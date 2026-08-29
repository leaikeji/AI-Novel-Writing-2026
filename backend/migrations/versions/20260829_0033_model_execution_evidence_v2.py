"""Add structured public model execution evidence to writing jobs.

Revision ID: 20260829_0033
Revises: 20260829_0032

Historical jobs remain unchanged.  New application code writes the evidence
object after the Agent call; no model or network operation runs in migration.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260829_0033"
down_revision = "20260829_0032"
branch_labels = None
depends_on = None


GENERATION_TABLES = (
    "chapter_generation_jobs",
    "intelligence_proposals",
    "creative_generation_jobs",
)


def upgrade() -> None:
    for table_name in GENERATION_TABLES:
        op.add_column(
            table_name,
            sa.Column(
                "model_evidence_json",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=True,
            ),
        )


def downgrade() -> None:
    for table_name in reversed(GENERATION_TABLES):
        op.drop_column(table_name, "model_evidence_json")
