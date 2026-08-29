"""Transactional ORM adapter for the pure story-state engine.

All mutations lock the novel ledger, enforce CAS, add the complete mutation
plan, and call ``flush`` only.  Commit and rollback remain the responsibility of
the public API/service transaction boundary.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from enum import Enum
from hashlib import sha256
import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..creative_data_models import (
    CharacterInstance,
    CharacterInstanceRevision,
    StoryEventLink,
    StoryTimeline,
    StoryTimelineLink,
)
from ..models import DerivedSourceBinding, Novel, NovelCharacter, StoryFact

from .contracts import (
    CharacterContinuityKind,
    CharacterInstanceRecord,
    LifecycleState,
    StoryEventLinkRecord,
    StoryEventLinkType,
    StoryFactV2,
    StoryProjection,
    StoryStateError,
    StoryStateErrorCode,
    StoryTimelineLinkRecord,
    StoryTimelineRecord,
    TimelineKind,
    TimelineLinkType,
)
from .engine import (
    build_default_story_state,
    build_timeline_link,
    fork_timeline as build_fork_plan,
    project_story_facts,
    resolve_character_instance,
    resolve_timeline,
)


IdFactory = Callable[[], UUID]
Clock = Callable[[], datetime]


class PersistenceErrorCode(str, Enum):
    NOVEL_NOT_FOUND = "novel_not_found"
    CHARACTER_NOT_FOUND = "character_not_found"
    VERSION_CONFLICT = "version_conflict"
    INVALID_PATCH = "invalid_patch"
    FACT_NOT_FOUND = "fact_not_found"
    FACT_SCHEMA_INVALID = "fact_schema_invalid"


class StoryStatePersistenceError(ValueError):
    def __init__(
        self,
        code: PersistenceErrorCode,
        message: str,
        *,
        current: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.current = current


_UNSET = object()


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _require_novel(session: Session, novel_id: UUID, *, for_update: bool) -> Novel:
    statement = select(Novel).where(Novel.id == novel_id)
    if for_update:
        statement = statement.with_for_update()
    novel = session.scalar(statement)
    if novel is None:
        raise StoryStatePersistenceError(
            PersistenceErrorCode.NOVEL_NOT_FOUND,
            "novel was not found in the requested scope",
        )
    return novel


def _lock_ledger(
    session: Session,
    novel_id: UUID,
    expected_story_ledger_version: int,
) -> Novel:
    novel = _require_novel(session, novel_id, for_update=True)
    if novel.story_ledger_version != expected_story_ledger_version:
        raise StoryStatePersistenceError(
            PersistenceErrorCode.VERSION_CONFLICT,
            "story ledger version changed",
            current={"story_ledger_version": novel.story_ledger_version},
        )
    return novel


def _timeline_rows(
    session: Session, novel_id: UUID, *, for_update: bool = False
) -> list[StoryTimeline]:
    statement = (
        select(StoryTimeline)
        .where(StoryTimeline.novel_id == novel_id)
        .order_by(StoryTimeline.position, StoryTimeline.id)
    )
    if for_update:
        statement = statement.with_for_update()
    return list(session.scalars(statement))


def _instance_rows(
    session: Session, novel_id: UUID, *, for_update: bool = False
) -> list[CharacterInstance]:
    statement = (
        select(CharacterInstance)
        .where(CharacterInstance.novel_id == novel_id)
        .order_by(CharacterInstance.created_at, CharacterInstance.id)
    )
    if for_update:
        statement = statement.with_for_update()
    return list(session.scalars(statement))


def _timeline_record(row: StoryTimeline) -> StoryTimelineRecord:
    return StoryTimelineRecord.model_validate(row)


def _instance_record(row: CharacterInstance) -> CharacterInstanceRecord:
    return CharacterInstanceRecord.model_validate(row)


def _event_link_record(row: StoryEventLink) -> StoryEventLinkRecord:
    return StoryEventLinkRecord.model_validate(row)


def story_event_link_payload(row: StoryEventLink) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "novel_id": str(row.novel_id),
        "source_fact_id": str(row.source_fact_id),
        "target_fact_id": str(row.target_fact_id),
        "link_type": row.link_type,
        "details": dict(row.details_json or {}),
        "created_at": _iso(row.created_at),
    }


def _fact_record(row: StoryFact) -> StoryFactV2:
    try:
        return StoryFactV2.model_validate(row)
    except ValueError as exc:
        raise StoryStatePersistenceError(
            PersistenceErrorCode.FACT_SCHEMA_INVALID,
            f"StoryFact v2 row is invalid: {row.id}",
        ) from exc


def _new_timeline(record: StoryTimelineRecord) -> StoryTimeline:
    return StoryTimeline(
        id=record.id,
        novel_id=record.novel_id,
        timeline_key=record.timeline_key,
        name=record.name,
        normalized_name=record.normalized_name,
        timeline_kind=record.timeline_kind.value,
        is_primary=record.is_primary,
        parent_timeline_id=record.parent_timeline_id,
        fork_story_sequence=record.fork_story_sequence,
        fork_anchor_json=record.fork_anchor_json,
        lifecycle_state=record.lifecycle_state.value,
        position=record.position,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _new_instance(
    record: CharacterInstanceRecord,
    *,
    current_revision_id: UUID | None = None,
) -> CharacterInstance:
    return CharacterInstance(
        id=record.id,
        novel_id=record.novel_id,
        character_id=record.character_id,
        origin_timeline_id=record.origin_timeline_id,
        derived_from_instance_id=record.derived_from_instance_id,
        continuity_kind=record.continuity_kind.value,
        display_label=record.display_label,
        current_revision_id=current_revision_id,
        lifecycle_state=record.lifecycle_state.value,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _new_timeline_link(record: StoryTimelineLinkRecord) -> StoryTimelineLink:
    return StoryTimelineLink(
        id=record.id,
        novel_id=record.novel_id,
        source_timeline_id=record.source_timeline_id,
        target_timeline_id=record.target_timeline_id,
        link_type=record.link_type.value,
        source_story_sequence=record.source_story_sequence,
        target_story_sequence=record.target_story_sequence,
        details_json=record.details_json,
        link_fingerprint=record.link_fingerprint,
        lifecycle_state=record.lifecycle_state.value,
        version=record.version,
        created_at=record.created_at,
    )


def timeline_payload(row: StoryTimeline) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "novel_id": str(row.novel_id),
        "timeline_key": row.timeline_key,
        "name": row.name,
        "timeline_kind": row.timeline_kind,
        "is_primary": row.is_primary,
        "parent_timeline_id": str(row.parent_timeline_id) if row.parent_timeline_id else None,
        "fork_story_sequence": row.fork_story_sequence,
        "fork_anchor": dict(row.fork_anchor_json or {}),
        "lifecycle_state": row.lifecycle_state,
        "position": row.position,
        "version": row.version,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def character_instance_payload(row: CharacterInstance) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "novel_id": str(row.novel_id),
        "character_id": str(row.character_id),
        "origin_timeline_id": str(row.origin_timeline_id),
        "derived_from_instance_id": (
            str(row.derived_from_instance_id) if row.derived_from_instance_id else None
        ),
        "continuity_kind": row.continuity_kind,
        "display_label": row.display_label,
        "current_revision_id": str(row.current_revision_id) if row.current_revision_id else None,
        "lifecycle_state": row.lifecycle_state,
        "version": row.version,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def timeline_link_payload(row: StoryTimelineLink) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "novel_id": str(row.novel_id),
        "source_timeline_id": str(row.source_timeline_id),
        "target_timeline_id": str(row.target_timeline_id),
        "link_type": row.link_type,
        "source_story_sequence": row.source_story_sequence,
        "target_story_sequence": row.target_story_sequence,
        "details": dict(row.details_json or {}),
        "link_fingerprint": row.link_fingerprint,
        "lifecycle_state": row.lifecycle_state,
        "version": row.version,
        "created_at": _iso(row.created_at),
    }


def story_fact_payload(row: StoryFact) -> dict[str, Any]:
    return _fact_record(row).model_dump(mode="json")


def projection_payload(projection: StoryProjection) -> dict[str, Any]:
    return projection.model_dump(mode="json")


def list_timeline_payloads(session: Session, novel_id: UUID) -> list[dict[str, Any]]:
    _require_novel(session, novel_id, for_update=False)
    return [timeline_payload(row) for row in _timeline_rows(session, novel_id)]


def get_timeline_payload(
    session: Session,
    novel_id: UUID,
    timeline_id: UUID | None = None,
) -> dict[str, Any]:
    _require_novel(session, novel_id, for_update=False)
    rows = _timeline_rows(session, novel_id)
    resolved = resolve_timeline([_timeline_record(row) for row in rows], novel_id, timeline_id)
    row_by_id = {row.id: row for row in rows}
    return timeline_payload(row_by_id[resolved.id])


def patch_timeline(
    session: Session,
    novel_id: UUID,
    timeline_id: UUID,
    *,
    expected_story_ledger_version: int,
    expected_timeline_version: int,
    name: str | object = _UNSET,
    lifecycle_state: LifecycleState | object = _UNSET,
    clock: Clock = _now,
) -> dict[str, Any]:
    """Edit timeline presentation/lifecycle without rewriting inheritance."""

    if name is _UNSET and lifecycle_state is _UNSET:
        raise StoryStatePersistenceError(
            PersistenceErrorCode.INVALID_PATCH,
            "timeline patch contains no fields",
        )
    novel = _lock_ledger(session, novel_id, expected_story_ledger_version)
    row = session.scalar(
        select(StoryTimeline)
        .where(StoryTimeline.id == timeline_id, StoryTimeline.novel_id == novel_id)
        .with_for_update()
    )
    if row is None:
        raise StoryStateError(
            StoryStateErrorCode.TIMELINE_NOT_FOUND,
            "timeline was not found in the novel",
        )
    if row.version != expected_timeline_version:
        raise StoryStatePersistenceError(
            PersistenceErrorCode.VERSION_CONFLICT,
            "timeline version changed",
            current=timeline_payload(row),
        )
    next_name = row.name if name is _UNSET else str(name).strip()
    if not next_name:
        raise StoryStatePersistenceError(
            PersistenceErrorCode.INVALID_PATCH,
            "timeline name cannot be empty",
        )
    next_lifecycle = (
        LifecycleState(row.lifecycle_state)
        if lifecycle_state is _UNSET
        else LifecycleState(lifecycle_state)
    )
    if row.is_primary and next_lifecycle is LifecycleState.ARCHIVED:
        raise StoryStatePersistenceError(
            PersistenceErrorCode.INVALID_PATCH,
            "primary timeline cannot be archived",
        )
    normalized_name = next_name.casefold()
    duplicate = session.scalar(
        select(StoryTimeline.id).where(
            StoryTimeline.novel_id == novel_id,
            StoryTimeline.id != timeline_id,
            StoryTimeline.normalized_name == normalized_name,
            StoryTimeline.lifecycle_state == "active",
        )
    )
    if duplicate is not None and next_lifecycle is LifecycleState.ACTIVE:
        raise StoryStateError(
            StoryStateErrorCode.TIMELINE_CONFLICT,
            "an active timeline with the same normalized name already exists",
        )
    row.name = next_name
    row.normalized_name = normalized_name
    row.lifecycle_state = next_lifecycle.value
    row.version += 1
    row.updated_at = clock()
    novel.story_ledger_version += 1
    session.flush()
    payload = timeline_payload(row)
    payload["story_ledger_version"] = novel.story_ledger_version
    return payload


def list_timeline_link_payloads(
    session: Session, novel_id: UUID
) -> list[dict[str, Any]]:
    _require_novel(session, novel_id, for_update=False)
    rows = session.scalars(
        select(StoryTimelineLink)
        .where(StoryTimelineLink.novel_id == novel_id)
        .order_by(StoryTimelineLink.created_at, StoryTimelineLink.id)
    )
    return [timeline_link_payload(row) for row in rows]


def get_timeline_link_payload(
    session: Session, novel_id: UUID, link_id: UUID
) -> dict[str, Any]:
    _require_novel(session, novel_id, for_update=False)
    row = session.scalar(
        select(StoryTimelineLink).where(
            StoryTimelineLink.id == link_id,
            StoryTimelineLink.novel_id == novel_id,
        )
    )
    if row is None:
        raise StoryStateError(
            StoryStateErrorCode.INVALID_TIMELINE_LINK,
            "timeline link was not found in the novel",
        )
    return timeline_link_payload(row)


def list_story_fact_payloads(session: Session, novel_id: UUID) -> list[dict[str, Any]]:
    _require_novel(session, novel_id, for_update=False)
    rows = session.scalars(
        select(StoryFact)
        .where(
            StoryFact.novel_id == novel_id,
            StoryFact.schema_version == "story-fact/2",
        )
        .order_by(StoryFact.created_at, StoryFact.id)
    )
    return [story_fact_payload(row) for row in rows]


def get_story_fact_payload(
    session: Session, novel_id: UUID, fact_id: UUID
) -> dict[str, Any]:
    _require_novel(session, novel_id, for_update=False)
    row = session.scalar(
        select(StoryFact).where(
            StoryFact.id == fact_id,
            StoryFact.novel_id == novel_id,
            StoryFact.schema_version == "story-fact/2",
        )
    )
    if row is None:
        raise StoryStatePersistenceError(
            PersistenceErrorCode.FACT_NOT_FOUND,
            "StoryFact v2 row was not found in the novel",
        )
    return story_fact_payload(row)


def list_character_instance_payloads(
    session: Session,
    novel_id: UUID,
    *,
    timeline_id: UUID | None = None,
    character_id: UUID | None = None,
) -> list[dict[str, Any]]:
    _require_novel(session, novel_id, for_update=False)
    statement = select(CharacterInstance).where(CharacterInstance.novel_id == novel_id)
    if timeline_id is not None:
        statement = statement.where(CharacterInstance.origin_timeline_id == timeline_id)
    if character_id is not None:
        statement = statement.where(CharacterInstance.character_id == character_id)
    rows = session.scalars(statement.order_by(CharacterInstance.created_at, CharacterInstance.id))
    return [character_instance_payload(row) for row in rows]


def get_character_instance_payload(
    session: Session,
    novel_id: UUID,
    *,
    character_instance_id: UUID | None = None,
    character_id: UUID | None = None,
    timeline_id: UUID | None = None,
) -> dict[str, Any]:
    _require_novel(session, novel_id, for_update=False)
    rows = _instance_rows(session, novel_id)
    resolved = resolve_character_instance(
        [_instance_record(row) for row in rows],
        novel_id,
        character_id=character_id,
        timeline_id=timeline_id,
        character_instance_id=character_instance_id,
    )
    row_by_id = {row.id: row for row in rows}
    return character_instance_payload(row_by_id[resolved.id])


def ensure_default_story_state(
    session: Session,
    novel_id: UUID,
    *,
    expected_story_ledger_version: int,
    character_ids: Sequence[UUID] | None = None,
    id_factory: IdFactory = uuid4,
    clock: Clock = _now,
) -> dict[str, Any]:
    novel = _lock_ledger(session, novel_id, expected_story_ledger_version)
    timelines = _timeline_rows(session, novel_id, for_update=True)
    instances = _instance_rows(session, novel_id, for_update=True)
    if character_ids is None:
        character_ids = tuple(
            session.scalars(
                select(NovelCharacter.id)
                .where(
                    NovelCharacter.novel_id == novel_id,
                    NovelCharacter.lifecycle_state == "active",
                )
                .order_by(NovelCharacter.position, NovelCharacter.id)
            )
        )
    else:
        requested = tuple(character_ids)
        found = set(
            session.scalars(
                select(NovelCharacter.id).where(
                    NovelCharacter.novel_id == novel_id,
                    NovelCharacter.id.in_(requested),
                    NovelCharacter.lifecycle_state == "active",
                )
            )
        )
        if found != set(requested):
            raise StoryStatePersistenceError(
                PersistenceErrorCode.CHARACTER_NOT_FOUND,
                "one or more character roots are outside the novel scope",
            )
        character_ids = requested
    plan = build_default_story_state(
        novel_id,
        character_ids,
        [_timeline_record(row) for row in timelines],
        [_instance_record(row) for row in instances],
        id_factory=id_factory,
        clock=clock,
    )
    new_rows: list[object] = []
    if plan.timeline is not None:
        new_rows.append(_new_timeline(plan.timeline))
    revision_rows: list[CharacterInstanceRevision] = []
    for record in plan.character_instances:
        revision_id = id_factory()
        # Root details (for example gender and cross-line themes) are not an
        # instance profile.  Profile fields are populated explicitly through
        # the versioned profile service after the stable instance exists.
        profile: dict[str, object] = {
            "schema_version": "character-instance-profile/1"
        }
        operation_key = f"default-instance:{record.id}:v1"
        content_digest = sha256(
            json.dumps(
                profile, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        new_rows.append(_new_instance(record, current_revision_id=revision_id))
        revision_rows.append(
            CharacterInstanceRevision(
                id=revision_id,
                novel_id=novel_id,
                character_instance_id=record.id,
                revision_number=1,
                parent_revision_id=None,
                restored_from_revision_id=None,
                source_kind="character_create",
                operation_key=operation_key,
                operation_hash=sha256(operation_key.encode("utf-8")).hexdigest(),
                profile_schema_version=1,
                profile_json=profile,
                change_set_json={"created_with_default_timeline": True},
                content_hash=content_digest,
                created_at=clock(),
            )
        )
    new_rows.extend(revision_rows)
    if new_rows:
        session.add_all(new_rows)
        novel.story_ledger_version += 1
        session.flush()
    return {
        "timeline": timeline_payload(new_rows[0]) if plan.timeline is not None else None,
        "character_instances": [
            character_instance_payload(row)
            for row in new_rows
            if isinstance(row, CharacterInstance)
        ],
        "story_ledger_version": novel.story_ledger_version,
    }


def fork_timeline(
    session: Session,
    novel_id: UUID,
    source_timeline_id: UUID,
    *,
    expected_story_ledger_version: int,
    expected_source_timeline_version: int,
    timeline_key: str,
    name: str,
    fork_story_sequence: int,
    fork_anchor: Mapping[str, object] | None = None,
    id_factory: IdFactory = uuid4,
    clock: Clock = _now,
) -> dict[str, Any]:
    novel = _lock_ledger(session, novel_id, expected_story_ledger_version)
    timelines = _timeline_rows(session, novel_id, for_update=True)
    instances = _instance_rows(session, novel_id, for_update=True)
    source_rows = [row for row in timelines if row.id == source_timeline_id]
    if not source_rows:
        raise StoryStateError(
            StoryStateErrorCode.TIMELINE_NOT_FOUND,
            "source timeline was not found in the novel",
        )
    if source_rows[0].version != expected_source_timeline_version:
        raise StoryStatePersistenceError(
            PersistenceErrorCode.VERSION_CONFLICT,
            "source timeline version changed",
            current=timeline_payload(source_rows[0]),
        )
    plan = build_fork_plan(
        novel_id,
        source_timeline_id,
        timeline_key=timeline_key,
        name=name,
        fork_story_sequence=fork_story_sequence,
        fork_anchor_json=fork_anchor,
        timelines=[_timeline_record(row) for row in timelines],
        instances=[_instance_record(row) for row in instances],
        id_factory=id_factory,
        clock=clock,
    )
    timeline_row = _new_timeline(plan.timeline)
    derived_rows: list[CharacterInstance] = []
    revision_rows: list[CharacterInstanceRevision] = []
    source_by_id = {row.id: row for row in instances}
    for record in plan.derived_instances:
        current_revision_id: UUID | None = None
        source_instance = source_by_id[record.derived_from_instance_id]
        if source_instance.current_revision_id is not None:
            source_revision = session.scalar(
                select(CharacterInstanceRevision).where(
                    CharacterInstanceRevision.id == source_instance.current_revision_id,
                    CharacterInstanceRevision.character_instance_id == source_instance.id,
                    CharacterInstanceRevision.novel_id == novel_id,
                )
            )
            if source_revision is None:
                raise StoryStatePersistenceError(
                    PersistenceErrorCode.INVALID_PATCH,
                    "source instance current revision is outside the novel scope",
                )
            current_revision_id = id_factory()
            operation_key = f"timeline-fork:{plan.timeline.id}:{source_instance.id}"
            operation_hash = sha256(operation_key.encode("utf-8")).hexdigest()
            revision_rows.append(
                CharacterInstanceRevision(
                    id=current_revision_id,
                    novel_id=novel_id,
                    character_instance_id=record.id,
                    revision_number=1,
                    parent_revision_id=None,
                    restored_from_revision_id=None,
                    source_kind="timeline_fork",
                    operation_key=operation_key,
                    operation_hash=operation_hash,
                    profile_schema_version=source_revision.profile_schema_version,
                    profile_json=dict(source_revision.profile_json or {}),
                    change_set_json={
                        "derived_from_instance_id": str(source_instance.id),
                        "source_revision_id": str(source_revision.id),
                    },
                    content_hash=source_revision.content_hash,
                    created_at=clock(),
                )
            )
        derived_rows.append(
            _new_instance(record, current_revision_id=current_revision_id)
        )
    # SQLAlchemy has no relationship graph for these deliberately narrow ORM
    # models, so make the FK order explicit: timeline -> instances -> their
    # immutable initial revisions. The instance current-revision constraint is
    # deferred and is complete before this transaction can commit.
    session.add(timeline_row)
    session.flush()
    session.add_all(derived_rows)
    session.flush()
    session.add_all(revision_rows)
    novel.story_ledger_version += 1
    session.flush()
    return {
        "timeline": timeline_payload(timeline_row),
        "derived_instances": [character_instance_payload(row) for row in derived_rows],
        "copied_fact_count": plan.copied_fact_count,
        "story_ledger_version": novel.story_ledger_version,
    }


def create_timeline_link(
    session: Session,
    novel_id: UUID,
    *,
    source_timeline_id: UUID,
    target_timeline_id: UUID,
    link_type: TimelineLinkType,
    expected_story_ledger_version: int,
    expected_source_timeline_version: int,
    expected_target_timeline_version: int,
    source_story_sequence: int | None = None,
    target_story_sequence: int | None = None,
    details: Mapping[str, object] | None = None,
    id_factory: IdFactory = uuid4,
    clock: Clock = _now,
) -> dict[str, Any]:
    novel = _lock_ledger(session, novel_id, expected_story_ledger_version)
    rows = _timeline_rows(session, novel_id, for_update=True)
    by_id = {row.id: row for row in rows}
    source = by_id.get(source_timeline_id)
    target = by_id.get(target_timeline_id)
    if source is None or target is None:
        raise StoryStateError(
            StoryStateErrorCode.TIMELINE_NOT_FOUND,
            "timeline link endpoint was not found in the novel",
        )
    if (
        source.version != expected_source_timeline_version
        or target.version != expected_target_timeline_version
    ):
        raise StoryStatePersistenceError(
            PersistenceErrorCode.VERSION_CONFLICT,
            "timeline link endpoint version changed",
        )
    record = build_timeline_link(
        novel_id,
        source_timeline_id,
        target_timeline_id,
        link_type,
        [_timeline_record(row) for row in rows],
        source_story_sequence=source_story_sequence,
        target_story_sequence=target_story_sequence,
        details_json=details,
        id_factory=id_factory,
        clock=clock,
    )
    replay = session.scalar(
        select(StoryTimelineLink).where(
            StoryTimelineLink.novel_id == novel_id,
            StoryTimelineLink.link_fingerprint == record.link_fingerprint,
        )
    )
    if replay is not None:
        payload = timeline_link_payload(replay)
        payload["story_ledger_version"] = novel.story_ledger_version
        return payload
    row = _new_timeline_link(record)
    session.add(row)
    novel.story_ledger_version += 1
    session.flush()
    payload = timeline_link_payload(row)
    payload["story_ledger_version"] = novel.story_ledger_version
    return payload


def create_merge_timeline(
    session: Session,
    novel_id: UUID,
    *,
    primary_timeline_id: UUID,
    input_timeline_ids: Sequence[UUID],
    expected_story_ledger_version: int,
    expected_timeline_versions: Mapping[UUID, int],
    timeline_key: str,
    name: str,
    merge_story_sequence: int,
    merge_anchor: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Create a merge whose sole inherited state comes from the primary input.

    Other inputs are recorded as ``merge_reference`` links only.  No facts are
    copied or propagated, so target-line StoryFacts remain an explicit author
    decision.
    """

    unique_inputs = list(dict.fromkeys(input_timeline_ids))
    if len(unique_inputs) < 2 or primary_timeline_id not in unique_inputs:
        raise StoryStatePersistenceError(
            PersistenceErrorCode.INVALID_PATCH,
            "a merge requires at least two inputs including its primary timeline",
        )
    rows = _timeline_rows(session, novel_id, for_update=False)
    by_id = {row.id: row for row in rows}
    for timeline_id in unique_inputs:
        row = by_id.get(timeline_id)
        if row is None:
            raise StoryStateError(
                StoryStateErrorCode.TIMELINE_NOT_FOUND,
                "merge input timeline was not found in the novel",
            )
        expected = expected_timeline_versions.get(timeline_id)
        if expected is None or row.version != expected:
            raise StoryStatePersistenceError(
                PersistenceErrorCode.VERSION_CONFLICT,
                "merge input timeline version changed",
                current={"timeline_id": str(timeline_id), "version": row.version},
            )
    primary = by_id[primary_timeline_id]
    result = fork_timeline(
        session,
        novel_id,
        primary_timeline_id,
        expected_story_ledger_version=expected_story_ledger_version,
        expected_source_timeline_version=primary.version,
        timeline_key=timeline_key,
        name=name,
        fork_story_sequence=merge_story_sequence,
        fork_anchor={**dict(merge_anchor or {}), "merge_inputs": [str(i) for i in unique_inputs]},
    )
    target_id = UUID(str(result["timeline"]["id"]))
    target = session.get(StoryTimeline, target_id)
    if target is None:
        raise StoryStatePersistenceError(
            PersistenceErrorCode.INVALID_PATCH, "merge timeline was not persisted"
        )
    target.timeline_kind = TimelineKind.MERGE.value
    result["timeline"] = timeline_payload(target)
    ledger_version = int(result["story_ledger_version"])
    references: list[dict[str, Any]] = []
    for source_id in unique_inputs:
        if source_id == primary_timeline_id:
            continue
        link = create_timeline_link(
            session,
            novel_id,
            source_timeline_id=source_id,
            target_timeline_id=target_id,
            link_type=TimelineLinkType.MERGE_REFERENCE,
            expected_story_ledger_version=ledger_version,
            expected_source_timeline_version=by_id[source_id].version,
            expected_target_timeline_version=target.version,
            source_story_sequence=merge_story_sequence,
            target_story_sequence=merge_story_sequence,
            details={"state_propagation": "none"},
        )
        ledger_version = int(link["story_ledger_version"])
        references.append(link)
    result["merge_references"] = references
    result["story_ledger_version"] = ledger_version
    return result


def list_story_event_link_payloads(
    session: Session, novel_id: UUID
) -> list[dict[str, Any]]:
    _require_novel(session, novel_id, for_update=False)
    rows = session.scalars(
        select(StoryEventLink)
        .where(StoryEventLink.novel_id == novel_id)
        .order_by(StoryEventLink.created_at, StoryEventLink.id)
    )
    return [story_event_link_payload(row) for row in rows]


def create_story_event_link(
    session: Session,
    novel_id: UUID,
    *,
    source_fact_id: UUID,
    target_fact_id: UUID,
    link_type: StoryEventLinkType,
    expected_story_ledger_version: int,
    details: Mapping[str, object] | None = None,
    id_factory: IdFactory = uuid4,
    clock: Clock = _now,
) -> dict[str, Any]:
    novel = _lock_ledger(session, novel_id, expected_story_ledger_version)
    if source_fact_id == target_fact_id:
        raise StoryStatePersistenceError(
            PersistenceErrorCode.INVALID_PATCH,
            "story event link endpoints must be distinct",
        )
    facts = list(
        session.scalars(
            select(StoryFact)
            .where(
                StoryFact.novel_id == novel_id,
                StoryFact.id.in_([source_fact_id, target_fact_id]),
                StoryFact.schema_version == "story-fact/2",
            )
            .with_for_update()
        )
    )
    if {row.id for row in facts} != {source_fact_id, target_fact_id}:
        raise StoryStatePersistenceError(
            PersistenceErrorCode.FACT_NOT_FOUND,
            "story event link endpoint was not found in the novel",
        )
    replay = session.scalar(
        select(StoryEventLink).where(
            StoryEventLink.novel_id == novel_id,
            StoryEventLink.source_fact_id == source_fact_id,
            StoryEventLink.target_fact_id == target_fact_id,
            StoryEventLink.link_type == link_type.value,
        )
    )
    if replay is not None:
        payload = story_event_link_payload(replay)
        payload["story_ledger_version"] = novel.story_ledger_version
        payload["replayed"] = True
        return payload
    row = StoryEventLink(
        id=id_factory(),
        novel_id=novel_id,
        source_fact_id=source_fact_id,
        target_fact_id=target_fact_id,
        link_type=link_type.value,
        details_json=dict(details or {}),
        created_at=clock(),
    )
    session.add(row)
    novel.story_ledger_version += 1
    session.flush()
    payload = story_event_link_payload(row)
    payload["story_ledger_version"] = novel.story_ledger_version
    payload["replayed"] = False
    return payload


def create_character_instance(
    session: Session,
    novel_id: UUID,
    *,
    character_id: UUID,
    timeline_id: UUID | None,
    continuity_kind: CharacterContinuityKind,
    display_label: str,
    expected_story_ledger_version: int,
    expected_timeline_version: int,
    derived_from_instance_id: UUID | None = None,
    id_factory: IdFactory = uuid4,
    clock: Clock = _now,
) -> dict[str, Any]:
    novel = _lock_ledger(session, novel_id, expected_story_ledger_version)
    character = session.scalar(
        select(NovelCharacter).where(
            NovelCharacter.id == character_id,
            NovelCharacter.novel_id == novel_id,
            NovelCharacter.lifecycle_state == "active",
        )
    )
    if character is None:
        raise StoryStatePersistenceError(
            PersistenceErrorCode.CHARACTER_NOT_FOUND,
            "character root was not found in the novel",
        )
    timelines = _timeline_rows(session, novel_id, for_update=True)
    timeline = resolve_timeline(
        [_timeline_record(row) for row in timelines], novel_id, timeline_id
    )
    timeline_row = next(row for row in timelines if row.id == timeline.id)
    if timeline_row.version != expected_timeline_version:
        raise StoryStatePersistenceError(
            PersistenceErrorCode.VERSION_CONFLICT,
            "timeline version changed",
            current=timeline_payload(timeline_row),
        )
    instances = _instance_rows(session, novel_id, for_update=True)
    if any(
        row.character_id == character_id
        and row.origin_timeline_id == timeline.id
        and row.lifecycle_state == "active"
        for row in instances
    ):
        raise StoryStateError(
            StoryStateErrorCode.CHARACTER_INSTANCE_CONFLICT,
            "an active local instance already exists for this character and timeline",
        )
    if derived_from_instance_id is not None:
        source_instance = resolve_character_instance(
            [_instance_record(row) for row in instances],
            novel_id,
            character_instance_id=derived_from_instance_id,
        )
        if source_instance.character_id != character_id:
            raise StoryStateError(
                StoryStateErrorCode.CHARACTER_INSTANCE_CONFLICT,
                "derived source instance belongs to another character root",
            )
    now = clock()
    record = CharacterInstanceRecord(
        id=id_factory(),
        novel_id=novel_id,
        character_id=character_id,
        origin_timeline_id=timeline.id,
        derived_from_instance_id=derived_from_instance_id,
        continuity_kind=continuity_kind,
        display_label=display_label,
        created_at=now,
        updated_at=now,
    )
    row = _new_instance(record)
    session.add(row)
    novel.story_ledger_version += 1
    session.flush()
    payload = character_instance_payload(row)
    payload["story_ledger_version"] = novel.story_ledger_version
    return payload


def patch_character_instance(
    session: Session,
    novel_id: UUID,
    character_instance_id: UUID,
    *,
    expected_story_ledger_version: int,
    expected_instance_version: int,
    display_label: str | object = _UNSET,
    lifecycle_state: LifecycleState | object = _UNSET,
    clock: Clock = _now,
) -> dict[str, Any]:
    if display_label is _UNSET and lifecycle_state is _UNSET:
        raise StoryStatePersistenceError(
            PersistenceErrorCode.INVALID_PATCH,
            "character instance patch contains no fields",
        )
    novel = _lock_ledger(session, novel_id, expected_story_ledger_version)
    row = session.scalar(
        select(CharacterInstance)
        .where(
            CharacterInstance.id == character_instance_id,
            CharacterInstance.novel_id == novel_id,
        )
        .with_for_update()
    )
    if row is None:
        raise StoryStateError(
            StoryStateErrorCode.CHARACTER_INSTANCE_NOT_FOUND,
            "character instance was not found in the novel",
        )
    if row.version != expected_instance_version:
        raise StoryStatePersistenceError(
            PersistenceErrorCode.VERSION_CONFLICT,
            "character instance version changed",
            current=character_instance_payload(row),
        )
    candidate = _instance_record(row).model_dump()
    if display_label is not _UNSET:
        candidate["display_label"] = display_label
    if lifecycle_state is not _UNSET:
        candidate["lifecycle_state"] = lifecycle_state
    candidate["version"] = row.version + 1
    candidate["updated_at"] = clock()
    validated = CharacterInstanceRecord.model_validate(candidate)
    row.display_label = validated.display_label
    row.lifecycle_state = validated.lifecycle_state.value
    row.version = validated.version
    row.updated_at = validated.updated_at
    novel.story_ledger_version += 1
    session.flush()
    payload = character_instance_payload(row)
    payload["story_ledger_version"] = novel.story_ledger_version
    return payload


def get_story_projection_payload(
    session: Session,
    novel_id: UUID,
    *,
    timeline_id: UUID | None = None,
    narrative_cutoff: int | None = None,
) -> dict[str, Any]:
    _require_novel(session, novel_id, for_update=False)
    timeline_rows = _timeline_rows(session, novel_id)
    timeline_records = [_timeline_record(row) for row in timeline_rows]
    resolved = resolve_timeline(timeline_records, novel_id, timeline_id)
    fact_rows = list(
        session.scalars(
            select(StoryFact)
            .where(
                StoryFact.novel_id == novel_id,
                StoryFact.schema_version == "story-fact/2",
                StoryFact.timeline_id.is_not(None),
            )
            .order_by(StoryFact.created_at, StoryFact.id)
        )
    )
    facts = [_fact_record(row) for row in fact_rows]
    fact_ids = [fact.id for fact in facts]
    link_rows = list(
        session.scalars(
            select(StoryEventLink)
            .where(StoryEventLink.novel_id == novel_id)
            .order_by(StoryEventLink.created_at, StoryEventLink.id)
        )
    )
    binding_rows = (
        list(
            session.scalars(
                select(DerivedSourceBinding)
                .join(StoryFact, StoryFact.id == DerivedSourceBinding.derived_entity_id)
                .where(
                    StoryFact.novel_id == novel_id,
                    DerivedSourceBinding.derived_entity_type == "story_fact",
                    DerivedSourceBinding.derived_entity_id.in_(fact_ids),
                )
            )
        )
        if fact_ids
        else []
    )
    effective_states = {"current", "source_restored"}
    validity: dict[UUID, bool] = {}
    for binding in binding_rows:
        current = binding.validity_state in effective_states
        existing = validity.get(binding.source_chapter_revision_id)
        validity[binding.source_chapter_revision_id] = (
            current if existing is None else existing and current
        )
    projection = project_story_facts(
        novel_id,
        resolved.id,
        narrative_cutoff=narrative_cutoff,
        timelines=timeline_records,
        facts=facts,
        event_links=[_event_link_record(row) for row in link_rows],
        source_revision_validity=validity,
    )
    return projection_payload(projection)
