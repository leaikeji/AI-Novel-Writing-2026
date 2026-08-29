"""Bind character authority revisions to durable name aliases.

Revision ID: 20260829_0029
Revises: 20260829_0028
"""

from __future__ import annotations

import unicodedata
from uuid import uuid4

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260829_0029"
down_revision = "20260829_0028"
branch_labels = None
depends_on = None


def _normalize_alias(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def upgrade() -> None:
    op.add_column(
        "character_aliases",
        sa.Column(
            "source_character_revision_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_character_alias_source_character_revision",
        "character_aliases",
        "novel_character_revisions",
        ["source_character_revision_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    if context.is_offline_mode():
        return

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            SELECT c.id AS character_id,
                   c.novel_id,
                   c.name,
                   r.id AS revision_id
              FROM novel_characters AS c
              JOIN LATERAL (
                    SELECT id
                      FROM novel_character_revisions
                     WHERE novel_id = c.novel_id
                       AND character_id = c.id
                     ORDER BY character_version DESC, created_at DESC, id DESC
                     LIMIT 1
              ) AS r ON TRUE
             WHERE c.lifecycle_state = 'active'
            """
        )
    ).mappings().all()
    existing = {
        (row.character_id, row.normalized_alias): row.id
        for row in connection.execute(
            sa.text(
                "SELECT id, character_id, normalized_alias FROM character_aliases"
            )
        ).mappings()
    }
    affected: set[tuple[object, str]] = set()
    for row in rows:
        normalized = _normalize_alias(str(row.name))
        affected.add((row.novel_id, normalized))
        key = (row.character_id, normalized)
        alias_id = existing.get(key)
        if alias_id is None:
            alias_id = uuid4()
            connection.execute(
                sa.text(
                    """
                    INSERT INTO character_aliases (
                        id, novel_id, character_id, alias, normalized_alias,
                        alias_kind, identity_layer, source,
                        source_character_revision_id, lifecycle_state
                    ) VALUES (
                        :id, :novel_id, :character_id, :alias, :normalized_alias,
                        'official_name', 'public', 'authority_backfill',
                        :revision_id, 'active'
                    )
                    """
                ),
                {
                    "id": alias_id,
                    "novel_id": row.novel_id,
                    "character_id": row.character_id,
                    "alias": row.name,
                    "normalized_alias": normalized,
                    "revision_id": row.revision_id,
                },
            )
            existing[key] = alias_id
        else:
            connection.execute(
                sa.text(
                    """
                    UPDATE character_aliases
                       SET source_character_revision_id = :revision_id
                     WHERE id = :id
                       AND source_character_revision_id IS NULL
                    """
                ),
                {"id": alias_id, "revision_id": row.revision_id},
            )

    for novel_id, normalized in affected:
        character_count = int(
            connection.execute(
                sa.text(
                    """
                    SELECT count(DISTINCT a.character_id)
                      FROM character_aliases AS a
                      JOIN novel_characters AS c
                        ON c.id = a.character_id AND c.novel_id = a.novel_id
                     WHERE a.novel_id = :novel_id
                       AND a.normalized_alias = :normalized_alias
                       AND c.lifecycle_state = 'active'
                    """
                ),
                {"novel_id": novel_id, "normalized_alias": normalized},
            ).scalar_one()
        )
        connection.execute(
            sa.text(
                """
                UPDATE character_aliases AS a
                   SET lifecycle_state = CASE
                       WHEN c.lifecycle_state <> 'active' THEN 'archived'
                       WHEN :character_count > 1 THEN 'conflicted'
                       ELSE 'active'
                   END
                  FROM novel_characters AS c
                 WHERE c.id = a.character_id
                   AND c.novel_id = a.novel_id
                   AND a.novel_id = :novel_id
                   AND a.normalized_alias = :normalized_alias
                """
            ),
            {
                "novel_id": novel_id,
                "normalized_alias": normalized,
                "character_count": character_count,
            },
        )


def downgrade() -> None:
    op.drop_constraint(
        "fk_character_alias_source_character_revision",
        "character_aliases",
        type_="foreignkey",
    )
    op.drop_column("character_aliases", "source_character_revision_id")
