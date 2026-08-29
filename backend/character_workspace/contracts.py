"""Versioned read contracts for the character workspace."""

from __future__ import annotations

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
