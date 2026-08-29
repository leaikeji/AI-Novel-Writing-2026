"""Close the writing retrieval loop and add incremental source refreshes.

Revision ID: 20260829_0030
Revises: 20260829_0029
"""

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import VECTOR
from sqlalchemy.dialects import postgresql


revision = "20260829_0030"
down_revision = "20260829_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM embedding_profiles WHERE dimension <> 2048) THEN
            RAISE EXCEPTION 'VM34 requires every embedding profile to use dimension 2048';
          END IF;
          IF EXISTS (SELECT 1 FROM semantic_embeddings WHERE dimension <> 2048) THEN
            RAISE EXCEPTION 'VM34 requires every stored semantic embedding to use dimension 2048';
          END IF;
          IF EXISTS (SELECT 1 FROM novel_chunks LIMIT 1) THEN
            RAISE EXCEPTION 'novel_chunks is not empty; back up and migrate it before VM34';
          END IF;
        END $$;
        """
    )

    op.add_column(
        "embedding_configurations",
        sa.Column(
            "retrieval_policy_version",
            sa.String(120),
            nullable=False,
            server_default="writing-retrieval/2",
        ),
    )
    op.drop_constraint(
        "ck_embedding_profile_dimension", "embedding_profiles", type_="check"
    )
    op.create_check_constraint(
        "ck_embedding_profile_dimension", "embedding_profiles", "dimension = 2048"
    )

    op.add_column(
        "embedding_generation_novels",
        sa.Column("index_version", sa.BigInteger(), nullable=False, server_default="1"),
    )
    op.add_column(
        "embedding_generation_novels",
        sa.Column(
            "authority_digest", sa.String(64), nullable=False, server_default="0" * 64
        ),
    )
    op.add_column(
        "embedding_generation_novels",
        sa.Column(
            "published_digest", sa.String(64), nullable=False, server_default="0" * 64
        ),
    )
    op.add_column(
        "embedding_generation_novels",
        sa.Column("sync_state", sa.String(24), nullable=False, server_default="outdated"),
    )
    op.add_column(
        "embedding_generation_novels",
        sa.Column(
            "pending_refresh_count", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "embedding_generation_novels",
        sa.Column("last_refresh_at", sa.DateTime(timezone=True)),
    )
    op.execute(
        """
        UPDATE embedding_generation_novels
        SET authority_digest = input_digest,
            published_digest = CASE WHEN state = 'ready' THEN input_digest ELSE repeat('0', 64) END,
            sync_state = CASE WHEN state = 'ready' THEN 'current' ELSE 'outdated' END,
            last_refresh_at = CASE WHEN state = 'ready' THEN completed_at ELSE NULL END
        """
    )
    op.drop_constraint(
        "ck_embedding_generation_novel_state",
        "embedding_generation_novels",
        type_="check",
    )
    op.create_check_constraint(
        "ck_embedding_generation_novel_state",
        "embedding_generation_novels",
        "state IN ('pending','building','ready','updating','outdated','partial_failed','failed','cancelled','stale')",
    )
    op.create_check_constraint(
        "ck_embedding_generation_novel_sync_state",
        "embedding_generation_novels",
        "sync_state IN ('current','updating','outdated','partial_failed','revoked')",
    )
    op.create_check_constraint(
        "ck_embedding_generation_novel_refresh_counts",
        "embedding_generation_novels",
        "index_version > 0 AND pending_refresh_count >= 0",
    )
    op.create_check_constraint(
        "ck_embedding_generation_novel_sync_hashes",
        "embedding_generation_novels",
        "char_length(authority_digest) = 64 AND char_length(published_digest) = 64",
    )

    op.add_column("semantic_sources", sa.Column("story_sequence_start", sa.BigInteger()))
    op.add_column("semantic_sources", sa.Column("story_sequence_end", sa.BigInteger()))
    op.execute(
        """
        UPDATE semantic_sources
        SET story_sequence_start = narrative_start,
            story_sequence_end = narrative_end
        WHERE source_type = 'chapter_revision'
          AND source_locator_json ? 'mapping_revision_id'
        """
    )
    op.alter_column(
        "semantic_sources", "narrative_start", new_column_name="narrative_sequence_start"
    )
    op.alter_column(
        "semantic_sources", "narrative_end", new_column_name="narrative_sequence_end"
    )
    op.execute(
        """
        WITH chapter_positions AS (
          SELECT id,
                 row_number() OVER (PARTITION BY novel_id ORDER BY position, id) AS seq
          FROM documents
          WHERE kind = 'chapter'
        )
        UPDATE semantic_sources AS source
        SET narrative_sequence_start = chapter_positions.seq,
            narrative_sequence_end = chapter_positions.seq,
            story_sequence_start = COALESCE(source.story_sequence_start, chapter_positions.seq),
            story_sequence_end = COALESCE(source.story_sequence_end, chapter_positions.seq)
        FROM chapter_positions
        WHERE source.source_type = 'chapter_revision'
          AND source.source_entity_id = chapter_positions.id
        """
    )
    op.drop_constraint("ck_semantic_source_status", "semantic_sources", type_="check")
    op.create_check_constraint(
        "ck_semantic_source_status",
        "semantic_sources",
        "status IN ('pending','current','invalid','retired')",
    )

    op.alter_column(
        "semantic_chunks", "token_count", new_column_name="estimated_token_count"
    )
    op.add_column(
        "semantic_chunks",
        sa.Column(
            "token_estimator_version",
            sa.String(120),
            nullable=False,
            server_default="unicode-char-estimate/1",
        ),
    )
    op.execute(
        """
        UPDATE semantic_chunks
        SET estimated_token_count = GREATEST(
          estimated_token_count,
          CEIL(char_length(content_text)::numeric / 2.0)::integer
        )
        """
    )
    op.drop_constraint("ck_semantic_chunk_bounds", "semantic_chunks", type_="check")
    op.create_check_constraint(
        "ck_semantic_chunk_bounds",
        "semantic_chunks",
        "chunk_index >= 0 AND source_start >= 0 AND source_end > source_start AND estimated_token_count >= 0",
    )
    op.create_index(
        "ix_semantic_chunks_content_trgm",
        "semantic_chunks",
        ["content_text"],
        postgresql_using="gin",
        postgresql_ops={"content_text": "gin_trgm_ops"},
    )

    op.create_table(
        "semantic_source_refreshes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("generation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_type", sa.String(60), nullable=False),
        sa.Column("source_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_revision_id", postgresql.UUID(as_uuid=True)),
        sa.Column("target_content_hash", sa.String(64), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("state", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("pending_source_id", postgresql.UUID(as_uuid=True)),
        sa.Column("failure_code", sa.String(96)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["generation_id", "novel_id"],
            ["embedding_generation_novels.generation_id", "embedding_generation_novels.novel_id"],
            name="fk_semantic_refresh_generation_novel",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["pending_source_id", "generation_id"],
            ["semantic_sources.id", "semantic_sources.generation_id"],
            name="fk_semantic_refresh_pending_source",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "generation_id",
            "novel_id",
            "request_digest",
            name="uq_semantic_refresh_request",
        ),
        sa.UniqueConstraint("id", "generation_id", name="uq_semantic_refresh_generation_scope"),
        sa.CheckConstraint(
            "state IN ('pending','queued','building','ready','published','failed','cancelled','superseded')",
            name="ck_semantic_refresh_state",
        ),
        sa.CheckConstraint(
            "char_length(target_content_hash) = 64 AND char_length(request_digest) = 64",
            name="ck_semantic_refresh_hashes",
        ),
    )
    op.add_column(
        "embedding_index_batches",
        sa.Column("refresh_id", postgresql.UUID(as_uuid=True)),
    )
    op.create_foreign_key(
        "fk_embedding_batch_refresh",
        "embedding_index_batches",
        "semantic_source_refreshes",
        ["refresh_id", "generation_id"],
        ["id", "generation_id"],
        ondelete="CASCADE",
    )

    op.drop_constraint(
        "ck_semantic_embedding_dimension", "semantic_embeddings", type_="check"
    )
    op.create_check_constraint(
        "ck_semantic_embedding_dimension",
        "semantic_embeddings",
        "dimension = 2048 AND vector_dims(embedding) = dimension",
    )

    op.drop_index("ix_novel_chunks_revision", table_name="novel_chunks")
    op.drop_table("novel_chunks")


def downgrade() -> None:
    op.create_table(
        "novel_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "novel_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("novels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "revision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_revisions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("embedding_profile", sa.String(160), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("embedding", VECTOR()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "revision_id",
            "embedding_profile",
            "chunk_index",
            name="uq_novel_chunk_profile_index",
        ),
    )
    op.create_index("ix_novel_chunks_revision", "novel_chunks", ["revision_id"])

    op.drop_constraint(
        "ck_semantic_embedding_dimension", "semantic_embeddings", type_="check"
    )
    op.create_check_constraint(
        "ck_semantic_embedding_dimension",
        "semantic_embeddings",
        "dimension > 0 AND vector_dims(embedding) = dimension",
    )
    op.drop_constraint(
        "fk_embedding_batch_refresh", "embedding_index_batches", type_="foreignkey"
    )
    op.drop_column("embedding_index_batches", "refresh_id")
    op.drop_table("semantic_source_refreshes")

    op.drop_index("ix_semantic_chunks_content_trgm", table_name="semantic_chunks")
    op.drop_constraint("ck_semantic_chunk_bounds", "semantic_chunks", type_="check")
    op.drop_column("semantic_chunks", "token_estimator_version")
    op.alter_column(
        "semantic_chunks", "estimated_token_count", new_column_name="token_count"
    )
    op.create_check_constraint(
        "ck_semantic_chunk_bounds",
        "semantic_chunks",
        "chunk_index >= 0 AND source_start >= 0 AND source_end > source_start AND token_count >= 0",
    )

    op.drop_constraint("ck_semantic_source_status", "semantic_sources", type_="check")
    op.create_check_constraint(
        "ck_semantic_source_status",
        "semantic_sources",
        "status IN ('current','invalid','retired')",
    )
    op.alter_column(
        "semantic_sources", "narrative_sequence_start", new_column_name="narrative_start"
    )
    op.alter_column(
        "semantic_sources", "narrative_sequence_end", new_column_name="narrative_end"
    )
    op.drop_column("semantic_sources", "story_sequence_end")
    op.drop_column("semantic_sources", "story_sequence_start")

    op.drop_constraint(
        "ck_embedding_generation_novel_sync_hashes",
        "embedding_generation_novels",
        type_="check",
    )
    op.drop_constraint(
        "ck_embedding_generation_novel_refresh_counts",
        "embedding_generation_novels",
        type_="check",
    )
    op.drop_constraint(
        "ck_embedding_generation_novel_sync_state",
        "embedding_generation_novels",
        type_="check",
    )
    op.drop_constraint(
        "ck_embedding_generation_novel_state",
        "embedding_generation_novels",
        type_="check",
    )
    op.create_check_constraint(
        "ck_embedding_generation_novel_state",
        "embedding_generation_novels",
        "state IN ('pending','building','ready','failed','cancelled','stale')",
    )
    for column in (
        "last_refresh_at",
        "pending_refresh_count",
        "sync_state",
        "published_digest",
        "authority_digest",
        "index_version",
    ):
        op.drop_column("embedding_generation_novels", column)

    op.drop_constraint(
        "ck_embedding_profile_dimension", "embedding_profiles", type_="check"
    )
    op.create_check_constraint(
        "ck_embedding_profile_dimension", "embedding_profiles", "dimension > 0"
    )
    op.drop_column("embedding_configurations", "retrieval_policy_version")
