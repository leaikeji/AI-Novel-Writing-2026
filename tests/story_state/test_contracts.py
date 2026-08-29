from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from backend.story_state import (
    CharacterStateDetailsV1,
    GeneralFactDetailsV1,
    StoryFactType,
    StoryFactV2,
    StoryTimeV1,
    StoryVisibilityV1,
)


NOW = datetime(2026, 8, 29, tzinfo=UTC)
HEX_DIGEST = "a" * 64


def fact_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": uuid4(),
        "novel_id": uuid4(),
        "fact_type": StoryFactType.GENERAL_FACT,
        "subject": "钟楼",
        "predicate": "位置",
        "object_text": "城北",
        "details": {"schema_version": "general-fact/1", "value": "城北"},
        "timeline_id": uuid4(),
        "dimension": "location",
        "event_kind": "established",
        "story_sequence": 1,
        "visibility_json": {"schema_version": "story-visibility/1", "scope": "author"},
        "event_fingerprint": HEX_DIGEST,
        "created_at": NOW,
    }
    payload.update(overrides)
    return payload


def test_story_fact_v2_parses_versioned_details_and_orm_json_fields() -> None:
    fact = StoryFactV2.model_validate(fact_payload())
    assert fact.schema_version == "story-fact/2"
    assert isinstance(fact.details, GeneralFactDetailsV1)
    assert isinstance(fact.visibility_json, StoryVisibilityV1)

    orm_like = SimpleNamespace(**fact_payload())
    parsed = StoryFactV2.model_validate(orm_like)
    assert parsed.timeline_id == orm_like.timeline_id
    assert isinstance(parsed.details, GeneralFactDetailsV1)


def test_story_fact_type_requires_matching_versioned_schema_and_entity_ids() -> None:
    character_id = uuid4()
    instance_id = uuid4()
    fact = StoryFactV2.model_validate(
        fact_payload(
            fact_type="character_state",
            details={"schema_version": "character-state/1", "value": "警觉"},
            character_id=character_id,
            character_instance_id=instance_id,
        )
    )
    assert isinstance(fact.details, CharacterStateDetailsV1)

    with pytest.raises(ValidationError, match="details schema does not match"):
        StoryFactV2.model_validate(
            fact_payload(
                fact_type="character_state",
                details={"schema_version": "general-fact/1", "value": "警觉"},
                character_id=character_id,
                character_instance_id=instance_id,
            )
        )
    with pytest.raises(ValidationError, match="character and instance IDs"):
        StoryFactV2.model_validate(
            fact_payload(
                fact_type="knowledge_event",
                details={
                    "schema_version": "knowledge-event/1",
                    "operation": "learn",
                    "knowledge_key": "letter_owner",
                },
            )
        )
    with pytest.raises(ValidationError, match="stable entity ID"):
        StoryFactV2.model_validate(
            fact_payload(
                fact_type="relationship_state",
                details={"schema_version": "relationship-state/1", "value": "盟友"},
            )
        )


def test_story_fact_source_evidence_is_pairwise_and_bounded() -> None:
    with pytest.raises(ValidationError, match="revision and document"):
        StoryFactV2.model_validate(fact_payload(source_revision_id=uuid4()))
    with pytest.raises(ValidationError, match="offsets must be supplied together"):
        StoryFactV2.model_validate(fact_payload(source_start=0))
    with pytest.raises(ValidationError, match="empty or reversed"):
        StoryFactV2.model_validate(fact_payload(source_start=5, source_end=5))


def test_story_time_does_not_invent_precision() -> None:
    assert StoryTimeV1().precision == "unknown"
    exact = StoryTimeV1(precision="exact", lower_bound=42, upper_bound=42)
    assert exact.lower_bound == 42
    with pytest.raises(ValidationError):
        StoryTimeV1(precision="exact", lower_bound=41, upper_bound=42)
    with pytest.raises(ValidationError):
        StoryTimeV1(lower_bound=42, upper_bound=41)


def test_story_fact_contract_forbids_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        StoryFactV2.model_validate(fact_payload(guessed_character_name="不能按名称绑定"))
