"""Deterministic V1 renderers and lossless semantic chunking."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Literal
from uuid import UUID


LEGACY_V1_RENDERER_VERSION = "semantic-v1-renderers/1"
V1_RENDERER_VERSION = "semantic-v1-renderers/2"
CHUNKER_CANDIDATES = {
    # Read/build compatibility for immutable generations activated before VM34.
    # New candidates never select this version.
    "semantic-char-chunker/4": (256, 32),
    "semantic-char-chunker/5a": (512, 64),
    "semantic-char-chunker/5b": (800, 120),
}
V1_CHUNKER_VERSION = "semantic-char-chunker/5b"
V1_CHUNK_MAX_CHARACTERS, V1_CHUNK_OVERLAP_CHARACTERS = CHUNKER_CANDIDATES[
    V1_CHUNKER_VERSION
]
TOKEN_ESTIMATOR_VERSION = "unicode-char-estimate/1"


def content_hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def normalize_text(value: str) -> str:
    """Normalize line endings without changing meaningful whitespace."""

    return value.replace("\r\n", "\n").replace("\r", "\n")


def render_structured_setting(value: object) -> str:
    """Render approved setting data as labeled text, never as a JSON blob."""

    lines: list[str] = []

    def visit(item: object, path: tuple[str, ...]) -> None:
        if isinstance(item, dict):
            for key in sorted(item):
                if not isinstance(key, str) or not key.strip():
                    raise ValueError("setting keys must be non-empty strings")
                visit(item[key], (*path, key.strip()))
            return
        if isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, (*path, str(index + 1)))
            return
        if item is None:
            return
        if not isinstance(item, (str, int, float, bool)):
            raise ValueError("setting contains an unsupported value")
        label = " / ".join(path) if path else "设定"
        lines.append(f"{label}: {normalize_text(str(item))}")

    visit(value, ())
    if not lines:
        raise ValueError("setting content must not be empty")
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class V1SourceInput:
    corpus: Literal["manuscript", "planning", "private_asset"]
    source_type: Literal[
        "chapter_revision", "outline_revision", "setting_revision", "private_asset_version"
    ]
    source_entity_id: UUID
    source_revision_id: UUID
    title: str
    content: str
    usage_policy: str | None = None


@dataclass(frozen=True, slots=True)
class RenderedSource:
    corpus: str
    source_type: str
    source_entity_id: UUID
    source_revision_id: UUID
    text: str
    header: str
    body: str
    renderer_version: str
    content_hash: str
    source_fingerprint: str


@dataclass(frozen=True, slots=True)
class RenderedChunk:
    index: int
    source_start: int
    source_end: int
    text: str
    content_hash: str
    chunker_version: str = V1_CHUNKER_VERSION


def estimate_token_count(value: str) -> int:
    """Return a conservative, explicitly labelled estimate for Chinese prose."""

    return max(1, (len(value) + 1) // 2)


def render_v1_source(
    source: V1SourceInput,
    *,
    renderer_version: str = V1_RENDERER_VERSION,
) -> RenderedSource:
    title = normalize_text(source.title).strip()
    body = normalize_text(source.content)
    if not title:
        raise ValueError("source title must not be blank")
    if not body.strip():
        raise ValueError("source content must not be blank")
    if source.corpus == "private_asset" and source.usage_policy not in {
        "required",
        "preferred",
        "context_only",
    }:
        raise ValueError("private assets must be bound with an indexable policy")
    labels = [f"语料: {source.corpus}", f"标题: {title}"]
    if source.usage_policy is not None:
        labels.append(f"使用策略: {source.usage_policy}")
    if renderer_version not in {LEGACY_V1_RENDERER_VERSION, V1_RENDERER_VERSION}:
        raise ValueError("unknown renderer version")
    header = "\n".join(labels)
    text = f"{header}\n\n{body}"
    digest = content_hash(text)
    fingerprint = content_hash(
        "\x1f".join(
            (
                renderer_version,
                source.corpus,
                source.source_type,
                str(source.source_entity_id),
                str(source.source_revision_id),
                digest,
            )
        )
    )
    return RenderedSource(
        corpus=source.corpus,
        source_type=source.source_type,
        source_entity_id=source.source_entity_id,
        source_revision_id=source.source_revision_id,
        text=text,
        header=header,
        body=body,
        renderer_version=renderer_version,
        content_hash=digest,
        source_fingerprint=fingerprint,
    )


def chunk_text(
    text: str,
    *,
    max_characters: int = V1_CHUNK_MAX_CHARACTERS,
    overlap_characters: int = V1_CHUNK_OVERLAP_CHARACTERS,
) -> tuple[RenderedChunk, ...]:
    """Return complete, ordered chunks; no suffix is silently discarded."""

    normalized = normalize_text(text)
    if not normalized:
        return ()
    if max_characters < 256:
        raise ValueError("max_characters must be at least 256")
    if overlap_characters < 0 or overlap_characters >= max_characters:
        raise ValueError("overlap_characters must be smaller than max_characters")
    chunks: list[RenderedChunk] = []
    start = 0
    while start < len(normalized):
        hard_end = min(len(normalized), start + max_characters)
        end = hard_end
        if hard_end < len(normalized):
            candidates = (
                normalized.rfind("\n\n", start + 1, hard_end),
                normalized.rfind("\n", start + 1, hard_end),
                normalized.rfind("。", start + 1, hard_end),
            )
            boundary = max(candidates)
            if boundary >= start + max_characters // 2:
                end = boundary + (1 if normalized[boundary] == "。" else 0)
        piece = normalized[start:end]
        if not piece:
            raise RuntimeError("chunker made no progress")
        chunks.append(
            RenderedChunk(
                index=len(chunks),
                source_start=start,
                source_end=end,
                text=piece,
                content_hash=content_hash(piece),
            )
        )
        if end == len(normalized):
            break
        start = max(start + 1, end - overlap_characters)
    return tuple(chunks)


def chunk_rendered_source(
    source: RenderedSource,
    *,
    chunker_version: str = V1_CHUNKER_VERSION,
) -> tuple[RenderedChunk, ...]:
    """Chunk a source body while repeating provenance labels in every chunk."""

    try:
        max_characters, overlap_characters = CHUNKER_CANDIDATES[chunker_version]
    except KeyError as error:
        raise ValueError("unknown chunker version") from error
    legacy = chunker_version == "semantic-char-chunker/4"
    body_chunks = chunk_text(
        source.text if legacy else source.body,
        max_characters=max_characters,
        overlap_characters=overlap_characters,
    )
    prefix = "" if legacy else f"{source.header}\n分块版本: {chunker_version}\n\n"
    return tuple(
        RenderedChunk(
            index=item.index,
            source_start=item.source_start,
            source_end=item.source_end,
            text=f"{prefix}{item.text}",
            content_hash=content_hash(f"{prefix}{item.text}"),
            chunker_version=chunker_version,
        )
        for item in body_chunks
    )


def batch_chunks(
    chunks: tuple[RenderedChunk, ...], *, batch_size: int = 10
) -> tuple[tuple[RenderedChunk, ...], ...]:
    if not 1 <= batch_size <= 10:
        raise ValueError("batch_size must be between 1 and 10")
    return tuple(
        tuple(chunks[offset : offset + batch_size])
        for offset in range(0, len(chunks), batch_size)
    )
