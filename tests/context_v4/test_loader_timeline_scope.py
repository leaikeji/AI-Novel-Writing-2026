from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID

from backend.context_v4 import (
    ContextBudgetV2,
    NovelContextAssemblySnapshotV4,
    PerspectiveKind,
    PerspectiveV1,
    RetrievalPurpose,
    StoryPositionV3,
    assemble_novel_context,
)
from backend.context_v4_loader import _character_blocks, _manuscript_blocks
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
        rows: list[Any] | None = None,
    ) -> None:
        self.scalar_batches = {
            model: [list(batch) for batch in batches]
            for model, batches in (scalar_batches or {}).items()
        }
        self.rows: dict[tuple[type[Any], Any], Any] = {}
        for row in rows or []:
            identity = getattr(row, "id", None)
            if identity is None:
                identity = getattr(row, "revision_id", None)
            if identity is None:
                identity = getattr(row, "document_id", None)
            self.rows[(type(row), identity)] = row

    @staticmethod
    def _entity(statement: Any) -> type[Any]:
        entity = statement.column_descriptions[0].get("entity")
        assert entity is not None
        return entity

    def scalars(self, statement: Any) -> list[Any]:
        batches = self.scalar_batches.get(self._entity(statement), [])
        return batches.pop(0) if batches else []

    def get(self, model: type[Any], identity: Any) -> Any:
        return self.rows.get((model, identity))


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


def test_multi_timeline_character_loader_uses_exact_target_instance_only() -> None:
    target, target_revision = character_instance(31, 11, 131, label="目标线身份")
    sibling, sibling_revision = character_instance(32, 12, 132, label="兄弟线秘密")
    session = LoaderSession(
        scalar_batches={
            NovelCharacterRevision: [[root_revision()]],
            CharacterInstance: [[target, sibling]],
        },
        rows=[target_revision, sibling_revision],
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
    rows: list[Any] = []
    for (document, revision, working), (head, mapping, _) in zip(
        documents, mappings, strict=True
    ):
        rows.extend((revision, working, head, mapping))
    session = LoaderSession(
        scalar_batches={
            Document: [[item[0] for item in documents]],
            RevisionTimelineMappingSegment: [[item[2]] for item in mappings],
        },
        rows=rows,
    )

    blocks = _manuscript_blocks(
        session,
        uid(1),
        uid(11),
        timelines=(main, target, sibling),
    )

    assert [(block.content, block.timeline_id) for block in blocks] == [
        ("父线分叉前事实", uid(10)),
        ("目标线合法事实", uid(11)),
        # The parent post-fork segment cannot be inherited into the branch.
        ("兄弟线绝密事实", uid(12)),
    ]
    included = _assemble_manuscript(blocks, [main, target, sibling])
    assert included == ("父线分叉前事实", "目标线合法事实")


def test_multi_timeline_unmapped_revision_fails_closed_without_target_disguise() -> None:
    main = timeline(10, primary=True)
    target = timeline(11, parent=10, fork_sequence=10)
    document, revision, working = chapter(50, position=1, content="没有映射的正文")
    session = LoaderSession(
        scalar_batches={Document: [[document]]},
        rows=[revision, working],
    )

    blocks = _manuscript_blocks(
        session,
        uid(1),
        uid(11),
        timelines=(main, target),
    )

    assert all(block.timeline_id != uid(11) for block in blocks)
    assert "没有映射的正文" not in _assemble_manuscript(blocks, [main, target])


def test_single_timeline_identity_loader_keeps_full_current_revision() -> None:
    main = timeline(10, primary=True)
    document, revision, working = chapter(60, position=1, content="单线完整正文")
    session = LoaderSession(
        scalar_batches={Document: [[document]]},
        rows=[revision, working],
    )

    blocks = _manuscript_blocks(
        session,
        uid(1),
        uid(10),
        timelines=(main,),
    )

    assert len(blocks) == 1
    assert blocks[0].content == "单线完整正文"
    assert blocks[0].timeline_id == uid(10)
    assert blocks[0].narrative_sequence == 1
