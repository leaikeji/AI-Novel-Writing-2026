from __future__ import annotations

import os
from pathlib import Path

import pytest

from .benchmark_current_paths import PROFILES, SAFE_DATABASE_NAME, guarded_engine, run
from .benchmark_vector_operator import TABLE
from .benchmark_hybrid_scale import _FakeAdapter
from .benchmark_churn_scale import _seed_retired


pytestmark = pytest.mark.long_novel


def test_plan52_profiles_freeze_required_scale_points() -> None:
    assert PROFILES["1m"].chapter_count == 500
    assert PROFILES["1m"].fact_count == 2_000
    assert PROFILES["1m"].chunk_count == 1_500
    assert PROFILES["5m"].chapter_count == 2_500
    assert PROFILES["5m"].fact_count == 10_000
    assert PROFILES["5m"].chunk_count == 7_500
    assert TABLE == "plan52_g0_vector_probe"
    assert _FakeAdapter.__name__ == "_FakeAdapter"
    assert _seed_retired.__name__ == "_seed_retired"


def test_plan52_database_guard_rejects_missing_or_wrong_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AI_NOVEL_TEST_DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="required"):
        guarded_engine()
    monkeypatch.setenv(
        "AI_NOVEL_TEST_DATABASE_URL",
        "postgresql+psycopg://invalid/ai_novel_world_2026_test",
    )
    with pytest.raises(RuntimeError, match=SAFE_DATABASE_NAME):
        guarded_engine()


@pytest.mark.skipif(
    os.environ.get("AI_NOVEL_RUN_PLAN52_G0") != "1",
    reason="set AI_NOVEL_RUN_PLAN52_G0=1 for the isolated scale benchmark",
)
def test_current_paths_with_synthetic_long_novels() -> None:
    evidence = run(["small", "1m", "5m"])
    assert evidence["provider_calls"] == 0
    assert [item["profile"] for item in evidence["profiles"]] == ["small", "1m", "5m"]
    for item in evidence["profiles"]:
        paths = item["paths"]
        assert paths["selected_document"]["response_bytes"] < 100_000
        assert paths["list_novels"]["p95_ms"] <= 250
        assert paths["list_novels"]["sql_count_max"] <= 5
        assert paths["assistant_context"]["p95_ms"] <= 1_500
        assert paths["assistant_context"]["peak_tracemalloc_mib"] <= 64
        assert paths["assistant_context"]["response_bytes"] <= 512 * 1024
        assert paths["context_v4"]["p95_ms"] <= 1_500
        assert paths["context_v4"]["sql_count_max"] <= 60
        assert paths["context_v4"]["peak_tracemalloc_mib"] <= 64
        assert paths["context_v4"]["response_bytes"] <= 2 * 1024 * 1024
        assert paths["authority_local_lexical"]["p95_ms"] <= 750
        assert paths["authority_local_lexical"]["sql_count_max"] <= 12
        assert paths["indexed_lexical_current"]["p95_ms"] <= 250
        assert paths["indexed_lexical_current"]["sql_count_max"] <= 20
        assert paths["indexed_lexical_current"]["response_bytes"] <= 64 * 1024
        assert paths["search_novel"]["p95_ms"] <= 500
        assert item["lexical_explain"]["current_unbounded"]["root_rows"] == item["seed"]["semantic_chunk_count"]
    output = os.environ.get("AI_NOVEL_PLAN52_G0_OUTPUT", "").strip()
    if output:
        target = Path(output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            __import__("json").dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
