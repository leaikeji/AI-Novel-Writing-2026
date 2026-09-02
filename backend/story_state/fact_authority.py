"""Shared, I/O-free assembly for fact authority evidence.

Database-facing consumers intentionally own their query shape, but they must
not each reimplement how bindings, commit batches and supersedes links are
combined for one fact.  This adapter accepts already-loaded rows and delegates
the frozen precedence rules to :mod:`effective_state`.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence, Set
from typing import Any, Protocol, TypeVar
from uuid import UUID

from .effective_state import (
    FactEffectiveStateEvidence,
    FactEffectiveStateResult,
    FactProjectionEvidence,
    FactSourceBindingEvidence,
    resolve_fact_effective_state,
)


class FactAuthorityRow(Protocol):
    id: UUID
    source_revision_id: UUID | None
    status: Any
    story_sequence: int | None


class FactAuthorityBindingRow(Protocol):
    derived_entity_id: UUID
    source_chapter_revision_id: UUID
    validity_state: str
    commit_batch_id: UUID | None


FactRowT = TypeVar("FactRowT", bound=FactAuthorityRow)


def resolve_fact_authority_rows(
    facts: Sequence[FactRowT],
    *,
    bindings: Iterable[FactAuthorityBindingRow] = (),
    batch_states: Mapping[UUID, str] | None = None,
    incoming_superseded_fact_ids: Set[UUID] = frozenset(),
    projection_by_fact_id: Mapping[UUID, FactProjectionEvidence] | None = None,
) -> dict[UUID, FactEffectiveStateResult]:
    """Resolve already-loaded rows with one shared evidence assembly rule.

    ``commit_batch_id is None`` denotes provenance independent of an
    intelligence batch.  A non-null reference missing from ``batch_states``
    is corrupt/incomplete evidence and therefore fails closed; it must never
    be mistaken for independent provenance.
    """

    observed_batch_states = batch_states or {}
    bindings_by_fact: dict[UUID, list[FactSourceBindingEvidence]] = defaultdict(list)
    fact_ids = {fact.id for fact in facts}
    for binding in bindings:
        if binding.derived_entity_id not in fact_ids:
            continue
        batch_state: str | None = None
        validity_state = binding.validity_state
        if binding.commit_batch_id is not None:
            batch_state = observed_batch_states.get(binding.commit_batch_id)
            if batch_state is None:
                validity_state = "missing_commit_batch"
                batch_state = "missing"
        bindings_by_fact[binding.derived_entity_id].append(
            FactSourceBindingEvidence(
                fact_id=binding.derived_entity_id,
                source_revision_id=binding.source_chapter_revision_id,
                validity_state=validity_state,
                commit_batch_state=batch_state,
            )
        )

    projections = projection_by_fact_id or {}
    return {
        fact.id: resolve_fact_effective_state(
            FactEffectiveStateEvidence(
                fact_id=fact.id,
                lifecycle_status=fact.status,
                source_revision_id=fact.source_revision_id,
                bindings=tuple(bindings_by_fact.get(fact.id, ())),
                has_incoming_supersedes=(
                    fact.id in incoming_superseded_fact_ids
                ),
                projection=projections.get(
                    fact.id,
                    FactProjectionEvidence(
                        story_sequence=getattr(fact, "story_sequence", None),
                        story_sequence_required=False,
                        selected_as_current=False,
                    ),
                ),
            )
        )
        for fact in facts
    }


__all__ = [
    "FactAuthorityBindingRow",
    "FactAuthorityRow",
    "resolve_fact_authority_rows",
]
