"""Add auditable automatic relationship generation provenance.

Revision ID: 20260824_0008
Revises: 20260824_0007
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260824_0008"
down_revision = "20260824_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "character_relationships",
        sa.Column(
            "manual_override",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "character_relationships",
        sa.Column("confidence", sa.Integer(), nullable=True),
    )
    op.add_column(
        "character_relationships",
        sa.Column(
            "evidence_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "character_relationships",
        sa.Column("source_generation_job_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_character_relationship_generation_job",
        "character_relationships",
        "creative_generation_jobs",
        ["source_generation_job_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_character_relationships_generation_job",
        "character_relationships",
        ["source_generation_job_id"],
    )

    op.add_column(
        "character_relationship_revisions",
        sa.Column(
            "manual_override",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "character_relationship_revisions",
        sa.Column("confidence", sa.Integer(), nullable=True),
    )
    op.add_column(
        "character_relationship_revisions",
        sa.Column(
            "evidence_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "character_relationship_revisions",
        sa.Column("source_generation_job_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_character_relationship_revision_generation_job",
        "character_relationship_revisions",
        "creative_generation_jobs",
        ["source_generation_job_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_character_relationship_revision_generation_job",
        "character_relationship_revisions",
        type_="foreignkey",
    )
    for column_name in (
        "source_generation_job_id",
        "evidence_json",
        "confidence",
        "manual_override",
    ):
        op.drop_column("character_relationship_revisions", column_name)

    op.drop_index(
        "ix_character_relationships_generation_job",
        table_name="character_relationships",
    )
    op.drop_constraint(
        "fk_character_relationship_generation_job",
        "character_relationships",
        type_="foreignkey",
    )
    for column_name in (
        "source_generation_job_id",
        "evidence_json",
        "confidence",
        "manual_override",
    ):
        op.drop_column("character_relationships", column_name)
