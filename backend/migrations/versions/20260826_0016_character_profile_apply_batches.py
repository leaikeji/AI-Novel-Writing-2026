"""Add recoverable character profile application audit batches.

Revision ID: 20260826_0016
Revises: 20260826_0015

The migration adds an audit table only.  It does not rewrite existing
characters or trigger model generation.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260826_0016"
down_revision = "20260826_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "character_profile_apply_batches",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("novel_id", sa.UUID(), nullable=False),
        sa.Column("generation_job_id", sa.UUID(), nullable=True),
        sa.Column("restored_from_batch_id", sa.UUID(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column(
            "decisions_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "before_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "after_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "base_versions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "result_versions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "applied_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('applied','restored')",
            name="ck_character_profile_apply_batch_state",
        ),
        sa.ForeignKeyConstraint(
            ["generation_job_id"],
            ["creative_generation_jobs.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["restored_from_batch_id"],
            ["character_profile_apply_batches.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "novel_id",
            "idempotency_key",
            name="uq_character_profile_apply_batch_idempotency",
        ),
    )
    op.create_index(
        "ix_character_profile_apply_batch_novel_created",
        "character_profile_apply_batches",
        ["novel_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_character_profile_apply_batch_novel_created",
        table_name="character_profile_apply_batches",
    )
    op.drop_table("character_profile_apply_batches")
