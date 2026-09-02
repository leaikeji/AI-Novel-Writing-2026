from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

from sqlalchemy.dialects import postgresql

from backend.creative_data_models import SemanticChunk, SemanticSource
from backend.embedding.contracts import EmbeddingCorpus
from backend.embedding.query_service import DenseQueryInput, execute_bounded_retrieval
from backend.embedding.retrieval import (
    RetrievalChannelStatus,
    RetrievalPurpose,
    SearchScope,
    SemanticSearchRequestV2,
    TimelineSearchLimit,
)


def _uid(value: int) -> UUID:
    return UUID(int=value)


def _source(*, value: int, source_entity_id: UUID) -> SemanticSource:
    return SemanticSource(
        id=_uid(value),
        generation_id=_uid(4),
        novel_id=_uid(3),
        corpus="manuscript",
        source_type="chapter_revision",
        source_entity_id=source_entity_id,
        source_revision_id=_uid(value + 100),
        source_locator_json={},
        content_hash="a" * 64,
        renderer_version="semantic-v1-renderers/2",
        timeline_id=_uid(5),
        narrative_sequence_start=1,
        narrative_sequence_end=1,
        story_sequence_start=1,
        story_sequence_end=1,
        visibility_json={"visibility": "public"},
        status="current",
        source_fingerprint="b" * 64,
    )


def _chunk(*, value: int, source_id: UUID, ordinal: int) -> SemanticChunk:
    return SemanticChunk(
        id=_uid(value),
        generation_id=_uid(4),
        source_id=source_id,
        chunk_index=ordinal,
        source_start=ordinal * 10,
        source_end=ordinal * 10 + 9,
        content_text=f"证据块 {ordinal}",
        content_hash="c" * 64,
        estimated_token_count=4,
        token_estimator_version="unicode-char-estimate/1",
        chunker_version="semantic-char-chunker/5b",
    )


class _ScriptedSession:
    def __init__(self, outputs: list[list[tuple[object, ...]]]) -> None:
        self.outputs = outputs
        self.sql: list[str] = []

    def execute(self, statement: object) -> SimpleNamespace:
        self.sql.append(
            str(
                statement.compile(  # type: ignore[attr-defined]
                    dialect=postgresql.dialect(),
                    compile_kwargs={"literal_binds": True},
                )
            )
        )
        rows = self.outputs.pop(0)
        return SimpleNamespace(all=lambda: rows)


def _request() -> SemanticSearchRequestV2:
    return SemanticSearchRequestV2(
        query="蓝钥匙",
        purpose=RetrievalPurpose.CHAPTER_BODY,
        scope=SearchScope(
            owner_id=_uid(1),
            workspace_id=_uid(2),
            novel_id=_uid(3),
            generation_id=_uid(4),
            index_version=7,
            corpora=frozenset({EmbeddingCorpus.MANUSCRIPT}),
            target_timeline_id=_uid(5),
            narrative_sequence_cutoff=4,
            story_sequence_cutoff=8,
            timeline_limits=(
                TimelineSearchLimit(timeline_id=_uid(5), story_sequence_cutoff=8),
            ),
        ),
    )


def test_bounded_query_filters_before_limit_and_batch_enriches_once() -> None:
    source = _source(value=20, source_entity_id=_uid(30))
    anchor = _chunk(value=40, source_id=source.id, ordinal=1)
    neighbor = _chunk(value=41, source_id=source.id, ordinal=0)
    session = _ScriptedSession(
        [
            [(anchor.id, 0.8)],
            [(source, anchor)],
            [(source, neighbor)],
        ]
    )

    execution = execute_bounded_retrieval(
        session,  # type: ignore[arg-type]
        request=_request(),
        dense_input=DenseQueryInput(status=RetrievalChannelStatus.SKIPPED),
    )

    assert execution.lexical_candidate_count == 1
    assert execution.result.policy_version == "writing-retrieval/3"
    assert execution.enriched_candidate_count == 1
    assert execution.adjacent_candidate_count == 1
    assert [chunk.chunk_id for chunk in execution.result.hits[0].chunks] == [
        neighbor.id,
        anchor.id,
    ]
    assert len(session.sql) == 3
    candidate_sql = session.sql[0]
    assert "LIMIT 80" in candidate_sql
    assert "embedding_generation_novels" in candidate_sql
    assert "embedding_generations.state = 'active'" in candidate_sql
    assert "document_working_copies" in candidate_sql
    assert "semantic_sources.status = 'current'" in candidate_sql
    assert "semantic_sources.novel_id" in candidate_sql
    assert "semantic_sources.timeline_id" in candidate_sql
    assert "LIMIT 20" in session.sql[2]


def test_driver_overreturn_is_still_capped_to_eighty_candidates() -> None:
    source = _source(value=50, source_entity_id=_uid(60))
    chunks = tuple(
        _chunk(value=1_000 + index, source_id=source.id, ordinal=index)
        for index in range(81)
    )
    session = _ScriptedSession(
        [
            [(chunk.id, 1.0 - index / 1_000) for index, chunk in enumerate(chunks)],
            [(source, chunk) for chunk in chunks[:80]],
            [],
        ]
    )

    execution = execute_bounded_retrieval(
        session,  # type: ignore[arg-type]
        request=_request(),
        dense_input=DenseQueryInput(status=RetrievalChannelStatus.SKIPPED),
    )

    assert execution.lexical_candidate_count == 80
    assert execution.enriched_candidate_count == 80
