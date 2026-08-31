"""Canonical volume/chapter ordering and derived-title contracts.

Stored titles are author-owned semantic names.  Ordinals are projections of
the current canonical tree and must never be persisted into those names.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Literal
from uuid import UUID


TitleKind = Literal["volume", "chapter"]

_ORDINAL_TOKEN = r"(?:\d+|[零〇一二三四五六七八九十百千万两]+)"
_BOUNDARY = r"(?:\s*[:：·—-]+\s*|\s+)"
_LEGACY_PREFIX = {
    "volume": re.compile(
        rf"^第\s*{_ORDINAL_TOKEN}\s*卷(?P<boundary>{_BOUNDARY}|$)"
    ),
    "chapter": re.compile(
        rf"^第\s*{_ORDINAL_TOKEN}\s*章(?P<boundary>{_BOUNDARY}|$)"
    ),
}
_DISPLAY_ORDINAL_PREFIX = re.compile(
    rf"^第\s*{_ORDINAL_TOKEN}\s*(?:卷|章)"
)


class VolumeChapterContractError(RuntimeError):
    """Stable structured domain error consumed by both HTTP API surfaces."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 422,
        current: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.current = current


def contract_error_detail(error: VolumeChapterContractError) -> dict[str, Any]:
    detail: dict[str, Any] = {"type": error.code, "message": str(error)}
    if error.current is not None:
        detail["current"] = error.current
    return detail


def semantic_title(raw_title: str | None, kind: TitleKind) -> str:
    """Trim and strip one legacy ordinal only at an unambiguous boundary."""

    title = (raw_title or "").strip()
    match = _LEGACY_PREFIX[kind].match(title)
    if match is None:
        return title
    return title[match.end() :].strip()


def display_volume_title(raw_title: str | None, ordinal: int) -> str:
    name = semantic_title(raw_title, "volume")
    return f"第{ordinal}卷" + (f" {name}" if name else "")


def display_chapter_title(raw_title: str | None, ordinal: int) -> str:
    name = semantic_title(raw_title, "chapter")
    return f"第{ordinal}章" + (f" {name}" if name else "")


def embedding_chapter_title(raw_title: str | None) -> str:
    """Return stable non-empty index text without a position-derived ordinal."""

    return semantic_title(raw_title, "chapter") or "章节正文"


def bound_contract_title(
    display_title: str,
    *,
    suffix: str = "",
    max_length: int = 240,
) -> str:
    """Bound the final title while preserving its ordinal prefix and suffix."""

    if max_length < 1:
        raise ValueError("max_length must be positive")
    ordinal_match = _DISPLAY_ORDINAL_PREFIX.match(display_title)
    if ordinal_match is None:
        raise ValueError("display_title must begin with a volume or chapter ordinal")
    available = max_length - len(suffix)
    if available < ordinal_match.end():
        raise ValueError("max_length cannot preserve both ordinal prefix and suffix")
    return display_title[:available].rstrip() + suffix


def context_chapter_title(
    raw_title: str | None,
    ordinal: int,
    *,
    suffix: str = "",
    max_length: int = 240,
) -> str:
    """Return the bounded, current display title required by runtime contracts."""

    return bound_contract_title(
        display_chapter_title(raw_title, ordinal),
        suffix=suffix,
        max_length=max_length,
    )


@dataclass(frozen=True, slots=True)
class CanonicalTree:
    volumes: tuple[Any, ...]
    chapters: tuple[Any, ...]
    volume_ordinals: dict[UUID, int]
    chapter_ordinals: dict[UUID, int]


def canonical_tree(
    volumes: Iterable[Any],
    documents: Iterable[Any],
) -> CanonicalTree:
    """Project real volumes first, then the virtual unassigned chapter group."""

    ordered_volumes = tuple(sorted(volumes, key=lambda item: (item.position, str(item.id))))
    chapter_rows = tuple(item for item in documents if item.kind == "chapter")
    by_volume: dict[UUID | None, list[Any]] = {item.id: [] for item in ordered_volumes}
    by_volume[None] = []
    for document in chapter_rows:
        # The legacy schema only constrains volume_id to an existing volume,
        # not to a volume in the same novel. New writes reject that state, but
        # reads must not make historical author content disappear.
        group_id = document.volume_id if document.volume_id in by_volume else None
        by_volume[group_id].append(document)
    for rows in by_volume.values():
        rows.sort(key=lambda item: (item.position, str(item.id)))
    ordered_chapters = tuple(
        document
        for volume in ordered_volumes
        for document in by_volume.get(volume.id, ())
    ) + tuple(by_volume.get(None, ()))
    return CanonicalTree(
        volumes=ordered_volumes,
        chapters=ordered_chapters,
        volume_ordinals={item.id: index for index, item in enumerate(ordered_volumes, 1)},
        chapter_ordinals={item.id: index for index, item in enumerate(ordered_chapters, 1)},
    )


def next_chapter_ordinal(tree: CanonicalTree, volume_id: UUID) -> int:
    if volume_id not in tree.volume_ordinals:
        raise KeyError(volume_id)
    before = 0
    in_target = 0
    target_ordinal = tree.volume_ordinals[volume_id]
    for document in tree.chapters:
        if document.volume_id == volume_id:
            in_target += 1
        elif document.volume_id is not None:
            ordinal = tree.volume_ordinals.get(document.volume_id)
            if ordinal is not None and ordinal < target_ordinal:
                before += 1
    return before + in_target + 1
