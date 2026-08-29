"""Static contracts for the additive creative-authority schema.

These tests inspect SQLAlchemy metadata and Alembic source only.  They must
never connect to a database or execute a migration.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import ForeignKeyConstraint, UniqueConstraint

import backend.creative_data_models  # noqa: F401  # registers additive tables
from backend.models import Base


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "backend/migrations/versions/20260829_0025_creative_authority.py"


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


def test_authority_tables_and_legacy_catalog_version_are_registered() -> None:
    assert {
        "novel_outline_revisions",
        "novel_outline_heads",
        "novel_setting_revisions",
        "novel_setting_heads",
        "novel_character_revisions",
    } <= set(Base.metadata.tables)
    assert "character_catalog_version" in _table("novels").c
    assert not _table("novels").c.character_catalog_version.nullable


def test_outline_and_setting_heads_point_to_same_novel_revisions() -> None:
    for domain in ("outline", "setting"):
        head = f"novel_{domain}_heads"
        revision = f"novel_{domain}_revisions"
        expected_target = (f"{revision}.id", f"{revision}.novel_id")

        current = _constraint(
            head,
            f"fk_{domain}_head_current_scope",
            ForeignKeyConstraint,
        )
        assert _column_names(current) == ("current_revision_id", "novel_id")
        assert _remote_names(current) == expected_target
        assert current.deferrable is True
        assert current.initially == "DEFERRED"

        for relation in ("parent", "restore"):
            parent = _constraint(
                revision,
                f"fk_{domain}_revision_{relation}_scope",
                ForeignKeyConstraint,
            )
            local_prefix = (
                "parent_revision_id" if relation == "parent" else "restored_from_revision_id"
            )
            assert _column_names(parent) == (local_prefix, "novel_id")
            assert _remote_names(parent) == expected_target


def test_outline_and_setting_revisions_have_monotonic_and_idempotent_keys() -> None:
    for domain in ("outline", "setting"):
        table_name = f"novel_{domain}_revisions"
        number = _constraint(
            table_name,
            f"uq_{domain}_revision_number",
            UniqueConstraint,
        )
        idempotency = _constraint(
            table_name,
            f"uq_{domain}_revision_idempotency",
            UniqueConstraint,
        )
        scope = _constraint(
            table_name,
            f"uq_{domain}_revision_novel_scope",
            UniqueConstraint,
        )
        assert _column_names(number) == ("novel_id", "revision_number")
        assert _column_names(idempotency) == ("novel_id", "idempotency_key")
        assert _column_names(scope) == ("id", "novel_id")


def test_character_revision_chain_is_scoped_to_root_and_novel() -> None:
    root = _constraint(
        "novel_character_revisions",
        "fk_character_revision_root_scope",
        ForeignKeyConstraint,
    )
    assert _column_names(root) == ("character_id", "novel_id")
    assert _remote_names(root) == (
        "novel_characters.id",
        "novel_characters.novel_id",
    )

    for relation, local in (
        ("parent", "parent_revision_id"),
        ("restore", "restored_from_revision_id"),
    ):
        constraint = _constraint(
            "novel_character_revisions",
            f"fk_character_revision_{relation}_scope",
            ForeignKeyConstraint,
        )
        assert _column_names(constraint) == (local, "character_id", "novel_id")
        assert _remote_names(constraint) == (
            "novel_character_revisions.id",
            "novel_character_revisions.character_id",
            "novel_character_revisions.novel_id",
        )

    number = _constraint(
        "novel_character_revisions",
        "uq_character_revision_number",
        UniqueConstraint,
    )
    operation = _constraint(
        "novel_character_revisions",
        "uq_character_revision_operation",
        UniqueConstraint,
    )
    assert _column_names(number) == ("character_id", "character_version")
    assert _column_names(operation) == ("novel_id", "operation_key", "character_id")


def test_authority_migration_is_linear_narrow_and_io_free() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "20260829_0025"' in source
    assert 'down_revision = "20260828_0024"' in source
    for table_name in (
        "novel_outline_revisions",
        "novel_outline_heads",
        "novel_setting_revisions",
        "novel_setting_heads",
        "novel_character_revisions",
    ):
        assert f'"{table_name}"' in source
    for forbidden in (
        "from backend.models",
        "create_engine",
        "requests.",
        "subprocess",
    ):
        assert forbidden not in source
