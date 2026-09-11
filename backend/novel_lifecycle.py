"""Single authority for active, recycled, and restored novels."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from .models import (
    BackgroundJob,
    ChapterGenerationJob,
    CreativeGenerationJob,
    Document,
    DocumentWorkingCopy,
    MediaAsset,
    MediaGcDeletionRecord,
    Novel,
    NovelLifecycleEvent,
    VoiceDeletionRequest,
)
from .novel_lifecycle_errors import (
    NovelCleanupInProgress,
    NovelLifecycleBusy,
    NovelLifecycleIdempotencyConflict,
    NovelLifecycleNotFound,
    NovelLifecycleStateConflict,
    NovelLifecycleVersionConflict,
    NovelRecycledError,
    NovelRestoreIntegrityBlocked,
)


LOCAL_OWNER_ID = UUID("29cf94d9-a5c9-54ec-912c-5dfff8738c4c")
LOCAL_WORKSPACE_ID = UUID("f0e2e632-bc99-52d2-9916-bb906aa4da6e")
ACTIVE_BACKGROUND_STATES = frozenset(
    {"queued", "running", "retry_wait", "cancel_requested"}
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _validate_action_input(
    novel_id: UUID, expected_version: int, idempotency_key: str, actor: str
) -> tuple[str, str]:
    if type(novel_id) is not UUID:
        raise ValueError("novel_id must be an exact UUID")
    if type(expected_version) is not int or expected_version < 1:
        raise ValueError("expected_version must be a positive integer")
    key = idempotency_key.strip()
    trusted_actor = actor.strip()
    if not key or len(key) > 120:
        raise ValueError("idempotency_key must contain 1 to 120 characters")
    if not trusted_actor or len(trusted_actor) > 120:
        raise ValueError("actor is invalid")
    return key, trusted_actor


def _request_digest(
    action: str, novel_id: UUID, expected_version: int, actor: str
) -> str:
    payload = {
        "actor": actor,
        "expected_version": expected_version,
        "novel_id": str(novel_id),
        "owner_id": str(LOCAL_OWNER_ID),
        "schema": "novel-lifecycle-request/1",
        "workspace_id": str(LOCAL_WORKSPACE_ID),
        "action": action,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _receipt(event: NovelLifecycleEvent, *, replayed: bool) -> dict[str, object]:
    value = dict(event.result_json)
    value["replayed"] = replayed
    return value


def _existing_event(
    session: Session, novel_id: UUID, idempotency_key: str, digest: str
) -> NovelLifecycleEvent | None:
    event = session.scalar(
        select(NovelLifecycleEvent).where(
            NovelLifecycleEvent.novel_id == novel_id,
            NovelLifecycleEvent.idempotency_key == idempotency_key,
        )
    )
    if event is not None and event.request_sha256 != digest:
        raise NovelLifecycleIdempotencyConflict(
            "该幂等键已经用于不同的小说生命周期请求"
        )
    return event


def _scoped_novel_statement(novel_id: UUID):
    return select(Novel).where(
        Novel.id == novel_id,
        Novel.owner_id == LOCAL_OWNER_ID,
        Novel.workspace_id == LOCAL_WORKSPACE_ID,
    )


def require_active_novel(
    session: Session, novel_id: UUID, *, for_update: bool = False
) -> Novel:
    statement = _scoped_novel_statement(novel_id)
    if for_update:
        statement = statement.with_for_update()
    novel = session.scalar(statement)
    if novel is None:
        raise NovelLifecycleNotFound("小说不存在")
    # ORM rows always expose a real datetime here.  A few legacy unit-test
    # sessions return lightweight objects (or MagicMock instances) from
    # ``scalar``; do not mistake those test doubles for recycled novels.
    if isinstance(getattr(novel, "recycled_at", None), datetime):
        raise NovelRecycledError("小说已移入回收站")
    return novel


def lock_active_novel(
    session: Session, novel_id: UUID, expected_version: int | None = None
) -> Novel:
    novel = require_active_novel(session, novel_id, for_update=True)
    if expected_version is not None and novel.version != expected_version:
        raise NovelLifecycleVersionConflict("小说已在其他位置更新，请刷新后重试")
    return novel


def lock_recycled_novel(
    session: Session, novel_id: UUID, expected_version: int | None = None
) -> Novel:
    novel = session.scalar(_scoped_novel_statement(novel_id).with_for_update())
    if novel is None:
        raise NovelLifecycleNotFound("小说不存在")
    if novel.recycled_at is None:
        raise NovelLifecycleStateConflict("小说当前不在回收站")
    if expected_version is not None and novel.version != expected_version:
        raise NovelLifecycleVersionConflict("小说已在其他位置更新，请刷新后重试")
    return novel


def _assert_recyclable(session: Session, novel_id: UUID) -> None:
    active_background = session.scalar(
        select(func.count()).select_from(BackgroundJob).where(
            BackgroundJob.novel_id == novel_id,
            BackgroundJob.state.in_(ACTIVE_BACKGROUND_STATES),
        )
    )
    active_chapter = session.scalar(
        select(func.count())
        .select_from(ChapterGenerationJob)
        .join(Document, Document.id == ChapterGenerationJob.document_id)
        .where(Document.novel_id == novel_id, ChapterGenerationJob.state == "running")
    )
    active_creative = session.scalar(
        select(func.count()).select_from(CreativeGenerationJob).where(
            CreativeGenerationJob.novel_id == novel_id,
            CreativeGenerationJob.state == "running",
        )
    )
    if sum(int(value or 0) for value in (active_background, active_chapter, active_creative)):
        raise NovelLifecycleBusy("小说仍有进行中的任务，请稍后重试")
    deleting_assets = session.scalar(
        select(func.count()).select_from(MediaAsset).where(
            MediaAsset.novel_id == novel_id, MediaAsset.state == "deleting"
        )
    )
    gc_plans = session.scalar(
        select(func.count()).select_from(MediaGcDeletionRecord).where(
            MediaGcDeletionRecord.novel_id == novel_id
        )
    )
    voice_deletions = session.scalar(
        select(func.count()).select_from(VoiceDeletionRequest).where(
            VoiceDeletionRequest.novel_id == novel_id,
            VoiceDeletionRequest.state.in_(
                {
                    "grace_pending",
                    "requested",
                    "live_deleting",
                    "live_deleted_backup_pending",
                    "failed",
                }
            ),
        )
    )
    if sum(int(value or 0) for value in (deleting_assets, gc_plans, voice_deletions)):
        raise NovelCleanupInProgress("小说仍有媒体清理正在进行，请稍后重试")


def _assert_restore_integrity(session: Session, novel_id: UUID) -> list[str]:
    missing_working = session.scalar(
        select(func.count())
        .select_from(Document)
        .outerjoin(DocumentWorkingCopy, DocumentWorkingCopy.document_id == Document.id)
        .where(Document.novel_id == novel_id, DocumentWorkingCopy.document_id.is_(None))
    )
    if int(missing_working or 0):
        raise NovelRestoreIntegrityBlocked("小说权威正文结构不完整，暂时无法恢复")
    deleting = session.scalar(
        select(func.count()).select_from(MediaAsset).where(
            MediaAsset.novel_id == novel_id, MediaAsset.state == "deleting"
        )
    )
    if int(deleting or 0):
        raise NovelCleanupInProgress("小说仍有媒体清理正在进行，请稍后重试")
    missing_media = session.scalar(
        select(func.count()).select_from(MediaAsset).where(
            MediaAsset.novel_id == novel_id, MediaAsset.state == "deleted"
        )
    )
    return ["derived_media_missing"] if int(missing_media or 0) else []


def _lifecycle_action(
    session: Session,
    *,
    action: str,
    novel_id: UUID,
    expected_version: int,
    idempotency_key: str,
    actor: str,
) -> dict[str, object]:
    key, trusted_actor = _validate_action_input(
        novel_id, expected_version, idempotency_key, actor
    )
    digest = _request_digest(action, novel_id, expected_version, trusted_actor)
    existing = _existing_event(session, novel_id, key, digest)
    if existing is not None:
        return _receipt(existing, replayed=True)

    novel = session.scalar(_scoped_novel_statement(novel_id).with_for_update())
    if novel is None:
        raise NovelLifecycleNotFound("小说不存在")
    session.refresh(novel)
    existing = _existing_event(session, novel_id, key, digest)
    if existing is not None:
        return _receipt(existing, replayed=True)
    if novel.version != expected_version:
        raise NovelLifecycleVersionConflict("小说已在其他位置更新，请刷新后重试")

    warnings: list[str] = []
    timestamp = _now()
    if action == "recycled":
        if novel.recycled_at is not None:
            raise NovelLifecycleStateConflict("小说已经在回收站中")
        _assert_recyclable(session, novel_id)
        novel.recycled_at = timestamp
        novel.recycled_by = trusted_actor
        recycled_at: str | None = timestamp.isoformat()
    elif action == "restored":
        if novel.recycled_at is None:
            raise NovelLifecycleStateConflict("小说当前不在回收站")
        warnings = _assert_restore_integrity(session, novel_id)
        novel.recycled_at = None
        novel.recycled_by = None
        recycled_at = None
    else:  # pragma: no cover - internal contract
        raise ValueError("unknown lifecycle action")

    before = novel.version
    novel.version += 1
    novel.updated_at = timestamp
    event_id = uuid4()
    result: dict[str, object] = {
        "event_id": str(event_id),
        "action": action,
        "version": novel.version,
        "recycled_at": recycled_at,
        "warning_codes": warnings,
    }
    session.add(
        NovelLifecycleEvent(
            id=event_id,
            novel_id=novel_id,
            action=action,
            version_before=before,
            version_after=novel.version,
            title_sha256=hashlib.sha256(novel.title.encode("utf-8")).hexdigest(),
            actor=trusted_actor,
            idempotency_key=key,
            request_sha256=digest,
            result_json=result,
            occurred_at=timestamp,
        )
    )
    session.flush()
    result["replayed"] = False
    return result


def recycle_novel(
    session: Session,
    novel_id: UUID,
    expected_version: int,
    idempotency_key: str,
    actor: str = "local-author",
) -> dict[str, object]:
    return _lifecycle_action(
        session,
        action="recycled",
        novel_id=novel_id,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        actor=actor,
    )


def restore_novel(
    session: Session,
    novel_id: UUID,
    expected_version: int,
    idempotency_key: str,
    actor: str = "local-author",
) -> dict[str, object]:
    return _lifecycle_action(
        session,
        action="restored",
        novel_id=novel_id,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        actor=actor,
    )


def _encode_cursor(value: datetime, novel_id: UUID) -> str:
    raw = json.dumps([value.isoformat(), str(novel_id)], separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        timestamp, novel_id = json.loads(
            base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        )
        return datetime.fromisoformat(timestamp), UUID(novel_id)
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("invalid recycle-bin cursor") from error


def list_recycled_novels(
    session: Session, limit: int = 20, cursor: str | None = None
) -> dict[str, object]:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    chapter_stats = (
        select(
            Document.novel_id.label("novel_id"),
            func.count(Document.id).label("chapter_count"),
            func.coalesce(func.sum(DocumentWorkingCopy.visible_character_count), 0).label(
                "visible_character_count"
            ),
        )
        .join(DocumentWorkingCopy, DocumentWorkingCopy.document_id == Document.id)
        .where(Document.kind == "chapter")
        .group_by(Document.novel_id)
        .subquery()
    )
    media_stats = (
        select(
            MediaAsset.novel_id.label("novel_id"),
            func.coalesce(func.sum(MediaAsset.byte_size), 0).label("media_bytes"),
        )
        .where(MediaAsset.state != "deleted")
        .group_by(MediaAsset.novel_id)
        .subquery()
    )
    statement = (
        select(
            Novel,
            func.coalesce(chapter_stats.c.chapter_count, 0),
            func.coalesce(chapter_stats.c.visible_character_count, 0),
            func.coalesce(media_stats.c.media_bytes, 0),
        )
        .outerjoin(chapter_stats, chapter_stats.c.novel_id == Novel.id)
        .outerjoin(media_stats, media_stats.c.novel_id == Novel.id)
        .where(
            Novel.owner_id == LOCAL_OWNER_ID,
            Novel.workspace_id == LOCAL_WORKSPACE_ID,
            Novel.recycled_at.is_not(None),
        )
    )
    if cursor:
        recycled_at, cursor_id = _decode_cursor(cursor)
        statement = statement.where(
            or_(
                Novel.recycled_at < recycled_at,
                and_(Novel.recycled_at == recycled_at, Novel.id < cursor_id),
            )
        )
    rows = session.execute(
        statement.order_by(Novel.recycled_at.desc(), Novel.id.desc()).limit(limit + 1)
    ).all()
    page = rows[:limit]
    items = [
        {
            "id": str(novel.id),
            "title": novel.title,
            "recycled_at": novel.recycled_at.isoformat(),
            "version": novel.version,
            "chapter_count": int(chapters),
            "visible_character_count": int(characters),
            "media_bytes": int(media_bytes),
        }
        for novel, chapters, characters, media_bytes in page
    ]
    next_cursor = None
    if len(rows) > limit and page:
        last = page[-1][0]
        next_cursor = _encode_cursor(last.recycled_at, last.id)
    total_count = session.scalar(
        select(func.count()).select_from(Novel).where(
            Novel.owner_id == LOCAL_OWNER_ID,
            Novel.workspace_id == LOCAL_WORKSPACE_ID,
            Novel.recycled_at.is_not(None),
        )
    )
    return {"items": items, "next_cursor": next_cursor, "total_count": int(total_count or 0)}


__all__ = [
    "ACTIVE_BACKGROUND_STATES",
    "list_recycled_novels",
    "lock_active_novel",
    "lock_recycled_novel",
    "recycle_novel",
    "require_active_novel",
    "restore_novel",
]
