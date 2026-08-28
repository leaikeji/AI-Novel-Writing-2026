"""Add the durable product voice upload and preview pipeline.

Revision ID: 20260827_0021
Revises: 20260827_0020

The migration is PostgreSQL-only and performs no filesystem/model/network I/O.
It preserves existing rows, adds exact-null scope closure for library previews,
and refuses a downgrade once product voice evidence exists.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260827_0021"
down_revision = "20260827_0020"
branch_labels = None
depends_on = None


LOCAL_OWNER = "29cf94d9-a5c9-54ec-912c-5dfff8738c4c"
LOCAL_WORKSPACE = "f0e2e632-bc99-52d2-9916-bb906aa4da6e"


def _preflight() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
              IF EXISTS (
                SELECT 1
                FROM active_job_assets a
                LEFT JOIN background_jobs j ON j.id=a.job_id
                LEFT JOIN media_assets m ON m.id=a.asset_id
                WHERE j.id IS NULL OR m.id IS NULL
                   OR (j.owner_id,j.workspace_id,j.novel_id) IS DISTINCT FROM
                      (a.owner_id,a.workspace_id,a.novel_id)
                   OR (m.owner_id,m.workspace_id,m.novel_id) IS DISTINCT FROM
                      (a.owner_id,a.workspace_id,a.novel_id)
              ) THEN
                RAISE EXCEPTION
                  'T4 voice preflight: active job media scope is ambiguous';
              END IF;
            END $$;
            """
        )
    )


def _extend_active_job_assets() -> None:
    op.drop_constraint(
        "fk_active_job_asset_job_scope", "active_job_assets", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_active_job_asset_media_scope", "active_job_assets", type_="foreignkey"
    )
    op.alter_column(
        "active_job_assets",
        "novel_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.create_foreign_key(
        "fk_active_job_asset_job_scope",
        "active_job_assets",
        "background_jobs",
        ["job_id", "owner_id", "workspace_id", "novel_id"],
        ["id", "owner_id", "workspace_id", "novel_id"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_active_job_asset_media_scope",
        "active_job_assets",
        "media_assets",
        ["asset_id", "owner_id", "workspace_id", "novel_id"],
        ["id", "owner_id", "workspace_id", "novel_id"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )


def _create_product_tables() -> None:
    owner_default = sa.text(f"'{LOCAL_OWNER}'::uuid")
    workspace_default = sa.text(f"'{LOCAL_WORKSPACE}'::uuid")

    op.create_table(
        "voice_action_receipts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=owner_default,
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=workspace_default,
        ),
        sa.Column("operation", sa.String(48), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column(
            "reserved_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "owner_id",
            "workspace_id",
            "operation",
            "idempotency_key",
            name="uq_voice_action_receipt_idempotency",
        ),
        sa.UniqueConstraint(
            "owner_id",
            "workspace_id",
            "operation",
            "resource_id",
            name="uq_voice_action_receipt_resource",
        ),
        sa.CheckConstraint(
            f"owner_id='{LOCAL_OWNER}'::uuid "
            f"AND workspace_id='{LOCAL_WORKSPACE}'::uuid",
            name="ck_voice_action_receipt_fixed_local_scope",
        ),
        sa.CheckConstraint(
            "operation ~ '^[a-z][a-z0-9_]{2,47}$'",
            name="ck_voice_action_receipt_operation",
        ),
        sa.CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$'",
            name="ck_voice_action_receipt_idempotency_key",
        ),
        sa.CheckConstraint(
            "request_hash ~ '^[0-9a-f]{64}$'",
            name="ck_voice_action_receipt_request_hash",
        ),
        sa.CheckConstraint(
            "state IN ('reserved','completed')",
            name="ck_voice_action_receipt_state",
        ),
        sa.CheckConstraint(
            "(state='reserved' AND completed_at IS NULL) OR "
            "(state='completed' AND completed_at IS NOT NULL "
            "AND completed_at>=reserved_at)",
            name="ck_voice_action_receipt_lifecycle",
        ),
    )

    op.create_table(
        "voice_reference_asset_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True)),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("voice_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rights_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reference_asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("normalization_fingerprint", sa.String(64), nullable=False),
        sa.Column("validation_fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["novel_id"],
            ["novels.id"],
            name="fk_voice_reference_link_novel",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["voice_profiles.id"],
            name="fk_voice_reference_link_profile",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["voice_version_id", "profile_id"],
            ["voice_profile_versions.id", "voice_profile_versions.profile_id"],
            name="fk_voice_reference_link_version_profile",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rights_record_id"],
            ["voice_rights_records.id"],
            name="fk_voice_reference_link_rights",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_asset_id"],
            ["media_assets.id"],
            name="fk_voice_reference_link_source_asset",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reference_asset_id"],
            ["media_assets.id"],
            name="fk_voice_reference_link_reference_asset",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "voice_version_id", name="uq_voice_reference_link_version"
        ),
        sa.CheckConstraint(
            f"owner_id='{LOCAL_OWNER}'::uuid "
            f"AND workspace_id='{LOCAL_WORKSPACE}'::uuid",
            name="ck_voice_reference_link_fixed_local_scope",
        ),
        sa.CheckConstraint(
            "normalization_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_voice_reference_link_normalization_fingerprint",
        ),
        sa.CheckConstraint(
            "validation_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_voice_reference_link_validation_fingerprint",
        ),
        sa.CheckConstraint(
            "source_asset_id<>reference_asset_id",
            name="ck_voice_reference_link_distinct_assets",
        ),
    )
    op.create_index(
        "ix_voice_reference_links_scope_profile",
        "voice_reference_asset_links",
        ["owner_id", "workspace_id", "novel_id", "profile_id"],
    )
    op.create_index(
        "ix_voice_reference_links_source_asset",
        "voice_reference_asset_links",
        ["source_asset_id"],
    )
    op.create_index(
        "ix_voice_reference_links_reference_asset",
        "voice_reference_asset_links",
        ["reference_asset_id"],
    )

    op.create_table(
        "voice_previews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True)),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rights_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reference_asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("result_asset_id", postgresql.UUID(as_uuid=True)),
        sa.Column("preview_text", sa.Text()),
        sa.Column("preview_text_digest_key_id", sa.String(80), nullable=False),
        sa.Column("preview_text_digest", sa.String(64), nullable=False),
        sa.Column("model_fingerprint", sa.String(64), nullable=False),
        sa.Column("reference_fingerprint", sa.String(64), nullable=False),
        sa.Column("parameters_fingerprint", sa.String(64), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("failure_code", sa.String(96)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["novel_id"],
            ["novels.id"],
            name="fk_voice_preview_novel",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["voice_profiles.id"],
            name="fk_voice_preview_profile",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["version_id", "profile_id"],
            ["voice_profile_versions.id", "voice_profile_versions.profile_id"],
            name="fk_voice_preview_version_profile",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rights_record_id"],
            ["voice_rights_records.id"],
            name="fk_voice_preview_rights",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["background_jobs.id"],
            name="fk_voice_preview_job",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reference_asset_id"],
            ["media_assets.id"],
            name="fk_voice_preview_reference_asset",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["result_asset_id"],
            ["media_assets.id"],
            name="fk_voice_preview_result_asset",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("job_id", name="uq_voice_preview_job"),
        sa.CheckConstraint(
            f"owner_id='{LOCAL_OWNER}'::uuid "
            f"AND workspace_id='{LOCAL_WORKSPACE}'::uuid",
            name="ck_voice_preview_fixed_local_scope",
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','ready','failed','cancelled')",
            name="ck_voice_preview_status",
        ),
        sa.CheckConstraint(
            "preview_text_digest_key_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$' "
            "AND preview_text_digest ~ '^[0-9a-f]{64}$'",
            name="ck_voice_preview_text_digest",
        ),
        sa.CheckConstraint(
            "model_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND reference_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND parameters_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND request_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_voice_preview_fingerprints",
        ),
        sa.CheckConstraint(
            "preview_text IS NULL OR "
            "(char_length(preview_text) BETWEEN 1 AND 500 AND btrim(preview_text)<>'')",
            name="ck_voice_preview_private_text_bounds",
        ),
        sa.CheckConstraint(
            "(status='queued' AND preview_text IS NOT NULL AND started_at IS NULL "
            "AND completed_at IS NULL AND result_asset_id IS NULL "
            "AND expires_at IS NULL AND failure_code IS NULL) OR "
            "(status='running' AND preview_text IS NOT NULL AND started_at IS NOT NULL "
            "AND completed_at IS NULL AND result_asset_id IS NULL "
            "AND expires_at IS NULL AND failure_code IS NULL) OR "
            "(status='ready' AND preview_text IS NULL AND completed_at IS NOT NULL "
            "AND result_asset_id IS NOT NULL AND expires_at IS NOT NULL "
            "AND expires_at>completed_at AND failure_code IS NULL) OR "
            "(status='failed' AND preview_text IS NULL AND completed_at IS NOT NULL "
            "AND result_asset_id IS NULL AND expires_at IS NULL "
            "AND failure_code IS NOT NULL AND btrim(failure_code)<>'') OR "
            "(status='cancelled' AND preview_text IS NULL AND completed_at IS NOT NULL "
            "AND result_asset_id IS NULL AND expires_at IS NULL "
            "AND failure_code IS NULL)",
            name="ck_voice_preview_lifecycle_shape",
        ),
    )
    op.create_index(
        "ix_voice_previews_scope_status",
        "voice_previews",
        ["owner_id", "workspace_id", "novel_id", "status"],
    )
    op.create_index(
        "ix_voice_previews_expiry",
        "voice_previews",
        ["expires_at", "status"],
    )
    op.create_index(
        "ix_voice_previews_reference_asset",
        "voice_previews",
        ["reference_asset_id"],
    )
    op.create_index(
        "ix_voice_previews_result_asset",
        "voice_previews",
        ["result_asset_id"],
    )


def _create_product_guards() -> None:
    op.execute(
        sa.text(
            """
            CREATE FUNCTION narration_guard_voice_action_receipt_v1()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF TG_OP='INSERT' THEN
                IF NEW.state<>'reserved' OR NEW.completed_at IS NOT NULL THEN
                  RAISE EXCEPTION 'voice action receipt must be inserted reserved';
                END IF;
                RETURN NEW;
              END IF;
              IF TG_OP='DELETE' THEN
                RAISE EXCEPTION 'voice action receipt cannot be deleted';
              END IF;
              IF OLD.state<>'reserved' OR NEW.state<>'completed'
                 OR NEW.completed_at IS NULL
              THEN
                RAISE EXCEPTION 'voice action receipt only permits reserved to completed';
              END IF;
              IF (OLD.id,OLD.owner_id,OLD.workspace_id,OLD.operation,
                  OLD.idempotency_key,OLD.request_hash,OLD.resource_id,OLD.reserved_at)
                 IS DISTINCT FROM
                 (NEW.id,NEW.owner_id,NEW.workspace_id,NEW.operation,
                  NEW.idempotency_key,NEW.request_hash,NEW.resource_id,NEW.reserved_at)
              THEN
                RAISE EXCEPTION 'voice action receipt canonical identity is immutable';
              END IF;
              RETURN NEW;
            END $$;

            CREATE TRIGGER trg_t4_voice_action_receipt_guard
            BEFORE INSERT OR UPDATE OR DELETE ON voice_action_receipts
            FOR EACH ROW EXECUTE FUNCTION narration_guard_voice_action_receipt_v1();

            CREATE FUNCTION narration_reject_voice_reference_link_mutation_v1()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              RAISE EXCEPTION 'voice reference provenance is immutable';
            END $$;

            CREATE TRIGGER trg_t4_voice_reference_link_immutable
            BEFORE UPDATE OR DELETE ON voice_reference_asset_links
            FOR EACH ROW
            EXECUTE FUNCTION narration_reject_voice_reference_link_mutation_v1();

            CREATE FUNCTION narration_guard_voice_reference_link_scope_v1()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF NOT EXISTS (
                SELECT 1
                FROM voice_profiles p
                JOIN voice_profile_versions v
                  ON v.id=NEW.voice_version_id AND v.profile_id=p.id
                JOIN voice_rights_records r ON r.id=NEW.rights_record_id
                JOIN media_assets source ON source.id=NEW.source_asset_id
                JOIN media_assets reference ON reference.id=NEW.reference_asset_id
                WHERE p.id=NEW.profile_id
                  AND (p.owner_id,p.workspace_id,p.novel_id) IS NOT DISTINCT FROM
                      (NEW.owner_id,NEW.workspace_id,NEW.novel_id)
                  AND p.status IN ('draft','active')
                  AND (v.owner_id,v.workspace_id)=(NEW.owner_id,NEW.workspace_id)
                  AND v.source_type='uploaded'
                  AND v.state IN ('draft','preview_ready','locked')
                  AND v.rights_record_id=r.id
                  AND v.reference_asset_id=reference.id
                  AND (r.owner_id,r.workspace_id,r.novel_id) IS NOT DISTINCT FROM
                      (NEW.owner_id,NEW.workspace_id,NEW.novel_id)
                  AND r.source_kind='user_upload'
                  AND r.voice_cloning IS TRUE
                  AND (r.expires_at IS NULL OR r.expires_at>CURRENT_TIMESTAMP)
                  AND EXISTS (
                    SELECT 1 FROM voice_rights_events confirmed
                    WHERE confirmed.rights_record_id=r.id
                      AND confirmed.event_type='confirmed'
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM voice_rights_events e
                    WHERE e.rights_record_id=r.id
                      AND e.event_type IN ('revoked','expired','review_blocked')
                  )
                  AND (source.owner_id,source.workspace_id,source.novel_id)
                      IS NOT DISTINCT FROM
                      (NEW.owner_id,NEW.workspace_id,NEW.novel_id)
                  AND source.kind='narration_voice_reference_source'
                  AND source.asset_class='source'
                  AND source.state='ready'
                  AND source.retention_policy='uploaded_original'
                  AND (reference.owner_id,reference.workspace_id,reference.novel_id)
                      IS NOT DISTINCT FROM
                      (NEW.owner_id,NEW.workspace_id,NEW.novel_id)
                  AND reference.kind='narration_voice_reference'
                  AND reference.asset_class='voice_reference'
                  AND reference.state='ready'
                  AND reference.retention_policy='locked_voice'
              ) THEN
                RAISE EXCEPTION
                  'voice reference link profile/version/rights/media closure mismatch';
              END IF;
              RETURN NULL;
            END $$;

            CREATE CONSTRAINT TRIGGER trg_t4_voice_reference_link_scope
            AFTER INSERT OR UPDATE ON voice_reference_asset_links
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION narration_guard_voice_reference_link_scope_v1();

            CREATE OR REPLACE FUNCTION narration_guard_voice_version()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF OLD.state='locked' THEN
                RAISE EXCEPTION 'locked voice version is immutable';
              END IF;
              IF OLD.state='deleted' THEN
                RAISE EXCEPTION 'deleted voice version is immutable';
              END IF;
              IF TG_OP='DELETE' THEN RETURN OLD; END IF;
              IF (to_jsonb(OLD)-ARRAY['state','quality_state','locked_actor','locked_at']) <>
                 (to_jsonb(NEW)-ARRAY['state','quality_state','locked_actor','locked_at'])
              THEN
                RAISE EXCEPTION 'voice profile version canonical identity is immutable';
              END IF;
              IF OLD.state<>NEW.state AND NOT (
                (OLD.state='draft' AND NEW.state IN
                  ('preview_ready','unavailable','deleted')) OR
                (OLD.state='preview_ready' AND NEW.state IN
                  ('locked','unavailable','deleted')) OR
                (OLD.state='unavailable' AND NEW.state='deleted')
              ) THEN
                RAISE EXCEPTION 'invalid voice profile version state transition';
              END IF;
              IF OLD.quality_state<>NEW.quality_state AND NOT (
                OLD.quality_state='pending'
                AND NEW.quality_state IN ('accepted','rejected')
              ) THEN
                RAISE EXCEPTION 'invalid voice quality state transition';
              END IF;
              IF (NEW.quality_state='accepted') <> (NEW.state='locked')
                 OR (NEW.quality_state='rejected' AND NEW.state<>'unavailable')
              THEN
                RAISE EXCEPTION 'voice quality and lifecycle state disagree';
              END IF;
              IF NEW.state='locked' THEN
                IF NEW.locked_actor IS NULL OR NEW.locked_at IS NULL THEN
                  RAISE EXCEPTION 'locked voice version requires author evidence';
                END IF;
              ELSIF NEW.locked_actor IS NOT NULL OR NEW.locked_at IS NOT NULL THEN
                RAISE EXCEPTION 'unlocked voice version cannot carry lock evidence';
              END IF;
              RETURN NEW;
            END $$;

            CREATE FUNCTION narration_guard_voice_preview_lifecycle_v1()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF TG_OP='INSERT' THEN
                IF NEW.status<>'queued' THEN
                  RAISE EXCEPTION 'voice preview must be inserted queued';
                END IF;
                RETURN NEW;
              END IF;
              IF TG_OP='DELETE' THEN
                RAISE EXCEPTION 'voice preview evidence cannot be deleted';
              END IF;
              IF OLD.status IN ('ready','failed','cancelled') THEN
                RAISE EXCEPTION 'terminal voice preview is immutable';
              END IF;
              IF (to_jsonb(OLD)-ARRAY['status','preview_text','result_asset_id',
                                      'started_at','completed_at','expires_at',
                                      'failure_code','updated_at']) <>
                 (to_jsonb(NEW)-ARRAY['status','preview_text','result_asset_id',
                                      'started_at','completed_at','expires_at',
                                      'failure_code','updated_at'])
              THEN
                RAISE EXCEPTION 'voice preview canonical request is immutable';
              END IF;
              IF NEW.updated_at<OLD.updated_at THEN
                RAISE EXCEPTION 'voice preview update time cannot move backwards';
              END IF;
              IF OLD.status=NEW.status THEN
                IF (OLD.preview_text,OLD.result_asset_id,OLD.started_at,
                    OLD.completed_at,OLD.expires_at,OLD.failure_code)
                   IS DISTINCT FROM
                   (NEW.preview_text,NEW.result_asset_id,NEW.started_at,
                    NEW.completed_at,NEW.expires_at,NEW.failure_code)
                THEN
                  RAISE EXCEPTION 'voice preview payload may only change with state';
                END IF;
                RETURN NEW;
              END IF;
              IF NOT (
                (OLD.status='queued' AND NEW.status IN
                  ('running','ready','failed','cancelled')) OR
                (OLD.status='running' AND NEW.status IN
                  ('ready','failed','cancelled'))
              ) THEN
                RAISE EXCEPTION 'invalid voice preview state transition';
              END IF;
              IF NEW.status='running' AND NEW.preview_text IS DISTINCT FROM OLD.preview_text
              THEN
                RAISE EXCEPTION 'voice preview text must remain private and stable while running';
              END IF;
              IF NEW.status IN ('ready','failed','cancelled')
                 AND NEW.preview_text IS NOT NULL
              THEN
                RAISE EXCEPTION 'terminal voice preview must clear private text';
              END IF;
              RETURN NEW;
            END $$;

            CREATE TRIGGER trg_t4_voice_preview_lifecycle
            BEFORE INSERT OR UPDATE OR DELETE ON voice_previews
            FOR EACH ROW EXECUTE FUNCTION narration_guard_voice_preview_lifecycle_v1();

            CREATE FUNCTION narration_guard_voice_preview_scope_v1()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE preview_row voice_previews%ROWTYPE;
            BEGIN
              SELECT * INTO preview_row FROM voice_previews WHERE id=NEW.id;
              IF NOT FOUND THEN RETURN NULL; END IF;
              IF NOT EXISTS (
                SELECT 1
                FROM voice_profiles p
                JOIN voice_profile_versions v
                  ON v.id=preview_row.version_id AND v.profile_id=p.id
                JOIN voice_rights_records r ON r.id=preview_row.rights_record_id
                JOIN voice_reference_asset_links l
                  ON l.voice_version_id=v.id AND l.profile_id=p.id
                JOIN media_assets reference
                  ON reference.id=preview_row.reference_asset_id
                JOIN background_jobs j ON j.id=preview_row.job_id
                LEFT JOIN media_assets result
                  ON result.id=preview_row.result_asset_id
                WHERE p.id=preview_row.profile_id
                  AND (p.owner_id,p.workspace_id,p.novel_id) IS NOT DISTINCT FROM
                      (preview_row.owner_id,preview_row.workspace_id,preview_row.novel_id)
                  AND p.status IN ('draft','active')
                  AND (v.owner_id,v.workspace_id)=
                      (preview_row.owner_id,preview_row.workspace_id)
                  AND v.state IN ('draft','preview_ready','locked')
                  AND v.rights_record_id=r.id
                  AND v.reference_asset_id=preview_row.reference_asset_id
                  AND (r.owner_id,r.workspace_id,r.novel_id) IS NOT DISTINCT FROM
                      (preview_row.owner_id,preview_row.workspace_id,preview_row.novel_id)
                  AND (r.expires_at IS NULL OR r.expires_at>CURRENT_TIMESTAMP)
                  AND (v.source_type<>'uploaded' OR r.voice_cloning IS TRUE)
                  AND EXISTS (
                    SELECT 1 FROM voice_rights_events confirmed
                    WHERE confirmed.rights_record_id=r.id
                      AND confirmed.event_type='confirmed'
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM voice_rights_events e
                    WHERE e.rights_record_id=r.id
                      AND e.event_type IN ('revoked','expired','review_blocked')
                  )
                  AND l.rights_record_id=r.id
                  AND l.reference_asset_id=reference.id
                  AND (l.owner_id,l.workspace_id,l.novel_id) IS NOT DISTINCT FROM
                      (preview_row.owner_id,preview_row.workspace_id,preview_row.novel_id)
                  AND (reference.owner_id,reference.workspace_id,reference.novel_id)
                      IS NOT DISTINCT FROM
                      (preview_row.owner_id,preview_row.workspace_id,preview_row.novel_id)
                  AND reference.kind='narration_voice_reference'
                  AND reference.asset_class='voice_reference'
                  AND reference.state='ready'
                  AND reference.retention_policy='locked_voice'
                  AND (j.owner_id,j.workspace_id,j.novel_id) IS NOT DISTINCT FROM
                      (preview_row.owner_id,preview_row.workspace_id,preview_row.novel_id)
                  AND j.job_kind='narration.voice_preview'
                  AND j.resource_class='moss-nano'
                  AND j.request_id IS NULL
                  AND (
                    (preview_row.status='queued' AND j.state IN
                      ('queued','running','retry_wait','cancel_requested')) OR
                    (preview_row.status='running' AND j.state IN
                      ('running','retry_wait','cancel_requested')) OR
                    (preview_row.status='ready' AND j.state='succeeded') OR
                    (preview_row.status='failed' AND j.state IN
                      ('failed','dead_letter')) OR
                    (preview_row.status='cancelled' AND j.state='cancelled')
                  )
                  AND (
                    (preview_row.status<>'ready' AND result.id IS NULL) OR
                    (preview_row.status='ready'
                     AND (result.owner_id,result.workspace_id,result.novel_id)
                         IS NOT DISTINCT FROM
                         (preview_row.owner_id,preview_row.workspace_id,preview_row.novel_id)
                     AND result.kind='narration_voice_preview'
                     AND result.asset_class='preview'
                     AND result.state='ready'
                     AND result.retention_policy='temporary_preview'
                     AND result.expires_at IS NOT DISTINCT FROM preview_row.expires_at
                     AND result.duration_ms>0)
                  )
              ) THEN
                RAISE EXCEPTION
                  'voice preview profile/version/rights/job/media closure mismatch';
              END IF;
              RETURN NULL;
            END $$;

            CREATE CONSTRAINT TRIGGER trg_t4_voice_preview_scope
            AFTER INSERT OR UPDATE ON voice_previews
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION narration_guard_voice_preview_scope_v1();

            CREATE FUNCTION narration_guard_voice_preview_job_closure_v1()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE job_row background_jobs%ROWTYPE;
            BEGIN
              SELECT * INTO job_row FROM background_jobs WHERE id=NEW.id;
              IF NOT FOUND OR job_row.job_kind<>'narration.voice_preview' THEN
                RETURN NULL;
              END IF;
              IF NOT EXISTS (
                SELECT 1 FROM voice_previews p
                WHERE p.job_id=job_row.id
                  AND (p.owner_id,p.workspace_id,p.novel_id) IS NOT DISTINCT FROM
                      (job_row.owner_id,job_row.workspace_id,job_row.novel_id)
                  AND (
                    (p.status='queued' AND job_row.state IN
                      ('queued','running','retry_wait','cancel_requested')) OR
                    (p.status='running' AND job_row.state IN
                      ('running','retry_wait','cancel_requested')) OR
                    (p.status='ready' AND job_row.state='succeeded') OR
                    (p.status='failed' AND job_row.state IN
                      ('failed','dead_letter')) OR
                    (p.status='cancelled' AND job_row.state='cancelled')
                  )
              ) THEN
                RAISE EXCEPTION 'voice preview job requires one coherent preview record';
              END IF;
              RETURN NULL;
            END $$;

            CREATE CONSTRAINT TRIGGER trg_t4_voice_preview_job_closure
            AFTER INSERT OR UPDATE ON background_jobs
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION narration_guard_voice_preview_job_closure_v1();

            CREATE FUNCTION narration_guard_active_job_asset_scope_v2()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE asset_row active_job_assets%ROWTYPE;
            BEGIN
              SELECT * INTO asset_row FROM active_job_assets
              WHERE job_id=NEW.job_id AND asset_id=NEW.asset_id;
              IF NOT FOUND THEN RETURN NULL; END IF;
              IF NOT EXISTS (
                SELECT 1 FROM background_jobs j
                JOIN media_assets m ON m.id=asset_row.asset_id
                WHERE j.id=asset_row.job_id
                  AND (j.owner_id,j.workspace_id,j.novel_id) IS NOT DISTINCT FROM
                      (asset_row.owner_id,asset_row.workspace_id,asset_row.novel_id)
                  AND (m.owner_id,m.workspace_id,m.novel_id) IS NOT DISTINCT FROM
                      (asset_row.owner_id,asset_row.workspace_id,asset_row.novel_id)
                  AND (asset_row.novel_id IS NOT NULL
                       OR j.job_kind='narration.voice_preview')
              ) THEN
                RAISE EXCEPTION 'active job asset exact-null scope mismatch';
              END IF;
              RETURN NULL;
            END $$;

            CREATE CONSTRAINT TRIGGER trg_t4_active_job_asset_scope_v2
            AFTER INSERT OR UPDATE ON active_job_assets
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION narration_guard_active_job_asset_scope_v2();

            CREATE OR REPLACE FUNCTION narration_media_has_live_reference(p_asset_id uuid)
            RETURNS boolean LANGUAGE sql STABLE AS $$
              SELECT
                EXISTS (SELECT 1 FROM novels n WHERE n.cover_asset_id=p_asset_id)
                OR EXISTS (SELECT 1 FROM narration_render_assets r WHERE r.asset_id=p_asset_id)
                OR EXISTS (SELECT 1 FROM narration_exports e WHERE e.asset_id=p_asset_id)
                OR EXISTS (
                  SELECT 1 FROM voice_profile_versions v
                  WHERE v.reference_asset_id=p_asset_id OR v.preview_asset_id=p_asset_id
                )
                OR EXISTS (
                  SELECT 1 FROM voice_reference_asset_links l
                  WHERE l.source_asset_id=p_asset_id OR l.reference_asset_id=p_asset_id
                )
                OR EXISTS (
                  SELECT 1 FROM voice_previews p
                  WHERE (p.reference_asset_id=p_asset_id
                         AND p.status IN ('queued','running'))
                     OR (p.result_asset_id=p_asset_id AND p.status='ready'
                         AND p.expires_at>CURRENT_TIMESTAMP)
                )
                OR EXISTS (
                  SELECT 1 FROM active_job_assets a
                  WHERE a.asset_id=p_asset_id AND a.released_at IS NULL
                )
                OR EXISTS (
                  SELECT 1 FROM narration_manifest_segments ms
                  JOIN narration_render_assets ra ON ra.render_id=ms.render_id
                  WHERE ra.asset_id=p_asset_id
                );
            $$;
            """
        )
    )


def upgrade() -> None:
    _preflight()
    _extend_active_job_assets()
    _create_product_tables()
    _create_product_guards()


def _restore_0020_functions() -> None:
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION narration_media_has_live_reference(p_asset_id uuid)
            RETURNS boolean LANGUAGE sql STABLE AS $$
              SELECT
                EXISTS (SELECT 1 FROM novels n WHERE n.cover_asset_id=p_asset_id)
                OR EXISTS (SELECT 1 FROM narration_render_assets r WHERE r.asset_id=p_asset_id)
                OR EXISTS (SELECT 1 FROM narration_exports e WHERE e.asset_id=p_asset_id)
                OR EXISTS (
                  SELECT 1 FROM voice_profile_versions v
                  WHERE v.reference_asset_id=p_asset_id OR v.preview_asset_id=p_asset_id
                )
                OR EXISTS (
                  SELECT 1 FROM active_job_assets a
                  WHERE a.asset_id=p_asset_id AND a.released_at IS NULL
                )
                OR EXISTS (
                  SELECT 1 FROM narration_manifest_segments ms
                  JOIN narration_render_assets ra ON ra.render_id=ms.render_id
                  WHERE ra.asset_id=p_asset_id
                );
            $$;

            CREATE OR REPLACE FUNCTION narration_guard_voice_version()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF OLD.state='locked' THEN
                RAISE EXCEPTION 'locked voice version is immutable';
              END IF;
              IF OLD.state='deleted' THEN
                RAISE EXCEPTION 'deleted voice version is immutable';
              END IF;
              IF TG_OP='DELETE' THEN RETURN OLD; END IF;
              IF (to_jsonb(OLD)-ARRAY['state','quality_state','locked_actor','locked_at']) <>
                 (to_jsonb(NEW)-ARRAY['state','quality_state','locked_actor','locked_at'])
              THEN
                RAISE EXCEPTION 'voice profile version canonical identity is immutable';
              END IF;
              RETURN NEW;
            END $$;
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM voice_action_receipts)
                 OR EXISTS (SELECT 1 FROM voice_reference_asset_links)
                 OR EXISTS (SELECT 1 FROM voice_previews)
                 OR EXISTS (SELECT 1 FROM active_job_assets WHERE novel_id IS NULL)
              THEN
                RAISE EXCEPTION
                  'T4 voice downgrade refused: durable voice/library evidence exists; fix forward';
              END IF;
            END $$;
            """
        )
    )

    for trigger, table in (
        ("trg_t4_active_job_asset_scope_v2", "active_job_assets"),
        ("trg_t4_voice_preview_job_closure", "background_jobs"),
        ("trg_t4_voice_preview_scope", "voice_previews"),
        ("trg_t4_voice_preview_lifecycle", "voice_previews"),
        ("trg_t4_voice_reference_link_scope", "voice_reference_asset_links"),
        (
            "trg_t4_voice_reference_link_immutable",
            "voice_reference_asset_links",
        ),
        ("trg_t4_voice_action_receipt_guard", "voice_action_receipts"),
    ):
        op.execute(sa.text(f"DROP TRIGGER {trigger} ON {table}"))

    _restore_0020_functions()

    for function in (
        "narration_guard_active_job_asset_scope_v2()",
        "narration_guard_voice_preview_job_closure_v1()",
        "narration_guard_voice_preview_scope_v1()",
        "narration_guard_voice_preview_lifecycle_v1()",
        "narration_guard_voice_reference_link_scope_v1()",
        "narration_reject_voice_reference_link_mutation_v1()",
        "narration_guard_voice_action_receipt_v1()",
    ):
        op.execute(sa.text(f"DROP FUNCTION {function}"))

    op.drop_table("voice_previews")
    op.drop_table("voice_reference_asset_links")
    op.drop_table("voice_action_receipts")

    op.drop_constraint(
        "fk_active_job_asset_job_scope", "active_job_assets", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_active_job_asset_media_scope", "active_job_assets", type_="foreignkey"
    )
    op.alter_column(
        "active_job_assets",
        "novel_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.create_foreign_key(
        "fk_active_job_asset_job_scope",
        "active_job_assets",
        "background_jobs",
        ["job_id", "owner_id", "workspace_id", "novel_id"],
        ["id", "owner_id", "workspace_id", "novel_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_active_job_asset_media_scope",
        "active_job_assets",
        "media_assets",
        ["asset_id", "owner_id", "workspace_id", "novel_id"],
        ["id", "owner_id", "workspace_id", "novel_id"],
        ondelete="RESTRICT",
    )
