"""One-shot generator or codec worker used only by the native product host."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gc
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
from typing import Sequence

from backend.narration.voice_generator_runtime import (
    CODEC_REVISION,
    EXPECTED_RUNTIME_FINGERPRINT,
    VOICE_GENERATOR_REVISION,
    VoiceGeneratorRuntimeError,
    inspect_generated_wav,
)
from scripts.tts.voice_generator.host_server import parse_generation_request
from scripts.tts.voice_generator.product_adapters import (
    CODEC_ADAPTER_SCHEMA,
    GENERATION_ADAPTER_SCHEMA,
    decode_batch_one,
    generate_batch_one,
)


GENERATOR_RESULT_SCHEMA = "voice-generator-product-stage/1"
CODEC_RESULT_SCHEMA = "voice-generator-product-codec/1"
TOKEN_SCHEMA = "voice-generator-audio-codes/1"
MIN_GENERATED_AUDIO_FRAMES = 25
# The product call requests 256 new delayed tokens. With 16 audio codebooks,
# at most 16 boundary steps belong to the delay pattern rather than audio.
MAX_GENERATED_AUDIO_FRAMES = 256 - 16
REQUIRED_ENVIRONMENT = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "PYTORCH_ENABLE_MPS_FALLBACK": "0",
}
PREVIEW_TEXT = {
    "zh-CN": ("雾散之后，我们沿着河岸慢慢往前走。", "Chinese"),
    "en": ("After the fog lifted, we walked slowly along the river.", "English"),
    "ja-JP": ("霧が晴れたあと、私たちは川沿いをゆっくり歩いた。", "Japanese"),
}


def run_generator(run_directory: Path, model_directory: Path) -> int:
    result_path = run_directory / "generator-result.json"
    token_path = run_directory / "tokens.safetensors"
    phase = "validate"
    failure_diagnostics: dict[str, object] = {}
    try:
        request = _load_request(run_directory)
        _validate_model_directory(
            model_directory,
            ("config.json", "model.safetensors", "processing_moss_tts.py"),
        )
        _validate_environment()
        import torch
        from safetensors.torch import save_file
        from transformers import AutoConfig, AutoModel, AutoTokenizer
        from transformers.dynamic_module_utils import get_class_from_dynamic_module

        if not torch.backends.mps.is_built() or not torch.backends.mps.is_available():
            raise RuntimeError("MPS_UNAVAILABLE")
        torch.set_grad_enabled(False)
        torch.manual_seed(request.seed)
        torch.mps.set_per_process_memory_fraction(0.65)
        phase = "prepare"
        config = AutoConfig.from_pretrained(
            model_directory, trust_remote_code=True, local_files_only=True
        )
        if config.n_vq != 16 or config.audio_pad_code != 1024:
            raise RuntimeError("MODEL_CONTRACT_MISMATCH")
        tokenizer = AutoTokenizer.from_pretrained(
            model_directory, trust_remote_code=True, local_files_only=True
        )
        processor_class = get_class_from_dynamic_module(
            "processing_moss_tts.MossTTSDelayProcessor",
            str(model_directory),
            local_files_only=True,
        )
        processor = processor_class(
            tokenizer=tokenizer,
            audio_tokenizer=None,
            model_config=config,
            normalize_inputs=True,
        )
        text, language = PREVIEW_TEXT[request.language]
        message = processor.build_user_message(
            text=text,
            instruction=request.instruction,
            tokens=55,
            quality="high",
            language=language,
            normalize=True,
        )
        inputs = processor([message], mode="generation", n_vq=16).to("mps")
        phase = "load"
        model = AutoModel.from_pretrained(
            model_directory,
            trust_remote_code=True,
            local_files_only=True,
            dtype=torch.bfloat16,
            low_cpu_mem_usage=True,
            device_map={"": "mps"},
            attn_implementation="sdpa",
        ).eval()
        torch.mps.synchronize()
        phase = "generate"
        parameters = request.audio_parameters
        generated = generate_batch_one(
            model,
            **inputs,
            max_new_tokens=256,
            text_temperature=0.0,
            text_top_p=1.0,
            text_top_k=50,
            audio_temperature=parameters.audio_temperature_milli / 1_000,
            audio_top_p=parameters.audio_top_p_milli / 1_000,
            audio_top_k=parameters.audio_top_k,
            audio_repetition_penalty=parameters.audio_repetition_penalty_milli / 1_000,
        )
        torch.mps.synchronize()
        if not generated.completed or not isinstance(generated.output, list) or len(generated.output) != 1:
            raise RuntimeError("GENERATION_INCOMPLETE")
        start_length, generation_ids = generated.output[0]
        failure_diagnostics.update(
            {
                "generation_completed": generated.completed,
                "generation_steps": generated.generation_steps,
                "start_length": int(start_length),
                "generation_shape": [int(value) for value in generation_ids.shape],
            }
        )
        delayed = generation_ids[:, 1:].detach().to("cpu", dtype=torch.long)
        codes = processor.apply_de_delay_pattern(delayed)
        non_pad = ~(codes == 1024).all(dim=1)
        indices = torch.nonzero(non_pad).squeeze(1)
        if indices.numel() == 0:
            raise RuntimeError("GENERATION_EMPTY")
        breaks = torch.where(indices[1:] != indices[:-1] + 1)[0] + 1
        groups = [indices] if breaks.numel() == 0 else list(torch.split(indices, breaks.tolist()))
        codes = max((codes[group].contiguous() for group in groups if group.numel()), key=lambda item: int(item.shape[0]))
        failure_diagnostics["segment_shape_before_prefix"] = [
            int(value) for value in codes.shape
        ]
        if int(start_length):
            codes = codes[int(start_length) :].contiguous()
        failure_diagnostics.update(
            {
                "token_shape": [int(value) for value in codes.shape],
                "token_min": int(codes.min().item()) if codes.numel() else None,
                "token_max": int(codes.max().item()) if codes.numel() else None,
            }
        )
        if (
            codes.dtype != torch.int64
            or codes.ndim != 2
            or int(codes.shape[1]) != 16
            or not MIN_GENERATED_AUDIO_FRAMES
            <= int(codes.shape[0])
            <= MAX_GENERATED_AUDIO_FRAMES
            or int(codes.min().item()) < 0
            or int(codes.max().item()) >= 1024
        ):
            raise RuntimeError("TOKEN_CONTRACT_MISMATCH")
        temporary = token_path.with_name(f".{token_path.name}.{secrets.token_hex(8)}.tmp")
        save_file(
            {"audio_codes": codes},
            temporary,
            metadata={
                "schema_version": TOKEN_SCHEMA,
                "request_id": str(request.request_id),
                "request_digest": request.request_digest,
                "generator_revision": VOICE_GENERATOR_REVISION,
                "runtime_fingerprint": EXPECTED_RUNTIME_FINGERPRINT,
            },
        )
        _fsync_replace(temporary, token_path)
        token_digest = _sha256(token_path)
        token_bytes = token_path.stat().st_size
        token_shape = [int(value) for value in codes.shape]
        phase = "release"
        del generated, generation_ids, delayed, codes, inputs, model, processor
        gc.collect()
        torch.mps.empty_cache()
        torch.mps.synchronize()
        if torch.mps.current_allocated_memory() != 0:
            raise RuntimeError("MPS_RELEASE_FAILED")
        _write_result(
            result_path,
            {
                "schema_version": GENERATOR_RESULT_SCHEMA,
                "passed": True,
                "request_id": str(request.request_id),
                "request_digest": request.request_digest,
                "revision": VOICE_GENERATOR_REVISION,
                "runtime_fingerprint": EXPECTED_RUNTIME_FINGERPRINT,
                "adapter_schema": GENERATION_ADAPTER_SCHEMA,
                "token_schema": TOKEN_SCHEMA,
                "token_sha256": token_digest,
                "token_bytes": token_bytes,
                "token_shape": token_shape,
                "observed_at": _now(),
            },
        )
        return 0
    except BaseException as error:
        _write_failure(
            result_path,
            phase,
            error,
            diagnostics=failure_diagnostics,
        )
        return 1


def run_codec(run_directory: Path, model_directory: Path) -> int:
    result_path = run_directory / "codec-result.json"
    token_path = run_directory / "tokens.safetensors"
    output_path = run_directory / ".backend-audio.wav"
    phase = "validate"
    try:
        request = _load_request(run_directory)
        _validate_model_directory(
            model_directory,
            (
                "config.json",
                "model.safetensors.index.json",
                "model-00001-of-00002.safetensors",
                "model-00002-of-00002.safetensors",
            ),
        )
        generator = _read_json(run_directory / "generator-result.json")
        if (
            generator.get("schema_version") != GENERATOR_RESULT_SCHEMA
            or generator.get("passed") is not True
            or generator.get("request_id") != str(request.request_id)
            or generator.get("request_digest") != request.request_digest
            or generator.get("revision") != VOICE_GENERATOR_REVISION
            or generator.get("adapter_schema") != GENERATION_ADAPTER_SCHEMA
            or generator.get("token_sha256") != _sha256(token_path)
        ):
            raise RuntimeError("GENERATOR_EVIDENCE_MISMATCH")
        _validate_environment()
        import numpy as np
        import soundfile as soundfile
        import torch
        import torchaudio
        from safetensors import safe_open
        from transformers import AutoModel

        if not torch.backends.mps.is_built() or not torch.backends.mps.is_available():
            raise RuntimeError("MPS_UNAVAILABLE")
        with safe_open(str(token_path), framework="pt", device="cpu") as source:
            metadata = source.metadata() or {}
            if (
                metadata.get("schema_version") != TOKEN_SCHEMA
                or metadata.get("request_id") != str(request.request_id)
                or metadata.get("request_digest") != request.request_digest
            ):
                raise RuntimeError("TOKEN_METADATA_MISMATCH")
            codes = source.get_tensor("audio_codes")
        if (
            codes.dtype != torch.int64
            or codes.ndim != 2
            or tuple(codes.shape)[1] != 16
            or not MIN_GENERATED_AUDIO_FRAMES
            <= int(codes.shape[0])
            <= MAX_GENERATED_AUDIO_FRAMES
            or int(codes.min().item()) < 0
            or int(codes.max().item()) >= 1024
        ):
            raise RuntimeError("TOKEN_CONTRACT_MISMATCH")
        torch.set_grad_enabled(False)
        torch.mps.set_per_process_memory_fraction(0.75)
        phase = "load"
        codec = AutoModel.from_pretrained(
            model_directory,
            trust_remote_code=True,
            local_files_only=True,
            dtype=torch.bfloat16,
            low_cpu_mem_usage=True,
            device_map={"": "mps"},
        ).eval()
        torch.mps.synchronize()
        phase = "decode"
        audio_codes = codes.transpose(0, 1).unsqueeze(1).contiguous().to("mps")
        lengths = torch.tensor([int(codes.shape[0])], dtype=torch.long, device="mps")
        decoded, decoded_lengths = decode_batch_one(codec, audio_codes, lengths)
        torch.mps.synchronize()
        native_length = int(decoded_lengths[0].item())
        native = decoded[0, 0, :native_length].detach().to("cpu", dtype=torch.float32)
        phase = "release"
        del decoded, decoded_lengths, audio_codes, lengths, codec, codes
        gc.collect()
        torch.mps.empty_cache()
        torch.mps.synchronize()
        if torch.mps.current_allocated_memory() != 0:
            raise RuntimeError("MPS_RELEASE_FAILED")
        phase = "encode"
        converted = torchaudio.functional.resample(native, 24_000, 48_000)
        stereo = converted.unsqueeze(1).repeat(1, 2).numpy()
        temporary = output_path.with_name(f".{output_path.name}.{secrets.token_hex(8)}.tmp.wav")
        soundfile.write(temporary, np.clip(stereo, -1.0, 1.0), 48_000, subtype="PCM_16")
        _fsync_replace(temporary, output_path)
        payload = output_path.read_bytes()
        metrics = inspect_generated_wav(payload)
        _write_result(
            result_path,
            {
                "schema_version": CODEC_RESULT_SCHEMA,
                "passed": True,
                "request_id": str(request.request_id),
                "request_digest": request.request_digest,
                "revision": CODEC_REVISION,
                "runtime_fingerprint": EXPECTED_RUNTIME_FINGERPRINT,
                "adapter_schema": CODEC_ADAPTER_SCHEMA,
                "token_sha256": generator["token_sha256"],
                "audio_sha256": hashlib.sha256(payload).hexdigest(),
                "audio_size_bytes": len(payload),
                "audio_metrics": dict(metrics.public_payload()),
                "observed_at": _now(),
            },
        )
        return 0
    except BaseException as error:
        _write_failure(result_path, phase, error)
        return 1


def _load_request(run_directory: Path):
    value = _read_json(run_directory / "request.json")
    request = value.get("request")
    return parse_generation_request(request)


def _validate_model_directory(path: Path, required: tuple[str, ...]) -> None:
    if not path.is_absolute() or path.is_symlink() or not path.is_dir() or path.resolve(strict=True) != path:
        raise RuntimeError("MODEL_DIRECTORY_INVALID")
    if any((path / name).is_symlink() or not (path / name).is_file() for name in required):
        raise RuntimeError("MODEL_SNAPSHOT_INCOMPLETE")


def _validate_environment() -> None:
    if any(os.environ.get(name) != expected for name, expected in REQUIRED_ENVIRONMENT.items()):
        raise RuntimeError("OFFLINE_ENVIRONMENT_INVALID")


def _read_json(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file() or not 1 <= path.stat().st_size <= 64 * 1024:
        raise RuntimeError("INPUT_MANIFEST_INVALID")
    value = json.loads(path.read_text(encoding="utf-8"))
    if type(value) is not dict:
        raise RuntimeError("INPUT_MANIFEST_INVALID")
    return value


def _write_failure(
    path: Path,
    phase: str,
    error: BaseException,
    *,
    diagnostics: dict[str, object] | None = None,
) -> None:
    if isinstance(error, VoiceGeneratorRuntimeError):
        code = error.code
    elif isinstance(error, RuntimeError) and str(error).isupper():
        code = str(error)
    elif isinstance(error, (ModuleNotFoundError, ImportError)):
        code = "DEPENDENCY_IMPORT_FAILED"
    elif isinstance(error, AttributeError):
        code = "RUNTIME_API_MISMATCH"
    elif isinstance(error, OSError):
        code = "RUNTIME_IO_FAILED"
    elif isinstance(error, (TypeError, ValueError)):
        code = "RUNTIME_VALUE_INVALID"
    else:
        code = "WORKER_FAILURE"
    missing_module = (
        error.name
        if isinstance(error, ModuleNotFoundError)
        and isinstance(error.name, str)
        and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]{0,159}", error.name)
        else None
    )
    try:
        _write_result(
            path,
            {
                "schema_version": "voice-generator-product-worker-failure/1",
                "passed": False,
                "phase": phase,
                "failure_code": code,
                # Class names are bounded diagnostic metadata; exception text,
                # instructions and paths never enter durable worker evidence.
                "exception_class": type(error).__name__[:80],
                "missing_module": missing_module,
                "diagnostics": dict(diagnostics or {}),
                "observed_at": _now(),
            },
        )
    except BaseException:
        pass


def _write_result(path: Path, value: dict[str, object]) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError("worker result already exists")
    payload = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    with os.fdopen(descriptor, "wb") as target:
        target.write(payload)
        target.flush()
        os.fsync(target.fileno())
    os.replace(temporary, path)


def _fsync_replace(temporary: Path, final: Path) -> None:
    temporary.chmod(0o600)
    with temporary.open("rb+") as target:
        os.fsync(target.fileno())
    if final.exists() or final.is_symlink():
        raise FileExistsError("worker output already exists")
    os.replace(temporary, final)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("generator", "codec"))
    parser.add_argument("--run-directory", type=Path, required=True)
    parser.add_argument("--model-directory", type=Path, required=True)
    parser.add_argument("--host-pid", type=int, required=True)
    arguments = parser.parse_args(argv)
    _start_parent_watchdog(arguments.host_pid)
    if arguments.stage == "generator":
        return run_generator(arguments.run_directory, arguments.model_directory)
    return run_codec(arguments.run_directory, arguments.model_directory)


def _start_parent_watchdog(expected_parent_pid: int) -> None:
    if expected_parent_pid <= 1 or os.getppid() != expected_parent_pid:
        raise RuntimeError("HOST_PARENT_IDENTITY_INVALID")

    def monitor() -> None:
        while True:
            time.sleep(1.0)
            if os.getppid() != expected_parent_pid:
                os._exit(75)

    threading.Thread(
        target=monitor,
        name="voice-generator-parent-watchdog",
        daemon=True,
    ).start()


if __name__ == "__main__":
    raise SystemExit(main())
