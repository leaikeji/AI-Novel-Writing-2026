"""Frozen, non-self-query quality gate for one embedding model space."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from importlib.resources import files
from math import sqrt
from typing import Any, Mapping


MIN_DENSE_RELEVANCE = 0.55
RECALL_AT_5_THRESHOLD = 0.85
MRR_THRESHOLD = 0.70
ABSTENTION_THRESHOLD = 0.90


@dataclass(frozen=True, slots=True)
class FrozenEvaluationFixture:
    cases: tuple[dict[str, Any], ...]
    sources: tuple[dict[str, Any], ...]


def load_frozen_evaluation_fixture() -> FrozenEvaluationFixture:
    # QwenPaw imports PawApps under a generated package name, so this anchor
    # must follow the module's actual package instead of assuming top-level
    # ``backend`` is importable in the host process.
    root = files(__package__).joinpath("fixtures")
    cases_payload = json.loads(
        root.joinpath("evaluation_cases_v2.json").read_text(encoding="utf-8")
    )
    sources_payload = json.loads(
        root.joinpath("evaluation_sources_v2.json").read_text(encoding="utf-8")
    )
    cases = tuple(cases_payload.get("cases") or ())
    sources = tuple(sources_payload.get("sources") or ())
    if cases_payload.get("schema_version") != "embedding-v2-cases/1" or len(cases) < 36:
        raise ValueError("frozen embedding evaluation cases are invalid")
    if sources_payload.get("schema_version") != "embedding-v2-sources/1" or not sources:
        raise ValueError("frozen embedding evaluation sources are invalid")
    source_keys = {str(item.get("source_key") or "") for item in sources}
    if "" in source_keys or len(source_keys) != len(sources):
        raise ValueError("frozen embedding evaluation source keys are invalid")
    for case in cases:
        if not case.get("is_no_answer") and not set(
            case.get("expected_source_keys") or ()
        ).issubset(source_keys):
            raise ValueError("positive evaluation case has no frozen source")
    return FrozenEvaluationFixture(cases=cases, sources=sources)


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("evaluation vectors must share one positive dimension")
    denominator = sqrt(sum(value * value for value in left)) * sqrt(
        sum(value * value for value in right)
    )
    if denominator == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / denominator


def _trigrams(value: str) -> set[str]:
    normalized = "".join(value.casefold().split())
    padded = f"  {normalized} "
    return {padded[index : index + 3] for index in range(max(0, len(padded) - 2))}


def _trigram_similarity(left: str, right: str) -> float:
    left_set, right_set = _trigrams(left), _trigrams(right)
    if not left_set and not right_set:
        return 1.0
    if not left_set or not right_set:
        return 0.0
    return 2.0 * len(left_set & right_set) / (len(left_set) + len(right_set))


def _rank(
    values: Mapping[str, float], *, minimum: float = 0.0
) -> tuple[str, ...]:
    return tuple(
        key
        for key, score in sorted(values.items(), key=lambda item: (-item[1], item[0]))
        if score >= minimum
    )


def _rrf(lexical: tuple[str, ...], dense: tuple[str, ...]) -> tuple[str, ...]:
    scores: dict[str, float] = {}
    for ranking in (lexical, dense):
        for index, key in enumerate(ranking, start=1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (60 + index)
    return _rank(scores)


def evaluate_frozen_vectors(
    fixture: FrozenEvaluationFixture,
    *,
    source_vectors: Mapping[str, tuple[float, ...]],
    query_vectors: Mapping[str, tuple[float, ...]],
) -> dict[str, object]:
    sources = {str(item["source_key"]): item for item in fixture.sources}
    if set(source_vectors) != set(sources):
        raise ValueError("evaluation requires one vector for every frozen source")
    if set(query_vectors) != {str(item["case_id"]) for item in fixture.cases}:
        raise ValueError("evaluation requires one vector for every frozen query")

    positive_count = 0
    no_answer_count = 0
    recall_hits = 0
    lexical_recall_hits = 0
    reciprocal_rank = 0.0
    abstained = 0
    leaks: list[dict[str, str]] = []
    digest_rows: list[object] = []
    for case in fixture.cases:
        case_id = str(case["case_id"])
        corpora = set(case.get("corpora") or ())
        eligible = {
            key: source
            for key, source in sources.items()
            if source.get("corpus") in corpora
        }
        dense_scores = {
            key: _cosine(query_vectors[case_id], source_vectors[key])
            for key in eligible
        }
        lexical_scores = {
            key: _trigram_similarity(str(case["query"]), str(source["content"]))
            for key, source in eligible.items()
        }
        dense = _rank(dense_scores, minimum=MIN_DENSE_RELEVANCE)
        lexical = _rank(lexical_scores, minimum=0.01)
        hybrid = _rrf(lexical, dense)
        forbidden = set(case.get("forbidden_source_keys") or ())
        leaks.extend(
            {"case_id": case_id, "source_key": key}
            for key in hybrid[:5]
            if key in forbidden
        )
        if case.get("is_no_answer"):
            no_answer_count += 1
            if not hybrid:
                abstained += 1
            digest_rows.append([case_id, "no_answer", list(hybrid[:5])])
            continue
        positive_count += 1
        expected = set(case.get("expected_source_keys") or ())
        if expected.intersection(hybrid[:5]):
            recall_hits += 1
        if expected.intersection(lexical[:5]):
            lexical_recall_hits += 1
        rank = next(
            (index for index, key in enumerate(hybrid, start=1) if key in expected),
            None,
        )
        if rank is not None:
            reciprocal_rank += 1.0 / rank
        digest_rows.append([case_id, list(hybrid[:5]), rank])

    recall_at_5 = recall_hits / positive_count if positive_count else 0.0
    lexical_recall_at_5 = (
        lexical_recall_hits / positive_count if positive_count else 0.0
    )
    mrr = reciprocal_rank / positive_count if positive_count else 0.0
    abstention = abstained / no_answer_count if no_answer_count else 0.0
    passed = (
        recall_at_5 >= RECALL_AT_5_THRESHOLD
        and mrr >= MRR_THRESHOLD
        and abstention >= ABSTENTION_THRESHOLD
        and recall_at_5 >= lexical_recall_at_5
        and not leaks
    )
    return {
        "schema_version": "embedding-evaluation/2",
        "case_count": len(fixture.cases),
        "positive_count": positive_count,
        "no_answer_count": no_answer_count,
        "recall_at_5": recall_at_5,
        "mrr": mrr,
        "abstention": abstention,
        "lexical_recall_at_5": lexical_recall_at_5,
        "hybrid_not_below_lexical": recall_at_5 >= lexical_recall_at_5,
        "leak_count": len(leaks),
        "leaks": leaks,
        "minimum_dense_relevance": MIN_DENSE_RELEVANCE,
        "thresholds": {
            "recall_at_5": RECALL_AT_5_THRESHOLD,
            "mrr": MRR_THRESHOLD,
            "abstention": ABSTENTION_THRESHOLD,
            "max_leak_count": 0,
        },
        "passed": passed,
        "case_digest": sha256(
            json.dumps(
                digest_rows,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
    }
