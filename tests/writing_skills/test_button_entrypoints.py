"""Existing chapter domain service + real isolated dispatch transactions.

No HTTP/Provider gate is claimed here. Tests stop before any model call.
"""
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import hashlib
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from backend.embedding.writing import resolve_writing_position
from backend.models import ChapterGenerationJob, Novel
from backend.services import (build_chapter_generation_prompt, create_novel,
                              ChapterGenerationInProgressError,
                              fail_chapter_generation, save_chapter_brief,
                              start_chapter_generation, prepare_chapter_generation,
                              ValidationError)
from backend.writing_skills.contracts import (
    ActionIdentity, FrozenRouteRequest, MethodBlock, MethodPreferences, Scope,
    SkillInvocationPlanV1, SkillInjectionPacketV1,
)
from backend.writing_skills.persistence import claim_action, advance, lookup_action, StaleFence
from backend.writing_skills.projection import chapter_projection
from .test_persistence import engine  # isolated URL guard and existing migrated fixture


@pytest.fixture
def chapter(engine, monkeypatch):
    from backend.narration import official_voice_selection
    monkeypatch.setattr(official_voice_selection, "initialize_new_novel_default_narrator", lambda *a, **k: None)
    with Session(engine) as session:
        created = create_novel(session, "s58-method-atomic-test")
        document_id = UUID(created["initial_document_id"])
        brief = save_chapter_brief(session, document_id, expected_version=0,
            target_word_count=1000, expectation_text="核对线索", outline_text="角色比较两份记录。",
            forbidden_text="不揭晓真相", role_constraints={})
        kwargs = dict(expected_brief_version=brief["version"], execution_agent_id="ai-novel-writer",
            requested_provider_id="s58-fake", requested_model_id="s58-fake-model",
            generation_contract_version="s58-fixture/1", effective_context_window_tokens=131072,
            writing_position=resolve_writing_position(session, document_id))
        # Existing domain preparation (no Provider execution) supplies a real
        # Context V4 snapshot. This legacy job remains immutable and unrecorded.
        legacy = start_chapter_generation(session, document_id, **kwargs)
        snapshot = legacy["generation_context_snapshot"]
        novel = session.get(Novel, UUID(snapshot["novel"]["id"]))
        scope = Scope(owner_id=novel.owner_id, workspace_id=novel.workspace_id,
            kind="novel", scope_id=novel.id, document_id=document_id, tab_id="s58-button")
        projection = chapter_projection(scope, snapshot, build_chapter_generation_prompt(snapshot))
        # The legacy job exists only to freeze a real Context V4 fixture.  It
        # must be terminal before a managed action can claim the chapter.
        fail_chapter_generation(session, UUID(legacy["id"]), "fixture snapshot captured")
    return document_id, kwargs, projection, legacy


def assembled(engine, projection, text="frozen primary"):
    request = FrozenRouteRequest(identity=ActionIdentity(owner_id=projection.scope.owner_id,
        workspace_id=projection.scope.workspace_id, entry="button", action_id=uuid4()),
        projection=projection, preferences=MethodPreferences(), catalog_version="a" * 64,
        provider_id="s58-fake", model_id="s58-fake-model")
    packet = SkillInjectionPacketV1(plan=SkillInvocationPlanV1(task="chapter_body",
        primary_skill="prose-writing", source_hash=projection.source_hash, catalog_version=request.catalog_version,
        genre_state="unresolved", mechanism_state="unresolved"),
        blocks=(MethodBlock(skill_id="prose-writing", path="SKILL.md", text=text,
                            sha256=hashlib.sha256(text.encode()).hexdigest()),), estimated_tokens=10)
    with Session(engine) as session:
        claimed = claim_action(session, request.identity, projection.scope, "b" * 64,
                               authorize=lambda *a: None, freeze=lambda: request)
        ready = advance(session, claimed, "route_ready")
        return advance(session, ready, "assembled", packet=packet)


def read_claim(engine, claim):
    with Session(engine) as session:
        return lookup_action(session, claim.request.identity, claim.request.projection.scope,
                             "b" * 64, authorize=lambda *a: None)


def test_job_and_dispatch_commit_together_and_method_changes_hash(engine, chapter):
    document_id, kwargs, projection, legacy = chapter
    claim = assembled(engine, projection)
    with Session(engine) as session:
        job = start_chapter_generation(session, document_id, **kwargs, method_dispatch=claim)
    linked = read_claim(engine, claim)
    assert linked.state == "dispatch_started" and linked.job_ref == f"chapter:{job['id']}"
    invocation = job["generation_context_snapshot"]["skill_invocation"]
    assert invocation["dispatch_id"] == str(claim.id)
    assert invocation["method_input_hash"] == claim.packet.method_input_hash
    assert job["input_hash"] != legacy["input_hash"]
    assert "skill_invocation" not in legacy["generation_context_snapshot"]
    assert "dispatch_id" not in build_chapter_generation_prompt(job["generation_context_snapshot"])
    with Session(engine) as session:
        fail_chapter_generation(session, UUID(job["id"]), "first method fixture complete")
    other = assembled(engine, projection, text="new method version")
    with Session(engine) as session:
        changed = start_chapter_generation(session, document_id, **kwargs, method_dispatch=other)
    assert changed["input_hash"] != job["input_hash"]


def test_new_action_same_methods_cannot_attach_to_an_active_job(engine, chapter):
    document_id, kwargs, projection, _ = chapter
    first, second = assembled(engine, projection), assembled(engine, projection)
    with Session(engine) as session:
        job = start_chapter_generation(session, document_id, **kwargs, method_dispatch=first)
    with Session(engine) as session:
        with pytest.raises(ChapterGenerationInProgressError) as caught:
            start_chapter_generation(session, document_id, **kwargs, method_dispatch=second)
        session.rollback()
    assert caught.value.job["id"] == job["id"]
    assert read_claim(engine, second).state == "assembled"
    assert read_claim(engine, second).job_ref is None


def test_failed_commit_leaves_no_orphan_job_or_false_dispatch(engine, chapter):
    document_id, kwargs, projection, _ = chapter
    claim = assembled(engine, projection)
    with Session(engine) as session:
        before = session.scalar(select(func.count()).select_from(ChapterGenerationJob).where(ChapterGenerationJob.document_id == document_id))
    with Session(engine) as session:
        def fail(_session):
            raise RuntimeError("injected precommit crash")
        event.listen(session, "before_commit", fail)
        with pytest.raises(RuntimeError, match="precommit"):
            start_chapter_generation(session, document_id, **kwargs, method_dispatch=claim)
        session.rollback()
    with Session(engine) as session:
        after = session.scalar(select(func.count()).select_from(ChapterGenerationJob).where(ChapterGenerationJob.document_id == document_id))
    assert after == before
    assert read_claim(engine, claim).state == "assembled"
    assert read_claim(engine, claim).job_ref is None


def test_stale_model_or_source_stops_before_job_commit(engine, chapter):
    document_id, kwargs, projection, _ = chapter
    claim = assembled(engine, projection.model_copy(update={"visibility_key": "wrong"}))
    with Session(engine) as session, pytest.raises(ValidationError, match="source or model changed"):
        start_chapter_generation(session, document_id, **kwargs, method_dispatch=claim)
    assert read_claim(engine, claim).state == "assembled"
    claim = assembled(engine, projection)
    with Session(engine) as session, pytest.raises(ValidationError, match="source or model changed"):
        start_chapter_generation(session, document_id, **{**kwargs, "requested_model_id": "different"}, method_dispatch=claim)
    assert read_claim(engine, claim).job_ref is None


def test_cancelled_or_forged_claim_cannot_create_job(engine, chapter):
    document_id, kwargs, projection, _ = chapter
    claim = assembled(engine, projection)
    with Session(engine) as session:
        advance(session, claim, "cancelled")
    with Session(engine) as session, pytest.raises(StaleFence):
        start_chapter_generation(session, document_id, **kwargs, method_dispatch=claim)
    other = assembled(engine, projection)
    with Session(engine) as session, pytest.raises(StaleFence):
        start_chapter_generation(session, document_id, **kwargs, method_dispatch=replace(other, id=uuid4()))


def test_preparation_is_job_free_and_uses_the_same_frozen_source(engine, chapter):
    document_id, kwargs, projection, _ = chapter
    with Session(engine) as session:
        count = session.scalar(select(func.count()).select_from(ChapterGenerationJob).where(ChapterGenerationJob.document_id == document_id))
        snapshot, assets = prepare_chapter_generation(session, document_id, **kwargs)
        assert chapter_projection(projection.scope, snapshot, build_chapter_generation_prompt(snapshot)) == projection
        assert isinstance(assets, list)
        assert session.scalar(select(func.count()).select_from(ChapterGenerationJob).where(ChapterGenerationJob.document_id == document_id)) == count


def test_concurrent_same_action_cannot_create_two_jobs(engine, chapter):
    document_id, kwargs, projection, _ = chapter
    claim = assembled(engine, projection)
    def start(_):
        try:
            with Session(engine) as session:
                return start_chapter_generation(session, document_id, **kwargs, method_dispatch=claim)["id"]
        except StaleFence:
            return None
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(start, range(2)))
    assert len([result for result in results if result is not None]) == 1


def test_forged_low_token_estimate_cannot_exceed_generation_budget(engine, chapter):
    document_id, kwargs, projection, _ = chapter
    claim = assembled(engine, projection, text="文" * 300000)
    with Session(engine) as session, pytest.raises(ValidationError, match="remaining prompt budget"):
        start_chapter_generation(session, document_id, **kwargs, method_dispatch=claim)
    assert read_claim(engine, claim).state == "assembled"
