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
_DOUBLE_QUOTE_CHARACTERS = frozenset({'"', "“", "”", "＂"})
_SINGLE_QUOTE_CHARACTERS = frozenset({"'", "‘", "’", "＇"})
_QUOTE_CANONICAL_TRANSLATION = str.maketrans(
    {
        "“": '"',
        "”": '"',
        "＂": '"',
        "‘": "'",
        "’": "'",
        "＇": "'",
    }
)
_NO_SUBSTANTIVE_CHANGE_SUMMARY = "未发现可验证的实质差异。"
_SUMMARY_PREVIEW_CHARACTERS = 24
_SUMMARY_CHANGE_LIMIT = 2


def _quote_family(character: str) -> str | None:
    if character in _DOUBLE_QUOTE_CHARACTERS:
        return "double"
    if character in _SINGLE_QUOTE_CHARACTERS:
        return "single"
    return None


def _quotes_are_typographically_equivalent(
    original_character: str,
    replacement_character: str,
) -> bool:
    original_family = _quote_family(original_character)
    return (
        original_family is not None
        and original_family == _quote_family(replacement_character)
    )


def _restore_original_quote_typography(
    original_text: str,
    replacement_text: str,
) -> str:
    """Remove quote-glyph-only noise without changing substantive candidate text."""

    canonical_original = original_text.translate(_QUOTE_CANONICAL_TRANSLATION)
    canonical_replacement = replacement_text.translate(_QUOTE_CANONICAL_TRANSLATION)
    if canonical_original == canonical_replacement:
        return original_text

    original_quotes = [
        (index, character, family)
        for index, character in enumerate(original_text)
        if (family := _quote_family(character)) is not None
    ]
    replacement_quotes = [
        (index, character, family)
        for index, character in enumerate(replacement_text)
        if (family := _quote_family(character)) is not None
    ]
    if [item[2] for item in original_quotes] == [
        item[2] for item in replacement_quotes
    ]:
        # Content insertions and deletions often move every later quote. Pairing
        # the unchanged family sequence by order is deterministic and linear.
        output = list(replacement_text)
        for original, replacement in zip(original_quotes, replacement_quotes):
            output[replacement[0]] = original[1]
        return "".join(output)

    def restore_aligned_quotes(original: str, replacement: str) -> str:
        return "".join(
            original_character
            if _quotes_are_typographically_equivalent(
                original_character,
                replacement_character,
            )
            else replacement_character
            for original_character, replacement_character in zip(original, replacement)
        )

    # Most model edits preserve length. This linear path also avoids ambiguous
    # alignment in long, repetitive prose while retaining every non-quote edit.
    if len(original_text) == len(replacement_text):
        return restore_aligned_quotes(original_text, replacement_text)

    # Character alignment remains bounded. Long inputs whose quote sequences
    # changed retain the ambiguous middle and only normalize exact outer context.
    if (
        len(original_text) > _CHAR_REFINEMENT_LIMIT
        or len(replacement_text) > _CHAR_REFINEMENT_LIMIT
        or len(original_text) * len(replacement_text)
        > _CHAR_REFINEMENT_PRODUCT_LIMIT
    ):
        output = list(replacement_text)
        prefix_limit = min(len(original_text), len(replacement_text))
        prefix = 0
        while (
            prefix < prefix_limit
            and canonical_original[prefix] == canonical_replacement[prefix]
        ):
            if _quotes_are_typographically_equivalent(
                original_text[prefix],
                replacement_text[prefix],
            ):
                output[prefix] = original_text[prefix]
            prefix += 1

        original_index = len(original_text) - 1
        replacement_index = len(replacement_text) - 1
        while (
            original_index >= prefix
            and replacement_index >= prefix
            and canonical_original[original_index]
            == canonical_replacement[replacement_index]
        ):
            if _quotes_are_typographically_equivalent(
                original_text[original_index],
                replacement_text[replacement_index],
            ):
                output[replacement_index] = original_text[original_index]
            original_index -= 1
            replacement_index -= 1
        return "".join(output)

    matcher = SequenceMatcher(
        None,
        canonical_original,
        canonical_replacement,
        autojunk=False,
    )
    output: list[str] = []
    for tag, left_start, left_end, right_start, right_end in matcher.get_opcodes():
        original = original_text[left_start:left_end]
        replacement = replacement_text[right_start:right_end]
        if tag == "equal":
            # Canonical equality guarantees identical text except for quote glyphs.
            output.append(original)
        elif tag == "replace" and len(original) == len(replacement):
            output.append(restore_aligned_quotes(original, replacement))
        else:
            output.append(replacement)
    return "".join(output)


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


def _summary_preview(text: str) -> str:
    compact = " ".join(text.split())
    if not compact and text:
        if text == " ":
            return "一个空格"
        if set(text) <= {"\r", "\n"}:
            return "换行"
        return "空白字符"
    if len(compact) <= _SUMMARY_PREVIEW_CHARACTERS:
        return compact
    return f"{compact[:_SUMMARY_PREVIEW_CHARACTERS]}…"


def _verified_change_summary(segments: Iterable[dict[str, str]]) -> str:
    """Describe only edits that the persisted diff can independently verify."""

    changes = [segment for segment in segments if segment["kind"] != "equal"]
    if not changes:
        return _NO_SUBSTANTIVE_CHANGE_SUMMARY

    descriptions: list[str] = []
    for segment in changes[:_SUMMARY_CHANGE_LIMIT]:
        kind = segment["kind"]
        if kind == "delete":
            descriptions.append(f"删除「{_summary_preview(segment['original_text'])}」")
        elif kind == "insert":
            descriptions.append(f"新增「{_summary_preview(segment['replacement_text'])}」")
        else:
            descriptions.append(
                "将「"
                f"{_summary_preview(segment['original_text'])}"
                "」改为「"
                f"{_summary_preview(segment['replacement_text'])}"
                "」"
            )
    remaining = len(changes) - len(descriptions)
    suffix = f"；另有 {remaining} 处" if remaining else ""
    return f"共 {len(changes)} 处实质修改：{'；'.join(descriptions)}{suffix}。"


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

    replacement_text = _restore_original_quote_typography(
        original_text,
        replacement_text,
    )
    diff_segments = build_selection_edit_diff(
        original_text,
        replacement_text,
        job_id=job_id,
    )
    # The model summary is deliberately not persisted as authoritative prose:
    # it can claim edits that are absent from the candidate. The author-facing
    # summary is reconstructed from the same immutable diff shown in review.
    short_summary = _verified_change_summary(diff_segments)

    return {
        "schema_version": 2,
        "selection_id": selection_id,
        "operation": operation,
        "replacement_text": replacement_text,
        "short_summary": short_summary,
        "replacement_character_count": len(replacement_text),
        "warnings": [],
        "diff_segments": diff_segments,
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
