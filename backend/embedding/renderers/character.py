from ..contracts import EmbeddingCorpus

from .base import make_document, make_metadata, source_is_in_scope
from .contracts import CharacterRenderSource, RenderScope, RenderedCorpusDocument


CHARACTER_RENDERER_VERSION = "character/1"


class CharacterRendererV1:
    corpus = EmbeddingCorpus.CHARACTER
    renderer_id = "structured-character"
    renderer_version = CHARACTER_RENDERER_VERSION

    def render(
        self, source: CharacterRenderSource, scope: RenderScope
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
            source_type="character",
            source_id=source.source_id,
            source_revision_id=source.source_revision_id,
            source_version=source.source_version,
            timeline_id=source.timeline_id,
            character_instance_ids=(source.character_instance_id,),
            narrative_sequence=source.story_sequence,
            visibility=source.visibility,
        )
        return make_document(
            renderer_id=self.renderer_id,
            renderer_version=self.renderer_version,
            metadata=metadata,
            text_lines=[
                ("语料类型", "人物"),
                ("资料分段", source.segment_key),
                ("姓名", source.display_name),
                ("实例区分", source.display_label),
                ("角色层级", source.role_type),
                ("人物小传", source.description),
                ("公开身份", source.public_identity),
                ("真实身份", source.true_identity),
                ("掩护身份", source.cover_identity),
                ("出生信息", source.birth_information),
                ("当前年龄", source.current_age),
                ("职业", source.occupation),
                ("性格", source.personality),
                ("目标", source.goals),
                ("缺陷", source.flaws),
                ("秘密", source.secrets),
                ("成长方向", source.growth_direction),
            ],
        )
