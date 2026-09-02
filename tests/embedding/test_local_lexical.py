from __future__ import annotations

from contextlib import nullcontext
from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from backend.creative_data_models import (
    NovelAssetBinding,
    NovelOutlineHead,
    NovelOutlineRevision,
    NovelSettingHead,
    NovelSettingRevision,
    PrivateAssetVersion,
    RevisionTimelineMappingHead,
    RevisionTimelineMappingSegment,
    StoryTimeline,
)
from backend.embedding.contracts import EmbeddingCorpus
from backend.embedding.local_lexical import (
    LocalLexicalScopeError,
    LocalLexicalSearchRequest,
    LocalTimelineLimit,
    search_local_authority,
)
from backend.embedding.retrieval.contracts import RetrievalPerspective
from backend.models import Document, DocumentRevision, Novel


def _hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _novel(*, novel_id: UUID, owner_id: UUID, workspace_id: UUID) -> Novel:
    return Novel(
        id=novel_id,
        owner_id=owner_id,
        workspace_id=workspace_id,
        title="回声档案",
    )


def _timeline(*, novel_id: UUID, name: str, primary: bool) -> StoryTimeline:
    return StoryTimeline(
        id=uuid4(),
        novel_id=novel_id,
        timeline_key=name,
        name=name,
        normalized_name=name,
        timeline_kind="main" if primary else "branch",
        is_primary=primary,
        parent_timeline_id=None,
        fork_anchor_json={},
        lifecycle_state="active",
        position=0 if primary else 1,
        version=1,
    )


def _chapter(
    *, novel_id: UUID, position: int, title: str, text: str
) -> tuple[Document, DocumentRevision]:
    document = Document(
        id=uuid4(),
        novel_id=novel_id,
        kind="chapter",
        title=title,
        position=position,
        status="draft",
    )
    revision = DocumentRevision(
        id=uuid4(),
        document_id=document.id,
        revision_number=1,
        content_markdown=text,
        content_text=text,
        content_hash=_hash(text),
        source="manual",
    )
    return document, revision


class _FakeAuthoritySession:
    def __init__(
        self,
        *,
        novel: Novel | None,
        timelines: tuple[StoryTimeline, ...],
        chapters: tuple[tuple[Document, DocumentRevision], ...] = (),
        objects: dict[tuple[type[object], UUID], object] | None = None,
        segments: tuple[RevisionTimelineMappingSegment, ...] = (),
        bindings: tuple[tuple[NovelAssetBinding, PrivateAssetVersion], ...] = (),
    ) -> None:
        self.novel = novel
        self.timelines = timelines
        self.chapters = chapters
        self.objects = objects or {}
        self.segments = segments
        self.bindings = bindings
        self.statements: list[str] = []
        self.no_autoflush = nullcontext()

    def scalar(self, statement: object) -> object | None:
        self.statements.append(str(statement))
        return self.novel

    def scalars(self, statement: object) -> tuple[object, ...]:
        sql = str(statement)
        self.statements.append(sql)
        if "similarity" in sql and "documents" in sql:
            return tuple(document.id for document, _revision in self.chapters)
        if "revision_timeline_mapping_segments" in sql:
            return self.segments
        if "revision_timeline_mapping_heads" in sql:
            return tuple(
                value
                for (model, _identity), value in self.objects.items()
                if model is RevisionTimelineMappingHead
            )
        if "story_timelines" in sql:
            return self.timelines
        if "documents" in sql:
            return tuple(document for document, _revision in self.chapters)
        raise AssertionError(f"unexpected scalars statement: {sql}")

    def execute(self, statement: object) -> SimpleNamespace:
        sql = str(statement)
        self.statements.append(sql)
        if "row_number()" in sql:
            return SimpleNamespace(
                all=lambda: [
                    (document.id, ordinal)
                    for ordinal, (document, _revision) in enumerate(
                        self.chapters, start=1
                    )
                ]
            )
        if "novel_asset_bindings" in sql:
            return SimpleNamespace(all=lambda: list(self.bindings))
        if "documents" in sql:
            return SimpleNamespace(all=lambda: list(self.chapters))
        raise AssertionError(f"unexpected execute statement: {sql}")

    def get(self, model: type[object], identity: UUID) -> object | None:
        return self.objects.get((model, identity))


def test_single_timeline_uses_current_authority_and_narrative_cutoff() -> None:
    owner_id, workspace_id, novel_id = uuid4(), uuid4(), uuid4()
    timeline = _timeline(novel_id=novel_id, name="main", primary=True)
    first = _chapter(
        novel_id=novel_id,
        position=1,
        title="蓝钥匙",
        text="林绪把蓝钥匙封进红色证物袋。",
    )
    future = _chapter(
        novel_id=novel_id,
        position=2,
        title="未来章",
        text="未来才会揭露蓝钥匙能打开地下室。",
    )
    session = _FakeAuthoritySession(
        novel=_novel(novel_id=novel_id, owner_id=owner_id, workspace_id=workspace_id),
        timelines=(timeline,),
        chapters=(first, future),
    )

    result = search_local_authority(
        session,
        LocalLexicalSearchRequest(
            owner_id=owner_id,
            workspace_id=workspace_id,
            novel_id=novel_id,
            query="谁保管蓝钥匙",
            corpora=frozenset({EmbeddingCorpus.MANUSCRIPT}),
            target_timeline_id=None,
            narrative_sequence_cutoff=1,
        ),
    )

    assert result.hits
    assert {hit.source_id for hit in result.hits} == {first[0].id}
    assert all(hit.timeline_id == timeline.id for hit in result.hits)
    assert all(hit.narrative_sequence_start == 1 for hit in result.hits)
    assert result.diagnostics.filtered_future_narrative_count == 1
    rebuilt = search_local_authority(
        session,
        LocalLexicalSearchRequest(
            owner_id=owner_id,
            workspace_id=workspace_id,
            novel_id=novel_id,
            query="谁保管蓝钥匙",
            corpora=frozenset({EmbeddingCorpus.MANUSCRIPT}),
            narrative_sequence_cutoff=1,
        ),
    )
    assert [hit.chunk_id for hit in rebuilt.hits] == [hit.chunk_id for hit in result.hits]
    chapter_sql = next(
        sql
        for sql in session.statements
        if "documents" in sql and "document_working_copies" in sql
    )
    assert "document_working_copies" in chapter_sql
    assert "base_revision_id" in chapter_sql


def test_empty_chapter_name_uses_internal_stable_title_without_public_leak() -> None:
    owner_id, workspace_id, novel_id = uuid4(), uuid4(), uuid4()
    timeline = _timeline(novel_id=novel_id, name="main", primary=True)
    chapter = _chapter(
        novel_id=novel_id,
        position=1,
        title="",
        text="潮声穿过窗户。",
    )
    session = _FakeAuthoritySession(
        novel=_novel(novel_id=novel_id, owner_id=owner_id, workspace_id=workspace_id),
        timelines=(timeline,),
        chapters=(chapter,),
    )

    result = search_local_authority(
        session,
        LocalLexicalSearchRequest(
            owner_id=owner_id,
            workspace_id=workspace_id,
            novel_id=novel_id,
            query="潮声",
            corpora=frozenset({EmbeddingCorpus.MANUSCRIPT}),
        ),
    )

    assert "标题: 章节正文" in result.hits[0].text
    public_hit = result.as_semantic_search_hits()[0]
    assert public_hit.snippet == "潮声穿过窗户。"
    assert "章节正文" not in public_hit.snippet


def test_multi_timeline_accepts_only_current_mapping_for_explicit_scope() -> None:
    owner_id, workspace_id, novel_id = uuid4(), uuid4(), uuid4()
    main = _timeline(novel_id=novel_id, name="main", primary=True)
    sibling = _timeline(novel_id=novel_id, name="sibling", primary=False)
    document, revision = _chapter(
        novel_id=novel_id,
        position=1,
        title="分岔",
        text="主线线索是银色钥匙。兄弟线秘密是绿色密匙。",
    )
    mapping_id = uuid4()
    head = RevisionTimelineMappingHead(
        revision_id=revision.id,
        document_id=document.id,
        novel_id=novel_id,
        source_content_hash=revision.content_hash,
        current_mapping_revision_id=mapping_id,
        version=1,
    )
    split = revision.content_text.index("兄弟")
    segments = (
        RevisionTimelineMappingSegment(
            id=uuid4(),
            mapping_revision_id=mapping_id,
            novel_id=novel_id,
            timeline_id=main.id,
            ordinal=0,
            source_start=0,
            source_end=split,
            story_sequence=1,
            story_time_json={},
        ),
        RevisionTimelineMappingSegment(
            id=uuid4(),
            mapping_revision_id=mapping_id,
            novel_id=novel_id,
            timeline_id=sibling.id,
            ordinal=1,
            source_start=split,
            source_end=len(revision.content_text),
            story_sequence=1,
            story_time_json={},
        ),
    )
    session = _FakeAuthoritySession(
        novel=_novel(novel_id=novel_id, owner_id=owner_id, workspace_id=workspace_id),
        timelines=(main, sibling),
        chapters=((document, revision),),
        objects={(RevisionTimelineMappingHead, revision.id): head},
        segments=segments,
    )

    result = search_local_authority(
        session,
        LocalLexicalSearchRequest(
            owner_id=owner_id,
            workspace_id=workspace_id,
            novel_id=novel_id,
            query="绿色密匙",
            corpora=frozenset({EmbeddingCorpus.MANUSCRIPT}),
            target_timeline_id=main.id,
            timeline_limits=(LocalTimelineLimit(timeline_id=main.id),),
        ),
    )

    assert not result.hits
    assert result.diagnostics.filtered_timeline_count == 1
    assert result.diagnostics.unmapped_revision_count == 0


def test_multi_timeline_unmapped_revision_fails_closed() -> None:
    owner_id, workspace_id, novel_id = uuid4(), uuid4(), uuid4()
    main = _timeline(novel_id=novel_id, name="main", primary=True)
    sibling = _timeline(novel_id=novel_id, name="sibling", primary=False)
    chapter = _chapter(
        novel_id=novel_id,
        position=1,
        title="未映射",
        text="这条秘密不得被猜测归入主线。",
    )
    session = _FakeAuthoritySession(
        novel=_novel(novel_id=novel_id, owner_id=owner_id, workspace_id=workspace_id),
        timelines=(main, sibling),
        chapters=(chapter,),
    )

    result = search_local_authority(
        session,
        LocalLexicalSearchRequest(
            owner_id=owner_id,
            workspace_id=workspace_id,
            novel_id=novel_id,
            query="秘密",
            corpora=frozenset({EmbeddingCorpus.MANUSCRIPT}),
            target_timeline_id=main.id,
        ),
    )

    assert not result.hits
    assert result.diagnostics.unmapped_revision_count == 1


def test_only_current_outline_setting_and_permitted_bound_asset_are_loaded() -> None:
    owner_id, workspace_id, novel_id = uuid4(), uuid4(), uuid4()
    timeline = _timeline(novel_id=novel_id, name="main", primary=True)
    outline_id, setting_id = uuid4(), uuid4()
    outline = NovelOutlineRevision(
        id=outline_id,
        novel_id=novel_id,
        revision_number=2,
        source_kind="manual",
        idempotency_key="outline-current",
        request_hash="a" * 64,
        target_chapter_count=3,
        background_text="红雨市全城监控离线。",
        plot_text="林绪追查蓝钥匙。",
        highlight_text="同名身份错位。",
        character_revision_refs_json=[],
        character_reference_digest="b" * 64,
        change_set_json={},
        content_hash="c" * 64,
    )
    setting = NovelSettingRevision(
        id=setting_id,
        novel_id=novel_id,
        revision_number=1,
        source_kind="manual",
        idempotency_key="setting-current",
        request_hash="d" * 64,
        schema_id="novel-setting/1",
        schema_version=1,
        settings_json={"规则": "红色证物袋不得离开档案室"},
        change_set_json={},
        content_hash="e" * 64,
    )
    allowed = PrivateAssetVersion(
        id=uuid4(),
        asset_id=uuid4(),
        version_number=3,
        title="现场手册",
        content="蓝钥匙由林绪保管。",
        metadata_json={},
        source_json={},
        rights_json={},
        content_hash="f" * 64,
        operation_key="asset-v3",
        operation_hash="1" * 64,
    )
    prohibited = PrivateAssetVersion(
        id=uuid4(),
        asset_id=uuid4(),
        version_number=1,
        title="禁用秘密",
        content="未来真相是林绪改写了档案。",
        metadata_json={},
        source_json={},
        rights_json={},
        content_hash="2" * 64,
        operation_key="prohibited-v1",
        operation_hash="3" * 64,
    )
    bindings = (
        (
            NovelAssetBinding(
                id=uuid4(), novel_id=novel_id, asset_id=allowed.asset_id,
                asset_version_id=allowed.id, usage_policy="required", position=0,
                lifecycle_state="active", version=1, operation_key="bind-allowed",
                operation_hash="4" * 64,
            ),
            allowed,
        ),
        # A defensive fake row verifies the Python boundary too; real SQL excludes it.
        (
            NovelAssetBinding(
                id=uuid4(), novel_id=novel_id, asset_id=prohibited.asset_id,
                asset_version_id=prohibited.id, usage_policy="prohibited", position=1,
                lifecycle_state="active", version=1, operation_key="bind-prohibited",
                operation_hash="5" * 64,
            ),
            prohibited,
        ),
    )
    session = _FakeAuthoritySession(
        novel=_novel(novel_id=novel_id, owner_id=owner_id, workspace_id=workspace_id),
        timelines=(timeline,),
        objects={
            (NovelOutlineHead, novel_id): NovelOutlineHead(
                novel_id=novel_id, current_revision_id=outline_id, version=2,
                establishment_source="manual",
            ),
            (NovelOutlineRevision, outline_id): outline,
            (NovelSettingHead, novel_id): NovelSettingHead(
                novel_id=novel_id, current_revision_id=setting_id, version=1,
                establishment_source="manual",
            ),
            (NovelSettingRevision, setting_id): setting,
        },
        bindings=bindings,
    )

    result = search_local_authority(
        session,
        LocalLexicalSearchRequest(
            owner_id=owner_id,
            workspace_id=workspace_id,
            novel_id=novel_id,
            query="蓝钥匙由谁保管",
            corpora=frozenset(
                {EmbeddingCorpus.PLANNING, EmbeddingCorpus.PRIVATE_ASSET}
            ),
        ),
    )

    assert any(hit.source_revision_id == allowed.id for hit in result.hits)
    assert all(hit.source_revision_id != prohibited.id for hit in result.hits)
    assert result.diagnostics.filtered_prohibited_asset_count == 1
    binding_sql = next(sql for sql in session.statements if "novel_asset_bindings" in sql)
    assert "lifecycle_state" in binding_sql
    assert "usage_policy" in binding_sql


def test_wrong_owner_or_workspace_is_rejected_without_loading_sources() -> None:
    owner_id, workspace_id, novel_id = uuid4(), uuid4(), uuid4()
    session = _FakeAuthoritySession(novel=None, timelines=())

    with pytest.raises(LocalLexicalScopeError, match="novel_scope_not_found"):
        search_local_authority(
            session,
            LocalLexicalSearchRequest(
                owner_id=owner_id,
                workspace_id=workspace_id,
                novel_id=novel_id,
                query="蓝钥匙",
                corpora=frozenset({EmbeddingCorpus.MANUSCRIPT}),
            ),
        )

    assert len(session.statements) == 1


def test_result_can_be_adapted_to_v2_candidate_without_provider_metadata() -> None:
    owner_id, workspace_id, novel_id = uuid4(), uuid4(), uuid4()
    timeline = _timeline(novel_id=novel_id, name="main", primary=True)
    chapter = _chapter(
        novel_id=novel_id,
        position=1,
        title="证物",
        text="蓝钥匙被锁在三号柜。",
    )
    session = _FakeAuthoritySession(
        novel=_novel(novel_id=novel_id, owner_id=owner_id, workspace_id=workspace_id),
        timelines=(timeline,),
        chapters=(chapter,),
    )

    result = search_local_authority(
        session,
        LocalLexicalSearchRequest(
            owner_id=owner_id,
            workspace_id=workspace_id,
            novel_id=novel_id,
            query="蓝钥匙",
            corpora=frozenset({EmbeddingCorpus.MANUSCRIPT}),
        ),
    )
    generation_id = uuid4()
    candidates, lexical = result.as_v2_inputs(
        owner_id=owner_id,
        workspace_id=workspace_id,
        novel_id=novel_id,
        generation_id=generation_id,
        index_version=1,
    )

    assert candidates[0].generation_id == generation_id
    assert candidates[0].source_current is True
    assert lexical.provider_request_id is None
    assert lexical.token_count is None
    assert lexical.redacted_error is None
    public_hits = result.as_semantic_search_hits()
    assert public_hits[0].source_revision_id == chapter[1].id
    assert [channel.value for channel in public_hits[0].channels] == ["lexical"]


def test_non_author_perspective_cannot_receive_author_only_authority() -> None:
    owner_id, workspace_id, novel_id = uuid4(), uuid4(), uuid4()
    timeline = _timeline(novel_id=novel_id, name="main", primary=True)
    outline_id = uuid4()
    outline = NovelOutlineRevision(
        id=outline_id,
        novel_id=novel_id,
        revision_number=1,
        source_kind="manual",
        idempotency_key="outline-private",
        request_hash="a" * 64,
        target_chapter_count=3,
        background_text="作者秘密：蓝钥匙由林绪保管。",
        plot_text="",
        highlight_text="",
        character_revision_refs_json=[],
        character_reference_digest="b" * 64,
        change_set_json={},
        content_hash="c" * 64,
    )
    session = _FakeAuthoritySession(
        novel=_novel(novel_id=novel_id, owner_id=owner_id, workspace_id=workspace_id),
        timelines=(timeline,),
        objects={
            (NovelOutlineHead, novel_id): NovelOutlineHead(
                novel_id=novel_id,
                current_revision_id=outline_id,
                version=1,
                establishment_source="manual",
            ),
            (NovelOutlineRevision, outline_id): outline,
        },
    )

    result = search_local_authority(
        session,
        LocalLexicalSearchRequest(
            owner_id=owner_id,
            workspace_id=workspace_id,
            novel_id=novel_id,
            query="蓝钥匙",
            corpora=frozenset({EmbeddingCorpus.PLANNING}),
            perspective=RetrievalPerspective.READER,
        ),
    )

    assert not result.hits
    assert result.diagnostics.filtered_visibility_count == 1


def test_local_authority_fallback_has_source_chunk_and_final_hit_caps() -> None:
    owner_id, workspace_id, novel_id = uuid4(), uuid4(), uuid4()
    timeline = _timeline(novel_id=novel_id, name="main", primary=True)
    chapters = tuple(
        _chapter(
            novel_id=novel_id,
            position=index,
            title=f"第{index}章",
            text=f"蓝钥匙证据 {index}",
        )
        for index in range(1, 101)
    )
    session = _FakeAuthoritySession(
        novel=_novel(
            novel_id=novel_id,
            owner_id=owner_id,
            workspace_id=workspace_id,
        ),
        timelines=(timeline,),
        chapters=chapters,
    )

    result = search_local_authority(
        session,
        LocalLexicalSearchRequest(
            owner_id=owner_id,
            workspace_id=workspace_id,
            novel_id=novel_id,
            query="蓝钥匙证据",
            corpora=frozenset({EmbeddingCorpus.MANUSCRIPT}),
            top_k=50,
        ),
    )

    assert result.diagnostics.candidate_chunk_count == 80
    assert len(result.hits) == 10
    bounded_queries = [
        sql
        for sql in session.statements
        if "documents" in sql and "LIMIT" in sql
    ]
    assert len(bounded_queries) == 2
