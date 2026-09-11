"""Bind whole-novel purge audits to a verified backup receipt.

Revision ID: 20260911_0053
Revises: 20260910_0052
"""

from alembic import op
import sqlalchemy as sa


revision = "20260911_0053"
down_revision = "20260910_0052"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "novel_deletion_audits",
        sa.Column("backup_receipt_sha256", sa.String(64)),
    )
    op.create_check_constraint(
        "ck_novel_deletion_backup_receipt_hash",
        "novel_deletion_audits",
        "backup_receipt_sha256 IS NULL OR backup_receipt_sha256 ~ '^[0-9a-f]{64}$'",
    )


def downgrade():
    raise RuntimeError(
        "novel purge backup receipt evidence is forward-only; restore the pre-0053 backup"
    )
