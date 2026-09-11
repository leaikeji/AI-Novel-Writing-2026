from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from threading import Event
from urllib.parse import urlparse

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from backend.models import Novel, NovelLifecycleEvent
from backend.novel_lifecycle import lock_active_novel, recycle_novel
from backend.novel_lifecycle_errors import NovelRecycledError


def _test_engine():  # type: ignore[no-untyped-def]
    url = os.environ.get("AI_NOVEL_DATABASE_URL", "")
    if not url:
        pytest.skip("AI_NOVEL_DATABASE_URL is required for PostgreSQL race tests")
    database = urlparse(url.replace("postgresql+psycopg", "postgresql", 1)).path.lstrip("/")
    if "plan67" not in database:
        pytest.fail("race tests refuse a database not explicitly named for plan67")
    return create_engine(url, pool_size=4, max_overflow=0)


def _novel(engine, title: str) -> tuple[object, int]:  # type: ignore[no-untyped-def]
    with Session(engine) as session:
        row = Novel(title=title)
        session.add(row)
        session.commit()
        return row.id, row.version


def test_same_idempotency_key_concurrently_creates_one_event() -> None:
    engine = _test_engine()
    novel_id, version = _novel(engine, "plan67 concurrent idempotency")
    start = Event()

    def act() -> dict[str, object]:
        with Session(engine) as session:
            start.wait()
            value = recycle_novel(
                session, novel_id, version, "race-same-key"  # type: ignore[arg-type]
            )
            session.commit()
            return value

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(act), executor.submit(act)]
        start.set()
        results = [future.result(timeout=10) for future in futures]

    assert {value["replayed"] for value in results} == {False, True}
    assert len({value["event_id"] for value in results}) == 1
    with Session(engine) as session:
        assert session.scalar(
            select(func.count()).select_from(NovelLifecycleEvent).where(
                NovelLifecycleEvent.novel_id == novel_id
            )
        ) == 1


def test_active_write_commits_before_waiting_recycle() -> None:
    engine = _test_engine()
    novel_id, version = _novel(engine, "plan67 write before recycle")
    writer_locked = Event()
    allow_writer_commit = Event()

    def writer() -> None:
        with Session(engine) as session:
            row = lock_active_novel(session, novel_id)  # type: ignore[arg-type]
            row.description = "author write committed before recycle"
            writer_locked.set()
            allow_writer_commit.wait()
            session.commit()

    def recycler() -> dict[str, object]:
        writer_locked.wait()
        with Session(engine) as session:
            return_value = recycle_novel(
                session, novel_id, version, "race-after-write"  # type: ignore[arg-type]
            )
            session.commit()
            return return_value

    with ThreadPoolExecutor(max_workers=2) as executor:
        write_future = executor.submit(writer)
        recycle_future = executor.submit(recycler)
        writer_locked.wait(timeout=5)
        allow_writer_commit.set()
        write_future.result(timeout=10)
        result = recycle_future.result(timeout=10)

    assert result["action"] == "recycled"
    with Session(engine) as session:
        row = session.get(Novel, novel_id)
        assert row.description == "author write committed before recycle"
        assert row.recycled_at is not None


def test_recycle_commit_fences_later_active_write() -> None:
    engine = _test_engine()
    novel_id, version = _novel(engine, "plan67 recycle before write")
    with Session(engine) as session:
        recycle_novel(session, novel_id, version, "race-before-write")  # type: ignore[arg-type]
        session.commit()
    with Session(engine) as session, pytest.raises(NovelRecycledError):
        lock_active_novel(session, novel_id)  # type: ignore[arg-type]
