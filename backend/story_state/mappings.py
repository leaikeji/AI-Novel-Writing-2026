"""Immutable timeline mappings for one authoritative document revision.

Offsets are Python character offsets into ``DocumentRevision.content_text``.
Every saved mapping covers that text exactly once.  Mutations only flush; the
HTTP or calling service owns the transaction boundary.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from enum import Enum
from hashlib import sha256
import json
import re
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..creative_data_models import (
    RevisionTimelineMapping,
    RevisionTimelineMappingHead,
    RevisionTimelineMappingSegment,
    StoryTimeline,
)
from ..models import Document, DocumentRevision, Novel

from .contracts import StoryTimeV1
from .persistence import _iso


IdFactory = Callable[[], UUID]
Clock = Callable[[], datetime]
_OPERATION_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")


def _now() -> datetime:
    return datetime.now(UTC)


class MappingServiceErrorCode(str, Enum):
    NOVEL_NOT_FOUND = "novel_not_found"
    DOCUMENT_NOT_FOUND = "document_not_found"
    REVISION_NOT_FOUND = "document_revision_not_found"
    MAPPING_NOT_FOUND = "timeline_mapping_not_found"
    TIMELINE_REQUIRED = "timeline_required"
    INVALID_SEGMENTS = "invalid_timeline_mapping_segments"
    INVALID_OPERATION_KEY = "invalid_operation_key"
    VERSION_CONFLICT = "version_conflict"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"


class MappingServiceError(ValueError):
    def __init__(
        self,
        code: MappingServiceErrorCode,
        message: str,
        *,
        current: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.current = current


class TimelineMappingSegmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    timeline_id: UUID
    source_start: int = Field(ge=0)
    source_end: int = Field(gt=0)
    story_sequence: int | None = Field(default=None, ge=0)
    story_time: StoryTimeV1 = Field(default_factory=StoryTimeV1)


def _validate_operation_key(operation_key: str) -> str:
    cleaned = operation_key.strip()
    if not _OPERATION_KEY_RE.fullmatch(cleaned):
        raise MappingServiceError(
            MappingServiceErrorCode.INVALID_OPERATION_KEY,
            "operation_key must be 1-120 safe ASCII characters",
        )
    return cleaned


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def timeline_mapping_segment_payload(
    row: RevisionTimelineMappingSegment,
) -> dict[str, object]:
    return {
        "id": str(row.id),
        "mapping_revision_id": str(row.mapping_revision_id),
        "novel_id": str(row.novel_id),
        "timeline_id": str(row.timeline_id),
        "ordinal": row.ordinal,
        "source_start": row.source_start,
        "source_end": row.source_end,
        "story_sequence": row.story_sequence,
        "story_time": dict(row.story_time_json or {}),
    }


def timeline_mapping_payload(
    row: RevisionTimelineMapping,
    segments: Sequence[RevisionTimelineMappingSegment],
    *,
    head_version: int | None,
    is_current: bool,
) -> dict[str, object]:
    ordered = sorted(segments, key=lambda item: (item.ordinal, item.id))
    return {
        "id": str(row.id),
        "novel_id": str(row.novel_id),
        "document_id": str(row.document_id),
        "revision_id": str(row.revision_id),
        "source_content_hash": row.source_content_hash,
        "mapping_version": row.mapping_version,
        "source_kind": row.source_kind,
        "operation_key": row.operation_key,
        "mapping_digest": row.mapping_digest,
        "created_at": _iso(row.created_at),
        "head_version": head_version,
        "is_current": is_current,
        "segments": [timeline_mapping_segment_payload(item) for item in ordered],
    }


def _document_and_revision(
    session: Session,
    novel_id: UUID,
    document_id: UUID,
    revision_id: UUID,
) -> tuple[Document, DocumentRevision]:
    document = session.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.novel_id == novel_id,
            Document.kind == "chapter",
        )
    )
    if document is None:
        raise MappingServiceError(
            MappingServiceErrorCode.DOCUMENT_NOT_FOUND,
            "chapter document was not found in the novel",
        )
    revision = session.scalar(
        select(DocumentRevision).where(
            DocumentRevision.id == revision_id,
            DocumentRevision.document_id == document_id,
        )
    )
    if revision is None:
        raise MappingServiceError(
            MappingServiceErrorCode.REVISION_NOT_FOUND,
            "document revision was not found in the novel document",
        )
    return document, revision


def _timelines(session: Session, novel_id: UUID) -> list[StoryTimeline]:
    return list(
        session.scalars(
            select(StoryTimeline)
            .where(StoryTimeline.novel_id == novel_id)
            .order_by(StoryTimeline.position, StoryTimeline.id)
        )
    )


def _normalize_segments(
    segments: Sequence[TimelineMappingSegmentInput] | None,
    *,
    timelines: Sequence[StoryTimeline],
    content_length: int,
) -> tuple[list[dict[str, object]], Literal["manual", "auto_single"]]:
    if content_length <= 0:
        raise MappingServiceError(
            MappingServiceErrorCode.INVALID_SEGMENTS,
            "an empty document revision cannot have non-empty timeline ranges",
        )
    if segments is None:
        if len(timelines) != 1:
            raise MappingServiceError(
                MappingServiceErrorCode.TIMELINE_REQUIRED,
                "multi-timeline documents require explicit character ranges",
                current={"timeline_count": len(timelines)},
            )
        segments = (
            TimelineMappingSegmentInput(
                timeline_id=timelines[0].id,
                source_start=0,
                source_end=content_length,
            ),
        )
        source_kind: Literal["manual", "auto_single"] = "auto_single"
    else:
        source_kind = "manual"
    if not segments:
        raise MappingServiceError(
            MappingServiceErrorCode.INVALID_SEGMENTS,
            "timeline mapping must contain at least one segment",
        )

    timeline_ids = {item.id for item in timelines}
    ordered = sorted(segments, key=lambda item: (item.source_start, item.source_end))
    normalized: list[dict[str, object]] = []
    expected_start = 0
    for item in ordered:
        if item.timeline_id not in timeline_ids:
            raise MappingServiceError(
                MappingServiceErrorCode.INVALID_SEGMENTS,
                "timeline segment references a cross-novel or unknown timeline",
            )
        if item.source_start != expected_start or item.source_end <= item.source_start:
            raise MappingServiceError(
                MappingServiceErrorCode.INVALID_SEGMENTS,
                "timeline segments must be contiguous, non-overlapping, and non-empty",
                current={"expected_source_start": expected_start},
            )
        if item.source_end > content_length:
            raise MappingServiceError(
                MappingServiceErrorCode.INVALID_SEGMENTS,
                "timeline segment ends beyond the revision text",
                current={"content_length": content_length},
            )
        normalized.append(
            {
                "timeline_id": str(item.timeline_id),
                "source_start": item.source_start,
                "source_end": item.source_end,
                "story_sequence": item.story_sequence,
                "story_time": item.story_time.model_dump(mode="json", exclude_none=True),
            }
        )
        expected_start = item.source_end
    if expected_start != content_length:
        raise MappingServiceError(
            MappingServiceErrorCode.INVALID_SEGMENTS,
            "timeline segments must cover the complete revision text",
            current={"expected_source_end": content_length, "actual_source_end": expected_start},
        )
    return normalized, source_kind


def save_revision_timeline_mapping(
    session: Session,
    novel_id: UUID,
    document_id: UUID,
    revision_id: UUID,
    *,
    expected_head_version: int,
    operation_key: str,
    segments: Sequence[TimelineMappingSegmentInput] | None = None,
    id_factory: IdFactory = uuid4,
    clock: Clock = _now,
) -> dict[str, object]:
    """Append a mapping revision and move its CAS head in one transaction."""

    novel = session.scalar(
        select(Novel).where(Novel.id == novel_id).with_for_update()
    )
    if novel is None:
        raise MappingServiceError(
            MappingServiceErrorCode.NOVEL_NOT_FOUND,
            "novel was not found",
        )
    key = _validate_operation_key(operation_key)
    _, source_revision = _document_and_revision(
        session, novel_id, document_id, revision_id
    )
    timelines = _timelines(session, novel_id)
    normalized, source_kind = _normalize_segments(
        segments,
        timelines=timelines,
        content_length=len(source_revision.content_text),
    )
    digest = _canonical_hash(normalized)
    operation_hash = _canonical_hash(
        {
            "action": "save",
            "novel_id": str(novel_id),
            "document_id": str(document_id),
            "revision_id": str(revision_id),
            "source_content_hash": source_revision.content_hash,
            "source_kind": source_kind,
            "mapping_digest": digest,
        }
    )
    head = session.scalar(
        select(RevisionTimelineMappingHead)
        .where(
            RevisionTimelineMappingHead.revision_id == revision_id,
            RevisionTimelineMappingHead.document_id == document_id,
            RevisionTimelineMappingHead.novel_id == novel_id,
        )
        .with_for_update()
    )
    history = list(
        session.scalars(
            select(RevisionTimelineMapping)
            .where(
                RevisionTimelineMapping.revision_id == revision_id,
                RevisionTimelineMapping.document_id == document_id,
                RevisionTimelineMapping.novel_id == novel_id,
            )
            .order_by(RevisionTimelineMapping.mapping_version)
            .with_for_update()
        )
    )
    replay = next((item for item in history if item.operation_key == key), None)
    if replay is not None:
        if replay.operation_hash != operation_hash:
            raise MappingServiceError(
                MappingServiceErrorCode.IDEMPOTENCY_CONFLICT,
                "operation_key was already used with another mapping payload",
            )
        replay_segments = list(
            session.scalars(
                select(RevisionTimelineMappingSegment)
                .where(RevisionTimelineMappingSegment.mapping_revision_id == replay.id)
                .order_by(RevisionTimelineMappingSegment.ordinal)
            )
        )
        return {
            "mapping": timeline_mapping_payload(
                replay,
                replay_segments,
                head_version=head.version if head else None,
                is_current=bool(head and head.current_mapping_revision_id == replay.id),
            ),
            "replayed": True,
            "changed": False,
            "story_ledger_version": novel.story_ledger_version,
        }

    actual_head_version = head.version if head is not None else 0
    if actual_head_version != expected_head_version:
        raise MappingServiceError(
            MappingServiceErrorCode.VERSION_CONFLICT,
            "timeline mapping head version changed",
            current={
                "head_version": actual_head_version,
                "current_mapping_revision_id": (
                    str(head.current_mapping_revision_id) if head is not None else None
                ),
            },
        )
    if head is not None and head.source_content_hash != source_revision.content_hash:
        raise MappingServiceError(
            MappingServiceErrorCode.VERSION_CONFLICT,
            "timeline mapping head belongs to another source content hash",
        )

    created_at = clock()
    row = RevisionTimelineMapping(
        id=id_factory(),
        novel_id=novel_id,
        document_id=document_id,
        revision_id=revision_id,
        source_content_hash=source_revision.content_hash,
        mapping_version=max((item.mapping_version for item in history), default=0) + 1,
        source_kind=source_kind,
        operation_key=key,
        operation_hash=operation_hash,
        mapping_digest=digest,
        created_at=created_at,
    )
    segment_rows = [
        RevisionTimelineMappingSegment(
            id=id_factory(),
            mapping_revision_id=row.id,
            novel_id=novel_id,
            timeline_id=UUID(str(item["timeline_id"])),
            ordinal=ordinal,
            source_start=int(item["source_start"]),
            source_end=int(item["source_end"]),
            story_sequence=(
                int(item["story_sequence"])
                if item["story_sequence"] is not None
                else None
            ),
            story_time_json=dict(item["story_time"]),
        )
        for ordinal, item in enumerate(normalized)
    ]
    if head is None:
        head = RevisionTimelineMappingHead(
            revision_id=revision_id,
            document_id=document_id,
            novel_id=novel_id,
            source_content_hash=source_revision.content_hash,
            current_mapping_revision_id=row.id,
            version=1,
            updated_at=created_at,
        )
        session.add(head)
    else:
        head.current_mapping_revision_id = row.id
        head.version += 1
        head.updated_at = created_at
    session.add(row)
    session.add_all(segment_rows)
    novel.story_ledger_version += 1
    session.flush()
    return {
        "mapping": timeline_mapping_payload(
            row, segment_rows, head_version=head.version, is_current=True
        ),
        "replayed": False,
        "changed": True,
        "story_ledger_version": novel.story_ledger_version,
    }


def get_revision_timeline_mapping(
    session: Session,
    novel_id: UUID,
    document_id: UUID,
    revision_id: UUID,
) -> dict[str, object]:
    _, source_revision = _document_and_revision(
        session, novel_id, document_id, revision_id
    )
    head = session.scalar(
        select(RevisionTimelineMappingHead).where(
            RevisionTimelineMappingHead.revision_id == revision_id,
            RevisionTimelineMappingHead.document_id == document_id,
            RevisionTimelineMappingHead.novel_id == novel_id,
        )
    )
    if head is None:
        raise MappingServiceError(
            MappingServiceErrorCode.MAPPING_NOT_FOUND,
            "current timeline mapping was not found",
        )
    row = session.scalar(
        select(RevisionTimelineMapping).where(
            RevisionTimelineMapping.id == head.current_mapping_revision_id,
            RevisionTimelineMapping.revision_id == revision_id,
            RevisionTimelineMapping.document_id == document_id,
            RevisionTimelineMapping.novel_id == novel_id,
        )
    )
    if (
        row is None
        or head.source_content_hash != source_revision.content_hash
        or row.source_content_hash != source_revision.content_hash
    ):
        raise MappingServiceError(
            MappingServiceErrorCode.MAPPING_NOT_FOUND,
            "current timeline mapping revision was not found in scope",
        )
    segments = list(
        session.scalars(
            select(RevisionTimelineMappingSegment)
            .where(
                RevisionTimelineMappingSegment.mapping_revision_id == row.id,
                RevisionTimelineMappingSegment.novel_id == novel_id,
            )
            .order_by(RevisionTimelineMappingSegment.ordinal)
        )
    )
    return timeline_mapping_payload(
        row, segments, head_version=head.version, is_current=True
    )


def list_revision_timeline_mapping_history(
    session: Session,
    novel_id: UUID,
    document_id: UUID,
    revision_id: UUID,
) -> list[dict[str, object]]:
    _, source_revision = _document_and_revision(
        session, novel_id, document_id, revision_id
    )
    head = session.scalar(
        select(RevisionTimelineMappingHead).where(
            RevisionTimelineMappingHead.revision_id == revision_id,
            RevisionTimelineMappingHead.document_id == document_id,
            RevisionTimelineMappingHead.novel_id == novel_id,
        )
    )
    rows = list(
        session.scalars(
            select(RevisionTimelineMapping)
            .where(
                RevisionTimelineMapping.revision_id == revision_id,
                RevisionTimelineMapping.document_id == document_id,
                RevisionTimelineMapping.novel_id == novel_id,
                RevisionTimelineMapping.source_content_hash == source_revision.content_hash,
            )
            .order_by(RevisionTimelineMapping.mapping_version.desc())
        )
    )
    if not rows:
        return []
    segment_rows = list(
        session.scalars(
            select(RevisionTimelineMappingSegment)
            .where(
                RevisionTimelineMappingSegment.mapping_revision_id.in_(
                    [item.id for item in rows]
                ),
                RevisionTimelineMappingSegment.novel_id == novel_id,
            )
            .order_by(
                RevisionTimelineMappingSegment.mapping_revision_id,
                RevisionTimelineMappingSegment.ordinal,
            )
        )
    )
    by_mapping: dict[UUID, list[RevisionTimelineMappingSegment]] = defaultdict(list)
    for item in segment_rows:
        by_mapping[item.mapping_revision_id].append(item)
    return [
        timeline_mapping_payload(
            item,
            by_mapping[item.id],
            head_version=head.version if head else None,
            is_current=bool(head and head.current_mapping_revision_id == item.id),
        )
        for item in rows
    ]
