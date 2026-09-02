"""Public wire contracts for the whole-novel Story Ledger workspace."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


FactEffectiveState = Literal[
    "current",
    "historical",
    "superseded",
    "source_invalid",
    "batch_reverted",
]
FactHealth = Literal["ok", "conflict", "ambiguous"]


class _ReadModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True, frozen=True)


class LedgerTimelineContext(_ReadModel):
    mode: Literal["none", "single", "multiple"]
    timeline_id: UUID | None = None
    timeline_name: str | None = None
    narrative_cutoff: int | None = Field(default=None, ge=0)


class LedgerEntityReference(_ReadModel):
    entity_type: Literal[
        "character",
        "character_instance",
        "relationship",
        "storyline",
        "foreshadow",
    ]
    entity_id: UUID
    label: str
    lifecycle_state: str | None = None
    reference_missing: bool = False


class LedgerSourceReference(_ReadModel):
    source_document_id: UUID | None = None
    document_title: str | None = None
    document_position: int | None = None
    source_revision_id: UUID | None = None
    revision_number: int | None = None
    revision_is_current: bool | None = None
    source_content_hash: str | None = None
    source_start: int | None = None
    source_end: int | None = None
    binding_state: str | None = None
    commit_batch_id: UUID | None = None
    evidence_available: bool = False


class LedgerFactItem(_ReadModel):
    id: UUID
    fact_type: str
    subject: str
    predicate: str
    object_preview: str
    object_truncated: bool
    timeline_id: UUID | None = None
    dimension: str | None = None
    event_kind: str | None = None
    story_sequence: int | None = None
    created_at: datetime
    effective_state: FactEffectiveState
    effective_reason_codes: tuple[str, ...]
    included_in_current_projection: bool
    health: FactHealth
    health_reason_codes: tuple[str, ...]
    entities: tuple[LedgerEntityReference, ...] = ()
    source: LedgerSourceReference | None = None


class LedgerEventLinkView(_ReadModel):
    id: UUID
    direction: Literal["incoming", "outgoing"]
    link_type: str
    other_fact_id: UUID
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class LedgerBindingView(_ReadModel):
    id: UUID
    source_document_id: UUID
    source_revision_id: UUID
    source_content_hash: str
    validity_state: str
    proposal_item_id: UUID | None = None
    commit_batch_id: UUID | None = None
    commit_batch_state: str | None = None
    created_at: datetime


class LedgerFactDetail(_ReadModel):
    schema_version: Literal["story-ledger-fact-detail/1"] = (
        "story-ledger-fact-detail/1"
    )
    novel_id: UUID
    ledger_snapshot_token: str
    story_ledger_version: int
    timeline: LedgerTimelineContext
    item: LedgerFactItem
    object_text: str
    details: dict[str, Any] = Field(default_factory=dict)
    story_time: dict[str, Any] | None = None
    visibility: dict[str, Any] | None = None
    lifecycle_status: str
    schema_version_of_fact: str | None = None
    event_fingerprint: str | None = None
    event_links: tuple[LedgerEventLinkView, ...] = ()
    bindings: tuple[LedgerBindingView, ...] = ()


class LedgerSummary(_ReadModel):
    schema_version: Literal["story-ledger-summary/1"] = "story-ledger-summary/1"
    novel_id: UUID
    ledger_snapshot_token: str
    story_ledger_version: int
    timeline: LedgerTimelineContext
    filter_sha256: str
    total: int
    by_fact_type: dict[str, int]
    by_effective_state: dict[str, int]
    by_health: dict[str, int]
    review_required: int


class LedgerFactPage(_ReadModel):
    schema_version: Literal["story-ledger-page/1"] = "story-ledger-page/1"
    novel_id: UUID
    ledger_snapshot_token: str
    story_ledger_version: int
    timeline: LedgerTimelineContext
    filter_sha256: str
    items: tuple[LedgerFactItem, ...]
    next_cursor: str | None = None


class LedgerSourceExcerpt(_ReadModel):
    schema_version: Literal["story-ledger-source/1"] = "story-ledger-source/1"
    novel_id: UUID
    fact_id: UUID
    ledger_snapshot_token: str
    story_ledger_version: int
    timeline: LedgerTimelineContext
    available: bool
    unavailable_reason: str | None = None
    document_id: UUID | None = None
    document_title: str | None = None
    document_position: int | None = None
    revision_id: UUID | None = None
    revision_number: int | None = None
    revision_is_current: bool | None = None
    source_content_hash: str | None = None
    source_range_hash: str | None = None
    source_start: int | None = None
    source_end: int | None = None
    excerpt: str = ""
    excerpt_start: int | None = None
    excerpt_end: int | None = None
    highlight_start: int | None = None
    highlight_end: int | None = None
    truncated_before: bool = False
    truncated_after: bool = False


class LedgerFactImpactPreview(_ReadModel):
    schema_version: Literal["story-ledger-fact-impact-preview/1"] = (
        "story-ledger-fact-impact-preview/1"
    )
    novel_id: UUID
    fact_id: UUID
    preview_snapshot_token: str
    story_ledger_version: int
    timeline: LedgerTimelineContext
    currently_in_projection: bool
    current_projection_fact_count: int
    related_event_link_count: int
    embedding_rebuild_required: bool
    commit_batch_ids: tuple[UUID, ...] = ()
    batch_fact_count: int
    batch_relationship_count: int
    correction_supported: bool
    correction_block_reason: str | None = None


class LedgerBatchImpactPreview(_ReadModel):
    schema_version: Literal["story-ledger-batch-impact-preview/1"] = (
        "story-ledger-batch-impact-preview/1"
    )
    novel_id: UUID
    batch_id: UUID
    preview_snapshot_token: str
    story_ledger_version: int
    timeline: LedgerTimelineContext
    state: str
    already_reverted: bool
    batch_fact_count: int
    batch_relationship_count: int
    facts: tuple[dict[str, Any], ...]
    relationships: tuple[dict[str, Any], ...]


__all__ = [
    "FactEffectiveState",
    "FactHealth",
    "LedgerBatchImpactPreview",
    "LedgerBindingView",
    "LedgerEntityReference",
    "LedgerEventLinkView",
    "LedgerFactDetail",
    "LedgerFactImpactPreview",
    "LedgerFactItem",
    "LedgerFactPage",
    "LedgerSourceExcerpt",
    "LedgerSourceReference",
    "LedgerSummary",
    "LedgerTimelineContext",
]
