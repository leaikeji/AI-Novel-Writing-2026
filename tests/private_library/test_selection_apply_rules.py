"""Controlled body saves: pure contract checks and opt-in real PostgreSQL cases."""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from backend import services
from backend.creative_data_models import LibraryCheckReport
from backend.models import CreativeGenerationJob, Document, DocumentWorkingCopy, Novel, PrivateAsset
from backend.private_library.contracts import VersionSelection
from backend.private_library.errors import PrivateLibraryConflictError, PrivateLibraryValidationError
from backend.private_library.lexicon_contracts import LexiconEntry, LexiconPack
from backend.private_library.lexicon_reports import create_or_reuse_check_report
from backend.private_library.lexicon_service import resolve_effective_lexicon_policy
from backend.private_library.maintenance_contracts import LibraryCheckTextRef, SelectionLibraryApplication
from backend.private_library.selection_application import resolve_selection_application_source
from backend.private_library.service import create_asset, replace_novel_bindings
from backend.selection_edit_diff import build_selection_edit_result


def selection_snapshot(novel_id, document_id, baseline, selected, draft_version=2):
    before, after = baseline.split(selected, 1)
    start = len(before.encode("utf-16-le")) // 2
    return {
        "target": {
            "novel_id": str(novel_id), "document_id": str(document_id),
            "field_id": "chapter.body", "persistence": "autosave",
        },
        "base": {
            "persistence_version_kind": "draft", "persistence_version": draft_version,
            "field_value_sha256": services.content_hash(baseline),
            "start_utf16": start, "end_utf16": start + len(selected.encode("utf-16-le")) // 2,
            "selection_text": selected,
        },
    }


def _mock_selection():
    novel_id, document_id, job_id = uuid4(), uuid4(), uuid4()
    baseline, selected, replacement = "🙂堤岸。旧句。灯塔。", "旧句。", "新句。"
    document = SimpleNamespace(id=document_id, novel_id=novel_id)
    working = SimpleNamespace(
        draft_version=2, content_markdown=baseline, content_hash=services.content_hash(baseline),
    )
    job = SimpleNamespace(
        id=job_id, novel_id=novel_id, document_id=document_id, kind="selection_edit",
        state="ready", attempt=1, output_text=replacement,
        input_snapshot=selection_snapshot(novel_id, document_id, baseline, selected),
        output_json={"diff_segments": [
            {"segment_id": "change-1", "kind": "replace", "original_text": "旧", "replacement_text": "新"},
            {"segment_id": "equal-2", "kind": "equal", "text": "句。"},
        ]},
    )
    session = MagicMock(spec=Session)
    session.get.side_effect = lambda model, _id: {
        Document: document, DocumentWorkingCopy: working, CreativeGenerationJob: job,
    }[model]
    return session, novel_id, document_id, job, working


def test_selection_rebuild_uses_utf16_and_exact_partial_diff_decisions() -> None:
    session, novel_id, document_id, job, working = _mock_selection()
    final, unchanged = resolve_selection_application_source(
        session, novel_id, document_id, job.id, 1, services.content_hash("新句。"), ["change-1"],
    )
    assert final == "🙂堤岸。新句。灯塔。"
    assert unchanged == (working.content_markdown, 5, 8)
    original, _ = resolve_selection_application_source(
        session, novel_id, document_id, job.id, 1, services.content_hash("旧句。"), [],
    )
    assert original == working.content_markdown
    session.commit.assert_not_called()


@pytest.mark.parametrize("change", ["field", "novel", "document", "persistence"])
def test_selection_rejects_nonbody_or_forged_persisted_target(change) -> None:
    session, novel_id, document_id, job, _ = _mock_selection()
    key, value = {
        "field": ("field_id", "chapter.title"), "novel": ("novel_id", str(uuid4())),
        "document": ("document_id", str(uuid4())), "persistence": ("persistence", "explicit-save"),
    }[change]
    job.input_snapshot["target"][key] = value
    with pytest.raises(PrivateLibraryValidationError):
        resolve_selection_application_source(
            session, novel_id, document_id, job.id, 1, services.content_hash("新句。"), None,
        )


@pytest.mark.parametrize("change", ["attempt", "hash", "baseline", "range", "surrogate", "unknown_segment"])
def test_selection_rejects_stale_or_invalid_source_without_any_write(change) -> None:
    session, novel_id, document_id, job, working = _mock_selection()
    attempt, digest, segments = 1, services.content_hash("新句。"), None
    if change == "attempt":
        attempt = 2
    elif change == "hash":
        digest = services.content_hash("伪造替换")
    elif change == "baseline":
        working.draft_version = 3
    elif change == "range":
        job.input_snapshot["base"]["start_utf16"] = -1
    elif change == "surrogate":
        job.input_snapshot["base"].update(start_utf16=1, end_utf16=2)
    else:
        segments = ["unknown"]
    with pytest.raises((PrivateLibraryConflictError, PrivateLibraryValidationError)):
        resolve_selection_application_source(
            session, novel_id, document_id, job.id, attempt, digest, segments,
        )
    session.add.assert_not_called()
    session.commit.assert_not_called()


@pytest.fixture
def postgres_session(monkeypatch):
    """Never connect implicitly; only an explicitly provisioned *_test DB."""
    url = os.environ.get("AI_NOVEL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("AI_NOVEL_TEST_DATABASE_URL is required for real PostgreSQL checks")
    parsed = make_url(url)
    if not parsed.drivername.startswith("postgresql") or not str(parsed.database).endswith("_test"):
        pytest.fail("Plan 74 database checks require an explicit PostgreSQL *_test database")
    from backend.narration import official_voice_selection
    monkeypatch.setattr(official_voice_selection, "initialize_new_novel_default_narrator", lambda *_a, **_kw: None)
    engine = create_engine(url, pool_pre_ping=True)
    with Session(engine, expire_on_commit=False) as session:
        session.info["plan74_novels"] = []
        session.info["plan74_assets"] = []
        try:
            yield session
        finally:
            session.rollback()
            novel_ids = session.info["plan74_novels"]
            asset_ids = session.info["plan74_assets"]
            if novel_ids:
                session.execute(delete(Novel).where(Novel.id.in_(novel_ids)))
            if asset_ids:
                session.execute(delete(PrivateAsset).where(PrivateAsset.id.in_(asset_ids)))
            session.commit()
    engine.dispose()


def seed_novel(session, baseline="潮声。旧句。灯塔。"):
    result = services.create_novel(session, f"pytest-plan74-{uuid4()}")
    novel_id, document_id = UUID(result["id"]), UUID(result["initial_document_id"])
    session.info["plan74_novels"].append(novel_id)
    saved = services.save_draft(session, document_id, expected_draft_version=1, content_markdown=baseline)
    return novel_id, document_id, saved


def enable_forbid(session, novel_id, term="眼底闪过"):
    asset_id = uuid4()
    result = create_asset(
        session, asset_id=asset_id, asset_type="vocabulary", title=f"pytest-plan74-{asset_id}",
        content=term, metadata=LexiconPack(entries=[
            LexiconEntry(entry_id="entry_0001", term=term, action="forbid"),
        ]).model_dump(mode="json"), operation_key=f"create-{asset_id}",
    )
    session.info["plan74_assets"].append(asset_id)
    replace_novel_bindings(
        session, novel_id, expected_binding_versions={},
        selections=[VersionSelection(asset_id, result.asset_version.id)],
        operation_key=f"enable-{asset_id}",
    )
    session.commit()
    return result


def seed_selection(session, novel_id, document_id, saved, replacement="新句。"):
    job_id = uuid4()
    baseline = saved["content_markdown"]
    snapshot = selection_snapshot(novel_id, document_id, baseline, "旧句。", saved["draft_version"])
    output = build_selection_edit_result(
        job_id=str(job_id), selection_id=str(uuid4()), operation="polish",
        original_text="旧句。", replacement_text=replacement, short_summary="调整动作表达。",
    )
    job = CreativeGenerationJob(
        id=job_id, novel_id=novel_id, document_id=document_id,
        scope_type="novel", scope_id=novel_id, kind="selection_edit", state="ready",
        input_hash=services.content_hash(str(job_id)), input_snapshot=snapshot,
        requested_provider_id="contract-provider", requested_model_id="contract-model",
        output_text=replacement, output_json=output, attempt=1,
    )
    session.add(job)
    session.commit()
    return job


def selection_application(session, novel_id, document_id, saved, job):
    job_id, attempt, replacement_hash = job.id, int(job.attempt), services.content_hash(job.output_text)
    final, unchanged = resolve_selection_application_source(
        session, novel_id, document_id, job_id, attempt, replacement_hash, None,
    )
    policy = resolve_effective_lexicon_policy(session, novel_id, lock=False)
    result = create_or_reuse_check_report(
        session, text_ref=LibraryCheckTextRef(
            source_kind="selection_result", novel_id=novel_id, document_id=document_id,
            version=attempt, text_sha256=services.content_hash(final),
        ), source_id=job_id, source_markdown=final, policy=policy, unchanged_baseline=unchanged,
    )
    session.commit()
    application = SelectionLibraryApplication(
        application_id=uuid4(), job_id=job_id, attempt=attempt,
        base_draft_version=saved["draft_version"], base_content_hash=saved["content_hash"],
        replacement_sha256=replacement_hash,
        library_check_report_id=result.report.id, library_check_version=result.report.version,
    )
    return final, application, result.report


def test_postgres_selection_application_replay_keeps_newer_manual_draft(postgres_session) -> None:
    session = postgres_session
    novel_id, document_id, saved = seed_novel(session)
    job = seed_selection(session, novel_id, document_id, saved)
    final, application, report = selection_application(session, novel_id, document_id, saved, job)
    applied = services.save_draft(
        session, document_id, expected_draft_version=saved["draft_version"],
        content_markdown=final, library_application=application,
    )
    assert applied["library_application"]["draft_version"] == applied["draft_version"]
    assert applied["library_application"]["replayed"] is False
    manual = services.save_draft(
        session, document_id, expected_draft_version=applied["draft_version"],
        content_markdown=final + "我沿堤岸走向灯塔。",
    )
    # A rule created after success must not turn an idempotent replay into a
    # second application or overwrite the author's subsequent sentence.
    enable_forbid(session, novel_id, "新句")
    replay = services.save_draft(
        session, document_id, expected_draft_version=saved["draft_version"],
        content_markdown=final, library_application=application,
    )
    assert replay["library_application"]["replayed"] is True
    assert replay["library_application"]["draft_version"] < replay["draft_version"]
    assert replay["content_markdown"] == manual["content_markdown"]
    assert len([event for event in session.get(LibraryCheckReport, report.id).decisions_json if event["kind"] == "application"]) == 1
    with pytest.raises(PrivateLibraryConflictError) as error:
        services.save_draft(
            session, document_id, expected_draft_version=saved["draft_version"],
            content_markdown=final + "另一个结果。", library_application=application,
        )
    assert error.value.code == "library_application_idempotency_conflict"
    session.rollback()


def test_postgres_selection_rejects_new_rules_after_check_without_writing(postgres_session) -> None:
    session = postgres_session
    novel_id, document_id, saved = seed_novel(session)
    job = seed_selection(session, novel_id, document_id, saved, "眼底闪过迟疑。")
    final, application, report = selection_application(session, novel_id, document_id, saved, job)
    report_id = report.id
    enable_forbid(session, novel_id)
    with pytest.raises(PrivateLibraryConflictError) as error:
        services.save_draft(
            session, document_id, expected_draft_version=saved["draft_version"],
            content_markdown=final, library_application=application,
        )
    assert error.value.code == "library_check_required"
    session.rollback()
    assert services.get_document(session, document_id)["content_markdown"] == saved["content_markdown"]
    assert session.get(LibraryCheckReport, report_id).decisions_json == []


@pytest.mark.parametrize("failure", ["flush", "commit"])
def test_postgres_selection_receipt_and_body_roll_back_together(postgres_session, monkeypatch, failure) -> None:
    session = postgres_session
    novel_id, document_id, saved = seed_novel(session)
    job = seed_selection(session, novel_id, document_id, saved)
    final, application, report = selection_application(session, novel_id, document_id, saved, job)
    report_id = report.id
    original_flush = session.flush

    def fail_commit():
        # Authority + receipt SQL has already executed; rollback must undo both.
        original_flush()
        raise RuntimeError("forced-commit-failure")

    def fail_flush(*args, **kwargs):
        if any(
            isinstance(row, LibraryCheckReport)
            and any(item.get("kind") == "application" for item in row.decisions_json)
            for row in session.dirty
        ):
            raise RuntimeError("forced-flush-failure")
        return original_flush(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(session, "commit" if failure == "commit" else "flush", fail_commit if failure == "commit" else fail_flush)
        with pytest.raises(RuntimeError, match=f"forced-{failure}"):
            services.save_draft(
                session, document_id, expected_draft_version=saved["draft_version"],
                content_markdown=final, library_application=application,
            )
    session.rollback()
    current = services.get_document(session, document_id)
    assert current["content_markdown"] == saved["content_markdown"]
    assert current["draft_version"] == saved["draft_version"]
    assert session.get(LibraryCheckReport, report_id).decisions_json == []
    applied = services.save_draft(
        session, document_id, expected_draft_version=saved["draft_version"],
        content_markdown=final, library_application=application,
    )
    assert applied["library_application"]["replayed"] is False


def test_postgres_scan_has_no_transaction_and_detects_concurrent_binding_change(postgres_session, monkeypatch) -> None:
    from backend.private_library import lexicon_reports

    session = postgres_session
    novel_id, document_id, saved = seed_novel(session)
    policy = resolve_effective_lexicon_policy(session, novel_id, lock=False)
    matcher = lexicon_reports.match_lexicon
    observed = []

    def mutate_during_scan(*args, **kwargs):
        assert not session.in_transaction()
        with Session(session.bind, expire_on_commit=False) as other:
            other.info["plan74_assets"] = session.info["plan74_assets"]
            # If the scan held the novel write lock this operation would fail
            # promptly instead of deadlocking the test runner.
            from sqlalchemy import text
            other.execute(text("SET LOCAL lock_timeout = '1000ms'"))
            enable_forbid(other, novel_id, "旧句")
        observed.append(True)
        return matcher(*args, **kwargs)

    monkeypatch.setattr(lexicon_reports, "match_lexicon", mutate_during_scan)
    with pytest.raises(PrivateLibraryConflictError) as error:
        create_or_reuse_check_report(
            session, text_ref=LibraryCheckTextRef(
                source_kind="working_copy", novel_id=novel_id, document_id=document_id,
                version=saved["draft_version"], text_sha256=saved["content_hash"],
            ), source_id=document_id, source_markdown=saved["content_markdown"], policy=policy,
        )
    assert observed == [True]
    assert error.value.code == "library_check_required"
    assert error.value.current["rules_sha256"] != policy.rules_hash
    assert "report_id" not in error.value.current
    session.rollback()
    assert session.scalar(select(LibraryCheckReport).where(LibraryCheckReport.novel_id == novel_id)) is None
