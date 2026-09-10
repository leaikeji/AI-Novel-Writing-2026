"""Authorize exact whole-novel deletion across immutable narration evidence.

Revision ID: 20260910_0051
Revises: 20260909_0050

Narration audit rows deliberately reject ordinary mutation statements. A novel
deletion is different: the author has confirmed removal of the complete novel,
including its derived narration evidence and media. This migration keeps the
existing guards intact and suppresses their execution only while the same
transaction owns an uncommitted ``purging`` audit row. This also permits the
two pointer-clearing UPDATEs needed to break non-deferrable reference cycles.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260910_0051"
down_revision = "20260909_0050"
branch_labels = None
depends_on = None


_DELETE_GUARD_TABLES = (
    "active_job_assets",
    "asset_tombstones",
    "anonymous_speakers",
    "background_job_attempts",
    "background_jobs",
    "background_manual_retry_commands",
    "character_voice_bindings",
    "document_narration_state",
    "document_revisions",
    "documents",
    "media_assets",
    "media_gc_deletion_plans",
    "model_run_records",
    "narration_cloud_consents",
    "narration_edition_segments",
    "narration_edition_state",
    "narration_editions",
    "narration_exports",
    "narration_manifest_segments",
    "narration_manifests",
    "narration_playback_progress",
    "narration_render_assets",
    "narration_request_sources",
    "narration_requests",
    "narration_scope_overrides",
    "narration_scenes",
    "narration_script_issues",
    "narration_script_review_actions",
    "narration_script_versions",
    "narration_scripts",
    "narration_segment_renders",
    "narration_segments",
    "narration_settings_snapshots",
    "novel_narration_settings",
    "pronunciation_entries",
    "pronunciation_profiles",
    "voice_action_commands",
    "voice_action_receipts",
    "voice_deletion_asset_plans",
    "voice_deletion_requests",
    "voice_previews",
    "voice_profile_versions",
    "voice_profiles",
    "voice_reference_asset_links",
    "voice_rights_events",
    "voice_rights_records",
    "volumes",
)


def _table_array() -> str:
    return ",".join(f"'{name}'" for name in _DELETE_GUARD_TABLES)


def upgrade():
    # These two constraints form an intentional, deferrable audit cycle. PostgreSQL
    # RESTRICT is nevertheless checked immediately, so change only the action to
    # NO ACTION and retain commit-time referential integrity.
    op.drop_constraint(
        "fk_background_manual_retry_claimed_attempt",
        "background_manual_retry_commands",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_background_job_attempt_manual_retry_command",
        "background_job_attempts",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_background_manual_retry_claimed_attempt",
        "background_manual_retry_commands",
        "background_job_attempts",
        ["claimed_attempt_id"],
        ["id"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_background_job_attempt_manual_retry_command",
        "background_job_attempts",
        "background_manual_retry_commands",
        ["manual_retry_command_id"],
        ["id"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_table(
        "novel_deletion_audits",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expected_version", sa.BigInteger(), nullable=False),
        sa.Column("title_sha256", sa.String(64), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("media_manifest_json", postgresql.JSONB(), nullable=False),
        sa.Column("media_count", sa.Integer(), nullable=False),
        sa.Column("media_bytes", sa.BigInteger(), nullable=False),
        sa.Column("confirmed_actor", sa.String(120), nullable=False),
        sa.Column("failure_code", sa.String(96)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("database_deleted_at", sa.DateTime(timezone=True)),
        sa.Column("media_deleted_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("expected_version >= 1", name="ck_novel_deletion_expected_version"),
        sa.CheckConstraint("title_sha256 ~ '^[0-9a-f]{64}$'", name="ck_novel_deletion_title_hash"),
        sa.CheckConstraint("media_count >= 0 AND media_bytes >= 0", name="ck_novel_deletion_media_totals"),
        sa.CheckConstraint(
            "state IN ('purging','database_deleted','completed','media_cleanup_failed')",
            name="ck_novel_deletion_state",
        ),
    )
    op.create_index(
        "ix_novel_deletion_audits_novel_created",
        "novel_deletion_audits",
        ["novel_id", "created_at"],
    )
    op.create_index(
        "ix_novel_deletion_audits_state",
        "novel_deletion_audits",
        ["state", "updated_at"],
    )
    op.execute(
        r"""
        CREATE FUNCTION narration_novel_deletion_authorized()
        RETURNS boolean
        LANGUAGE plpgsql
        STABLE
        SET search_path = public, pg_temp
        AS $novel_delete$
        DECLARE request_value text;
        BEGIN
          request_value := current_setting(
            'ai_novel.novel_deletion_request_id', true
          );
          IF request_value IS NULL OR request_value !~
            '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
          THEN
            RETURN false;
          END IF;
          RETURN EXISTS (
            SELECT 1 FROM novel_deletion_audits
            WHERE id=request_value::uuid AND state='purging'
          );
        END
        $novel_delete$;
        """
    )
    op.execute(
        f"""
        DO $novel_delete$
        DECLARE
          trigger_row record;
          trigger_definition text;
          guarded_definition text;
        BEGIN
          FOR trigger_row IN
            SELECT trigger.oid, namespace.nspname, relation.relname,
                   trigger.tgname
            FROM pg_trigger trigger
            JOIN pg_class relation ON relation.oid=trigger.tgrelid
            JOIN pg_namespace namespace ON namespace.oid=relation.relnamespace
            WHERE NOT trigger.tgisinternal
              AND namespace.nspname='public'
              AND relation.relname = ANY(
                ARRAY[{_table_array()}]::text[]
              )
            ORDER BY relation.relname, trigger.tgname
          LOOP
            trigger_definition := pg_get_triggerdef(trigger_row.oid);
            IF position(' WHEN (' IN trigger_definition)>0 OR
               position(' EXECUTE FUNCTION ' IN trigger_definition)=0
            THEN
              RAISE EXCEPTION
                'novel deletion trigger shape changed: %.%',
                trigger_row.relname, trigger_row.tgname;
            END IF;
            guarded_definition := replace(
              trigger_definition,
              ' EXECUTE FUNCTION ',
              ' WHEN (NOT narration_novel_deletion_authorized()) EXECUTE FUNCTION '
            );
            EXECUTE format(
              'DROP TRIGGER %I ON %I.%I',
              trigger_row.tgname, trigger_row.nspname, trigger_row.relname
            );
            EXECUTE guarded_definition;
          END LOOP;
        END
        $novel_delete$;
        """
    )


def downgrade():
    raise RuntimeError(
        "whole-novel deletion authorization is forward-only; restore the pre-0051 database backup"
    )
