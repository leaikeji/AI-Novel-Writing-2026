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
from backend.story_state.corrections import (
    StoryCorrectionError,
    StoryCorrectionErrorCode,
    revert_intelligence_batch,
)


NOW = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)


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


def test_batch_revert_changes_batch_authority_without_rewriting_fact_lifecycle() -> None:
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
    assert result["changed"] is True
    assert result["outcome"] == "reverted"
    assert owned.status == "active"
    assert binding.validity_state == "current"
    assert batch.state == "reverted"
    assert novel.story_ledger_version == 10

    replayed = revert_intelligence_batch(
        BatchSession(novel, batch, proposal, owned),  # type: ignore[arg-type]
        novel.id,
        batch.id,
        expected_story_ledger_version=1,
        operation_key="revert-batch-1",
        reason="作者撤销误同步",
    )
    assert replayed["replayed"] is True
    assert replayed["changed"] is False
    assert replayed["outcome"] == "already_reverted"
    assert novel.story_ledger_version == 10

    with pytest.raises(StoryCorrectionError) as conflict:
        revert_intelligence_batch(
            BatchSession(novel, batch, proposal, owned),  # type: ignore[arg-type]
            novel.id,
            batch.id,
            expected_story_ledger_version=10,
            operation_key="revert-batch-1",
            reason="另一份撤销理由",
        )
    assert conflict.value.code == StoryCorrectionErrorCode.IDEMPOTENCY_CONFLICT
    assert novel.story_ledger_version == 10


def test_no_change_receipt_is_not_a_revertible_committed_batch() -> None:
    novel = Novel(id=uuid4(), title="测试", story_ledger_version=9)
    owned = fact(novel.id)
    proposal = IntelligenceProposal(id=uuid4(), novel_id=novel.id)
    batch = IntelligenceCommitBatch(
        id=uuid4(),
        proposal_id=proposal.id,
        chapter_revision_id=uuid4(),
        commit_key="n" * 64,
        state="no_change",
        accepted_item_ids=[str(uuid4())],
        inverse_operations={
            "schema_version": "intelligence-commit-inverse/2",
            "created_story_fact_ids": [],
            "changed": False,
        },
        expected_story_ledger_version=9,
    )

    with pytest.raises(StoryCorrectionError) as raised:
        revert_intelligence_batch(
            BatchSession(novel, batch, proposal, owned),  # type: ignore[arg-type]
            novel.id,
            batch.id,
            expected_story_ledger_version=9,
            operation_key="revert-no-change",
        )

    assert raised.value.code == StoryCorrectionErrorCode.INVALID_TARGET
    assert batch.state == "no_change"
    assert novel.story_ledger_version == 9


def test_legacy_empty_committed_batch_cannot_create_a_false_revert() -> None:
    novel = Novel(id=uuid4(), title="测试", story_ledger_version=9)
    owned = fact(novel.id)
    proposal = IntelligenceProposal(id=uuid4(), novel_id=novel.id)
    batch = IntelligenceCommitBatch(
        id=uuid4(),
        proposal_id=proposal.id,
        chapter_revision_id=uuid4(),
        commit_key="e" * 64,
        state="committed",
        accepted_item_ids=[],
        inverse_operations={"created_story_fact_ids": [], "changed": False},
        expected_story_ledger_version=8,
    )

    with pytest.raises(StoryCorrectionError) as raised:
        revert_intelligence_batch(
            BatchSession(novel, batch, proposal, owned),  # type: ignore[arg-type]
            novel.id,
            batch.id,
            expected_story_ledger_version=9,
            operation_key="revert-empty",
        )

    assert raised.value.code == StoryCorrectionErrorCode.INVALID_TARGET
    assert batch.state == "committed"
    assert novel.story_ledger_version == 9


class ReconcileSession:
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

    result = services._reconcile_story_facts_for_revision(
        ReconcileSession(),  # type: ignore[arg-type]
        document_id,
        revision,
        restored=True,
    )

    assert result == {
        "changed": True,
        "metadata_changed": False,
        "target_revision_id": str(revision.id),
        "changed_binding_ids": [str(binding.id)],
        "metadata_changed_binding_ids": [],
        "changed_fact_ids": [str(row.id)],
        "activated_binding_ids": [str(binding.id)],
        "invalidated_binding_ids": [],
    }
    assert binding.validity_state == "source_restored"
    assert row.status == "superseded"

    restored_at = binding.restored_at
    replay = services._reconcile_story_facts_for_revision(
        ReconcileSession(),  # type: ignore[arg-type]
        document_id,
        revision,
        restored=True,
    )
    assert replay["changed"] is False
    assert replay["metadata_changed"] is False
    assert binding.restored_at == restored_at


def test_revision_reconcile_invalidates_only_the_fact_specific_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = uuid4()
    revision = DocumentRevision(
        id=uuid4(),
        document_id=document_id,
        revision_number=3,
        content_markdown="新版本",
        content_text="新版本",
        content_hash="f" * 64,
        source="manual",
    )
    row = fact(uuid4(), status="active")
    binding = DerivedSourceBinding(
        id=uuid4(),
        derived_entity_id=row.id,
        source_chapter_id=document_id,
        source_chapter_revision_id=uuid4(),
        source_content_hash="a" * 64,
        validity_state="current",
    )
    monkeypatch.setattr(
        services,
        "_document_fact_binding_rows",
        lambda *_args, **_kwargs: [(binding, row)],
    )

    result = services._reconcile_story_facts_for_revision(
        ReconcileSession(),  # type: ignore[arg-type]
        document_id,
        revision,
    )

    assert result["changed"] is True
    assert result["invalidated_binding_ids"] == [str(binding.id)]
    assert binding.validity_state == "source_superseded"
    assert binding.invalidated_at is not None
    assert row.status == "active"


def test_reconcile_metadata_repair_does_not_report_authority_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = uuid4()
    revision = DocumentRevision(
        id=uuid4(),
        document_id=document_id,
        revision_number=4,
        content_markdown="当前版本",
        content_text="当前版本",
        content_hash="1" * 64,
        source="manual",
    )
    row = fact(uuid4(), status="active")
    binding = DerivedSourceBinding(
        id=uuid4(),
        derived_entity_id=row.id,
        source_chapter_id=document_id,
        source_chapter_revision_id=revision.id,
        source_content_hash=revision.content_hash,
        validity_state="current",
        invalidated_at=NOW,
        restored_at=NOW,
    )
    monkeypatch.setattr(
        services,
        "_document_fact_binding_rows",
        lambda *_args, **_kwargs: [(binding, row)],
    )

    result = services._reconcile_story_facts_for_revision(
        ReconcileSession(),  # type: ignore[arg-type]
        document_id,
        revision,
    )

    assert result["changed"] is False
    assert result["metadata_changed"] is True
    assert result["metadata_changed_binding_ids"] == [str(binding.id)]
    assert binding.validity_state == "current"
    assert binding.invalidated_at is None
    assert binding.restored_at is None
