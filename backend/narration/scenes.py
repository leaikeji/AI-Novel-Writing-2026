"""Deterministic scene-boundary detection for T3 narration scripts.

The detector only uses document structure and explicit caller hints.  It does
not call a model and v1 can therefore never emit a ``cloud_assisted`` boundary.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Final, Sequence
from uuid import RFC_4122, UUID

from .script_contracts import (
    SceneBoundarySource,
    SceneContract,
    Utf16Range,
    derive_scene_id,
    text_sha256,
    utf16_length,
    utf16_slice,
)


SCENE_RULESET_VERSION: Final = "narration-scene-rules/1"

_MARKDOWN_HEADING = re.compile(
    r"^\s{0,3}(?P<marks>#{1,6})[ \t]+(?P<title>.+?)[ \t]*#*[ \t]*$"
)
_SCENE_SEPARATOR = re.compile(
    r"^\s*(?:"
    r"(?:\*\s*){3,}|"
    r"(?:_\s*){3,}|"
    r"(?:-\s*){3,}|"
    r"(?:—\s*){3,}|"
    r"(?:※\s*){3,}|"
    r"(?:◆\s*){3,}"
    r")\s*$"
)


class SceneRuleError(ValueError):
    """Raised when source or boundary hints are malformed or conflicting."""


def _require_uuid(value: object, *, field_name: str) -> UUID:
    if (
        type(value) is not UUID
        or value.variant != RFC_4122
        or value.version not in {1, 2, 3, 4, 5}
    ):
        raise SceneRuleError(f"{field_name} must be an RFC-4122 UUID v1-v5")
    return value


def _require_source_text(value: object) -> str:
    if type(value) is not str:
        raise SceneRuleError("source_text must be a string")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise SceneRuleError(
            "source_text contains an unpaired Unicode surrogate"
        ) from error
    return value


def _normalize_title(value: str | None) -> str | None:
    if value is None:
        return None
    if type(value) is not str:
        raise SceneRuleError("scene title must be a string or None")
    title = unicodedata.normalize("NFC", value.strip())
    if not title:
        return None
    if len(title) > 240:
        raise SceneRuleError("scene title exceeds 240 characters")
    try:
        title.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise SceneRuleError(
            "scene title contains an unpaired Unicode surrogate"
        ) from error
    return title


@dataclass(frozen=True, slots=True)
class SceneBoundaryHint:
    start_utf16: int
    boundary_source: SceneBoundarySource
    title: str | None = None
    ruleset_version: str = SCENE_RULESET_VERSION

    def __post_init__(self) -> None:
        if type(self.start_utf16) is not int or self.start_utf16 < 0:
            raise SceneRuleError("start_utf16 must be a non-negative integer")
        if type(self.boundary_source) is not SceneBoundarySource:
            raise SceneRuleError("boundary_source must be SceneBoundarySource")
        object.__setattr__(self, "title", _normalize_title(self.title))
        if self.ruleset_version != SCENE_RULESET_VERSION:
            raise SceneRuleError("unknown scene ruleset version")


def _line_offsets(source_text: str) -> tuple[tuple[int, str], ...]:
    offsets: list[tuple[int, str]] = []
    start_utf16 = 0
    for line in source_text.splitlines(keepends=True):
        offsets.append((start_utf16, line.rstrip("\r\n")))
        start_utf16 += utf16_length(line)
    if source_text and not offsets:
        offsets.append((0, source_text))
    return tuple(offsets)


def scan_scene_boundary_hints(source_text: str) -> tuple[SceneBoundaryHint, ...]:
    """Scan Markdown headings and explicit separator-only lines."""

    source_text = _require_source_text(source_text)
    if not source_text:
        return ()

    detected: list[SceneBoundaryHint] = []
    pending_separator: SceneBoundaryHint | None = None
    lines = _line_offsets(source_text)
    for index, (start_utf16, line) in enumerate(lines):
        heading = _MARKDOWN_HEADING.fullmatch(line)
        if heading is not None:
            if pending_separator is not None:
                detected.append(
                    SceneBoundaryHint(
                        start_utf16=pending_separator.start_utf16,
                        boundary_source=SceneBoundarySource.SCENE_SEPARATOR,
                        title=heading.group("title"),
                    )
                )
                pending_separator = None
            else:
                detected.append(
                    SceneBoundaryHint(
                        start_utf16=start_utf16,
                        boundary_source=(
                            SceneBoundarySource.DOCUMENT_START
                            if start_utf16 == 0
                            else SceneBoundarySource.MARKDOWN_HEADING
                        ),
                        title=heading.group("title"),
                    )
                )
            continue
        separator = _SCENE_SEPARATOR.fullmatch(line) is not None
        previous_is_setext_title = (
            separator
            and line.strip().replace("-", "") == ""
            and index > 0
            and bool(lines[index - 1][1].strip())
        )
        if separator and not previous_is_setext_title:
            if pending_separator is None:
                pending_separator = SceneBoundaryHint(
                    start_utf16=start_utf16,
                    boundary_source=SceneBoundarySource.SCENE_SEPARATOR,
                )
            continue
        if not line.strip():
            continue
        if pending_separator is not None:
            detected.append(pending_separator)
            pending_separator = None
    return tuple(detected)


def _python_index_for_utf16_boundary(source_text: str, offset: int) -> int:
    if type(offset) is not int or offset < 0:
        raise SceneRuleError("scene boundary offset must be non-negative")
    units = 0
    for index, character in enumerate(source_text):
        if units == offset:
            return index
        width = 2 if ord(character) > 0xFFFF else 1
        if units < offset < units + width:
            raise SceneRuleError("scene boundary splits a UTF-16 surrogate pair")
        units += width
    if units == offset:
        return len(source_text)
    raise SceneRuleError("scene boundary exceeds source_text")


def _merge_hints(
    hints: Sequence[SceneBoundaryHint],
    *,
    source_length_utf16: int,
) -> tuple[SceneBoundaryHint, ...]:
    by_offset: dict[int, SceneBoundaryHint] = {}
    for hint in hints:
        if type(hint) is not SceneBoundaryHint:
            raise SceneRuleError("boundary_hints contain a non-SceneBoundaryHint")
        if hint.start_utf16 >= source_length_utf16:
            raise SceneRuleError(
                "scene boundary must point inside non-empty source_text"
            )
        existing = by_offset.get(hint.start_utf16)
        if existing is None:
            by_offset[hint.start_utf16] = hint
            continue
        if existing != hint:
            raise SceneRuleError(
                "conflicting scene boundary hints share the same UTF-16 offset"
            )
    return tuple(by_offset[offset] for offset in sorted(by_offset))


def _validate_segment_partition(
    source_segment_ranges_utf16: Sequence[Utf16Range],
    *,
    source_length_utf16: int,
) -> tuple[Utf16Range, ...]:
    if isinstance(source_segment_ranges_utf16, (str, bytes)) or not isinstance(
        source_segment_ranges_utf16, Sequence
    ):
        raise SceneRuleError("source_segment_ranges_utf16 must be a sequence")
    ranges = tuple(source_segment_ranges_utf16)
    if not ranges or not all(type(item) is Utf16Range for item in ranges):
        raise SceneRuleError(
            "source segment ranges must be a non-empty sequence of Utf16Range"
        )
    cursor = 0
    for source_range in ranges:
        if source_range.start != cursor:
            raise SceneRuleError(
                "source segment ranges must form a contiguous partition"
            )
        cursor = source_range.end_exclusive
    if cursor != source_length_utf16:
        raise SceneRuleError(
            "source segment ranges must cover the complete source_text"
        )
    return ranges


def _align_hints_to_segment_partition(
    hints: Sequence[SceneBoundaryHint],
    *,
    ranges: tuple[Utf16Range, ...],
    source_length_utf16: int,
) -> tuple[SceneBoundaryHint, ...]:
    starts = {source_range.start for source_range in ranges}
    aligned: list[SceneBoundaryHint] = []
    for hint in hints:
        if hint.start_utf16 in starts:
            aligned.append(hint)
            continue
        containing = next(
            (
                source_range
                for source_range in ranges
                if source_range.start
                < hint.start_utf16
                < source_range.end_exclusive
            ),
            None,
        )
        if containing is None:
            raise SceneRuleError("scene boundary is outside the source partition")
        if hint.boundary_source is not SceneBoundarySource.SCENE_SEPARATOR:
            raise SceneRuleError(
                "non-separator scene boundary cannot split a source segment"
            )
        if containing.end_exclusive == source_length_utf16:
            continue
        aligned.append(
            SceneBoundaryHint(
                start_utf16=containing.end_exclusive,
                boundary_source=hint.boundary_source,
                title=hint.title,
            )
        )
    return _merge_hints(aligned, source_length_utf16=source_length_utf16)


def build_scene_contracts(
    *,
    script_version_id: UUID,
    source_text: str,
    boundary_hints: Sequence[SceneBoundaryHint] = (),
    detect_document_structure: bool = True,
    source_segment_ranges_utf16: Sequence[Utf16Range] | None = None,
) -> tuple[SceneContract, ...]:
    """Build contiguous, version-scoped T3-A scene contracts.

    If no reliable boundary exists, the exact fallback is one chapter-wide
    scene.  Explicit ``PARAGRAPH_RULE`` and ``MANUAL`` hints are accepted only
    from the caller; this module never invents them from ordinary blank lines.
    """

    _require_uuid(script_version_id, field_name="script_version_id")
    source_text = _require_source_text(source_text)
    if type(detect_document_structure) is not bool:
        raise SceneRuleError("detect_document_structure must be an exact boolean")
    if isinstance(boundary_hints, (str, bytes)) or not isinstance(
        boundary_hints, Sequence
    ):
        raise SceneRuleError("boundary_hints must be a sequence")
    if not source_text:
        if boundary_hints:
            raise SceneRuleError("empty source_text cannot carry scene boundaries")
        if source_segment_ranges_utf16 is not None:
            if isinstance(source_segment_ranges_utf16, (str, bytes)) or not isinstance(
                source_segment_ranges_utf16, Sequence
            ):
                raise SceneRuleError(
                    "source_segment_ranges_utf16 must be a sequence"
                )
            if source_segment_ranges_utf16:
                raise SceneRuleError(
                    "empty source_text cannot carry source segment ranges"
                )
        return ()

    source_length = utf16_length(source_text)
    combined: list[SceneBoundaryHint] = []
    if detect_document_structure:
        combined.extend(scan_scene_boundary_hints(source_text))
    combined.extend(boundary_hints)

    merged: Sequence[SceneBoundaryHint] = _merge_hints(
        combined,
        source_length_utf16=source_length,
    )
    for hint in merged:
        _python_index_for_utf16_boundary(source_text, hint.start_utf16)
        if (
            hint.boundary_source is SceneBoundarySource.DOCUMENT_START
            and hint.start_utf16 != 0
        ):
            raise SceneRuleError(
                "document_start boundary is only valid at UTF-16 offset zero"
            )
    if source_segment_ranges_utf16 is not None:
        partition = _validate_segment_partition(
            source_segment_ranges_utf16,
            source_length_utf16=source_length,
        )
        for source_range in partition:
            _python_index_for_utf16_boundary(source_text, source_range.start)
            _python_index_for_utf16_boundary(
                source_text,
                source_range.end_exclusive,
            )
        merged = _align_hints_to_segment_partition(
            merged,
            ranges=partition,
            source_length_utf16=source_length,
        )
    merged = list(merged)

    start_hint = next((hint for hint in merged if hint.start_utf16 == 0), None)
    boundaries: list[SceneBoundaryHint] = [
        SceneBoundaryHint(
            start_utf16=0,
            boundary_source=SceneBoundarySource.DOCUMENT_START,
            title=start_hint.title if start_hint is not None else None,
        )
    ]
    boundaries.extend(hint for hint in merged if hint.start_utf16 > 0)

    scenes: list[SceneContract] = []
    for ordinal, boundary in enumerate(boundaries):
        end_exclusive = (
            boundaries[ordinal + 1].start_utf16
            if ordinal + 1 < len(boundaries)
            else source_length
        )
        source_range = Utf16Range(boundary.start_utf16, end_exclusive)
        scene_text = utf16_slice(source_text, source_range)
        local_hash = text_sha256(scene_text)
        scenes.append(
            SceneContract(
                scene_id=derive_scene_id(
                    script_version_id=script_version_id,
                    ordinal=ordinal,
                    source_range=source_range,
                    local_hash=local_hash,
                ),
                ordinal=ordinal,
                source_range_utf16=source_range,
                boundary_source=boundary.boundary_source,
                local_hash=local_hash,
                title=boundary.title,
            )
        )
    return tuple(scenes)


def scene_ids_for_source_ranges(
    *,
    scenes: Sequence[SceneContract],
    source_ranges_utf16: Sequence[Utf16Range],
) -> tuple[UUID, ...]:
    """Map each T3-B range to exactly one containing typed scene."""

    if isinstance(scenes, (str, bytes)) or not isinstance(scenes, Sequence):
        raise SceneRuleError("scenes must be a sequence")
    if type(scenes) is tuple:
        typed_scenes = scenes
    else:
        typed_scenes = tuple(scenes)
    if not all(type(scene) is SceneContract for scene in typed_scenes):
        raise SceneRuleError("scenes contain a non-SceneContract value")
    if [scene.ordinal for scene in typed_scenes] != list(range(len(typed_scenes))):
        raise SceneRuleError("scene ordinals must be contiguous from zero")
    if isinstance(source_ranges_utf16, (str, bytes)) or not isinstance(
        source_ranges_utf16, Sequence
    ):
        raise SceneRuleError("source_ranges_utf16 must be a sequence")

    resolved: list[UUID] = []
    for source_range in source_ranges_utf16:
        if type(source_range) is not Utf16Range:
            raise SceneRuleError("source ranges contain a non-Utf16Range value")
        matches = tuple(
            scene
            for scene in typed_scenes
            if scene.source_range_utf16 is not None
            and scene.source_range_utf16.start <= source_range.start
            and source_range.end_exclusive
            <= scene.source_range_utf16.end_exclusive
        )
        if len(matches) != 1:
            raise SceneRuleError(
                "each source range must belong to exactly one scene"
            )
        resolved.append(matches[0].scene_id)
    return tuple(resolved)


__all__ = [
    "SCENE_RULESET_VERSION",
    "SceneBoundaryHint",
    "SceneRuleError",
    "build_scene_contracts",
    "scan_scene_boundary_hints",
    "scene_ids_for_source_ranges",
]
