import importlib
import sys
from types import ModuleType, SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.model_runtime import ModelAudit


def _import_creative_api(monkeypatch):
    qwenpaw_module = ModuleType("qwenpaw")
    pawapp_module = ModuleType("qwenpaw.pawapp")

    async def get_ctx():
        raise AssertionError("dependency should not execute in direct endpoint tests")

    pawapp_module.get_ctx = get_ctx
    qwenpaw_module.pawapp = pawapp_module
    monkeypatch.setitem(sys.modules, "qwenpaw", qwenpaw_module)
    monkeypatch.setitem(sys.modules, "qwenpaw.pawapp", pawapp_module)
    monkeypatch.delitem(sys.modules, "backend.generation_dependencies", raising=False)
    monkeypatch.delitem(sys.modules, "backend.creative_api", raising=False)
    return importlib.import_module("backend.creative_api")


def _reply_with_usage(provider_id: str, model_id: str, *, text: str):
    message = SimpleNamespace(
        metadata={
            "qwenpaw_turn_usage": {
                "usage": {
                    "provider_id": provider_id,
                    "model_name": model_id,
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                }
            }
        }
    )
    return SimpleNamespace(
        chunks=[SimpleNamespace(output=[message])],
        text=text,
    )


class _FakeSession:
    def __init__(self) -> None:
        self.rollback_count = 0

    def rollback(self) -> None:
        self.rollback_count += 1


@pytest.mark.asyncio
async def test_model_mismatch_precedes_malformed_content_and_fail_keeps_actual(
    monkeypatch,
) -> None:
    api = _import_creative_api(monkeypatch)
    job_id = uuid4()
    fail_calls: list[dict[str, object]] = []
    parse_calls: list[str] = []

    monkeypatch.setattr(
        api,
        "start_creative_generation",
        lambda *args, **kwargs: {
            "id": str(job_id),
            "kind": "novel_template",
            "state": "running",
            "should_execute": True,
            "input_snapshot": {},
        },
    )
    monkeypatch.setattr(api, "build_creative_generation_prompt", lambda job: "prompt")
    monkeypatch.setattr(api, "ensure_prompt_within_effective_limit", lambda *args: None)

    def parse_model_json(text: str):
        parse_calls.append(text)
        raise AssertionError("malformed content must not be parsed after mismatch")

    monkeypatch.setattr(api, "parse_model_json", parse_model_json)

    def fail_creative_generation(session, received_job_id, **kwargs):
        assert received_job_id == job_id
        fail_calls.append(kwargs)
        return {
            "id": str(job_id),
            "state": "failed",
            "actual_provider_id": kwargs.get("actual_provider_id"),
            "actual_model_id": kwargs.get("actual_model_id"),
        }

    monkeypatch.setattr(api, "fail_creative_generation", fail_creative_generation)
    ctx = SimpleNamespace(
        chat=lambda *args, **kwargs: None,
    )

    async def chat(*args, **kwargs):
        return _reply_with_usage(
            "actual-provider",
            "actual-model",
            text="{malformed",
        )

    ctx.chat = chat
    configured = ModelAudit(
        provider_id="expected-provider",
        model_id="expected-model",
        source="effective-model-api",
    )
    request = api.StartCreativeGenerationRequest(
        scope_type="novel_creation",
        scope_id=uuid4(),
        kind="novel_template",
        input_snapshot={},
    )
    session = _FakeSession()

    with pytest.raises(HTTPException) as captured:
        await api.creative_generations_create(
            request,
            ctx=ctx,
            configured_model=configured,
            session=session,
        )

    assert captured.value.status_code == 502
    assert captured.value.detail["type"] == "model_verification_failed"
    assert parse_calls == []
    assert fail_calls[0]["actual_provider_id"] == "actual-provider"
    assert fail_calls[0]["actual_model_id"] == "actual-model"
    assert "与调用前活动模型不一致" in str(fail_calls[0]["failure_message"])


@pytest.mark.asyncio
async def test_relationship_non_owner_returns_409_without_failing_shared_job(
    monkeypatch,
) -> None:
    api = _import_creative_api(monkeypatch)
    job_id = uuid4()
    fail_calls: list[object] = []
    chat_calls: list[object] = []
    monkeypatch.setattr(api, "build_relationship_graph_snapshot", lambda *args: {})
    monkeypatch.setattr(
        api,
        "start_creative_generation",
        lambda *args, **kwargs: {
            "id": str(job_id),
            "kind": "relationship_graph",
            "state": "running",
            "should_execute": False,
        },
    )
    monkeypatch.setattr(
        api,
        "fail_creative_generation",
        lambda *args, **kwargs: fail_calls.append((args, kwargs)),
    )

    async def chat(*args, **kwargs):
        chat_calls.append((args, kwargs))

    configured = ModelAudit(
        provider_id="provider",
        model_id="model",
        source="effective-model-api",
    )
    session = _FakeSession()

    with pytest.raises(HTTPException) as captured:
        await api.relationships_auto_sync(
            uuid4(),
            api.SyncRelationshipsRequest(force_new=False),
            ctx=SimpleNamespace(chat=chat),
            configured_model=configured,
            session=session,
        )

    assert captured.value.status_code == 409
    assert captured.value.detail["type"] == "relationship_generation_in_progress"
    assert fail_calls == []
    assert chat_calls == []
