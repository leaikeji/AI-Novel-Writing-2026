from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from backend.character_workspace.contracts import (
    CharacterWorkspaceError,
    CharacterWorkspaceErrorCode,
)
from backend.character_workspace.service import (
    CharacterFactReadSet,
    CharacterWorkspaceService,
)
from backend.models import (
    DerivedSourceBinding,
    Document,
    DocumentRevision,
    StoryFact,
)

from .test_service import MemoryStore, single_line_store


NOW = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)


class FactStore(MemoryStore):
    read_set: CharacterFactReadSet

    def fact_read_set(
        self,
        novel_id: UUID,
        character_id: UUID,
        relationship_ids: tuple[UUID, ...] = (),
    ) -> CharacterFactReadSet:
        assert novel_id == self.root.novel_id
        assert character_id == self.root.id
        return self.read_set


def story_fact(
    store: MemoryStore,
    line_id: UUID,
    person_id: UUID,
    *,
    dimension: str,
    value: str,
    sequence: int | None,
    created_offset: int,
    status: str = "active",
    source_document_id: UUID | None = None,
    source_revision_id: UUID | None = None,
    source_start: int | None = None,
    source_end: int | None = None,
) -> StoryFact:
    return StoryFact(
        id=uuid4(),
        novel_id=store.root.novel_id,
        fact_type="character_state",
        subject=store.root.name,
        predicate=dimension,
        object_text=value,
        details={"schema_version": "character-state/1", "value": value},
        source_revision_id=source_revision_id,
        source_document_id=source_document_id,
        schema_version="story-fact/2",
        timeline_id=line_id,
        character_id=store.root.id,
        character_instance_id=person_id,
        dimension=dimension,
        event_kind="updated",
        story_sequence=sequence,
        story_time_json=None,
        visibility_json={"schema_version": "story-visibility/1", "scope": "author"},
        source_start=source_start,
        source_end=source_end,
        event_fingerprint=hashlib.sha256(str(uuid4()).encode()).hexdigest(),
        status=status,
        created_at=NOW + timedelta(seconds=created_offset),
    )


def populated_store() -> tuple[FactStore, UUID, UUID, list[StoryFact]]:
    base, line, person = single_line_store()
    store = FactStore(base.root)
    store.novel_row = base.novel_row
    store.timeline_rows = base.timeline_rows
    store.instance_rows = base.instance_rows

    document = Document(
        id=uuid4(),
        novel_id=store.root.novel_id,
        kind="chapter",
        title="证据章",
        position=2,
        status="draft",
        version=1,
    )
    content = "甲😀乙在旧港发现线索。" + "潮" * 620
    revision = DocumentRevision(
        id=uuid4(),
        document_id=document.id,
        revision_number=1,
        content_markdown=content,
        content_text=content,
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        source="manual",
        created_at=NOW,
    )
    facts = [
        story_fact(
            store,
            line.id,
            person.id,
            dimension="location",
            value="旧港",
            sequence=4,
            created_offset=4,
            source_document_id=document.id,
            source_revision_id=revision.id,
            source_start=1,
            source_end=4,
        ),
        story_fact(
            store,
            line.id,
            person.id,
            dimension="action",
            value="追踪线索",
            sequence=5,
            created_offset=5,
        ),
        story_fact(
            store,
            line.id,
            person.id,
            dimension="identity",
            value="旧身份",
            sequence=2,
            created_offset=2,
        ),
        story_fact(
            store,
            line.id,
            person.id,
            dimension="emotion",
            value="迟疑",
            sequence=None,
            created_offset=3,
        ),
        story_fact(
            store,
            line.id,
            person.id,
            dimension="goal",
            value="已撤销目标",
            sequence=1,
            created_offset=1,
            status="superseded",
        ),
    ]
    current_binding = DerivedSourceBinding(
        id=uuid4(),
        derived_entity_type="story_fact",
        derived_entity_id=facts[0].id,
        source_chapter_id=document.id,
        source_chapter_revision_id=revision.id,
        source_content_hash=revision.content_hash,
        validity_state="current",
        created_at=NOW,
    )
    store.fact_rows = facts
    store.projection_payload = {
        "novel_id": str(store.root.novel_id),
        "timeline_id": str(line.id),
        "narrative_cutoff": 8,
        "visible_facts": [
            {"id": str(facts[0].id)},
            {"id": str(facts[1].id)},
            {"id": str(facts[2].id)},
        ],
        "current_facts": [
            {"id": str(facts[0].id)},
            {"id": str(facts[1].id)},
        ],
        "conflicts": [
            {
                "conflict_key": "identity",
                "fact_ids": [str(facts[2].id), str(facts[0].id)],
                "reason": "explicit_contradiction",
            }
        ],
        "ambiguous_fact_ids": [str(facts[3].id)],
        "suppressed_fact_ids": [str(facts[4].id)],
        "inheritance_path": [str(line.id)],
    }
    store.read_set = CharacterFactReadSet(
        facts=tuple(facts),
        bindings_by_fact_id={facts[0].id: (current_binding,)},
        documents_by_id={document.id: document},
        revisions_by_id={revision.id: revision},
        current_revision_by_document_id={document.id: revision.id},
        batch_state_by_id={},
        superseded_fact_ids=frozenset({facts[2].id}),
    )
    return store, line.id, person.id, facts


def test_fact_history_keeps_effective_state_and_health_orthogonal() -> None:
    store, line_id, person_id, facts = populated_store()

    page = CharacterWorkspaceService(store).list_facts(
        store.root.novel_id,
        store.root.id,
        timeline_id=line_id,
        character_instance_id=person_id,
        narrative_cutoff=8,
        limit=20,
    )

    by_id = {item.id: item for item in page.items}
    assert by_id[facts[0].id].effective_state == "current"
    assert by_id[facts[0].id].health == "conflict"
    assert by_id[facts[1].id].effective_state == "historical"
    assert by_id[facts[2].id].effective_state == "superseded"
    assert by_id[facts[2].id].health == "conflict"
    assert by_id[facts[3].id].effective_state == "historical"
    assert by_id[facts[3].id].health == "ambiguous"
    assert page.total_summary.total == 5
    assert page.total_summary.current == 1
    assert page.total_summary.historical == 2
    assert page.total_summary.superseded == 2


def test_source_hashes_use_unicode_code_points_and_never_return_whole_revision() -> None:
    store, line_id, person_id, facts = populated_store()

    page = CharacterWorkspaceService(store).list_facts(
        store.root.novel_id,
        store.root.id,
        timeline_id=line_id,
        character_instance_id=person_id,
    )

    source = next(item for item in page.items if item.id == facts[0].id).source
    assert source is not None
    revision = next(iter(store.read_set.revisions_by_id.values()))
    assert source.source_content_hash == revision.content_hash
    assert source.source_excerpt == "😀乙在"
    assert source.source_range_hash == hashlib.sha256("😀乙在".encode("utf-8")).hexdigest()
    assert source.source_coordinate == "unicode-codepoint-v1"
    assert source.revision_is_current is True
    assert len(source.source_excerpt) <= 500


def test_fact_history_cursor_is_stable_and_invalid_cursor_is_rejected() -> None:
    store, line_id, person_id, _facts = populated_store()
    service = CharacterWorkspaceService(store)

    first = service.list_facts(
        store.root.novel_id,
        store.root.id,
        timeline_id=line_id,
        character_instance_id=person_id,
        limit=2,
    )
    second = service.list_facts(
        store.root.novel_id,
        store.root.id,
        timeline_id=line_id,
        character_instance_id=person_id,
        cursor=first.next_cursor,
        limit=2,
    )

    assert first.next_cursor is not None
    assert set(item.id for item in first.items).isdisjoint(item.id for item in second.items)
    assert first.total_summary.total == second.total_summary.total == 5
    with pytest.raises(CharacterWorkspaceError) as caught:
        service.list_facts(
            store.root.novel_id,
            store.root.id,
            timeline_id=line_id,
            character_instance_id=person_id,
            cursor="not-a-cursor",
        )
    assert caught.value.code is CharacterWorkspaceErrorCode.INVALID_CURSOR


def test_filters_and_batch_revert_priority_share_the_same_summary_rules() -> None:
    store, line_id, person_id, facts = populated_store()
    batch_id = uuid4()
    binding = DerivedSourceBinding(
        id=uuid4(),
        derived_entity_type="story_fact",
        derived_entity_id=facts[4].id,
        source_chapter_id=uuid4(),
        source_chapter_revision_id=uuid4(),
        source_content_hash="a" * 64,
        commit_batch_id=batch_id,
        validity_state="current",
        created_at=NOW,
    )
    store.read_set = replace(
        store.read_set,
        bindings_by_fact_id={
            **store.read_set.bindings_by_fact_id,
            facts[4].id: (binding,),
        },
        batch_state_by_id={batch_id: "reverted"},
    )

    page = CharacterWorkspaceService(store).list_facts(
        store.root.novel_id,
        store.root.id,
        timeline_id=line_id,
        character_instance_id=person_id,
        effective_state="batch_reverted",
    )

    assert [item.id for item in page.items] == [facts[4].id]
    assert page.total_summary.model_dump() == {
        "total": 1,
        "current": 0,
        "historical": 0,
        "superseded": 0,
        "source_invalid": 0,
        "batch_reverted": 1,
    }
