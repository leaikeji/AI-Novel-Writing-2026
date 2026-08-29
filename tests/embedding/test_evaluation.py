from uuid import UUID

import pytest

from backend.embedding.evaluation import EvaluationCase, evaluate_rankings


def uid(value: int) -> UUID:
    return UUID(int=value)


def test_evaluation_passes_only_when_recall_and_mrr_gates_pass() -> None:
    cases = tuple(
        EvaluationCase(
            query=f"q{index}",
            expected_chunk_id=uid(index),
            candidate_vectors=((uid(index), (1.0, 0.0)), (uid(100 + index), (0.0, 1.0))),
        )
        for index in range(1, 11)
    )
    summary = evaluate_rankings(cases, tuple((1.0, 0.0) for _ in cases))
    assert summary.passed is True
    assert summary.recall_at_5 == 1.0
    assert summary.mrr == 1.0
    assert len(summary.case_digest) == 64


def test_evaluation_rejects_empty_or_dimension_mismatched_cases() -> None:
    with pytest.raises(ValueError):
        evaluate_rankings((), ())
    case = EvaluationCase(
        query="q",
        expected_chunk_id=uid(1),
        candidate_vectors=((uid(1), (1.0, 0.0)),),
    )
    with pytest.raises(ValueError):
        evaluate_rankings((case,), ((1.0,),))
