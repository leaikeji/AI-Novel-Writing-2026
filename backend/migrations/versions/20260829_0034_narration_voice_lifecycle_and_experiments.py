"""Close Nano experiments and recoverable private-voice deletion lifecycle.

Revision ID: 20260829_0034
Revises: 20260829_0033

This PostgreSQL-only migration changes durable schema and database guards.  It
does not execute a model, access the network, unlink media, or schedule work.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260829_0034"
down_revision = "20260829_0033"
branch_labels = None
depends_on = None


LOCAL_OWNER = "29cf94d9-a5c9-54ec-912c-5dfff8738c4c"
LOCAL_WORKSPACE = "f0e2e632-bc99-52d2-9916-bb906aa4da6e"


def _replace_voice_version_guard(*, allow_machine_validation: bool) -> None:
    experimental_transition = """
                OR (
                  (to_jsonb(OLD)-ARRAY['state','quality_state','activation_basis',
                    'validation_basis','model_run_id','locked_actor','locked_at']) =
                  (to_jsonb(NEW)-ARRAY['state','quality_state','activation_basis',
                    'validation_basis','model_run_id','locked_actor','locked_at'])
                  AND
                  OLD.state='preview_ready' AND NEW.state='locked'
                  AND OLD.quality_state='pending' AND NEW.quality_state='accepted'
                  AND OLD.activation_basis='preview_confirmed'
                  AND NEW.activation_basis='experimental_machine_validated'
                  AND OLD.validation_basis='pending'
                  AND NEW.validation_basis='machine_validated'
                  AND OLD.model_run_id IS NULL AND NEW.model_run_id IS NOT NULL
                  AND NEW.source_type='generated'
                  AND NEW.locked_actor IS NULL AND NEW.locked_at IS NULL
                )
    """ if allow_machine_validation else ""
    machine_validation_branch = """
                OR
                (OLD.validation_basis='pending'
                 AND NEW.validation_basis='machine_validated'
                 AND NEW.activation_basis='experimental_machine_validated'
                 AND NEW.source_type='generated'
                 AND NEW.state='locked'
                 AND NEW.quality_state='accepted'
                 AND NEW.model_run_id IS NOT NULL)
    """ if allow_machine_validation else ""
    machine_locked_shape = """
                  OR
                  (NEW.activation_basis='experimental_machine_validated'
                   AND NEW.source_type='generated'
                   AND NEW.validation_basis='machine_validated'
                   AND NEW.quality_state='accepted'
                   AND NEW.model_run_id IS NOT NULL
                   AND NEW.locked_actor IS NULL AND NEW.locked_at IS NULL)
    """ if allow_machine_validation else ""
    model_run_guard = """
              IF NEW.model_run_id IS NOT NULL AND NOT (
                NEW.state='locked' AND NEW.source_type='generated'
                AND NEW.activation_basis='experimental_machine_validated'
                AND NEW.validation_basis='machine_validated'
                AND NEW.quality_state='accepted'
              ) THEN
                RAISE EXCEPTION 'voice version model run evidence is inconsistent';
              END IF;
    """ if allow_machine_validation else ""
    op.execute(
        sa.text(
            f"""
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
              IF OLD.state='preview_ready'
                 AND NEW.state='locked'
                 AND OLD.validation_basis='pending'
                 AND NEW.validation_basis='pending'
                 AND NEW.activation_basis='preview_confirmed'
                 AND OLD.quality_state='pending'
                 AND NEW.quality_state='accepted'
                 AND NEW.locked_actor IS NOT NULL
                 AND NEW.locked_at IS NOT NULL
              THEN
                NEW.validation_basis := 'human_accepted';
              END IF;
              IF NOT (
                (to_jsonb(OLD)-ARRAY['state','quality_state','validation_basis',
                    'locked_actor','locked_at']) =
                (to_jsonb(NEW)-ARRAY['state','quality_state','validation_basis',
                    'locked_actor','locked_at'])
                {experimental_transition}
              ) THEN
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
              IF OLD.validation_basis<>NEW.validation_basis AND NOT (
                (OLD.validation_basis='pending'
                 AND NEW.validation_basis='human_accepted'
                 AND NEW.activation_basis='preview_confirmed'
                 AND NEW.state='locked'
                 AND NEW.quality_state='accepted')
                {machine_validation_branch}
              ) THEN
                RAISE EXCEPTION 'invalid voice validation transition';
              END IF;
              IF NEW.state='locked' THEN
                IF NOT (
                  (NEW.activation_basis='preview_confirmed'
                   AND NEW.validation_basis='human_accepted'
                   AND NEW.quality_state='accepted'
                   AND NEW.locked_actor IS NOT NULL AND NEW.locked_at IS NOT NULL)
                  OR
                  (NEW.activation_basis='explicit_official_preset_selection'
                   AND NEW.source_type='preset'
                   AND NEW.validation_basis='not_required'
                   AND NEW.quality_state='pending'
                   AND NEW.locked_actor IS NULL AND NEW.locked_at IS NULL)
                  {machine_locked_shape}
                ) THEN
                  RAISE EXCEPTION 'locked voice activation evidence is inconsistent';
                END IF;
              ELSIF NEW.activation_basis<>'preview_confirmed'
                 OR NEW.validation_basis<>'pending'
                 OR NEW.locked_actor IS NOT NULL OR NEW.locked_at IS NOT NULL
              THEN
                RAISE EXCEPTION 'unlocked voice version carries activation evidence';
              END IF;
              {model_run_guard}
              IF NEW.quality_state='rejected' AND NEW.state<>'unavailable' THEN
                RAISE EXCEPTION 'rejected voice quality requires unavailable state';
              END IF;
              RETURN NEW;
            END $$;
            """
        )
    )


def _create_experiment_table() -> None:
    op.create_table(
        "nano_voice_experiment_commands",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("preview_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("background_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("base_preset_id", sa.String(160), nullable=False),
        sa.Column("target_kind", sa.String(16), nullable=False),
        sa.Column("target_character_id", postgresql.UUID(as_uuid=True)),
        sa.Column("expected_settings_version", sa.BigInteger(), nullable=False),
        sa.Column("expected_binding_version", sa.BigInteger()),
        sa.Column("applied_settings_version", sa.BigInteger()),
        sa.Column("applied_binding_version", sa.BigInteger()),
        sa.Column(
            "parameters_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("parameters_digest", sa.String(64), nullable=False),
        sa.Column("input_digest_key_id", sa.String(80), nullable=False),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("state", sa.String(24), nullable=False, server_default="pending"),
        sa.Column(
            "reused_version", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("failure_code", sa.String(96)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["novel_id", "owner_id", "workspace_id"],
            ["novels.id", "novels.owner_id", "novels.workspace_id"],
            name="fk_nano_voice_experiment_novel_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["voice_profiles.id"],
            name="fk_nano_voice_experiment_profile",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["version_id", "profile_id"],
            ["voice_profile_versions.id", "voice_profile_versions.profile_id"],
            name="fk_nano_voice_experiment_version_profile",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["preview_id"],
            ["voice_previews.id"],
            name="fk_nano_voice_experiment_preview",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["background_job_id", "owner_id", "workspace_id", "novel_id"],
            [
                "background_jobs.id",
                "background_jobs.owner_id",
                "background_jobs.workspace_id",
                "background_jobs.novel_id",
            ],
            name="fk_nano_voice_experiment_job_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_character_id", "novel_id"],
            ["novel_characters.id", "novel_characters.novel_id"],
            name="fk_nano_voice_experiment_character_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "owner_id",
            "workspace_id",
            "idempotency_key",
            name="uq_nano_voice_experiment_idempotency",
        ),
        sa.CheckConstraint(
            f"owner_id='{LOCAL_OWNER}'::uuid AND "
            f"workspace_id='{LOCAL_WORKSPACE}'::uuid",
            name="ck_nano_voice_experiment_fixed_local_scope",
        ),
        sa.CheckConstraint(
            "target_kind IN ('narrator','character')",
            name="ck_nano_voice_experiment_target_kind",
        ),
        sa.CheckConstraint(
            "(target_kind='narrator' AND target_character_id IS NULL "
            "AND expected_binding_version IS NULL) OR "
            "(target_kind='character' AND target_character_id IS NOT NULL "
            "AND expected_binding_version IS NOT NULL AND expected_binding_version>=0)",
            name="ck_nano_voice_experiment_target_shape",
        ),
        sa.CheckConstraint(
            "expected_settings_version>=0",
            name="ck_nano_voice_experiment_expected_settings_version",
        ),
        sa.CheckConstraint(
            "base_preset_id ~ '^onnx\\.[A-Za-z][A-Za-z0-9]{0,79}$'",
            name="ck_nano_voice_experiment_preset_id",
        ),
        sa.CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$'",
            name="ck_nano_voice_experiment_idempotency_key",
        ),
        sa.CheckConstraint(
            "request_hash ~ '^[0-9a-f]{64}$' "
            "AND parameters_digest ~ '^[0-9a-f]{64}$' "
            "AND input_digest ~ '^[0-9a-f]{64}$' "
            "AND fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_nano_voice_experiment_digests",
        ),
        sa.CheckConstraint(
            "input_digest_key_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$'",
            name="ck_nano_voice_experiment_digest_key",
        ),
        sa.CheckConstraint(
            "parameters_json ?& ARRAY['schema_version','seed',"
            "'text_temperature_milli','text_top_p_milli','text_top_k',"
            "'audio_temperature_milli','audio_top_p_milli','audio_top_k',"
            "'audio_repetition_penalty_milli','sample_mode','max_new_frames'] "
            "AND parameters_json->>'schema_version'='nano-decode-parameters/3' "
            "AND parameters_json->>'sample_mode'='full' "
            "AND parameters_json->>'max_new_frames'='375'",
            name="ck_nano_voice_experiment_parameters_shape",
        ),
        sa.CheckConstraint(
            "state IN ('pending','running','ready_applied','ready_unapplied','failed')",
            name="ck_nano_voice_experiment_state",
        ),
        sa.CheckConstraint(
            "(state='pending' AND started_at IS NULL AND completed_at IS NULL "
            "AND applied_at IS NULL AND failure_code IS NULL "
            "AND created_at<=updated_at) OR "
            "(state='running' AND started_at IS NOT NULL AND started_at>=created_at "
            "AND completed_at IS NULL AND applied_at IS NULL AND failure_code IS NULL "
            "AND updated_at>=started_at) OR "
            "(state='ready_applied' AND started_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND completed_at>=started_at AND applied_at IS NOT NULL "
            "AND applied_at>=completed_at AND updated_at>=applied_at "
            "AND failure_code IS NULL) OR "
            "(state='ready_unapplied' AND started_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND completed_at>=started_at AND applied_at IS NULL "
            "AND updated_at>=completed_at AND failure_code IS NULL) OR "
            "(state='failed' AND started_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND completed_at>=started_at AND applied_at IS NULL "
            "AND updated_at>=completed_at AND failure_code IN ("
            "'NANO_EXPERIMENT_MODEL_UNAVAILABLE','NANO_EXPERIMENT_SYNTHESIS_FAILED',"
            "'NANO_EXPERIMENT_AUDIO_INVALID','NANO_EXPERIMENT_MODEL_IDENTITY_MISMATCH',"
            "'NANO_EXPERIMENT_PARAMETERS_MISMATCH','NANO_EXPERIMENT_OUTPUT_HASH_MISMATCH',"
            "'NANO_EXPERIMENT_DATABASE_FAILED'))",
            name="ck_nano_voice_experiment_lifecycle",
        ),
        sa.CheckConstraint(
            "(state<>'ready_applied' AND applied_settings_version IS NULL "
            "AND applied_binding_version IS NULL) OR "
            "(state='ready_applied' AND applied_settings_version IS NOT NULL "
            "AND applied_settings_version>0 AND "
            "((target_kind='narrator' AND applied_binding_version IS NULL) OR "
            "(target_kind='character' AND applied_binding_version IS NOT NULL "
            "AND applied_binding_version>0)))",
            name="ck_nano_voice_experiment_applied_versions",
        ),
    )
    op.create_index(
        "ix_nano_voice_experiments_scope_created",
        "nano_voice_experiment_commands",
        ["owner_id", "workspace_id", "novel_id", "created_at"],
    )
    op.create_index(
        "ix_nano_voice_experiments_state",
        "nano_voice_experiment_commands",
        ["state", "updated_at"],
    )


def _install_experiment_guards() -> None:
    op.execute(
        sa.text(
            """
            CREATE FUNCTION narration_guard_nano_voice_experiment_v1()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF TG_OP='INSERT' THEN
                IF NEW.state<>'pending' THEN
                  RAISE EXCEPTION 'Nano experiment must be inserted pending';
                END IF;
                RETURN NEW;
              END IF;
              IF TG_OP='DELETE' THEN
                RAISE EXCEPTION 'Nano experiment evidence cannot be deleted';
              END IF;
              IF OLD.state IN ('ready_applied','failed') THEN
                RAISE EXCEPTION 'terminal Nano experiment is immutable';
              END IF;
              IF OLD.state='ready_unapplied' AND NEW.state<>'ready_applied' THEN
                RAISE EXCEPTION 'ready unapplied Nano experiment only permits CAS apply';
              END IF;
              IF (to_jsonb(OLD)-ARRAY['state','reused_version','applied_settings_version',
                    'applied_binding_version','failure_code','started_at',
                    'completed_at','applied_at','updated_at']) <>
                 (to_jsonb(NEW)-ARRAY['state','reused_version','applied_settings_version',
                    'applied_binding_version','failure_code','started_at',
                    'completed_at','applied_at','updated_at'])
              THEN
                RAISE EXCEPTION 'Nano experiment canonical request is immutable';
              END IF;
              IF NEW.updated_at<OLD.updated_at
                 OR (OLD.started_at IS NOT NULL AND NEW.started_at IS DISTINCT FROM OLD.started_at)
                 OR (OLD.completed_at IS NOT NULL AND NEW.completed_at IS DISTINCT FROM OLD.completed_at)
                 OR (OLD.applied_at IS NOT NULL AND NEW.applied_at IS DISTINCT FROM OLD.applied_at)
              THEN
                RAISE EXCEPTION 'Nano experiment timestamps are monotonic and write-once';
              END IF;
              IF OLD.reused_version IS DISTINCT FROM NEW.reused_version AND NOT (
                OLD.reused_version IS FALSE AND NEW.reused_version IS TRUE
                AND OLD.state='running'
                AND NEW.state IN ('ready_applied','ready_unapplied')
              ) THEN
                RAISE EXCEPTION 'Nano experiment reuse evidence is write-once';
              END IF;
              IF OLD.state<>NEW.state AND NOT (
                (OLD.state='pending' AND NEW.state='running') OR
                (OLD.state='running' AND NEW.state IN
                  ('ready_applied','ready_unapplied','failed')) OR
                (OLD.state='ready_unapplied' AND NEW.state='ready_applied')
              ) THEN
                RAISE EXCEPTION 'invalid Nano experiment state transition';
              END IF;
              RETURN NEW;
            END $$;

            CREATE TRIGGER trg_nano_voice_experiment_lifecycle
            BEFORE INSERT OR UPDATE OR DELETE ON nano_voice_experiment_commands
            FOR EACH ROW EXECUTE FUNCTION narration_guard_nano_voice_experiment_v1();

            CREATE FUNCTION narration_guard_experiment_model_run_immutable_v1()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF EXISTS (
                SELECT 1 FROM voice_profile_versions version
                JOIN nano_voice_experiment_commands command
                  ON command.version_id=version.id
                WHERE version.model_run_id=OLD.id
              ) THEN
                RAISE EXCEPTION 'Nano experiment ModelRun evidence is immutable';
              END IF;
              RETURN OLD;
            END $$;

            CREATE TRIGGER trg_nano_voice_experiment_model_run_immutable
            BEFORE UPDATE OR DELETE ON model_run_records
            FOR EACH ROW
            EXECUTE FUNCTION narration_guard_experiment_model_run_immutable_v1();

            CREATE FUNCTION narration_check_nano_voice_experiment_closure_v1()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE command_row nano_voice_experiment_commands%ROWTYPE;
            BEGIN
              FOR command_row IN
                SELECT command.* FROM nano_voice_experiment_commands command
                WHERE
                  (TG_TABLE_NAME='nano_voice_experiment_commands' AND command.id=NEW.id)
                  OR (TG_TABLE_NAME='voice_previews' AND command.preview_id=NEW.id)
                  OR (TG_TABLE_NAME='background_jobs' AND command.background_job_id=NEW.id)
                  OR (TG_TABLE_NAME='voice_profile_versions' AND command.version_id=NEW.id)
                  OR (TG_TABLE_NAME='model_run_records' AND EXISTS (
                    SELECT 1 FROM voice_profile_versions version
                    WHERE version.id=command.version_id
                      AND version.model_run_id=NEW.id
                  ))
              LOOP
                IF NOT EXISTS (
                  SELECT 1
                  FROM voice_profiles profile
                  JOIN voice_profile_versions version
                    ON version.id=command_row.version_id
                   AND version.profile_id=profile.id
                  JOIN voice_previews preview
                    ON preview.id=command_row.preview_id
                   AND preview.profile_id=profile.id
                   AND preview.version_id=version.id
                  JOIN background_jobs job
                    ON job.id=command_row.background_job_id
                  JOIN background_jobs source_job
                    ON source_job.id=preview.job_id
                  WHERE profile.id=command_row.profile_id
                    AND (profile.owner_id,profile.workspace_id,profile.novel_id)=
                        (command_row.owner_id,command_row.workspace_id,command_row.novel_id)
                    AND (version.owner_id,version.workspace_id)=
                        (command_row.owner_id,command_row.workspace_id)
                    AND (preview.owner_id,preview.workspace_id,preview.novel_id)=
                        (command_row.owner_id,command_row.workspace_id,command_row.novel_id)
                    AND (job.owner_id,job.workspace_id,job.novel_id)=
                        (command_row.owner_id,command_row.workspace_id,command_row.novel_id)
                    AND (source_job.owner_id,source_job.workspace_id,source_job.novel_id)=
                        (command_row.owner_id,command_row.workspace_id,command_row.novel_id)
                    AND version.source_type='generated'
                    AND version.preset_key=command_row.base_preset_id
                    AND version.fingerprint=command_row.fingerprint
                    AND version.seed=(command_row.parameters_json->>'seed')::bigint
                    AND preview.parameters_fingerprint=command_row.parameters_digest
                    AND preview.preview_text_digest_key_id=command_row.input_digest_key_id
                    AND preview.preview_text_digest=command_row.input_digest
                    AND preview.request_fingerprint=command_row.fingerprint
                    AND preview.model_fingerprint=
                        '3c76f3e9e1381699c5555287cf66eeb023632d0c3ee94adc6d8ae1b1d455fd7d'
                    AND preview.reference_fingerprint=
                        version.parameters_json#>>'{{official_preset,provenance_fingerprint_sha256}}'
                    AND job.job_kind='narration.voice_preview'
                    AND job.resource_class='moss-nano'
                    AND job.request_id IS NULL
                    AND source_job.job_kind='narration.voice_preview'
                    AND source_job.resource_class='moss-nano'
                    AND source_job.request_id IS NULL
                    AND (
                      (command_row.reused_version IS FALSE
                       AND job.id=source_job.id
                       AND ((command_row.state='pending'
                             AND preview.status='queued'
                             AND job.state IN ('queued','running','retry_wait','cancel_requested'))
                            OR (command_row.state='running'
                             AND preview.status IN ('queued','running')
                             AND job.state IN ('queued','running','retry_wait','cancel_requested')))) OR
                      (command_row.reused_version IS FALSE
                       AND job.id<>source_job.id
                       AND command_row.state IN ('pending','running')
                       AND preview.status='ready' AND source_job.state='succeeded'
                       AND job.state IN ('queued','running','retry_wait','cancel_requested')
                       AND version.state='locked'
                       AND version.activation_basis='experimental_machine_validated'
                       AND version.validation_basis='machine_validated'
                       AND version.quality_state='accepted'
                       AND version.model_run_id IS NOT NULL
                       AND EXISTS (
                         SELECT 1 FROM model_run_records source_run
                         JOIN background_job_attempts source_attempt
                           ON source_attempt.id=source_run.attempt_id
                         WHERE source_run.id=version.model_run_id
                           AND source_attempt.job_id=source_job.id
                           AND source_run.result_classification='success')) OR
                      (command_row.state IN ('ready_applied','ready_unapplied')
                       AND preview.status='ready' AND source_job.state='succeeded'
                       AND job.state='succeeded'
                       AND ((command_row.reused_version IS FALSE AND job.id=source_job.id)
                            OR (command_row.reused_version IS TRUE AND job.id<>source_job.id))
                       AND version.state='locked'
                       AND version.activation_basis='experimental_machine_validated'
                       AND version.validation_basis='machine_validated'
                       AND version.quality_state='accepted'
                       AND version.model_run_id IS NOT NULL
                       AND EXISTS (
                         SELECT 1
                         FROM model_run_records run
                         JOIN background_job_attempts attempt
                           ON attempt.id=run.attempt_id
                         WHERE run.id=version.model_run_id
                           AND attempt.job_id=source_job.id
                           AND run.result_classification='success'
                           AND run.parameters_digest=command_row.parameters_digest
                           AND run.requested_provider_id='local-sidecar'
                           AND run.requested_model_id=
                               'OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX+MOSS-Audio-Tokenizer-Nano-ONNX'
                           AND run.requested_revision=
                               'f52645cb467506d8e18e746ddd59482685b74e58+ceff0d0749bfb3fa2d61149794ec6feef0d1e1ae'
                           AND run.actual_provider_id='local-sidecar'
                           AND run.actual_model_id=
                               'OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX+MOSS-Audio-Tokenizer-Nano-ONNX'
                           AND run.actual_revision=
                               'f52645cb467506d8e18e746ddd59482685b74e58+ceff0d0749bfb3fa2d61149794ec6feef0d1e1ae'
                           AND run.model_fingerprint=
                               '3c76f3e9e1381699c5555287cf66eeb023632d0c3ee94adc6d8ae1b1d455fd7d'
                           AND run.output_digest=(
                             SELECT asset.content_hash FROM media_assets asset
                             WHERE asset.id=preview.result_asset_id
                           )
                           AND run.duration_ms=(
                             SELECT asset.duration_ms FROM media_assets asset
                             WHERE asset.id=preview.result_asset_id
                           )
                       )) OR
                      (command_row.state='failed'
                       AND job.state IN ('failed','dead_letter','cancelled')
                       AND ((job.id=source_job.id
                             AND preview.status IN ('failed','cancelled'))
                            OR (job.id<>source_job.id
                                AND preview.status='ready'
                                AND source_job.state='succeeded'
                                AND version.state='locked'
                                AND version.activation_basis='experimental_machine_validated'
                                AND version.validation_basis='machine_validated'
                                AND version.quality_state='accepted'
                                AND version.model_run_id IS NOT NULL)))
                    )
                ) THEN
                  RAISE EXCEPTION 'Nano experiment resource closure mismatch';
                END IF;
              END LOOP;
              RETURN NULL;
            END $$;

            CREATE CONSTRAINT TRIGGER trg_nano_voice_experiment_closure
            AFTER INSERT OR UPDATE ON nano_voice_experiment_commands
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION narration_check_nano_voice_experiment_closure_v1();

            CREATE CONSTRAINT TRIGGER trg_nano_voice_experiment_preview_closure
            AFTER INSERT OR UPDATE ON voice_previews
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION narration_check_nano_voice_experiment_closure_v1();

            CREATE CONSTRAINT TRIGGER trg_nano_voice_experiment_job_closure
            AFTER INSERT OR UPDATE ON background_jobs
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION narration_check_nano_voice_experiment_closure_v1();

            CREATE CONSTRAINT TRIGGER trg_nano_voice_experiment_version_closure
            AFTER INSERT OR UPDATE ON voice_profile_versions
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION narration_check_nano_voice_experiment_closure_v1();

            CREATE CONSTRAINT TRIGGER trg_nano_voice_experiment_model_run_closure
            AFTER INSERT OR UPDATE ON model_run_records
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION narration_check_nano_voice_experiment_closure_v1();
            """
        )
    )


def _install_preview_scope(*, allow_generated: bool) -> None:
    generated_branch = """
                    OR (
                      v.source_type='generated'
                      AND r.source_kind='official_preset'
                      AND r.commercial_use IS FALSE
                      AND r.redistribution IS FALSE
                      AND preview_row.reference_asset_id IS NULL
                      AND v.reference_asset_id IS NULL
                      AND l.id IS NULL AND reference.id IS NULL
                      AND v.parameters_json->>'schema_version'=
                          'narration-nano-experiment-version/1'
                      AND v.parameters_json->>'sample_mode'='full'
                      AND v.parameters_json->>'max_new_frames'='375'
                      AND EXISTS (
                        SELECT 1 FROM nano_voice_experiment_commands command
                        WHERE command.profile_id=v.profile_id
                          AND command.version_id=v.id
                          AND command.preview_id=preview_row.id
                          AND command.background_job_id=preview_row.job_id
                          AND command.base_preset_id=v.preset_key
                          AND command.parameters_json=v.parameters_json->'decode_parameters'
                          AND command.parameters_digest=preview_row.parameters_fingerprint
                          AND command.fingerprint=v.fingerprint
                      )
                    )
    """ if allow_generated else ""
    op.execute(
        sa.text(
            f"""
            CREATE OR REPLACE FUNCTION narration_guard_voice_preview_scope_v1()
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
                JOIN background_jobs j ON j.id=preview_row.job_id
                LEFT JOIN voice_reference_asset_links l
                  ON l.voice_version_id=v.id AND l.profile_id=p.id
                LEFT JOIN media_assets reference
                  ON reference.id=preview_row.reference_asset_id
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
                  AND (r.owner_id,r.workspace_id,r.novel_id) IS NOT DISTINCT FROM
                      (preview_row.owner_id,preview_row.workspace_id,preview_row.novel_id)
                  AND r.purpose='private_novel_narration'
                  AND (r.expires_at IS NULL OR r.expires_at>CURRENT_TIMESTAMP)
                  AND EXISTS (
                    SELECT 1 FROM voice_rights_events confirmed
                    WHERE confirmed.rights_record_id=r.id
                      AND confirmed.event_type='confirmed'
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM voice_rights_events event
                    WHERE event.rights_record_id=r.id
                      AND event.event_type IN ('revoked','expired','review_blocked')
                  )
                  AND (
                    (
                      v.source_type='uploaded'
                      AND r.source_kind='user_upload'
                      AND r.voice_cloning IS TRUE
                      AND preview_row.reference_asset_id IS NOT NULL
                      AND v.reference_asset_id=preview_row.reference_asset_id
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
                    ) OR (
                      v.source_type='preset'
                      AND r.source_kind='official_preset'
                      AND r.commercial_use IS FALSE
                      AND r.redistribution IS FALSE
                      AND preview_row.reference_asset_id IS NULL
                      AND v.reference_asset_id IS NULL
                      AND l.id IS NULL AND reference.id IS NULL
                      AND v.parameters_json->>'schema_version'=
                          'narration-official-preset-version/1.0'
                    )
                    {generated_branch}
                  )
                  AND v.provider_id='local-sidecar'
                  AND v.model_id='OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX'
                  AND v.model_revision='f52645cb467506d8e18e746ddd59482685b74e58'
                  AND v.preset_key=v.parameters_json#>>'{{official_preset,preset_id}}'
                  AND v.preset_key='onnx.' ||
                      (v.parameters_json#>>'{{official_preset,manifest_voice}}')
                  AND v.parameters_json#>>'{{official_preset,schema_version}}'=
                      'moss-tts-official-preset-provenance/1.0'
                  AND v.parameters_json#>>'{{official_preset,repository}}'=
                      'OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX'
                  AND v.parameters_json#>>'{{official_preset,revision}}'=
                      'f52645cb467506d8e18e746ddd59482685b74e58'
                  AND v.parameters_json#>>'{{official_preset,manifest_path}}'=
                      'browser_poc_manifest.json'
                  AND v.parameters_json#>>'{{official_preset,manifest_sha256}}'=
                      '097d80e993dc29f0bae427590b4f77084a161cb578b50d82c29f455d5faa9eee'
                  AND v.parameters_json#>>'{{official_preset,model_fingerprint_sha256}}'=
                      '3c76f3e9e1381699c5555287cf66eeb023632d0c3ee94adc6d8ae1b1d455fd7d'
                  AND v.parameters_json#>>'{{official_preset,prompt_codes_sha256}}'
                      ~ '^[0-9a-f]{{64}}$'
                  AND (v.parameters_json#>>'{{official_preset,prompt_frame_count}}')
                      ~ '^[1-9][0-9]*$'
                  AND (
                    v.preset_key,
                    v.parameters_json#>>'{{official_preset,prompt_codes_sha256}}',
                    (v.parameters_json#>>'{{official_preset,prompt_frame_count}}')::integer
                  ) IN (VALUES
                    ('onnx.Junhao','395976042d458c44977c43b9b20a9945100cbf0302381e5d25e46b43304aa6d4',98),
                    ('onnx.Zhiming','6574897aab814be3b155f073683e4f19a3e5f1ab92ddfa66bec5b7911cf4099e',98),
                    ('onnx.Weiguo','cbfa9212b4f8ec64172f7057c92dc8ec9a1731530b012bd9dfb3b1e297624ee6',140),
                    ('onnx.Xiaoyu','847277bcef201396ef1aa6adbc8e55a25c9b0b8e3cfa3c72ac306053224022be',180),
                    ('onnx.Yuewen','bed66ac01188f639b18f1a8cfd1520d6fbf0c319d27c282b1dc1cd3e9a8a888f',102),
                    ('onnx.Lingyu','761b4a0b0c3e0cec067c76b9a21560d8c8b0e302f67e16f0bf090e288c6fb3b0',218),
                    ('onnx.Trump','3055948dd0646a7d1a72de824d33ab069ca3a2a5489a78f22818314a3d2e9d27',97),
                    ('onnx.Ava','892a532b562d79fe683640e98f2e061683e4ea7bc93929d0866a1f5dae30ba48',98),
                    ('onnx.Bella','d4def268888ebb0575d3bb8b1428bdea252af26e68281c43218432ddc9b0cda4',59),
                    ('onnx.Adam','14ffba3b57fdd50e16f431ba6631bf9b26d4c8ae1ec671ab73c1dea61e2835b7',59),
                    ('onnx.Nathan','3e4bdb8ba9884ebf028efafb1535af784bb792a2695a25e571abc0a9cd18072e',168),
                    ('onnx.Soyo','d2079895cc7f2ec931a983e8f16150cc322c37bf0b62135507126736ee70e4e1',125),
                    ('onnx.Saki','85f916c338c1a26f5e91b90b71f7942bfb3c465e999d97a12b24644258de18bd',32),
                    ('onnx.Mortis','9976030044c8746d488fa1cdf470e43760429bf73113819f9da15784bf4d4449',60),
                    ('onnx.Umiri','72bdf9fb4dfcd4405ec216030a73bf004856b6cf66b100c040fe36bea6165d43',77),
                    ('onnx.Mei','2068325ad43d3589bcffcb2f8a969eb7ff6570de4736aa3221553537c6232b1a',49),
                    ('onnx.Anon','566b5098c19390f178cba0e1d16961ff45a225677adbb6f0bc2315c20954a5ee',47),
                    ('onnx.Arisa','2cf65c28e3bb62c93195a1d0778578d10c0ef71a42a66dcbe613592efb17dd5f',85)
                  )
                  AND v.parameters_json#>>'{{official_preset,prompt_quantizer_count}}'='16'
                  AND v.parameters_json#>>'{{official_preset,provenance_fingerprint_sha256}}'
                      ~ '^[0-9a-f]{{64}}$'
                  AND (j.owner_id,j.workspace_id,j.novel_id) IS NOT DISTINCT FROM
                      (preview_row.owner_id,preview_row.workspace_id,preview_row.novel_id)
                  AND j.job_kind='narration.voice_preview'
                  AND j.resource_class='moss-nano'
                  AND j.request_id IS NULL
                  AND (
                    (preview_row.status='queued' AND j.state IN
                      ('queued','running','retry_wait','cancel_requested')) OR
                    (preview_row.status='running' AND j.state IN
                      ('queued','running','retry_wait','cancel_requested')) OR
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
            """
        )
    )


def _install_voice_preview_job_closure(*, allow_nano_reuse: bool) -> None:
    """Keep the 0023 one-preview-per-job rule, with one exact reuse exception.

    A Nano experiment that reuses an already machine-validated Version owns a
    fresh BackgroundJob but deliberately points at the immutable source
    VoicePreview.  The exception below proves the full source
    Preview/Job/ModelRun/Asset closure; ordinary preview jobs still require
    their own direct VoicePreview exactly as before.
    """

    nano_reuse_branch = """
                  OR EXISTS (
                    SELECT 1
                    FROM nano_voice_experiment_commands command
                    JOIN voice_profiles profile
                      ON profile.id=command.profile_id
                    JOIN voice_profile_versions version
                      ON version.id=command.version_id
                     AND version.profile_id=profile.id
                    JOIN voice_previews source_preview
                      ON source_preview.id=command.preview_id
                     AND source_preview.profile_id=profile.id
                     AND source_preview.version_id=version.id
                    JOIN background_jobs source_job
                      ON source_job.id=source_preview.job_id
                    JOIN model_run_records source_run
                      ON source_run.id=version.model_run_id
                    JOIN background_job_attempts source_attempt
                      ON source_attempt.id=source_run.attempt_id
                    JOIN media_assets source_asset
                      ON source_asset.id=source_preview.result_asset_id
                    WHERE command.background_job_id=job_row.id
                      AND source_preview.job_id<>job_row.id
                      AND (command.owner_id,command.workspace_id,command.novel_id)=
                          (job_row.owner_id,job_row.workspace_id,job_row.novel_id)
                      AND (profile.owner_id,profile.workspace_id,profile.novel_id)=
                          (job_row.owner_id,job_row.workspace_id,job_row.novel_id)
                      AND (version.owner_id,version.workspace_id)=
                          (job_row.owner_id,job_row.workspace_id)
                      AND (source_preview.owner_id,source_preview.workspace_id,
                           source_preview.novel_id)=
                          (job_row.owner_id,job_row.workspace_id,job_row.novel_id)
                      AND (source_job.owner_id,source_job.workspace_id,
                           source_job.novel_id)=
                          (job_row.owner_id,job_row.workspace_id,job_row.novel_id)
                      AND source_preview.status='ready'
                      AND source_job.state='succeeded'
                      AND source_job.job_kind='narration.voice_preview'
                      AND source_job.resource_class='moss-nano'
                      AND source_job.request_id IS NULL
                      AND version.state='locked'
                      AND version.source_type='generated'
                      AND version.activation_basis='experimental_machine_validated'
                      AND version.validation_basis='machine_validated'
                      AND version.quality_state='accepted'
                      AND source_attempt.job_id=source_job.id
                      AND source_run.result_classification='success'
                      AND source_run.parameters_digest=command.parameters_digest
                      AND source_run.model_fingerprint=
                          '3c76f3e9e1381699c5555287cf66eeb023632d0c3ee94adc6d8ae1b1d455fd7d'
                      AND source_run.output_digest=source_asset.content_hash
                      AND source_run.duration_ms=source_asset.duration_ms
                      AND source_asset.state='ready'
                      AND source_asset.kind='narration_voice_preview'
                      AND source_asset.asset_class='preview'
                      AND (
                        (command.state='pending'
                         AND command.reused_version IS FALSE
                         AND job_row.state IN
                           ('queued','running','retry_wait','cancel_requested')) OR
                        (command.state='running'
                         AND command.reused_version IS FALSE
                         AND job_row.state IN
                           ('queued','running','retry_wait','cancel_requested')) OR
                        (command.state IN ('ready_applied','ready_unapplied')
                         AND command.reused_version IS TRUE
                         AND job_row.state='succeeded') OR
                        (command.state='failed'
                         AND command.reused_version IS FALSE
                         AND job_row.state IN ('failed','dead_letter','cancelled'))
                      )
                  )
    """ if allow_nano_reuse else ""
    op.execute(
        sa.text(
            f"""
            CREATE OR REPLACE FUNCTION narration_guard_voice_preview_job_closure_v1()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE job_row background_jobs%ROWTYPE;
            BEGIN
              SELECT * INTO job_row FROM background_jobs WHERE id=NEW.id;
              IF NOT FOUND OR job_row.job_kind<>'narration.voice_preview' THEN
                RETURN NULL;
              END IF;
              IF NOT (
                EXISTS (
                  SELECT 1 FROM voice_previews preview
                  WHERE preview.job_id=job_row.id
                    AND (preview.owner_id,preview.workspace_id,preview.novel_id)
                        IS NOT DISTINCT FROM
                        (job_row.owner_id,job_row.workspace_id,job_row.novel_id)
                    AND (
                      (preview.status='queued' AND job_row.state IN
                        ('queued','running','retry_wait','cancel_requested')) OR
                      (preview.status='running' AND job_row.state IN
                        ('queued','running','retry_wait','cancel_requested')) OR
                      (preview.status='ready' AND job_row.state='succeeded') OR
                      (preview.status='failed' AND job_row.state IN
                        ('failed','dead_letter')) OR
                      (preview.status='cancelled' AND job_row.state='cancelled')
                    )
                )
                {nano_reuse_branch}
              ) THEN
                RAISE EXCEPTION
                  'voice preview job requires one coherent preview record';
              END IF;
              RETURN NULL;
            END $$;
            """
        )
    )


def _upgrade_deletion_lifecycle() -> None:
    for name in (
        "superseded_at",
        "job_drain_started_at",
        "job_drain_deadline",
    ):
        op.add_column(
            "voice_deletion_requests",
            sa.Column(name, sa.DateTime(timezone=True)),
        )
    op.drop_constraint(
        "ck_voice_deletion_request_state",
        "voice_deletion_requests",
        type_="check",
    )
    op.create_check_constraint(
        "ck_voice_deletion_request_state",
        "voice_deletion_requests",
        "state IN ('grace_pending','requested','cancelled','live_deleting',"
        "'live_deleted_backup_pending','completed','failed','superseded')",
    )
    op.create_check_constraint(
        "ck_voice_deletion_request_superseded_shape",
        "voice_deletion_requests",
        "(state='superseded' AND superseded_at IS NOT NULL "
        "AND failure_code IN ('VOICE_DELETE_PROFILE_CHANGED',"
        "'VOICE_DELETE_IMPACT_CHANGED','VOICE_DELETE_IMPACT_EXPIRED',"
        "'VOICE_DELETE_JOB_DRAIN_TIMEOUT')) OR "
        "(state<>'superseded' AND superseded_at IS NULL)",
    )
    op.create_check_constraint(
        "ck_voice_deletion_request_job_drain_shape",
        "voice_deletion_requests",
        "(job_drain_started_at IS NULL AND job_drain_deadline IS NULL) OR "
        "(job_drain_started_at IS NOT NULL AND job_drain_deadline IS NOT NULL "
        "AND job_drain_deadline>job_drain_started_at)",
    )
    op.create_check_constraint(
        "ck_voice_deletion_request_failure_shape",
        "voice_deletion_requests",
        "(state='failed' AND failure_code IN ("
        "'VOICE_DELETE_WAITING_FOR_JOBS','VOICE_DELETE_UNLINK_FAILED',"
        "'VOICE_DELETE_STORAGE_TEMPORARY','VOICE_DELETE_FINALIZE_FAILED',"
        "'VOICE_DELETE_SCOPE_INVALID','VOICE_DELETE_FILE_IDENTITY_INVALID',"
        "'VOICE_DELETE_ASSET_PLAN_INVALID')) OR "
        "(state='superseded' AND failure_code IN ("
        "'VOICE_DELETE_PROFILE_CHANGED','VOICE_DELETE_IMPACT_CHANGED',"
        "'VOICE_DELETE_IMPACT_EXPIRED','VOICE_DELETE_JOB_DRAIN_TIMEOUT')) OR "
        "(state NOT IN ('failed','superseded') AND failure_code IS NULL)",
    )
    op.drop_index(
        "uq_voice_deletion_requests_idempotency",
        table_name="voice_deletion_requests",
    )
    op.create_index(
        "uq_voice_deletion_requests_idempotency",
        "voice_deletion_requests",
        ["owner_id", "workspace_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.drop_index(
        "uq_voice_deletion_requests_active_profile",
        table_name="voice_deletion_requests",
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
        sa.text(
            """
            CREATE OR REPLACE FUNCTION narration_guard_voice_deletion()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF TG_OP='INSERT' THEN
                IF NEW.state NOT IN ('grace_pending','requested')
                   OR NEW.confirmed_actor IS NOT NULL OR NEW.confirmed_at IS NOT NULL
                   OR NEW.superseded_at IS NOT NULL
                   OR NEW.job_drain_started_at IS NOT NULL
                   OR NEW.job_drain_deadline IS NOT NULL
                   OR NEW.failure_code IS NOT NULL
                   OR NEW.cancelled_actor IS NOT NULL
                   OR NEW.cancelled_at IS NOT NULL
                   OR NEW.completed_at IS NOT NULL
                THEN RAISE EXCEPTION 'voice deletion must be inserted unconfirmed/pending'; END IF;
                RETURN NEW;
              END IF;
              IF TG_OP='DELETE' THEN
                RAISE EXCEPTION 'voice deletion request cannot be deleted';
              END IF;
              IF OLD.state IN ('completed','cancelled','superseded') THEN
                RAISE EXCEPTION 'terminal voice deletion is immutable';
              END IF;
              IF OLD.state='failed' AND OLD.failure_code IN (
                'VOICE_DELETE_SCOPE_INVALID',
                'VOICE_DELETE_FILE_IDENTITY_INVALID',
                'VOICE_DELETE_ASSET_PLAN_INVALID'
              ) THEN
                RAISE EXCEPTION 'terminal safety failure is immutable';
              END IF;
              IF OLD.confirmed_actor IS NOT NULL AND
                 (OLD.confirmed_actor,OLD.confirmed_at) IS DISTINCT FROM
                 (NEW.confirmed_actor,NEW.confirmed_at)
              THEN RAISE EXCEPTION 'voice deletion confirmation is write-once'; END IF;
              IF (NEW.confirmed_actor IS NULL)<>(NEW.confirmed_at IS NULL)
              THEN RAISE EXCEPTION 'voice deletion confirmation actor/time must be paired'; END IF;
              IF (to_jsonb(OLD)-ARRAY['state','confirmed_actor','confirmed_at',
                     'cancelled_actor','cancelled_at','failure_code','completed_at',
                     'superseded_at','job_drain_started_at','job_drain_deadline','updated_at']) <>
                 (to_jsonb(NEW)-ARRAY['state','confirmed_actor','confirmed_at',
                     'cancelled_actor','cancelled_at','failure_code','completed_at',
                     'superseded_at','job_drain_started_at','job_drain_deadline','updated_at'])
              THEN RAISE EXCEPTION 'voice deletion canonical request is immutable'; END IF;
              IF OLD.state<>NEW.state AND NOT (
                (OLD.state IN ('grace_pending','requested')
                 AND NEW.state IN ('cancelled','live_deleting','failed','superseded')) OR
                (OLD.state='failed' AND OLD.failure_code='VOICE_DELETE_WAITING_FOR_JOBS'
                 AND NEW.state IN ('cancelled','live_deleting','superseded')) OR
                (OLD.state='live_deleting'
                 AND NEW.state IN ('live_deleted_backup_pending','completed','failed')) OR
                (OLD.state='live_deleted_backup_pending'
                 AND NEW.state IN ('completed','failed')) OR
                (OLD.state='failed' AND OLD.failure_code<>'VOICE_DELETE_WAITING_FOR_JOBS'
                 AND NEW.state IN
                   ('live_deleting','live_deleted_backup_pending','completed'))
              ) THEN RAISE EXCEPTION 'invalid voice deletion state transition'; END IF;
              RETURN NEW;
            END $$;
            """
        )
    )


def _downgrade_deletion_lifecycle() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
              IF EXISTS (
                SELECT 1 FROM voice_deletion_requests
              ) THEN
                RAISE EXCEPTION
                  'TTS35 deletion downgrade refused: 0034 lifecycle evidence exists';
              END IF;
            END $$;
            """
        )
    )
    op.execute(
        sa.text(
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
    )
    op.drop_index(
        "uq_voice_deletion_requests_active_profile",
        table_name="voice_deletion_requests",
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
    op.drop_index(
        "uq_voice_deletion_requests_idempotency",
        table_name="voice_deletion_requests",
    )
    op.create_index(
        "uq_voice_deletion_requests_idempotency",
        "voice_deletion_requests",
        ["owner_id", "workspace_id", "command", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.drop_constraint(
        "ck_voice_deletion_request_failure_shape",
        "voice_deletion_requests",
        type_="check",
    )
    op.drop_constraint(
        "ck_voice_deletion_request_job_drain_shape",
        "voice_deletion_requests",
        type_="check",
    )
    op.drop_constraint(
        "ck_voice_deletion_request_superseded_shape",
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
        "state IN ('grace_pending','requested','cancelled','live_deleting',"
        "'live_deleted_backup_pending','completed','failed')",
    )
    for name in (
        "job_drain_deadline",
        "job_drain_started_at",
        "superseded_at",
    ):
        op.drop_column("voice_deletion_requests", name)


def upgrade() -> None:
    op.add_column(
        "voice_profile_versions",
        sa.Column("model_run_id", postgresql.UUID(as_uuid=True)),
    )
    op.create_foreign_key(
        "fk_voice_profile_version_model_run",
        "voice_profile_versions",
        "model_run_records",
        ["model_run_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "ck_voice_profile_version_locked_shape",
        "voice_profile_versions",
        type_="check",
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
        "AND model_run_id IS NOT NULL AND locked_actor IS NULL AND locked_at IS NULL))",
    )
    op.create_check_constraint(
        "ck_voice_profile_version_model_run_shape",
        "voice_profile_versions",
        "model_run_id IS NULL OR (state='locked' AND source_type='generated' "
        "AND activation_basis='experimental_machine_validated' "
        "AND validation_basis='machine_validated' AND quality_state='accepted')",
    )
    _replace_voice_version_guard(allow_machine_validation=True)
    _create_experiment_table()
    _install_experiment_guards()
    _install_preview_scope(allow_generated=True)
    _install_voice_preview_job_closure(allow_nano_reuse=True)
    _upgrade_deletion_lifecycle()


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM nano_voice_experiment_commands)
                 OR EXISTS (
                   SELECT 1 FROM voice_profile_versions
                   WHERE model_run_id IS NOT NULL
                      OR activation_basis='experimental_machine_validated'
                      OR validation_basis='machine_validated'
                 )
              THEN
                RAISE EXCEPTION
                  'TTS35 experiment downgrade refused: 0034 evidence exists';
              END IF;
            END $$;
            """
        )
    )
    _downgrade_deletion_lifecycle()
    _install_voice_preview_job_closure(allow_nano_reuse=False)
    _install_preview_scope(allow_generated=False)
    op.execute(
        "DROP TRIGGER IF EXISTS trg_nano_voice_experiment_model_run_immutable "
        "ON model_run_records"
    )
    op.execute(
        "DROP FUNCTION narration_guard_experiment_model_run_immutable_v1()"
    )
    for trigger, table in (
        ("trg_nano_voice_experiment_model_run_closure", "model_run_records"),
        ("trg_nano_voice_experiment_version_closure", "voice_profile_versions"),
        ("trg_nano_voice_experiment_job_closure", "background_jobs"),
        ("trg_nano_voice_experiment_preview_closure", "voice_previews"),
        ("trg_nano_voice_experiment_closure", "nano_voice_experiment_commands"),
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
    op.execute("DROP FUNCTION narration_check_nano_voice_experiment_closure_v1()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_nano_voice_experiment_lifecycle "
        "ON nano_voice_experiment_commands"
    )
    op.execute("DROP FUNCTION narration_guard_nano_voice_experiment_v1()")
    op.drop_index(
        "ix_nano_voice_experiments_state",
        table_name="nano_voice_experiment_commands",
    )
    op.drop_index(
        "ix_nano_voice_experiments_scope_created",
        table_name="nano_voice_experiment_commands",
    )
    op.drop_table("nano_voice_experiment_commands")
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
    op.create_check_constraint(
        "ck_voice_profile_version_locked_shape",
        "voice_profile_versions",
        "state <> 'locked' OR ("
        "(activation_basis='preview_confirmed' AND validation_basis='human_accepted' "
        "AND quality_state='accepted' AND locked_actor IS NOT NULL AND locked_at IS NOT NULL) OR "
        "(activation_basis='explicit_official_preset_selection' AND source_type='preset' "
        "AND validation_basis='not_required' AND quality_state='pending' "
        "AND locked_actor IS NULL AND locked_at IS NULL))",
    )
    op.drop_constraint(
        "fk_voice_profile_version_model_run",
        "voice_profile_versions",
        type_="foreignkey",
    )
    op.drop_column("voice_profile_versions", "model_run_id")
    _replace_voice_version_guard(allow_machine_validation=False)
