"""Versioned wire contracts for narration settings and voice management.

T2-A freezes these models before any settings UI or voice-source implementation
is allowed to run in parallel.  The models intentionally expose capability and
rights state instead of letting a client infer support from the presence of a
button or endpoint.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
import re
from typing import TYPE_CHECKING, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .official_presets import (
    OFFICIAL_PRESET_PROVENANCE_SCHEMA_VERSION,
    OFFICIAL_PRESETS,
    OFFICIAL_PRESETS_BY_ID,
    canonical_sha256 as official_preset_canonical_sha256,
    official_preset_validation_tier,
)

if TYPE_CHECKING:
    from .nano_experiments import NanoDecodeParametersV3


NARRATION_SETTINGS_API_VERSION: Final = "narration-settings-api/1"
NARRATION_SETTINGS_SCHEMA_VERSION: Final = "narration-settings/1"
NARRATION_CAPABILITY_SCHEMA_VERSION: Final = "narration-capabilities/4"
NARRATION_VOICE_SCHEMA_VERSION: Final = "narration-voice/2"
NARRATION_CACHE_SCHEMA_VERSION: Final = "narration-cache/1"
REFERENCE_UPLOAD_MAX_BYTES: Final = 16 * 1024 * 1024
REFERENCE_UPLOAD_MIME_TYPES: Final[tuple[str, ...]] = (
    "audio/wav",
    "audio/flac",
)

_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_SAFE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,95}$")
_LANGUAGE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,2}$")
_SAFE_FIELD = re.compile(r"^[a-z][a-z0-9_.]{0,159}$")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CapabilityKey(str, Enum):
    NARRATION_PRODUCT = "narration_product"
    READING_SETTINGS = "reading_settings"
    NARRATION_SYNTHESIS = "narration_synthesis"
    PRODUCT_PLAYER = "product_player"
    EDITOR_PRODUCTION = "editor_production"
    VOICE_PREVIEW = "voice_preview"
    PRESET_VOICE_SOURCE = "preset_voice_source"
    REFERENCE_CLONE = "reference_clone"
    GENERIC_VOICE_POOL = "generic_voice_pool"
    AUTOMATIC_GENERIC_CASTING = "automatic_generic_casting"
    AUTOMATIC_SPEAKER_DETECTION = "automatic_speaker_detection"
    CLOUD_ASSISTED_ANALYSIS = "cloud_assisted_analysis"
    VOICE_GENERATOR = "voice_generator"
    CACHE_CLEANUP = "cache_cleanup"
    CHARACTER_VOICE_MATCHING = "character_voice_matching"
    CHARACTER_CAST_PLANNING = "character_cast_planning"
    NANO_ADVANCED_TUNING = "nano_advanced_tuning"
    PRIVATE_VOICE_DELETION = "private_voice_deletion"
    AUTOMATIC_CHARACTER_VOICE_GENERATION = "automatic_character_voice_generation"


T4_PRODUCT_CAPABILITY_KEYS: Final[frozenset[CapabilityKey]] = frozenset(
    {
        CapabilityKey.NARRATION_PRODUCT,
        CapabilityKey.READING_SETTINGS,
        CapabilityKey.NARRATION_SYNTHESIS,
        CapabilityKey.PRODUCT_PLAYER,
        CapabilityKey.EDITOR_PRODUCTION,
        CapabilityKey.AUTOMATIC_SPEAKER_DETECTION,
        CapabilityKey.CACHE_CLEANUP,
    }
)


class CapabilityState(str, Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"
    HOLD = "hold"


class FeatureCapability(_StrictModel):
    key: CapabilityKey
    state: CapabilityState
    visible: bool = Field(strict=True)
    actionable: bool = Field(strict=True)
    reason_code: str | None = Field(default=None, max_length=96)
    required_gate: str | None = Field(default=None, max_length=32)

    @field_validator("reason_code")
    @classmethod
    def validate_reason_code(cls, value: str | None) -> str | None:
        if value is not None and not _SAFE_CODE.fullmatch(value):
            raise ValueError("reason_code must be a stable uppercase code")
        return value

    @model_validator(mode="after")
    def validate_state_shape(self) -> "FeatureCapability":
        if self.state is CapabilityState.ENABLED:
            if not self.visible or not self.actionable or self.reason_code is not None:
                raise ValueError(
                    "enabled capability must be visible/actionable without a reason"
                )
        else:
            if self.actionable or self.reason_code is None:
                raise ValueError(
                    "non-enabled capability must be non-actionable with a reason"
                )
        if not self.visible and self.actionable:
            raise ValueError("hidden capability cannot be actionable")
        return self


class NarrationCapabilities(_StrictModel):
    schema_version: Literal["narration-capabilities/4"] = (
        NARRATION_CAPABILITY_SCHEMA_VERSION
    )
    items: list[FeatureCapability]

    @model_validator(mode="after")
    def validate_complete_matrix(self) -> "NarrationCapabilities":
        keys = [item.key for item in self.items]
        if len(keys) != len(set(keys)):
            raise ValueError("capability keys must be unique")
        if set(keys) != set(CapabilityKey):
            raise ValueError("capability matrix must contain every frozen key")
        return self

    def item(self, key: CapabilityKey) -> FeatureCapability:
        return next(item for item in self.items if item.key is key)


def t2_hold_capabilities() -> NarrationCapabilities:
    """Return the truthful pre-T2-GATE product baseline.

    Technical Sidecar readiness is reported separately.  It never upgrades a
    product capability on its own.
    """

    definitions = (
        (CapabilityKey.NARRATION_PRODUCT, True, "T2_GATE_REQUIRED", "T2-GATE"),
        (CapabilityKey.READING_SETTINGS, True, "T2_GATE_REQUIRED", "T2-GATE"),
        (CapabilityKey.NARRATION_SYNTHESIS, False, "T4_GATE_REQUIRED", "T4-GATE"),
        (CapabilityKey.PRODUCT_PLAYER, False, "T4_GATE_REQUIRED", "T4-GATE"),
        (CapabilityKey.EDITOR_PRODUCTION, False, "T4_GATE_REQUIRED", "T4-GATE"),
        (CapabilityKey.VOICE_PREVIEW, True, "VOICE_SOURCE_NOT_APPROVED", "T2-D"),
        (
            CapabilityKey.PRESET_VOICE_SOURCE,
            True,
            "OFFICIAL_PRESET_CATALOG_NOT_RELEASED",
            "T4-PRESET",
        ),
        (
            CapabilityKey.REFERENCE_CLONE,
            False,
            "REFERENCE_CLONE_PRODUCT_GATE_HOLD",
            "T2-D",
        ),
        (
            CapabilityKey.GENERIC_VOICE_POOL,
            True,
            "GENERIC_VOICE_ASSETS_UNAVAILABLE",
            "T2-E",
        ),
        (
            CapabilityKey.AUTOMATIC_GENERIC_CASTING,
            False,
            "GENERIC_VOICE_POOL_UNAVAILABLE",
            "T2-E",
        ),
        (
            CapabilityKey.AUTOMATIC_SPEAKER_DETECTION,
            False,
            "T3_GATE_REQUIRED",
            "T3-GATE",
        ),
        (
            CapabilityKey.CLOUD_ASSISTED_ANALYSIS,
            True,
            "CLOUD_CONSENT_FLOW_NOT_READY",
            "T2-G",
        ),
        (
            CapabilityKey.VOICE_GENERATOR,
            False,
            "VOICE_GENERATOR_NO_GO",
            "T5-GATE",
        ),
        (CapabilityKey.CACHE_CLEANUP, True, "T2_GATE_REQUIRED", "T2-F"),
        (
            CapabilityKey.CHARACTER_VOICE_MATCHING,
            True,
            "TTS_FEATURE_STARTING",
            "TTS35-CORE",
        ),
        (
            CapabilityKey.CHARACTER_CAST_PLANNING,
            True,
            "TTS_FEATURE_STARTING",
            "TTS47-CAST",
        ),
        (
            CapabilityKey.NANO_ADVANCED_TUNING,
            True,
            "TTS_FEATURE_STARTING",
            "TTS35-CORE",
        ),
        (
            CapabilityKey.PRIVATE_VOICE_DELETION,
            True,
            "TTS_FEATURE_STARTING",
            "TTS35-CORE",
        ),
        (
            CapabilityKey.AUTOMATIC_CHARACTER_VOICE_GENERATION,
            False,
            "TTS_FEATURE_STARTING",
            "TTS55-CHARACTER",
        ),
    )
    return NarrationCapabilities(
        items=[
            FeatureCapability(
                key=key,
                state=CapabilityState.HOLD
                if reason.endswith("REQUIRED") or reason.endswith("HOLD")
                else CapabilityState.UNAVAILABLE,
                visible=visible,
                actionable=False,
                reason_code=reason,
                required_gate=gate,
            )
            for key, visible, reason, gate in definitions
        ]
    )


class NarrationErrorCode(str, Enum):
    REQUEST_VALIDATION_FAILED = "REQUEST_VALIDATION_FAILED"
    RESPONSE_CONTRACT_VIOLATION = "RESPONSE_CONTRACT_VIOLATION"
    SETTINGS_BACKEND_NOT_INSTALLED = "SETTINGS_BACKEND_NOT_INSTALLED"
    CAPABILITY_DISABLED = "CAPABILITY_DISABLED"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"
    DISK_SPACE_INSUFFICIENT = "DISK_SPACE_INSUFFICIENT"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    SCOPE_VIOLATION = "SCOPE_VIOLATION"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    INVALID_STATE = "INVALID_STATE"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    VOICE_PROFILE_NOT_FOUND = "VOICE_PROFILE_NOT_FOUND"
    VOICE_VERSION_NOT_FOUND = "VOICE_VERSION_NOT_FOUND"
    VOICE_VERSION_NOT_LOCKED = "VOICE_VERSION_NOT_LOCKED"
    VOICE_RIGHTS_REQUIRED = "VOICE_RIGHTS_REQUIRED"
    VOICE_RIGHTS_UNAVAILABLE = "VOICE_RIGHTS_UNAVAILABLE"
    VOICE_SOURCE_UNAVAILABLE = "VOICE_SOURCE_UNAVAILABLE"
    REFERENCE_AUDIO_INVALID = "REFERENCE_AUDIO_INVALID"
    PREVIEW_UNAVAILABLE = "PREVIEW_UNAVAILABLE"
    PREVIEW_FAILED = "PREVIEW_FAILED"
    CLOUD_CONSENT_REQUIRED = "CLOUD_CONSENT_REQUIRED"
    CLOUD_CONSENT_REVOKED = "CLOUD_CONSENT_REVOKED"
    GENERIC_VOICE_POOL_UNAVAILABLE = "GENERIC_VOICE_POOL_UNAVAILABLE"
    UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    VALIDATION_FAILED = "VALIDATION_FAILED"


class NarrationApiErrorDetail(_StrictModel):
    contract_version: Literal["narration-settings-api/1"] = (
        NARRATION_SETTINGS_API_VERSION
    )
    code: NarrationErrorCode
    message: str = Field(min_length=1, max_length=400)
    retryable: bool = Field(strict=True)
    field: str | None = Field(default=None, max_length=160)
    current_version: int | None = Field(default=None, ge=0, strict=True)
    capability: CapabilityKey | None = None

    @field_validator("field")
    @classmethod
    def validate_field(cls, value: str | None) -> str | None:
        if value is not None and not _SAFE_FIELD.fullmatch(value):
            raise ValueError("field must be a safe dotted identifier")
        return value


class NarrationApiErrorResponse(_StrictModel):
    detail: NarrationApiErrorDetail


class RuntimeLifecycleStatus(str, Enum):
    DISABLED = "disabled"
    STARTING = "starting"
    READY = "ready"
    UNAVAILABLE = "unavailable"
    STOPPING = "stopping"


class NarrationRuntimeStatus(_StrictModel):
    technical_enabled: bool = Field(strict=True)
    lifecycle_status: RuntimeLifecycleStatus
    sidecar_reachable: bool = Field(strict=True)
    model_ready: bool = Field(strict=True)
    product_visible: bool = Field(strict=True)
    protocol_version: str = Field(min_length=1, max_length=80)
    model_fingerprint_sha256: str | None = Field(
        default=None, pattern=r"^[a-f0-9]{64}$"
    )
    reason_code: str | None = Field(default=None, max_length=96)

    @field_validator("reason_code")
    @classmethod
    def validate_runtime_reason(cls, value: str | None) -> str | None:
        if value is not None and not _SAFE_CODE.fullmatch(value):
            raise ValueError("reason_code must be a stable uppercase code")
        return value

    @model_validator(mode="after")
    def validate_runtime_shape(self) -> "NarrationRuntimeStatus":
        if self.lifecycle_status is RuntimeLifecycleStatus.READY:
            if not self.technical_enabled or not self.sidecar_reachable or not self.model_ready:
                raise ValueError("ready runtime must be technically enabled and model-ready")
            if self.model_fingerprint_sha256 is None:
                raise ValueError("ready runtime requires a model fingerprint")
        if self.product_visible and self.lifecycle_status is not RuntimeLifecycleStatus.READY:
            raise ValueError("product-visible runtime must be ready")
        if self.lifecycle_status in {
            RuntimeLifecycleStatus.DISABLED,
            RuntimeLifecycleStatus.UNAVAILABLE,
        } and self.reason_code is None:
            raise ValueError("disabled/unavailable runtime requires a reason code")
        return self


class CloudConsentState(str, Enum):
    NOT_GRANTED = "not_granted"
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


class NarrationCloudConsent(_StrictModel):
    consent_id: UUID | None = None
    version: int = Field(ge=0, strict=True)
    state: CloudConsentState
    purpose: Literal["narration_speaker_analysis"] = "narration_speaker_analysis"
    data_scope: Literal["uncertain_segments_with_minimal_context"] = (
        "uncertain_segments_with_minimal_context"
    )
    notice_version: str | None = Field(default=None, max_length=120)
    provider_id: str | None = Field(default=None, max_length=160)
    model_id: str | None = Field(default=None, max_length=160)
    confirmed_at: datetime | None = None
    revoked_at: datetime | None = None

    @model_validator(mode="after")
    def validate_consent_shape(self) -> "NarrationCloudConsent":
        if (self.provider_id is None) != (self.model_id is None):
            raise ValueError("provider_id and model_id must be set together")
        if self.state is CloudConsentState.NOT_GRANTED:
            if self.version != 0 or any(
                value is not None
                for value in (
                    self.consent_id,
                    self.notice_version,
                    self.provider_id,
                    self.model_id,
                    self.confirmed_at,
                    self.revoked_at,
                )
            ):
                raise ValueError("not-granted consent is the empty version-zero projection")
            return self
        if (
            self.consent_id is None
            or self.version < 1
            or self.notice_version is None
            or self.confirmed_at is None
        ):
            raise ValueError("persisted consent requires identity, version, notice, and confirmation")
        if self.state is CloudConsentState.ACTIVE:
            if self.revoked_at is not None:
                raise ValueError("active consent cannot be revoked")
        elif self.state is CloudConsentState.REVOKED:
            if self.revoked_at is None:
                raise ValueError("revoked consent requires revocation evidence")
        elif self.revoked_at is not None:
            raise ValueError("expired consent cannot claim revocation evidence")
        return self


class NarrationAuthorizationState(_StrictModel):
    mode: Literal["fixed_local_owner_workspace"] = "fixed_local_owner_workspace"
    can_read: bool = Field(strict=True)
    can_configure: bool = Field(strict=True)
    can_manage_voice_assets: bool = Field(strict=True)
    can_confirm_voice_rights: bool = Field(strict=True)
    cloud_consent: NarrationCloudConsent


class CreateNarrationCloudConsentRequest(_StrictModel):
    notice_version: str = Field(min_length=1, max_length=120)
    data_scope: Literal["uncertain_segments_with_minimal_context"]
    provider_id: str | None = Field(min_length=1, max_length=160)
    model_id: str | None = Field(min_length=1, max_length=160)
    confirmed: bool = Field(strict=True)

    @model_validator(mode="after")
    def require_confirmation(self) -> "CreateNarrationCloudConsentRequest":
        if not self.confirmed:
            raise ValueError("cloud consent must be explicitly confirmed")
        if (self.provider_id is None) != (self.model_id is None):
            raise ValueError("provider_id and model_id must be set together")
        return self


class RevokeNarrationCloudConsentRequest(_StrictModel):
    consent_id: UUID
    expected_version: int = Field(ge=1, strict=True)


class ScriptReviewPolicy(str, Enum):
    BLOCKERS_ONLY = "blockers_only"
    ALWAYS_REVIEW = "always_review"


class AnalysisMode(str, Enum):
    LOCAL_RULES_ONLY = "local_rules_only"
    CLOUD_ASSISTED = "cloud_assisted"


class FirstPersonVoiceMode(str, Enum):
    NARRATOR = "narrator"
    CHARACTER = "character"


class InnerMonologueVoiceMode(str, Enum):
    CHARACTER = "character"
    NARRATOR = "narrator"


class AnonymousReuseScope(str, Enum):
    SCENE = "scene"
    CHAPTER = "chapter"
    NOVEL = "novel"


class UnknownSpeakerAction(str, Enum):
    BLOCK = "block"
    REQUIRE_REVIEW = "require_review"


class OutputAudioFormat(str, Enum):
    M4A_AAC_LC = "m4a_aac_lc"


class NarratorVoiceSelection(_StrictModel):
    profile_id: UUID
    version_id: UUID


class NarrationTextRules(_StrictModel):
    read_chapter_title: bool = Field(strict=True)
    read_author_notes: bool = Field(strict=True)
    read_section_breaks: bool = Field(strict=True)
    first_person_mode: FirstPersonVoiceMode
    first_person_character_id: UUID | None
    inner_monologue_mode: InnerMonologueVoiceMode

    @model_validator(mode="after")
    def validate_first_person_target(self) -> "NarrationTextRules":
        if self.first_person_mode is FirstPersonVoiceMode.CHARACTER:
            if self.first_person_character_id is None:
                raise ValueError("character first-person mode requires a character id")
        elif self.first_person_character_id is not None:
            raise ValueError("narrator first-person mode cannot carry a character id")
        return self


class NarrationTimingSettings(_StrictModel):
    sentence_gap_ms: int = Field(ge=0, le=5_000, strict=True)
    paragraph_gap_ms: int = Field(ge=0, le=10_000, strict=True)
    section_gap_ms: int = Field(ge=0, le=15_000, strict=True)


class NarrationCastingSettings(_StrictModel):
    anonymous_reuse_scope: AnonymousReuseScope
    same_scene_voice_deduplication: bool = Field(strict=True)
    unknown_speaker_action: UnknownSpeakerAction


class NarrationPlaybackPreferences(_StrictModel):
    playback_rate: float = Field(ge=0.5, le=3.0, strict=True)
    volume: float = Field(ge=0.0, le=1.0, strict=True)


class NarrationSettingsValues(_StrictModel):
    narrator: NarratorVoiceSelection | None
    language: str = Field(min_length=2, max_length=40)
    output_format: OutputAudioFormat
    script_review_policy: ScriptReviewPolicy
    analysis_mode: AnalysisMode
    text_rules: NarrationTextRules
    timing: NarrationTimingSettings
    casting: NarrationCastingSettings
    playback: NarrationPlaybackPreferences

    @field_validator("language")
    @classmethod
    def validate_language(cls, value: str) -> str:
        if not _LANGUAGE.fullmatch(value):
            raise ValueError("language must be a conservative BCP-47 tag")
        return value


class NarrationSettingsResource(_StrictModel):
    contract_version: Literal["narration-settings-api/1"] = (
        NARRATION_SETTINGS_API_VERSION
    )
    schema_version: Literal["narration-settings/1"] = (
        NARRATION_SETTINGS_SCHEMA_VERSION
    )
    novel_id: UUID
    settings_id: UUID | None = None
    exists: bool = Field(strict=True)
    version: int = Field(ge=0, strict=True)
    values: NarrationSettingsValues
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def validate_identity(self) -> "NarrationSettingsResource":
        if self.exists:
            if self.settings_id is None or self.version < 1:
                raise ValueError("persisted settings require id and positive version")
        elif self.settings_id is not None or self.version != 0 or self.updated_at is not None:
            raise ValueError("default settings must have null identity and version zero")
        return self


class UpdateNarrationSettingsRequest(_StrictModel):
    expected_version: int = Field(ge=0, strict=True)
    values: NarrationSettingsValues


class UpdateNarrationPlaybackPreferencesRequest(_StrictModel):
    expected_version: int = Field(ge=0, strict=True)
    playback: NarrationPlaybackPreferences


class NarrationScopeKind(str, Enum):
    VOLUME = "volume"
    CHAPTER = "chapter"


class NarrationScopeOverrideValues(_StrictModel):
    narrator: NarratorVoiceSelection | None
    language: str | None = Field(min_length=2, max_length=40)
    text_rules: NarrationTextRules | None
    timing: NarrationTimingSettings | None

    @field_validator("language")
    @classmethod
    def validate_language(cls, value: str | None) -> str | None:
        if value is not None and not _LANGUAGE.fullmatch(value):
            raise ValueError("language must be a conservative BCP-47 tag")
        return value

    def is_empty(self) -> bool:
        return all(
            value is None
            for value in (self.narrator, self.language, self.text_rules, self.timing)
        )


class NarrationScopeOverrideResource(_StrictModel):
    contract_version: Literal["narration-settings-api/1"] = (
        NARRATION_SETTINGS_API_VERSION
    )
    override_id: UUID | None = None
    novel_id: UUID
    scope_kind: NarrationScopeKind
    scope_id: UUID
    enabled: bool = Field(strict=True)
    version: int = Field(ge=0, strict=True)
    overrides: NarrationScopeOverrideValues

    @model_validator(mode="after")
    def validate_override(self) -> "NarrationScopeOverrideResource":
        if self.enabled:
            if self.override_id is None or self.version < 1 or self.overrides.is_empty():
                raise ValueError("enabled override requires identity, version, and a value")
        elif self.override_id is not None or self.version != 0 or not self.overrides.is_empty():
            raise ValueError("disabled override is the empty version-zero projection")
        return self


class NarrationScopeOverrideListResponse(_StrictModel):
    contract_version: Literal["narration-settings-api/1"] = (
        NARRATION_SETTINGS_API_VERSION
    )
    novel_id: UUID
    items: list[NarrationScopeOverrideResource]

    @model_validator(mode="after")
    def validate_scope(self) -> "NarrationScopeOverrideListResponse":
        keys = [(item.scope_kind, item.scope_id) for item in self.items]
        if len(keys) != len(set(keys)):
            raise ValueError("scope overrides must be unique per kind and scope")
        if any(item.novel_id != self.novel_id for item in self.items):
            raise ValueError("scope overrides must belong to the response novel")
        return self


class PutNarrationScopeOverrideRequest(_StrictModel):
    expected_version: int = Field(ge=0, strict=True)
    enabled: bool = Field(strict=True)
    overrides: NarrationScopeOverrideValues

    @model_validator(mode="after")
    def validate_override(self) -> "PutNarrationScopeOverrideRequest":
        if self.enabled == self.overrides.is_empty():
            raise ValueError("enabled override must contain values; disabled must be empty")
        return self


class VoiceProfileStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"
    UNAVAILABLE = "unavailable"


class VoiceSourceType(str, Enum):
    PRESET = "preset"
    UPLOADED = "uploaded"
    GENERATED = "generated"


class VoiceVersionState(str, Enum):
    DRAFT = "draft"
    PREVIEW_READY = "preview_ready"
    LOCKED = "locked"
    UNAVAILABLE = "unavailable"
    DELETED = "deleted"


class VoiceQualityState(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class VoiceActivationBasis(str, Enum):
    PREVIEW_CONFIRMED = "preview_confirmed"
    EXPLICIT_OFFICIAL_PRESET_SELECTION = "explicit_official_preset_selection"
    CHARACTER_ONE_CLICK_GENERATION = "character_one_click_generation"
    GENERIC_VOICE_PACK_GENERATION = "generic_voice_pack_generation"
    EXPERIMENTAL_MACHINE_VALIDATED = "experimental_machine_validated"


class VoiceValidationBasis(str, Enum):
    PENDING = "pending"
    HUMAN_ACCEPTED = "human_accepted"
    MACHINE_VALIDATED = "machine_validated"
    NOT_REQUIRED = "not_required"


class VoiceRightsState(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"
    REVIEW_BLOCKED = "review_blocked"


class VoiceRightsSummary(_StrictModel):
    rights_record_id: UUID
    state: VoiceRightsState
    notice_version: str = Field(min_length=1, max_length=120)
    source_kind: Literal[
        "official_preset",
        "preset_catalog",
        "user_upload",
        "voice_generator",
    ]
    source_identifier_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    purpose: Literal["private_novel_narration"]
    commercial_use: bool = Field(strict=True)
    redistribution: bool = Field(strict=True)
    voice_cloning: bool = Field(strict=True)
    subject_consent_recorded: bool = Field(strict=True)
    confirmed_at: datetime
    expires_at: datetime | None = None
    risk_flags: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("risk_flags")
    @classmethod
    def validate_risk_flags(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("voice rights risk flags must be unique")
        if any(not _SAFE_CODE.fullmatch(value) for value in values):
            raise ValueError("voice rights risk flags must be stable codes")
        return values


class VoiceRightsDeclarationRequest(_StrictModel):
    notice_version: str = Field(min_length=1, max_length=120)
    source_identifier: str = Field(min_length=1, max_length=240)
    purpose: Literal["private_novel_narration"]
    commercial_use: bool = Field(strict=True)
    redistribution: bool = Field(strict=True)
    voice_cloning: bool = Field(strict=True)
    subject_consent_reference: str | None = Field(max_length=240)
    confirmed: bool = Field(strict=True)

    @model_validator(mode="after")
    def validate_rights_confirmation(self) -> "VoiceRightsDeclarationRequest":
        if not self.confirmed:
            raise ValueError("voice rights must be explicitly confirmed")
        if not self.voice_cloning:
            raise ValueError("uploaded reference requires voice-cloning permission")
        return self


class MediaAssetLink(_StrictModel):
    asset_id: UUID
    content_path: str = Field(min_length=1, max_length=300)
    mime_type: str = Field(min_length=1, max_length=120)
    byte_size: int = Field(ge=1, strict=True)
    duration_ms: int = Field(ge=1, strict=True)
    checksum_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_content_path(self) -> "MediaAssetLink":
        expected = f"/media-assets/{self.asset_id}/content"
        if self.content_path != expected:
            raise ValueError("media link path must exactly match asset_id")
        return self


class OfficialPresetProvenance(_StrictModel):
    schema_version: Literal["moss-tts-official-preset-provenance/1.0"] = (
        OFFICIAL_PRESET_PROVENANCE_SCHEMA_VERSION
    )
    repository: str = Field(min_length=1, max_length=200)
    revision: str = Field(pattern=r"^[a-f0-9]{40}$")
    manifest_path: str = Field(min_length=1, max_length=200)
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    preset_id: str = Field(pattern=r"^onnx\.[A-Za-z][A-Za-z0-9]{0,79}$")
    manifest_voice: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9]{0,79}$")
    prompt_codes_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    prompt_frame_count: int = Field(ge=1, le=1_000_000, strict=True)
    prompt_quantizer_count: int = Field(ge=1, le=1_024, strict=True)
    model_fingerprint_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    provenance_fingerprint_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_against_pinned_manifest(self) -> "OfficialPresetProvenance":
        preset = OFFICIAL_PRESETS_BY_ID.get(self.preset_id)
        if preset is None or self.manifest_voice != preset.manifest_voice:
            raise ValueError("official preset_id is absent from the pinned ONNX manifest")
        expected = preset.provenance()
        actual = self.model_dump(mode="python")
        if actual != expected:
            raise ValueError("official preset provenance disagrees with pinned ONNX manifest")
        unsigned = {
            key: value
            for key, value in actual.items()
            if key != "provenance_fingerprint_sha256"
        }
        if self.provenance_fingerprint_sha256 != official_preset_canonical_sha256(
            unsigned
        ):
            raise ValueError("official preset provenance fingerprint is invalid")
        return self


class OfficialPresetCatalogItem(_StrictModel):
    preset_id: str = Field(pattern=r"^onnx\.[A-Za-z][A-Za-z0-9]{0,79}$")
    display_name: str = Field(min_length=1, max_length=160)
    group: str = Field(min_length=1, max_length=80)
    language: str = Field(min_length=2, max_length=40)
    local_use_status: Literal["available"] = "available"
    commercial_distribution_status: Literal["not_evaluated"] = "not_evaluated"
    validation_tier: Literal[
        "canonical_chapter_verified", "pinned_catalog_unreviewed"
    ]
    language_scope: Literal["zh-CN", "en", "ja-JP"]
    selectable_now: bool = Field(strict=True)
    previewable_now: bool = Field(strict=True)
    renderable_existing: bool = Field(strict=True)
    usage_notice: Literal["private_local_writing_tool"] = (
        "private_local_writing_tool"
    )
    provenance: OfficialPresetProvenance

    @model_validator(mode="after")
    def validate_catalog_identity(self) -> "OfficialPresetCatalogItem":
        preset = OFFICIAL_PRESETS_BY_ID.get(self.preset_id)
        if preset is None or (
            self.display_name,
            self.group,
            self.language,
            self.language_scope,
            self.provenance.preset_id,
        ) != (
            preset.display_name,
            preset.group,
            preset.language,
            preset.language,
            preset.preset_id,
        ):
            raise ValueError("official preset catalog metadata disagrees with manifest")
        if self.validation_tier != official_preset_validation_tier(self.preset_id):
            raise ValueError("official preset validation tier changed")
        return self


class OfficialPresetCatalogResponse(_StrictModel):
    schema_version: Literal["moss-tts-official-preset-catalog/2.0"] = (
        "moss-tts-official-preset-catalog/2.0"
    )
    items: list[OfficialPresetCatalogItem]

    @model_validator(mode="after")
    def validate_complete_catalog(self) -> "OfficialPresetCatalogResponse":
        ids = [item.preset_id for item in self.items]
        if ids != [item.preset_id for item in OFFICIAL_PRESETS]:
            raise ValueError(
                "official preset catalog must publish all 18 pinned presets in order"
            )
        return self


class VoiceProfileVersionResource(_StrictModel):
    schema_version: Literal["narration-voice/2"] = NARRATION_VOICE_SCHEMA_VERSION
    version_id: UUID
    profile_id: UUID
    version_number: int = Field(ge=1, strict=True)
    source_type: VoiceSourceType
    state: VoiceVersionState
    provider_id: str | None = Field(default=None, max_length=160)
    model_id: str | None = Field(default=None, max_length=160)
    model_revision: str | None = Field(default=None, max_length=160)
    preset_key: str | None = Field(default=None, max_length=160)
    language: str = Field(min_length=2, max_length=40)
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    quality_state: VoiceQualityState
    activation_basis: VoiceActivationBasis
    validation_basis: VoiceValidationBasis
    rights: VoiceRightsSummary
    official_preset: OfficialPresetProvenance | None = None
    reference_asset_id: UUID | None = None
    preview_asset: MediaAssetLink | None = None
    description_available: bool = Field(strict=True)
    locked_at: datetime | None = None
    created_at: datetime

    @field_validator("language")
    @classmethod
    def validate_language(cls, value: str) -> str:
        if not _LANGUAGE.fullmatch(value):
            raise ValueError("language must be a conservative BCP-47 tag")
        return value

    @model_validator(mode="after")
    def validate_version_shape(self) -> "VoiceProfileVersionResource":
        experimental = (
            self.source_type is VoiceSourceType.GENERATED
            and self.activation_basis
            is VoiceActivationBasis.EXPERIMENTAL_MACHINE_VALIDATED
            and self.validation_basis is VoiceValidationBasis.MACHINE_VALIDATED
        )
        character_generated = (
            self.source_type is VoiceSourceType.GENERATED
            and self.activation_basis
            is VoiceActivationBasis.CHARACTER_ONE_CLICK_GENERATION
            and self.validation_basis is VoiceValidationBasis.MACHINE_VALIDATED
        )
        generic_pack_generated = (
            self.source_type is VoiceSourceType.GENERATED
            and self.activation_basis
            is VoiceActivationBasis.GENERIC_VOICE_PACK_GENERATION
            and self.validation_basis is VoiceValidationBasis.MACHINE_VALIDATED
        )
        if self.source_type is VoiceSourceType.PRESET and self.preset_key is None:
            raise ValueError("preset source requires preset_key")
        if (
            self.source_type is not VoiceSourceType.PRESET
            and not experimental
            and self.preset_key is not None
        ):
            raise ValueError("non-preset source cannot carry preset_key")
        if experimental and self.preset_key is None:
            raise ValueError("experimental Nano source requires its base preset")
        if self.source_type is VoiceSourceType.UPLOADED and self.reference_asset_id is None:
            raise ValueError("uploaded source requires a reference asset")
        if self.rights.source_kind == "official_preset":
            if (
                self.source_type not in {
                    VoiceSourceType.PRESET,
                    VoiceSourceType.GENERATED,
                }
                or self.official_preset is None
                or self.official_preset.preset_id != self.preset_key
            ):
                raise ValueError("official preset rights require exact pinned provenance")
        elif self.official_preset is not None:
            raise ValueError("only official preset rights can publish preset provenance")
        if (
            self.source_type is VoiceSourceType.GENERATED
            and not experimental
            and not self.description_available
        ):
            raise ValueError("generated source requires a private description record")
        if self.state is VoiceVersionState.LOCKED:
            human_confirmed = (
                self.activation_basis is VoiceActivationBasis.PREVIEW_CONFIRMED
                and self.validation_basis is VoiceValidationBasis.HUMAN_ACCEPTED
                and self.quality_state is VoiceQualityState.ACCEPTED
                and self.locked_at is not None
            )
            official_direct = (
                self.source_type is VoiceSourceType.PRESET
                and self.activation_basis
                is VoiceActivationBasis.EXPLICIT_OFFICIAL_PRESET_SELECTION
                and self.validation_basis is VoiceValidationBasis.NOT_REQUIRED
                and self.quality_state is VoiceQualityState.PENDING
                and self.locked_at is None
            )
            machine_validated = (
                (experimental or character_generated or generic_pack_generated)
                and self.quality_state is VoiceQualityState.ACCEPTED
                and self.locked_at is None
            )
            if not (human_confirmed or official_direct or machine_validated):
                raise ValueError("locked version activation evidence is inconsistent")
        elif self.locked_at is not None:
            raise ValueError("only a locked version can carry locked_at")
        elif (
            self.activation_basis is not VoiceActivationBasis.PREVIEW_CONFIRMED
            or self.validation_basis is not VoiceValidationBasis.PENDING
        ):
            raise ValueError("unlocked version cannot carry activation evidence")
        return self


class VoiceProfileResource(_StrictModel):
    contract_version: Literal["narration-settings-api/1"] = (
        NARRATION_SETTINGS_API_VERSION
    )
    schema_version: Literal["narration-voice/2"] = NARRATION_VOICE_SCHEMA_VERSION
    profile_id: UUID
    novel_id: UUID | None = None
    name: str = Field(min_length=1, max_length=240)
    status: VoiceProfileStatus
    version: int = Field(ge=1, strict=True)
    current_version_id: UUID | None = None
    versions: list[VoiceProfileVersionResource]
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None

    @model_validator(mode="after")
    def validate_current_version(self) -> "VoiceProfileResource":
        version_ids = {item.version_id for item in self.versions}
        if len(version_ids) != len(self.versions):
            raise ValueError("voice versions must be unique")
        if any(item.profile_id != self.profile_id for item in self.versions):
            raise ValueError("voice versions must belong to their enclosing profile")
        if self.current_version_id is not None:
            matching = [
                item
                for item in self.versions
                if item.version_id == self.current_version_id
            ]
            if len(matching) != 1 or matching[0].state is not VoiceVersionState.LOCKED:
                raise ValueError("current version must name one locked version")
        if self.status is VoiceProfileStatus.ARCHIVED and self.archived_at is None:
            raise ValueError("archived profile requires archived_at")
        return self


class VoiceProfileListResponse(_StrictModel):
    contract_version: Literal["narration-settings-api/1"] = (
        NARRATION_SETTINGS_API_VERSION
    )
    items: list[VoiceProfileResource]


class CreateVoiceProfileRequest(_StrictModel):
    novel_id: UUID | None
    name: str = Field(min_length=1, max_length=240)


class UpdateVoiceProfileRequest(_StrictModel):
    expected_version: int = Field(ge=1, strict=True)
    name: str = Field(min_length=1, max_length=240)


class CreatePresetVoiceVersionRequest(_StrictModel):
    expected_profile_version: int = Field(ge=1, strict=True)
    preset_id: str = Field(pattern=r"^onnx\.[A-Za-z][A-Za-z0-9]{0,79}$")

    @field_validator("preset_id")
    @classmethod
    def validate_preset_id(cls, value: str) -> str:
        if value not in OFFICIAL_PRESETS_BY_ID:
            raise ValueError("preset_id is absent from the pinned ONNX manifest")
        return value


class UploadedVoiceVersionMetadata(_StrictModel):
    expected_profile_version: int = Field(ge=1, strict=True)
    language: str = Field(min_length=2, max_length=40)
    original_filename: str = Field(min_length=1, max_length=240)
    reference_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    rights: VoiceRightsDeclarationRequest

    @field_validator("language")
    @classmethod
    def validate_language(cls, value: str) -> str:
        if not _LANGUAGE.fullmatch(value):
            raise ValueError("language must be a conservative BCP-47 tag")
        return value

    @field_validator("original_filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        if "/" in value or "\\" in value or value in {".", ".."}:
            raise ValueError("original_filename must not contain a path")
        return value


class VoicePreviewStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNAVAILABLE = "unavailable"


class CreateVoicePreviewRequest(_StrictModel):
    version_id: UUID
    preview_text: str = Field(min_length=1, max_length=500)

    @field_validator("preview_text")
    @classmethod
    def validate_preview_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("preview_text cannot be blank")
        return value


class VoicePreviewResource(_StrictModel):
    contract_version: Literal["narration-settings-api/1"] = (
        NARRATION_SETTINGS_API_VERSION
    )
    preview_id: UUID
    profile_id: UUID
    version_id: UUID
    status: VoicePreviewStatus
    job_id: UUID | None = None
    asset: MediaAssetLink | None = None
    temporary: Literal[True] = True
    expires_at: datetime | None = None
    failure_code: NarrationErrorCode | None = None

    @model_validator(mode="after")
    def validate_preview_shape(self) -> "VoicePreviewResource":
        if self.status is VoicePreviewStatus.READY:
            if self.asset is None or self.expires_at is None or self.failure_code is not None:
                raise ValueError("ready preview requires an expiring asset and no failure")
        elif self.asset is not None:
            raise ValueError("non-ready preview cannot publish an asset")
        if self.status in {VoicePreviewStatus.FAILED, VoicePreviewStatus.UNAVAILABLE}:
            if self.failure_code is None:
                raise ValueError("failed/unavailable preview requires a failure code")
        elif self.failure_code is not None:
            raise ValueError("non-failed preview cannot carry a failure code")
        return self


class LockVoiceProfileRequest(_StrictModel):
    expected_profile_version: int = Field(ge=1, strict=True)
    version_id: UUID
    quality_confirmed: bool = Field(strict=True)

    @model_validator(mode="after")
    def require_quality_confirmation(self) -> "LockVoiceProfileRequest":
        if not self.quality_confirmed:
            raise ValueError("voice quality must be explicitly confirmed")
        return self


class CharacterVoiceBindingPolicy(str, Enum):
    DEDICATED = "dedicated"
    INHERITED = "inherited"
    UNSET = "unset"


class VoiceBindingImpact(_StrictModel):
    affected_chapter_count: int = Field(ge=0, strict=True)
    affected_segment_count: int = Field(ge=0, strict=True)
    historical_edition_count: int = Field(ge=0, strict=True)
    regeneration_required: bool = Field(strict=True)


class CharacterVoiceBindingResource(_StrictModel):
    contract_version: Literal["narration-settings-api/1"] = (
        NARRATION_SETTINGS_API_VERSION
    )
    binding_id: UUID | None = None
    novel_id: UUID
    character_id: UUID
    binding_policy: CharacterVoiceBindingPolicy
    profile_id: UUID | None = None
    version_id: UUID | None = None
    language: str = Field(default="zh-CN", min_length=2, max_length=40)
    version: int = Field(ge=0, strict=True)
    impact: VoiceBindingImpact
    updated_at: datetime | None = None

    @field_validator("language")
    @classmethod
    def validate_language(cls, value: str) -> str:
        if not _LANGUAGE.fullmatch(value):
            raise ValueError("language must be a conservative BCP-47 tag")
        return value

    @model_validator(mode="after")
    def validate_binding_shape(self) -> "CharacterVoiceBindingResource":
        has_voice = self.profile_id is not None and self.version_id is not None
        if (self.profile_id is None) != (self.version_id is None):
            raise ValueError("profile_id and version_id must be set together")
        if self.binding_policy is CharacterVoiceBindingPolicy.UNSET:
            if (
                has_voice
                or self.binding_id is not None
                or self.version != 0
                or self.updated_at is not None
            ):
                raise ValueError("unset binding must be the empty version-zero projection")
        elif not has_voice or self.binding_id is None or self.version < 1:
            raise ValueError("configured binding requires identity and locked voice")
        return self


class CharacterVoiceBindingListResponse(_StrictModel):
    contract_version: Literal["narration-settings-api/1"] = (
        NARRATION_SETTINGS_API_VERSION
    )
    novel_id: UUID
    items: list[CharacterVoiceBindingResource]

    @model_validator(mode="after")
    def validate_scope(self) -> "CharacterVoiceBindingListResponse":
        character_ids = [item.character_id for item in self.items]
        if len(character_ids) != len(set(character_ids)):
            raise ValueError("character voice bindings must be unique per character")
        if any(item.novel_id != self.novel_id for item in self.items):
            raise ValueError("character voice bindings must belong to the response novel")
        return self


class PutCharacterVoiceBindingRequest(_StrictModel):
    expected_version: int = Field(ge=0, strict=True)
    binding_policy: CharacterVoiceBindingPolicy
    profile_id: UUID | None = None
    version_id: UUID | None = None
    language: str = Field(min_length=2, max_length=40)

    @field_validator("language")
    @classmethod
    def validate_language(cls, value: str) -> str:
        if not _LANGUAGE.fullmatch(value):
            raise ValueError("language must be a conservative BCP-47 tag")
        return value

    @model_validator(mode="after")
    def validate_binding_shape(self) -> "PutCharacterVoiceBindingRequest":
        if (self.profile_id is None) != (self.version_id is None):
            raise ValueError("profile_id and version_id must be set together")
        has_voice = self.profile_id is not None
        if self.binding_policy is CharacterVoiceBindingPolicy.UNSET and has_voice:
            raise ValueError("unset binding cannot carry a voice")
        if self.binding_policy is not CharacterVoiceBindingPolicy.UNSET and not has_voice:
            raise ValueError("configured binding requires profile_id and version_id")
        return self


class OfficialVoiceSelectionTargetKind(str, Enum):
    NARRATOR = "narrator"
    CHARACTER = "character"


class OfficialVoicePreviewRequest(_StrictModel):
    preset_id: str = Field(pattern=r"^onnx\.[A-Za-z][A-Za-z0-9]{0,79}$")

    @field_validator("preset_id")
    @classmethod
    def validate_preset_id(cls, value: str) -> str:
        if value not in OFFICIAL_PRESETS_BY_ID:
            raise ValueError("preset_id is absent from the pinned ONNX manifest")
        return value


class OfficialVoiceSelectionRequest(_StrictModel):
    preset_id: str = Field(pattern=r"^onnx\.[A-Za-z][A-Za-z0-9]{0,79}$")
    target_kind: OfficialVoiceSelectionTargetKind
    character_id: UUID | None = None
    expected_settings_version: int = Field(ge=0, strict=True)
    expected_binding_version: int | None = Field(default=None, ge=0, strict=True)

    @model_validator(mode="after")
    def validate_selection_target(self) -> "OfficialVoiceSelectionRequest":
        if self.preset_id not in OFFICIAL_PRESETS_BY_ID:
            raise ValueError("preset_id is absent from the pinned ONNX manifest")
        if self.target_kind is OfficialVoiceSelectionTargetKind.NARRATOR:
            if self.character_id is not None or self.expected_binding_version is not None:
                raise ValueError("narrator target cannot carry character binding fields")
        elif self.character_id is None or self.expected_binding_version is None:
            raise ValueError("character target requires identity and binding version")
        return self


class OfficialVoiceSelectionResult(_StrictModel):
    command_id: UUID
    preset_id: str = Field(pattern=r"^onnx\.[A-Za-z][A-Za-z0-9]{0,79}$")
    target_kind: OfficialVoiceSelectionTargetKind
    character_id: UUID | None = None
    profile_id: UUID
    version_id: UUID
    settings_version: int = Field(ge=1, strict=True)
    binding_version: int | None = Field(default=None, ge=1, strict=True)
    target_language: str = Field(min_length=2, max_length=40)
    language_mismatch: bool = Field(strict=True)
    completed_at: datetime

    @model_validator(mode="after")
    def validate_result_target(self) -> "OfficialVoiceSelectionResult":
        preset = OFFICIAL_PRESETS_BY_ID.get(self.preset_id)
        if preset is None:
            raise ValueError("selection result preset is absent from pinned inventory")
        character_target = self.target_kind is OfficialVoiceSelectionTargetKind.CHARACTER
        if character_target != (self.character_id is not None):
            raise ValueError("selection result character identity is inconsistent")
        if character_target != (self.binding_version is not None):
            raise ValueError("selection result binding version is inconsistent")
        expected_mismatch = (
            preset.language.split("-", 1)[0].casefold()
            != self.target_language.split("-", 1)[0].casefold()
        )
        if self.language_mismatch is not expected_mismatch:
            raise ValueError("selection result language mismatch evidence changed")
        return self


class OfficialVoiceSelectionResponse(_StrictModel):
    contract_version: Literal["official-voice-selection/1.0"] = (
        "official-voice-selection/1.0"
    )
    replayed: bool = Field(strict=True)
    selection_still_current: bool = Field(strict=True)
    frozen_result: OfficialVoiceSelectionResult
    profile: VoiceProfileResource
    current_settings: NarrationSettingsResource | None = None
    current_character_binding: CharacterVoiceBindingResource | None = None

    @model_validator(mode="after")
    def validate_projection(self) -> "OfficialVoiceSelectionResponse":
        result = self.frozen_result
        narrator = result.target_kind is OfficialVoiceSelectionTargetKind.NARRATOR
        if narrator != (self.current_settings is not None):
            raise ValueError("narrator result requires exactly one settings projection")
        if narrator == (self.current_character_binding is not None):
            raise ValueError("character result requires exactly one binding projection")
        if self.profile.profile_id != result.profile_id:
            raise ValueError("selection profile projection changed identity")
        if result.version_id not in {
            item.version_id for item in self.profile.versions
        }:
            raise ValueError("selection version is absent from profile projection")
        if narrator:
            assert self.current_settings is not None
            selection = self.current_settings.values.narrator
            is_current = (
                selection is not None
                and selection.profile_id == result.profile_id
                and selection.version_id == result.version_id
            )
        else:
            assert self.current_character_binding is not None
            is_current = (
                self.current_character_binding.character_id == result.character_id
                and self.current_character_binding.profile_id == result.profile_id
                and self.current_character_binding.version_id == result.version_id
            )
        if self.selection_still_current is not is_current:
            raise ValueError("selection current-state evidence changed")
        if not self.replayed and (
            not self.selection_still_current
            or (
                narrator
                and self.current_settings is not None
                and self.current_settings.version != result.settings_version
            )
            or (
                not narrator
                and self.current_character_binding is not None
                and self.current_character_binding.version != result.binding_version
            )
        ):
            raise ValueError("new selection must return its exact committed projection")
        return self


class NanoDecodeParametersResource(_StrictModel):
    """Lossless HTTP form of the Nano advanced decode contract."""

    schema_version: Literal["nano-decode-parameters/3"] = (
        "nano-decode-parameters/3"
    )
    seed: str = Field(pattern=r"^(0|[1-9][0-9]{0,18})$")
    text_temperature_milli: int = Field(ge=100, le=2_000, strict=True)
    text_top_p_milli: int = Field(ge=1, le=1_000, strict=True)
    text_top_k: int = Field(ge=1, le=100, strict=True)
    audio_temperature_milli: int = Field(ge=100, le=2_000, strict=True)
    audio_top_p_milli: int = Field(ge=1, le=1_000, strict=True)
    audio_top_k: int = Field(ge=1, le=100, strict=True)
    audio_repetition_penalty_milli: int = Field(
        ge=1_000, le=2_000, strict=True
    )
    sample_mode: Literal["full"] = "full"
    max_new_frames: Literal[375] = 375

    @field_validator("seed")
    @classmethod
    def validate_seed_bound(cls, value: str) -> str:
        if int(value) > 9_223_372_036_854_775_807:
            raise ValueError("seed exceeds the signed 64-bit Nano bound")
        return value

    def domain(self) -> "NanoDecodeParametersV3":
        from .nano_experiments import NanoDecodeParametersV3

        payload = self.model_dump()
        payload["seed"] = int(self.seed)
        return NanoDecodeParametersV3(**payload)

    @classmethod
    def from_domain(
        cls,
        value: "NanoDecodeParametersV3",
    ) -> "NanoDecodeParametersResource":
        payload = dict(value.canonical_payload())
        payload["seed"] = str(payload["seed"])
        return cls.model_validate(payload)


class CreateNanoVoiceExperimentRequest(_StrictModel):
    contract_version: Literal["nano-voice-experiment-request/1"] = (
        "nano-voice-experiment-request/1"
    )
    base_preset_id: str = Field(
        pattern=r"^onnx\.[A-Za-z][A-Za-z0-9]{0,79}$"
    )
    target_kind: Literal["narrator", "character"]
    character_id: UUID | None = None
    expected_settings_version: int = Field(ge=0, strict=True)
    expected_binding_version: int | None = Field(default=None, ge=0, strict=True)
    parameters: NanoDecodeParametersResource

    @model_validator(mode="after")
    def validate_target_shape(self) -> "CreateNanoVoiceExperimentRequest":
        if self.base_preset_id not in OFFICIAL_PRESETS_BY_ID:
            raise ValueError("base_preset_id is absent from the pinned catalog")
        if self.target_kind == "narrator":
            if self.character_id is not None or self.expected_binding_version is not None:
                raise ValueError("narrator target cannot carry character fields")
        elif self.character_id is None or self.expected_binding_version is None:
            raise ValueError("character target requires identity and binding version")
        return self


class ApplyNanoVoiceExperimentRequest(_StrictModel):
    expected_settings_version: int = Field(ge=0, strict=True)
    expected_binding_version: int | None = Field(default=None, ge=0, strict=True)


class NanoVoiceExperimentResource(_StrictModel):
    contract_version: Literal["nano-voice-experiment/1"] = (
        "nano-voice-experiment/1"
    )
    command_id: UUID
    novel_id: UUID
    profile_id: UUID
    version_id: UUID
    background_job_id: UUID
    base_preset_id: str = Field(
        pattern=r"^onnx\.[A-Za-z][A-Za-z0-9]{0,79}$"
    )
    target_kind: Literal["narrator", "character"]
    character_id: UUID | None = None
    expected_settings_version: int = Field(ge=0, strict=True)
    expected_binding_version: int | None = Field(default=None, ge=0, strict=True)
    parameters: NanoDecodeParametersResource
    parameters_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    state: Literal[
        "pending", "running", "ready_applied", "ready_unapplied", "failed"
    ]
    reused_version: bool = Field(strict=True)
    preview: VoicePreviewResource | None = None
    current_settings: NarrationSettingsResource | None = None
    current_character_binding: CharacterVoiceBindingResource | None = None
    failure_code: str | None = Field(default=None, max_length=96)
    retryable: bool = Field(strict=True)
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_experiment_resource(self) -> "NanoVoiceExperimentResource":
        narrator = self.target_kind == "narrator"
        if narrator != (self.current_settings is not None):
            raise ValueError("Nano narrator projection requires current_settings")
        if narrator == (self.current_character_binding is not None):
            raise ValueError("Nano character projection requires current binding")
        if self.state in {"ready_applied", "ready_unapplied"} and self.preview is None:
            raise ValueError("ready Nano experiment requires its validated preview")
        if self.state == "failed":
            if self.failure_code is None or self.preview is not None:
                raise ValueError("failed Nano experiment has invalid evidence")
        elif self.failure_code is not None or self.retryable:
            raise ValueError("non-failed Nano experiment cannot carry failure evidence")
        return self


class NanoVoiceExperimentListResource(_StrictModel):
    contract_version: Literal["nano-voice-experiment-list/1"] = (
        "nano-voice-experiment-list/1"
    )
    novel_id: UUID
    items: list[NanoVoiceExperimentResource]

    @model_validator(mode="after")
    def validate_scope(self) -> "NanoVoiceExperimentListResource":
        if any(item.novel_id != self.novel_id for item in self.items):
            raise ValueError("experiment list contains another novel")
        command_ids = [item.command_id for item in self.items]
        if len(command_ids) != len(set(command_ids)):
            raise ValueError("experiment command IDs must be unique")
        return self


class CharacterVoiceMatchRequest(_StrictModel):
    contract_version: Literal["character-voice-match-request/1"] = (
        "character-voice-match-request/1"
    )
    timeline_id: UUID | None = None
    character_instance_id: UUID | None = None
    expected_binding_version: int = Field(ge=0, strict=True)


class CharacterVoiceBriefResource(_StrictModel):
    schema_version: Literal["character-voice-brief/1"] = "character-voice-brief/1"
    language: Literal["zh-CN", "en", "ja-JP"] | None = None
    presentation: Literal["masculine", "feminine", "androgynous"] | None = None
    pitch: int | None = Field(default=None, ge=-2, le=2, strict=True)
    pace: int | None = Field(default=None, ge=-2, le=2, strict=True)
    energy: int | None = Field(default=None, ge=-2, le=2, strict=True)
    texture: Literal[
        "clear", "warm", "airy", "husky", "firm", "soft", "bright", "dark"
    ] | None = None
    evidence_fields: list[str] = Field(max_length=48)


class NarratorVoiceBriefResource(_StrictModel):
    """Saved-novel-only narrator evidence; never a free-form preset choice."""

    schema_version: Literal["narrator-voice-brief/1"] = "narrator-voice-brief/1"
    language: Literal["zh-CN", "en", "ja-JP"] | None = None
    presentation: Literal["masculine", "feminine", "androgynous"] | None = None
    pitch: int | None = Field(default=None, ge=-2, le=2, strict=True)
    pace: int | None = Field(default=None, ge=-2, le=2, strict=True)
    energy: int | None = Field(default=None, ge=-2, le=2, strict=True)
    texture: Literal[
        "clear", "warm", "airy", "husky", "firm", "soft", "bright", "dark"
    ] | None = None
    evidence_fields: list[str] = Field(max_length=48)

    @field_validator("evidence_fields")
    @classmethod
    def validate_narrator_evidence_fields(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("narrator evidence fields must be unique")
        pattern = re.compile(
            r"^(language|presentation|pitch|pace|energy|texture):"
            r"(?:narration_settings\.language|novel\."
            r"(?:title|genre|subgenre|description|idea|highlight|background|main_plot))$"
        )
        if any(pattern.fullmatch(value) is None for value in values):
            raise ValueError("narrator evidence escaped the saved novel allowlist")
        return values

    @model_validator(mode="after")
    def validate_narrator_dimension_evidence(self) -> "NarratorVoiceBriefResource":
        evidenced = {value.split(":", 1)[0] for value in self.evidence_fields}
        populated = {
            field_name
            for field_name in (
                "language",
                "presentation",
                "pitch",
                "pace",
                "energy",
                "texture",
            )
            if getattr(self, field_name) is not None
        }
        if evidenced != populated:
            raise ValueError("narrator evidence must exactly cover populated dimensions")
        return self


CharacterCastPlanState = Literal[
    "reserved",
    "analyzing",
    "ready_applied",
    "ready_applied_with_warnings",
    "ready_unapplied",
    "failed",
    "superseded",
]
CharacterCastPlanItemState = Literal[
    "pending",
    "analyzing",
    "preserved",
    "scored",
    "assigned",
    "blocked",
]


VoicePreparationState = Literal[
    "reserved",
    "preparing",
    "ready",
    "ready_with_warnings",
    "failed",
    "cancelled",
    "superseded",
]
VoicePreparationItemState = Literal[
    "pending",
    "preserved",
    "queued",
    "generating",
    "ready_applied",
    "ready_unapplied",
    "fallback_official",
    "failed",
    "cancelled",
]
VoicePreparationContinuationState = Literal[
    "not_applicable",
    "pending",
    "creating",
    "created",
    "cancelled",
    "superseded",
    "failed",
]


class CreateVoicePreparationRequest(_StrictModel):
    contract_version: Literal["narration-voice-preparation-request/1"] = (
        "narration-voice-preparation-request/1"
    )
    mode: Literal["prepare_missing_dedicated"] = "prepare_missing_dedicated"
    document_id: UUID | None = None
    expected_draft_version: int | None = Field(default=None, ge=1, strict=True)
    expected_content_hash: str | None = None
    expected_settings_version: int | None = Field(default=None, ge=1, strict=True)

    @model_validator(mode="after")
    def validate_chapter_cas(self) -> "CreateVoicePreparationRequest":
        values = (
            self.expected_draft_version,
            self.expected_content_hash,
            self.expected_settings_version,
        )
        if self.document_id is None:
            if any(value is not None for value in values):
                raise ValueError("whole-book preparation cannot carry chapter CAS")
        elif any(value is None for value in values):
            raise ValueError("chapter preparation requires complete chapter CAS")
        if self.expected_content_hash is not None and _SHA256.fullmatch(
            self.expected_content_hash
        ) is None:
            raise ValueError("expected_content_hash must be lowercase SHA-256")
        return self


class VoicePreparationTargetResource(_StrictModel):
    character_id: UUID
    character_name: str = Field(min_length=1, max_length=240)
    role_type: Literal["main", "supporting"]
    chapter_speaker: bool = Field(strict=True)
    state: VoicePreparationItemState
    voice_generator_command_id: UUID | None = None
    profile_id: UUID | None = None
    voice_version_id: UUID | None = None
    failure_code: str | None = Field(default=None, max_length=96)

    @field_validator("failure_code")
    @classmethod
    def validate_failure_code(cls, value: str | None) -> str | None:
        if value is not None and _SAFE_CODE.fullmatch(value) is None:
            raise ValueError("voice preparation failure code must be stable")
        return value


class VoicePreparationResource(_StrictModel):
    contract_version: Literal["narration-voice-preparation/1"] = (
        "narration-voice-preparation/1"
    )
    command_id: UUID
    novel_id: UUID
    document_id: UUID | None = None
    state: VoicePreparationState
    server_now: datetime
    progress_current: int = Field(ge=0, strict=True)
    progress_total: int = Field(ge=0, strict=True)
    preflight_request_id: UUID | None = None
    preflight_script_version_id: UUID | None = None
    chapter_ready: bool = Field(strict=True)
    background_remaining: int = Field(ge=0, strict=True)
    continuation_state: VoicePreparationContinuationState
    narration_request_id: UUID | None = None
    current_target: VoicePreparationTargetResource | None = None
    preserved: list[VoicePreparationTargetResource]
    generated: list[VoicePreparationTargetResource]
    fallback: list[VoicePreparationTargetResource]
    failed: list[VoicePreparationTargetResource]
    cancellable: bool = Field(strict=True)
    retryable: bool = Field(strict=True)
    terminal: bool = Field(strict=True)
    failure_code: str | None = Field(default=None, max_length=96)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_projection(self) -> "VoicePreparationResource":
        if self.progress_current > self.progress_total:
            raise ValueError("voice preparation progress is invalid")
        if self.failure_code is not None and _SAFE_CODE.fullmatch(
            self.failure_code
        ) is None:
            raise ValueError("voice preparation failure code must be stable")
        active = self.state in {"reserved", "preparing"}
        if self.terminal == active:
            raise ValueError("voice preparation terminal flag drifted")
        if self.terminal and self.cancellable:
            raise ValueError("terminal voice preparation cannot be cancelled")
        if self.state == "failed" and self.failure_code is None:
            raise ValueError("failed voice preparation requires failure evidence")
        return self


class VoicePreparationListResource(_StrictModel):
    contract_version: Literal["narration-voice-preparation-list/1"] = (
        "narration-voice-preparation-list/1"
    )
    novel_id: UUID
    server_now: datetime
    items: list[VoicePreparationResource]


GenericVoicePackState = Literal[
    "missing",
    "building",
    "ready_to_activate",
    "active",
    "retired_for_new_use",
    "rejected",
    "failed",
    "superseded",
]
GenericVoicePackSlotState = Literal[
    "pending", "generating", "validated", "reused", "rejected", "failed"
]
GenericVoicePackSlotCategory = Literal[
    "child", "youth", "middle_age", "older", "neutral_group"
]


class GenericVoicePackSlotResource(_StrictModel):
    slot_id: UUID
    slot_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")
    label: str = Field(min_length=1, max_length=120)
    category: GenericVoicePackSlotCategory
    state: GenericVoicePackSlotState
    preview_available: bool = Field(strict=True)
    preview_asset: MediaAssetLink | None = None
    voice_profile_id: UUID | None = None
    voice_version_id: UUID | None = None
    failure_code: str | None = Field(default=None, max_length=96)

    @model_validator(mode="after")
    def validate_preview_identity(self) -> "GenericVoicePackSlotResource":
        has_identity = self.voice_profile_id is not None and self.voice_version_id is not None
        if (self.voice_profile_id is None) != (self.voice_version_id is None):
            raise ValueError("generic voice slot identity must be complete")
        has_preview = self.preview_asset is not None
        if self.preview_available != (has_identity and has_preview):
            raise ValueError("generic voice slot preview identity is inconsistent")
        is_published = self.state in {"validated", "reused"}
        if is_published != has_preview:
            raise ValueError("generic voice slot preview publication is inconsistent")
        return self


class GenericVoicePackResource(_StrictModel):
    contract_version: Literal["generic-voice-pack/1"] = "generic-voice-pack/1"
    language: Literal["zh-CN"] = "zh-CN"
    pack_version_id: UUID | None = None
    state: GenericVoicePackState
    prepared_slots: int = Field(ge=0, le=24, strict=True)
    total_slots: Literal[24] = 24
    slots: list[GenericVoicePackSlotResource]
    failure_code: str | None = Field(default=None, max_length=96)
    updated_at: datetime

    @model_validator(mode="after")
    def validate_pack(self) -> "GenericVoicePackResource":
        prepared = sum(item.state in {"validated", "reused"} for item in self.slots)
        if prepared != self.prepared_slots or len({item.slot_key for item in self.slots}) != len(self.slots):
            raise ValueError("generic voice pack slot projection is invalid")
        if self.state == "missing":
            if self.pack_version_id is not None or self.slots or self.prepared_slots:
                raise ValueError("missing generic voice pack must be empty")
        elif self.pack_version_id is None:
            raise ValueError("generic voice pack requires immutable identity")
        return self


GenericVoiceBuildCommandState = Literal[
    "queued", "building", "ready", "failed", "cancelled", "superseded"
]


class GenericVoiceBuildCommandResource(_StrictModel):
    contract_version: Literal["generic-voice-generation-command/1"] = (
        "generic-voice-generation-command/1"
    )
    command_id: UUID
    pack_version_id: UUID
    state: GenericVoiceBuildCommandState
    progress_current: int = Field(ge=0, le=24, strict=True)
    progress_total: Literal[24] = 24
    current_slot_key: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,79}$")
    cancellable: bool = Field(strict=True)
    retryable: bool = Field(strict=True)
    terminal: bool = Field(strict=True)
    failure_code: str | None = Field(default=None, max_length=96)
    updated_at: datetime


class GenericVoicePackLoadResource(_StrictModel):
    pack: GenericVoicePackResource
    command: GenericVoiceBuildCommandResource | None = None


class RejectGenericVoiceSlotRequest(_StrictModel):
    expected_pack_version_id: UUID


class CreateCharacterCastPlanRequest(_StrictModel):
    contract_version: Literal["character-cast-plan-request/1"] = (
        "character-cast-plan-request/1"
    )
    timeline_id: UUID
    mode: Literal["fill_and_deduplicate"] = "fill_and_deduplicate"


class CharacterCastTargetResource(_StrictModel):
    target_key: str = Field(pattern=r"^(narrator|character:[0-9a-f-]{36})$")
    target_kind: Literal["narrator", "character"]
    character_id: UUID | None = None
    character_name: str | None = Field(default=None, min_length=1, max_length=240)
    role_type: str | None = Field(default=None, min_length=1, max_length=30)

    @model_validator(mode="after")
    def validate_target_identity(self) -> "CharacterCastTargetResource":
        narrator = self.target_kind == "narrator"
        if narrator:
            if (
                self.target_key != "narrator"
                or self.character_id is not None
                or self.character_name is not None
                or self.role_type is not None
            ):
                raise ValueError("narrator target cannot carry character identity")
        elif (
            self.character_id is None
            or self.character_name is None
            or self.role_type is None
            or self.target_key != f"character:{self.character_id}"
        ):
            raise ValueError("character cast target identity is incomplete")
        return self


class CharacterCastPlanItemResource(_StrictModel):
    item_id: UUID
    target: CharacterCastTargetResource
    state: CharacterCastPlanItemState
    attempt: int = Field(ge=0, strict=True)
    workspace_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    lease_expires_at: datetime | None = None
    brief: CharacterVoiceBriefResource | NarratorVoiceBriefResource | None = None
    selected_preset_id: str | None = Field(
        default=None,
        pattern=r"^onnx\.[A-Za-z][A-Za-z0-9]{0,79}$",
    )
    score_milli: int | None = Field(default=None, ge=0, le=1_000, strict=True)
    profile_id: UUID | None = None
    version_id: UUID | None = None
    voice_action_command_id: UUID | None = None
    warning_code: str | None = Field(default=None, max_length=96)
    failure_code: str | None = Field(default=None, max_length=96)

    @field_validator("warning_code", "failure_code")
    @classmethod
    def validate_cast_item_code(cls, value: str | None) -> str | None:
        if value is not None and _SAFE_CODE.fullmatch(value) is None:
            raise ValueError("cast item codes must be stable")
        return value

    @model_validator(mode="after")
    def validate_cast_item_shape(self) -> "CharacterCastPlanItemResource":
        if (self.profile_id is None) != (self.version_id is None):
            raise ValueError("preserved cast voice identity is incomplete")
        if self.state == "analyzing" and self.lease_expires_at is None:
            raise ValueError("analyzing cast item requires a lease")
        if self.state != "analyzing" and self.lease_expires_at is not None:
            raise ValueError("only an analyzing cast item carries a lease")
        if self.state in {"scored", "assigned"} and (
            self.brief is None
            or self.selected_preset_id is None
            or self.score_milli is None
        ):
            raise ValueError("scored cast item requires brief, preset and score")
        if self.state == "preserved" and self.version_id is None:
            raise ValueError("preserved cast item requires its voice identity")
        return self


class CharacterCastAssignmentResource(_StrictModel):
    target: CharacterCastTargetResource
    preset_id: str = Field(pattern=r"^onnx\.[A-Za-z][A-Za-z0-9]{0,79}$")
    score_milli: int = Field(ge=0, le=1_000, strict=True)
    voice_action_command_id: UUID | None = None


class CharacterCastPreservedResource(_StrictModel):
    target: CharacterCastTargetResource
    profile_id: UUID
    version_id: UUID
    preset_id: str | None = Field(
        default=None,
        pattern=r"^onnx\.[A-Za-z][A-Za-z0-9]{0,79}$",
    )
    source_type: Literal["preset", "uploaded", "generated"]


class CharacterCastWarningResource(_StrictModel):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,95}$")
    target_key: str | None = Field(
        default=None,
        pattern=r"^(narrator|character:[0-9a-f-]{36})$",
    )
    message: str = Field(min_length=1, max_length=400)


class CharacterCastPlanResource(_StrictModel):
    contract_version: Literal["character-cast-plan/1"] = "character-cast-plan/1"
    command_id: UUID
    novel_id: UUID
    timeline_id: UUID
    mode: Literal["fill_and_deduplicate"] = "fill_and_deduplicate"
    state: CharacterCastPlanState
    server_now: datetime
    progress_current: int = Field(ge=0, strict=True)
    progress_total: int = Field(ge=1, strict=True)
    terminal: bool = Field(strict=True)
    retryable: bool = Field(strict=True)
    current_target_key: str | None = Field(
        default=None,
        pattern=r"^(narrator|character:[0-9a-f-]{36})$",
    )
    lease_expires_at: datetime | None = None
    assignments: list[CharacterCastAssignmentResource]
    preserved: list[CharacterCastPreservedResource]
    warnings: list[CharacterCastWarningResource]
    items: list[CharacterCastPlanItemResource]
    failure_code: str | None = Field(default=None, max_length=96)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None

    @field_validator("failure_code")
    @classmethod
    def validate_cast_failure_code(cls, value: str | None) -> str | None:
        if value is not None and _SAFE_CODE.fullmatch(value) is None:
            raise ValueError("cast failure code must be stable")
        return value

    @model_validator(mode="after")
    def validate_cast_plan_shape(self) -> "CharacterCastPlanResource":
        terminal_states = {
            "ready_applied",
            "ready_applied_with_warnings",
            "ready_unapplied",
            "failed",
            "superseded",
        }
        if self.terminal != (self.state in terminal_states):
            raise ValueError("cast terminal flag drifted from command state")
        if self.progress_current > self.progress_total:
            raise ValueError("cast progress exceeds its target count")
        if self.state == "analyzing" and self.current_target_key is not None:
            if self.lease_expires_at is None:
                raise ValueError("active cast target requires a lease")
        elif self.lease_expires_at is not None:
            raise ValueError("inactive cast plan cannot publish a lease")
        if (self.state == "failed") != (self.failure_code is not None):
            raise ValueError("cast failure evidence drifted from command state")
        if self.terminal and self.completed_at is None:
            raise ValueError("terminal cast plan requires completed_at")
        if not self.terminal and self.completed_at is not None:
            raise ValueError("active cast plan cannot be completed")
        return self


class CharacterCastPlanListResource(_StrictModel):
    contract_version: Literal["character-cast-plan-list/1"] = (
        "character-cast-plan-list/1"
    )
    novel_id: UUID
    server_now: datetime
    items: list[CharacterCastPlanResource]

    @model_validator(mode="after")
    def validate_cast_plan_list_scope(self) -> "CharacterCastPlanListResource":
        if any(item.novel_id != self.novel_id for item in self.items):
            raise ValueError("cast plan list contains another novel")
        if len({item.command_id for item in self.items}) != len(self.items):
            raise ValueError("cast plan list command IDs must be unique")
        return self


class CharacterVoiceMatchResource(_StrictModel):
    contract_version: Literal["character-voice-match/1"] = (
        "character-voice-match/1"
    )
    character_id: UUID
    brief: CharacterVoiceBriefResource
    selected_preset_id: str = Field(
        pattern=r"^onnx\.[A-Za-z][A-Za-z0-9]{0,79}$"
    )
    score_milli: int = Field(ge=0, le=1_000, strict=True)
    state: Literal["ready_applied", "ready_unapplied"]
    selection_still_current: bool = Field(strict=True)
    current_character_binding: CharacterVoiceBindingResource
    model_evidence: dict[str, object]

    @model_validator(mode="after")
    def validate_match_projection(self) -> "CharacterVoiceMatchResource":
        if self.current_character_binding.character_id != self.character_id:
            raise ValueError("character match binding scope drifted")
        if (self.state == "ready_applied") != self.selection_still_current:
            raise ValueError("character match state/current evidence drifted")
        return self


class CreateCharacterVoiceGeneratorCommandRequest(_StrictModel):
    contract_version: Literal["character-voice-generation-request/1"] = (
        "character-voice-generation-request/1"
    )
    timeline_id: UUID | None = None
    character_instance_id: UUID | None = None
    expected_binding_version: int = Field(ge=0, strict=True)
    seed: str | None = Field(default=None, pattern=r"^(0|[1-9][0-9]{0,18})$")

    @field_validator("seed")
    @classmethod
    def validate_seed_bound(cls, value: str | None) -> str | None:
        if value is not None and int(value) > 9_223_372_036_854_775_807:
            raise ValueError("seed exceeds the signed 64-bit VoiceGenerator bound")
        return value


class RetryCharacterVoiceGeneratorCommandRequest(_StrictModel):
    expected_binding_version: int = Field(ge=0, strict=True)


class ApplyCharacterVoiceGeneratorCommandRequest(_StrictModel):
    expected_binding_version: int = Field(ge=0, strict=True)


CharacterVoiceGeneratorState = Literal[
    "queued",
    "analyzing_character",
    "waiting_for_heavy_runtime",
    "generating_voice",
    "unloading_voice_generator",
    "validating_with_nano",
    "ready_applied",
    "ready_unapplied",
    "failed_character_analysis",
    "failed_runtime_unavailable",
    "failed_memory_safety",
    "failed_generation",
    "failed_audio_validation",
    "failed_nano_validation",
    "failed_storage",
    "cancelled",
    "superseded",
]


class CharacterVoiceGeneratorCommandResource(_StrictModel):
    contract_version: Literal["character-voice-generation/1"] = (
        "character-voice-generation/1"
    )
    command_id: UUID
    novel_id: UUID
    character_id: UUID
    draft_id: UUID | None = None
    background_job_id: UUID | None = None
    state: CharacterVoiceGeneratorState
    progress_current: int = Field(ge=0, le=6, strict=True)
    progress_total: Literal[6] = 6
    expected_binding_version: int = Field(ge=0, strict=True)
    applied_binding_version: int | None = Field(default=None, ge=1, strict=True)
    brief: CharacterVoiceBriefResource | None = None
    voice_profile_id: UUID | None = None
    voice_version_id: UUID | None = None
    result_version: VoiceProfileVersionResource | None = None
    current_character_binding: CharacterVoiceBindingResource
    selection_still_current: bool = Field(strict=True)
    cancellable: bool = Field(strict=True)
    retryable: bool = Field(strict=True)
    terminal: bool = Field(strict=True)
    failure_code: str | None = Field(default=None, max_length=96)
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    applied_at: datetime | None = None
    updated_at: datetime

    @field_validator("failure_code")
    @classmethod
    def validate_failure_code(cls, value: str | None) -> str | None:
        if value is not None and _SAFE_CODE.fullmatch(value) is None:
            raise ValueError("VoiceGenerator failure code must be stable")
        return value

    @model_validator(mode="after")
    def validate_command_projection(self) -> "CharacterVoiceGeneratorCommandResource":
        if (
            self.current_character_binding.character_id != self.character_id
            or self.current_character_binding.novel_id != self.novel_id
        ):
            raise ValueError("VoiceGenerator binding scope drifted")
        if (self.voice_profile_id is None) != (self.voice_version_id is None):
            raise ValueError("VoiceGenerator result voice identity is incomplete")
        if self.result_version is not None and (
            self.result_version.profile_id != self.voice_profile_id
            or self.result_version.version_id != self.voice_version_id
        ):
            raise ValueError("VoiceGenerator result version identity drifted")
        active = self.state in {
            "queued",
            "analyzing_character",
            "waiting_for_heavy_runtime",
            "generating_voice",
            "unloading_voice_generator",
            "validating_with_nano",
        }
        failed = self.state.startswith("failed_")
        ready = self.state in {"ready_applied", "ready_unapplied"}
        if self.draft_id is None and self.state not in {
            "queued",
            "analyzing_character",
            "failed_character_analysis",
            "cancelled",
            "superseded",
        }:
            raise ValueError("VoiceGenerator state requires a design draft")
        if self.terminal == active:
            raise ValueError("VoiceGenerator terminal flag drifted")
        if failed != (self.failure_code is not None):
            raise ValueError("VoiceGenerator failure evidence drifted")
        if ready and (
            self.voice_version_id is None
            or self.result_version is None
            or self.completed_at is None
        ):
            raise ValueError("ready VoiceGenerator command lacks its result")
        if self.state == "ready_applied":
            if (
                self.applied_binding_version is None
                or self.applied_at is None
            ):
                raise ValueError("applied VoiceGenerator command lacks CAS evidence")
        elif self.applied_binding_version is not None or self.applied_at is not None:
            raise ValueError("non-applied VoiceGenerator command carries CAS evidence")
        if self.state == "ready_unapplied" and self.selection_still_current:
            raise ValueError("unapplied VoiceGenerator command cannot be current")
        if self.terminal and self.cancellable:
            raise ValueError("terminal VoiceGenerator command cannot be cancelled")
        if self.retryable and not (failed or self.state == "superseded"):
            raise ValueError("only failed or superseded VoiceGenerator commands retry")
        return self


class CharacterVoiceGeneratorCommandListResource(_StrictModel):
    contract_version: Literal["character-voice-generation-list/1"] = (
        "character-voice-generation-list/1"
    )
    novel_id: UUID
    character_id: UUID
    items: list[CharacterVoiceGeneratorCommandResource]

    @model_validator(mode="after")
    def validate_list_scope(self) -> "CharacterVoiceGeneratorCommandListResource":
        if any(
            item.novel_id != self.novel_id or item.character_id != self.character_id
            for item in self.items
        ):
            raise ValueError("VoiceGenerator command list contains another target")
        command_ids = [item.command_id for item in self.items]
        if len(command_ids) != len(set(command_ids)):
            raise ValueError("VoiceGenerator command IDs must be unique")
        return self


class CreatePrivateVoiceDeletionRequest(_StrictModel):
    expected_profile_version: int = Field(ge=1, strict=True)


class ConfirmPrivateVoiceDeletionRequest(_StrictModel):
    expected_profile_version: int = Field(ge=1, strict=True)
    impact_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class PrivateVoiceDeletionImpactResource(_StrictModel):
    schema_version: Literal["private-voice-deletion-impact/2"] = (
        "private-voice-deletion-impact/2"
    )
    profile_id: UUID
    novel_id: UUID
    profile_version: int = Field(ge=1, strict=True)
    voice_version_ids: list[UUID]
    current_narrator_count: int = Field(ge=0, strict=True)
    character_binding_count: int = Field(ge=0, strict=True)
    anonymous_speaker_count: int = Field(ge=0, strict=True)
    generic_slot_count: int = Field(ge=0, strict=True)
    historical_edition_count: int = Field(ge=0, strict=True)
    render_count: int = Field(ge=0, strict=True)
    export_count: int = Field(ge=0, strict=True)
    current_reference_count: int = Field(ge=0, strict=True)
    historical_reference_count: int = Field(ge=0, strict=True)
    reference_count: int = Field(ge=0, strict=True)
    asset_count: int = Field(ge=0, strict=True)
    total_bytes: int = Field(ge=0, strict=True)
    active_job_count: int = Field(ge=0, strict=True)
    external_backup_status: Literal[
        "unmanaged", "managed_pending", "managed_expired"
    ]
    historical_audio_consequence: Literal[
        "unavailable_private_voice_deleted"
    ] | None = None
    impact_summary: str = Field(min_length=1, max_length=800)

    @model_validator(mode="after")
    def validate_totals(self) -> "PrivateVoiceDeletionImpactResource":
        if self.current_reference_count != (
            self.current_narrator_count
            + self.character_binding_count
            + self.anonymous_speaker_count
            + self.generic_slot_count
        ):
            raise ValueError("private voice current-reference total drifted")
        if self.historical_reference_count != (
            self.historical_edition_count + self.render_count + self.export_count
        ):
            raise ValueError("private voice historical-reference total drifted")
        if self.reference_count != (
            self.current_reference_count + self.historical_reference_count
        ):
            raise ValueError("private voice reference total drifted")
        expected_consequence = (
            "unavailable_private_voice_deleted"
            if self.historical_edition_count > 0
            else None
        )
        if self.historical_audio_consequence != expected_consequence:
            raise ValueError("private voice historical consequence drifted")
        if len(set(self.voice_version_ids)) != len(self.voice_version_ids):
            raise ValueError("private voice version ids must be unique")
        return self


class PrivateVoiceDeletionRequestResource(_StrictModel):
    contract_version: Literal["private-voice-deletion/2"] = (
        "private-voice-deletion/2"
    )
    request_id: UUID
    profile_id: UUID
    novel_id: UUID
    command: Literal[
        "discard_unreferenced_private_voice", "true_delete_private_voice"
    ]
    state: Literal[
        "grace_pending",
        "requested",
        "cancelled",
        "live_deleting",
        "live_deleted_backup_pending",
        "completed",
        "failed",
        "superseded",
    ]
    server_now: datetime
    expected_profile_version: int = Field(ge=1, strict=True)
    impact_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    impact: PrivateVoiceDeletionImpactResource
    eligibility: Literal["unreferenced", "referenced", "blocked"]
    reference_count: int = Field(ge=0, strict=True)
    execute_after: datetime | None = None
    impact_expires_at: datetime | None = None
    asset_count: int = Field(ge=0, strict=True)
    total_bytes: int = Field(ge=0, strict=True)
    external_backup_status: Literal[
        "unmanaged", "managed_pending", "managed_expired"
    ]
    confirmed_at: datetime | None = None
    cancelled_at: datetime | None = None
    completed_at: datetime | None = None
    superseded_at: datetime | None = None
    job_drain_started_at: datetime | None = None
    job_drain_deadline: datetime | None = None
    failure_code: str | None = Field(default=None, max_length=96)
    cancellable: bool = Field(strict=True)
    retryable: bool = Field(strict=True)
    terminal: bool = Field(strict=True)

    @model_validator(mode="after")
    def validate_projection(self) -> "PrivateVoiceDeletionRequestResource":
        if (
            self.impact.profile_id != self.profile_id
            or self.impact.novel_id != self.novel_id
            or self.impact.profile_version != self.expected_profile_version
            or self.impact.reference_count != self.reference_count
            or self.impact.asset_count != self.asset_count
            or self.impact.total_bytes != self.total_bytes
            or self.impact.external_backup_status != self.external_backup_status
        ):
            raise ValueError("private voice deletion projection drifted")
        if self.eligibility == "unreferenced" and self.reference_count != 0:
            raise ValueError("unreferenced private voice has references")
        if self.eligibility == "referenced" and self.reference_count == 0:
            raise ValueError("referenced private voice has no references")
        fixed_terminal = self.state in {"cancelled", "completed", "superseded"}
        if fixed_terminal and not self.terminal:
            raise ValueError("private voice deletion terminal flag drifted")
        if self.state != "failed" and not fixed_terminal and self.terminal:
            raise ValueError("active private voice deletion cannot be terminal")
        if self.terminal and (self.cancellable or self.retryable):
            raise ValueError("terminal private voice deletion exposes actions")
        return self


class PrivateVoiceLifecycleProfileResource(_StrictModel):
    profile_id: UUID
    novel_id: UUID
    current_version_id: UUID | None = None
    display_name: str = Field(min_length=1, max_length=240)
    source_type: Literal["uploaded", "generated"]
    profile_version: int = Field(ge=1, strict=True)
    eligibility: Literal["unreferenced", "referenced", "blocked"]
    blocked_reason: str | None = Field(default=None, max_length=160)
    reference_count: int = Field(ge=0, strict=True)
    asset_count: int = Field(ge=0, strict=True)
    total_bytes: int = Field(ge=0, strict=True)
    impact: PrivateVoiceDeletionImpactResource
    impact_summary: str = Field(min_length=1, max_length=800)
    active_request: PrivateVoiceDeletionRequestResource | None = None

    @model_validator(mode="after")
    def validate_projection(self) -> "PrivateVoiceLifecycleProfileResource":
        if (
            self.impact.profile_id != self.profile_id
            or self.impact.novel_id != self.novel_id
            or self.impact.profile_version != self.profile_version
            or self.impact.reference_count != self.reference_count
            or self.impact.asset_count != self.asset_count
            or self.impact.total_bytes != self.total_bytes
            or self.impact.impact_summary != self.impact_summary
        ):
            raise ValueError("private voice lifecycle projection drifted")
        if self.eligibility == "unreferenced" and self.reference_count != 0:
            raise ValueError("unreferenced private voice has references")
        if self.eligibility == "referenced" and self.reference_count == 0:
            raise ValueError("referenced private voice has no references")
        if self.active_request is not None and (
            self.active_request.profile_id != self.profile_id
            or self.active_request.novel_id != self.novel_id
        ):
            raise ValueError("private voice active request scope drifted")
        return self


class PrivateVoiceLifecycleResource(_StrictModel):
    schema_version: Literal["private-voice-lifecycle/1"] = (
        "private-voice-lifecycle/1"
    )
    novel_id: UUID
    server_now: datetime
    items: list[PrivateVoiceLifecycleProfileResource]

    @model_validator(mode="after")
    def validate_lifecycle_scope(self) -> "PrivateVoiceLifecycleResource":
        if any(item.novel_id != self.novel_id for item in self.items):
            raise ValueError("private voice lifecycle contains another novel")
        profile_ids = [item.profile_id for item in self.items]
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError("private voice lifecycle profiles must be unique")
        return self


class CastingSpeakerKind(str, Enum):
    CHARACTER = "character"
    ANONYMOUS = "anonymous"
    GROUP = "group"
    UNKNOWN = "unknown"


class CastingGender(str, Enum):
    FEMALE = "female"
    MALE = "male"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"


class CastingAgeBand(str, Enum):
    CHILD = "child"
    TEEN = "teen"
    YOUNG_ADULT = "young_adult"
    MIDDLE_AGED = "middle_aged"
    ELDERLY = "elderly"
    UNKNOWN = "unknown"


class CastingContextKind(str, Enum):
    DIALOGUE = "dialogue"
    INNER_MONOLOGUE = "inner_monologue"
    LETTER = "letter"
    TELEPHONE = "telephone"
    BROADCAST = "broadcast"
    GROUP = "group"


class VoiceCastingCondition(_StrictModel):
    speaker_kinds: list[CastingSpeakerKind] = Field(max_length=4)
    genders: list[CastingGender] = Field(max_length=4)
    age_bands: list[CastingAgeBand] = Field(max_length=6)
    context_kinds: list[CastingContextKind] = Field(max_length=6)
    role_tags: list[str] = Field(max_length=32)

    @model_validator(mode="after")
    def validate_condition(self) -> "VoiceCastingCondition":
        collections = (
            self.speaker_kinds,
            self.genders,
            self.age_bands,
            self.context_kinds,
            self.role_tags,
        )
        if not any(collections):
            raise ValueError("casting condition must constrain at least one field")
        if any(len(value) != len(set(value)) for value in collections):
            raise ValueError("casting condition values must be unique")
        if any(not tag.strip() or len(tag) > 80 for tag in self.role_tags):
            raise ValueError("casting role tags must be non-empty and bounded")
        return self


class VoiceCastingTargetKind(str, Enum):
    GENERIC_SLOT = "generic_slot"
    VOICE_VERSION = "voice_version"
    REQUIRE_REVIEW = "require_review"


class VoiceCastingTarget(_StrictModel):
    kind: VoiceCastingTargetKind
    pool_id: UUID | None
    slot_key: str | None = Field(max_length=80)
    profile_id: UUID | None
    version_id: UUID | None

    @model_validator(mode="after")
    def validate_target(self) -> "VoiceCastingTarget":
        generic_complete = self.pool_id is not None and self.slot_key is not None
        voice_complete = self.profile_id is not None and self.version_id is not None
        if (self.pool_id is None) != (self.slot_key is None):
            raise ValueError("generic casting target requires pool_id and slot_key")
        if (self.profile_id is None) != (self.version_id is None):
            raise ValueError("voice casting target requires profile_id and version_id")
        if self.kind is VoiceCastingTargetKind.GENERIC_SLOT:
            if not generic_complete or voice_complete:
                raise ValueError("generic_slot target has an invalid shape")
        elif self.kind is VoiceCastingTargetKind.VOICE_VERSION:
            if generic_complete or not voice_complete:
                raise ValueError("voice_version target has an invalid shape")
        elif generic_complete or voice_complete:
            raise ValueError("require_review target cannot carry a voice")
        return self


class VoiceCastingRuleInput(_StrictModel):
    priority: int = Field(ge=-10_000, le=10_000, strict=True)
    enabled: bool = Field(strict=True)
    condition: VoiceCastingCondition
    target: VoiceCastingTarget


class VoiceCastingRuleResource(VoiceCastingRuleInput):
    rule_id: UUID
    version_number: int = Field(ge=1, strict=True)
    source: Literal["system", "user"]


class VoiceCastingRulesResource(_StrictModel):
    contract_version: Literal["narration-settings-api/1"] = (
        NARRATION_SETTINGS_API_VERSION
    )
    novel_id: UUID
    version: int = Field(ge=0, strict=True)
    items: list[VoiceCastingRuleResource]

    @model_validator(mode="after")
    def validate_rules(self) -> "VoiceCastingRulesResource":
        if len({item.rule_id for item in self.items}) != len(self.items):
            raise ValueError("casting rule ids must be unique")
        if len({item.priority for item in self.items}) != len(self.items):
            raise ValueError("casting rule priorities must be unique")
        if not self.items and self.version != 0:
            raise ValueError("empty casting rule set is version zero")
        if self.items and self.version < 1:
            raise ValueError("persisted casting rules require a positive version")
        return self


class VoiceSourceAvailability(_StrictModel):
    source_type: VoiceSourceType
    capability: CapabilityKey
    available: bool = Field(strict=True)
    reason_code: str | None = Field(default=None, max_length=96)
    accepted_mime_types: list[str] = Field(default_factory=list)
    maximum_bytes: int | None = Field(default=None, ge=1, strict=True)

    @field_validator("reason_code")
    @classmethod
    def validate_reason_code(cls, value: str | None) -> str | None:
        if value is not None and not _SAFE_CODE.fullmatch(value):
            raise ValueError("voice source reason must be a stable code")
        return value

    @model_validator(mode="after")
    def validate_availability(self) -> "VoiceSourceAvailability":
        expected_capability = {
            VoiceSourceType.PRESET: CapabilityKey.PRESET_VOICE_SOURCE,
            VoiceSourceType.UPLOADED: CapabilityKey.REFERENCE_CLONE,
            VoiceSourceType.GENERATED: CapabilityKey.VOICE_GENERATOR,
        }[self.source_type]
        if self.capability is not expected_capability:
            raise ValueError("voice source must use its frozen capability key")
        if self.available == (self.reason_code is not None):
            raise ValueError("available source has no reason; unavailable source requires one")
        if self.source_type is VoiceSourceType.UPLOADED:
            if (
                tuple(self.accepted_mime_types) != REFERENCE_UPLOAD_MIME_TYPES
                or self.maximum_bytes != REFERENCE_UPLOAD_MAX_BYTES
            ):
                raise ValueError("uploaded source must publish the frozen upload limits")
        elif self.accepted_mime_types or self.maximum_bytes is not None:
            raise ValueError("only uploaded source publishes media limits")
        return self


class GenericVoicePoolState(str, Enum):
    DISABLED = "disabled"
    MISSING = "missing"
    INCOMPLETE = "incomplete"
    READY = "ready"


class GenericVoiceSlotState(str, Enum):
    MISSING = "missing"
    UNAVAILABLE = "unavailable"
    READY = "ready"


class GenericVoiceSlotResource(_StrictModel):
    slot_key: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=80)
    state: GenericVoiceSlotState
    voice_version_id: UUID | None = None
    enabled: bool = Field(strict=True)
    priority: int = Field(ge=-10_000, le=10_000, strict=True)
    reason_code: str | None = Field(default=None, max_length=96)

    @field_validator("reason_code")
    @classmethod
    def validate_reason_code(cls, value: str | None) -> str | None:
        if value is not None and not _SAFE_CODE.fullmatch(value):
            raise ValueError("generic voice slot reason must be a stable code")
        return value

    @model_validator(mode="after")
    def validate_slot(self) -> "GenericVoiceSlotResource":
        if self.state is GenericVoiceSlotState.READY:
            if (
                self.voice_version_id is None
                or self.reason_code is not None
                or not self.enabled
            ):
                raise ValueError("ready slot requires an enabled voice and no reason")
        elif self.voice_version_id is not None or self.reason_code is None or self.enabled:
            raise ValueError("non-ready slot is disabled, voice-less, and reasoned")
        return self


class GenericVoicePoolResource(_StrictModel):
    contract_version: Literal["narration-settings-api/1"] = (
        NARRATION_SETTINGS_API_VERSION
    )
    novel_id: UUID
    pool_id: UUID | None = None
    state: GenericVoicePoolState
    version: int = Field(ge=0, strict=True)
    required_slot_count: Literal[24] = 24
    ready_slot_count: int = Field(ge=0, le=24, strict=True)
    rights_approved_slot_count: int = Field(ge=0, le=24, strict=True)
    quality_approved_slot_count: int = Field(ge=0, le=24, strict=True)
    production_ready_slot_count: int = Field(ge=0, le=24, strict=True)
    slots: list[GenericVoiceSlotResource]
    reason_codes: list[str] = Field(max_length=32)

    @field_validator("reason_codes")
    @classmethod
    def validate_reason_codes(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("generic voice pool reason codes must be unique")
        if any(not _SAFE_CODE.fullmatch(value) for value in values):
            raise ValueError("generic voice pool reason codes must be stable codes")
        return values

    @model_validator(mode="after")
    def validate_pool(self) -> "GenericVoicePoolResource":
        if len({item.slot_key for item in self.slots}) != len(self.slots):
            raise ValueError("generic voice slot keys must be unique")
        if self.ready_slot_count != sum(
            item.state is GenericVoiceSlotState.READY for item in self.slots
        ):
            raise ValueError("ready_slot_count must match slots")
        if self.pool_id is None and self.version != 0:
            raise ValueError("missing pool identity requires version zero")
        if self.pool_id is not None and self.version < 1:
            raise ValueError("persisted pool requires a positive version")
        if self.production_ready_slot_count > min(
            self.ready_slot_count,
            self.rights_approved_slot_count,
            self.quality_approved_slot_count,
        ):
            raise ValueError("production-ready count cannot exceed its prerequisites")
        if self.state is GenericVoicePoolState.READY:
            if (
                self.pool_id is None
                or self.version < 1
                or len(self.slots) != 24
                or min(
                    self.ready_slot_count,
                    self.rights_approved_slot_count,
                    self.quality_approved_slot_count,
                    self.production_ready_slot_count,
                )
                != 24
                or self.reason_codes
            ):
                raise ValueError("ready pool requires 24 fully approved slots")
        elif not self.reason_codes:
            raise ValueError("non-ready pool requires at least one stable reason")
        elif self.state is GenericVoicePoolState.MISSING:
            if (
                self.pool_id is not None
                or self.version != 0
                or self.ready_slot_count != 0
                or self.rights_approved_slot_count != 0
                or self.quality_approved_slot_count != 0
                or self.production_ready_slot_count != 0
            ):
                raise ValueError("missing pool cannot claim any ready or approved slot")
        elif self.state is GenericVoicePoolState.DISABLED:
            if self.production_ready_slot_count != 0:
                raise ValueError("disabled pool cannot claim production-ready slots")
        elif (
            self.pool_id is None
            or self.version < 1
            or len(self.slots) != 24
            or self.production_ready_slot_count >= 24
        ):
            raise ValueError("incomplete pool requires 24 persisted but non-production-ready slots")
        return self


class PronunciationAction(str, Enum):
    REPLACE = "replace"
    SKIP = "skip"


class PronunciationEntryResource(_StrictModel):
    entry_id: UUID | None = None
    source_text: str = Field(min_length=1, max_length=160)
    action: PronunciationAction
    spoken_text: str | None = Field(default=None, max_length=240)
    language: str = Field(default="zh-CN", min_length=2, max_length=40)
    scope_kind: Literal["novel", "volume", "chapter"] = "novel"
    scope_id: UUID
    priority: int = Field(default=0, ge=-10_000, le=10_000, strict=True)

    @model_validator(mode="after")
    def validate_pronunciation(self) -> "PronunciationEntryResource":
        if self.action is PronunciationAction.REPLACE:
            if self.spoken_text is None or not self.spoken_text.strip():
                raise ValueError("replace pronunciation requires spoken_text")
        elif self.spoken_text is not None:
            raise ValueError("skip pronunciation cannot carry spoken_text")
        if not _LANGUAGE.fullmatch(self.language):
            raise ValueError("language must be a conservative BCP-47 tag")
        return self


class PronunciationProfileResource(_StrictModel):
    contract_version: Literal["narration-settings-api/1"] = (
        NARRATION_SETTINGS_API_VERSION
    )
    novel_id: UUID
    profile_id: UUID | None = None
    version: int = Field(ge=0, strict=True)
    fingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    entries: list[PronunciationEntryResource]

    @model_validator(mode="after")
    def validate_profile(self) -> "PronunciationProfileResource":
        if self.profile_id is None:
            if self.version != 0 or self.fingerprint is not None or self.entries:
                raise ValueError("missing pronunciation profile is empty version zero")
        elif self.version < 1 or self.fingerprint is None:
            raise ValueError("persisted pronunciation profile requires version/fingerprint")
        return self


class PutPronunciationProfileRequest(_StrictModel):
    expected_version: int = Field(ge=0, strict=True)
    entries: list[PronunciationEntryResource] = Field(max_length=2_000)

    @model_validator(mode="after")
    def reject_client_entry_ids(self) -> "PutPronunciationProfileRequest":
        if any(item.entry_id is not None for item in self.entries):
            raise ValueError("replacement request cannot choose server entry ids")
        return self


class NarrationCacheStatus(_StrictModel):
    contract_version: Literal["narration-settings-api/1"] = (
        NARRATION_SETTINGS_API_VERSION
    )
    schema_version: Literal["narration-cache/1"] = NARRATION_CACHE_SCHEMA_VERSION
    novel_id: UUID
    snapshot_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_asset_bytes: int = Field(ge=0, strict=True)
    locked_voice_bytes: int = Field(ge=0, strict=True)
    referenced_edition_bytes: int = Field(ge=0, strict=True)
    derived_cache_bytes: int = Field(ge=0, strict=True)
    reclaimable_bytes: int = Field(ge=0, strict=True)
    pending_job_count: int = Field(ge=0, strict=True)
    disk_free_bytes: int = Field(ge=0, strict=True)
    disk_total_bytes: int = Field(ge=1, strict=True)
    cleanup_capability: FeatureCapability

    @model_validator(mode="after")
    def validate_cache(self) -> "NarrationCacheStatus":
        if self.reclaimable_bytes > self.derived_cache_bytes:
            raise ValueError("reclaimable bytes cannot exceed derived cache")
        if self.disk_free_bytes > self.disk_total_bytes:
            raise ValueError("disk free bytes cannot exceed total bytes")
        if self.cleanup_capability.key is not CapabilityKey.CACHE_CLEANUP:
            raise ValueError("cleanup_capability must describe cache_cleanup")
        return self


class PreviewNarrationCacheCleanupRequest(_StrictModel):
    snapshot_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


class NarrationCacheCleanupPreview(_StrictModel):
    contract_version: Literal["narration-settings-api/1"] = (
        NARRATION_SETTINGS_API_VERSION
    )
    novel_id: UUID
    snapshot_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    cleanup_token: str = Field(min_length=32, max_length=256)
    expires_at: datetime
    reclaimable_bytes: int = Field(ge=0, strict=True)
    protected_asset_count: int = Field(ge=0, strict=True)
    candidate_asset_count: int = Field(ge=0, strict=True)


class ExecuteNarrationCacheCleanupRequest(_StrictModel):
    snapshot_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    cleanup_token: str = Field(min_length=32, max_length=256)
    confirmed: bool = Field(strict=True)

    @model_validator(mode="after")
    def require_confirmation(self) -> "ExecuteNarrationCacheCleanupRequest":
        if not self.confirmed:
            raise ValueError("cache cleanup must be explicitly confirmed")
        return self


class NarrationCacheCleanupResult(_StrictModel):
    contract_version: Literal["narration-settings-api/1"] = (
        NARRATION_SETTINGS_API_VERSION
    )
    novel_id: UUID
    deleted_asset_count: int = Field(ge=0, strict=True)
    reclaimed_bytes: int = Field(ge=0, strict=True)
    source_asset_deleted_count: Literal[0] = 0
    locked_voice_deleted_count: Literal[0] = 0
    referenced_asset_deleted_count: Literal[0] = 0


class NarrationCoverageSummary(_StrictModel):
    character_count: int = Field(ge=0, strict=True)
    configured_character_count: int = Field(ge=0, strict=True)
    locked_character_voice_count: int = Field(ge=0, strict=True)
    generic_required_slot_count: Literal[24] = 24
    generic_ready_slot_count: int = Field(ge=0, le=24, strict=True)
    pending_review_script_count: int = Field(ge=0, strict=True)
    blocker_count: int = Field(ge=0, strict=True)
    warning_count: int = Field(ge=0, strict=True)
    generated_chapter_count: int = Field(ge=0, strict=True)
    failed_job_count: int = Field(ge=0, strict=True)

    @model_validator(mode="after")
    def validate_coverage(self) -> "NarrationCoverageSummary":
        if self.configured_character_count > self.character_count:
            raise ValueError("configured characters cannot exceed all characters")
        if self.locked_character_voice_count > self.configured_character_count:
            raise ValueError("locked character voices cannot exceed configured characters")
        return self


class NarrationOverviewResponse(_StrictModel):
    contract_version: Literal["narration-settings-api/1"] = (
        NARRATION_SETTINGS_API_VERSION
    )
    novel_id: UUID
    capabilities: NarrationCapabilities
    authorization: NarrationAuthorizationState
    runtime: NarrationRuntimeStatus
    settings: NarrationSettingsResource
    coverage: NarrationCoverageSummary
    voice_sources: list[VoiceSourceAvailability]
    cache: NarrationCacheStatus

    @model_validator(mode="after")
    def validate_overview_scope(self) -> "NarrationOverviewResponse":
        if self.settings.novel_id != self.novel_id or self.cache.novel_id != self.novel_id:
            raise ValueError("overview child resources must belong to the same novel")
        sources = [item.source_type for item in self.voice_sources]
        if len(sources) != len(set(sources)) or set(sources) != set(VoiceSourceType):
            raise ValueError("overview must report every voice source exactly once")
        for source in self.voice_sources:
            capability = self.capabilities.item(source.capability)
            capability_available = (
                capability.state is CapabilityState.ENABLED and capability.actionable
            )
            if source.available != capability_available:
                raise ValueError("voice source availability must match its capability")
            if not source.available and source.reason_code != capability.reason_code:
                raise ValueError("unavailable voice source must expose the capability reason")
        if self.runtime.product_visible and any(
            (capability := self.capabilities.item(key)).state
            is not CapabilityState.ENABLED
            or not capability.visible
            or not capability.actionable
            for key in T4_PRODUCT_CAPABILITY_KEYS
        ):
            raise ValueError(
                "runtime cannot be product-visible while the T4 product chain is gated"
            )
        global_cleanup = self.capabilities.item(CapabilityKey.CACHE_CLEANUP)
        nested_cleanup = self.cache.cleanup_capability
        restrictiveness = {
            CapabilityState.DISABLED: 0,
            CapabilityState.UNAVAILABLE: 1,
            CapabilityState.HOLD: 2,
            CapabilityState.ENABLED: 3,
        }
        if restrictiveness[nested_cleanup.state] > restrictiveness[global_cleanup.state]:
            raise ValueError("cache cleanup capability cannot exceed the global gate")
        if (
            nested_cleanup.state is global_cleanup.state
            and nested_cleanup.reason_code != global_cleanup.reason_code
        ):
            raise ValueError("equivalent cache cleanup gates must expose one reason")
        return self
