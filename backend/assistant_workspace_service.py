"""Read-only aggregation of authoritative novel workspace material.

The tool adapter must construct :class:`WorkspaceOwnerScope` from server-side
workbench state. Model-provided novel/document/entity ids are never sufficient
authorization by themselves.
"""

from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any
from uuid import UUID

from sqlalchemy import and_, case, select
from sqlalchemy.orm import Session

from .creative_services import (
    _character_payload,
    _foreshadow_payload,
    _outline_payload,
    _relationship_payload,
    _storyline_payload,
)
from .models import (
    CharacterRelationship,
    Document,
    DocumentWorkingCopy,
    Foreshadow,
    Novel,
    NovelCharacter,
    OutlineDraft,
    Storyline,
    Volume,
)
from .services import NotFoundError, ValidationError, _document_payload
from .volume_chapter_titles import (
    bound_contract_title,
    context_chapter_title,
    display_volume_title,
)


WORKSPACE_CONTEXT_SCHEMA_VERSION = 2
WORKSPACE_CONTEXT_DEFAULT_MAX_CHARS = 12_000
WORKSPACE_CONTEXT_MIN_CHARS = 1_000
WORKSPACE_CONTEXT_MAX_CHARS = 40_000
CHAPTER_NAMING_BODY_MAX_CHARS = 20_000
CHAPTER_NAMING_TITLE_LIMIT = 500

WORKSPACE_CONTEXT_SECTIONS = frozenset(
    {"chapters", "outline", "roles", "clues", "settings"}
)
WORKSPACE_CONTEXT_INCLUDE_ORDER = (
    "chapter_naming",
    "outline",
    "characters",
    "relationships",
    "storylines",
    "foreshadows",
    "settings",
)
WORKSPACE_CONTEXT_INCLUDES = frozenset(WORKSPACE_CONTEXT_INCLUDE_ORDER)
WORKSPACE_CONTEXT_DEFAULT_INCLUDES = frozenset(
    item for item in WORKSPACE_CONTEXT_INCLUDE_ORDER if item != "chapter_naming"
)
WORKSPACE_CONTEXT_ENTITY_TYPES = frozenset(
    {
        "novel",
        "volume",
        "document",
        "outline",
        "character",
        "relationship",
        "storyline",
        "foreshadow",
        "setting",
    }
)


_SECTION_INCLUDE_ORDER: dict[str, tuple[str, ...]] = {
    "chapters": (
        "chapter_naming",
        "outline",
        "characters",
        "relationships",
        "storylines",
        "foreshadows",
        "settings",
    ),
    "outline": (
        "outline",
        "characters",
        "storylines",
        "relationships",
        "settings",
        "foreshadows",
        "chapter_naming",
    ),
    "roles": (
        "characters",
        "relationships",
        "storylines",
        "outline",
        "foreshadows",
        "settings",
        "chapter_naming",
    ),
    "clues": (
        "foreshadows",
        "storylines",
        "relationships",
        "characters",
        "outline",
        "settings",
        "chapter_naming",
    ),
    "settings": (
        "settings",
        "outline",
        "characters",
        "relationships",
        "storylines",
        "foreshadows",
        "chapter_naming",
    ),
}


class WorkspaceScopeError(NotFoundError):
    """Uniform non-enumerable failure for resources outside server scope."""

    def __init__(self) -> None:
        super().__init__("workspace resource is not available in the current owner scope")


@dataclass(frozen=True, slots=True)
class WorkspaceOwnerScope:
    """Server-resolved local owner and the novels authorized for this request."""

    owner_id: str
    novel_ids: frozenset[UUID]

    @classmethod
    def from_novel_ids(
        cls,
        owner_id: str,
        novel_ids: Collection[UUID],
    ) -> WorkspaceOwnerScope:
        return cls(owner_id=owner_id.strip(), novel_ids=frozenset(novel_ids))


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _as_of(clock: Callable[[], datetime]) -> str:
    value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationError("workspace context clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_include(
    section: str,
    include: Collection[str] | None,
) -> tuple[str, ...]:
    if not isinstance(section, str) or section not in WORKSPACE_CONTEXT_SECTIONS:
        raise ValidationError(f"unsupported workspace section: {section}")
    if include is None:
        requested = WORKSPACE_CONTEXT_DEFAULT_INCLUDES
    else:
        if isinstance(include, (str, bytes)):
            raise ValidationError("include must be a collection of approved section names")
        requested_items = tuple(include)
        if any(not isinstance(item, str) for item in requested_items):
            raise ValidationError(
                "include must contain only approved section names"
            )
        requested = set(requested_items)
        invalid = sorted(requested - WORKSPACE_CONTEXT_INCLUDES)
        if invalid:
            raise ValidationError(
                f"unsupported workspace include: {', '.join(invalid)}"
            )
    return tuple(item for item in _SECTION_INCLUDE_ORDER[section] if item in requested)


def _normalize_max_chars(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError("max_chars must be an integer")
    return max(WORKSPACE_CONTEXT_MIN_CHARS, min(value, WORKSPACE_CONTEXT_MAX_CHARS))


def _provenance(
    source_type: str,
    table: str,
    record_count: int,
) -> dict[str, Any]:
    return {
        "source_type": source_type,
        "table": table,
        "record_count": record_count,
    }


def _novel_outline_payload(novel: Novel) -> dict[str, Any]:
    return {
        "novel_id": str(novel.id),
        "title": novel.title,
        "target_chapter_count": novel.outline_target_chapters,
        "background": novel.background,
        "main_plot": novel.main_plot,
        "highlight": novel.highlight,
        "version": novel.version,
        "updated_at": _iso(novel.updated_at),
    }


def _novel_settings_payload(novel: Novel) -> dict[str, Any]:
    return {
        "novel_id": str(novel.id),
        "title": novel.title,
        "author_name": novel.author_name,
        "writing_type": novel.writing_type,
        "audience": novel.audience,
        "genre": novel.genre,
        "subgenre": novel.subgenre,
        "idea": novel.idea,
        "template_key": novel.template_key,
        "template_name": novel.template_name,
        "template_data": novel.template_data,
        "version": novel.version,
        "updated_at": _iso(novel.updated_at),
    }


def _document_envelope(
    document: Document,
    *,
    projected_title: str | None = None,
) -> dict[str, Any]:
    runtime_title = (
        projected_title
        if projected_title is not None
        else context_chapter_title(document.title, 1)
        if document.kind == "chapter"
        else document.title
    )
    return {
        "id": str(document.id),
        "novel_id": str(document.novel_id),
        "volume_id": str(document.volume_id) if document.volume_id else None,
        "kind": document.kind,
        "title": runtime_title,
        "position": document.position,
        "status": document.status,
        "version": document.version,
        "updated_at": _iso(document.updated_at),
        "provenance": _provenance("database_table", "documents", 1),
    }


def _load_working_documents(
    session: Session,
    novel_id: UUID,
    kind: str,
) -> list[tuple[Document, DocumentWorkingCopy]]:
    statement = (
        select(Document, DocumentWorkingCopy)
        .join(DocumentWorkingCopy, DocumentWorkingCopy.document_id == Document.id)
        .where(Document.novel_id == novel_id, Document.kind == kind)
    )
    if kind == "chapter":
        statement = statement.outerjoin(
            Volume,
            and_(
                Volume.id == Document.volume_id,
                Volume.novel_id == Document.novel_id,
            ),
        ).order_by(
            case((Document.volume_id.is_(None), 1), else_=0),
            Volume.position,
            Document.position,
            Document.id,
        )
    else:
        statement = statement.order_by(Document.position, Document.id)
    return list(
        session.execute(statement).all()
    )


def _chapter_title_projection(session: Session, novel_id: UUID) -> dict[UUID, str]:
    documents = tuple(
        item
        for item in session.scalars(
            select(Document)
            .outerjoin(
                Volume,
                and_(
                    Volume.id == Document.volume_id,
                    Volume.novel_id == Document.novel_id,
                ),
            )
            .where(Document.novel_id == novel_id, Document.kind == "chapter")
            .order_by(
                case((Document.volume_id.is_(None), 1), else_=0),
                Volume.position,
                Document.position,
                Document.id,
            )
        ).all()
        if item.novel_id == novel_id and item.kind == "chapter"
    )
    return {
        document.id: context_chapter_title(document.title, ordinal)
        for ordinal, document in enumerate(documents, start=1)
    }


def _volume_title_projection(session: Session, novel_id: UUID) -> dict[UUID, str]:
    volumes = tuple(
        item
        for item in session.scalars(
            select(Volume)
            .where(Volume.novel_id == novel_id)
            .order_by(Volume.position, Volume.id)
        ).all()
        if item.novel_id == novel_id
    )
    return {
        volume.id: bound_contract_title(display_volume_title(volume.title, ordinal))
        for ordinal, volume in enumerate(volumes, start=1)
    }


def _scope_entity(
    session: Session,
    novel: Novel,
    entity_type: str | None,
    entity_id: UUID | None,
    *,
    chapter_titles: dict[UUID, str] | None = None,
    volume_titles: dict[UUID, str] | None = None,
) -> dict[str, Any] | None:
    if (entity_type is None) != (entity_id is None):
        raise ValidationError("entity_type and entity_id must be provided together")
    if entity_type is None or entity_id is None:
        return None
    if (
        not isinstance(entity_type, str)
        or entity_type not in WORKSPACE_CONTEXT_ENTITY_TYPES
    ):
        raise ValidationError(f"unsupported workspace entity type: {entity_type}")

    if entity_type == "novel":
        if entity_id != novel.id:
            raise WorkspaceScopeError()
        return {
            "type": "novel",
            "id": str(novel.id),
            "title": novel.title,
            "provenance": _provenance("database_table", "novels", 1),
        }

    if entity_type == "outline" and entity_id == novel.id:
        return {
            "type": "outline",
            "id": str(novel.id),
            "title": novel.title,
            "provenance": _provenance("database_table", "novels", 1),
        }
    if entity_type == "setting" and entity_id == novel.id:
        return {
            "type": "setting",
            "id": str(novel.id),
            "title": novel.title,
            "provenance": _provenance("database_table", "novels", 1),
        }

    model_by_type: dict[str, type[Any]] = {
        "volume": Volume,
        "document": Document,
        "outline": OutlineDraft,
        "character": NovelCharacter,
        "relationship": CharacterRelationship,
        "storyline": Storyline,
        "foreshadow": Foreshadow,
        "setting": Document,
    }
    entity = session.get(model_by_type[entity_type], entity_id)
    if entity is None or getattr(entity, "novel_id", None) != novel.id:
        raise WorkspaceScopeError()
    if entity_type == "setting" and entity.kind != "setting":
        raise WorkspaceScopeError()

    if entity_type == "volume":
        return {
            "type": "volume",
            "id": str(entity.id),
            "title": (volume_titles or {}).get(entity.id)
            or bound_contract_title(display_volume_title(entity.title, 1)),
            "provenance": _provenance("database_table", "volumes", 1),
        }
    if entity_type in {"document", "setting"}:
        payload = _document_envelope(
            entity,
            projected_title=(chapter_titles or {}).get(entity.id),
        )
        payload["type"] = entity_type
        return payload
    if entity_type == "outline":
        payload = _outline_payload(entity)
        return {
            "type": "outline",
            "id": payload["id"],
            "title": novel.title,
            "state": payload["state"],
            "version": payload["version"],
            "provenance": _provenance("database_table", "outline_drafts", 1),
        }
    if entity_type == "character":
        payload = _character_payload(entity)
        return {
            "type": "character",
            "id": payload["id"],
            "title": payload["name"],
            "lifecycle_state": payload["lifecycle_state"],
            "version": payload["version"],
            "provenance": _provenance("database_table", "novel_characters", 1),
        }
    if entity_type == "relationship":
        source = session.get(NovelCharacter, entity.source_character_id)
        target = session.get(NovelCharacter, entity.target_character_id)
        if (
            source is None
            or target is None
            or source.novel_id != novel.id
            or target.novel_id != novel.id
        ):
            raise WorkspaceScopeError()
        return {
            "type": "relationship",
            "id": str(entity.id),
            "title": entity.label,
            "source_character_id": str(source.id),
            "target_character_id": str(target.id),
            "provenance": _provenance(
                "database_table", "character_relationships", 1
            ),
        }
    if entity_type == "storyline":
        return {
            "type": "storyline",
            "id": str(entity.id),
            "title": entity.title,
            "status": entity.status,
            "version": entity.version,
            "provenance": _provenance("database_table", "storylines", 1),
        }
    return {
        "type": "foreshadow",
        "id": str(entity.id),
        "title": entity.title,
        "status": entity.status,
        "version": entity.version,
        "provenance": _provenance("database_table", "foreshadows", 1),
    }


def _json_character_count(value: object) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def _append_once(items: list[str], item: str) -> None:
    if item not in items:
        items.append(item)


def _truncate_middle(value: str, maximum: int) -> tuple[str, bool]:
    if len(value) <= maximum:
        return value, False
    marker = "\n…[本章正文中段已截断]…\n"
    available = maximum - len(marker)
    head = (available * 3) // 5
    tail = available - head
    return f"{value[:head]}{marker}{value[-tail:]}", True


def _chapter_naming_context(
    rows: list[tuple[Document, DocumentWorkingCopy]],
    current_document: Document,
    *,
    projected_titles: dict[UUID, str] | None = None,
) -> tuple[dict[str, Any], list[str], bool]:
    current_pair = next(
        ((row, working) for row, working in rows if row.id == current_document.id),
        None,
    )
    if current_pair is None:
        return (
            {
                "current_chapter": _document_envelope(
                    current_document,
                    projected_title=(projected_titles or {}).get(current_document.id),
                ),
                "chapter_titles_in_book_order": [],
                "title_index_truncated": False,
            },
            ["current chapter working copy is unavailable for title generation"],
            True,
        )

    chapter, working = current_pair
    content, content_truncated = _truncate_middle(
        working.content_markdown,
        CHAPTER_NAMING_BODY_MAX_CHARS,
    )
    chapter_payload = _document_payload(chapter, working)
    title_by_id = {
        row.id: (projected_titles or {}).get(
            row.id,
            context_chapter_title(row.title, ordinal),
        )
        for ordinal, (row, _working) in enumerate(rows, start=1)
    }
    chapter_payload["title"] = title_by_id[chapter.id]
    chapter_payload["content_markdown"] = content
    chapter_payload["content_truncated"] = content_truncated
    chapter_payload["returned_character_count"] = len(content)

    ordered_titles = [title_by_id[row.id] for row, _working in rows]
    title_index_truncated = len(ordered_titles) > CHAPTER_NAMING_TITLE_LIMIT
    if title_index_truncated:
        current_index = next(
            index for index, (row, _working) in enumerate(rows) if row.id == chapter.id
        )
        # Keep the beginning, the current chapter's neighbourhood, and the end.
        keep: set[int] = set(range(min(150, len(ordered_titles))))
        keep.update(
            range(
                max(0, current_index - 100),
                min(len(ordered_titles), current_index + 101),
            )
        )
        keep.update(range(max(0, len(ordered_titles) - 150), len(ordered_titles)))
        ordered_titles = [
            title for index, title in enumerate(ordered_titles) if index in keep
        ][:CHAPTER_NAMING_TITLE_LIMIT]

    warnings: list[str] = []
    if content_truncated:
        warnings.append("current chapter body was middle-truncated for title generation")
    if title_index_truncated:
        warnings.append("chapter title index was truncated for title generation")
    return (
        {
            "current_chapter": chapter_payload,
            "chapter_titles_in_book_order": ordered_titles,
            "title_index_truncated": title_index_truncated,
        },
        warnings,
        content_truncated or title_index_truncated,
    )


def get_assistant_workspace_context(
    session: Session,
    *,
    owner_scope: WorkspaceOwnerScope,
    novel_id: UUID,
    section: str,
    schema_version: int = WORKSPACE_CONTEXT_SCHEMA_VERSION,
    document_id: UUID | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    include: Collection[str] | None = None,
    max_chars: int = WORKSPACE_CONTEXT_DEFAULT_MAX_CHARS,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict[str, Any]:
    """Return a bounded read-only snapshot of persisted workspace material.

    ``owner_scope`` is an authorization input produced by the server/tool layer,
    never from model arguments. Chapter working-copy content is returned only
    for the explicitly requested, bounded ``chapter_naming`` category and only
    for the current server-scoped chapter.
    """

    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version != WORKSPACE_CONTEXT_SCHEMA_VERSION
    ):
        raise ValidationError(
            f"unsupported workspace schema version: {schema_version}"
        )
    selected_includes = _normalize_include(section, include)
    character_budget = _normalize_max_chars(max_chars)
    if not isinstance(novel_id, UUID):
        raise ValidationError("novel_id must be a UUID")
    if document_id is not None and not isinstance(document_id, UUID):
        raise ValidationError("document_id must be a UUID")
    if entity_id is not None and not isinstance(entity_id, UUID):
        raise ValidationError("entity_id must be a UUID")
    if not owner_scope.owner_id or novel_id not in owner_scope.novel_ids:
        raise WorkspaceScopeError()

    novel = session.get(Novel, novel_id)
    if novel is None:
        raise WorkspaceScopeError()

    document: Document | None = None
    if document_id is not None:
        document = session.get(Document, document_id)
        if document is None or document.novel_id != novel_id:
            raise WorkspaceScopeError()
    chapter_titles = (
        _chapter_title_projection(session, novel_id)
        if (
            (document is not None and document.kind == "chapter")
            or entity_type == "document"
        )
        else {}
    )
    volume_titles = (
        _volume_title_projection(session, novel_id) if entity_type == "volume" else {}
    )
    entity = _scope_entity(
        session,
        novel,
        entity_type,
        entity_id,
        chapter_titles=chapter_titles,
        volume_titles=volume_titles,
    )
    if (
        document is not None
        and entity_type == "document"
        and entity_id != document.id
    ):
        raise ValidationError("document_id and document entity must identify the same document")

    as_of = _as_of(clock)
    section_data: dict[str, object] = {}
    section_provenance: dict[str, list[dict[str, Any]]] = {}
    warnings: list[str] = []
    incomplete_sections: list[str] = []

    if "chapter_naming" in selected_includes:
        if document is None or document.kind != "chapter":
            section_data["chapter_naming"] = {
                "current_chapter": None,
                "chapter_titles_in_book_order": [],
                "title_index_truncated": False,
            }
            section_provenance["chapter_naming"] = []
            warnings.append("chapter_naming requires a current chapter document")
            incomplete_sections.append("chapter_naming")
        else:
            rows = _load_working_documents(session, novel_id, "chapter")
            payload, naming_warnings, incomplete = _chapter_naming_context(
                rows,
                document,
                projected_titles=chapter_titles,
            )
            section_data["chapter_naming"] = payload
            section_provenance["chapter_naming"] = [
                _provenance("database_table", "documents", len(rows)),
                _provenance(
                    "working_copy",
                    "document_working_copies",
                    1
                    if isinstance(payload["current_chapter"], dict)
                    and "content_markdown" in payload["current_chapter"]
                    else 0,
                ),
            ]
            warnings.extend(naming_warnings)
            if incomplete:
                incomplete_sections.append("chapter_naming")

    if "outline" in selected_includes:
        rows = _load_working_documents(session, novel_id, "outline")
        section_data["outline"] = {
            "novel": _novel_outline_payload(novel),
            "documents": [
                _document_payload(document_row, working) for document_row, working in rows
            ],
        }
        section_provenance["outline"] = [
            _provenance("database_table", "novels", 1),
            _provenance("working_copy", "document_working_copies", len(rows)),
        ]

    character_rows: list[NovelCharacter] | None = None
    character_by_id: dict[UUID, NovelCharacter] = {}
    if "characters" in selected_includes or "relationships" in selected_includes:
        character_rows = list(
            session.scalars(
                select(NovelCharacter)
                .where(NovelCharacter.novel_id == novel_id)
                .order_by(NovelCharacter.position, NovelCharacter.id)
            ).all()
        )
        character_by_id = {item.id: item for item in character_rows}

    if "characters" in selected_includes:
        active_characters = [
            item for item in character_rows or [] if item.lifecycle_state == "active"
        ]
        section_data["characters"] = [
            _character_payload(item) for item in active_characters
        ]
        section_provenance["characters"] = [
            _provenance("database_table", "novel_characters", len(active_characters))
        ]

    if "relationships" in selected_includes:
        relationship_rows = list(
            session.scalars(
                select(CharacterRelationship)
                .where(
                    CharacterRelationship.novel_id == novel_id,
                    CharacterRelationship.archived_at.is_(None),
                )
                .order_by(CharacterRelationship.created_at, CharacterRelationship.id)
            ).all()
        )
        relationship_payloads: list[dict[str, Any]] = []
        invalid_endpoint_count = 0
        endpoint_ids: set[UUID] = set()
        for relationship in relationship_rows:
            if relationship.archived_at is not None:
                continue
            source = character_by_id.get(relationship.source_character_id)
            target = character_by_id.get(relationship.target_character_id)
            if (
                source is None
                or target is None
                or source.novel_id != novel_id
                or target.novel_id != novel_id
            ):
                invalid_endpoint_count += 1
                continue
            payload = _relationship_payload(relationship)
            payload["source_character_name"] = source.name
            payload["target_character_name"] = target.name
            relationship_payloads.append(payload)
            endpoint_ids.update((source.id, target.id))
        if invalid_endpoint_count:
            warnings.append(
                "relationships with endpoints outside the novel were omitted"
            )
            incomplete_sections.append("relationships")
        section_data["relationships"] = relationship_payloads
        section_provenance["relationships"] = [
            _provenance(
                "database_table",
                "character_relationships",
                len(relationship_payloads),
            ),
            _provenance("database_table", "novel_characters", len(endpoint_ids)),
        ]

    if "storylines" in selected_includes:
        rows = list(
            session.scalars(
                select(Storyline)
                .where(
                    Storyline.novel_id == novel_id,
                    Storyline.status != "archived",
                )
                .order_by(Storyline.position, Storyline.id)
            ).all()
        )
        rows = [item for item in rows if item.status != "archived"]
        section_data["storylines"] = [_storyline_payload(item) for item in rows]
        section_provenance["storylines"] = [
            _provenance("database_table", "storylines", len(rows))
        ]

    if "foreshadows" in selected_includes:
        rows = list(
            session.scalars(
                select(Foreshadow)
                .where(
                    Foreshadow.novel_id == novel_id,
                    Foreshadow.status != "dropped",
                )
                .order_by(Foreshadow.position, Foreshadow.id)
            ).all()
        )
        rows = [item for item in rows if item.status != "dropped"]
        section_data["foreshadows"] = [_foreshadow_payload(item) for item in rows]
        section_provenance["foreshadows"] = [
            _provenance("database_table", "foreshadows", len(rows))
        ]

    if "settings" in selected_includes:
        rows = _load_working_documents(session, novel_id, "setting")
        section_data["settings"] = {
            "novel": _novel_settings_payload(novel),
            "documents": [
                _document_payload(document_row, working) for document_row, working in rows
            ],
        }
        section_provenance["settings"] = [
            _provenance("database_table", "novels", 1),
            _provenance("working_copy", "document_working_copies", len(rows)),
        ]

    data: dict[str, object] = {}
    provenance: dict[str, list[dict[str, Any]]] = {}
    omitted_sections = list(incomplete_sections)
    used_chars = 0
    for include_name in selected_includes:
        payload = section_data[include_name]
        payload_chars = _json_character_count(payload)
        if used_chars + payload_chars > character_budget:
            _append_once(omitted_sections, include_name)
            warnings.append(f"{include_name} omitted by max_chars budget")
            continue
        data[include_name] = payload
        provenance[include_name] = section_provenance[include_name]
        used_chars += payload_chars

    return {
        "schema_version": WORKSPACE_CONTEXT_SCHEMA_VERSION,
        "as_of": as_of,
        "novel_id": str(novel_id),
        "section": section,
        "document_id": str(document.id) if document is not None else None,
        "document": (
            _document_envelope(
                document,
                projected_title=chapter_titles.get(document.id),
            )
            if document is not None
            else None
        ),
        "entity": entity,
        "provenance": provenance,
        "truncated": bool(omitted_sections),
        "omitted_sections": omitted_sections,
        "data": data,
        "warnings": warnings,
        "budget": {
            "max_chars": character_budget,
            "used_chars": used_chars,
        },
    }
