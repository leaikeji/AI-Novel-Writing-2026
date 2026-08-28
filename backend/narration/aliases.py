"""Deterministic, server-scoped character alias normalization and lookup.

T3-C intentionally owns no ORM writes.  Callers must supply the exact set of
server-authorized character IDs; alias rows outside that set fail closed.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Final, Mapping, Sequence
from uuid import RFC_4122, UUID


CHARACTER_ALIAS_NORMALIZATION_VERSION: Final = "character-alias-normalization/1"


class AliasContractError(ValueError):
    """Raised when alias input is ambiguous, malformed, or unauthorized."""


class AliasSource(str, Enum):
    CANONICAL_NAME = "canonical_name"
    AUTHOR_DEFINED = "author_defined"
    IMPORTED = "imported"


class AliasResolutionKind(str, Enum):
    NOT_FOUND = "not_found"
    UNIQUE = "unique"
    CONFLICT = "conflict"


def _require_uuid(value: object, *, field_name: str) -> UUID:
    if (
        type(value) is not UUID
        or value.variant != RFC_4122
        or value.version not in {1, 2, 3, 4, 5}
    ):
        raise AliasContractError(f"{field_name} must be an RFC-4122 UUID v1-v5")
    return value


def _require_alias_text(value: object, *, field_name: str) -> str:
    if type(value) is not str or not value or len(value) > 80:
        raise AliasContractError(f"{field_name} must contain 1-80 characters")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise AliasContractError(
            f"{field_name} contains an unpaired Unicode surrogate"
        ) from error
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise AliasContractError(f"{field_name} cannot contain control characters")
    return value


def normalize_character_alias(value: str) -> str:
    """Return the exact v1 lookup key without fuzzy or phonetic guessing."""

    value = _require_alias_text(value, field_name="character alias")
    normalized = " ".join(unicodedata.normalize("NFKC", value).casefold().split())
    if not normalized:
        raise AliasContractError("character alias cannot normalize to empty")
    return normalized


@dataclass(frozen=True, slots=True)
class CharacterAliasRecord:
    character_id: UUID
    alias: str
    source: AliasSource
    active: bool = True
    normalization_version: str = CHARACTER_ALIAS_NORMALIZATION_VERSION

    def __post_init__(self) -> None:
        _require_uuid(self.character_id, field_name="character_id")
        _require_alias_text(self.alias, field_name="alias")
        if type(self.source) is not AliasSource:
            raise AliasContractError("source must be AliasSource")
        if type(self.active) is not bool:
            raise AliasContractError("active must be an exact boolean")
        if self.normalization_version != CHARACTER_ALIAS_NORMALIZATION_VERSION:
            raise AliasContractError("unknown character alias normalization version")

    @property
    def normalized_alias(self) -> str:
        return normalize_character_alias(self.alias)


@dataclass(frozen=True, slots=True)
class AliasResolution:
    query: str
    normalized_alias: str
    kind: AliasResolutionKind
    character_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        _require_alias_text(self.query, field_name="alias query")
        if self.normalized_alias != normalize_character_alias(self.query):
            raise AliasContractError("normalized_alias does not match the query")
        if type(self.kind) is not AliasResolutionKind:
            raise AliasContractError("kind must be AliasResolutionKind")
        if type(self.character_ids) is not tuple:
            raise AliasContractError("character_ids must be a tuple")
        if len(self.character_ids) > 32:
            raise AliasContractError(
                "character_ids exceed the T3-A candidate limit of 32"
            )
        for character_id in self.character_ids:
            _require_uuid(character_id, field_name="resolved character_id")
        if self.character_ids != tuple(
            sorted(set(self.character_ids), key=str)
        ):
            raise AliasContractError(
                "character_ids must be unique and use canonical UUID order"
            )
        expected_kind = (
            AliasResolutionKind.NOT_FOUND
            if not self.character_ids
            else AliasResolutionKind.UNIQUE
            if len(self.character_ids) == 1
            else AliasResolutionKind.CONFLICT
        )
        if self.kind is not expected_kind:
            raise AliasContractError("resolution kind does not match character IDs")

    @property
    def character_id(self) -> UUID | None:
        if self.kind is AliasResolutionKind.UNIQUE:
            return self.character_ids[0]
        return None


@dataclass(frozen=True, slots=True)
class CharacterAliasIndex:
    """Immutable exact-match index derived from authorized active alias rows."""

    allowed_character_ids: frozenset[UUID]
    records: tuple[CharacterAliasRecord, ...]
    _active_ids_by_alias: Mapping[str, tuple[UUID, ...]] = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if type(self.allowed_character_ids) is not frozenset:
            raise AliasContractError("allowed_character_ids must be a frozenset")
        for character_id in self.allowed_character_ids:
            _require_uuid(character_id, field_name="allowed character_id")
        if type(self.records) is not tuple or not all(
            type(record) is CharacterAliasRecord for record in self.records
        ):
            raise AliasContractError(
                "records must be a tuple of CharacterAliasRecord"
            )
        canonical_records = tuple(
            sorted(
                self.records,
                key=lambda record: (
                    record.normalized_alias,
                    str(record.character_id),
                    record.source.value,
                    record.alias,
                    not record.active,
                ),
            )
        )
        if self.records != canonical_records:
            raise AliasContractError("alias records must use canonical order")
        unauthorized = {
            record.character_id
            for record in self.records
            if record.character_id not in self.allowed_character_ids
        }
        if unauthorized:
            raise AliasContractError(
                "alias records reference a character outside server authority"
            )

        active: dict[str, set[UUID]] = {}
        for record in self.records:
            if record.active:
                active.setdefault(record.normalized_alias, set()).add(
                    record.character_id
                )
        frozen = {
            alias: tuple(sorted(character_ids, key=str))
            for alias, character_ids in sorted(active.items())
        }
        if any(len(character_ids) > 32 for character_ids in frozen.values()):
            raise AliasContractError(
                "one normalized alias exceeds the T3-A candidate limit of 32"
            )
        object.__setattr__(
            self,
            "_active_ids_by_alias",
            MappingProxyType(frozen),
        )

    def resolve(self, query: str) -> AliasResolution:
        normalized = normalize_character_alias(query)
        character_ids = self._active_ids_by_alias.get(normalized, ())
        kind = (
            AliasResolutionKind.NOT_FOUND
            if not character_ids
            else AliasResolutionKind.UNIQUE
            if len(character_ids) == 1
            else AliasResolutionKind.CONFLICT
        )
        return AliasResolution(
            query=query,
            normalized_alias=normalized,
            kind=kind,
            character_ids=character_ids,
        )

    @property
    def conflicts(self) -> tuple[AliasResolution, ...]:
        return tuple(
            AliasResolution(
                query=normalized_alias,
                normalized_alias=normalized_alias,
                kind=AliasResolutionKind.CONFLICT,
                character_ids=character_ids,
            )
            for normalized_alias, character_ids in self._active_ids_by_alias.items()
            if len(character_ids) > 1
        )


def build_character_alias_index(
    records: Sequence[CharacterAliasRecord],
    *,
    allowed_character_ids: frozenset[UUID],
) -> CharacterAliasIndex:
    """Build a canonical index; it never creates or widens character scope."""

    if isinstance(records, (str, bytes)) or not isinstance(records, Sequence):
        raise AliasContractError("records must be a sequence")
    if not all(type(record) is CharacterAliasRecord for record in records):
        raise AliasContractError("records contain a non-CharacterAliasRecord value")
    canonical = tuple(
        sorted(
            records,
            key=lambda record: (
                record.normalized_alias,
                str(record.character_id),
                record.source.value,
                record.alias,
                not record.active,
            ),
        )
    )
    return CharacterAliasIndex(
        allowed_character_ids=allowed_character_ids,
        records=canonical,
    )


__all__ = [
    "CHARACTER_ALIAS_NORMALIZATION_VERSION",
    "AliasContractError",
    "AliasResolution",
    "AliasResolutionKind",
    "AliasSource",
    "CharacterAliasIndex",
    "CharacterAliasRecord",
    "build_character_alias_index",
    "normalize_character_alias",
]
