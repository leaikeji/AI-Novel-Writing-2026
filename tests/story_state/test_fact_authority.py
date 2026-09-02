from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from backend.story_state.effective_state import FactEffectiveState
from backend.story_state.fact_authority import resolve_fact_authority_rows


def uid(value: int) -> UUID:
    return UUID(int=value)


@dataclass(frozen=True)
class FactRow:
    id: UUID
    source_revision_id: UUID | None
    status: str = "active"
    story_sequence: int | None = 1


@dataclass(frozen=True)
class BindingRow:
    derived_entity_id: UUID
    source_chapter_revision_id: UUID
    validity_state: str = "current"
    commit_batch_id: UUID | None = None


def test_adapter_keeps_same_revision_bindings_fact_specific() -> None:
    revision_id = uid(50)
    current = FactRow(uid(1), revision_id)
    invalid = FactRow(uid(2), revision_id)

    results = resolve_fact_authority_rows(
        (current, invalid),
        bindings=(
            BindingRow(current.id, revision_id),
            BindingRow(invalid.id, revision_id, "source_superseded"),
        ),
    )

    assert results[current.id].included_in_current_projection is True
    assert results[current.id].effective_state is FactEffectiveState.HISTORICAL
    assert results[invalid.id].included_in_current_projection is False
    assert results[invalid.id].effective_state is FactEffectiveState.SOURCE_INVALID


def test_missing_owning_batch_fails_closed_but_independent_binding_does_not() -> None:
    revision_id = uid(50)
    batch_id = uid(70)
    missing_batch = FactRow(uid(1), revision_id)
    independent = FactRow(uid(2), revision_id)

    results = resolve_fact_authority_rows(
        (missing_batch, independent),
        bindings=(
            BindingRow(missing_batch.id, revision_id, commit_batch_id=batch_id),
            BindingRow(independent.id, revision_id),
        ),
        batch_states={},
    )

    assert results[missing_batch.id].included_in_current_projection is False
    assert results[missing_batch.id].effective_state is FactEffectiveState.SOURCE_INVALID
    assert results[independent.id].included_in_current_projection is True


def test_adapter_applies_reverted_batch_and_incoming_supersedes_consistently() -> None:
    revision_id = uid(50)
    batch_id = uid(70)
    reverted = FactRow(uid(1), revision_id)
    superseded = FactRow(uid(2), None)

    results = resolve_fact_authority_rows(
        (reverted, superseded),
        bindings=(
            BindingRow(reverted.id, revision_id, commit_batch_id=batch_id),
        ),
        batch_states={batch_id: "reverted"},
        incoming_superseded_fact_ids={superseded.id},
    )

    assert results[reverted.id].effective_state is FactEffectiveState.BATCH_REVERTED
    assert results[superseded.id].effective_state is FactEffectiveState.SUPERSEDED
    assert all(
        not results[fact_id].included_in_current_projection
        for fact_id in (reverted.id, superseded.id)
    )
