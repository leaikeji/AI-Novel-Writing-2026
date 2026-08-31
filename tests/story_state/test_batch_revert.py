from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend import services
from backend.models import (
    DerivedSourceBinding,
    DocumentRevision,
    IntelligenceCommitBatch,
    IntelligenceProposal,
    Novel,
    StoryFact,
)
from backend.story_state.corrections import revert_intelligence_batch


NOW = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)


class ScalarPages:
    def __init__(self, pages: list[list[object]]) -> None:
        self.pages = pages

    def scalars(self, _statement):
        return iter(self.pages.pop(0))


def fact(novel_id, *, status: str = "active") -> StoryFact:
    return StoryFact(
        id=uuid4(),
        novel_id=novel_id,
        schema_version="story-fact/2",
        fact_type="general_fact",
        subject="潮汐",
        predicate="状态",
        object_text="升高",
        details={"schema_version": "general-fact/1", "value": "升高"},
        timeline_id=uuid4(),
        dimension="tide",
        event_kind="changed",
        visibility_json={"schema_version": "story-visibility/1", "scope": "author"},
        event_fingerprint="b" * 64,
        status=status,
        created_at=NOW,
    )


class BatchSession:
    def __init__(self, novel, batch, proposal, owned_fact) -> None:
        self.novel = novel
        self.batch = batch
        self.proposal = proposal
        self.owned_fact = owned_fact

    def scalar(self, _statement):
        return self.novel

    def execute(self, _statement):
        return SimpleNamespace(one_or_none=lambda: (self.batch, self.proposal))

    def scalars(self, _statement):
        if not hasattr(self, "_scalars_calls"):
            self._scalars_calls = 1
            return iter([self.owned_fact.id])
        return iter([self.owned_fact])

    def flush(self) -> None:
        return None


def test_batch_revert_marks_only_owned_facts_without_invalidating_bindings() -> None:
    novel = Novel(id=uuid4(), title="测试", story_ledger_version=9)
    owned = fact(novel.id)
    proposal = IntelligenceProposal(id=uuid4(), novel_id=novel.id)
    batch = IntelligenceCommitBatch(
        id=uuid4(),
        proposal_id=proposal.id,
        chapter_revision_id=uuid4(),
        commit_key="c" * 64,
        state="committed",
        accepted_item_ids=[],
        inverse_operations={"created_story_fact_ids": [str(owned.id)]},
        expected_story_ledger_version=8,
    )
    binding = DerivedSourceBinding(
        id=uuid4(),
        derived_entity_type="story_fact",
        derived_entity_id=owned.id,
        source_chapter_id=uuid4(),
        source_chapter_revision_id=uuid4(),
        source_content_hash="d" * 64,
        commit_batch_id=batch.id,
        validity_state="current",
    )

    result = revert_intelligence_batch(
        BatchSession(novel, batch, proposal, owned),  # type: ignore[arg-type]
        novel.id,
        batch.id,
        expected_story_ledger_version=9,
        operation_key="revert-batch-1",
        reason="作者撤销误同步",
    )

    assert result["replayed"] is False
    assert owned.status == "superseded"
    assert binding.validity_state == "current"
    assert batch.state == "reverted"
    assert novel.story_ledger_version == 10


class ReconcileSession(ScalarPages):
    pass


def test_source_restore_never_reactivates_a_reverted_batch_fact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = uuid4()
    batch_id = uuid4()
    revision = DocumentRevision(
        id=uuid4(),
        document_id=document_id,
        revision_number=2,
        content_markdown="潮水回来了",
        content_text="潮水回来了",
        content_hash="e" * 64,
        source="manual",
    )
    row = fact(uuid4(), status="superseded")
    binding = DerivedSourceBinding(
        id=uuid4(),
        derived_entity_type="story_fact",
        derived_entity_id=row.id,
        source_chapter_id=document_id,
        source_chapter_revision_id=revision.id,
        source_content_hash=revision.content_hash,
        commit_batch_id=batch_id,
        validity_state="source_superseded",
    )
    monkeypatch.setattr(
        services,
        "_document_fact_binding_rows",
        lambda *_args, **_kwargs: [(binding, row)],
    )

    services._reconcile_story_facts_for_revision(
        ReconcileSession([[batch_id]]),  # type: ignore[arg-type]
        document_id,
        revision,
        restored=True,
    )

    assert binding.validity_state == "source_restored"
    assert row.status == "superseded"
