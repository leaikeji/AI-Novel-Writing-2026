"""Frozen Plan 74 request, scope, receipt, and check-report contracts."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


LIBRARY_CHANGE_SCHEMA_VERSION = "library-change/1"
LIBRARY_CHECK_SCHEMA_VERSION = "library-check/1"
MAX_CHANGE_ACTIONS = 200
MAX_CHANGE_ASSETS = 20
MAX_CHANGE_REQUEST_BYTES = 512 * 1024
MAX_CHECK_TEXT_CHARACTERS = 500_000
MAX_CHECK_HITS_PER_PAGE = 200


class LibraryScopeKind(str, Enum):
    LIBRARY = "library"
    NOVEL = "novel"


class LibraryScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: LibraryScopeKind
    novel_id: UUID | None = None

    @model_validator(mode="after")
    def validate_scope(self) -> "LibraryScope":
        if (self.kind is LibraryScopeKind.LIBRARY) != (self.novel_id is None):
            raise ValueError("library scope cannot carry novel_id; novel scope requires it")
        return self


class LibraryCaptureSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "saved_field", "unsynced_selection", "ai_candidate", "authorized_external"
    ]
    text_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    selection_id: UUID | None = None
    document_id: UUID | None = None
    field_id: Annotated[str | None, Field(max_length=200)] = None
    document_version: Annotated[int | None, Field(ge=0)] = None
    label: Annotated[str | None, Field(max_length=240)] = None


class LibraryChangeOperation(str, Enum):
    CREATE_ASSET = "create_asset"
    UPDATE_ASSET = "update_asset"
    ARCHIVE_ASSET = "archive_asset"
    RESTORE_ASSET = "restore_asset"
    UPSERT_LEXICON_ENTRIES = "upsert_lexicon_entries"
    REMOVE_LEXICON_ENTRIES = "remove_lexicon_entries"
    SET_NOVEL_BINDING = "set_novel_binding"
    CREATE_NOVEL_COPY = "create_novel_copy"


class LibraryChangeAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: LibraryChangeOperation
    asset_id: UUID | None = None
    asset_version_id: UUID | None = None
    expected_root_version: Annotated[int | None, Field(ge=1)] = None
    payload: dict[str, Any] = Field(default_factory=dict)


class LibraryChangeProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["library-change/1"] = LIBRARY_CHANGE_SCHEMA_VERSION
    request_id: UUID
    session_id: Annotated[str, Field(min_length=1, max_length=200)]
    author_text_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    scope: LibraryScope
    source: LibraryCaptureSource | None = None
    actions: list[LibraryChangeAction] = Field(
        min_length=1,
        max_length=MAX_CHANGE_ACTIONS,
    )
    idempotency_key: Annotated[str, Field(min_length=8, max_length=160)]
    content_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    requires_review: bool

    @model_validator(mode="after")
    def validate_asset_budget(self) -> "LibraryChangeProposal":
        assets = {action.asset_id for action in self.actions if action.asset_id is not None}
        if len(assets) > MAX_CHANGE_ASSETS:
            raise ValueError("change proposal touches too many assets")
        return self


class LibraryCheckTextRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_kind: Literal["working_copy", "candidate", "selection_result"]
    novel_id: UUID
    document_id: UUID
    version: Annotated[int, Field(ge=0)]
    text_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class SelectionLibraryApplication(BaseModel):
    """Evidence for one author-applied body selection, never a manual save."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["selection-library-application/1"] = "selection-library-application/1"
    application_id: UUID
    job_id: UUID
    attempt: Annotated[int, Field(ge=1)]
    base_draft_version: Annotated[int, Field(ge=1)]
    base_content_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    replacement_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    accepted_segment_ids: Annotated[list[str] | None, Field(max_length=200)] = None
    library_check_report_id: UUID
    library_check_version: Annotated[int, Field(ge=1)]

    @model_validator(mode="after")
    def unique_segments(self) -> "SelectionLibraryApplication":
        if self.accepted_segment_ids is not None and (
            any(not value or len(value) > 200 for value in self.accepted_segment_ids)
            or len(set(self.accepted_segment_ids)) != len(self.accepted_segment_ids)
        ):
            raise ValueError("accepted segments must be unique non-empty identifiers")
        return self


class LibraryCheckHit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hit_id: UUID
    entry_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")]
    asset_id: UUID
    asset_version_id: UUID
    action: Literal["watch", "forbid"]
    matched_text: Annotated[str, Field(min_length=1, max_length=80)]
    start_utf16: Annotated[int, Field(ge=0)]
    end_utf16: Annotated[int, Field(gt=0)]
    reason: Annotated[str, Field(min_length=1, max_length=500)]
    count: Annotated[int, Field(ge=1)]
    window: Annotated[int | None, Field(ge=1)] = None

    @model_validator(mode="after")
    def validate_range(self) -> "LibraryCheckHit":
        if self.end_utf16 <= self.start_utf16:
            raise ValueError("hit range must be non-empty")
        return self


__all__ = [
    "LIBRARY_CHANGE_SCHEMA_VERSION",
    "LIBRARY_CHECK_SCHEMA_VERSION",
    "MAX_CHANGE_ACTIONS",
    "MAX_CHANGE_ASSETS",
    "MAX_CHANGE_REQUEST_BYTES",
    "MAX_CHECK_HITS_PER_PAGE",
    "MAX_CHECK_TEXT_CHARACTERS",
    "LibraryCaptureSource",
    "LibraryChangeAction",
    "LibraryChangeOperation",
    "LibraryChangeProposal",
    "LibraryCheckHit",
    "LibraryCheckTextRef",
    "SelectionLibraryApplication",
    "LibraryScope",
    "LibraryScopeKind",
]
