"""Deterministic retrieval-evaluation metrics for candidate generations."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from math import sqrt
from uuid import UUID


RECALL_AT_5_THRESHOLD = 0.85
MRR_THRESHOLD = 0.70


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    query: str
    expected_chunk_id: UUID
    candidate_vectors: tuple[tuple[UUID, tuple[float, ...]], ...]


@dataclass(frozen=True, slots=True)
class EvaluationSummary:
    case_count: int
    recall_at_5: float
    mrr: float
    passed: bool
    case_digest: str

    def as_json(self) -> dict[str, object]:
        return {
            "schema_version": "embedding-evaluation/1",
            "case_count": self.case_count,
            "recall_at_5": self.recall_at_5,
            "mrr": self.mrr,
            "thresholds": {
                "recall_at_5": RECALL_AT_5_THRESHOLD,
                "mrr": MRR_THRESHOLD,
            },
            "passed": self.passed,
            "case_digest": self.case_digest,
        }


def cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("evaluation vectors must have the same positive dimension")
    denominator = sqrt(sum(value * value for value in left)) * sqrt(
        sum(value * value for value in right)
    )
    if denominator == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / denominator


def evaluate_rankings(
    cases: tuple[EvaluationCase, ...],
    query_vectors: tuple[tuple[float, ...], ...],
) -> EvaluationSummary:
    if not cases or len(cases) != len(query_vectors):
        raise ValueError("evaluation requires one query vector per non-empty case")
    hits = 0
    reciprocal_rank = 0.0
    digest_rows: list[object] = []
    for case, query_vector in zip(cases, query_vectors):
        ranking = sorted(
            case.candidate_vectors,
            key=lambda item: (-cosine_similarity(query_vector, item[1]), str(item[0])),
        )
        rank = next(
            (index for index, (chunk_id, _) in enumerate(ranking, start=1)
             if chunk_id == case.expected_chunk_id),
            None,
        )
        if rank is not None and rank <= 5:
            hits += 1
        if rank is not None:
            reciprocal_rank += 1.0 / rank
        digest_rows.append([case.query, str(case.expected_chunk_id), rank])
    case_count = len(cases)
    recall = hits / case_count
    mrr = reciprocal_rank / case_count
    digest = sha256(
        json.dumps(
            digest_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    return EvaluationSummary(
        case_count=case_count,
        recall_at_5=recall,
        mrr=mrr,
        passed=recall >= RECALL_AT_5_THRESHOLD and mrr >= MRR_THRESHOLD,
        case_digest=digest,
    )
