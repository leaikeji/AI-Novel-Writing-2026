"""Durable, recoverable whole-book official-voice casting commands.

Every method owns only a short database transaction. Model calls are performed
by the HTTP orchestration layer after ``claim_next`` commits its lease. The
final official-voice writes and cast-command completion share one transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import re
from typing import Callable, Mapping
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..character_workspace.contracts import CharacterWorkspaceError
from ..character_workspace.service import service_for_session
from ..creative_data_models import CharacterInstance, StoryTimeline
from ..models import (
    CharacterCastPlanCommand,
    CharacterCastPlanItem,
    CharacterVoiceBinding,
    Novel,
    NovelCharacter,
    VoiceProfile,
    VoiceProfileVersion,
)
from . import schemas as wire
from .character_casting import (
    CastDecisionStatus,
    CastRole,
    CastTarget,
    CastTargetKind,
    CastVoiceSource,
    CharacterCastSolution,
    CurrentCastVoice,
    solve_character_cast,
)
from .character_voice_matching import (
    CharacterVoiceBrief,
    CharacterVoiceLanguage,
    CharacterVoiceMatchingError,
    load_official_voice_casting_baseline,
    parse_character_voice_brief,
    score_official_voice_candidates,
)
from .contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID
from .narrator_voice_brief import NarratorVoiceBrief, parse_narrator_voice_brief
from .official_presets import (
    OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256,
    OFFICIAL_PRESETS,
    OFFICIAL_PRESETS_BY_ID,
    official_preset_canonical_profile_id,
    official_preset_canonical_version_id,
)
from .official_voice_selection import (
    OfficialVoiceBatchSelection,
    OfficialVoiceSelectionService,
)
from .privacy import get_narration_settings
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


CAST_PLAN_MODE = "fill_and_deduplicate"
CAST_PLAN_LEASE_SECONDS = 15 * 60
CAST_PLAN_ALL_TARGETS_FAILED = "CAST_PLAN_ALL_TARGETS_FAILED"
CAST_PLAN_AUTHORITY_DRIFT = "CAST_PLAN_AUTHORITY_DRIFT"
CAST_PLAN_MODEL_FAILED = "CAST_PLAN_MODEL_FAILED"
CAST_PLAN_WORKSPACE_UNAVAILABLE = "CAST_PLAN_WORKSPACE_UNAVAILABLE"
CAST_PLAN_LEASE_RECOVERED = "CAST_PLAN_LEASE_RECOVERED"
CAST_PLAN_APPLY_CONFLICT = "CAST_PLAN_APPLY_CONFLICT"

ACTIVE_STATES = frozenset({"reserved", "analyzing"})
TERMINAL_STATES = frozenset(
    {
        "ready_applied",
        "ready_applied_with_warnings",
        "ready_unapplied",
        "failed",
        "superseded",
    }
)
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
_STABLE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,95}$")

SessionFactory = Callable[[], Session]


@dataclass(frozen=True, slots=True)
class CharacterCastPlanReservation:
    command_id: UUID
    replayed: bool


@dataclass(frozen=True, slots=True)
class CharacterCastPlanLease:
    command_id: UUID
    item_id: UUID
    target_key: str
    target_kind: str
    character_id: UUID | None
    timeline_id: UUID
    attempt: int
    fence_token: UUID
    lease_expires_at: datetime
    workspace_digest: str
    prompt_payload: Mapping[str, object]
    narration_language: str


@dataclass(frozen=True, slots=True)
class CharacterCastTargetAnalysis:
    workspace_digest: str
    brief: CharacterVoiceBrief | NarratorVoiceBrief
    model_evidence: Mapping[str, object]


def _transaction(factory: SessionFactory, operation):
    with factory() as session:
        try:
            value = operation(session)
            session.commit()
            return value
        except BaseException:
            session.rollback()
            raise


def _required_idempotency_key(value: str) -> str:
    if type(value) is not str or _IDEMPOTENCY_KEY.fullmatch(value) is None:
        raise InvalidNarrationState("cast plan idempotency key is invalid")
    return value


def character_cast_plan_request_hash(
    *, novel_id: UUID, timeline_id: UUID, mode: str = CAST_PLAN_MODE
) -> str:
    return canonical_sha256(
        {
            "contract_version": "character-cast-plan-request/1",
            "novel_id": str(novel_id),
            "timeline_id": str(timeline_id),
            "mode": mode,
        }
    )


def _narrator_payload(novel: Novel, narration_language: str) -> dict[str, object]:
    return {
        "narration_settings": {"language": narration_language},
        "novel": {
            "title": novel.title,
            "genre": novel.genre,
            "subgenre": novel.subgenre,
            "description": novel.description,
            "idea": novel.idea,
            "highlight": novel.highlight,
            "background": novel.background,
            "main_plot": novel.main_plot,
        },
    }


def _character_workspace_payload(workspace: object) -> dict[str, object]:
    return {
        "character": workspace.character.model_dump(mode="json"),
        "selected_instance": workspace.selected_instance.model_dump(mode="json"),
        "aliases": [item.model_dump(mode="json") for item in workspace.aliases],
        "relationships": [
            item.model_dump(mode="json") for item in workspace.relationships
        ],
        "projected_state": workspace.projected_state.model_dump(mode="json"),
    }


def _unavailable_character_payload(
    *,
    character: NovelCharacter,
    character_catalog_version: int,
    timeline_id: UUID,
) -> dict[str, object]:
    """Freeze the same fail-closed payload everywhere it is re-evaluated."""

    return {
        "character": {
            "id": str(character.id),
            "version": character.version,
            "catalog_version": character_catalog_version,
        },
        "timeline_id": str(timeline_id),
        "workspace_unavailable": True,
    }


def _active_instance_id(
    session: Session,
    *,
    novel_id: UUID,
    character_id: UUID,
    timeline_id: UUID,
) -> UUID | None:
    return session.scalar(
        select(CharacterInstance.id)
        .where(
            CharacterInstance.novel_id == novel_id,
            CharacterInstance.character_id == character_id,
            CharacterInstance.origin_timeline_id == timeline_id,
            CharacterInstance.lifecycle_state == "active",
        )
        .order_by(CharacterInstance.id)
        .limit(1)
    )


def _character_payload(
    session: Session,
    *,
    novel_id: UUID,
    character_id: UUID,
    timeline_id: UUID,
) -> dict[str, object]:
    instance_id = _active_instance_id(
        session,
        novel_id=novel_id,
        character_id=character_id,
        timeline_id=timeline_id,
    )
    workspace = service_for_session(session).get_workspace(
        novel_id,
        character_id,
        timeline_id=timeline_id,
        character_instance_id=instance_id,
    )
    return _character_workspace_payload(workspace)


def _workspace_digest(payload: Mapping[str, object]) -> str:
    return canonical_sha256(canonical_payload(dict(payload)))


def _catalog_fingerprint() -> str:
    baseline = load_official_voice_casting_baseline()
    return canonical_sha256(
        {
            "schema_version": "character-cast-catalog/1",
            "model_fingerprint": OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256,
            "baseline_sha256": baseline.file_sha256,
            "preset_ids": [preset.preset_id for preset in OFFICIAL_PRESETS],
        }
    )


def _settings_digest(settings: wire.NarrationSettingsResource) -> str:
    values = settings.values.model_dump(mode="json")
    playback = values.get("playback")
    if type(playback) is not dict:
        raise InvalidNarrationState("narration playback settings are malformed")
    # Narration fingerprints intentionally reject binary floats.  Match the
    # bounded round-trip representation used by settings persistence so the
    # cast command can freeze and later compare the complete public resource.
    playback_rate = playback.get("playback_rate")
    volume = playback.get("volume")
    if type(playback_rate) is not float or type(volume) is not float:
        raise InvalidNarrationState("narration playback settings are malformed")
    values["playback"] = {
        "playback_rate": str(playback_rate),
        "volume": str(volume),
    }
    return canonical_sha256(
        {
            "version": settings.version,
            "exists": settings.exists,
            "values": values,
        }
    )


def _bindings_digest(
    settings: wire.NarrationSettingsResource,
    characters: tuple[NovelCharacter, ...],
    bindings: Mapping[UUID, CharacterVoiceBinding],
) -> str:
    narrator = settings.values.narrator
    return canonical_sha256(
        {
            "narrator": (
                None
                if narrator is None
                else {
                    "profile_id": str(narrator.profile_id),
                    "version_id": str(narrator.version_id),
                }
            ),
            "characters": [
                {
                    "character_id": str(character.id),
                    "binding_version": (
                        bindings[character.id].version
                        if character.id in bindings
                        else 0
                    ),
                    "profile_id": (
                        str(bindings[character.id].profile_id)
                        if character.id in bindings
                        and bindings[character.id].profile_id is not None
                        else None
                    ),
                    "version_id": (
                        str(bindings[character.id].voice_version_id)
                        if character.id in bindings
                        and bindings[character.id].voice_version_id is not None
                        else None
                    ),
                }
                for character in characters
            ],
        }
    )


def _role_rank(role_type: str) -> int:
    return 1 if role_type == "main" else 2


def _load_voice_identity(
    session: Session,
    *,
    novel_id: UUID,
    profile_id: UUID | None,
    version_id: UUID | None,
) -> tuple[VoiceProfile | None, VoiceProfileVersion | None]:
    if profile_id is None or version_id is None:
        return None, None
    profile = session.get(VoiceProfile, profile_id)
    version = session.get(VoiceProfileVersion, version_id)
    if (
        profile is None
        or version is None
        or version.profile_id != profile.id
        or profile.novel_id != novel_id
        or profile.owner_id != LOCAL_OWNER_ID
        or profile.workspace_id != LOCAL_WORKSPACE_ID
        or version.owner_id != LOCAL_OWNER_ID
        or version.workspace_id != LOCAL_WORKSPACE_ID
    ):
        return None, None
    return profile, version


def _canonical_official_available(
    *, novel_id: UUID, profile: VoiceProfile | None, version: VoiceProfileVersion | None
) -> bool:
    if (
        profile is None
        or version is None
        or version.source_type != "preset"
        or version.preset_key not in OFFICIAL_PRESETS_BY_ID
        or profile.status != "active"
        or version.state != "locked"
    ):
        return False
    expected_profile = official_preset_canonical_profile_id(
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        novel_id=novel_id,
        preset_id=version.preset_key,
    )
    expected_version = official_preset_canonical_version_id(
        profile_id=expected_profile,
        preset_id=version.preset_key,
    )
    return profile.id == expected_profile and version.id == expected_version


def _warning(code: str, target_key: str | None, message: str) -> dict[str, object]:
    if _STABLE_CODE.fullmatch(code) is None:
        raise ValueError("cast warning code is invalid")
    return {"code": code, "target_key": target_key, "message": message}


def _append_warning(row: CharacterCastPlanCommand, warning: dict[str, object]) -> None:
    current = list(row.warnings_json or [])
    if warning not in current:
        current.append(warning)
    row.warnings_json = current


def _required_command(
    session: Session,
    *,
    novel_id: UUID,
    command_id: UUID,
    for_update: bool,
) -> CharacterCastPlanCommand:
    statement = select(CharacterCastPlanCommand).where(
        CharacterCastPlanCommand.id == command_id,
        CharacterCastPlanCommand.novel_id == novel_id,
        CharacterCastPlanCommand.owner_id == LOCAL_OWNER_ID,
        CharacterCastPlanCommand.workspace_id == LOCAL_WORKSPACE_ID,
    )
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    row = session.scalar(statement)
    if row is None:
        raise NarrationNotFound("character cast plan not found")
    return row


def _items(
    session: Session,
    command_id: UUID,
    *,
    for_update: bool,
) -> list[CharacterCastPlanItem]:
    statement = (
        select(CharacterCastPlanItem)
        .where(CharacterCastPlanItem.command_id == command_id)
        .order_by(CharacterCastPlanItem.position, CharacterCastPlanItem.id)
    )
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return list(session.scalars(statement))


def _terminal(
    command: CharacterCastPlanCommand,
    *,
    state: str,
    now: datetime,
    failure_code: str | None = None,
) -> None:
    if state not in TERMINAL_STATES:
        raise ValueError("cast terminal state is invalid")
    command.state = state
    command.progress_current = command.progress_total
    command.failure_code = failure_code
    command.completed_at = now
    command.updated_at = now


def _target_resource(item: CharacterCastPlanItem) -> wire.CharacterCastTargetResource:
    return wire.CharacterCastTargetResource(
        target_key=item.target_key,
        target_kind=item.target_kind,
        character_id=item.character_id,
        character_name=item.character_name,
        role_type=item.role_type,
    )


def _brief_resource(item: CharacterCastPlanItem):
    if item.brief_json is None:
        return None
    if item.target_kind == "narrator":
        return wire.NarratorVoiceBriefResource.model_validate(item.brief_json)
    return wire.CharacterVoiceBriefResource.model_validate(item.brief_json)


def _resource(
    session: Session,
    command: CharacterCastPlanCommand,
    *,
    now: datetime,
) -> wire.CharacterCastPlanResource:
    rows = _items(session, command.id, for_update=False)
    active = next((item for item in rows if item.state == "analyzing"), None)
    item_resources = [
        wire.CharacterCastPlanItemResource(
            item_id=item.id,
            target=_target_resource(item),
            state=item.state,
            attempt=item.attempt,
            workspace_digest=item.workspace_digest,
            lease_expires_at=item.lease_expires_at,
            brief=_brief_resource(item),
            selected_preset_id=(
                item.selected_preset_key
                if item.selected_preset_key is not None
                else (
                    item.current_preset_key
                    if item.state == "preserved"
                    else None
                )
            ),
            score_milli=item.score_milli,
            profile_id=item.profile_id,
            version_id=item.voice_version_id,
            voice_action_command_id=item.voice_action_command_id,
            warning_code=item.warning_code,
            failure_code=item.failure_code,
        )
        for item in rows
    ]
    assignments = [
        wire.CharacterCastAssignmentResource(
            target=_target_resource(item),
            preset_id=item.selected_preset_key,
            score_milli=item.score_milli,
            voice_action_command_id=item.voice_action_command_id,
        )
        for item in rows
        if item.state == "assigned"
        and item.selected_preset_key is not None
        and item.score_milli is not None
    ]
    preserved = [
        wire.CharacterCastPreservedResource(
            target=_target_resource(item),
            profile_id=item.profile_id,
            version_id=item.voice_version_id,
            preset_id=item.current_preset_key,
            source_type=item.voice_source_type,
        )
        for item in rows
        if item.state == "preserved"
        and item.profile_id is not None
        and item.voice_version_id is not None
        and item.voice_source_type in {"preset", "uploaded", "generated"}
    ]
    warnings = [
        wire.CharacterCastWarningResource.model_validate(warning)
        for warning in command.warnings_json or []
    ]
    terminal = command.state in TERMINAL_STATES
    retryable = command.state == "failed" and any(
        item.state == "blocked" and item.failure_code == CAST_PLAN_MODEL_FAILED
        for item in rows
    )
    return wire.CharacterCastPlanResource(
        command_id=command.id,
        novel_id=command.novel_id,
        timeline_id=command.timeline_id,
        mode=command.mode,
        state=command.state,
        server_now=now,
        progress_current=command.progress_current,
        progress_total=command.progress_total,
        terminal=terminal,
        retryable=retryable,
        current_target_key=active.target_key if active is not None else None,
        lease_expires_at=active.lease_expires_at if active is not None else None,
        assignments=assignments,
        preserved=preserved,
        warnings=warnings,
        items=item_resources,
        failure_code=command.failure_code,
        created_at=command.created_at,
        updated_at=command.updated_at,
        completed_at=command.completed_at,
    )


def _no_assignment_terminal_state(
    solution: CharacterCastSolution,
    *,
    has_warnings: bool,
) -> tuple[str, str | None]:
    if solution.blocked or not solution.preserved:
        return "failed", CAST_PLAN_ALL_TARGETS_FAILED
    return (
        "ready_applied_with_warnings" if has_warnings else "ready_applied",
        None,
    )


class SqlAlchemyCharacterCastPlanService:
    """Persistent command authority used by HTTP and future agent tools."""

    def __init__(self, session_factory: SessionFactory) -> None:
        if not callable(session_factory):
            raise TypeError("character cast plan requires a session factory")
        self._session_factory = session_factory

    def reserve(
        self,
        *,
        novel_id: UUID,
        timeline_id: UUID,
        idempotency_key: str,
        request_hash: str,
    ) -> CharacterCastPlanReservation:
        key = _required_idempotency_key(idempotency_key)

        def operation(session: Session) -> CharacterCastPlanReservation:
            store = SqlAlchemyNarrationStore(session)
            novel = require_local_novel(store, novel_id, for_update=True)
            timeline = session.scalar(
                select(StoryTimeline)
                .where(
                    StoryTimeline.id == timeline_id,
                    StoryTimeline.novel_id == novel_id,
                    StoryTimeline.lifecycle_state == "active",
                )
                .with_for_update()
            )
            if timeline is None:
                raise NarrationNotFound("story timeline not found")
            replay = session.scalar(
                select(CharacterCastPlanCommand)
                .where(
                    CharacterCastPlanCommand.owner_id == LOCAL_OWNER_ID,
                    CharacterCastPlanCommand.workspace_id == LOCAL_WORKSPACE_ID,
                    CharacterCastPlanCommand.novel_id == novel_id,
                    CharacterCastPlanCommand.idempotency_key == key,
                )
                .with_for_update()
            )
            if replay is not None:
                if (
                    replay.timeline_id != timeline_id
                    or replay.mode != CAST_PLAN_MODE
                    or replay.request_hash != request_hash
                ):
                    raise IdempotencyConflict("cast plan idempotency key was reused")
                return CharacterCastPlanReservation(replay.id, True)

            active = session.scalar(
                select(CharacterCastPlanCommand.id).where(
                    CharacterCastPlanCommand.novel_id == novel_id,
                    CharacterCastPlanCommand.timeline_id == timeline_id,
                    CharacterCastPlanCommand.state.in_(tuple(ACTIVE_STATES)),
                )
            )
            if active is not None:
                return CharacterCastPlanReservation(active, True)

            settings = get_narration_settings(store, novel_id=novel_id)
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
            binding_rows = tuple(
                session.scalars(
                    select(CharacterVoiceBinding).where(
                        CharacterVoiceBinding.novel_id == novel_id
                    )
                )
            )
            bindings = {row.character_id: row for row in binding_rows}

            target_rows: list[dict[str, object]] = []
            narrator_payload = _narrator_payload(novel, settings.values.language)
            narrator = settings.values.narrator
            target_rows.append(
                {
                    "target_key": "narrator",
                    "target_kind": "narrator",
                    "character": None,
                    "character_name": None,
                    "role_type": None,
                    "priority_rank": 0,
                    "expected_binding_version": 0,
                    "payload": narrator_payload,
                    "workspace_digest": _workspace_digest(narrator_payload),
                    "profile_id": narrator.profile_id if narrator else None,
                    "version_id": narrator.version_id if narrator else None,
                    "workspace_failed": False,
                }
            )
            for character in characters:
                try:
                    payload = _character_payload(
                        session,
                        novel_id=novel_id,
                        character_id=character.id,
                        timeline_id=timeline_id,
                    )
                    workspace_failed = False
                except CharacterWorkspaceError:
                    payload = _unavailable_character_payload(
                        character=character,
                        character_catalog_version=novel.character_catalog_version,
                        timeline_id=timeline_id,
                    )
                    workspace_failed = True
                binding = bindings.get(character.id)
                target_rows.append(
                    {
                        "target_key": f"character:{character.id}",
                        "target_kind": "character",
                        "character": character,
                        "character_name": character.name,
                        "role_type": character.role_type,
                        "priority_rank": _role_rank(character.role_type),
                        "expected_binding_version": (
                            binding.version if binding is not None else 0
                        ),
                        "payload": payload,
                        "workspace_digest": _workspace_digest(payload),
                        "profile_id": binding.profile_id if binding else None,
                        "version_id": binding.voice_version_id if binding else None,
                        "workspace_failed": workspace_failed,
                    }
                )

            official_groups: dict[str, list[dict[str, object]]] = {}
            protected_groups: dict[str, list[str]] = {}
            for target in target_rows:
                profile, version = _load_voice_identity(
                    session,
                    novel_id=novel_id,
                    profile_id=target["profile_id"],  # type: ignore[arg-type]
                    version_id=target["version_id"],  # type: ignore[arg-type]
                )
                target["voice_source_type"] = (
                    version.source_type if version is not None else None
                )
                target["current_preset_key"] = (
                    version.preset_key if version is not None else None
                )
                official = _canonical_official_available(
                    novel_id=novel_id,
                    profile=profile,
                    version=version,
                )
                target["official_available"] = official
                protected_private = (
                    version is not None
                    and not official
                    and (
                        version.source_type in {"uploaded", "generated"}
                        or version.activation_basis
                        == "experimental_machine_validated"
                        or (
                            version.source_type == "preset"
                            and version.preset_key not in OFFICIAL_PRESETS_BY_ID
                        )
                    )
                )
                target["protected_private"] = protected_private
                if official and version is not None and version.preset_key is not None:
                    official_groups.setdefault(version.preset_key, []).append(target)
                elif protected_private and version is not None:
                    protected_groups.setdefault(str(version.id), []).append(
                        str(target["target_key"])
                    )

            preserved_targets: set[str] = set()
            for rows in official_groups.values():
                winner = min(
                    rows,
                    key=lambda value: (
                        int(value["priority_rank"]),
                        str(
                            value["character"].id  # type: ignore[union-attr]
                            if value["character"] is not None
                            else "narrator"
                        ),
                    ),
                )
                preserved_targets.add(str(winner["target_key"]))
            for target in target_rows:
                if bool(target.get("protected_private")):
                    preserved_targets.add(str(target["target_key"]))

            warnings: list[dict[str, object]] = []
            for identity, keys in protected_groups.items():
                if len(keys) > 1:
                    for target_key in sorted(keys):
                        warnings.append(
                            _warning(
                                "PROTECTED_VOICE_SHARED",
                                target_key,
                                "多个角色共用私人或专属音色，已按作者现有设置保留。",
                            )
                        )
            now = datetime.now(UTC)
            command = CharacterCastPlanCommand(
                id=uuid4(),
                owner_id=LOCAL_OWNER_ID,
                workspace_id=LOCAL_WORKSPACE_ID,
                novel_id=novel_id,
                timeline_id=timeline_id,
                mode=CAST_PLAN_MODE,
                idempotency_key=key,
                request_hash=request_hash,
                state="reserved",
                character_catalog_version=novel.character_catalog_version,
                settings_version=settings.version,
                catalog_fingerprint=_catalog_fingerprint(),
                workspace_digest=canonical_sha256(
                    [
                        {
                            "target_key": target["target_key"],
                            "workspace_digest": target["workspace_digest"],
                        }
                        for target in target_rows
                    ]
                ),
                settings_digest=_settings_digest(settings),
                bindings_digest=_bindings_digest(settings, characters, bindings),
                progress_current=0,
                progress_total=len(target_rows),
                warnings_json=warnings,
                created_at=now,
                updated_at=now,
            )
            session.add(command)
            session.flush()
            processed = 0
            for position, target in enumerate(target_rows):
                target_key = str(target["target_key"])
                if target_key in preserved_targets:
                    state = "preserved"
                    failure_code = None
                    processed += 1
                elif bool(target["workspace_failed"]):
                    state = "blocked"
                    failure_code = CAST_PLAN_WORKSPACE_UNAVAILABLE
                    processed += 1
                    _append_warning(
                        command,
                        _warning(
                            CAST_PLAN_WORKSPACE_UNAVAILABLE,
                            target_key,
                            "人物工作区暂不可用于声音分析，已跳过该人物。",
                        ),
                    )
                else:
                    state = "pending"
                    failure_code = None
                character = target["character"]
                session.add(
                    CharacterCastPlanItem(
                        id=uuid4(),
                        command_id=command.id,
                        novel_id=novel_id,
                        position=position,
                        priority_rank=int(target["priority_rank"]),
                        target_key=target_key,
                        target_kind=str(target["target_kind"]),
                        character_id=(
                            character.id if character is not None else None  # type: ignore[union-attr]
                        ),
                        character_name=target["character_name"],
                        role_type=target["role_type"],
                        expected_binding_version=int(
                            target["expected_binding_version"]
                        ),
                        workspace_digest=str(target["workspace_digest"]),
                        state=state,
                        attempt=0,
                        profile_id=target["profile_id"],
                        voice_version_id=target["version_id"],
                        voice_source_type=target["voice_source_type"],
                        current_preset_key=target["current_preset_key"],
                        failure_code=failure_code,
                        created_at=now,
                        updated_at=now,
                    )
                )
            command.progress_current = processed
            try:
                session.flush()
            except IntegrityError as error:
                raise InvalidNarrationState(
                    "another active cast plan already exists"
                ) from error
            return CharacterCastPlanReservation(command.id, False)

        return _transaction(self._session_factory, operation)

    def list_resources(self, *, novel_id: UUID) -> wire.CharacterCastPlanListResource:
        def operation(session: Session) -> wire.CharacterCastPlanListResource:
            require_local_novel(SqlAlchemyNarrationStore(session), novel_id)
            rows = tuple(
                session.scalars(
                    select(CharacterCastPlanCommand)
                    .where(CharacterCastPlanCommand.novel_id == novel_id)
                    .order_by(
                        CharacterCastPlanCommand.created_at.desc(),
                        CharacterCastPlanCommand.id.desc(),
                    )
                    .limit(20)
                )
            )
            now = datetime.now(UTC)
            return wire.CharacterCastPlanListResource(
                novel_id=novel_id,
                server_now=now,
                items=[_resource(session, row, now=now) for row in rows],
            )

        return _transaction(self._session_factory, operation)

    def get_resource(
        self, *, novel_id: UUID, command_id: UUID
    ) -> wire.CharacterCastPlanResource:
        def operation(session: Session) -> wire.CharacterCastPlanResource:
            row = _required_command(
                session,
                novel_id=novel_id,
                command_id=command_id,
                for_update=False,
            )
            now = datetime.now(UTC)
            return _resource(session, row, now=now)

        return _transaction(self._session_factory, operation)

    def _current_prompt_payload(
        self,
        session: Session,
        command: CharacterCastPlanCommand,
        item: CharacterCastPlanItem,
    ) -> tuple[dict[str, object], str]:
        settings = get_narration_settings(
            SqlAlchemyNarrationStore(session), novel_id=command.novel_id
        )
        if item.target_kind == "narrator":
            novel = session.get(Novel, command.novel_id)
            if novel is None:
                raise NarrationNotFound("novel not found")
            return _narrator_payload(novel, settings.values.language), settings.values.language
        if item.character_id is None:
            raise InvalidNarrationState("character cast item lost its identity")
        return (
            _character_payload(
                session,
                novel_id=command.novel_id,
                character_id=item.character_id,
                timeline_id=command.timeline_id,
            ),
            settings.values.language,
        )

    def claim_next(
        self, *, novel_id: UUID, command_id: UUID
    ) -> CharacterCastPlanLease | None:
        def operation(session: Session) -> CharacterCastPlanLease | None:
            command = _required_command(
                session,
                novel_id=novel_id,
                command_id=command_id,
                for_update=True,
            )
            if command.state in TERMINAL_STATES:
                return None
            rows = _items(session, command.id, for_update=True)
            now = datetime.now(UTC)
            for item in rows:
                if (
                    item.state == "analyzing"
                    and item.lease_expires_at is not None
                    and item.lease_expires_at <= now
                ):
                    item.state = "pending"
                    item.lease_fence = None
                    item.lease_expires_at = None
                    item.updated_at = now
                    _append_warning(
                        command,
                        _warning(
                            CAST_PLAN_LEASE_RECOVERED,
                            item.target_key,
                            "上一次声音分析中断，已从持久命令恢复。",
                        ),
                    )
            active = next((item for item in rows if item.state == "analyzing"), None)
            if active is not None:
                session.flush()
                return None
            item = next((row for row in rows if row.state == "pending"), None)
            if item is None:
                session.flush()
                return None
            try:
                payload, narration_language = self._current_prompt_payload(
                    session, command, item
                )
            except CharacterWorkspaceError:
                for unfinished in rows:
                    if unfinished.state in {"pending", "analyzing"}:
                        unfinished.state = "blocked"
                        unfinished.failure_code = CAST_PLAN_AUTHORITY_DRIFT
                        unfinished.lease_fence = None
                        unfinished.lease_expires_at = None
                        unfinished.updated_at = now
                _append_warning(
                    command,
                    _warning(
                        CAST_PLAN_AUTHORITY_DRIFT,
                        item.target_key,
                        "人物工作区已变化或暂不可用，本次旧方案未应用。",
                    ),
                )
                _terminal(command, state="ready_unapplied", now=now)
                session.flush()
                return None
            current_digest = _workspace_digest(payload)
            if current_digest != item.workspace_digest:
                for pending in rows:
                    if pending.state in {"pending", "analyzing"}:
                        pending.state = "blocked"
                        pending.failure_code = CAST_PLAN_AUTHORITY_DRIFT
                        pending.lease_fence = None
                        pending.lease_expires_at = None
                        pending.updated_at = now
                _append_warning(
                    command,
                    _warning(
                        CAST_PLAN_AUTHORITY_DRIFT,
                        item.target_key,
                        "人物或小说资料已变化，本次旧方案未应用。",
                    ),
                )
                _terminal(command, state="ready_unapplied", now=now)
                session.flush()
                return None
            fence = uuid4()
            expires = now + timedelta(seconds=CAST_PLAN_LEASE_SECONDS)
            item.state = "analyzing"
            item.attempt += 1
            item.lease_fence = fence
            item.lease_expires_at = expires
            item.failure_code = None
            item.updated_at = now
            command.state = "analyzing"
            command.updated_at = now
            session.flush()
            return CharacterCastPlanLease(
                command_id=command.id,
                item_id=item.id,
                target_key=item.target_key,
                target_kind=item.target_kind,
                character_id=item.character_id,
                timeline_id=command.timeline_id,
                attempt=item.attempt,
                fence_token=fence,
                lease_expires_at=expires,
                workspace_digest=item.workspace_digest,
                prompt_payload=canonical_payload(payload),
                narration_language=narration_language,
            )

        return _transaction(self._session_factory, operation)

    def finish_analysis(
        self,
        *,
        novel_id: UUID,
        command_id: UUID,
        item_id: UUID,
        attempt: int,
        fence_token: UUID,
        analysis: CharacterCastTargetAnalysis,
    ) -> bool:
        if type(analysis) is not CharacterCastTargetAnalysis:
            raise TypeError("cast analysis has an invalid shape")

        def operation(session: Session) -> bool:
            command = _required_command(
                session,
                novel_id=novel_id,
                command_id=command_id,
                for_update=True,
            )
            item = session.scalar(
                select(CharacterCastPlanItem)
                .where(
                    CharacterCastPlanItem.id == item_id,
                    CharacterCastPlanItem.command_id == command.id,
                )
                .with_for_update()
            )
            if item is None:
                raise NarrationNotFound("cast plan target not found")
            if (
                item.state != "analyzing"
                or item.attempt != attempt
                or item.lease_fence != fence_token
            ):
                return False
            if analysis.workspace_digest != item.workspace_digest:
                now = datetime.now(UTC)
                rows = _items(session, command.id, for_update=True)
                for unfinished in rows:
                    if unfinished.state in {"pending", "analyzing"}:
                        unfinished.state = "blocked"
                        unfinished.failure_code = CAST_PLAN_AUTHORITY_DRIFT
                        unfinished.lease_fence = None
                        unfinished.lease_expires_at = None
                        unfinished.updated_at = now
                _append_warning(
                    command,
                    _warning(
                        CAST_PLAN_AUTHORITY_DRIFT,
                        item.target_key,
                        "分析结果与已冻结的人物资料不一致，本次旧方案未应用。",
                    ),
                )
                _terminal(command, state="ready_unapplied", now=now)
                session.flush()
                return False
            try:
                payload, _narration_language = self._current_prompt_payload(
                    session, command, item
                )
            except CharacterWorkspaceError:
                payload = None
            if payload is None or _workspace_digest(payload) != item.workspace_digest:
                now = datetime.now(UTC)
                rows = _items(session, command.id, for_update=True)
                for unfinished in rows:
                    if unfinished.state in {"pending", "analyzing"}:
                        unfinished.state = "blocked"
                        unfinished.failure_code = CAST_PLAN_AUTHORITY_DRIFT
                        unfinished.lease_fence = None
                        unfinished.lease_expires_at = None
                        unfinished.updated_at = now
                _append_warning(
                    command,
                    _warning(
                        CAST_PLAN_AUTHORITY_DRIFT,
                        item.target_key,
                        "人物或小说资料已变化，本次旧方案未应用。",
                    ),
                )
                _terminal(command, state="ready_unapplied", now=now)
                session.flush()
                return False
            if item.target_kind == "narrator":
                if type(analysis.brief) is not NarratorVoiceBrief:
                    raise TypeError("narrator cast target requires NarratorVoiceBrief")
            elif type(analysis.brief) is not CharacterVoiceBrief:
                raise TypeError("character cast target requires CharacterVoiceBrief")
            settings = get_narration_settings(
                SqlAlchemyNarrationStore(session), novel_id=novel_id
            )
            try:
                fallback = CharacterVoiceLanguage(settings.values.language)
            except ValueError:
                fallback = None
            effective_language = analysis.brief.language or fallback
            now = datetime.now(UTC)
            try:
                candidates = score_official_voice_candidates(
                    analysis.brief,
                    effective_language=effective_language,
                )
            except CharacterVoiceMatchingError as error:
                item.state = "blocked"
                item.failure_code = error.code
                item.warning_code = error.code
                item.brief_schema_version = analysis.brief.schema_version
                item.brief_json = canonical_payload(analysis.brief.to_payload())
                item.model_evidence_json = canonical_payload(
                    dict(analysis.model_evidence)
                )
                item.model_evidence_digest = canonical_sha256(
                    item.model_evidence_json
                )
                item.language = (
                    effective_language.value if effective_language is not None else None
                )
                _append_warning(
                    command,
                    _warning(
                        error.code,
                        item.target_key,
                        "声音资料不足以自动选择官方音色，已保留给作者手动处理。",
                    ),
                )
            else:
                best = max(candidates, key=lambda candidate: candidate.score_milli)
                item.state = "scored"
                item.failure_code = None
                item.warning_code = None
                item.brief_schema_version = analysis.brief.schema_version
                item.brief_json = canonical_payload(analysis.brief.to_payload())
                item.model_evidence_json = canonical_payload(
                    dict(analysis.model_evidence)
                )
                item.model_evidence_digest = canonical_sha256(
                    item.model_evidence_json
                )
                item.language = (
                    effective_language.value if effective_language is not None else None
                )
                item.selected_preset_key = best.preset_id
                item.score_milli = best.score_milli
            item.lease_fence = None
            item.lease_expires_at = None
            item.updated_at = now
            command.progress_current += 1
            command.updated_at = now
            session.flush()
            return True

        return _transaction(self._session_factory, operation)

    def fail_analysis(
        self,
        *,
        novel_id: UUID,
        command_id: UUID,
        item_id: UUID,
        attempt: int,
        fence_token: UUID,
        failure_code: str = CAST_PLAN_MODEL_FAILED,
    ) -> bool:
        if _STABLE_CODE.fullmatch(failure_code) is None:
            raise ValueError("cast model failure code is invalid")

        def operation(session: Session) -> bool:
            command = _required_command(
                session,
                novel_id=novel_id,
                command_id=command_id,
                for_update=True,
            )
            item = session.scalar(
                select(CharacterCastPlanItem)
                .where(
                    CharacterCastPlanItem.id == item_id,
                    CharacterCastPlanItem.command_id == command.id,
                )
                .with_for_update()
            )
            if item is None:
                raise NarrationNotFound("cast plan target not found")
            if (
                item.state != "analyzing"
                or item.attempt != attempt
                or item.lease_fence != fence_token
            ):
                return False
            now = datetime.now(UTC)
            item.state = "blocked"
            item.failure_code = CAST_PLAN_MODEL_FAILED
            item.warning_code = failure_code
            item.lease_fence = None
            item.lease_expires_at = None
            item.updated_at = now
            command.progress_current += 1
            command.updated_at = now
            _append_warning(
                command,
                _warning(
                    failure_code,
                    item.target_key,
                    "该目标的声音分析失败，其余目标仍会继续。",
                ),
            )
            session.flush()
            return True

        return _transaction(self._session_factory, operation)

    def _authority_matches(
        self,
        session: Session,
        command: CharacterCastPlanCommand,
        rows: list[CharacterCastPlanItem],
    ) -> bool:
        store = SqlAlchemyNarrationStore(session)
        novel = require_local_novel(store, command.novel_id, for_update=True)
        if novel.character_catalog_version != command.character_catalog_version:
            return False
        if _catalog_fingerprint() != command.catalog_fingerprint:
            return False
        settings = get_narration_settings(store, novel_id=command.novel_id)
        if (
            settings.version != command.settings_version
            or _settings_digest(settings) != command.settings_digest
        ):
            return False
        characters = tuple(
            session.scalars(
                select(NovelCharacter)
                .where(
                    NovelCharacter.novel_id == command.novel_id,
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
            binding.character_id: binding
            for binding in session.scalars(
                select(CharacterVoiceBinding).where(
                    CharacterVoiceBinding.novel_id == command.novel_id
                )
            )
        }
        if _bindings_digest(settings, characters, bindings) != command.bindings_digest:
            return False
        digests: list[dict[str, str]] = []
        characters_by_id = {character.id: character for character in characters}
        for item in rows:
            try:
                payload, _language = self._current_prompt_payload(
                    session, command, item
                )
            except CharacterWorkspaceError:
                if item.failure_code != CAST_PLAN_WORKSPACE_UNAVAILABLE:
                    return False
                character = characters_by_id.get(item.character_id)
                if character is None:
                    return False
                payload = _unavailable_character_payload(
                    character=character,
                    character_catalog_version=novel.character_catalog_version,
                    timeline_id=command.timeline_id,
                )
            digest = _workspace_digest(payload)
            if digest != item.workspace_digest:
                return False
            digests.append({"target_key": item.target_key, "workspace_digest": digest})
        return canonical_sha256(digests) == command.workspace_digest

    @staticmethod
    def _cast_source(
        *,
        novel_id: UUID,
        profile: VoiceProfile | None,
        version: VoiceProfileVersion | None,
    ) -> CurrentCastVoice | None:
        if profile is None or version is None:
            return None
        if _canonical_official_available(
            novel_id=novel_id, profile=profile, version=version
        ):
            assert version.preset_key is not None
            return CurrentCastVoice(
                source=CastVoiceSource.OFFICIAL,
                identity_key=version.preset_key,
                preset_id=version.preset_key,
                available=True,
            )
        if version.source_type == "uploaded":
            source = CastVoiceSource.UPLOADED
        elif version.source_type == "generated":
            source = CastVoiceSource.GENERATED
        else:
            # A non-canonical preset includes Nano experiments and stale
            # official versions. Experiments are private and protected; stale
            # direct official versions are deliberately eligible for repair.
            if version.activation_basis == "experimental_machine_validated":
                source = CastVoiceSource.PRIVATE
            elif version.preset_key in OFFICIAL_PRESETS_BY_ID:
                return CurrentCastVoice(
                    source=CastVoiceSource.OFFICIAL,
                    identity_key=version.preset_key or str(version.id),
                    preset_id=version.preset_key,
                    available=False,
                )
            else:
                # Unknown/non-canonical sources are author-owned by default.
                # Never invent an official preset identity merely to feed the
                # solver; preserving is the only fail-closed interpretation.
                source = CastVoiceSource.PRIVATE
        return CurrentCastVoice(source=source, identity_key=str(version.id))

    def _solution(
        self,
        session: Session,
        command: CharacterCastPlanCommand,
        rows: list[CharacterCastPlanItem],
    ) -> CharacterCastSolution:
        settings = get_narration_settings(
            SqlAlchemyNarrationStore(session), novel_id=command.novel_id
        )
        try:
            fallback = CharacterVoiceLanguage(settings.values.language)
        except ValueError:
            fallback = None
        targets: list[CastTarget] = []
        for item in rows:
            profile, version = _load_voice_identity(
                session,
                novel_id=command.novel_id,
                profile_id=item.profile_id,
                version_id=item.voice_version_id,
            )
            brief: CharacterVoiceBrief | NarratorVoiceBrief | None
            if item.brief_json is None:
                brief = None
            elif item.target_kind == "narrator":
                brief = parse_narrator_voice_brief(item.brief_json)
            else:
                brief = parse_character_voice_brief(item.brief_json)
            role = (
                CastRole.NARRATOR
                if item.target_kind == "narrator"
                else (CastRole.MAIN if item.role_type == "main" else CastRole.SUPPORTING)
            )
            targets.append(
                CastTarget(
                    target_key=item.target_key,
                    stable_id=(
                        "narrator"
                        if item.character_id is None
                        else str(item.character_id)
                    ),
                    kind=(
                        CastTargetKind.NARRATOR
                        if item.target_kind == "narrator"
                        else CastTargetKind.CHARACTER
                    ),
                    role=role,
                    brief=brief,
                    fallback_language=fallback,
                    current_voice=self._cast_source(
                        novel_id=command.novel_id,
                        profile=profile,
                        version=version,
                    ),
                )
            )
        return solve_character_cast(tuple(targets))

    def finalize_if_ready(
        self, *, novel_id: UUID, command_id: UUID
    ) -> wire.CharacterCastPlanResource:
        def operation(session: Session) -> wire.CharacterCastPlanResource:
            command = _required_command(
                session,
                novel_id=novel_id,
                command_id=command_id,
                for_update=True,
            )
            now = datetime.now(UTC)
            if command.state in TERMINAL_STATES:
                return _resource(session, command, now=now)
            rows = _items(session, command.id, for_update=True)
            if any(item.state in {"pending", "analyzing"} for item in rows):
                return _resource(session, command, now=now)
            if not self._authority_matches(session, command, rows):
                _append_warning(
                    command,
                    _warning(
                        CAST_PLAN_AUTHORITY_DRIFT,
                        None,
                        "人物、设置或声音绑定已变化，本次旧方案未应用。",
                    ),
                )
                _terminal(command, state="ready_unapplied", now=now)
                session.flush()
                return _resource(session, command, now=now)

            solution = self._solution(session, command, rows)
            rows_by_key = {item.target_key: item for item in rows}
            for warning in solution.warnings:
                for target_key in warning.target_keys or (None,):
                    _append_warning(
                        command,
                        _warning(
                            warning.code,
                            target_key,
                            "智能选角已保留现有声音或按音色容量完成安全复用。",
                        ),
                    )
            for decision in solution.decisions:
                item = rows_by_key[decision.target_key]
                if decision.status is CastDecisionStatus.PRESERVED:
                    item.state = "preserved"
                    item.failure_code = None
                elif decision.status is CastDecisionStatus.BLOCKED:
                    item.state = "blocked"
                    if item.failure_code != CAST_PLAN_MODEL_FAILED:
                        item.failure_code = decision.reason_code
                        item.warning_code = decision.reason_code
                        _append_warning(
                            command,
                            _warning(
                                decision.reason_code,
                                item.target_key,
                                "该目标缺少可评分声音资料，需作者手动选择。",
                            ),
                        )
                else:
                    item.selected_preset_key = decision.preset_id
                    item.score_milli = decision.score_milli

            assignments = solution.assignments
            if not assignments:
                terminal_state, failure_code = _no_assignment_terminal_state(
                    solution,
                    has_warnings=bool(command.warnings_json),
                )
                _terminal(
                    command,
                    state=terminal_state,
                    now=now,
                    failure_code=failure_code,
                )
                session.flush()
                return _resource(session, command, now=now)

            selections: list[OfficialVoiceBatchSelection] = []
            for decision in assignments:
                item = rows_by_key[decision.target_key]
                if decision.preset_id is None:
                    raise InvalidNarrationState("cast assignment lost its preset")
                selections.append(
                    OfficialVoiceBatchSelection(
                        target_key=item.target_key,
                        idempotency_key=f"cast:{command.id}:{item.target_key}",
                        request=wire.OfficialVoiceSelectionRequest(
                            preset_id=decision.preset_id,
                            target_kind=(
                                wire.OfficialVoiceSelectionTargetKind.NARRATOR
                                if item.target_kind == "narrator"
                                else wire.OfficialVoiceSelectionTargetKind.CHARACTER
                            ),
                            character_id=item.character_id,
                            expected_settings_version=command.settings_version,
                            expected_binding_version=(
                                item.expected_binding_version
                                if item.target_kind == "character"
                                else None
                            ),
                        ),
                    )
                )
            selection_service = OfficialVoiceSelectionService(self._session_factory)
            try:
                with session.begin_nested():
                    responses = selection_service.select_official_voices_atomically_in_session(
                        session,
                        novel_id=novel_id,
                        selections=tuple(selections),
                    )
            except (
                IdempotencyConflict,
                InvalidNarrationState,
                NarrationCasConflict,
                NarrationNotFound,
                NarrationScopeMismatch,
                IntegrityError,
            ):
                _append_warning(
                    command,
                    _warning(
                        CAST_PLAN_APPLY_CONFLICT,
                        None,
                        "应用前检测到并发修改，本次方案未覆盖作者的新选择。",
                    ),
                )
                _terminal(command, state="ready_unapplied", now=now)
                session.flush()
                return _resource(session, command, now=now)

            for selection, response in zip(selections, responses, strict=True):
                item = rows_by_key[selection.target_key]
                result = response.frozen_result
                item.state = "assigned"
                item.profile_id = result.profile_id
                item.voice_version_id = result.version_id
                item.voice_source_type = "preset"
                item.current_preset_key = result.preset_id
                item.voice_action_command_id = result.command_id
                item.failure_code = None
                item.updated_at = now
            _terminal(
                command,
                state=(
                    "ready_applied_with_warnings"
                    if command.warnings_json or solution.blocked
                    else "ready_applied"
                ),
                now=now,
            )
            session.flush()
            return _resource(session, command, now=now)

        return _transaction(self._session_factory, operation)

    def retry(
        self, *, novel_id: UUID, command_id: UUID
    ) -> wire.CharacterCastPlanResource:
        def operation(session: Session) -> wire.CharacterCastPlanResource:
            command = _required_command(
                session,
                novel_id=novel_id,
                command_id=command_id,
                for_update=True,
            )
            rows = _items(session, command.id, for_update=True)
            retry_rows = [
                item
                for item in rows
                if item.state == "blocked" and item.failure_code == CAST_PLAN_MODEL_FAILED
            ]
            if command.state != "failed" or not retry_rows:
                raise InvalidNarrationState("cast plan is not retryable")
            other_active = session.scalar(
                select(CharacterCastPlanCommand.id).where(
                    CharacterCastPlanCommand.novel_id == novel_id,
                    CharacterCastPlanCommand.timeline_id == command.timeline_id,
                    CharacterCastPlanCommand.id != command.id,
                    CharacterCastPlanCommand.state.in_(tuple(ACTIVE_STATES)),
                )
            )
            if other_active is not None:
                raise InvalidNarrationState("another cast plan is active")
            now = datetime.now(UTC)
            stale_warnings = {
                (item.target_key, item.warning_code)
                for item in retry_rows
                if item.warning_code is not None
            }
            command.warnings_json = [
                warning
                for warning in command.warnings_json or []
                if (
                    warning.get("target_key"),
                    warning.get("code"),
                )
                not in stale_warnings
            ]
            for item in retry_rows:
                item.state = "pending"
                item.failure_code = None
                item.warning_code = None
                item.updated_at = now
            command.state = "analyzing"
            command.progress_current -= len(retry_rows)
            command.failure_code = None
            command.completed_at = None
            command.updated_at = now
            session.flush()
            return _resource(session, command, now=now)

        return _transaction(self._session_factory, operation)


__all__ = [
    "CAST_PLAN_ALL_TARGETS_FAILED",
    "CAST_PLAN_AUTHORITY_DRIFT",
    "CAST_PLAN_LEASE_SECONDS",
    "CAST_PLAN_MODE",
    "CharacterCastPlanLease",
    "CharacterCastPlanReservation",
    "CharacterCastTargetAnalysis",
    "SqlAlchemyCharacterCastPlanService",
    "character_cast_plan_request_hash",
]
