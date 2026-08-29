from __future__ import annotations

from datetime import UTC, datetime
from itertools import count
from uuid import UUID

import pytest

from backend.story_state import (
    CharacterContinuityKind,
    CharacterInstanceRecord,
    LifecycleState,
    StoryEventLinkRecord,
    StoryEventLinkType,
    StoryFactType,
    StoryFactV2,
    StoryStateError,
    StoryStateErrorCode,
    StoryTimelineRecord,
    TimelineKind,
    TimelineLinkType,
    build_default_story_state,
    build_timeline_link,
    fork_timeline,
    project_story_facts,
    resolve_character_instance,
    resolve_timeline,
    validate_inheritance_dag,
)


NOW = datetime(2026, 8, 29, tzinfo=UTC)


def uid(number: int) -> UUID:
    return UUID(int=number)


def id_factory(start: int = 1000):
    values = count(start)
    return lambda: uid(next(values))


def timeline(
    timeline_id: int,
    novel_id: UUID,
    *,
    kind: TimelineKind = TimelineKind.MAIN,
    primary: bool = False,
    parent_id: int | None = None,
    anchor: int | None = None,
    key: str | None = None,
    position: int = 0,
) -> StoryTimelineRecord:
    name = key or f"线-{timeline_id}"
    return StoryTimelineRecord(
        id=uid(timeline_id),
        novel_id=novel_id,
        timeline_key=key or f"timeline-{timeline_id}",
        name=name,
        normalized_name=name.casefold(),
        timeline_kind=kind,
        is_primary=primary,
        parent_timeline_id=uid(parent_id) if parent_id is not None else None,
        fork_story_sequence=anchor,
        position=position,
        created_at=NOW,
        updated_at=NOW,
    )


def instance(
    instance_id: int,
    novel_id: UUID,
    character_id: int,
    origin_timeline_id: int,
    *,
    continuity: CharacterContinuityKind = CharacterContinuityKind.NATIVE,
    derived_from: int | None = None,
    lifecycle: LifecycleState = LifecycleState.ACTIVE,
) -> CharacterInstanceRecord:
    return CharacterInstanceRecord(
        id=uid(instance_id),
        novel_id=novel_id,
        character_id=uid(character_id),
        origin_timeline_id=uid(origin_timeline_id),
        derived_from_instance_id=uid(derived_from) if derived_from is not None else None,
        continuity_kind=continuity,
        lifecycle_state=lifecycle,
        created_at=NOW,
        updated_at=NOW,
    )


def fact(
    fact_id: int,
    novel_id: UUID,
    timeline_id: int,
    sequence: int | None,
    value: str,
    *,
    dimension: str = "weather",
    source_revision_id: int | None = None,
) -> StoryFactV2:
    source_id = uid(source_revision_id) if source_revision_id is not None else None
    return StoryFactV2(
        id=uid(fact_id),
        novel_id=novel_id,
        fact_type=StoryFactType.WORLD_STATE,
        subject="城中天气",
        predicate="状态",
        object_text=value,
        details={"schema_version": "world-state/1", "value": value},
        source_revision_id=source_id,
        source_document_id=uid(source_revision_id + 100) if source_revision_id else None,
        timeline_id=uid(timeline_id),
        dimension=dimension,
        event_kind="changed",
        story_sequence=sequence,
        visibility_json={"schema_version": "story-visibility/1", "scope": "author"},
        event_fingerprint=f"{fact_id:064x}",
        created_at=NOW,
    )


def event_link(
    link_id: int,
    novel_id: UUID,
    source_id: int,
    target_id: int,
    link_type: StoryEventLinkType,
) -> StoryEventLinkRecord:
    return StoryEventLinkRecord(
        id=uid(link_id),
        novel_id=novel_id,
        source_fact_id=uid(source_id),
        target_fact_id=uid(target_id),
        link_type=link_type,
        created_at=NOW,
    )


def test_default_main_timeline_and_instances_are_zero_configuration_and_idempotent() -> None:
    novel_id = uid(1)
    characters = [uid(10), uid(11)]
    ids = id_factory()
    plan = build_default_story_state(
        novel_id,
        characters,
        [],
        [],
        id_factory=ids,
        clock=lambda: NOW,
    )

    assert plan.timeline is not None
    assert plan.timeline.is_primary is True
    assert plan.timeline.timeline_kind is TimelineKind.MAIN
    assert len(plan.character_instances) == 2
    assert {item.continuity_kind for item in plan.character_instances} == {
        CharacterContinuityKind.NATIVE
    }

    repeated = build_default_story_state(
        novel_id,
        characters,
        [plan.timeline],
        list(plan.character_instances),
        id_factory=ids,
        clock=lambda: NOW,
    )
    assert repeated.timeline is None
    assert repeated.character_instances == ()


def test_single_timeline_resolves_but_multi_timeline_never_guesses() -> None:
    novel_id = uid(1)
    main = timeline(10, novel_id, primary=True)
    branch = timeline(11, novel_id, kind=TimelineKind.BRANCH, parent_id=10, anchor=20)

    assert resolve_timeline([main], novel_id).id == main.id
    with pytest.raises(StoryStateError) as error:
        resolve_timeline([main, branch], novel_id)
    assert error.value.code is StoryStateErrorCode.TIMELINE_REQUIRED
    assert resolve_timeline([main, branch], novel_id, branch.id).id == branch.id


def test_character_instance_resolution_is_id_based_and_never_name_based() -> None:
    novel_id = uid(1)
    root_id = uid(20)
    main_instance = instance(30, novel_id, 20, 10)
    parallel_instance = instance(
        31,
        novel_id,
        20,
        11,
        continuity=CharacterContinuityKind.DERIVED,
        derived_from=30,
    )

    assert (
        resolve_character_instance(
            [main_instance, parallel_instance],
            novel_id,
            character_id=root_id,
            timeline_id=uid(10),
        ).id
        == main_instance.id
    )
    with pytest.raises(StoryStateError) as error:
        resolve_character_instance(
            [main_instance, parallel_instance], novel_id, character_id=root_id
        )
    assert error.value.code is StoryStateErrorCode.CHARACTER_INSTANCE_REQUIRED
    assert (
        resolve_character_instance(
            [main_instance, parallel_instance],
            novel_id,
            character_instance_id=parallel_instance.id,
        ).id
        == parallel_instance.id
    )


def test_inheritance_must_be_a_dag_but_does_not_require_link_graph_acyclicity() -> None:
    novel_id = uid(1)
    first = timeline(10, novel_id, kind=TimelineKind.BRANCH, parent_id=11, anchor=2)
    second = timeline(11, novel_id, kind=TimelineKind.BRANCH, parent_id=10, anchor=3)

    with pytest.raises(StoryStateError) as error:
        validate_inheritance_dag([first, second], novel_id)
    assert error.value.code is StoryStateErrorCode.INVALID_INHERITANCE

    main = timeline(20, novel_id, primary=True)
    branch = timeline(21, novel_id, kind=TimelineKind.BRANCH, parent_id=20, anchor=4)
    link_ab = build_timeline_link(
        novel_id,
        main.id,
        branch.id,
        TimelineLinkType.LOOP_RETURN,
        [main, branch],
        id_factory=id_factory(200),
        clock=lambda: NOW,
    )
    link_ba = build_timeline_link(
        novel_id,
        branch.id,
        main.id,
        TimelineLinkType.CAUSAL,
        [main, branch],
        id_factory=id_factory(201),
        clock=lambda: NOW,
    )
    assert link_ab.source_timeline_id == link_ba.target_timeline_id
    validate_inheritance_dag([main, branch], novel_id)


def test_fork_derives_active_local_instances_without_copying_facts_or_travelers() -> None:
    novel_id = uid(1)
    main = timeline(10, novel_id, primary=True)
    local = instance(30, novel_id, 20, 10)
    archived = instance(31, novel_id, 21, 10, lifecycle=LifecycleState.ARCHIVED)
    traveler = instance(
        32,
        novel_id,
        22,
        9,
        continuity=CharacterContinuityKind.TRAVELER,
    )
    plan = fork_timeline(
        novel_id,
        main.id,
        timeline_key="branch-red",
        name="红线",
        fork_story_sequence=25,
        fork_anchor_json={"chapter": 3},
        timelines=[main],
        instances=[local, archived, traveler],
        id_factory=id_factory(100),
        clock=lambda: NOW,
    )

    assert plan.timeline.parent_timeline_id == main.id
    assert plan.timeline.fork_story_sequence == 25
    assert plan.copied_fact_count == 0
    assert len(plan.derived_instances) == 1
    assert plan.derived_instances[0].derived_from_instance_id == local.id
    assert plan.derived_instances[0].origin_timeline_id == plan.timeline.id


def test_branch_projection_inherits_only_parent_pre_anchor_and_isolates_sibling() -> None:
    novel_id = uid(1)
    main = timeline(10, novel_id, primary=True)
    branch = timeline(11, novel_id, kind=TimelineKind.BRANCH, parent_id=10, anchor=10)
    sibling = timeline(12, novel_id, kind=TimelineKind.BRANCH, parent_id=10, anchor=10)
    facts = [
        fact(100, novel_id, 10, 5, "晴"),
        fact(101, novel_id, 10, 11, "暴雨"),
        fact(102, novel_id, 11, 12, "薄雾"),
        fact(103, novel_id, 12, 8, "大雪"),
    ]

    projection = project_story_facts(
        novel_id,
        branch.id,
        narrative_cutoff=20,
        timelines=[main, branch, sibling],
        facts=facts,
    )

    assert [item.id for item in projection.visible_facts] == [uid(100), uid(102)]
    assert [item.id for item in projection.current_facts] == [uid(102)]
    assert uid(101) in projection.suppressed_fact_ids
    assert uid(103) not in {item.id for item in projection.visible_facts}
    assert projection.inheritance_path == (main.id, branch.id)


def test_nested_branch_never_inherits_beyond_earlier_query_cutoff() -> None:
    novel_id = uid(1)
    main = timeline(10, novel_id, primary=True)
    branch = timeline(11, novel_id, kind=TimelineKind.BRANCH, parent_id=10, anchor=20)
    nested = timeline(12, novel_id, kind=TimelineKind.BRANCH, parent_id=11, anchor=30)
    before_cutoff = fact(100, novel_id, 10, 8, "晴")
    after_cutoff = fact(101, novel_id, 10, 12, "雨")

    projection = project_story_facts(
        novel_id,
        nested.id,
        narrative_cutoff=10,
        timelines=[main, branch, nested],
        facts=[before_cutoff, after_cutoff],
    )

    assert [item.id for item in projection.visible_facts] == [before_cutoff.id]
    assert after_cutoff.id in projection.suppressed_fact_ids


def test_projection_reports_unknown_evidence_and_equal_position_conflicts() -> None:
    novel_id = uid(1)
    main = timeline(10, novel_id, primary=True)
    sourced = fact(100, novel_id, 10, 2, "晴", source_revision_id=50)
    no_sequence = fact(101, novel_id, 10, None, "未知")
    first = fact(102, novel_id, 10, 5, "雨")
    second = fact(103, novel_id, 10, 5, "雪")

    projection = project_story_facts(
        novel_id,
        main.id,
        narrative_cutoff=10,
        timelines=[main],
        facts=[sourced, no_sequence, first, second],
    )

    assert set(projection.ambiguous_fact_ids) == {sourced.id, no_sequence.id}
    assert len(projection.conflicts) == 1
    assert set(projection.conflicts[0].fact_ids) == {first.id, second.id}
    assert projection.current_facts == ()


def test_explicit_supersedes_selects_new_fact_and_contradiction_remains_visible() -> None:
    novel_id = uid(1)
    main = timeline(10, novel_id, primary=True)
    old = fact(100, novel_id, 10, 5, "雨")
    new = fact(101, novel_id, 10, 5, "晴")
    other = fact(102, novel_id, 10, 6, "晴", dimension="temperature")
    supersedes = event_link(200, novel_id, 101, 100, StoryEventLinkType.SUPERSEDES)
    contradicts = event_link(201, novel_id, 101, 102, StoryEventLinkType.CONTRADICTS)

    projection = project_story_facts(
        novel_id,
        main.id,
        narrative_cutoff=10,
        timelines=[main],
        facts=[old, new, other],
        event_links=[supersedes, contradicts],
    )

    assert old.id in projection.suppressed_fact_ids
    assert {item.id for item in projection.visible_facts} == {new.id, other.id}
    assert any(item.reason == "explicit_contradiction" for item in projection.conflicts)
    assert projection.current_facts == ()


def test_projection_accepts_only_explicitly_valid_source_revisions() -> None:
    novel_id = uid(1)
    main = timeline(10, novel_id, primary=True)
    accepted = fact(100, novel_id, 10, 2, "晴", source_revision_id=50)
    invalid = fact(101, novel_id, 10, 3, "雨", source_revision_id=51)
    projection = project_story_facts(
        novel_id,
        main.id,
        narrative_cutoff=10,
        timelines=[main],
        facts=[accepted, invalid],
        source_revision_validity={uid(50): True, uid(51): False},
    )

    assert [item.id for item in projection.visible_facts] == [accepted.id]
    assert invalid.id in projection.ambiguous_fact_ids
