from __future__ import annotations

from hashlib import sha256
from typing import Any
from uuid import UUID

from backend.context_v4_loader import _manuscript_blocks
from backend.creative_data_models import (
    RevisionTimelineMapping,
    RevisionTimelineMappingHead,
    RevisionTimelineMappingSegment,
    StoryTimeline,
)
from backend.models import Document, DocumentRevision, DocumentWorkingCopy


def _uid(value: int) -> UUID:
    return UUID(int=value)


class _Session:
    def __init__(self, document: Document, rows: list[object]) -> None:
        self.document = document
        self.rows: dict[tuple[type[object], object], object] = {}
        self.segment: RevisionTimelineMappingSegment | None = None
        for row in rows:
            identity = getattr(row, "id", None)
            if identity is None:
                identity = getattr(row, "revision_id", None)
            if identity is None:
                identity = getattr(row, "document_id", None)
            self.rows[(type(row), identity)] = row
            if isinstance(row, RevisionTimelineMappingSegment):
                self.segment = row

    def scalars(self, statement: Any) -> list[object]:
        entity = statement.column_descriptions[0].get("entity")
        if entity is Document:
            return [self.document]
        if entity is RevisionTimelineMappingSegment:
            return [self.segment] if self.segment is not None else []
        return []

    def get(self, model: type[object], identity: object) -> object | None:
        return self.rows.get((model, identity))


def _timeline(value: int, *, primary: bool) -> StoryTimeline:
    return StoryTimeline(
        id=_uid(value),
        novel_id=_uid(1),
        timeline_key=f"line-{value}",
        name=f"时间线 {value}",
        normalized_name=f"时间线 {value}",
        timeline_kind="main" if primary else "branch",
        is_primary=primary,
        parent_timeline_id=None,
        fork_anchor_json={},
        lifecycle_state="active",
        position=value,
        version=1,
    )


def _chapter(title: str, content: str) -> tuple[Document, DocumentRevision, DocumentWorkingCopy]:
    document = Document(
        id=_uid(10),
        novel_id=_uid(1),
        kind="chapter",
        title=title,
        position=9_000,
        status="final",
        version=1,
    )
    revision = DocumentRevision(
        id=_uid(11),
        document_id=document.id,
        revision_number=1,
        content_markdown=content,
        content_text=content,
        content_hash=sha256(content.encode()).hexdigest(),
        source="manual",
    )
    working = DocumentWorkingCopy(
        document_id=document.id,
        base_revision_id=revision.id,
        draft_version=1,
        content_markdown=content,
        content_hash=revision.content_hash,
    )
    return document, revision, working


def test_empty_chapter_name_is_adapted_to_non_empty_context_title() -> None:
    document, revision, working = _chapter("", "正式正文")
    timeline = _timeline(20, primary=True)
    session = _Session(document, [revision, working])

    blocks = _manuscript_blocks(
        session,  # type: ignore[arg-type]
        document.novel_id,
        timeline.id,
        timelines=(timeline,),
    )

    assert [block.title for block in blocks] == ["第1章"]
    assert blocks[0].narrative_sequence == 1


def test_segment_suffix_participates_in_context_title_length_bound() -> None:
    document, revision, working = _chapter(
        "第十二章 · " + "潮" * 240,
        "分段正文",
    )
    mapping = RevisionTimelineMapping(
        id=_uid(30),
        novel_id=document.novel_id,
        document_id=document.id,
        revision_id=revision.id,
        source_content_hash=revision.content_hash,
        mapping_version=1,
        source_kind="manual",
        operation_key="mapping",
        operation_hash="1" * 64,
        mapping_digest="2" * 64,
    )
    head = RevisionTimelineMappingHead(
        revision_id=revision.id,
        document_id=document.id,
        novel_id=document.novel_id,
        source_content_hash=revision.content_hash,
        current_mapping_revision_id=mapping.id,
        version=1,
    )
    segment = RevisionTimelineMappingSegment(
        id=_uid(31),
        mapping_revision_id=mapping.id,
        novel_id=document.novel_id,
        timeline_id=_uid(20),
        ordinal=0,
        source_start=0,
        source_end=len(revision.content_text),
        story_sequence=1,
        story_time_json={},
    )
    main = _timeline(20, primary=True)
    branch = _timeline(21, primary=False)
    session = _Session(document, [revision, working, head, mapping, segment])

    blocks = _manuscript_blocks(
        session,  # type: ignore[arg-type]
        document.novel_id,
        main.id,
        timelines=(main, branch),
    )

    assert len(blocks) == 1
    assert blocks[0].title.startswith("第1章 潮")
    assert blocks[0].title.endswith(" · 片段 1")
    assert len(blocks[0].title) == 240
    assert "第十二章" not in blocks[0].title
