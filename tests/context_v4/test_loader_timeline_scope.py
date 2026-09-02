from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID

import pytest

from backend.context_v4 import (
    ContextAssemblyError,
    ContextAssemblyErrorCode,
    ContextBudgetV2,
    NovelContextAssemblySnapshotV4,
    PerspectiveKind,
    PerspectiveV1,
    RetrievalPurpose,
    StoryPositionV3,
    assemble_novel_context,
    resolve_context_scope,
)
from backend.context_v4_loader import (
    MAX_MANUSCRIPT_EVIDENCE,
    _ChapterRevisionRef,
    _character_blocks,
    _hydrate_manuscript_blocks,
)
from backend.context_v4_loader import TOKEN_ESTIMATOR_VERSION
from backend.creative_data_models import (
    CharacterInstance,
    CharacterInstanceRevision,
    NovelCharacterRevision,
    RevisionTimelineMapping,
    RevisionTimelineMappingHead,
    RevisionTimelineMappingSegment,
    StoryTimeline,
)
from backend.models import Document, DocumentRevision, DocumentWorkingCopy
from backend.story_state import StoryTimelineRecord


NOW = datetime(2026, 8, 29, tzinfo=UTC)


def uid(value: int) -> UUID:
    return UUID(int=value)


class LoaderSession:
    def __init__(
        self,
        *,
        scalar_batches: dict[type[Any], list[list[Any]]] | None = None,
    ) -> None:
        self.scalar_batches = {
            model: [list(batch) for batch in batches]
            for model, batches in (scalar_batches or {}).items()
        }

    @staticmethod
    def _entity(statement: Any) -> type[Any]:
        entity = statement.column_descriptions[0].get("entity")
        assert entity is not None
        return entity

    def scalars(self, statement: Any) -> list[Any]:
        batches = self.scalar_batches.get(self._entity(statement), [])
        return batches.pop(0) if batches else []

    def scalar(self, statement: Any) -> Any:
        return None


def timeline(
    value: int,
    *,
    parent: int | None = None,
    fork_sequence: int | None = None,
    primary: bool = False,
) -> StoryTimeline:
    return StoryTimeline(
        id=uid(value),
        novel_id=uid(1),
        timeline_key=f"line-{value}",
        name=f"时间线 {value}",
        normalized_name=f"时间线 {value}",
        timeline_kind="main" if parent is None else "branch",
        is_primary=primary,
        parent_timeline_id=uid(parent) if parent is not None else None,
        fork_story_sequence=fork_sequence,
        fork_anchor_json={},
        lifecycle_state="active",
        position=value,
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )


def root_revision() -> NovelCharacterRevision:
    return NovelCharacterRevision(
        id=uid(100),
        novel_id=uid(1),
        character_id=uid(20),
        character_version=1,
        role_type="protagonist",
        name="林岚",
        description="侦探",
        details_json={},
        lifecycle_state="active",
        position=1,
    )


def character_instance(
    value: int,
    timeline_id: int,
    revision_id: int,
    *,
    label: str,
) -> tuple[CharacterInstance, CharacterInstanceRevision]:
    instance = CharacterInstance(
        id=uid(value),
        novel_id=uid(1),
        character_id=uid(20),
        origin_timeline_id=uid(timeline_id),
        continuity_kind="native" if timeline_id == 10 else "derived",
        derived_from_instance_id=None if timeline_id == 10 else uid(30),
        display_label=label,
        current_revision_id=uid(revision_id),
        lifecycle_state="active",
        version=1,
    )
    revision = CharacterInstanceRevision(
        id=uid(revision_id),
        novel_id=uid(1),
        character_instance_id=instance.id,
        revision_number=1,
        source_kind="manual",
        operation_key=f"profile-{revision_id}",
        operation_hash=f"{revision_id:064x}",
        profile_schema_version=2,
        profile_json={"true_identity": label},
        change_set_json={},
        content_hash=f"{revision_id + 1:064x}",
    )
    return instance, revision


def chapter(
    value: int,
    *,
    position: int,
    content: str,
) -> tuple[Document, DocumentRevision, DocumentWorkingCopy]:
    document = Document(
        id=uid(value),
        novel_id=uid(1),
        kind="chapter",
        title=f"第 {position} 章",
        position=position,
        status="final",
        version=1,
    )
    revision = DocumentRevision(
        id=uid(value + 100),
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


def mapped_revision(
    document: Document,
    revision: DocumentRevision,
    *,
    mapping_id: int,
    timeline_id: int,
    story_sequence: int,
) -> tuple[
    RevisionTimelineMappingHead,
    RevisionTimelineMapping,
    RevisionTimelineMappingSegment,
]:
    mapping = RevisionTimelineMapping(
        id=uid(mapping_id),
        novel_id=uid(1),
        document_id=document.id,
        revision_id=revision.id,
        source_content_hash=revision.content_hash,
        mapping_version=1,
        source_kind="manual",
        operation_key=f"mapping-{mapping_id}",
        operation_hash=f"{mapping_id:064x}",
        mapping_digest=f"{mapping_id + 1:064x}",
    )
    head = RevisionTimelineMappingHead(
        revision_id=revision.id,
        document_id=document.id,
        novel_id=uid(1),
        source_content_hash=revision.content_hash,
        current_mapping_revision_id=mapping.id,
        version=1,
    )
    segment = RevisionTimelineMappingSegment(
        id=uid(mapping_id + 100),
        mapping_revision_id=mapping.id,
        novel_id=uid(1),
        timeline_id=uid(timeline_id),
        ordinal=0,
        source_start=0,
        source_end=len(revision.content_text),
        story_sequence=story_sequence,
        story_time_json={},
    )
    return head, mapping, segment


def _assemble_manuscript(
    blocks: list[Any], timelines: list[StoryTimeline]
) -> tuple[str, ...]:
    envelope = assemble_novel_context(
        NovelContextAssemblySnapshotV4(
            novel_id=uid(1),
            purpose=RetrievalPurpose.REVIEW,
            position=StoryPositionV3(
                timeline_id=uid(11),
                narrative_sequence=4,
                story_sequence_cutoff=20,
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
            timelines=tuple(StoryTimelineRecord.model_validate(item) for item in timelines),
            facts=(),
            event_links=(),
            source_revision_validity={},
            blocks=tuple(blocks),
        )
    )
    return tuple(
        block.content
        for block in envelope.included_blocks
        if block.section.value == "manuscript"
    )


def _resolved_scope(timelines: list[StoryTimeline], *, timeline_id: int) -> Any:
    snapshot = NovelContextAssemblySnapshotV4(
        novel_id=uid(1),
        purpose=RetrievalPurpose.REVIEW,
        position=StoryPositionV3(
            timeline_id=uid(timeline_id),
            narrative_sequence=5,
            story_sequence_cutoff=20,
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
        timelines=tuple(StoryTimelineRecord.model_validate(item) for item in timelines),
    )
    return resolve_context_scope(snapshot)


def _ref(item: tuple[Document, DocumentRevision, DocumentWorkingCopy]) -> _ChapterRevisionRef:
    document, revision, _ = item
    return _ChapterRevisionRef(
        document_id=document.id,
        title=document.title,
        narrative_sequence=document.position,
        revision_id=revision.id,
        content_hash=revision.content_hash,
    )


def test_multi_timeline_character_loader_uses_exact_target_instance_only() -> None:
    target, target_revision = character_instance(31, 11, 131, label="目标线身份")
    session = LoaderSession(
        scalar_batches={
            CharacterInstance: [[target.id], [target]],
            NovelCharacterRevision: [[root_revision()]],
            CharacterInstanceRevision: [[target_revision]],
        },
    )

    blocks = _character_blocks(session, uid(1), timeline_id=uid(11))

    assert [block.source_id for block in blocks] == [target.id]
    assert blocks[0].timeline_id == uid(11)
    assert "目标线身份" in blocks[0].content
    assert all("兄弟线秘密" not in block.content for block in blocks)


def test_multi_timeline_manuscript_loader_preserves_mapping_and_excludes_sibling() -> None:
    main = timeline(10, primary=True)
    target = timeline(11, parent=10, fork_sequence=10)
    sibling = timeline(12, parent=10, fork_sequence=10)
    documents = [
        chapter(40, position=1, content="父线分叉前事实"),
        chapter(41, position=2, content="目标线合法事实"),
        chapter(42, position=3, content="父线分叉后事实"),
        chapter(43, position=4, content="兄弟线绝密事实"),
    ]
    mappings = [
        mapped_revision(doc, rev, mapping_id=200 + index, timeline_id=line, story_sequence=seq)
        for index, ((doc, rev, _), line, seq) in enumerate(
            zip(documents, (10, 11, 10, 12), (5, 12, 11, 12), strict=True)
        )
    ]
    session = LoaderSession(
        scalar_batches={
            RevisionTimelineMappingHead: [[item[0] for item in mappings]],
            RevisionTimelineMapping: [[item[1] for item in mappings]],
            RevisionTimelineMappingSegment: [[mappings[0][2], mappings[1][2]]],
            DocumentRevision: [[documents[0][1], documents[1][1]]],
        },
    )

    blocks = _hydrate_manuscript_blocks(
        session,
        novel_id=uid(1),
        timeline_id=uid(11),
        timelines=(main, target, sibling),
        scope=_resolved_scope([main, target, sibling], timeline_id=11),
        refs=tuple(_ref(item) for item in documents),
    )

    assert [(block.content, block.timeline_id) for block in blocks] == [
        ("父线分叉前事实", uid(10)),
        ("目标线合法事实", uid(11)),
    ]
    # Parent post-fork and sibling segments are removed before body hydration.
    included = _assemble_manuscript(blocks, [main, target, sibling])
    assert included == ("父线分叉前事实", "目标线合法事实")


def test_multi_timeline_unmapped_revision_fails_closed_without_target_disguise() -> None:
    main = timeline(10, primary=True)
    target = timeline(11, parent=10, fork_sequence=10)
    document, revision, working = chapter(50, position=1, content="没有映射的正文")
    session = LoaderSession(scalar_batches={RevisionTimelineMappingHead: [[]]})

    with pytest.raises(ContextAssemblyError) as captured:
        _hydrate_manuscript_blocks(
            session,
            novel_id=uid(1),
            timeline_id=uid(11),
            timelines=(main, target),
            scope=_resolved_scope([main, target], timeline_id=11),
            refs=(_ref((document, revision, working)),),
        )

    assert captured.value.code is ContextAssemblyErrorCode.CONTEXT_SELECTION_INCOMPLETE


def test_single_timeline_identity_loader_keeps_full_current_revision() -> None:
    main = timeline(10, primary=True)
    document, revision, working = chapter(60, position=1, content="单线完整正文")
    session = LoaderSession(scalar_batches={DocumentRevision: [[revision]]})

    blocks = _hydrate_manuscript_blocks(
        session,
        novel_id=uid(1),
        timeline_id=uid(10),
        timelines=(main,),
        scope=_resolved_scope([main], timeline_id=10),
        refs=(_ref((document, revision, working)),),
    )

    assert len(blocks) == 1
    assert blocks[0].content == "单线完整正文"
    assert blocks[0].timeline_id == uid(10)
    assert blocks[0].narrative_sequence == 1


def test_mapped_manuscript_segments_use_cap_plus_one_and_fail_before_body_hydration() -> None:
    main = timeline(10, primary=True)
    target = timeline(11, parent=10, fork_sequence=10)
    document, revision, working = chapter(
        70,
        position=1,
        content="字" * (MAX_MANUSCRIPT_EVIDENCE + 1),
    )
    head, mapping, _ = mapped_revision(
        document,
        revision,
        mapping_id=300,
        timeline_id=11,
        story_sequence=1,
    )
    segments = [
        RevisionTimelineMappingSegment(
            id=uid(500 + index),
            mapping_revision_id=mapping.id,
            novel_id=uid(1),
            timeline_id=uid(11),
            ordinal=index,
            source_start=index,
            source_end=index + 1,
            story_sequence=1,
            story_time_json={},
        )
        for index in range(MAX_MANUSCRIPT_EVIDENCE + 1)
    ]
    session = LoaderSession(
        scalar_batches={
            RevisionTimelineMappingHead: [[head]],
            RevisionTimelineMapping: [[mapping]],
            RevisionTimelineMappingSegment: [segments],
        }
    )

    with pytest.raises(ContextAssemblyError) as captured:
        _hydrate_manuscript_blocks(
            session,
            novel_id=uid(1),
            timeline_id=uid(11),
            timelines=(main, target),
            scope=_resolved_scope([main, target], timeline_id=11),
            refs=(_ref((document, revision, working)),),
        )

    assert captured.value.code is ContextAssemblyErrorCode.CONTEXT_SELECTION_INCOMPLETE
    assert captured.value.details["candidate_count"] == MAX_MANUSCRIPT_EVIDENCE + 1
    assert session.scalar_batches.get(DocumentRevision) is None
