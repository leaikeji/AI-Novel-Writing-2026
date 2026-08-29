from ..contracts import EmbeddingCorpus

from .base import make_document, make_metadata, source_is_in_scope
from .contracts import RenderScope, RenderedCorpusDocument, TimelineRenderSource


TIMELINE_RENDERER_VERSION = "timeline/1"


class TimelineRendererV1:
    corpus = EmbeddingCorpus.TIMELINE
    renderer_id = "structured-timeline"
    renderer_version = TIMELINE_RENDERER_VERSION

    def render(
        self, source: TimelineRenderSource, scope: RenderScope
    ) -> RenderedCorpusDocument | None:
        if (
            source.parent_timeline_id is not None
            and source.parent_timeline_id not in scope.inheritance_path
        ):
            return None
        if not source_is_in_scope(
            source_novel_id=source.novel_id,
            source_timeline_id=source.timeline_id,
            source_story_sequence=source.story_sequence,
            source_visibility=source.visibility,
            scope=scope,
        ):
            return None
        metadata = make_metadata(
            corpus=self.corpus,
            novel_id=source.novel_id,
            source_type="timeline",
            source_id=source.source_id,
            source_revision_id=source.source_revision_id,
            source_version=source.source_version,
            timeline_id=source.timeline_id,
            narrative_sequence=source.story_sequence,
            visibility=source.visibility,
        )
        return make_document(
            renderer_id=self.renderer_id,
            renderer_version=self.renderer_version,
            metadata=metadata,
            text_lines=[
                ("语料类型", "时间线"),
                ("名称", source.name),
                ("时间线类型", source.timeline_kind),
                ("是否主线", source.is_primary),
                ("主继承父线", source.parent_timeline_name),
                ("分叉故事序列", source.fork_story_sequence),
                ("分叉锚点", source.fork_anchor_label),
            ],
        )
