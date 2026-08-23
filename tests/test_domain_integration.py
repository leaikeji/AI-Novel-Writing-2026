from __future__ import annotations

import os
from uuid import UUID

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from backend.models import Document, Novel
from backend.services import (
    CandidateConflictError,
    adopt_candidate,
    commit_intelligence_items,
    complete_chapter_generation,
    complete_intelligence_proposal,
    DraftConflictError,
    create_checkpoint,
    create_novel,
    get_document,
    get_novel_context,
    list_story_facts,
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
                "'intelligence_proposal_items')"
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
    assert restored["revision"]["revision_number"] == 3
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
