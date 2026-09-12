from __future__ import annotations

import json
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.run_plan70_real_writing_ab as runner
from .test_persistence import engine  # explicit isolated DB guard, never application default


FIXTURE = Path(__file__).with_name("fixtures") / "plan70_writing_ab_cases.json"
MODEL = ("fake-provider", "fake-model")


def write_review(tmp_path, output, approval, **changes):
    receipt = {
        "schema_version": "plan70-writing-review-receipt/1",
        "run_id": approval["run_id"],
        "checkpoint_sha256": runner._sha256(output.read_bytes()),
        "reviewer": "independent-fake-reviewer", "signed_at": "2026-09-12T12:00:00+08:00",
        "decision": "continue", "major_errors": 0, "clear_b_losses": 0,
        **changes,
    }
    path = tmp_path / "review.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    return path


def transport_helpers():
    # Load the actual test adapter helpers without importing a QwenPaw host.
    source = (FIXTURE.parent / "chapter_transport/plugin.py").read_text()
    tree = ast.parse(source)
    names = {"_plan70_outline_fields", "_plan70_input_evidence", "_Plan70ProseContext"}
    nodes = [node for node in tree.body if getattr(node, "name", "") in names]
    namespace = {"canonical_hash": runner.canonical_hash, "hashlib": runner.hashlib}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "test-transport-helpers", "exec"), namespace)
    return namespace


def fixture_value():
    return runner._load_fixture(runner.DEFAULT_FIXTURE)


def approval_value(fixture):
    return runner.build_approval(
        fixture,
        run_id="plan70-writing-test-v1",
        provider_id=MODEL[0],
        model_id=MODEL[1],
    )


def response_for(payload, *, visible=2200):
    arm = payload["request"]["arm"]
    selected = ["golden-finger-writing"] if arm == "B" else []
    content = "城" * visible
    sources = {key: payload["request"]["seed"][key] for key in (
        "description", "background", "main_plot", "idea",
        "expectation_text", "outline_text", "forbidden_text",
    )}
    return {
        "schema_version": "plan70-writing-ab-transport/2",
        "run_id": payload["run_id"],
        "cell_id": payload["cell_id"],
        "attempt_id": payload["attempt_id"],
        "pair_id": payload["request"]["pair_id"],
        "arm": arm,
        "provider_id": MODEL[0],
        "model_id": MODEL[1],
        "novel_id": "11111111-1111-4111-8111-111111111111",
        "document_id": "22222222-2222-4222-8222-222222222222",
        "brief_version": 1,
        "prose_model_call_limit": 1,
        "automatic_retries": 0,
        "input_evidence": {
            "schema_version": "plan70-writing-input/1",
            "observation_boundary": "project_frozen_input_before_ctx_chat",
            "provider_receipt_proven": False,
            "sources": sources, "source_hash": runner.canonical_hash(sources),
            "brief_version": 1,
        },
        "generation": {
            "requested_visible_character_count": 2500,
            "minimum_visible_character_count": 2125,
            "maximum_visible_character_count": 2875,
            "id": "33333333-3333-4333-8333-333333333333",
            "state": "ready",
            "requested_provider_id": MODEL[0],
            "requested_model_id": MODEL[1],
            "actual_provider_id": MODEL[0],
            "actual_model_id": MODEL[1],
            "model_evidence": {
                "schema_version": "model-execution-evidence/2",
                "status": "verified_from_provider_usage",
            },
            "validation_state": "meets_target",
            "candidate": {
                "id": "44444444-4444-4444-8444-444444444444",
                "state": "ready",
                "adopted_revision_id": None,
                "visible_character_count": visible,
                "content_markdown": content,
            },
            "writing_method": {
                "selected_ids": selected,
                "auxiliary_calls": 1 if arm == "B" else 0,
                "semantic_enabled": arm == "B",
                "details": {"methods": [
                    {**runner._approved_methods()[0]},
                    *([{**runner._approved_methods()[1]}]
                      if arm == "B" else []),
                ]},
            },
        },
    }


def test_fixture_freezes_four_equal_baseline_pairs_and_interleaved_gate():
    fixture = fixture_value()
    assert fixture["execution_order"] == [
        "T03-A", "T03-B", "T04-B", "T04-A",
        "T01-A", "T01-B", "T02-B", "T02-A",
    ]
    assert fixture["first_gate_cells"] == fixture["execution_order"][:4]
    assert fixture["target_visible_character_count"] == 2500
    assert fixture["minimum_visible_character_count"] == 2000
    for pair in fixture["pairs"]:
        a = runner._cell_request(fixture, f"{pair['pair_id']}-A",
                                 "11111111-1111-4111-8111-111111111111")
        b = runner._cell_request(fixture, f"{pair['pair_id']}-B",
                                 "22222222-2222-4222-8222-222222222222")
        assert a["seed"] == b["seed"]
        assert a["generation"]["expected_brief_version"] == 1
        assert a["generation"]["writing_action"]["preferences"]["mode"] == "generic_only"
        assert a["generation"]["writing_action"]["preferences"]["semantic_mode"] == "off"
        assert b["generation"]["writing_action"]["preferences"]["mode"] == "auto"
        assert b["generation"]["writing_action"]["preferences"]["semantic_mode"] == "auto"


def test_approval_is_exact_eight_unique_cells_and_hash_bound(tmp_path):
    fixture = fixture_value()
    approval = approval_value(fixture)
    path = tmp_path / "approval.json"
    path.write_text(json.dumps(approval), encoding="utf-8")
    assert runner._load_approval(path, fixture) == approval
    assert len({item["attempt_id"] for item in approval["cells"]}) == 8
    assert len({item["action_id"] for item in approval["cells"]}) == 8
    assert approval["effective_max_input_length"] == 131_072
    assert approval["schema_version"] == "plan70-writing-ab-approval/3"
    assert approval["comparison_contract"]["sampling_policy"] == {
        "request_level_overrides": {},
        "provider_defaults_apply": True,
        "variance_control": "balanced_interleaved_execution_order",
    }
    approval["cells"][0]["request_hash"] = "0" * 64
    path.write_text(json.dumps(approval), encoding="utf-8")
    with pytest.raises(ValueError, match="request hash mismatch"):
        runner._load_approval(path, fixture)


def test_comparison_contract_proves_only_approved_method_differences(tmp_path):
    fixture = fixture_value()
    approval = approval_value(fixture)
    expected = approval["comparison_contract"]
    assert expected["allowed_request_differences"] == [
        "arm",
        "generation.writing_action.action_id",
        "generation.writing_action.tab_id",
        "generation.writing_action.preferences.mode",
        "generation.writing_action.preferences.semantic_mode",
    ]
    assert [item["pair_id"] for item in expected["pair_baselines"]] == [
        "T01", "T02", "T03", "T04",
    ]
    for pair in fixture["pairs"]:
        pair_id = pair["pair_id"]
        a = runner._cell_request(fixture, f"{pair_id}-A", str(runner.uuid4()))
        b = runner._cell_request(fixture, f"{pair_id}-B", str(runner.uuid4()))
        assert runner.canonical_hash(runner._normalized_shared_input(a)) == (
            runner.canonical_hash(runner._normalized_shared_input(b))
        )

    path = tmp_path / "approval.json"
    approval["comparison_contract"]["pair_baselines"][0][
        "shared_input_hash"
    ] = "0" * 64
    path.write_text(json.dumps(approval), encoding="utf-8")
    with pytest.raises(ValueError, match="comparison contract changed"):
        runner._load_approval(path, fixture)


def test_runner_precommits_pauses_then_runs_only_reviewed_remaining_four(tmp_path):
    fixture = fixture_value()
    approval = approval_value(fixture)
    output = tmp_path / "result.json"
    calls = []

    def request_cell(_url, payload):
        checkpoint = json.loads(output.read_text(encoding="utf-8"))
        current = next(item for item in checkpoint["attempts"]
                       if item["cell_id"] == payload["cell_id"])
        assert current["state"] == "started"
        assert current["request_hash"] == runner.canonical_hash(payload["request"])
        calls.append(payload["cell_id"])
        return response_for(payload)

    status = runner.run(
        fixture=fixture,
        approval=approval,
        route_url="http://fixture.test/api/s58-chapter-transport/writing-ab",
        output=output,
        active_model=lambda _base: MODEL,
        request_cell=request_cell,
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    assert status == runner.EXIT_AWAITING_REVIEW
    assert calls == fixture["execution_order"][:4]
    assert report["state"] == "awaiting_review"
    assert report["prose_calls"] == 4 and report["auxiliary_calls"] == 2
    assert all(item["state"] == "planned" for item in report["attempts"][4:])
    receipt = write_review(tmp_path, output, approval)
    status = runner.run(
        fixture=fixture, approval=approval,
        route_url="http://fixture.test/api/s58-chapter-transport/writing-ab",
        output=output, active_model=lambda _base: MODEL,
        request_cell=request_cell, review_path=receipt,
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    assert status == runner.EXIT_COMPLETE
    assert calls == fixture["execution_order"]
    assert report["state"] == "complete"
    assert report["http_requests"] == report["prose_calls"] == 8
    assert report["auxiliary_calls"] == 4
    assert report["automatic_retries"] == 0
    assert report["assistant_console_used"] is False
    assert all(item["state"] == "completed" for item in report["attempts"])
    assert all(item["result"]["adopted_revision_id"] is None for item in report["attempts"])
    assert all(item["result"]["target_status"] == "TARGET_MISSED" for item in report["attempts"])


def test_runner_stops_on_first_failed_cell_without_spending_remaining_budget(tmp_path):
    fixture = fixture_value()
    approval = approval_value(fixture)
    output = tmp_path / "stopped.json"
    calls = []

    def request_cell(_url, payload):
        calls.append(payload["cell_id"])
        if payload["cell_id"] == "T04-B":
            raise RuntimeError("synthetic_failure")
        return response_for(payload)

    status = runner.run(
        fixture=fixture,
        approval=approval,
        route_url="http://fixture.test/api/s58-chapter-transport/writing-ab",
        output=output,
        active_model=lambda _base: MODEL,
        request_cell=request_cell,
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    assert status == runner.EXIT_STOPPED
    assert calls == ["T03-A", "T03-B", "T04-B"]
    assert report["http_requests"] == report["prose_calls"] == 3
    assert report["auxiliary_calls"] == 2
    assert [item["state"] for item in report["attempts"]] == [
        "completed", "completed", "failed", "planned", "planned", "planned",
        "planned", "planned",
    ]


def test_existing_checkpoint_refuses_restart_before_any_probe_or_request(tmp_path):
    fixture = fixture_value()
    approval = approval_value(fixture)
    output = tmp_path / "existing.json"
    output.write_text('{"state":"running"}', encoding="utf-8")
    touched = []
    with pytest.raises(ValueError, match="must never replay"):
        runner.run(
            fixture=fixture,
            approval=approval,
            route_url="http://fixture.test/api/s58-chapter-transport/writing-ab",
            output=output,
            active_model=lambda _base: touched.append("probe") or MODEL,
            request_cell=lambda _url, _payload: touched.append("request") or {},
        )
    assert touched == []


def test_model_drift_and_short_output_are_terminal(tmp_path):
    fixture = fixture_value()
    approval = approval_value(fixture)
    output = tmp_path / "drift.json"
    probes = iter((MODEL, MODEL, ("other", "model")))
    status = runner.run(
        fixture=fixture,
        approval=approval,
        route_url="http://fixture.test/api/s58-chapter-transport/writing-ab",
        output=output,
        active_model=lambda _base: next(probes),
        request_cell=lambda _url, payload: response_for(payload),
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    assert status == runner.EXIT_STOPPED
    assert report["http_requests"] == 1
    assert report["attempts"][0]["state"] == "failed"

    approval = approval_value(fixture)
    output = tmp_path / "short.json"
    status = runner.run(
        fixture=fixture,
        approval=approval,
        route_url="http://fixture.test/api/s58-chapter-transport/writing-ab",
        output=output,
        active_model=lambda _base: MODEL,
        request_cell=lambda _url, payload: response_for(payload, visible=1999),
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    assert status == runner.EXIT_STOPPED
    assert report["http_requests"] == 1
    assert report["attempts"][0]["state"] == "failed"


def test_public_usage_not_exposed_accepts_exact_pre_and_post_model_evidence():
    fixture = fixture_value()
    approval = approval_value(fixture)
    cell = approval["cells"][0]
    payload = {
        "run_id": approval["run_id"],
        "cell_id": cell["cell_id"],
        "attempt_id": cell["attempt_id"],
        "request": runner._cell_request(fixture, cell["cell_id"], cell["action_id"]),
    }
    response = response_for(payload)
    generation = response["generation"]
    generation["actual_provider_id"] = None
    generation["actual_model_id"] = None
    generation["model_evidence"] = {
        "schema_version": "model-execution-evidence/2",
        "status": "not_exposed",
        "reported_actual": None,
        "preflight_effective": {"provider_id": MODEL[0], "model_id": MODEL[1]},
        "postflight_effective": {"provider_id": MODEL[0], "model_id": MODEL[1]},
    }
    result = runner._validate_response(
        response, approval=approval, approved_cell=cell
    )
    assert result["actual_provider_id"] is None


def test_fixture_endpoint_is_test_only_strict_and_uses_managed_chapter_service():
    source = (
        Path(__file__).with_name("fixtures") / "chapter_transport" / "plugin.py"
    ).read_text(encoding="utf-8")
    assert '@router.post("/writing-ab")' in source
    assert "PLAN70_WRITING_AB_APPROVAL_JSON" in source
    assert "PLAN70_WRITING_AB_APPROVAL_FILE" in source
    assert 'source="effective-model-api+plan70-approved-context"' in source
    assert "generate_managed_chapter(" in source
    assert "create_novel(" in source and "save_chapter_brief(" in source
    assert 'semantic_factory if payload.request.arm == "B" else None' in source
    assert 'candidate.get("adopted_revision_id") is not None' in source
    assert "/api/console/chat" not in source


def test_v2_baseline_is_verbatim_and_first_gate_is_resource_and_mixed_pairs():
    fixture = runner._load_fixture(runner.DEFAULT_FIXTURE)
    assert fixture["schema_version"] == "plan70-writing-ab-cases/2"
    assert fixture["execution_order"] == ["T03-A", "T03-B", "T04-B", "T04-A", "T01-A", "T01-B", "T02-B", "T02-A"]
    baseline = runner.review_baselines(fixture)
    assert baseline["fixture_sha256"] == fixture["fixture_sha256"]
    assert [pair["sources"] for pair in baseline["pairs"]] == [pair["seed"] for pair in fixture["pairs"]]
    assert "仍装在货梯控制箱内" in fixture["pairs"][2]["seed"]["background"]
    assert "并用包隔音" not in json.dumps(fixture, ensure_ascii=False)


@pytest.mark.parametrize("changes", [
    {"checkpoint_sha256": "0" * 64}, {"decision": "stop"},
    {"major_errors": 1}, {"clear_b_losses": 1}, {"reviewer": ""},
])
def test_wrong_or_failed_review_never_probes_or_dispatches(tmp_path, changes):
    fixture = runner._load_fixture(runner.DEFAULT_FIXTURE)
    approval = approval_value(fixture)
    output = tmp_path / "result.json"
    route = "http://fixture.test/writing-ab"
    assert runner.run(fixture=fixture, approval=approval, route_url=route, output=output,
                      active_model=lambda _: MODEL, request_cell=lambda _, p: response_for(p)) == runner.EXIT_AWAITING_REVIEW
    receipt = write_review(tmp_path, output, approval, **changes)
    with pytest.raises(ValueError, match="review"):
        runner.run(fixture=fixture, approval=approval, route_url=route, output=output,
                   review_path=receipt, active_model=lambda _: pytest.fail("must not probe"),
                   request_cell=lambda *_: pytest.fail("must not dispatch"))


def test_resume_rejects_started_remaining_cell_even_with_matching_receipt(tmp_path):
    fixture = fixture_value()
    approval = approval_value(fixture)
    output = tmp_path / "result.json"
    route = "http://fixture.test/writing-ab"
    runner.run(fixture=fixture, approval=approval, route_url=route, output=output,
               active_model=lambda _: MODEL, request_cell=lambda _, p: response_for(p))
    report = json.loads(output.read_bytes())
    report["attempts"][4]["started_at_unix_ms"] = 1
    output.write_text(json.dumps(report))
    receipt = write_review(tmp_path, output, approval)
    with pytest.raises(ValueError, match="never replay"):
        runner.run(fixture=fixture, approval=approval, route_url=route, output=output,
                   review_path=receipt, active_model=lambda _: pytest.fail("must not probe"))


@pytest.mark.parametrize("visible", [2000, 2124, 2876])
def test_software_length_window_stops_even_above_user_minimum(tmp_path, visible):
    fixture = fixture_value()
    output = tmp_path / "result.json"
    assert runner.run(fixture=fixture, approval=approval_value(fixture),
                      route_url="http://fixture.test/writing-ab", output=output,
                      active_model=lambda _: MODEL,
                      request_cell=lambda _, p: response_for(p, visible=visible)) == runner.EXIT_STOPPED
    assert json.loads(output.read_bytes())["prose_calls"] == 1


def test_sources_missing_from_formal_blocks_or_prompt_fail_before_dispatch():
    helpers = transport_helpers()
    check = helpers["_plan70_input_evidence"]
    for pair in runner._load_fixture(runner.DEFAULT_FIXTURE)["pairs"]:
        seed = SimpleNamespace(**pair["seed"])
        outline = helpers["_plan70_outline_fields"](seed)
        brief = {"section": "chapter_requirements", "content": "\n".join(
            getattr(seed, field) for field in ("expectation_text", "outline_text", "forbidden_text"))}
        snapshot = {"brief": {"version": 1}, "writing_context": {"envelope": {"included_blocks": [brief]}}}
        with pytest.raises(ValueError, match="missing: description"):
            check(seed, snapshot, brief["content"])
        snapshot["writing_context"]["envelope"]["included_blocks"].append(
            {"section": "formal_planning", "content": "\n".join(outline.values())})
        prompt = brief["content"] + "\n" + "\n".join(outline.values())
        evidence = check(seed, snapshot, prompt)
        assert evidence["sources"]["idea"] == seed.idea
        assert evidence["provider_receipt_proven"] is False
        with pytest.raises(ValueError, match="missing: idea"):
            check(seed, snapshot, prompt.replace(seed.idea, ""))


def test_legacy_fixture_and_approval_still_readable_but_not_executable(tmp_path):
    fixture = runner._load_fixture(FIXTURE)
    assert fixture["fixture_sha256"] == "ca6cf59072fe6efa4f4d5bd98e0e1f278de2b233b342cad1beba67335155da1c"
    approval = approval_value(fixture)
    path = tmp_path / "approval.json"
    path.write_text(json.dumps(approval))
    assert runner._load_approval(path, fixture)["schema_version"] == "plan70-writing-ab-approval/2"
    with pytest.raises(ValueError, match="read-only"):
        runner.run(fixture=fixture, approval=approval, output=tmp_path / "result.json",
                   route_url="http://fixture.test/writing-ab",
                   active_model=lambda _: pytest.fail("must not probe"))


def test_checkpoint_lock_rejects_concurrent_run_before_probe(tmp_path):
    output = tmp_path / "result.json"
    with output.with_suffix(".json.lock").open("a") as lock:
        runner.fcntl.flock(lock, runner.fcntl.LOCK_EX | runner.fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="already in use"):
            runner.run(output=output)


def test_prose_adapter_checks_before_forwarding_and_never_forwards_twice():
    import asyncio
    from uuid import UUID, uuid4
    helpers = transport_helpers()
    helpers.update(UUID=UUID, ChapterGenerationJob=object)
    seed = SimpleNamespace(**fixture_value()["pairs"][0]["seed"])
    outline = helpers["_plan70_outline_fields"](seed)
    blocks = [
        {"section": "formal_planning", "content": "\n".join(outline.values())},
        {"section": "chapter_requirements", "content": "\n".join(
            getattr(seed, key) for key in ("expectation_text", "outline_text", "forbidden_text"))},
    ]
    document_id = uuid4()
    snapshot = {"brief": {"version": 1}, "writing_context": {"envelope": {"included_blocks": blocks}}}
    prompt = "\n".join(block["content"] for block in blocks)
    calls = []
    async def chat(*args, **kwargs):
        calls.append((args, kwargs))
        return "fake reply"
    session = SimpleNamespace(
        get=lambda *args: SimpleNamespace(document_id=document_id, generation_context_snapshot=snapshot),
        rollback=lambda: None,
    )
    adapter = helpers["_Plan70ProseContext"](SimpleNamespace(chat=chat), session, document_id, seed)
    session_id = f"novel-generation:{uuid4()}"
    with pytest.raises(ValueError, match="missing: idea"):
        asyncio.run(adapter.chat(prompt.replace(seed.idea, ""), skill=None, session_id=session_id))
    assert calls == []
    assert asyncio.run(adapter.chat(prompt, skill=None, session_id=session_id)) == "fake reply"
    assert len(calls) == 1
    assert adapter.evidence["prompt_sha256"] == runner._sha256(prompt)
    with pytest.raises(ValueError, match="repeated"):
        asyncio.run(adapter.chat(prompt, skill=None, session_id=session_id))
    assert len(calls) == 1


@pytest.mark.parametrize("field", ["input_evidence", "visible_character_count", "sources"])
def test_runner_rejects_missing_or_altered_evidence(tmp_path, field):
    fixture = fixture_value()
    output = tmp_path / "result.json"
    def request_cell(_, payload):
        result = response_for(payload)
        if field == "input_evidence":
            del result[field]
        elif field == "visible_character_count":
            result["generation"]["candidate"][field] += 1
        else:
            result["input_evidence"]["sources"]["idea"] = "altered ability"
            result["input_evidence"]["source_hash"] = runner.canonical_hash(result["input_evidence"]["sources"])
        return result
    assert runner.run(fixture=fixture, approval=approval_value(fixture), output=output,
                      route_url="http://fixture.test/writing-ab", active_model=lambda _: MODEL,
                      request_cell=request_cell) == runner.EXIT_STOPPED
    assert json.loads(output.read_bytes())["prose_calls"] == 1


@pytest.mark.parametrize("pair_index", range(4))
def test_real_domain_formalization_reaches_frozen_prompt(engine, monkeypatch, pair_index):
    from uuid import UUID, uuid4
    from sqlalchemy.orm import Session
    from backend.creative_authority import save_outline
    from backend.embedding.writing import resolve_writing_position
    from backend.narration import official_voice_selection
    from backend.services import create_novel, save_chapter_brief, prepare_chapter_generation, build_chapter_generation_prompt
    monkeypatch.setattr(official_voice_selection, "initialize_new_novel_default_narrator", lambda *a, **k: None)
    seed = SimpleNamespace(**fixture_value()["pairs"][pair_index]["seed"])
    helper = transport_helpers()
    with Session(engine) as session:
        created = create_novel(session, "plan70-input-offline-test", seed.description)
        novel_id, document_id = UUID(created["id"]), UUID(created["initial_document_id"])
        save_chapter_brief(session, document_id, expected_version=0, target_word_count=2500,
                           expectation_text=seed.expectation_text, outline_text=seed.outline_text,
                           forbidden_text=seed.forbidden_text, role_constraints={})
        options = dict(expected_brief_version=1, execution_agent_id="ai-novel-writer",
                       requested_provider_id="s58-fake", requested_model_id="s58-fake-model",
                       generation_contract_version="plan70-input-offline/1",
                       effective_context_window_tokens=131072,
                       writing_position=resolve_writing_position(session, document_id))
        before, _ = prepare_chapter_generation(session, document_id, **options)
        with pytest.raises(ValueError, match="missing: description"):
            helper["_plan70_input_evidence"](seed, before, build_chapter_generation_prompt(before))
        saved = save_outline(session, novel_id, expected_head_version=0,
                             idempotency_key=f"plan70-offline:{uuid4()}", source_kind="manual",
                             target_chapter_count=12, **helper["_plan70_outline_fields"](seed))
        session.commit()
        after, _ = prepare_chapter_generation(session, document_id, **options)
        evidence = helper["_plan70_input_evidence"](seed, after, build_chapter_generation_prompt(after))
        formal = [block for block in evidence["included_blocks"] if block["section"] == "formal_planning"]
        assert len(formal) == 1
        assert formal[0]["source_revision_id"] == str(saved.revision.id)
        assert evidence["sources"]["background"] == seed.background
