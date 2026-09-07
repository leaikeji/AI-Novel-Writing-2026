"""Explicit isolated PostgreSQL tests; never default to the application DB."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from backend.writing_skills.contracts import (
    ActionIdentity, FrozenRouteRequest, MethodPreferences, Scope,
    SkillInvocationPlanV1, SkillInjectionPacketV1, TaskModelInputProjectionV1,
)
from backend.writing_skills.persistence import ActionConflict, StaleFence, advance, claim_action
from backend.writing_skills.dispatch import prepare_action
from backend.writing_skills.api import method_status

OWNER = UUID("29cf94d9-a5c9-54ec-912c-5dfff8738c4c")
WORKSPACE = UUID("f0e2e632-bc99-52d2-9916-bb906aa4da6e")


@pytest.fixture(scope="module")
def engine():
    raw = os.getenv("S58_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("S58_TEST_DATABASE_URL not configured")
    url = make_url(raw)
    if url.host != "127.0.0.1" or url.database != "ai_novel_s58_test":
        pytest.fail("refusing non-isolated S58 database")
    result = create_engine(url)
    with result.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "20260905_0042"
    yield result
    result.dispose()


def request():
    scope = Scope(owner_id=OWNER, workspace_id=WORKSPACE, kind="creation_draft", scope_id=uuid4(), tab_id="s58-test")
    identity = ActionIdentity(owner_id=OWNER, workspace_id=WORKSPACE, entry="button", action_id=uuid4())
    projection = TaskModelInputProjectionV1(scope=scope, task="chapter_body", intent="write", source_version="1", visibility_key="test-only", sources=())
    return FrozenRouteRequest(identity=identity, projection=projection, preferences=MethodPreferences(), catalog_version="a"*64, provider_id="fake", model_id="fake")


def claim(engine, req, *, freeze=None, content="b"*64, authorize=None):
    with Session(engine) as session:
        return claim_action(session, req.identity, req.projection.scope, content,
                            authorize=authorize or (lambda s, scope: None),
                            freeze=freeze or (lambda: req))


def move(engine, current, target, **kw):
    with Session(engine) as session:
        return advance(session, current, target, **kw)


def packet(req):
    plan = SkillInvocationPlanV1(task=req.projection.task, primary_skill="prose-writing", source_hash=req.projection.source_hash, catalog_version=req.catalog_version, genre_state="unresolved", mechanism_state="unresolved")
    return SkillInjectionPacketV1(plan=plan, blocks=(), estimated_tokens=0)


def test_stable_action_checked_before_changed_config(engine):
    req = request()
    first = claim(engine, req)
    assert first.acquired
    def must_not_freeze():
        pytest.fail("duplicate froze current configuration")
    replay = claim(engine, req.model_copy(update={"model_id": "changed", "catalog_version": "c"*64}), freeze=must_not_freeze)
    assert not replay.acquired and replay.id == first.id
    assert replay.request.model_id == "fake"
    with pytest.raises(ActionConflict):
        claim(engine, req, content="d"*64)


def test_concurrent_claim_has_one_winner(engine):
    req = request()
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = list(pool.map(lambda _: claim(engine, req), range(16)))
    assert sum(c.acquired for c in claims) == 1
    assert len({c.id for c in claims}) == 1


def test_authorization_precedes_lookup_and_freeze(engine):
    req = request()
    claim(engine, req)
    def reject(session, scope):
        raise PermissionError("expired creation draft")
    with pytest.raises(PermissionError):
        claim(engine, req, authorize=reject)


def test_fence_and_unknown_never_replay(engine):
    req = request()
    first = claim(engine, req)
    routing = move(engine, first, "routing_started")
    with pytest.raises(StaleFence):
        move(engine, first, "route_ready")
    unknown = move(engine, routing, "unknown", error_code="remote_stop_unconfirmed")
    assert claim(engine, req).state == "unknown"
    for target in ("claimed", "routing_started", "route_ready", "dispatch_started"):
        with pytest.raises(ValueError):
            move(engine, unknown, target)


def test_packet_and_dispatch_are_committed_and_frozen(engine):
    req = request()
    ready = move(engine, claim(engine, req), "route_ready")
    assembled = move(engine, ready, "assembled", packet=packet(req))
    assert claim(engine, req).packet == packet(req)
    sending = move(engine, assembled, "dispatch_started")
    done = move(engine, sending, "dispatched", job_ref="generation:test")
    assert done.job_ref == "generation:test"
    with Session(engine) as session:
        with pytest.raises(DBAPIError):
            session.execute(text("UPDATE writing_skill_dispatches SET route_snapshot='{}'::jsonb WHERE id=:id"), {"id": done.id})
        session.rollback()
        with pytest.raises(DBAPIError):
            session.execute(text("UPDATE writing_skill_dispatches SET method_packet='{}'::jsonb WHERE id=:id"), {"id": done.id})


def test_packet_scope_mismatch_rejected(engine):
    req = request()
    ready = move(engine, claim(engine, req), "route_ready")
    with pytest.raises(ValueError):
        move(engine, ready, "assembled", packet=packet(request()))
    assert claim(engine, req).state == "route_ready"


def test_cancellation_fences_late_response(engine):
    req = request()
    pending = move(engine, claim(engine, req), "routing_started")
    cancelled = move(engine, pending, "cancelled")
    with pytest.raises(StaleFence):
        move(engine, pending, "route_ready")
    assert claim(engine, req).state == cancelled.state


def test_dispatch_cannot_claim_cancelled_without_confirmed_remote_stop(engine):
    req = request()
    ready = move(engine, claim(engine, req), "route_ready")
    assembled = move(engine, ready, "assembled", packet=packet(req))
    sending = move(engine, assembled, "dispatch_started")
    with pytest.raises(ValueError, match="confirmed remote stop"):
        move(engine, sending, "cancelled")
    assert claim(engine, req).state == "dispatch_started"
    cancelled = move(
        engine,
        sending,
        "cancelled",
        error_code="remote_stop_confirmed",
    )
    assert cancelled.state == "cancelled"


def test_fake_claim_identity_cannot_update_other_scope(engine):
    first = claim(engine, request())
    fake = replace(first, request=request().model_copy(update={"identity": ActionIdentity(owner_id=uuid4(), workspace_id=WORKSPACE, entry="button", action_id=uuid4())}))
    with pytest.raises(StaleFence):
        move(engine, fake, "route_ready")


def test_prepare_replay_and_status_are_content_free(engine):
    req = request()
    calls = []
    def compose(frozen):
        calls.append(frozen)
        return packet(frozen)
    kwargs = dict(session_factory=lambda: Session(engine), identity=req.identity,
                  scope=req.projection.scope, client_input_hash="b"*64,
                  authorize=lambda s, scope: None, freeze=lambda: req,
                  compose=compose, still_current=lambda r: True)
    first = prepare_action(**kwargs)
    replay = prepare_action(**kwargs)
    assert len(calls) == 1 and first.id == replay.id and first.state == "assembled"
    status = method_status(replay).model_dump()
    assert status["auxiliary_calls"] == 0 and not status["semantic_enabled"]
    assert "route_snapshot" not in status and "sources" not in status


def test_stale_source_stops_before_assembly(engine):
    req = request()
    result = prepare_action(session_factory=lambda: Session(engine), identity=req.identity,
                  scope=req.projection.scope, client_input_hash="b"*64,
                  authorize=lambda s, scope: None, freeze=lambda: req,
                  compose=packet, still_current=lambda r: False)
    assert result.state == "stale" and result.packet is None
