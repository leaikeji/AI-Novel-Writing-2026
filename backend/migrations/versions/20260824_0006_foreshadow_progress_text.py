"""Persist narrative progress notes for foreshadows.

Revision ID: 20260824_0006
Revises: 20260824_0005
"""

from alembic import op
import sqlalchemy as sa


revision = "20260824_0006"
down_revision = "20260824_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "foreshadows",
        sa.Column("latest_progress", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("foreshadows", "latest_progress")
