"""Expand the pinned Qwen official-voice catalog to nine local speakers.

Revision ID: 20260912_0054
Revises: 20260911_0053
"""

from alembic import op


revision = "20260912_0054"
down_revision = "20260911_0053"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint(
        "ck_voice_action_command_preset_key",
        "voice_action_commands",
        type_="check",
    )
    # Keep immutable historical rows untouched while enforcing the expanded
    # Qwen-only catalog for every insert/update from this revision onward.
    op.execute(
        "ALTER TABLE voice_action_commands ADD CONSTRAINT "
        "ck_voice_action_command_preset_key CHECK ("
        "preset_key IS NULL OR preset_key IN ("
        "'qwen.WarmFemale','qwen.Vivian','qwen.UncleFu','qwen.Dylan',"
        "'qwen.Eric','qwen.ClearMale','qwen.Ryan','qwen.OnoAnna','qwen.Sohee'"
        ")) NOT VALID"
    )
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION narration_check_official_voice_action_closure_v1()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
          command_row voice_action_commands%ROWTYPE;
          expected_language text;
          expected_provider_voices jsonb;
          expected_provenance_fingerprint text;
        BEGIN
          SELECT * INTO command_row
          FROM voice_action_commands WHERE id=NEW.id;
          IF NOT FOUND OR command_row.state<>'completed' THEN
            RAISE EXCEPTION 'voice action command must be completed by commit';
          END IF;

          SELECT catalog.language, catalog.provider_voices, catalog.fingerprint
          INTO expected_language, expected_provider_voices,
               expected_provenance_fingerprint
          FROM (VALUES
            ('qwen.WarmFemale', 'zh-CN', '{
              "local_qwen3_tts":"Serena",
              "aliyun_qwen_audio_tts:qwen-audio-3.0-tts-plus":"longanlingxin",
              "aliyun_qwen_audio_tts:qwen-audio-3.0-tts-flash":"longanhuan_v3.6"
            }'::jsonb, 'daa7873178cfb83a67d19fc00fbccf73bef5269a79addb29098b1720e63e1e15'),
            ('qwen.Vivian', 'zh-CN',
              '{"local_qwen3_tts":"Vivian"}'::jsonb,
              '1e510bf6bba6c4d0b79f2b969b8530e68dd30ee431cccc55e72a288d3d7ea199'),
            ('qwen.UncleFu', 'zh-CN',
              '{"local_qwen3_tts":"Uncle_Fu"}'::jsonb,
              '0fcbcce01715d020fb7642cc5044667717b677f9d9ed64ed19ec76f7f734cd46'),
            ('qwen.Dylan', 'zh-CN',
              '{"local_qwen3_tts":"Dylan"}'::jsonb,
              'fd761f1b7b4cae911f97edd7efab68cde95cdc8e679e8550eb594cfc6267480b'),
            ('qwen.Eric', 'zh-CN',
              '{"local_qwen3_tts":"Eric"}'::jsonb,
              '133274db4e82447c82c56ac86d9451bdb75e44e7a74cde1a5779132abfbf0639'),
            ('qwen.ClearMale', 'zh-CN', '{
              "local_qwen3_tts":"Aiden",
              "aliyun_qwen_audio_tts:qwen-audio-3.0-tts-plus":"longanlufeng",
              "aliyun_qwen_audio_tts:qwen-audio-3.0-tts-flash":"loongjohn"
            }'::jsonb, '55abfe223530dee39987a93ebb517a3c15531131a377ee7b1c5fc916c70a2601'),
            ('qwen.Ryan', 'en',
              '{"local_qwen3_tts":"Ryan"}'::jsonb,
              '42ad5cd79aaf4b7f075b4d59f9992ea3f7db473ddf8529d4d64889648e48daf6'),
            ('qwen.OnoAnna', 'ja-JP',
              '{"local_qwen3_tts":"Ono_Anna"}'::jsonb,
              '0a9bad58942493e931d807eef99ad43d01259135a84fc1f9ddc756a8b73c3a75'),
            ('qwen.Sohee', 'ko-KR',
              '{"local_qwen3_tts":"Sohee"}'::jsonb,
              '9f8946128eb07fa40720c504d9e501c45deda8d5796349866526f74856fea3e9')
          ) AS catalog(preset_key, language, provider_voices, fingerprint)
          WHERE catalog.preset_key=command_row.preset_key;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'official voice command preset is not a pinned Qwen voice';
          END IF;

          IF command_row.language_mismatch IS DISTINCT FROM (
            split_part(lower(command_row.target_language), '-', 1) <>
            split_part(lower(expected_language), '-', 1)
          ) THEN
            RAISE EXCEPTION 'official voice command language evidence failed';
          END IF;
          IF NOT EXISTS (
            SELECT 1 FROM voice_action_receipts receipt
            WHERE receipt.owner_id=command_row.owner_id
              AND receipt.workspace_id=command_row.workspace_id
              AND receipt.operation=command_row.operation
              AND receipt.resource_id=command_row.id
              AND receipt.request_hash=command_row.request_hash
              AND receipt.state='completed'
              AND receipt.completed_at=command_row.completed_at
          ) THEN
            RAISE EXCEPTION 'voice action command receipt closure failed';
          END IF;
          IF NOT EXISTS (
            SELECT 1
            FROM voice_profiles profile
            JOIN voice_profile_versions version
              ON version.profile_id=profile.id
             AND version.id=command_row.voice_version_id
            JOIN voice_rights_records rights
              ON rights.id=version.rights_record_id
            WHERE profile.id=command_row.profile_id
              AND profile.owner_id=command_row.owner_id
              AND profile.workspace_id=command_row.workspace_id
              AND profile.novel_id=command_row.novel_id
              AND profile.status='active'
              AND profile.current_version_id=version.id
              AND version.owner_id=command_row.owner_id
              AND version.workspace_id=command_row.workspace_id
              AND version.source_type='preset'
              AND version.state='locked'
              AND version.provider_id='qwen-tts'
              AND version.model_id='mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit'
              AND version.model_revision='41d3337e8b7f2843a75841595fc14e4b9a7a4b96'
              AND version.preset_key=command_row.preset_key
              AND version.language=expected_language
              AND version.activation_basis='explicit_official_preset_selection'
              AND version.validation_basis='not_required'
              AND version.quality_state='pending'
              AND version.locked_actor IS NULL
              AND version.locked_at IS NULL
              AND version.seed=1234
              AND version.parameters_json ?& ARRAY[
                'schema_version','voice_kind','provider_voice_ids','official_preset'
              ]
              AND version.parameters_json - ARRAY[
                'schema_version','voice_kind','provider_voice_ids','official_preset'
              ] = '{}'::jsonb
              AND version.parameters_json->>'schema_version'='qwen-tts-voice/1'
              AND version.parameters_json->>'voice_kind'='preset'
              AND version.parameters_json->'provider_voice_ids'=expected_provider_voices
              AND version.parameters_json->'official_preset'->>'schema_version'=
                  'qwen-tts-preset-provenance/1'
              AND version.parameters_json->'official_preset'->>'catalog_id'=
                  'qwen-provider-voice-map/1'
              AND version.parameters_json->'official_preset'->>'preset_id'=
                  command_row.preset_key
              AND version.parameters_json->'official_preset'->>'local_model_id'=
                  'mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit'
              AND version.parameters_json->'official_preset'->>'local_model_revision'=
                  '41d3337e8b7f2843a75841595fc14e4b9a7a4b96'
              AND version.parameters_json->'official_preset'->>'model_fingerprint_sha256'=
                  '728e8b60b4cdb195a1379faf033b428bf93feaceccbdcf3c3a4bd3a6698b4fb6'
              AND version.parameters_json->'official_preset'->'provider_voice_ids'=
                  expected_provider_voices
              AND version.parameters_json->'official_preset'->>
                  'provenance_fingerprint_sha256'=expected_provenance_fingerprint
              AND rights.owner_id=command_row.owner_id
              AND rights.workspace_id=command_row.workspace_id
              AND rights.novel_id=command_row.novel_id
              AND rights.source_kind='official_preset'
              AND rights.source_identifier=
                  'qwen-tts-catalog://' || command_row.preset_key
              AND rights.notice_version='qwen-tts-built-in-voice-use/1'
              AND rights.purpose='private_novel_narration'
              AND rights.commercial_use IS FALSE
              AND rights.redistribution IS FALSE
              AND rights.voice_cloning IS FALSE
              AND rights.subject_consent_reference IS NULL
              AND rights.expires_at IS NULL
              AND rights.risk_flags_json='[]'::jsonb
          ) THEN
            RAISE EXCEPTION 'official voice version evidence closure failed';
          END IF;
          IF command_row.target_kind='narrator' THEN
            IF NOT EXISTS (
              SELECT 1 FROM novel_narration_settings settings
              WHERE settings.novel_id=command_row.novel_id
                AND settings.narrator_profile_id=command_row.profile_id
                AND settings.narrator_version_id=command_row.voice_version_id
                AND settings.version=command_row.settings_version
            ) THEN
              RAISE EXCEPTION 'narrator voice selection projection closure failed';
            END IF;
          ELSE
            IF NOT EXISTS (
              SELECT 1 FROM novel_narration_settings settings
              WHERE settings.novel_id=command_row.novel_id
                AND settings.version=command_row.settings_version
            ) OR NOT EXISTS (
              SELECT 1 FROM character_voice_bindings binding
              WHERE binding.novel_id=command_row.novel_id
                AND binding.character_id=command_row.target_character_id
                AND binding.profile_id=command_row.profile_id
                AND binding.voice_version_id=command_row.voice_version_id
                AND binding.binding_policy='dedicated'
                AND binding.version=command_row.binding_version
            ) THEN
              RAISE EXCEPTION 'character voice selection projection closure failed';
            END IF;
          END IF;
          RETURN NULL;
        END $$;
        """
    )


def downgrade():
    raise RuntimeError(
        "the nine-speaker Qwen catalog is forward-only; restore the pre-0054 backup"
    )
