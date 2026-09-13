#!/usr/bin/env python3
"""Emit the deterministic Plan 74 1000-rule/10000-character fixture.

The generator never writes files and uses no random or external input.  Tests
may import ``build_fixture`` to avoid storing a large duplicate JSON payload.
"""

from __future__ import annotations

import json


RULE_COUNT = 1_000
TEXT_CHARACTER_COUNT = 10_000
ASSET_ID = "74000000-0000-4000-8000-000000000501"
ASSET_VERSION_ID = "74000000-0000-4000-8000-000000001501"


def _entry(index: int) -> dict[str, object]:
    action = ("forbid", "watch", "recommend")[index % 3]
    value: dict[str, object] = {
        "entry_id": f"perf_{index:04d}",
        "term": f"合成词{index:04d}",
        "action": action,
        "state": "active",
        "match_mode": "phrase",
        "case_sensitive": True,
        "variants": [],
        "categories": ["性能语料"],
        "genres": [],
        "eras": [],
        "positions": ["body"],
        "note": "项目合成性能规则",
        "example": "",
        "counterexample": "",
        "replacement_hint": "",
        "source_refs": [{
            "source_type": "author",
            "label": "synthetic-project-fixture",
            "evidence_scope": "deterministic-performance-corpus",
            "verified_popularity": False,
        }],
    }
    if action == "watch":
        value["watch_threshold"] = {"count": 3, "window_characters": 1_000}
    return value


def _insert(buffer: list[str], start: int, value: str) -> None:
    buffer[start:start + len(value)] = value


def build_fixture() -> dict[str, object]:
    text = ["墙"] * TEXT_CHARACTER_COUNT
    _insert(text, 100, "合成词0000")
    _insert(text, 300, "合成词0001")
    _insert(text, 360, "合成词0001")
    _insert(text, 420, "合成词0001")
    _insert(text, 1_000, "合成词0002")
    _insert(text, 9_000, "合成词0999")
    rules = [{
        "asset_id": ASSET_ID,
        "asset_version_id": ASSET_VERSION_ID,
        "priority": RULE_COUNT - index,
        "entry": _entry(index),
    } for index in range(RULE_COUNT)]
    return {
        "schema_version": "private-library-performance-fixture/1",
        "fixture_id": "plan74-performance-1000x10000-v1",
        "source": {
            "kind": "synthetic-project-fixture",
            "license": "synthetic-project-fixture",
            "contains_external_text": False,
            "contains_user_content": False,
        },
        "input": {"markdown": "".join(text), "rules": rules},
        "expected": {
            "status": "complete",
            "scanned_rule_count": RULE_COUNT,
            "omitted_rule_count": 0,
            "visible_character_count": TEXT_CHARACTER_COUNT,
            "hit_count": 5,
            "hit_entry_ids_in_order": [
                "perf_0000", "perf_0001", "perf_0001", "perf_0001", "perf_0999",
            ],
            "hit_start_utf16_in_order": [100, 300, 360, 420, 9_000],
        },
    }


if __name__ == "__main__":
    print(json.dumps(build_fixture(), ensure_ascii=False, separators=(",", ":")))
