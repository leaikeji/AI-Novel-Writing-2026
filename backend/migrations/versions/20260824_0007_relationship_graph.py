"""Add versioned relationship semantics and saved graph layouts.

Revision ID: 20260824_0007
Revises: 20260824_0006
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260824_0007"
down_revision = "20260824_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "novel_characters",
        sa.Column(
            "lifecycle_state",
            sa.String(length=30),
            nullable=False,
            server_default="active",
        ),
    )
    op.add_column(
        "novel_characters",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.add_column(
        "character_relationships",
        sa.Column(
            "directionality",
            sa.String(length=24),
            nullable=False,
            server_default="legacy_unspecified",
        ),
    )
    op.add_column(
        "character_relationships",
        sa.Column(
            "relation_kind",
            sa.String(length=30),
            nullable=False,
            server_default="other",
        ),
    )
    op.add_column(
        "character_relationships",
        sa.Column("label", sa.String(length=80), nullable=False, server_default=""),
    )
    op.add_column(
        "character_relationships",
        sa.Column(
            "normalized_label",
            sa.String(length=80),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "character_relationships",
        sa.Column(
            "relation_pair_key",
            sa.String(length=73),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "character_relationships",
        sa.Column(
            "status",
            sa.String(length=24),
            nullable=False,
            server_default="active",
        ),
    )
    op.add_column(
        "character_relationships",
        sa.Column(
            "created_by",
            sa.String(length=24),
            nullable=False,
            server_default="manual",
        ),
    )
    op.add_column(
        "character_relationships",
        sa.Column("source_chapter_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "character_relationships",
        sa.Column("proposal_item_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "character_relationships",
        sa.Column("current_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "character_relationships",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                lower(btrim(relation_type)) AS clean_label,
                row_number() OVER (
                    PARTITION BY novel_id, source_character_id, target_character_id,
                        lower(btrim(relation_type))
                    ORDER BY created_at, id
                ) AS duplicate_rank
            FROM character_relationships
        )
        UPDATE character_relationships AS relationship
        SET
            label = relationship.relation_type,
            normalized_label = CASE
                WHEN ranked.duplicate_rank = 1 THEN ranked.clean_label
                ELSE left(ranked.clean_label, 55) || '#legacy-' || left(relationship.id::text, 8)
            END,
            relation_pair_key = least(
                relationship.source_character_id::text,
                relationship.target_character_id::text
            ) || ':' || greatest(
                relationship.source_character_id::text,
                relationship.target_character_id::text
            )
        FROM ranked
        WHERE ranked.id = relationship.id
        """
    )

    op.drop_constraint(
        "uq_character_relationship_edge",
        "character_relationships",
        type_="unique",
    )
    op.drop_index("ix_character_relationships_novel", table_name="character_relationships")
    op.create_check_constraint(
        "ck_character_relationship_distinct_endpoints",
        "character_relationships",
        "source_character_id <> target_character_id",
    )
    op.create_index(
        "ix_character_relationships_novel",
        "character_relationships",
        ["novel_id", "archived_at"],
    )
    op.create_index(
        "ix_character_relationships_pair",
        "character_relationships",
        ["novel_id", "relation_pair_key"],
    )
    op.create_index(
        "uq_character_relationship_active_semantics",
        "character_relationships",
        [
            "novel_id",
            "source_character_id",
            "target_character_id",
            "directionality",
            "relation_kind",
            "normalized_label",
        ],
        unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
    )
    op.create_foreign_key(
        "fk_character_relationship_source_revision",
        "character_relationships",
        "document_revisions",
        ["source_chapter_revision_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_character_relationship_proposal_item",
        "character_relationships",
        "intelligence_proposal_items",
        ["proposal_item_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "character_relationship_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relationship_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("source_character_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_character_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("directionality", sa.String(length=24), nullable=False),
        sa.Column("relation_kind", sa.String(length=30), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column(
            "change_reason",
            sa.String(length=30),
            nullable=False,
            server_default="editorial",
        ),
        sa.Column(
            "changed_by",
            sa.String(length=24),
            nullable=False,
            server_default="manual",
        ),
        sa.Column("source_chapter_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("proposal_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["relationship_id"], ["character_relationships.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_chapter_revision_id"], ["document_revisions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["proposal_item_id"], ["intelligence_proposal_items.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "relationship_id",
            "revision_number",
            name="uq_character_relationship_revision_number",
        ),
    )
    op.create_index(
        "ix_character_relationship_revision_source",
        "character_relationship_revisions",
        ["source_chapter_revision_id"],
    )
    # Preserve every pre-migration relationship as revision 1. Reusing the
    # relationship UUID is safe because revisions live in a separate table and
    # avoids depending on an additional UUID extension during installation.
    op.execute(
        """
        INSERT INTO character_relationship_revisions (
            id,
            relationship_id,
            revision_number,
            source_character_id,
            target_character_id,
            directionality,
            relation_kind,
            label,
            description,
            status,
            change_reason,
            changed_by,
            created_at
        )
        SELECT
            id,
            id,
            1,
            source_character_id,
            target_character_id,
            directionality,
            relation_kind,
            label,
            description,
            status,
            'migration',
            'import',
            created_at
        FROM character_relationships
        """
    )
    op.execute(
        """
        UPDATE character_relationships
        SET current_revision_id = id
        """
    )
    op.create_foreign_key(
        "fk_character_relationship_current_revision",
        "character_relationships",
        "character_relationship_revisions",
        ["current_revision_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "relationship_graph_views",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "name", sa.String(length=120), nullable=False, server_default="默认视图"
        ),
        sa.Column(
            "layout_algorithm",
            sa.String(length=40),
            nullable=False,
            server_default="force_atlas_2",
        ),
        sa.Column(
            "random_seed",
            sa.String(length=64),
            nullable=False,
            server_default="relationship-v1",
        ),
        sa.Column("zoom", sa.Float(), nullable=False, server_default="1"),
        sa.Column("pan_x", sa.Float(), nullable=False, server_default="0"),
        sa.Column("pan_y", sa.Float(), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("novel_id", "name", name="uq_relationship_graph_view_name"),
    )
    op.create_index(
        "ix_relationship_graph_views_novel",
        "relationship_graph_views",
        ["novel_id"],
    )

    op.create_table(
        "relationship_graph_positions",
        sa.Column("view_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("character_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("x", sa.Float(), nullable=False),
        sa.Column("y", sa.Float(), nullable=False),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(
            ["view_id"], ["relationship_graph_views.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["character_id"], ["novel_characters.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("view_id", "character_id"),
    )
    op.create_index(
        "ix_relationship_graph_positions_character",
        "relationship_graph_positions",
        ["character_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_relationship_graph_positions_character",
        table_name="relationship_graph_positions",
    )
    op.drop_table("relationship_graph_positions")
    op.drop_index("ix_relationship_graph_views_novel", table_name="relationship_graph_views")
    op.drop_table("relationship_graph_views")

    op.drop_constraint(
        "fk_character_relationship_current_revision",
        "character_relationships",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_character_relationship_revision_source",
        table_name="character_relationship_revisions",
    )
    op.drop_table("character_relationship_revisions")

    op.drop_constraint(
        "fk_character_relationship_proposal_item",
        "character_relationships",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_character_relationship_source_revision",
        "character_relationships",
        type_="foreignkey",
    )
    op.drop_index(
        "uq_character_relationship_active_semantics",
        table_name="character_relationships",
    )
    op.drop_index("ix_character_relationships_pair", table_name="character_relationships")
    op.drop_index("ix_character_relationships_novel", table_name="character_relationships")
    op.drop_constraint(
        "ck_character_relationship_distinct_endpoints",
        "character_relationships",
        type_="check",
    )
    op.create_index(
        "ix_character_relationships_novel",
        "character_relationships",
        ["novel_id"],
    )
    op.create_unique_constraint(
        "uq_character_relationship_edge",
        "character_relationships",
        ["novel_id", "source_character_id", "target_character_id", "relation_type"],
    )

    for column_name in (
        "archived_at",
        "current_revision_id",
        "proposal_item_id",
        "source_chapter_revision_id",
        "created_by",
        "status",
        "relation_pair_key",
        "normalized_label",
        "label",
        "relation_kind",
        "directionality",
    ):
        op.drop_column("character_relationships", column_name)

    op.drop_column("novel_characters", "archived_at")
    op.drop_column("novel_characters", "lifecycle_state")
