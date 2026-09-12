"""Frozen Plan 58 D/S/E scenarios and resolver-only deterministic checks."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import sys
from uuid import UUID

import pytest

import scripts.run_plan58_real_semantic_eval as evaluation

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
from scripts.run_plan58_real_semantic_eval import _load_plan70_approval, main as eval_main


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).with_name("fixtures") / "routing_scenarios.json"
PLAN70_FIXTURE = Path(__file__).with_name("fixtures") / "plan70_chapter_scenarios.json"
PLAN70_ROUTE_FIXTURE = (
    Path(__file__).with_name("fixtures") / "plan70_chapter_route_requests.json"
)
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
    future_time_loop = value["catalog_fixture"]["future_mechanism"]
    assert "主动保存并读取" in future_time_loop["semantic_criteria"][0]
    assert "自动复位" in future_time_loop["semantic_criteria"][0]
    expected_by_id = {case["id"]: case["expected"] for case in s_cases}
    assert expected_by_id["S12"] == ["golden-finger-writing"]
    assert expected_by_id["S16"] == ["suspense-writing"]


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


def test_plan70_chapter_scenarios_are_frozen_balanced_task_material():
    value = json.loads(PLAN70_FIXTURE.read_text(encoding="utf-8"))
    assert value["schema_version"] == "plan70-chapter-routing-scenarios/2"
    assert value["rules"] == {
        "task": "chapter_body",
        "formal_skill_id": "golden-finger-writing",
        "source_contract": "actual chapter generation projection only",
        "forbid_manual_source_items": True,
        "maximum_auxiliary_calls_per_case": 1,
        "formal_skill_ids": ["golden-finger-writing", "suspense-writing"],
        "expected_contract": "per-skill decision plus independent skip",
    }
    cases = value["scenarios"]
    assert len(cases) == 20
    assert [case["id"] for case in cases] == [f"P70-C{i:02d}" for i in range(1, 21)]
    assert sum(case["expected"] == "select" for case in cases) == 10
    assert sum(case["expected"] != "select" for case in cases) == 10
    assert {case["expected"] for case in cases} == {"select", "reject", "skip", "unknown"}
    assert sum(case["expected_auxiliary_calls"] for case in cases) == 19
    for case in cases:
        assert all(isinstance(case[key], str) for key in (
            "title", "genre", "subgenre", "outline", "expectation", "forbidden", "reason",
        ))
        assert case["expected_auxiliary_calls"] in {0, 1}
        assert (case["expected_case_outcome"] == "skip") == (
            case["expected_auxiliary_calls"] == 0
        )
        if case["expected_case_outcome"] == "skip":
            assert "expected_by_skill" not in case
        else:
            assert set(case["expected_by_skill"]) == set(FORMAL_IDS)
            assert set(case["expected_by_skill"].values()) <= {
                "select", "reject", "unknown",
            }
    routed = [case for case in cases if case["expected_case_outcome"] == "route"]
    assert sum(
        case["expected_by_skill"]["golden-finger-writing"] == "select"
        for case in routed
    ) == 10
    assert sum(
        case["expected_by_skill"]["suspense-writing"] == "select"
        for case in routed
    ) == 4
    expected_truth = {
        case["id"]: case.get("expected_by_skill") for case in cases
    }
    assert expected_truth["P70-C05"] == {
        "golden-finger-writing": "select", "suspense-writing": "select",
    }
    assert expected_truth["P70-C10"] == {
        "golden-finger-writing": "reject", "suspense-writing": "reject",
    }
    assert expected_truth["P70-C12"] == {
        "golden-finger-writing": "reject", "suspense-writing": "select",
    }
    assert expected_truth["P70-C14"] == {
        "golden-finger-writing": "select", "suspense-writing": "reject",
    }
    assert expected_truth["P70-C18"] == {
        "golden-finger-writing": "unknown", "suspense-writing": "select",
    }
    assert expected_truth["P70-C19"] == {
        "golden-finger-writing": "select", "suspense-writing": "select",
    }
    boundary = cases[-1]
    assert boundary["padding_repeat"] >= 5000
    assert boundary["padding_unit"]
    assert boundary["tail_sentinel"] == "P70-TAIL-MUST-NOT-ROUTE"
    assert all("padding_repeat" not in case for case in cases[:-1])


def test_plan70_real_runner_requires_explicit_transport_before_any_network(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", [
        "run_plan58_real_semantic_eval.py", "--output", str(tmp_path / "report.json"),
    ])
    with pytest.raises(SystemExit) as stopped:
        eval_main()
    assert stopped.value.code == 2


def test_plan70_captured_projection_fixture_is_complete_and_bounded():
    value = json.loads(PLAN70_ROUTE_FIXTURE.read_text(encoding="utf-8"))
    assert value["schema_version"] == "plan70-chapter-route-requests/2"
    assert value["source_fixture"] == "plan70_chapter_scenarios.json"
    assert value["normalization"] == (
        "actual-chapter-context-block-projection-stable-identities/2"
    )
    assert value["projection_encoding"] == "zlib-base64-canonical-json/1"
    assert [item["id"] for item in value["cases"]] == [
        f"P70-C{i:02d}" for i in range(1, 21)
    ]
    projections = [evaluation.decode_plan70_projection(item) for item in value["cases"]]
    assert all(item.task == "chapter_body" for item in projections)
    assert all(all(source.kind != "mechanism" for source in item.sources)
               for item in projections)
    assert sum(item.truncated for item in projections) == 1
    assert projections[-1].truncated is True
    assert sum(len(source.text) for source in projections[-1].sources) == 80000
    assert "P70-TAIL-MUST-NOT-ROUTE" not in "".join(
        source.text for source in projections[-1].sources
    )


def _fake_public_result(text: str) -> dict[str, object]:
    return {
        "session_id": "fake",
        "event_count": 1,
        "statuses": ["completed"],
        "content_types": {"output_text": 1},
        "tool_markers": 0,
        "usage": {"provider_id": "fake-provider", "model_id": "fake-model"},
        "errors": [],
        "final_text": text,
        "model_rounds": 1,
        "transport_attempts": 1,
        "failure_stage": None,
        "failure_code": None,
        "failure_type": None,
        "duration_ms": 12,
    }


def _plan70_case_data(scenario_ids: list[str]):
    captured = json.loads(PLAN70_ROUTE_FIXTURE.read_text(encoding="utf-8"))
    cases = {item["id"]: item for item in captured["cases"]}
    catalog = evaluation._plan70_catalog()
    approvals = []
    for index, scenario_id in enumerate(scenario_ids, start=1):
        case = cases[scenario_id]
        if case["expected_case_outcome"] == "skip":
            continue
        projection = evaluation.decode_plan70_projection(case)
        plan = resolve_methods(
            projection, catalog, MethodPreferences(), "prose-writing",
        )
        request = evaluation.prepare_semantic_request(
            projection, catalog, plan, semantic_enabled=True,
        )
        approvals.append({
            "scenario_id": scenario_id,
            "attempt_id": str(UUID(int=index)),
            "request_hash": canonical_hash(request),
        })
    return cases, approvals


def _write_plan70_approval(tmp_path, scenario_ids: list[str]) -> tuple[dict, Path]:
    cases, approvals = _plan70_case_data(scenario_ids)
    path = tmp_path / "approval.json"
    path.write_text(json.dumps({
        "schema_version": "plan70-semantic-eval-approval/1",
        "run_id": "plan70-runner-contract",
        "provider_id": "fake-provider",
        "model_id": "fake-model",
        "cases": approvals,
    }), encoding="utf-8")
    return cases, path


def _plan70_argv(output: Path, approval: Path, ids: list[str] | None = None):
    value = [
        "run_plan58_real_semantic_eval.py",
        "--suite", "plan70-chapter",
        "--transport", "isolated-chapter-pawapp",
        "--route-url", "http://fake",
        "--approval", str(approval),
        "--output", str(output),
    ]
    if ids is not None:
        value.extend(("--ids", ",".join(ids)))
    return value


def _semantic_reply(request, decisions: dict[str, str]):
    return _fake_public_result(json.dumps({
        "schema_version": "semantic-route-response/1",
        "decisions": [{
            "skill_id": item.skill_id,
            "decision": decisions.get(item.skill_id, "reject"),
            "evidence_refs": [] if decisions.get(item.skill_id) == "unknown"
            else [request.sources[0].key],
        } for item in request.candidates],
    }, ensure_ascii=False))


def test_plan58_and_plan70_suites_are_independent_without_network(monkeypatch, tmp_path):
    monkeypatch.setattr(evaluation, "_active_model", lambda _url: (
        "fake-provider", "fake-model",
    ))
    plan58 = scenarios()
    plan58_cases = {item["id"]: item for item in plan58["s_scenarios"]}

    def fake_console(_base_url, prompt, scenario_id):
        request = json.loads(prompt.rsplit("路由数据：", 1)[1])
        expected = set(plan58_cases[scenario_id]["expected"])
        return _fake_public_result(json.dumps({
            "schema_version": "semantic-route-response/1",
            "decisions": [{
                "skill_id": item["skill_id"],
                "decision": "select" if item["skill_id"] in expected else "reject",
                "evidence_refs": [request["sources"][0]["key"]],
            } for item in request["candidates"]],
        }, ensure_ascii=False))

    monkeypatch.setattr(evaluation, "_public_chat", fake_console)
    first_output = tmp_path / "plan58.json"
    monkeypatch.setattr(sys, "argv", [
        "run_plan58_real_semantic_eval.py", "--suite", "plan58-s",
        "--transport", "legacy-console", "--output", str(first_output),
    ])
    assert evaluation.main() == evaluation.EXIT_COMPLETE
    first = json.loads(first_output.read_text(encoding="utf-8"))
    assert first["suite"] == "plan58-s"
    assert first["requested_ids"] == [f"S{i:02d}" for i in range(1, 21)]

    captured = json.loads(PLAN70_ROUTE_FIXTURE.read_text(encoding="utf-8"))
    cases = {item["id"]: item for item in captured["cases"]}
    catalog = evaluation._plan70_catalog()
    approvals = []
    for scenario_id, case in cases.items():
        if case["expected_case_outcome"] == "skip":
            continue
        projection = evaluation.decode_plan70_projection(case)
        plan = resolve_methods(projection, catalog, MethodPreferences(), "prose-writing")
        request = evaluation.prepare_semantic_request(
            projection, catalog, plan, semantic_enabled=True
        )
        approvals.append({
            "scenario_id": scenario_id,
            "attempt_id": str(UUID(int=len(approvals) + 1)),
            "request_hash": canonical_hash(request),
        })
    approval = {
        "schema_version": "plan70-semantic-eval-approval/1",
        "run_id": "plan70-no-network",
        "provider_id": "fake-provider",
        "model_id": "fake-model",
        "cases": approvals,
    }
    approval_path = tmp_path / "approval.json"
    approval_path.write_text(json.dumps(approval), encoding="utf-8")

    def fake_isolated(_url, request, *, approval, approved_case):
        expected = cases[approved_case["scenario_id"]]["expected_by_skill"]
        return _semantic_reply(request, expected)

    monkeypatch.setattr(evaluation, "_isolated_chapter_route", fake_isolated)
    second_output = tmp_path / "plan70.json"
    monkeypatch.setattr(sys, "argv", [
        "run_plan58_real_semantic_eval.py", "--suite", "plan70-chapter",
        "--transport", "isolated-chapter-pawapp", "--route-url", "http://fake",
        "--approval", str(approval_path), "--output", str(second_output),
    ])
    assert evaluation.main() == 0
    second = json.loads(second_output.read_text(encoding="utf-8"))
    assert second["suite"] == "plan70-chapter"
    assert second["http_requests"] == 19
    assert second["score"]["exact"] == 20
    assert next(item for item in second["results"]
                if item["scenario_id"] == "P70-C13")["status"] == "skipped"


def test_plan58_suite_uses_isolated_transport_without_network(monkeypatch, tmp_path):
    monkeypatch.setattr(evaluation, "_active_model", lambda _url: (
        "fake-provider", "fake-model",
    ))
    value = scenarios()
    cases = {item["id"]: item for item in value["s_scenarios"]}
    catalog = evaluation._catalog(value)
    approvals = []
    for index, scenario_id in enumerate(cases, start=1):
        projection = evaluation._projection(cases[scenario_id])
        plan = resolve_methods(
            projection, catalog, MethodPreferences(), "prose-writing",
        )
        request = evaluation.prepare_semantic_request(
            projection, catalog, plan, semantic_enabled=True,
        )
        approvals.append({
            "scenario_id": scenario_id,
            "attempt_id": str(UUID(int=index)),
            "request_hash": canonical_hash(request),
        })
    approval_path = tmp_path / "plan58-isolated-approval.json"
    approval_path.write_text(json.dumps({
        "schema_version": "plan70-semantic-eval-approval/1",
        "run_id": "plan58-isolated-no-network",
        "provider_id": "fake-provider",
        "model_id": "fake-model",
        "cases": approvals,
    }), encoding="utf-8")

    def fail_if_console_used(*_args, **_kwargs):
        raise AssertionError("legacy console transport must not be used")

    def fake_isolated(_url, request, *, approval, approved_case):
        expected = set(cases[approved_case["scenario_id"]]["expected"])
        return _fake_public_result(json.dumps({
            "schema_version": "semantic-route-response/1",
            "decisions": [{
                "skill_id": item.skill_id,
                "decision": "select" if item.skill_id in expected else "reject",
                "evidence_refs": [request.sources[0].key],
            } for item in request.candidates],
        }, ensure_ascii=False))

    monkeypatch.setattr(evaluation, "_public_chat", fail_if_console_used)
    monkeypatch.setattr(evaluation, "_isolated_chapter_route", fake_isolated)
    output = tmp_path / "plan58-isolated.json"
    monkeypatch.setattr(sys, "argv", [
        "run_plan58_real_semantic_eval.py", "--suite", "plan58-s",
        "--transport", "isolated-chapter-pawapp",
        "--route-url", "http://fake",
        "--approval", str(approval_path), "--output", str(output),
    ])
    assert evaluation.main() == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["suite"] == "plan58-s"
    assert report["transport"] == "isolated-chapter-pawapp"
    assert report["http_requests"] == 20
    assert report["score"]["exact"] == 20
    assert [item["state"] for item in report["attempts"]] == ["completed"] * 20


def test_plan70_approval_is_exact_bounded_and_duplicate_safe(tmp_path):
    approval = {
        "schema_version": "plan70-semantic-eval-approval/1",
        "run_id": "plan70-test",
        "provider_id": "fake-provider",
        "model_id": "fake-model",
        "cases": [{
            "scenario_id": "S01",
            "attempt_id": "11111111-1111-4111-8111-111111111111",
            "request_hash": "a" * 64,
        }],
    }
    path = tmp_path / "approval.json"
    path.write_text(json.dumps(approval), encoding="utf-8")
    assert _load_plan70_approval(path) == approval
    approval["cases"].append(dict(approval["cases"][0]))
    path.write_text(json.dumps(approval), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        _load_plan70_approval(path)


def test_plan70_fixture_route_uses_public_middleware_not_console_chat():
    source = (Path(__file__).with_name("fixtures") / "chapter_transport" / "plugin.py").read_text(encoding="utf-8")
    assert '@router.post("/semantic-route")' in source
    assert "PLAN70_SEMANTIC_EVAL_APPROVAL_JSON" in source
    assert "public_semantic_call(" in source
    assert "observation.model_dump(mode=\"json\")" in source
    assert "/api/console/chat" not in source


def test_isolated_route_preserves_only_bounded_semantic_diagnostics(monkeypatch):
    captured = json.loads(PLAN70_ROUTE_FIXTURE.read_text(encoding="utf-8"))
    case = captured["cases"][0]
    projection = evaluation.decode_plan70_projection(case)
    catalog = evaluation._plan70_catalog()
    plan = resolve_methods(
        projection, catalog, MethodPreferences(), "prose-writing",
    )
    semantic_request = evaluation.prepare_semantic_request(
        projection, catalog, plan, semantic_enabled=True,
    )
    approved_case = {
        "scenario_id": case["id"],
        "attempt_id": "11111111-1111-4111-8111-111111111111",
        "request_hash": canonical_hash(semantic_request),
    }
    approval = {
        "schema_version": "plan70-semantic-eval-approval/1",
        "run_id": "p70-diagnostic-test",
        "provider_id": "fake-provider",
        "model_id": "fake-model",
        "cases": [approved_case],
    }
    response = {
        "schema_version": "plan70-semantic-route-transport/1",
        "run_id": approval["run_id"],
        "scenario_id": approved_case["scenario_id"],
        "attempt_id": approved_case["attempt_id"],
        "provider_id": approval["provider_id"],
        "model_id": approval["model_id"],
        "observation": {
            "schema_version": "semantic-adapter-observation/1",
            "status": "unknown",
            "text": None,
            "model_rounds": 1,
            "tool_calls": 0,
            "transport_attempts": 1,
            "recursion_detected": False,
            "failure_stage": "reply_verification",
            "failure_code": "reply_evidence_public_usage_malformed",
            "failure_type": "NovelModelEvidenceRejected",
            "duration_ms": 842,
        },
    }

    def fake_urlopen(_request, timeout):
        assert timeout == 120
        return io.BytesIO(json.dumps(response).encode("utf-8"))

    monkeypatch.setattr(evaluation, "urlopen", fake_urlopen)
    result = evaluation._isolated_chapter_route(
        "http://isolated.invalid/semantic-route",
        semantic_request,
        approval=approval,
        approved_case=approved_case,
    )
    assert result["failure_stage"] == "reply_verification"
    assert result["failure_code"] == "reply_evidence_public_usage_malformed"
    assert result["failure_type"] == "NovelModelEvidenceRejected"
    assert result["duration_ms"] == 842
    assert "must not be persisted" not in json.dumps(result)

    response["observation"]["raw_error"] = "secret and model text"
    with pytest.raises(ValueError, match="invalid_plan70_route_observation"):
        evaluation._isolated_chapter_route(
            "http://isolated.invalid/semantic-route",
            semantic_request,
            approval=approval,
            approved_case=approved_case,
        )


def test_plan70_runner_persists_unknown_diagnostic_without_retry(
    monkeypatch, tmp_path,
):
    monkeypatch.setattr(evaluation, "_active_model", lambda _url: (
        "fake-provider", "fake-model",
    ))
    captured = json.loads(PLAN70_ROUTE_FIXTURE.read_text(encoding="utf-8"))
    case = captured["cases"][0]
    projection = evaluation.decode_plan70_projection(case)
    catalog = evaluation._plan70_catalog()
    plan = resolve_methods(
        projection, catalog, MethodPreferences(), "prose-writing",
    )
    semantic_request = evaluation.prepare_semantic_request(
        projection, catalog, plan, semantic_enabled=True,
    )
    approved_case = {
        "scenario_id": case["id"],
        "attempt_id": "11111111-1111-4111-8111-111111111111",
        "request_hash": canonical_hash(semantic_request),
    }
    approval_path = tmp_path / "diagnostic-approval.json"
    approval_path.write_text(json.dumps({
        "schema_version": "plan70-semantic-eval-approval/1",
        "run_id": "p70-diagnostic-persist",
        "provider_id": "fake-provider",
        "model_id": "fake-model",
        "cases": [approved_case],
    }), encoding="utf-8")

    calls = 0

    def fake_isolated(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        result = _fake_public_result("")
        result.update({
            "statuses": ["unknown"],
            "content_types": {},
            "errors": ["semantic_transport_unknown"],
            "failure_stage": "chat",
            "failure_code": "chat_error_after_observation",
            "failure_type": "RuntimeError",
            "duration_ms": 731,
        })
        return result

    monkeypatch.setattr(evaluation, "_isolated_chapter_route", fake_isolated)
    output = tmp_path / "diagnostic-result.json"
    monkeypatch.setattr(sys, "argv", [
        "run_plan58_real_semantic_eval.py",
        "--suite", "plan70-chapter",
        "--ids", case["id"],
        "--transport", "isolated-chapter-pawapp",
        "--route-url", "http://fake",
        "--approval", str(approval_path),
        "--output", str(output),
    ])
    assert evaluation.main() == evaluation.EXIT_STOPPED
    report = json.loads(output.read_text(encoding="utf-8"))
    assert calls == report["http_requests"] == 1
    assert report["automatic_retries"] == 0
    assert report["run_status"] == "stopped"
    assert report["stop_reason"] == "transport_unknown"
    assert report["stopped_at_case"] == case["id"]
    assert report["unexecuted_count"] == 0
    assert report["attempts"] == [{
        "scenario_id": approved_case["scenario_id"],
        "attempt_id": approved_case["attempt_id"],
        "state": "completed",
    }]
    transport = report["results"][0]["transport"]
    assert transport["failure_stage"] == "chat"
    assert transport["failure_code"] == "chat_error_after_observation"
    assert transport["failure_type"] == "RuntimeError"
    assert transport["duration_ms"] == 731
    assert transport["model_rounds"] == 1
    assert transport["transport_attempts"] == 1
    assert transport["response_shape"] == "empty"
    assert transport["errors"] == ["transport_reported_error"]


def test_plan70_runner_stops_after_first_transport_failure_and_redacts_error(
    monkeypatch, tmp_path,
):
    ids = ["P70-C01", "P70-C02"]
    _cases, approval = _write_plan70_approval(tmp_path, ids)
    monkeypatch.setattr(evaluation, "_active_model", lambda _url: (
        "fake-provider", "fake-model",
    ))
    calls = 0

    def fail_once(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("private input must never enter evidence")

    monkeypatch.setattr(evaluation, "_isolated_chapter_route", fail_once)
    output = tmp_path / "stopped.json"
    monkeypatch.setattr(sys, "argv", _plan70_argv(output, approval, ids))
    assert evaluation.main() == evaluation.EXIT_STOPPED
    report_text = output.read_text(encoding="utf-8")
    report = json.loads(report_text)
    assert calls == report["http_requests"] == 1
    assert report["run_status"] == "stopped"
    assert report["stop_reason"] == "transport_failed"
    assert report["stopped_at_case"] == ids[0]
    assert report["unexecuted_count"] == 1
    assert [item["state"] for item in report["attempts"]] == ["started", "planned"]
    failed = report["results"][0]
    assert failed["expected_outcome"] == "route"
    assert failed["expected_by_skill"] == {
        "golden-finger-writing": "select", "suspense-writing": "reject",
    }
    assert failed["observed_by_skill"] == {}
    assert "private input" not in report_text


def test_plan70_runner_stops_when_explicit_skill_exclusion_is_violated(
    monkeypatch, tmp_path,
):
    ids = ["P70-C09", "P70-C10"]
    _cases, approval = _write_plan70_approval(tmp_path, ids)
    monkeypatch.setattr(evaluation, "_active_model", lambda _url: (
        "fake-provider", "fake-model",
    ))
    calls = 0

    def select_forbidden(_url, request, **_kwargs):
        nonlocal calls
        calls += 1
        return _semantic_reply(request, {"golden-finger-writing": "select"})

    monkeypatch.setattr(evaluation, "_isolated_chapter_route", select_forbidden)
    output = tmp_path / "explicit-exclusion.json"
    monkeypatch.setattr(sys, "argv", _plan70_argv(output, approval, ids))
    assert evaluation.main() == evaluation.EXIT_STOPPED
    report = json.loads(output.read_text(encoding="utf-8"))
    assert calls == report["http_requests"] == 1
    assert report["run_status"] == "stopped"
    assert report["stop_reason"] == "explicit_exclusion_violated"
    assert report["stopped_at_case"] == "P70-C09"
    assert report["unexecuted_count"] == 1
    assert report["results"][0]["observed"] == ["golden-finger-writing"]
    assert report["results"][0]["exact"] is False
    assert [item["state"] for item in report["attempts"]] == [
        "completed", "planned",
    ]


def test_plan70_runner_allows_expected_abstention_then_continues(
    monkeypatch, tmp_path,
):
    ids = ["P70-C18", "P70-C01"]
    _cases, approval = _write_plan70_approval(tmp_path, ids)
    monkeypatch.setattr(evaluation, "_active_model", lambda _url: (
        "fake-provider", "fake-model",
    ))
    calls = 0

    def route(_url, request, *, approved_case, **_kwargs):
        nonlocal calls
        calls += 1
        decisions = (
            {
                "golden-finger-writing": "unknown",
                "suspense-writing": "select",
            }
            if approved_case["scenario_id"] == ids[0]
            else {"golden-finger-writing": "select"}
        )
        return _semantic_reply(request, decisions)

    monkeypatch.setattr(evaluation, "_isolated_chapter_route", route)
    output = tmp_path / "expected-abstention.json"
    monkeypatch.setattr(sys, "argv", _plan70_argv(output, approval, ids))
    assert evaluation.main() == evaluation.EXIT_SCORE_FAILED
    report = json.loads(output.read_text(encoding="utf-8"))
    assert calls == report["http_requests"] == 2
    assert report["run_status"] == "complete"
    assert report["stop_reason"] == "score_below_threshold"
    assert report["stopped_at_case"] is None
    assert report["unexecuted_count"] == 0
    assert [item["route_status"] for item in report["results"]] == [
        "unknown", "applied",
    ]


def test_plan70_runner_counts_classification_errors_without_technical_stop(
    monkeypatch, tmp_path,
):
    ids = ["P70-C01", "P70-C02"]
    _cases, approval = _write_plan70_approval(tmp_path, ids)
    monkeypatch.setattr(evaluation, "_active_model", lambda _url: (
        "fake-provider", "fake-model",
    ))
    calls = 0

    def route(_url, request, **_kwargs):
        nonlocal calls
        calls += 1
        return _semantic_reply(request, {})

    monkeypatch.setattr(evaluation, "_isolated_chapter_route", route)
    output = tmp_path / "classification-errors.json"
    monkeypatch.setattr(sys, "argv", _plan70_argv(output, approval, ids))
    assert evaluation.main() == evaluation.EXIT_SCORE_FAILED
    report = json.loads(output.read_text(encoding="utf-8"))
    assert calls == 2
    assert report["run_status"] == "complete"
    assert report["stop_reason"] == "score_below_threshold"
    assert report["score"]["exact"] == 0
    assert [item["status"] for item in report["results"]] == ["ok", "ok"]


def test_plan70_complete_suite_below_threshold_returns_score_failure(
    monkeypatch, tmp_path,
):
    ids = [f"P70-C{index:02d}" for index in range(1, 21)]
    _cases, approval = _write_plan70_approval(tmp_path, ids)
    monkeypatch.setattr(evaluation, "_active_model", lambda _url: (
        "fake-provider", "fake-model",
    ))
    calls = 0

    def route(_url, request, **_kwargs):
        nonlocal calls
        calls += 1
        return _semantic_reply(request, {})

    monkeypatch.setattr(evaluation, "_isolated_chapter_route", route)
    output = tmp_path / "full-score-failure.json"
    monkeypatch.setattr(sys, "argv", _plan70_argv(output, approval))
    assert evaluation.main() == evaluation.EXIT_SCORE_FAILED
    report = json.loads(output.read_text(encoding="utf-8"))
    assert calls == report["http_requests"] == 19
    assert report["run_status"] == "complete"
    assert report["stop_reason"] == "score_below_threshold"
    assert report["unexecuted_count"] == 0
    assert len(report["results"]) == 20


def test_plan70_runner_preflight_model_mismatch_dispatches_nothing(
    monkeypatch, tmp_path,
):
    ids = ["P70-C01"]
    _cases, approval = _write_plan70_approval(tmp_path, ids)
    monkeypatch.setattr(evaluation, "_active_model", lambda _url: (
        "another-provider", "another-model",
    ))
    monkeypatch.setattr(
        evaluation, "_isolated_chapter_route",
        lambda *_args, **_kwargs: pytest.fail("transport must not be called"),
    )
    output = tmp_path / "model-mismatch.json"
    monkeypatch.setattr(sys, "argv", _plan70_argv(output, approval, ids))
    assert evaluation.main() == evaluation.EXIT_PREFLIGHT_FAILED
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["run_status"] == "preflight_failed"
    assert report["stop_reason"] == "effective_model_mismatch"
    assert report["http_requests"] == 0
    assert report["unexecuted_count"] == 1
    assert report["attempts"][0]["state"] == "planned"


def test_plan70_runner_preserves_reply_when_postflight_probe_fails(
    monkeypatch, tmp_path,
):
    ids = ["P70-C01"]
    _cases, approval = _write_plan70_approval(tmp_path, ids)
    probes = 0

    def active(_url):
        nonlocal probes
        probes += 1
        if probes == 3:
            raise OSError("private postflight details")
        return "fake-provider", "fake-model"

    def route(_url, request, **_kwargs):
        return _semantic_reply(request, {"golden-finger-writing": "select"})

    monkeypatch.setattr(evaluation, "_active_model", active)
    monkeypatch.setattr(evaluation, "_isolated_chapter_route", route)
    output = tmp_path / "postflight-failed.json"
    monkeypatch.setattr(sys, "argv", _plan70_argv(output, approval, ids))
    assert evaluation.main() == evaluation.EXIT_STOPPED
    report_text = output.read_text(encoding="utf-8")
    report = json.loads(report_text)
    assert report["stop_reason"] == "model_probe_failed"
    assert report["http_requests"] == 1
    assert report["attempts"][0]["state"] == "completed"
    assert report["results"][0]["transport"]["response_shape"] == "bare_object_candidate"
    assert report["results"][0]["response_sha256"]
    assert report["results"][0]["model_after"] is None
    assert "private postflight" not in report_text


def test_plan70_runner_refuses_to_overwrite_existing_output(monkeypatch, tmp_path):
    output = tmp_path / "existing.json"
    output.write_text("author evidence", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "run_plan58_real_semantic_eval.py",
        "--suite", "plan70-chapter",
        "--transport", "isolated-chapter-pawapp",
        "--output", str(output),
    ])
    assert evaluation.main() == evaluation.EXIT_PREFLIGHT_FAILED
    assert output.read_text(encoding="utf-8") == "author evidence"
