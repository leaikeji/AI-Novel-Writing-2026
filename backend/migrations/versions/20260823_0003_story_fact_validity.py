"""Add idempotent intelligence commits and revision-bound fact validity.

Revision ID: 20260823_0003
Revises: 20260823_0002
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260823_0003"
down_revision = "20260823_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_revisions",
        sa.Column("restored_from_revision_id", postgresql.UUID(as_uuid=True)),
    )
    op.create_foreign_key(
        "fk_document_revision_restored_from",
        "document_revisions",
        "document_revisions",
        ["restored_from_revision_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_document_revisions_restored_from",
        "document_revisions",
        ["restored_from_revision_id"],
    )

    op.create_table(
        "intelligence_commit_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chapter_revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("commit_key", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=30), nullable=False),
        sa.Column(
            "accepted_item_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "inverse_operations",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("expected_story_ledger_version", sa.BigInteger()),
        sa.Column("committed_at", sa.DateTime(timezone=True)),
        sa.Column("reverted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["chapter_revision_id"], ["document_revisions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"], ["intelligence_proposals.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "proposal_id", "commit_key", name="uq_intelligence_commit_key"
        ),
    )
    op.create_index(
        "ix_intelligence_commit_revision",
        "intelligence_commit_batches",
        ["chapter_revision_id", "state"],
    )

    op.create_table(
        "derived_source_bindings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("derived_entity_type", sa.String(length=40), nullable=False),
        sa.Column("derived_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_chapter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "source_chapter_revision_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("source_content_hash", sa.String(length=64), nullable=False),
        sa.Column("proposal_item_id", postgresql.UUID(as_uuid=True)),
        sa.Column("commit_batch_id", postgresql.UUID(as_uuid=True)),
        sa.Column("validity_state", sa.String(length=30), nullable=False),
        sa.Column("invalidated_at", sa.DateTime(timezone=True)),
        sa.Column("restored_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["commit_batch_id"], ["intelligence_commit_batches.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["derived_entity_id"], ["story_facts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["proposal_item_id"], ["intelligence_proposal_items.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["source_chapter_id"], ["documents.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_chapter_revision_id"],
            ["document_revisions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "derived_entity_type",
            "derived_entity_id",
            "source_chapter_revision_id",
            name="uq_derived_source_entity_revision",
        ),
    )
    op.create_index(
        "ix_derived_source_document_validity",
        "derived_source_bindings",
        ["source_chapter_id", "validity_state"],
    )
    op.create_index(
        "ix_derived_source_revision",
        "derived_source_bindings",
        ["source_chapter_revision_id"],
    )

    required_timestamps = (
        ("novels", "created_at"),
        ("novels", "updated_at"),
        ("volumes", "created_at"),
        ("volumes", "updated_at"),
        ("documents", "created_at"),
        ("documents", "updated_at"),
        ("document_revisions", "created_at"),
        ("document_working_copies", "updated_at"),
        ("story_facts", "created_at"),
        ("novel_chunks", "created_at"),
        ("media_assets", "created_at"),
        ("chapter_briefs", "created_at"),
        ("chapter_briefs", "updated_at"),
        ("chapter_generation_jobs", "created_at"),
        ("candidate_revisions", "created_at"),
        ("intelligence_proposals", "created_at"),
        ("intelligence_proposal_items", "created_at"),
        ("intelligence_commit_batches", "created_at"),
        ("derived_source_bindings", "created_at"),
    )
    for table_name, column_name in required_timestamps:
        op.execute(
            sa.text(
                f'UPDATE "{table_name}" SET "{column_name}" = now() '
                f'WHERE "{column_name}" IS NULL'
            )
        )
        op.alter_column(
            table_name,
            column_name,
            existing_type=sa.DateTime(timezone=True),
            existing_server_default=sa.text("now()"),
            nullable=False,
        )

    op.execute(
        """
        UPDATE document_revisions AS restored
        SET restored_from_revision_id = (
            SELECT prior.id
            FROM document_revisions AS prior
            WHERE prior.document_id = restored.document_id
              AND prior.revision_number < restored.revision_number
              AND prior.content_hash = restored.content_hash
            ORDER BY prior.revision_number DESC
            LIMIT 1
        )
        WHERE restored.source = 'manual_restore'
          AND restored.restored_from_revision_id IS NULL
        """
    )
    op.execute(
        """
        INSERT INTO intelligence_commit_batches (
            id,
            proposal_id,
            chapter_revision_id,
            commit_key,
            state,
            accepted_item_ids,
            inverse_operations,
            committed_at,
            created_at
        )
        SELECT
            proposal.id,
            proposal.id,
            proposal.chapter_revision_id,
            'legacy-' || proposal.id::text,
            'committed',
            jsonb_agg(item.id::text ORDER BY item.position),
            jsonb_build_object(
                'created_story_fact_ids',
                jsonb_agg(item.committed_story_fact_id::text ORDER BY item.position)
            ),
            COALESCE(proposal.reviewed_at, proposal.created_at),
            proposal.created_at
        FROM intelligence_proposals AS proposal
        JOIN intelligence_proposal_items AS item
          ON item.proposal_id = proposal.id
        WHERE item.committed_story_fact_id IS NOT NULL
        GROUP BY proposal.id
        """
    )
    op.execute(
        """
        INSERT INTO derived_source_bindings (
            id,
            derived_entity_type,
            derived_entity_id,
            source_chapter_id,
            source_chapter_revision_id,
            source_content_hash,
            proposal_item_id,
            commit_batch_id,
            validity_state,
            invalidated_at,
            restored_at,
            created_at
        )
        SELECT
            fact.id,
            'story_fact',
            fact.id,
            revision.document_id,
            fact.source_revision_id,
            revision.content_hash,
            item.id,
            batch.id,
            CASE WHEN fact.status = 'active' THEN 'current' ELSE fact.status END,
            CASE WHEN fact.status = 'active' THEN NULL ELSE now() END,
            NULL,
            fact.created_at
        FROM story_facts AS fact
        JOIN document_revisions AS revision
          ON revision.id = fact.source_revision_id
        LEFT JOIN intelligence_proposal_items AS item
          ON item.committed_story_fact_id = fact.id
        LEFT JOIN intelligence_commit_batches AS batch
          ON batch.proposal_id = item.proposal_id
        WHERE fact.source_revision_id IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE derived_source_bindings
        SET validity_state = 'source_superseded',
            invalidated_at = now(),
            restored_at = NULL
        """
    )
    op.execute(
        """
        UPDATE derived_source_bindings AS binding
        SET validity_state = CASE
                WHEN binding.source_chapter_revision_id = working.base_revision_id
                    THEN 'current'
                ELSE 'source_restored'
            END,
            invalidated_at = NULL,
            restored_at = CASE
                WHEN binding.source_chapter_revision_id = working.base_revision_id
                    THEN NULL
                ELSE now()
            END
        FROM document_working_copies AS working
        JOIN document_revisions AS current_revision
          ON current_revision.id = working.base_revision_id
        WHERE binding.source_chapter_id = working.document_id
          AND binding.source_content_hash = current_revision.content_hash
        """
    )
    op.execute(
        """
        UPDATE story_facts AS fact
        SET status = CASE
            WHEN binding.validity_state = 'current' THEN 'active'
            ELSE binding.validity_state
        END
        FROM derived_source_bindings AS binding
        WHERE binding.derived_entity_type = 'story_fact'
          AND binding.derived_entity_id = fact.id
        """
    )


def downgrade() -> None:
    op.drop_index("ix_derived_source_revision", table_name="derived_source_bindings")
    op.drop_index(
        "ix_derived_source_document_validity", table_name="derived_source_bindings"
    )
    op.drop_table("derived_source_bindings")
    op.drop_index(
        "ix_intelligence_commit_revision", table_name="intelligence_commit_batches"
    )
    op.drop_table("intelligence_commit_batches")
    op.drop_index(
        "ix_document_revisions_restored_from", table_name="document_revisions"
    )
    op.drop_constraint(
        "fk_document_revision_restored_from", "document_revisions", type_="foreignkey"
    )
    op.drop_column("document_revisions", "restored_from_revision_id")
