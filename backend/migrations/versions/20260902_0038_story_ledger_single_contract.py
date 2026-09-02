"""Collapse the Story Ledger onto one physical and wire contract.

Revision ID: 20260902_0038
Revises: 20260902_0037

The migration removes two redundant discriminator/alias columns and rewrites
intelligence commit payload hashes after ``item_overrides`` is removed from the
public command.  It fails closed before changing data when legacy rows cannot
be represented by the single contract.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "20260902_0038"
down_revision = "20260902_0037"
branch_labels = None
depends_on = None


OLD_BINDING_UNIQUE = "uq_derived_source_entity_revision"
NEW_BINDING_UNIQUE = "uq_derived_source_fact_revision"


def _canonical_payload_hash(
    proposal_id: object,
    accepted_item_ids: list[str],
    *,
    include_empty_overrides: bool,
) -> str:
    payload: dict[str, Any] = {
        "proposal_id": str(proposal_id),
        "accepted_item_ids": sorted(accepted_item_ids),
    }
    if include_empty_overrides:
        payload["item_overrides"] = {
            item_id: {} for item_id in sorted(accepted_item_ids)
        }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _commit_rewrites(
    *,
    include_empty_overrides: bool,
) -> list[dict[str, object]]:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            SELECT id, proposal_id, commit_key, accepted_item_ids,
                   inverse_operations
              FROM intelligence_commit_batches
             ORDER BY id
            """
        )
    ).mappings()
    rewrites: list[dict[str, object]] = []
    planned_unique_keys: set[tuple[str, str]] = set()
    for row in rows:
        accepted = row["accepted_item_ids"]
        inverse = row["inverse_operations"]
        if not isinstance(accepted, list) or not all(
            isinstance(item_id, str) and item_id for item_id in accepted
        ):
            raise RuntimeError(
                "0038 requires every intelligence batch accepted_item_ids "
                "value to be a non-empty-string JSON array"
            )
        if not isinstance(inverse, dict):
            raise RuntimeError(
                "0038 requires every intelligence batch inverse_operations "
                "value to be a JSON object"
            )
        payload_hash = _canonical_payload_hash(
            row["proposal_id"],
            accepted,
            include_empty_overrides=include_empty_overrides,
        )
        operation_key = inverse.get("operation_key")
        commit_key = str(row["commit_key"]) if operation_key is not None else payload_hash
        unique_key = (str(row["proposal_id"]), commit_key)
        if unique_key in planned_unique_keys:
            raise RuntimeError(
                "0038 commit hash rewrite would collide within one proposal"
            )
        planned_unique_keys.add(unique_key)
        next_inverse = dict(inverse)
        next_inverse["payload_hash"] = payload_hash
        next_inverse.setdefault("operation_key", None)
        rewrites.append(
            {
                "id": row["id"],
                "commit_key": commit_key,
                "inverse_operations": json.dumps(
                    next_inverse,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            }
        )
    return rewrites


def _apply_commit_rewrites(rewrites: list[dict[str, object]]) -> None:
    connection = op.get_bind()
    statement = sa.text(
        """
        UPDATE intelligence_commit_batches
           SET commit_key = :commit_key,
               inverse_operations = CAST(:inverse_operations AS jsonb)
         WHERE id = :id
        """
    )
    for rewrite in rewrites:
        connection.execute(statement, rewrite)


def _guard_single_contract() -> None:
    connection = op.get_bind()
    non_fact_bindings = connection.scalar(
        sa.text(
            """
            SELECT count(*)
              FROM derived_source_bindings
             WHERE derived_entity_type IS DISTINCT FROM 'story_fact'
            """
        )
    )
    if int(non_fact_bindings or 0):
        raise RuntimeError(
            "0038 cannot remove derived_entity_type while non-story_fact rows exist"
        )
    divergent_relationships = connection.scalar(
        sa.text(
            """
            SELECT count(*)
              FROM character_relationships
             WHERE relation_type IS DISTINCT FROM label
            """
        )
    )
    if int(divergent_relationships or 0):
        raise RuntimeError(
            "0038 cannot remove relation_type while it differs from label"
        )


def upgrade() -> None:
    _guard_single_contract()
    rewrites = _commit_rewrites(include_empty_overrides=False)

    op.drop_constraint(
        OLD_BINDING_UNIQUE,
        "derived_source_bindings",
        type_="unique",
    )
    op.create_unique_constraint(
        NEW_BINDING_UNIQUE,
        "derived_source_bindings",
        ["derived_entity_id", "source_chapter_revision_id"],
    )
    op.drop_column("derived_source_bindings", "derived_entity_type")
    op.drop_column("character_relationships", "relation_type")
    _apply_commit_rewrites(rewrites)


def downgrade() -> None:
    rewrites = _commit_rewrites(include_empty_overrides=True)

    op.add_column(
        "character_relationships",
        sa.Column("relation_type", sa.String(length=80), nullable=True),
    )
    op.execute(
        "UPDATE character_relationships SET relation_type = label "
        "WHERE relation_type IS NULL"
    )
    op.alter_column(
        "character_relationships",
        "relation_type",
        existing_type=sa.String(length=80),
        nullable=False,
    )

    op.add_column(
        "derived_source_bindings",
        sa.Column("derived_entity_type", sa.String(length=40), nullable=True),
    )
    op.execute(
        "UPDATE derived_source_bindings SET derived_entity_type = 'story_fact' "
        "WHERE derived_entity_type IS NULL"
    )
    op.alter_column(
        "derived_source_bindings",
        "derived_entity_type",
        existing_type=sa.String(length=40),
        nullable=False,
    )
    op.drop_constraint(
        NEW_BINDING_UNIQUE,
        "derived_source_bindings",
        type_="unique",
    )
    op.create_unique_constraint(
        OLD_BINDING_UNIQUE,
        "derived_source_bindings",
        [
            "derived_entity_type",
            "derived_entity_id",
            "source_chapter_revision_id",
        ],
    )
    _apply_commit_rewrites(rewrites)
