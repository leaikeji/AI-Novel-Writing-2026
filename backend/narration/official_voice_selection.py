"""Atomic narrator/character selection of pinned official Nano voices.

The service owns one short database transaction.  It never calls Nano or
publishes media; official provenance, rights and version construction remain
owned by :mod:`voice_product`.
"""

from __future__ import annotations

from dataclasses import dataclass
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
DEFAULT_NARRATOR_PRESET_ID: Final = "onnx.Junhao"
_IDEMPOTENCY_KEY: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")

SessionFactory = Callable[[], Session]


@dataclass(frozen=True, slots=True)
class OfficialVoiceBatchSelection:
    """One deterministic target inside an all-or-nothing selection batch."""

    target_key: str
    request: wire.OfficialVoiceSelectionRequest
    idempotency_key: str


def _selection_target_key(request: wire.OfficialVoiceSelectionRequest) -> str:
    if request.target_kind is wire.OfficialVoiceSelectionTargetKind.NARRATOR:
        return "narrator"
    if request.character_id is None:
        raise InvalidNarrationState("character official voice target is incomplete")
    return f"character:{request.character_id}"


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
        target_key = _selection_target_key(request)
        responses = self.select_official_voices_atomically(
            novel_id=novel_id,
            selections=(
                OfficialVoiceBatchSelection(
                    target_key=target_key,
                    request=request,
                    idempotency_key=idempotency_key,
                ),
            ),
        )
        return responses[0]

    def select_official_voices_atomically(
        self,
        *,
        novel_id: UUID,
        selections: tuple[OfficialVoiceBatchSelection, ...],
    ) -> tuple[wire.OfficialVoiceSelectionResponse, ...]:
        """Apply one or more official voices in one short transaction.

        Receipt reservation, aggregate/target locks, canonical preset creation,
        binding writes, command completion and projections share one commit.
        Any scope or CAS error therefore rolls back every target.
        """

        if not isinstance(novel_id, UUID):
            raise NarrationServiceError("novel_id must be a UUID")
        if not selections:
            raise NarrationServiceError("official voice batch cannot be empty")
        normalized: list[OfficialVoiceBatchSelection] = []
        seen_targets: set[str] = set()
        for selection in selections:
            if not isinstance(selection, OfficialVoiceBatchSelection):
                raise NarrationServiceError(
                    "official voice batch item does not match the frozen contract"
                )
            if not isinstance(selection.request, wire.OfficialVoiceSelectionRequest):
                raise NarrationServiceError(
                    "official voice request does not match the frozen contract"
                )
            expected_target = _selection_target_key(selection.request)
            if selection.target_key != expected_target:
                raise NarrationServiceError("official voice batch target key drifted")
            if selection.target_key in seen_targets:
                raise NarrationServiceError("official voice batch targets must be unique")
            seen_targets.add(selection.target_key)
            normalized.append(
                OfficialVoiceBatchSelection(
                    target_key=selection.target_key,
                    request=selection.request,
                    idempotency_key=_required_idempotency_key(
                        selection.idempotency_key
                    ),
                )
            )
        with self._session_factory() as session:
            if session.in_transaction():
                raise RuntimeError(
                    "official voice selection received a pre-opened transaction"
                )
            with session.begin():
                return self._select_many_in_session(
                    session,
                    novel_id=novel_id,
                    selections=tuple(normalized),
                )

    def select_official_voices_atomically_in_session(
        self,
        session: Session,
        *,
        novel_id: UUID,
        selections: tuple[OfficialVoiceBatchSelection, ...],
    ) -> tuple[wire.OfficialVoiceSelectionResponse, ...]:
        """Use the batch path inside a caller-owned short transaction."""

        if not isinstance(session, Session) or not session.in_transaction():
            raise RuntimeError("atomic official voice batch requires an active session")
        if not isinstance(novel_id, UUID) or not selections:
            raise NarrationServiceError("official voice batch scope is invalid")
        normalized: list[OfficialVoiceBatchSelection] = []
        seen_targets: set[str] = set()
        for selection in selections:
            if not isinstance(selection, OfficialVoiceBatchSelection) or not isinstance(
                selection.request,
                wire.OfficialVoiceSelectionRequest,
            ):
                raise NarrationServiceError(
                    "official voice batch item does not match the frozen contract"
                )
            target_key = _selection_target_key(selection.request)
            if selection.target_key != target_key or target_key in seen_targets:
                raise NarrationServiceError("official voice batch target scope drifted")
            seen_targets.add(target_key)
            normalized.append(
                OfficialVoiceBatchSelection(
                    target_key=target_key,
                    request=selection.request,
                    idempotency_key=_required_idempotency_key(
                        selection.idempotency_key
                    ),
                )
            )
        return self._select_many_in_session(
            session,
            novel_id=novel_id,
            selections=tuple(normalized),
        )

    def _select_many_in_session(
        self,
        session: Session,
        *,
        novel_id: UUID,
        selections: tuple[OfficialVoiceBatchSelection, ...],
    ) -> tuple[wire.OfficialVoiceSelectionResponse, ...]:
        store = SqlAlchemyNarrationStore(session)
        # Scope precedes idempotency lookup so a key cannot disclose another novel.
        require_local_novel(store, novel_id)
        ordered = tuple(sorted(selections, key=lambda item: item.target_key))
        scope = NarrationRequestScope.fixed_local()
        entries: dict[str, tuple[str, UUID, object, VoiceActionCommand | None]] = {}
        for selection in ordered:
            request_hash = _selection_request_hash(
                novel_id=novel_id,
                request=selection.request,
            )
            command_id = _stable_uuid(
                OFFICIAL_VOICE_SELECTION_OPERATION,
                selection.idempotency_key,
            )
            receipt = _reserve_receipt(
                session,
                operation=OFFICIAL_VOICE_SELECTION_OPERATION,
                idempotency_key=selection.idempotency_key,
                request_hash=request_hash,
                resource_id=command_id,
            )
            command = _required_command(session, command_id=command_id)
            entries[selection.target_key] = (
                request_hash,
                command_id,
                receipt,
                command,
            )

        completed = [
            selection
            for selection in ordered
            if entries[selection.target_key][2].state == "completed"  # type: ignore[attr-defined]
        ]
        if completed:
            if len(completed) != len(ordered):
                raise InvalidNarrationState(
                    "official voice batch cannot mix completed and new targets"
                )
            replayed_by_target: dict[str, wire.OfficialVoiceSelectionResponse] = {}
            for selection in ordered:
                request_hash, _command_id, _receipt, command = entries[
                    selection.target_key
                ]
                if command is None:
                    raise InvalidNarrationState(
                        "completed official voice receipt has no command"
                    )
                _assert_command_identity(
                    command,
                    novel_id=novel_id,
                    request=selection.request,
                    request_hash=request_hash,
                )
                replayed_by_target[selection.target_key] = _response_for_result(
                    session,
                    novel_id=novel_id,
                    result=_frozen_result(command),
                    replayed=True,
                )
            return tuple(
                replayed_by_target[selection.target_key]
                for selection in selections
            )

        created_at = _db_now(session)
        commands: dict[str, VoiceActionCommand] = {}
        receipts: dict[str, object] = {}
        for selection in ordered:
            request_hash, command_id, receipt, command = entries[selection.target_key]
            if receipt.replay or command is not None:  # type: ignore[attr-defined]
                raise InvalidNarrationState(
                    "reserved official voice receipt has inconsistent command state"
                )
            command = VoiceActionCommand(
                id=command_id,
                owner_id=scope.owner_id,
                workspace_id=scope.workspace_id,
                novel_id=novel_id,
                operation=OFFICIAL_VOICE_SELECTION_OPERATION,
                target_kind=selection.request.target_kind.value,
                target_character_id=selection.request.character_id,
                preset_key=selection.request.preset_id,
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
            commands[selection.target_key] = command
            receipts[selection.target_key] = receipt
        session.flush()

        # All mutable locks follow one global order: novel, settings, characters,
        # bindings and finally canonical preset versions.
        require_local_novel(store, novel_id, for_update=True)
        settings = _locked_settings_projection(store, novel_id=novel_id)
        if any(
            selection.request.expected_settings_version != settings.version
            for selection in ordered
        ):
            raise NarrationCasConflict("narration settings version changed")

        character_selections = tuple(
            selection
            for selection in ordered
            if selection.request.target_kind
            is wire.OfficialVoiceSelectionTargetKind.CHARACTER
        )
        for selection in character_selections:
            character_id = selection.request.character_id
            expected_binding = selection.request.expected_binding_version
            if character_id is None or expected_binding is None:
                raise InvalidNarrationState(
                    "character official voice target is incomplete"
                )
            character = _require_character(
                store,
                novel_id=novel_id,
                character_id=character_id,
                for_update=True,
            )
            if character.lifecycle_state != "active":
                raise InvalidNarrationState(
                    "archived character voice binding cannot change"
                )
        for selection in character_selections:
            assert selection.request.character_id is not None
            binding_row = store.find_one(
                CharacterVoiceBinding,
                character_id=selection.request.character_id,
                for_update=True,
            )
            binding_version = 0 if binding_row is None else binding_row.version
            if binding_version != selection.request.expected_binding_version:
                raise NarrationCasConflict("character voice binding version changed")

        canonicals: dict[str, CanonicalOfficialPresetVoice] = {}
        for preset_id in sorted({item.request.preset_id for item in ordered}):
            canonicals[preset_id] = ensure_canonical_official_preset_voice(
                session,
                novel_id=novel_id,
                preset_id=preset_id,
                actor=self._actor,
                at=_db_now(session),
            )

        narrator_selection = next(
            (
                selection
                for selection in ordered
                if selection.request.target_kind
                is wire.OfficialVoiceSelectionTargetKind.NARRATOR
            ),
            None,
        )
        projected_settings: wire.NarrationSettingsResource | None = None
        if narrator_selection is not None:
            projected_settings = _apply_narrator(
                store,
                current=settings,
                canonical=canonicals[narrator_selection.request.preset_id],
            )
            settings = projected_settings
        elif character_selections:
            settings = _materialize_default_settings(store, current=settings)

        target_language = settings.values.language
        projected_bindings: dict[str, wire.CharacterVoiceBindingResource] = {}
        for selection in character_selections:
            assert selection.request.character_id is not None
            assert selection.request.expected_binding_version is not None
            canonical = canonicals[selection.request.preset_id]
            projected_bindings[selection.target_key] = put_character_voice_binding(
                store,
                novel_id=novel_id,
                character_id=selection.request.character_id,
                request=wire.PutCharacterVoiceBindingRequest(
                    expected_version=selection.request.expected_binding_version,
                    binding_policy=wire.CharacterVoiceBindingPolicy.DEDICATED,
                    profile_id=canonical.profile.id,
                    version_id=canonical.version.id,
                    language=target_language,
                ),
            )

        completed_at = _db_now(session)
        responses: dict[str, wire.OfficialVoiceSelectionResponse] = {}
        for selection in ordered:
            request = selection.request
            command = commands[selection.target_key]
            receipt = receipts[selection.target_key]
            canonical = canonicals[request.preset_id]
            projected_binding = projected_bindings.get(selection.target_key)
            binding_version = (
                projected_binding.version if projected_binding is not None else None
            )
            if settings.version < 1 or (
                request.target_kind
                is wire.OfficialVoiceSelectionTargetKind.CHARACTER
                and (binding_version is None or binding_version < 1)
            ):
                raise InvalidNarrationState(
                    "official voice selection did not produce positive target versions"
                )
            language_mismatch = (
                canonical.preset.language.split("-", 1)[0].casefold()
                != target_language.split("-", 1)[0].casefold()
            )
            result = wire.OfficialVoiceSelectionResult(
                command_id=command.id,
                preset_id=canonical.preset.preset_id,
                target_kind=request.target_kind,
                character_id=request.character_id,
                profile_id=canonical.profile.id,
                version_id=canonical.version.id,
                settings_version=settings.version,
                binding_version=binding_version,
                target_language=target_language,
                language_mismatch=language_mismatch,
                completed_at=completed_at,
            )
            command.state = "completed"
            command.profile_id = canonical.profile.id
            command.voice_version_id = canonical.version.id
            command.settings_version = settings.version
            command.binding_version = binding_version
            command.target_language = target_language
            command.language_mismatch = language_mismatch
            command.completed_at = completed_at
            _complete_receipt(session, receipt.row_id, at=completed_at)  # type: ignore[attr-defined]
            responses[selection.target_key] = _selection_response(
                replayed=False,
                result=result,
                profile=voice_profile_resource(
                    store,
                    canonical.profile,
                    at=completed_at,
                ),
                settings=(
                    settings
                    if request.target_kind
                    is wire.OfficialVoiceSelectionTargetKind.NARRATOR
                    else None
                ),
                character_binding=projected_binding,
                selection_still_current=True,
            )
        session.flush()
        return tuple(responses[selection.target_key] for selection in selections)


def initialize_new_novel_default_narrator(
    session: Session,
    *,
    novel_id: UUID,
) -> wire.NarrationSettingsResource:
    """Create the project-wide narrator default inside the novel transaction.

    Official profiles are novel-scoped, so a future-book default cannot be a
    shared profile UUID.  Materialize the pinned preset through the same
    receipt, provenance, rights and CAS path as an explicit author selection.
    """

    if not isinstance(session, Session) or not session.in_transaction():
        raise RuntimeError("new-novel narrator initialization requires an active session")
    response = OfficialVoiceSelectionService(
        lambda: session
    ).select_official_voices_atomically_in_session(
        session,
        novel_id=novel_id,
        selections=(
            OfficialVoiceBatchSelection(
                target_key="narrator",
                request=wire.OfficialVoiceSelectionRequest(
                    preset_id=DEFAULT_NARRATOR_PRESET_ID,
                    target_kind=wire.OfficialVoiceSelectionTargetKind.NARRATOR,
                    expected_settings_version=0,
                ),
                idempotency_key=f"new-novel-default-narrator:{novel_id}",
            ),
        ),
    )[0]
    if response.current_settings is None:
        raise InvalidNarrationState("new-novel narrator initialization lost settings")
    return response.current_settings


__all__ = [
    "DEFAULT_NARRATOR_PRESET_ID",
    "OFFICIAL_VOICE_SELECTION_ACTOR",
    "OFFICIAL_VOICE_SELECTION_OPERATION",
    "OfficialVoiceBatchSelection",
    "OfficialVoiceSelectionService",
    "initialize_new_novel_default_narrator",
]
