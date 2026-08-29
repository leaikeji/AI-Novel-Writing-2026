"""Add truthful activation evidence and atomic voice action results.

Revision ID: 20260829_0031
Revises: 20260829_0030

This migration is PostgreSQL-only and performs no filesystem, model, or
network I/O. Existing voice versions are backfilled without changing their
identity, state, quality decision, preview evidence, or bindings.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260829_0031"
down_revision = "20260829_0030"
branch_labels = None
depends_on = None


LOCAL_OWNER = "29cf94d9-a5c9-54ec-912c-5dfff8738c4c"
LOCAL_WORKSPACE = "f0e2e632-bc99-52d2-9916-bb906aa4da6e"


def _replace_voice_version_guard() -> None:
    op.execute(
        sa.text(
            """
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
              -- Compatibility for the pre-0031 lock writer: its legal
              -- preview_ready -> locked transition did not know the new
              -- validation column. Normalize that one exact legacy shape.
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
              IF (to_jsonb(OLD)-ARRAY['state','quality_state','validation_basis',
                                      'locked_actor','locked_at']) <>
                 (to_jsonb(NEW)-ARRAY['state','quality_state','validation_basis',
                                      'locked_actor','locked_at'])
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
              IF NEW.quality_state='rejected' AND NEW.state<>'unavailable' THEN
                RAISE EXCEPTION 'rejected voice quality requires unavailable state';
              END IF;
              RETURN NEW;
            END $$;
            """
        )
    )


def _create_action_commands() -> None:
    op.create_table(
        "voice_action_commands",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation", sa.String(48), nullable=False),
        sa.Column("target_kind", sa.String(16), nullable=False),
        sa.Column("target_character_id", postgresql.UUID(as_uuid=True)),
        sa.Column("preset_key", sa.String(160)),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="reserved"),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True)),
        sa.Column("voice_version_id", postgresql.UUID(as_uuid=True)),
        sa.Column("settings_version", sa.BigInteger()),
        sa.Column("binding_version", sa.BigInteger()),
        sa.Column("target_language", sa.String(40)),
        sa.Column("language_mismatch", sa.Boolean()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["novel_id", "owner_id", "workspace_id"],
            ["novels.id", "novels.owner_id", "novels.workspace_id"],
            name="fk_voice_action_command_novel_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_character_id", "novel_id"],
            ["novel_characters.id", "novel_characters.novel_id"],
            name="fk_voice_action_command_character_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["voice_version_id", "profile_id"],
            ["voice_profile_versions.id", "voice_profile_versions.profile_id"],
            name="fk_voice_action_command_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "workspace_id", "operation", "id"],
            [
                "voice_action_receipts.owner_id",
                "voice_action_receipts.workspace_id",
                "voice_action_receipts.operation",
                "voice_action_receipts.resource_id",
            ],
            name="fk_voice_action_command_receipt",
            deferrable=True,
            initially="DEFERRED",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            f"owner_id='{LOCAL_OWNER}'::uuid AND workspace_id='{LOCAL_WORKSPACE}'::uuid",
            name="ck_voice_action_command_fixed_local_scope",
        ),
        sa.CheckConstraint(
            "operation ~ '^[a-z][a-z0-9_]{2,47}$'",
            name="ck_voice_action_command_operation",
        ),
        sa.CheckConstraint(
            "operation = 'official_preset_selection'",
            name="ck_voice_action_command_operation_kind",
        ),
        sa.CheckConstraint(
            "request_hash ~ '^[0-9a-f]{64}$'",
            name="ck_voice_action_command_request_hash",
        ),
        sa.CheckConstraint(
            "preset_key IS NULL OR preset_key ~ '^onnx\\.[A-Za-z][A-Za-z0-9]{0,79}$'",
            name="ck_voice_action_command_preset_key",
        ),
        sa.CheckConstraint(
            "target_kind IN ('narrator','character')",
            name="ck_voice_action_command_target_kind",
        ),
        sa.CheckConstraint(
            "(target_kind='narrator' AND target_character_id IS NULL) OR "
            "(target_kind='character' AND target_character_id IS NOT NULL)",
            name="ck_voice_action_command_target_shape",
        ),
        sa.CheckConstraint(
            "state IN ('reserved','completed')",
            name="ck_voice_action_command_state",
        ),
        sa.CheckConstraint(
            "target_language IS NULL OR "
            "target_language ~ '^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$'",
            name="ck_voice_action_command_target_language",
        ),
        sa.CheckConstraint(
            "(state='reserved' AND profile_id IS NULL AND voice_version_id IS NULL "
            "AND settings_version IS NULL AND binding_version IS NULL "
            "AND target_language IS NULL AND language_mismatch IS NULL "
            "AND completed_at IS NULL) OR "
            "(state='completed' AND profile_id IS NOT NULL AND voice_version_id IS NOT NULL "
            "AND settings_version IS NOT NULL AND settings_version>0 "
            "AND ((target_kind='narrator' AND binding_version IS NULL) "
            "OR (target_kind='character' AND binding_version IS NOT NULL AND binding_version>0)) "
            "AND target_language IS NOT NULL AND language_mismatch IS NOT NULL "
            "AND completed_at IS NOT NULL "
            "AND completed_at>=created_at)",
            name="ck_voice_action_command_lifecycle",
        ),
    )
    op.create_index(
        "ix_voice_action_commands_scope_created",
        "voice_action_commands",
        ["owner_id", "workspace_id", "novel_id", "created_at"],
    )
    op.execute(
        sa.text(
            """
            CREATE FUNCTION narration_guard_voice_action_command_v1()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF TG_OP='INSERT' THEN
                IF NEW.state<>'reserved' THEN
                  RAISE EXCEPTION 'voice action command must be inserted reserved';
                END IF;
                RETURN NEW;
              END IF;
              IF TG_OP='DELETE' THEN
                RAISE EXCEPTION 'voice action command evidence cannot be deleted';
              END IF;
              IF OLD.state='completed' THEN
                RAISE EXCEPTION 'completed voice action command is immutable';
              END IF;
              IF (to_jsonb(OLD)-ARRAY['state','profile_id','voice_version_id',
                                      'settings_version','binding_version',
                                      'target_language','language_mismatch',
                                      'completed_at']) <>
                 (to_jsonb(NEW)-ARRAY['state','profile_id','voice_version_id',
                                      'settings_version','binding_version',
                                      'target_language','language_mismatch',
                                      'completed_at'])
              THEN
                RAISE EXCEPTION 'voice action command request is immutable';
              END IF;
              IF OLD.state<>'reserved' OR NEW.state<>'completed' THEN
                RAISE EXCEPTION 'invalid voice action command transition';
              END IF;
              RETURN NEW;
            END $$;

            CREATE TRIGGER trg_voice_action_command_lifecycle
            BEFORE INSERT OR UPDATE OR DELETE ON voice_action_commands
            FOR EACH ROW EXECUTE FUNCTION narration_guard_voice_action_command_v1();

            CREATE FUNCTION narration_check_official_voice_action_closure_v1()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE
              command_row voice_action_commands%ROWTYPE;
            BEGIN
              SELECT * INTO command_row
              FROM voice_action_commands WHERE id=NEW.id;
              IF NOT FOUND OR command_row.state<>'completed' THEN
                RAISE EXCEPTION 'voice action command must be completed by commit';
              END IF;
              IF command_row.preset_key NOT IN (
                'onnx.Junhao','onnx.Zhiming','onnx.Weiguo','onnx.Xiaoyu',
                'onnx.Yuewen','onnx.Lingyu','onnx.Trump','onnx.Ava',
                'onnx.Bella','onnx.Adam','onnx.Nathan','onnx.Soyo',
                'onnx.Saki','onnx.Mortis','onnx.Umiri','onnx.Mei',
                'onnx.Anon','onnx.Arisa'
              ) OR command_row.language_mismatch IS DISTINCT FROM (
                split_part(lower(command_row.target_language), '-', 1) <>
                CASE
                  WHEN command_row.preset_key IN (
                    'onnx.Junhao','onnx.Zhiming','onnx.Weiguo','onnx.Xiaoyu',
                    'onnx.Yuewen','onnx.Lingyu'
                  ) THEN 'zh'
                  WHEN command_row.preset_key IN (
                    'onnx.Trump','onnx.Ava','onnx.Bella','onnx.Adam','onnx.Nathan'
                  ) THEN 'en'
                  ELSE 'ja'
                END
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
                  AND version.provider_id='local-sidecar'
                  AND version.model_id='OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX'
                  AND version.model_revision='f52645cb467506d8e18e746ddd59482685b74e58'
                  AND version.preset_key=command_row.preset_key
                  AND version.language=(CASE
                    WHEN command_row.preset_key IN (
                      'onnx.Junhao','onnx.Zhiming','onnx.Weiguo','onnx.Xiaoyu',
                      'onnx.Yuewen','onnx.Lingyu'
                    ) THEN 'zh-CN'
                    WHEN command_row.preset_key IN (
                      'onnx.Trump','onnx.Ava','onnx.Bella','onnx.Adam','onnx.Nathan'
                    ) THEN 'en'
                    ELSE 'ja-JP'
                  END)
                  AND version.activation_basis='explicit_official_preset_selection'
                  AND version.validation_basis='not_required'
                  AND version.quality_state='pending'
                  AND version.locked_actor IS NULL
                  AND version.locked_at IS NULL
                  AND version.seed=1234
                  AND version.parameters_json ?& ARRAY[
                    'schema_version','official_preset','sample_mode','max_new_frames'
                  ]
                  AND version.parameters_json - ARRAY[
                    'schema_version','official_preset','sample_mode','max_new_frames'
                  ] = '{}'::jsonb
                  AND version.parameters_json->>'schema_version'='narration-official-preset-version/1.0'
                  AND version.parameters_json->>'sample_mode'='fixed'
                  AND version.parameters_json->>'max_new_frames'='375'
                  AND version.parameters_json->'official_preset'->>'preset_id'=command_row.preset_key
                  AND version.parameters_json->'official_preset'->>'repository'='OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX'
                  AND version.parameters_json->'official_preset'->>'revision'='f52645cb467506d8e18e746ddd59482685b74e58'
                  AND version.parameters_json->'official_preset'->>'manifest_path'='browser_poc_manifest.json'
                  AND version.parameters_json->'official_preset'->>'manifest_sha256'='097d80e993dc29f0bae427590b4f77084a161cb578b50d82c29f455d5faa9eee'
                  AND version.parameters_json->'official_preset'->>'model_fingerprint_sha256'='3c76f3e9e1381699c5555287cf66eeb023632d0c3ee94adc6d8ae1b1d455fd7d'
                  AND rights.owner_id=command_row.owner_id
                  AND rights.workspace_id=command_row.workspace_id
                  AND rights.novel_id=command_row.novel_id
                  AND rights.source_kind='official_preset'
                  AND rights.source_identifier=(
                    'hf://OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX@f52645cb467506d8e18e746ddd59482685b74e58/'
                    || 'browser_poc_manifest.json#' || command_row.preset_key
                  )
                  AND rights.notice_version='moss-tts-official-preset-local-use/1.0'
                  AND rights.purpose='private_novel_narration'
                  AND rights.commercial_use IS FALSE
                  AND rights.redistribution IS FALSE
                  AND rights.voice_cloning IS FALSE
                  AND rights.subject_consent_reference IS NULL
                  AND rights.expires_at IS NULL
                  AND rights.risk_flags_json='["COMMERCIAL_DISTRIBUTION_NOT_EVALUATED"]'::jsonb
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

            CREATE CONSTRAINT TRIGGER trg_voice_action_command_closure
            AFTER INSERT OR UPDATE ON voice_action_commands
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION narration_check_official_voice_action_closure_v1();

            CREATE FUNCTION narration_check_official_voice_receipt_closure_v1()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE
              receipt_row voice_action_receipts%ROWTYPE;
            BEGIN
              SELECT * INTO receipt_row
              FROM voice_action_receipts WHERE id=NEW.id;
              IF receipt_row.operation='official_preset_selection' AND NOT EXISTS (
                SELECT 1 FROM voice_action_commands command
                WHERE command.id=receipt_row.resource_id
                  AND command.owner_id=receipt_row.owner_id
                  AND command.workspace_id=receipt_row.workspace_id
                  AND command.operation=receipt_row.operation
                  AND command.request_hash=receipt_row.request_hash
                  AND command.state='completed'
                  AND receipt_row.state='completed'
                  AND command.completed_at=receipt_row.completed_at
              ) THEN
                RAISE EXCEPTION 'official voice receipt command closure failed';
              END IF;
              RETURN NULL;
            END $$;

            CREATE CONSTRAINT TRIGGER trg_official_voice_receipt_closure
            AFTER INSERT OR UPDATE ON voice_action_receipts
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION narration_check_official_voice_receipt_closure_v1();
            """
        )
    )


def upgrade() -> None:
    op.add_column(
        "voice_profile_versions",
        sa.Column(
            "activation_basis",
            sa.String(48),
            nullable=False,
            server_default="preview_confirmed",
        ),
    )
    op.add_column(
        "voice_profile_versions",
        sa.Column(
            "validation_basis",
            sa.String(32),
            nullable=False,
            server_default="pending",
        ),
    )
    # The historical immutability trigger correctly rejects UPDATEs to locked
    # rows. Disable only that table-local trigger inside this transactional DDL
    # migration, perform the exact semantic backfill, then restore it before
    # replacing the function body below. No identity or lifecycle column moves.
    op.execute(
        "ALTER TABLE voice_profile_versions "
        "DISABLE TRIGGER trg_voice_profile_version_locked"
    )
    op.execute(
        "UPDATE voice_profile_versions "
        "SET validation_basis='human_accepted' "
        "WHERE state='locked' AND quality_state='accepted'"
    )
    op.execute(
        "ALTER TABLE voice_profile_versions "
        "ENABLE TRIGGER trg_voice_profile_version_locked"
    )
    op.drop_constraint(
        "ck_voice_profile_version_locked_shape",
        "voice_profile_versions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_voice_profile_version_activation_basis",
        "voice_profile_versions",
        "activation_basis IN ('preview_confirmed','explicit_official_preset_selection',"
        "'character_one_click_generation','experimental_machine_validated')",
    )
    op.create_check_constraint(
        "ck_voice_profile_version_validation_basis",
        "voice_profile_versions",
        "validation_basis IN ('pending','human_accepted','machine_validated','not_required')",
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
    op.create_check_constraint(
        "ck_voice_profile_version_unlocked_activation",
        "voice_profile_versions",
        "state = 'locked' OR (activation_basis='preview_confirmed' AND validation_basis='pending')",
    )
    _replace_voice_version_guard()
    _create_action_commands()


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM voice_action_commands)
                 OR EXISTS (
                   SELECT 1 FROM voice_profile_versions
                   WHERE activation_basis<>'preview_confirmed'
                      OR validation_basis NOT IN ('pending','human_accepted')
                 )
              THEN
                RAISE EXCEPTION
                  'P0 voice downgrade refused: direct-use activation evidence exists';
              END IF;
            END $$;

            DROP TRIGGER trg_official_voice_receipt_closure ON voice_action_receipts;
            DROP FUNCTION narration_check_official_voice_receipt_closure_v1();
            DROP TRIGGER trg_voice_action_command_closure ON voice_action_commands;
            DROP FUNCTION narration_check_official_voice_action_closure_v1();
            DROP TRIGGER trg_voice_action_command_lifecycle ON voice_action_commands;
            DROP FUNCTION narration_guard_voice_action_command_v1();
            """
        )
    )
    op.drop_index(
        "ix_voice_action_commands_scope_created",
        table_name="voice_action_commands",
    )
    op.drop_table("voice_action_commands")
    op.drop_constraint(
        "ck_voice_profile_version_unlocked_activation",
        "voice_profile_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_voice_profile_version_locked_shape",
        "voice_profile_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_voice_profile_version_validation_basis",
        "voice_profile_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_voice_profile_version_activation_basis",
        "voice_profile_versions",
        type_="check",
    )
    op.execute(
        sa.text(
            """
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
            """
        )
    )
    op.drop_column("voice_profile_versions", "validation_basis")
    op.drop_column("voice_profile_versions", "activation_basis")
    op.create_check_constraint(
        "ck_voice_profile_version_locked_shape",
        "voice_profile_versions",
        "state <> 'locked' OR (quality_state = 'accepted' "
        "AND locked_actor IS NOT NULL AND locked_at IS NOT NULL)",
    )
