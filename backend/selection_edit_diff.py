"""Deterministic, bounded unified diff for explicit selection-edit jobs."""

from __future__ import annotations

import hashlib
from difflib import SequenceMatcher
from typing import Any, Iterable


class SelectionEditDiffError(RuntimeError):
    """Raised when a structured diff cannot reconstruct both source texts."""


SELECTION_EDIT_REPLACEMENT_MAX_CHARACTERS = 24_000
_MAX_UNIT_CHARACTERS = 256
_MAX_SEQUENCE_UNITS = 512
_CHAR_REFINEMENT_LIMIT = 1_024
_CHAR_REFINEMENT_PRODUCT_LIMIT = 250_000
_BOUNDARY_CHARACTERS = frozenset("。！？!?；;.\n\r")


def _bounded_text_units(text: str) -> list[str]:
    """Split at prose boundaries without creating an unbounded token list."""

    if not text:
        return []
    prose_units: list[str] = []
    start = 0
    for index, character in enumerate(text, start=1):
        length = index - start
        if length >= _MAX_UNIT_CHARACTERS or character in _BOUNDARY_CHARACTERS:
            prose_units.append(text[start:index])
            start = index
    if start < len(text):
        prose_units.append(text[start:])
    if len(prose_units) <= _MAX_SEQUENCE_UNITS:
        return prose_units

    # Pathological punctuation-heavy input can otherwise create thousands of
    # SequenceMatcher tokens. Coalesce only after the sentence/paragraph split,
    # retaining exact text while keeping the outer alignment budget bounded.
    target_size = max(1, (len(text) + _MAX_SEQUENCE_UNITS - 1) // _MAX_SEQUENCE_UNITS)
    units: list[str] = []
    buffer: list[str] = []
    buffer_length = 0
    for unit in prose_units:
        buffer.append(unit)
        buffer_length += len(unit)
        if buffer_length >= target_size:
            units.append("".join(buffer))
            buffer = []
            buffer_length = 0
    if buffer:
        units.append("".join(buffer))
    return units


def _raw_segment(
    kind: str,
    *,
    text: str = "",
    original_text: str = "",
    replacement_text: str = "",
) -> dict[str, str]:
    if kind == "equal":
        return {"kind": kind, "text": text}
    if kind == "delete":
        return {"kind": kind, "original_text": original_text}
    if kind == "insert":
        return {"kind": kind, "replacement_text": replacement_text}
    if kind == "replace":
        return {
            "kind": kind,
            "original_text": original_text,
            "replacement_text": replacement_text,
        }
    raise SelectionEditDiffError(f"unsupported diff segment kind: {kind}")


def _character_segments(original_text: str, replacement_text: str) -> list[dict[str, str]]:
    if (
        len(original_text) > _CHAR_REFINEMENT_LIMIT
        or len(replacement_text) > _CHAR_REFINEMENT_LIMIT
        or len(original_text) * len(replacement_text) > _CHAR_REFINEMENT_PRODUCT_LIMIT
    ):
        return [
            _raw_segment(
                "replace",
                original_text=original_text,
                replacement_text=replacement_text,
            )
        ]
    matcher = SequenceMatcher(
        None,
        original_text,
        replacement_text,
        autojunk=True,
    )
    output: list[dict[str, str]] = []
    for tag, left_start, left_end, right_start, right_end in matcher.get_opcodes():
        original = original_text[left_start:left_end]
        replacement = replacement_text[right_start:right_end]
        if tag == "equal":
            output.append(_raw_segment("equal", text=original))
        elif tag == "delete":
            output.append(_raw_segment("delete", original_text=original))
        elif tag == "insert":
            output.append(_raw_segment("insert", replacement_text=replacement))
        else:
            output.append(
                _raw_segment(
                    "replace",
                    original_text=original,
                    replacement_text=replacement,
                )
            )
    return output


def _merge_adjacent_segments(segments: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    field_by_kind = {
        "equal": "text",
        "delete": "original_text",
        "insert": "replacement_text",
    }
    for segment in segments:
        kind = segment["kind"]
        if output and output[-1]["kind"] == kind and kind in field_by_kind:
            field = field_by_kind[kind]
            output[-1][field] += segment[field]
        else:
            output.append(dict(segment))
    return output


def _segment_id(job_id: str, position: int, segment: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for value in (
        job_id,
        str(position),
        segment["kind"],
        segment.get("text", ""),
        segment.get("original_text", ""),
        segment.get("replacement_text", ""),
    ):
        digest.update(value.encode("utf-8"))
        digest.update(b"\x00")
    return f"seg-{position:04d}-{digest.hexdigest()[:16]}"


def reconstruct_selection_edit_diff(
    segments: Iterable[dict[str, Any]],
    *,
    candidate: bool,
) -> str:
    """Reconstruct the source or candidate side of one frozen result."""

    output: list[str] = []
    for segment in segments:
        kind = segment.get("kind")
        if kind == "equal":
            value = segment.get("text")
        elif kind == "delete":
            value = "" if candidate else segment.get("original_text")
        elif kind == "insert":
            value = segment.get("replacement_text") if candidate else ""
        elif kind == "replace":
            value = (
                segment.get("replacement_text")
                if candidate
                else segment.get("original_text")
            )
        else:
            raise SelectionEditDiffError("diff segment kind is invalid")
        if not isinstance(value, str):
            raise SelectionEditDiffError("diff segment text is invalid")
        output.append(value)
    return "".join(output)


def build_selection_edit_diff(
    original_text: str,
    replacement_text: str,
    *,
    job_id: str,
) -> list[dict[str, str]]:
    """Build a stable diff that is safe to persist and independently verify."""

    if not job_id.strip():
        raise SelectionEditDiffError("job_id is required for stable segment ids")
    raw_segments: list[dict[str, str]]
    if original_text == replacement_text:
        raw_segments = (
            [_raw_segment("equal", text=original_text)] if original_text else []
        )
    else:
        original_units = _bounded_text_units(original_text)
        replacement_units = _bounded_text_units(replacement_text)
        matcher = SequenceMatcher(
            None,
            original_units,
            replacement_units,
            autojunk=True,
        )
        raw_segments = []
        for tag, left_start, left_end, right_start, right_end in matcher.get_opcodes():
            original = "".join(original_units[left_start:left_end])
            replacement = "".join(replacement_units[right_start:right_end])
            if tag == "equal":
                raw_segments.append(_raw_segment("equal", text=original))
            elif tag == "delete":
                raw_segments.append(_raw_segment("delete", original_text=original))
            elif tag == "insert":
                raw_segments.append(_raw_segment("insert", replacement_text=replacement))
            else:
                raw_segments.extend(_character_segments(original, replacement))
        raw_segments = _merge_adjacent_segments(raw_segments)

    segments = [
        {"segment_id": _segment_id(job_id, index, segment), **segment}
        for index, segment in enumerate(raw_segments)
    ]
    if reconstruct_selection_edit_diff(segments, candidate=False) != original_text:
        raise SelectionEditDiffError("diff cannot reconstruct original selection")
    if reconstruct_selection_edit_diff(segments, candidate=True) != replacement_text:
        raise SelectionEditDiffError("diff cannot reconstruct replacement candidate")
    return segments


def build_selection_edit_result(
    *,
    job_id: str,
    selection_id: str,
    operation: str,
    original_text: str,
    replacement_text: str,
    short_summary: str,
) -> dict[str, Any]:
    """Add project-owned metadata and diff to a normalized model result."""

    return {
        "schema_version": 2,
        "selection_id": selection_id,
        "operation": operation,
        "replacement_text": replacement_text,
        "short_summary": short_summary,
        "replacement_character_count": len(replacement_text),
        "warnings": [],
        "diff_segments": build_selection_edit_diff(
            original_text,
            replacement_text,
            job_id=job_id,
        ),
    }


def validate_selection_edit_result(
    result: dict[str, Any],
    *,
    expected_selection_id: str,
    expected_operation: str,
    expected_original_text: str,
) -> None:
    """Fail closed when a persisted result drifts from the frozen V2 DTO."""

    expected_keys = {
        "schema_version",
        "selection_id",
        "operation",
        "replacement_text",
        "short_summary",
        "replacement_character_count",
        "warnings",
        "diff_segments",
    }
    if set(result) != expected_keys:
        raise SelectionEditDiffError("selection edit result fields are invalid")
    if result.get("schema_version") != 2:
        raise SelectionEditDiffError("selection edit result schema is invalid")
    if result.get("selection_id") != expected_selection_id:
        raise SelectionEditDiffError("selection edit result selection_id mismatches")
    if result.get("operation") != expected_operation:
        raise SelectionEditDiffError("selection edit result operation mismatches")
    replacement_text = result.get("replacement_text")
    short_summary = result.get("short_summary")
    warnings = result.get("warnings")
    segments = result.get("diff_segments")
    if (
        not isinstance(replacement_text, str)
        or not replacement_text.strip()
        or len(replacement_text) > SELECTION_EDIT_REPLACEMENT_MAX_CHARACTERS
    ):
        raise SelectionEditDiffError("selection edit replacement is invalid")
    if (
        not isinstance(short_summary, str)
        or not short_summary.strip()
        or len(short_summary) > 240
    ):
        raise SelectionEditDiffError("selection edit summary is invalid")
    try:
        replacement_text.encode("utf-8")
        short_summary.encode("utf-8")
    except UnicodeEncodeError as error:
        raise SelectionEditDiffError("selection edit result Unicode is invalid") from error
    if any(
        ord(character) < 32 and character not in "\n\r\t"
        for character in replacement_text + short_summary
    ):
        raise SelectionEditDiffError("selection edit result control character is invalid")
    if result.get("replacement_character_count") != len(replacement_text):
        raise SelectionEditDiffError("selection edit character count is invalid")
    if (
        not isinstance(warnings, list)
        or len(warnings) > 20
        or any(not isinstance(item, str) or len(item) > 240 for item in warnings)
    ):
        raise SelectionEditDiffError("selection edit warnings are invalid")
    if not isinstance(segments, list):
        raise SelectionEditDiffError("selection edit diff_segments are invalid")
    segment_fields = {
        "equal": {"segment_id", "kind", "text"},
        "delete": {"segment_id", "kind", "original_text"},
        "insert": {"segment_id", "kind", "replacement_text"},
        "replace": {
            "segment_id",
            "kind",
            "original_text",
            "replacement_text",
        },
    }
    seen_ids: set[str] = set()
    for segment in segments:
        if not isinstance(segment, dict):
            raise SelectionEditDiffError("selection edit diff segment is invalid")
        kind = segment.get("kind")
        if kind not in segment_fields or set(segment) != segment_fields[kind]:
            raise SelectionEditDiffError("selection edit diff segment fields are invalid")
        segment_id = segment.get("segment_id")
        if (
            not isinstance(segment_id, str)
            or not segment_id
            or segment_id in seen_ids
        ):
            raise SelectionEditDiffError("selection edit segment_id is invalid")
        text_fields = set(segment) - {"segment_id", "kind"}
        if any(
            not isinstance(segment.get(field), str) or not segment[field]
            for field in text_fields
        ):
            raise SelectionEditDiffError("selection edit diff segment text is invalid")
        if (
            kind == "replace"
            and segment["original_text"] == segment["replacement_text"]
        ):
            raise SelectionEditDiffError("selection edit diff contains a fake replacement")
        seen_ids.add(segment_id)
    if reconstruct_selection_edit_diff(segments, candidate=False) != expected_original_text:
        raise SelectionEditDiffError("selection edit diff original reconstruction failed")
    if reconstruct_selection_edit_diff(segments, candidate=True) != replacement_text:
        raise SelectionEditDiffError("selection edit diff candidate reconstruction failed")
