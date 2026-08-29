"""Scope-first hybrid retrieval helpers.

Filtering happens before ranking.  Callers must supply deterministic timeline
reachability and knowledge visibility calculated by story-state services.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from collections.abc import Iterable, Mapping
from typing import Literal
from uuid import UUID

from ..story_state.contracts import (
    KnowledgeEventDetailsV1,
    StoryFactStatus,
    StoryFactType,
    StoryFactV2,
)


@dataclass(frozen=True, slots=True)
class SearchScope:
    novel_id: UUID
    corpora: frozenset[str]
    reachable_timeline_ids: frozenset[UUID]
    narrative_sequence: int | None
    perspective: Literal["author", "reader", "character_instance"]
    observer_character_instance_id: UUID | None = None
    known_visibility_keys: frozenset[str] = frozenset()
    # Ordered root -> target.  Parent limits are capped at each fork anchor.
    # The empty default preserves callers that only have one linear timeline.
    timeline_sequence_limits: tuple[tuple[UUID, int | None], ...] = ()

    def __post_init__(self) -> None:
        timeline_ids = [item[0] for item in self.timeline_sequence_limits]
        if len(timeline_ids) != len(set(timeline_ids)):
            raise ValueError("timeline sequence limits must not contain duplicates")
        if self.timeline_sequence_limits and set(timeline_ids) != set(
            self.reachable_timeline_ids
        ):
            raise ValueError("timeline sequence limits must cover exact reachability")


def _timeline_cutoff(scope: SearchScope, timeline_id: UUID | None) -> int | None:
    if timeline_id is None:
        # Global planning/private sources are not narrative events. Their
        # visibility is controlled by source scope, not an invented sequence.
        return None
    if not scope.timeline_sequence_limits:
        return scope.narrative_sequence
    return dict(scope.timeline_sequence_limits)[timeline_id]


def derive_known_visibility_keys(
    facts: Iterable[StoryFactV2],
    *,
    scope: SearchScope,
    source_revision_validity: Mapping[UUID, bool] | None = None,
) -> frozenset[str]:
    """Project one observer's knowledge keys without guessing or writes.

    Only effective V2 knowledge events for the exact observer, novel,
    inheritance path and per-line cutoff are considered.  ``forget`` revokes a
    prior key.  A same-position learn/forget collision fails closed to forgotten.
    """

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
        if not isinstance(fact.details, KnowledgeEventDetailsV1):
            continue
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
        position = (
            first.timeline_id,
            first.story_sequence,
            details.knowledge_key,
        )
        same_position: list[StoryFactV2] = []
        while index < len(accepted):
            candidate = accepted[index]
            candidate_details = candidate.details
            candidate_position = (
                candidate.timeline_id,
                candidate.story_sequence,
                candidate_details.knowledge_key,
            )
            if candidate_position != position:
                break
            same_position.append(candidate)
            index += 1
        key = details.knowledge_key
        if any(item.details.operation == "forget" for item in same_position):
            known.discard(key)
        else:
            known.add(key)
    return frozenset(known)


@dataclass(frozen=True, slots=True)
class Candidate:
    chunk_id: UUID
    novel_id: UUID
    corpus: str
    source_id: UUID
    source_revision_id: UUID | None
    source_type: str
    text: str
    source_status: str
    timeline_id: UUID | None
    character_instance_id: UUID | None
    narrative_start: int | None
    narrative_end: int | None
    visibility_key: str | None


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    candidate: Candidate
    score: float
    channels: tuple[str, ...]


def candidate_is_visible(candidate: Candidate, scope: SearchScope) -> bool:
    if candidate.novel_id != scope.novel_id or candidate.corpus not in scope.corpora:
        return False
    if candidate.source_status != "current":
        return False
    if candidate.timeline_id is not None and candidate.timeline_id not in scope.reachable_timeline_ids:
        return False
    cutoff = _timeline_cutoff(scope, candidate.timeline_id)
    if cutoff is not None:
        if candidate.narrative_start is None or candidate.narrative_start > cutoff:
            return False
    if scope.perspective == "author":
        return True
    if candidate.visibility_key is None or candidate.visibility_key == "public":
        return True
    return candidate.visibility_key in scope.known_visibility_keys


def filter_candidates(
    candidates: Iterable[Candidate], scope: SearchScope
) -> tuple[Candidate, ...]:
    if scope.perspective == "character_instance" and scope.observer_character_instance_id is None:
        raise ValueError("character perspective requires an observer instance")
    return tuple(candidate for candidate in candidates if candidate_is_visible(candidate, scope))


def reciprocal_rank_fusion(
    *,
    lexical: Iterable[Candidate],
    dense: Iterable[Candidate],
    scope: SearchScope,
    top_k: int,
    per_corpus_quota: int = 4,
    rank_constant: int = 60,
) -> tuple[RankedCandidate, ...]:
    if top_k < 1 or per_corpus_quota < 1 or rank_constant < 1:
        raise ValueError("ranking limits must be positive")
    scores: dict[UUID, float] = defaultdict(float)
    channels: dict[UUID, set[str]] = defaultdict(set)
    records: dict[UUID, Candidate] = {}
    for channel, stream in (("lexical", lexical), ("dense", dense)):
        visible = filter_candidates(stream, scope)
        corpus_rank: dict[str, int] = defaultdict(int)
        for candidate in visible:
            corpus_rank[candidate.corpus] += 1
            scores[candidate.chunk_id] += 1.0 / (rank_constant + corpus_rank[candidate.corpus])
            channels[candidate.chunk_id].add(channel)
            records[candidate.chunk_id] = candidate
    ordered = sorted(
        records.values(),
        key=lambda item: (-scores[item.chunk_id], item.corpus, str(item.chunk_id)),
    )
    selected: list[RankedCandidate] = []
    corpus_counts: dict[str, int] = defaultdict(int)
    for candidate in ordered:
        if corpus_counts[candidate.corpus] >= per_corpus_quota:
            continue
        selected.append(
            RankedCandidate(
                candidate=candidate,
                score=scores[candidate.chunk_id],
                channels=tuple(sorted(channels[candidate.chunk_id])),
            )
        )
        corpus_counts[candidate.corpus] += 1
        if len(selected) == top_k:
            break
    return tuple(selected)
