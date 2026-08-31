from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.character_workspace import api
from backend.creative_authority import AuthorityConflictError


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class WorkspaceResult:
    def __init__(self, value: dict[str, object]) -> None:
        self.value = value

    def model_dump(self, *, mode: str) -> dict[str, object]:
        assert mode == "json"
        return self.value


def request() -> api.CharacterWorkspaceSaveRequestV2:
    return api.CharacterWorkspaceSaveRequestV2(
        operation_key="character-workspace:test",
        selected_timeline_id=uuid4(),
        selected_instance_id=uuid4(),
        expected_character_catalog_version=4,
        expected_story_ledger_version=8,
        expected_character_version=3,
        expected_instance_version=6,
        root_patch={
            "name": "沈砚",
            "role_type": "main",
            "description": "调查记者",
            "gender": "男",
            "core_theme": "真相",
        },
        profile={
            "schema_version": "character-instance-profile/2",
            "occupation": "记者",
            "goals": ["查清真相"],
        },
    )


def test_put_commits_both_aggregates_once_and_returns_v2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    expected = {"schema_version": "character-workspace/2", "novel_id": "novel"}
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        api,
        "save_character_workspace",
        lambda *_args, **kwargs: calls.append(kwargs),
    )
    monkeypatch.setattr(
        api,
        "service_for_session",
        lambda _session: SimpleNamespace(
            get_workspace=lambda *_args, **_kwargs: WorkspaceResult(expected)
        ),
    )

    result = api.character_workspace_put(
        uuid4(),
        uuid4(),
        request(),
        session,  # type: ignore[arg-type]
    )

    assert result == expected
    assert session.commits == 1
    assert session.rollbacks == 0
    assert len(calls) == 1
    assert calls[0]["root_patch"]["name"] == "沈砚"  # type: ignore[index]
    assert calls[0]["profile"].schema_version == "character-instance-profile/2"  # type: ignore[union-attr]


def test_put_rolls_back_everything_and_returns_current_workspace_on_cas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    current = {"schema_version": "character-workspace/2", "character": {"version": 4}}
    monkeypatch.setattr(
        api,
        "save_character_workspace",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AuthorityConflictError("character_version_conflict", current={"version": 4})
        ),
    )
    monkeypatch.setattr(
        api,
        "service_for_session",
        lambda _session: SimpleNamespace(
            get_workspace=lambda *_args, **_kwargs: WorkspaceResult(current)
        ),
    )

    with pytest.raises(HTTPException) as caught:
        api.character_workspace_put(
            uuid4(),
            uuid4(),
            request(),
            session,  # type: ignore[arg-type]
        )

    assert session.commits == 0
    assert session.rollbacks == 1
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "cas_conflict"
    assert caught.value.detail["current_workspace"] == current


def test_get_accepts_numeric_v2_query_through_fastapi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = {"schema_version": "character-workspace/2"}
    observed: list[int] = []
    monkeypatch.setattr(
        api,
        "service_for_session",
        lambda _session: SimpleNamespace(
            get_workspace=lambda *_args, **kwargs: (
                observed.append(kwargs["view_version"]) or WorkspaceResult(expected)
            )
        ),
    )
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_session] = lambda: FakeSession()

    with TestClient(app) as client:
        response = client.get(
            f"/novels/{uuid4()}/characters/{uuid4()}/workspace",
            params={"view_version": 2},
        )

    assert response.status_code == 200
    assert response.json() == expected
    assert observed == [2]
