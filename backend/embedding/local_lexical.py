"""Read-only lexical fallback over current novel authority.

The semantic index is derived and can be absent, stale, or temporarily
unavailable.  This module rebuilds a small, deterministic lexical candidate
set directly from current authoritative revisions without persisting chunks or
calling an embedding provider.  It deliberately accepts explicit timeline
limits instead of inferring cross-line inheritance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from math import isfinite
from types import MappingProxyType
from typing import Mapping, Sequence
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from ..creative_data_models import (
    NovelAssetBinding,
    NovelOutlineHead,
    NovelOutlineRevision,
    NovelSettingHead,
    NovelSettingRevision,
    PrivateAssetVersion,
    RevisionTimelineMappingHead,
    RevisionTimelineMappingSegment,
    StoryTimeline,
)
from ..models import Document, DocumentRevision, DocumentWorkingCopy, Novel, Volume
from ..volume_chapter_titles import embedding_chapter_title
from .chunking import (
    V1_CHUNKER_VERSION,
    V1_RENDERER_VERSION,
    V1SourceInput,
    chunk_rendered_source,
    render_structured_setting,
    render_v1_source,
)
from .contracts import (
    EmbeddingCorpus,
    SemanticMatchChannel,
    SemanticSearchHit,
    SemanticSourceState,
)
from .retrieval.contracts import (
    CandidateVisibility,
    RawChannelScore,
    RetrievalCandidate,
    RetrievalChannel,
    RetrievalChannelEvidence,
    RetrievalChannelStatus,
    RetrievalPerspective,
)


LOCAL_LEXICAL_POLICY_VERSION = "authority-local-lexical/1"
LOCAL_AUTHORITY_SOURCE_CAP = 80
LOCAL_AUTHORITY_CHUNK_CAP = 80
LOCAL_AUTHORITY_FINAL_HIT_CAP = 10
_SEARCHABLE_CORPORA = frozenset(
    {
        EmbeddingCorpus.MANUSCRIPT,
        EmbeddingCorpus.PLANNING,
        EmbeddingCorpus.PRIVATE_ASSET,
    }
)
_INDEXABLE_ASSET_POLICIES = frozenset({"required", "preferred", "context_only"})
_WORD_RE = re.compile(r"[\w]+", re.UNICODE)
_NON_WORD_RE = re.compile(r"[^\w]+", re.UNICODE)
_V1_RENDERER_HEADER_LABELS = frozenset(
    {
        "语料",
        "标题",
        "使用策略",
        "分块版本",
    }
)


def author_visible_v1_snippet(value: str) -> str:
    """Remove only a proven V1 renderer header from an author-facing snippet."""

    header, separator, body = value.partition("\n\n")
    if not separator:
        return value
    lines = tuple(line.strip() for line in header.splitlines() if line.strip())
    labels: list[str] = []
    for line in lines:
        delimiter = "：" if "：" in line else ":" if ":" in line else None
        if delimiter is None:
            return value
        label = line.split(delimiter, 1)[0].strip()
        if label not in _V1_RENDERER_HEADER_LABELS:
            return value
        labels.append(label)
    if "语料" not in labels or "标题" not in labels:
        return value
    return body.lstrip("\n")


class LocalLexicalScopeError(ValueError):
    """A deterministic authority boundary could not be established."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class LocalTimelineLimit:
    timeline_id: UUID
    story_sequence_cutoff: int | None = None

    def __post_init__(self) -> None:
        if self.story_sequence_cutoff is not None and self.story_sequence_cutoff < 0:
            raise ValueError("story_sequence_cutoff must be non-negative")


@dataclass(frozen=True, slots=True)
class LocalLexicalSearchRequest:
    owner_id: UUID
    workspace_id: UUID
    novel_id: UUID
    query: str
    corpora: frozenset[EmbeddingCorpus]
    top_k: int = 10
    target_timeline_id: UUID | None = None
    narrative_sequence_cutoff: int | None = None
    story_sequence_cutoff: int | None = None
    timeline_limits: tuple[LocalTimelineLimit, ...] = ()
    perspective: RetrievalPerspective = RetrievalPerspective.AUTHOR
    minimum_score: float = 0.01

    def __post_init__(self) -> None:
        if not self.query.strip():
            raise ValueError("query must not be blank")
        if not self.corpora:
            raise ValueError("corpora must not be empty")
        if not self.corpora <= _SEARCHABLE_CORPORA:
            raise ValueError("local authority fallback only supports V1 corpora")
        if not 1 <= self.top_k <= 50:
            raise ValueError("top_k must be between 1 and 50")
        if self.narrative_sequence_cutoff is not None and self.narrative_sequence_cutoff < 0:
            raise ValueError("narrative_sequence_cutoff must be non-negative")
        if self.story_sequence_cutoff is not None and self.story_sequence_cutoff < 0:
            raise ValueError("story_sequence_cutoff must be non-negative")
        if not isfinite(self.minimum_score) or self.minimum_score < 0:
            raise ValueError("minimum_score must be finite and non-negative")
        timeline_ids = tuple(item.timeline_id for item in self.timeline_limits)
        if len(timeline_ids) != len(set(timeline_ids)):
            raise ValueError("timeline_limits must not contain duplicates")
        if (
            self.target_timeline_id is not None
            and timeline_ids
            and self.target_timeline_id not in set(timeline_ids)
        ):
            raise ValueError("target timeline must be included in timeline_limits")


@dataclass(frozen=True, slots=True)
class LocalLexicalHit:
    corpus: EmbeddingCorpus
    source_type: str
    source_id: UUID
    source_revision_id: UUID
    chunk_id: UUID
    chunk_ordinal: int
    text: str
    lexical_raw_score: float
    timeline_id: UUID | None = None
    narrative_sequence_start: int | None = None
    narrative_sequence_end: int | None = None
    story_sequence_start: int | None = None
    story_sequence_end: int | None = None
    visibility: CandidateVisibility = CandidateVisibility.PUBLIC
    usage_policy: str | None = None


@dataclass(frozen=True, slots=True)
class LocalLexicalDiagnostics:
    authority_source_count: int
    candidate_chunk_count: int
    scored_chunk_count: int
    below_threshold_count: int
    top_k_omitted_count: int
    unmapped_revision_count: int
    filtered_future_narrative_count: int
    filtered_timeline_count: int
    filtered_story_count: int
    filtered_prohibited_asset_count: int
    filtered_visibility_count: int

    @property
    def omission_summary(self) -> tuple[dict[str, int], ...]:
        values = (
            ("below_minimum_relevance", self.below_threshold_count),
            ("top_k", self.top_k_omitted_count),
            ("unmapped_revision", self.unmapped_revision_count),
            ("future_narrative", self.filtered_future_narrative_count),
            ("timeline", self.filtered_timeline_count),
            ("future_story", self.filtered_story_count),
            ("prohibited_asset", self.filtered_prohibited_asset_count),
            ("hidden_visibility", self.filtered_visibility_count),
        )
        return tuple({"reason": reason, "count": count} for reason, count in values if count)


@dataclass(frozen=True, slots=True)
class LocalLexicalResult:
    hits: tuple[LocalLexicalHit, ...]
    diagnostics: LocalLexicalDiagnostics
    policy_version: str = LOCAL_LEXICAL_POLICY_VERSION
    mode: str = "lexical_only"
    degraded_reason: str = "dense_unavailable"
    provider_request_id: None = None
    token_count: None = None

    def as_semantic_search_hits(self) -> tuple[SemanticSearchHit, ...]:
        """Return public ``semantic-search/2`` hit resources."""

        source_states = {
            "chapter_revision": SemanticSourceState.CURRENT_REVISION,
            "private_asset_version": SemanticSourceState.BOUND_ASSET_VERSION,
        }
        return tuple(
            SemanticSearchHit(
                corpus=item.corpus,
                source_type=item.source_type,
                source_id=item.source_id,
                source_revision_id=item.source_revision_id,
                chunk_id=item.chunk_id,
                source_state=source_states.get(
                    item.source_type,
                    SemanticSourceState.CURRENT_ENTITY_REVISION,
                ),
                timeline_id=item.timeline_id,
                narrative_sequence_start=item.narrative_sequence_start,
                narrative_sequence_end=item.narrative_sequence_end,
                story_sequence_start=item.story_sequence_start,
                story_sequence_end=item.story_sequence_end,
                snippet=author_visible_v1_snippet(item.text),
                channels=(SemanticMatchChannel.LEXICAL,),
                lexical_score=item.lexical_raw_score,
                fused_score=item.lexical_raw_score,
            )
            for item in self.hits
        )

    def as_v2_inputs(
        self,
        *,
        owner_id: UUID,
        workspace_id: UUID,
        novel_id: UUID,
        generation_id: UUID,
        index_version: int,
    ) -> tuple[tuple[RetrievalCandidate, ...], RetrievalChannelEvidence]:
        """Adapt fallback hits to the existing pure retrieval V2 engine."""

        candidates = tuple(
            RetrievalCandidate(
                chunk_id=item.chunk_id,
                owner_id=owner_id,
                workspace_id=workspace_id,
                novel_id=novel_id,
                generation_id=generation_id,
                index_version=index_version,
                corpus=item.corpus,
                source_type=item.source_type,
                source_id=item.source_id,
                source_revision_id=item.source_revision_id,
                chunk_ordinal=item.chunk_ordinal,
                text=item.text,
                source_current=True,
                binding_permitted=True,
                timeline_id=item.timeline_id,
                narrative_sequence_start=item.narrative_sequence_start,
                narrative_sequence_end=item.narrative_sequence_end,
                story_sequence_start=item.story_sequence_start,
                story_sequence_end=item.story_sequence_end,
                visibility=item.visibility,
            )
            for item in self.hits
        )
        evidence = RetrievalChannelEvidence(
            channel=RetrievalChannel.LEXICAL,
            status=RetrievalChannelStatus.AVAILABLE,
            scores=tuple(
                RawChannelScore(chunk_id=item.chunk_id, score=item.lexical_raw_score)
                for item in self.hits
            ),
            latency_ms=0,
        )
        return candidates, evidence


@dataclass(frozen=True, slots=True)
class _AuthoritySource:
    corpus: EmbeddingCorpus
    source_type: str
    source_id: UUID
    source_revision_id: UUID
    title: str
    content: str
    timeline_id: UUID | None = None
    narrative_sequence: int | None = None
    story_sequence: int | None = None
    visibility: CandidateVisibility = CandidateVisibility.PUBLIC
    usage_policy: str | None = None
    locator_key: str = "head"


@dataclass(slots=True)
class _MutableDiagnostics:
    unmapped_revision_count: int = 0
    filtered_future_narrative_count: int = 0
    filtered_timeline_count: int = 0
    filtered_story_count: int = 0
    filtered_prohibited_asset_count: int = 0
    filtered_visibility_count: int = 0


def _timeline_scope(
    timelines: Sequence[StoryTimeline], request: LocalLexicalSearchRequest
) -> tuple[UUID, Mapping[UUID, int | None]]:
    active = {
        item.id: item
        for item in timelines
        if item.novel_id == request.novel_id and item.lifecycle_state == "active"
    }
    requested = request.target_timeline_id
    if requested is None:
        if len(active) != 1:
            raise LocalLexicalScopeError(
                "timeline_required",
                "an explicit target is required unless exactly one timeline is active",
            )
        requested = next(iter(active))
    if requested not in active:
        raise LocalLexicalScopeError(
            "timeline_not_found", "target timeline is not active in this novel"
        )
    raw_limits = request.timeline_limits or (
        LocalTimelineLimit(
            timeline_id=requested,
            story_sequence_cutoff=request.story_sequence_cutoff,
        ),
    )
    limits: dict[UUID, int | None] = {}
    for item in raw_limits:
        if item.timeline_id not in active:
            raise LocalLexicalScopeError(
                "timeline_scope_invalid", "a timeline limit is outside the active novel scope"
            )
        cutoff = item.story_sequence_cutoff
        if cutoff is None and item.timeline_id == requested:
            cutoff = request.story_sequence_cutoff
        limits[item.timeline_id] = cutoff
    if requested not in limits:
        raise LocalLexicalScopeError(
            "timeline_scope_invalid", "target timeline is absent from the explicit limits"
        )
    return requested, MappingProxyType(limits)


def _canonical_document_order(novel_id: UUID):
    return (
        select(
            Document.id.label("document_id"),
            func.row_number()
            .over(
                order_by=(
                    case((Document.volume_id.is_(None), 1), else_=0),
                    Volume.position,
                    Document.position,
                    Document.id,
                )
            )
            .label("narrative_sequence"),
        )
        .outerjoin(
            Volume,
            and_(
                Volume.id == Document.volume_id,
                Volume.novel_id == Document.novel_id,
            ),
        )
        .where(Document.novel_id == novel_id, Document.kind == "chapter")
        .subquery()
    )


def _bounded_manuscript_source_ids(
    session: Session,
    *,
    request: LocalLexicalSearchRequest,
    timelines: Sequence[StoryTimeline],
    target_timeline_id: UUID,
    timeline_limits: Mapping[UUID, int | None],
) -> tuple[UUID, ...]:
    """Select relevant current authority IDs before any chapter text hydration."""

    canonical = _canonical_document_order(request.novel_id)
    base_conditions: list[object] = [
        Document.novel_id == request.novel_id,
        Document.kind == "chapter",
        DocumentRevision.content_text != "",
    ]
    if request.narrative_sequence_cutoff is not None:
        base_conditions.append(
            canonical.c.narrative_sequence <= request.narrative_sequence_cutoff
        )
    if len(timelines) == 1:
        cutoff = timeline_limits.get(target_timeline_id)
        if cutoff is not None:
            base_conditions.append(canonical.c.narrative_sequence <= cutoff)
        score = func.similarity(
            func.concat(Document.title, " ", DocumentRevision.content_text),
            request.query,
        )
        statement = (
            select(canonical.c.document_id)
            .select_from(canonical)
            .join(Document, Document.id == canonical.c.document_id)
            .join(
                DocumentWorkingCopy,
                DocumentWorkingCopy.document_id == Document.id,
            )
            .join(
                DocumentRevision,
                DocumentRevision.id == DocumentWorkingCopy.base_revision_id,
            )
            .where(*base_conditions, score > request.minimum_score)
            .order_by(score.desc(), canonical.c.document_id)
            .limit(LOCAL_AUTHORITY_SOURCE_CAP)
        )
        return tuple(session.scalars(statement))[:LOCAL_AUTHORITY_SOURCE_CAP]

    excerpt = func.substr(
        DocumentRevision.content_text,
        RevisionTimelineMappingSegment.source_start + 1,
        RevisionTimelineMappingSegment.source_end
        - RevisionTimelineMappingSegment.source_start,
    )
    score = func.similarity(func.concat(Document.title, " ", excerpt), request.query)
    story_scope: list[object] = []
    for timeline_id, cutoff in timeline_limits.items():
        item: object = RevisionTimelineMappingSegment.timeline_id == timeline_id
        if cutoff is not None:
            item = and_(
                item,
                RevisionTimelineMappingSegment.story_sequence.is_not(None),
                RevisionTimelineMappingSegment.story_sequence <= cutoff,
            )
        story_scope.append(item)
    best_score = func.max(score)
    statement = (
        select(canonical.c.document_id)
        .select_from(canonical)
        .join(Document, Document.id == canonical.c.document_id)
        .join(
            DocumentWorkingCopy,
            DocumentWorkingCopy.document_id == Document.id,
        )
        .join(
            DocumentRevision,
            DocumentRevision.id == DocumentWorkingCopy.base_revision_id,
        )
        .join(
            RevisionTimelineMappingHead,
            and_(
                RevisionTimelineMappingHead.revision_id == DocumentRevision.id,
                RevisionTimelineMappingHead.document_id == Document.id,
                RevisionTimelineMappingHead.novel_id == request.novel_id,
                RevisionTimelineMappingHead.source_content_hash
                == DocumentRevision.content_hash,
            ),
        )
        .join(
            RevisionTimelineMappingSegment,
            and_(
                RevisionTimelineMappingSegment.mapping_revision_id
                == RevisionTimelineMappingHead.current_mapping_revision_id,
                RevisionTimelineMappingSegment.novel_id == request.novel_id,
            ),
        )
        .where(
            *base_conditions,
            or_(*story_scope),
            RevisionTimelineMappingSegment.source_start >= 0,
            RevisionTimelineMappingSegment.source_end
            > RevisionTimelineMappingSegment.source_start,
            RevisionTimelineMappingSegment.source_end
            <= func.char_length(DocumentRevision.content_text),
            score > request.minimum_score,
        )
        .group_by(canonical.c.document_id)
        .order_by(best_score.desc(), canonical.c.document_id)
        .limit(LOCAL_AUTHORITY_SOURCE_CAP)
    )
    return tuple(session.scalars(statement))[:LOCAL_AUTHORITY_SOURCE_CAP]


def _load_manuscript(
    session: Session,
    *,
    request: LocalLexicalSearchRequest,
    timelines: Sequence[StoryTimeline],
    target_timeline_id: UUID,
    timeline_limits: Mapping[UUID, int | None],
    diagnostics: _MutableDiagnostics,
) -> list[_AuthoritySource]:
    source_ids = _bounded_manuscript_source_ids(
        session,
        request=request,
        timelines=timelines,
        target_timeline_id=target_timeline_id,
        timeline_limits=timeline_limits,
    )
    if not source_ids:
        return []
    canonical_order = _canonical_document_order(request.novel_id)
    narrative_by_document_id = {
        document_id: int(sequence)
        for document_id, sequence in session.execute(
            select(
                canonical_order.c.document_id,
                canonical_order.c.narrative_sequence,
            ).where(canonical_order.c.document_id.in_(source_ids))
        ).all()
    }
    rows = session.execute(
        select(Document, DocumentRevision)
        .join(DocumentWorkingCopy, DocumentWorkingCopy.document_id == Document.id)
        .join(
            DocumentRevision,
            DocumentRevision.id == DocumentWorkingCopy.base_revision_id,
        )
        .outerjoin(
            Volume,
            and_(
                Volume.id == Document.volume_id,
                Volume.novel_id == Document.novel_id,
            ),
        )
        .where(
            Document.novel_id == request.novel_id,
            Document.kind == "chapter",
            Document.id.in_(source_ids),
        )
        .order_by(
            case((Document.volume_id.is_(None), 1), else_=0),
            Volume.position,
            Document.position,
            Document.id,
        )
        .limit(LOCAL_AUTHORITY_SOURCE_CAP)
    ).all()
    single_timeline = len(timelines) == 1
    heads_by_revision_id: dict[UUID, RevisionTimelineMappingHead] = {}
    segments_by_mapping_id: dict[UUID, list[RevisionTimelineMappingSegment]] = {}
    if not single_timeline:
        revision_ids = tuple(revision.id for _document, revision in rows)
        heads = tuple(
            session.scalars(
                select(RevisionTimelineMappingHead).where(
                    RevisionTimelineMappingHead.revision_id.in_(revision_ids),
                    RevisionTimelineMappingHead.novel_id == request.novel_id,
                )
            )
        )
        heads_by_revision_id = {head.revision_id: head for head in heads}
        mapping_revision_ids = tuple(
            sorted(
                {head.current_mapping_revision_id for head in heads},
                key=str,
            )
        )
        if mapping_revision_ids:
            for segment in session.scalars(
                select(RevisionTimelineMappingSegment)
                .where(
                    RevisionTimelineMappingSegment.mapping_revision_id.in_(
                        mapping_revision_ids
                    ),
                    RevisionTimelineMappingSegment.novel_id == request.novel_id,
                )
                .order_by(
                    RevisionTimelineMappingSegment.mapping_revision_id,
                    RevisionTimelineMappingSegment.ordinal,
                )
            ):
                segments_by_mapping_id.setdefault(
                    segment.mapping_revision_id, []
                ).append(segment)
    sources: list[_AuthoritySource] = []
    selected_source_ids = set(source_ids)
    for document, revision in sorted(
        rows,
        key=lambda item: narrative_by_document_id.get(item[0].id, 2**63 - 1),
    ):
        narrative_sequence = narrative_by_document_id.get(document.id)
        if document.id not in selected_source_ids or narrative_sequence is None:
            continue
        if document.novel_id != request.novel_id or revision.document_id != document.id:
            continue
        if not revision.content_text.strip():
            continue
        if (
            request.narrative_sequence_cutoff is not None
            and narrative_sequence > request.narrative_sequence_cutoff
        ):
            diagnostics.filtered_future_narrative_count += 1
            continue
        if single_timeline:
            story_cutoff = timeline_limits.get(target_timeline_id)
            if story_cutoff is not None and narrative_sequence > story_cutoff:
                diagnostics.filtered_story_count += 1
                continue
            sources.append(
                _AuthoritySource(
                    corpus=EmbeddingCorpus.MANUSCRIPT,
                    source_type="chapter_revision",
                    source_id=document.id,
                    source_revision_id=revision.id,
                    title=embedding_chapter_title(document.title),
                    content=revision.content_text,
                    timeline_id=target_timeline_id,
                    narrative_sequence=narrative_sequence,
                    story_sequence=narrative_sequence,
                    locator_key="single-timeline-identity/1",
                )
            )
            continue

        head = heads_by_revision_id.get(revision.id)
        if (
            head is None
            or head.novel_id != request.novel_id
            or head.document_id != document.id
            or head.source_content_hash != revision.content_hash
        ):
            diagnostics.unmapped_revision_count += 1
            continue
        segments = tuple(
            segments_by_mapping_id.get(head.current_mapping_revision_id, ())
        )
        accepted_segment = False
        for segment in segments:
            if segment.timeline_id not in timeline_limits:
                diagnostics.filtered_timeline_count += 1
                continue
            cutoff = timeline_limits[segment.timeline_id]
            if cutoff is not None and (
                segment.story_sequence is None or segment.story_sequence > cutoff
            ):
                diagnostics.filtered_story_count += 1
                continue
            if not (
                segment.novel_id == request.novel_id
                and segment.mapping_revision_id == head.current_mapping_revision_id
                and 0 <= segment.source_start < segment.source_end <= len(revision.content_text)
            ):
                # Malformed or stale mapping evidence is never repaired by guessing.
                continue
            excerpt = revision.content_text[segment.source_start : segment.source_end]
            if not excerpt.strip():
                continue
            accepted_segment = True
            sources.append(
                _AuthoritySource(
                    corpus=EmbeddingCorpus.MANUSCRIPT,
                    source_type="chapter_revision",
                    source_id=document.id,
                    source_revision_id=revision.id,
                    title=(
                        f"{embedding_chapter_title(document.title)}"
                        f"·片段{segment.ordinal + 1}"
                    ),
                    content=excerpt,
                    timeline_id=segment.timeline_id,
                    narrative_sequence=narrative_sequence,
                    story_sequence=segment.story_sequence,
                    locator_key=(
                        f"{head.current_mapping_revision_id}:"
                        f"{segment.source_start}:{segment.source_end}"
                    ),
                )
            )
        if not segments:
            diagnostics.unmapped_revision_count += 1
        elif not accepted_segment and all(
            segment.timeline_id in timeline_limits for segment in segments
        ):
            # A current head with no valid excerpts is effectively unmapped.
            diagnostics.unmapped_revision_count += 1
    return sources


def _load_planning(
    session: Session, *, request: LocalLexicalSearchRequest
) -> list[_AuthoritySource]:
    sources: list[_AuthoritySource] = []
    outline_head = session.get(NovelOutlineHead, request.novel_id)
    if outline_head is not None:
        revision = session.get(NovelOutlineRevision, outline_head.current_revision_id)
        if revision is not None and revision.novel_id == request.novel_id:
            content = "\n\n".join(
                value
                for value in (
                    revision.background_text,
                    revision.plot_text,
                    revision.highlight_text,
                )
                if value.strip()
            )
            if content:
                sources.append(
                    _AuthoritySource(
                        corpus=EmbeddingCorpus.PLANNING,
                        source_type="outline_revision",
                        source_id=request.novel_id,
                        source_revision_id=revision.id,
                        title="正式大纲",
                        content=content,
                        visibility=CandidateVisibility.AUTHOR_ONLY,
                    )
                )
    setting_head = session.get(NovelSettingHead, request.novel_id)
    if setting_head is not None:
        revision = session.get(NovelSettingRevision, setting_head.current_revision_id)
        if revision is not None and revision.novel_id == request.novel_id:
            try:
                content = render_structured_setting(revision.settings_json)
            except ValueError:
                content = ""
            if content:
                sources.append(
                    _AuthoritySource(
                        corpus=EmbeddingCorpus.PLANNING,
                        source_type="setting_revision",
                        source_id=request.novel_id,
                        source_revision_id=revision.id,
                        title="正式故事设定",
                        content=content,
                        visibility=CandidateVisibility.AUTHOR_ONLY,
                    )
                )
    return sources


def _load_private_assets(
    session: Session,
    *,
    request: LocalLexicalSearchRequest,
    diagnostics: _MutableDiagnostics,
) -> list[_AuthoritySource]:
    similarity = func.similarity(
        func.concat(PrivateAssetVersion.title, " ", PrivateAssetVersion.content),
        request.query,
    )
    rows = session.execute(
        select(NovelAssetBinding, PrivateAssetVersion)
        .join(
            PrivateAssetVersion,
            PrivateAssetVersion.id == NovelAssetBinding.asset_version_id,
        )
        .where(
            NovelAssetBinding.novel_id == request.novel_id,
            NovelAssetBinding.lifecycle_state == "active",
            NovelAssetBinding.usage_policy != "prohibited",
            similarity > request.minimum_score,
        )
        .order_by(
            similarity.desc(),
            NovelAssetBinding.position,
            NovelAssetBinding.id,
        )
        .limit(LOCAL_AUTHORITY_SOURCE_CAP)
    ).all()
    sources: list[_AuthoritySource] = []
    for binding, version in rows:
        if binding.usage_policy not in _INDEXABLE_ASSET_POLICIES:
            if binding.usage_policy == "prohibited":
                diagnostics.filtered_prohibited_asset_count += 1
            continue
        if (
            binding.novel_id != request.novel_id
            or binding.lifecycle_state != "active"
            or binding.asset_id != version.asset_id
            or binding.asset_version_id != version.id
        ):
            continue
        if not version.content.strip():
            continue
        sources.append(
            _AuthoritySource(
                corpus=EmbeddingCorpus.PRIVATE_ASSET,
                source_type="private_asset_version",
                source_id=binding.asset_id,
                source_revision_id=version.id,
                title=version.title,
                content=version.content,
                visibility=CandidateVisibility.AUTHOR_ONLY,
                usage_policy=binding.usage_policy,
                locator_key=str(binding.id),
            )
        )
    return sources


def _compact(value: str) -> str:
    return _NON_WORD_RE.sub("", value.casefold())


def _ngrams(value: str, size: int) -> frozenset[str]:
    if len(value) < size:
        return frozenset({value}) if value else frozenset()
    return frozenset(value[index : index + size] for index in range(len(value) - size + 1))


def _lexical_score(query: str, text: str) -> float:
    compact_query = _compact(query)
    compact_text = _compact(text)
    if not compact_query or not compact_text:
        return 0.0
    if compact_query in compact_text:
        return 1.0
    size = 2 if len(compact_query) < 12 else 3
    query_grams = _ngrams(compact_query, size)
    text_grams = _ngrams(compact_text, size)
    gram_recall = (
        len(query_grams & text_grams) / len(query_grams) if query_grams else 0.0
    )
    query_words = {
        item.casefold()
        for item in _WORD_RE.findall(query)
        if len(item.strip()) >= 2
    }
    word_recall = (
        sum(1 for item in query_words if item in text.casefold()) / len(query_words)
        if query_words
        else 0.0
    )
    return min(1.0, max(gram_recall, word_recall))


def _rank_sources(
    *,
    request: LocalLexicalSearchRequest,
    sources: Sequence[_AuthoritySource],
    diagnostics: _MutableDiagnostics,
) -> LocalLexicalResult:
    scored: list[LocalLexicalHit] = []
    candidate_chunk_count = 0
    below_threshold_count = 0
    exhausted = False
    for source in sources[:LOCAL_AUTHORITY_SOURCE_CAP]:
        if (
            source.visibility is CandidateVisibility.AUTHOR_ONLY
            and request.perspective is not RetrievalPerspective.AUTHOR
        ):
            diagnostics.filtered_visibility_count += 1
            continue
        rendered = render_v1_source(
            V1SourceInput(
                corpus=source.corpus.value,
                source_type=source.source_type,
                source_entity_id=source.source_id,
                source_revision_id=source.source_revision_id,
                title=source.title,
                content=source.content,
                usage_policy=source.usage_policy,
            ),
            renderer_version=V1_RENDERER_VERSION,
        )
        for chunk in chunk_rendered_source(rendered, chunker_version=V1_CHUNKER_VERSION):
            if candidate_chunk_count >= LOCAL_AUTHORITY_CHUNK_CAP:
                exhausted = True
                break
            candidate_chunk_count += 1
            score = _lexical_score(request.query, chunk.text)
            if score <= request.minimum_score:
                below_threshold_count += 1
                continue
            chunk_id = uuid5(
                NAMESPACE_URL,
                "|".join(
                    (
                        LOCAL_LEXICAL_POLICY_VERSION,
                        str(request.novel_id),
                        source.source_type,
                        str(source.source_revision_id),
                        str(source.timeline_id or "global"),
                        source.locator_key,
                        str(chunk.index),
                        chunk.content_hash,
                    )
                ),
            )
            scored.append(
                LocalLexicalHit(
                    corpus=source.corpus,
                    source_type=source.source_type,
                    source_id=source.source_id,
                    source_revision_id=source.source_revision_id,
                    chunk_id=chunk_id,
                    chunk_ordinal=chunk.index,
                    text=chunk.text,
                    lexical_raw_score=score,
                    timeline_id=source.timeline_id,
                    narrative_sequence_start=source.narrative_sequence,
                    narrative_sequence_end=source.narrative_sequence,
                    story_sequence_start=source.story_sequence,
                    story_sequence_end=source.story_sequence,
                    visibility=source.visibility,
                    usage_policy=source.usage_policy,
                )
            )
        if exhausted:
            break
    scored.sort(
        key=lambda item: (
            -item.lexical_raw_score,
            item.corpus.value,
            item.source_type,
            str(item.source_id),
            item.chunk_ordinal,
        )
    )
    selected = tuple(scored[: min(request.top_k, LOCAL_AUTHORITY_FINAL_HIT_CAP)])
    return LocalLexicalResult(
        hits=selected,
        diagnostics=LocalLexicalDiagnostics(
            authority_source_count=len(sources),
            candidate_chunk_count=candidate_chunk_count,
            scored_chunk_count=len(scored),
            below_threshold_count=below_threshold_count,
            top_k_omitted_count=max(0, len(scored) - len(selected)),
            unmapped_revision_count=diagnostics.unmapped_revision_count,
            filtered_future_narrative_count=(
                diagnostics.filtered_future_narrative_count
            ),
            filtered_timeline_count=diagnostics.filtered_timeline_count,
            filtered_story_count=diagnostics.filtered_story_count,
            filtered_prohibited_asset_count=(
                diagnostics.filtered_prohibited_asset_count
            ),
            filtered_visibility_count=diagnostics.filtered_visibility_count,
        ),
    )


def search_local_authority(
    session: Session, request: LocalLexicalSearchRequest
) -> LocalLexicalResult:
    """Search current authority with no writes and no provider interaction.

    The caller owns retrieval-purpose policy such as subtracting the target
    chapter from a generation cutoff.  This function enforces the cutoff it is
    given exactly.
    """

    with session.no_autoflush:
        novel = session.scalar(
            select(Novel).where(
                Novel.id == request.novel_id,
                Novel.owner_id == request.owner_id,
                Novel.workspace_id == request.workspace_id,
            )
        )
        if (
            novel is None
            or novel.id != request.novel_id
            or novel.owner_id != request.owner_id
            or novel.workspace_id != request.workspace_id
        ):
            raise LocalLexicalScopeError(
                "novel_scope_not_found", "novel is outside the requested local scope"
            )
        timelines = tuple(
            session.scalars(
                select(StoryTimeline)
                .where(
                    StoryTimeline.novel_id == request.novel_id,
                    StoryTimeline.lifecycle_state == "active",
                )
                .order_by(StoryTimeline.position, StoryTimeline.id)
            )
        )
        target_timeline_id, timeline_limits = _timeline_scope(timelines, request)
        diagnostics = _MutableDiagnostics()
        sources: list[_AuthoritySource] = []
        if EmbeddingCorpus.MANUSCRIPT in request.corpora:
            sources.extend(
                _load_manuscript(
                    session,
                    request=request,
                    timelines=timelines,
                    target_timeline_id=target_timeline_id,
                    timeline_limits=timeline_limits,
                    diagnostics=diagnostics,
                )
            )
        if EmbeddingCorpus.PLANNING in request.corpora:
            sources.extend(_load_planning(session, request=request))
        if EmbeddingCorpus.PRIVATE_ASSET in request.corpora:
            sources.extend(
                _load_private_assets(
                    session,
                    request=request,
                    diagnostics=diagnostics,
                )
            )
        return _rank_sources(request=request, sources=sources, diagnostics=diagnostics)
