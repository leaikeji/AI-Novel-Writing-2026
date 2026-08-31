"""One-shot VoiceGenerator stage for the Plan 40 neutral T3 fixture.

The process loads only VoiceGenerator.  It never loads the audio tokenizer and
publishes only a bounded safetensors token artifact for a later codec process.
"""

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
import time
import traceback
from typing import Sequence


SCHEMA = "vg40-t3-generator-probe/1"
TOKEN_SCHEMA = "vg40-audio-codes/1"
REVISION = re.compile(r"^[0-9a-f]{40}$")
FIXTURE = {
    "schema_version": "vg40-neutral-voice-input/1",
    "text": "雾散之后，我们沿着河岸慢慢往前走。",
    "instruction": "沉静、温暖、清晰的成年男声，语速从容，情绪克制。",
    "language": "Chinese",
    "quality": "high",
    "tokens": 55,
}
GENERATION_PARAMETERS = {
    "max_new_tokens": 256,
    # Text-channel tokens are protocol/control tokens for this voice-design
    # path.  Keep them deterministic; the documented VoiceGenerator diversity
    # controls remain on the 16 audio channels below.
    "text_temperature": 0.0,
    "text_top_p": 1.0,
    "text_top_k": 50,
    "audio_temperature": 1.5,
    "audio_top_p": 0.6,
    "audio_top_k": 50,
    "audio_repetition_penalty": 1.1,
}
REQUIRED_ENVIRONMENT = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "PYTORCH_ENABLE_MPS_FALLBACK": "0",
}


class T3ProbeError(RuntimeError):
    pass


def classify_error(error: BaseException) -> str:
    """Map runtime text to a bounded diagnostic family without retaining it."""

    message = str(error).lower()
    if "out of memory" in message or "failed to allocate" in message:
        return "memory_allocation"
    if "placeholder" in message:
        return "mps_placeholder_storage"
    if "not implemented for" in message:
        return "operator_not_implemented"
    if "does not support" in message or "not supported" in message:
        return "operator_not_supported"
    if "dtype" in message or "scalar type" in message:
        return "dtype_contract"
    if "out of bounds" in message or "index" in message:
        return "index_contract"
    if "nan" in message or "inf" in message or "probability" in message:
        return "non_finite_sampling"
    if "mps" in message or "metal" in message:
        return "mps_runtime"
    if isinstance(error, T3ProbeError):
        return "probe_contract"
    return "unclassified"


def fixture_sha256() -> str:
    payload = json.dumps(
        FIXTURE,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_probe_request(
    *,
    model_dir: Path,
    revision: str,
    result_path: Path,
    artifact_path: Path,
    seed: int,
) -> dict[str, object]:
    if REVISION.fullmatch(revision) is None:
        raise T3ProbeError("revision is not a fixed commit")
    if not 0 <= seed <= 2**63 - 1:
        raise T3ProbeError("seed is outside the fixed integer range")
    if model_dir.is_symlink() or not model_dir.is_dir():
        raise T3ProbeError("model directory must be a regular directory")
    if model_dir.absolute() != model_dir.resolve(strict=True):
        raise T3ProbeError("model directory traverses a symlink")
    required = ("config.json", "model.safetensors", "processing_moss_tts.py")
    if any(
        (model_dir / name).is_symlink() or not (model_dir / name).is_file()
        for name in required
    ):
        raise T3ProbeError("generator snapshot is incomplete")
    if result_path.parent != artifact_path.parent:
        raise T3ProbeError("result and artifact must share one run directory")
    for path in (result_path, artifact_path):
        if not path.is_absolute() or not path.parent.is_dir():
            raise T3ProbeError("output parent must be an existing absolute directory")
        if path.exists() or path.is_symlink():
            raise T3ProbeError("output path must not already exist")
    config = json.loads((model_dir / "config.json").read_text(encoding="utf-8"))
    n_vq = config.get("n_vq")
    if n_vq != 16 or config.get("audio_pad_code") != 1024:
        raise T3ProbeError("generator token contract differs from the frozen topology")
    return {
        "revision": revision,
        "model_type": config.get("model_type"),
        "n_vq": n_vq,
        "audio_pad_code": 1024,
        "seed": seed,
        "fixture_sha256": fixture_sha256(),
    }


def run_probe(
    *,
    model_dir: Path,
    revision: str,
    result_path: Path,
    artifact_path: Path,
    seed: int,
    mps_memory_fraction: float,
) -> int:
    identity: dict[str, object] = {"revision": revision, "seed": seed}
    phase = "validate_request"
    try:
        identity = validate_probe_request(
            model_dir=model_dir,
            revision=revision,
            result_path=result_path,
            artifact_path=artifact_path,
            seed=seed,
        )
        _validate_environment()
        if not 0.05 <= mps_memory_fraction <= 1.0:
            raise T3ProbeError("MPS memory fraction is outside the spike bound")

        phase = "import_runtime"
        import torch
        from safetensors.torch import save_file
        from transformers import AutoConfig, AutoModel, AutoTokenizer
        from transformers.dynamic_module_utils import get_class_from_dynamic_module
        from mps_generation_adapter import SCHEMA as ADAPTER_SCHEMA
        from mps_generation_adapter import generate_batch_one

        if not torch.backends.mps.is_built() or not torch.backends.mps.is_available():
            raise T3ProbeError("MPS is unavailable")
        torch.set_grad_enabled(False)
        torch.manual_seed(seed)
        torch.mps.set_per_process_memory_fraction(mps_memory_fraction)

        phase = "prepare_input"
        config = AutoConfig.from_pretrained(
            model_dir,
            trust_remote_code=True,
            local_files_only=True,
        )
        tokenizer = AutoTokenizer.from_pretrained(
            model_dir,
            trust_remote_code=True,
            local_files_only=True,
        )
        processor_class = get_class_from_dynamic_module(
            "processing_moss_tts.MossTTSDelayProcessor",
            str(model_dir),
            local_files_only=True,
        )
        processor = processor_class(
            tokenizer=tokenizer,
            audio_tokenizer=None,
            model_config=config,
            normalize_inputs=True,
        )
        user_message = processor.build_user_message(
            text=FIXTURE["text"],
            instruction=FIXTURE["instruction"],
            tokens=FIXTURE["tokens"],
            quality=FIXTURE["quality"],
            language=FIXTURE["language"],
            normalize=True,
        )
        inputs = processor(
            [user_message],
            mode="generation",
            n_vq=identity["n_vq"],
        ).to("mps")

        phase = "load_generator"
        load_started = time.monotonic()
        model = AutoModel.from_pretrained(
            model_dir,
            trust_remote_code=True,
            local_files_only=True,
            dtype=torch.bfloat16,
            low_cpu_mem_usage=True,
            device_map={"": "mps"},
            attn_implementation="sdpa",
        ).eval()
        torch.mps.synchronize()
        load_seconds = time.monotonic() - load_started

        phase = "generate_tokens"
        generation_started = time.monotonic()
        adapter_result = generate_batch_one(model, **inputs, **GENERATION_PARAMETERS)
        torch.mps.synchronize()
        generation_seconds = time.monotonic() - generation_started
        if not adapter_result.completed:
            raise T3ProbeError("generator reached the token bound before natural audio completion")
        generated = adapter_result.output
        phase = "extract_tokens"
        if not isinstance(generated, list) or len(generated) != 1:
            raise T3ProbeError("generator returned an invalid batch")
        start_length, generation_ids = generated[0]
        delayed_codes = generation_ids[:, 1:].detach().to("cpu", dtype=torch.long)
        codes = processor.apply_de_delay_pattern(delayed_codes)
        non_pad = ~(codes == int(identity["audio_pad_code"])).all(dim=1)
        indices = torch.nonzero(non_pad).squeeze(1)
        if indices.numel() == 0:
            raise T3ProbeError("generator returned no audio codes")
        breaks = torch.where(indices[1:] != indices[:-1] + 1)[0] + 1
        groups = [indices] if breaks.numel() == 0 else list(torch.split(indices, breaks.tolist()))
        segments = [codes[group].contiguous() for group in groups if group.numel()]
        codes = max(segments, key=lambda value: int(value.shape[0]))
        if int(start_length) != 0:
            if int(start_length) >= int(codes.shape[0]):
                raise T3ProbeError("generation prefix consumed the only audio segment")
            codes = codes[int(start_length) :].contiguous()
        if (
            codes.ndim != 2
            or int(codes.shape[1]) != int(identity["n_vq"])
            or not 25 <= int(codes.shape[0]) <= 75
            or int(codes.min().item()) < 0
            or int(codes.max().item()) >= int(identity["audio_pad_code"])
        ):
            raise T3ProbeError("generated audio codes violate the T3 bound")
        token_shape = [int(value) for value in codes.shape]

        phase = "publish_tokens"
        temporary_artifact = artifact_path.with_name(
            f".{artifact_path.name}.{secrets.token_hex(4)}.tmp"
        )
        save_file(
            {"audio_codes": codes},
            temporary_artifact,
            metadata={
                "schema_version": TOKEN_SCHEMA,
                "generator_revision": revision,
                "fixture_sha256": str(identity["fixture_sha256"]),
                "seed": str(seed),
            },
        )
        with temporary_artifact.open("rb+") as source:
            os.fsync(source.fileno())
        if artifact_path.exists() or artifact_path.is_symlink():
            raise FileExistsError("token artifact already exists")
        os.replace(temporary_artifact, artifact_path)
        artifact_sha256 = _sha256(artifact_path)
        artifact_bytes = artifact_path.stat().st_size
        generation_completed = adapter_result.completed
        assistant_completed = adapter_result.assistant_completed
        generation_steps = adapter_result.generation_steps

        phase = "release_generator"
        mps_allocated = torch.mps.current_allocated_memory()
        mps_driver = torch.mps.driver_allocated_memory()
        del adapter_result, generated, generation_ids, delayed_codes, codes, inputs, model
        gc.collect()
        torch.mps.empty_cache()
        torch.mps.synchronize()
        allocated_after_release = torch.mps.current_allocated_memory()
        if allocated_after_release != 0:
            raise T3ProbeError("MPS allocation did not return to zero")
        payload = {
            "schema_version": SCHEMA,
            "passed": True,
            **identity,
            "token_schema_version": TOKEN_SCHEMA,
            "token_shape": token_shape,
            "token_dtype": "int64",
            "artifact_bytes": artifact_bytes,
            "artifact_sha256": artifact_sha256,
            "generation_parameters": GENERATION_PARAMETERS,
            "generation_adapter_schema": ADAPTER_SCHEMA,
            "generation_completed": generation_completed,
            "assistant_completed": assistant_completed,
            "generation_steps": generation_steps,
            "mps_memory_fraction": mps_memory_fraction,
            "mps_current_allocated_bytes": mps_allocated,
            "mps_driver_allocated_bytes": mps_driver,
            "mps_allocated_after_release_bytes": allocated_after_release,
            "load_seconds": load_seconds,
            "generation_seconds": generation_seconds,
            "observed_at": datetime.now(timezone.utc).isoformat(),
        }
        _write_result(result_path, payload)
        return 0
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
            raise T3ProbeError("offline or fallback environment is not frozen")


def _write_result(path: Path, payload: dict[str, object]) -> None:
    encoded = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")
    if len(encoded) > 64 * 1024:
        raise T3ProbeError("probe result exceeded the fixed bound")
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
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=104729)
    parser.add_argument("--mps-memory-fraction", type=float, default=0.55)
    arguments = parser.parse_args(argv)
    return run_probe(
        model_dir=arguments.model_dir,
        revision=arguments.revision,
        result_path=arguments.result,
        artifact_path=arguments.artifact,
        seed=arguments.seed,
        mps_memory_fraction=arguments.mps_memory_fraction,
    )


if __name__ == "__main__":
    raise SystemExit(main())
