from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend import assistant_api
from backend.assistant_context_registry import (
    AssistantContextRefRegistry,
    CONTEXT_REF_MAX_REQUEST_BYTES,
)
from backend.database import get_session


NOW = datetime(2026, 8, 25, 10, 0, tzinfo=timezone.utc)
NOVEL_ID = uuid4()
DOCUMENT_ID = uuid4()


def snapshot(*, with_document: bool = True) -> dict[str, object]:
    value: dict[str, object] = {
        "schemaVersion": 2,
        "contextRevision": 7,
        "capturedAt": NOW.isoformat(),
        "expiresAt": (NOW + timedelta(minutes=10)).isoformat(),
        "agentId": "ai-novel-writer",
        "sessionId": "session-1",
        "novel": {"id": str(NOVEL_ID), "title": "潮声替我说晚安"},
        "page": {"section": "chapters", "view": "chapter-editor"},
        "budget": {
            "maxCharacters": 24_000,
            "usedCharacters": 300,
            "truncated": False,
            "omittedFieldIds": [],
        },
    }
    if with_document:
        value["document"] = {
            "id": str(DOCUMENT_ID),
            "kind": "chapter",
            "title": "第一章 潮声",
            "draftVersion": 3,
            "savedContentHash": "a" * 64,
            "dirty": True,
        }
    return value


def body(*, document_id: str | None = str(DOCUMENT_ID)) -> dict[str, object]:
    value: dict[str, object] = {
        "ownerToken": "owner_token_0000000000000001",
        "tabInstance": "tab_instance_000000000000001",
        "agentId": "ai-novel-writer",
        "novelId": str(NOVEL_ID),
        "sessionId": "session-1",
        "snapshot": snapshot(with_document=document_id is not None),
    }
    if document_id is not None:
        value["documentId"] = document_id
    return value


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    registry = AssistantContextRefRegistry(clock=lambda: NOW)
    monkeypatch.setattr(assistant_api, "assistant_context_registry", registry)
    monkeypatch.setattr(
        assistant_api,
        "get_novel",
        lambda _session, novel_id: {"id": str(novel_id)},
    )
    monkeypatch.setattr(
        assistant_api,
        "get_document",
        lambda _session, document_id: {
            "id": str(document_id),
            "novel_id": str(NOVEL_ID),
        },
    )
    app = FastAPI()
    app.include_router(assistant_api.router)
    app.dependency_overrides[get_session] = lambda: object()
    with TestClient(app) as value:
        yield value


def test_endpoint_creates_no_store_ref_and_runtime_can_lease_it(client: TestClient) -> None:
    response = client.post("/assistant-contexts", json=body())

    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert set(payload) == {
        "contextRef",
        "expiresAt",
        "contextRevision",
        "payloadCharacters",
    }
    assert len(payload["contextRef"]) == 43
    leased = assistant_api.assistant_context_registry.lease_for_runtime(
        payload["contextRef"],
        agent_id="ai-novel-writer",
        session_id="session-1",
    )
    assert leased.accepted
    assert leased.snapshot["novel"]["id"] == str(NOVEL_ID)


def test_endpoint_supports_a_first_ref_without_a_native_session(
    client: TestClient,
) -> None:
    payload = body(document_id=None)
    payload.pop("sessionId")
    payload["snapshot"].pop("sessionId")
    response = client.post("/assistant-contexts", json=payload)

    assert response.status_code == 201
    leased = assistant_api.assistant_context_registry.lease_for_runtime(
        response.json()["contextRef"],
        agent_id="ai-novel-writer",
        session_id="first-native-session",
    )
    assert leased.accepted
    assert leased.snapshot["sessionId"] == "first-native-session"


def test_endpoint_rejects_cross_novel_document_without_creating_a_ref(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        assistant_api,
        "get_document",
        lambda _session, document_id: {
            "id": str(document_id),
            "novel_id": str(uuid4()),
        },
    )
    response = client.post("/assistant-contexts", json=body())

    assert response.status_code == 404
    assert response.json() == {
        "detail": {"type": "assistant_context_scope_unavailable"},
    }
    assert assistant_api.assistant_context_registry.diagnostics().active_entries == 0


def test_endpoint_rejects_unapproved_keys_without_echoing_author_content(
    client: TestClient,
) -> None:
    payload = body()
    payload["SECRET AUTHOR CONTENT"] = "must never be echoed"
    response = client.post("/assistant-contexts", json=payload)

    assert response.status_code == 422
    assert response.json() == {
        "detail": {
            "type": "assistant_context_rejected",
            "reason": "invalid-request",
        },
    }
    assert "SECRET" not in response.text


def test_endpoint_enforces_raw_96_kib_before_json_validation(client: TestClient) -> None:
    response = client.post(
        "/assistant-contexts",
        content=b"x" * (CONTEXT_REF_MAX_REQUEST_BYTES + 1),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json()["detail"]["reason"] == "request-too-large"
    assert assistant_api.assistant_context_registry.diagnostics().active_entries == 0
