from backend.embedding.contracts import RetrievalPurpose
from backend.embedding.writing import deterministic_query, retrieval_purpose_for_selection


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
