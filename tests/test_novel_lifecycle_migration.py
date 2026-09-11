from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from backend.models import Base, Novel, NovelDeletionAudit, NovelLifecycleEvent


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "backend/migrations/versions/20260910_0052_novel_recycle_bin.py"
PURGE_MIGRATION = ROOT / "backend/migrations/versions/20260911_0053_novel_purge_backup_receipt.py"


def test_recycle_migration_is_linear_and_forward_only() -> None:
    scripts = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert scripts.get_current_head() == "20260911_0053"
    assert scripts.get_revision("20260910_0052").down_revision == "20260910_0051"
    assert scripts.get_revision("20260911_0053").down_revision == "20260910_0052"
    source = MIGRATION.read_text(encoding="utf-8")
    assert "novel_lifecycle_events_immutable" in source
    assert "BEFORE UPDATE OR DELETE" in source
    assert "BEFORE TRUNCATE" in source
    assert "forward-only" in source
    purge_source = PURGE_MIGRATION.read_text(encoding="utf-8")
    assert "backup_receipt_sha256" in purge_source
    assert "forward-only" in purge_source


def test_model_exposes_single_lifecycle_authority_and_audit() -> None:
    assert {"recycled_at", "recycled_by"} <= set(Novel.__table__.columns.keys())
    assert "ck_novel_recycle_metadata_pair" in {
        constraint.name for constraint in Novel.__table__.constraints
    }
    assert NovelLifecycleEvent.__table__ is Base.metadata.tables["novel_lifecycle_events"]
    assert NovelLifecycleEvent.__table__.foreign_keys == set()
    assert "uq_novel_lifecycle_idempotency" in {
        constraint.name for constraint in NovelLifecycleEvent.__table__.constraints
    }
    assert "backup_receipt_sha256" in NovelDeletionAudit.__table__.columns


def test_migration_does_not_mutate_content_or_media_tables() -> None:
    source = MIGRATION.read_text(encoding="utf-8").lower()
    for forbidden in (
        "update documents",
        "delete from documents",
        "delete from media_assets",
        "delete from document_revisions",
    ):
        assert forbidden not in source
