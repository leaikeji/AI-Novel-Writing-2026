from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session

from backend.narration import script_api


SCRIPT_ID = UUID("b1000000-0000-4000-8000-000000000001")
VERSION_ID = UUID("b1000000-0000-4000-8000-000000000002")
NEXT_VERSION_ID = UUID("b1000000-0000-4000-8000-000000000012")
NOVEL_ID = UUID("b1000000-0000-4000-8000-000000000003")
DOCUMENT_ID = UUID("b1000000-0000-4000-8000-000000000004")
REVISION_ID = UUID("b1000000-0000-4000-8000-000000000005")
SEGMENT_ID = UUID("b1000000-0000-4000-8000-000000000006")
REQUEST_ID = UUID("b1000000-0000-4000-8000-000000000007")
CHARACTER_ID = UUID("b1000000-0000-4000-8000-000000000008")
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SOURCE_BLOCK_KEY = f"sb1_{'d' * 64}"


def _segment(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "segment_id": str(SEGMENT_ID),
        "ordinal": 0,
        "segment_kind": "dialogue",
        "source_block_key": SOURCE_BLOCK_KEY,
        "source_start_utf16": 0,
        "source_end_utf16": 4,
        "source_text": "“你好”",
        "spoken_text": "你好",
        "local_hash": SHA_C,
        "speaker_kind": "character",
        "speaker_label": "林晚",
        "character_id": str(CHARACTER_ID),
        "anonymous_speaker_id": None,
        "confidence": "high",
        "casting_state": "resolved",
        "issue_codes": [],
        "editable": True,
    }
    payload.update(changes)
    return payload


def _resource(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "contract_version": script_api.NARRATION_SCRIPT_REVIEW_API_VERSION,
        "taxonomy_version": "narration-review-taxonomy/1",
        "script_id": str(SCRIPT_ID),
        "script_version_id": str(VERSION_ID),
        "novel_id": str(NOVEL_ID),
        "document_id": str(DOCUMENT_ID),
        "revision_id": str(REVISION_ID),
        "source_content_hash": SHA_A,
        "immutable_hash": SHA_B,
        "version_number": 1,
        "state": "review_required",
        "effective_policy": "always_review",
        "source_status": "current",
        "warning_count": 0,
        "blocker_count": 0,
        "allowed_actions": ["approve", "edit_segment", "reanalyze_segments"],
        "segments": [_segment()],
        "issues": [],
        "approval": None,
    }
    payload.update(changes)
    return payload


@dataclass
class Backend:
    result: object = field(default_factory=_resource)
    commands: list[script_api.ScriptApiCommand] = field(default_factory=list)
    failure: Exception | None = None

    def dispatch(self, command: script_api.ScriptApiCommand) -> object:
        self.commands.append(command)
        if self.failure is not None:
            raise self.failure
        return self.result


@pytest.fixture(autouse=True)
def _reset_backend(monkeypatch: pytest.MonkeyPatch) -> Any:
    def test_session():  # type: ignore[no-untyped-def]
        with Session() as session:
            yield session

    monkeypatch.setattr(script_api, "get_session", test_session)
    script_api.uninstall_script_api_backend_factory()
    yield
    script_api.uninstall_script_api_backend_factory()


def _client(backend: Backend | None = None) -> TestClient:
    if backend is not None:
        factory = lambda _session: backend
        script_api.install_script_api_backend_factory(factory)
    app = FastAPI()
    app.dependency_overrides[
        script_api.require_narration_t4_http_access
    ] = lambda: None
    app.include_router(script_api.router)
    return TestClient(app, raise_server_exceptions=False)


def test_routes_fail_closed_until_t3_gate_installs_backend() -> None:
    response = _client().get(f"/narration-script-versions/{VERSION_ID}")

    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["detail"]["code"] == "SCRIPT_BACKEND_NOT_INSTALLED"


def test_installed_backend_reports_retryable_storage_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable_session():  # type: ignore[no-untyped-def]
        raise script_api.DatabaseNotConfigured("hidden database setting")
        yield

    monkeypatch.setattr(script_api, "get_session", unavailable_session)
    script_api.install_script_api_backend_factory(lambda _session: Backend())

    response = _client().get(f"/narration-script-versions/{VERSION_ID}")

    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["detail"] == {
        "contract_version": "narration-script-review-api/1",
        "code": "STORAGE_UNAVAILABLE",
        "message": "朗读脚本数据库当前不可用。",
        "retryable": True,
        "field": None,
        "current_version": None,
    }
    assert "hidden database setting" not in response.text


def test_queue_dependency_fault_is_a_sanitized_retryable_503() -> None:
    fault = script_api.ScriptApiFault(
        script_api.ScriptApiErrorCode.STORAGE_UNAVAILABLE,
        "朗读脚本数据库当前不可用。",
        retryable=True,
    )
    fault.__cause__ = RuntimeError("secret queue endpoint and credentials")
    backend = Backend(failure=fault)

    response = _client(backend).patch(
        f"/narration-script-versions/{VERSION_ID}/segments/{SEGMENT_ID}",
        headers={"Idempotency-Key": "script-patch-queue-failure"},
        json={
            "expected_request_version": 1,
            "expected_version_number": 1,
            "expected_immutable_hash": SHA_B,
            "expected_local_hash": SHA_C,
            "request_id": str(REQUEST_ID),
            "speaker_kind": "character",
            "speaker_label": "林晚",
            "character_id": str(CHARACTER_ID),
            "anonymous_speaker_id": None,
            "group_key": None,
            "spoken_text": "你好",
            "reason": "作者确认人物卡映射",
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "contract_version": "narration-script-review-api/1",
        "code": "STORAGE_UNAVAILABLE",
        "message": "朗读脚本数据库当前不可用。",
        "retryable": True,
        "field": None,
        "current_version": None,
    }
    assert "secret queue endpoint" not in response.text


def test_get_version_dispatches_only_server_scoped_identity() -> None:
    backend = Backend()

    response = _client(backend).get(f"/narration-script-versions/{VERSION_ID}")

    assert response.status_code == 200
    command = backend.commands[-1]
    assert command.operation is script_api.ScriptApiOperation.GET_SCRIPT_VERSION
    assert command.version_id == VERSION_ID
    assert not hasattr(command, "owner_id")
    assert not hasattr(command, "workspace_id")


def test_analyze_requires_source_snapshot_and_stable_idempotency_key() -> None:
    backend = Backend()
    client = _client(backend)
    response = client.post(
        f"/documents/{DOCUMENT_ID}/narration-scripts/analyze",
        headers={"Idempotency-Key": "script-analyze-0001"},
        json={
            "request_id": str(REQUEST_ID),
            "source_revision_id": str(REVISION_ID),
            "source_content_hash": SHA_A,
        },
    )

    assert response.status_code == 202
    command = backend.commands[-1]
    assert command.operation is script_api.ScriptApiOperation.ANALYZE_SCRIPT
    assert command.document_id == DOCUMENT_ID
    assert command.idempotency_key == "script-analyze-0001"
    assert isinstance(command.payload, script_api.AnalyzeScriptRequest)

    rejected = client.post(
        f"/documents/{DOCUMENT_ID}/narration-scripts/analyze",
        headers={"Idempotency-Key": "short"},
        json={
            "request_id": str(REQUEST_ID),
            "source_revision_id": str(REVISION_ID),
            "source_content_hash": SHA_A,
        },
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "REQUEST_VALIDATION_FAILED"


@pytest.mark.parametrize(
    "authority_field", ["owner_id", "workspace_id", "actor_id", "actor_type"]
)
@pytest.mark.parametrize(
    ("method", "path", "headers", "body"),
    [
        (
            "POST",
            f"/documents/{DOCUMENT_ID}/narration-scripts/analyze",
            {"Idempotency-Key": "script-analyze-injection"},
            {
                "request_id": str(REQUEST_ID),
                "source_revision_id": str(REVISION_ID),
                "source_content_hash": SHA_A,
            },
        ),
        (
            "PATCH",
            f"/narration-script-versions/{VERSION_ID}/segments/{SEGMENT_ID}",
            {"Idempotency-Key": "script-patch-injection"},
            {
                "expected_version_number": 1,
                "expected_immutable_hash": SHA_B,
                "expected_local_hash": SHA_C,
                "request_id": str(REQUEST_ID),
                "speaker_kind": "character",
                "speaker_label": "林晚",
                "character_id": str(CHARACTER_ID),
                "anonymous_speaker_id": None,
                "group_key": None,
                "spoken_text": "你好",
                "reason": "作者确认人物卡映射",
            },
        ),
        (
            "POST",
            f"/narration-script-versions/{VERSION_ID}/approve",
            {"Idempotency-Key": "script-approve-injection"},
            {
                "request_id": str(REQUEST_ID),
                "expected_version_number": 1,
                "expected_immutable_hash": SHA_B,
                "source_revision_id": str(REVISION_ID),
                "confirmed": True,
            },
        ),
        (
            "POST",
            f"/narration-script-versions/{VERSION_ID}/reanalyze-segments",
            {"Idempotency-Key": "script-reanalyze-injection"},
            {
                "request_id": str(REQUEST_ID),
                "expected_version_number": 1,
                "expected_immutable_hash": SHA_B,
                "segment_ids": [str(SEGMENT_ID)],
            },
        ),
    ],
)
def test_write_routes_reject_client_authority_before_dispatch(
    authority_field: str,
    method: str,
    path: str,
    headers: dict[str, str],
    body: dict[str, object],
) -> None:
    backend = Backend()

    response = _client(backend).request(
        method,
        path,
        headers=headers,
        json={**body, authority_field: "forged-client-authority"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "REQUEST_VALIDATION_FAILED"
    assert backend.commands == []


def test_response_source_and_spoken_whitespace_round_trip_without_normalization() -> None:
    source_text = "  “你好”\n"
    spoken_text = "  你好  "
    backend = Backend(
        result=_resource(
            segments=[_segment(source_text=source_text, spoken_text=spoken_text)]
        )
    )

    response = _client(backend).get(f"/narration-script-versions/{VERSION_ID}")

    assert response.status_code == 200
    assert response.json()["segments"][0]["source_text"] == source_text
    assert response.json()["segments"][0]["spoken_text"] == spoken_text


@pytest.mark.parametrize(
    ("field_name", "blank_value"),
    [("speaker_label", "   "), ("reason", "\t\n")],
)
def test_segment_patch_rejects_blank_human_fields_before_dispatch(
    field_name: str,
    blank_value: str,
) -> None:
    backend = Backend()
    body = {
        "expected_version_number": 1,
        "expected_immutable_hash": SHA_B,
        "expected_local_hash": SHA_C,
        "request_id": str(REQUEST_ID),
        "speaker_kind": "character",
        "speaker_label": "林晚",
        "character_id": str(CHARACTER_ID),
        "anonymous_speaker_id": None,
        "group_key": None,
        "spoken_text": "你好",
        "reason": "作者确认人物卡映射",
    }
    body[field_name] = blank_value

    response = _client(backend).patch(
        f"/narration-script-versions/{VERSION_ID}/segments/{SEGMENT_ID}",
        headers={"Idempotency-Key": "script-patch-blank-field"},
        json=body,
    )

    assert response.status_code == 422
    assert backend.commands == []


def test_segment_correction_is_a_new_version_command_not_an_old_row_patch() -> None:
    backend = Backend(
        result=_resource(script_version_id=str(NEXT_VERSION_ID), version_number=2)
    )
    response = _client(backend).patch(
        f"/narration-script-versions/{VERSION_ID}/segments/{SEGMENT_ID}",
        headers={"Idempotency-Key": "script-patch-0001"},
            json={
                "expected_request_version": 1,
                "expected_version_number": 1,
            "expected_immutable_hash": SHA_B,
            "expected_local_hash": SHA_C,
            "request_id": str(REQUEST_ID),
            "speaker_kind": "character",
            "speaker_label": "林晚",
            "character_id": str(CHARACTER_ID),
            "anonymous_speaker_id": None,
            "group_key": None,
            "spoken_text": "你好",
            "reason": "作者确认人物卡映射",
        },
    )

    assert response.status_code == 201
    command = backend.commands[-1]
    assert command.operation is script_api.ScriptApiOperation.PATCH_SEGMENT
    assert command.version_id == VERSION_ID
    assert command.segment_id == SEGMENT_ID
    assert command.idempotency_key == "script-patch-0001"


def _valid_segment_patch_body(*, spoken_text: str) -> dict[str, object]:
    return {
        "expected_request_version": 1,
        "expected_version_number": 1,
        "expected_immutable_hash": SHA_B,
        "expected_local_hash": SHA_C,
        "request_id": str(REQUEST_ID),
        "speaker_kind": "character",
        "speaker_label": "林晚",
        "character_id": str(CHARACTER_ID),
        "anonymous_speaker_id": None,
        "group_key": None,
        "spoken_text": spoken_text,
        "reason": "作者确认人物卡映射",
    }


def test_segment_patch_accepts_4000_codepoints_and_dispatches() -> None:
    backend = Backend(
        result=_resource(script_version_id=str(NEXT_VERSION_ID), version_number=2)
    )
    spoken_text = "声" * 4000

    response = _client(backend).patch(
        f"/narration-script-versions/{VERSION_ID}/segments/{SEGMENT_ID}",
        headers={"Idempotency-Key": "script-patch-max-codepoints"},
        json=_valid_segment_patch_body(spoken_text=spoken_text),
    )

    assert response.status_code == 201
    payload = backend.commands[-1].payload
    assert isinstance(payload, script_api.SegmentReviewPatch)
    assert payload.spoken_text == spoken_text


@pytest.mark.parametrize(
    "spoken_text",
    [
        "声" * 4001,
        "e\u0301",
    ],
    ids=["max-plus-one", "not-nfc"],
)
def test_segment_patch_rejects_oversize_or_non_nfc_before_dispatch(
    spoken_text: str,
) -> None:
    backend = Backend()

    response = _client(backend).patch(
        f"/narration-script-versions/{VERSION_ID}/segments/{SEGMENT_ID}",
        headers={"Idempotency-Key": "script-patch-invalid-unicode"},
        json=_valid_segment_patch_body(spoken_text=spoken_text),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "REQUEST_VALIDATION_FAILED"
    assert backend.commands == []


def test_segment_patch_rejects_unpaired_surrogate_at_dto_boundary() -> None:
    with pytest.raises(script_api.ValidationError):
        script_api.SegmentReviewPatch.model_validate(
            _valid_segment_patch_body(spoken_text="\ud800")
        )


def test_manual_approval_requires_explicit_snapshot_confirmation() -> None:
    approved = _resource(
        state="approved",
        allowed_actions=[],
        approval={
            "kind": "manual_after_review",
            "request_id": str(REQUEST_ID),
            "actor_type": "owner",
            "actor_id": "local-owner",
            "approved_at": "2026-08-26T12:00:00Z",
        },
    )
    backend = Backend(result=approved)
    client = _client(backend)

    response = client.post(
        f"/narration-script-versions/{VERSION_ID}/approve",
        headers={"Idempotency-Key": "script-approve-0001"},
            json={
                "request_id": str(REQUEST_ID),
                "expected_request_version": 1,
                "expected_version_number": 1,
            "expected_immutable_hash": SHA_B,
            "source_revision_id": str(REVISION_ID),
            "confirmed": True,
        },
    )
    assert response.status_code == 200
    assert backend.commands[-1].operation is script_api.ScriptApiOperation.APPROVE_SCRIPT_VERSION

    rejected = client.post(
        f"/narration-script-versions/{VERSION_ID}/approve",
        headers={"Idempotency-Key": "script-approve-0002"},
        json={
            "request_id": str(REQUEST_ID),
            "expected_version_number": 1,
            "expected_immutable_hash": SHA_B,
            "source_revision_id": str(REVISION_ID),
            "confirmed": False,
        },
    )
    assert rejected.status_code == 422


def test_reanalyze_segments_rejects_duplicates_and_dispatches_bounded_set() -> None:
    backend = Backend(
        result=_resource(script_version_id=str(NEXT_VERSION_ID), version_number=2)
    )
    client = _client(backend)
    body = {
        "request_id": str(REQUEST_ID),
        "expected_request_version": 1,
        "expected_version_number": 1,
        "expected_immutable_hash": SHA_B,
        "segment_ids": [str(SEGMENT_ID)],
    }
    response = client.post(
        f"/narration-script-versions/{VERSION_ID}/reanalyze-segments",
        headers={"Idempotency-Key": "script-reanalyze-0001"},
        json=body,
    )
    assert response.status_code == 202
    assert backend.commands[-1].operation is script_api.ScriptApiOperation.REANALYZE_SEGMENTS

    rejected = client.post(
        f"/narration-script-versions/{VERSION_ID}/reanalyze-segments",
        headers={"Idempotency-Key": "script-reanalyze-0002"},
        json={**body, "segment_ids": [str(SEGMENT_ID), str(SEGMENT_ID)]},
    )
    assert rejected.status_code == 422


@pytest.mark.parametrize(
    "resource",
    [
        _resource(unexpected=True),
        _resource(warning_count=1),
        _resource(
            segments=[_segment(speaker_kind="unknown", character_id=None)],
        ),
        _resource(
            segments=[
                _segment(
                    casting_state="unresolved",
                    issue_codes=[],
                )
            ],
        ),
        _resource(
            issues=[{
                "taxonomy_version": "narration-review-taxonomy/1",
                "code": "B_VOICE_MISSING",
                "severity": "warning",
                "segment_id": str(SEGMENT_ID),
                "evidence_summary": None,
                "evidence_digest": None,
            }],
            warning_count=1,
        ),
        _resource(
            segments=[_segment(confidence="medium")],
        ),
        _resource(
            source_status="superseded",
        ),
        _resource(
            state="approved",
            allowed_actions=[],
            approval={
                "kind": "auto_no_blockers",
                "request_id": str(REQUEST_ID),
                "actor_type": "service",
                "actor_id": "narration-orchestrator",
                "approved_at": "2026-08-26T12:00:00Z",
            },
        ),
        _resource(
            state="review_required",
            effective_policy="blockers_only",
            warning_count=1,
            blocker_count=1,
            allowed_actions=["edit_segment", "reanalyze_segments"],
            segments=[_segment(issue_codes=["B_VOICE_MISSING", "W_NEW_ANONYMOUS_SPEAKER"])],
            issues=[
                {
                    "taxonomy_version": "narration-review-taxonomy/1",
                    "code": "W_NEW_ANONYMOUS_SPEAKER",
                    "severity": "warning",
                    "segment_id": str(SEGMENT_ID),
                    "evidence_summary": None,
                    "evidence_digest": None,
                },
                {
                    "taxonomy_version": "narration-review-taxonomy/1",
                    "code": "B_VOICE_MISSING",
                    "severity": "blocker",
                    "segment_id": str(SEGMENT_ID),
                    "evidence_summary": None,
                    "evidence_digest": None,
                },
            ],
        ),
    ],
)
def test_response_contract_rejects_drift_counts_unknown_and_spoofed_severity(
    resource: dict[str, object],
) -> None:
    backend = Backend(result=resource)
    response = _client(backend).get(f"/narration-script-versions/{VERSION_ID}")

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "RESPONSE_CONTRACT_VIOLATION"


def test_unknown_speaker_blocker_resource_is_accepted_only_when_rows_match() -> None:
    issues = [
        {
            "taxonomy_version": "narration-review-taxonomy/1",
            "code": code,
            "severity": "blocker",
            "segment_id": str(SEGMENT_ID),
            "evidence_summary": None,
            "evidence_digest": None,
        }
        for code in ["B_SPEAKER_LOW_CONFIDENCE", "B_SPEAKER_UNKNOWN"]
    ]
    resource = _resource(
        state="review_required",
        effective_policy="blockers_only",
        blocker_count=2,
        allowed_actions=["edit_segment", "reanalyze_segments"],
        segments=[
            _segment(
                speaker_kind="unknown",
                speaker_label="待确认人物",
                character_id=None,
                confidence="unknown",
                issue_codes=["B_SPEAKER_LOW_CONFIDENCE", "B_SPEAKER_UNKNOWN"],
            )
        ],
        issues=issues,
    )

    response = _client(Backend(result=resource)).get(
        f"/narration-script-versions/{VERSION_ID}"
    )

    assert response.status_code == 200
    assert response.json()["blocker_count"] == 2


def test_unknown_confidence_rejects_unknown_speaker_blocker_without_low_confidence() -> None:
    resource = _resource(
        blocker_count=1,
        allowed_actions=["edit_segment", "reanalyze_segments"],
        segments=[
            _segment(
                speaker_kind="unknown",
                speaker_label="待确认人物",
                character_id=None,
                confidence="unknown",
                issue_codes=["B_SPEAKER_UNKNOWN"],
            )
        ],
        issues=[
            {
                "taxonomy_version": "narration-review-taxonomy/1",
                "code": "B_SPEAKER_UNKNOWN",
                "severity": "blocker",
                "segment_id": str(SEGMENT_ID),
                "evidence_summary": None,
                "evidence_digest": None,
            }
        ],
    )

    response = _client(Backend(result=resource)).get(
        f"/narration-script-versions/{VERSION_ID}"
    )

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "RESPONSE_CONTRACT_VIOLATION"


def test_diverged_source_requires_both_explicit_snapshot_choices() -> None:
    resource = _resource(
        source_status="working_copy_diverged",
        allowed_actions=["approve", "reanalyze_latest"],
    )

    response = _client(Backend(result=resource)).get(
        f"/narration-script-versions/{VERSION_ID}"
    )

    assert response.status_code == 500


def test_current_source_rejects_snapshot_actions_and_approved_history_stays_read_only() -> None:
    current_with_snapshot_action = _resource(
        allowed_actions=["approve", "continue_snapshot"]
    )
    backend = Backend(result=current_with_snapshot_action)
    client = _client(backend)
    rejected = client.get(
        f"/narration-script-versions/{VERSION_ID}"
    )
    assert rejected.status_code == 500

    approved_history = _resource(
        state="approved",
        source_status="working_copy_diverged",
        allowed_actions=[],
        approval={
            "kind": "manual_after_review",
            "request_id": str(REQUEST_ID),
            "actor_type": "owner",
            "actor_id": "local-owner",
            "approved_at": "2026-08-26T12:00:00Z",
        },
    )
    backend.result = approved_history
    accepted = client.get(
        f"/narration-script-versions/{VERSION_ID}"
    )
    assert accepted.status_code == 200
    assert accepted.json()["allowed_actions"] == []


def test_route_rejects_a_valid_resource_from_another_path_or_snapshot_scope() -> None:
    other_version = UUID("b1000000-0000-4000-8000-000000000099")
    backend = Backend(result=_resource(script_version_id=str(other_version)))
    client = _client(backend)
    version_response = client.get(f"/narration-script-versions/{VERSION_ID}")
    assert version_response.status_code == 500
    assert version_response.json()["detail"]["code"] == "RESPONSE_CONTRACT_VIOLATION"

    backend.result = _resource(revision_id=str(other_version))
    analyze_response = client.post(
        f"/documents/{DOCUMENT_ID}/narration-scripts/analyze",
        headers={"Idempotency-Key": "script-analyze-scope"},
        json={
            "request_id": str(REQUEST_ID),
            "source_revision_id": str(REVISION_ID),
            "source_content_hash": SHA_A,
        },
    )
    assert analyze_response.status_code == 500
    assert analyze_response.json()["detail"]["code"] == "RESPONSE_CONTRACT_VIOLATION"


@pytest.mark.parametrize(
    ("failure", "status_code", "code"),
    [
        (script_api.NarrationScopeMismatch("scope"), 404, "SCOPE_VIOLATION"),
        (script_api.NarrationCasConflict("cas"), 409, "VERSION_CONFLICT"),
        (script_api.StaleNarrationInput("stale"), 409, "STALE_INPUT"),
        (script_api.InvalidNarrationState("state"), 409, "INVALID_STATE"),
    ],
)
def test_domain_failures_are_sanitized(
    failure: Exception,
    status_code: int,
    code: str,
) -> None:
    backend = Backend(failure=failure)

    response = _client(backend).get(f"/narration-script-versions/{VERSION_ID}")

    assert response.status_code == status_code
    assert response.json()["detail"]["code"] == code
    assert str(failure) not in response.text


def test_factory_install_and_uninstall_are_identity_safe() -> None:
    first = lambda _session: Backend()
    second = lambda _session: Backend()
    script_api.install_script_api_backend_factory(first)
    script_api.install_script_api_backend_factory(first)
    with pytest.raises(RuntimeError, match="already installed"):
        script_api.install_script_api_backend_factory(second)
    with pytest.raises(RuntimeError, match="another"):
        script_api.uninstall_script_api_backend_factory(second)
    script_api.uninstall_script_api_backend_factory(first)
