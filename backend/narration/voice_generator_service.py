"""VoiceGenerator workflow contracts and durable command service.

The small state helpers remain dependency-free.  The SQLAlchemy service below
owns only short database transactions; character analysis and both model calls
are deliberately performed by the API/worker outside those transactions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from types import MappingProxyType
from typing import Callable, Mapping, Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import (
    CharacterVoiceBinding,
    NovelCharacter,
    VoiceDesignDraft,
    VoiceGeneratorCommand,
    VoiceProfile,
    VoiceProfileVersion,
)
from . import schemas as wire
from .character_voice_matching import CharacterVoiceBrief
from .contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID, NarrationRequestScope
from .digest_keyring import DigestKeyring, private_text_digest
from .jobs import enqueue_job, request_cancel
from .privacy import get_character_voice_binding, put_character_voice_binding
from .services import (
    IdempotencyConflict,
    InvalidNarrationState,
    NarrationCasConflict,
    NarrationNotFound,
    NarrationScopeMismatch,
    SqlAlchemyNarrationStore,
    canonical_payload,
    canonical_sha256,
    require_local_novel,
)
from .voices import voice_profile_resource

from .voice_generator_runtime import (
    EXPECTED_AUDIO_PARAMETERS,
    EXPECTED_RUNTIME_IDENTITY,
    HostGenerationReceipt,
    HostGenerationStatus,
    NativeVoiceGeneratorHostClient,
    VoiceGeneratorAudioMetrics,
    VoiceGeneratorAudioResult,
    VoiceGeneratorHostHealth,
    VoiceGeneratorHostRequest,
    VoiceGeneratorRuntimeError,
)


class VoiceGeneratorCommandState(str, Enum):
    QUEUED = "queued"
    ANALYZING_CHARACTER = "analyzing_character"
    WAITING_FOR_HEAVY_RUNTIME = "waiting_for_heavy_runtime"
    GENERATING_VOICE = "generating_voice"
    UNLOADING_VOICE_GENERATOR = "unloading_voice_generator"
    VALIDATING_WITH_NANO = "validating_with_nano"
    READY_APPLIED = "ready_applied"
    READY_UNAPPLIED = "ready_unapplied"
    FAILED_CHARACTER_ANALYSIS = "failed_character_analysis"
    FAILED_RUNTIME_UNAVAILABLE = "failed_runtime_unavailable"
    FAILED_MEMORY_SAFETY = "failed_memory_safety"
    FAILED_GENERATION = "failed_generation"
    FAILED_AUDIO_VALIDATION = "failed_audio_validation"
    FAILED_NANO_VALIDATION = "failed_nano_validation"
    FAILED_STORAGE = "failed_storage"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


ACTIVE_STATES = frozenset(
    {
        VoiceGeneratorCommandState.QUEUED,
        VoiceGeneratorCommandState.ANALYZING_CHARACTER,
        VoiceGeneratorCommandState.WAITING_FOR_HEAVY_RUNTIME,
        VoiceGeneratorCommandState.GENERATING_VOICE,
        VoiceGeneratorCommandState.UNLOADING_VOICE_GENERATOR,
        VoiceGeneratorCommandState.VALIDATING_WITH_NANO,
    }
)
FAILURE_STATES = frozenset(
    state for state in VoiceGeneratorCommandState if state.value.startswith("failed_")
)
TERMINAL_STATES = frozenset(set(VoiceGeneratorCommandState) - set(ACTIVE_STATES))
RETRYABLE_STATES = frozenset(
    {
        VoiceGeneratorCommandState.FAILED_CHARACTER_ANALYSIS,
        VoiceGeneratorCommandState.FAILED_RUNTIME_UNAVAILABLE,
        VoiceGeneratorCommandState.FAILED_MEMORY_SAFETY,
        VoiceGeneratorCommandState.FAILED_GENERATION,
        VoiceGeneratorCommandState.FAILED_AUDIO_VALIDATION,
        VoiceGeneratorCommandState.FAILED_NANO_VALIDATION,
        VoiceGeneratorCommandState.FAILED_STORAGE,
        VoiceGeneratorCommandState.SUPERSEDED,
    }
)

_PROGRESS = {
    VoiceGeneratorCommandState.QUEUED: 0,
    VoiceGeneratorCommandState.ANALYZING_CHARACTER: 1,
    VoiceGeneratorCommandState.WAITING_FOR_HEAVY_RUNTIME: 2,
    VoiceGeneratorCommandState.GENERATING_VOICE: 3,
    VoiceGeneratorCommandState.UNLOADING_VOICE_GENERATOR: 4,
    VoiceGeneratorCommandState.VALIDATING_WITH_NANO: 5,
    **{state: 6 for state in TERMINAL_STATES},
}

_FORWARD = {
    VoiceGeneratorCommandState.QUEUED: {VoiceGeneratorCommandState.ANALYZING_CHARACTER},
    VoiceGeneratorCommandState.ANALYZING_CHARACTER: {
        VoiceGeneratorCommandState.WAITING_FOR_HEAVY_RUNTIME,
        VoiceGeneratorCommandState.FAILED_CHARACTER_ANALYSIS,
    },
    VoiceGeneratorCommandState.WAITING_FOR_HEAVY_RUNTIME: {
        VoiceGeneratorCommandState.GENERATING_VOICE,
        VoiceGeneratorCommandState.FAILED_RUNTIME_UNAVAILABLE,
        VoiceGeneratorCommandState.FAILED_MEMORY_SAFETY,
    },
    VoiceGeneratorCommandState.GENERATING_VOICE: {
        VoiceGeneratorCommandState.UNLOADING_VOICE_GENERATOR,
        VoiceGeneratorCommandState.FAILED_RUNTIME_UNAVAILABLE,
        VoiceGeneratorCommandState.FAILED_MEMORY_SAFETY,
        VoiceGeneratorCommandState.FAILED_GENERATION,
        VoiceGeneratorCommandState.FAILED_AUDIO_VALIDATION,
    },
    VoiceGeneratorCommandState.UNLOADING_VOICE_GENERATOR: {
        VoiceGeneratorCommandState.VALIDATING_WITH_NANO,
        VoiceGeneratorCommandState.FAILED_MEMORY_SAFETY,
        VoiceGeneratorCommandState.FAILED_AUDIO_VALIDATION,
        VoiceGeneratorCommandState.FAILED_STORAGE,
    },
    VoiceGeneratorCommandState.VALIDATING_WITH_NANO: {
        VoiceGeneratorCommandState.READY_APPLIED,
        VoiceGeneratorCommandState.READY_UNAPPLIED,
        VoiceGeneratorCommandState.FAILED_NANO_VALIDATION,
        VoiceGeneratorCommandState.FAILED_STORAGE,
    },
    VoiceGeneratorCommandState.READY_UNAPPLIED: {
        VoiceGeneratorCommandState.READY_APPLIED,
    },
}


@dataclass(frozen=True, slots=True)
class VoiceGeneratorStateView:
    state: VoiceGeneratorCommandState
    progress_current: int
    progress_total: int
    cancellable: bool
    retryable: bool
    terminal: bool


def state_view(state: VoiceGeneratorCommandState) -> VoiceGeneratorStateView:
    if type(state) is not VoiceGeneratorCommandState:
        raise ValueError("VoiceGenerator state is outside the frozen taxonomy")
    return VoiceGeneratorStateView(
        state=state,
        progress_current=_PROGRESS[state],
        progress_total=6,
        cancellable=state in ACTIVE_STATES,
        retryable=state in RETRYABLE_STATES,
        terminal=state in TERMINAL_STATES,
    )


def ensure_command_transition(
    current: VoiceGeneratorCommandState,
    target: VoiceGeneratorCommandState,
) -> VoiceGeneratorCommandState:
    if current is target:
        return target
    if current in ACTIVE_STATES and target in {
        VoiceGeneratorCommandState.CANCELLED,
        VoiceGeneratorCommandState.SUPERSEDED,
    }:
        return target
    if target not in _FORWARD.get(current, set()):
        raise ValueError(f"invalid VoiceGenerator state transition: {current.value}->{target.value}")
    return target


class VoiceGeneratorRuntimePort(Protocol):
    async def health(self) -> VoiceGeneratorHostHealth: ...

    async def create(self, request: VoiceGeneratorHostRequest) -> HostGenerationReceipt: ...

    async def get(self, request: VoiceGeneratorHostRequest) -> HostGenerationReceipt: ...

    async def cancel(self, request: VoiceGeneratorHostRequest) -> HostGenerationReceipt: ...

    async def download_audio(
        self,
        request: VoiceGeneratorHostRequest,
        receipt: HostGenerationReceipt,
    ) -> VoiceGeneratorAudioResult: ...


@dataclass(frozen=True, slots=True)
class ValidatedVoiceGeneratorResult:
    request_id: UUID
    request_digest: str
    runtime_fingerprint: str
    instruction_digest: str
    token_digest: str
    audio_digest: str
    audio_bytes: bytes = field(repr=False)
    audio_metrics: VoiceGeneratorAudioMetrics
    memory_summary: Mapping[str, int | bool]
    started_at: datetime
    completed_at: datetime
    result_classification: str = "success"
    exit_reason_code: str = "COMPLETED"

    def __post_init__(self) -> None:
        if self.result_classification != "success" or self.exit_reason_code != "COMPLETED":
            raise ValueError("validated VoiceGenerator result must be successful")
        object.__setattr__(self, "memory_summary", MappingProxyType(dict(self.memory_summary)))


def validate_runtime_completion(
    request: VoiceGeneratorHostRequest,
    receipt: HostGenerationReceipt,
    audio: VoiceGeneratorAudioResult,
) -> ValidatedVoiceGeneratorResult:
    """Close the request/receipt/audio identity before any storage write."""

    if (
        receipt.status is not HostGenerationStatus.COMPLETED
        or receipt.request_id != request.request_id
        or receipt.request_digest != request.request_digest
        or receipt.token_sha256 is None
        or receipt.audio_sha256 is None
        or receipt.memory_summary is None
        or audio.request_id != request.request_id
        or audio.audio_sha256 != receipt.audio_sha256
        or audio.runtime_fingerprint != receipt.runtime_fingerprint
        or audio.metrics.byte_size != receipt.audio_size_bytes
    ):
        raise VoiceGeneratorRuntimeError(
            "RUNTIME_RESULT_IDENTITY_MISMATCH",
            "VoiceGenerator runtime result identity is inconsistent",
        )
    return ValidatedVoiceGeneratorResult(
        request_id=request.request_id,
        request_digest=request.request_digest,
        runtime_fingerprint=receipt.runtime_fingerprint,
        instruction_digest=request.instruction_digest,
        token_digest=receipt.token_sha256,
        audio_digest=audio.audio_sha256,
        audio_bytes=audio.audio_bytes,
        audio_metrics=audio.metrics,
        memory_summary=receipt.memory_summary.public_payload(),
        started_at=receipt.started_at,
        completed_at=receipt.completed_at,
    )


_MEMORY_FAILURE_CODES = frozenset(
    {
        "MEMORY_BASELINE_CRITICAL",
        "MEMORY_PRESSURE_CRITICAL",
        "MEMORY_RECOVERY_FAILED",
        "NANO_RESIDENCY_OVERLAP",
        "STAGE_PROCESS_OVERLAP",
        "WATCHDOG_MEMORY_SAFETY",
    }
)
_AUDIO_FAILURE_CODES = frozenset(
    code
    for code in (
        "AUDIO_EVIDENCE_MISMATCH",
        "AUDIO_FORMAT_DRIFT",
        "AUDIO_FORMAT_INVALID",
        "AUDIO_FRAME_COUNT_MISMATCH",
        "AUDIO_MACHINE_VALIDATION_FAILED",
        "AUDIO_SIZE_INVALID",
        "AUDIO_SIZE_MISMATCH",
    )
)
_RUNTIME_FAILURE_CODES = frozenset(
    {
        "HOST_UNREACHABLE",
        "HOST_NOT_READY",
        "PROTOCOL_MISMATCH",
        "RUNTIME_IDENTITY_MISMATCH",
        "TOKEN_FILE_INVALID",
        "TOKEN_CONFIGURATION_INVALID",
    }
)


def terminal_state_for_runtime_error(
    error: VoiceGeneratorRuntimeError,
) -> VoiceGeneratorCommandState:
    if error.code == "USER_CANCELLED":
        return VoiceGeneratorCommandState.CANCELLED
    if error.code in _MEMORY_FAILURE_CODES:
        return VoiceGeneratorCommandState.FAILED_MEMORY_SAFETY
    if error.code in _AUDIO_FAILURE_CODES or error.code.startswith("AUDIO_"):
        return VoiceGeneratorCommandState.FAILED_AUDIO_VALIDATION
    if error.code in {
        "GENERATION_EMPTY",
        "GENERATION_INCOMPLETE",
        "TOKEN_CONTRACT_MISMATCH",
    }:
        return VoiceGeneratorCommandState.FAILED_GENERATION
    if error.code in _RUNTIME_FAILURE_CODES or error.code.startswith(("HOST_", "TOKEN_", "PROTOCOL_", "RUNTIME_")):
        return VoiceGeneratorCommandState.FAILED_RUNTIME_UNAVAILABLE
    return VoiceGeneratorCommandState.FAILED_GENERATION


def command_state_for_host_receipt(
    receipt: HostGenerationReceipt,
) -> VoiceGeneratorCommandState:
    """Project the private host state into the durable product state machine."""

    if receipt.status in {
        HostGenerationStatus.ACCEPTED,
        HostGenerationStatus.GENERATING,
    }:
        return VoiceGeneratorCommandState.GENERATING_VOICE
    if receipt.status is HostGenerationStatus.UNLOADING:
        return VoiceGeneratorCommandState.UNLOADING_VOICE_GENERATOR
    if receipt.status is HostGenerationStatus.COMPLETED:
        return VoiceGeneratorCommandState.VALIDATING_WITH_NANO
    if receipt.status is HostGenerationStatus.CANCELLED:
        return VoiceGeneratorCommandState.CANCELLED
    if receipt.failure_code is None:
        raise VoiceGeneratorRuntimeError(
            "GENERATION_RECEIPT_INVALID",
            "VoiceGenerator failure receipt has no failure code",
        )
    return terminal_state_for_runtime_error(
        VoiceGeneratorRuntimeError(
            receipt.failure_code,
            "VoiceGenerator host failed",
            retryable=receipt.retryable,
        )
    )


def runtime_port(client: NativeVoiceGeneratorHostClient) -> VoiceGeneratorRuntimePort:
    """Narrow typing helper used by the future durable command processor."""

    return client


VOICE_GENERATOR_JOB_KIND = "narration.voice_generate"
VOICE_GENERATOR_RESOURCE_CLASS = "moss-nano"
VOICE_DESIGN_INSTRUCTION_PURPOSE = "voice-generator-instruction"


@dataclass(frozen=True, slots=True)
class VoiceGeneratorReservation:
    command_id: UUID
    replayed: bool


@dataclass(frozen=True, slots=True)
class VoiceGeneratorAnalysis:
    character_version: int
    character_catalog_version: int
    workspace_digest: str
    brief: CharacterVoiceBrief
    instruction: str = field(repr=False)
    model_evidence: Mapping[str, object]
    language: str
    seed: int


SessionFactory = Callable[[], Session]


def _transaction(factory: SessionFactory, operation):
    with factory() as session:
        try:
            value = operation(session)
            session.commit()
            return value
        except BaseException:
            session.rollback()
            raise


def _current_binding_version(session: Session, character_id: UUID) -> int:
    row = session.scalar(
        select(CharacterVoiceBinding)
        .where(CharacterVoiceBinding.character_id == character_id)
        .with_for_update()
    )
    return 0 if row is None else row.version


def _required_command(
    session: Session,
    *,
    novel_id: UUID,
    command_id: UUID,
    for_update: bool,
) -> VoiceGeneratorCommand:
    statement = select(VoiceGeneratorCommand).where(
        VoiceGeneratorCommand.id == command_id,
        VoiceGeneratorCommand.novel_id == novel_id,
        VoiceGeneratorCommand.owner_id == LOCAL_OWNER_ID,
        VoiceGeneratorCommand.workspace_id == LOCAL_WORKSPACE_ID,
    )
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    row = session.scalar(statement)
    if row is None:
        raise NarrationNotFound("VoiceGenerator command not found")
    return row


def _mark_terminal(
    row: VoiceGeneratorCommand,
    *,
    state: VoiceGeneratorCommandState,
    now: datetime,
    failure_code: str | None = None,
) -> None:
    current = VoiceGeneratorCommandState(row.state)
    ensure_command_transition(current, state)
    row.state = state.value
    row.progress_current = 6
    row.failure_code = failure_code
    row.completed_at = now
    row.updated_at = now


class SqlAlchemyVoiceGeneratorService:
    """Durable, idempotent authority for the public one-click workflow."""

    def __init__(self, session_factory: SessionFactory, *, digest_keyring: DigestKeyring):
        if type(digest_keyring) is not DigestKeyring:
            raise TypeError("VoiceGenerator service requires DigestKeyring")
        self._session_factory = session_factory
        self._digest_keyring = digest_keyring
        self._scope = NarrationRequestScope.fixed_local()

    def reserve(
        self,
        *,
        novel_id: UUID,
        character_id: UUID,
        expected_binding_version: int,
        idempotency_key: str,
        request_hash: str,
    ) -> VoiceGeneratorReservation:
        def operation(session: Session) -> VoiceGeneratorReservation:
            store = SqlAlchemyNarrationStore(session)
            require_local_novel(store, novel_id, for_update=True)
            character = session.scalar(
                select(NovelCharacter)
                .where(
                    NovelCharacter.id == character_id,
                    NovelCharacter.novel_id == novel_id,
                )
                .with_for_update()
            )
            if character is None:
                raise NarrationNotFound("character not found")
            if character.lifecycle_state != "active":
                raise InvalidNarrationState("archived character cannot generate a voice")
            replay = session.scalar(
                select(VoiceGeneratorCommand)
                .where(
                    VoiceGeneratorCommand.owner_id == LOCAL_OWNER_ID,
                    VoiceGeneratorCommand.workspace_id == LOCAL_WORKSPACE_ID,
                    VoiceGeneratorCommand.idempotency_key == idempotency_key,
                )
                .with_for_update()
            )
            if replay is not None:
                if (
                    replay.novel_id != novel_id
                    or replay.character_id != character_id
                    or replay.request_hash != request_hash
                    or replay.expected_binding_version != expected_binding_version
                ):
                    raise IdempotencyConflict("VoiceGenerator idempotency key was reused")
                return VoiceGeneratorReservation(command_id=replay.id, replayed=True)
            if _current_binding_version(session, character_id) != expected_binding_version:
                raise NarrationCasConflict("character voice binding changed")
            active = session.scalar(
                select(VoiceGeneratorCommand.id).where(
                    VoiceGeneratorCommand.novel_id == novel_id,
                    VoiceGeneratorCommand.character_id == character_id,
                    VoiceGeneratorCommand.state.in_(tuple(state.value for state in ACTIVE_STATES)),
                )
            )
            if active is not None:
                raise InvalidNarrationState("character already has an active VoiceGenerator command")
            now = datetime.now(UTC)
            row = VoiceGeneratorCommand(
                id=uuid4(),
                owner_id=LOCAL_OWNER_ID,
                workspace_id=LOCAL_WORKSPACE_ID,
                novel_id=novel_id,
                character_id=character_id,
                host_request_id=uuid4(),
                expected_binding_version=expected_binding_version,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                state=VoiceGeneratorCommandState.QUEUED.value,
                progress_current=0,
                progress_total=6,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            try:
                session.flush()
            except IntegrityError as error:
                raise InvalidNarrationState(
                    "character already has an active VoiceGenerator command"
                ) from error
            return VoiceGeneratorReservation(command_id=row.id, replayed=False)

        return _transaction(self._session_factory, operation)

    def begin_analysis(self, *, novel_id: UUID, command_id: UUID) -> bool:
        def operation(session: Session) -> bool:
            row = _required_command(
                session, novel_id=novel_id, command_id=command_id, for_update=True
            )
            if row.state != VoiceGeneratorCommandState.QUEUED.value:
                return False
            now = datetime.now(UTC)
            row.state = VoiceGeneratorCommandState.ANALYZING_CHARACTER.value
            row.progress_current = 1
            row.started_at = now
            row.updated_at = now
            session.flush()
            return True

        return _transaction(self._session_factory, operation)

    def expire_stale_analysis(
        self,
        *,
        novel_id: UUID,
        command_id: UUID,
        older_than: datetime,
    ) -> bool:
        """Fence an Agent analysis abandoned by a crashed request worker.

        The late response cannot publish because ``finish_analysis`` only
        accepts ``analyzing_character``.  A parent preparation command can
        therefore fall back safely instead of remaining active forever.
        """

        def operation(session: Session) -> bool:
            row = _required_command(
                session, novel_id=novel_id, command_id=command_id, for_update=True
            )
            if (
                row.state != VoiceGeneratorCommandState.ANALYZING_CHARACTER.value
                or row.started_at is None
                or row.started_at > older_than
            ):
                return False
            _mark_terminal(
                row,
                state=VoiceGeneratorCommandState.FAILED_CHARACTER_ANALYSIS,
                failure_code="CHARACTER_VOICE_MODEL_UNAVAILABLE",
                now=datetime.now(UTC),
            )
            session.flush()
            return True

        return _transaction(self._session_factory, operation)

    def finish_analysis(
        self,
        *,
        novel_id: UUID,
        command_id: UUID,
        analysis: VoiceGeneratorAnalysis,
    ) -> UUID | None:
        if type(analysis) is not VoiceGeneratorAnalysis:
            raise TypeError("analysis must be VoiceGeneratorAnalysis")
        brief_payload = canonical_payload(analysis.brief.to_payload())
        evidence_payload = canonical_payload(dict(analysis.model_evidence))
        parameters = EXPECTED_AUDIO_PARAMETERS.wire_payload()
        runtime_identity = EXPECTED_RUNTIME_IDENTITY.wire_payload()
        instruction_key = self._digest_keyring.active
        instruction_digest = private_text_digest(
            instruction_key,
            purpose=VOICE_DESIGN_INSTRUCTION_PURPOSE,
            text=analysis.instruction,
        )
        draft_payload = {
            "schema_version": "voice-design-draft-fingerprint/1",
            "novel_id": str(novel_id),
            "character_version": analysis.character_version,
            "character_catalog_version": analysis.character_catalog_version,
            "workspace_digest": analysis.workspace_digest,
            "brief": brief_payload,
            "instruction_digest_key_id": instruction_key.key_id,
            "instruction_digest": instruction_digest,
            "model_evidence": evidence_payload,
            "language": analysis.language,
            "seed": analysis.seed,
            "parameters": parameters,
            "runtime_identity": runtime_identity,
        }
        fingerprint = canonical_sha256(draft_payload)

        def operation(session: Session) -> UUID | None:
            row = _required_command(
                session, novel_id=novel_id, command_id=command_id, for_update=True
            )
            if row.state != VoiceGeneratorCommandState.ANALYZING_CHARACTER.value:
                return row.background_job_id
            character = session.scalar(
                select(NovelCharacter)
                .where(
                    NovelCharacter.id == row.character_id,
                    NovelCharacter.novel_id == row.novel_id,
                )
                .with_for_update()
            )
            now = datetime.now(UTC)
            if (
                character is None
                or character.lifecycle_state != "active"
                or character.version != analysis.character_version
                or _current_binding_version(session, row.character_id)
                != row.expected_binding_version
            ):
                _mark_terminal(
                    row,
                    state=VoiceGeneratorCommandState.SUPERSEDED,
                    now=now,
                )
                session.flush()
                return None
            draft = session.scalar(
                select(VoiceDesignDraft).where(
                    VoiceDesignDraft.owner_id == LOCAL_OWNER_ID,
                    VoiceDesignDraft.workspace_id == LOCAL_WORKSPACE_ID,
                    VoiceDesignDraft.fingerprint == fingerprint,
                )
            )
            if draft is None:
                draft = VoiceDesignDraft(
                    id=uuid4(),
                    owner_id=LOCAL_OWNER_ID,
                    workspace_id=LOCAL_WORKSPACE_ID,
                    novel_id=novel_id,
                    character_id=row.character_id,
                    character_version=analysis.character_version,
                    character_catalog_version=analysis.character_catalog_version,
                    workspace_digest=analysis.workspace_digest,
                    brief_schema_version="character-voice-brief/1",
                    brief_json=brief_payload,
                    brief_digest=canonical_sha256(brief_payload),
                    instruction=analysis.instruction,
                    instruction_digest_key_id=instruction_key.key_id,
                    instruction_digest=instruction_digest,
                    model_evidence_json=evidence_payload,
                    model_evidence_digest=canonical_sha256(evidence_payload),
                    language=analysis.language,
                    seed=analysis.seed,
                    parameters_json=parameters,
                    parameters_digest=canonical_sha256(parameters),
                    runtime_identity_json=runtime_identity,
                    fingerprint=fingerprint,
                    created_at=now,
                )
                session.add(draft)
                session.flush()
            elif draft.novel_id != novel_id or draft.character_id != row.character_id:
                raise NarrationScopeMismatch("VoiceGenerator draft fingerprint scope changed")
            enqueued = enqueue_job(
                session,
                scope=self._scope,
                job_kind=VOICE_GENERATOR_JOB_KIND,
                input_hash=fingerprint,
                idempotency_key=f"voice-generator:{row.id}",
                resource_class=VOICE_GENERATOR_RESOURCE_CLASS,
                novel_id=novel_id,
                base_priority=80,
                # Product retry creates a new immutable command.  Reusing one
                # command across automatic attempts would make its monotonic
                # state/evidence ambiguous after a heavy-runtime failure.
                max_attempts=1,
            )
            row.draft_id = draft.id
            row.background_job_id = enqueued.job_id
            row.state = VoiceGeneratorCommandState.WAITING_FOR_HEAVY_RUNTIME.value
            row.progress_current = 2
            row.updated_at = now
            session.flush()
            return enqueued.job_id

        return _transaction(self._session_factory, operation)

    def fail_analysis(
        self,
        *,
        novel_id: UUID,
        command_id: UUID,
        failure_code: str = "CHARACTER_VOICE_ANALYSIS_FAILED",
    ) -> None:
        def operation(session: Session) -> None:
            row = _required_command(
                session, novel_id=novel_id, command_id=command_id, for_update=True
            )
            if row.state != VoiceGeneratorCommandState.ANALYZING_CHARACTER.value:
                return
            _mark_terminal(
                row,
                state=VoiceGeneratorCommandState.FAILED_CHARACTER_ANALYSIS,
                failure_code=failure_code,
                now=datetime.now(UTC),
            )
            session.flush()

        _transaction(self._session_factory, operation)

    def cancel(self, *, novel_id: UUID, command_id: UUID) -> None:
        def operation(session: Session) -> None:
            row = _required_command(
                session, novel_id=novel_id, command_id=command_id, for_update=True
            )
            current = VoiceGeneratorCommandState(row.state)
            if current is VoiceGeneratorCommandState.CANCELLED:
                return
            if current not in ACTIVE_STATES:
                raise InvalidNarrationState("VoiceGenerator command is not cancellable")
            if row.background_job_id is not None:
                request_cancel(
                    session,
                    scope=self._scope,
                    job_id=row.background_job_id,
                    actor="local-owner",
                    reason_code="VOICE_GENERATOR_CANCELLED",
                )
            _mark_terminal(
                row,
                state=VoiceGeneratorCommandState.CANCELLED,
                now=datetime.now(UTC),
            )
            session.flush()

        _transaction(self._session_factory, operation)

    def apply(
        self,
        *,
        novel_id: UUID,
        command_id: UUID,
        expected_binding_version: int,
    ) -> None:
        def operation(session: Session) -> None:
            row = _required_command(
                session, novel_id=novel_id, command_id=command_id, for_update=True
            )
            if row.state == VoiceGeneratorCommandState.READY_APPLIED.value:
                current = _current_binding_version(session, row.character_id)
                if current == expected_binding_version and row.voice_version_id is not None:
                    binding = session.scalar(
                        select(CharacterVoiceBinding).where(
                            CharacterVoiceBinding.character_id == row.character_id
                        )
                    )
                    if binding is not None and binding.voice_version_id == row.voice_version_id:
                        return
                raise NarrationCasConflict("character voice binding changed")
            if row.state != VoiceGeneratorCommandState.READY_UNAPPLIED.value:
                raise InvalidNarrationState("VoiceGenerator result is not ready to apply")
            if row.voice_profile_id is None or row.voice_version_id is None:
                raise InvalidNarrationState("VoiceGenerator result voice is absent")
            version = session.get(VoiceProfileVersion, row.voice_version_id)
            if version is None or version.profile_id != row.voice_profile_id:
                raise NarrationNotFound("VoiceGenerator result version not found")
            result = put_character_voice_binding(
                SqlAlchemyNarrationStore(session),
                novel_id=novel_id,
                character_id=row.character_id,
                request=wire.PutCharacterVoiceBindingRequest(
                    binding_policy=wire.CharacterVoiceBindingPolicy.DEDICATED,
                    profile_id=row.voice_profile_id,
                    version_id=row.voice_version_id,
                    language=version.language,
                    expected_version=expected_binding_version,
                ),
            )
            now = datetime.now(UTC)
            row.state = VoiceGeneratorCommandState.READY_APPLIED.value
            row.applied_binding_version = result.version
            row.applied_at = now
            row.updated_at = now
            session.flush()

        _transaction(self._session_factory, operation)

    def get_resource(
        self, *, novel_id: UUID, command_id: UUID
    ) -> wire.CharacterVoiceGeneratorCommandResource:
        def operation(session: Session) -> wire.CharacterVoiceGeneratorCommandResource:
            row = _required_command(
                session, novel_id=novel_id, command_id=command_id, for_update=False
            )
            return self._resource(session, row)

        return _transaction(self._session_factory, operation)

    def list_resources(
        self, *, novel_id: UUID, character_id: UUID
    ) -> wire.CharacterVoiceGeneratorCommandListResource:
        def operation(session: Session) -> wire.CharacterVoiceGeneratorCommandListResource:
            require_local_novel(SqlAlchemyNarrationStore(session), novel_id)
            rows = list(
                session.scalars(
                    select(VoiceGeneratorCommand)
                    .where(
                        VoiceGeneratorCommand.novel_id == novel_id,
                        VoiceGeneratorCommand.character_id == character_id,
                    )
                    .order_by(VoiceGeneratorCommand.created_at.desc(), VoiceGeneratorCommand.id.desc())
                    .limit(25)
                )
            )
            return wire.CharacterVoiceGeneratorCommandListResource(
                novel_id=novel_id,
                character_id=character_id,
                items=[self._resource(session, row) for row in rows],
            )

        return _transaction(self._session_factory, operation)

    def _resource(
        self, session: Session, row: VoiceGeneratorCommand
    ) -> wire.CharacterVoiceGeneratorCommandResource:
        store = SqlAlchemyNarrationStore(session)
        binding = get_character_voice_binding(
            store, novel_id=row.novel_id, character_id=row.character_id
        )
        draft = session.get(VoiceDesignDraft, row.draft_id) if row.draft_id else None
        brief = (
            wire.CharacterVoiceBriefResource.model_validate(draft.brief_json)
            if draft is not None
            else None
        )
        result_version = None
        if row.voice_profile_id is not None and row.voice_version_id is not None:
            profile = session.get(VoiceProfile, row.voice_profile_id)
            if profile is None or profile.novel_id != row.novel_id:
                raise NarrationScopeMismatch("VoiceGenerator result profile scope changed")
            resources = voice_profile_resource(store, profile).versions
            result_version = next(
                (item for item in resources if item.version_id == row.voice_version_id),
                None,
            )
            if result_version is None:
                raise NarrationNotFound("VoiceGenerator result version not found")
        state = VoiceGeneratorCommandState(row.state)
        view = state_view(state)
        current = (
            row.voice_version_id is not None
            and binding.profile_id == row.voice_profile_id
            and binding.version_id == row.voice_version_id
        )
        return wire.CharacterVoiceGeneratorCommandResource(
            command_id=row.id,
            novel_id=row.novel_id,
            character_id=row.character_id,
            draft_id=row.draft_id,
            background_job_id=row.background_job_id,
            state=state.value,
            progress_current=row.progress_current,
            progress_total=6,
            expected_binding_version=row.expected_binding_version,
            applied_binding_version=row.applied_binding_version,
            brief=brief,
            voice_profile_id=row.voice_profile_id,
            voice_version_id=row.voice_version_id,
            result_version=result_version,
            current_character_binding=binding,
            selection_still_current=current,
            cancellable=view.cancellable,
            retryable=view.retryable,
            terminal=view.terminal,
            failure_code=row.failure_code,
            created_at=row.created_at,
            started_at=row.started_at,
            completed_at=row.completed_at,
            applied_at=row.applied_at,
            updated_at=row.updated_at,
        )


def voice_generator_request_hash(
    *,
    novel_id: UUID,
    character_id: UUID,
    timeline_id: UUID | None,
    character_instance_id: UUID | None,
    expected_binding_version: int,
    seed: str | None,
) -> str:
    return canonical_sha256(
        {
            "schema_version": "character-voice-generation-request/1",
            "novel_id": str(novel_id),
            "character_id": str(character_id),
            "timeline_id": str(timeline_id) if timeline_id is not None else None,
            "character_instance_id": (
                str(character_instance_id) if character_instance_id is not None else None
            ),
            "expected_binding_version": expected_binding_version,
            "seed": seed,
        }
    )


__all__ = [
    "SqlAlchemyVoiceGeneratorService",
    "VoiceGeneratorAnalysis",
    "VoiceGeneratorCommandState",
    "VoiceGeneratorReservation",
    "VOICE_GENERATOR_JOB_KIND",
    "command_state_for_host_receipt",
    "ensure_command_transition",
    "runtime_port",
    "state_view",
    "terminal_state_for_runtime_error",
    "validate_runtime_completion",
    "voice_generator_request_hash",
]
