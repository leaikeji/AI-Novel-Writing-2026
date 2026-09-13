from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend import services
from backend.creative_data_models import LibraryCheckReport, NovelAssetBinding
from backend.models import CandidateRevision, ChapterGenerationJob, DocumentRevision
from backend.private_library.errors import (
    PrivateLibraryConflictError, PrivateLibraryNotFoundError, PrivateLibraryValidationError,
)
from backend.private_library.lexicon_contracts import LexiconEntry
from backend.private_library.lexicon_reports import (
    append_check_decisions, create_or_reuse_check_report, require_application_report,
)
from backend.private_library.lexicon_service import (
    EffectiveLexiconPolicy, EffectiveLexiconRule, effective_policy_snapshot,
    resolve_effective_lexicon_policy,
)
from backend.private_library.maintenance_contracts import LibraryCheckTextRef
from backend.private_library.service import replace_novel_bindings

from .test_selection_apply_rules import enable_forbid, postgres_session, seed_novel


def _gate_fixture(*, forbid=True, present=True):
    novel_id, document_id, candidate_id = uuid4(), uuid4(), uuid4()
    rules = (EffectiveLexiconRule(
        uuid4(), uuid4(), LexiconEntry(entry_id="entry_0001", term="眼底闪过", action="forbid"), 0,
    ),) if forbid else ()
    policy = EffectiveLexiconPolicy(novel_id=novel_id, rules=rules, conflicts=(), rules_hash="a" * 64)
    report = SimpleNamespace(
        id=uuid4(), novel_id=novel_id, document_id=document_id,
        source_kind="candidate", source_id=candidate_id, version=1, status="complete",
        text_hash="b" * 64, rules_hash=policy.rules_hash, decisions_json=[], hits_json=[],
    )
    session = MagicMock(spec=Session)
    session.scalar.return_value = report if present else None
    session.get.return_value = report
    arguments = {
        "novel_id": novel_id, "document_id": document_id, "source_kind": "candidate",
        "source_id": candidate_id, "source_version": 1, "text_hash": report.text_hash,
        "policy": policy, "report_id": None, "expected_version": None,
        "allow_without_forbid": True,
    }
    return session, report, arguments


def test_current_forbid_requires_current_report_even_for_old_snapshot_free_candidate() -> None:
    session, _, arguments = _gate_fixture(present=False)
    with pytest.raises(PrivateLibraryConflictError) as error:
        require_application_report(session, **arguments)
    assert error.value.code == "library_check_required"
    assert error.value.current["candidate_id"] == str(arguments["source_id"])
    assert "report_id" not in error.value.current
    session.add.assert_not_called()
    session.commit.assert_not_called()


def test_legacy_no_current_forbid_does_not_depend_on_generation_time_report() -> None:
    session, _, arguments = _gate_fixture(forbid=False, present=False)
    assert require_application_report(session, **arguments) is None


def test_report_query_selects_full_current_source_identity_not_arbitrary_first_report() -> None:
    session, report, arguments = _gate_fixture()
    assert require_application_report(session, **arguments) is report
    statement = session.scalar.call_args.args[0]
    sql = str(statement)
    for field in (
        "novel_id", "document_id", "source_kind", "source_id", "source_version",
        "text_hash", "rules_hash", "scanner_version",
    ):
        assert f"library_check_reports.{field} =" in sql
    assert "FOR UPDATE" in sql


@pytest.mark.parametrize("status", ["failed", "stale", "incomplete"])
def test_noncomplete_reports_do_not_silently_authorize_adoption(status) -> None:
    session, report, arguments = _gate_fixture()
    report.status = status
    with pytest.raises(PrivateLibraryConflictError) as error:
        require_application_report(session, **arguments)
    assert error.value.code == "library_check_required"
    assert error.value.current["report_id"] == str(report.id)


def test_incomplete_skip_is_explicit_and_preserves_incomplete_status() -> None:
    session, report, arguments = _gate_fixture()
    report.status = "incomplete"
    result = require_application_report(
        session, **{**arguments, "report_id": report.id, "expected_version": 1}, skip_incomplete=True,
    )
    assert result.status == "incomplete"
    assert result.decisions_json[0]["kind"] == "skip_incomplete"


def test_report_version_is_checked_even_without_new_decisions() -> None:
    session, report, arguments = _gate_fixture()
    with pytest.raises(PrivateLibraryConflictError) as error:
        require_application_report(session, **{**arguments, "report_id": report.id, "expected_version": 2})
    assert error.value.code == "library_check_report_version_conflict"


def test_report_scope_cannot_be_replaced_by_a_client_reference() -> None:
    session, report, arguments = _gate_fixture()
    session.get.return_value = SimpleNamespace(novel_id=uuid4(), document_id=report.document_id)
    with pytest.raises(PrivateLibraryNotFoundError):
        require_application_report(session, **{**arguments, "report_id": uuid4(), "expected_version": 1})


def test_saved_keep_decisions_do_not_authorize_unselected_hits() -> None:
    session, report, arguments = _gate_fixture()
    selected, unresolved = uuid4(), uuid4()
    report.hits_json = [
        {"hit_id": str(selected), "action": "forbid"},
        {"hit_id": str(unresolved), "action": "forbid"},
    ]
    report.decisions_json = [{"kind": "keep_once", "hit_id": str(selected)}]
    with pytest.raises(PrivateLibraryConflictError) as error:
        require_application_report(session, **arguments)
    assert "1处" in error.value.current["message"]
    assert report.decisions_json == [{"kind": "keep_once", "hit_id": str(selected)}]


def test_accepted_candidate_replays_before_loading_generation_or_current_rules(monkeypatch) -> None:
    session = MagicMock(spec=Session)
    candidate = SimpleNamespace(
        id=uuid4(), document_id=uuid4(), state="accepted", adopted_revision_id=uuid4(),
    )
    session.get.return_value = candidate
    session.scalar.return_value = candidate
    monkeypatch.setattr(services, "_require_document", lambda *_: SimpleNamespace(id=candidate.document_id, novel_id=uuid4()))
    monkeypatch.setattr(services, "_lock_novel", lambda *_: object())
    monkeypatch.setattr(services, "_candidate_payload", lambda _: {"state": "accepted"})
    monkeypatch.setattr(services, "get_document", lambda *_: {"content_markdown": "较新稿"})
    monkeypatch.setattr(services, "get_revision", lambda *_: {"id": str(candidate.adopted_revision_id)})
    monkeypatch.setattr(services, "resolve_effective_lexicon_policy", lambda *_: pytest.fail("replay must not evaluate changed rules"))
    result = services.adopt_candidate(session, candidate.id, expected_draft_version=0, library_check_version=0)
    assert result["document"]["content_markdown"] == "较新稿"
    assert session.get.call_count == 1
    session.commit.assert_not_called()
    session.add.assert_not_called()


def seed_candidate(session, document_id, saved, *, with_policy=False, state="ready"):
    document = services.get_document(session, document_id)
    policy = resolve_effective_lexicon_policy(session, UUID(document["novel_id"]), lock=False)
    prose = "她眼底闪过迟疑，随后将湿透的信封放在桌上。"
    count = services.visible_character_count(prose)
    snapshot = {
        "chapter": {"base_content_markdown": saved["content_markdown"]},
        "acceptance": {
            "requested_visible_character_count": count,
            "minimum_visible_character_count": count, "maximum_visible_character_count": count,
        },
    }
    if with_policy:
        snapshot["lexicon_policy"] = effective_policy_snapshot(policy)
    job = ChapterGenerationJob(
        id=uuid4(), document_id=document_id, kind="body", input_hash=services.content_hash(str(uuid4())),
        state=state, brief_version=1, base_revision_id=None,
        base_draft_version=saved["draft_version"], base_content_hash=saved["content_hash"],
        generation_context_snapshot=snapshot, asset_snapshot=[],
        requested_provider_id="contract-provider", requested_model_id="contract-model",
        actual_provider_id="contract-provider", actual_model_id="contract-model",
        target_visible_character_count=count, output_visible_character_count=count,
        validation_state="meets_target", attempt=1,
    )
    session.add(job)
    session.flush()
    candidate = None
    if state == "ready":
        candidate = CandidateRevision(
            id=uuid4(), document_id=document_id, generation_job_id=job.id,
            base_revision_id=None, base_draft_version=saved["draft_version"],
            base_content_hash=saved["content_hash"], base_content_markdown=saved["content_markdown"],
            content_markdown=prose, content_text=prose, content_hash=services.content_hash(prose), state="ready",
        )
        session.add(candidate)
    session.commit()
    return job, candidate, prose, policy


def candidate_report(session, novel_id, document_id, candidate):
    candidate_id, text_hash, prose = candidate.id, candidate.content_hash, candidate.content_markdown
    policy = resolve_effective_lexicon_policy(session, novel_id, lock=False)
    result = create_or_reuse_check_report(
        session, text_ref=LibraryCheckTextRef(
            source_kind="candidate", novel_id=novel_id, document_id=document_id,
            version=1, text_sha256=text_hash,
        ), source_id=candidate_id, source_markdown=prose, policy=policy,
    )
    session.commit()
    return result.report


def test_postgres_legacy_candidate_new_rules_current_report_and_replay(postgres_session) -> None:
    session = postgres_session
    novel_id, document_id, saved = seed_novel(session)
    job, candidate, prose, _ = seed_candidate(session, document_id, saved)
    candidate_id = candidate.id
    old_report = candidate_report(session, novel_id, document_id, candidate)
    old_report_id, old_hash = old_report.id, old_report.rules_hash
    enable_forbid(session, novel_id)
    with pytest.raises(PrivateLibraryConflictError) as error:
        services.adopt_candidate(session, candidate_id, expected_draft_version=saved["draft_version"])
    assert error.value.code == "library_check_required"
    assert error.value.current["rules_sha256"] != old_hash
    session.rollback()
    assert services.get_document(session, document_id)["content_markdown"] == saved["content_markdown"]
    report = candidate_report(session, novel_id, document_id, session.get(CandidateRevision, candidate_id))
    report_id = report.id
    assert report.id != old_report_id and len(report.hits_json) == 1
    with pytest.raises(PrivateLibraryConflictError):
        services.adopt_candidate(
            session, candidate_id, expected_draft_version=saved["draft_version"],
            library_check_report_id=report.id, library_check_version=report.version,
        )
    session.rollback()
    report = append_check_decisions(
        session, novel_id=novel_id, report_id=report_id, expected_version=1,
        keep_hit_ids=[UUID(session.get(LibraryCheckReport, report_id).hits_json[0]["hit_id"])],
    )
    session.commit()
    adopted = services.adopt_candidate(
        session, candidate_id, expected_draft_version=saved["draft_version"],
        library_check_report_id=report_id, library_check_version=report.version,
    )
    assert adopted["document"]["content_markdown"] == prose
    event = session.get(LibraryCheckReport, report_id).decisions_json[-1]
    assert event["kind"] == "application" and event["revision_id"] == adopted["revision"]["id"]
    assert session.get(LibraryCheckReport, old_report_id).decisions_json == []
    assert "lexicon_policy" not in session.get(ChapterGenerationJob, job.id).generation_context_snapshot
    revision_count = session.scalar(select(func.count(DocumentRevision.id)).where(DocumentRevision.document_id == document_id))
    later = services.save_draft(
        session, document_id, expected_draft_version=adopted["document"]["draft_version"],
        content_markdown=prose + "屋外传来脚步声。",
    )
    replay = services.adopt_candidate(
        session, candidate_id, expected_draft_version=saved["draft_version"],
        library_check_report_id=old_report_id, library_check_version=1,
    )
    assert replay["revision"]["id"] == adopted["revision"]["id"]
    assert replay["document"]["content_markdown"] == later["content_markdown"]
    assert session.scalar(select(func.count(DocumentRevision.id)).where(DocumentRevision.document_id == document_id)) == revision_count


def test_postgres_removed_historical_forbid_does_not_strand_old_client(postgres_session) -> None:
    session = postgres_session
    novel_id, document_id, saved = seed_novel(session)
    enable_forbid(session, novel_id)
    _, candidate, prose, _ = seed_candidate(session, document_id, saved, with_policy=True)
    candidate_id = candidate.id
    old_report = candidate_report(session, novel_id, document_id, candidate)
    old_report_id = old_report.id
    bindings = session.scalars(select(NovelAssetBinding).where(NovelAssetBinding.novel_id == novel_id, NovelAssetBinding.lifecycle_state == "active")).all()
    replace_novel_bindings(
        session, novel_id,
        expected_binding_versions={row.asset_id: row.version for row in bindings},
        selections=[], operation_key=f"disable-{uuid4()}",
    )
    session.commit()
    adopted = services.adopt_candidate(session, candidate_id, expected_draft_version=saved["draft_version"])
    assert adopted["document"]["content_markdown"] == prose
    assert session.get(LibraryCheckReport, old_report_id).decisions_json == []


def test_postgres_generation_scans_frozen_evidence_without_locks_and_preserves_it(postgres_session, monkeypatch) -> None:
    from backend.private_library import lexicon_reports

    session = postgres_session
    novel_id, document_id, saved = seed_novel(session)
    job, _, prose, policy = seed_candidate(session, document_id, saved, with_policy=True, state="running")
    job_id = job.id
    original = lexicon_reports.match_lexicon

    def scan(*args, **kwargs):
        assert not session.in_transaction()
        with Session(session.bind, expire_on_commit=False) as other:
            other.info["plan74_assets"] = session.info["plan74_assets"]
            from sqlalchemy import text
            other.execute(text("SET LOCAL lock_timeout = '1000ms'"))
            enable_forbid(other, novel_id)
        return original(*args, **kwargs)

    monkeypatch.setattr(lexicon_reports, "match_lexicon", scan)
    complete = services.complete_chapter_generation(
        session, job_id, content_markdown=prose,
        actual_provider_id="contract-provider", actual_model_id="contract-model",
    )
    candidate_id = UUID(complete["candidate"]["id"])
    report = session.scalar(select(LibraryCheckReport).where(LibraryCheckReport.source_id == candidate_id))
    assert report.rules_hash == policy.rules_hash
    assert report.hits_json == []
    assert complete["generation_context_snapshot"]["lexicon_policy"]["rules_hash"] == policy.rules_hash
    with pytest.raises(PrivateLibraryConflictError) as error:
        services.adopt_candidate(session, candidate_id, expected_draft_version=saved["draft_version"])
    assert error.value.code == "library_check_required"
    session.rollback()
