"""Add the complete long-form creation workflow domain.

Revision ID: 20260824_0004
Revises: 20260823_0003
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260824_0004"
down_revision = "20260823_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    json_object = sa.text("'{}'::jsonb")
    json_array = sa.text("'[]'::jsonb")

    op.add_column(
        "novels",
        sa.Column("writing_type", sa.String(length=20), nullable=False, server_default="long"),
    )
    op.add_column(
        "novels",
        sa.Column("audience", sa.String(length=20), nullable=False, server_default=""),
    )
    op.add_column(
        "novels",
        sa.Column("genre", sa.String(length=80), nullable=False, server_default=""),
    )
    op.add_column(
        "novels",
        sa.Column("subgenre", sa.String(length=80), nullable=False, server_default=""),
    )
    op.add_column(
        "novels",
        sa.Column("idea", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column("novels", sa.Column("template_key", sa.String(length=120)))
    op.add_column(
        "novels",
        sa.Column("template_name", sa.String(length=160), nullable=False, server_default=""),
    )
    op.add_column(
        "novels",
        sa.Column(
            "template_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=json_object,
        ),
    )
    op.add_column(
        "novels",
        sa.Column("cover_mode", sa.String(length=20), nullable=False, server_default="system"),
    )
    op.add_column("novels", sa.Column("cover_asset_id", postgresql.UUID(as_uuid=True)))
    op.create_foreign_key(
        "fk_novel_cover_asset",
        "novels",
        "media_assets",
        ["cover_asset_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "novels",
        sa.Column("outline_target_chapters", sa.Integer(), nullable=False, server_default="200"),
    )
    op.add_column(
        "novels", sa.Column("highlight", sa.Text(), nullable=False, server_default="")
    )
    op.add_column(
        "novels", sa.Column("background", sa.Text(), nullable=False, server_default="")
    )
    op.add_column(
        "novels", sa.Column("main_plot", sa.Text(), nullable=False, server_default="")
    )
    op.add_column(
        "novels",
        sa.Column("story_ledger_version", sa.BigInteger(), nullable=False, server_default="1"),
    )

    op.add_column(
        "documents",
        sa.Column("status", sa.String(length=30), nullable=False, server_default="draft"),
    )
    op.add_column(
        "documents", sa.Column("version", sa.Integer(), nullable=False, server_default="1")
    )

    op.add_column(
        "chapter_generation_jobs",
        sa.Column(
            "asset_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=json_array,
        ),
    )
    op.add_column(
        "chapter_generation_jobs",
        sa.Column(
            "requested_model_id",
            sa.String(length=120),
            nullable=False,
            server_default="MiniMax-M3",
        ),
    )
    op.add_column(
        "chapter_generation_jobs", sa.Column("actual_model_id", sa.String(length=160))
    )
    op.add_column(
        "chapter_generation_jobs", sa.Column("provider_profile", sa.String(length=160))
    )
    op.add_column(
        "chapter_generation_jobs",
        sa.Column(
            "target_visible_character_count",
            sa.Integer(),
            nullable=False,
            server_default="3000",
        ),
    )
    op.add_column(
        "chapter_generation_jobs",
        sa.Column(
            "output_visible_character_count", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "chapter_generation_jobs",
        sa.Column(
            "validation_state",
            sa.String(length=30),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "chapter_generation_jobs",
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
    )

    op.add_column(
        "intelligence_proposals",
        sa.Column(
            "requested_model_id",
            sa.String(length=120),
            nullable=False,
            server_default="MiniMax-M3",
        ),
    )
    op.add_column(
        "intelligence_proposals", sa.Column("actual_model_id", sa.String(length=160))
    )
    op.add_column(
        "intelligence_proposals", sa.Column("provider_profile", sa.String(length=160))
    )

    op.create_table(
        "novel_creation_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("draft_key", sa.String(length=120), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=30), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("data_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("completed_novel_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["completed_novel_id"], ["novels.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("draft_key"),
    )

    op.create_table(
        "private_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_type", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_private_assets_type_archived", "private_assets", ["asset_type", "archived"]
    )

    op.create_table(
        "asset_presets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "asset_preset_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("preset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["private_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["preset_id"], ["asset_presets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("preset_id", "asset_id", name="uq_asset_preset_asset"),
        sa.UniqueConstraint("preset_id", "position", name="uq_asset_preset_position"),
    )

    op.create_table(
        "outline_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=30), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("target_chapter_count", sa.Integer(), nullable=False),
        sa.Column("background_text", sa.Text(), nullable=False),
        sa.Column("characters_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("plot_text", sa.Text(), nullable=False),
        sa.Column("highlight_text", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("novel_id"),
    )

    op.create_table(
        "novel_characters",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_type", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("novel_id", "name", name="uq_novel_character_name"),
        sa.UniqueConstraint("novel_id", "position", name="uq_novel_character_position"),
    )
    op.create_index(
        "ix_novel_characters_novel_role", "novel_characters", ["novel_id", "role_type"]
    )

    op.create_table(
        "character_relationships",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_character_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_character_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relation_type", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["source_character_id"], ["novel_characters.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["target_character_id"], ["novel_characters.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "novel_id",
            "source_character_id",
            "target_character_id",
            "relation_type",
            name="uq_character_relationship_edge",
        ),
    )
    op.create_index(
        "ix_character_relationships_novel", "character_relationships", ["novel_id"]
    )

    op.create_table(
        "storylines",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("storyline_type", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("novel_id", "position", name="uq_storyline_position"),
    )
    op.create_index("ix_storylines_novel_type", "storylines", ["novel_id", "storyline_type"])

    op.create_table(
        "foreshadows",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("novel_id", "position", name="uq_foreshadow_position"),
    )
    op.create_index("ix_foreshadows_novel_status", "foreshadows", ["novel_id", "status"])

    op.create_table(
        "chapter_creation_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("draft_key", sa.String(length=120), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("volume_id", postgresql.UUID(as_uuid=True)),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=30), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("target_character_count", sa.Integer(), nullable=False),
        sa.Column("expectation_text", sa.Text(), nullable=False),
        sa.Column("outline_text", sa.Text(), nullable=False),
        sa.Column("data_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("completed_document_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["completed_document_id"], ["documents.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["volume_id"], ["volumes.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("draft_key"),
    )
    op.create_index(
        "ix_chapter_creation_novel_state",
        "chapter_creation_drafts",
        ["novel_id", "state"],
    )

    op.create_table(
        "creative_generation_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope_type", sa.String(length=40), nullable=False),
        sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True)),
        sa.Column("document_id", postgresql.UUID(as_uuid=True)),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("state", sa.String(length=30), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("input_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("requested_model_id", sa.String(length=120), nullable=False),
        sa.Column("actual_model_id", sa.String(length=160)),
        sa.Column("provider_profile", sa.String(length=160)),
        sa.Column("output_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("output_text", sa.Text(), nullable=False),
        sa.Column("target_character_count", sa.Integer()),
        sa.Column("output_visible_character_count", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("failure_message", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scope_type",
            "scope_id",
            "kind",
            "input_hash",
            "attempt",
            name="uq_creative_generation_attempt",
        ),
    )
    op.create_index(
        "ix_creative_generation_scope_created",
        "creative_generation_jobs",
        ["scope_type", "scope_id", "created_at"],
    )

    op.create_table(
        "novel_exports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("export_format", sa.String(length=20), nullable=False),
        sa.Column("state", sa.String(length=30), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_novel_exports_novel_created", "novel_exports", ["novel_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_novel_exports_novel_created", table_name="novel_exports")
    op.drop_table("novel_exports")
    op.drop_index("ix_creative_generation_scope_created", table_name="creative_generation_jobs")
    op.drop_table("creative_generation_jobs")
    op.drop_index("ix_chapter_creation_novel_state", table_name="chapter_creation_drafts")
    op.drop_table("chapter_creation_drafts")
    op.drop_index("ix_foreshadows_novel_status", table_name="foreshadows")
    op.drop_table("foreshadows")
    op.drop_index("ix_storylines_novel_type", table_name="storylines")
    op.drop_table("storylines")
    op.drop_index("ix_character_relationships_novel", table_name="character_relationships")
    op.drop_table("character_relationships")
    op.drop_index("ix_novel_characters_novel_role", table_name="novel_characters")
    op.drop_table("novel_characters")
    op.drop_table("outline_drafts")
    op.drop_table("asset_preset_items")
    op.drop_table("asset_presets")
    op.drop_index("ix_private_assets_type_archived", table_name="private_assets")
    op.drop_table("private_assets")
    op.drop_table("novel_creation_drafts")

    op.drop_column("intelligence_proposals", "provider_profile")
    op.drop_column("intelligence_proposals", "actual_model_id")
    op.drop_column("intelligence_proposals", "requested_model_id")

    op.drop_column("chapter_generation_jobs", "attempt")
    op.drop_column("chapter_generation_jobs", "validation_state")
    op.drop_column("chapter_generation_jobs", "output_visible_character_count")
    op.drop_column("chapter_generation_jobs", "target_visible_character_count")
    op.drop_column("chapter_generation_jobs", "provider_profile")
    op.drop_column("chapter_generation_jobs", "actual_model_id")
    op.drop_column("chapter_generation_jobs", "requested_model_id")
    op.drop_column("chapter_generation_jobs", "asset_snapshot")

    op.drop_column("documents", "version")
    op.drop_column("documents", "status")

    op.drop_column("novels", "story_ledger_version")
    op.drop_column("novels", "main_plot")
    op.drop_column("novels", "background")
    op.drop_column("novels", "highlight")
    op.drop_column("novels", "outline_target_chapters")
    op.drop_constraint("fk_novel_cover_asset", "novels", type_="foreignkey")
    op.drop_column("novels", "cover_asset_id")
    op.drop_column("novels", "cover_mode")
    op.drop_column("novels", "template_data")
    op.drop_column("novels", "template_name")
    op.drop_column("novels", "template_key")
    op.drop_column("novels", "idea")
    op.drop_column("novels", "subgenre")
    op.drop_column("novels", "genre")
    op.drop_column("novels", "audience")
    op.drop_column("novels", "writing_type")
