from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from backend.models import Novel, NovelLifecycleEvent
from backend.novel_lifecycle import recycle_novel, restore_novel
from backend.novel_lifecycle_errors import NovelLifecycleIdempotencyConflict


class ScalarQueueSession:
    def __init__(self, *values: object) -> None:
        self.values = list(values)
        self.added: list[object] = []
        self.flush_count = 0

    def scalar(self, _statement):  # type: ignore[no-untyped-def]
        return self.values.pop(0)

    def refresh(self, _row: object) -> None:
        return None

    def add(self, row: object) -> None:
        self.added.append(row)

    def flush(self) -> None:
        self.flush_count += 1


def novel(*, version: int = 3, recycled: bool = False) -> Novel:
    return Novel(
        id=uuid4(),
        title="验收小说",
        version=version,
        recycled_at=datetime.now(timezone.utc) if recycled else None,
        recycled_by="local-author" if recycled else None,
    )


def test_recycle_changes_only_lifecycle_and_records_one_receipt() -> None:
    target = novel()
    session = ScalarQueueSession(None, target, None, 0, 0, 0, 0, 0, 0)

    result = recycle_novel(session, target.id, 3, "recycle-1")  # type: ignore[arg-type]

    assert result["action"] == "recycled"
    assert result["version"] == 4
    assert result["replayed"] is False
    assert target.recycled_at is not None
    assert target.recycled_by == "local-author"
    assert session.flush_count == 1
    assert len(session.added) == 1
    event = session.added[0]
    assert isinstance(event, NovelLifecycleEvent)
    assert event.version_before == 3 and event.version_after == 4


def test_restore_preserves_identity_and_returns_degraded_warning() -> None:
    target = novel(version=4, recycled=True)
    session = ScalarQueueSession(None, target, None, 0, 0, 1)

    result = restore_novel(session, target.id, 4, "restore-1")  # type: ignore[arg-type]

    assert result == {
        "event_id": result["event_id"],
        "action": "restored",
        "version": 5,
        "recycled_at": None,
        "warning_codes": ["derived_media_missing"],
        "replayed": False,
    }
    assert target.recycled_at is None and target.recycled_by is None


def test_same_idempotency_key_with_different_digest_is_rejected() -> None:
    target = novel()
    event = NovelLifecycleEvent(
        id=uuid4(),
        novel_id=target.id,
        action="recycled",
        version_before=3,
        version_after=4,
        title_sha256="a" * 64,
        actor="local-author",
        idempotency_key="same-key",
        request_sha256="b" * 64,
        result_json={},
        occurred_at=datetime.now(timezone.utc),
    )
    session = ScalarQueueSession(event)

    with pytest.raises(NovelLifecycleIdempotencyConflict):
        recycle_novel(session, target.id, 3, "same-key")  # type: ignore[arg-type]


def test_successful_event_replays_before_current_state_check(monkeypatch) -> None:
    target = novel()
    expected = {
        "event_id": str(uuid4()),
        "action": "recycled",
        "version": 4,
        "recycled_at": datetime.now(timezone.utc).isoformat(),
        "warning_codes": [],
    }
    event = NovelLifecycleEvent(
        id=uuid4(),
        novel_id=target.id,
        action="recycled",
        version_before=3,
        version_after=4,
        title_sha256="a" * 64,
        actor="local-author",
        idempotency_key="replay-key",
        request_sha256="unused",
        result_json=expected,
        occurred_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr("backend.novel_lifecycle._request_digest", lambda *args: "unused")
    session = ScalarQueueSession(event)

    assert recycle_novel(session, target.id, 3, "replay-key") == {
        **expected,
        "replayed": True,
    }
    assert session.values == []
