"""Frozen Plan 58 D/S/E scenarios and resolver-only deterministic checks."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import UUID

from backend.writing_skills.catalog import load_catalog, packaged_approvals
from backend.writing_skills.contracts import (
    CapabilityCatalog,
    CapabilityDeclaration,
    LoadedCapability,
    MethodBlock,
    MethodPreferences,
    Scope,
    SourceItem,
    TaskModelInputProjectionV1,
    canonical_hash,
)
from backend.writing_skills.resolver import resolve_methods


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).with_name("fixtures") / "routing_scenarios.json"
OWNER = UUID("29cf94d9-a5c9-54ec-912c-5dfff8738c4c")
WORKSPACE = UUID("f0e2e632-bc99-52d2-9916-bb906aa4da6e")
SCOPE_ID = UUID("11111111-1111-4111-8111-111111111111")
FORMAL_IDS = frozenset({"suspense-writing", "golden-finger-writing"})
CREATIVE_TASKS = (
    "direction", "chapter_body", "chapter_outline",
    "chapter_storyline_recommendation", "outline_background",
    "outline_characters", "outline_plot", "outline_highlight",
    "character_profile_completion", "review", "continuity_check",
    "selection_edit",
)


def scenarios() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def future_capability(
    skill_id: str,
    kind: str,
    label: str,
    description: str,
    semantic_criteria: list[str],
    negative_examples: list[str],
    supersedes: list[str] | None = None,
) -> LoadedCapability:
    declaration = CapabilityDeclaration(
        skill_id=skill_id,
        capability_version="1.0.0",
        kind=kind,
        display_name=f"测试模块 {skill_id}",
        description=description,
        approval_ref="plan58-frozen-fixture",
        release_status="author_approved",
        genre_aliases=(label,) if kind == "genre" else (),
        mechanism_tags=(label,) if kind == "mechanism" else (),
        applicable_tasks=CREATIVE_TASKS,
        excluded_tasks=("mechanical", "excluded", "novel_naming", "novel_template"),
        semantic_criteria=tuple(semantic_criteria),
        negative_examples=tuple(negative_examples),
        supersedes=tuple(supersedes or ()),
    )
    text = f"---\nname: {skill_id}\n---\n\n# 测试方法\n"
    return LoadedCapability(
        declaration=declaration,
        routing_hash=canonical_hash(declaration),
        body=MethodBlock(
            skill_id=skill_id,
            path="SKILL.md",
            text=text,
            sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        ),
    )


def evaluation_catalog(value: dict[str, object]) -> CapabilityCatalog:
    formal = load_catalog(ROOT / "skills", packaged_approvals(), FORMAL_IDS)
    fixtures = tuple(
        future_capability(
            item["skill_id"], item["kind"], item["label"],
            item["description"], item["semantic_criteria"], item["negative_examples"],
            item.get("supersedes"),
        )
        for item in value["catalog_fixture"].values()
    )
    return CapabilityCatalog(capabilities=(*formal.capabilities, *fixtures))


def synthetic_projection(case: dict[str, object]) -> TaskModelInputProjectionV1:
    """Build a resolver fixture, not evidence of a production entry projection."""
    return TaskModelInputProjectionV1(
        scope=Scope(
            owner_id=OWNER,
            workspace_id=WORKSPACE,
            kind="novel",
            scope_id=SCOPE_ID,
            tab_id=f"plan58-{case['id']}",
        ),
        task=case["task"],
        intent=("review" if case["task"] in ("review", "continuity_check") else "write"),
        operation=("polish" if case["task"] == "selection_edit" else ""),
        source_version="plan58-scenario-v1",
        visibility_key=f"frozen-{case['id']}",
        sources=tuple(
            SourceItem(key=f"source.{index}", kind=item[0], text=item[1])
            for index, item in enumerate(case["sources"])
        ),
    )


def test_frozen_scenario_inventory_and_coverage_contract():
    value = scenarios()
    assert value["schema_version"] == "writing-routing-scenarios/1"
    d_cases = value["d_scenarios"]
    s_cases = value["s_scenarios"]
    assert len(d_cases) == len(s_cases) == 20
    assert [case["id"] for case in d_cases] == [f"D{i:02d}" for i in range(1, 21)]
    assert [case["id"] for case in s_cases] == [f"S{i:02d}" for i in range(1, 21)]
    s_ids = {case["id"] for case in s_cases}
    assert len(value["e_button_ids"]) == len(set(value["e_button_ids"])) == 8
    assert len(value["e_native_ids"]) == len(set(value["e_native_ids"])) == 8
    assert set(value["e_button_ids"]) <= s_ids
    assert set(value["e_native_ids"]) <= s_ids

    all_cases = (*d_cases, *s_cases)
    for skill_id in FORMAL_IDS:
        positives = sum(skill_id in case["expected"] for case in all_cases)
        exclusions = sum(skill_id not in case["expected"] for case in all_cases)
        assert positives >= 10
        assert exclusions >= 10
    future_ids = {
        item["skill_id"] for item in value["catalog_fixture"].values()
    }
    assert sum(bool(future_ids & set(case["expected"])) for case in s_cases) >= 2
    assert sum(len(case["expected"]) == 2 for case in s_cases) >= 2


def test_d_resolver_fixture_is_20_of_20_without_semantic_calls():
    value = scenarios()
    catalog = evaluation_catalog(value)
    observed: dict[str, list[str]] = {}
    for case in value["d_scenarios"]:
        preferences = MethodPreferences.model_validate(case.get("preferences", {}))
        plan = resolve_methods(
            synthetic_projection(case), catalog, preferences, "prose-writing",
        )
        observed[case["id"]] = [selection.skill_id for selection in plan.selected]
    expected = {case["id"]: case["expected"] for case in value["d_scenarios"]}
    assert observed == expected
