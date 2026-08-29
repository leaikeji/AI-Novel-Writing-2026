"""Deterministic V1 renderers and lossless semantic chunking."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Literal
from uuid import UUID


V1_RENDERER_VERSION = "semantic-v1-renderers/1"
V1_CHUNKER_VERSION = "semantic-char-chunker/1"


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


def render_v1_source(source: V1SourceInput) -> RenderedSource:
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
    text = "\n".join((*labels, "", body))
    digest = content_hash(text)
    fingerprint = content_hash(
        "\x1f".join(
            (
                V1_RENDERER_VERSION,
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
        renderer_version=V1_RENDERER_VERSION,
        content_hash=digest,
        source_fingerprint=fingerprint,
    )


def chunk_text(
    text: str,
    *,
    max_characters: int = 1800,
    overlap_characters: int = 180,
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
                normalized.rfind("\n\n", start + 1, hard_end + 1),
                normalized.rfind("\n", start + 1, hard_end + 1),
                normalized.rfind("。", start + 1, hard_end + 1),
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


def batch_chunks(
    chunks: tuple[RenderedChunk, ...], *, batch_size: int = 10
) -> tuple[tuple[RenderedChunk, ...], ...]:
    if not 1 <= batch_size <= 10:
        raise ValueError("batch_size must be between 1 and 10")
    return tuple(
        tuple(chunks[offset : offset + batch_size])
        for offset in range(0, len(chunks), batch_size)
    )
