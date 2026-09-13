#!/usr/bin/env python3
"""Validate Plan 74 fixture JSON, provenance, hashes and exact expectations."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any


FIXTURE_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = FIXTURE_DIR.parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.private_library.lexicon_contracts import LexiconEntry  # noqa: E402
from backend.private_library.lexicon_matcher import (  # noqa: E402
    LexiconRuleSource,
    extract_markdown_visible_text,
    match_lexicon,
)
from backend.private_library.maintenance_contracts import LibraryCaptureSource  # noqa: E402
from generate_performance_fixture import build_fixture  # noqa: E402


JSON_FILES = (
    "matching-cases.json",
    "lifecycle-cases.json",
    "maintenance-cases.json",
    "performance-spec.json",
)


def _load(name: str) -> dict[str, Any]:
    value = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict), f"{name} root must be an object"
    return value


def _assert_synthetic(name: str, value: dict[str, Any]) -> None:
    source = value.get("source")
    assert source == {
        "kind": "synthetic-project-fixture",
        "license": "synthetic-project-fixture",
        "contains_external_text": False,
        "contains_user_content": False,
    }, f"{name} must carry the exact synthetic source boundary"


def _compact_hits(report: Any) -> list[dict[str, Any]]:
    return [{
        "entry_id": hit.entry_id,
        "matched_text": hit.matched_text,
        "start_utf16": hit.start_utf16,
        "end_utf16": hit.end_utf16,
        "count": hit.count,
        "window": hit.window,
    } for hit in report.hits]


def validate_matching(value: dict[str, Any]) -> None:
    _assert_synthetic("matching-cases.json", value)
    identifiers: set[str] = set()
    for case in value["cases"]:
        assert case["id"] not in identifiers
        identifiers.add(case["id"])
        rules = [LexiconRuleSource(
            asset_id=rule["asset_id"],
            asset_version_id=rule["asset_version_id"],
            priority=rule["priority"],
            entry=LexiconEntry.model_validate(rule["entry"]),
        ) for rule in case["rules"]]
        source = case["input"]["markdown"]
        expected = case["expected"]
        visible = extract_markdown_visible_text(source)
        report = match_lexicon(source, rules)
        assert visible.text == expected["visible_text"], case["id"]
        assert report.status == expected["status"], case["id"]
        assert report.visible_character_count == expected["visible_character_count"], case["id"]
        assert _compact_hits(report) == expected["hits"], case["id"]


def validate_lifecycle(value: dict[str, Any]) -> None:
    _assert_synthetic("lifecycle-cases.json", value)
    assert len(value["cases"]) >= 8
    assert len({case["id"] for case in value["cases"]}) == len(value["cases"])
    source_case = next(case for case in value["cases"] if case["id"] == "LIFE-UNSYNCED-SELECTION-SOURCE")
    selected = source_case["input"]["selected_text"]
    source = LibraryCaptureSource.model_validate(source_case["input"]["source"])
    assert source.kind == "unsynced_selection"
    assert source.text_sha256 == hashlib.sha256(selected.encode("utf-8")).hexdigest()


def validate_maintenance(value: dict[str, Any]) -> None:
    _assert_synthetic("maintenance-cases.json", value)
    cases = value["cases"]
    assert len(cases) >= 20
    assert len({case["id"] for case in cases}) == len(cases)
    classes = {case["class"] for case in cases}
    assert {
        "direct_command",
        "consultation",
        "ambiguous_preference",
        "embedded_material_instruction",
        "tool_failure",
        "undo",
        "undo_conflict",
    } <= classes
    assert all(case["author_input"].strip() for case in cases)
    assert all("result" in case["expected"] for case in cases)
    non_writes = {
        "answer_only", "awaiting_author_acceptance", "need_target",
        "need_selection", "conflict", "refused", "need_trusted_scope",
        "need_novel_scope", "unknown_until_receipt_found",
    }
    for case in cases:
        if case["expected"]["result"] in non_writes:
            assert case["expected"].get("write_count", 0) == 0, case["id"]


def validate_performance(value: dict[str, Any]) -> None:
    _assert_synthetic("performance-spec.json", value)
    generated = build_fixture()
    _assert_synthetic("generated performance fixture", generated)
    contract = value["generator_contract"]
    rules = generated["input"]["rules"]
    source = generated["input"]["markdown"]
    assert len(rules) == contract["rule_count"] == 1_000
    assert len(source) == contract["source_codepoint_count"] == 10_000
    parsed = [LexiconRuleSource(
        asset_id=rule["asset_id"],
        asset_version_id=rule["asset_version_id"],
        priority=rule["priority"],
        entry=LexiconEntry.model_validate(rule["entry"]),
    ) for rule in rules]
    report = match_lexicon(source, parsed)
    expected = generated["expected"]
    assert report.status == expected["status"]
    assert report.scanned_rule_count == expected["scanned_rule_count"]
    assert report.omitted_rule_count == expected["omitted_rule_count"]
    assert report.visible_character_count == expected["visible_character_count"]
    assert len(report.hits) == expected["hit_count"]
    assert [hit.entry_id for hit in report.hits] == expected["hit_entry_ids_in_order"]
    assert [hit.start_utf16 for hit in report.hits] == expected["hit_start_utf16_in_order"]
    assert value["expected"] == {
        key: expected[key] for key in value["expected"]
    }


def validate_manifest(value: dict[str, Any]) -> None:
    _assert_synthetic("manifest.json", value)
    expected_paths = set(JSON_FILES) | {
        "README.md",
        "generate_performance_fixture.py",
        "validate_fixtures.py",
    }
    entries = value["content_files"]
    assert {entry["path"] for entry in entries} == expected_paths
    for entry in entries:
        payload = (FIXTURE_DIR / entry["path"]).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == entry["sha256"], entry["path"]


def main() -> None:
    loaded = {name: _load(name) for name in JSON_FILES}
    validate_matching(loaded["matching-cases.json"])
    validate_lifecycle(loaded["lifecycle-cases.json"])
    validate_maintenance(loaded["maintenance-cases.json"])
    validate_performance(loaded["performance-spec.json"])
    validate_manifest(_load("manifest.json"))
    print(json.dumps({
        "status": "PASS",
        "json_files": len(JSON_FILES) + 1,
        "matching_cases": len(loaded["matching-cases.json"]["cases"]),
        "lifecycle_cases": len(loaded["lifecycle-cases.json"]["cases"]),
        "maintenance_cases": len(loaded["maintenance-cases.json"]["cases"]),
        "performance_rules": 1_000,
        "performance_characters": 10_000,
        "source_license": "synthetic-project-fixture",
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
