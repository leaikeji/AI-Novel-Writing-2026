"""Add formal outline, setting and character authority revisions.

Revision ID: 20260829_0025
Revises: 20260828_0024
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260829_0025"
down_revision = "20260828_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "novels",
        sa.Column("character_catalog_version", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_novel_character_catalog_version", "novels", "character_catalog_version >= 0"
    )
    op.create_unique_constraint(
        "uq_creative_generation_job_novel_scope", "creative_generation_jobs", ["id", "novel_id"]
    )
    op.create_unique_constraint(
        "uq_character_profile_apply_batch_novel_scope",
        "character_profile_apply_batches",
        ["id", "novel_id"],
    )

    op.create_table(
        "novel_outline_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_number", sa.BigInteger(), nullable=False),
        sa.Column("parent_revision_id", postgresql.UUID(as_uuid=True)),
        sa.Column("restored_from_revision_id", postgresql.UUID(as_uuid=True)),
        sa.Column("source_kind", sa.String(40), nullable=False),
        sa.Column("source_job_id", postgresql.UUID(as_uuid=True)),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("target_chapter_count", sa.Integer(), nullable=False),
        sa.Column("background_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("plot_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("highlight_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("character_revision_refs_json", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("character_reference_digest", sa.String(64), nullable=False),
        sa.Column("change_set_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_job_id"], ["creative_generation_jobs.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("novel_id", "revision_number", name="uq_outline_revision_number"),
        sa.UniqueConstraint("novel_id", "idempotency_key", name="uq_outline_revision_idempotency"),
        sa.UniqueConstraint("id", "novel_id", name="uq_outline_revision_novel_scope"),
        sa.CheckConstraint("revision_number > 0", name="ck_outline_revision_number"),
        sa.CheckConstraint("target_chapter_count > 0", name="ck_outline_target_chapters"),
        sa.CheckConstraint("char_length(content_hash) = 64", name="ck_outline_content_hash"),
        sa.CheckConstraint("char_length(request_hash) = 64", name="ck_outline_request_hash"),
    )
    op.create_foreign_key(
        "fk_outline_revision_parent_scope", "novel_outline_revisions", "novel_outline_revisions",
        ["parent_revision_id", "novel_id"], ["id", "novel_id"], deferrable=True, initially="DEFERRED"
    )
    op.create_foreign_key(
        "fk_outline_revision_restore_scope", "novel_outline_revisions", "novel_outline_revisions",
        ["restored_from_revision_id", "novel_id"], ["id", "novel_id"], deferrable=True, initially="DEFERRED"
    )
    op.create_table(
        "novel_outline_heads",
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("current_revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("established_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("establishment_source", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["current_revision_id", "novel_id"],
            ["novel_outline_revisions.id", "novel_outline_revisions.novel_id"],
            name="fk_outline_head_current_scope", deferrable=True, initially="DEFERRED"
        ),
        sa.CheckConstraint("version > 0", name="ck_outline_head_version"),
    )

    op.create_table(
        "novel_setting_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_number", sa.BigInteger(), nullable=False),
        sa.Column("parent_revision_id", postgresql.UUID(as_uuid=True)),
        sa.Column("restored_from_revision_id", postgresql.UUID(as_uuid=True)),
        sa.Column("source_kind", sa.String(40), nullable=False),
        sa.Column("source_job_id", postgresql.UUID(as_uuid=True)),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("schema_id", sa.String(80), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("settings_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("change_set_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_job_id"], ["creative_generation_jobs.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("novel_id", "revision_number", name="uq_setting_revision_number"),
        sa.UniqueConstraint("novel_id", "idempotency_key", name="uq_setting_revision_idempotency"),
        sa.UniqueConstraint("id", "novel_id", name="uq_setting_revision_novel_scope"),
        sa.CheckConstraint("revision_number > 0", name="ck_setting_revision_number"),
        sa.CheckConstraint("schema_version > 0", name="ck_setting_schema_version"),
        sa.CheckConstraint("char_length(content_hash) = 64", name="ck_setting_content_hash"),
        sa.CheckConstraint("char_length(request_hash) = 64", name="ck_setting_request_hash"),
    )
    op.create_foreign_key(
        "fk_setting_revision_parent_scope", "novel_setting_revisions", "novel_setting_revisions",
        ["parent_revision_id", "novel_id"], ["id", "novel_id"], deferrable=True, initially="DEFERRED"
    )
    op.create_foreign_key(
        "fk_setting_revision_restore_scope", "novel_setting_revisions", "novel_setting_revisions",
        ["restored_from_revision_id", "novel_id"], ["id", "novel_id"], deferrable=True, initially="DEFERRED"
    )
    op.create_table(
        "novel_setting_heads",
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("current_revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("established_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("establishment_source", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["current_revision_id", "novel_id"],
            ["novel_setting_revisions.id", "novel_setting_revisions.novel_id"],
            name="fk_setting_head_current_scope", deferrable=True, initially="DEFERRED"
        ),
        sa.CheckConstraint("version > 0", name="ck_setting_head_version"),
    )

    op.create_table(
        "novel_character_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("character_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("character_version", sa.BigInteger(), nullable=False),
        sa.Column("parent_revision_id", postgresql.UUID(as_uuid=True)),
        sa.Column("restored_from_revision_id", postgresql.UUID(as_uuid=True)),
        sa.Column("source_kind", sa.String(40), nullable=False),
        sa.Column("source_job_id", postgresql.UUID(as_uuid=True)),
        sa.Column("source_batch_id", postgresql.UUID(as_uuid=True)),
        sa.Column("operation_key", sa.String(160), nullable=False),
        sa.Column("operation_hash", sa.String(64), nullable=False),
        sa.Column("role_type", sa.String(30), nullable=False),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("details_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("lifecycle_state", sa.String(30), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("change_set_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["character_id", "novel_id"], ["novel_characters.id", "novel_characters.novel_id"], name="fk_character_revision_root_scope", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_job_id"], ["creative_generation_jobs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_batch_id"], ["character_profile_apply_batches.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("character_id", "character_version", name="uq_character_revision_number"),
        sa.UniqueConstraint("novel_id", "operation_key", "character_id", name="uq_character_revision_operation"),
        sa.UniqueConstraint("id", "character_id", "novel_id", name="uq_character_revision_scope"),
        sa.CheckConstraint("character_version > 0", name="ck_character_revision_number"),
        sa.CheckConstraint("char_length(content_hash) = 64 AND char_length(operation_hash) = 64", name="ck_character_revision_hashes"),
    )
    op.create_foreign_key(
        "fk_character_revision_parent_scope", "novel_character_revisions", "novel_character_revisions",
        ["parent_revision_id", "character_id", "novel_id"], ["id", "character_id", "novel_id"],
        deferrable=True, initially="DEFERRED"
    )
    op.create_foreign_key(
        "fk_character_revision_restore_scope", "novel_character_revisions", "novel_character_revisions",
        ["restored_from_revision_id", "character_id", "novel_id"], ["id", "character_id", "novel_id"],
        deferrable=True, initially="DEFERRED"
    )


def downgrade() -> None:
    op.drop_table("novel_character_revisions")
    op.drop_table("novel_setting_heads")
    op.drop_table("novel_setting_revisions")
    op.drop_table("novel_outline_heads")
    op.drop_table("novel_outline_revisions")
    op.drop_constraint("uq_character_profile_apply_batch_novel_scope", "character_profile_apply_batches", type_="unique")
    op.drop_constraint("uq_creative_generation_job_novel_scope", "creative_generation_jobs", type_="unique")
    op.drop_constraint("ck_novel_character_catalog_version", "novels", type_="check")
    op.drop_column("novels", "character_catalog_version")
