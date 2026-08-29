"""Versioned, immutable DTOs for the unified novel context envelope.

These contracts contain no persistence adapter.  Integration code must load a
fully scoped snapshot first, then pass it to the pure assembler.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..story_state import (
    StoryEventLinkRecord,
    StoryFactV2,
    StoryTimeV1,
    StoryTimelineRecord,
    StoryVisibilityV1,
)


NOVEL_CONTEXT_SCHEMA_VERSION = "novel-context/3"


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        from_attributes=True,
        frozen=True,
    )


class PerspectiveKind(str, Enum):
    AUTHOR = "author"
    READER = "reader"
    CHARACTER = "character"


class ContextAuthority(str, Enum):
    INSTRUCTION = "instruction"
    FORMAL = "formal"
    DETERMINISTIC = "deterministic"
    FIXED_PRIVATE = "fixed_private"
    SUPPLEMENTAL = "supplemental"


class ContextSectionName(str, Enum):
    CHAPTER_REQUIREMENTS = "chapter_requirements"
    FORMAL_PLANNING = "formal_planning"
    CHARACTER_STATE = "character_state"
    STORY_STATE = "story_state"
    PRIVATE_ASSETS = "private_assets"
    SEMANTIC_EVIDENCE = "semantic_evidence"
    DIAGNOSTICS = "diagnostics"


CONTEXT_SECTION_ORDER: tuple[ContextSectionName, ...] = (
    ContextSectionName.CHAPTER_REQUIREMENTS,
    ContextSectionName.FORMAL_PLANNING,
    ContextSectionName.CHARACTER_STATE,
    ContextSectionName.STORY_STATE,
    ContextSectionName.PRIVATE_ASSETS,
    ContextSectionName.SEMANTIC_EVIDENCE,
    ContextSectionName.DIAGNOSTICS,
)


class ContextAssemblyErrorCode(str, Enum):
    REQUIRED_CHARACTER_UNAVAILABLE = "required_character_unavailable"
    OBSERVER_UNAVAILABLE = "observer_unavailable"


class ContextAssemblyError(ValueError):
    def __init__(
        self,
        code: ContextAssemblyErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class CharacterRefV2(_StrictModel):
    """Stable character identity; display text is never a lookup key."""

    character_id: UUID
    character_instance_id: UUID
    display_label: str = Field(default="", max_length=240)


class AuthorSecretConstraintV1(_StrictModel):
    constraint_id: UUID
    instruction: str = Field(min_length=1, max_length=10_000)
    source_revision_id: UUID
    character_ref: CharacterRefV2 | None = None


class ChapterRoleConstraintsV3(_StrictModel):
    schema_version: Literal["chapter-role-constraints/3"] = "chapter-role-constraints/3"
    required_characters: tuple[CharacterRefV2, ...] = ()
    point_of_view: CharacterRefV2 | None = None
    public_requirements: tuple[str, ...] = ()
    prohibited_outcomes: tuple[str, ...] = ()
    author_secret_constraints: tuple[AuthorSecretConstraintV1, ...] = ()
    author_secret_facts: tuple[StoryFactV2, ...] = ()

    @field_validator("required_characters")
    @classmethod
    def validate_unique_required_characters(
        cls, value: tuple[CharacterRefV2, ...]
    ) -> tuple[CharacterRefV2, ...]:
        instance_ids = [item.character_instance_id for item in value]
        if len(instance_ids) != len(set(instance_ids)):
            raise ValueError("required character instances must be unique")
        return value


class StoryPositionV2(_StrictModel):
    schema_version: Literal["story-position/2"] = "story-position/2"
    timeline_id: UUID | None = None
    narrative_sequence: int | None = Field(default=None, ge=0)
    chapter_id: UUID | None = None
    document_revision_id: UUID | None = None
    story_time: StoryTimeV1 | None = None


class PerspectiveV1(_StrictModel):
    schema_version: Literal["perspective/1"] = "perspective/1"
    kind: PerspectiveKind
    observer_character_instance_id: UUID | None = None

    @model_validator(mode="after")
    def validate_observer(self) -> "PerspectiveV1":
        if self.kind is PerspectiveKind.CHARACTER:
            if self.observer_character_instance_id is None:
                raise ValueError("character perspective requires an observer instance ID")
        elif self.observer_character_instance_id is not None:
            raise ValueError("only character perspective accepts an observer instance ID")
        return self


class ChapterTimelineContextV2(_StrictModel):
    schema_version: Literal["chapter-timeline-context/2"] = "chapter-timeline-context/2"
    timeline_id: UUID
    timeline_key: str = Field(min_length=1, max_length=120)
    narrative_sequence: int | None = Field(default=None, ge=0)
    story_time: StoryTimeV1 | None = None
    perspective: PerspectiveV1
    inheritance_path: tuple[UUID, ...]


class PlanningKind(str, Enum):
    OUTLINE = "outline"
    SETTING = "setting"


class FormalPlanningRecordV1(_StrictModel):
    novel_id: UUID
    planning_kind: PlanningKind
    source_id: UUID
    revision_id: UUID
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(min_length=1, max_length=200_000)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    is_current: bool = True


class CharacterContextRecordV2(_StrictModel):
    novel_id: UUID
    ref: CharacterRefV2
    root_revision_id: UUID
    instance_revision_id: UUID
    present_on_timeline_ids: tuple[UUID, ...] = Field(min_length=1)
    active_from_sequence: int | None = Field(default=None, ge=0)
    active_to_sequence: int | None = Field(default=None, ge=0)
    public_profile: str = Field(default="", max_length=100_000)
    author_secret_constraints: tuple[AuthorSecretConstraintV1, ...] = ()

    @field_validator("present_on_timeline_ids")
    @classmethod
    def validate_unique_timelines(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(value) != len(set(value)):
            raise ValueError("present_on_timeline_ids must be unique")
        return value

    @model_validator(mode="after")
    def validate_active_range_and_secret_refs(self) -> "CharacterContextRecordV2":
        if (
            self.active_from_sequence is not None
            and self.active_to_sequence is not None
            and self.active_to_sequence < self.active_from_sequence
        ):
            raise ValueError("character active range is reversed")
        for constraint in self.author_secret_constraints:
            if constraint.character_ref is not None and (
                constraint.character_ref.character_id != self.ref.character_id
                or constraint.character_ref.character_instance_id
                != self.ref.character_instance_id
            ):
                raise ValueError("character secret constraint references another character")
        return self


class PrivateAssetPolicy(str, Enum):
    REQUIRED = "required"
    PREFERRED = "preferred"
    CONTEXT_ONLY = "context_only"
    PROHIBITED = "prohibited"


class BoundPrivateAssetRecordV1(_StrictModel):
    novel_id: UUID
    binding_id: UUID
    asset_id: UUID
    asset_version_id: UUID
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(min_length=1, max_length=200_000)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy: PrivateAssetPolicy
    is_current_binding: bool = True


class SemanticCorpus(str, Enum):
    MANUSCRIPT = "manuscript"
    PLANNING = "planning"
    PRIVATE_ASSET = "private_asset"
    CHARACTER = "character"
    RELATIONSHIP = "relationship"
    STORY_EVENT = "story_event"
    STORYLINE = "storyline"
    FORESHADOW = "foreshadow"
    TIMELINE = "timeline"


class SemanticEvidenceRecordV1(_StrictModel):
    evidence_id: UUID
    novel_id: UUID
    corpus: SemanticCorpus
    source_id: UUID
    source_revision_id: UUID | None = None
    chunk_id: UUID
    content: str = Field(min_length=1, max_length=100_000)
    score: float
    timeline_id: UUID | None = None
    story_sequence: int | None = Field(default=None, ge=0)
    visibility: StoryVisibilityV1
    is_current_source: bool = True


class ContextTextBlockV1(_StrictModel):
    source_id: UUID
    revision_id: UUID
    title: str
    content: str
    authority: ContextAuthority
    policy: PrivateAssetPolicy | None = None


class CharacterContextV2(_StrictModel):
    ref: CharacterRefV2
    root_revision_id: UUID
    instance_revision_id: UUID
    public_profile: str
    current_state_facts: tuple[StoryFactV2, ...]


class StoryStateContextV1(_StrictModel):
    current_facts: tuple[StoryFactV2, ...]


class SemanticContextEvidenceV1(_StrictModel):
    evidence_id: UUID
    corpus: SemanticCorpus
    source_id: UUID
    source_revision_id: UUID | None = None
    chunk_id: UUID
    content: str
    score: float
    visibility: StoryVisibilityV1
    authority: Literal[ContextAuthority.SUPPLEMENTAL] = ContextAuthority.SUPPLEMENTAL


class ContextSourceV1(_StrictModel):
    source_kind: str = Field(min_length=1, max_length=80)
    source_id: UUID
    revision_id: UUID | None = None
    timeline_id: UUID | None = None
    authority: ContextAuthority


class ContextConflictV1(_StrictModel):
    conflict_key: str
    fact_ids: tuple[UUID, ...] = Field(min_length=2)
    reason: Literal["same_position", "explicit_contradiction"]


class OmissionCode(str, Enum):
    CROSS_NOVEL = "cross_novel"
    NOT_CURRENT = "not_current"
    OUTSIDE_TIMELINE = "outside_timeline"
    AFTER_CUTOFF = "after_cutoff"
    NOT_VISIBLE = "not_visible"
    SOURCE_INVALID = "source_invalid"
    AMBIGUOUS = "ambiguous"
    SUPERSEDED_OR_INVALID = "superseded_or_invalid"
    PROHIBITED = "prohibited"
    AUTHOR_SECRET_WITHHELD = "author_secret_withheld"


class ContextOmissionV1(_StrictModel):
    code: OmissionCode
    count: int = Field(ge=1)
    explanation: str = Field(min_length=1, max_length=500)


class ContextDiagnosticsV1(_StrictModel):
    sources: tuple[ContextSourceV1, ...]
    conflicts: tuple[ContextConflictV1, ...]
    omissions: tuple[ContextOmissionV1, ...]
    ambiguous_fact_ids: tuple[UUID, ...]
    suppressed_fact_ids: tuple[UUID, ...]


class NovelContextAssemblySnapshotV3(_StrictModel):
    """Complete read-only input snapshot for one deterministic assembly."""

    novel_id: UUID
    position: StoryPositionV2
    perspective: PerspectiveV1
    chapter_requirements: ChapterRoleConstraintsV3
    timelines: tuple[StoryTimelineRecord, ...]
    character_records: tuple[CharacterContextRecordV2, ...] = ()
    facts: tuple[StoryFactV2, ...] = ()
    event_links: tuple[StoryEventLinkRecord, ...] = ()
    source_revision_validity: dict[UUID, bool] = Field(default_factory=dict)
    formal_planning: tuple[FormalPlanningRecordV1, ...] = ()
    private_assets: tuple[BoundPrivateAssetRecordV1, ...] = ()
    semantic_evidence: tuple[SemanticEvidenceRecordV1, ...] = ()


class NovelContextEnvelopeV3(_StrictModel):
    schema_version: Literal[NOVEL_CONTEXT_SCHEMA_VERSION] = NOVEL_CONTEXT_SCHEMA_VERSION
    novel_id: UUID
    chapter_timeline: ChapterTimelineContextV2
    chapter_requirements: ChapterRoleConstraintsV3
    formal_planning: tuple[ContextTextBlockV1, ...]
    character_state: tuple[CharacterContextV2, ...]
    story_state: StoryStateContextV1
    private_assets: tuple[ContextTextBlockV1, ...]
    semantic_evidence: tuple[SemanticContextEvidenceV1, ...]
    diagnostics: ContextDiagnosticsV1
    section_order: tuple[ContextSectionName, ...] = CONTEXT_SECTION_ORDER

    @field_validator("section_order")
    @classmethod
    def validate_section_order(
        cls, value: tuple[ContextSectionName, ...]
    ) -> tuple[ContextSectionName, ...]:
        if value != CONTEXT_SECTION_ORDER:
            raise ValueError("NovelContextEnvelopeV3 section order is fixed")
        return value

    def ordered_sections(self) -> tuple[tuple[ContextSectionName, object], ...]:
        return (
            (ContextSectionName.CHAPTER_REQUIREMENTS, self.chapter_requirements),
            (ContextSectionName.FORMAL_PLANNING, self.formal_planning),
            (ContextSectionName.CHARACTER_STATE, self.character_state),
            (ContextSectionName.STORY_STATE, self.story_state),
            (ContextSectionName.PRIVATE_ASSETS, self.private_assets),
            (ContextSectionName.SEMANTIC_EVIDENCE, self.semantic_evidence),
            (ContextSectionName.DIAGNOSTICS, self.diagnostics),
        )
