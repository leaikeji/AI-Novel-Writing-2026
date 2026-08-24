"""Follow the AI novelist Agent's effective model for every generation.

Revision ID: 20260825_0009
Revises: 20260824_0008

This is an intentionally one-way migration. Historical profile columns remain
nullable and read-only for one compatibility cycle; new writes use explicit
requested/actual evidence and immutable attempts.
"""

from alembic import op
import sqlalchemy as sa


revision = "20260825_0009"
down_revision = "20260824_0008"
branch_labels = None
depends_on = None


GENERATION_TABLES = (
    "chapter_generation_jobs",
    "intelligence_proposals",
    "creative_generation_jobs",
)


def _add_model_evidence_columns(table_name: str) -> None:
    op.add_column(table_name, sa.Column("execution_agent_id", sa.String(120)))
    op.add_column(table_name, sa.Column("requested_provider_id", sa.String(160)))
    op.add_column(
        table_name,
        sa.Column("generation_contract_version", sa.String(120)),
    )
    op.add_column(table_name, sa.Column("actual_provider_id", sa.String(160)))


def upgrade() -> None:
    for table_name in GENERATION_TABLES:
        _add_model_evidence_columns(table_name)
        op.execute(
            sa.text(
                f"UPDATE {table_name} "
                "SET actual_provider_id = provider_profile "
                "WHERE provider_profile IS NOT NULL"
            )
        )
        op.execute(
            sa.text(
                f"UPDATE {table_name} "
                "SET requested_provider_id = provider_profile "
                "WHERE provider_profile IS NOT NULL "
                "AND actual_model_id IS NOT NULL "
                "AND actual_model_id = requested_model_id"
            )
        )
        op.execute(
            sa.text(
                f"UPDATE {table_name} "
                "SET generation_contract_version = 'legacy-fixed-model-v1'"
            )
        )
        op.alter_column(
            table_name,
            "requested_model_id",
            existing_type=sa.String(120),
            server_default=None,
        )

    op.alter_column(
        "chapter_generation_jobs",
        "model_profile_fingerprint",
        existing_type=sa.String(160),
        nullable=True,
        server_default=None,
    )
    op.alter_column(
        "intelligence_proposals",
        "model_profile_fingerprint",
        existing_type=sa.String(160),
        nullable=True,
        server_default=None,
    )

    op.add_column(
        "intelligence_proposals",
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
    )
    op.alter_column(
        "intelligence_proposals",
        "attempt",
        existing_type=sa.Integer(),
        server_default=None,
    )

    op.drop_constraint(
        "uq_chapter_generation_input",
        "chapter_generation_jobs",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_chapter_generation_attempt",
        "chapter_generation_jobs",
        ["document_id", "kind", "input_hash", "attempt"],
    )

    op.drop_constraint(
        "uq_intelligence_revision_input",
        "intelligence_proposals",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_intelligence_revision_attempt",
        "intelligence_proposals",
        ["chapter_revision_id", "input_hash", "attempt"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "20260825_0009 is a one-way migration; recover data from the pre-migration "
        "backup and fix forward instead of restoring the fixed-model runtime"
    )
