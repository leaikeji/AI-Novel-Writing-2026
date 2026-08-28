"""Isolated PawApp-side test harness; stdin JSON only, never a production API."""

from __future__ import annotations

import hashlib
from http.client import HTTPConnection
import json
from pathlib import Path
import sys
import wave
import io

from sidecar_client import SidecarClient
from sidecar_protocol import (
    PROTOCOL_VERSION,
    TOKEN_HEADER,
    VERSION_HEADER,
    ReferenceAudio,
    SynthesisRequest,
    build_multipart_body,
    canonical_json_bytes,
)


TOKEN_FILE = Path("/run/secrets/moss_sidecar_token")
PUBLISH_ROOT = Path("/pawapp-media")
REFERENCE_ROOT = Path("/authorized-reference-fixtures")


def fail(message: str) -> None:
    raise ValueError(message)


def load_reference(name: object, reference_asset_id: object) -> ReferenceAudio | None:
    if name is None:
        return None
    if not isinstance(name, str) or Path(name).name != name or not name.endswith((".wav", ".flac")):
        fail("reference fixture identity is invalid")
    if not isinstance(reference_asset_id, str):
        fail("reference asset identity is required")
    root = REFERENCE_ROOT.resolve()
    path = (root / name).resolve()
    path.relative_to(root)
    payload = path.read_bytes()
    audio_format = path.suffix.removeprefix(".").lower()
    # Duration is re-inspected and enforced by the Sidecar. This local value is
    # descriptive only and is deliberately not trusted by the wire protocol.
    duration = 0.0
    if audio_format == "wav":
        with wave.open(io.BytesIO(payload), "rb") as stream:
            duration = stream.getnframes() / stream.getframerate()
    return ReferenceAudio(
        reference_asset_id=reference_asset_id,
        declared_sha256=hashlib.sha256(payload).hexdigest(),
        audio_format=audio_format,
        declared_size_bytes=len(payload),
        duration_seconds=duration,
        payload=payload,
    )


def request_from(row: dict[str, object]) -> SynthesisRequest:
    expected = {
        "operation",
        "request_id",
        "asset_id",
        "text",
        "voice",
        "seed",
        "max_new_frames",
        "sample_mode",
        "reference_fixture_name",
        "reference_asset_id",
    }
    if set(row) != expected:
        fail("harness request fields are invalid")
    return SynthesisRequest(
        request_id=str(row["request_id"]),
        asset_id=str(row["asset_id"]),
        text=str(row["text"]),
        voice=str(row["voice"]),
        seed=int(row["seed"]),
        max_new_frames=int(row["max_new_frames"]),
        sample_mode=str(row["sample_mode"]),
        reference_audio=load_reference(row["reference_fixture_name"], row["reference_asset_id"]),
    )


def main() -> int:
    raw = sys.stdin.buffer.read(64 * 1024 + 1)
    if not raw or len(raw) > 64 * 1024:
        fail("harness control request is outside the limit")
    row = json.loads(raw.decode("utf-8"))
    if not isinstance(row, dict):
        fail("harness control request must be an object")
    client = SidecarClient(
        "sidecar",
        8765,
        TOKEN_FILE.read_text(encoding="ascii").rstrip("\r\n"),
        timeout_seconds=300,
    )
    operation = row.get("operation")
    if operation == "capabilities" and set(row) == {"operation"}:
        result = client.capabilities()
    elif operation == "synthesize":
        result = client.synthesize_and_publish(request_from(row), PUBLISH_ROOT)
    elif operation == "malicious_reference_hash_probe":
        request = request_from(row | {"operation": "synthesize"})
        if request.reference_audio is None:
            fail("reference fixture is required")
        body, content_type = build_multipart_body(request, "maliciousprobe0123456789abcdef")
        body = body.replace(request.reference_audio.declared_sha256.encode("ascii"), b"0" * 64, 1)
        token = TOKEN_FILE.read_text(encoding="ascii").rstrip("\r\n")
        connection = HTTPConnection("sidecar", 8765, timeout=30)
        try:
            connection.request(
                "POST",
                "/v1/synthesize",
                body=body,
                headers={
                    TOKEN_HEADER: token,
                    VERSION_HEADER: PROTOCOL_VERSION,
                    "Content-Type": content_type,
                    "Content-Length": str(len(body)),
                },
            )
            response = connection.getresponse()
            response_body = response.read(64 * 1024 + 1)
            detail = json.loads(response_body.decode("utf-8"))
            result = {"http_status": response.status, "error_code": detail.get("error", {}).get("code")}
        finally:
            connection.close()
    elif operation == "cancel" and set(row) == {"operation", "request_id", "asset_id"}:
        result = client.cancel(str(row["request_id"]), str(row["asset_id"]))
    elif operation == "audit_storage" and set(row) == {"operation"}:
        files = [
            path
            for path in PUBLISH_ROOT.rglob("*")
            if path.is_file() and path.name != ".t0b-sidecar-test-root"
        ]
        result = {
            "wav_count": sum(path.suffix == ".wav" for path in files),
            "partial_count": sum(path.suffix == ".part" or ".part" in path.name for path in files),
            "unexpected_file_count": sum(path.suffix not in {".wav"} for path in files),
        }
    else:
        fail("harness operation is invalid")
    sys.stdout.buffer.write(canonical_json_bytes(result) + b"\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        sys.stderr.write(f"harness_failed:{type(error).__name__}\n")
        raise SystemExit(2)
