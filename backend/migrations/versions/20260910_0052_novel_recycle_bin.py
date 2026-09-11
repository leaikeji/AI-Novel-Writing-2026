"""Add recoverable novel lifecycle and immutable action receipts.

Revision ID: 20260910_0052
Revises: 20260910_0051
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260910_0052"
down_revision = "20260910_0051"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("novels", sa.Column("recycled_at", sa.DateTime(timezone=True)))
    op.add_column("novels", sa.Column("recycled_by", sa.String(120)))
    op.create_check_constraint(
        "ck_novel_recycle_metadata_pair",
        "novels",
        "(recycled_at IS NULL) = (recycled_by IS NULL)",
    )
    op.create_index(
        "ix_novels_active_scope_updated",
        "novels",
        ["owner_id", "workspace_id", sa.text("updated_at DESC")],
        postgresql_where=sa.text("recycled_at IS NULL"),
    )
    op.create_index(
        "ix_novels_recycled_scope_time",
        "novels",
        ["owner_id", "workspace_id", sa.text("recycled_at DESC"), sa.text("id DESC")],
        postgresql_where=sa.text("recycled_at IS NOT NULL"),
    )
    op.create_table(
        "novel_lifecycle_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("version_before", sa.BigInteger(), nullable=False),
        sa.Column("version_after", sa.BigInteger(), nullable=False),
        sa.Column("title_sha256", sa.String(64), nullable=False),
        sa.Column("actor", sa.String(120), nullable=False),
        sa.Column("idempotency_key", sa.String(120), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("result_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "novel_id", "idempotency_key", name="uq_novel_lifecycle_idempotency"
        ),
        sa.CheckConstraint(
            "action IN ('recycled','restored')", name="ck_novel_lifecycle_action"
        ),
        sa.CheckConstraint(
            "version_before >= 1 AND version_after = version_before + 1",
            name="ck_novel_lifecycle_version_step",
        ),
        sa.CheckConstraint(
            "title_sha256 ~ '^[0-9a-f]{64}$' AND request_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_novel_lifecycle_hashes",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(result_json)='object'",
            name="ck_novel_lifecycle_result_object",
        ),
    )
    op.create_index(
        "ix_novel_lifecycle_novel_time",
        "novel_lifecycle_events",
        ["novel_id", "occurred_at"],
    )
    op.execute(
        r"""
        CREATE FUNCTION novel_lifecycle_events_immutable()
        RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
        BEGIN
          RAISE EXCEPTION 'novel lifecycle events are immutable';
        END $$;
        CREATE TRIGGER trg_novel_lifecycle_events_immutable
        BEFORE UPDATE OR DELETE ON novel_lifecycle_events
        FOR EACH ROW EXECUTE FUNCTION novel_lifecycle_events_immutable();
        CREATE TRIGGER trg_novel_lifecycle_events_no_truncate
        BEFORE TRUNCATE ON novel_lifecycle_events
        FOR EACH STATEMENT EXECUTE FUNCTION novel_lifecycle_events_immutable();
        """
    )


def downgrade():
    raise RuntimeError(
        "novel recycle lifecycle is forward-only; restore the pre-0052 database backup"
    )
