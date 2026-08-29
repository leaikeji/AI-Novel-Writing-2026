"""Deterministic scope-first hybrid retrieval pipeline."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

from .contracts import (
    CandidateFilterReason,
    CandidateVisibility,
    FilterCount,
    RawChannelScore,
    RetrievalCandidate,
    RetrievalChannel,
    RetrievalChannelEvidence,
    RetrievalChannelStatus,
    RetrievalDegradationReason,
    RetrievalDiagnostics,
    RetrievalEmptyReason,
    RetrievalEvidenceChunk,
    RetrievalMode,
    RetrievalPerspective,
    RetrievalPolicyV1,
    SearchScope,
    SemanticRetrievalHitV2,
    SemanticSearchRequestV2,
    SemanticSearchResultV2,
)


@dataclass(frozen=True, slots=True)
class _Ranked:
    candidate: RetrievalCandidate
    lexical_raw: float | None
    dense_raw: float | None
    lexical_rank: int | None
    dense_rank: int | None
    fused_score: float


def _timeline_story_cutoff(
    scope: SearchScope, timeline_id: UUID | None
) -> int | None:
    if timeline_id is None:
        return scope.story_sequence_cutoff
    limit = next(
        (item for item in scope.timeline_limits if item.timeline_id == timeline_id),
        None,
    )
    if limit is None:
        return None
    return (
        limit.story_sequence_cutoff
        if limit.story_sequence_cutoff is not None
        else scope.story_sequence_cutoff
    )


def candidate_filter_reason(
    candidate: RetrievalCandidate, scope: SearchScope
) -> CandidateFilterReason | None:
    """Return the first fail-closed reason without inspecting any score."""

    if (
        candidate.owner_id != scope.owner_id
        or candidate.workspace_id != scope.workspace_id
        or candidate.novel_id != scope.novel_id
    ):
        return CandidateFilterReason.WRONG_AUTHORITY_SCOPE
    if candidate.corpus not in scope.corpora:
        return CandidateFilterReason.WRONG_CORPUS
    if not candidate.source_current:
        return CandidateFilterReason.STALE_SOURCE
    if not candidate.binding_permitted:
        return CandidateFilterReason.UNBOUND_SOURCE
    if (
        candidate.generation_id != scope.generation_id
        or candidate.index_version != scope.index_version
    ):
        return CandidateFilterReason.WRONG_INDEX

    reachable_ids = {item.timeline_id for item in scope.timeline_limits}
    if candidate.timeline_id is not None and candidate.timeline_id not in reachable_ids:
        return CandidateFilterReason.UNREACHABLE_TIMELINE

    narrative_cutoff = scope.narrative_sequence_cutoff
    if narrative_cutoff is not None:
        narrative_end = (
            candidate.narrative_sequence_end
            if candidate.narrative_sequence_end is not None
            else candidate.narrative_sequence_start
        )
        if narrative_end is not None and narrative_end > narrative_cutoff:
            return CandidateFilterReason.FUTURE_NARRATIVE

    story_cutoff = _timeline_story_cutoff(scope, candidate.timeline_id)
    if story_cutoff is not None:
        story_end = (
            candidate.story_sequence_end
            if candidate.story_sequence_end is not None
            else candidate.story_sequence_start
        )
        if story_end is not None and story_end > story_cutoff:
            return CandidateFilterReason.FUTURE_STORY

    if scope.perspective is not RetrievalPerspective.AUTHOR:
        if candidate.visibility is CandidateVisibility.AUTHOR_ONLY:
            return CandidateFilterReason.HIDDEN_KNOWLEDGE
        if (
            candidate.visibility is CandidateVisibility.KNOWLEDGE
            and not candidate.required_knowledge_keys.issubset(scope.knowledge_keys)
        ):
            return CandidateFilterReason.HIDDEN_KNOWLEDGE
    return None


def filter_candidates(
    candidates: Iterable[RetrievalCandidate], scope: SearchScope
) -> tuple[tuple[RetrievalCandidate, ...], tuple[FilterCount, ...]]:
    """Apply every authority/time/knowledge gate before ranking."""

    visible: list[RetrievalCandidate] = []
    reasons: Counter[CandidateFilterReason] = Counter()
    seen_chunk_ids: set[UUID] = set()
    seen_source_ordinals: set[tuple[object, ...]] = set()
    for candidate in candidates:
        if candidate.chunk_id in seen_chunk_ids:
            raise ValueError("candidate chunk IDs must be unique")
        seen_chunk_ids.add(candidate.chunk_id)
        source_ordinal = (*candidate.source_revision_identity, candidate.chunk_ordinal)
        if source_ordinal in seen_source_ordinals:
            raise ValueError("candidate source ordinals must be unique")
        seen_source_ordinals.add(source_ordinal)
        reason = candidate_filter_reason(candidate, scope)
        if reason is None:
            visible.append(candidate)
        else:
            reasons[reason] += 1
    counts = tuple(
        FilterCount(reason=reason, count=reasons[reason])
        for reason in CandidateFilterReason
        if reasons[reason]
    )
    return tuple(visible), counts


def _score_map(scores: Sequence[RawChannelScore]) -> dict[UUID, float]:
    return {item.chunk_id: item.score for item in scores}


def _visible_channel_evidence(
    evidence: RetrievalChannelEvidence,
    visible_ids: set[UUID],
) -> RetrievalChannelEvidence:
    """Remove filtered and unknown chunk identifiers from returned evidence."""

    return RetrievalChannelEvidence(
        channel=evidence.channel,
        status=evidence.status,
        scores=tuple(item for item in evidence.scores if item.chunk_id in visible_ids),
        provider_request_id=evidence.provider_request_id,
        token_count=evidence.token_count,
        latency_ms=evidence.latency_ms,
        redacted_error=evidence.redacted_error,
    )


def _rank_channel(
    candidates: Sequence[RetrievalCandidate],
    raw_scores: Mapping[UUID, float],
    *,
    minimum_raw_score: float,
) -> tuple[dict[UUID, int], dict[UUID, float]]:
    """Rank within each corpus after filtering and absolute-score gating."""

    by_corpus: dict[object, list[tuple[RetrievalCandidate, float]]] = defaultdict(list)
    for candidate in candidates:
        score = raw_scores.get(candidate.chunk_id)
        if score is not None and score >= minimum_raw_score:
            by_corpus[candidate.corpus].append((candidate, score))
    ranks: dict[UUID, int] = {}
    accepted_scores: dict[UUID, float] = {}
    for corpus in sorted(by_corpus, key=lambda item: item.value):
        ordered = sorted(
            by_corpus[corpus],
            key=lambda item: (-item[1], str(item[0].chunk_id)),
        )
        for rank, (candidate, score) in enumerate(ordered, start=1):
            ranks[candidate.chunk_id] = rank
            accepted_scores[candidate.chunk_id] = score
    return ranks, accepted_scores


def _rank_candidates(
    candidates: Sequence[RetrievalCandidate],
    *,
    lexical: RetrievalChannelEvidence,
    dense: RetrievalChannelEvidence,
    policy: RetrievalPolicyV1,
) -> tuple[_Ranked, ...]:
    lexical_ranks, lexical_scores = _rank_channel(
        candidates,
        _score_map(lexical.scores),
        minimum_raw_score=policy.minimum_lexical_raw_score,
    )
    if dense.status is RetrievalChannelStatus.AVAILABLE:
        dense_ranks, dense_scores = _rank_channel(
            candidates,
            _score_map(dense.scores),
            minimum_raw_score=policy.minimum_dense_raw_score,
        )
    else:
        dense_ranks, dense_scores = {}, {}

    by_id = {candidate.chunk_id: candidate for candidate in candidates}
    ranked: list[_Ranked] = []
    for chunk_id in set(lexical_ranks) | set(dense_ranks):
        lexical_rank = lexical_ranks.get(chunk_id)
        dense_rank = dense_ranks.get(chunk_id)
        fused = 0.0
        if lexical_rank is not None:
            fused += policy.lexical_weight / (
                policy.rrf_rank_constant + lexical_rank
            )
        if dense_rank is not None:
            fused += policy.dense_weight / (policy.rrf_rank_constant + dense_rank)
        ranked.append(
            _Ranked(
                candidate=by_id[chunk_id],
                lexical_raw=lexical_scores.get(chunk_id),
                dense_raw=dense_scores.get(chunk_id),
                lexical_rank=lexical_rank,
                dense_rank=dense_rank,
                fused_score=fused,
            )
        )
    return tuple(
        sorted(
            ranked,
            key=lambda item: (
                -item.fused_score,
                item.candidate.corpus.value,
                str(item.candidate.chunk_id),
            ),
        )
    )


def _evidence_chunk(candidate: RetrievalCandidate) -> RetrievalEvidenceChunk:
    return RetrievalEvidenceChunk(
        chunk_id=candidate.chunk_id,
        chunk_ordinal=candidate.chunk_ordinal,
        text=candidate.text,
        timeline_id=candidate.timeline_id,
        narrative_sequence_start=candidate.narrative_sequence_start,
        narrative_sequence_end=candidate.narrative_sequence_end,
        story_sequence_start=candidate.story_sequence_start,
        story_sequence_end=candidate.story_sequence_end,
    )


def _expand_adjacent(
    anchor: RetrievalCandidate,
    *,
    visible_candidates: Sequence[RetrievalCandidate],
    radius: int,
) -> tuple[RetrievalEvidenceChunk, ...]:
    neighbors = (
        item
        for item in visible_candidates
        if item.source_revision_identity == anchor.source_revision_identity
        and abs(item.chunk_ordinal - anchor.chunk_ordinal) <= radius
    )
    return tuple(
        _evidence_chunk(item)
        for item in sorted(neighbors, key=lambda item: (item.chunk_ordinal, str(item.chunk_id)))
    )


def _degradation(
    dense: RetrievalChannelEvidence,
) -> tuple[bool, RetrievalDegradationReason | None]:
    reason_by_status = {
        RetrievalChannelStatus.TIMEOUT: RetrievalDegradationReason.DENSE_TIMEOUT,
        RetrievalChannelStatus.NETWORK_FAILURE: (
            RetrievalDegradationReason.DENSE_NETWORK_FAILURE
        ),
        RetrievalChannelStatus.UNAVAILABLE: RetrievalDegradationReason.DENSE_UNAVAILABLE,
    }
    reason = reason_by_status.get(dense.status)
    return reason is not None, reason


def retrieve(
    request: SemanticSearchRequestV2,
    *,
    candidates: Iterable[RetrievalCandidate],
    lexical: RetrievalChannelEvidence,
    dense: RetrievalChannelEvidence,
    policy: RetrievalPolicyV1,
) -> SemanticSearchResultV2:
    """Filter, gate raw relevance, fuse, deduplicate, quota, then expand."""

    if lexical.channel is not RetrievalChannel.LEXICAL:
        raise ValueError("lexical evidence has the wrong channel")
    if dense.channel is not RetrievalChannel.DENSE:
        raise ValueError("dense evidence has the wrong channel")

    all_candidates = tuple(candidates)
    visible, filtered = filter_candidates(all_candidates, request.scope)
    visible_ids = {item.chunk_id for item in visible}
    visible_lexical = _visible_channel_evidence(lexical, visible_ids)
    visible_dense = _visible_channel_evidence(dense, visible_ids)
    ranked = _rank_candidates(
        visible,
        lexical=visible_lexical,
        dense=visible_dense,
        policy=policy,
    )
    raw_candidate_ids = visible_ids.intersection(
        {item.chunk_id for item in visible_lexical.scores}
        | (
            {item.chunk_id for item in visible_dense.scores}
            if visible_dense.status is RetrievalChannelStatus.AVAILABLE
            else set()
        )
    )
    ranked_ids = {item.candidate.chunk_id for item in ranked}
    above_threshold = tuple(
        item for item in ranked if item.fused_score >= policy.minimum_fused_score
    )
    below_threshold_count = (
        len(raw_candidate_ids - ranked_ids) + len(ranked) - len(above_threshold)
    )

    top_k = min(request.top_k, policy.max_results)
    corpus_counts: Counter[object] = Counter()
    seen_sources: set[tuple[object, ...]] = set()
    accepted_hits: list[SemanticRetrievalHitV2] = []
    duplicate_source_count = 0
    quota_omitted_count = 0
    for item in above_threshold:
        source_identity = item.candidate.source_identity
        if source_identity in seen_sources:
            duplicate_source_count += 1
            continue
        seen_sources.add(source_identity)
        quota = policy.quota_for(item.candidate.corpus)
        if corpus_counts[item.candidate.corpus] >= quota:
            quota_omitted_count += 1
            continue
        channels = tuple(
            channel
            for channel, rank in (
                (RetrievalChannel.LEXICAL, item.lexical_rank),
                (RetrievalChannel.DENSE, item.dense_rank),
            )
            if rank is not None
        )
        accepted_hits.append(
            SemanticRetrievalHitV2(
                corpus=item.candidate.corpus,
                source_type=item.candidate.source_type,
                source_id=item.candidate.source_id,
                source_revision_id=item.candidate.source_revision_id,
                anchor_chunk_id=item.candidate.chunk_id,
                chunks=_expand_adjacent(
                    item.candidate,
                    visible_candidates=visible,
                    radius=policy.adjacent_chunk_radius,
                ),
                lexical_raw_score=item.lexical_raw,
                dense_raw_score=item.dense_raw,
                lexical_rank=item.lexical_rank,
                dense_rank=item.dense_rank,
                fused_score=item.fused_score,
                channels=channels,
            )
        )
        corpus_counts[item.candidate.corpus] += 1
    hits = accepted_hits[:top_k]
    top_k_omitted_count = len(accepted_hits) - len(hits)

    if hits:
        empty_reason = None
    elif not visible:
        empty_reason = RetrievalEmptyReason.NO_VISIBLE_CANDIDATES
    elif not ranked and not raw_candidate_ids:
        empty_reason = RetrievalEmptyReason.NO_CHANNEL_MATCHES
    else:
        empty_reason = RetrievalEmptyReason.BELOW_MINIMUM_RELEVANCE

    degraded, degradation_reason = _degradation(visible_dense)
    mode = (
        RetrievalMode.HYBRID
        if visible_dense.status is RetrievalChannelStatus.AVAILABLE
        else RetrievalMode.LEXICAL_ONLY
    )
    return SemanticSearchResultV2(
        purpose=request.purpose,
        generation_id=request.scope.generation_id,
        index_version=request.scope.index_version,
        policy_version=policy.policy_version,
        rrf_version=policy.rrf_version,
        mode=mode,
        hits=tuple(hits),
        lexical=visible_lexical,
        dense=visible_dense,
        degraded=degraded,
        degradation_reason=degradation_reason,
        empty_reason=empty_reason,
        diagnostics=RetrievalDiagnostics(
            candidate_count=len(all_candidates),
            visible_candidate_count=len(visible),
            scored_candidate_count=len(ranked),
            below_threshold_count=below_threshold_count,
            duplicate_source_count=duplicate_source_count,
            quota_omitted_count=quota_omitted_count,
            top_k_omitted_count=top_k_omitted_count,
            filtered=filtered,
        ),
    )
