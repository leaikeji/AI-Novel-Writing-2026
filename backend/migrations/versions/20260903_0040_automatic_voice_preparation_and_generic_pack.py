"""Add automatic voice preparation and workspace generic voice packs.

Revision ID: 20260903_0040
Revises: 20260902_0039

This PostgreSQL-only migration creates authority, constraints and runtime
sentinels.  It performs no model, network, media or voice-binding work.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260903_0040"
down_revision = "20260902_0039"
branch_labels = None
depends_on = None

LOCAL_OWNER = "29cf94d9-a5c9-54ec-912c-5dfff8738c4c"
LOCAL_WORKSPACE = "f0e2e632-bc99-52d2-9916-bb906aa4da6e"


def _replace_voice_version_constraints(*, allow_generic: bool) -> None:
    op.drop_constraint(
        "ck_voice_profile_version_activation_basis",
        "voice_profile_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_voice_profile_version_locked_shape",
        "voice_profile_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_voice_profile_version_model_run_shape",
        "voice_profile_versions",
        type_="check",
    )
    activation_values = (
        "'preview_confirmed','explicit_official_preset_selection',"
        "'character_one_click_generation','experimental_machine_validated'"
    )
    model_run_values = (
        "'experimental_machine_validated','character_one_click_generation'"
    )
    generic_locked = ""
    if allow_generic:
        activation_values += ",'generic_voice_pack_generation'"
        model_run_values += ",'generic_voice_pack_generation'"
        generic_locked = (
            " OR (activation_basis='generic_voice_pack_generation' "
            "AND source_type='generated' "
            "AND validation_basis='machine_validated' "
            "AND quality_state='accepted' AND model_run_id IS NOT NULL "
            "AND reference_asset_id IS NOT NULL "
            "AND locked_actor IS NULL AND locked_at IS NULL)"
        )
    op.create_check_constraint(
        "ck_voice_profile_version_activation_basis",
        "voice_profile_versions",
        f"activation_basis IN ({activation_values})",
    )
    op.create_check_constraint(
        "ck_voice_profile_version_locked_shape",
        "voice_profile_versions",
        "state <> 'locked' OR ("
        "(activation_basis='preview_confirmed' AND validation_basis='human_accepted' "
        "AND quality_state='accepted' AND locked_actor IS NOT NULL AND locked_at IS NOT NULL) OR "
        "(activation_basis='explicit_official_preset_selection' AND source_type='preset' "
        "AND validation_basis='not_required' AND quality_state='pending' "
        "AND locked_actor IS NULL AND locked_at IS NULL) OR "
        "(activation_basis='experimental_machine_validated' AND source_type='generated' "
        "AND validation_basis='machine_validated' AND quality_state='accepted' "
        "AND model_run_id IS NOT NULL AND locked_actor IS NULL AND locked_at IS NULL) OR "
        "(activation_basis='character_one_click_generation' AND source_type='generated' "
        "AND validation_basis='machine_validated' AND quality_state='accepted' "
        "AND model_run_id IS NOT NULL AND reference_asset_id IS NOT NULL "
        "AND locked_actor IS NULL AND locked_at IS NULL)"
        f"{generic_locked})",
    )
    op.create_check_constraint(
        "ck_voice_profile_version_model_run_shape",
        "voice_profile_versions",
        "model_run_id IS NULL OR (state='locked' AND source_type='generated' "
        f"AND activation_basis IN ({model_run_values}) "
        "AND validation_basis='machine_validated' AND quality_state='accepted')",
    )


def _create_voice_preparation_tables() -> None:
    op.create_table(
        "voice_preparation_commands",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True)),
        sa.Column("source_revision_id", postgresql.UUID(as_uuid=True)),
        sa.Column("mode", sa.String(40), nullable=False),
        sa.Column("actor", sa.String(120), nullable=False),
        sa.Column("explicit_requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("external_idempotency_digest", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("state", sa.String(32), nullable=False, server_default="reserved"),
        sa.Column("aggregate_version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("character_catalog_version", sa.BigInteger(), nullable=False),
        sa.Column("workspace_digest", sa.String(64), nullable=False),
        sa.Column("preflight_request_id", postgresql.UUID(as_uuid=True)),
        sa.Column("preflight_script_version_id", postgresql.UUID(as_uuid=True)),
        sa.Column("expected_draft_version", sa.BigInteger()),
        sa.Column("expected_content_hash", sa.String(64)),
        sa.Column("expected_settings_version", sa.BigInteger()),
        sa.Column("speaker_digest_version", sa.String(80)),
        sa.Column("speaker_digest", sa.String(64)),
        sa.Column("progress_current", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chapter_ready", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("background_remaining", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("continuation_idempotency_key", sa.String(160)),
        sa.Column("continuation_state", sa.String(24), nullable=False, server_default="not_applicable"),
        sa.Column("narration_request_id", postgresql.UUID(as_uuid=True)),
        sa.Column("preparation_attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_fence", postgresql.UUID(as_uuid=True)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("failure_code", sa.String(96)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["novel_id", "owner_id", "workspace_id"],
            ["novels.id", "novels.owner_id", "novels.workspace_id"],
            name="fk_voice_preparation_novel_scope", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "novel_id"], ["documents.id", "documents.novel_id"],
            name="fk_voice_preparation_document_scope", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["source_revision_id"], ["document_revisions.id"], name="fk_voice_preparation_source_revision", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["preflight_request_id", "novel_id"],
            ["narration_requests.id", "narration_requests.novel_id"],
            name="fk_voice_preparation_preflight_scope", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["preflight_script_version_id"], ["narration_script_versions.id"], name="fk_voice_preparation_script_version", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["narration_request_id", "novel_id"],
            ["narration_requests.id", "narration_requests.novel_id"],
            name="fk_voice_preparation_result_scope", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("owner_id", "workspace_id", "novel_id", "external_idempotency_digest", name="uq_voice_preparation_idempotency"),
        sa.UniqueConstraint("id", "novel_id", name="uq_voice_preparation_novel_guard"),
        sa.UniqueConstraint("owner_id", "workspace_id", "continuation_idempotency_key", name="uq_voice_preparation_continuation_key"),
        sa.UniqueConstraint("narration_request_id", name="uq_voice_preparation_result_request"),
        sa.CheckConstraint(f"owner_id='{LOCAL_OWNER}'::uuid AND workspace_id='{LOCAL_WORKSPACE}'::uuid", name="ck_voice_preparation_fixed_local_scope"),
        sa.CheckConstraint("mode='prepare_missing_dedicated'", name="ck_voice_preparation_mode"),
        sa.CheckConstraint("state IN ('reserved','preparing','ready','ready_with_warnings','failed','cancelled','superseded')", name="ck_voice_preparation_state"),
        sa.CheckConstraint("continuation_state IN ('not_applicable','pending','creating','created','cancelled','superseded','failed')", name="ck_voice_preparation_continuation_state"),
        sa.CheckConstraint("request_hash ~ '^[0-9a-f]{64}$' AND external_idempotency_digest ~ '^[0-9a-f]{64}$' AND workspace_digest ~ '^[0-9a-f]{64}$' AND (expected_content_hash IS NULL OR expected_content_hash ~ '^[0-9a-f]{64}$') AND (speaker_digest IS NULL OR speaker_digest ~ '^[0-9a-f]{64}$')", name="ck_voice_preparation_digests"),
        sa.CheckConstraint("aggregate_version>0 AND character_catalog_version>=0 AND progress_current>=0 AND progress_total>=0 AND progress_current<=progress_total AND background_remaining>=0 AND preparation_attempt>=0", name="ck_voice_preparation_counters"),
        sa.CheckConstraint("(document_id IS NULL AND source_revision_id IS NULL AND expected_draft_version IS NULL AND expected_content_hash IS NULL AND expected_settings_version IS NULL AND preflight_request_id IS NULL AND preflight_script_version_id IS NULL AND speaker_digest IS NULL AND speaker_digest_version IS NULL AND continuation_state='not_applicable' AND continuation_idempotency_key IS NULL AND narration_request_id IS NULL) OR (document_id IS NOT NULL AND source_revision_id IS NOT NULL AND expected_draft_version>0 AND expected_content_hash IS NOT NULL AND expected_settings_version>0 AND preflight_request_id IS NOT NULL AND preflight_script_version_id IS NOT NULL AND speaker_digest IS NOT NULL AND speaker_digest_version='narration-voice-preparation-speakers/1' AND continuation_idempotency_key IS NOT NULL)", name="ck_voice_preparation_chapter_shape"),
        sa.CheckConstraint("(lease_fence IS NULL AND lease_expires_at IS NULL) OR (lease_fence IS NOT NULL AND lease_expires_at IS NOT NULL)", name="ck_voice_preparation_lease"),
        sa.CheckConstraint("failure_code IS NULL OR failure_code ~ '^[A-Z][A-Z0-9_]{0,95}$'", name="ck_voice_preparation_failure_code"),
    )
    op.create_index("uq_voice_preparation_active_document", "voice_preparation_commands", ["novel_id", "document_id"], unique=True, postgresql_where=sa.text("document_id IS NOT NULL AND state IN ('reserved','preparing')"))
    op.create_index("uq_voice_preparation_active_book", "voice_preparation_commands", ["novel_id"], unique=True, postgresql_where=sa.text("document_id IS NULL AND state IN ('reserved','preparing')"))

    op.create_table(
        "voice_preparation_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("character_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("role_type", sa.String(30), nullable=False),
        sa.Column("chapter_speaker", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("expected_binding_version", sa.BigInteger(), nullable=False),
        sa.Column("workspace_digest", sa.String(64), nullable=False),
        sa.Column("original_voice_kind", sa.String(20), nullable=False),
        sa.Column("original_profile_id", postgresql.UUID(as_uuid=True)),
        sa.Column("original_voice_version_id", postgresql.UUID(as_uuid=True)),
        sa.Column("original_usable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("state", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("usable_for_narration", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("voice_generator_command_id", postgresql.UUID(as_uuid=True)),
        sa.Column("result_profile_id", postgresql.UUID(as_uuid=True)),
        sa.Column("result_voice_version_id", postgresql.UUID(as_uuid=True)),
        sa.Column("applied_binding_version", sa.BigInteger()),
        sa.Column("failure_code", sa.String(96)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["command_id", "novel_id"], ["voice_preparation_commands.id", "voice_preparation_commands.novel_id"], name="fk_voice_preparation_item_command_scope", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["character_id", "novel_id"], ["novel_characters.id", "novel_characters.novel_id"], name="fk_voice_preparation_item_character_scope", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["original_profile_id"], ["voice_profiles.id"], name="fk_voice_preparation_item_original_profile", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["original_voice_version_id"], ["voice_profile_versions.id"], name="fk_voice_preparation_item_original_version", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["voice_generator_command_id"], ["voice_generator_commands.id"], name="fk_voice_preparation_item_generator_command", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["result_profile_id"], ["voice_profiles.id"], name="fk_voice_preparation_item_result_profile", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["result_voice_version_id", "result_profile_id"], ["voice_profile_versions.id", "voice_profile_versions.profile_id"], name="fk_voice_preparation_item_result_version", ondelete="RESTRICT"),
        sa.UniqueConstraint("command_id", "position", name="uq_voice_preparation_item_position"),
        sa.UniqueConstraint("command_id", "character_id", name="uq_voice_preparation_item_character"),
        sa.CheckConstraint("state IN ('pending','preserved','queued','generating','ready_applied','ready_unapplied','fallback_official','failed','cancelled')", name="ck_voice_preparation_item_state"),
        sa.CheckConstraint("role_type IN ('main','supporting')", name="ck_voice_preparation_item_role"),
        sa.CheckConstraint("position>=0 AND expected_binding_version>=0 AND workspace_digest ~ '^[0-9a-f]{64}$'", name="ck_voice_preparation_item_identity"),
        sa.CheckConstraint("original_voice_kind IN ('none','official','private','uploaded','generated')", name="ck_voice_preparation_item_original_kind"),
        sa.CheckConstraint("(original_profile_id IS NULL AND original_voice_version_id IS NULL) OR (original_profile_id IS NOT NULL AND original_voice_version_id IS NOT NULL)", name="ck_voice_preparation_item_original_shape"),
        sa.CheckConstraint("(result_profile_id IS NULL AND result_voice_version_id IS NULL) OR (result_profile_id IS NOT NULL AND result_voice_version_id IS NOT NULL)", name="ck_voice_preparation_item_result_shape"),
        sa.CheckConstraint("failure_code IS NULL OR failure_code ~ '^[A-Z][A-Z0-9_]{0,95}$'", name="ck_voice_preparation_item_failure_code"),
    )
    op.create_index("ix_voice_preparation_items_command_state", "voice_preparation_items", ["command_id", "state", "position"])


def _create_generic_pack_tables() -> None:
    op.create_table(
        "generic_voice_pack_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("language", sa.String(40), nullable=False),
        sa.Column("catalog_id", sa.String(160), nullable=False),
        sa.Column("taxonomy_sha256", sa.String(64), nullable=False),
        sa.Column("design_catalog_sha256", sa.String(64), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("predecessor_version_id", postgresql.UUID(as_uuid=True)),
        sa.Column("state", sa.String(32), nullable=False, server_default="building"),
        sa.Column("slot_total", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("validated_slot_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_code", sa.String(96)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("ready_at", sa.DateTime(timezone=True)),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column("retired_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["predecessor_version_id"], ["generic_voice_pack_versions.id"], name="fk_generic_voice_pack_predecessor", ondelete="RESTRICT"),
        sa.UniqueConstraint("workspace_id", "language", "version_number", name="uq_generic_voice_pack_version_number"),
        sa.UniqueConstraint("id", "workspace_id", name="uq_generic_voice_pack_scope"),
        sa.CheckConstraint(f"owner_id='{LOCAL_OWNER}'::uuid AND workspace_id='{LOCAL_WORKSPACE}'::uuid", name="ck_generic_voice_pack_fixed_local_scope"),
        sa.CheckConstraint("language='zh-CN'", name="ck_generic_voice_pack_language"),
        sa.CheckConstraint("state IN ('building','ready_to_activate','active','retired_for_new_use','rejected','failed','superseded')", name="ck_generic_voice_pack_state"),
        sa.CheckConstraint("slot_total=24 AND validated_slot_count>=0 AND validated_slot_count<=slot_total", name="ck_generic_voice_pack_progress"),
        sa.CheckConstraint("taxonomy_sha256 ~ '^[0-9a-f]{64}$' AND design_catalog_sha256 ~ '^[0-9a-f]{64}$'", name="ck_generic_voice_pack_digests"),
        sa.CheckConstraint("failure_code IS NULL OR failure_code ~ '^[A-Z][A-Z0-9_]{0,95}$'", name="ck_generic_voice_pack_failure_code"),
        sa.CheckConstraint("state NOT IN ('ready_to_activate','active') OR validated_slot_count=24", name="ck_generic_voice_pack_activation_progress"),
    )
    op.create_index("uq_generic_voice_pack_active_language", "generic_voice_pack_versions", ["workspace_id", "language"], unique=True, postgresql_where=sa.text("state='active'"))

    op.create_table(
        "generic_voice_design_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("language", sa.String(40), nullable=False),
        sa.Column("slot_key", sa.String(80), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("instruction_digest", sa.String(64), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("parameters_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("parameters_digest", sa.String(64), nullable=False),
        sa.Column("runtime_identity_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("runtime_fingerprint", sa.String(64), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "fingerprint", name="uq_generic_voice_design_fingerprint"),
        sa.UniqueConstraint("id", "workspace_id", name="uq_generic_voice_design_scope"),
        sa.CheckConstraint(f"owner_id='{LOCAL_OWNER}'::uuid AND workspace_id='{LOCAL_WORKSPACE}'::uuid", name="ck_generic_voice_design_fixed_local_scope"),
        sa.CheckConstraint("language='zh-CN' AND seed>=0", name="ck_generic_voice_design_language_seed"),
        sa.CheckConstraint("slot_key ~ '^[a-z][a-z0-9_]{0,79}$' AND instruction_digest ~ '^[0-9a-f]{64}$' AND parameters_digest ~ '^[0-9a-f]{64}$' AND runtime_fingerprint ~ '^[0-9a-f]{64}$' AND fingerprint ~ '^[0-9a-f]{64}$'", name="ck_generic_voice_design_identity"),
        sa.CheckConstraint("char_length(instruction) BETWEEN 1 AND 1200 AND instruction=btrim(instruction)", name="ck_generic_voice_design_instruction"),
    )

    op.create_table(
        "generic_voice_generation_commands",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pack_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("design_draft_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("background_job_id", postgresql.UUID(as_uuid=True)),
        sa.Column("host_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("language", sa.String(40), nullable=False),
        sa.Column("slot_key", sa.String(80), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("design_fingerprint", sa.String(64), nullable=False),
        sa.Column("state", sa.String(24), nullable=False, server_default="queued"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_fence", postgresql.UUID(as_uuid=True)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("generated_reference_asset_id", postgresql.UUID(as_uuid=True)),
        sa.Column("nano_validation_asset_id", postgresql.UUID(as_uuid=True)),
        sa.Column("generator_model_run_id", postgresql.UUID(as_uuid=True)),
        sa.Column("nano_model_run_id", postgresql.UUID(as_uuid=True)),
        sa.Column("voice_profile_id", postgresql.UUID(as_uuid=True)),
        sa.Column("voice_version_id", postgresql.UUID(as_uuid=True)),
        sa.Column("progress_current", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_total", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("failure_code", sa.String(96)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["pack_version_id", "workspace_id"], ["generic_voice_pack_versions.id", "generic_voice_pack_versions.workspace_id"], name="fk_generic_voice_generation_pack_scope", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["design_draft_id", "workspace_id"], ["generic_voice_design_drafts.id", "generic_voice_design_drafts.workspace_id"], name="fk_generic_voice_generation_design_scope", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["background_job_id", "owner_id", "workspace_id"], ["background_jobs.id", "background_jobs.owner_id", "background_jobs.workspace_id"], name="fk_generic_voice_generation_job_scope", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["generated_reference_asset_id"], ["media_assets.id"], name="fk_generic_voice_generation_reference_asset", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["nano_validation_asset_id"], ["media_assets.id"], name="fk_generic_voice_generation_validation_asset", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["generator_model_run_id"], ["model_run_records.id"], name="fk_generic_voice_generation_generator_run", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["nano_model_run_id"], ["model_run_records.id"], name="fk_generic_voice_generation_nano_run", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["voice_profile_id"], ["voice_profiles.id"], name="fk_generic_voice_generation_profile", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["voice_version_id", "voice_profile_id"], ["voice_profile_versions.id", "voice_profile_versions.profile_id"], name="fk_generic_voice_generation_version_profile", ondelete="RESTRICT"),
        sa.UniqueConstraint("owner_id", "workspace_id", "idempotency_key", name="uq_generic_voice_generation_idempotency"),
        sa.UniqueConstraint("host_request_id", name="uq_generic_voice_generation_host_request"),
        sa.CheckConstraint(f"owner_id='{LOCAL_OWNER}'::uuid AND workspace_id='{LOCAL_WORKSPACE}'::uuid", name="ck_generic_voice_generation_fixed_local_scope"),
        sa.CheckConstraint("language='zh-CN'", name="ck_generic_voice_generation_language"),
        sa.CheckConstraint("state IN ('queued','building','ready','failed','cancelled','superseded')", name="ck_generic_voice_generation_state"),
        sa.CheckConstraint("slot_key ~ '^[a-z][a-z0-9_]{0,79}$' AND request_hash ~ '^[0-9a-f]{64}$' AND design_fingerprint ~ '^[0-9a-f]{64}$'", name="ck_generic_voice_generation_identity"),
        sa.CheckConstraint("attempt>=0 AND progress_current>=0 AND progress_total=2 AND progress_current<=progress_total", name="ck_generic_voice_generation_progress"),
        sa.CheckConstraint("failure_code IS NULL OR failure_code ~ '^[A-Z][A-Z0-9_]{0,95}$'", name="ck_generic_voice_generation_failure_code"),
        sa.CheckConstraint("(lease_fence IS NULL AND lease_expires_at IS NULL) OR (lease_fence IS NOT NULL AND lease_expires_at IS NOT NULL)", name="ck_generic_voice_generation_lease"),
        sa.CheckConstraint("(voice_profile_id IS NULL AND voice_version_id IS NULL) OR (voice_profile_id IS NOT NULL AND voice_version_id IS NOT NULL)", name="ck_generic_voice_generation_result_shape"),
    )
    op.create_index("uq_generic_voice_generation_pack_slot_active", "generic_voice_generation_commands", ["pack_version_id", "slot_key"], unique=True, postgresql_where=sa.text("state IN ('queued','building')"))

    op.create_table(
        "generic_voice_pack_version_slots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("pack_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slot_key", sa.String(80), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("category", sa.String(80), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("design_draft_id", postgresql.UUID(as_uuid=True)),
        sa.Column("generation_command_id", postgresql.UUID(as_uuid=True)),
        sa.Column("voice_profile_id", postgresql.UUID(as_uuid=True)),
        sa.Column("voice_version_id", postgresql.UUID(as_uuid=True)),
        sa.Column("design_fingerprint", sa.String(64), nullable=False),
        sa.Column("reference_audio_sha256", sa.String(64)),
        sa.Column("validation_audio_sha256", sa.String(64)),
        sa.Column("rights_approved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("quality_approved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("failure_code", sa.String(96)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["pack_version_id", "workspace_id"], ["generic_voice_pack_versions.id", "generic_voice_pack_versions.workspace_id"], name="fk_generic_voice_pack_slot_pack_scope", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["design_draft_id"], ["generic_voice_design_drafts.id"], name="fk_generic_voice_pack_slot_design", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["generation_command_id"], ["generic_voice_generation_commands.id"], name="fk_generic_voice_pack_slot_command", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["voice_profile_id"], ["voice_profiles.id"], name="fk_generic_voice_pack_slot_profile", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["voice_version_id", "voice_profile_id"], ["voice_profile_versions.id", "voice_profile_versions.profile_id"], name="fk_generic_voice_pack_slot_voice_version", ondelete="RESTRICT"),
        sa.UniqueConstraint("pack_version_id", "position", name="uq_generic_voice_pack_slot_position"),
        sa.UniqueConstraint("pack_version_id", "slot_key", name="uq_generic_voice_pack_slot_key"),
        sa.CheckConstraint("state IN ('pending','generating','validated','reused','rejected','failed')", name="ck_generic_voice_pack_slot_state"),
        sa.CheckConstraint("position>=0 AND position<24 AND slot_key ~ '^[a-z][a-z0-9_]{0,79}$'", name="ck_generic_voice_pack_slot_position_key"),
        sa.CheckConstraint("(voice_profile_id IS NULL AND voice_version_id IS NULL) OR (voice_profile_id IS NOT NULL AND voice_version_id IS NOT NULL)", name="ck_generic_voice_pack_slot_voice_shape"),
        sa.CheckConstraint("design_fingerprint ~ '^[0-9a-f]{64}$' AND (reference_audio_sha256 IS NULL OR reference_audio_sha256 ~ '^[0-9a-f]{64}$') AND (validation_audio_sha256 IS NULL OR validation_audio_sha256 ~ '^[0-9a-f]{64}$')", name="ck_generic_voice_pack_slot_digests"),
    )


def _extend_generic_voice_pools() -> None:
    op.add_column("generic_voice_pools", sa.Column("language", sa.String(40), nullable=False, server_default="zh-CN"))
    op.add_column("generic_voice_pools", sa.Column("source_pack_version_id", postgresql.UUID(as_uuid=True)))
    op.create_foreign_key("fk_generic_voice_pool_source_pack", "generic_voice_pools", "generic_voice_pack_versions", ["source_pack_version_id"], ["id"], ondelete="RESTRICT")
    op.create_check_constraint("ck_generic_voice_pool_language", "generic_voice_pools", "language IN ('zh-CN','en','ja-JP')")
    op.create_check_constraint("ck_generic_voice_pool_source_shape", "generic_voice_pools", "(source_pack_version_id IS NULL AND status<>'active') OR source_pack_version_id IS NOT NULL")


def _install_runtime_guards() -> None:
    op.execute(sa.text("""
        CREATE FUNCTION narration_guard_generic_voice_pack_v1()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE valid_count integer;
        BEGIN
          IF NEW.state IN ('ready_to_activate','active') THEN
            SELECT count(*) INTO valid_count
            FROM generic_voice_pack_version_slots s
            JOIN voice_profile_versions v ON v.id=s.voice_version_id
            JOIN voice_profiles p ON p.id=s.voice_profile_id
            WHERE s.pack_version_id=NEW.id
              AND s.state IN ('validated','reused')
              AND s.rights_approved IS TRUE AND s.quality_approved IS TRUE
              AND p.novel_id IS NULL AND p.workspace_id=NEW.workspace_id
              AND v.profile_id=p.id AND v.state='locked'
              AND v.activation_basis='generic_voice_pack_generation'
              AND v.validation_basis='machine_validated';
            IF valid_count<>24 OR NEW.validated_slot_count<>24 THEN
              RAISE EXCEPTION 'generic voice pack requires 24 validated library slots';
            END IF;
          END IF;
          RETURN NEW;
        END $$;

        CREATE TRIGGER trg_generic_voice_pack_activation
        BEFORE INSERT OR UPDATE ON generic_voice_pack_versions
        FOR EACH ROW EXECUTE FUNCTION narration_guard_generic_voice_pack_v1();

        CREATE FUNCTION narration_guard_generic_voice_pool_v1()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.status='active' AND NOT EXISTS (
            SELECT 1 FROM generic_voice_pack_versions p
            WHERE p.id=NEW.source_pack_version_id AND p.state='active'
              AND p.language=NEW.language AND p.validated_slot_count=24
          ) THEN
            RAISE EXCEPTION 'generic voice pool requires an active complete source pack';
          END IF;
          RETURN NEW;
        END $$;

        CREATE TRIGGER trg_generic_voice_pool_source
        BEFORE INSERT OR UPDATE ON generic_voice_pools
        FOR EACH ROW EXECUTE FUNCTION narration_guard_generic_voice_pool_v1();

        CREATE FUNCTION narration_reject_generic_voice_design_mutation_v1()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'generic voice design evidence is immutable';
        END $$;

        CREATE TRIGGER trg_generic_voice_design_immutable
        BEFORE UPDATE OR DELETE ON generic_voice_design_drafts
        FOR EACH ROW EXECUTE FUNCTION narration_reject_generic_voice_design_mutation_v1();
    """))
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION narration_guard_two_phase_voice_generator_run_v1()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE existing_count integer; owning_job_kind text;
        BEGIN
          SELECT count(*) INTO existing_count FROM model_run_records
          WHERE attempt_id=NEW.attempt_id;
          IF existing_count=0 THEN RETURN NEW; END IF;
          SELECT j.job_kind INTO owning_job_kind
          FROM background_job_attempts a JOIN background_jobs j ON j.id=a.job_id
          WHERE a.id=NEW.attempt_id;
          IF owning_job_kind NOT IN ('narration.voice_generate','narration.generic_voice_generate')
             OR existing_count>=2 THEN
            RAISE EXCEPTION 'background attempt cannot carry another ModelRun';
          END IF;
          RETURN NEW;
        END $$;
    """))


def _register_job_kinds(*, add: bool) -> None:
    op.execute("DROP TRIGGER trg_background_job_kind_policy_immutable ON background_job_kind_policies")
    if add:
        op.execute(sa.text(f"""
            INSERT INTO background_job_kind_policies
              (job_kind,resource_class,executor_key,version,created_actor,created_at)
            VALUES
              ('narration.voice_prepare','cpu-analysis','narration-worker',1,'{LOCAL_OWNER}',clock_timestamp()),
              ('narration.generic_voice_generate','moss-nano','narration-worker',1,'{LOCAL_OWNER}',clock_timestamp())
            ON CONFLICT (job_kind) DO NOTHING;
        """))
    else:
        op.execute("DELETE FROM background_job_kind_policies WHERE job_kind IN ('narration.voice_prepare','narration.generic_voice_generate')")
    op.execute("CREATE TRIGGER trg_background_job_kind_policy_immutable BEFORE INSERT OR UPDATE OR DELETE ON background_job_kind_policies FOR EACH ROW EXECUTE FUNCTION narration_reject_registry_mutation()")


def upgrade() -> None:
    _replace_voice_version_constraints(allow_generic=True)
    _create_voice_preparation_tables()
    _create_generic_pack_tables()
    _extend_generic_voice_pools()
    _register_job_kinds(add=True)
    _install_runtime_guards()


def downgrade() -> None:
    op.execute(sa.text("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM voice_preparation_commands)
             OR EXISTS (SELECT 1 FROM generic_voice_pack_versions)
             OR EXISTS (SELECT 1 FROM voice_profile_versions WHERE activation_basis='generic_voice_pack_generation')
          THEN RAISE EXCEPTION '0040 downgrade refused: voice preparation or generic pack evidence exists';
          END IF;
        END $$;
    """))
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION narration_guard_two_phase_voice_generator_run_v1()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE existing_count integer; owning_job_kind text;
        BEGIN
          SELECT count(*) INTO existing_count FROM model_run_records WHERE attempt_id=NEW.attempt_id;
          IF existing_count=0 THEN RETURN NEW; END IF;
          SELECT j.job_kind INTO owning_job_kind
          FROM background_job_attempts a JOIN background_jobs j ON j.id=a.job_id
          WHERE a.id=NEW.attempt_id;
          IF owning_job_kind<>'narration.voice_generate' OR existing_count>=2 THEN
            RAISE EXCEPTION 'background attempt cannot carry another ModelRun';
          END IF;
          RETURN NEW;
        END $$;
    """))
    op.execute("DROP TRIGGER trg_generic_voice_design_immutable ON generic_voice_design_drafts")
    op.execute("DROP FUNCTION narration_reject_generic_voice_design_mutation_v1()")
    op.execute("DROP TRIGGER trg_generic_voice_pool_source ON generic_voice_pools")
    op.execute("DROP FUNCTION narration_guard_generic_voice_pool_v1()")
    op.execute("DROP TRIGGER trg_generic_voice_pack_activation ON generic_voice_pack_versions")
    op.execute("DROP FUNCTION narration_guard_generic_voice_pack_v1()")
    _register_job_kinds(add=False)
    op.drop_constraint("ck_generic_voice_pool_source_shape", "generic_voice_pools", type_="check")
    op.drop_constraint("ck_generic_voice_pool_language", "generic_voice_pools", type_="check")
    op.drop_constraint("fk_generic_voice_pool_source_pack", "generic_voice_pools", type_="foreignkey")
    op.drop_column("generic_voice_pools", "source_pack_version_id")
    op.drop_column("generic_voice_pools", "language")
    op.drop_table("generic_voice_pack_version_slots")
    op.drop_index("uq_generic_voice_generation_pack_slot_active", table_name="generic_voice_generation_commands")
    op.drop_table("generic_voice_generation_commands")
    op.drop_table("generic_voice_design_drafts")
    op.drop_index("uq_generic_voice_pack_active_language", table_name="generic_voice_pack_versions")
    op.drop_table("generic_voice_pack_versions")
    op.drop_index("ix_voice_preparation_items_command_state", table_name="voice_preparation_items")
    op.drop_table("voice_preparation_items")
    op.drop_index("uq_voice_preparation_active_book", table_name="voice_preparation_commands")
    op.drop_index("uq_voice_preparation_active_document", table_name="voice_preparation_commands")
    op.drop_table("voice_preparation_commands")
    _replace_voice_version_constraints(allow_generic=False)
