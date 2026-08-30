from __future__ import annotations

import hashlib
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from backend.models import AssetTombstone, MediaAsset, MediaGcDeletionRecord
from backend.narration.media import (
    MediaConflict,
    apply_ready_evidence_in_session,
    begin_gc_deletion_in_session,
    execute_gc_delete,
    finalize_gc_deletion_in_session,
    load_reference_roots_in_session,
    plan_media_read_in_session,
)
from backend.narration.storage import NarrationStorage, PublishedFile


OWNER = UUID("29cf94d9-a5c9-54ec-912c-5dfff8738c4c")
WORKSPACE = UUID("f0e2e632-bc99-52d2-9916-bb906aa4da6e")
GC_FIXTURE_NOVEL_ID = UUID("00000000-0000-4000-8000-000000001200")
OLD_STAGING_FIXTURE_ID = UUID("00000000-0000-4000-8000-000000001201")
REFERENCE_FIRST_FIXTURE_ID = UUID("00000000-0000-4000-8000-000000001202")
GC_FIRST_FIXTURE_ID = UUID("00000000-0000-4000-8000-000000001203")
ROOT = Path(__file__).resolve().parents[2]


def _repository_head() -> str:
    config = Config(str(ROOT / "alembic.ini"))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise RuntimeError("media PostgreSQL gate requires one linear Alembic head")
    return heads[0]


def _asset_path(asset_id: UUID, digest: str, extension: str = "wav") -> str:
    return f"assets/{asset_id.hex[:2]}/{asset_id.hex}/{digest}.{extension}"


def _live_url() -> str:
    raw = os.environ.get("TTS_TEST_DATABASE_URL", "").strip()
    if not raw:
        pytest.skip("TTS_TEST_DATABASE_URL is not configured")
    parsed = make_url(raw)
    if (
        parsed.database != "ai_novel_world_2026_tts_test"
        or parsed.username != "tts_test"
        or parsed.host not in {"127.0.0.1", "localhost", "::1"}
    ):
        raise RuntimeError(
            "T1-E tests require the exact loopback disposable TTS database identity"
        )
    production = os.environ.get("AI_NOVEL_DATABASE_URL", "").strip()
    if production:
        prod = make_url(production)
        if (parsed.host, parsed.port, parsed.database) == (
            prod.host,
            prod.port,
            prod.database,
        ):
            raise RuntimeError("T1-E tests refuse the configured production database")
    return raw


@pytest.fixture(scope="module")
def engine() -> Engine:
    database = create_engine(_live_url(), pool_pre_ping=True)
    with database.begin() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            _repository_head()
        )
        # These three durable fixtures exercise commit-order and recovery
        # semantics across separate tests.  Rebuild only their fixed IDs in the
        # explicitly disposable superuser database so the module has no hidden
        # dependency on an out-of-band seed script and can be rerun safely.
        connection.execute(text("SET LOCAL session_replication_role=replica"))
        connection.execute(
            text(
                "DELETE FROM media_gc_deletion_plans "
                "WHERE asset_id IN (:old_staging,:reference_first,:gc_first)"
            ),
            {
                "old_staging": OLD_STAGING_FIXTURE_ID,
                "reference_first": REFERENCE_FIRST_FIXTURE_ID,
                "gc_first": GC_FIRST_FIXTURE_ID,
            },
        )
        connection.execute(
            text(
                "DELETE FROM asset_tombstones "
                "WHERE original_asset_id IN (:old_staging,:reference_first,:gc_first)"
            ),
            {
                "old_staging": OLD_STAGING_FIXTURE_ID,
                "reference_first": REFERENCE_FIRST_FIXTURE_ID,
                "gc_first": GC_FIRST_FIXTURE_ID,
            },
        )
        connection.execute(
            text(
                "DELETE FROM media_assets "
                "WHERE id IN (:old_staging,:reference_first,:gc_first)"
            ),
            {
                "old_staging": OLD_STAGING_FIXTURE_ID,
                "reference_first": REFERENCE_FIRST_FIXTURE_ID,
                "gc_first": GC_FIRST_FIXTURE_ID,
            },
        )
        connection.execute(
            text("DELETE FROM novels WHERE id=:novel"),
            {"novel": GC_FIXTURE_NOVEL_ID},
        )
        connection.execute(
            text(
                "INSERT INTO novels (id,title,description,version) "
                "VALUES (:id,'t1e-fixed-gc-fixtures','',1)"
            ),
            {"id": GC_FIXTURE_NOVEL_ID},
        )
        connection.execute(
            text(
                """
                INSERT INTO media_assets
                  (id,owner_id,workspace_id,novel_id,kind,asset_class,mime_type,
                   byte_size,storage_backend,state,retention_policy,
                   checksum_algorithm,validation_json,verified_at,gc_generation,
                   gc_marked_at,storage_path,content_hash,metadata_json,created_at)
                VALUES
                  (:old_staging,:owner,:workspace,:novel,'narration_preview',
                   'preview','audio/wav',4,'local','staging','derivable','sha256',
                   '{}'::jsonb,NULL,0,NULL,:old_path,:old_digest,'{}'::jsonb,
                   clock_timestamp()-interval '25 hours'),
                  (:reference_first,:owner,:workspace,:novel,'narration_preview',
                   'preview','audio/wav',4,'local','ready','derivable','sha256',
                   '{}'::jsonb,clock_timestamp(),1,
                   clock_timestamp()-interval '8 days',:reference_path,
                   :reference_digest,'{}'::jsonb,clock_timestamp()),
                  (:gc_first,:owner,:workspace,:novel,'narration_preview',
                   'preview','audio/wav',4,'local','ready','derivable','sha256',
                   '{}'::jsonb,clock_timestamp(),1,
                   clock_timestamp()-interval '8 days',:gc_path,:gc_digest,
                   '{}'::jsonb,clock_timestamp())
                """
            ),
            {
                "owner": OWNER,
                "workspace": WORKSPACE,
                "novel": GC_FIXTURE_NOVEL_ID,
                "old_staging": OLD_STAGING_FIXTURE_ID,
                "old_path": _asset_path(OLD_STAGING_FIXTURE_ID, "12" * 32),
                "old_digest": "12" * 32,
                "reference_first": REFERENCE_FIRST_FIXTURE_ID,
                "reference_path": _asset_path(REFERENCE_FIRST_FIXTURE_ID, "13" * 32),
                "reference_digest": "13" * 32,
                "gc_first": GC_FIRST_FIXTURE_ID,
                "gc_path": _asset_path(GC_FIRST_FIXTURE_ID, "14" * 32),
                "gc_digest": "14" * 32,
            },
        )
        connection.execute(text("SET LOCAL session_replication_role=origin"))
    try:
        yield database
    finally:
        database.dispose()


def _load_gc_fixture(
    engine: Engine,
    asset_id: UUID,
    *,
    expected_state: str,
    expected_generation: int,
) -> tuple[UUID, UUID, str, str, int]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT novel_id,storage_path,content_hash,byte_size,state,gc_generation "
                "FROM media_assets WHERE id=:id"
            ),
            {"id": asset_id},
        ).mappings().one()
    assert row["novel_id"] is not None
    assert row["state"] == expected_state
    assert row["gc_generation"] == expected_generation
    return (
        row["novel_id"],
        asset_id,
        row["storage_path"],
        row["content_hash"],
        row["byte_size"],
    )


def _insert_media_row(
    connection,
    *,
    novel_id: UUID,
    asset_id: UUID,
    asset_class: str = "preview",
    state: str = "ready",
    retention_policy: str = "derivable",
) -> tuple[str, str]:
    digest = hashlib.sha256(str(asset_id).encode("ascii")).hexdigest()
    path = _asset_path(asset_id, digest)
    connection.execute(
        text(
            """
            INSERT INTO media_assets
              (id,owner_id,workspace_id,novel_id,kind,asset_class,mime_type,
               byte_size,storage_backend,state,retention_policy,checksum_algorithm,
               validation_json,verified_at,gc_generation,gc_marked_at,storage_path,
               content_hash,metadata_json)
            VALUES
              (:id,:owner,:workspace,:novel,:kind,:class,'audio/wav',7,'local',:state,
               :retention,'sha256',jsonb_build_object('test_only_db_fixture',true),
               clock_timestamp(),0,NULL,:path,:digest,'{}'::jsonb)
            """
        ),
        {
            "id": asset_id,
            "owner": OWNER,
            "workspace": WORKSPACE,
            "novel": novel_id,
            "kind": f"narration_{asset_class}",
            "class": asset_class,
            "state": state,
            "retention": retention_policy,
            "path": path,
            "digest": digest,
        },
    )
    return path, digest


def _insert_gc_plan(
    connection,
    *,
    novel_id: UUID,
    asset_id: UUID,
    path: str,
    digest: str,
    byte_size: int = 7,
    generation: int = 1,
) -> None:
    connection.execute(
        text(
            """
            INSERT INTO media_gc_deletion_plans
              (asset_id,owner_id,workspace_id,novel_id,storage_backend,storage_path,
               content_hash,byte_size,generation,file_present,device,inode,reason_code,created_at)
            VALUES
              (:asset,:owner,:workspace,:novel,'local',:path,:digest,:byte_size,
               :generation,true,1,1,
               'unreferenced_derivative_after_grace',clock_timestamp())
            """
        ),
        {
            "asset": asset_id,
            "owner": OWNER,
            "workspace": WORKSPACE,
            "novel": novel_id,
            "path": path,
            "digest": digest,
            "byte_size": byte_size,
            "generation": generation,
        },
    )


def _set_worker_name(connection, name: str) -> None:
    connection.execute(text("SELECT set_config('application_name', :name, true)"), {"name": name})
    connection.execute(text("SET LOCAL lock_timeout = '8s'"))


def _wait_until_lock_wait(engine: Engine, application_name: str) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with engine.connect() as observer:
            wait_type = observer.scalar(
                text(
                    "SELECT wait_event_type FROM pg_stat_activity "
                    "WHERE application_name=:name AND state='active'"
                ),
                {"name": application_name},
            )
        if wait_type == "Lock":
            return
        time.sleep(0.02)
    raise AssertionError(f"worker {application_name} never reached the expected row-lock wait")


def _expect_db_rejection(connection, statement: str, parameters: dict[str, object]) -> None:
    savepoint = connection.begin_nested()
    try:
        with pytest.raises(DBAPIError):
            connection.execute(text(statement), parameters)
            savepoint.commit()
    finally:
        if savepoint.is_active:
            savepoint.rollback()


def test_live_schema_has_unique_blob_and_all_ready_reference_guards(engine: Engine) -> None:
    with engine.connect() as connection:
        unique_definition = connection.scalar(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname='uq_media_asset_physical_blob'"
            )
        )
        assert unique_definition == "UNIQUE (storage_backend, storage_path)"
        triggers = set(
            connection.scalars(
                text(
                    "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal "
                    "AND tgname LIKE 'trg_t1e_%'"
                )
            )
        )
    assert {
        "trg_t1e_novel_cover_ready",
        "trg_t1e_voice_assets_ready",
        "trg_t1e_render_asset_ready",
        "trg_t1e_export_asset_ready",
        "trg_t1e_active_job_asset_ready",
        "trg_t1e_media_identity",
        "trg_t1e_media_deleting_plan",
    } <= triggers
    with engine.connect() as connection:
        hardened = set(
            connection.scalars(
                text(
                    "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal "
                    "AND tgname IN "
                    "('trg_t1_media_gc_plan_reachability','trg_t1_media_gc_mark_v2',"
                    "'trg_t1_media_policy_identity_v2')"
                )
            )
        )
    assert hardened == {
        "trg_t1_media_gc_plan_reachability",
        "trg_t1_media_gc_mark_v2",
        "trg_t1_media_policy_identity_v2",
    }
    with engine.connect() as connection:
        media_checks = set(
            connection.scalars(
                text(
                    "SELECT conname FROM pg_constraint WHERE conrelid='media_assets'::regclass "
                    "AND conname IN ('ck_media_asset_ready_narration_identity',"
                    "'ck_media_asset_narration_canonical_path',"
                    "'ck_media_asset_narration_mime_path')"
                )
            )
        )
    assert media_checks == {
        "ck_media_asset_ready_narration_identity",
        "ck_media_asset_narration_canonical_path",
        "ck_media_asset_narration_mime_path",
    }


def test_media_fk_catalog_matches_the_explicit_root_and_guard_inventory(engine: Engine) -> None:
    with engine.connect() as connection:
        foreign_id_columns = set(
            connection.execute(
                text(
                    """
                    SELECT child.relname, child_column.attname
                    FROM pg_constraint constraint_row
                    JOIN pg_class child ON child.oid=constraint_row.conrelid
                    JOIN pg_class parent ON parent.oid=constraint_row.confrelid
                    JOIN LATERAL unnest(constraint_row.conkey) WITH ORDINALITY
                      AS child_key(attnum,ordinality) ON true
                    JOIN LATERAL unnest(constraint_row.confkey) WITH ORDINALITY
                      AS parent_key(attnum,ordinality)
                      ON parent_key.ordinality=child_key.ordinality
                    JOIN pg_attribute child_column
                      ON child_column.attrelid=child.oid
                     AND child_column.attnum=child_key.attnum
                    JOIN pg_attribute parent_column
                      ON parent_column.attrelid=parent.oid
                     AND parent_column.attnum=parent_key.attnum
                    WHERE constraint_row.contype='f' AND parent.relname='media_assets'
                      AND parent_column.attname='id'
                    """
                )
            ).all()
        )
        root_function = connection.scalar(
            text(
                "SELECT pg_get_functiondef(p.oid) FROM pg_proc p "
                "WHERE p.proname='narration_media_has_live_reference'"
            )
        )
    internal_non_root = {
        ("media_gc_deletion_plans", "asset_id"),
        ("voice_deletion_asset_plans", "asset_id"),
    }
    expected_roots = {
        ("novels", "cover_asset_id"),
        ("voice_profile_versions", "reference_asset_id"),
        ("voice_profile_versions", "preview_asset_id"),
        ("narration_render_assets", "asset_id"),
        ("narration_exports", "asset_id"),
        ("active_job_assets", "asset_id"),
        ("voice_reference_asset_links", "reference_asset_id"),
        ("voice_reference_asset_links", "source_asset_id"),
        ("voice_previews", "reference_asset_id"),
        ("voice_previews", "result_asset_id"),
    }
    assert foreign_id_columns - internal_non_root == expected_roots
    assert isinstance(root_function, str)
    for table_name, _column_name in expected_roots:
        assert table_name in root_function


def test_direct_dml_cannot_forge_or_backdate_gc_grace(engine: Engine) -> None:
    connection = engine.connect()
    transaction = connection.begin()
    novel_id, asset_id = uuid4(), uuid4()
    try:
        connection.execute(
            text("INSERT INTO novels (id,title,description,version) VALUES (:id,:title,'',1)"),
            {"id": novel_id, "title": f"t1e-direct-dml-{novel_id}"},
        )
        path, digest = _insert_media_row(
            connection, novel_id=novel_id, asset_id=asset_id
        )

        _expect_db_rejection(
            connection,
            "UPDATE media_assets SET gc_generation=1, "
            "gc_marked_at=clock_timestamp()-interval '8 days' WHERE id=:id",
            {"id": asset_id},
        )
        connection.execute(
            text(
                "UPDATE media_assets SET gc_generation=1, "
                "gc_marked_at=clock_timestamp() WHERE id=:id"
            ),
            {"id": asset_id},
        )
        _expect_db_rejection(
            connection,
            "UPDATE media_assets SET gc_marked_at=clock_timestamp()-interval '8 days' "
            "WHERE id=:id",
            {"id": asset_id},
        )
        _expect_db_rejection(
            connection,
            "INSERT INTO media_gc_deletion_plans "
            "(asset_id,owner_id,workspace_id,novel_id,storage_backend,storage_path,"
            "content_hash,byte_size,generation,file_present,device,inode,reason_code,created_at) "
            "VALUES (:asset,:owner,:workspace,:novel,'local',:path,:digest,7,1,true,1,1,"
            "'unreferenced_derivative_after_grace',clock_timestamp())",
            {
                "asset": asset_id,
                "owner": OWNER,
                "workspace": WORKSPACE,
                "novel": novel_id,
                "path": path,
                "digest": digest,
            },
        )

        forged_id = uuid4()
        forged_digest = hashlib.sha256(str(forged_id).encode("ascii")).hexdigest()
        _expect_db_rejection(
            connection,
            "INSERT INTO media_assets "
            "(id,owner_id,workspace_id,novel_id,kind,asset_class,mime_type,byte_size,"
            "storage_backend,state,retention_policy,checksum_algorithm,validation_json,"
            "gc_generation,gc_marked_at,storage_path,content_hash,metadata_json,created_at) "
            "VALUES (:id,:owner,:workspace,:novel,'narration_preview','preview','audio/wav',"
            "7,'local','ready','derivable','sha256','{}'::jsonb,1,"
            "clock_timestamp()-interval '8 days',:path,:digest,'{}'::jsonb,clock_timestamp())",
            {
                "id": forged_id,
                "owner": OWNER,
                "workspace": WORKSPACE,
                "novel": novel_id,
                "path": _asset_path(forged_id, forged_digest),
                "digest": forged_digest,
            },
        )

        stale_staging_id = uuid4()
        stale_digest = hashlib.sha256(str(stale_staging_id).encode("ascii")).hexdigest()
        _expect_db_rejection(
            connection,
            "INSERT INTO media_assets "
            "(id,owner_id,workspace_id,novel_id,kind,asset_class,mime_type,byte_size,"
            "storage_backend,state,retention_policy,checksum_algorithm,validation_json,"
            "gc_generation,storage_path,content_hash,metadata_json,created_at) "
            "VALUES (:id,:owner,:workspace,:novel,'narration_preview','preview','audio/wav',"
            "7,'local','staging','derivable','sha256','{}'::jsonb,0,:path,:digest,"
            "'{}'::jsonb,clock_timestamp()-interval '25 hours')",
            {
                "id": stale_staging_id,
                "owner": OWNER,
                "workspace": WORKSPACE,
                "novel": novel_id,
                "path": _asset_path(stale_staging_id, stale_digest),
                "digest": stale_digest,
            },
        )

        promoted_id = uuid4()
        promoted_digest = hashlib.sha256(str(promoted_id).encode("ascii")).hexdigest()
        connection.execute(
            text(
                "INSERT INTO media_assets "
                "(id,owner_id,workspace_id,novel_id,kind,asset_class,mime_type,byte_size,"
                "storage_backend,state,retention_policy,checksum_algorithm,validation_json,"
                "gc_generation,storage_path,content_hash,metadata_json,created_at) "
                "VALUES (:id,:owner,:workspace,:novel,'legacy_media',NULL,'audio/wav',7,"
                "'local','staging','derivable','sha256','{}'::jsonb,0,:path,:digest,"
                "'{}'::jsonb,clock_timestamp()-interval '25 hours')"
            ),
            {
                "id": promoted_id,
                "owner": OWNER,
                "workspace": WORKSPACE,
                "novel": novel_id,
                "path": f"assets/{promoted_digest[:2]}/{promoted_digest}.wav",
                "digest": promoted_digest,
            },
        )
        _expect_db_rejection(
            connection,
            "UPDATE media_assets SET kind='narration_preview', asset_class='preview' "
            "WHERE id=:id",
            {"id": promoted_id},
        )

        noncanonical_id = uuid4()
        noncanonical_digest = hashlib.sha256(
            str(noncanonical_id).encode("ascii")
        ).hexdigest()
        _expect_db_rejection(
            connection,
            "INSERT INTO media_assets "
            "(id,owner_id,workspace_id,novel_id,kind,asset_class,mime_type,byte_size,"
            "storage_backend,state,retention_policy,checksum_algorithm,validation_json,"
            "gc_generation,storage_path,content_hash,metadata_json) "
            "VALUES (:id,:owner,:workspace,:novel,'narration_preview','preview','audio/wav',"
            "7,'local','staging','derivable','sha256','{}'::jsonb,0,:path,:digest,"
            "'{}'::jsonb)",
            {
                "id": noncanonical_id,
                "owner": OWNER,
                "workspace": WORKSPACE,
                "novel": novel_id,
                "path": f"assets/zz/{noncanonical_digest}.wav",
                "digest": noncanonical_digest,
            },
        )

        unverified_id = uuid4()
        unverified_digest = hashlib.sha256(
            str(unverified_id).encode("ascii")
        ).hexdigest()
        _expect_db_rejection(
            connection,
            "INSERT INTO media_assets "
            "(id,owner_id,workspace_id,novel_id,kind,asset_class,mime_type,byte_size,"
            "storage_backend,state,retention_policy,checksum_algorithm,validation_json,"
            "verified_at,gc_generation,storage_path,content_hash,metadata_json) "
            "VALUES (:id,:owner,:workspace,:novel,'narration_preview','preview','audio/wav',"
            "7,'local','ready','derivable','sha256','{}'::jsonb,NULL,0,:path,:digest,"
            "'{}'::jsonb)",
            {
                "id": unverified_id,
                "owner": OWNER,
                "workspace": WORKSPACE,
                "novel": novel_id,
                "path": _asset_path(unverified_id, unverified_digest),
                "digest": unverified_digest,
            },
        )
    finally:
        if transaction.is_active:
            transaction.rollback()
        connection.close()


def test_published_policy_and_protected_gc_are_database_enforced(engine: Engine) -> None:
    connection = engine.connect()
    transaction = connection.begin()
    novel_id = uuid4()
    try:
        connection.execute(
            text("INSERT INTO novels (id,title,description,version) VALUES (:id,:title,'',1)"),
            {"id": novel_id, "title": f"t1e-policy-{novel_id}"},
        )
        preview_id = uuid4()
        _insert_media_row(connection, novel_id=novel_id, asset_id=preview_id)
        for assignment in (
            "asset_class='source'",
            "retention_policy='legal_hold'",
            "expires_at=clock_timestamp()+interval '1 day'",
        ):
            _expect_db_rejection(
                connection,
                f"UPDATE media_assets SET {assignment} WHERE id=:id",
                {"id": preview_id},
            )

        source_id = uuid4()
        source_path, source_digest = _insert_media_row(
            connection,
            novel_id=novel_id,
            asset_id=source_id,
            asset_class="source",
            retention_policy="source",
        )
        _expect_db_rejection(
            connection,
            "INSERT INTO media_gc_deletion_plans "
            "(asset_id,owner_id,workspace_id,novel_id,storage_backend,storage_path,"
            "content_hash,byte_size,generation,file_present,device,inode,reason_code,created_at) "
            "VALUES (:asset,:owner,:workspace,:novel,'local',:path,:digest,7,0,true,1,1,"
            "'unreferenced_derivative_after_grace',clock_timestamp())",
            {
                "asset": source_id,
                "owner": OWNER,
                "workspace": WORKSPACE,
                "novel": novel_id,
                "path": source_path,
                "digest": source_digest,
            },
        )

        held_id = uuid4()
        held_path, held_digest = _insert_media_row(
            connection,
            novel_id=novel_id,
            asset_id=held_id,
            retention_policy="legal_hold",
        )
        _expect_db_rejection(
            connection,
            "INSERT INTO media_gc_deletion_plans "
            "(asset_id,owner_id,workspace_id,novel_id,storage_backend,storage_path,"
            "content_hash,byte_size,generation,file_present,device,inode,reason_code,created_at) "
            "VALUES (:asset,:owner,:workspace,:novel,'local',:path,:digest,7,0,true,1,1,"
            "'unreferenced_derivative_after_grace',clock_timestamp())",
            {
                "asset": held_id,
                "owner": OWNER,
                "workspace": WORKSPACE,
                "novel": novel_id,
                "path": held_path,
                "digest": held_digest,
            },
        )
    finally:
        if transaction.is_active:
            transaction.rollback()
        connection.close()


def test_gc_plan_reverse_deferred_guard_rejects_plan_without_state_transition(
    engine: Engine,
) -> None:
    novel_id, asset_id, path, digest, byte_size = _load_gc_fixture(
        engine,
        OLD_STAGING_FIXTURE_ID,
        expected_state="staging",
        expected_generation=0,
    )
    assert digest == "12" * 32
    assert path == _asset_path(asset_id, digest)
    assert byte_size == 4
    connection = engine.connect()
    transaction = connection.begin()
    try:
        connection.execute(
            text(
                """
                INSERT INTO media_gc_deletion_plans
                  (asset_id,owner_id,workspace_id,novel_id,storage_backend,storage_path,
                   content_hash,byte_size,generation,file_present,device,inode,
                   reason_code,created_at)
                VALUES
                  (:asset,:owner,:workspace,:novel,'local',:path,:digest,:byte_size,0,
                   false,NULL,NULL,'staging_orphan',clock_timestamp())
                """
            ),
            {
                "asset": asset_id,
                "owner": OWNER,
                "workspace": WORKSPACE,
                "novel": novel_id,
                "path": path,
                "digest": digest,
                "byte_size": byte_size,
            },
        )
        with pytest.raises(DBAPIError):
            connection.execute(
                text(
                    'SET CONSTRAINTS "trg_t1_media_gc_plan_reachability" IMMEDIATE'
                )
            )
    finally:
        if transaction.is_active:
            transaction.rollback()
        connection.close()
    with engine.connect() as check:
        assert check.scalar(
            text("SELECT state FROM media_assets WHERE id=:id"), {"id": asset_id}
        ) == "staging"
        assert check.scalar(
            text("SELECT count(*) FROM media_gc_deletion_plans WHERE asset_id=:id"),
            {"id": asset_id},
        ) == 0


def test_physical_blob_has_exactly_one_database_owner(engine: Engine) -> None:
    connection = engine.connect()
    transaction = connection.begin()
    novel_id, asset_id = uuid4(), uuid4()
    try:
        connection.execute(
            text("INSERT INTO novels (id,title,description,version) VALUES (:id,:title,'',1)"),
            {"id": novel_id, "title": f"t1e-unique-{novel_id}"},
        )
        path, digest = _insert_media_row(
            connection, novel_id=novel_id, asset_id=asset_id
        )
        savepoint = connection.begin_nested()
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    """
                    INSERT INTO media_assets
                      (id,owner_id,workspace_id,novel_id,kind,asset_class,mime_type,
                       byte_size,storage_backend,state,retention_policy,checksum_algorithm,
                       validation_json,verified_at,gc_generation,storage_path,content_hash,
                       metadata_json)
                    VALUES
                      (:id,:owner,:workspace,:novel,'narration_preview','preview','audio/wav',
                       7,'local','ready','derivable','sha256','{}'::jsonb,
                       clock_timestamp(),0,:path,:digest,'{}'::jsonb)
                    """
                ),
                {
                    "id": uuid4(),
                    "owner": OWNER,
                    "workspace": WORKSPACE,
                    "novel": novel_id,
                    "path": path,
                    "digest": digest,
                },
            )
            savepoint.commit()
        if savepoint.is_active:
            savepoint.rollback()
    finally:
        if transaction.is_active:
            transaction.rollback()
        connection.close()


def test_active_job_assets_are_persistent_roots_and_release_before_terminal(engine: Engine) -> None:
    connection = engine.connect()
    transaction = connection.begin()
    novel_id, asset_id, job_id = uuid4(), uuid4(), uuid4()
    try:
        connection.execute(
            text("INSERT INTO novels (id,title,description,version) VALUES (:id,:title,'',1)"),
            {"id": novel_id, "title": f"t1e-active-root-{novel_id}"},
        )
        _insert_media_row(connection, novel_id=novel_id, asset_id=asset_id)
        connection.execute(
            text(
                """
                INSERT INTO background_jobs
                  (id,owner_id,workspace_id,novel_id,request_id,request_allows_render,
                   job_kind,input_hash,idempotency_key,resource_class,base_priority,state,
                   max_attempts,attempt_count,progress_current)
                VALUES
                  (:id,:owner,:workspace,:novel,NULL,NULL,'embedding.index_batch',:hash,:key,
                   'dashscope-embedding',0,'queued',3,0,0)
                """
            ),
            {
                "id": job_id,
                "owner": OWNER,
                "workspace": WORKSPACE,
                "novel": novel_id,
                "hash": hashlib.sha256(str(job_id).encode("ascii")).hexdigest(),
                "key": f"t1e-{job_id}",
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO active_job_assets
                  (job_id,asset_id,owner_id,workspace_id,novel_id,role,acquired_at)
                VALUES (:job,:asset,:owner,:workspace,:novel,'input',clock_timestamp())
                """
            ),
            {
                "job": job_id,
                "asset": asset_id,
                "owner": OWNER,
                "workspace": WORKSPACE,
                "novel": novel_id,
            },
        )
        with Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        ) as session, session.begin():
            roots = load_reference_roots_in_session(session, asset_ids=(asset_id,))
            assert roots.active_job_assets == frozenset({asset_id})
        _expect_db_rejection(
            connection,
            "UPDATE media_assets SET gc_generation=gc_generation+1, "
            "gc_marked_at=clock_timestamp() WHERE id=:id",
            {"id": asset_id},
        )

        terminal_savepoint = connection.begin_nested()
        try:
            connection.execute(
                text("UPDATE background_jobs SET state='running' WHERE id=:id"),
                {"id": job_id},
            )
            connection.execute(
                text("UPDATE background_jobs SET state='succeeded' WHERE id=:id"),
                {"id": job_id},
            )
            with pytest.raises(DBAPIError):
                connection.execute(
                    text('SET CONSTRAINTS "trg_t1e_terminal_job_assets" IMMEDIATE')
                )
        finally:
            if terminal_savepoint.is_active:
                terminal_savepoint.rollback()

        connection.execute(
            text(
                "UPDATE active_job_assets SET released_at=clock_timestamp() "
                "WHERE job_id=:job AND asset_id=:asset"
            ),
            {"job": job_id, "asset": asset_id},
        )
        connection.execute(
            text("UPDATE background_jobs SET state='running' WHERE id=:id"), {"id": job_id}
        )
        connection.execute(
            text("UPDATE background_jobs SET state='succeeded' WHERE id=:id"), {"id": job_id}
        )
        connection.execute(
            text('SET CONSTRAINTS "trg_t1e_terminal_job_assets" IMMEDIATE')
        )
        with Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
        ) as session, session.begin():
            roots = load_reference_roots_in_session(session, asset_ids=(asset_id,))
            assert asset_id not in roots.active_job_assets
    finally:
        if transaction.is_active:
            transaction.rollback()
        connection.close()


def test_service_gc_plan_survives_commit_and_finalizes_from_db_authority(
    engine: Engine, tmp_path: Path
) -> None:
    models_root = tmp_path / "models"
    media_root = tmp_path / "media"
    models_root.mkdir()
    media_root.mkdir()
    storage = NarrationStorage(models_root=models_root, media_root=media_root)
    novel_id, asset_id, path, digest, byte_size = _load_gc_fixture(
        engine,
        OLD_STAGING_FIXTURE_ID,
        expected_state="staging",
        expected_generation=0,
    )
    assert digest == "12" * 32
    assert path == _asset_path(asset_id, digest)
    assert byte_size == 4
    with Session(engine, expire_on_commit=False) as session, session.begin():
        plan = begin_gc_deletion_in_session(
            session, storage, asset_id=asset_id, expected_generation=0
        )
        assert plan.reason_code == "staging_orphan"
        assert not plan.file_present
        assert plan.device is None and plan.inode is None
    with Session(engine) as session:
        durable_record = session.get(MediaGcDeletionRecord, asset_id)
        durable_asset = session.get(MediaAsset, asset_id)
        assert durable_record is not None
        assert durable_record.reason_code == "staging_orphan"
        assert durable_asset is not None and durable_asset.state == "deleting"
    result = execute_gc_delete(storage, plan)
    assert not result.removed and result.verified_absent
    with Session(engine, expire_on_commit=False) as session, session.begin():
        tombstone = finalize_gc_deletion_in_session(
            session,
            storage,
            asset_id=asset_id,
            digest_key_id="t1e-test-key-v1",
            digest_key=b"k" * 32,
            deleted_actor="t1e-postgres-test",
        )
        tombstone_id = tombstone.id
    with Session(engine) as session:
        asset = session.get(MediaAsset, asset_id)
        record = session.get(MediaGcDeletionRecord, asset_id)
        tombstone = session.get(AssetTombstone, tombstone_id)
        assert asset is not None and asset.state == "deleted"
        assert record is not None and record.inode is None and not record.file_present
        assert tombstone is not None and tombstone.original_asset_id == asset_id
        assert path not in tombstone.digest


def test_ready_publication_service_reverifies_inode_and_single_owner(
    engine: Engine, tmp_path: Path
) -> None:
    models_root = tmp_path / "models"
    media_root = tmp_path / "media"
    models_root.mkdir()
    media_root.mkdir()
    storage = NarrationStorage(models_root=models_root, media_root=media_root)
    payload = f"ready-publication-evidence-{uuid4()}".encode("ascii")
    digest = hashlib.sha256(payload).hexdigest()
    novel_id, asset_id = uuid4(), uuid4()
    published = storage.publish_media(
        [payload],
        asset_id=asset_id,
        expected_sha256=digest,
        expected_size=len(payload),
        extension="wav",
        max_bytes=len(payload),
    )
    connection = engine.connect()
    transaction = connection.begin()
    try:
        connection.execute(
            text("INSERT INTO novels (id,title,description,version) VALUES (:id,:title,'',1)"),
            {"id": novel_id, "title": f"t1e-publish-{novel_id}"},
        )
        connection.execute(
            text(
                """
                INSERT INTO media_assets
                  (id,owner_id,workspace_id,novel_id,kind,asset_class,storage_backend,
                   state,retention_policy,checksum_algorithm,validation_json,gc_generation,
                   storage_path,content_hash,metadata_json)
                VALUES
                  (:id,:owner,:workspace,:novel,'narration_preview','preview','local',
                   'staging','derivable','sha256','{}'::jsonb,0,:path,:digest,'{}'::jsonb)
                """
            ),
            {
                "id": asset_id,
                "owner": OWNER,
                "workspace": WORKSPACE,
                "novel": novel_id,
                "path": published.relative_path,
                "digest": digest,
            },
        )
        forged = PublishedFile(
            asset_id=asset_id,
            relative_path=published.relative_path,
            actual_sha256=published.actual_sha256,
            byte_size=published.byte_size,
            strong_etag=published.strong_etag,
            device=published.device,
            inode=published.inode + 1,
        )
        with Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        ) as session, session.begin():
            with pytest.raises(MediaConflict):
                apply_ready_evidence_in_session(
                    session,
                    storage,
                    asset_id=asset_id,
                    published=forged,
                    mime_type="audio/wav",
                )
            asset = apply_ready_evidence_in_session(
                session,
                storage,
                asset_id=asset_id,
                published=published,
                mime_type="audio/wav",
                validation={"decoder": "pending-t1-g"},
            )
            assert asset.state == "ready"
        with Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
        ) as session, session.begin():
            asset = session.get(MediaAsset, asset_id)
            assert asset is not None and asset.state == "ready"
            assert asset.byte_size == len(payload)
            assert asset.validation_json["filesystem_inode"] == published.inode
            decision = plan_media_read_in_session(
                session, storage, asset_id=asset_id, method="HEAD"
            )
            assert decision.status == 200 and not decision.send_body
    finally:
        if transaction.is_active:
            transaction.rollback()
        connection.close()


def test_gc_first_commit_makes_late_cover_reference_fail_closed(engine: Engine) -> None:
    novel_id, asset_id, path, digest, byte_size = _load_gc_fixture(
        engine,
        GC_FIRST_FIXTURE_ID,
        expected_state="ready",
        expected_generation=1,
    )
    assert digest == "14" * 32
    assert path == _asset_path(asset_id, digest)
    assert byte_size == 4
    worker_name = f"t1e-ref-{uuid4()}"

    def late_reference() -> None:
        with engine.begin() as connection:
            _set_worker_name(connection, worker_name)
            connection.execute(
                text("UPDATE novels SET cover_asset_id=:asset WHERE id=:novel"),
                {"asset": asset_id, "novel": novel_id},
            )

    connection = engine.connect()
    transaction = connection.begin()
    try:
        _insert_gc_plan(
            connection,
            novel_id=novel_id,
            asset_id=asset_id,
            path=path,
            digest=digest,
            byte_size=byte_size,
            generation=1,
        )
        connection.execute(
            text("UPDATE media_assets SET state='deleting' WHERE id=:id"),
            {"id": asset_id},
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(late_reference)
            _wait_until_lock_wait(engine, worker_name)
            transaction.commit()
            with pytest.raises(DBAPIError):
                future.result(timeout=10)
    finally:
        if transaction.is_active:
            transaction.rollback()
        connection.close()
    with engine.connect() as check:
        assert check.scalar(
            text("SELECT state FROM media_assets WHERE id=:id"), {"id": asset_id}
        ) == "deleting"
        assert check.scalar(
            text("SELECT cover_asset_id FROM novels WHERE id=:id"), {"id": novel_id}
        ) is None
        assert check.scalar(
            text("SELECT count(*) FROM media_gc_deletion_plans WHERE asset_id=:id"),
            {"id": asset_id},
        ) == 1


def test_reference_first_commit_makes_gc_transition_fail_closed(engine: Engine) -> None:
    novel_id, asset_id, path, digest, byte_size = _load_gc_fixture(
        engine,
        REFERENCE_FIRST_FIXTURE_ID,
        expected_state="ready",
        expected_generation=1,
    )
    assert digest == "13" * 32
    assert path == _asset_path(asset_id, digest)
    assert byte_size == 4
    worker_name = f"t1e-gc-{uuid4()}"

    def late_gc() -> None:
        with engine.begin() as worker:
            _set_worker_name(worker, worker_name)
            _insert_gc_plan(
                worker,
                novel_id=novel_id,
                asset_id=asset_id,
                path=path,
                digest=digest,
                byte_size=byte_size,
                generation=1,
            )
            worker.execute(
                text("UPDATE media_assets SET state='deleting' WHERE id=:id"),
                {"id": asset_id},
            )

    connection = engine.connect()
    transaction = connection.begin()
    try:
        connection.execute(
            text("UPDATE novels SET cover_asset_id=:asset WHERE id=:novel"),
            {"asset": asset_id, "novel": novel_id},
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(late_gc)
            _wait_until_lock_wait(engine, worker_name)
            transaction.commit()
            with pytest.raises(DBAPIError):
                future.result(timeout=10)
    finally:
        if transaction.is_active:
            transaction.rollback()
        connection.close()
    with engine.connect() as check:
        assert check.scalar(
            text("SELECT state FROM media_assets WHERE id=:id"), {"id": asset_id}
        ) == "ready"
        assert check.scalar(
            text("SELECT cover_asset_id FROM novels WHERE id=:id"), {"id": novel_id}
        ) == asset_id
        assert check.scalar(
            text("SELECT count(*) FROM media_gc_deletion_plans WHERE asset_id=:id"),
            {"id": asset_id},
        ) == 0
