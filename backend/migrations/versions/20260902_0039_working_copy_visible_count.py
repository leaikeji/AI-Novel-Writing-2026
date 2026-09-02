"""Persist visible character counts for bounded novel-list aggregation.

Revision ID: 20260902_0039
Revises: 20260902_0038

The backfill deliberately mirrors the frozen Python markdown normalization in
``backend.services``.  It streams rows in bounded batches so upgrading a long
novel does not materialize every working-copy body at once.
"""

from __future__ import annotations

import re
from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "20260902_0039"
down_revision = "20260902_0038"
branch_labels = None
depends_on = None


CHECK_NAME = "ck_document_working_copy_visible_character_count"
BACKFILL_BATCH_SIZE = 500


def _markdown_to_text(markdown: str) -> str:
    value = re.sub(r"```.*?```", " ", markdown, flags=re.DOTALL)
    value = re.sub(r"`([^`]*)`", r"\1", value)
    value = re.sub(r"!\[([^]]*)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"^\s{0,3}#{1,6}\s+", "", value, flags=re.MULTILINE)
    value = re.sub(r"[*_~>#-]", "", value)
    return re.sub(r"\n{3,}", "\n\n", value).strip()


def _visible_character_count(markdown: str) -> int:
    return sum(1 for character in _markdown_to_text(markdown) if not character.isspace())


def _backfill_visible_counts() -> None:
    connection = op.get_bind()
    first_page = sa.text(
        """
        SELECT document_id, content_markdown
          FROM document_working_copies
         ORDER BY document_id
         LIMIT :batch_size
        """
    )
    next_page = sa.text(
        """
        SELECT document_id, content_markdown
          FROM document_working_copies
         WHERE document_id > CAST(:last_document_id AS uuid)
         ORDER BY document_id
         LIMIT :batch_size
        """
    )
    update_statement = sa.text(
        """
        UPDATE document_working_copies
           SET visible_character_count = :visible_character_count
         WHERE document_id = :document_id
        """
    )
    last_document_id: object | None = None
    while True:
        statement = first_page if last_document_id is None else next_page
        parameters = {"batch_size": BACKFILL_BATCH_SIZE}
        if last_document_id is not None:
            parameters["last_document_id"] = last_document_id
        batch = connection.execute(statement, parameters).all()
        if not batch:
            break
        payloads: list[dict[str, Any]] = [
            {
                "document_id": row.document_id,
                "visible_character_count": _visible_character_count(
                    str(row.content_markdown or "")
                ),
            }
            for row in batch
        ]
        connection.execute(update_statement, payloads)
        last_document_id = batch[-1].document_id


def upgrade() -> None:
    op.add_column(
        "document_working_copies",
        sa.Column("visible_character_count", sa.BigInteger(), nullable=True),
    )
    _backfill_visible_counts()
    op.alter_column(
        "document_working_copies",
        "visible_character_count",
        existing_type=sa.BigInteger(),
        nullable=False,
        server_default=sa.text("0"),
    )
    op.create_check_constraint(
        CHECK_NAME,
        "document_working_copies",
        "visible_character_count >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        CHECK_NAME,
        "document_working_copies",
        type_="check",
    )
    op.drop_column("document_working_copies", "visible_character_count")
