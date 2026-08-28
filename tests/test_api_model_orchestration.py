import importlib
import hashlib
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
        role="assistant",
        content=[SimpleNamespace(type="output_text", text=text)],
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


def _selection_snapshot(novel_id, *, operation: str = "review"):
    selection_id = uuid4()
    selection_text = "她把湿透的车票攥在掌心。"
    digest = hashlib.sha256(selection_text.encode("utf-8")).hexdigest()
    return {
        "schema_version": 1,
        "selection_id": str(selection_id),
        "operation": operation,
        "custom_instruction": None,
        "target": {
            "novel_id": str(novel_id),
            "document_id": None,
            "entity_type": "setting",
            "entity_id": str(novel_id),
            "field_id": "settings.idea",
            "field_label": "创作思路",
            "persistence": "explicit-save",
            "context_revision": 3,
        },
        "base": {
            "field_value_sha256": digest,
            "persistence_version_kind": "entity",
            "persistence_version": 1,
            "start_utf16": 0,
            "end_utf16": len(selection_text.encode("utf-16-le")) // 2,
            "selection_text": selection_text,
            "selection_text_sha256": digest,
            "before": "雨声压住了站台广播。",
            "after": "远处的绿灯亮了。",
        },
    }


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


@pytest.mark.asyncio
async def test_selection_edit_uses_operation_skill_and_project_owned_diff(
    monkeypatch,
) -> None:
    api = _import_creative_api(monkeypatch)
    novel_id = uuid4()
    job_id = uuid4()
    snapshot = _selection_snapshot(novel_id, operation="review")
    chat_calls: list[dict[str, object]] = []
    completed: list[dict[str, object]] = []
    monkeypatch.setattr(
        api,
        "start_creative_generation",
        lambda *args, **kwargs: {
            "id": str(job_id),
            "kind": "selection_edit",
            "state": "running",
            "should_execute": True,
            "input_snapshot": snapshot,
        },
    )
    monkeypatch.setattr(api, "ensure_prompt_within_effective_limit", lambda *args: None)

    async def chat(prompt, **kwargs):
        chat_calls.append({"prompt": prompt, **kwargs})
        return _reply_with_usage(
            "provider-a",
            "model-a",
            text=(
                '{"replacement_text":"她把湿透的旧车票攥在掌心。",'
                '"short_summary":"补充物件质感。"}'
            ),
        )

    def complete(session, received_job_id, **kwargs):
        assert received_job_id == job_id
        completed.append(kwargs)
        return {"id": str(job_id), "state": "ready", **kwargs}

    monkeypatch.setattr(api, "complete_creative_generation", complete)
    request = api.StartCreativeGenerationRequest(
        scope_type="novel",
        scope_id=novel_id,
        kind="selection_edit",
        input_snapshot=snapshot,
        novel_id=novel_id,
    )

    result = await api.creative_generations_create(
        request,
        ctx=SimpleNamespace(chat=chat),
        configured_model=ModelAudit(
            provider_id="provider-a",
            model_id="model-a",
            source="effective-model-api",
        ),
        session=_FakeSession(),
    )

    assert result["state"] == "ready"
    assert chat_calls[0]["skill"] == "style-review"
    assert chat_calls[0]["session_id"] == f"novel-creative-generation:{job_id}"
    output = completed[0]["output_json"]
    assert output["schema_version"] == 2
    assert output["selection_id"] == snapshot["selection_id"]
    assert output["operation"] == "review"
    assert output["warnings"] == []
    assert output["replacement_character_count"] == len(output["replacement_text"])
    assert completed[0]["output_text"] == output["replacement_text"]
    assert all("segment_id" in item for item in output["diff_segments"])


@pytest.mark.asyncio
async def test_selection_edit_retries_one_ambiguous_model_reply_then_completes(
    monkeypatch,
) -> None:
    api = _import_creative_api(monkeypatch)
    novel_id = uuid4()
    job_id = uuid4()
    snapshot = _selection_snapshot(novel_id, operation="polish")
    chat_calls: list[dict[str, object]] = []
    completed: list[dict[str, object]] = []
    replies = iter(
        [
            (
                '{"replacement_text":"她攥紧车票。","short_summary":"候选一。"}\n'
                '{"replacement_text":"她收紧手指。","short_summary":"候选二。"}'
            ),
            (
                '{"replacement_text":"她把湿透的旧车票攥在掌心。",'
                '"short_summary":"补充物件质感。"}'
            ),
        ]
    )
    monkeypatch.setattr(
        api,
        "start_creative_generation",
        lambda *args, **kwargs: {
            "id": str(job_id),
            "kind": "selection_edit",
            "state": "running",
            "should_execute": True,
            "input_snapshot": snapshot,
        },
    )
    monkeypatch.setattr(api, "ensure_prompt_within_effective_limit", lambda *args: None)

    async def chat(prompt, **kwargs):
        chat_calls.append({"prompt": prompt, **kwargs})
        return _reply_with_usage("provider-a", "model-a", text=next(replies))

    def complete(session, received_job_id, **kwargs):
        assert received_job_id == job_id
        completed.append(kwargs)
        return {"id": str(job_id), "state": "ready", **kwargs}

    monkeypatch.setattr(api, "complete_creative_generation", complete)
    request = api.StartCreativeGenerationRequest(
        scope_type="novel",
        scope_id=novel_id,
        kind="selection_edit",
        input_snapshot=snapshot,
        novel_id=novel_id,
    )

    result = await api.creative_generations_create(
        request,
        ctx=SimpleNamespace(chat=chat),
        configured_model=ModelAudit(
            provider_id="provider-a",
            model_id="model-a",
            source="effective-model-api",
        ),
        session=_FakeSession(),
    )

    assert result["state"] == "ready"
    assert len(chat_calls) == 2
    assert chat_calls[0]["session_id"] == f"novel-creative-generation:{job_id}"
    assert chat_calls[1]["session_id"] == (
        f"novel-creative-generation:{job_id}:verification-retry-1"
    )
    assert "上一次响应未通过严格 JSON 验证" in str(chat_calls[1]["prompt"])
    assert completed[0]["output_text"] == "她把湿透的旧车票攥在掌心。"


@pytest.mark.asyncio
async def test_selection_edit_strict_model_failure_is_recorded_without_completion(
    monkeypatch,
) -> None:
    api = _import_creative_api(monkeypatch)
    novel_id = uuid4()
    job_id = uuid4()
    snapshot = _selection_snapshot(novel_id, operation="polish")
    fail_calls: list[dict[str, object]] = []
    complete_calls: list[object] = []
    monkeypatch.setattr(
        api,
        "start_creative_generation",
        lambda *args, **kwargs: {
            "id": str(job_id),
            "kind": "selection_edit",
            "state": "running",
            "should_execute": True,
            "input_snapshot": snapshot,
        },
    )
    monkeypatch.setattr(api, "ensure_prompt_within_effective_limit", lambda *args: None)
    monkeypatch.setattr(
        api,
        "complete_creative_generation",
        lambda *args, **kwargs: complete_calls.append((args, kwargs)),
    )

    def fail(session, received_job_id, **kwargs):
        assert received_job_id == job_id
        fail_calls.append(kwargs)
        return {"id": str(job_id), "state": "failed", **kwargs}

    monkeypatch.setattr(api, "fail_creative_generation", fail)

    async def chat(*args, **kwargs):
        return _reply_with_usage(
            "provider-a",
            "model-a",
            text=(
                '{"replacement_text":"她攥紧车票。","short_summary":"润色。",'
                '"diff_segments":[]}'
            ),
        )

    request = api.StartCreativeGenerationRequest(
        scope_type="novel",
        scope_id=novel_id,
        kind="selection_edit",
        input_snapshot=snapshot,
        novel_id=novel_id,
    )
    session = _FakeSession()

    with pytest.raises(HTTPException) as captured:
        await api.creative_generations_create(
            request,
            ctx=SimpleNamespace(chat=chat),
            configured_model=ModelAudit(
                provider_id="provider-a",
                model_id="model-a",
                source="effective-model-api",
            ),
            session=session,
        )

    assert captured.value.status_code == 502
    assert captured.value.detail["type"] == "model_verification_failed"
    assert complete_calls == []
    assert fail_calls[0]["actual_provider_id"] == "provider-a"
    assert fail_calls[0]["actual_model_id"] == "model-a"
    assert "只能包含" in str(fail_calls[0]["failure_message"])
