from __future__ import annotations

import copy
from pathlib import Path

import pytest

from scripts.tts.nano_short_regression import (
    MODEL_FINGERPRINT_SHA256,
    NanoShortRegressionError,
    RESULT_SCHEMA_VERSION,
    load_regression_fixture,
    validate_regression_result,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = (
    REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "narration"
    / "short-attribution-regression-v1.json"
)


def _result() -> dict[str, object]:
    fixture = load_regression_fixture(FIXTURE_PATH)
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "fixture_id": fixture.fixture_id,
        "fixture_sha256": fixture.fixture_sha256,
        "source_chapter_fixture_sha256": fixture.source_chapter_fixture_sha256,
        "model_fingerprint_sha256": MODEL_FINGERPRINT_SHA256,
        "preset_id": fixture.preset_id,
        "language": fixture.language,
        "speaker_kind": fixture.speaker_kind,
        "segment_kind": fixture.segment_kind,
        "policy_version": fixture.policy_version,
        "selected_strategy": "fixed_seed_1",
        "cases": [
            {
                "case_id": case.case_id,
                "text_sha256": case.text_sha256,
                "occurrence_count": case.occurrence_count,
                "duration_ms": min(1_200, case.maximum_duration_ms),
                "audio_sha256": f"{index + 1:064x}",
            }
            for index, case in enumerate(fixture.cases)
        ],
    }


def test_result_requires_every_case_once_and_returns_sorted_audio_hashes() -> None:
    fixture = load_regression_fixture(FIXTURE_PATH)

    hashes = validate_regression_result(
        fixture,
        _result(),
        selected_strategy="fixed_seed_1",
    )

    assert hashes == tuple(f"{index + 1:064x}" for index in range(len(fixture.cases)))


@pytest.mark.parametrize(
    "mutation,error",
    [
        ("missing_case", "REGRESSION_RESULT_CASES_INVALID"),
        ("duplicate_case", "REGRESSION_RESULT_CASE_INVALID"),
        ("wrong_text", "REGRESSION_RESULT_CASE_INVALID"),
        ("over_duration", "REGRESSION_RESULT_CASE_INVALID"),
        ("wrong_model", "REGRESSION_RESULT_BINDING_INVALID"),
        ("wrong_strategy", "REGRESSION_RESULT_BINDING_INVALID"),
        ("duplicate_audio", "REGRESSION_RESULT_CASES_INVALID"),
    ],
)
def test_result_fails_closed_on_incomplete_or_stale_evidence(
    mutation: str,
    error: str,
) -> None:
    fixture = load_regression_fixture(FIXTURE_PATH)
    payload = copy.deepcopy(_result())
    cases = payload["cases"]
    assert isinstance(cases, list)
    if mutation == "missing_case":
        cases.pop()
    elif mutation == "duplicate_case":
        cases[1]["case_id"] = cases[0]["case_id"]
    elif mutation == "wrong_text":
        cases[0]["text_sha256"] = "f" * 64
    elif mutation == "over_duration":
        cases[0]["duration_ms"] = fixture.cases[0].maximum_duration_ms + 1
    elif mutation == "wrong_model":
        payload["model_fingerprint_sha256"] = "f" * 64
    elif mutation == "wrong_strategy":
        payload["selected_strategy"] = "greedy"
    elif mutation == "duplicate_audio":
        cases[1]["audio_sha256"] = cases[0]["audio_sha256"]

    with pytest.raises(NanoShortRegressionError, match=error):
        validate_regression_result(
            fixture,
            payload,
            selected_strategy="fixed_seed_1",
        )
