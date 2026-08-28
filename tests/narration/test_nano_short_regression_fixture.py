from __future__ import annotations

import hashlib
import json
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = (
    REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "narration"
    / "short-attribution-regression-v1.json"
)
EXPECTED_CASES = {
    "known-lin-colon": ("林晚说道：", 3_200, 2),
    "known-shen-colon": ("沈川说道：", 3_200, 2),
    "other-sutang-colon": ("苏棠说道：", 3_200, 1),
    "other-ouyangche-colon": ("欧阳澈说道：", 3_600, 1),
    "punct-lin-period": ("林晚说道。", 3_200, 1),
    "punct-shen-period": ("沈川说道。", 3_200, 1),
    "normal-station": (
        "站台上的灯忽然闪了一次，四周仍然没有人影。",
        9_600,
        1,
    ),
    "normal-truck": (
        "远处传来货车压过石子的声音，随后又恢复安静。",
        10_000,
        1,
    ),
}


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load() -> dict[str, object]:
    value = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_fixture_is_frozen_authorized_and_scoped_to_zhiming() -> None:
    fixture = _load()

    assert fixture["schema_version"] == (
        "moss-tts-nano-short-attribution-regression/1.0"
    )
    assert fixture["fixture_id"] == "t4-k-zhiming-short-attribution-v1"
    assert fixture["authorization"] == {
        "text_owner": "project_owned",
        "authorization_reference": (
            "project-original-t4-k-short-attribution-v1"
        ),
        "authorized_for_tts": True,
        "contains_private_reference_audio": False,
    }
    assert fixture["model_scope"] == {
        "preset_id": "onnx.Zhiming",
        "language": "zh-CN",
        "speaker_kind": "narrator",
        "segment_kind": "narration",
        "policy_version": "nano-zh-attribution-sampling/2",
        "strategy_status": "author_confirmed",
        "allowed_strategies": ["fixed_seed_1"],
    }


def test_fixture_binds_existing_chapter_without_rewriting_it() -> None:
    fixture = _load()
    source = fixture["source_chapter_fixture"]
    assert isinstance(source, dict)
    source_path = REPOSITORY_ROOT / str(source["path"])

    assert source_path == (
        REPOSITORY_ROOT / "tests" / "fixtures" / "narration" / "chapter-e2e-v2.json"
    )
    assert _sha256(source_path.read_bytes()) == source["sha256"]


def test_fixture_text_hashes_duration_limits_and_occurrences_are_exact() -> None:
    fixture = _load()
    rows = fixture["cases"]
    assert isinstance(rows, list)
    assert len(rows) == len(EXPECTED_CASES)
    by_id = {str(row["case_id"]): row for row in rows}
    assert set(by_id) == set(EXPECTED_CASES)

    for case_id, (text, maximum_duration_ms, occurrence_count) in EXPECTED_CASES.items():
        row = by_id[case_id]
        assert row["text"] == text
        assert row["text_sha256"] == _sha256(text.encode("utf-8"))
        assert row["maximum_duration_ms"] == maximum_duration_ms
        assert row["occurrence_count"] == occurrence_count
        checks = row["required_human_checks"]
        assert isinstance(checks, list)
        assert "intelligible_mandarin" in checks
        assert "exact_words" in checks

    assert sum(row[2] for row in EXPECTED_CASES.values()) == 10


def test_fixture_contains_no_audio_or_runtime_output_paths() -> None:
    raw = FIXTURE_PATH.read_text(encoding="utf-8")

    assert "audio_sha256" not in raw
    assert "/private/tmp" not in raw
    assert "/tmp/" not in raw
    assert ".wav" not in raw
    assert ".m4a" not in raw
