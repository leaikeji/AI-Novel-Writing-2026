"""Bounded, deterministic matching for structured private-library lexicons."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import hashlib
import heapq
import html
import re
from typing import Iterable, Iterator, Literal, Sequence
from uuid import UUID, uuid5

from .lexicon_contracts import (
    LEXICON_MATCHER_VERSION,
    MAX_EFFECTIVE_RULES,
    LexiconAction,
    LexiconEntry,
    LexiconEntryState,
    LexiconMatchMode,
)


MAX_MATCH_HITS = 2_000
_HIT_NAMESPACE = UUID("cc79fe83-566d-5d9b-8e32-d3a10fe31b07")
_ASCII_WORD_CHARACTER = re.compile(r"[A-Za-z0-9_]")
_ESCAPABLE = frozenset(r"!\"#$%&'()*+,-./:;<=>?@[\]^_`{|}~")


@dataclass(frozen=True, slots=True)
class VisibleText:
    text: str
    source_utf16_offsets: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class LexiconRuleSource:
    asset_id: UUID
    asset_version_id: UUID
    entry: LexiconEntry
    priority: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset_id", UUID(str(self.asset_id)))
        object.__setattr__(self, "asset_version_id", UUID(str(self.asset_version_id)))
        if not isinstance(self.entry, LexiconEntry):
            object.__setattr__(self, "entry", LexiconEntry.model_validate(self.entry))
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise TypeError("priority must be an integer")


@dataclass(frozen=True, slots=True)
class LexiconMatchHit:
    hit_id: UUID
    asset_id: UUID
    asset_version_id: UUID
    entry_id: str
    action: LexiconAction
    matched_text: str
    start_utf16: int
    end_utf16: int
    reason: str
    count: int
    window: int | None


@dataclass(frozen=True, slots=True)
class LexiconMatchReport:
    status: Literal["complete", "incomplete"]
    hits: tuple[LexiconMatchHit, ...]
    scanned_rule_count: int
    omitted_rule_count: int
    visible_character_count: int
    matcher_version: str = LEXICON_MATCHER_VERSION


@dataclass(frozen=True, slots=True)
class _Projection:
    public: VisibleText
    source_spans: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class _Occurrence:
    start: int
    end: int
    matched_text: str


def _utf16_width(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _source_utf16_boundaries(source: str) -> list[int]:
    boundaries = [0]
    for character in source:
        boundaries.append(boundaries[-1] + _utf16_width(character))
    return boundaries


def _hide(
    visible: list[bool],
    start: int,
    end: int,
) -> None:
    for index in range(max(start, 0), min(end, len(visible))):
        visible[index] = False


def _eligible(visible: Sequence[bool], inline: Sequence[bool], start: int, end: int) -> bool:
    return start < end and all(
        visible[index] and inline[index] for index in range(start, end)
    )


def _mark_block_syntax(source: str, visible: list[bool], inline: list[bool]) -> None:
    in_fence = False
    fence_character = ""
    fence_length = 0
    cursor = 0
    for line in source.splitlines(keepends=True):
        content_end = len(line.rstrip("\r\n"))
        content = line[:content_end]
        fence = re.match(r"^[ \t]{0,3}(`{3,}|~{3,})", content)
        if in_fence:
            if (
                fence
                and fence.group(1)[0] == fence_character
                and len(fence.group(1)) >= fence_length
            ):
                _hide(visible, cursor, cursor + content_end)
                in_fence = False
            else:
                for index in range(cursor, cursor + content_end):
                    inline[index] = False
            cursor += len(line)
            continue
        if fence:
            _hide(visible, cursor, cursor + content_end)
            in_fence = True
            fence_character = fence.group(1)[0]
            fence_length = len(fence.group(1))
            cursor += len(line)
            continue

        if re.match(r"^[ \t]{0,3}\[[^\]\n]+\]:[ \t]*\S+", content):
            _hide(visible, cursor, cursor + content_end)
            cursor += len(line)
            continue
        if re.match(r"^[ \t]{0,3}((\*[ \t]*){3,}|(-[ \t]*){3,}|(_[ \t]*){3,})$", content):
            _hide(visible, cursor, cursor + content_end)
            cursor += len(line)
            continue
        if re.match(r"^[ \t]{0,3}(=+|-+)[ \t]*$", content):
            _hide(visible, cursor, cursor + content_end)
            cursor += len(line)
            continue

        prefix = re.match(r"^[ \t]{0,3}(?:>[ \t]?)*", content)
        offset = prefix.end() if prefix else 0
        _hide(visible, cursor, cursor + offset)
        rest = content[offset:]
        marker = re.match(r"(?:#{1,6}[ \t]+|(?:[-+*]|\d{1,9}[.)])[ \t]+)", rest)
        if marker:
            _hide(visible, cursor + offset, cursor + offset + marker.end())
            rest_start = offset + marker.end()
            task = re.match(r"\[[ xX]\][ \t]+", content[rest_start:])
            if task:
                _hide(visible, cursor + rest_start, cursor + rest_start + task.end())
        heading_close = re.search(r"[ \t]+#+[ \t]*$", content)
        if heading_close and re.match(r"^[ \t]{0,3}#{1,6}[ \t]+", content):
            _hide(visible, cursor + heading_close.start(), cursor + content_end)
        cursor += len(line)


def _mark_inline_syntax(source: str, visible: list[bool], inline: list[bool]) -> None:
    # HTML comments are absent from the rendered prose.
    for match in re.finditer(r"<!--[\s\S]*?(?:-->|\Z)", source):
        _hide(visible, match.start(), match.end())

    # Images have no rendered body text.  Ordinary links retain their label but
    # lose brackets and destination addresses.
    link_pattern = re.compile(
        r"(?P<image>!)?\[(?P<label>[^\]\n]*)\]\([ \t]*(?:<[^>\n]*>|[^)\n]*)\)"
    )
    for match in link_pattern.finditer(source):
        if not _eligible(visible, inline, match.start(), match.end()):
            continue
        if match.group("image"):
            _hide(visible, match.start(), match.end())
            continue
        _hide(visible, match.start(), match.start("label"))
        _hide(visible, match.end("label"), match.end())

    reference_labels = {
        match.group("label").strip().casefold()
        for match in re.finditer(
            r"(?m)^[ \t]{0,3}\[(?P<label>[^\]\n]+)\]:[ \t]*\S+",
            source,
        )
    }
    reference_pattern = re.compile(
        r"(?P<image>!)?\[(?P<label>[^\]\n]+)\](?:\[(?P<reference>[^\]\n]*)\])?"
    )
    for match in reference_pattern.finditer(source):
        if not _eligible(visible, inline, match.start(), match.end()):
            continue
        reference = match.group("reference")
        key = (reference if reference not in (None, "") else match.group("label"))
        if key.strip().casefold() not in reference_labels:
            continue
        if match.group("image"):
            _hide(visible, match.start(), match.end())
            continue
        _hide(visible, match.start(), match.start("label"))
        _hide(visible, match.end("label"), match.end())

    # Autolinks and HTML tags are not prose.  A less-than sign in dialogue is
    # retained unless the complete token has HTML/autolink shape.
    for match in re.finditer(r"<(?:https?://|mailto:)[^>\n]+>", source, re.IGNORECASE):
        if _eligible(visible, inline, match.start(), match.end()):
            _hide(visible, match.start(), match.end())
    for match in re.finditer(r"</?[A-Za-z][^>\n]*>", source):
        if _eligible(visible, inline, match.start(), match.end()):
            _hide(visible, match.start(), match.end())

    # Inline-code content is visible literally; only matching delimiters vanish.
    cursor = 0
    while cursor < len(source):
        if source[cursor] != "`" or not (visible[cursor] and inline[cursor]):
            cursor += 1
            continue
        end = cursor + 1
        while end < len(source) and source[end] == "`":
            end += 1
        delimiter = source[cursor:end]
        close = source.find(delimiter, end)
        if close >= 0 and _eligible(visible, inline, cursor, end) and _eligible(
            visible, inline, close, close + len(delimiter)
        ):
            _hide(visible, cursor, end)
            _hide(visible, close, close + len(delimiter))
            for index in range(end, close):
                inline[index] = False
            cursor = close + len(delimiter)
        else:
            cursor = end

    # Markdown escapes expose the escaped punctuation but not the backslash.
    for match in re.finditer(r"\\(.)", source, re.DOTALL):
        if match.group(1) in _ESCAPABLE and _eligible(
            visible, inline, match.start(), match.end()
        ):
            visible[match.start()] = False

    # Paired emphasis/strike delimiters.  Underscores inside ASCII identifiers
    # are deliberately left alone.
    delimiter_pattern = re.compile(r"(?<!\\)(\*{1,3}|_{1,3}|~{2})")
    openers = list(delimiter_pattern.finditer(source))
    used: set[int] = set()
    for opener in openers:
        if opener.start() in used or not _eligible(
            visible, inline, opener.start(), opener.end()
        ):
            continue
        token = opener.group(1)
        if opener.end() >= len(source) or source[opener.end()].isspace():
            continue
        if token.startswith("_") and opener.start() > 0:
            if source[opener.start() - 1].isascii() and source[opener.start() - 1].isalnum():
                continue
        for closer in openers:
            if closer.start() <= opener.end() or closer.group(1) != token:
                continue
            if closer.start() in used or source[closer.start() - 1].isspace():
                continue
            if not _eligible(visible, inline, closer.start(), closer.end()):
                continue
            if token.startswith("_") and closer.end() < len(source):
                if source[closer.end()].isascii() and source[closer.end()].isalnum():
                    continue
            _hide(visible, opener.start(), opener.end())
            _hide(visible, closer.start(), closer.end())
            used.update((opener.start(), closer.start()))
            break

    # Raw link addresses are visible in Markdown renderers but are not prose for
    # this scanner.  Do not inspect them inside fenced or inline code.
    for match in re.finditer(r"(?:https?://|mailto:)[^\s<>()]+", source, re.IGNORECASE):
        start, end = match.span()
        while end > start and source[end - 1] in ".,!?;:，。！？；：":
            end -= 1
        if _eligible(visible, inline, start, end):
            _hide(visible, start, end)

    # Table pipes are structural unless escaped or protected as code.
    for index, character in enumerate(source):
        if character == "|" and visible[index] and inline[index]:
            if index == 0 or source[index - 1] != "\\":
                visible[index] = False


def _project_markdown(source: str) -> _Projection:
    if not isinstance(source, str):
        raise TypeError("source must be text")
    visible = [True] * len(source)
    inline = [True] * len(source)
    _mark_block_syntax(source, visible, inline)
    _mark_inline_syntax(source, visible, inline)
    source_boundaries = _source_utf16_boundaries(source)

    text_parts: list[str] = []
    spans: list[tuple[int, int]] = []
    indices = [index for index, keep in enumerate(visible) if keep]
    cursor = 0
    while cursor < len(indices):
        index = indices[cursor]
        # Decode a complete visible HTML character reference as rendered text.
        if source[index] == "&":
            entity_match = re.match(
                r"&(?:#[0-9]{1,7}|#[xX][0-9A-Fa-f]{1,6}|"
                r"[A-Za-z][A-Za-z0-9]{1,31});",
                source[index:],
            )
            if entity_match:
                end_index = index + entity_match.end()
                expected = list(range(index, end_index))
                if indices[cursor:cursor + len(expected)] == expected:
                    decoded = html.unescape(source[index:end_index])
                    for character in decoded:
                        text_parts.append(character)
                        spans.append((source_boundaries[index], source_boundaries[end_index]))
                    cursor += len(expected)
                    continue
        text_parts.append(source[index])
        spans.append((source_boundaries[index], source_boundaries[index + 1]))
        cursor += 1

    text = "".join(text_parts)
    offsets: list[int] = []
    for character, (start, end) in zip(text, spans, strict=True):
        width = _utf16_width(character)
        if width == 1:
            offsets.append(start)
        else:
            # Astral characters expose the surrogate boundary in UTF-16.
            source_width = end - start
            offsets.extend(start + min(unit, source_width) for unit in range(width))
    if spans:
        offsets.append(spans[-1][1])
    else:
        offsets.append(0)
    return _Projection(
        public=VisibleText(text=text, source_utf16_offsets=tuple(offsets)),
        source_spans=tuple(spans),
    )


def extract_markdown_visible_text(source: str) -> VisibleText:
    """Return rendered prose and a monotonic visible-to-source UTF-16 map.

    ``source_utf16_offsets`` contains one element for every UTF-16 boundary in
    ``text``.  Boundaries separated by removed markup map forward to the next
    visible source character; the terminal boundary maps after the last one.
    """

    return _project_markdown(source).public


def _candidate_pattern(entry: LexiconEntry, candidate: str) -> re.Pattern[str]:
    escaped = re.escape(candidate)
    if entry.match_mode is LexiconMatchMode.ASCII_WORD:
        if _ASCII_WORD_CHARACTER.match(candidate[0]):
            escaped = rf"(?<![A-Za-z0-9_]){escaped}"
        if _ASCII_WORD_CHARACTER.match(candidate[-1]):
            escaped = rf"{escaped}(?![A-Za-z0-9_])"
    flags = 0 if entry.case_sensitive else re.IGNORECASE
    return re.compile(rf"(?=({escaped}))", flags)


def _iter_occurrences(text: str, entry: LexiconEntry) -> Iterator[_Occurrence]:
    candidates = []
    seen: set[str] = set()
    for candidate in (entry.term, *entry.variants):
        key = candidate if entry.case_sensitive else candidate.casefold()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)

    iterators: list[Iterator[_Occurrence]] = []
    for candidate in candidates:
        pattern = _candidate_pattern(entry, candidate)

        def generate(
            expression: re.Pattern[str] = pattern,
        ) -> Iterator[_Occurrence]:
            for match in expression.finditer(text):
                start, end = match.span(1)
                yield _Occurrence(start=start, end=end, matched_text=text[start:end])

        iterators.append(generate())

    merged = heapq.merge(*iterators, key=lambda item: (item.start, item.end, item.matched_text))
    previous: tuple[int, int] | None = None
    for occurrence in merged:
        key = (occurrence.start, occurrence.end)
        if key == previous:
            continue
        previous = key
        yield occurrence


def _watch_occurrences(
    occurrences: Iterable[_Occurrence],
    *,
    threshold: int,
    window: int,
    nonspace_prefix: Sequence[int],
    retain: int,
) -> tuple[list[_Occurrence], int, int]:
    active: deque[_Occurrence] = deque()
    retained: list[_Occurrence] = []
    retained_keys: set[tuple[int, int]] = set()
    eligible_count = 0
    total_count = 0
    eligible_keys: set[tuple[int, int]] = set()

    def mark(occurrence: _Occurrence) -> None:
        nonlocal eligible_count
        key = (occurrence.start, occurrence.end)
        if key in eligible_keys:
            return
        if eligible_count < retain:
            eligible_keys.add(key)
            eligible_count += 1
        if len(retained) < retain and key not in retained_keys:
            retained.append(occurrence)
            retained_keys.add(key)

    was_qualifying = False
    for occurrence in occurrences:
        total_count += 1
        current_position = nonspace_prefix[occurrence.start]
        while active and (
            current_position - nonspace_prefix[active[0].start] >= window
        ):
            active.popleft()
        active.append(occurrence)
        qualifying = len(active) >= threshold
        if qualifying:
            if not was_qualifying:
                for member in active:
                    mark(member)
            else:
                mark(occurrence)
        was_qualifying = qualifying
    return retained, eligible_count, total_count


def _bounded_reason(prefix: str, note: str) -> str:
    reason = prefix if not note else f"{prefix}；{note}"
    return reason if len(reason) <= 500 else reason[:499] + "…"


def _rule_order(rule: LexiconRuleSource) -> tuple[int, str, str, str]:
    return (-rule.priority, str(rule.asset_id), str(rule.asset_version_id), rule.entry.entry_id)


def match_lexicon(
    source_markdown: str,
    rules: Sequence[LexiconRuleSource] | Iterable[LexiconRuleSource],
    max_rules: int = MAX_EFFECTIVE_RULES,
    max_hits: int = MAX_MATCH_HITS,
) -> LexiconMatchReport:
    """Match active watch/forbid rules without parsing rendered asset content."""

    if (
        isinstance(max_rules, bool)
        or not isinstance(max_rules, int)
        or not 0 <= max_rules <= MAX_EFFECTIVE_RULES
    ):
        raise ValueError(f"max_rules must be between 0 and {MAX_EFFECTIVE_RULES}")
    if (
        isinstance(max_hits, bool)
        or not isinstance(max_hits, int)
        or not 0 <= max_hits <= MAX_MATCH_HITS
    ):
        raise ValueError(f"max_hits must be between 0 and {MAX_MATCH_HITS}")
    projection = _project_markdown(source_markdown)
    text = projection.public.text
    normalized_rules = [
        rule if isinstance(rule, LexiconRuleSource) else LexiconRuleSource(**rule)
        for rule in rules
    ]
    normalized_rules.sort(key=_rule_order)
    selected = normalized_rules[:max_rules]
    omitted_rule_count = len(normalized_rules) - len(selected)

    nonspace_prefix = [0]
    for character in text:
        nonspace_prefix.append(nonspace_prefix[-1] + (0 if character.isspace() else 1))
    visible_character_count = nonspace_prefix[-1]

    retained_hits: list[LexiconMatchHit] = []
    total_hit_count = 0
    retain_per_rule = max_hits + 1
    source_hash = hashlib.sha256(source_markdown.encode("utf-8")).hexdigest()
    for rule in selected:
        entry = rule.entry
        if entry.state is not LexiconEntryState.ACTIVE or entry.action is LexiconAction.RECOMMEND:
            continue
        occurrences = _iter_occurrences(text, entry)
        if entry.action is LexiconAction.WATCH:
            assert entry.watch_threshold is not None
            kept, eligible_count, total_count = _watch_occurrences(
                occurrences,
                threshold=entry.watch_threshold.count,
                window=entry.watch_threshold.window_characters,
                nonspace_prefix=nonspace_prefix,
                retain=retain_per_rule,
            )
            total_hit_count += eligible_count
            count = total_count
            window: int | None = entry.watch_threshold.window_characters
            reason = _bounded_reason(
                f"连续{window}个可见字符内达到慎用阈值"
                f"{entry.watch_threshold.count}次（全文{total_count}次）",
                entry.note,
            )
        else:
            kept = []
            total_count = 0
            for occurrence in occurrences:
                total_count += 1
                if len(kept) < retain_per_rule:
                    kept.append(occurrence)
            total_hit_count += total_count
            count = total_count
            window = None
            reason = _bounded_reason("作者标记为禁用表达", entry.note)

        for occurrence in kept:
            if occurrence.start >= occurrence.end:
                continue
            start_utf16 = projection.source_spans[occurrence.start][0]
            end_utf16 = projection.source_spans[occurrence.end - 1][1]
            stable_key = ":".join((
                source_hash,
                str(rule.asset_id),
                str(rule.asset_version_id),
                entry.entry_id,
                entry.action.value,
                str(start_utf16),
                str(end_utf16),
            ))
            retained_hits.append(LexiconMatchHit(
                hit_id=uuid5(_HIT_NAMESPACE, stable_key),
                asset_id=rule.asset_id,
                asset_version_id=rule.asset_version_id,
                entry_id=entry.entry_id,
                action=entry.action,
                matched_text=occurrence.matched_text,
                start_utf16=start_utf16,
                end_utf16=end_utf16,
                reason=reason,
                count=count,
                window=window,
            ))

    retained_hits.sort(key=lambda hit: (
        hit.start_utf16,
        hit.end_utf16,
        -{LexiconAction.WATCH: 1, LexiconAction.FORBID: 2}[hit.action],
        str(hit.asset_id),
        str(hit.asset_version_id),
        hit.entry_id,
    ))
    incomplete = omitted_rule_count > 0 or total_hit_count > max_hits
    return LexiconMatchReport(
        status="incomplete" if incomplete else "complete",
        hits=tuple(retained_hits[:max_hits]),
        scanned_rule_count=len(selected),
        omitted_rule_count=omitted_rule_count,
        visible_character_count=visible_character_count,
    )


__all__ = [
    "LexiconMatchHit",
    "LexiconMatchReport",
    "LexiconRuleSource",
    "VisibleText",
    "extract_markdown_visible_text",
    "match_lexicon",
]
