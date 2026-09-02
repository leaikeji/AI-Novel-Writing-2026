from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest

from backend.creative_data_models import SemanticChunk, SemanticSource
from backend.embedding.contracts import EmbeddingCorpus
from backend.embedding.query_service import DenseQueryInput, execute_bounded_retrieval
from backend.embedding.retrieval import (
    CorpusQuota,
    RetrievalChannelStatus,
    RetrievalPurpose,
    SearchScope,
    SemanticSearchRequestV2,
    TimelineSearchLimit,
    writing_retrieval_policy_v3,
)


pytestmark = pytest.mark.long_novel


def _uid(value: int) -> UUID:
    return UUID(int=value)


def _source(value: int) -> SemanticSource:
    return SemanticSource(
        id=_uid(10_000 + value),
        generation_id=_uid(4),
        novel_id=_uid(3),
        corpus="manuscript",
        source_type="chapter_revision",
        source_entity_id=_uid(20_000 + value),
        source_revision_id=_uid(30_000 + value),
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


def _chunk(value: int, source: SemanticSource, ordinal: int = 1) -> SemanticChunk:
    return SemanticChunk(
        id=_uid(40_000 + value * 10 + ordinal),
        generation_id=_uid(4),
        source_id=source.id,
        chunk_index=ordinal,
        source_start=ordinal * 10,
        source_end=ordinal * 10 + 9,
        content_text=f"蓝钥匙证据 {value}:{ordinal}",
        content_hash="c" * 64,
        estimated_token_count=8,
        token_estimator_version="unicode-char-estimate/1",
        chunker_version="semantic-char-chunker/5b",
    )


class _ScaleSession:
    def __init__(self, outputs: list[list[tuple[object, ...]]]) -> None:
        self.outputs = outputs
        self.execute_count = 0

    def execute(self, _statement: object) -> SimpleNamespace:
        self.execute_count += 1
        rows = self.outputs.pop(0)
        return SimpleNamespace(all=lambda: rows)


def test_hybrid_candidate_and_neighbor_work_stays_constant_at_scale() -> None:
    sources = tuple(_source(index) for index in range(160))
    chunks = tuple(_chunk(index, source) for index, source in enumerate(sources))
    adjacent = [
        (sources[index], _chunk(index, sources[index], ordinal))
        for index in range(10)
        for ordinal in (0, 2)
    ]
    session = _ScaleSession(
        [
            [(chunk.id, index / 100) for index, chunk in enumerate(chunks[:120])],
            [
                (chunk.id, 1.0 - index / 1_000)
                for index, chunk in enumerate(chunks[40:160])
            ],
            [(source, chunk) for source, chunk in zip(sources, chunks)],
            adjacent,
        ]
    )
    request = SemanticSearchRequestV2(
        query="蓝钥匙",
        purpose=RetrievalPurpose.CHAPTER_BODY,
        top_k=50,
        scope=SearchScope(
            owner_id=_uid(1),
            workspace_id=_uid(2),
            novel_id=_uid(3),
            generation_id=_uid(4),
            index_version=7,
            corpora=frozenset({EmbeddingCorpus.MANUSCRIPT}),
            target_timeline_id=_uid(5),
            timeline_limits=(TimelineSearchLimit(timeline_id=_uid(5)),),
        ),
    )
    policy = writing_retrieval_policy_v3().model_copy(
        update={
            "corpus_quotas": (
                CorpusQuota(corpus=EmbeddingCorpus.MANUSCRIPT, limit=50),
            )
        }
    )

    execution = execute_bounded_retrieval(
        session,  # type: ignore[arg-type]
        request=request,
        dense_input=DenseQueryInput(
            status=RetrievalChannelStatus.AVAILABLE,
            vector=(1.0, 0.0),
        ),
        policy=policy,
    )

    assert execution.dense_candidate_count == 80
    assert execution.lexical_candidate_count == 80
    assert execution.enriched_candidate_count <= 160
    assert execution.adjacent_candidate_count <= 20
    assert len(execution.result.hits) <= 10
    assert all(len(hit.chunks) - 1 <= 2 for hit in execution.result.hits)
    assert sum(len(hit.chunks) - 1 for hit in execution.result.hits) <= 20
    assert session.execute_count == 4
