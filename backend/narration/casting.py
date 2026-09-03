"""Deterministic, fail-closed narration casting for T3-F.

The resolver consumes server-validated snapshots.  It never queries the ORM,
persists state, calls a model, or synthesizes audio.  T3-A deliberately keeps
``voice_version_id`` out of ``CastingDecision``; ``ResolvedVoiceSnapshot`` is
therefore transient Edition input and is not a second script contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import re
import unicodedata
from typing import Final, Iterable
from uuid import NAMESPACE_URL, RFC_4122, UUID, uuid5

from . import schemas as wire
from .contracts import issue_severity
from .fingerprints import canonical_json_bytes
from .script_contracts import (
    CastingDecision,
    CastingDecisionOrigin,
    CastingRuleAuthorityRecord,
    CastingTargetKind,
    CastingTargetRef,
    ScriptIssueContract,
    SegmentKind,
    SpeakerKind,
    SpeakerRef,
    speaker_target_hash,
)


CASTING_RESOLVER_VERSION: Final = "narration-casting-resolver/1"
GENERIC_ASSIGNMENT_VERSION: Final = "narration-generic-assignment/1"
GENERIC_POOL_REQUIRED_SLOT_COUNT: Final = 24
AUTOMATIC_GENERIC_CASTING_RULE_NAMESPACE: Final = uuid5(
    NAMESPACE_URL,
    "app://ai-novel-world-2026/narration/generic-casting-rule/v1",
)

_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_SLOT_KEY = re.compile(r"^[a-z][a-z0-9_]{0,79}$")


class CastingInputError(ValueError):
    """Raised when server authority snapshots are internally inconsistent."""


class CastingScopeKind(str, Enum):
    NOVEL = "novel"
    VOLUME = "volume"
    CHAPTER = "chapter"


class CastingRuleAction(str, Enum):
    VOICE_VERSION = "voice_version"
    GENERIC_SLOT = "generic_slot"
    REQUIRE_REVIEW = "require_review"
    AUTOMATIC_POOL = "automatic_pool"


class CastingResolutionSource(str, Enum):
    NOT_APPLICABLE = "not_applicable"
    UNRESOLVED = "unresolved"
    CHAPTER_NARRATOR = "chapter_narrator"
    VOLUME_NARRATOR = "volume_narrator"
    NOVEL_NARRATOR = "novel_narrator"
    EXPLICIT_RULE = "explicit_rule"
    CHARACTER_DEDICATED = "character_dedicated"
    CHARACTER_INHERITED = "character_inherited"
    ANONYMOUS_BINDING = "anonymous_binding"
    GENERIC_RULE = "generic_rule"


def automatic_generic_casting_rule_id(
    *, novel_id: UUID, pool_id: UUID, pool_version: int
) -> UUID:
    """Rebuild the identity of the server-owned automatic pool rule."""

    _require_uuid(novel_id, field_name="automatic rule novel_id")
    _require_uuid(pool_id, field_name="automatic rule pool_id")
    _require_positive_int(pool_version, field_name="automatic rule pool_version")
    return uuid5(
        AUTOMATIC_GENERIC_CASTING_RULE_NAMESPACE,
        f"{novel_id}:{pool_id}:{pool_version}",
    )


def _require_uuid(value: object, *, field_name: str) -> UUID:
    if (
        type(value) is not UUID
        or value.variant != RFC_4122
        or value.version not in {4, 5}
    ):
        raise CastingInputError(f"{field_name} must be a canonical UUIDv4/v5")
    return value


def _require_optional_uuid(value: object, *, field_name: str) -> UUID | None:
    if value is None:
        return None
    return _require_uuid(value, field_name=field_name)


def _require_positive_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise CastingInputError(f"{field_name} must be a positive integer")
    return value


def _require_bounded_int(
    value: object, *, field_name: str, minimum: int, maximum: int
) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise CastingInputError(
            f"{field_name} must be an integer in [{minimum}, {maximum}]"
        )
    return value


def _require_sha256(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise CastingInputError(f"{field_name} must be lowercase SHA-256")
    return value


def _require_exact_bool(value: object, *, field_name: str) -> bool:
    if type(value) is not bool:
        raise CastingInputError(f"{field_name} must be an exact boolean")
    return value


def _normalized_tag(value: object, *, field_name: str) -> str:
    if type(value) is not str:
        raise CastingInputError(f"{field_name} must be text")
    normalized = unicodedata.normalize("NFC", value.strip()).casefold()
    if not normalized or len(normalized) > 80:
        raise CastingInputError(f"{field_name} must be bounded non-empty text")
    return normalized


def _normalized_tags(values: object, *, field_name: str) -> frozenset[str]:
    if type(values) not in {tuple, frozenset}:
        raise CastingInputError(f"{field_name} must be an immutable collection")
    normalized = frozenset(
        _normalized_tag(value, field_name=f"{field_name} item") for value in values
    )
    if len(normalized) != len(values) or len(normalized) > 32:
        raise CastingInputError(f"{field_name} must contain at most 32 unique tags")
    return normalized


def _require_enum_tuple(
    values: object, enum_type: type[Enum], *, field_name: str, maximum: int
) -> tuple[Enum, ...]:
    if type(values) is not tuple:
        raise CastingInputError(f"{field_name} must be a tuple")
    if len(values) > maximum or len(values) != len(set(values)):
        raise CastingInputError(f"{field_name} must contain unique bounded values")
    if any(type(value) is not enum_type for value in values):
        raise CastingInputError(f"{field_name} contains an unknown enum")
    return values


@dataclass(frozen=True, slots=True)
class VoiceVersionSnapshot:
    """Current server evidence for one immutable voice version."""

    profile_id: UUID
    version_id: UUID
    version_number: int
    fingerprint: str
    profile_novel_id: UUID | None
    profile_status: wire.VoiceProfileStatus
    source_type: wire.VoiceSourceType
    version_state: wire.VoiceVersionState
    quality_state: wire.VoiceQualityState
    activation_evidence_usable: bool
    rights_record_id: UUID | None
    rights_state: wire.VoiceRightsState | None
    voice_cloning_permitted: bool

    def __post_init__(self) -> None:
        _require_uuid(self.profile_id, field_name="voice profile_id")
        _require_uuid(self.version_id, field_name="voice version_id")
        _require_positive_int(self.version_number, field_name="voice version_number")
        _require_sha256(self.fingerprint, field_name="voice fingerprint")
        _require_optional_uuid(
            self.profile_novel_id, field_name="voice profile_novel_id"
        )
        if type(self.profile_status) is not wire.VoiceProfileStatus:
            raise CastingInputError("voice profile_status is unsupported")
        if type(self.source_type) is not wire.VoiceSourceType:
            raise CastingInputError("voice source_type is unsupported")
        if type(self.version_state) is not wire.VoiceVersionState:
            raise CastingInputError("voice version_state is unsupported")
        if type(self.quality_state) is not wire.VoiceQualityState:
            raise CastingInputError("voice quality_state is unsupported")
        _require_exact_bool(
            self.activation_evidence_usable,
            field_name="activation_evidence_usable",
        )
        _require_optional_uuid(
            self.rights_record_id, field_name="voice rights_record_id"
        )
        if self.rights_state is not None and type(
            self.rights_state
        ) is not wire.VoiceRightsState:
            raise CastingInputError("voice rights_state is unsupported")
        _require_exact_bool(
            self.voice_cloning_permitted,
            field_name="voice_cloning_permitted",
        )

    def blocker_codes(self, *, novel_id: UUID) -> frozenset[str]:
        _require_uuid(novel_id, field_name="voice use novel_id")
        blockers: set[str] = set()
        if (
            self.profile_novel_id not in {None, novel_id}
            or self.profile_status is not wire.VoiceProfileStatus.ACTIVE
            or self.version_state is not wire.VoiceVersionState.LOCKED
            or not self.activation_evidence_usable
        ):
            blockers.add("B_VOICE_VERSION_UNAVAILABLE")
        if (
            self.rights_record_id is None
            or self.rights_state is not wire.VoiceRightsState.ACTIVE
            or (
                self.source_type is wire.VoiceSourceType.UPLOADED
                and not self.voice_cloning_permitted
            )
        ):
            blockers.add("B_VOICE_RIGHTS_UNAVAILABLE")
        return frozenset(blockers)


@dataclass(frozen=True, slots=True)
class NarratorSelectionSnapshot:
    novel_id: UUID
    scope_kind: CastingScopeKind
    scope_id: UUID
    profile_id: UUID
    version_id: UUID
    voice: VoiceVersionSnapshot | None

    def __post_init__(self) -> None:
        _require_uuid(self.novel_id, field_name="narrator novel_id")
        if type(self.scope_kind) is not CastingScopeKind:
            raise CastingInputError("narrator scope_kind is unsupported")
        _require_uuid(self.scope_id, field_name="narrator scope_id")
        if self.scope_kind is CastingScopeKind.NOVEL and self.scope_id != self.novel_id:
            raise CastingInputError("novel narrator scope_id must equal novel_id")
        _require_uuid(self.profile_id, field_name="narrator profile_id")
        _require_uuid(self.version_id, field_name="narrator version_id")
        if self.voice is not None:
            if type(self.voice) is not VoiceVersionSnapshot:
                raise CastingInputError("narrator voice must be VoiceVersionSnapshot")
            if (
                self.voice.profile_id != self.profile_id
                or self.voice.version_id != self.version_id
            ):
                raise CastingInputError(
                    "narrator profile/version relation differs from voice snapshot"
                )


@dataclass(frozen=True, slots=True)
class CharacterBindingSnapshot:
    novel_id: UUID
    binding_id: UUID
    character_id: UUID
    policy: wire.CharacterVoiceBindingPolicy
    profile_id: UUID
    version_id: UUID
    voice: VoiceVersionSnapshot | None

    def __post_init__(self) -> None:
        _require_uuid(self.novel_id, field_name="character binding novel_id")
        _require_uuid(self.binding_id, field_name="character binding_id")
        _require_uuid(self.character_id, field_name="character binding character_id")
        if self.policy not in {
            wire.CharacterVoiceBindingPolicy.DEDICATED,
            wire.CharacterVoiceBindingPolicy.INHERITED,
        } or type(self.policy) is not wire.CharacterVoiceBindingPolicy:
            raise CastingInputError("character binding must be dedicated or inherited")
        _require_uuid(self.profile_id, field_name="character binding profile_id")
        _require_uuid(self.version_id, field_name="character binding version_id")
        if self.voice is not None:
            if type(self.voice) is not VoiceVersionSnapshot:
                raise CastingInputError("character binding voice has an invalid type")
            if (
                self.voice.profile_id != self.profile_id
                or self.voice.version_id != self.version_id
            ):
                raise CastingInputError(
                    "character binding profile/version relation is inconsistent"
                )


@dataclass(frozen=True, slots=True)
class GenericSlotSnapshot:
    pool_id: UUID
    slot_id: UUID
    slot_key: str
    position: int
    enabled: bool
    state: wire.GenericVoiceSlotState
    rights_approved: bool
    quality_approved: bool
    production_ready: bool
    voice: VoiceVersionSnapshot | None
    speaker_kinds: tuple[wire.CastingSpeakerKind, ...] = ()
    genders: tuple[wire.CastingGender, ...] = ()
    age_bands: tuple[wire.CastingAgeBand, ...] = ()
    context_kinds: tuple[wire.CastingContextKind, ...] = ()
    role_tags: frozenset[str] = frozenset()
    neutral_fallback: bool = False

    def __post_init__(self) -> None:
        _require_uuid(self.pool_id, field_name="generic slot pool_id")
        _require_uuid(self.slot_id, field_name="generic slot_id")
        if type(self.slot_key) is not str or _SLOT_KEY.fullmatch(self.slot_key) is None:
            raise CastingInputError("generic slot_key is not canonical")
        _require_bounded_int(
            self.position,
            field_name="generic slot position",
            minimum=0,
            maximum=GENERIC_POOL_REQUIRED_SLOT_COUNT - 1,
        )
        _require_exact_bool(self.enabled, field_name="generic slot enabled")
        if type(self.state) is not wire.GenericVoiceSlotState:
            raise CastingInputError("generic slot state is unsupported")
        for field_name, value in (
            ("rights_approved", self.rights_approved),
            ("quality_approved", self.quality_approved),
            ("production_ready", self.production_ready),
            ("neutral_fallback", self.neutral_fallback),
        ):
            _require_exact_bool(value, field_name=f"generic slot {field_name}")
        if self.voice is not None and type(self.voice) is not VoiceVersionSnapshot:
            raise CastingInputError("generic slot voice has an invalid type")
        _require_enum_tuple(
            self.speaker_kinds,
            wire.CastingSpeakerKind,
            field_name="generic slot speaker_kinds",
            maximum=3,
        )
        _require_enum_tuple(
            self.genders,
            wire.CastingGender,
            field_name="generic slot genders",
            maximum=4,
        )
        _require_enum_tuple(
            self.age_bands,
            wire.CastingAgeBand,
            field_name="generic slot age_bands",
            maximum=6,
        )
        _require_enum_tuple(
            self.context_kinds,
            wire.CastingContextKind,
            field_name="generic slot context_kinds",
            maximum=6,
        )
        normalized = _normalized_tags(self.role_tags, field_name="generic slot role_tags")
        if normalized != self.role_tags:
            raise CastingInputError("generic slot role_tags must be normalized")
        ready_shape = (
            self.enabled
            and self.state is wire.GenericVoiceSlotState.READY
            and self.rights_approved
            and self.quality_approved
            and self.production_ready
            and self.voice is not None
        )
        if self.state is wire.GenericVoiceSlotState.READY and not ready_shape:
            raise CastingInputError(
                "ready generic slot requires enabled approved production voice evidence"
            )
        if self.state is not wire.GenericVoiceSlotState.READY and (
            self.enabled
            or self.rights_approved
            or self.quality_approved
            or self.production_ready
        ):
            raise CastingInputError(
                "non-ready generic slot cannot claim enabled or approval evidence"
            )

    def is_production_ready(self, *, novel_id: UUID) -> bool:
        return bool(
            self.enabled
            and self.state is wire.GenericVoiceSlotState.READY
            and self.rights_approved
            and self.quality_approved
            and self.production_ready
            and self.voice is not None
            and not self.voice.blocker_codes(novel_id=novel_id)
        )


@dataclass(frozen=True, slots=True)
class GenericPoolSnapshot:
    novel_id: UUID
    pool_id: UUID | None
    version: int
    state: wire.GenericVoicePoolState
    ready_slot_count: int
    rights_approved_slot_count: int
    quality_approved_slot_count: int
    production_ready_slot_count: int
    slots: tuple[GenericSlotSnapshot, ...]

    def __post_init__(self) -> None:
        _require_uuid(self.novel_id, field_name="generic pool novel_id")
        _require_optional_uuid(self.pool_id, field_name="generic pool_id")
        _require_bounded_int(
            self.version,
            field_name="generic pool version",
            minimum=0,
            maximum=2_147_483_647,
        )
        if self.pool_id is None and self.version != 0:
            raise CastingInputError("missing generic pool identity must be version zero")
        if self.pool_id is not None and self.version < 1:
            raise CastingInputError("persisted generic pool requires a positive version")
        if type(self.state) is not wire.GenericVoicePoolState:
            raise CastingInputError("generic pool state is unsupported")
        for field_name, value in (
            ("ready_slot_count", self.ready_slot_count),
            ("rights_approved_slot_count", self.rights_approved_slot_count),
            ("quality_approved_slot_count", self.quality_approved_slot_count),
            ("production_ready_slot_count", self.production_ready_slot_count),
        ):
            _require_bounded_int(
                value,
                field_name=f"generic pool {field_name}",
                minimum=0,
                maximum=GENERIC_POOL_REQUIRED_SLOT_COUNT,
            )
        if type(self.slots) is not tuple or not all(
            type(slot) is GenericSlotSnapshot for slot in self.slots
        ):
            raise CastingInputError("generic pool slots must be a tuple of snapshots")
        if self.pool_id is not None and any(
            slot.pool_id != self.pool_id for slot in self.slots
        ):
            raise CastingInputError("generic slot belongs to another pool")
        for values, label in (
            ([slot.slot_id for slot in self.slots], "slot ids"),
            ([slot.slot_key for slot in self.slots], "slot keys"),
            ([slot.position for slot in self.slots], "slot positions"),
        ):
            if len(values) != len(set(values)):
                raise CastingInputError(f"generic pool contains duplicate {label}")
        if self.ready_slot_count != sum(
            slot.state is wire.GenericVoiceSlotState.READY for slot in self.slots
        ):
            raise CastingInputError("generic pool ready count differs from slots")
        for actual, expected, label in (
            (
                self.rights_approved_slot_count,
                sum(slot.rights_approved for slot in self.slots),
                "rights-approved",
            ),
            (
                self.quality_approved_slot_count,
                sum(slot.quality_approved for slot in self.slots),
                "quality-approved",
            ),
            (
                self.production_ready_slot_count,
                sum(slot.production_ready for slot in self.slots),
                "production-ready",
            ),
        ):
            if actual != expected:
                raise CastingInputError(
                    f"generic pool {label} count differs from slots"
                )
        if self.state is wire.GenericVoicePoolState.READY and (
            self.pool_id is None
            or self.version < 1
            or len(self.slots) != GENERIC_POOL_REQUIRED_SLOT_COUNT
            or set(slot.position for slot in self.slots)
            != set(range(GENERIC_POOL_REQUIRED_SLOT_COUNT))
            or min(
                self.ready_slot_count,
                self.rights_approved_slot_count,
                self.quality_approved_slot_count,
                self.production_ready_slot_count,
            )
            != GENERIC_POOL_REQUIRED_SLOT_COUNT
        ):
            raise CastingInputError(
                "ready generic pool requires one complete approved 24-slot pack"
            )
        if self.state is wire.GenericVoicePoolState.MISSING and (
            self.pool_id is not None
            or self.version != 0
            or self.slots
            or max(
                self.ready_slot_count,
                self.rights_approved_slot_count,
                self.quality_approved_slot_count,
                self.production_ready_slot_count,
            )
            != 0
        ):
            raise CastingInputError("missing generic pool cannot claim persisted evidence")
        if self.state is wire.GenericVoicePoolState.DISABLED and (
            self.pool_id is None
            or self.version < 1
            or self.production_ready_slot_count != 0
        ):
            raise CastingInputError(
                "disabled generic pool requires identity and zero production-ready slots"
            )
        if self.state is wire.GenericVoicePoolState.INCOMPLETE and (
            self.pool_id is None
            or self.version < 1
            or len(self.slots) != GENERIC_POOL_REQUIRED_SLOT_COUNT
            or self.production_ready_slot_count >= GENERIC_POOL_REQUIRED_SLOT_COUNT
        ):
            raise CastingInputError(
                "incomplete generic pool requires 24 persisted non-ready slots"
            )

    def ready_for_automatic_casting(self) -> bool:
        return bool(
            self.state is wire.GenericVoicePoolState.READY
            and self.pool_id is not None
            and self.version >= 1
            and len(self.slots) == GENERIC_POOL_REQUIRED_SLOT_COUNT
            and min(
                self.ready_slot_count,
                self.rights_approved_slot_count,
                self.quality_approved_slot_count,
                self.production_ready_slot_count,
            )
            == GENERIC_POOL_REQUIRED_SLOT_COUNT
            and all(
                slot.is_production_ready(novel_id=self.novel_id)
                for slot in self.slots
            )
        )

    def slot(self, slot_id: UUID) -> GenericSlotSnapshot | None:
        return next((slot for slot in self.slots if slot.slot_id == slot_id), None)


@dataclass(frozen=True, slots=True)
class AnonymousBindingSnapshot:
    novel_id: UUID
    anonymous_speaker_id: UUID
    profile_id: UUID
    version_id: UUID
    voice: VoiceVersionSnapshot | None
    slot: GenericSlotSnapshot | None = None
    pool_version: int | None = None
    pool_active: bool | None = None

    def __post_init__(self) -> None:
        _require_uuid(self.novel_id, field_name="anonymous binding novel_id")
        _require_uuid(
            self.anonymous_speaker_id,
            field_name="anonymous binding speaker_id",
        )
        _require_uuid(self.profile_id, field_name="anonymous binding profile_id")
        _require_uuid(self.version_id, field_name="anonymous binding version_id")
        if self.voice is not None:
            if type(self.voice) is not VoiceVersionSnapshot:
                raise CastingInputError("anonymous binding voice has an invalid type")
            if (
                self.voice.profile_id != self.profile_id
                or self.voice.version_id != self.version_id
            ):
                raise CastingInputError(
                    "anonymous binding profile/version relation is inconsistent"
                )
        if self.slot is not None:
            if type(self.slot) is not GenericSlotSnapshot:
                raise CastingInputError("anonymous binding slot has an invalid type")
            if self.voice is None or self.slot.voice != self.voice:
                raise CastingInputError(
                    "anonymous binding slot/voice relation is inconsistent"
                )
            if self.pool_version is None:
                raise CastingInputError(
                    "anonymous slot binding requires its exact pool version"
                )
            _require_positive_int(
                self.pool_version,
                field_name="anonymous binding pool_version",
            )
            _require_exact_bool(
                self.pool_active,
                field_name="anonymous binding pool_active",
            )
        elif self.pool_version is not None or self.pool_active is not None:
            raise CastingInputError(
                "anonymous binding pool evidence requires an exact slot"
            )


@dataclass(frozen=True, slots=True)
class CastingAttributes:
    gender: wire.CastingGender = wire.CastingGender.UNKNOWN
    age_band: wire.CastingAgeBand = wire.CastingAgeBand.UNKNOWN
    context_kind: wire.CastingContextKind | None = None
    role_tags: frozenset[str] = frozenset()
    anonymous_stable_key: str | None = None

    def __post_init__(self) -> None:
        if type(self.gender) is not wire.CastingGender:
            raise CastingInputError("casting gender is unsupported")
        if type(self.age_band) is not wire.CastingAgeBand:
            raise CastingInputError("casting age_band is unsupported")
        if self.context_kind is not None and type(
            self.context_kind
        ) is not wire.CastingContextKind:
            raise CastingInputError("casting context_kind is unsupported")
        normalized = _normalized_tags(self.role_tags, field_name="casting role_tags")
        if normalized != self.role_tags:
            raise CastingInputError("casting role_tags must be normalized")
        if self.anonymous_stable_key is not None:
            if (
                type(self.anonymous_stable_key) is not str
                or not self.anonymous_stable_key.strip()
                or len(self.anonymous_stable_key) > 160
                or unicodedata.normalize("NFC", self.anonymous_stable_key)
                != self.anonymous_stable_key
            ):
                raise CastingInputError("anonymous_stable_key must be bounded NFC text")


@dataclass(frozen=True, slots=True)
class CastingRuleSnapshot:
    novel_id: UUID
    rule_id: UUID
    version: int
    priority: int
    enabled: bool
    condition: wire.VoiceCastingCondition
    action: CastingRuleAction
    profile_id: UUID | None = None
    version_id: UUID | None = None
    voice: VoiceVersionSnapshot | None = None
    pool_id: UUID | None = None
    slot_id: UUID | None = None

    def __post_init__(self) -> None:
        _require_uuid(self.novel_id, field_name="casting rule novel_id")
        _require_uuid(self.rule_id, field_name="casting rule_id")
        _require_positive_int(self.version, field_name="casting rule version")
        _require_bounded_int(
            self.priority,
            field_name="casting rule priority",
            minimum=-10_000,
            maximum=10_000,
        )
        _require_exact_bool(self.enabled, field_name="casting rule enabled")
        if type(self.condition) is not wire.VoiceCastingCondition:
            raise CastingInputError("casting rule condition has an invalid type")
        if type(self.action) is not CastingRuleAction:
            raise CastingInputError("casting rule action is unsupported")
        _require_optional_uuid(self.profile_id, field_name="casting rule profile_id")
        _require_optional_uuid(self.version_id, field_name="casting rule version_id")
        _require_optional_uuid(self.pool_id, field_name="casting rule pool_id")
        _require_optional_uuid(self.slot_id, field_name="casting rule slot_id")
        if self.voice is not None and type(self.voice) is not VoiceVersionSnapshot:
            raise CastingInputError("casting rule voice has an invalid type")
        voice_pair = self.profile_id is not None and self.version_id is not None
        if (self.profile_id is None) != (self.version_id is None):
            raise CastingInputError("casting rule profile/version must be paired")
        slot_pair = self.pool_id is not None and self.slot_id is not None
        if (self.pool_id is None) != (self.slot_id is None):
            if self.action is not CastingRuleAction.AUTOMATIC_POOL:
                raise CastingInputError("casting rule pool/slot must be paired")
        if self.action is CastingRuleAction.VOICE_VERSION:
            if not voice_pair or self.voice is None or self.pool_id is not None:
                raise CastingInputError("voice-version rule has an invalid target")
            if (
                self.voice.profile_id != self.profile_id
                or self.voice.version_id != self.version_id
            ):
                raise CastingInputError("voice-version rule relation is inconsistent")
        elif self.action is CastingRuleAction.GENERIC_SLOT:
            if not slot_pair or voice_pair or self.voice is not None:
                raise CastingInputError("generic-slot rule has an invalid target")
        elif self.action is CastingRuleAction.AUTOMATIC_POOL:
            if (
                self.pool_id is None
                or self.slot_id is not None
                or voice_pair
                or self.voice is not None
            ):
                raise CastingInputError("automatic-pool rule has an invalid target")
        elif any(
            value is not None
            for value in (
                self.profile_id,
                self.version_id,
                self.voice,
                self.pool_id,
                self.slot_id,
            )
        ):
            raise CastingInputError("require-review rule cannot carry a target")


@dataclass(frozen=True, slots=True)
class CastingRequest:
    novel_id: UUID
    segment_id: UUID
    source_local_hash: str
    segment_kind: SegmentKind
    speaker: SpeakerRef
    chapter_id: UUID
    volume_id: UUID | None
    scene_id: UUID | None
    attributes: CastingAttributes
    same_scene_voice_deduplication: bool
    used_voice_version_ids: frozenset[UUID] = frozenset()
    used_slot_ids: frozenset[UUID] = frozenset()

    def __post_init__(self) -> None:
        _require_uuid(self.novel_id, field_name="casting request novel_id")
        _require_uuid(self.segment_id, field_name="casting request segment_id")
        _require_sha256(
            self.source_local_hash, field_name="casting request source_local_hash"
        )
        if type(self.segment_kind) is not SegmentKind:
            raise CastingInputError("casting request segment_kind is unsupported")
        if type(self.speaker) is not SpeakerRef:
            raise CastingInputError("casting request speaker has an invalid type")
        _require_uuid(self.chapter_id, field_name="casting request chapter_id")
        _require_optional_uuid(self.volume_id, field_name="casting request volume_id")
        _require_optional_uuid(self.scene_id, field_name="casting request scene_id")
        if type(self.attributes) is not CastingAttributes:
            raise CastingInputError("casting request attributes have an invalid type")
        _require_exact_bool(
            self.same_scene_voice_deduplication,
            field_name="same_scene_voice_deduplication",
        )
        for field_name, values in (
            ("used_voice_version_ids", self.used_voice_version_ids),
            ("used_slot_ids", self.used_slot_ids),
        ):
            if type(values) is not frozenset:
                raise CastingInputError(f"{field_name} must be a frozenset")
            for value in values:
                _require_uuid(value, field_name=f"{field_name} item")
        if (
            self.segment_kind is SegmentKind.SYNTHETIC_PAUSE
            and self.speaker.kind is not SpeakerKind.NARRATOR
        ):
            raise CastingInputError("synthetic pause must use narrator identity")


@dataclass(frozen=True, slots=True)
class CastingInventory:
    narrator_selections: tuple[NarratorSelectionSnapshot, ...] = ()
    character_bindings: tuple[CharacterBindingSnapshot, ...] = ()
    anonymous_bindings: tuple[AnonymousBindingSnapshot, ...] = ()
    rules: tuple[CastingRuleSnapshot, ...] = ()
    generic_pool: GenericPoolSnapshot | None = None

    def __post_init__(self) -> None:
        collections: tuple[tuple[object, ...], ...] = (
            self.narrator_selections,
            self.character_bindings,
            self.anonymous_bindings,
            self.rules,
        )
        if any(type(items) is not tuple for items in collections):
            raise CastingInputError("casting inventory collections must be tuples")
        expected_types = (
            (self.narrator_selections, NarratorSelectionSnapshot),
            (self.character_bindings, CharacterBindingSnapshot),
            (self.anonymous_bindings, AnonymousBindingSnapshot),
            (self.rules, CastingRuleSnapshot),
        )
        if any(
            any(type(item) is not expected for item in items)
            for items, expected in expected_types
        ):
            raise CastingInputError("casting inventory contains an invalid snapshot")
        narrator_keys = [
            (item.novel_id, item.scope_kind, item.scope_id)
            for item in self.narrator_selections
        ]
        if len(narrator_keys) != len(set(narrator_keys)):
            raise CastingInputError("narrator selections contain duplicate scopes")
        character_keys = [
            (item.novel_id, item.character_id) for item in self.character_bindings
        ]
        if len(character_keys) != len(set(character_keys)):
            raise CastingInputError("character bindings contain duplicate identities")
        anonymous_keys = [
            (item.novel_id, item.anonymous_speaker_id)
            for item in self.anonymous_bindings
        ]
        if len(anonymous_keys) != len(set(anonymous_keys)):
            raise CastingInputError("anonymous bindings contain duplicate identities")
        if len({item.rule_id for item in self.rules}) != len(self.rules):
            raise CastingInputError("casting rules contain duplicate rule ids")
        if len({item.priority for item in self.rules}) != len(self.rules):
            raise CastingInputError("casting rules contain duplicate priorities")
        if self.generic_pool is not None and type(
            self.generic_pool
        ) is not GenericPoolSnapshot:
            raise CastingInputError("generic_pool has an invalid type")


@dataclass(frozen=True, slots=True)
class ResolvedVoiceSnapshot:
    """Transient Edition input; never serialize into T3-A casting JSON."""

    profile_id: UUID
    version_id: UUID
    version_number: int
    fingerprint: str
    pool_id: UUID | None = None
    pool_version: int | None = None
    slot_id: UUID | None = None

    def __post_init__(self) -> None:
        _require_uuid(self.profile_id, field_name="resolved voice profile_id")
        _require_uuid(self.version_id, field_name="resolved voice version_id")
        _require_positive_int(
            self.version_number, field_name="resolved voice version_number"
        )
        _require_sha256(self.fingerprint, field_name="resolved voice fingerprint")
        _require_optional_uuid(self.pool_id, field_name="resolved voice pool_id")
        _require_optional_uuid(self.slot_id, field_name="resolved voice slot_id")
        if self.pool_version is not None:
            _require_positive_int(
                self.pool_version, field_name="resolved voice pool_version"
            )
        if not (
            (self.pool_id is None and self.pool_version is None and self.slot_id is None)
            or (
                self.pool_id is not None
                and self.pool_version is not None
                and self.slot_id is not None
            )
        ):
            raise CastingInputError("resolved generic pool identity must be complete")


@dataclass(frozen=True, slots=True)
class CastingResolution:
    speaker: SpeakerRef
    segment_id: UUID
    source_local_hash: str
    decision: CastingDecision
    source: CastingResolutionSource
    resolved_voice: ResolvedVoiceSnapshot | None
    issues: tuple[ScriptIssueContract, ...]
    rule_authority: CastingRuleAuthorityRecord | None = None

    def __post_init__(self) -> None:
        if type(self.speaker) is not SpeakerRef:
            raise CastingInputError("casting resolution speaker has an invalid type")
        _require_uuid(self.segment_id, field_name="casting resolution segment_id")
        _require_sha256(
            self.source_local_hash,
            field_name="casting resolution source_local_hash",
        )
        if type(self.decision) is not CastingDecision:
            raise CastingInputError("casting resolution decision has an invalid type")
        if type(self.source) is not CastingResolutionSource:
            raise CastingInputError("casting resolution source is unsupported")
        if self.resolved_voice is not None and type(
            self.resolved_voice
        ) is not ResolvedVoiceSnapshot:
            raise CastingInputError("casting resolved_voice has an invalid type")
        if type(self.issues) is not tuple or not all(
            type(issue) is ScriptIssueContract for issue in self.issues
        ):
            raise CastingInputError("casting issues must be frozen script issues")
        if self.issues != tuple(
            sorted(
                self.issues,
                key=lambda issue: (
                    issue.code,
                    str(issue.segment_id) if issue.segment_id else "",
                    issue.evidence_digest or "",
                ),
            )
        ):
            raise CastingInputError("casting issues must use T3-A canonical order")
        if any(issue.segment_id != self.segment_id for issue in self.issues):
            raise CastingInputError("casting issue belongs to another segment")
        codes = {issue.code for issue in self.issues}
        if self.decision.origin is CastingDecisionOrigin.UNRESOLVED:
            if self.resolved_voice is not None or "B_CASTING_TARGET_UNRESOLVED" not in codes:
                raise CastingInputError(
                    "unresolved casting must have no voice and its frozen blocker"
                )
        elif self.decision.origin is CastingDecisionOrigin.NOT_APPLICABLE:
            if self.resolved_voice is not None or self.issues:
                raise CastingInputError("not-applicable casting cannot carry voice/issues")
        elif self.resolved_voice is None:
            raise CastingInputError("resolved casting requires transient voice evidence")
        if self.decision.origin is CastingDecisionOrigin.CASTING_RULE:
            if self.rule_authority is None or self.rule_authority.decision != self.decision:
                raise CastingInputError(
                    "casting-rule decision requires its exact T3-A authority record"
                )
            if (
                self.rule_authority.segment_id != self.segment_id
                or self.rule_authority.source_local_hash != self.source_local_hash
                or self.rule_authority.speaker_target_hash
                != speaker_target_hash(self.speaker, self.decision)
            ):
                raise CastingInputError(
                    "casting-rule authority differs from segment/source/speaker decision"
                )
        elif self.rule_authority is not None:
            raise CastingInputError("only casting-rule decisions carry rule authority")
        target = self.decision.final_target
        if target is not None and self.resolved_voice is not None:
            if (
                target.kind is CastingTargetKind.PROFILE
                and target.profile_id != self.resolved_voice.profile_id
            ):
                raise CastingInputError("profile target differs from resolved voice")
            if target.kind is CastingTargetKind.GENERIC_SLOT and (
                target.pool_id != self.resolved_voice.pool_id
                or target.slot_id != self.resolved_voice.slot_id
            ):
                raise CastingInputError("pool-slot target differs from resolved voice")

    @property
    def blocker_codes(self) -> tuple[str, ...]:
        return tuple(issue.code for issue in self.issues if issue.severity.value == "blocker")

    @property
    def warning_codes(self) -> tuple[str, ...]:
        return tuple(issue.code for issue in self.issues if issue.severity.value == "warning")


def _target_key(target: CastingTargetRef) -> bytes:
    return canonical_json_bytes(
        {
            "kind": target.kind.value,
            "binding_id": str(target.binding_id) if target.binding_id else None,
            "character_id": str(target.character_id) if target.character_id else None,
            "anonymous_speaker_id": (
                str(target.anonymous_speaker_id)
                if target.anonymous_speaker_id
                else None
            ),
            "pool_id": str(target.pool_id) if target.pool_id else None,
            "slot_id": str(target.slot_id) if target.slot_id else None,
            "profile_id": str(target.profile_id) if target.profile_id else None,
        }
    )


def _canonical_targets(
    targets: Iterable[CastingTargetRef],
) -> tuple[CastingTargetRef, ...]:
    unique = {_target_key(target): target for target in targets}
    return tuple(unique[key] for key in sorted(unique))


def _issues(segment_id: UUID, codes: Iterable[str]) -> tuple[ScriptIssueContract, ...]:
    return tuple(
        sorted(
            (
                ScriptIssueContract(
                    code=code,
                    severity=issue_severity(code),
                    segment_id=segment_id,
                )
                for code in set(codes)
            ),
            key=lambda issue: (
                issue.code,
                str(issue.segment_id) if issue.segment_id else "",
                issue.evidence_digest or "",
            ),
        )
    )


def _unresolved(
    request: CastingRequest,
    *,
    candidates: Iterable[CastingTargetRef] = (),
    codes: Iterable[str] = (),
) -> CastingResolution:
    all_codes = {"B_CASTING_TARGET_UNRESOLVED", *codes}
    return CastingResolution(
        speaker=request.speaker,
        segment_id=request.segment_id,
        source_local_hash=request.source_local_hash,
        decision=CastingDecision(
            candidate_targets=_canonical_targets(candidates),
            final_target=None,
            origin=CastingDecisionOrigin.UNRESOLVED,
        ),
        source=CastingResolutionSource.UNRESOLVED,
        resolved_voice=None,
        issues=_issues(request.segment_id, all_codes),
    )


def _resolved_voice(
    voice: VoiceVersionSnapshot,
    *,
    pool: GenericPoolSnapshot | None = None,
    slot: GenericSlotSnapshot | None = None,
    bound_pool_version: int | None = None,
) -> ResolvedVoiceSnapshot:
    if slot is None:
        if pool is not None or bound_pool_version is not None:
            raise CastingInputError("resolved pool evidence requires an exact slot")
        pool_id = None
        pool_version = None
    elif pool is not None:
        if bound_pool_version is not None or pool.pool_id != slot.pool_id:
            raise CastingInputError("resolved pool-slot relation is inconsistent")
        pool_id = pool.pool_id
        pool_version = pool.version
    else:
        if bound_pool_version is None:
            raise CastingInputError("bound slot requires its exact pool version")
        _require_positive_int(
            bound_pool_version,
            field_name="resolved bound pool version",
        )
        pool_id = slot.pool_id
        pool_version = bound_pool_version
    return ResolvedVoiceSnapshot(
        profile_id=voice.profile_id,
        version_id=voice.version_id,
        version_number=voice.version_number,
        fingerprint=voice.fingerprint,
        pool_id=pool_id,
        pool_version=pool_version,
        slot_id=slot.slot_id if slot else None,
    )


def _success(
    request: CastingRequest,
    *,
    target: CastingTargetRef,
    voice: VoiceVersionSnapshot,
    origin: CastingDecisionOrigin,
    source: CastingResolutionSource,
    warning_codes: Iterable[str] = (),
    rule: CastingRuleSnapshot | None = None,
    pool: GenericPoolSnapshot | None = None,
    slot: GenericSlotSnapshot | None = None,
    bound_pool_version: int | None = None,
    candidates: Iterable[CastingTargetRef] | None = None,
) -> CastingResolution:
    decision = CastingDecision(
        candidate_targets=_canonical_targets(candidates or (target,)),
        final_target=target,
        origin=origin,
        rule_id=rule.rule_id if rule else None,
        rule_version=rule.version if rule else None,
    )
    authority = None
    if rule is not None:
        authority = CastingRuleAuthorityRecord(
            decision=decision,
            segment_id=request.segment_id,
            source_local_hash=request.source_local_hash,
            speaker_target_hash=speaker_target_hash(request.speaker, decision),
        )
    return CastingResolution(
        speaker=request.speaker,
        segment_id=request.segment_id,
        source_local_hash=request.source_local_hash,
        decision=decision,
        source=source,
        resolved_voice=_resolved_voice(
            voice,
            pool=pool,
            slot=slot,
            bound_pool_version=bound_pool_version,
        ),
        issues=_issues(request.segment_id, warning_codes),
        rule_authority=authority,
    )


def _voice_or_block(
    request: CastingRequest,
    *,
    target: CastingTargetRef,
    voice: VoiceVersionSnapshot | None,
    origin: CastingDecisionOrigin,
    source: CastingResolutionSource,
    rule: CastingRuleSnapshot | None = None,
    pool: GenericPoolSnapshot | None = None,
    slot: GenericSlotSnapshot | None = None,
    bound_pool_version: int | None = None,
    warning_codes: Iterable[str] = (),
) -> CastingResolution:
    if voice is None:
        return _unresolved(
            request,
            candidates=(target,),
            codes=("B_VOICE_VERSION_UNAVAILABLE",),
        )
    blockers = voice.blocker_codes(novel_id=request.novel_id)
    if blockers:
        return _unresolved(request, candidates=(target,), codes=blockers)
    return _success(
        request,
        target=target,
        voice=voice,
        origin=origin,
        source=source,
        warning_codes=warning_codes,
        rule=rule,
        pool=pool,
        slot=slot,
        bound_pool_version=bound_pool_version,
    )


def _rule_matches(rule: CastingRuleSnapshot, request: CastingRequest) -> bool:
    if not rule.enabled:
        return False
    if request.speaker.kind not in {
        SpeakerKind.CHARACTER,
        SpeakerKind.ANONYMOUS,
        SpeakerKind.GROUP,
        SpeakerKind.UNKNOWN,
    }:
        return False
    speaker_kind = wire.CastingSpeakerKind(request.speaker.kind.value)
    condition = rule.condition
    if condition.speaker_kinds and speaker_kind not in condition.speaker_kinds:
        return False
    if condition.genders and request.attributes.gender not in condition.genders:
        return False
    if condition.age_bands and request.attributes.age_band not in condition.age_bands:
        return False
    if condition.context_kinds and (
        request.attributes.context_kind is None
        or request.attributes.context_kind not in condition.context_kinds
    ):
        return False
    required_tags = {
        _normalized_tag(tag, field_name="casting rule role tag")
        for tag in condition.role_tags
    }
    return required_tags.issubset(request.attributes.role_tags)


def _matching_rules(
    request: CastingRequest,
    inventory: CastingInventory,
    *,
    automatic: bool,
) -> tuple[CastingRuleSnapshot, ...]:
    return tuple(
        sorted(
            (
                rule
                for rule in inventory.rules
                if rule.novel_id == request.novel_id
                and (rule.action is CastingRuleAction.AUTOMATIC_POOL) is automatic
                and _rule_matches(rule, request)
            ),
            key=lambda rule: (-rule.priority, str(rule.rule_id)),
        )
    )


def _pool_failure_codes(pool: GenericPoolSnapshot | None, novel_id: UUID) -> set[str]:
    if pool is None or not pool.slots:
        return {"B_VOICE_MISSING"}
    codes: set[str] = set()
    if len(pool.slots) != GENERIC_POOL_REQUIRED_SLOT_COUNT:
        codes.add("B_VOICE_MISSING")
    for slot in pool.slots:
        if slot.voice is None:
            codes.add("B_VOICE_MISSING")
            continue
        codes.update(slot.voice.blocker_codes(novel_id=novel_id))
    if not codes:
        codes.add("B_VOICE_MISSING")
    return codes


def _resolve_explicit_rule(
    request: CastingRequest,
    inventory: CastingInventory,
    rule: CastingRuleSnapshot,
) -> CastingResolution:
    if rule.action is CastingRuleAction.REQUIRE_REVIEW:
        return _unresolved(request)
    if rule.action is CastingRuleAction.VOICE_VERSION:
        assert rule.profile_id is not None
        target = CastingTargetRef(
            kind=CastingTargetKind.PROFILE,
            profile_id=rule.profile_id,
        )
        return _voice_or_block(
            request,
            target=target,
            voice=rule.voice,
            origin=CastingDecisionOrigin.CASTING_RULE,
            source=CastingResolutionSource.EXPLICIT_RULE,
            rule=rule,
        )
    if rule.action is not CastingRuleAction.GENERIC_SLOT:
        raise CastingInputError("automatic pool rule used in explicit rule path")
    assert rule.pool_id is not None and rule.slot_id is not None
    target = CastingTargetRef(
        kind=CastingTargetKind.GENERIC_SLOT,
        pool_id=rule.pool_id,
        slot_id=rule.slot_id,
    )
    pool = inventory.generic_pool
    if (
        pool is None
        or pool.novel_id != request.novel_id
        or pool.pool_id != rule.pool_id
        or not pool.ready_for_automatic_casting()
    ):
        return _unresolved(
            request,
            candidates=(target,),
            codes=_pool_failure_codes(pool, request.novel_id),
        )
    slot = pool.slot(rule.slot_id)
    if slot is None:
        return _unresolved(
            request,
            candidates=(target,),
            codes=("B_VOICE_MISSING",),
        )
    if request.same_scene_voice_deduplication and (
        slot.slot_id in request.used_slot_ids
        or (slot.voice is not None and slot.voice.version_id in request.used_voice_version_ids)
    ):
        return _unresolved(request, candidates=(target,))
    return _voice_or_block(
        request,
        target=target,
        voice=slot.voice,
        origin=CastingDecisionOrigin.CASTING_RULE,
        source=CastingResolutionSource.EXPLICIT_RULE,
        rule=rule,
        pool=pool,
        slot=slot,
        warning_codes=("W_GENERIC_VOICE_FALLBACK",),
    )


def _slot_base_matches(slot: GenericSlotSnapshot, request: CastingRequest) -> bool:
    speaker_kind = wire.CastingSpeakerKind(request.speaker.kind.value)
    if slot.speaker_kinds and speaker_kind not in slot.speaker_kinds:
        return False
    if slot.context_kinds and (
        request.attributes.context_kind is None
        or request.attributes.context_kind not in slot.context_kinds
    ):
        return False
    return True


def _demographic_match(slot: GenericSlotSnapshot, request: CastingRequest) -> bool:
    known_gender = request.attributes.gender is not wire.CastingGender.UNKNOWN
    known_age = request.attributes.age_band is not wire.CastingAgeBand.UNKNOWN
    if not known_gender and not known_age:
        return False
    if known_gender and slot.genders and request.attributes.gender not in slot.genders:
        return False
    if known_age and slot.age_bands and request.attributes.age_band not in slot.age_bands:
        return False
    return bool((known_gender and slot.genders) or (known_age and slot.age_bands))


def _generic_tier(
    pool: GenericPoolSnapshot, request: CastingRequest
) -> tuple[GenericSlotSnapshot, ...]:
    base = [slot for slot in pool.slots if _slot_base_matches(slot, request)]
    described = [
        slot
        for slot in base
        if request.attributes.role_tags
        and bool(slot.role_tags & request.attributes.role_tags)
        and (
            not slot.genders
            or request.attributes.gender in slot.genders
            or request.attributes.gender is wire.CastingGender.UNKNOWN
        )
        and (
            not slot.age_bands
            or request.attributes.age_band in slot.age_bands
            or request.attributes.age_band is wire.CastingAgeBand.UNKNOWN
        )
    ]
    if described:
        return tuple(described)
    demographic = [slot for slot in base if _demographic_match(slot, request)]
    if demographic:
        return tuple(demographic)
    return tuple(slot for slot in base if slot.neutral_fallback)


def _stable_identity(request: CastingRequest) -> str:
    speaker = request.speaker
    if speaker.kind is SpeakerKind.CHARACTER:
        assert speaker.character_id is not None
        return f"character:{speaker.character_id}"
    if speaker.kind is SpeakerKind.ANONYMOUS:
        if request.attributes.anonymous_stable_key is None:
            raise CastingInputError(
                "automatic anonymous casting requires its T3-E stable key"
            )
        return f"anonymous:{request.attributes.anonymous_stable_key}"
    if speaker.kind is SpeakerKind.GROUP:
        assert speaker.group_key is not None
        return f"group:{speaker.group_key}"
    if speaker.kind is SpeakerKind.UNKNOWN:
        return f"unknown:{request.source_local_hash}"
    raise CastingInputError(
        "generic casting requires character/anonymous/group/unknown"
    )


def _stable_slot_order(
    request: CastingRequest,
    pool: GenericPoolSnapshot,
    slots: Iterable[GenericSlotSnapshot],
) -> tuple[GenericSlotSnapshot, ...]:
    identity = _stable_identity(request)

    def key(slot: GenericSlotSnapshot) -> tuple[str, str]:
        digest = hashlib.sha256(
            GENERIC_ASSIGNMENT_VERSION.encode("ascii")
            + b"\x00"
            + canonical_json_bytes(
                {
                    "novel_id": str(request.novel_id),
                    "stable_identity": identity,
                    "pool_id": str(pool.pool_id),
                    "pool_version": pool.version,
                    "slot_id": str(slot.slot_id),
                    "slot_key": slot.slot_key,
                }
            )
        ).hexdigest()
        return digest, str(slot.slot_id)

    return tuple(sorted(slots, key=key))


def _resolve_automatic_rule(
    request: CastingRequest,
    inventory: CastingInventory,
    rule: CastingRuleSnapshot,
) -> CastingResolution:
    assert rule.action is CastingRuleAction.AUTOMATIC_POOL
    assert rule.pool_id is not None
    pool = inventory.generic_pool
    if (
        pool is None
        or pool.novel_id != request.novel_id
        or pool.pool_id != rule.pool_id
        or not pool.ready_for_automatic_casting()
    ):
        return _unresolved(
            request,
            codes=_pool_failure_codes(pool, request.novel_id),
        )
    tier = _generic_tier(pool, request)
    candidates = tuple(
        CastingTargetRef(
            kind=CastingTargetKind.GENERIC_SLOT,
            pool_id=pool.pool_id,
            slot_id=slot.slot_id,
        )
        for slot in tier
    )
    if not tier:
        return _unresolved(
            request,
            codes=("B_VOICE_MISSING",),
        )
    ordered = _stable_slot_order(request, pool, tier)
    if request.same_scene_voice_deduplication:
        ordered = tuple(
            slot
            for slot in ordered
            if slot.slot_id not in request.used_slot_ids
            and slot.voice is not None
            and slot.voice.version_id not in request.used_voice_version_ids
        )
    if not ordered:
        return _unresolved(request, candidates=candidates)
    slot = ordered[0]
    assert slot.voice is not None and pool.pool_id is not None
    target = CastingTargetRef(
        kind=CastingTargetKind.GENERIC_SLOT,
        pool_id=pool.pool_id,
        slot_id=slot.slot_id,
    )
    return _success(
        request,
        target=target,
        voice=slot.voice,
        origin=CastingDecisionOrigin.CASTING_RULE,
        source=CastingResolutionSource.GENERIC_RULE,
        warning_codes=("W_GENERIC_VOICE_FALLBACK",),
        rule=rule,
        pool=pool,
        slot=slot,
        candidates=candidates,
    )


def _matching_narrator_selections(
    request: CastingRequest, inventory: CastingInventory
) -> tuple[NarratorSelectionSnapshot, ...]:
    scope_ids = {
        CastingScopeKind.NOVEL: request.novel_id,
        CastingScopeKind.VOLUME: request.volume_id,
        CastingScopeKind.CHAPTER: request.chapter_id,
    }
    matches = tuple(
        selection
        for selection in inventory.narrator_selections
        if selection.novel_id == request.novel_id
        and scope_ids[selection.scope_kind] is not None
        and selection.scope_id == scope_ids[selection.scope_kind]
    )
    priority = {
        CastingScopeKind.CHAPTER: 3,
        CastingScopeKind.VOLUME: 2,
        CastingScopeKind.NOVEL: 1,
    }
    return tuple(sorted(matches, key=lambda item: -priority[item.scope_kind]))


def _resolve_narrator(
    request: CastingRequest, inventory: CastingInventory
) -> CastingResolution:
    selections = _matching_narrator_selections(request, inventory)
    if not selections:
        return _unresolved(request, codes=("B_VOICE_MISSING",))
    selection = selections[0]
    target = CastingTargetRef(
        kind=CastingTargetKind.PROFILE,
        profile_id=selection.profile_id,
    )
    source = {
        CastingScopeKind.CHAPTER: CastingResolutionSource.CHAPTER_NARRATOR,
        CastingScopeKind.VOLUME: CastingResolutionSource.VOLUME_NARRATOR,
        CastingScopeKind.NOVEL: CastingResolutionSource.NOVEL_NARRATOR,
    }[selection.scope_kind]
    return _voice_or_block(
        request,
        target=target,
        voice=selection.voice,
        origin=CastingDecisionOrigin.NARRATOR_SETTING,
        source=source,
    )


def _resolve_character_binding(
    request: CastingRequest, binding: CharacterBindingSnapshot
) -> CastingResolution:
    assert request.speaker.character_id is not None
    target = CastingTargetRef(
        kind=CastingTargetKind.CHARACTER_BINDING,
        binding_id=binding.binding_id,
        character_id=request.speaker.character_id,
    )
    source = (
        CastingResolutionSource.CHARACTER_DEDICATED
        if binding.policy is wire.CharacterVoiceBindingPolicy.DEDICATED
        else CastingResolutionSource.CHARACTER_INHERITED
    )
    return _voice_or_block(
        request,
        target=target,
        voice=binding.voice,
        origin=CastingDecisionOrigin.CHARACTER_BINDING,
        source=source,
    )


def _resolve_anonymous_binding(
    request: CastingRequest, binding: AnonymousBindingSnapshot
) -> CastingResolution:
    assert request.speaker.anonymous_speaker_id is not None
    target = CastingTargetRef(
        kind=CastingTargetKind.ANONYMOUS_BINDING,
        anonymous_speaker_id=request.speaker.anonymous_speaker_id,
    )
    if binding.slot is not None:
        assert binding.pool_version is not None
        if (
            not binding.pool_active
            or not binding.slot.enabled
            or binding.slot.state is not wire.GenericVoiceSlotState.READY
        ):
            return _unresolved(
                request,
                candidates=(target,),
                codes=("B_VOICE_VERSION_UNAVAILABLE",),
            )
    return _voice_or_block(
        request,
        target=target,
        voice=binding.voice,
        origin=CastingDecisionOrigin.ANONYMOUS_BINDING,
        source=CastingResolutionSource.ANONYMOUS_BINDING,
        slot=binding.slot,
        bound_pool_version=binding.pool_version,
    )


def resolve_casting(
    request: CastingRequest, inventory: CastingInventory
) -> CastingResolution:
    """Resolve one segment using the frozen priority and fail-closed rules.

    Priority is chapter narrator > volume narrator > novel narrator / explicit
    work rule > dedicated character > inherited character > known anonymous >
    deterministic 24-slot automatic rule > unresolved.  A present higher-level
    target that is unusable returns blockers and is never skipped.
    """

    if type(request) is not CastingRequest or type(inventory) is not CastingInventory:
        raise CastingInputError("resolve_casting requires frozen request/inventory")
    for collection in (
        inventory.narrator_selections,
        inventory.character_bindings,
        inventory.anonymous_bindings,
        inventory.rules,
    ):
        if any(item.novel_id != request.novel_id for item in collection):
            raise CastingInputError("casting inventory contains another novel")
    if (
        inventory.generic_pool is not None
        and inventory.generic_pool.novel_id != request.novel_id
    ):
        raise CastingInputError("generic pool belongs to another novel")

    if request.segment_kind is SegmentKind.SYNTHETIC_PAUSE:
        return CastingResolution(
            speaker=request.speaker,
            segment_id=request.segment_id,
            source_local_hash=request.source_local_hash,
            decision=CastingDecision(
                candidate_targets=(),
                final_target=None,
                origin=CastingDecisionOrigin.NOT_APPLICABLE,
            ),
            source=CastingResolutionSource.NOT_APPLICABLE,
            resolved_voice=None,
            issues=(),
        )
    if request.speaker.kind is SpeakerKind.NARRATOR:
        return _resolve_narrator(request, inventory)

    explicit_rules = _matching_rules(request, inventory, automatic=False)
    if explicit_rules:
        return _resolve_explicit_rule(request, inventory, explicit_rules[0])

    if request.speaker.kind is SpeakerKind.CHARACTER:
        binding = next(
            (
                item
                for item in inventory.character_bindings
                if item.character_id == request.speaker.character_id
            ),
            None,
        )
        if binding is not None:
            return _resolve_character_binding(request, binding)
    elif request.speaker.kind is SpeakerKind.ANONYMOUS:
        binding = next(
            (
                item
                for item in inventory.anonymous_bindings
                if item.anonymous_speaker_id
                == request.speaker.anonymous_speaker_id
            ),
            None,
        )
        if binding is not None:
            return _resolve_anonymous_binding(request, binding)

    automatic_rules = _matching_rules(request, inventory, automatic=True)
    if automatic_rules:
        return _resolve_automatic_rule(request, inventory, automatic_rules[0])
    if request.speaker.kind is SpeakerKind.UNKNOWN:
        return _unresolved(request, codes=("B_SPEAKER_UNKNOWN",))
    return _unresolved(request, codes=("B_VOICE_MISSING",))


__all__ = [
    "AUTOMATIC_GENERIC_CASTING_RULE_NAMESPACE",
    "CASTING_RESOLVER_VERSION",
    "GENERIC_ASSIGNMENT_VERSION",
    "GENERIC_POOL_REQUIRED_SLOT_COUNT",
    "AnonymousBindingSnapshot",
    "CastingAttributes",
    "CastingInputError",
    "CastingInventory",
    "CastingRequest",
    "CastingResolution",
    "CastingResolutionSource",
    "CastingRuleAction",
    "CastingRuleSnapshot",
    "CastingScopeKind",
    "CharacterBindingSnapshot",
    "GenericPoolSnapshot",
    "GenericSlotSnapshot",
    "NarratorSelectionSnapshot",
    "ResolvedVoiceSnapshot",
    "VoiceVersionSnapshot",
    "automatic_generic_casting_rule_id",
    "resolve_casting",
]
