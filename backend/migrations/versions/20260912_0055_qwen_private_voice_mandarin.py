"""Open the Qwen private-voice reference path and freeze Mandarin output.

Revision ID: 20260912_0055
Revises: 20260912_0054

The migration does not rewrite existing rows.  NOT VALID constraints protect
all new or changed rows while preserving historical editions verbatim.
"""

from alembic import op


revision = "20260912_0055"
down_revision = "20260912_0054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE voice_profile_versions ADD CONSTRAINT "
        "ck_voice_profile_version_product_language CHECK (language='zh-CN') NOT VALID"
    )
    op.execute(
        "ALTER TABLE voice_profile_versions ADD CONSTRAINT "
        "ck_voice_profile_version_generated_reference CHECK ("
        "source_type<>'generated' OR state NOT IN ('preview_ready','locked') "
        "OR reference_asset_id IS NOT NULL) NOT VALID"
    )
    op.execute(
        "ALTER TABLE narration_scope_overrides ADD CONSTRAINT "
        "ck_narration_scope_override_mandarin CHECK ("
        "settings_json->>'language' IS NULL OR "
        "settings_json->>'language'='zh-CN') NOT VALID"
    )
    # 0054 froze each speaker's historical native language into the deferred
    # official-selection closure. Product output is now Mandarin-only, while
    # native_language remains catalog metadata. Patch only those three SQL
    # literals; all provider identities and provenance hashes stay unchanged.
    op.execute(
        r"""
        DO $migration$
        DECLARE
          function_definition text;
          old_fragment text;
          new_fragment text;
          replacements text[][] := ARRAY[
            ARRAY['(''qwen.Ryan'', ''en'',', '(''qwen.Ryan'', ''zh-CN'','],
            ARRAY['(''qwen.OnoAnna'', ''ja-JP'',', '(''qwen.OnoAnna'', ''zh-CN'','],
            ARRAY['(''qwen.Sohee'', ''ko-KR'',', '(''qwen.Sohee'', ''zh-CN'',']
          ];
          item text[];
        BEGIN
          SELECT pg_get_functiondef(
            'narration_check_official_voice_action_closure_v1()'::regprocedure
          ) INTO function_definition;
          FOREACH item SLICE 1 IN ARRAY replacements
          LOOP
            old_fragment := item[1];
            new_fragment := item[2];
            IF position(old_fragment IN function_definition)=0 THEN
              RAISE EXCEPTION
                'Qwen official voice closure lacks expected native-language fragment';
            END IF;
            function_definition := replace(
              function_definition, old_fragment, new_fragment
            );
          END LOOP;
          EXECUTE function_definition;
        END
        $migration$;
        """
    )
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION narration_guard_voice_version()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
          generated_reference_publication boolean;
          preview_publication boolean;
        BEGIN
          IF OLD.state='locked' THEN
            RAISE EXCEPTION 'locked voice version is immutable';
          END IF;
          IF OLD.state='deleted' THEN
            RAISE EXCEPTION 'deleted voice version is immutable';
          END IF;
          IF TG_OP='DELETE' THEN RETURN OLD; END IF;

          generated_reference_publication :=
            OLD.source_type='generated'
            AND NEW.source_type='generated'
            AND OLD.state='draft' AND NEW.state='draft'
            AND OLD.reference_asset_id IS NULL
            AND NEW.reference_asset_id IS NOT NULL
            AND OLD.preview_asset_id IS NOT DISTINCT FROM NEW.preview_asset_id
            AND OLD.parameters_json->>'design_description' IS NOT NULL
            AND NOT (NEW.parameters_json ? 'design_description')
            AND NEW.parameters_json->>'schema_version'='qwen-tts-voice/1'
            AND NEW.parameters_json->>'voice_kind'='reference_clone'
            AND NEW.parameters_json->>'provider_voice_id'='durable-reference'
            AND btrim(NEW.parameters_json->>'reference_text')<>''
            AND (to_jsonb(OLD)-ARRAY['reference_asset_id','parameters_json']) =
                (to_jsonb(NEW)-ARRAY['reference_asset_id','parameters_json']);

          preview_publication :=
            OLD.source_type IN ('uploaded','generated')
            AND NEW.source_type=OLD.source_type
            AND OLD.state='draft' AND NEW.state='preview_ready'
            AND OLD.preview_asset_id IS NULL
            AND NEW.preview_asset_id IS NOT NULL
            AND NEW.reference_asset_id IS NOT NULL
            AND OLD.reference_asset_id IS NOT DISTINCT FROM NEW.reference_asset_id
            AND OLD.parameters_json=NEW.parameters_json
            AND NEW.parameters_json->>'schema_version'='qwen-tts-voice/1'
            AND NEW.parameters_json->>'voice_kind'='reference_clone'
            AND NEW.parameters_json->>'provider_voice_id'='durable-reference'
            AND btrim(NEW.parameters_json->>'reference_text')<>''
            AND (to_jsonb(OLD)-ARRAY['state','preview_asset_id']) =
                (to_jsonb(NEW)-ARRAY['state','preview_asset_id']);

          IF NOT (
            (to_jsonb(OLD)-ARRAY['state','quality_state','validation_basis',
                'locked_actor','locked_at']) =
            (to_jsonb(NEW)-ARRAY['state','quality_state','validation_basis',
                'locked_actor','locked_at'])
            OR generated_reference_publication
            OR preview_publication
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
            OLD.validation_basis='pending'
            AND NEW.validation_basis='human_accepted'
            AND NEW.activation_basis='preview_confirmed'
            AND NEW.state='locked'
            AND NEW.quality_state='accepted'
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
            ) THEN
              RAISE EXCEPTION 'locked voice activation evidence is inconsistent';
            END IF;
          ELSIF NEW.activation_basis<>'preview_confirmed'
             OR NEW.validation_basis<>'pending'
             OR NEW.locked_actor IS NOT NULL OR NEW.locked_at IS NOT NULL
          THEN
            RAISE EXCEPTION 'unlocked voice version carries activation evidence';
          END IF;
          IF NEW.model_run_id IS NOT NULL THEN
            RAISE EXCEPTION 'voice version cannot own mutable model-run identity';
          END IF;
          IF NEW.quality_state='rejected' AND NEW.state<>'unavailable' THEN
            RAISE EXCEPTION 'rejected voice quality requires unavailable state';
          END IF;
          RETURN NEW;
        END $$;
        """
    )

    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION narration_guard_voice_preview_lifecycle_v1()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE generated_reference_publication boolean;
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

          generated_reference_publication :=
            OLD.status='running' AND NEW.status='running'
            AND OLD.reference_asset_id IS NULL
            AND NEW.reference_asset_id IS NOT NULL
            AND OLD.reference_fingerprint<>NEW.reference_fingerprint
            AND OLD.parameters_fingerprint<>NEW.parameters_fingerprint
            AND NEW.reference_fingerprint ~ '^[0-9a-f]{64}$'
            AND NEW.parameters_fingerprint ~ '^[0-9a-f]{64}$'
            AND (to_jsonb(OLD)-ARRAY[
                  'reference_asset_id','reference_fingerprint',
                  'parameters_fingerprint','updated_at'
                ]) =
                (to_jsonb(NEW)-ARRAY[
                  'reference_asset_id','reference_fingerprint',
                  'parameters_fingerprint','updated_at'
                ]);

          IF (to_jsonb(OLD)-ARRAY['status','preview_text','result_asset_id',
                                  'started_at','completed_at','expires_at',
                                  'failure_code','updated_at']) <>
             (to_jsonb(NEW)-ARRAY['status','preview_text','result_asset_id',
                                  'started_at','completed_at','expires_at',
                                  'failure_code','updated_at'])
             AND NOT generated_reference_publication
          THEN
            RAISE EXCEPTION 'voice preview canonical request is immutable';
          END IF;
          IF NEW.updated_at<OLD.updated_at THEN
            RAISE EXCEPTION 'voice preview update time cannot move backwards';
          END IF;
          IF generated_reference_publication THEN
            RETURN NEW;
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

        CREATE OR REPLACE FUNCTION narration_guard_voice_preview_scope_v1()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE preview_row voice_previews%ROWTYPE;
        BEGIN
          SELECT * INTO preview_row FROM voice_previews WHERE id=NEW.id;
          IF NOT FOUND THEN RETURN NULL; END IF;
          IF NOT EXISTS (
            SELECT 1
            FROM voice_profiles profile
            JOIN voice_profile_versions version
              ON version.id=preview_row.version_id
             AND version.profile_id=profile.id
            JOIN voice_rights_records rights
              ON rights.id=preview_row.rights_record_id
             AND rights.id=version.rights_record_id
            JOIN background_jobs job ON job.id=preview_row.job_id
            LEFT JOIN voice_reference_asset_links link
              ON link.voice_version_id=version.id AND link.profile_id=profile.id
            LEFT JOIN media_assets reference
              ON reference.id=preview_row.reference_asset_id
            LEFT JOIN media_assets result
              ON result.id=preview_row.result_asset_id
            WHERE profile.id=preview_row.profile_id
              AND (profile.owner_id,profile.workspace_id,profile.novel_id)
                  IS NOT DISTINCT FROM
                  (preview_row.owner_id,preview_row.workspace_id,preview_row.novel_id)
              AND profile.status IN ('draft','active')
              AND (version.owner_id,version.workspace_id)=
                  (preview_row.owner_id,preview_row.workspace_id)
              AND version.state IN ('draft','preview_ready','locked')
              AND version.provider_id='qwen-tts'
              AND version.model_id=
                  'mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit'
              AND version.model_revision=
                  'e7dd0585652209fa0d7783659aad4e8a324de11c'
              AND version.language='zh-CN'
              AND version.parameters_json->>'schema_version'='qwen-tts-voice/1'
              AND version.parameters_json->>'voice_kind'='reference_clone'
              AND version.parameters_json->>'provider_voice_id'='durable-reference'
              AND btrim(version.parameters_json->>'reference_text')<>''
              AND (rights.owner_id,rights.workspace_id,rights.novel_id)
                  IS NOT DISTINCT FROM
                  (preview_row.owner_id,preview_row.workspace_id,preview_row.novel_id)
              AND rights.purpose='private_novel_narration'
              AND rights.voice_cloning IS TRUE
              AND (rights.expires_at IS NULL OR rights.expires_at>CURRENT_TIMESTAMP)
              AND EXISTS (
                SELECT 1 FROM voice_rights_events confirmed
                WHERE confirmed.rights_record_id=rights.id
                  AND confirmed.event_type='confirmed'
              )
              AND NOT EXISTS (
                SELECT 1 FROM voice_rights_events event
                WHERE event.rights_record_id=rights.id
                  AND event.event_type IN ('revoked','expired','review_blocked')
              )
              AND (
                (
                  version.source_type='uploaded'
                  AND rights.source_kind='user_upload'
                  AND version.reference_asset_id=preview_row.reference_asset_id
                  AND preview_row.reference_asset_id IS NOT NULL
                  AND link.rights_record_id=rights.id
                  AND link.reference_asset_id=reference.id
                  AND (link.owner_id,link.workspace_id,link.novel_id)
                      IS NOT DISTINCT FROM
                      (preview_row.owner_id,preview_row.workspace_id,
                       preview_row.novel_id)
                ) OR (
                  version.source_type='generated'
                  AND rights.source_kind='qwen_synthetic_design'
                  AND link.id IS NULL
                  AND (
                    (version.reference_asset_id IS NULL
                     AND preview_row.reference_asset_id IS NULL
                     AND preview_row.status IN ('queued','running')) OR
                    (version.reference_asset_id=preview_row.reference_asset_id
                     AND preview_row.reference_asset_id IS NOT NULL)
                  )
                )
              )
              AND (
                preview_row.reference_asset_id IS NULL OR
                (
                  (reference.owner_id,reference.workspace_id,reference.novel_id)
                      IS NOT DISTINCT FROM
                      (preview_row.owner_id,preview_row.workspace_id,
                       preview_row.novel_id)
                  AND reference.kind='narration_voice_reference'
                  AND reference.asset_class='voice_reference'
                  AND reference.state='ready'
                  AND reference.retention_policy='locked_voice'
                )
              )
              AND (job.owner_id,job.workspace_id,job.novel_id)
                  IS NOT DISTINCT FROM
                  (preview_row.owner_id,preview_row.workspace_id,preview_row.novel_id)
              AND job.job_kind='narration.voice_preview'
              AND job.resource_class='qwen-tts'
              AND job.request_id IS NULL
              AND (
                (preview_row.status='queued' AND job.state IN
                  ('queued','running','retry_wait','cancel_requested')) OR
                (preview_row.status='running' AND job.state IN
                  ('queued','running','retry_wait','cancel_requested')) OR
                (preview_row.status='ready' AND job.state='succeeded') OR
                (preview_row.status='failed' AND job.state IN
                  ('failed','dead_letter')) OR
                (preview_row.status='cancelled' AND job.state='cancelled')
              )
              AND (
                (preview_row.status<>'ready' AND result.id IS NULL) OR
                (preview_row.status='ready'
                 AND preview_row.reference_asset_id IS NOT NULL
                 AND version.state IN ('preview_ready','locked')
                 AND version.preview_asset_id=preview_row.result_asset_id
                 AND (result.owner_id,result.workspace_id,result.novel_id)
                     IS NOT DISTINCT FROM
                     (preview_row.owner_id,preview_row.workspace_id,
                      preview_row.novel_id)
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

        CREATE OR REPLACE FUNCTION narration_guard_voice_preview_job_closure_v1()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE job_row background_jobs%ROWTYPE;
        BEGIN
          SELECT * INTO job_row FROM background_jobs WHERE id=NEW.id;
          IF NOT FOUND OR job_row.job_kind<>'narration.voice_preview' THEN
            RETURN NULL;
          END IF;
          IF NOT EXISTS (
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
          ) THEN
            RAISE EXCEPTION
              'voice preview job requires one coherent preview record';
          END IF;
          RETURN NULL;
        END $$;
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "the Qwen private-voice Mandarin contract is forward-only; "
        "restore the pre-0055 database backup"
    )
