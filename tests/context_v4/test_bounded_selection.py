from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from backend.context_v4 import ContextAssemblyError, ContextAssemblyErrorCode, RetrievalPurpose
from backend.context_v4_loader import (
    MAX_ADJACENT_CHAPTERS,
    MAX_CHARACTER_INSTANCES,
    MAX_FACT_CANDIDATES,
    MAX_PRIVATE_ASSETS,
    MAX_SEMANTIC_HITS,
    _character_blocks,
    _private_asset_blocks,
    _select_adjacent_chapter_refs,
    _select_story_facts,
    _semantic_blocks,
    _validate_target_timeline_scope,
)
from backend.embedding.writing import WritingPosition
from backend.creative_data_models import StoryEventLink
from backend.models import DerivedSourceBinding, StoryFact


def uid(value: int) -> UUID:
    return UUID(int=value)


def _chapter_row(sequence: int) -> SimpleNamespace:
    return SimpleNamespace(
        document_id=uid(1_000 + sequence),
        title=f"第 {sequence} 章",
        narrative_sequence=sequence,
        revision_id=uid(10_000 + sequence),
        content_hash=f"{sequence:064x}",
    )


class _ExecuteSession:
    def __init__(self, batches: list[list[Any]]) -> None:
        self.batches = list(batches)
        self.statements: list[Any] = []

    def execute(self, statement: Any) -> list[Any]:
        self.statements.append(statement)
        return self.batches.pop(0)


def test_generation_adjacent_selector_is_body_free_and_never_returns_more_than_eight() -> None:
    target = SimpleNamespace(document_id=uid(50), narrative_sequence=100)
    candidates = [_chapter_row(sequence) for sequence in range(99, 90, -1)]
    session = _ExecuteSession([[target], candidates])

    refs = _select_adjacent_chapter_refs(
        session,  # type: ignore[arg-type]
        novel_id=uid(1),
        target_document_id=uid(50),
        target_narrative_sequence=100,
        purpose=RetrievalPurpose.CHAPTER_BODY,
    )

    assert [item.narrative_sequence for item in refs] == list(range(92, 100))
    assert len(refs) == MAX_ADJACENT_CHAPTERS
    assert session.statements[1]._limit_clause.value == MAX_ADJACENT_CHAPTERS + 1
    selected_column_names = set(session.statements[1].selected_columns.keys())
    assert "content_markdown" not in selected_column_names
    assert "content_text" not in selected_column_names
    assert {"markdown_character_count", "text_character_count"}.issubset(
        selected_column_names
    )


def test_review_adjacent_selector_uses_four_before_and_four_after() -> None:
    target = SimpleNamespace(document_id=uid(50), narrative_sequence=100)
    previous = [_chapter_row(sequence) for sequence in range(99, 94, -1)]
    following = [_chapter_row(sequence) for sequence in range(101, 106)]
    session = _ExecuteSession([[target], previous, following])

    refs = _select_adjacent_chapter_refs(
        session,  # type: ignore[arg-type]
        novel_id=uid(1),
        target_document_id=uid(50),
        target_narrative_sequence=100,
        purpose=RetrievalPurpose.REVIEW,
    )

    assert [item.narrative_sequence for item in refs] == [
        96,
        97,
        98,
        99,
        101,
        102,
        103,
        104,
    ]
    assert [item._limit_clause.value for item in session.statements[1:]] == [5, 5]


def test_target_position_mismatch_is_reported_as_scope_unresolved() -> None:
    target = SimpleNamespace(document_id=uid(50), narrative_sequence=99)
    session = _ExecuteSession([[target]])

    with pytest.raises(ContextAssemblyError) as captured:
        _select_adjacent_chapter_refs(
            session,  # type: ignore[arg-type]
            novel_id=uid(1),
            target_document_id=uid(50),
            target_narrative_sequence=100,
            purpose=RetrievalPurpose.CHAPTER_BODY,
        )

    assert captured.value.code is ContextAssemblyErrorCode.CONTEXT_SCOPE_UNRESOLVED
    assert captured.value.details["observed_narrative_sequence"] == 99


def test_single_timeline_target_requires_the_frozen_identity_mapping() -> None:
    timeline = SimpleNamespace(novel_id=uid(1), id=uid(2))
    position = WritingPosition(
        novel_id=uid(1),
        document_id=uid(50),
        title="target",
        narrative_sequence=100,
        timeline_id=uid(2),
        story_sequence_cutoff=99,
        mapping_version="stale-mapping/1",
    )

    with pytest.raises(ContextAssemblyError) as captured:
        _validate_target_timeline_scope(
            SimpleNamespace(),  # type: ignore[arg-type]
            position=position,
            timelines=(timeline,),  # type: ignore[arg-type]
        )

    assert captured.value.code is ContextAssemblyErrorCode.CONTEXT_SCOPE_UNRESOLVED


class _ScalarSession:
    def __init__(self, values: list[Any], *, malformed: Any = None) -> None:
        self.values = values
        self.malformed = malformed
        self.statements: list[Any] = []

    def scalar(self, statement: Any) -> Any:
        self.statements.append(statement)
        return self.malformed

    def scalars(self, statement: Any) -> list[Any]:
        self.statements.append(statement)
        return self.values

    def execute(self, statement: Any) -> list[Any]:
        self.statements.append(statement)
        return self.values


def test_character_cap_plus_one_and_fact_driver_overreturn_fail_closed() -> None:
    character_session = _ScalarSession(
        [uid(index + 1) for index in range(MAX_CHARACTER_INSTANCES + 1)]
    )
    with pytest.raises(ContextAssemblyError) as character_error:
        _character_blocks(
            character_session,  # type: ignore[arg-type]
            uid(1),
            timeline_id=uid(2),
        )
    assert character_error.value.code is ContextAssemblyErrorCode.CONTEXT_SELECTION_INCOMPLETE
    assert character_session.statements[0]._limit_clause.value == MAX_CHARACTER_INSTANCES + 1

    fact_session = _ScalarSession(
        [uid(index + 1) for index in range(MAX_FACT_CANDIDATES + 1)]
    )
    scope = SimpleNamespace(
        timeline=SimpleNamespace(id=uid(2)),
        story_limits={uid(2): 1_000},
    )
    with pytest.raises(ContextAssemblyError) as fact_error:
        _select_story_facts(
            fact_session,  # type: ignore[arg-type]
            novel_id=uid(1),
            scope=scope,  # type: ignore[arg-type]
        )
    assert fact_error.value.code is ContextAssemblyErrorCode.CONTEXT_SELECTION_INCOMPLETE
    candidate_statement = next(
        item
        for item in fact_session.statements
        if item.column_descriptions[0].get("entity") is StoryFact
        and item._limit_clause is not None
        and item._limit_clause.value == MAX_FACT_CANDIDATES
    )
    assert candidate_statement._limit_clause.value == MAX_FACT_CANDIDATES


def test_asset_and_semantic_caps_apply_after_stable_reference_deduplication() -> None:
    duplicate = {
        "asset_id": str(uid(1)),
        "asset_version_id": str(uid(101)),
        "title": "same",
        "content": "same",
    }
    assets = [duplicate, dict(duplicate)] + [
        {
            "asset_id": str(uid(index + 2)),
            "asset_version_id": str(uid(index + 102)),
            "title": f"asset-{index}",
            "content": "content",
        }
        for index in range(MAX_PRIVATE_ASSETS)
    ]
    with pytest.raises(ContextAssemblyError) as asset_error:
        _private_asset_blocks(uid(1), assets)
    assert asset_error.value.code is ContextAssemblyErrorCode.CONTEXT_SELECTION_INCOMPLETE
    assert asset_error.value.details["candidate_count"] == MAX_PRIVATE_ASSETS + 1

    hits = [
        {
            "source_id": str(uid(index + 1)),
            "source_revision_id": str(uid(index + 101)),
            "source_start": 0,
            "source_end": 10,
            "snippet": f"hit-{index}",
        }
        for index in range(MAX_SEMANTIC_HITS + 1)
    ]
    with pytest.raises(ContextAssemblyError) as semantic_error:
        _semantic_blocks(uid(1), {"hits": hits})
    assert semantic_error.value.code is ContextAssemblyErrorCode.CONTEXT_SELECTION_INCOMPLETE
    assert semantic_error.value.details["candidate_count"] == MAX_SEMANTIC_HITS + 1


class _FactSelectionSession:
    def __init__(self, candidates: list[SimpleNamespace], final_row: StoryFact) -> None:
        self.candidates = candidates
        self.final_row = final_row
        self.statements: list[Any] = []

    def scalar(self, statement: Any) -> Any:
        self.statements.append(statement)
        return None

    def execute(self, statement: Any) -> list[Any]:
        self.statements.append(statement)
        return self.candidates

    def scalars(self, statement: Any) -> list[Any]:
        self.statements.append(statement)
        entity = statement.column_descriptions[0].get("entity")
        if entity in {StoryEventLink, DerivedSourceBinding}:
            return []
        if entity is StoryFact:
            return [self.final_row]
        return [self.final_row.id]


def test_story_fact_full_fields_are_hydrated_only_after_final_projection_selection() -> None:
    now = datetime(2026, 9, 2, tzinfo=UTC)
    candidates = [
        SimpleNamespace(
            id=uid(index),
            source_revision_id=None,
            status="active",
            story_sequence=index,
        )
        for index in (10, 11, 12)
    ]
    final = StoryFact(
        id=uid(12),
        novel_id=uid(1),
        schema_version="story-fact/2",
        fact_type="general_fact",
        subject="door",
        predicate="state",
        object_text="open",
        details={"schema_version": "general-fact/1", "value": "open"},
        timeline_id=uid(2),
        dimension="door-state",
        event_kind="confirmed",
        story_sequence=12,
        visibility_json={"schema_version": "story-visibility/1", "scope": "all"},
        event_fingerprint=sha256(b"fact-12").hexdigest(),
        status="active",
        created_at=now,
    )
    session = _FactSelectionSession(candidates, final)
    scope = SimpleNamespace(
        timeline=SimpleNamespace(id=uid(2)),
        story_limits={uid(2): 100},
    )

    facts, links, source_validity, omitted_count = _select_story_facts(
        session,  # type: ignore[arg-type]
        novel_id=uid(1),
        scope=scope,  # type: ignore[arg-type]
    )

    assert [item.id for item in facts] == [final.id]
    assert links == ()
    assert source_validity == {}
    assert omitted_count == 2
    full_hydration = next(
        statement
        for statement in session.statements
        if statement.column_descriptions[0].get("entity") is StoryFact
        and len(statement.selected_columns) > 4
    )
    bound_values = [
        value
        for value in full_hydration.compile().params.values()
        if isinstance(value, (list, tuple))
    ]
    assert any(value == [final.id] or value == (final.id,) for value in bound_values)


class _FinalFactCapSession:
    def __init__(self) -> None:
        self.candidates = [
            SimpleNamespace(
                id=uid(index + 1),
                source_revision_id=None,
                status="active",
                story_sequence=index + 1,
            )
            for index in range(161)
        ]
        now = datetime(2026, 9, 2, tzinfo=UTC)
        self.fact_rows = [
            StoryFact(
                id=item.id,
                novel_id=uid(1),
                schema_version="story-fact/2",
                fact_type="general_fact",
                subject=f"entity-{index}",
                predicate="state",
                object_text=f"value-{index}",
                details={"schema_version": "general-fact/1", "value": f"value-{index}"},
                timeline_id=uid(2),
                dimension="state",
                event_kind="confirmed",
                story_sequence=index + 1,
                visibility_json={"schema_version": "story-visibility/1", "scope": "all"},
                event_fingerprint=sha256(f"fact-{index}".encode()).hexdigest(),
                status="active",
                created_at=now,
            )
            for index, item in enumerate(self.candidates)
        ]
        self.statements: list[Any] = []
        self.scalar_calls = 0

    def scalar(self, statement: Any) -> Any:
        self.statements.append(statement)
        self.scalar_calls += 1
        return None if self.scalar_calls == 1 else len(self.candidates)

    def execute(self, statement: Any) -> list[Any]:
        self.statements.append(statement)
        return self.candidates

    def scalars(self, statement: Any) -> list[Any]:
        self.statements.append(statement)
        entity = statement.column_descriptions[0].get("entity")
        if entity in {StoryEventLink, DerivedSourceBinding}:
            return []
        if entity is StoryFact and len(statement.selected_columns) > 4:
            return self.fact_rows[:160]
        return [item.id for item in self.candidates]


def test_final_story_fact_selection_caps_at_160_and_audits_omission() -> None:
    session = _FinalFactCapSession()
    scope = SimpleNamespace(
        timeline=SimpleNamespace(id=uid(2)),
        story_limits={uid(2): 1_000},
    )

    facts, links, source_validity, omitted_count = _select_story_facts(
        session,  # type: ignore[arg-type]
        novel_id=uid(1),
        scope=scope,  # type: ignore[arg-type]
    )

    assert len(facts) == 160
    assert links == ()
    assert source_validity == {}
    assert omitted_count == 1
    final_statement = next(
        item
        for item in session.statements
        if item.column_descriptions[0].get("entity") is None
        and item._limit_clause is not None
    )
    assert final_statement._limit_clause.value == 160
    assert any(
        item.column_descriptions[0].get("entity") is StoryFact
        and len(item.selected_columns) > 4
        for item in session.statements
    )
