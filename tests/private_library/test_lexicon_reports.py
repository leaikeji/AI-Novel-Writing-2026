from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from backend.models import CreativeGenerationJob, Document, DocumentWorkingCopy
from backend.private_library.errors import (
    PrivateLibraryConflictError,
    PrivateLibraryValidationError,
)
from backend.private_library.lexicon_contracts import LexiconEntry
from backend.private_library.lexicon_reports import (
    append_check_decisions,
    check_report_payload,
    create_or_reuse_check_report,
    unresolved_forbid_hit_ids,
)
from backend.private_library.lexicon_service import (
    EffectiveLexiconPolicy,
    EffectiveLexiconRule,
)
from backend.private_library.maintenance_contracts import LibraryCheckTextRef


def _policy(novel_id):
    asset_id, version_id = uuid4(), uuid4()
    entry = LexiconEntry(
        entry_id="entry_0001", term="眼底闪过", action="forbid",
    )
    return EffectiveLexiconPolicy(
        novel_id=novel_id,
        rules=(EffectiveLexiconRule(asset_id, version_id, entry, 0),),
        conflicts=(),
        rules_hash="a" * 64,
    )


def _ref(novel_id, document_id, text):
    import hashlib

    return LibraryCheckTextRef(
        source_kind="working_copy",
        novel_id=novel_id,
        document_id=document_id,
        version=4,
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
    )


def _read_session(monkeypatch, novel_id, document_id, source, policy, *, job=None):
    session = MagicMock(spec=Session)
    document = Document(id=document_id, novel_id=novel_id, title="潮声", position=1)
    session.get.side_effect = lambda model, _id, **_kw: (
        document if model is Document else job if model is CreativeGenerationJob else source
    )
    session.scalar.side_effect = lambda statement: (
        source if statement.column_descriptions[0]["entity"] is DocumentWorkingCopy else None
    )
    monkeypatch.setattr("backend.private_library.lexicon_reports.lock_active_novel", lambda *_: object())
    monkeypatch.setattr(
        "backend.private_library.lexicon_reports.resolve_effective_lexicon_policy",
        lambda *_a, **_kw: policy,
    )
    return session


def test_check_persists_exact_hash_rules_and_utf16_hits(monkeypatch) -> None:
    novel_id, document_id = uuid4(), uuid4()
    policy = _policy(novel_id)
    ref = _ref(novel_id, document_id, "🙂眼底闪过")
    session = _read_session(
        monkeypatch, novel_id, document_id,
        SimpleNamespace(draft_version=ref.version, content_hash=ref.text_sha256), policy,
    )

    result = create_or_reuse_check_report(
        session,
        text_ref=_ref(novel_id, document_id, "🙂眼底闪过"),
        source_markdown="🙂眼底闪过",
        policy=policy,
        source_id=document_id,
    )

    assert result.replayed is False
    assert result.report.status == "complete"
    assert result.report.hits_json[0]["start_utf16"] == 2
    assert result.report.hits_json[0]["end_utf16"] == 6
    assert result.report.hits_json[0]["count"] == 1
    assert result.report.scanned_rule_count == 1
    assert result.report.omitted_rule_count == 0
    assert result.report.visible_character_count == 5
    assert result.report.text_hash == _ref(
        novel_id, document_id, "🙂眼底闪过"
    ).text_sha256
    session.add.assert_called_once_with(result.report)
    session.flush.assert_called_once()


def test_selection_check_only_blocks_new_or_touched_forbid_hits(monkeypatch) -> None:
    novel_id, document_id, job_id = uuid4(), uuid4(), uuid4()
    baseline = "眼底闪过。旧句。"
    final = "眼底闪过。眼底闪过。"
    policy = _policy(novel_id)
    source = SimpleNamespace(draft_version=4, content_hash=_ref(novel_id, document_id, baseline).text_sha256)
    job = SimpleNamespace(
        novel_id=novel_id, document_id=document_id, kind="selection_edit", state="ready", attempt=4,
        input_snapshot={"base": {
            "persistence_version_kind": "draft", "persistence_version": 4,
            "field_value_sha256": source.content_hash, "start_utf16": 5, "end_utf16": 8,
        }},
    )
    session = _read_session(monkeypatch, novel_id, document_id, source, policy, job=job)

    result = create_or_reuse_check_report(
        session,
        text_ref=_ref(novel_id, document_id, final).model_copy(
            update={"source_kind": "selection_result"}
        ),
        source_markdown=final,
        policy=policy,
        source_id=job_id,
        unchanged_baseline=(baseline, 5, 8),
    )

    assert len(result.report.hits_json) == 2
    assert result.report.decisions_json[0]["kind"] == "preexisting_unchanged"
    assert tuple(str(item) for item in unresolved_forbid_hit_ids(result.report)) == (
        result.report.hits_json[1]["hit_id"],
    )
    session.commit.assert_not_called()


def test_check_rejects_changed_text_before_scan(monkeypatch) -> None:
    session = MagicMock(spec=Session)
    novel_id, document_id = uuid4(), uuid4()
    monkeypatch.setattr(
        "backend.private_library.lexicon_reports.lock_active_novel",
        lambda *_args: object(),
    )
    with pytest.raises(PrivateLibraryConflictError):
        create_or_reuse_check_report(
            session,
            text_ref=_ref(novel_id, document_id, "原文"),
            source_markdown="已变化",
            policy=_policy(novel_id),
            source_id=document_id,
        )
    session.add.assert_not_called()


def test_decisions_are_cas_appended_and_do_not_rewrite_hits() -> None:
    session = MagicMock(spec=Session)
    novel_id = uuid4()
    hit_id = uuid4()
    report = SimpleNamespace(
        id=uuid4(), novel_id=novel_id, document_id=uuid4(),
        source_kind="candidate", source_id=uuid4(), source_version=1,
        text_hash="a" * 64, rules_hash="b" * 64,
        scanner_version="lexicon-matcher/1", status="complete",
        scanned_rule_count=1, omitted_rule_count=0, visible_character_count=4,
        hits_json=[{"hit_id": str(hit_id), "action": "forbid"}],
        decisions_json=[], version=2, updated_at=None,
    )
    session.scalar.return_value = report

    updated = append_check_decisions(
        session,
        novel_id=novel_id,
        report_id=report.id,
        expected_version=2,
        keep_hit_ids=[hit_id],
    )

    assert updated.hits_json == [{"hit_id": str(hit_id), "action": "forbid"}]
    assert updated.version == 3
    assert unresolved_forbid_hit_ids(updated) == ()
    assert check_report_payload(updated)["unresolved_forbid_hit_ids"] == []
    payload = check_report_payload(updated)
    assert payload["schema_version"] == "library-check/1"
    assert payload["id"] == str(report.id)
    assert payload["text_sha256"] == "a" * 64
    assert payload["rules_sha256"] == "b" * 64


def test_decisions_reject_unknown_hits_and_incomplete_skip_on_complete() -> None:
    session = MagicMock(spec=Session)
    novel_id = uuid4()
    report = SimpleNamespace(
        id=uuid4(), novel_id=novel_id, document_id=uuid4(),
        source_kind="working_copy", source_id=uuid4(), source_version=1,
        text_hash="a" * 64, rules_hash="b" * 64,
        scanner_version="lexicon-matcher/1", status="complete",
        scanned_rule_count=0, omitted_rule_count=0, visible_character_count=0,
        hits_json=[], decisions_json=[], version=1, updated_at=None,
    )
    session.scalar.return_value = report
    with pytest.raises(PrivateLibraryValidationError):
        append_check_decisions(
            session,
            novel_id=novel_id,
            report_id=report.id,
            expected_version=1,
            keep_hit_ids=[uuid4()],
        )
    with pytest.raises(PrivateLibraryValidationError):
        append_check_decisions(
            session,
            novel_id=novel_id,
            report_id=report.id,
            expected_version=1,
            skip_incomplete=True,
        )


def test_report_scan_releases_read_transaction_before_any_write_lock(monkeypatch) -> None:
    from backend.private_library import lexicon_reports

    novel_id, document_id = uuid4(), uuid4()
    policy = _policy(novel_id)
    ref = _ref(novel_id, document_id, "潮声")
    session = _read_session(
        monkeypatch, novel_id, document_id,
        SimpleNamespace(draft_version=4, content_hash=ref.text_sha256), policy,
    )
    events = []
    session.rollback.side_effect = lambda: events.append("read-transaction-ended")
    match = lexicon_reports.match_lexicon

    def scan(*args, **kwargs):
        assert events == ["read-transaction-ended"]
        events.append("scan")
        return match(*args, **kwargs)

    monkeypatch.setattr(lexicon_reports, "match_lexicon", scan)
    monkeypatch.setattr(lexicon_reports, "lock_active_novel", lambda *_: events.append("write-lock"))
    create_or_reuse_check_report(
        session, text_ref=ref, source_markdown="潮声", policy=policy, source_id=document_id,
    )
    assert events == ["read-transaction-ended", "scan", "write-lock"]
    session.commit.assert_not_called()


@pytest.mark.parametrize("drift", ["text", "rules"])
def test_scan_drift_returns_conflict_without_an_uncommitted_report_id(monkeypatch, drift) -> None:
    from dataclasses import replace
    from backend.private_library import lexicon_reports

    novel_id, document_id = uuid4(), uuid4()
    policy = _policy(novel_id)
    ref = _ref(novel_id, document_id, "潮声")
    working = SimpleNamespace(draft_version=4, content_hash=ref.text_sha256)
    session = _read_session(monkeypatch, novel_id, document_id, working, policy)
    match = lexicon_reports.match_lexicon

    def scan(*args, **kwargs):
        if drift == "text":
            working.draft_version = 5
        else:
            monkeypatch.setattr(
                lexicon_reports, "resolve_effective_lexicon_policy",
                lambda *_a, **_kw: replace(policy, rules_hash="b" * 64),
            )
        return match(*args, **kwargs)

    monkeypatch.setattr(lexicon_reports, "match_lexicon", scan)
    with pytest.raises(PrivateLibraryConflictError) as error:
        create_or_reuse_check_report(
            session, text_ref=ref, source_markdown="潮声", policy=policy, source_id=document_id,
        )
    assert "report_id" not in error.value.current
    session.add.assert_not_called()
    session.commit.assert_not_called()


def test_check_does_not_rollback_a_callers_pending_write(monkeypatch) -> None:
    novel_id, document_id = uuid4(), uuid4()
    session = MagicMock(spec=Session)
    session.new = {object()}
    with pytest.raises(PrivateLibraryValidationError, match="before starting"):
        create_or_reuse_check_report(
            session, text_ref=_ref(novel_id, document_id, "潮声"),
            source_markdown="潮声", policy=_policy(novel_id), source_id=document_id,
        )
    session.rollback.assert_not_called()


def test_201_decisions_require_two_cas_batches_and_never_select_the_rest() -> None:
    session = MagicMock(spec=Session)
    hit_ids = [uuid4() for _ in range(201)]
    report = SimpleNamespace(
        id=uuid4(), novel_id=uuid4(), version=1, status="complete",
        text_hash="a" * 64, rules_hash="b" * 64,
        hits_json=[{"hit_id": str(hit_id), "action": "forbid"} for hit_id in hit_ids],
        decisions_json=[],
    )
    session.scalar.return_value = report
    with pytest.raises(PrivateLibraryValidationError, match="200"):
        append_check_decisions(
            session, novel_id=report.novel_id, report_id=report.id,
            expected_version=1, keep_hit_ids=hit_ids,
        )
    append_check_decisions(
        session, novel_id=report.novel_id, report_id=report.id,
        expected_version=1, keep_hit_ids=hit_ids[:200],
    )
    assert report.version == 2
    assert unresolved_forbid_hit_ids(report) == (hit_ids[-1],)
    with pytest.raises(PrivateLibraryConflictError):
        append_check_decisions(
            session, novel_id=report.novel_id, report_id=report.id,
            expected_version=1, keep_hit_ids=hit_ids[-1:],
        )
    assert unresolved_forbid_hit_ids(report) == (hit_ids[-1],)
    append_check_decisions(
        session, novel_id=report.novel_id, report_id=report.id,
        expected_version=2, keep_hit_ids=hit_ids[-1:],
    )
    assert report.version == 3
    assert unresolved_forbid_hit_ids(report) == ()
    assert not any(item["kind"] == "application" for item in report.decisions_json)
