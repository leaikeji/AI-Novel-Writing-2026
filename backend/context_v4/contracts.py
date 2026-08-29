"""Immutable DTOs for the Context V4 production path.

Persistence and retrieval adapters must fully materialize these records before
calling the pure assembler.  No DTO contains a callback, session or client.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..story_state import (
    StoryEventLinkRecord,
    StoryFactV2,
    StoryTimelineRecord,
    StoryVisibilityV1,
)


NOVEL_CONTEXT_SCHEMA_VERSION = "novel-context/4"
WRITING_CONTEXT_SNAPSHOT_VERSION = "writing-context-snapshot/1"
WRITING_CONTEXT_SNAPSHOT_VERSION_V2 = "writing-context-snapshot/2"
SINGLE_TIMELINE_MAPPING_VERSION = "single-timeline-identity/1"


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        from_attributes=True,
        frozen=True,
    )


class RetrievalPurpose(str, Enum):
    CHAPTER_BODY = "chapter_body"
    CHAPTER_OUTLINE = "chapter_outline"
    REVIEW = "review"
    SELECTION = "selection"


class PerspectiveKind(str, Enum):
    AUTHOR = "author"
    READER = "reader"
    CHARACTER = "character"


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


class StoryPositionV3(_StrictModel):
    schema_version: Literal["story-position/3"] = "story-position/3"
    timeline_id: UUID | None = None
    narrative_sequence: int = Field(ge=1)
    story_sequence_cutoff: int | None = Field(default=None, ge=0)
    timeline_mapping_version: str | None = Field(default=None, min_length=1, max_length=120)
    chapter_id: UUID | None = None
    document_revision_id: UUID | None = None


class TimelineMappingKind(str, Enum):
    SINGLE_TIMELINE_IDENTITY = "single_timeline_identity"
    EXPLICIT = "explicit"


class ChapterTimelineContextV3(_StrictModel):
    schema_version: Literal["chapter-timeline-context/3"] = "chapter-timeline-context/3"
    timeline_id: UUID
    timeline_key: str = Field(min_length=1, max_length=120)
    narrative_sequence: int = Field(ge=1)
    story_sequence_cutoff: int = Field(ge=0)
    mapping_kind: TimelineMappingKind
    mapping_version: str = Field(min_length=1, max_length=120)
    inheritance_path: tuple[UUID, ...] = Field(min_length=1)


class PositionDomain(str, Enum):
    NONE = "none"
    NARRATIVE = "narrative"
    STORY = "story"


class ContextSection(str, Enum):
    CHAPTER_REQUIREMENTS = "chapter_requirements"
    FORMAL_PLANNING = "formal_planning"
    CHARACTER_STATE = "character_state"
    STORY_STATE = "story_state"
    MANUSCRIPT = "manuscript"
    PRIVATE_ASSETS = "private_assets"
    SEMANTIC_EVIDENCE = "semantic_evidence"


CONTEXT_SECTION_ORDER: tuple[ContextSection, ...] = (
    ContextSection.CHAPTER_REQUIREMENTS,
    ContextSection.FORMAL_PLANNING,
    ContextSection.CHARACTER_STATE,
    ContextSection.STORY_STATE,
    ContextSection.MANUSCRIPT,
    ContextSection.PRIVATE_ASSETS,
    ContextSection.SEMANTIC_EVIDENCE,
)


class ContextRequirement(str, Enum):
    REQUIRED = "required"
    EXPLICIT = "explicit"
    PREFERRED = "preferred"
    CONTEXT_ONLY = "context_only"
    PROHIBITED = "prohibited"

    @property
    def mandatory(self) -> bool:
        return self in {ContextRequirement.REQUIRED, ContextRequirement.EXPLICIT}


class ContextBlockV2(_StrictModel):
    """One indivisible prompt block with an explicit coordinate domain."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=False,
        from_attributes=True,
        frozen=True,
    )

    block_id: UUID
    novel_id: UUID
    section: ContextSection
    source_kind: str = Field(min_length=1, max_length=80)
    source_id: UUID
    source_revision_id: UUID | None = None
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(min_length=1, max_length=200_000)
    estimated_token_count: int = Field(ge=1)
    estimator_version: str = Field(min_length=1, max_length=120)
    requirement: ContextRequirement = ContextRequirement.PREFERRED
    priority: int = Field(default=100, ge=0)
    position_domain: PositionDomain = PositionDomain.NONE
    timeline_id: UUID | None = None
    narrative_sequence: int | None = Field(default=None, ge=1)
    story_sequence: int | None = Field(default=None, ge=0)
    visibility: StoryVisibilityV1
    is_current_source: bool = True
    source_is_valid: bool = True

    @field_validator("source_kind", "title", "estimator_version")
    @classmethod
    def validate_labels(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("context block labels cannot be blank")
        return value

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        if not value:
            raise ValueError("context block content cannot be empty")
        return value

    @model_validator(mode="after")
    def validate_position(self) -> "ContextBlockV2":
        if self.position_domain is PositionDomain.NARRATIVE:
            if self.narrative_sequence is None:
                raise ValueError("narrative blocks require narrative_sequence")
            if self.story_sequence is not None:
                raise ValueError("narrative blocks cannot use story_sequence for cutoff")
        elif self.position_domain is PositionDomain.STORY:
            if self.story_sequence is None or self.timeline_id is None:
                raise ValueError("story blocks require timeline_id and story_sequence")
            if self.narrative_sequence is not None:
                raise ValueError("story blocks cannot use narrative_sequence for cutoff")
        elif self.narrative_sequence is not None or self.story_sequence is not None:
            raise ValueError("position-free blocks cannot contain sequence coordinates")
        return self


class ContextBudgetV1(_StrictModel):
    schema_version: Literal["context-budget/1"] = "context-budget/1"
    actual_model_id: str = Field(min_length=1, max_length=240)
    effective_context_window_tokens: int = Field(ge=1)
    reserved_output_tokens: int = Field(ge=0)
    reserved_prompt_tokens: int = Field(ge=0)
    fixed_overhead_tokens: int = Field(ge=0)
    estimator_version: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def validate_window(self) -> "ContextBudgetV1":
        if self.reserved_output_tokens + self.reserved_prompt_tokens >= self.effective_context_window_tokens:
            raise ValueError("model reservations leave no input context budget")
        return self

    @property
    def hard_input_token_budget(self) -> int:
        return (
            self.effective_context_window_tokens
            - self.reserved_output_tokens
            - self.reserved_prompt_tokens
        )


class ContextBudgetV2(_StrictModel):
    """Pre-call budget identity without invented actual-model evidence."""

    schema_version: Literal["context-budget/2"] = "context-budget/2"
    requested_provider_id: str = Field(min_length=1, max_length=160)
    requested_model_id: str = Field(min_length=1, max_length=240)
    budget_provider_id: str = Field(min_length=1, max_length=160)
    budget_model_id: str = Field(min_length=1, max_length=240)
    effective_context_window_tokens: int = Field(ge=1)
    reserved_output_tokens: int = Field(ge=0)
    reserved_prompt_tokens: int = Field(ge=0)
    fixed_overhead_tokens: int = Field(ge=0)
    estimator_version: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def validate_window(self) -> "ContextBudgetV2":
        if (
            self.reserved_output_tokens + self.reserved_prompt_tokens
            >= self.effective_context_window_tokens
        ):
            raise ValueError("model reservations leave no input context budget")
        return self

    @property
    def hard_input_token_budget(self) -> int:
        return (
            self.effective_context_window_tokens
            - self.reserved_output_tokens
            - self.reserved_prompt_tokens
        )


class ContextAssemblyErrorCode(str, Enum):
    TIMELINE_REQUIRED = "timeline_required"
    TIMELINE_MAPPING_REQUIRED = "timeline_mapping_required"
    CONTEXT_OVERFLOW = "context_overflow"


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


class OmissionCode(str, Enum):
    CROSS_NOVEL = "cross_novel"
    NOT_CURRENT = "not_current"
    SOURCE_INVALID = "source_invalid"
    OUTSIDE_TIMELINE = "outside_timeline"
    AFTER_NARRATIVE_CUTOFF = "after_narrative_cutoff"
    AFTER_STORY_CUTOFF = "after_story_cutoff"
    NOT_VISIBLE = "not_visible"
    SUPERSEDED_OR_INVALID = "superseded_or_invalid"
    AMBIGUOUS = "ambiguous"
    PROHIBITED = "prohibited"
    BUDGET_OMITTED = "budget_omitted"


class ContextOmissionV2(_StrictModel):
    code: OmissionCode
    count: int = Field(ge=1)
    source_ids: tuple[UUID, ...]
    block_ids: tuple[UUID, ...]
    estimated_token_count: int = Field(ge=0)
    explanation: str = Field(min_length=1, max_length=500)


class ContextConflictV2(_StrictModel):
    conflict_key: str = Field(min_length=1)
    fact_ids: tuple[UUID, ...] = Field(min_length=2)
    reason: Literal["same_position", "explicit_contradiction"]


class ContextBudgetResultV1(_StrictModel):
    actual_model_id: str = Field(min_length=1, max_length=240)
    effective_context_window_tokens: int = Field(ge=1)
    reserved_output_tokens: int = Field(ge=0)
    reserved_prompt_tokens: int = Field(ge=0)
    hard_input_token_budget: int = Field(ge=1)
    fixed_overhead_tokens: int = Field(ge=0)
    included_block_tokens: int = Field(ge=0)
    omitted_block_tokens: int = Field(ge=0)
    remaining_tokens: int = Field(ge=0)
    estimator_version: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def validate_accounting(self) -> "ContextBudgetResultV1":
        if (
            self.effective_context_window_tokens
            - self.reserved_output_tokens
            - self.reserved_prompt_tokens
            != self.hard_input_token_budget
        ):
            raise ValueError("hard input budget does not match the model window")
        if (
            self.fixed_overhead_tokens
            + self.included_block_tokens
            + self.remaining_tokens
            != self.hard_input_token_budget
        ):
            raise ValueError("context budget accounting is inconsistent")
        return self


class ContextBudgetResultV2(_StrictModel):
    schema_version: Literal["context-budget-result/2"] = "context-budget-result/2"
    requested_provider_id: str = Field(min_length=1, max_length=160)
    requested_model_id: str = Field(min_length=1, max_length=240)
    budget_provider_id: str = Field(min_length=1, max_length=160)
    budget_model_id: str = Field(min_length=1, max_length=240)
    effective_context_window_tokens: int = Field(ge=1)
    reserved_output_tokens: int = Field(ge=0)
    reserved_prompt_tokens: int = Field(ge=0)
    hard_input_token_budget: int = Field(ge=1)
    fixed_overhead_tokens: int = Field(ge=0)
    included_block_tokens: int = Field(ge=0)
    omitted_block_tokens: int = Field(ge=0)
    remaining_tokens: int = Field(ge=0)
    estimator_version: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def validate_accounting(self) -> "ContextBudgetResultV2":
        if (
            self.effective_context_window_tokens
            - self.reserved_output_tokens
            - self.reserved_prompt_tokens
            != self.hard_input_token_budget
        ):
            raise ValueError("hard input budget does not match the model window")
        if (
            self.fixed_overhead_tokens
            + self.included_block_tokens
            + self.remaining_tokens
            != self.hard_input_token_budget
        ):
            raise ValueError("context budget accounting is inconsistent")
        return self


class ContextDiagnosticsV2(_StrictModel):
    omissions: tuple[ContextOmissionV2, ...]
    conflicts: tuple[ContextConflictV2, ...]
    ambiguous_fact_ids: tuple[UUID, ...]
    suppressed_fact_ids: tuple[UUID, ...]
    mapping_version: str


class NovelContextAssemblySnapshotV4(_StrictModel):
    """Complete, immutable, already-loaded input for pure assembly."""

    novel_id: UUID
    purpose: RetrievalPurpose
    position: StoryPositionV3
    perspective: PerspectiveV1
    budget: ContextBudgetV1 | ContextBudgetV2
    timelines: tuple[StoryTimelineRecord, ...]
    facts: tuple[StoryFactV2, ...] = ()
    event_links: tuple[StoryEventLinkRecord, ...] = ()
    source_revision_validity: dict[UUID, bool] = Field(default_factory=dict)
    blocks: tuple[ContextBlockV2, ...] = ()

    @model_validator(mode="after")
    def validate_token_estimator(self) -> "NovelContextAssemblySnapshotV4":
        mismatched = [
            str(block.block_id)
            for block in self.blocks
            if block.estimator_version != self.budget.estimator_version
        ]
        if mismatched:
            raise ValueError(
                "all context blocks must use the budget estimator version: "
                + ",".join(mismatched)
            )
        return self


class NovelContextEnvelopeV4(_StrictModel):
    schema_version: Literal[NOVEL_CONTEXT_SCHEMA_VERSION] = NOVEL_CONTEXT_SCHEMA_VERSION
    novel_id: UUID
    purpose: RetrievalPurpose
    position: StoryPositionV3
    perspective: PerspectiveV1
    chapter_timeline: ChapterTimelineContextV3
    current_story_facts: tuple[StoryFactV2, ...]
    visible_story_facts: tuple[StoryFactV2, ...]
    included_blocks: tuple[ContextBlockV2, ...]
    diagnostics: ContextDiagnosticsV2
    budget: ContextBudgetResultV1 | ContextBudgetResultV2
    section_order: tuple[ContextSection, ...] = CONTEXT_SECTION_ORDER

    @field_validator("section_order")
    @classmethod
    def validate_section_order(
        cls, value: tuple[ContextSection, ...]
    ) -> tuple[ContextSection, ...]:
        if value != CONTEXT_SECTION_ORDER:
            raise ValueError("NovelContextEnvelopeV4 section order is fixed")
        return value

    def ordered_blocks(self) -> tuple[tuple[ContextSection, tuple[ContextBlockV2, ...]], ...]:
        return tuple(
            (
                section,
                tuple(block for block in self.included_blocks if block.section is section),
            )
            for section in CONTEXT_SECTION_ORDER
        )


class WritingContextSnapshotV1(_StrictModel):
    schema_version: Literal[WRITING_CONTEXT_SNAPSHOT_VERSION] = WRITING_CONTEXT_SNAPSHOT_VERSION
    novel_id: UUID
    purpose: RetrievalPurpose
    requested_model_id: str = Field(min_length=1, max_length=240)
    actual_model_id: str = Field(min_length=1, max_length=240)
    context_policy_version: str = Field(min_length=1, max_length=120)
    envelope: NovelContextEnvelopeV4
    assembly_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_scope(self) -> "WritingContextSnapshotV1":
        if self.novel_id != self.envelope.novel_id or self.purpose is not self.envelope.purpose:
            raise ValueError("writing snapshot scope differs from its context envelope")
        if not isinstance(self.envelope.budget, ContextBudgetResultV1):
            raise ValueError("V1 writing snapshot requires a V1 context budget")
        return self


class WritingContextSnapshotV2(_StrictModel):
    """Pre-call writing snapshot; actual identity is recorded after execution."""

    schema_version: Literal[WRITING_CONTEXT_SNAPSHOT_VERSION_V2] = (
        WRITING_CONTEXT_SNAPSHOT_VERSION_V2
    )
    novel_id: UUID
    purpose: RetrievalPurpose
    requested_provider_id: str = Field(min_length=1, max_length=160)
    requested_model_id: str = Field(min_length=1, max_length=240)
    budget_provider_id: str = Field(min_length=1, max_length=160)
    budget_model_id: str = Field(min_length=1, max_length=240)
    effective_context_window_tokens: int = Field(ge=1)
    context_policy_version: str = Field(min_length=1, max_length=120)
    envelope: NovelContextEnvelopeV4
    assembly_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_scope_and_budget(self) -> "WritingContextSnapshotV2":
        if self.novel_id != self.envelope.novel_id or self.purpose is not self.envelope.purpose:
            raise ValueError("writing snapshot scope differs from its context envelope")
        budget = self.envelope.budget
        if not isinstance(budget, ContextBudgetResultV2):
            raise ValueError("V2 writing snapshot requires a V2 context budget")
        if (
            self.requested_provider_id,
            self.requested_model_id,
            self.budget_provider_id,
            self.budget_model_id,
            self.effective_context_window_tokens,
        ) != (
            budget.requested_provider_id,
            budget.requested_model_id,
            budget.budget_provider_id,
            budget.budget_model_id,
            budget.effective_context_window_tokens,
        ):
            raise ValueError("writing snapshot identity differs from its context budget")
        return self
