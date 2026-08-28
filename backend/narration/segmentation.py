"""Deterministic Markdown/plain-text segmentation for T3 narration scripts.

This work package materializes only source-bound metadata.  Speaker attribution,
scene inference, casting, cloud assistance, review, and persistence deliberately
remain outside this module and are joined by the T3-GATE owner.
"""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass, replace
from enum import Enum
from typing import Final, Iterable, Sequence
from uuid import RFC_4122, UUID

from .script_contracts import (
    SOURCE_BOUND_SEGMENT_KINDS,
    ScriptContractError,
    SegmentKind,
    SourceBlockKind,
    Utf16Range,
    derive_segment_id,
    derive_source_block_key,
    text_sha256,
    utf16_length,
    utf16_slice,
)
from .source_mapping import SourceIndexMap, validate_complete_utf16_partition


class SegmentationError(ScriptContractError):
    """Raised when source cannot be segmented without violating T3-A."""


class SourceFormat(str, Enum):
    MARKDOWN = "markdown"
    PLAIN_TEXT = "plain_text"


@dataclass(frozen=True, slots=True)
class MaterializedSegment:
    """T3-B-owned subset of the frozen ``SegmentContract`` fields."""

    segment_id: UUID
    ordinal: int
    segment_kind: SegmentKind
    source_block_kind: SourceBlockKind
    paragraph_ordinal: int
    segment_ordinal_in_block: int
    source_block_key: str
    source_block_hash: str
    source_range_utf16: Utf16Range
    source_text: str
    spoken_text: str
    local_hash: str
    anchor_before_hash: str | None
    anchor_after_hash: str | None


@dataclass(frozen=True, slots=True)
class MaterializedSourceBlock:
    paragraph_ordinal: int
    block_kind: SourceBlockKind
    source_block_key: str
    source_block_hash: str
    source_range_utf16: Utf16Range
    source_text: str
    anchor_before_hash: str | None
    anchor_after_hash: str | None
    segments: tuple[MaterializedSegment, ...]


@dataclass(frozen=True, slots=True)
class SegmentationResult:
    script_version_id: UUID
    source_format: SourceFormat
    source_content_hash: str
    source_length_utf16: int
    blocks: tuple[MaterializedSourceBlock, ...]
    segments: tuple[MaterializedSegment, ...]


@dataclass(frozen=True, slots=True)
class _Line:
    start: int
    end: int
    text: str


@dataclass(frozen=True, slots=True)
class _CoreBlock:
    start: int
    end: int
    block_kind: SourceBlockKind


@dataclass(frozen=True, slots=True)
class _RawBlock:
    start: int
    end: int
    block_kind: SourceBlockKind


@dataclass(frozen=True, slots=True)
class _RawUnit:
    start: int
    end: int
    kind: SegmentKind


_ATX_HEADING: Final = re.compile(r"^[ \t]{0,3}#{1,6}(?:[ \t]+|$)")
_SETEXT_UNDERLINE: Final = re.compile(r"^[ \t]{0,3}(?:=+|-+)[ \t]*$")
_FENCE_OPEN: Final = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")
_THEMATIC_BREAK: Final = re.compile(
    r"^[ \t]{0,3}(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})$"
)
_SEMANTIC_PREFIXES: Final[tuple[tuple[SourceBlockKind, re.Pattern[str]], ...]] = (
    (
        SourceBlockKind.MESSAGE,
        re.compile(r"^(?:\[|\u3010)?(?:\u77ed\u4fe1|\u6d88\u606f|\u804a\u5929\u8bb0\u5f55|\u5fae\u4fe1)(?:\]|\u3011)?\s*[:\uff1a]?"),
    ),
    (
        SourceBlockKind.LETTER,
        re.compile(r"^(?:\[|\u3010)?(?:\u4fe1\u4ef6|\u4e66\u4fe1|\u6765\u4fe1)(?:\]|\u3011)?\s*[:\uff1a]?"),
    ),
    (
        SourceBlockKind.BROADCAST,
        re.compile(r"^(?:\[|\u3010)?(?:\u5e7f\u64ad|\u64ad\u62a5|\u516c\u544a)(?:\]|\u3011)?\s*[:\uff1a]?"),
    ),
    (
        SourceBlockKind.PHONE,
        re.compile(r"^(?:\[|\u3010)?(?:\u7535\u8bdd|\u901a\u8bdd|\u6765\u7535)(?:\]|\u3011)?\s*[:\uff1a]?"),
    ),
)
_SEMANTIC_TAG: Final = re.compile(
    r"^(?:\[|\u3010)(?:\u77ed\u4fe1|\u6d88\u606f|\u804a\u5929\u8bb0\u5f55|\u5fae\u4fe1|\u4fe1\u4ef6|\u4e66\u4fe1|\u6765\u4fe1|\u5e7f\u64ad|\u64ad\u62a5|\u516c\u544a|\u7535\u8bdd|\u901a\u8bdd|\u6765\u7535|\u5185\u5fc3|\u5185\u5fc3\u72ec\u767d)(?:\]|\u3011)\s*[:\uff1a]?"
)
_INNER_BLOCK_PREFIX: Final = re.compile(
    r"^(?:\[|\u3010)(?:\u5185\u5fc3|\u5185\u5fc3\u72ec\u767d)(?:\]|\u3011)\s*[:\uff1a]?"
)
_INNER_CUE: Final = re.compile(
    r"(?:\u5fc3\u60f3|\u6697\u60f3|\u5fc3\u9053|\u6697\u9053|\u9ed8\u5ff5|\u601d\u5fd6)\s*[:\uff1a]?\s*$"
)
_NO_READ_TOKEN: Final = re.compile(
    r"<!--\s*(?P<html_end>/)?tts:skip\s*-->|"
    r"(?P<tag_start><noread(?:\s[^>]*)?>)|(?P<tag_end></noread\s*>)|"
    r"(?P<cn_start>\[\u4e0d\u6717\u8bfb\])|(?P<cn_end>\[/\u4e0d\u6717\u8bfb\])",
    re.IGNORECASE,
)
_HTML_COMMENT: Final = re.compile(r"<!--.*?-->", re.DOTALL)
_HTML_TAG: Final = re.compile(r"</?[A-Za-z][^>]*>")
_IMAGE: Final = re.compile(r"!\[([^\]\n]*)\]\([^\)\n]*\)")
_LINK: Final = re.compile(r"\[([^\]\n]+)\]\([^\)\n]*\)")
_LINK_DESTINATION: Final = re.compile(r"!?\[[^\]\n]*\]\(([^\)\n]*)\)")
_AUTOLINK: Final = re.compile(r"<(?:https?://|mailto:)[^>]+>", re.IGNORECASE)
_INLINE_CODE: Final = re.compile(r"(`+)(.*?)\1", re.DOTALL)
_FENCE_LINE: Final = re.compile(r"^[ \t]{0,3}(?:`{3,}|~{3,}).*$", re.MULTILINE)
_THEMATIC_LINE: Final = re.compile(
    r"^[ \t]{0,3}(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})[ \t]*$",
    re.MULTILINE,
)
_HEADING_PREFIX: Final = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+", re.MULTILINE)
_HEADING_SUFFIX: Final = re.compile(r"[ \t]+#+[ \t]*(?=$)", re.MULTILINE)
_SETEXT_LINE: Final = re.compile(r"^[ \t]{0,3}(?:=+|-+)[ \t]*$", re.MULTILINE)
_BLOCKQUOTE_PREFIX: Final = re.compile(r"^[ \t]{0,3}>[ \t]?", re.MULTILINE)
_LIST_PREFIX: Final = re.compile(
    r"^[ \t]{0,3}(?:[-+*]|\d{1,9}[.)])[ \t]+", re.MULTILINE
)
_MARKDOWN_ESCAPE: Final = re.compile(r"\\([\\`*_{}\[\]()#+.!>~\-])")
_WHITESPACE: Final = re.compile(r"\s+")
_TERMINALS: Final = frozenset("。！？!?;\uff1b….")
_TRAILING_CLOSERS: Final = frozenset("”’」』）)]】》〉〕〗〙〛")
_QUOTE_PAIRS: Final[dict[str, str]] = {
    "“": "”",
    "「": "」",
    "『": "』",
    "‘": "’",
    '"': '"',
}
_BLOCK_TO_SEGMENT: Final[dict[SourceBlockKind, SegmentKind]] = {
    SourceBlockKind.MESSAGE: SegmentKind.MESSAGE,
    SourceBlockKind.LETTER: SegmentKind.LETTER,
    SourceBlockKind.BROADCAST: SegmentKind.BROADCAST,
    SourceBlockKind.PHONE: SegmentKind.PHONE,
}


def _require_script_version_id(value: object) -> UUID:
    if (
        type(value) is not UUID
        or value.variant != RFC_4122
        or value.version not in {1, 2, 3, 4, 5}
    ):
        raise SegmentationError("script_version_id must be an RFC-4122 UUID v1-v5")
    return value


def _lines(source_text: str) -> list[_Line]:
    lines: list[_Line] = []
    cursor = 0
    for value in source_text.splitlines(keepends=True):
        end = cursor + len(value)
        lines.append(_Line(cursor, end, value))
        cursor = end
    if cursor < len(source_text):
        lines.append(_Line(cursor, len(source_text), source_text[cursor:]))
    return lines


def _line_body(value: str) -> str:
    return value.rstrip("\r\n")


def _is_blank(value: str) -> bool:
    return not _line_body(value).strip(" \t")


def _classify_core(text: str, *, heading: bool = False) -> SourceBlockKind:
    if heading:
        return SourceBlockKind.HEADING
    probe = text
    probe = _BLOCKQUOTE_PREFIX.sub("", probe)
    probe = _LIST_PREFIX.sub("", probe)
    probe = _HEADING_PREFIX.sub("", probe)
    probe = probe.lstrip(" \t\r\n*_~`")
    for block_kind, pattern in _SEMANTIC_PREFIXES:
        if pattern.match(probe):
            return block_kind
    return SourceBlockKind.PARAGRAPH


def _core_blocks(source_text: str, source_format: SourceFormat) -> list[_CoreBlock]:
    lines = _lines(source_text)
    if source_format is SourceFormat.PLAIN_TEXT:
        cores: list[_CoreBlock] = []
        start: int | None = None
        end = 0
        for line in lines:
            if _is_blank(line.text):
                if start is not None:
                    cores.append(_CoreBlock(start, end, SourceBlockKind.PARAGRAPH))
                    start = None
                continue
            if start is None:
                start = line.start
            end = line.end
        if start is not None:
            cores.append(_CoreBlock(start, end, SourceBlockKind.PARAGRAPH))
        return cores

    cores = []
    normal_start: int | None = None
    normal_end = 0

    def flush_normal() -> None:
        nonlocal normal_start, normal_end
        if normal_start is not None:
            text = source_text[normal_start:normal_end]
            cores.append(
                _CoreBlock(normal_start, normal_end, _classify_core(text))
            )
            normal_start = None

    index = 0
    while index < len(lines):
        line = lines[index]
        body = _line_body(line.text)
        if _is_blank(line.text):
            flush_normal()
            index += 1
            continue

        fence = _FENCE_OPEN.match(body)
        if fence is not None:
            flush_normal()
            marker = fence.group(1)[0]
            minimum = len(fence.group(1))
            end = line.end
            index += 1
            while index < len(lines):
                candidate = _line_body(lines[index].text)
                end = lines[index].end
                index += 1
                close = re.match(r"^[ \t]{0,3}(`+|~+)[ \t]*$", candidate)
                if (
                    close is not None
                    and close.group(1)[0] == marker
                    and len(close.group(1)) >= minimum
                ):
                    break
            text = source_text[line.start:end]
            cores.append(
                _CoreBlock(line.start, end, _classify_core(text))
            )
            continue

        if _ATX_HEADING.match(body):
            flush_normal()
            cores.append(
                _CoreBlock(line.start, line.end, SourceBlockKind.HEADING)
            )
            index += 1
            continue

        if (
            index + 1 < len(lines)
            and not _is_blank(lines[index + 1].text)
            and _SETEXT_UNDERLINE.match(_line_body(lines[index + 1].text))
        ):
            flush_normal()
            end = lines[index + 1].end
            cores.append(_CoreBlock(line.start, end, SourceBlockKind.HEADING))
            index += 2
            continue

        if _THEMATIC_BREAK.match(body):
            flush_normal()
            cores.append(_CoreBlock(line.start, line.end, SourceBlockKind.PARAGRAPH))
            index += 1
            continue

        if normal_start is None:
            normal_start = line.start
        normal_end = line.end
        index += 1

    flush_normal()
    return cores


def _validate_no_read_markers(source_text: str) -> None:
    stack: list[str] = []
    for match in _NO_READ_TOKEN.finditer(source_text):
        token: str
        is_end: bool
        if match.group("html_end") is not None:
            token, is_end = "html", True
        elif match.group(0).lower().lstrip().startswith("<!--"):
            token, is_end = "html", False
        elif match.group("tag_start") is not None:
            token, is_end = "tag", False
        elif match.group("tag_end") is not None:
            token, is_end = "tag", True
        elif match.group("cn_start") is not None:
            token, is_end = "cn", False
        else:
            token, is_end = "cn", True
        if is_end:
            if not stack or stack[-1] != token:
                raise SegmentationError("unbalanced or crossed no-read marker")
            stack.pop()
        else:
            if stack:
                raise SegmentationError("nested no-read markers are not supported")
            stack.append(token)
    if stack:
        raise SegmentationError("unclosed no-read marker")


def _validate_html_comments(source_text: str) -> None:
    cursor = 0
    while True:
        start = source_text.find("<!--", cursor)
        if start < 0:
            return
        end = source_text.find("-->", start + 4)
        if end < 0:
            raise SegmentationError("unclosed Markdown HTML comment")
        cursor = end + 3


def _no_read_ranges(text: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    start: int | None = None
    for match in _NO_READ_TOKEN.finditer(text):
        is_end = (
            match.group("html_end") is not None
            or match.group("tag_end") is not None
            or match.group("cn_end") is not None
        )
        if is_end:
            if start is not None:
                ranges.append((start, match.end()))
                start = None
        else:
            start = match.start()
    return ranges


def _unspoken_ranges(text: str) -> list[tuple[int, int]]:
    ranges = _no_read_ranges(text)
    ranges.extend((match.start(), match.end()) for match in _HTML_COMMENT.finditer(text))
    return sorted(ranges)


def _mask_analysis_text(text: str, source_format: SourceFormat) -> str:
    characters = list(text)

    def mask(start: int, end: int) -> None:
        for index in range(start, end):
            if characters[index] not in "\r\n":
                characters[index] = " "

    for start, end in _unspoken_ranges(text):
        mask(start, end)
    for match in _HTML_TAG.finditer(text):
        mask(match.start(), match.end())
    for match in _LINK_DESTINATION.finditer(text):
        label_end = text.rfind("](", match.start(), match.end())
        mask(label_end, match.end())
    for match in _AUTOLINK.finditer(text):
        mask(match.start(), match.end())
    if source_format is SourceFormat.MARKDOWN:
        for index, character in enumerate(characters):
            if character in "*_~`":
                characters[index] = " "
    return "".join(characters)


def _remove_no_read(text: str) -> str:
    ranges = _no_read_ranges(text)
    if not ranges:
        return text
    pieces: list[str] = []
    cursor = 0
    for start, end in ranges:
        pieces.append(text[cursor:start])
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces)


def spoken_text_for_source(source_text: str, source_format: SourceFormat) -> str:
    """Return deterministic display-level TTS text without source mutation."""

    if type(source_text) is not str:
        raise SegmentationError("source_text must be a string")
    if type(source_format) is not SourceFormat:
        raise SegmentationError("source_format must be SourceFormat")
    utf16_length(source_text)
    value = _remove_no_read(source_text)
    value = _HTML_COMMENT.sub("", value)
    if source_format is SourceFormat.MARKDOWN:
        value = _IMAGE.sub(lambda match: match.group(1), value)
        value = _LINK.sub(lambda match: match.group(1), value)
        value = _AUTOLINK.sub("", value)
        value = _HTML_TAG.sub("", value)
        value = _FENCE_LINE.sub("", value)
        value = _INLINE_CODE.sub(lambda match: match.group(2), value)
        value = _THEMATIC_LINE.sub("", value)
        value = _HEADING_PREFIX.sub("", value)
        value = _HEADING_SUFFIX.sub("", value)
        value = _SETEXT_LINE.sub("", value)
        value = _BLOCKQUOTE_PREFIX.sub("", value)
        value = _LIST_PREFIX.sub("", value)
        value = _SEMANTIC_TAG.sub("", value.lstrip())
        value = _MARKDOWN_ESCAPE.sub(lambda match: match.group(1), value)
        value = re.sub(r"(?<!\\)[*_~]", "", value)
        value = value.replace("`", "")
        value = html.unescape(value)
    value = _WHITESPACE.sub(" ", value).strip()
    return unicodedata.normalize("NFC", value)


def _raw_blocks(source_text: str, source_format: SourceFormat) -> list[_RawBlock]:
    cores = _core_blocks(source_text, source_format)
    if not cores:
        raise SegmentationError("non-empty source contains no speakable text")
    blocks = [
        _RawBlock(
            0 if index == 0 else core.start,
            cores[index + 1].start if index + 1 < len(cores) else len(source_text),
            core.block_kind,
        )
        for index, core in enumerate(cores)
    ]
    # A hidden region is one indivisible source structure even when it contains
    # blank lines or heading-like text.  Joining at such boundaries prevents a
    # partial marker from ever reaching spoken-text rendering.
    hidden_ranges = _unspoken_ranges(source_text)
    joined: list[_RawBlock] = []
    for block in blocks:
        boundary_is_hidden = bool(joined) and any(
            start < block.start < end for start, end in hidden_ranges
        )
        if boundary_is_hidden:
            joined[-1] = replace(joined[-1], end=block.end)
        else:
            joined.append(block)
    blocks = joined
    merged: list[_RawBlock] = []
    pending_start: int | None = None
    for block in blocks:
        if spoken_text_for_source(source_text[block.start:block.end], source_format):
            start = pending_start if pending_start is not None else block.start
            merged.append(_RawBlock(start, block.end, block.block_kind))
            pending_start = None
        elif merged:
            merged[-1] = replace(merged[-1], end=block.end)
        elif pending_start is None:
            pending_start = block.start
    if pending_start is not None or not merged:
        raise SegmentationError("non-empty source contains no speakable text")
    return merged


def _find_quote_end(text: str, start: int, end: int) -> int | None:
    opener = text[start]
    closer = _QUOTE_PAIRS[opener]
    stack = [closer]
    index = start + 1
    while index < end:
        character = text[index]
        if character == stack[-1]:
            stack.pop()
            if not stack:
                return _extend_grapheme_tail(text, index + 1, end)
            index += 1
            continue
        nested_closer = _QUOTE_PAIRS.get(character)
        if nested_closer is not None:
            stack.append(nested_closer)
        index += 1
    return None


def _is_grapheme_extender(character: str) -> bool:
    codepoint = ord(character)
    return (
        bool(unicodedata.combining(character))
        or unicodedata.category(character) in {"Mc", "Me"}
        or 0xFE00 <= codepoint <= 0xFE0F
        or 0xE0100 <= codepoint <= 0xE01EF
        or 0x1F3FB <= codepoint <= 0x1F3FF
    )


def _extend_grapheme_tail(text: str, boundary: int, end: int) -> int:
    """Move a proposed cut past combining/variation/ZWJ continuation."""

    cursor = boundary
    while cursor < end:
        if _is_grapheme_extender(text[cursor]):
            cursor += 1
            continue
        if text[cursor] == "\u200d" and cursor + 1 < end:
            cursor += 2
            continue
        if text[cursor] == "\u200d":
            cursor += 1
            continue
        break
    return cursor


def _quote_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(text):
        if text[index] not in _QUOTE_PAIRS:
            index += 1
            continue
        end = _find_quote_end(text, index, len(text))
        if end is None:
            index += 1
            continue
        spans.append((index, end))
        index = end
    return spans


def _is_terminal(text: str, index: int, end: int) -> bool:
    character = text[index]
    if character not in _TERMINALS:
        return False
    if character == "!" and index + 1 < end and text[index + 1] == "[":
        return False
    if character != ".":
        return True
    before = text[index - 1] if index > 0 else ""
    after = text[index + 1] if index + 1 < end else ""
    if before.isdigit() and after.isdigit():
        return False
    return not after or after.isspace() or after in _TRAILING_CLOSERS


def _split_narration_span(text: str, start: int, end: int) -> list[tuple[int, int]]:
    if start >= end:
        return []
    spans: list[tuple[int, int]] = []
    unit_start = start
    index = start
    while index < end:
        if not _is_terminal(text, index, end):
            index += 1
            continue
        boundary = index + 1
        while boundary < end and text[boundary] in _TERMINALS:
            boundary += 1
        while boundary < end and text[boundary] in _TRAILING_CLOSERS:
            boundary += 1
        boundary = _extend_grapheme_tail(text, boundary, end)
        while boundary < end and text[boundary].isspace():
            boundary += 1
            boundary = _extend_grapheme_tail(text, boundary, end)
        spans.append((unit_start, boundary))
        unit_start = boundary
        index = boundary
    if unit_start < end:
        spans.append((unit_start, end))
    return spans


def _inner_block(text: str) -> bool:
    probe = _BLOCKQUOTE_PREFIX.sub("", text)
    probe = _LIST_PREFIX.sub("", probe)
    return _INNER_BLOCK_PREFIX.match(probe.lstrip()) is not None


def _unit_kind(
    *,
    block_kind: SourceBlockKind,
    block_text: str,
    quote_start: int | None,
) -> SegmentKind:
    semantic = _BLOCK_TO_SEGMENT.get(block_kind)
    if semantic is not None:
        return semantic
    if _inner_block(block_text):
        return SegmentKind.INNER_MONOLOGUE
    if quote_start is not None:
        cue = spoken_text_for_source(
            block_text[max(0, quote_start - 48):quote_start],
            SourceFormat.MARKDOWN,
        )
        if _INNER_CUE.search(cue):
            return SegmentKind.INNER_MONOLOGUE
        return SegmentKind.DIALOGUE
    return SegmentKind.NARRATION


def _raw_units(
    block_text: str,
    block_kind: SourceBlockKind,
    source_format: SourceFormat,
) -> list[_RawUnit]:
    if block_kind is SourceBlockKind.HEADING:
        return [_RawUnit(0, len(block_text), SegmentKind.NARRATION)]
    analysis_text = _mask_analysis_text(block_text, source_format)
    quote_spans = _quote_spans(analysis_text)
    units: list[_RawUnit] = []
    cursor = 0
    for quote_start, quote_end in quote_spans:
        kind = _unit_kind(
            block_kind=block_kind,
            block_text=block_text,
            quote_start=None,
        )
        units.extend(
            _RawUnit(start, end, kind)
            for start, end in _split_narration_span(
                analysis_text, cursor, quote_start
            )
        )
        units.append(
            _RawUnit(
                quote_start,
                quote_end,
                _unit_kind(
                    block_kind=block_kind,
                    block_text=block_text,
                    quote_start=quote_start,
                ),
            )
        )
        cursor = quote_end
    kind = _unit_kind(
        block_kind=block_kind,
        block_text=block_text,
        quote_start=None,
    )
    units.extend(
        _RawUnit(start, end, kind)
        for start, end in _split_narration_span(
            analysis_text, cursor, len(block_text)
        )
    )
    return units


def _spoken_units(
    block_text: str,
    block_kind: SourceBlockKind,
    source_format: SourceFormat,
) -> list[_RawUnit]:
    units = _raw_units(block_text, block_kind, source_format)
    material: list[_RawUnit] = []
    pending_start: int | None = None
    for unit in units:
        spoken = spoken_text_for_source(block_text[unit.start:unit.end], source_format)
        if spoken:
            start = pending_start if pending_start is not None else unit.start
            material.append(_RawUnit(start, unit.end, unit.kind))
            pending_start = None
        elif material:
            material[-1] = replace(material[-1], end=unit.end)
        elif pending_start is None:
            pending_start = unit.start
    if pending_start is not None or not material:
        raise SegmentationError("source block contains no speakable segment")
    return material


def segment_source(
    *,
    script_version_id: UUID,
    source_text: str,
    source_format: SourceFormat,
) -> SegmentationResult:
    """Materialize deterministic, source-complete T3-B segmentation metadata."""

    script_id = _require_script_version_id(script_version_id)
    if type(source_text) is not str:
        raise SegmentationError("source_text must be a string")
    if type(source_format) is not SourceFormat:
        raise SegmentationError("source_format must be SourceFormat")
    source_index = SourceIndexMap(source_text)
    _validate_no_read_markers(source_text)
    _validate_html_comments(source_text)
    if not source_text:
        result = SegmentationResult(
            script_version_id=script_id,
            source_format=source_format,
            source_content_hash=text_sha256(source_text),
            source_length_utf16=0,
            blocks=(),
            segments=(),
        )
        validate_segmentation_result(source_text, result)
        return result

    raw_blocks = _raw_blocks(source_text, source_format)
    block_hashes = [
        text_sha256(source_text[block.start:block.end]) for block in raw_blocks
    ]
    blocks: list[MaterializedSourceBlock] = []
    all_segments: list[MaterializedSegment] = []
    global_ordinal = 0
    for paragraph_ordinal, block in enumerate(raw_blocks):
        block_text = source_text[block.start:block.end]
        block_hash = block_hashes[paragraph_ordinal]
        before_hash = block_hashes[paragraph_ordinal - 1] if paragraph_ordinal else None
        after_hash = (
            block_hashes[paragraph_ordinal + 1]
            if paragraph_ordinal + 1 < len(block_hashes)
            else None
        )
        block_key = derive_source_block_key(
            script_version_id=script_id,
            block_kind=block.block_kind,
            paragraph_ordinal=paragraph_ordinal,
            block_hash=block_hash,
            anchor_before_hash=before_hash,
            anchor_after_hash=after_hash,
        )
        units = _spoken_units(block_text, block.block_kind, source_format)
        materialized: list[MaterializedSegment] = []
        for ordinal_in_block, unit in enumerate(units):
            absolute_start = block.start + unit.start
            absolute_end = block.start + unit.end
            segment_text = source_text[absolute_start:absolute_end]
            local_hash = text_sha256(segment_text)
            source_range = source_index.to_utf16_range(absolute_start, absolute_end)
            segment = MaterializedSegment(
                segment_id=derive_segment_id(
                    script_version_id=script_id,
                    ordinal=global_ordinal,
                    source_block_key=block_key,
                    segment_ordinal_in_block=ordinal_in_block,
                    local_hash=local_hash,
                ),
                ordinal=global_ordinal,
                segment_kind=unit.kind,
                source_block_kind=block.block_kind,
                paragraph_ordinal=paragraph_ordinal,
                segment_ordinal_in_block=ordinal_in_block,
                source_block_key=block_key,
                source_block_hash=block_hash,
                source_range_utf16=source_range,
                source_text=segment_text,
                spoken_text=spoken_text_for_source(segment_text, source_format),
                local_hash=local_hash,
                anchor_before_hash=before_hash,
                anchor_after_hash=after_hash,
            )
            materialized.append(segment)
            all_segments.append(segment)
            global_ordinal += 1
        blocks.append(
            MaterializedSourceBlock(
                paragraph_ordinal=paragraph_ordinal,
                block_kind=block.block_kind,
                source_block_key=block_key,
                source_block_hash=block_hash,
                source_range_utf16=source_index.to_utf16_range(block.start, block.end),
                source_text=block_text,
                anchor_before_hash=before_hash,
                anchor_after_hash=after_hash,
                segments=tuple(materialized),
            )
        )
    result = SegmentationResult(
        script_version_id=script_id,
        source_format=source_format,
        source_content_hash=text_sha256(source_text),
        source_length_utf16=source_index.utf16_length,
        blocks=tuple(blocks),
        segments=tuple(all_segments),
    )
    validate_segmentation_result(source_text, result)
    return result


def _require_contiguous_ordinals(values: Iterable[int], *, field_name: str) -> None:
    actual = list(values)
    if any(type(value) is not int for value in actual) or actual != list(
        range(len(actual))
    ):
        raise SegmentationError(f"{field_name} must be contiguous from zero")


def validate_segmentation_result(
    source_text: str,
    result: SegmentationResult,
) -> None:
    """Fail closed if materialized metadata drifts from the T3-A contract."""

    if type(source_text) is not str or type(result) is not SegmentationResult:
        raise SegmentationError("source_text/result types are invalid")
    _require_script_version_id(result.script_version_id)
    if type(result.source_format) is not SourceFormat:
        raise SegmentationError("result source_format is invalid")
    if type(result.blocks) is not tuple or not all(
        type(block) is MaterializedSourceBlock for block in result.blocks
    ):
        raise SegmentationError("blocks must be a tuple of MaterializedSourceBlock values")
    if type(result.segments) is not tuple or not all(
        type(segment) is MaterializedSegment for segment in result.segments
    ):
        raise SegmentationError("segments must be a tuple of MaterializedSegment values")
    if type(result.source_content_hash) is not str:
        raise SegmentationError("source_content_hash must be a string")
    if result.source_content_hash != text_sha256(source_text):
        raise SegmentationError("source_content_hash differs from source text")
    if type(result.source_length_utf16) is not int:
        raise SegmentationError("source_length_utf16 must be an integer")
    if result.source_length_utf16 != utf16_length(source_text):
        raise SegmentationError("source_length_utf16 differs from source text")
    _require_contiguous_ordinals(
        (block.paragraph_ordinal for block in result.blocks),
        field_name="paragraph ordinals",
    )
    _require_contiguous_ordinals(
        (segment.ordinal for segment in result.segments),
        field_name="segment ordinals",
    )
    validate_complete_utf16_partition(
        source_text,
        [block.source_range_utf16 for block in result.blocks],
    )
    validate_complete_utf16_partition(
        source_text,
        [segment.source_range_utf16 for segment in result.segments],
    )
    flattened: list[MaterializedSegment] = []
    for index, block in enumerate(result.blocks):
        if type(block.block_kind) is not SourceBlockKind:
            raise SegmentationError("source block kind must use the frozen enum")
        if block.block_kind is SourceBlockKind.SYNTHETIC:
            raise SegmentationError("T3-B must not materialize synthetic source blocks")
        if type(block.segments) is not tuple or not all(
            type(segment) is MaterializedSegment for segment in block.segments
        ):
            raise SegmentationError(
                "source block segments must be a tuple of MaterializedSegment values"
            )
        if utf16_slice(source_text, block.source_range_utf16) != block.source_text:
            raise SegmentationError("source block text differs from UTF-16 slice")
        if block.source_block_hash != text_sha256(block.source_text):
            raise SegmentationError("source block hash differs from source text")
        expected_before = result.blocks[index - 1].source_block_hash if index else None
        expected_after = (
            result.blocks[index + 1].source_block_hash
            if index + 1 < len(result.blocks)
            else None
        )
        if (
            block.anchor_before_hash != expected_before
            or block.anchor_after_hash != expected_after
        ):
            raise SegmentationError("source block neighbor anchors differ")
        expected_key = derive_source_block_key(
            script_version_id=result.script_version_id,
            block_kind=block.block_kind,
            paragraph_ordinal=block.paragraph_ordinal,
            block_hash=block.source_block_hash,
            anchor_before_hash=block.anchor_before_hash,
            anchor_after_hash=block.anchor_after_hash,
        )
        if block.source_block_key != expected_key:
            raise SegmentationError("source_block_key differs from frozen derivation")
        if not block.segments:
            raise SegmentationError("non-empty source block requires segments")
        _require_contiguous_ordinals(
            (segment.segment_ordinal_in_block for segment in block.segments),
            field_name="segment ordinals in block",
        )
        validate_complete_utf16_partition(
            block.source_text,
            [
                Utf16Range(
                    segment.source_range_utf16.start - block.source_range_utf16.start,
                    segment.source_range_utf16.end_exclusive
                    - block.source_range_utf16.start,
                )
                for segment in block.segments
            ],
        )
        for segment in block.segments:
            if type(segment) is not MaterializedSegment:
                raise SegmentationError("block segments must be MaterializedSegment values")
            if (
                type(segment.segment_kind) is not SegmentKind
                or segment.segment_kind not in SOURCE_BOUND_SEGMENT_KINDS
            ):
                raise SegmentationError("T3-B segment_kind must be source-bound")
            if type(segment.source_block_kind) is not SourceBlockKind:
                raise SegmentationError("segment source_block_kind must use frozen enum")
            if (
                segment.source_block_kind is not block.block_kind
                or segment.paragraph_ordinal != block.paragraph_ordinal
                or segment.source_block_key != block.source_block_key
                or segment.source_block_hash != block.source_block_hash
                or segment.anchor_before_hash != block.anchor_before_hash
                or segment.anchor_after_hash != block.anchor_after_hash
            ):
                raise SegmentationError("segment source-block metadata drifted")
            if utf16_slice(source_text, segment.source_range_utf16) != segment.source_text:
                raise SegmentationError("segment source_text differs from UTF-16 slice")
            if segment.local_hash != text_sha256(segment.source_text):
                raise SegmentationError("segment local_hash differs from source_text")
            if type(segment.spoken_text) is not str or not segment.spoken_text:
                raise SegmentationError("segment spoken_text must be non-empty NFC")
            if segment.spoken_text != unicodedata.normalize(
                "NFC", segment.spoken_text
            ):
                raise SegmentationError("segment spoken_text must be non-empty NFC")
            expected_spoken = spoken_text_for_source(
                segment.source_text,
                result.source_format,
            )
            if segment.spoken_text != expected_spoken:
                raise SegmentationError("segment spoken_text differs from source rendering")
            expected_id = derive_segment_id(
                script_version_id=result.script_version_id,
                ordinal=segment.ordinal,
                source_block_key=segment.source_block_key,
                segment_ordinal_in_block=segment.segment_ordinal_in_block,
                local_hash=segment.local_hash,
            )
            if segment.segment_id != expected_id:
                raise SegmentationError("segment_id differs from frozen derivation")
        flattened.extend(block.segments)
    if tuple(flattened) != result.segments:
        raise SegmentationError("flattened block segments differ from result segments")
    if bool(source_text) != bool(result.blocks):
        raise SegmentationError("empty/non-empty source materialization differs")


__all__ = [
    "MaterializedSegment",
    "MaterializedSourceBlock",
    "SegmentationError",
    "SegmentationResult",
    "SourceFormat",
    "segment_source",
    "spoken_text_for_source",
    "validate_segmentation_result",
]
