"""Persist author and selected cover preview on novels.

Revision ID: 20260824_0005
Revises: 20260824_0004
"""

from alembic import op
import sqlalchemy as sa


revision = "20260824_0005"
down_revision = "20260824_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "novels",
        sa.Column("author_name", sa.String(length=120), nullable=False, server_default=""),
    )
    op.add_column(
        "novels",
        sa.Column("cover_image_data", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("novels", "cover_image_data")
    op.drop_column("novels", "author_name")
