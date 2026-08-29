"""Versioned contracts for deterministic story-state processing.

The record shapes mirror the frozen ORM columns but contain no SQLAlchemy or
database behavior.  ``from_attributes=True`` lets the later integration layer
adapt ORM rows without coupling this domain package to a session.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator


STORY_FACT_SCHEMA_VERSION = "story-fact/2"


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        from_attributes=True,
        frozen=True,
    )


class StoryStateErrorCode(str, Enum):
    TIMELINE_NOT_FOUND = "timeline_not_found"
    TIMELINE_REQUIRED = "timeline_required"
    TIMELINE_CONFLICT = "timeline_conflict"
    CHARACTER_INSTANCE_NOT_FOUND = "character_instance_not_found"
    CHARACTER_INSTANCE_REQUIRED = "character_instance_required"
    CHARACTER_INSTANCE_CONFLICT = "character_instance_conflict"
    INVALID_INHERITANCE = "invalid_inheritance"
    INVALID_TIMELINE_LINK = "invalid_timeline_link"
    FORK_CONFLICT = "fork_conflict"


class StoryStateError(ValueError):
    """Domain error with a stable code suitable for later API translation."""

    def __init__(
        self,
        code: StoryStateErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class LifecycleState(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class TimelineKind(str, Enum):
    MAIN = "main"
    BRANCH = "branch"
    MERGE = "merge"


class TimelineLinkType(str, Enum):
    TRAVEL = "travel"
    MEMORY_TRANSFER = "memory_transfer"
    CAUSAL = "causal"
    LOOP_RETURN = "loop_return"
    MERGE_REFERENCE = "merge_reference"


class CharacterContinuityKind(str, Enum):
    NATIVE = "native"
    DERIVED = "derived"
    TRAVELER = "traveler"


class StoryEventLinkType(str, Enum):
    CAUSES = "causes"
    REVEALS = "reveals"
    CONTRADICTS = "contradicts"
    SUPERSEDES = "supersedes"
    ENABLES = "enables"


class StoryFactType(str, Enum):
    CHARACTER_STATE = "character_state"
    RELATIONSHIP_STATE = "relationship_state"
    STORYLINE_EVENT = "storyline_event"
    FORESHADOW_EVENT = "foreshadow_event"
    STORY_TIME = "story_time"
    KNOWLEDGE_EVENT = "knowledge_event"
    WORLD_STATE = "world_state"
    GENERAL_FACT = "general_fact"


class StoryFactStatus(str, Enum):
    ACTIVE = "active"
    SOURCE_RESTORED = "source_restored"
    SOURCE_SUPERSEDED = "source_superseded"
    SUPERSEDED = "superseded"
    INVALID = "invalid"


class VisibilityScope(str, Enum):
    AUTHOR = "author"
    READER = "reader"
    ALL = "all"
    CHARACTER_INSTANCES = "character_instances"


class StoryTimelineRecord(_StrictModel):
    id: UUID
    novel_id: UUID
    timeline_key: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=240)
    normalized_name: str = Field(min_length=1, max_length=240)
    timeline_kind: TimelineKind
    is_primary: bool = False
    parent_timeline_id: UUID | None = None
    fork_story_sequence: int | None = Field(default=None, ge=0)
    fork_anchor_json: dict[str, JsonValue] = Field(default_factory=dict)
    lifecycle_state: LifecycleState = LifecycleState.ACTIVE
    position: int = Field(default=0, ge=0)
    version: int = Field(default=1, ge=1)
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_kind_and_parent(self) -> "StoryTimelineRecord":
        if self.parent_timeline_id == self.id:
            raise ValueError("timeline cannot inherit from itself")
        if self.is_primary and self.parent_timeline_id is not None:
            raise ValueError("primary timeline cannot have a parent")
        if self.timeline_kind is TimelineKind.MAIN and self.parent_timeline_id is not None:
            raise ValueError("main timeline cannot have a parent")
        if self.timeline_kind in {TimelineKind.BRANCH, TimelineKind.MERGE}:
            if self.parent_timeline_id is None or self.fork_story_sequence is None:
                raise ValueError("branch and merge timelines require a parent and fork anchor")
        return self


class StoryTimelineLinkRecord(_StrictModel):
    id: UUID
    novel_id: UUID
    source_timeline_id: UUID
    target_timeline_id: UUID
    link_type: TimelineLinkType
    source_story_sequence: int | None = Field(default=None, ge=0)
    target_story_sequence: int | None = Field(default=None, ge=0)
    details_json: dict[str, JsonValue] = Field(default_factory=dict)
    link_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    lifecycle_state: LifecycleState = LifecycleState.ACTIVE
    version: int = Field(default=1, ge=1)
    created_at: datetime

    @model_validator(mode="after")
    def validate_distinct_timelines(self) -> "StoryTimelineLinkRecord":
        if self.source_timeline_id == self.target_timeline_id:
            raise ValueError("timeline link endpoints must be distinct")
        return self


class CharacterInstanceRecord(_StrictModel):
    id: UUID
    novel_id: UUID
    character_id: UUID
    origin_timeline_id: UUID
    derived_from_instance_id: UUID | None = None
    continuity_kind: CharacterContinuityKind
    display_label: str = Field(default="", max_length=240)
    current_revision_id: UUID | None = None
    lifecycle_state: LifecycleState = LifecycleState.ACTIVE
    version: int = Field(default=1, ge=1)
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_continuity(self) -> "CharacterInstanceRecord":
        if self.derived_from_instance_id == self.id:
            raise ValueError("character instance cannot derive from itself")
        if (
            self.continuity_kind is CharacterContinuityKind.DERIVED
            and self.derived_from_instance_id is None
        ):
            raise ValueError("derived instance requires derived_from_instance_id")
        if (
            self.continuity_kind is CharacterContinuityKind.NATIVE
            and self.derived_from_instance_id is not None
        ):
            raise ValueError("native instance cannot have derived_from_instance_id")
        return self


class StoryTimeV1(_StrictModel):
    schema_version: Literal["story-time/1"] = "story-time/1"
    label: str | None = Field(default=None, max_length=300)
    calendar_id: str | None = Field(default=None, max_length=80)
    lower_bound: int | None = None
    upper_bound: int | None = None
    precision: Literal["exact", "range", "approximate", "unknown"] = "unknown"

    @model_validator(mode="after")
    def validate_bounds(self) -> "StoryTimeV1":
        if (
            self.lower_bound is not None
            and self.upper_bound is not None
            and self.upper_bound < self.lower_bound
        ):
            raise ValueError("story time range is reversed")
        if self.precision == "exact" and (
            self.lower_bound is None or self.lower_bound != self.upper_bound
        ):
            raise ValueError("exact story time requires equal lower and upper bounds")
        return self


class StoryVisibilityV1(_StrictModel):
    schema_version: Literal["story-visibility/1"] = "story-visibility/1"
    scope: VisibilityScope = VisibilityScope.AUTHOR
    character_instance_ids: tuple[UUID, ...] = ()
    revealed_at_sequence: int | None = Field(default=None, ge=0)

    @field_validator("character_instance_ids")
    @classmethod
    def validate_unique_instances(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(value) != len(set(value)):
            raise ValueError("character_instance_ids must not contain duplicates")
        return value

    @model_validator(mode="after")
    def validate_scope(self) -> "StoryVisibilityV1":
        if self.scope is VisibilityScope.CHARACTER_INSTANCES:
            if not self.character_instance_ids:
                raise ValueError("character visibility requires explicit instances")
        elif self.character_instance_ids:
            raise ValueError("character_instance_ids require character visibility scope")
        return self


class CharacterStateDetailsV1(_StrictModel):
    schema_version: Literal["character-state/1"] = "character-state/1"
    value: JsonValue
    previous_value: JsonValue | None = None


class RelationshipStateDetailsV1(_StrictModel):
    schema_version: Literal["relationship-state/1"] = "relationship-state/1"
    value: JsonValue
    previous_value: JsonValue | None = None


class StorylineEventDetailsV1(_StrictModel):
    schema_version: Literal["storyline-event/1"] = "storyline-event/1"
    event: str = Field(min_length=1, max_length=120)
    value: JsonValue | None = None
    status: Literal["active", "paused", "completed", "archived"] | None = None
    progress: int | None = Field(default=None, ge=0, le=100)


class ForeshadowEventDetailsV1(_StrictModel):
    schema_version: Literal["foreshadow-event/1"] = "foreshadow-event/1"
    event: Literal["plant", "reinforce", "reveal", "resolve", "cancel"]
    note: str | None = Field(default=None, max_length=2000)


class StoryTimeDetailsV1(_StrictModel):
    schema_version: Literal["story-time-event/1"] = "story-time-event/1"
    transition: Literal["advance", "flashback", "flashforward", "anchor", "unknown"]
    from_time: StoryTimeV1 | None = None
    to_time: StoryTimeV1 | None = None


class KnowledgeEventDetailsV1(_StrictModel):
    schema_version: Literal["knowledge-event/1"] = "knowledge-event/1"
    operation: Literal["learn", "forget", "believe", "doubt", "reveal"]
    knowledge_key: str = Field(min_length=1, max_length=240)


class WorldStateDetailsV1(_StrictModel):
    schema_version: Literal["world-state/1"] = "world-state/1"
    value: JsonValue
    previous_value: JsonValue | None = None


class GeneralFactDetailsV1(_StrictModel):
    schema_version: Literal["general-fact/1"] = "general-fact/1"
    value: JsonValue | None = None


FactDetailsV2 = Annotated[
    CharacterStateDetailsV1
    | RelationshipStateDetailsV1
    | StorylineEventDetailsV1
    | ForeshadowEventDetailsV1
    | StoryTimeDetailsV1
    | KnowledgeEventDetailsV1
    | WorldStateDetailsV1
    | GeneralFactDetailsV1,
    Field(discriminator="schema_version"),
]


_DETAILS_TYPE_BY_FACT_TYPE: dict[StoryFactType, type[_StrictModel]] = {
    StoryFactType.CHARACTER_STATE: CharacterStateDetailsV1,
    StoryFactType.RELATIONSHIP_STATE: RelationshipStateDetailsV1,
    StoryFactType.STORYLINE_EVENT: StorylineEventDetailsV1,
    StoryFactType.FORESHADOW_EVENT: ForeshadowEventDetailsV1,
    StoryFactType.STORY_TIME: StoryTimeDetailsV1,
    StoryFactType.KNOWLEDGE_EVENT: KnowledgeEventDetailsV1,
    StoryFactType.WORLD_STATE: WorldStateDetailsV1,
    StoryFactType.GENERAL_FACT: GeneralFactDetailsV1,
}


class StoryFactV2(_StrictModel):
    """Validated StoryFact v2 envelope aligned with ``story_facts`` columns."""

    id: UUID
    novel_id: UUID
    schema_version: Literal[STORY_FACT_SCHEMA_VERSION] = STORY_FACT_SCHEMA_VERSION
    fact_type: StoryFactType
    subject: str = Field(min_length=1, max_length=240)
    predicate: str = Field(min_length=1, max_length=240)
    object_text: str = Field(min_length=1, max_length=10_000)
    details: FactDetailsV2
    source_revision_id: UUID | None = None
    source_document_id: UUID | None = None
    timeline_id: UUID
    character_id: UUID | None = None
    character_instance_id: UUID | None = None
    relationship_id: UUID | None = None
    storyline_id: UUID | None = None
    foreshadow_id: UUID | None = None
    dimension: str = Field(min_length=1, max_length=80)
    event_kind: str = Field(min_length=1, max_length=80)
    story_sequence: int | None = Field(default=None, ge=0)
    story_time_json: StoryTimeV1 | None = None
    visibility_json: StoryVisibilityV1
    source_start: int | None = Field(default=None, ge=0)
    source_end: int | None = Field(default=None, gt=0)
    event_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: StoryFactStatus = StoryFactStatus.ACTIVE
    created_at: datetime

    @model_validator(mode="before")
    @classmethod
    def adapt_orm_json_fields(cls, value: Any) -> Any:
        """Map JSON dicts from ORM rows into the versioned nested schemas."""
        if isinstance(value, dict):
            return value
        data = {
            field_name: getattr(value, field_name)
            for field_name in cls.model_fields
            if hasattr(value, field_name)
        }
        return data

    @model_validator(mode="after")
    def validate_fact_shape(self) -> "StoryFactV2":
        expected_details_type = _DETAILS_TYPE_BY_FACT_TYPE[self.fact_type]
        if not isinstance(self.details, expected_details_type):
            raise ValueError("details schema does not match fact_type")
        if (self.source_revision_id is None) != (self.source_document_id is None):
            raise ValueError("source revision and document must be supplied together")
        if (self.source_start is None) != (self.source_end is None):
            raise ValueError("source offsets must be supplied together")
        if (
            self.source_start is not None
            and self.source_end is not None
            and self.source_end <= self.source_start
        ):
            raise ValueError("source offset range is empty or reversed")
        if self.fact_type in {
            StoryFactType.CHARACTER_STATE,
            StoryFactType.KNOWLEDGE_EVENT,
        } and (self.character_id is None or self.character_instance_id is None):
            raise ValueError("character facts require character and instance IDs")
        required_entity = {
            StoryFactType.RELATIONSHIP_STATE: self.relationship_id,
            StoryFactType.STORYLINE_EVENT: self.storyline_id,
            StoryFactType.FORESHADOW_EVENT: self.foreshadow_id,
        }.get(self.fact_type, self.id)
        if required_entity is None:
            raise ValueError("fact type requires its stable entity ID")
        return self


class StoryEventLinkRecord(_StrictModel):
    id: UUID
    novel_id: UUID
    source_fact_id: UUID
    target_fact_id: UUID
    link_type: StoryEventLinkType
    details_json: dict[str, JsonValue] = Field(default_factory=dict)
    created_at: datetime

    @model_validator(mode="after")
    def validate_distinct_facts(self) -> "StoryEventLinkRecord":
        if self.source_fact_id == self.target_fact_id:
            raise ValueError("story event link endpoints must be distinct")
        return self


class DefaultStoryStatePlan(_StrictModel):
    timeline: StoryTimelineRecord | None = None
    character_instances: tuple[CharacterInstanceRecord, ...] = ()


class TimelineForkPlan(_StrictModel):
    timeline: StoryTimelineRecord
    derived_instances: tuple[CharacterInstanceRecord, ...]
    copied_fact_count: Literal[0] = 0


class ProjectionConflict(_StrictModel):
    conflict_key: str
    fact_ids: tuple[UUID, ...] = Field(min_length=2)
    reason: Literal["same_position", "explicit_contradiction"]


class StoryProjection(_StrictModel):
    novel_id: UUID
    timeline_id: UUID
    narrative_cutoff: int | None = Field(default=None, ge=0)
    visible_facts: tuple[StoryFactV2, ...]
    current_facts: tuple[StoryFactV2, ...]
    conflicts: tuple[ProjectionConflict, ...]
    ambiguous_fact_ids: tuple[UUID, ...]
    suppressed_fact_ids: tuple[UUID, ...]
    inheritance_path: tuple[UUID, ...]
