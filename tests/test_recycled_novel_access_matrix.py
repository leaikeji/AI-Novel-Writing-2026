from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend import creative_data_api
from backend.character_workspace import api as character_workspace_api
from backend.creative_authority import service as authority_service
from backend.novel_lifecycle_errors import NovelRecycledError
from backend.story_ledger import api as story_ledger_api
from backend.story_state import api as story_state_api
from backend.writing_skills import button as writing_button


def _recycled_novel():
    return SimpleNamespace(
        id=uuid4(),
        recycled_at=datetime.now(timezone.utc),
    )


class _ScalarSession:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar(self, _statement):  # type: ignore[no-untyped-def]
        return self.value


@pytest.mark.parametrize(
    "adapter",
    (
        creative_data_api._raise,
        story_state_api._raise,
        story_ledger_api._raise,
        character_workspace_api._raise_workspace_error,
    ),
)
def test_http_adapters_map_recycled_to_stable_410(adapter) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(HTTPException) as raised:
        adapter(NovelRecycledError("小说已移入回收站"))

    assert raised.value.status_code == 410
    assert raised.value.detail == {
        "type": "novel_recycled",
        "message": "小说已移入回收站",
    }


def test_authority_write_rejects_recycled_before_child_locks() -> None:
    novel = _recycled_novel()

    with pytest.raises(NovelRecycledError):
        authority_service._lock_novel(_ScalarSession(novel), novel.id)  # type: ignore[arg-type]


def test_document_scoped_writing_history_maps_recycled_to_410(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel = _recycled_novel()
    document_id = uuid4()
    row = SimpleNamespace(
        id=document_id,
        kind="chapter",
        novel_id=novel.id,
        owner_id=uuid4(),
        workspace_id=uuid4(),
    )
    session = SimpleNamespace(
        execute=lambda _statement: SimpleNamespace(first=lambda: row)
    )
    monkeypatch.setattr(
        writing_button,
        "require_active_novel",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            NovelRecycledError("小说已移入回收站")
        ),
    )

    with pytest.raises(HTTPException) as raised:
        writing_button._scope(session, document_id, "tab")

    assert raised.value.status_code == 410
    assert raised.value.detail["type"] == "novel_recycled"
