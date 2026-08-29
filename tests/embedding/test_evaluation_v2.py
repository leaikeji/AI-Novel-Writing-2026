from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.embedding.evaluate_v2 import (
    CASE_FIELDS,
    FixtureValidationError,
    evaluate,
    load_cases,
    load_rankings,
    load_source_catalog,
    validate_cases,
)


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = ROOT / "backend" / "embedding" / "fixtures"
CASES_PATH = FIXTURE_DIR / "evaluation_cases_v2.json"
SOURCE_CATALOG_PATH = FIXTURE_DIR / "evaluation_sources_v2.json"
RANKINGS_PATH = ROOT / "tests" / "fixtures" / "embedding_v2" / "rankings.json"
SCRIPT_PATH = ROOT / "scripts" / "embedding" / "evaluate_v2.py"


def _fixtures():
    cases = load_cases(CASES_PATH)
    rankings = load_rankings(RANKINGS_PATH)
    sources = load_source_catalog(SOURCE_CATALOG_PATH)
    return cases, rankings, sources


def test_v2_fixture_meets_frozen_case_mix_and_schema() -> None:
    cases, _, sources = _fixtures()

    validate_cases(cases, source_catalog=sources)

    assert len(cases) == 36
    assert len({case["case_id"] for case in cases}) == 36
    assert all(set(case) == CASE_FIELDS for case in cases)
    assert sum(case["is_no_answer"] for case in cases) == 12
    for corpus in ("manuscript", "planning", "private_asset"):
        assert sum(not case["is_no_answer"] and corpus in case["corpora"] for case in cases) >= 8


def test_positive_queries_are_not_copied_source_chunks() -> None:
    cases, _, sources = _fixtures()

    for case in cases:
        for source_key in case["expected_source_keys"]:
            query = "".join(case["query"].split()).casefold()
            content = "".join(sources[source_key]["content"].split()).casefold()
            assert query not in content
            assert content not in query

    copied = copy.deepcopy(cases)
    copied[0]["query"] = sources[copied[0]["expected_source_keys"][0]]["content"]
    with pytest.raises(FixtureValidationError, match="self-query"):
        validate_cases(copied, source_catalog=sources)


def test_golden_offline_rankings_report_all_required_metrics() -> None:
    cases, rankings, sources = _fixtures()
    validate_cases(cases, source_catalog=sources)

    metrics = evaluate(cases, rankings)

    assert metrics["case_count"] == 36
    assert metrics["positive_count"] == 24
    assert metrics["no_answer_count"] == 12
    assert metrics["recall_at_5"] == pytest.approx(1.0)
    assert metrics["mrr"] == pytest.approx(1.0)
    assert metrics["hybrid_vs_lexical"]["lexical_recall_at_5"] == pytest.approx(0.5)
    assert metrics["hybrid_vs_lexical"]["recall_at_5_delta"] == pytest.approx(0.5)
    assert metrics["hybrid_vs_lexical"]["improved_case_count"] == 21
    assert metrics["hybrid_vs_lexical"]["regressed_case_count"] == 0
    assert metrics["abstention"] == pytest.approx(1.0)
    assert metrics["leak_count"] == 0
    assert metrics["leaks"] == []
    assert metrics["passed"] is True


def test_forbidden_result_counts_as_leak_and_breaks_abstention_gate() -> None:
    cases, rankings, _ = _fixtures()
    bad_rankings = copy.deepcopy(rankings)
    forbidden = next(case for case in cases if case["case_id"] == "n01-future-chapter")[
        "forbidden_source_keys"
    ][0]
    bad_rankings["n01-future-chapter"]["hybrid"] = [forbidden]

    metrics = evaluate(cases, bad_rankings)

    assert metrics["abstention"] == pytest.approx(11 / 12)
    assert metrics["leak_count"] == 1
    assert metrics["leaks"] == [
        {"case_id": "n01-future-chapter", "source_key": forbidden}
    ]
    assert metrics["passed"] is False


def test_rankings_must_cover_every_case_exactly() -> None:
    cases, rankings, _ = _fixtures()
    rankings.pop("m01-sabotage-location")

    with pytest.raises(FixtureValidationError, match="coverage mismatch"):
        evaluate(cases, rankings)


def test_cli_runs_offline_and_emits_json_metrics() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--indent", "0"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert completed.returncode == 0, completed.stderr
    metrics = json.loads(completed.stdout)
    assert metrics["recall_at_5"] == pytest.approx(1.0)
    assert metrics["mrr"] == pytest.approx(1.0)
    assert metrics["abstention"] == pytest.approx(1.0)
    assert metrics["leak_count"] == 0
    assert metrics["hybrid_vs_lexical"]["recall_at_5_delta"] > 0


def test_evaluator_has_no_cloud_or_http_client_dependency() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "backend.embedding.adapter" not in source
    assert "dashscope" not in source.casefold()
    assert "httpx" not in source
    assert "requests" not in source
    assert "urllib.request" not in source
