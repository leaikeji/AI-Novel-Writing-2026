from __future__ import annotations

from uuid import UUID

import pytest

from backend.story_state.contracts import StoryFactStatus
from backend.story_state.effective_state import (
    FactEffectiveReasonCode,
    FactEffectiveState,
    FactEffectiveStateEvidence,
    FactEffectiveStateResult,
    FactHealth,
    FactHealthEvidence,
    FactHealthReasonCode,
    FactProjectionEvidence,
    FactSourceBindingEvidence,
    classify_fact_health,
    resolve_fact_effective_state,
)


FACT_ID = UUID(int=1)
OTHER_FACT_ID = UUID(int=2)
SOURCE_REVISION_ID = UUID(int=10)
OTHER_REVISION_ID = UUID(int=11)


def projection(**overrides: object) -> FactProjectionEvidence:
    values: dict[str, object] = {
        "timeline_in_scope": True,
        "story_sequence": 5,
        "story_sequence_required": True,
        "selected_as_current": True,
        "is_state_fact": True,
    }
    values.update(overrides)
    return FactProjectionEvidence(**values)  # type: ignore[arg-type]


def binding(
    *,
    fact_id: UUID = FACT_ID,
    source_revision_id: UUID = SOURCE_REVISION_ID,
    validity_state: str = "current",
    commit_batch_state: str | None = None,
) -> FactSourceBindingEvidence:
    return FactSourceBindingEvidence(
        fact_id=fact_id,
        source_revision_id=source_revision_id,
        validity_state=validity_state,
        commit_batch_state=commit_batch_state,
    )


def effective(
    *,
    lifecycle_status: StoryFactStatus | str = StoryFactStatus.ACTIVE,
    source_revision_id: UUID | None = SOURCE_REVISION_ID,
    bindings: tuple[FactSourceBindingEvidence, ...] | None = None,
    has_incoming_supersedes: bool = False,
    projection_evidence: FactProjectionEvidence | None = None,
) -> FactEffectiveStateResult:
    if bindings is None:
        bindings = (binding(),) if source_revision_id is not None else ()
    return resolve_fact_effective_state(
        FactEffectiveStateEvidence(
            fact_id=FACT_ID,
            lifecycle_status=lifecycle_status,
            source_revision_id=source_revision_id,
            bindings=bindings,
            has_incoming_supersedes=has_incoming_supersedes,
            projection=projection_evidence or projection(),
        )
    )


@pytest.mark.parametrize(
    ("lifecycle_status", "expected_state", "expected_reason"),
    [
        (
            StoryFactStatus.ACTIVE,
            FactEffectiveState.CURRENT,
            FactEffectiveReasonCode.PROJECTION_CURRENT,
        ),
        (
            StoryFactStatus.SOURCE_RESTORED,
            FactEffectiveState.CURRENT,
            FactEffectiveReasonCode.PROJECTION_CURRENT,
        ),
        (
            StoryFactStatus.SUPERSEDED,
            FactEffectiveState.SUPERSEDED,
            FactEffectiveReasonCode.FACT_STATUS_SUPERSEDED,
        ),
        (
            StoryFactStatus.INVALID,
            FactEffectiveState.SOURCE_INVALID,
            FactEffectiveReasonCode.FACT_STATUS_INVALID,
        ),
        (
            StoryFactStatus.SOURCE_SUPERSEDED,
            FactEffectiveState.SOURCE_INVALID,
            FactEffectiveReasonCode.FACT_STATUS_INVALID,
        ),
    ],
)
def test_lifecycle_matrix_has_frozen_priority(
    lifecycle_status: StoryFactStatus,
    expected_state: FactEffectiveState,
    expected_reason: FactEffectiveReasonCode,
) -> None:
    result = effective(lifecycle_status=lifecycle_status)

    assert result.effective_state is expected_state
    assert expected_reason in result.reason_codes
    assert result.included_in_current_projection is (
        expected_state is FactEffectiveState.CURRENT
    )


@pytest.mark.parametrize(
    ("bindings", "expected_reason"),
    [
        ((), FactEffectiveReasonCode.SOURCE_BINDING_MISSING),
        (
            (binding(validity_state="source_superseded"),),
            FactEffectiveReasonCode.SOURCE_BINDING_INVALID,
        ),
        (
            (binding(validity_state="invalid"),),
            FactEffectiveReasonCode.SOURCE_BINDING_INVALID,
        ),
        (
            (binding(source_revision_id=OTHER_REVISION_ID),),
            FactEffectiveReasonCode.SOURCE_BINDING_MISSING,
        ),
        (
            (
                binding(validity_state="source_superseded"),
                binding(
                    source_revision_id=OTHER_REVISION_ID,
                    validity_state="current",
                ),
            ),
            FactEffectiveReasonCode.SOURCE_BINDING_INVALID,
        ),
    ],
)
def test_missing_or_invalid_matching_binding_fails_closed(
    bindings: tuple[FactSourceBindingEvidence, ...],
    expected_reason: FactEffectiveReasonCode,
) -> None:
    result = effective(bindings=bindings)

    assert result.included_in_current_projection is False
    assert result.effective_state is FactEffectiveState.SOURCE_INVALID
    assert result.reason_codes == (expected_reason,)


@pytest.mark.parametrize("validity_state", ["current", "source_restored"])
def test_current_and_restored_matching_bindings_are_valid(
    validity_state: str,
) -> None:
    result = effective(bindings=(binding(validity_state=validity_state),))

    assert result.included_in_current_projection is True
    assert result.effective_state is FactEffectiveState.CURRENT
    assert result.reason_codes == (FactEffectiveReasonCode.PROJECTION_CURRENT,)


def test_binding_is_filtered_by_fact_and_revision_together() -> None:
    result = effective(
        bindings=(
            binding(fact_id=OTHER_FACT_ID, validity_state="source_superseded"),
            binding(
                source_revision_id=OTHER_REVISION_ID,
                validity_state="source_superseded",
            ),
            binding(),
        )
    )

    assert result.included_in_current_projection is True
    assert result.effective_state is FactEffectiveState.CURRENT


def test_source_free_fact_does_not_require_a_binding() -> None:
    result = effective(source_revision_id=None, bindings=())

    assert result.included_in_current_projection is True
    assert result.effective_state is FactEffectiveState.CURRENT
    assert result.reason_codes == (
        FactEffectiveReasonCode.SOURCE_NOT_APPLICABLE,
        FactEffectiveReasonCode.PROJECTION_CURRENT,
    )


def test_reverted_owning_batch_wins_over_supersedes_and_lifecycle() -> None:
    result = effective(
        lifecycle_status=StoryFactStatus.SUPERSEDED,
        bindings=(binding(commit_batch_state="reverted"),),
        has_incoming_supersedes=True,
    )

    assert result.included_in_current_projection is False
    assert result.effective_state is FactEffectiveState.BATCH_REVERTED
    assert result.reason_codes == (FactEffectiveReasonCode.BATCH_REVERTED,)


@pytest.mark.parametrize("non_reverted_batch_state", [None, "committed"])
def test_valid_provenance_independent_of_reverted_batch_keeps_fact_eligible(
    non_reverted_batch_state: str | None,
) -> None:
    result = effective(
        bindings=(
            binding(commit_batch_state="reverted"),
            binding(
                commit_batch_state=non_reverted_batch_state,
                validity_state="source_restored",
            ),
        )
    )

    assert result.included_in_current_projection is True
    assert result.effective_state is FactEffectiveState.CURRENT


def test_other_revision_provenance_does_not_revive_reverted_owning_binding() -> None:
    result = effective(
        bindings=(
            binding(commit_batch_state="reverted"),
            binding(
                source_revision_id=OTHER_REVISION_ID,
                commit_batch_state="committed",
            ),
        )
    )

    assert result.included_in_current_projection is False
    assert result.effective_state is FactEffectiveState.BATCH_REVERTED


def test_supersedes_link_and_lifecycle_reasons_are_both_preserved() -> None:
    result = effective(
        lifecycle_status=StoryFactStatus.SUPERSEDED,
        has_incoming_supersedes=True,
    )

    assert result.effective_state is FactEffectiveState.SUPERSEDED
    assert result.reason_codes == (
        FactEffectiveReasonCode.SUPERSEDED_BY_FACT,
        FactEffectiveReasonCode.FACT_STATUS_SUPERSEDED,
    )


@pytest.mark.parametrize(
    "lifecycle_status",
    [StoryFactStatus.ACTIVE, StoryFactStatus.SOURCE_SUPERSEDED],
)
def test_incoming_supersedes_precedes_source_invalidity(
    lifecycle_status: StoryFactStatus,
) -> None:
    result = effective(
        lifecycle_status=lifecycle_status,
        has_incoming_supersedes=True,
    )

    assert result.included_in_current_projection is False
    assert result.effective_state is FactEffectiveState.SUPERSEDED
    assert result.reason_codes == (FactEffectiveReasonCode.SUPERSEDED_BY_FACT,)


@pytest.mark.parametrize(
    ("projection_evidence", "included", "state", "reason"),
    [
        (
            projection(timeline_in_scope=False),
            False,
            FactEffectiveState.HISTORICAL,
            FactEffectiveReasonCode.TIMELINE_OUT_OF_SCOPE,
        ),
        (
            projection(narrative_cutoff=4),
            False,
            FactEffectiveState.HISTORICAL,
            FactEffectiveReasonCode.AFTER_NARRATIVE_CUTOFF,
        ),
        (
            projection(narrative_cutoff=5),
            True,
            FactEffectiveState.CURRENT,
            FactEffectiveReasonCode.PROJECTION_CURRENT,
        ),
        (
            projection(selected_as_current=False),
            True,
            FactEffectiveState.HISTORICAL,
            FactEffectiveReasonCode.PROJECTION_HISTORICAL,
        ),
        (
            projection(is_state_fact=False, selected_as_current=False),
            True,
            FactEffectiveState.HISTORICAL,
            FactEffectiveReasonCode.NON_STATE_EVENT,
        ),
        (
            projection(story_sequence=None),
            False,
            FactEffectiveState.HISTORICAL,
            FactEffectiveReasonCode.PROJECTION_HISTORICAL,
        ),
        (
            projection(story_sequence=None, narrative_cutoff=5),
            False,
            FactEffectiveState.HISTORICAL,
            FactEffectiveReasonCode.PROJECTION_HISTORICAL,
        ),
    ],
)
def test_projection_matrix_preserves_inclusion_separately_from_display_state(
    projection_evidence: FactProjectionEvidence,
    included: bool,
    state: FactEffectiveState,
    reason: FactEffectiveReasonCode,
) -> None:
    result = effective(projection_evidence=projection_evidence)

    assert result.included_in_current_projection is included
    assert result.effective_state is state
    assert result.reason_codes == (reason,)


@pytest.mark.parametrize("field", ["narrative_cutoff", "story_sequence"])
def test_projection_rejects_negative_sequence_values(field: str) -> None:
    with pytest.raises(ValueError, match="must be non-negative"):
        FactProjectionEvidence(**{field: -1})


def test_unknown_fact_lifecycle_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported StoryFact lifecycle"):
        effective(lifecycle_status="deleted")


@pytest.mark.parametrize(
    ("evidence", "expected_health", "expected_reasons"),
    [
        (FactHealthEvidence(), FactHealth.OK, ()),
        (
            FactHealthEvidence(explicit_contradiction=True),
            FactHealth.CONFLICT,
            (FactHealthReasonCode.EXPLICIT_CONTRADICTION,),
        ),
        (
            FactHealthEvidence(same_position_conflict=True),
            FactHealth.CONFLICT,
            (FactHealthReasonCode.SAME_POSITION_CONFLICT,),
        ),
        (
            FactHealthEvidence(source_reference_incomplete=True),
            FactHealth.AMBIGUOUS,
            (FactHealthReasonCode.SOURCE_REFERENCE_INCOMPLETE,),
        ),
        (
            FactHealthEvidence(source_hash_mismatch=True),
            FactHealth.AMBIGUOUS,
            (FactHealthReasonCode.SOURCE_HASH_MISMATCH,),
        ),
        (
            FactHealthEvidence(source_coordinate_invalid=True),
            FactHealth.AMBIGUOUS,
            (FactHealthReasonCode.SOURCE_COORDINATE_INVALID,),
        ),
        (
            FactHealthEvidence(
                projection=projection(story_sequence=None),
            ),
            FactHealth.AMBIGUOUS,
            (FactHealthReasonCode.STORY_SEQUENCE_AMBIGUOUS,),
        ),
        (
            FactHealthEvidence(entity_reference_missing=True),
            FactHealth.AMBIGUOUS,
            (FactHealthReasonCode.ENTITY_REFERENCE_MISSING,),
        ),
    ],
)
def test_health_matrix_uses_frozen_reason_codes(
    evidence: FactHealthEvidence,
    expected_health: FactHealth,
    expected_reasons: tuple[FactHealthReasonCode, ...],
) -> None:
    result = classify_fact_health(evidence)

    assert result.health is expected_health
    assert result.reason_codes == expected_reasons


def test_conflict_wins_over_ambiguity_but_preserves_every_reason() -> None:
    result = classify_fact_health(
        FactHealthEvidence(
            explicit_contradiction=True,
            same_position_conflict=True,
            source_reference_incomplete=True,
            source_hash_mismatch=True,
            source_coordinate_invalid=True,
            entity_reference_missing=True,
            projection=projection(story_sequence=None),
        )
    )

    assert result.health is FactHealth.CONFLICT
    assert result.reason_codes == tuple(FactHealthReasonCode)


@pytest.mark.parametrize(
    ("effective_result", "health_evidence", "state", "health"),
    [
        (
            effective(),
            FactHealthEvidence(explicit_contradiction=True),
            FactEffectiveState.CURRENT,
            FactHealth.CONFLICT,
        ),
        (
            effective(projection_evidence=projection(selected_as_current=False)),
            FactHealthEvidence(source_hash_mismatch=True),
            FactEffectiveState.HISTORICAL,
            FactHealth.AMBIGUOUS,
        ),
        (
            effective(bindings=()),
            FactHealthEvidence(explicit_contradiction=True),
            FactEffectiveState.SOURCE_INVALID,
            FactHealth.CONFLICT,
        ),
    ],
)
def test_effective_state_and_health_remain_orthogonal(
    effective_result,
    health_evidence: FactHealthEvidence,
    state: FactEffectiveState,
    health: FactHealth,
) -> None:
    health_result = classify_fact_health(health_evidence)

    assert effective_result.effective_state is state
    assert health_result.health is health
