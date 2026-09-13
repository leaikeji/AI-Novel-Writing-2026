"""Rebuild a reviewed body edit from the persisted selection job, never UI text."""

from __future__ import annotations

import hashlib
from typing import Sequence
from uuid import UUID

from sqlalchemy.orm import Session

from ..models import CreativeGenerationJob, Document, DocumentWorkingCopy
from .errors import (
    PrivateLibraryConflictError,
    PrivateLibraryNotFoundError,
    PrivateLibraryValidationError,
)


def _changed(message: str, **current: object) -> PrivateLibraryConflictError:
    return PrivateLibraryConflictError(
        "library_check_source_changed", current={"message": message, **current}
    )


def _selection_replacement(job: CreativeGenerationJob, accepted: Sequence[str] | None) -> str:
    if accepted is None:
        return str(job.output_text or "")
    if (
        len(accepted) > 200
        or len(set(accepted)) != len(accepted)
        or any(not isinstance(value, str) or not value or len(value) > 200 for value in accepted)
    ):
        raise PrivateLibraryValidationError("selection application decisions are invalid")
    segments = (job.output_json or {}).get("diff_segments")
    if not isinstance(segments, list):
        raise _changed("选区候选的差异证据不可用，请重新打开候选")
    known: set[str] = set()
    for item in segments:
        if not isinstance(item, dict):
            raise _changed("选区候选的差异证据无效")
        segment_id = item.get("segment_id")
        if not isinstance(segment_id, str) or not segment_id or segment_id in known:
            raise _changed("选区候选的差异标识无效")
        known.add(segment_id)
    changed_ids = {
        item["segment_id"] for item in segments if item.get("kind") != "equal"
    }
    accepted_ids = set(accepted)
    if not accepted_ids <= changed_ids:
        raise PrivateLibraryValidationError("selection application contains unknown decisions")
    parts: list[str] = []
    for item in segments:
        kind, selected = item.get("kind"), item["segment_id"] in accepted_ids
        if kind == "equal":
            value = item.get("text")
        elif kind == "delete":
            value = "" if selected else item.get("original_text")
        elif kind == "insert":
            value = item.get("replacement_text") if selected else ""
        elif kind == "replace":
            value = item.get("replacement_text") if selected else item.get("original_text")
        else:
            raise _changed("选区候选的差异类型无效")
        if not isinstance(value, str):
            raise _changed("选区候选的差异正文无效")
        parts.append(value)
    return "".join(parts)


def resolve_selection_application_source(
    session: Session,
    novel_id: UUID,
    document_id: UUID,
    job_id: UUID,
    attempt: int,
    replacement_sha256: str,
    accepted_segment_ids: Sequence[str] | None,
) -> tuple[str, tuple[str, int, int]]:
    """Resolve exact final chapter and untouched baseline under caller's scope.

    This function acquires no locks and owns no transaction. The check endpoint
    uses it for a read snapshot; the final save uses it after locking the novel
    and working copy, so the same composition rules protect both paths.
    """
    document = session.get(Document, document_id)
    if document is None or document.novel_id != novel_id:
        raise PrivateLibraryNotFoundError("document is outside the selected novel")
    job = session.get(CreativeGenerationJob, job_id)
    if (
        job is None or job.kind != "selection_edit" or job.state != "ready"
        or job.novel_id != novel_id or job.document_id != document_id
    ):
        raise PrivateLibraryNotFoundError("selection result is outside the selected document")
    target = (job.input_snapshot or {}).get("target")
    if (
        not isinstance(target, dict)
        or target.get("field_id") != "chapter.body"
        or target.get("persistence") != "autosave"
        or str(target.get("novel_id")) != str(novel_id)
        or str(target.get("document_id")) != str(document_id)
    ):
        raise PrivateLibraryValidationError("selection result is not a controlled chapter body edit")
    replacement = _selection_replacement(job, accepted_segment_ids)
    replacement_hash = hashlib.sha256(replacement.encode("utf-8")).hexdigest()
    if int(job.attempt) != attempt or replacement_hash != replacement_sha256:
        raise _changed(
            "选区候选或审阅决定已变化，请重新检查",
            source_version=int(job.attempt), text_hash=replacement_hash,
        )
    base = (job.input_snapshot or {}).get("base")
    working = session.get(DocumentWorkingCopy, document_id)
    if (
        not isinstance(base, dict) or working is None
        or base.get("persistence_version_kind") != "draft"
        or base.get("persistence_version") != int(working.draft_version)
        or base.get("field_value_sha256") != working.content_hash
        or hashlib.sha256(working.content_markdown.encode("utf-8")).hexdigest() != working.content_hash
    ):
        raise _changed(
            "选区应用的正文基线已变化，候选仍保留",
            source_version=int(working.draft_version) if working else None,
            text_hash=working.content_hash if working else None,
        )
    start, end = base.get("start_utf16"), base.get("end_utf16")
    raw = working.content_markdown.encode("utf-16-le")
    if (
        type(start) is not int or type(end) is not int
        or start < 0 or end <= start or end * 2 > len(raw)
    ):
        raise _changed("选区应用的正文范围无效")
    try:
        before, selected, after = (
            raw[:start * 2].decode("utf-16-le"),
            raw[start * 2:end * 2].decode("utf-16-le"),
            raw[end * 2:].decode("utf-16-le"),
        )
    except UnicodeDecodeError as error:
        raise _changed("选区应用的正文范围无效") from error
    if selected != base.get("selection_text"):
        raise _changed("选区应用的原文已变化")
    return before + replacement + after, (working.content_markdown, start, end)


__all__ = ["resolve_selection_application_source"]
