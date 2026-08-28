"""Production MOSS Nano private Sidecar server.

This module is intentionally stdlib-only at import time.  The Nano runtime is
loaded only by an authenticated warmup request after all 29 pinned files have
been verified.  It owns neither database state nor media publication paths.
"""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
import gc
import hashlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import metadata
import io
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import tempfile
import threading
import time
from types import MappingProxyType
from typing import Final, Mapping
import unicodedata
from urllib.parse import urlsplit
from uuid import UUID
import wave

try:
    from .model_assets import (
        MODEL_INVENTORY_SHA256,
        MODEL_TREE_SHA256,
        SOURCE_TREE_SHA256,
        release_root,
        verify_release,
    )
except ImportError:  # Docker copies the three T1-B runtime modules flat.
    from model_assets import (  # type: ignore[no-redef]
        MODEL_INVENTORY_SHA256,
        MODEL_TREE_SHA256,
        SOURCE_TREE_SHA256,
        release_root,
        verify_release,
    )


PROTOCOL_VERSION: Final = "moss-tts-sidecar/1.1"
TOKEN_HEADER: Final = "X-MOSS-Sidecar-Token"
WORKER_TOKEN_HEADER: Final = "X-MOSS-Worker-Token"
VERSION_HEADER: Final = "X-MOSS-Protocol-Version"
REQUEST_ID_HEADER: Final = "X-MOSS-Request-ID"
GENERATION_HEADER: Final = "X-MOSS-Worker-Generation"
ACTUAL_MODEL_HEADER: Final = "X-MOSS-Actual-Model-Fingerprint-SHA256"
LOCAL_SCOPE_FINGERPRINT: Final = "8cd0df892dc4c7289e1182087e9ea8ec365c2d54d254d8aee5bd9252f5225095"
CAPABILITIES_SHA256: Final = "767153dce32afeb09b75c7b80fd653d9b112825820b505a733b8506d621375f8"
PRODUCTION_MODEL_FINGERPRINT_SHA256: Final = "3c76f3e9e1381699c5555287cf66eeb023632d0c3ee94adc6d8ae1b1d455fd7d"
TEST_MODEL_FINGERPRINT_SHA256: Final = "9846cd5d051a8dc124441d6704cd7db1d27f3db91c493b176c4d1a5643876ed3"
MAX_JSON_BYTES: Final = 64 * 1024
MAX_MULTIPART_BYTES: Final = 13 * 1024 * 1024
MAX_AUDIO_BYTES: Final = 16 * 1024 * 1024
MAX_REFERENCE_BYTES: Final = 12 * 1024 * 1024
MAX_REFERENCE_DURATION_SECONDS: Final = 12.5
MAX_TEXT_CHARS: Final = 4_000
MIN_TOKEN_CHARS: Final = 32
MAX_TOKEN_CHARS: Final = 128
MAX_REFERENCE_DECODED_BYTES: Final = 16 * 1024 * 1024
WORKER_LEASE_TTL_SECONDS: Final = 60
WORKER_LEASE_WATCHDOG_SECONDS: Final = 0.25
WORKER_LEASE_DRAIN_GRACE_SECONDS: Final = 10.0
WORKER_TOKEN_CHARS: Final = 43
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_VOICE = re.compile(r"^(?:onnx\.[A-Za-z0-9_-]{1,59}|[A-Za-z0-9_-]{1,64})$")
_BOUNDARY = re.compile(r"^[A-Za-z0-9_-]{16,70}$")
_RESTART_REASON = re.compile(r"^[A-Z][A-Z0-9_]{0,95}$")
_MODEL_KEYS = frozenset(
    {
        "adapter_contract_version",
        "model_name",
        "model_revision",
        "artifact_tree_sha256",
        "runtime_name",
        "runtime_version",
        "execution_backend",
        "protocol_version",
        "deployment_topology",
        "parameters",
        "schema_version",
    }
)
OFFICIAL_PRESET_MANIFEST_RELATIVE_PATH: Final = Path(
    "MOSS-TTS-Nano-100M-ONNX/browser_poc_manifest.json"
)
OFFICIAL_PRESET_MANIFEST_SHA256: Final = (
    "097d80e993dc29f0bae427590b4f77084a161cb578b50d82c29f455d5faa9eee"
)
OFFICIAL_PRESET_COUNT: Final = 18
OFFICIAL_PRESET_QUANTIZER_COUNT: Final = 16
_OFFICIAL_PRESET_MANIFEST_KEYS = frozenset(
    {
        "builtin_voices",
        "format_version",
        "generation_defaults",
        "model_files",
        "prompt_templates",
        "text_samples",
        "tts_config",
    }
)
_OFFICIAL_PRESET_ROW_KEYS = frozenset(
    {"voice", "display_name", "group", "audio_file", "prompt_audio_codes"}
)


class SidecarProtocolError(RuntimeError):
    def __init__(self, code: str, message: str, *, status: HTTPStatus = HTTPStatus.BAD_REQUEST, retryable: bool = False, poison: bool = False):
        super().__init__(message)
        self.code = code
        self.status = status
        self.retryable = retryable
        self.poison = poison


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _model_fingerprint_sha256(payload: Mapping[str, object]) -> str:
    if frozenset(payload) != _MODEL_KEYS:
        raise SidecarProtocolError("MODEL_FINGERPRINT_INVALID", "model fingerprint shape is invalid", poison=True)
    body = {key: payload[key] for key in _MODEL_KEYS if key != "schema_version"}
    envelope = {"schema_version": "moss-model-fingerprint/1", "payload": body}
    return _sha256(_canonical_bytes(envelope))


@dataclass(frozen=True, slots=True)
class OfficialPresetMetadata:
    """Non-secret projection of one row in the fixed official manifest."""

    preset_id: str
    manifest_voice: str
    display_name: str
    group: str
    audio_file: str
    prompt_frame_count: int
    prompt_codes_sha256: str


@dataclass(frozen=True, slots=True)
class OfficialPresetCatalog:
    manifest_sha256: str
    metadata_fingerprint_sha256: str
    voices: Mapping[str, str]
    presets: tuple[OfficialPresetMetadata, ...]


def _read_fixed_file(path: Path, *, maximum_bytes: int) -> bytes:
    descriptor: int | None = None
    try:
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            raise SidecarProtocolError(
                "OFFICIAL_PRESET_MANIFEST_OPEN_FAILED",
                "official preset manifest cannot be opened safely",
                status=HTTPStatus.SERVICE_UNAVAILABLE,
                poison=True,
            )
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | nofollow)
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or not (1 <= details.st_size <= maximum_bytes):
            raise SidecarProtocolError(
                "OFFICIAL_PRESET_MANIFEST_INVALID",
                "official preset manifest file is invalid",
                status=HTTPStatus.SERVICE_UNAVAILABLE,
                poison=True,
            )
        chunks: list[bytes] = []
        remaining = details.st_size
        while remaining:
            block = os.read(descriptor, min(remaining, 1024 * 1024))
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            len(raw) != details.st_size
            or (
                details.st_dev,
                details.st_ino,
                details.st_size,
                details.st_mtime_ns,
                details.st_ctime_ns,
            )
            != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            )
        ):
            raise SidecarProtocolError(
                "OFFICIAL_PRESET_MANIFEST_CHANGED",
                "official preset manifest changed while being read",
                status=HTTPStatus.SERVICE_UNAVAILABLE,
                poison=True,
            )
        return raw
    except FileNotFoundError as error:
        raise SidecarProtocolError(
            "OFFICIAL_PRESET_MANIFEST_MISSING",
            "official preset manifest is missing",
            status=HTTPStatus.SERVICE_UNAVAILABLE,
            poison=True,
        ) from error
    except SidecarProtocolError:
        raise
    except OSError as error:
        raise SidecarProtocolError(
            "OFFICIAL_PRESET_MANIFEST_OPEN_FAILED",
            "official preset manifest cannot be opened safely",
            status=HTTPStatus.SERVICE_UNAVAILABLE,
            poison=True,
        ) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def load_official_preset_catalog(
    path: Path,
    *,
    expected_sha256: str = OFFICIAL_PRESET_MANIFEST_SHA256,
) -> OfficialPresetCatalog:
    """Validate the exact ONNX manifest without retaining its prompt codes."""

    raw = _read_fixed_file(path, maximum_bytes=1024 * 1024)
    actual_sha256 = _sha256(raw)
    if actual_sha256 != expected_sha256:
        raise SidecarProtocolError(
            "OFFICIAL_PRESET_MANIFEST_HASH_MISMATCH",
            "official preset manifest hash differs from the fixed revision",
            status=HTTPStatus.SERVICE_UNAVAILABLE,
            poison=True,
        )
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SidecarProtocolError(
            "OFFICIAL_PRESET_MANIFEST_SCHEMA_INVALID",
            "official preset manifest is not valid UTF-8 JSON",
            status=HTTPStatus.SERVICE_UNAVAILABLE,
            poison=True,
        ) from error
    if (
        not isinstance(manifest, dict)
        or frozenset(manifest) != _OFFICIAL_PRESET_MANIFEST_KEYS
        or not isinstance(manifest.get("builtin_voices"), list)
        or isinstance(manifest.get("format_version"), bool)
        or not isinstance(manifest.get("format_version"), int)
        or not isinstance(manifest.get("generation_defaults"), dict)
        or not isinstance(manifest.get("model_files"), dict)
        or not isinstance(manifest.get("prompt_templates"), dict)
        or not isinstance(manifest.get("text_samples"), list)
        or not isinstance(manifest.get("tts_config"), dict)
    ):
        raise SidecarProtocolError(
            "OFFICIAL_PRESET_MANIFEST_SCHEMA_INVALID",
            "official preset manifest schema is invalid",
            status=HTTPStatus.SERVICE_UNAVAILABLE,
            poison=True,
        )
    rows = manifest["builtin_voices"]
    if len(rows) != OFFICIAL_PRESET_COUNT:
        raise SidecarProtocolError(
            "OFFICIAL_PRESET_COUNT_MISMATCH",
            "official preset count differs from the fixed revision",
            status=HTTPStatus.SERVICE_UNAVAILABLE,
            poison=True,
        )
    voices: dict[str, str] = {}
    presets: list[OfficialPresetMetadata] = []
    for row in rows:
        if not isinstance(row, dict) or frozenset(row) != _OFFICIAL_PRESET_ROW_KEYS:
            raise SidecarProtocolError(
                "OFFICIAL_PRESET_MANIFEST_SCHEMA_INVALID",
                "official preset row schema is invalid",
                status=HTTPStatus.SERVICE_UNAVAILABLE,
                poison=True,
            )
        voice = row["voice"]
        display_name = row["display_name"]
        group = row["group"]
        audio_file = row["audio_file"]
        if (
            not isinstance(voice, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,59}", voice)
            or not isinstance(display_name, str)
            or not display_name
            or not isinstance(group, str)
            or not group
            or not isinstance(audio_file, str)
            or not audio_file
            or Path(audio_file).name != audio_file
        ):
            raise SidecarProtocolError(
                "OFFICIAL_PRESET_MANIFEST_SCHEMA_INVALID",
                "official preset row metadata is invalid",
                status=HTTPStatus.SERVICE_UNAVAILABLE,
                poison=True,
            )
        preset_id = f"onnx.{voice}"
        if preset_id in voices:
            raise SidecarProtocolError(
                "OFFICIAL_PRESET_DUPLICATE",
                "official preset voice is duplicated",
                status=HTTPStatus.SERVICE_UNAVAILABLE,
                poison=True,
            )
        codes = row["prompt_audio_codes"]
        if (
            not isinstance(codes, list)
            or not codes
            or any(
                not isinstance(frame, list)
                or len(frame) != OFFICIAL_PRESET_QUANTIZER_COUNT
                or any(isinstance(code, bool) or not isinstance(code, int) for code in frame)
                for frame in codes
            )
        ):
            raise SidecarProtocolError(
                "OFFICIAL_PRESET_PROMPT_CODES_INVALID",
                "official preset prompt code shape is invalid",
                status=HTTPStatus.SERVICE_UNAVAILABLE,
                poison=True,
            )
        prompt_codes_sha256 = _sha256(_canonical_bytes(codes))
        voices[preset_id] = voice
        presets.append(
            OfficialPresetMetadata(
                preset_id=preset_id,
                manifest_voice=voice,
                display_name=display_name,
                group=group,
                audio_file=audio_file,
                prompt_frame_count=len(codes),
                prompt_codes_sha256=prompt_codes_sha256,
            )
        )
    projection = {
        "schema_version": "moss-official-preset-catalog/1",
        "manifest_sha256": actual_sha256,
        "presets": [
            {
                "preset_id": preset.preset_id,
                "manifest_voice": preset.manifest_voice,
                "display_name": preset.display_name,
                "group": preset.group,
                "audio_file": preset.audio_file,
                "prompt_frame_count": preset.prompt_frame_count,
                "prompt_codes_sha256": preset.prompt_codes_sha256,
            }
            for preset in presets
        ],
    }
    return OfficialPresetCatalog(
        manifest_sha256=actual_sha256,
        metadata_fingerprint_sha256=_sha256(_canonical_bytes(projection)),
        voices=MappingProxyType(voices),
        presets=tuple(presets),
    )


def read_secret_token(path: Path) -> str:
    if not path.is_absolute():
        raise SidecarProtocolError("TOKEN_FILE_INVALID", "token file must be an absolute secret path", status=HTTPStatus.INTERNAL_SERVER_ERROR)
    descriptor: int | None = None
    try:
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            raise SidecarProtocolError(
                "TOKEN_FILE_INVALID",
                "token secret open policy is unavailable",
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | nofollow)
        details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_nlink != 1
            or details.st_size > MAX_TOKEN_CHARS
            or stat.S_IMODE(details.st_mode) & 0o077
        ):
            raise SidecarProtocolError("TOKEN_FILE_INVALID", "token secret file is invalid", status=HTTPStatus.INTERNAL_SERVER_ERROR)
        chunks: list[bytes] = []
        remaining = MAX_TOKEN_CHARS + 1
        while remaining:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            (
                details.st_dev,
                details.st_ino,
                details.st_size,
                details.st_mtime_ns,
                details.st_ctime_ns,
            )
            != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            )
            or len(raw) != details.st_size
        ):
            raise SidecarProtocolError(
                "TOKEN_FILE_INVALID",
                "token secret changed while being read",
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        token = raw.decode("ascii")
    except (OSError, UnicodeDecodeError) as error:
        raise SidecarProtocolError("TOKEN_FILE_INVALID", "token secret file is unreadable", status=HTTPStatus.INTERNAL_SERVER_ERROR) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if not (MIN_TOKEN_CHARS <= len(token) <= MAX_TOKEN_CHARS) or any(
        not (0x21 <= byte <= 0x7E) for byte in raw
    ):
        raise SidecarProtocolError("TOKEN_CONFIGURATION_INVALID", "token secret value is invalid", status=HTTPStatus.INTERNAL_SERVER_ERROR)
    return token


def _request_uuid(raw: object) -> str:
    if not isinstance(raw, str):
        raise SidecarProtocolError("REQUEST_ID_INVALID", "request_id must be a canonical UUID")
    try:
        parsed = UUID(raw)
    except (ValueError, AttributeError) as error:
        raise SidecarProtocolError("REQUEST_ID_INVALID", "request_id must be a canonical UUID") from error
    if str(parsed) != raw:
        raise SidecarProtocolError("REQUEST_ID_INVALID", "request_id must be a canonical UUID")
    return raw


def _parse_json(body: bytes, expected_keys: frozenset[str]) -> dict[str, object]:
    if not body or len(body) > MAX_JSON_BYTES:
        raise SidecarProtocolError("REQUEST_SIZE_INVALID", "JSON body size is invalid")
    try:
        row = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SidecarProtocolError("INVALID_JSON", "body is not valid UTF-8 JSON") from error
    if not isinstance(row, dict) or frozenset(row) != expected_keys:
        raise SidecarProtocolError("REQUEST_FIELDS_INVALID", "request fields do not match protocol")
    return row


@dataclass(frozen=True, slots=True)
class ReferenceAudio:
    content_type: str
    actual_sha256: str
    payload: bytes
    duration_seconds: float


@dataclass(frozen=True, slots=True)
class ParsedSynthesisRequest:
    request_id: str
    scope_fingerprint: str
    requested_model_fingerprint_sha256: str
    text: str
    voice: str
    seed: int
    sample_mode: str
    max_new_frames: int
    reference_audio: ReferenceAudio | None


@dataclass(frozen=True, slots=True)
class AudioResult:
    payload: bytes
    sample_rate_hz: int
    channels: int
    sample_width_bytes: int


def _inspect_complete_pcm_wav(
    payload: bytes,
    *,
    maximum_bytes: int,
    reference: bool,
) -> tuple[int, int, int, int]:
    invalid_code = "REFERENCE_FORMAT_INVALID" if reference else "AUDIO_FORMAT_INVALID"
    boundary_code = (
        "REFERENCE_TRAILING_OR_TRUNCATED"
        if reference
        else "AUDIO_TRAILING_OR_TRUNCATED"
    )
    poison = not reference
    if (
        not payload
        or len(payload) > maximum_bytes
        or len(payload) < 44
        or payload[:4] != b"RIFF"
        or payload[8:12] != b"WAVE"
    ):
        raise SidecarProtocolError(
            invalid_code, "WAV container is invalid", poison=poison
        )
    if int.from_bytes(payload[4:8], "little") != len(payload) - 8:
        raise SidecarProtocolError(
            boundary_code,
            "WAV RIFF length differs from actual bytes",
            poison=poison,
        )
    offset = 12
    format_chunk: bytes | None = None
    data_chunk: bytes | None = None
    while offset < len(payload):
        if offset + 8 > len(payload):
            raise SidecarProtocolError(
                boundary_code, "WAV chunk header is truncated", poison=poison
            )
        chunk_name = payload[offset : offset + 4]
        chunk_size = int.from_bytes(payload[offset + 4 : offset + 8], "little")
        chunk_start = offset + 8
        chunk_end = chunk_start + chunk_size
        padded_end = chunk_end + (chunk_size & 1)
        if chunk_end > len(payload) or padded_end > len(payload):
            raise SidecarProtocolError(
                boundary_code, "WAV chunk is truncated", poison=poison
            )
        if chunk_name == b"fmt ":
            if format_chunk is not None or data_chunk is not None:
                raise SidecarProtocolError(
                    invalid_code, "WAV format chunk ordering is invalid", poison=poison
                )
            format_chunk = payload[chunk_start:chunk_end]
        elif chunk_name == b"data":
            if format_chunk is None or data_chunk is not None or padded_end != len(payload):
                raise SidecarProtocolError(
                    boundary_code,
                    "WAV data chunk is duplicated or followed by trailing chunks",
                    poison=poison,
                )
            data_chunk = payload[chunk_start:chunk_end]
        elif not reference:
            raise SidecarProtocolError(
                invalid_code,
                "backend WAV contains a non-canonical chunk",
                poison=True,
            )
        offset = padded_end
    if format_chunk is None or data_chunk is None or len(format_chunk) < 16:
        raise SidecarProtocolError(
            invalid_code, "WAV chunks are incomplete", poison=poison
        )
    audio_format = int.from_bytes(format_chunk[0:2], "little")
    channels = int.from_bytes(format_chunk[2:4], "little")
    sample_rate = int.from_bytes(format_chunk[4:8], "little")
    byte_rate = int.from_bytes(format_chunk[8:12], "little")
    block_align = int.from_bytes(format_chunk[12:14], "little")
    bits_per_sample = int.from_bytes(format_chunk[14:16], "little")
    sample_width = bits_per_sample // 8
    if (
        audio_format != 1
        or not (1 <= channels <= 8)
        or not (8_000 <= sample_rate <= 192_000)
        or sample_width not in {1, 2, 3, 4}
        or block_align != channels * sample_width
        or byte_rate != sample_rate * block_align
        or not data_chunk
        or len(data_chunk) % block_align
        or len(data_chunk) > MAX_REFERENCE_DECODED_BYTES
    ):
        raise SidecarProtocolError(
            invalid_code, "WAV PCM parameters are invalid", poison=poison
        )
    frames = len(data_chunk) // block_align
    try:
        with wave.open(io.BytesIO(payload), "rb") as wav_file:
            observed = (
                wav_file.getframerate(),
                wav_file.getnchannels(),
                wav_file.getsampwidth(),
                wav_file.getnframes(),
            )
            decoded = wav_file.readframes(frames)
            exhausted = wav_file.readframes(1)
    except (wave.Error, EOFError) as error:
        raise SidecarProtocolError(
            invalid_code, "WAV cannot be fully decoded", poison=poison
        ) from error
    if (
        observed != (sample_rate, channels, sample_width, frames)
        or len(decoded) != len(data_chunk)
        or exhausted
    ):
        raise SidecarProtocolError(
            boundary_code,
            "WAV decoded frames differ from the declared data chunk",
            poison=poison,
        )
    return sample_rate, channels, sample_width, frames


def _load_soundfile():  # noqa: ANN201
    try:
        import soundfile  # type: ignore[import-not-found]
    except (ImportError, OSError) as error:
        raise SidecarProtocolError(
            "REFERENCE_DECODER_UNAVAILABLE",
            "fixed FLAC decoder is unavailable",
            status=HTTPStatus.SERVICE_UNAVAILABLE,
        ) from error
    return soundfile


def _inspect_flac(payload: bytes) -> float:
    soundfile = _load_soundfile()
    try:
        with soundfile.SoundFile(io.BytesIO(payload), mode="r") as stream:
            sample_rate = int(stream.samplerate)
            channels = int(stream.channels)
            frames = int(stream.frames)
            if (
                str(stream.format).upper() != "FLAC"
                or not (8_000 <= sample_rate <= 192_000)
                or not (1 <= channels <= 8)
                or frames <= 0
                or frames * channels * 2 > MAX_REFERENCE_DECODED_BYTES
            ):
                raise SidecarProtocolError(
                    "REFERENCE_FORMAT_INVALID", "reference FLAC metadata is invalid"
                )
            decoded_frames = 0
            while decoded_frames < frames:
                wanted = min(65_536, frames - decoded_frames)
                block = bytes(stream.buffer_read(wanted, dtype="int16"))
                if not block:
                    raise SidecarProtocolError(
                        "REFERENCE_FORMAT_INVALID",
                        "reference FLAC ended before its declared frames",
                    )
                frame_width = channels * 2
                if len(block) % frame_width:
                    raise SidecarProtocolError(
                        "REFERENCE_FORMAT_INVALID",
                        "reference FLAC decoded frame alignment is invalid",
                    )
                decoded_frames += len(block) // frame_width
                if decoded_frames > frames:
                    raise SidecarProtocolError(
                        "REFERENCE_FORMAT_INVALID",
                        "reference FLAC decoded beyond its declared frames",
                    )
            if bytes(stream.buffer_read(1, dtype="int16")) != b"":
                raise SidecarProtocolError(
                    "REFERENCE_FORMAT_INVALID",
                    "reference FLAC contains undeclared decoded frames",
                )
    except SidecarProtocolError:
        raise
    except Exception as error:
        raise SidecarProtocolError(
            "REFERENCE_FORMAT_INVALID", "reference FLAC cannot be fully decoded"
        ) from error
    return frames / sample_rate


def _inspect_reference(payload: bytes, content_type: str) -> float:
    if not (1 <= len(payload) <= MAX_REFERENCE_BYTES):
        raise SidecarProtocolError("REFERENCE_SIZE_INVALID", "reference audio size is invalid")
    if content_type == "audio/wav":
        sample_rate, _, _, frames = _inspect_complete_pcm_wav(
            payload,
            maximum_bytes=MAX_REFERENCE_BYTES,
            reference=True,
        )
        duration = frames / sample_rate
    elif content_type == "audio/flac":
        duration = _inspect_flac(payload)
    else:
        raise SidecarProtocolError("REFERENCE_CONTENT_TYPE_INVALID", "reference content type is not allowed")
    if not (0 < duration <= MAX_REFERENCE_DURATION_SECONDS):
        raise SidecarProtocolError("REFERENCE_DURATION_INVALID", "reference duration is outside limit")
    return duration


def _parse_metadata(body: bytes, reference: tuple[str, bytes] | None) -> ParsedSynthesisRequest:
    keys = frozenset(
        {
            "request_id",
            "scope_fingerprint",
            "requested_model_fingerprint_sha256",
            "text",
            "voice",
            "seed",
            "sample_mode",
            "max_new_frames",
        }
    )
    expected = keys | ({"reference_audio"} if reference is not None else set())
    row = _parse_json(body, frozenset(expected))
    request_id = _request_uuid(row["request_id"])
    if row["scope_fingerprint"] != LOCAL_SCOPE_FINGERPRINT:
        raise SidecarProtocolError("SCOPE_MISMATCH", "scope fingerprint mismatch", status=HTTPStatus.FORBIDDEN)
    requested = row["requested_model_fingerprint_sha256"]
    if not isinstance(requested, str) or not _SHA256.fullmatch(requested):
        raise SidecarProtocolError("REQUESTED_MODEL_INVALID", "requested model fingerprint is invalid")
    text = row["text"]
    voice = row["voice"]
    seed = row["seed"]
    sample_mode = row["sample_mode"]
    frames = row["max_new_frames"]
    if (
        not isinstance(text, str)
        or not text.strip()
        or len(text) > MAX_TEXT_CHARS
        or text != unicodedata.normalize("NFC", text)
        or "\ufffd" in text
        or any(
            unicodedata.category(character) == "Cs"
            or (
                unicodedata.category(character) == "Cc"
                and character not in "\t\n\r"
            )
            for character in text
        )
    ):
        raise SidecarProtocolError("TEXT_INVALID", "text is invalid")
    if not isinstance(voice, str) or not _VOICE.fullmatch(voice):
        raise SidecarProtocolError("VOICE_INVALID", "voice is invalid")
    if isinstance(seed, bool) or not isinstance(seed, int) or not (0 <= seed <= 2**63 - 1):
        raise SidecarProtocolError("SEED_INVALID", "seed is invalid")
    if sample_mode not in {"greedy", "fixed", "full"}:
        raise SidecarProtocolError("SAMPLE_MODE_INVALID", "sample mode is invalid")
    if isinstance(frames, bool) or not isinstance(frames, int) or not (1 <= frames <= 2_000):
        raise SidecarProtocolError("FRAME_LIMIT_INVALID", "max_new_frames is invalid")
    parsed_reference = None
    if reference is not None:
        metadata_row = row["reference_audio"]
        if not isinstance(metadata_row, dict) or frozenset(metadata_row) != {"content_type", "actual_sha256", "size_bytes"}:
            raise SidecarProtocolError("REFERENCE_METADATA_INVALID", "reference metadata is invalid")
        content_type, payload = reference
        declared_type = metadata_row["content_type"]
        declared_hash = metadata_row["actual_sha256"]
        declared_size = metadata_row["size_bytes"]
        if declared_type != content_type or declared_size != len(payload) or not isinstance(declared_size, int):
            raise SidecarProtocolError("REFERENCE_METADATA_MISMATCH", "reference metadata differs from bytes")
        if not isinstance(declared_hash, str) or _sha256(payload) != declared_hash:
            raise SidecarProtocolError("REFERENCE_HASH_MISMATCH", "reference hash differs from bytes")
        parsed_reference = ReferenceAudio(content_type, declared_hash, payload, _inspect_reference(payload, content_type))
    return ParsedSynthesisRequest(request_id, LOCAL_SCOPE_FINGERPRINT, requested, text, voice, seed, str(sample_mode), frames, parsed_reference)


def parse_multipart(body: bytes, content_type: str) -> tuple[bytes, tuple[str, bytes]]:
    if not body or len(body) > MAX_MULTIPART_BYTES:
        raise SidecarProtocolError("REQUEST_SIZE_INVALID", "multipart body size is invalid")
    match = re.fullmatch(r"multipart/form-data;\s*boundary=([A-Za-z0-9_-]{16,70})", content_type)
    if match is None:
        raise SidecarProtocolError("MULTIPART_CONTENT_TYPE_INVALID", "multipart content type is invalid")
    marker = f"--{match.group(1)}".encode("ascii")
    chunks = body.split(marker)
    if len(chunks) != 4 or chunks[0] != b"" or chunks[-1] not in {b"--", b"--\r\n"}:
        raise SidecarProtocolError("MULTIPART_INVALID", "multipart framing is invalid")
    parts: dict[str, tuple[str, bytes]] = {}
    for chunk in chunks[1:-1]:
        if not chunk.startswith(b"\r\n") or not chunk.endswith(b"\r\n"):
            raise SidecarProtocolError("MULTIPART_INVALID", "multipart delimiter framing is invalid")
        header_blob, separator, payload = chunk[2:-2].partition(b"\r\n\r\n")
        if not separator:
            raise SidecarProtocolError("MULTIPART_INVALID", "multipart part is invalid")
        try:
            lines = header_blob.decode("ascii").split("\r\n")
        except UnicodeDecodeError as error:
            raise SidecarProtocolError("MULTIPART_INVALID", "multipart headers are invalid") from error
        if len(lines) != 2 or any("filename=" in line.lower() for line in lines):
            raise SidecarProtocolError("MULTIPART_HEADERS_INVALID", "multipart headers are invalid")
        disposition = next((line for line in lines if line.lower().startswith("content-disposition:")), "")
        media = next((line for line in lines if line.lower().startswith("content-type:")), "")
        name = re.fullmatch(r'Content-Disposition:\s*form-data;\s*name="([a-z_]+)"', disposition, re.IGNORECASE)
        if name is None or name.group(1) in parts:
            raise SidecarProtocolError("MULTIPART_PART_INVALID", "multipart part identity is invalid")
        parts[name.group(1)] = (media.split(":", 1)[-1].strip().lower(), payload)
    if frozenset(parts) != {"metadata", "reference_audio"} or parts["metadata"][0] != "application/json" or parts["reference_audio"][0] not in {"audio/wav", "audio/flac"}:
        raise SidecarProtocolError("MULTIPART_PARTS_INVALID", "multipart parts are invalid")
    return parts["metadata"][1], parts["reference_audio"]


def _validate_wav(payload: bytes) -> tuple[int, int, int]:
    values = _inspect_complete_pcm_wav(
        payload,
        maximum_bytes=MAX_AUDIO_BYTES,
        reference=False,
    )[:3]
    if values != (48_000, 2, 2):
        raise SidecarProtocolError("AUDIO_FORMAT_DRIFT", "backend WAV format differs from contract", poison=True)
    return values


class Backend:
    is_test_backend = False

    def warmup(self) -> Mapping[str, object]:
        raise NotImplementedError

    def synthesize(self, request: ParsedSynthesisRequest, cancelled: threading.Event) -> bytes:
        raise NotImplementedError

    def unload(self) -> None:
        """Release model/runtime memory after the worker lease becomes inert."""

        return


class FakeBackend(Backend):
    is_test_backend = True

    def __init__(self, *, step_delay_seconds: float = 0.0, fail_mode: str | None = None):
        self.step_delay_seconds = step_delay_seconds
        self.fail_mode = fail_mode
        self.unload_count = 0

    def warmup(self) -> Mapping[str, object]:
        return {
            "adapter_contract_version": "moss-nano-tts-adapter/1",
            "model_name": "fake-moss-nano-sidecar",
            "model_revision": "test-double/1",
            "artifact_tree_sha256": hashlib.sha256(b"fake-moss-nano-sidecar").hexdigest(),
            "runtime_name": "python-stdlib-fake",
            "runtime_version": "1",
            "execution_backend": "deterministic-test-double",
            "protocol_version": PROTOCOL_VERSION,
            "deployment_topology": "test-only",
            "parameters": {"test_double": True},
            "schema_version": "moss-model-fingerprint/1",
        }

    def synthesize(self, request: ParsedSynthesisRequest, cancelled: threading.Event) -> bytes:
        if self.fail_mode == "crash":
            raise RuntimeError("injected backend failure")
        for _ in range(5):
            if self.step_delay_seconds:
                time.sleep(self.step_delay_seconds)
        frames = hashlib.sha256(f"{request.text}\0{request.voice}\0{request.seed}\0{request.sample_mode}".encode()).digest() * 128
        samples = bytearray()
        for index in range(0, len(frames), 2):
            sample = int.from_bytes(frames[index : index + 2], "little", signed=False) - 32768
            samples.extend(int(sample).to_bytes(2, "little", signed=True) * 2)
        output = io.BytesIO()
        with wave.open(output, "wb") as wav_file:
            wav_file.setnchannels(2)
            wav_file.setsampwidth(2)
            wav_file.setframerate(48_000)
            wav_file.writeframes(bytes(samples))
        return output.getvalue()

    def unload(self) -> None:
        self.unload_count += 1


class NanoBackend(Backend):
    def __init__(self, *, lock_path: Path, assets_root: Path, cpu_threads: int = 4):
        self.lock_path = lock_path
        self.assets_root = assets_root
        self.cpu_threads = cpu_threads
        self._runtime = None
        self._fingerprint: Mapping[str, object] | None = None
        self._official_preset_catalog: OfficialPresetCatalog | None = None

    @property
    def official_preset_catalog(self) -> OfficialPresetCatalog | None:
        return self._official_preset_catalog

    def warmup(self) -> Mapping[str, object]:
        if self._runtime is not None and self._fingerprint is not None:
            return self._fingerprint
        verified = verify_release(
            self.lock_path,
            self.assets_root,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
        )
        release = release_root(self.assets_root)
        source = release / "source"
        models = release / "models"
        preset_catalog = load_official_preset_catalog(
            models / OFFICIAL_PRESET_MANIFEST_RELATIVE_PATH
        )
        sys.path.insert(0, str(source.resolve()))
        try:
            from onnx_tts_runtime import OnnxTtsRuntime
        except Exception as error:
            raise SidecarProtocolError("MODEL_IMPORT_FAILED", "verified model runtime import failed", status=HTTPStatus.SERVICE_UNAVAILABLE, poison=True) from error
        runtime = OnnxTtsRuntime(
            model_dir=models.resolve(),
            thread_count=self.cpu_threads,
            max_new_frames=375,
            sample_mode="fixed",
            execution_provider="cpu",
            output_dir=Path("/tmp/moss-output"),
        )
        fingerprint = {
            "adapter_contract_version": "moss-nano-tts-adapter/1",
            "model_name": "OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX+MOSS-Audio-Tokenizer-Nano-ONNX",
            "model_revision": "f52645cb467506d8e18e746ddd59482685b74e58+ceff0d0749bfb3fa2d61149794ec6feef0d1e1ae",
            "artifact_tree_sha256": MODEL_INVENTORY_SHA256,
            "runtime_name": "onnxruntime",
            "runtime_version": metadata.version("onnxruntime"),
            "execution_backend": "cpu",
            "protocol_version": PROTOCOL_VERSION,
            "deployment_topology": "linux_arm64_private_sidecar",
            "parameters": {
                "cpu_threads": self.cpu_threads,
                "source_tree_sha256": SOURCE_TREE_SHA256,
                "model_tree_sha256": MODEL_TREE_SHA256,
            },
            "schema_version": "moss-model-fingerprint/1",
        }
        if verified["source_tree_sha256"] != SOURCE_TREE_SHA256 or verified["model_tree_sha256"] != MODEL_TREE_SHA256:
            raise SidecarProtocolError("MODEL_TREE_MISMATCH", "verified model tree changed", status=HTTPStatus.SERVICE_UNAVAILABLE, poison=True)
        self._runtime = runtime
        self._fingerprint = fingerprint
        self._official_preset_catalog = preset_catalog
        return fingerprint

    def synthesize(self, request: ParsedSynthesisRequest, cancelled: threading.Event) -> bytes:
        if self._runtime is None:
            raise SidecarProtocolError("MODEL_NOT_READY", "model must be warmed before synthesis", status=HTTPStatus.SERVICE_UNAVAILABLE, retryable=True)
        runtime_voice = request.voice
        if request.reference_audio is None:
            if not request.voice.startswith("onnx."):
                raise SidecarProtocolError(
                    "OFFICIAL_PRESET_ID_INVALID",
                    "preset synthesis requires an exact external preset id",
                )
            catalog = self._official_preset_catalog
            if catalog is None:
                raise SidecarProtocolError(
                    "OFFICIAL_PRESET_CATALOG_NOT_READY",
                    "official preset catalog must be verified before synthesis",
                    status=HTTPStatus.SERVICE_UNAVAILABLE,
                    poison=True,
                )
            try:
                runtime_voice = catalog.voices[request.voice]
            except KeyError as error:
                raise SidecarProtocolError(
                    "OFFICIAL_PRESET_NOT_FOUND",
                    "official preset id is not in the fixed manifest",
                ) from error
        output_root = Path("/tmp/moss-output")
        output_root.mkdir(parents=True, exist_ok=True)
        output = output_root / f"{request.request_id}.wav"
        reference: Path | None = None
        try:
            if request.reference_audio is not None:
                suffix = ".wav" if request.reference_audio.content_type == "audio/wav" else ".flac"
                fd, raw_path = tempfile.mkstemp(prefix="reference-", suffix=suffix, dir="/tmp")
                reference = Path(raw_path)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(request.reference_audio.payload)
                    stream.flush()
                    os.fsync(stream.fileno())
            result = self._runtime.synthesize(
                text=request.text,
                voice=runtime_voice,
                prompt_audio_path=reference,
                output_audio_path=output,
                sample_mode=request.sample_mode,
                do_sample=request.sample_mode != "greedy",
                streaming=True,
                max_new_frames=request.max_new_frames,
                enable_wetext=False,
                enable_normalize_tts_text=True,
                seed=request.seed,
                voice_clone_max_text_tokens=750,
            )
            produced = Path(str(result["audio_path"])).resolve()
            if produced != output.resolve():
                raise SidecarProtocolError("OUTPUT_IDENTITY_MISMATCH", "backend output identity mismatch", poison=True)
            return produced.read_bytes()
        finally:
            output.unlink(missing_ok=True)
            if reference is not None:
                reference.unlink(missing_ok=True)

    def unload(self) -> None:
        # ONNX Runtime releases native sessions when the last Python owner is
        # dropped.  Clear both references before collecting so an expired
        # worker lease cannot retain a ready model in the idle Sidecar.
        runtime = self._runtime
        self._runtime = None
        self._fingerprint = None
        self._official_preset_catalog = None
        if runtime is not None:
            del runtime
        gc.collect()


@dataclass(slots=True)
class ActiveRequest:
    cancelled: threading.Event


class SidecarState:
    def __init__(self, token: str, backend: Backend):
        self.token = token
        self.backend = backend
        self.pid = os.getpid()
        self.generation = secrets.randbelow(2**63 - 1) + 1
        self.started_at = time.monotonic()
        self.status = "unloaded"
        self.model_fingerprint: Mapping[str, object] | None = None
        self.model_fingerprint_sha256: str | None = None
        self.active: dict[str, ActiveRequest] = {}
        self.terminal = deque(maxlen=1024)
        self.lock = threading.Lock()
        self.condition = threading.Condition(self.lock)
        self.warmup_lock = threading.Lock()
        self.poisoned = False
        self.worker_token: str | None = None
        self.worker_lease_deadline: float | None = None
        self.worker_lease_generation = 0

    def _worker_lease_valid_locked(self, worker_token: str) -> bool:
        return (
            self.worker_token is not None
            and self.worker_lease_deadline is not None
            and time.monotonic() < self.worker_lease_deadline
            and secrets.compare_digest(self.worker_token, worker_token)
        )

    def _begin_deactivate_locked(self) -> None:
        self.worker_token = None
        self.worker_lease_deadline = None
        for request in self.active.values():
            request.cancelled.set()
        self.status = "draining"
        self.model_fingerprint = None
        self.model_fingerprint_sha256 = None
        self.condition.notify_all()

    def acquire_worker_lease(self) -> tuple[str, int]:
        """Replace an idle lease and immediately fence the previous token."""

        with self.lock:
            if self.poisoned:
                raise SidecarProtocolError(
                    "SIDECAR_POISONED",
                    "sidecar requires restart",
                    status=HTTPStatus.SERVICE_UNAVAILABLE,
                    poison=True,
                )
            if self.status in {"warming", "draining"} or self.active:
                raise SidecarProtocolError(
                    "SIDECAR_BUSY",
                    "sidecar cannot replace an active worker lease",
                    status=HTTPStatus.CONFLICT,
                    retryable=True,
                )
            worker_token = secrets.token_urlsafe(32)
            if len(worker_token) != WORKER_TOKEN_CHARS:
                raise SidecarProtocolError(
                    "WORKER_TOKEN_GENERATION_FAILED",
                    "worker token generation failed",
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                    poison=True,
                )
            self.worker_lease_generation += 1
            self.worker_token = worker_token
            self.worker_lease_deadline = (
                time.monotonic() + WORKER_LEASE_TTL_SECONDS
            )
            return worker_token, self.worker_lease_generation

    def validate_worker_lease(self, worker_token: str) -> int:
        with self.lock:
            if self._worker_lease_valid_locked(worker_token):
                return self.worker_lease_generation
            if (
                self.worker_token is not None
                and self.worker_lease_deadline is not None
                and time.monotonic() >= self.worker_lease_deadline
            ):
                self._begin_deactivate_locked()
            raise SidecarProtocolError(
                "WORKER_LEASE_INVALID",
                "worker lease is invalid",
                status=HTTPStatus.UNAUTHORIZED,
            )

    def renew_worker_lease(self, worker_token: str) -> int:
        with self.lock:
            if not self._worker_lease_valid_locked(worker_token):
                if (
                    self.worker_token is not None
                    and self.worker_lease_deadline is not None
                    and time.monotonic() >= self.worker_lease_deadline
                ):
                    self._begin_deactivate_locked()
                raise SidecarProtocolError(
                    "WORKER_LEASE_INVALID",
                    "worker lease is invalid",
                    status=HTTPStatus.UNAUTHORIZED,
                )
            self.worker_lease_deadline = (
                time.monotonic() + WORKER_LEASE_TTL_SECONDS
            )
            return self.worker_lease_generation

    def release_worker_lease(self, worker_token: str) -> int:
        with self.lock:
            if not self._worker_lease_valid_locked(worker_token):
                if (
                    self.worker_token is not None
                    and self.worker_lease_deadline is not None
                    and time.monotonic() >= self.worker_lease_deadline
                ):
                    self._begin_deactivate_locked()
                raise SidecarProtocolError(
                    "WORKER_LEASE_INVALID",
                    "worker lease is invalid",
                    status=HTTPStatus.UNAUTHORIZED,
                )
            lease_generation = self.worker_lease_generation
            self._begin_deactivate_locked()
            return lease_generation

    def expire_worker_lease_if_needed(self) -> bool:
        with self.lock:
            if (
                self.worker_token is None
                or self.worker_lease_deadline is None
                or time.monotonic() < self.worker_lease_deadline
            ):
                return False
            self._begin_deactivate_locked()
            return True

    def finish_deactivate(self, timeout_seconds: float) -> bool:
        """Drain active work and release backend state without a new lease."""

        deadline = time.monotonic() + timeout_seconds
        with self.condition:
            while self.active:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self.condition.wait(timeout=remaining)
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not self.warmup_lock.acquire(timeout=remaining):
            return False
        try:
            with self.lock:
                if self.active or self.worker_token is not None:
                    return False
            unload_finished = threading.Event()
            unload_errors: list[BaseException] = []

            def unload_backend() -> None:
                try:
                    self.backend.unload()
                except BaseException as error:
                    unload_errors.append(error)
                finally:
                    unload_finished.set()

            # Native runtime teardown is not trusted to respect Python-level
            # cancellation.  Keep it on a daemon thread so a bounded timeout
            # can poison this process and let the supervisor replace it.
            threading.Thread(
                target=unload_backend,
                name="moss-sidecar-backend-unload",
                daemon=True,
            ).start()
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not unload_finished.wait(timeout=remaining):
                return False
            if unload_errors:
                return False
            with self.lock:
                if self.worker_token is not None:
                    return False
                self.status = "unloaded"
                self.model_fingerprint = None
                self.model_fingerprint_sha256 = None
                self.condition.notify_all()
            return True
        finally:
            self.warmup_lock.release()

    def begin_request(
        self,
        request_id: str,
        worker_token: str,
    ) -> threading.Event:
        with self.lock:
            if not self._worker_lease_valid_locked(worker_token):
                if (
                    self.worker_token is not None
                    and self.worker_lease_deadline is not None
                    and time.monotonic() >= self.worker_lease_deadline
                ):
                    self._begin_deactivate_locked()
                raise SidecarProtocolError(
                    "WORKER_LEASE_INVALID",
                    "worker lease is invalid",
                    status=HTTPStatus.UNAUTHORIZED,
                )
            if self.status != "ready" or self.model_fingerprint_sha256 is None:
                raise SidecarProtocolError(
                    "MODEL_NOT_READY",
                    "warmup is required",
                    status=HTTPStatus.SERVICE_UNAVAILABLE,
                    retryable=True,
                )
            if self.active:
                raise SidecarProtocolError(
                    "SIDECAR_BUSY",
                    "single inference slot is occupied",
                    status=HTTPStatus.TOO_MANY_REQUESTS,
                    retryable=True,
                )
            cancelled = threading.Event()
            self.active[request_id] = ActiveRequest(cancelled)
            return cancelled

    def finish_request(self, request_id: str) -> None:
        with self.condition:
            self.active.pop(request_id, None)
            self.terminal.append(request_id)
            self.condition.notify_all()

    def commit_request_for_publication(
        self,
        request_id: str,
        worker_token: str,
    ) -> bool:
        """Atomically fence the lease and commit one response for publication."""

        with self.condition:
            active = self.active.get(request_id)
            allowed = (
                active is not None
                and not active.cancelled.is_set()
                and self._worker_lease_valid_locked(worker_token)
            )
            self.active.pop(request_id, None)
            self.terminal.append(request_id)
            self.condition.notify_all()
            return allowed

    def cancel_request(self, request_id: str, worker_token: str) -> str:
        with self.lock:
            if not self._worker_lease_valid_locked(worker_token):
                if (
                    self.worker_token is not None
                    and self.worker_lease_deadline is not None
                    and time.monotonic() >= self.worker_lease_deadline
                ):
                    self._begin_deactivate_locked()
                raise SidecarProtocolError(
                    "WORKER_LEASE_INVALID",
                    "worker lease is invalid",
                    status=HTTPStatus.UNAUTHORIZED,
                )
            active = self.active.get(request_id)
            if active is not None:
                active.cancelled.set()
                return "requested"
            if request_id in self.terminal:
                return "already_terminal"
            return "not_found"

    def worker_lease_is_current(self, worker_token: str) -> bool:
        with self.lock:
            return self._worker_lease_valid_locked(worker_token)

    def warmup(self, worker_token: str) -> None:
        # Only the winning request may load the model.  Contenders wait for
        # that exact attempt and then observe its ready/poisoned terminal state.
        with self.warmup_lock:
            with self.lock:
                if not self._worker_lease_valid_locked(worker_token):
                    if (
                        self.worker_token is not None
                        and self.worker_lease_deadline is not None
                        and time.monotonic() >= self.worker_lease_deadline
                    ):
                        self._begin_deactivate_locked()
                    raise SidecarProtocolError(
                        "WORKER_LEASE_INVALID",
                        "worker lease is invalid",
                        status=HTTPStatus.UNAUTHORIZED,
                    )
                if self.poisoned:
                    raise SidecarProtocolError(
                        "SIDECAR_POISONED",
                        "sidecar requires restart",
                        status=HTTPStatus.SERVICE_UNAVAILABLE,
                        poison=True,
                    )
                if self.status == "ready":
                    return
                self.status = "warming"
            try:
                fingerprint = self.backend.warmup()
                digest = _model_fingerprint_sha256(fingerprint)
                expected_digest = (
                    TEST_MODEL_FINGERPRINT_SHA256
                    if self.backend.is_test_backend
                    else PRODUCTION_MODEL_FINGERPRINT_SHA256
                )
                if digest != expected_digest:
                    raise SidecarProtocolError(
                        "MODEL_FINGERPRINT_MISMATCH",
                        "model fingerprint differs from the frozen runtime identity",
                        status=HTTPStatus.SERVICE_UNAVAILABLE,
                        poison=True,
                    )
            except SidecarProtocolError:
                with self.lock:
                    if self.status != "draining":
                        self.status = "unavailable"
                        self.model_fingerprint = None
                        self.model_fingerprint_sha256 = None
                raise
            except Exception as error:
                with self.lock:
                    self.status = "unavailable"
                    self.poisoned = True
                    self.model_fingerprint = None
                    self.model_fingerprint_sha256 = None
                raise SidecarProtocolError(
                    "MODEL_WARMUP_FAILED",
                    "model warmup failed",
                    status=HTTPStatus.SERVICE_UNAVAILABLE,
                    poison=True,
                ) from error
            with self.lock:
                if not self._worker_lease_valid_locked(worker_token):
                    self._begin_deactivate_locked()
                    raise SidecarProtocolError(
                        "WORKER_LEASE_INVALID",
                        "worker lease expired during warmup",
                        status=HTTPStatus.UNAUTHORIZED,
                    )
                self.model_fingerprint = fingerprint
                self.model_fingerprint_sha256 = digest
                self.status = "ready"

    def poison(self) -> None:
        with self.lock:
            self.poisoned = True
            self.status = "poisoned"


class SidecarHandler(BaseHTTPRequestHandler):
    server_version = "MOSSProductionSidecar/1.1"

    @property
    def state(self) -> SidecarState:
        return self.server.state  # type: ignore[attr-defined]

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _route(self) -> str:
        parsed = urlsplit(self.path)
        if parsed.query or parsed.fragment:
            raise SidecarProtocolError("QUERY_FORBIDDEN", "query strings are forbidden")
        return parsed.path

    def _authenticate_version(self) -> None:
        versions = self.headers.get_all(VERSION_HEADER, [])
        if len(versions) != 1 or versions[0] != PROTOCOL_VERSION:
            raise SidecarProtocolError("VERSION_MISMATCH", "protocol version mismatch", status=HTTPStatus.UPGRADE_REQUIRED)

    def _authenticate_control(self) -> None:
        self._authenticate_version()
        tokens = self.headers.get_all(TOKEN_HEADER, [])
        worker_tokens = self.headers.get_all(WORKER_TOKEN_HEADER, [])
        if worker_tokens:
            raise SidecarProtocolError(
                "AUTHENTICATION_FAILED",
                "authentication failed",
                status=HTTPStatus.UNAUTHORIZED,
            )
        if len(tokens) != 1 or not secrets.compare_digest(self.state.token, tokens[0]):
            raise SidecarProtocolError("AUTHENTICATION_FAILED", "authentication failed", status=HTTPStatus.UNAUTHORIZED)

    def _authenticate_worker(self) -> str:
        self._authenticate_version()
        control_tokens = self.headers.get_all(TOKEN_HEADER, [])
        worker_tokens = self.headers.get_all(WORKER_TOKEN_HEADER, [])
        if control_tokens or len(worker_tokens) != 1:
            raise SidecarProtocolError(
                "WORKER_LEASE_INVALID",
                "worker lease is invalid",
                status=HTTPStatus.UNAUTHORIZED,
            )
        worker_token = worker_tokens[0]
        try:
            self.state.validate_worker_lease(worker_token)
        except SidecarProtocolError:
            self._schedule_drain_if_needed()
            raise
        return worker_token

    def _authenticate_health(self) -> None:
        self._authenticate_version()
        control_tokens = self.headers.get_all(TOKEN_HEADER, [])
        worker_tokens = self.headers.get_all(WORKER_TOKEN_HEADER, [])
        if len(control_tokens) == 1 and not worker_tokens:
            if secrets.compare_digest(self.state.token, control_tokens[0]):
                return
            raise SidecarProtocolError(
                "AUTHENTICATION_FAILED",
                "authentication failed",
                status=HTTPStatus.UNAUTHORIZED,
            )
        if len(worker_tokens) == 1 and not control_tokens:
            try:
                self.state.validate_worker_lease(worker_tokens[0])
            except SidecarProtocolError:
                self._schedule_drain_if_needed()
                raise
            return
        raise SidecarProtocolError(
            "AUTHENTICATION_FAILED",
            "authentication failed",
            status=HTTPStatus.UNAUTHORIZED,
        )

    def _schedule_drain_if_needed(self) -> None:
        with self.state.lock:
            draining = self.state.status == "draining"
        if draining:
            self.server.schedule_unload()  # type: ignore[attr-defined]

    def _worker_identity(self) -> Mapping[str, object]:
        return {
            "pid": self.state.pid,
            "generation": self.state.generation,
            "test_backend": self.state.backend.is_test_backend,
        }

    def _read_body(self, maximum: int) -> bytes:
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or not lengths[0].isdigit():
            raise SidecarProtocolError("CONTENT_LENGTH_REQUIRED", "content length is required", status=HTTPStatus.LENGTH_REQUIRED)
        length = int(lengths[0])
        if not (1 <= length <= maximum):
            raise SidecarProtocolError("REQUEST_SIZE_INVALID", "request body size is invalid", status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        body = self.rfile.read(length)
        if len(body) != length:
            raise SidecarProtocolError("REQUEST_TRUNCATED", "request body is truncated")
        return body

    def _json(self, status: HTTPStatus, payload: Mapping[str, object]) -> None:
        body = _canonical_bytes(payload)
        with self.state.lock:
            generation = self.state.generation
            actual_model = (
                payload.get("model_fingerprint_sha256")
                if "model_fingerprint_sha256" in payload
                else self.state.model_fingerprint_sha256
            )
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header(VERSION_HEADER, PROTOCOL_VERSION)
        self.send_header(GENERATION_HEADER, str(generation))
        request_id = payload.get("request_id")
        if isinstance(request_id, str):
            self.send_header(REQUEST_ID_HEADER, request_id)
        if isinstance(actual_model, str):
            self.send_header(ACTUAL_MODEL_HEADER, actual_model)
        self.end_headers()
        self.wfile.write(body)

    def _error(self, error: SidecarProtocolError, request_id: str | None = None) -> None:
        if error.poison:
            self.state.poison()
        self._json(
            error.status,
            {
                "protocol_version": PROTOCOL_VERSION,
                "request_id": request_id,
                "error": {"code": error.code, "retryable": error.retryable, "message_redacted": str(error)},
            },
        )
        if error.poison:
            self.server.request_restart()  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        try:
            route = self._route()
            if route == "/health/live":
                self._json(HTTPStatus.OK, {"status": "live", "protocol_version": PROTOCOL_VERSION})
                return
            if route != "/v1/health":
                raise SidecarProtocolError("ENDPOINT_NOT_FOUND", "endpoint not found", status=HTTPStatus.NOT_FOUND)
            self._authenticate_health()
            if self.state.expire_worker_lease_if_needed():
                self.server.schedule_unload()  # type: ignore[attr-defined]
            with self.state.lock:
                status = self.state.status
                poisoned = self.state.poisoned
                model_fingerprint = self.state.model_fingerprint
                model_fingerprint_sha256 = self.state.model_fingerprint_sha256
                active_request_count = len(self.state.active)
                lease_active = self.state.worker_token is not None
                lease_generation = self.state.worker_lease_generation
            self._json(
                HTTPStatus.OK,
                {
                    "protocol_version": PROTOCOL_VERSION,
                    "status": status,
                    "ready": status == "ready" and not poisoned,
                    "capabilities_sha256": CAPABILITIES_SHA256,
                    "model_fingerprint": model_fingerprint,
                    "model_fingerprint_sha256": model_fingerprint_sha256,
                    "lease": {
                        "active": lease_active,
                        "generation": lease_generation,
                    },
                    "worker": {
                        "pid": self.state.pid,
                        "generation": self.state.generation,
                        "test_backend": self.state.backend.is_test_backend,
                        "active_request_count": active_request_count,
                    },
                },
            )
        except SidecarProtocolError as error:
            self._error(error)

    def do_POST(self) -> None:
        request_id: str | None = None
        try:
            route = self._route()
            if route == "/v1/restart":
                self._authenticate_control()
                if self.headers.get("Content-Type") != "application/json":
                    raise SidecarProtocolError(
                        "CONTENT_TYPE_INVALID",
                        "restart requires application/json",
                        status=HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                    )
                row = _parse_json(
                    self._read_body(MAX_JSON_BYTES),
                    frozenset({"request_id", "reason_code"}),
                )
                request_id = _request_uuid(row["request_id"])
                reason_code = row["reason_code"]
                if not isinstance(reason_code, str) or not _RESTART_REASON.fullmatch(
                    reason_code
                ):
                    raise SidecarProtocolError(
                        "RESTART_REASON_INVALID", "restart reason is invalid"
                    )
                self.state.poison()
                self._json(
                    HTTPStatus.ACCEPTED,
                    {
                        "protocol_version": PROTOCOL_VERSION,
                        "request_id": request_id,
                        "status": "restart_requested",
                        "worker": self._worker_identity(),
                    },
                )
                self.server.request_restart()  # type: ignore[attr-defined]
                return
            if route == "/v1/lease/acquire":
                self._authenticate_control()
                if self.headers.get("Content-Type") != "application/json":
                    raise SidecarProtocolError(
                        "CONTENT_TYPE_INVALID",
                        "lease acquire requires application/json",
                        status=HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                    )
                row = _parse_json(
                    self._read_body(MAX_JSON_BYTES),
                    frozenset({"request_id"}),
                )
                request_id = _request_uuid(row["request_id"])
                worker_token, lease_generation = (
                    self.state.acquire_worker_lease()
                )
                self._json(
                    HTTPStatus.OK,
                    {
                        "protocol_version": PROTOCOL_VERSION,
                        "request_id": request_id,
                        "status": "active",
                        "worker_token": worker_token,
                        "lease_ttl_seconds": WORKER_LEASE_TTL_SECONDS,
                        "lease_generation": lease_generation,
                        "worker": self._worker_identity(),
                    },
                )
                return

            worker_token = self._authenticate_worker()
            if route == "/v1/lease/renew":
                if self.headers.get("Content-Type") != "application/json":
                    raise SidecarProtocolError(
                        "CONTENT_TYPE_INVALID",
                        "lease renewal requires application/json",
                        status=HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                    )
                row = _parse_json(
                    self._read_body(MAX_JSON_BYTES),
                    frozenset({"request_id"}),
                )
                request_id = _request_uuid(row["request_id"])
                lease_generation = self.state.renew_worker_lease(worker_token)
                self._json(
                    HTTPStatus.OK,
                    {
                        "protocol_version": PROTOCOL_VERSION,
                        "request_id": request_id,
                        "status": "renewed",
                        "lease_ttl_seconds": WORKER_LEASE_TTL_SECONDS,
                        "lease_generation": lease_generation,
                        "worker": self._worker_identity(),
                    },
                )
                return
            if route == "/v1/lease/release":
                if self.headers.get("Content-Type") != "application/json":
                    raise SidecarProtocolError(
                        "CONTENT_TYPE_INVALID",
                        "lease release requires application/json",
                        status=HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                    )
                row = _parse_json(
                    self._read_body(MAX_JSON_BYTES),
                    frozenset({"request_id"}),
                )
                request_id = _request_uuid(row["request_id"])
                lease_generation = self.state.release_worker_lease(worker_token)
                self._json(
                    HTTPStatus.ACCEPTED,
                    {
                        "protocol_version": PROTOCOL_VERSION,
                        "request_id": request_id,
                        "status": "release_requested",
                        "lease_generation": lease_generation,
                        "worker": self._worker_identity(),
                    },
                )
                self.server.schedule_unload()  # type: ignore[attr-defined]
                return
            if self.state.poisoned:
                raise SidecarProtocolError("SIDECAR_POISONED", "sidecar requires restart", status=HTTPStatus.SERVICE_UNAVAILABLE, poison=True)
            if route == "/v1/warmup":
                if self.headers.get("Content-Type") != "application/json":
                    raise SidecarProtocolError("CONTENT_TYPE_INVALID", "warmup requires application/json", status=HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
                row = _parse_json(self._read_body(MAX_JSON_BYTES), frozenset({"request_id"}))
                request_id = _request_uuid(row["request_id"])
                self.state.warmup(worker_token)
                self._json(HTTPStatus.OK, self._ready_payload(request_id))
                return
            if route == "/v1/cancel":
                if self.headers.get("Content-Type") != "application/json":
                    raise SidecarProtocolError("CONTENT_TYPE_INVALID", "cancel requires application/json", status=HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
                row = _parse_json(self._read_body(MAX_JSON_BYTES), frozenset({"request_id"}))
                request_id = _request_uuid(row["request_id"])
                disposition = self.state.cancel_request(request_id, worker_token)
                self._json(
                    HTTPStatus.OK,
                    {
                        "protocol_version": PROTOCOL_VERSION,
                        "request_id": request_id,
                        "disposition": disposition,
                        "effective_at": "segment_boundary" if disposition == "requested" else None,
                    },
                )
                return
            if route != "/v1/synthesize":
                raise SidecarProtocolError("ENDPOINT_NOT_FOUND", "endpoint not found", status=HTTPStatus.NOT_FOUND)
            content_type = self.headers.get("Content-Type", "")
            if content_type == "application/json":
                request = _parse_metadata(self._read_body(MAX_JSON_BYTES), None)
            elif content_type.startswith("multipart/form-data;"):
                metadata_body, reference = parse_multipart(self._read_body(MAX_MULTIPART_BYTES), content_type)
                request = _parse_metadata(metadata_body, reference)
            else:
                raise SidecarProtocolError("CONTENT_TYPE_INVALID", "synthesis content type is invalid", status=HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
            request_id = request.request_id
            cancelled = self.state.begin_request(request.request_id, worker_token)
            request_finished = False
            try:
                with self.state.lock:
                    actual_model_fingerprint_sha256 = (
                        self.state.model_fingerprint_sha256
                    )
                if (
                    request.requested_model_fingerprint_sha256
                    != actual_model_fingerprint_sha256
                ):
                    raise SidecarProtocolError(
                        "MODEL_FINGERPRINT_MISMATCH",
                        "requested model differs from actual",
                        status=HTTPStatus.CONFLICT,
                    )
                payload = self.state.backend.synthesize(request, cancelled)
                if cancelled.is_set():
                    if not self.state.worker_lease_is_current(worker_token):
                        raise SidecarProtocolError(
                            "WORKER_LEASE_INVALID",
                            "worker lease expired before result publication",
                            status=HTTPStatus.UNAUTHORIZED,
                        )
                    raise SidecarProtocolError("REQUEST_CANCELLED", "request cancelled at segment boundary", status=HTTPStatus.CONFLICT)
                sample_rate, channels, sample_width = _validate_wav(payload)
                publication_committed = self.state.commit_request_for_publication(
                    request.request_id,
                    worker_token,
                )
                request_finished = True
                if not publication_committed:
                    raise SidecarProtocolError(
                        "WORKER_LEASE_INVALID",
                        "worker lease expired before result publication",
                        status=HTTPStatus.UNAUTHORIZED,
                    )
            except SidecarProtocolError:
                raise
            except Exception as error:
                raise SidecarProtocolError("BACKEND_FAILURE", "backend failed", status=HTTPStatus.SERVICE_UNAVAILABLE, retryable=True, poison=True) from error
            finally:
                if not request_finished:
                    self.state.finish_request(request.request_id)
            digest = _sha256(payload)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header(VERSION_HEADER, PROTOCOL_VERSION)
            self.send_header(REQUEST_ID_HEADER, request.request_id)
            self.send_header(GENERATION_HEADER, str(self.state.generation))
            self.send_header(ACTUAL_MODEL_HEADER, request.requested_model_fingerprint_sha256)
            self.send_header("X-MOSS-Audio-SHA256", digest)
            self.send_header("X-MOSS-Sample-Rate", str(sample_rate))
            self.send_header("X-MOSS-Channels", str(channels))
            self.send_header("X-MOSS-Sample-Width", str(sample_width))
            self.end_headers()
            self.wfile.write(payload)
        except SidecarProtocolError as error:
            self._schedule_drain_if_needed()
            self._error(error, request_id)

    def _ready_payload(self, request_id: str) -> Mapping[str, object]:
        with self.state.lock:
            status = self.state.status
            poisoned = self.state.poisoned
            model_fingerprint = self.state.model_fingerprint
            model_fingerprint_sha256 = self.state.model_fingerprint_sha256
            lease_active = self.state.worker_token is not None
            lease_generation = self.state.worker_lease_generation
        return {
            "protocol_version": PROTOCOL_VERSION,
            "request_id": request_id,
            "status": status,
            "ready": status == "ready" and not poisoned,
            "capabilities_sha256": CAPABILITIES_SHA256,
            "model_fingerprint": model_fingerprint,
            "model_fingerprint_sha256": model_fingerprint_sha256,
            "lease": {
                "active": lease_active,
                "generation": lease_generation,
            },
            "worker": {
                "pid": self.state.pid,
                "generation": self.state.generation,
                "test_backend": self.state.backend.is_test_backend,
            },
        }


class SidecarHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], state: SidecarState):
        super().__init__(address, SidecarHandler)
        self.state = state
        self._restart_lock = threading.Lock()
        self._restart_scheduled = False
        self._unload_lock = threading.Lock()
        self._unload_scheduled = False
        self._watchdog_stop = threading.Event()
        self._watchdog_thread = threading.Thread(
            target=self._watch_worker_lease,
            name="moss-sidecar-lease-watchdog",
            daemon=True,
        )
        self._watchdog_thread.start()

    def _watch_worker_lease(self) -> None:
        while not self._watchdog_stop.wait(WORKER_LEASE_WATCHDOG_SECONDS):
            if self.state.expire_worker_lease_if_needed():
                self.schedule_unload()

    def schedule_unload(self) -> None:
        """Start one bounded drain; a stuck backend forces supervisor restart."""

        with self._unload_lock:
            if self._unload_scheduled:
                return
            self._unload_scheduled = True
        threading.Thread(
            target=self._drain_and_unload,
            name="moss-sidecar-lease-unload",
            daemon=True,
        ).start()

    def _drain_and_unload(self) -> None:
        reschedule = False
        try:
            if not self.state.finish_deactivate(
                WORKER_LEASE_DRAIN_GRACE_SECONDS
            ):
                self.state.poison()
                self.request_restart()
        finally:
            with self._unload_lock:
                self._unload_scheduled = False
            with self.state.lock:
                reschedule = self.state.status == "draining"
        if reschedule:
            self.schedule_unload()

    def request_restart(self) -> None:
        """Stop ``serve_forever`` from another thread exactly once."""

        with self._restart_lock:
            if self._restart_scheduled:
                return
            self._restart_scheduled = True
        threading.Thread(
            target=self.shutdown,
            name="moss-sidecar-poison-shutdown",
            daemon=True,
        ).start()

    def server_close(self) -> None:
        self._watchdog_stop.set()
        super().server_close()
        if threading.current_thread() is not self._watchdog_thread:
            self._watchdog_thread.join(timeout=1)


def build_state(args: argparse.Namespace) -> SidecarState:
    token_path = os.environ.get("MOSS_TTS_SIDECAR_TOKEN_FILE")
    if not token_path:
        raise SidecarProtocolError("TOKEN_FILE_REQUIRED", "secret-file token configuration is required", status=HTTPStatus.INTERNAL_SERVER_ERROR)
    if args.backend == "nano" and (
        os.environ.get("MOSS_MODEL_TREE_SHA256") != MODEL_TREE_SHA256
        or os.environ.get("MOSS_SOURCE_TREE_SHA256") != SOURCE_TREE_SHA256
    ):
        raise SidecarProtocolError(
            "MODEL_ENVIRONMENT_IDENTITY_MISMATCH",
            "model environment identity differs from the frozen lock",
            status=HTTPStatus.INTERNAL_SERVER_ERROR,
        )
    token = read_secret_token(Path(token_path))
    if args.backend == "fake":
        if not args.allow_test_backend:
            raise SidecarProtocolError("TEST_BACKEND_FORBIDDEN", "fake backend requires explicit test-only flag", status=HTTPStatus.INTERNAL_SERVER_ERROR)
        backend: Backend = FakeBackend(step_delay_seconds=args.fake_step_delay_seconds, fail_mode=args.fake_fail_mode)
    else:
        if args.cpu_threads != 4 or args.host != "0.0.0.0" or args.port != 8765:
            raise SidecarProtocolError(
                "PRODUCTION_RUNTIME_CONFIG_INVALID",
                "Nano runtime must use the frozen private service configuration",
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        backend = NanoBackend(
            lock_path=Path(args.model_lock),
            assets_root=Path(args.assets_root),
            cpu_threads=args.cpu_threads,
        )
    return SidecarState(token, backend)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--backend", choices=("nano", "fake"), default="nano")
    parser.add_argument("--allow-test-backend", action="store_true")
    parser.add_argument("--fake-step-delay-seconds", type=float, default=0.0)
    parser.add_argument("--fake-fail-mode", choices=("crash",))
    parser.add_argument("--model-lock", default="/opt/ai-novel-world/tts-sidecar/model-source.lock.json")
    parser.add_argument("--assets-root", default="/opt/moss-assets")
    parser.add_argument("--cpu-threads", type=int, default=4)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not (1 <= args.port <= 65535) or not (1 <= args.cpu_threads <= 16) or not (0 <= args.fake_step_delay_seconds <= 10):
        raise SystemExit(78)
    try:
        state = build_state(args)
    except SidecarProtocolError as error:
        print(
            _canonical_bytes(
                {
                    "protocol_version": PROTOCOL_VERSION,
                    "status": "inert",
                    "error": {"code": error.code, "message_redacted": str(error)},
                }
            ).decode("utf-8"),
            flush=True,
        )
        return 78
    server = SidecarHTTPServer((args.host, args.port), state)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
    return 75 if state.poisoned else 0


if __name__ == "__main__":
    raise SystemExit(main())
