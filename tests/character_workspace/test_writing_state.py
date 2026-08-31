from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from backend.character_workspace.contracts import ProjectedFactViewV2
from backend.character_workspace.writing_state import build_writing_state


NOW = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)


def fact(
    *,
    timeline_id: UUID,
    dimension: str,
    value: str,
    sequence: int | None,
    fact_type: str = "character_state",
    effective_state: str = "current",
    health: str = "ok",
    created_offset: int = 0,
) -> ProjectedFactViewV2:
    return ProjectedFactViewV2(
        id=uuid4(),
        fact_type=fact_type,
        timeline_id=timeline_id,
        character_id=uuid4(),
        character_instance_id=uuid4(),
        dimension=dimension,
        event_kind="updated",
        predicate=dimension,
        object_text=value,
        details={"schema_version": "character-state/1", "value": value},
        story_sequence=sequence,
        source_revision_id=None,
        source_document_id=None,
        story_time=None,
        created_at=NOW + timedelta(seconds=created_offset),
        effective_state=effective_state,
        health=health,
        source=None,
    )


def test_summary_separates_single_multi_event_and_unknown_dimensions() -> None:
    timeline_id = uuid4()
    facts = (
        fact(timeline_id=timeline_id, dimension="location", value="旧港", sequence=3),
        fact(timeline_id=timeline_id, dimension="goal", value="找到证人", sequence=4),
        fact(timeline_id=timeline_id, dimension="goal", value="隐藏身份", sequence=5),
        fact(
            timeline_id=timeline_id,
            dimension="action",
            value="潜入仓库",
            sequence=6,
            effective_state="historical",
        ),
        fact(
            timeline_id=timeline_id,
            dimension="weather_signal",
            value="风暴将至",
            sequence=7,
            effective_state="historical",
        ),
    )

    summary = build_writing_state(
        timeline_id=timeline_id,
        narrative_cutoff=9,
        facts=facts,
    )

    slots = {slot.key: slot for slot in summary.slots}
    assert [value.object_text for value in slots["location"].values] == ["旧港"]
    assert [value.object_text for value in slots["goal"].values] == [
        "隐藏身份",
        "找到证人",
    ]
    assert slots["health"].health == "missing"
    assert all(slot.key not in {"action", "weather_signal"} for slot in summary.slots)
    assert [item.object_text for item in summary.recent_changes] == [
        "风暴将至",
        "潜入仓库",
        "隐藏身份",
        "找到证人",
        "旧港",
    ]
    assert summary.history_summary.current == 3
    assert summary.history_summary.historical == 2


def test_conflict_ambiguity_and_invalid_source_are_orthogonal_risks() -> None:
    timeline_id = uuid4()
    facts = (
        fact(
            timeline_id=timeline_id,
            dimension="location",
            value="旧港",
            sequence=3,
            effective_state="historical",
            health="conflict",
        ),
        fact(
            timeline_id=timeline_id,
            dimension="emotion",
            value="警惕",
            sequence=None,
            effective_state="historical",
            health="ambiguous",
        ),
        fact(
            timeline_id=timeline_id,
            dimension="identity",
            value="守门人",
            sequence=2,
            effective_state="source_invalid",
            health="ambiguous",
        ),
        fact(
            timeline_id=timeline_id,
            dimension="goal",
            value="旧目标",
            sequence=1,
            effective_state="batch_reverted",
            health="conflict",
        ),
    )

    summary = build_writing_state(
        timeline_id=timeline_id,
        narrative_cutoff=None,
        facts=facts,
    )

    slots = {slot.key: slot for slot in summary.slots}
    assert slots["location"].health == "conflicted"
    assert slots["emotion"].health == "ambiguous"
    assert slots["identity"].health == "ambiguous"
    assert summary.risk_summary.model_dump() == {
        "conflict_count": 1,
        "ambiguous_count": 1,
        "invalid_source_count": 1,
    }
    assert summary.history_summary.batch_reverted == 1
    assert summary.recent_changes == ()


def test_single_value_slot_never_guesses_between_distinct_current_values() -> None:
    timeline_id = uuid4()
    summary = build_writing_state(
        timeline_id=timeline_id,
        narrative_cutoff=None,
        facts=(
            fact(timeline_id=timeline_id, dimension="location", value="旧港", sequence=4),
            fact(timeline_id=timeline_id, dimension="location", value="灯塔", sequence=4),
        ),
    )

    location = next(slot for slot in summary.slots if slot.key == "location")
    assert location.health == "conflicted"
    assert location.values == ()
