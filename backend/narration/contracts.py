"""Frozen public contracts for the narration subsystem.

This module deliberately contains no ORM, HTTP, worker, model, or media I/O.
It is the shared T1-A input for later schema and runtime work packages.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Final, Mapping
from uuid import NAMESPACE_URL, UUID, uuid5

NARRATION_SCOPE_CONTRACT_VERSION: Final = "narration-scope/1"
NARRATION_REVIEW_TAXONOMY_VERSION: Final = "narration-review-taxonomy/1"
MOSS_NANO_ADAPTER_CONTRACT_VERSION: Final = "moss-nano-tts-adapter/1"
MOSS_NANO_DECODE_PARAMETERS_V2: Final = "moss-nano-decode-parameters/2"
VOICE_DESIGN_ADAPTER_CONTRACT_VERSION: Final = "moss-voice-design-adapter/1"
MODEL_FINGERPRINT_SCHEMA_VERSION: Final = "moss-model-fingerprint/1"
EDITION_FINGERPRINT_SCHEMA_VERSION: Final = "narration-edition-fingerprint/1"
RENDER_FINGERPRINT_SCHEMA_VERSION: Final = "narration-render-fingerprint/1"
APP_ID: Final = "ai-novel-world-2026"
PRODUCTION_NANO_MAX_NEW_FRAMES: Final = 375
PRODUCTION_NANO_MAX_SEED: Final = 2**63 - 1
PRODUCTION_NANO_SAMPLE_MODES: Final[frozenset[str]] = frozenset(
    {"greedy", "fixed", "full"}
)
NANO_TEMPERATURE_MILLI_RANGE: Final = (100, 2_000)
NANO_TOP_P_MILLI_RANGE: Final = (1, 1_000)
NANO_TOP_K_RANGE: Final = (1, 100)
NANO_AUDIO_REPETITION_PENALTY_MILLI_RANGE: Final = (1_000, 2_000)

LOCAL_OWNER_ID: Final = UUID("29cf94d9-a5c9-54ec-912c-5dfff8738c4c")
LOCAL_WORKSPACE_ID: Final = UUID("f0e2e632-bc99-52d2-9916-bb906aa4da6e")

_SAFE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,95}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")


class ContractError(ValueError):
    """Raised when a caller violates a frozen narration contract."""


class UnknownTaxonomyCodeError(ContractError):
    """Raised for a code outside the exact frozen taxonomy."""


class AdapterKind(str, Enum):
    MOSS_NANO_TTS = "moss_nano_tts"
    VOICE_DESIGN = "voice_design"


class AdapterHealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"


class CancellationGranularity(str, Enum):
    NONE = "none"
    SEGMENT_BOUNDARY = "segment_boundary"


class CancelDisposition(str, Enum):
    REQUESTED = "requested"
    ALREADY_TERMINAL = "already_terminal"
    NOT_FOUND = "not_found"
    UNSUPPORTED = "unsupported"


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class ReviewIssueSeverity(str, Enum):
    WARNING = "warning"
    BLOCKER = "blocker"


WARNING_CODES: Final[tuple[str, ...]] = (
    "W_SPEAKER_MEDIUM_CONFIDENCE",
    "W_NEW_ANONYMOUS_SPEAKER",
    "W_GENERIC_VOICE_FALLBACK",
    "W_MANUAL_OVERRIDE_INHERITED",
    "W_PRONUNCIATION_SOFT_FALLBACK",
    "W_CLOUD_ASSISTED_USED",
    "W_SCENE_BOUNDARY_MEDIUM_CONFIDENCE",
)

BLOCKER_CODES: Final[tuple[str, ...]] = (
    "B_SPEAKER_UNKNOWN",
    "B_SPEAKER_LOW_CONFIDENCE",
    "B_CHARACTER_ALIAS_CONFLICT",
    "B_CHARACTER_REFERENCE_INVALID",
    "B_ANONYMOUS_IDENTITY_CONFLICT",
    "B_CASTING_TARGET_UNRESOLVED",
    "B_VOICE_MISSING",
    "B_VOICE_VERSION_UNAVAILABLE",
    "B_VOICE_RIGHTS_UNAVAILABLE",
    "B_PRONUNCIATION_HARD_CONFLICT",
    "B_CLOUD_DECISION_UNAVAILABLE",
)

WORKFLOW_FAILURE_CODES: Final[tuple[str, ...]] = (
    "F_ANALYZER_RUNTIME",
    "F_MODEL_IDENTITY_MISMATCH",
    "F_MODEL_OUTPUT_SCHEMA_INVALID",
    "F_INPUT_FINGERPRINT_CHANGED",
    "F_SCOPE_VIOLATION",
    "F_CONSENT_REVOKED_BEFORE_CALL",
    "F_ADAPTER_UNAVAILABLE",
)

_ISSUE_SEVERITY: Final[dict[str, ReviewIssueSeverity]] = {
    **{code: ReviewIssueSeverity.WARNING for code in WARNING_CODES},
    **{code: ReviewIssueSeverity.BLOCKER for code in BLOCKER_CODES},
}


@dataclass(frozen=True, slots=True)
class NarrationRequestScope:
    """Server-authoritative local scope; it is not an authentication token."""

    owner_id: UUID = LOCAL_OWNER_ID
    workspace_id: UUID = LOCAL_WORKSPACE_ID
    app_id: str = APP_ID
    is_local_only: bool = True
    contract_version: str = NARRATION_SCOPE_CONTRACT_VERSION

    @classmethod
    def fixed_local(cls) -> "NarrationRequestScope":
        return cls()

    def ensure_fixed_local(self) -> "NarrationRequestScope":
        if self != NarrationRequestScope.fixed_local():
            raise ContractError(
                "narration scope must come from the fixed server-side local scope"
            )
        return self


def issue_severity(code: str) -> ReviewIssueSeverity:
    """Return server-owned severity, rejecting every unknown/failure code."""

    try:
        return _ISSUE_SEVERITY[code]
    except KeyError as error:
        raise UnknownTaxonomyCodeError(f"unknown review taxonomy code: {code}") from error


def ensure_workflow_failure_code(code: str) -> str:
    if code not in WORKFLOW_FAILURE_CODES:
        raise UnknownTaxonomyCodeError(f"unknown workflow failure code: {code}")
    return code


@dataclass(frozen=True, slots=True)
class ReviewIssue:
    code: str
    severity: ReviewIssueSeverity
    evidence_digest: str | None = None
    segment_id: UUID | None = None
    taxonomy_version: str = NARRATION_REVIEW_TAXONOMY_VERSION

    def __post_init__(self) -> None:
        expected = issue_severity(self.code)
        if self.severity is not expected:
            raise ContractError(
                f"severity for {self.code} is server-owned and must be {expected.value}"
            )
        if self.taxonomy_version != NARRATION_REVIEW_TAXONOMY_VERSION:
            raise ContractError("unknown review taxonomy version")
        if self.evidence_digest is not None:
            _ensure_sha256(self.evidence_digest, field_name="evidence_digest")


@dataclass(frozen=True, slots=True)
class AdapterCapabilities:
    adapter_kind: AdapterKind
    supports_warmup: bool
    supports_synthesis: bool
    supports_cancel: bool
    cancellation_granularity: CancellationGranularity
    supports_reference_audio: bool
    supports_streaming_response_bytes: bool
    supports_voice_design: bool
    max_inference_concurrency: int
    product_visible: bool = False
    production_ready: bool = False
    is_test_double: bool = False
    supports_nano_decode_parameters: bool = False

    def __post_init__(self) -> None:
        if type(self.adapter_kind) is not AdapterKind:
            raise ContractError("adapter_kind must be an AdapterKind value")
        if type(self.cancellation_granularity) is not CancellationGranularity:
            raise ContractError(
                "cancellation_granularity must be a CancellationGranularity value"
            )
        for name in (
            "supports_warmup",
            "supports_synthesis",
            "supports_cancel",
            "supports_reference_audio",
            "supports_streaming_response_bytes",
            "supports_voice_design",
            "supports_nano_decode_parameters",
            "product_visible",
            "production_ready",
            "is_test_double",
        ):
            if type(getattr(self, name)) is not bool:
                raise ContractError(f"{name} must be an exact boolean")
        if type(self.max_inference_concurrency) is not int:
            raise ContractError("max_inference_concurrency must be an exact integer")
        if self.max_inference_concurrency < 0:
            raise ContractError("max_inference_concurrency must be non-negative")
        if not self.supports_cancel and self.cancellation_granularity is not CancellationGranularity.NONE:
            raise ContractError("cancel granularity must be none when cancel is unsupported")
        if self.supports_cancel and self.cancellation_granularity is CancellationGranularity.NONE:
            raise ContractError("supported cancellation requires an explicit granularity")
        if self.adapter_kind is AdapterKind.MOSS_NANO_TTS and self.supports_voice_design:
            raise ContractError("Nano TTS adapter cannot claim voice design")
        if self.supports_nano_decode_parameters and (
            self.adapter_kind is not AdapterKind.MOSS_NANO_TTS
            or not self.supports_synthesis
        ):
            raise ContractError(
                "Nano decode parameters require a synthesizing Nano TTS adapter"
            )
        if self.adapter_kind is AdapterKind.VOICE_DESIGN and self.supports_synthesis:
            raise ContractError("Voice design adapter cannot claim narration synthesis")
        if self.is_test_double and (self.product_visible or self.production_ready):
            raise ContractError("test doubles can never be product-visible or production-ready")
        if self.product_visible and not self.production_ready:
            raise ContractError("a product-visible adapter must be production-ready")


@dataclass(frozen=True, slots=True)
class ModelFingerprint:
    adapter_contract_version: str
    model_name: str
    model_revision: str
    artifact_tree_sha256: str
    runtime_name: str
    runtime_version: str
    execution_backend: str
    protocol_version: str
    deployment_topology: str
    parameters: Mapping[str, str | int | bool | None] = field(default_factory=dict)
    schema_version: str = MODEL_FINGERPRINT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != MODEL_FINGERPRINT_SCHEMA_VERSION:
            raise ContractError("unknown model fingerprint schema version")
        for name in (
            "adapter_contract_version",
            "model_name",
            "model_revision",
            "runtime_name",
            "runtime_version",
            "execution_backend",
            "protocol_version",
            "deployment_topology",
        ):
            _ensure_nonempty(getattr(self, name), field_name=name)
        _ensure_sha256(self.artifact_tree_sha256, field_name="artifact_tree_sha256")
        if not isinstance(self.parameters, Mapping):
            raise ContractError("parameters must be a mapping")
        frozen_parameters: dict[str, str | int | bool | None] = {}
        for key, value in self.parameters.items():
            _ensure_nonempty(key, field_name="parameters key")
            if value is not None and type(value) not in {str, int, bool}:
                raise ContractError(
                    "model fingerprint parameter values must be scalar "
                    "str, int, bool, or null"
                )
            frozen_parameters[key] = value
        object.__setattr__(
            self,
            "parameters",
            MappingProxyType(frozen_parameters),
        )


@dataclass(frozen=True, slots=True)
class AdapterHealth:
    status: AdapterHealthStatus
    capabilities_sha256: str
    model_fingerprint_sha256: str | None
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if type(self.status) is not AdapterHealthStatus:
            raise ContractError("status must be an AdapterHealthStatus value")
        _ensure_sha256(self.capabilities_sha256, field_name="capabilities_sha256")
        if self.model_fingerprint_sha256 is not None:
            _ensure_sha256(
                self.model_fingerprint_sha256,
                field_name="model_fingerprint_sha256",
            )
        if self.reason_code is not None and not _SAFE_CODE.fullmatch(self.reason_code):
            raise ContractError("reason_code must be a stable, redacted uppercase code")
        if self.status in {AdapterHealthStatus.UNAVAILABLE, AdapterHealthStatus.DISABLED} and self.reason_code is None:
            raise ContractError("unavailable/disabled health requires a reason_code")


@dataclass(frozen=True, slots=True)
class ReferenceAudioInput:
    audio_bytes: bytes = field(repr=False)
    actual_sha256: str
    content_type: str = "audio/wav"

    def __post_init__(self) -> None:
        if not self.audio_bytes:
            raise ContractError("reference audio bytes cannot be empty")
        _ensure_sha256(self.actual_sha256, field_name="actual_sha256")
        if hashlib.sha256(self.audio_bytes).hexdigest() != self.actual_sha256:
            raise ContractError("reference audio actual_sha256 does not match bytes")
        if self.content_type not in {"audio/wav", "audio/flac"}:
            raise ContractError("reference audio content_type is not allowed")


@dataclass(frozen=True, slots=True)
class NanoDecodeParametersV2:
    """Canonical advanced sampling values consumed by Nano ``full`` mode.

    Fractional values use integer thousandths so version, HMAC, ModelRun and
    render fingerprints never depend on non-canonical JSON floats.  The
    official ``fixed`` path intentionally does not carry this object because
    its sampler values are compiled into the fixed ONNX graph.
    """

    text_temperature_milli: int = 1_000
    text_top_p_milli: int = 1_000
    text_top_k: int = 50
    audio_temperature_milli: int = 800
    audio_top_p_milli: int = 950
    audio_top_k: int = 25
    audio_repetition_penalty_milli: int = 1_200
    schema_version: str = MOSS_NANO_DECODE_PARAMETERS_V2

    def __post_init__(self) -> None:
        if self.schema_version != MOSS_NANO_DECODE_PARAMETERS_V2:
            raise ContractError("unknown Nano decode parameter contract")
        for field_name in (
            "text_temperature_milli",
            "text_top_p_milli",
            "text_top_k",
            "audio_temperature_milli",
            "audio_top_p_milli",
            "audio_top_k",
            "audio_repetition_penalty_milli",
        ):
            if type(getattr(self, field_name)) is not int:
                raise ContractError(f"{field_name} must be an exact integer")
        if not NANO_TEMPERATURE_MILLI_RANGE[0] <= self.text_temperature_milli <= NANO_TEMPERATURE_MILLI_RANGE[1]:
            raise ContractError("text_temperature_milli is outside the Nano bound")
        if not NANO_TEMPERATURE_MILLI_RANGE[0] <= self.audio_temperature_milli <= NANO_TEMPERATURE_MILLI_RANGE[1]:
            raise ContractError("audio_temperature_milli is outside the Nano bound")
        if not NANO_TOP_P_MILLI_RANGE[0] <= self.text_top_p_milli <= NANO_TOP_P_MILLI_RANGE[1]:
            raise ContractError("text_top_p_milli is outside the Nano bound")
        if not NANO_TOP_P_MILLI_RANGE[0] <= self.audio_top_p_milli <= NANO_TOP_P_MILLI_RANGE[1]:
            raise ContractError("audio_top_p_milli is outside the Nano bound")
        if not NANO_TOP_K_RANGE[0] <= self.text_top_k <= NANO_TOP_K_RANGE[1]:
            raise ContractError("text_top_k is outside the Nano bound")
        if not NANO_TOP_K_RANGE[0] <= self.audio_top_k <= NANO_TOP_K_RANGE[1]:
            raise ContractError("audio_top_k is outside the Nano bound")
        if not (
            NANO_AUDIO_REPETITION_PENALTY_MILLI_RANGE[0]
            <= self.audio_repetition_penalty_milli
            <= NANO_AUDIO_REPETITION_PENALTY_MILLI_RANGE[1]
        ):
            raise ContractError(
                "audio_repetition_penalty_milli is outside the Nano bound"
            )

    def wire_payload(self) -> Mapping[str, str | int]:
        return MappingProxyType(
            {
                "schema_version": self.schema_version,
                "text_temperature_milli": self.text_temperature_milli,
                "text_top_p_milli": self.text_top_p_milli,
                "text_top_k": self.text_top_k,
                "audio_temperature_milli": self.audio_temperature_milli,
                "audio_top_p_milli": self.audio_top_p_milli,
                "audio_top_k": self.audio_top_k,
                "audio_repetition_penalty_milli": self.audio_repetition_penalty_milli,
            }
        )

    @classmethod
    def from_wire_payload(cls, value: object) -> "NanoDecodeParametersV2":
        expected_keys = {
            "schema_version",
            "text_temperature_milli",
            "text_top_p_milli",
            "text_top_k",
            "audio_temperature_milli",
            "audio_top_p_milli",
            "audio_top_k",
            "audio_repetition_penalty_milli",
        }
        if type(value) is not dict or set(value) != expected_keys:
            raise ContractError("Nano decode parameter shape is invalid")
        return cls(
            schema_version=value["schema_version"],
            text_temperature_milli=value["text_temperature_milli"],
            text_top_p_milli=value["text_top_p_milli"],
            text_top_k=value["text_top_k"],
            audio_temperature_milli=value["audio_temperature_milli"],
            audio_top_p_milli=value["audio_top_p_milli"],
            audio_top_k=value["audio_top_k"],
            audio_repetition_penalty_milli=value[
                "audio_repetition_penalty_milli"
            ],
        )


@dataclass(frozen=True, slots=True)
class SynthesisRequest:
    request_id: UUID
    scope: NarrationRequestScope
    text: str = field(repr=False)
    voice: str
    seed: int
    sample_mode: str
    max_new_frames: int
    decode_parameters: NanoDecodeParametersV2 | None = None
    reference_audio: ReferenceAudioInput | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.scope.ensure_fixed_local()
        _ensure_nonempty(self.text, field_name="text")
        _ensure_nonempty(self.voice, field_name="voice")
        _ensure_nonempty(self.sample_mode, field_name="sample_mode")
        if type(self.seed) is not int or not 0 <= self.seed <= PRODUCTION_NANO_MAX_SEED:
            raise ContractError("seed is outside the Nano runtime bound")
        if self.max_new_frames <= 0:
            raise ContractError("max_new_frames must be positive")
        if self.decode_parameters is not None:
            if type(self.decode_parameters) is not NanoDecodeParametersV2:
                raise ContractError("decode_parameters must use the Nano v2 contract")
            if self.sample_mode != "full":
                raise ContractError(
                    "advanced Nano decode parameters are effective only in full mode"
                )


@dataclass(frozen=True, slots=True)
class SynthesisResult:
    request_id: UUID
    audio_bytes: bytes = field(repr=False)
    actual_output_sha256: str
    sample_rate_hz: int
    channels: int
    sample_width_bytes: int
    model_fingerprint: ModelFingerprint
    worker_generation: int
    content_type: str = "audio/wav"

    def __post_init__(self) -> None:
        if not self.audio_bytes:
            raise ContractError("synthesis output cannot be empty")
        _ensure_sha256(self.actual_output_sha256, field_name="actual_output_sha256")
        if hashlib.sha256(self.audio_bytes).hexdigest() != self.actual_output_sha256:
            raise ContractError("actual_output_sha256 does not match returned bytes")
        if min(self.sample_rate_hz, self.channels, self.sample_width_bytes, self.worker_generation) <= 0:
            raise ContractError("audio format and worker_generation must be positive")
        if self.content_type != "audio/wav":
            raise ContractError("Nano synthesis result must be audio/wav")


@dataclass(frozen=True, slots=True)
class VoiceDesignRequest:
    request_id: UUID
    scope: NarrationRequestScope
    description: str = field(repr=False)
    preview_text: str = field(repr=False)
    seed: int

    def __post_init__(self) -> None:
        self.scope.ensure_fixed_local()
        _ensure_nonempty(self.description, field_name="description")
        _ensure_nonempty(self.preview_text, field_name="preview_text")


@dataclass(frozen=True, slots=True)
class VoiceDesignResult:
    request_id: UUID
    candidate_audio_bytes: bytes = field(repr=False)
    actual_output_sha256: str
    model_fingerprint: ModelFingerprint

    def __post_init__(self) -> None:
        if not self.candidate_audio_bytes:
            raise ContractError("voice design output cannot be empty")
        _ensure_sha256(self.actual_output_sha256, field_name="actual_output_sha256")
        if hashlib.sha256(self.candidate_audio_bytes).hexdigest() != self.actual_output_sha256:
            raise ContractError("actual_output_sha256 does not match candidate bytes")


def _ensure_nonempty(value: str, *, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field_name} must be a non-empty string")


def _ensure_sha256(value: str, *, field_name: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ContractError(f"{field_name} must be 64 lowercase hexadecimal characters")


assert uuid5(NAMESPACE_URL, "app://ai-novel-world-2026/local-owner/v1") == LOCAL_OWNER_ID
assert uuid5(NAMESPACE_URL, "app://ai-novel-world-2026/local-workspace/v1") == LOCAL_WORKSPACE_ID
