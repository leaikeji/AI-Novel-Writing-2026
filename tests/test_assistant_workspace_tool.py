from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any
from uuid import UUID, uuid4

import pytest

from backend import tools
from backend.assistant_context import (
    AssistantWorkspaceRequestScope,
    TARGET_AGENT_ID,
)
from backend.assistant_workspace_service import WorkspaceScopeError


NOVEL_ID = uuid4()
DOCUMENT_ID = uuid4()
ENTITY_ID = uuid4()


class ReadOnlySession:
    def __init__(self) -> None:
        self.entered = 0
        self.exited = 0

    def __enter__(self) -> ReadOnlySession:
        self.entered += 1
        return self

    def __exit__(self, *_args: object) -> None:
        self.exited += 1

    def commit(self) -> None:  # pragma: no cover - a call is a hard failure.
        raise AssertionError("read-only workspace tool must not commit")

    def flush(self) -> None:  # pragma: no cover - a call is a hard failure.
        raise AssertionError("read-only workspace tool must not flush")

    def add(self, _value: object) -> None:  # pragma: no cover
        raise AssertionError("read-only workspace tool must not add rows")


def request_scope(
    *,
    agent_id: str = TARGET_AGENT_ID,
    session_id: str = "workspace-session-1",
    novel_id: str = str(NOVEL_ID),
    document_id: str | None = str(DOCUMENT_ID),
    section: str = "roles",
    entity_type: str | None = "character",
    entity_id: str | None = str(ENTITY_ID),
) -> AssistantWorkspaceRequestScope:
    return AssistantWorkspaceRequestScope(
        agent_id=agent_id,
        session_id=session_id,
        novel_id=novel_id,
        document_id=document_id,
        section=section,
        view="character-editor",
        entity_type=entity_type,
        entity_id=entity_id,
    )


def install_session(
    monkeypatch: pytest.MonkeyPatch,
    session: ReadOnlySession,
) -> list[dict[str, object]]:
    factory_calls: list[dict[str, object]] = []
    engine = object()
    monkeypatch.setattr(tools, "get_engine", lambda: engine)

    def fake_sessionmaker(**kwargs: object) -> object:
        factory_calls.append(kwargs)
        return lambda: session

    monkeypatch.setattr(tools, "sessionmaker", fake_sessionmaker)
    return factory_calls


def fail_before_database(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected() -> object:
        raise AssertionError("invalid scope must fail before opening the database")

    monkeypatch.setattr(tools, "get_engine", unexpected)
    monkeypatch.setattr(tools, "get_assistant_workspace_context", unexpected)


def test_tool_signature_has_no_model_supplied_scope_identifiers() -> None:
    parameters = inspect.signature(
        tools.novel_get_workspace_context,
    ).parameters

    assert list(parameters) == [
        "section",
        "include",
        "max_chars",
        "schema_version",
    ]
    assert not {
        "novel_id",
        "document_id",
        "entity_id",
        "entity_type",
        "owner_token",
        "session_id",
        "agent_id",
    } & set(parameters)


def test_uses_current_scope_document_entity_and_page_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = request_scope()
    monkeypatch.setattr(
        tools,
        "current_assistant_workspace_scope",
        lambda: scope,
    )
    session = ReadOnlySession()
    factory_calls = install_session(monkeypatch, session)
    service_calls: list[tuple[object, dict[str, Any]]] = []

    def fake_workspace_service(
        current_session: object,
        **kwargs: Any,
    ) -> dict[str, object]:
        service_calls.append((current_session, kwargs))
        return {
            "schema_version": 2,
            "as_of": "2026-08-25T08:00:00Z",
            "novel_id": str(NOVEL_ID),
            "section": "roles",
            "document_id": str(DOCUMENT_ID),
            "document": {"id": str(DOCUMENT_ID)},
            "entity": {"type": "character", "id": str(ENTITY_ID)},
            "provenance": {
                "characters": [
                    {
                        "source_type": "database_table",
                        "table": "novel_characters",
                        "record_count": 1,
                    },
                ],
            },
            "truncated": False,
            "omitted_sections": [],
            "data": {"characters": [{"name": "林雾"}]},
            "warnings": [],
            "budget": {"max_chars": 4_000, "used_chars": 120},
        }

    monkeypatch.setattr(
        tools,
        "get_assistant_workspace_context",
        fake_workspace_service,
    )

    result = json.loads(
        asyncio.run(
            tools.novel_get_workspace_context(
                include=["characters"],
                max_chars=4_000,
            ),
        ),
    )

    assert result["as_of"] == "2026-08-25T08:00:00Z"
    assert result["provenance"]["characters"][0]["record_count"] == 1
    assert result["truncated"] is False
    assert len(service_calls) == 1
    current_session, arguments = service_calls[0]
    assert current_session is session
    assert arguments["novel_id"] == NOVEL_ID
    assert arguments["document_id"] == DOCUMENT_ID
    assert arguments["entity_type"] == "character"
    assert arguments["entity_id"] == ENTITY_ID
    assert arguments["section"] == "roles"
    assert arguments["include"] == ["characters"]
    assert arguments["max_chars"] == 4_000
    assert arguments["schema_version"] == 2
    owner_scope = arguments["owner_scope"]
    assert owner_scope.owner_id == "workspace-session-1"
    assert owner_scope.novel_ids == frozenset({NOVEL_ID})
    assert factory_calls == [{"bind": factory_calls[0]["bind"], "expire_on_commit": False}]
    assert session.entered == session.exited == 1


def test_forwards_approved_section_include_budget_and_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tools,
        "current_assistant_workspace_scope",
        request_scope,
    )
    install_session(monkeypatch, ReadOnlySession())
    observed: dict[str, Any] = {}

    def fake_workspace_service(
        _session: object,
        **kwargs: Any,
    ) -> dict[str, object]:
        observed.update(kwargs)
        return {
            "schema_version": 2,
            "as_of": "2026-08-25T08:00:00Z",
            "provenance": {},
            "truncated": True,
            "omitted_sections": ["relationships"],
            "warnings": ["relationships omitted by max_chars budget"],
            "budget": {"max_chars": 1_000, "used_chars": 0},
            "data": {},
        }

    monkeypatch.setattr(
        tools,
        "get_assistant_workspace_context",
        fake_workspace_service,
    )

    result = json.loads(
        asyncio.run(
            tools.novel_get_workspace_context(
                section="clues",
                include=["foreshadows", "relationships"],
                max_chars=1,
                schema_version=2,
            ),
        ),
    )

    assert observed["section"] == "clues"
    assert observed["include"] == ["foreshadows", "relationships"]
    assert observed["max_chars"] == 1
    assert observed["schema_version"] == 2
    assert result["budget"] == {"max_chars": 1_000, "used_chars": 0}
    assert result["truncated"] is True
    assert result["omitted_sections"] == ["relationships"]


@pytest.mark.parametrize(
    ("material_section", "page_section"),
    [
        ("characters", "roles"),
        ("relationships", "roles"),
        ("storylines", "clues"),
        ("foreshadows", "clues"),
    ],
)
def test_maps_material_category_section_aliases_without_expanding_scope(
    monkeypatch: pytest.MonkeyPatch,
    material_section: str,
    page_section: str,
) -> None:
    monkeypatch.setattr(
        tools,
        "current_assistant_workspace_scope",
        request_scope,
    )
    install_session(monkeypatch, ReadOnlySession())
    observed: dict[str, Any] = {}

    def fake_workspace_service(
        _session: object,
        **kwargs: Any,
    ) -> dict[str, object]:
        observed.update(kwargs)
        return {
            "schema_version": 2,
            "as_of": "2026-08-25T08:00:00Z",
            "provenance": {},
            "truncated": False,
            "omitted_sections": [],
            "warnings": [],
            "budget": {"max_chars": 12_000, "used_chars": 0},
            "data": {},
        }

    monkeypatch.setattr(
        tools,
        "get_assistant_workspace_context",
        fake_workspace_service,
    )

    asyncio.run(
        tools.novel_get_workspace_context(  # type: ignore[arg-type]
            section=material_section,
            include=[material_section],  # type: ignore[list-item]
        ),
    )

    assert observed["section"] == page_section
    assert observed["include"] == [material_section]
    assert observed["novel_id"] == NOVEL_ID


@pytest.mark.parametrize(
    "scope",
    [
        None,
        request_scope(agent_id="default"),
        request_scope(session_id=""),
    ],
)
def test_missing_or_non_target_context_fails_before_database(
    monkeypatch: pytest.MonkeyPatch,
    scope: AssistantWorkspaceRequestScope | None,
) -> None:
    monkeypatch.setattr(
        tools,
        "current_assistant_workspace_scope",
        lambda: scope,
    )
    fail_before_database(monkeypatch)

    with pytest.raises(WorkspaceScopeError) as captured:
        asyncio.run(tools.novel_get_workspace_context())

    assert str(captured.value) == (
        "workspace resource is not available in the current owner scope"
    )


@pytest.mark.parametrize(
    "scope",
    [
        request_scope(novel_id="not-a-uuid"),
        request_scope(document_id="not-a-uuid"),
        request_scope(entity_id="not-a-uuid"),
        request_scope(entity_type="character", entity_id=None),
    ],
)
def test_malformed_scope_ids_fail_without_leaking_values(
    monkeypatch: pytest.MonkeyPatch,
    scope: AssistantWorkspaceRequestScope,
) -> None:
    monkeypatch.setattr(
        tools,
        "current_assistant_workspace_scope",
        lambda: scope,
    )
    fail_before_database(monkeypatch)

    with pytest.raises(WorkspaceScopeError) as captured:
        asyncio.run(tools.novel_get_workspace_context())

    assert "not-a-uuid" not in str(captured.value)
    assert str(NOVEL_ID) not in str(captured.value)
    assert str(DOCUMENT_ID) not in str(captured.value)
    assert str(ENTITY_ID) not in str(captured.value)


def test_current_scope_cannot_be_expanded_to_another_novel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    other_novel_id = uuid4()
    cross_novel_document_id = uuid4()
    scope = request_scope(document_id=str(cross_novel_document_id))
    monkeypatch.setattr(
        tools,
        "current_assistant_workspace_scope",
        lambda: scope,
    )
    install_session(monkeypatch, ReadOnlySession())

    def reject_cross_novel(
        _session: object,
        **kwargs: Any,
    ) -> dict[str, object]:
        assert kwargs["novel_id"] == NOVEL_ID
        assert kwargs["owner_scope"].novel_ids == frozenset({NOVEL_ID})
        assert kwargs["document_id"] == cross_novel_document_id
        raise WorkspaceScopeError()

    monkeypatch.setattr(
        tools,
        "get_assistant_workspace_context",
        reject_cross_novel,
    )

    with pytest.raises(WorkspaceScopeError) as captured:
        asyncio.run(tools.novel_get_workspace_context())
    assert str(other_novel_id) not in str(captured.value)
    assert str(cross_novel_document_id) not in str(captured.value)

    with pytest.raises(TypeError):
        asyncio.run(
            tools.novel_get_workspace_context(  # type: ignore[call-arg]
                novel_id=str(other_novel_id),
            ),
        )


def test_existing_three_read_only_tools_keep_their_signatures_and_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = uuid4()
    document_id = uuid4()
    session = ReadOnlySession()
    install_session(monkeypatch, session)
    calls: list[tuple[object, ...]] = []

    def fake_get_context(
        current_session: object,
        current_novel_id: UUID,
        *,
        document_id: UUID | None,
        max_chars: int,
    ) -> dict[str, object]:
        calls.append(
            ("context", current_session, current_novel_id, document_id, max_chars),
        )
        return {"kind": "context"}

    def fake_get_document(
        current_session: object,
        current_document_id: UUID,
    ) -> dict[str, object]:
        calls.append(("document", current_session, current_document_id))
        return {"kind": "document"}

    def fake_search(
        current_session: object,
        current_novel_id: UUID,
        query: str,
        *,
        limit: int,
    ) -> dict[str, object]:
        calls.append(("search", current_session, current_novel_id, query, limit))
        return {"kind": "search"}

    monkeypatch.setattr(tools, "get_novel_context", fake_get_context)
    monkeypatch.setattr(tools, "get_document", fake_get_document)
    monkeypatch.setattr(tools, "search_novel", fake_search)

    context = json.loads(
        asyncio.run(
            tools.novel_get_context(
                str(novel_id),
                str(document_id),
                7_000,
            ),
        ),
    )
    document = json.loads(
        asyncio.run(tools.novel_get_document(str(document_id))),
    )
    search = json.loads(
        asyncio.run(tools.novel_search(str(novel_id), "旧电台", 8)),
    )

    assert context == {"kind": "context"}
    assert document == {"kind": "document"}
    assert search == {"kind": "search"}
    assert calls == [
        ("context", session, novel_id, document_id, 7_000),
        ("document", session, document_id),
        ("search", session, novel_id, "旧电台", 8),
    ]
    assert list(inspect.signature(tools.novel_get_context).parameters) == [
        "novel_id",
        "document_id",
        "max_chars",
    ]
    assert list(inspect.signature(tools.novel_get_document).parameters) == [
        "document_id",
    ]
    assert list(inspect.signature(tools.novel_search).parameters) == [
        "novel_id",
        "query",
        "limit",
    ]
    assert session.entered == session.exited == 3
