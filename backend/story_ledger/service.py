"""Snapshot-consistent, database-bounded whole-novel Story Ledger service."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from hashlib import sha256
from typing import Any, Mapping, Sequence
from uuid import UUID

from sqlalchemy import and_, case, exists, func, literal, or_, select, union_all
from sqlalchemy.orm import Session

from ..creative_data_models import (
    CharacterInstance,
    SemanticSource,
    StoryEventLink,
    StoryTimeline,
)
from ..models import (
    CharacterRelationship,
    DerivedSourceBinding,
    Document,
    DocumentRevision,
    DocumentWorkingCopy,
    Foreshadow,
    IntelligenceCommitBatch,
    Novel,
    NovelCharacter,
    StoryFact,
    Storyline,
)
from ..story_state import (
    StoryStateError,
    StoryTimelineRecord,
    resolve_timeline,
    validate_inheritance_dag,
)
from ..story_state.corrections import intelligence_batch_revert_impact
from ..story_state.effective_state import (
    FactHealthEvidence,
    FactProjectionEvidence,
    classify_fact_health,
)
from ..story_state.fact_authority import resolve_fact_authority_rows
from ..volume_chapter_titles import context_chapter_title
from .contracts import (
    LedgerBatchImpactPreview,
    LedgerBindingView,
    LedgerEntityReference,
    LedgerEventLinkView,
    LedgerFactDetail,
    LedgerFactImpactPreview,
    LedgerFactItem,
    LedgerFactPage,
    LedgerSourceExcerpt,
    LedgerSourceReference,
    LedgerSummary,
    LedgerTimelineContext,
)
from .query import (
    LedgerQueryFilters,
    TimelineQueryScope,
    classify_fact_ids_statement,
    fact_statement,
    filters_require_classified_scan,
    page_statement,
    raw_page_ids_statement,
    summary_statement,
)
from .tokens import (
    LedgerTokenError,
    decode_cursor,
    decode_snapshot,
    encode_cursor,
    encode_snapshot,
    filter_sha256,
)


class StoryLedgerErrorCode(str, Enum):
    NOVEL_NOT_FOUND = "novel_not_found"
    FACT_NOT_FOUND = "story_fact_not_found"
    BATCH_NOT_FOUND = "intelligence_commit_batch_not_found"
    TIMELINE_REQUIRED = "timeline_required"
    TIMELINE_NOT_FOUND = "timeline_not_found"
    INVALID_TIMELINE = "invalid_timeline"
    INVALID_CURSOR = "invalid_cursor"
    INVALID_SNAPSHOT = "invalid_snapshot_token"
    STALE_PAGE = "stale_page"
    SNAPSHOT_CONFLICT = "ledger_snapshot_conflict"
    SNAPSHOT_TRANSACTION_INVALID = "snapshot_transaction_invalid"


class StoryLedgerError(ValueError):
    def __init__(
        self,
        code: StoryLedgerErrorCode,
        message: str,
        *,
        current: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.current = dict(current or {})


@dataclass(frozen=True, slots=True)
class _ReadScope:
    novel: Novel
    snapshot_token: str
    timeline_rows: tuple[StoryTimeline, ...]
    timeline: LedgerTimelineContext
    query_scope: TimelineQueryScope


@dataclass(frozen=True, slots=True)
class _RevisionMeta:
    id: UUID
    document_id: UUID
    revision_number: int
    content_hash: str
    content_length: int


@dataclass(frozen=True, slots=True)
class _EntityMeta:
    label: str
    lifecycle_state: str | None


@dataclass(frozen=True, slots=True)
class _Evidence:
    facts: dict[UUID, StoryFact]
    bindings_by_fact_id: dict[UUID, tuple[DerivedSourceBinding, ...]]
    batches_by_id: dict[UUID, IntelligenceCommitBatch]
    links_by_fact_id: dict[UUID, tuple[StoryEventLink, ...]]
    documents_by_id: dict[UUID, Document]
    revisions_by_id: dict[UUID, _RevisionMeta]
    current_revision_by_document_id: dict[UUID, UUID | None]
    entities_by_type_and_id: dict[tuple[str, UUID], _EntityMeta]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _begin_repeatable_read(session: Session) -> None:
    """Start, or verify, the one transaction used by a read response."""

    if not session.in_transaction():
        session.connection(
            execution_options={"isolation_level": "REPEATABLE READ"}
        )
        return
    isolation = session.connection().get_isolation_level().upper()
    if isolation not in {"REPEATABLE READ", "SERIALIZABLE"}:
        raise StoryLedgerError(
            StoryLedgerErrorCode.SNAPSHOT_TRANSACTION_INVALID,
            "账本读取必须从新的 repeatable-read 事务开始",
        )


def _timeline_scope(
    rows: Sequence[StoryTimeline],
    novel_id: UUID,
    *,
    requested_timeline_id: UUID | None,
    narrative_cutoff: int | None,
) -> tuple[LedgerTimelineContext, TimelineQueryScope]:
    records = tuple(StoryTimelineRecord.model_validate(row) for row in rows)
    active = tuple(row for row in rows if row.lifecycle_state == "active")
    if not active:
        if requested_timeline_id is not None:
            raise StoryLedgerError(
                StoryLedgerErrorCode.TIMELINE_NOT_FOUND,
                "作品没有可用的活动时间线",
            )
        context = LedgerTimelineContext(
            mode="none", narrative_cutoff=narrative_cutoff
        )
        return context, TimelineQueryScope(
            timeline_id=None, limits_by_timeline_id={}
        )
    try:
        validate_inheritance_dag(records, novel_id)
        target = resolve_timeline(records, novel_id, requested_timeline_id)
    except StoryStateError as error:
        code = (
            StoryLedgerErrorCode.TIMELINE_REQUIRED
            if error.code.value == "timeline_required"
            else StoryLedgerErrorCode.TIMELINE_NOT_FOUND
            if error.code.value == "timeline_not_found"
            else StoryLedgerErrorCode.INVALID_TIMELINE
        )
        raise StoryLedgerError(code, str(error), current=error.details) from error

    by_id = {row.id: row for row in rows}
    limits: dict[UUID, int | None] = {}
    current = by_id[target.id]
    current_limit = narrative_cutoff
    visited: set[UUID] = set()
    while True:
        if current.id in visited:
            raise StoryLedgerError(
                StoryLedgerErrorCode.INVALID_TIMELINE,
                "时间线继承关系存在循环",
            )
        visited.add(current.id)
        limits[current.id] = current_limit
        if current.parent_timeline_id is None:
            break
        if current.fork_story_sequence is None:
            raise StoryLedgerError(
                StoryLedgerErrorCode.INVALID_TIMELINE,
                "分支时间线缺少继承锚点",
            )
        parent = by_id.get(current.parent_timeline_id)
        if parent is None:
            raise StoryLedgerError(
                StoryLedgerErrorCode.INVALID_TIMELINE,
                "分支时间线的父时间线不存在",
            )
        current_limit = (
            current.fork_story_sequence
            if current_limit is None
            else min(current_limit, current.fork_story_sequence)
        )
        current = parent
    context = LedgerTimelineContext(
        mode="multiple" if len(active) > 1 else "single",
        timeline_id=target.id,
        timeline_name=by_id[target.id].name,
        narrative_cutoff=narrative_cutoff,
    )
    return context, TimelineQueryScope(
        timeline_id=target.id,
        limits_by_timeline_id=limits,
    )


def _source_title(document: Document) -> str:
    if document.kind != "chapter":
        return document.title
    return context_chapter_title(document.title, max(1, document.position))


class StoryLedgerService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _read_scope(
        self,
        novel_id: UUID,
        *,
        timeline_id: UUID | None,
        narrative_cutoff: int | None,
        expected_snapshot_token: str | None,
        stale_page: bool = False,
    ) -> _ReadScope:
        _begin_repeatable_read(self.session)
        novel = self.session.scalar(select(Novel).where(Novel.id == novel_id))
        if novel is None:
            raise StoryLedgerError(
                StoryLedgerErrorCode.NOVEL_NOT_FOUND, "小说不存在"
            )
        current_token = encode_snapshot(novel.id, novel.story_ledger_version)
        if expected_snapshot_token is not None:
            try:
                identity = decode_snapshot(expected_snapshot_token)
            except LedgerTokenError as error:
                raise StoryLedgerError(
                    StoryLedgerErrorCode.INVALID_SNAPSHOT,
                    "账本快照 token 无效",
                    current={"ledger_snapshot_token": current_token},
                ) from error
            if (
                identity.novel_id != novel.id
                or identity.story_ledger_version != novel.story_ledger_version
                or expected_snapshot_token != current_token
            ):
                raise StoryLedgerError(
                    StoryLedgerErrorCode.STALE_PAGE
                    if stale_page
                    else StoryLedgerErrorCode.SNAPSHOT_CONFLICT,
                    "故事账本已经变化，请刷新后继续",
                    current={
                        "ledger_snapshot_token": current_token,
                        "story_ledger_version": novel.story_ledger_version,
                    },
                )
        timeline_rows = tuple(
            self.session.scalars(
                select(StoryTimeline)
                .where(StoryTimeline.novel_id == novel_id)
                .order_by(StoryTimeline.position, StoryTimeline.id)
            )
        )
        timeline, query_scope = _timeline_scope(
            timeline_rows,
            novel_id,
            requested_timeline_id=timeline_id,
            narrative_cutoff=narrative_cutoff,
        )
        return _ReadScope(
            novel=novel,
            snapshot_token=current_token,
            timeline_rows=timeline_rows,
            timeline=timeline,
            query_scope=query_scope,
        )

    @staticmethod
    def normalize_filters(filters: LedgerQueryFilters) -> LedgerQueryFilters:
        return LedgerQueryFilters(
            fact_types=tuple(
                sorted(
                    {
                        value.strip()
                        for value in filters.fact_types
                        if value.strip()
                    }
                )
            ),
            effective_state=filters.effective_state,
            health=filters.health,
            dimension=(
                filters.dimension.strip() if filters.dimension else None
            ),
            source_document_id=filters.source_document_id,
            commit_batch_id=filters.commit_batch_id,
            fact_timeline_id=filters.fact_timeline_id,
            entity_type=filters.entity_type,
            entity_id=filters.entity_id,
            review_only=filters.review_only,
        )

    def summary(
        self,
        novel_id: UUID,
        *,
        timeline_id: UUID | None = None,
        narrative_cutoff: int | None = None,
        filters: LedgerQueryFilters = LedgerQueryFilters(),
        snapshot_token: str | None = None,
    ) -> LedgerSummary:
        scope = self._read_scope(
            novel_id,
            timeline_id=timeline_id,
            narrative_cutoff=narrative_cutoff,
            expected_snapshot_token=snapshot_token,
        )
        normalized = self.normalize_filters(filters)
        digest = filter_sha256(
            normalized.canonical_payload(
                timeline_id=scope.timeline.timeline_id,
                narrative_cutoff=narrative_cutoff,
            )
        )
        rows = self.session.execute(
            summary_statement(novel_id, scope.query_scope, normalized)
        ).mappings()
        by_type: dict[str, int] = defaultdict(int)
        by_effective: dict[str, int] = {
            key: 0
            for key in (
                "current",
                "historical",
                "superseded",
                "source_invalid",
                "batch_reverted",
            )
        }
        by_health: dict[str, int] = {
            "ok": 0,
            "conflict": 0,
            "ambiguous": 0,
        }
        total = 0
        review_required = 0
        for row in rows:
            count = int(row["fact_count"])
            total += count
            by_type[str(row["fact_type"])] += count
            by_effective[str(row["effective_state"])] += count
            by_health[str(row["health"])] += count
            if row["health"] != "ok" or row["effective_state"] == "source_invalid":
                review_required += count
        return LedgerSummary(
            novel_id=novel_id,
            ledger_snapshot_token=scope.snapshot_token,
            story_ledger_version=scope.novel.story_ledger_version,
            timeline=scope.timeline,
            filter_sha256=digest,
            total=total,
            by_fact_type=dict(sorted(by_type.items())),
            by_effective_state=by_effective,
            by_health=by_health,
            review_required=review_required,
        )

    def list_facts(
        self,
        novel_id: UUID,
        *,
        timeline_id: UUID | None = None,
        narrative_cutoff: int | None = None,
        filters: LedgerQueryFilters = LedgerQueryFilters(),
        cursor: str | None = None,
        snapshot_token: str | None = None,
        limit: int = 20,
    ) -> LedgerFactPage:
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        normalized = self.normalize_filters(filters)
        cursor_identity = None
        if cursor is not None:
            try:
                cursor_identity = decode_cursor(cursor)
            except LedgerTokenError as error:
                raise StoryLedgerError(
                    StoryLedgerErrorCode.INVALID_CURSOR,
                    "账本分页游标无效",
                ) from error
            if (
                snapshot_token is not None
                and cursor_identity.snapshot_token != snapshot_token
            ):
                raise StoryLedgerError(
                    StoryLedgerErrorCode.STALE_PAGE,
                    "分页游标与请求快照不一致",
                )
        expected = (
            cursor_identity.snapshot_token
            if cursor_identity is not None
            else snapshot_token
        )
        scope = self._read_scope(
            novel_id,
            timeline_id=timeline_id,
            narrative_cutoff=narrative_cutoff,
            expected_snapshot_token=expected,
            stale_page=cursor_identity is not None,
        )
        digest = filter_sha256(
            normalized.canonical_payload(
                timeline_id=scope.timeline.timeline_id,
                narrative_cutoff=narrative_cutoff,
            )
        )
        if cursor_identity is not None and cursor_identity.filter_sha256 != digest:
            raise StoryLedgerError(
                StoryLedgerErrorCode.STALE_PAGE,
                "筛选条件已改变，旧分页不能继续追加",
                current={
                    "ledger_snapshot_token": scope.snapshot_token,
                    "story_ledger_version": scope.novel.story_ledger_version,
                    "filter_sha256": digest,
                },
            )
        before_created_at = (
            cursor_identity.created_at if cursor_identity else None
        )
        before_fact_id = cursor_identity.fact_id if cursor_identity else None
        if filters_require_classified_scan(normalized):
            raw_rows = list(
                self.session.execute(
                    page_statement(
                        novel_id,
                        scope.query_scope,
                        normalized,
                        limit=limit,
                        before_created_at=before_created_at,
                        before_fact_id=before_fact_id,
                    )
                ).mappings()
            )
            has_more = len(raw_rows) > limit
            page_rows = raw_rows[:limit]
        else:
            identity_rows = list(
                self.session.execute(
                    raw_page_ids_statement(
                        novel_id,
                        normalized,
                        limit=limit,
                        before_created_at=before_created_at,
                        before_fact_id=before_fact_id,
                    )
                ).mappings()
            )
            has_more = len(identity_rows) > limit
            page_identities = identity_rows[:limit]
            page_ids = tuple(row["id"] for row in page_identities)
            if page_ids:
                classified_rows = {
                    row["id"]: row
                    for row in self.session.execute(
                        classify_fact_ids_statement(
                            novel_id, scope.query_scope, page_ids
                        )
                    ).mappings()
                }
                page_rows = [classified_rows[row["id"]] for row in page_identities]
            else:
                page_rows = []
        items = self._items(page_rows, scope)
        next_cursor = None
        if has_more and page_rows:
            last = page_rows[-1]
            next_cursor = encode_cursor(
                snapshot_token=scope.snapshot_token,
                filter_sha256=digest,
                created_at=_utc(last["created_at"]),
                fact_id=last["id"],
            )
        return LedgerFactPage(
            novel_id=novel_id,
            ledger_snapshot_token=scope.snapshot_token,
            story_ledger_version=scope.novel.story_ledger_version,
            timeline=scope.timeline,
            filter_sha256=digest,
            items=items,
            next_cursor=next_cursor,
        )

    def detail(
        self,
        novel_id: UUID,
        fact_id: UUID,
        *,
        timeline_id: UUID | None = None,
        narrative_cutoff: int | None = None,
        snapshot_token: str | None = None,
    ) -> LedgerFactDetail:
        scope = self._read_scope(
            novel_id,
            timeline_id=timeline_id,
            narrative_cutoff=narrative_cutoff,
            expected_snapshot_token=snapshot_token,
        )
        row = self.session.execute(
            fact_statement(novel_id, scope.query_scope, fact_id)
        ).mappings().one_or_none()
        if row is None:
            raise StoryLedgerError(
                StoryLedgerErrorCode.FACT_NOT_FOUND, "故事事实不存在"
            )
        evidence = self._load_evidence((fact_id,))
        item = self._item(row, scope, evidence)
        fact = evidence.facts[fact_id]
        links = tuple(
            self._link_view(link, fact_id)
            for link in evidence.links_by_fact_id.get(fact_id, ())
        )
        bindings = tuple(
            self._binding_view(binding, evidence)
            for binding in evidence.bindings_by_fact_id.get(fact_id, ())
        )
        return LedgerFactDetail(
            novel_id=novel_id,
            ledger_snapshot_token=scope.snapshot_token,
            story_ledger_version=scope.novel.story_ledger_version,
            timeline=scope.timeline,
            item=item,
            object_text=fact.object_text,
            details=dict(fact.details or {}),
            story_time=(
                dict(fact.story_time_json)
                if isinstance(fact.story_time_json, dict)
                else None
            ),
            visibility=(
                dict(fact.visibility_json)
                if isinstance(fact.visibility_json, dict)
                else None
            ),
            lifecycle_status=fact.status,
            schema_version_of_fact=fact.schema_version,
            event_fingerprint=fact.event_fingerprint,
            event_links=links,
            bindings=bindings,
        )

    def source(
        self,
        novel_id: UUID,
        fact_id: UUID,
        *,
        timeline_id: UUID | None = None,
        narrative_cutoff: int | None = None,
        snapshot_token: str | None = None,
    ) -> LedgerSourceExcerpt:
        scope = self._read_scope(
            novel_id,
            timeline_id=timeline_id,
            narrative_cutoff=narrative_cutoff,
            expected_snapshot_token=snapshot_token,
        )
        fact = self.session.scalar(
            select(StoryFact).where(
                StoryFact.id == fact_id, StoryFact.novel_id == novel_id
            )
        )
        if fact is None:
            raise StoryLedgerError(
                StoryLedgerErrorCode.FACT_NOT_FOUND, "故事事实不存在"
            )
        base = {
            "novel_id": novel_id,
            "fact_id": fact_id,
            "ledger_snapshot_token": scope.snapshot_token,
            "story_ledger_version": scope.novel.story_ledger_version,
            "timeline": scope.timeline,
        }
        if fact.source_document_id is None or fact.source_revision_id is None:
            return LedgerSourceExcerpt(
                **base,
                available=False,
                unavailable_reason="source_reference_missing",
                document_id=fact.source_document_id,
                revision_id=fact.source_revision_id,
                source_start=fact.source_start,
                source_end=fact.source_end,
            )
        if fact.source_start is None or fact.source_end is None:
            return LedgerSourceExcerpt(
                **base,
                available=False,
                unavailable_reason="source_coordinates_missing",
                document_id=fact.source_document_id,
                revision_id=fact.source_revision_id,
            )

        excerpt_start = max(0, fact.source_start - 400)
        desired_end = max(fact.source_start + 800, fact.source_end + 400)
        excerpt_cap_end = excerpt_start + 1_600
        excerpt_end_expression = func.least(
            func.char_length(DocumentRevision.content_text),
            min(desired_end, excerpt_cap_end),
        )
        range_length = fact.source_end - fact.source_start
        source_row = self.session.execute(
            select(
                Document,
                DocumentWorkingCopy.base_revision_id,
                DocumentRevision.revision_number,
                DocumentRevision.content_hash,
                func.char_length(DocumentRevision.content_text).label(
                    "content_length"
                ),
                func.substr(
                    DocumentRevision.content_text,
                    excerpt_start + 1,
                    func.greatest(
                        0, excerpt_end_expression - excerpt_start
                    ),
                ).label("excerpt"),
                case(
                    (
                        range_length <= 8_192,
                        func.substr(
                            DocumentRevision.content_text,
                            fact.source_start + 1,
                            range_length,
                        ),
                    ),
                    else_=literal(None),
                ).label("range_text_for_hash"),
            )
            .join(
                DocumentRevision,
                and_(
                    DocumentRevision.id == fact.source_revision_id,
                    DocumentRevision.document_id == Document.id,
                ),
            )
            .outerjoin(
                DocumentWorkingCopy,
                DocumentWorkingCopy.document_id == Document.id,
            )
            .where(
                Document.id == fact.source_document_id,
                Document.novel_id == novel_id,
            )
        ).one_or_none()
        if source_row is None:
            return LedgerSourceExcerpt(
                **base,
                available=False,
                unavailable_reason="source_revision_missing_or_out_of_scope",
                document_id=fact.source_document_id,
                revision_id=fact.source_revision_id,
                source_start=fact.source_start,
                source_end=fact.source_end,
            )
        (
            document,
            current_revision_id,
            revision_number,
            content_hash,
            content_length,
            excerpt,
            range_text,
        ) = source_row
        if not (
            0 <= fact.source_start < fact.source_end <= int(content_length)
        ):
            return LedgerSourceExcerpt(
                **base,
                available=False,
                unavailable_reason="source_coordinates_invalid",
                document_id=document.id,
                document_title=_source_title(document),
                document_position=document.position,
                revision_id=fact.source_revision_id,
                revision_number=revision_number,
                revision_is_current=current_revision_id == fact.source_revision_id,
                source_content_hash=content_hash,
                source_start=fact.source_start,
                source_end=fact.source_end,
            )
        actual_excerpt_end = excerpt_start + len(excerpt or "")
        range_hash = (
            sha256(str(range_text).encode("utf-8")).hexdigest()
            if range_text is not None
            else None
        )
        return LedgerSourceExcerpt(
            **base,
            available=True,
            document_id=document.id,
            document_title=_source_title(document),
            document_position=document.position,
            revision_id=fact.source_revision_id,
            revision_number=revision_number,
            revision_is_current=current_revision_id == fact.source_revision_id,
            source_content_hash=content_hash,
            source_range_hash=range_hash,
            source_start=fact.source_start,
            source_end=fact.source_end,
            excerpt=excerpt or "",
            excerpt_start=excerpt_start,
            excerpt_end=actual_excerpt_end,
            highlight_start=fact.source_start - excerpt_start,
            highlight_end=min(fact.source_end, actual_excerpt_end) - excerpt_start,
            truncated_before=excerpt_start > 0,
            truncated_after=actual_excerpt_end < int(content_length),
        )

    def fact_impact_preview(
        self,
        novel_id: UUID,
        fact_id: UUID,
        *,
        timeline_id: UUID | None = None,
        narrative_cutoff: int | None = None,
        snapshot_token: str | None = None,
    ) -> LedgerFactImpactPreview:
        scope = self._read_scope(
            novel_id,
            timeline_id=timeline_id,
            narrative_cutoff=narrative_cutoff,
            expected_snapshot_token=snapshot_token,
        )
        row = self.session.execute(
            fact_statement(novel_id, scope.query_scope, fact_id)
        ).mappings().one_or_none()
        if row is None:
            raise StoryLedgerError(
                StoryLedgerErrorCode.FACT_NOT_FOUND, "故事事实不存在"
            )
        evidence = self._load_evidence((fact_id,))
        item = self._item(row, scope, evidence)
        fact = evidence.facts[fact_id]
        bindings = evidence.bindings_by_fact_id.get(fact_id, ())
        batch_ids = tuple(
            sorted(
                {
                    binding.commit_batch_id
                    for binding in bindings
                    if binding.commit_batch_id is not None
                },
                key=str,
            )
        )
        batch_fact_ids: set[str] = set()
        batch_relationship_ids: set[str] = set()
        for batch_id in batch_ids:
            batch = evidence.batches_by_id.get(batch_id)
            if batch is None:
                continue
            inverse = dict(batch.inverse_operations or {})
            batch_fact_ids.update(
                inverse.get("created_story_fact_ids", ()) or ()
            )
            for key in (
                "created_relationship_ids",
                "updated_relationship_ids",
            ):
                batch_relationship_ids.update(inverse.get(key, ()) or ())
        embedding_exists = bool(
            self.session.scalar(
                select(
                    exists(
                        select(literal(1)).select_from(SemanticSource).where(
                            SemanticSource.novel_id == novel_id,
                            SemanticSource.source_type == "story_fact",
                            SemanticSource.source_entity_id == fact_id,
                            SemanticSource.status.in_(("pending", "current")),
                        )
                    )
                )
            )
        )
        correction_supported, block_reason = self._correction_support(
            fact, item, evidence
        )
        return LedgerFactImpactPreview(
            novel_id=novel_id,
            fact_id=fact_id,
            preview_snapshot_token=scope.snapshot_token,
            story_ledger_version=scope.novel.story_ledger_version,
            timeline=scope.timeline,
            currently_in_projection=item.included_in_current_projection,
            current_projection_fact_count=(
                1 if item.included_in_current_projection else 0
            ),
            related_event_link_count=len(
                evidence.links_by_fact_id.get(fact_id, ())
            ),
            embedding_rebuild_required=embedding_exists,
            commit_batch_ids=batch_ids,
            batch_fact_count=len(batch_fact_ids),
            batch_relationship_count=len(batch_relationship_ids),
            correction_supported=correction_supported,
            correction_block_reason=block_reason,
        )

    def batch_impact_preview(
        self,
        novel_id: UUID,
        batch_id: UUID,
        *,
        timeline_id: UUID | None = None,
        narrative_cutoff: int | None = None,
        snapshot_token: str | None = None,
    ) -> LedgerBatchImpactPreview:
        scope = self._read_scope(
            novel_id,
            timeline_id=timeline_id,
            narrative_cutoff=narrative_cutoff,
            expected_snapshot_token=snapshot_token,
        )
        try:
            impact = intelligence_batch_revert_impact(
                self.session, novel_id, batch_id
            )
        except Exception as error:
            if getattr(getattr(error, "code", None), "value", None) in {
                "intelligence_commit_batch_not_found",
                "story_fact_not_found",
            }:
                raise StoryLedgerError(
                    StoryLedgerErrorCode.BATCH_NOT_FOUND, "同步批次不存在"
                ) from error
            raise
        facts = tuple(
            {
                **{
                    key: value
                    for key, value in raw.items()
                    if key not in {"object_text", "details", "visibility"}
                },
                "object_preview": str(raw.get("object_text") or "")[:300],
                "object_truncated": len(str(raw.get("object_text") or "")) > 300,
            }
            for raw in impact.get("facts", ())
            if isinstance(raw, dict)
        )
        relationships = tuple(
            dict(raw)
            for raw in impact.get("relationships", ())
            if isinstance(raw, dict)
        )
        return LedgerBatchImpactPreview(
            novel_id=novel_id,
            batch_id=batch_id,
            preview_snapshot_token=scope.snapshot_token,
            story_ledger_version=scope.novel.story_ledger_version,
            timeline=scope.timeline,
            state=str(impact["state"]),
            already_reverted=bool(impact["already_reverted"]),
            batch_fact_count=len(facts),
            batch_relationship_count=len(relationships),
            facts=facts,
            relationships=relationships,
        )

    def _items(
        self, rows: Sequence[Mapping[str, Any]], scope: _ReadScope
    ) -> tuple[LedgerFactItem, ...]:
        if not rows:
            return ()
        fact_ids = tuple(row["id"] for row in rows)
        evidence = self._load_evidence(fact_ids)
        return tuple(self._item(row, scope, evidence) for row in rows)

    def _item(
        self,
        row: Mapping[str, Any],
        scope: _ReadScope,
        evidence: _Evidence,
    ) -> LedgerFactItem:
        fact = evidence.facts[row["id"]]
        projection = FactProjectionEvidence(
            timeline_in_scope=bool(row["timeline_in_scope"]),
            narrative_cutoff=self._fact_cutoff(fact, scope),
            story_sequence=fact.story_sequence,
            story_sequence_required=bool(row["sequence_ambiguous"]),
            selected_as_current=bool(row["selected_as_current"]),
            is_state_fact=bool(row["is_state_fact"]),
        )
        bindings = evidence.bindings_by_fact_id.get(fact.id, ())
        incoming_supersedes = {
            fact.id
            for link in evidence.links_by_fact_id.get(fact.id, ())
            if link.link_type == "supersedes" and link.target_fact_id == fact.id
        }
        effective = resolve_fact_authority_rows(
            (fact,),
            bindings=bindings,
            batch_states={
                batch_id: batch.state
                for batch_id, batch in evidence.batches_by_id.items()
            },
            incoming_superseded_fact_ids=incoming_supersedes,
            projection_by_fact_id={fact.id: projection},
        )[fact.id]
        source_incomplete, hash_mismatch, coordinate_invalid = (
            self._source_health(fact, evidence)
        )
        entities = self._entity_refs(fact, evidence)
        health = classify_fact_health(
            FactHealthEvidence(
                explicit_contradiction=bool(row["explicit_contradiction"]),
                same_position_conflict=bool(row["same_position_conflict"]),
                source_reference_incomplete=source_incomplete,
                source_hash_mismatch=hash_mismatch,
                source_coordinate_invalid=coordinate_invalid,
                entity_reference_missing=any(
                    entity.reference_missing for entity in entities
                ),
                projection=projection,
            )
        )
        source = self._source_ref(fact, evidence)
        preview = fact.object_text[:300]
        return LedgerFactItem(
            id=fact.id,
            fact_type=fact.fact_type,
            subject=fact.subject,
            predicate=fact.predicate,
            object_preview=preview,
            object_truncated=len(fact.object_text) > len(preview),
            timeline_id=fact.timeline_id,
            dimension=fact.dimension,
            event_kind=fact.event_kind,
            story_sequence=fact.story_sequence,
            created_at=_utc(fact.created_at),
            effective_state=effective.effective_state.value,
            effective_reason_codes=tuple(
                reason.value for reason in effective.reason_codes
            ),
            included_in_current_projection=(
                effective.included_in_current_projection
            ),
            health=health.health.value,
            health_reason_codes=tuple(
                reason.value for reason in health.reason_codes
            ),
            entities=entities,
            source=source,
        )

    @staticmethod
    def _fact_cutoff(fact: StoryFact, scope: _ReadScope) -> int | None:
        if fact.timeline_id is None:
            return scope.timeline.narrative_cutoff
        return scope.query_scope.limits_by_timeline_id.get(fact.timeline_id)

    def _load_evidence(self, fact_ids: Sequence[UUID]) -> _Evidence:
        ids = tuple(dict.fromkeys(fact_ids))
        facts = tuple(
            self.session.scalars(
                select(StoryFact).where(StoryFact.id.in_(ids))
            )
        )
        by_id = {fact.id: fact for fact in facts}
        bindings = tuple(
            self.session.scalars(
                select(DerivedSourceBinding)
                .where(
                    DerivedSourceBinding.derived_entity_id.in_(ids),
                )
                .order_by(DerivedSourceBinding.created_at, DerivedSourceBinding.id)
            )
        )
        bindings_by_fact: dict[UUID, list[DerivedSourceBinding]] = defaultdict(list)
        for binding in bindings:
            bindings_by_fact[binding.derived_entity_id].append(binding)
        batch_ids = tuple(
            {
                binding.commit_batch_id
                for binding in bindings
                if binding.commit_batch_id is not None
            }
        )
        batches = (
            tuple(
                self.session.scalars(
                    select(IntelligenceCommitBatch).where(
                        IntelligenceCommitBatch.id.in_(batch_ids)
                    )
                )
            )
            if batch_ids
            else ()
        )
        links = tuple(
            self.session.scalars(
                select(StoryEventLink)
                .where(
                    or_(
                        StoryEventLink.source_fact_id.in_(ids),
                        StoryEventLink.target_fact_id.in_(ids),
                    )
                )
                .order_by(StoryEventLink.created_at, StoryEventLink.id)
            )
        )
        links_by_fact: dict[UUID, list[StoryEventLink]] = defaultdict(list)
        for link in links:
            if link.source_fact_id in by_id:
                links_by_fact[link.source_fact_id].append(link)
            if link.target_fact_id in by_id and link.target_fact_id != link.source_fact_id:
                links_by_fact[link.target_fact_id].append(link)

        document_ids = tuple(
            {fact.source_document_id for fact in facts if fact.source_document_id}
        )
        revision_ids = tuple(
            {fact.source_revision_id for fact in facts if fact.source_revision_id}
        )
        source_rows = (
            tuple(
                self.session.execute(
                    select(
                        Document,
                        DocumentWorkingCopy.base_revision_id,
                        DocumentRevision.id,
                        DocumentRevision.document_id,
                        DocumentRevision.revision_number,
                        DocumentRevision.content_hash,
                        func.char_length(DocumentRevision.content_text).label(
                            "content_length"
                        ),
                    )
                    .outerjoin(
                        DocumentWorkingCopy,
                        DocumentWorkingCopy.document_id == Document.id,
                    )
                    .outerjoin(
                        DocumentRevision,
                        and_(
                            DocumentRevision.document_id == Document.id,
                            DocumentRevision.id.in_(revision_ids),
                        ),
                    )
                    .where(Document.id.in_(document_ids))
                )
            )
            if document_ids
            else ()
        )

        instance_ids = tuple(
            {
                fact.character_instance_id
                for fact in facts
                if fact.character_instance_id
            }
        )
        character_ids = tuple(
            {fact.character_id for fact in facts if fact.character_id}
        )
        relationship_ids = tuple(
            {fact.relationship_id for fact in facts if fact.relationship_id}
        )
        storyline_ids = tuple(
            {fact.storyline_id for fact in facts if fact.storyline_id}
        )
        foreshadow_ids = tuple(
            {fact.foreshadow_id for fact in facts if fact.foreshadow_id}
        )
        entity_selects = []
        if character_ids:
            entity_selects.append(
                select(
                    literal("character").label("entity_type"),
                    NovelCharacter.id.label("entity_id"),
                    NovelCharacter.name.label("label"),
                    NovelCharacter.lifecycle_state.label("lifecycle_state"),
                ).where(NovelCharacter.id.in_(character_ids))
            )
        if instance_ids:
            entity_selects.append(
                select(
                    literal("character_instance").label("entity_type"),
                    CharacterInstance.id.label("entity_id"),
                    func.coalesce(
                        func.nullif(CharacterInstance.display_label, ""),
                        NovelCharacter.name,
                        "人物实例",
                    ).label("label"),
                    CharacterInstance.lifecycle_state.label("lifecycle_state"),
                )
                .outerjoin(
                    NovelCharacter,
                    NovelCharacter.id == CharacterInstance.character_id,
                )
                .where(CharacterInstance.id.in_(instance_ids))
            )
        if relationship_ids:
            entity_selects.append(
                select(
                    literal("relationship").label("entity_type"),
                    CharacterRelationship.id.label("entity_id"),
                    CharacterRelationship.label.label("label"),
                    case(
                        (
                            CharacterRelationship.archived_at.is_not(None),
                            "archived",
                        ),
                        else_="active",
                    ).label("lifecycle_state"),
                ).where(CharacterRelationship.id.in_(relationship_ids))
            )
        if storyline_ids:
            entity_selects.append(
                select(
                    literal("storyline").label("entity_type"),
                    Storyline.id.label("entity_id"),
                    Storyline.title.label("label"),
                    Storyline.status.label("lifecycle_state"),
                ).where(Storyline.id.in_(storyline_ids))
            )
        if foreshadow_ids:
            entity_selects.append(
                select(
                    literal("foreshadow").label("entity_type"),
                    Foreshadow.id.label("entity_id"),
                    Foreshadow.title.label("label"),
                    Foreshadow.status.label("lifecycle_state"),
                ).where(Foreshadow.id.in_(foreshadow_ids))
            )
        entity_rows = (
            tuple(self.session.execute(union_all(*entity_selects)))
            if entity_selects
            else ()
        )
        documents_by_id = {
            row[0].id: row[0]
            for row in source_rows
        }
        current_revision_by_document_id = {
            row[0].id: row[1]
            for row in source_rows
        }
        revisions_by_id = {
            row[2]: _RevisionMeta(
                id=row[2],
                document_id=row[3],
                revision_number=row[4],
                content_hash=row[5],
                content_length=int(row[6]),
            )
            for row in source_rows
            if row[2] is not None
        }
        return _Evidence(
            facts=by_id,
            bindings_by_fact_id={
                fact_id: tuple(values)
                for fact_id, values in bindings_by_fact.items()
            },
            batches_by_id={batch.id: batch for batch in batches},
            links_by_fact_id={
                fact_id: tuple(values)
                for fact_id, values in links_by_fact.items()
            },
            documents_by_id=documents_by_id,
            revisions_by_id=revisions_by_id,
            current_revision_by_document_id=current_revision_by_document_id,
            entities_by_type_and_id={
                (str(row.entity_type), row.entity_id): _EntityMeta(
                    label=str(row.label),
                    lifecycle_state=(
                        str(row.lifecycle_state)
                        if row.lifecycle_state is not None
                        else None
                    ),
                )
                for row in entity_rows
            },
        )

    @staticmethod
    def _matching_binding(
        fact: StoryFact, evidence: _Evidence
    ) -> DerivedSourceBinding | None:
        matches = tuple(
            binding
            for binding in evidence.bindings_by_fact_id.get(fact.id, ())
            if binding.source_chapter_revision_id == fact.source_revision_id
        )
        if not matches:
            return None
        return sorted(
            matches,
            key=lambda binding: (
                binding.validity_state not in {"current", "source_restored"},
                evidence.batches_by_id.get(binding.commit_batch_id).state
                == "reverted"
                if binding.commit_batch_id in evidence.batches_by_id
                else binding.commit_batch_id is not None,
                _utc(binding.created_at),
                str(binding.id),
            ),
        )[0]

    def _source_health(
        self, fact: StoryFact, evidence: _Evidence
    ) -> tuple[bool, bool, bool]:
        if fact.source_document_id is None and fact.source_revision_id is None:
            return (
                False,
                False,
                fact.source_start is not None or fact.source_end is not None,
            )
        document = evidence.documents_by_id.get(fact.source_document_id)
        revision = evidence.revisions_by_id.get(fact.source_revision_id)
        binding = self._matching_binding(fact, evidence)
        incomplete = (
            fact.source_document_id is None
            or fact.source_revision_id is None
            or document is None
            or revision is None
            or (revision is not None and revision.document_id != fact.source_document_id)
            or binding is None
            or (
                binding is not None
                and binding.commit_batch_id is not None
                and binding.commit_batch_id not in evidence.batches_by_id
            )
        )
        hash_mismatch = (
            binding is not None
            and revision is not None
            and binding.source_content_hash != revision.content_hash
        )
        if fact.source_start is None and fact.source_end is None:
            coordinate_invalid = False
        elif fact.source_start is None or fact.source_end is None or revision is None:
            coordinate_invalid = True
        else:
            coordinate_invalid = not (
                0
                <= fact.source_start
                < fact.source_end
                <= revision.content_length
            )
        return incomplete, hash_mismatch, coordinate_invalid

    def _source_ref(
        self, fact: StoryFact, evidence: _Evidence
    ) -> LedgerSourceReference | None:
        if fact.source_document_id is None and fact.source_revision_id is None:
            return None
        document = evidence.documents_by_id.get(fact.source_document_id)
        revision = evidence.revisions_by_id.get(fact.source_revision_id)
        binding = self._matching_binding(fact, evidence)
        coordinate_valid = (
            fact.source_start is not None
            and fact.source_end is not None
            and revision is not None
            and not self._source_health(fact, evidence)[2]
        )
        reference_valid = (
            document is not None
            and revision is not None
            and revision.document_id == document.id
        )
        return LedgerSourceReference(
            source_document_id=fact.source_document_id,
            document_title=_source_title(document) if document else None,
            document_position=document.position if document else None,
            source_revision_id=fact.source_revision_id,
            revision_number=revision.revision_number if revision else None,
            revision_is_current=(
                evidence.current_revision_by_document_id.get(document.id)
                == revision.id
                if document is not None and revision is not None
                else None
            ),
            source_content_hash=revision.content_hash if revision else None,
            source_start=fact.source_start,
            source_end=fact.source_end,
            binding_state=binding.validity_state if binding else None,
            commit_batch_id=binding.commit_batch_id if binding else None,
            evidence_available=reference_valid and coordinate_valid,
        )

    @staticmethod
    def _entity_refs(
        fact: StoryFact, evidence: _Evidence
    ) -> tuple[LedgerEntityReference, ...]:
        refs: list[LedgerEntityReference] = []
        values = (
            ("character", fact.character_id, "已删除人物"),
            (
                "character_instance",
                fact.character_instance_id,
                "已删除人物实例",
            ),
            ("relationship", fact.relationship_id, "已删除关系"),
            ("storyline", fact.storyline_id, "已删除故事线"),
            ("foreshadow", fact.foreshadow_id, "已删除伏笔"),
        )
        for entity_type, entity_id, missing_label in values:
            if entity_id is None:
                continue
            entity = evidence.entities_by_type_and_id.get(
                (entity_type, entity_id)
            )
            refs.append(
                LedgerEntityReference(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    label=entity.label if entity else missing_label,
                    lifecycle_state=entity.lifecycle_state if entity else None,
                    reference_missing=entity is None,
                )
            )
        return tuple(refs)

    @staticmethod
    def _link_view(link: StoryEventLink, fact_id: UUID) -> LedgerEventLinkView:
        outgoing = link.source_fact_id == fact_id
        return LedgerEventLinkView(
            id=link.id,
            direction="outgoing" if outgoing else "incoming",
            link_type=link.link_type,
            other_fact_id=(
                link.target_fact_id if outgoing else link.source_fact_id
            ),
            details=dict(link.details_json or {}),
            created_at=_utc(link.created_at),
        )

    @staticmethod
    def _binding_view(
        binding: DerivedSourceBinding, evidence: _Evidence
    ) -> LedgerBindingView:
        batch = evidence.batches_by_id.get(binding.commit_batch_id)
        return LedgerBindingView(
            id=binding.id,
            source_document_id=binding.source_chapter_id,
            source_revision_id=binding.source_chapter_revision_id,
            source_content_hash=binding.source_content_hash,
            validity_state=binding.validity_state,
            proposal_item_id=binding.proposal_item_id,
            commit_batch_id=binding.commit_batch_id,
            commit_batch_state=batch.state if batch else None,
            created_at=_utc(binding.created_at),
        )

    def _correction_support(
        self,
        fact: StoryFact,
        item: LedgerFactItem,
        evidence: _Evidence,
    ) -> tuple[bool, str | None]:
        if fact.schema_version != "story-fact/2":
            return False, "fact_schema_not_supported"
        if item.effective_state in {
            "superseded",
            "source_invalid",
            "batch_reverted",
        }:
            return False, "fact_not_authoritative"
        if any(
            link.link_type == "supersedes" and link.target_fact_id == fact.id
            for link in evidence.links_by_fact_id.get(fact.id, ())
        ):
            return False, "fact_already_superseded"
        has_any_source = any(
            value is not None
            for value in (
                fact.source_document_id,
                fact.source_revision_id,
                fact.source_start,
                fact.source_end,
            )
        )
        if not has_any_source:
            return True, None
        has_all_source = all(
            value is not None
            for value in (
                fact.source_document_id,
                fact.source_revision_id,
                fact.source_start,
                fact.source_end,
            )
        )
        if not has_all_source:
            return False, "source_reference_incomplete"
        incomplete, mismatch, invalid_coordinate = self._source_health(
            fact, evidence
        )
        if incomplete:
            return False, "source_reference_incomplete"
        if mismatch:
            return False, "source_hash_mismatch"
        if invalid_coordinate:
            return False, "source_coordinate_invalid"
        return True, None


__all__ = [
    "LedgerQueryFilters",
    "StoryLedgerError",
    "StoryLedgerErrorCode",
    "StoryLedgerService",
]
