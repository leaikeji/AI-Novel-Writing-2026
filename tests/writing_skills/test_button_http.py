"""Real FastAPI chapter route + isolated DB + public-shape fake transport."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.orm import Session

from backend.model_runtime import ModelAudit
from backend.models import Document, Novel
from backend.services import save_chapter_brief
from backend.writing_skills import button
from backend.writing_skills.catalog import published_skill_ids
from backend.writing_skills.load_policy import PublicLoadCapabilities, create_managed_method_middleware
from backend.writing_skills.semantic_runtime import SemanticAdapterObservationV1
from scripts.run_plan58_real_semantic_eval import (
    decode_plan70_projection,
    normalize_plan70_projection,
)
from writing_e2e._host_stub import import_app, reply
from .test_button_entrypoints import chapter
from .test_persistence import engine


@pytest.fixture
def harness(engine, chapter, monkeypatch):
    monkeypatch.delenv(button.CHAPTER_SEMANTIC_ROUTING_ENV, raising=False)
    module = import_app(monkeypatch)
    document_id, options, projection, _ = chapter
    with Session(engine) as session:
        novel = session.get(Novel, projection.scope.scope_id)
        novel.genre = "悬疑"
        session.commit()
    app = FastAPI()
    app.include_router(module.router, prefix="/api/ai-novel-world-2026")
    counts = {"model_reads": 0, "catalog_reads": 0, "chat": 0, "injected": 0}
    def database():
        with Session(engine) as session:
            yield session
    async def model():
        counts["model_reads"] += 1
        return ModelAudit(provider_id="s58-fake", model_id="s58-fake-model", source="effective-model-api",
                          agent_id="ai-novel-writer", effective_max_input_length=131072)
    async def chat(prompt, *, skill, session_id):
        counts["chat"] += 1
        assert skill is None
        semantic = session_id.startswith("writing-semantic:")
        if counts.get("raise"):
            raise TimeoutError("fake uncertain transport")
        if not counts.get("unmanaged"):
            context = SimpleNamespace(agent_id="ai-novel-writer", root_agent_id="ai-novel-writer",
                                      session_id=session_id, request=SimpleNamespace(agent_id="ai-novel-writer", session_id=session_id))
            middleware = create_managed_method_middleware(context, None)
            assert middleware is not None
            kwargs = {"messages": [], "tools": []}
            async def raw_model():
                if semantic:
                    counts["semantic_model"] = counts.get("semantic_model", 0) + 1
                    if counts.get("semantic_raise"):
                        raise TimeoutError("fake observed semantic timeout")
                else:
                    counts["injected"] += 1
                assert kwargs["tools"] == [] and kwargs["tool_choice"] is None
                if semantic:
                    assert kwargs["messages"] == []
                else:
                    assert kwargs["messages"][-1].role == "system"
                    assert len(kwargs["messages"][-1].content) >= 4  # primary + dependencies + policy
            await middleware.on_model_call(None, kwargs, raw_model)
            if counts.get("second_model_call"):
                await middleware.on_model_call(None, kwargs, raw_model)
        if semantic:
            route = json.loads(prompt.rsplit("路由数据：", 1)[1])
            counts.setdefault("semantic_routes", []).append(route)
            case_decisions = counts.get("semantic_case_decisions")
            case_decision = case_decisions.pop(0) if case_decisions else None
            def decision_for(item):
                if isinstance(case_decision, dict):
                    return case_decision[item["skill_id"]]
                if item["skill_id"] == "golden-finger-writing" and case_decision:
                    return case_decision
                return counts.get("semantic_decision", "reject")
            text = json.dumps({
                "schema_version": "semantic-route-response/1",
                "decisions": [{
                    "skill_id": item["skill_id"],
                    "decision": decision_for(item),
                    "evidence_refs": [] if decision_for(item) == "unknown"
                    else [route["sources"][-1]["key"]],
                } for item in route["candidates"]],
            }, ensure_ascii=False)
            return reply(text=text, provider_id="s58-fake", model_id="s58-fake-model")
        lengths = counts.get("output_lengths")
        output_length = lengths.pop(0) if lengths else counts.get("output_length", 1000)
        return reply(text="测" * output_length, provider_id="s58-fake",
                     model_id=counts.get("actual_model", "s58-fake-model"))
    app.dependency_overrides[module.get_session] = database
    app.dependency_overrides[module.get_novel_generation_ctx] = lambda: SimpleNamespace(chat=chat)
    app.dependency_overrides[module.get_novel_effective_model_probe] = lambda: model
    @app.get("/api/skills")
    def skills():
        counts["catalog_reads"] += 1
        names = (
            {"prose-writing"}
            if counts.get("primary_only")
            else published_skill_ids(button.SKILLS_ROOT)
        )
        return [{"name": name, "source": "plugin:ai-novel-world-2026", "enabled": True}
                for name in names]
    monkeypatch.setattr(button, "CHAPTER_CAPABILITIES", PublicLoadCapabilities(True, True, True))
    payload = {"expected_brief_version": options["expected_brief_version"],
               "writing_action": {"action_id": str(uuid4()), "tab_id": "http-test"}}
    path = f"/api/ai-novel-world-2026/documents/{document_id}/generation-jobs/body"
    return app, counts, path, payload


@pytest.mark.asyncio
async def test_http_generates_once_with_real_injection_and_replay_reads_no_current_config(harness):
    app, counts, path, payload = harness
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(path, json=payload)
        assert first.status_code == 201, first.text
        value = first.json()
        assert value["state"] == "ready" and value["candidate"]
        assert value["writing_method"]["state"] == "dispatched"
        assert value["writing_method"]["selected_ids"] == ["suspense-writing"]
        details = value["writing_method"]["details"]
        assert [(item["skill_id"], item["version"]) for item in details["methods"]] == [
            ("prose-writing", "0.4.0"), ("suspense-writing", "1.0.1")]
        assert details["methods"][0]["reference_count"] == 2
        assert counts["chat"] == counts["injected"] == 1
        before = dict(counts)
        replay = await client.post(path, json=payload)
        assert replay.status_code == 201 and replay.json()["id"] == value["id"]
        assert counts == before
        changed = await client.post(path, json={**payload, "force_new": True})
        assert changed.status_code == 409
        assert counts == before


@pytest.mark.asyncio
async def test_internal_semantic_adapter_routes_once_then_replay_is_read_only(
    harness, monkeypatch
):
    import json

    app, counts, path, payload = harness
    original = button.generate_managed_chapter

    async def semantic_call(_prompt, request):
        counts["semantic"] = counts.get("semantic", 0) + 1
        return SemanticAdapterObservationV1(
            status="ok",
            text=json.dumps({
                "schema_version": "semantic-route-response/1",
                "decisions": [{
                    "skill_id": item.skill_id,
                    "decision": "reject",
                    "evidence_refs": [request.sources[0].key],
                } for item in request.candidates],
            }),
            model_rounds=1,
            tool_calls=0,
            transport_attempts=1,
        )

    async def enabled(**kwargs):
        kwargs["semantic_call_factory"] = (
            lambda _session, _verify, _model: semantic_call
        )
        return await original(**kwargs)

    monkeypatch.setattr(button, "generate_managed_chapter", enabled)
    payload["writing_action"]["preferences"] = {
        "mode": "auto", "semantic_mode": "auto"
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post(path, json=payload)
        assert first.status_code == 201, first.text
        method = first.json()["writing_method"]
        assert method["state"] == "dispatched"
        assert method["semantic_enabled"] is True
        assert method["auxiliary_calls"] == 1
        assert counts["semantic"] == counts["chat"] == 1
        frozen_hash = method["method_input_hash"]
        before = dict(counts)
        replay = await client.post(path, json=payload)
        assert replay.status_code == 201
        assert replay.json()["writing_method"]["method_input_hash"] == frozen_hash
        assert counts == before


@pytest.mark.asyncio
async def test_product_chapter_route_uses_server_gate_for_one_semantic_round(
    harness, monkeypatch
):
    app, counts, path, payload = harness
    monkeypatch.setenv(button.CHAPTER_SEMANTIC_ROUTING_ENV, "true")
    counts["semantic_decision"] = "select"
    payload["writing_action"]["preferences"] = {
        "mode": "auto", "semantic_mode": "auto",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post(path, json=payload)
        assert first.status_code == 201, first.text
        method = first.json()["writing_method"]
        assert method["state"] == "dispatched"
        assert method["semantic_enabled"] is True
        assert method["auxiliary_calls"] == 1
        assert method["selected_ids"] == [
            "suspense-writing", "golden-finger-writing",
        ]
        assert counts["semantic_model"] == counts["injected"] == 1
        assert counts["chat"] == 2
        before = dict(counts)
        replay = await client.post(path, json=payload)
        assert replay.status_code == 201
        assert replay.json()["id"] == first.json()["id"]
        assert counts == before


@pytest.mark.asyncio
async def test_plan70_frozen_material_flows_through_actual_chapter_projection(
    harness, monkeypatch, engine
):
    app, counts, path, payload = harness
    fixture = json.loads((
        Path(__file__).with_name("fixtures") / "plan70_chapter_scenarios.json"
    ).read_text(encoding="utf-8"))
    cases = fixture["scenarios"]
    monkeypatch.setenv(button.CHAPTER_SEMANTIC_ROUTING_ENV, "true")
    counts["semantic_case_decisions"] = []
    payload["force_new"] = True
    document_id = UUID(path.split("/")[-3])
    observed = []
    captured_projections = {}
    original_projection = button.chapter_routing_projection

    def capture_projection(*args, **kwargs):
        projection = original_projection(*args, **kwargs)
        captured_projections.setdefault(projection.source_hash, projection)
        return projection

    monkeypatch.setattr(button, "chapter_routing_projection", capture_projection)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for case in cases:
            with Session(engine) as session:
                document = session.get(Document, document_id)
                assert document is not None
                novel = session.get(Novel, document.novel_id)
                assert novel is not None
                novel.genre = case["genre"]
                novel.subgenre = case["subgenre"]
                brief = save_chapter_brief(
                    session, document_id,
                    expected_version=payload["expected_brief_version"],
                    target_word_count=1000,
                    expectation_text=case["expectation"],
                    outline_text=case["outline"],
                    forbidden_text=(
                        case["forbidden"]
                        + case.get("padding_unit", "") * case.get("padding_repeat", 0)
                        + case.get("tail_sentinel", "")
                    ),
                    role_constraints={},
                )
            payload["expected_brief_version"] = brief["version"]
            payload["writing_action"] = {
                "action_id": str(uuid4()), "tab_id": "http-test",
                "preferences": {"mode": "auto", "semantic_mode": "auto"},
            }
            if case["expected_case_outcome"] != "skip":
                counts["semantic_case_decisions"].append(case["expected_by_skill"])
            response = await client.post(path, json=payload)
            if "unknown" in case.get("expected_by_skill", {}).values():
                assert response.status_code == 502, (case["id"], response.text)
                method = response.json()["detail"]["writing_method"]
                assert method["state"] == "failed"
            else:
                assert response.status_code == 201, (case["id"], response.text)
                method = response.json()["writing_method"]
                assert method["state"] == "dispatched"
                assert method["auxiliary_calls"] == case["expected_auxiliary_calls"]
                assert method["semantic_enabled"] is (
                    case["expected_case_outcome"] != "skip"
                )
                if case["expected_case_outcome"] == "route":
                    expected_selected = {
                        skill_id for skill_id, decision
                        in case["expected_by_skill"].items()
                        if decision == "select"
                    }
                    assert expected_selected <= set(method["selected_ids"])
            observed.append((case["id"], method["state"]))

    routes = counts["semantic_routes"]
    assert len(routes) == 19
    assert counts["semantic_model"] == 19
    assert counts["injected"] == 19  # 10 select + 8 reject + 1 zero-call skip.
    assert counts["chat"] == 38
    assert len({route["source_hash"] for route in routes}) == 19
    assert len(captured_projections) == 20
    routed_cases = [
        case for case in cases if case["expected_case_outcome"] != "skip"
    ]
    for case, route in zip(routed_cases, routes, strict=True):
        assert route["task"] == "chapter_body"
        assert all(source["kind"] != "mechanism" for source in route["sources"])
        routed_text = "\n".join(
            source["text"] for source in route["sources"] if source["kind"] == "content"
        )
        assert case["expectation"] in routed_text
        if case["id"] != "P70-C20":
            assert case["outline"] in routed_text
    boundary_route = routes[-1]
    boundary_projection = captured_projections[boundary_route["source_hash"]]
    assert boundary_projection.truncated is True
    assert sum(len(source.text) for source in boundary_projection.sources) == 80000
    assert cases[-1]["expectation"] in "\n".join(
        source.text for source in boundary_projection.sources
    )
    assert cases[-1]["tail_sentinel"] not in "\n".join(
        source.text for source in boundary_projection.sources
    )
    assert len(observed) == 20
    frozen = json.loads((
        Path(__file__).with_name("fixtures")
        / "plan70_chapter_route_requests.json"
    ).read_text(encoding="utf-8"))
    assert frozen["normalization"] == (
        "actual-chapter-context-block-projection-stable-identities/2"
    )
    assert frozen["projection_encoding"] == "zlib-base64-canonical-json/1"
    projections = list(captured_projections.values())
    assert [item["id"] for item in frozen["cases"]] == [case["id"] for case in cases]
    for case, projection, stored in zip(
        cases, projections, frozen["cases"], strict=True
    ):
        assert stored["expected"] == case["expected"]
        assert stored["expected_case_outcome"] == case["expected_case_outcome"]
        assert stored.get("expected_by_skill") == case.get("expected_by_skill")
        assert stored["expected_auxiliary_calls"] == case["expected_auxiliary_calls"]
        assert decode_plan70_projection(stored) == normalize_plan70_projection(
            projection, case["id"]
        )


@pytest.mark.asyncio
async def test_client_cannot_open_semantic_gate_and_empty_story_skips_auxiliary_call(
    harness, monkeypatch, engine
):
    app, counts, path, payload = harness
    payload["writing_action"]["preferences"] = {
        "mode": "auto", "semantic_mode": "auto",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        closed = await client.post(path, json=payload)
        assert closed.status_code == 409
        assert "not released" in closed.json()["detail"]
        assert counts == {
            "model_reads": 0, "catalog_reads": 0, "chat": 0, "injected": 0,
        }

        document_id = UUID(path.split("/")[-3])
        with Session(engine) as session:
            brief = save_chapter_brief(
                session, document_id, expected_version=payload["expected_brief_version"],
                target_word_count=1000, expectation_text="", outline_text="",
                forbidden_text="", role_constraints={},
            )
        payload["expected_brief_version"] = brief["version"]
        payload["writing_action"]["action_id"] = str(uuid4())
        monkeypatch.setenv(button.CHAPTER_SEMANTIC_ROUTING_ENV, "true")
        generated = await client.post(path, json=payload)
        assert generated.status_code == 201, generated.text
        method = generated.json()["writing_method"]
        assert method["semantic_enabled"] is False
        assert method["auxiliary_calls"] == 0
        assert "semantic_model" not in counts
        assert counts["chat"] == counts["injected"] == 1


@pytest.mark.asyncio
async def test_semantic_abstention_and_observed_timeout_have_distinct_safe_results(
    harness, monkeypatch
):
    app, counts, path, payload = harness
    monkeypatch.setenv(button.CHAPTER_SEMANTIC_ROUTING_ENV, "true")
    payload["writing_action"]["preferences"] = {
        "mode": "auto", "semantic_mode": "auto",
    }
    counts["semantic_decision"] = "unknown"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        abstained = await client.post(path, json=payload)
        assert abstained.status_code == 502
        detail = abstained.json()["detail"]
        assert detail["type"] == "semantic_route_incomplete"
        assert detail["writing_method"]["state"] == "failed"
        assert "未能确认本章适用方法" in detail["message"]
        assert counts["injected"] == 0

        payload["writing_action"]["action_id"] = str(uuid4())
        counts["semantic_raise"] = True
        timed_out = await client.post(path, json=payload)
        assert timed_out.status_code == 502
        detail = timed_out.json()["detail"]
        assert detail["type"] == "semantic_route_incomplete"
        assert detail["writing_method"]["state"] == "unknown"
        assert "原请求结果尚未确认" in detail["message"]
        assert counts["injected"] == 0


def test_chapter_semantic_release_gate_is_strict_and_fail_closed():
    key = button.CHAPTER_SEMANTIC_ROUTING_ENV
    assert button.chapter_semantic_routing_enabled({}) is False
    assert button.chapter_semantic_routing_enabled({key: "false"}) is False
    assert button.chapter_semantic_routing_enabled({key: "1"}) is False
    assert button.chapter_semantic_routing_enabled({key: " TRUE "}) is True


@pytest.mark.asyncio
async def test_uncertain_semantic_route_never_dispatches_writing_or_replays(
    harness, monkeypatch
):
    app, counts, path, payload = harness
    original = button.generate_managed_chapter

    async def semantic_call(_prompt, _request):
        counts["semantic"] = counts.get("semantic", 0) + 1
        return SemanticAdapterObservationV1(
            status="unknown",
            text=None,
            model_rounds=1,
            tool_calls=0,
            transport_attempts=1,
        )

    async def enabled(**kwargs):
        kwargs["semantic_call_factory"] = (
            lambda _session, _verify, _model: semantic_call
        )
        return await original(**kwargs)

    monkeypatch.setattr(button, "generate_managed_chapter", enabled)
    payload["writing_action"]["preferences"] = {
        "mode": "auto", "semantic_mode": "auto"
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post(path, json=payload)
        assert first.status_code == 502, first.text
        assert first.json()["detail"]["writing_method"]["state"] == "unknown"
        assert counts["semantic"] == 1
        assert counts["chat"] == 0
        before = dict(counts)
        replay = await client.post(path, json=payload)
        assert replay.status_code == 201
        assert replay.json()["writing_method"]["state"] == "unknown"
        assert counts == before
        changed = await client.post(path, json={**payload, "force_new": True})
        assert changed.status_code == 409
        assert counts == before


@pytest.mark.asyncio
async def test_released_server_gate_rejects_legacy_chapter_request_before_io(harness):
    app, counts, path, payload = harness
    payload.pop("writing_action")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(path, json=payload)
    assert response.status_code == 409
    assert response.json()["detail"]["type"] == "managed_writing_action_required"
    assert counts == {
        "model_reads": 0,
        "catalog_reads": 0,
        "chat": 0,
        "injected": 0,
    }
@pytest.mark.asyncio
async def test_history_reads_frozen_methods_after_current_relation_drift_without_reresolving(harness, monkeypatch, tmp_path):
    import json
    from shutil import copytree

    app, counts, path, payload = harness
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        generated = (await client.post(path, json=payload)).json()
        before = dict(counts)
        changed_root = tmp_path / "changed-skills"
        copytree(button.SKILLS_ROOT, changed_root)
        routing_path = changed_root / "golden-finger-writing" / "routing.json"
        routing = json.loads(routing_path.read_text(encoding="utf-8"))
        routing["supersedes"] = ["suspense-writing"]
        routing_path.write_text(
            json.dumps(routing, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(button, "SKILLS_ROOT", changed_root)
        url = path.replace("/generation-jobs/body", f"/generation-jobs/{generated['id']}/writing-method")
        result = await client.get(url, params={"tab_id": "explicit-history-in-another-tab"})
        assert result.status_code == 200, result.text
        history = result.json()
        assert history["record_status"] == "recorded" and history["phase"] == "dispatched"
        assert history["details"] == generated["writing_method"]["details"]
        assert history["method_input_hash"] == generated["writing_method"]["method_input_hash"]
        assert "projection" not in history and "action_id" not in history
        assert "核对线索" not in result.text and "block.text" not in result.text
        assert (await client.get(url.replace(generated["document_id"], str(uuid4())), params={"tab_id": "wrong"})).status_code == 404
        assert counts == before


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", ["job_ref", "document_scope", "input_hash", "null_reference", "malformed_snapshot"])
async def test_history_rejects_mismatched_frozen_bindings(harness, engine, damage):
    from copy import deepcopy
    from uuid import UUID
    from backend.models import ChapterGenerationJob
    from backend.writing_skills.models import WritingSkillDispatch
    app, counts, path, payload = harness
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        generated = (await client.post(path, json=payload)).json()
        before = dict(counts)
        with Session(engine) as session:
            job = session.get(ChapterGenerationJob, UUID(generated["id"]))
            snapshot = deepcopy(job.generation_context_snapshot)
            dispatch = session.get(WritingSkillDispatch, UUID(snapshot["skill_invocation"]["dispatch_id"]))
            if damage in ("job_ref", "document_scope"):
                # Existing dispatch rows are immutable even in the test DB.
                # Insert a malformed fixture reference; never disable guards.
                values = {column.name: deepcopy(getattr(dispatch, column.name))
                          for column in WritingSkillDispatch.__table__.columns}
                values.update(id=uuid4(), action_id=uuid4())
                dispatch = WritingSkillDispatch(**values)
                session.add(dispatch)
                snapshot["skill_invocation"]["dispatch_id"] = str(dispatch.id)
            if damage == "job_ref":
                dispatch.job_ref = f"chapter:{uuid4()}"
            elif damage == "document_scope":
                route = deepcopy(dispatch.route_snapshot)
                route["projection"]["scope"]["document_id"] = str(uuid4())
                dispatch.route_snapshot = route
            elif damage == "input_hash":
                snapshot["skill_invocation"]["method_input_hash"] = "0" * 64
            elif damage == "null_reference":
                snapshot["skill_invocation"] = None
            else:
                snapshot = ["malformed test snapshot"]
            job.generation_context_snapshot = snapshot
            session.commit()
        url = path.replace("/generation-jobs/body", f"/generation-jobs/{generated['id']}/writing-method")
        response = await client.get(url, params={"tab_id": "history"})
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["record_status"] == "evidence_unavailable"
        assert result["details"] is result["method_input_hash"] is result["phase"] is None
        assert counts == before


@pytest.mark.asyncio
async def test_history_labels_legacy_and_broken_references_without_backfilling(harness, chapter, engine):
    from backend.models import ChapterGenerationJob
    from uuid import UUID
    app, counts, path, _ = harness
    legacy = chapter[3]
    url = path.replace("/generation-jobs/body", f"/generation-jobs/{legacy['id']}/writing-method")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        before = dict(counts)
        result = await client.get(url, params={"tab_id": "history"})
        assert result.status_code == 200
        assert result.json()["record_status"] == "legacy_unrecorded"
        with Session(engine) as session:
            job = session.get(ChapterGenerationJob, UUID(legacy["id"]))
            assert "skill_invocation" not in job.generation_context_snapshot
            # Deliberately damaged test reference, not a historical backfill.
            job.generation_context_snapshot = {**job.generation_context_snapshot, "skill_invocation": {
                "schema_version": "job-skill-invocation/1", "dispatch_id": str(uuid4()), "method_input_hash": "a" * 64}}
            session.commit()
        damaged = (await client.get(url, params={"tab_id": "history"})).json()
        assert damaged["record_status"] == "evidence_unavailable" and damaged["details"] is None
        assert counts == before


@pytest.mark.asyncio
async def test_http_unknown_does_not_retry_or_change_methods(harness):
    app, counts, path, payload = harness
    counts["raise"] = True
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(path, json=payload)
        assert first.status_code == 502, first.text
        detail = first.json()["detail"]
        assert detail["writing_method"]["state"] == "unknown"
        assert detail["job"]["state"] == "failed"
        assert detail["retry_policy"]["decision"] == "confirm_required"
        before = dict(counts)
        replay = await client.post(path, json=payload)
        assert replay.json()["writing_method"]["state"] == "unknown"
        assert replay.json()["retry_policy"]["decision"] == "confirm_required"
        assert counts == before


@pytest.mark.asyncio
async def test_second_tab_gets_existing_active_job_before_model_or_catalog_io(
    harness, monkeypatch
):
    app, counts, path, payload = harness
    active_id = str(uuid4())
    monkeypatch.setattr(button, "get_active_chapter_generation_job", lambda *_: {
        "id": active_id,
        "document_id": path.split("/")[-3],
        "kind": "body",
        "state": "running",
    })
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        result = await client.post(path, json=payload)
    assert result.status_code == 409
    detail = result.json()["detail"]
    assert detail["type"] == "chapter_generation_in_progress"
    assert detail["job"]["id"] == active_id
    assert detail["retry_policy"] == {
        "decision": "blocked_active",
        "reason": "请查看或刷新原任务进度。",
        "active_job_id": active_id,
    }
    assert counts == {
        "model_reads": 0, "catalog_reads": 0, "chat": 0, "injected": 0,
    }


@pytest.mark.asyncio
async def test_authoritative_active_race_keeps_blocked_policy(harness, monkeypatch):
    from backend.services import ChapterGenerationInProgressError

    app, counts, path, payload = harness
    active_id = str(uuid4())
    monkeypatch.setattr(button, "get_active_chapter_generation_job", lambda *_: None)
    def conflict(*_args, **_kwargs):
        raise ChapterGenerationInProgressError({
            "id": active_id, "document_id": path.split("/")[-3],
            "kind": "body", "state": "running",
        })
    monkeypatch.setattr(button, "start_chapter_generation", conflict)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        result = await client.post(path, json=payload)
    assert result.status_code == 409
    detail = result.json()["detail"]
    assert detail["type"] == "chapter_generation_in_progress"
    assert detail["retry_policy"]["decision"] == "blocked_active"
    assert detail["retry_policy"]["active_job_id"] == active_id
    assert counts["chat"] == counts["injected"] == 0


@pytest.mark.asyncio
async def test_http_cannot_accept_reply_without_actual_method_injection(harness):
    app, counts, path, payload = harness
    counts["unmanaged"] = True
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        result = await client.post(path, json=payload)
    assert result.status_code == 502
    assert result.json()["detail"]["writing_method"]["state"] == "failed"


@pytest.mark.asyncio
async def test_http_release_gate_is_not_a_client_preference(harness, monkeypatch):
    app, counts, path, payload = harness
    monkeypatch.setattr(button, "CHAPTER_CAPABILITIES", PublicLoadCapabilities())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        result = await client.post(path, json=payload)
    assert result.status_code == 503
    assert not any(counts.values())


@pytest.mark.asyncio
async def test_http_duplicate_during_retrieval_does_not_prepare_again(harness, monkeypatch):
    app, counts, path, payload = harness
    entered, release = asyncio.Event(), asyncio.Event()
    original = button.retrieve_for_writing
    async def paused(*args, **kwargs):
        counts["retrieval"] = counts.get("retrieval", 0) + 1
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)
    monkeypatch.setattr(button, "retrieve_for_writing", paused)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        first_task = asyncio.create_task(client.post(path, json=payload))
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            before = dict(counts)
            duplicate = await client.post(path, json=payload)
            assert duplicate.status_code == 201, duplicate.text
            assert duplicate.json()["writing_method"]["state"] == "claimed"
            assert duplicate.json()["writing_method"]["method_input_hash"] is None
            assert counts == before
        finally:
            release.set()
            result = await first_task
        assert result.status_code == 201, result.text
        assert counts["retrieval"] == counts["chat"] == 1


@pytest.mark.asyncio
async def test_http_preparation_failure_keeps_action_and_does_not_retry(harness, monkeypatch):
    app, counts, path, payload = harness
    async def unavailable(*args, **kwargs):
        counts["retrieval"] = counts.get("retrieval", 0) + 1
        raise RuntimeError("fake input preparation unavailable")
    monkeypatch.setattr(button, "retrieve_for_writing", unavailable)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(path, json=payload)
        assert first.status_code == 502
        assert first.json()["detail"]["writing_method"]["state"] == "failed"
        before = dict(counts)
        replay = await client.post(path, json=payload)
        assert replay.json()["writing_method"]["state"] == "failed"
        assert counts == before and counts["chat"] == 0


@pytest.mark.asyncio
async def test_http_second_model_call_is_rejected_before_transport(harness):
    app, counts, path, payload = harness
    counts["second_model_call"] = True
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        result = await client.post(path, json=payload)
    assert result.status_code == 502
    assert counts["injected"] == 1
    # First transport occurred but no public reply returned: conservative unknown.
    assert result.json()["detail"]["writing_method"]["state"] == "unknown"


@pytest.mark.asyncio
async def test_http_length_rejection_preserves_existing_envelope_and_action(harness):
    app, counts, path, payload = harness
    counts["output_length"] = 100
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        result = await client.post(path, json=payload)
        assert result.status_code == 422, result.text
        detail = result.json()["detail"]
        assert detail["type"] == "chapter_length_out_of_range" and detail["retryable"] is True
        assert detail["direction"] == "below_target"
        assert detail["output_visible_character_count"] == 100
        assert detail["job"]["state"] == "failed"
        assert detail["job"]["actual_model_id"] == "s58-fake-model"
        assert "generation_context_snapshot" not in detail["job"]
        before = dict(counts)
        replay = await client.post(path, json=payload)
        assert replay.json()["state"] == "failed" and counts == before


@pytest.mark.asyncio
async def test_length_retry_reuses_exact_frozen_packet_without_rerouting(harness, monkeypatch, engine):
    from copy import deepcopy
    from uuid import UUID
    from backend.models import ChapterGenerationJob
    from backend.writing_skills.models import WritingSkillDispatch
    app, counts, path, payload = harness
    counts["output_lengths"] = [100, 120, 1000]
    resolver_calls = 0
    composer_calls = 0
    original_resolver, original_composer = button.resolve_methods, button.compose_writing_request
    def resolver(*args, **kwargs):
        nonlocal resolver_calls
        resolver_calls += 1
        return original_resolver(*args, **kwargs)
    def composer(*args, **kwargs):
        nonlocal composer_calls
        composer_calls += 1
        return original_composer(*args, **kwargs)
    monkeypatch.setattr(button, "resolve_methods", resolver)
    monkeypatch.setattr(button, "compose_writing_request", composer)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(path, json=payload)
        assert first.status_code == 422, first.text
        first_detail = first.json()["detail"]
        first_method = first_detail["writing_method"]
        retry_payload = deepcopy(payload)
        retry_payload["force_new"] = True
        retry_payload["writing_action"]["action_id"] = str(uuid4())
        retry_payload["writing_action"]["retry_of_action_id"] = first_method["action_id"]
        second = await client.post(path, json=retry_payload)
        assert second.status_code == 422, second.text
        second_detail = second.json()["detail"]
        second_method = second_detail["writing_method"]
        third_payload = deepcopy(payload)
        third_payload["force_new"] = True
        third_payload["writing_action"]["action_id"] = str(uuid4())
        third_payload["writing_action"]["retry_of_action_id"] = second_method["action_id"]
        third = await client.post(path, json=third_payload)
        assert third.status_code == 201, third.text
        third_value = third.json()
        third_method = third_value["writing_method"]
        assert third_value["state"] == "ready"
        assert len({first_method["dispatch_id"], second_method["dispatch_id"], third_method["dispatch_id"]}) == 3
        assert second_method["method_input_hash"] == third_method["method_input_hash"] == first_method["method_input_hash"]
        assert second_method["details"] == third_method["details"] == first_method["details"]
        assert resolver_calls == composer_calls == 1
        assert counts["chat"] == counts["injected"] == 3
        with Session(engine) as session:
            retry_dispatch = session.get(WritingSkillDispatch, UUID(third_method["dispatch_id"]))
            retry_job = session.get(ChapterGenerationJob, UUID(third_value["id"]))
            assert retry_dispatch.route_snapshot["retry_of_action_id"] == second_method["action_id"]
            invocation = retry_job.generation_context_snapshot["skill_invocation"]
            assert invocation["retry_of_action_id"] == second_method["action_id"]
            assert retry_job.generation_context_snapshot["length_control"]["previous_visible_character_count"] == 120


@pytest.mark.asyncio
async def test_length_retry_rejects_changed_method_choice_before_model(harness):
    from copy import deepcopy
    app, counts, path, payload = harness
    counts["output_length"] = 100
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        first = (await client.post(path, json=payload)).json()["detail"]
        before = dict(counts)
        retry = deepcopy(payload)
        retry["force_new"] = True
        retry["writing_action"] = {"action_id": str(uuid4()), "tab_id": "http-test",
            "retry_of_action_id": first["writing_method"]["action_id"],
            "preferences": {"mode": "generic_only", "semantic_mode": "off"}}
        result = await client.post(path, json=retry)
        assert result.status_code == 409
        assert counts == before


@pytest.mark.asyncio
async def test_http_model_mismatch_records_rejected_evidence_and_no_candidate(harness):
    app, counts, path, payload = harness
    counts["actual_model"] = "s58-wrong-model"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(path, json=payload)
        assert first.status_code == 502
        replay = await client.post(path, json=payload)
        job = replay.json()
        assert job["state"] == "failed" and not job["candidate"]
        assert job["requested_model_id"] == "s58-fake-model"
        assert job["actual_model_id"] == "s58-wrong-model"
        assert job["model_evidence"]
        assert counts["chat"] == 1


@pytest.mark.asyncio
async def test_read_only_recovery_and_status_never_reenter_model_or_config(harness):
    app, counts, path, payload = harness
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        first = (await client.post(path, json=payload)).json()
        method = first["writing_method"]
        before = dict(counts)
        action_path = path.replace("generation-jobs/body", f"writing-method-actions/{method['action_id']}")
        recovered = await client.get(action_path, params={"tab_id": "http-test"})
        assert recovered.status_code == 200 and recovered.json()["id"] == first["id"]
        status_path = f"/api/ai-novel-world-2026/writing-skill-dispatches/{method['dispatch_id']}"
        query = {"document_id": first["document_id"], "tab_id": "http-test", "action_id": method["action_id"]}
        status = await client.get(status_path, params=query)
        assert status.status_code == 200 and status.json() == method
        assert "candidate" not in status.json()
        assert "generation_context_snapshot" not in recovered.json()
        for changed in ({"tab_id": "wrong-tab"}, {"document_id": str(uuid4())}, {"action_id": str(uuid4())}):
            assert (await client.get(status_path, params={**query, **changed})).status_code == 404
        assert (await client.get(status_path.replace(method["dispatch_id"], str(uuid4())), params=query)).status_code == 404
        assert counts == before


@pytest.mark.asyncio
async def test_discovery_reports_real_server_gate_without_model_calls(harness, monkeypatch):
    app, counts, _, _ = harness
    monkeypatch.setattr(button, "CHAPTER_CAPABILITIES", PublicLoadCapabilities())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        result = await client.get("/api/ai-novel-world-2026/writing-skills")
    assert result.status_code == 200, result.text
    value = result.json()
    assert value["chapter_body_available"] is False and value["semantic_available"] is False
    assert {item["skill_id"] for item in value["capabilities"]} == {"suspense-writing", "golden-finger-writing"}
    assert counts == {"model_reads": 0, "catalog_reads": 1, "chat": 0, "injected": 0}


@pytest.mark.asyncio
async def test_discovery_opens_semantic_only_for_released_chapter_scope(harness, monkeypatch):
    app, counts, path, _ = harness
    monkeypatch.setenv(button.CHAPTER_SEMANTIC_ROUTING_ENV, "true")
    document_id = path.split("/")[-3]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        scoped = await client.get(
            "/api/ai-novel-world-2026/writing-skills",
            params={"document_id": document_id, "tab_id": "http-test"},
        )
        assert scoped.status_code == 200, scoped.text
        assert scoped.json()["chapter_body_available"] is True
        assert scoped.json()["semantic_available"] is True
        unscoped = await client.get("/api/ai-novel-world-2026/writing-skills")
        assert unscoped.status_code == 200
        assert unscoped.json()["semantic_available"] is False
    assert counts["chat"] == counts["injected"] == 0


@pytest.mark.asyncio
async def test_discovery_does_not_claim_semantic_ready_without_an_enabled_candidate(
    harness, monkeypatch
):
    app, counts, path, _ = harness
    monkeypatch.setenv(button.CHAPTER_SEMANTIC_ROUTING_ENV, "true")
    counts["primary_only"] = True
    document_id = path.split("/")[-3]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/ai-novel-world-2026/writing-skills",
            params={"document_id": document_id, "tab_id": "http-test"},
        )
    assert response.status_code == 200, response.text
    assert response.json()["chapter_body_available"] is True
    assert response.json()["semantic_available"] is False
    assert response.json()["capabilities"] == []
    assert counts["chat"] == counts["injected"] == 0


@pytest.mark.asyncio
async def test_catalog_failure_does_not_hide_authorized_recovery_scope(harness, monkeypatch):
    app, counts, path, payload = harness
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        job = (await client.post(path, json=payload)).json()
        before = dict(counts)
        async def unavailable(*_):
            raise ValueError("fake damaged catalog")
        monkeypatch.setattr(button, "current_catalog", unavailable)
        catalog = await client.get("/api/ai-novel-world-2026/writing-skills",
            params={"document_id": job["document_id"], "tab_id": "http-test"})
        assert catalog.status_code == 200
        assert catalog.json()["catalog_available"] is False
        assert catalog.json()["chapter_body_available"] is False
        assert catalog.json()["scope"]["document_id"] == job["document_id"]
        action = job["writing_method"]["action_id"]
        result = await client.get(path.replace("generation-jobs/body", f"writing-method-actions/{action}"),
                                  params={"tab_id": "http-test"})
        assert result.status_code == 200 and result.json()["id"] == job["id"]
        assert counts == before
