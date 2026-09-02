from uuid import uuid4

import pytest

from backend.embedding.contracts import RetrievalPurpose
from backend.embedding.writing import (
    deterministic_query,
    retrieval_purpose_for_selection,
    retrieve_for_writing,
)


def test_selection_operation_matrix_is_explicit() -> None:
    assert retrieval_purpose_for_selection("rewrite") is RetrievalPurpose.SELECTION_REWRITE
    assert retrieval_purpose_for_selection("expand") is RetrievalPurpose.SELECTION_EXPAND
    assert retrieval_purpose_for_selection("dialogue") is RetrievalPurpose.SELECTION_DIALOGUE
    assert retrieval_purpose_for_selection("review") is RetrievalPurpose.SELECTION_REVIEW
    assert retrieval_purpose_for_selection("polish") is None
    assert retrieval_purpose_for_selection("shorten") is None
    assert retrieval_purpose_for_selection("custom") is None
    assert retrieval_purpose_for_selection(
        "custom", use_novel_context=True
    ) is RetrievalPurpose.SELECTION_CUSTOM


def test_query_renderer_is_bounded_and_deterministic() -> None:
    first = deterministic_query(
        purpose=RetrievalPurpose.CHAPTER_BODY,
        title="第三章",
        outline="追查旧案",
        expectation="承接前文",
    )
    second = deterministic_query(
        purpose=RetrievalPurpose.CHAPTER_BODY,
        title="第三章",
        outline="追查旧案",
        expectation="承接前文",
    )
    assert first == second
    assert "chapter_body" in first
    assert len(first) <= 4000


@pytest.mark.asyncio
async def test_failed_retrieval_is_context_only_not_fictional_lexical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.embedding import writing

    async def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("retrieval unavailable")

    monkeypatch.setattr(writing, "semantic_search", fail)

    snapshot = await retrieve_for_writing(
        object(),  # type: ignore[arg-type]
        novel_id=uuid4(),
        purpose=RetrievalPurpose.CHAPTER_BODY,
        query="蓝钥匙",
    )

    assert snapshot["mode"] == "context_only"
    assert snapshot["retrieval_policy_version"] == "writing-retrieval/3"
    assert snapshot["degraded_reason"] == "semantic_retrieval_unavailable"


@pytest.mark.asyncio
async def test_lexical_only_is_preserved_only_after_search_reports_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.embedding import writing

    async def lexical(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "mode": "lexical_only",
            "hits": [],
            "degraded_reason": "dense_timeout",
        }

    monkeypatch.setattr(writing, "semantic_search", lexical)

    snapshot = await retrieve_for_writing(
        object(),  # type: ignore[arg-type]
        novel_id=uuid4(),
        purpose=RetrievalPurpose.CHAPTER_BODY,
        query="蓝钥匙",
    )

    assert snapshot["mode"] == "lexical_only"
    assert snapshot["degraded_reason"] == "dense_timeout"
