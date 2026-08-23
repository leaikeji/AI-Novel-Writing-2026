from __future__ import annotations

import os
from uuid import UUID

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from backend.models import Document, Novel
from backend.services import (
    DraftConflictError,
    create_checkpoint,
    create_novel,
    get_document,
    get_novel_context,
    restore_revision,
    save_draft,
    search_novel,
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
                "'story_facts','novel_chunks','media_assets')"
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
