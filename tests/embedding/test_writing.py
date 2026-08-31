from __future__ import annotations

from typing import Any
from uuid import uuid4

from backend.creative_data_models import StoryTimeline
from backend.embedding.writing import resolve_writing_position
from backend.models import Document


class _Session:
    def __init__(
        self,
        target: Document,
        ordered_document_ids: tuple[object, ...],
        timeline: StoryTimeline,
    ) -> None:
        self.target = target
        self.ordered_document_ids = ordered_document_ids
        self.timeline = timeline

    def get(self, model: type[object], identity: object) -> object | None:
        if model is Document and identity == self.target.id:
            return self.target
        return None

    def scalars(self, statement: Any) -> tuple[object, ...]:
        sql = str(statement)
        if "story_timelines" in sql:
            return (self.timeline,)
        return self.ordered_document_ids


def test_writing_position_uses_canonical_ordinal_and_derived_non_empty_title() -> None:
    novel_id = uuid4()
    target = Document(
        id=uuid4(),
        novel_id=novel_id,
        volume_id=uuid4(),
        kind="chapter",
        title="",
        position=9_000,
        status="draft",
        version=1,
    )
    timeline = StoryTimeline(
        id=uuid4(),
        novel_id=novel_id,
        timeline_key="main",
        name="主线",
        normalized_name="主线",
        timeline_kind="main",
        is_primary=True,
        parent_timeline_id=None,
        fork_anchor_json={},
        lifecycle_state="active",
        position=1,
        version=1,
    )
    session = _Session(target, (uuid4(), target.id, uuid4()), timeline)

    position = resolve_writing_position(session, target.id)  # type: ignore[arg-type]

    assert position.narrative_sequence == 2
    assert position.story_sequence_cutoff == 2
    assert position.title == "第2章"
