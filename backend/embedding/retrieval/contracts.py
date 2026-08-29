"""Pure contracts for scope-first semantic retrieval V2.

This module has no ORM, HTTP, provider SDK, or network behavior.  Callers adapt
database rows and provider responses into these immutable contracts.
"""

from __future__ import annotations

from enum import Enum
from math import isfinite
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..contracts import EmbeddingCorpus


SEMANTIC_RETRIEVAL_SCHEMA_VERSION = "semantic-retrieval/2"
DEFAULT_QUERY_POLICY_VERSION = "retrieval-policy/1"
RRF_VERSION = "rrf/1"


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class RetrievalPurpose(str, Enum):
    CHAPTER_BODY = "chapter_body"
    CHAPTER_OUTLINE = "chapter_outline"
    CHAPTER_REVIEW = "chapter_review"
    SELECTION_REWRITE = "selection_rewrite"
    EXPAND = "expand"
    DIALOGUE = "dialogue"
    REVIEW = "review"
    CUSTOM = "custom"


class RetrievalPerspective(str, Enum):
    AUTHOR = "author"
    READER = "reader"
    CHARACTER_INSTANCE = "character_instance"


class CandidateVisibility(str, Enum):
    PUBLIC = "public"
    AUTHOR_ONLY = "author_only"
    KNOWLEDGE = "knowledge"


class RetrievalChannel(str, Enum):
    LEXICAL = "lexical"
    DENSE = "dense"


class RetrievalChannelStatus(str, Enum):
    AVAILABLE = "available"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"
    NETWORK_FAILURE = "network_failure"
    UNAVAILABLE = "unavailable"


class RetrievalDegradationReason(str, Enum):
    DENSE_TIMEOUT = "dense_timeout"
    DENSE_NETWORK_FAILURE = "dense_network_failure"
    DENSE_UNAVAILABLE = "dense_unavailable"


class RetrievalMode(str, Enum):
    LEXICAL_ONLY = "lexical_only"
    HYBRID = "hybrid"


class RetrievalEmptyReason(str, Enum):
    NO_VISIBLE_CANDIDATES = "no_visible_candidates"
    NO_CHANNEL_MATCHES = "no_channel_matches"
    BELOW_MINIMUM_RELEVANCE = "below_minimum_relevance"


class CandidateFilterReason(str, Enum):
    WRONG_AUTHORITY_SCOPE = "wrong_authority_scope"
    WRONG_CORPUS = "wrong_corpus"
    STALE_SOURCE = "stale_source"
    UNBOUND_SOURCE = "unbound_source"
    WRONG_INDEX = "wrong_index"
    UNREACHABLE_TIMELINE = "unreachable_timeline"
    FUTURE_NARRATIVE = "future_narrative"
    FUTURE_STORY = "future_story"
    HIDDEN_KNOWLEDGE = "hidden_knowledge"


class TimelineSearchLimit(_StrictModel):
    """One reachable line and its deterministic inherited story cutoff."""

    timeline_id: UUID
    story_sequence_cutoff: int | None = Field(default=None, ge=0)


class SearchScope(_StrictModel):
    owner_id: UUID
    workspace_id: UUID
    novel_id: UUID
    generation_id: UUID
    index_version: int = Field(ge=1)
    corpora: frozenset[EmbeddingCorpus]
    target_timeline_id: UUID | None = None
    narrative_sequence_cutoff: int | None = Field(default=None, ge=0)
    story_sequence_cutoff: int | None = Field(default=None, ge=0)
    timeline_limits: tuple[TimelineSearchLimit, ...] = ()
    perspective: RetrievalPerspective = RetrievalPerspective.AUTHOR
    observer_character_instance_id: UUID | None = None
    knowledge_keys: frozenset[str] = frozenset()

    @field_validator("corpora")
    @classmethod
    def validate_corpora(
        cls, value: frozenset[EmbeddingCorpus]
    ) -> frozenset[EmbeddingCorpus]:
        if not value:
            raise ValueError("corpora must not be empty")
        return value

    @field_validator("knowledge_keys")
    @classmethod
    def validate_knowledge_keys(cls, value: frozenset[str]) -> frozenset[str]:
        if any(not item or len(item) > 240 for item in value):
            raise ValueError("knowledge keys must contain 1-240 characters")
        return value

    @model_validator(mode="after")
    def validate_timeline_and_perspective(self) -> "SearchScope":
        timeline_ids = tuple(item.timeline_id for item in self.timeline_limits)
        if len(timeline_ids) != len(set(timeline_ids)):
            raise ValueError("timeline_limits must not contain duplicate timelines")
        if (
            self.target_timeline_id is not None
            and self.target_timeline_id not in set(timeline_ids)
        ):
            raise ValueError("target timeline must be present in timeline_limits")
        if self.story_sequence_cutoff is not None:
            if any(
                item.story_sequence_cutoff is not None
                and item.story_sequence_cutoff > self.story_sequence_cutoff
                for item in self.timeline_limits
            ):
                raise ValueError("timeline cutoff cannot exceed global story cutoff")
        if self.perspective is RetrievalPerspective.CHARACTER_INSTANCE:
            if self.observer_character_instance_id is None:
                raise ValueError("character perspective requires an observer instance")
        elif self.observer_character_instance_id is not None:
            raise ValueError("observer instance is valid only for character perspective")
        return self


class SemanticSearchRequestV2(_StrictModel):
    schema_version: Literal[SEMANTIC_RETRIEVAL_SCHEMA_VERSION] = (
        SEMANTIC_RETRIEVAL_SCHEMA_VERSION
    )
    query: str = Field(min_length=1, max_length=8_000)
    purpose: RetrievalPurpose
    use_novel_context: bool = False
    scope: SearchScope
    top_k: int = Field(default=10, ge=1, le=50)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        if not value:
            raise ValueError("query must not be blank")
        return value

    @model_validator(mode="after")
    def validate_custom_opt_in(self) -> "SemanticSearchRequestV2":
        if self.purpose is RetrievalPurpose.CUSTOM and not self.use_novel_context:
            raise ValueError("custom retrieval requires explicit use_novel_context")
        return self


class CorpusQuota(_StrictModel):
    corpus: EmbeddingCorpus
    limit: int = Field(ge=0, le=50)


def _default_quotas() -> tuple[CorpusQuota, ...]:
    return tuple(CorpusQuota(corpus=corpus, limit=4) for corpus in EmbeddingCorpus)


class RetrievalPolicyV1(_StrictModel):
    policy_version: str = Field(
        default=DEFAULT_QUERY_POLICY_VERSION,
        min_length=1,
        max_length=120,
        pattern=r"^[a-z0-9][a-z0-9._/-]*$",
    )
    rrf_version: Literal[RRF_VERSION] = RRF_VERSION
    rrf_rank_constant: int = Field(default=60, ge=1, le=10_000)
    lexical_weight: float = Field(default=1.0, gt=0)
    dense_weight: float = Field(default=1.0, gt=0)
    minimum_lexical_raw_score: float = 0.0
    minimum_dense_raw_score: float = -1.0
    minimum_fused_score: float = Field(default=0.0, ge=0)
    corpus_quotas: tuple[CorpusQuota, ...] = Field(default_factory=_default_quotas)
    adjacent_chunk_radius: int = Field(default=1, ge=0, le=5)
    max_results: int = Field(default=50, ge=1, le=50)
    dense_timeout_seconds: Literal[8] = 8

    @field_validator(
        "lexical_weight",
        "dense_weight",
        "minimum_lexical_raw_score",
        "minimum_dense_raw_score",
        "minimum_fused_score",
    )
    @classmethod
    def validate_finite_numbers(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("retrieval policy numbers must be finite")
        return value

    @model_validator(mode="after")
    def validate_unique_quotas(self) -> "RetrievalPolicyV1":
        corpora = tuple(item.corpus for item in self.corpus_quotas)
        if len(corpora) != len(set(corpora)):
            raise ValueError("corpus_quotas must not contain duplicates")
        return self

    def quota_for(self, corpus: EmbeddingCorpus) -> int:
        return next(
            (item.limit for item in self.corpus_quotas if item.corpus is corpus),
            0,
        )


class RetrievalCandidate(_StrictModel):
    chunk_id: UUID
    owner_id: UUID
    workspace_id: UUID
    novel_id: UUID
    generation_id: UUID
    index_version: int = Field(ge=1)
    corpus: EmbeddingCorpus
    source_type: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    source_id: UUID
    source_revision_id: UUID | None = None
    chunk_ordinal: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=32_000)
    source_current: bool = True
    binding_permitted: bool = True
    timeline_id: UUID | None = None
    narrative_sequence_start: int | None = Field(default=None, ge=0)
    narrative_sequence_end: int | None = Field(default=None, ge=0)
    story_sequence_start: int | None = Field(default=None, ge=0)
    story_sequence_end: int | None = Field(default=None, ge=0)
    visibility: CandidateVisibility = CandidateVisibility.PUBLIC
    required_knowledge_keys: frozenset[str] = frozenset()

    @field_validator("required_knowledge_keys")
    @classmethod
    def validate_required_keys(cls, value: frozenset[str]) -> frozenset[str]:
        if any(not item or len(item) > 240 for item in value):
            raise ValueError("required knowledge keys must contain 1-240 characters")
        return value

    @model_validator(mode="after")
    def validate_ranges_and_visibility(self) -> "RetrievalCandidate":
        for start, end, label in (
            (
                self.narrative_sequence_start,
                self.narrative_sequence_end,
                "narrative",
            ),
            (self.story_sequence_start, self.story_sequence_end, "story"),
        ):
            if end is not None and start is None:
                raise ValueError(f"{label} end requires a start")
            if start is not None and end is not None and end < start:
                raise ValueError(f"{label} range is reversed")
        if self.corpus is EmbeddingCorpus.MANUSCRIPT:
            if self.narrative_sequence_start is None:
                raise ValueError("manuscript candidate requires narrative sequence")
        if self.visibility is CandidateVisibility.KNOWLEDGE:
            if not self.required_knowledge_keys:
                raise ValueError("knowledge visibility requires explicit keys")
        elif self.required_knowledge_keys:
            raise ValueError("knowledge keys require knowledge visibility")
        return self

    @property
    def source_identity(self) -> tuple[EmbeddingCorpus, str, UUID]:
        """Stable source key used for result de-duplication."""

        return (self.corpus, self.source_type, self.source_id)

    @property
    def source_revision_identity(
        self,
    ) -> tuple[EmbeddingCorpus, str, UUID, UUID | None]:
        """Exact immutable source version used for adjacent chunk expansion."""

        return (
            self.corpus,
            self.source_type,
            self.source_id,
            self.source_revision_id,
        )


class RawChannelScore(_StrictModel):
    """Adapter-normalized relevance; larger values are always more relevant."""

    chunk_id: UUID
    score: float

    @field_validator("score")
    @classmethod
    def validate_finite_score(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("raw channel score must be finite")
        return value


class RetrievalChannelEvidence(_StrictModel):
    channel: RetrievalChannel
    status: RetrievalChannelStatus
    scores: tuple[RawChannelScore, ...] = ()
    provider_request_id: str | None = Field(default=None, min_length=1, max_length=200)
    token_count: int | None = Field(default=None, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    redacted_error: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_status_payload(self) -> "RetrievalChannelEvidence":
        ids = tuple(item.chunk_id for item in self.scores)
        if len(ids) != len(set(ids)):
            raise ValueError("channel scores must not contain duplicate chunk IDs")
        if self.status is not RetrievalChannelStatus.AVAILABLE and self.scores:
            raise ValueError("unavailable channels must not contain scores")
        if self.channel is RetrievalChannel.LEXICAL:
            if self.status is not RetrievalChannelStatus.AVAILABLE:
                raise ValueError("the local lexical channel must remain available")
            if any(
                value is not None
                for value in (
                    self.provider_request_id,
                    self.token_count,
                    self.redacted_error,
                )
            ):
                raise ValueError("lexical evidence must not contain provider metadata")
        return self


class RetrievalEvidenceChunk(_StrictModel):
    chunk_id: UUID
    chunk_ordinal: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=32_000)
    timeline_id: UUID | None = None
    narrative_sequence_start: int | None = Field(default=None, ge=0)
    narrative_sequence_end: int | None = Field(default=None, ge=0)
    story_sequence_start: int | None = Field(default=None, ge=0)
    story_sequence_end: int | None = Field(default=None, ge=0)


class SemanticRetrievalHitV2(_StrictModel):
    corpus: EmbeddingCorpus
    source_type: str
    source_id: UUID
    source_revision_id: UUID | None = None
    anchor_chunk_id: UUID
    chunks: tuple[RetrievalEvidenceChunk, ...]
    lexical_raw_score: float | None = None
    dense_raw_score: float | None = None
    lexical_rank: int | None = Field(default=None, ge=1)
    dense_rank: int | None = Field(default=None, ge=1)
    fused_score: float = Field(ge=0)
    channels: tuple[RetrievalChannel, ...]

    @field_validator("lexical_raw_score", "dense_raw_score", "fused_score")
    @classmethod
    def validate_scores(cls, value: float | None) -> float | None:
        if value is not None and not isfinite(value):
            raise ValueError("result scores must be finite")
        return value

    @model_validator(mode="after")
    def validate_hit(self) -> "SemanticRetrievalHitV2":
        if not self.chunks:
            raise ValueError("retrieval hit must include at least its anchor chunk")
        if self.anchor_chunk_id not in {item.chunk_id for item in self.chunks}:
            raise ValueError("anchor chunk must be present in expanded chunks")
        if not self.channels or len(self.channels) != len(set(self.channels)):
            raise ValueError("channels must be non-empty and unique")
        return self


class FilterCount(_StrictModel):
    reason: CandidateFilterReason
    count: int = Field(ge=1)


class RetrievalDiagnostics(_StrictModel):
    candidate_count: int = Field(ge=0)
    visible_candidate_count: int = Field(ge=0)
    scored_candidate_count: int = Field(ge=0)
    below_threshold_count: int = Field(ge=0)
    duplicate_source_count: int = Field(ge=0)
    quota_omitted_count: int = Field(ge=0)
    top_k_omitted_count: int = Field(ge=0)
    filtered: tuple[FilterCount, ...] = ()


class SemanticSearchResultV2(_StrictModel):
    schema_version: Literal[SEMANTIC_RETRIEVAL_SCHEMA_VERSION] = (
        SEMANTIC_RETRIEVAL_SCHEMA_VERSION
    )
    purpose: RetrievalPurpose
    generation_id: UUID
    index_version: int = Field(ge=1)
    policy_version: str
    rrf_version: Literal[RRF_VERSION] = RRF_VERSION
    mode: RetrievalMode
    hits: tuple[SemanticRetrievalHitV2, ...] = ()
    lexical: RetrievalChannelEvidence
    dense: RetrievalChannelEvidence
    degraded: bool = False
    degradation_reason: RetrievalDegradationReason | None = None
    empty_reason: RetrievalEmptyReason | None = None
    diagnostics: RetrievalDiagnostics

    @model_validator(mode="after")
    def validate_result_state(self) -> "SemanticSearchResultV2":
        if self.lexical.channel is not RetrievalChannel.LEXICAL:
            raise ValueError("lexical evidence has the wrong channel")
        if self.dense.channel is not RetrievalChannel.DENSE:
            raise ValueError("dense evidence has the wrong channel")
        if self.degraded != (self.degradation_reason is not None):
            raise ValueError("degraded state and reason must agree")
        expected_degradation = {
            RetrievalChannelStatus.TIMEOUT: RetrievalDegradationReason.DENSE_TIMEOUT,
            RetrievalChannelStatus.NETWORK_FAILURE: (
                RetrievalDegradationReason.DENSE_NETWORK_FAILURE
            ),
            RetrievalChannelStatus.UNAVAILABLE: (
                RetrievalDegradationReason.DENSE_UNAVAILABLE
            ),
        }.get(self.dense.status)
        if self.degradation_reason is not expected_degradation:
            raise ValueError("dense channel status and degradation reason must agree")
        if self.hits and self.empty_reason is not None:
            raise ValueError("non-empty results must not have an empty reason")
        if not self.hits and self.empty_reason is None:
            raise ValueError("empty results require an empty reason")
        if self.mode is RetrievalMode.HYBRID:
            if self.dense.status is not RetrievalChannelStatus.AVAILABLE:
                raise ValueError("hybrid mode requires an available dense channel")
        elif self.dense.status is RetrievalChannelStatus.AVAILABLE:
            raise ValueError("available dense channel requires hybrid mode")
        return self
