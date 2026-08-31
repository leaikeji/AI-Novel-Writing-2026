"""Strict PawApp client for the native macOS MOSS VoiceGenerator host.

The host owns model paths, preview text, temporary files and process commands.
This module deliberately exposes no field that can select any of them.  It
also treats every host response as untrusted until protocol, runtime identity,
hashes and the complete WAV payload have been checked.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import hashlib
from http.client import HTTPConnection
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
from types import MappingProxyType
from typing import Final, Mapping, Protocol
from uuid import UUID
import wave


HOST_PROTOCOL_VERSION: Final = "moss-voice-generator-host/1"
HOST_TOKEN_HEADER: Final = "Authorization"
PROTOCOL_HEADER: Final = "X-MOSS-Protocol-Version"
REQUEST_ID_HEADER: Final = "X-MOSS-Request-ID"
RUNTIME_FINGERPRINT_HEADER: Final = "X-MOSS-Runtime-Fingerprint-SHA256"
AUDIO_SHA256_HEADER: Final = "X-MOSS-Audio-SHA256"
AUDIO_BYTES_HEADER: Final = "X-MOSS-Audio-Bytes"
AUDIO_FORMAT_HEADER: Final = "X-MOSS-Audio-Format"

PRODUCTION_HOST: Final = "host.docker.internal"
PRODUCTION_PORT: Final = 18_765
VOICE_GENERATOR_REVISION: Final = "97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4"
CODEC_REVISION: Final = "3cd226ba2947efa357ef453bcad111b6eafba782"
RUNTIME_TOPOLOGY: Final = "mps-bf16-staged-process-v1"
GENERATION_ADAPTER_SCHEMA: Final = "vg40-mps-generation-adapter/2"
CODEC_ADAPTER_SCHEMA: Final = "vg40-mps-codec-adapter/1"
RUNTIME_IDENTITY_SCHEMA: Final = "voice-generator-runtime-identity/1"
AUDIO_PARAMETERS_SCHEMA: Final = "voice-generator-audio-parameters/1"
REQUEST_SCHEMA: Final = "voice-generator-host-request/1"
EXPECTED_AUDIO_FORMAT_HEADER: Final = "WAV_PCM_S16LE_48000HZ_STEREO"

MAX_JSON_BYTES: Final = 64 * 1024
MAX_AUDIO_BYTES: Final = 4 * 1024 * 1024
MIN_GENERATED_AUDIO_MILLISECONDS: Final = 2_000
# 256 delayed generation steps minus the 16-codebook boundary can yield at
# most 240 audio frames.  The codec represents each frame as 80 ms.
MAX_GENERATED_AUDIO_MILLISECONDS: Final = 240 * 80
MAX_INSTRUCTION_CHARS: Final = 1_200
MAX_SEED: Final = 2**63 - 1
MIN_TOKEN_CHARS: Final = 32
MAX_TOKEN_CHARS: Final = 128

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STABLE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,95}$")
_LANGUAGES: Final = frozenset({"zh-CN", "en", "ja-JP"})
_SECURITY_HEADERS: Final = frozenset(
    {
        PROTOCOL_HEADER.lower(),
        REQUEST_ID_HEADER.lower(),
        RUNTIME_FINGERPRINT_HEADER.lower(),
        AUDIO_SHA256_HEADER.lower(),
        AUDIO_BYTES_HEADER.lower(),
        AUDIO_FORMAT_HEADER.lower(),
    }
)


class VoiceGeneratorRuntimeError(RuntimeError):
    """Stable, redacted failure raised by the native-host boundary."""

    def __init__(self, code: str, message: str, *, retryable: bool = False):
        if _STABLE_CODE.fullmatch(code) is None:
            code = "HOST_RESPONSE_INVALID"
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class VoiceGeneratorHostConfig:
    host: str
    port: int
    token_file: Path = field(repr=False)
    timeout_seconds: float = 360.0
    allow_test_backend: bool = False

    def __post_init__(self) -> None:
        if type(self.allow_test_backend) is not bool:
            raise ValueError("allow_test_backend must be an exact boolean")
        if self.allow_test_backend:
            if self.host not in {"127.0.0.1", "localhost"}:
                raise ValueError("test VoiceGenerator host must be loopback")
        elif (self.host, self.port) != (PRODUCTION_HOST, PRODUCTION_PORT):
            raise ValueError("production VoiceGenerator host identity is not frozen")
        if isinstance(self.port, bool) or not isinstance(self.port, int):
            raise ValueError("VoiceGenerator host port must be an integer")
        if not (10_000 <= self.port <= 65_535):
            raise ValueError("VoiceGenerator host port must be five digits")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not 1 <= float(self.timeout_seconds) <= 600
        ):
            raise ValueError("VoiceGenerator host timeout is invalid")
        if not isinstance(self.token_file, Path) or not self.token_file.is_absolute():
            raise ValueError("VoiceGenerator token file must be absolute")


def read_host_token(path: Path) -> str:
    """Read one owner-only regular secret without following links."""

    if not isinstance(path, Path) or not path.is_absolute():
        raise VoiceGeneratorRuntimeError(
            "TOKEN_FILE_INVALID", "VoiceGenerator token secret is invalid"
        )
    descriptor: int | None = None
    try:
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            raise VoiceGeneratorRuntimeError(
                "TOKEN_FILE_INVALID", "VoiceGenerator token policy is unavailable"
            )
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | nofollow)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != os.geteuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or not MIN_TOKEN_CHARS <= before.st_size <= MAX_TOKEN_CHARS
        ):
            raise VoiceGeneratorRuntimeError(
                "TOKEN_FILE_INVALID", "VoiceGenerator token secret is invalid"
            )
        raw = os.read(descriptor, MAX_TOKEN_CHARS + 1)
        after = os.fstat(descriptor)
        if (
            len(raw) != before.st_size
            or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        ):
            raise VoiceGeneratorRuntimeError(
                "TOKEN_FILE_INVALID", "VoiceGenerator token secret changed"
            )
        token = raw.decode("ascii")
    except VoiceGeneratorRuntimeError:
        raise
    except (OSError, UnicodeDecodeError) as error:
        raise VoiceGeneratorRuntimeError(
            "TOKEN_FILE_INVALID", "VoiceGenerator token secret is unreadable"
        ) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if any(not 0x21 <= byte <= 0x7E for byte in raw):
        raise VoiceGeneratorRuntimeError(
            "TOKEN_CONFIGURATION_INVALID", "VoiceGenerator token value is invalid"
        )
    return token


def _canonical_sha256(value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class VoiceGeneratorRuntimeIdentity:
    protocol_version: str = HOST_PROTOCOL_VERSION
    topology: str = RUNTIME_TOPOLOGY
    voice_generator_revision: str = VOICE_GENERATOR_REVISION
    codec_revision: str = CODEC_REVISION
    generation_adapter_schema: str = GENERATION_ADAPTER_SCHEMA
    codec_adapter_schema: str = CODEC_ADAPTER_SCHEMA
    device: str = "mps"
    dtype: str = "bfloat16"
    quantization: str = "none"
    schema_version: str = RUNTIME_IDENTITY_SCHEMA

    def __post_init__(self) -> None:
        if self.wire_payload() != EXPECTED_RUNTIME_IDENTITY_PAYLOAD:
            raise ValueError("VoiceGenerator runtime identity differs from the frozen contract")

    def wire_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "protocol_version": self.protocol_version,
            "topology": self.topology,
            "voice_generator_revision": self.voice_generator_revision,
            "codec_revision": self.codec_revision,
            "generation_adapter_schema": self.generation_adapter_schema,
            "codec_adapter_schema": self.codec_adapter_schema,
            "device": self.device,
            "dtype": self.dtype,
            "quantization": self.quantization,
        }

    @property
    def fingerprint(self) -> str:
        return _canonical_sha256(self.wire_payload())

    @classmethod
    def from_wire(cls, value: object) -> "VoiceGeneratorRuntimeIdentity":
        if type(value) is not dict or value != EXPECTED_RUNTIME_IDENTITY_PAYLOAD:
            raise VoiceGeneratorRuntimeError(
                "RUNTIME_IDENTITY_MISMATCH",
                "VoiceGenerator runtime identity is invalid",
            )
        return cls()


EXPECTED_RUNTIME_IDENTITY_PAYLOAD: Final[dict[str, object]] = {
    "schema_version": RUNTIME_IDENTITY_SCHEMA,
    "protocol_version": HOST_PROTOCOL_VERSION,
    "topology": RUNTIME_TOPOLOGY,
    "voice_generator_revision": VOICE_GENERATOR_REVISION,
    "codec_revision": CODEC_REVISION,
    "generation_adapter_schema": GENERATION_ADAPTER_SCHEMA,
    "codec_adapter_schema": CODEC_ADAPTER_SCHEMA,
    "device": "mps",
    "dtype": "bfloat16",
    "quantization": "none",
}
EXPECTED_RUNTIME_IDENTITY: Final = VoiceGeneratorRuntimeIdentity()
EXPECTED_RUNTIME_FINGERPRINT: Final = EXPECTED_RUNTIME_IDENTITY.fingerprint


@dataclass(frozen=True, slots=True)
class VoiceGeneratorAudioParameters:
    audio_temperature_milli: int = 1_500
    audio_top_p_milli: int = 600
    audio_top_k: int = 50
    audio_repetition_penalty_milli: int = 1_100
    schema_version: str = AUDIO_PARAMETERS_SCHEMA

    def __post_init__(self) -> None:
        if self.wire_payload() != EXPECTED_AUDIO_PARAMETERS_PAYLOAD:
            raise ValueError("VoiceGenerator audio parameters are not the official values")

    def wire_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "audio_temperature_milli": self.audio_temperature_milli,
            "audio_top_p_milli": self.audio_top_p_milli,
            "audio_top_k": self.audio_top_k,
            "audio_repetition_penalty_milli": self.audio_repetition_penalty_milli,
        }

    @classmethod
    def from_wire(cls, value: object) -> "VoiceGeneratorAudioParameters":
        if type(value) is not dict or value != EXPECTED_AUDIO_PARAMETERS_PAYLOAD:
            raise VoiceGeneratorRuntimeError(
                "AUDIO_PARAMETERS_MISMATCH",
                "VoiceGenerator audio parameters are invalid",
            )
        return cls()


EXPECTED_AUDIO_PARAMETERS_PAYLOAD: Final[dict[str, object]] = {
    "schema_version": AUDIO_PARAMETERS_SCHEMA,
    "audio_temperature_milli": 1_500,
    "audio_top_p_milli": 600,
    "audio_top_k": 50,
    "audio_repetition_penalty_milli": 1_100,
}
EXPECTED_AUDIO_PARAMETERS: Final = VoiceGeneratorAudioParameters()


@dataclass(frozen=True, slots=True)
class VoiceGeneratorHostRequest:
    request_id: UUID
    instruction: str = field(repr=False)
    instruction_digest: str
    language: str
    seed: int
    audio_parameters: VoiceGeneratorAudioParameters = EXPECTED_AUDIO_PARAMETERS
    runtime_identity: VoiceGeneratorRuntimeIdentity = EXPECTED_RUNTIME_IDENTITY
    schema_version: str = REQUEST_SCHEMA

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, UUID) or self.request_id.int == 0:
            raise ValueError("VoiceGenerator request_id must be a non-zero UUID")
        if (
            not isinstance(self.instruction, str)
            or self.instruction != self.instruction.strip()
            or not 1 <= len(self.instruction) <= MAX_INSTRUCTION_CHARS
            or any(ord(character) < 0x20 and character not in "\n\t" for character in self.instruction)
        ):
            raise ValueError("VoiceGenerator instruction is outside the frozen bound")
        _ensure_sha256(self.instruction_digest, "instruction_digest")
        if self.instruction_digest != hashlib.sha256(
            self.instruction.encode("utf-8")
        ).hexdigest():
            raise ValueError("VoiceGenerator instruction digest changed")
        if self.language not in _LANGUAGES:
            raise ValueError("VoiceGenerator language is unsupported")
        if type(self.seed) is not int or not 0 <= self.seed <= MAX_SEED:
            raise ValueError("VoiceGenerator seed is outside the frozen bound")
        if self.audio_parameters != EXPECTED_AUDIO_PARAMETERS:
            raise ValueError("VoiceGenerator audio parameters changed")
        if self.runtime_identity != EXPECTED_RUNTIME_IDENTITY:
            raise ValueError("VoiceGenerator runtime identity changed")
        if self.schema_version != REQUEST_SCHEMA:
            raise ValueError("VoiceGenerator request schema changed")

    def wire_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "protocol_version": HOST_PROTOCOL_VERSION,
            "request_id": str(self.request_id),
            "instruction": self.instruction,
            "instruction_digest": self.instruction_digest,
            "language": self.language,
            "seed": self.seed,
            "audio_parameters": self.audio_parameters.wire_payload(),
            "runtime_identity": self.runtime_identity.wire_payload(),
        }
        payload["request_digest"] = _canonical_sha256(payload)
        return payload

    @property
    def request_digest(self) -> str:
        return str(self.wire_payload()["request_digest"])


class HostGenerationStatus(str, Enum):
    ACCEPTED = "accepted"
    GENERATING = "generating"
    UNLOADING = "unloading"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class HostMemorySummary:
    minimum_available_memory_bytes: int
    maximum_swap_delta_bytes: int
    maximum_pageouts_per_second: int
    critical_pressure_milliseconds: int
    stage_pid_overlap: bool
    recovered_within_60_seconds: bool

    def __post_init__(self) -> None:
        for name in (
            "minimum_available_memory_bytes",
            "maximum_swap_delta_bytes",
            "maximum_pageouts_per_second",
            "critical_pressure_milliseconds",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise VoiceGeneratorRuntimeError(
                    "MEMORY_EVIDENCE_INVALID", "VoiceGenerator memory evidence is invalid"
                )
        if type(self.stage_pid_overlap) is not bool or type(self.recovered_within_60_seconds) is not bool:
            raise VoiceGeneratorRuntimeError(
                "MEMORY_EVIDENCE_INVALID", "VoiceGenerator memory evidence is invalid"
            )

    @classmethod
    def from_wire(cls, value: object) -> "HostMemorySummary":
        expected = {
            "minimum_available_memory_bytes",
            "maximum_swap_delta_bytes",
            "maximum_pageouts_per_second",
            "critical_pressure_milliseconds",
            "stage_pid_overlap",
            "recovered_within_60_seconds",
        }
        if type(value) is not dict or set(value) != expected:
            raise VoiceGeneratorRuntimeError(
                "MEMORY_EVIDENCE_INVALID", "VoiceGenerator memory evidence is invalid"
            )
        try:
            return cls(**value)
        except TypeError as error:
            raise VoiceGeneratorRuntimeError(
                "MEMORY_EVIDENCE_INVALID", "VoiceGenerator memory evidence is invalid"
            ) from error

    def public_payload(self) -> Mapping[str, int | bool]:
        return MappingProxyType(
            {
                "minimum_available_memory_bytes": self.minimum_available_memory_bytes,
                "maximum_swap_delta_bytes": self.maximum_swap_delta_bytes,
                "maximum_pageouts_per_second": self.maximum_pageouts_per_second,
                "critical_pressure_milliseconds": self.critical_pressure_milliseconds,
                "stage_pid_overlap": self.stage_pid_overlap,
                "recovered_within_60_seconds": self.recovered_within_60_seconds,
            }
        )


@dataclass(frozen=True, slots=True)
class HostGenerationReceipt:
    request_id: UUID
    request_digest: str
    status: HostGenerationStatus
    terminal: bool
    cancellable: bool
    retryable: bool
    failure_code: str | None
    runtime_identity: VoiceGeneratorRuntimeIdentity
    runtime_fingerprint: str
    token_sha256: str | None
    audio_sha256: str | None
    audio_size_bytes: int | None
    memory_summary: HostMemorySummary | None
    started_at: datetime | None
    completed_at: datetime | None

    @classmethod
    def from_wire(cls, value: object) -> "HostGenerationReceipt":
        expected = {
            "protocol_version",
            "request_id",
            "request_digest",
            "status",
            "terminal",
            "cancellable",
            "retryable",
            "failure_code",
            "runtime_identity",
            "runtime_fingerprint",
            "token_sha256",
            "audio_sha256",
            "audio_size_bytes",
            "memory_summary",
            "started_at",
            "completed_at",
        }
        if type(value) is not dict or set(value) != expected:
            raise VoiceGeneratorRuntimeError(
                "GENERATION_RECEIPT_INVALID", "VoiceGenerator receipt shape is invalid"
            )
        if value.get("protocol_version") != HOST_PROTOCOL_VERSION:
            raise VoiceGeneratorRuntimeError(
                "PROTOCOL_MISMATCH", "VoiceGenerator protocol identity changed"
            )
        try:
            request_id = UUID(str(value["request_id"]))
            status = HostGenerationStatus(value["status"])
        except (ValueError, TypeError, KeyError) as error:
            raise VoiceGeneratorRuntimeError(
                "GENERATION_RECEIPT_INVALID", "VoiceGenerator receipt identity is invalid"
            ) from error
        if str(request_id) != value["request_id"] or request_id.int == 0:
            raise VoiceGeneratorRuntimeError(
                "GENERATION_RECEIPT_INVALID", "VoiceGenerator request UUID is invalid"
            )
        request_digest = value["request_digest"]
        runtime_fingerprint = value["runtime_fingerprint"]
        _ensure_sha256(request_digest, "request_digest", runtime=True)
        _ensure_sha256(runtime_fingerprint, "runtime_fingerprint", runtime=True)
        runtime_identity = VoiceGeneratorRuntimeIdentity.from_wire(value["runtime_identity"])
        if runtime_fingerprint != runtime_identity.fingerprint:
            raise VoiceGeneratorRuntimeError(
                "RUNTIME_IDENTITY_MISMATCH", "VoiceGenerator runtime fingerprint changed"
            )
        terminal = value["terminal"]
        cancellable = value["cancellable"]
        retryable = value["retryable"]
        if any(type(item) is not bool for item in (terminal, cancellable, retryable)):
            raise VoiceGeneratorRuntimeError(
                "GENERATION_RECEIPT_INVALID", "VoiceGenerator receipt flags are invalid"
            )
        expected_terminal = status in {
            HostGenerationStatus.COMPLETED,
            HostGenerationStatus.FAILED,
            HostGenerationStatus.CANCELLED,
        }
        if terminal is not expected_terminal or cancellable is not (not expected_terminal):
            raise VoiceGeneratorRuntimeError(
                "GENERATION_RECEIPT_INVALID", "VoiceGenerator receipt state is inconsistent"
            )
        failure_code = value["failure_code"]
        if status is HostGenerationStatus.FAILED:
            if not isinstance(failure_code, str) or _STABLE_CODE.fullmatch(failure_code) is None:
                raise VoiceGeneratorRuntimeError(
                    "GENERATION_RECEIPT_INVALID", "VoiceGenerator failure code is invalid"
                )
        elif status is HostGenerationStatus.CANCELLED:
            if failure_code != "USER_CANCELLED" or retryable:
                raise VoiceGeneratorRuntimeError(
                    "GENERATION_RECEIPT_INVALID", "VoiceGenerator cancellation is invalid"
                )
        elif failure_code is not None or retryable:
            raise VoiceGeneratorRuntimeError(
                "GENERATION_RECEIPT_INVALID", "VoiceGenerator success state carries failure evidence"
            )
        token_sha256 = _optional_sha256(value["token_sha256"], "token_sha256")
        audio_sha256 = _optional_sha256(value["audio_sha256"], "audio_sha256")
        audio_size = value["audio_size_bytes"]
        if audio_size is not None and (
            type(audio_size) is not int or not 1 <= audio_size <= MAX_AUDIO_BYTES
        ):
            raise VoiceGeneratorRuntimeError(
                "GENERATION_RECEIPT_INVALID", "VoiceGenerator audio size is invalid"
            )
        memory = (
            None
            if value["memory_summary"] is None
            else HostMemorySummary.from_wire(value["memory_summary"])
        )
        started_at = _optional_datetime(value["started_at"], "started_at")
        completed_at = _optional_datetime(value["completed_at"], "completed_at")
        if status is HostGenerationStatus.COMPLETED:
            if (
                token_sha256 is None
                or audio_sha256 is None
                or audio_size is None
                or memory is None
                or started_at is None
                or completed_at is None
                or completed_at < started_at
                or memory.stage_pid_overlap
                or not memory.recovered_within_60_seconds
            ):
                raise VoiceGeneratorRuntimeError(
                    "GENERATION_RECEIPT_INVALID", "VoiceGenerator completion evidence is incomplete"
                )
        elif audio_sha256 is not None or audio_size is not None:
            raise VoiceGeneratorRuntimeError(
                "GENERATION_RECEIPT_INVALID", "Unpublished VoiceGenerator audio was exposed"
            )
        if expected_terminal and completed_at is None:
            raise VoiceGeneratorRuntimeError(
                "GENERATION_RECEIPT_INVALID", "VoiceGenerator terminal time is missing"
            )
        if not expected_terminal and completed_at is not None:
            raise VoiceGeneratorRuntimeError(
                "GENERATION_RECEIPT_INVALID", "VoiceGenerator active state has a completion time"
            )
        return cls(
            request_id=request_id,
            request_digest=request_digest,
            status=status,
            terminal=terminal,
            cancellable=cancellable,
            retryable=retryable,
            failure_code=failure_code,
            runtime_identity=runtime_identity,
            runtime_fingerprint=runtime_fingerprint,
            token_sha256=token_sha256,
            audio_sha256=audio_sha256,
            audio_size_bytes=audio_size,
            memory_summary=memory,
            started_at=started_at,
            completed_at=completed_at,
        )


@dataclass(frozen=True, slots=True)
class VoiceGeneratorHostHealth:
    ready: bool
    status: str
    runtime_identity: VoiceGeneratorRuntimeIdentity
    runtime_fingerprint: str
    active_request_id: UUID | None


@dataclass(frozen=True, slots=True)
class VoiceGeneratorAudioMetrics:
    byte_size: int
    frame_count: int
    duration_milliseconds: int
    sample_rate_hz: int
    channels: int
    sample_width_bytes: int
    peak_milli: int
    rms_dbfs_milli: int
    dc_offset_milli: int
    clipped_fraction_millionths: int

    def public_payload(self) -> Mapping[str, int | str]:
        return MappingProxyType(
            {
                "container": "WAV",
                "codec": "PCM_S16LE",
                "byte_size": self.byte_size,
                "frame_count": self.frame_count,
                "duration_milliseconds": self.duration_milliseconds,
                "sample_rate_hz": self.sample_rate_hz,
                "channels": self.channels,
                "sample_width_bytes": self.sample_width_bytes,
                "peak_milli": self.peak_milli,
                "rms_dbfs_milli": self.rms_dbfs_milli,
                "dc_offset_milli": self.dc_offset_milli,
                "clipped_fraction_millionths": self.clipped_fraction_millionths,
            }
        )


@dataclass(frozen=True, slots=True)
class VoiceGeneratorAudioResult:
    request_id: UUID
    audio_bytes: bytes = field(repr=False)
    audio_sha256: str
    runtime_fingerprint: str
    metrics: VoiceGeneratorAudioMetrics


@dataclass(frozen=True, slots=True)
class HttpResponseEnvelope:
    status: int
    headers: tuple[tuple[str, str], ...]
    body: bytes = field(repr=False)


class VoiceGeneratorHostTransport(Protocol):
    def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        maximum_response_bytes: int,
    ) -> HttpResponseEnvelope: ...


class _HTTPConnectionTransport:
    def __init__(self, config: VoiceGeneratorHostConfig):
        self._config = config

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        maximum_response_bytes: int,
    ) -> HttpResponseEnvelope:
        connection = HTTPConnection(
            self._config.host,
            self._config.port,
            timeout=float(self._config.timeout_seconds),
        )
        try:
            connection.request(method, path, headers=dict(headers), body=body)
            response = connection.getresponse()
            raw_length = response.getheader("Content-Length")
            if raw_length is None or not raw_length.isdigit():
                raise VoiceGeneratorRuntimeError(
                    "RESPONSE_FRAMING_INVALID", "VoiceGenerator response framing is invalid"
                )
            size = int(raw_length)
            if not 1 <= size <= maximum_response_bytes:
                raise VoiceGeneratorRuntimeError(
                    "RESPONSE_SIZE_INVALID", "VoiceGenerator response size is invalid"
                )
            payload = response.read(size + 1)
            if len(payload) != size:
                raise VoiceGeneratorRuntimeError(
                    "RESPONSE_SIZE_INVALID", "VoiceGenerator response length changed"
                )
            return HttpResponseEnvelope(
                status=response.status,
                headers=tuple(response.getheaders()),
                body=payload,
            )
        except VoiceGeneratorRuntimeError:
            raise
        except (OSError, TimeoutError) as error:
            raise VoiceGeneratorRuntimeError(
                "HOST_UNREACHABLE", "VoiceGenerator host is unavailable", retryable=True
            ) from error
        finally:
            connection.close()


class NativeVoiceGeneratorHostClient:
    """Async facade around the strict synchronous private-host transport."""

    def __init__(
        self,
        config: VoiceGeneratorHostConfig,
        *,
        transport: VoiceGeneratorHostTransport | None = None,
    ) -> None:
        if transport is not None and not config.allow_test_backend:
            raise ValueError("custom VoiceGenerator transports are test-only")
        self.config = config
        self._token = read_host_token(config.token_file)
        self._transport = transport or _HTTPConnectionTransport(config)

    def _headers(
        self,
        body: bytes | None = None,
        *,
        accept: str = "application/json",
    ) -> dict[str, str]:
        headers = {
            HOST_TOKEN_HEADER: f"Bearer {self._token}",
            PROTOCOL_HEADER: HOST_PROTOCOL_VERSION,
            "Accept": accept,
        }
        if body is not None:
            headers.update(
                {
                    "Content-Type": "application/json",
                    "Content-Length": str(len(body)),
                }
            )
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, object] | None = None,
        maximum: int = MAX_JSON_BYTES,
        accept: str = "application/json",
    ) -> HttpResponseEnvelope:
        if not path.startswith("/v1/") or "?" in path or "#" in path or "://" in path:
            raise VoiceGeneratorRuntimeError(
                "REQUEST_PATH_INVALID", "VoiceGenerator request path is invalid"
            )
        body = None
        if payload is not None:
            body = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            if not 1 <= len(body) <= MAX_JSON_BYTES:
                raise VoiceGeneratorRuntimeError(
                    "REQUEST_SIZE_INVALID", "VoiceGenerator request is too large"
                )
        return self._transport.request(
            method,
            path,
            headers=self._headers(body, accept=accept),
            body=body,
            maximum_response_bytes=maximum,
        )

    @staticmethod
    def _headers_checked(envelope: HttpResponseEnvelope) -> dict[str, str]:
        headers: dict[str, str] = {}
        for raw_name, value in envelope.headers:
            name = raw_name.lower()
            if name in _SECURITY_HEADERS and name in headers:
                raise VoiceGeneratorRuntimeError(
                    "RESPONSE_HEADER_DUPLICATED",
                    "VoiceGenerator identity header is duplicated",
                )
            headers[name] = value
        if headers.get(PROTOCOL_HEADER.lower()) != HOST_PROTOCOL_VERSION:
            raise VoiceGeneratorRuntimeError(
                "PROTOCOL_MISMATCH", "VoiceGenerator protocol header changed"
            )
        return headers

    @classmethod
    def _json(cls, envelope: HttpResponseEnvelope) -> tuple[dict[str, str], dict[str, object]]:
        headers = cls._headers_checked(envelope)
        content_type = next(
            (value for name, value in envelope.headers if name.lower() == "content-type"),
            None,
        )
        if content_type != "application/json":
            raise VoiceGeneratorRuntimeError(
                "RESPONSE_CONTENT_TYPE_INVALID", "VoiceGenerator response type is invalid"
            )
        try:
            value = json.loads(envelope.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise VoiceGeneratorRuntimeError(
                "RESPONSE_JSON_INVALID", "VoiceGenerator response is invalid"
            ) from error
        if type(value) is not dict:
            raise VoiceGeneratorRuntimeError(
                "RESPONSE_SHAPE_INVALID", "VoiceGenerator response shape is invalid"
            )
        return headers, value

    @classmethod
    def _raise_error(cls, envelope: HttpResponseEnvelope) -> None:
        headers, value = cls._json(envelope)
        del headers
        if type(value) is not dict or set(value) != {
            "protocol_version",
            "request_id",
            "error",
        }:
            raise VoiceGeneratorRuntimeError(
                "HOST_ERROR_INVALID", "VoiceGenerator error response is invalid"
            )
        error = value.get("error")
        if (
            value.get("protocol_version") != HOST_PROTOCOL_VERSION
            or type(error) is not dict
            or set(error) != {"code", "retryable"}
            or not isinstance(error.get("code"), str)
            or _STABLE_CODE.fullmatch(str(error["code"])) is None
            or type(error.get("retryable")) is not bool
        ):
            raise VoiceGeneratorRuntimeError(
                "HOST_ERROR_INVALID", "VoiceGenerator error response is invalid"
            )
        raise VoiceGeneratorRuntimeError(
            str(error["code"]),
            "VoiceGenerator host rejected the request",
            retryable=bool(error["retryable"]),
        )

    @classmethod
    def _receipt(
        cls,
        envelope: HttpResponseEnvelope,
        request: VoiceGeneratorHostRequest | None = None,
    ) -> HostGenerationReceipt:
        if envelope.status not in {200, 202}:
            cls._raise_error(envelope)
        headers, value = cls._json(envelope)
        receipt = HostGenerationReceipt.from_wire(value)
        if (
            headers.get(REQUEST_ID_HEADER.lower()) != str(receipt.request_id)
            or headers.get(RUNTIME_FINGERPRINT_HEADER.lower())
            != receipt.runtime_fingerprint
        ):
            raise VoiceGeneratorRuntimeError(
                "RESPONSE_IDENTITY_MISMATCH", "VoiceGenerator receipt headers changed"
            )
        if request is not None and (
            receipt.request_id != request.request_id
            or receipt.request_digest != request.request_digest
        ):
            raise VoiceGeneratorRuntimeError(
                "REQUEST_IDENTITY_MISMATCH", "VoiceGenerator receipt is for another request"
            )
        return receipt

    async def health(self) -> VoiceGeneratorHostHealth:
        envelope = await asyncio.to_thread(self._request, "GET", "/v1/health")
        if envelope.status != 200:
            self._raise_error(envelope)
        headers, value = self._json(envelope)
        expected = {
            "protocol_version",
            "status",
            "ready",
            "runtime_identity",
            "runtime_fingerprint",
            "active_request_id",
        }
        if set(value) != expected or value.get("protocol_version") != HOST_PROTOCOL_VERSION:
            raise VoiceGeneratorRuntimeError(
                "HEALTH_RESPONSE_INVALID", "VoiceGenerator health response is invalid"
            )
        identity = VoiceGeneratorRuntimeIdentity.from_wire(value["runtime_identity"])
        fingerprint = value["runtime_fingerprint"]
        ready = value["ready"]
        status = value["status"]
        if (
            fingerprint != identity.fingerprint
            or headers.get(RUNTIME_FINGERPRINT_HEADER.lower()) != fingerprint
            or type(ready) is not bool
            or status not in {"ready", "unavailable"}
            or ready is not (status == "ready")
        ):
            raise VoiceGeneratorRuntimeError(
                "HEALTH_RESPONSE_INVALID", "VoiceGenerator health identity is invalid"
            )
        raw_active = value["active_request_id"]
        try:
            active = None if raw_active is None else UUID(str(raw_active))
        except (ValueError, TypeError) as error:
            raise VoiceGeneratorRuntimeError(
                "HEALTH_RESPONSE_INVALID", "VoiceGenerator active request is invalid"
            ) from error
        if active is not None and (str(active) != raw_active or active.int == 0):
            raise VoiceGeneratorRuntimeError(
                "HEALTH_RESPONSE_INVALID", "VoiceGenerator active request is invalid"
            )
        return VoiceGeneratorHostHealth(
            ready=ready,
            status=status,
            runtime_identity=identity,
            runtime_fingerprint=fingerprint,
            active_request_id=active,
        )

    async def create(self, request: VoiceGeneratorHostRequest) -> HostGenerationReceipt:
        envelope = await asyncio.to_thread(
            self._request,
            "POST",
            "/v1/generations",
            payload=request.wire_payload(),
        )
        return self._receipt(envelope, request)

    async def get(self, request: VoiceGeneratorHostRequest) -> HostGenerationReceipt:
        envelope = await asyncio.to_thread(
            self._request,
            "GET",
            f"/v1/generations/{request.request_id}",
        )
        return self._receipt(envelope, request)

    async def cancel(self, request: VoiceGeneratorHostRequest) -> HostGenerationReceipt:
        payload = {
            "protocol_version": HOST_PROTOCOL_VERSION,
            "request_id": str(request.request_id),
            "request_digest": request.request_digest,
        }
        envelope = await asyncio.to_thread(
            self._request,
            "POST",
            f"/v1/generations/{request.request_id}/cancel",
            payload=payload,
        )
        return self._receipt(envelope, request)

    async def download_audio(
        self,
        request: VoiceGeneratorHostRequest,
        receipt: HostGenerationReceipt,
    ) -> VoiceGeneratorAudioResult:
        if (
            receipt.status is not HostGenerationStatus.COMPLETED
            or receipt.request_id != request.request_id
            or receipt.request_digest != request.request_digest
            or receipt.audio_sha256 is None
            or receipt.audio_size_bytes is None
        ):
            raise VoiceGeneratorRuntimeError(
                "AUDIO_NOT_PUBLISHED", "VoiceGenerator audio is not published"
            )
        envelope = await asyncio.to_thread(
            self._request,
            "GET",
            f"/v1/generations/{request.request_id}/audio",
            maximum=MAX_AUDIO_BYTES,
            accept="audio/wav",
        )
        if envelope.status != 200:
            self._raise_error(envelope)
        headers = self._headers_checked(envelope)
        content_type = next(
            (value for name, value in envelope.headers if name.lower() == "content-type"),
            None,
        )
        digest = hashlib.sha256(envelope.body).hexdigest()
        if (
            content_type != "audio/wav"
            or headers.get(REQUEST_ID_HEADER.lower()) != str(request.request_id)
            or headers.get(RUNTIME_FINGERPRINT_HEADER.lower())
            != EXPECTED_RUNTIME_FINGERPRINT
            or headers.get(AUDIO_SHA256_HEADER.lower()) != digest
            or headers.get(AUDIO_BYTES_HEADER.lower()) != str(len(envelope.body))
            or headers.get(AUDIO_FORMAT_HEADER.lower()) != EXPECTED_AUDIO_FORMAT_HEADER
            or digest != receipt.audio_sha256
            or len(envelope.body) != receipt.audio_size_bytes
        ):
            raise VoiceGeneratorRuntimeError(
                "AUDIO_EVIDENCE_MISMATCH", "VoiceGenerator audio evidence changed"
            )
        metrics = inspect_generated_wav(envelope.body)
        return VoiceGeneratorAudioResult(
            request_id=request.request_id,
            audio_bytes=envelope.body,
            audio_sha256=digest,
            runtime_fingerprint=EXPECTED_RUNTIME_FINGERPRINT,
            metrics=metrics,
        )


def inspect_generated_wav(payload: bytes) -> VoiceGeneratorAudioMetrics:
    """Validate the full canonical WAV and derive bounded machine metrics."""

    if not 44 <= len(payload) <= MAX_AUDIO_BYTES:
        raise VoiceGeneratorRuntimeError(
            "AUDIO_SIZE_INVALID", "VoiceGenerator WAV size is invalid"
        )
    if payload[:4] != b"RIFF" or payload[8:12] != b"WAVE":
        raise VoiceGeneratorRuntimeError(
            "AUDIO_FORMAT_INVALID", "VoiceGenerator WAV container is invalid"
        )
    if int.from_bytes(payload[4:8], "little") != len(payload) - 8:
        raise VoiceGeneratorRuntimeError(
            "AUDIO_SIZE_MISMATCH", "VoiceGenerator WAV framing is invalid"
        )
    offset = 12
    format_chunk: bytes | None = None
    data_chunk: bytes | None = None
    while offset < len(payload):
        if offset + 8 > len(payload):
            raise VoiceGeneratorRuntimeError(
                "AUDIO_FORMAT_INVALID", "VoiceGenerator WAV chunk is truncated"
            )
        name = payload[offset : offset + 4]
        size = int.from_bytes(payload[offset + 4 : offset + 8], "little")
        start = offset + 8
        end = start + size
        padded = end + (size & 1)
        if padded > len(payload):
            raise VoiceGeneratorRuntimeError(
                "AUDIO_FORMAT_INVALID", "VoiceGenerator WAV chunk is truncated"
            )
        if name == b"fmt " and format_chunk is None and data_chunk is None:
            format_chunk = payload[start:end]
        elif name == b"data" and format_chunk is not None and data_chunk is None and padded == len(payload):
            data_chunk = payload[start:end]
        else:
            raise VoiceGeneratorRuntimeError(
                "AUDIO_FORMAT_INVALID", "VoiceGenerator WAV chunks are non-canonical"
            )
        offset = padded
    if format_chunk is None or data_chunk is None or len(format_chunk) != 16:
        raise VoiceGeneratorRuntimeError(
            "AUDIO_FORMAT_INVALID", "VoiceGenerator WAV chunks are incomplete"
        )
    audio_format, channels, sample_rate, byte_rate, block_align, bits = struct.unpack(
        "<HHIIHH", format_chunk
    )
    if (
        audio_format != 1
        or channels != 2
        or sample_rate != 48_000
        or bits != 16
        or block_align != 4
        or byte_rate != 192_000
        or not data_chunk
        or len(data_chunk) % block_align
    ):
        raise VoiceGeneratorRuntimeError(
            "AUDIO_FORMAT_DRIFT", "VoiceGenerator WAV differs from PCM16 stereo 48 kHz"
        )
    frame_count = len(data_chunk) // block_align
    try:
        with wave.open(io.BytesIO(payload), "rb") as source:
            decoded = source.readframes(frame_count)
            trailing = source.readframes(1)
    except (wave.Error, EOFError) as error:
        raise VoiceGeneratorRuntimeError(
            "AUDIO_FORMAT_INVALID", "VoiceGenerator WAV cannot be decoded"
        ) from error
    if decoded != data_chunk or trailing:
        raise VoiceGeneratorRuntimeError(
            "AUDIO_FRAME_COUNT_MISMATCH", "VoiceGenerator WAV frame count changed"
        )
    sample_count = len(data_chunk) // 2
    samples = struct.unpack(f"<{sample_count}h", data_chunk)
    squares = sum(sample * sample for sample in samples)
    rms = math.sqrt(squares / sample_count) / 32768.0
    peak = max(abs(sample) for sample in samples) / 32768.0
    dc_offset = sum(samples) / sample_count / 32768.0
    clipped_fraction = sum(abs(sample) >= 32_767 for sample in samples) / sample_count
    duration_ms = round(frame_count * 1_000 / sample_rate)
    rms_dbfs = 20.0 * math.log10(max(rms, 1e-12))
    if (
        not MIN_GENERATED_AUDIO_MILLISECONDS
        <= duration_ms
        <= MAX_GENERATED_AUDIO_MILLISECONDS
        or rms_dbfs <= -55.0
        or clipped_fraction > 0.001
        or abs(dc_offset) >= 0.05
    ):
        raise VoiceGeneratorRuntimeError(
            "AUDIO_MACHINE_VALIDATION_FAILED",
            "VoiceGenerator WAV failed machine validation",
        )
    return VoiceGeneratorAudioMetrics(
        byte_size=len(payload),
        frame_count=frame_count,
        duration_milliseconds=duration_ms,
        sample_rate_hz=sample_rate,
        channels=channels,
        sample_width_bytes=2,
        peak_milli=round(peak * 1_000),
        rms_dbfs_milli=round(rms_dbfs * 1_000),
        dc_offset_milli=round(dc_offset * 1_000),
        clipped_fraction_millionths=round(clipped_fraction * 1_000_000),
    )


def _ensure_sha256(value: object, name: str, *, runtime: bool = False) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        if runtime:
            raise VoiceGeneratorRuntimeError(
                "DIGEST_INVALID", f"VoiceGenerator {name} is invalid"
            )
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _optional_sha256(value: object, name: str) -> str | None:
    if value is None:
        return None
    _ensure_sha256(value, name, runtime=True)
    return str(value)


def _optional_datetime(value: object, name: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.endswith("Z"):
        raise VoiceGeneratorRuntimeError(
            "GENERATION_RECEIPT_INVALID", f"VoiceGenerator {name} is invalid"
        )
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise VoiceGeneratorRuntimeError(
            "GENERATION_RECEIPT_INVALID", f"VoiceGenerator {name} is invalid"
        ) from error
    return parsed
