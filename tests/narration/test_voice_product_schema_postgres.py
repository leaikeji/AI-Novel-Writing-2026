"""Schema and optional PostgreSQL gates for the T4 product voice pipeline.

The live checks are skipped unless the existing exact disposable TTS database
is configured.  They never migrate, truncate, or commit test evidence.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.schema import CreateTable

from backend.models import (
    ActiveJobAsset,
    Base,
    VoiceActionReceipt,
    VoicePreview,
    VoiceReferenceAssetLink,
)
from backend.narration.contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (
    ROOT
    / "backend/migrations/versions/20260827_0021_voice_product_pipeline.py"
)
REVISION = "20260827_0021"
DOWN_REVISION = "20260827_0020"
HEAD_REVISION = "20260829_0032"
EXPECTED_DATABASE = "ai_novel_world_2026_tts_test"
EXPECTED_USER = "tts_test"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _constraint_names(table_name: str) -> set[str]:
    return {
        str(constraint.name)
        for constraint in Base.metadata.tables[table_name].constraints
        if constraint.name is not None
    }


def _index_names(table_name: str) -> set[str]:
    return {
        str(index.name)
        for index in Base.metadata.tables[table_name].indexes
        if index.name is not None
    }


def test_voice_product_revision_is_followed_by_official_preset_and_retry_head() -> None:
    scripts = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert scripts.get_heads() == [HEAD_REVISION]
    assert scripts.get_revision(HEAD_REVISION).down_revision == "20260829_0031"
    assert scripts.get_revision("20260829_0031").down_revision == "20260829_0030"
    assert scripts.get_revision("20260829_0030").down_revision == "20260829_0029"
    assert scripts.get_revision("20260829_0029").down_revision == "20260829_0028"
    assert scripts.get_revision("20260827_0023").down_revision == "20260827_0022"
    assert scripts.get_revision("20260827_0022").down_revision == REVISION
    assert scripts.get_revision(REVISION).down_revision == DOWN_REVISION


def test_voice_product_orm_names_columns_and_constraints_are_frozen() -> None:
    expected_columns = {
        "voice_action_receipts": {
            "id",
            "owner_id",
            "workspace_id",
            "operation",
            "idempotency_key",
            "request_hash",
            "resource_id",
            "state",
            "reserved_at",
            "completed_at",
        },
        "voice_reference_asset_links": {
            "id",
            "owner_id",
            "workspace_id",
            "novel_id",
            "profile_id",
            "voice_version_id",
            "rights_record_id",
            "source_asset_id",
            "reference_asset_id",
            "normalization_fingerprint",
            "validation_fingerprint",
            "created_at",
        },
        "voice_previews": {
            "id",
            "owner_id",
            "workspace_id",
            "novel_id",
            "profile_id",
            "version_id",
            "rights_record_id",
            "job_id",
            "reference_asset_id",
            "result_asset_id",
            "preview_text",
            "preview_text_digest_key_id",
            "preview_text_digest",
            "model_fingerprint",
            "reference_fingerprint",
            "parameters_fingerprint",
            "request_fingerprint",
            "status",
            "started_at",
            "completed_at",
            "expires_at",
            "failure_code",
            "created_at",
            "updated_at",
        },
    }
    assert VoiceActionReceipt.__tablename__ == "voice_action_receipts"
    assert VoiceReferenceAssetLink.__tablename__ == "voice_reference_asset_links"
    assert VoicePreview.__tablename__ == "voice_previews"
    assert VoicePreview.__table__.c.reference_asset_id.nullable is True
    assert VoiceReferenceAssetLink.__table__.c.reference_asset_id.nullable is False
    for table_name, names in expected_columns.items():
        assert {column.name for column in Base.metadata.tables[table_name].columns} == names

    assert {
        "uq_voice_action_receipt_idempotency",
        "uq_voice_action_receipt_resource",
        "ck_voice_action_receipt_request_hash",
        "ck_voice_action_receipt_lifecycle",
    } <= _constraint_names("voice_action_receipts")
    assert {
        "fk_voice_reference_link_version_profile",
        "uq_voice_reference_link_version",
        "ck_voice_reference_link_normalization_fingerprint",
        "ck_voice_reference_link_validation_fingerprint",
    } <= _constraint_names("voice_reference_asset_links")
    assert {
        "fk_voice_preview_version_profile",
        "uq_voice_preview_job",
        "ck_voice_preview_lifecycle_shape",
        "ck_voice_preview_fingerprints",
        "ck_voice_preview_text_digest",
    } <= _constraint_names("voice_previews")
    assert {
        "ix_voice_reference_links_source_asset",
        "ix_voice_reference_links_reference_asset",
    } <= _index_names("voice_reference_asset_links")
    assert {
        "ix_voice_previews_reference_asset",
        "ix_voice_previews_result_asset",
        "ix_voice_previews_expiry",
    } <= _index_names("voice_previews")


def test_library_active_job_asset_scope_is_nullable_and_deferred() -> None:
    table = ActiveJobAsset.__table__
    assert table.c.novel_id.nullable is True
    foreign_keys = {
        constraint.name: constraint
        for constraint in table.foreign_key_constraints
    }
    for name in (
        "fk_active_job_asset_job_scope",
        "fk_active_job_asset_media_scope",
    ):
        constraint = foreign_keys[name]
        assert constraint.deferrable is True
        assert constraint.initially == "DEFERRED"


def test_new_tables_compile_for_the_postgresql_dialect() -> None:
    dialect = postgresql.dialect()
    for model in (VoiceActionReceipt, VoiceReferenceAssetLink, VoicePreview):
        ddl = str(CreateTable(model.__table__).compile(dialect=dialect))
        assert f"CREATE TABLE {model.__tablename__}" in ddl
        assert "UUID" in ddl
        assert "TIMESTAMP WITH TIME ZONE" in ddl
        assert "JSON" not in ddl


def test_migration_is_io_free_fix_forward_and_contains_all_database_guards() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert "from backend.models" not in source
    assert "create_engine" not in source
    assert "subprocess" not in source
    assert "requests." not in source
    for marker in (
        'revision = "20260827_0021"',
        'down_revision = "20260827_0020"',
        "voice_action_receipts",
        "voice_reference_asset_links",
        "voice_previews",
        "reserved','completed",
        "queued','running','ready','failed','cancelled",
        "preview_text IS NULL",
        "narration_guard_voice_preview_lifecycle_v1",
        "narration_guard_voice_preview_scope_v1",
        "narration_guard_voice_preview_job_closure_v1",
        "narration_guard_active_job_asset_scope_v2",
        "IS NOT DISTINCT FROM",
        "DEFERRABLE INITIALLY DEFERRED",
        "narration_voice_reference_source",
        "narration_voice_reference",
        "narration_voice_preview",
        "r.source_kind='user_upload'",
        "uploaded_original",
        "locked_voice",
        "temporary_preview",
        "narration_media_has_live_reference",
        "voice downgrade refused",
    ):
        assert marker in source


def _live_url() -> str:
    raw = os.environ.get("TTS_TEST_DATABASE_URL", "").strip()
    if not raw:
        pytest.skip("TTS_TEST_DATABASE_URL is not configured")
    parsed = make_url(raw)
    if (
        not parsed.drivername.startswith("postgresql")
        or parsed.database != EXPECTED_DATABASE
        or parsed.username != EXPECTED_USER
        or parsed.host not in LOOPBACK_HOSTS
    ):
        raise RuntimeError(
            "voice product schema tests require the exact loopback disposable database"
        )
    production = os.environ.get("AI_NOVEL_DATABASE_URL", "").strip()
    if production:
        production_url = make_url(production)
        if (parsed.host, parsed.port, parsed.database) == (
            production_url.host,
            production_url.port,
            production_url.database,
        ):
            raise RuntimeError("voice product schema tests refuse the production database")
    return raw


@pytest.fixture(scope="module")
def engine() -> Engine:
    database = create_engine(_live_url(), pool_pre_ping=True)
    try:
        with database.connect() as connection:
            identity = connection.execute(
                text("SELECT current_database(), current_user, version()")
            ).one()
            assert identity[0] == EXPECTED_DATABASE
            assert identity[1] == EXPECTED_USER
            assert "PostgreSQL 18" in identity[2]
            assert connection.scalar(
                text("SELECT version_num FROM alembic_version")
            ) == REVISION
        yield database
    finally:
        database.dispose()


def test_live_postgres_has_expected_tables_triggers_and_nullable_scope(
    engine: Engine,
) -> None:
    inspector = inspect(engine)
    assert {
        "voice_action_receipts",
        "voice_reference_asset_links",
        "voice_previews",
    } <= set(inspector.get_table_names())
    active_columns = {
        column["name"]: column for column in inspector.get_columns("active_job_assets")
    }
    assert active_columns["novel_id"]["nullable"] is True
    with engine.connect() as connection:
        trigger_names = set(
            connection.scalars(
                text(
                    "SELECT tgname FROM pg_trigger "
                    "WHERE NOT tgisinternal AND tgname LIKE 'trg_t4_%'"
                )
            )
        )
        assert {
            "trg_t4_voice_action_receipt_guard",
            "trg_t4_voice_reference_link_scope",
            "trg_t4_voice_preview_lifecycle",
            "trg_t4_voice_preview_scope",
            "trg_t4_voice_preview_job_closure",
            "trg_t4_active_job_asset_scope_v2",
        } <= trigger_names
        live_reference_function = connection.scalar(
            text(
                "SELECT pg_get_functiondef('narration_media_has_live_reference(uuid)'::regprocedure)"
            )
        )
        assert "voice_reference_asset_links" in live_reference_function
        assert "voice_previews" in live_reference_function


def test_live_receipt_is_reservable_completable_and_then_immutable(
    engine: Engine,
) -> None:
    receipt_id = uuid4()
    resource_id = uuid4()
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(
                text(
                    "INSERT INTO voice_action_receipts "
                    "(id,owner_id,workspace_id,operation,idempotency_key,request_hash,"
                    " resource_id,state) "
                    "VALUES (:id,:owner,:workspace,'create_voice_profile',:key,:hash,"
                    " :resource,'reserved')"
                ),
                {
                    "id": receipt_id,
                    "owner": LOCAL_OWNER_ID,
                    "workspace": LOCAL_WORKSPACE_ID,
                    "key": f"voice-schema-{uuid4().hex}",
                    "hash": "a" * 64,
                    "resource": resource_id,
                },
            )
            connection.execute(
                text(
                    "UPDATE voice_action_receipts "
                    "SET state='completed',completed_at=clock_timestamp() WHERE id=:id"
                ),
                {"id": receipt_id},
            )
            state = connection.execute(
                text(
                    "SELECT state,resource_id,completed_at IS NOT NULL "
                    "FROM voice_action_receipts WHERE id=:id"
                ),
                {"id": receipt_id},
            ).one()
            assert state == ("completed", resource_id, True)

            savepoint = connection.begin_nested()
            try:
                with pytest.raises(DBAPIError):
                    connection.execute(
                        text(
                            "UPDATE voice_action_receipts SET request_hash=:hash WHERE id=:id"
                        ),
                        {"id": receipt_id, "hash": "b" * 64},
                    )
            finally:
                savepoint.rollback()
        finally:
            transaction.rollback()


def _fingerprint(value: object) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _insert_ready_voice_asset(
    connection,
    *,
    asset_id,
    kind: str,
    asset_class: str,
    retention_policy: str,
    content_hash: str,
) -> None:
    relative_path = (
        f"assets/{asset_id.hex[:2]}/{asset_id.hex}/{content_hash}.wav"
    )
    connection.execute(
        text(
            "INSERT INTO media_assets "
            "(id,owner_id,workspace_id,novel_id,kind,asset_class,mime_type,"
            " byte_size,duration_ms,sample_rate,channels,storage_backend,state,"
            " retention_policy,checksum_algorithm,validation_json,verified_at,"
            " storage_path,content_hash,metadata_json) "
            "VALUES (:id,:owner,:workspace,NULL,:kind,:class,'audio/wav',4,1000,"
            " 48000,2,'local','ready',:retention,'sha256','{}'::jsonb,"
            " clock_timestamp(),:path,:hash,'{}'::jsonb)"
        ),
        {
            "id": asset_id,
            "owner": LOCAL_OWNER_ID,
            "workspace": LOCAL_WORKSPACE_ID,
            "kind": kind,
            "class": asset_class,
            "retention": retention_policy,
            "path": relative_path,
            "hash": content_hash,
        },
    )


def _insert_library_uploaded_version(connection, *, wrong_source_class: bool = False):
    source_id = uuid4()
    reference_id = uuid4()
    rights_id = uuid4()
    profile_id = uuid4()
    version_id = uuid4()
    link_id = uuid4()
    rights_event_id = uuid4()
    source_hash = _fingerprint(source_id)
    reference_hash = _fingerprint(reference_id)
    _insert_ready_voice_asset(
        connection,
        asset_id=source_id,
        kind=(
            "narration_voice_reference"
            if wrong_source_class
            else "narration_voice_reference_source"
        ),
        asset_class="voice_reference" if wrong_source_class else "source",
        retention_policy="locked_voice" if wrong_source_class else "uploaded_original",
        content_hash=source_hash,
    )
    _insert_ready_voice_asset(
        connection,
        asset_id=reference_id,
        kind="narration_voice_reference",
        asset_class="voice_reference",
        retention_policy="locked_voice",
        content_hash=reference_hash,
    )
    connection.execute(
        text(
            "INSERT INTO voice_rights_records "
            "(id,owner_id,workspace_id,novel_id,source_kind,source_identifier,"
            " notice_version,purpose,commercial_use,redistribution,voice_cloning,"
            " confirmed_actor,confirmed_at,risk_flags_json) "
            "VALUES (:id,:owner,:workspace,NULL,'user_upload','private-test-source',"
            " 'voice-rights/1','private_tts',false,false,true,'schema-test',"
            " clock_timestamp(),'[]'::jsonb)"
        ),
        {
            "id": rights_id,
            "owner": LOCAL_OWNER_ID,
            "workspace": LOCAL_WORKSPACE_ID,
        },
    )
    connection.execute(
        text(
            "INSERT INTO voice_rights_events "
            "(id,rights_record_id,event_key,event_type,actor,occurred_at) "
            "VALUES (:id,:rights,'schema-test-confirmed','confirmed','schema-test',"
            " clock_timestamp())"
        ),
        {"id": rights_event_id, "rights": rights_id},
    )
    connection.execute(
        text(
            "INSERT INTO voice_profiles "
            "(id,owner_id,workspace_id,novel_id,name,status,version) "
            "VALUES (:id,:owner,:workspace,NULL,'schema-test','draft',1)"
        ),
        {
            "id": profile_id,
            "owner": LOCAL_OWNER_ID,
            "workspace": LOCAL_WORKSPACE_ID,
        },
    )
    connection.execute(
        text(
            "INSERT INTO voice_profile_versions "
            "(id,profile_id,owner_id,workspace_id,version_number,source_type,state,"
            " provider_id,model_id,model_revision,reference_asset_id,rights_record_id,"
            " language,parameters_json,fingerprint,quality_state) "
            "VALUES (:id,:profile,:owner,:workspace,1,'uploaded','draft','moss',"
            " 'OpenMOSS-Team/MOSS-TTS-Nano','schema-test',:reference,:rights,"
            " 'zh-CN','{}'::jsonb,:fingerprint,'pending')"
        ),
        {
            "id": version_id,
            "profile": profile_id,
            "owner": LOCAL_OWNER_ID,
            "workspace": LOCAL_WORKSPACE_ID,
            "reference": reference_id,
            "rights": rights_id,
            "fingerprint": _fingerprint(version_id),
        },
    )
    connection.execute(
        text(
            "INSERT INTO voice_reference_asset_links "
            "(id,owner_id,workspace_id,novel_id,profile_id,voice_version_id,"
            " rights_record_id,source_asset_id,reference_asset_id,"
            " normalization_fingerprint,validation_fingerprint) "
            "VALUES (:id,:owner,:workspace,NULL,:profile,:version,:rights,:source,"
            " :reference,:normalization,:validation)"
        ),
        {
            "id": link_id,
            "owner": LOCAL_OWNER_ID,
            "workspace": LOCAL_WORKSPACE_ID,
            "profile": profile_id,
            "version": version_id,
            "rights": rights_id,
            "source": source_id,
            "reference": reference_id,
            "normalization": _fingerprint(f"normalize:{link_id}"),
            "validation": _fingerprint(f"validate:{link_id}"),
        },
    )
    return profile_id, version_id, rights_id, reference_id, reference_hash, link_id


def test_live_reference_fingerprint_is_composite_not_media_sha256(
    engine: Engine,
) -> None:
    """A canonical reference fingerprint may intentionally differ from byte SHA."""

    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            (
                profile_id,
                version_id,
                rights_id,
                reference_id,
                reference_hash,
                link_id,
            ) = _insert_library_uploaded_version(connection)
            job_id = uuid4()
            preview_id = uuid4()
            composite_reference_fingerprint = _fingerprint(
                f"{version_id}:{link_id}:{reference_id}:normalization:validation"
            )
            assert composite_reference_fingerprint != reference_hash
            connection.execute(
                text(
                    "INSERT INTO background_jobs "
                    "(id,owner_id,workspace_id,novel_id,request_id,request_allows_render,"
                    " job_kind,input_hash,idempotency_key,resource_class,base_priority,"
                    " state,max_attempts,attempt_count,progress_current) "
                    "VALUES (:id,:owner,:workspace,NULL,NULL,NULL,"
                    " 'narration.voice_preview',:hash,:key,'moss-nano',0,'queued',3,0,0)"
                ),
                {
                    "id": job_id,
                    "owner": LOCAL_OWNER_ID,
                    "workspace": LOCAL_WORKSPACE_ID,
                    "hash": _fingerprint(job_id),
                    "key": f"voice-preview-job-{uuid4().hex}",
                },
            )
            connection.execute(
                text(
                    "INSERT INTO voice_previews "
                    "(id,owner_id,workspace_id,novel_id,profile_id,version_id,"
                    " rights_record_id,job_id,reference_asset_id,preview_text,"
                    " preview_text_digest_key_id,preview_text_digest,model_fingerprint,"
                    " reference_fingerprint,parameters_fingerprint,request_fingerprint,"
                    " status) "
                    "VALUES (:id,:owner,:workspace,NULL,:profile,:version,:rights,:job,"
                    " :reference,'仅用于数据库闭包测试','schema-test-key',:text_digest,"
                    " :model,:reference_fingerprint,:parameters,:request,'queued')"
                ),
                {
                    "id": preview_id,
                    "owner": LOCAL_OWNER_ID,
                    "workspace": LOCAL_WORKSPACE_ID,
                    "profile": profile_id,
                    "version": version_id,
                    "rights": rights_id,
                    "job": job_id,
                    "reference": reference_id,
                    "text_digest": _fingerprint("private preview text"),
                    "model": _fingerprint("moss-nano:model"),
                    "reference_fingerprint": composite_reference_fingerprint,
                    "parameters": _fingerprint("{}"),
                    "request": _fingerprint(preview_id),
                },
            )
            connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
            assert connection.scalar(
                text("SELECT reference_fingerprint FROM voice_previews WHERE id=:id"),
                {"id": preview_id},
            ) == composite_reference_fingerprint
        finally:
            transaction.rollback()


def test_live_reference_link_rejects_wrong_media_class_at_deferred_gate(
    engine: Engine,
) -> None:
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            _insert_library_uploaded_version(connection, wrong_source_class=True)
            with pytest.raises(DBAPIError, match="closure mismatch"):
                connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        finally:
            transaction.rollback()
