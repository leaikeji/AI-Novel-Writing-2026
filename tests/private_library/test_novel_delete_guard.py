from __future__ import annotations

from uuid import uuid4

import pytest

from backend.narration.novel_deletion import _require_private_library_purge_safe
from backend.services import ValidationError


class _ScalarSession:
    def __init__(self, value: int) -> None:
        self.value = value
        self.statement = ""
        self.parameters: dict[str, object] = {}

    def scalar(self, statement: object, parameters: dict[str, object]) -> int:
        self.statement = str(statement)
        self.parameters = parameters
        return self.value


def test_permanent_delete_allows_novel_without_plan74_owned_records() -> None:
    novel_id = uuid4()
    session = _ScalarSession(0)

    _require_private_library_purge_safe(session, novel_id)  # type: ignore[arg-type]

    assert session.parameters == {"novel_id": novel_id}
    assert "private_assets" in session.statement
    assert "library_check_reports" in session.statement
    assert "library_change_requests" in session.statement


def test_permanent_delete_blocks_when_private_library_evidence_would_be_lost() -> None:
    session = _ScalarSession(2)

    with pytest.raises(ValidationError, match="禁止永久删除"):
        _require_private_library_purge_safe(session, uuid4())  # type: ignore[arg-type]
