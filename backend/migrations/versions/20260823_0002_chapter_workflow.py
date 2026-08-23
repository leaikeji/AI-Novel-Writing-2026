"""Add the reviewed chapter generation and intelligence workflow.

Revision ID: 20260823_0002
Revises: 20260823_0001
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260823_0002"
down_revision = "20260823_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chapter_briefs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("target_word_count", sa.Integer(), nullable=False),
        sa.Column("expectation_text", sa.Text(), nullable=False),
        sa.Column("outline_text", sa.Text(), nullable=False),
        sa.Column("forbidden_text", sa.Text(), nullable=False),
        sa.Column("role_constraints", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id"),
    )
    op.create_table(
        "chapter_generation_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=30), nullable=False),
        sa.Column("brief_version", sa.Integer(), nullable=False),
        sa.Column("base_revision_id", postgresql.UUID(as_uuid=True)),
        sa.Column("base_draft_version", sa.BigInteger(), nullable=False),
        sa.Column("base_content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "generation_context_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("model_profile_fingerprint", sa.String(length=160), nullable=False),
        sa.Column("failure_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["base_revision_id"], ["document_revisions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id", "kind", "input_hash", name="uq_chapter_generation_input"
        ),
    )
    op.create_index(
        "ix_chapter_generation_document_created",
        "chapter_generation_jobs",
        ["document_id", "created_at"],
    )
    op.create_table(
        "candidate_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("generation_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("base_revision_id", postgresql.UUID(as_uuid=True)),
        sa.Column("base_draft_version", sa.BigInteger(), nullable=False),
        sa.Column("base_content_hash", sa.String(length=64), nullable=False),
        sa.Column("base_content_markdown", sa.Text(), nullable=False),
        sa.Column("content_markdown", sa.Text(), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=30), nullable=False),
        sa.Column("adopted_revision_id", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["adopted_revision_id"], ["document_revisions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["base_revision_id"], ["document_revisions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["generation_job_id"], ["chapter_generation_jobs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("generation_job_id"),
    )
    op.create_index(
        "ix_candidate_document_state", "candidate_revisions", ["document_id", "state"]
    )
    op.create_table(
        "intelligence_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chapter_revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=30), nullable=False),
        sa.Column("model_profile_fingerprint", sa.String(length=160), nullable=False),
        sa.Column("failure_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["chapter_revision_id"], ["document_revisions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "chapter_revision_id", "input_hash", name="uq_intelligence_revision_input"
        ),
    )
    op.create_index(
        "ix_intelligence_document_created",
        "intelligence_proposals",
        ["document_id", "created_at"],
    )
    op.create_table(
        "intelligence_proposal_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("item_type", sa.String(length=40), nullable=False),
        sa.Column("suggested_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("reasoning_summary", sa.Text(), nullable=False),
        sa.Column("review_state", sa.String(length=30), nullable=False),
        sa.Column("committed_story_fact_id", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["committed_story_fact_id"], ["story_facts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["proposal_id"], ["intelligence_proposals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("proposal_id", "position", name="uq_intelligence_item_position"),
    )


def downgrade() -> None:
    op.drop_table("intelligence_proposal_items")
    op.drop_index("ix_intelligence_document_created", table_name="intelligence_proposals")
    op.drop_table("intelligence_proposals")
    op.drop_index("ix_candidate_document_state", table_name="candidate_revisions")
    op.drop_table("candidate_revisions")
    op.drop_index("ix_chapter_generation_document_created", table_name="chapter_generation_jobs")
    op.drop_table("chapter_generation_jobs")
    op.drop_table("chapter_briefs")
