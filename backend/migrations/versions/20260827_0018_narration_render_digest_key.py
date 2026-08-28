"""Freeze the private-text HMAC key identity on each Edition segment.

Revision ID: 20260827_0018
Revises: 20260827_0017

Existing NULL rows are immutable ``narration-render-input/1`` or ``/2``
records.  New v3 rows are required by the application service to carry a key ID; the column
remains nullable so historical data is never rewritten or falsely re-keyed.
"""

from alembic import op
import sqlalchemy as sa


revision = "20260827_0018"
down_revision = "20260827_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "narration_edition_segments",
        sa.Column("render_digest_key_id", sa.String(length=80), nullable=True),
    )
    op.create_check_constraint(
        "ck_narration_edition_segment_digest_key_id",
        "narration_edition_segments",
        "render_digest_key_id IS NULL OR "
        "render_digest_key_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$'",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_narration_edition_segment_digest_key_id",
        "narration_edition_segments",
        type_="check",
    )
    op.drop_column("narration_edition_segments", "render_digest_key_id")
