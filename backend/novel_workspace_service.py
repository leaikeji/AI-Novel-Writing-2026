"""Bounded workspace navigation projections for long novels."""

from __future__ import annotations

import base64
from datetime import datetime
from hashlib import sha256
import json
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Integer, String, and_, cast, func, literal, null, or_, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Session

from .models import Document, DocumentWorkingCopy, Novel, Volume
from .services import NotFoundError


MANIFEST_SCHEMA_VERSION = "novel-workspace-manifest/1"
MANIFEST_DEFAULT_LIMIT = 200
MANIFEST_MAX_LIMIT = 200
UNGROUPED_VOLUME_POSITION = 2_147_483_647


class WorkspaceManifestError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _encode_cursor(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> dict[str, object]:
    try:
        padding = "=" * (-len(value) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode((value + padding).encode("ascii"))
        )
    except Exception as error:
        raise WorkspaceManifestError("workspace_cursor_invalid", "工作区游标无效") from error
    if not isinstance(payload, dict):
        raise WorkspaceManifestError("workspace_cursor_invalid", "工作区游标无效")
    return payload


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _manifest_material(session: Session, novel: Novel) -> tuple[str, int]:
    volume_count = select(func.count(Volume.id)).where(Volume.novel_id == novel.id).scalar_subquery()
    volume_updated = select(func.max(Volume.updated_at)).where(Volume.novel_id == novel.id).scalar_subquery()
    document_count = select(func.count(Document.id)).where(Document.novel_id == novel.id).scalar_subquery()
    document_updated = select(func.max(Document.updated_at)).where(Document.novel_id == novel.id).scalar_subquery()
    visible_count = (
        select(func.coalesce(func.sum(DocumentWorkingCopy.visible_character_count), 0))
        .join(Document, Document.id == DocumentWorkingCopy.document_id)
        .where(Document.novel_id == novel.id, Document.kind == "chapter")
        .scalar_subquery()
    )
    row = session.execute(
        select(
            volume_count,
            volume_updated,
            document_count,
            document_updated,
            visible_count,
        )
    ).one()
    material = json.dumps(
        [
            str(novel.id),
            novel.version,
            novel.story_ledger_version,
            int(row[0] or 0),
            _iso(row[1]),
            int(row[2] or 0),
            _iso(row[3]),
        ],
        separators=(",", ":"),
    )
    return sha256(material.encode("utf-8")).hexdigest(), int(row[4] or 0)


def _manifest_rows_statement(novel_id: UUID):
    uuid_type = PGUUID(as_uuid=True)
    timestamp_type = DateTime(timezone=True)
    volume_rows = select(
        literal("volume").label("kind"),
        Volume.id.label("id"),
        cast(null(), uuid_type).label("parent_volume_id"),
        cast(null(), String()).label("document_type"),
        Volume.title.label("title"),
        Volume.position.label("position"),
        cast(null(), String()).label("status"),
        Volume.version.label("version"),
        cast(null(), Integer()).label("draft_version"),
        cast(null(), uuid_type).label("base_revision_id"),
        cast(null(), String()).label("content_hash"),
        cast(null(), Integer()).label("visible_character_count"),
        cast(Volume.updated_at, timestamp_type).label("updated_at"),
        Volume.position.label("sort_volume_position"),
        literal(0).label("sort_kind"),
        literal(0).label("sort_position"),
        Volume.id.label("sort_id"),
    ).where(Volume.novel_id == novel_id)
    document_rows = (
        select(
            literal("document").label("kind"),
            Document.id.label("id"),
            Document.volume_id.label("parent_volume_id"),
            Document.kind.label("document_type"),
            Document.title.label("title"),
            Document.position.label("position"),
            Document.status.label("status"),
            Document.version.label("version"),
            DocumentWorkingCopy.draft_version.label("draft_version"),
            DocumentWorkingCopy.base_revision_id.label("base_revision_id"),
            DocumentWorkingCopy.content_hash.label("content_hash"),
            DocumentWorkingCopy.visible_character_count.label("visible_character_count"),
            DocumentWorkingCopy.updated_at.label("updated_at"),
            func.coalesce(Volume.position, UNGROUPED_VOLUME_POSITION).label("sort_volume_position"),
            literal(1).label("sort_kind"),
            Document.position.label("sort_position"),
            Document.id.label("sort_id"),
        )
        .join(DocumentWorkingCopy, DocumentWorkingCopy.document_id == Document.id)
        .outerjoin(Volume, Volume.id == Document.volume_id)
        .where(Document.novel_id == novel_id)
    )
    return volume_rows.union_all(document_rows).subquery("workspace_manifest_rows")


def get_workspace_manifest(
    session: Session,
    novel_id: UUID,
    *,
    cursor: str | None = None,
    limit: int = MANIFEST_DEFAULT_LIMIT,
) -> dict[str, Any]:
    if limit < 1 or limit > MANIFEST_MAX_LIMIT:
        raise WorkspaceManifestError(
            "workspace_limit_invalid",
            f"工作区分页大小必须在 1..{MANIFEST_MAX_LIMIT} 之间",
        )
    novel = session.get(Novel, novel_id)
    if novel is None:
        raise NotFoundError(f"novel {novel_id} not found")
    manifest_etag, visible_count = _manifest_material(session, novel)
    decoded: dict[str, object] | None = None
    if cursor:
        decoded = _decode_cursor(cursor)
        if decoded.get("schema") != MANIFEST_SCHEMA_VERSION:
            raise WorkspaceManifestError("workspace_cursor_invalid", "工作区游标版本无效")
        if decoded.get("novel_id") != str(novel_id):
            raise WorkspaceManifestError("workspace_cursor_invalid", "工作区游标不属于当前小说")
        if decoded.get("etag") != manifest_etag:
            raise WorkspaceManifestError("manifest_changed", "卷章目录已经变化，请从第一页重新加载")

    rows = _manifest_rows_statement(novel_id)
    statement = select(rows)
    if decoded is not None:
        try:
            volume_position = int(decoded["volume_position"])
            kind_order = int(decoded["kind_order"])
            item_position = int(decoded["item_position"])
            item_id = UUID(str(decoded["item_id"]))
        except (KeyError, TypeError, ValueError) as error:
            raise WorkspaceManifestError("workspace_cursor_invalid", "工作区游标无效") from error
        statement = statement.where(
            or_(
                rows.c.sort_volume_position > volume_position,
                and_(rows.c.sort_volume_position == volume_position, rows.c.sort_kind > kind_order),
                and_(rows.c.sort_volume_position == volume_position, rows.c.sort_kind == kind_order, rows.c.sort_position > item_position),
                and_(rows.c.sort_volume_position == volume_position, rows.c.sort_kind == kind_order, rows.c.sort_position == item_position, rows.c.sort_id > item_id),
            )
        )
    result_rows = session.execute(
        statement.order_by(
            rows.c.sort_volume_position,
            rows.c.sort_kind,
            rows.c.sort_position,
            rows.c.sort_id,
        ).limit(limit + 1)
    ).mappings().all()
    page = result_rows[:limit]
    items = [
        {
            "kind": row["kind"],
            "id": str(row["id"]),
            "parent_volume_id": str(row["parent_volume_id"]) if row["parent_volume_id"] else None,
            "document_type": row["document_type"],
            "title": row["title"],
            "position": row["position"],
            "status": row["status"],
            "version": row["version"],
            "draft_version": row["draft_version"],
            "base_revision_id": str(row["base_revision_id"]) if row["base_revision_id"] else None,
            "content_hash": row["content_hash"],
            "visible_character_count": row["visible_character_count"],
            "updated_at": _iso(row["updated_at"]),
        }
        for row in page
    ]
    next_cursor = None
    if len(result_rows) > limit and page:
        last = page[-1]
        next_cursor = _encode_cursor(
            {
                "schema": MANIFEST_SCHEMA_VERSION,
                "novel_id": str(novel_id),
                "etag": manifest_etag,
                "volume_position": last["sort_volume_position"],
                "kind_order": last["sort_kind"],
                "item_position": last["sort_position"],
                "item_id": str(last["sort_id"]),
            }
        )
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "novel": {
            "id": str(novel.id),
            "title": novel.title,
            "description": novel.description,
            "story_ledger_version": novel.story_ledger_version,
            "visible_character_count": visible_count,
            "updated_at": _iso(novel.updated_at),
        },
        "items": items,
        "next_cursor": next_cursor,
        "manifest_etag": manifest_etag,
    }
