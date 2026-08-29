from __future__ import annotations

from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from backend.creative_data_models import (
    CharacterInstance,
    CharacterInstanceRevision,
    StoryTimeline,
    StoryTimelineLink,
)
from backend.models import DerivedSourceBinding, Novel, NovelCharacter, StoryFact
from backend.story_state.contracts import (
    CharacterContinuityKind,
    StoryStateError,
    StoryStateErrorCode,
    TimelineLinkType,
)
from backend.story_state.persistence import (
    PersistenceErrorCode,
    StoryStatePersistenceError,
    create_character_instance,
    create_timeline_link,
    ensure_default_story_state,
    fork_timeline,
    get_character_instance_payload,
    get_story_fact_payload,
    get_story_projection_payload,
    get_timeline_payload,
    list_character_instance_payloads,
    list_story_fact_payloads,
    list_timeline_link_payloads,
    list_timeline_payloads,
    patch_character_instance,
)


NOW = datetime(2026, 8, 29, tzinfo=UTC)


def uid(value: int) -> UUID:
    return UUID(int=value)


def id_factory(start: int = 1000):
    values = count(start)
    return lambda: uid(next(values))


def novel(version: int = 1) -> Novel:
    return Novel(id=uid(1), title="测试小说", story_ledger_version=version)


def timeline(
    value: int,
    *,
    novel_id: UUID = uid(1),
    parent: int | None = None,
    anchor: int | None = None,
    primary: bool = False,
    version: int = 1,
    position: int = 0,
) -> StoryTimeline:
    kind = "main" if parent is None else "branch"
    return StoryTimeline(
        id=uid(value),
        novel_id=novel_id,
        timeline_key=f"line-{value}",
        name=f"时间线 {value}",
        normalized_name=f"时间线 {value}",
        timeline_kind=kind,
        is_primary=primary,
        parent_timeline_id=uid(parent) if parent is not None else None,
        fork_story_sequence=anchor,
        fork_anchor_json={},
        lifecycle_state="active",
        position=position,
        version=version,
        created_at=NOW,
        updated_at=NOW,
    )


def instance(
    value: int,
    *,
    character_id: int = 20,
    timeline_id: int = 10,
    current_revision_id: int | None = None,
    version: int = 1,
    novel_id: UUID = uid(1),
) -> CharacterInstance:
    return CharacterInstance(
        id=uid(value),
        novel_id=novel_id,
        character_id=uid(character_id),
        origin_timeline_id=uid(timeline_id),
        derived_from_instance_id=None,
        continuity_kind="native",
        display_label="主线版本",
        current_revision_id=(uid(current_revision_id) if current_revision_id else None),
        lifecycle_state="active",
        version=version,
        created_at=NOW,
        updated_at=NOW,
    )


def character(value: int = 20) -> NovelCharacter:
    return NovelCharacter(
        id=uid(value),
        novel_id=uid(1),
        role_type="protagonist",
        name="林岚",
        description="",
        details={},
        lifecycle_state="active",
        position=1,
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )


def fact(value: int, timeline_id: int, sequence: int, text: str) -> StoryFact:
    return StoryFact(
        id=uid(value),
        novel_id=uid(1),
        fact_type="world_state",
        subject="天气",
        predicate="状态",
        object_text=text,
        details={"schema_version": "world-state/1", "value": text},
        source_revision_id=None,
        source_document_id=None,
        schema_version="story-fact/2",
        timeline_id=uid(timeline_id),
        character_id=None,
        character_instance_id=None,
        relationship_id=None,
        storyline_id=None,
        foreshadow_id=None,
        dimension="weather",
        event_kind="changed",
        story_sequence=sequence,
        story_time_json=None,
        visibility_json={"schema_version": "story-visibility/1", "scope": "author"},
        source_start=None,
        source_end=None,
        event_fingerprint=f"{value:064x}",
        status="active",
        created_at=NOW,
    )


class FakeSession:
    """Statement-aware fake; it never opens a database connection."""

    def __init__(
        self,
        *,
        scalar_results: dict[type[Any], list[Any]] | None = None,
        scalars_results: dict[type[Any], list[list[Any]]] | None = None,
    ) -> None:
        self.scalar_results = {key: list(value) for key, value in (scalar_results or {}).items()}
        self.scalars_results = {
            key: [list(batch) for batch in value]
            for key, value in (scalars_results or {}).items()
        }
        self.statements: list[str] = []
        self.added: list[Any] = []
        self.flush_count = 0
        self.commit_count = 0

    @staticmethod
    def _entity(statement) -> type[Any]:
        entity = statement.column_descriptions[0].get("entity")
        assert entity is not None
        return entity

    def scalar(self, statement):
        self.statements.append(str(statement))
        queue = self.scalar_results.get(self._entity(statement), [])
        return queue.pop(0) if queue else None

    def scalars(self, statement):
        self.statements.append(str(statement))
        queue = self.scalars_results.get(self._entity(statement), [])
        return queue.pop(0) if queue else []

    def add(self, value: Any) -> None:
        self.added.append(value)

    def add_all(self, values) -> None:
        self.added.extend(values)

    def flush(self) -> None:
        self.flush_count += 1

    def commit(self) -> None:
        self.commit_count += 1
        raise AssertionError("persistence adapter must not commit")


def test_default_mainline_initialization_flushes_one_atomic_plan_without_commit() -> None:
    novel_row = novel()
    session = FakeSession(
        scalar_results={Novel: [novel_row]},
        scalars_results={
            StoryTimeline: [[]],
            CharacterInstance: [[]],
            NovelCharacter: [[uid(20)]],
        },
    )

    payload = ensure_default_story_state(
        session,
        uid(1),
        expected_story_ledger_version=1,
        id_factory=id_factory(),
        clock=lambda: NOW,
    )

    assert len([row for row in session.added if isinstance(row, StoryTimeline)]) == 1
    assert len([row for row in session.added if isinstance(row, CharacterInstance)]) == 1
    assert payload["timeline"]["is_primary"] is True
    assert payload["story_ledger_version"] == 2
    assert session.flush_count == 1
    assert session.commit_count == 0
    assert all("story_timelines.novel_id" in sql for sql in session.statements[1:2])


def test_default_initialization_is_idempotent_and_does_not_advance_cas_on_noop() -> None:
    novel_row = novel()
    main = timeline(10, primary=True)
    native = instance(30)
    session = FakeSession(
        scalar_results={Novel: [novel_row]},
        scalars_results={
            StoryTimeline: [[main]],
            CharacterInstance: [[native]],
            NovelCharacter: [[uid(20)]],
        },
    )

    payload = ensure_default_story_state(
        session,
        uid(1),
        expected_story_ledger_version=1,
        clock=lambda: NOW,
    )

    assert payload["timeline"] is None
    assert session.added == []
    assert session.flush_count == 0
    assert novel_row.story_ledger_version == 1


def test_multi_timeline_get_requires_explicit_id_and_never_guesses_primary() -> None:
    main = timeline(10, primary=True)
    branch = timeline(11, parent=10, anchor=5, position=1)
    session = FakeSession(
        scalar_results={Novel: [novel()]},
        scalars_results={StoryTimeline: [[main, branch]]},
    )

    with pytest.raises(StoryStateError) as error:
        get_timeline_payload(session, uid(1))
    assert error.value.code is StoryStateErrorCode.TIMELINE_REQUIRED
    assert session.flush_count == 0


def test_single_timeline_and_single_instance_payloads_resolve_without_ids() -> None:
    main = timeline(10, primary=True)
    native = instance(30)
    timeline_session = FakeSession(
        scalar_results={Novel: [novel()]},
        scalars_results={StoryTimeline: [[main]]},
    )
    instance_session = FakeSession(
        scalar_results={Novel: [novel()]},
        scalars_results={CharacterInstance: [[native]]},
    )

    assert get_timeline_payload(timeline_session, uid(1))["id"] == str(main.id)
    assert (
        get_character_instance_payload(instance_session, uid(1))["id"]
        == str(native.id)
    )


def test_fork_derives_instances_clones_instance_revision_and_never_copies_facts() -> None:
    novel_row = novel()
    main = timeline(10, primary=True)
    native = instance(30, current_revision_id=31)
    revision = CharacterInstanceRevision(
        id=uid(31),
        novel_id=uid(1),
        character_instance_id=native.id,
        revision_number=2,
        parent_revision_id=None,
        restored_from_revision_id=None,
        source_kind="manual",
        operation_key="source",
        operation_hash="a" * 64,
        profile_schema_version=1,
        profile_json={"occupation": "记者"},
        change_set_json={},
        content_hash="b" * 64,
        created_at=NOW,
    )
    session = FakeSession(
        scalar_results={Novel: [novel_row], CharacterInstanceRevision: [revision]},
        scalars_results={StoryTimeline: [[main]], CharacterInstance: [[native]]},
    )

    payload = fork_timeline(
        session,
        uid(1),
        main.id,
        expected_story_ledger_version=1,
        expected_source_timeline_version=1,
        timeline_key="red",
        name="红线",
        fork_story_sequence=12,
        id_factory=id_factory(100),
        clock=lambda: NOW,
    )

    added_facts = [row for row in session.added if isinstance(row, StoryFact)]
    derived = [row for row in session.added if isinstance(row, CharacterInstance)]
    revisions = [row for row in session.added if isinstance(row, CharacterInstanceRevision)]
    assert added_facts == []
    assert payload["copied_fact_count"] == 0
    assert len(derived) == len(revisions) == 1
    assert derived[0].current_revision_id == revisions[0].id
    assert derived[0].current_revision_id != native.current_revision_id
    assert revisions[0].profile_json == revision.profile_json
    assert revisions[0].character_instance_id == derived[0].id
    assert session.flush_count == 3
    assert session.commit_count == 0


def test_fork_rejects_stale_source_version_before_any_write() -> None:
    session = FakeSession(
        scalar_results={Novel: [novel()]},
        scalars_results={
            StoryTimeline: [[timeline(10, primary=True, version=2)]],
            CharacterInstance: [[]],
        },
    )

    with pytest.raises(StoryStatePersistenceError) as error:
        fork_timeline(
            session,
            uid(1),
            uid(10),
            expected_story_ledger_version=1,
            expected_source_timeline_version=1,
            timeline_key="red",
            name="红线",
            fork_story_sequence=12,
        )
    assert error.value.code is PersistenceErrorCode.VERSION_CONFLICT
    assert session.added == []
    assert session.flush_count == 0


def test_explicit_timeline_link_is_novel_scoped_cas_guarded_and_flush_only() -> None:
    novel_row = novel()
    main = timeline(10, primary=True)
    branch = timeline(11, parent=10, anchor=5, position=1)
    session = FakeSession(
        scalar_results={Novel: [novel_row], StoryTimelineLink: [None]},
        scalars_results={StoryTimeline: [[main, branch]]},
    )

    payload = create_timeline_link(
        session,
        uid(1),
        source_timeline_id=main.id,
        target_timeline_id=branch.id,
        link_type=TimelineLinkType.LOOP_RETURN,
        expected_story_ledger_version=1,
        expected_source_timeline_version=1,
        expected_target_timeline_version=1,
        id_factory=id_factory(),
        clock=lambda: NOW,
    )

    assert isinstance(session.added[0], StoryTimelineLink)
    assert payload["story_ledger_version"] == 2
    assert session.flush_count == 1
    assert session.commit_count == 0
    assert any("story_timeline_links.novel_id" in sql for sql in session.statements)


def test_character_creation_uses_single_line_resolution_and_stable_ids_only() -> None:
    novel_row = novel()
    main = timeline(10, primary=True)
    root = character()
    session = FakeSession(
        scalar_results={Novel: [novel_row], NovelCharacter: [root]},
        scalars_results={StoryTimeline: [[main]], CharacterInstance: [[]]},
    )

    payload = create_character_instance(
        session,
        uid(1),
        character_id=root.id,
        timeline_id=None,
        continuity_kind=CharacterContinuityKind.NATIVE,
        display_label="默认版本",
        expected_story_ledger_version=1,
        expected_timeline_version=1,
        id_factory=id_factory(),
        clock=lambda: NOW,
    )

    assert payload["character_id"] == str(root.id)
    assert payload["origin_timeline_id"] == str(main.id)
    assert "name" not in payload
    assert session.flush_count == 1


def test_character_creation_in_multi_line_mode_requires_timeline_id() -> None:
    session = FakeSession(
        scalar_results={Novel: [novel()], NovelCharacter: [character()]},
        scalars_results={
            StoryTimeline: [[
                timeline(10, primary=True),
                timeline(11, parent=10, anchor=5, position=1),
            ]],
        },
    )

    with pytest.raises(StoryStateError) as error:
        create_character_instance(
            session,
            uid(1),
            character_id=uid(20),
            timeline_id=None,
            continuity_kind=CharacterContinuityKind.NATIVE,
            display_label="默认版本",
            expected_story_ledger_version=1,
            expected_timeline_version=1,
        )
    assert error.value.code is StoryStateErrorCode.TIMELINE_REQUIRED
    assert session.flush_count == 0


def test_derived_instance_cannot_cross_character_root_ids() -> None:
    source = instance(31, character_id=21, timeline_id=9)
    session = FakeSession(
        scalar_results={Novel: [novel()], NovelCharacter: [character()]},
        scalars_results={
            StoryTimeline: [[timeline(10, primary=True)]],
            CharacterInstance: [[source]],
        },
    )

    with pytest.raises(StoryStateError) as error:
        create_character_instance(
            session,
            uid(1),
            character_id=uid(20),
            timeline_id=uid(10),
            continuity_kind=CharacterContinuityKind.DERIVED,
            derived_from_instance_id=source.id,
            display_label="错误派生",
            expected_story_ledger_version=1,
            expected_timeline_version=1,
        )
    assert error.value.code is StoryStateErrorCode.CHARACTER_INSTANCE_CONFLICT
    assert session.added == []
    assert session.flush_count == 0


def test_character_instance_patch_enforces_novel_scope_and_both_cas_versions() -> None:
    novel_row = novel()
    row = instance(30, version=2)
    session = FakeSession(
        scalar_results={Novel: [novel_row], CharacterInstance: [row]},
    )

    payload = patch_character_instance(
        session,
        uid(1),
        row.id,
        expected_story_ledger_version=1,
        expected_instance_version=2,
        display_label="改名后的区分标签",
        clock=lambda: NOW,
    )

    assert payload["display_label"] == "改名后的区分标签"
    assert payload["version"] == 3
    assert payload["story_ledger_version"] == 2
    assert session.flush_count == 1
    assert "character_instances.novel_id" in session.statements[-1]


def test_stale_ledger_cas_stops_before_loading_or_writing_children() -> None:
    session = FakeSession(scalar_results={Novel: [novel(version=3)]})

    with pytest.raises(StoryStatePersistenceError) as error:
        ensure_default_story_state(
            session,
            uid(1),
            expected_story_ledger_version=2,
        )
    assert error.value.code is PersistenceErrorCode.VERSION_CONFLICT
    assert error.value.current == {"story_ledger_version": 3}
    assert len(session.statements) == 1
    assert session.flush_count == 0


def test_readonly_projection_inherits_parent_pre_anchor_and_excludes_sibling() -> None:
    main = timeline(10, primary=True)
    branch = timeline(11, parent=10, anchor=10, position=1)
    sibling = timeline(12, parent=10, anchor=10, position=2)
    rows = [
        fact(100, 10, 5, "晴"),
        fact(101, 10, 11, "雨"),
        fact(102, 11, 12, "雾"),
        fact(103, 12, 8, "雪"),
    ]
    session = FakeSession(
        scalar_results={Novel: [novel()]},
        scalars_results={
            StoryTimeline: [[main, branch, sibling]],
            StoryFact: [rows],
            # No StoryEventLink/DerivedSourceBinding rows.
        },
    )

    payload = get_story_projection_payload(
        session,
        uid(1),
        timeline_id=branch.id,
        narrative_cutoff=20,
    )

    assert [item["id"] for item in payload["visible_facts"]] == [str(uid(100)), str(uid(102))]
    assert str(uid(101)) in payload["suppressed_fact_ids"]
    assert str(uid(103)) not in [item["id"] for item in payload["visible_facts"]]
    assert session.added == []
    assert session.flush_count == 0
    assert session.commit_count == 0
    assert all(
        "novel_id" in sql
        for sql in session.statements
        if "story_timelines" in sql or "story_facts" in sql or "story_event_links" in sql
    )


def test_list_helpers_are_readonly_and_novel_scoped() -> None:
    main = timeline(10, primary=True)
    native = instance(30)
    link = StoryTimelineLink(
        id=uid(50),
        novel_id=uid(1),
        source_timeline_id=uid(10),
        target_timeline_id=uid(11),
        link_type="causal",
        source_story_sequence=2,
        target_story_sequence=3,
        details_json={},
        link_fingerprint="a" * 64,
        lifecycle_state="active",
        version=1,
        created_at=NOW,
    )
    timeline_session = FakeSession(
        scalar_results={Novel: [novel()]},
        scalars_results={StoryTimeline: [[main]]},
    )
    instance_session = FakeSession(
        scalar_results={Novel: [novel()]},
        scalars_results={CharacterInstance: [[native]]},
    )
    link_session = FakeSession(
        scalar_results={Novel: [novel()]},
        scalars_results={StoryTimelineLink: [[link]]},
    )
    fact_row = fact(100, 10, 5, "晴")
    fact_session = FakeSession(
        scalar_results={Novel: [novel()]},
        scalars_results={StoryFact: [[fact_row]]},
    )
    fact_get_session = FakeSession(
        scalar_results={Novel: [novel()], StoryFact: [fact_row]},
    )

    assert len(list_timeline_payloads(timeline_session, uid(1))) == 1
    assert len(list_character_instance_payloads(instance_session, uid(1))) == 1
    assert len(list_timeline_link_payloads(link_session, uid(1))) == 1
    assert len(list_story_fact_payloads(fact_session, uid(1))) == 1
    assert get_story_fact_payload(fact_get_session, uid(1), fact_row.id)["id"] == str(
        fact_row.id
    )
    for session in (
        timeline_session,
        instance_session,
        link_session,
        fact_session,
        fact_get_session,
    ):
        assert session.added == []
        assert session.flush_count == 0
        assert session.commit_count == 0
        assert "novel_id" in session.statements[-1]


def test_adapter_source_contains_no_commit_call() -> None:
    source_path = Path(__file__).parents[2] / "backend" / "story_state" / "persistence.py"
    source_text = source_path.resolve().read_text(encoding="utf-8")
    assert ".commit(" not in source_text
