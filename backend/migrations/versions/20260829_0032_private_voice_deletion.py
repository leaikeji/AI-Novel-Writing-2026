"""Add recoverable request-scoped private voice deletion plans.

Revision ID: 20260829_0032
Revises: 20260829_0031

The migration adds only durable planning state.  It performs no filesystem or
backup deletion and does not rewrite immutable voice versions or Editions.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260829_0032"
down_revision = "20260829_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_voice_deletion_request_state",
        "voice_deletion_requests",
        type_="check",
    )
    op.drop_constraint(
        "ck_voice_deletion_request_command",
        "voice_deletion_requests",
        type_="check",
    )
    op.add_column(
        "voice_deletion_requests",
        sa.Column("novel_id", postgresql.UUID(as_uuid=True)),
    )
    op.add_column(
        "voice_deletion_requests", sa.Column("idempotency_key", sa.String(160))
    )
    op.add_column(
        "voice_deletion_requests", sa.Column("request_hash", sa.String(64))
    )
    op.add_column(
        "voice_deletion_requests",
        sa.Column("expected_profile_version", sa.BigInteger()),
    )
    op.add_column(
        "voice_deletion_requests",
        sa.Column(
            "impact_snapshot_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "voice_deletion_requests",
        sa.Column("impact_expires_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "voice_deletion_requests",
        sa.Column("execute_after", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "voice_deletion_requests",
        sa.Column("asset_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "voice_deletion_requests",
        sa.Column("total_bytes", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "voice_deletion_requests",
        sa.Column(
            "external_backup_status",
            sa.String(24),
            nullable=False,
            server_default="unmanaged",
        ),
    )
    op.add_column(
        "voice_deletion_requests", sa.Column("cancelled_actor", sa.String(120))
    )
    op.add_column(
        "voice_deletion_requests",
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "voice_deletion_requests",
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "voice_deletion_requests",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.execute(
        """
        UPDATE voice_deletion_requests request
        SET novel_id = profile.novel_id,
            expected_profile_version = profile.version,
            impact_expires_at = request.requested_at + interval '15 minutes'
        FROM voice_profiles profile
        WHERE profile.id = request.voice_profile_id
        """
    )
    op.create_foreign_key(
        "fk_voice_deletion_request_novel",
        "voice_deletion_requests",
        "novels",
        ["novel_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_voice_deletion_request_state",
        "voice_deletion_requests",
        "state IN ('grace_pending','requested','cancelled','live_deleting',"
        "'live_deleted_backup_pending','completed','failed')",
    )
    op.create_check_constraint(
        "ck_voice_deletion_request_command",
        "voice_deletion_requests",
        "command IN ('delete_uploaded_original_only',"
        "'discard_unreferenced_private_voice','true_delete_private_voice')",
    )
    op.create_check_constraint(
        "ck_voice_deletion_request_asset_totals",
        "voice_deletion_requests",
        "asset_count >= 0 AND total_bytes >= 0",
    )
    op.create_check_constraint(
        "ck_voice_deletion_request_backup_status",
        "voice_deletion_requests",
        "external_backup_status IN ('unmanaged','managed_pending','managed_expired')",
    )
    op.create_index(
        "ix_voice_deletion_requests_scope_profile_state",
        "voice_deletion_requests",
        ["owner_id", "workspace_id", "voice_profile_id", "state"],
    )
    op.create_index(
        "uq_voice_deletion_requests_idempotency",
        "voice_deletion_requests",
        ["owner_id", "workspace_id", "command", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index(
        "uq_voice_deletion_requests_active_profile",
        "voice_deletion_requests",
        ["owner_id", "workspace_id", "voice_profile_id"],
        unique=True,
        postgresql_where=sa.text(
            "state IN ('grace_pending','requested','live_deleting',"
            "'live_deleted_backup_pending','failed')"
        ),
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION narration_guard_voice_deletion()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP='INSERT' THEN
            IF NEW.state NOT IN ('grace_pending','requested')
               OR NEW.confirmed_actor IS NOT NULL OR NEW.confirmed_at IS NOT NULL
            THEN RAISE EXCEPTION 'voice deletion must be inserted unconfirmed/pending'; END IF;
            RETURN NEW;
          END IF;
          IF TG_OP='DELETE' THEN RAISE EXCEPTION 'voice deletion request cannot be deleted'; END IF;
          IF OLD.state IN ('completed','cancelled')
          THEN RAISE EXCEPTION 'terminal voice deletion is immutable'; END IF;
          IF OLD.confirmed_actor IS NOT NULL AND
             (OLD.confirmed_actor,OLD.confirmed_at) IS DISTINCT FROM
             (NEW.confirmed_actor,NEW.confirmed_at)
          THEN RAISE EXCEPTION 'voice deletion confirmation is write-once'; END IF;
          IF (NEW.confirmed_actor IS NULL)<>(NEW.confirmed_at IS NULL)
          THEN RAISE EXCEPTION 'voice deletion confirmation actor/time must be paired'; END IF;
          IF (to_jsonb(OLD)-ARRAY['state','confirmed_actor','confirmed_at',
                 'cancelled_actor','cancelled_at','failure_code','completed_at','updated_at']) <>
             (to_jsonb(NEW)-ARRAY['state','confirmed_actor','confirmed_at',
                 'cancelled_actor','cancelled_at','failure_code','completed_at','updated_at'])
          THEN RAISE EXCEPTION 'voice deletion canonical request is immutable'; END IF;
          IF OLD.state<>NEW.state AND NOT (
            (OLD.state IN ('grace_pending','requested')
             AND NEW.state IN ('cancelled','live_deleting','failed')) OR
            (OLD.state='live_deleting'
             AND NEW.state IN ('live_deleted_backup_pending','completed','failed')) OR
            (OLD.state='live_deleted_backup_pending'
             AND NEW.state IN ('completed','failed')) OR
            (OLD.state='failed' AND NEW.state='live_deleting')
          ) THEN RAISE EXCEPTION 'invalid voice deletion state transition'; END IF;
          RETURN NEW;
        END $$;
        """
    )

    op.create_table(
        "voice_deletion_asset_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("deletion_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(24), nullable=False),
        sa.Column("storage_backend", sa.String(40), nullable=False),
        sa.Column("storage_path", sa.String(1024), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("gc_generation", sa.BigInteger(), nullable=False),
        sa.Column("file_present", sa.Boolean(), nullable=False),
        sa.Column("device", sa.BigInteger()),
        sa.Column("inode", sa.BigInteger()),
        sa.Column("state", sa.String(24), nullable=False, server_default="planned"),
        sa.Column("unlinked_at", sa.DateTime(timezone=True)),
        sa.Column("finalized_at", sa.DateTime(timezone=True)),
        sa.Column("failure_code", sa.String(96)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["deletion_request_id"],
            ["voice_deletion_requests.id"],
            name="fk_voice_deletion_asset_plan_request",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["novel_id"],
            ["novels.id"],
            name="fk_voice_deletion_asset_plan_novel",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id", "owner_id", "workspace_id"],
            ["media_assets.id", "media_assets.owner_id", "media_assets.workspace_id"],
            name="fk_voice_deletion_asset_plan_media_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "deletion_request_id",
            "asset_id",
            name="uq_voice_deletion_asset_plan_request_asset",
        ),
        sa.CheckConstraint(
            "role IN ('reference','preview','render_master','render_playback','export')",
            name="ck_voice_deletion_asset_plan_role",
        ),
        sa.CheckConstraint(
            "state IN ('planned','unlinking','unlinked','finalized','failed')",
            name="ck_voice_deletion_asset_plan_state",
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$' AND byte_size >= 0 AND gc_generation >= 0",
            name="ck_voice_deletion_asset_plan_identity",
        ),
        sa.CheckConstraint(
            "(file_present IS TRUE AND device IS NOT NULL AND inode IS NOT NULL) OR "
            "(file_present IS FALSE AND device IS NULL AND inode IS NULL)",
            name="ck_voice_deletion_asset_plan_file_identity",
        ),
    )
    op.create_index(
        "ix_voice_deletion_asset_plans_request_state",
        "voice_deletion_asset_plans",
        ["deletion_request_id", "state"],
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION narration_guard_media_identity_v2()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP='DELETE' THEN
            IF OLD.asset_class IS NOT NULL OR OLD.state <> 'deleted' THEN
              RAISE EXCEPTION 'narration/undeleted media rows cannot be deleted';
            END IF;
            RETURN OLD;
          END IF;
          IF OLD.state IN ('ready','quarantined','deleting','deleted') AND
             (OLD.owner_id,OLD.workspace_id,OLD.novel_id,OLD.storage_backend,
              OLD.storage_path,OLD.content_hash,OLD.byte_size,OLD.checksum_algorithm,
              OLD.mime_type) IS DISTINCT FROM
             (NEW.owner_id,NEW.workspace_id,NEW.novel_id,NEW.storage_backend,
              NEW.storage_path,NEW.content_hash,NEW.byte_size,NEW.checksum_algorithm,
              NEW.mime_type)
          THEN RAISE EXCEPTION 'published media physical identity is immutable'; END IF;
          IF OLD.gc_generation <> NEW.gc_generation AND NOT (
             OLD.state='ready' AND NEW.gc_generation=OLD.gc_generation+1
             AND NEW.gc_marked_at IS NOT NULL)
          THEN RAISE EXCEPTION 'media GC generation may only advance by one while ready'; END IF;
          IF OLD.state <> NEW.state AND NOT (
            (OLD.state='staging' AND NEW.state IN ('ready','quarantined','deleting')) OR
            (OLD.state='ready' AND NEW.state IN ('quarantined','deleting')) OR
            (OLD.state='quarantined' AND NEW.state='deleting') OR
            (OLD.state='deleting' AND NEW.state IN ('deleted','quarantined'))
          ) THEN RAISE EXCEPTION 'invalid media state transition'; END IF;
          IF NEW.state='deleting' AND OLD.state<>'deleting'
             AND narration_media_has_live_reference(NEW.id)
             AND NOT EXISTS (
               SELECT 1
               FROM voice_deletion_asset_plans plan
               JOIN voice_deletion_requests request
                 ON request.id=plan.deletion_request_id
               WHERE plan.asset_id=NEW.id
                 AND plan.owner_id=NEW.owner_id
                 AND plan.workspace_id=NEW.workspace_id
                 AND plan.novel_id=NEW.novel_id
                 AND plan.storage_backend=NEW.storage_backend
                 AND plan.storage_path=NEW.storage_path
                 AND plan.content_hash=NEW.content_hash
                 AND plan.byte_size=NEW.byte_size
                 AND plan.gc_generation=NEW.gc_generation
                 AND plan.state='planned'
                 AND request.state IN ('grace_pending','requested','failed')
                 AND request.confirmed_actor IS NOT NULL
                 AND request.confirmed_at IS NOT NULL
             )
          THEN RAISE EXCEPTION 'referenced media cannot transition to deleting'; END IF;
          RETURN NEW;
        END $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION narration_guard_media_deleting_plan()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.state='deleting' AND NOT EXISTS (
            SELECT 1 FROM media_gc_deletion_plans plan
            WHERE plan.asset_id=NEW.id
              AND (plan.owner_id,plan.workspace_id,plan.novel_id,plan.storage_backend,
                   plan.storage_path,plan.content_hash,plan.byte_size,plan.generation)
                  IS NOT DISTINCT FROM
                  (NEW.owner_id,NEW.workspace_id,NEW.novel_id,NEW.storage_backend,
                   NEW.storage_path,NEW.content_hash,NEW.byte_size,NEW.gc_generation)
          ) AND NOT EXISTS (
            SELECT 1
            FROM voice_deletion_asset_plans plan
            JOIN voice_deletion_requests request
              ON request.id=plan.deletion_request_id
            WHERE plan.asset_id=NEW.id
              AND (plan.owner_id,plan.workspace_id,plan.novel_id,plan.storage_backend,
                   plan.storage_path,plan.content_hash,plan.byte_size,plan.gc_generation)
                  IS NOT DISTINCT FROM
                  (NEW.owner_id,NEW.workspace_id,NEW.novel_id,NEW.storage_backend,
                   NEW.storage_path,NEW.content_hash,NEW.byte_size,NEW.gc_generation)
              AND request.state='live_deleting'
              AND request.confirmed_actor IS NOT NULL
              AND request.confirmed_at IS NOT NULL
          ) THEN
            RAISE EXCEPTION 'deleting media requires a matching durable deletion plan';
          END IF;
          RETURN NEW;
        END $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION narration_guard_voice_delete_tombstone()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.deletion_request_id IS NOT NULL AND NOT EXISTS (
            SELECT 1
            FROM voice_deletion_asset_plans plan
            WHERE plan.deletion_request_id = NEW.deletion_request_id
              AND plan.asset_id = NEW.original_asset_id
              AND plan.state IN ('unlinked','finalized')
          ) THEN
            RAISE EXCEPTION 'voice deletion tombstone requires its frozen asset plan';
          END IF;
          RETURN NEW;
        END $$;

        CREATE TRIGGER trg_voice_delete_tombstone_guard
        BEFORE INSERT OR UPDATE ON asset_tombstones
        FOR EACH ROW EXECUTE FUNCTION narration_guard_voice_delete_tombstone();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_voice_delete_tombstone_guard ON asset_tombstones")
    op.execute("DROP FUNCTION IF EXISTS narration_guard_voice_delete_tombstone()")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION narration_guard_media_identity_v2()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP='DELETE' THEN
            IF OLD.asset_class IS NOT NULL OR OLD.state <> 'deleted' THEN
              RAISE EXCEPTION 'narration/undeleted media rows cannot be deleted';
            END IF;
            RETURN OLD;
          END IF;
          IF OLD.state IN ('ready','quarantined','deleting','deleted') AND
             (OLD.owner_id,OLD.workspace_id,OLD.novel_id,OLD.storage_backend,
              OLD.storage_path,OLD.content_hash,OLD.byte_size,OLD.checksum_algorithm,
              OLD.mime_type) IS DISTINCT FROM
             (NEW.owner_id,NEW.workspace_id,NEW.novel_id,NEW.storage_backend,
              NEW.storage_path,NEW.content_hash,NEW.byte_size,NEW.checksum_algorithm,
              NEW.mime_type)
          THEN RAISE EXCEPTION 'published media physical identity is immutable'; END IF;
          IF OLD.gc_generation <> NEW.gc_generation AND NOT (
             OLD.state='ready' AND NEW.gc_generation=OLD.gc_generation+1
             AND NEW.gc_marked_at IS NOT NULL)
          THEN RAISE EXCEPTION 'media GC generation may only advance by one while ready'; END IF;
          IF OLD.state <> NEW.state AND NOT (
            (OLD.state='staging' AND NEW.state IN ('ready','quarantined','deleting')) OR
            (OLD.state='ready' AND NEW.state IN ('quarantined','deleting')) OR
            (OLD.state='quarantined' AND NEW.state='deleting') OR
            (OLD.state='deleting' AND NEW.state IN ('deleted','quarantined'))
          ) THEN RAISE EXCEPTION 'invalid media state transition'; END IF;
          IF NEW.state='deleting' AND OLD.state<>'deleting'
             AND narration_media_has_live_reference(NEW.id)
          THEN RAISE EXCEPTION 'referenced media cannot transition to deleting'; END IF;
          RETURN NEW;
        END $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION narration_guard_media_deleting_plan()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.state='deleting' AND NOT EXISTS (
            SELECT 1 FROM media_gc_deletion_plans plan
            WHERE plan.asset_id=NEW.id
              AND (plan.owner_id,plan.workspace_id,plan.novel_id,plan.storage_backend,
                   plan.storage_path,plan.content_hash,plan.byte_size,plan.generation)
                  IS NOT DISTINCT FROM
                  (NEW.owner_id,NEW.workspace_id,NEW.novel_id,NEW.storage_backend,
                   NEW.storage_path,NEW.content_hash,NEW.byte_size,NEW.gc_generation)
          ) THEN
            RAISE EXCEPTION 'deleting media requires a matching durable GC plan';
          END IF;
          RETURN NEW;
        END $$;
        """
    )
    op.drop_index(
        "ix_voice_deletion_asset_plans_request_state",
        table_name="voice_deletion_asset_plans",
    )
    op.drop_table("voice_deletion_asset_plans")
    op.drop_index(
        "uq_voice_deletion_requests_active_profile",
        table_name="voice_deletion_requests",
    )
    op.drop_index(
        "uq_voice_deletion_requests_idempotency",
        table_name="voice_deletion_requests",
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION narration_guard_voice_deletion()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP='INSERT' THEN
            IF NEW.state<>'requested' OR NEW.confirmed_actor IS NOT NULL OR NEW.confirmed_at IS NOT NULL
            THEN RAISE EXCEPTION 'voice deletion must be inserted unconfirmed/requested'; END IF;
            RETURN NEW;
          END IF;
          IF TG_OP='DELETE' THEN RAISE EXCEPTION 'voice deletion request cannot be deleted'; END IF;
          IF OLD.state='completed' THEN RAISE EXCEPTION 'completed voice deletion is immutable'; END IF;
          IF OLD.confirmed_actor IS NOT NULL AND
             (OLD.confirmed_actor,OLD.confirmed_at) IS DISTINCT FROM (NEW.confirmed_actor,NEW.confirmed_at)
          THEN RAISE EXCEPTION 'voice deletion confirmation is write-once'; END IF;
          IF (NEW.confirmed_actor IS NULL)<>(NEW.confirmed_at IS NULL)
          THEN RAISE EXCEPTION 'voice deletion confirmation actor/time must be paired'; END IF;
          IF (to_jsonb(OLD)-ARRAY['state','confirmed_actor','confirmed_at','failure_code']) <>
             (to_jsonb(NEW)-ARRAY['state','confirmed_actor','confirmed_at','failure_code'])
          THEN RAISE EXCEPTION 'voice deletion canonical request is immutable'; END IF;
          IF OLD.state<>NEW.state AND NOT (
            (OLD.state='requested' AND NEW.state IN ('live_deleting','failed')) OR
            (OLD.state='live_deleting' AND NEW.state IN ('live_deleted_backup_pending','failed')) OR
            (OLD.state='live_deleted_backup_pending' AND NEW.state IN ('completed','failed')) OR
            (OLD.state='failed' AND NEW.state='live_deleting')
          ) THEN RAISE EXCEPTION 'invalid voice deletion state transition'; END IF;
          RETURN NEW;
        END $$;
        """
    )
    op.drop_index(
        "ix_voice_deletion_requests_scope_profile_state",
        table_name="voice_deletion_requests",
    )
    op.drop_constraint(
        "ck_voice_deletion_request_backup_status",
        "voice_deletion_requests",
        type_="check",
    )
    op.drop_constraint(
        "ck_voice_deletion_request_asset_totals",
        "voice_deletion_requests",
        type_="check",
    )
    op.drop_constraint(
        "ck_voice_deletion_request_command",
        "voice_deletion_requests",
        type_="check",
    )
    op.drop_constraint(
        "ck_voice_deletion_request_state",
        "voice_deletion_requests",
        type_="check",
    )
    op.create_check_constraint(
        "ck_voice_deletion_request_state",
        "voice_deletion_requests",
        "state IN ('requested','live_deleting','live_deleted_backup_pending','completed','failed')",
    )
    op.create_check_constraint(
        "ck_voice_deletion_request_command",
        "voice_deletion_requests",
        "command IN ('delete_uploaded_original_only','true_delete_private_voice')",
    )
    op.drop_constraint(
        "fk_voice_deletion_request_novel",
        "voice_deletion_requests",
        type_="foreignkey",
    )
    for column in (
        "updated_at",
        "completed_at",
        "cancelled_at",
        "cancelled_actor",
        "external_backup_status",
        "total_bytes",
        "asset_count",
        "execute_after",
        "impact_expires_at",
        "impact_snapshot_json",
        "expected_profile_version",
        "request_hash",
        "idempotency_key",
        "novel_id",
    ):
        op.drop_column("voice_deletion_requests", column)
