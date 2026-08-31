"""Shared, content-agnostic relationship contract helpers."""

from __future__ import annotations

import re
from uuid import UUID


RELATIONSHIP_DIRECTIONALITIES = frozenset({"directed", "undirected"})
RELATIONSHIP_KINDS = frozenset(
    {"family", "colleague", "mentor", "ally", "enemy", "romance", "other"}
)


def normalize_relationship_label(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def relationship_pair_key(source_character_id: UUID, target_character_id: UUID) -> str:
    left, right = sorted((str(source_character_id), str(target_character_id)))
    return f"{left}:{right}"


def canonical_relationship_endpoints(
    source_character_id: UUID,
    target_character_id: UUID,
    directionality: str,
) -> tuple[UUID, UUID]:
    if source_character_id == target_character_id:
        raise ValueError("relationship endpoints must be distinct")
    if directionality not in RELATIONSHIP_DIRECTIONALITIES:
        raise ValueError("invalid relationship directionality")
    if directionality == "undirected" and str(source_character_id) > str(target_character_id):
        return target_character_id, source_character_id
    return source_character_id, target_character_id
