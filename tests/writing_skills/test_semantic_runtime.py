"""No-network semantic runtime prompt, strict parser and one-call tests."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from backend.writing_skills.contracts import MethodPreferences
from backend.writing_skills.resolver import resolve_methods
from backend.writing_skills.semantic import SemanticCandidateV1, SemanticRouteRequestV2
from backend.writing_skills.semantic_runtime import (
    SemanticAdapterObservationV1,
    build_semantic_prompt,
    parse_semantic_response,
    public_semantic_call,
    run_semantic_transport,
)
from backend.writing_skills.load_policy import (
    PublicLoadCapabilities,
    create_managed_method_middleware,
)
from tests.writing_skills.test_evaluation_contract import (
    evaluation_catalog,
    synthetic_projection as projection,
    scenarios,
)


def request() -> SemanticRouteRequestV2:
    value = scenarios()
    catalog = evaluation_catalog(value)
    case = value["s_scenarios"][0]
    source = projection(case)
    plan = resolve_methods(source, catalog, MethodPreferences(), "prose-writing")
    capability_by_id = {
        item.declaration.skill_id: item for item in catalog.capabilities
    }
    return SemanticRouteRequestV2(
        source_hash=source.source_hash,
        catalog_version=catalog.version,
        task=source.task,
        intent=source.intent,
        operation=source.operation,
        sources=source.sources,
        candidates=tuple(
            SemanticCandidateV1(
                skill_id=skill_id,
                kind=capability_by_id[skill_id].declaration.kind,
                description=capability_by_id[skill_id].declaration.description,
                semantic_criteria=capability_by_id[skill_id].declaration.semantic_criteria,
                negative_examples=capability_by_id[skill_id].declaration.negative_examples,
                conflicts_with=capability_by_id[skill_id].declaration.conflicts_with,
                supersedes=capability_by_id[skill_id].declaration.supersedes,
            ) for skill_id in plan.unresolved_ids
        ),
    )


def response(req: SemanticRouteRequestV2) -> str:
    return json.dumps({
        "schema_version": "semantic-route-response/1",
        "decisions": [{
            "skill_id": item.skill_id,
            "decision": "reject",
            "evidence_refs": [req.sources[0].key],
        } for item in req.candidates],
    }, ensure_ascii=False)


def observation(req, **changes):
    values = dict(
        status="ok", text=response(req), model_rounds=1,
        tool_calls=0, transport_attempts=1, recursion_detected=False,
    )
    values.update(changes)
    return SemanticAdapterObservationV1(**values)


def test_prompt_contains_only_frozen_projection_and_candidate_metadata():
    req = request()
    prompt = build_semantic_prompt(req)
    assert req.sources[0].text in prompt
    assert all(item.skill_id in prompt for item in req.candidates)
    assert "writing_skill_routing" in prompt
    assert "不得调用工具" in prompt
    assert "不得省略该字段" in prompt
    assert "supersedes" in prompt
    assert "# 悬疑写作" not in prompt
    assert "# 金手指机制写作" not in prompt


def test_future_specific_candidate_exposes_supersedence_to_the_router():
    value = scenarios()
    catalog = evaluation_catalog(value)
    case = next(item for item in value["s_scenarios"] if item["id"] == "S10")
    source = projection(case)
    plan = resolve_methods(source, catalog, MethodPreferences(), "prose-writing")
    capability_by_id = {
        item.declaration.skill_id: item for item in catalog.capabilities
    }
    req = SemanticRouteRequestV2(
        source_hash=source.source_hash,
        catalog_version=catalog.version,
        task=source.task,
        intent=source.intent,
        operation=source.operation,
        sources=source.sources,
        candidates=tuple(
            SemanticCandidateV1(
                skill_id=skill_id,
                kind=capability_by_id[skill_id].declaration.kind,
                description=capability_by_id[skill_id].declaration.description,
                semantic_criteria=capability_by_id[skill_id].declaration.semantic_criteria,
                negative_examples=capability_by_id[skill_id].declaration.negative_examples,
                conflicts_with=capability_by_id[skill_id].declaration.conflicts_with,
                supersedes=capability_by_id[skill_id].declaration.supersedes,
            )
            for skill_id in plan.unresolved_ids
        ),
    )
    future = next(
        item for item in req.candidates if item.skill_id == "future-time-loop"
    )
    assert future.supersedes == ("golden-finger-writing",)
    assert '"supersedes":["golden-finger-writing"]' in build_semantic_prompt(req)


@pytest.mark.parametrize("text", [
    "```json\n{}\n```",
    "解释如下：{}",
    '{"schema_version":"semantic-route-response/1","schema_version":"semantic-route-response/1","decisions":[]}',
    '{"schema_version":"semantic-route-response/1","decisions":[],"extra":true}',
])
def test_parser_rejects_wrappers_duplicates_empty_and_extra_fields(text):
    with pytest.raises(ValueError):
        parse_semantic_response(text)


@pytest.mark.asyncio
async def test_runtime_calls_adapter_once_and_returns_strict_payload():
    req = request()
    calls = []

    async def call(prompt, observed_request):
        calls.append((prompt, observed_request))
        return observation(req)

    result = await run_semantic_transport(req, call=call)
    assert result.status == "ok"
    assert result.model_rounds == result.transport_attempts == len(calls) == 1
    assert result.tool_calls == 0
    assert result.payload["schema_version"] == "semantic-route-response/1"
    assert calls[0][1] == req


@pytest.mark.asyncio
async def test_invalid_json_and_timeout_are_not_retried():
    req = request()
    invalid_calls = 0

    async def invalid(_prompt, _request):
        nonlocal invalid_calls
        invalid_calls += 1
        return observation(req, text="not-json")

    invalid_result = await run_semantic_transport(req, call=invalid)
    assert invalid_result.status == "failed"
    assert invalid_result.payload is None
    assert invalid_calls == 1

    timeout_calls = 0

    async def timeout(_prompt, _request):
        nonlocal timeout_calls
        timeout_calls += 1
        raise TimeoutError

    timeout_result = await run_semantic_transport(req, call=timeout)
    assert timeout_result.status == "timeout"
    assert timeout_result.payload is None
    assert timeout_calls == timeout_result.transport_attempts == 1


@pytest.mark.asyncio
async def test_cancel_before_call_and_after_observation_are_distinct():
    req = request()
    pre = await run_semantic_transport(
        req, call=lambda *_: pytest.fail("must not call"), cancelled=lambda: True,
    )
    assert pre.status == "cancelled"
    assert pre.transport_attempts == 0

    checks = iter((False, True))
    calls = 0

    async def call(_prompt, _request):
        nonlocal calls
        calls += 1
        return observation(req)

    post = await run_semantic_transport(req, call=call, cancelled=lambda: next(checks))
    assert post.status == "cancelled"
    assert calls == post.transport_attempts == 1
    assert post.payload is None


@pytest.mark.asyncio
async def test_runtime_preserves_violation_counters_for_fail_closed_merge():
    req = request()
    result = await run_semantic_transport(
        req,
        call=lambda *_: _resolved(observation(
            req, model_rounds=2, tool_calls=1, transport_attempts=2,
            recursion_detected=True,
        )),
    )
    assert result.status == "ok"
    assert result.model_rounds == 2
    assert result.tool_calls == 1
    assert result.transport_attempts == 2
    assert result.recursion_detected is True


@pytest.mark.asyncio
async def test_public_chat_adapter_is_observed_once_with_no_tools():
    req = request()
    counts = {"chat": 0, "raw": 0, "verify": 0}

    async def current():
        counts["verify"] += 1

    async def verified_reply(reply):
        assert reply == "fake-reply"
        return response(req)

    async def chat(prompt, *, skill, session_id):
        counts["chat"] += 1
        assert prompt == build_semantic_prompt(req)
        assert skill is None
        context = SimpleNamespace(
            agent_id="ai-novel-writer",
            root_agent_id="ai-novel-writer",
            session_id=session_id,
            request=SimpleNamespace(
                agent_id="ai-novel-writer", session_id=session_id
            ),
        )
        middleware = create_managed_method_middleware(context, None)
        kwargs = {
            "messages": [],
            "tools": [{"type": "function", "function": {"name": "web"}}],
            "tool_choice": {"type": "function", "function": {"name": "web"}},
        }

        async def raw_model():
            counts["raw"] += 1
            assert kwargs["tools"] == []
            assert kwargs["tool_choice"] is None
            return "fake-reply"

        return await middleware.on_model_call(None, kwargs, raw_model)

    call = public_semantic_call(
        ctx=SimpleNamespace(chat=chat),
        session_id="semantic:s58-public",
        capabilities=PublicLoadCapabilities(True, True, True),
        verify_current=current,
        verify_reply=verified_reply,
    )
    result = await run_semantic_transport(req, call=call)
    assert result.status == "ok"
    assert result.model_rounds == result.transport_attempts == 1
    assert result.tool_calls == 0
    assert counts == {"chat": 1, "raw": 1, "verify": 2}


async def _resolved(value):
    return value
