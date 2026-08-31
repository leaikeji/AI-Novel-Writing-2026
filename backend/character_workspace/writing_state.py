"""Deterministic author-facing summaries built from authoritative fact views."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from datetime import UTC
from typing import Literal

from .contracts import (
    CharacterWritingState,
    FactHistorySummary,
    ProjectedFactViewV2,
    WritingStateAsOf,
    WritingStateRiskSummary,
    WritingStateSlot,
    WritingStateValue,
)


SlotKey = Literal[
    "location",
    "goal",
    "health",
    "emotion",
    "identity",
    "knowledge",
    "possession",
    "relationship",
]

_SLOT_SPECS: tuple[tuple[SlotKey, str, Literal["single", "multiple"]], ...] = (
    ("location", "位置", "single"),
    ("goal", "目标", "multiple"),
    ("health", "健康", "single"),
    ("emotion", "情绪", "single"),
    ("identity", "身份", "single"),
    ("knowledge", "已知信息", "multiple"),
    ("possession", "持有物", "multiple"),
    ("relationship", "关键关系", "multiple"),
)
_DIRECT_SLOT_KEYS = {key for key, _label, _mode in _SLOT_SPECS}
_AUDIT_ONLY_STATES = {"superseded", "batch_reverted"}


def fact_slot_key(fact: ProjectedFactViewV2) -> SlotKey | None:
    """Map only protocol fields to a writing slot; prose is never inspected."""

    if fact.dimension in {"action", "presence"}:
        return None
    if fact.fact_type == "relationship_state":
        return "relationship"
    if fact.fact_type == "knowledge_event":
        return "knowledge"
    if fact.dimension in _DIRECT_SLOT_KEYS:
        return fact.dimension  # type: ignore[return-value]
    return None


def is_state_fact(fact: ProjectedFactViewV2) -> bool:
    return fact_slot_key(fact) is not None


def fact_sort_key(fact: ProjectedFactViewV2) -> tuple[int, int, str, str]:
    created_at = fact.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    else:
        created_at = created_at.astimezone(UTC)
    return (
        int(fact.story_sequence is not None),
        fact.story_sequence if fact.story_sequence is not None else -1,
        created_at.isoformat(timespec="microseconds"),
        str(fact.id),
    )


def fact_history_summary(facts: Sequence[ProjectedFactViewV2]) -> FactHistorySummary:
    counts = Counter(fact.effective_state for fact in facts)
    return FactHistorySummary(
        total=len(facts),
        current=counts["current"],
        historical=counts["historical"],
        superseded=counts["superseded"],
        source_invalid=counts["source_invalid"],
        batch_reverted=counts["batch_reverted"],
    )


def build_writing_state(
    *,
    timeline_id,
    narrative_cutoff: int | None,
    facts: Sequence[ProjectedFactViewV2],
) -> CharacterWritingState:
    """Build slots and recent history without creating a second authority."""

    ordered = tuple(sorted(facts, key=fact_sort_key, reverse=True))
    actionable = tuple(
        fact for fact in ordered if fact.effective_state not in _AUDIT_ONLY_STATES
    )
    recent = tuple(
        fact
        for fact in actionable
        if fact.effective_state in {"current", "historical"} and fact.health == "ok"
    )[:5]
    latest_story_time = next(
        (fact.story_time for fact in recent if fact.story_time is not None), None
    )

    slots: list[WritingStateSlot] = []
    for key, label, mode in _SLOT_SPECS:
        candidates = tuple(fact for fact in actionable if fact_slot_key(fact) == key)
        current = tuple(
            fact
            for fact in candidates
            if fact.effective_state == "current" and fact.health == "ok"
        )
        has_conflict = any(fact.health == "conflict" for fact in candidates)
        has_ambiguity = any(
            fact.health == "ambiguous" or fact.effective_state == "source_invalid"
            for fact in candidates
        )

        if mode == "single" and len({fact.object_text for fact in current}) > 1:
            has_conflict = True
            current = ()
        elif mode == "single" and current:
            current = current[:1]

        if has_conflict:
            slot_health = "conflicted"
        elif has_ambiguity and not current:
            slot_health = "ambiguous"
        elif not current:
            slot_health = "missing"
        else:
            slot_health = "ok"
        slots.append(
            WritingStateSlot(
                key=key,
                label=label,
                mode=mode,
                values=tuple(
                    WritingStateValue(
                        fact_id=fact.id,
                        object_text=fact.object_text,
                        story_sequence=fact.story_sequence,
                        story_time=fact.story_time,
                        source=fact.source,
                    )
                    for fact in current
                ),
                health=slot_health,
            )
        )

    return CharacterWritingState(
        as_of=WritingStateAsOf(
            timeline_id=timeline_id,
            narrative_cutoff=narrative_cutoff,
            story_time=latest_story_time,
        ),
        slots=tuple(slots),
        recent_changes=recent,
        risk_summary=WritingStateRiskSummary(
            conflict_count=sum(fact.health == "conflict" for fact in actionable),
            # Source-invalid facts are already a dedicated actionable category.
            # Their projection health is also ambiguous, but counting both would
            # make one fact appear as two author tasks in the tab badge.
            ambiguous_count=sum(
                fact.health == "ambiguous"
                and fact.effective_state != "source_invalid"
                for fact in actionable
            ),
            invalid_source_count=sum(
                fact.effective_state == "source_invalid" for fact in actionable
            ),
        ),
        history_summary=fact_history_summary(ordered),
    )
