from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend import assistant_api
from backend.assistant_context_registry import (
    AssistantContextRefRegistry,
    CONTEXT_REF_MAX_REQUEST_BYTES,
    STORY_LEDGER_CONTEXT_MAX_CODE_POINTS,
)
from backend.database import get_session
from backend.novel_lifecycle_errors import NovelLifecycleNotFound
from backend.services import NotFoundError


NOW = datetime(2026, 8, 25, 10, 0, tzinfo=timezone.utc)
NOVEL_ID = uuid4()
DOCUMENT_ID = uuid4()
DRAFT_ID = uuid4()


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


def creation_snapshot() -> dict[str, object]:
    return {
        "schemaVersion": "creation-draft-assistant-context/1",
        "contextRevision": 3,
        "capturedAt": NOW.isoformat(),
        "expiresAt": (NOW + timedelta(minutes=10)).isoformat(),
        "agentId": "ai-novel-writer",
        "sessionId": "session-1",
        "creationDraft": {
            "id": str(DRAFT_ID),
            "version": 4,
            "step": 2,
            "state": "draft",
        },
        "page": {
            "section": "creation",
            "view": "novel-creation-wizard",
            "step": 2,
        },
        "editing": {
            "focusedFieldId": "creation.idea",
            "fields": [{
                "id": "creation.idea",
                "label": "创作思路",
                "value": "暴雨封路，刑警收到死者来信。",
                "dirty": True,
                "truncated": False,
                "characterCount": 16,
                "persistence": "explicit-save",
            }],
        },
        "budget": {
            "maxCharacters": 24_000,
            "usedCharacters": 500,
            "truncated": False,
            "omittedFieldIds": [],
        },
    }


def creation_body() -> dict[str, object]:
    return {
        "ownerToken": "owner_token_0000000000000001",
        "tabInstance": "tab_instance_000000000000001",
        "agentId": "ai-novel-writer",
        "scopeKind": "creation_draft",
        "scopeId": str(DRAFT_ID),
        "sessionId": "session-1",
        "snapshot": creation_snapshot(),
    }


def library_snapshot(*, selected_novel: bool = False) -> dict[str, object]:
    value: dict[str, object] = {
        "schemaVersion": "private-library-assistant-context/1",
        "contextRevision": 2,
        "capturedAt": NOW.isoformat(),
        "expiresAt": (NOW + timedelta(minutes=10)).isoformat(),
        "agentId": "ai-novel-writer",
        "sessionId": "session-1",
        "library": {"id": "personal"},
        "page": {"section": "private-library", "view": "library"},
        "budget": {
            "maxCharacters": 24_000,
            "usedCharacters": 180,
            "truncated": False,
            "omittedFieldIds": [],
        },
    }
    if selected_novel:
        value["novel"] = {
            "id": str(NOVEL_ID),
            "title": "潮声替我说晚安",
        }
    return value


def library_body() -> dict[str, object]:
    return {
        "ownerToken": "owner_token_0000000000000001",
        "tabInstance": "tab_instance_000000000000001",
        "agentId": "ai-novel-writer",
        "scopeKind": "private_library",
        "scopeId": "personal",
        "sessionId": "session-1",
        "snapshot": library_snapshot(),
    }


def selected_novel_library_body() -> dict[str, object]:
    value = library_body()
    value["novelId"] = str(NOVEL_ID)
    value["snapshot"] = library_snapshot(selected_novel=True)
    return value


def ledger_snapshot() -> dict[str, object]:
    value = snapshot(with_document=False)
    value["page"] = {"section": "ledger", "view": "story-ledger"}
    ledger: dict[str, object] = {
        "schema_version": "story-ledger-assistant-context/1",
        "novel": {"id": str(NOVEL_ID), "title": "潮声替我说晚安"},
        "ledger_snapshot_token": "snapshot-token-1",
        "timeline": {"id": "timeline-1", "name": "主线"},
        "filters": {
            "fact_types": [],
            "effective_state": None,
            "health": None,
            "dimension": None,
            "source_document_id": None,
            "commit_batch_id": None,
            "fact_timeline_id": None,
            "entity_type": None,
            "entity_id": None,
            "review_only": False,
        },
        "summary": {
            "total": 0,
            "review_required": 0,
            "by_fact_type": {},
            "by_effective_state": {},
            "by_health": {},
        },
        "selected_fact_id": None,
        "selected_fact": None,
        "budget": {
            "max_code_points": STORY_LEDGER_CONTEXT_MAX_CODE_POINTS,
            "used_code_points": 0,
            "truncated": False,
        },
    }
    budget = ledger["budget"]
    assert isinstance(budget, dict)
    for _ in range(8):
        used = len(
            json.dumps(
                ledger,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
        if budget["used_code_points"] == used:
            break
        budget["used_code_points"] = used
    value["ledger"] = ledger
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
    monkeypatch.setattr(
        assistant_api,
        "get_novel_creation_draft",
        lambda _session, draft_id: {
            "id": str(draft_id),
            "version": 4,
            "step": 2,
            "state": "draft",
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
        "writingActionId",
        "expiresAt",
        "contextRevision",
        "payloadCharacters",
    }
    assert len(payload["contextRef"]) == 43
    assert str(UUID(payload["writingActionId"])) == payload["writingActionId"]
    leased = assistant_api.assistant_context_registry.lease_for_runtime(
        payload["contextRef"],
        agent_id="ai-novel-writer",
        session_id="session-1",
    )
    assert leased.accepted
    assert leased.writing_action_id == UUID(payload["writingActionId"])
    assert leased.runtime_app is client.app
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


def test_each_prepared_send_gets_a_new_action_but_ref_retry_keeps_identity(
    client: TestClient,
) -> None:
    first = client.post("/assistant-contexts", json=body()).json()
    second = client.post("/assistant-contexts", json=body()).json()
    assert first["contextRef"] != second["contextRef"]
    assert first["writingActionId"] != second["writingActionId"]

    first_lease = assistant_api.assistant_context_registry.lease_for_runtime(
        first["contextRef"],
        agent_id="ai-novel-writer",
        session_id="session-1",
    )
    retry_lease = assistant_api.assistant_context_registry.lease_for_runtime(
        first["contextRef"],
        agent_id="ai-novel-writer",
        session_id="session-1",
    )
    assert first_lease.accepted and retry_lease.accepted
    assert first_lease.writing_action_id == retry_lease.writing_action_id
    assert str(first_lease.writing_action_id) == first["writingActionId"]


def test_endpoint_accepts_creation_draft_without_a_fake_novel(
    client: TestClient,
) -> None:
    response = client.post("/assistant-contexts", json=creation_body())

    assert response.status_code == 201
    leased = assistant_api.assistant_context_registry.lease_for_runtime(
        response.json()["contextRef"],
        agent_id="ai-novel-writer",
        session_id="session-1",
    )
    assert leased.accepted
    assert leased.snapshot is not None
    assert "novel" not in leased.snapshot
    assert leased.snapshot["creationDraft"]["id"] == str(DRAFT_ID)


def test_endpoint_accepts_private_library_without_a_fake_novel_or_database_lookup(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        assistant_api,
        "get_novel",
        lambda *_args: pytest.fail("library scope must not borrow a novel"),
    )
    response = client.post("/assistant-contexts", json=library_body())

    assert response.status_code == 201
    leased = assistant_api.assistant_context_registry.lease_for_runtime(
        response.json()["contextRef"],
        agent_id="ai-novel-writer",
        session_id="session-1",
    )
    assert leased.accepted
    assert leased.snapshot is not None
    assert "novel" not in leased.snapshot
    assert leased.snapshot["library"] == {"id": "personal"}


def test_endpoint_verifies_selected_novel_for_private_library_scope(
    client: TestClient,
) -> None:
    response = client.post("/assistant-contexts", json=selected_novel_library_body())

    assert response.status_code == 201
    leased = assistant_api.assistant_context_registry.lease_for_runtime(
        response.json()["contextRef"],
        agent_id="ai-novel-writer",
        session_id="session-1",
    )
    assert leased.accepted
    assert leased.snapshot is not None
    assert leased.snapshot["novel"]["id"] == str(NOVEL_ID)


def test_endpoint_rejects_unknown_selected_novel_for_private_library_scope(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        assistant_api,
        "get_novel",
        lambda *_args: (_ for _ in ()).throw(NotFoundError("not found")),
    )
    response = client.post("/assistant-contexts", json=selected_novel_library_body())

    assert response.status_code == 404


def test_endpoint_maps_lifecycle_unknown_novel_to_404(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SqlalchemyLikeSession:
        pass

    SqlalchemyLikeSession.__module__ = "sqlalchemy.orm.session"
    monkeypatch.setattr(
        assistant_api,
        "require_active_novel",
        lambda *_args: (_ for _ in ()).throw(
            NovelLifecycleNotFound("小说不存在"),
        ),
    )
    client.app.dependency_overrides[get_session] = lambda: SqlalchemyLikeSession()

    response = client.post("/assistant-contexts", json=selected_novel_library_body())

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "type": "assistant_context_scope_unavailable",
    }


@pytest.mark.parametrize("mutation", ["fake-novel", "wrong-scope-id", "mixed-scope"])
def test_endpoint_rejects_invalid_private_library_scope(
    client: TestClient,
    mutation: str,
) -> None:
    payload = library_body()
    if mutation == "fake-novel":
        payload["snapshot"]["novel"] = {"id": str(NOVEL_ID), "title": "越界作品"}
    elif mutation == "wrong-scope-id":
        payload["scopeId"] = "shared"
    else:
        payload["novelId"] = str(NOVEL_ID)

    response = client.post("/assistant-contexts", json=payload)

    assert response.status_code == 422


@pytest.mark.parametrize("mutation", ["fake-novel", "wrong-version", "mixed-scope"])
def test_endpoint_rejects_invalid_creation_draft_scope(
    client: TestClient,
    mutation: str,
) -> None:
    payload = creation_body()
    if mutation == "fake-novel":
        payload["snapshot"]["novel"] = {"id": str(NOVEL_ID), "title": "伪造小说"}
    elif mutation == "wrong-version":
        payload["snapshot"]["creationDraft"]["version"] = 5
    else:
        payload["novelId"] = str(NOVEL_ID)

    response = client.post("/assistant-contexts", json=payload)

    assert response.status_code in {409, 422}


def test_endpoint_accepts_the_frozen_story_ledger_context(
    client: TestClient,
) -> None:
    payload = body(document_id=None)
    payload["snapshot"] = ledger_snapshot()

    response = client.post("/assistant-contexts", json=payload)

    assert response.status_code == 201
    leased = assistant_api.assistant_context_registry.lease_for_runtime(
        response.json()["contextRef"],
        agent_id="ai-novel-writer",
        session_id="session-1",
    )
    assert leased.accepted
    assert leased.snapshot is not None
    assert leased.snapshot["ledger"]["schema_version"] == (
        "story-ledger-assistant-context/1"
    )


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
