"""Frozen Plan 74 contracts for structured vocabulary assets.

These models validate machine-executable lexicon metadata.  Human-readable
``PrivateAssetVersion.content`` remains a rendered projection and is never
parsed back into rules.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


LEXICON_SCHEMA_VERSION = "lexicon-pack/1"
LEXICON_RENDERER_VERSION = "lexicon-renderer/1"
LEXICON_MATCHER_VERSION = "lexicon-matcher/1"

MAX_TERM_CHARACTERS = 80
MAX_VARIANTS_PER_ENTRY = 20
MAX_LEXICON_ENTRIES_PER_PACK = 200
MAX_LEXICON_ENTRIES_PER_IMPORT = 200
MAX_EFFECTIVE_RULES = 1_000
MAX_PROMPT_RECOMMENDATIONS = 30
MAX_EXAMPLE_CHARACTERS = 1_000
MAX_NOTE_CHARACTERS = 2_000
MAX_SOURCE_REFS_PER_ENTRY = 10
MAX_LEXICON_METADATA_BYTES = 256 * 1024
DEFAULT_WATCH_WINDOW_CHARACTERS = 1_000
DEFAULT_WATCH_COUNT = 3


class LexiconAction(str, Enum):
    RECOMMEND = "recommend"
    WATCH = "watch"
    FORBID = "forbid"


class LexiconMatchMode(str, Enum):
    PHRASE = "phrase"
    ASCII_WORD = "ascii_word"


class LexiconEntryState(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class LexiconSourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: Literal[
        "author", "selection", "licensed_material", "public_domain", "research"
    ]
    label: Annotated[str, Field(min_length=1, max_length=240)]
    locator: Annotated[str | None, Field(max_length=1_000)] = None
    observed_at: Annotated[str | None, Field(max_length=40)] = None
    evidence_scope: Annotated[str | None, Field(max_length=500)] = None
    verified_popularity: bool = False


class LexiconWatchThreshold(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: Annotated[int, Field(ge=1, le=100)] = DEFAULT_WATCH_COUNT
    window_characters: Annotated[int, Field(ge=100, le=10_000)] = (
        DEFAULT_WATCH_WINDOW_CHARACTERS
    )


class LexiconEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")]
    term: Annotated[str, Field(min_length=1, max_length=MAX_TERM_CHARACTERS)]
    action: LexiconAction
    state: LexiconEntryState = LexiconEntryState.ACTIVE
    match_mode: LexiconMatchMode = LexiconMatchMode.PHRASE
    case_sensitive: bool = True
    variants: list[Annotated[str, Field(min_length=1, max_length=MAX_TERM_CHARACTERS)]] = (
        Field(default_factory=list, max_length=MAX_VARIANTS_PER_ENTRY)
    )
    categories: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        default_factory=list, max_length=20
    )
    genres: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        default_factory=list, max_length=20
    )
    eras: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        default_factory=list, max_length=20
    )
    positions: list[
        Literal["body", "dialogue", "title", "synopsis", "any"]
    ] = Field(default_factory=lambda: ["any"], max_length=5)
    note: Annotated[str, Field(max_length=MAX_NOTE_CHARACTERS)] = ""
    example: Annotated[str, Field(max_length=MAX_EXAMPLE_CHARACTERS)] = ""
    counterexample: Annotated[str, Field(max_length=MAX_EXAMPLE_CHARACTERS)] = ""
    replacement_hint: Annotated[str, Field(max_length=MAX_EXAMPLE_CHARACTERS)] = ""
    watch_threshold: LexiconWatchThreshold | None = None
    source_refs: list[LexiconSourceRef] = Field(
        default_factory=list, max_length=MAX_SOURCE_REFS_PER_ENTRY
    )

    @field_validator("term")
    @classmethod
    def validate_term(cls, value: str) -> str:
        if value != value.strip() or "\x00" in value:
            raise ValueError("term must be trimmed text without NUL")
        return value

    @field_validator("variants", "categories", "genres", "eras")
    @classmethod
    def validate_unique_strings(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item or "\x00" in item for item in normalized):
            raise ValueError("list entries must be trimmed non-empty text")
        if len(set(normalized)) != len(normalized):
            raise ValueError("list entries must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_action_contract(self) -> "LexiconEntry":
        if self.match_mode is LexiconMatchMode.ASCII_WORD and not all(
            candidate.isascii() and any(character.isalnum() for character in candidate)
            for candidate in (self.term, *self.variants)
        ):
            raise ValueError("ascii_word rules require ASCII terms and variants")
        if self.action is LexiconAction.WATCH and self.watch_threshold is None:
            self.watch_threshold = LexiconWatchThreshold()
        if self.action is not LexiconAction.WATCH and self.watch_threshold is not None:
            raise ValueError("watch_threshold is only valid for watch rules")
        return self


class LexiconPack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["lexicon-pack/1"] = LEXICON_SCHEMA_VERSION
    renderer_version: Literal["lexicon-renderer/1"] = LEXICON_RENDERER_VERSION
    entries: list[LexiconEntry] = Field(
        default_factory=list,
        max_length=MAX_LEXICON_ENTRIES_PER_PACK,
    )

    @model_validator(mode="after")
    def validate_unique_entries(self) -> "LexiconPack":
        entry_ids = [entry.entry_id for entry in self.entries]
        if len(set(entry_ids)) != len(entry_ids):
            raise ValueError("entry_id must be unique within a lexicon pack")
        return self


__all__ = [
    "DEFAULT_WATCH_COUNT",
    "DEFAULT_WATCH_WINDOW_CHARACTERS",
    "LEXICON_MATCHER_VERSION",
    "LEXICON_RENDERER_VERSION",
    "LEXICON_SCHEMA_VERSION",
    "MAX_EFFECTIVE_RULES",
    "MAX_LEXICON_ENTRIES_PER_IMPORT",
    "MAX_LEXICON_ENTRIES_PER_PACK",
    "MAX_LEXICON_METADATA_BYTES",
    "MAX_PROMPT_RECOMMENDATIONS",
    "MAX_TERM_CHARACTERS",
    "LexiconAction",
    "LexiconEntry",
    "LexiconEntryState",
    "LexiconMatchMode",
    "LexiconPack",
    "LexiconSourceRef",
    "LexiconWatchThreshold",
]
