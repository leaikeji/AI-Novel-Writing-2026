"""Durable, scoped evidence for deterministic private-library checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from typing import Iterable, Literal, Sequence
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..creative_data_models import LibraryCheckReport
from ..models import CandidateRevision, CreativeGenerationJob, Document, DocumentWorkingCopy
from ..novel_lifecycle import lock_active_novel
from .errors import (
    PrivateLibraryConflictError,
    PrivateLibraryNotFoundError,
    PrivateLibraryValidationError,
)
from .lexicon_contracts import LEXICON_MATCHER_VERSION, MAX_EFFECTIVE_RULES, LexiconAction
from .lexicon_matcher import LexiconRuleSource, match_lexicon
from .lexicon_service import EffectiveLexiconPolicy, resolve_effective_lexicon_policy
from .maintenance_contracts import (
    LIBRARY_CHECK_SCHEMA_VERSION,
    MAX_CHECK_HITS_PER_PAGE,
    MAX_CHECK_TEXT_CHARACTERS,
    LibraryCheckHit,
    LibraryCheckTextRef,
)


CheckDecisionKind = Literal[
    "keep_once", "skip_incomplete", "preexisting_unchanged",
]


@dataclass(frozen=True, slots=True)
class CheckReportWriteResult:
    report: LibraryCheckReport
    replayed: bool


@dataclass(frozen=True, slots=True)
class PreparedCheckScan:
    """Pure scan result carried across the read/compute/write boundary."""

    text_hash: str
    rules_hash: str
    status: str
    scanner_version: str
    scanned_rule_count: int
    omitted_rule_count: int
    visible_character_count: int
    hits: tuple[dict[str, object], ...]
    decisions: tuple[dict[str, object], ...]


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _preexisting_unchanged_hit_ids(
    *,
    baseline_markdown: str,
    source_markdown: str,
    selection_start_utf16: int,
    selection_end_utf16: int,
    rules: tuple[LexiconRuleSource, ...],
    final_hits: Sequence[LibraryCheckHit],
) -> tuple[UUID, ...]:
    """Map untouched baseline hits into the final text after one replacement."""

    baseline = match_lexicon(
        baseline_markdown,
        rules,
        max_rules=MAX_EFFECTIVE_RULES,
    )
    delta = _utf16_length(source_markdown) - _utf16_length(baseline_markdown)
    unchanged: set[tuple[object, ...]] = set()
    for hit in baseline.hits:
        if hit.action.value != "forbid":
            continue
        if hit.end_utf16 <= selection_start_utf16:
            start, end = hit.start_utf16, hit.end_utf16
        elif hit.start_utf16 >= selection_end_utf16:
            start, end = hit.start_utf16 + delta, hit.end_utf16 + delta
        else:
            continue
        unchanged.add((
            hit.entry_id, hit.asset_id, hit.asset_version_id,
            hit.matched_text, start, end,
        ))
    return tuple(
        hit.hit_id
        for hit in final_hits
        if hit.action == "forbid" and (
            hit.entry_id, hit.asset_id, hit.asset_version_id,
            hit.matched_text, hit.start_utf16, hit.end_utf16,
        ) in unchanged
    )


def _report_current(report: LibraryCheckReport) -> dict[str, object]:
    return {
        "schema_version": LIBRARY_CHECK_SCHEMA_VERSION,
        "id": str(report.id),
        "version": int(report.version),
        "status": report.status,
        "text_sha256": report.text_hash,
        "rules_sha256": report.rules_hash,
    }


def _require_document_scope(
    session: Session,
    *,
    novel_id: UUID,
    document_id: UUID,
) -> None:
    lock_active_novel(session, novel_id)
    document = session.get(Document, document_id)
    if document is None or document.novel_id != novel_id:
        raise PrivateLibraryNotFoundError("document is outside the selected novel")


def prepare_check_scan(
    *,
    text_ref: LibraryCheckTextRef,
    source_markdown: str,
    policy: EffectiveLexiconPolicy,
    unchanged_baseline: tuple[str, int, int] | None = None,
) -> PreparedCheckScan:
    """Scan immutable values without a Session or any database lock."""

    if not isinstance(source_markdown, str):
        raise PrivateLibraryValidationError("check source must be text")
    if len(source_markdown) > MAX_CHECK_TEXT_CHARACTERS:
        raise PrivateLibraryValidationError("check source exceeds the text budget")
    if text_ref.novel_id != policy.novel_id:
        raise PrivateLibraryNotFoundError("rule policy is outside the selected novel")
    if _sha256(source_markdown) != text_ref.text_sha256:
        raise PrivateLibraryConflictError(
            "library_check_text_changed",
            current={"text_hash": _sha256(source_markdown)},
        )
    rules = tuple(
        LexiconRuleSource(
            asset_id=item.asset_id,
            asset_version_id=item.asset_version_id,
            entry=item.entry,
            priority=item.position,
        )
        for item in policy.rules
    )
    matched = match_lexicon(
        source_markdown,
        rules,
        max_rules=MAX_EFFECTIVE_RULES,
    )
    typed_hits = [
        LibraryCheckHit(
            hit_id=item.hit_id,
            entry_id=item.entry_id,
            asset_id=item.asset_id,
            asset_version_id=item.asset_version_id,
            action=item.action.value,
            matched_text=item.matched_text,
            start_utf16=item.start_utf16,
            end_utf16=item.end_utf16,
            reason=item.reason,
            count=item.count,
            window=item.window,
        )
        for item in matched.hits
    ]
    hits = [item.model_dump(mode="json") for item in typed_hits]
    decisions: list[dict[str, object]] = []
    if unchanged_baseline is not None:
        baseline_markdown, selection_start_utf16, selection_end_utf16 = (
            unchanged_baseline
        )
        if (
            selection_start_utf16 < 0
            or selection_end_utf16 <= selection_start_utf16
            or selection_end_utf16 > _utf16_length(baseline_markdown)
        ):
            raise PrivateLibraryValidationError("invalid unchanged baseline range")
        now = datetime.now(timezone.utc).isoformat()
        decisions = [
            {
                "kind": "preexisting_unchanged",
                "hit_id": str(hit_id),
                "at": now,
            }
            for hit_id in _preexisting_unchanged_hit_ids(
                baseline_markdown=baseline_markdown,
                source_markdown=source_markdown,
                selection_start_utf16=selection_start_utf16,
                selection_end_utf16=selection_end_utf16,
                rules=rules,
                final_hits=typed_hits,
            )
        ]
    return PreparedCheckScan(
        text_hash=text_ref.text_sha256,
        rules_hash=policy.rules_hash,
        status=matched.status,
        scanner_version=matched.matcher_version,
        scanned_rule_count=matched.scanned_rule_count,
        omitted_rule_count=matched.omitted_rule_count,
        visible_character_count=matched.visible_character_count,
        hits=tuple(hits),
        decisions=tuple(decisions),
    )


def _require_current_source(
    session: Session,
    text_ref: LibraryCheckTextRef,
    source_id: UUID,
    unchanged_baseline: tuple[str, int, int] | None,
) -> None:
    """Re-read source after computation, while holding the novel lock."""
    if text_ref.source_kind == "candidate":
        candidate = session.scalar(
            select(CandidateRevision).where(CandidateRevision.id == source_id)
            .with_for_update().execution_options(populate_existing=True)
        )
        if (
            candidate is not None and candidate.document_id == text_ref.document_id
            and text_ref.version == 1 and candidate.content_hash == text_ref.text_sha256
        ):
            return
    else:
        working = session.scalar(
            select(DocumentWorkingCopy)
            .where(DocumentWorkingCopy.document_id == text_ref.document_id)
            .with_for_update().execution_options(populate_existing=True)
        )
        if text_ref.source_kind == "working_copy":
            if (
                source_id == text_ref.document_id and working is not None
                and int(working.draft_version) == text_ref.version
                and working.content_hash == text_ref.text_sha256
            ):
                return
        elif text_ref.source_kind == "selection_result":
            job = session.get(CreativeGenerationJob, source_id, populate_existing=True)
            base = (job.input_snapshot or {}).get("base") if job is not None else None
            if (
                working is not None and unchanged_baseline is not None
                and job is not None and job.novel_id == text_ref.novel_id
                and job.document_id == text_ref.document_id
                and job.kind == "selection_edit" and job.state == "ready"
                and int(job.attempt) == text_ref.version and isinstance(base, dict)
                and base.get("persistence_version_kind") == "draft"
                and base.get("persistence_version") == int(working.draft_version)
                and base.get("field_value_sha256") == working.content_hash
                and working.content_hash == _sha256(unchanged_baseline[0])
                and base.get("start_utf16") == unchanged_baseline[1]
                and base.get("end_utf16") == unchanged_baseline[2]
            ):
                return
    raise PrivateLibraryConflictError(
        "library_check_source_changed",
        current={"message": "检查期间正文或候选已变化，请重新检查"},
    )


def create_or_reuse_check_report(
    session: Session,
    *,
    text_ref: LibraryCheckTextRef,
    source_markdown: str,
    policy: EffectiveLexiconPolicy,
    source_id: UUID,
    unchanged_baseline: tuple[str, int, int] | None = None,
    prepared: PreparedCheckScan | None = None,
    require_current_policy: bool = True,
) -> CheckReportWriteResult:
    """Release the read transaction, scan, then guard and persist evidence.

    A caller with pending writes must prepare the scan *before* starting its
    write transaction and supply it explicitly. This preserves atomic generated
    candidate + frozen evidence writes without holding a lock during matching.
    The caller commits the final, short transaction.
    """
    if prepared is None:
        if any(len(values) for values in (session.new, session.dirty, session.deleted)):
            raise PrivateLibraryValidationError("prepare checks before starting a write transaction")
        # This transaction contains only the caller's source/policy reads. In
        # particular, release any legacy resolver lock before calling matcher.
        session.rollback()
        prepared = prepare_check_scan(
            text_ref=text_ref, source_markdown=source_markdown, policy=policy,
            unchanged_baseline=unchanged_baseline,
        )
    if (
        prepared.text_hash != text_ref.text_sha256
        or prepared.text_hash != _sha256(source_markdown)
        or prepared.rules_hash != policy.rules_hash
        or text_ref.novel_id != policy.novel_id
    ):
        raise PrivateLibraryValidationError("prepared check does not match its immutable inputs")
    _require_document_scope(
        session, novel_id=text_ref.novel_id, document_id=text_ref.document_id,
    )
    _require_current_source(session, text_ref, source_id, unchanged_baseline)
    if require_current_policy:
        current_policy = resolve_effective_lexicon_policy(session, text_ref.novel_id, lock=False)
        if current_policy.rules_hash != policy.rules_hash:
            raise PrivateLibraryConflictError(
                "library_check_required",
                current={
                    "message": "检查期间本书用词规则已变化，请重新检查",
                    "rules_sha256": current_policy.rules_hash,
                },
            )
    existing = session.scalar(
        select(LibraryCheckReport).where(
            LibraryCheckReport.novel_id == text_ref.novel_id,
            LibraryCheckReport.document_id == text_ref.document_id,
            LibraryCheckReport.source_kind == text_ref.source_kind,
            LibraryCheckReport.source_id == source_id,
            LibraryCheckReport.source_version == text_ref.version,
            LibraryCheckReport.text_hash == text_ref.text_sha256,
            LibraryCheckReport.rules_hash == policy.rules_hash,
            LibraryCheckReport.scanner_version == LEXICON_MATCHER_VERSION,
        ).with_for_update().execution_options(populate_existing=True)
    )
    if existing is not None:
        return CheckReportWriteResult(existing, True)
    report = LibraryCheckReport(
        id=uuid4(),
        novel_id=text_ref.novel_id,
        document_id=text_ref.document_id,
        source_kind=text_ref.source_kind,
        source_id=source_id,
        source_version=text_ref.version,
        text_hash=text_ref.text_sha256,
        rules_hash=policy.rules_hash,
        scanner_version=prepared.scanner_version,
        status=prepared.status,
        scanned_rule_count=prepared.scanned_rule_count,
        omitted_rule_count=prepared.omitted_rule_count,
        visible_character_count=prepared.visible_character_count,
        hits_json=list(prepared.hits),
        decisions_json=list(prepared.decisions),
        version=1,
    )
    session.add(report)
    session.flush()
    return CheckReportWriteResult(report, False)


def get_check_report(
    session: Session,
    *,
    novel_id: UUID,
    report_id: UUID,
) -> LibraryCheckReport:
    report = session.get(LibraryCheckReport, report_id)
    if report is None or report.novel_id != novel_id:
        raise PrivateLibraryNotFoundError("library check report not found")
    return report


def append_check_decisions(
    session: Session,
    *,
    novel_id: UUID,
    report_id: UUID,
    expected_version: int,
    keep_hit_ids: Sequence[UUID] = (),
    skip_incomplete: bool = False,
) -> LibraryCheckReport:
    """CAS-append author decisions without rewriting the scan evidence."""

    if isinstance(expected_version, bool) or expected_version <= 0:
        raise PrivateLibraryValidationError("expected report version must be positive")
    if len(keep_hit_ids) > MAX_CHECK_HITS_PER_PAGE:
        raise PrivateLibraryValidationError("a decision batch cannot exceed 200 hits")
    report = session.scalar(
        select(LibraryCheckReport)
        .where(
            LibraryCheckReport.id == report_id,
            LibraryCheckReport.novel_id == novel_id,
        )
        .with_for_update().execution_options(populate_existing=True)
    )
    if report is None:
        raise PrivateLibraryNotFoundError("library check report not found")
    if int(report.version) != expected_version:
        raise PrivateLibraryConflictError(
            "library_check_report_version_conflict",
            current=_report_current(report),
        )
    hit_ids = {UUID(str(item["hit_id"])) for item in report.hits_json}
    requested = [UUID(str(item)) for item in keep_hit_ids]
    if len(set(requested)) != len(requested) or not set(requested) <= hit_ids:
        raise PrivateLibraryValidationError("one or more check hits are invalid")
    if skip_incomplete and report.status != "incomplete":
        raise PrivateLibraryValidationError("only an incomplete scan may be skipped")

    prior = list(report.decisions_json or [])
    existing = {
        (item.get("kind"), item.get("hit_id"))
        for item in prior
        if isinstance(item, dict)
    }
    now = datetime.now(timezone.utc).isoformat()
    additions: list[dict[str, object]] = []
    for hit_id in requested:
        key = ("keep_once", str(hit_id))
        if key not in existing:
            additions.append({"kind": "keep_once", "hit_id": str(hit_id), "at": now})
    if skip_incomplete and ("skip_incomplete", None) not in existing:
        additions.append({"kind": "skip_incomplete", "hit_id": None, "at": now})
    if not additions:
        return report
    report.decisions_json = [*prior, *additions]
    report.version = int(report.version) + 1
    report.updated_at = datetime.now(timezone.utc)
    session.flush()
    return report


def require_application_report(
    session: Session,
    *,
    novel_id: UUID,
    document_id: UUID,
    source_kind: str,
    source_id: UUID,
    source_version: int,
    text_hash: str,
    policy: EffectiveLexiconPolicy,
    report_id: UUID | None,
    expected_version: int | None,
    allow_without_forbid: bool = False,
    keep_hit_ids: Sequence[UUID] = (),
    skip_incomplete: bool = False,
) -> LibraryCheckReport | None:
    """Validate current evidence inside the authoritative write transaction."""
    current: dict[str, object] = {"rules_sha256": policy.rules_hash}
    if source_kind == "candidate":
        current["candidate_id"] = str(source_id)
    report = session.scalar(
        select(LibraryCheckReport).where(
            LibraryCheckReport.novel_id == novel_id,
            LibraryCheckReport.document_id == document_id,
            LibraryCheckReport.source_kind == source_kind,
            LibraryCheckReport.source_id == source_id,
            LibraryCheckReport.source_version == source_version,
            LibraryCheckReport.text_hash == text_hash,
            LibraryCheckReport.rules_hash == policy.rules_hash,
            LibraryCheckReport.scanner_version == LEXICON_MATCHER_VERSION,
        ).with_for_update().execution_options(populate_existing=True)
    )
    has_forbid = any(item.entry.action is LexiconAction.FORBID for item in policy.rules)
    if report is not None:
        current["report_id"] = str(report.id)
    if report_id is not None:
        supplied = session.get(LibraryCheckReport, report_id)
        if supplied is None or supplied.novel_id != novel_id or supplied.document_id != document_id:
            raise PrivateLibraryNotFoundError("library check report is outside the selected document")
        if supplied.source_kind != source_kind or supplied.source_id != source_id:
            raise PrivateLibraryValidationError("library check report does not belong to this source")
    # Removing a historical hard rule must not strand old clients/candidates.
    # A controlled selection save still requires its exact explicit report.
    if allow_without_forbid and not has_forbid and (
        report is None or (report_id is not None and report.id != report_id)
    ):
        if keep_hit_ids or skip_incomplete:
            raise PrivateLibraryConflictError(
                "library_check_required",
                current={**current, "message": "用词规则已变化，请重新确认当前报告"},
            )
        return None
    if report is None or (report_id is not None and report.id != report_id):
        raise PrivateLibraryConflictError(
            "library_check_required",
            current={**current, "message": "本书用词规则或正文已变化，候选已保留，请重新检查"},
        )
    if expected_version is not None and int(report.version) != expected_version:
        raise PrivateLibraryConflictError(
            "library_check_report_version_conflict", current=_report_current(report),
        )
    if report_id is not None and expected_version is None:
        raise PrivateLibraryValidationError("a referenced library check requires its version")
    if report.status in {"stale", "failed"}:
        raise PrivateLibraryConflictError(
            "library_check_required", current={**current, "message": "用词检查尚未有效完成，请重新检查"},
        )
    if keep_hit_ids or skip_incomplete:
        if expected_version is None:
            raise PrivateLibraryValidationError("author decisions require the report version")
        report = append_check_decisions(
            session, novel_id=novel_id, report_id=report.id,
            expected_version=expected_version, keep_hit_ids=keep_hit_ids,
            skip_incomplete=skip_incomplete,
        )
    skipped = any(item.get("kind") == "skip_incomplete" for item in report.decisions_json or [])
    if report.status == "incomplete" and has_forbid and not skipped:
        raise PrivateLibraryConflictError(
            "library_check_required",
            current={**current, "message": "禁用规则检查未完成，请重试或明确跳过并留痕"},
        )
    unresolved = unresolved_forbid_hit_ids(report)
    if unresolved:
        raise PrivateLibraryConflictError(
            "library_check_required",
            current={**current, "message": f"仍有{len(unresolved)}处禁用表达未处理，候选已保留"},
        )
    return report


def find_application_receipt(
    session: Session, *, novel_id: UUID, document_id: UUID, application_id: UUID,
) -> dict[str, object] | None:
    """Read a prior receipt before baseline/rule checks; the novel is locked."""
    report = session.scalar(
        select(LibraryCheckReport).where(
            LibraryCheckReport.novel_id == novel_id,
            LibraryCheckReport.document_id == document_id,
            LibraryCheckReport.decisions_json.contains([
                {"kind": "application", "application_id": str(application_id)},
            ]),
        ).with_for_update().execution_options(populate_existing=True)
    )
    if report is None:
        return None
    return next((
        dict(item) for item in report.decisions_json or []
        if item.get("kind") == "application" and item.get("application_id") == str(application_id)
    ), None)


def append_application_receipt(
    report: LibraryCheckReport,
    *,
    application_id: UUID,
    input_sha256: str,
    output_sha256: str,
    request_sha256: str,
    revision_id: UUID | None = None,
    draft_version: int | None = None,
) -> dict[str, object]:
    """Append without commit: receipt and authoritative text succeed together."""
    receipt: dict[str, object] = {
        "kind": "application", "application_id": str(application_id),
        "report_id": str(report.id), "input_sha256": input_sha256,
        "output_sha256": output_sha256, "request_sha256": request_sha256,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    if revision_id is not None:
        receipt["revision_id"] = str(revision_id)
    if draft_version is not None:
        receipt["draft_version"] = draft_version
    report.decisions_json = [*(report.decisions_json or []), receipt]
    report.version = int(report.version) + 1
    report.updated_at = datetime.now(timezone.utc)
    return receipt


def unresolved_forbid_hit_ids(report: LibraryCheckReport) -> tuple[UUID, ...]:
    kept = {
        UUID(str(item["hit_id"]))
        for item in (report.decisions_json or [])
        if isinstance(item, dict)
        and item.get("kind") in {"keep_once", "preexisting_unchanged"}
        and item.get("hit_id") is not None
    }
    return tuple(
        UUID(str(item["hit_id"]))
        for item in (report.hits_json or [])
        if item.get("action") == "forbid" and UUID(str(item["hit_id"])) not in kept
    )


def check_report_payload(
    report: LibraryCheckReport,
    *,
    offset: int = 0,
    limit: int = MAX_CHECK_HITS_PER_PAGE,
) -> dict[str, object]:
    if isinstance(offset, bool) or offset < 0:
        raise PrivateLibraryValidationError("offset must be non-negative")
    if isinstance(limit, bool) or not 1 <= limit <= MAX_CHECK_HITS_PER_PAGE:
        raise PrivateLibraryValidationError("invalid check report page size")
    hits = list(report.hits_json or [])
    page = hits[offset:offset + limit]
    return {
        **_report_current(report),
        "novel_id": str(report.novel_id),
        "document_id": str(report.document_id),
        "source_kind": report.source_kind,
        "source_id": str(report.source_id) if report.source_id else None,
        "source_version": int(report.source_version),
        "scanner_version": report.scanner_version,
        "scanned_rule_count": int(report.scanned_rule_count),
        "omitted_rule_count": int(report.omitted_rule_count),
        "visible_character_count": int(report.visible_character_count),
        "hits": page,
        "decisions": list(report.decisions_json or []),
        "offset": offset,
        "limit": limit,
        "total_hits": len(hits),
        "has_more": offset + len(page) < len(hits),
        "unresolved_forbid_hit_ids": [
            str(item) for item in unresolved_forbid_hit_ids(report)
        ],
    }


__all__ = [
    "CheckReportWriteResult",
    "PreparedCheckScan",
    "append_application_receipt",
    "append_check_decisions",
    "check_report_payload",
    "create_or_reuse_check_report",
    "get_check_report",
    "find_application_receipt",
    "prepare_check_scan",
    "require_application_report",
    "unresolved_forbid_hit_ids",
]
