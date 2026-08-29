"""Add semantic-index generations, consent, sources, batches and embeddings.

Revision ID: 20260829_0028
Revises: 20260829_0027
"""

from uuid import UUID

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import VECTOR
from sqlalchemy.dialects import postgresql


revision = "20260829_0028"
down_revision = "20260829_0027"
branch_labels = None
depends_on = None

MIGRATION_ACTOR = "migration:20260829_0028"
EMBEDDING_EPOCH_ID = UUID("7ff8a523-30f5-5d3f-9d7a-0c41bb7028fe")


def upgrade() -> None:
    op.add_column(
        "background_job_kind_policies",
        sa.Column("executor_key", sa.String(80), nullable=False, server_default="narration-worker"),
    )
    op.create_table(
        "embedding_configurations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("credential_ref", sa.String(240)),
        sa.Column("api_key_last4", sa.String(4)),
        sa.Column("api_key_updated_at", sa.DateTime(timezone=True)),
        sa.Column("active_generation_id", postgresql.UUID(as_uuid=True)),
        sa.Column("candidate_generation_id", postgresql.UUID(as_uuid=True)),
        sa.Column("previous_generation_id", postgresql.UUID(as_uuid=True)),
        sa.Column("connection_state", sa.String(30), nullable=False, server_default="unconfigured"),
        sa.Column("connection_summary_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("owner_id", "workspace_id", name="uq_embedding_configuration_scope"),
        sa.CheckConstraint("version > 0", name="ck_embedding_configuration_version"),
        sa.CheckConstraint("api_key_last4 IS NULL OR char_length(api_key_last4) = 4", name="ck_embedding_configuration_key_last4"),
    )
    op.create_table(
        "embedding_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_id", sa.String(80), nullable=False),
        sa.Column("protocol", sa.String(80), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("credential_ref", sa.String(240), nullable=False),
        sa.Column("requested_model_id", sa.String(160), nullable=False),
        sa.Column("actual_model_id", sa.String(160), nullable=False),
        sa.Column("actual_revision", sa.String(160)),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("output_type", sa.String(30), nullable=False),
        sa.Column("document_text_type", sa.String(30), nullable=False),
        sa.Column("query_text_type", sa.String(30), nullable=False),
        sa.Column("distance_metric", sa.String(30), nullable=False),
        sa.Column("index_fingerprint", sa.String(64), nullable=False),
        sa.Column("connection_state", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("owner_id", "workspace_id", "index_fingerprint", name="uq_embedding_profile_fingerprint"),
        sa.UniqueConstraint("id", "owner_id", "workspace_id", name="uq_embedding_profile_scope"),
        sa.CheckConstraint("dimension > 0", name="ck_embedding_profile_dimension"),
        sa.CheckConstraint("char_length(index_fingerprint) = 64", name="ck_embedding_profile_fingerprint"),
    )
    op.create_table(
        "embedding_generations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("generation_number", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("renderer_bundle_version", sa.String(120), nullable=False),
        sa.Column("chunker_version", sa.String(120), nullable=False),
        sa.Column("query_policy_version", sa.String(120), nullable=False),
        sa.Column("index_fingerprint", sa.String(64), nullable=False),
        sa.Column("consent_cohort_hash", sa.String(64), nullable=False),
        sa.Column("failure_code", sa.String(96)),
        sa.Column("evaluation_state", sa.String(20), nullable=False, server_default="not_run"),
        sa.Column("evaluation_summary_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("ready_at", sa.DateTime(timezone=True)),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column("retired_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["profile_id", "owner_id", "workspace_id"], ["embedding_profiles.id", "embedding_profiles.owner_id", "embedding_profiles.workspace_id"], name="fk_embedding_generation_profile_scope", ondelete="RESTRICT"),
        sa.UniqueConstraint("id", "owner_id", "workspace_id", name="uq_embedding_generation_scope"),
        sa.UniqueConstraint("owner_id", "workspace_id", "generation_number", name="uq_embedding_generation_number"),
        sa.CheckConstraint("generation_number > 0", name="ck_embedding_generation_number"),
        sa.CheckConstraint("state IN ('draft','building','ready','active','failed','cancelled','stale','retired')", name="ck_embedding_generation_state"),
        sa.CheckConstraint("evaluation_state IN ('not_run','pending','passed','failed')", name="ck_embedding_generation_evaluation_state"),
        sa.CheckConstraint("char_length(index_fingerprint) = 64 AND char_length(consent_cohort_hash) = 64", name="ck_embedding_generation_hashes"),
    )
    op.create_index("uq_embedding_generation_active", "embedding_generations", ["owner_id", "workspace_id"], unique=True, postgresql_where=sa.text("state='active'"))
    for column, suffix in (
        ("active_generation_id", "active_generation"),
        ("candidate_generation_id", "candidate_generation"),
        ("previous_generation_id", "previous_generation"),
    ):
        op.create_foreign_key(
            f"fk_embedding_configuration_{suffix}_scope",
            "embedding_configurations", "embedding_generations",
            [column, "owner_id", "workspace_id"], ["id", "owner_id", "workspace_id"],
            deferrable=True, initially="DEFERRED"
        )

    op.create_table(
        "novel_embedding_consents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("purpose", sa.String(80), nullable=False),
        sa.Column("data_scope_json", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("notice_version", sa.String(80), nullable=False),
        sa.Column("provider_id", sa.String(80), nullable=False),
        sa.Column("model_id", sa.String(160), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("operation_hash", sa.String(64), nullable=False),
        sa.Column("confirmed_actor", sa.String(120), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("revoked_actor", sa.String(120)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_reason", sa.String(240)),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("id", "novel_id", name="uq_novel_embedding_consent_scope"),
        sa.UniqueConstraint("novel_id", "idempotency_key", name="uq_novel_embedding_consent_idempotency"),
        sa.CheckConstraint("char_length(operation_hash) = 64", name="ck_novel_embedding_consent_hash"),
    )
    op.create_index("uq_novel_embedding_consent_active", "novel_embedding_consents", ["novel_id"], unique=True, postgresql_where=sa.text("revoked_at IS NULL"))
    op.create_table(
        "embedding_generation_novels",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("generation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("consent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("target_corpora_json", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("embedded_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_code", sa.String(96)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["generation_id", "owner_id", "workspace_id"], ["embedding_generations.id", "embedding_generations.owner_id", "embedding_generations.workspace_id"], name="fk_embedding_generation_novel_generation_scope", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["novel_id", "owner_id", "workspace_id"], ["novels.id", "novels.owner_id", "novels.workspace_id"], name="fk_embedding_generation_novel_novel_scope", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["consent_id", "novel_id"], ["novel_embedding_consents.id", "novel_embedding_consents.novel_id"], name="fk_embedding_generation_novel_consent_scope", ondelete="RESTRICT"),
        sa.UniqueConstraint("generation_id", "novel_id", name="uq_embedding_generation_novel"),
        sa.CheckConstraint("state IN ('pending','building','ready','failed','cancelled','stale')", name="ck_embedding_generation_novel_state"),
        sa.CheckConstraint("source_count >= 0 AND chunk_count >= 0 AND embedded_count >= 0 AND failure_count >= 0", name="ck_embedding_generation_novel_counts"),
        sa.CheckConstraint("char_length(input_digest) = 64", name="ck_embedding_generation_novel_digest"),
    )

    op.create_table(
        "semantic_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("generation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("corpus", sa.String(30), nullable=False),
        sa.Column("source_type", sa.String(60), nullable=False),
        sa.Column("source_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_revision_id", postgresql.UUID(as_uuid=True)),
        sa.Column("source_locator_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("renderer_version", sa.String(120), nullable=False),
        sa.Column("timeline_id", postgresql.UUID(as_uuid=True)),
        sa.Column("character_instance_id", postgresql.UUID(as_uuid=True)),
        sa.Column("narrative_start", sa.BigInteger()),
        sa.Column("narrative_end", sa.BigInteger()),
        sa.Column("visibility_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["generation_id", "novel_id"], ["embedding_generation_novels.generation_id", "embedding_generation_novels.novel_id"], name="fk_semantic_source_generation_novel", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["timeline_id", "novel_id"], ["story_timelines.id", "story_timelines.novel_id"], name="fk_semantic_source_timeline_scope", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["character_instance_id", "novel_id"], ["character_instances.id", "character_instances.novel_id"], name="fk_semantic_source_character_instance_scope", ondelete="RESTRICT"),
        sa.UniqueConstraint("generation_id", "novel_id", "source_fingerprint", name="uq_semantic_source_fingerprint"),
        sa.UniqueConstraint("id", "generation_id", name="uq_semantic_source_generation_scope"),
        sa.CheckConstraint("corpus IN ('manuscript','planning','private_asset','character','relationship','story_event','storyline','foreshadow','timeline')", name="ck_semantic_source_corpus"),
        sa.CheckConstraint("status IN ('current','invalid','retired')", name="ck_semantic_source_status"),
        sa.CheckConstraint("char_length(content_hash) = 64 AND char_length(source_fingerprint) = 64", name="ck_semantic_source_hashes"),
    )
    op.create_table(
        "semantic_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("generation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("source_start", sa.Integer(), nullable=False),
        sa.Column("source_end", sa.Integer(), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("chunker_version", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["source_id", "generation_id"], ["semantic_sources.id", "semantic_sources.generation_id"], name="fk_semantic_chunk_source_generation", ondelete="CASCADE"),
        sa.UniqueConstraint("source_id", "chunk_index", name="uq_semantic_chunk_index"),
        sa.UniqueConstraint("id", "generation_id", name="uq_semantic_chunk_generation_scope"),
        sa.CheckConstraint("chunk_index >= 0 AND source_start >= 0 AND source_end > source_start AND token_count >= 0", name="ck_semantic_chunk_bounds"),
        sa.CheckConstraint("char_length(content_hash) = 64", name="ck_semantic_chunk_hash"),
    )
    op.create_table(
        "embedding_index_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("generation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("batch_number", sa.Integer(), nullable=False),
        sa.Column("background_job_id", postgresql.UUID(as_uuid=True)),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_code", sa.String(96)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["generation_id", "novel_id"], ["embedding_generation_novels.generation_id", "embedding_generation_novels.novel_id"], name="fk_embedding_batch_generation_novel", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["background_job_id"], ["background_jobs.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("generation_id", "novel_id", "batch_number", name="uq_embedding_batch_number"),
        sa.UniqueConstraint("background_job_id", name="uq_embedding_batch_job"),
        sa.UniqueConstraint("id", "generation_id", name="uq_embedding_batch_generation_scope"),
        sa.CheckConstraint("batch_number >= 0 AND item_count BETWEEN 1 AND 10", name="ck_embedding_batch_size"),
        sa.CheckConstraint("state IN ('pending','queued','running','ready','failed','cancelled')", name="ck_embedding_batch_state"),
        sa.CheckConstraint("char_length(input_hash) = 64", name="ck_embedding_batch_hash"),
    )
    op.create_table(
        "embedding_index_batch_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("generation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["batch_id", "generation_id"], ["embedding_index_batches.id", "embedding_index_batches.generation_id"], name="fk_embedding_batch_item_batch_generation", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chunk_id", "generation_id"], ["semantic_chunks.id", "semantic_chunks.generation_id"], name="fk_embedding_batch_item_chunk_generation", ondelete="RESTRICT"),
        sa.UniqueConstraint("batch_id", "ordinal", name="uq_embedding_batch_item_ordinal"),
        sa.UniqueConstraint("batch_id", "chunk_id", name="uq_embedding_batch_item_chunk"),
        sa.CheckConstraint("ordinal BETWEEN 0 AND 9", name="ck_embedding_batch_item_ordinal"),
    )
    op.create_table(
        "semantic_embeddings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("generation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("embedding", VECTOR(), nullable=False),
        sa.Column("embedding_hash", sa.String(64), nullable=False),
        sa.Column("model_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("response_ordinal", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["chunk_id", "generation_id"], ["semantic_chunks.id", "semantic_chunks.generation_id"], name="fk_semantic_embedding_chunk_generation", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["batch_id", "generation_id"], ["embedding_index_batches.id", "embedding_index_batches.generation_id"], name="fk_semantic_embedding_batch_generation", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["model_run_id"], ["model_run_records.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("generation_id", "chunk_id", name="uq_semantic_embedding_chunk"),
        sa.CheckConstraint("dimension > 0 AND vector_dims(embedding) = dimension", name="ck_semantic_embedding_dimension"),
        sa.CheckConstraint("char_length(embedding_hash) = 64", name="ck_semantic_embedding_hash"),
    )

    # Registry rows are migration-owned.  Reopen only for this controlled seed.
    op.execute("DROP TRIGGER trg_background_resource_policy_immutable ON background_resource_class_policies")
    op.execute("DROP TRIGGER trg_background_resource_slot_immutable ON background_resource_class_slots")
    op.execute("DROP TRIGGER trg_background_job_kind_policy_immutable ON background_job_kind_policies")
    op.execute("DROP TRIGGER trg_background_executor_epoch_guard ON background_executor_epochs")
    op.execute(sa.text(f"""
        INSERT INTO background_resource_class_policies
          (resource_class,requires_publish_fence,exact_resource_key,max_concurrency,version,created_actor,created_at)
        VALUES ('dashscope-embedding',false,NULL,1,1,'{MIGRATION_ACTOR}',clock_timestamp());
        INSERT INTO background_resource_class_slots
          (resource_class,slot_number,resource_key,enabled,created_at)
        VALUES ('dashscope-embedding',0,'dashscope-embedding:0',true,clock_timestamp());
        INSERT INTO background_job_kind_policies
          (job_kind,resource_class,executor_key,version,created_actor,created_at)
        VALUES ('embedding.index_batch','dashscope-embedding','embedding-worker',1,'{MIGRATION_ACTOR}',clock_timestamp());
        INSERT INTO background_executor_epochs
          (id,executor_key,generation,state,activated_at,activated_actor)
        VALUES ('{EMBEDDING_EPOCH_ID}'::uuid,'embedding-worker',1,'active',clock_timestamp(),'{MIGRATION_ACTOR}');
    """))
    op.execute("CREATE TRIGGER trg_background_resource_policy_immutable BEFORE INSERT OR UPDATE OR DELETE ON background_resource_class_policies FOR EACH ROW EXECUTE FUNCTION narration_reject_registry_mutation()")
    op.execute("CREATE TRIGGER trg_background_resource_slot_immutable BEFORE INSERT OR UPDATE OR DELETE ON background_resource_class_slots FOR EACH ROW EXECUTE FUNCTION narration_reject_registry_mutation()")
    op.execute("CREATE TRIGGER trg_background_job_kind_policy_immutable BEFORE INSERT OR UPDATE OR DELETE ON background_job_kind_policies FOR EACH ROW EXECUTE FUNCTION narration_reject_registry_mutation()")
    op.execute("CREATE TRIGGER trg_background_executor_epoch_guard BEFORE INSERT OR UPDATE OR DELETE ON background_executor_epochs FOR EACH ROW EXECUTE FUNCTION narration_guard_executor_epoch()")
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION narration_guard_registered_job_kind()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM background_job_kind_policies p
            WHERE p.job_kind=NEW.job_kind AND p.resource_class=NEW.resource_class
          ) THEN
            RAISE EXCEPTION 'background job kind/resource class is not registered';
          END IF;
          RETURN NEW;
        END $$;
    """))


def downgrade() -> None:
    # Downgrade is intentionally schema-only and should run only when no new
    # semantic jobs/data exist.  Registry rows are removed under the migration lock.
    op.execute("DROP TRIGGER trg_background_resource_policy_immutable ON background_resource_class_policies")
    op.execute("DROP TRIGGER trg_background_resource_slot_immutable ON background_resource_class_slots")
    op.execute("DROP TRIGGER trg_background_job_kind_policy_immutable ON background_job_kind_policies")
    op.execute("DROP TRIGGER trg_background_executor_epoch_guard ON background_executor_epochs")
    op.execute(sa.text(f"""
        DELETE FROM background_executor_epochs WHERE id='{EMBEDDING_EPOCH_ID}'::uuid;
        DELETE FROM background_job_kind_policies WHERE job_kind='embedding.index_batch';
        DELETE FROM background_resource_class_slots WHERE resource_class='dashscope-embedding';
        DELETE FROM background_resource_class_policies WHERE resource_class='dashscope-embedding';
    """))
    op.execute("CREATE TRIGGER trg_background_resource_policy_immutable BEFORE INSERT OR UPDATE OR DELETE ON background_resource_class_policies FOR EACH ROW EXECUTE FUNCTION narration_reject_registry_mutation()")
    op.execute("CREATE TRIGGER trg_background_resource_slot_immutable BEFORE INSERT OR UPDATE OR DELETE ON background_resource_class_slots FOR EACH ROW EXECUTE FUNCTION narration_reject_registry_mutation()")
    op.execute("CREATE TRIGGER trg_background_job_kind_policy_immutable BEFORE INSERT OR UPDATE OR DELETE ON background_job_kind_policies FOR EACH ROW EXECUTE FUNCTION narration_reject_registry_mutation()")
    op.execute("CREATE TRIGGER trg_background_executor_epoch_guard BEFORE INSERT OR UPDATE OR DELETE ON background_executor_epochs FOR EACH ROW EXECUTE FUNCTION narration_guard_executor_epoch()")
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION narration_guard_registered_job_kind()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.job_kind LIKE 'narration.%' AND NOT EXISTS (
            SELECT 1 FROM background_job_kind_policies p
            WHERE p.job_kind=NEW.job_kind AND p.resource_class=NEW.resource_class
          ) THEN
            RAISE EXCEPTION 'narration job kind/resource class is not registered';
          END IF;
          RETURN NEW;
        END $$;
    """))
    op.drop_column("background_job_kind_policies", "executor_key")
    for table in (
        "semantic_embeddings", "embedding_index_batch_items", "embedding_index_batches",
        "semantic_chunks", "semantic_sources", "embedding_generation_novels",
        "novel_embedding_consents",
    ):
        op.drop_table(table)
    for name in ("fk_embedding_configuration_previous_generation_scope", "fk_embedding_configuration_candidate_generation_scope", "fk_embedding_configuration_active_generation_scope"):
        op.drop_constraint(name, "embedding_configurations", type_="foreignkey")
    op.drop_table("embedding_generations")
    op.drop_table("embedding_profiles")
    op.drop_table("embedding_configurations")
