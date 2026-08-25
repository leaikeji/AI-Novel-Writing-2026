from __future__ import annotations

import asyncio
import inspect
import json
from typing import Literal, cast, get_args, get_origin
from uuid import uuid4

import pytest

from backend import tools
from backend.assistant_context import (
    AssistantWorkspaceRequestScope,
    TARGET_AGENT_ID,
)
from backend.assistant_workspace_service import WorkspaceScopeError


SELECTION_ID = str(uuid4())


def request_scope(
    *,
    agent_id: str = TARGET_AGENT_ID,
    session_id: str = "proposal-session-1",
    selection_id: str | None = SELECTION_ID,
    selection_character_count: int | None = 100,
) -> AssistantWorkspaceRequestScope:
    return AssistantWorkspaceRequestScope(
        agent_id=agent_id,
        session_id=session_id,
        novel_id=str(uuid4()),
        document_id=str(uuid4()),
        section="chapters",
        view="chapter-editor",
        entity_type="document",
        entity_id=str(uuid4()),
        selection_id=selection_id,
        selection_character_count=selection_character_count,
    )


def run_proposal(**overrides: object) -> dict[str, object]:
    arguments: dict[str, object] = {
        "selection_id": SELECTION_ID,
        "operation": "polish",
        "replacement_text": "海风掠过旧窗，留下淡淡盐味。",
        "short_summary": "收紧句子并保留海边质感",
    }
    arguments.update(overrides)
    return json.loads(
        asyncio.run(
            tools.novel_prepare_selection_edit(
                selection_id=cast(str, arguments["selection_id"]),
                operation=cast(tools.SelectionEditOperation, arguments["operation"]),
                replacement_text=cast(str, arguments["replacement_text"]),
                short_summary=cast(str, arguments["short_summary"]),
            ),
        ),
    )


def test_tool_signature_is_the_frozen_four_field_contract() -> None:
    assert list(inspect.signature(tools.novel_prepare_selection_edit).parameters) == [
        "selection_id",
        "operation",
        "replacement_text",
        "short_summary",
    ]
    operation_annotation = inspect.signature(
        tools.novel_prepare_selection_edit,
    ).parameters["operation"].annotation
    assert get_origin(operation_annotation) is Literal
    assert set(get_args(operation_annotation)) == tools.SELECTION_EDIT_OPERATIONS


def test_returns_versioned_plain_text_proposal_without_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tools, "current_assistant_workspace_scope", request_scope)
    monkeypatch.setattr(
        tools,
        "get_engine",
        lambda: (_ for _ in ()).throw(
            AssertionError("selection proposal tool must not open the database"),
        ),
    )

    payload = run_proposal(
        replacement_text="潮声🌊",
        short_summary="  保留意象  ",
    )

    assert payload == {
        "schema_version": 1,
        "selection_id": SELECTION_ID,
        "operation": "polish",
        "replacement_text": "潮声🌊",
        "short_summary": "保留意象",
        "replacement_character_count": 3,
        "warnings": [],
    }


def test_warns_about_markdown_fences_but_keeps_text_literal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tools, "current_assistant_workspace_scope", request_scope)
    payload = run_proposal(replacement_text="```text\n潮声\n```")

    assert payload["replacement_text"] == "```text\n潮声\n```"
    assert payload["warnings"] == ["候选文本包含 Markdown 围栏，请确认后再应用。"]


@pytest.mark.parametrize(
    ("operation", "replacement_length", "error_code"),
    [
        ("shorten", 81, "insufficient-shortening"),
        ("expand", 129, "insufficient-expansion"),
        ("review", 79, "review-size-mismatch"),
        ("review", 121, "review-size-mismatch"),
    ],
)
def test_rejects_candidates_that_do_not_meet_measurable_length_intent(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    replacement_length: int,
    error_code: str,
) -> None:
    monkeypatch.setattr(tools, "current_assistant_workspace_scope", request_scope)
    with pytest.raises(ValueError, match=f"^{error_code}$"):
        run_proposal(
            operation=operation,
            replacement_text="字" * replacement_length,
        )


@pytest.mark.parametrize(
    ("operation", "replacement_length"),
    [("shorten", 80), ("expand", 130), ("review", 80), ("review", 120)],
)
def test_accepts_candidates_at_the_measurable_length_boundary(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    replacement_length: int,
) -> None:
    monkeypatch.setattr(tools, "current_assistant_workspace_scope", request_scope)
    payload = run_proposal(
        operation=operation,
        replacement_text="字" * replacement_length,
    )
    assert payload["replacement_character_count"] == replacement_length


def test_rejects_a_model_supplied_selection_outside_the_trusted_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tools,
        "current_assistant_workspace_scope",
        lambda: request_scope(selection_id=str(uuid4())),
    )
    with pytest.raises(ValueError, match="^selection-scope-mismatch$"):
        run_proposal()


@pytest.mark.parametrize(
    ("overrides", "error_code"),
    [
        ({"selection_id": "not-a-uuid"}, "invalid-selection-id"),
        ({"selection_id": f" {SELECTION_ID}"}, "invalid-selection-id"),
        ({"operation": "delete"}, "unsupported-selection-operation"),
        ({"replacement_text": ""}, "invalid-replacement-text"),
        ({"replacement_text": "bad\x00text"}, "invalid-replacement-text"),
        (
            {
                "replacement_text": "字"
                * (tools.SELECTION_EDIT_MAX_REPLACEMENT_CHARACTERS + 1),
            },
            "invalid-replacement-text",
        ),
        ({"short_summary": "   "}, "invalid-short-summary"),
        (
            {
                "short_summary": "字"
                * (tools.SELECTION_EDIT_MAX_SUMMARY_CHARACTERS + 1),
            },
            "invalid-short-summary",
        ),
    ],
)
def test_rejects_invalid_or_oversized_contract_fields(
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, object],
    error_code: str,
) -> None:
    monkeypatch.setattr(tools, "current_assistant_workspace_scope", request_scope)
    with pytest.raises(ValueError, match=f"^{error_code}$"):
        run_proposal(**overrides)


@pytest.mark.parametrize(
    "scope",
    [
        None,
        request_scope(agent_id="default"),
        request_scope(session_id=" "),
    ],
)
def test_rejects_missing_non_target_or_unbound_request_scope(
    monkeypatch: pytest.MonkeyPatch,
    scope: AssistantWorkspaceRequestScope | None,
) -> None:
    monkeypatch.setattr(tools, "current_assistant_workspace_scope", lambda: scope)
    with pytest.raises(WorkspaceScopeError):
        run_proposal()
