from datetime import UTC, datetime
from uuid import UUID

import pytest

from backend.embedding.contracts import EmbeddingCorpus
from backend.embedding.renderers import (
    CHARACTER_RENDERER_VERSION,
    FORESHADOW_RENDERER_VERSION,
    RELATIONSHIP_RENDERER_VERSION,
    STORYLINE_RENDERER_VERSION,
    STORY_EVENT_RENDERER_VERSION,
    TIMELINE_RENDERER_VERSION,
    CharacterRenderSource,
    CharacterRendererV1,
    ForeshadowRenderSource,
    ForeshadowRendererV1,
    RelationshipRenderSource,
    RelationshipRendererV1,
    RendererError,
    RendererErrorCode,
    RendererPerspective,
    RenderScope,
    StoryEventRenderSource,
    StoryEventRendererV1,
    StorylineRenderSource,
    StorylineRendererV1,
    TimelineRenderSource,
    TimelineRendererV1,
)
from backend.story_state.contracts import StoryFactV2


NOW = datetime(2026, 8, 29, tzinfo=UTC)


def uid(value: int) -> UUID:
    return UUID(int=value)


def visibility(
    scope: str = "author",
    *,
    instances: tuple[UUID, ...] = (),
    revealed_at: int | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "story-visibility/1",
        "scope": scope,
        "character_instance_ids": instances,
        "revealed_at_sequence": revealed_at,
    }


def render_scope(
    *,
    novel_id: UUID = uid(1),
    target_timeline_id: UUID = uid(11),
    path: tuple[UUID, ...] = (uid(10), uid(11)),
    cutoff: int | None = 20,
    perspective: RendererPerspective = RendererPerspective.AUTHOR,
    observer: UUID | None = None,
) -> RenderScope:
    return RenderScope(
        novel_id=novel_id,
        target_timeline_id=target_timeline_id,
        inheritance_path=path,
        narrative_cutoff=cutoff,
        perspective=perspective,
        observer_character_instance_id=observer,
    )


def character_source(**overrides: object) -> CharacterRenderSource:
    values: dict[str, object] = {
        "novel_id": uid(1),
        "source_id": uid(100),
        "source_revision_id": uid(101),
        "source_version": 3,
        "timeline_id": uid(11),
        "story_sequence": 12,
        "visibility": visibility("author"),
        "character_instance_id": uid(102),
        "instance_character_id": uid(100),
        "character_instance_revision_id": uid(103),
        "segment_key": "identity",
        "display_name": "林岚",
        "display_label": "红线版本",
        "role_type": "protagonist",
        "description": "钟楼调查员",
        "public_identity": "记者",
        "true_identity": "失踪王女",
        "cover_identity": "地方报记者",
        "birth_information": "新历 18 年",
        "current_age": "22—23 岁",
        "occupation": "记者",
        "personality": "谨慎",
        "goals": "查清旧案",
        "flaws": "不信任盟友",
        "secrets": "持有王室印章",
        "growth_direction": "学会合作",
    }
    values.update(overrides)
    return CharacterRenderSource(**values)


def relationship_source(**overrides: object) -> RelationshipRenderSource:
    values: dict[str, object] = {
        "novel_id": uid(1),
        "source_id": uid(200),
        "source_revision_id": uid(201),
        "source_version": 2,
        "timeline_id": uid(11),
        "story_sequence": 13,
        "visibility": visibility("author"),
        "source_character_id": uid(100),
        "target_character_id": uid(110),
        "source_character_instance_id": uid(102),
        "target_character_instance_id": uid(112),
        "source_instance_character_id": uid(100),
        "target_instance_character_id": uid(110),
        "source_display_name": "林岚",
        "target_display_name": "陆川",
        "directionality": "directed",
        "relation_kind": "alliance",
        "label": "秘密盟友",
        "description": "共同调查钟楼旧案",
        "projected_status": "互相信任但仍隐瞒身份",
    }
    values.update(overrides)
    return RelationshipRenderSource(**values)


def storyline_source(**overrides: object) -> StorylineRenderSource:
    values: dict[str, object] = {
        "novel_id": uid(1),
        "source_id": uid(300),
        "source_version": 4,
        "timeline_id": uid(11),
        "story_sequence": 14,
        "visibility": visibility("author"),
        "storyline_type": "main",
        "title": "钟楼旧案",
        "description": "寻找王室失踪的真相",
        "planned_status": "active",
        "projected_status": "获得第一封密信",
    }
    values.update(overrides)
    return StorylineRenderSource(**values)


def foreshadow_source(**overrides: object) -> ForeshadowRenderSource:
    values: dict[str, object] = {
        "novel_id": uid(1),
        "source_id": uid(400),
        "source_version": 5,
        "timeline_id": uid(11),
        "story_sequence": 15,
        "visibility": visibility("author"),
        "title": "褪色印章",
        "content": "印章背面刻有被抹去的继承人姓名",
        "planned_status": "planted",
        "projected_status": "尚未揭示刻字含义",
    }
    values.update(overrides)
    return ForeshadowRenderSource(**values)


def timeline_source(**overrides: object) -> TimelineRenderSource:
    values: dict[str, object] = {
        "novel_id": uid(1),
        "source_id": uid(11),
        "source_version": 1,
        "timeline_id": uid(11),
        "story_sequence": 10,
        "visibility": visibility("author"),
        "timeline_key": "red-branch",
        "name": "红线",
        "timeline_kind": "branch",
        "is_primary": False,
        "parent_timeline_id": uid(10),
        "parent_timeline_name": "主时间线",
        "fork_story_sequence": 10,
        "fork_anchor_label": "第三章结尾",
    }
    values.update(overrides)
    return TimelineRenderSource(**values)


def story_fact(**overrides: object) -> StoryFactV2:
    values: dict[str, object] = {
        "id": uid(500),
        "novel_id": uid(1),
        "fact_type": "general_fact",
        "subject": "钟楼密信",
        "predicate": "藏于",
        "object_text": "北侧暗格",
        "details": {
            "schema_version": "general-fact/1",
            "value": {"never_dump_this_key": "任意 JSON 秘密"},
        },
        "timeline_id": uid(11),
        "dimension": "location",
        "event_kind": "established",
        "story_sequence": 16,
        "visibility_json": visibility("author"),
        "event_fingerprint": "a" * 64,
        "created_at": NOW,
    }
    values.update(overrides)
    return StoryFactV2(**values)


@pytest.mark.parametrize(
    ("renderer", "source", "corpus", "version", "expected_text"),
    [
        (
            CharacterRendererV1(),
            character_source(),
            EmbeddingCorpus.CHARACTER,
            CHARACTER_RENDERER_VERSION,
            "真实身份：失踪王女",
        ),
        (
            RelationshipRendererV1(),
            relationship_source(),
            EmbeddingCorpus.RELATIONSHIP,
            RELATIONSHIP_RENDERER_VERSION,
            "关系标签：秘密盟友",
        ),
        (
            StoryEventRendererV1(),
            StoryEventRenderSource(novel_id=uid(1), fact=story_fact()),
            EmbeddingCorpus.STORY_EVENT,
            STORY_EVENT_RENDERER_VERSION,
            "事实内容：北侧暗格",
        ),
        (
            StorylineRendererV1(),
            storyline_source(),
            EmbeddingCorpus.STORYLINE,
            STORYLINE_RENDERER_VERSION,
            "标题：钟楼旧案",
        ),
        (
            ForeshadowRendererV1(),
            foreshadow_source(),
            EmbeddingCorpus.FORESHADOW,
            FORESHADOW_RENDERER_VERSION,
            "标题：褪色印章",
        ),
        (
            TimelineRendererV1(),
            timeline_source(),
            EmbeddingCorpus.TIMELINE,
            TIMELINE_RENDERER_VERSION,
            "主继承父线：主时间线",
        ),
    ],
)
def test_each_structured_corpus_has_an_explicit_version_and_stable_metadata(
    renderer, source, corpus, version, expected_text
) -> None:
    document = renderer.render(source, render_scope())

    assert document is not None
    assert document.renderer_version == version
    assert document.metadata.corpus is corpus
    assert document.metadata.novel_id == uid(1)
    assert document.metadata.timeline_id == uid(11)
    assert expected_text in document.text
    assert len(document.content_hash) == 64


def test_renderer_is_deterministic_after_safe_whitespace_normalization() -> None:
    renderer = CharacterRendererV1()
    first = renderer.render(character_source(description="钟楼  调查员\r\n谨慎"), render_scope())
    second = renderer.render(character_source(description="钟楼 调查员\n谨慎"), render_scope())

    assert first is not None and second is not None
    assert first.text == second.text
    assert first.content_hash == second.content_hash


def test_story_event_never_dumps_arbitrary_details_json() -> None:
    document = StoryEventRendererV1().render(
        StoryEventRenderSource(novel_id=uid(1), fact=story_fact()), render_scope()
    )

    assert document is not None
    assert "never_dump_this_key" not in document.text
    assert "任意 JSON 秘密" not in document.text
    assert "{'" not in document.text


def test_cross_novel_source_is_a_hard_scope_error() -> None:
    with pytest.raises(RendererError) as error:
        CharacterRendererV1().render(character_source(novel_id=uid(2)), render_scope())
    assert error.value.code is RendererErrorCode.CROSS_NOVEL_SOURCE


@pytest.mark.parametrize(
    "source",
    [
        character_source(timeline_id=uid(12)),
        character_source(story_sequence=21),
        character_source(story_sequence=None),
    ],
)
def test_sibling_timeline_and_future_source_are_not_rendered(source) -> None:
    assert CharacterRendererV1().render(source, render_scope()) is None


def test_reader_and_character_perspectives_never_render_unrevealed_information() -> None:
    reader_scope = render_scope(perspective=RendererPerspective.READER, cutoff=20)
    unrevealed = character_source(
        visibility=visibility("reader", revealed_at=21),
        story_sequence=19,
    )
    revealed = character_source(
        visibility=visibility("reader", revealed_at=18),
        story_sequence=19,
    )
    assert CharacterRendererV1().render(unrevealed, reader_scope) is None
    assert CharacterRendererV1().render(revealed, reader_scope) is not None
    missing_reveal_evidence = character_source(
        visibility=visibility("reader"),
        story_sequence=19,
    )
    assert CharacterRendererV1().render(missing_reveal_evidence, reader_scope) is None

    observer = uid(900)
    character_scope = render_scope(
        perspective=RendererPerspective.CHARACTER_INSTANCE,
        observer=observer,
        cutoff=20,
    )
    other_only = character_source(
        visibility=visibility(
            "character_instances", instances=(uid(901),), revealed_at=10
        ),
        story_sequence=19,
    )
    observer_visible = character_source(
        visibility=visibility(
            "character_instances", instances=(observer,), revealed_at=10
        ),
        story_sequence=19,
    )
    assert CharacterRendererV1().render(other_only, character_scope) is None
    assert CharacterRendererV1().render(observer_visible, character_scope) is not None


def test_non_author_scope_requires_explicit_cutoff() -> None:
    with pytest.raises(ValueError):
        render_scope(perspective=RendererPerspective.READER, cutoff=None)


def test_hash_changes_when_renderer_metadata_or_semantic_text_changes() -> None:
    renderer = CharacterRendererV1()
    baseline = renderer.render(character_source(), render_scope())
    changed_text = renderer.render(character_source(goals="离开王都"), render_scope())
    changed_revision = renderer.render(
        character_source(source_revision_id=uid(999)), render_scope()
    )

    assert baseline is not None and changed_text is not None and changed_revision is not None
    assert len({baseline.content_hash, changed_text.content_hash, changed_revision.content_hash}) == 3
