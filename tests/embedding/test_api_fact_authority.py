from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from backend.creative_data_models import StoryEventLink
from backend.embedding import api
from backend.embedding.retrieval import KnowledgeProjectionScope
from backend.models import DerivedSourceBinding, IntelligenceCommitBatch, StoryFact


NOW = datetime(2026, 9, 2, tzinfo=UTC)


def uid(value: int) -> UUID:
    return UUID(int=value)


def knowledge_fact(
    value: int,
    *,
    key: str,
    source_revision_id: int | None,
    timeline_id: int = 10,
    observer_id: int = 20,
    status: str = "active",
) -> StoryFact:
    return StoryFact(
        id=uid(value),
        novel_id=uid(1),
        fact_type="knowledge_event",
        subject="林岚",
        predicate="knowledge",
        object_text=key,
        details={
            "schema_version": "knowledge-event/1",
            "operation": "learn",
            "knowledge_key": key,
        },
        source_revision_id=(uid(source_revision_id) if source_revision_id else None),
        source_document_id=(
            uid(source_revision_id + 1000) if source_revision_id else None
        ),
        schema_version="story-fact/2",
        timeline_id=uid(timeline_id),
        character_id=uid(30),
        character_instance_id=uid(observer_id),
        relationship_id=None,
        storyline_id=None,
        foreshadow_id=None,
        dimension="knowledge",
        event_kind="learn",
        story_sequence=4,
        story_time_json=None,
        visibility_json={"schema_version": "story-visibility/1", "scope": "author"},
        source_start=None,
        source_end=None,
        event_fingerprint=f"{value:064x}",
        status=status,
        created_at=NOW,
    )


def source_binding(
    value: int,
    *,
    fact_id: int,
    source_revision_id: int,
    validity_state: str = "current",
    commit_batch_id: int | None = None,
) -> DerivedSourceBinding:
    return DerivedSourceBinding(
        id=uid(value),
        derived_entity_id=uid(fact_id),
        source_chapter_id=uid(source_revision_id + 1000),
        source_chapter_revision_id=uid(source_revision_id),
        source_content_hash=f"{source_revision_id:064x}",
        proposal_item_id=None,
        commit_batch_id=(uid(commit_batch_id) if commit_batch_id else None),
        validity_state=validity_state,
        invalidated_at=None,
        restored_at=None,
        created_at=NOW,
    )


def commit_batch(value: int, *, source_revision_id: int, state: str) -> IntelligenceCommitBatch:
    return IntelligenceCommitBatch(
        id=uid(value),
        proposal_id=uid(value + 1000),
        chapter_revision_id=uid(source_revision_id),
        commit_key=f"{value:064x}",
        state=state,
        accepted_item_ids=[],
        inverse_operations={},
        expected_story_ledger_version=1,
        committed_at=NOW,
        reverted_at=NOW if state == "reverted" else None,
        created_at=NOW,
    )


def supersedes_link(value: int, *, source_fact_id: int, target_fact_id: int) -> StoryEventLink:
    return StoryEventLink(
        id=uid(value),
        novel_id=uid(1),
        source_fact_id=uid(source_fact_id),
        target_fact_id=uid(target_fact_id),
        link_type="supersedes",
        details_json={},
        created_at=NOW,
    )


class FakeSession:
    def __init__(
        self,
        *,
        scalars_results: dict[type[Any], list[list[Any]]] | None = None,
        facts_by_id: dict[UUID, StoryFact] | None = None,
    ) -> None:
        self.scalars_results = {
            key: [list(batch) for batch in batches]
            for key, batches in (scalars_results or {}).items()
        }
        self.facts_by_id = facts_by_id or {}
        self.statements: list[str] = []

    @staticmethod
    def _entity(statement) -> type[Any]:
        entity = statement.column_descriptions[0].get("entity")
        assert entity is not None
        return entity

    def scalars(self, statement):
        self.statements.append(str(statement))
        queue = self.scalars_results.get(self._entity(statement), [])
        return queue.pop(0) if queue else []

    def get(self, model: type[Any], identity: UUID):
        if model is StoryFact:
            return self.facts_by_id.get(identity)
        return None


def character_scope() -> KnowledgeProjectionScope:
    return KnowledgeProjectionScope(
        novel_id=uid(1),
        reachable_timeline_ids=frozenset({uid(10)}),
        perspective="character_instance",
        observer_character_instance_id=uid(20),
        timeline_sequence_limits=((uid(10), 10),),
    )


def story_fact_source(fact: StoryFact) -> SimpleNamespace:
    return SimpleNamespace(
        status="current",
        source_type="story_fact",
        source_entity_id=fact.id,
        source_revision_id=fact.source_revision_id,
        novel_id=fact.novel_id,
    )


def test_known_visibility_resolves_mixed_same_revision_bindings_per_fact() -> None:
    accepted = knowledge_fact(100, key="secret:accepted", source_revision_id=50)
    invalid = knowledge_fact(101, key="secret:invalid", source_revision_id=50)
    session = FakeSession(
        scalars_results={
            StoryFact: [[accepted, invalid]],
            DerivedSourceBinding: [[
                source_binding(200, fact_id=100, source_revision_id=50),
                source_binding(
                    201,
                    fact_id=101,
                    source_revision_id=50,
                    validity_state="source_superseded",
                ),
            ]],
            StoryEventLink: [[]],
        }
    )

    known = api._known_visibility_keys(
        session,
        novel_id=uid(1),
        scope=character_scope(),
    )

    assert known == frozenset({"secret:accepted"})


def test_known_visibility_excludes_reverted_batch_fact() -> None:
    reverted = knowledge_fact(100, key="secret:reverted", source_revision_id=50)
    session = FakeSession(
        scalars_results={
            StoryFact: [[reverted]],
            DerivedSourceBinding: [[
                source_binding(
                    200,
                    fact_id=100,
                    source_revision_id=50,
                    commit_batch_id=300,
                ),
            ]],
            IntelligenceCommitBatch: [[
                commit_batch(300, source_revision_id=50, state="reverted"),
            ]],
            StoryEventLink: [[]],
        }
    )

    known = api._known_visibility_keys(
        session,
        novel_id=uid(1),
        scope=character_scope(),
    )

    assert known == frozenset()


def test_known_visibility_excludes_fact_with_incoming_supersedes() -> None:
    old = knowledge_fact(100, key="secret:old", source_revision_id=None)
    session = FakeSession(
        scalars_results={
            StoryFact: [[old]],
            DerivedSourceBinding: [[]],
            StoryEventLink: [[
                supersedes_link(200, source_fact_id=101, target_fact_id=100),
            ]],
        }
    )

    known = api._known_visibility_keys(
        session,
        novel_id=uid(1),
        scope=character_scope(),
    )

    assert known == frozenset()


@pytest.mark.parametrize(
    ("batch_state", "expected"),
    [("committed", True), ("reverted", False)],
)
def test_story_fact_semantic_source_uses_commit_batch_state(
    batch_state: str,
    expected: bool,
) -> None:
    fact = knowledge_fact(100, key="secret:source", source_revision_id=50)
    session = FakeSession(
        facts_by_id={fact.id: fact},
        scalars_results={
            DerivedSourceBinding: [[
                source_binding(
                    200,
                    fact_id=100,
                    source_revision_id=50,
                    commit_batch_id=300,
                ),
            ]],
            IntelligenceCommitBatch: [[
                commit_batch(300, source_revision_id=50, state=batch_state),
            ]],
            StoryEventLink: [[]],
        },
    )

    assert api._source_is_current(session, story_fact_source(fact)) is expected


def test_story_fact_semantic_source_uses_incoming_supersedes() -> None:
    fact = knowledge_fact(100, key="secret:source", source_revision_id=None)
    session = FakeSession(
        facts_by_id={fact.id: fact},
        scalars_results={
            DerivedSourceBinding: [[]],
            StoryEventLink: [[
                supersedes_link(200, source_fact_id=101, target_fact_id=100),
            ]],
        },
    )

    assert api._source_is_current(session, story_fact_source(fact)) is False
