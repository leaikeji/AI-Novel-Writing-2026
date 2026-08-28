from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError

from backend.models import Base
from backend.narration.contracts import (
    BLOCKER_CODES,
    LOCAL_OWNER_ID,
    LOCAL_WORKSPACE_ID,
    WARNING_CODES,
)


ROOT = Path(__file__).resolve().parents[2]
REVISION = "20260826_0010"
DOWN_REVISION = "20260825_0009"
HEAD_REVISION = "20260828_0024"
FAILED_SEGMENT_RETRY_REVISION = "20260828_0024"
VOICE_PREVIEW_RETRY_REVISION = "20260827_0023"
OFFICIAL_PRESET_REVISION = "20260827_0022"
VOICE_PRODUCT_REVISION = "20260827_0021"
SCRIPT_REVIEW_REVISION = "20260827_0020"
MODEL_RUN_CANCEL_REVISION = "20260827_0019"
RENDER_DIGEST_REVISION = "20260827_0018"
GENERATION_GUARD_REVISION = "20260827_0017"
CHARACTER_PROFILE_REVISION = "20260826_0016"
NARRATION_CONCURRENCY_REVISION = "20260826_0015"
MEDIA_SAFETY_REVISION = "20260826_0011"
EXECUTION_SAFETY_REVISION = "20260826_0012"
ASSET_PATH_REVISION = "20260826_0013"
REQUEST_SOURCE_SEALING_REVISION = "20260826_0014"
MIGRATION = ROOT / "backend/migrations/versions/20260826_0010_narration_foundation.py"
CONCURRENCY_MIGRATION = (
    ROOT
    / "backend/migrations/versions/20260826_0015_narration_domain_concurrency_guards.py"
)
GENERATION_GUARD_MIGRATION = (
    ROOT
    / "backend/migrations/versions/20260827_0017_narration_generation_transaction_guards.py"
)
RENDER_DIGEST_MIGRATION = (
    ROOT
    / "backend/migrations/versions/20260827_0018_narration_render_digest_key.py"
)
MODEL_RUN_CANCEL_MIGRATION = (
    ROOT
    / "backend/migrations/versions/20260827_0019_model_run_cancel_fence.py"
)
SCRIPT_REVIEW_ACTION_MIGRATION = (
    ROOT
    / "backend/migrations/versions/20260827_0020_narration_script_review_actions.py"
)
VOICE_PRODUCT_MIGRATION = (
    ROOT
    / "backend/migrations/versions/20260827_0021_voice_product_pipeline.py"
)
OFFICIAL_PRESET_MIGRATION = (
    ROOT
    / "backend/migrations/versions/20260827_0022_official_preset_previews.py"
)
VOICE_PREVIEW_RETRY_MIGRATION = (
    ROOT
    / "backend/migrations/versions/20260827_0023_voice_preview_retry_transition.py"
)
FAILED_SEGMENT_RETRY_MIGRATION = (
    ROOT
    / "backend/migrations/versions/20260828_0024_failed_segment_manual_retry.py"
)
EXPECTED_NEW_TABLES = {
    "narration_requests", "narration_request_sources", "novel_narration_settings",
    "narration_settings_snapshots", "narration_scope_overrides", "narration_cloud_consents",
    "voice_rights_records", "voice_rights_events", "voice_profiles", "voice_profile_versions",
    "character_aliases", "character_voice_bindings", "generic_voice_pools", "generic_voice_slots",
    "voice_casting_rules", "anonymous_speakers", "pronunciation_profiles", "pronunciation_entries",
    "narration_scripts", "narration_script_versions", "narration_script_issues", "narration_scenes",
    "narration_segments", "background_jobs", "background_job_attempts", "background_resource_locks",
    "model_run_records", "narration_editions", "narration_edition_segments",
    "narration_segment_renders", "narration_render_assets", "narration_exports",
    "narration_manifests", "narration_manifest_segments", "narration_edition_state",
    "document_narration_state", "narration_playback_progress", "voice_deletion_requests",
    "asset_tombstones", "narration_script_review_actions",
    "voice_action_receipts", "voice_reference_asset_links", "voice_previews",
}
FOUNDATION_TABLES = EXPECTED_NEW_TABLES - {"narration_script_review_actions"}


def _script_directory() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))


def test_revision_is_the_only_linear_head() -> None:
    scripts = _script_directory()
    assert scripts.get_heads() == [HEAD_REVISION]
    assert (
        scripts.get_revision(FAILED_SEGMENT_RETRY_REVISION).down_revision
        == VOICE_PREVIEW_RETRY_REVISION
    )
    assert (
        scripts.get_revision(VOICE_PREVIEW_RETRY_REVISION).down_revision
        == OFFICIAL_PRESET_REVISION
    )
    assert (
        scripts.get_revision(OFFICIAL_PRESET_REVISION).down_revision
        == VOICE_PRODUCT_REVISION
    )
    assert (
        scripts.get_revision(VOICE_PRODUCT_REVISION).down_revision
        == SCRIPT_REVIEW_REVISION
    )
    assert (
        scripts.get_revision(SCRIPT_REVIEW_REVISION).down_revision
        == MODEL_RUN_CANCEL_REVISION
    )
    assert (
        scripts.get_revision(MODEL_RUN_CANCEL_REVISION).down_revision
        == RENDER_DIGEST_REVISION
    )
    assert (
        scripts.get_revision(RENDER_DIGEST_REVISION).down_revision
        == GENERATION_GUARD_REVISION
    )
    assert (
        scripts.get_revision(GENERATION_GUARD_REVISION).down_revision
        == CHARACTER_PROFILE_REVISION
    )
    assert (
        scripts.get_revision(CHARACTER_PROFILE_REVISION).down_revision
        == NARRATION_CONCURRENCY_REVISION
    )
    assert (
        scripts.get_revision(NARRATION_CONCURRENCY_REVISION).down_revision
        == REQUEST_SOURCE_SEALING_REVISION
    )
    assert scripts.get_revision(REQUEST_SOURCE_SEALING_REVISION).down_revision == ASSET_PATH_REVISION
    assert scripts.get_revision(ASSET_PATH_REVISION).down_revision == EXECUTION_SAFETY_REVISION
    assert scripts.get_revision(EXECUTION_SAFETY_REVISION).down_revision == MEDIA_SAFETY_REVISION
    assert scripts.get_revision(MEDIA_SAFETY_REVISION).down_revision == REVISION
    assert scripts.get_revision(REVISION).down_revision == DOWN_REVISION


def test_voice_preview_retry_migration_is_narrow_fix_forward_and_io_free() -> None:
    source = VOICE_PREVIEW_RETRY_MIGRATION.read_text(encoding="utf-8")
    for forbidden in (
        "from backend.models",
        "create_engine",
        "requests.",
        "subprocess",
    ):
        assert forbidden not in source
    for marker in (
        'revision = "20260827_0023"',
        'down_revision = "20260827_0022"',
        "narration_guard_voice_preview_job_closure_v1",
        "'queued','running','retry_wait','cancel_requested'",
        "running queued retry exists",
    ):
        assert marker in source


def test_failed_segment_retry_migration_is_narrow_fix_forward_and_io_free() -> None:
    source = FAILED_SEGMENT_RETRY_MIGRATION.read_text(encoding="utf-8")
    for forbidden in (
        "from backend.models",
        "create_engine",
        "requests.",
        "subprocess",
        "op.create_table",
        "op.add_column",
        "op.drop_table",
        "op.drop_column",
    ):
        assert forbidden not in source
    for marker in (
        'revision = "20260828_0024"',
        'down_revision = "20260827_0023"',
        "narration_failed_segment_retry_authorized_v1",
        "c.state='pending'",
        "j.state='queued'",
        "j.job_kind='narration.segment_render'",
        "j.resource_class='moss-nano'",
        "j.owner_id=p_owner_id",
        "j.workspace_id=p_workspace_id",
        "j.novel_id=p_novel_id",
        "j.request_id=p_request_id",
        "OLD.state='failed' AND NEW.state='queued'",
        "OLD.state='unavailable' AND NEW.state='rendering'",
        "OLD.state='failed' AND NEW.state='pending'",
        "OLD.render_state='failed' AND NEW.render_state='queued'",
        "NEW.failure_code IS NULL",
        "DROP FUNCTION narration_failed_segment_retry_authorized_v1",
    ):
        assert marker in source


def test_failed_segment_retry_downgrade_restores_guards_without_retry_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _script_directory().get_revision(FAILED_SEGMENT_RETRY_REVISION).module
    statements: list[str] = []
    monkeypatch.setattr(module.op, "execute", lambda statement: statements.append(str(statement)))

    module._install_request_guard(allow_failed_segment_retry=False)
    module._install_render_guard(allow_failed_segment_retry=False)
    module._install_edition_guard(allow_failed_segment_retry=False)
    module._install_edition_segment_guard(allow_failed_segment_retry=False)

    assert len(statements) == 4
    assert all("narration_failed_segment_retry_authorized_v1(" not in sql for sql in statements)
    assert "OLD.state='analyzed'" in statements[0]
    assert "review_script_id" in statements[0]
    assert "unavailable edition is immutable" in statements[2]


def test_concurrency_migration_is_fix_forward_and_io_free() -> None:
    source = CONCURRENCY_MIGRATION.read_text(encoding="utf-8")
    assert "from backend.models" not in source
    assert "create_engine" not in source
    assert "requests." not in source
    assert "subprocess" not in source
    for marker in (
        "narration_guard_approved_child",
        "ORDER BY sv.id",
        "FOR UPDATE",
        "narration_lock_settings_aggregate",
        "trg_t1_narration_settings_aggregate_lock",
        "trg_t1_narration_override_aggregate_lock",
        "narration_lock_voice_rights_aggregate",
        "trg_t1_voice_rights_aggregate_lock",
        "_restore_0010_script_child_guard",
    ):
        assert marker in source


def test_generation_guard_migration_is_fix_forward_and_io_free() -> None:
    source = GENERATION_GUARD_MIGRATION.read_text(encoding="utf-8")
    assert "from backend.models" not in source
    assert "create_engine" not in source
    assert "requests." not in source
    assert "subprocess" not in source
    for marker in (
        "20260827_0017",
        "OLD.state='analyzed'",
        "NEW.state IN ('queued','cancel_requested','failed')",
        "uq_narration_segment_render_source_job",
        "DEFERRABLE INITIALLY DEFERRED",
        "trg_t4_generation_request_requires_edition",
        "trg_t4_edition_requires_generation_request",
        "generation request state requires an Edition in the same transaction",
        "Edition requires a compatible generation request in the same transaction",
    ):
        assert marker in source


def test_render_digest_migration_is_fix_forward_and_io_free() -> None:
    source = RENDER_DIGEST_MIGRATION.read_text(encoding="utf-8")
    assert "from backend.models" not in source
    assert "create_engine" not in source
    assert "requests." not in source
    assert "subprocess" not in source
    for marker in (
        "20260827_0018",
        "20260827_0017",
        "render_digest_key_id",
        "ck_narration_edition_segment_digest_key_id",
        "nullable=True",
    ):
        assert marker in source


def test_model_run_cancel_fence_migration_is_fix_forward_and_io_free() -> None:
    source = MODEL_RUN_CANCEL_MIGRATION.read_text(encoding="utf-8")
    assert "from backend.models" not in source
    assert "create_engine" not in source
    assert "requests." not in source
    assert "subprocess" not in source
    for marker in (
        "20260827_0019",
        "20260827_0018",
        "narration_guard_model_run_execution_fence",
        "job_state='cancel_requested'",
        "NEW.result_classification='cancelled'",
        "attempt_row.lease_until<=db_now",
        "lock_row.lease_generation",
    ):
        assert marker in source


def test_script_review_action_migration_is_fix_forward_and_io_free() -> None:
    source = SCRIPT_REVIEW_ACTION_MIGRATION.read_text(encoding="utf-8")
    assert "from backend.models" not in source
    assert "create_engine" not in source
    assert "import requests" not in source
    assert "subprocess" not in source
    for marker in (
        "20260827_0020",
        "20260827_0019",
        "review_script_id",
        "current_review_version_id",
        "narration_script_review_actions",
        "uq_narration_review_action_idempotency",
        "ck_narration_review_action_result_shape",
        "CREATE OR REPLACE FUNCTION narration_guard_request",
        "initial review pointer provenance is invalid",
        "review pointer CAS target is invalid",
        "trg_t4_review_action_required",
        "manual review continuation requires approval action and Edition",
        "OLD.state IS DISTINCT FROM 'queued' AND NEW.state='queued'",
        "queued narration request requires a proven review pointer",
        "uq_narration_review_action_request_version",
        "uq_narration_review_action_approve_request",
        "fk_narration_review_action_request_script",
        "fk_narration_review_action_edition_version",
        "CREATE FUNCTION narration_require_manual_script_approval_action()",
        "became_manual_approved",
        "trg_t4_manual_script_approval_required",
        "manual script approval requires action, Edition, and queued request",
        "trg_t4_review_action_target_required",
        "correction action does not match request final state",
        "0020 downgrade refused",
        "trg_t4_narration_script_review_actions_immutable",
    ):
        assert marker in source


def test_metadata_contains_the_complete_foundation_without_native_enums() -> None:
    assert EXPECTED_NEW_TABLES <= set(Base.metadata.tables)
    assert len(EXPECTED_NEW_TABLES) == 43
    for table_name in EXPECTED_NEW_TABLES:
        for column in Base.metadata.tables[table_name].columns:
            assert column.type.__class__.__name__ not in {"ENUM", "Enum"}


def test_critical_constraints_and_taxonomy_are_frozen() -> None:
    expected = {
        "narration_requests": {
            "fk_narration_request_novel_scope", "uq_narration_request_idempotency",
            "uq_narration_request_edition_guard", "uq_narration_request_render_guard",
            "uq_narration_request_full_render_guard",
            "fk_narration_request_review_script_document",
            "fk_narration_request_current_review_version",
            "uq_narration_request_review_script_guard",
            "ck_narration_request_review_pointer_shape",
        },
        "narration_script_review_actions": {
            "fk_narration_review_action_request_scope",
            "fk_narration_review_action_parent_version",
            "fk_narration_review_action_result_version",
            "fk_narration_review_action_result_edition",
            "fk_narration_review_action_request_script",
            "fk_narration_review_action_edition_version",
            "uq_narration_review_action_idempotency",
            "uq_narration_review_action_request_version",
            "ck_narration_review_action_result_shape",
            "ck_narration_review_action_idempotency_key",
        },
        "narration_editions": {
            "fk_narration_edition_request_guard", "fk_narration_edition_approved_guard",
            "fk_narration_edition_settings_scope", "fk_narration_edition_pronunciation_scope",
            "uq_narration_edition_request_guard",
        },
        "narration_segment_renders": {
            "fk_narration_segment_render_request_guard", "fk_narration_segment_render_novel_scope",
            "uq_narration_segment_render_source_job",
        },
        "narration_edition_segments": {
            "ck_narration_edition_segment_digest_key_id",
        },
        "narration_script_versions": {"fk_narration_script_version_parent_same_script"},
        "narration_exports": {"fk_narration_export_edition_request_guard"},
        "narration_playback_progress": {
            "fk_narration_playback_manifest_revision", "fk_narration_playback_edition_segment",
        },
    }
    for table_name, names in expected.items():
        actual = {constraint.name for constraint in Base.metadata.tables[table_name].constraints}
        assert names <= actual
    action_indexes = {
        index.name: index
        for index in Base.metadata.tables[
            "narration_script_review_actions"
        ].indexes
    }
    approve_index = action_indexes["uq_narration_review_action_approve_request"]
    assert approve_index.unique is True
    assert [column.name for column in approve_index.columns] == ["request_id"]
    assert str(approve_index.dialect_options["postgresql"]["where"]) == (
        "action_kind = 'approve'"
    )
    issue_checks = " ".join(
        str(constraint.sqltext)
        for constraint in Base.metadata.tables["narration_script_issues"].constraints
        if constraint.__class__.__name__ == "CheckConstraint"
    )
    for code in (*WARNING_CODES, *BLOCKER_CODES):
        assert code in issue_checks
    assert "narration-review-taxonomy/1" in issue_checks
    assert not Base.metadata.tables["narration_segment_renders"].c.novel_id.nullable
    assert not Base.metadata.tables["anonymous_speakers"].c.scope_id.nullable
    segment_checks = " ".join(
        str(constraint.sqltext)
        for constraint in Base.metadata.tables["narration_segments"].constraints
        if constraint.__class__.__name__ == "CheckConstraint"
    )
    assert "speaker_kind='character'" in segment_checks
    job_checks = " ".join(
        str(constraint.sqltext)
        for constraint in Base.metadata.tables["background_jobs"].constraints
        if constraint.__class__.__name__ == "CheckConstraint"
    )
    assert "request_id IS NOT NULL" in job_checks
    assert "novel_id IS NOT NULL" in job_checks
    snapshot_checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in Base.metadata.tables["narration_settings_snapshots"].constraints
        if constraint.__class__.__name__ == "CheckConstraint"
    }
    assert snapshot_checks["ck_narration_settings_snapshot_taxonomy_version"] == (
        "taxonomy_version = 'narration-review-taxonomy/1'"
    )
    script_checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in Base.metadata.tables["narration_script_versions"].constraints
        if constraint.__class__.__name__ == "CheckConstraint"
    }
    assert "approved_actor_type IS NOT NULL" in script_checks[
        "ck_narration_script_version_approved_shape"
    ]
    assert script_checks["ck_narration_script_version_taxonomy_version"] == (
        "taxonomy_version = 'narration-review-taxonomy/1'"
    )


def test_script_review_action_upgrade_and_downgrade_are_reverse_ordered() -> None:
    source = SCRIPT_REVIEW_ACTION_MIGRATION.read_text(encoding="utf-8")
    upgrade_source, downgrade_source = source.split("def downgrade() -> None:", 1)

    upgrade_markers = (
        'sa.Column("review_script_id", uuid_type, nullable=True)',
        'op.create_table(\n        "narration_script_review_actions"',
        "trg_t4_narration_script_review_actions_immutable",
        "CREATE FUNCTION narration_require_review_action()",
        "CREATE FUNCTION narration_require_manual_script_approval_action()",
        "CREATE FUNCTION narration_require_review_action_target()",
    )
    assert [upgrade_source.index(marker) for marker in upgrade_markers] == sorted(
        upgrade_source.index(marker) for marker in upgrade_markers
    )

    downgrade_markers = (
        "0020 downgrade refused",
        "DROP TRIGGER IF EXISTS trg_t4_review_action_target_required",
        "DROP TRIGGER IF EXISTS trg_t4_manual_script_approval_required",
        "DROP TRIGGER IF EXISTS trg_t4_review_action_required",
        "DROP TRIGGER IF EXISTS trg_t4_narration_script_review_actions_immutable",
        'op.drop_table("narration_script_review_actions")',
        'op.drop_column("narration_requests", "current_review_version_id")',
        "_install_request_guard(review_pointers=False)",
    )
    assert [downgrade_source.index(marker) for marker in downgrade_markers] == sorted(
        downgrade_source.index(marker) for marker in downgrade_markers
    )


def test_migration_is_a_frozen_no_io_snapshot_with_required_guards() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert "from backend.models" not in source
    assert "create_engine" not in source
    assert "requests." not in source
    assert "subprocess" not in source
    assert "LIMIT 1\" for name in NEW_TABLES" not in source
    for marker in (
        "narration_guard_approved_child", "narration_guard_generated_media",
        "narration_validate_scope", "narration_guard_cas",
        "approval_request_allows_edition", "T1-D downgrade refused",
        "uq_narration_request_full_render_guard", "fk_narration_edition_settings_scope",
        "fk_narration_edition_pronunciation_scope", "fk_narration_export_edition_request_guard",
        "ck_narration_segment_speaker_shape", "voice reference asset scope/class/state mismatch",
        "narration script version canonical identity is immutable",
        "voice profile version canonical identity is immutable",
        "render canonical input and scope are immutable",
        "trg_generic_voice_slot_immutable",
        "r.effective_policy=(row_data->>'effective_policy')",
        "r.effective_policy=sv.effective_policy",
        "edition segment voice scope/rights unavailable",
        "referenced volume narration scope is immutable",
        "referenced document narration scope is immutable",
        "referenced scene narration scope is immutable",
        "media source revision identity is immutable",
        "cancelled/quarantined render is immutable",
        "deleted media asset is immutable",
        "deleted voice version is immutable",
        "ready/cancelled/quarantined export is immutable",
        "unavailable edition is immutable",
        "ck_voice_profile_version_quality_state",
        "quality_state='accepted'",
        "ready/cancelled/quarantined edition segment is immutable",
        "es.render_state='ready'",
        "invalid edition state transition",
        "JOIN narration_segment_renders r ON r.id=ra.render_id",
        "e.asset_id=NEW.id AND e.state='ready'",
        "'allows_edition','allows_render'",
        "'state','is_approved','approval_kind'",
        "ck_narration_settings_snapshot_taxonomy_version",
        "ck_narration_script_version_taxonomy_version",
        "approved_actor_type IS NOT NULL AND approved_actor_id IS NOT NULL",
    ):
        assert marker in source
    scope_function = source.split("CREATE FUNCTION narration_validate_scope()", 1)[1].split(
        "CREATE FUNCTION narration_guard_edition_segment()", 1
    )[0]
    assert "NEW." not in scope_function
    assert "row_data jsonb := to_jsonb(NEW)" in scope_function
    for guarded_return in (
        "approved narration script is immutable", "locked voice version is immutable",
        "ready render is immutable",
    ):
        function_tail = source.split(guarded_return, 1)[1].split("END $$;", 1)[0]
        assert "IF TG_OP='DELETE' THEN RETURN OLD; END IF;" in function_tail
        assert "RETURN NEW;" in function_tail


def _live_url() -> str:
    raw = os.environ.get("TTS_TEST_DATABASE_URL", "").strip()
    if not raw:
        pytest.skip("TTS_TEST_DATABASE_URL is not configured; live PostgreSQL gate is pending")
    parsed = make_url(raw)
    if parsed.database != "ai_novel_world_2026_tts_test":
        raise RuntimeError("TTS_TEST_DATABASE_URL must target exactly ai_novel_world_2026_tts_test")
    production = os.environ.get("AI_NOVEL_DATABASE_URL", "").strip()
    if production:
        prod = make_url(production)
        if (parsed.host, parsed.port, parsed.database) == (prod.host, prod.port, prod.database):
            raise RuntimeError("TTS test database must differ from AI_NOVEL_DATABASE_URL")
    return raw


def _alembic_config(url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def _expect_db_rejection(connection, statement: str, parameters: dict[str, object]) -> None:
    savepoint = connection.begin_nested()
    with pytest.raises((IntegrityError, DBAPIError)):
        connection.execute(text(statement), parameters)
        savepoint.commit()
    if savepoint.is_active:
        savepoint.rollback()


def _assert_live_schema_matches_frozen_guards(connection) -> None:
    inspector = inspect(connection)

    def foreign_key(table: str, name: str) -> dict[str, object]:
        return next(item for item in inspector.get_foreign_keys(table) if item["name"] == name)

    render_guard = foreign_key("narration_segment_renders", "fk_narration_segment_render_request_guard")
    assert render_guard["constrained_columns"] == [
        "request_id", "owner_id", "workspace_id", "novel_id", "request_allows_render",
    ]
    assert render_guard["referred_columns"] == [
        "id", "owner_id", "workspace_id", "novel_id", "allows_render",
    ]
    assert foreign_key("narration_editions", "fk_narration_edition_settings_scope")["constrained_columns"] == [
        "settings_snapshot_id", "owner_id", "workspace_id", "novel_id",
    ]
    assert foreign_key("narration_editions", "fk_narration_edition_pronunciation_scope")["constrained_columns"] == [
        "pronunciation_profile_id", "novel_id",
    ]
    assert foreign_key("narration_exports", "fk_narration_export_edition_request_guard")["constrained_columns"] == [
        "edition_id", "request_id",
    ]
    assert foreign_key("narration_script_versions", "fk_narration_script_version_parent_same_script")["constrained_columns"] == [
        "script_id", "parent_version_id",
    ]
    columns = {column["name"]: column for column in inspector.get_columns("narration_segment_renders")}
    assert columns["novel_id"]["nullable"] is False
    anonymous = {column["name"]: column for column in inspector.get_columns("anonymous_speakers")}
    assert anonymous["scope_id"]["nullable"] is False
    checks = {item["name"] for item in inspector.get_check_constraints("narration_segments")}
    assert "ck_narration_segment_speaker_shape" in checks


def test_live_postgresql_upgrade_guards_and_conditional_rollback() -> None:
    """Full destructive gate, only for the exact disposable TTS database."""

    url = _live_url()
    engine = create_engine(url, pool_pre_ping=True)
    config = _alembic_config(url)
    old_database_url = os.environ.get("AI_NOVEL_DATABASE_URL")
    os.environ["AI_NOVEL_DATABASE_URL"] = url
    novel_a, novel_b, doc_a, doc_b, rev_a, rev_b, cover_a, cover_b = [uuid4() for _ in range(8)]
    volume_a, volume_b, polymorphic_doc = uuid4(), uuid4(), uuid4()
    try:
        with engine.connect() as connection:
            existing = inspect(connection).get_table_names()
            assert not existing, f"disposable TTS database is not empty: {existing}"
        command.upgrade(config, DOWN_REVISION)
        with engine.begin() as connection:
            for novel_id, title in ((novel_a, "tts-migration-a"), (novel_b, "tts-migration-b")):
                connection.execute(text("INSERT INTO novels (id,title,description,version) VALUES (:id,:title,'',1)"), {"id": novel_id, "title": title})
            for volume_id, novel_id, position in ((volume_a, novel_a, 1), (volume_b, novel_b, 2)):
                connection.execute(text("""INSERT INTO volumes (id,novel_id,title,position,version)
                    VALUES (:id,:novel,'volume',:position,1)"""),
                    {"id": volume_id, "novel": novel_id, "position": position})
            for document_id, novel_id, position in ((doc_a, novel_a, 1), (doc_b, novel_b, 1)):
                connection.execute(text("INSERT INTO documents (id,novel_id,kind,title,position) VALUES (:id,:novel,'chapter','chapter',:position)"), {"id": document_id, "novel": novel_id, "position": position})
            for revision_id, document_id, content_hash in ((rev_a, doc_a, "a" * 64), (rev_b, doc_b, "b" * 64)):
                connection.execute(text("INSERT INTO document_revisions (id,document_id,revision_number,content_markdown,content_text,content_hash,source) VALUES (:id,:document,1,'正文','正文',:hash,'manual')"), {"id": revision_id, "document": document_id, "hash": content_hash})
            for asset_id, novel_id, revision_id, content_hash in ((cover_a, novel_a, rev_a, "c" * 64), (cover_b, novel_b, rev_b, "d" * 64)):
                connection.execute(text("INSERT INTO media_assets (id,novel_id,source_revision_id,kind,storage_path,content_hash,metadata_json) VALUES (:id,:novel,:revision,'novel_cover',:path,:hash,'{}'::jsonb)"), {"id": asset_id, "novel": novel_id, "revision": revision_id, "path": f"covers/{asset_id}.png", "hash": content_hash})
                connection.execute(text("UPDATE novels SET cover_asset_id=:asset WHERE id=:novel"), {"asset": asset_id, "novel": novel_id})
        command.upgrade(config, REVISION)
        with engine.begin() as connection:
            _assert_live_schema_matches_frozen_guards(connection)
            rows = connection.execute(text("SELECT id,owner_id,workspace_id,cover_asset_id FROM novels ORDER BY title")).mappings().all()
            assert {row["owner_id"] for row in rows} == {LOCAL_OWNER_ID}
            assert {row["workspace_id"] for row in rows} == {LOCAL_WORKSPACE_ID}
            assert {row["cover_asset_id"] for row in rows} == {cover_a, cover_b}
            legacy = connection.execute(text(
                "SELECT kind,asset_class,content_hash FROM media_assets ORDER BY content_hash"
            )).all()
            assert legacy == [("novel_cover", None, "c" * 64), ("novel_cover", None, "d" * 64)]
            _expect_db_rejection(connection,
                "UPDATE document_revisions SET content_hash=:hash WHERE id=:id",
                {"id": rev_a, "hash": "9" * 64})
            _expect_db_rejection(connection,
                "UPDATE document_revisions SET document_id=:document,revision_number=2 WHERE id=:id",
                {"id": rev_a, "document": doc_b})
            _expect_db_rejection(connection,
                "DELETE FROM document_revisions WHERE id=:id", {"id": rev_a})
            volume_override = uuid4()
            connection.execute(text("""INSERT INTO narration_scope_overrides
                (id,novel_id,scope_kind,scope_id,settings_json,version)
                VALUES (:id,:novel,'volume',:volume,'{}'::jsonb,1)"""),
                {"id": volume_override, "novel": novel_a, "volume": volume_a})
            _expect_db_rejection(connection,
                "UPDATE volumes SET novel_id=:novel,position=3 WHERE id=:id",
                {"id": volume_a, "novel": novel_b})
            _expect_db_rejection(connection, "DELETE FROM volumes WHERE id=:id", {"id": volume_a})
            connection.execute(text("""INSERT INTO documents
                (id,novel_id,kind,title,position,status,version)
                VALUES (:id,:novel,'chapter','polymorphic-scope',9,'draft',1)"""),
                {"id": polymorphic_doc, "novel": novel_a})
            deleted_media_savepoint = connection.begin_nested()
            deleted_media = uuid4()
            connection.execute(text("""INSERT INTO media_assets
                (id,owner_id,workspace_id,novel_id,kind,asset_class,storage_path,content_hash,
                 metadata_json,state,deleted_at)
                VALUES (:id,:owner,:workspace,:novel,'narration_source','source',:path,:hash,
                        '{}'::jsonb,'deleted',now())"""),
                {"id": deleted_media, "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID,
                 "novel": novel_a, "path": f"tts/source/{deleted_media}.txt", "hash": "9" * 64})
            _expect_db_rejection(connection, """UPDATE media_assets
                SET state='ready',deleted_at=NULL,storage_path='tts/source/resurrected.txt'
                WHERE id=:id""", {"id": deleted_media})
            deleted_media_savepoint.rollback()
            _expect_db_rejection(connection,
                "UPDATE novels SET cover_asset_id=:cover WHERE id=:novel",
                {"cover": cover_b, "novel": novel_a})
            _expect_db_rejection(connection,
                "UPDATE media_assets SET novel_id=:novel WHERE id=:asset",
                {"asset": cover_a, "novel": novel_b})
            _expect_db_rejection(connection, """INSERT INTO media_assets
                (id,owner_id,workspace_id,novel_id,source_revision_id,kind,asset_class,
                 storage_path,content_hash,metadata_json,state)
                VALUES (:id,:owner,:workspace,:novel,:revision,'narration_source','source',
                        :path,:hash,'{}'::jsonb,'ready')""",
                {"id": uuid4(), "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID,
                 "novel": novel_a, "revision": rev_b, "path": "tts/source/mismatch.txt",
                 "hash": "0" * 64})

            request_id = uuid4()
            connection.execute(text("""INSERT INTO narration_requests
                (id,owner_id,workspace_id,novel_id,document_id,intent,request_hash,idempotency_key,
                 settings_fingerprint,force_review,effective_policy,state,version)
                VALUES (:id,:owner,:workspace,:novel,:document,'analyze_only',:hash,:key,:hash,false,'blockers_only','created',1)"""),
                {"id": request_id, "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID, "novel": novel_a, "document": doc_a, "hash": "e" * 64, "key": str(uuid4())})
            _expect_db_rejection(connection,
                "UPDATE narration_requests SET state='analyzing' WHERE id=:id",
                {"id": request_id})
            _expect_db_rejection(connection,
                "UPDATE narration_requests SET state='ready',version=2 WHERE id=:id",
                {"id": request_id})
            _expect_db_rejection(connection,
                "UPDATE narration_requests SET intent='create',version=2 WHERE id=:id",
                {"id": request_id})
            connection.execute(text("UPDATE narration_requests SET state='analyzing',version=2 WHERE id=:id"), {"id": request_id})
            connection.execute(text("UPDATE narration_requests SET state='analyzed',version=3 WHERE id=:id"), {"id": request_id})
            _expect_db_rejection(connection, """INSERT INTO narration_requests
                (id,owner_id,workspace_id,novel_id,document_id,intent,request_hash,idempotency_key,
                 settings_fingerprint,force_review,effective_policy,state,version)
                VALUES (:id,:owner,:workspace,:novel,:document,'analyze_only',:hash,:key,:hash,false,'blockers_only','created',1)""",
                {"id": uuid4(), "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID, "novel": novel_a, "document": doc_b, "hash": "f" * 64, "key": str(uuid4())})
            _expect_db_rejection(connection, """INSERT INTO narration_requests
                (id,owner_id,workspace_id,novel_id,intent,request_hash,idempotency_key,
                 settings_fingerprint,force_review,effective_policy,state,version)
                VALUES (:id,:owner,:workspace,:novel,'analyze_only',:hash,:key,:hash,false,
                        'blockers_only','analyzed',1)""",
                {"id": uuid4(), "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID,
                 "novel": novel_a, "hash": "f" * 64, "key": str(uuid4())})
            _expect_db_rejection(connection, """INSERT INTO narration_requests
                (id,owner_id,workspace_id,novel_id,intent,request_hash,idempotency_key,
                 settings_fingerprint,force_review,effective_policy,state,version)
                VALUES (:id,:owner,:workspace,:novel,'analyze_only',:hash,:key,:hash,true,
                        'blockers_only','created',1)""",
                {"id": uuid4(), "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID,
                 "novel": novel_a, "hash": "0" * 64, "key": str(uuid4())})

            generation_a, generation_b = uuid4(), uuid4()
            for generation_id, novel_id, marker in (
                (generation_a, novel_a, "2"), (generation_b, novel_b, "3"),
            ):
                connection.execute(text("""INSERT INTO narration_requests
                    (id,owner_id,workspace_id,novel_id,intent,request_hash,idempotency_key,
                     settings_fingerprint,force_review,effective_policy,state,version,
                     explicit_generation_intent_at,explicit_generation_actor)
                    VALUES (:id,:owner,:workspace,:novel,'batch',:hash,:key,:hash,false,
                            'blockers_only','created',1,now(),'owner')"""),
                    {"id": generation_id, "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID,
                     "novel": novel_id, "hash": marker * 64, "key": str(uuid4())})
            connection.execute(text("""INSERT INTO narration_request_sources
                (id,request_id,novel_id,document_id,revision_id,content_hash,position)
                VALUES (:id,:request,:novel,:document,:revision,:hash,0)"""),
                {"id": uuid4(), "request": generation_a, "novel": novel_a, "document": doc_a,
                 "revision": rev_a, "hash": "a" * 64})
            force_review_request = uuid4()
            connection.execute(text("""INSERT INTO narration_requests
                (id,owner_id,workspace_id,novel_id,intent,request_hash,idempotency_key,
                 settings_fingerprint,force_review,effective_policy,state,version,
                 explicit_generation_intent_at,explicit_generation_actor)
                VALUES (:id,:owner,:workspace,:novel,'batch',:hash,:key,:settings,true,
                        'always_review','created',1,now(),'owner')"""),
                {"id": force_review_request, "owner": LOCAL_OWNER_ID,
                 "workspace": LOCAL_WORKSPACE_ID, "novel": novel_a, "hash": "4" * 64,
                 "settings": "2" * 64, "key": str(uuid4())})
            connection.execute(text("""INSERT INTO narration_request_sources
                (id,request_id,novel_id,document_id,revision_id,content_hash,position)
                VALUES (:id,:request,:novel,:document,:revision,:hash,0)"""),
                {"id": uuid4(), "request": force_review_request, "novel": novel_a,
                 "document": doc_a, "revision": rev_a, "hash": "a" * 64})
            _expect_db_rejection(connection,
                "UPDATE narration_requests SET state='analyzing',version=2 WHERE id=:id",
                {"id": generation_b})
            _expect_db_rejection(connection, """INSERT INTO narration_request_sources
                (id,request_id,novel_id,document_id,revision_id,content_hash,position)
                VALUES (:id,:request,:novel,:document,:revision,:hash,0)""",
                {"id": uuid4(), "request": request_id, "novel": novel_a, "document": doc_a,
                 "revision": rev_a, "hash": "a" * 64})
            _expect_db_rejection(connection, """UPDATE narration_requests
                SET explicit_generation_actor='attacker',version=2 WHERE id=:id""",
                {"id": generation_a})
            scope_override_id = uuid4()
            connection.execute(text("""INSERT INTO narration_scope_overrides
                (id,novel_id,scope_kind,scope_id,settings_json,version)
                VALUES (:id,:novel,'chapter',:document,'{}'::jsonb,1)"""),
                {"id": scope_override_id, "novel": novel_a, "document": doc_a})
            _expect_db_rejection(connection, """UPDATE narration_scope_overrides
                SET novel_id=:novel,scope_id=:document,version=2 WHERE id=:id""",
                {"id": scope_override_id, "novel": novel_b, "document": doc_b})
            job_sql = """INSERT INTO background_jobs
                (id,owner_id,workspace_id,novel_id,request_id,request_allows_render,job_kind,
                 input_hash,idempotency_key,resource_class,base_priority,state,max_attempts,
                 attempt_count,progress_current)
                VALUES (:id,:owner,:workspace,:novel,:request,:allows,:kind,:hash,:key,
                        'tts',0,'queued',3,0,0)"""
            valid_job = uuid4()
            connection.execute(text(job_sql), {
                "id": valid_job, "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID,
                "novel": novel_a, "request": generation_a, "allows": True,
                "kind": "narration.analysis", "hash": "0" * 64, "key": str(uuid4()),
            })
            _expect_db_rejection(connection, job_sql.replace("'queued'", "'running'"), {
                "id": uuid4(), "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID,
                "novel": novel_a, "request": generation_a, "allows": True,
                "kind": "narration.analysis", "hash": "1" * 64, "key": str(uuid4()),
            })
            _expect_db_rejection(connection, """UPDATE background_jobs
                SET novel_id=:novel,request_id=:request,request_allows_render=true WHERE id=:id""",
                {"id": valid_job, "novel": novel_b, "request": generation_b})
            attempt_id, lease_token = uuid4(), uuid4()
            connection.execute(text("""INSERT INTO background_job_attempts
                (id,job_id,attempt_number,retry_kind,lease_owner,lease_token,lease_generation,
                 lease_until,started_at)
                VALUES (:id,:job,1,'initial','worker-a',:token,1,now()+interval '1 minute',now())"""),
                {"id": attempt_id, "job": valid_job, "token": lease_token})
            _expect_db_rejection(connection, """INSERT INTO background_job_attempts
                (id,job_id,attempt_number,retry_kind,lease_owner,lease_token,lease_generation,
                 lease_until,started_at)
                VALUES (:id,:job,2,'manual','worker-a',:token,1,now()+interval '1 minute',now())""",
                {"id": uuid4(), "job": valid_job, "token": uuid4()})
            connection.execute(text("""UPDATE background_job_attempts
                SET heartbeat_at=now(),lease_until=now()+interval '2 minutes' WHERE id=:id"""),
                {"id": attempt_id})
            _expect_db_rejection(connection,
                "UPDATE background_job_attempts SET lease_generation=2 WHERE id=:id", {"id": attempt_id})
            connection.execute(text("""UPDATE background_job_attempts
                SET completed_at=now(),actual_result_digest=:digest WHERE id=:id"""),
                {"id": attempt_id, "digest": "1" * 64})
            _expect_db_rejection(connection,
                "UPDATE background_job_attempts SET heartbeat_at=now() WHERE id=:id", {"id": attempt_id})
            _expect_db_rejection(connection, job_sql, {
                "id": uuid4(), "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID,
                "novel": novel_a, "request": None, "allows": True,
                "kind": "narration.segment_render", "hash": "4" * 64, "key": str(uuid4()),
            })
            _expect_db_rejection(connection, job_sql, {
                "id": uuid4(), "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID,
                "novel": novel_b, "request": generation_a, "allows": True,
                "kind": "narration.export", "hash": "5" * 64, "key": str(uuid4()),
            })
            _expect_db_rejection(connection, job_sql, {
                "id": uuid4(), "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID,
                "novel": novel_a, "request": request_id, "allows": True,
                "kind": "narration.segment_render", "hash": "6" * 64, "key": str(uuid4()),
            })

            rights_id = uuid4()
            connection.execute(text("""INSERT INTO voice_rights_records
                (id,owner_id,workspace_id,novel_id,source_kind,source_identifier,notice_version,purpose,
                 commercial_use,redistribution,voice_cloning,confirmed_actor,confirmed_at,risk_flags_json)
                VALUES (:id,:owner,:workspace,:novel,'uploaded','self','v1','private',false,false,true,'owner',now(),'[]'::jsonb)"""),
                {"id": rights_id, "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID, "novel": novel_a})
            _expect_db_rejection(connection, "UPDATE voice_rights_records SET purpose='changed' WHERE id=:id", {"id": rights_id})
            profile_id, voice_version_id = uuid4(), uuid4()
            connection.execute(text("""INSERT INTO voice_profiles
                (id,owner_id,workspace_id,novel_id,name,status,version)
                VALUES (:id,:owner,:workspace,:novel,'narrator','active',1)"""),
                {"id": profile_id, "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID, "novel": novel_a})
            voice_version_sql = """INSERT INTO voice_profile_versions
                (id,profile_id,owner_id,workspace_id,version_number,source_type,state,preset_key,
                 reference_asset_id,rights_record_id,language,parameters_json,fingerprint,quality_state)
                VALUES (:id,:profile,:owner,:workspace,:number,'preset','draft','preset-a',
                        :reference,:rights,'zh-CN','{}'::jsonb,:fingerprint,'pending')"""
            connection.execute(text(voice_version_sql), {
                "id": voice_version_id, "profile": profile_id, "owner": LOCAL_OWNER_ID,
                "workspace": LOCAL_WORKSPACE_ID, "number": 1, "reference": None,
                "rights": rights_id, "fingerprint": "7" * 64,
            })
            _expect_db_rejection(connection, voice_version_sql.replace("'pending'", "'unknown'"), {
                "id": uuid4(), "profile": profile_id, "owner": LOCAL_OWNER_ID,
                "workspace": LOCAL_WORKSPACE_ID, "number": 9, "reference": None,
                "rights": rights_id, "fingerprint": "b" * 64,
            })
            foreign_reference = uuid4()
            connection.execute(text("""INSERT INTO media_assets
                (id,owner_id,workspace_id,novel_id,kind,asset_class,storage_path,content_hash,metadata_json,state)
                VALUES (:id,:owner,:workspace,:novel,'narration_voice_reference','voice_reference',
                        :path,:hash,'{}'::jsonb,'ready')"""),
                {"id": foreign_reference, "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID,
                 "novel": novel_b, "path": f"tts/reference/{foreign_reference}.wav", "hash": "8" * 64})
            _expect_db_rejection(connection, voice_version_sql, {
                "id": uuid4(), "profile": profile_id, "owner": LOCAL_OWNER_ID,
                "workspace": LOCAL_WORKSPACE_ID, "number": 2, "reference": foreign_reference,
                "rights": rights_id, "fingerprint": "9" * 64,
            })
            _expect_db_rejection(connection, """INSERT INTO voice_profile_versions
                (id,profile_id,owner_id,workspace_id,version_number,source_type,state,preset_key,
                 rights_record_id,language,parameters_json,fingerprint,quality_state)
                VALUES (:id,:profile,:owner,:workspace,2,'preset','locked','preset-a',:rights,
                        'zh-CN','{}'::jsonb,:fingerprint,'accepted')""",
                {"id": uuid4(), "profile": profile_id, "owner": LOCAL_OWNER_ID,
                 "workspace": LOCAL_WORKSPACE_ID, "rights": rights_id, "fingerprint": "9" * 64})
            _expect_db_rejection(connection, """INSERT INTO voice_profile_versions
                (id,profile_id,owner_id,workspace_id,version_number,source_type,state,preset_key,
                 rights_record_id,language,parameters_json,fingerprint,quality_state,locked_actor,locked_at)
                VALUES (:id,:profile,:owner,:workspace,9,'preset','locked','preset-a',:rights,
                        'zh-CN','{}'::jsonb,:fingerprint,'pending','owner',now())""",
                {"id": uuid4(), "profile": profile_id, "owner": LOCAL_OWNER_ID,
                 "workspace": LOCAL_WORKSPACE_ID, "rights": rights_id, "fingerprint": "b" * 64})
            disposable_voice = uuid4()
            connection.execute(text(voice_version_sql), {
                "id": disposable_voice, "profile": profile_id, "owner": LOCAL_OWNER_ID,
                "workspace": LOCAL_WORKSPACE_ID, "number": 2, "reference": None,
                "rights": rights_id, "fingerprint": "0" * 64,
            })
            deleted_voice = connection.execute(text(
                "DELETE FROM voice_profile_versions WHERE id=:id RETURNING id"
            ), {"id": disposable_voice}).scalar_one()
            assert deleted_voice == disposable_voice
            connection.execute(text("""UPDATE voice_profile_versions
                SET state='locked',quality_state='accepted',locked_actor='owner',locked_at=now()
                WHERE id=:id"""),
                {"id": voice_version_id})
            uploaded_reference, rights_no_clone = uuid4(), uuid4()
            connection.execute(text("""INSERT INTO media_assets
                (id,owner_id,workspace_id,novel_id,kind,asset_class,storage_path,content_hash,
                 metadata_json,state)
                VALUES (:id,:owner,:workspace,:novel,'narration_voice_reference','voice_reference',
                        :path,:hash,'{}'::jsonb,'ready')"""),
                {"id": uploaded_reference, "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID,
                 "novel": novel_a, "path": f"tts/reference/{uploaded_reference}.wav", "hash": "1" * 64})
            connection.execute(text("""INSERT INTO voice_rights_records
                (id,owner_id,workspace_id,novel_id,source_kind,source_identifier,notice_version,purpose,
                 commercial_use,redistribution,voice_cloning,confirmed_actor,confirmed_at,risk_flags_json)
                VALUES (:id,:owner,:workspace,:novel,'uploaded','self','v1','private',false,false,
                        false,'owner',now(),'[]'::jsonb)"""),
                {"id": rights_no_clone, "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID,
                 "novel": novel_a})
            _expect_db_rejection(connection, """INSERT INTO voice_profile_versions
                (id,profile_id,owner_id,workspace_id,version_number,source_type,state,
                 reference_asset_id,rights_record_id,language,parameters_json,fingerprint,quality_state)
                VALUES (:id,:profile,:owner,:workspace,2,'uploaded','draft',:reference,:rights,
                        'zh-CN','{}'::jsonb,:fingerprint,'pending')""",
                {"id": uuid4(), "profile": profile_id, "owner": LOCAL_OWNER_ID,
                 "workspace": LOCAL_WORKSPACE_ID, "reference": uploaded_reference,
                 "rights": rights_no_clone, "fingerprint": "2" * 64})
            rights_uploaded, profile_uploaded, voice_uploaded = uuid4(), uuid4(), uuid4()
            connection.execute(text("""INSERT INTO voice_rights_records
                (id,owner_id,workspace_id,novel_id,source_kind,source_identifier,notice_version,purpose,
                 commercial_use,redistribution,voice_cloning,confirmed_actor,confirmed_at,risk_flags_json)
                VALUES (:id,:owner,:workspace,:novel,'uploaded','self','v1','private',false,false,
                        true,'owner',now(),'[]'::jsonb)"""),
                {"id": rights_uploaded, "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID,
                 "novel": novel_a})
            connection.execute(text("""INSERT INTO voice_profiles
                (id,owner_id,workspace_id,novel_id,name,status,version)
                VALUES (:id,:owner,:workspace,:novel,'uploaded','active',1)"""),
                {"id": profile_uploaded, "owner": LOCAL_OWNER_ID,
                 "workspace": LOCAL_WORKSPACE_ID, "novel": novel_a})
            connection.execute(text("""INSERT INTO voice_profile_versions
                (id,profile_id,owner_id,workspace_id,version_number,source_type,state,
                 reference_asset_id,rights_record_id,language,parameters_json,fingerprint,
                 quality_state,locked_actor,locked_at)
                VALUES (:id,:profile,:owner,:workspace,1,'uploaded','locked',:reference,:rights,
                        'zh-CN','{}'::jsonb,:fingerprint,'accepted','owner',now())"""),
                {"id": voice_uploaded, "profile": profile_uploaded, "owner": LOCAL_OWNER_ID,
                 "workspace": LOCAL_WORKSPACE_ID, "reference": uploaded_reference,
                 "rights": rights_uploaded, "fingerprint": "3" * 64})
            connection.execute(text("""INSERT INTO voice_rights_events
                (id,rights_record_id,event_key,event_type,actor,occurred_at)
                VALUES (:id,:rights,'revoked-once','revoked','owner',now())"""),
                {"id": uuid4(), "rights": rights_uploaded})
            _expect_db_rejection(connection,
                "UPDATE voice_profiles SET novel_id=:novel,version=2 WHERE id=:id",
                {"id": profile_id, "novel": novel_b})
            rights_b, profile_b, voice_b = uuid4(), uuid4(), uuid4()
            connection.execute(text("""INSERT INTO voice_rights_records
                (id,owner_id,workspace_id,novel_id,source_kind,source_identifier,notice_version,purpose,
                 commercial_use,redistribution,voice_cloning,confirmed_actor,confirmed_at,risk_flags_json)
                VALUES (:id,:owner,:workspace,:novel,'preset','preset-b','v1','private',false,false,
                        false,'owner',now(),'[]'::jsonb)"""),
                {"id": rights_b, "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID, "novel": novel_b})
            connection.execute(text("""INSERT INTO voice_profiles
                (id,owner_id,workspace_id,novel_id,name,status,version)
                VALUES (:id,:owner,:workspace,:novel,'foreign','active',1)"""),
                {"id": profile_b, "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID, "novel": novel_b})
            connection.execute(text("""INSERT INTO voice_profile_versions
                (id,profile_id,owner_id,workspace_id,version_number,source_type,state,preset_key,
                 rights_record_id,language,parameters_json,fingerprint,quality_state,locked_actor,locked_at)
                VALUES (:id,:profile,:owner,:workspace,1,'preset','locked','preset-b',:rights,
                        'zh-CN','{}'::jsonb,:fingerprint,'accepted','owner',now())"""),
                {"id": voice_b, "profile": profile_b, "owner": LOCAL_OWNER_ID,
                 "workspace": LOCAL_WORKSPACE_ID, "rights": rights_b, "fingerprint": "f" * 64})
            movable_voice = uuid4()
            connection.execute(text(voice_version_sql), {
                "id": movable_voice, "profile": profile_id, "owner": LOCAL_OWNER_ID,
                "workspace": LOCAL_WORKSPACE_ID, "number": 2, "reference": None,
                "rights": rights_id, "fingerprint": "6" * 64,
            })
            deleted_voice = uuid4()
            connection.execute(text(voice_version_sql.replace("'draft'", "'deleted'")), {
                "id": deleted_voice, "profile": profile_id, "owner": LOCAL_OWNER_ID,
                "workspace": LOCAL_WORKSPACE_ID, "number": 3, "reference": None,
                "rights": rights_id, "fingerprint": "5" * 64,
            })
            _expect_db_rejection(connection, """UPDATE voice_profile_versions
                SET state='locked',quality_state='accepted',locked_actor='owner',locked_at=now()
                WHERE id=:id""", {"id": deleted_voice})
            local_character = uuid4()
            connection.execute(text("""INSERT INTO novel_characters
                (id,novel_id,role_type,name,description,details,lifecycle_state,position,version)
                VALUES (:id,:novel,'protagonist','local','','{}'::jsonb,'active',1,1)"""),
                {"id": local_character, "novel": novel_a})
            binding_id = uuid4()
            connection.execute(text("""INSERT INTO character_voice_bindings
                (id,novel_id,character_id,profile_id,voice_version_id,binding_policy,language,
                 parameters_json,version)
                VALUES (:id,:novel,:character,:profile,:voice,'dedicated','zh-CN','{}'::jsonb,1)"""),
                {"id": binding_id, "novel": novel_a, "character": local_character,
                 "profile": profile_id, "voice": voice_version_id})
            unbound_character = uuid4()
            connection.execute(text("""INSERT INTO novel_characters
                (id,novel_id,role_type,name,description,details,lifecycle_state,position,version)
                VALUES (:id,:novel,'supporting','unbound','','{}'::jsonb,'active',2,1)"""),
                {"id": unbound_character, "novel": novel_a})
            _expect_db_rejection(connection, """INSERT INTO character_voice_bindings
                (id,novel_id,character_id,binding_policy,language,parameters_json,version)
                VALUES (:id,:novel,:character,'dedicated','zh-CN','{}'::jsonb,1)""",
                {"id": uuid4(), "novel": novel_a, "character": unbound_character})
            _expect_db_rejection(connection, """UPDATE character_voice_bindings
                SET character_id=:character,version=2 WHERE id=:id""",
                {"id": binding_id, "character": unbound_character})
            local_pool, local_slot = uuid4(), uuid4()
            connection.execute(text("""INSERT INTO generic_voice_pools
                (id,novel_id,name,version_number,status,attributes_json)
                VALUES (:id,:novel,'local',1,'active','{}'::jsonb)"""),
                {"id": local_pool, "novel": novel_a})
            _expect_db_rejection(connection,
                "UPDATE generic_voice_pools SET novel_id=:novel WHERE id=:id",
                {"id": local_pool, "novel": novel_b})
            connection.execute(text("""INSERT INTO generic_voice_slots
                (id,pool_id,slot_key,position,voice_version_id,labels_json,enabled,priority)
                VALUES (:id,:pool,'路人甲',1,:voice,'[]'::jsonb,true,0)"""),
                {"id": local_slot, "pool": local_pool, "voice": movable_voice})
            local_anonymous = uuid4()
            connection.execute(text("""INSERT INTO anonymous_speakers
                (id,novel_id,stable_key_algorithm,stable_key,display_name,scope_kind,scope_id,
                 inferred_json,confidence,slot_id,voice_version_id,lifecycle_state)
                VALUES (:id,:novel,'anon-v1','novel-local','路人甲','novel',:novel,'{}'::jsonb,
                        'high',:slot,:voice,'active')"""),
                {"id": local_anonymous, "novel": novel_a, "slot": local_slot, "voice": movable_voice})
            _expect_db_rejection(connection, """UPDATE voice_profile_versions
                SET profile_id=:profile,rights_record_id=:rights WHERE id=:id""",
                {"id": movable_voice, "profile": profile_b, "rights": rights_b})
            _expect_db_rejection(connection, """UPDATE anonymous_speakers
                SET novel_id=:novel,scope_id=:novel WHERE id=:id""",
                {"id": local_anonymous, "novel": novel_b})
            connection.execute(text("""INSERT INTO voice_casting_rules
                (id,novel_id,priority,version_number,condition_json,target_pool_id,target_slot_id,action)
                VALUES (:id,:novel,1,1,'{}'::jsonb,:pool,:slot,'assign_slot')"""),
                {"id": uuid4(), "novel": novel_a, "pool": local_pool, "slot": local_slot})
            render_job = uuid4()
            connection.execute(text(job_sql), {
                "id": render_job, "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID,
                "novel": novel_a, "request": generation_a, "allows": True,
                "kind": "narration.segment_render", "hash": "a" * 64, "key": str(uuid4()),
            })
            render_job_b = uuid4()
            connection.execute(text(job_sql), {
                "id": render_job_b, "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID,
                "novel": novel_b, "request": generation_b, "allows": True,
                "kind": "narration.segment_render", "hash": "b" * 64, "key": str(uuid4()),
            })
            render_sql = """INSERT INTO narration_segment_renders
                (id,owner_id,workspace_id,novel_id,request_id,request_allows_render,
                 render_fingerprint,canonical_input_json,voice_version_id,model_fingerprint,
                 postprocess_fingerprint,state,source_job_id,audio_validation_json)
                VALUES (:id,:owner,:workspace,:novel,:request,true,:fingerprint,'{}'::jsonb,
                        :voice,:model,:post,'pending',:source_job,'{}'::jsonb)"""
            _expect_db_rejection(connection, render_sql.replace("'pending'", "'ready'"), {
                "id": uuid4(), "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID,
                "novel": novel_a, "request": generation_a, "fingerprint": "1" * 64,
                "voice": voice_version_id, "model": "2" * 64, "post": "3" * 64,
                "source_job": render_job,
            })
            _expect_db_rejection(connection, render_sql, {
                "id": uuid4(), "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID,
                "novel": novel_b, "request": generation_a, "fingerprint": "a" * 64,
                "voice": voice_version_id, "model": "b" * 64, "post": "c" * 64,
                "source_job": render_job,
            })
            _expect_db_rejection(connection, render_sql, {
                "id": uuid4(), "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID,
                "novel": novel_a, "request": generation_a, "fingerprint": "2" * 64,
                "voice": voice_b, "model": "3" * 64, "post": "4" * 64,
                "source_job": render_job,
            })
            _expect_db_rejection(connection, render_sql, {
                "id": uuid4(), "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID,
                "novel": novel_a, "request": generation_a, "fingerprint": "3" * 64,
                "voice": voice_uploaded, "model": "4" * 64, "post": "5" * 64,
                "source_job": render_job,
            })
            _expect_db_rejection(connection, render_sql, {
                "id": uuid4(), "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID,
                "novel": novel_a, "request": request_id, "fingerprint": "d" * 64,
                "voice": voice_version_id, "model": "e" * 64, "post": "f" * 64,
                "source_job": render_job,
            })
            _expect_db_rejection(connection, render_sql, {
                "id": uuid4(), "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID,
                "novel": novel_a, "request": generation_a, "fingerprint": "e" * 64,
                "voice": voice_version_id, "model": "f" * 64, "post": "0" * 64,
                "source_job": valid_job,
            })
            disposable_render = uuid4()
            connection.execute(text(render_sql), {
                "id": disposable_render, "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID,
                "novel": novel_a, "request": generation_a, "fingerprint": "f" * 64,
                "voice": voice_version_id, "model": "0" * 64, "post": "1" * 64,
                "source_job": render_job,
            })
            deleted_render = connection.execute(text(
                "DELETE FROM narration_segment_renders WHERE id=:id RETURNING id"
            ), {"id": disposable_render}).scalar_one()
            assert deleted_render == disposable_render
            settings_id = uuid4()
            connection.execute(text("INSERT INTO novel_narration_settings (id,novel_id,script_review_policy,analysis_mode,settings_json,version) VALUES (:id,:novel,'blockers_only','local_rules_only','{}'::jsonb,1)"), {"id": settings_id, "novel": novel_a})
            _expect_db_rejection(connection, "UPDATE novel_narration_settings SET settings_json='{}'::jsonb WHERE id=:id", {"id": settings_id})
            connection.execute(text("""UPDATE novel_narration_settings
                SET narrator_profile_id=:profile,narrator_version_id=:voice,version=2 WHERE id=:id"""),
                {"id": settings_id, "profile": profile_id, "voice": voice_version_id})
            _expect_db_rejection(connection, """UPDATE novel_narration_settings
                SET narrator_version_id=NULL,version=3 WHERE id=:id""", {"id": settings_id})
            _expect_db_rejection(connection, """UPDATE novel_narration_settings
                SET novel_id=:novel,narrator_profile_id=NULL,narrator_version_id=NULL,version=3
                WHERE id=:id""", {"id": settings_id, "novel": novel_b})

            script_id, approved_version, draft_version = uuid4(), uuid4(), uuid4()
            connection.execute(text("""INSERT INTO narration_scripts
                (id,novel_id,document_id,revision_id,content_hash,version)
                VALUES (:id,:novel,:document,:revision,:hash,1)"""),
                {"id": script_id, "novel": novel_a, "document": doc_a, "revision": rev_a, "hash": "a" * 64})
            script_version_sql = """INSERT INTO narration_script_versions
                (id,script_id,version_number,state,analyzer_fingerprint,rules_fingerprint,
                 settings_fingerprint,taxonomy_version,immutable_hash,idempotency_key,warning_count,
                 blocker_count,approval_kind,approval_request_id,approval_request_allows_edition,
                 effective_policy,approved_actor_type,approved_actor_id,approved_at)
                VALUES (:id,:script,:number,:state,:analyzer,:rules,:settings,
                        'narration-review-taxonomy/1',:immutable,:key,0,0,:approval_kind,
                        :approval_request,:approval_allows,:policy,:actor_type,:actor_id,:approved_at)"""
            connection.execute(text(script_version_sql), {
                "id": approved_version, "script": script_id, "number": 1, "state": "draft",
                "analyzer": "1" * 64, "rules": "2" * 64, "settings": "2" * 64,
                "immutable": "4" * 64, "key": str(uuid4()), "approval_kind": None,
                "approval_request": None, "approval_allows": None, "policy": "blockers_only",
                "actor_type": None, "actor_id": None, "approved_at": None,
            })
            connection.execute(text(script_version_sql), {
                "id": draft_version, "script": script_id, "number": 2, "state": "draft",
                "analyzer": "5" * 64, "rules": "6" * 64, "settings": "7" * 64,
                "immutable": "8" * 64, "key": str(uuid4()), "approval_kind": None,
                "approval_request": None, "approval_allows": None, "policy": "always_review",
                "actor_type": None, "actor_id": None, "approved_at": None,
            })
            foreign_script, foreign_script_version = uuid4(), uuid4()
            connection.execute(text("""INSERT INTO narration_scripts
                (id,novel_id,document_id,revision_id,content_hash,version)
                VALUES (:id,:novel,:document,:revision,:hash,1)"""),
                {"id": foreign_script, "novel": novel_b, "document": doc_b,
                 "revision": rev_b, "hash": "b" * 64})
            connection.execute(text(script_version_sql), {
                "id": foreign_script_version, "script": foreign_script, "number": 1, "state": "draft",
                "analyzer": "1" * 64, "rules": "2" * 64, "settings": "3" * 64,
                "immutable": "4" * 64, "key": str(uuid4()), "approval_kind": None,
                "approval_request": None, "approval_allows": None, "policy": "always_review",
                "actor_type": None, "actor_id": None, "approved_at": None,
            })
            _expect_db_rejection(connection, """INSERT INTO narration_script_versions
                (id,script_id,version_number,state,analyzer_fingerprint,rules_fingerprint,
                 settings_fingerprint,taxonomy_version,immutable_hash,idempotency_key,warning_count,
                 blocker_count,effective_policy)
                VALUES (:id,:script,6,'draft',:hash,:hash,:hash,'unknown-taxonomy',:hash,:key,
                        0,0,'blockers_only')""",
                {"id": uuid4(), "script": script_id, "hash": "f" * 64, "key": str(uuid4())})
            scoped_scene, scoped_scene_speaker = uuid4(), uuid4()
            connection.execute(text("""INSERT INTO narration_scenes
                (id,script_version_id,ordinal,boundary_source,local_hash)
                VALUES (:id,:version,9,'paragraph',:hash)"""),
                {"id": scoped_scene, "version": draft_version, "hash": "e" * 64})
            connection.execute(text("""INSERT INTO anonymous_speakers
                (id,novel_id,stable_key_algorithm,stable_key,display_name,scope_kind,scope_id,
                 inferred_json,confidence,lifecycle_state)
                VALUES (:id,:novel,'anon-v1','scene-scoped','scene voice','scene',:scene,
                        '{}'::jsonb,'high','active')"""),
                {"id": scoped_scene_speaker, "novel": novel_a, "scene": scoped_scene})
            _expect_db_rejection(connection,
                "UPDATE narration_scenes SET script_version_id=:version WHERE id=:id",
                {"id": scoped_scene, "version": foreign_script_version})
            _expect_db_rejection(connection,
                "DELETE FROM narration_scenes WHERE id=:id", {"id": scoped_scene})
            policy_bypass_version = uuid4()
            connection.execute(text(script_version_sql), {
                "id": policy_bypass_version, "script": script_id, "number": 5, "state": "draft",
                "analyzer": "8" * 64, "rules": "9" * 64, "settings": "2" * 64,
                "immutable": "a" * 64, "key": str(uuid4()), "approval_kind": None,
                "approval_request": None, "approval_allows": None, "policy": "blockers_only",
                "actor_type": None, "actor_id": None, "approved_at": None,
            })
            _expect_db_rejection(connection, """UPDATE narration_script_versions
                SET state='approved',approval_kind='auto_no_blockers',approval_request_id=:request,
                    approval_request_allows_edition=true,approved_actor_type='system',
                    approved_actor_id='rules-v1',approved_at=now() WHERE id=:id""",
                {"id": policy_bypass_version, "request": force_review_request})
            anonymous_approval_version = uuid4()
            connection.execute(text(script_version_sql), {
                "id": anonymous_approval_version, "script": script_id, "number": 7,
                "state": "draft", "analyzer": "7" * 64, "rules": "8" * 64,
                "settings": "9" * 64, "immutable": "a" * 64, "key": str(uuid4()),
                "approval_kind": None, "approval_request": None, "approval_allows": None,
                "policy": "blockers_only", "actor_type": None, "actor_id": None,
                "approved_at": None,
            })
            _expect_db_rejection(connection, """UPDATE narration_script_versions
                SET state='approved',approval_kind='auto_no_blockers',approval_request_id=:request,
                    approval_request_allows_edition=true,approved_at=now() WHERE id=:id""",
                {"id": anonymous_approval_version, "request": generation_a})
            _expect_db_rejection(connection, """INSERT INTO narration_script_versions
                (id,script_id,version_number,parent_version_id,state,analyzer_fingerprint,
                 rules_fingerprint,settings_fingerprint,taxonomy_version,immutable_hash,
                 idempotency_key,warning_count,blocker_count,effective_policy)
                VALUES (:id,:script,4,:parent,'draft',:hash,:hash,:hash,
                        'narration-review-taxonomy/1',:hash,:key,0,0,'always_review')""",
                {"id": uuid4(), "script": script_id, "parent": foreign_script_version,
                 "hash": "5" * 64, "key": str(uuid4())})
            approved_scene, approved_segment = uuid4(), uuid4()
            connection.execute(text("""INSERT INTO narration_scenes
                (id,script_version_id,ordinal,boundary_source,local_hash)
                VALUES (:id,:version,1,'paragraph',:hash)"""),
                {"id": approved_scene, "version": approved_version, "hash": "9" * 64})
            connection.execute(text("""INSERT INTO narration_segments
                (id,script_version_id,scene_id,ordinal,segment_kind,source_block_key,source_text,
                 spoken_text,local_hash,speaker_kind,casting_json,evidence_json,confidence,
                 pause_before_ms,pause_after_ms,manual_override)
                VALUES (:id,:version,:scene,1,'narration','p0','text','text',:hash,'narrator',
                        '{}'::jsonb,'{}'::jsonb,'high',0,0,false)"""),
                {"id": approved_segment, "version": approved_version, "scene": approved_scene,
                 "hash": "0" * 64})
            connection.execute(text("""UPDATE narration_script_versions
                SET state='approved',approval_kind='auto_no_blockers',approval_request_id=:request,
                    approval_request_allows_edition=true,approved_actor_type='system',
                    approved_actor_id='rules-v1',approved_at=now()
                WHERE id=:id"""), {"id": approved_version, "request": generation_a})
            _expect_db_rejection(connection, """INSERT INTO narration_scenes
                (id,script_version_id,ordinal,boundary_source,local_hash)
                VALUES (:id,:version,1,'paragraph',:hash)""",
                {"id": uuid4(), "version": approved_version, "hash": "9" * 64})
            _expect_db_rejection(connection, """INSERT INTO narration_script_issues
                (id,script_version_id,taxonomy_version,code,severity)
                VALUES (:id,:version,'narration-review-taxonomy/1','UNKNOWN_CODE','warning')""",
                {"id": uuid4(), "version": draft_version})
            disposable_script_version = uuid4()
            connection.execute(text(script_version_sql), {
                "id": disposable_script_version, "script": script_id, "number": 3, "state": "draft",
                "analyzer": "a" * 64, "rules": "b" * 64, "settings": "c" * 64,
                "immutable": "d" * 64, "key": str(uuid4()), "approval_kind": None,
                "approval_request": None, "approval_allows": None, "policy": "always_review",
                "actor_type": None, "actor_id": None, "approved_at": None,
            })
            deleted_script_version = connection.execute(text(
                "DELETE FROM narration_script_versions WHERE id=:id RETURNING id"
            ), {"id": disposable_script_version}).scalar_one()
            assert deleted_script_version == disposable_script_version

            foreign_character = uuid4()
            connection.execute(text("""INSERT INTO novel_characters
                (id,novel_id,role_type,name,description,details,lifecycle_state,position,version)
                VALUES (:id,:novel,'supporting','foreign','','{}'::jsonb,'active',1,1)"""),
                {"id": foreign_character, "novel": novel_b})
            _expect_db_rejection(connection, """INSERT INTO anonymous_speakers
                (id,novel_id,stable_key_algorithm,stable_key,display_name,scope_kind,scope_id,
                 inferred_json,confidence,promoted_character_id,lifecycle_state)
                VALUES (:id,:novel,'anon-v1','bad-character','unknown','novel',:novel,
                        '{}'::jsonb,'unknown',:character,'active')""",
                {"id": uuid4(), "novel": novel_a, "character": foreign_character})
            _expect_db_rejection(connection, """INSERT INTO narration_segments
                (id,script_version_id,ordinal,segment_kind,source_block_key,source_text,spoken_text,
                 local_hash,speaker_kind,character_id,casting_json,evidence_json,confidence,
                 pause_before_ms,pause_after_ms,manual_override)
                VALUES (:id,:version,1,'dialogue','p1','text','text',:hash,'character',:character,
                        '{}'::jsonb,'{}'::jsonb,'high',0,0,false)""",
                {"id": uuid4(), "version": draft_version, "hash": "a" * 64, "character": foreign_character})
            _expect_db_rejection(connection, """INSERT INTO narration_segments
                (id,script_version_id,ordinal,segment_kind,source_block_key,source_start_utf16,
                 source_text,spoken_text,local_hash,speaker_kind,casting_json,evidence_json,
                 confidence,pause_before_ms,pause_after_ms,manual_override)
                VALUES (:id,:version,2,'narration','p2',0,'text','text',:hash,'narrator',
                        '{}'::jsonb,'{}'::jsonb,'high',0,0,false)""",
                {"id": uuid4(), "version": draft_version, "hash": "b" * 64})
            connection.execute(text("""INSERT INTO narration_segments
                (id,script_version_id,ordinal,segment_kind,source_block_key,source_text,spoken_text,
                 local_hash,speaker_kind,character_id,casting_json,evidence_json,confidence,
                 pause_before_ms,pause_after_ms,manual_override)
                VALUES (:id,:version,3,'dialogue','p3','text','text',:hash,'character',:character,
                        '{}'::jsonb,'{}'::jsonb,'high',0,0,false)"""),
                {"id": uuid4(), "version": draft_version, "hash": "c" * 64,
                 "character": local_character})
            _expect_db_rejection(connection,
                "UPDATE narration_script_versions SET script_id=:script WHERE id=:id",
                {"id": draft_version, "script": foreign_script})
            _expect_db_rejection(connection,
                "UPDATE novel_characters SET novel_id=:novel WHERE id=:id",
                {"id": local_character, "novel": novel_b})
            _expect_db_rejection(connection, """INSERT INTO anonymous_speakers
                (id,novel_id,stable_key_algorithm,stable_key,display_name,scope_kind,scope_id,
                 inferred_json,confidence,lifecycle_state)
                VALUES (:id,:novel,'anon-v1','missing-scope','unknown','novel',NULL,'{}'::jsonb,
                        'unknown','active')""", {"id": uuid4(), "novel": novel_a})
            foreign_pool = uuid4()
            connection.execute(text("""INSERT INTO generic_voice_pools
                (id,novel_id,name,version_number,status,attributes_json)
                VALUES (:id,:novel,'foreign',1,'active','{}'::jsonb)"""),
                {"id": foreign_pool, "novel": novel_b})
            foreign_slot = uuid4()
            connection.execute(text("""INSERT INTO generic_voice_slots
                (id,pool_id,slot_key,position,voice_version_id,labels_json,enabled,priority)
                VALUES (:id,:pool,'foreign',1,:voice,'[]'::jsonb,true,0)"""),
                {"id": foreign_slot, "pool": foreign_pool, "voice": voice_b})
            _expect_db_rejection(connection, """UPDATE generic_voice_slots
                SET pool_id=:pool,voice_version_id=:voice WHERE id=:id""",
                {"id": local_slot, "pool": foreign_pool, "voice": voice_b})
            for stable_key, slot_id, foreign_voice in (
                ("bad-slot", foreign_slot, None),
                ("bad-voice", None, voice_b),
                ("bad-pair", local_slot, voice_b),
            ):
                _expect_db_rejection(connection, """INSERT INTO anonymous_speakers
                    (id,novel_id,stable_key_algorithm,stable_key,display_name,scope_kind,scope_id,
                     inferred_json,confidence,slot_id,voice_version_id,lifecycle_state)
                    VALUES (:id,:novel,'anon-v1',:stable,'unknown','novel',:novel,
                            '{}'::jsonb,'unknown',:slot,:voice,'active')""",
                    {"id": uuid4(), "novel": novel_a, "stable": stable_key,
                     "slot": slot_id, "voice": foreign_voice})
            _expect_db_rejection(connection, """INSERT INTO voice_casting_rules
                (id,novel_id,priority,version_number,condition_json,target_pool_id,action)
                VALUES (:id,:novel,1,1,'{}'::jsonb,:pool,'assign_pool')""",
                {"id": uuid4(), "novel": novel_a, "pool": foreign_pool})

            snapshot_a, snapshot_b, pronunciation_a, pronunciation_b = uuid4(), uuid4(), uuid4(), uuid4()
            for snapshot_id, novel_id, marker in (
                (snapshot_a, novel_a, "2"), (snapshot_b, novel_b, "c"),
            ):
                connection.execute(text("""INSERT INTO narration_settings_snapshots
                    (id,owner_id,workspace_id,novel_id,schema_version,taxonomy_version,
                     fingerprint,snapshot_json)
                    VALUES (:id,:owner,:workspace,:novel,'narration-settings/1',
                            'narration-review-taxonomy/1',:fingerprint,'{}'::jsonb)"""),
                    {"id": snapshot_id, "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID,
                     "novel": novel_id, "fingerprint": marker * 64})
            _expect_db_rejection(connection, """INSERT INTO narration_settings_snapshots
                (id,owner_id,workspace_id,novel_id,schema_version,taxonomy_version,
                 fingerprint,snapshot_json)
                VALUES (:id,:owner,:workspace,:novel,'narration-settings/1','unknown-taxonomy',
                        :fingerprint,'{}'::jsonb)""",
                {"id": uuid4(), "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID,
                 "novel": novel_a, "fingerprint": "f" * 64})
            for pronunciation_id, novel_id, marker in (
                (pronunciation_a, novel_a, "d"), (pronunciation_b, novel_b, "e"),
            ):
                connection.execute(text("""INSERT INTO pronunciation_profiles
                    (id,novel_id,version_number,fingerprint) VALUES (:id,:novel,1,:fingerprint)"""),
                    {"id": pronunciation_id, "novel": novel_id, "fingerprint": marker * 64})
            connection.execute(text("""INSERT INTO pronunciation_entries
                (id,profile_id,scope_kind,scope_id,source_text,normalized_source,spoken_text,
                 language,priority,source_kind)
                VALUES (:id,:profile,'novel',:novel,'测试','测试','测试','zh-CN',0,'manual')"""),
                {"id": uuid4(), "profile": pronunciation_a, "novel": novel_a})
            connection.execute(text("""INSERT INTO pronunciation_entries
                (id,profile_id,scope_kind,scope_id,source_text,normalized_source,spoken_text,
                 language,priority,source_kind)
                VALUES (:id,:profile,'chapter',:document,'章节','章节','章节','zh-CN',0,'manual')"""),
                {"id": uuid4(), "profile": pronunciation_a, "document": polymorphic_doc})
            _expect_db_rejection(connection,
                "UPDATE documents SET novel_id=:novel,position=9 WHERE id=:id",
                {"id": polymorphic_doc, "novel": novel_b})
            _expect_db_rejection(connection,
                "DELETE FROM documents WHERE id=:id", {"id": polymorphic_doc})
            edition_sql = """INSERT INTO narration_editions
                (id,owner_id,workspace_id,novel_id,document_id,request_id,request_allows_edition,
                 script_version_id,script_is_approved,settings_snapshot_id,pronunciation_profile_id,
                 tts_fingerprint,tokenizer_fingerprint,normalizer_fingerprint,postprocess_fingerprint,
                 context_mode,buffer_policy_version,edition_fingerprint,state,created_actor)
                VALUES (:id,:owner,:workspace,:novel,:document,:request,true,:script,true,:snapshot,
                        :pronunciation,:tts,:tokenizer,:normalizer,:post,'independent_segment',
                        'buffer/1',:edition,'created','owner')"""
            edition_common = {
                "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID, "novel": novel_a,
                "document": doc_a, "script": approved_version, "tts": "e" * 64,
                "tokenizer": "f" * 64, "normalizer": "0" * 64, "post": "1" * 64,
            }
            _expect_db_rejection(connection, edition_sql, {
                **edition_common, "id": uuid4(), "request": request_id, "snapshot": snapshot_a,
                "pronunciation": None, "edition": "2" * 64,
            })
            _expect_db_rejection(connection, edition_sql, {
                **edition_common, "id": uuid4(), "request": force_review_request,
                "snapshot": snapshot_a, "pronunciation": None, "edition": "6" * 64,
            })
            _expect_db_rejection(connection, edition_sql, {
                **edition_common, "id": uuid4(), "request": generation_a, "snapshot": snapshot_b,
                "pronunciation": None, "edition": "3" * 64,
            })
            _expect_db_rejection(connection, edition_sql, {
                **edition_common, "id": uuid4(), "request": generation_a, "snapshot": snapshot_a,
                "pronunciation": pronunciation_b, "edition": "4" * 64,
            })
            unavailable_edition = uuid4()
            connection.execute(text(edition_sql.replace("'created'", "'unavailable'")), {
                **edition_common, "id": unavailable_edition, "request": generation_a,
                "snapshot": snapshot_a, "pronunciation": pronunciation_a, "edition": "8" * 64,
            })
            _expect_db_rejection(connection,
                "UPDATE narration_editions SET state='ready',unavailable_reason=NULL WHERE id=:id",
                {"id": unavailable_edition})
            edition_id = uuid4()
            connection.execute(text(edition_sql), {
                **edition_common, "id": edition_id, "request": generation_a, "snapshot": snapshot_a,
                "pronunciation": pronunciation_a, "edition": "5" * 64,
            })
            edition_segment, ready_render, render_asset = uuid4(), uuid4(), uuid4()
            render_fingerprint = "8" * 64
            connection.execute(text("""INSERT INTO narration_edition_segments
                (id,edition_id,script_version_id,segment_id,ordinal,profile_id,voice_version_id,
                 resolution_json,render_fingerprint,render_state,gap_after_ms)
                VALUES (:id,:edition,:version,:segment,0,:profile,:voice,'{}'::jsonb,
                        :fingerprint,'pending',0)"""),
                {"id": edition_segment, "edition": edition_id, "version": approved_version,
                 "segment": approved_segment, "profile": profile_id, "voice": voice_version_id,
                 "fingerprint": render_fingerprint})
            cancelled_edition_segment = uuid4()
            connection.execute(text("""INSERT INTO narration_edition_segments
                (id,edition_id,script_version_id,segment_id,ordinal,profile_id,voice_version_id,
                 resolution_json,render_fingerprint,render_state,gap_after_ms)
                VALUES (:id,:edition,:version,:segment,1,:profile,:voice,'{}'::jsonb,
                        :fingerprint,'cancelled',0)"""),
                {"id": cancelled_edition_segment, "edition": edition_id,
                 "version": approved_version, "segment": approved_segment,
                 "profile": profile_id, "voice": voice_version_id,
                 "fingerprint": render_fingerprint})
            _expect_db_rejection(connection,
                "UPDATE narration_edition_segments SET render_state='ready' WHERE id=:id",
                {"id": cancelled_edition_segment})
            connection.execute(text(render_sql), {
                "id": ready_render, "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID,
                "novel": novel_a, "request": generation_a, "fingerprint": render_fingerprint,
                "voice": voice_version_id, "model": "9" * 64, "post": "a" * 64,
                "source_job": render_job,
            })
            connection.execute(text("""INSERT INTO media_assets
                (id,owner_id,workspace_id,novel_id,kind,asset_class,storage_path,content_hash,
                 metadata_json,state,duration_ms)
                VALUES (:id,:owner,:workspace,:novel,'narration_audio','segment_master',:path,:hash,
                        '{}'::jsonb,'ready',1000)"""),
                {"id": render_asset, "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID,
                 "novel": novel_a, "path": f"tts/render/{render_asset}.wav", "hash": "b" * 64})
            connection.execute(text("""INSERT INTO narration_render_assets
                (id,render_id,asset_id,role,actual_sha256)
                VALUES (:id,:render,:asset,'master',:hash)"""),
                {"id": uuid4(), "render": ready_render, "asset": render_asset, "hash": "b" * 64})
            _expect_db_rejection(connection, """UPDATE narration_segment_renders
                SET novel_id=:novel,request_id=:request,voice_version_id=:voice,
                    source_job_id=:job,render_fingerprint=:fingerprint WHERE id=:id""",
                {"id": ready_render, "novel": novel_b, "request": generation_b,
                 "voice": voice_b, "job": render_job_b, "fingerprint": "6" * 64})
            _expect_db_rejection(connection,
                "UPDATE media_assets SET storage_path='tts/render/rewritten.wav' WHERE id=:id",
                {"id": render_asset})
            _expect_db_rejection(connection,
                "UPDATE media_assets SET state='deleting',deleted_at=now() WHERE id=:id",
                {"id": render_asset})
            connection.execute(text("""UPDATE narration_segment_renders
                SET state='ready',duration_ms=1000,ready_at=now() WHERE id=:id"""),
                {"id": ready_render})
            connection.execute(text("""UPDATE narration_edition_segments
                SET render_state='ready' WHERE id=:id"""), {"id": edition_segment})
            cancelled_render_savepoint = connection.begin_nested()
            cancelled_render, cancelled_render_asset = uuid4(), uuid4()
            connection.execute(text(render_sql.replace("'pending'", "'cancelled'")), {
                "id": cancelled_render, "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID,
                "novel": novel_a, "request": generation_a, "fingerprint": "4" * 64,
                "voice": voice_version_id, "model": "5" * 64, "post": "6" * 64,
                "source_job": render_job,
            })
            connection.execute(text("""INSERT INTO media_assets
                (id,owner_id,workspace_id,novel_id,kind,asset_class,storage_path,content_hash,
                 metadata_json,state,duration_ms)
                VALUES (:id,:owner,:workspace,:novel,'narration_audio','segment_master',:path,:hash,
                        '{}'::jsonb,'ready',1000)"""),
                {"id": cancelled_render_asset, "owner": LOCAL_OWNER_ID,
                 "workspace": LOCAL_WORKSPACE_ID, "novel": novel_a,
                 "path": f"tts/render/{cancelled_render_asset}.wav", "hash": "4" * 64})
            connection.execute(text("""INSERT INTO narration_render_assets
                (id,render_id,asset_id,role,actual_sha256)
                VALUES (:id,:render,:asset,'master',:hash)"""),
                {"id": uuid4(), "render": cancelled_render,
                 "asset": cancelled_render_asset, "hash": "4" * 64})
            _expect_db_rejection(connection, """UPDATE narration_segment_renders
                SET state='ready',duration_ms=1000,ready_at=now() WHERE id=:id""",
                {"id": cancelled_render})
            _expect_db_rejection(connection,
                "SET CONSTRAINTS trg_media_generated_reachability IMMEDIATE", {})
            cancelled_render_savepoint.rollback()
            connection.execute(text(
                "SET CONSTRAINTS trg_media_generated_reachability DEFERRED"
            ))
            mismatched_render, mismatched_asset = uuid4(), uuid4()
            connection.execute(text(render_sql), {
                "id": mismatched_render, "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID,
                "novel": novel_a, "request": generation_a, "fingerprint": "7" * 64,
                "voice": voice_version_id, "model": "c" * 64, "post": "d" * 64,
                "source_job": render_job,
            })
            connection.execute(text("""INSERT INTO media_assets
                (id,owner_id,workspace_id,novel_id,kind,asset_class,storage_path,content_hash,
                 metadata_json,state,duration_ms)
                VALUES (:id,:owner,:workspace,:novel,'narration_audio','segment_master',:path,:hash,
                        '{}'::jsonb,'ready',1000)"""),
                {"id": mismatched_asset, "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID,
                 "novel": novel_a, "path": f"tts/render/{mismatched_asset}.wav", "hash": "e" * 64})
            connection.execute(text("""INSERT INTO narration_render_assets
                (id,render_id,asset_id,role,actual_sha256)
                VALUES (:id,:render,:asset,'master',:hash)"""),
                {"id": uuid4(), "render": mismatched_render, "asset": mismatched_asset, "hash": "e" * 64})
            connection.execute(text("""UPDATE narration_segment_renders
                SET state='ready',duration_ms=1000,ready_at=now() WHERE id=:id"""),
                {"id": mismatched_render})
            manifest_id = uuid4()
            connection.execute(text("""INSERT INTO narration_manifests
                (id,edition_id,manifest_revision,schema_version,canonical_json,etag_sha256,
                 ready_prefix_count,ready_ranges_json,total_duration_ms,status)
                VALUES (:id,:edition,1,'narration-manifest/2.0','{}'::jsonb,:etag,1,
                        '[]'::jsonb,1000,'ready')"""),
                {"id": manifest_id, "edition": edition_id, "etag": "c" * 64})
            _expect_db_rejection(connection, """INSERT INTO narration_manifest_segments
                (id,manifest_id,edition_id,edition_segment_id,ordinal,render_id,render_state,
                 duration_ms,gap_after_ms)
                VALUES (:id,:manifest,:edition,:segment,0,:render,'ready',1000,0)""",
                {"id": uuid4(), "manifest": manifest_id, "edition": edition_id,
                 "segment": edition_segment, "render": mismatched_render})
            _expect_db_rejection(connection, """INSERT INTO narration_manifest_segments
                (id,manifest_id,edition_id,edition_segment_id,ordinal,render_id,render_state,
                 duration_ms,gap_after_ms)
                VALUES (:id,:manifest,:edition,:segment,1,:render,'ready',1000,0)""",
                {"id": uuid4(), "manifest": manifest_id, "edition": edition_id,
                 "segment": cancelled_edition_segment, "render": ready_render})
            _expect_db_rejection(connection, """INSERT INTO narration_manifest_segments
                (id,manifest_id,edition_id,edition_segment_id,ordinal,render_id,render_state,
                 duration_ms,gap_after_ms)
                VALUES (:id,:manifest,:edition,:segment,1,:render,'ready',1000,0)""",
                {"id": uuid4(), "manifest": manifest_id, "edition": edition_id,
                 "segment": edition_segment, "render": ready_render})
            _expect_db_rejection(connection, """INSERT INTO narration_manifest_segments
                (id,manifest_id,edition_id,edition_segment_id,ordinal,render_id,render_state,
                 duration_ms,gap_after_ms)
                VALUES (:id,:manifest,:edition,:segment,1,NULL,'pending',NULL,0)""",
                {"id": uuid4(), "manifest": manifest_id, "edition": edition_id,
                 "segment": edition_segment})
            connection.execute(text("""INSERT INTO narration_manifest_segments
                (id,manifest_id,edition_id,edition_segment_id,ordinal,render_id,render_state,
                 duration_ms,gap_after_ms)
                VALUES (:id,:manifest,:edition,:segment,0,:render,'ready',1000,0)"""),
                {"id": uuid4(), "manifest": manifest_id, "edition": edition_id,
                 "segment": edition_segment, "render": ready_render})
            connection.execute(text(
                "UPDATE narration_editions SET state='ready' WHERE id=:id"
            ), {"id": edition_id})
            _expect_db_rejection(connection,
                "UPDATE narration_editions SET state='rendering' WHERE id=:id",
                {"id": edition_id})
            connection.execute(text("""INSERT INTO voice_rights_events
                (id,rights_record_id,event_key,event_type,actor,occurred_at)
                VALUES (:id,:rights,'revoked-after-edition','revoked','owner',now())"""),
                {"id": uuid4(), "rights": rights_id})
            revoked_edition = uuid4()
            connection.execute(text(edition_sql), {
                **edition_common, "id": revoked_edition, "request": generation_a,
                "snapshot": snapshot_a, "pronunciation": pronunciation_a, "edition": "7" * 64,
            })
            _expect_db_rejection(connection, """INSERT INTO narration_edition_segments
                (id,edition_id,script_version_id,segment_id,ordinal,profile_id,voice_version_id,
                 resolution_json,render_fingerprint,render_state,gap_after_ms)
                VALUES (:id,:edition,:version,:segment,0,:profile,:voice,'{}'::jsonb,
                        :fingerprint,'pending',0)""",
                {"id": uuid4(), "edition": revoked_edition, "version": approved_version,
                 "segment": approved_segment, "profile": profile_id,
                 "voice": voice_version_id, "fingerprint": "a" * 64})
            assert connection.scalar(text(
                "SELECT count(*) FROM narration_editions WHERE id=:id"
            ), {"id": edition_id}) == 1
            assert connection.scalar(text(
                "SELECT count(*) FROM narration_edition_segments WHERE edition_id=:id"
            ), {"id": revoked_edition}) == 0
            assert connection.scalar(text(
                "SELECT count(*) FROM narration_manifests WHERE edition_id=:id"
            ), {"id": revoked_edition}) == 0
            connection.execute(text("""INSERT INTO narration_edition_state
                (edition_id,current_manifest_id,current_manifest_revision,version,updated_actor)
                VALUES (:edition,:manifest,1,1,'owner')"""),
                {"edition": edition_id, "manifest": manifest_id})
            document_state_id = uuid4()
            connection.execute(text("""INSERT INTO document_narration_state
                (id,owner_id,workspace_id,document_id,script_id,current_script_version_id,
                 current_edition_id,version,switched_actor,switched_at)
                VALUES (:id,:owner,:workspace,:document,:script,:version,:edition,1,'owner',now())"""),
                {"id": document_state_id, "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID,
                 "document": doc_a, "script": script_id, "version": approved_version,
                 "edition": edition_id})
            _expect_db_rejection(connection, """UPDATE document_narration_state
                SET document_id=:document,script_id=NULL,current_script_version_id=NULL,
                    current_edition_id=NULL,version=2 WHERE id=:id""",
                {"id": document_state_id, "document": doc_b})
            connection.execute(text("""INSERT INTO narration_playback_progress
                (id,owner_id,workspace_id,profile_id,edition_id,manifest_revision,
                 edition_segment_id,offset_ms,last_legal_start_ordinal,playback_rate_millis)
                VALUES (:id,:owner,:workspace,'local',:edition,1,:segment,0,0,1000)"""),
                {"id": uuid4(), "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID,
                 "edition": edition_id, "segment": edition_segment})
            export_asset = uuid4()
            connection.execute(text("""INSERT INTO media_assets
                (id,owner_id,workspace_id,novel_id,kind,asset_class,storage_path,content_hash,
                 metadata_json,state)
                VALUES (:id,:owner,:workspace,:novel,'narration_export','export',:path,:hash,
                        '{}'::jsonb,'staging')"""),
                {"id": export_asset, "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID,
                 "novel": novel_a, "path": f"tts/export/{export_asset}.m4b", "hash": "6" * 64})
            _expect_db_rejection(connection, """INSERT INTO narration_exports
                (id,edition_id,request_id,request_allows_render,export_fingerprint,asset_id,state)
                VALUES (:id,:edition,:request,true,:fingerprint,:asset,'staging')""",
                {"id": uuid4(), "edition": edition_id, "request": generation_b,
                 "fingerprint": "7" * 64, "asset": export_asset})
            connection.execute(text("""INSERT INTO narration_exports
                (id,edition_id,request_id,request_allows_render,export_fingerprint,asset_id,state)
                VALUES (:id,:edition,:request,true,:fingerprint,:asset,'staging')"""),
                {"id": uuid4(), "edition": edition_id, "request": generation_a,
                 "fingerprint": "9" * 64, "asset": export_asset})
            ready_export_asset, ready_export = uuid4(), uuid4()
            connection.execute(text("""INSERT INTO media_assets
                (id,owner_id,workspace_id,novel_id,kind,asset_class,storage_path,content_hash,
                 metadata_json,state)
                VALUES (:id,:owner,:workspace,:novel,'narration_export','export',:path,:hash,
                        '{}'::jsonb,'ready')"""),
                {"id": ready_export_asset, "owner": LOCAL_OWNER_ID,
                 "workspace": LOCAL_WORKSPACE_ID, "novel": novel_a,
                 "path": f"tts/export/{ready_export_asset}.m4b", "hash": "0" * 64})
            connection.execute(text("""INSERT INTO narration_exports
                (id,edition_id,request_id,request_allows_render,export_fingerprint,asset_id,state)
                VALUES (:id,:edition,:request,true,:fingerprint,:asset,'ready')"""),
                {"id": ready_export, "edition": edition_id, "request": generation_a,
                 "fingerprint": "0" * 64, "asset": ready_export_asset})
            cancelled_export_savepoint = connection.begin_nested()
            cancelled_export_asset, cancelled_export = uuid4(), uuid4()
            connection.execute(text("""INSERT INTO media_assets
                (id,owner_id,workspace_id,novel_id,kind,asset_class,storage_path,content_hash,
                 metadata_json,state)
                VALUES (:id,:owner,:workspace,:novel,'narration_export','export',:path,:hash,
                        '{}'::jsonb,'ready')"""),
                {"id": cancelled_export_asset, "owner": LOCAL_OWNER_ID,
                 "workspace": LOCAL_WORKSPACE_ID, "novel": novel_a,
                 "path": f"tts/export/{cancelled_export_asset}.m4b", "hash": "8" * 64})
            connection.execute(text("""INSERT INTO narration_exports
                (id,edition_id,request_id,request_allows_render,export_fingerprint,asset_id,state)
                VALUES (:id,:edition,:request,true,:fingerprint,:asset,'cancelled')"""),
                {"id": cancelled_export, "edition": edition_id, "request": generation_a,
                 "fingerprint": "8" * 64, "asset": cancelled_export_asset})
            _expect_db_rejection(connection,
                "UPDATE narration_exports SET state='ready' WHERE id=:id",
                {"id": cancelled_export})
            _expect_db_rejection(connection,
                "SET CONSTRAINTS trg_media_generated_reachability IMMEDIATE", {})
            cancelled_export_savepoint.rollback()
            connection.execute(text(
                "SET CONSTRAINTS trg_media_generated_reachability DEFERRED"
            ))
            deletion_request = uuid4()
            connection.execute(text("""INSERT INTO voice_deletion_requests
                (id,owner_id,workspace_id,voice_profile_id,command,state,impact_digest_key_id,
                 impact_digest,requested_actor,requested_at)
                VALUES (:id,:owner,:workspace,:profile,'true_delete_private_voice','requested','local-key',
                        :digest,'owner',now())"""),
                {"id": deletion_request, "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID,
                 "profile": profile_id, "digest": "d" * 64})
            _expect_db_rejection(connection, """INSERT INTO voice_deletion_requests
                (id,owner_id,workspace_id,voice_profile_id,command,state,impact_digest_key_id,
                 impact_digest,requested_actor,requested_at)
                VALUES (:id,:owner,:workspace,:profile,'delete_live_only','requested','local-key',
                        :digest,'owner',now())""",
                {"id": uuid4(), "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID,
                 "profile": profile_id, "digest": "e" * 64})
            _expect_db_rejection(connection,
                "UPDATE voice_deletion_requests SET command='delete_everything' WHERE id=:id",
                {"id": deletion_request})
            _expect_db_rejection(connection,
                "DELETE FROM voice_deletion_requests WHERE id=:id", {"id": deletion_request})
            connection.execute(text("""UPDATE voice_deletion_requests
                SET state='live_deleting',confirmed_actor='owner',confirmed_at=now() WHERE id=:id"""),
                {"id": deletion_request})
            _expect_db_rejection(connection,
                "UPDATE voice_deletion_requests SET confirmed_actor='attacker' WHERE id=:id",
                {"id": deletion_request})
            connection.execute(text(
                "UPDATE voice_deletion_requests SET state='failed',failure_code='retryable' WHERE id=:id"
            ), {"id": deletion_request})
            connection.execute(text(
                "UPDATE voice_deletion_requests SET state='live_deleting',failure_code=NULL WHERE id=:id"
            ), {"id": deletion_request})
            connection.execute(text("""INSERT INTO asset_tombstones
                (id,owner_id,workspace_id,original_asset_id,deletion_request_id,digest_key_id,
                 digest,reason_code,deleted_actor,deleted_at)
                VALUES (:id,:owner,:workspace,:asset,:request,'local-key',:digest,
                        'voice_delete','owner',now())"""),
                {"id": uuid4(), "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID,
                 "asset": foreign_reference, "request": deletion_request, "digest": "e" * 64})
            orphan_savepoint = connection.begin_nested()
            with pytest.raises((IntegrityError, DBAPIError)):
                connection.execute(text("""INSERT INTO media_assets
                    (id,owner_id,workspace_id,novel_id,kind,asset_class,storage_path,content_hash,metadata_json,
                     storage_backend,state,retention_policy,checksum_algorithm,validation_json,gc_generation)
                    VALUES (:id,:owner,:workspace,:novel,'narration_audio','segment_master','tts/orphan.wav',:hash,'{}'::jsonb,
                     'local','ready','derived','sha256','{}'::jsonb,0)"""),
                    {"id": uuid4(), "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID,
                     "novel": novel_a, "hash": "1" * 64})
                connection.execute(text("SET CONSTRAINTS trg_media_generated_reachability IMMEDIATE"))
            if orphan_savepoint.is_active:
                orphan_savepoint.rollback()
            connection.execute(text("SET CONSTRAINTS trg_media_generated_reachability DEFERRED"))

        with engine.begin() as connection:
            table_list = ",".join(f'"{name}"' for name in sorted(FOUNDATION_TABLES))
            connection.execute(text(f"TRUNCATE TABLE {table_list} CASCADE"))
            connection.execute(text("DELETE FROM media_assets WHERE asset_class IS NOT NULL"))
        command.downgrade(config, DOWN_REVISION)
        with engine.connect() as connection:
            assert "narration_requests" not in inspect(connection).get_table_names()
            assert connection.scalar(text("SELECT count(*) FROM media_assets WHERE kind='novel_cover'")) == 2
        command.upgrade(config, REVISION)
        with engine.begin() as connection:
            connection.execute(text("""INSERT INTO voice_rights_records
                (id,owner_id,workspace_id,novel_id,source_kind,source_identifier,notice_version,purpose,
                 commercial_use,redistribution,voice_cloning,confirmed_actor,confirmed_at,risk_flags_json)
                VALUES (:id,:owner,:workspace,:novel,'uploaded','self','v1','private',false,false,true,'owner',now(),'[]'::jsonb)"""),
                {"id": uuid4(), "owner": LOCAL_OWNER_ID, "workspace": LOCAL_WORKSPACE_ID, "novel": novel_a})
        with pytest.raises(Exception, match="downgrade refused"):
            command.downgrade(config, DOWN_REVISION)
        assert _script_directory().get_revision(REVISION) is not None
    finally:
        if old_database_url is None:
            os.environ.pop("AI_NOVEL_DATABASE_URL", None)
        else:
            os.environ["AI_NOVEL_DATABASE_URL"] = old_database_url
        engine.dispose()
