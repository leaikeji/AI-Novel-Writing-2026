"""Versioned read contracts for the character workspace."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class _ReadModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class CharacterWorkspaceErrorCode(str, Enum):
    CHARACTER_NOT_FOUND = "character_not_found"
    TIMELINE_NOT_FOUND = "timeline_not_found"
    TIMELINE_REQUIRED = "timeline_required"
    TIMELINE_CONFLICT = "timeline_conflict"
    CHARACTER_INSTANCE_NOT_FOUND = "character_instance_not_found"
    CHARACTER_INSTANCE_REQUIRED = "character_instance_required"
    CHARACTER_INSTANCE_CONFLICT = "character_instance_conflict"
    INVALID_CURSOR = "invalid_cursor"


class CharacterWorkspaceError(ValueError):
    def __init__(
        self,
        code: CharacterWorkspaceErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class CharacterRootView(_ReadModel):
    id: UUID
    novel_id: UUID
    name: str
    role_type: str
    description: str = ""
    details: dict[str, JsonValue] = Field(default_factory=dict)
    lifecycle_state: str
    position: int
    version: int
    current_revision_id: UUID | None = None


class TimelineView(_ReadModel):
    id: UUID
    name: str
    timeline_kind: str
    is_primary: bool
    parent_timeline_id: UUID | None = None
    fork_story_sequence: int | None = None


class CharacterInstanceView(_ReadModel):
    id: UUID
    character_id: UUID
    origin_timeline_id: UUID
    continuity_kind: str
    display_label: str = ""
    derived_from_instance_id: UUID | None = None
    lifecycle_state: str
    version: int
    current_revision_id: UUID | None = None
    profile: dict[str, JsonValue] = Field(default_factory=dict)
    profile_schema_version: int | None = None


class CharacterAliasView(_ReadModel):
    id: UUID
    alias: str
    alias_kind: str | None = None
    character_instance_id: UUID | None = None
    timeline_id: UUID | None = None
    identity_layer: str | None = None
    valid_from_sequence: int | None = None
    valid_to_sequence: int | None = None
    lifecycle_state: str


class CharacterRelationshipView(_ReadModel):
    id: UUID
    timeline_id: UUID | None = None
    source_character_id: UUID
    target_character_id: UUID
    source_character_instance_id: UUID | None = None
    target_character_instance_id: UUID | None = None
    directionality: str
    relation_kind: str
    label: str
    description: str = ""
    status: str
    manual_override: bool
    version: int


class ChapterCharacterReference(_ReadModel):
    document_id: UUID
    document_title: str
    document_position: int
    reference_kinds: tuple[Literal["required", "point_of_view"], ...]
    character_instance_id: UUID | None = None
    timeline_id: UUID | None = None


class CharacterVoiceBindingView(_ReadModel):
    binding_id: UUID
    binding_policy: str
    profile_id: UUID | None = None
    voice_version_id: UUID | None = None
    language: str
    version: int


class ProjectedFactView(_ReadModel):
    id: UUID
    fact_type: str
    timeline_id: UUID
    character_id: UUID | None = None
    character_instance_id: UUID | None = None
    relationship_id: UUID | None = None
    dimension: str
    event_kind: str
    predicate: str
    object_text: str
    details: dict[str, JsonValue]
    story_sequence: int | None = None
    source_revision_id: UUID | None = None


class ProjectionConflictView(_ReadModel):
    conflict_key: str
    fact_ids: tuple[UUID, ...]
    reason: str


FactEffectiveState = Literal[
    "current",
    "historical",
    "superseded",
    "source_invalid",
    "batch_reverted",
]
FactHealth = Literal["ok", "conflict", "ambiguous"]


class FactSourceView(_ReadModel):
    document_id: UUID
    document_title: str
    document_position: int
    revision_id: UUID
    revision_is_current: bool
    source_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_coordinate: Literal["unicode-codepoint-v1"] = "unicode-codepoint-v1"
    source_start: int | None = Field(default=None, ge=0)
    source_end: int | None = Field(default=None, gt=0)
    source_range_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_excerpt: str = Field(default="", max_length=500)
    source_excerpt_truncated: bool = False
    binding_state: str | None = None
    proposal_item_id: UUID | None = None
    commit_batch_id: UUID | None = None


class ProjectedFactViewV2(ProjectedFactView):
    source_document_id: UUID | None = None
    story_time: dict[str, JsonValue] | None = None
    created_at: datetime
    effective_state: FactEffectiveState
    health: FactHealth
    source: FactSourceView | None = None


class CharacterProjectedStateV2(_ReadModel):
    timeline_id: UUID
    narrative_cutoff: int | None = None
    current_facts: tuple[ProjectedFactViewV2, ...] = ()
    conflicts: tuple[ProjectionConflictView, ...] = ()
    ambiguous_fact_ids: tuple[UUID, ...] = ()


class WritingStateAsOf(_ReadModel):
    timeline_id: UUID
    narrative_cutoff: int | None = None
    story_time: dict[str, JsonValue] | None = None


class WritingStateValue(_ReadModel):
    fact_id: UUID
    object_text: str
    story_sequence: int | None = None
    story_time: dict[str, JsonValue] | None = None
    source: FactSourceView | None = None


class WritingStateSlot(_ReadModel):
    key: Literal[
        "location",
        "goal",
        "health",
        "emotion",
        "identity",
        "knowledge",
        "possession",
        "relationship",
    ]
    label: str
    mode: Literal["single", "multiple"]
    values: tuple[WritingStateValue, ...] = ()
    health: Literal["ok", "conflicted", "ambiguous", "missing"]


class WritingStateRiskSummary(_ReadModel):
    conflict_count: int = Field(ge=0)
    ambiguous_count: int = Field(ge=0)
    invalid_source_count: int = Field(ge=0)


class FactHistorySummary(_ReadModel):
    total: int = Field(ge=0)
    current: int = Field(ge=0)
    historical: int = Field(ge=0)
    superseded: int = Field(ge=0)
    source_invalid: int = Field(ge=0)
    batch_reverted: int = Field(ge=0)


class CharacterWritingState(_ReadModel):
    as_of: WritingStateAsOf
    slots: tuple[WritingStateSlot, ...]
    recent_changes: tuple[ProjectedFactViewV2, ...] = ()
    risk_summary: WritingStateRiskSummary
    history_summary: FactHistorySummary


class CharacterProjectedState(_ReadModel):
    timeline_id: UUID
    narrative_cutoff: int | None = None
    current_facts: tuple[ProjectedFactView, ...] = ()
    conflicts: tuple[ProjectionConflictView, ...] = ()
    ambiguous_fact_ids: tuple[UUID, ...] = ()


class CharacterWorkspaceV1(_ReadModel):
    schema_version: Literal["character-workspace/1"] = "character-workspace/1"
    novel_id: UUID
    character_catalog_version: int
    story_ledger_version: int
    timeline_mode: Literal["single", "multiple"]
    character: CharacterRootView
    selected_timeline: TimelineView
    selected_instance: CharacterInstanceView
    timelines: tuple[TimelineView, ...]
    instances: tuple[CharacterInstanceView, ...]
    aliases: tuple[CharacterAliasView, ...]
    relationships: tuple[CharacterRelationshipView, ...]
    chapter_references: tuple[ChapterCharacterReference, ...]
    voice_binding: CharacterVoiceBindingView | None = None
    projected_state: CharacterProjectedState


class CharacterWorkspaceV2(_ReadModel):
    schema_version: Literal["character-workspace/2"] = "character-workspace/2"
    novel_id: UUID
    character_catalog_version: int
    story_ledger_version: int
    timeline_mode: Literal["single", "multiple"]
    character: CharacterRootView
    selected_timeline: TimelineView
    selected_instance: CharacterInstanceView
    timelines: tuple[TimelineView, ...]
    instances: tuple[CharacterInstanceView, ...]
    aliases: tuple[CharacterAliasView, ...]
    relationships: tuple[CharacterRelationshipView, ...]
    chapter_references: tuple[ChapterCharacterReference, ...]
    voice_binding: CharacterVoiceBindingView | None = None
    projected_state: CharacterProjectedStateV2
    writing_state: CharacterWritingState


class CharacterFactHistoryPage(_ReadModel):
    schema_version: Literal["character-fact-history/1"] = (
        "character-fact-history/1"
    )
    items: tuple[ProjectedFactViewV2, ...]
    next_cursor: str | None = None
    total_summary: FactHistorySummary


class ArchiveImpactReference(_ReadModel):
    reference_type: Literal[
        "active_instance",
        "active_alias",
        "active_relationship",
        "chapter_brief",
        "voice_binding",
        "story_fact",
    ]
    reference_id: UUID
    label: str
    disposition: Literal["requires_review", "preserved_history"]


class CharacterArchiveImpactV1(_ReadModel):
    schema_version: Literal["character-archive-impact/1"] = (
        "character-archive-impact/1"
    )
    novel_id: UUID
    character_id: UUID
    character_name: str
    character_version: int
    already_archived: bool
    requires_confirmation: bool
    current_dependency_count: int
    preserved_history_count: int
    references: tuple[ArchiveImpactReference, ...]
