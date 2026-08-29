"""Add immutable private-asset versions and novel bindings.

Revision ID: 20260829_0027
Revises: 20260829_0026
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260829_0027"
down_revision = "20260829_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "private_asset_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("source_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("rights_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("operation_key", sa.String(160), nullable=False),
        sa.Column("operation_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["asset_id"], ["private_assets.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("asset_id", "version_number", name="uq_private_asset_version_number"),
        sa.UniqueConstraint("asset_id", "operation_key", name="uq_private_asset_version_operation"),
        sa.UniqueConstraint("id", "asset_id", name="uq_private_asset_version_scope"),
        sa.CheckConstraint("version_number > 0", name="ck_private_asset_version_number"),
        sa.CheckConstraint("char_length(content_hash) = 64 AND char_length(operation_hash) = 64", name="ck_private_asset_version_hashes"),
    )
    op.add_column("private_assets", sa.Column("current_version_id", postgresql.UUID(as_uuid=True)))
    op.add_column("private_assets", sa.Column("tags_json", postgresql.JSONB(), nullable=False, server_default="[]"))
    op.add_column("private_assets", sa.Column("source_json", postgresql.JSONB(), nullable=False, server_default="{}"))
    op.add_column("private_assets", sa.Column("rights_json", postgresql.JSONB(), nullable=False, server_default="{}"))
    op.create_foreign_key(
        "fk_private_asset_current_version_scope", "private_assets", "private_asset_versions",
        ["current_version_id", "id"], ["id", "asset_id"], deferrable=True, initially="DEFERRED"
    )


    op.add_column("asset_preset_items", sa.Column("asset_version_id", postgresql.UUID(as_uuid=True)))
    op.add_column("asset_preset_items", sa.Column("usage_policy", sa.String(24), nullable=False, server_default="preferred"))
    op.create_foreign_key(
        "fk_asset_preset_item_version_scope", "asset_preset_items", "private_asset_versions",
        ["asset_version_id", "asset_id"], ["id", "asset_id"], ondelete="RESTRICT"
    )
    op.create_check_constraint(
        "ck_asset_preset_item_usage_policy", "asset_preset_items",
        "usage_policy IN ('required','preferred','context_only','prohibited')"
    )

    op.create_table(
        "novel_asset_bindings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("usage_policy", sa.String(24), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("lifecycle_state", sa.String(20), nullable=False, server_default="active"),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("operation_key", sa.String(160), nullable=False),
        sa.Column("operation_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["private_assets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["asset_version_id", "asset_id"], ["private_asset_versions.id", "private_asset_versions.asset_id"], name="fk_novel_asset_binding_version_scope", ondelete="RESTRICT"),
        sa.CheckConstraint("usage_policy IN ('required','preferred','context_only','prohibited')", name="ck_novel_asset_binding_policy"),
        sa.CheckConstraint("lifecycle_state IN ('active','archived')", name="ck_novel_asset_binding_lifecycle"),
        sa.CheckConstraint("position >= 0 AND version > 0", name="ck_novel_asset_binding_versions"),
        sa.CheckConstraint("char_length(operation_hash) = 64", name="ck_novel_asset_binding_hash"),
    )
    op.create_index("uq_novel_asset_binding_active_asset", "novel_asset_bindings", ["novel_id", "asset_id"], unique=True, postgresql_where=sa.text("lifecycle_state='active'"))
    op.create_index("uq_novel_asset_binding_active_position", "novel_asset_bindings", ["novel_id", "position"], unique=True, postgresql_where=sa.text("lifecycle_state='active'"))


def downgrade() -> None:
    op.drop_table("novel_asset_bindings")
    op.drop_constraint("ck_asset_preset_item_usage_policy", "asset_preset_items", type_="check")
    op.drop_constraint("fk_asset_preset_item_version_scope", "asset_preset_items", type_="foreignkey")
    op.drop_column("asset_preset_items", "usage_policy")
    op.drop_column("asset_preset_items", "asset_version_id")
    op.drop_constraint("fk_private_asset_current_version_scope", "private_assets", type_="foreignkey")
    for name in ("rights_json", "source_json", "tags_json", "current_version_id"):
        op.drop_column("private_assets", name)
    op.drop_table("private_asset_versions")
