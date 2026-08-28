from __future__ import annotations

import importlib
import sys
from types import ModuleType, SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.model_runtime import ModelAudit


def _import_creative_api(monkeypatch: pytest.MonkeyPatch):
    """Import the PawApp router without loading a real QwenPaw runtime."""

    qwenpaw_module = ModuleType("qwenpaw")
    pawapp_module = ModuleType("qwenpaw.pawapp")

    async def get_ctx():
        raise AssertionError("the real PawApp context must not run in API tests")

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
                    "prompt_tokens": 12,
                    "completion_tokens": 34,
                    "total_tokens": 46,
                }
            }
        },
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


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch):
    return _import_creative_api(monkeypatch)


@pytest.fixture
def http(api):
    session = _FakeSession()

    async def unexpected_chat(*args, **kwargs):
        raise AssertionError("model chat was not configured for this test")

    ctx = SimpleNamespace(chat=unexpected_chat)
    configured_model = ModelAudit(
        provider_id="provider-a",
        model_id="model-a",
        source="effective-model-api",
        effective_max_input_length=32_768,
    )
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_session] = lambda: session
    app.dependency_overrides[api.get_novel_generation_ctx] = lambda: ctx
    app.dependency_overrides[api.get_novel_effective_model] = lambda: configured_model
    with TestClient(app, raise_server_exceptions=False) as client:
        yield SimpleNamespace(
            client=client,
            session=session,
            ctx=ctx,
            configured_model=configured_model,
        )


def _generation_setup(monkeypatch, api, http, *, final_text: str, actual_model="model-a"):
    novel_id = uuid4()
    job_id = uuid4()
    snapshot = {
        "schema_version": "character-profile-completion-v1",
        "novel": {"id": str(novel_id), "title": "刑侦1988"},
        "characters": [
            {
                "id": str(uuid4()),
                "base_version": 2,
                "name": "江述",
                "details": {"core_flaw": "过度相信程序正义"},
            }
        ],
    }
    start_calls: list[dict[str, object]] = []
    complete_calls: list[dict[str, object]] = []
    fail_calls: list[dict[str, object]] = []
    chat_calls: list[dict[str, object]] = []
    status_calls: list[UUID] = []

    def status(_session, received_novel_id):
        status_calls.append(received_novel_id)
        if len(status_calls) == 1:
            return {
                "eligible": True,
                "state": "never",
                "stale": False,
                "source_summary": {},
            }
        return {
            "eligible": True,
            "state": "ready",
            "stale": False,
            "source_summary": {},
            "job": {"id": str(job_id), "state": "ready"},
        }

    def start(_session, **kwargs):
        start_calls.append(kwargs)
        return {
            "id": str(job_id),
            "kind": "character_profile_completion",
            "state": "running",
            "should_execute": True,
            "input_snapshot": snapshot,
        }

    async def chat(prompt, **kwargs):
        chat_calls.append({"prompt": prompt, **kwargs})
        return _reply_with_usage(
            "provider-a",
            actual_model,
            text=final_text,
        )

    def complete(_session, received_job_id, **kwargs):
        assert received_job_id == job_id
        complete_calls.append(kwargs)
        return {"id": str(job_id), "state": "ready", **kwargs}

    def fail(_session, received_job_id, **kwargs):
        assert received_job_id == job_id
        fail_calls.append(kwargs)
        return {"id": str(job_id), "state": "failed", **kwargs}

    monkeypatch.setattr(api, "get_character_profile_completion_status", status)
    monkeypatch.setattr(
        api,
        "build_character_profile_completion_snapshot",
        lambda _session, received_novel_id: snapshot,
    )
    monkeypatch.setattr(api, "start_creative_generation", start)
    monkeypatch.setattr(api, "build_creative_generation_prompt", lambda job: "profile-prompt")
    monkeypatch.setattr(api, "complete_creative_generation", complete)
    monkeypatch.setattr(api, "fail_creative_generation", fail)
    http.ctx.chat = chat
    return SimpleNamespace(
        novel_id=novel_id,
        job_id=job_id,
        snapshot=snapshot,
        start_calls=start_calls,
        complete_calls=complete_calls,
        fail_calls=fail_calls,
        chat_calls=chat_calls,
        status_calls=status_calls,
    )


def test_status_forwards_novel_scope_and_returns_service_payload(
    monkeypatch: pytest.MonkeyPatch,
    api,
    http,
) -> None:
    novel_id = uuid4()
    expected = {
        "eligible": True,
        "state": "ready",
        "stale": False,
        "source_summary": {"character_count": 6},
        "candidates": [],
        "can_restore": False,
    }
    calls: list[tuple[object, UUID]] = []

    def status(session, received_novel_id):
        calls.append((session, received_novel_id))
        return expected

    monkeypatch.setattr(api, "get_character_profile_completion_status", status)

    response = http.client.get(
        f"/novels/{novel_id}/character-profile-completion/status"
    )

    assert response.status_code == 200
    assert response.json() == expected
    assert calls == [(http.session, novel_id)]
    assert http.session.rollback_count == 0


def test_status_maps_missing_novel_to_404_without_model_or_database_runtime(
    monkeypatch: pytest.MonkeyPatch,
    api,
    http,
) -> None:
    novel_id = uuid4()
    monkeypatch.setattr(
        api,
        "get_character_profile_completion_status",
        lambda *_args: (_ for _ in ()).throw(api.NotFoundError("novel not found")),
    )

    response = http.client.get(
        f"/novels/{novel_id}/character-profile-completion/status"
    )

    assert response.status_code == 404
    assert "novel not found" in response.json()["detail"]


def test_generate_uses_novel_agent_character_skill_and_verified_actual_model(
    monkeypatch: pytest.MonkeyPatch,
    api,
    http,
) -> None:
    final_text = '{"characters":[{"character_id":"placeholder"}]}'
    setup = _generation_setup(
        monkeypatch,
        api,
        http,
        final_text=final_text,
    )
    prompt_limit_calls: list[tuple[str, ModelAudit]] = []
    normalize_calls: list[tuple[dict, dict]] = []
    normalized = {
        "schema_version": "character-profile-completion-output-v1",
        "characters": [],
    }

    monkeypatch.setattr(
        api,
        "ensure_prompt_within_effective_limit",
        lambda prompt, model: prompt_limit_calls.append((prompt, model)),
    )

    def normalize(snapshot, payload):
        normalize_calls.append((snapshot, payload))
        return normalized

    monkeypatch.setattr(api, "normalize_character_profile_output", normalize)

    response = http.client.post(
        f"/novels/{setup.novel_id}/character-profile-completion/generate",
        json={"force_new": True},
    )

    assert response.status_code == 200
    assert response.json()["state"] == "ready"
    assert setup.status_calls == [setup.novel_id, setup.novel_id]
    assert setup.start_calls == [
        {
            "scope_type": "novel",
            "scope_id": setup.novel_id,
            "kind": "character_profile_completion",
            "input_snapshot": setup.snapshot,
            "execution_agent_id": "ai-novel-writer",
            "requested_provider_id": "provider-a",
            "requested_model_id": "model-a",
            "generation_contract_version": api.GENERATION_CONTRACT_VERSION,
            "novel_id": setup.novel_id,
            "force_new": True,
        }
    ]
    assert prompt_limit_calls == [("profile-prompt", http.configured_model)]
    assert setup.chat_calls == [
        {
            "prompt": "profile-prompt",
            "skill": "character-craft",
            "session_id": f"novel-character-profile-completion:{setup.job_id}",
        }
    ]
    assert normalize_calls == [
        (setup.snapshot, {"characters": [{"character_id": "placeholder"}]})
    ]
    assert setup.complete_calls == [
        {
            "actual_provider_id": "provider-a",
            "actual_model_id": "model-a",
            "output_text": final_text,
            "output_json": normalized,
        }
    ]
    assert setup.fail_calls == []


def test_generate_model_audit_mismatch_fails_before_json_parsing_and_records_actual(
    monkeypatch: pytest.MonkeyPatch,
    api,
    http,
) -> None:
    setup = _generation_setup(
        monkeypatch,
        api,
        http,
        final_text="{malformed",
        actual_model="model-b",
    )
    parse_calls: list[str] = []
    monkeypatch.setattr(api, "ensure_prompt_within_effective_limit", lambda *_args: None)

    def parse(text):
        parse_calls.append(text)
        raise AssertionError("model mismatch must precede JSON parsing")

    monkeypatch.setattr(api, "parse_model_json", parse)

    response = http.client.post(
        f"/novels/{setup.novel_id}/character-profile-completion/generate",
        json={},
    )

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["type"] == "model_verification_failed"
    assert detail["job"]["state"] == "failed"
    assert parse_calls == []
    assert setup.complete_calls == []
    assert setup.fail_calls[0]["actual_provider_id"] == "provider-a"
    assert setup.fail_calls[0]["actual_model_id"] == "model-b"
    assert "与调用前活动模型不一致" in setup.fail_calls[0]["failure_message"]


def test_generate_malformed_final_json_returns_502_and_never_completes(
    monkeypatch: pytest.MonkeyPatch,
    api,
    http,
) -> None:
    setup = _generation_setup(
        monkeypatch,
        api,
        http,
        final_text="这不是 JSON",
    )
    monkeypatch.setattr(api, "ensure_prompt_within_effective_limit", lambda *_args: None)

    response = http.client.post(
        f"/novels/{setup.novel_id}/character-profile-completion/generate",
        json={},
    )

    assert response.status_code == 502
    assert response.json()["detail"]["type"] == "model_verification_failed"
    assert setup.complete_calls == []
    assert setup.fail_calls[0]["actual_provider_id"] == "provider-a"
    assert setup.fail_calls[0]["actual_model_id"] == "model-a"
    assert "没有返回可解析的 JSON" in setup.fail_calls[0]["failure_message"]


def test_generate_rejects_prose_wrapped_json_instead_of_accepting_embedded_object(
    monkeypatch: pytest.MonkeyPatch,
    api,
    http,
) -> None:
    """The dedicated profile contract requires one bare final JSON object."""

    wrapped = '分析完成：{"characters":[]}'
    setup = _generation_setup(monkeypatch, api, http, final_text=wrapped)
    monkeypatch.setattr(api, "ensure_prompt_within_effective_limit", lambda *_args: None)
    monkeypatch.setattr(
        api,
        "normalize_character_profile_output",
        lambda *_args: {
            "schema_version": "character-profile-completion-output-v1",
            "characters": [],
        },
    )

    response = http.client.post(
        f"/novels/{setup.novel_id}/character-profile-completion/generate",
        json={},
    )

    assert response.status_code == 502
    assert response.json()["detail"]["type"] == "model_verification_failed"
    assert setup.complete_calls == []
    assert len(setup.fail_calls) == 1


def test_generate_does_not_call_agent_when_single_flight_job_is_not_owned(
    monkeypatch: pytest.MonkeyPatch,
    api,
    http,
) -> None:
    novel_id = uuid4()
    job_id = uuid4()
    status_calls = 0

    def status(*_args):
        nonlocal status_calls
        status_calls += 1
        return {
            "eligible": True,
            "state": "running",
            "stale": False,
            "source_summary": {},
            "job": {"id": str(job_id), "state": "running"},
        }

    monkeypatch.setattr(api, "get_character_profile_completion_status", status)
    monkeypatch.setattr(
        api,
        "build_character_profile_completion_snapshot",
        lambda *_args: {"characters": []},
    )
    monkeypatch.setattr(
        api,
        "start_creative_generation",
        lambda *_args, **_kwargs: {
            "id": str(job_id),
            "state": "running",
            "should_execute": False,
        },
    )

    response = http.client.post(
        f"/novels/{novel_id}/character-profile-completion/generate",
        json={"force_new": True},
    )

    assert response.status_code == 200
    assert response.json()["state"] == "running"
    assert status_calls == 2


def test_apply_forwards_json_decisions_and_idempotency_key(
    monkeypatch: pytest.MonkeyPatch,
    api,
    http,
) -> None:
    novel_id = uuid4()
    job_id = uuid4()
    character_id = uuid4()
    calls: list[dict[str, object]] = []

    def apply(session, received_novel_id, received_job_id, **kwargs):
        calls.append(
            {
                "session": session,
                "novel_id": received_novel_id,
                "job_id": received_job_id,
                **kwargs,
            }
        )
        return {"state": "applied", "can_restore": True}

    monkeypatch.setattr(api, "apply_character_profile_completion", apply)

    response = http.client.post(
        f"/novels/{novel_id}/character-profile-completion/jobs/{job_id}/apply",
        json={
            "idempotency_key": "apply-key-001",
            "decisions": [
                {
                    "character_id": str(character_id),
                    "base_version": 2,
                    "replace_existing": True,
                }
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["state"] == "applied"
    assert calls == [
        {
            "session": http.session,
            "novel_id": novel_id,
            "job_id": job_id,
            "idempotency_key": "apply-key-001",
            "decisions": [
                {
                    "character_id": str(character_id),
                    "base_version": 2,
                    "replace_existing": True,
                }
            ],
        }
    ]


@pytest.mark.parametrize(
    "body",
    [
        {"idempotency_key": "short", "decisions": []},
        {"idempotency_key": "apply-key-001", "decisions": []},
        {
            "idempotency_key": "apply-key-001",
            "decisions": [
                {"character_id": "not-a-uuid", "base_version": 1}
            ],
        },
        {
            "idempotency_key": "apply-key-001",
            "decisions": [
                {"character_id": str(uuid4()), "base_version": 0}
            ],
        },
        {
            "idempotency_key": "apply-key-001",
            "decisions": [
                {"character_id": str(uuid4()), "base_version": 1}
                for _ in range(201)
            ],
        },
    ],
)
def test_apply_rejects_invalid_request_boundaries_before_service(
    monkeypatch: pytest.MonkeyPatch,
    api,
    http,
    body,
) -> None:
    monkeypatch.setattr(
        api,
        "apply_character_profile_completion",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("invalid request reached the domain service")
        ),
    )

    response = http.client.post(
        f"/novels/{uuid4()}/character-profile-completion/jobs/{uuid4()}/apply",
        json=body,
    )

    assert response.status_code == 422


def test_apply_rejects_whitespace_only_idempotency_key(
    monkeypatch: pytest.MonkeyPatch,
    api,
    http,
) -> None:
    monkeypatch.setattr(
        api,
        "apply_character_profile_completion",
        lambda *_args, **_kwargs: {"state": "applied"},
    )

    response = http.client.post(
        f"/novels/{uuid4()}/character-profile-completion/jobs/{uuid4()}/apply",
        json={
            "idempotency_key": "        ",
            "decisions": [
                {"character_id": str(uuid4()), "base_version": 1}
            ],
        },
    )

    assert response.status_code == 422


def test_apply_domain_failure_rolls_back_and_maps_to_422(
    monkeypatch: pytest.MonkeyPatch,
    api,
    http,
) -> None:
    monkeypatch.setattr(
        api,
        "apply_character_profile_completion",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            api.ValidationError("角色版本冲突，整批不能应用")
        ),
    )

    response = http.client.post(
        f"/novels/{uuid4()}/character-profile-completion/jobs/{uuid4()}/apply",
        json={
            "idempotency_key": "apply-key-001",
            "decisions": [
                {"character_id": str(uuid4()), "base_version": 1}
            ],
        },
    )

    assert response.status_code == 422
    assert "角色版本冲突" in response.json()["detail"]
    assert http.session.rollback_count == 1


def test_restore_forwards_scope_batch_and_idempotency_key(
    monkeypatch: pytest.MonkeyPatch,
    api,
    http,
) -> None:
    novel_id = uuid4()
    batch_id = uuid4()
    calls: list[dict[str, object]] = []

    def restore(session, received_novel_id, received_batch_id, **kwargs):
        calls.append(
            {
                "session": session,
                "novel_id": received_novel_id,
                "batch_id": received_batch_id,
                **kwargs,
            }
        )
        return {"state": "applied", "can_restore": False}

    monkeypatch.setattr(api, "restore_character_profile_apply_batch", restore)

    response = http.client.post(
        f"/novels/{novel_id}/character-profile-completion/apply-batches/{batch_id}/restore",
        json={"idempotency_key": "restore-key-001"},
    )

    assert response.status_code == 200
    assert calls == [
        {
            "session": http.session,
            "novel_id": novel_id,
            "batch_id": batch_id,
            "idempotency_key": "restore-key-001",
        }
    ]


@pytest.mark.parametrize("idempotency_key", ["short", ""])
def test_restore_rejects_short_idempotency_key_before_service(
    monkeypatch: pytest.MonkeyPatch,
    api,
    http,
    idempotency_key: str,
) -> None:
    monkeypatch.setattr(
        api,
        "restore_character_profile_apply_batch",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("invalid request reached the restore service")
        ),
    )

    response = http.client.post(
        f"/novels/{uuid4()}/character-profile-completion/apply-batches/{uuid4()}/restore",
        json={"idempotency_key": idempotency_key},
    )

    assert response.status_code == 422


def test_restore_rejects_whitespace_only_idempotency_key(
    monkeypatch: pytest.MonkeyPatch,
    api,
    http,
) -> None:
    monkeypatch.setattr(
        api,
        "restore_character_profile_apply_batch",
        lambda *_args, **_kwargs: {"state": "applied"},
    )

    response = http.client.post(
        f"/novels/{uuid4()}/character-profile-completion/apply-batches/{uuid4()}/restore",
        json={"idempotency_key": "        "},
    )

    assert response.status_code == 422

