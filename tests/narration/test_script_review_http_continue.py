from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session

from backend.models import (
    NarrationEdition,
    NarrationRequest,
    NarrationScriptReviewActionRecord,
    NarrationScriptVersion,
)
from backend.narration import narration_api, script_api
from backend.narration.script_backend import SqlAlchemyScriptApiBackend
from tests.narration.test_domain_services import MemoryNarrationStore
from tests.narration.test_edition_service import (
    POLICY,
    MemoryRenderQueue,
    _workflow_seed,
)


START_KEY = "http-review-start-0001"
PATCH_KEY = "http-review-patch-0001"
APPROVE_KEY = "http-review-approve-0001"


@dataclass
class HttpReviewHarness:
    client: TestClient
    store: MemoryNarrationStore
    queue: MemoryRenderQueue
    document_id: str
    source_hash: str
    policy_mode: list[str]
    queue_mode: list[str]


class _TransactionalMemorySession(Session):
    """Give the shared MemoryNarrationStore real rollback-shaped semantics."""

    def __init__(self, store: MemoryNarrationStore) -> None:
        super().__init__()
        self._memory_store = store

    @contextmanager
    def begin(self, nested: bool = False):  # type: ignore[no-untyped-def, override]
        checkpoint = (
            deepcopy(self._memory_store.rows),
            self._memory_store.flush_count,
            deepcopy(self._memory_store.resource_fences),
        )
        try:
            with super().begin(nested=nested) as transaction:
                yield transaction
        except BaseException:
            (
                self._memory_store.rows,
                self._memory_store.flush_count,
                self._memory_store.resource_fences,
            ) = checkpoint
            raise


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Iterator[HttpReviewHarness]:
    store, _novel, document, revision, _seed_request, _command = _workflow_seed()
    queue = MemoryRenderQueue(store)
    policy_mode = ["valid"]
    queue_mode = ["valid"]

    def production_policy_provider():  # type: ignore[no-untyped-def]
        if policy_mode[0] == "raise":
            raise RuntimeError("secret-provider-dsn=postgresql://hidden")
        if policy_mode[0] == "wrong-type":
            return {"secret-provider-token": "hidden"}
        return POLICY

    def queue_factory(_session: Session):  # type: ignore[no-untyped-def]
        if queue_mode[0] == "factory-raise":
            raise RuntimeError("secret-queue-endpoint=https://hidden.invalid")
        if queue_mode[0] == "malformed":
            return object()
        queue.fail = queue_mode[0] == "enqueue-raise"
        return queue

    def script_backend_factory(session: Session) -> SqlAlchemyScriptApiBackend:
        backend = SqlAlchemyScriptApiBackend(
            session,
            production_policy_provider=(
                None if policy_mode[0] == "none" else production_policy_provider
            ),
            queue_factory=queue_factory,
        )
        backend.store = store  # type: ignore[assignment]
        return backend

    def production_backend_factory(
        session: Session,
    ) -> narration_api.SqlAlchemyNarrationProductionBackend:
        backend = narration_api.SqlAlchemyNarrationProductionBackend(session, POLICY)
        backend._service.store = store  # type: ignore[assignment]
        backend._service.queue = queue  # type: ignore[assignment]
        return backend

    def memory_session() -> Iterator[Session]:
        session = _TransactionalMemorySession(store)
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr(script_api, "get_session", memory_session)
    monkeypatch.setattr(narration_api, "get_session", memory_session)
    script_api.uninstall_script_api_backend_factory()
    narration_api.uninstall_narration_production_backend_factory()
    script_api.install_script_api_backend_factory(script_backend_factory)
    narration_api.install_narration_production_backend_factory(
        production_backend_factory
    )
    app = FastAPI()
    app.dependency_overrides[
        narration_api.require_narration_t4_http_access
    ] = lambda: None
    app.include_router(narration_api.router)
    app.include_router(script_api.router)
    client = TestClient(app, raise_server_exceptions=False)
    try:
        yield HttpReviewHarness(
            client=client,
            store=store,
            queue=queue,
            document_id=str(document.id),
            source_hash=revision.content_hash,
            policy_mode=policy_mode,
            queue_mode=queue_mode,
        )
    finally:
        client.close()
        script_api.uninstall_script_api_backend_factory(script_backend_factory)
        narration_api.uninstall_narration_production_backend_factory(
            production_backend_factory
        )


def _start_always_review(
    harness: HttpReviewHarness,
) -> tuple[dict[str, Any], dict[str, Any]]:
    response = harness.client.post(
        f"/documents/{harness.document_id}/narration-requests",
        headers={"Idempotency-Key": START_KEY},
        json={
            "intent": "create",
            "expected_draft_version": 7,
            "expected_content_hash": harness.source_hash,
            "expected_settings_version": 1,
            "force_review": True,
        },
    )
    assert response.status_code == 202, response.text
    workflow = response.json()
    assert workflow["workflow_state"] == "review_required"
    assert workflow["edition_id"] is None
    assert workflow["script_version_id"] is not None
    assert workflow["blocker_count"] == 0

    review_response = harness.client.get(
        f"/narration-script-versions/{workflow['script_version_id']}"
    )
    assert review_response.status_code == 200, review_response.text
    review = review_response.json()
    assert review["state"] == "review_required"
    assert review["effective_policy"] == "always_review"
    assert {"approve", "edit_segment"}.issubset(review["allowed_actions"])
    assert review["approval"] is None
    assert review["segments"]
    assert harness.store.find_all(
        NarrationEdition,
        request_id=UUID(workflow["request_id"]),
    ) == []
    return workflow, review


def _patch_body(
    workflow: dict[str, Any],
    review: dict[str, Any],
    *,
    spoken_text: str | None = None,
) -> dict[str, Any]:
    segment = review["segments"][0]
    return {
        "request_id": workflow["request_id"],
        "expected_request_version": workflow["request_version"],
        "expected_version_number": review["version_number"],
        "expected_immutable_hash": review["immutable_hash"],
        "expected_local_hash": segment["local_hash"],
        "speaker_kind": "narrator",
        "speaker_label": "客户端显示旁白",
        "character_id": None,
        "anonymous_speaker_id": None,
        "group_key": None,
        "spoken_text": spoken_text or f"{segment['spoken_text']}（作者确认）",
        "reason": "作者通过章节复核确认说话人与朗读文本",
    }


def _patch_review(
    harness: HttpReviewHarness,
    workflow: dict[str, Any],
    review: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    body = _patch_body(workflow, review)
    response = harness.client.patch(
        (
            f"/narration-script-versions/{review['script_version_id']}"
            f"/segments/{review['segments'][0]['segment_id']}"
        ),
        headers={"Idempotency-Key": PATCH_KEY},
        json=body,
    )
    assert response.status_code == 201, response.text
    child = response.json()
    assert child["script_version_id"] != review["script_version_id"]
    assert child["version_number"] == review["version_number"] + 1
    assert child["state"] == "review_required"
    assert child["segments"][0]["spoken_text"] == body["spoken_text"]
    assert child["segments"][0]["speaker_kind"] == "narrator"
    assert child["segments"][0]["speaker_label"] == "旁白"

    current_response = harness.client.get(
        f"/narration-requests/{workflow['request_id']}"
    )
    assert current_response.status_code == 200, current_response.text
    current = current_response.json()
    assert current["request_id"] == workflow["request_id"]
    assert current["script_version_id"] == child["script_version_id"]
    assert current["request_version"] > workflow["request_version"]
    assert current["workflow_state"] == "review_required"
    assert current["edition_id"] is None
    return child, current, body


def _approve_body(
    workflow: dict[str, Any],
    review: dict[str, Any],
) -> dict[str, Any]:
    return {
        "request_id": workflow["request_id"],
        "expected_request_version": workflow["request_version"],
        "expected_version_number": review["version_number"],
        "expected_immutable_hash": review["immutable_hash"],
        "source_revision_id": review["revision_id"],
        "confirmed": True,
    }


def _graph_snapshot(store: MemoryNarrationStore) -> tuple[object, ...]:
    rows = tuple(
        (
            f"{model.__module__}.{model.__qualname__}",
            tuple(
                deepcopy(
                    {
                        key: value
                        for key, value in row.__dict__.items()
                        if key != "_sa_instance_state"
                    }
                )
                for row in model_rows
            ),
        )
        for model, model_rows in sorted(
            store.rows.items(),
            key=lambda item: (item[0].__module__, item[0].__qualname__),
        )
        if model_rows
    )
    return rows, deepcopy(store.resource_fences)


def _set_dependency_modes(
    harness: HttpReviewHarness,
    *,
    policy: str = "valid",
    queue: str = "valid",
) -> None:
    harness.policy_mode[0] = policy
    harness.queue_mode[0] = queue
    harness.queue.fail = queue == "enqueue-raise"


def _assert_sanitized_storage_unavailable(response: Any) -> None:
    assert response.status_code == 503, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "detail": {
            "contract_version": "narration-script-review-api/1",
            "code": "STORAGE_UNAVAILABLE",
            "message": "朗读脚本数据库当前不可用。",
            "retryable": True,
            "field": None,
            "current_version": None,
        }
    }
    leaked = response.text.lower()
    for internal_detail in (
        "secret-provider",
        "secret-queue",
        "postgresql://hidden",
        "hidden.invalid",
        "injected queue failure",
    ):
        assert internal_detail not in leaked


def _assert_review_graph_is_pending(
    harness: HttpReviewHarness,
    *,
    request_id: str,
    script_version_id: str,
) -> None:
    request = harness.store.get(NarrationRequest, UUID(request_id))
    version = harness.store.get(
        NarrationScriptVersion,
        UUID(script_version_id),
    )
    assert request is not None and version is not None
    assert request.state == "review_required"
    assert str(request.current_review_version_id) == script_version_id
    assert version.state == "review_required"
    assert harness.store.find_all(
        NarrationEdition,
        request_id=request.id,
    ) == []


def _immutable_script_resource(resource: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(resource)
    result.pop("allowed_actions", None)
    for segment in result["segments"]:
        segment.pop("allowed_actions", None)
        segment.pop("editable", None)
    return result
    assert harness.store.find_all(
        NarrationScriptReviewActionRecord,
        request_id=request.id,
        action_kind="approve",
    ) == []


def test_http_manual_correction_approval_continues_same_request_to_real_edition(
    harness: HttpReviewHarness,
) -> None:
    initial_workflow, parent = _start_always_review(harness)
    child, review_workflow, patch_body = _patch_review(
        harness,
        initial_workflow,
        parent,
    )

    patch_graph = _graph_snapshot(harness.store)
    patch_queue_calls = len(harness.queue.calls)
    patch_replay = harness.client.patch(
        (
            f"/narration-script-versions/{parent['script_version_id']}"
            f"/segments/{parent['segments'][0]['segment_id']}"
        ),
        headers={"Idempotency-Key": PATCH_KEY},
        json=patch_body,
    )
    assert patch_replay.status_code == 201
    assert patch_replay.json() == child
    assert _graph_snapshot(harness.store) == patch_graph
    assert len(harness.queue.calls) == patch_queue_calls == 0

    changed_patch = harness.client.patch(
        (
            f"/narration-script-versions/{parent['script_version_id']}"
            f"/segments/{parent['segments'][0]['segment_id']}"
        ),
        headers={"Idempotency-Key": PATCH_KEY},
        json={**patch_body, "spoken_text": "同一幂等键下的另一份文本"},
    )
    assert changed_patch.status_code == 409
    assert changed_patch.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert _graph_snapshot(harness.store) == patch_graph

    approval_body = _approve_body(review_workflow, child)
    approval_response = harness.client.post(
        f"/narration-script-versions/{child['script_version_id']}/approve",
        headers={"Idempotency-Key": APPROVE_KEY},
        json=approval_body,
    )
    assert approval_response.status_code == 200, approval_response.text
    approved = approval_response.json()
    assert approved["state"] == "approved"
    assert approved["script_version_id"] == child["script_version_id"]
    assert approved["approval"] == {
        "kind": "manual_after_review",
        "request_id": initial_workflow["request_id"],
        "actor_type": "owner",
        "actor_id": "owner",
        "approved_at": approved["approval"]["approved_at"],
    }
    assert "edition_id" not in approved

    workflow_response = harness.client.get(
        f"/narration-requests/{initial_workflow['request_id']}"
    )
    assert workflow_response.status_code == 200, workflow_response.text
    workflow = workflow_response.json()
    assert workflow["request_id"] == initial_workflow["request_id"]
    assert workflow["script_version_id"] == approved["script_version_id"]
    assert workflow["workflow_state"] in {
        "queued",
        "rendering",
        "partial_ready",
        "ready",
    }
    assert workflow["edition_id"] is not None

    editions = harness.store.find_all(
        NarrationEdition,
        request_id=UUID(initial_workflow["request_id"]),
    )
    assert len(editions) == 1
    assert str(editions[0].id) == workflow["edition_id"]
    assert str(editions[0].script_version_id) == approved["script_version_id"]
    approval_actions = harness.store.find_all(
        NarrationScriptReviewActionRecord,
        request_id=editions[0].request_id,
        action_kind="approve",
    )
    assert len(approval_actions) == 1
    assert approval_actions[0].result_edition_id == editions[0].id
    edition_response = harness.client.get(
        f"/narration-editions/{workflow['edition_id']}"
    )
    assert edition_response.status_code == 200, edition_response.text
    edition = edition_response.json()
    assert edition["edition_id"] == workflow["edition_id"]
    assert edition["request_id"] == initial_workflow["request_id"]
    assert edition["script_version_id"] == approved["script_version_id"]
    assert set(edition["job_ids"]) == set(workflow["job_ids"])

    approval_graph = _graph_snapshot(harness.store)
    approval_queue_calls = len(harness.queue.calls)
    approval_replay = harness.client.post(
        f"/narration-script-versions/{child['script_version_id']}/approve",
        headers={"Idempotency-Key": APPROVE_KEY},
        json=approval_body,
    )
    assert approval_replay.status_code == 200
    assert approval_replay.json() == approved
    assert _graph_snapshot(harness.store) == approval_graph
    assert len(harness.queue.calls) == approval_queue_calls

    changed_approval = harness.client.post(
        f"/narration-script-versions/{child['script_version_id']}/approve",
        headers={"Idempotency-Key": APPROVE_KEY},
        json={
            **approval_body,
            "expected_request_version": approval_body["expected_request_version"] + 1,
        },
    )
    assert changed_approval.status_code == 409
    assert changed_approval.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert "edition_id" not in changed_approval.json()
    assert _graph_snapshot(harness.store) == approval_graph
    assert len(harness.queue.calls) == approval_queue_calls


@pytest.mark.parametrize(
    "policy_mode",
    ["none", "raise", "wrong-type"],
    ids=["provider-none", "provider-raises", "provider-wrong-type"],
)
def test_http_new_patch_dependency_fault_is_sanitized_and_zero_write(
    harness: HttpReviewHarness,
    policy_mode: str,
) -> None:
    workflow, review = _start_always_review(harness)
    before = _graph_snapshot(harness.store)
    queue_calls = len(harness.queue.calls)
    _set_dependency_modes(harness, policy=policy_mode)

    response = harness.client.patch(
        (
            f"/narration-script-versions/{review['script_version_id']}"
            f"/segments/{review['segments'][0]['segment_id']}"
        ),
        headers={"Idempotency-Key": PATCH_KEY},
        json=_patch_body(workflow, review),
    )

    _assert_sanitized_storage_unavailable(response)
    assert _graph_snapshot(harness.store) == before
    assert len(harness.queue.calls) == queue_calls == 0
    _assert_review_graph_is_pending(
        harness,
        request_id=workflow["request_id"],
        script_version_id=review["script_version_id"],
    )


@pytest.mark.parametrize(
    "policy_mode",
    ["none", "raise", "wrong-type"],
    ids=["provider-none", "provider-raises", "provider-wrong-type"],
)
def test_http_new_approval_policy_fault_cannot_freeze_or_forge_edition(
    harness: HttpReviewHarness,
    policy_mode: str,
) -> None:
    workflow, parent = _start_always_review(harness)
    child, review_workflow, _patch = _patch_review(harness, workflow, parent)
    before = _graph_snapshot(harness.store)
    queue_calls = len(harness.queue.calls)
    _set_dependency_modes(harness, policy=policy_mode)

    response = harness.client.post(
        f"/narration-script-versions/{child['script_version_id']}/approve",
        headers={"Idempotency-Key": APPROVE_KEY},
        json=_approve_body(review_workflow, child),
    )

    _assert_sanitized_storage_unavailable(response)
    assert _graph_snapshot(harness.store) == before
    assert len(harness.queue.calls) == queue_calls == 0
    _assert_review_graph_is_pending(
        harness,
        request_id=workflow["request_id"],
        script_version_id=child["script_version_id"],
    )


@pytest.mark.parametrize(
    "queue_mode",
    ["factory-raise", "malformed", "enqueue-raise"],
    ids=["factory-raises", "malformed-queue", "enqueue-runtime-error"],
)
def test_http_new_approval_queue_fault_is_sanitized_and_zero_write(
    harness: HttpReviewHarness,
    queue_mode: str,
) -> None:
    workflow, parent = _start_always_review(harness)
    child, review_workflow, _patch = _patch_review(harness, workflow, parent)
    before = _graph_snapshot(harness.store)
    queue_calls = len(harness.queue.calls)
    _set_dependency_modes(harness, queue=queue_mode)

    response = harness.client.post(
        f"/narration-script-versions/{child['script_version_id']}/approve",
        headers={"Idempotency-Key": APPROVE_KEY},
        json=_approve_body(review_workflow, child),
    )

    _assert_sanitized_storage_unavailable(response)
    assert _graph_snapshot(harness.store) == before
    expected_attempts = 1 if queue_mode == "enqueue-raise" else 0
    assert len(harness.queue.calls) == queue_calls + expected_attempts
    _assert_review_graph_is_pending(
        harness,
        request_id=workflow["request_id"],
        script_version_id=child["script_version_id"],
    )


@pytest.mark.parametrize(
    "policy_mode",
    ["none", "raise", "wrong-type"],
    ids=["provider-none", "provider-raises", "provider-wrong-type"],
)
def test_http_existing_patch_replay_ignores_broken_runtime_dependencies(
    harness: HttpReviewHarness,
    policy_mode: str,
) -> None:
    workflow, parent = _start_always_review(harness)
    child, _review_workflow, patch_body = _patch_review(
        harness,
        workflow,
        parent,
    )
    before = _graph_snapshot(harness.store)
    queue_calls = len(harness.queue.calls)
    _set_dependency_modes(
        harness,
        policy=policy_mode,
        queue="factory-raise",
    )

    replay = harness.client.patch(
        (
            f"/narration-script-versions/{parent['script_version_id']}"
            f"/segments/{parent['segments'][0]['segment_id']}"
        ),
        headers={"Idempotency-Key": PATCH_KEY},
        json=patch_body,
    )

    assert replay.status_code == 201, replay.text
    replayed_child = replay.json()
    assert _immutable_script_resource(replayed_child) == _immutable_script_resource(
        child
    )
    assert replayed_child["allowed_actions"] == []
    assert _graph_snapshot(harness.store) == before
    assert len(harness.queue.calls) == queue_calls == 0


@pytest.mark.parametrize(
    ("policy_mode", "queue_mode"),
    [
        ("none", "factory-raise"),
        ("raise", "malformed"),
        ("wrong-type", "enqueue-raise"),
    ],
    ids=[
        "provider-none-and-factory-raises",
        "provider-raises-and-malformed-queue",
        "provider-wrong-type-and-enqueue-would-raise",
    ],
)
def test_http_existing_approval_replay_ignores_broken_runtime_dependencies(
    harness: HttpReviewHarness,
    policy_mode: str,
    queue_mode: str,
) -> None:
    workflow, parent = _start_always_review(harness)
    child, review_workflow, _patch = _patch_review(harness, workflow, parent)
    approval_body = _approve_body(review_workflow, child)
    first = harness.client.post(
        f"/narration-script-versions/{child['script_version_id']}/approve",
        headers={"Idempotency-Key": APPROVE_KEY},
        json=approval_body,
    )
    assert first.status_code == 200, first.text
    approved = first.json()
    assert approved["state"] == "approved"
    before = _graph_snapshot(harness.store)
    queue_calls = len(harness.queue.calls)
    _set_dependency_modes(
        harness,
        policy=policy_mode,
        queue=queue_mode,
    )

    replay = harness.client.post(
        f"/narration-script-versions/{child['script_version_id']}/approve",
        headers={"Idempotency-Key": APPROVE_KEY},
        json=approval_body,
    )

    assert replay.status_code == 200, replay.text
    assert replay.json() == approved
    assert _graph_snapshot(harness.store) == before
    assert len(harness.queue.calls) == queue_calls
