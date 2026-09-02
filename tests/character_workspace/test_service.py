from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from backend.character_workspace import (
    CharacterWorkspaceError,
    CharacterWorkspaceErrorCode,
    CharacterWorkspaceService,
)
from backend.creative_data_models import (
    CharacterInstance,
    CharacterInstanceRevision,
    NovelCharacterRevision,
    StoryTimeline,
)
from backend.models import (
    ChapterBrief,
    CharacterAlias,
    CharacterRelationship,
    CharacterVoiceBinding,
    Document,
    Novel,
    NovelCharacter,
    StoryFact,
)


NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


class MemoryStore:
    def __init__(self, root: NovelCharacter) -> None:
        self.root = root
        self.novel_row = Novel(
            id=root.novel_id,
            title="测试小说",
            character_catalog_version=7,
            story_ledger_version=11,
        )
        self.root_revision: NovelCharacterRevision | None = None
        self.timeline_rows: list[StoryTimeline] = []
        self.instance_rows: list[CharacterInstance] = []
        self.instance_revisions: dict[UUID, CharacterInstanceRevision] = {}
        self.alias_rows: list[CharacterAlias] = []
        self.relationship_rows: list[CharacterRelationship] = []
        self.brief_rows: list[tuple[ChapterBrief, Document]] = []
        self.voice: CharacterVoiceBinding | None = None
        self.fact_rows: list[StoryFact] = []
        self.projection_payload: dict[str, object] = {}
        self.projection_calls: list[tuple[UUID, UUID, int | None]] = []

    def novel(self, novel_id: UUID):
        return self.novel_row if self.novel_row.id == novel_id else None

    def character(self, novel_id: UUID, character_id: UUID):
        if (self.root.novel_id, self.root.id) == (novel_id, character_id):
            return self.root
        return None

    def character_revision(self, character: NovelCharacter):
        return self.root_revision

    def timelines(self, novel_id: UUID):
        return tuple(item for item in self.timeline_rows if item.novel_id == novel_id)

    def instances(self, novel_id: UUID, character_id: UUID):
        return tuple(
            item
            for item in self.instance_rows
            if item.novel_id == novel_id and item.character_id == character_id
        )

    def instance_revision(self, instance: CharacterInstance):
        return self.instance_revisions.get(instance.id)

    def aliases(self, novel_id: UUID, character_id: UUID):
        return tuple(
            item
            for item in self.alias_rows
            if item.novel_id == novel_id and item.character_id == character_id
        )

    def relationships(self, novel_id: UUID, character_id: UUID):
        return tuple(
            item
            for item in self.relationship_rows
            if item.novel_id == novel_id
            and character_id in {item.source_character_id, item.target_character_id}
        )

    def chapter_briefs(self, novel_id: UUID):
        return tuple(
            item for item in self.brief_rows if item[1].novel_id == novel_id
        )

    def voice_binding(self, novel_id: UUID, character_id: UUID):
        if self.voice and (self.voice.novel_id, self.voice.character_id) == (
            novel_id,
            character_id,
        ):
            return self.voice
        return None

    def projection(self, novel_id: UUID, timeline_id: UUID, narrative_cutoff: int | None):
        self.projection_calls.append((novel_id, timeline_id, narrative_cutoff))
        return dict(self.projection_payload)

    def story_facts(
        self,
        novel_id: UUID,
        character_id: UUID,
        relationship_ids: tuple[UUID, ...] = (),
    ):
        return tuple(
            item
            for item in self.fact_rows
            if item.novel_id == novel_id
            and (
                item.character_id == character_id
                or item.relationship_id in relationship_ids
            )
        )


def root_character() -> NovelCharacter:
    return NovelCharacter(
        id=uuid4(),
        novel_id=uuid4(),
        role_type="main",
        name="林岚",
        description="调查员",
        details={"theme": "truth"},
        lifecycle_state="active",
        position=1,
        version=2,
    )


def timeline(root: NovelCharacter, *, name: str = "主时间线", position: int = 0):
    return StoryTimeline(
        id=uuid4(),
        novel_id=root.novel_id,
        timeline_key=f"line-{position}",
        name=name,
        normalized_name=name,
        timeline_kind="main" if position == 0 else "branch",
        is_primary=position == 0,
        parent_timeline_id=None if position == 0 else uuid4(),
        fork_story_sequence=None if position == 0 else 1,
        fork_anchor_json={},
        lifecycle_state="active",
        position=position,
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )


def instance(root: NovelCharacter, line: StoryTimeline, *, label: str = ""):
    return CharacterInstance(
        id=uuid4(),
        novel_id=root.novel_id,
        character_id=root.id,
        origin_timeline_id=line.id,
        continuity_kind="native",
        display_label=label,
        lifecycle_state="active",
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )


def projected_fact(root: NovelCharacter, person: CharacterInstance, line: StoryTimeline):
    fact_id = uuid4()
    return {
        "id": str(fact_id),
        "novel_id": str(root.novel_id),
        "schema_version": "story-fact/2",
        "fact_type": "character_state",
        "subject": "林岚",
        "predicate": "location",
        "object_text": "旧港",
        "details": {"schema_version": "character-state/1", "value": "旧港"},
        "source_revision_id": None,
        "source_document_id": None,
        "timeline_id": str(line.id),
        "character_id": str(root.id),
        "character_instance_id": str(person.id),
        "relationship_id": None,
        "storyline_id": None,
        "foreshadow_id": None,
        "dimension": "location",
        "event_kind": "moved",
        "story_sequence": 3,
        "story_time_json": None,
        "visibility_json": {"schema_version": "story-visibility/1", "scope": "author"},
        "source_start": None,
        "source_end": None,
        "event_fingerprint": "f" * 64,
        "status": "active",
        "created_at": NOW.isoformat(),
    }


def single_line_store() -> tuple[MemoryStore, StoryTimeline, CharacterInstance]:
    root = root_character()
    store = MemoryStore(root)
    line = timeline(root)
    person = instance(root, line)
    store.timeline_rows.append(line)
    store.instance_rows.append(person)
    fact = projected_fact(root, person, line)
    store.projection_payload = {
        "novel_id": str(root.novel_id),
        "timeline_id": str(line.id),
        "narrative_cutoff": 8,
        "visible_facts": [fact],
        "current_facts": [fact],
        "conflicts": [],
        "ambiguous_fact_ids": [],
        "suppressed_fact_ids": [],
        "inheritance_path": [str(line.id)],
    }
    store.fact_rows.append(
        StoryFact(
            id=UUID(str(fact["id"])),
            novel_id=root.novel_id,
            fact_type="character_state",
            subject=root.name,
            predicate="location",
            object_text="旧港",
            details={"schema_version": "character-state/1", "value": "旧港"},
            schema_version="story-fact/2",
            timeline_id=line.id,
            character_id=root.id,
            character_instance_id=person.id,
            dimension="location",
            event_kind="moved",
            story_sequence=3,
            visibility_json={"schema_version": "story-visibility/1", "scope": "author"},
            event_fingerprint="f" * 64,
            status="active",
            created_at=NOW,
        )
    )
    return store, line, person


def chapter_reference(
    root: NovelCharacter, line: StoryTimeline, person: CharacterInstance
) -> tuple[ChapterBrief, Document]:
    document = Document(
        id=uuid4(),
        novel_id=root.novel_id,
        kind="chapter",
        title="第一章",
        position=1,
        status="draft",
        version=1,
    )
    brief = ChapterBrief(
        id=uuid4(),
        document_id=document.id,
        version=1,
        target_word_count=3000,
        expectation_text="",
        outline_text="",
        forbidden_text="",
        role_constraints={
            "required": [root.name],
            "_v3": {
                "schema_version": "chapter-role-constraints/3",
                "timeline_id": str(line.id),
                "required_characters": [
                    {
                        "character_id": str(root.id),
                        "character_instance_id": str(person.id),
                        "display_label": root.name,
                    }
                ],
                "point_of_view": None,
            },
        },
    )
    return brief, document


def test_single_timeline_resolves_without_extra_arguments() -> None:
    store, line, person = single_line_store()
    service = CharacterWorkspaceService(store)

    workspace = service.get_workspace(store.root.novel_id, store.root.id, narrative_cutoff=8)

    assert workspace.schema_version == "character-workspace/2"
    assert workspace.timeline_mode == "single"
    assert workspace.character_catalog_version == 7
    assert workspace.story_ledger_version == 11
    assert workspace.selected_timeline.id == line.id
    assert workspace.selected_instance.id == person.id
    assert workspace.projected_state.current_facts[0].object_text == "旧港"
    assert store.projection_calls == [(store.root.novel_id, line.id, 8)]


def test_workspace_returns_only_v2_with_current_and_historical_facts() -> None:
    store, line, person = single_line_store()
    raw = store.projection_payload["current_facts"][0]  # type: ignore[index]
    action_id = uuid4()
    action_payload = {
        **raw,
        "id": str(action_id),
        "predicate": "opened_door",
        "object_text": "打开暗门",
        "details": {
            "schema_version": "character-state/1",
            "value": "打开暗门",
        },
        "dimension": "action",
        "story_sequence": 4,
        "event_fingerprint": "8" * 64,
    }
    store.projection_payload["visible_facts"].append(action_payload)  # type: ignore[union-attr]
    store.projection_payload["current_facts"].append(action_payload)  # type: ignore[union-attr]
    store.fact_rows.append(
        StoryFact(
            id=action_id,
            novel_id=store.root.novel_id,
            fact_type="character_state",
            subject=store.root.name,
            predicate="opened_door",
            object_text="打开暗门",
            details={"schema_version": "character-state/1", "value": "打开暗门"},
            schema_version="story-fact/2",
            timeline_id=line.id,
            character_id=store.root.id,
            character_instance_id=person.id,
            dimension="action",
            event_kind="acted",
            story_sequence=4,
            visibility_json={"schema_version": "story-visibility/1", "scope": "author"},
            event_fingerprint="8" * 64,
            status="active",
            created_at=NOW,
        )
    )
    service = CharacterWorkspaceService(store)

    workspace = service.get_workspace(store.root.novel_id, store.root.id)

    assert workspace.schema_version == "character-workspace/2"
    assert [fact.object_text for fact in workspace.projected_state.current_facts] == [
        "旧港"
    ]
    location = next(
        slot for slot in workspace.writing_state.slots if slot.key == "location"
    )
    assert [value.object_text for value in location.values] == ["旧港"]
    assert workspace.writing_state.history_summary.current == 1
    assert workspace.writing_state.history_summary.historical == 1


def test_multiline_requires_explicit_timeline_before_projection() -> None:
    store, _, _ = single_line_store()
    branch = timeline(store.root, name="支线", position=1)
    branch.parent_timeline_id = store.timeline_rows[0].id
    store.timeline_rows.append(branch)
    store.instance_rows.append(instance(store.root, branch))

    with pytest.raises(CharacterWorkspaceError) as caught:
        CharacterWorkspaceService(store).get_workspace(store.root.novel_id, store.root.id)

    assert caught.value.code is CharacterWorkspaceErrorCode.TIMELINE_REQUIRED
    assert set(caught.value.details["timeline_ids"]) == {
        str(item.id) for item in store.timeline_rows
    }
    assert store.projection_calls == []


def test_multiline_requires_explicit_instance_even_when_one_local_candidate_exists() -> None:
    store, main, main_person = single_line_store()
    branch = timeline(store.root, name="支线", position=1)
    branch.parent_timeline_id = main.id
    branch_person = instance(store.root, branch)
    store.timeline_rows.append(branch)
    store.instance_rows.append(branch_person)

    with pytest.raises(CharacterWorkspaceError) as caught:
        CharacterWorkspaceService(store).get_workspace(
            store.root.novel_id,
            store.root.id,
            timeline_id=branch.id,
        )

    assert caught.value.code is CharacterWorkspaceErrorCode.CHARACTER_INSTANCE_REQUIRED
    assert caught.value.details == {"character_instance_ids": [str(branch_person.id)]}

    store.projection_payload["timeline_id"] = str(branch.id)
    workspace = CharacterWorkspaceService(store).get_workspace(
        store.root.novel_id,
        store.root.id,
        timeline_id=branch.id,
        character_instance_id=branch_person.id,
    )
    assert workspace.selected_instance.id == branch_person.id
    assert workspace.selected_instance.id != main_person.id


def test_ambiguous_instance_returns_stable_error_and_never_guesses() -> None:
    store, line, _ = single_line_store()
    store.instance_rows.append(instance(store.root, line, label="穿越者"))

    with pytest.raises(CharacterWorkspaceError) as caught:
        CharacterWorkspaceService(store).get_workspace(
            store.root.novel_id, store.root.id, timeline_id=line.id
        )

    assert caught.value.code is CharacterWorkspaceErrorCode.CHARACTER_INSTANCE_REQUIRED
    assert len(caught.value.details["character_instance_ids"]) == 2
    assert store.projection_calls == []


def test_workspace_reads_revisions_alias_relationship_brief_and_root_voice_binding() -> None:
    store, line, person = single_line_store()
    store.root_revision = NovelCharacterRevision(
        id=uuid4(),
        novel_id=store.root.novel_id,
        character_id=store.root.id,
        character_version=store.root.version,
        source_kind="manual",
        operation_key="op",
        operation_hash="a" * 64,
        role_type=store.root.role_type,
        name=store.root.name,
        description=store.root.description,
        details_json=store.root.details,
        lifecycle_state="active",
        position=1,
        change_set_json={},
        content_hash="b" * 64,
    )
    revision = CharacterInstanceRevision(
        id=uuid4(),
        novel_id=store.root.novel_id,
        character_instance_id=person.id,
        revision_number=1,
        source_kind="manual",
        operation_key="instance-op",
        operation_hash="c" * 64,
        profile_schema_version=1,
        profile_json={"true_identity": "守门人"},
        change_set_json={},
        content_hash="d" * 64,
    )
    person.current_revision_id = revision.id
    store.instance_revisions[person.id] = revision
    alias = CharacterAlias(
        id=uuid4(),
        novel_id=store.root.novel_id,
        character_id=store.root.id,
        character_instance_id=person.id,
        timeline_id=line.id,
        alias="灰鸢",
        normalized_alias="灰鸢",
        alias_kind="cover_name",
        identity_layer="cover",
        source="manual",
        lifecycle_state="active",
    )
    store.alias_rows.append(alias)
    other_id = uuid4()
    relation = CharacterRelationship(
        id=uuid4(),
        novel_id=store.root.novel_id,
        source_character_id=store.root.id,
        target_character_id=other_id,
        timeline_id=line.id,
        source_character_instance_id=person.id,
        directionality="directed",
        relation_kind="ally",
        label="盟友",
        normalized_label="盟友",
        relation_pair_key="pair",
        status="active",
        created_by="manual",
        manual_override=True,
        evidence_json=[],
        version=1,
    )
    store.relationship_rows.append(relation)
    relationship_fact = dict(projected_fact(store.root, person, line))
    relationship_fact.update(
        {
            "id": str(uuid4()),
            "fact_type": "relationship_state",
            "character_id": None,
            "character_instance_id": None,
            "relationship_id": str(relation.id),
            "dimension": "trust",
            "event_kind": "strengthened",
            "predicate": "trust",
            "object_text": "加深",
            "details": {
                "schema_version": "relationship-state/1",
                "value": "加深",
            },
        }
    )
    store.projection_payload["visible_facts"].append(relationship_fact)  # type: ignore[union-attr]
    store.projection_payload["current_facts"].append(relationship_fact)  # type: ignore[union-attr]
    store.fact_rows.append(
        StoryFact(
            id=UUID(str(relationship_fact["id"])),
            novel_id=store.root.novel_id,
            fact_type="relationship_state",
            subject=store.root.name,
            predicate="trust",
            object_text="加深",
            details={"schema_version": "relationship-state/1", "value": "加深"},
            schema_version="story-fact/2",
            timeline_id=line.id,
            relationship_id=relation.id,
            dimension="trust",
            event_kind="strengthened",
            story_sequence=3,
            visibility_json={"schema_version": "story-visibility/1", "scope": "author"},
            event_fingerprint="e" * 64,
            status="active",
            created_at=NOW,
        )
    )
    store.brief_rows.append(chapter_reference(store.root, line, person))
    store.voice = CharacterVoiceBinding(
        id=uuid4(),
        novel_id=store.root.novel_id,
        character_id=store.root.id,
        profile_id=uuid4(),
        voice_version_id=uuid4(),
        binding_policy="dedicated",
        language="zh-CN",
        parameters_json={},
        version=2,
    )

    workspace = CharacterWorkspaceService(store).get_workspace(
        store.root.novel_id, store.root.id
    )

    assert workspace.character.current_revision_id == store.root_revision.id
    assert workspace.selected_instance.profile["true_identity"] == "守门人"
    assert [item.alias for item in workspace.aliases] == ["灰鸢"]
    assert [item.label for item in workspace.relationships] == ["盟友"]
    assert {item.dimension for item in workspace.projected_state.current_facts} == {
        "location",
        "trust",
    }
    assert workspace.chapter_references[0].reference_kinds == ("required",)
    assert workspace.voice_binding is not None
    assert workspace.voice_binding.binding_policy == "dedicated"


def test_legacy_name_only_chapter_brief_is_not_treated_as_stable_reference() -> None:
    store, _, _ = single_line_store()
    document = Document(
        id=uuid4(), novel_id=store.root.novel_id, kind="chapter",
        title="旧章纲", position=1, status="draft", version=1,
    )
    brief = ChapterBrief(
        id=uuid4(), document_id=document.id, version=1, target_word_count=3000,
        expectation_text="", outline_text="", forbidden_text="",
        role_constraints={"required": [store.root.name]},
    )
    store.brief_rows.append((brief, document))

    workspace = CharacterWorkspaceService(store).get_workspace(
        store.root.novel_id, store.root.id
    )

    assert workspace.chapter_references == ()


def test_archive_impact_separates_live_dependencies_from_preserved_facts() -> None:
    store, line, person = single_line_store()
    store.alias_rows.append(
        CharacterAlias(
            id=uuid4(), novel_id=store.root.novel_id, character_id=store.root.id,
            alias="灰鸢", normalized_alias="灰鸢", source="manual",
            lifecycle_state="active",
        )
    )
    store.brief_rows.append(chapter_reference(store.root, line, person))
    store.voice = CharacterVoiceBinding(
        id=uuid4(), novel_id=store.root.novel_id, character_id=store.root.id,
        profile_id=uuid4(), voice_version_id=uuid4(), binding_policy="dedicated",
        language="zh-CN", parameters_json={}, version=1,
    )
    store.fact_rows.append(
        StoryFact(
            id=uuid4(), novel_id=store.root.novel_id, fact_type="character_state",
            subject=store.root.name, predicate="identity", object_text="守门人",
            details={"schema_version": "character-state/1", "value": "守门人"},
            schema_version="story-fact/2", timeline_id=line.id,
            character_id=store.root.id, character_instance_id=person.id,
            dimension="identity", event_kind="revealed", story_sequence=2,
            visibility_json={"schema_version": "story-visibility/1", "scope": "author"},
            event_fingerprint="e" * 64, status="active",
        )
    )

    impact = CharacterWorkspaceService(store).archive_impact(
        store.root.novel_id, store.root.id
    )

    assert impact.requires_confirmation is True
    assert impact.current_dependency_count == 4
    assert impact.preserved_history_count == 2
    fact_ref = next(item for item in impact.references if item.reference_type == "story_fact")
    assert fact_ref.disposition == "preserved_history"


def test_services_are_structurally_read_only() -> None:
    import inspect

    from backend.character_workspace import service as module

    source = inspect.getsource(module)
    for forbidden in ("session.flush(", "session.commit(", "session.add(", "session.delete("):
        assert forbidden not in source
