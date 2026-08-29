"""Pure deterministic story-state engine.

All functions operate on immutable snapshots and return records or mutation
plans.  They neither read nor write a database, so a later service can persist a
whole plan in one transaction after CAS and scope checks.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from hashlib import sha256
import json
from uuid import UUID, uuid4

from .contracts import (
    CharacterContinuityKind,
    CharacterInstanceRecord,
    DefaultStoryStatePlan,
    LifecycleState,
    ProjectionConflict,
    StoryEventLinkRecord,
    StoryEventLinkType,
    StoryFactStatus,
    StoryFactType,
    StoryFactV2,
    StoryProjection,
    StoryStateError,
    StoryStateErrorCode,
    StoryTimelineLinkRecord,
    StoryTimelineRecord,
    TimelineForkPlan,
    TimelineKind,
    TimelineLinkType,
)


IdFactory = Callable[[], UUID]
Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _for_novel(records: Iterable[object], novel_id: UUID) -> list[object]:
    return [record for record in records if getattr(record, "novel_id") == novel_id]


def validate_inheritance_dag(
    timelines: Sequence[StoryTimelineRecord],
    novel_id: UUID,
) -> None:
    """Validate the single-parent inheritance graph; explicit links are ignored."""

    scoped = [timeline for timeline in timelines if timeline.novel_id == novel_id]
    by_id = {timeline.id: timeline for timeline in scoped}
    if len(by_id) != len(scoped):
        raise StoryStateError(
            StoryStateErrorCode.TIMELINE_CONFLICT,
            "duplicate timeline IDs exist in the novel snapshot",
        )

    primary_ids = [timeline.id for timeline in scoped if timeline.is_primary]
    if len(primary_ids) > 1:
        raise StoryStateError(
            StoryStateErrorCode.TIMELINE_CONFLICT,
            "a novel may have only one primary timeline",
            details={"timeline_ids": [str(item) for item in primary_ids]},
        )

    for timeline in scoped:
        parent_id = timeline.parent_timeline_id
        if parent_id is not None and parent_id not in by_id:
            raise StoryStateError(
                StoryStateErrorCode.INVALID_INHERITANCE,
                "timeline parent is missing or belongs to another novel",
                details={"timeline_id": str(timeline.id), "parent_timeline_id": str(parent_id)},
            )

    visiting: set[UUID] = set()
    visited: set[UUID] = set()

    def visit(timeline_id: UUID) -> None:
        if timeline_id in visiting:
            raise StoryStateError(
                StoryStateErrorCode.INVALID_INHERITANCE,
                "timeline inheritance must be acyclic",
                details={"timeline_id": str(timeline_id)},
            )
        if timeline_id in visited:
            return
        visiting.add(timeline_id)
        parent_id = by_id[timeline_id].parent_timeline_id
        if parent_id is not None:
            visit(parent_id)
        visiting.remove(timeline_id)
        visited.add(timeline_id)

    for timeline_id in by_id:
        visit(timeline_id)


def resolve_timeline(
    timelines: Sequence[StoryTimelineRecord],
    novel_id: UUID,
    timeline_id: UUID | None = None,
) -> StoryTimelineRecord:
    active = [
        timeline
        for timeline in timelines
        if timeline.novel_id == novel_id and timeline.lifecycle_state is LifecycleState.ACTIVE
    ]
    if timeline_id is not None:
        for timeline in active:
            if timeline.id == timeline_id:
                return timeline
        raise StoryStateError(
            StoryStateErrorCode.TIMELINE_NOT_FOUND,
            "active timeline was not found in the novel",
            details={"timeline_id": str(timeline_id)},
        )
    if len(active) == 1:
        return active[0]
    if not active:
        raise StoryStateError(
            StoryStateErrorCode.TIMELINE_NOT_FOUND,
            "novel has no active timeline",
        )
    raise StoryStateError(
        StoryStateErrorCode.TIMELINE_REQUIRED,
        "timeline_id is required when a novel has multiple active timelines",
        details={"timeline_ids": [str(item.id) for item in active]},
    )


def resolve_character_instance(
    instances: Sequence[CharacterInstanceRecord],
    novel_id: UUID,
    *,
    character_id: UUID | None = None,
    timeline_id: UUID | None = None,
    character_instance_id: UUID | None = None,
) -> CharacterInstanceRecord:
    active = [
        instance
        for instance in instances
        if instance.novel_id == novel_id and instance.lifecycle_state is LifecycleState.ACTIVE
    ]
    if character_instance_id is not None:
        matches = [instance for instance in active if instance.id == character_instance_id]
        if not matches:
            raise StoryStateError(
                StoryStateErrorCode.CHARACTER_INSTANCE_NOT_FOUND,
                "active character instance was not found in the novel",
                details={"character_instance_id": str(character_instance_id)},
            )
        resolved = matches[0]
        if character_id is not None and resolved.character_id != character_id:
            raise StoryStateError(
                StoryStateErrorCode.CHARACTER_INSTANCE_CONFLICT,
                "character instance does not belong to the requested character root",
            )
        # An explicit traveler may originate on another line.  Presence on the
        # target line is validated by the calling projection, never guessed here.
        return resolved

    candidates = active
    if character_id is not None:
        candidates = [item for item in candidates if item.character_id == character_id]
    if timeline_id is not None:
        candidates = [item for item in candidates if item.origin_timeline_id == timeline_id]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise StoryStateError(
            StoryStateErrorCode.CHARACTER_INSTANCE_NOT_FOUND,
            "no active character instance matches the explicit scope",
        )
    raise StoryStateError(
        StoryStateErrorCode.CHARACTER_INSTANCE_REQUIRED,
        "character_instance_id is required because the scope is ambiguous",
        details={"character_instance_ids": [str(item.id) for item in candidates]},
    )


def build_default_story_state(
    novel_id: UUID,
    character_ids: Sequence[UUID],
    timelines: Sequence[StoryTimelineRecord],
    instances: Sequence[CharacterInstanceRecord],
    *,
    id_factory: IdFactory = uuid4,
    clock: Clock = _utc_now,
) -> DefaultStoryStatePlan:
    """Plan idempotent main-line and native-instance initialization."""

    scoped_timelines = [item for item in timelines if item.novel_id == novel_id]
    now = clock()
    created_timeline: StoryTimelineRecord | None = None
    if not scoped_timelines:
        created_timeline = StoryTimelineRecord(
            id=id_factory(),
            novel_id=novel_id,
            timeline_key="main",
            name="主时间线",
            normalized_name="主时间线",
            timeline_kind=TimelineKind.MAIN,
            is_primary=True,
            created_at=now,
            updated_at=now,
        )
        primary = created_timeline
        validation_snapshot = [created_timeline]
    else:
        validate_inheritance_dag(scoped_timelines, novel_id)
        active_primary = [
            item
            for item in scoped_timelines
            if item.is_primary and item.lifecycle_state is LifecycleState.ACTIVE
        ]
        if len(active_primary) != 1:
            raise StoryStateError(
                StoryStateErrorCode.TIMELINE_CONFLICT,
                "existing story state must contain exactly one active primary timeline",
            )
        primary = active_primary[0]
        validation_snapshot = scoped_timelines
    validate_inheritance_dag(validation_snapshot, novel_id)

    scoped_instances = [item for item in instances if item.novel_id == novel_id]
    created_instances: list[CharacterInstanceRecord] = []
    if len(character_ids) != len(set(character_ids)):
        raise StoryStateError(
            StoryStateErrorCode.CHARACTER_INSTANCE_CONFLICT,
            "character roots must not contain duplicates",
        )
    for character_id in character_ids:
        matching = [
            item
            for item in scoped_instances
            if item.character_id == character_id
            and item.origin_timeline_id == primary.id
            and item.lifecycle_state is LifecycleState.ACTIVE
        ]
        if len(matching) > 1:
            raise StoryStateError(
                StoryStateErrorCode.CHARACTER_INSTANCE_CONFLICT,
                "multiple active native instances exist for one character and timeline",
            )
        if not matching:
            created_instances.append(
                CharacterInstanceRecord(
                    id=id_factory(),
                    novel_id=novel_id,
                    character_id=character_id,
                    origin_timeline_id=primary.id,
                    continuity_kind=CharacterContinuityKind.NATIVE,
                    created_at=now,
                    updated_at=now,
                )
            )
    return DefaultStoryStatePlan(
        timeline=created_timeline,
        character_instances=tuple(created_instances),
    )


def fork_timeline(
    novel_id: UUID,
    source_timeline_id: UUID,
    *,
    timeline_key: str,
    name: str,
    fork_story_sequence: int,
    fork_anchor_json: Mapping[str, object] | None,
    timelines: Sequence[StoryTimelineRecord],
    instances: Sequence[CharacterInstanceRecord],
    id_factory: IdFactory = uuid4,
    clock: Clock = _utc_now,
) -> TimelineForkPlan:
    """Create a branch and derived local instances without copying facts."""

    source = resolve_timeline(timelines, novel_id, source_timeline_id)
    normalized_name = " ".join(name.split()).casefold()
    if not timeline_key.strip() or not normalized_name:
        raise StoryStateError(StoryStateErrorCode.FORK_CONFLICT, "fork key and name are required")
    for timeline in timelines:
        if timeline.novel_id != novel_id:
            continue
        if timeline.timeline_key == timeline_key or (
            timeline.lifecycle_state is LifecycleState.ACTIVE
            and timeline.normalized_name == normalized_name
        ):
            raise StoryStateError(
                StoryStateErrorCode.FORK_CONFLICT,
                "fork key or active name already exists",
            )
    now = clock()
    branch = StoryTimelineRecord(
        id=id_factory(),
        novel_id=novel_id,
        timeline_key=timeline_key,
        name=name,
        normalized_name=normalized_name,
        timeline_kind=TimelineKind.BRANCH,
        parent_timeline_id=source.id,
        fork_story_sequence=fork_story_sequence,
        fork_anchor_json=dict(fork_anchor_json or {}),
        position=max((item.position for item in timelines if item.novel_id == novel_id), default=-1)
        + 1,
        created_at=now,
        updated_at=now,
    )
    validate_inheritance_dag([*timelines, branch], novel_id)

    local_active_instances = [
        item
        for item in instances
        if item.novel_id == novel_id
        and item.origin_timeline_id == source.id
        and item.lifecycle_state is LifecycleState.ACTIVE
    ]
    character_ids = [item.character_id for item in local_active_instances]
    if len(character_ids) != len(set(character_ids)):
        raise StoryStateError(
            StoryStateErrorCode.FORK_CONFLICT,
            "source timeline has duplicate active local instances for a character root",
        )
    derived = tuple(
        CharacterInstanceRecord(
            id=id_factory(),
            novel_id=novel_id,
            character_id=item.character_id,
            origin_timeline_id=branch.id,
            derived_from_instance_id=item.id,
            continuity_kind=CharacterContinuityKind.DERIVED,
            display_label=item.display_label,
            current_revision_id=item.current_revision_id,
            created_at=now,
            updated_at=now,
        )
        for item in sorted(local_active_instances, key=lambda record: str(record.id))
    )
    return TimelineForkPlan(timeline=branch, derived_instances=derived)


def build_timeline_link(
    novel_id: UUID,
    source_timeline_id: UUID,
    target_timeline_id: UUID,
    link_type: TimelineLinkType,
    timelines: Sequence[StoryTimelineRecord],
    *,
    source_story_sequence: int | None = None,
    target_story_sequence: int | None = None,
    details_json: Mapping[str, object] | None = None,
    id_factory: IdFactory = uuid4,
    clock: Clock = _utc_now,
) -> StoryTimelineLinkRecord:
    """Build an explicit non-inheritance link; cycles are intentionally allowed."""

    resolve_timeline(timelines, novel_id, source_timeline_id)
    resolve_timeline(timelines, novel_id, target_timeline_id)
    if source_timeline_id == target_timeline_id:
        raise StoryStateError(
            StoryStateErrorCode.INVALID_TIMELINE_LINK,
            "timeline link endpoints must be distinct",
        )
    details = dict(details_json or {})
    fingerprint_payload = {
        "novel_id": str(novel_id),
        "source_timeline_id": str(source_timeline_id),
        "target_timeline_id": str(target_timeline_id),
        "link_type": link_type.value,
        "source_story_sequence": source_story_sequence,
        "target_story_sequence": target_story_sequence,
        "details_json": details,
    }
    fingerprint = sha256(
        json.dumps(
            fingerprint_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return StoryTimelineLinkRecord(
        id=id_factory(),
        novel_id=novel_id,
        source_timeline_id=source_timeline_id,
        target_timeline_id=target_timeline_id,
        link_type=link_type,
        source_story_sequence=source_story_sequence,
        target_story_sequence=target_story_sequence,
        details_json=details,
        link_fingerprint=fingerprint,
        created_at=clock(),
    )


def _inheritance_limits(
    by_id: Mapping[UUID, StoryTimelineRecord],
    timeline_id: UUID,
    narrative_cutoff: int | None,
) -> tuple[list[UUID], dict[UUID, int | None]]:
    path_target_to_root: list[UUID] = []
    limits: dict[UUID, int | None] = {}
    current = by_id[timeline_id]
    current_limit = narrative_cutoff
    while True:
        path_target_to_root.append(current.id)
        limits[current.id] = current_limit
        if current.parent_timeline_id is None:
            break
        parent = by_id[current.parent_timeline_id]
        fork_limit = current.fork_story_sequence
        if fork_limit is None:
            raise StoryStateError(
                StoryStateErrorCode.INVALID_INHERITANCE,
                "inherited timeline is missing its fork anchor",
                details={"timeline_id": str(current.id)},
            )
        current_limit = (
            fork_limit if current_limit is None else min(current_limit, fork_limit)
        )
        current = parent
    return list(reversed(path_target_to_root)), limits


def _projection_key(fact: StoryFactV2) -> str:
    stable_entity = (
        fact.character_instance_id
        or fact.relationship_id
        or fact.storyline_id
        or fact.foreshadow_id
        or fact.character_id
        or fact.subject
    )
    return "|".join(
        (fact.fact_type.value, str(stable_entity), fact.dimension, fact.predicate)
    )


def project_story_facts(
    novel_id: UUID,
    timeline_id: UUID,
    *,
    narrative_cutoff: int | None,
    timelines: Sequence[StoryTimelineRecord],
    facts: Sequence[StoryFactV2],
    event_links: Sequence[StoryEventLinkRecord] = (),
    source_revision_validity: Mapping[UUID, bool] | None = None,
) -> StoryProjection:
    """Project inherited facts without writes or cross-line propagation.

    Parent facts are visible only up to the child's fork anchor.  Explicit
    timeline links never add facts.  Missing sequence/source-validity evidence is
    reported as ambiguous, and equally ranked conflicting facts have no selected
    current value.
    """

    validate_inheritance_dag(timelines, novel_id)
    target = resolve_timeline(timelines, novel_id, timeline_id)
    by_id = {
        item.id: item
        for item in timelines
        if item.novel_id == novel_id
    }
    inheritance_path, limits = _inheritance_limits(by_id, target.id, narrative_cutoff)
    inherited_ids = set(inheritance_path)
    validity = source_revision_validity or {}

    visible: list[StoryFactV2] = []
    ambiguous: set[UUID] = set()
    suppressed: set[UUID] = set()
    for fact in facts:
        if fact.novel_id != novel_id or fact.timeline_id not in inherited_ids:
            continue
        if fact.status not in {StoryFactStatus.ACTIVE, StoryFactStatus.SOURCE_RESTORED}:
            suppressed.add(fact.id)
            continue
        if fact.source_revision_id is not None:
            source_is_valid = validity.get(fact.source_revision_id)
            if source_is_valid is not True:
                ambiguous.add(fact.id)
                continue
        limit = limits[fact.timeline_id]
        if limit is not None:
            if fact.story_sequence is None:
                ambiguous.add(fact.id)
                continue
            if fact.story_sequence > limit:
                suppressed.add(fact.id)
                continue
        visible.append(fact)

    visible_ids = {fact.id for fact in visible}
    superseded: set[UUID] = set()
    contradiction_pairs: list[tuple[UUID, UUID]] = []
    for link in event_links:
        if link.novel_id != novel_id:
            continue
        if link.source_fact_id not in visible_ids or link.target_fact_id not in visible_ids:
            continue
        if link.link_type is StoryEventLinkType.SUPERSEDES:
            # The source is the replacement and the target is the old fact.
            superseded.add(link.target_fact_id)
        elif link.link_type is StoryEventLinkType.CONTRADICTS:
            contradiction_pairs.append((link.source_fact_id, link.target_fact_id))
    if superseded:
        visible = [fact for fact in visible if fact.id not in superseded]
        suppressed.update(superseded)

    by_fact_id = {fact.id: fact for fact in visible}
    groups: dict[str, list[StoryFactV2]] = defaultdict(list)
    for fact in visible:
        groups[_projection_key(fact)].append(fact)

    current: list[StoryFactV2] = []
    conflicts: list[ProjectionConflict] = []
    conflict_fact_ids: set[UUID] = set()
    for key, candidates in sorted(groups.items()):
        comparable = [fact for fact in candidates if fact.story_sequence is not None]
        without_sequence = [fact for fact in candidates if fact.story_sequence is None]
        ambiguous.update(fact.id for fact in without_sequence)
        if not comparable:
            continue
        greatest_sequence = max(fact.story_sequence for fact in comparable)
        latest = [fact for fact in comparable if fact.story_sequence == greatest_sequence]
        distinct_values = {
            (fact.object_text, fact.details.model_dump_json()) for fact in latest
        }
        if len(distinct_values) > 1:
            fact_ids = tuple(sorted((fact.id for fact in latest), key=str))
            conflicts.append(
                ProjectionConflict(
                    conflict_key=key,
                    fact_ids=fact_ids,
                    reason="same_position",
                )
            )
            conflict_fact_ids.update(fact_ids)
        else:
            current.extend(sorted(latest, key=lambda fact: str(fact.id)))

    for source_id, target_id in contradiction_pairs:
        if source_id not in by_fact_id or target_id not in by_fact_id:
            continue
        conflict_key = "explicit:" + ":".join(sorted((str(source_id), str(target_id))))
        fact_ids = tuple(sorted((source_id, target_id), key=str))
        conflicts.append(
            ProjectionConflict(
                conflict_key=conflict_key,
                fact_ids=fact_ids,
                reason="explicit_contradiction",
            )
        )
        conflict_fact_ids.update(fact_ids)
    if conflict_fact_ids:
        current = [fact for fact in current if fact.id not in conflict_fact_ids]

    fact_order = lambda fact: (
        inheritance_path.index(fact.timeline_id),
        fact.story_sequence if fact.story_sequence is not None else -1,
        fact.created_at,
        str(fact.id),
    )
    return StoryProjection(
        novel_id=novel_id,
        timeline_id=target.id,
        narrative_cutoff=narrative_cutoff,
        visible_facts=tuple(sorted(visible, key=fact_order)),
        current_facts=tuple(sorted(current, key=fact_order)),
        conflicts=tuple(sorted(conflicts, key=lambda item: item.conflict_key)),
        ambiguous_fact_ids=tuple(sorted(ambiguous, key=str)),
        suppressed_fact_ids=tuple(sorted(suppressed, key=str)),
        inheritance_path=tuple(inheritance_path),
    )
