from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from backend.embedding.contracts import EmbeddingCorpus
from backend.embedding.retrieval import (
    ADJACENT_NEIGHBORS_GLOBAL_CAP,
    ADJACENT_NEIGHBORS_PER_HIT_CAP,
    DENSE_CANDIDATE_CAP,
    FINAL_HIT_CAP,
    LEXICAL_CANDIDATE_CAP,
    RetrievalPerspective,
    RetrievalPolicyV1,
    RetrievalPurpose,
    SearchScope,
    SemanticSearchRequestV2,
    TimelineSearchLimit,
    writing_retrieval_policy_v3,
)


def uid(value: int) -> UUID:
    return UUID(int=value)


def scope(**overrides) -> SearchScope:
    payload = {
        "owner_id": uid(1),
        "workspace_id": uid(2),
        "novel_id": uid(3),
        "generation_id": uid(4),
        "index_version": 7,
        "corpora": frozenset(
            {
                EmbeddingCorpus.MANUSCRIPT,
                EmbeddingCorpus.PLANNING,
                EmbeddingCorpus.PRIVATE_ASSET,
            }
        ),
        "target_timeline_id": uid(10),
        "narrative_sequence_cutoff": 5,
        "story_sequence_cutoff": 30,
        "timeline_limits": (
            TimelineSearchLimit(timeline_id=uid(9), story_sequence_cutoff=12),
            TimelineSearchLimit(timeline_id=uid(10), story_sequence_cutoff=30),
        ),
        "knowledge_keys": frozenset({"identity:linlan"}),
    }
    payload.update(overrides)
    return SearchScope(**payload)


def test_purpose_enum_has_only_approved_automatic_and_custom_operations() -> None:
    assert {item.value for item in RetrievalPurpose} == {
        "chapter_body",
        "chapter_outline",
        "chapter_review",
        "selection_rewrite",
        "expand",
        "dialogue",
        "review",
        "custom",
    }
    with pytest.raises(ValueError):
        RetrievalPurpose("polish")
    with pytest.raises(ValueError):
        RetrievalPurpose("shorten")


def test_custom_requires_explicit_novel_context_opt_in() -> None:
    with pytest.raises(ValidationError, match="explicit use_novel_context"):
        SemanticSearchRequestV2(
            query="人物为何隐瞒身份？",
            purpose=RetrievalPurpose.CUSTOM,
            use_novel_context=False,
            scope=scope(),
        )
    request = SemanticSearchRequestV2(
        query="人物为何隐瞒身份？",
        purpose=RetrievalPurpose.CUSTOM,
        use_novel_context=True,
        scope=scope(),
    )
    assert request.use_novel_context is True


def test_search_scope_keeps_both_coordinates_timeline_limits_and_knowledge() -> None:
    value = scope(
        perspective=RetrievalPerspective.CHARACTER_INSTANCE,
        observer_character_instance_id=uid(20),
    )
    assert value.narrative_sequence_cutoff == 5
    assert value.story_sequence_cutoff == 30
    assert dict(
        (item.timeline_id, item.story_sequence_cutoff)
        for item in value.timeline_limits
    ) == {uid(9): 12, uid(10): 30}
    assert value.knowledge_keys == frozenset({"identity:linlan"})


def test_search_scope_fails_closed_for_invalid_timeline_or_observer() -> None:
    with pytest.raises(ValidationError, match="target timeline"):
        scope(target_timeline_id=uid(99))
    with pytest.raises(ValidationError, match="cannot exceed global"):
        scope(
            timeline_limits=(
                TimelineSearchLimit(timeline_id=uid(10), story_sequence_cutoff=31),
            )
        )
    with pytest.raises(ValidationError, match="observer instance"):
        scope(perspective=RetrievalPerspective.CHARACTER_INSTANCE)


def test_eight_second_dense_budget_is_a_frozen_policy_field() -> None:
    policy = RetrievalPolicyV1()
    assert policy.dense_timeout_seconds == 8
    with pytest.raises(ValidationError):
        RetrievalPolicyV1(dense_timeout_seconds=5)


def test_writing_retrieval_v3_has_frozen_scale_budgets() -> None:
    policy = writing_retrieval_policy_v3()

    assert policy.policy_version == "writing-retrieval/3"
    assert (DENSE_CANDIDATE_CAP, LEXICAL_CANDIDATE_CAP) == (80, 80)
    assert policy.max_results == FINAL_HIT_CAP == 10
    assert (
        policy.max_adjacent_neighbors_per_hit
        == ADJACENT_NEIGHBORS_PER_HIT_CAP
        == 2
    )
    assert policy.max_adjacent_neighbors_total == ADJACENT_NEIGHBORS_GLOBAL_CAP == 20
