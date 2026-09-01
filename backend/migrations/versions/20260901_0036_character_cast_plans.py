"""Add recoverable whole-book character cast planning authority.

Revision ID: 20260901_0036
Revises: 20260830_0035

This PostgreSQL-only migration creates durable records and guards. It never
calls a model, binds a voice, accesses the network, or processes media.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260901_0036"
down_revision = "20260830_0035"
branch_labels = None
depends_on = None


LOCAL_OWNER = "29cf94d9-a5c9-54ec-912c-5dfff8738c4c"
LOCAL_WORKSPACE = "f0e2e632-bc99-52d2-9916-bb906aa4da6e"


def upgrade() -> None:
    op.create_table(
        "character_cast_plan_commands",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("timeline_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("state", sa.String(40), nullable=False, server_default="reserved"),
        sa.Column("character_catalog_version", sa.BigInteger(), nullable=False),
        sa.Column("settings_version", sa.BigInteger(), nullable=False),
        sa.Column("catalog_fingerprint", sa.String(64), nullable=False),
        sa.Column("workspace_digest", sa.String(64), nullable=False),
        sa.Column("settings_digest", sa.String(64), nullable=False),
        sa.Column("bindings_digest", sa.String(64), nullable=False),
        sa.Column("progress_current", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_total", sa.Integer(), nullable=False),
        sa.Column(
            "warnings_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("failure_code", sa.String(96)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["novel_id", "owner_id", "workspace_id"],
            ["novels.id", "novels.owner_id", "novels.workspace_id"],
            name="fk_character_cast_plan_novel_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["timeline_id", "novel_id"],
            ["story_timelines.id", "story_timelines.novel_id"],
            name="fk_character_cast_plan_timeline_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "owner_id",
            "workspace_id",
            "novel_id",
            "idempotency_key",
            name="uq_character_cast_plan_idempotency",
        ),
        sa.UniqueConstraint(
            "id", "novel_id", name="uq_character_cast_plan_novel_guard"
        ),
        sa.CheckConstraint(
            f"owner_id='{LOCAL_OWNER}'::uuid AND workspace_id='{LOCAL_WORKSPACE}'::uuid",
            name="ck_character_cast_plan_fixed_local_scope",
        ),
        sa.CheckConstraint(
            "mode='fill_and_deduplicate'",
            name="ck_character_cast_plan_mode",
        ),
        sa.CheckConstraint(
            "state IN ('reserved','analyzing','ready_applied',"
            "'ready_applied_with_warnings','ready_unapplied','failed','superseded')",
            name="ck_character_cast_plan_state",
        ),
        sa.CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$' "
            "AND request_hash ~ '^[0-9a-f]{64}$' "
            "AND catalog_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND workspace_digest ~ '^[0-9a-f]{64}$' "
            "AND settings_digest ~ '^[0-9a-f]{64}$' "
            "AND bindings_digest ~ '^[0-9a-f]{64}$'",
            name="ck_character_cast_plan_digests",
        ),
        sa.CheckConstraint(
            "character_catalog_version >= 0 AND settings_version >= 0 "
            "AND progress_total > 0 AND progress_current >= 0 "
            "AND progress_current <= progress_total",
            name="ck_character_cast_plan_versions_progress",
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR failure_code ~ '^[A-Z][A-Z0-9_]{0,95}$'",
            name="ck_character_cast_plan_failure_code",
        ),
        sa.CheckConstraint(
            "(state IN ('reserved','analyzing') AND completed_at IS NULL "
            "AND failure_code IS NULL) OR "
            "(state='failed' AND completed_at IS NOT NULL AND failure_code IS NOT NULL) OR "
            "(state IN ('ready_applied','ready_applied_with_warnings',"
            "'ready_unapplied','superseded') AND completed_at IS NOT NULL "
            "AND failure_code IS NULL)",
            name="ck_character_cast_plan_terminal_shape",
        ),
    )
    op.create_index(
        "ix_character_cast_plan_scope_created",
        "character_cast_plan_commands",
        ["owner_id", "workspace_id", "novel_id", "created_at"],
    )
    op.create_index(
        "uq_character_cast_plan_active",
        "character_cast_plan_commands",
        ["novel_id", "timeline_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('reserved','analyzing')"),
    )

    op.create_table(
        "character_cast_plan_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("priority_rank", sa.Integer(), nullable=False),
        sa.Column("target_key", sa.String(64), nullable=False),
        sa.Column("target_kind", sa.String(16), nullable=False),
        sa.Column("character_id", postgresql.UUID(as_uuid=True)),
        sa.Column("character_name", sa.String(240)),
        sa.Column("role_type", sa.String(30)),
        sa.Column("expected_binding_version", sa.BigInteger(), nullable=False),
        sa.Column("workspace_digest", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_fence", postgresql.UUID(as_uuid=True)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("brief_schema_version", sa.String(80)),
        sa.Column("brief_json", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("model_evidence_json", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("model_evidence_digest", sa.String(64)),
        sa.Column("language", sa.String(40)),
        sa.Column("selected_preset_key", sa.String(160)),
        sa.Column("score_milli", sa.Integer()),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True)),
        sa.Column("voice_version_id", postgresql.UUID(as_uuid=True)),
        sa.Column("voice_source_type", sa.String(20)),
        sa.Column("current_preset_key", sa.String(160)),
        sa.Column("voice_action_command_id", postgresql.UUID(as_uuid=True)),
        sa.Column("warning_code", sa.String(96)),
        sa.Column("failure_code", sa.String(96)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["command_id", "novel_id"],
            ["character_cast_plan_commands.id", "character_cast_plan_commands.novel_id"],
            name="fk_character_cast_plan_item_command_scope",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["character_id", "novel_id"],
            ["novel_characters.id", "novel_characters.novel_id"],
            name="fk_character_cast_plan_item_character_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["voice_version_id", "profile_id"],
            ["voice_profile_versions.id", "voice_profile_versions.profile_id"],
            name="fk_character_cast_plan_item_voice_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["voice_action_command_id"],
            ["voice_action_commands.id"],
            name="fk_character_cast_plan_item_action_command",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "command_id", "position", name="uq_character_cast_plan_item_position"
        ),
        sa.UniqueConstraint(
            "command_id", "target_key", name="uq_character_cast_plan_item_target"
        ),
        sa.CheckConstraint(
            "target_kind IN ('narrator','character') AND "
            "((target_kind='narrator' AND target_key='narrator' "
            "AND character_id IS NULL AND character_name IS NULL AND role_type IS NULL) OR "
            "(target_kind='character' AND character_id IS NOT NULL "
            "AND target_key=('character:'||character_id::text) "
            "AND character_name IS NOT NULL AND role_type IS NOT NULL))",
            name="ck_character_cast_plan_item_target",
        ),
        sa.CheckConstraint(
            "state IN ('pending','analyzing','preserved','scored','assigned','blocked')",
            name="ck_character_cast_plan_item_state",
        ),
        sa.CheckConstraint(
            "position >= 0 AND priority_rank >= 0 AND attempt >= 0 "
            "AND expected_binding_version >= 0",
            name="ck_character_cast_plan_item_counters",
        ),
        sa.CheckConstraint(
            "workspace_digest ~ '^[0-9a-f]{64}$' "
            "AND (model_evidence_digest IS NULL "
            "OR model_evidence_digest ~ '^[0-9a-f]{64}$')",
            name="ck_character_cast_plan_item_digests",
        ),
        sa.CheckConstraint(
            "(state='analyzing' AND lease_fence IS NOT NULL "
            "AND lease_expires_at IS NOT NULL) OR "
            "(state<>'analyzing' AND lease_fence IS NULL AND lease_expires_at IS NULL)",
            name="ck_character_cast_plan_item_lease",
        ),
        sa.CheckConstraint(
            "(profile_id IS NULL AND voice_version_id IS NULL) OR "
            "(profile_id IS NOT NULL AND voice_version_id IS NOT NULL)",
            name="ck_character_cast_plan_item_voice_shape",
        ),
        sa.CheckConstraint(
            "voice_source_type IS NULL OR voice_source_type IN ('preset','uploaded','generated')",
            name="ck_character_cast_plan_item_voice_source",
        ),
        sa.CheckConstraint(
            "brief_schema_version IS NULL OR brief_schema_version IN "
            "('character-voice-brief/1','narrator-voice-brief/1')",
            name="ck_character_cast_plan_item_brief_schema",
        ),
        sa.CheckConstraint(
            "selected_preset_key IS NULL OR "
            "selected_preset_key ~ '^onnx\\.[A-Za-z][A-Za-z0-9]{0,79}$'",
            name="ck_character_cast_plan_item_preset",
        ),
        sa.CheckConstraint(
            "score_milli IS NULL OR (score_milli >= 0 AND score_milli <= 1000)",
            name="ck_character_cast_plan_item_score",
        ),
        sa.CheckConstraint(
            "warning_code IS NULL OR warning_code ~ '^[A-Z][A-Z0-9_]{0,95}$'",
            name="ck_character_cast_plan_item_warning_code",
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR failure_code ~ '^[A-Z][A-Z0-9_]{0,95}$'",
            name="ck_character_cast_plan_item_failure_code",
        ),
    )
    op.create_index(
        "ix_character_cast_plan_items_command_state",
        "character_cast_plan_items",
        ["command_id", "state", "position"],
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM character_cast_plan_commands LIMIT 1) THEN
            RAISE EXCEPTION 'character cast plan downgrade refused: 0036 evidence exists';
          END IF;
        END $$;
        """
    )
    op.drop_index(
        "ix_character_cast_plan_items_command_state",
        table_name="character_cast_plan_items",
    )
    op.drop_table("character_cast_plan_items")
    op.drop_index(
        "uq_character_cast_plan_active",
        table_name="character_cast_plan_commands",
    )
    op.drop_index(
        "ix_character_cast_plan_scope_created",
        table_name="character_cast_plan_commands",
    )
    op.drop_table("character_cast_plan_commands")
