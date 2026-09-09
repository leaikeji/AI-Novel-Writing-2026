"""Remove retired MOSS/Nano/VoiceGenerator and generic voice-pool state.

Revision ID: 20260909_0049
Revises: 20260909_0048

The migration is intentionally forward-only.  It deletes only TTS-derived
objects selected by the frozen Plan 62 predicates; document revisions and
working copies are never selected or mutated.
"""

from alembic import op


revision = "20260909_0049"
down_revision = "20260909_0048"
branch_labels = None
depends_on = None


_RETAINED_TRIGGER_TABLES = (
    "active_job_assets",
    "anonymous_speakers",
    "background_job_attempts",
    "background_job_kind_policies",
    "background_jobs",
    "background_manual_retry_commands",
    "background_resource_class_policies",
    "background_resource_class_slots",
    "background_resource_locks",
    "character_voice_bindings",
    "document_narration_state",
    "media_assets",
    "media_gc_deletion_plans",
    "model_run_records",
    "narration_edition_segments",
    "narration_edition_state",
    "narration_editions",
    "narration_exports",
    "narration_manifest_segments",
    "narration_manifests",
    "narration_playback_progress",
    "narration_render_assets",
    "narration_requests",
    "narration_scenes",
    "narration_script_issues",
    "narration_script_review_actions",
    "narration_script_versions",
    "narration_settings_snapshots",
    "narration_segment_renders",
    "narration_segments",
    "novel_narration_settings",
    "voice_action_commands",
    "voice_action_receipts",
    "voice_casting_rules",
    "voice_deletion_asset_plans",
    "voice_deletion_requests",
    "voice_previews",
    "voice_profile_versions",
    "voice_profiles",
    "voice_reference_asset_links",
    "voice_rights_events",
    "voice_rights_records",
)


def _set_user_triggers(*, enabled: bool) -> None:
    verb = "ENABLE" if enabled else "DISABLE"
    tables = ",".join(f"'{name}'" for name in _RETAINED_TRIGGER_TABLES)
    op.execute(
        f"""
        DO $plan62$
        DECLARE table_name text;
        BEGIN
          FOREACH table_name IN ARRAY ARRAY[{tables}]
          LOOP
            EXECUTE format('ALTER TABLE %I {verb} TRIGGER USER', table_name);
          END LOOP;
        END
        $plan62$;
        """
    )


def upgrade():
    # Freeze every destructive target before any mutation.  These predicates
    # are the same ones used by the hashed W0 object and media manifests.
    op.execute(
        r"""
        CREATE TEMP TABLE plan62_old_versions ON COMMIT DROP AS
        SELECT id, profile_id, rights_record_id, model_run_id
        FROM voice_profile_versions
        WHERE provider_id IN ('local-sidecar', 'local-native-host')
           OR model_id LIKE 'OpenMOSS-Team/%'
           OR activation_basis IN (
             'character_one_click_generation',
             'experimental_machine_validated',
             'generic_voice_pack_generation'
           );
        ALTER TABLE plan62_old_versions ADD PRIMARY KEY (id);

        CREATE TEMP TABLE plan62_old_profiles ON COMMIT DROP AS
        SELECT DISTINCT profile_id AS id FROM plan62_old_versions;
        ALTER TABLE plan62_old_profiles ADD PRIMARY KEY (id);

        CREATE TEMP TABLE plan62_old_editions ON COMMIT DROP AS
        SELECT DISTINCT edition.id, edition.settings_snapshot_id
        FROM narration_editions edition
        JOIN narration_edition_segments segment ON segment.edition_id=edition.id
        WHERE segment.voice_version_id IN (SELECT id FROM plan62_old_versions)
           OR segment.slot_id IS NOT NULL;
        ALTER TABLE plan62_old_editions ADD PRIMARY KEY (id);

        CREATE TEMP TABLE plan62_old_renders ON COMMIT DROP AS
        SELECT id, source_job_id
        FROM narration_segment_renders
        WHERE voice_version_id IN (SELECT id FROM plan62_old_versions);
        ALTER TABLE plan62_old_renders ADD PRIMARY KEY (id);

        CREATE TEMP TABLE plan62_old_previews ON COMMIT DROP AS
        SELECT id, job_id
        FROM voice_previews
        WHERE version_id IN (SELECT id FROM plan62_old_versions)
           OR profile_id IN (SELECT id FROM plan62_old_profiles);
        ALTER TABLE plan62_old_previews ADD PRIMARY KEY (id);

        CREATE TEMP TABLE plan62_old_jobs ON COMMIT DROP AS
        SELECT id FROM background_jobs
        WHERE resource_class IN ('moss-nano', 'voice-generator')
           OR job_kind IN (
             'narration.generic_voice_generate',
             'narration.voice_generate',
             'narration.voice_prepare'
           )
        UNION SELECT source_job_id FROM plan62_old_renders WHERE source_job_id IS NOT NULL
        UNION SELECT job_id FROM plan62_old_previews WHERE job_id IS NOT NULL
        UNION SELECT background_job_id FROM voice_generator_commands
          WHERE background_job_id IS NOT NULL
        UNION SELECT background_job_id FROM generic_voice_generation_commands
          WHERE background_job_id IS NOT NULL;
        ALTER TABLE plan62_old_jobs ADD PRIMARY KEY (id);

        CREATE TEMP TABLE plan62_old_model_runs ON COMMIT DROP AS
        SELECT run.id
        FROM model_run_records run
        JOIN background_job_attempts attempt ON attempt.id=run.attempt_id
        WHERE attempt.job_id IN (SELECT id FROM plan62_old_jobs)
        UNION SELECT model_run_id FROM voice_generator_run_evidence
        UNION SELECT generator_model_run_id FROM voice_generator_commands
          WHERE generator_model_run_id IS NOT NULL
        UNION SELECT nano_model_run_id FROM voice_generator_commands
          WHERE nano_model_run_id IS NOT NULL
        UNION SELECT generator_model_run_id FROM generic_voice_generation_commands
          WHERE generator_model_run_id IS NOT NULL
        UNION SELECT nano_model_run_id FROM generic_voice_generation_commands
          WHERE nano_model_run_id IS NOT NULL
        UNION SELECT model_run_id FROM plan62_old_versions
          WHERE model_run_id IS NOT NULL;
        ALTER TABLE plan62_old_model_runs ADD PRIMARY KEY (id);

        CREATE TEMP TABLE plan62_old_assets ON COMMIT DROP AS
        SELECT reference_asset_id AS id FROM voice_profile_versions
          WHERE id IN (SELECT id FROM plan62_old_versions)
            AND reference_asset_id IS NOT NULL
        UNION SELECT preview_asset_id FROM voice_profile_versions
          WHERE id IN (SELECT id FROM plan62_old_versions)
            AND preview_asset_id IS NOT NULL
        UNION SELECT reference_asset_id FROM voice_previews
          WHERE id IN (SELECT id FROM plan62_old_previews)
            AND reference_asset_id IS NOT NULL
        UNION SELECT result_asset_id FROM voice_previews
          WHERE id IN (SELECT id FROM plan62_old_previews)
            AND result_asset_id IS NOT NULL
        UNION SELECT asset_id FROM narration_render_assets
          WHERE render_id IN (SELECT id FROM plan62_old_renders)
        UNION SELECT asset_id FROM narration_exports
          WHERE edition_id IN (SELECT id FROM plan62_old_editions)
        UNION SELECT generated_reference_asset_id FROM voice_generator_commands
          WHERE generated_reference_asset_id IS NOT NULL
        UNION SELECT nano_validation_asset_id FROM voice_generator_commands
          WHERE nano_validation_asset_id IS NOT NULL
        UNION SELECT generated_reference_asset_id FROM generic_voice_generation_commands
          WHERE generated_reference_asset_id IS NOT NULL
        UNION SELECT nano_validation_asset_id FROM generic_voice_generation_commands
          WHERE nano_validation_asset_id IS NOT NULL;
        ALTER TABLE plan62_old_assets ADD PRIMARY KEY (id);

        CREATE TEMP TABLE plan62_old_actions ON COMMIT DROP AS
        SELECT id FROM voice_action_commands
        WHERE voice_version_id IN (SELECT id FROM plan62_old_versions)
           OR profile_id IN (SELECT id FROM plan62_old_profiles);
        ALTER TABLE plan62_old_actions ADD PRIMARY KEY (id);

        CREATE TEMP TABLE plan62_old_rights ON COMMIT DROP AS
        SELECT DISTINCT rights_record_id AS id FROM plan62_old_versions;
        ALTER TABLE plan62_old_rights ADD PRIMARY KEY (id);

        CREATE TEMP TABLE plan62_old_script_versions ON COMMIT DROP AS
        SELECT DISTINCT script_version_id AS id
        FROM narration_segments
        WHERE casting_json::text LIKE '%"kind": "generic_slot"%'
           OR casting_json::text LIKE '%"kind":"generic_slot"%';
        ALTER TABLE plan62_old_script_versions ADD PRIMARY KEY (id);
        """
    )

    # Fail closed if any frozen object is shared with a retained Qwen object or
    # if work is still active.  Foreign keys remain enabled throughout.
    op.execute(
        r"""
        DO $plan62$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM voice_profile_versions retained
            WHERE retained.profile_id IN (SELECT id FROM plan62_old_profiles)
              AND retained.id NOT IN (SELECT id FROM plan62_old_versions)
          ) THEN
            RAISE EXCEPTION 'plan62_mixed_voice_profile';
          END IF;
          IF EXISTS (
            SELECT 1 FROM background_jobs
            WHERE id IN (SELECT id FROM plan62_old_jobs)
              AND state IN ('queued','leased','running','retry_wait','cancelling')
          ) THEN
            RAISE EXCEPTION 'plan62_old_job_still_active';
          END IF;
          IF EXISTS (
            SELECT 1 FROM document_narration_state
            WHERE current_script_version_id IN (SELECT id FROM plan62_old_script_versions)
          ) OR EXISTS (
            SELECT 1 FROM narration_editions
            WHERE script_version_id IN (SELECT id FROM plan62_old_script_versions)
          ) OR EXISTS (
            SELECT 1 FROM narration_script_review_actions
            WHERE parent_version_id IN (SELECT id FROM plan62_old_script_versions)
               OR result_version_id IN (SELECT id FROM plan62_old_script_versions)
          ) THEN
            RAISE EXCEPTION 'plan62_generic_script_is_still_referenced';
          END IF;
          IF EXISTS (
            SELECT 1 FROM voice_profile_versions
            WHERE id NOT IN (SELECT id FROM plan62_old_versions)
              AND (reference_asset_id IN (SELECT id FROM plan62_old_assets)
                   OR preview_asset_id IN (SELECT id FROM plan62_old_assets))
          ) OR EXISTS (
            SELECT 1 FROM narration_render_assets
            WHERE asset_id IN (SELECT id FROM plan62_old_assets)
              AND render_id NOT IN (SELECT id FROM plan62_old_renders)
          ) OR EXISTS (
            SELECT 1 FROM narration_exports
            WHERE asset_id IN (SELECT id FROM plan62_old_assets)
              AND edition_id NOT IN (SELECT id FROM plan62_old_editions)
          ) OR EXISTS (
            SELECT 1 FROM active_job_assets
            WHERE asset_id IN (SELECT id FROM plan62_old_assets)
              AND job_id NOT IN (SELECT id FROM plan62_old_jobs)
          ) OR EXISTS (
            SELECT 1 FROM media_assets
            WHERE id IN (SELECT id FROM plan62_old_assets)
              AND kind='novel_cover'
          ) THEN
            RAISE EXCEPTION 'plan62_media_asset_is_shared';
          END IF;
          IF EXISTS (
            SELECT 1 FROM model_run_records
            WHERE id IN (SELECT id FROM plan62_old_model_runs)
              AND id IN (
                SELECT model_run_id FROM voice_profile_versions
                WHERE id NOT IN (SELECT id FROM plan62_old_versions)
                  AND model_run_id IS NOT NULL
              )
          ) THEN
            RAISE EXCEPTION 'plan62_model_run_is_shared';
          END IF;
        END
        $plan62$;
        """
    )

    # Remove closure triggers that query tables retired below.
    op.execute(
        r"""
        DROP TRIGGER IF EXISTS trg_nano_voice_experiment_job_closure ON background_jobs;
        DROP TRIGGER IF EXISTS trg_voice_generator_job_closure ON background_jobs;
        DROP TRIGGER IF EXISTS trg_voice_generator_binding_closure ON character_voice_bindings;
        DROP TRIGGER IF EXISTS trg_voice_generator_media_closure ON media_assets;
        DROP TRIGGER IF EXISTS trg_nano_voice_experiment_model_run_closure ON model_run_records;
        DROP TRIGGER IF EXISTS trg_nano_voice_experiment_model_run_immutable ON model_run_records;
        DROP TRIGGER IF EXISTS trg_two_phase_voice_generator_model_run ON model_run_records;
        DROP TRIGGER IF EXISTS trg_voice_generator_model_run_closure ON model_run_records;
        DROP TRIGGER IF EXISTS trg_nano_voice_experiment_preview_closure ON voice_previews;
        DROP TRIGGER IF EXISTS trg_nano_voice_experiment_version_closure ON voice_profile_versions;
        DROP TRIGGER IF EXISTS trg_voice_generator_version_closure ON voice_profile_versions;
        DROP TRIGGER IF EXISTS trg_voice_generator_profile_closure ON voice_profiles;
        """
    )
    _set_user_triggers(enabled=False)

    op.execute(
        r"""
        SET CONSTRAINTS ALL DEFERRED;

        UPDATE document_narration_state
        SET current_edition_id=NULL,
            version=version+1,
            switched_actor='plan62-retired-tts-cleanup',
            switched_at=now()
        WHERE current_edition_id IN (SELECT id FROM plan62_old_editions);

        DELETE FROM narration_script_review_actions
        WHERE result_edition_id IN (SELECT id FROM plan62_old_editions);
        DELETE FROM narration_playback_progress
        WHERE edition_id IN (SELECT id FROM plan62_old_editions);
        DELETE FROM narration_edition_state
        WHERE edition_id IN (SELECT id FROM plan62_old_editions);
        DELETE FROM narration_manifest_segments
        WHERE edition_id IN (SELECT id FROM plan62_old_editions);
        DELETE FROM narration_manifests
        WHERE edition_id IN (SELECT id FROM plan62_old_editions);
        DELETE FROM narration_exports
        WHERE edition_id IN (SELECT id FROM plan62_old_editions);
        DELETE FROM narration_edition_segments
        WHERE edition_id IN (SELECT id FROM plan62_old_editions);
        DELETE FROM narration_editions
        WHERE id IN (SELECT id FROM plan62_old_editions);

        DELETE FROM narration_render_assets
        WHERE render_id IN (SELECT id FROM plan62_old_renders);
        DELETE FROM narration_segment_renders
        WHERE id IN (SELECT id FROM plan62_old_renders);
        DELETE FROM narration_settings_snapshots snapshot
        WHERE snapshot.id IN (SELECT settings_snapshot_id FROM plan62_old_editions)
          AND NOT EXISTS (
            SELECT 1 FROM narration_editions retained
            WHERE retained.settings_snapshot_id=snapshot.id
          );

        UPDATE character_voice_bindings
        SET profile_id=NULL,
            voice_version_id=NULL,
            binding_policy='unset',
            version=version+1,
            updated_at=now()
        WHERE voice_version_id IN (SELECT id FROM plan62_old_versions);
        UPDATE novel_narration_settings
        SET narrator_profile_id=NULL,
            narrator_version_id=NULL,
            version=version+1,
            updated_at=now()
        WHERE narrator_version_id IN (SELECT id FROM plan62_old_versions);
        UPDATE anonymous_speakers
        SET voice_version_id=NULL
        WHERE voice_version_id IN (SELECT id FROM plan62_old_versions);
        DELETE FROM voice_casting_rules
        WHERE target_pool_id IS NOT NULL OR target_slot_id IS NOT NULL;

        DELETE FROM narration_script_issues
        WHERE script_version_id IN (SELECT id FROM plan62_old_script_versions);
        DELETE FROM narration_segments
        WHERE script_version_id IN (SELECT id FROM plan62_old_script_versions);
        DELETE FROM narration_scenes
        WHERE script_version_id IN (SELECT id FROM plan62_old_script_versions);
        UPDATE narration_requests
        SET review_script_id=NULL,
            current_review_version_id=NULL,
            version=version+1,
            updated_at=now()
        WHERE current_review_version_id IN (SELECT id FROM plan62_old_script_versions);
        DELETE FROM voice_deletion_asset_plans
        WHERE deletion_request_id IN (
          SELECT id FROM voice_deletion_requests
          WHERE voice_profile_id IN (SELECT id FROM plan62_old_profiles)
        );
        DELETE FROM voice_deletion_requests
        WHERE voice_profile_id IN (SELECT id FROM plan62_old_profiles);
        DELETE FROM voice_reference_asset_links
        WHERE voice_version_id IN (SELECT id FROM plan62_old_versions)
           OR profile_id IN (SELECT id FROM plan62_old_profiles);
        DELETE FROM voice_previews WHERE id IN (SELECT id FROM plan62_old_previews);

        DELETE FROM active_job_assets WHERE job_id IN (SELECT id FROM plan62_old_jobs);
        DELETE FROM media_gc_deletion_plans WHERE asset_id IN (SELECT id FROM plan62_old_assets);
        """
    )

    # Remove external slot columns before dropping the retired table family.
    op.execute(
        r"""
        ALTER TABLE voice_casting_rules DROP COLUMN target_slot_id;
        ALTER TABLE voice_casting_rules DROP COLUMN target_pool_id;
        ALTER TABLE anonymous_speakers DROP COLUMN slot_id;
        ALTER TABLE narration_edition_segments DROP COLUMN slot_id;

        DROP TABLE character_cast_plan_items;
        DROP TABLE character_cast_plan_commands;
        DROP TABLE voice_preparation_items;
        DROP TABLE voice_preparation_commands;
        DROP TABLE voice_generator_run_evidence;
        DROP TABLE voice_generator_commands;
        DROP TABLE voice_design_drafts;
        DROP TABLE nano_voice_experiment_commands;
        DROP TABLE generic_voice_pack_version_slots;
        DROP TABLE generic_voice_slots;
        DROP TABLE generic_voice_pools;
        DROP TABLE generic_voice_generation_commands;
        DROP TABLE generic_voice_pack_versions;
        DROP TABLE generic_voice_design_drafts;

        DELETE FROM voice_action_commands WHERE id IN (SELECT id FROM plan62_old_actions);
        DELETE FROM voice_action_receipts
        WHERE resource_id IN (SELECT id FROM plan62_old_actions);
        DELETE FROM narration_script_versions
        WHERE id IN (SELECT id FROM plan62_old_script_versions);
        """
    )

    op.execute(
        r"""
        UPDATE voice_profiles
        SET current_version_id=NULL,
            status='unavailable',
            version=version+1,
            updated_at=now()
        WHERE id IN (SELECT id FROM plan62_old_profiles);
        DELETE FROM voice_profile_versions WHERE id IN (SELECT id FROM plan62_old_versions);
        DELETE FROM voice_profiles WHERE id IN (SELECT id FROM plan62_old_profiles);
        DELETE FROM voice_rights_events WHERE rights_record_id IN (SELECT id FROM plan62_old_rights);
        DELETE FROM voice_rights_records WHERE id IN (SELECT id FROM plan62_old_rights);

        DELETE FROM model_run_records WHERE id IN (SELECT id FROM plan62_old_model_runs);
        ALTER TABLE background_job_attempts
          DROP CONSTRAINT fk_background_job_attempt_manual_retry_command;
        ALTER TABLE background_manual_retry_commands
          DROP CONSTRAINT fk_background_manual_retry_claimed_attempt;
        DELETE FROM background_manual_retry_commands
        WHERE job_id IN (SELECT id FROM plan62_old_jobs);
        DELETE FROM background_job_attempts
        WHERE job_id IN (SELECT id FROM plan62_old_jobs);
        ALTER TABLE background_job_attempts
          ADD CONSTRAINT fk_background_job_attempt_manual_retry_command
          FOREIGN KEY (manual_retry_command_id)
          REFERENCES background_manual_retry_commands(id)
          ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;
        ALTER TABLE background_manual_retry_commands
          ADD CONSTRAINT fk_background_manual_retry_claimed_attempt
          FOREIGN KEY (claimed_attempt_id)
          REFERENCES background_job_attempts(id)
          ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;
        DELETE FROM background_jobs WHERE id IN (SELECT id FROM plan62_old_jobs);

        DELETE FROM media_assets WHERE id IN (SELECT id FROM plan62_old_assets);

        UPDATE background_job_kind_policies
        SET resource_class='qwen-tts', version=version+1,
            created_actor='plan62-retired-tts-cleanup', created_at=now()
        WHERE job_kind='narration.voice_preview';
        DELETE FROM background_job_kind_policies
        WHERE job_kind IN (
          'narration.generic_voice_generate',
          'narration.voice_generate',
          'narration.voice_prepare'
        );
        DELETE FROM background_resource_locks
        WHERE resource_key IN (
          SELECT resource_key FROM background_resource_class_slots
          WHERE resource_class IN ('moss-nano','voice-generator')
        );
        DELETE FROM background_resource_class_slots
        WHERE resource_class IN ('moss-nano','voice-generator');
        DELETE FROM background_resource_class_policies
        WHERE resource_class IN ('moss-nano','voice-generator');

        ALTER TABLE voice_profile_versions
          DROP CONSTRAINT ck_voice_profile_version_activation_basis,
          DROP CONSTRAINT ck_voice_profile_version_locked_shape,
          DROP CONSTRAINT ck_voice_profile_version_model_run_shape,
          DROP CONSTRAINT ck_voice_profile_version_unlocked_activation;
        ALTER TABLE voice_profile_versions
          ADD CONSTRAINT ck_voice_profile_version_activation_basis
            CHECK (activation_basis IN (
              'preview_confirmed','explicit_official_preset_selection'
            )),
          ADD CONSTRAINT ck_voice_profile_version_locked_shape
            CHECK (state <> 'locked' OR (
              (activation_basis='preview_confirmed'
               AND validation_basis='human_accepted'
               AND quality_state='accepted'
               AND locked_actor IS NOT NULL AND locked_at IS NOT NULL)
              OR
              (activation_basis='explicit_official_preset_selection'
               AND source_type='preset'
               AND validation_basis='not_required'
               AND quality_state='pending'
               AND locked_actor IS NULL AND locked_at IS NULL)
            )),
          ADD CONSTRAINT ck_voice_profile_version_model_run_shape
            CHECK (model_run_id IS NULL),
          ADD CONSTRAINT ck_voice_profile_version_unlocked_activation
            CHECK (state='locked' OR (
              activation_basis='preview_confirmed' AND validation_basis='pending'
            ));

        ALTER TABLE narration_script_issues
          DROP CONSTRAINT ck_narration_issue_taxonomy_code;
        ALTER TABLE narration_script_issues
          ADD CONSTRAINT ck_narration_issue_taxonomy_code CHECK (
            (severity='warning' AND code IN (
              'W_SPEAKER_MEDIUM_CONFIDENCE','W_NEW_ANONYMOUS_SPEAKER',
              'W_MANUAL_OVERRIDE_INHERITED','W_PRONUNCIATION_SOFT_FALLBACK',
              'W_CLOUD_ASSISTED_USED','W_SCENE_BOUNDARY_MEDIUM_CONFIDENCE'
            )) OR
            (severity='blocker' AND code IN (
              'B_SPEAKER_UNKNOWN','B_SPEAKER_LOW_CONFIDENCE',
              'B_CHARACTER_ALIAS_CONFLICT','B_CHARACTER_REFERENCE_INVALID',
              'B_ANONYMOUS_IDENTITY_CONFLICT','B_CASTING_TARGET_UNRESOLVED',
              'B_VOICE_MISSING','B_VOICE_VERSION_UNAVAILABLE',
              'B_VOICE_RIGHTS_UNAVAILABLE','B_PRONUNCIATION_HARD_CONFLICT',
              'B_CLOUD_DECISION_UNAVAILABLE'
            ))
          );
        """
    )

    _set_user_triggers(enabled=True)
    op.execute(
        r"""
        DROP FUNCTION IF EXISTS narration_check_nano_voice_experiment_closure_v1();
        DROP FUNCTION IF EXISTS narration_guard_experiment_model_run_immutable_v1();
        DROP FUNCTION IF EXISTS narration_guard_nano_voice_experiment_v1();
        DROP FUNCTION IF EXISTS narration_check_voice_generator_closure_v1();
        DROP FUNCTION IF EXISTS narration_guard_two_phase_voice_generator_run_v1();
        DROP FUNCTION IF EXISTS narration_guard_voice_generator_command_v1();
        DROP FUNCTION IF EXISTS narration_reject_voice_generator_immutable_v1();
        DROP FUNCTION IF EXISTS narration_guard_generic_voice_pack_v1();
        DROP FUNCTION IF EXISTS narration_guard_generic_voice_pool_v1();
        DROP FUNCTION IF EXISTS narration_guard_voice_pool();
        DROP FUNCTION IF EXISTS narration_reject_generic_voice_design_mutation_v1();
        """
    )


def downgrade():
    raise RuntimeError(
        "retired MOSS TTS cleanup is forward-only; restore the Plan 62 database and media backups"
    )
