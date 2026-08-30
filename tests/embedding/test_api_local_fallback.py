from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.embedding import api
from backend.embedding.contracts import (
    EmbeddingCorpus,
    RetrievalPurpose,
    SemanticSearchRequest,
)
from backend.embedding.local_lexical import (
    LocalLexicalDiagnostics,
    LocalLexicalHit,
    LocalLexicalResult,
)


class _ReadOnlySession:
    def __init__(self) -> None:
        self.scalar_calls = 0

    def scalar(self, _statement):
        self.scalar_calls += 1
        return None


@pytest.mark.asyncio
async def test_semantic_search_uses_authority_lexical_when_index_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = uuid4()
    timeline_id = uuid4()
    source_id = uuid4()
    revision_id = uuid4()
    chunk_id = uuid4()
    captured = {}

    monkeypatch.setattr(api, "get_configuration", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        api,
        "_inheritance_scope",
        lambda *_args, **_kwargs: (
            frozenset({timeline_id}),
            ((timeline_id, 8),),
        ),
    )

    def local_search(_session, request):
        captured["request"] = request
        return LocalLexicalResult(
            hits=(
                LocalLexicalHit(
                    corpus=EmbeddingCorpus.MANUSCRIPT,
                    source_type="chapter_revision",
                    source_id=source_id,
                    source_revision_id=revision_id,
                    chunk_id=chunk_id,
                    chunk_ordinal=0,
                    text="第一章确认蓝钥匙由林绪保管。",
                    lexical_raw_score=0.75,
                    timeline_id=timeline_id,
                    narrative_sequence_start=1,
                    narrative_sequence_end=1,
                    story_sequence_start=1,
                    story_sequence_end=1,
                ),
            ),
            diagnostics=LocalLexicalDiagnostics(
                authority_source_count=1,
                candidate_chunk_count=1,
                scored_chunk_count=1,
                below_threshold_count=0,
                top_k_omitted_count=0,
                unmapped_revision_count=0,
                filtered_future_narrative_count=1,
                filtered_timeline_count=0,
                filtered_story_count=0,
                filtered_prohibited_asset_count=0,
                filtered_visibility_count=0,
            ),
        )

    monkeypatch.setattr(api, "search_local_authority", local_search)

    result = await api.semantic_search(
        novel_id,
        SemanticSearchRequest(
            query="谁保管蓝钥匙",
            retrieval_purpose=RetrievalPurpose.CHAPTER_BODY,
            corpora=(EmbeddingCorpus.MANUSCRIPT,),
            timeline_id=timeline_id,
            narrative_sequence=3,
            story_sequence_cutoff=8,
        ),
        _ReadOnlySession(),
    )

    assert captured["request"].narrative_sequence_cutoff == 2
    assert captured["request"].timeline_limits[0].timeline_id == timeline_id
    assert result["generation_id"] is None
    assert result["mode"] == "lexical_only"
    assert result["degraded_reason"] == "dense_unavailable"
    assert result["hits"][0]["source_revision_id"] == str(revision_id)
    assert result["hits"][0]["channels"] == ["lexical"]
    assert result["omission_summary"] == [
        {"reason": "future_narrative", "count": 1}
    ]


@pytest.mark.asyncio
async def test_semantic_search_uses_authority_lexical_when_attached_index_has_no_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = uuid4()
    timeline_id = uuid4()
    generation_id = uuid4()
    source_id = uuid4()
    revision_id = uuid4()
    chunk_id = uuid4()
    configuration = SimpleNamespace(
        active_generation_id=generation_id,
        credential_ref=None,
        retrieval_policy_version="writing-retrieval/2",
    )
    generation = SimpleNamespace(
        id=generation_id,
        state="active",
        profile_id=uuid4(),
    )
    build = SimpleNamespace(
        generation_id=generation_id,
        novel_id=novel_id,
        index_version=0,
        sync_state="updating",
        published_digest="0" * 64,
        authority_digest="0" * 64,
    )

    class SessionWithEmptyIndex:
        def __init__(self) -> None:
            self.scalar_calls = 0

        def scalar(self, _statement):
            self.scalar_calls += 1
            return None if self.scalar_calls == 1 else build

        def get(self, model, identity):
            if model is api.EmbeddingGeneration and identity == generation_id:
                return generation
            return None

        def execute(self, _statement):
            return SimpleNamespace(all=lambda: [])

    monkeypatch.setattr(
        api, "get_configuration", lambda *_args, **_kwargs: configuration
    )
    monkeypatch.setattr(
        api,
        "_inheritance_scope",
        lambda *_args, **_kwargs: (
            frozenset({timeline_id}),
            ((timeline_id, 8),),
        ),
    )
    monkeypatch.setattr(api, "_known_visibility_keys", lambda *_args, **_kwargs: frozenset())
    monkeypatch.setattr(
        api,
        "search_local_authority",
        lambda _session, _request: LocalLexicalResult(
            hits=(
                LocalLexicalHit(
                    corpus=EmbeddingCorpus.MANUSCRIPT,
                    source_type="chapter_revision",
                    source_id=source_id,
                    source_revision_id=revision_id,
                    chunk_id=chunk_id,
                    chunk_ordinal=0,
                    text="第一章仍可从正式 revision 做本地词面召回。",
                    lexical_raw_score=0.8,
                    timeline_id=timeline_id,
                    narrative_sequence_start=1,
                    narrative_sequence_end=1,
                    story_sequence_start=1,
                    story_sequence_end=1,
                ),
            ),
            diagnostics=LocalLexicalDiagnostics(
                authority_source_count=1,
                candidate_chunk_count=1,
                scored_chunk_count=1,
                below_threshold_count=0,
                top_k_omitted_count=0,
                unmapped_revision_count=0,
                filtered_future_narrative_count=0,
                filtered_timeline_count=0,
                filtered_story_count=0,
                filtered_prohibited_asset_count=0,
                filtered_visibility_count=0,
            ),
        ),
    )

    result = await api.semantic_search(
        novel_id,
        SemanticSearchRequest(
            query="第一章发生了什么",
            retrieval_purpose=RetrievalPurpose.CHAPTER_BODY,
            corpora=(EmbeddingCorpus.MANUSCRIPT,),
            timeline_id=timeline_id,
            narrative_sequence=2,
            story_sequence_cutoff=8,
        ),
        SessionWithEmptyIndex(),
    )

    assert result["mode"] == "lexical_only"
    assert result["index_status"] == "updating"
    assert result["generation_id"] is None
    assert result["hits"][0]["source_revision_id"] == str(revision_id)
