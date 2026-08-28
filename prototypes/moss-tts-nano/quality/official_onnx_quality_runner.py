#!/usr/bin/env python3
"""Offline adapter from the T0-C runner contract to pinned OnnxTtsRuntime.

This module does not contain or download upstream source/model assets.  The
driver supplies both directories explicitly after their hashes are verified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import sys
import tempfile
import time
from typing import Any


REQUEST_SCHEMA = "moss-tts-quality-runner-request/1.0"
RESPONSE_SCHEMA = "moss-tts-quality-runner-response/1.0"
REQUIRED_SOURCE_FILES = (
    "onnx_tts_runtime.py",
    "ort_cpu_runtime.py",
    "text_normalization_pipeline.py",
)


class RunnerInputError(RuntimeError):
    """A request/source/model contract error safe to report by category only."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def peak_rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def require_path(value: object, label: str, *, directory: bool = False) -> Path:
    if not isinstance(value, str) or not value:
        raise RunnerInputError(f"{label} is missing")
    raw_path = Path(value)
    if raw_path.is_symlink():
        raise RunnerInputError(f"{label} must not be a symbolic link")
    path = raw_path.resolve()
    if directory and not path.is_dir():
        raise RunnerInputError(f"{label} directory is missing")
    return path


def validate_request(request: object) -> dict[str, Any]:
    if not isinstance(request, dict) or request.get("schema_version") != REQUEST_SCHEMA:
        raise RunnerInputError("unsupported request schema")
    text = request.get("text")
    text_hash = request.get("text_sha256")
    if not isinstance(text, str) or not text:
        raise RunnerInputError("fixture text is missing")
    if not isinstance(text_hash, str) or hashlib.sha256(text.encode("utf-8")).hexdigest() != text_hash:
        raise RunnerInputError("fixture text hash mismatch")
    if request.get("execution_backend") != "onnx-cpu":
        raise RunnerInputError("official runner only supports the pinned ONNX CPU topology")
    if request.get("streaming") is not True:
        raise RunnerInputError("quality evidence requires streaming first-packet instrumentation")
    if request.get("enable_wetext") is not False:
        raise RunnerInputError("Stage 0 macOS arm64 lock requires WeText to remain disabled")
    if request.get("enable_normalize_tts_text") is not True:
        raise RunnerInputError("robust TTS text normalization must remain explicit")
    for key in ("cpu_threads", "max_new_frames", "voice_clone_max_text_tokens"):
        value = request.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise RunnerInputError(f"{key} must be a positive integer")
    if request.get("sample_mode") not in {"greedy", "fixed", "full"}:
        raise RunnerInputError("sample_mode is unsupported")
    require_path(request.get("source_dir"), "source", directory=True)
    require_path(request.get("model_dir"), "model", directory=True)
    output = require_path(request.get("output_wav"), "output")
    if output.exists():
        raise RunnerInputError("output WAV already exists")
    reference = request.get("reference_audio")
    if reference is not None:
        reference_path = require_path(reference, "reference audio")
        if not reference_path.is_file():
            raise RunnerInputError("reference audio is missing")
    return request


def resolve_voice(runtime: Any, requested: object) -> str:
    voices = runtime.list_builtin_voices()
    names = [row.get("voice") for row in voices if isinstance(row, dict) and row.get("voice")]
    if not names:
        raise RunnerInputError("official runtime exposed no built-in voices")
    voice = str(requested or "default")
    if voice == "default":
        return str(names[0])
    if voice not in names:
        raise RunnerInputError("requested built-in voice is unavailable")
    return voice


def run_official(request: dict[str, Any]) -> dict[str, object]:
    source_dir = Path(request["source_dir"]).resolve()
    model_dir = Path(request["model_dir"]).resolve()
    output_path = Path(request["output_wav"]).resolve()
    missing_source = [name for name in REQUIRED_SOURCE_FILES if not (source_dir / name).is_file()]
    if missing_source:
        raise RunnerInputError("pinned official source tree is incomplete")

    # Explicit local assets plus offline flags prevent the upstream default path
    # from initiating a model download.  WeText stays disabled by frozen T0-A policy.
    os.environ.update(
        {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_DATASETS_OFFLINE": "1",
            "TOKENIZERS_PARALLELISM": "false",
        }
    )
    sys.path.insert(0, str(source_dir))
    try:
        from onnx_tts_runtime import OnnxTtsRuntime  # type: ignore[import-not-found]
    except Exception as error:
        raise RunnerInputError("pinned official ONNX runtime could not be imported") from error

    runtime = OnnxTtsRuntime(
        model_dir=model_dir,
        thread_count=int(request["cpu_threads"]),
        max_new_frames=int(request["max_new_frames"]),
        do_sample=request["sample_mode"] != "greedy",
        sample_mode=str(request["sample_mode"]),
        execution_provider="cpu",
        output_dir=output_path.parent,
    )
    voice = resolve_voice(runtime, request.get("voice"))
    first_packet_ms: float | None = None
    started = time.perf_counter()
    streaming_session = getattr(runtime, "codec_streaming_session", None)
    original_run_frames = getattr(streaming_session, "run_frames", None)
    if not callable(original_run_frames):
        raise RunnerInputError("official runtime has no streaming decode instrumentation point")

    def measured_run_frames(frames: object):
        nonlocal first_packet_ms
        decoded = original_run_frames(frames)
        if decoded is not None and first_packet_ms is None:
            _audio, audio_length = decoded
            if int(audio_length) > 0:
                first_packet_ms = (time.perf_counter() - started) * 1000.0
        return decoded

    streaming_session.run_frames = measured_run_frames
    try:
        runtime.synthesize(
            text=str(request["text"]),
            voice=voice,
            prompt_audio_path=request.get("reference_audio"),
            output_audio_path=output_path,
            sample_mode=str(request["sample_mode"]),
            do_sample=request["sample_mode"] != "greedy",
            streaming=True,
            max_new_frames=int(request["max_new_frames"]),
            voice_clone_max_text_tokens=int(request["voice_clone_max_text_tokens"]),
            enable_wetext=False,
            enable_normalize_tts_text=True,
            seed=int(request["seed"]),
        )
    finally:
        streaming_session.run_frames = original_run_frames
    if first_packet_ms is None:
        raise RunnerInputError("official runtime produced no measurable first audio packet")
    if not output_path.is_file():
        raise RunnerInputError("official runtime did not create the requested WAV")
    return {
        "schema_version": RESPONSE_SCHEMA,
        "status": "passed",
        "adapter_kind": "official-nano-onnx",
        "first_packet_ms": round(first_packet_ms, 6),
        "peak_rss_bytes": peak_rss_bytes(),
        "peak_accelerator_bytes": None,
        "output_sha256": sha256_file(output_path),
        "error": None,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--response", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        raw_request = json.loads(args.request.read_text(encoding="utf-8"))
        request = validate_request(raw_request)
        response = run_official(request)
        exit_code = 0
    except Exception as error:
        response = {
            "schema_version": RESPONSE_SCHEMA,
            "status": "failed",
            "adapter_kind": "official-nano-onnx",
            "first_packet_ms": None,
            "peak_rss_bytes": peak_rss_bytes(),
            "peak_accelerator_bytes": None,
            "output_sha256": None,
            "error": {
                "category": "official_onnx_runner",
                "code": type(error).__name__,
                "message_redacted": "official ONNX runner was blocked or failed",
            },
        }
        exit_code = 2
    atomic_json(args.response, response)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
