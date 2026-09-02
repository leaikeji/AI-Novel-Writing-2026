"""Bounded SQL candidate retrieval for ``writing-retrieval/3``.

Provider calls deliberately stay outside this module.  The API adapter supplies
an already-produced query vector (or a closed dense-channel status), and this
service keeps authority/current filters inside both capped candidate queries.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Sequence
from uuid import UUID

from sqlalchemy import String, and_, cast, exists, func, literal, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from ..creative_data_models import (
    EmbeddingGeneration,
    EmbeddingGenerationNovel,
    NovelAssetBinding,
    NovelOutlineHead,
    NovelSettingHead,
    SemanticChunk,
    SemanticEmbedding,
    SemanticSource,
)
from ..models import Document, DocumentWorkingCopy, StoryFact
from .contracts import EmbeddingCorpus
from .retrieval import (
    ADJACENT_NEIGHBORS_GLOBAL_CAP,
    ADJACENT_NEIGHBORS_PER_HIT_CAP,
    DENSE_CANDIDATE_CAP,
    FINAL_HIT_CAP,
    LEXICAL_CANDIDATE_CAP,
    WRITING_RETRIEVAL_POLICY_VERSION,
    CandidateVisibility,
    RawChannelScore,
    RetrievalCandidate,
    RetrievalChannel,
    RetrievalChannelEvidence,
    RetrievalChannelStatus,
    RetrievalPerspective,
    RetrievalPolicyV1,
    SemanticSearchRequestV2,
    SemanticSearchResultV2,
    retrieve,
    writing_retrieval_policy_v3,
)


@dataclass(frozen=True, slots=True)
class DenseQueryInput:
    """Provider evidence supplied after the caller's existing provider boundary."""

    status: RetrievalChannelStatus
    vector: tuple[float, ...] | None = None
    provider_request_id: str | None = None
    token_count: int | None = None
    latency_ms: int | None = None
    redacted_error: str | None = None

    def __post_init__(self) -> None:
        if self.status is RetrievalChannelStatus.AVAILABLE:
            if not self.vector:
                raise ValueError("an available dense channel requires a query vector")
        elif self.vector is not None:
            raise ValueError("a closed dense channel must not carry a query vector")


@dataclass(frozen=True, slots=True)
class BoundedRetrievalExecution:
    result: SemanticSearchResultV2
    candidates_by_id: Mapping[UUID, RetrievalCandidate]
    dense_candidate_count: int
    lexical_candidate_count: int
    enriched_candidate_count: int
    adjacent_candidate_count: int


@dataclass(frozen=True, slots=True)
class _HydratedCandidate:
    candidate: RetrievalCandidate
    semantic_source_id: UUID


def _current_authority_predicate(
    *,
    effective_story_fact_ids: frozenset[UUID],
) -> object:
    chapter_is_current = exists(
        select(literal(1))
        .select_from(DocumentWorkingCopy)
        .join(Document, Document.id == DocumentWorkingCopy.document_id)
        .where(
            DocumentWorkingCopy.document_id == SemanticSource.source_entity_id,
            DocumentWorkingCopy.base_revision_id == SemanticSource.source_revision_id,
            Document.novel_id == SemanticSource.novel_id,
            Document.kind == "chapter",
        )
    )
    outline_is_current = exists(
        select(literal(1)).select_from(NovelOutlineHead).where(
            NovelOutlineHead.novel_id == SemanticSource.novel_id,
            NovelOutlineHead.current_revision_id == SemanticSource.source_revision_id,
            SemanticSource.source_entity_id == SemanticSource.novel_id,
        )
    )
    setting_is_current = exists(
        select(literal(1)).select_from(NovelSettingHead).where(
            NovelSettingHead.novel_id == SemanticSource.novel_id,
            NovelSettingHead.current_revision_id == SemanticSource.source_revision_id,
            SemanticSource.source_entity_id == SemanticSource.novel_id,
        )
    )
    asset_is_current = exists(
        select(literal(1)).select_from(NovelAssetBinding).where(
            NovelAssetBinding.novel_id == SemanticSource.novel_id,
            NovelAssetBinding.asset_id == SemanticSource.source_entity_id,
            NovelAssetBinding.asset_version_id == SemanticSource.source_revision_id,
            NovelAssetBinding.lifecycle_state == "active",
            NovelAssetBinding.usage_policy != "prohibited",
        )
    )
    story_fact_is_current = (
        exists(
            select(literal(1)).select_from(StoryFact).where(
                StoryFact.id == SemanticSource.source_entity_id,
                StoryFact.novel_id == SemanticSource.novel_id,
                StoryFact.source_revision_id.is_not_distinct_from(
                    SemanticSource.source_revision_id
                ),
                StoryFact.id.in_(effective_story_fact_ids),
            )
        )
        if effective_story_fact_ids
        else literal(False)
    )
    return or_(
        and_(SemanticSource.source_type == "chapter_revision", chapter_is_current),
        and_(SemanticSource.source_type == "outline_revision", outline_is_current),
        and_(SemanticSource.source_type == "setting_revision", setting_is_current),
        and_(SemanticSource.source_type == "private_asset_version", asset_is_current),
        and_(SemanticSource.source_type == "story_fact", story_fact_is_current),
    )


def _visibility_predicate(request: SemanticSearchRequestV2) -> object:
    if request.scope.perspective is RetrievalPerspective.AUTHOR:
        return literal(True)
    visibility = func.coalesce(
        cast(SemanticSource.visibility_json["visibility"].as_string(), String),
        cast(SemanticSource.visibility_json["visibility_key"].as_string(), String),
        "public",
    )
    author_values = ("author", "author_only", "secret")
    knowledge_values = ("knowledge", "knowledge_scoped")
    public = visibility.not_in((*author_values, *knowledge_values))
    required_keys = func.coalesce(
        SemanticSource.visibility_json["required_knowledge_keys"],
        cast([], JSONB),
    )
    knowledge = and_(
        visibility.in_(knowledge_values),
        required_keys.op("<@")(cast(sorted(request.scope.knowledge_keys), JSONB)),
    )
    return or_(public, knowledge)


def _eligible_source_predicates(
    request: SemanticSearchRequestV2,
    *,
    effective_story_fact_ids: frozenset[UUID],
) -> tuple[object, ...]:
    scope = request.scope
    attached_active_generation = exists(
        select(literal(1))
        .select_from(EmbeddingGenerationNovel)
        .join(
            EmbeddingGeneration,
            EmbeddingGeneration.id == EmbeddingGenerationNovel.generation_id,
        )
        .where(
            EmbeddingGenerationNovel.generation_id == SemanticSource.generation_id,
            EmbeddingGenerationNovel.novel_id == SemanticSource.novel_id,
            EmbeddingGenerationNovel.owner_id == scope.owner_id,
            EmbeddingGenerationNovel.workspace_id == scope.workspace_id,
            EmbeddingGenerationNovel.index_version == scope.index_version,
            EmbeddingGeneration.id == scope.generation_id,
            EmbeddingGeneration.owner_id == scope.owner_id,
            EmbeddingGeneration.workspace_id == scope.workspace_id,
            EmbeddingGeneration.state == "active",
        )
    )
    timeline_ids = tuple(item.timeline_id for item in scope.timeline_limits)
    timeline_scope = or_(
        SemanticSource.timeline_id.is_(None),
        SemanticSource.timeline_id.in_(timeline_ids),
    )
    predicates: list[object] = [
        SemanticSource.generation_id == scope.generation_id,
        SemanticSource.novel_id == scope.novel_id,
        SemanticSource.corpus.in_(tuple(item.value for item in scope.corpora)),
        SemanticSource.status == "current",
        attached_active_generation,
        _current_authority_predicate(
            effective_story_fact_ids=effective_story_fact_ids
        ),
        timeline_scope,
        _visibility_predicate(request),
    ]
    if scope.narrative_sequence_cutoff is not None:
        predicates.append(
            or_(
                SemanticSource.narrative_sequence_start.is_(None),
                func.coalesce(
                    SemanticSource.narrative_sequence_end,
                    SemanticSource.narrative_sequence_start,
                )
                <= scope.narrative_sequence_cutoff,
            )
        )
    story_scope: list[object] = [SemanticSource.timeline_id.is_(None)]
    for timeline_limit in scope.timeline_limits:
        item: object = SemanticSource.timeline_id == timeline_limit.timeline_id
        cutoff = (
            timeline_limit.story_sequence_cutoff
            if timeline_limit.story_sequence_cutoff is not None
            else scope.story_sequence_cutoff
        )
        if cutoff is not None:
            item = and_(
                item,
                SemanticSource.story_sequence_start.is_not(None),
                func.coalesce(
                    SemanticSource.story_sequence_end,
                    SemanticSource.story_sequence_start,
                )
                <= cutoff,
            )
        story_scope.append(item)
    predicates.append(or_(*story_scope))
    return tuple(predicates)


def _visibility(source: SemanticSource) -> tuple[CandidateVisibility, frozenset[str]]:
    payload = source.visibility_json or {}
    raw_visibility = str(
        payload.get("visibility") or payload.get("visibility_key") or "public"
    )
    if raw_visibility in {"author", "author_only", "secret"}:
        return CandidateVisibility.AUTHOR_ONLY, frozenset()
    if raw_visibility in {"knowledge", "knowledge_scoped"}:
        keys = frozenset(
            str(value) for value in payload.get("required_knowledge_keys", ()) if str(value).strip()
        )
        return CandidateVisibility.KNOWLEDGE, keys
    return CandidateVisibility.PUBLIC, frozenset()


def _hydrate_candidate(
    *,
    source: SemanticSource,
    chunk: SemanticChunk,
    request: SemanticSearchRequestV2,
) -> _HydratedCandidate | None:
    try:
        visibility, required_keys = _visibility(source)
        candidate = RetrievalCandidate(
            chunk_id=chunk.id,
            owner_id=request.scope.owner_id,
            workspace_id=request.scope.workspace_id,
            novel_id=source.novel_id,
            generation_id=source.generation_id,
            index_version=request.scope.index_version,
            corpus=EmbeddingCorpus(source.corpus),
            source_type=source.source_type,
            source_id=source.source_entity_id,
            source_revision_id=source.source_revision_id,
            chunk_ordinal=chunk.chunk_index,
            text=chunk.content_text,
            source_current=True,
            binding_permitted=True,
            timeline_id=source.timeline_id,
            narrative_sequence_start=source.narrative_sequence_start,
            narrative_sequence_end=source.narrative_sequence_end,
            story_sequence_start=source.story_sequence_start,
            story_sequence_end=source.story_sequence_end,
            visibility=visibility,
            required_knowledge_keys=required_keys,
        )
    except (TypeError, ValueError):
        return None
    return _HydratedCandidate(candidate=candidate, semantic_source_id=source.id)


def _channel_rows(
    session: Session,
    *,
    request: SemanticSearchRequestV2,
    dense_input: DenseQueryInput,
    predicates: Sequence[object],
    policy: RetrievalPolicyV1,
) -> tuple[list[tuple[UUID, float]], list[tuple[UUID, float]]]:
    dense_rows: list[tuple[UUID, float]] = []
    if dense_input.status is RetrievalChannelStatus.AVAILABLE:
        distance = SemanticEmbedding.embedding.cosine_distance(list(dense_input.vector or ()))
        dense_rows = [
            (chunk_id, 1.0 - float(distance_value))
            for chunk_id, distance_value in session.execute(
                select(SemanticChunk.id, distance.label("dense_distance"))
                .select_from(SemanticSource)
                .join(SemanticChunk, SemanticChunk.source_id == SemanticSource.id)
                .join(
                    SemanticEmbedding,
                    and_(
                        SemanticEmbedding.chunk_id == SemanticChunk.id,
                        SemanticEmbedding.generation_id == request.scope.generation_id,
                    ),
                )
                .where(*predicates, distance <= 2.0)
                .order_by(
                    distance,
                    SemanticSource.source_entity_id,
                    SemanticChunk.chunk_index,
                    SemanticChunk.id,
                )
                .limit(DENSE_CANDIDATE_CAP)
            ).all()[:DENSE_CANDIDATE_CAP]
        ]
    similarity = func.similarity(SemanticChunk.content_text, request.query)
    lexical_rows = [
        (chunk_id, float(score))
        for chunk_id, score in session.execute(
            select(SemanticChunk.id, similarity.label("lexical_score"))
            .select_from(SemanticSource)
            .join(SemanticChunk, SemanticChunk.source_id == SemanticSource.id)
            .where(*predicates, similarity > policy.minimum_lexical_raw_score)
            .order_by(
                similarity.desc(),
                SemanticSource.source_entity_id,
                SemanticChunk.chunk_index,
                SemanticChunk.id,
            )
            .limit(LEXICAL_CANDIDATE_CAP)
        ).all()[:LEXICAL_CANDIDATE_CAP]
    ]
    return dense_rows, lexical_rows


def _enrich_candidates(
    session: Session,
    *,
    request: SemanticSearchRequestV2,
    chunk_ids: frozenset[UUID],
    predicates: Sequence[object],
) -> tuple[_HydratedCandidate, ...]:
    if not chunk_ids:
        return ()
    rows = session.execute(
        select(SemanticSource, SemanticChunk)
        .select_from(SemanticSource)
        .join(SemanticChunk, SemanticChunk.source_id == SemanticSource.id)
        .where(*predicates, SemanticChunk.id.in_(chunk_ids))
        .order_by(
            SemanticSource.source_entity_id,
            SemanticChunk.chunk_index,
            SemanticChunk.id,
        )
    ).all()
    hydrated = (
        _hydrate_candidate(source=source, chunk=chunk, request=request)
        for source, chunk in rows
        if chunk.id in chunk_ids
    )
    return tuple(item for item in hydrated if item is not None)


def _load_adjacent_candidates(
    session: Session,
    *,
    request: SemanticSearchRequestV2,
    anchors: Sequence[RetrievalCandidate],
    hydrated_by_id: Mapping[UUID, _HydratedCandidate],
    predicates: Sequence[object],
) -> tuple[_HydratedCandidate, ...]:
    scopes: list[object] = []
    anchor_ids: set[UUID] = set()
    for anchor in anchors:
        hydrated = hydrated_by_id.get(anchor.chunk_id)
        if hydrated is None:
            continue
        anchor_ids.add(anchor.chunk_id)
        scopes.append(
            and_(
                SemanticChunk.source_id == hydrated.semantic_source_id,
                SemanticChunk.chunk_index >= max(0, anchor.chunk_ordinal - 1),
                SemanticChunk.chunk_index <= anchor.chunk_ordinal + 1,
            )
        )
    if not scopes:
        return ()
    rows = session.execute(
        select(SemanticSource, SemanticChunk)
        .select_from(SemanticSource)
        .join(SemanticChunk, SemanticChunk.source_id == SemanticSource.id)
        .where(
            *predicates,
            or_(*scopes),
            SemanticChunk.id.not_in(anchor_ids),
        )
        .order_by(
            SemanticSource.source_entity_id,
            SemanticChunk.chunk_index,
            SemanticChunk.id,
        )
        .limit(ADJACENT_NEIGHBORS_GLOBAL_CAP)
    ).all()
    hydrated = (
        _hydrate_candidate(source=source, chunk=chunk, request=request)
        for source, chunk in rows
    )
    return tuple(item for item in hydrated if item is not None)


def execute_bounded_retrieval(
    session: Session,
    *,
    request: SemanticSearchRequestV2,
    dense_input: DenseQueryInput,
    effective_story_fact_ids: frozenset[UUID] = frozenset(),
    policy: RetrievalPolicyV1 | None = None,
) -> BoundedRetrievalExecution:
    """Query capped channels, batch-hydrate, then load only final-hit neighbors."""

    base_policy = policy or writing_retrieval_policy_v3()
    effective_policy = base_policy.model_copy(
        update={
            "policy_version": WRITING_RETRIEVAL_POLICY_VERSION,
            "minimum_lexical_raw_score": max(
                base_policy.minimum_lexical_raw_score, 0.01
            ),
            "adjacent_chunk_radius": min(base_policy.adjacent_chunk_radius, 1),
            "max_adjacent_neighbors_per_hit": min(
                base_policy.max_adjacent_neighbors_per_hit,
                ADJACENT_NEIGHBORS_PER_HIT_CAP,
            ),
            "max_adjacent_neighbors_total": min(
                base_policy.max_adjacent_neighbors_total,
                ADJACENT_NEIGHBORS_GLOBAL_CAP,
            ),
            "max_results": min(base_policy.max_results, FINAL_HIT_CAP),
        }
    )
    predicates = _eligible_source_predicates(
        request,
        effective_story_fact_ids=effective_story_fact_ids,
    )
    dense_rows, lexical_rows = _channel_rows(
        session,
        request=request,
        dense_input=dense_input,
        predicates=predicates,
        policy=effective_policy,
    )
    chunk_ids = frozenset(
        chunk_id for chunk_id, _ in (*dense_rows, *lexical_rows)
    )
    hydrated = _enrich_candidates(
        session,
        request=request,
        chunk_ids=chunk_ids,
        predicates=predicates,
    )
    hydrated_by_id = {item.candidate.chunk_id: item for item in hydrated}
    valid_ids = set(hydrated_by_id)
    lexical = RetrievalChannelEvidence(
        channel=RetrievalChannel.LEXICAL,
        status=RetrievalChannelStatus.AVAILABLE,
        scores=tuple(
            RawChannelScore(chunk_id=chunk_id, score=score)
            for chunk_id, score in lexical_rows
            if chunk_id in valid_ids
        ),
        latency_ms=0,
    )
    dense = RetrievalChannelEvidence(
        channel=RetrievalChannel.DENSE,
        status=dense_input.status,
        scores=tuple(
            RawChannelScore(chunk_id=chunk_id, score=score)
            for chunk_id, score in dense_rows
            if chunk_id in valid_ids
        ),
        provider_request_id=dense_input.provider_request_id,
        token_count=dense_input.token_count,
        latency_ms=dense_input.latency_ms,
        redacted_error=dense_input.redacted_error,
    )
    candidates = tuple(item.candidate for item in hydrated)
    anchor_result = retrieve(
        request,
        candidates=candidates,
        lexical=lexical,
        dense=dense,
        policy=effective_policy.model_copy(update={"adjacent_chunk_radius": 0}),
    )
    anchor_candidates = tuple(
        hydrated_by_id[hit.anchor_chunk_id].candidate
        for hit in anchor_result.hits
        if hit.anchor_chunk_id in hydrated_by_id
    )
    adjacent = _load_adjacent_candidates(
        session,
        request=request,
        anchors=anchor_candidates,
        hydrated_by_id=hydrated_by_id,
        predicates=predicates,
    )
    result = retrieve(
        request,
        candidates=candidates,
        lexical=lexical,
        dense=dense,
        policy=effective_policy,
        expansion_candidates=tuple(item.candidate for item in adjacent),
    )
    all_candidates = {
        item.candidate.chunk_id: item.candidate for item in (*hydrated, *adjacent)
    }
    return BoundedRetrievalExecution(
        result=result,
        candidates_by_id=MappingProxyType(all_candidates),
        dense_candidate_count=len(dense_rows),
        lexical_candidate_count=len(lexical_rows),
        enriched_candidate_count=len(hydrated),
        adjacent_candidate_count=len(adjacent),
    )
