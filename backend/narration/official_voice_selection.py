"""Atomic narrator/character selection of pinned official Nano voices.

The service owns one short database transaction.  It never calls Nano or
publishes media; official provenance, rights and version construction remain
owned by :mod:`voice_product`.
"""

from __future__ import annotations

import re
from typing import Callable, Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    CharacterVoiceBinding,
    NovelNarrationSettings,
    VoiceActionCommand,
    VoiceProfile,
)
from . import schemas as wire
from .contracts import NarrationRequestScope
from .privacy import (
    _require_character,
    _storage_settings,
    get_character_voice_binding,
    get_narration_settings,
    put_character_voice_binding,
)
from .services import (
    IdempotencyConflict,
    InvalidNarrationState,
    NarrationCasConflict,
    NarrationScopeMismatch,
    NarrationServiceError,
    SqlAlchemyNarrationStore,
    canonical_sha256,
    require_local_novel,
)
from .settings import NarrationSettingsUpdate, update_settings
from .voice_product import (
    CanonicalOfficialPresetVoice,
    _complete_receipt,
    _db_now,
    _reserve_receipt,
    _stable_uuid,
    ensure_canonical_official_preset_voice,
)
from .voices import voice_profile_resource


OFFICIAL_VOICE_SELECTION_OPERATION: Final = "official_preset_selection"
OFFICIAL_VOICE_SELECTION_ACTOR: Final = "local-owner"
_IDEMPOTENCY_KEY: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")

SessionFactory = Callable[[], Session]


def _required_idempotency_key(value: str) -> str:
    if type(value) is not str or _IDEMPOTENCY_KEY.fullmatch(value) is None:
        raise NarrationServiceError(
            "official voice idempotency key is outside the frozen format"
        )
    return value


def _selection_request_hash(
    *,
    novel_id: UUID,
    request: wire.OfficialVoiceSelectionRequest,
) -> str:
    scope = NarrationRequestScope.fixed_local()
    return canonical_sha256(
        {
            "contract_version": "official-voice-selection/1.0",
            "operation": OFFICIAL_VOICE_SELECTION_OPERATION,
            "owner_id": str(scope.owner_id),
            "workspace_id": str(scope.workspace_id),
            "novel_id": str(novel_id),
            "preset_id": request.preset_id,
            "target_kind": request.target_kind.value,
            "character_id": (
                str(request.character_id) if request.character_id is not None else None
            ),
            "expected_settings_version": request.expected_settings_version,
            "expected_binding_version": request.expected_binding_version,
        }
    )


def _required_command(
    session: Session,
    *,
    command_id: UUID,
) -> VoiceActionCommand | None:
    return session.scalar(
        select(VoiceActionCommand)
        .where(VoiceActionCommand.id == command_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _assert_command_identity(
    command: VoiceActionCommand,
    *,
    novel_id: UUID,
    request: wire.OfficialVoiceSelectionRequest,
    request_hash: str,
) -> None:
    scope = NarrationRequestScope.fixed_local()
    if (
        command.owner_id != scope.owner_id
        or command.workspace_id != scope.workspace_id
        or command.novel_id != novel_id
        or command.operation != OFFICIAL_VOICE_SELECTION_OPERATION
        or command.target_kind != request.target_kind.value
        or command.target_character_id != request.character_id
        or command.preset_key != request.preset_id
        or command.request_hash != request_hash
    ):
        raise IdempotencyConflict(
            "official voice command key already names another request"
        )
    if command.state not in {"reserved", "completed"}:
        raise InvalidNarrationState("official voice command state is invalid")


def _frozen_result(command: VoiceActionCommand) -> wire.OfficialVoiceSelectionResult:
    if (
        command.state != "completed"
        or command.completed_at is None
        or command.profile_id is None
        or command.voice_version_id is None
        or command.settings_version is None
        or command.target_language is None
        or command.language_mismatch is None
    ):
        raise InvalidNarrationState("official voice command is not completed")
    try:
        target_kind = wire.OfficialVoiceSelectionTargetKind(command.target_kind)
        result = wire.OfficialVoiceSelectionResult(
            command_id=command.id,
            preset_id=command.preset_key,
            target_kind=target_kind,
            character_id=command.target_character_id,
            profile_id=command.profile_id,
            version_id=command.voice_version_id,
            settings_version=command.settings_version,
            binding_version=command.binding_version,
            target_language=command.target_language,
            language_mismatch=command.language_mismatch,
            completed_at=command.completed_at,
        )
    except (TypeError, ValueError) as error:
        raise InvalidNarrationState(
            "official voice command columns cannot reconstruct the frozen result"
        ) from error
    return result


def _response_for_result(
    session: Session,
    *,
    novel_id: UUID,
    result: wire.OfficialVoiceSelectionResult,
    replayed: bool,
) -> wire.OfficialVoiceSelectionResponse:
    store = SqlAlchemyNarrationStore(session)
    profile = store.get(VoiceProfile, result.profile_id)
    scope = NarrationRequestScope.fixed_local()
    if profile is None:
        raise InvalidNarrationState(
            "completed official voice command has no profile projection"
        )
    if (
        profile.owner_id != scope.owner_id
        or profile.workspace_id != scope.workspace_id
        or profile.novel_id != novel_id
    ):
        raise NarrationScopeMismatch(
            "completed official voice profile left its novel scope"
        )
    projected_profile = voice_profile_resource(store, profile)
    if result.target_kind is wire.OfficialVoiceSelectionTargetKind.NARRATOR:
        settings = get_narration_settings(store, novel_id=novel_id)
        narrator = settings.values.narrator
        still_current = (
            narrator is not None
            and narrator.profile_id == result.profile_id
            and narrator.version_id == result.version_id
        )
        return _selection_response(
            replayed=replayed,
            result=result,
            profile=projected_profile,
            settings=settings,
            character_binding=None,
            selection_still_current=still_current,
        )
    if result.character_id is None:
        raise InvalidNarrationState(
            "completed character voice command lost its character identity"
        )
    binding = get_character_voice_binding(
        store,
        novel_id=novel_id,
        character_id=result.character_id,
    )
    still_current = (
        binding.profile_id == result.profile_id
        and binding.version_id == result.version_id
    )
    return _selection_response(
        replayed=replayed,
        result=result,
        profile=projected_profile,
        settings=None,
        character_binding=binding,
        selection_still_current=still_current,
    )


def _selection_response(
    *,
    replayed: bool,
    result: wire.OfficialVoiceSelectionResult,
    profile: wire.VoiceProfileResource,
    settings: wire.NarrationSettingsResource | None,
    character_binding: wire.CharacterVoiceBindingResource | None,
    selection_still_current: bool,
) -> wire.OfficialVoiceSelectionResponse:
    return wire.OfficialVoiceSelectionResponse(
        replayed=replayed,
        selection_still_current=selection_still_current,
        frozen_result=result,
        profile=profile,
        current_settings=settings,
        current_character_binding=character_binding,
    )


def _locked_settings_projection(
    store: SqlAlchemyNarrationStore,
    *,
    novel_id: UUID,
) -> wire.NarrationSettingsResource:
    # The Novel mutex protects the first-row/phantom case.  Lock an existing
    # settings row as well so the target CAS is explicit and auditable.
    store.find_one(NovelNarrationSettings, novel_id=novel_id, for_update=True)
    return get_narration_settings(store, novel_id=novel_id)


def _materialize_default_settings(
    store: SqlAlchemyNarrationStore,
    *,
    current: wire.NarrationSettingsResource,
) -> wire.NarrationSettingsResource:
    if current.exists:
        return current
    values = current.values
    update_settings(
        store,
        NarrationSettingsUpdate(
            novel_id=current.novel_id,
            script_review_policy=values.script_review_policy.value,
            analysis_mode=values.analysis_mode.value,
            settings_json=_storage_settings(values),
            expected_version=0,
            narrator_profile_id=None,
            narrator_version_id=None,
        ),
    )
    return get_narration_settings(store, novel_id=current.novel_id)


def _apply_narrator(
    store: SqlAlchemyNarrationStore,
    *,
    current: wire.NarrationSettingsResource,
    canonical: CanonicalOfficialPresetVoice,
) -> wire.NarrationSettingsResource:
    selected = wire.NarratorVoiceSelection(
        profile_id=canonical.profile.id,
        version_id=canonical.version.id,
    )
    if current.exists and current.values.narrator == selected:
        return current
    values = current.values
    update_settings(
        store,
        NarrationSettingsUpdate(
            novel_id=current.novel_id,
            script_review_policy=values.script_review_policy.value,
            analysis_mode=values.analysis_mode.value,
            settings_json=_storage_settings(values),
            expected_version=current.version,
            narrator_profile_id=canonical.profile.id,
            narrator_version_id=canonical.version.id,
        ),
    )
    return get_narration_settings(store, novel_id=current.novel_id)


class OfficialVoiceSelectionService:
    """Narrow settings-backend port with one independent short transaction."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        actor: str = OFFICIAL_VOICE_SELECTION_ACTOR,
    ) -> None:
        if not callable(session_factory):
            raise TypeError("official voice selection requires a session factory")
        if (
            type(actor) is not str
            or not actor
            or actor != actor.strip()
            or len(actor) > 120
        ):
            raise ValueError("official voice selection actor is invalid")
        self._session_factory = session_factory
        self._actor = actor

    def select_official_voice(
        self,
        *,
        novel_id: UUID,
        request: wire.OfficialVoiceSelectionRequest,
        idempotency_key: str,
    ) -> wire.OfficialVoiceSelectionResponse:
        if not isinstance(novel_id, UUID):
            raise NarrationServiceError("novel_id must be a UUID")
        if not isinstance(request, wire.OfficialVoiceSelectionRequest):
            raise NarrationServiceError(
                "official voice request does not match the frozen contract"
            )
        key = _required_idempotency_key(idempotency_key)
        with self._session_factory() as session:
            if session.in_transaction():
                raise RuntimeError(
                    "official voice selection received a pre-opened transaction"
                )
            with session.begin():
                return self._select_in_session(
                    session,
                    novel_id=novel_id,
                    request=request,
                    idempotency_key=key,
                )

    def _select_in_session(
        self,
        session: Session,
        *,
        novel_id: UUID,
        request: wire.OfficialVoiceSelectionRequest,
        idempotency_key: str,
    ) -> wire.OfficialVoiceSelectionResponse:
        store = SqlAlchemyNarrationStore(session)
        # Scope is checked before an idempotency lookup can disclose a command.
        require_local_novel(store, novel_id)
        request_hash = _selection_request_hash(novel_id=novel_id, request=request)
        command_id = _stable_uuid(
            OFFICIAL_VOICE_SELECTION_OPERATION,
            idempotency_key,
        )
        receipt = _reserve_receipt(
            session,
            operation=OFFICIAL_VOICE_SELECTION_OPERATION,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            resource_id=command_id,
        )
        command = _required_command(session, command_id=command_id)
        if receipt.state == "completed":
            if command is None:
                raise InvalidNarrationState(
                    "completed official voice receipt has no command"
                )
            _assert_command_identity(
                command,
                novel_id=novel_id,
                request=request,
                request_hash=request_hash,
            )
            # Deliberately before every mutable target lock and CAS check.
            result = _frozen_result(command)
            return _response_for_result(
                session,
                novel_id=novel_id,
                result=result,
                replayed=True,
            )
        if receipt.replay or command is not None:
            raise InvalidNarrationState(
                "reserved official voice receipt has inconsistent command state"
            )

        created_at = _db_now(session)
        scope = NarrationRequestScope.fixed_local()
        command = VoiceActionCommand(
            id=command_id,
            owner_id=scope.owner_id,
            workspace_id=scope.workspace_id,
            novel_id=novel_id,
            operation=OFFICIAL_VOICE_SELECTION_OPERATION,
            target_kind=request.target_kind.value,
            target_character_id=request.character_id,
            preset_key=request.preset_id,
            request_hash=request_hash,
            state="reserved",
            profile_id=None,
            voice_version_id=None,
            settings_version=None,
            binding_version=None,
            target_language=None,
            language_mismatch=None,
            created_at=created_at,
            completed_at=None,
        )
        session.add(command)
        session.flush()

        # New commands alone acquire the aggregate/target locks and enforce
        # the transparent settings/binding CAS values.
        require_local_novel(store, novel_id, for_update=True)
        settings = _locked_settings_projection(store, novel_id=novel_id)
        if settings.version != request.expected_settings_version:
            raise NarrationCasConflict("narration settings version changed")

        binding_row: CharacterVoiceBinding | None = None
        if request.target_kind is wire.OfficialVoiceSelectionTargetKind.CHARACTER:
            if request.character_id is None or request.expected_binding_version is None:
                raise InvalidNarrationState(
                    "character official voice target is incomplete"
                )
            character = _require_character(
                store,
                novel_id=novel_id,
                character_id=request.character_id,
                for_update=True,
            )
            if character.lifecycle_state != "active":
                raise InvalidNarrationState(
                    "archived character voice binding cannot change"
                )
            binding_row = store.find_one(
                CharacterVoiceBinding,
                character_id=request.character_id,
                for_update=True,
            )
            binding_version = 0 if binding_row is None else binding_row.version
            if binding_version != request.expected_binding_version:
                raise NarrationCasConflict("character voice binding version changed")

        canonical = ensure_canonical_official_preset_voice(
            session,
            novel_id=novel_id,
            preset_id=request.preset_id,
            actor=self._actor,
            at=_db_now(session),
        )
        target_language = settings.values.language
        language_mismatch = (
            canonical.preset.language.split("-", 1)[0].casefold()
            != target_language.split("-", 1)[0].casefold()
        )

        projected_settings: wire.NarrationSettingsResource | None = None
        projected_binding: wire.CharacterVoiceBindingResource | None = None
        if request.target_kind is wire.OfficialVoiceSelectionTargetKind.NARRATOR:
            projected_settings = _apply_narrator(
                store,
                current=settings,
                canonical=canonical,
            )
            settings_version = projected_settings.version
            binding_version = None
        else:
            settings = _materialize_default_settings(store, current=settings)
            if request.character_id is None or request.expected_binding_version is None:
                raise InvalidNarrationState(
                    "character official voice target is incomplete"
                )
            projected_binding = put_character_voice_binding(
                store,
                novel_id=novel_id,
                character_id=request.character_id,
                request=wire.PutCharacterVoiceBindingRequest(
                    expected_version=request.expected_binding_version,
                    binding_policy=wire.CharacterVoiceBindingPolicy.DEDICATED,
                    profile_id=canonical.profile.id,
                    version_id=canonical.version.id,
                    language=target_language,
                ),
            )
            settings_version = settings.version
            binding_version = projected_binding.version

        if settings_version < 1 or (
            request.target_kind is wire.OfficialVoiceSelectionTargetKind.CHARACTER
            and (binding_version is None or binding_version < 1)
        ):
            raise InvalidNarrationState(
                "official voice selection did not produce positive target versions"
            )
        completed_at = _db_now(session)
        result = wire.OfficialVoiceSelectionResult(
            command_id=command.id,
            preset_id=canonical.preset.preset_id,
            target_kind=request.target_kind,
            character_id=request.character_id,
            profile_id=canonical.profile.id,
            version_id=canonical.version.id,
            settings_version=settings_version,
            binding_version=binding_version,
            target_language=target_language,
            language_mismatch=language_mismatch,
            completed_at=completed_at,
        )
        command.state = "completed"
        command.profile_id = canonical.profile.id
        command.voice_version_id = canonical.version.id
        command.settings_version = settings_version
        command.binding_version = binding_version
        command.target_language = target_language
        command.language_mismatch = language_mismatch
        command.completed_at = completed_at
        _complete_receipt(session, receipt.row_id, at=completed_at)
        session.flush()

        # Build from the exact rows already locked/written in this transaction.
        return _selection_response(
            replayed=False,
            result=result,
            profile=voice_profile_resource(store, canonical.profile, at=completed_at),
            settings=projected_settings,
            character_binding=projected_binding,
            selection_still_current=True,
        )


__all__ = [
    "OFFICIAL_VOICE_SELECTION_ACTOR",
    "OFFICIAL_VOICE_SELECTION_OPERATION",
    "OfficialVoiceSelectionService",
]
