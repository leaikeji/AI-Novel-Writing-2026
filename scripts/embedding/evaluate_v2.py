#!/usr/bin/env python3
"""Offline evaluator for the embedding V2 retrieval fixture.

The evaluator intentionally consumes source-key rankings instead of calling an
embedding provider.  This makes the quality gate deterministic, cheap, and safe
to run in CI.  A runtime retrieval implementation can export rankings using the
same small JSON contract and reuse this evaluator unchanged.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


CASE_FIELDS = frozenset(
    {
        "case_id",
        "query",
        "corpora",
        "expected_source_keys",
        "forbidden_source_keys",
        "is_no_answer",
        "timeline_id",
        "narrative_sequence_cutoff",
        "story_sequence_cutoff",
        "perspective",
    }
)
ALLOWED_CORPORA = frozenset({"manuscript", "planning", "private_asset"})
_NORMALIZE_RE = re.compile(r"[^0-9A-Za-z\u3400-\u9fff]+")


class FixtureValidationError(ValueError):
    """Raised when an evaluation fixture violates the frozen contract."""


@dataclass(frozen=True)
class GateThresholds:
    recall_at_5: float = 0.85
    mrr: float = 0.70
    abstention: float = 0.90
    max_leak_count: int = 0


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_cases(path: Path) -> list[dict[str, Any]]:
    payload = _load_json(path)
    if not isinstance(payload, dict) or payload.get("schema_version") != "embedding-v2-cases/1":
        raise FixtureValidationError("cases fixture must use embedding-v2-cases/1")
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise FixtureValidationError("cases must be a list")
    return cases


def load_rankings(path: Path) -> dict[str, dict[str, list[str]]]:
    payload = _load_json(path)
    if not isinstance(payload, dict) or payload.get("schema_version") != "embedding-v2-rankings/1":
        raise FixtureValidationError("rankings fixture must use embedding-v2-rankings/1")
    rows = payload.get("rankings")
    if not isinstance(rows, list):
        raise FixtureValidationError("rankings must be a list")

    result: dict[str, dict[str, list[str]]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise FixtureValidationError(f"ranking {index} must be an object")
        if set(row) != {"case_id", "lexical_source_keys", "hybrid_source_keys"}:
            raise FixtureValidationError(f"ranking {index} has unexpected fields")
        case_id = row["case_id"]
        if not isinstance(case_id, str) or not case_id:
            raise FixtureValidationError(f"ranking {index} has invalid case_id")
        if case_id in result:
            raise FixtureValidationError(f"duplicate ranking case_id: {case_id}")
        lexical = _validate_source_key_list(row["lexical_source_keys"], f"{case_id}.lexical")
        hybrid = _validate_source_key_list(row["hybrid_source_keys"], f"{case_id}.hybrid")
        result[case_id] = {"lexical": lexical, "hybrid": hybrid}
    return result


def load_source_catalog(path: Path) -> dict[str, dict[str, Any]]:
    payload = _load_json(path)
    if not isinstance(payload, dict) or payload.get("schema_version") != "embedding-v2-sources/1":
        raise FixtureValidationError("source catalog must use embedding-v2-sources/1")
    rows = payload.get("sources")
    if not isinstance(rows, list):
        raise FixtureValidationError("sources must be a list")
    result: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise FixtureValidationError(f"source {index} must be an object")
        source_key = row.get("source_key")
        corpus = row.get("corpus")
        content = row.get("content")
        if not isinstance(source_key, str) or not source_key:
            raise FixtureValidationError(f"source {index} has invalid source_key")
        if source_key in result:
            raise FixtureValidationError(f"duplicate source_key: {source_key}")
        if corpus not in ALLOWED_CORPORA:
            raise FixtureValidationError(f"source {source_key} has invalid corpus")
        if not isinstance(content, str) or not content.strip():
            raise FixtureValidationError(f"source {source_key} has empty content")
        result[source_key] = row
    return result


def _validate_source_key_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise FixtureValidationError(f"{field} must be a list of non-empty strings")
    if len(value) != len(set(value)):
        raise FixtureValidationError(f"{field} contains duplicate source keys")
    return list(value)


def _normalize_text(value: str) -> str:
    return _NORMALIZE_RE.sub("", value).casefold()


def validate_cases(
    cases: Sequence[Mapping[str, Any]],
    *,
    source_catalog: Mapping[str, Mapping[str, Any]] | None = None,
) -> None:
    if len(cases) < 36:
        raise FixtureValidationError("V2 evaluation requires at least 36 cases")

    seen: set[str] = set()
    positive_counts = {corpus: 0 for corpus in ALLOWED_CORPORA}
    negative_count = 0
    for index, case in enumerate(cases):
        if set(case) != CASE_FIELDS:
            missing = sorted(CASE_FIELDS - set(case))
            extra = sorted(set(case) - CASE_FIELDS)
            raise FixtureValidationError(f"case {index} fields mismatch; missing={missing}, extra={extra}")

        case_id = case["case_id"]
        if not isinstance(case_id, str) or not case_id:
            raise FixtureValidationError(f"case {index} has invalid case_id")
        if case_id in seen:
            raise FixtureValidationError(f"duplicate case_id: {case_id}")
        seen.add(case_id)

        query = case["query"]
        if not isinstance(query, str) or len(query.strip()) < 6:
            raise FixtureValidationError(f"case {case_id} has an invalid query")
        corpora = _validate_source_key_list(case["corpora"], f"{case_id}.corpora")
        if not corpora or not set(corpora) <= ALLOWED_CORPORA:
            raise FixtureValidationError(f"case {case_id} has invalid corpora")
        expected = _validate_source_key_list(case["expected_source_keys"], f"{case_id}.expected")
        forbidden = _validate_source_key_list(case["forbidden_source_keys"], f"{case_id}.forbidden")
        if set(expected) & set(forbidden):
            raise FixtureValidationError(f"case {case_id} marks a source as expected and forbidden")

        is_no_answer = case["is_no_answer"]
        if not isinstance(is_no_answer, bool):
            raise FixtureValidationError(f"case {case_id}.is_no_answer must be boolean")
        if is_no_answer:
            negative_count += 1
            if expected:
                raise FixtureValidationError(f"no-answer case {case_id} cannot have expected sources")
        else:
            if not expected:
                raise FixtureValidationError(f"positive case {case_id} requires expected sources")
            for corpus in corpora:
                positive_counts[corpus] += 1

        if not isinstance(case["timeline_id"], str) or not case["timeline_id"]:
            raise FixtureValidationError(f"case {case_id} has invalid timeline_id")
        cutoff = case["narrative_sequence_cutoff"]
        if cutoff is not None and (not isinstance(cutoff, int) or isinstance(cutoff, bool) or cutoff < 0):
            raise FixtureValidationError(f"case {case_id} has invalid narrative_sequence_cutoff")
        story_cutoff = case["story_sequence_cutoff"]
        if story_cutoff is not None and (
            not isinstance(story_cutoff, int)
            or isinstance(story_cutoff, bool)
            or story_cutoff < 0
        ):
            raise FixtureValidationError(f"case {case_id} has invalid story_sequence_cutoff")
        perspective = case["perspective"]
        if not isinstance(perspective, dict) or set(perspective) != {
            "kind",
            "observer_character_instance_id",
        }:
            raise FixtureValidationError(f"case {case_id} has invalid perspective")
        if perspective["kind"] not in {"author", "reader", "character_instance"}:
            raise FixtureValidationError(f"case {case_id} has invalid perspective kind")
        character_id = perspective["observer_character_instance_id"]
        if perspective["kind"] == "character_instance" and (
            not isinstance(character_id, str) or not character_id
        ):
            raise FixtureValidationError(
                f"case {case_id} requires an observer_character_instance_id"
            )
        if perspective["kind"] != "character_instance" and character_id is not None:
            raise FixtureValidationError(
                f"case {case_id} must not set observer_character_instance_id"
            )

        if source_catalog is not None:
            query_normalized = _normalize_text(query)
            for source_key in expected:
                source = source_catalog.get(source_key)
                if source is None:
                    raise FixtureValidationError(f"case {case_id} references unknown expected source {source_key}")
                if source.get("corpus") not in corpora:
                    raise FixtureValidationError(f"case {case_id} source corpus is outside its filter")
                content_normalized = _normalize_text(str(source.get("content", "")))
                if query_normalized in content_normalized or content_normalized in query_normalized:
                    raise FixtureValidationError(f"case {case_id} is a self-query copied from {source_key}")

    if negative_count < 12:
        raise FixtureValidationError("V2 evaluation requires at least 12 no-answer cases")
    for corpus, count in sorted(positive_counts.items()):
        if count < 8:
            raise FixtureValidationError(f"V2 evaluation requires at least 8 positive {corpus} cases")


def _recall_at_k(cases: Sequence[Mapping[str, Any]], rankings: Mapping[str, Sequence[str]], k: int) -> float:
    positives = [case for case in cases if not case["is_no_answer"]]
    if not positives:
        return 0.0
    total = 0.0
    for case in positives:
        expected = set(case["expected_source_keys"])
        retrieved = set(rankings[case["case_id"]][:k])
        total += len(expected & retrieved) / len(expected)
    return total / len(positives)


def _reciprocal_rank(case: Mapping[str, Any], ranked: Sequence[str]) -> float:
    expected = set(case["expected_source_keys"])
    for rank, source_key in enumerate(ranked, start=1):
        if source_key in expected:
            return 1.0 / rank
    return 0.0


def _mrr(cases: Sequence[Mapping[str, Any]], rankings: Mapping[str, Sequence[str]]) -> float:
    positives = [case for case in cases if not case["is_no_answer"]]
    if not positives:
        return 0.0
    return sum(_reciprocal_rank(case, rankings[case["case_id"]]) for case in positives) / len(positives)


def evaluate(
    cases: Sequence[Mapping[str, Any]],
    ranking_rows: Mapping[str, Mapping[str, Sequence[str]]],
    *,
    thresholds: GateThresholds = GateThresholds(),
) -> dict[str, Any]:
    validate_cases(cases)
    case_ids = {case["case_id"] for case in cases}
    missing = sorted(case_ids - set(ranking_rows))
    extra = sorted(set(ranking_rows) - case_ids)
    if missing or extra:
        raise FixtureValidationError(f"ranking coverage mismatch; missing={missing}, extra={extra}")

    lexical = {case_id: list(row["lexical"]) for case_id, row in ranking_rows.items()}
    hybrid = {case_id: list(row["hybrid"]) for case_id, row in ranking_rows.items()}
    lexical_recall = _recall_at_k(cases, lexical, 5)
    hybrid_recall = _recall_at_k(cases, hybrid, 5)
    lexical_mrr = _mrr(cases, lexical)
    hybrid_mrr = _mrr(cases, hybrid)

    wins = 0
    regressions = 0
    for case in cases:
        if case["is_no_answer"]:
            continue
        lexical_rr = _reciprocal_rank(case, lexical[case["case_id"]])
        hybrid_rr = _reciprocal_rank(case, hybrid[case["case_id"]])
        if hybrid_rr > lexical_rr:
            wins += 1
        elif hybrid_rr < lexical_rr:
            regressions += 1

    negatives = [case for case in cases if case["is_no_answer"]]
    abstained = sum(not hybrid[case["case_id"]] for case in negatives)
    abstention = abstained / len(negatives) if negatives else 1.0

    leaks: list[dict[str, str]] = []
    for case in cases:
        forbidden = set(case["forbidden_source_keys"])
        for source_key in hybrid[case["case_id"]]:
            if source_key in forbidden:
                leaks.append({"case_id": case["case_id"], "source_key": source_key})

    metrics = {
        "case_count": len(cases),
        "positive_count": len(cases) - len(negatives),
        "no_answer_count": len(negatives),
        "recall_at_5": hybrid_recall,
        "mrr": hybrid_mrr,
        "hybrid_vs_lexical": {
            "lexical_recall_at_5": lexical_recall,
            "hybrid_recall_at_5": hybrid_recall,
            "recall_at_5_delta": hybrid_recall - lexical_recall,
            "lexical_mrr": lexical_mrr,
            "hybrid_mrr": hybrid_mrr,
            "mrr_delta": hybrid_mrr - lexical_mrr,
            "improved_case_count": wins,
            "regressed_case_count": regressions,
        },
        "abstention": abstention,
        "leak_count": len(leaks),
        "leaks": leaks,
    }
    metrics["passed"] = (
        metrics["recall_at_5"] >= thresholds.recall_at_5
        and metrics["mrr"] >= thresholds.mrr
        and metrics["abstention"] >= thresholds.abstention
        and metrics["leak_count"] <= thresholds.max_leak_count
        and metrics["hybrid_vs_lexical"]["recall_at_5_delta"] >= 0.0
        and metrics["hybrid_vs_lexical"]["mrr_delta"] >= 0.0
    )
    _assert_finite_metrics(metrics)
    return metrics


def _assert_finite_metrics(metrics: Mapping[str, Any]) -> None:
    numeric_values = [metrics["recall_at_5"], metrics["mrr"], metrics["abstention"]]
    numeric_values.extend(
        metrics["hybrid_vs_lexical"][key]
        for key in (
            "lexical_recall_at_5",
            "hybrid_recall_at_5",
            "recall_at_5_delta",
            "lexical_mrr",
            "hybrid_mrr",
            "mrr_delta",
        )
    )
    if not all(math.isfinite(value) for value in numeric_values):
        raise FixtureValidationError("evaluation produced a non-finite metric")


def _default_fixture_dirs() -> tuple[Path, Path]:
    root = Path(__file__).resolve().parents[2]
    return root / "backend" / "embedding" / "fixtures", root / "tests" / "fixtures" / "embedding_v2"


def main(argv: Sequence[str] | None = None) -> int:
    runtime_fixture_dir, test_fixture_dir = _default_fixture_dirs()
    parser = argparse.ArgumentParser(description="Evaluate offline embedding V2 source-key rankings")
    parser.add_argument(
        "--cases", type=Path,
        default=runtime_fixture_dir / "evaluation_cases_v2.json",
    )
    parser.add_argument(
        "--rankings", type=Path, default=test_fixture_dir / "rankings.json"
    )
    parser.add_argument(
        "--source-catalog", type=Path,
        default=runtime_fixture_dir / "evaluation_sources_v2.json",
    )
    parser.add_argument("--indent", type=int, default=2)
    args = parser.parse_args(argv)

    cases = load_cases(args.cases)
    source_catalog = load_source_catalog(args.source_catalog)
    validate_cases(cases, source_catalog=source_catalog)
    rankings = load_rankings(args.rankings)
    metrics = evaluate(cases, rankings)
    print(json.dumps(metrics, ensure_ascii=False, indent=args.indent, sort_keys=True))
    return 0 if metrics["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
