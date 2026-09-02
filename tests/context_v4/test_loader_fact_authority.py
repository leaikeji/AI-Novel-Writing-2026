from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

from backend import context_v4_loader
from backend.models import DerivedSourceBinding, IntelligenceCommitBatch


def _uid(value: int) -> UUID:
    return UUID(int=value)


def _fact(
    value: int,
    *,
    source_revision_id: UUID | None,
    status: str = "active",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=_uid(value),
        source_revision_id=source_revision_id,
        status=status,
    )


def _binding(
    fact_id: UUID,
    source_revision_id: UUID,
    validity_state: str,
    *,
    commit_batch_id: UUID | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        derived_entity_id=fact_id,
        source_chapter_revision_id=source_revision_id,
        validity_state=validity_state,
        commit_batch_id=commit_batch_id,
    )


def _supersedes(source_fact_id: UUID, target_fact_id: UUID) -> SimpleNamespace:
    return SimpleNamespace(
        source_fact_id=source_fact_id,
        target_fact_id=target_fact_id,
        link_type="supersedes",
    )


class _AuthoritySession:
    def __init__(self, bindings: list[SimpleNamespace], batches: list[SimpleNamespace]) -> None:
        self.bindings = bindings
        self.batches = batches
        self.loaded_entities: list[type[object]] = []

    def scalars(self, statement: object) -> list[SimpleNamespace]:
        entity = statement.column_descriptions[0].get("entity")
        self.loaded_entities.append(entity)
        if entity is DerivedSourceBinding:
            return self.bindings
        if entity is IntelligenceCommitBatch:
            return self.batches
        raise AssertionError(f"unexpected authority query: {entity}")


def test_fact_binding_validity_is_fact_specific_with_shared_revision() -> None:
    shared_revision_id = _uid(100)
    unrelated_revision_id = _uid(101)
    valid_fact = _fact(10, source_revision_id=shared_revision_id)
    invalid_sibling = _fact(11, source_revision_id=shared_revision_id)
    bindings = [
        _binding(valid_fact.id, shared_revision_id, "current"),
        _binding(valid_fact.id, unrelated_revision_id, "source_invalid"),
        _binding(invalid_sibling.id, shared_revision_id, "source_invalid"),
    ]

    included, source_validity = context_v4_loader._resolve_story_fact_rows(
        [valid_fact, invalid_sibling],
        bindings,
        {},
        [],
    )

    assert [fact.id for fact in included] == [valid_fact.id]
    assert source_validity == {shared_revision_id: True}
    assert all(source_validity.values())


def test_reverted_batch_supersedes_and_lifecycle_use_shared_resolver() -> None:
    source_revision_id = _uid(110)
    reverted_batch_id = _uid(210)
    reverted_fact = _fact(20, source_revision_id=source_revision_id)
    superseded_target = _fact(21, source_revision_id=source_revision_id)
    replacement = _fact(22, source_revision_id=source_revision_id)
    invalid_lifecycle = _fact(
        23,
        source_revision_id=source_revision_id,
        status="invalid",
    )
    facts = [reverted_fact, superseded_target, replacement, invalid_lifecycle]
    bindings = [
        _binding(
            reverted_fact.id,
            source_revision_id,
            "current",
            commit_batch_id=reverted_batch_id,
        ),
        _binding(superseded_target.id, source_revision_id, "current"),
        _binding(replacement.id, source_revision_id, "source_restored"),
        _binding(invalid_lifecycle.id, source_revision_id, "current"),
    ]

    session = _AuthoritySession(
        bindings,
        [SimpleNamespace(id=reverted_batch_id, state="reverted")],
    )
    included, source_validity = context_v4_loader._load_effective_story_fact_rows(
        session,  # type: ignore[arg-type]
        facts,
        [_supersedes(replacement.id, superseded_target.id)],
    )

    assert [fact.id for fact in included] == [replacement.id]
    assert source_validity == {source_revision_id: True}
    assert session.loaded_entities == [DerivedSourceBinding, IntelligenceCommitBatch]


def test_missing_owning_batch_fails_closed_in_context_loader() -> None:
    source_revision_id = _uid(120)
    missing_batch_id = _uid(220)
    fact = _fact(30, source_revision_id=source_revision_id)
    session = _AuthoritySession(
        [
            _binding(
                fact.id,
                source_revision_id,
                "current",
                commit_batch_id=missing_batch_id,
            )
        ],
        [],
    )

    included, source_validity = context_v4_loader._load_effective_story_fact_rows(
        session,  # type: ignore[arg-type]
        [fact],
        [],
    )

    assert included == ()
    assert source_validity == {}
    assert session.loaded_entities == [DerivedSourceBinding, IntelligenceCommitBatch]
