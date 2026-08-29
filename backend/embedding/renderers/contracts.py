"""Typed inputs and deterministic outputs for structured semantic corpora.

These contracts deliberately accept explicit, allow-listed fields instead of
ORM JSON blobs.  The integration layer must derive them from current revisions
and the deterministic story-state projection before invoking a renderer.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..contracts import EmbeddingCorpus
from ...story_state.contracts import StoryFactV2, StoryVisibilityV1, VisibilityScope


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)


class RendererPerspective(str, Enum):
    AUTHOR = "author"
    READER = "reader"
    CHARACTER_INSTANCE = "character_instance"


class RendererErrorCode(str, Enum):
    CORPUS_DISABLED = "corpus_disabled"
    CROSS_NOVEL_SOURCE = "cross_novel_source"
    UNSUPPORTED_SOURCE = "unsupported_source"
    INVALID_SOURCE_SCOPE = "invalid_source_scope"


class RendererError(ValueError):
    def __init__(self, code: RendererErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class RenderScope(_StrictModel):
    novel_id: UUID
    target_timeline_id: UUID
    # Ordered root -> target path produced by the deterministic inheritance
    # projection. Explicit causal/travel links must never be inserted here.
    inheritance_path: tuple[UUID, ...]
    narrative_cutoff: int | None = Field(default=None, ge=0)
    perspective: RendererPerspective = RendererPerspective.AUTHOR
    observer_character_instance_id: UUID | None = None

    @field_validator("inheritance_path")
    @classmethod
    def validate_unique_path(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if not value or len(value) != len(set(value)):
            raise ValueError("inheritance_path must be non-empty and unique")
        return value

    @model_validator(mode="after")
    def validate_perspective(self) -> "RenderScope":
        if self.inheritance_path[-1] != self.target_timeline_id:
            raise ValueError("inheritance_path must end at target_timeline_id")
        if self.perspective is RendererPerspective.CHARACTER_INSTANCE:
            if self.observer_character_instance_id is None:
                raise ValueError("character perspective requires an observer instance")
        elif self.observer_character_instance_id is not None:
            raise ValueError("observer instance is valid only for character perspective")
        if self.perspective is not RendererPerspective.AUTHOR and self.narrative_cutoff is None:
            raise ValueError("reader and character perspectives require a narrative cutoff")
        return self


class _BaseRenderSource(_StrictModel):
    novel_id: UUID
    source_id: UUID
    source_revision_id: UUID | None = None
    source_version: int = Field(ge=1)
    timeline_id: UUID
    story_sequence: int | None = Field(default=None, ge=0)
    visibility: StoryVisibilityV1


class CharacterRenderSource(_BaseRenderSource):
    corpus: Literal[EmbeddingCorpus.CHARACTER] = EmbeddingCorpus.CHARACTER
    character_instance_id: UUID
    instance_character_id: UUID
    character_instance_revision_id: UUID | None = None
    segment_key: Literal["public_profile", "identity", "private_profile", "projected_state"]
    display_name: str = Field(min_length=1, max_length=240)
    display_label: str | None = Field(default=None, max_length=240)
    role_type: str = Field(min_length=1, max_length=30)
    description: str | None = Field(default=None, max_length=20_000)
    public_identity: str | None = Field(default=None, max_length=2_000)
    true_identity: str | None = Field(default=None, max_length=2_000)
    cover_identity: str | None = Field(default=None, max_length=2_000)
    birth_information: str | None = Field(default=None, max_length=2_000)
    current_age: str | None = Field(default=None, max_length=500)
    occupation: str | None = Field(default=None, max_length=2_000)
    personality: str | None = Field(default=None, max_length=4_000)
    goals: str | None = Field(default=None, max_length=4_000)
    flaws: str | None = Field(default=None, max_length=4_000)
    secrets: str | None = Field(default=None, max_length=8_000)
    growth_direction: str | None = Field(default=None, max_length=4_000)

    @model_validator(mode="after")
    def validate_root_instance_pair(self) -> "CharacterRenderSource":
        if self.instance_character_id != self.source_id:
            raise ValueError("character instance does not belong to the source root")
        return self


class RelationshipRenderSource(_BaseRenderSource):
    corpus: Literal[EmbeddingCorpus.RELATIONSHIP] = EmbeddingCorpus.RELATIONSHIP
    source_character_id: UUID
    target_character_id: UUID
    source_character_instance_id: UUID
    target_character_instance_id: UUID
    source_instance_character_id: UUID
    target_instance_character_id: UUID
    source_display_name: str = Field(min_length=1, max_length=240)
    target_display_name: str = Field(min_length=1, max_length=240)
    directionality: str = Field(min_length=1, max_length=24)
    relation_kind: str = Field(min_length=1, max_length=30)
    label: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=20_000)
    projected_status: str | None = Field(default=None, max_length=240)

    @model_validator(mode="after")
    def validate_endpoints(self) -> "RelationshipRenderSource":
        if self.source_character_instance_id == self.target_character_instance_id:
            raise ValueError("relationship instance endpoints must be distinct")
        if self.source_instance_character_id != self.source_character_id:
            raise ValueError("source instance does not belong to source character root")
        if self.target_instance_character_id != self.target_character_id:
            raise ValueError("target instance does not belong to target character root")
        return self


class StoryEventRenderSource(_StrictModel):
    corpus: Literal[EmbeddingCorpus.STORY_EVENT] = EmbeddingCorpus.STORY_EVENT
    novel_id: UUID
    fact: StoryFactV2

    @model_validator(mode="after")
    def validate_fact_scope(self) -> "StoryEventRenderSource":
        if self.fact.novel_id != self.novel_id:
            raise ValueError("story fact belongs to another novel")
        return self


class StorylineRenderSource(_BaseRenderSource):
    corpus: Literal[EmbeddingCorpus.STORYLINE] = EmbeddingCorpus.STORYLINE
    storyline_type: str = Field(min_length=1, max_length=30)
    title: str = Field(min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=20_000)
    planned_status: str = Field(min_length=1, max_length=30)
    projected_status: str | None = Field(default=None, max_length=240)


class ForeshadowRenderSource(_BaseRenderSource):
    corpus: Literal[EmbeddingCorpus.FORESHADOW] = EmbeddingCorpus.FORESHADOW
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(min_length=1, max_length=20_000)
    planned_status: str = Field(min_length=1, max_length=30)
    projected_status: str | None = Field(default=None, max_length=240)


class TimelineRenderSource(_BaseRenderSource):
    corpus: Literal[EmbeddingCorpus.TIMELINE] = EmbeddingCorpus.TIMELINE
    timeline_key: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=240)
    timeline_kind: Literal["main", "branch", "merge"]
    is_primary: bool
    parent_timeline_id: UUID | None = None
    parent_timeline_name: str | None = Field(default=None, max_length=240)
    fork_story_sequence: int | None = Field(default=None, ge=0)
    fork_anchor_label: str | None = Field(default=None, max_length=2_000)
    lifecycle_state: Literal["active"] = "active"

    @model_validator(mode="after")
    def validate_parent(self) -> "TimelineRenderSource":
        if self.source_id != self.timeline_id:
            raise ValueError("timeline source_id must equal timeline_id")
        if self.timeline_kind == "main":
            if self.parent_timeline_id is not None or self.fork_story_sequence is not None:
                raise ValueError("main timeline cannot expose a parent or fork anchor")
        elif self.parent_timeline_id is None or self.fork_story_sequence is None:
            raise ValueError("branch and merge timelines require parent and fork anchor")
        return self


StructuredRenderSource = (
    CharacterRenderSource
    | RelationshipRenderSource
    | StoryEventRenderSource
    | StorylineRenderSource
    | ForeshadowRenderSource
    | TimelineRenderSource
)


class RenderedCorpusMetadata(_StrictModel):
    corpus: EmbeddingCorpus
    novel_id: UUID
    source_type: Literal[
        "character",
        "relationship",
        "story_fact",
        "storyline",
        "foreshadow",
        "timeline",
    ]
    source_id: UUID
    source_revision_id: UUID | None = None
    source_version: int = Field(ge=1)
    timeline_id: UUID
    character_instance_ids: tuple[UUID, ...] = ()
    narrative_sequence: int | None = Field(default=None, ge=0)
    visibility_scope: VisibilityScope
    visibility_character_instance_ids: tuple[UUID, ...] = ()
    revealed_at_sequence: int | None = Field(default=None, ge=0)

    @field_validator("character_instance_ids", "visibility_character_instance_ids")
    @classmethod
    def normalize_ids(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(value) != len(set(value)):
            raise ValueError("metadata IDs must not contain duplicates")
        return tuple(sorted(value, key=str))


class RenderedCorpusDocument(_StrictModel):
    renderer_id: str = Field(min_length=1, max_length=120)
    renderer_version: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=1)
    metadata: RenderedCorpusMetadata
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
