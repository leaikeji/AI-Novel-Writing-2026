from __future__ import annotations

import os
from uuid import UUID

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from backend.models import Document, IntelligenceCommitBatch, Novel, StoryFact
from backend.services import (
    CandidateConflictError,
    adopt_candidate,
    commit_intelligence_items,
    complete_chapter_generation,
    complete_intelligence_proposal,
    DraftConflictError,
    RestorationPlanConflictError,
    create_checkpoint,
    create_novel,
    get_document,
    get_novel_context,
    list_story_facts,
    preview_restore_revision,
    restore_revision,
    save_chapter_brief,
    save_draft,
    search_novel,
    start_chapter_generation,
    start_intelligence_proposal,
)


TEST_DATABASE_URL = os.environ.get("AI_NOVEL_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="integration database not configured")


@pytest.fixture
def session():
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    with Session(engine, expire_on_commit=False) as database_session:
        yield database_session
        database_session.rollback()
        database_session.execute(
            text("DELETE FROM novels WHERE title LIKE 'pytest-%'")
        )
        database_session.commit()
    engine.dispose()


def test_migration_installs_pgvector_and_authority_tables(session: Session) -> None:
    extension = session.scalar(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'"))
    table_names = {
        row[0]
        for row in session.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname='public' AND tablename IN "
                "('novels','documents','document_working_copies','document_revisions',"
                "'story_facts','novel_chunks','media_assets','chapter_briefs',"
                "'chapter_generation_jobs','candidate_revisions','intelligence_proposals',"
                "'intelligence_proposal_items','intelligence_commit_batches',"
                "'derived_source_bindings')"
            )
        )
    }

    assert extension == "0.8.6"
    assert table_names == {
        "novels",
        "documents",
        "document_working_copies",
        "document_revisions",
        "story_facts",
        "novel_chunks",
        "media_assets",
        "chapter_briefs",
        "chapter_generation_jobs",
        "candidate_revisions",
        "intelligence_proposals",
        "intelligence_proposal_items",
        "intelligence_commit_batches",
        "derived_source_bindings",
    }


def test_draft_cas_checkpoint_search_and_restore(session: Session) -> None:
    novel = create_novel(session, "pytest-CAS小说")
    novel_id = UUID(novel["id"])
    document_id = UUID(novel["tree"][0]["documents"][0]["id"])

    first_save = save_draft(
        session,
        document_id,
        expected_draft_version=1,
        content_markdown="# 第一章\n\n雨夜里，江述发现一封信。",
    )
    assert first_save["draft_version"] == 2

    with pytest.raises(DraftConflictError) as conflict:
        save_draft(
            session,
            document_id,
            expected_draft_version=1,
            content_markdown="过期标签页不应覆盖正文",
        )
    session.rollback()
    assert conflict.value.current["content_markdown"].endswith("一封信。")

    checkpoint = create_checkpoint(session, document_id, expected_draft_version=2)
    assert checkpoint["revision"]["revision_number"] == 2
    assert checkpoint["document"]["draft_version"] == 3

    second_save = save_draft(
        session,
        document_id,
        expected_draft_version=3,
        content_markdown="# 第一章\n\n江述烧掉了那封信。",
    )
    assert second_save["draft_version"] == 4
    assert search_novel(session, novel_id, "烧掉")[0]["document_id"] == str(document_id)

    restored = restore_revision(
        session,
        document_id,
        UUID(checkpoint["revision"]["id"]),
        expected_draft_version=4,
    )
    assert restored["preserved_revision"]["revision_number"] == 3
    assert restored["preserved_revision"]["source"] == "pre_restore_checkpoint"
    assert restored["preserved_revision"]["content_markdown"].endswith("烧掉了那封信。")
    assert restored["revision"]["revision_number"] == 4
    assert restored["revision"]["parent_revision_id"] == restored["preserved_revision"]["id"]
    assert restored["revision"]["source"] == "manual_restore"
    assert restored["document"]["content_markdown"].endswith("一封信。")

    context = get_novel_context(session, novel_id, document_id=document_id)
    assert context["novel"]["title"] == "pytest-CAS小说"
    assert context["documents"][-1]["base_revision_id"] == restored["revision"]["id"]
    assert context["retrieval"].startswith("lexical")


def test_create_novel_is_ready_to_write(session: Session) -> None:
    novel = create_novel(session, "pytest-开箱即写")
    document_id = UUID(novel["tree"][0]["documents"][0]["id"])
    document = get_document(session, document_id)

    assert novel["tree"][0]["title"] == "第一卷"
    assert document["title"] == "第一章"
    assert document["draft_version"] == 1
    assert document["revisions"][0]["revision_number"] == 1
    assert session.scalar(select(Novel).where(Novel.id == UUID(novel["id"]))) is not None
    assert session.scalar(select(Document).where(Document.id == document_id)) is not None


def test_reviewed_candidate_and_intelligence_are_separate_authority_steps(
    session: Session,
) -> None:
    novel = create_novel(session, "pytest-候选闭环")
    novel_id = UUID(novel["id"])
    document_id = UUID(novel["tree"][0]["documents"][0]["id"])

    brief = save_chapter_brief(
        session,
        document_id,
        expected_version=0,
        target_word_count=1800,
        expectation_text="推进雨夜来信的来源",
        outline_text="江述核对邮戳，发现寄出日期来自明天。",
        forbidden_text="不要揭示寄信人",
        role_constraints={"required": ["江述"], "forbidden": ["寄信人"]},
    )
    job = start_chapter_generation(
        session, document_id, expected_brief_version=brief["version"]
    )
    completed = complete_chapter_generation(
        session,
        UUID(job["id"]),
        content_markdown="雨水敲着窗。江述翻过信封，邮戳日期写着明天。",
        model_profile_fingerprint="pytest-model",
    )
    candidate = completed["candidate"]

    assert candidate["state"] == "ready"
    assert get_document(session, document_id)["content_markdown"] == ""

    adopted = adopt_candidate(
        session, UUID(candidate["id"]), expected_draft_version=1
    )
    assert adopted["document"]["content_markdown"].startswith("雨水敲着窗")
    assert adopted["revision"]["source"] == "ai_candidate_adopt"

    proposal = start_intelligence_proposal(
        session,
        document_id,
        revision_id=UUID(adopted["revision"]["id"]),
    )
    proposal = complete_intelligence_proposal(
        session,
        UUID(proposal["id"]),
        items=[
            {
                "item_type": "fact",
                "subject": "信封邮戳",
                "predicate": "日期",
                "object": "明天",
                "source_text": "邮戳日期写着明天",
                "reasoning_summary": "明确的新时间异常",
                "confidence": 98,
            },
            {
                "item_type": "foreshadow_new",
                "subject": "寄信人",
                "predicate": "身份",
                "object": "尚未揭示",
                "source_text": "江述翻过信封",
                "reasoning_summary": "可以继续追查",
                "confidence": 61,
            },
        ],
    )
    assert list_story_facts(session, novel_id) == []

    committed = commit_intelligence_items(
        session,
        UUID(proposal["id"]),
        accepted_item_ids=[UUID(proposal["items"][0]["id"])],
    )
    assert committed["state"] == "partially_accepted"
    facts = list_story_facts(session, novel_id)
    assert len(facts) == 1
    assert facts[0]["subject"] == "信封邮戳"
    assert facts[0]["source_revision_id"] == adopted["revision"]["id"]


def test_restore_reactivates_target_facts_without_duplicate_commits(
    session: Session,
) -> None:
    novel = create_novel(session, "pytest-版本事实事务")
    novel_id = UUID(novel["id"])
    document_id = UUID(novel["tree"][0]["documents"][0]["id"])

    saved_a = save_draft(
        session,
        document_id,
        expected_draft_version=1,
        content_markdown="版本 A：蓝色车票留在抽屉里。",
    )
    revision_a = create_checkpoint(
        session, document_id, expected_draft_version=saved_a["draft_version"]
    )["revision"]
    proposal_a = start_intelligence_proposal(
        session, document_id, revision_id=UUID(revision_a["id"])
    )
    proposal_a = complete_intelligence_proposal(
        session,
        UUID(proposal_a["id"]),
        items=[
            {
                "item_type": "fact",
                "subject": "车票",
                "predicate": "颜色",
                "object": "蓝色",
                "source_text": "蓝色车票",
                "reasoning_summary": "版本 A 的专属事实",
                "confidence": 99,
            }
        ],
    )
    selected_a = [UUID(proposal_a["items"][0]["id"])]
    committed_a = commit_intelligence_items(
        session, UUID(proposal_a["id"]), accepted_item_ids=selected_a
    )
    replayed_a = commit_intelligence_items(
        session, UUID(proposal_a["id"]), accepted_item_ids=selected_a
    )
    assert replayed_a["commit_batch"]["id"] == committed_a["commit_batch"]["id"]
    assert session.scalar(
        select(func.count(StoryFact.id)).where(StoryFact.novel_id == novel_id)
    ) == 1
    assert session.scalar(
        select(func.count(IntelligenceCommitBatch.id)).where(
            IntelligenceCommitBatch.proposal_id == UUID(proposal_a["id"])
        )
    ) == 1

    current = get_document(session, document_id)
    saved_b = save_draft(
        session,
        document_id,
        expected_draft_version=current["draft_version"],
        content_markdown="版本 B：银色怀表埋在旧桥下。",
    )
    revision_b = create_checkpoint(
        session, document_id, expected_draft_version=saved_b["draft_version"]
    )["revision"]
    proposal_b = start_intelligence_proposal(
        session, document_id, revision_id=UUID(revision_b["id"])
    )
    proposal_b = complete_intelligence_proposal(
        session,
        UUID(proposal_b["id"]),
        items=[
            {
                "item_type": "fact",
                "subject": "怀表",
                "predicate": "位置",
                "object": "旧桥下",
                "source_text": "银色怀表埋在旧桥下",
                "reasoning_summary": "版本 B 的专属事实",
                "confidence": 99,
            }
        ],
    )
    commit_intelligence_items(
        session,
        UUID(proposal_b["id"]),
        accepted_item_ids=[UUID(proposal_b["items"][0]["id"])],
    )

    before_restore = {fact["subject"]: fact["status"] for fact in list_story_facts(session, novel_id)}
    assert before_restore == {"怀表": "active", "车票": "source_superseded"}

    preview = preview_restore_revision(session, document_id, UUID(revision_a["id"]))
    assert [fact["subject"] for fact in preview["will_deactivate"]] == ["怀表"]
    assert [fact["subject"] for fact in preview["will_reactivate"]] == ["车票"]
    assert len(preview["available_commit_batches"]) == 1

    with pytest.raises(RestorationPlanConflictError):
        restore_revision(
            session,
            document_id,
            UUID(revision_a["id"]),
            expected_draft_version=preview["expected_draft_version"],
            expected_fact_plan_hash="0" * 64,
        )
    session.rollback()
    assert get_document(session, document_id)["base_revision_id"] == revision_b["id"]

    restored = restore_revision(
        session,
        document_id,
        UUID(revision_a["id"]),
        expected_draft_version=preview["expected_draft_version"],
        expected_fact_plan_hash=preview["fact_plan_hash"],
    )
    assert restored["revision"]["restored_from_revision_id"] == revision_a["id"]
    after_restore = {fact["subject"]: fact["status"] for fact in list_story_facts(session, novel_id)}
    assert after_restore == {"怀表": "source_superseded", "车票": "source_restored"}
    assert [fact["subject"] for fact in get_novel_context(session, novel_id)["story_facts"]] == ["车票"]
    assert session.scalar(
        select(func.count(StoryFact.id)).where(StoryFact.novel_id == novel_id)
    ) == 2
    proposal_ids = [UUID(proposal_a["id"]), UUID(proposal_b["id"])]
    assert session.scalar(
        select(func.count(IntelligenceCommitBatch.id)).where(
            IntelligenceCommitBatch.proposal_id.in_(proposal_ids)
        )
    ) == 2

    second_preview = preview_restore_revision(session, document_id, UUID(revision_a["id"]))
    restore_revision(
        session,
        document_id,
        UUID(revision_a["id"]),
        expected_draft_version=second_preview["expected_draft_version"],
        expected_fact_plan_hash=second_preview["fact_plan_hash"],
    )
    assert session.scalar(
        select(func.count(StoryFact.id)).where(StoryFact.novel_id == novel_id)
    ) == 2
    assert session.scalar(
        select(func.count(IntelligenceCommitBatch.id)).where(
            IntelligenceCommitBatch.proposal_id.in_(proposal_ids)
        )
    ) == 2


def test_candidate_adoption_rejects_a_changed_working_copy(session: Session) -> None:
    novel = create_novel(session, "pytest-候选冲突")
    document_id = UUID(novel["tree"][0]["documents"][0]["id"])
    brief = save_chapter_brief(
        session,
        document_id,
        expected_version=0,
        target_word_count=1200,
        expectation_text="测试冲突",
        outline_text="候选必须绑定生成基线。",
        forbidden_text="",
        role_constraints={},
    )
    job = start_chapter_generation(
        session, document_id, expected_brief_version=brief["version"]
    )
    completed = complete_chapter_generation(
        session, UUID(job["id"]), content_markdown="这是一份旧基线候选。"
    )
    save_draft(
        session,
        document_id,
        expected_draft_version=1,
        content_markdown="作者在模型运行时继续修改了正文。",
    )

    with pytest.raises(CandidateConflictError):
        adopt_candidate(
            session,
            UUID(completed["candidate"]["id"]),
            expected_draft_version=2,
        )
    session.rollback()
    assert get_document(session, document_id)["content_markdown"].startswith("作者在模型运行时")
