from __future__ import annotations

import os
from uuid import UUID

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from backend.creative_services import (
    EntityConflictError,
    archive_private_asset,
    build_novel_export,
    complete_chapter_creation_draft,
    complete_creative_generation,
    complete_novel_creation_draft,
    complete_outline_draft,
    create_asset_preset,
    create_foreshadow,
    create_novel_character,
    create_private_asset,
    create_storyline,
    delete_volume,
    get_or_create_chapter_creation_draft,
    get_or_create_novel_creation_draft,
    get_or_create_outline_draft,
    list_creative_generations,
    list_foreshadows,
    list_novel_characters,
    list_storylines,
    reorder_chapters,
    reorder_volumes,
    snapshot_private_assets,
    start_creative_generation,
    update_chapter_creation_draft,
    update_foreshadow,
    update_novel_settings,
    update_novel_creation_draft,
    update_outline_draft,
    update_private_asset,
)
from backend.models import (
    CandidateRevision,
    Document,
    IntelligenceCommitBatch,
    Novel,
    StoryFact,
)
from backend.services import (
    CandidateConflictError,
    ValidationError,
    adopt_candidate,
    commit_intelligence_items,
    complete_chapter_generation,
    complete_intelligence_proposal,
    DraftConflictError,
    RestorationPlanConflictError,
    create_checkpoint,
    create_document,
    create_novel,
    create_volume,
    delete_novel,
    get_chapter_brief,
    get_document,
    get_novel,
    get_novel_context,
    list_chapter_generation_jobs,
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
MINIMAX_MODEL_ID = "MiniMax-M3"
MINIMAX_PROVIDER_ID = "minimax-cn"


def _long_chapter(opening: str, *, paragraphs: int = 90) -> str:
    body = [opening]
    body.extend(
        (
            f"第{index}个场景里，人物沿着既定线索继续行动，环境、对话与选择都产生新的因果；"
            f"这一段保留编号{index}，让测试正文具有可核对的独立内容。"
        )
        for index in range(1, paragraphs + 1)
    )
    return "\n\n".join(body)


def _create_long_novel_via_wizard(
    session: Session,
    *,
    draft_key: str,
    title: str,
    audience: str = "female",
    genre: str = "年代言情",
) -> dict[str, object]:
    draft = get_or_create_novel_creation_draft(session, draft_key)
    draft = update_novel_creation_draft(
        session,
        UUID(draft["id"]),
        expected_version=draft["version"],
        step=6,
        data_patch={
            "writing_type": "long",
            "audience": audience,
            "genre": genre,
            "subgenre": "成长",
            "idea": "人物在时代变化中重新选择人生，并为每次选择承担后果。",
            "template_key": "growth-romance",
            "template_name": "成长型长篇",
            "template_data": {"structure": "起承转合"},
            "title": title,
            "author_name": "pytest-作者",
            "cover_mode": "system",
            "cover_image_data": "data:image/jpeg;base64,AA==",
        },
    )
    return complete_novel_creation_draft(
        session,
        UUID(draft["id"]),
        expected_version=draft["version"],
    )


@pytest.fixture
def session():
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    with Session(engine, expire_on_commit=False) as database_session:
        yield database_session
        database_session.rollback()
        database_session.execute(
            text(
                "DELETE FROM creative_generation_jobs WHERE "
                "novel_id IN (SELECT id FROM novels WHERE title LIKE 'pytest-%') OR "
                "scope_id IN (SELECT id FROM novel_creation_drafts "
                "WHERE draft_key LIKE 'pytest-%')"
            )
        )
        database_session.execute(
            text("DELETE FROM novels WHERE title LIKE 'pytest-%'")
        )
        database_session.execute(
            text("DELETE FROM novel_creation_drafts WHERE draft_key LIKE 'pytest-%'")
        )
        database_session.execute(
            text("DELETE FROM asset_presets WHERE title LIKE 'pytest-%'")
        )
        database_session.execute(
            text("DELETE FROM private_assets WHERE title LIKE 'pytest-%'")
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
                "'derived_source_bindings','novel_creation_drafts','private_assets',"
                "'asset_presets','asset_preset_items','outline_drafts',"
                "'novel_characters','character_relationships','storylines',"
                "'foreshadows','chapter_creation_drafts','creative_generation_jobs',"
                "'novel_exports')"
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
        "novel_creation_drafts",
        "private_assets",
        "asset_presets",
        "asset_preset_items",
        "outline_drafts",
        "novel_characters",
        "character_relationships",
        "storylines",
        "foreshadows",
        "chapter_creation_drafts",
        "creative_generation_jobs",
        "novel_exports",
    }

    generation_columns = {
        row[0]
        for row in session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='chapter_generation_jobs'"
            )
        )
    }
    assert {
        "asset_snapshot",
        "requested_model_id",
        "actual_model_id",
        "provider_profile",
        "target_visible_character_count",
        "output_visible_character_count",
        "validation_state",
        "attempt",
    } <= generation_columns


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


def test_novel_scoped_queries_and_commands_never_cross_books(session: Session) -> None:
    first = create_novel(session, "pytest-隔离甲")
    second = create_novel(session, "pytest-隔离乙")
    first_id = UUID(first["id"])
    second_id = UUID(second["id"])
    first_document_id = UUID(first["tree"][0]["documents"][0]["id"])
    second_document_id = UUID(second["tree"][0]["documents"][0]["id"])
    second_volume_id = UUID(second["tree"][0]["id"])

    save_draft(
        session,
        first_document_id,
        expected_draft_version=1,
        content_markdown="甲书独有线索：蓝色纸鹤。",
    )
    save_draft(
        session,
        second_document_id,
        expected_draft_version=1,
        content_markdown="乙书独有线索：铜制罗盘。",
    )

    assert [item["document_id"] for item in search_novel(session, first_id, "蓝色纸鹤")] == [
        str(first_document_id)
    ]
    assert search_novel(session, first_id, "铜制罗盘") == []
    assert search_novel(session, second_id, "蓝色纸鹤") == []

    with pytest.raises(ValidationError, match="does not belong"):
        get_novel_context(session, first_id, document_id=second_document_id)

    with pytest.raises(ValidationError, match="does not belong"):
        create_document(
            session,
            first_id,
            "不应跨书创建",
            volume_id=second_volume_id,
        )
    session.rollback()

    created_volume = create_volume(session, first_id, "甲书第二卷")
    assert created_volume["novel_id"] == str(first_id)
    assert get_novel_context(session, first_id)["novel"]["title"] == "pytest-隔离甲"
    assert get_novel_context(session, second_id)["novel"]["title"] == "pytest-隔离乙"


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
        content_markdown=_long_chapter(
            "雨水敲着窗。江述翻过信封，邮戳日期写着明天。"
        ),
        model_profile_fingerprint="pytest-model",
        actual_model_id=MINIMAX_MODEL_ID,
        provider_profile=MINIMAX_PROVIDER_ID,
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
        actual_model_id=MINIMAX_MODEL_ID,
        provider_profile=MINIMAX_PROVIDER_ID,
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
        actual_model_id=MINIMAX_MODEL_ID,
        provider_profile=MINIMAX_PROVIDER_ID,
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
        actual_model_id=MINIMAX_MODEL_ID,
        provider_profile=MINIMAX_PROVIDER_ID,
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
        session,
        UUID(job["id"]),
        content_markdown=_long_chapter("这是一份旧基线候选。"),
        actual_model_id=MINIMAX_MODEL_ID,
        provider_profile=MINIMAX_PROVIDER_ID,
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


def test_six_step_creation_is_persisted_validated_and_idempotent(
    session: Session,
) -> None:
    draft = get_or_create_novel_creation_draft(session, "pytest-六步建书")
    incomplete = update_novel_creation_draft(
        session,
        UUID(draft["id"]),
        expected_version=draft["version"],
        step=4,
        data_patch={"writing_type": "long", "audience": "female", "title": "不完整"},
    )
    with pytest.raises(ValidationError, match="题材"):
        complete_novel_creation_draft(
            session,
            UUID(incomplete["id"]),
            expected_version=incomplete["version"],
        )
    session.rollback()

    completed = _create_long_novel_via_wizard(
        session,
        draft_key="pytest-六步建书",
        title="pytest-六步建书成品",
    )
    novel = completed["novel"]
    assert completed["draft"]["state"] == "completed"
    assert novel["audience"] == "female"
    assert novel["genre"] == "年代言情"
    assert novel["author_name"] == "pytest-作者"
    assert novel["cover_image_data"] == "data:image/jpeg;base64,AA=="
    assert novel["tree"] == []

    replayed = complete_novel_creation_draft(
        session,
        UUID(completed["draft"]["id"]),
        expected_version=1,
    )
    assert replayed["novel"]["id"] == novel["id"]

    with pytest.raises(EntityConflictError):
        update_novel_creation_draft(
            session,
            UUID(completed["draft"]["id"]),
            expected_version=1,
            step=6,
            data_patch={"title": "不应覆盖"},
        )
    session.rollback()


def test_novel_delete_requires_current_version_and_removes_the_exact_novel(
    session: Session,
) -> None:
    completed = _create_long_novel_via_wizard(
        session,
        draft_key="pytest-删除小说",
        title="pytest-待删除小说",
    )
    novel = completed["novel"]
    novel_id = UUID(novel["id"])

    with pytest.raises(ValidationError, match="其他位置更新"):
        delete_novel(session, novel_id, expected_version=novel["version"] + 1)
    session.rollback()
    assert session.get(Novel, novel_id) is not None

    delete_novel(session, novel_id, expected_version=novel["version"])
    assert session.get(Novel, novel_id) is None


def test_private_library_presets_produce_immutable_generation_snapshots(
    session: Session,
) -> None:
    plot = create_private_asset(
        session,
        asset_type="plot",
        title="pytest-桥段",
        content="旧车站误认与重逢。",
    )
    style = create_private_asset(
        session,
        asset_type="writing_style",
        title="pytest-文风",
        content="克制、具象、少用空泛抒情。",
    )
    preset = create_asset_preset(
        session,
        title="pytest-年代言情组合",
        description="桥段和文风组合",
        asset_ids=[UUID(plot["id"]), UUID(style["id"])],
    )
    frozen = snapshot_private_assets(
        session,
        asset_ids=[],
        preset_id=UUID(preset["id"]),
    )
    assert [item["title"] for item in frozen] == ["pytest-桥段", "pytest-文风"]
    assert frozen[0]["version"] == 1

    updated = update_private_asset(
        session,
        UUID(plot["id"]),
        expected_version=plot["version"],
        title="pytest-桥段",
        content="旧车站误认、错过与十年后重逢。",
    )
    refreshed = snapshot_private_assets(
        session,
        asset_ids=[UUID(updated["id"])],
    )
    assert frozen[0]["content"] == "旧车站误认与重逢。"
    assert refreshed[0]["version"] == 2

    archive_private_asset(
        session,
        UUID(style["id"]),
        expected_version=style["version"],
    )
    with pytest.raises(ValidationError, match="不存在或已删除"):
        snapshot_private_assets(
            session,
            asset_ids=[],
            preset_id=UUID(preset["id"]),
        )
    session.rollback()


def test_outline_completion_materializes_roles_and_updates_main_storyline(
    session: Session,
) -> None:
    created = _create_long_novel_via_wizard(
        session,
        draft_key="pytest-大纲建书",
        title="pytest-五步大纲",
    )
    novel_id = UUID(created["novel"]["id"])
    outline = get_or_create_outline_draft(session, novel_id)
    outline = update_outline_draft(
        session,
        novel_id,
        expected_version=outline["version"],
        step=5,
        target_chapter_count=10,
        background_text="一九八八年的县城高中，升学与家庭变迁交织。",
        characters=[
            {"name": "林知夏", "role_type": "main", "description": "重返高三"},
            {"name": "顾明川", "role_type": "main", "description": "理科尖子生"},
        ],
        plot_text="两人从互相试探到共同改变家庭命运。",
        highlight_text="重返一九八八，把错过的青春重新写一遍。",
    )
    first = complete_outline_draft(
        session,
        novel_id,
        expected_version=outline["version"],
    )
    assert first["novel"]["outline_target_chapters"] == 10
    assert [item["name"] for item in first["characters"]] == ["林知夏", "顾明川"]

    create_novel_character(
        session,
        novel_id,
        role_type="supporting",
        name="顾老师",
        description="班主任",
        details={},
    )
    outline = update_outline_draft(
        session,
        novel_id,
        expected_version=first["outline"]["version"],
        step=5,
        characters=[
            {"name": "顾明川", "role_type": "main", "description": "承担家庭压力"},
            {"name": "林知夏", "role_type": "main", "description": "主动修正遗憾"},
            {"name": "沈青", "role_type": "supporting", "description": "同桌"},
        ],
        plot_text="两人先修正报名档案，再面对家庭与高考的双重抉择。",
    )
    second = complete_outline_draft(
        session,
        novel_id,
        expected_version=outline["version"],
    )
    characters = list_novel_characters(session, novel_id)
    assert [item["name"] for item in characters] == [
        "顾明川",
        "林知夏",
        "沈青",
        "顾老师",
    ]
    assert len({item["position"] for item in characters}) == 4
    main_line = next(
        item for item in list_storylines(session, novel_id) if item["storyline_type"] == "main"
    )
    assert main_line["description"] == second["novel"]["main_plot"]


def test_next_chapter_required_roles_reject_uncertain_supporting_inference(
    session: Session,
) -> None:
    novel = create_novel(session, "pytest-下一章必现角色")
    novel_id = UUID(novel["id"])
    document_id = UUID(novel["tree"][0]["documents"][0]["id"])
    create_novel_character(
        session,
        novel_id,
        role_type="main",
        name="苏晚",
        description="电台修复师",
        details={},
    )
    create_novel_character(
        session,
        novel_id,
        role_type="main",
        name="陆沉舟",
        description="灯塔维护工程师",
        details={},
    )
    create_novel_character(
        session,
        novel_id,
        role_type="supporting",
        name="周柚",
        description="咖啡馆老板",
        details={},
    )
    saved = save_draft(
        session,
        document_id,
        expected_draft_version=1,
        content_markdown=(
            "周柚把信放下，说自己先回咖啡馆。"
            "苏晚摊开记录说：『明天我们一起去文化馆查档案。』"
            "陆沉舟点头：『我和你一起去。』两人收好档案，等雨停后离开。"
        ),
    )
    revision = create_checkpoint(
        session,
        document_id,
        expected_draft_version=saved["draft_version"],
    )["revision"]
    proposal = start_intelligence_proposal(
        session, document_id, revision_id=UUID(revision["id"])
    )
    proposal = complete_intelligence_proposal(
        session,
        UUID(proposal["id"]),
        items=[
            {
                "item_type": "next_chapter_required_role",
                "subject": "陆沉舟",
                "predicate": "下一章必现",
                "object": "已明确答应与苏晚一起去文化馆查档案",
                "source_text": "我和你一起去",
                "reasoning_summary": "结尾形成明确的共同计划",
                "confidence": 99,
            },
            {
                "item_type": "next_chapter_required_role",
                "subject": "周柚",
                "predicate": "下一章必现",
                "object": "送来了关键记录",
                "source_text": "周柚把信放下",
                "reasoning_summary": "作为送件人，下一章极可能继续出现",
                "confidence": 70,
            },
        ],
        actual_model_id=MINIMAX_MODEL_ID,
        provider_profile=MINIMAX_PROVIDER_ID,
    )
    commit_intelligence_items(
        session,
        UUID(proposal["id"]),
        accepted_item_ids=[UUID(item["id"]) for item in proposal["items"]],
    )

    characters = list_novel_characters(session, novel_id)
    required = {item["name"] for item in characters if item["required_next_chapter"]}
    assert required == {"苏晚", "陆沉舟"}


def test_six_step_chapter_creation_rejects_cross_book_references(
    session: Session,
) -> None:
    first = _create_long_novel_via_wizard(
        session,
        draft_key="pytest-章节甲建书",
        title="pytest-章节甲",
    )
    second = _create_long_novel_via_wizard(
        session,
        draft_key="pytest-章节乙建书",
        title="pytest-章节乙",
    )
    first_id = UUID(first["novel"]["id"])
    second_id = UUID(second["novel"]["id"])
    first_role = create_novel_character(
        session,
        first_id,
        role_type="main",
        name="林知夏",
        description="主角",
        details={},
    )
    second_role = create_novel_character(
        session,
        second_id,
        role_type="main",
        name="陆沉舟",
        description="另一书主角",
        details={},
    )
    first_line = create_storyline(
        session,
        first_id,
        storyline_type="main",
        title="高考报名线",
        description="核对报名档案",
    )
    second_line = create_storyline(
        session,
        second_id,
        storyline_type="main",
        title="异世界远征线",
        description="不应进入甲书",
    )
    first_foreshadow = create_foreshadow(
        session,
        first_id,
        title="被改动的档案",
        content="报名表上的联系人被人替换。",
        latest_progress="第一章确认联系人栏被改动。",
    )

    draft = get_or_create_chapter_creation_draft(
        session,
        novel_id=first_id,
        volume_id=None,
        draft_key="pytest-章节甲-第一章",
    )
    draft = update_chapter_creation_draft(
        session,
        UUID(draft["id"]),
        expected_version=draft["version"],
        step=6,
        title="第一章 被改动的报名表",
        target_character_count=3000,
        expectation_text="发现档案异常，但暂不揭示幕后人。",
        outline_text="林知夏与顾老师核对报名表，确认联系人栏被改动。",
        data_patch={
            "storyline_ids": [second_line["id"]],
            "required_role_ids": [first_role["id"]],
            "optional_role_ids": [],
            "foreshadow_ids": [first_foreshadow["id"]],
        },
    )
    with pytest.raises(ValidationError, match="故事线包含其他小说"):
        complete_chapter_creation_draft(
            session,
            UUID(draft["id"]),
            expected_version=draft["version"],
        )
    session.rollback()

    draft = update_chapter_creation_draft(
        session,
        UUID(draft["id"]),
        expected_version=draft["version"],
        step=6,
        data_patch={
            "storyline_ids": [first_line["id"]],
            "required_role_ids": [first_role["id"]],
            "optional_role_ids": [],
            "foreshadow_ids": [first_foreshadow["id"]],
        },
    )
    completed = complete_chapter_creation_draft(
        session,
        UUID(draft["id"]),
        expected_version=draft["version"],
    )
    document_id = UUID(completed["document"]["id"])
    assert completed["document"]["volume_id"] is not None
    assert get_chapter_brief(session, document_id)["target_word_count"] == 3000
    replayed = complete_chapter_creation_draft(
        session,
        UUID(draft["id"]),
        expected_version=1,
    )
    assert replayed["document"]["id"] == completed["document"]["id"]

    with pytest.raises(ValidationError, match="已属于其他小说"):
        get_or_create_chapter_creation_draft(
            session,
            novel_id=second_id,
            volume_id=None,
            draft_key="pytest-章节甲-第一章",
        )
    session.rollback()
    assert second_role["novel_id"] == str(second_id)


def test_generation_requires_verified_minimax_and_acceptance_window(
    session: Session,
) -> None:
    novel = create_novel(session, "pytest-MiniMax门槛")
    document_id = UUID(novel["tree"][0]["documents"][0]["id"])
    brief = save_chapter_brief(
        session,
        document_id,
        expected_version=0,
        target_word_count=5000,
        expectation_text="建立冲突",
        outline_text="人物发现关键证据。",
        forbidden_text="",
        role_constraints={},
    )
    with pytest.raises(ValidationError, match="固定为 MiniMax M3"):
        start_chapter_generation(
            session,
            document_id,
            expected_brief_version=brief["version"],
            requested_model_id="MiniMax-M30",
        )
    session.rollback()

    first_job = start_chapter_generation(
        session,
        document_id,
        expected_brief_version=brief["version"],
    )
    assert first_job["target_visible_character_count"] == 1000
    with pytest.raises(ValidationError, match="必须整章重写"):
        complete_chapter_generation(
            session,
            UUID(first_job["id"]),
            content_markdown="这一章太短。",
            actual_model_id=MINIMAX_MODEL_ID,
            provider_profile=MINIMAX_PROVIDER_ID,
        )
    failed = list_chapter_generation_jobs(session, document_id)[0]
    assert failed["state"] == "failed"
    assert failed["validation_state"] == "below_target"
    assert session.scalar(
        select(func.count(CandidateRevision.id)).where(
            CandidateRevision.generation_job_id == UUID(first_job["id"])
        )
    ) == 0

    second_job = start_chapter_generation(
        session,
        document_id,
        expected_brief_version=brief["version"],
        force_new=True,
    )
    completed = complete_chapter_generation(
        session,
        UUID(second_job["id"]),
        content_markdown=_long_chapter("人物终于找到能够推进调查的关键证据。", paragraphs=22),
        model_profile_fingerprint="qwenpaw:provider-usage:minimax-cn:MiniMax-M3",
        actual_model_id=MINIMAX_MODEL_ID,
        provider_profile=MINIMAX_PROVIDER_ID,
    )
    assert completed["attempt"] == 2
    assert completed["state"] == "ready"
    assert completed["validation_state"] == "meets_target"
    assert 1000 <= completed["output_visible_character_count"] <= 1500
    assert completed["actual_model_id"] == MINIMAX_MODEL_ID


def test_cover_settings_and_narrative_foreshadow_progress_persist(
    session: Session,
) -> None:
    novel = create_novel(session, "pytest-封面与伏笔进展")
    novel_id = UUID(novel["id"])
    updated = update_novel_settings(
        session,
        novel_id,
        expected_version=novel["version"],
        genre="悬疑",
        subgenre="悬疑脑洞",
        idea="档案馆里的未来录音带。",
        template_name="悬疑探案",
        template_data={"lead_name": "林默"},
        cover_image_data="data:image/jpeg;base64,ZmFrZQ==",
    )
    assert updated["cover_image_data"] == "data:image/jpeg;base64,ZmFrZQ=="

    created = create_foreshadow(
        session,
        novel_id,
        title="无源录音",
        content="未接电源的磁带机自行启动。",
        latest_progress="第一章确认录音来自明日。",
    )
    assert created["latest_progress"] == "第一章确认录音来自明日。"
    changed = update_foreshadow(
        session,
        novel_id,
        UUID(created["id"]),
        expected_version=created["version"],
        title=created["title"],
        content=created["content"],
        latest_progress="第五章确认录音与旧案重合。",
        status="active",
        progress=30,
    )
    assert changed["latest_progress"] == "第五章确认录音与旧案重合。"
    assert list_foreshadows(session, novel_id)[0]["latest_progress"] == changed["latest_progress"]


def test_structured_creative_jobs_keep_failed_attempts_and_model_identity(
    session: Session,
) -> None:
    draft = get_or_create_novel_creation_draft(session, "pytest-创作生成")
    snapshot = {
        "audience": "female",
        "genre": "年代言情",
        "idea": "重回一九八八年的高三。",
    }
    with pytest.raises(ValidationError, match="固定为 MiniMax M3"):
        start_creative_generation(
            session,
            scope_type="novel_creation",
            scope_id=UUID(draft["id"]),
            kind="novel_naming",
            input_snapshot=snapshot,
            requested_model_id="qwen3.7-plus",
        )
    session.rollback()

    first = start_creative_generation(
        session,
        scope_type="novel_creation",
        scope_id=UUID(draft["id"]),
        kind="novel_naming",
        input_snapshot=snapshot,
    )
    with pytest.raises(ValidationError, match="实际模型不是 MiniMax M3"):
        complete_creative_generation(
            session,
            UUID(first["id"]),
            actual_model_id="qwen3.7-plus",
            provider_profile="bailian",
            output_json={"titles": ["错误模型书名"]},
        )

    second = start_creative_generation(
        session,
        scope_type="novel_creation",
        scope_id=UUID(draft["id"]),
        kind="novel_naming",
        input_snapshot=snapshot,
        force_new=True,
    )
    second = complete_creative_generation(
        session,
        UUID(second["id"]),
        actual_model_id=MINIMAX_MODEL_ID,
        provider_profile=MINIMAX_PROVIDER_ID,
        output_text='{"titles":["风从一九八八的操场吹来"]}',
        output_json={"titles": ["风从一九八八的操场吹来"]},
    )
    history = list_creative_generations(
        session,
        scope_type="novel_creation",
        scope_id=UUID(draft["id"]),
    )
    assert {item["state"] for item in history} == {"failed", "ready"}
    assert second["attempt"] == 2
    assert second["actual_model_id"] == MINIMAX_MODEL_ID
    assert second["input_snapshot"] == snapshot


def test_volume_chapter_reorder_delete_guard_and_export_structure(
    session: Session,
) -> None:
    novel = create_novel(session, "pytest-卷章导出")
    novel_id = UUID(novel["id"])
    first_volume_id = UUID(novel["tree"][0]["id"])
    first_document_id = UUID(novel["tree"][0]["documents"][0]["id"])
    second_volume = create_volume(session, novel_id, "第二卷")
    second_volume_id = UUID(second_volume["id"])
    second_document = create_document(
        session,
        novel_id,
        "第二章",
        volume_id=second_volume_id,
    )
    ungrouped = create_document(session, novel_id, "卷外章")
    for document_id, opening in (
        (first_document_id, "第一章正文。"),
        (UUID(second_document["id"]), "第二章正文。"),
        (UUID(ungrouped["id"]), "卷外章正文。"),
    ):
        save_draft(
            session,
            document_id,
            expected_draft_version=1,
            content_markdown=_long_chapter(opening),
        )

    initial_export = build_novel_export(session, novel_id, export_format="markdown")
    assert "## 第一卷" in initial_export["content"]
    assert "## 第二卷" in initial_export["content"]
    assert "## 未分卷" in initial_export["content"]
    assert initial_export["metadata"]["chapter_count"] == 3

    reordered_volumes = reorder_volumes(
        session,
        novel_id,
        ordered_volume_ids=[second_volume_id, first_volume_id],
    )
    assert [item["title"] for item in reordered_volumes] == ["第二卷", "第一卷"]
    reordered_chapters = reorder_chapters(
        session,
        novel_id,
        ordered_document_ids=[
            UUID(ungrouped["id"]),
            UUID(second_document["id"]),
            first_document_id,
        ],
        volume_by_document={str(ungrouped["id"]): first_volume_id},
    )
    assert [item["title"] for item in reordered_chapters] == [
        "卷外章",
        "第二章",
        "第一章",
    ]
    moved_export = build_novel_export(session, novel_id, export_format="text")
    assert moved_export["metadata"]["ungrouped_chapter_count"] == 0
    assert moved_export["metadata"]["chapter_count"] == 3

    current_second_volume = reordered_volumes[0]
    delete_volume(
        session,
        novel_id,
        second_volume_id,
        expected_version=current_second_volume["version"],
        move_documents_to=first_volume_id,
    )
    remaining = get_novel(session, novel_id)["tree"][0]
    with pytest.raises(ValidationError, match="至少需要保留一个分卷"):
        delete_volume(
            session,
            novel_id,
            UUID(remaining["id"]),
            expected_version=remaining["version"],
        )
    session.rollback()
