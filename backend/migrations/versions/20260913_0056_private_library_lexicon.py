"""Add scoped lexicon assets, maintenance receipts, and check reports.

Revision ID: 20260913_0056
Revises: 20260912_0055
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260913_0056"
down_revision = "20260912_0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "private_assets",
        sa.Column("scope_kind", sa.String(16), nullable=False, server_default="library"),
    )
    op.add_column(
        "private_assets",
        sa.Column("scope_novel_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "private_assets",
        sa.Column("collection_key", sa.String(120), nullable=True),
    )
    op.add_column(
        "private_assets",
        sa.Column("source_asset_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "private_assets",
        sa.Column("source_version_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_private_asset_scope_novel",
        "private_assets",
        "novels",
        ["scope_novel_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_private_asset_source_asset",
        "private_assets",
        "private_assets",
        ["source_asset_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_private_asset_source_version_scope",
        "private_assets",
        "private_asset_versions",
        ["source_version_id", "source_asset_id"],
        ["id", "asset_id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_private_asset_scope",
        "private_assets",
        "(scope_kind='library' AND scope_novel_id IS NULL) OR "
        "(scope_kind='novel' AND scope_novel_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_private_asset_collection_key",
        "private_assets",
        "collection_key IS NULL OR (char_length(collection_key) BETWEEN 1 AND 120)",
    )
    op.create_check_constraint(
        "ck_private_asset_source_pair",
        "private_assets",
        "(source_asset_id IS NULL AND source_version_id IS NULL) OR "
        "(source_asset_id IS NOT NULL AND source_version_id IS NOT NULL)",
    )
    op.create_index(
        "ix_private_assets_scope",
        "private_assets",
        ["scope_kind", "scope_novel_id", "archived"],
    )
    op.create_index(
        "uq_private_assets_library_collection_key",
        "private_assets",
        ["collection_key"],
        unique=True,
        postgresql_where=sa.text("scope_kind='library' AND collection_key IS NOT NULL"),
    )
    op.create_index(
        "uq_private_assets_novel_collection_key",
        "private_assets",
        ["scope_novel_id", "collection_key"],
        unique=True,
        postgresql_where=sa.text("scope_kind='novel' AND collection_key IS NOT NULL"),
    )
    op.create_index(
        "uq_private_assets_novel_source_copy",
        "private_assets",
        ["scope_novel_id", "source_asset_id"],
        unique=True,
        postgresql_where=sa.text(
            "scope_kind='novel' AND source_asset_id IS NOT NULL"
        ),
    )

    op.create_table(
        "library_change_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope_kind", sa.String(16), nullable=False),
        sa.Column("scope_novel_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("session_id", sa.String(200), nullable=False),
        sa.Column("author_text_hash", sa.String(64), nullable=False),
        sa.Column("source_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("actions_json", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("state", sa.String(20), nullable=False, server_default="proposed"),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("result_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("undo_of_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["scope_novel_id"], ["novels.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["undo_of_id"], ["library_change_requests.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("request_id", name="uq_library_change_request_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_library_change_idempotency"),
        sa.CheckConstraint(
            "(scope_kind='library' AND scope_novel_id IS NULL) OR "
            "(scope_kind='novel' AND scope_novel_id IS NOT NULL)",
            name="ck_library_change_scope",
        ),
        sa.CheckConstraint(
            "state IN ('proposed','applied','cancelled','conflict')",
            name="ck_library_change_state",
        ),
        sa.CheckConstraint("version > 0", name="ck_library_change_version"),
        sa.CheckConstraint(
            "char_length(author_text_hash)=64 AND char_length(content_hash)=64",
            name="ck_library_change_hashes",
        ),
    )
    op.create_index(
        "ix_library_change_scope_created",
        "library_change_requests",
        ["scope_kind", "scope_novel_id", "created_at"],
    )

    op.create_table(
        "library_check_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_kind", sa.String(24), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_version", sa.BigInteger(), nullable=False),
        sa.Column("text_hash", sa.String(64), nullable=False),
        sa.Column("rules_hash", sa.String(64), nullable=False),
        sa.Column("scanner_version", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("scanned_rule_count", sa.BigInteger(), nullable=False),
        sa.Column("omitted_rule_count", sa.BigInteger(), nullable=False),
        sa.Column("visible_character_count", sa.BigInteger(), nullable=False),
        sa.Column("hits_json", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("decisions_json", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["document_id", "novel_id"],
            ["documents.id", "documents.novel_id"],
            name="fk_library_check_document_scope",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "source_kind IN ('working_copy','candidate','selection_result')",
            name="ck_library_check_source_kind",
        ),
        sa.CheckConstraint(
            "status IN ('complete','incomplete','stale','failed')",
            name="ck_library_check_status",
        ),
        sa.CheckConstraint(
            "source_version >= 0 AND version > 0",
            name="ck_library_check_versions",
        ),
        sa.CheckConstraint(
            "scanned_rule_count >= 0 AND omitted_rule_count >= 0 "
            "AND visible_character_count >= 0",
            name="ck_library_check_coverage",
        ),
        sa.CheckConstraint(
            "char_length(text_hash)=64 AND char_length(rules_hash)=64",
            name="ck_library_check_hashes",
        ),
        sa.UniqueConstraint(
            "novel_id", "document_id", "source_kind", "source_id", "source_version",
            "text_hash", "rules_hash", "scanner_version",
            name="uq_library_check_input",
        ),
    )
    op.create_index(
        "ix_library_check_document_created",
        "library_check_reports",
        ["novel_id", "document_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("library_check_reports")
    op.drop_table("library_change_requests")
    op.drop_index("uq_private_assets_novel_collection_key", table_name="private_assets")
    op.drop_index("uq_private_assets_novel_source_copy", table_name="private_assets")
    op.drop_index("uq_private_assets_library_collection_key", table_name="private_assets")
    op.drop_index("ix_private_assets_scope", table_name="private_assets")
    op.drop_constraint("ck_private_asset_collection_key", "private_assets", type_="check")
    op.drop_constraint("ck_private_asset_source_pair", "private_assets", type_="check")
    op.drop_constraint("ck_private_asset_scope", "private_assets", type_="check")
    op.drop_constraint("fk_private_asset_source_version_scope", "private_assets", type_="foreignkey")
    op.drop_constraint("fk_private_asset_source_asset", "private_assets", type_="foreignkey")
    op.drop_constraint("fk_private_asset_scope_novel", "private_assets", type_="foreignkey")
    for name in (
        "source_version_id", "source_asset_id", "collection_key",
        "scope_novel_id", "scope_kind",
    ):
        op.drop_column("private_assets", name)
