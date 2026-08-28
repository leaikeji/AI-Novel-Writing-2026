"""Narrow production protocol shared by the Sidecar server and PawApp client.

The protocol deliberately has no filesystem path field.  PawApp sends a
bounded request/asset identity and receives bounded WAV bytes plus immutable
metadata; PawApp alone owns final media publication.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import secrets
from typing import Any, Mapping
import wave
import io


PROTOCOL_VERSION = "moss-tts-sidecar/1.0"
TOKEN_HEADER = "X-MOSS-Sidecar-Token"
VERSION_HEADER = "X-MOSS-Protocol-Version"
MAX_REQUEST_BYTES = 64 * 1024
MAX_AUDIO_BYTES = 16 * 1024 * 1024
MAX_TEXT_CHARS = 4_000
MAX_REFERENCE_AUDIO_BYTES = 12 * 1024 * 1024
MAX_MULTIPART_BYTES = MAX_REQUEST_BYTES + MAX_REFERENCE_AUDIO_BYTES + 4 * 1024
MAX_REFERENCE_DURATION_SECONDS = 12.5
MIN_TOKEN_CHARS = 32
MAX_TOKEN_CHARS = 256
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
VOICE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
REQUEST_KEYS = frozenset({"request_id", "asset_id", "text", "parameters"})
REQUEST_KEYS_WITH_REFERENCE = REQUEST_KEYS | {"reference_audio"}
PARAMETER_KEYS = frozenset({"voice", "seed", "max_new_frames", "sample_mode"})
FORBIDDEN_KEY_FRAGMENTS = ("path", "directory", "database", "dsn", "url", "token")


class ProtocolError(ValueError):
    def __init__(self, category: str, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.category = category
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class SynthesisRequest:
    request_id: str
    asset_id: str
    text: str
    voice: str
    seed: int
    max_new_frames: int
    sample_mode: str
    reference_audio: "ReferenceAudio | None" = None


@dataclass(frozen=True)
class ReferenceAudio:
    reference_asset_id: str
    declared_sha256: str
    audio_format: str
    declared_size_bytes: int
    duration_seconds: float
    payload: bytes


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def validate_token(token: str) -> str:
    if not isinstance(token, str) or not (MIN_TOKEN_CHARS <= len(token) <= MAX_TOKEN_CHARS):
        raise ProtocolError("authentication", "TOKEN_CONFIGURATION_INVALID", "token length is invalid")
    if any(character.isspace() for character in token):
        raise ProtocolError("authentication", "TOKEN_CONFIGURATION_INVALID", "token contains whitespace")
    return token


def authenticate(expected: str, supplied: str | None) -> None:
    validate_token(expected)
    if supplied is None or not secrets.compare_digest(expected, supplied):
        raise ProtocolError("authentication", "AUTHENTICATION_FAILED", "authentication failed")


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProtocolError("request", "INVALID_JSON_SHAPE", f"{label} must be an object")
    return value


def _reject_forbidden_keys(value: object, location: str = "request") -> None:
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = str(raw_key).lower()
            if any(fragment in key for fragment in FORBIDDEN_KEY_FRAGMENTS):
                raise ProtocolError("request", "FILESYSTEM_OR_SECRET_FIELD_FORBIDDEN", f"{location} contains a forbidden field")
            _reject_forbidden_keys(child, f"{location}.{raw_key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden_keys(child, f"{location}[{index}]")


def _inspect_reference_audio(payload: bytes, audio_format: str) -> float:
    if audio_format == "wav":
        try:
            with wave.open(io.BytesIO(payload), "rb") as wav_file:
                if wav_file.getcomptype() != "NONE" or wav_file.getframerate() <= 0:
                    raise ProtocolError("reference_audio", "REFERENCE_FORMAT_INVALID", "reference WAV is invalid")
                return wav_file.getnframes() / wav_file.getframerate()
        except (wave.Error, EOFError) as error:
            raise ProtocolError("reference_audio", "REFERENCE_FORMAT_INVALID", "reference WAV is invalid") from error
    if audio_format == "flac":
        if len(payload) < 42 or payload[:4] != b"fLaC":
            raise ProtocolError("reference_audio", "REFERENCE_FORMAT_INVALID", "reference FLAC is invalid")
        block_header = payload[4:8]
        block_type = block_header[0] & 0x7F
        block_size = int.from_bytes(block_header[1:4], "big")
        if block_type != 0 or block_size != 34 or len(payload) < 8 + block_size:
            raise ProtocolError("reference_audio", "REFERENCE_FORMAT_INVALID", "reference FLAC STREAMINFO is invalid")
        packed = int.from_bytes(payload[18:26], "big")
        sample_rate = (packed >> 44) & 0xFFFFF
        total_samples = packed & ((1 << 36) - 1)
        if sample_rate <= 0 or total_samples <= 0:
            raise ProtocolError("reference_audio", "REFERENCE_FORMAT_INVALID", "reference FLAC duration is invalid")
        return total_samples / sample_rate
    raise ProtocolError("reference_audio", "REFERENCE_FORMAT_UNSUPPORTED", "reference format is unsupported")


def _parse_reference_audio(metadata: object, payload: bytes | None) -> ReferenceAudio:
    row = _mapping(metadata, "reference_audio")
    expected = {"reference_asset_id", "declared_sha256", "format", "size_bytes"}
    if frozenset(row) != expected:
        raise ProtocolError("reference_audio", "REFERENCE_METADATA_INVALID", "reference metadata fields are invalid")
    if payload is None:
        raise ProtocolError("reference_audio", "REFERENCE_BYTES_REQUIRED", "reference audio bytes are required")
    reference_asset_id = str(row.get("reference_asset_id", ""))
    declared_hash = str(row.get("declared_sha256", ""))
    audio_format = str(row.get("format", "")).lower()
    declared_size = row.get("size_bytes")
    if not ID_PATTERN.fullmatch(reference_asset_id):
        raise ProtocolError("reference_audio", "REFERENCE_ASSET_ID_INVALID", "reference asset identity is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", declared_hash):
        raise ProtocolError("reference_audio", "REFERENCE_HASH_INVALID", "reference declared hash is invalid")
    if isinstance(declared_size, bool) or not isinstance(declared_size, int):
        raise ProtocolError("reference_audio", "REFERENCE_SIZE_INVALID", "reference declared size is invalid")
    if declared_size != len(payload) or not (1 <= declared_size <= MAX_REFERENCE_AUDIO_BYTES):
        raise ProtocolError("reference_audio", "REFERENCE_SIZE_INVALID", "reference size is invalid")
    if sha256_bytes(payload) != declared_hash:
        raise ProtocolError("reference_audio", "REFERENCE_HASH_MISMATCH", "reference audio hash mismatch")
    duration = _inspect_reference_audio(payload, audio_format)
    if not (0 < duration <= MAX_REFERENCE_DURATION_SECONDS):
        raise ProtocolError("reference_audio", "REFERENCE_DURATION_EXCEEDED", "reference duration exceeds limit")
    return ReferenceAudio(reference_asset_id, declared_hash, audio_format, declared_size, duration, payload)


def parse_request_bytes(body: bytes, *, reference_audio_bytes: bytes | None = None) -> SynthesisRequest:
    if not body or len(body) > MAX_REQUEST_BYTES:
        raise ProtocolError("request", "REQUEST_SIZE_INVALID", "request size is outside the limit")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProtocolError("request", "INVALID_JSON", "request is not valid UTF-8 JSON") from error
    row = _mapping(payload, "request")
    _reject_forbidden_keys(row)
    keys = frozenset(row)
    if keys not in {REQUEST_KEYS, REQUEST_KEYS_WITH_REFERENCE}:
        raise ProtocolError("request", "REQUEST_FIELDS_INVALID", "request fields do not match the protocol")
    request_id = str(row.get("request_id", ""))
    asset_id = str(row.get("asset_id", ""))
    if not ID_PATTERN.fullmatch(request_id) or not ID_PATTERN.fullmatch(asset_id):
        raise ProtocolError("request", "IDENTIFIER_INVALID", "request or asset identifier is invalid")
    text = row.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT_CHARS:
        raise ProtocolError("request", "TEXT_INVALID", "text is empty or too large")
    parameters = _mapping(row.get("parameters"), "parameters")
    if frozenset(parameters) != PARAMETER_KEYS:
        raise ProtocolError("request", "PARAMETER_FIELDS_INVALID", "parameter fields do not match the protocol")
    voice = str(parameters.get("voice", ""))
    seed = parameters.get("seed")
    max_new_frames = parameters.get("max_new_frames")
    sample_mode = parameters.get("sample_mode")
    if not VOICE_PATTERN.fullmatch(voice):
        raise ProtocolError("request", "VOICE_INVALID", "voice is invalid")
    if isinstance(seed, bool) or not isinstance(seed, int) or not (0 <= seed <= 2**63 - 1):
        raise ProtocolError("request", "SEED_INVALID", "seed is invalid")
    if isinstance(max_new_frames, bool) or not isinstance(max_new_frames, int) or not (1 <= max_new_frames <= 2_000):
        raise ProtocolError("request", "FRAME_LIMIT_INVALID", "max_new_frames is invalid")
    if sample_mode not in {"greedy", "fixed", "full"}:
        raise ProtocolError("request", "SAMPLE_MODE_INVALID", "sample_mode is invalid")
    reference_audio = (
        _parse_reference_audio(row["reference_audio"], reference_audio_bytes)
        if "reference_audio" in row
        else None
    )
    if reference_audio_bytes is not None and reference_audio is None:
        raise ProtocolError("reference_audio", "REFERENCE_METADATA_REQUIRED", "reference metadata is required")
    return SynthesisRequest(
        request_id=request_id,
        asset_id=asset_id,
        text=text,
        voice=voice,
        seed=seed,
        max_new_frames=max_new_frames,
        sample_mode=sample_mode,
        reference_audio=reference_audio,
    )


def request_payload(request: SynthesisRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "request_id": request.request_id,
        "asset_id": request.asset_id,
        "text": request.text,
        "parameters": {
            "voice": request.voice,
            "seed": request.seed,
            "max_new_frames": request.max_new_frames,
            "sample_mode": request.sample_mode,
        },
    }
    if request.reference_audio is not None:
        payload["reference_audio"] = {
            "reference_asset_id": request.reference_audio.reference_asset_id,
            "declared_sha256": request.reference_audio.declared_sha256,
            "format": request.reference_audio.audio_format,
            "size_bytes": request.reference_audio.declared_size_bytes,
        }
    return payload


def build_multipart_body(request: SynthesisRequest, boundary: str) -> tuple[bytes, str]:
    if request.reference_audio is None:
        raise ProtocolError("client", "REFERENCE_BYTES_REQUIRED", "reference audio bytes are required")
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,70}", boundary):
        raise ProtocolError("client", "MULTIPART_BOUNDARY_INVALID", "multipart boundary is invalid")
    marker = f"--{boundary}".encode("ascii")
    metadata = canonical_json_bytes(request_payload(request))
    body = b"\r\n".join(
        [
            marker,
            b'Content-Disposition: form-data; name="metadata"',
            b"Content-Type: application/json",
            b"",
            metadata,
            marker,
            b'Content-Disposition: form-data; name="reference_audio"',
            f"Content-Type: audio/{request.reference_audio.audio_format}".encode("ascii"),
            b"",
            request.reference_audio.payload,
            marker + b"--",
            b"",
        ]
    )
    return body, f"multipart/form-data; boundary={boundary}"


def parse_multipart_body(body: bytes, content_type: str) -> tuple[bytes, bytes, str]:
    if not body or len(body) > MAX_MULTIPART_BYTES:
        raise ProtocolError("request", "REQUEST_SIZE_INVALID", "multipart request size is outside the limit")
    match = re.fullmatch(r"multipart/form-data;\s*boundary=([A-Za-z0-9_-]{16,70})", content_type)
    if not match:
        raise ProtocolError("request", "MULTIPART_CONTENT_TYPE_INVALID", "multipart content type is invalid")
    marker = f"--{match.group(1)}".encode("ascii")
    chunks = body.split(marker)
    if len(chunks) != 4 or chunks[0] != b"" or chunks[-1] not in {b"--", b"--\r\n"}:
        raise ProtocolError("request", "MULTIPART_INVALID", "multipart framing is invalid")
    parts: dict[str, tuple[bytes, bytes]] = {}
    for chunk in chunks[1:-1]:
        if not chunk.startswith(b"\r\n") or not chunk.endswith(b"\r\n"):
            raise ProtocolError("request", "MULTIPART_INVALID", "multipart delimiter framing is invalid")
        chunk = chunk[2:-2]
        header_blob, separator, payload = chunk.partition(b"\r\n\r\n")
        if not separator:
            raise ProtocolError("request", "MULTIPART_INVALID", "multipart part is invalid")
        try:
            headers = header_blob.decode("ascii", errors="strict").split("\r\n")
        except UnicodeDecodeError as error:
            raise ProtocolError("request", "MULTIPART_INVALID", "multipart headers are invalid") from error
        if len(headers) != 2:
            raise ProtocolError("request", "MULTIPART_PART_INVALID", "multipart part headers are invalid")
        disposition = next((line for line in headers if line.lower().startswith("content-disposition:")), "")
        if "filename=" in disposition.lower():
            raise ProtocolError("request", "REFERENCE_FILENAME_FORBIDDEN", "multipart filename is forbidden")
        name_match = re.fullmatch(r'Content-Disposition:\s*form-data;\s*name="([a-z_]+)"', disposition, re.IGNORECASE)
        if name_match is None or name_match.group(1) in parts:
            raise ProtocolError("request", "MULTIPART_PART_INVALID", "multipart part identity is invalid")
        content = next((line for line in headers if line.lower().startswith("content-type:")), "")
        parts[name_match.group(1)] = (content.split(":", 1)[-1].strip().encode("ascii"), payload)
    if frozenset(parts) != {"metadata", "reference_audio"}:
        raise ProtocolError("request", "MULTIPART_PARTS_INVALID", "multipart parts are invalid")
    if parts["metadata"][0] != b"application/json" or parts["reference_audio"][0] not in {b"audio/wav", b"audio/flac"}:
        raise ProtocolError("request", "MULTIPART_MEDIA_TYPE_INVALID", "multipart media type is invalid")
    media_format = parts["reference_audio"][0].decode("ascii").split("/", 1)[1]
    return parts["metadata"][1], parts["reference_audio"][1], media_format


def error_payload(error: ProtocolError, request_id: str | None = None) -> bytes:
    return canonical_json_bytes(
        {
            "protocol_version": PROTOCOL_VERSION,
            "request_id": request_id,
            "error": {
                "category": error.category,
                "code": error.code,
                "message_redacted": str(error),
                "retryable": error.retryable,
            },
        }
    )


def require_protocol_version(headers: Mapping[str, str]) -> None:
    if headers.get(VERSION_HEADER) != PROTOCOL_VERSION:
        raise ProtocolError("protocol", "VERSION_MISMATCH", "protocol version mismatch")
