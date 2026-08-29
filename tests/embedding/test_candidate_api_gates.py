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
from backend.embedding.adapter import EmbeddingBatchResult, EmbeddingVector
from backend.embedding.lifecycle import EmbeddingLifecycleError
from backend.embedding.persistence import activate_candidate_generation


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


def _app(session: Any) -> FastAPI:
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[get_session] = lambda: session
    return app


@pytest.mark.asyncio
async def test_post_candidate_evaluate_uses_adapter_fake_and_marks_gate_passed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generation_id = uuid4()
    profile_id = uuid4()
    configuration = SimpleNamespace(
        version=4,
        candidate_generation_id=generation_id,
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
        lambda: SimpleNamespace(get=lambda credential_ref: "fake-api-key"),
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
