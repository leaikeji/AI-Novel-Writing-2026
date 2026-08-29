from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from backend.creative_data_models import EmbeddingGeneration, EmbeddingProfile
from backend.database import get_session
from backend.embedding import api
from backend.embedding.adapter import (
    EmbeddingAdapterError,
    EmbeddingBatchResult,
    EmbeddingVector,
)
from backend.embedding.lifecycle import EmbeddingLifecycleError
from backend.embedding.persistence import activate_candidate_generation
from backend.embedding.secrets import EmbeddingSecretError


class _Rows:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class EvaluationSession:
    def __init__(self, generation: Any, profile: Any, rows: list[Any]) -> None:
        self.generation = generation
        self.profile = profile
        self.rows = rows
        self.commit_count = 0
        self.rollback_count = 0

    def get(self, model: type[Any], identity: Any) -> Any | None:
        if model is EmbeddingGeneration and identity == self.generation.id:
            return self.generation
        if model is EmbeddingProfile and identity == self.profile.id:
            return self.profile
        return None

    def execute(self, _statement: Any) -> _Rows:
        return _Rows(self.rows)

    def scalar(self, _statement: Any) -> Any:
        return self.generation

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1


class ActivationSession:
    def __init__(
        self,
        *,
        configuration: Any,
        candidate: Any,
        builds: tuple[Any, ...] = (),
        consents: tuple[Any, ...] = (),
    ) -> None:
        self._scalars = iter((configuration, candidate))
        self._collections = iter((builds, consents))
        self.commit_count = 0
        self.rollback_count = 0
        self.flush_count = 0

    def scalar(self, _statement: Any) -> Any:
        return next(self._scalars)

    def scalars(self, _statement: Any) -> tuple[Any, ...]:
        return next(self._collections)

    def get(self, _model: type[Any], _identity: Any) -> None:
        return None

    def flush(self) -> None:
        self.flush_count += 1

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1


class CandidateSession:
    def __init__(self) -> None:
        self.commit_count = 0
        self.rollback_count = 0

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1


class FakeSecretStore:
    def __init__(self, *, fail_delete_ref: str | None = None) -> None:
        self.fail_delete_ref = fail_delete_ref
        self.put_calls: list[str] = []
        self.delete_calls: list[str] = []

    def put(self, value: str) -> Any:
        self.put_calls.append(value)
        return SimpleNamespace(credential_ref="credential:temporary", last4=value[-4:])

    def delete(self, credential_ref: str) -> None:
        self.delete_calls.append(credential_ref)
        if credential_ref == self.fail_delete_ref:
            raise EmbeddingSecretError("SECRET_DELETE_FAILED", "脱敏清理失败")

    def get(self, credential_ref: str) -> str:
        return "stored-key-for-test"


def _app(session: Any) -> FastAPI:
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[get_session] = lambda: session
    return app


def _configuration(*, version: int = 5) -> Any:
    return SimpleNamespace(
        version=version,
        credential_ref="credential:old",
        api_key_last4="old4",
        base_url="https://workspace.cn-beijing.maas.aliyuncs.com/api/v1",
        candidate_generation_id="candidate:old",
        connection_summary_json={},
    )


def _candidate_payload(*, expected_version: int = 5, dimension: int = 2048) -> dict[str, Any]:
    return {
        "expected_version": expected_version,
        "base_url": "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1",
        "requested_model_id": "qwen3.7-text-embedding",
        "requested_dimension": dimension,
        "api_key_action": "replace",
        "api_key": "sk-new-secret-value-123456",
    }


def _sentinel_evidence(dimension: int = 2048) -> Any:
    return api._SentinelEvidence(
        query_request_id="query-request",
        document_request_id="document-request",
        actual_dimension=dimension,
        total_tokens=8,
        latency_ms=12,
    )


def test_config_mask_uses_only_database_last_four() -> None:
    configuration = SimpleNamespace(
        credential_ref="credential:test",
        api_key_last4="3456",
    )
    assert api._masked_api_key(configuration) == "********3456"
    assert "12345678" not in api._masked_api_key(configuration)


def test_config_get_never_returns_raw_key_or_last_eight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configuration = SimpleNamespace(
        version=5,
        credential_ref="credential:test",
        api_key="sk-raw-key-must-not-escape",
        api_key_last4="3456",
        api_key_last8="12343456",
        base_url="https://workspace.cn-beijing.maas.aliyuncs.com/api/v1",
        connection_state="available",
        connection_summary_json={},
        active_generation_id=None,
        candidate_generation_id=None,
        previous_generation_id=None,
    )
    session = SimpleNamespace(scalar=lambda _statement: 0)
    monkeypatch.setattr(api, "get_configuration", lambda *_args, **_kwargs: configuration)
    monkeypatch.setattr(api, "_secret_store_ready", lambda: True)

    payload = api.embedding_config_get(session)

    assert payload["api_key_masked"] == "********3456"
    assert "api_key" not in payload
    assert "api_key_last4" not in payload
    assert "api_key_last8" not in payload
    serialized = str(payload)
    assert "sk-raw-key-must-not-escape" not in serialized
    assert "12343456" not in serialized


def test_candidate_request_defaults_to_2048_and_allows_1024() -> None:
    base = {
        "expected_version": 0,
        "base_url": "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1",
    }
    assert api.CandidateRequest(**base).requested_dimension == 2048
    assert api.CandidateRequest(**base, requested_dimension=1024).requested_dimension == 1024


@pytest.mark.asyncio
async def test_sentinel_verifies_query_and_document_at_2048(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class FakeAdapter:
        def __init__(self, *, base_url: str) -> None:
            assert base_url.endswith("/api/v1")

        async def embed(self, **kwargs: Any) -> EmbeddingBatchResult:
            calls.append(kwargs)
            request_id = f"{kwargs['text_type']}-request"
            return EmbeddingBatchResult(
                request_id=request_id,
                vectors=(EmbeddingVector(0, (0.0,) * 2048),),
                total_tokens=4,
                input_tokens=4,
            )

    monkeypatch.setattr(api, "DashScopeEmbeddingAdapter", FakeAdapter)
    evidence = await api._sentinel(
        base_url="https://workspace.cn-beijing.maas.aliyuncs.com/api/v1",
        credential_ref=None,
        model_id="qwen3.7-text-embedding",
        dimension=2048,
        ephemeral_api_key="sk-never-log-this-value",
    )

    assert evidence.actual_dimension == 2048
    assert evidence.query_request_id == "query-request"
    assert evidence.document_request_id == "document-request"
    assert [call["text_type"] for call in calls] == ["query", "document"]
    assert "instruct" in calls[0]
    assert "instruct" not in calls[1]


@pytest.mark.asyncio
async def test_candidate_sentinel_failure_preserves_old_configuration_and_deletes_temp_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configuration = _configuration()
    session = CandidateSession()
    store = FakeSecretStore()
    monkeypatch.setattr(api, "get_configuration", lambda *_args, **_kwargs: configuration)
    monkeypatch.setattr(api, "_secret_store", lambda: store)

    async def reject_sentinel(**_kwargs: Any) -> Any:
        assert session.rollback_count >= 1
        raise EmbeddingAdapterError("EMBEDDING_AUTH_FAILED", "authentication failed")

    monkeypatch.setattr(api, "_sentinel", reject_sentinel)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(session)),
        base_url="http://testserver",
    ) as client:
        response = await client.put("/embedding-config/candidate", json=_candidate_payload())

    assert response.status_code == 503
    assert configuration.version == 5
    assert configuration.credential_ref == "credential:old"
    assert configuration.candidate_generation_id == "candidate:old"
    assert session.commit_count == 0
    assert store.delete_calls == ["credential:temporary"]
    assert "sk-new-secret-value-123456" not in response.text


@pytest.mark.asyncio
async def test_candidate_cas_conflict_after_sentinel_does_not_overwrite_other_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = _configuration()
    changed = _configuration(version=6)
    changed.credential_ref = "credential:other-window"
    changed.candidate_generation_id = "candidate:other-window"
    states = iter((original, changed))
    session = CandidateSession()
    store = FakeSecretStore()
    monkeypatch.setattr(api, "get_configuration", lambda *_args, **_kwargs: next(states))
    monkeypatch.setattr(api, "_secret_store", lambda: store)

    async def sentinel(**_kwargs: Any) -> Any:
        assert session.rollback_count >= 1
        return _sentinel_evidence()

    monkeypatch.setattr(api, "_sentinel", sentinel)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(session)),
        base_url="http://testserver",
    ) as client:
        response = await client.put("/embedding-config/candidate", json=_candidate_payload())

    assert response.status_code == 409
    assert changed.credential_ref == "credential:other-window"
    assert changed.candidate_generation_id == "candidate:other-window"
    assert session.commit_count == 0
    assert store.delete_calls == ["credential:temporary"]


@pytest.mark.asyncio
async def test_candidate_creation_failure_rolls_back_and_deletes_temp_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = _configuration()
    session = CandidateSession()
    store = FakeSecretStore()
    monkeypatch.setattr(api, "get_configuration", lambda *_args, **_kwargs: original)
    monkeypatch.setattr(api, "_secret_store", lambda: store)

    async def sentinel(**_kwargs: Any) -> Any:
        assert session.rollback_count >= 1
        return _sentinel_evidence()

    staged = SimpleNamespace(
        version=6,
        credential_ref="credential:temporary",
        api_key_last4="3456",
    )
    monkeypatch.setattr(api, "_sentinel", sentinel)
    monkeypatch.setattr(api, "apply_credential_reference", lambda *_args, **_kwargs: staged)
    monkeypatch.setattr(
        api,
        "create_verified_candidate",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            EmbeddingLifecycleError("candidate_create_failed", "candidate creation failed")
        ),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(session)),
        base_url="http://testserver",
    ) as client:
        response = await client.put("/embedding-config/candidate", json=_candidate_payload())

    assert response.status_code == 409
    assert original.version == 5
    assert original.credential_ref == "credential:old"
    assert original.candidate_generation_id == "candidate:old"
    assert session.commit_count == 0
    assert store.delete_calls == ["credential:temporary"]


@pytest.mark.asyncio
async def test_candidate_2048_commits_atomically_and_retry_is_version_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configuration = _configuration()
    session = CandidateSession()
    store = FakeSecretStore()
    create_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(api, "get_configuration", lambda *_args, **_kwargs: configuration)
    monkeypatch.setattr(api, "_secret_store", lambda: store)

    async def sentinel(**kwargs: Any) -> Any:
        assert session.rollback_count >= 1
        assert kwargs["dimension"] == 2048
        assert kwargs["ephemeral_api_key"] == "sk-new-secret-value-123456"
        return _sentinel_evidence()

    def apply_reference(_session: Any, **kwargs: Any) -> Any:
        assert kwargs["expected_version"] == configuration.version
        configuration.credential_ref = kwargs["credential_ref"]
        configuration.api_key_last4 = kwargs["last4"]
        configuration.version += 1
        return configuration

    def create_candidate(_session: Any, **kwargs: Any) -> tuple[Any, Any]:
        create_calls.append(kwargs)
        assert kwargs["expected_config_version"] == configuration.version
        assert kwargs["dimension"] == 2048
        assert kwargs["request_id"] == "query-request"
        assert kwargs["document_request_id"] == "document-request"
        configuration.candidate_generation_id = "candidate:new"
        configuration.version += 1
        return SimpleNamespace(), SimpleNamespace()

    monkeypatch.setattr(api, "_sentinel", sentinel)
    monkeypatch.setattr(api, "apply_credential_reference", apply_reference)
    monkeypatch.setattr(api, "create_verified_candidate", create_candidate)
    monkeypatch.setattr(
        api,
        "embedding_config_get",
        lambda _session: {
            "version": configuration.version,
            "api_key_masked": "********3456",
            "credential_cleanup_warning": None,
        },
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(session)),
        base_url="http://testserver",
    ) as client:
        response = await client.put("/embedding-config/candidate", json=_candidate_payload())
        retry = await client.put("/embedding-config/candidate", json=_candidate_payload())

    assert response.status_code == 200
    assert retry.status_code == 409
    assert response.json()["api_key_masked"] == "********3456"
    assert configuration.version == 7
    assert configuration.credential_ref == "credential:temporary"
    assert configuration.candidate_generation_id == "candidate:new"
    assert len(create_calls) == 1
    assert store.put_calls == ["sk-new-secret-value-123456"]
    assert store.delete_calls == ["credential:old"]


@pytest.mark.asyncio
async def test_candidate_keep_does_not_rewrite_credential_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configuration = _configuration()
    session = CandidateSession()
    store = FakeSecretStore()
    monkeypatch.setattr(api, "get_configuration", lambda *_args, **_kwargs: configuration)
    monkeypatch.setattr(api, "_secret_store", lambda: store)

    async def sentinel(**_kwargs: Any) -> Any:
        return _sentinel_evidence()

    monkeypatch.setattr(api, "_sentinel", sentinel)
    monkeypatch.setattr(
        api,
        "apply_credential_reference",
        lambda *_args, **_kwargs: pytest.fail("keep must not rewrite credential metadata"),
    )

    def create_candidate(_session: Any, **kwargs: Any) -> tuple[Any, Any]:
        assert kwargs["expected_config_version"] == 5
        configuration.version += 1
        configuration.candidate_generation_id = "candidate:new"
        return SimpleNamespace(), SimpleNamespace()

    monkeypatch.setattr(api, "create_verified_candidate", create_candidate)
    monkeypatch.setattr(
        api,
        "embedding_config_get",
        lambda _session: {"version": configuration.version},
    )

    payload = _candidate_payload()
    payload.update({"api_key_action": "keep"})
    payload.pop("api_key")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(session)),
        base_url="http://testserver",
    ) as client:
        response = await client.put("/embedding-config/candidate", json=payload)

    assert response.status_code == 200
    assert configuration.version == 6
    assert configuration.credential_ref == "credential:old"
    assert configuration.api_key_last4 == "old4"
    assert store.put_calls == []
    assert store.delete_calls == []


@pytest.mark.asyncio
async def test_candidate_success_records_old_secret_cleanup_failure_without_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configuration = _configuration()
    session = CandidateSession()
    store = FakeSecretStore(fail_delete_ref="credential:old")
    monkeypatch.setattr(api, "get_configuration", lambda *_args, **_kwargs: configuration)
    monkeypatch.setattr(api, "_secret_store", lambda: store)

    async def sentinel(**_kwargs: Any) -> Any:
        return _sentinel_evidence()

    def apply_reference(_session: Any, **kwargs: Any) -> Any:
        configuration.credential_ref = kwargs["credential_ref"]
        configuration.api_key_last4 = kwargs["last4"]
        configuration.version += 1
        return configuration

    def create_candidate(_session: Any, **_kwargs: Any) -> tuple[Any, Any]:
        configuration.version += 1
        configuration.candidate_generation_id = "candidate:new"
        return SimpleNamespace(), SimpleNamespace()

    monkeypatch.setattr(api, "_sentinel", sentinel)
    monkeypatch.setattr(api, "apply_credential_reference", apply_reference)
    monkeypatch.setattr(api, "create_verified_candidate", create_candidate)
    monkeypatch.setattr(
        api,
        "embedding_config_get",
        lambda _session: {
            "version": configuration.version,
            "credential_cleanup_warning": None,
        },
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(session)),
        base_url="http://testserver",
    ) as client:
        response = await client.put("/embedding-config/candidate", json=_candidate_payload())

    assert response.status_code == 200
    assert response.json()["credential_cleanup_warning"]
    assert configuration.version == 7
    assert configuration.candidate_generation_id == "candidate:new"
    assert configuration.connection_summary_json["credential_cleanup"]["state"] == "pending"
    assert "credential:old" not in str(configuration.connection_summary_json)
    assert session.commit_count == 2


@pytest.mark.asyncio
async def test_candidate_rejects_unsupported_dimension_before_secret_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = CandidateSession()
    store = FakeSecretStore()
    monkeypatch.setattr(api, "_secret_store", lambda: store)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(session)),
        base_url="http://testserver",
    ) as client:
        response = await client.put(
            "/embedding-config/candidate",
            json=_candidate_payload(dimension=1234),
        )

    assert response.status_code == 422
    assert store.put_calls == []


@pytest.mark.asyncio
async def test_post_candidate_evaluate_uses_adapter_fake_and_marks_gate_passed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generation_id = uuid4()
    profile_id = uuid4()
    configuration = SimpleNamespace(
        version=4,
        candidate_generation_id=generation_id,
        credential_ref="credential:current",
    )
    generation = SimpleNamespace(
        id=generation_id,
        profile_id=profile_id,
        state="ready",
        index_fingerprint="a" * 64,
        evaluation_state="not_run",
        evaluation_summary_json={},
    )
    profile = SimpleNamespace(
        id=profile_id,
        credential_ref="credential:test",
        base_url="https://workspace.cn-beijing.maas.aliyuncs.com/api/v1",
        actual_model_id="qwen3.7-text-embedding",
        dimension=2,
    )
    source = SimpleNamespace(novel_id=uuid4(), corpus="manuscript", id=uuid4())
    chunk = SimpleNamespace(
        id=uuid4(), chunk_index=0, content_text="fixed evaluation query"
    )
    embedding = SimpleNamespace(embedding=(1.0, 0.0))
    session = EvaluationSession(generation, profile, [(source, chunk, embedding)])
    adapter_calls: list[dict[str, Any]] = []

    class FakeAdapter:
        def __init__(self, *, base_url: str) -> None:
            assert base_url == profile.base_url

        async def embed(self, **kwargs: Any) -> EmbeddingBatchResult:
            adapter_calls.append(kwargs)
            assert kwargs["text_type"] == "query"
            assert kwargs["texts"] == ["fixed evaluation query"]
            return EmbeddingBatchResult(
                request_id="fake-request-id",
                vectors=(EmbeddingVector(text_index=0, values=(1.0, 0.0)),),
                total_tokens=3,
                input_tokens=3,
            )

    monkeypatch.setattr(api, "get_configuration", lambda *_args, **_kwargs: configuration)
    monkeypatch.setattr(api, "DashScopeEmbeddingAdapter", FakeAdapter)
    monkeypatch.setattr(
        api,
        "_secret_store",
        lambda: SimpleNamespace(
            get=lambda credential_ref: (
                "fake-api-key"
                if credential_ref == configuration.credential_ref
                else pytest.fail("候选评测使用了过期凭据引用")
            )
        ),
    )
    monkeypatch.setattr(
        api,
        "embedding_config_get",
        lambda _session: {"evaluation_state": generation.evaluation_state},
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(session)),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/embedding-config/candidate/evaluate",
            json={"expected_version": 4},
        )

    assert response.status_code == 200
    assert response.json() == {"evaluation_state": "passed"}
    assert generation.evaluation_summary_json["passed"] is True
    assert generation.evaluation_summary_json["request_ids"] == ["fake-request-id"]
    assert session.commit_count == 2
    assert len(adapter_calls) == 1


@pytest.mark.asyncio
async def test_post_candidate_activate_refuses_unpassed_evaluation_and_then_activates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_id = api.LOCAL_OWNER_ID
    workspace_id = api.LOCAL_WORKSPACE_ID
    novel_id = uuid4()
    consent_id = uuid4()
    candidate_id = uuid4()

    def state(evaluation_state: str) -> tuple[Any, Any, Any, Any]:
        configuration = SimpleNamespace(
            version=7,
            candidate_generation_id=candidate_id,
            active_generation_id=None,
            previous_generation_id=None,
            updated_at=None,
        )
        candidate = SimpleNamespace(
            id=candidate_id,
            owner_id=owner_id,
            workspace_id=workspace_id,
            state="ready",
            evaluation_state=evaluation_state,
            activated_at=None,
        )
        build = SimpleNamespace(
            novel_id=novel_id,
            consent_id=consent_id,
            state="ready",
        )
        consent = SimpleNamespace(novel_id=novel_id, id=consent_id)
        return configuration, candidate, build, consent

    failed_config, failed_candidate, _, _ = state("failed")
    failed_session = ActivationSession(
        configuration=failed_config,
        candidate=failed_candidate,
    )
    with pytest.raises(EmbeddingLifecycleError) as blocked:
        activate_candidate_generation(
            failed_session,
            owner_id=owner_id,
            workspace_id=workspace_id,
            expected_config_version=7,
        )
    assert blocked.value.code == "candidate_evaluation_failed"
    assert failed_candidate.state == "ready"
    assert failed_config.active_generation_id is None
    assert failed_session.flush_count == 0

    configuration, candidate, build, consent = state("passed")
    session = ActivationSession(
        configuration=configuration,
        candidate=candidate,
        builds=(build,),
        consents=(consent,),
    )
    monkeypatch.setattr(api, "get_configuration", lambda *_args, **_kwargs: configuration)
    monkeypatch.setattr(
        api,
        "_generation_payload",
        lambda _session, generation_id: {
            "id": str(generation_id),
            "state": candidate.state,
        },
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(session)),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/embedding-config/candidate/activate",
            json={"expected_version": 7},
        )

    assert response.status_code == 200
    assert response.json() == {"id": str(candidate_id), "state": "active"}
    assert candidate.state == "active"
    assert configuration.active_generation_id == candidate_id
    assert configuration.candidate_generation_id is None
    assert configuration.version == 8
    assert session.flush_count == 1
    assert session.commit_count == 1
