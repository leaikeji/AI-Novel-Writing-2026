from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
from threading import Barrier, Event
from uuid import UUID

import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.orm import Session

from backend.creative_data_models import (
    CharacterInstance,
    CharacterInstanceRevision,
    NovelCharacterRevision,
    StoryTimeline,
)
from backend.story_state.contracts import StoryEventLinkType
from backend.story_state.persistence import (
    create_merge_timeline,
    create_story_event_link,
    fork_timeline,
    get_story_projection_payload,
    list_story_event_link_payloads,
)

from backend.creative_services import (
    CharacterLinkRequiredError,
    EntityConflictError,
    archive_private_asset,
    apply_relationship_graph_generation,
    batch_character_relationships,
    build_relationship_graph_snapshot,
    build_novel_export,
    complete_chapter_creation_draft,
    complete_creative_generation as _complete_creative_generation,
    complete_novel_creation_draft,
    complete_outline_draft,
    create_asset_preset,
    create_character_relationship,
    create_foreshadow,
    create_novel_character,
    create_private_asset,
    create_storyline,
    delete_character_relationship,
    delete_document,
    delete_foreshadow,
    delete_novel_character,
    delete_storyline,
    delete_volume,
    fail_creative_generation,
    get_relationship_graph_view,
    get_relationship_auto_sync_status,
    get_or_create_chapter_creation_draft,
    get_or_create_novel_creation_draft,
    get_or_create_outline_draft,
    list_creative_generations,
    list_character_relationship_history,
    list_character_relationships,
    list_foreshadows,
    list_novel_characters,
    list_storylines,
    reorder_chapters,
    reorder_volumes,
    restore_character_relationship,
    save_relationship_graph_view,
    snapshot_private_assets,
    start_creative_generation as _start_creative_generation,
    update_chapter_creation_draft,
    update_foreshadow,
    update_document_metadata,
    update_novel_settings,
    update_novel_creation_draft,
    update_outline_draft,
    update_novel_character,
    update_private_asset,
    update_character_relationship,
    update_storyline,
    update_volume,
)
from backend.models import (
    CandidateRevision,
    ChapterCreationDraft,
    ChapterGenerationJob,
    CharacterRelationship,
    CharacterRelationshipRevision,
    DerivedSourceBinding,
    Document,
    DocumentRevision,
    DocumentWorkingCopy,
    IntelligenceCommitBatch,
    IntelligenceProposal,
    IntelligenceProposalItem,
    Novel,
    Foreshadow,
    StoryFact,
    Storyline,
    Volume,
)
from backend.embedding.writing import resolve_writing_position
from backend.volume_chapter_titles import VolumeChapterContractError
from backend.services import (
    CandidateConflictError,
    ChapterLengthValidationError,
    ValidationError,
    adopt_candidate,
    commit_intelligence_items,
    complete_chapter_generation as _complete_chapter_generation,
    complete_intelligence_proposal as _complete_intelligence_proposal,
    DraftConflictError,
    IntelligenceCommitConflictError,
    fail_chapter_generation,
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
    preview_restore_revision,
    restore_revision,
    save_chapter_brief,
    save_draft,
    search_novel,
    start_chapter_generation as _start_chapter_generation,
    start_intelligence_proposal as _start_intelligence_proposal,
)


TEST_DATABASE_URL = os.environ.get("AI_NOVEL_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="integration database not configured")
TEST_AGENT_ID = "ai-novel-writer"
TEST_MODEL_ID = "model-test-v1"
TEST_PROVIDER_ID = "provider-test"
TEST_CONTRACT_VERSION = "follow-agent-effective-test-v1"


def _requested_model_kwargs() -> dict[str, str]:
    return {
        "execution_agent_id": TEST_AGENT_ID,
        "requested_provider_id": TEST_PROVIDER_ID,
        "requested_model_id": TEST_MODEL_ID,
        "generation_contract_version": TEST_CONTRACT_VERSION,
    }


def _story_facts(session: Session, novel_id: UUID) -> list[dict[str, object]]:
    """Read authoritative fact rows directly; no retired API compatibility helper."""

    rows = session.scalars(
        select(StoryFact)
        .where(StoryFact.novel_id == novel_id)
        .order_by(StoryFact.created_at, StoryFact.id)
    )
    return [
        {
            "id": str(row.id),
            "fact_type": row.fact_type,
            "subject": row.subject,
            "relationship_id": (
                str(row.relationship_id) if row.relationship_id else None
            ),
            "source_revision_id": (
                str(row.source_revision_id) if row.source_revision_id else None
            ),
            "status": row.status,
        }
        for row in rows
    ]


def start_chapter_generation(*args, **kwargs):
    for key, value in _requested_model_kwargs().items():
        kwargs.setdefault(key, value)
    kwargs.setdefault("writing_position", resolve_writing_position(args[0], args[1]))
    kwargs.setdefault("effective_context_window_tokens", 131_072)
    return _start_chapter_generation(*args, **kwargs)


def start_intelligence_proposal(*args, **kwargs):
    for key, value in _requested_model_kwargs().items():
        kwargs.setdefault(key, value)
    return _start_intelligence_proposal(*args, **kwargs)


def start_creative_generation(*args, **kwargs):
    for key, value in _requested_model_kwargs().items():
        kwargs.setdefault(key, value)
    return _start_creative_generation(*args, **kwargs)


def _actual_model_kwargs(kwargs: dict[str, object]) -> dict[str, object]:
    normalized = dict(kwargs)
    normalized.pop("model_profile_fingerprint", None)
    legacy_provider = normalized.pop("provider_profile", None)
    normalized.setdefault(
        "actual_provider_id",
        legacy_provider if legacy_provider is not None else TEST_PROVIDER_ID,
    )
    normalized.setdefault("actual_model_id", TEST_MODEL_ID)
    return normalized


def complete_chapter_generation(*args, **kwargs):
    return _complete_chapter_generation(*args, **_actual_model_kwargs(kwargs))


def complete_intelligence_proposal(*args, **kwargs):
    return _complete_intelligence_proposal(*args, **_actual_model_kwargs(kwargs))


def complete_creative_generation(*args, **kwargs):
    return _complete_creative_generation(*args, **_actual_model_kwargs(kwargs))


def _long_chapter(opening: str, *, paragraphs: int = 21) -> str:
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
    cover_mode: str = "system",
    cover_image_data: str = "data:image/jpeg;base64,AA==",
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
            "cover_mode": cover_mode,
            "cover_image_data": cover_image_data,
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
                "'story_facts','media_assets','chapter_briefs',"
                "'chapter_generation_jobs','candidate_revisions','intelligence_proposals',"
                "'intelligence_proposal_items','intelligence_commit_batches',"
                "'derived_source_bindings','novel_creation_drafts','private_assets',"
                "'asset_presets','asset_preset_items','outline_drafts',"
                "'novel_characters','character_relationships','storylines',"
                "'character_relationship_revisions','relationship_graph_views',"
                "'relationship_graph_positions',"
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
        "character_relationship_revisions",
        "relationship_graph_views",
        "relationship_graph_positions",
        "storylines",
        "foreshadows",
        "chapter_creation_drafts",
        "creative_generation_jobs",
        "novel_exports",
    }

    model_evidence_columns = {
        "execution_agent_id",
        "requested_provider_id",
        "requested_model_id",
        "generation_contract_version",
        "actual_provider_id",
        "actual_model_id",
        "provider_profile",
        "attempt",
    }
    for table_name in (
        "chapter_generation_jobs",
        "intelligence_proposals",
        "creative_generation_jobs",
    ):
        generation_columns = {
            row[0]
            for row in session.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name=:table_name"
                ),
                {"table_name": table_name},
            )
        }
        assert model_evidence_columns <= generation_columns

    chapter_generation_columns = {
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
        "target_visible_character_count",
        "output_visible_character_count",
        "validation_state",
    } <= chapter_generation_columns

    requested_model_defaults = dict(
        session.execute(
            text(
                "SELECT table_name, column_default FROM information_schema.columns "
                "WHERE table_schema='public' AND column_name='requested_model_id' "
                "AND table_name IN ('chapter_generation_jobs', "
                "'intelligence_proposals', 'creative_generation_jobs')"
            )
        ).all()
    )
    assert requested_model_defaults == {
        "chapter_generation_jobs": None,
        "intelligence_proposals": None,
        "creative_generation_jobs": None,
    }
    generation_constraints = {
        row[0]
        for row in session.execute(
            text(
                "SELECT conname FROM pg_constraint WHERE conname IN "
                "('uq_chapter_generation_attempt', 'uq_intelligence_revision_attempt', "
                "'uq_creative_generation_attempt')"
            )
        )
    }
    assert generation_constraints == {
        "uq_chapter_generation_attempt",
        "uq_intelligence_revision_attempt",
        "uq_creative_generation_attempt",
    }

    relationship_columns = {
        row[0]
        for row in session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='character_relationships'"
            )
        )
    }
    assert {
        "directionality",
        "relation_kind",
        "label",
        "normalized_label",
        "relation_pair_key",
        "current_revision_id",
        "archived_at",
        "manual_override",
        "confidence",
        "evidence_json",
        "source_generation_job_id",
    } <= relationship_columns


def test_sync_progress_incrementally_materializes_relationships_and_respects_manual_override(
    session: Session,
) -> None:
    novel = create_novel(session, "pytest-同步进展关系网")
    novel_id = UUID(novel["id"])
    document_id = UUID(novel["tree"][0]["documents"][0]["id"])
    source = create_novel_character(
        session,
        novel_id,
        role_type="main",
        name="苏晚",
        description="旧电台修复师",
        details={},
    )
    target = create_novel_character(
        session,
        novel_id,
        role_type="supporting",
        name="陆沉舟",
        description="灯塔维护工程师",
        details={},
    )
    planned = create_character_relationship(
        session,
        novel_id,
        source_character_id=UUID(source["id"]),
        target_character_id=UUID(target["id"]),
        directionality="undirected",
        relation_kind="ally",
        label="调查同盟",
        description="作者规划的关系根。",
    )
    saved = save_draft(
        session,
        document_id,
        expected_draft_version=1,
        content_markdown="苏晚与陆沉舟约定共同调查旧电台档案。陆沉舟说：『我们一起查到底。』",
    )
    revision = create_checkpoint(
        session,
        document_id,
        expected_draft_version=saved["draft_version"],
    )["revision"]
    proposal = start_intelligence_proposal(
        session,
        document_id,
        revision_id=UUID(revision["id"]),
    )
    proposal_row = session.get(IntelligenceProposal, UUID(proposal["id"]))
    assert proposal_row is not None
    relationship_key = next(
        key
        for key, value in proposal_row.extraction_context_json["relationship_catalog"].items()
        if value["relationship_id"] == planned["id"]
    )
    proposal = complete_intelligence_proposal(
        session,
        UUID(proposal["id"]),
        items=[
            {
                "fact_type": "relationship_state",
                "entity_key": relationship_key,
                "dimension": "alliance",
                "event_kind": "formed",
                "subject": "苏晚与陆沉舟",
                "predicate": "结成同盟",
                "object": "共同调查旧电台档案",
                "source_text": "我们一起查到底",
                "reasoning_summary": "形成稳定协作关系",
                "confidence": 93,
                "details": {},
            }
        ],
        actual_model_id=TEST_MODEL_ID,
        provider_profile=TEST_PROVIDER_ID,
    )
    committed = commit_intelligence_items(
        session,
        UUID(proposal["id"]),
        accepted_item_ids=[UUID(item["id"]) for item in proposal["items"]],
    )
    assert committed["relationship_sync"] == {"created": 0, "updated": 1, "skipped": 0}
    projected_existing = list_character_relationships(session, novel_id)[0]
    assert projected_existing["label"] == planned["label"]
    assert projected_existing["version"] == planned["version"]
    assert projected_existing["manual_override"] is True

    generated = list_character_relationships(session, novel_id)[0]
    assert generated["id"] == planned["id"]
    fact = _story_facts(session, novel_id)[0]
    assert fact["fact_type"] == "relationship_state"
    assert fact["relationship_id"] == planned["id"]

    edited = update_character_relationship(
        session,
        novel_id,
        UUID(generated["id"]),
        expected_version=generated["version"],
        source_character_id=UUID(source["id"]),
        target_character_id=UUID(target["id"]),
        directionality="undirected",
        relation_kind="ally",
        label="作者确认的同盟",
        description="作者手动修正后的关系。",
    )
    assert edited["manual_override"] is True

    assert list_character_relationships(session, novel_id)[0]["label"] == "作者确认的同盟"


def test_sync_progress_can_create_the_first_relationship_atomically_and_idempotently(
    session: Session,
) -> None:
    novel = create_novel(session, "pytest-同步进展首条关系")
    novel_id = UUID(novel["id"])
    document_id = UUID(novel["tree"][0]["documents"][0]["id"])
    source = create_novel_character(
        session,
        novel_id,
        role_type="main",
        name="苏晚",
        description="旧电台修复师",
        details={},
    )
    target = create_novel_character(
        session,
        novel_id,
        role_type="supporting",
        name="陆沉舟",
        description="灯塔维护工程师",
        details={},
    )
    saved = save_draft(
        session,
        document_id,
        expected_draft_version=1,
        content_markdown="苏晚与陆沉舟约定共同调查旧电台档案。陆沉舟说：『我们一起查到底。』",
    )
    revision = create_checkpoint(
        session,
        document_id,
        expected_draft_version=saved["draft_version"],
    )["revision"]
    proposal = start_intelligence_proposal(
        session,
        document_id,
        revision_id=UUID(revision["id"]),
    )
    proposal_row = session.get(IntelligenceProposal, UUID(proposal["id"]))
    assert proposal_row is not None
    assert proposal_row.extraction_context_json["relationship_catalog"] == {}
    character_key_by_id = {
        value["character_id"]: key
        for key, value in proposal_row.extraction_context_json["character_catalog"].items()
    }
    proposal = complete_intelligence_proposal(
        session,
        UUID(proposal["id"]),
        items=[
            {
                "fact_type": "relationship_state",
                "source_character_key": character_key_by_id[source["id"]],
                "target_character_key": character_key_by_id[target["id"]],
                "directionality": "undirected",
                "relation_kind": "ally",
                "relationship_label": "调查同盟",
                "dimension": "alliance",
                "event_kind": "formed",
                "subject": "苏晚与陆沉舟",
                "predicate": "结成同盟",
                "object": "共同调查旧电台档案",
                "source_text": "我们一起查到底",
                "reasoning_summary": "形成稳定协作关系",
                "confidence": 93,
                "details": {},
            },
            {
                "fact_type": "general_fact",
                "subject": "旧电台档案",
                "predicate": "调查状态",
                "object": "等待共同核查",
                "source_text": "共同调查旧电台档案",
                "reasoning_summary": "用于验证不同接受集合不能复用操作键",
                "confidence": 88,
            },
        ],
        actual_model_id=TEST_MODEL_ID,
        provider_profile=TEST_PROVIDER_ID,
    )
    assert proposal["items"][0]["suggested_payload"]["entity"]["is_new"] is True
    assert list_character_relationships(session, novel_id) == []
    ledger_before = session.get(Novel, novel_id).story_ledger_version
    operation_key = "commit-first-relationship"

    selected = [UUID(proposal["items"][0]["id"])]
    committed = commit_intelligence_items(
        session,
        UUID(proposal["id"]),
        accepted_item_ids=selected,
        expected_story_ledger_version=ledger_before,
        operation_key=operation_key,
    )

    assert committed["changed"] is True
    assert committed["replayed"] is False
    assert committed["outcome"] == "committed"
    assert committed["relationship_sync"] == {"created": 1, "updated": 0, "skipped": 0}
    relationships = list_character_relationships(session, novel_id)
    assert len(relationships) == 1
    relationship = relationships[0]
    assert relationship["label"] == "调查同盟"
    assert relationship["manual_override"] is False
    assert relationship["created_by"] == "ai_auto"
    facts = _story_facts(session, novel_id)
    assert len(facts) == 1
    assert facts[0]["relationship_id"] == relationship["id"]
    assert session.scalar(
        select(func.count(CharacterRelationshipRevision.id)).where(
            CharacterRelationshipRevision.relationship_id == UUID(relationship["id"])
        )
    ) == 1
    assert session.get(Novel, novel_id).story_ledger_version == ledger_before + 1

    replayed = commit_intelligence_items(
        session,
        UUID(proposal["id"]),
        accepted_item_ids=selected,
        expected_story_ledger_version=ledger_before,
        operation_key=operation_key,
    )
    assert replayed["commit_batch"]["id"] == committed["commit_batch"]["id"]
    assert replayed["relationship_sync"] == committed["relationship_sync"]
    assert replayed["changed"] is False
    assert replayed["replayed"] is True
    assert replayed["outcome"] == "already_committed"
    assert session.scalar(
        select(func.count(CharacterRelationship.id)).where(
            CharacterRelationship.novel_id == novel_id
        )
    ) == 1
    assert session.scalar(
        select(func.count(StoryFact.id)).where(StoryFact.novel_id == novel_id)
    ) == 1
    assert session.scalar(
        select(func.count(CharacterRelationshipRevision.id)).where(
            CharacterRelationshipRevision.relationship_id == UUID(relationship["id"])
        )
    ) == 1
    assert session.get(Novel, novel_id).story_ledger_version == ledger_before + 1

    with pytest.raises(IntelligenceCommitConflictError) as payload_conflict:
        commit_intelligence_items(
            session,
            UUID(proposal["id"]),
            accepted_item_ids=[UUID(proposal["items"][1]["id"])],
            expected_story_ledger_version=ledger_before + 1,
            operation_key=operation_key,
        )
    assert payload_conflict.value.code == "idempotency_conflict"
    session.rollback()

    with pytest.raises(IntelligenceCommitConflictError) as version_conflict:
        commit_intelligence_items(
            session,
            UUID(proposal["id"]),
            accepted_item_ids=selected,
            expected_story_ledger_version=ledger_before,
            operation_key="commit-new-stale-attempt",
        )
    assert version_conflict.value.code == "story_ledger_version_conflict"
    assert version_conflict.value.current == {
        "story_ledger_version": ledger_before + 1
    }
    session.rollback()

    no_change = commit_intelligence_items(
        session,
        UUID(proposal["id"]),
        accepted_item_ids=selected,
        expected_story_ledger_version=ledger_before + 1,
        operation_key="commit-no-change-receipt",
    )
    assert no_change["changed"] is False
    assert no_change["replayed"] is False
    assert no_change["outcome"] == "no_change"
    assert no_change["commit_batch"]["state"] == "no_change"
    assert session.get(Novel, novel_id).story_ledger_version == ledger_before + 1
    committed_batches = session.scalars(
        select(IntelligenceCommitBatch).where(
            IntelligenceCommitBatch.proposal_id == UUID(proposal["id"]),
            IntelligenceCommitBatch.state == "committed",
        )
    ).all()
    assert all(
        dict(batch.inverse_operations or {}).get("created_story_fact_ids")
        for batch in committed_batches
    )

    no_change_replay = commit_intelligence_items(
        session,
        UUID(proposal["id"]),
        accepted_item_ids=selected,
        expected_story_ledger_version=ledger_before,
        operation_key="commit-no-change-receipt",
    )
    assert no_change_replay["commit_batch"]["id"] == no_change["commit_batch"]["id"]
    assert no_change_replay["changed"] is False
    assert no_change_replay["replayed"] is True
    assert no_change_replay["outcome"] == "no_change"
    assert session.get(Novel, novel_id).story_ledger_version == ledger_before + 1


def test_intelligence_commit_concurrent_same_operation_replays_once(
    session: Session,
) -> None:
    novel = create_novel(session, "pytest-情报提交并发幂等")
    novel_id = UUID(novel["id"])
    document_id = UUID(novel["tree"][0]["documents"][0]["id"])
    saved = save_draft(
        session,
        document_id,
        expected_draft_version=1,
        content_markdown="蓝色车票留在抽屉里。",
    )
    revision = create_checkpoint(
        session,
        document_id,
        expected_draft_version=saved["draft_version"],
    )["revision"]
    proposal = start_intelligence_proposal(
        session,
        document_id,
        revision_id=UUID(revision["id"]),
    )
    proposal = complete_intelligence_proposal(
        session,
        UUID(proposal["id"]),
        items=[
            {
                "fact_type": "general_fact",
                "subject": "车票",
                "predicate": "颜色",
                "object": "蓝色",
                "source_text": "蓝色车票",
                "reasoning_summary": "正文明确给出颜色",
                "confidence": 99,
            }
        ],
        actual_model_id=TEST_MODEL_ID,
        provider_profile=TEST_PROVIDER_ID,
    )
    proposal_id = UUID(proposal["id"])
    selected = [UUID(proposal["items"][0]["id"])]
    ledger_before = session.get(Novel, novel_id).story_ledger_version
    barrier = Barrier(2)
    worker_engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)

    def submit() -> dict[str, object]:
        with Session(worker_engine, expire_on_commit=False) as worker:
            barrier.wait()
            return commit_intelligence_items(
                worker,
                proposal_id,
                accepted_item_ids=selected,
                expected_story_ledger_version=ledger_before,
                operation_key="concurrent-intelligence-commit",
            )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _index: submit(), range(2)))
    finally:
        worker_engine.dispose()

    assert sorted(result["changed"] for result in results) == [False, True]
    assert sorted(result["replayed"] for result in results) == [False, True]
    assert {result["commit_batch"]["id"] for result in results} == {
        results[0]["commit_batch"]["id"]
    }
    session.expire_all()
    assert session.get(Novel, novel_id).story_ledger_version == ledger_before + 1
    assert session.scalar(
        select(func.count(StoryFact.id)).where(StoryFact.novel_id == novel_id)
    ) == 1
    assert session.scalar(
        select(func.count(IntelligenceCommitBatch.id)).where(
            IntelligenceCommitBatch.proposal_id == proposal_id
        )
    ) == 1


def test_incremental_relationship_visibility_tracks_source_revision_and_manual_override(
    session: Session,
) -> None:
    novel = create_novel(session, "pytest-同步关系来源有效性")
    novel_id = UUID(novel["id"])
    document_id = UUID(novel["tree"][0]["documents"][0]["id"])
    source = create_novel_character(
        session,
        novel_id,
        role_type="main",
        name="苏晚",
        description="旧电台修复师",
        details={},
    )
    target = create_novel_character(
        session,
        novel_id,
        role_type="supporting",
        name="陆沉舟",
        description="灯塔维护工程师",
        details={},
    )
    relationship_text = "苏晚与陆沉舟约定共同调查旧电台档案。"
    saved = save_draft(
        session,
        document_id,
        expected_draft_version=1,
        content_markdown=relationship_text,
    )
    relationship_revision = create_checkpoint(
        session,
        document_id,
        expected_draft_version=saved["draft_version"],
    )["revision"]
    proposal = start_intelligence_proposal(
        session,
        document_id,
        revision_id=UUID(relationship_revision["id"]),
    )
    proposal_row = session.get(IntelligenceProposal, UUID(proposal["id"]))
    assert proposal_row is not None
    character_key_by_id = {
        value["character_id"]: key
        for key, value in proposal_row.extraction_context_json["character_catalog"].items()
    }
    proposal = complete_intelligence_proposal(
        session,
        UUID(proposal["id"]),
        items=[
            {
                "fact_type": "relationship_state",
                "source_character_key": character_key_by_id[source["id"]],
                "target_character_key": character_key_by_id[target["id"]],
                "directionality": "undirected",
                "relation_kind": "ally",
                "relationship_label": "调查同盟",
                "dimension": "alliance",
                "event_kind": "formed",
                "subject": "苏晚与陆沉舟",
                "predicate": "结成同盟",
                "object": "共同调查旧电台档案",
                "source_text": relationship_text,
                "reasoning_summary": "形成稳定协作关系",
                "confidence": 93,
                "details": {},
            }
        ],
        actual_model_id=TEST_MODEL_ID,
        provider_profile=TEST_PROVIDER_ID,
    )
    commit_intelligence_items(
        session,
        UUID(proposal["id"]),
        accepted_item_ids=[UUID(proposal["items"][0]["id"])],
    )

    current = list_character_relationships(session, novel_id)
    assert len(current) == 1
    relationship_id = UUID(current[0]["id"])
    assert get_relationship_auto_sync_status(session, novel_id)["ai_relationship_count"] == 1

    rewritten = save_draft(
        session,
        document_id,
        expected_draft_version=3,
        content_markdown="苏晚独自整理旧电台档案。",
    )
    assert rewritten["draft_version"] == 4
    assert len(list_character_relationships(session, novel_id)) == 1
    rewritten_revision = create_checkpoint(
        session,
        document_id,
        expected_draft_version=rewritten["draft_version"],
    )["revision"]
    assert rewritten_revision["content_markdown"] == "苏晚独自整理旧电台档案。"
    assert list_character_relationships(session, novel_id) == []
    assert len(list_character_relationships(session, novel_id, include_archived=True)) == 1
    assert get_relationship_auto_sync_status(session, novel_id)["ai_relationship_count"] == 0

    restored = restore_revision(
        session,
        document_id,
        UUID(relationship_revision["id"]),
        expected_draft_version=5,
    )
    assert restored["document"]["content_markdown"] == relationship_text
    assert [relation["id"] for relation in list_character_relationships(session, novel_id)] == [
        str(relationship_id)
    ]
    restored_status = get_relationship_auto_sync_status(session, novel_id)
    assert restored_status["source_summary"]["relationship_facts"] == 1
    assert restored_status["ai_relationship_count"] == 1

    manual = update_character_relationship(
        session,
        novel_id,
        relationship_id,
        expected_version=current[0]["version"],
        source_character_id=UUID(source["id"]),
        target_character_id=UUID(target["id"]),
        directionality="undirected",
        relation_kind="ally",
        label="作者确认的调查同盟",
        description="作者确认后不再随来源章节失效而隐藏。",
    )
    rewritten_again = save_draft(
        session,
        document_id,
        expected_draft_version=restored["document"]["draft_version"],
        content_markdown="苏晚再次独自整理档案。",
    )
    assert rewritten_again["draft_version"] > rewritten["draft_version"]
    assert list_character_relationships(session, novel_id)[0]["id"] == manual["id"]
    assert get_relationship_auto_sync_status(session, novel_id)["manual_relationship_count"] == 1


def test_sync_progress_rejects_an_unknown_new_relationship_character_key_without_writes(
    session: Session,
) -> None:
    novel = create_novel(session, "pytest-同步进展关系越权")
    novel_id = UUID(novel["id"])
    document_id = UUID(novel["tree"][0]["documents"][0]["id"])
    create_novel_character(
        session,
        novel_id,
        role_type="main",
        name="苏晚",
        description="旧电台修复师",
        details={},
    )
    create_novel_character(
        session,
        novel_id,
        role_type="supporting",
        name="陆沉舟",
        description="灯塔维护工程师",
        details={},
    )
    saved = save_draft(
        session,
        document_id,
        expected_draft_version=1,
        content_markdown="苏晚与陆沉舟约定共同调查旧电台档案。",
    )
    revision = create_checkpoint(
        session,
        document_id,
        expected_draft_version=saved["draft_version"],
    )["revision"]
    proposal = start_intelligence_proposal(
        session,
        document_id,
        revision_id=UUID(revision["id"]),
    )

    with pytest.raises(ValidationError, match="关系候选包含无效或越权"):
        complete_intelligence_proposal(
            session,
            UUID(proposal["id"]),
            items=[
                {
                    "fact_type": "relationship_state",
                    "source_character_key": "character_1",
                    "target_character_key": "character_999",
                    "directionality": "undirected",
                    "relation_kind": "ally",
                    "relationship_label": "调查同盟",
                    "subject": "苏晚与陆沉舟",
                    "predicate": "结成同盟",
                    "object": "共同调查旧电台档案",
                    "source_text": "苏晚与陆沉舟约定共同调查旧电台档案",
                    "reasoning_summary": "形成协作关系",
                    "confidence": 93,
                }
            ],
            actual_model_id=TEST_MODEL_ID,
            provider_profile=TEST_PROVIDER_ID,
        )
    session.rollback()

    assert session.scalar(
        select(func.count(CharacterRelationship.id)).where(
            CharacterRelationship.novel_id == novel_id
        )
    ) == 0
    assert session.scalar(
        select(func.count(StoryFact.id)).where(StoryFact.novel_id == novel_id)
    ) == 0


def test_sync_progress_counts_a_new_relationship_once_when_two_events_share_it(
    session: Session,
) -> None:
    novel = create_novel(session, "pytest-同步进展关系计数")
    novel_id = UUID(novel["id"])
    document_id = UUID(novel["tree"][0]["documents"][0]["id"])
    source = create_novel_character(
        session,
        novel_id,
        role_type="main",
        name="苏晚",
        description="旧电台修复师",
        details={},
    )
    target = create_novel_character(
        session,
        novel_id,
        role_type="supporting",
        name="陆沉舟",
        description="灯塔维护工程师",
        details={},
    )
    saved = save_draft(
        session,
        document_id,
        expected_draft_version=1,
        content_markdown=(
            "苏晚与陆沉舟约定共同调查旧电台档案。"
            "档案核对结束后，两人又约定共同保护原始母带。"
        ),
    )
    revision = create_checkpoint(
        session,
        document_id,
        expected_draft_version=saved["draft_version"],
    )["revision"]
    proposal = start_intelligence_proposal(
        session,
        document_id,
        revision_id=UUID(revision["id"]),
    )
    proposal_row = session.get(IntelligenceProposal, UUID(proposal["id"]))
    assert proposal_row is not None
    character_key_by_id = {
        value["character_id"]: key
        for key, value in proposal_row.extraction_context_json["character_catalog"].items()
    }
    relation_scope = {
        "fact_type": "relationship_state",
        "source_character_key": character_key_by_id[source["id"]],
        "target_character_key": character_key_by_id[target["id"]],
        "directionality": "undirected",
        "relation_kind": "ally",
        "relationship_label": "调查同盟",
        "dimension": "alliance",
        "confidence": 93,
        "details": {},
    }
    proposal = complete_intelligence_proposal(
        session,
        UUID(proposal["id"]),
        items=[
            {
                **relation_scope,
                "event_kind": "formed",
                "subject": "苏晚与陆沉舟",
                "predicate": "结成同盟",
                "object": "共同调查旧电台档案",
                "source_text": "约定共同调查旧电台档案",
                "reasoning_summary": "形成稳定协作关系",
            },
            {
                **relation_scope,
                "event_kind": "reinforced",
                "subject": "苏晚与陆沉舟",
                "predicate": "加深互信",
                "object": "共同保护原始母带",
                "source_text": "约定共同保护原始母带",
                "reasoning_summary": "同一关系在本章继续发展",
            },
        ],
        actual_model_id=TEST_MODEL_ID,
        provider_profile=TEST_PROVIDER_ID,
    )

    committed = commit_intelligence_items(
        session,
        UUID(proposal["id"]),
        accepted_item_ids=[UUID(item["id"]) for item in proposal["items"]],
    )

    assert committed["relationship_sync"] == {"created": 1, "updated": 0, "skipped": 0}
    assert session.scalar(
        select(func.count(CharacterRelationship.id)).where(
            CharacterRelationship.novel_id == novel_id
        )
    ) == 1
    assert session.scalar(
        select(func.count(StoryFact.id)).where(StoryFact.novel_id == novel_id)
    ) == 2


def test_sync_progress_revalidates_relationship_instances_against_the_timeline(
    session: Session,
) -> None:
    novel_payload = create_novel(session, "pytest-同步进展时间线重验")
    novel_id = UUID(novel_payload["id"])
    document_id = UUID(novel_payload["tree"][0]["documents"][0]["id"])
    source = create_novel_character(
        session,
        novel_id,
        role_type="main",
        name="苏晚",
        description="旧电台修复师",
        details={},
    )
    target = create_novel_character(
        session,
        novel_id,
        role_type="supporting",
        name="陆沉舟",
        description="灯塔维护工程师",
        details={},
    )
    saved = save_draft(
        session,
        document_id,
        expected_draft_version=1,
        content_markdown="苏晚与陆沉舟约定共同调查旧电台档案。",
    )
    revision = create_checkpoint(
        session,
        document_id,
        expected_draft_version=saved["draft_version"],
    )["revision"]
    proposal = start_intelligence_proposal(
        session,
        document_id,
        revision_id=UUID(revision["id"]),
    )
    proposal_row = session.get(IntelligenceProposal, UUID(proposal["id"]))
    assert proposal_row is not None
    character_key_by_id = {
        value["character_id"]: key
        for key, value in proposal_row.extraction_context_json["character_catalog"].items()
    }
    proposal = complete_intelligence_proposal(
        session,
        UUID(proposal["id"]),
        items=[
            {
                "fact_type": "relationship_state",
                "source_character_key": character_key_by_id[source["id"]],
                "target_character_key": character_key_by_id[target["id"]],
                "directionality": "undirected",
                "relation_kind": "ally",
                "relationship_label": "调查同盟",
                "dimension": "alliance",
                "event_kind": "formed",
                "subject": "苏晚与陆沉舟",
                "predicate": "结成同盟",
                "object": "共同调查旧电台档案",
                "source_text": "约定共同调查旧电台档案",
                "reasoning_summary": "形成稳定协作关系",
                "confidence": 93,
                "details": {},
            }
        ],
        actual_model_id=TEST_MODEL_ID,
        provider_profile=TEST_PROVIDER_ID,
    )
    novel = session.get(Novel, novel_id)
    primary = session.scalar(
        select(StoryTimeline).where(
            StoryTimeline.novel_id == novel_id,
            StoryTimeline.is_primary.is_(True),
        )
    )
    assert novel is not None and primary is not None
    branch = fork_timeline(
        session,
        novel_id,
        primary.id,
        expected_story_ledger_version=novel.story_ledger_version,
        expected_source_timeline_version=primary.version,
        timeline_key="branch-sync-audit",
        name="同步审计分支",
        fork_story_sequence=2,
    )
    session.commit()
    proposal_item = session.get(
        IntelligenceProposalItem,
        UUID(proposal["items"][0]["id"]),
    )
    assert proposal_item is not None
    tampered_payload = dict(proposal_item.suggested_payload)
    tampered_entity = dict(tampered_payload["entity"])
    tampered_entity["timeline_id"] = branch["timeline"]["id"]
    tampered_payload["entity"] = tampered_entity
    proposal_item.suggested_payload = tampered_payload
    session.flush()
    ledger_before_commit = session.get(Novel, novel_id).story_ledger_version

    with pytest.raises(ValidationError, match="人物实例或时间线已失效"):
        commit_intelligence_items(
            session,
            UUID(proposal["id"]),
            accepted_item_ids=[UUID(proposal["items"][0]["id"])],
            expected_story_ledger_version=ledger_before_commit,
            operation_key="invalid-relationship-commit",
        )
    session.rollback()

    assert session.scalar(
        select(func.count(CharacterRelationship.id)).where(
            CharacterRelationship.novel_id == novel_id
        )
    ) == 0
    assert session.scalar(
        select(func.count(StoryFact.id)).where(StoryFact.novel_id == novel_id)
    ) == 0
    assert session.scalar(
        select(func.count(IntelligenceCommitBatch.id)).where(
            IntelligenceCommitBatch.proposal_id == UUID(proposal["id"])
        )
    ) == 0
    assert session.get(Novel, novel_id).story_ledger_version == ledger_before_commit


def test_sync_progress_retries_a_stale_running_proposal(
    session: Session,
) -> None:
    novel = create_novel(session, "pytest-同步进展超时恢复")
    document_id = UUID(novel["tree"][0]["documents"][0]["id"])
    saved = save_draft(
        session,
        document_id,
        expected_draft_version=1,
        content_markdown="苏晚在旧电台核对母带编号。",
    )
    revision = create_checkpoint(
        session,
        document_id,
        expected_draft_version=saved["draft_version"],
    )["revision"]
    first = start_intelligence_proposal(
        session,
        document_id,
        revision_id=UUID(revision["id"]),
    )
    first_row = session.get(IntelligenceProposal, UUID(first["id"]))
    assert first_row is not None
    first_row.created_at = datetime.now(timezone.utc) - timedelta(hours=2)
    session.commit()

    retried = start_intelligence_proposal(
        session,
        document_id,
        revision_id=UUID(revision["id"]),
    )

    assert retried["id"] != first["id"]
    assert retried["attempt"] == 2
    assert retried["state"] == "running"
    assert retried["should_execute"] is True
    assert session.get(IntelligenceProposal, UUID(first["id"])).state == "failed"

def test_explicit_merge_inherits_one_parent_and_event_links_do_not_copy_facts(
    session: Session,
) -> None:
    novel_payload = create_novel(session, "pytest-显式汇合与因果边")
    novel_id = UUID(novel_payload["id"])
    create_novel_character(
        session,
        novel_id,
        role_type="main",
        name="沈青禾",
        description="用于验证汇合人物实例",
        details={},
    )
    novel = session.get(Novel, novel_id)
    primary = session.scalar(
        select(StoryTimeline).where(
            StoryTimeline.novel_id == novel_id,
            StoryTimeline.is_primary.is_(True),
        )
    )
    assert novel is not None and primary is not None
    branch = fork_timeline(
        session,
        novel_id,
        primary.id,
        expected_story_ledger_version=novel.story_ledger_version,
        expected_source_timeline_version=primary.version,
        timeline_key="branch-a",
        name="A 分支",
        fork_story_sequence=3,
    )
    merge = create_merge_timeline(
        session,
        novel_id,
        primary_timeline_id=primary.id,
        input_timeline_ids=[primary.id, UUID(branch["timeline"]["id"])],
        expected_story_ledger_version=branch["story_ledger_version"],
        expected_timeline_versions={
            primary.id: primary.version,
            UUID(branch["timeline"]["id"]): branch["timeline"]["version"],
        },
        timeline_key="merge-a",
        name="作者裁决后的汇合线",
        merge_story_sequence=8,
    )
    assert merge["timeline"]["timeline_kind"] == "merge"
    assert merge["timeline"]["parent_timeline_id"] == str(primary.id)
    assert merge["copied_fact_count"] == 0
    assert [item["source_timeline_id"] for item in merge["merge_references"]] == [
        branch["timeline"]["id"]
    ]

    earlier = StoryFact(
        id=UUID("00000000-0000-0000-0000-00000000f101"),
        novel_id=novel_id,
        schema_version="story-fact/2",
        timeline_id=primary.id,
        fact_type="general_fact",
        subject="车票",
        predicate="颜色",
        object_text="蓝色",
        details={"schema_version": "general-fact/1", "value": "蓝色"},
        dimension="appearance",
        event_kind="confirmed",
        story_sequence=1,
        visibility_json={"scope": "author"},
        event_fingerprint="a" * 64,
        status="active",
    )
    correction = StoryFact(
        id=UUID("00000000-0000-0000-0000-00000000f102"),
        novel_id=novel_id,
        schema_version="story-fact/2",
        timeline_id=primary.id,
        fact_type="general_fact",
        subject="车票",
        predicate="颜色",
        object_text="绿色",
        details={"schema_version": "general-fact/1", "value": "绿色"},
        dimension="appearance",
        event_kind="correction",
        story_sequence=2,
        visibility_json={"scope": "author"},
        event_fingerprint="b" * 64,
        status="active",
    )
    session.add_all((earlier, correction))
    session.flush()
    linked = create_story_event_link(
        session,
        novel_id,
        source_fact_id=correction.id,
        target_fact_id=earlier.id,
        link_type=StoryEventLinkType.SUPERSEDES,
        expected_story_ledger_version=merge["story_ledger_version"],
        details={"reason": "author_correction"},
    )
    assert linked["link_type"] == "supersedes"
    assert len(list_story_event_link_payloads(session, novel_id)) == 1
    projection = get_story_projection_payload(session, novel_id, timeline_id=primary.id)
    assert [item["object_text"] for item in projection["current_facts"]] == ["绿色"]


def test_relationship_graph_status_matches_snapshot_and_prevents_parallel_force_new(
    session: Session,
) -> None:
    novel = create_novel(session, "pytest-关系网状态契约")
    novel_id = UUID(novel["id"])
    source = create_novel_character(
        session,
        novel_id,
        role_type="main",
        name="苏晚",
        description="与陆沉舟长期共同调查旧电台档案。",
        details={"gender": "女"},
    )
    create_novel_character(
        session,
        novel_id,
        role_type="supporting",
        name="陆沉舟",
        description="与苏晚长期共同调查旧电台档案。",
        details={"gender": "男"},
    )
    snapshot = build_relationship_graph_snapshot(session, novel_id)
    assert snapshot["chapter_index"][0]["title"] == "第1章"
    assert snapshot["chapter_index"][0]["position"] == 1
    keys = {item["name"]: item["entity_key"] for item in snapshot["characters"]}
    first = start_creative_generation(
        session,
        scope_type="novel",
        scope_id=novel_id,
        kind="relationship_graph",
        input_snapshot=snapshot,
        novel_id=novel_id,
    )
    duplicate = start_creative_generation(
        session,
        scope_type="novel",
        scope_id=novel_id,
        kind="relationship_graph",
        input_snapshot=snapshot,
        novel_id=novel_id,
        force_new=True,
    )
    running_status = get_relationship_auto_sync_status(session, novel_id)

    assert duplicate["id"] == first["id"]
    assert duplicate["should_execute"] is False
    assert running_status["state"] == "running"
    assert running_status["job"]["id"] == first["id"]

    completed = complete_creative_generation(
        session,
        UUID(first["id"]),
        output_json={
            "complete_snapshot": True,
            "relationships": [
                {
                    "source_key": keys["苏晚"],
                    "target_key": keys["陆沉舟"],
                    "directionality": "undirected",
                    "relation_kind": "ally",
                    "label": "调查同盟",
                    "description": "两人长期共同调查旧电台档案。",
                    "confidence": 94,
                    "evidence": ["角色设定：苏晚与陆沉舟长期共同调查旧电台档案。"],
                }
            ],
        },
    )
    ledger_before_apply = get_novel(session, novel_id)["story_ledger_version"]
    applied = apply_relationship_graph_generation(
        session,
        novel_id,
        UUID(completed["id"]),
    )

    assert applied["status"]["state"] == "ready"
    assert applied["status"]["stale"] is False
    assert applied["status"]["job"]["id"] == first["id"]
    assert len(applied["relationships"]) == 1
    assert applied["changed"] is True
    assert applied["story_ledger_version"] == ledger_before_apply + 1

    replayed_apply = apply_relationship_graph_generation(
        session,
        novel_id,
        UUID(completed["id"]),
    )
    assert replayed_apply["changed"] is False
    assert replayed_apply["story_ledger_version"] == applied["story_ledger_version"]

    updated = update_novel_character(
        session,
        novel_id,
        UUID(source["id"]),
        expected_version=source["version"],
        role_type="main",
        name="苏晚",
        description="与陆沉舟共同调查旧电台档案，并开始互相隐瞒线索。",
        details={"gender": "女"},
    )
    assert updated["version"] == source["version"] + 1
    stale_status = get_relationship_auto_sync_status(session, novel_id)
    assert stale_status["state"] == "never"
    assert stale_status["stale"] is True
    assert stale_status["last_synced_at"] is not None


def test_relationship_graph_is_versioned_atomic_and_layout_persistent(
    session: Session,
) -> None:
    novel = create_novel(session, "pytest-关系网闭环")
    novel_id = UUID(novel["id"])
    characters = [
        create_novel_character(
            session,
            novel_id,
            role_type="main" if index == 0 else "supporting",
            name=name,
            description="",
            details={},
        )
        for index, name in enumerate(("苏晚", "陆沉舟", "周柚"))
    ]
    character_ids = [UUID(character["id"]) for character in characters]

    family = create_character_relationship(
        session,
        novel_id,
        source_character_id=character_ids[1],
        target_character_id=character_ids[0],
        directionality="undirected",
        relation_kind="family",
        label="姐弟",
    )
    assert family["source_character_id"] == min(
        (str(character_ids[0]), str(character_ids[1]))
    )
    assert family["current_revision_id"] is not None

    with pytest.raises(ValidationError, match="已经存在"):
        create_character_relationship(
            session,
            novel_id,
            source_character_id=character_ids[0],
            target_character_id=character_ids[1],
            directionality="undirected",
            relation_kind="family",
            label="  姐弟  ",
        )
    session.rollback()

    mentor = create_character_relationship(
        session,
        novel_id,
        source_character_id=character_ids[0],
        target_character_id=character_ids[1],
        directionality="directed",
        relation_kind="mentor",
        label="指导",
    )
    result = batch_character_relationships(
        session,
        novel_id,
        operations=[
            {
                "action": "update",
                "relationship_id": UUID(family["id"]),
                "expected_version": family["version"],
                "source_character_id": character_ids[0],
                "target_character_id": character_ids[1],
                "directionality": "undirected",
                "relation_kind": "family",
                "label": "姐弟",
                "description": "共同守护旧电台。",
            },
            {
                "action": "create",
                "client_id": "new-ally",
                "source_character_id": character_ids[1],
                "target_character_id": character_ids[2],
                "directionality": "undirected",
                "relation_kind": "ally",
                "label": "盟友",
                "description": "",
            },
        ],
    )
    assert len(result["relationships"]) == 3
    assert len(
        list_character_relationship_history(session, novel_id, UUID(family["id"]))
    ) == 2

    delete_character_relationship(
        session,
        novel_id,
        UUID(mentor["id"]),
        expected_version=mentor["version"],
    )
    assert len(list_character_relationships(session, novel_id)) == 2
    archived = next(
        relationship
        for relationship in list_character_relationships(
            session, novel_id, include_archived=True
        )
        if relationship["id"] == mentor["id"]
    )
    restored = restore_character_relationship(
        session,
        novel_id,
        UUID(mentor["id"]),
        expected_version=archived["version"],
    )
    assert restored["archived_at"] is None

    empty_view = get_relationship_graph_view(session, novel_id)
    assert empty_view["version"] == 0
    saved_view = save_relationship_graph_view(
        session,
        novel_id,
        expected_version=0,
        name="默认视图",
        layout_algorithm="force_atlas_2",
        random_seed="pytest-relationship-layout",
        zoom=0.9,
        pan_x=12,
        pan_y=-8,
        positions=[
            {
                "character_id": character_id,
                "x": index * 120.0,
                "y": index * -40.0,
                "pinned": False,
            }
            for index, character_id in enumerate(character_ids)
        ],
    )
    assert saved_view["version"] == 1
    assert len(saved_view["positions"]) == 3
    with pytest.raises(EntityConflictError):
        save_relationship_graph_view(
            session,
            novel_id,
            expected_version=0,
            name="默认视图",
            layout_algorithm="force_atlas_2",
            random_seed="stale-client",
            zoom=1,
            pan_x=0,
            pan_y=0,
            positions=[],
        )
    session.rollback()


def test_draft_cas_checkpoint_search_and_restore(session: Session) -> None:
    novel = create_novel(session, "pytest-CAS小说")
    novel_id = UUID(novel["id"])
    document_id = UUID(novel["tree"][0]["documents"][0]["id"])
    assert novel["tree"][0]["documents"][0]["version_state"] == "empty_draft"

    first_save = save_draft(
        session,
        document_id,
        expected_draft_version=1,
        content_markdown="# 第一章\n\n雨夜里，江述发现一封信。",
    )
    assert first_save["draft_version"] == 2
    assert first_save["version_state"] == "saved_working_copy"

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
    assert checkpoint["document"]["version_state"] == "checkpointed"

    second_save = save_draft(
        session,
        document_id,
        expected_draft_version=3,
        content_markdown="# 第一章\n\n江述烧掉了那封信。",
    )
    assert second_save["draft_version"] == 4
    assert second_save["version_state"] == "saved_working_copy"
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
    assert restored["document"]["version_state"] == "checkpointed"

    context = get_novel_context(session, novel_id, document_id=document_id)
    assert context["novel"]["title"] == "pytest-CAS小说"
    assert context["documents"][-1]["base_revision_id"] == restored["revision"]["id"]
    assert context["retrieval"].startswith("deterministic/context-v3")


def test_create_novel_is_ready_to_write(session: Session) -> None:
    novel = create_novel(session, "pytest-开箱即写")
    document_id = UUID(novel["tree"][0]["documents"][0]["id"])
    document = get_document(session, document_id)

    assert novel["tree"][0]["title"] == ""
    assert document["title"] == ""
    assert document["draft_version"] == 1
    assert document["revisions"][0]["revision_number"] == 1
    assert session.scalar(select(Novel).where(Novel.id == UUID(novel["id"]))) is not None
    assert session.scalar(select(Document).where(Document.id == document_id)) is not None


def test_chapter_creation_without_valid_volume_is_structured_and_zero_write(
    session: Session,
) -> None:
    created = _create_long_novel_via_wizard(
        session,
        draft_key="pytest-无卷零写入建书",
        title="pytest-无卷零写入",
    )
    novel_id = UUID(created["novel"]["id"])
    other = _create_long_novel_via_wizard(
        session,
        draft_key="pytest-无卷零写入他书",
        title="pytest-无卷零写入他书",
    )
    other_id = UUID(other["novel"]["id"])
    other_volume = create_volume(session, other_id, "")

    def counts() -> tuple[int, int, int, int]:
        return (
            int(session.scalar(select(func.count(Document.id)).where(Document.novel_id == novel_id)) or 0),
            int(
                session.scalar(
                    select(func.count(DocumentRevision.id))
                    .join(Document, Document.id == DocumentRevision.document_id)
                    .where(Document.novel_id == novel_id)
                )
                or 0
            ),
            int(
                session.scalar(
                    select(func.count(DocumentWorkingCopy.document_id))
                    .join(Document, Document.id == DocumentWorkingCopy.document_id)
                    .where(Document.novel_id == novel_id)
                )
                or 0
            ),
            int(
                session.scalar(
                    select(func.count(ChapterCreationDraft.id)).where(
                        ChapterCreationDraft.novel_id == novel_id
                    )
                )
                or 0
            ),
        )

    before = counts()
    with pytest.raises(VolumeChapterContractError) as missing:
        create_document(session, novel_id, "", volume_id=None)
    assert missing.value.code == "chapter_volume_required"
    session.rollback()

    with pytest.raises(VolumeChapterContractError) as missing_draft:
        get_or_create_chapter_creation_draft(
            session,
            novel_id=novel_id,
            volume_id=None,
            draft_key="pytest-无卷零写入-草稿",
        )
    assert missing_draft.value.code == "chapter_volume_required"
    session.rollback()

    with pytest.raises(VolumeChapterContractError) as cross_book:
        create_document(
            session,
            novel_id,
            "",
            volume_id=UUID(other_volume["id"]),
        )
    assert cross_book.value.code == "chapter_volume_invalid"
    session.rollback()
    assert counts() == before


def test_stale_chapter_draft_rebinds_without_losing_author_input(
    session: Session,
) -> None:
    created = _create_long_novel_via_wizard(
        session,
        draft_key="pytest-草稿失效恢复建书",
        title="pytest-草稿失效恢复",
    )
    novel_id = UUID(created["novel"]["id"])
    old_volume = create_volume(session, novel_id, "第 8 卷：旧卷")
    draft = get_or_create_chapter_creation_draft(
        session,
        novel_id=novel_id,
        volume_id=UUID(old_volume["id"]),
        draft_key="pytest-草稿失效恢复-章节",
    )
    draft = update_chapter_creation_draft(
        session,
        UUID(draft["id"]),
        expected_version=draft["version"],
        step=6,
        title="第十二章 · 海边来信",
        expectation_text="保留作者已填期待",
        outline_text="保留作者已填章纲",
        data_patch={"storyline_ids": [], "marker": "keep-me"},
    )
    delete_volume(
        session,
        novel_id,
        UUID(old_volume["id"]),
        expected_version=old_volume["version"],
    )

    with pytest.raises(VolumeChapterContractError) as stale:
        complete_chapter_creation_draft(
            session,
            UUID(draft["id"]),
            expected_version=draft["version"],
        )
    assert stale.value.code == "chapter_draft_volume_stale"
    assert stale.value.status_code == 409
    assert stale.value.current["id"] == draft["id"]
    assert stale.value.current["data"]["marker"] == "keep-me"
    session.rollback()
    assert session.scalar(
        select(func.count(Document.id)).where(Document.novel_id == novel_id)
    ) == 0

    new_volume = create_volume(session, novel_id, "")
    rebound = get_or_create_chapter_creation_draft(
        session,
        novel_id=novel_id,
        volume_id=UUID(new_volume["id"]),
        draft_key="pytest-草稿失效恢复-章节",
    )
    assert rebound["id"] == draft["id"]
    assert rebound["version"] == draft["version"] + 1
    assert rebound["title"] == "海边来信"
    assert rebound["expectation_text"] == "保留作者已填期待"
    assert rebound["outline_text"] == "保留作者已填章纲"
    assert rebound["data"]["marker"] == "keep-me"
    assert rebound["recovery"] == {
        "kind": "volume_rebound",
        "from_volume_id": None,
        "to_volume_id": str(new_volume["id"]),
    }
    completed = complete_chapter_creation_draft(
        session,
        UUID(rebound["id"]),
        expected_version=rebound["version"],
    )
    assert completed["document"]["title"] == "海边来信"
    assert completed["document"]["volume_id"] == new_volume["id"]


def test_concurrent_chapter_writes_converge_draft_key_and_allocate_unique_positions(
    session: Session,
) -> None:
    created = _create_long_novel_via_wizard(
        session,
        draft_key="pytest-并发卷章建书",
        title="pytest-并发卷章",
    )
    novel_id = UUID(created["novel"]["id"])
    volume = create_volume(session, novel_id, "")
    volume_id = UUID(volume["id"])
    worker_engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    draft_barrier = Barrier(2)

    def prepare_same_draft() -> dict[str, object]:
        with Session(worker_engine, expire_on_commit=False) as worker_session:
            draft_barrier.wait(timeout=5)
            return get_or_create_chapter_creation_draft(
                worker_session,
                novel_id=novel_id,
                volume_id=volume_id,
                draft_key="pytest-并发卷章-同-key",
            )

    chapter_barrier = Barrier(2)

    def create_chapter() -> dict[str, object]:
        with Session(worker_engine, expire_on_commit=False) as worker_session:
            chapter_barrier.wait(timeout=5)
            return create_document(
                worker_session,
                novel_id,
                "",
                volume_id=volume_id,
            )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            drafts = list(executor.map(lambda _: prepare_same_draft(), range(2)))
        with ThreadPoolExecutor(max_workers=2) as executor:
            chapters = list(executor.map(lambda _: create_chapter(), range(2)))
    finally:
        worker_engine.dispose()

    assert len({str(item["id"]) for item in drafts}) == 1
    assert len({str(item["id"]) for item in chapters}) == 2
    session.expire_all()
    positions = session.scalars(
        select(Document.position)
        .where(Document.novel_id == novel_id, Document.kind == "chapter")
        .order_by(Document.position)
    ).all()
    assert positions == [1000, 2000]
    assert session.scalar(
        select(func.count(ChapterCreationDraft.id)).where(
            ChapterCreationDraft.novel_id == novel_id
        )
    ) == 1


def test_chapter_name_commit_survives_post_commit_index_refresh_failure(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel = create_novel(session, "pytest-章名刷新失败隔离")
    novel_id = UUID(novel["id"])
    document_id = UUID(novel["tree"][0]["documents"][0]["id"])

    def fail_refresh(*_args: object, **_kwargs: object) -> bool:
        raise RuntimeError("synthetic post-commit refresh failure")

    monkeypatch.setattr(
        "backend.embedding.indexing.request_active_novel_refresh",
        fail_refresh,
    )

    updated = update_document_metadata(
        session,
        novel_id,
        document_id,
        expected_version=1,
        title="第十二章 · 海边来信",
    )

    assert updated["title"] == "海边来信"
    session.expire_all()
    stored = session.get(Document, document_id)
    assert stored is not None
    assert stored.title == "海边来信"


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

    with pytest.raises(VolumeChapterContractError) as cross_book_volume:
        create_document(
            session,
            first_id,
            "不应跨书创建",
            volume_id=second_volume_id,
        )
    assert cross_book_volume.value.code == "chapter_volume_invalid"
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
    create_novel_character(
        session,
        novel_id,
        role_type="main",
        name="江述",
        description="核查雨夜来信来源的人",
        details={},
    )

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
    assert job["generation_context_snapshot"]["schema_version"] == 4
    assert "context_v3" not in job["generation_context_snapshot"]
    assert "previous_context" not in job["generation_context_snapshot"]
    completed = complete_chapter_generation(
        session,
        UUID(job["id"]),
        content_markdown=_long_chapter(
            "雨水敲着窗。江述翻过信封，邮戳日期写着明天。",
            paragraphs=28,
        ),
        model_profile_fingerprint="pytest-model",
        actual_model_id=TEST_MODEL_ID,
        provider_profile=TEST_PROVIDER_ID,
    )
    candidate = completed["candidate"]

    assert candidate["state"] == "ready"
    assert completed["generation_context_snapshot"] == job["generation_context_snapshot"]
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
                "fact_type": "general_fact",
                "subject": "信封邮戳",
                "predicate": "日期",
                "object": "明天",
                "source_text": "邮戳日期写着明天",
                "reasoning_summary": "明确的新时间异常",
                "confidence": 98,
            },
            {
                "fact_type": "general_fact",
                "subject": "寄信人",
                "predicate": "身份",
                "object": "尚未揭示",
                "source_text": "江述翻过信封",
                "reasoning_summary": "可以继续追查",
                "confidence": 61,
            },
        ],
        actual_model_id=TEST_MODEL_ID,
        provider_profile=TEST_PROVIDER_ID,
    )
    assert _story_facts(session, novel_id) == []

    committed = commit_intelligence_items(
        session,
        UUID(proposal["id"]),
        accepted_item_ids=[UUID(proposal["items"][0]["id"])],
    )
    assert committed["state"] == "partially_accepted"
    facts = _story_facts(session, novel_id)
    assert len(facts) == 1
    assert facts[0]["subject"] == "信封邮戳"
    assert facts[0]["source_revision_id"] == adopted["revision"]["id"]


def test_intelligence_no_changes_keeps_a_named_character_out_of_the_ledger(
    session: Session,
) -> None:
    novel = create_novel(session, "pytest-情报无变化")
    novel_id = UUID(novel["id"])
    document_id = UUID(novel["tree"][0]["documents"][0]["id"])
    create_novel_character(
        session,
        novel_id,
        role_type="main",
        name="沈砚",
        description="声音修复师",
        details={},
    )
    saved = save_draft(
        session,
        document_id,
        expected_draft_version=1,
        content_markdown="沈砚核对完旧磁带编号，把记录本合上。",
    )
    revision = create_checkpoint(
        session,
        document_id,
        expected_draft_version=saved["draft_version"],
    )["revision"]
    proposal = start_intelligence_proposal(
        session,
        document_id,
        revision_id=UUID(revision["id"]),
    )
    ledger_before = session.get(Novel, novel_id).story_ledger_version

    completed = complete_intelligence_proposal(
        session,
        UUID(proposal["id"]),
        items=[],
        actual_model_id=TEST_MODEL_ID,
        provider_profile=TEST_PROVIDER_ID,
    )

    assert completed["state"] == "ready"
    assert completed["items"] == []
    assert _story_facts(session, novel_id) == []
    assert session.get(Novel, novel_id).story_ledger_version == ledger_before


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
                "fact_type": "general_fact",
                "subject": "车票",
                "predicate": "颜色",
                "object": "蓝色",
                "source_text": "蓝色车票",
                "reasoning_summary": "版本 A 的专属事实",
                "confidence": 99,
            }
        ],
        actual_model_id=TEST_MODEL_ID,
        provider_profile=TEST_PROVIDER_ID,
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
    ledger_before_checkpoint_b = session.get(Novel, novel_id).story_ledger_version
    checkpoint_b = create_checkpoint(
        session, document_id, expected_draft_version=saved_b["draft_version"]
    )
    revision_b = checkpoint_b["revision"]
    assert checkpoint_b["reconciliation"]["changed"] is True
    assert checkpoint_b["story_ledger_version"] == ledger_before_checkpoint_b + 1
    proposal_b = start_intelligence_proposal(
        session, document_id, revision_id=UUID(revision_b["id"])
    )
    proposal_b = complete_intelligence_proposal(
        session,
        UUID(proposal_b["id"]),
        items=[
            {
                "fact_type": "general_fact",
                "subject": "怀表",
                "predicate": "位置",
                "object": "旧桥下",
                "source_text": "银色怀表埋在旧桥下",
                "reasoning_summary": "版本 B 的专属事实",
                "confidence": 99,
            }
        ],
        actual_model_id=TEST_MODEL_ID,
        provider_profile=TEST_PROVIDER_ID,
    )
    commit_intelligence_items(
        session,
        UUID(proposal_b["id"]),
        accepted_item_ids=[UUID(proposal_b["items"][0]["id"])],
    )

    before_restore = {
        fact["subject"]: fact["status"] for fact in _story_facts(session, novel_id)
    }
    assert before_restore == {"怀表": "active", "车票": "active"}
    before_binding_state = {
        fact.subject: binding.validity_state
        for binding, fact in session.execute(
            select(DerivedSourceBinding, StoryFact)
            .join(StoryFact, StoryFact.id == DerivedSourceBinding.derived_entity_id)
            .where(StoryFact.novel_id == novel_id)
        ).all()
    }
    assert before_binding_state == {
        "怀表": "current",
        "车票": "source_superseded",
    }

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

    ledger_before_restore = session.get(Novel, novel_id).story_ledger_version
    restored = restore_revision(
        session,
        document_id,
        UUID(revision_a["id"]),
        expected_draft_version=preview["expected_draft_version"],
        expected_fact_plan_hash=preview["fact_plan_hash"],
    )
    assert restored["revision"]["restored_from_revision_id"] == revision_a["id"]
    assert restored["reconciliation"]["changed"] is True
    assert restored["story_ledger_version"] == ledger_before_restore + 1
    after_restore = {
        fact["subject"]: fact["status"] for fact in _story_facts(session, novel_id)
    }
    assert after_restore == {"怀表": "active", "车票": "active"}
    after_binding_state = {
        fact.subject: binding.validity_state
        for binding, fact in session.execute(
            select(DerivedSourceBinding, StoryFact)
            .join(StoryFact, StoryFact.id == DerivedSourceBinding.derived_entity_id)
            .where(StoryFact.novel_id == novel_id)
        ).all()
    }
    assert after_binding_state == {
        "怀表": "source_superseded",
        "车票": "source_restored",
    }
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
    ledger_before_replay = session.get(Novel, novel_id).story_ledger_version
    replayed_restore = restore_revision(
        session,
        document_id,
        UUID(revision_a["id"]),
        expected_draft_version=second_preview["expected_draft_version"],
        expected_fact_plan_hash=second_preview["fact_plan_hash"],
    )
    assert replayed_restore["reconciliation"]["changed"] is False
    assert session.get(Novel, novel_id).story_ledger_version == ledger_before_replay
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
        actual_model_id=TEST_MODEL_ID,
        provider_profile=TEST_PROVIDER_ID,
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


def test_six_step_creation_accepts_a_text_only_cover(session: Session) -> None:
    completed = _create_long_novel_via_wizard(
        session,
        draft_key="pytest-文字封面建书",
        title="pytest-文字封面成品",
        cover_mode="text",
        cover_image_data="",
    )

    novel = completed["novel"]
    assert novel["cover_mode"] == "text"
    assert novel["cover_image_data"] == ""


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
            {
                "name": "林知夏",
                "role_type": "main",
                "description": "重返高三",
                "details": {
                    "gender": "女",
                    "age": "18岁左右",
                    "identity": "重返高三的学生",
                    "personality": "谨慎但敢于补救遗憾",
                    "core_goal": "改变家人的命运",
                },
            },
            {"name": "顾明川", "role_type": "main", "description": "理科尖子生"},
        ],
        plot_text="两人从互相试探到共同改变家庭命运。",
        highlight_text="重返一九八八，把错过的青春重新写一遍。",
    )
    ledger_before = session.get(Novel, novel_id).story_ledger_version
    first = complete_outline_draft(
        session,
        novel_id,
        expected_version=outline["version"],
    )
    assert first["novel"]["outline_target_chapters"] == 10
    assert first["novel"]["story_ledger_version"] == ledger_before + 1
    assert [item["name"] for item in first["characters"]] == ["林知夏", "顾明川"]
    lead_instance = session.scalar(
        select(CharacterInstance).where(
            CharacterInstance.novel_id == novel_id,
            CharacterInstance.character_id == UUID(first["characters"][0]["id"]),
        )
    )
    assert lead_instance is not None
    lead_profile = session.get(
        CharacterInstanceRevision, lead_instance.current_revision_id
    )
    assert lead_profile is not None
    assert lead_profile.profile_schema_version == 2
    assert lead_profile.profile_json["age_at_story_start_note"] == "18岁左右"
    assert lead_profile.profile_json["public_identity"] == "重返高三的学生"
    assert lead_profile.profile_json["goals"] == ["改变家人的命运"]

    formal_lead = first["characters"][0]
    update_novel_character(
        session,
        novel_id,
        UUID(formal_lead["id"]),
        expected_version=formal_lead["version"],
        role_type="main",
        name="林知夏",
        description="重返高三",
        details={
            "gender": "其他",
            "identity": "学生",
            "personality": "面对压力时会先保护同伴，却容易独自承担风险。",
            "secret": "不得被大纲表单删除",
        },
    )

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
            {
                "character_id": first["characters"][1]["id"],
                "name": "顾明川",
                "role_type": "main",
                "description": "承担家庭压力",
            },
            {
                "character_id": formal_lead["id"],
                "name": "林知夏",
                "role_type": "main",
                "description": "主动修正遗憾",
                "details": {"gender": "女"},
            },
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
    rematerialized_lead = next(item for item in characters if item["name"] == "林知夏")
    assert rematerialized_lead["details"]["gender"] == "其他"
    assert rematerialized_lead["details"]["secret"] == "不得被大纲表单删除"
    assert rematerialized_lead["details"]["personality"].startswith("面对压力")
    assert all(item.get("character_id") for item in second["outline"]["characters"])
    main_line = next(
        item for item in list_storylines(session, novel_id) if item["storyline_type"] == "main"
    )
    assert main_line["description"] == second["novel"]["main_plot"]


def test_outline_completion_requires_explicit_same_name_character_link(
    session: Session,
) -> None:
    created = _create_long_novel_via_wizard(
        session,
        draft_key="pytest-大纲同名关联",
        title="pytest-大纲同名关联",
    )
    novel_id = UUID(created["novel"]["id"])
    existing = create_novel_character(
        session,
        novel_id,
        role_type="main",
        name="林知夏",
        description="已经存在的正式人物",
        details={},
    )
    outline = get_or_create_outline_draft(session, novel_id)
    outline = update_outline_draft(
        session,
        novel_id,
        expected_version=outline["version"],
        step=5,
        background_text="同名人物冲突测试背景。",
        plot_text="同名人物冲突测试情节。",
        highlight_text="同名人物必须显式关联。",
        characters=[
            {
                "draft_key": "same-name-unlinked",
                "name": "林知夏",
                "role_type": "main",
                "bio": "没有稳定人物 ID 的同名草案",
                "origin": "manual",
            }
        ],
    )

    with pytest.raises(CharacterLinkRequiredError) as captured:
        complete_outline_draft(
            session,
            novel_id,
            expected_version=outline["version"],
        )

    assert captured.value.conflicts == [
        {
            "draft_key": "same-name-unlinked",
            "draft_name": "林知夏",
            "existing_character_id": existing["id"],
            "existing_character_name": "林知夏",
        }
    ]


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
    characters = list_novel_characters(session, novel_id)
    required = {item["name"] for item in characters if item["required_next_chapter"]}
    assert required == set()


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
    first_volume = create_volume(session, first_id, "第一卷")
    second_volume = create_volume(session, second_id, "第一卷")
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
        volume_id=UUID(first_volume["id"]),
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

    with pytest.raises(VolumeChapterContractError, match="已属于其他小说"):
        get_or_create_chapter_creation_draft(
            session,
            novel_id=second_id,
            volume_id=UUID(second_volume["id"]),
            draft_key="pytest-章节甲-第一章",
        )
    session.rollback()
    assert second_role["novel_id"] == str(second_id)


def test_generation_requires_matching_model_evidence_and_acceptance_window(
    session: Session,
) -> None:
    novel = create_novel(session, "pytest-通用模型门槛")
    document_id = UUID(novel["tree"][0]["documents"][0]["id"])
    brief = save_chapter_brief(
        session,
        document_id,
        expected_version=0,
        target_word_count=2500,
        expectation_text="建立冲突",
        outline_text="人物发现关键证据。",
        forbidden_text="",
        role_constraints={},
    )
    first_job = start_chapter_generation(
        session,
        document_id,
        expected_brief_version=brief["version"],
    )
    assert first_job["target_visible_character_count"] == 2125
    assert first_job["minimum_visible_character_count"] == 2125
    assert first_job["maximum_visible_character_count"] == 2875
    assert first_job["requested_visible_character_count"] == 2500
    assert "length_control" not in first_job["generation_context_snapshot"]
    with pytest.raises(ChapterLengthValidationError, match="必须整章重写") as below_error:
        complete_chapter_generation(
            session,
            UUID(first_job["id"]),
            content_markdown="这一章太短。",
            actual_model_id=TEST_MODEL_ID,
            provider_profile=TEST_PROVIDER_ID,
        )
    assert below_error.value.validation_state == "below_target"
    assert below_error.value.minimum_visible_character_count == 2125
    assert below_error.value.maximum_visible_character_count == 2875
    failed = list_chapter_generation_jobs(session, document_id)[0]
    assert failed["state"] == "failed"
    assert failed["validation_state"] == "below_target"
    assert session.scalar(
        select(func.count(CandidateRevision.id)).where(
            CandidateRevision.generation_job_id == UUID(first_job["id"])
        )
    ) == 0
    still_failed = complete_chapter_generation(
        session,
        UUID(first_job["id"]),
        content_markdown=_long_chapter("终态不应被重新完成。"),
        actual_provider_id=TEST_PROVIDER_ID,
        actual_model_id=TEST_MODEL_ID,
    )
    assert still_failed["state"] == "failed"
    assert still_failed["failure_message"] == failed["failure_message"]

    second_job = start_chapter_generation(
        session,
        document_id,
        expected_brief_version=brief["version"],
        force_new=True,
    )
    second_control = second_job["generation_context_snapshot"]["length_control"]
    assert second_control["schema_version"] == "chapter-length-control/1"
    assert second_control["root_job_id"] == first_job["id"]
    assert second_control["previous_job_id"] == first_job["id"]
    assert second_control["retry_round"] == 2
    assert second_control["previous_validation_state"] == "below_target"
    assert second_control["previous_visible_character_count"] == failed["output_visible_character_count"]
    assert second_control["calibrated_drafting_target_visible_character_count"] == 3594
    assert second_job["input_hash"] != first_job["input_hash"]
    with pytest.raises(ChapterLengthValidationError, match="上浮15%") as above_error:
        complete_chapter_generation(
            session,
            UUID(second_job["id"]),
            content_markdown=_long_chapter("人物反复解释线索。", paragraphs=60),
            actual_model_id=TEST_MODEL_ID,
            provider_profile=TEST_PROVIDER_ID,
        )
    assert above_error.value.validation_state == "above_target"
    assert above_error.value.output_visible_character_count > 2875
    above = list_chapter_generation_jobs(session, document_id)[0]
    assert above["validation_state"] == "above_target"

    third_job = start_chapter_generation(
        session,
        document_id,
        expected_brief_version=brief["version"],
        force_new=True,
    )
    third_control = third_job["generation_context_snapshot"]["length_control"]
    assert third_control["previous_job_id"] == second_job["id"]
    assert third_control["root_job_id"] == first_job["id"]
    assert third_control["retry_round"] == 3
    assert third_control["previous_validation_state"] == "above_target"
    assert third_control["previous_visible_character_count"] == above["output_visible_character_count"]
    assert 1381 <= third_control["calibrated_drafting_target_visible_character_count"] <= 2875
    completed = complete_chapter_generation(
        session,
        UUID(third_job["id"]),
        content_markdown=_long_chapter("人物终于找到能够推进调查的关键证据。", paragraphs=40),
        actual_model_id=TEST_MODEL_ID,
        provider_profile=TEST_PROVIDER_ID,
    )
    assert completed["attempt"] == 1
    assert completed["state"] == "ready"
    assert completed["validation_state"] == "meets_target"
    assert 2125 <= completed["output_visible_character_count"] <= 2875
    assert completed["actual_model_id"] == TEST_MODEL_ID
    still_ready = fail_chapter_generation(
        session,
        UUID(third_job["id"]),
        "迟到的失败回调",
    )
    assert still_ready["state"] == "ready"
    assert still_ready["failure_message"] is None


def test_candidate_adoption_recomputes_the_frozen_upper_bound(
    session: Session,
) -> None:
    novel = create_novel(session, "pytest-候选采用长度防线")
    document_id = UUID(novel["tree"][0]["documents"][0]["id"])
    brief = save_chapter_brief(
        session,
        document_id,
        expected_version=0,
        target_word_count=2500,
        expectation_text="完成一次可采用的调查推进",
        outline_text="人物核对证据并做出选择。",
        forbidden_text="",
        role_constraints={},
    )
    job = start_chapter_generation(
        session,
        document_id,
        expected_brief_version=brief["version"],
    )
    completed = complete_chapter_generation(
        session,
        UUID(job["id"]),
        content_markdown=_long_chapter("人物开始核对证据。", paragraphs=40),
        actual_provider_id=TEST_PROVIDER_ID,
        actual_model_id=TEST_MODEL_ID,
    )
    candidate_id = UUID(completed["candidate"]["id"])
    candidate = session.get(CandidateRevision, candidate_id)
    assert candidate is not None
    candidate.content_markdown = _long_chapter("异常超长候选。", paragraphs=60)
    session.flush()
    candidate_count = len("".join(candidate.content_markdown.split()))
    revision_count = session.scalar(
        select(func.count(DocumentRevision.id)).where(
            DocumentRevision.document_id == document_id
        )
    )

    with pytest.raises(ValidationError, match=f"实际{candidate_count}字"):
        adopt_candidate(
            session,
            candidate_id,
            expected_draft_version=completed["candidate"]["base_draft_version"],
        )
    session.rollback()

    assert get_document(session, document_id)["content_markdown"] == ""
    assert session.scalar(
        select(func.count(DocumentRevision.id)).where(
            DocumentRevision.document_id == document_id
        )
    ) == revision_count


def test_stale_chapter_generation_is_failed_before_new_attempt(
    session: Session,
) -> None:
    novel = create_novel(session, "pytest-章节生成超时恢复")
    document_id = UUID(novel["tree"][0]["documents"][0]["id"])
    brief = save_chapter_brief(
        session,
        document_id,
        expected_version=0,
        target_word_count=2500,
        expectation_text="",
        outline_text="人物发现关键证据。",
        forbidden_text="",
        role_constraints={},
    )
    first = start_chapter_generation(
        session,
        document_id,
        expected_brief_version=brief["version"],
    )
    stale = session.get(ChapterGenerationJob, UUID(first["id"]))
    assert stale is not None
    stale.created_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    session.commit()

    second = start_chapter_generation(
        session,
        document_id,
        expected_brief_version=brief["version"],
        force_new=True,
    )
    history = list_chapter_generation_jobs(session, document_id)

    assert second["attempt"] == 2
    assert history[0]["state"] == "running"
    assert history[1]["state"] == "failed"
    assert history[1]["validation_state"] == "runtime_timeout"
    assert "正式正文未修改" in str(history[1]["failure_message"])


def test_fail_path_preserves_known_actual_model_and_terminal_state(
    session: Session,
) -> None:
    draft = get_or_create_novel_creation_draft(session, "pytest-解析失败模型审计")
    job = start_creative_generation(
        session,
        scope_type="novel_creation",
        scope_id=UUID(draft["id"]),
        kind="novel_template",
        input_snapshot={"idea": "海岛旧电台"},
    )

    failed = fail_creative_generation(
        session,
        UUID(job["id"]),
        failure_message="模型身份已核验，但返回内容无法解析",
        actual_provider_id=TEST_PROVIDER_ID,
        actual_model_id=TEST_MODEL_ID,
    )
    assert failed["state"] == "failed"
    assert failed["actual_provider_id"] == TEST_PROVIDER_ID
    assert failed["actual_model_id"] == TEST_MODEL_ID

    replayed = complete_creative_generation(
        session,
        UUID(job["id"]),
        actual_provider_id=TEST_PROVIDER_ID,
        actual_model_id=TEST_MODEL_ID,
        output_json={"template": "迟到的解析结果"},
    )
    assert replayed["state"] == "failed"
    assert replayed["failure_message"] == failed["failure_message"]


def test_concurrent_forced_generation_allocates_unique_attempts(
    session: Session,
) -> None:
    novel = create_novel(session, "pytest-并发生成尝试")
    document_id = UUID(novel["tree"][0]["documents"][0]["id"])
    brief = save_chapter_brief(
        session,
        document_id,
        expected_version=0,
        target_word_count=3000,
        expectation_text="并发生成",
        outline_text="两个请求同时到达。",
        forbidden_text="",
        role_constraints={},
    )
    barrier = Barrier(2)
    worker_engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)

    def create_attempt() -> dict[str, object]:
        with Session(worker_engine, expire_on_commit=False) as worker_session:
            barrier.wait(timeout=5)
            return start_chapter_generation(
                worker_session,
                document_id,
                expected_brief_version=brief["version"],
                force_new=True,
            )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            jobs = list(executor.map(lambda _: create_attempt(), range(2)))
    finally:
        worker_engine.dispose()

    assert sorted(int(job["attempt"]) for job in jobs) == [1, 2]
    assert len({str(job["id"]) for job in jobs}) == 2


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

    text_cover = update_novel_settings(
        session,
        novel_id,
        expected_version=updated["version"],
        genre=updated["genre"],
        subgenre=updated["subgenre"],
        idea=updated["idea"],
        template_name=updated["template_name"],
        template_data=updated["template_data"],
        cover_mode="text",
        cover_image_data="",
    )
    assert text_cover["cover_mode"] == "text"
    assert text_cover["cover_image_data"] == ""

    ledger_before_create = get_novel(session, novel_id)["story_ledger_version"]
    created = create_foreshadow(
        session,
        novel_id,
        title="无源录音",
        content="未接电源的磁带机自行启动。",
        latest_progress="第一章确认录音来自明日。",
    )
    assert created["latest_progress"] == "第一章确认录音来自明日。"
    assert created["story_ledger_version"] == ledger_before_create + 1
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
    assert changed["story_ledger_version"] == ledger_before_create + 2
    unchanged = update_foreshadow(
        session,
        novel_id,
        UUID(created["id"]),
        expected_version=changed["version"],
        title=changed["title"],
        content=changed["content"],
        latest_progress=changed["latest_progress"],
        status=changed["planning_status"],
        progress=changed["planning_progress"],
    )
    assert unchanged["changed"] is False
    assert unchanged["version"] == changed["version"]
    assert unchanged["story_ledger_version"] == changed["story_ledger_version"]
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
    first = start_creative_generation(
        session,
        scope_type="novel_creation",
        scope_id=UUID(draft["id"]),
        kind="novel_naming",
        input_snapshot=snapshot,
    )
    with pytest.raises(ValidationError, match="模型与任务启动模型不一致"):
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
        actual_model_id=TEST_MODEL_ID,
        provider_profile=TEST_PROVIDER_ID,
        output_text='{"titles":["风从一九八八的操场吹来"]}',
        output_json={"titles": ["风从一九八八的操场吹来"]},
    )
    switched = start_creative_generation(
        session,
        scope_type="novel_creation",
        scope_id=UUID(draft["id"]),
        kind="novel_naming",
        input_snapshot=snapshot,
        requested_provider_id="bailian",
        requested_model_id="qwen-next",
        force_new=False,
    )
    switched = complete_creative_generation(
        session,
        UUID(switched["id"]),
        actual_provider_id="bailian",
        actual_model_id="qwen-next",
        output_text='{"titles":["另一模型的书名"]}',
        output_json={"titles": ["另一模型的书名"]},
    )
    history = list_creative_generations(
        session,
        scope_type="novel_creation",
        scope_id=UUID(draft["id"]),
    )
    assert {item["state"] for item in history} == {"failed", "ready"}
    assert len(history) == 3
    assert second["attempt"] == 2
    assert switched["attempt"] == 1
    assert switched["input_hash"] != second["input_hash"]
    assert second["actual_model_id"] == TEST_MODEL_ID
    assert second["actual_provider_id"] == TEST_PROVIDER_ID
    assert second["requested_provider_id"] == TEST_PROVIDER_ID
    assert second["input_snapshot"] == snapshot

    short_target = start_creative_generation(
        session,
        scope_type="novel_creation",
        scope_id=UUID(draft["id"]),
        kind="novel_cover",
        input_snapshot=snapshot,
        target_character_count=2_000,
    )
    long_target = start_creative_generation(
        session,
        scope_type="novel_creation",
        scope_id=UUID(draft["id"]),
        kind="novel_cover",
        input_snapshot=snapshot,
        target_character_count=5_000,
    )
    assert short_target["id"] != long_target["id"]
    assert short_target["input_hash"] != long_target["input_hash"]


def test_export_repeatable_read_never_mixes_concurrent_volume_and_chapter_order(
    session: Session,
) -> None:
    created = _create_long_novel_via_wizard(
        session,
        draft_key="pytest-导出快照建书",
        title="pytest-导出快照",
    )
    novel_id = UUID(created["novel"]["id"])
    volume_one = create_volume(session, novel_id, "甲卷")
    volume_two = create_volume(session, novel_id, "乙卷")
    chapter_one = create_document(
        session,
        novel_id,
        "甲章",
        volume_id=UUID(volume_one["id"]),
    )
    chapter_two = create_document(
        session,
        novel_id,
        "乙章",
        volume_id=UUID(volume_two["id"]),
    )

    export_engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    worker_engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    volumes_loaded = Event()
    reorder_committed = Event()

    def pause_after_volume_snapshot(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if "FROM volumes" not in statement or volumes_loaded.is_set():
            return
        volumes_loaded.set()
        if not reorder_committed.wait(timeout=10):
            raise RuntimeError("concurrent reorder did not finish")

    event.listen(export_engine, "after_cursor_execute", pause_after_volume_snapshot)

    def export_snapshot() -> dict[str, object]:
        with Session(export_engine, expire_on_commit=False) as export_session:
            return build_novel_export(
                export_session,
                novel_id,
                export_format="markdown",
            )

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(export_snapshot)
            assert volumes_loaded.wait(timeout=10)
            with Session(worker_engine, expire_on_commit=False) as worker_session:
                worker_session.scalar(
                    select(Novel).where(Novel.id == novel_id).with_for_update()
                )
                volumes = worker_session.scalars(
                    select(Volume)
                    .where(Volume.novel_id == novel_id)
                    .with_for_update()
                ).all()
                chapters = worker_session.scalars(
                    select(Document)
                    .where(Document.novel_id == novel_id, Document.kind == "chapter")
                    .with_for_update()
                ).all()
                volume_by_id = {item.id: item for item in volumes}
                chapter_by_id = {item.id: item for item in chapters}
                volume_by_id[UUID(volume_one["id"])].position = -1000
                volume_by_id[UUID(volume_two["id"])].position = -2000
                chapter_by_id[UUID(chapter_one["id"])].position = -1000
                chapter_by_id[UUID(chapter_two["id"])].position = -2000
                worker_session.flush()
                volume_by_id[UUID(volume_one["id"])].position = 2000
                volume_by_id[UUID(volume_two["id"])].position = 1000
                chapter_by_id[UUID(chapter_one["id"])].volume_id = UUID(volume_two["id"])
                chapter_by_id[UUID(chapter_one["id"])].position = 1000
                chapter_by_id[UUID(chapter_two["id"])].volume_id = UUID(volume_one["id"])
                chapter_by_id[UUID(chapter_two["id"])].position = 2000
                worker_session.commit()
            reorder_committed.set()
            exported = future.result(timeout=10)
    finally:
        reorder_committed.set()
        event.remove(export_engine, "after_cursor_execute", pause_after_volume_snapshot)
        export_engine.dispose()
        worker_engine.dispose()

    content = str(exported["content"])
    assert content.index("### 第1章 甲章") < content.index("### 第2章 乙章")
    assert [item["title"] for item in exported["metadata"]["chapters"]] == [
        "第1章 甲章",
        "第2章 乙章",
    ]


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
    ungrouped = create_document(
        session,
        novel_id,
        "卷外章",
        volume_id=first_volume_id,
    )
    with pytest.raises(VolumeChapterContractError) as duplicate_mapping:
        reorder_chapters(
            session,
            novel_id,
            ordered_document_ids=[
                first_document_id,
                UUID(second_document["id"]),
                UUID(ungrouped["id"]),
            ],
            volume_by_document={
                str(ungrouped["id"]): first_volume_id,
                f"{{{ungrouped['id']}}}": second_volume_id,
            },
        )
    assert duplicate_mapping.value.code == "chapter_order_inconsistent"
    session.rollback()
    reorder_chapters(
        session,
        novel_id,
        ordered_document_ids=[
            first_document_id,
            UUID(second_document["id"]),
            UUID(ungrouped["id"]),
        ],
        volume_by_document={str(ungrouped["id"]): None},
    )
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
    assert "## 第1卷" in initial_export["content"]
    assert "## 第2卷" in initial_export["content"]
    assert "## 未分卷" in initial_export["content"]
    assert initial_export["metadata"]["chapter_count"] == 3

    reordered_volumes = reorder_volumes(
        session,
        novel_id,
        ordered_volume_ids=[second_volume_id, first_volume_id],
    )
    assert [item["title"] for item in reordered_volumes] == ["", ""]
    reordered_chapters = reorder_chapters(
        session,
        novel_id,
        ordered_document_ids=[
            UUID(second_document["id"]),
            UUID(ungrouped["id"]),
            first_document_id,
        ],
        volume_by_document={str(ungrouped["id"]): first_volume_id},
    )
    assert [item["title"] for item in reordered_chapters] == [
        "",
        "卷外章",
        "",
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
    with pytest.raises(ValidationError, match="最后一个分卷仍有章节"):
        delete_volume(
            session,
            novel_id,
            UUID(remaining["id"]),
            expected_version=remaining["version"],
        )
    session.rollback()


def test_ledger_visible_root_and_source_writers_advance_once_and_noop_zero(
    session: Session,
) -> None:
    novel = create_novel(session, "pytest-账本写命令矩阵")
    novel_id = UUID(novel["id"])

    character = create_novel_character(
        session,
        novel_id,
        role_type="supporting",
        name="档案管理员",
        description="负责保管旧案卷宗。",
        details={},
    )
    novel_row = session.get(Novel, novel_id)
    assert novel_row is not None
    character_ledger = novel_row.story_ledger_version
    character_catalog = novel_row.character_catalog_version
    archived_character = delete_novel_character(
        session,
        novel_id,
        UUID(character["id"]),
        expected_version=character["version"],
    )
    assert archived_character["changed"] is True
    assert archived_character["story_ledger_version"] == character_ledger + 1
    assert novel_row.character_catalog_version == character_catalog + 1
    archive_revision = session.scalar(
        select(NovelCharacterRevision).where(
            NovelCharacterRevision.character_id == UUID(character["id"]),
            NovelCharacterRevision.lifecycle_state == "archived",
        )
    )
    assert archive_revision is not None
    archived_character_replay = delete_novel_character(
        session,
        novel_id,
        UUID(character["id"]),
        expected_version=character["version"],
    )
    assert archived_character_replay["changed"] is False
    assert archived_character_replay["replayed"] is True
    assert archived_character_replay["story_ledger_version"] == character_ledger + 1

    ledger = get_novel(session, novel_id)["story_ledger_version"]
    storyline = create_storyline(
        session,
        novel_id,
        storyline_type="main",
        title="追查旧案",
        description="主角开始追查旧案。",
    )
    assert storyline["story_ledger_version"] == ledger + 1
    storyline_noop = update_storyline(
        session,
        novel_id,
        UUID(storyline["id"]),
        expected_version=storyline["version"],
        storyline_type=storyline["storyline_type"],
        title=storyline["title"],
        description=storyline["description"],
        status=storyline["planning_status"],
        progress=storyline["planning_progress"],
    )
    assert storyline_noop["changed"] is False
    assert storyline_noop["story_ledger_version"] == ledger + 1
    storyline_changed = update_storyline(
        session,
        novel_id,
        UUID(storyline["id"]),
        expected_version=storyline["version"],
        storyline_type=storyline["storyline_type"],
        title=storyline["title"],
        description="主角确认旧案与现在的失踪事件相关。",
        status="active",
        progress=20,
    )
    assert storyline_changed["story_ledger_version"] == ledger + 2
    archived = delete_storyline(
        session,
        novel_id,
        UUID(storyline["id"]),
        expected_version=storyline_changed["version"],
    )
    assert archived["changed"] is True
    assert archived["story_ledger_version"] == ledger + 3
    storyline_row = session.get(Storyline, UUID(storyline["id"]))
    assert storyline_row is not None and storyline_row.status == "archived"
    archived_noop = delete_storyline(
        session,
        novel_id,
        storyline_row.id,
        expected_version=storyline_row.version,
    )
    assert archived_noop["changed"] is False
    assert archived_noop["story_ledger_version"] == ledger + 3

    foreshadow = create_foreshadow(
        session,
        novel_id,
        title="旧钥匙",
        content="钥匙来自已封存的档案室。",
        latest_progress="尚未揭示",
    )
    dropped = delete_foreshadow(
        session,
        novel_id,
        UUID(foreshadow["id"]),
        expected_version=foreshadow["version"],
    )
    assert dropped["changed"] is True
    foreshadow_row = session.get(Foreshadow, UUID(foreshadow["id"]))
    assert foreshadow_row is not None and foreshadow_row.status == "dropped"

    first_volume_id = UUID(novel["tree"][0]["id"])
    document_id = UUID(novel["tree"][0]["documents"][0]["id"])
    document = get_document(session, document_id)
    saved = save_draft(
        session,
        document_id,
        expected_draft_version=document["draft_version"],
        content_markdown=_long_chapter("第一章留下权威来源。"),
    )
    checkpoint = create_checkpoint(
        session,
        document_id,
        expected_draft_version=saved["draft_version"],
    )
    source_fact = StoryFact(
        novel_id=novel_id,
        fact_type="general_fact",
        subject="旧钥匙",
        predicate="来源",
        object_text="档案室",
        details={"schema_version": "general-fact/1", "value": "档案室"},
        source_revision_id=UUID(checkpoint["revision"]["id"]),
        source_document_id=document_id,
        schema_version="story-fact/2",
        status="active",
    )
    session.add(source_fact)
    session.commit()

    source_ledger = get_novel(session, novel_id)["story_ledger_version"]
    same_document = update_document_metadata(
        session,
        novel_id,
        document_id,
        expected_version=checkpoint["document"]["version"],
        title=checkpoint["document"]["title"],
    )
    assert same_document["changed"] is False
    assert same_document["story_ledger_version"] == source_ledger
    renamed_document = update_document_metadata(
        session,
        novel_id,
        document_id,
        expected_version=same_document["version"],
        title="权威来源章",
    )
    assert renamed_document["changed"] is True
    assert renamed_document["story_ledger_version"] == source_ledger + 1
    with pytest.raises(ValidationError, match="故事账本的权威来源"):
        delete_document(
            session,
            novel_id,
            document_id,
            expected_version=renamed_document["version"],
        )
    session.rollback()
    assert session.get(Document, document_id) is not None

    first_volume = session.get(Volume, first_volume_id)
    assert first_volume is not None
    volume_ledger = get_novel(session, novel_id)["story_ledger_version"]
    same_volume = update_volume(
        session,
        novel_id,
        first_volume_id,
        expected_version=first_volume.version,
        title=first_volume.title,
    )
    assert same_volume["changed"] is False
    renamed_volume = update_volume(
        session,
        novel_id,
        first_volume_id,
        expected_version=same_volume["version"],
        title="来源卷",
    )
    assert renamed_volume["story_ledger_version"] == volume_ledger + 1

    second_document = create_document(
        session,
        novel_id,
        "第二章",
        volume_id=first_volume_id,
    )
    chapter_ledger = get_novel(session, novel_id)["story_ledger_version"]
    reordered_chapters = reorder_chapters(
        session,
        novel_id,
        ordered_document_ids=[UUID(second_document["id"]), document_id],
        volume_by_document={},
    )
    assert reordered_chapters[0]["changed"] is True
    assert reordered_chapters[0]["story_ledger_version"] == chapter_ledger + 1
    repeated_chapters = reorder_chapters(
        session,
        novel_id,
        ordered_document_ids=[UUID(second_document["id"]), document_id],
        volume_by_document={},
    )
    assert repeated_chapters[0]["changed"] is False
    assert repeated_chapters[0]["story_ledger_version"] == chapter_ledger + 1

    second_volume = create_volume(session, novel_id, "第二卷")
    volume_order_ledger = get_novel(session, novel_id)["story_ledger_version"]
    reordered_volumes = reorder_volumes(
        session,
        novel_id,
        ordered_volume_ids=[UUID(second_volume["id"]), first_volume_id],
    )
    assert reordered_volumes[0]["changed"] is True
    assert reordered_volumes[0]["story_ledger_version"] == volume_order_ledger + 1
    repeated_volumes = reorder_volumes(
        session,
        novel_id,
        ordered_volume_ids=[UUID(second_volume["id"]), first_volume_id],
    )
    assert repeated_volumes[0]["changed"] is False
    assert repeated_volumes[0]["story_ledger_version"] == volume_order_ledger + 1
