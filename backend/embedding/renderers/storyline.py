from ..contracts import EmbeddingCorpus

from .base import make_document, make_metadata, source_is_in_scope
from .contracts import RenderScope, RenderedCorpusDocument, StorylineRenderSource


STORYLINE_RENDERER_VERSION = "storyline/1"


class StorylineRendererV1:
    corpus = EmbeddingCorpus.STORYLINE
    renderer_id = "structured-storyline"
    renderer_version = STORYLINE_RENDERER_VERSION

    def render(
        self, source: StorylineRenderSource, scope: RenderScope
    ) -> RenderedCorpusDocument | None:
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
            source_type="storyline",
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
                ("语料类型", "故事线"),
                ("标题", source.title),
                ("线路类别", source.storyline_type),
                ("作者规划状态", source.planned_status),
                ("当前位置状态", source.projected_status),
                ("作者定义", source.description),
            ],
        )
