from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session

from backend.narration import narration_api
from backend.narration.failed_segment_retry import (
    FailedSegmentRetryCommandResult,
    FailedSegmentRetryItem,
)
from backend.narration.services import (
    IdempotencyConflict,
    InvalidNarrationState,
    NarrationCasConflict,
    NarrationScopeMismatch,
    StaleNarrationInput,
    VoiceRightsUnavailable,
)


DOCUMENT_ID = UUID("d4000000-0000-4000-8000-000000000001")
REQUEST_ID = UUID("d4000000-0000-4000-8000-000000000002")
REVISION_ID = UUID("d4000000-0000-4000-8000-000000000003")
SCRIPT_VERSION_ID = UUID("d4000000-0000-4000-8000-000000000004")
EDITION_ID = UUID("d4000000-0000-4000-8000-000000000005")
NOVEL_ID = UUID("d4000000-0000-4000-8000-000000000006")
JOB_ID = UUID("d4000000-0000-4000-8000-000000000007")
HISTORICAL_EDITION_ID = UUID("d4000000-0000-4000-8000-000000000008")
HISTORICAL_REQUEST_ID = UUID("d4000000-0000-4000-8000-000000000009")
HISTORICAL_REVISION_ID = UUID("d4000000-0000-4000-8000-000000000010")
START_SEGMENT_ID = UUID("d4000000-0000-4000-8000-000000000011")
PLAYBACK_PROGRESS_ID = UUID("d4000000-0000-4000-8000-000000000012")
OTHER_DOCUMENT_ID = UUID("d4000000-0000-4000-8000-000000000013")
FAILED_SEGMENT_ID = UUID("d4000000-0000-4000-8000-000000000014")
FANOUT_SEGMENT_ID = UUID("d4000000-0000-4000-8000-000000000015")
RETRY_COMMAND_ID = UUID("d4000000-0000-4000-8000-000000000016")
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _workflow(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "contract_version": narration_api.NARRATION_PRODUCTION_API_VERSION,
        "request_id": str(REQUEST_ID),
        "intent": "create",
        "request_version": 4,
        "workflow_state": "queued",
        "source_revision_id": str(REVISION_ID),
        "source_content_hash": SHA_A,
        "settings_fingerprint": SHA_B,
        "warning_count": 0,
        "blocker_count": 0,
        "script_version_id": str(SCRIPT_VERSION_ID),
        "edition_id": str(EDITION_ID),
        "current_manifest_revision": None,
        "job_ids": [str(JOB_ID)],
        "replayed": False,
    }
    payload.update(changes)
    return payload


def _edition(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "contract_version": narration_api.NARRATION_PRODUCTION_API_VERSION,
        "edition_id": str(EDITION_ID),
        "request_id": str(REQUEST_ID),
        "novel_id": str(NOVEL_ID),
        "document_id": str(DOCUMENT_ID),
        "script_version_id": str(SCRIPT_VERSION_ID),
        "settings_fingerprint": SHA_B,
        "edition_fingerprint": SHA_C,
        "state": "created",
        "segment_count": 1,
        "pending_segment_count": 0,
        "queued_segment_count": 1,
        "rendering_segment_count": 0,
        "ready_segment_count": 0,
        "failed_segment_count": 0,
        "current_manifest_revision": None,
        "job_ids": [str(JOB_ID)],
    }
    payload.update(changes)
    return payload


def _document_context(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "contract_version": "document-narration-context/1",
        "document_id": str(DOCUMENT_ID),
        "novel_id": str(NOVEL_ID),
        "pointer_version": 4,
        "current_script_version_id": str(SCRIPT_VERSION_ID),
        "current_edition_id": str(EDITION_ID),
        "active_edition_id": str(HISTORICAL_EDITION_ID),
        "active_is_current": False,
        "working_copy_draft_version": 7,
        "working_copy_content_hash": SHA_A,
        "source_snapshot": {
            "revision_id": str(HISTORICAL_REVISION_ID),
            "content_hash": SHA_A,
            "matches_working_copy": True,
        },
        "compatibility": "superseded",
        "source_notice_code": "HISTORICAL_EDITION",
        "editor_timeline_mode": "exact_working_copy",
        "old_draft_subtitle_required": False,
        "explicit_update_required": True,
        "can_request_update": True,
        "available_current_source_edition_ids": [str(HISTORICAL_EDITION_ID)],
        "edition_history": {
            "contract_version": "narration-edition-history/1",
            "document_id": str(DOCUMENT_ID),
            "pointer_version": 4,
            "current_edition_id": str(EDITION_ID),
            "working_copy_content_hash": SHA_A,
            "working_copy_draft_version": 7,
            "editions": [
                {
                    "edition_id": str(EDITION_ID),
                    "request_id": str(REQUEST_ID),
                    "source_revision_id": str(REVISION_ID),
                    "source_content_hash": SHA_B,
                    "edition_fingerprint": SHA_B,
                    "state": "ready",
                    "created_at": None,
                    "manifest_revision": 6,
                    "manifest_etag": '"' + SHA_B + '"',
                    "ready_segment_count": 3,
                    "total_segment_count": 3,
                    "is_current": True,
                    "source_status": "working_copy_diverged",
                    "rights_available": True,
                    "playable": True,
                    "default_start_ready": True,
                    "resume_available": False,
                    "switch_allowed": False,
                },
                {
                    "edition_id": str(HISTORICAL_EDITION_ID),
                    "request_id": str(HISTORICAL_REQUEST_ID),
                    "source_revision_id": str(HISTORICAL_REVISION_ID),
                    "source_content_hash": SHA_A,
                    "edition_fingerprint": SHA_C,
                    "state": "ready",
                    "created_at": None,
                    "manifest_revision": 7,
                    "manifest_etag": '"' + SHA_C + '"',
                    "ready_segment_count": 4,
                    "total_segment_count": 4,
                    "is_current": False,
                    "source_status": "current",
                    "rights_available": True,
                    "playable": True,
                    "default_start_ready": True,
                    "resume_available": True,
                    "switch_allowed": True,
                },
            ],
        },
    }
    payload.update(changes)
    return payload


def _edition_switch(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "contract_version": "document-narration-context/1",
        "document_id": str(DOCUMENT_ID),
        "current_edition_id": str(HISTORICAL_EDITION_ID),
        "pointer_version": 5,
        "switch_mode": "immediate",
        "start_segment_id": str(START_SEGMENT_ID),
        "manifest_revision": 7,
        "playback_progress_id": str(PLAYBACK_PROGRESS_ID),
    }
    payload.update(changes)
    return payload


def _failed_segments(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "contract_version": "narration-failed-segment-retry/1",
        "edition_id": str(EDITION_ID),
        "request_id": str(REQUEST_ID),
        "request_version": 4,
        "manifest_revision": 7,
        "request_state": "partial_ready",
        "edition_state": "partial_ready",
        "items": [
            {
                "segment_id": str(FAILED_SEGMENT_ID),
                "ordinal": 3,
                "failure_code": "LEASE_EXPIRED",
                "retryable": True,
                "retry_reason_code": None,
                "job_id": str(JOB_ID),
                "fanout_segment_ids": [
                    str(FAILED_SEGMENT_ID),
                    str(FANOUT_SEGMENT_ID),
                ],
            }
        ],
    }
    payload.update(changes)
    return payload


def _retry_failed_segments(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "contract_version": "narration-failed-segment-retry/1",
        "edition_id": str(EDITION_ID),
        "request_id": str(REQUEST_ID),
        "accepted_segment_ids": [str(FAILED_SEGMENT_ID)],
        "affected_segment_ids": [
            str(FAILED_SEGMENT_ID),
            str(FANOUT_SEGMENT_ID),
        ],
        "commands": [
            {
                "command_id": str(RETRY_COMMAND_ID),
                "job_id": str(JOB_ID),
                "affected_segment_ids": [
                    str(FAILED_SEGMENT_ID),
                    str(FANOUT_SEGMENT_ID),
                ],
            }
        ],
        "request_version": 5,
        "request_state": "partial_ready",
        "edition_state": "partial_ready",
        "replayed": False,
    }
    payload.update(changes)
    return payload


@dataclass
class Backend:
    result: object = field(default_factory=_workflow)
    commands: list[narration_api.NarrationProductionApiCommand] = field(
        default_factory=list
    )
    failure: Exception | None = None

    def dispatch(
        self,
        command: narration_api.NarrationProductionApiCommand,
    ) -> object:
        self.commands.append(command)
        if self.failure is not None:
            raise self.failure
        return self.result


@pytest.fixture(autouse=True)
def _reset_backend(monkeypatch: pytest.MonkeyPatch) -> Any:
    def test_session():  # type: ignore[no-untyped-def]
        with Session() as session:
            yield session

    monkeypatch.setattr(narration_api, "get_session", test_session)
    narration_api.uninstall_narration_production_backend_factory()
    yield
    narration_api.uninstall_narration_production_backend_factory()


def _client(backend: Backend | None = None) -> TestClient:
    if backend is not None:
        factory = lambda _session: backend
        narration_api.install_narration_production_backend_factory(factory)
    app = FastAPI()
    app.dependency_overrides[
        narration_api.require_narration_t4_http_access
    ] = lambda: None
    app.include_router(narration_api.router)
    return TestClient(app, raise_server_exceptions=False)


def _start_body(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "intent": "create",
        "expected_draft_version": 7,
        "expected_content_hash": SHA_A,
        "expected_settings_version": 3,
        "force_review": False,
    }
    payload.update(changes)
    return payload


def _switch_body(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "target_edition_id": str(HISTORICAL_EDITION_ID),
        "expected_version": 4,
        "switch_mode": "immediate",
        "start_segment_id": str(START_SEGMENT_ID),
        "playback_rate_millis": 1000,
        "confirmed": True,
    }
    payload.update(changes)
    return payload


def _retry_body(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "segment_ids": [str(FAILED_SEGMENT_ID)],
        "expected_request_version": 4,
        "expected_manifest_revision": 7,
    }
    payload.update(changes)
    return payload


def test_routes_fail_closed_until_main_owner_installs_backend() -> None:
    response = _client().get(f"/narration-requests/{REQUEST_ID}")

    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["detail"] == {
        "contract_version": "narration-production-api/1",
        "code": "NARRATION_PRODUCTION_BACKEND_NOT_INSTALLED",
        "message": "朗读生产后端尚未完成应用入口接线。",
        "retryable": False,
        "field": None,
        "current_version": None,
    }


def test_start_dispatches_only_frozen_client_fields() -> None:
    backend = Backend()
    response = _client(backend).post(
        f"/documents/{DOCUMENT_ID}/narration-requests",
        headers={"Idempotency-Key": "narration-create-0001"},
        json=_start_body(),
    )

    assert response.status_code == 202
    assert response.headers["cache-control"] == "no-store"
    command = backend.commands[-1]
    assert command.operation is narration_api.NarrationProductionOperation.START
    assert command.document_id == DOCUMENT_ID
    assert command.idempotency_key == "narration-create-0001"
    assert isinstance(command.payload, narration_api.CreateNarrationWorkflowRequest)
    assert not hasattr(command, "owner_id")
    assert not hasattr(command, "workspace_id")
    assert not hasattr(command.payload, "effective_policy")
    assert not hasattr(command.payload, "tts_fingerprint")


def test_update_http_adapter_derives_explicit_author_action_server_side() -> None:
    captured: list[narration_api.StartNarrationWorkflow] = []

    class CaptureService:
        def start(
            self,
            command: narration_api.StartNarrationWorkflow,
        ) -> narration_api.NarrationWorkflowProjection:
            captured.append(command)
            return narration_api.NarrationWorkflowProjection(
                request_id=REQUEST_ID,
                intent="update",
                request_version=4,
                workflow_state="queued",
                source_revision_id=REVISION_ID,
                source_content_hash=SHA_A,
                settings_fingerprint=SHA_B,
                warning_count=0,
                blocker_count=0,
                script_version_id=SCRIPT_VERSION_ID,
                edition_id=EDITION_ID,
                current_manifest_revision=None,
                job_ids=(JOB_ID,),
                replayed=False,
            )

    with Session() as session:
        adapter = object.__new__(narration_api.SqlAlchemyNarrationProductionBackend)
        adapter._session = session
        adapter._service = CaptureService()
        response = adapter.dispatch(
            narration_api.NarrationProductionApiCommand(
                operation=narration_api.NarrationProductionOperation.START,
                document_id=DOCUMENT_ID,
                idempotency_key="narration-update-explicit-0001",
                payload=narration_api.CreateNarrationWorkflowRequest.model_validate(
                    _start_body(intent="update")
                ),
            )
        )

    assert response["intent"] == "update"
    assert len(captured) == 1
    command = captured[0]
    assert command.intent == "update"
    assert command.explicitly_requested is True
    assert command.actor == "local-owner"


@pytest.mark.parametrize(
    "injected_field",
    [
        "owner_id",
        "workspace_id",
        "effective_policy",
        "approval",
        "tts_fingerprint",
        "voice_rights",
    ],
)
def test_start_rejects_client_authority_injection(injected_field: str) -> None:
    backend = Backend()
    body = _start_body(**{injected_field: "attacker-value"})

    response = _client(backend).post(
        f"/documents/{DOCUMENT_ID}/narration-requests",
        headers={"Idempotency-Key": "narration-injection-0001"},
        json=body,
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "REQUEST_VALIDATION_FAILED"
    assert backend.commands == []


@pytest.mark.parametrize(
    "body",
    [
        _start_body(intent="batch"),
        _start_body(force_review="false"),
        _start_body(expected_draft_version=True),
        _start_body(expected_settings_version=1.0),
        _start_body(expected_content_hash="A" * 64),
    ],
)
def test_start_rejects_hold_intent_and_nonstrict_scalars(
    body: dict[str, object],
) -> None:
    backend = Backend()

    response = _client(backend).post(
        f"/documents/{DOCUMENT_ID}/narration-requests",
        headers={"Idempotency-Key": "narration-invalid-0001"},
        json=body,
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "REQUEST_VALIDATION_FAILED"
    assert backend.commands == []


def test_analyze_only_response_cannot_claim_production_rows() -> None:
    backend = Backend(
        result=_workflow(
            intent="analyze_only",
            workflow_state="analyzed",
            edition_id=str(EDITION_ID),
            job_ids=[str(JOB_ID)],
        )
    )

    response = _client(backend).post(
        f"/documents/{DOCUMENT_ID}/narration-requests",
        headers={"Idempotency-Key": "narration-analyze-0001"},
        json=_start_body(intent="analyze_only"),
    )

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "RESPONSE_CONTRACT_VIOLATION"


def test_recovery_routes_enforce_exact_response_identity() -> None:
    request_backend = Backend()
    request_response = _client(request_backend).get(
        f"/narration-requests/{REQUEST_ID}"
    )
    assert request_response.status_code == 200
    assert request_backend.commands[-1].operation is (
        narration_api.NarrationProductionOperation.GET_REQUEST
    )

    narration_api.uninstall_narration_production_backend_factory()
    edition_backend = Backend(result=_edition())
    edition_response = _client(edition_backend).get(
        f"/narration-editions/{EDITION_ID}"
    )
    assert edition_response.status_code == 200
    assert edition_backend.commands[-1].operation is (
        narration_api.NarrationProductionOperation.GET_EDITION
    )

    narration_api.uninstall_narration_production_backend_factory()
    wrong = Backend(result=_workflow(request_id="e4000000-0000-4000-8000-000000000001"))
    mismatch = _client(wrong).get(f"/narration-requests/{REQUEST_ID}")
    assert mismatch.status_code == 500
    assert mismatch.json()["detail"]["code"] == "RESPONSE_CONTRACT_VIOLATION"


def test_failed_segment_projection_dispatches_strict_read_command() -> None:
    expected = _failed_segments()
    backend = Backend(result=expected)

    response = _client(backend).get(
        f"/narration-editions/{EDITION_ID}/failed-segments"
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == expected
    assert len(backend.commands) == 1
    command = backend.commands[0]
    assert command.operation is (
        narration_api.NarrationProductionOperation.GET_FAILED_SEGMENTS
    )
    assert command.edition_id == EDITION_ID
    assert command.payload is None
    assert command.idempotency_key is None


def test_retry_failed_segments_dispatches_exact_owner_command() -> None:
    expected = _retry_failed_segments()
    backend = Backend(result=expected)

    response = _client(backend).post(
        f"/narration-editions/{EDITION_ID}/retry-failed-segments",
        headers={"Idempotency-Key": "failed-segment-retry-0001"},
        json=_retry_body(),
    )

    assert response.status_code == 202
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == expected
    command = backend.commands[0]
    assert command.operation is (
        narration_api.NarrationProductionOperation.RETRY_FAILED_SEGMENTS
    )
    assert command.edition_id == EDITION_ID
    assert command.idempotency_key == "failed-segment-retry-0001"
    assert isinstance(command.payload, narration_api.RetryFailedSegmentsRequest)
    assert command.payload.segment_ids == [FAILED_SEGMENT_ID]
    assert command.payload.expected_request_version == 4
    assert command.payload.expected_manifest_revision == 7
    assert not hasattr(command.payload, "actor")
    assert not hasattr(command.payload, "owner_id")
    assert not hasattr(command.payload, "workspace_id")


@pytest.mark.parametrize(
    "body",
    [
        _retry_body(segment_ids=[]),
        _retry_body(segment_ids=[str(FAILED_SEGMENT_ID)] * 2),
        _retry_body(segment_ids=[str(uuid4()) for _ in range(101)]),
        _retry_body(expected_request_version=True),
        _retry_body(expected_request_version=0),
        _retry_body(expected_manifest_revision=0),
        _retry_body(actor="attacker"),
        _retry_body(owner_id=str(uuid4())),
    ],
)
def test_retry_failed_segments_rejects_noncanonical_schema(
    body: dict[str, object],
) -> None:
    backend = Backend(result=_retry_failed_segments())

    response = _client(backend).post(
        f"/narration-editions/{EDITION_ID}/retry-failed-segments",
        headers={"Idempotency-Key": "failed-segment-retry-0002"},
        json=body,
    )

    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["detail"]["code"] == "REQUEST_VALIDATION_FAILED"
    assert backend.commands == []


def test_retry_failed_segments_requires_idempotency_header() -> None:
    backend = Backend(result=_retry_failed_segments())

    response = _client(backend).post(
        f"/narration-editions/{EDITION_ID}/retry-failed-segments",
        json=_retry_body(),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "REQUEST_VALIDATION_FAILED"
    assert backend.commands == []


@pytest.mark.parametrize(
    "result",
    [
        _failed_segments(edition_id=str(HISTORICAL_EDITION_ID)),
        _failed_segments(
            items=[
                {
                    **_failed_segments()["items"][0],  # type: ignore[index]
                    "fanout_segment_ids": [str(FANOUT_SEGMENT_ID)],
                }
            ]
        ),
        _retry_failed_segments(edition_id=str(HISTORICAL_EDITION_ID)),
        _retry_failed_segments(accepted_segment_ids=[str(FANOUT_SEGMENT_ID)]),
        _retry_failed_segments(commands=[]),
    ],
)
def test_failed_segment_routes_reject_incoherent_backend_response(
    result: dict[str, object],
) -> None:
    backend = Backend(result=result)
    if "items" in result:
        response = _client(backend).get(
            f"/narration-editions/{EDITION_ID}/failed-segments"
        )
    else:
        response = _client(backend).post(
            f"/narration-editions/{EDITION_ID}/retry-failed-segments",
            headers={"Idempotency-Key": "failed-segment-retry-0003"},
            json=_retry_body(),
        )

    assert response.status_code == 500
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["detail"]["code"] == "RESPONSE_CONTRACT_VIOLATION"


def test_document_playback_context_has_strict_wire_shape_and_active_selection() -> None:
    expected = _document_context()
    backend = Backend(result=expected)

    response = _client(backend).get(
        f"/documents/{DOCUMENT_ID}/narration-playback-context",
        params={"active_edition_id": str(HISTORICAL_EDITION_ID)},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == expected
    assert len(backend.commands) == 1
    command = backend.commands[0]
    assert command.operation is (
        narration_api.NarrationProductionOperation.GET_DOCUMENT_CONTEXT
    )
    assert command.document_id == DOCUMENT_ID
    assert command.active_edition_id == HISTORICAL_EDITION_ID
    assert command.payload is None


def test_immediate_edition_switch_has_strict_wire_shape() -> None:
    expected = _edition_switch()
    backend = Backend(result=expected)

    response = _client(backend).put(
        f"/documents/{DOCUMENT_ID}/current-narration-edition",
        json=_switch_body(),
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == expected
    assert len(backend.commands) == 1
    command = backend.commands[0]
    assert command.operation is (
        narration_api.NarrationProductionOperation.SWITCH_DOCUMENT_EDITION
    )
    assert command.document_id == DOCUMENT_ID
    assert isinstance(command.payload, narration_api.SwitchNarrationEditionRequest)
    assert command.payload.target_edition_id == HISTORICAL_EDITION_ID
    assert command.payload.expected_version == 4
    assert command.payload.switch_mode == "immediate"
    assert command.payload.start_segment_id == START_SEGMENT_ID
    assert command.payload.playback_rate_millis == 1000
    assert command.payload.confirmed is True
    assert not hasattr(command.payload, "profile_id")
    assert not hasattr(command.payload, "actor_id")


def test_switch_adapter_derives_profile_and_actor_inside_one_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    with Session() as session:
        adapter = object.__new__(narration_api.SqlAlchemyNarrationProductionBackend)
        adapter._session = session
        adapter._service = object()

        def fake_switch(_store: object, **values: object) -> object:
            captured.update(values)
            captured["transaction"] = session.get_transaction()
            captured["transaction_active"] = session.in_transaction()
            return narration_api.ExplicitEditionSwitchResult(
                document_id=DOCUMENT_ID,
                current_edition_id=HISTORICAL_EDITION_ID,
                pointer_version=5,
                switch_mode="immediate",
                start_segment_id=START_SEGMENT_ID,
                manifest_revision=7,
                playback_progress_id=PLAYBACK_PROGRESS_ID,
            )

        monkeypatch.setattr(
            narration_api,
            "switch_document_narration_edition_explicitly",
            fake_switch,
        )
        response = adapter.dispatch(
            narration_api.NarrationProductionApiCommand(
                operation=(
                    narration_api.NarrationProductionOperation.SWITCH_DOCUMENT_EDITION
                ),
                document_id=DOCUMENT_ID,
                payload=narration_api.SwitchNarrationEditionRequest.model_validate(
                    _switch_body()
                ),
            )
        )
        assert session.in_transaction() is False

    assert (
        narration_api.SwitchNarrationEditionResource.model_validate(response).model_dump(
            mode="json"
        )
        == _edition_switch()
    )
    assert captured["document_id"] == DOCUMENT_ID
    assert captured["target_edition_id"] == HISTORICAL_EDITION_ID
    assert captured["expected_pointer_version"] == 4
    assert captured["switch_mode"] == "immediate"
    assert captured["start_segment_id"] == START_SEGMENT_ID
    assert captured["profile_id"] == "default"
    assert captured["playback_rate_millis"] == 1000
    assert captured["actor"] == "local-owner"
    assert captured["confirmed"] is True


def test_failed_segment_adapter_uses_read_and_write_transaction_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    with Session() as session:
        adapter = object.__new__(narration_api.SqlAlchemyNarrationProductionBackend)
        adapter._session = session
        adapter._service = object()

        def fake_project(_store: object, **values: object) -> object:
            captured["get_transaction_active"] = session.in_transaction()
            captured.update({f"get_{key}": value for key, value in values.items()})
            return narration_api.FailedSegmentRetryProjection(
                contract_version="narration-failed-segment-retry/1",
                edition_id=EDITION_ID,
                request_id=REQUEST_ID,
                request_version=4,
                manifest_revision=7,
                request_state="partial_ready",
                edition_state="partial_ready",
                items=(
                    FailedSegmentRetryItem(
                        segment_id=FAILED_SEGMENT_ID,
                        ordinal=3,
                        failure_code="LEASE_EXPIRED",
                        retryable=True,
                        retry_reason_code=None,
                        job_id=JOB_ID,
                        fanout_segment_ids=(
                            FAILED_SEGMENT_ID,
                            FANOUT_SEGMENT_ID,
                        ),
                    ),
                ),
            )

        def fake_retry(_session: Session, command: object) -> object:
            captured["post_transaction_active"] = session.in_transaction()
            captured["domain_command"] = command
            return narration_api.RetryFailedSegmentsResult(
                contract_version="narration-failed-segment-retry/1",
                edition_id=EDITION_ID,
                request_id=REQUEST_ID,
                accepted_segment_ids=(FAILED_SEGMENT_ID,),
                affected_segment_ids=(FAILED_SEGMENT_ID, FANOUT_SEGMENT_ID),
                commands=(
                    FailedSegmentRetryCommandResult(
                        command_id=RETRY_COMMAND_ID,
                        job_id=JOB_ID,
                        affected_segment_ids=(
                            FAILED_SEGMENT_ID,
                            FANOUT_SEGMENT_ID,
                        ),
                    ),
                ),
                request_version=5,
                request_state="partial_ready",
                edition_state="partial_ready",
                replayed=False,
            )

        monkeypatch.setattr(
            narration_api,
            "project_failed_segment_retries",
            fake_project,
        )
        monkeypatch.setattr(
            narration_api,
            "retry_failed_segments",
            fake_retry,
        )
        get_result = adapter.dispatch(
            narration_api.NarrationProductionApiCommand(
                operation=narration_api.NarrationProductionOperation.GET_FAILED_SEGMENTS,
                edition_id=EDITION_ID,
            )
        )
        assert session.in_transaction() is False
        post_result = adapter.dispatch(
            narration_api.NarrationProductionApiCommand(
                operation=narration_api.NarrationProductionOperation.RETRY_FAILED_SEGMENTS,
                edition_id=EDITION_ID,
                idempotency_key="failed-segment-retry-transaction-0001",
                payload=narration_api.RetryFailedSegmentsRequest.model_validate(
                    _retry_body()
                ),
            )
        )
        assert session.in_transaction() is False

    assert get_result["edition_id"] == EDITION_ID
    assert post_result["replayed"] is False
    assert captured["get_transaction_active"] is True
    assert captured["get_edition_id"] == EDITION_ID
    assert captured["post_transaction_active"] is True
    command = captured["domain_command"]
    assert isinstance(command, narration_api.RetryFailedSegmentsCommand)
    assert command.segment_ids == (FAILED_SEGMENT_ID,)
    assert command.expected_request_version == 4
    assert command.expected_manifest_revision == 7
    assert command.idempotency_key == "failed-segment-retry-transaction-0001"
    assert command.actor == "local-owner"


def test_failed_segment_write_rolls_back_domain_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with Session() as session:
        adapter = object.__new__(narration_api.SqlAlchemyNarrationProductionBackend)
        adapter._session = session
        adapter._service = object()

        def fail_in_transaction(_session: Session, _command: object) -> object:
            assert session.in_transaction() is True
            raise InvalidNarrationState("retry state changed")

        monkeypatch.setattr(
            narration_api,
            "retry_failed_segments",
            fail_in_transaction,
        )
        with pytest.raises(InvalidNarrationState):
            adapter.dispatch(
                narration_api.NarrationProductionApiCommand(
                    operation=(
                        narration_api.NarrationProductionOperation.RETRY_FAILED_SEGMENTS
                    ),
                    edition_id=EDITION_ID,
                    idempotency_key="failed-segment-retry-rollback-0001",
                    payload=narration_api.RetryFailedSegmentsRequest.model_validate(
                        _retry_body()
                    ),
                )
            )
        assert session.in_transaction() is False


@pytest.mark.parametrize(
    ("failure", "expected_status", "expected_code"),
    [
        (NarrationScopeMismatch("private scope"), 404, "SCOPE_VIOLATION"),
        (NarrationCasConflict("private version"), 409, "VERSION_CONFLICT"),
        (InvalidNarrationState("private state"), 409, "INVALID_STATE"),
        (IdempotencyConflict("private digest"), 409, "IDEMPOTENCY_CONFLICT"),
        (
            VoiceRightsUnavailable("private voice"),
            403,
            "VOICE_RIGHTS_UNAVAILABLE",
        ),
        (
            InvalidNarrationState(
                "failed segment retry is unavailable: VOICE_RIGHTS_UNAVAILABLE"
            ),
            403,
            "VOICE_RIGHTS_UNAVAILABLE",
        ),
    ],
)
def test_failed_segment_retry_maps_domain_failures_without_leaking_details(
    failure: Exception,
    expected_status: int,
    expected_code: str,
) -> None:
    response = _client(Backend(failure=failure)).post(
        f"/narration-editions/{EDITION_ID}/retry-failed-segments",
        headers={"Idempotency-Key": "failed-segment-retry-failure-0001"},
        json=_retry_body(),
    )

    assert response.status_code == expected_status
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["detail"]["code"] == expected_code
    assert "private" not in response.text


def test_next_playback_switch_omits_immediate_start() -> None:
    expected = _edition_switch(
        switch_mode="next_playback",
        start_segment_id=None,
        playback_progress_id=None,
    )
    backend = Backend(result=expected)

    response = _client(backend).put(
        f"/documents/{DOCUMENT_ID}/current-narration-edition",
        json=_switch_body(switch_mode="next_playback", start_segment_id=None),
    )

    assert response.status_code == 200
    assert response.json() == expected
    payload = backend.commands[0].payload
    assert isinstance(payload, narration_api.SwitchNarrationEditionRequest)
    assert payload.switch_mode == "next_playback"
    assert payload.start_segment_id is None


@pytest.mark.parametrize(
    "body",
    [
        _switch_body(switch_mode="next_playback"),
        _switch_body(confirmed=False),
        _switch_body(confirmed=1),
        _switch_body(expected_version=True),
        _switch_body(playback_rate_millis=1000.0),
        _switch_body(profile_id="attacker-profile"),
        _switch_body(actor_id="attacker-actor"),
    ],
)
def test_edition_switch_rejects_ambiguous_modes_and_client_authority(
    body: dict[str, object],
) -> None:
    backend = Backend(result=_edition_switch())

    response = _client(backend).put(
        f"/documents/{DOCUMENT_ID}/current-narration-edition",
        json=body,
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "REQUEST_VALIDATION_FAILED"
    assert backend.commands == []


def test_document_context_and_switch_reject_wrong_response_document() -> None:
    context_backend = Backend(
        result=_document_context(document_id=str(OTHER_DOCUMENT_ID))
    )
    context_response = _client(context_backend).get(
        f"/documents/{DOCUMENT_ID}/narration-playback-context"
    )
    assert context_response.status_code == 500
    assert context_response.json()["detail"]["code"] == (
        "RESPONSE_CONTRACT_VIOLATION"
    )

    narration_api.uninstall_narration_production_backend_factory()
    switch_backend = Backend(
        result=_edition_switch(document_id=str(OTHER_DOCUMENT_ID))
    )
    switch_response = _client(switch_backend).put(
        f"/documents/{DOCUMENT_ID}/current-narration-edition",
        json=_switch_body(),
    )
    assert switch_response.status_code == 500
    assert switch_response.json()["detail"]["code"] == (
        "RESPONSE_CONTRACT_VIOLATION"
    )


@pytest.mark.parametrize(
    ("history_field", "invalid_value"),
    [
        ("document_id", str(OTHER_DOCUMENT_ID)),
        ("pointer_version", 5),
        ("current_edition_id", str(HISTORICAL_EDITION_ID)),
        ("working_copy_content_hash", SHA_C),
        ("working_copy_draft_version", 8),
    ],
)
def test_document_context_rejects_incoherent_nested_history(
    history_field: str,
    invalid_value: object,
) -> None:
    result = _document_context()
    history = result["edition_history"]
    assert isinstance(history, dict)
    history[history_field] = invalid_value
    backend = Backend(result=result)

    response = _client(backend).get(
        f"/documents/{DOCUMENT_ID}/narration-playback-context",
        params={"active_edition_id": str(HISTORICAL_EDITION_ID)},
    )

    assert response.status_code == 500
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["detail"]["code"] == "RESPONSE_CONTRACT_VIOLATION"


def test_edition_switch_rejects_response_for_another_target_edition() -> None:
    backend = Backend(result=_edition_switch(current_edition_id=str(EDITION_ID)))

    response = _client(backend).put(
        f"/documents/{DOCUMENT_ID}/current-narration-edition",
        json=_switch_body(),
    )

    assert response.status_code == 500
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["detail"]["code"] == "RESPONSE_CONTRACT_VIOLATION"


def test_document_context_and_switch_fail_closed_without_backend() -> None:
    client = _client()

    context_response = client.get(
        f"/documents/{DOCUMENT_ID}/narration-playback-context"
    )
    switch_response = client.put(
        f"/documents/{DOCUMENT_ID}/current-narration-edition",
        json=_switch_body(),
    )

    for response in (context_response, switch_response):
        assert response.status_code == 503
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["detail"] == {
            "contract_version": "narration-production-api/1",
            "code": "NARRATION_PRODUCTION_BACKEND_NOT_INSTALLED",
            "message": "朗读生产后端尚未完成应用入口接线。",
            "retryable": False,
            "field": None,
            "current_version": None,
        }


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        (IdempotencyConflict("private digest"), "IDEMPOTENCY_CONFLICT"),
        (StaleNarrationInput("private text"), "STALE_INPUT"),
    ],
)
def test_domain_failures_are_stable_and_do_not_echo_private_values(
    failure: Exception,
    expected_code: str,
) -> None:
    backend = Backend(failure=failure)

    response = _client(backend).post(
        f"/documents/{DOCUMENT_ID}/narration-requests",
        headers={"Idempotency-Key": "narration-failure-0001"},
        json=_start_body(),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == expected_code
    assert "private" not in response.text


def test_factory_install_and_uninstall_are_identity_safe() -> None:
    first = lambda _session: Backend()
    second = lambda _session: Backend()

    narration_api.install_narration_production_backend_factory(first)
    narration_api.install_narration_production_backend_factory(first)
    with pytest.raises(RuntimeError):
        narration_api.install_narration_production_backend_factory(second)
    with pytest.raises(RuntimeError):
        narration_api.uninstall_narration_production_backend_factory(second)
    narration_api.uninstall_narration_production_backend_factory(first)
