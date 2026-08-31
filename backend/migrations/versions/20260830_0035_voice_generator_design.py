"""Add the durable VoiceGenerator design and one-click command authority.

Revision ID: 20260830_0035
Revises: 20260829_0034

This PostgreSQL-only migration creates records and guards.  It never loads a
model, performs network I/O, moves media, or starts a background command.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260830_0035"
down_revision = "20260829_0034"
branch_labels = None
depends_on = None


LOCAL_OWNER = "29cf94d9-a5c9-54ec-912c-5dfff8738c4c"
LOCAL_WORKSPACE = "f0e2e632-bc99-52d2-9916-bb906aa4da6e"


def _replace_voice_version_constraints(*, allow_character_generation: bool) -> None:
    op.drop_constraint(
        "ck_voice_profile_version_model_run_shape",
        "voice_profile_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_voice_profile_version_locked_shape",
        "voice_profile_versions",
        type_="check",
    )
    character_locked = (
        " OR (activation_basis='character_one_click_generation' "
        "AND source_type='generated' AND validation_basis='machine_validated' "
        "AND quality_state='accepted' AND model_run_id IS NOT NULL "
        "AND reference_asset_id IS NOT NULL AND locked_actor IS NULL "
        "AND locked_at IS NULL)"
        if allow_character_generation
        else ""
    )
    allowed_activations = (
        "('experimental_machine_validated','character_one_click_generation')"
        if allow_character_generation
        else "('experimental_machine_validated')"
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
        "AND model_run_id IS NOT NULL AND locked_actor IS NULL AND locked_at IS NULL)"
        f"{character_locked})",
    )
    op.create_check_constraint(
        "ck_voice_profile_version_model_run_shape",
        "voice_profile_versions",
        "model_run_id IS NULL OR (state='locked' AND source_type='generated' "
        f"AND activation_basis IN {allowed_activations} "
        "AND validation_basis='machine_validated' AND quality_state='accepted')",
    )


def _rebind_voice_generator_job(*, resource_class: str) -> None:
    if resource_class not in {"moss-nano", "voice-generator"}:
        raise ValueError("unsupported narration.voice_generate resource class")
    op.execute(
        "DROP TRIGGER trg_background_job_kind_policy_immutable "
        "ON background_job_kind_policies"
    )
    op.execute(
        sa.text(
            "UPDATE background_job_kind_policies "
            "SET resource_class=:resource_class, version=version+1 "
            "WHERE job_kind='narration.voice_generate'"
        ).bindparams(resource_class=resource_class)
    )
    op.execute(
        f"""
            DO $$
            BEGIN
              IF NOT EXISTS (
                SELECT 1 FROM background_job_kind_policies
                WHERE job_kind='narration.voice_generate'
                  AND resource_class='{resource_class}'
              ) THEN
                RAISE EXCEPTION 'narration.voice_generate policy rebind failed';
              END IF;
            END $$;
            """
    )
    op.execute(
        "CREATE TRIGGER trg_background_job_kind_policy_immutable "
        "BEFORE INSERT OR UPDATE OR DELETE ON background_job_kind_policies "
        "FOR EACH ROW EXECUTE FUNCTION narration_reject_registry_mutation()"
    )


def _create_voice_design_drafts() -> None:
    op.create_table(
        "voice_design_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("character_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("character_version", sa.BigInteger(), nullable=False),
        sa.Column("character_catalog_version", sa.BigInteger(), nullable=False),
        sa.Column("workspace_digest", sa.String(64), nullable=False),
        sa.Column("brief_schema_version", sa.String(80), nullable=False),
        sa.Column("brief_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("brief_digest", sa.String(64), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("instruction_digest_key_id", sa.String(80), nullable=False),
        sa.Column("instruction_digest", sa.String(64), nullable=False),
        sa.Column("model_evidence_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model_evidence_digest", sa.String(64), nullable=False),
        sa.Column("language", sa.String(40), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("parameters_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("parameters_digest", sa.String(64), nullable=False),
        sa.Column("runtime_identity_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["novel_id", "owner_id", "workspace_id"],
            ["novels.id", "novels.owner_id", "novels.workspace_id"],
            name="fk_voice_design_draft_novel_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["character_id", "novel_id"],
            ["novel_characters.id", "novel_characters.novel_id"],
            name="fk_voice_design_draft_character_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "owner_id", "workspace_id", "fingerprint",
            name="uq_voice_design_draft_fingerprint",
        ),
        sa.CheckConstraint(
            f"owner_id='{LOCAL_OWNER}'::uuid AND workspace_id='{LOCAL_WORKSPACE}'::uuid",
            name="ck_voice_design_draft_fixed_local_scope",
        ),
        sa.CheckConstraint(
            "character_version > 0 AND character_catalog_version >= 0",
            name="ck_voice_design_draft_character_versions",
        ),
        sa.CheckConstraint(
            "workspace_digest ~ '^[0-9a-f]{64}$' "
            "AND brief_digest ~ '^[0-9a-f]{64}$' "
            "AND instruction_digest ~ '^[0-9a-f]{64}$' "
            "AND model_evidence_digest ~ '^[0-9a-f]{64}$' "
            "AND parameters_digest ~ '^[0-9a-f]{64}$' "
            "AND fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_voice_design_draft_digests",
        ),
        sa.CheckConstraint(
            "instruction_digest_key_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$'",
            name="ck_voice_design_draft_digest_key",
        ),
        sa.CheckConstraint(
            "brief_schema_version='character-voice-brief/1' "
            "AND brief_json->>'schema_version'='character-voice-brief/1'",
            name="ck_voice_design_draft_brief_schema",
        ),
        sa.CheckConstraint(
            "char_length(instruction) BETWEEN 1 AND 1200 AND instruction=btrim(instruction)",
            name="ck_voice_design_draft_instruction",
        ),
        sa.CheckConstraint(
            "language IN ('zh-CN','en','ja-JP') AND seed >= 0",
            name="ck_voice_design_draft_language_seed",
        ),
        sa.CheckConstraint(
            "parameters_json->>'schema_version'='voice-generator-audio-parameters/1' "
            "AND parameters_json->>'audio_temperature_milli'='1500' "
            "AND parameters_json->>'audio_top_p_milli'='600' "
            "AND parameters_json->>'audio_top_k'='50' "
            "AND parameters_json->>'audio_repetition_penalty_milli'='1100'",
            name="ck_voice_design_draft_official_parameters",
        ),
        sa.CheckConstraint(
            "runtime_identity_json->>'protocol_version'='moss-voice-generator-host/1' "
            "AND runtime_identity_json->>'topology'='mps-bf16-staged-process-v1' "
            "AND runtime_identity_json->>'voice_generator_revision'="
            "'97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4' "
            "AND runtime_identity_json->>'codec_revision'="
            "'3cd226ba2947efa357ef453bcad111b6eafba782'",
            name="ck_voice_design_draft_runtime_identity",
        ),
    )


def _create_voice_generator_commands() -> None:
    op.create_table(
        "voice_generator_commands",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("character_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("draft_id", postgresql.UUID(as_uuid=True)),
        sa.Column("background_job_id", postgresql.UUID(as_uuid=True)),
        sa.Column("host_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expected_binding_version", sa.BigInteger(), nullable=False),
        sa.Column("applied_binding_version", sa.BigInteger()),
        sa.Column("generated_reference_asset_id", postgresql.UUID(as_uuid=True)),
        sa.Column("nano_validation_asset_id", postgresql.UUID(as_uuid=True)),
        sa.Column("generator_model_run_id", postgresql.UUID(as_uuid=True)),
        sa.Column("nano_model_run_id", postgresql.UUID(as_uuid=True)),
        sa.Column("voice_profile_id", postgresql.UUID(as_uuid=True)),
        sa.Column("voice_version_id", postgresql.UUID(as_uuid=True)),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("state", sa.String(48), nullable=False, server_default="queued"),
        sa.Column("progress_current", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_total", sa.Integer(), nullable=False, server_default="6"),
        sa.Column("failure_code", sa.String(96)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["novel_id", "owner_id", "workspace_id"],
            ["novels.id", "novels.owner_id", "novels.workspace_id"],
            name="fk_voice_generator_command_novel_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["character_id", "novel_id"],
            ["novel_characters.id", "novel_characters.novel_id"],
            name="fk_voice_generator_command_character_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["draft_id"], ["voice_design_drafts.id"], name="fk_voice_generator_command_draft", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["background_job_id", "owner_id", "workspace_id", "novel_id"],
            ["background_jobs.id", "background_jobs.owner_id", "background_jobs.workspace_id", "background_jobs.novel_id"],
            name="fk_voice_generator_command_job_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["generated_reference_asset_id"], ["media_assets.id"], name="fk_voice_generator_command_reference_asset", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["nano_validation_asset_id"], ["media_assets.id"], name="fk_voice_generator_command_validation_asset", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["generator_model_run_id"], ["model_run_records.id"], name="fk_voice_generator_command_generator_run", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["nano_model_run_id"], ["model_run_records.id"], name="fk_voice_generator_command_nano_run", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["voice_profile_id"], ["voice_profiles.id"], name="fk_voice_generator_command_profile", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["voice_version_id", "voice_profile_id"],
            ["voice_profile_versions.id", "voice_profile_versions.profile_id"],
            name="fk_voice_generator_command_version_profile",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("owner_id", "workspace_id", "idempotency_key", name="uq_voice_generator_command_idempotency"),
        sa.UniqueConstraint("host_request_id", name="uq_voice_generator_command_host_request"),
        sa.CheckConstraint(
            f"owner_id='{LOCAL_OWNER}'::uuid AND workspace_id='{LOCAL_WORKSPACE}'::uuid",
            name="ck_voice_generator_command_fixed_local_scope",
        ),
        sa.CheckConstraint(
            "expected_binding_version >= 0 AND "
            "(applied_binding_version IS NULL OR applied_binding_version > 0)",
            name="ck_voice_generator_command_binding_versions",
        ),
        sa.CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$' "
            "AND request_hash ~ '^[0-9a-f]{64}$'",
            name="ck_voice_generator_command_request_identity",
        ),
        sa.CheckConstraint(
            "state IN ('queued','analyzing_character','waiting_for_heavy_runtime',"
            "'generating_voice','unloading_voice_generator','validating_with_nano',"
            "'ready_applied','ready_unapplied','failed_character_analysis',"
            "'failed_runtime_unavailable','failed_memory_safety','failed_generation',"
            "'failed_audio_validation','failed_nano_validation','failed_storage',"
            "'cancelled','superseded')",
            name="ck_voice_generator_command_state",
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR failure_code ~ '^[A-Z][A-Z0-9_]{0,95}$'",
            name="ck_voice_generator_command_failure_code",
        ),
        sa.CheckConstraint(
            "progress_current >= 0 AND progress_total=6 AND progress_current <= progress_total",
            name="ck_voice_generator_command_progress",
        ),
        sa.CheckConstraint(
            "(draft_id IS NULL AND state IN ('queued','analyzing_character',"
            "'failed_character_analysis','cancelled','superseded')) OR draft_id IS NOT NULL",
            name="ck_voice_generator_command_draft_state",
        ),
        sa.CheckConstraint(
            "(voice_profile_id IS NULL AND voice_version_id IS NULL) OR "
            "(voice_profile_id IS NOT NULL AND voice_version_id IS NOT NULL)",
            name="ck_voice_generator_command_voice_result_shape",
        ),
        sa.CheckConstraint(
            "(state='ready_applied' AND voice_version_id IS NOT NULL "
            "AND applied_binding_version IS NOT NULL AND completed_at IS NOT NULL "
            "AND failure_code IS NULL) OR "
            "(state='ready_unapplied' AND voice_version_id IS NOT NULL "
            "AND applied_binding_version IS NULL AND completed_at IS NOT NULL "
            "AND failure_code IS NULL) OR "
            "(state LIKE 'failed_%' AND completed_at IS NOT NULL "
            "AND applied_binding_version IS NULL AND failure_code IS NOT NULL) OR "
            "(state IN ('cancelled','superseded') AND completed_at IS NOT NULL "
            "AND applied_binding_version IS NULL) OR "
            "(state IN ('queued','analyzing_character','waiting_for_heavy_runtime',"
            "'generating_voice','unloading_voice_generator','validating_with_nano') "
            "AND completed_at IS NULL AND applied_binding_version IS NULL "
            "AND failure_code IS NULL)",
            name="ck_voice_generator_command_terminal_shape",
        ),
    )
    op.create_index(
        "ix_voice_generator_commands_scope_created",
        "voice_generator_commands",
        ["owner_id", "workspace_id", "novel_id", "character_id", "created_at"],
    )
    op.create_index(
        "uq_voice_generator_command_character_active",
        "voice_generator_commands",
        ["novel_id", "character_id"],
        unique=True,
        postgresql_where=sa.text(
            "state IN ('queued','analyzing_character','waiting_for_heavy_runtime',"
            "'generating_voice','unloading_voice_generator','validating_with_nano')"
        ),
    )


def _create_voice_generator_run_evidence() -> None:
    op.create_table(
        "voice_generator_run_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("model_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("protocol_version", sa.String(80), nullable=False),
        sa.Column("topology", sa.String(80), nullable=False),
        sa.Column("runtime_fingerprint", sa.String(64), nullable=False),
        sa.Column("requested_identity_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("actual_identity_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("instruction_digest", sa.String(64), nullable=False),
        sa.Column("token_digest", sa.String(64)),
        sa.Column("audio_digest", sa.String(64)),
        sa.Column("audio_metrics_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("memory_summary_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result_classification", sa.String(32), nullable=False),
        sa.Column("exit_reason_code", sa.String(96), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["command_id"], ["voice_generator_commands.id"], name="fk_voice_generator_run_command", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["model_run_id"], ["model_run_records.id"], name="fk_voice_generator_run_model_run", ondelete="RESTRICT"),
        sa.UniqueConstraint("command_id", "attempt_number", name="uq_voice_generator_run_attempt_number"),
        sa.UniqueConstraint("model_run_id", name="uq_voice_generator_run_model_run"),
        sa.CheckConstraint("attempt_number > 0", name="ck_voice_generator_run_attempt_number"),
        sa.CheckConstraint(
            "request_digest ~ '^[0-9a-f]{64}$' "
            "AND runtime_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND instruction_digest ~ '^[0-9a-f]{64}$' "
            "AND (token_digest IS NULL OR token_digest ~ '^[0-9a-f]{64}$') "
            "AND (audio_digest IS NULL OR audio_digest ~ '^[0-9a-f]{64}$')",
            name="ck_voice_generator_run_digests",
        ),
        sa.CheckConstraint(
            "result_classification IN ('success','retryable_failure',"
            "'non_retryable_failure','cancelled','security_failure')",
            name="ck_voice_generator_run_result",
        ),
        sa.CheckConstraint(
            "protocol_version='moss-voice-generator-host/1' "
            "AND topology='mps-bf16-staged-process-v1'",
            name="ck_voice_generator_run_runtime_identity",
        ),
        sa.CheckConstraint("completed_at >= started_at", name="ck_voice_generator_run_time_order"),
        sa.CheckConstraint(
            "result_classification <> 'success' OR "
            "(token_digest IS NOT NULL AND audio_digest IS NOT NULL)",
            name="ck_voice_generator_run_success_shape",
        ),
    )


def _allow_two_phase_voice_generator_model_runs() -> None:
    op.drop_constraint(
        "uq_model_run_attempt",
        "model_run_records",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_model_run_attempt",
        "model_run_records",
        ["attempt_id", "requested_model_id"],
    )
    op.execute(
        sa.text(
            """
            CREATE FUNCTION narration_guard_two_phase_voice_generator_run_v1()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE
              existing_count integer;
              owning_job_kind text;
            BEGIN
              SELECT count(*) INTO existing_count
              FROM model_run_records
              WHERE attempt_id=NEW.attempt_id;
              IF existing_count=0 THEN
                RETURN NEW;
              END IF;
              SELECT j.job_kind INTO owning_job_kind
              FROM background_job_attempts a
              JOIN background_jobs j ON j.id=a.job_id
              WHERE a.id=NEW.attempt_id;
              IF owning_job_kind<>'narration.voice_generate' OR existing_count>=2 THEN
                RAISE EXCEPTION 'background attempt cannot carry another ModelRun';
              END IF;
              RETURN NEW;
            END $$;

            CREATE TRIGGER trg_two_phase_voice_generator_model_run
            BEFORE INSERT ON model_run_records
            FOR EACH ROW EXECUTE FUNCTION narration_guard_two_phase_voice_generator_run_v1();
            """
        )
    )


def _restore_one_model_run_per_attempt() -> None:
    op.execute(
        "DROP TRIGGER trg_two_phase_voice_generator_model_run ON model_run_records"
    )
    op.execute("DROP FUNCTION narration_guard_two_phase_voice_generator_run_v1()")
    op.drop_constraint(
        "uq_model_run_attempt",
        "model_run_records",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_model_run_attempt",
        "model_run_records",
        ["attempt_id"],
    )


def _install_guards() -> None:
    op.execute(
        sa.text(
            """
            CREATE FUNCTION narration_reject_voice_generator_immutable_v1()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              RAISE EXCEPTION 'immutable VoiceGenerator evidence cannot be changed';
            END $$;

            CREATE TRIGGER trg_voice_design_draft_immutable
            BEFORE UPDATE OR DELETE ON voice_design_drafts
            FOR EACH ROW EXECUTE FUNCTION narration_reject_voice_generator_immutable_v1();

            CREATE TRIGGER trg_voice_generator_run_evidence_immutable
            BEFORE UPDATE OR DELETE ON voice_generator_run_evidence
            FOR EACH ROW EXECUTE FUNCTION narration_reject_voice_generator_immutable_v1();

            CREATE FUNCTION narration_guard_voice_generator_command_v1()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF TG_OP='DELETE' THEN
                RAISE EXCEPTION 'VoiceGenerator command evidence cannot be deleted';
              END IF;
              IF OLD.state IN (
                'ready_applied','failed_character_analysis','failed_runtime_unavailable',
                'failed_memory_safety','failed_generation','failed_audio_validation',
                'failed_nano_validation','failed_storage','cancelled','superseded'
              ) THEN
                RAISE EXCEPTION 'terminal VoiceGenerator command is immutable';
              END IF;
              IF OLD.state='ready_unapplied' AND NEW.state<>'ready_applied' THEN
                RAISE EXCEPTION 'unapplied VoiceGenerator command can only be applied';
              END IF;
              IF (to_jsonb(OLD)-ARRAY[
                    'draft_id','background_job_id','generated_reference_asset_id',
                    'nano_validation_asset_id','generator_model_run_id','nano_model_run_id',
                    'voice_profile_id','voice_version_id','state','progress_current',
                    'failure_code','started_at','completed_at','applied_at','updated_at',
                    'applied_binding_version'
                  ]) <>
                 (to_jsonb(NEW)-ARRAY[
                    'draft_id','background_job_id','generated_reference_asset_id',
                    'nano_validation_asset_id','generator_model_run_id','nano_model_run_id',
                    'voice_profile_id','voice_version_id','state','progress_current',
                    'failure_code','started_at','completed_at','applied_at','updated_at',
                    'applied_binding_version'
                  ]) THEN
                RAISE EXCEPTION 'VoiceGenerator command identity is immutable';
              END IF;
              IF OLD.state<>NEW.state AND NOT (
                (OLD.state='queued' AND NEW.state IN ('analyzing_character','cancelled','superseded')) OR
                (OLD.state='analyzing_character' AND NEW.state IN (
                  'waiting_for_heavy_runtime','failed_character_analysis','cancelled','superseded')) OR
                (OLD.state='waiting_for_heavy_runtime' AND NEW.state IN (
                  'generating_voice','failed_runtime_unavailable','cancelled','superseded')) OR
                (OLD.state='generating_voice' AND NEW.state IN (
                  'unloading_voice_generator','failed_runtime_unavailable',
                  'failed_memory_safety','failed_generation',
                  'failed_audio_validation','cancelled','superseded')) OR
                (OLD.state='unloading_voice_generator' AND NEW.state IN (
                  'validating_with_nano','failed_memory_safety',
                  'failed_audio_validation','failed_storage','superseded')) OR
                (OLD.state='validating_with_nano' AND NEW.state IN (
                  'ready_applied','ready_unapplied','failed_nano_validation',
                  'failed_storage','superseded')) OR
                (OLD.state='ready_unapplied' AND NEW.state='ready_applied')
              ) THEN
                RAISE EXCEPTION 'invalid VoiceGenerator command state transition';
              END IF;
              IF NEW.updated_at < OLD.updated_at OR NEW.progress_current < OLD.progress_current THEN
                RAISE EXCEPTION 'VoiceGenerator command progress is not monotonic';
              END IF;
              RETURN NEW;
            END $$;

            CREATE TRIGGER trg_voice_generator_command_lifecycle
            BEFORE UPDATE OR DELETE ON voice_generator_commands
            FOR EACH ROW EXECUTE FUNCTION narration_guard_voice_generator_command_v1();
            """
        )
    )


def _install_closure() -> None:
    op.execute(
        sa.text(
            """
            CREATE FUNCTION narration_check_voice_generator_closure_v1()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE command_row voice_generator_commands%ROWTYPE;
            BEGIN
              FOR command_row IN
                SELECT * FROM voice_generator_commands
                WHERE state IN (
                  'waiting_for_heavy_runtime','generating_voice',
                  'unloading_voice_generator','validating_with_nano',
                  'ready_applied','ready_unapplied'
                )
              LOOP
                IF NOT EXISTS (
                  SELECT 1
                  FROM voice_design_drafts draft
                  JOIN background_jobs job
                    ON job.id=command_row.background_job_id
                  WHERE draft.id=command_row.draft_id
                    AND (draft.owner_id,draft.workspace_id,draft.novel_id,draft.character_id)=
                        (command_row.owner_id,command_row.workspace_id,
                         command_row.novel_id,command_row.character_id)
                    AND job.job_kind='narration.voice_generate'
                    AND job.resource_class='moss-nano'
                    AND (job.owner_id,job.workspace_id,job.novel_id)=
                        (command_row.owner_id,command_row.workspace_id,command_row.novel_id)
                    AND job.input_hash=draft.fingerprint
                    AND (
                      (command_row.state IN (
                         'waiting_for_heavy_runtime','generating_voice',
                         'unloading_voice_generator','validating_with_nano'
                       ) AND job.state IN ('queued','running','cancel_requested'))
                      OR
                      (command_row.state IN ('ready_applied','ready_unapplied')
                       AND job.state='succeeded')
                    )
                ) THEN
                  RAISE EXCEPTION 'VoiceGenerator draft/job closure mismatch';
                END IF;

                IF command_row.state IN ('ready_applied','ready_unapplied') AND NOT EXISTS (
                  SELECT 1
                  FROM voice_design_drafts draft
                  JOIN media_assets reference
                    ON reference.id=command_row.generated_reference_asset_id
                  JOIN media_assets validation
                    ON validation.id=command_row.nano_validation_asset_id
                  JOIN model_run_records generator_run
                    ON generator_run.id=command_row.generator_model_run_id
                  JOIN model_run_records nano_run
                    ON nano_run.id=command_row.nano_model_run_id
                  JOIN background_job_attempts attempt
                    ON attempt.id=generator_run.attempt_id
                   AND attempt.id=nano_run.attempt_id
                   AND attempt.job_id=command_row.background_job_id
                  JOIN voice_generator_run_evidence evidence
                    ON evidence.command_id=command_row.id
                   AND evidence.model_run_id=generator_run.id
                  JOIN voice_profiles profile
                    ON profile.id=command_row.voice_profile_id
                  JOIN voice_profile_versions version
                    ON version.id=command_row.voice_version_id
                   AND version.profile_id=profile.id
                  JOIN voice_rights_records rights
                    ON rights.id=version.rights_record_id
                  WHERE draft.id=command_row.draft_id
                    AND reference.kind='narration_voice_reference'
                    AND reference.asset_class='voice_reference'
                    AND reference.state IN ('ready','deleting','deleted')
                    AND reference.content_hash=evidence.audio_digest
                    AND validation.kind='narration_voice_preview'
                    AND validation.asset_class='preview'
                    AND validation.state IN ('ready','deleting','deleted')
                    AND generator_run.requested_model_id=
                        'OpenMOSS-Team/MOSS-VoiceGenerator'
                    AND generator_run.requested_revision=
                        '97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4'
                    AND generator_run.output_digest=reference.content_hash
                    AND nano_run.requested_model_id=
                        'OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX+MOSS-Audio-Tokenizer-Nano-ONNX'
                    AND nano_run.requested_revision=
                        'f52645cb467506d8e18e746ddd59482685b74e58+ceff0d0749bfb3fa2d61149794ec6feef0d1e1ae'
                    AND nano_run.actual_model_id=nano_run.requested_model_id
                    AND nano_run.actual_revision=nano_run.requested_revision
                    AND nano_run.model_fingerprint=
                        '3c76f3e9e1381699c5555287cf66eeb023632d0c3ee94adc6d8ae1b1d455fd7d'
                    AND nano_run.output_digest=validation.content_hash
                    AND evidence.request_digest ~ '^[0-9a-f]{64}$'
                    AND evidence.runtime_fingerprint=
                        'f39979f7a522a4db308968d3e00b3ba217b9e154a04967c329d5adfabc2b79b7'
                    AND evidence.instruction_digest=draft.instruction_digest
                    AND profile.current_version_id=version.id
                    AND (
                      (profile.status='active'
                       AND reference.state='ready'
                       AND validation.state='ready')
                      OR
                      (profile.status='unavailable'
                       AND reference.state IN ('deleting','deleted')
                       AND validation.state IN ('deleting','deleted'))
                    )
                    AND (profile.owner_id,profile.workspace_id,profile.novel_id)=
                        (command_row.owner_id,command_row.workspace_id,command_row.novel_id)
                    AND version.state='locked'
                    AND version.source_type='generated'
                    AND version.activation_basis='character_one_click_generation'
                    AND version.validation_basis='machine_validated'
                    AND version.quality_state='accepted'
                    AND version.reference_asset_id=reference.id
                    AND version.preview_asset_id=validation.id
                    AND version.model_run_id=nano_run.id
                    AND version.model_id='OpenMOSS-Team/MOSS-VoiceGenerator'
                    AND version.model_revision=
                        '97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4'
                    AND rights.source_kind='voice_generator'
                    AND rights.purpose='private_novel_narration'
                    AND rights.commercial_use IS FALSE
                    AND rights.redistribution IS FALSE
                    AND rights.voice_cloning IS FALSE
                    AND EXISTS (
                      SELECT 1 FROM voice_rights_events confirmed
                      WHERE confirmed.rights_record_id=rights.id
                        AND confirmed.event_type='confirmed'
                    )
                ) THEN
                  RAISE EXCEPTION 'VoiceGenerator result evidence closure mismatch';
                END IF;

                IF command_row.state='ready_applied' AND EXISTS (
                  SELECT 1 FROM voice_profiles profile
                  WHERE profile.id=command_row.voice_profile_id
                    AND profile.status='active'
                ) AND NOT EXISTS (
                  SELECT 1 FROM character_voice_bindings binding
                  WHERE binding.character_id=command_row.character_id
                    AND binding.novel_id=command_row.novel_id
                    AND binding.profile_id=command_row.voice_profile_id
                    AND binding.voice_version_id=command_row.voice_version_id
                    AND binding.version=command_row.applied_binding_version
                ) THEN
                  RAISE EXCEPTION 'VoiceGenerator applied binding closure mismatch';
                END IF;
              END LOOP;

              IF EXISTS (
                SELECT 1 FROM voice_profile_versions version
                WHERE version.activation_basis='character_one_click_generation'
                  AND NOT EXISTS (
                    SELECT 1 FROM voice_generator_commands command
                    WHERE command.voice_version_id=version.id
                      AND command.voice_profile_id=version.profile_id
                      AND command.state IN ('ready_applied','ready_unapplied')
                  )
              ) THEN
                RAISE EXCEPTION 'generated voice version lacks its command';
              END IF;
              RETURN NULL;
            END $$;

            CREATE CONSTRAINT TRIGGER trg_voice_generator_command_closure
            AFTER INSERT OR UPDATE ON voice_generator_commands
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION narration_check_voice_generator_closure_v1();
            CREATE CONSTRAINT TRIGGER trg_voice_generator_job_closure
            AFTER INSERT OR UPDATE ON background_jobs
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION narration_check_voice_generator_closure_v1();
            CREATE CONSTRAINT TRIGGER trg_voice_generator_model_run_closure
            AFTER INSERT OR UPDATE ON model_run_records
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION narration_check_voice_generator_closure_v1();
            CREATE CONSTRAINT TRIGGER trg_voice_generator_version_closure
            AFTER INSERT OR UPDATE ON voice_profile_versions
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION narration_check_voice_generator_closure_v1();
            CREATE CONSTRAINT TRIGGER trg_voice_generator_binding_closure
            AFTER INSERT OR UPDATE ON character_voice_bindings
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION narration_check_voice_generator_closure_v1();
            CREATE CONSTRAINT TRIGGER trg_voice_generator_media_closure
            AFTER INSERT OR UPDATE ON media_assets
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION narration_check_voice_generator_closure_v1();
            CREATE CONSTRAINT TRIGGER trg_voice_generator_profile_closure
            AFTER INSERT OR UPDATE ON voice_profiles
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION narration_check_voice_generator_closure_v1();
            """
        )
    )


def _allow_request_scoped_voice_media_deletion() -> None:
    """Fix forward the legacy 0010 guard without weakening other references."""

    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION narration_guard_media_identity()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE
              row_data jsonb;
              planned_voice_deletion boolean := false;
            BEGIN
              row_data := CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
              IF TG_OP IN ('UPDATE','DELETE') AND OLD.state='deleted'
              THEN RAISE EXCEPTION 'deleted media asset is immutable'; END IF;
              IF (row_data->>'source_revision_id') IS NOT NULL AND NOT EXISTS
                (SELECT 1 FROM document_revisions revision
                 JOIN documents document ON document.id=revision.document_id
                 WHERE revision.id=(row_data->>'source_revision_id')::uuid
                   AND document.novel_id=(row_data->>'novel_id')::uuid)
              THEN RAISE EXCEPTION 'media source revision novel mismatch'; END IF;

              IF TG_OP='UPDATE' AND (
                (OLD.state IN ('ready','quarantined') AND NEW.state='deleting') OR
                (OLD.state='deleting' AND NEW.state='deleted')
              ) AND
                (to_jsonb(OLD)-ARRAY['state','deleted_at']) =
                (to_jsonb(NEW)-ARRAY['state','deleted_at'])
              THEN
                SELECT EXISTS (
                  SELECT 1
                  FROM voice_deletion_asset_plans plan
                  JOIN voice_deletion_requests request
                    ON request.id=plan.deletion_request_id
                  WHERE plan.asset_id=OLD.id
                    AND (plan.owner_id,plan.workspace_id,plan.novel_id,
                         plan.storage_backend,plan.storage_path,plan.content_hash,
                         plan.byte_size,plan.gc_generation)
                        IS NOT DISTINCT FROM
                        (OLD.owner_id,OLD.workspace_id,OLD.novel_id,
                         OLD.storage_backend,OLD.storage_path,OLD.content_hash,
                         OLD.byte_size,OLD.gc_generation)
                    AND request.confirmed_actor IS NOT NULL
                    AND request.confirmed_at IS NOT NULL
                    AND (
                      (NEW.state='deleting'
                       AND plan.state='planned'
                       AND request.state IN ('grace_pending','requested','failed'))
                      OR
                      (NEW.state='deleted'
                       AND plan.state IN ('unlinked','finalized')
                       AND request.state IN ('live_deleting','failed'))
                    )
                ) INTO planned_voice_deletion;
              END IF;

              IF TG_OP IN ('UPDATE','DELETE') AND EXISTS
                (SELECT 1 FROM narration_render_assets render_asset
                   WHERE render_asset.asset_id=OLD.id
                 UNION ALL SELECT 1 FROM narration_exports export
                   WHERE export.asset_id=OLD.id
                 UNION ALL SELECT 1 FROM voice_profile_versions version
                   WHERE version.state='locked'
                     AND (version.reference_asset_id=OLD.id
                          OR version.preview_asset_id=OLD.id)
                 UNION ALL SELECT 1 FROM novels novel
                   WHERE novel.cover_asset_id=OLD.id)
              THEN
                IF NOT planned_voice_deletion AND (
                  TG_OP='DELETE' OR
                  (to_jsonb(OLD)-ARRAY['verified_at','last_accessed_at','validation_json']) <>
                  (to_jsonb(NEW)-ARRAY['verified_at','last_accessed_at','validation_json'])
                )
                THEN RAISE EXCEPTION 'referenced media identity is immutable'; END IF;
              END IF;
              RETURN COALESCE(NEW,OLD);
            END $$;
            """
        )
    )


def _restore_legacy_media_identity_guard() -> None:
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION narration_guard_media_identity()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE row_data jsonb; BEGIN
              row_data := CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
              IF TG_OP IN ('UPDATE','DELETE') AND OLD.state='deleted'
              THEN RAISE EXCEPTION 'deleted media asset is immutable'; END IF;
              IF (row_data->>'source_revision_id') IS NOT NULL AND NOT EXISTS
                (SELECT 1 FROM document_revisions r JOIN documents d ON d.id=r.document_id
                 WHERE r.id=(row_data->>'source_revision_id')::uuid
                   AND d.novel_id=(row_data->>'novel_id')::uuid)
              THEN RAISE EXCEPTION 'media source revision novel mismatch'; END IF;
              IF TG_OP IN ('UPDATE','DELETE') AND EXISTS
                (SELECT 1 FROM narration_render_assets ra WHERE ra.asset_id=OLD.id
                 UNION ALL SELECT 1 FROM narration_exports ex WHERE ex.asset_id=OLD.id
                 UNION ALL SELECT 1 FROM voice_profile_versions vv
                   WHERE vv.state='locked'
                     AND (vv.reference_asset_id=OLD.id OR vv.preview_asset_id=OLD.id)
                 UNION ALL SELECT 1 FROM novels n WHERE n.cover_asset_id=OLD.id)
              THEN
                IF TG_OP='DELETE' OR
                   (to_jsonb(OLD)-ARRAY['verified_at','last_accessed_at','validation_json']) <>
                   (to_jsonb(NEW)-ARRAY['verified_at','last_accessed_at','validation_json'])
                THEN RAISE EXCEPTION 'referenced media identity is immutable'; END IF;
              END IF;
              RETURN COALESCE(NEW,OLD);
            END $$;
            """
        )
    )


def upgrade() -> None:
    _replace_voice_version_constraints(allow_character_generation=True)
    _rebind_voice_generator_job(resource_class="moss-nano")
    _allow_two_phase_voice_generator_model_runs()
    _create_voice_design_drafts()
    _create_voice_generator_commands()
    _create_voice_generator_run_evidence()
    _install_guards()
    _allow_request_scoped_voice_media_deletion()
    _install_closure()


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM voice_generator_commands)
                 OR EXISTS (
                   SELECT 1 FROM voice_profile_versions
                   WHERE activation_basis='character_one_click_generation'
                 )
                 OR EXISTS (
                   SELECT 1 FROM model_run_records
                   GROUP BY attempt_id HAVING count(*) > 1
                 )
              THEN
                RAISE EXCEPTION 'VoiceGenerator downgrade refused: 0035 evidence exists';
              END IF;
            END $$;
            """
        )
    )
    _restore_legacy_media_identity_guard()
    op.execute("DROP TRIGGER trg_voice_generator_profile_closure ON voice_profiles")
    op.execute("DROP TRIGGER trg_voice_generator_media_closure ON media_assets")
    op.execute("DROP TRIGGER trg_voice_generator_binding_closure ON character_voice_bindings")
    op.execute("DROP TRIGGER trg_voice_generator_version_closure ON voice_profile_versions")
    op.execute("DROP TRIGGER trg_voice_generator_model_run_closure ON model_run_records")
    op.execute("DROP TRIGGER trg_voice_generator_job_closure ON background_jobs")
    op.execute("DROP TRIGGER trg_voice_generator_command_closure ON voice_generator_commands")
    op.execute("DROP FUNCTION narration_check_voice_generator_closure_v1()")
    op.execute("DROP TRIGGER trg_voice_generator_command_lifecycle ON voice_generator_commands")
    op.execute("DROP FUNCTION narration_guard_voice_generator_command_v1()")
    op.execute("DROP TRIGGER trg_voice_generator_run_evidence_immutable ON voice_generator_run_evidence")
    op.execute("DROP TRIGGER trg_voice_design_draft_immutable ON voice_design_drafts")
    op.execute("DROP FUNCTION narration_reject_voice_generator_immutable_v1()")
    op.drop_table("voice_generator_run_evidence")
    op.drop_index("uq_voice_generator_command_character_active", table_name="voice_generator_commands")
    op.drop_index("ix_voice_generator_commands_scope_created", table_name="voice_generator_commands")
    op.drop_table("voice_generator_commands")
    op.drop_table("voice_design_drafts")
    _restore_one_model_run_per_attempt()
    _rebind_voice_generator_job(resource_class="voice-generator")
    _replace_voice_version_constraints(allow_character_generation=False)
