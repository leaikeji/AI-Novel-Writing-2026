"""PawApp-side narrow client and atomic media publisher prototype."""

from __future__ import annotations

import hashlib
from http.client import HTTPConnection
import io
import json
import os
from pathlib import Path
import re
import secrets
import uuid
import wave

from sidecar_protocol import (
    MAX_AUDIO_BYTES,
    PROTOCOL_VERSION,
    TOKEN_HEADER,
    VERSION_HEADER,
    ProtocolError,
    SynthesisRequest,
    build_multipart_body,
    canonical_json_bytes,
    request_payload,
    parse_request_bytes,
    sha256_bytes,
    validate_token,
)


class SidecarClient:
    def __init__(self, host: str, port: int, token: str, *, timeout_seconds: float = 30.0):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}", host):
            raise ProtocolError("client", "HOST_INVALID", "host must be a service identity")
        if isinstance(port, bool) or not isinstance(port, int) or not (1 <= port <= 65535):
            raise ProtocolError("client", "PORT_INVALID", "port is invalid")
        if timeout_seconds <= 0 or timeout_seconds > 300:
            raise ProtocolError("client", "TIMEOUT_INVALID", "timeout is invalid")
        self.host = host
        self.port = port
        self.token = validate_token(token)
        self.timeout_seconds = timeout_seconds

    def _headers(self, content_length: int | None = None, *, content_type: str = "application/json") -> dict[str, str]:
        headers = {
            TOKEN_HEADER: self.token,
            VERSION_HEADER: PROTOCOL_VERSION,
        }
        if content_length is not None:
            headers.update({"Content-Type": content_type, "Content-Length": str(content_length)})
        return headers

    def capabilities(self) -> dict[str, object]:
        connection = HTTPConnection(self.host, self.port, timeout=self.timeout_seconds)
        try:
            connection.request("GET", "/v1/capabilities", headers=self._headers())
            response = connection.getresponse()
            body = response.read(64 * 1024 + 1)
            if response.status != 200 or len(body) > 64 * 1024:
                raise ProtocolError("client", "CAPABILITY_HANDSHAKE_FAILED", "capability handshake failed")
            row = json.loads(body.decode("utf-8"))
            if row.get("protocol_version") != PROTOCOL_VERSION:
                raise ProtocolError("client", "VERSION_MISMATCH", "protocol version mismatch")
            return row
        finally:
            connection.close()

    def synthesize_and_publish(self, request: SynthesisRequest, publish_root: Path) -> dict[str, object]:
        metadata = canonical_json_bytes(request_payload(request))
        parse_request_bytes(
            metadata,
            reference_audio_bytes=request.reference_audio.payload if request.reference_audio is not None else None,
        )
        root = publish_root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        target = (root / f"{request.asset_id}.wav").resolve()
        target.relative_to(root)
        if target.exists():
            payload = target.read_bytes()
            actual_hash = sha256_bytes(payload)
            try:
                with wave.open(io.BytesIO(payload), "rb") as wav_file:
                    descriptor = {
                        "sample_rate": wav_file.getframerate(),
                        "channels": wav_file.getnchannels(),
                        "sample_width": wav_file.getsampwidth(),
                        "frames": wav_file.getnframes(),
                    }
            except (wave.Error, EOFError) as error:
                raise ProtocolError("client", "EXISTING_ASSET_INVALID", "existing asset is invalid") from error
            return {
                "status": "reused",
                "file_name": target.name,
                "sha256": actual_hash,
                "sidecar_request_skipped": True,
                **descriptor,
            }
        if request.reference_audio is None:
            body = metadata
            content_type = "application/json"
        else:
            body, content_type = build_multipart_body(request, secrets.token_hex(24))
        connection = HTTPConnection(self.host, self.port, timeout=self.timeout_seconds)
        try:
            connection.request(
                "POST",
                "/v1/synthesize",
                body=body,
                headers=self._headers(len(body), content_type=content_type),
            )
            response = connection.getresponse()
            if response.status != 200:
                error_body = response.read(64 * 1024 + 1)
                try:
                    row = json.loads(error_body.decode("utf-8"))
                    detail = row["error"]
                    if row.get("protocol_version") != PROTOCOL_VERSION or not isinstance(detail, dict):
                        raise ValueError
                except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                    raise ProtocolError("client", "SIDECAR_ERROR_INVALID", "sidecar error response is invalid") from error
                raise ProtocolError(
                    str(detail.get("category", "sidecar")),
                    str(detail.get("code", "SIDECAR_ERROR")),
                    "sidecar rejected request",
                    retryable=detail.get("retryable") is True,
                )
            content_length = response.getheader("Content-Length")
            if content_length is None or not content_length.isdigit():
                raise ProtocolError("client", "CONTENT_LENGTH_INVALID", "audio content length is invalid")
            size = int(content_length)
            if size <= 0 or size > MAX_AUDIO_BYTES:
                raise ProtocolError("client", "AUDIO_SIZE_EXCEEDED", "audio exceeds response limit")
            payload = response.read(size + 1)
            if len(payload) != size:
                raise ProtocolError("client", "AUDIO_RESPONSE_INVALID", "audio response is invalid")
            if response.getheader("Content-Type") != "audio/wav":
                raise ProtocolError("client", "AUDIO_FORMAT_INVALID", "audio response format is invalid")
            if response.getheader(VERSION_HEADER) != PROTOCOL_VERSION:
                raise ProtocolError("client", "VERSION_MISMATCH", "protocol version mismatch")
            if response.getheader("X-MOSS-Request-ID") != request.request_id:
                raise ProtocolError("client", "REQUEST_ID_MISMATCH", "response request identity mismatch")
            if response.getheader("X-MOSS-Asset-ID") != request.asset_id:
                raise ProtocolError("client", "ASSET_ID_MISMATCH", "response asset identity mismatch")
            actual_hash = sha256_bytes(payload)
            if response.getheader("X-MOSS-Audio-SHA256") != actual_hash:
                raise ProtocolError("client", "AUDIO_HASH_MISMATCH", "audio hash mismatch")
            with wave.open(io.BytesIO(payload), "rb") as wav_file:
                descriptor = {
                    "sample_rate": wav_file.getframerate(),
                    "channels": wav_file.getnchannels(),
                    "sample_width": wav_file.getsampwidth(),
                    "frames": wav_file.getnframes(),
                }
            expected_headers = {
                "X-MOSS-Sample-Rate": descriptor["sample_rate"],
                "X-MOSS-Channels": descriptor["channels"],
                "X-MOSS-Sample-Width": descriptor["sample_width"],
            }
            if any(response.getheader(name) != str(value) for name, value in expected_headers.items()):
                raise ProtocolError("client", "AUDIO_DESCRIPTOR_MISMATCH", "audio descriptor mismatch")
            metrics: dict[str, int | float] = {}
            try:
                metrics = {
                    "inference_entered_ms": float(response.getheader("X-MOSS-Inference-Entered-Ms", "")),
                    "ready_wav_ms": float(response.getheader("X-MOSS-Ready-Wav-Ms", "")),
                    "wall_ms": float(response.getheader("X-MOSS-Wall-Ms", "")),
                    "peak_rss_bytes": int(response.getheader("X-MOSS-Peak-RSS-Bytes", "")),
                    "worker_pid": int(response.getheader("X-MOSS-Worker-PID", "")),
                }
            except ValueError as error:
                raise ProtocolError("client", "METRICS_INVALID", "sidecar metrics are invalid") from error
            generation = response.getheader("X-MOSS-Worker-Generation", "")
            if (
                metrics["inference_entered_ms"] < 0
                or metrics["ready_wav_ms"] < 0
                or metrics["wall_ms"] < 0
                or metrics["peak_rss_bytes"] <= 0
                or metrics["worker_pid"] <= 0
                or not re.fullmatch(r"[0-9a-f]{32}", generation)
            ):
                raise ProtocolError("client", "METRICS_INVALID", "sidecar metrics are invalid")
            metrics["worker_generation"] = generation
            temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.part")
            publication_status = "published"
            try:
                with temporary.open("xb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    os.link(temporary, target)
                except FileExistsError:
                    existing_hash = hashlib.sha256(target.read_bytes()).hexdigest()
                    if existing_hash != actual_hash:
                        raise ProtocolError("client", "ASSET_CONFLICT", "asset already exists with another hash")
                    publication_status = "reused_after_race"
                directory_fd = os.open(root, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                temporary.unlink(missing_ok=True)
            return {
                "status": publication_status,
                "file_name": target.name,
                "sha256": actual_hash,
                "sidecar_request_skipped": False,
                **descriptor,
                **metrics,
            }
        finally:
            connection.close()

    def cancel(self, request_id: str, asset_id: str) -> dict[str, object]:
        body = canonical_json_bytes({"request_id": request_id, "asset_id": asset_id})
        connection = HTTPConnection(self.host, self.port, timeout=self.timeout_seconds)
        try:
            connection.request("POST", "/v1/cancel", body=body, headers=self._headers(len(body)))
            response = connection.getresponse()
            payload = response.read(64 * 1024 + 1)
            if response.status != 200 or len(payload) > 64 * 1024:
                raise ProtocolError("client", "CANCEL_FAILED", "sidecar cancel failed")
            row = json.loads(payload.decode("utf-8"))
            if (
                row.get("protocol_version") != PROTOCOL_VERSION
                or row.get("request_id") != request_id
                or row.get("asset_id") != asset_id
                or row.get("status") not in {"cancel_requested", "not_active"}
            ):
                raise ProtocolError("client", "CANCEL_RESPONSE_INVALID", "sidecar cancel response is invalid")
            return row
        finally:
            connection.close()
