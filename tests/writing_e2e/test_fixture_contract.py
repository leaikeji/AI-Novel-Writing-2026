from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from uuid import UUID


FIXTURE_ROOT = (
    Path(__file__).resolve().parents[1] / "fixtures" / "writing_e2e_v1"
)


def _load(name: str) -> dict:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _all_keys(value: object) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _all_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _all_keys(child)


def test_manifest_freezes_every_content_file_and_suite_hash() -> None:
    manifest = _load("manifest.json")

    assert manifest["schema_version"] == "writing-e2e-manifest/1"
    assert manifest["rights_basis"] == "project-synthetic"
    assert manifest["contains_real_user_content"] is False
    assert manifest["external_model_policy"] == {
        "default_state": "disabled",
        "enablement": "explicit_per_run_authorization_required",
        "authorization_record_location": "separate_run_manifest",
        "fixture_manifest_is_authorization": False,
    }

    entries = manifest["content_files"]
    paths = [entry["path"] for entry in entries]
    assert paths == sorted(paths)
    assert paths == [
        "chapter_plans.json",
        "novel.json",
        "private_assets.json",
        "retrieval_labels.json",
    ]

    digest_lines = []
    for entry in entries:
        actual = _sha256(FIXTURE_ROOT / entry["path"])
        assert actual == entry["sha256"]
        digest_lines.append(f"{entry['path']}:{actual}\n")

    suite_digest = hashlib.sha256("".join(digest_lines).encode()).hexdigest()
    assert suite_digest == manifest["suite_sha256"]


def test_stable_entity_ids_are_unique_and_alias_keeps_character_identity() -> None:
    fixture = _load("novel.json")
    assets = _load("private_assets.json")["assets"]
    novel = fixture["novel"]
    timelines = fixture["timelines"]
    characters = fixture["characters"]
    instances = fixture["character_instances"]
    chapters = fixture["chapters"]

    uuid_values = [novel["id"]]
    uuid_values.extend(item["id"] for item in timelines)
    uuid_values.extend(item["id"] for item in characters)
    uuid_values.extend(alias["id"] for item in characters for alias in item["aliases"])
    uuid_values.extend(item["id"] for item in instances)
    uuid_values.extend(item["id"] for item in chapters)
    uuid_values.extend(
        value for asset in assets for value in (asset["id"], asset["version_id"])
    )

    assert len(uuid_values) == len(set(uuid_values))
    assert all(str(UUID(value)) == value for value in uuid_values)

    timeline_ids = {item["id"] for item in timelines}
    character_ids = {item["id"] for item in characters}
    assert novel["default_timeline_id"] in timeline_ids
    assert all(item["timeline_id"] in timeline_ids for item in instances)
    assert all(item["character_id"] in character_ids for item in instances)
    assert all(item["timeline_id"] in timeline_ids for item in chapters)

    protagonist = next(item for item in characters if item["key"] == "character:shen-yanzhou")
    assert protagonist["official_name"] == "沈砚舟"
    assert [alias["name"] for alias in protagonist["aliases"]] == ["周砚"]
    assert protagonist["identity_layers"]["public_identity"] == "市档案馆数字化修复员"
    assert protagonist["identity_layers"]["true_identity_visibility"] == (
        "author_secret_until_chapter_3"
    )


def test_private_asset_policies_cover_required_fallback_and_hard_exclusion() -> None:
    assets = _load("private_assets.json")["assets"]
    policies = {asset["policy"] for asset in assets}

    assert policies == {"required", "preferred", "context_only", "prohibited"}

    required = next(asset for asset in assets if asset["policy"] == "required")
    prohibited = next(asset for asset in assets if asset["policy"] == "prohibited")
    unbound = next(asset for asset in assets if not asset["bound_to_fixture_novel"])

    assert required["bound_to_fixture_novel"] is True
    assert required["index_eligible"] is True
    assert prohibited["bound_to_fixture_novel"] is True
    assert prohibited["index_eligible"] is False
    assert unbound["index_eligible"] is False

    stable_ids = [value for asset in assets for value in (asset["id"], asset["version_id"])]
    assert len(stable_ids) == len(set(stable_ids))
    assert all(str(UUID(value)) == value for value in stable_ids)


def test_all_fixture_payloads_declare_same_synthetic_rights_and_identity() -> None:
    for name in (
        "novel.json",
        "private_assets.json",
        "chapter_plans.json",
        "retrieval_labels.json",
    ):
        payload = _load(name)
        assert payload["fixture_id"] == "writing-e2e-v1-archive-1988"
        assert payload["rights_basis"] == "project-synthetic"


def test_three_chapter_inputs_target_2000_chars_without_prewritten_manuscript() -> None:
    fixture = _load("chapter_plans.json")
    contract = fixture["global_generation_contract"]
    chapters = fixture["chapters"]

    assert contract["target_visible_chars"] == 2000
    assert contract["accepted_visible_char_range"] == {
        "minimum": 1700,
        "maximum": 2300,
    }
    protagonist_ref = contract["character_reference_contract"][0]
    assert protagonist_ref == {
        "character_id": "37000000-0000-4000-8000-000000000201",
        "official_name": "沈砚舟",
        "known_aliases": ["周砚"],
    }
    assert len(chapters) == 3
    assert [chapter["narrative_sequence"] for chapter in chapters] == [1, 2, 3]
    assert [chapter["story_sequence_cutoff"] for chapter in chapters] == [1, 2, 3]

    forbidden_payload_keys = {"body", "content", "manuscript", "manuscript_text"}
    assert forbidden_payload_keys.isdisjoint(set(_all_keys(fixture)))
    for chapter in chapters:
        generation_input = chapter["generation_input"]
        assert len(generation_input["chapter_brief"]) < 500
        assert len(generation_input["scene_requirements"]) >= 5
        assert generation_input["required_asset_keys"] == [
            "asset:archive-blue-ticket:v1"
        ]


def test_retrieval_labels_reference_existing_fixture_entities() -> None:
    novel = _load("novel.json")
    assets = _load("private_assets.json")["assets"]
    labels = _load("retrieval_labels.json")

    chapter_keys = {chapter["key"] for chapter in novel["chapters"]}
    source_ids = {source["id"] for source in novel["source_records"]}
    fact_ids = {fact["id"] for fact in novel["fact_seeds"]}
    character_ids = {character["id"] for character in novel["characters"]}
    alias_ids = {
        alias["id"]
        for character in novel["characters"]
        for alias in character["aliases"]
    }
    asset_keys = {asset["key"] for asset in assets}

    all_labels = labels["positive_labels"] + labels["negative_labels"]
    label_ids = [label["id"] for label in all_labels]
    assert len(label_ids) == len(set(label_ids))
    assert all(label["target_chapter_key"] in chapter_keys for label in all_labels)

    for label in all_labels:
        assert set(label.get("expected_source_ids", [])).issubset(source_ids)
        assert set(label.get("forbidden_source_ids", [])).issubset(source_ids)
        assert set(label.get("expected_fact_ids", [])).issubset(fact_ids)
        assert set(label.get("forbidden_fact_ids", [])).issubset(fact_ids)
        assert set(label.get("expected_character_ids", [])).issubset(character_ids)
        assert set(label.get("expected_alias_ids", [])).issubset(alias_ids)
        assert set(label.get("expected_asset_keys", [])).issubset(asset_keys)
        assert set(label.get("forbidden_asset_keys", [])).issubset(asset_keys)

    assert len(labels["positive_labels"]) >= 6
    assert len(labels["negative_labels"]) >= 7

    canonical_fixture_text = "\n".join(
        (FIXTURE_ROOT / name).read_text(encoding="utf-8")
        for name in ("novel.json", "private_assets.json")
    )
    for label in labels["negative_labels"]:
        for sentinel in label.get("forbidden_text_sentinels", []):
            assert sentinel in canonical_fixture_text


def test_secret_timeline_revision_and_asset_boundaries_are_explicit() -> None:
    novel = _load("novel.json")
    plans = _load("chapter_plans.json")["chapters"]
    labels = _load("retrieval_labels.json")["negative_labels"]

    fact_by_id = {fact["id"]: fact for fact in novel["fact_seeds"]}
    chapter_by_key = {chapter["chapter_key"]: chapter for chapter in plans}
    k17 = fact_by_id["fact:main:ch03:k17-reveal"]

    assert k17["available_from_narrative_sequence"] == 3
    assert k17["visibility"] == "author_secret_before_reveal"
    assert k17["id"] in chapter_by_key["chapter:main:01"]["generation_input"][
        "forbidden_fact_ids"
    ]
    assert k17["id"] in chapter_by_key["chapter:main:02"]["generation_input"][
        "forbidden_fact_ids"
    ]
    assert k17["id"] in chapter_by_key["chapter:main:03"]["generation_input"][
        "allowed_reveal_fact_ids"
    ]

    sibling = fact_by_id["fact:sibling:white-gull-key"]
    assert sibling["timeline_id"] != novel["novel"]["default_timeline_id"]
    assert sibling["visibility"] == "sibling_timeline_only"

    boundary_kinds = {label["boundary_kind"] for label in labels}
    assert boundary_kinds == {
        "future_knowledge",
        "sibling_timeline",
        "retired_revision",
        "prohibited_private_asset",
        "unbound_private_asset",
        "cross_novel",
    }
