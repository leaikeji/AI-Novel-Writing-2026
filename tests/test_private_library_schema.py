"""Static contracts for immutable private-asset versions and bindings."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

import backend.creative_data_models  # noqa: F401  # registers additive tables
from backend.models import Base


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "backend/migrations/versions/20260829_0027_private_library_versions.py"


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


def test_private_library_tables_and_legacy_projection_columns_are_registered() -> None:
    assert {"private_asset_versions", "novel_asset_bindings"} <= set(Base.metadata.tables)
    assert {"current_version_id", "tags_json", "source_json", "rights_json"} <= set(
        _table("private_assets").c.keys()
    )
    assert {"asset_version_id", "usage_policy"} <= set(
        _table("asset_preset_items").c.keys()
    )


def test_private_asset_versions_have_linear_and_idempotent_keys() -> None:
    number = _constraint(
        "private_asset_versions",
        "uq_private_asset_version_number",
        UniqueConstraint,
    )
    operation = _constraint(
        "private_asset_versions",
        "uq_private_asset_version_operation",
        UniqueConstraint,
    )
    scope = _constraint(
        "private_asset_versions",
        "uq_private_asset_version_scope",
        UniqueConstraint,
    )
    assert _column_names(number) == ("asset_id", "version_number")
    assert _column_names(operation) == ("asset_id", "operation_key")
    assert _column_names(scope) == ("id", "asset_id")


def test_root_presets_and_novel_bindings_pin_a_matching_asset_version() -> None:
    expected = {
        ("private_assets", "fk_private_asset_current_version_scope"): (
            ("current_version_id", "id"),
            ("private_asset_versions.id", "private_asset_versions.asset_id"),
        ),
        ("asset_preset_items", "fk_asset_preset_item_version_scope"): (
            ("asset_version_id", "asset_id"),
            ("private_asset_versions.id", "private_asset_versions.asset_id"),
        ),
        ("novel_asset_bindings", "fk_novel_asset_binding_version_scope"): (
            ("asset_version_id", "asset_id"),
            ("private_asset_versions.id", "private_asset_versions.asset_id"),
        ),
    }
    for (table_name, constraint_name), (local, remote) in expected.items():
        constraint = _constraint(table_name, constraint_name, ForeignKeyConstraint)
        assert _column_names(constraint) == local
        assert _remote_names(constraint) == remote


def test_preset_and_binding_policies_use_the_same_closed_vocabulary() -> None:
    expected_sql = "usage_policy IN ('required','preferred','context_only','prohibited')"
    preset = _constraint(
        "asset_preset_items",
        "ck_asset_preset_item_usage_policy",
        CheckConstraint,
    )
    binding = _constraint(
        "novel_asset_bindings",
        "ck_novel_asset_binding_policy",
        CheckConstraint,
    )
    assert str(preset.sqltext) == expected_sql
    assert str(binding.sqltext) == expected_sql


def test_a_novel_has_at_most_one_active_binding_per_asset_and_position() -> None:
    table = _table("novel_asset_bindings")
    expected = {
        "uq_novel_asset_binding_active_asset": ("novel_id", "asset_id"),
        "uq_novel_asset_binding_active_position": ("novel_id", "position"),
    }
    for name, columns in expected.items():
        index = next(index for index in table.indexes if index.name == name)
        assert index.unique is True
        assert tuple(column.name for column in index.columns) == columns
        assert "lifecycle_state='active'" in str(
            index.dialect_options["postgresql"]["where"]
        )


def test_private_library_migration_is_linear_narrow_and_io_free() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "20260829_0027"' in source
    assert 'down_revision = "20260829_0026"' in source
    for table_name in ("private_asset_versions", "novel_asset_bindings"):
        assert f'"{table_name}"' in source
    for constraint_name in (
        "fk_private_asset_current_version_scope",
        "fk_asset_preset_item_version_scope",
        "fk_novel_asset_binding_version_scope",
    ):
        assert constraint_name in source
    for forbidden in ("from backend.models", "create_engine", "requests.", "subprocess"):
        assert forbidden not in source
