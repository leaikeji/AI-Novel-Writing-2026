from __future__ import annotations

from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError as PydanticValidationError
import pytest

from backend.creative_schemas import PurgeRecycledNovelRequest
from tests.writing_e2e._host_stub import FakeSession, import_creative_api


def test_delete_route_moves_permanent_delete_to_recycle_bin(monkeypatch) -> None:
    api = import_creative_api(monkeypatch)
    novel_id = uuid4()
    with pytest.raises(HTTPException) as captured:
        api.novels_delete(novel_id, expected_version=7, session=FakeSession())
    assert captured.value.status_code == 409
    assert captured.value.detail["type"] == "permanent_delete_moved_to_recycle_bin"


def test_purge_contract_requires_the_exact_typed_phrase() -> None:
    with pytest.raises(PydanticValidationError):
        PurgeRecycledNovelRequest(expected_version=7, confirmation_text="确认")
    with pytest.raises(PydanticValidationError):
        PurgeRecycledNovelRequest(
            expected_version=7,
            confirmation_text="确认删除",
            backup_receipt="/tmp/forbidden.json",
        )


def test_purge_route_uses_server_owned_typed_confirmation_context(monkeypatch) -> None:
    api = import_creative_api(monkeypatch)
    from backend.narration import production_runtime

    novel_id = uuid4()
    runtime = object()
    monkeypatch.setattr(production_runtime, "current_narration_cache_runtime", lambda: runtime)
    load = monkeypatch.setattr
    calls: list[tuple[object, ...]] = []

    def fake_delete(actual_runtime, target, *, expected_version, maintenance):  # type: ignore[no-untyped-def]
        calls.append(
            (
                "delete",
                actual_runtime,
                target,
                expected_version,
                maintenance.novel_id,
                maintenance.expected_version,
            )
        )
        return {"deleted": True, "deleted_document_ids": []}

    load(api, "delete_novel_with_narration", fake_delete)
    result = api.recycle_bin_purge(
        novel_id,
        PurgeRecycledNovelRequest(expected_version=7, confirmation_text="确认删除"),
    )

    assert result["deleted"] is True
    assert calls == [
        ("delete", runtime, novel_id, 7, novel_id, 7),
    ]


def test_purge_route_fails_closed_without_full_runtime(monkeypatch) -> None:
    api = import_creative_api(monkeypatch)
    from backend.narration import production_runtime

    monkeypatch.setattr(production_runtime, "current_narration_cache_runtime", lambda: None)
    with pytest.raises(HTTPException) as captured:
        api.recycle_bin_purge(
            uuid4(),
            PurgeRecycledNovelRequest(expected_version=7, confirmation_text="确认删除"),
        )
    assert captured.value.status_code == 503
    assert captured.value.detail["type"] == "novel_purge_runtime_unavailable"
