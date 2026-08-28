from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

from backend.models import (
    BackgroundExecutorEpoch,
    BackgroundJob,
    BackgroundJobAttempt,
    BackgroundManualRetryCommand,
    BackgroundResourceLock,
)
from backend.narration import jobs, resource_locks
from backend.narration.contracts import NarrationRequestScope
from backend.narration.jobs import JobFenceError, JobValidationError
from backend.narration.resource_locks import ResourceFenceError


UTC = timezone.utc
SCOPE = NarrationRequestScope.fixed_local()
EXPECTED_DATABASE = "ai_novel_world_2026_tts_test"
EXPECTED_USERNAME = "tts_test"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _live_url() -> str:
    raw = os.environ.get("TTS_TEST_DATABASE_URL", "").strip()
    if not raw:
        pytest.skip(
            "TTS_TEST_DATABASE_URL is not configured; live PostgreSQL job gate is pending"
        )
    parsed = make_url(raw)
    if not parsed.drivername.startswith("postgresql"):
        raise RuntimeError("TTS_TEST_DATABASE_URL must use PostgreSQL")
    if (
        parsed.database != EXPECTED_DATABASE
        or parsed.username != EXPECTED_USERNAME
        or parsed.host not in LOOPBACK_HOSTS
    ):
        raise RuntimeError(
            "T1-C tests require the exact loopback disposable TTS database identity"
        )
    production = os.environ.get("AI_NOVEL_DATABASE_URL", "").strip()
    if production:
        prod = make_url(production)
        if (parsed.host, parsed.port, parsed.database) == (
            prod.host,
            prod.port,
            prod.database,
        ):
            raise RuntimeError("TTS job test database must differ from production")
    return raw


@pytest.fixture(scope="module")
def pg_engine() -> Engine:
    engine = create_engine(_live_url(), pool_pre_ping=True)
    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        required = {
            "background_jobs",
            "background_job_attempts",
            "background_manual_retry_commands",
            "background_executor_epochs",
            "background_resource_class_policies",
            "background_resource_class_slots",
            "background_job_kind_policies",
            "background_resource_locks",
        }
        if not required <= tables:
            raise RuntimeError("the disposable TTS database is not at 0015")
        version = connection.scalar(text("SHOW server_version"))
        head = connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert isinstance(version, str) and version.startswith("18.")
        assert head == "20260826_0015"
    try:
        yield engine
    finally:
        engine.dispose()


def _enqueue(
    engine: Engine,
    *,
    resource_class: str = "cpu-analysis",
    job_kind: str = "test.postgresql",
    key: str | None = None,
    max_attempts: int = 3,
    base_priority: int = 0,
    interactive_priority: int | None = None,
    interactive_priority_expires_at: datetime | None = None,
) -> jobs.EnqueueResult:
    with Session(engine, expire_on_commit=False) as session:
        result = jobs.enqueue_job(
            session,
            scope=SCOPE,
            job_kind=job_kind,
            input_hash="a" * 64,
            idempotency_key=key or f"t1-c-0012-pg-{uuid4()}",
            resource_class=resource_class,
            max_attempts=max_attempts,
            base_priority=base_priority,
            interactive_priority=interactive_priority,
            interactive_priority_expires_at=interactive_priority_expires_at,
        )
        session.commit()
        return result


def _claim(
    session: Session,
    *,
    resource_class: str = "cpu-analysis",
    owner: str,
    lease_seconds: int = 120,
) -> jobs.JobLease:
    lease = jobs.claim_next_job(
        session,
        scope=SCOPE,
        lease_owner=owner,
        resource_classes=(resource_class,),
        lease_seconds=lease_seconds,
    )
    assert lease is not None
    assert lease.executor_epoch_id is not None
    assert lease.resource_fence is not None
    return lease


def _fail_and_release(session: Session, lease: jobs.JobLease, code: str) -> None:
    jobs.fail_attempt(
        session,
        scope=SCOPE,
        fence=lease.fence,
        classification="non_retryable",
        error_code=code,
    )


def _rotate_active_epoch(
    session: Session, *, reason: str
) -> tuple[BackgroundExecutorEpoch, BackgroundExecutorEpoch]:
    current = session.scalar(
        select(BackgroundExecutorEpoch)
        .where(
            BackgroundExecutorEpoch.executor_key == "narration-worker",
            BackgroundExecutorEpoch.state == "active",
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert current is not None
    db_now = session.scalar(select(func.clock_timestamp()))
    current.state = "revoked"
    current.revoked_at = db_now
    current.revoked_actor = "test:lifecycle-owner"
    current.revoked_reason_code = reason
    session.flush()
    replacement = BackgroundExecutorEpoch(
        id=uuid4(),
        executor_key="narration-worker",
        generation=current.generation + 1,
        state="active",
        activated_at=db_now,
        activated_actor="test:lifecycle-owner",
        revoked_at=None,
        revoked_actor=None,
        revoked_reason_code=None,
    )
    session.add(replacement)
    return current, replacement


def test_live_postgresql_0012_and_production_clock_hook_rejected(
    pg_engine: Engine,
) -> None:
    created = _enqueue(pg_engine)
    with Session(pg_engine, expire_on_commit=False) as session:
        lease = _claim(session, owner=f"clock-worker-{uuid4()}")
        session.commit()
        before = session.get(BackgroundJobAttempt, lease.fence.attempt_id)
        assert before is not None
        old_until = before.lease_until
        with pytest.raises(JobValidationError, match="SQLite test path"):
            jobs.heartbeat_attempt(
                session,
                scope=SCOPE,
                fence=lease.fence,
                test_only_now=datetime(2000, 1, 1, tzinfo=UTC),
            )
        session.rollback()
        session.expire_all()
        after = session.get(BackgroundJobAttempt, lease.fence.attempt_id)
        assert after is not None and after.lease_until == old_until
        assert created.job_id == lease.fence.job_id
        _fail_and_release(session, lease, "CLOCK_TEST_DONE")
        session.commit()


def test_two_open_sessions_claim_distinct_jobs_and_distinct_slots(
    pg_engine: Engine,
) -> None:
    first_job = _enqueue(pg_engine)
    second_job = _enqueue(pg_engine)
    second_done = threading.Event()
    second_result: list[jobs.JobLease] = []
    errors: list[BaseException] = []
    with Session(pg_engine, expire_on_commit=False) as first_session:
        first = _claim(first_session, owner=f"concurrent-a-{uuid4()}")

        def claim_second() -> None:
            try:
                with Session(pg_engine, expire_on_commit=False) as second_session:
                    second = _claim(
                        second_session,
                        owner=f"concurrent-b-{uuid4()}",
                    )
                    second_result.append(second)
                    second_done.set()
                    _fail_and_release(second_session, second, "CONCURRENT_B_DONE")
                    second_session.commit()
            except BaseException as error:  # pragma: no cover - surfaced below
                errors.append(error)
                second_done.set()

        worker = threading.Thread(target=claim_second, daemon=True)
        worker.start()
        assert second_done.wait(timeout=3), "second claim was globally serialized"
        assert errors == [] and len(second_result) == 1
        second = second_result[0]
        assert {first.fence.job_id, second.fence.job_id} == {
            first_job.job_id,
            second_job.job_id,
        }
        assert first.resource_fence is not None and second.resource_fence is not None
        assert first.resource_fence.resource_key != second.resource_fence.resource_key
        _fail_and_release(first_session, first, "CONCURRENT_A_DONE")
        first_session.commit()
        worker.join(timeout=3)
        assert not worker.is_alive() and errors == []


def test_postgresql_lock_wait_crosses_expiry_and_reconcile_releases(
    pg_engine: Engine,
) -> None:
    # One automatic attempt keeps cleanup terminal after reconciliation.
    _enqueue(pg_engine, max_attempts=1)
    with Session(pg_engine, expire_on_commit=False) as claimant:
        lease = _claim(
            claimant,
            owner=f"expiry-worker-{uuid4()}",
            lease_seconds=1,
        )
        claimant.commit()

    locked = threading.Event()
    release = threading.Event()
    blocker_error: list[BaseException] = []

    def hold_job_lock() -> None:
        try:
            with Session(pg_engine) as blocker:
                blocker.scalar(
                    select(BackgroundJob)
                    .where(BackgroundJob.id == lease.fence.job_id)
                    .with_for_update()
                )
                locked.set()
                release.wait(timeout=5)
                blocker.commit()
        except BaseException as error:  # pragma: no cover - surfaced below
            blocker_error.append(error)
            locked.set()

    blocker = threading.Thread(target=hold_job_lock, daemon=True)
    blocker.start()
    assert locked.wait(timeout=5)

    def release_after_expiry() -> None:
        time.sleep(1.25)
        release.set()

    timer = threading.Thread(target=release_after_expiry, daemon=True)
    timer.start()
    started = time.monotonic()
    with Session(pg_engine) as contender:
        with pytest.raises(JobFenceError, match="expired"):
            jobs.complete_attempt(
                contender,
                scope=SCOPE,
                fence=lease.fence,
                actual_result_digest="b" * 64,
            )
        contender.rollback()
    elapsed = time.monotonic() - started
    blocker.join(timeout=5)
    timer.join(timeout=5)
    assert not blocker.is_alive() and blocker_error == [] and elapsed >= 1.0
    with Session(pg_engine) as recovery:
        result = jobs.reconcile_expired_attempts(recovery, scope=SCOPE)
        assert result and result[0].attempt_id == lease.fence.attempt_id
        recovery.commit()


def test_manual_retry_concurrent_replay_and_claim_beyond_max(
    pg_engine: Engine,
) -> None:
    _enqueue(pg_engine, max_attempts=1)
    with Session(pg_engine, expire_on_commit=False) as session:
        first = _claim(session, owner=f"manual-first-{uuid4()}")
        _fail_and_release(session, first, "MANUAL_FIRST_FAILED")
        session.commit()

    retry_key = f"manual-retry-{uuid4()}"
    barrier = threading.Barrier(2)
    results: list[jobs.ManualRetryResult] = []
    errors: list[BaseException] = []

    def request_retry() -> None:
        try:
            with Session(pg_engine, expire_on_commit=False) as session:
                barrier.wait(timeout=5)
                result = jobs.manual_retry(
                    session,
                    scope=SCOPE,
                    job_id=first.fence.job_id,
                    actor="local-owner",
                    reason="Author approved one retry after inspecting the failure.",
                    idempotency_key=retry_key,
                )
                session.commit()
                results.append(result)
        except BaseException as error:  # pragma: no cover - surfaced below
            errors.append(error)

    threads = [threading.Thread(target=request_retry, daemon=True) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert all(not thread.is_alive() for thread in threads)
    assert errors == [] and len(results) == 2
    assert {result.created for result in results} == {True, False}
    assert len({result.command_id for result in results}) == 1

    with Session(pg_engine, expire_on_commit=False) as session:
        commands = session.scalars(
            select(BackgroundManualRetryCommand).where(
                BackgroundManualRetryCommand.job_id == first.fence.job_id
            )
        ).all()
        assert len(commands) == 1 and commands[0].state == "pending"
        manual = _claim(session, owner=f"manual-second-{uuid4()}")
        assert manual.fence.job_id == first.fence.job_id
        assert manual.retry_kind == "manual" and manual.attempt_number == 2
        session.commit()
        session.expire_all()
        command = session.get(BackgroundManualRetryCommand, commands[0].id)
        attempt = session.get(BackgroundJobAttempt, manual.fence.attempt_id)
        assert command is not None and command.state == "claimed"
        assert command.claimed_attempt_id == manual.fence.attempt_id
        assert attempt is not None and attempt.manual_retry_command_id == command.id
        _fail_and_release(session, manual, "MANUAL_SECOND_DONE")
        session.commit()


def test_epoch_revoke_wins_race_and_old_attempt_cannot_mutate(
    pg_engine: Engine,
) -> None:
    _enqueue(pg_engine)
    with Session(pg_engine, expire_on_commit=False) as claimant:
        lease = _claim(
            claimant,
            owner=f"epoch-worker-{uuid4()}",
            lease_seconds=1,
        )
        claimant.commit()

    worker_started = threading.Event()
    worker_done = threading.Event()
    worker_errors: list[BaseException] = []
    with Session(pg_engine, expire_on_commit=False) as lifecycle:
        current = lifecycle.scalar(
            select(BackgroundExecutorEpoch)
            .where(BackgroundExecutorEpoch.id == lease.executor_epoch_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        assert current is not None and current.state == "active"

        def old_heartbeat() -> None:
            try:
                with Session(pg_engine) as worker:
                    worker_started.set()
                    jobs.heartbeat_attempt(worker, scope=SCOPE, fence=lease.fence)
                    worker.commit()
            except BaseException as error:
                worker_errors.append(error)
            finally:
                worker_done.set()

        thread = threading.Thread(target=old_heartbeat, daemon=True)
        thread.start()
        assert worker_started.wait(timeout=3)
        time.sleep(0.2)
        old, replacement = _rotate_active_epoch(lifecycle, reason="PLUGIN_UPGRADE")
        assert old.id == current.id
        lifecycle.commit()
        assert worker_done.wait(timeout=3)
        thread.join(timeout=3)
        assert not thread.is_alive()
        assert len(worker_errors) == 1
        assert isinstance(worker_errors[0], JobFenceError)
        assert "revoked" in str(worker_errors[0])
        assert replacement.state == "active"

    time.sleep(1.05)
    with Session(pg_engine) as recovery:
        result = jobs.reconcile_expired_attempts(recovery, scope=SCOPE)
        assert result and result[0].resulting_state == "failed"
        recovery.commit()


def test_slot_contention_returns_none_without_attempt_or_resource_leak(
    pg_engine: Engine,
) -> None:
    first_job = _enqueue(pg_engine, base_priority=30)
    second_job = _enqueue(pg_engine, base_priority=20)
    third_job = _enqueue(pg_engine, base_priority=10)
    with Session(pg_engine, expire_on_commit=False) as session:
        first = _claim(session, owner=f"slot-a-{uuid4()}")
        session.commit()
        second = _claim(session, owner=f"slot-b-{uuid4()}")
        session.commit()
        unavailable = jobs.claim_next_job(
            session,
            scope=SCOPE,
            lease_owner=f"slot-c-{uuid4()}",
            resource_classes=("cpu-analysis",),
        )
        assert unavailable is None
        session.commit()
        third_row = session.get(BackgroundJob, third_job.job_id)
        assert third_row is not None
        assert third_row.state == "queued" and third_row.attempt_count == 0
        assert session.scalar(
            select(func.count())
            .select_from(BackgroundJobAttempt)
            .where(BackgroundJobAttempt.job_id == third_job.job_id)
        ) == 0
        _fail_and_release(session, first, "SLOT_A_DONE")
        session.commit()
        third = _claim(session, owner=f"slot-c-{uuid4()}")
        assert third.fence.job_id == third_job.job_id
        assert first.resource_fence is not None and third.resource_fence is not None
        assert third.resource_fence.resource_key == first.resource_fence.resource_key
        assert (
            third.resource_fence.lease_generation
            == first.resource_fence.lease_generation + 1
        )
        _fail_and_release(session, second, "SLOT_B_DONE")
        _fail_and_release(session, third, "SLOT_C_DONE")
        session.commit()
        assert {first.fence.job_id, second.fence.job_id} == {
            first_job.job_id,
            second_job.job_id,
        }


def test_stale_identity_cancel_ack_releases_recorded_resource(
    pg_engine: Engine,
) -> None:
    enqueued = _enqueue(pg_engine)
    with Session(pg_engine, expire_on_commit=False) as stale_session:
        lease = _claim(stale_session, owner=f"stale-worker-{uuid4()}")
        stale_session.commit()
        stale_job = stale_session.get(BackgroundJob, enqueued.job_id)
        stale_attempt = stale_session.get(
            BackgroundJobAttempt,
            lease.fence.attempt_id,
        )
        stale_resource = stale_session.get(
            BackgroundResourceLock,
            lease.resource_fence.resource_key,
        )
        assert stale_job is not None and stale_attempt is not None
        assert stale_resource is not None
        old_resource_token = stale_resource.lease_token
        stale_session.commit()
        with Session(pg_engine, expire_on_commit=False) as other:
            jobs.request_cancel(
                other,
                scope=SCOPE,
                job_id=enqueued.job_id,
                actor="other-session",
                reason_code="USER_CANCELLED",
            )
            jobs.acknowledge_cancel(other, scope=SCOPE, fence=lease.fence)
            other.commit()
        with pytest.raises(JobFenceError):
            jobs.complete_attempt(
                stale_session,
                scope=SCOPE,
                fence=lease.fence,
                actual_result_digest="c" * 64,
            )
        stale_session.rollback()
        stale_session.expire_all()
        released = stale_session.get(
            BackgroundResourceLock,
            lease.resource_fence.resource_key,
        )
        assert released is not None and released.lease_token != old_resource_token


def test_resource_release_takeover_has_no_aba_on_registered_slot(
    pg_engine: Engine,
) -> None:
    key = "voice-generator:generation"
    with Session(pg_engine, expire_on_commit=False) as session:
        first = resource_locks.acquire_resource_lock(
            session,
            resource_key=key,
            lease_owner=f"resource-a-{uuid4()}",
        )
        session.commit()
        resource_locks.release_resource_lock(session, fence=first.fence)
        second = resource_locks.acquire_resource_lock(
            session,
            resource_key=key,
            lease_owner=f"resource-b-{uuid4()}",
        )
        session.commit()
        assert second.fence.lease_generation == first.fence.lease_generation + 1
        for operation in (
            resource_locks.renew_resource_lock,
            resource_locks.release_resource_lock,
            resource_locks.lock_resource_publish_fence,
        ):
            with pytest.raises(ResourceFenceError, match="stale"):
                operation(session, fence=first.fence)
            session.rollback()
        resource_locks.release_resource_lock(session, fence=second.fence)
        session.commit()


def test_concurrent_idempotent_boosts_join_monotonically(
    pg_engine: Engine,
) -> None:
    key = f"t1-c-0012-boost-{uuid4()}"
    created = _enqueue(pg_engine, key=key)
    with pg_engine.connect() as connection:
        db_now = connection.scalar(text("SELECT clock_timestamp()"))
    first_done = threading.Event()
    allow_first_commit = threading.Event()
    errors: list[BaseException] = []

    def first_boost() -> None:
        try:
            with Session(pg_engine) as session:
                jobs.enqueue_job(
                    session,
                    scope=SCOPE,
                    job_kind="test.postgresql",
                    input_hash="a" * 64,
                    idempotency_key=key,
                    resource_class="cpu-analysis",
                    interactive_priority=20,
                    interactive_priority_expires_at=db_now + timedelta(seconds=30),
                )
                first_done.set()
                allow_first_commit.wait(timeout=5)
                session.commit()
        except BaseException as error:  # pragma: no cover - surfaced below
            errors.append(error)
            first_done.set()

    worker = threading.Thread(target=first_boost, daemon=True)
    worker.start()
    assert first_done.wait(timeout=5)

    def unblock_first() -> None:
        time.sleep(0.2)
        allow_first_commit.set()

    timer = threading.Thread(target=unblock_first, daemon=True)
    timer.start()
    with Session(pg_engine) as second:
        jobs.enqueue_job(
            second,
            scope=SCOPE,
            job_kind="test.postgresql",
            input_hash="a" * 64,
            idempotency_key=key,
            resource_class="cpu-analysis",
            interactive_priority=30,
            interactive_priority_expires_at=db_now + timedelta(seconds=20),
        )
        second.commit()
    worker.join(timeout=5)
    timer.join(timeout=5)
    assert not worker.is_alive() and errors == []
    with Session(pg_engine) as verification:
        row = verification.get(BackgroundJob, created.job_id)
        assert row is not None and row.interactive_priority == 30
        assert row.interactive_priority_expires_at == db_now + timedelta(seconds=30)
        jobs.request_cancel(
            verification,
            scope=SCOPE,
            job_id=created.job_id,
            actor="test-cleanup",
            reason_code="TEST_COMPLETED",
        )
        verification.commit()


def test_heavy_publication_uses_attempt_fence_and_context_is_one_transaction(
    pg_engine: Engine,
) -> None:
    created = _enqueue(
        pg_engine,
        resource_class="moss-nano",
        job_kind="test.postgresql.heavy",
    )
    with Session(pg_engine, expire_on_commit=False) as session:
        lease = _claim(
            session,
            resource_class="moss-nano",
            owner=f"heavy-worker-{uuid4()}",
        )
        session.commit()
        assert lease.resource_fence is not None
        with pytest.raises(JobFenceError, match="combined publication context"):
            jobs.complete_attempt(
                session,
                scope=SCOPE,
                fence=lease.fence,
                actual_result_digest="d" * 64,
            )
        session.rollback()
        old_context = jobs.lock_result_publish_fences(
            session,
            scope=SCOPE,
            job_fence=lease.fence,
            resource_fence=lease.resource_fence,
        )
        session.commit()
        with pytest.raises(JobFenceError, match="another transaction"):
            jobs.complete_attempt(
                session,
                scope=SCOPE,
                fence=lease.fence,
                publication_context=old_context,
                actual_result_digest="d" * 64,
            )
        session.rollback()
        context = jobs.lock_result_publish_fences(
            session,
            scope=SCOPE,
            job_fence=lease.fence,
            resource_fence=lease.resource_fence,
        )
        jobs.complete_attempt(
            session,
            scope=SCOPE,
            fence=lease.fence,
            publication_context=context,
            actual_result_digest="d" * 64,
        )
        session.commit()
        assert session.get(BackgroundJob, created.job_id).state == "succeeded"
        with pytest.raises(ResourceFenceError, match="stale"):
            resource_locks.lock_resource_publish_fence(
                session,
                fence=lease.resource_fence,
            )
