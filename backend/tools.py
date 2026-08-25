"""Read-only QwenPaw Agent tools backed by the novel domain service."""

import json
from typing import Literal
from uuid import UUID

from sqlalchemy.orm import sessionmaker

from .assistant_context import (
    TARGET_AGENT_ID,
    current_assistant_workspace_scope,
)
from .assistant_workspace_service import (
    WORKSPACE_CONTEXT_DEFAULT_MAX_CHARS,
    WORKSPACE_CONTEXT_SCHEMA_VERSION,
    WorkspaceOwnerScope,
    WorkspaceScopeError,
    get_assistant_workspace_context,
)
from .database import get_engine
from .services import get_document, get_novel_context, search_novel


_WORKSPACE_SECTION_ALIASES: dict[str, str] = {
    "characters": "roles",
    "relationships": "roles",
    "storylines": "clues",
    "foreshadows": "clues",
}

SELECTION_EDIT_SCHEMA_VERSION = 1
SELECTION_EDIT_MAX_REPLACEMENT_CHARACTERS = 100_000
SELECTION_EDIT_MAX_SUMMARY_CHARACTERS = 500
SELECTION_EDIT_OPERATIONS = frozenset(
    {"polish", "rewrite", "expand", "shorten", "dialogue", "review", "custom"},
)

SelectionEditOperation = Literal[
    "polish",
    "rewrite",
    "expand",
    "shorten",
    "dialogue",
    "review",
    "custom",
]


def _json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _scope_uuid(value: str | None) -> UUID | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise WorkspaceScopeError()
    try:
        return UUID(value)
    except (AttributeError, TypeError, ValueError):
        raise WorkspaceScopeError() from None


async def novel_get_workspace_context(
    section: str = "",
    include: list[str] | None = None,
    max_chars: int = WORKSPACE_CONTEXT_DEFAULT_MAX_CHARS,
    schema_version: int = WORKSPACE_CONTEXT_SCHEMA_VERSION,
) -> str:
    """Read bounded formal material for the current trusted workbench scope.

    Args:
        section: Page section or material-category alias used only for ordering;
            defaults to the current page section.
        include: Optional material categories: chapter_naming, outline,
            characters, relationships, storylines, foreshadows, or settings.
            chapter_naming returns only the current chapter working copy plus a
            bounded book-order title index for evidence-based title proposals.
        max_chars: Requested response budget, clamped by the service.
        schema_version: Workspace context response schema version.

    Novel, document, entity, owner, Agent, and session identifiers are resolved
    only from the current server-side Middleware scope, never model arguments.
    """

    scope = current_assistant_workspace_scope()
    if (
        scope is None
        or scope.agent_id != TARGET_AGENT_ID
        or not isinstance(scope.session_id, str)
        or not scope.session_id.strip()
    ):
        raise WorkspaceScopeError()

    novel_id = _scope_uuid(scope.novel_id)
    if novel_id is None:
        raise WorkspaceScopeError()
    document_id = _scope_uuid(scope.document_id)
    if (scope.entity_type is None) != (scope.entity_id is None):
        raise WorkspaceScopeError()
    entity_id = _scope_uuid(scope.entity_id)
    owner_scope = WorkspaceOwnerScope.from_novel_ids(
        scope.session_id,
        [novel_id],
    )
    requested_section = (
        scope.section
        if section == ""
        else _WORKSPACE_SECTION_ALIASES.get(section, section)
    )

    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    with factory() as session:
        payload = get_assistant_workspace_context(
            session,
            owner_scope=owner_scope,
            novel_id=novel_id,
            section=requested_section,
            schema_version=schema_version,
            document_id=document_id,
            entity_type=scope.entity_type,
            entity_id=entity_id,
            include=include,
            max_chars=max_chars,
        )
    return _json(payload)


async def novel_prepare_selection_edit(
    selection_id: str,
    operation: Literal[
        "polish",
        "rewrite",
        "expand",
        "shorten",
        "dialogue",
        "review",
        "custom",
    ],
    replacement_text: str,
    short_summary: str,
) -> str:
    """Return one bounded, non-persistent proposal for a browser selection.

    Args:
        selection_id: UUID supplied by the current workbench selection context.
        operation: Requested selection operation.
        replacement_text: Plain candidate text only, without commentary.
        short_summary: Brief author-facing description of the proposed change.

    The browser remains authoritative for whether the selection is still live.
    This tool validates only its strict result contract and never opens a
    database transaction or writes a novel field.
    """

    scope = current_assistant_workspace_scope()
    if (
        scope is None
        or scope.agent_id != TARGET_AGENT_ID
        or not isinstance(scope.session_id, str)
        or not scope.session_id.strip()
    ):
        raise WorkspaceScopeError()

    if (
        not isinstance(selection_id, str)
        or selection_id != selection_id.strip()
    ):
        raise ValueError("invalid-selection-id")
    try:
        UUID(selection_id)
    except (AttributeError, TypeError, ValueError):
        raise ValueError("invalid-selection-id") from None
    if (
        scope.selection_id is None
        or scope.selection_character_count is None
        or selection_id != scope.selection_id
    ):
        raise ValueError("selection-scope-mismatch")
    if operation not in SELECTION_EDIT_OPERATIONS:
        raise ValueError("unsupported-selection-operation")
    if (
        not isinstance(replacement_text, str)
        or not replacement_text
        or "\x00" in replacement_text
        or len(replacement_text) > SELECTION_EDIT_MAX_REPLACEMENT_CHARACTERS
    ):
        raise ValueError("invalid-replacement-text")
    if (
        not isinstance(short_summary, str)
        or not short_summary.strip()
        or len(short_summary) > SELECTION_EDIT_MAX_SUMMARY_CHARACTERS
        or "\x00" in short_summary
    ):
        raise ValueError("invalid-short-summary")

    source_characters = scope.selection_character_count
    replacement_characters = len(replacement_text)
    if source_characters >= 80:
        if operation == "shorten" and replacement_characters * 5 > source_characters * 4:
            raise ValueError("insufficient-shortening")
        if operation == "expand" and replacement_characters * 10 < source_characters * 13:
            raise ValueError("insufficient-expansion")
        if operation == "review" and (
            replacement_characters * 5 < source_characters * 4
            or replacement_characters * 5 > source_characters * 6
        ):
            raise ValueError("review-size-mismatch")

    warnings: list[str] = []
    if "```" in replacement_text:
        warnings.append("候选文本包含 Markdown 围栏，请确认后再应用。")

    return _json(
        {
            "schema_version": SELECTION_EDIT_SCHEMA_VERSION,
            "selection_id": selection_id,
            "operation": operation,
            "replacement_text": replacement_text,
            "short_summary": short_summary.strip(),
            "replacement_character_count": replacement_characters,
            "warnings": warnings,
        },
    )


async def novel_get_context(
    novel_id: str,
    document_id: str = "",
    max_chars: int = 12_000,
) -> str:
    """Read current novel facts and preceding documents.

    Args:
        novel_id: Current novel UUID copied from the novel workbench.
        document_id: Optional current document UUID copied from the workbench.
        max_chars: Maximum amount of recent document Markdown to return.
    """
    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    with factory() as session:
        payload = get_novel_context(
            session,
            UUID(novel_id),
            document_id=UUID(document_id) if document_id else None,
            max_chars=max_chars,
        )
    return _json(payload)


async def novel_get_document(document_id: str) -> str:
    """Read one current novel document and its revision metadata.

    Args:
        document_id: Document UUID copied from the novel workbench.
    """
    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    with factory() as session:
        payload = get_document(session, UUID(document_id))
    return _json(payload)


async def novel_search(novel_id: str, query: str, limit: int = 20) -> str:
    """Search current novel documents using safe lexical matching.

    Args:
        novel_id: Current novel UUID copied from the novel workbench.
        query: Text to find in current document working copies.
        limit: Maximum number of matches, from 1 to 50.
    """
    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    with factory() as session:
        payload = search_novel(session, UUID(novel_id), query, limit=limit)
    return _json(payload)
