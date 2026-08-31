"""Validate one accepted VoiceGenerator sample through the production Nano Sidecar.

The script is database-free.  It emits only hashes, model identity and scalar
audio facts; the synthesized Nano audio remains in memory and is not published.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import wave
from typing import Sequence
from uuid import UUID

from backend.narration.contracts import (
    AdapterHealthStatus,
    NarrationRequestScope,
    ReferenceAudioInput,
    SynthesisRequest,
)
from backend.narration.fingerprints import model_fingerprint_sha256
from backend.narration.runtime import (
    SidecarMossNanoTTSAdapter,
    SidecarRuntimeConfig,
    SupervisorManagedSidecarLifecycle,
)


SCHEMA = "vg40-t6-nano-validation/1"
REQUEST_ID = UUID("f81cd27e-3f31-4e48-b041-e5e41fa6acb6")
VALIDATION_TEXT = "灯影掠过窗沿，走廊尽头传来一声很轻的脚步。"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def load_source(source_run_dir: Path) -> tuple[bytes, str, dict[str, object]]:
    if (
        not source_run_dir.is_absolute()
        or source_run_dir.is_symlink()
        or not source_run_dir.is_dir()
        or source_run_dir.absolute() != source_run_dir.resolve(strict=True)
    ):
        raise ValueError("source run directory is invalid")
    assessment_path = source_run_dir / "assessment.json"
    wav_path = source_run_dir / "sample.wav"
    if assessment_path.is_symlink() or not assessment_path.is_file():
        raise ValueError("source assessment is missing")
    if wav_path.is_symlink() or not wav_path.is_file():
        raise ValueError("source WAV is missing")
    assessment = json.loads(assessment_path.read_text(encoding="utf-8"))
    child = assessment.get("child")
    output_audio = child.get("output_audio") if isinstance(child, dict) else None
    digest = _sha256(wav_path)
    if (
        assessment.get("schema_version") != "vg40-t4-assessment/1"
        or assessment.get("passed") is not True
        or assessment.get("audio_valid") is not True
        or assessment.get("wav_sha256") != digest
        or not isinstance(output_audio, dict)
        or output_audio.get("sha256") != digest
        or output_audio.get("duration_seconds") < 3.0
        or output_audio.get("duration_seconds") > 5.0
    ):
        raise ValueError("source sample did not pass T4 identity and quality")
    return wav_path.read_bytes(), digest, assessment


def inspect_output(payload: bytes) -> dict[str, object]:
    with wave.open(io.BytesIO(payload), "rb") as stream:
        channels = stream.getnchannels()
        sample_rate = stream.getframerate()
        sample_width = stream.getsampwidth()
        frame_count = stream.getnframes()
        frames = stream.readframes(frame_count)
        if stream.readframes(1):
            raise ValueError("Nano output contains trailing decoded frames")
    if not frames or (sample_rate, channels, sample_width) != (48_000, 2, 2):
        raise ValueError("Nano output differs from the frozen PCM contract")
    return {
        "sample_rate_hz": sample_rate,
        "channels": channels,
        "sample_width_bytes": sample_width,
        "frame_count": frame_count,
        "duration_seconds": frame_count / sample_rate,
        "byte_size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _write_json(path: Path, payload: object) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError("result path already exists")
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2) + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    with temporary.open("xb") as target:
        target.write(encoded)
        target.flush()
        os.fsync(target.fileno())
    os.replace(temporary, path)


async def run(source_run_dir: Path, result_path: Path) -> int:
    source_bytes, source_sha256, source_assessment = load_source(source_run_dir)
    config = SidecarRuntimeConfig(
        host=os.environ["MOSS_TTS_SIDECAR_HOST"],
        port=int(os.environ["MOSS_TTS_SIDECAR_PORT"]),
        token_file=Path(os.environ["MOSS_TTS_SIDECAR_TOKEN_FILE"]),
        timeout_seconds=float(os.environ.get("MOSS_TTS_REQUEST_TIMEOUT_SECONDS", "120")),
        allow_test_backend=False,
    )
    lifecycle = SupervisorManagedSidecarLifecycle(config)
    adapter = SidecarMossNanoTTSAdapter(config, lifecycle=lifecycle)
    activated = False
    try:
        await adapter.activate()
        activated = True
        warmed = await adapter.warmup()
        if warmed.status is not AdapterHealthStatus.HEALTHY:
            raise RuntimeError("Nano warmup did not become healthy")
        result = await adapter.synthesize(
            SynthesisRequest(
                request_id=REQUEST_ID,
                scope=NarrationRequestScope.fixed_local(),
                text=VALIDATION_TEXT,
                voice="vg40.generated.reference",
                seed=104729,
                sample_mode="full",
                max_new_frames=375,
                reference_audio=ReferenceAudioInput(
                    audio_bytes=source_bytes,
                    actual_sha256=source_sha256,
                    content_type="audio/wav",
                ),
            )
        )
        output = inspect_output(result.audio_bytes)
        fingerprint_digest = model_fingerprint_sha256(result.model_fingerprint)
        passed = (
            output["sha256"] == result.actual_output_sha256
            and result.request_id == REQUEST_ID
            and result.sample_rate_hz == 48_000
            and result.channels == 2
            and result.sample_width_bytes == 2
            and fingerprint_digest == warmed.model_fingerprint_sha256
        )
        payload = {
            "schema_version": SCHEMA,
            "passed": passed,
            "status": "PASS" if passed else "FAIL",
            "source_run_name": source_run_dir.name,
            "source_sample_sha256": source_sha256,
            "source_t4_status": source_assessment.get("status"),
            "validation_text_sha256": hashlib.sha256(VALIDATION_TEXT.encode("utf-8")).hexdigest(),
            "request_id": str(REQUEST_ID),
            "requested_model_fingerprint_sha256": warmed.model_fingerprint_sha256,
            "actual_model_fingerprint_sha256": fingerprint_digest,
            "actual_model_name": result.model_fingerprint.model_name,
            "actual_model_revision": result.model_fingerprint.model_revision,
            "worker_generation": result.worker_generation,
            "output": output,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "database_writes": 0,
            "audio_published": False,
        }
        _write_json(result_path, payload)
        return 0 if passed else 1
    finally:
        if activated:
            await adapter.deactivate()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-run-dir", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    arguments = parser.parse_args(argv)
    if not arguments.result.is_absolute() or not arguments.result.parent.is_dir():
        raise ValueError("result parent must be an existing absolute directory")
    return asyncio.run(run(arguments.source_run_dir, arguments.result))


if __name__ == "__main__":
    raise SystemExit(main())
