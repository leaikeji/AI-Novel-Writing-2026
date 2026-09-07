"""Plan 58 D-E checks through real button projection functions.

These cases intentionally differ from the resolver-only D-R fixture: prose that
describes a mechanism remains content, because no production button currently
owns an authoritative ``mechanism`` field.
"""

from __future__ import annotations

import json
from uuid import UUID

from backend.creative_services import build_creative_generation_prompt
from backend.writing_skills.contracts import MethodPreferences, Scope
from backend.writing_skills.projection import chapter_projection, creative_projection
from backend.writing_skills.resolver import resolve_methods
from tests.writing_skills.test_evaluation_contract import evaluation_catalog, scenarios


OWNER = UUID("29cf94d9-a5c9-54ec-912c-5dfff8738c4c")
WORKSPACE = UUID("f0e2e632-bc99-52d2-9916-bb906aa4da6e")
SCOPE_ID = UUID("11111111-1111-4111-8111-111111111111")
DOCUMENT_ID = UUID("22222222-2222-4222-8222-222222222222")
BUTTON_CASES = (
    "D01", "D02", "D03", "D04", "D05", "D08", "D09", "D10",
    "D11", "D12", "D13", "D16", "D17", "D18", "D19", "D20",
)
EXPECTED = {
    "D01": ["suspense-writing"],
    "D02": ["suspense-writing"],
    "D03": [],
    "D04": [],
    "D05": ["suspense-writing"],
    "D08": ["suspense-writing"],
    "D09": [],
    "D10": [],
    "D11": [],
    "D12": [],
    "D13": [],
    "D16": [],
    "D17": [],
    "D18": [],
    "D19": [],
    "D20": ["golden-finger-writing"],
}
NATIVE_OR_NON_GENERATION_CASES = {
    "D06": "continuity_check has no released product-generation projection",
    "D07": "direction belongs to the blocked native branch",
    "D14": "mechanical is intentionally excluded from generation routing",
    "D15": "excluded is intentionally excluded from generation routing",
}


def _scope(*, creation: bool = False, document: bool = False) -> Scope:
    return Scope(
        owner_id=OWNER,
        workspace_id=WORKSPACE,
        kind="creation_draft" if creation else "novel",
        scope_id=SCOPE_ID,
        document_id=DOCUMENT_ID if document else None,
        tab_id="plan58-d-entry",
    )


def _case_parts(case: dict[str, object]) -> tuple[dict[str, str], str]:
    classification: dict[str, str] = {}
    content: list[str] = []
    for kind, text in case["sources"]:
        if kind in {"genre", "subgenre"}:
            classification[kind] = text
        else:
            content.append(text)
    return classification, "\n".join(content)


def _button_projection(case: dict[str, object]):
    task = str(case["task"])
    classification, content = _case_parts(case)
    preferences = MethodPreferences.model_validate(case.get("preferences") or {})
    required = preferences.required_ids
    if task == "chapter_body":
        snapshot = {
            "novel": {"id": str(SCOPE_ID), **classification},
            "chapter": {
                "document_id": str(DOCUMENT_ID),
                "base_draft_version": 1,
                "base_revision_id": None,
                "base_content_hash": "a" * 64,
            },
            "brief": {"version": 1},
        }
        classification_text = {
            key: classification.get(key, "") for key in ("genre", "subgenre")
        }
        prompt = ""
        if any(classification_text.values()):
            prompt += "分类资料：" + json.dumps(
                classification_text, ensure_ascii=False, sort_keys=True,
            ) + "\n"
        prompt += content or "本次章节正文任务"
        return chapter_projection(
            _scope(document=True), snapshot, prompt, required_ids=required,
        )
    if task in {"novel_template", "novel_naming"}:
        snapshot = {**classification, "idea": content}
        prompt = build_creative_generation_prompt(
            {"kind": task, "input_snapshot": snapshot}
        )
        return creative_projection(
            _scope(creation=True), task, snapshot, prompt, required_ids=required,
        )
    if task.startswith("outline_"):
        snapshot = {
            "intent": "fresh",
            "model_context": {**classification, "idea": content},
        }
        return creative_projection(
            _scope(), task, snapshot, "strict outline projection",
            required_ids=required,
        )
    if task == "chapter_outline":
        snapshot = {
            "novel": {"title": "入口投影样本", **classification},
            "chapter_number": 2,
            "expectation_text": content,
            "rewrite_attempt": 1,
            "rewrite_requirement": "",
        }
    elif task == "review":
        snapshot = {
            "novel": {"title": "入口投影样本", **classification},
            "chapter_title": "测试章",
            "content_markdown": content or "待审正文",
        }
    elif task == "selection_edit":
        selected = content or "待修改文字"
        snapshot = {
            "novel": {"title": "入口投影样本", **classification},
            "schema_version": 1,
            "selection_id": "33333333-3333-4333-8333-333333333333",
            "operation": "polish",
            "custom_instruction": None,
            "use_novel_context": False,
            "target": {},
            "base": {"selection_text": selected, "before": "", "after": ""},
        }
    else:  # pragma: no cover - inventory assertion below owns this failure
        raise AssertionError(f"no released button projector for {task}")
    prompt = build_creative_generation_prompt(
        {"kind": task, "input_snapshot": snapshot}
    )
    return creative_projection(
        _scope(document=task in {"review", "selection_edit"}),
        task,
        snapshot,
        prompt,
        required_ids=required,
    )


def test_d_entry_inventory_is_frozen_before_scoring():
    value = scenarios()
    ids = {case["id"] for case in value["d_scenarios"]}
    assert set(BUTTON_CASES) | set(NATIVE_OR_NON_GENERATION_CASES) == ids
    assert set(BUTTON_CASES).isdisjoint(NATIVE_OR_NON_GENERATION_CASES)
    assert set(EXPECTED) == set(BUTTON_CASES)


def test_d_button_entries_use_real_projection_and_do_not_promote_plot_keywords():
    value = scenarios()
    catalog = evaluation_catalog(value)
    cases = {case["id"]: case for case in value["d_scenarios"]}
    observed: dict[str, list[str]] = {}
    plans = {}
    for case_id in BUTTON_CASES:
        case = cases[case_id]
        projection = _button_projection(case)
        assert all(source.kind != "mechanism" for source in projection.sources)
        preferences = MethodPreferences.model_validate(case.get("preferences") or {})
        plan = resolve_methods(projection, catalog, preferences, "prose-writing")
        plans[case_id] = plan
        observed[case_id] = [selection.skill_id for selection in plan.selected]

    assert observed == EXPECTED
    for case_id in ("D03", "D04", "D05", "D08", "D09", "D10", "D11"):
        assert plans[case_id].mechanism_state == "unresolved"
        assert "golden-finger-writing" not in observed[case_id]
    assert plans["D20"].mechanism_state == "resolved"
    assert plans["D20"].selected[0].basis == "explicit"
