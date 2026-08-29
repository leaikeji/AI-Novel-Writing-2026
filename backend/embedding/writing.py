"""Best-effort semantic retrieval for the writing production path.

The adapter deliberately freezes only redacted provider evidence and selected
source snippets.  Query vectors, credentials and full query text are never
persisted by this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..creative_data_models import (
    RevisionTimelineMappingHead,
    RevisionTimelineMappingSegment,
    StoryTimeline,
)
from ..models import Document, DocumentWorkingCopy

from .api import semantic_search
from .contracts import (
    EmbeddingCorpus,
    RetrievalPurpose,
    SemanticPerspective,
    SemanticSearchRequest,
)


WRITING_RETRIEVAL_POLICY_VERSION = "writing-retrieval/2"


class WritingTimelineMappingRequired(ValueError):
    code = "timeline_mapping_required"


@dataclass(frozen=True, slots=True)
class WritingPosition:
    novel_id: UUID
    document_id: UUID
    title: str
    narrative_sequence: int
    timeline_id: UUID
    story_sequence_cutoff: int
    mapping_version: str


def resolve_writing_position(session: Session, document_id: UUID) -> WritingPosition:
    """Resolve the independent narrative/story coordinates without guessing."""

    document = session.get(Document, document_id)
    if document is None or document.kind != "chapter":
        raise ValueError("chapter document is required")
    narrative_sequence = int(
        session.scalar(
            select(func.count()).select_from(Document).where(
                Document.novel_id == document.novel_id,
                Document.kind == "chapter",
                Document.position <= document.position,
            )
        )
        or 0
    )
    timelines = tuple(
        session.scalars(
            select(StoryTimeline).where(
                StoryTimeline.novel_id == document.novel_id,
                StoryTimeline.lifecycle_state == "active",
            )
        )
    )
    if len(timelines) == 1:
        return WritingPosition(
            novel_id=document.novel_id,
            document_id=document.id,
            title=document.title,
            narrative_sequence=narrative_sequence,
            timeline_id=timelines[0].id,
            story_sequence_cutoff=narrative_sequence,
            mapping_version="single-timeline-identity/1",
        )
    working = session.get(DocumentWorkingCopy, document.id)
    head = (
        session.get(RevisionTimelineMappingHead, working.base_revision_id)
        if working is not None and working.base_revision_id is not None
        else None
    )
    segments = (
        tuple(
            session.scalars(
                select(RevisionTimelineMappingSegment).where(
                    RevisionTimelineMappingSegment.mapping_revision_id
                    == head.current_mapping_revision_id
                )
            )
        )
        if head is not None
        else ()
    )
    timeline_ids = {item.timeline_id for item in segments}
    story_sequences = {
        int(item.story_sequence)
        for item in segments
        if item.story_sequence is not None
    }
    if len(timeline_ids) != 1 or not story_sequences:
        raise WritingTimelineMappingRequired(
            "multi-timeline writing requires one explicit current revision mapping"
        )
    return WritingPosition(
        novel_id=document.novel_id,
        document_id=document.id,
        title=document.title,
        narrative_sequence=narrative_sequence,
        timeline_id=next(iter(timeline_ids)),
        story_sequence_cutoff=max(story_sequences),
        mapping_version=f"revision-timeline-mapping/{head.version}",
    )


def retrieval_purpose_for_selection(
    operation: str,
    *,
    use_novel_context: bool = False,
) -> RetrievalPurpose | None:
    """Return the explicit operation matrix; never infer intent from text."""

    values = {
        "rewrite": RetrievalPurpose.SELECTION_REWRITE,
        "expand": RetrievalPurpose.SELECTION_EXPAND,
        "dialogue": RetrievalPurpose.SELECTION_DIALOGUE,
        "review": RetrievalPurpose.SELECTION_REVIEW,
    }
    if operation == "custom":
        return RetrievalPurpose.SELECTION_CUSTOM if use_novel_context else None
    return values.get(operation)


def deterministic_query(
    *,
    purpose: RetrievalPurpose,
    title: str = "",
    outline: str = "",
    expectation: str = "",
    selection: str = "",
    before: str = "",
    after: str = "",
    instruction: str = "",
) -> str:
    """Render a bounded query without a second model or keyword routing."""

    parts = [
        f"写作操作：{purpose.value}",
        f"目标：{title.strip()}" if title.strip() else "",
        f"章纲：{outline.strip()}" if outline.strip() else "",
        f"本章要求：{expectation.strip()}" if expectation.strip() else "",
        f"选区：{selection.strip()}" if selection.strip() else "",
        f"选区前文：{before.strip()}" if before.strip() else "",
        f"选区后文：{after.strip()}" if after.strip() else "",
        f"作者指令：{instruction.strip()}" if instruction.strip() else "",
    ]
    query = "\n".join(item for item in parts if item)
    return query[:4000]


def _degraded_snapshot(reason: str) -> dict[str, Any]:
    return {
        "schema_version": "writing-retrieval-snapshot/1",
        "retrieval_policy_version": WRITING_RETRIEVAL_POLICY_VERSION,
        "mode": "lexical_only",
        "generation_id": None,
        "index_version": None,
        "hits": [],
        "provider_request_id": None,
        "token_count": None,
        "latency_ms": None,
        "degraded_reason": reason[:96],
        "omission_summary": [],
    }


async def retrieve_for_writing(
    session: Session,
    *,
    novel_id: UUID,
    purpose: RetrievalPurpose,
    query: str,
    timeline_id: UUID | None = None,
    narrative_sequence: int | None = None,
    story_sequence_cutoff: int | None = None,
    top_k: int = 10,
) -> dict[str, Any]:
    """Run scope-first retrieval and return an immutable, prompt-safe snapshot.

    Any retrieval failure is represented as a local degradation and never
    blocks writing.  ``context_overflow`` remains the responsibility of the
    Context V4 assembler because required author inputs may not be dropped.
    """

    try:
        result = await semantic_search(
            novel_id,
            SemanticSearchRequest(
                query=query,
                retrieval_purpose=purpose,
                corpora=(
                    EmbeddingCorpus.MANUSCRIPT,
                    EmbeddingCorpus.PLANNING,
                    EmbeddingCorpus.PRIVATE_ASSET,
                ),
                top_k=top_k,
                timeline_id=timeline_id,
                narrative_sequence=narrative_sequence,
                story_sequence_cutoff=story_sequence_cutoff,
                perspective=SemanticPerspective(),
            ),
            session,
        )
    except Exception as error:
        code = getattr(error, "code", None)
        if not isinstance(code, str):
            code = "semantic_retrieval_unavailable"
        return _degraded_snapshot(code)
    return {
        "schema_version": "writing-retrieval-snapshot/1",
        "retrieval_policy_version": result.get(
            "retrieval_policy_version", WRITING_RETRIEVAL_POLICY_VERSION
        ),
        "mode": result.get("mode", "lexical_only"),
        "generation_id": result.get("generation_id"),
        "index_version": result.get("index_version"),
        "hits": result.get("hits", []),
        "provider_request_id": result.get("provider_request_id"),
        "token_count": result.get("token_count"),
        "latency_ms": result.get("latency_ms"),
        "degraded_reason": result.get("degraded_reason"),
        "omission_summary": result.get("omission_summary", []),
    }
