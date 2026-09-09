"""Add workspace-scoped Qwen TTS cloud provider profiles.

Revision ID: 20260908_0044
Revises: 20260908_0043
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260908_0044"
down_revision = "20260908_0043"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tts_cloud_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("protocol", sa.String(length=80), nullable=False),
        sa.Column("base_url", sa.String(length=2048), nullable=False),
        sa.Column("credential_ref", sa.String(length=240), nullable=True),
        sa.Column("api_key_last4", sa.String(length=4), nullable=True),
        sa.Column("api_key_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("quality_model_id", sa.String(length=240), nullable=False),
        sa.Column("speed_model_id", sa.String(length=240), nullable=True),
        sa.Column(
            "quality_test_state",
            sa.String(length=16),
            server_default="untested",
            nullable=False,
        ),
        sa.Column(
            "speed_test_state",
            sa.String(length=16),
            server_default="untested",
            nullable=False,
        ),
        sa.Column(
            "lifecycle_state",
            sa.String(length=16),
            server_default="draft",
            nullable=False,
        ),
        sa.Column("verification_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("failure_code", sa.String(length=96), nullable=True),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_operation_key", sa.String(length=160), nullable=True),
        sa.Column("last_operation_hash", sa.String(length=64), nullable=True),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "protocol = 'qwen_audio_native_http/1'",
            name="ck_tts_cloud_profile_protocol",
        ),
        sa.CheckConstraint(
            "lifecycle_state IN ('draft','verified','active','disabled')",
            name="ck_tts_cloud_profile_lifecycle_state",
        ),
        sa.CheckConstraint(
            "quality_test_state IN ('untested','testing','passed','failed')",
            name="ck_tts_cloud_profile_quality_test_state",
        ),
        sa.CheckConstraint(
            "speed_test_state IN ('untested','testing','passed','failed')",
            name="ck_tts_cloud_profile_speed_test_state",
        ),
        sa.CheckConstraint(
            "api_key_last4 IS NULL OR char_length(api_key_last4) = 4",
            name="ck_tts_cloud_profile_key_last4",
        ),
        sa.CheckConstraint(
            "verification_fingerprint IS NULL OR "
            "char_length(verification_fingerprint) = 64",
            name="ck_tts_cloud_profile_verification_fingerprint",
        ),
        sa.CheckConstraint(
            "last_operation_hash IS NULL OR char_length(last_operation_hash) = 64",
            name="ck_tts_cloud_profile_operation_hash",
        ),
        sa.CheckConstraint("version > 0", name="ck_tts_cloud_profile_version"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id",
            "workspace_id",
            "name",
            name="uq_tts_cloud_profile_scope_name",
        ),
        sa.UniqueConstraint(
            "id",
            "owner_id",
            "workspace_id",
            name="uq_tts_cloud_profile_scope",
        ),
    )
    op.create_index(
        "uq_tts_cloud_profile_active_scope",
        "tts_cloud_profiles",
        ["owner_id", "workspace_id"],
        unique=True,
        postgresql_where=sa.text("lifecycle_state='active'"),
    )


def downgrade():
    op.drop_index(
        "uq_tts_cloud_profile_active_scope",
        table_name="tts_cloud_profiles",
    )
    op.drop_table("tts_cloud_profiles")
