"""Static semantic-index schema and migration contracts.

No test in this module connects to PostgreSQL or invokes a cloud endpoint.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

import backend.creative_data_models  # noqa: F401  # registers additive tables
from backend.embedding import api as embedding_api
from backend.embedding import persistence as embedding_persistence
from backend.models import Base


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "backend/migrations/versions/20260829_0028_semantic_index_schema.py"


def _table(name: str):
    return Base.metadata.tables[name]


def _constraint(table_name: str, constraint_name: str, kind: type):
    matches = [
        constraint
        for constraint in _table(table_name).constraints
        if isinstance(constraint, kind) and constraint.name == constraint_name
    ]
    assert len(matches) == 1, (
        f"{table_name} must define exactly one {kind.__name__} "
        f"named {constraint_name}"
    )
    return matches[0]


def _column_names(constraint) -> tuple[str, ...]:
    return tuple(column.name for column in constraint.columns)


def _remote_names(constraint: ForeignKeyConstraint) -> tuple[str, ...]:
    return tuple(element.target_fullname for element in constraint.elements)


def test_semantic_index_tables_are_registered() -> None:
    assert {
        "embedding_configurations",
        "embedding_profiles",
        "embedding_generations",
        "novel_embedding_consents",
        "embedding_generation_novels",
        "semantic_sources",
        "semantic_chunks",
        "embedding_index_batches",
        "embedding_index_batch_items",
        "semantic_embeddings",
    } <= set(Base.metadata.tables)


def test_configuration_stores_only_a_secret_reference_and_scoped_pointers() -> None:
    table = _table("embedding_configurations")
    assert "api_key" not in table.c
    assert {"credential_ref", "api_key_last4"} <= set(table.c.keys())

    for pointer in ("active", "candidate", "previous"):
        constraint = _constraint(
            "embedding_configurations",
            f"fk_embedding_configuration_{pointer}_generation_scope",
            ForeignKeyConstraint,
        )
        assert _column_names(constraint) == (
            f"{pointer}_generation_id",
            "owner_id",
            "workspace_id",
        )
        assert _remote_names(constraint) == (
            "embedding_generations.id",
            "embedding_generations.owner_id",
            "embedding_generations.workspace_id",
        )


def test_generation_profile_and_per_novel_progress_are_scope_guarded() -> None:
    profile = _constraint(
        "embedding_generations",
        "fk_embedding_generation_profile_scope",
        ForeignKeyConstraint,
    )
    assert _column_names(profile) == ("profile_id", "owner_id", "workspace_id")
    assert _remote_names(profile) == (
        "embedding_profiles.id",
        "embedding_profiles.owner_id",
        "embedding_profiles.workspace_id",
    )

    active = next(
        index for index in _table("embedding_generations").indexes
        if index.name == "uq_embedding_generation_active"
    )
    assert active.unique is True
    assert tuple(column.name for column in active.columns) == ("owner_id", "workspace_id")

    expected = {
        "fk_embedding_generation_novel_generation_scope": (
            ("generation_id", "owner_id", "workspace_id"),
            (
                "embedding_generations.id",
                "embedding_generations.owner_id",
                "embedding_generations.workspace_id",
            ),
        ),
        "fk_embedding_generation_novel_novel_scope": (
            ("novel_id", "owner_id", "workspace_id"),
            ("novels.id", "novels.owner_id", "novels.workspace_id"),
        ),
        "fk_embedding_generation_novel_consent_scope": (
            ("consent_id", "novel_id"),
            ("novel_embedding_consents.id", "novel_embedding_consents.novel_id"),
        ),
    }
    for name, (local, remote) in expected.items():
        constraint = _constraint(
            "embedding_generation_novels",
            name,
            ForeignKeyConstraint,
        )
        assert _column_names(constraint) == local
        assert _remote_names(constraint) == remote

    per_novel = _constraint(
        "embedding_generation_novels",
        "uq_embedding_generation_novel",
        UniqueConstraint,
    )
    assert _column_names(per_novel) == ("generation_id", "novel_id")


def test_sources_chunks_batches_and_items_cannot_cross_generation() -> None:
    expected = {
        ("semantic_sources", "fk_semantic_source_generation_novel"): (
            ("generation_id", "novel_id"),
            (
                "embedding_generation_novels.generation_id",
                "embedding_generation_novels.novel_id",
            ),
        ),
        ("semantic_chunks", "fk_semantic_chunk_source_generation"): (
            ("source_id", "generation_id"),
            ("semantic_sources.id", "semantic_sources.generation_id"),
        ),
        ("embedding_index_batches", "fk_embedding_batch_generation_novel"): (
            ("generation_id", "novel_id"),
            (
                "embedding_generation_novels.generation_id",
                "embedding_generation_novels.novel_id",
            ),
        ),
        ("embedding_index_batch_items", "fk_embedding_batch_item_batch_generation"): (
            ("batch_id", "generation_id"),
            ("embedding_index_batches.id", "embedding_index_batches.generation_id"),
        ),
        ("embedding_index_batch_items", "fk_embedding_batch_item_chunk_generation"): (
            ("chunk_id", "generation_id"),
            ("semantic_chunks.id", "semantic_chunks.generation_id"),
        ),
    }
    for (table_name, name), (local, remote) in expected.items():
        constraint = _constraint(table_name, name, ForeignKeyConstraint)
        assert _column_names(constraint) == local
        assert _remote_names(constraint) == remote

    batch_size = _constraint(
        "embedding_index_batches",
        "ck_embedding_batch_size",
        CheckConstraint,
    )
    ordinal = _constraint(
        "embedding_index_batch_items",
        "ck_embedding_batch_item_ordinal",
        CheckConstraint,
    )
    assert "item_count BETWEEN 1 AND 10" in str(batch_size.sqltext)
    assert str(ordinal.sqltext) == "ordinal BETWEEN 0 AND 9"


def test_vector_dimension_is_recorded_and_checked_without_a_mixed_typmod() -> None:
    table = _table("semantic_embeddings")
    assert isinstance(table.c.embedding.type, VECTOR)
    assert table.c.embedding.type.dim is None
    assert "dimension" in table.c

    constraint = _constraint(
        "semantic_embeddings",
        "ck_semantic_embedding_dimension",
        CheckConstraint,
    )
    assert "dimension = 2048" in str(constraint.sqltext)
    assert "vector_dims(embedding) = dimension" in str(constraint.sqltext)

    for index in table.indexes:
        assert "hnsw" not in str(index).lower()
        assert "ivfflat" not in str(index).lower()


def test_api_key_rotation_is_not_part_of_vector_space_fingerprint() -> None:
    source = inspect.getsource(embedding_persistence.create_verified_candidate)
    fingerprint_source = source.split("fingerprint = _digest(", 1)[1].split(")\n", 1)[0]
    assert '"credential_ref"' not in fingerprint_source
    assert "profile.credential_ref = configuration.credential_ref" in source


def test_embedding_product_surface_has_no_billing_or_price_api() -> None:
    paths = tuple(route.path.lower() for route in embedding_api.router.routes)
    for forbidden in ("billing", "price", "cost", "balance", "charge"):
        assert all(forbidden not in path for path in paths)


def test_semantic_index_migration_is_linear_and_registers_reusable_batches() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "20260829_0028"' in source
    assert 'down_revision = "20260829_0027"' in source
    for table_name in (
        "embedding_configurations",
        "embedding_profiles",
        "embedding_generations",
        "novel_embedding_consents",
        "embedding_generation_novels",
        "semantic_sources",
        "semantic_chunks",
        "embedding_index_batches",
        "embedding_index_batch_items",
        "semantic_embeddings",
    ):
        assert f'"{table_name}"' in source
    assert "vector_dims(embedding) = dimension" in source
    assert "item_count BETWEEN 1 AND 10" in source
    assert "ordinal BETWEEN 0 AND 9" in source
    assert "embedding.index_batch" in source
    assert "dashscope-embedding" in source
    assert "embedding-worker" in source
    for forbidden in ("from backend.models", "create_engine", "requests.", "subprocess"):
        assert forbidden not in source
