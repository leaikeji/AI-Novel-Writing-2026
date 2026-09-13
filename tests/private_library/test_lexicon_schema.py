from pathlib import Path

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

import backend.creative_data_models  # noqa: F401
from backend.models import Base


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "backend/migrations/versions/20260913_0056_private_library_lexicon.py"


def _table(name: str):
    return Base.metadata.tables[name]


def _named(table_name: str, name: str, kind: type):
    matches = [
        item for item in _table(table_name).constraints
        if isinstance(item, kind) and item.name == name
    ]
    assert len(matches) == 1
    return matches[0]


def test_private_asset_scope_and_copy_provenance_are_registered() -> None:
    table = _table("private_assets")
    assert {
        "scope_kind",
        "scope_novel_id",
        "collection_key",
        "source_asset_id",
        "source_version_id",
    } <= set(table.c.keys())
    assert _named("private_assets", "ck_private_asset_scope", CheckConstraint) is not None
    assert _named("private_assets", "ck_private_asset_source_pair", CheckConstraint) is not None
    source = _named(
        "private_assets",
        "fk_private_asset_source_version_scope",
        ForeignKeyConstraint,
    )
    assert tuple(column.name for column in source.columns) == (
        "source_version_id",
        "source_asset_id",
    )


def test_collection_targets_are_unique_by_scope_without_coalescing_nulls() -> None:
    indexes = {item.name: item for item in _table("private_assets").indexes}
    library = indexes["uq_private_assets_library_collection_key"]
    novel = indexes["uq_private_assets_novel_collection_key"]
    assert library.unique is True
    assert tuple(column.name for column in library.columns) == ("collection_key",)
    assert "scope_kind='library'" in str(library.dialect_options["postgresql"]["where"])
    assert novel.unique is True
    assert tuple(column.name for column in novel.columns) == (
        "scope_novel_id",
        "collection_key",
    )
    assert "scope_kind='novel'" in str(novel.dialect_options["postgresql"]["where"])
    copy = indexes["uq_private_assets_novel_source_copy"]
    assert copy.unique is True
    assert tuple(column.name for column in copy.columns) == (
        "scope_novel_id",
        "source_asset_id",
    )


def test_change_and_check_tables_have_closed_states_and_idempotency() -> None:
    assert {"library_change_requests", "library_check_reports"} <= set(
        Base.metadata.tables
    )
    assert _named(
        "library_change_requests",
        "uq_library_change_idempotency",
        UniqueConstraint,
    ) is not None
    assert _named(
        "library_change_requests",
        "ck_library_change_state",
        CheckConstraint,
    ) is not None
    assert _named(
        "library_check_reports",
        "ck_library_check_status",
        CheckConstraint,
    ) is not None
    check_input = _named(
        "library_check_reports",
        "uq_library_check_input",
        UniqueConstraint,
    )
    assert tuple(column.name for column in check_input.columns) == (
        "novel_id",
        "document_id",
        "source_kind",
        "source_id",
        "source_version",
        "text_hash",
        "rules_hash",
        "scanner_version",
    )
    document_scope = _named(
        "library_check_reports",
        "fk_library_check_document_scope",
        ForeignKeyConstraint,
    )
    assert tuple(column.name for column in document_scope.columns) == (
        "document_id",
        "novel_id",
    )


def test_0056_migration_is_linear_additive_and_has_recovery_path() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "20260913_0056"' in source
    assert 'down_revision = "20260912_0055"' in source
    for name in (
        "scope_kind",
        "library_change_requests",
        "library_check_reports",
        "fk_private_asset_source_version_scope",
        "def downgrade()",
    ):
        assert name in source
    for forbidden in (
        "from backend.models",
        "create_engine",
        "import requests",
        "import subprocess",
    ):
        assert forbidden not in source
