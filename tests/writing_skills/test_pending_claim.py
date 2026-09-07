"""Durable preparation ownership and one-time freeze on isolated PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from backend.writing_skills.persistence import (
    PendingAction, ActionConflict, StaleFence, advance, claim_pending_action,
    freeze_prepared_action, lookup_action,
)
from backend.writing_skills.api import method_status
from .test_persistence import engine, request


def acquire(engine, req):
    with Session(engine) as session:
        return claim_pending_action(session, req.identity, req.projection.scope,
                                    "b" * 64, authorize=lambda *_: None)


def test_concurrent_pending_claim_has_one_preparation_owner(engine):
    req = request()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: acquire(engine, req), range(16)))
    assert sum(row.acquired for row in results) == 1
    assert len({row.id for row in results}) == 1
    assert all(isinstance(row, PendingAction) for row in results)
    assert method_status(results[0]).method_input_hash is None
    with Session(engine) as session:
        with pytest.raises(ActionConflict):
            lookup_action(session, req.identity, req.projection.scope, "c" * 64, authorize=lambda *_: None)


def test_one_freeze_then_immutable_and_fenced(engine):
    req = request()
    pending = acquire(engine, req)
    with Session(engine) as session:
        frozen = freeze_prepared_action(session, pending, req)
        assert frozen.request == req and frozen.fence == pending.fence + 1
        with pytest.raises(StaleFence):
            freeze_prepared_action(session, pending, req)
        with pytest.raises(DBAPIError, match="snapshot is immutable"):
            session.execute(text("UPDATE writing_skill_dispatches SET route_request_key=:key WHERE id=:id"),
                            {"id": pending.id, "key": "d" * 64})
        session.rollback()
    assert acquire(engine, req).request == req


def test_failed_or_cancelled_pending_cannot_freeze_or_reclaim(engine):
    for terminal in ("failed", "cancelled", "stale"):
        req = request()
        pending = acquire(engine, req)
        with Session(engine) as session:
            settled = advance(session, pending, terminal)
            assert settled.state == terminal
            with pytest.raises(StaleFence):
                freeze_prepared_action(session, pending, req)
        replay = acquire(engine, req)
        assert replay.state == terminal and not replay.acquired


def test_pending_cannot_dispatch_or_change_scope(engine):
    req = request()
    pending = acquire(engine, req)
    with Session(engine) as session:
        with pytest.raises(ValueError, match="must be frozen"):
            advance(session, pending, "route_ready")
        with pytest.raises(ActionConflict):
            freeze_prepared_action(session, pending, request())
        with pytest.raises(DBAPIError, match="pending input cannot dispatch"):
            session.execute(text("UPDATE writing_skill_dispatches SET state='dispatch_started' WHERE id=:id"),
                            {"id": pending.id})
        session.rollback()
        with pytest.raises(DBAPIError, match="snapshot is immutable"):
            session.execute(text("UPDATE writing_skill_dispatches SET route_snapshot=route_snapshot - 'scope', fence=fence+1 WHERE id=:id"),
                            {"id": pending.id})
        session.rollback()
