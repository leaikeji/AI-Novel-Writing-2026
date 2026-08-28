from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.narration import health_api, release_gate
from backend.narration import production_runtime
from backend.narration.contracts import ContractError
from backend.narration.production_runtime import ValidationRuntimeScope
from backend.narration.runtime import SidecarRuntimeError, SidecarValidationMetrics


NOVEL_ID = UUID("7a000000-0000-4000-8000-000000000001")
DOCUMENT_ID = UUID("7a000000-0000-4000-8000-000000000002")
TOKEN = "validation-observation-token-000000000000000"


class _Adapter:
    def __init__(self, *, failure: bool = False) -> None:
        self.calls = 0
        self.failure = failure

    async def observe_validation_metrics(self) -> SidecarValidationMetrics:
        self.calls += 1
        if self.failure:
            raise SidecarRuntimeError(
                "PRIVATE_DETAIL_MUST_NOT_ESCAPE",
                "private token path prompt audio body",
            )
        return SidecarValidationMetrics(
            model_ready=True,
            worker_ready=True,
            active_syntheses=1,
        )


@pytest.fixture(autouse=True)
def _reset_gate() -> None:
    release_gate.uninstall_narration_t4_http_access_policy()
    production_runtime._validation_segment_claim_gate.clear()
    production_runtime._validation_runtime_scope = None
    yield
    production_runtime._validation_segment_claim_gate.clear()
    production_runtime._validation_runtime_scope = None
    release_gate.uninstall_narration_t4_http_access_policy()


def _scope(*, expired: bool = False) -> ValidationRuntimeScope:
    seconds = -1 if expired else 3_600
    return ValidationRuntimeScope(
        novel_id=NOVEL_ID,
        document_id=DOCUMENT_ID,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=seconds),
    )


def _client(monkeypatch: pytest.MonkeyPatch, adapter: _Adapter | None) -> TestClient:
    monkeypatch.setenv(health_api.PRODUCT_ENABLE_ENV, "false")
    monkeypatch.setenv(health_api.VALIDATION_ENABLE_ENV, "true")
    monkeypatch.setattr(health_api, "current_validation_runtime_scope", _scope)
    production_runtime._validation_runtime_scope = _scope()
    monkeypatch.setattr(
        health_api,
        "get_ready_narration_adapter",
        lambda: adapter,
    )

    def access_policy(request) -> bool:  # type: ignore[no-untyped-def]
        values = request.headers.getlist(release_gate.VALIDATION_TOKEN_HEADER)
        return len(values) == 1 and values[0] == TOKEN

    release_gate.install_narration_t4_http_access_policy(access_policy)
    app = FastAPI()
    app.include_router(health_api.router)
    return TestClient(app, raise_server_exceptions=False)


def _path(
    *,
    novel_id: UUID = NOVEL_ID,
    document_id: UUID = DOCUMENT_ID,
) -> str:
    return (
        f"/novels/{novel_id}/documents/{document_id}"
        "/narration-validation-observation"
    )


def _claim_gate_path(
    *,
    novel_id: UUID = NOVEL_ID,
    document_id: UUID = DOCUMENT_ID,
) -> str:
    return (
        f"/novels/{novel_id}/documents/{document_id}"
        "/narration-validation-segment-claim-gate"
    )


def test_exact_validation_scope_returns_only_redacted_fixed_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _Adapter()
    response = _client(monkeypatch, adapter).get(
        _path(),
        headers={release_gate.VALIDATION_TOKEN_HEADER: TOKEN},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert set(payload) == {
        "model_ready",
        "worker_ready",
        "active_syntheses",
        "queued_jobs",
        "observed_at",
    }
    assert payload | {"observed_at": None} == {
        "model_ready": True,
        "worker_ready": True,
        "active_syntheses": 1,
        "queued_jobs": 0,
        "observed_at": None,
    }
    assert datetime.fromisoformat(payload["observed_at"]).tzinfo is not None
    assert adapter.calls == 1
    assert not any(
        marker in response.text.lower()
        for marker in ("token", "path", "prompt", "audio", "正文")
    )


def test_hidden_claim_gate_arm_observe_pause_and_release_are_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(monkeypatch, _Adapter())
    headers = {release_gate.VALIDATION_TOKEN_HEADER: TOKEN}
    run_id = UUID("7a000000-0000-4000-8000-000000000003")

    default = client.get(_claim_gate_path(), headers=headers)
    assert default.status_code == 200
    assert default.json() == {
        "code": "VALIDATION_SEGMENT_CLAIM_GATE_DEFAULT_ALLOW",
        "state": "default_allow",
        "claim_limit": 0,
        "claimed_count": 0,
        "remaining_count": 0,
        "expires_at": None,
        "run_fingerprint_sha256": None,
        "scope_fingerprint_sha256": None,
    }

    armed = client.post(
        _claim_gate_path(),
        headers=headers,
        json={"run_id": str(run_id)},
    )
    assert armed.status_code == 200
    payload = armed.json()
    assert set(payload) == {
        "code",
        "state",
        "claim_limit",
        "claimed_count",
        "remaining_count",
        "expires_at",
        "run_fingerprint_sha256",
        "scope_fingerprint_sha256",
    }
    assert payload["code"] == "VALIDATION_SEGMENT_CLAIM_GATE_ARMED"
    assert payload["state"] == "armed"
    assert payload["claim_limit"] == 1
    assert payload["remaining_count"] == 1
    assert payload["run_fingerprint_sha256"] != str(run_id)
    assert not any(
        marker in armed.text.lower()
        for marker in (TOKEN.lower(), str(NOVEL_ID), str(DOCUMENT_ID), "path", "正文")
    )

    permit = production_runtime._validation_segment_claim_gate.reserve(
        ("narration.segment_render", "narration.voice_preview")
    )
    permit.settle("narration.segment_render")
    paused = client.get(_claim_gate_path(), headers=headers)
    assert paused.status_code == 200
    assert paused.json()["state"] == "paused"
    assert paused.json()["claimed_count"] == 1
    assert paused.json()["remaining_count"] == 0

    wrong_run = client.post(
        f"{_claim_gate_path()}/release",
        headers=headers,
        json={"run_id": str(uuid4())},
    )
    assert wrong_run.status_code == 409
    assert wrong_run.json()["detail"]["code"] == (
        "TTS_VALIDATION_CLAIM_GATE_BINDING_MISMATCH"
    )
    released = client.post(
        f"{_claim_gate_path()}/release",
        headers=headers,
        json={"run_id": str(run_id)},
    )
    assert released.status_code == 200
    assert released.json()["code"] == "VALIDATION_SEGMENT_CLAIM_GATE_RELEASED"
    assert released.json()["state"] == "default_allow"
    assert client.get(_claim_gate_path(), headers=headers).json()["claim_limit"] == 0
    assert not any(
        "narration-validation-segment-claim-gate" in path
        for path in client.get("/openapi.json").json()["paths"]
    )


@pytest.mark.parametrize(
    ("headers", "novel_id", "document_id"),
    [
        ({}, NOVEL_ID, DOCUMENT_ID),
        ({release_gate.VALIDATION_TOKEN_HEADER: "wrong"}, NOVEL_ID, DOCUMENT_ID),
        ({release_gate.VALIDATION_TOKEN_HEADER: TOKEN}, uuid4(), DOCUMENT_ID),
        ({release_gate.VALIDATION_TOKEN_HEADER: TOKEN}, NOVEL_ID, uuid4()),
    ],
)
def test_hidden_claim_gate_rejects_wrong_token_or_scope(
    monkeypatch: pytest.MonkeyPatch,
    headers: dict[str, str],
    novel_id: UUID,
    document_id: UUID,
) -> None:
    response = _client(monkeypatch, _Adapter()).post(
        _claim_gate_path(novel_id=novel_id, document_id=document_id),
        headers=headers,
        json={"run_id": "7a000000-0000-4000-8000-000000000003"},
    )
    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"
    assert production_runtime._validation_segment_claim_gate.snapshot().state == (
        "default_allow"
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"run_id": "7A000000-0000-4000-8000-000000000003"},
        {"run_id": "7a000000-0000-4000-8000-000000000003", "ttl_seconds": 0},
        {"run_id": "7a000000-0000-4000-8000-000000000003", "ttl_seconds": 301},
        {"run_id": "7a000000-0000-4000-8000-000000000003", "segment_claim_limit": 0},
    ],
)
def test_hidden_claim_gate_rejects_noncanonical_run_or_invalid_bounds(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
) -> None:
    response = _client(monkeypatch, _Adapter()).post(
        _claim_gate_path(),
        headers={release_gate.VALIDATION_TOKEN_HEADER: TOKEN},
        json=payload,
    )
    assert response.status_code == 422
    assert production_runtime._validation_segment_claim_gate.snapshot().state == (
        "default_allow"
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"model_ready": 1},
        {"worker_ready": 1},
        {"active_syntheses": True},
        {"active_syntheses": 2},
        {"queued_jobs": False},
        {"queued_jobs": 1},
    ],
)
def test_sidecar_metric_projection_rejects_non_exact_values(
    changes: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "model_ready": True,
        "worker_ready": True,
        "active_syntheses": 0,
        "queued_jobs": 0,
    }
    values.update(changes)

    with pytest.raises(ContractError):
        SidecarValidationMetrics(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {release_gate.VALIDATION_TOKEN_HEADER: "wrong"},
        [
            (release_gate.VALIDATION_TOKEN_HEADER, TOKEN),
            (release_gate.VALIDATION_TOKEN_HEADER, TOKEN),
        ],
    ],
)
def test_missing_wrong_or_duplicate_validation_token_is_hidden(
    monkeypatch: pytest.MonkeyPatch,
    headers: object,
) -> None:
    adapter = _Adapter()
    response = _client(monkeypatch, adapter).get(_path(), headers=headers)  # type: ignore[arg-type]

    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["detail"]["code"] == "RESOURCE_NOT_FOUND"
    assert adapter.calls == 0


@pytest.mark.parametrize(
    ("novel_id", "document_id"),
    [
        (uuid4(), DOCUMENT_ID),
        (NOVEL_ID, uuid4()),
        (uuid4(), uuid4()),
    ],
)
def test_cross_scope_novel_or_document_is_hidden(
    monkeypatch: pytest.MonkeyPatch,
    novel_id: UUID,
    document_id: UUID,
) -> None:
    adapter = _Adapter()
    response = _client(monkeypatch, adapter).get(
        _path(novel_id=novel_id, document_id=document_id),
        headers={release_gate.VALIDATION_TOKEN_HEADER: TOKEN},
    )

    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"
    assert adapter.calls == 0


def test_expired_validation_scope_is_hidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _Adapter()
    client = _client(monkeypatch, adapter)
    monkeypatch.setattr(
        health_api,
        "current_validation_runtime_scope",
        lambda: _scope(expired=True),
    )

    response = client.get(
        _path(),
        headers={release_gate.VALIDATION_TOKEN_HEADER: TOKEN},
    )

    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"
    assert adapter.calls == 0
    claim_gate = client.get(
        _claim_gate_path(),
        headers={release_gate.VALIDATION_TOKEN_HEADER: TOKEN},
    )
    assert claim_gate.status_code == 404
    assert claim_gate.headers["cache-control"] == "no-store"


def test_released_product_mode_does_not_gain_observation_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _Adapter()
    client = _client(monkeypatch, adapter)
    monkeypatch.setenv(health_api.PRODUCT_ENABLE_ENV, "true")
    monkeypatch.setenv(health_api.VALIDATION_ENABLE_ENV, "false")

    response = client.get(
        _path(),
        headers={release_gate.VALIDATION_TOKEN_HEADER: TOKEN},
    )

    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"
    assert adapter.calls == 0

    malformed = client.get(
        "/novels/not-a-uuid/documents/not-a-uuid/narration-validation-observation",
        headers={release_gate.VALIDATION_TOKEN_HEADER: TOKEN},
    )
    assert malformed.status_code == 404
    assert malformed.headers["cache-control"] == "no-store"
    claim_gate = client.get(
        _claim_gate_path(),
        headers={release_gate.VALIDATION_TOKEN_HEADER: TOKEN},
    )
    assert claim_gate.status_code == 404
    assert claim_gate.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("adapter", [None, _Adapter(failure=True)])
def test_unavailable_private_observation_is_redacted_and_not_cached(
    monkeypatch: pytest.MonkeyPatch,
    adapter: _Adapter | None,
) -> None:
    response = _client(monkeypatch, adapter).get(
        _path(),
        headers={release_gate.VALIDATION_TOKEN_HEADER: TOKEN},
    )

    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "detail": {
            "code": "VALIDATION_OBSERVATION_UNAVAILABLE",
            "message": "朗读验证观测暂不可用。",
        }
    }
    assert "private token path prompt audio body" not in response.text
