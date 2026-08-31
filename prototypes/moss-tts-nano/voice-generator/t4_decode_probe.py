"""One-shot Audio Tokenizer decode stage for Plan 40 T4."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gc
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import time
import traceback
from typing import Sequence


SCHEMA = "vg40-t4-codec-probe/1"
TOKEN_SCHEMA = "vg40-audio-codes/1"
AUDIO_SCHEMA = "vg40-audio-inspection/1"
REVISION = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_ENVIRONMENT = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "PYTORCH_ENABLE_MPS_FALLBACK": "0",
}


class T4ProbeError(RuntimeError):
    pass


def classify_error(error: BaseException) -> str:
    message = str(error).lower()
    if "out of memory" in message or "failed to allocate" in message:
        return "memory_allocation"
    if "placeholder" in message:
        return "mps_placeholder_storage"
    if "not implemented for" in message:
        return "operator_not_implemented"
    if "does not support" in message or "not supported" in message:
        return "operator_not_supported"
    if "dtype" in message or "scalar type" in message or "bias type" in message:
        return "dtype_contract"
    if "padding" in message or "kernel size" in message or "calculated padded" in message:
        return "convolution_shape_contract"
    if "mps" in message or "metal" in message:
        return "mps_runtime"
    if isinstance(error, T4ProbeError):
        return "probe_contract"
    return "unclassified"


def validate_probe_request(
    *,
    codec_dir: Path,
    codec_revision: str,
    artifact_path: Path,
    artifact_sha256: str,
    result_path: Path,
    output_wav: Path,
) -> dict[str, object]:
    if REVISION.fullmatch(codec_revision) is None:
        raise T4ProbeError("codec revision is not a fixed commit")
    if SHA256.fullmatch(artifact_sha256) is None:
        raise T4ProbeError("token artifact digest is invalid")
    if codec_dir.is_symlink() or not codec_dir.is_dir():
        raise T4ProbeError("codec directory must be regular")
    if codec_dir.absolute() != codec_dir.resolve(strict=True):
        raise T4ProbeError("codec directory traverses a symlink")
    required = (
        "config.json",
        "model.safetensors.index.json",
        "model-00001-of-00002.safetensors",
        "model-00002-of-00002.safetensors",
    )
    if any(
        (codec_dir / name).is_symlink() or not (codec_dir / name).is_file()
        for name in required
    ):
        raise T4ProbeError("codec snapshot is incomplete")
    if artifact_path.is_symlink() or not artifact_path.is_file():
        raise T4ProbeError("token artifact must be a regular file")
    if _sha256(artifact_path) != artifact_sha256:
        raise T4ProbeError("token artifact digest changed")
    if result_path.parent != output_wav.parent:
        raise T4ProbeError("result and WAV must share one run directory")
    for path in (result_path, output_wav):
        if not path.is_absolute() or not path.parent.is_dir():
            raise T4ProbeError("output parent must be an existing absolute directory")
        if path.exists() or path.is_symlink():
            raise T4ProbeError("output path must not already exist")
    config = json.loads((codec_dir / "config.json").read_text(encoding="utf-8"))
    if config.get("sampling_rate") != 24000 or config.get("downsample_rate") != 1920:
        raise T4ProbeError("codec timing contract differs from the frozen topology")
    return {
        "codec_revision": codec_revision,
        "model_type": config.get("model_type"),
        "native_sampling_rate": 24000,
        "downsample_rate": 1920,
        "artifact_sha256": artifact_sha256,
    }


def inspect_waveform(samples: object, *, sampling_rate: int) -> dict[str, object]:
    import numpy as np

    values = np.asarray(samples, dtype=np.float32)
    if values.ndim == 1:
        values = values[:, None]
    finite = np.isfinite(values)
    non_finite = int(values.size - int(finite.sum()))
    safe = np.where(finite, values, 0.0)
    peak = float(np.max(np.abs(safe))) if safe.size else 0.0
    rms = float(np.sqrt(np.mean(np.square(safe), dtype=np.float64))) if safe.size else 0.0
    rms_dbfs = 20.0 * math.log10(max(rms, 1e-12))
    dc_offset = float(np.mean(safe, dtype=np.float64)) if safe.size else 0.0
    clipped_count = int(np.count_nonzero(np.abs(safe) >= 0.999))
    clipped_fraction = clipped_count / safe.size if safe.size else 1.0
    mono_peak = np.max(np.abs(safe), axis=1) if len(safe) else np.zeros(0)
    audible = np.flatnonzero(mono_peak >= 10 ** (-50 / 20))
    if audible.size:
        leading = int(audible[0]) / sampling_rate
        trailing = int(len(mono_peak) - audible[-1] - 1) / sampling_rate
    else:
        leading = len(mono_peak) / sampling_rate if sampling_rate else 0.0
        trailing = leading
    return {
        "frame_count": int(values.shape[0]),
        "channels": int(values.shape[1]),
        "sampling_rate": sampling_rate,
        "duration_seconds": float(values.shape[0] / sampling_rate),
        "peak": peak,
        "rms_dbfs": rms_dbfs,
        "dc_offset": dc_offset,
        "clipped_count": clipped_count,
        "clipped_fraction": clipped_fraction,
        "non_finite_sample_count": non_finite,
        "leading_silence_seconds": leading,
        "trailing_silence_seconds": trailing,
    }


def run_probe(
    *,
    codec_dir: Path,
    codec_revision: str,
    artifact_path: Path,
    artifact_sha256: str,
    result_path: Path,
    output_wav: Path,
    mps_memory_fraction: float,
) -> int:
    identity: dict[str, object] = {"codec_revision": codec_revision}
    phase = "validate_request"
    try:
        identity = validate_probe_request(
            codec_dir=codec_dir,
            codec_revision=codec_revision,
            artifact_path=artifact_path,
            artifact_sha256=artifact_sha256,
            result_path=result_path,
            output_wav=output_wav,
        )
        _validate_environment()
        if not 0.05 <= mps_memory_fraction <= 1.0:
            raise T4ProbeError("MPS memory fraction is outside the spike bound")

        phase = "import_runtime"
        import numpy as np
        import soundfile as sf
        import torch
        import torchaudio
        from safetensors import safe_open
        from transformers import AutoModel
        from mps_codec_adapter import SCHEMA as CODEC_ADAPTER_SCHEMA
        from mps_codec_adapter import decode_batch_one

        with safe_open(str(artifact_path), framework="pt", device="cpu") as source:
            metadata = source.metadata() or {}
            if metadata.get("schema_version") != TOKEN_SCHEMA:
                raise T4ProbeError("token schema identity is invalid")
            codes = source.get_tensor("audio_codes")
        if (
            codes.dtype != torch.int64
            or codes.ndim != 2
            or int(codes.shape[1]) != 16
            or not 25 <= int(codes.shape[0]) <= 75
            or int(codes.min().item()) < 0
            or int(codes.max().item()) >= 1024
        ):
            raise T4ProbeError("token tensor violates the frozen contract")
        token_shape = [int(value) for value in codes.shape]

        if not torch.backends.mps.is_built() or not torch.backends.mps.is_available():
            raise T4ProbeError("MPS is unavailable")
        torch.set_grad_enabled(False)
        torch.mps.set_per_process_memory_fraction(mps_memory_fraction)
        phase = "load_codec"
        load_started = time.monotonic()
        codec = AutoModel.from_pretrained(
            codec_dir,
            trust_remote_code=True,
            local_files_only=True,
            dtype=torch.bfloat16,
            low_cpu_mem_usage=True,
            device_map={"": "mps"},
        ).eval()
        torch.mps.synchronize()
        load_seconds = time.monotonic() - load_started

        phase = "decode_audio"
        audio_codes = codes.transpose(0, 1).unsqueeze(1).contiguous().to("mps")
        padding_mask = torch.ones(
            (1, int(codes.shape[0])), dtype=torch.bool, device="mps"
        )
        decode_started = time.monotonic()
        decoded_audio, decoded_lengths = decode_batch_one(
            codec,
            audio_codes,
            padding_mask.sum(dim=-1).long(),
        )
        torch.mps.synchronize()
        decode_seconds = time.monotonic() - decode_started
        native_length = int(decoded_lengths[0].item())
        if native_length <= 0:
            raise T4ProbeError("codec returned a zero-length waveform")
        native = (
            decoded_audio[0, 0, :native_length]
            .detach()
            .to("cpu", dtype=torch.float32)
            .contiguous()
        )
        native_inspection = inspect_waveform(native.numpy(), sampling_rate=24000)
        mps_allocated = torch.mps.current_allocated_memory()
        mps_driver = torch.mps.driver_allocated_memory()

        phase = "release_codec"
        del decoded_audio, decoded_lengths, audio_codes, padding_mask, codec
        gc.collect()
        torch.mps.empty_cache()
        torch.mps.synchronize()
        allocated_after_release = torch.mps.current_allocated_memory()
        if allocated_after_release != 0:
            raise T4ProbeError("MPS allocation did not return to zero")

        phase = "transcode_audio"
        converted = torchaudio.functional.resample(native, 24000, 48000)
        stereo = converted.unsqueeze(1).repeat(1, 2).numpy()
        output_inspection = inspect_waveform(stereo, sampling_rate=48000)
        machine_valid = (
            3.0 <= float(output_inspection["duration_seconds"]) <= 5.0
            and int(output_inspection["channels"]) == 2
            and int(output_inspection["non_finite_sample_count"]) == 0
            and float(output_inspection["rms_dbfs"]) > -55.0
            and float(output_inspection["clipped_fraction"]) <= 0.001
            and abs(float(output_inspection["dc_offset"])) < 0.05
        )
        temporary_wav = output_wav.with_name(
            f".{output_wav.name}.{secrets.token_hex(4)}.tmp.wav"
        )
        sf.write(temporary_wav, np.clip(stereo, -1.0, 1.0), 48000, subtype="PCM_16")
        with temporary_wav.open("rb+") as source:
            os.fsync(source.fileno())
        info = sf.info(temporary_wav)
        if (
            info.format != "WAV"
            or info.subtype != "PCM_16"
            or info.samplerate != 48000
            or info.channels != 2
            or info.frames != int(output_inspection["frame_count"])
        ):
            raise T4ProbeError("written WAV identity is invalid")
        if output_wav.exists() or output_wav.is_symlink():
            raise FileExistsError("WAV output already exists")
        os.replace(temporary_wav, output_wav)
        wav_sha256 = _sha256(output_wav)
        wav_bytes = output_wav.stat().st_size

        payload = {
            "schema_version": SCHEMA,
            "audio_schema_version": AUDIO_SCHEMA,
            "passed": machine_valid,
            **identity,
            "token_schema_version": TOKEN_SCHEMA,
            "token_shape": token_shape,
            "token_dtype": "int64",
            "native_audio": native_inspection,
            "output_audio": {
                **output_inspection,
                "container": "WAV",
                "codec": "PCM_S16LE",
                "sample_width_bytes": 2,
                "bytes": wav_bytes,
                "sha256": wav_sha256,
            },
            "processing_policy": "vg40-24k-mono-to-48k-stereo-pcm16/1",
            "codec_adapter_schema": CODEC_ADAPTER_SCHEMA,
            "runtime_versions": {
                "torch": torch.__version__,
                "torchaudio": torchaudio.__version__,
                "soundfile": sf.__version__,
            },
            "machine_valid": machine_valid,
            "mps_memory_fraction": mps_memory_fraction,
            "mps_current_allocated_bytes": mps_allocated,
            "mps_driver_allocated_bytes": mps_driver,
            "mps_allocated_after_release_bytes": allocated_after_release,
            "load_seconds": load_seconds,
            "decode_seconds": decode_seconds,
            "observed_at": datetime.now(timezone.utc).isoformat(),
        }
        _write_result(result_path, payload)
        return 0 if machine_valid else 1
    except BaseException as error:
        extracted = traceback.extract_tb(error.__traceback__)
        origin = None
        if extracted:
            frame = extracted[-1]
            origin = {
                "module": Path(frame.filename).name,
                "function": frame.name,
                "line": frame.lineno,
            }
        payload = {
            "schema_version": SCHEMA,
            "passed": False,
            **identity,
            "error_type": type(error).__name__,
            "error_family": classify_error(error),
            "error_phase": phase,
            "error_origin": origin,
            "observed_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            _write_result(result_path, payload)
        except BaseException:
            pass
        return 1


def _validate_environment() -> None:
    for name, expected in REQUIRED_ENVIRONMENT.items():
        if os.environ.get(name) != expected:
            raise T4ProbeError("offline or fallback environment is not frozen")


def _write_result(path: Path, payload: dict[str, object]) -> None:
    encoded = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")
    if len(encoded) > 64 * 1024:
        raise T4ProbeError("probe result exceeded the fixed bound")
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(encoded)
            target.flush()
            os.fsync(target.fileno())
        if path.exists() or path.is_symlink():
            raise FileExistsError("probe result already exists")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codec-dir", type=Path, required=True)
    parser.add_argument("--codec-revision", required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--artifact-sha256", required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--output-wav", type=Path, required=True)
    parser.add_argument("--mps-memory-fraction", type=float, default=0.75)
    arguments = parser.parse_args(argv)
    return run_probe(
        codec_dir=arguments.codec_dir,
        codec_revision=arguments.codec_revision,
        artifact_path=arguments.artifact,
        artifact_sha256=arguments.artifact_sha256,
        result_path=arguments.result,
        output_wav=arguments.output_wav,
        mps_memory_fraction=arguments.mps_memory_fraction,
    )


if __name__ == "__main__":
    raise SystemExit(main())
