"""Shared deterministic rendering primitives."""

from __future__ import annotations

from hashlib import sha256
from typing import Protocol
import unicodedata

from ..contracts import EmbeddingCorpus
from ...story_state.contracts import StoryVisibilityV1, VisibilityScope

from .contracts import (
    RenderedCorpusDocument,
    RenderedCorpusMetadata,
    RendererError,
    RendererErrorCode,
    RendererPerspective,
    RenderScope,
    StructuredRenderSource,
)


class StructuredCorpusRenderer(Protocol):
    corpus: EmbeddingCorpus
    renderer_id: str
    renderer_version: str

    def render(
        self, source: StructuredRenderSource, scope: RenderScope
    ) -> RenderedCorpusDocument | None: ...


def normalize_text(value: str) -> str:
    """Normalize without truncating or interpreting the source text."""

    normalized = unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")
    if "\x00" in normalized:
        raise ValueError("render source contains a null byte")
    lines = [" ".join(line.split()) for line in normalized.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def visible_in_scope(visibility: StoryVisibilityV1, scope: RenderScope) -> bool:
    if scope.perspective is RendererPerspective.AUTHOR:
        return True
    reveal_at = visibility.revealed_at_sequence
    if visibility.scope is not VisibilityScope.ALL and reveal_at is None:
        # Non-public information needs an explicit knowledge/reveal event before
        # it can enter a reader or character corpus.
        return False
    if reveal_at is not None:
        if scope.narrative_cutoff is None or reveal_at > scope.narrative_cutoff:
            return False
    if scope.perspective is RendererPerspective.READER:
        return visibility.scope in {VisibilityScope.ALL, VisibilityScope.READER}
    return visibility.scope is VisibilityScope.ALL or (
        visibility.scope is VisibilityScope.CHARACTER_INSTANCES
        and scope.observer_character_instance_id in visibility.character_instance_ids
    )


def source_is_in_scope(
    *,
    source_novel_id,
    source_timeline_id,
    source_story_sequence,
    source_visibility: StoryVisibilityV1,
    scope: RenderScope,
) -> bool:
    if source_novel_id != scope.novel_id:
        raise RendererError(
            RendererErrorCode.CROSS_NOVEL_SOURCE,
            "structured renderer source belongs to another novel",
        )
    if source_timeline_id not in scope.inheritance_path:
        return False
    if scope.narrative_cutoff is not None:
        if source_story_sequence is None:
            # Any cutoff-scoped render must not guess whether an unpositioned
            # source is already true at that point, including author views.
            return False
        if source_story_sequence > scope.narrative_cutoff:
            return False
    return visible_in_scope(source_visibility, scope)


def make_metadata(
    *,
    corpus: EmbeddingCorpus,
    novel_id,
    source_type,
    source_id,
    source_revision_id,
    source_version,
    timeline_id,
    character_instance_ids=(),
    narrative_sequence,
    visibility: StoryVisibilityV1,
) -> RenderedCorpusMetadata:
    return RenderedCorpusMetadata(
        corpus=corpus,
        novel_id=novel_id,
        source_type=source_type,
        source_id=source_id,
        source_revision_id=source_revision_id,
        source_version=source_version,
        timeline_id=timeline_id,
        character_instance_ids=character_instance_ids,
        narrative_sequence=narrative_sequence,
        visibility_scope=visibility.scope,
        visibility_character_instance_ids=visibility.character_instance_ids,
        revealed_at_sequence=visibility.revealed_at_sequence,
    )


def make_document(
    *,
    renderer_id: str,
    renderer_version: str,
    text_lines: list[tuple[str, str | int | bool | None]],
    metadata: RenderedCorpusMetadata,
) -> RenderedCorpusDocument:
    rendered_lines: list[str] = []
    for label, raw_value in text_lines:
        if raw_value is None:
            continue
        if isinstance(raw_value, bool):
            value = "是" if raw_value else "否"
        else:
            value = normalize_text(str(raw_value))
        if value:
            rendered_lines.append(f"{label}：{value}")
    text = "\n".join(rendered_lines)
    if not text:
        raise RendererError(
            RendererErrorCode.UNSUPPORTED_SOURCE,
            "renderer source has no allow-listed semantic text",
        )

    # Hash only explicit scalar fields in a fixed order.  Never stringify an
    # arbitrary dict or an ORM object.
    fingerprint_fields = (
        renderer_id,
        renderer_version,
        metadata.corpus.value,
        str(metadata.novel_id),
        metadata.source_type,
        str(metadata.source_id),
        str(metadata.source_revision_id or ""),
        str(metadata.source_version),
        str(metadata.timeline_id),
        ",".join(str(item) for item in metadata.character_instance_ids),
        str(metadata.narrative_sequence if metadata.narrative_sequence is not None else ""),
        metadata.visibility_scope.value,
        ",".join(str(item) for item in metadata.visibility_character_instance_ids),
        str(metadata.revealed_at_sequence if metadata.revealed_at_sequence is not None else ""),
        text,
    )
    content_hash = sha256("\x1f".join(fingerprint_fields).encode("utf-8")).hexdigest()
    return RenderedCorpusDocument(
        renderer_id=renderer_id,
        renderer_version=renderer_version,
        text=text,
        metadata=metadata,
        content_hash=content_hash,
    )
