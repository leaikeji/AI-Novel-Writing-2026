from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import os
import re
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, event, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

from backend.creative_data_models import CharacterInstance, StoryEventLink, StoryTimeline
from backend.database import get_session
from backend.models import (
    CharacterRelationship,
    DerivedSourceBinding,
    Document,
    DocumentRevision,
    DocumentWorkingCopy,
    Foreshadow,
    IntelligenceCommitBatch,
    IntelligenceProposal,
    Novel,
    NovelCharacter,
    StoryFact,
    Storyline,
)
from backend.story_ledger.api import router
from backend.story_ledger.query import LedgerQueryFilters
from backend.story_ledger.service import StoryLedgerError, StoryLedgerErrorCode, StoryLedgerService


TEST_DATABASE_URL = os.environ.get("AI_NOVEL_TEST_DATABASE_URL", "").strip()
pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="AI_NOVEL_TEST_DATABASE_URL is not configured",
)
_SAFE_TEST_DATABASE = re.compile(r"^[A-Za-z0-9_]*_test$")


@pytest.fixture(scope="module")
def engine() -> Engine:
    parsed = make_url(TEST_DATABASE_URL)
    database_name = parsed.database or ""
    if parsed.get_backend_name() != "postgresql" or not _SAFE_TEST_DATABASE.fullmatch(
        database_name
    ):
        raise RuntimeError(
            "AI_NOVEL_TEST_DATABASE_URL must name an explicit PostgreSQL *_test database"
        )
    production_url = os.environ.get("AI_NOVEL_DATABASE_URL", "").strip()
    if production_url and make_url(production_url) == parsed:
        raise RuntimeError("test database must not equal AI_NOVEL_DATABASE_URL")
    value = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    yield value
    value.dispose()


@dataclass(frozen=True, slots=True)
class Seed:
    novel_id: UUID
    timeline_id: UUID
    fact_ids: dict[str, UUID]
    document_id: UUID
    revision_id: UUID
    batch_id: UUID
    relationship_id: UUID
    source_text: str


def _fact_details(fact_type: str, value: str) -> dict[str, object]:
    return {"schema_version": f"{fact_type.replace('_', '-')}/test", "value": value}


def _seed_full_matrix(engine: Engine) -> Seed:
    novel_id = uuid4()
    timeline_id = uuid4()
    document_id = uuid4()
    revision_id = uuid4()
    batch_id = uuid4()
    relationship_id = uuid4()
    source_text = "开场" + "甲在旧塔中发现钥匙。" + ("背景资料。" * 500)
    content_hash = sha256(source_text.encode("utf-8")).hexdigest()
    evidence_start = source_text.index("甲在旧塔中发现钥匙。")
    evidence_end = evidence_start + len("甲在旧塔中发现钥匙。")
    fact_ids: dict[str, UUID] = {}

    with Session(engine) as session:
        novel = Novel(id=novel_id, title="账本 API 测试", story_ledger_version=1)
        session.add(novel)
        session.flush()
        timeline = StoryTimeline(
            id=timeline_id,
            novel_id=novel_id,
            timeline_key="main",
            name="主时间线",
            normalized_name="主时间线",
            timeline_kind="main",
            is_primary=True,
            lifecycle_state="active",
            position=0,
            version=1,
        )
        session.add(timeline)
        session.flush()

        character_a = NovelCharacter(
            id=uuid4(),
            novel_id=novel_id,
            role_type="protagonist",
            name="甲",
            position=1,
            lifecycle_state="active",
        )
        character_b = NovelCharacter(
            id=uuid4(),
            novel_id=novel_id,
            role_type="supporting",
            name="乙",
            position=2,
            lifecycle_state="active",
        )
        session.add_all((character_a, character_b))
        session.flush()
        instance = CharacterInstance(
            id=uuid4(),
            novel_id=novel_id,
            character_id=character_a.id,
            origin_timeline_id=timeline_id,
            continuity_kind="native",
            display_label="甲·主线",
            lifecycle_state="active",
            version=1,
        )
        relationship = CharacterRelationship(
            id=relationship_id,
            novel_id=novel_id,
            source_character_id=character_a.id,
            target_character_id=character_b.id,
            timeline_id=timeline_id,
            source_character_instance_id=instance.id,
            directionality="directed",
            relation_kind="ally",
            label="盟友",
            normalized_label="盟友",
            relation_pair_key=f"{character_a.id}:{character_b.id}",
            status="active",
            created_by="manual",
            manual_override=True,
            evidence_json=[],
            version=1,
        )
        storyline = Storyline(
            id=uuid4(),
            novel_id=novel_id,
            storyline_type="main",
            title="寻钥匙",
            status="active",
            position=1,
        )
        foreshadow = Foreshadow(
            id=uuid4(),
            novel_id=novel_id,
            title="旧塔钥匙",
            status="planned",
            position=1,
        )
        session.add(instance)
        session.flush()
        session.add_all((relationship, storyline, foreshadow))
        session.flush()

        document = Document(
            id=document_id,
            novel_id=novel_id,
            kind="chapter",
            title="旧塔",
            position=1,
            status="ready",
        )
        session.add(document)
        session.flush()
        revision = DocumentRevision(
            id=revision_id,
            document_id=document_id,
            revision_number=1,
            content_markdown=source_text,
            content_text=source_text,
            content_hash=content_hash,
            source="manual",
        )
        session.add(revision)
        session.flush()
        session.add(
            DocumentWorkingCopy(
                document_id=document_id,
                base_revision_id=revision_id,
                draft_version=1,
                content_markdown=source_text,
                content_hash=content_hash,
            )
        )
        proposal = IntelligenceProposal(
            id=uuid4(),
            novel_id=novel_id,
            document_id=document_id,
            chapter_revision_id=revision_id,
            input_hash="1" * 64,
            extraction_context_json={},
            state="completed",
            requested_model_id="test-model",
            attempt=1,
        )
        session.add(proposal)
        session.flush()
        batch = IntelligenceCommitBatch(
            id=batch_id,
            proposal_id=proposal.id,
            chapter_revision_id=revision_id,
            commit_key="2" * 64,
            state="committed",
            accepted_item_ids=[],
            inverse_operations={},
            expected_story_ledger_version=1,
            committed_at=datetime.now(UTC),
        )
        session.add(batch)
        session.flush()

        specs = (
            (
                "character_state",
                "位置",
                "旧塔",
                "location",
                "state",
                {"character_id": character_a.id, "character_instance_id": instance.id},
            ),
            (
                "relationship_state",
                "关系",
                "盟友",
                "relationship",
                "state",
                {"relationship_id": relationship.id},
            ),
            (
                "storyline_event",
                "主线",
                "开始寻钥匙",
                "action",
                "advance",
                {"storyline_id": storyline.id},
            ),
            (
                "foreshadow_event",
                "伏笔",
                "埋下旧塔钥匙",
                "action",
                "plant",
                {"foreshadow_id": foreshadow.id},
            ),
            ("story_time", "时间", "第一日", "time", "anchor", {}),
            (
                "knowledge_event",
                "认知",
                "甲知道钥匙存在",
                "knowledge",
                "learn",
                {"character_id": character_a.id, "character_instance_id": instance.id},
            ),
            ("world_state", "世界", "旧塔封闭", "world", "state", {}),
            ("general_fact", "旁白", "钥匙很旧", "fact", "note", {}),
        )
        for index, (fact_type, predicate, object_text, dimension, event_kind, refs) in enumerate(
            specs, start=1
        ):
            fact_id = uuid4()
            fact_ids[fact_type] = fact_id
            has_source = fact_type == "knowledge_event"
            session.add(
                StoryFact(
                    id=fact_id,
                    novel_id=novel_id,
                    fact_type=fact_type,
                    subject="甲" if refs else "世界",
                    predicate=predicate,
                    object_text=object_text,
                    details=_fact_details(fact_type, object_text),
                    source_revision_id=revision_id if has_source else None,
                    source_document_id=document_id if has_source else None,
                    schema_version="story-fact/2",
                    timeline_id=timeline_id,
                    dimension=dimension,
                    event_kind=event_kind,
                    story_sequence=index,
                    source_start=evidence_start if has_source else None,
                    source_end=evidence_end if has_source else None,
                    status="active",
                    **refs,
                )
            )
        session.flush()
        sourced_fact_id = fact_ids["knowledge_event"]
        session.add(
            DerivedSourceBinding(
                id=uuid4(),
                derived_entity_id=sourced_fact_id,
                source_chapter_id=document_id,
                source_chapter_revision_id=revision_id,
                source_content_hash=content_hash,
                commit_batch_id=batch_id,
                validity_state="current",
            )
        )
        batch.inverse_operations = {
            "created_story_fact_ids": [str(sourced_fact_id)],
            "created_relationship_ids": [str(relationship.id)],
        }
        session.commit()
    return Seed(
        novel_id=novel_id,
        timeline_id=timeline_id,
        fact_ids=fact_ids,
        document_id=document_id,
        revision_id=revision_id,
        batch_id=batch_id,
        relationship_id=relationship_id,
        source_text=source_text,
    )


def _cleanup(engine: Engine, novel_id: UUID) -> None:
    with Session(engine) as session:
        session.execute(delete(Novel).where(Novel.id == novel_id))
        session.commit()


def _client(engine: Engine) -> TestClient:
    app = FastAPI()
    app.include_router(router)

    def session_override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    return TestClient(app, raise_server_exceptions=False)


def test_all_frozen_fact_types_page_summary_detail_source_and_impact(
    engine: Engine,
) -> None:
    seed = _seed_full_matrix(engine)
    try:
        with Session(engine) as session:
            first = StoryLedgerService(session).list_facts(seed.novel_id, limit=3)
        assert len(first.items) == 3
        assert first.next_cursor is not None
        collected = list(first.items)
        cursor = first.next_cursor
        while cursor:
            with Session(engine) as session:
                page = StoryLedgerService(session).list_facts(
                    seed.novel_id, limit=3, cursor=cursor
                )
            assert page.ledger_snapshot_token == first.ledger_snapshot_token
            collected.extend(page.items)
            cursor = page.next_cursor
        assert len(collected) == 8
        assert len({item.id for item in collected}) == 8
        assert {item.fact_type for item in collected} == set(seed.fact_ids)

        with Session(engine) as session:
            summary = StoryLedgerService(session).summary(seed.novel_id)
        assert summary.total == 8
        assert set(summary.by_fact_type) == set(seed.fact_ids)
        assert summary.by_health == {"ok": 8, "conflict": 0, "ambiguous": 0}
        assert summary.by_effective_state["current"] == 3

        with Session(engine) as session:
            detail = StoryLedgerService(session).detail(
                seed.novel_id, seed.fact_ids["knowledge_event"]
            )
        assert detail.item.effective_state == "current"
        assert detail.item.source is not None
        assert detail.item.source.commit_batch_id == seed.batch_id
        assert detail.item.source.evidence_available is True
        assert detail.bindings[0].commit_batch_state == "committed"

        with Session(engine) as session:
            source = StoryLedgerService(session).source(
                seed.novel_id, seed.fact_ids["knowledge_event"]
            )
        assert source.available is True
        assert len(source.excerpt) <= 1_600
        assert source.excerpt[source.highlight_start : source.highlight_end] == (
            "甲在旧塔中发现钥匙。"
        )
        assert source.source_content_hash == sha256(
            seed.source_text.encode("utf-8")
        ).hexdigest()

        with Session(engine) as session:
            impact = StoryLedgerService(session).fact_impact_preview(
                seed.novel_id, seed.fact_ids["knowledge_event"]
            )
        assert impact.preview_snapshot_token == first.ledger_snapshot_token
        assert impact.currently_in_projection is True
        assert impact.batch_fact_count == 1
        assert impact.batch_relationship_count == 1
        assert impact.correction_supported is True

        with Session(engine) as session:
            batch = StoryLedgerService(session).batch_impact_preview(
                seed.novel_id, seed.batch_id
            )
        assert batch.batch_fact_count == 1
        assert batch.batch_relationship_count == 1
        assert batch.facts[0]["object_preview"]
        assert "object_text" not in batch.facts[0]
    finally:
        _cleanup(engine, seed.novel_id)


def test_filters_bind_cursor_and_stale_version_returns_structured_409(
    engine: Engine,
) -> None:
    seed = _seed_full_matrix(engine)
    try:
        with _client(engine) as client:
            first = client.get(
                f"/novels/{seed.novel_id}/story-ledger/facts",
                params=[("limit", "2"), ("fact_type", "character_state"), ("fact_type", "knowledge_event")],
            )
            assert first.status_code == 200, first.text
            payload = first.json()
            assert payload["next_cursor"] is None

            general = client.get(
                f"/novels/{seed.novel_id}/story-ledger/facts", params={"limit": 2}
            )
            assert general.status_code == 200, general.text
            cursor = general.json()["next_cursor"]
            assert cursor
            changed_filter = client.get(
                f"/novels/{seed.novel_id}/story-ledger/facts",
                params={"limit": 2, "cursor": cursor, "health": "ok"},
            )
            assert changed_filter.status_code == 409
            assert changed_filter.json()["detail"]["code"] == "stale_page"

            with Session(engine) as writer:
                novel = writer.get(Novel, seed.novel_id)
                assert novel is not None
                novel.story_ledger_version += 1
                writer.commit()
            stale = client.get(
                f"/novels/{seed.novel_id}/story-ledger/facts",
                params={"limit": 2, "cursor": cursor},
            )
            assert stale.status_code == 409
            body = stale.json()["detail"]
            assert body["code"] == "stale_page"
            assert body["current"]["story_ledger_version"] == 2
            assert body["current"]["ledger_snapshot_token"] != general.json()[
                "ledger_snapshot_token"
            ]
    finally:
        _cleanup(engine, seed.novel_id)


def test_http_contract_for_summary_detail_source_and_both_previews(
    engine: Engine,
) -> None:
    seed = _seed_full_matrix(engine)
    fact_id = seed.fact_ids["knowledge_event"]
    try:
        with _client(engine) as client:
            summary = client.get(
                f"/novels/{seed.novel_id}/story-ledger/summary"
            )
            assert summary.status_code == 200, summary.text
            token = summary.json()["ledger_snapshot_token"]
            assert summary.json()["schema_version"] == "story-ledger-summary/1"

            detail = client.get(
                f"/novels/{seed.novel_id}/story-ledger/facts/{fact_id}",
                params={"snapshot_token": token},
            )
            assert detail.status_code == 200, detail.text
            assert detail.json()["schema_version"] == "story-ledger-fact-detail/1"
            assert detail.json()["ledger_snapshot_token"] == token

            source = client.get(
                f"/novels/{seed.novel_id}/story-ledger/facts/{fact_id}/source",
                params={"snapshot_token": token},
            )
            assert source.status_code == 200, source.text
            assert source.json()["schema_version"] == "story-ledger-source/1"
            assert source.json()["ledger_snapshot_token"] == token

            fact_preview = client.get(
                f"/novels/{seed.novel_id}/story-ledger/facts/{fact_id}/impact-preview",
                params={"snapshot_token": token},
            )
            assert fact_preview.status_code == 200, fact_preview.text
            assert fact_preview.json()["preview_snapshot_token"] == token

            batch_preview = client.get(
                f"/novels/{seed.novel_id}/story-ledger/batches/{seed.batch_id}/impact-preview",
                params={"snapshot_token": token},
            )
            assert batch_preview.status_code == 200, batch_preview.text
            assert batch_preview.json()["preview_snapshot_token"] == token
    finally:
        _cleanup(engine, seed.novel_id)


def test_empty_ledger_returns_explainable_zero_summary_and_page(engine: Engine) -> None:
    novel_id = uuid4()
    timeline_id = uuid4()
    try:
        with Session(engine) as setup:
            setup.add(Novel(id=novel_id, title="空账本"))
            setup.flush()
            setup.add(
                StoryTimeline(
                    id=timeline_id,
                    novel_id=novel_id,
                    timeline_key="main",
                    name="主时间线",
                    normalized_name="主时间线",
                    timeline_kind="main",
                    is_primary=True,
                    lifecycle_state="active",
                    position=0,
                    version=1,
                )
            )
            setup.commit()
        with Session(engine) as session:
            summary = StoryLedgerService(session).summary(novel_id)
        with Session(engine) as session:
            page = StoryLedgerService(session).list_facts(novel_id)
        assert summary.total == 0
        assert summary.review_required == 0
        assert page.items == ()
        assert page.next_cursor is None
        assert page.ledger_snapshot_token == summary.ledger_snapshot_token
    finally:
        _cleanup(engine, novel_id)


def test_multiple_active_timelines_require_explicit_context_and_scope_ids(
    engine: Engine,
) -> None:
    seed = _seed_full_matrix(engine)
    branch_id = uuid4()
    try:
        with Session(engine) as session:
            session.add(
                StoryTimeline(
                    id=branch_id,
                    novel_id=seed.novel_id,
                    timeline_key="branch",
                    name="支线",
                    normalized_name="支线",
                    timeline_kind="branch",
                    is_primary=False,
                    parent_timeline_id=seed.timeline_id,
                    fork_story_sequence=4,
                    lifecycle_state="active",
                    position=1,
                    version=1,
                )
            )
            session.commit()
        with Session(engine) as session:
            with pytest.raises(StoryLedgerError) as captured:
                StoryLedgerService(session).summary(seed.novel_id)
        assert captured.value.code is StoryLedgerErrorCode.TIMELINE_REQUIRED

        with Session(engine) as session:
            summary = StoryLedgerService(session).summary(
                seed.novel_id, timeline_id=branch_id
            )
        assert summary.timeline.mode == "multiple"
        assert summary.timeline.timeline_id == branch_id
        assert summary.total == 8
    finally:
        _cleanup(engine, seed.novel_id)


def test_same_position_conflict_supersedes_and_reverted_binding_axes(
    engine: Engine,
) -> None:
    seed = _seed_full_matrix(engine)
    conflict_a = uuid4()
    conflict_b = uuid4()
    old_fact = uuid4()
    replacement = uuid4()
    reverted_fact = uuid4()
    try:
        with Session(engine) as session:
            for fact_id, value in ((conflict_a, "东"), (conflict_b, "西")):
                session.add(
                    StoryFact(
                        id=fact_id,
                        novel_id=seed.novel_id,
                        fact_type="character_state",
                        subject="冲突人物",
                        predicate="位置",
                        object_text=value,
                        details=_fact_details("character_state", value),
                        schema_version="story-fact/2",
                        timeline_id=seed.timeline_id,
                        dimension="location",
                        event_kind="state",
                        story_sequence=99,
                        status="active",
                    )
                )
            for fact_id, value in ((old_fact, "旧"), (replacement, "新")):
                session.add(
                    StoryFact(
                        id=fact_id,
                        novel_id=seed.novel_id,
                        fact_type="general_fact",
                        subject="替代",
                        predicate="值",
                        object_text=value,
                        details=_fact_details("general_fact", value),
                        schema_version="story-fact/2",
                        timeline_id=seed.timeline_id,
                        dimension="fact",
                        event_kind="note",
                        story_sequence=100,
                        status="active",
                    )
                )
            session.add(
                StoryFact(
                    id=reverted_fact,
                    novel_id=seed.novel_id,
                    fact_type="knowledge_event",
                    subject="撤销",
                    predicate="知识",
                    object_text="已撤销",
                    details=_fact_details("knowledge_event", "已撤销"),
                    source_revision_id=seed.revision_id,
                    source_document_id=seed.document_id,
                    schema_version="story-fact/2",
                    timeline_id=seed.timeline_id,
                    dimension="knowledge",
                    event_kind="learn",
                    story_sequence=101,
                    source_start=0,
                    source_end=2,
                    status="active",
                )
            )
            session.flush()
            session.add(
                StoryEventLink(
                    id=uuid4(),
                    novel_id=seed.novel_id,
                    source_fact_id=replacement,
                    target_fact_id=old_fact,
                    link_type="supersedes",
                    details_json={},
                )
            )
            batch = session.get(IntelligenceCommitBatch, seed.batch_id)
            assert batch is not None
            batch.state = "reverted"
            session.add(
                DerivedSourceBinding(
                    id=uuid4(),
                    derived_entity_id=reverted_fact,
                    source_chapter_id=seed.document_id,
                    source_chapter_revision_id=seed.revision_id,
                    source_content_hash=sha256(seed.source_text.encode("utf-8")).hexdigest(),
                    commit_batch_id=seed.batch_id,
                    validity_state="current",
                )
            )
            session.commit()

        with Session(engine) as session:
            page = StoryLedgerService(session).list_facts(seed.novel_id, limit=100)
        by_id = {item.id: item for item in page.items}
        assert by_id[conflict_a].health == "conflict"
        assert by_id[conflict_b].health == "conflict"
        assert "same_position_conflict" in by_id[conflict_a].health_reason_codes
        assert by_id[old_fact].effective_state == "superseded"
        assert by_id[old_fact].included_in_current_projection is False
        assert by_id[reverted_fact].effective_state == "batch_reverted"
        assert by_id[reverted_fact].included_in_current_projection is False
    finally:
        _cleanup(engine, seed.novel_id)


def test_page_sql_count_is_bounded_by_page_shape_not_item_count(engine: Engine) -> None:
    seed = _seed_full_matrix(engine)
    try:
        with Session(engine) as setup:
            setup.add_all(
                StoryFact(
                    id=uuid4(),
                    novel_id=seed.novel_id,
                    fact_type="general_fact",
                    subject="性能样本",
                    predicate=f"字段 {index}",
                    object_text=f"值 {index}",
                    details=_fact_details("general_fact", f"值 {index}"),
                    schema_version="story-fact/2",
                    timeline_id=seed.timeline_id,
                    dimension="fact",
                    event_kind="note",
                    story_sequence=300 + index,
                    status="active",
                )
                for index in range(20)
            )
            setup.commit()
        counts: list[int] = []
        for limit in (1, 10):
            statements = 0

            def count_statement(*_args, **_kwargs) -> None:
                nonlocal statements
                statements += 1

            event.listen(engine, "before_cursor_execute", count_statement)
            try:
                with Session(engine) as session:
                    page = StoryLedgerService(session).list_facts(
                        seed.novel_id,
                        limit=limit,
                        filters=LedgerQueryFilters(
                            fact_types=("general_fact",)
                        ),
                    )
                assert len(page.items) == limit
            finally:
                event.remove(engine, "before_cursor_execute", count_statement)
            counts.append(statements)
        assert counts[0] <= 8
        assert counts[1] <= 8
        assert counts[1] == counts[0]

        mixed_statements = 0

        def count_mixed(*_args, **_kwargs) -> None:
            nonlocal mixed_statements
            mixed_statements += 1

        event.listen(engine, "before_cursor_execute", count_mixed)
        try:
            with Session(engine) as session:
                mixed = StoryLedgerService(session).list_facts(
                    seed.novel_id, limit=100
                )
            assert len(mixed.items) == 28
        finally:
            event.remove(engine, "before_cursor_execute", count_mixed)
        assert mixed_statements <= 10
    finally:
        _cleanup(engine, seed.novel_id)


def test_token_and_page_are_from_one_repeatable_read_snapshot(engine: Engine) -> None:
    seed = _seed_full_matrix(engine)
    writer_ran = False
    writer_running = False

    def concurrent_write(_connection, _cursor, statement, _parameters, _context, _many):
        nonlocal writer_ran, writer_running
        if writer_ran or writer_running or "FROM novels" not in statement:
            return
        writer_running = True
        try:
            with Session(engine) as writer:
                novel = writer.get(Novel, seed.novel_id)
                assert novel is not None
                novel.story_ledger_version += 1
                writer.add(
                    StoryFact(
                        id=uuid4(),
                        novel_id=seed.novel_id,
                        fact_type="general_fact",
                        subject="并发",
                        predicate="新增",
                        object_text="新快照中的事实",
                        details=_fact_details("general_fact", "新快照中的事实"),
                        schema_version="story-fact/2",
                        timeline_id=seed.timeline_id,
                        dimension="fact",
                        event_kind="note",
                        story_sequence=200,
                        status="active",
                    )
                )
                writer.commit()
            writer_ran = True
        finally:
            writer_running = False

    try:
        event.listen(engine, "after_cursor_execute", concurrent_write)
        try:
            with Session(engine) as reader:
                page = StoryLedgerService(reader).list_facts(
                    seed.novel_id, limit=100
                )
        finally:
            event.remove(engine, "after_cursor_execute", concurrent_write)
        assert writer_ran is True
        assert page.story_ledger_version == 1
        assert len(page.items) == 8

        with Session(engine) as current:
            refreshed = StoryLedgerService(current).summary(seed.novel_id)
        assert refreshed.story_ledger_version == 2
        assert refreshed.total == 9
        with Session(engine) as stale:
            with pytest.raises(StoryLedgerError) as captured:
                StoryLedgerService(stale).list_facts(
                    seed.novel_id,
                    snapshot_token=page.ledger_snapshot_token,
                    limit=100,
                )
        assert captured.value.code is StoryLedgerErrorCode.SNAPSHOT_CONFLICT
    finally:
        _cleanup(engine, seed.novel_id)


def test_cross_novel_fact_and_batch_ids_are_not_disclosed(engine: Engine) -> None:
    first = _seed_full_matrix(engine)
    second = _seed_full_matrix(engine)
    try:
        with Session(engine) as session:
            with pytest.raises(StoryLedgerError) as fact_error:
                StoryLedgerService(session).detail(
                    first.novel_id, second.fact_ids["general_fact"]
                )
        assert fact_error.value.code is StoryLedgerErrorCode.FACT_NOT_FOUND
        with Session(engine) as session:
            with pytest.raises(StoryLedgerError) as batch_error:
                StoryLedgerService(session).batch_impact_preview(
                    first.novel_id, second.batch_id
                )
        assert batch_error.value.code is StoryLedgerErrorCode.BATCH_NOT_FOUND
    finally:
        _cleanup(engine, first.novel_id)
        _cleanup(engine, second.novel_id)
