from ..contracts import EmbeddingCorpus
from ...story_state.contracts import (
    ForeshadowEventDetailsV1,
    KnowledgeEventDetailsV1,
    StoryFactStatus,
    StoryTimeDetailsV1,
    StorylineEventDetailsV1,
)

from .base import make_document, make_metadata, source_is_in_scope
from .contracts import RenderScope, RenderedCorpusDocument, StoryEventRenderSource


STORY_EVENT_RENDERER_VERSION = "story-event/1"


def _detail_lines(source: StoryEventRenderSource) -> list[tuple[str, str | int | None]]:
    details = source.fact.details
    if isinstance(details, StorylineEventDetailsV1):
        return [("线路事件", details.event)]
    if isinstance(details, ForeshadowEventDetailsV1):
        return [("伏笔动作", details.event), ("事件说明", details.note)]
    if isinstance(details, KnowledgeEventDetailsV1):
        return [("知识动作", details.operation), ("知识键", details.knowledge_key)]
    if isinstance(details, StoryTimeDetailsV1):
        lines: list[tuple[str, str | int | None]] = [("时间转换", details.transition)]
        if details.from_time is not None:
            lines.extend(
                [
                    ("起始故事时间", details.from_time.label),
                    ("起始下界", details.from_time.lower_bound),
                    ("起始上界", details.from_time.upper_bound),
                ]
            )
        if details.to_time is not None:
            lines.extend(
                [
                    ("目标故事时间", details.to_time.label),
                    ("目标下界", details.to_time.lower_bound),
                    ("目标上界", details.to_time.upper_bound),
                ]
            )
        return lines
    # Character/relationship/world/general values are represented by the
    # validated object_text. Nested JSON values are intentionally not dumped.
    return []


class StoryEventRendererV1:
    corpus = EmbeddingCorpus.STORY_EVENT
    renderer_id = "structured-story-event"
    renderer_version = STORY_EVENT_RENDERER_VERSION

    def render(
        self, source: StoryEventRenderSource, scope: RenderScope
    ) -> RenderedCorpusDocument | None:
        fact = source.fact
        if fact.status not in {StoryFactStatus.ACTIVE, StoryFactStatus.SOURCE_RESTORED}:
            return None
        if not source_is_in_scope(
            source_novel_id=source.novel_id,
            source_timeline_id=fact.timeline_id,
            source_story_sequence=fact.story_sequence,
            source_visibility=fact.visibility_json,
            scope=scope,
        ):
            return None
        character_instance_ids = (
            (fact.character_instance_id,) if fact.character_instance_id is not None else ()
        )
        metadata = make_metadata(
            corpus=self.corpus,
            novel_id=source.novel_id,
            source_type="story_fact",
            source_id=fact.id,
            source_revision_id=fact.source_revision_id,
            source_version=2,
            timeline_id=fact.timeline_id,
            character_instance_ids=character_instance_ids,
            narrative_sequence=fact.story_sequence,
            visibility=fact.visibility_json,
        )
        return make_document(
            renderer_id=self.renderer_id,
            renderer_version=self.renderer_version,
            metadata=metadata,
            text_lines=[
                ("语料类型", "故事事件"),
                ("事实类型", fact.fact_type.value),
                ("维度", fact.dimension),
                ("事件动作", fact.event_kind),
                ("主体", fact.subject),
                ("谓词", fact.predicate),
                ("事实内容", fact.object_text),
                *_detail_lines(source),
            ],
        )
