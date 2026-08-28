"""Validate the bounded real-Nano short-attribution regression corpus.

The fixture contains project-owned text only.  Runtime audio remains outside
Git; a result binds each distinct case to the selected synthesis policy,
duration, and actual audio digest without embedding paths or audio bytes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Final, Mapping


FIXTURE_SCHEMA_VERSION: Final = (
    "moss-tts-nano-short-attribution-regression/1.0"
)
RESULT_SCHEMA_VERSION: Final = (
    "moss-tts-nano-short-attribution-regression-result/1.0"
)
MODEL_FINGERPRINT_SHA256: Final = (
    "3c76f3e9e1381699c5555287cf66eeb023632d0c3ee94adc6d8ae1b1d455fd7d"
)
_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")


class NanoShortRegressionError(ValueError):
    """Raised when a fixture or runtime result is not exactly bound."""


@dataclass(frozen=True, slots=True)
class RegressionCase:
    case_id: str
    text: str
    text_sha256: str
    maximum_duration_ms: int
    occurrence_count: int
    required_human_checks: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RegressionFixture:
    fixture_id: str
    fixture_sha256: str
    source_chapter_fixture_sha256: str
    preset_id: str
    language: str
    speaker_kind: str
    segment_kind: str
    policy_version: str
    allowed_strategies: tuple[str, ...]
    cases: tuple[RegressionCase, ...]


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _mapping(value: object, *, code: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        raise NanoShortRegressionError(code)
    return value


def _sha256(value: object, *, code: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise NanoShortRegressionError(code)
    return value


def load_regression_fixture(path: Path) -> RegressionFixture:
    if not isinstance(path, Path) or not path.is_absolute():
        raise NanoShortRegressionError("REGRESSION_FIXTURE_PATH_INVALID")
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise NanoShortRegressionError("REGRESSION_FIXTURE_INVALID") from None
    root = _mapping(payload, code="REGRESSION_FIXTURE_INVALID")
    if root.get("schema_version") != FIXTURE_SCHEMA_VERSION:
        raise NanoShortRegressionError("REGRESSION_FIXTURE_SCHEMA_INVALID")
    authorization = _mapping(
        root.get("authorization"), code="REGRESSION_FIXTURE_AUTHORIZATION_INVALID"
    )
    if (
        authorization.get("text_owner") != "project_owned"
        or authorization.get("authorized_for_tts") is not True
        or authorization.get("contains_private_reference_audio") is not False
    ):
        raise NanoShortRegressionError("REGRESSION_FIXTURE_AUTHORIZATION_INVALID")
    source = _mapping(
        root.get("source_chapter_fixture"), code="REGRESSION_SOURCE_FIXTURE_INVALID"
    )
    source_sha256 = _sha256(
        source.get("sha256"), code="REGRESSION_SOURCE_FIXTURE_INVALID"
    )
    model_scope = _mapping(
        root.get("model_scope"), code="REGRESSION_MODEL_SCOPE_INVALID"
    )
    allowed = model_scope.get("allowed_strategies")
    if (
        model_scope.get("strategy_status") != "author_confirmed"
        or not isinstance(allowed, list)
        or allowed != ["fixed_seed_1"]
    ):
        raise NanoShortRegressionError("REGRESSION_MODEL_SCOPE_INVALID")
    rows = root.get("cases")
    if not isinstance(rows, list) or not rows:
        raise NanoShortRegressionError("REGRESSION_CASES_INVALID")
    cases: list[RegressionCase] = []
    seen: set[str] = set()
    for raw_case in rows:
        case = _mapping(raw_case, code="REGRESSION_CASE_INVALID")
        case_id = case.get("case_id")
        text = case.get("text")
        duration = case.get("maximum_duration_ms")
        occurrences = case.get("occurrence_count")
        checks = case.get("required_human_checks")
        if (
            type(case_id) is not str
            or not case_id
            or case_id in seen
            or type(text) is not str
            or not text
            or type(duration) is not int
            or duration <= 0
            or type(occurrences) is not int
            or occurrences <= 0
            or not isinstance(checks, list)
            or not checks
            or any(type(item) is not str or not item for item in checks)
            or len(set(checks)) != len(checks)
            or "intelligible_mandarin" not in checks
            or "exact_words" not in checks
        ):
            raise NanoShortRegressionError("REGRESSION_CASE_INVALID")
        expected_text_hash = _sha256_bytes(text.encode("utf-8"))
        if _sha256(case.get("text_sha256"), code="REGRESSION_CASE_INVALID") != (
            expected_text_hash
        ):
            raise NanoShortRegressionError("REGRESSION_CASE_TEXT_MISMATCH")
        seen.add(case_id)
        cases.append(
            RegressionCase(
                case_id=case_id,
                text=text,
                text_sha256=expected_text_hash,
                maximum_duration_ms=duration,
                occurrence_count=occurrences,
                required_human_checks=tuple(checks),
            )
        )
    return RegressionFixture(
        fixture_id=str(root.get("fixture_id")),
        fixture_sha256=_sha256_bytes(raw),
        source_chapter_fixture_sha256=source_sha256,
        preset_id=str(model_scope.get("preset_id")),
        language=str(model_scope.get("language")),
        speaker_kind=str(model_scope.get("speaker_kind")),
        segment_kind=str(model_scope.get("segment_kind")),
        policy_version=str(model_scope.get("policy_version")),
        allowed_strategies=tuple(allowed),
        cases=tuple(cases),
    )


def validate_regression_result(
    fixture: RegressionFixture,
    payload: Mapping[str, object],
    *,
    selected_strategy: str,
) -> tuple[str, ...]:
    """Return sorted audio hashes after exact, fail-closed validation."""

    if (
        type(fixture) is not RegressionFixture
        or type(selected_strategy) is not str
        or selected_strategy not in fixture.allowed_strategies
        or not isinstance(payload, dict)
        or payload.get("schema_version") != RESULT_SCHEMA_VERSION
        or payload.get("fixture_id") != fixture.fixture_id
        or payload.get("fixture_sha256") != fixture.fixture_sha256
        or payload.get("source_chapter_fixture_sha256")
        != fixture.source_chapter_fixture_sha256
        or payload.get("model_fingerprint_sha256")
        != MODEL_FINGERPRINT_SHA256
        or payload.get("preset_id") != fixture.preset_id
        or payload.get("language") != fixture.language
        or payload.get("speaker_kind") != fixture.speaker_kind
        or payload.get("segment_kind") != fixture.segment_kind
        or payload.get("policy_version") != fixture.policy_version
        or payload.get("selected_strategy") != selected_strategy
    ):
        raise NanoShortRegressionError("REGRESSION_RESULT_BINDING_INVALID")
    rows = payload.get("cases")
    if not isinstance(rows, list) or len(rows) != len(fixture.cases):
        raise NanoShortRegressionError("REGRESSION_RESULT_CASES_INVALID")
    expected = {case.case_id: case for case in fixture.cases}
    seen: set[str] = set()
    audio_hashes: list[str] = []
    for raw_row in rows:
        row = _mapping(raw_row, code="REGRESSION_RESULT_CASE_INVALID")
        case_id = row.get("case_id")
        duration = row.get("duration_ms")
        if (
            type(case_id) is not str
            or case_id not in expected
            or case_id in seen
            or row.get("text_sha256") != expected[case_id].text_sha256
            or row.get("occurrence_count") != expected[case_id].occurrence_count
            or type(duration) is not int
            or duration <= 0
            or duration > expected[case_id].maximum_duration_ms
        ):
            raise NanoShortRegressionError("REGRESSION_RESULT_CASE_INVALID")
        audio_hashes.append(
            _sha256(
                row.get("audio_sha256"),
                code="REGRESSION_RESULT_AUDIO_HASH_INVALID",
            )
        )
        seen.add(case_id)
    if seen != set(expected) or len(set(audio_hashes)) != len(audio_hashes):
        raise NanoShortRegressionError("REGRESSION_RESULT_CASES_INVALID")
    return tuple(sorted(audio_hashes))


__all__ = [
    "FIXTURE_SCHEMA_VERSION",
    "MODEL_FINGERPRINT_SHA256",
    "NanoShortRegressionError",
    "RESULT_SCHEMA_VERSION",
    "RegressionCase",
    "RegressionFixture",
    "load_regression_fixture",
    "validate_regression_result",
]
