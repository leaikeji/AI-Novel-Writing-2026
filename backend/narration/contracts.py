"""Frozen public contracts for the narration subsystem.

This module deliberately contains no ORM, HTTP, worker, model, or media I/O.
It is the shared T1-A input for later schema and runtime work packages.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Final
from uuid import NAMESPACE_URL, UUID, uuid5

NARRATION_SCOPE_CONTRACT_VERSION: Final = "narration-scope/1"
NARRATION_REVIEW_TAXONOMY_VERSION: Final = "narration-review-taxonomy/1"
TTS_PROVIDER_CONTRACT_VERSION: Final = "qwen-tts-provider/1"
TTS_MODEL_FINGERPRINT_SCHEMA_VERSION: Final = "qwen-tts-model-fingerprint/1"
QWEN_TTS_PRODUCT_LANGUAGE: Final = "zh-CN"
QWEN_TTS_VOICE_DESIGN_POLICY_VERSION: Final = "qwen-tts-mandarin-only/1"
EDITION_FINGERPRINT_SCHEMA_VERSION: Final = "narration-edition-fingerprint/1"
RENDER_FINGERPRINT_SCHEMA_VERSION: Final = "narration-render-fingerprint/1"
APP_ID: Final = "ai-novel-world-2026"

LOCAL_OWNER_ID: Final = UUID("29cf94d9-a5c9-54ec-912c-5dfff8738c4c")
LOCAL_WORKSPACE_ID: Final = UUID("f0e2e632-bc99-52d2-9916-bb906aa4da6e")
LOCAL_OWNER_ACTOR_ID: Final = "owner"

_SAFE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,95}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_NON_MANDARIN_VOICE_TERMS: Final[tuple[str, ...]] = (
    "方言",
    "口音",
    "粤语",
    "广东话",
    "四川话",
    "四川腔",
    "东北话",
    "东北腔",
    "上海话",
    "沪语",
    "闽南语",
    "客家话",
    "吴语",
    "陕西话",
    "河南话",
    "山东话",
    "天津话",
    "北京腔",
    "台湾腔",
    "港腔",
    "日语",
    "韩语",
    "英语",
    "英文",
)


class ContractError(ValueError):
    """Raised when a caller violates a frozen narration contract."""


def require_mandarin_language(value: str) -> str:
    """Accept the only product TTS language without silently normalizing it."""

    if value != QWEN_TTS_PRODUCT_LANGUAGE:
        raise ContractError("Qwen TTS product language must be zh-CN")
    return value


def require_mandarin_voice_design(value: str) -> str:
    """Reject explicit dialect or foreign-language voice-design instructions."""

    normalized = value.strip()
    _ensure_nonempty(normalized, field_name="description")
    if any(term in normalized for term in _NON_MANDARIN_VOICE_TERMS):
        raise ContractError(
            "voice design must describe a Mandarin voice without dialect instructions"
        )
    return normalized


class UnknownTaxonomyCodeError(ContractError):
    """Raised for a code outside the exact frozen taxonomy."""


class TTSProviderId(str, Enum):
    """Stable product-facing Provider identities."""

    LOCAL_QWEN3_TTS = "local_qwen3_tts"
    ALIYUN_QWEN_AUDIO_TTS = "aliyun_qwen_audio_tts"


class TTSVoiceKind(str, Enum):
    PRESET = "preset"
    REFERENCE_CLONE = "reference_clone"
    DESIGNED = "designed"


class TTSAudioFormat(str, Enum):
    WAV = "wav"


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


TTS_PROVIDER_ERROR_CODES: Final[frozenset[str]] = frozenset(
    {
        "TTS_PROVIDER_DISABLED",
        "TTS_PROVIDER_UNAVAILABLE",
        "TTS_PROVIDER_AUTH_FAILED",
        "TTS_PROVIDER_RATE_LIMITED",
        "TTS_PROVIDER_TIMEOUT",
        "TTS_PROVIDER_RESPONSE_INVALID",
        "TTS_PROVIDER_CANCELLED",
        "TTS_PROVIDER_CONSENT_REQUIRED",
        "TTS_VOICE_UNAVAILABLE",
        "TTS_MODEL_IDENTITY_MISMATCH",
    }
)


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

# These findings are wholly replaced when the owner supplies (or the service
# safely inherits) an exact speaker plus resolved casting target.  Keep the
# set shared so manual correction and inheritance cannot drift apart.
SPEAKER_CORRECTION_ISSUE_CODES: Final[frozenset[str]] = frozenset(
    {
        "B_SPEAKER_UNKNOWN",
        "B_SPEAKER_LOW_CONFIDENCE",
        "B_CHARACTER_ALIAS_CONFLICT",
        "B_CHARACTER_REFERENCE_INVALID",
        "B_ANONYMOUS_IDENTITY_CONFLICT",
        "B_CASTING_TARGET_UNRESOLVED",
        "B_VOICE_MISSING",
        "B_VOICE_VERSION_UNAVAILABLE",
        "B_VOICE_RIGHTS_UNAVAILABLE",
        "W_SPEAKER_MEDIUM_CONFIDENCE",
    }
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
class TTSProviderCapabilities:
    provider_id: TTSProviderId
    supports_synthesis: bool
    supports_presets: bool
    supports_reference_clone: bool
    supports_voice_design: bool
    supports_instructions: bool
    supports_streaming_first_audio: bool
    supports_warmup: bool
    supports_cancel: bool
    cancellation_granularity: CancellationGranularity
    max_inference_concurrency: int
    product_visible: bool = False
    production_ready: bool = False
    is_test_double: bool = False
    contract_version: str = TTS_PROVIDER_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if type(self.provider_id) is not TTSProviderId:
            raise ContractError("provider_id must be a TTSProviderId value")
        if self.contract_version != TTS_PROVIDER_CONTRACT_VERSION:
            raise ContractError("unknown TTS Provider contract version")
        for name in (
            "supports_synthesis",
            "supports_presets",
            "supports_reference_clone",
            "supports_voice_design",
            "supports_instructions",
            "supports_streaming_first_audio",
            "supports_warmup",
            "supports_cancel",
            "product_visible",
            "production_ready",
            "is_test_double",
        ):
            if type(getattr(self, name)) is not bool:
                raise ContractError(f"{name} must be an exact boolean")
        if type(self.cancellation_granularity) is not CancellationGranularity:
            raise ContractError(
                "cancellation_granularity must be a CancellationGranularity value"
            )
        if isinstance(self.max_inference_concurrency, bool) or not isinstance(
            self.max_inference_concurrency, int
        ):
            raise ContractError("max_inference_concurrency must be an exact integer")
        if self.max_inference_concurrency < 0:
            raise ContractError("max_inference_concurrency must be non-negative")
        if self.supports_cancel != (
            self.cancellation_granularity is not CancellationGranularity.NONE
        ):
            raise ContractError("cancel support and granularity disagree")
        if self.is_test_double and (self.product_visible or self.production_ready):
            raise ContractError(
                "test doubles can never be product-visible or production-ready"
            )
        if self.product_visible and not self.production_ready:
            raise ContractError("a product-visible Provider must be production-ready")


@dataclass(frozen=True, slots=True)
class TTSModelIdentity:
    provider_id: TTSProviderId
    model_id: str
    model_revision: str
    runtime_id: str
    runtime_version: str
    quantization: str
    artifact_tree_sha256: str
    schema_version: str = TTS_MODEL_FINGERPRINT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if type(self.provider_id) is not TTSProviderId:
            raise ContractError("provider_id must be a TTSProviderId value")
        if self.schema_version != TTS_MODEL_FINGERPRINT_SCHEMA_VERSION:
            raise ContractError("unknown TTS model fingerprint schema version")
        for name in (
            "model_id",
            "model_revision",
            "runtime_id",
            "runtime_version",
            "quantization",
        ):
            _ensure_nonempty(getattr(self, name), field_name=name)
        _ensure_sha256(
            self.artifact_tree_sha256,
            field_name="artifact_tree_sha256",
        )


@dataclass(frozen=True, slots=True)
class TTSVoiceInput:
    kind: TTSVoiceKind
    provider_voice_id: str
    reference_audio: "ReferenceAudioInput | None" = field(default=None, repr=False)
    reference_text: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if type(self.kind) is not TTSVoiceKind:
            raise ContractError("voice kind must be a TTSVoiceKind value")
        _ensure_nonempty(self.provider_voice_id, field_name="provider_voice_id")
        if self.kind is TTSVoiceKind.REFERENCE_CLONE:
            if self.reference_text is not None:
                _ensure_nonempty(self.reference_text, field_name="reference_text")
            if self.reference_audio is None and self.reference_text is not None:
                raise ContractError("reference_text requires reference audio")
        elif self.reference_audio is not None or self.reference_text is not None:
            raise ContractError("only reference clone may carry reference material")


@dataclass(frozen=True, slots=True)
class TTSSynthesisRequest:
    request_id: UUID
    scope: NarrationRequestScope
    text: str = field(repr=False)
    language: str
    voice: TTSVoiceInput
    seed: int | None = None
    instruction: str | None = field(default=None, repr=False)
    audio_format: TTSAudioFormat = TTSAudioFormat.WAV

    def __post_init__(self) -> None:
        self.scope.ensure_fixed_local()
        _ensure_nonempty(self.text, field_name="text")
        _ensure_nonempty(self.language, field_name="language")
        if type(self.voice) is not TTSVoiceInput:
            raise ContractError("voice must use the frozen TTS voice contract")
        if self.seed is not None and (
            type(self.seed) is not int or not 0 <= self.seed <= 2**63 - 1
        ):
            raise ContractError("seed must be null or a non-negative signed 64-bit integer")
        if self.instruction is not None:
            _ensure_nonempty(self.instruction, field_name="instruction")
        if type(self.audio_format) is not TTSAudioFormat:
            raise ContractError("audio_format must be a TTSAudioFormat value")


@dataclass(frozen=True, slots=True)
class TTSSynthesisResult:
    request_id: UUID
    audio_bytes: bytes = field(repr=False)
    actual_output_sha256: str
    sample_rate_hz: int
    channels: int
    sample_width_bytes: int
    model_identity: TTSModelIdentity
    content_type: str = "audio/wav"

    def __post_init__(self) -> None:
        if not self.audio_bytes:
            raise ContractError("synthesis output cannot be empty")
        _ensure_sha256(self.actual_output_sha256, field_name="actual_output_sha256")
        if hashlib.sha256(self.audio_bytes).hexdigest() != self.actual_output_sha256:
            raise ContractError("actual_output_sha256 does not match returned bytes")
        if min(self.sample_rate_hz, self.channels, self.sample_width_bytes) <= 0:
            raise ContractError("audio format values must be positive")
        if type(self.model_identity) is not TTSModelIdentity:
            raise ContractError("model_identity must use the frozen TTS model contract")
        if self.content_type != "audio/wav":
            raise ContractError("the current TTS Provider contract returns WAV only")


@dataclass(frozen=True, slots=True)
class TTSVoicePreparationRequest:
    request_id: UUID
    scope: NarrationRequestScope
    preview_text: str = field(repr=False)
    language: str
    description: str | None = field(default=None, repr=False)
    reference_audio: "ReferenceAudioInput | None" = field(default=None, repr=False)
    reference_text: str | None = field(default=None, repr=False)
    seed: int | None = None

    def __post_init__(self) -> None:
        self.scope.ensure_fixed_local()
        _ensure_nonempty(self.preview_text, field_name="preview_text")
        require_mandarin_language(self.language)
        has_design = self.description is not None
        has_clone = self.reference_audio is not None
        if has_design == has_clone:
            raise ContractError(
                "voice preparation requires exactly one of description or reference audio"
            )
        if self.description is not None:
            require_mandarin_voice_design(self.description)
            if self.reference_text is not None:
                raise ContractError("voice design cannot carry reference_text")
        elif self.reference_text is not None:
            _ensure_nonempty(self.reference_text, field_name="reference_text")
        if self.seed is not None and (
            type(self.seed) is not int or not 0 <= self.seed <= 2**63 - 1
        ):
            raise ContractError("seed must be null or a non-negative signed 64-bit integer")


@dataclass(frozen=True, slots=True)
class TTSVoicePreparationResult:
    request_id: UUID
    provider_voice_id: str
    preview_audio_bytes: bytes = field(repr=False)
    actual_output_sha256: str
    model_identity: TTSModelIdentity
    voice_kind: TTSVoiceKind

    def __post_init__(self) -> None:
        _ensure_nonempty(self.provider_voice_id, field_name="provider_voice_id")
        if not self.preview_audio_bytes:
            raise ContractError("voice preparation preview cannot be empty")
        _ensure_sha256(self.actual_output_sha256, field_name="actual_output_sha256")
        if hashlib.sha256(self.preview_audio_bytes).hexdigest() != self.actual_output_sha256:
            raise ContractError("actual_output_sha256 does not match preview bytes")
        if type(self.model_identity) is not TTSModelIdentity:
            raise ContractError("model_identity must use the frozen TTS model contract")
        if self.voice_kind not in {
            TTSVoiceKind.REFERENCE_CLONE,
            TTSVoiceKind.DESIGNED,
        }:
            raise ContractError("voice preparation result must be cloned or designed")


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


def _ensure_nonempty(value: str, *, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field_name} must be a non-empty string")


def _ensure_sha256(value: str, *, field_name: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ContractError(f"{field_name} must be 64 lowercase hexadecimal characters")


assert uuid5(NAMESPACE_URL, "app://ai-novel-world-2026/local-owner/v1") == LOCAL_OWNER_ID
assert uuid5(NAMESPACE_URL, "app://ai-novel-world-2026/local-workspace/v1") == LOCAL_WORKSPACE_ID
