from __future__ import annotations

import hashlib
import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError


ROOT = Path(__file__).resolve().parents[2]
FROZEN_0012 = ROOT / (
    "backend/migrations/versions/20260826_0012_narration_execution_safety.py"
)
MIGRATION_0013 = ROOT / (
    "backend/migrations/versions/20260826_0013_narration_asset_scoped_paths.py"
)
FROZEN_0012_SHA256 = (
    "ab4384841a5471ef2638c2f5118f5e23028e32a333545c427445550f5e82c805"
)
REVISION_0012 = "20260826_0012"
REVISION_0013 = "20260826_0013"
OWNER_ID = UUID("29cf94d9-a5c9-54ec-912c-5dfff8738c4c")
WORKSPACE_ID = UUID("f0e2e632-bc99-52d2-9916-bb906aa4da6e")


def test_frozen_0012_bytes_are_unchanged_and_0013_is_no_io_forward_only() -> None:
    assert hashlib.sha256(FROZEN_0012.read_bytes()).hexdigest() == FROZEN_0012_SHA256
    source = MIGRATION_0013.read_text(encoding="utf-8")
    assert 'revision = "20260826_0013"' in source
    assert 'down_revision = "20260826_0012"' in source
    assert "replace(id::text,'-','')" in source
    assert "replace(media_row.id::text,'-','')" in source
    assert "CREATE OR REPLACE FUNCTION narration_guard_media_gc_plan()" in source
    assert "filesystem-plus-database fix-forward" in source
    for forbidden in ("from backend.models", "shutil", "os.rename", "Path(", "subprocess"):
        assert forbidden not in source


def _live_url() -> str:
    raw = os.environ.get("TTS_ASSET_MIGRATION_DATABASE_URL", "").strip()
    if not raw:
        pytest.skip("TTS_ASSET_MIGRATION_DATABASE_URL is not configured")
    parsed = make_url(raw)
    if (
        not parsed.drivername.startswith("postgresql")
        or parsed.database != "ai_novel_world_2026_tts_asset_migration_test"
        or parsed.username != "tts_asset_test"
        or parsed.host not in {"127.0.0.1", "localhost", "::1"}
    ):
        raise RuntimeError("asset-path migration test requires its exact disposable loopback DB")
    production = os.environ.get("AI_NOVEL_DATABASE_URL", "").strip()
    if production:
        prod = make_url(production)
        if (parsed.host, parsed.port, parsed.database) == (
            prod.host,
            prod.port,
            prod.database,
        ):
            raise RuntimeError("asset-path migration test database must differ from production")
    return raw


def _config(url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def _head(engine) -> str:
    with engine.connect() as connection:
        return str(connection.scalar(text("SELECT version_num FROM alembic_version")))


def _constraint_definition(engine) -> str:
    with engine.connect() as connection:
        return str(
            connection.scalar(
                text(
                    """
                    SELECT pg_get_constraintdef(oid)
                    FROM pg_constraint
                    WHERE conname='ck_media_asset_narration_canonical_path'
                    """
                )
            )
        )


def _insert_novel(connection, novel_id: UUID) -> None:
    connection.execute(
        text(
            """
            INSERT INTO novels
              (id,owner_id,workspace_id,title,description,version)
            VALUES (:id,:owner,:workspace,'asset-scope-migration','',1)
            """
        ),
        {"id": novel_id, "owner": OWNER_ID, "workspace": WORKSPACE_ID},
    )


def _insert_staging_asset(
    connection,
    *,
    asset_id: UUID,
    novel_id: UUID,
    storage_path: str,
    digest: str,
) -> None:
    connection.execute(
        text(
            """
            INSERT INTO media_assets
              (id,owner_id,workspace_id,novel_id,kind,asset_class,mime_type,
               byte_size,storage_backend,storage_path,content_hash,state,
               retention_policy,checksum_algorithm,validation_json,metadata_json)
            VALUES
              (:id,:owner,:workspace,:novel,'narration_preview','preview','audio/wav',
               1,'local',:path,:digest,'staging','derivable','sha256','{}'::jsonb,'{}'::jsonb)
            """
        ),
        {
            "id": asset_id,
            "owner": OWNER_ID,
            "workspace": WORKSPACE_ID,
            "novel": novel_id,
            "path": storage_path,
            "digest": digest,
        },
    )


def _remove_committed_migration_fixture(
    connection, *, novel_id: UUID, asset_id: UUID
) -> None:
    """Clean only this disposable fixture after a deliberate migration refusal."""

    connection.execute(text("SET LOCAL session_replication_role=replica"))
    connection.execute(text("DELETE FROM media_assets WHERE id=:id"), {"id": asset_id})
    connection.execute(text("DELETE FROM novels WHERE id=:id"), {"id": novel_id})


def test_live_0013_lifecycle_rejects_unmoved_rows_and_unsafe_downgrade() -> None:
    url = _live_url()
    engine = create_engine(url, pool_pre_ping=True)
    config = _config(url)
    old_database_url = os.environ.get("AI_NOVEL_DATABASE_URL")
    os.environ["AI_NOVEL_DATABASE_URL"] = url
    try:
        with engine.connect() as connection:
            tables = inspect(connection).get_table_names()
            assert not tables, f"asset migration database is not empty: {tables}"

        command.upgrade(config, REVISION_0012)
        assert _head(engine) == REVISION_0012
        pure_definition = _constraint_definition(engine)
        assert "substr((content_hash)::text, 1, 2)" in pure_definition
        assert "replace((id)::text" not in pure_definition

        command.downgrade(config, "20260826_0011")
        command.upgrade(config, REVISION_0012)

        legacy_novel, legacy_asset = uuid4(), uuid4()
        digest = "a" * 64
        legacy_path = f"assets/{digest[:2]}/{digest}.wav"
        with engine.begin() as connection:
            _insert_novel(connection, legacy_novel)
            _insert_staging_asset(
                connection,
                asset_id=legacy_asset,
                novel_id=legacy_novel,
                storage_path=legacy_path,
                digest=digest,
            )
        with pytest.raises((DBAPIError, RuntimeError)):
            command.upgrade(config, REVISION_0013)
        assert _head(engine) == REVISION_0012
        with engine.begin() as connection:
            assert connection.scalar(
                text("SELECT storage_path FROM media_assets WHERE id=:id"),
                {"id": legacy_asset},
            ) == legacy_path
            _remove_committed_migration_fixture(
                connection,
                novel_id=legacy_novel,
                asset_id=legacy_asset,
            )

        command.upgrade(config, REVISION_0013)
        assert _head(engine) == REVISION_0013
        scoped_definition = _constraint_definition(engine)
        assert "replace((id)::text" in scoped_definition
        with engine.connect() as connection:
            gc_guard = str(
                connection.scalar(
                    text(
                        """
                        SELECT pg_get_functiondef(p.oid)
                        FROM pg_proc p
                        JOIN pg_namespace n ON n.oid=p.pronamespace
                        WHERE n.nspname='public'
                          AND p.proname='narration_guard_media_gc_plan'
                        """
                    )
                )
            )
            assert "replace(media_row.id::text" in gc_guard

        scoped_novel, scoped_asset = uuid4(), uuid4()
        scoped_path = (
            f"assets/{scoped_asset.hex[:2]}/{scoped_asset.hex}/{digest}.wav"
        )
        with engine.begin() as connection:
            _insert_novel(connection, scoped_novel)
            _insert_staging_asset(
                connection,
                asset_id=scoped_asset,
                novel_id=scoped_novel,
                storage_path=scoped_path,
                digest=digest,
            )
            nested = connection.begin_nested()
            with pytest.raises(DBAPIError):
                _insert_staging_asset(
                    connection,
                    asset_id=uuid4(),
                    novel_id=scoped_novel,
                    storage_path=legacy_path,
                    digest=digest,
                )
                nested.commit()
            if nested.is_active:
                nested.rollback()

        with pytest.raises((DBAPIError, RuntimeError)):
            command.downgrade(config, REVISION_0012)
        assert _head(engine) == REVISION_0013
        with engine.begin() as connection:
            assert connection.scalar(
                text("SELECT storage_path FROM media_assets WHERE id=:id"),
                {"id": scoped_asset},
            ) == scoped_path
            _remove_committed_migration_fixture(
                connection,
                novel_id=scoped_novel,
                asset_id=scoped_asset,
            )

        command.downgrade(config, REVISION_0012)
        command.upgrade(config, REVISION_0013)
        assert _head(engine) == REVISION_0013
    finally:
        if old_database_url is None:
            os.environ.pop("AI_NOVEL_DATABASE_URL", None)
        else:
            os.environ["AI_NOVEL_DATABASE_URL"] = old_database_url
        engine.dispose()
