from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from backend.creative_data_models import StoryEventLink
from backend.models import Novel, StoryFact
from backend.story_state.corrections import (
    StoryCorrectionError,
    StoryCorrectionErrorCode,
    correct_story_fact,
)


NOW = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)


class FakeSession:
    def __init__(self, scalar_results: list[object | None]) -> None:
        self.scalar_results = list(scalar_results)
        self.added: list[object] = []

    def scalar(self, _statement):
        return self.scalar_results.pop(0)

    def add(self, row: object) -> None:
        self.added.append(row)

    def flush(self) -> None:
        return None

    def get(self, _model, _identity):
        return None


def target_fact(novel_id):
    return StoryFact(
        id=uuid4(),
        novel_id=novel_id,
        schema_version="story-fact/2",
        fact_type="character_state",
        subject="沈砚",
        predicate="location",
        object_text="旧港",
        details={"schema_version": "character-state/1", "value": "旧港"},
        timeline_id=uuid4(),
        character_id=uuid4(),
        character_instance_id=uuid4(),
        dimension="location",
        event_kind="state",
        story_sequence=8,
        visibility_json={"schema_version": "story-visibility/1", "scope": "author"},
        event_fingerprint="a" * 64,
        status="active",
        created_at=NOW,
    )


def test_correction_creates_new_fact_and_supersedes_link_without_mutating_target() -> None:
    novel = Novel(id=uuid4(), title="测试", story_ledger_version=5)
    target = target_fact(novel.id)
    session = FakeSession([novel, target, None, None])

    result = correct_story_fact(
        session,
        novel.id,
        target.id,
        expected_story_ledger_version=5,
        operation_key="fix-location-1",
        reason="章节中已经离开旧港",
        replacement={
            "object_text": "北站",
            "details": {"schema_version": "character-state/1", "value": "北站"},
        },
    )

    replacement = next(row for row in session.added if isinstance(row, StoryFact))
    link = next(row for row in session.added if isinstance(row, StoryEventLink))
    assert replacement.object_text == "北站"
    assert replacement.character_id == target.character_id
    assert replacement.event_fingerprint != target.event_fingerprint
    assert link.source_fact_id == replacement.id
    assert link.target_fact_id == target.id
    assert link.link_type == "supersedes"
    assert target.status == "active"
    assert novel.story_ledger_version == 6
    assert result["replayed"] is False


def test_same_operation_key_with_different_payload_is_rejected() -> None:
    novel = Novel(id=uuid4(), title="测试", story_ledger_version=6)
    target = target_fact(novel.id)
    replay = target_fact(novel.id)
    replay.event_fingerprint = __import__("hashlib").sha256(
        f"manual-correction-v1|{novel.id}|{target.id}|same-key".encode("utf-8")
    ).hexdigest()
    link = StoryEventLink(
        id=uuid4(),
        novel_id=novel.id,
        source_fact_id=replay.id,
        target_fact_id=target.id,
        link_type="supersedes",
        details_json={"operation_hash": "not-the-new-hash"},
        created_at=NOW,
    )
    session = FakeSession([novel, target, replay, link])

    with pytest.raises(StoryCorrectionError) as caught:
        correct_story_fact(
            session,
            novel.id,
            target.id,
            expected_story_ledger_version=1,
            operation_key="same-key",
            reason="另一份理由",
            replacement={"object_text": "新地点"},
        )

    assert caught.value.code is StoryCorrectionErrorCode.IDEMPOTENCY_CONFLICT
    assert novel.story_ledger_version == 6


def test_correction_rejects_a_reason_only_noop() -> None:
    novel = Novel(id=uuid4(), title="测试", story_ledger_version=5)
    target = target_fact(novel.id)
    session = FakeSession([novel, target, None, None])

    with pytest.raises(StoryCorrectionError) as caught:
        correct_story_fact(
            session,
            novel.id,
            target.id,
            expected_story_ledger_version=5,
            operation_key="noop-1",
            reason="没有真正修改",
            replacement={"object_text": target.object_text},
        )

    assert caught.value.code is StoryCorrectionErrorCode.INVALID_REPLACEMENT
    assert novel.story_ledger_version == 5
