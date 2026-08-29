from ..contracts import EmbeddingCorpus

from .base import make_document, make_metadata, source_is_in_scope
from .contracts import RelationshipRenderSource, RenderScope, RenderedCorpusDocument


RELATIONSHIP_RENDERER_VERSION = "relationship/1"


class RelationshipRendererV1:
    corpus = EmbeddingCorpus.RELATIONSHIP
    renderer_id = "structured-relationship"
    renderer_version = RELATIONSHIP_RENDERER_VERSION

    def render(
        self, source: RelationshipRenderSource, scope: RenderScope
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
            source_type="relationship",
            source_id=source.source_id,
            source_revision_id=source.source_revision_id,
            source_version=source.source_version,
            timeline_id=source.timeline_id,
            character_instance_ids=(
                source.source_character_instance_id,
                source.target_character_instance_id,
            ),
            narrative_sequence=source.story_sequence,
            visibility=source.visibility,
        )
        return make_document(
            renderer_id=self.renderer_id,
            renderer_version=self.renderer_version,
            metadata=metadata,
            text_lines=[
                ("语料类型", "人物关系"),
                ("起点人物", source.source_display_name),
                ("终点人物", source.target_display_name),
                ("方向", source.directionality),
                ("关系类别", source.relation_kind),
                ("关系标签", source.label),
                ("作者定义", source.description),
                ("当前位置状态", source.projected_status),
            ],
        )
