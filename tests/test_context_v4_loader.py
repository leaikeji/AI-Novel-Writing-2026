from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from backend.context_v4 import (
    ContextBudgetV2,
    NovelContextAssemblySnapshotV4,
    PerspectiveKind,
    PerspectiveV1,
    RetrievalPurpose,
    StoryPositionV3,
    resolve_context_scope,
)
from backend.context_v4_loader import (
    TOKEN_ESTIMATOR_VERSION,
    _ChapterRevisionRef,
    _hydrate_manuscript_blocks,
    assemble_writing_context_from_db,
)
from backend.creative_data_models import (
    CharacterInstance,
    NovelAssetBinding,
    RevisionTimelineMapping,
    RevisionTimelineMappingHead,
    RevisionTimelineMappingSegment,
    StoryTimeline,
)
from backend.embedding.writing import WritingPosition
from backend.models import Document, DocumentRevision, DocumentWorkingCopy
from backend.story_state import StoryTimelineRecord


def _uid(value: int) -> UUID:
    return UUID(int=value)


NOW = datetime(2026, 9, 2, tzinfo=UTC)


class _Session:
    def __init__(self, rows: list[object]) -> None:
        self.rows: dict[tuple[type[object], object], object] = {}
        for row in rows:
            identity = getattr(row, "id", None)
            if identity is None:
                identity = getattr(row, "revision_id", None)
            if identity is None:
                identity = getattr(row, "document_id", None)
            self.rows[(type(row), identity)] = row

    def scalars(self, statement: Any) -> list[object]:
        entity = statement.column_descriptions[0].get("entity")
        return [
            row
            for (model, _), row in self.rows.items()
            if model is entity
        ]

    def scalar(self, statement: Any) -> object | None:
        return None


def _timeline(value: int, *, primary: bool) -> StoryTimeline:
    return StoryTimeline(
        id=_uid(value),
        novel_id=_uid(1),
        timeline_key=f"line-{value}",
        name=f"时间线 {value}",
        normalized_name=f"时间线 {value}",
        timeline_kind="main" if primary else "branch",
        is_primary=primary,
        parent_timeline_id=None if primary else _uid(20),
        fork_story_sequence=None if primary else 1,
        fork_anchor_json={},
        lifecycle_state="active",
        position=value,
        version=1,
        created_at=NOW,
        updated_at=NOW,
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


def _scope(timelines: tuple[StoryTimeline, ...], timeline_id: UUID) -> Any:
    return resolve_context_scope(
        NovelContextAssemblySnapshotV4(
            novel_id=_uid(1),
            purpose=RetrievalPurpose.REVIEW,
            position=StoryPositionV3(
                timeline_id=timeline_id,
                narrative_sequence=2,
                story_sequence_cutoff=2,
                timeline_mapping_version="map/1",
            ),
            perspective=PerspectiveV1(kind=PerspectiveKind.AUTHOR),
            budget=ContextBudgetV2(
                requested_provider_id="provider",
                requested_model_id="model",
                budget_provider_id="provider",
                budget_model_id="model",
                effective_context_window_tokens=100_000,
                reserved_output_tokens=1_000,
                reserved_prompt_tokens=1_000,
                fixed_overhead_tokens=100,
                estimator_version=TOKEN_ESTIMATOR_VERSION,
            ),
            timelines=tuple(
                StoryTimelineRecord.model_validate(item) for item in timelines
            ),
        )
    )


def _ref(document: Document, revision: DocumentRevision) -> _ChapterRevisionRef:
    return _ChapterRevisionRef(
        document_id=document.id,
        title=document.title,
        narrative_sequence=1,
        revision_id=revision.id,
        content_hash=revision.content_hash,
    )


def test_empty_chapter_name_is_adapted_to_non_empty_context_title() -> None:
    document, revision, _ = _chapter("", "正式正文")
    timeline = _timeline(20, primary=True)
    session = _Session([revision])

    blocks = _hydrate_manuscript_blocks(
        session,  # type: ignore[arg-type]
        novel_id=document.novel_id,
        timeline_id=timeline.id,
        timelines=(timeline,),
        scope=_scope((timeline,), timeline.id),
        refs=(_ref(document, revision),),
    )

    assert [block.title for block in blocks] == ["第1章"]
    assert blocks[0].narrative_sequence == 1


def test_segment_suffix_participates_in_context_title_length_bound() -> None:
    document, revision, _ = _chapter(
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
    session = _Session([revision, head, mapping, segment])

    blocks = _hydrate_manuscript_blocks(
        session,  # type: ignore[arg-type]
        novel_id=document.novel_id,
        timeline_id=main.id,
        timelines=(main, branch),
        scope=_scope((main, branch), main.id),
        refs=(_ref(document, revision),),
    )

    assert len(blocks) == 1
    assert blocks[0].title.startswith("第1章 潮")
    assert blocks[0].title.endswith(" · 片段 1")
    assert len(blocks[0].title) == 240
    assert "第十二章" not in blocks[0].title


class _EmptySingleTimelineSession:
    def __init__(self, timeline: StoryTimeline, document_id: UUID) -> None:
        self.timeline = timeline
        self.document_id = document_id
        self.statements: list[Any] = []

    def get(self, model: type[object], identity: object) -> object | None:
        if model.__name__ == "Novel":
            return object()
        return None

    def scalars(self, statement: Any) -> list[Any]:
        self.statements.append(statement)
        entity = statement.column_descriptions[0].get("entity")
        if entity is StoryTimeline:
            return [self.timeline]
        if entity in {CharacterInstance, NovelAssetBinding}:
            return []
        raise AssertionError(f"unexpected scalar query for {entity}")

    def scalar(self, statement: Any) -> Any:
        self.statements.append(statement)
        return None

    def execute(self, statement: Any) -> list[Any]:
        self.statements.append(statement)
        columns = set(statement.selected_columns.keys())
        if columns == {"document_id", "narrative_sequence"}:
            return [
                SimpleNamespace(
                    document_id=self.document_id,
                    narrative_sequence=1,
                )
            ]
        return []


def test_full_single_timeline_loader_freezes_a_v2_snapshot_without_unbounded_sources() -> None:
    timeline = _timeline(20, primary=True)
    document_id = _uid(10)
    session = _EmptySingleTimelineSession(timeline, document_id)
    position = WritingPosition(
        novel_id=_uid(1),
        document_id=document_id,
        title="第1章",
        narrative_sequence=1,
        timeline_id=timeline.id,
        story_sequence_cutoff=1,
        mapping_version="single-timeline-identity/1",
    )

    snapshot = assemble_writing_context_from_db(
        session,  # type: ignore[arg-type]
        position=position,
        purpose=RetrievalPurpose.CHAPTER_BODY,
        requested_provider_id="provider",
        requested_model_id="model",
        budget_provider_id="provider",
        budget_model_id="model",
        effective_context_window_tokens=16_384,
        reserved_output_tokens=2_048,
        private_assets=(),
    )

    assert snapshot["schema_version"] == "writing-context-snapshot/2"
    assert snapshot["context_policy_version"] == "context-source-policy/1"
    assert snapshot["envelope"]["current_story_facts"] == []
    assert snapshot["envelope"]["included_blocks"] == []
