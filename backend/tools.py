"""Read-only QwenPaw Agent tools backed by the novel domain service."""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy.orm import sessionmaker

from .database import get_engine
from .services import get_document, get_novel_context, search_novel


def _json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


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
