from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from backend.models import TTSCloudProfile


ROOT = Path(__file__).resolve().parents[2]
REVISION = "20260908_0044"
DOWN_REVISION = "20260908_0043"
HEAD_REVISION = "20260910_0051"
MIGRATION = (
    ROOT
    / "backend/migrations/versions/20260908_0044_tts_cloud_profiles.py"
)


def _scripts() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))


def test_cloud_profile_revision_is_the_only_linear_head() -> None:
    scripts = _scripts()
    assert scripts.get_heads() == [HEAD_REVISION]
    assert scripts.get_revision(HEAD_REVISION).down_revision == "20260909_0050"
    assert scripts.get_revision("20260909_0049").down_revision == "20260909_0048"
    assert scripts.get_revision("20260909_0045").down_revision == REVISION
    assert scripts.get_revision(REVISION).down_revision == DOWN_REVISION


def test_cloud_profile_model_has_one_active_profile_guard() -> None:
    columns = set(TTSCloudProfile.__table__.columns.keys())
    assert columns == {
        "id",
        "owner_id",
        "workspace_id",
        "name",
        "protocol",
        "base_url",
        "credential_ref",
        "api_key_last4",
        "api_key_updated_at",
        "quality_model_id",
        "speed_model_id",
        "quality_test_state",
        "speed_test_state",
        "lifecycle_state",
        "verification_fingerprint",
        "failure_code",
        "last_tested_at",
        "last_operation_key",
        "last_operation_hash",
        "version",
        "created_at",
        "updated_at",
    }
    active_index = next(
        index
        for index in TTSCloudProfile.__table__.indexes
        if index.name == "uq_tts_cloud_profile_active_scope"
    )
    assert active_index.unique is True
    compiled = str(CreateIndex(active_index).compile(dialect=postgresql.dialect()))
    assert "UNIQUE INDEX uq_tts_cloud_profile_active_scope" in compiled
    assert "WHERE lifecycle_state='active'" in compiled


def test_cloud_profile_migration_is_self_contained_and_reversible() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    for marker in (
        'revision = "20260908_0044"',
        'down_revision = "20260908_0043"',
        '"tts_cloud_profiles"',
        '"uq_tts_cloud_profile_active_scope"',
        "postgresql_where=sa.text(\"lifecycle_state='active'\")",
        'op.drop_table("tts_cloud_profiles")',
    ):
        assert marker in source
    for forbidden in (
        "from backend.models",
        "create_engine",
        "requests.",
        "httpx.",
        "subprocess",
    ):
        assert forbidden not in source
