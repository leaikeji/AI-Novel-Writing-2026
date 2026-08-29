from ..contracts import EmbeddingCorpus

from .base import make_document, make_metadata, source_is_in_scope
from .contracts import ForeshadowRenderSource, RenderScope, RenderedCorpusDocument


FORESHADOW_RENDERER_VERSION = "foreshadow/1"


class ForeshadowRendererV1:
    corpus = EmbeddingCorpus.FORESHADOW
    renderer_id = "structured-foreshadow"
    renderer_version = FORESHADOW_RENDERER_VERSION

    def render(
        self, source: ForeshadowRenderSource, scope: RenderScope
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
            source_type="foreshadow",
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
                ("语料类型", "伏笔"),
                ("标题", source.title),
                ("作者规划状态", source.planned_status),
                ("当前位置状态", source.projected_status),
                ("伏笔内容", source.content),
            ],
        )
