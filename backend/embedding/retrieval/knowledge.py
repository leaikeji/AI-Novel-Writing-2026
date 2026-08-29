"""Read-only knowledge projection used by retrieval scope construction."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from ...story_state.contracts import (
    KnowledgeEventDetailsV1,
    StoryFactStatus,
    StoryFactType,
    StoryFactV2,
)


@dataclass(frozen=True, slots=True)
class KnowledgeProjectionScope:
    novel_id: UUID
    reachable_timeline_ids: frozenset[UUID]
    perspective: Literal["author", "reader", "character_instance"]
    story_sequence_cutoff: int | None = None
    observer_character_instance_id: UUID | None = None
    timeline_sequence_limits: tuple[tuple[UUID, int | None], ...] = ()

    def __post_init__(self) -> None:
        timeline_ids = tuple(item[0] for item in self.timeline_sequence_limits)
        if len(timeline_ids) != len(set(timeline_ids)):
            raise ValueError("timeline sequence limits must not contain duplicates")
        if self.timeline_sequence_limits and set(timeline_ids) != set(
            self.reachable_timeline_ids
        ):
            raise ValueError("timeline sequence limits must cover exact reachability")


def _timeline_cutoff(
    scope: KnowledgeProjectionScope, timeline_id: UUID | None
) -> int | None:
    if timeline_id is None:
        return None
    if not scope.timeline_sequence_limits:
        return scope.story_sequence_cutoff
    return dict(scope.timeline_sequence_limits)[timeline_id]


def derive_known_visibility_keys(
    facts: Iterable[StoryFactV2],
    *,
    scope: KnowledgeProjectionScope,
    source_revision_validity: Mapping[UUID, bool] | None = None,
) -> frozenset[str]:
    """Project one observer's currently known visibility keys, failing closed."""

    if scope.perspective != "character_instance":
        return frozenset()
    observer_id = scope.observer_character_instance_id
    if observer_id is None:
        raise ValueError("character perspective requires an observer instance")
    validity = source_revision_validity or {}
    timeline_rank = {
        timeline_id: index
        for index, (timeline_id, _) in enumerate(scope.timeline_sequence_limits)
    }
    accepted: list[StoryFactV2] = []
    for fact in facts:
        if (
            fact.novel_id != scope.novel_id
            or fact.fact_type is not StoryFactType.KNOWLEDGE_EVENT
            or fact.character_instance_id != observer_id
            or fact.timeline_id not in scope.reachable_timeline_ids
            or fact.status
            not in {StoryFactStatus.ACTIVE, StoryFactStatus.SOURCE_RESTORED}
        ):
            continue
        if fact.source_revision_id is not None and (
            validity.get(fact.source_revision_id) is not True
        ):
            continue
        cutoff = _timeline_cutoff(scope, fact.timeline_id)
        if cutoff is not None and (
            fact.story_sequence is None or fact.story_sequence > cutoff
        ):
            continue
        if isinstance(fact.details, KnowledgeEventDetailsV1):
            accepted.append(fact)

    accepted.sort(
        key=lambda fact: (
            timeline_rank.get(fact.timeline_id, 0),
            fact.story_sequence if fact.story_sequence is not None else -1,
            fact.details.knowledge_key,
            fact.created_at,
            str(fact.id),
        )
    )
    known: set[str] = set()
    index = 0
    while index < len(accepted):
        first = accepted[index]
        details = first.details
        position = (first.timeline_id, first.story_sequence, details.knowledge_key)
        same_position: list[StoryFactV2] = []
        while index < len(accepted):
            candidate = accepted[index]
            candidate_details = candidate.details
            if (
                candidate.timeline_id,
                candidate.story_sequence,
                candidate_details.knowledge_key,
            ) != position:
                break
            same_position.append(candidate)
            index += 1
        if any(item.details.operation == "forget" for item in same_position):
            known.discard(details.knowledge_key)
        else:
            known.add(details.knowledge_key)
    return frozenset(known)
