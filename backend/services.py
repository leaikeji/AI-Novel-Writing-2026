"""Single-source novel domain service used by both HTTP and Agent tools."""

from __future__ import annotations

import hashlib
import re
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    Document,
    DocumentRevision,
    DocumentWorkingCopy,
    Novel,
    StoryFact,
    Volume,
)


class DomainError(RuntimeError):
    pass


class NotFoundError(DomainError):
    pass


class ValidationError(DomainError):
    pass


class DraftConflictError(DomainError):
    def __init__(self, current: dict[str, Any]):
        super().__init__("document draft version conflict")
        self.current = current


def content_hash(markdown: str) -> str:
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def markdown_to_text(markdown: str) -> str:
    text = re.sub(r"```.*?```", " ", markdown, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!\[([^]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"[*_~>#-]", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def visible_character_count(markdown: str) -> int:
    return sum(1 for character in markdown_to_text(markdown) if not character.isspace())


def _document_payload(document: Document, working: DocumentWorkingCopy) -> dict[str, Any]:
    return {
        "id": str(document.id),
        "novel_id": str(document.novel_id),
        "volume_id": str(document.volume_id) if document.volume_id else None,
        "kind": document.kind,
        "title": document.title,
        "position": document.position,
        "draft_version": working.draft_version,
        "base_revision_id": str(working.base_revision_id) if working.base_revision_id else None,
        "content_markdown": working.content_markdown,
        "content_hash": working.content_hash,
        "visible_character_count": visible_character_count(working.content_markdown),
        "updated_at": working.updated_at.isoformat() if working.updated_at else None,
    }


def _revision_payload(revision: DocumentRevision, *, include_content: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": str(revision.id),
        "document_id": str(revision.document_id),
        "revision_number": revision.revision_number,
        "parent_revision_id": (
            str(revision.parent_revision_id) if revision.parent_revision_id else None
        ),
        "content_hash": revision.content_hash,
        "source": revision.source,
        "visible_character_count": visible_character_count(revision.content_markdown),
        "created_at": revision.created_at.isoformat() if revision.created_at else None,
    }
    if include_content:
        payload["content_markdown"] = revision.content_markdown
        payload["content_text"] = revision.content_text
    return payload


def _require_novel(session: Session, novel_id: UUID) -> Novel:
    novel = session.get(Novel, novel_id)
    if novel is None:
        raise NotFoundError(f"novel {novel_id} not found")
    return novel


def _require_document(session: Session, document_id: UUID) -> Document:
    document = session.get(Document, document_id)
    if document is None:
        raise NotFoundError(f"document {document_id} not found")
    return document


def _next_position(session: Session, model: type[Volume] | type[Document], novel_id: UUID) -> int:
    current = session.scalar(select(func.max(model.position)).where(model.novel_id == novel_id))
    return int(current or 0) + 1000


def _new_document(
    session: Session,
    *,
    novel_id: UUID,
    title: str,
    kind: str,
    position: int,
    volume_id: UUID | None,
) -> Document:
    document = Document(
        id=uuid4(),
        novel_id=novel_id,
        volume_id=volume_id,
        title=title.strip(),
        kind=kind,
        position=position,
    )
    empty_hash = content_hash("")
    revision = DocumentRevision(
        id=uuid4(),
        document_id=document.id,
        revision_number=1,
        content_markdown="",
        content_text="",
        content_hash=empty_hash,
        source="initial",
    )
    working = DocumentWorkingCopy(
        document_id=document.id,
        base_revision_id=revision.id,
        draft_version=1,
        content_markdown="",
        content_hash=empty_hash,
    )
    session.add_all((document, revision, working))
    return document


def create_novel(session: Session, title: str, description: str = "") -> dict[str, Any]:
    title = title.strip()
    if not title:
        raise ValidationError("novel title cannot be empty")
    novel = Novel(id=uuid4(), title=title, description=description.strip())
    volume = Volume(id=uuid4(), novel_id=novel.id, title="第一卷", position=1000)
    session.add_all((novel, volume))
    _new_document(
        session,
        novel_id=novel.id,
        title="第一章",
        kind="chapter",
        position=1000,
        volume_id=volume.id,
    )
    session.commit()
    return get_novel(session, novel.id)


def list_novels(session: Session) -> list[dict[str, Any]]:
    novels = session.scalars(select(Novel).order_by(Novel.updated_at.desc(), Novel.created_at.desc())).all()
    result: list[dict[str, Any]] = []
    for novel in novels:
        documents = session.scalars(
            select(Document).where(Document.novel_id == novel.id, Document.kind == "chapter")
        ).all()
        total_characters = 0
        for document in documents:
            working = session.get(DocumentWorkingCopy, document.id)
            if working:
                total_characters += visible_character_count(working.content_markdown)
        result.append(
            {
                "id": str(novel.id),
                "title": novel.title,
                "description": novel.description,
                "version": novel.version,
                "chapter_count": len(documents),
                "visible_character_count": total_characters,
                "created_at": novel.created_at.isoformat() if novel.created_at else None,
                "updated_at": novel.updated_at.isoformat() if novel.updated_at else None,
            }
        )
    return result


def get_novel(session: Session, novel_id: UUID) -> dict[str, Any]:
    novel = _require_novel(session, novel_id)
    return {
        "id": str(novel.id),
        "title": novel.title,
        "description": novel.description,
        "version": novel.version,
        "created_at": novel.created_at.isoformat() if novel.created_at else None,
        "updated_at": novel.updated_at.isoformat() if novel.updated_at else None,
        "tree": get_novel_tree(session, novel_id),
    }


def create_volume(session: Session, novel_id: UUID, title: str) -> dict[str, Any]:
    _require_novel(session, novel_id)
    title = title.strip()
    if not title:
        raise ValidationError("volume title cannot be empty")
    volume = Volume(
        id=uuid4(), novel_id=novel_id, title=title, position=_next_position(session, Volume, novel_id)
    )
    session.add(volume)
    session.commit()
    return {
        "id": str(volume.id),
        "novel_id": str(volume.novel_id),
        "title": volume.title,
        "position": volume.position,
        "version": volume.version,
    }


def create_document(
    session: Session,
    novel_id: UUID,
    title: str,
    *,
    kind: str = "chapter",
    volume_id: UUID | None = None,
) -> dict[str, Any]:
    _require_novel(session, novel_id)
    if kind not in {"chapter", "outline", "setting"}:
        raise ValidationError(f"unsupported document kind: {kind}")
    title = title.strip()
    if not title:
        raise ValidationError("document title cannot be empty")
    if volume_id is not None:
        volume = session.get(Volume, volume_id)
        if volume is None or volume.novel_id != novel_id:
            raise ValidationError("volume does not belong to this novel")
    document = _new_document(
        session,
        novel_id=novel_id,
        title=title,
        kind=kind,
        position=_next_position(session, Document, novel_id),
        volume_id=volume_id,
    )
    session.commit()
    return get_document(session, document.id)


def get_novel_tree(session: Session, novel_id: UUID) -> list[dict[str, Any]]:
    _require_novel(session, novel_id)
    volumes = session.scalars(
        select(Volume).where(Volume.novel_id == novel_id).order_by(Volume.position)
    ).all()
    documents = session.scalars(
        select(Document).where(Document.novel_id == novel_id).order_by(Document.position)
    ).all()
    grouped: dict[UUID | None, list[dict[str, Any]]] = {volume.id: [] for volume in volumes}
    grouped[None] = []
    for document in documents:
        working = session.get(DocumentWorkingCopy, document.id)
        if working is None:
            continue
        grouped.setdefault(document.volume_id, []).append(_document_payload(document, working))
    result = [
        {
            "id": str(volume.id),
            "title": volume.title,
            "position": volume.position,
            "version": volume.version,
            "documents": grouped.get(volume.id, []),
        }
        for volume in volumes
    ]
    if grouped[None]:
        result.append(
            {
                "id": None,
                "title": "未分卷资料",
                "position": 2_147_483_647,
                "version": 1,
                "documents": grouped[None],
            }
        )
    return result


def get_document(session: Session, document_id: UUID) -> dict[str, Any]:
    document = _require_document(session, document_id)
    working = session.get(DocumentWorkingCopy, document.id)
    if working is None:
        raise NotFoundError(f"working copy for document {document_id} not found")
    payload = _document_payload(document, working)
    revisions = session.scalars(
        select(DocumentRevision)
        .where(DocumentRevision.document_id == document.id)
        .order_by(DocumentRevision.revision_number.desc())
    ).all()
    payload["revisions"] = [_revision_payload(revision) for revision in revisions]
    return payload


def save_draft(
    session: Session,
    document_id: UUID,
    *,
    expected_draft_version: int,
    content_markdown: str,
    client_hash: str | None = None,
) -> dict[str, Any]:
    document = _require_document(session, document_id)
    working = session.scalar(
        select(DocumentWorkingCopy)
        .where(DocumentWorkingCopy.document_id == document_id)
        .with_for_update()
    )
    if working is None:
        raise NotFoundError(f"working copy for document {document_id} not found")
    if working.draft_version != expected_draft_version:
        raise DraftConflictError(_document_payload(document, working))
    server_hash = content_hash(content_markdown)
    if client_hash is not None and client_hash != server_hash:
        raise ValidationError("content_hash does not match content_markdown")
    if working.content_hash == server_hash:
        return _document_payload(document, working)
    working.content_markdown = content_markdown
    working.content_hash = server_hash
    working.draft_version += 1
    document.novel.updated_at = func.now()
    session.commit()
    return _document_payload(document, working)


def create_checkpoint(
    session: Session, document_id: UUID, *, expected_draft_version: int
) -> dict[str, Any]:
    document = _require_document(session, document_id)
    working = session.scalar(
        select(DocumentWorkingCopy)
        .where(DocumentWorkingCopy.document_id == document_id)
        .with_for_update()
    )
    if working is None:
        raise NotFoundError(f"working copy for document {document_id} not found")
    if working.draft_version != expected_draft_version:
        raise DraftConflictError(_document_payload(document, working))
    latest_number = session.scalar(
        select(func.max(DocumentRevision.revision_number)).where(
            DocumentRevision.document_id == document_id
        )
    )
    revision = DocumentRevision(
        id=uuid4(),
        document_id=document_id,
        revision_number=int(latest_number or 0) + 1,
        parent_revision_id=working.base_revision_id,
        content_markdown=working.content_markdown,
        content_text=markdown_to_text(working.content_markdown),
        content_hash=working.content_hash,
        source="manual_checkpoint",
    )
    session.add(revision)
    working.base_revision_id = revision.id
    working.draft_version += 1
    session.commit()
    return {"document": get_document(session, document_id), "revision": _revision_payload(revision, include_content=True)}


def restore_revision(
    session: Session,
    document_id: UUID,
    revision_id: UUID,
    *,
    expected_draft_version: int,
) -> dict[str, Any]:
    document = _require_document(session, document_id)
    source_revision = session.get(DocumentRevision, revision_id)
    if source_revision is None or source_revision.document_id != document_id:
        raise NotFoundError(f"revision {revision_id} not found for document {document_id}")
    working = session.scalar(
        select(DocumentWorkingCopy)
        .where(DocumentWorkingCopy.document_id == document_id)
        .with_for_update()
    )
    if working is None:
        raise NotFoundError(f"working copy for document {document_id} not found")
    if working.draft_version != expected_draft_version:
        raise DraftConflictError(_document_payload(document, working))
    latest_number = session.scalar(
        select(func.max(DocumentRevision.revision_number)).where(
            DocumentRevision.document_id == document_id
        )
    )
    restored = DocumentRevision(
        id=uuid4(),
        document_id=document_id,
        revision_number=int(latest_number or 0) + 1,
        parent_revision_id=working.base_revision_id,
        content_markdown=source_revision.content_markdown,
        content_text=source_revision.content_text,
        content_hash=source_revision.content_hash,
        source="manual_restore",
    )
    session.add(restored)
    working.base_revision_id = restored.id
    working.content_markdown = restored.content_markdown
    working.content_hash = restored.content_hash
    working.draft_version += 1
    session.commit()
    return {"document": get_document(session, document_id), "revision": _revision_payload(restored, include_content=True)}


def get_revision(session: Session, document_id: UUID, revision_id: UUID) -> dict[str, Any]:
    revision = session.get(DocumentRevision, revision_id)
    if revision is None or revision.document_id != document_id:
        raise NotFoundError(f"revision {revision_id} not found for document {document_id}")
    return _revision_payload(revision, include_content=True)


def search_novel(session: Session, novel_id: UUID, query: str, limit: int = 20) -> list[dict[str, Any]]:
    _require_novel(session, novel_id)
    query = query.strip()
    if not query:
        return []
    pattern = f"%{query}%"
    rows = session.execute(
        select(Document, DocumentWorkingCopy)
        .join(DocumentWorkingCopy, DocumentWorkingCopy.document_id == Document.id)
        .where(
            Document.novel_id == novel_id,
            DocumentWorkingCopy.content_markdown.ilike(pattern) | Document.title.ilike(pattern),
        )
        .order_by(Document.position)
        .limit(max(1, min(limit, 50)))
    ).all()
    results: list[dict[str, Any]] = []
    for document, working in rows:
        plain = markdown_to_text(working.content_markdown)
        index = plain.lower().find(query.lower())
        start = max(0, index - 120) if index >= 0 else 0
        results.append(
            {
                "document_id": str(document.id),
                "title": document.title,
                "kind": document.kind,
                "base_revision_id": str(working.base_revision_id) if working.base_revision_id else None,
                "snippet": plain[start : start + 360],
            }
        )
    return results


def get_novel_context(
    session: Session,
    novel_id: UUID,
    *,
    document_id: UUID | None = None,
    max_chars: int = 12_000,
) -> dict[str, Any]:
    novel = _require_novel(session, novel_id)
    max_chars = max(1_000, min(max_chars, 40_000))
    documents = session.scalars(
        select(Document)
        .where(Document.novel_id == novel_id)
        .order_by(Document.position)
    ).all()
    current_index = len(documents) - 1
    if document_id is not None:
        matches = [index for index, item in enumerate(documents) if item.id == document_id]
        if not matches:
            raise ValidationError("document does not belong to this novel")
        current_index = matches[0]
    selected: list[dict[str, Any]] = []
    remaining = max_chars
    for document in reversed(documents[: current_index + 1]):
        working = session.get(DocumentWorkingCopy, document.id)
        if working is None:
            continue
        text = working.content_markdown[-remaining:]
        selected.append(
            {
                "document_id": str(document.id),
                "title": document.title,
                "kind": document.kind,
                "base_revision_id": str(working.base_revision_id) if working.base_revision_id else None,
                "content_markdown": text,
            }
        )
        remaining -= len(text)
        if remaining <= 0:
            break
    selected.reverse()
    facts = session.scalars(
        select(StoryFact)
        .where(StoryFact.novel_id == novel_id, StoryFact.status == "active")
        .order_by(StoryFact.created_at)
        .limit(200)
    ).all()
    return {
        "novel": {"id": str(novel.id), "title": novel.title, "description": novel.description},
        "current_document_id": str(document_id) if document_id else None,
        "documents": selected,
        "story_facts": [
            {
                "id": str(fact.id),
                "type": fact.fact_type,
                "subject": fact.subject,
                "predicate": fact.predicate,
                "object": fact.object_text,
                "source_revision_id": str(fact.source_revision_id) if fact.source_revision_id else None,
            }
            for fact in facts
        ],
        "retrieval": "lexical/current-revision context; vector retrieval is intentionally disabled in MVP-0",
    }
