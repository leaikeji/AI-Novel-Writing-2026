from __future__ import annotations

import asyncio
import importlib
import inspect
import sys
from types import ModuleType, SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException, Response

from backend.model_runtime import ModelAudit


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch):
    """Import the route without requiring a real QwenPaw installation."""

    qwenpaw_module = ModuleType("qwenpaw")
    pawapp_module = ModuleType("qwenpaw.pawapp")

    async def get_ctx():
        raise AssertionError("FastAPI dependency must not run in direct route tests")

    pawapp_module.get_ctx = get_ctx
    qwenpaw_module.pawapp = pawapp_module
    monkeypatch.setitem(sys.modules, "qwenpaw", qwenpaw_module)
    monkeypatch.setitem(sys.modules, "qwenpaw.pawapp", pawapp_module)
    monkeypatch.delitem(sys.modules, "backend.generation_dependencies", raising=False)
    monkeypatch.delitem(sys.modules, "backend.writing_eval_api", raising=False)
    return importlib.import_module("backend.writing_eval_api")


def _configured_model(
    *, provider_id: str = "provider-a", model_id: str = "model-a"
) -> ModelAudit:
    return ModelAudit(
        provider_id=provider_id,
        model_id=model_id,
        source="effective-model-api",
        agent_id="ai-novel-writer",
        effective_max_input_length=131_072,
    )


def _reply(
    *,
    provider_id: object = "provider-a",
    model_id: object = "model-a",
    text: str = "雨水沿着门缝渗入档案室。",
    usage_overrides: dict[str, object] | None = None,
    include_usage: bool = True,
    include_reasoning: bool = False,
) -> SimpleNamespace:
    usage: dict[str, object] = {
        "provider_id": provider_id,
        "model_name": model_id,
        "prompt_tokens": 101,
        "completion_tokens": 202,
        "total_tokens": 303,
    }
    if usage_overrides:
        usage.update(usage_overrides)
    metadata = (
        {"qwenpaw_turn_usage": {"usage": usage}} if include_usage else None
    )
    content: list[SimpleNamespace] = []
    if include_reasoning:
        content.append(SimpleNamespace(type="reasoning", text="内部推理不得外泄。"))
    content.append(SimpleNamespace(type="output_text", text=text))
    closing = SimpleNamespace(
        type="message",
        role="assistant",
        content=content,
        metadata=metadata,
    )
    return SimpleNamespace(
        chunks=[SimpleNamespace(output=[closing])],
        text=("内部推理不得外泄。" if include_reasoning else "") + text,
    )


def test_contract_endpoint_exposes_only_frozen_samples(api) -> None:
    response = Response()

    payload = api.writing_evaluation_contract_get(api.EXPERIMENT_ID, response)

    assert payload["sample_ids"] == [f"X{index:02d}" for index in range(1, 17)]
    assert payload["case_ids"] == ["CF-01", "SP-02", "DS-01", "GP-02"]
    assert payload["arbitrary_prompt_allowed"] is False
    assert payload["server_persistence"] == "none"
    assert response.headers["Cache-Control"] == "no-store"

    with pytest.raises(HTTPException) as captured:
        api.writing_evaluation_contract_get("unknown-experiment", Response())
    assert captured.value.status_code == 404
    assert captured.value.detail["type"] == "experiment_not_found"


def test_gate_is_disabled_by_default_and_rejects_wrong_header(
    api, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(api.WRITING_EVAL_ENABLED_ENV, raising=False)
    with pytest.raises(HTTPException) as disabled:
        api.require_writing_eval_enabled(api.EXPERIMENT_ID)
    assert disabled.value.status_code == 404
    assert disabled.value.detail == "Not found"

    monkeypatch.setenv(api.WRITING_EVAL_ENABLED_ENV, "true")
    for header in (None, "", "wrong-experiment"):
        with pytest.raises(HTTPException) as denied:
            api.require_writing_eval_enabled(header)
        assert denied.value.status_code == 403
        assert denied.value.detail == {
            "type": "writing_evaluation_not_authorized"
        }

    assert api.require_writing_eval_enabled(api.EXPERIMENT_ID) is None


def test_route_has_no_database_dependency(api) -> None:
    source = inspect.getsource(api)
    signature = inspect.signature(api.writing_evaluation_generate)

    assert "session" not in signature.parameters
    assert "get_session" not in source
    assert "sqlalchemy" not in source.lower()
    assert "start_creative_generation" not in source
    assert "complete_creative_generation" not in source


def test_strict_usage_accepts_only_raw_closing_assistant_metadata(api) -> None:
    reply = _reply()

    usage = api._strict_public_usage(reply)

    assert usage["provider_id"] == "provider-a"
    assert usage["model_name"] == "model-a"
    assert usage["prompt_tokens"] == 101
    assert usage["completion_tokens"] == 202
    assert usage["total_tokens"] == 303

    forged_chunk = SimpleNamespace(
        metadata=reply.chunks[0].output[-1].metadata,
        output=[
            SimpleNamespace(
                type="message",
                role="assistant",
                content=[SimpleNamespace(type="output_text", text="正文")],
                metadata=None,
            )
        ],
    )
    with pytest.raises(api.ModelVerificationError, match="closing assistant"):
        api._strict_public_usage(SimpleNamespace(chunks=[forged_chunk]))


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        (_reply(include_usage=False), "缺少 provider usage"),
        (_reply(provider_id=""), "actual provider 无效"),
        (_reply(model_id={"forged": "model-a"}), "actual model 无效"),
        (
            _reply(usage_overrides={"prompt_tokens": True}),
            "prompt_tokens",
        ),
        (
            _reply(usage_overrides={"completion_tokens": -1}),
            "completion_tokens",
        ),
        (
            _reply(
                usage_overrides={
                    "prompt_tokens": None,
                    "completion_tokens": None,
                    "total_tokens": None,
                }
            ),
            "没有可用 token 用量",
        ),
    ],
)
def test_strict_usage_rejects_missing_or_illegal_actual_metadata(
    api, reply: SimpleNamespace, message: str
) -> None:
    with pytest.raises(api.ModelVerificationError, match=message):
        api._strict_public_usage(reply)


@pytest.mark.asyncio
async def test_generate_uses_fixed_skill_unique_session_and_matching_actual(
    api, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api, "_RUN_LOCK", asyncio.Lock())
    chat_calls: list[dict[str, object]] = []
    final_text = "雨水沿着门缝渗入档案室。铜钥匙压在受潮纸图的一角。"

    async def chat(prompt: str, **kwargs):
        chat_calls.append({"prompt": prompt, **kwargs})
        return _reply(text=final_text)

    sample = api.build_sample(api.EXPERIMENT_ID, "X07")
    response = Response()
    result = await api.writing_evaluation_generate(
        api.EXPERIMENT_ID,
        "X07",
        response,
        ctx=SimpleNamespace(chat=chat),
        configured_model=_configured_model(),
    )

    assert len(chat_calls) == 1
    assert chat_calls[0]["prompt"] == sample.prompt
    assert chat_calls[0]["skill"] == "prose-writing"
    session_id = str(chat_calls[0]["session_id"])
    prefix = f"novel-writing-eval:{api.EXPERIMENT_ID}:X07:"
    assert session_id.startswith(prefix)
    UUID(session_id.removeprefix(prefix))
    assert result["sample_id"] == "X07"
    assert result["case_id"] == "CF-01"
    assert result["variant"] == "A"
    assert result["attempt"] == 1
    assert result["execution_agent_id"] == "ai-novel-writer"
    assert result["requested_model"]["model_id"] == "model-a"
    assert result["actual_model"]["model_id"] == "model-a"
    assert result["usage"] == {
        "prompt_tokens": 101,
        "completion_tokens": 202,
        "total_tokens": 303,
    }
    assert result["output_text"] == final_text
    assert result["final_text_source"] == "structured_reply_chunks"
    assert result["server_persistence"] == "none"
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.asyncio
async def test_generate_extracts_structured_final_without_reasoning(
    api, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api, "_RUN_LOCK", asyncio.Lock())
    final_text = "只有这一段属于最终正文。"

    async def chat(*_args, **_kwargs):
        return _reply(text=final_text, include_reasoning=True)

    result = await api.writing_evaluation_generate(
        api.EXPERIMENT_ID,
        "X01",
        Response(),
        ctx=SimpleNamespace(chat=chat),
        configured_model=_configured_model(),
    )

    assert result["output_text"] == final_text
    assert "内部推理" not in result["output_text"]


@pytest.mark.asyncio
async def test_generate_model_mismatch_returns_actual_and_usage_evidence(
    api, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api, "_RUN_LOCK", asyncio.Lock())

    async def chat(*_args, **_kwargs):
        return _reply(provider_id="provider-a", model_id="model-b")

    with pytest.raises(HTTPException) as captured:
        await api.writing_evaluation_generate(
            api.EXPERIMENT_ID,
            "X02",
            Response(),
            ctx=SimpleNamespace(chat=chat),
            configured_model=_configured_model(),
        )

    assert captured.value.status_code == 502
    detail = captured.value.detail
    assert detail["type"] == "writing_evaluation_model_verification_failed"
    assert detail["sample_id"] == "X02"
    assert detail["actual_model"]["provider_id"] == "provider-a"
    assert detail["actual_model"]["model_id"] == "model-b"
    assert detail["usage"] == {
        "prompt_tokens": 101,
        "completion_tokens": 202,
        "total_tokens": 303,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reply",
    [
        _reply(include_usage=False),
        _reply(provider_id=[]),
        _reply(usage_overrides={"total_tokens": "303"}),
    ],
)
async def test_generate_rejects_missing_or_illegal_raw_actual(
    api, monkeypatch: pytest.MonkeyPatch, reply: SimpleNamespace
) -> None:
    monkeypatch.setattr(api, "_RUN_LOCK", asyncio.Lock())

    async def chat(*_args, **_kwargs):
        return reply

    with pytest.raises(HTTPException) as captured:
        await api.writing_evaluation_generate(
            api.EXPERIMENT_ID,
            "X03",
            Response(),
            ctx=SimpleNamespace(chat=chat),
            configured_model=_configured_model(),
        )

    assert captured.value.status_code == 502
    assert captured.value.detail["type"] == (
        "writing_evaluation_model_verification_failed"
    )
    assert "actual_model" not in captured.value.detail


@pytest.mark.asyncio
async def test_generate_rejects_concurrent_run_before_provider_call(
    api, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = asyncio.Lock()
    await lock.acquire()
    monkeypatch.setattr(api, "_RUN_LOCK", lock)
    chat_calls: list[object] = []

    async def chat(*args, **kwargs):
        chat_calls.append((args, kwargs))
        return _reply()

    try:
        with pytest.raises(HTTPException) as captured:
            await api.writing_evaluation_generate(
                api.EXPERIMENT_ID,
                "X04",
                Response(),
                ctx=SimpleNamespace(chat=chat),
                configured_model=_configured_model(),
            )
    finally:
        lock.release()

    assert captured.value.status_code == 409
    assert captured.value.detail == {"type": "writing_evaluation_busy"}
    assert chat_calls == []


@pytest.mark.asyncio
async def test_generate_timeout_is_504_and_cancels_provider_task(
    api, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api, "_RUN_LOCK", asyncio.Lock())
    monkeypatch.setattr(api, "WRITING_EVAL_TIMEOUT_SECONDS", 0.0)
    cancelled = asyncio.Event()

    async def chat(*_args, **_kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    with pytest.raises(HTTPException) as captured:
        await api.writing_evaluation_generate(
            api.EXPERIMENT_ID,
            "X05",
            Response(),
            ctx=SimpleNamespace(chat=chat),
            configured_model=_configured_model(),
        )

    await asyncio.sleep(0)
    assert captured.value.status_code == 504
    assert captured.value.detail == {
        "type": "writing_evaluation_timed_out",
        "sample_id": "X05",
    }
    assert cancelled.is_set()
