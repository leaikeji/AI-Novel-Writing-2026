"""SQLAlchemy integration for Plan 55 automatic character voice preparation.

The pure state machine remains in :mod:`voice_preparation`.  This module owns
only persistence, adapters to already-audited narration/VoiceGenerator/official
selection services, HTTP projections, and the lightweight reconciler.  Model
calls are deliberately absent: request-scoped Agent analysis is scheduled by
the API adapter and heavy work remains in the shared runtime queue.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..character_workspace import CharacterWorkspaceError, service_for_session
from ..models import (
    CharacterVoiceBinding,
    Document,
    DocumentWorkingCopy,
    NarrationRequest,
    NarrationScript,
    NarrationScriptVersion,
    NarrationSegment,
    Novel,
    NovelCharacter,
    VoiceDesignDraft,
    VoicePreparationCommand as VoicePreparationCommandRow,
    VoicePreparationItem as VoicePreparationItemRow,
    VoiceProfile,
    VoiceProfileVersion,
)
from . import schemas as wire
from .character_voice_matching import (
    match_official_voice,
    parse_character_voice_brief,
)
from .contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID
from .edition_service import (
    NarrationProductionPolicy,
    SqlAlchemyNarrationWorkflowService,
    StartNarrationWorkflow,
)
from .official_presets import OFFICIAL_PRESETS_BY_ID
from .official_voice_selection import OfficialVoiceSelectionService
from .privacy import get_character_voice_binding, get_narration_settings
from .services import (
    IdempotencyConflict,
    InvalidNarrationState,
    NarrationCasConflict,
    NarrationNotFound,
    NarrationServiceError,
    SqlAlchemyNarrationStore,
    StaleNarrationInput,
    canonical_sha256,
    require_local_novel,
)
from .voice_generator_service import (
    SqlAlchemyVoiceGeneratorService,
    voice_generator_request_hash,
)
from .voice_preparation import (
    ACTIVE_COMMAND_STATES,
    TERMINAL_COMMAND_STATES,
    TERMINAL_ITEM_STATES,
    AnalyzeOnlyPreflightRequest,
    ContinuationResultState,
    ExistingVoiceKind,
    ExistingVoiceSnapshot,
    FrozenSpeakerSegment,
    NarrationContinuationRequest,
    NarrationContinuationResult,
    OfficialFallbackRequest,
    OfficialFallbackResult,
    OfficialFallbackState,
    VoiceGeneratorChild,
    VoiceGeneratorChildState,
    VoiceGeneratorReserveRequest,
    VoicePreparationCommand,
    VoicePreparationCommandState,
    VoicePreparationContinuationState,
    VoicePreparationCreateRequest,
    VoicePreparationItem,
    VoicePreparationItemState,
    VoicePreparationPreflight,
    VoicePreparationReservation,
    VoicePreparationService,
    VoicePreparationTarget,
    speaker_summary_digest,
)


SessionFactory = Callable[[], Session]
ACTIVE_ROW_STATES: Final = tuple(state.value for state in ACTIVE_COMMAND_STATES)
logger = logging.getLogger(__name__)


def _transaction(session_factory: SessionFactory, operation):
    with session_factory() as session:
        with session.begin():
            return operation(session)


def _workspace_payload(workspace) -> dict[str, object]:
    return {
        "character": workspace.character.model_dump(mode="json"),
        "selected_instance": workspace.selected_instance.model_dump(mode="json"),
        "aliases": [item.model_dump(mode="json") for item in workspace.aliases],
        "relationships": [item.model_dump(mode="json") for item in workspace.relationships],
        "projected_state": workspace.projected_state.model_dump(mode="json"),
    }


def _frozen_segments(
    session: Session,
    *,
    script_version_id: UUID,
) -> tuple[FrozenSpeakerSegment, ...]:
    rows = tuple(
        session.scalars(
            select(NarrationSegment)
            .where(NarrationSegment.script_version_id == script_version_id)
            .order_by(NarrationSegment.ordinal)
        )
    )
    return tuple(
        FrozenSpeakerSegment(
            ordinal=row.ordinal,
            segment_kind=row.segment_kind,
            source_start_utf16=row.source_start_utf16,
            source_end_utf16=row.source_end_utf16,
            speaker_kind=row.speaker_kind,
            character_id=row.character_id,
            anonymous_speaker_id=row.anonymous_speaker_id,
        )
        for row in rows
    )


class SqlAlchemyAnalyzeOnlyPreflight:
    def __init__(self, session_factory: SessionFactory, policy: NarrationProductionPolicy) -> None:
        self._session_factory = session_factory
        self._policy = policy

    def analyze(self, request: AnalyzeOnlyPreflightRequest) -> VoicePreparationPreflight:
        with self._session_factory() as session:
            service = SqlAlchemyNarrationWorkflowService(session, self._policy)
            result = service.start(
                StartNarrationWorkflow(
                    document_id=request.document_id,
                    intent="analyze_only",
                    expected_draft_version=request.expected_draft_version,
                    expected_content_hash=request.expected_content_hash,
                    expected_settings_version=request.expected_settings_version,
                    force_review=False,
                    idempotency_key=request.idempotency_key,
                    explicitly_requested=True,
                    actor="local-owner",
                )
            )
            if result.script_version_id is None:
                raise InvalidNarrationState("analyze-only preflight produced no script")
            with session.begin():
                request_row = session.get(NarrationRequest, result.request_id)
                version = session.get(NarrationScriptVersion, result.script_version_id)
                if request_row is None or version is None:
                    raise NarrationNotFound("analyze-only preflight evidence not found")
                script = session.get(NarrationScript, version.script_id)
                if script is None or script.document_id != request.document_id:
                    raise InvalidNarrationState("analyze-only preflight scope changed")
                segments = _frozen_segments(
                    session, script_version_id=result.script_version_id
                )
                digest = speaker_summary_digest(segments)
                return VoicePreparationPreflight(
                    novel_id=script.novel_id,
                    request_id=result.request_id,
                    script_version_id=result.script_version_id,
                    document_id=request.document_id,
                    source_revision_id=result.source_revision_id,
                    draft_version=request.expected_draft_version,
                    content_hash=result.source_content_hash,
                    settings_version=request.expected_settings_version,
                    settings_fingerprint=result.settings_fingerprint,
                    segments=segments,
                    speaker_digest=digest,
                )


class SqlAlchemyVoicePreparationInventory:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def load_targets(
        self,
        *,
        novel_id: UUID,
        preflight: VoicePreparationPreflight | None,
    ) -> tuple[VoicePreparationTarget, ...]:
        del preflight

        def operation(session: Session) -> tuple[VoicePreparationTarget, ...]:
            require_local_novel(SqlAlchemyNarrationStore(session), novel_id)
            characters = tuple(
                session.scalars(
                    select(NovelCharacter)
                    .where(
                        NovelCharacter.novel_id == novel_id,
                        NovelCharacter.lifecycle_state == "active",
                    )
                    .order_by(
                        (NovelCharacter.role_type != "main"),
                        NovelCharacter.position,
                        NovelCharacter.id,
                    )
                )
            )
            bindings = {
                row.character_id: row
                for row in session.scalars(
                    select(CharacterVoiceBinding).where(
                        CharacterVoiceBinding.novel_id == novel_id
                    )
                )
            }
            targets: list[VoicePreparationTarget] = []
            workspace_service = service_for_session(session)
            for character in characters:
                try:
                    workspace = workspace_service.get_workspace(novel_id, character.id)
                    workspace_digest = canonical_sha256(_workspace_payload(workspace))
                    has_card = True
                except CharacterWorkspaceError:
                    workspace_digest = canonical_sha256(
                        {
                            "novel_id": str(novel_id),
                            "character_id": str(character.id),
                            "version": character.version,
                            "unavailable": True,
                        }
                    )
                    has_card = False
                binding = bindings.get(character.id)
                snapshot = _existing_voice(session, novel_id=novel_id, binding=binding)
                targets.append(
                    VoicePreparationTarget(
                        character_id=character.id,
                        # Historical novels may still carry the pre-V2
                        # ``protagonist`` value.  The preparation command owns
                        # the frozen V1 vocabulary and must normalize it before
                        # persisting an item protected by the 0040 constraint.
                        role_type=(
                            "main"
                            if character.role_type in {"main", "protagonist"}
                            else "supporting"
                        ),
                        active=True,
                        has_saved_character_card=has_card,
                        workspace_digest=workspace_digest,
                        voice=snapshot,
                    )
                )
            return tuple(targets)

        return _transaction(self._session_factory, operation)


def _existing_voice(
    session: Session,
    *,
    novel_id: UUID,
    binding: CharacterVoiceBinding | None,
) -> ExistingVoiceSnapshot:
    if (
        binding is None
        or binding.binding_policy == "unset"
        or binding.profile_id is None
        or binding.voice_version_id is None
    ):
        return ExistingVoiceSnapshot(kind=ExistingVoiceKind.NONE, binding_version=0)
    profile = session.get(VoiceProfile, binding.profile_id)
    version = session.get(VoiceProfileVersion, binding.voice_version_id)
    if (
        profile is None
        or version is None
        or version.profile_id != profile.id
        or profile.novel_id != novel_id
    ):
        return ExistingVoiceSnapshot(
            kind=ExistingVoiceKind.PRIVATE,
            binding_version=binding.version,
            profile_id=binding.profile_id,
            voice_version_id=binding.voice_version_id,
            usable=False,
        )
    official = (
        version.source_type == "preset"
        and version.preset_key in OFFICIAL_PRESETS_BY_ID
        and version.activation_basis == "explicit_official_preset_selection"
    )
    if official:
        kind = ExistingVoiceKind.OFFICIAL
    elif version.source_type == "uploaded":
        kind = ExistingVoiceKind.UPLOADED
    elif version.activation_basis == "character_one_click_generation":
        kind = ExistingVoiceKind.GENERATED
    else:
        kind = ExistingVoiceKind.PRIVATE
    return ExistingVoiceSnapshot(
        kind=kind,
        binding_version=binding.version,
        profile_id=profile.id,
        voice_version_id=version.id,
        usable=profile.status == "active" and version.state == "locked",
    )


class SqlAlchemyVoicePreparationRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def reserve(self, command: VoicePreparationCommand) -> VoicePreparationReservation:
        def operation(session: Session) -> VoicePreparationReservation:
            novel = require_local_novel(
                SqlAlchemyNarrationStore(session), command.novel_id, for_update=True
            )
            replay = session.scalar(
                select(VoicePreparationCommandRow)
                .where(
                    VoicePreparationCommandRow.novel_id == command.novel_id,
                    VoicePreparationCommandRow.external_idempotency_digest
                    == command.external_idempotency_digest,
                )
                .with_for_update()
            )
            if replay is not None:
                if replay.request_hash != command.request_hash:
                    raise IdempotencyConflict("voice preparation idempotency key was reused")
                return VoicePreparationReservation(replay.id, True)
            active = session.scalar(
                select(VoicePreparationCommandRow.id).where(
                    VoicePreparationCommandRow.novel_id == command.novel_id,
                    VoicePreparationCommandRow.document_id == command.document_id,
                    VoicePreparationCommandRow.state.in_(ACTIVE_ROW_STATES),
                )
            )
            if active is not None:
                return VoicePreparationReservation(active, True)
            preflight = command.preflight
            row = VoicePreparationCommandRow(
                id=command.command_id,
                owner_id=LOCAL_OWNER_ID,
                workspace_id=LOCAL_WORKSPACE_ID,
                novel_id=command.novel_id,
                document_id=command.document_id,
                source_revision_id=(preflight.source_revision_id if preflight else None),
                mode=command.mode,
                actor=command.actor,
                explicit_requested_at=command.explicit_requested_at,
                external_idempotency_digest=command.external_idempotency_digest,
                request_hash=command.request_hash,
                state=command.state.value,
                aggregate_version=command.aggregate_version,
                character_catalog_version=novel.character_catalog_version,
                workspace_digest=canonical_sha256(
                    [
                        {
                            "character_id": str(item.character_id),
                            "workspace_digest": item.workspace_digest,
                        }
                        for item in command.items
                    ]
                ),
                preflight_request_id=(preflight.request_id if preflight else None),
                preflight_script_version_id=(
                    preflight.script_version_id if preflight else None
                ),
                expected_draft_version=command.expected_draft_version,
                expected_content_hash=command.expected_content_hash,
                expected_settings_version=command.expected_settings_version,
                speaker_digest_version=(
                    "narration-voice-preparation-speakers/1" if preflight else None
                ),
                speaker_digest=(preflight.speaker_digest if preflight else None),
                progress_current=command.progress_current,
                progress_total=command.progress_total,
                chapter_ready=command.chapter_ready,
                background_remaining=command.background_remaining,
                continuation_idempotency_key=command.continuation_idempotency_key,
                continuation_state=command.continuation_state.value,
                narration_request_id=command.narration_request_id,
                preparation_attempt=command.continuation_attempt,
                lease_fence=command.continuation_fence,
                lease_expires_at=command.continuation_lease_expires_at,
                failure_code=command.failure_code,
                created_at=command.created_at,
                updated_at=command.updated_at,
                completed_at=command.completed_at,
            )
            session.add(row)
            for item in command.items:
                session.add(_item_row(command.command_id, command.novel_id, item))
            try:
                session.flush()
            except IntegrityError as error:
                raise InvalidNarrationState(
                    "another active voice preparation already exists"
                ) from error
            return VoicePreparationReservation(command.command_id, False)

        return _transaction(self._session_factory, operation)

    def get(self, *, novel_id: UUID, command_id: UUID) -> VoicePreparationCommand:
        return _transaction(
            self._session_factory,
            lambda session: _load_command(
                session, novel_id=novel_id, command_id=command_id
            ),
        )

    def compare_and_swap(
        self,
        *,
        expected_aggregate_version: int,
        command: VoicePreparationCommand,
    ) -> bool:
        def operation(session: Session) -> bool:
            row = session.scalar(
                select(VoicePreparationCommandRow)
                .where(
                    VoicePreparationCommandRow.id == command.command_id,
                    VoicePreparationCommandRow.novel_id == command.novel_id,
                    VoicePreparationCommandRow.aggregate_version
                    == expected_aggregate_version,
                )
                .with_for_update()
            )
            if row is None:
                return False
            row.state = command.state.value
            row.aggregate_version = command.aggregate_version
            row.progress_current = command.progress_current
            row.progress_total = command.progress_total
            row.chapter_ready = command.chapter_ready
            row.background_remaining = command.background_remaining
            row.continuation_state = command.continuation_state.value
            row.narration_request_id = command.narration_request_id
            row.preparation_attempt = command.continuation_attempt
            row.lease_fence = command.continuation_fence
            row.lease_expires_at = command.continuation_lease_expires_at
            row.failure_code = command.failure_code
            row.updated_at = command.updated_at
            row.completed_at = command.completed_at
            stored_items = {
                item.character_id: item
                for item in session.scalars(
                    select(VoicePreparationItemRow)
                    .where(VoicePreparationItemRow.command_id == command.command_id)
                    .with_for_update()
                )
            }
            if set(stored_items) != {item.character_id for item in command.items}:
                raise InvalidNarrationState("voice preparation item set changed")
            for item in command.items:
                stored = stored_items[item.character_id]
                stored.state = item.state.value
                stored.usable_for_narration = item.usable_for_narration
                stored.voice_generator_command_id = item.voice_generator_command_id
                stored.result_profile_id = item.result_profile_id
                stored.result_voice_version_id = item.result_voice_version_id
                stored.applied_binding_version = item.applied_binding_version
                stored.failure_code = item.failure_code
                stored.updated_at = command.updated_at
            session.flush()
            return True

        return _transaction(self._session_factory, operation)


def _item_row(
    command_id: UUID,
    novel_id: UUID,
    item: VoicePreparationItem,
) -> VoicePreparationItemRow:
    return VoicePreparationItemRow(
        command_id=command_id,
        novel_id=novel_id,
        character_id=item.character_id,
        position=item.position,
        role_type=item.role_type,
        chapter_speaker=item.chapter_speaker,
        expected_binding_version=item.expected_binding_version,
        workspace_digest=item.workspace_digest,
        original_voice_kind=item.original_voice.kind.value,
        original_profile_id=item.original_voice.profile_id,
        original_voice_version_id=item.original_voice.voice_version_id,
        original_usable=item.original_voice.usable,
        state=item.state.value,
        usable_for_narration=item.usable_for_narration,
        voice_generator_command_id=item.voice_generator_command_id,
        result_profile_id=item.result_profile_id,
        result_voice_version_id=item.result_voice_version_id,
        applied_binding_version=item.applied_binding_version,
        failure_code=item.failure_code,
    )


def _load_command(
    session: Session,
    *,
    novel_id: UUID,
    command_id: UUID,
) -> VoicePreparationCommand:
    row = session.scalar(
        select(VoicePreparationCommandRow).where(
            VoicePreparationCommandRow.id == command_id,
            VoicePreparationCommandRow.novel_id == novel_id,
        )
    )
    if row is None:
        raise NarrationNotFound("voice preparation command not found")
    item_rows = tuple(
        session.scalars(
            select(VoicePreparationItemRow)
            .where(VoicePreparationItemRow.command_id == row.id)
            .order_by(VoicePreparationItemRow.position)
        )
    )
    preflight = None
    if row.preflight_script_version_id is not None:
        version = session.get(NarrationScriptVersion, row.preflight_script_version_id)
        request_row = session.get(NarrationRequest, row.preflight_request_id)
        if version is None or request_row is None:
            raise InvalidNarrationState("voice preparation preflight evidence missing")
        script = session.get(NarrationScript, version.script_id)
        if script is None or row.source_revision_id is None:
            raise InvalidNarrationState("voice preparation preflight scope missing")
        segments = _frozen_segments(
            session, script_version_id=row.preflight_script_version_id
        )
        preflight = VoicePreparationPreflight(
            novel_id=row.novel_id,
            request_id=row.preflight_request_id,
            script_version_id=row.preflight_script_version_id,
            document_id=row.document_id,
            source_revision_id=row.source_revision_id,
            draft_version=row.expected_draft_version,
            content_hash=row.expected_content_hash,
            settings_version=row.expected_settings_version,
            settings_fingerprint=version.settings_fingerprint,
            segments=segments,
            speaker_digest=row.speaker_digest,
        )
    items = tuple(
        VoicePreparationItem(
            character_id=item.character_id,
            position=item.position,
            role_type=item.role_type,
            chapter_speaker=item.chapter_speaker,
            expected_binding_version=item.expected_binding_version,
            workspace_digest=item.workspace_digest,
            original_voice=ExistingVoiceSnapshot(
                kind=ExistingVoiceKind(item.original_voice_kind),
                binding_version=item.expected_binding_version,
                profile_id=item.original_profile_id,
                voice_version_id=item.original_voice_version_id,
                usable=item.original_usable,
            ),
            state=VoicePreparationItemState(item.state),
            usable_for_narration=item.usable_for_narration,
            voice_generator_command_id=item.voice_generator_command_id,
            result_profile_id=item.result_profile_id,
            result_voice_version_id=item.result_voice_version_id,
            applied_binding_version=item.applied_binding_version,
            failure_code=item.failure_code,
        )
        for item in item_rows
    )
    return VoicePreparationCommand(
        command_id=row.id,
        aggregate_version=row.aggregate_version,
        novel_id=row.novel_id,
        mode=row.mode,
        request_hash=row.request_hash,
        external_idempotency_digest=row.external_idempotency_digest,
        actor=row.actor,
        explicit_requested_at=row.explicit_requested_at,
        document_id=row.document_id,
        expected_draft_version=row.expected_draft_version,
        expected_content_hash=row.expected_content_hash,
        expected_settings_version=row.expected_settings_version,
        preflight=preflight,
        items=items,
        state=VoicePreparationCommandState(row.state),
        progress_current=row.progress_current,
        progress_total=row.progress_total,
        chapter_ready=row.chapter_ready,
        background_remaining=row.background_remaining,
        continuation_idempotency_key=row.continuation_idempotency_key,
        continuation_state=VoicePreparationContinuationState(row.continuation_state),
        continuation_attempt=row.preparation_attempt,
        continuation_fence=row.lease_fence,
        continuation_lease_expires_at=row.lease_expires_at,
        narration_request_id=row.narration_request_id,
        failure_code=row.failure_code,
        created_at=row.created_at,
        updated_at=row.updated_at,
        completed_at=row.completed_at,
    )


class VoiceGeneratorPreparationAdapter:
    def __init__(self, service: SqlAlchemyVoiceGeneratorService) -> None:
        self._service = service

    def reserve(self, request: VoiceGeneratorReserveRequest) -> VoiceGeneratorChild:
        request_hash = voice_generator_request_hash(
            novel_id=request.novel_id,
            character_id=request.character_id,
            timeline_id=None,
            character_instance_id=None,
            expected_binding_version=request.expected_binding_version,
            seed=None,
        )
        reservation = self._service.reserve(
            novel_id=request.novel_id,
            character_id=request.character_id,
            expected_binding_version=request.expected_binding_version,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
        )
        return self.get(
            novel_id=request.novel_id, command_id=reservation.command_id
        )

    def get(self, *, novel_id: UUID, command_id: UUID) -> VoiceGeneratorChild:
        self._service.expire_stale_analysis(
            novel_id=novel_id,
            command_id=command_id,
            older_than=datetime.now(UTC) - timedelta(minutes=15),
        )
        resource = self._service.get_resource(
            novel_id=novel_id, command_id=command_id
        )
        if resource.state == "ready_applied":
            state = VoiceGeneratorChildState.READY_APPLIED
        elif resource.state == "ready_unapplied":
            state = VoiceGeneratorChildState.READY_UNAPPLIED
        elif resource.terminal:
            if resource.state == "cancelled":
                state = VoiceGeneratorChildState.CANCELLED
            elif resource.state == "superseded":
                state = VoiceGeneratorChildState.SUPERSEDED
            else:
                state = VoiceGeneratorChildState.FAILED
        else:
            state = VoiceGeneratorChildState.ACTIVE
        binding = resource.current_character_binding
        current_usable = binding.profile_id is not None and binding.version_id is not None
        return VoiceGeneratorChild(
            command_id=resource.command_id,
            state=state,
            profile_id=resource.voice_profile_id,
            voice_version_id=resource.voice_version_id,
            applied_binding_version=resource.applied_binding_version,
            current_binding_usable=current_usable,
            runtime_unavailable=resource.state in {
                "failed_runtime_unavailable",
                "failed_memory_safety",
            },
            failure_code=resource.failure_code,
        )

    def cancel(self, *, novel_id: UUID, command_id: UUID) -> None:
        self._service.cancel(novel_id=novel_id, command_id=command_id)


class SqlAlchemyOfficialVoiceFallback:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory
        self._selection = OfficialVoiceSelectionService(session_factory)

    def ensure(self, request: OfficialFallbackRequest) -> OfficialFallbackResult:
        def read(session: Session):
            store = SqlAlchemyNarrationStore(session)
            settings = get_narration_settings(store, novel_id=request.novel_id)
            binding = get_character_voice_binding(
                store,
                novel_id=request.novel_id,
                character_id=request.character_id,
            )
            draft = session.scalar(
                select(VoiceDesignDraft)
                .where(
                    VoiceDesignDraft.novel_id == request.novel_id,
                    VoiceDesignDraft.character_id == request.character_id,
                )
                .order_by(VoiceDesignDraft.created_at.desc(), VoiceDesignDraft.id.desc())
                .limit(1)
            )
            preset_id = "onnx.Junhao"
            if draft is not None:
                preset_id = match_official_voice(
                    parse_character_voice_brief(draft.brief_json)
                ).selected_preset_id
            return settings.version, binding, preset_id

        settings_version, before, preset_id = _transaction(self._session_factory, read)
        if before.version != request.expected_binding_version:
            return OfficialFallbackResult(state=OfficialFallbackState.CAS_DRIFTED)
        try:
            selected = self._selection.select_official_voice(
                novel_id=request.novel_id,
                request=wire.OfficialVoiceSelectionRequest(
                    preset_id=preset_id,
                    target_kind=wire.OfficialVoiceSelectionTargetKind.CHARACTER,
                    character_id=request.character_id,
                    expected_settings_version=settings_version,
                    expected_binding_version=request.expected_binding_version,
                ),
                idempotency_key=request.idempotency_key,
            )
        except NarrationCasConflict:
            return OfficialFallbackResult(state=OfficialFallbackState.CAS_DRIFTED)
        except NarrationServiceError:
            return OfficialFallbackResult(state=OfficialFallbackState.FAILED)
        binding = selected.current_character_binding
        if binding is None or binding.profile_id is None or binding.version_id is None:
            return OfficialFallbackResult(state=OfficialFallbackState.FAILED)
        return OfficialFallbackResult(
            state=OfficialFallbackState.APPLIED,
            profile_id=binding.profile_id,
            voice_version_id=binding.version_id,
            binding_version=binding.version,
        )


class SqlAlchemyNarrationContinuation:
    def __init__(
        self,
        session_factory: SessionFactory,
        policy: NarrationProductionPolicy,
    ) -> None:
        self._session_factory = session_factory
        self._policy = policy

    def create_or_replay(
        self, request: NarrationContinuationRequest
    ) -> NarrationContinuationResult:
        try:
            with self._session_factory() as session:
                result = SqlAlchemyNarrationWorkflowService(session, self._policy).start(
                    StartNarrationWorkflow(
                        document_id=request.document_id,
                        intent="create",
                        expected_draft_version=request.expected_draft_version,
                        expected_content_hash=request.expected_content_hash,
                        expected_settings_version=request.expected_settings_version,
                        force_review=False,
                        idempotency_key=request.idempotency_key,
                        explicitly_requested=True,
                        actor=request.actor,
                        requested_at=request.explicit_requested_at,
                        expected_speaker_digest=request.speaker_digest,
                    )
                )
            return NarrationContinuationResult(
                state=ContinuationResultState.CREATED,
                request_id=result.request_id,
            )
        except StaleNarrationInput:
            return NarrationContinuationResult(
                state=ContinuationResultState.SOURCE_DRIFTED
            )
        except (NarrationCasConflict, IdempotencyConflict):
            return NarrationContinuationResult(state=ContinuationResultState.CONFLICT)


class SqlAlchemyVoicePreparationService:
    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        policy: NarrationProductionPolicy,
        voice_generator: SqlAlchemyVoiceGeneratorService,
    ) -> None:
        self._session_factory = session_factory
        self._voice_generator_service = voice_generator
        self._domain = VoicePreparationService(
            repository=SqlAlchemyVoicePreparationRepository(session_factory),
            preflight=SqlAlchemyAnalyzeOnlyPreflight(session_factory, policy),
            inventory=SqlAlchemyVoicePreparationInventory(session_factory),
            voice_generator=VoiceGeneratorPreparationAdapter(voice_generator),
            official_fallback=SqlAlchemyOfficialVoiceFallback(session_factory),
            continuation=SqlAlchemyNarrationContinuation(session_factory, policy),
        )

    @property
    def voice_generator_service(self) -> SqlAlchemyVoiceGeneratorService:
        return self._voice_generator_service

    def create(self, request: VoicePreparationCreateRequest) -> VoicePreparationReservation:
        return self._domain.create(request)

    def retry(
        self, *, novel_id: UUID, command_id: UUID
    ) -> VoicePreparationReservation:
        previous = self._domain.get(novel_id=novel_id, command_id=command_id)

        def refreshed(session: Session) -> VoicePreparationCreateRequest:
            require_local_novel(SqlAlchemyNarrationStore(session), novel_id)
            if previous.document_id is None:
                return VoicePreparationCreateRequest(
                    novel_id=novel_id,
                    document_id=None,
                    expected_draft_version=None,
                    expected_content_hash=None,
                    expected_settings_version=None,
                    idempotency_key="voice-preparation-retry-placeholder",
                    actor=previous.actor,
                    explicit_requested_at=datetime.now(UTC),
                )
            document = session.get(Document, previous.document_id)
            working_copy = session.get(DocumentWorkingCopy, previous.document_id)
            settings = get_narration_settings(
                SqlAlchemyNarrationStore(session), novel_id=novel_id
            )
            if (
                document is None
                or document.novel_id != novel_id
                or working_copy is None
            ):
                raise NarrationNotFound("voice preparation chapter source not found")
            return VoicePreparationCreateRequest(
                novel_id=novel_id,
                document_id=document.id,
                expected_draft_version=working_copy.draft_version,
                expected_content_hash=working_copy.content_hash,
                expected_settings_version=settings.version,
                idempotency_key="voice-preparation-retry-placeholder",
                actor=previous.actor,
                explicit_requested_at=datetime.now(UTC),
            )

        request = _transaction(self._session_factory, refreshed)
        return self._domain.retry(
            novel_id=novel_id,
            command_id=command_id,
            refreshed_request=request,
        )

    def reserve_next_pending(
        self, *, novel_id: UUID, command_id: UUID
    ) -> VoicePreparationCommand:
        return self._domain.reserve_next_pending(
            novel_id=novel_id, command_id=command_id
        )

    def reconcile_once(self, *, novel_id: UUID, command_id: UUID) -> VoicePreparationCommand:
        current = self._domain.get(novel_id=novel_id, command_id=command_id)
        has_child_to_poll = any(
            item.voice_generator_command_id is not None
            and item.state
            in {VoicePreparationItemState.QUEUED, VoicePreparationItemState.GENERATING}
            for item in current.items
        )
        has_pending = any(
            item.state is VoicePreparationItemState.PENDING for item in current.items
        )
        if has_child_to_poll or current.chapter_ready or not has_pending:
            return self._domain.advance(novel_id=novel_id, command_id=command_id)
        return current

    def cancel(self, *, novel_id: UUID, command_id: UUID) -> wire.VoicePreparationResource:
        self._domain.cancel(novel_id=novel_id, command_id=command_id)
        return self.get_resource(novel_id=novel_id, command_id=command_id)

    def get_domain(self, *, novel_id: UUID, command_id: UUID) -> VoicePreparationCommand:
        return self._domain.get(novel_id=novel_id, command_id=command_id)

    def get_resource(
        self, *, novel_id: UUID, command_id: UUID
    ) -> wire.VoicePreparationResource:
        return _transaction(
            self._session_factory,
            lambda session: _resource(
                session,
                _load_command(session, novel_id=novel_id, command_id=command_id),
            ),
        )

    def list_resources(self, *, novel_id: UUID) -> wire.VoicePreparationListResource:
        def operation(session: Session) -> wire.VoicePreparationListResource:
            require_local_novel(SqlAlchemyNarrationStore(session), novel_id)
            ids = tuple(
                session.scalars(
                    select(VoicePreparationCommandRow.id)
                    .where(VoicePreparationCommandRow.novel_id == novel_id)
                    .order_by(
                        VoicePreparationCommandRow.created_at.desc(),
                        VoicePreparationCommandRow.id.desc(),
                    )
                    .limit(20)
                )
            )
            now = datetime.now(UTC)
            return wire.VoicePreparationListResource(
                novel_id=novel_id,
                server_now=now,
                items=[
                    _resource(
                        session,
                        _load_command(session, novel_id=novel_id, command_id=identifier),
                        now=now,
                    )
                    for identifier in ids
                ],
            )

        return _transaction(self._session_factory, operation)

    def active_command_ids(self) -> tuple[tuple[UUID, UUID], ...]:
        return _transaction(
            self._session_factory,
            lambda session: tuple(
                session.execute(
                    select(
                        VoicePreparationCommandRow.novel_id,
                        VoicePreparationCommandRow.id,
                    ).where(VoicePreparationCommandRow.state.in_(ACTIVE_ROW_STATES))
                ).all()
            ),
        )


def _target_resource(
    item: VoicePreparationItem,
    names: dict[UUID, str],
) -> wire.VoicePreparationTargetResource:
    return wire.VoicePreparationTargetResource(
        character_id=item.character_id,
        character_name=names.get(item.character_id, "未知人物"),
        role_type=item.role_type,
        chapter_speaker=item.chapter_speaker,
        state=item.state.value,
        voice_generator_command_id=item.voice_generator_command_id,
        profile_id=item.result_profile_id,
        voice_version_id=item.result_voice_version_id,
        failure_code=item.failure_code,
    )


def _resource(
    session: Session,
    command: VoicePreparationCommand,
    *,
    now: datetime | None = None,
) -> wire.VoicePreparationResource:
    names = {
        row.id: row.name
        for row in session.scalars(
            select(NovelCharacter).where(
                NovelCharacter.id.in_([item.character_id for item in command.items])
            )
        )
    }
    targets = [_target_resource(item, names) for item in command.items]
    current = next(
        (
            target
            for target in targets
            if target.state in {"pending", "queued", "generating"}
        ),
        None,
    )
    terminal = command.state in TERMINAL_COMMAND_STATES
    return wire.VoicePreparationResource(
        command_id=command.command_id,
        novel_id=command.novel_id,
        document_id=command.document_id,
        state=command.state.value,
        server_now=now or datetime.now(UTC),
        progress_current=command.progress_current,
        progress_total=command.progress_total,
        preflight_request_id=(command.preflight.request_id if command.preflight else None),
        preflight_script_version_id=(
            command.preflight.script_version_id if command.preflight else None
        ),
        chapter_ready=command.chapter_ready,
        background_remaining=command.background_remaining,
        continuation_state=command.continuation_state.value,
        narration_request_id=command.narration_request_id,
        current_target=current,
        preserved=[target for target in targets if target.state == "preserved"],
        generated=[
            target
            for target in targets
            if target.state in {"ready_applied", "ready_unapplied"}
        ],
        fallback=[target for target in targets if target.state == "fallback_official"],
        failed=[target for target in targets if target.state == "failed"],
        cancellable=not terminal,
        retryable=command.state
        in {
            VoicePreparationCommandState.FAILED,
            VoicePreparationCommandState.SUPERSEDED,
            VoicePreparationCommandState.READY_WITH_WARNINGS,
        },
        terminal=terminal,
        failure_code=command.failure_code,
        created_at=command.created_at,
        updated_at=command.updated_at,
        completed_at=command.completed_at,
    )


class VoicePreparationReconciler:
    def __init__(
        self,
        service: SqlAlchemyVoicePreparationService,
        *,
        idle_seconds: float = 5.0,
        on_crash: Callable[[BaseException], None] | None = None,
    ) -> None:
        self._service = service
        self._idle_seconds = idle_seconds
        self._on_crash = on_crash
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self.healthy = False

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self.healthy = True
        self._task = asyncio.create_task(self._run(), name="voice-preparation-reconciler")

    async def stop(self) -> None:
        self.healthy = False
        self._stop.set()
        self._wake.set()
        task = self._task
        self._task = None
        if task is not None:
            await task

    def wake(self) -> None:
        self._wake.set()

    async def _run(self) -> None:
        try:
            while not self._stop.is_set():
                rows = await asyncio.to_thread(self._service.active_command_ids)
                for novel_id, command_id in rows:
                    if self._stop.is_set():
                        break
                    await asyncio.to_thread(
                        self._service.reconcile_once,
                        novel_id=novel_id,
                        command_id=command_id,
                    )
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=self._idle_seconds)
                except TimeoutError:
                    pass
        except BaseException as error:
            self.healthy = False
            if not isinstance(error, asyncio.CancelledError):
                logger.exception("voice preparation reconciler crashed")
            if self._on_crash is not None:
                self._on_crash(error)
            if not isinstance(error, asyncio.CancelledError):
                return
            raise
        finally:
            self.healthy = False


__all__ = [
    "SqlAlchemyVoicePreparationService",
    "VoicePreparationReconciler",
]
