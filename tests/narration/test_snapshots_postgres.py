from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

from backend.models import Document, DocumentRevision, DocumentWorkingCopy, Novel
from backend.narration.services import (
    NarrationCasConflict,
    NarrationNotFound,
    SqlAlchemyNarrationStore,
)
from backend.narration.snapshots import (
    CreateTtsSnapshot,
    _insert_tts_snapshot_or_get,
    create_tts_snapshot,
)
from backend.services import content_hash


EXPECTED_DATABASE = "ai_novel_world_2026_tts_test"
EXPECTED_USERNAME = "tts_test"


def _live_url() -> str:
    raw = os.environ.get("TTS_T1G_TEST_DATABASE_URL", "").strip()
    if not raw:
        pytest.skip("TTS_T1G_TEST_DATABASE_URL is not configured")
    parsed = make_url(raw)
    if (
        not parsed.drivername.startswith("postgresql")
        or parsed.database != EXPECTED_DATABASE
        or parsed.username != EXPECTED_USERNAME
        or parsed.host not in {"127.0.0.1", "localhost", "::1"}
    ):
        raise RuntimeError("snapshot live tests require the exact disposable loopback DB")
    production = os.environ.get("AI_NOVEL_DATABASE_URL", "").strip()
    if production:
        prod = make_url(production)
        if (parsed.host, parsed.port, parsed.database) == (
            prod.host,
            prod.port,
            prod.database,
        ):
            raise RuntimeError("snapshot test database must differ from production")
    return raw


@pytest.fixture(scope="module")
def pg_engine() -> Engine:
    engine = create_engine(_live_url(), pool_pre_ping=True)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "20260826_0015"
        )
    try:
        yield engine
    finally:
        engine.dispose()


@dataclass(frozen=True)
class SeededDocument:
    novel_id: UUID
    document_id: UUID
    base_revision_id: UUID
    draft_version: int
    markdown: str
    digest: str


def _novel(novel_id: UUID) -> Novel:
    return Novel(
        id=novel_id,
        title=f"snapshot-live-{novel_id}",
        author_name="author",
        description="",
        writing_type="novel",
        audience="general",
        genre="fiction",
        subgenre="",
        idea="",
        template_name="",
        template_data={},
        cover_mode="none",
        cover_image_data="",
        outline_target_chapters=0,
        highlight="",
        background="",
        main_plot="",
        story_ledger_version=1,
        version=1,
    )


def _seed_document(engine: Engine, *, markdown: str = "初始正文") -> SeededDocument:
    novel_id, document_id, revision_id = uuid4(), uuid4(), uuid4()
    digest = content_hash(markdown)
    with Session(engine, expire_on_commit=False) as session:
        session.add(_novel(novel_id))
        session.flush()
        session.add(
            Document(
                id=document_id,
                novel_id=novel_id,
                kind="chapter",
                title="chapter",
                position=1,
                status="draft",
                version=1,
            )
        )
        session.flush()
        session.add(
            DocumentRevision(
                id=revision_id,
                document_id=document_id,
                revision_number=1,
                content_markdown=markdown,
                content_text=markdown,
                content_hash=digest,
                source="manual_checkpoint",
            )
        )
        session.flush()
        session.add(
            DocumentWorkingCopy(
                document_id=document_id,
                base_revision_id=revision_id,
                draft_version=1,
                content_markdown=markdown,
                content_hash=digest,
            )
        )
        session.commit()
    return SeededDocument(novel_id, document_id, revision_id, 1, markdown, digest)


def _set_worker_name(session: Session, name: str) -> None:
    session.execute(
        text("SELECT set_config('application_name', :name, true)"), {"name": name}
    )
    session.execute(text("SET LOCAL lock_timeout = '5s'"))


def _wait_until_lock_wait(engine: Engine, application_name: str) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with engine.connect() as observer:
            wait_type = observer.scalar(
                text(
                    "SELECT wait_event_type FROM pg_stat_activity "
                    "WHERE application_name=:name AND state='active'"
                ),
                {"name": application_name},
            )
        if wait_type == "Lock":
            return
        time.sleep(0.02)
    raise AssertionError(
        f"worker {application_name} never reached the expected row/index lock wait"
    )


def _tts_candidate(
    seeded: SeededDocument, *, revision_id: UUID, markdown: str
) -> DocumentRevision:
    return DocumentRevision(
        id=revision_id,
        document_id=seeded.document_id,
        revision_number=2,
        parent_revision_id=seeded.base_revision_id,
        content_markdown=markdown,
        content_text=markdown,
        content_hash=content_hash(markdown),
        source="tts_snapshot",
    )


def test_snapshot_refreshes_a_preloaded_identity_before_cas(pg_engine: Engine) -> None:
    seeded = _seed_document(pg_engine)
    stale = Session(pg_engine, expire_on_commit=False)
    writer = Session(pg_engine, expire_on_commit=False)
    try:
        preloaded = stale.get(DocumentWorkingCopy, seeded.document_id)
        assert preloaded is not None and preloaded.draft_version == 1
        current = writer.scalar(
            select(DocumentWorkingCopy)
            .where(DocumentWorkingCopy.document_id == seeded.document_id)
            .with_for_update()
        )
        assert current is not None
        current.content_markdown = "第二版正文"
        current.content_hash = content_hash(current.content_markdown)
        current.draft_version = 2
        writer.commit()

        with pytest.raises(NarrationCasConflict):
            create_tts_snapshot(
                SqlAlchemyNarrationStore(stale),
                CreateTtsSnapshot(
                    novel_id=seeded.novel_id,
                    document_id=seeded.document_id,
                    expected_draft_version=1,
                    expected_content_hash=seeded.digest,
                ),
            )
        stale.rollback()
        assert preloaded.draft_version == 2
    finally:
        stale.close()
        writer.close()


def test_autosave_first_lock_order_waits_then_snapshot_rejects_without_deadlock(
    pg_engine: Engine,
) -> None:
    seeded = _seed_document(pg_engine)
    writer_locked = threading.Event()
    release_writer = threading.Event()
    result: dict[str, object] = {}

    def writer() -> None:
        with Session(pg_engine, expire_on_commit=False) as session:
            working = session.scalar(
                select(DocumentWorkingCopy)
                .where(DocumentWorkingCopy.document_id == seeded.document_id)
                .with_for_update()
            )
            assert working is not None
            working.content_markdown = "自动保存后的正文"
            working.content_hash = content_hash(working.content_markdown)
            working.draft_version = 2
            session.flush()
            writer_locked.set()
            assert release_writer.wait(timeout=5)
            session.execute(
                text("UPDATE novels SET updated_at=now() WHERE id=:id"),
                {"id": seeded.novel_id},
            )
            session.commit()

    def snapshot() -> None:
        assert writer_locked.wait(timeout=5)
        try:
            with Session(pg_engine, expire_on_commit=False) as session:
                create_tts_snapshot(
                    SqlAlchemyNarrationStore(session),
                    CreateTtsSnapshot(
                        novel_id=seeded.novel_id,
                        document_id=seeded.document_id,
                        expected_draft_version=1,
                        expected_content_hash=seeded.digest,
                    ),
                )
                session.commit()
        except BaseException as error:  # captured and asserted in the parent thread
            result["error"] = error

    writer_thread = threading.Thread(target=writer, daemon=True)
    snapshot_thread = threading.Thread(target=snapshot, daemon=True)
    writer_thread.start()
    assert writer_locked.wait(timeout=5)
    snapshot_thread.start()
    time.sleep(0.15)
    assert snapshot_thread.is_alive(), "snapshot should be waiting on the working-copy mutex"
    release_writer.set()
    writer_thread.join(timeout=5)
    snapshot_thread.join(timeout=5)
    assert not writer_thread.is_alive() and not snapshot_thread.is_alive()
    assert isinstance(result.get("error"), NarrationCasConflict)


def test_two_snapshot_sessions_reuse_one_hidden_revision_without_baseline_change(
    pg_engine: Engine,
) -> None:
    seeded = _seed_document(pg_engine, markdown="并发快照基线")
    current_markdown = "并发快照正文"
    current_digest = content_hash(current_markdown)
    current_version = seeded.draft_version + 1
    with Session(pg_engine) as session:
        working = session.scalar(
            select(DocumentWorkingCopy)
            .where(DocumentWorkingCopy.document_id == seeded.document_id)
            .with_for_update()
        )
        assert working is not None
        working.content_markdown = current_markdown
        working.content_hash = current_digest
        working.draft_version = current_version
        session.commit()
    barrier = threading.Barrier(2)
    revision_ids: list[UUID] = []
    errors: list[BaseException] = []

    def run_snapshot() -> None:
        try:
            with Session(pg_engine, expire_on_commit=False) as session:
                barrier.wait(timeout=5)
                revision = create_tts_snapshot(
                    SqlAlchemyNarrationStore(session),
                    CreateTtsSnapshot(
                        novel_id=seeded.novel_id,
                        document_id=seeded.document_id,
                        expected_draft_version=current_version,
                        expected_content_hash=current_digest,
                    ),
                )
                revision_ids.append(revision.id)
                session.commit()
        except BaseException as error:
            errors.append(error)

    threads = [threading.Thread(target=run_snapshot, daemon=True) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    assert len(revision_ids) == 2 and len(set(revision_ids)) == 1

    with Session(pg_engine) as session:
        snapshots = session.scalars(
            select(DocumentRevision).where(
                DocumentRevision.document_id == seeded.document_id,
                DocumentRevision.source == "tts_snapshot",
            )
        ).all()
        working = session.get(DocumentWorkingCopy, seeded.document_id)
        assert len(snapshots) == 1
        assert working is not None
        assert (
            working.base_revision_id,
            working.draft_version,
            working.content_hash,
        ) == (seeded.base_revision_id, current_version, current_digest)


def test_delete_first_blocks_snapshot_then_snapshot_fails_without_deadlock(
    pg_engine: Engine,
) -> None:
    seeded = _seed_document(pg_engine, markdown="删除先获得文档锁")
    delete_locked = threading.Event()
    release_delete = threading.Event()
    errors: dict[str, BaseException] = {}
    snapshot_name = f"t1f-snapshot-after-delete-{uuid4()}"

    def delete_document() -> None:
        try:
            with Session(pg_engine, expire_on_commit=False) as session:
                document = session.scalar(
                    select(Document)
                    .where(Document.id == seeded.document_id)
                    .with_for_update()
                )
                assert document is not None
                delete_locked.set()
                assert release_delete.wait(timeout=5)
                session.delete(document)
                session.commit()
        except BaseException as error:
            errors["delete"] = error

    def take_snapshot() -> None:
        assert delete_locked.wait(timeout=5)
        try:
            with Session(pg_engine, expire_on_commit=False) as session:
                _set_worker_name(session, snapshot_name)
                create_tts_snapshot(
                    SqlAlchemyNarrationStore(session),
                    CreateTtsSnapshot(
                        novel_id=seeded.novel_id,
                        document_id=seeded.document_id,
                        expected_draft_version=seeded.draft_version,
                        expected_content_hash=seeded.digest,
                    ),
                )
                session.commit()
        except BaseException as error:
            errors["snapshot"] = error

    delete_thread = threading.Thread(target=delete_document, daemon=True)
    snapshot_thread = threading.Thread(target=take_snapshot, daemon=True)
    delete_thread.start()
    assert delete_locked.wait(timeout=5)
    snapshot_thread.start()
    _wait_until_lock_wait(pg_engine, snapshot_name)
    release_delete.set()
    delete_thread.join(timeout=5)
    snapshot_thread.join(timeout=5)

    assert not delete_thread.is_alive() and not snapshot_thread.is_alive()
    assert "delete" not in errors
    assert isinstance(errors.get("snapshot"), NarrationNotFound)
    with Session(pg_engine) as session:
        assert session.get(Document, seeded.document_id) is None
        assert session.get(DocumentWorkingCopy, seeded.document_id) is None


def test_snapshot_first_blocks_delete_then_delete_cascades_without_deadlock(
    pg_engine: Engine,
) -> None:
    seeded = _seed_document(pg_engine, markdown="快照先获得文档锁")
    snapshot_locked = threading.Event()
    release_snapshot = threading.Event()
    errors: dict[str, BaseException] = {}
    delete_name = f"t1f-delete-after-snapshot-{uuid4()}"

    def take_snapshot() -> None:
        try:
            with Session(pg_engine, expire_on_commit=False) as session:
                create_tts_snapshot(
                    SqlAlchemyNarrationStore(session),
                    CreateTtsSnapshot(
                        novel_id=seeded.novel_id,
                        document_id=seeded.document_id,
                        expected_draft_version=seeded.draft_version,
                        expected_content_hash=seeded.digest,
                    ),
                )
                snapshot_locked.set()
                assert release_snapshot.wait(timeout=5)
                session.commit()
        except BaseException as error:
            errors["snapshot"] = error

    def delete_document() -> None:
        assert snapshot_locked.wait(timeout=5)
        try:
            with Session(pg_engine, expire_on_commit=False) as session:
                _set_worker_name(session, delete_name)
                document = session.scalar(
                    select(Document)
                    .where(Document.id == seeded.document_id)
                    .with_for_update()
                )
                assert document is not None
                session.delete(document)
                session.commit()
        except BaseException as error:
            errors["delete"] = error

    snapshot_thread = threading.Thread(target=take_snapshot, daemon=True)
    delete_thread = threading.Thread(target=delete_document, daemon=True)
    snapshot_thread.start()
    assert snapshot_locked.wait(timeout=5)
    delete_thread.start()
    _wait_until_lock_wait(pg_engine, delete_name)
    release_snapshot.set()
    snapshot_thread.join(timeout=5)
    delete_thread.join(timeout=5)

    assert not snapshot_thread.is_alive() and not delete_thread.is_alive()
    assert errors == {}
    with Session(pg_engine) as session:
        assert session.get(Document, seeded.document_id) is None
        assert session.get(DocumentWorkingCopy, seeded.document_id) is None


def test_partial_unique_loser_reloads_winner_and_keeps_outer_transaction_usable(
    pg_engine: Engine,
) -> None:
    seeded = _seed_document(pg_engine, markdown="唯一竞争基线")
    markdown = "两个执行者提交相同的隐藏快照"
    winner_candidate = _tts_candidate(seeded, revision_id=uuid4(), markdown=markdown)
    loser_candidate = _tts_candidate(seeded, revision_id=uuid4(), markdown=markdown)
    winner_inserted = threading.Event()
    release_winner = threading.Event()
    results: dict[str, UUID] = {}
    errors: dict[str, BaseException] = {}
    # PostgreSQL truncates application_name at NAMEDATALEN-1 (63 bytes).
    loser_name = f"t1f-uniq-{uuid4()}"

    def insert_winner() -> None:
        try:
            with Session(pg_engine, expire_on_commit=False) as session:
                row = _insert_tts_snapshot_or_get(
                    SqlAlchemyNarrationStore(session), winner_candidate
                )
                results["winner"] = row.id
                winner_inserted.set()
                assert release_winner.wait(timeout=5)
                session.commit()
        except BaseException as error:
            errors["winner"] = error

    def insert_loser() -> None:
        assert winner_inserted.wait(timeout=5)
        try:
            with Session(pg_engine, expire_on_commit=False) as session:
                _set_worker_name(session, loser_name)
                row = _insert_tts_snapshot_or_get(
                    SqlAlchemyNarrationStore(session), loser_candidate
                )
                results["loser"] = row.id
                session.execute(
                    text("UPDATE novels SET description=:value WHERE id=:id"),
                    {
                        "id": seeded.novel_id,
                        "value": "partial-unique loser outer transaction remained usable",
                    },
                )
                session.commit()
        except BaseException as error:
            errors["loser"] = error

    winner_thread = threading.Thread(target=insert_winner, daemon=True)
    loser_thread = threading.Thread(target=insert_loser, daemon=True)
    winner_thread.start()
    assert winner_inserted.wait(timeout=5)
    loser_thread.start()
    _wait_until_lock_wait(pg_engine, loser_name)
    release_winner.set()
    winner_thread.join(timeout=5)
    loser_thread.join(timeout=5)

    assert not winner_thread.is_alive() and not loser_thread.is_alive()
    assert errors == {}
    assert results == {
        "winner": winner_candidate.id,
        "loser": winner_candidate.id,
    }
    with Session(pg_engine) as session:
        rows = session.scalars(
            select(DocumentRevision).where(
                DocumentRevision.document_id == seeded.document_id,
                DocumentRevision.content_hash == winner_candidate.content_hash,
                DocumentRevision.source == "tts_snapshot",
            )
        ).all()
        novel = session.get(Novel, seeded.novel_id)
        assert [row.id for row in rows] == [winner_candidate.id]
        assert novel is not None
        assert novel.description == (
            "partial-unique loser outer transaction remained usable"
        )
