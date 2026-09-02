"""Add the bounded Story Ledger page index.

Revision ID: 20260902_0037
Revises: 20260901_0036

The index matches the authoritative ``story-fact/2`` page query.  This
migration changes no rows or columns and is fully reversible.
"""

from alembic import op
import sqlalchemy as sa


revision = "20260902_0037"
down_revision = "20260901_0036"
branch_labels = None
depends_on = None


INDEX_NAME = "ix_story_facts_novel_created_v2"


def upgrade() -> None:
    op.create_index(
        INDEX_NAME,
        "story_facts",
        ["novel_id", sa.text("created_at DESC"), sa.text("id DESC")],
        postgresql_where=sa.text("schema_version = 'story-fact/2'"),
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="story_facts")
