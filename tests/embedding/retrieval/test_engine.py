from __future__ import annotations

from uuid import UUID

import pytest

from backend.embedding.contracts import EmbeddingCorpus
from backend.embedding.retrieval import (
    CandidateFilterReason,
    CandidateVisibility,
    CorpusQuota,
    RawChannelScore,
    RetrievalCandidate,
    RetrievalChannel,
    RetrievalChannelEvidence,
    RetrievalChannelStatus,
    RetrievalDegradationReason,
    RetrievalEmptyReason,
    RetrievalMode,
    RetrievalPerspective,
    RetrievalPolicyV1,
    RetrievalPurpose,
    SearchScope,
    SemanticSearchRequestV2,
    TimelineSearchLimit,
    filter_candidates,
    retrieve,
    writing_retrieval_policy_v3,
)


def uid(value: int) -> UUID:
    return UUID(int=value)


def scope(**overrides) -> SearchScope:
    payload = {
        "owner_id": uid(1),
        "workspace_id": uid(2),
        "novel_id": uid(3),
        "generation_id": uid(4),
        "index_version": 7,
        "corpora": frozenset(
            {
                EmbeddingCorpus.MANUSCRIPT,
                EmbeddingCorpus.PLANNING,
                EmbeddingCorpus.PRIVATE_ASSET,
            }
        ),
        "target_timeline_id": uid(10),
        "narrative_sequence_cutoff": 3,
        "story_sequence_cutoff": 20,
        "timeline_limits": (
            TimelineSearchLimit(timeline_id=uid(9), story_sequence_cutoff=5),
            TimelineSearchLimit(timeline_id=uid(10), story_sequence_cutoff=20),
        ),
    }
    payload.update(overrides)
    return SearchScope(**payload)


def candidate(value: int, **overrides) -> RetrievalCandidate:
    payload = {
        "chunk_id": uid(value),
        "owner_id": uid(1),
        "workspace_id": uid(2),
        "novel_id": uid(3),
        "generation_id": uid(4),
        "index_version": 7,
        "corpus": EmbeddingCorpus.MANUSCRIPT,
        "source_type": "chapter_revision",
        "source_id": uid(100 + value),
        "source_revision_id": uid(200 + value),
        "chunk_ordinal": 0,
        "text": f"证据块 {value}",
        "timeline_id": uid(10),
        "narrative_sequence_start": 2,
        "narrative_sequence_end": 2,
        "story_sequence_start": 10,
        "story_sequence_end": 10,
    }
    payload.update(overrides)
    return RetrievalCandidate(**payload)


def request(search_scope: SearchScope | None = None, *, top_k: int = 10):
    return SemanticSearchRequestV2(
        query="寻找能够解释人物选择的前文证据",
        purpose=RetrievalPurpose.CHAPTER_BODY,
        scope=search_scope or scope(),
        top_k=top_k,
    )


def lexical(*scores: tuple[int, float]) -> RetrievalChannelEvidence:
    return RetrievalChannelEvidence(
        channel=RetrievalChannel.LEXICAL,
        status=RetrievalChannelStatus.AVAILABLE,
        scores=tuple(RawChannelScore(chunk_id=uid(key), score=value) for key, value in scores),
    )


def dense_available(*scores: tuple[int, float]) -> RetrievalChannelEvidence:
    return RetrievalChannelEvidence(
        channel=RetrievalChannel.DENSE,
        status=RetrievalChannelStatus.AVAILABLE,
        scores=tuple(RawChannelScore(chunk_id=uid(key), score=value) for key, value in scores),
        provider_request_id="req-redacted-1",
        token_count=12,
        latency_ms=45,
    )


def dense_skipped() -> RetrievalChannelEvidence:
    return RetrievalChannelEvidence(
        channel=RetrievalChannel.DENSE,
        status=RetrievalChannelStatus.SKIPPED,
    )


def test_filtering_precedes_ranking_so_hidden_high_score_cannot_shift_rank() -> None:
    visible = candidate(30)
    sibling = candidate(31, timeline_id=uid(11))
    future = candidate(
        32,
        narrative_sequence_start=4,
        narrative_sequence_end=4,
    )
    stale = candidate(33, source_current=False)
    result = retrieve(
        request(),
        candidates=(visible, sibling, future, stale),
        lexical=lexical((31, 1.0), (32, 0.9), (33, 0.8), (30, 0.1)),
        dense=dense_skipped(),
        policy=RetrievalPolicyV1(adjacent_chunk_radius=0),
    )

    assert [item.anchor_chunk_id for item in result.hits] == [visible.chunk_id]
    assert result.hits[0].lexical_rank == 1
    assert result.hits[0].lexical_raw_score == 0.1
    assert result.hits[0].fused_score == pytest.approx(1 / 61)
    assert [item.chunk_id for item in result.lexical.scores] == [visible.chunk_id]
    counts = {item.reason: item.count for item in result.diagnostics.filtered}
    assert counts == {
        CandidateFilterReason.STALE_SOURCE: 1,
        CandidateFilterReason.UNREACHABLE_TIMELINE: 1,
        CandidateFilterReason.FUTURE_NARRATIVE: 1,
    }


def test_authority_binding_and_index_filters_fail_closed_before_scoring() -> None:
    wrong_novel = candidate(34, novel_id=uid(999))
    unbound = candidate(
        35,
        corpus=EmbeddingCorpus.PRIVATE_ASSET,
        source_type="private_asset_version",
        narrative_sequence_start=None,
        narrative_sequence_end=None,
        binding_permitted=False,
    )
    wrong_index = candidate(36, index_version=8)
    result = retrieve(
        request(),
        candidates=(wrong_novel, unbound, wrong_index),
        lexical=lexical((34, 1.0), (35, 1.0), (36, 1.0)),
        dense=dense_skipped(),
        policy=RetrievalPolicyV1(),
    )
    assert result.hits == ()
    assert result.lexical.scores == ()
    assert result.empty_reason is RetrievalEmptyReason.NO_VISIBLE_CANDIDATES
    assert {item.reason for item in result.diagnostics.filtered} == {
        CandidateFilterReason.WRONG_AUTHORITY_SCOPE,
        CandidateFilterReason.UNBOUND_SOURCE,
        CandidateFilterReason.WRONG_INDEX,
    }


def test_narrative_story_and_per_timeline_cutoffs_are_independent() -> None:
    allowed = candidate(40)
    future_narrative = candidate(
        41,
        narrative_sequence_start=4,
        narrative_sequence_end=4,
    )
    future_story = candidate(
        42,
        story_sequence_start=21,
        story_sequence_end=21,
    )
    beyond_parent_anchor = candidate(
        43,
        timeline_id=uid(9),
        story_sequence_start=6,
        story_sequence_end=6,
    )
    visible, reasons = filter_candidates(
        (allowed, future_narrative, future_story, beyond_parent_anchor), scope()
    )
    assert visible == (allowed,)
    counts = {item.reason: item.count for item in reasons}
    assert counts[CandidateFilterReason.FUTURE_NARRATIVE] == 1
    assert counts[CandidateFilterReason.FUTURE_STORY] == 2


def test_timeline_without_narrower_anchor_inherits_global_story_cutoff() -> None:
    search_scope = scope(
        timeline_limits=(
            TimelineSearchLimit(timeline_id=uid(10), story_sequence_cutoff=None),
        )
    )
    future = candidate(
        44,
        story_sequence_start=21,
        story_sequence_end=21,
    )
    assert filter_candidates((future,), search_scope)[0] == ()


def test_knowledge_visibility_is_fail_closed_but_author_can_see_confirmed_secret() -> None:
    secret = candidate(
        50,
        corpus=EmbeddingCorpus.PLANNING,
        source_type="setting_revision",
        narrative_sequence_start=None,
        narrative_sequence_end=None,
        visibility=CandidateVisibility.KNOWLEDGE,
        required_knowledge_keys=frozenset({"identity:linlan"}),
    )
    reader_scope = scope(
        perspective=RetrievalPerspective.READER,
        knowledge_keys=frozenset(),
    )
    assert filter_candidates((secret,), reader_scope)[0] == ()
    revealed_scope = scope(
        perspective=RetrievalPerspective.READER,
        knowledge_keys=frozenset({"identity:linlan"}),
    )
    assert filter_candidates((secret,), revealed_scope)[0] == (secret,)
    assert filter_candidates((secret,), scope())[0] == (secret,)


def test_versioned_rrf_preserves_both_raw_scores_and_channel_ranks() -> None:
    first = candidate(60)
    second = candidate(61)
    result = retrieve(
        request(),
        candidates=(first, second),
        lexical=lexical((60, 0.8), (61, 0.7)),
        dense=dense_available((61, 0.95), (60, 0.5)),
        policy=RetrievalPolicyV1(adjacent_chunk_radius=0),
    )
    assert result.rrf_version == "rrf/1"
    assert result.mode is RetrievalMode.HYBRID
    by_id = {item.anchor_chunk_id: item for item in result.hits}
    assert by_id[uid(60)].lexical_raw_score == 0.8
    assert by_id[uid(60)].dense_raw_score == 0.5
    assert by_id[uid(60)].lexical_rank == 1
    assert by_id[uid(60)].dense_rank == 2
    assert by_id[uid(60)].fused_score == pytest.approx(1 / 61 + 1 / 62)
    assert by_id[uid(61)].lexical_rank == 2
    assert by_id[uid(61)].dense_rank == 1


def test_source_dedup_quota_and_adjacent_expansion_use_only_visible_chunks() -> None:
    anchor = candidate(
        70,
        source_id=uid(500),
        source_revision_id=uid(501),
        chunk_ordinal=1,
    )
    previous = candidate(
        71,
        source_id=uid(500),
        source_revision_id=uid(501),
        chunk_ordinal=0,
    )
    hidden_next = candidate(
        72,
        source_id=uid(500),
        source_revision_id=uid(501),
        chunk_ordinal=2,
        narrative_sequence_start=4,
        narrative_sequence_end=4,
    )
    other_source = candidate(73)
    policy = RetrievalPolicyV1(
        corpus_quotas=(CorpusQuota(corpus=EmbeddingCorpus.MANUSCRIPT, limit=1),),
        adjacent_chunk_radius=1,
    )
    result = retrieve(
        request(),
        candidates=(anchor, previous, hidden_next, other_source),
        lexical=lexical((70, 0.9), (71, 0.8), (72, 1.0), (73, 0.7)),
        dense=dense_skipped(),
        policy=policy,
    )
    assert len(result.hits) == 1
    assert result.hits[0].anchor_chunk_id == anchor.chunk_id
    assert [item.chunk_id for item in result.hits[0].chunks] == [
        previous.chunk_id,
        anchor.chunk_id,
    ]
    assert result.diagnostics.duplicate_source_count == 1
    assert result.diagnostics.quota_omitted_count == 1


def test_minimum_raw_relevance_can_legally_return_empty_result() -> None:
    item = candidate(80)
    result = retrieve(
        request(),
        candidates=(item,),
        lexical=lexical((80, 0.2)),
        dense=dense_skipped(),
        policy=RetrievalPolicyV1(
            minimum_lexical_raw_score=0.5,
            adjacent_chunk_radius=0,
        ),
    )
    assert result.hits == ()
    assert result.empty_reason is RetrievalEmptyReason.BELOW_MINIMUM_RELEVANCE
    assert result.diagnostics.below_threshold_count == 1


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (
            RetrievalChannelStatus.TIMEOUT,
            RetrievalDegradationReason.DENSE_TIMEOUT,
        ),
        (
            RetrievalChannelStatus.NETWORK_FAILURE,
            RetrievalDegradationReason.DENSE_NETWORK_FAILURE,
        ),
        (
            RetrievalChannelStatus.UNAVAILABLE,
            RetrievalDegradationReason.DENSE_UNAVAILABLE,
        ),
    ],
)
def test_dense_failure_is_expressed_as_lexical_degradation(status, reason) -> None:
    item = candidate(90)
    dense = RetrievalChannelEvidence(
        channel=RetrievalChannel.DENSE,
        status=status,
        latency_ms=8_000 if status is RetrievalChannelStatus.TIMEOUT else 250,
        redacted_error="provider request failed",
    )
    result = retrieve(
        request(),
        candidates=(item,),
        lexical=lexical((90, 0.8)),
        dense=dense,
        policy=RetrievalPolicyV1(),
    )
    assert result.mode is RetrievalMode.LEXICAL_ONLY
    assert result.degraded is True
    assert result.degradation_reason is reason
    assert [hit.anchor_chunk_id for hit in result.hits] == [item.chunk_id]


def test_skipped_dense_channel_is_lexical_only_without_false_failure() -> None:
    item = candidate(91)
    result = retrieve(
        request(),
        candidates=(item,),
        lexical=lexical((91, 0.8)),
        dense=dense_skipped(),
        policy=RetrievalPolicyV1(),
    )
    assert result.mode is RetrievalMode.LEXICAL_ONLY
    assert result.degraded is False
    assert result.degradation_reason is None


def test_v3_expansion_is_bounded_per_hit_and_globally() -> None:
    anchors = tuple(
        candidate(
            1_000 + index,
            source_id=uid(2_000 + index),
            source_revision_id=uid(3_000 + index),
            chunk_ordinal=2,
        )
        for index in range(10)
    )
    neighbors = tuple(
        candidate(
            10_000 + index * 10 + ordinal,
            source_id=anchor.source_id,
            source_revision_id=anchor.source_revision_id,
            chunk_ordinal=ordinal,
        )
        for index, anchor in enumerate(anchors)
        for ordinal in (0, 1, 3, 4)
    )
    policy = writing_retrieval_policy_v3().model_copy(
        update={
            "adjacent_chunk_radius": 5,
            "corpus_quotas": (
                CorpusQuota(corpus=EmbeddingCorpus.MANUSCRIPT, limit=50),
            ),
        }
    )

    result = retrieve(
        request(top_k=50),
        candidates=anchors,
        expansion_candidates=neighbors,
        lexical=RetrievalChannelEvidence(
            channel=RetrievalChannel.LEXICAL,
            status=RetrievalChannelStatus.AVAILABLE,
            scores=tuple(
                RawChannelScore(chunk_id=anchor.chunk_id, score=1.0)
                for anchor in anchors
            ),
        ),
        dense=dense_skipped(),
        policy=policy,
    )

    assert len(result.hits) == 10
    assert all(len(hit.chunks) - 1 <= 2 for hit in result.hits)
    assert sum(len(hit.chunks) - 1 for hit in result.hits) == 20
