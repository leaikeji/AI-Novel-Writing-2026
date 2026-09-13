from __future__ import annotations

import ast
import asyncio
import inspect
import json
from pathlib import Path

import pytest

from backend import tools


ROOT = Path(__file__).resolve().parents[2]
MAINTENANCE_TOOLS = {
    "novel_library_query",
    "novel_library_prepare_change",
    "novel_library_apply_change",
}
FORBIDDEN_MODEL_AUTHORITY = {
    "authorized",
    "write_authorized",
    "session_id",
    "request_id",
    "author_text_hash",
    "author_text_sha256",
    "scope",
    "scope_kind",
    "scope_novel_id",
    "novel_id",
    "requires_review",
    "review_accepted",
    "accepted",
}


class RecordingSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def __enter__(self) -> "RecordingSession":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def _install_session(
    monkeypatch: pytest.MonkeyPatch,
) -> RecordingSession:
    session = RecordingSession()
    monkeypatch.setattr(tools, "get_engine", lambda: object())
    monkeypatch.setattr(
        tools,
        "sessionmaker",
        lambda **_kwargs: lambda: session,
    )
    return session


def _registered_tool_names() -> set[str]:
    tree = ast.parse((ROOT / "plugin.py").read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "register_tool":
            continue
        for keyword in node.keywords:
            if keyword.arg == "tool_name" and isinstance(keyword.value, ast.Constant):
                names.add(str(keyword.value.value))
    return names


def test_model_facing_signatures_do_not_accept_trusted_authority() -> None:
    expected = {
        "novel_library_query": {
            "kind",
            "proposal_id",
            "asset_id",
            "asset_type",
            "include_archived",
            "search",
            "limit",
        },
        "novel_library_prepare_change": {
            "actions",
            "source",
            "idempotency_key",
        },
        "novel_library_apply_change": {
            "proposal_id",
            "proposal_version",
            "mode",
        },
    }

    for name, parameters in expected.items():
        actual = set(inspect.signature(getattr(tools, name)).parameters)
        assert actual == parameters
        assert actual.isdisjoint(FORBIDDEN_MODEL_AUTHORITY)


def test_query_wrapper_commits_once_and_passes_only_query_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _install_session(monkeypatch)
    calls: list[tuple[object, object]] = []

    def operation(active_session: object, payload: object) -> dict[str, object]:
        calls.append((active_session, payload))
        return {"kind": "assets", "items": []}

    monkeypatch.setattr(tools, "_novel_library_query", operation)

    result = json.loads(
        asyncio.run(
            tools.novel_library_query(
                asset_type="vocabulary",
                include_archived=True,
                search="潮湿",
                limit=12,
            )
        )
    )

    assert result == {"kind": "assets", "items": []}
    assert calls == [
        (
            session,
            {
                "kind": "assets",
                "asset_type": "vocabulary",
                "include_archived": True,
                "search": "潮湿",
                "limit": 12,
            },
        )
    ]
    assert session.commits == 1
    assert session.rollbacks == 0


def test_prepare_wrapper_omits_empty_optional_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _install_session(monkeypatch)
    received: list[object] = []

    def operation(_session: object, payload: object) -> dict[str, object]:
        received.append(payload)
        return {"state": "proposed"}

    monkeypatch.setattr(tools, "_novel_library_prepare_change", operation)

    result = json.loads(
        asyncio.run(
            tools.novel_library_prepare_change(
                [{"operation": "create_asset", "payload": {"title": "雨夜"}}]
            )
        )
    )

    assert result == {"state": "proposed"}
    assert received == [
        {"actions": [{"operation": "create_asset", "payload": {"title": "雨夜"}}]}
    ]
    assert session.commits == 1
    assert session.rollbacks == 0


def test_apply_wrapper_rolls_back_unknown_failure_without_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _install_session(monkeypatch)
    calls = 0

    def operation(_session: object, _payload: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        raise RuntimeError("database result unknown")

    monkeypatch.setattr(tools, "_novel_library_apply_change", operation)

    with pytest.raises(RuntimeError, match="database result unknown"):
        asyncio.run(
            tools.novel_library_apply_change(
                "1afb7537-326d-4021-a718-e9407342cddd",
                3,
            )
        )

    assert calls == 1
    assert session.commits == 0
    assert session.rollbacks == 1


def test_manifest_registration_and_lifecycle_expectations_are_aligned() -> None:
    manifest = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
    manifest_names = {item["name"] for item in manifest["meta"]["tools"]}
    lifecycle_source = (
        ROOT / "scripts" / "tts" / "verify_qwenpaw_plugin_lifecycle.py"
    ).read_text(encoding="utf-8")

    assert MAINTENANCE_TOOLS <= manifest_names
    assert manifest_names == _registered_tool_names()
    for tool_name in MAINTENANCE_TOOLS:
        assert f'"{tool_name}"' in lifecycle_source
