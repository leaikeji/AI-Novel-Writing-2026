"""Stdlib-only T6 client for execution inside the production Sidecar container."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from http.client import HTTPConnection
import io
import json
from pathlib import Path
import secrets
import threading
import time
from typing import Mapping, Sequence
from uuid import UUID, uuid4
import wave


PROTOCOL = "moss-tts-sidecar/1.1"
CONTROL_HEADER = "X-MOSS-Sidecar-Token"
WORKER_HEADER = "X-MOSS-Worker-Token"
VERSION_HEADER = "X-MOSS-Protocol-Version"
GENERATION_HEADER = "X-MOSS-Worker-Generation"
MODEL_HEADER = "X-MOSS-Actual-Model-Fingerprint-SHA256"
REQUEST_HEADER = "X-MOSS-Request-ID"
LOCAL_SCOPE_FINGERPRINT = "8cd0df892dc4c7289e1182087e9ea8ec365c2d54d254d8aee5bd9252f5225095"
EXPECTED_MODEL = "3c76f3e9e1381699c5555287cf66eeb023632d0c3ee94adc6d8ae1b1d455fd7d"
REQUEST_ID = UUID("f81cd27e-3f31-4e48-b041-e5e41fa6acb6")
VALIDATION_TEXT = "灯影掠过窗沿，走廊尽头传来一声很轻的脚步。"


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _json_request(
    method: str,
    path: str,
    payload: Mapping[str, object] | None,
    *,
    header_name: str,
    token: str,
    timeout: float = 120.0,
) -> tuple[int, dict[str, str], dict[str, object]]:
    body = _canonical(payload) if payload is not None else None
    headers = {header_name: token, VERSION_HEADER: PROTOCOL}
    if body is not None:
        headers.update({"Content-Type": "application/json", "Content-Length": str(len(body))})
    connection = HTTPConnection("127.0.0.1", 8765, timeout=timeout)
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        row = json.loads(raw.decode("utf-8"))
        return response.status, {key: value for key, value in response.getheaders()}, row
    finally:
        connection.close()


def _require_success(
    response: tuple[int, dict[str, str], dict[str, object]],
    *,
    expected_status: int,
) -> tuple[dict[str, str], dict[str, object]]:
    status, headers, row = response
    if status != expected_status or headers.get(VERSION_HEADER) != PROTOCOL or row.get("protocol_version") != PROTOCOL:
        raise RuntimeError("Sidecar control response identity is invalid")
    return headers, row


def _inspect_wav(payload: bytes) -> dict[str, object]:
    with wave.open(io.BytesIO(payload), "rb") as stream:
        channels = stream.getnchannels()
        sample_rate = stream.getframerate()
        sample_width = stream.getsampwidth()
        frames = stream.getnframes()
        decoded = stream.readframes(frames)
        trailing = stream.readframes(1)
    if not decoded or trailing or (sample_rate, channels, sample_width) != (48_000, 2, 2):
        raise RuntimeError("Nano WAV differs from the frozen PCM contract")
    return {
        "sample_rate_hz": sample_rate,
        "channels": channels,
        "sample_width_bytes": sample_width,
        "frame_count": frames,
        "duration_seconds": frames / sample_rate,
        "byte_size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _synthesize(reference: bytes, worker_token: str, generation: int) -> tuple[dict[str, str], bytes]:
    source_sha256 = hashlib.sha256(reference).hexdigest()
    metadata = _canonical(
        {
            "request_id": str(REQUEST_ID),
            "scope_fingerprint": LOCAL_SCOPE_FINGERPRINT,
            "requested_model_fingerprint_sha256": EXPECTED_MODEL,
            "text": VALIDATION_TEXT,
            "voice": "vg40_generated_reference",
            "seed": 104729,
            "sample_mode": "full",
            "max_new_frames": 375,
            "reference_audio": {
                "content_type": "audio/wav",
                "actual_sha256": source_sha256,
                "size_bytes": len(reference),
            },
        }
    )
    boundary = f"moss_{secrets.token_hex(20)}"
    marker = f"--{boundary}".encode("ascii")
    body = b"\r\n".join(
        [
            marker,
            b'Content-Disposition: form-data; name="metadata"',
            b"Content-Type: application/json",
            b"",
            metadata,
            marker,
            b'Content-Disposition: form-data; name="reference_audio"',
            b"Content-Type: audio/wav",
            b"",
            reference,
            marker + b"--",
            b"",
        ]
    )
    connection = HTTPConnection("127.0.0.1", 8765, timeout=180.0)
    try:
        connection.request(
            "POST",
            "/v1/synthesize",
            body=body,
            headers={
                WORKER_HEADER: worker_token,
                VERSION_HEADER: PROTOCOL,
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body)),
            },
        )
        response = connection.getresponse()
        payload = response.read()
        headers = {key: value for key, value in response.getheaders()}
        if response.status != 200:
            raise RuntimeError("Nano reference synthesis failed")
        if (
            headers.get(VERSION_HEADER) != PROTOCOL
            or headers.get(REQUEST_HEADER) != str(REQUEST_ID)
            or headers.get(GENERATION_HEADER) != str(generation)
            or headers.get(MODEL_HEADER) != EXPECTED_MODEL
            or headers.get("X-MOSS-Audio-SHA256") != hashlib.sha256(payload).hexdigest()
        ):
            raise RuntimeError("Nano synthesis evidence identity is invalid")
        return headers, payload
    finally:
        connection.close()


def run(source_wav: Path, token_file: Path) -> dict[str, object]:
    reference = source_wav.read_bytes()
    source = _inspect_wav(reference)
    if not 3.0 <= source["duration_seconds"] <= 5.0:
        raise RuntimeError("VoiceGenerator source duration is outside T6")
    bootstrap_token = token_file.read_text(encoding="ascii")
    acquire_id = uuid4()
    headers, acquired = _require_success(
        _json_request("POST", "/v1/lease/acquire", {"request_id": str(acquire_id)}, header_name=CONTROL_HEADER, token=bootstrap_token),
        expected_status=200,
    )
    worker_token = acquired.get("worker_token")
    generation = acquired.get("worker", {}).get("generation") if isinstance(acquired.get("worker"), dict) else None
    if not isinstance(worker_token, str) or not isinstance(generation, int) or headers.get(GENERATION_HEADER) != str(generation):
        raise RuntimeError("Sidecar lease identity is invalid")

    stop_renewal = threading.Event()
    renewal_errors: list[str] = []

    def renew() -> None:
        while not stop_renewal.wait(20.0):
            try:
                _require_success(
                    _json_request("POST", "/v1/lease/renew", {"request_id": str(uuid4())}, header_name=WORKER_HEADER, token=worker_token),
                    expected_status=200,
                )
            except BaseException as error:
                renewal_errors.append(type(error).__name__)
                stop_renewal.set()

    renewal = threading.Thread(target=renew, name="vg40-t6-lease-renewal", daemon=True)
    renewal.start()
    try:
        warmup_id = uuid4()
        warm_headers, warmed = _require_success(
            _json_request("POST", "/v1/warmup", {"request_id": str(warmup_id)}, header_name=WORKER_HEADER, token=worker_token, timeout=180.0),
            expected_status=200,
        )
        actual_model = warmed.get("model_fingerprint_sha256")
        if actual_model != EXPECTED_MODEL or warm_headers.get(MODEL_HEADER) != EXPECTED_MODEL:
            raise RuntimeError("Nano warmup model identity changed")
        _, output_bytes = _synthesize(reference, worker_token, generation)
        output = _inspect_wav(output_bytes)
        if renewal_errors:
            raise RuntimeError("Sidecar lease renewal failed")
        return {
            "schema_version": "vg40-t6-nano-validation/1",
            "passed": True,
            "status": "PASS",
            "source_sample_sha256": source["sha256"],
            "source_duration_seconds": source["duration_seconds"],
            "validation_text_sha256": hashlib.sha256(VALIDATION_TEXT.encode("utf-8")).hexdigest(),
            "request_id": str(REQUEST_ID),
            "requested_model_fingerprint_sha256": EXPECTED_MODEL,
            "actual_model_fingerprint_sha256": actual_model,
            "worker_generation": generation,
            "output": output,
            "database_writes": 0,
            "audio_published": False,
            "observed_at": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        stop_renewal.set()
        renewal.join(timeout=2.0)
        release_id = uuid4()
        _require_success(
            _json_request("POST", "/v1/lease/release", {"request_id": str(release_id)}, header_name=WORKER_HEADER, token=worker_token),
            expected_status=202,
        )
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            _, row = _require_success(
                _json_request("GET", "/v1/health", None, header_name=CONTROL_HEADER, token=bootstrap_token),
                expected_status=200,
            )
            if row.get("status") == "unloaded" and row.get("ready") is False:
                break
            time.sleep(0.25)
        else:
            raise RuntimeError("Sidecar did not unload after T6")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-wav", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, default=Path("/run/moss-tts-secrets/moss_tts_sidecar_token"))
    arguments = parser.parse_args(argv)
    print(json.dumps(run(arguments.source_wav, arguments.token_file), ensure_ascii=False, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
