"""Pure orchestration for durable, automatic character-voice preparation.

Plan 55 deliberately keeps persistence and the existing product workflows out
of this module.  The aggregate below is the single state authority shared by a
future SQLAlchemy repository, the worker, and HTTP projections.  The narrow
ports adapt the already-public analyze-only narration, VoiceGenerator,
official-selection, and narration-production services; none of their contracts
or decision rules are reimplemented here.

Every external write is protected by a deterministic idempotency key.  State is
published with optimistic aggregate CAS, while the narration continuation also
uses an expiring attempt/fence lease.  A worker crash can therefore replay the
same child command or final Narration Request, but cannot create a second one.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import Enum
import hashlib
import re
from typing import Callable, Final, Protocol
from uuid import UUID, uuid4

from .services import (
    IdempotencyConflict,
    InvalidNarrationState,
    NarrationCasConflict,
    NarrationServiceError,
    canonical_sha256,
)


VOICE_PREPARATION_CONTRACT_VERSION: Final = "narration-voice-preparation/1"
VOICE_PREPARATION_MODE: Final = "prepare_missing_dedicated"
VOICE_PREPARATION_JOB_KIND: Final = "narration.voice_prepare"
VOICE_PREPARATION_SPEAKER_DIGEST_VERSION: Final = (
    "narration-voice-preparation-speakers/1"
)
VOICE_PREPARATION_CONTINUATION_LEASE: Final = timedelta(minutes=15)

VOICE_PREPARATION_NOT_READY: Final = "VOICE_PREPARATION_NOT_READY"
VOICE_PREPARATION_PREFLIGHT_FAILED: Final = "VOICE_PREPARATION_PREFLIGHT_FAILED"
VOICE_PREPARATION_SOURCE_DRIFTED: Final = "VOICE_PREPARATION_SOURCE_DRIFTED"
VOICE_PREPARATION_WORKSPACE_DRIFTED: Final = "VOICE_PREPARATION_WORKSPACE_DRIFTED"
VOICE_PREPARATION_BINDING_DRIFTED: Final = "VOICE_PREPARATION_BINDING_DRIFTED"
VOICE_PREPARATION_CONTINUATION_CONFLICT: Final = (
    "VOICE_PREPARATION_CONTINUATION_CONFLICT"
)
VOICE_PREPARATION_HEAVY_RUNTIME_UNAVAILABLE: Final = (
    "VOICE_PREPARATION_HEAVY_RUNTIME_UNAVAILABLE"
)
VOICE_PREPARATION_TARGET_FAILED: Final = "VOICE_PREPARATION_TARGET_FAILED"

VOICE_PREPARATION_FAILURE_CODES: Final = frozenset(
    {
        VOICE_PREPARATION_NOT_READY,
        VOICE_PREPARATION_PREFLIGHT_FAILED,
        VOICE_PREPARATION_SOURCE_DRIFTED,
        VOICE_PREPARATION_WORKSPACE_DRIFTED,
        VOICE_PREPARATION_BINDING_DRIFTED,
        VOICE_PREPARATION_CONTINUATION_CONFLICT,
        VOICE_PREPARATION_HEAVY_RUNTIME_UNAVAILABLE,
        VOICE_PREPARATION_TARGET_FAILED,
    }
)

_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_IDEMPOTENCY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")


class VoicePreparationError(NarrationServiceError):
    """Stable parent-workflow fault without leaking child failure details."""

    def __init__(self, code: str, message: str, *, retryable: bool) -> None:
        if code not in VOICE_PREPARATION_FAILURE_CODES:
            raise ValueError("voice preparation error code is outside the taxonomy")
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class VoicePreparationCommandState(str, Enum):
    RESERVED = "reserved"
    PREPARING = "preparing"
    READY = "ready"
    READY_WITH_WARNINGS = "ready_with_warnings"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


class VoicePreparationItemState(str, Enum):
    PENDING = "pending"
    PRESERVED = "preserved"
    QUEUED = "queued"
    GENERATING = "generating"
    READY_APPLIED = "ready_applied"
    READY_UNAPPLIED = "ready_unapplied"
    FALLBACK_OFFICIAL = "fallback_official"
    FAILED = "failed"
    CANCELLED = "cancelled"


class VoicePreparationContinuationState(str, Enum):
    NOT_APPLICABLE = "not_applicable"
    PENDING = "pending"
    CREATING = "creating"
    CREATED = "created"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"
    FAILED = "failed"


class ExistingVoiceKind(str, Enum):
    NONE = "none"
    OFFICIAL = "official"
    PRIVATE = "private"
    UPLOADED = "uploaded"
    GENERATED = "generated"


class VoiceGeneratorChildState(str, Enum):
    ACTIVE = "active"
    READY_APPLIED = "ready_applied"
    READY_UNAPPLIED = "ready_unapplied"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


class OfficialFallbackState(str, Enum):
    APPLIED = "applied"
    CURRENT_USABLE = "current_usable"
    CAS_DRIFTED = "cas_drifted"
    FAILED = "failed"


class ContinuationResultState(str, Enum):
    CREATED = "created"
    SOURCE_DRIFTED = "source_drifted"
    CONFLICT = "conflict"


ACTIVE_COMMAND_STATES: Final = frozenset(
    {VoicePreparationCommandState.RESERVED, VoicePreparationCommandState.PREPARING}
)
TERMINAL_COMMAND_STATES: Final = frozenset(
    set(VoicePreparationCommandState) - set(ACTIVE_COMMAND_STATES)
)
TERMINAL_ITEM_STATES: Final = frozenset(
    {
        VoicePreparationItemState.PRESERVED,
        VoicePreparationItemState.READY_APPLIED,
        VoicePreparationItemState.READY_UNAPPLIED,
        VoicePreparationItemState.FALLBACK_OFFICIAL,
        VoicePreparationItemState.FAILED,
        VoicePreparationItemState.CANCELLED,
    }
)
_WARNING_ITEM_STATES: Final = frozenset(
    {
        VoicePreparationItemState.READY_UNAPPLIED,
        VoicePreparationItemState.FALLBACK_OFFICIAL,
        VoicePreparationItemState.FAILED,
    }
)
_COMMAND_TRANSITIONS: Final = {
    VoicePreparationCommandState.RESERVED: frozenset(
        {
            VoicePreparationCommandState.PREPARING,
            VoicePreparationCommandState.READY,
            VoicePreparationCommandState.READY_WITH_WARNINGS,
            VoicePreparationCommandState.FAILED,
            VoicePreparationCommandState.CANCELLED,
            VoicePreparationCommandState.SUPERSEDED,
        }
    ),
    VoicePreparationCommandState.PREPARING: frozenset(
        {
            VoicePreparationCommandState.READY,
            VoicePreparationCommandState.READY_WITH_WARNINGS,
            VoicePreparationCommandState.FAILED,
            VoicePreparationCommandState.CANCELLED,
            VoicePreparationCommandState.SUPERSEDED,
        }
    ),
}
_ITEM_TRANSITIONS: Final = {
    VoicePreparationItemState.PENDING: frozenset(
        {
            VoicePreparationItemState.PRESERVED,
            VoicePreparationItemState.QUEUED,
            VoicePreparationItemState.FALLBACK_OFFICIAL,
            VoicePreparationItemState.FAILED,
            VoicePreparationItemState.CANCELLED,
        }
    ),
    VoicePreparationItemState.QUEUED: frozenset(
        {
            VoicePreparationItemState.GENERATING,
            VoicePreparationItemState.READY_APPLIED,
            VoicePreparationItemState.READY_UNAPPLIED,
            VoicePreparationItemState.FALLBACK_OFFICIAL,
            VoicePreparationItemState.FAILED,
            VoicePreparationItemState.CANCELLED,
        }
    ),
    VoicePreparationItemState.GENERATING: frozenset(
        {
            VoicePreparationItemState.READY_APPLIED,
            VoicePreparationItemState.READY_UNAPPLIED,
            VoicePreparationItemState.FALLBACK_OFFICIAL,
            VoicePreparationItemState.FAILED,
            VoicePreparationItemState.CANCELLED,
        }
    ),
}


def ensure_command_transition(
    current: VoicePreparationCommandState,
    target: VoicePreparationCommandState,
) -> VoicePreparationCommandState:
    if type(current) is not VoicePreparationCommandState or type(
        target
    ) is not VoicePreparationCommandState:
        raise ValueError("voice preparation command state is outside the taxonomy")
    if current is target:
        return target
    if target not in _COMMAND_TRANSITIONS.get(current, frozenset()):
        raise ValueError(
            f"invalid voice preparation transition: {current.value}->{target.value}"
        )
    return target


def ensure_item_transition(
    current: VoicePreparationItemState,
    target: VoicePreparationItemState,
) -> VoicePreparationItemState:
    if type(current) is not VoicePreparationItemState or type(
        target
    ) is not VoicePreparationItemState:
        raise ValueError("voice preparation item state is outside the taxonomy")
    if current is target:
        return target
    if target not in _ITEM_TRANSITIONS.get(current, frozenset()):
        raise ValueError(
            f"invalid voice preparation item transition: {current.value}->{target.value}"
        )
    return target


def _require_sha256(value: str, *, field_name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be lowercase SHA-256")
    return value


def _require_idempotency_key(value: str) -> str:
    if type(value) is not str or _IDEMPOTENCY.fullmatch(value) is None:
        raise ValueError("idempotency key is outside the frozen syntax")
    return value


def _require_aware(value: datetime, *, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class FrozenSpeakerSegment:
    ordinal: int
    segment_kind: str
    source_start_utf16: int | None
    source_end_utf16: int | None
    speaker_kind: str
    character_id: UUID | None = None
    anonymous_speaker_id: UUID | None = None

    def __post_init__(self) -> None:
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise ValueError("speaker ordinal must be a non-negative integer")
        if not self.segment_kind or self.speaker_kind not in {
            "narrator",
            "character",
            "anonymous",
            "group",
            "unknown",
        }:
            raise ValueError("speaker segment has an unsupported identity")
        if (self.source_start_utf16 is None) != (self.source_end_utf16 is None):
            raise ValueError("speaker source range must be complete or absent")
        if self.source_start_utf16 is not None and (
            type(self.source_start_utf16) is not int
            or type(self.source_end_utf16) is not int
            or self.source_start_utf16 < 0
            or self.source_end_utf16 <= self.source_start_utf16
        ):
            raise ValueError("speaker source range is invalid")
        if self.speaker_kind == "character":
            if self.character_id is None or self.anonymous_speaker_id is not None:
                raise ValueError("character speaker requires only character_id")
        elif self.speaker_kind == "anonymous":
            if self.anonymous_speaker_id is None or self.character_id is not None:
                raise ValueError("anonymous speaker requires only anonymous_speaker_id")
        elif self.character_id is not None or self.anonymous_speaker_id is not None:
            raise ValueError("non-character speaker cannot carry a stable target identity")


def speaker_summary_digest(segments: tuple[FrozenSpeakerSegment, ...]) -> str:
    """Hash only immutable text coordinates and stable speaker identities."""

    if type(segments) is not tuple:
        raise TypeError("speaker segments must be a tuple")
    if tuple(item.ordinal for item in segments) != tuple(range(len(segments))):
        raise ValueError("speaker segment ordinals must be contiguous from zero")
    return canonical_sha256(
        {
            "schema_version": VOICE_PREPARATION_SPEAKER_DIGEST_VERSION,
            "segments": [
                {
                    "ordinal": item.ordinal,
                    "segment_kind": item.segment_kind,
                    "source_start_utf16": item.source_start_utf16,
                    "source_end_utf16": item.source_end_utf16,
                    "speaker_kind": item.speaker_kind,
                    "character_id": (
                        str(item.character_id) if item.character_id is not None else None
                    ),
                    "anonymous_speaker_id": (
                        str(item.anonymous_speaker_id)
                        if item.anonymous_speaker_id is not None
                        else None
                    ),
                }
                for item in segments
            ],
        }
    )


@dataclass(frozen=True, slots=True)
class AnalyzeOnlyPreflightRequest:
    novel_id: UUID
    document_id: UUID
    expected_draft_version: int
    expected_content_hash: str
    expected_settings_version: int
    idempotency_key: str

    def __post_init__(self) -> None:
        if type(self.expected_draft_version) is not int or self.expected_draft_version < 1:
            raise ValueError("expected_draft_version must be positive")
        if (
            type(self.expected_settings_version) is not int
            or self.expected_settings_version < 1
        ):
            raise ValueError("expected_settings_version must be positive")
        _require_sha256(self.expected_content_hash, field_name="expected_content_hash")
        _require_idempotency_key(self.idempotency_key)


@dataclass(frozen=True, slots=True)
class VoicePreparationPreflight:
    novel_id: UUID
    request_id: UUID
    script_version_id: UUID
    document_id: UUID
    source_revision_id: UUID
    draft_version: int
    content_hash: str
    settings_version: int
    settings_fingerprint: str
    segments: tuple[FrozenSpeakerSegment, ...]
    speaker_digest: str

    def __post_init__(self) -> None:
        if type(self.draft_version) is not int or self.draft_version < 1:
            raise ValueError("preflight draft version must be positive")
        if type(self.settings_version) is not int or self.settings_version < 1:
            raise ValueError("preflight settings version must be positive")
        _require_sha256(self.content_hash, field_name="preflight content_hash")
        _require_sha256(
            self.settings_fingerprint, field_name="preflight settings_fingerprint"
        )
        _require_sha256(self.speaker_digest, field_name="preflight speaker_digest")
        if self.speaker_digest != speaker_summary_digest(self.segments):
            raise ValueError("preflight speaker digest differs from frozen segments")

    @property
    def chapter_character_ids(self) -> tuple[UUID, ...]:
        ordered: list[UUID] = []
        for segment in self.segments:
            if (
                segment.character_id is not None
                and segment.character_id not in ordered
            ):
                ordered.append(segment.character_id)
        return tuple(ordered)


class AnalyzeOnlyPreflightPort(Protocol):
    def analyze(self, request: AnalyzeOnlyPreflightRequest) -> VoicePreparationPreflight: ...


class AnalyzeOnlyPreflightAdapter:
    """Validate a narrow adapter around the existing analyze-only workflow."""

    def __init__(
        self,
        runner: Callable[[AnalyzeOnlyPreflightRequest], VoicePreparationPreflight],
    ) -> None:
        if not callable(runner):
            raise TypeError("analyze-only preflight runner must be callable")
        self._runner = runner

    def analyze(self, request: AnalyzeOnlyPreflightRequest) -> VoicePreparationPreflight:
        if type(request) is not AnalyzeOnlyPreflightRequest:
            raise TypeError("preflight request must use the frozen adapter contract")
        result = self._runner(request)
        if type(result) is not VoicePreparationPreflight:
            raise TypeError("preflight runner returned an incompatible result")
        if (
            result.document_id != request.document_id
            or result.novel_id != request.novel_id
            or result.draft_version != request.expected_draft_version
            or result.content_hash != request.expected_content_hash
            or result.settings_version != request.expected_settings_version
        ):
            raise NarrationCasConflict("analyze-only preflight source changed")
        return result


@dataclass(frozen=True, slots=True)
class ExistingVoiceSnapshot:
    kind: ExistingVoiceKind
    binding_version: int
    profile_id: UUID | None = None
    voice_version_id: UUID | None = None
    usable: bool = False

    def __post_init__(self) -> None:
        if type(self.kind) is not ExistingVoiceKind:
            raise ValueError("existing voice kind is outside the frozen taxonomy")
        if type(self.binding_version) is not int or self.binding_version < 0:
            raise ValueError("binding version must be non-negative")
        has_identity = self.profile_id is not None and self.voice_version_id is not None
        if (self.profile_id is None) != (self.voice_version_id is None):
            raise ValueError("existing voice identity is incomplete")
        if self.kind is ExistingVoiceKind.NONE:
            if has_identity or self.usable or self.binding_version != 0:
                raise ValueError("missing voice cannot carry binding evidence")
        elif not has_identity:
            raise ValueError("existing voice must carry profile and version identity")

    @property
    def protected(self) -> bool:
        return self.kind in {
            ExistingVoiceKind.PRIVATE,
            ExistingVoiceKind.UPLOADED,
            ExistingVoiceKind.GENERATED,
        }


@dataclass(frozen=True, slots=True)
class VoicePreparationTarget:
    character_id: UUID
    role_type: str
    active: bool
    has_saved_character_card: bool
    workspace_digest: str
    voice: ExistingVoiceSnapshot

    def __post_init__(self) -> None:
        if self.role_type not in {"main", "supporting"}:
            raise ValueError("voice preparation target role is unsupported")
        _require_sha256(self.workspace_digest, field_name="workspace_digest")


class VoicePreparationInventoryPort(Protocol):
    def load_targets(
        self,
        *,
        novel_id: UUID,
        preflight: VoicePreparationPreflight | None,
    ) -> tuple[VoicePreparationTarget, ...]: ...


@dataclass(frozen=True, slots=True)
class VoicePreparationItem:
    character_id: UUID
    position: int
    role_type: str
    chapter_speaker: bool
    expected_binding_version: int
    workspace_digest: str
    original_voice: ExistingVoiceSnapshot
    state: VoicePreparationItemState
    usable_for_narration: bool
    voice_generator_command_id: UUID | None = None
    result_profile_id: UUID | None = None
    result_voice_version_id: UUID | None = None
    applied_binding_version: int | None = None
    failure_code: str | None = None

    def __post_init__(self) -> None:
        if type(self.position) is not int or self.position < 0:
            raise ValueError("voice preparation item position must be non-negative")
        if self.expected_binding_version != self.original_voice.binding_version:
            raise ValueError("item binding CAS differs from its frozen voice")
        _require_sha256(self.workspace_digest, field_name="item workspace_digest")
        if (self.result_profile_id is None) != (self.result_voice_version_id is None):
            raise ValueError("item result voice identity is incomplete")
        if self.failure_code is not None and self.failure_code not in (
            VOICE_PREPARATION_FAILURE_CODES
        ):
            raise ValueError("item failure code is outside the frozen taxonomy")
        if type(self.usable_for_narration) is not bool:
            raise ValueError("item usability must be an exact boolean")
        if self.state is VoicePreparationItemState.PRESERVED and (
            self.usable_for_narration != self.original_voice.usable
        ):
            raise ValueError("preserved item usability differs from its frozen voice")
        if self.state in {
            VoicePreparationItemState.READY_APPLIED,
            VoicePreparationItemState.FALLBACK_OFFICIAL,
        } and not self.usable_for_narration:
            raise ValueError("applied item must be usable for narration")
        if self.state in {
            VoicePreparationItemState.PENDING,
            VoicePreparationItemState.QUEUED,
            VoicePreparationItemState.GENERATING,
            VoicePreparationItemState.FAILED,
            VoicePreparationItemState.CANCELLED,
        } and self.usable_for_narration:
            raise ValueError("unfinished or failed item cannot claim narration readiness")


@dataclass(frozen=True, slots=True)
class VoicePreparationCommand:
    command_id: UUID
    aggregate_version: int
    novel_id: UUID
    mode: str
    request_hash: str
    external_idempotency_digest: str
    actor: str
    explicit_requested_at: datetime
    document_id: UUID | None
    expected_draft_version: int | None
    expected_content_hash: str | None
    expected_settings_version: int | None
    preflight: VoicePreparationPreflight | None
    items: tuple[VoicePreparationItem, ...]
    state: VoicePreparationCommandState
    progress_current: int
    progress_total: int
    chapter_ready: bool
    background_remaining: int
    continuation_idempotency_key: str | None
    continuation_state: VoicePreparationContinuationState
    continuation_attempt: int
    continuation_fence: UUID | None
    continuation_lease_expires_at: datetime | None
    narration_request_id: UUID | None
    failure_code: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        if type(self.aggregate_version) is not int or self.aggregate_version < 1:
            raise ValueError("aggregate version must be positive")
        if self.mode != VOICE_PREPARATION_MODE:
            raise ValueError("voice preparation mode changed")
        _require_sha256(self.request_hash, field_name="request_hash")
        _require_sha256(
            self.external_idempotency_digest,
            field_name="external_idempotency_digest",
        )
        _require_aware(self.explicit_requested_at, field_name="explicit_requested_at")
        _require_aware(self.created_at, field_name="created_at")
        _require_aware(self.updated_at, field_name="updated_at")
        if not self.actor.strip():
            raise ValueError("voice preparation actor must not be blank")
        if tuple(item.position for item in self.items) != tuple(range(len(self.items))):
            raise ValueError("voice preparation item positions must be contiguous")
        if len({item.character_id for item in self.items}) != len(self.items):
            raise ValueError("voice preparation character targets must be unique")
        if self.progress_total != len(self.items):
            raise ValueError("voice preparation progress total drifted")
        if self.progress_current != sum(
            item.state in TERMINAL_ITEM_STATES for item in self.items
        ):
            raise ValueError("voice preparation progress current drifted")
        if self.background_remaining != sum(
            item.state not in TERMINAL_ITEM_STATES and not item.chapter_speaker
            for item in self.items
        ):
            raise ValueError("voice preparation background count drifted")
        if self.document_id is None:
            if any(
                value is not None
                for value in (
                    self.expected_draft_version,
                    self.expected_content_hash,
                    self.expected_settings_version,
                    self.preflight,
                    self.continuation_idempotency_key,
                    self.narration_request_id,
                )
            ) or self.continuation_state is not VoicePreparationContinuationState.NOT_APPLICABLE:
                raise ValueError("whole-book preparation cannot carry chapter continuation")
        else:
            if (
                self.preflight is None
                or self.preflight.document_id != self.document_id
                or self.preflight.novel_id != self.novel_id
                or self.continuation_idempotency_key is None
                or self.continuation_state
                is VoicePreparationContinuationState.NOT_APPLICABLE
            ):
                raise ValueError("chapter preparation lacks its preflight continuation")
            _require_idempotency_key(self.continuation_idempotency_key)
        if self.continuation_state is VoicePreparationContinuationState.CREATING:
            if self.continuation_fence is None or self.continuation_lease_expires_at is None:
                raise ValueError("creating continuation requires a fence lease")
        elif self.continuation_fence is not None or self.continuation_lease_expires_at is not None:
            raise ValueError("inactive continuation cannot retain a fence lease")
        if (
            self.continuation_state is VoicePreparationContinuationState.CREATED
        ) != (self.narration_request_id is not None):
            raise ValueError("continuation request identity differs from its state")
        if self.failure_code is not None and self.failure_code not in (
            VOICE_PREPARATION_FAILURE_CODES
        ):
            raise ValueError("command failure code is outside the frozen taxonomy")


@dataclass(frozen=True, slots=True)
class VoicePreparationCreateRequest:
    novel_id: UUID
    idempotency_key: str
    actor: str
    explicit_requested_at: datetime
    mode: str = VOICE_PREPARATION_MODE
    document_id: UUID | None = None
    expected_draft_version: int | None = None
    expected_content_hash: str | None = None
    expected_settings_version: int | None = None

    def __post_init__(self) -> None:
        _require_idempotency_key(self.idempotency_key)
        _require_aware(self.explicit_requested_at, field_name="explicit_requested_at")
        if not self.actor.strip() or self.mode != VOICE_PREPARATION_MODE:
            raise ValueError("voice preparation request changed")
        chapter_values = (
            self.expected_draft_version,
            self.expected_content_hash,
            self.expected_settings_version,
        )
        if self.document_id is None:
            if any(value is not None for value in chapter_values):
                raise ValueError("whole-book request cannot carry chapter CAS")
        elif any(value is None for value in chapter_values):
            raise ValueError("chapter request requires complete draft/settings CAS")
        else:
            assert self.expected_content_hash is not None
            _require_sha256(self.expected_content_hash, field_name="expected_content_hash")
            if type(self.expected_draft_version) is not int or self.expected_draft_version < 1:
                raise ValueError("expected_draft_version must be positive")
            if (
                type(self.expected_settings_version) is not int
                or self.expected_settings_version < 1
            ):
                raise ValueError("expected_settings_version must be positive")


@dataclass(frozen=True, slots=True)
class VoicePreparationReservation:
    command_id: UUID
    replayed: bool


class VoicePreparationRepository(Protocol):
    def reserve(self, command: VoicePreparationCommand) -> VoicePreparationReservation: ...

    def get(self, *, novel_id: UUID, command_id: UUID) -> VoicePreparationCommand: ...

    def compare_and_swap(
        self,
        *,
        expected_aggregate_version: int,
        command: VoicePreparationCommand,
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class VoiceGeneratorReserveRequest:
    novel_id: UUID
    character_id: UUID
    expected_binding_version: int
    workspace_digest: str
    idempotency_key: str

    def __post_init__(self) -> None:
        if type(self.expected_binding_version) is not int or self.expected_binding_version < 0:
            raise ValueError("VoiceGenerator expected binding version must be non-negative")
        _require_sha256(self.workspace_digest, field_name="VoiceGenerator workspace_digest")
        _require_idempotency_key(self.idempotency_key)


@dataclass(frozen=True, slots=True)
class VoiceGeneratorChild:
    command_id: UUID
    state: VoiceGeneratorChildState
    profile_id: UUID | None = None
    voice_version_id: UUID | None = None
    applied_binding_version: int | None = None
    current_binding_usable: bool = False
    runtime_unavailable: bool = False
    failure_code: str | None = None

    def __post_init__(self) -> None:
        if (self.profile_id is None) != (self.voice_version_id is None):
            raise ValueError("VoiceGenerator child result identity is incomplete")
        if self.state in {
            VoiceGeneratorChildState.READY_APPLIED,
            VoiceGeneratorChildState.READY_UNAPPLIED,
        } and self.profile_id is None:
            raise ValueError("ready VoiceGenerator child has no voice result")
        if type(self.current_binding_usable) is not bool or type(
            self.runtime_unavailable
        ) is not bool:
            raise ValueError("VoiceGenerator child flags must be exact booleans")


class VoiceGeneratorPreparationPort(Protocol):
    def reserve(self, request: VoiceGeneratorReserveRequest) -> VoiceGeneratorChild: ...

    def get(self, *, novel_id: UUID, command_id: UUID) -> VoiceGeneratorChild: ...

    def cancel(self, *, novel_id: UUID, command_id: UUID) -> None: ...


@dataclass(frozen=True, slots=True)
class OfficialFallbackRequest:
    novel_id: UUID
    character_id: UUID
    expected_binding_version: int
    workspace_digest: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class OfficialFallbackResult:
    state: OfficialFallbackState
    profile_id: UUID | None = None
    voice_version_id: UUID | None = None
    binding_version: int | None = None

    def __post_init__(self) -> None:
        if (self.profile_id is None) != (self.voice_version_id is None):
            raise ValueError("official fallback identity is incomplete")
        if self.state in {
            OfficialFallbackState.APPLIED,
            OfficialFallbackState.CURRENT_USABLE,
        } and self.profile_id is None:
            raise ValueError("usable official fallback has no voice identity")


class OfficialVoiceFallbackPort(Protocol):
    def ensure(self, request: OfficialFallbackRequest) -> OfficialFallbackResult: ...


@dataclass(frozen=True, slots=True)
class NarrationContinuationRequest:
    novel_id: UUID
    document_id: UUID
    expected_draft_version: int
    expected_content_hash: str
    expected_settings_version: int
    preflight_request_id: UUID
    preflight_script_version_id: UUID
    speaker_digest: str
    idempotency_key: str
    actor: str
    explicit_requested_at: datetime
    preparation_attempt: int
    preparation_fence: UUID

    def __post_init__(self) -> None:
        if type(self.expected_draft_version) is not int or self.expected_draft_version < 1:
            raise ValueError("continuation draft version must be positive")
        if type(self.expected_settings_version) is not int or self.expected_settings_version < 1:
            raise ValueError("continuation settings version must be positive")
        if type(self.preparation_attempt) is not int or self.preparation_attempt < 1:
            raise ValueError("continuation attempt must be positive")
        _require_sha256(self.expected_content_hash, field_name="continuation content_hash")
        _require_sha256(self.speaker_digest, field_name="continuation speaker_digest")
        _require_idempotency_key(self.idempotency_key)
        _require_aware(
            self.explicit_requested_at,
            field_name="continuation explicit_requested_at",
        )
        if not self.actor.strip():
            raise ValueError("continuation actor must not be blank")


@dataclass(frozen=True, slots=True)
class NarrationContinuationResult:
    state: ContinuationResultState
    request_id: UUID | None = None

    def __post_init__(self) -> None:
        if (self.state is ContinuationResultState.CREATED) != (
            self.request_id is not None
        ):
            raise ValueError("continuation result identity differs from its state")


class NarrationContinuationPort(Protocol):
    def create_or_replay(
        self, request: NarrationContinuationRequest
    ) -> NarrationContinuationResult: ...


def preparation_request_hash(request: VoicePreparationCreateRequest) -> str:
    return canonical_sha256(
        {
            "schema_version": "narration-voice-preparation-request/1",
            "novel_id": str(request.novel_id),
            "mode": request.mode,
            "document_id": (
                str(request.document_id) if request.document_id is not None else None
            ),
            "expected_draft_version": request.expected_draft_version,
            "expected_content_hash": request.expected_content_hash,
            "expected_settings_version": request.expected_settings_version,
            "actor": request.actor,
        }
    )


def _derived_key(prefix: str, *parts: object) -> str:
    digest = canonical_sha256([str(value) for value in parts])
    return f"{prefix}:{digest}"


def _ordered_targets(
    targets: tuple[VoicePreparationTarget, ...],
    *,
    chapter_ids: tuple[UUID, ...],
) -> tuple[VoicePreparationTarget, ...]:
    if type(targets) is not tuple:
        raise TypeError("voice preparation inventory must be a tuple")
    eligible = [
        target
        for target in targets
        if target.active and target.has_saved_character_card
    ]
    if len({target.character_id for target in eligible}) != len(eligible):
        raise InvalidNarrationState("voice preparation inventory repeats a character")
    chapter_order = {character_id: index for index, character_id in enumerate(chapter_ids)}
    return tuple(
        sorted(
            eligible,
            key=lambda target: (
                0 if target.character_id in chapter_order else 1,
                chapter_order.get(target.character_id, 0),
                0 if target.role_type == "main" else 1,
                str(target.character_id),
            ),
        )
    )


def _replace_item(
    command: VoicePreparationCommand,
    item: VoicePreparationItem,
    replacement: VoicePreparationItem,
    *,
    now: datetime,
) -> VoicePreparationCommand:
    ensure_item_transition(item.state, replacement.state)
    items = tuple(
        replacement if candidate.character_id == item.character_id else candidate
        for candidate in command.items
    )
    return _project_values(command, items=items, now=now)


def _chapter_is_ready(
    *,
    document_id: UUID | None,
    preflight: VoicePreparationPreflight | None,
    items: tuple[VoicePreparationItem, ...],
) -> bool:
    if document_id is None or preflight is None:
        return False
    chapter_ids = set(preflight.chapter_character_ids)
    chapter_items = [item for item in items if item.character_id in chapter_ids]
    return all(
        item.state
        in {
            VoicePreparationItemState.PRESERVED,
            VoicePreparationItemState.READY_APPLIED,
            VoicePreparationItemState.READY_UNAPPLIED,
            VoicePreparationItemState.FALLBACK_OFFICIAL,
        }
        and item.usable_for_narration
        for item in chapter_items
    )


def _project_command(
    command: VoicePreparationCommand,
    *,
    now: datetime,
) -> VoicePreparationCommand:
    return _project_values(command, items=command.items, now=now)


def _project_values(
    command: VoicePreparationCommand,
    *,
    items: tuple[VoicePreparationItem, ...],
    now: datetime,
) -> VoicePreparationCommand:
    """Project an aggregate and all denormalized counters in one construction."""

    progress = sum(item.state in TERMINAL_ITEM_STATES for item in items)
    background = sum(
        item.state not in TERMINAL_ITEM_STATES and not item.chapter_speaker
        for item in items
    )
    chapter_ready = _chapter_is_ready(
        document_id=command.document_id,
        preflight=command.preflight,
        items=items,
    )
    state = command.state
    failure_code = command.failure_code
    completed_at = command.completed_at
    continuation_complete = (
        command.document_id is None
        or command.continuation_state is VoicePreparationContinuationState.CREATED
    )
    chapter_terminal_but_unusable = (
        command.document_id is not None
        and progress == len(items)
        and not chapter_ready
        and command.continuation_state
        in {
            VoicePreparationContinuationState.PENDING,
            VoicePreparationContinuationState.CREATING,
        }
    )
    if state in ACTIVE_COMMAND_STATES and chapter_terminal_but_unusable:
        ensure_command_transition(state, VoicePreparationCommandState.FAILED)
        state = VoicePreparationCommandState.FAILED
        failure_code = VOICE_PREPARATION_TARGET_FAILED
        completed_at = now
    if (
        state in ACTIVE_COMMAND_STATES
        and progress == len(items)
        and continuation_complete
    ):
        failures = sum(item.state is VoicePreparationItemState.FAILED for item in items)
        warnings = any(item.state in _WARNING_ITEM_STATES for item in items)
        if items and failures == len(items):
            target = VoicePreparationCommandState.FAILED
            failure_code = VOICE_PREPARATION_TARGET_FAILED
        else:
            target = (
                VoicePreparationCommandState.READY_WITH_WARNINGS
                if warnings
                else VoicePreparationCommandState.READY
            )
        ensure_command_transition(state, target)
        state = target
        completed_at = now
    return replace(
        command,
        items=items,
        state=state,
        progress_current=progress,
        progress_total=len(items),
        chapter_ready=chapter_ready,
        background_remaining=background,
        failure_code=failure_code,
        completed_at=completed_at,
        updated_at=now,
    )


class VoicePreparationService:
    """Coordinate one durable parent command without owning persistence."""

    def __init__(
        self,
        *,
        repository: VoicePreparationRepository,
        preflight: AnalyzeOnlyPreflightPort,
        inventory: VoicePreparationInventoryPort,
        voice_generator: VoiceGeneratorPreparationPort,
        official_fallback: OfficialVoiceFallbackPort,
        continuation: NarrationContinuationPort,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        fence_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._repository = repository
        self._preflight = preflight
        self._inventory = inventory
        self._voice_generator = voice_generator
        self._official_fallback = official_fallback
        self._continuation = continuation
        self._clock = clock
        self._fence_factory = fence_factory

    def create(self, request: VoicePreparationCreateRequest) -> VoicePreparationReservation:
        if type(request) is not VoicePreparationCreateRequest:
            raise TypeError("voice preparation create request is invalid")
        request_hash = preparation_request_hash(request)
        external_digest = hashlib.sha256(request.idempotency_key.encode("utf-8")).hexdigest()
        preflight: VoicePreparationPreflight | None = None
        if request.document_id is not None:
            assert request.expected_draft_version is not None
            assert request.expected_content_hash is not None
            assert request.expected_settings_version is not None
            try:
                preflight = self._preflight.analyze(
                    AnalyzeOnlyPreflightRequest(
                        novel_id=request.novel_id,
                        document_id=request.document_id,
                        expected_draft_version=request.expected_draft_version,
                        expected_content_hash=request.expected_content_hash,
                        expected_settings_version=request.expected_settings_version,
                        idempotency_key=_derived_key(
                            "voice-preflight",
                            request.novel_id,
                            external_digest,
                            request_hash,
                        ),
                    )
                )
            except NarrationCasConflict as error:
                raise VoicePreparationError(
                    VOICE_PREPARATION_SOURCE_DRIFTED,
                    "voice preparation source changed before preflight",
                    retryable=True,
                ) from error
            except NarrationServiceError as error:
                raise VoicePreparationError(
                    VOICE_PREPARATION_PREFLIGHT_FAILED,
                    "voice preparation preflight failed",
                    retryable=True,
                ) from error
        targets = self._inventory.load_targets(
            novel_id=request.novel_id,
            preflight=preflight,
        )
        chapter_ids = preflight.chapter_character_ids if preflight is not None else ()
        ordered = _ordered_targets(targets, chapter_ids=chapter_ids)
        items = tuple(
            VoicePreparationItem(
                character_id=target.character_id,
                position=position,
                role_type=target.role_type,
                chapter_speaker=target.character_id in chapter_ids,
                expected_binding_version=target.voice.binding_version,
                workspace_digest=target.workspace_digest,
                original_voice=target.voice,
                state=(
                    VoicePreparationItemState.PRESERVED
                    if target.voice.protected
                    else VoicePreparationItemState.PENDING
                ),
                usable_for_narration=(
                    target.voice.usable if target.voice.protected else False
                ),
                result_profile_id=(
                    target.voice.profile_id if target.voice.protected else None
                ),
                result_voice_version_id=(
                    target.voice.voice_version_id if target.voice.protected else None
                ),
            )
            for position, target in enumerate(ordered)
        )
        now = _require_aware(self._clock(), field_name="clock result")
        command_id = uuid4()
        continuation_key = (
            _derived_key("voice-continue", request.novel_id, external_digest, request_hash)
            if preflight is not None
            else None
        )
        command = VoicePreparationCommand(
            command_id=command_id,
            aggregate_version=1,
            novel_id=request.novel_id,
            mode=request.mode,
            request_hash=request_hash,
            external_idempotency_digest=external_digest,
            actor=request.actor,
            explicit_requested_at=request.explicit_requested_at,
            document_id=request.document_id,
            expected_draft_version=request.expected_draft_version,
            expected_content_hash=request.expected_content_hash,
            expected_settings_version=request.expected_settings_version,
            preflight=preflight,
            items=items,
            state=VoicePreparationCommandState.RESERVED,
            progress_current=sum(item.state in TERMINAL_ITEM_STATES for item in items),
            progress_total=len(items),
            chapter_ready=False,
            background_remaining=sum(
                item.state not in TERMINAL_ITEM_STATES and not item.chapter_speaker
                for item in items
            ),
            continuation_idempotency_key=continuation_key,
            continuation_state=(
                VoicePreparationContinuationState.PENDING
                if preflight is not None
                else VoicePreparationContinuationState.NOT_APPLICABLE
            ),
            continuation_attempt=0,
            continuation_fence=None,
            continuation_lease_expires_at=None,
            narration_request_id=None,
            failure_code=None,
            created_at=now,
            updated_at=now,
        )
        command = _project_command(command, now=now)
        return self._repository.reserve(command)

    def retry(
        self,
        *,
        novel_id: UUID,
        command_id: UUID,
        refreshed_request: VoicePreparationCreateRequest,
    ) -> VoicePreparationReservation:
        """Create one replay-safe successor from server-refreshed source CAS.

        The public retry route accepts no client authority.  Its integration
        adapter reloads the current document/settings barriers and supplies
        ``refreshed_request`` here.  Repeating the retry call derives the same
        key and therefore returns the same successor command.
        """

        previous = self.get(novel_id=novel_id, command_id=command_id)
        if previous.state not in {
            VoicePreparationCommandState.FAILED,
            VoicePreparationCommandState.SUPERSEDED,
            VoicePreparationCommandState.READY_WITH_WARNINGS,
        }:
            raise InvalidNarrationState("voice preparation command is not retryable")
        if refreshed_request.novel_id != novel_id:
            raise InvalidNarrationState("voice preparation retry scope changed")
        retry_key = _derived_key("voice-prepare-retry", previous.command_id)
        return self.create(replace(refreshed_request, idempotency_key=retry_key))

    def get(self, *, novel_id: UUID, command_id: UUID) -> VoicePreparationCommand:
        return self._repository.get(novel_id=novel_id, command_id=command_id)

    def advance(self, *, novel_id: UUID, command_id: UUID) -> VoicePreparationCommand:
        """Advance at most one child/continuation operation and return truth."""

        for _attempt in range(12):
            current = self.get(novel_id=novel_id, command_id=command_id)
            if current.state in TERMINAL_COMMAND_STATES:
                return current
            now = _require_aware(self._clock(), field_name="clock result")
            if current.state is VoicePreparationCommandState.RESERVED:
                projected = replace(
                    current,
                    state=VoicePreparationCommandState.PREPARING,
                    updated_at=now,
                )
                if self._save(current, projected):
                    current = replace(
                        projected,
                        aggregate_version=current.aggregate_version + 1,
                    )
                else:
                    continue

            projected = _project_command(current, now=now)
            if projected != current:
                if not self._save(current, projected):
                    continue
                current = replace(
                    projected,
                    aggregate_version=current.aggregate_version + 1,
                )
                if current.state in TERMINAL_COMMAND_STATES:
                    return current

            if current.chapter_ready and current.continuation_state in {
                VoicePreparationContinuationState.PENDING,
                VoicePreparationContinuationState.CREATING,
            }:
                return self._advance_continuation(current, now=now)

            active = next(
                (
                    item
                    for item in current.items
                    if item.state
                    in {
                        VoicePreparationItemState.QUEUED,
                        VoicePreparationItemState.GENERATING,
                    }
                ),
                None,
            )
            if active is not None:
                return self._advance_active_item(current, active, now=now)

            pending = next(
                (
                    item
                    for item in current.items
                    if item.state is VoicePreparationItemState.PENDING
                ),
                None,
            )
            if pending is None:
                projected = _project_command(current, now=now)
                if projected == current or self._save(current, projected):
                    return projected
                continue
            queued = replace(pending, state=VoicePreparationItemState.QUEUED)
            projected = _replace_item(current, pending, queued, now=now)
            if not self._save(current, projected):
                continue
            stored = replace(
                projected,
                aggregate_version=current.aggregate_version + 1,
            )
            return self._reserve_child(stored, queued, now=now)
        raise NarrationCasConflict("voice preparation aggregate remained busy")

    def reserve_next_pending(
        self,
        *,
        novel_id: UUID,
        command_id: UUID,
    ) -> VoicePreparationCommand:
        """Reserve one additional character child without waiting for heavy work.

        Plan 55 performs request-scoped Agent analysis once, then lets the
        durable shared scheduler serialize VoiceGenerator/Nano work.  This
        narrow operation permits several already-analyzed child commands to be
        queued while preserving one external reservation per CAS step.
        """

        for _attempt in range(12):
            current = self.get(novel_id=novel_id, command_id=command_id)
            if current.state in TERMINAL_COMMAND_STATES:
                return current
            now = _require_aware(self._clock(), field_name="clock result")
            if current.state is VoicePreparationCommandState.RESERVED:
                projected = replace(
                    current,
                    state=VoicePreparationCommandState.PREPARING,
                    updated_at=now,
                )
                if not self._save(current, projected):
                    continue
                current = replace(
                    projected,
                    aggregate_version=current.aggregate_version + 1,
                )
            pending = next(
                (
                    item
                    for item in current.items
                    if item.state is VoicePreparationItemState.PENDING
                ),
                None,
            )
            if pending is None:
                return current
            queued = replace(pending, state=VoicePreparationItemState.QUEUED)
            projected = _replace_item(current, pending, queued, now=now)
            if not self._save(current, projected):
                continue
            stored = replace(
                projected,
                aggregate_version=current.aggregate_version + 1,
            )
            return self._reserve_child(stored, queued, now=now)
        raise NarrationCasConflict("voice preparation reservation remained busy")

    def cancel(self, *, novel_id: UUID, command_id: UUID) -> VoicePreparationCommand:
        for _attempt in range(8):
            current = self.get(novel_id=novel_id, command_id=command_id)
            if current.state is VoicePreparationCommandState.CANCELLED:
                return current
            if current.state not in ACTIVE_COMMAND_STATES:
                raise InvalidNarrationState("voice preparation command is not cancellable")
            now = _require_aware(self._clock(), field_name="clock result")
            child_ids = tuple(
                item.voice_generator_command_id
                for item in current.items
                if item.voice_generator_command_id is not None
                and item.state
                in {
                    VoicePreparationItemState.QUEUED,
                    VoicePreparationItemState.GENERATING,
                }
            )
            items = tuple(
                replace(item, state=VoicePreparationItemState.CANCELLED)
                if item.state
                in {
                    VoicePreparationItemState.PENDING,
                    VoicePreparationItemState.QUEUED,
                    VoicePreparationItemState.GENERATING,
                }
                else item
                for item in current.items
            )
            continuation_state = current.continuation_state
            if continuation_state is not VoicePreparationContinuationState.CREATED:
                continuation_state = (
                    VoicePreparationContinuationState.CANCELLED
                    if current.document_id is not None
                    else VoicePreparationContinuationState.NOT_APPLICABLE
                )
            projected = replace(
                current,
                state=VoicePreparationCommandState.CANCELLED,
                items=items,
                progress_current=sum(item.state in TERMINAL_ITEM_STATES for item in items),
                background_remaining=0,
                continuation_state=continuation_state,
                continuation_fence=None,
                continuation_lease_expires_at=None,
                failure_code=None,
                completed_at=now,
                updated_at=now,
            )
            if not self._save(current, projected):
                continue
            for child_id in child_ids:
                try:
                    self._voice_generator.cancel(
                        novel_id=novel_id,
                        command_id=child_id,
                    )
                except NarrationServiceError:
                    # The parent cancellation is already authoritative.  Child
                    # cleanup is idempotent and the reconciler will retry it.
                    pass
            return projected
        raise NarrationCasConflict("voice preparation cancellation remained busy")

    def _reserve_child(
        self,
        command: VoicePreparationCommand,
        item: VoicePreparationItem,
        *,
        now: datetime,
    ) -> VoicePreparationCommand:
        child = self._voice_generator.reserve(
            VoiceGeneratorReserveRequest(
                novel_id=command.novel_id,
                character_id=item.character_id,
                expected_binding_version=item.expected_binding_version,
                workspace_digest=item.workspace_digest,
                idempotency_key=_derived_key(
                    "voice-prepare-character", command.command_id, item.character_id
                ),
            )
        )
        return self._publish_child(command, item, child, now=now)

    def _advance_active_item(
        self,
        command: VoicePreparationCommand,
        item: VoicePreparationItem,
        *,
        now: datetime,
    ) -> VoicePreparationCommand:
        if item.voice_generator_command_id is None:
            return self._reserve_child(command, item, now=now)
        child = self._voice_generator.get(
            novel_id=command.novel_id,
            command_id=item.voice_generator_command_id,
        )
        return self._publish_child(command, item, child, now=now)

    def _publish_child(
        self,
        command: VoicePreparationCommand,
        item: VoicePreparationItem,
        child: VoiceGeneratorChild,
        *,
        now: datetime,
    ) -> VoicePreparationCommand:
        if (
            item.voice_generator_command_id is not None
            and item.voice_generator_command_id != child.command_id
        ):
            raise IdempotencyConflict("voice preparation child command changed")
        if child.state is VoiceGeneratorChildState.ACTIVE:
            target = VoicePreparationItemState.GENERATING
            replacement = replace(
                item,
                state=target,
                usable_for_narration=False,
                voice_generator_command_id=child.command_id,
            )
        elif child.state is VoiceGeneratorChildState.READY_APPLIED:
            replacement = replace(
                item,
                state=VoicePreparationItemState.READY_APPLIED,
                voice_generator_command_id=child.command_id,
                result_profile_id=child.profile_id,
                result_voice_version_id=child.voice_version_id,
                applied_binding_version=child.applied_binding_version,
                usable_for_narration=True,
                failure_code=None,
            )
        elif child.state is VoiceGeneratorChildState.READY_UNAPPLIED:
            replacement = replace(
                item,
                state=VoicePreparationItemState.READY_UNAPPLIED,
                voice_generator_command_id=child.command_id,
                result_profile_id=child.profile_id,
                result_voice_version_id=child.voice_version_id,
                usable_for_narration=child.current_binding_usable,
                failure_code=VOICE_PREPARATION_BINDING_DRIFTED,
            )
        else:
            return self._fallback_after_child(command, item, child, now=now)
        projected = _replace_item(command, item, replacement, now=now)
        return self._save_latest(command, projected)

    def _fallback_after_child(
        self,
        command: VoicePreparationCommand,
        item: VoicePreparationItem,
        child: VoiceGeneratorChild,
        *,
        now: datetime,
    ) -> VoicePreparationCommand:
        if item.original_voice.kind is ExistingVoiceKind.OFFICIAL and item.original_voice.usable:
            result = OfficialFallbackResult(
                state=OfficialFallbackState.CURRENT_USABLE,
                profile_id=item.original_voice.profile_id,
                voice_version_id=item.original_voice.voice_version_id,
                binding_version=item.original_voice.binding_version,
            )
        else:
            result = self._official_fallback.ensure(
                OfficialFallbackRequest(
                    novel_id=command.novel_id,
                    character_id=item.character_id,
                    expected_binding_version=item.expected_binding_version,
                    workspace_digest=item.workspace_digest,
                    idempotency_key=_derived_key(
                        "voice-prepare-fallback", command.command_id, item.character_id
                    ),
                )
            )
        if result.state in {
            OfficialFallbackState.APPLIED,
            OfficialFallbackState.CURRENT_USABLE,
        }:
            replacement = replace(
                item,
                state=VoicePreparationItemState.FALLBACK_OFFICIAL,
                voice_generator_command_id=child.command_id,
                result_profile_id=result.profile_id,
                result_voice_version_id=result.voice_version_id,
                applied_binding_version=result.binding_version,
                usable_for_narration=True,
                failure_code=VOICE_PREPARATION_TARGET_FAILED,
            )
        else:
            failure = (
                VOICE_PREPARATION_BINDING_DRIFTED
                if result.state is OfficialFallbackState.CAS_DRIFTED
                else (
                    VOICE_PREPARATION_HEAVY_RUNTIME_UNAVAILABLE
                    if child.runtime_unavailable
                    else VOICE_PREPARATION_TARGET_FAILED
                )
            )
            replacement = replace(
                item,
                state=VoicePreparationItemState.FAILED,
                voice_generator_command_id=child.command_id,
                usable_for_narration=False,
                failure_code=failure,
            )
        projected = _replace_item(command, item, replacement, now=now)
        return self._save_latest(command, projected)

    def _advance_continuation(
        self,
        command: VoicePreparationCommand,
        *,
        now: datetime,
    ) -> VoicePreparationCommand:
        if command.preflight is None or command.document_id is None:
            raise InvalidNarrationState("chapter-ready command lost its preflight")
        current = command
        if current.continuation_state is VoicePreparationContinuationState.CREATING:
            lease = current.continuation_lease_expires_at
            if lease is not None and lease > now:
                return current
            pending = replace(
                current,
                continuation_state=VoicePreparationContinuationState.PENDING,
                continuation_fence=None,
                continuation_lease_expires_at=None,
                updated_at=now,
            )
            current = self._save_latest(current, pending)
        fence = self._fence_factory()
        claimed = replace(
            current,
            continuation_state=VoicePreparationContinuationState.CREATING,
            continuation_attempt=current.continuation_attempt + 1,
            continuation_fence=fence,
            continuation_lease_expires_at=now + VOICE_PREPARATION_CONTINUATION_LEASE,
            updated_at=now,
        )
        claimed = self._save_latest(current, claimed)
        assert claimed.expected_draft_version is not None
        assert claimed.expected_content_hash is not None
        assert claimed.expected_settings_version is not None
        assert claimed.continuation_idempotency_key is not None
        outcome = self._continuation.create_or_replay(
            NarrationContinuationRequest(
                novel_id=claimed.novel_id,
                document_id=claimed.document_id,
                expected_draft_version=claimed.expected_draft_version,
                expected_content_hash=claimed.expected_content_hash,
                expected_settings_version=claimed.expected_settings_version,
                preflight_request_id=claimed.preflight.request_id,
                preflight_script_version_id=claimed.preflight.script_version_id,
                speaker_digest=claimed.preflight.speaker_digest,
                idempotency_key=claimed.continuation_idempotency_key,
                actor=claimed.actor,
                explicit_requested_at=claimed.explicit_requested_at,
                preparation_attempt=claimed.continuation_attempt,
                preparation_fence=fence,
            )
        )
        latest = self.get(novel_id=claimed.novel_id, command_id=claimed.command_id)
        if (
            latest.continuation_state is not VoicePreparationContinuationState.CREATING
            or latest.continuation_fence != fence
            or latest.continuation_attempt != claimed.continuation_attempt
        ):
            return latest
        finished_at = _require_aware(self._clock(), field_name="clock result")
        if outcome.state is ContinuationResultState.CREATED:
            if latest.narration_request_id not in {None, outcome.request_id}:
                raise IdempotencyConflict("continuation Narration Request changed")
            projected = replace(
                latest,
                continuation_state=VoicePreparationContinuationState.CREATED,
                continuation_fence=None,
                continuation_lease_expires_at=None,
                narration_request_id=outcome.request_id,
                updated_at=finished_at,
            )
        elif outcome.state is ContinuationResultState.SOURCE_DRIFTED:
            ensure_command_transition(latest.state, VoicePreparationCommandState.SUPERSEDED)
            projected = replace(
                latest,
                state=VoicePreparationCommandState.SUPERSEDED,
                continuation_state=VoicePreparationContinuationState.SUPERSEDED,
                continuation_fence=None,
                continuation_lease_expires_at=None,
                failure_code=VOICE_PREPARATION_SOURCE_DRIFTED,
                completed_at=finished_at,
                updated_at=finished_at,
            )
        else:
            ensure_command_transition(latest.state, VoicePreparationCommandState.FAILED)
            projected = replace(
                latest,
                state=VoicePreparationCommandState.FAILED,
                continuation_state=VoicePreparationContinuationState.FAILED,
                continuation_fence=None,
                continuation_lease_expires_at=None,
                failure_code=VOICE_PREPARATION_CONTINUATION_CONFLICT,
                completed_at=finished_at,
                updated_at=finished_at,
            )
        return self._save_latest(latest, projected)

    def _save(
        self,
        current: VoicePreparationCommand,
        projected: VoicePreparationCommand,
    ) -> bool:
        if projected.aggregate_version != current.aggregate_version:
            raise ValueError("projection changed aggregate version directly")
        stored = replace(projected, aggregate_version=current.aggregate_version + 1)
        return self._repository.compare_and_swap(
            expected_aggregate_version=current.aggregate_version,
            command=stored,
        )

    def _save_latest(
        self,
        current: VoicePreparationCommand,
        projected: VoicePreparationCommand,
    ) -> VoicePreparationCommand:
        if not self._save(current, projected):
            return self.get(novel_id=current.novel_id, command_id=current.command_id)
        return replace(projected, aggregate_version=current.aggregate_version + 1)


__all__ = [
    "ACTIVE_COMMAND_STATES",
    "TERMINAL_COMMAND_STATES",
    "TERMINAL_ITEM_STATES",
    "VOICE_PREPARATION_BINDING_DRIFTED",
    "VOICE_PREPARATION_CONTRACT_VERSION",
    "VOICE_PREPARATION_CONTINUATION_CONFLICT",
    "VOICE_PREPARATION_CONTINUATION_LEASE",
    "VOICE_PREPARATION_FAILURE_CODES",
    "VOICE_PREPARATION_HEAVY_RUNTIME_UNAVAILABLE",
    "VOICE_PREPARATION_JOB_KIND",
    "VOICE_PREPARATION_MODE",
    "VOICE_PREPARATION_NOT_READY",
    "VOICE_PREPARATION_PREFLIGHT_FAILED",
    "VOICE_PREPARATION_SOURCE_DRIFTED",
    "VOICE_PREPARATION_SPEAKER_DIGEST_VERSION",
    "VOICE_PREPARATION_TARGET_FAILED",
    "VOICE_PREPARATION_WORKSPACE_DRIFTED",
    "AnalyzeOnlyPreflightAdapter",
    "AnalyzeOnlyPreflightPort",
    "AnalyzeOnlyPreflightRequest",
    "ContinuationResultState",
    "ExistingVoiceKind",
    "ExistingVoiceSnapshot",
    "FrozenSpeakerSegment",
    "NarrationContinuationPort",
    "NarrationContinuationRequest",
    "NarrationContinuationResult",
    "OfficialFallbackRequest",
    "OfficialFallbackResult",
    "OfficialFallbackState",
    "OfficialVoiceFallbackPort",
    "VoiceGeneratorChild",
    "VoiceGeneratorChildState",
    "VoiceGeneratorPreparationPort",
    "VoiceGeneratorReserveRequest",
    "VoicePreparationCommand",
    "VoicePreparationCommandState",
    "VoicePreparationContinuationState",
    "VoicePreparationCreateRequest",
    "VoicePreparationError",
    "VoicePreparationInventoryPort",
    "VoicePreparationItem",
    "VoicePreparationItemState",
    "VoicePreparationPreflight",
    "VoicePreparationRepository",
    "VoicePreparationReservation",
    "VoicePreparationService",
    "VoicePreparationTarget",
    "ensure_command_transition",
    "ensure_item_transition",
    "preparation_request_hash",
    "speaker_summary_digest",
]
