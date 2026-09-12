"""No-network semantic runtime prompt, strict parser and one-call tests."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.model_runtime import ModelVerificationError
from backend.writing_skills.contracts import MethodPreferences
from backend.writing_skills.resolver import resolve_methods
from backend.writing_skills.semantic import SemanticCandidateV1, SemanticRouteRequestV2
from backend.writing_skills.semantic_runtime import (
    SEMANTIC_ROUTING_TIMEOUT_SECONDS,
    SemanticAdapterObservationV1,
    build_semantic_prompt,
    classify_semantic_response_shape,
    parse_semantic_response,
    public_semantic_call,
    run_semantic_transport,
)
from backend.writing_skills import semantic_runtime
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


def test_semantic_routing_default_timeout_is_ninety_seconds():
    assert SEMANTIC_ROUTING_TIMEOUT_SECONDS == 90.0


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
    assert "semantic_criteria是选入所需的正向适用条件" in prompt
    assert "negative_examples是排除边界" in prompt
    assert "作者对当前任务的明确禁用、停用或不适用要求优先" in prompt
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
    "解释如下：{}",
    "```json\n{}\n```\n附加解释",
    "```json\n```json\n{}\n```\n```",
    '{"schema_version":"semantic-route-response/1","schema_version":"semantic-route-response/1","decisions":[]}',
    '{"schema_version":"semantic-route-response/1","decisions":[],"extra":true}',
])
def test_parser_rejects_explanations_multiple_fences_duplicates_and_extra_fields(text):
    with pytest.raises(ValueError):
        parse_semantic_response(text)


def test_parser_accepts_one_json_fence_without_relaxing_response_schema():
    text = """```json
{"schema_version":"semantic-route-response/1","decisions":[{"skill_id":"golden-finger-writing","decision":"select","evidence_refs":["source.0"]}]}
```"""
    parsed = parse_semantic_response(text)
    assert parsed["schema_version"] == "semantic-route-response/1"
    assert parsed["decisions"][0]["skill_id"] == "golden-finger-writing"


def test_parser_accepts_one_strict_embedded_route_object_only():
    payload = (
        '{"schema_version":"semantic-route-response/1","decisions":['
        '{"skill_id":"golden-finger-writing","decision":"select",'
        '"evidence_refs":["source.0"]}]}'
    )
    wrapped = f"路由结果如下：\n```json\n{payload}\n```\n以上。"
    assert classify_semantic_response_shape(wrapped) == (
        "single_embedded_object_candidate"
    )
    parsed = parse_semantic_response(wrapped)
    assert parsed["decisions"][0]["decision"] == "select"


def test_parser_rejects_zero_multiple_or_unbounded_embedded_route_objects():
    payload = (
        '{"schema_version":"semantic-route-response/1","decisions":['
        '{"skill_id":"golden-finger-writing","decision":"reject",'
        '"evidence_refs":["source.0"]}]}'
    )
    for text in (
        "只有解释，没有对象",
        f"{payload}\n重复：{payload}",
        "{" * 257 + payload,
    ):
        with pytest.raises(ValueError):
            parse_semantic_response(text)


@pytest.mark.parametrize("envelope", [
    "{payload}",
    "```\n{payload}\n```",
    "```JSON\r\n{payload}\r\n```",
])
def test_parser_accepts_bare_no_language_fence_and_crlf(envelope):
    payload = (
        '{"schema_version":"semantic-route-response/1","decisions":['
        '{"skill_id":"golden-finger-writing","decision":"select",'
        '"evidence_refs":["source.0"]}]}'
    )
    parsed = parse_semantic_response(envelope.format(payload=payload))
    assert parsed["schema_version"] == "semantic-route-response/1"
    assert parsed["decisions"][0]["skill_id"] == "golden-finger-writing"


@pytest.mark.parametrize("text", [
    "{}\n补充解释",
    "{}\n{}",
    "```json\n{}\n```\n```json\n{}\n```",
    '{"schema_version":"semantic-route-response/1","decisions":[{"skill_id":"golden-finger-writing","skill_id":"suspense-writing","decision":"select","evidence_refs":["source.0"]}]}',
    '{"schema_version":"semantic-route-response/1","decisions":[{"skill_id":"golden-finger-writing","decision":"select","evidence_refs":["source.0"],"extra":true}]}',
])
def test_parser_rejects_additional_envelope_and_nested_schema_violations(text):
    with pytest.raises(ValueError):
        parse_semantic_response(text)


def test_parser_rejects_response_over_character_limit_before_schema_validation():
    over_limit = json.dumps({
        "schema_version": "semantic-route-response/1",
        "decisions": [{
            "skill_id": "golden-finger-writing",
            "decision": "select",
            "evidence_refs": ["x" * 50_000],
        }],
    })
    assert len(over_limit) > 50_000
    with pytest.raises(ValueError, match="semantic_response_not_bare_object"):
        parse_semantic_response(over_limit)


def test_parser_counts_outer_whitespace_toward_response_limit():
    valid = (
        '{"schema_version":"semantic-route-response/1","decisions":['
        '{"skill_id":"golden-finger-writing","decision":"select",'
        '"evidence_refs":["source.0"]}]}'
    )
    over_limit = (" " * 50_000) + valid
    assert classify_semantic_response_shape(over_limit) == "over_limit"
    with pytest.raises(ValueError, match="semantic_response_not_bare_object"):
        parse_semantic_response(over_limit)


@pytest.mark.parametrize(("text", "expected"), [
    ("", "empty"),
    (" \n\t", "empty"),
    ("{}", "bare_object_candidate"),
    ("{invalid}", "bare_object_candidate"),
    ("```json\n{}\n```", "single_json_fence_candidate"),
    ("```JSON\r\n{}\r\n```", "single_json_fence_candidate"),
    ("解释如下：{}", "other"),
    ("```json\n{}\n```\n附加说明", "other"),
    ("```json\n```json\n{}\n```\n```", "other"),
    ("x" * 50_001, "over_limit"),
])
def test_response_shape_is_bounded_and_does_not_relax_parser(text, expected):
    assert classify_semantic_response_shape(text) == expected


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


@pytest.mark.asyncio
async def test_public_chat_adapter_has_a_hard_deadline_and_never_retries(monkeypatch):
    req = request()
    counts = {"chat": 0, "raw": 0}
    monkeypatch.setattr(semantic_runtime, "SEMANTIC_ROUTING_TIMEOUT_SECONDS", 0.01)

    async def current():
        return None

    async def chat(_prompt, *, skill, session_id):
        counts["chat"] += 1
        assert skill is None
        context = SimpleNamespace(
            agent_id="ai-novel-writer", root_agent_id="ai-novel-writer",
            session_id=session_id,
            request=SimpleNamespace(agent_id="ai-novel-writer", session_id=session_id),
        )
        middleware = create_managed_method_middleware(context, None)
        assert middleware is not None
        kwargs = {"messages": [], "tools": []}

        async def raw_model():
            counts["raw"] += 1
            await asyncio.Event().wait()

        return await middleware.on_model_call(None, kwargs, raw_model)

    call = public_semantic_call(
        ctx=SimpleNamespace(chat=chat),
        session_id="semantic:s70-timeout",
        capabilities=PublicLoadCapabilities(True, True, True),
        verify_current=current,
        verify_reply=lambda _: pytest.fail("timed out reply must not be verified"),
    )
    captured = []

    async def inspected(prompt, observed_request):
        result = await call(prompt, observed_request)
        captured.append(result)
        return result

    result = await run_semantic_transport(req, call=inspected)
    assert result.status == "unknown"
    assert result.model_rounds == result.transport_attempts == 1
    assert result.tool_calls == 0
    assert counts == {"chat": 1, "raw": 1}
    assert captured[0].failure_stage == "chat"
    assert captured[0].failure_code == "chat_timeout_after_observation"
    assert captured[0].failure_type == "ChapterGenerationTimeoutError"
    assert captured[0].duration_ms is not None


@pytest.mark.asyncio
async def test_observed_public_chat_cancellation_becomes_unknown_without_retry():
    req = request()
    counts = {"chat": 0, "raw": 0}

    async def current():
        return None

    async def chat(_prompt, *, skill, session_id):
        counts["chat"] += 1
        assert skill is None
        context = SimpleNamespace(
            agent_id="ai-novel-writer", root_agent_id="ai-novel-writer",
            session_id=session_id,
            request=SimpleNamespace(agent_id="ai-novel-writer", session_id=session_id),
        )
        middleware = create_managed_method_middleware(context, None)
        assert middleware is not None

        async def raw_model():
            counts["raw"] += 1
            raise asyncio.CancelledError

        return await middleware.on_model_call(
            None, {"messages": [], "tools": []}, raw_model,
        )

    call = public_semantic_call(
        ctx=SimpleNamespace(chat=chat),
        session_id="semantic:s70-cancel",
        capabilities=PublicLoadCapabilities(True, True, True),
        verify_current=current,
        verify_reply=lambda _: pytest.fail("cancelled reply must not be verified"),
    )
    captured = []

    async def inspected(prompt, observed_request):
        result = await call(prompt, observed_request)
        captured.append(result)
        return result

    result = await run_semantic_transport(req, call=inspected)
    assert result.status == "unknown"
    assert result.model_rounds == result.transport_attempts == 1
    assert counts == {"chat": 1, "raw": 1}
    assert captured[0].failure_stage == "chat"
    assert captured[0].failure_code == "chat_cancelled_after_observation"
    assert captured[0].failure_type == "CancelledError"


@pytest.mark.asyncio
async def test_public_chat_cancellation_before_model_is_safe_and_records_zero_rounds():
    req = request()
    counts = {"chat": 0}

    async def current():
        return None

    async def chat(_prompt, *, skill, session_id):
        counts["chat"] += 1
        assert skill is None
        assert session_id == "semantic:s70-pre-model-cancel"
        raise asyncio.CancelledError

    call = public_semantic_call(
        ctx=SimpleNamespace(chat=chat),
        session_id="semantic:s70-pre-model-cancel",
        capabilities=PublicLoadCapabilities(True, True, True),
        verify_current=current,
        verify_reply=lambda _: pytest.fail("cancelled reply must not be verified"),
    )
    captured = []

    async def inspected(prompt, observed_request):
        result = await call(prompt, observed_request)
        captured.append(result)
        return result

    result = await run_semantic_transport(req, call=inspected)
    assert result.status == "cancelled"
    assert result.model_rounds == result.tool_calls == 0
    assert result.transport_attempts == 1
    assert counts == {"chat": 1}
    assert captured[0].failure_stage == "chat"
    assert captured[0].failure_code == "chat_cancelled_before_observation"


def test_semantic_diagnostic_contract_is_bounded_and_success_cannot_claim_failure():
    with pytest.raises(ValidationError, match="cannot report failure"):
        SemanticAdapterObservationV1(
            status="ok", text="{}", model_rounds=1, tool_calls=0,
            transport_attempts=1, failure_stage="chat",
            failure_code="chat_error_after_observation",
        )
    with pytest.raises(ValidationError):
        SemanticAdapterObservationV1(
            status="unknown", text=None, model_rounds=1, tool_calls=0,
            transport_attempts=1, failure_stage="chat",
            failure_code="chat_error_after_observation",
            failure_type="contains unsafe spaces",
        )
    with pytest.raises(ValidationError, match="requires a failure stage"):
        SemanticAdapterObservationV1(
            status="unknown", text=None, model_rounds=1, tool_calls=0,
            transport_attempts=1, failure_type="RuntimeError",
        )


@pytest.mark.asyncio
async def test_public_chat_adapter_distinguishes_post_call_failure_stages():
    req = request()

    async def exercise(*, current, verified_reply):
        async def chat(_prompt, *, skill, session_id):
            assert skill is None
            context = SimpleNamespace(
                agent_id="ai-novel-writer",
                root_agent_id="ai-novel-writer",
                session_id=session_id,
                request=SimpleNamespace(
                    agent_id="ai-novel-writer", session_id=session_id,
                ),
            )
            middleware = create_managed_method_middleware(context, None)
            return await middleware.on_model_call(
                None, {"messages": [], "tools": []}, lambda: _resolved("reply"),
            )

        call = public_semantic_call(
            ctx=SimpleNamespace(chat=chat),
            session_id="semantic:p70-diagnostic",
            capabilities=PublicLoadCapabilities(True, True, True),
            verify_current=current,
            verify_reply=verified_reply,
        )
        return await call(build_semantic_prompt(req), req)

    checks = 0

    async def postflight_fails_on_second_check():
        nonlocal checks
        checks += 1
        if checks == 2:
            raise RuntimeError("must not be persisted")

    current_failure = await exercise(
        current=postflight_fails_on_second_check,
        verified_reply=lambda _: pytest.fail("reply verification must not run"),
    )
    assert current_failure.status == "unknown"
    assert current_failure.failure_stage == "current_model_check"
    assert current_failure.failure_code == "current_model_check_failed"
    assert current_failure.failure_type == "RuntimeError"

    class EvidenceRejected(RuntimeError):
        def __init__(self):
            self.evidence = SimpleNamespace(
                rejection_reason=SimpleNamespace(value="public_usage_malformed")
            )

    async def evidence_rejected(_reply):
        raise EvidenceRejected()

    evidence_failure = await exercise(
        current=lambda: _resolved(None), verified_reply=evidence_rejected,
    )
    assert evidence_failure.status == "unknown"
    assert evidence_failure.failure_stage == "reply_verification"
    assert evidence_failure.failure_code == "reply_evidence_public_usage_malformed"
    assert evidence_failure.failure_type == "EvidenceRejected"

    async def final_text_missing(_reply):
        raise ModelVerificationError("must not be persisted")

    text_failure = await exercise(
        current=lambda: _resolved(None), verified_reply=final_text_missing,
    )
    assert text_failure.failure_stage == "reply_verification"
    assert text_failure.failure_code == "final_text_unavailable"
    assert text_failure.failure_type == "ModelVerificationError"


@pytest.mark.asyncio
async def test_public_chat_adapter_distinguishes_chat_and_middleware_failures():
    req = request()

    async def current():
        return None

    async def raw_failure_chat(_prompt, *, skill, session_id):
        context = SimpleNamespace(
            agent_id="ai-novel-writer", root_agent_id="ai-novel-writer",
            session_id=session_id,
            request=SimpleNamespace(agent_id="ai-novel-writer", session_id=session_id),
        )
        middleware = create_managed_method_middleware(context, None)

        async def raw_model():
            raise RuntimeError("must not be persisted")

        return await middleware.on_model_call(
            None, {"messages": [], "tools": []}, raw_model,
        )

    failed_chat = public_semantic_call(
        ctx=SimpleNamespace(chat=raw_failure_chat),
        session_id="semantic:p70-chat-failure",
        capabilities=PublicLoadCapabilities(True, True, True),
        verify_current=current,
        verify_reply=lambda _: pytest.fail("failed chat must not be verified"),
    )
    chat_result = await failed_chat(build_semantic_prompt(req), req)
    assert chat_result.status == "unknown"
    assert chat_result.failure_stage == "chat"
    assert chat_result.failure_code == "chat_error_after_observation"
    assert chat_result.failure_type == "RuntimeError"

    async def bypassed_middleware(_prompt, *, skill, session_id):
        return "unobserved reply"

    invalid_middleware = public_semantic_call(
        ctx=SimpleNamespace(chat=bypassed_middleware),
        session_id="semantic:p70-middleware-failure",
        capabilities=PublicLoadCapabilities(True, True, True),
        verify_current=current,
        verify_reply=lambda _: pytest.fail("unobserved reply must not be verified"),
    )
    middleware_result = await invalid_middleware(build_semantic_prompt(req), req)
    assert middleware_result.status == "failed"
    assert middleware_result.failure_stage == "middleware"
    assert middleware_result.failure_code == "middleware_observation_invalid"
    assert middleware_result.failure_type is None


async def _resolved(value):
    return value
