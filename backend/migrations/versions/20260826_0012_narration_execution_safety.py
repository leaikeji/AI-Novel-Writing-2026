"""Close narration execution, source, and media publication races.

Revision ID: 20260826_0012
Revises: 20260826_0011

This migration is deliberately PostgreSQL-only and performs no filesystem,
network, model, or media I/O.  T1 was not yet product-visible when this schema
was introduced, so an unfinished pre-0012 attempt fails preflight rather than
receiving an invented resource or executor fence.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260826_0012"
down_revision = "20260826_0011"
branch_labels = None
depends_on = None


ACTIVE_EPOCH_ID = "543b85c2-4831-5c0b-80da-f4c3ba9a40e9"
MIGRATION_ACTOR = "migration:20260826_0012"


def _preflight() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM background_job_attempts) THEN
                RAISE EXCEPTION
                  'T1 execution-safety preflight: drain/reconcile pre-0012 attempts; resource and executor fences cannot be invented';
              END IF;
              IF EXISTS (
                SELECT 1 FROM background_jobs
                WHERE state<>'queued' OR attempt_count<>0
              ) THEN
                RAISE EXCEPTION
                  'T1 execution-safety preflight: pre-0012 jobs must be unclaimed queued rows';
              END IF;
              IF EXISTS (
                SELECT 1 FROM background_jobs
                WHERE resource_class NOT IN
                  ('moss-nano','voice-generator','cpu-transcode','cpu-analysis')
              ) THEN
                RAISE EXCEPTION
                  'T1 execution-safety preflight: unregistered background resource class';
              END IF;
              IF EXISTS (
                SELECT 1 FROM background_jobs
                WHERE job_kind LIKE 'narration.%' AND
                  (job_kind, resource_class) NOT IN (
                    ('narration.segment_render','moss-nano'),
                    ('narration.export','cpu-transcode'),
                    ('narration.voice_generate','voice-generator'),
                    ('narration.voice_preview','moss-nano'),
                    ('narration.analyze','cpu-analysis')
                  )
              ) THEN
                RAISE EXCEPTION
                  'T1 execution-safety preflight: narration job kind/resource mapping is not registered';
              END IF;
              IF EXISTS (SELECT 1 FROM background_resource_locks) THEN
                RAISE EXCEPTION
                  'T1 execution-safety preflight: release pre-registry resource rows before upgrade';
              END IF;
              IF EXISTS (
                SELECT 1 FROM media_assets
                WHERE state='ready' AND asset_class IS NOT NULL AND
                  (byte_size IS NULL OR mime_type IS NULL OR verified_at IS NULL
                   OR checksum_algorithm<>'sha256' OR content_hash !~ '^[0-9a-f]{64}$')
              ) THEN
                RAISE EXCEPTION
                  'T1 execution-safety preflight: ready narration media lacks canonical HTTP identity';
              END IF;
              IF EXISTS (
                SELECT 1 FROM media_assets
                WHERE asset_class IS NOT NULL AND storage_backend='local' AND NOT (
                  content_hash ~ '^[0-9a-f]{64}$' AND storage_path ~
                  ('^assets/' || substr(content_hash,1,2) || '/' || content_hash ||
                   '\\.(aac|flac|m4a|mp3|ogg|opus|wav)$')
                )
              ) THEN
                RAISE EXCEPTION
                  'T1 execution-safety preflight: narration media path is not canonical and content-addressed';
              END IF;
              IF EXISTS (
                SELECT 1 FROM media_gc_deletion_plans
                WHERE reason_code NOT IN (
                  'staging_orphan','unreferenced_derivative_after_grace',
                  'recover_interrupted_delete'
                )
              ) THEN
                RAISE EXCEPTION
                  'T1 execution-safety preflight: unknown media GC reason';
              END IF;
              IF EXISTS (
                SELECT 1 FROM media_assets m
                WHERE m.state='deleting' AND NOT EXISTS (
                  SELECT 1 FROM media_gc_deletion_plans p
                  WHERE p.asset_id=m.id
                    AND (p.owner_id,p.workspace_id,p.novel_id,p.storage_backend,
                         p.storage_path,p.content_hash,p.byte_size,p.generation)
                        IS NOT DISTINCT FROM
                        (m.owner_id,m.workspace_id,m.novel_id,m.storage_backend,
                         m.storage_path,m.content_hash,m.byte_size,m.gc_generation)
                )
              ) THEN
                RAISE EXCEPTION
                  'T1 execution-safety preflight: deleting media lacks a durable matching plan';
              END IF;
              IF EXISTS (
                SELECT 1 FROM narration_segment_renders r
                WHERE r.source_job_id IS NULL OR NOT EXISTS (
                  SELECT 1 FROM background_jobs j
                  WHERE j.id=r.source_job_id AND j.owner_id=r.owner_id
                    AND j.workspace_id=r.workspace_id AND j.novel_id=r.novel_id
                    AND j.request_id=r.request_id
                )
              ) THEN
                RAISE EXCEPTION
                  'T1 execution-safety preflight: render lacks its scoped source job';
              END IF;
              IF EXISTS (SELECT 1 FROM narration_segment_renders WHERE state='ready') THEN
                RAISE EXCEPTION
                  'T1 execution-safety preflight: pre-0012 ready render cannot prove executor/resource publication closure';
              END IF;
              IF EXISTS (
                SELECT 1 FROM narration_render_assets
                WHERE actual_sha256 !~ '^[0-9a-f]{64}$'
              ) THEN
                RAISE EXCEPTION
                  'T1 execution-safety preflight: render asset digest is not SHA-256';
              END IF;
              IF EXISTS (
                SELECT original_asset_id FROM asset_tombstones
                GROUP BY original_asset_id HAVING count(*)>1
              ) THEN
                RAISE EXCEPTION
                  'T1 execution-safety preflight: one media asset has multiple tombstones';
              END IF;
            END $$;
            """
        )
    )


def _create_resource_and_epoch_registry() -> None:
    op.create_table(
        "background_resource_class_policies",
        sa.Column("resource_class", sa.String(80), primary_key=True),
        sa.Column("requires_publish_fence", sa.Boolean(), nullable=False),
        sa.Column("exact_resource_key", sa.String(160), unique=True),
        sa.Column("max_concurrency", sa.Integer(), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("created_actor", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "max_concurrency > 0", name="ck_background_resource_policy_slots"
        ),
        sa.CheckConstraint(
            "version > 0", name="ck_background_resource_policy_version"
        ),
        sa.CheckConstraint(
            "requires_publish_fence IS FALSE OR exact_resource_key IS NOT NULL",
            name="ck_background_resource_policy_fence_key",
        ),
    )
    op.create_table(
        "background_resource_class_slots",
        sa.Column("resource_class", sa.String(80), nullable=False),
        sa.Column("slot_number", sa.Integer(), nullable=False),
        sa.Column("resource_key", sa.String(160), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("resource_class", "slot_number"),
        sa.ForeignKeyConstraint(
            ["resource_class"],
            ["background_resource_class_policies.resource_class"],
            name="fk_background_resource_slot_policy",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "resource_key", name="uq_background_resource_slot_key"
        ),
        sa.CheckConstraint(
            "slot_number >= 0", name="ck_background_resource_slot_number"
        ),
    )
    op.create_table(
        "background_job_kind_policies",
        sa.Column("job_kind", sa.String(80), primary_key=True),
        sa.Column("resource_class", sa.String(80), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("created_actor", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["resource_class"],
            ["background_resource_class_policies.resource_class"],
            name="fk_background_job_kind_policy_resource",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "version > 0", name="ck_background_job_kind_policy_version"
        ),
    )
    op.create_table(
        "background_executor_epochs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("executor_key", sa.String(80), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_actor", sa.String(120), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_actor", sa.String(120)),
        sa.Column("revoked_reason_code", sa.String(96)),
        sa.UniqueConstraint(
            "executor_key", "generation",
            name="uq_background_executor_epoch_generation",
        ),
        sa.CheckConstraint(
            "generation > 0", name="ck_background_executor_epoch_generation"
        ),
        sa.CheckConstraint(
            "state IN ('active','revoked')",
            name="ck_background_executor_epoch_state",
        ),
        sa.CheckConstraint(
            "(state='active' AND revoked_at IS NULL AND revoked_actor IS NULL "
            "AND revoked_reason_code IS NULL) OR "
            "(state='revoked' AND revoked_at IS NOT NULL AND revoked_actor IS NOT NULL "
            "AND revoked_reason_code IS NOT NULL)",
            name="ck_background_executor_epoch_lifecycle",
        ),
    )
    op.create_index(
        "uq_background_executor_epoch_active",
        "background_executor_epochs",
        ["executor_key"],
        unique=True,
        postgresql_where=sa.text("state='active'"),
    )

    op.execute(
        sa.text(
            f"""
            INSERT INTO background_resource_class_policies
              (resource_class,requires_publish_fence,exact_resource_key,
               max_concurrency,version,created_actor,created_at)
            VALUES
              ('moss-nano',true,'moss-nano:inference',1,1,'{MIGRATION_ACTOR}',clock_timestamp()),
              ('voice-generator',true,'voice-generator:generation',1,1,'{MIGRATION_ACTOR}',clock_timestamp()),
              ('cpu-transcode',false,NULL,2,1,'{MIGRATION_ACTOR}',clock_timestamp()),
              ('cpu-analysis',false,NULL,2,1,'{MIGRATION_ACTOR}',clock_timestamp());

            INSERT INTO background_resource_class_slots
              (resource_class,slot_number,resource_key,enabled,created_at)
            VALUES
              ('moss-nano',0,'moss-nano:inference',true,clock_timestamp()),
              ('voice-generator',0,'voice-generator:generation',true,clock_timestamp()),
              ('cpu-transcode',0,'cpu-transcode:0',true,clock_timestamp()),
              ('cpu-transcode',1,'cpu-transcode:1',true,clock_timestamp()),
              ('cpu-analysis',0,'cpu-analysis:0',true,clock_timestamp()),
              ('cpu-analysis',1,'cpu-analysis:1',true,clock_timestamp());

            INSERT INTO background_job_kind_policies
              (job_kind,resource_class,version,created_actor,created_at)
            VALUES
              ('narration.segment_render','moss-nano',1,'{MIGRATION_ACTOR}',clock_timestamp()),
              ('narration.export','cpu-transcode',1,'{MIGRATION_ACTOR}',clock_timestamp()),
              ('narration.voice_generate','voice-generator',1,'{MIGRATION_ACTOR}',clock_timestamp()),
              ('narration.voice_preview','moss-nano',1,'{MIGRATION_ACTOR}',clock_timestamp()),
              ('narration.analyze','cpu-analysis',1,'{MIGRATION_ACTOR}',clock_timestamp());

            INSERT INTO background_executor_epochs
              (id,executor_key,generation,state,activated_at,activated_actor)
            VALUES
              ('{ACTIVE_EPOCH_ID}'::uuid,'narration-worker',1,'active',
               clock_timestamp(),'{MIGRATION_ACTOR}');
            """
        )
    )


def _extend_jobs_and_attempts() -> None:
    op.create_unique_constraint(
        "uq_background_job_command_scope",
        "background_jobs",
        ["id", "owner_id", "workspace_id"],
    )
    op.create_unique_constraint(
        "uq_background_job_publication_scope",
        "background_jobs",
        ["id", "owner_id", "workspace_id", "novel_id", "request_id"],
    )
    op.create_foreign_key(
        "fk_background_job_resource_policy",
        "background_jobs",
        "background_resource_class_policies",
        ["resource_class"],
        ["resource_class"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "narration_segment_renders_source_job_id_fkey",
        "narration_segment_renders",
        type_="foreignkey",
    )
    op.alter_column(
        "narration_segment_renders",
        "source_job_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.create_foreign_key(
        "fk_narration_segment_render_source_job_scope",
        "narration_segment_renders",
        "background_jobs",
        ["source_job_id", "owner_id", "workspace_id", "novel_id", "request_id"],
        ["id", "owner_id", "workspace_id", "novel_id", "request_id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_narration_render_asset_sha256",
        "narration_render_assets",
        "actual_sha256 ~ '^[0-9a-f]{64}$'",
    )
    op.create_check_constraint(
        "ck_model_run_result_classification",
        "model_run_records",
        "result_classification IN "
        "('success','retryable_failure','non_retryable_failure','cancelled','security_failure')",
    )
    op.create_check_constraint(
        "ck_model_run_output_digest_sha256",
        "model_run_records",
        "output_digest IS NULL OR output_digest ~ '^[0-9a-f]{64}$'",
    )
    op.create_check_constraint(
        "ck_model_run_success_shape",
        "model_run_records",
        "result_classification <> 'success' OR "
        "(actual_model_id IS NOT NULL AND model_fingerprint ~ '^[0-9a-f]{64}$' "
        "AND output_digest IS NOT NULL AND duration_ms IS NOT NULL AND duration_ms >= 0)",
    )
    op.create_unique_constraint(
        "uq_asset_tombstone_original_asset",
        "asset_tombstones",
        ["original_asset_id"],
    )
    op.create_foreign_key(
        "fk_background_resource_lock_slot",
        "background_resource_locks",
        "background_resource_class_slots",
        ["resource_key"],
        ["resource_key"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "background_manual_retry_commands",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("actor", sa.String(120), nullable=False),
        sa.Column("reason", sa.String(240), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("claimed_attempt_id", postgresql.UUID(as_uuid=True)),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_actor", sa.String(120)),
        sa.Column("cancelled_reason_code", sa.String(96)),
        sa.ForeignKeyConstraint(
            ["job_id", "owner_id", "workspace_id"],
            ["background_jobs.id", "background_jobs.owner_id", "background_jobs.workspace_id"],
            name="fk_background_manual_retry_job_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["claimed_attempt_id"],
            ["background_job_attempts.id"],
            name="fk_background_manual_retry_claimed_attempt",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.UniqueConstraint(
            "owner_id", "workspace_id", "idempotency_key",
            name="uq_background_manual_retry_idempotency",
        ),
        sa.UniqueConstraint(
            "claimed_attempt_id", name="uq_background_manual_retry_claimed_attempt"
        ),
        sa.CheckConstraint(
            "state IN ('pending','claimed','cancelled')",
            name="ck_background_manual_retry_state",
        ),
        sa.CheckConstraint(
            "(state='pending' AND claimed_attempt_id IS NULL AND claimed_at IS NULL "
            "AND cancelled_at IS NULL AND cancelled_actor IS NULL "
            "AND cancelled_reason_code IS NULL) OR "
            "(state='claimed' AND claimed_attempt_id IS NOT NULL AND claimed_at IS NOT NULL "
            "AND cancelled_at IS NULL AND cancelled_actor IS NULL "
            "AND cancelled_reason_code IS NULL) OR "
            "(state='cancelled' AND claimed_attempt_id IS NULL AND claimed_at IS NULL "
            "AND cancelled_at IS NOT NULL AND cancelled_actor IS NOT NULL "
            "AND cancelled_reason_code IS NOT NULL)",
            name="ck_background_manual_retry_lifecycle",
        ),
        sa.CheckConstraint(
            "trim(idempotency_key) <> '' AND trim(actor) <> '' AND trim(reason) <> ''",
            name="ck_background_manual_retry_audit_text",
        ),
    )
    op.create_index(
        "uq_background_manual_retry_pending_job",
        "background_manual_retry_commands",
        ["job_id"],
        unique=True,
        postgresql_where=sa.text("state='pending'"),
    )

    op.add_column(
        "background_job_attempts",
        sa.Column("manual_retry_command_id", postgresql.UUID(as_uuid=True)),
    )
    op.add_column(
        "background_job_attempts",
        sa.Column(
            "executor_epoch_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text(f"'{ACTIVE_EPOCH_ID}'::uuid"),
        ),
    )
    op.add_column(
        "background_job_attempts",
        sa.Column("resource_key", sa.String(160), nullable=False),
    )
    op.add_column(
        "background_job_attempts",
        sa.Column("resource_lease_token", postgresql.UUID(as_uuid=True), nullable=False),
    )
    op.add_column(
        "background_job_attempts",
        sa.Column("resource_lease_generation", sa.BigInteger(), nullable=False),
    )
    op.alter_column(
        "background_job_attempts",
        "executor_epoch_id",
        existing_type=postgresql.UUID(as_uuid=True),
        server_default=None,
    )
    op.create_foreign_key(
        "fk_background_job_attempt_manual_retry_command",
        "background_job_attempts",
        "background_manual_retry_commands",
        ["manual_retry_command_id"],
        ["id"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_background_job_attempt_executor_epoch",
        "background_job_attempts",
        "background_executor_epochs",
        ["executor_epoch_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_background_job_attempt_resource_slot",
        "background_job_attempts",
        "background_resource_class_slots",
        ["resource_key"],
        ["resource_key"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "ck_background_job_attempt_manual_shape",
        "background_job_attempts",
        type_="check",
    )
    op.create_check_constraint(
        "ck_background_job_attempt_manual_shape",
        "background_job_attempts",
        "(retry_kind='manual' AND manual_retry_command_id IS NOT NULL "
        "AND manual_actor IS NOT NULL AND manual_reason IS NOT NULL) OR "
        "(retry_kind IN ('initial','automatic') AND manual_retry_command_id IS NULL "
        "AND manual_actor IS NULL AND manual_reason IS NULL)",
    )
    op.create_check_constraint(
        "ck_background_job_attempt_resource_generation",
        "background_job_attempts",
        "resource_lease_generation > 0",
    )
    op.create_check_constraint(
        "ck_background_job_attempt_completion_shape",
        "background_job_attempts",
        "(completed_at IS NULL AND error_classification IS NULL "
        "AND error_code IS NULL AND actual_result_digest IS NULL) OR "
        "(completed_at IS NOT NULL AND ((actual_result_digest ~ '^[0-9a-f]{64}$' "
        "AND error_classification IS NULL AND error_code IS NULL) OR "
        "(actual_result_digest IS NULL AND error_classification IS NOT NULL "
        "AND error_code IS NOT NULL)))",
    )
    op.create_unique_constraint(
        "uq_background_job_attempt_manual_retry_command",
        "background_job_attempts",
        ["manual_retry_command_id"],
    )
    op.create_unique_constraint(
        "uq_background_job_attempt_resource_generation",
        "background_job_attempts",
        ["resource_key", "resource_lease_generation"],
    )
    op.create_unique_constraint(
        "uq_model_run_attempt",
        "model_run_records",
        ["attempt_id"],
    )


def _harden_request_sources_and_media() -> None:
    op.drop_constraint(
        "ck_narration_request_source_shape", "narration_requests", type_="check"
    )
    op.create_check_constraint(
        "ck_narration_request_source_shape",
        "narration_requests",
        "(intent IN ('create','update') AND document_id IS NOT NULL "
        "AND source_revision_id IS NOT NULL AND source_content_hash IS NOT NULL) OR "
        "(intent='analyze_only' AND ((document_id IS NOT NULL "
        "AND source_revision_id IS NOT NULL AND source_content_hash IS NOT NULL) OR "
        "(document_id IS NULL AND source_revision_id IS NULL AND source_content_hash IS NULL))) OR "
        "(intent='batch' AND document_id IS NULL AND source_revision_id IS NULL "
        "AND source_content_hash IS NULL)",
    )
    op.create_check_constraint(
        "ck_narration_request_source_position",
        "narration_request_sources",
        "position >= 0",
    )
    op.drop_constraint(
        "fk_media_gc_plan_asset_scope",
        "media_gc_deletion_plans",
        type_="foreignkey",
    )
    op.alter_column(
        "media_gc_deletion_plans",
        "novel_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.create_foreign_key(
        "fk_media_gc_plan_asset_local_scope",
        "media_gc_deletion_plans",
        "media_assets",
        ["asset_id", "owner_id", "workspace_id"],
        ["id", "owner_id", "workspace_id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_media_asset_ready_narration_identity",
        "media_assets",
        "state <> 'ready' OR asset_class IS NULL OR "
        "(byte_size IS NOT NULL AND mime_type IS NOT NULL "
        "AND checksum_algorithm='sha256' AND content_hash ~ '^[0-9a-f]{64}$' "
        "AND verified_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_media_asset_narration_canonical_path",
        "media_assets",
        "asset_class IS NULL OR storage_backend <> 'local' OR "
        "(content_hash ~ '^[0-9a-f]{64}$' AND storage_path ~ "
        "('^assets/' || substr(content_hash,1,2) || '/' || content_hash || "
        "'\\.(aac|flac|m4a|mp3|ogg|opus|wav)$'))",
    )
    op.create_check_constraint(
        "ck_media_asset_narration_mime_path",
        "media_assets",
        "state <> 'ready' OR asset_class IS NULL OR storage_backend <> 'local' OR "
        "(CASE substring(storage_path from '\\.[^.]+$') "
        "WHEN '.aac' THEN mime_type='audio/aac' "
        "WHEN '.flac' THEN mime_type='audio/flac' "
        "WHEN '.m4a' THEN mime_type='audio/mp4' "
        "WHEN '.mp3' THEN mime_type='audio/mpeg' "
        "WHEN '.ogg' THEN mime_type='audio/ogg' "
        "WHEN '.opus' THEN mime_type='audio/ogg' "
        "WHEN '.wav' THEN mime_type='audio/wav' ELSE FALSE END)",
    )
    op.create_check_constraint(
        "ck_media_gc_plan_reason_code",
        "media_gc_deletion_plans",
        "reason_code IN ('staging_orphan','unreferenced_derivative_after_grace',"
        "'recover_interrupted_delete')",
    )

    op.execute(
        sa.text(
            """
            DROP TRIGGER trg_narration_request_sources_scope ON narration_request_sources;

            CREATE FUNCTION narration_validate_request_source_v2()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE parent narration_requests%ROWTYPE;
            BEGIN
              SELECT * INTO parent FROM narration_requests r
              WHERE r.id=NEW.request_id FOR UPDATE;
              IF NOT FOUND OR parent.novel_id<>NEW.novel_id
                 OR parent.state<>'created' OR NOT (
                   parent.intent='batch' OR
                   (parent.intent='analyze_only' AND parent.document_id IS NULL
                    AND parent.source_revision_id IS NULL
                    AND parent.source_content_hash IS NULL)
                 )
              THEN
                RAISE EXCEPTION
                  'request source requires a created batch or multi-source analyze-only request in the same novel';
              END IF;
              RETURN NEW;
            END $$;

            CREATE TRIGGER trg_narration_request_sources_scope
            BEFORE INSERT OR UPDATE ON narration_request_sources FOR EACH ROW
            EXECUTE FUNCTION narration_validate_request_source_v2();

            CREATE FUNCTION narration_guard_request_source_closure_v2()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE request_id_value uuid; parent narration_requests%ROWTYPE;
                    source_count integer; min_position integer; max_position integer;
            BEGIN
              IF TG_TABLE_NAME='narration_requests' THEN
                request_id_value := (to_jsonb(NEW)->>'id')::uuid;
              ELSE
                request_id_value := (to_jsonb(NEW)->>'request_id')::uuid;
              END IF;
              SELECT * INTO parent FROM narration_requests
              WHERE id=request_id_value;
              IF NOT FOUND THEN RETURN NEW; END IF;
              SELECT count(*),min(position),max(position)
                INTO source_count,min_position,max_position
              FROM narration_request_sources WHERE request_id=request_id_value;
              IF source_count>0 AND
                 (min_position<>0 OR max_position<>source_count-1)
              THEN
                RAISE EXCEPTION 'request source positions must be contiguous from zero';
              END IF;
              IF parent.document_id IS NOT NULL AND source_count<>0 THEN
                RAISE EXCEPTION 'direct-source request cannot also own source rows';
              END IF;
              IF parent.document_id IS NULL AND parent.state<>'created'
                 AND source_count=0
              THEN
                RAISE EXCEPTION 'multi-source request requires at least one frozen source';
              END IF;
              RETURN NEW;
            END $$;
            CREATE CONSTRAINT TRIGGER trg_t1_request_source_closure_parent
            AFTER INSERT OR UPDATE ON narration_requests
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION narration_guard_request_source_closure_v2();
            CREATE CONSTRAINT TRIGGER trg_t1_request_source_closure_child
            AFTER INSERT OR UPDATE ON narration_request_sources
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION narration_guard_request_source_closure_v2();

            CREATE OR REPLACE FUNCTION narration_guard_request()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF TG_OP='INSERT' THEN
                IF NEW.state<>'created' THEN
                  RAISE EXCEPTION 'narration request must be inserted in created state';
                END IF;
                RETURN NEW;
              END IF;
              IF (to_jsonb(OLD)-ARRAY['state','version','allows_edition','allows_render',
                                      'cancel_requested_at','cancel_actor','cancel_reason_code',
                                      'failure_code','updated_at','completed_at']) <>
                 (to_jsonb(NEW)-ARRAY['state','version','allows_edition','allows_render',
                                      'cancel_requested_at','cancel_actor','cancel_reason_code',
                                      'failure_code','updated_at','completed_at'])
              THEN RAISE EXCEPTION 'narration request canonical input is immutable'; END IF;
              IF OLD.state='created' AND NEW.state='analyzing'
                 AND OLD.intent IN ('batch','analyze_only')
                 AND OLD.document_id IS NULL
                 AND NOT (
                   SELECT count(*)>0 AND min(position)=0
                          AND max(position)=count(*)-1
                   FROM narration_request_sources rs WHERE rs.request_id=OLD.id
                 )
              THEN
                RAISE EXCEPTION 'multi-source request requires at least one frozen source before analysis';
              END IF;
              IF OLD.state<>NEW.state AND NOT (
                (OLD.state='created' AND NEW.state IN ('analyzing','cancel_requested')) OR
                (OLD.state='analyzing' AND NEW.state IN
                  ('analyzed','review_required','queued','cancel_requested','failed')) OR
                (OLD.state='review_required' AND NEW.state IN
                  ('analyzing','queued','cancel_requested','failed')) OR
                (OLD.state='queued' AND NEW.state IN
                  ('rendering','cancel_requested','failed')) OR
                (OLD.state='rendering' AND NEW.state IN
                  ('partial_ready','ready','cancel_requested','failed')) OR
                (OLD.state='partial_ready' AND NEW.state IN
                  ('ready','cancel_requested','failed')) OR
                (OLD.state='cancel_requested' AND NEW.state='cancelled'))
              THEN RAISE EXCEPTION 'invalid narration request state transition'; END IF;
              RETURN NEW;
            END $$;

            CREATE OR REPLACE FUNCTION narration_guard_media_gc_plan()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE media_row media_assets%ROWTYPE;
            BEGIN
              IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'media GC deletion plan is immutable';
              END IF;
              SELECT * INTO media_row FROM media_assets m
              WHERE m.id=NEW.asset_id FOR UPDATE;
              IF NOT FOUND OR media_row.state NOT IN ('ready','staging') THEN
                RAISE EXCEPTION 'media GC plan requires a locked ready or staging asset';
              END IF;
              IF NEW.created_at<clock_timestamp()-interval '5 seconds'
                 OR NEW.created_at>clock_timestamp()+interval '1 second'
              THEN
                RAISE EXCEPTION 'media GC plan requires the authoritative database clock';
              END IF;
              IF media_row.storage_backend<>'local'
                 OR media_row.asset_class IN ('source','voice_reference')
                 OR media_row.retention_policy IN
                    ('source','cover','uploaded_original','locked_voice','legal_hold','keep')
                 OR (media_row.expires_at IS NOT NULL
                     AND media_row.expires_at>clock_timestamp())
              THEN
                RAISE EXCEPTION 'media GC plan targets protected or unexpired media';
              END IF;
              IF media_row.content_hash !~ '^[0-9a-f]{64}$'
                 OR media_row.storage_path !~
                    ('^assets/' || substr(media_row.content_hash,1,2) || '/' ||
                     media_row.content_hash ||
                     '\\.(aac|flac|m4a|mp3|ogg|opus|wav)$')
                 OR NOT (CASE substring(media_row.storage_path from '\\.[^.]+$')
                   WHEN '.aac' THEN media_row.mime_type='audio/aac'
                   WHEN '.flac' THEN media_row.mime_type='audio/flac'
                   WHEN '.m4a' THEN media_row.mime_type='audio/mp4'
                   WHEN '.mp3' THEN media_row.mime_type='audio/mpeg'
                   WHEN '.ogg' THEN media_row.mime_type='audio/ogg'
                   WHEN '.opus' THEN media_row.mime_type='audio/ogg'
                   WHEN '.wav' THEN media_row.mime_type='audio/wav'
                   ELSE FALSE END)
              THEN
                RAISE EXCEPTION 'media GC plan requires a canonical narration audio path and MIME';
              END IF;
              IF media_row.state='staging' AND NOT (
                   NEW.reason_code='staging_orphan'
                   AND media_row.created_at<=clock_timestamp()-interval '24 hours'
                 )
              THEN
                RAISE EXCEPTION 'staging GC plan requires the server-side orphan grace';
              END IF;
              IF media_row.state='ready' AND NOT (
                   NEW.reason_code='unreferenced_derivative_after_grace'
                   AND media_row.asset_class IN
                     ('preview','segment_master','segment_playback','export')
                   AND media_row.gc_marked_at IS NOT NULL
                   AND media_row.gc_marked_at<=clock_timestamp()-interval '7 days'
                 )
              THEN
                RAISE EXCEPTION 'ready GC plan requires a marked derivative after grace';
              END IF;
              IF media_row.state='ready' AND NEW.file_present IS NOT TRUE THEN
                RAISE EXCEPTION 'ready media GC plan requires a present inode';
              END IF;
              IF (
                media_row.owner_id, media_row.workspace_id, media_row.novel_id,
                media_row.storage_backend, media_row.storage_path,
                media_row.content_hash, media_row.byte_size, media_row.gc_generation
              ) IS DISTINCT FROM (
                NEW.owner_id, NEW.workspace_id, NEW.novel_id,
                NEW.storage_backend, NEW.storage_path,
                NEW.content_hash, NEW.byte_size, NEW.generation
              ) THEN
                RAISE EXCEPTION 'media GC plan does not match canonical asset identity';
              END IF;
              IF narration_media_has_live_reference(NEW.asset_id) THEN
                RAISE EXCEPTION 'referenced media cannot enter a GC deletion plan';
              END IF;
              IF (SELECT count(*) FROM media_assets m
                  WHERE m.storage_backend=NEW.storage_backend
                    AND m.storage_path=NEW.storage_path) <> 1
              THEN
                RAISE EXCEPTION 'media GC plan requires exactly one physical blob owner';
              END IF;
              RETURN NEW;
            END $$;

            CREATE FUNCTION narration_guard_media_gc_plan_reachability()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF NOT EXISTS (
                SELECT 1 FROM media_assets m
                WHERE m.id=NEW.asset_id AND m.state IN ('deleting','quarantined')
                  AND (m.owner_id,m.workspace_id,m.novel_id,m.storage_backend,
                       m.storage_path,m.content_hash,m.byte_size,m.gc_generation)
                      IS NOT DISTINCT FROM
                      (NEW.owner_id,NEW.workspace_id,NEW.novel_id,NEW.storage_backend,
                       NEW.storage_path,NEW.content_hash,NEW.byte_size,NEW.generation)
              ) THEN
                RAISE EXCEPTION
                  'media GC plan must close over the same deleting asset at commit';
              END IF;
              RETURN NEW;
            END $$;

            CREATE CONSTRAINT TRIGGER trg_t1_media_gc_plan_reachability
            AFTER INSERT OR UPDATE ON media_gc_deletion_plans
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION narration_guard_media_gc_plan_reachability();

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
              THEN
                RAISE EXCEPTION 'published media physical identity is immutable';
              END IF;
              IF OLD.gc_generation <> NEW.gc_generation AND
                 NOT (OLD.state='ready' AND NEW.gc_generation=OLD.gc_generation+1
                      AND NEW.gc_marked_at IS NOT NULL)
              THEN
                RAISE EXCEPTION 'media GC generation may only advance by one while ready';
              END IF;
              IF OLD.state <> NEW.state AND NOT (
                (OLD.state='staging' AND NEW.state IN ('ready','quarantined','deleting')) OR
                (OLD.state='ready' AND NEW.state IN ('quarantined','deleting')) OR
                (OLD.state='quarantined' AND NEW.state='deleting') OR
                (OLD.state='deleting' AND NEW.state IN ('deleted','quarantined'))
              ) THEN
                RAISE EXCEPTION 'invalid media state transition';
              END IF;
              IF NEW.state='deleting' AND OLD.state<>'deleting' AND
                 narration_media_has_live_reference(NEW.id)
              THEN
                RAISE EXCEPTION 'referenced media cannot transition to deleting';
              END IF;
              RETURN NEW;
            END $$;

            CREATE FUNCTION narration_guard_media_gc_mark_v2()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE db_now timestamptz := clock_timestamp();
            BEGIN
              IF NEW.gc_marked_at IS DISTINCT FROM OLD.gc_marked_at
                 AND NEW.gc_generation<>OLD.gc_generation+1
              THEN
                RAISE EXCEPTION 'media GC mark may only change with the next generation';
              END IF;
              IF NEW.gc_generation=OLD.gc_generation+1 THEN
                IF OLD.state<>'ready'
                   OR NEW.gc_marked_at IS NULL
                   OR NEW.gc_marked_at<db_now-interval '5 seconds'
                   OR NEW.gc_marked_at>db_now+interval '1 second'
                   OR NEW.asset_class NOT IN
                     ('preview','segment_master','segment_playback','export')
                   OR NEW.retention_policy IN
                     ('source','cover','uploaded_original','locked_voice','legal_hold','keep')
                   OR (NEW.expires_at IS NOT NULL AND NEW.expires_at>db_now)
                   OR narration_media_has_live_reference(NEW.id)
                THEN
                  RAISE EXCEPTION 'media GC mark requires an unreferenced eligible derivative and server time';
                END IF;
              END IF;
              RETURN NEW;
            END $$;
            CREATE TRIGGER trg_t1_media_gc_mark_v2
            BEFORE UPDATE OF gc_generation,gc_marked_at ON media_assets
            FOR EACH ROW EXECUTE FUNCTION narration_guard_media_gc_mark_v2();

            CREATE FUNCTION narration_guard_media_policy_identity_v2()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE db_now timestamptz := clock_timestamp();
            BEGIN
              IF TG_OP='INSERT' THEN
                IF NEW.asset_class IS NOT NULL AND (
                     NEW.gc_generation<>0 OR NEW.gc_marked_at IS NOT NULL
                     OR NEW.created_at<db_now-interval '60 seconds'
                     OR NEW.created_at>db_now+interval '1 second'
                   )
                THEN
                  RAISE EXCEPTION 'new narration media requires generation zero and server creation time';
                END IF;
                RETURN NEW;
              END IF;
              IF OLD.created_at IS DISTINCT FROM NEW.created_at THEN
                RAISE EXCEPTION 'media creation time is immutable';
              END IF;
              IF (OLD.kind,OLD.asset_class,OLD.source_revision_id,
                  OLD.retention_policy,OLD.expires_at) IS DISTINCT FROM
                 (NEW.kind,NEW.asset_class,NEW.source_revision_id,
                  NEW.retention_policy,NEW.expires_at)
              THEN
                RAISE EXCEPTION 'media class/source/retention identity is immutable';
              END IF;
              RETURN NEW;
            END $$;
            CREATE TRIGGER trg_t1_media_policy_identity_v2
            BEFORE INSERT OR UPDATE ON media_assets FOR EACH ROW
            EXECUTE FUNCTION narration_guard_media_policy_identity_v2();
            """
        )
    )


def _create_execution_guards() -> None:
    op.execute(
        sa.text(
            """
            CREATE FUNCTION narration_reject_registry_mutation()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              RAISE EXCEPTION 'background execution registry is migration-owned';
            END $$;

            CREATE TRIGGER trg_background_resource_policy_immutable
            BEFORE INSERT OR UPDATE OR DELETE ON background_resource_class_policies
            FOR EACH ROW EXECUTE FUNCTION narration_reject_registry_mutation();
            CREATE TRIGGER trg_background_resource_slot_immutable
            BEFORE INSERT OR UPDATE OR DELETE ON background_resource_class_slots
            FOR EACH ROW EXECUTE FUNCTION narration_reject_registry_mutation();
            CREATE TRIGGER trg_background_job_kind_policy_immutable
            BEFORE INSERT OR UPDATE OR DELETE ON background_job_kind_policies
            FOR EACH ROW EXECUTE FUNCTION narration_reject_registry_mutation();

            CREATE FUNCTION narration_guard_registered_job_kind()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF NEW.job_kind LIKE 'narration.%' AND NOT EXISTS (
                SELECT 1 FROM background_job_kind_policies p
                WHERE p.job_kind=NEW.job_kind
                  AND p.resource_class=NEW.resource_class
              ) THEN
                RAISE EXCEPTION 'narration job kind/resource class is not registered';
              END IF;
              RETURN NEW;
            END $$;
            CREATE TRIGGER trg_background_job_registered_kind
            BEFORE INSERT OR UPDATE OF job_kind,resource_class ON background_jobs
            FOR EACH ROW EXECUTE FUNCTION narration_guard_registered_job_kind();
            CREATE TRIGGER trg_background_job_no_delete
            BEFORE DELETE ON background_jobs FOR EACH ROW
            EXECUTE FUNCTION narration_reject_mutation();

            CREATE FUNCTION narration_guard_executor_epoch()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF TG_OP='INSERT' THEN
                IF NEW.state<>'active' OR NEW.generation<1 THEN
                  RAISE EXCEPTION 'executor epoch must start active at a positive generation';
                END IF;
                RETURN NEW;
              END IF;
              IF TG_OP='DELETE' THEN
                RAISE EXCEPTION 'executor epoch cannot be deleted';
              END IF;
              IF (OLD.id,OLD.executor_key,OLD.generation,OLD.activated_at,
                  OLD.activated_actor) IS DISTINCT FROM
                 (NEW.id,NEW.executor_key,NEW.generation,NEW.activated_at,
                  NEW.activated_actor)
              THEN RAISE EXCEPTION 'executor epoch identity is immutable'; END IF;
              IF OLD.state<>'active' OR NEW.state<>'revoked' THEN
                RAISE EXCEPTION 'executor epoch only permits active to revoked';
              END IF;
              RETURN NEW;
            END $$;
            CREATE TRIGGER trg_background_executor_epoch_guard
            BEFORE INSERT OR UPDATE OR DELETE ON background_executor_epochs
            FOR EACH ROW EXECUTE FUNCTION narration_guard_executor_epoch();

            CREATE FUNCTION narration_guard_resource_lock_v2()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE db_now timestamptz := clock_timestamp();
            BEGIN
              IF TG_OP='DELETE' THEN
                RAISE EXCEPTION 'resource lock rows cannot be deleted';
              END IF;
              IF TG_OP='INSERT' THEN
                IF NEW.lease_generation<>1 OR NEW.lease_until<=db_now THEN
                  RAISE EXCEPTION 'new resource lock requires generation one and a live lease';
                END IF;
                RETURN NEW;
              END IF;
              IF OLD.resource_key<>NEW.resource_key OR NEW.updated_at<OLD.updated_at THEN
                RAISE EXCEPTION 'resource identity/time is immutable or non-monotonic';
              END IF;
              IF NEW.lease_generation=OLD.lease_generation+1 THEN
                IF OLD.lease_until>db_now OR NEW.lease_token=OLD.lease_token
                   OR NEW.lease_until<=db_now THEN
                  RAISE EXCEPTION 'resource takeover requires expiry, a new token, and a live lease';
                END IF;
              ELSIF NEW.lease_generation=OLD.lease_generation THEN
                IF NEW.lease_token=OLD.lease_token THEN
                  IF NEW.lease_owner<>OLD.lease_owner OR NEW.lease_until<OLD.lease_until
                     OR NEW.lease_until<=db_now THEN
                    RAISE EXCEPTION 'resource renew must retain owner/token and extend a live lease';
                  END IF;
                ELSE
                  IF NEW.lease_owner<>OLD.lease_owner OR NEW.lease_until>db_now THEN
                    RAISE EXCEPTION 'resource release must rotate token and expire immediately';
                  END IF;
                END IF;
              ELSE
                RAISE EXCEPTION 'resource generation may only stay or advance by one';
              END IF;
              RETURN NEW;
            END $$;
            CREATE TRIGGER trg_background_resource_lock_guard_v2
            BEFORE INSERT OR UPDATE OR DELETE ON background_resource_locks
            FOR EACH ROW EXECUTE FUNCTION narration_guard_resource_lock_v2();

            CREATE FUNCTION narration_guard_manual_retry_command()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF TG_OP='DELETE' THEN
                RAISE EXCEPTION 'manual retry command cannot be deleted';
              END IF;
              IF TG_OP='INSERT' THEN
                IF NEW.state<>'pending' THEN
                  RAISE EXCEPTION 'manual retry command must start pending';
                END IF;
                RETURN NEW;
              END IF;
              IF (OLD.id,OLD.job_id,OLD.owner_id,OLD.workspace_id,
                  OLD.idempotency_key,OLD.actor,OLD.reason,OLD.requested_at)
                 IS DISTINCT FROM
                 (NEW.id,NEW.job_id,NEW.owner_id,NEW.workspace_id,
                  NEW.idempotency_key,NEW.actor,NEW.reason,NEW.requested_at)
              THEN RAISE EXCEPTION 'manual retry command identity/audit is immutable'; END IF;
              IF OLD.state<>'pending' OR NEW.state NOT IN ('claimed','cancelled') THEN
                RAISE EXCEPTION 'manual retry command has an invalid one-way transition';
              END IF;
              RETURN NEW;
            END $$;
            CREATE TRIGGER trg_background_manual_retry_command_guard
            BEFORE INSERT OR UPDATE OR DELETE ON background_manual_retry_commands
            FOR EACH ROW EXECUTE FUNCTION narration_guard_manual_retry_command();

            CREATE FUNCTION narration_guard_attempt_execution_fence()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE epoch_state text; job_resource_class text;
                    slot_resource_class text; lock_row background_resource_locks%ROWTYPE;
                    db_now timestamptz := clock_timestamp();
            BEGIN
              IF TG_OP='INSERT' THEN
                SELECT resource_class INTO job_resource_class FROM background_jobs
                WHERE id=NEW.job_id FOR UPDATE;
                SELECT state INTO epoch_state FROM background_executor_epochs
                WHERE id=NEW.executor_epoch_id FOR KEY SHARE;
                IF NOT FOUND OR epoch_state<>'active' THEN
                  RAISE EXCEPTION 'attempt requires the current active executor epoch';
                END IF;
                SELECT resource_class INTO slot_resource_class
                FROM background_resource_class_slots WHERE resource_key=NEW.resource_key;
                SELECT * INTO lock_row FROM background_resource_locks
                WHERE resource_key=NEW.resource_key FOR UPDATE;
                IF job_resource_class IS DISTINCT FROM slot_resource_class OR NOT FOUND OR
                   (lock_row.lease_token,lock_row.lease_generation) IS DISTINCT FROM
                   (NEW.resource_lease_token,NEW.resource_lease_generation) OR
                   lock_row.lease_owner<>NEW.lease_owner OR
                   lock_row.lease_until<=db_now
                THEN
                  RAISE EXCEPTION 'attempt requires a live registered resource fence';
                END IF;
                RETURN NEW;
              END IF;
              SELECT state INTO epoch_state FROM background_executor_epochs
              WHERE id=OLD.executor_epoch_id FOR KEY SHARE;
              IF epoch_state<>'active' AND NOT (
                OLD.completed_at IS NULL AND NEW.completed_at IS NOT NULL
                AND OLD.lease_until<=db_now
                AND NEW.error_classification='security_failure'
              ) THEN
                RAISE EXCEPTION 'revoked executor epoch cannot mutate an attempt';
              END IF;
              IF OLD.completed_at IS NULL AND NEW.completed_at IS NOT NULL THEN
                IF NEW.completed_at<db_now-interval '5 seconds'
                   OR NEW.completed_at>db_now+interval '1 second'
                THEN
                  RAISE EXCEPTION 'attempt completion requires the authoritative database clock';
                END IF;
                IF NEW.actual_result_digest IS NOT NULL THEN
                  SELECT * INTO lock_row FROM background_resource_locks
                  WHERE resource_key=OLD.resource_key FOR UPDATE;
                  IF NOT FOUND OR
                     (lock_row.resource_key,lock_row.lease_owner,lock_row.lease_token,
                      lock_row.lease_generation) IS DISTINCT FROM
                     (OLD.resource_key,OLD.lease_owner,OLD.resource_lease_token,
                      OLD.resource_lease_generation) OR
                     lock_row.lease_until<=db_now
                  THEN
                    RAISE EXCEPTION 'successful attempt completion requires its live claim-time resource fence';
                  END IF;
                END IF;
              END IF;
              RETURN NEW;
            END $$;
            CREATE TRIGGER trg_background_attempt_execution_fence
            BEFORE INSERT OR UPDATE ON background_job_attempts
            FOR EACH ROW EXECUTE FUNCTION narration_guard_attempt_execution_fence();

            CREATE FUNCTION narration_guard_model_run_execution_fence()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE target_job_id uuid; job_state text;
                    attempt_row background_job_attempts%ROWTYPE;
                    epoch_state text; lock_row background_resource_locks%ROWTYPE;
                    db_now timestamptz := clock_timestamp();
            BEGIN
              IF NEW.created_at<db_now-interval '5 seconds'
                 OR NEW.created_at>db_now+interval '1 second'
              THEN
                RAISE EXCEPTION 'model run record requires the authoritative database clock';
              END IF;
              SELECT a.job_id INTO target_job_id FROM background_job_attempts a
              WHERE a.id=NEW.attempt_id;
              IF NOT FOUND THEN
                RAISE EXCEPTION 'model run record requires an existing attempt';
              END IF;
              SELECT state INTO job_state FROM background_jobs
              WHERE id=target_job_id FOR UPDATE;
              SELECT * INTO attempt_row FROM background_job_attempts
              WHERE id=NEW.attempt_id AND job_id=target_job_id FOR UPDATE;
              IF NOT FOUND OR job_state<>'running'
                 OR attempt_row.completed_at IS NOT NULL
                 OR attempt_row.lease_until<=db_now
              THEN
                RAISE EXCEPTION 'model run record requires the live current attempt';
              END IF;
              SELECT state INTO epoch_state FROM background_executor_epochs
              WHERE id=attempt_row.executor_epoch_id FOR KEY SHARE;
              IF NOT FOUND OR epoch_state<>'active' THEN
                RAISE EXCEPTION 'model run record requires an active executor epoch';
              END IF;
              SELECT * INTO lock_row FROM background_resource_locks
              WHERE resource_key=attempt_row.resource_key FOR UPDATE;
              IF NOT FOUND OR
                 (lock_row.resource_key,lock_row.lease_owner,lock_row.lease_token,
                  lock_row.lease_generation) IS DISTINCT FROM
                 (attempt_row.resource_key,attempt_row.lease_owner,
                  attempt_row.resource_lease_token,
                  attempt_row.resource_lease_generation) OR
                 lock_row.lease_until<=db_now
              THEN
                RAISE EXCEPTION 'model run record requires the attempt resource fence';
              END IF;
              RETURN NEW;
            END $$;
            CREATE TRIGGER trg_model_run_execution_fence
            BEFORE INSERT ON model_run_records FOR EACH ROW
            EXECUTE FUNCTION narration_guard_model_run_execution_fence();

            CREATE OR REPLACE FUNCTION narration_guard_ready_render_assets()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF NEW.state='ready' AND NOT EXISTS (
                SELECT 1
                FROM background_jobs j
                JOIN background_job_attempts a
                  ON a.job_id=j.id AND a.attempt_number=j.attempt_count
                JOIN background_executor_epochs ep ON ep.id=a.executor_epoch_id
                JOIN background_resource_class_slots slot
                  ON slot.resource_key=a.resource_key
                 AND slot.resource_class=j.resource_class
                JOIN narration_render_assets master_link
                  ON master_link.render_id=NEW.id AND master_link.role='master'
                JOIN media_assets master_asset ON master_asset.id=master_link.asset_id
                JOIN narration_render_assets playback_link
                  ON playback_link.render_id=NEW.id AND playback_link.role='playback'
                JOIN media_assets playback_asset ON playback_asset.id=playback_link.asset_id
                WHERE j.id=NEW.source_job_id
                  AND j.owner_id=NEW.owner_id
                  AND j.workspace_id=NEW.workspace_id
                  AND j.novel_id=NEW.novel_id
                  AND j.request_id=NEW.request_id
                  AND j.job_kind='narration.segment_render'
                  AND j.resource_class='moss-nano'
                  AND j.state='succeeded'
                  AND j.attempt_count>0
                  AND a.completed_at IS NOT NULL
                  AND a.error_classification IS NULL
                  AND a.error_code IS NULL
                  AND a.actual_result_digest=playback_link.actual_sha256
                  AND ep.executor_key='narration-worker'
                  AND ep.state='active'
                  AND slot.enabled IS TRUE
                  AND master_asset.owner_id=NEW.owner_id
                  AND master_asset.workspace_id=NEW.workspace_id
                  AND master_asset.novel_id=NEW.novel_id
                  AND master_asset.state='ready'
                  AND master_asset.asset_class='segment_master'
                  AND master_asset.checksum_algorithm='sha256'
                  AND master_asset.content_hash=master_link.actual_sha256
                  AND master_asset.byte_size IS NOT NULL
                  AND master_asset.mime_type IS NOT NULL
                  AND master_asset.verified_at IS NOT NULL
                  AND (master_asset.duration_ms IS NULL OR
                       master_asset.duration_ms=NEW.duration_ms)
                  AND playback_asset.owner_id=NEW.owner_id
                  AND playback_asset.workspace_id=NEW.workspace_id
                  AND playback_asset.novel_id=NEW.novel_id
                  AND playback_asset.state='ready'
                  AND playback_asset.asset_class='segment_playback'
                  AND playback_asset.checksum_algorithm='sha256'
                  AND playback_asset.content_hash=playback_link.actual_sha256
                  AND playback_asset.byte_size IS NOT NULL
                  AND playback_asset.mime_type IS NOT NULL
                  AND playback_asset.verified_at IS NOT NULL
                  AND playback_asset.duration_ms=NEW.duration_ms
                  AND (SELECT count(*) FROM narration_render_assets ra
                       WHERE ra.render_id=NEW.id)=2
                  AND EXISTS (
                    SELECT 1 FROM model_run_records mr
                    WHERE mr.attempt_id=a.id
                      AND mr.result_classification='success'
                      AND mr.actual_model_id IS NOT NULL
                      AND mr.model_fingerprint=NEW.model_fingerprint
                      AND mr.output_digest=playback_link.actual_sha256
                      AND mr.duration_ms=NEW.duration_ms
                  )
              ) THEN
                RAISE EXCEPTION
                  'ready render requires exact master/playback and successful fenced model provenance';
              END IF;
              RETURN NEW;
            END $$;

            CREATE FUNCTION narration_validate_manual_retry_pair(p_command_id uuid)
            RETURNS boolean LANGUAGE sql STABLE AS $$
              SELECT EXISTS (
                SELECT 1 FROM background_manual_retry_commands c
                JOIN background_job_attempts a ON a.id=c.claimed_attempt_id
                WHERE c.id=p_command_id AND c.state='claimed'
                  AND a.manual_retry_command_id=c.id AND a.job_id=c.job_id
                  AND a.retry_kind='manual' AND a.manual_actor=c.actor
                  AND a.manual_reason=c.reason
              );
            $$;

            CREATE FUNCTION narration_guard_job_execution_invariant()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE target_job_id uuid; job_row background_jobs%ROWTYPE;
                    unfinished integer; attempt_rows integer; max_attempt integer;
            BEGIN
              IF TG_TABLE_NAME='background_jobs' THEN
                target_job_id := (to_jsonb(NEW)->>'id')::uuid;
              ELSE
                target_job_id := (to_jsonb(NEW)->>'job_id')::uuid;
              END IF;
              SELECT * INTO job_row FROM background_jobs WHERE id=target_job_id;
              IF NOT FOUND THEN RETURN NEW; END IF;
              SELECT count(*),count(*) FILTER (WHERE completed_at IS NULL),
                     COALESCE(max(attempt_number),0)
                INTO attempt_rows,unfinished,max_attempt
              FROM background_job_attempts WHERE job_id=target_job_id;
              IF attempt_rows<>job_row.attempt_count OR max_attempt<>job_row.attempt_count THEN
                RAISE EXCEPTION 'job attempt_count must close over immutable attempt history';
              END IF;
              IF job_row.state IN ('running','cancel_requested') AND unfinished<>1 THEN
                RAISE EXCEPTION 'running/cancel-requested job requires one unfinished attempt';
              END IF;
              IF job_row.state NOT IN ('running','cancel_requested') AND unfinished<>0 THEN
                RAISE EXCEPTION 'non-running job cannot retain an unfinished attempt';
              END IF;
              IF job_row.state IN ('succeeded','failed','dead_letter','cancelled')
                 AND EXISTS (
                   SELECT 1 FROM background_job_attempts a
                   WHERE a.job_id=target_job_id AND a.completed_at IS NULL
                 )
              THEN RAISE EXCEPTION 'terminal job requires completed attempts'; END IF;
              IF EXISTS (
                SELECT 1 FROM background_manual_retry_commands c
                WHERE c.job_id=target_job_id AND c.state='pending'
                  AND job_row.state<>'queued'
              ) THEN
                RAISE EXCEPTION 'pending manual retry command requires a queued job';
              END IF;
              IF EXISTS (
                SELECT 1 FROM background_manual_retry_commands c
                WHERE c.job_id=target_job_id AND c.state='claimed'
                  AND NOT narration_validate_manual_retry_pair(c.id)
              ) THEN
                RAISE EXCEPTION 'manual retry command/attempt closure mismatch';
              END IF;
              IF EXISTS (
                SELECT 1 FROM background_job_attempts a
                WHERE a.job_id=target_job_id AND a.retry_kind='manual'
                  AND NOT narration_validate_manual_retry_pair(a.manual_retry_command_id)
              ) THEN
                RAISE EXCEPTION 'manual attempt lacks its immutable command';
              END IF;
              RETURN NEW;
            END $$;

            CREATE CONSTRAINT TRIGGER trg_background_job_execution_invariant
            AFTER INSERT OR UPDATE ON background_jobs
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION narration_guard_job_execution_invariant();
            CREATE CONSTRAINT TRIGGER trg_background_attempt_execution_invariant
            AFTER INSERT OR UPDATE ON background_job_attempts
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION narration_guard_job_execution_invariant();
            CREATE CONSTRAINT TRIGGER trg_background_manual_retry_execution_invariant
            AFTER INSERT OR UPDATE ON background_manual_retry_commands
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION narration_guard_job_execution_invariant();
            """
        )
    )


def upgrade() -> None:
    _preflight()
    _create_resource_and_epoch_registry()
    _extend_jobs_and_attempts()
    _harden_request_sources_and_media()
    _create_execution_guards()


def _restore_0011_functions() -> None:
    op.execute(
        sa.text(
            """
            DROP TRIGGER trg_narration_request_sources_scope ON narration_request_sources;
            DROP FUNCTION narration_validate_request_source_v2();
            CREATE TRIGGER trg_narration_request_sources_scope
            BEFORE INSERT OR UPDATE ON narration_request_sources FOR EACH ROW
            EXECUTE FUNCTION narration_validate_scope();

            CREATE OR REPLACE FUNCTION narration_guard_request()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF TG_OP='INSERT' THEN
                IF NEW.state<>'created' THEN RAISE EXCEPTION 'narration request must be inserted in created state'; END IF;
                RETURN NEW;
              END IF;
              IF (to_jsonb(OLD)-ARRAY['state','version','allows_edition','allows_render',
                                      'cancel_requested_at','cancel_actor','cancel_reason_code',
                                      'failure_code','updated_at','completed_at']) <>
                 (to_jsonb(NEW)-ARRAY['state','version','allows_edition','allows_render',
                                      'cancel_requested_at','cancel_actor','cancel_reason_code',
                                      'failure_code','updated_at','completed_at'])
              THEN RAISE EXCEPTION 'narration request canonical input is immutable'; END IF;
              IF OLD.intent='batch' AND OLD.state='created' AND NEW.state='analyzing'
                 AND NOT EXISTS (SELECT 1 FROM narration_request_sources rs WHERE rs.request_id=OLD.id)
              THEN RAISE EXCEPTION 'batch request requires at least one frozen source before analysis'; END IF;
              IF OLD.state<>NEW.state AND NOT (
                (OLD.state='created' AND NEW.state IN ('analyzing','cancel_requested')) OR
                (OLD.state='analyzing' AND NEW.state IN ('analyzed','review_required','queued','cancel_requested','failed')) OR
                (OLD.state='review_required' AND NEW.state IN ('analyzing','queued','cancel_requested','failed')) OR
                (OLD.state='queued' AND NEW.state IN ('rendering','cancel_requested','failed')) OR
                (OLD.state='rendering' AND NEW.state IN ('partial_ready','ready','cancel_requested','failed')) OR
                (OLD.state='partial_ready' AND NEW.state IN ('ready','cancel_requested','failed')) OR
                (OLD.state='cancel_requested' AND NEW.state='cancelled'))
              THEN RAISE EXCEPTION 'invalid narration request state transition'; END IF;
              RETURN NEW;
            END $$;

            CREATE OR REPLACE FUNCTION narration_guard_media_gc_plan()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE media_row media_assets%ROWTYPE;
            BEGIN
              IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'media GC deletion plan is immutable';
              END IF;
              SELECT * INTO media_row FROM media_assets m
              WHERE m.id=NEW.asset_id FOR UPDATE;
              IF NOT FOUND OR media_row.state <> 'ready' THEN
                RAISE EXCEPTION 'media GC plan requires a ready locked asset';
              END IF;
              IF (
                media_row.owner_id, media_row.workspace_id, media_row.novel_id,
                media_row.storage_backend, media_row.storage_path,
                media_row.content_hash, media_row.byte_size, media_row.gc_generation
              ) IS DISTINCT FROM (
                NEW.owner_id, NEW.workspace_id, NEW.novel_id,
                NEW.storage_backend, NEW.storage_path,
                NEW.content_hash, NEW.byte_size, NEW.generation
              ) THEN
                RAISE EXCEPTION 'media GC plan does not match canonical asset identity';
              END IF;
              IF narration_media_has_live_reference(NEW.asset_id) THEN
                RAISE EXCEPTION 'referenced media cannot enter a GC deletion plan';
              END IF;
              IF (SELECT count(*) FROM media_assets m
                  WHERE m.storage_backend=NEW.storage_backend
                    AND m.storage_path=NEW.storage_path) <> 1
              THEN
                RAISE EXCEPTION 'media GC plan requires exactly one physical blob owner';
              END IF;
              RETURN NEW;
            END $$;

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
              THEN
                RAISE EXCEPTION 'published media physical identity is immutable';
              END IF;
              IF OLD.gc_generation <> NEW.gc_generation AND
                 NOT (OLD.state='ready' AND NEW.gc_generation=OLD.gc_generation+1
                      AND NEW.gc_marked_at IS NOT NULL)
              THEN
                RAISE EXCEPTION 'media GC generation may only advance by one while ready';
              END IF;
              IF OLD.state <> NEW.state AND NOT (
                (OLD.state='staging' AND NEW.state IN ('ready','quarantined','deleting')) OR
                (OLD.state='ready' AND NEW.state IN ('quarantined','deleting')) OR
                (OLD.state='quarantined' AND NEW.state='deleting') OR
                (OLD.state='deleting' AND NEW.state='deleted')
              ) THEN
                RAISE EXCEPTION 'invalid media state transition';
              END IF;
              IF NEW.state='deleting' AND OLD.state<>'deleting' AND
                 narration_media_has_live_reference(NEW.id)
              THEN
                RAISE EXCEPTION 'referenced media cannot transition to deleting';
              END IF;
              RETURN NEW;
            END $$;

            CREATE OR REPLACE FUNCTION narration_guard_ready_render_assets()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF NEW.state='ready' AND NOT EXISTS
              (SELECT 1 FROM narration_render_assets ra JOIN media_assets m ON m.id=ra.asset_id
               WHERE ra.render_id=NEW.id AND ra.role='master' AND m.state='ready'
                 AND m.asset_class='segment_master' AND m.content_hash=ra.actual_sha256)
              THEN RAISE EXCEPTION 'ready render requires a verified master asset'; END IF;
              RETURN NEW;
            END $$;
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DO $$ BEGIN
              IF EXISTS (SELECT 1 FROM background_manual_retry_commands)
                 OR EXISTS (SELECT 1 FROM background_job_attempts)
              THEN
                RAISE EXCEPTION
                  'T1 execution-safety downgrade refused: execution evidence exists; fix forward';
              END IF;
              IF EXISTS (
                SELECT 1 FROM media_gc_deletion_plans
                WHERE reason_code='staging_orphan' OR novel_id IS NULL
              ) THEN
                RAISE EXCEPTION
                  'T1 execution-safety downgrade refused: staging GC evidence requires 0012';
              END IF;
            END $$;
            """
        )
    )

    for trigger, table in (
        ("trg_background_manual_retry_execution_invariant", "background_manual_retry_commands"),
        ("trg_background_attempt_execution_invariant", "background_job_attempts"),
        ("trg_background_job_execution_invariant", "background_jobs"),
        ("trg_model_run_execution_fence", "model_run_records"),
        ("trg_background_attempt_execution_fence", "background_job_attempts"),
        ("trg_background_manual_retry_command_guard", "background_manual_retry_commands"),
        ("trg_background_resource_lock_guard_v2", "background_resource_locks"),
        ("trg_background_executor_epoch_guard", "background_executor_epochs"),
        ("trg_background_job_no_delete", "background_jobs"),
        ("trg_background_job_registered_kind", "background_jobs"),
        ("trg_background_job_kind_policy_immutable", "background_job_kind_policies"),
        ("trg_background_resource_slot_immutable", "background_resource_class_slots"),
        ("trg_background_resource_policy_immutable", "background_resource_class_policies"),
        ("trg_t1_media_policy_identity_v2", "media_assets"),
        ("trg_t1_media_gc_mark_v2", "media_assets"),
        ("trg_t1_media_gc_plan_reachability", "media_gc_deletion_plans"),
        ("trg_t1_request_source_closure_child", "narration_request_sources"),
        ("trg_t1_request_source_closure_parent", "narration_requests"),
    ):
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger} ON {table}"))
    for function in (
        "narration_guard_job_execution_invariant()",
        "narration_validate_manual_retry_pair(uuid)",
        "narration_guard_model_run_execution_fence()",
        "narration_guard_attempt_execution_fence()",
        "narration_guard_manual_retry_command()",
        "narration_guard_resource_lock_v2()",
        "narration_guard_executor_epoch()",
        "narration_guard_registered_job_kind()",
        "narration_reject_registry_mutation()",
        "narration_guard_media_policy_identity_v2()",
        "narration_guard_media_gc_mark_v2()",
        "narration_guard_media_gc_plan_reachability()",
        "narration_guard_request_source_closure_v2()",
    ):
        op.execute(sa.text(f"DROP FUNCTION IF EXISTS {function}"))

    _restore_0011_functions()
    op.drop_constraint(
        "ck_media_gc_plan_reason_code", "media_gc_deletion_plans", type_="check"
    )
    op.drop_constraint(
        "ck_media_asset_ready_narration_identity", "media_assets", type_="check"
    )
    op.drop_constraint(
        "ck_media_asset_narration_mime_path", "media_assets", type_="check"
    )
    op.drop_constraint(
        "ck_media_asset_narration_canonical_path", "media_assets", type_="check"
    )
    op.drop_constraint(
        "fk_media_gc_plan_asset_local_scope",
        "media_gc_deletion_plans",
        type_="foreignkey",
    )
    op.alter_column(
        "media_gc_deletion_plans",
        "novel_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.create_foreign_key(
        "fk_media_gc_plan_asset_scope",
        "media_gc_deletion_plans",
        "media_assets",
        ["asset_id", "owner_id", "workspace_id", "novel_id"],
        ["id", "owner_id", "workspace_id", "novel_id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "ck_narration_request_source_position",
        "narration_request_sources",
        type_="check",
    )
    op.drop_constraint(
        "ck_narration_request_source_shape", "narration_requests", type_="check"
    )
    op.create_check_constraint(
        "ck_narration_request_source_shape",
        "narration_requests",
        "(intent IN ('create','update') AND document_id IS NOT NULL "
        "AND source_revision_id IS NOT NULL AND source_content_hash IS NOT NULL) "
        "OR intent IN ('analyze_only','batch')",
    )

    op.drop_constraint(
        "uq_asset_tombstone_original_asset", "asset_tombstones", type_="unique"
    )
    for constraint in (
        "ck_model_run_success_shape",
        "ck_model_run_output_digest_sha256",
        "ck_model_run_result_classification",
    ):
        op.drop_constraint(constraint, "model_run_records", type_="check")
    op.drop_constraint(
        "ck_narration_render_asset_sha256",
        "narration_render_assets",
        type_="check",
    )
    op.drop_constraint(
        "fk_narration_segment_render_source_job_scope",
        "narration_segment_renders",
        type_="foreignkey",
    )
    op.alter_column(
        "narration_segment_renders",
        "source_job_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.create_foreign_key(
        "narration_segment_renders_source_job_id_fkey",
        "narration_segment_renders",
        "background_jobs",
        ["source_job_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_constraint(
        "uq_background_job_publication_scope", "background_jobs", type_="unique"
    )

    op.drop_constraint(
        "uq_background_job_attempt_resource_generation",
        "background_job_attempts",
        type_="unique",
    )
    op.drop_constraint(
        "uq_model_run_attempt", "model_run_records", type_="unique"
    )
    op.drop_constraint(
        "uq_background_job_attempt_manual_retry_command",
        "background_job_attempts",
        type_="unique",
    )
    op.drop_constraint(
        "ck_background_job_attempt_resource_generation",
        "background_job_attempts",
        type_="check",
    )
    op.drop_constraint(
        "ck_background_job_attempt_completion_shape",
        "background_job_attempts",
        type_="check",
    )
    op.drop_constraint(
        "ck_background_job_attempt_manual_shape",
        "background_job_attempts",
        type_="check",
    )
    op.create_check_constraint(
        "ck_background_job_attempt_manual_shape",
        "background_job_attempts",
        "(retry_kind='manual' AND manual_actor IS NOT NULL AND manual_reason IS NOT NULL) OR "
        "(retry_kind IN ('initial','automatic') AND manual_actor IS NULL AND manual_reason IS NULL)",
    )
    for constraint in (
        "fk_background_job_attempt_resource_slot",
        "fk_background_job_attempt_executor_epoch",
        "fk_background_job_attempt_manual_retry_command",
    ):
        op.drop_constraint(constraint, "background_job_attempts", type_="foreignkey")
    for column in (
        "resource_lease_generation",
        "resource_lease_token",
        "resource_key",
        "executor_epoch_id",
        "manual_retry_command_id",
    ):
        op.drop_column("background_job_attempts", column)

    op.drop_index(
        "uq_background_manual_retry_pending_job",
        table_name="background_manual_retry_commands",
    )
    op.drop_table("background_manual_retry_commands")
    op.drop_constraint(
        "fk_background_resource_lock_slot",
        "background_resource_locks",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_background_job_resource_policy", "background_jobs", type_="foreignkey"
    )
    op.drop_constraint(
        "uq_background_job_command_scope", "background_jobs", type_="unique"
    )
    op.drop_index(
        "uq_background_executor_epoch_active",
        table_name="background_executor_epochs",
    )
    op.drop_table("background_executor_epochs")
    op.drop_table("background_job_kind_policies")
    op.drop_table("background_resource_class_slots")
    op.drop_table("background_resource_class_policies")
