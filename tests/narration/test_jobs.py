from __future__ import annotations

import ast
import inspect
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from backend.models import (
    BackgroundExecutorEpoch,
    BackgroundJob,
    BackgroundJobAttempt,
    BackgroundJobKindPolicy,
    BackgroundManualRetryCommand,
    BackgroundResourceClassPolicy,
    BackgroundResourceClassSlot,
    BackgroundResourceLock,
)
from backend.narration import jobs, resource_locks
from backend.narration.contracts import NarrationRequestScope
from backend.narration.jobs import (
    JobFenceError,
    JobIdempotencyConflict,
    JobStateError,
    JobValidationError,
)
from backend.narration.resource_locks import (
    ResourceBusyError,
    ResourceFenceError,
)


UTC = timezone.utc
NOW = datetime(2026, 8, 26, 9, 0, tzinfo=UTC)
SCOPE = NarrationRequestScope.fixed_local()
EXECUTOR_EPOCH_ID = uuid4()


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    # SQLite is only the deterministic transaction fake; it does not prove PG
    # locks.  Keep production metadata untouched while translating the two
    # PostgreSQL-only CHECK expressions to narrow SQLite equivalents.
    for table in (
        BackgroundResourceClassPolicy.__table__,
        BackgroundResourceClassSlot.__table__,
        BackgroundJobKindPolicy.__table__,
        BackgroundExecutorEpoch.__table__,
        BackgroundJob.__table__,
        BackgroundManualRetryCommand.__table__,
        BackgroundJobAttempt.__table__,
        BackgroundResourceLock.__table__,
    ):
        if table in {
            BackgroundManualRetryCommand.__table__,
            BackgroundJobAttempt.__table__,
        }:
            ddl = str(CreateTable(table).compile(engine))
            ddl = ddl.replace(
                "actual_result_digest ~ '^[0-9a-f]{64}$'",
                "length(actual_result_digest) = 64",
            )
            ddl = ddl.replace("btrim(", "trim(")
            with engine.begin() as connection:
                connection.exec_driver_sql(ddl)
        else:
            table.create(engine)
    with Session(engine, expire_on_commit=False) as database_session:
        database_session.add_all(
            [
                BackgroundResourceClassPolicy(
                    resource_class="moss-nano",
                    requires_publish_fence=True,
                    exact_resource_key="moss-nano:inference",
                    max_concurrency=1,
                    version=1,
                    created_actor="test-seed",
                    created_at=NOW,
                ),
                BackgroundResourceClassPolicy(
                    resource_class="voice-generator",
                    requires_publish_fence=True,
                    exact_resource_key="voice-generator:generation",
                    max_concurrency=1,
                    version=1,
                    created_actor="test-seed",
                    created_at=NOW,
                ),
                BackgroundResourceClassPolicy(
                    resource_class="cpu-transcode",
                    requires_publish_fence=False,
                    exact_resource_key=None,
                    max_concurrency=2,
                    version=1,
                    created_actor="test-seed",
                    created_at=NOW,
                ),
                BackgroundResourceClassPolicy(
                    resource_class="cpu-analysis",
                    requires_publish_fence=False,
                    exact_resource_key=None,
                    max_concurrency=2,
                    version=1,
                    created_actor="test-seed",
                    created_at=NOW,
                ),
            ]
        )
        for resource_class, keys in (
            ("moss-nano", ("moss-nano:inference",)),
            ("voice-generator", ("voice-generator:generation",)),
            ("cpu-transcode", ("cpu-transcode:0", "cpu-transcode:1")),
            ("cpu-analysis", ("cpu-analysis:0", "cpu-analysis:1")),
        ):
            database_session.add_all(
                BackgroundResourceClassSlot(
                    resource_class=resource_class,
                    slot_number=number,
                    resource_key=resource_key,
                    enabled=True,
                    created_at=NOW,
                )
                for number, resource_key in enumerate(keys)
            )
        database_session.add_all(
            BackgroundJobKindPolicy(
                job_kind=job_kind,
                resource_class=resource_class,
                version=1,
                created_actor="test-seed",
                created_at=NOW,
            )
            for job_kind, resource_class in (
                ("narration.segment_render", "moss-nano"),
                ("narration.export", "cpu-transcode"),
                ("narration.voice_generate", "voice-generator"),
                ("narration.analyze", "cpu-analysis"),
                ("narration.voice_preview", "moss-nano"),
            )
        )
        database_session.add(
            BackgroundExecutorEpoch(
                id=EXECUTOR_EPOCH_ID,
                executor_key="narration-worker",
                generation=1,
                state="active",
                activated_at=NOW,
                activated_actor="test-seed",
                revoked_at=None,
                revoked_actor=None,
                revoked_reason_code=None,
            )
        )
        database_session.commit()
        yield database_session
    engine.dispose()


def _enqueue(
    session: Session,
    key: str,
    *,
    now: datetime = NOW,
    digest_character: str = "a",
    base_priority: int = 0,
    max_attempts: int = 3,
    resource_class: str = "cpu-analysis",
    interactive_priority: int | None = None,
    interactive_priority_expires_at: datetime | None = None,
    novel_id=None,  # type: ignore[no-untyped-def]
) -> jobs.EnqueueResult:
    result = jobs.enqueue_job(
        session,
        scope=SCOPE,
        job_kind="test.deterministic",
        input_hash=digest_character * 64,
        idempotency_key=key,
        resource_class=resource_class,
        base_priority=base_priority,
        max_attempts=max_attempts,
        interactive_priority=interactive_priority,
        interactive_priority_expires_at=interactive_priority_expires_at,
        novel_id=novel_id,
        test_only_now=now,
    )
    session.commit()
    return result


def _claim(
    session: Session,
    *,
    owner: str = "worker-a",
    now: datetime = NOW,
    lease_seconds: int = 120,
) -> jobs.JobLease:
    lease = jobs.claim_next_job(
        session,
        scope=SCOPE,
        lease_owner=owner,
        lease_seconds=lease_seconds,
        test_only_now=now,
    )
    assert lease is not None
    session.commit()
    return lease


def test_enqueue_is_idempotent_in_scope_and_conflicts_on_canonical_drift(
    session: Session,
) -> None:
    first = _enqueue(session, "same-key")
    replay = jobs.enqueue_job(
        session,
        scope=SCOPE,
        job_kind="test.deterministic",
        input_hash="a" * 64,
        idempotency_key="same-key",
        resource_class="cpu-analysis",
        test_only_now=NOW + timedelta(seconds=3),
    )
    assert replay == jobs.EnqueueResult(job_id=first.job_id, created=False)
    assert session.scalar(select(func.count()).select_from(BackgroundJob)) == 1

    with pytest.raises(JobIdempotencyConflict):
        jobs.enqueue_job(
            session,
            scope=SCOPE,
            job_kind="test.deterministic",
            input_hash="b" * 64,
            idempotency_key="same-key",
            resource_class="cpu-analysis",
            test_only_now=NOW + timedelta(seconds=2),
        )
    with pytest.raises(JobIdempotencyConflict):
        jobs.enqueue_job(
            session,
            scope=SCOPE,
            job_kind="test.deterministic",
            input_hash="a" * 64,
            idempotency_key="same-key",
            resource_class="cpu-transcode",
            test_only_now=NOW + timedelta(seconds=2),
        )


def test_enqueue_rejects_scope_override_bad_hash_and_unproven_render(
    session: Session,
) -> None:
    with pytest.raises(Exception, match="fixed server-side"):
        jobs.enqueue_job(
            session,
            scope=replace(SCOPE, owner_id=uuid4()),
            job_kind="test.deterministic",
            input_hash="a" * 64,
            idempotency_key="bad-scope",
            resource_class="cpu-analysis",
            test_only_now=NOW,
        )
    with pytest.raises(JobValidationError, match="SHA-256"):
        jobs.enqueue_job(
            session,
            scope=SCOPE,
            job_kind="test.deterministic",
            input_hash="A" * 64,
            idempotency_key="bad-hash",
            resource_class="cpu-analysis",
            test_only_now=NOW,
        )
    with pytest.raises(JobValidationError, match="request"):
        jobs.enqueue_job(
            session,
            scope=SCOPE,
            job_kind="narration.segment_render",
            input_hash="a" * 64,
            idempotency_key="render-without-request",
            resource_class="moss-nano",
            test_only_now=NOW,
        )


def test_postgresql_claim_sql_is_skip_locked_and_stably_ordered() -> None:
    novel_id = uuid4()
    document_id = uuid4()
    statement = jobs.build_claim_statement(
        scope=SCOPE,
        now=NOW,
        novel_ids=(novel_id,),
        document_ids=(document_id,),
        job_kinds=("narration.segment_render",),
    )
    compiled = str(statement.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE SKIP LOCKED" in compiled
    assert "background_jobs.attempt_count < background_jobs.max_attempts" in compiled
    assert "ORDER BY CASE" in compiled
    assert "EXTRACT(epoch FROM" in compiled
    assert "background_jobs.created_at ASC" in compiled
    assert "background_jobs.id ASC" in compiled
    assert "background_jobs.job_kind IN" in compiled
    assert "background_jobs.novel_id IN" in compiled
    assert "narration_requests.document_id IN" in compiled


def test_claim_statement_rejects_invalid_job_kind_filters() -> None:
    with pytest.raises(JobValidationError, match="job_kinds"):
        jobs.build_claim_statement(
            scope=SCOPE,
            now=NOW,
            job_kinds="narration.voice_preview",  # type: ignore[arg-type]
        )
    with pytest.raises(JobValidationError, match="cannot be empty"):
        jobs.build_claim_statement(scope=SCOPE, now=NOW, job_kinds=())

    with pytest.raises(JobValidationError, match="novel_ids"):
        jobs.build_claim_statement(scope=SCOPE, now=NOW, novel_ids=())
    with pytest.raises(JobValidationError, match="novel_id"):
        jobs.build_claim_statement(
            scope=SCOPE,
            now=NOW,
            novel_ids=("not-a-uuid",),  # type: ignore[arg-type]
        )
    with pytest.raises(JobValidationError, match="document_ids"):
        jobs.build_claim_statement(scope=SCOPE, now=NOW, document_ids=())
    with pytest.raises(JobValidationError, match="document_id"):
        jobs.build_claim_statement(
            scope=SCOPE,
            now=NOW,
            document_ids=("not-a-uuid",),  # type: ignore[arg-type]
        )


def test_validation_job_filters_leave_other_novel_queues_untouched(
    session: Session,
) -> None:
    target_novel = uuid4()
    other_novel = uuid4()
    target = _enqueue(
        session,
        "validation-target",
        novel_id=target_novel,
        resource_class="cpu-analysis",
    )
    other = _enqueue(
        session,
        "validation-other",
        novel_id=other_novel,
        resource_class="cpu-analysis",
        base_priority=jobs.MAX_PRIORITY,
        digest_character="b",
    )

    target_lease = jobs.claim_next_job(
        session,
        scope=SCOPE,
        lease_owner="validation-worker",
        novel_ids=(target_novel,),
        resource_classes=("cpu-analysis",),
        job_kinds=("test.deterministic",),
        lease_seconds=10,
        test_only_now=NOW,
    )
    assert target_lease is not None
    session.commit()
    assert target_lease.fence.job_id == target.job_id
    untouched = session.get(BackgroundJob, other.job_id)
    assert untouched is not None and untouched.state == "queued"

    jobs.fail_attempt(
        session,
        scope=SCOPE,
        fence=target_lease.fence,
        classification="retryable",
        error_code="VALIDATION_RETRY",
        test_only_now=NOW + timedelta(seconds=1),
    )
    other_lease = jobs.claim_next_job(
        session,
        scope=SCOPE,
        lease_owner="ordinary-worker",
        novel_ids=(other_novel,),
        resource_classes=("cpu-analysis",),
        job_kinds=("test.deterministic",),
        lease_seconds=10,
        test_only_now=NOW + timedelta(seconds=1),
    )
    assert other_lease is not None
    jobs.fail_attempt(
        session,
        scope=SCOPE,
        fence=other_lease.fence,
        classification="retryable",
        error_code="ORDINARY_RETRY",
        test_only_now=NOW + timedelta(seconds=2),
    )
    session.commit()

    promoted = jobs.promote_due_retries(
        session,
        scope=SCOPE,
        novel_ids=(target_novel,),
        resource_classes=("cpu-analysis",),
        job_kinds=("test.deterministic",),
        test_only_now=NOW + timedelta(minutes=1),
    )
    session.commit()
    assert promoted == (target.job_id,)
    assert session.get(BackgroundJob, target.job_id).state == "queued"
    assert session.get(BackgroundJob, other.job_id).state == "retry_wait"
    # Retire the already-proven promotion row so the expiry branch below has
    # one unambiguous target without acquiring another resource lease.
    session.get(BackgroundJob, target.job_id).state = "succeeded"
    session.commit()

    expiring_target = _enqueue(
        session,
        "validation-expiring-target",
        now=NOW + timedelta(minutes=2),
        novel_id=target_novel,
        resource_class="cpu-analysis",
        digest_character="c",
    )
    expiring_other = _enqueue(
        session,
        "validation-expiring-other",
        now=NOW + timedelta(minutes=2),
        novel_id=other_novel,
        resource_class="cpu-analysis",
        digest_character="d",
    )
    target_running = jobs.claim_next_job(
        session,
        scope=SCOPE,
        lease_owner="validation-worker",
        novel_ids=(target_novel,),
        resource_classes=("cpu-analysis",),
        job_kinds=("test.deterministic",),
        lease_seconds=1,
        test_only_now=NOW + timedelta(minutes=2),
    )
    other_running = jobs.claim_next_job(
        session,
        scope=SCOPE,
        lease_owner="ordinary-worker",
        novel_ids=(other_novel,),
        resource_classes=("cpu-analysis",),
        job_kinds=("test.deterministic",),
        lease_seconds=1,
        test_only_now=NOW + timedelta(minutes=2),
    )
    assert target_running is not None and other_running is not None
    session.commit()

    reconciled = jobs.reconcile_expired_attempts(
        session,
        scope=SCOPE,
        novel_ids=(target_novel,),
        resource_classes=("cpu-analysis",),
        job_kinds=("test.deterministic",),
        test_only_now=NOW + timedelta(minutes=2, seconds=2),
    )
    session.commit()
    assert tuple(item.job_id for item in reconciled) == (expiring_target.job_id,)
    assert session.get(BackgroundJob, expiring_target.job_id).state == "retry_wait"
    assert session.get(BackgroundJob, expiring_other.job_id).state == "running"


def test_fairness_aging_eventually_overtakes_fresh_bounded_priority() -> None:
    old_score = jobs.fairness_score(
        base_priority=0,
        created_at=NOW - timedelta(minutes=3),
        now=NOW,
    )
    fresh_score = jobs.fairness_score(
        base_priority=2,
        created_at=NOW,
        now=NOW,
    )
    assert old_score == 3
    assert fresh_score == 2
    assert old_score > fresh_score
    assert jobs.fairness_score(
        base_priority=0,
        interactive_priority=10,
        interactive_priority_expires_at=NOW + timedelta(seconds=1),
        created_at=NOW,
        now=NOW,
    ) == 10
    assert jobs.fairness_score(
        base_priority=0,
        interactive_priority=10,
        interactive_priority_expires_at=NOW,
        created_at=NOW,
        now=NOW,
    ) == 0


def test_two_workers_claim_distinct_jobs_and_sqlite_follows_same_fair_order(
    session: Session,
) -> None:
    old = _enqueue(
        session,
        "old-aged",
        now=NOW - timedelta(minutes=3),
        base_priority=0,
    )
    fresh = _enqueue(session, "fresh-priority", now=NOW, base_priority=2)

    first = _claim(session, owner="worker-a", now=NOW)
    second = _claim(session, owner="worker-b", now=NOW)
    assert first.fence.job_id == old.job_id
    assert second.fence.job_id == fresh.job_id
    assert first.fence.job_id != second.fence.job_id
    assert first.attempt_number == second.attempt_number == 1
    assert first.retry_kind == second.retry_kind == "initial"


def test_heartbeat_requires_current_live_fence_and_monotonic_progress(
    session: Session,
) -> None:
    _enqueue(session, "heartbeat")
    lease = _claim(session, now=NOW, lease_seconds=10)
    renewed = jobs.heartbeat_attempt(
        session,
        scope=SCOPE,
        fence=lease.fence,
        lease_seconds=20,
        progress_current=2,
        progress_total=5,
        test_only_now=NOW + timedelta(seconds=5),
    )
    session.commit()
    assert renewed.lease_until == NOW + timedelta(seconds=25)
    assert renewed.resource_fence is not None
    resource_row = session.get(
        BackgroundResourceLock,
        renewed.resource_fence.resource_key,
    )
    assert resource_row is not None
    assert resource_row.lease_until.replace(tzinfo=UTC) == renewed.lease_until

    with pytest.raises(JobFenceError, match="stale"):
        jobs.heartbeat_attempt(
            session,
            scope=SCOPE,
            fence=replace(lease.fence, lease_token=uuid4()),
            test_only_now=NOW + timedelta(seconds=6),
        )
    with pytest.raises(JobFenceError, match="stale"):
        jobs.heartbeat_attempt(
            session,
            scope=SCOPE,
            fence=replace(
                lease.fence,
                lease_generation=lease.fence.lease_generation + 1,
            ),
            test_only_now=NOW + timedelta(seconds=6),
        )
    with pytest.raises(JobValidationError, match="backwards"):
        jobs.heartbeat_attempt(
            session,
            scope=SCOPE,
            fence=lease.fence,
            progress_current=1,
            test_only_now=NOW + timedelta(seconds=6),
        )
    with pytest.raises(JobFenceError, match="expired"):
        jobs.heartbeat_attempt(
            session,
            scope=SCOPE,
            fence=lease.fence,
            test_only_now=NOW + timedelta(seconds=26),
        )


def test_complete_records_actual_digest_and_rejects_every_late_result(
    session: Session,
) -> None:
    enqueued = _enqueue(session, "complete")
    lease = _claim(session, now=NOW)
    jobs.lock_result_publish_fence(
        session,
        scope=SCOPE,
        fence=lease.fence,
        test_only_now=NOW + timedelta(seconds=3),
    )
    jobs.complete_attempt(
        session,
        scope=SCOPE,
        fence=lease.fence,
        actual_result_digest="d" * 64,
        test_only_now=NOW + timedelta(seconds=1),
    )
    session.commit()

    job = session.get(BackgroundJob, enqueued.job_id)
    attempt = session.get(BackgroundJobAttempt, lease.fence.attempt_id)
    assert lease.resource_fence is not None
    resource_row = session.get(
        BackgroundResourceLock,
        lease.resource_fence.resource_key,
    )
    assert job is not None and job.state == "succeeded"
    assert attempt is not None and attempt.actual_result_digest == "d" * 64
    assert attempt.completed_at is not None
    assert resource_row is not None
    assert resource_row.lease_token != lease.resource_fence.lease_token
    with pytest.raises(JobFenceError):
        jobs.complete_attempt(
            session,
            scope=SCOPE,
            fence=lease.fence,
            actual_result_digest="d" * 64,
            test_only_now=NOW + timedelta(seconds=2),
        )


def test_retry_backoff_is_capped_attempts_append_and_old_fence_is_rejected(
    session: Session,
) -> None:
    _enqueue(session, "automatic-retry", max_attempts=3)
    first = _claim(session, owner="worker-1", now=NOW)
    failure_one = jobs.fail_attempt(
        session,
        scope=SCOPE,
        fence=first.fence,
        classification="retryable",
        error_code="TEMPORARY_FAILURE",
        test_only_now=NOW + timedelta(seconds=1),
    )
    session.commit()
    assert failure_one.state == "retry_wait"
    assert failure_one.next_retry_at == NOW + timedelta(seconds=6)
    assert jobs.promote_due_retries(
        session, scope=SCOPE, test_only_now=NOW + timedelta(seconds=5)
    ) == ()
    assert jobs.promote_due_retries(
        session, scope=SCOPE, test_only_now=NOW + timedelta(seconds=6)
    )
    session.commit()

    second = _claim(session, owner="worker-2", now=NOW + timedelta(seconds=6))
    assert second.retry_kind == "automatic"
    assert second.attempt_number == second.fence.lease_generation == 2
    with pytest.raises(JobFenceError):
        jobs.complete_attempt(
            session,
            scope=SCOPE,
            fence=first.fence,
            actual_result_digest="e" * 64,
            test_only_now=NOW + timedelta(seconds=7),
        )
    failure_two = jobs.fail_attempt(
        session,
        scope=SCOPE,
        fence=second.fence,
        classification="retryable",
        error_code="TEMPORARY_FAILURE",
        test_only_now=NOW + timedelta(seconds=7),
    )
    session.commit()
    assert failure_two.next_retry_at == NOW + timedelta(seconds=17)
    jobs.promote_due_retries(
        session, scope=SCOPE, test_only_now=failure_two.next_retry_at
    )
    session.commit()
    third = _claim(session, owner="worker-3", now=failure_two.next_retry_at)
    exhausted = jobs.fail_attempt(
        session,
        scope=SCOPE,
        fence=third.fence,
        classification="retryable",
        error_code="TEMPORARY_FAILURE",
        test_only_now=failure_two.next_retry_at + timedelta(seconds=1),
    )
    session.commit()
    assert exhausted.state == "dead_letter"
    assert exhausted.next_retry_at is None
    attempts = session.scalars(
        select(BackgroundJobAttempt).order_by(BackgroundJobAttempt.attempt_number)
    ).all()
    assert [attempt.retry_kind for attempt in attempts] == [
        "initial",
        "automatic",
        "automatic",
    ]
    assert [attempt.attempt_number for attempt in attempts] == [1, 2, 3]


def test_manual_retry_command_is_idempotent_and_claims_beyond_automatic_max(
    session: Session,
) -> None:
    _enqueue(session, "manual", max_attempts=1)
    first = _claim(session, now=NOW)
    failed = jobs.fail_attempt(
        session,
        scope=SCOPE,
        fence=first.fence,
        classification="non_retryable",
        error_code="INVALID_INPUT",
        test_only_now=NOW + timedelta(seconds=1),
    )
    session.commit()
    assert failed.state == "failed"

    canonical = {
        "scope": SCOPE,
        "job_id": first.fence.job_id,
        "actor": "local-owner",
        "reason": "Author explicitly approved one diagnostic retry.",
        "idempotency_key": "manual-command-1",
    }
    created = jobs.manual_retry(
        session,
        **canonical,
        test_only_now=NOW + timedelta(seconds=2),
    )
    session.commit()
    replay = jobs.manual_retry(
        session,
        **canonical,
        test_only_now=NOW + timedelta(seconds=3),
    )
    session.commit()
    assert created.created is True
    assert replay == jobs.ManualRetryResult(
        command_id=created.command_id,
        job_id=first.fence.job_id,
        created=False,
    )
    queued = session.get(BackgroundJob, first.fence.job_id)
    assert queued is not None and queued.state == "queued"
    assert queued.attempt_count == queued.max_attempts == 1
    assert session.scalar(
        select(func.count()).select_from(BackgroundManualRetryCommand)
    ) == 1
    with pytest.raises(JobIdempotencyConflict, match="manual retry"):
        jobs.manual_retry(
            session,
            **{**canonical, "reason": "A different canonical reason."},
            test_only_now=NOW + timedelta(seconds=3),
        )
    session.rollback()

    second = _claim(session, owner="manual-worker", now=NOW + timedelta(seconds=4))
    assert second.retry_kind == "manual" and second.attempt_number == 2
    command = session.get(BackgroundManualRetryCommand, created.command_id)
    attempt = session.get(BackgroundJobAttempt, second.fence.attempt_id)
    assert command is not None and command.state == "claimed"
    assert command.claimed_attempt_id == second.fence.attempt_id
    assert attempt is not None
    assert attempt.manual_retry_command_id == command.id
    assert attempt.manual_actor == canonical["actor"]
    assert attempt.manual_reason == canonical["reason"]

    with pytest.raises(JobValidationError, match="non-empty"):
        jobs.manual_retry(
            session,
            scope=SCOPE,
            job_id=first.fence.job_id,
            actor="",
            reason="required",
            idempotency_key="bad-manual",
            test_only_now=NOW + timedelta(seconds=5),
        )


def test_cancel_queued_manual_retry_cancels_the_pending_command(
    session: Session,
) -> None:
    _enqueue(session, "manual-cancel", max_attempts=1)
    lease = _claim(session, now=NOW)
    jobs.fail_attempt(
        session,
        scope=SCOPE,
        fence=lease.fence,
        classification="non_retryable",
        error_code="NEEDS_REVIEW",
        test_only_now=NOW + timedelta(seconds=1),
    )
    command = jobs.manual_retry(
        session,
        scope=SCOPE,
        job_id=lease.fence.job_id,
        actor="local-owner",
        reason="Queue one reviewed retry.",
        idempotency_key="manual-cancel-command",
        test_only_now=NOW + timedelta(seconds=2),
    )
    cancelled = jobs.request_cancel(
        session,
        scope=SCOPE,
        job_id=lease.fence.job_id,
        actor="local-owner",
        reason_code="USER_CANCELLED",
        test_only_now=NOW + timedelta(seconds=3),
    )
    session.commit()
    row = session.get(BackgroundManualRetryCommand, command.command_id)
    assert cancelled.state == "cancelled"
    assert row is not None and row.state == "cancelled"
    assert row.cancelled_actor == "local-owner"
    assert row.cancelled_reason_code == "USER_CANCELLED"


def test_cancel_running_rejects_publish_then_requires_live_worker_ack(
    session: Session,
) -> None:
    _enqueue(session, "cancel-running")
    lease = _claim(session, now=NOW)
    requested = jobs.request_cancel(
        session,
        scope=SCOPE,
        job_id=lease.fence.job_id,
        actor="local-owner",
        reason_code="USER_CANCELLED",
        test_only_now=NOW + timedelta(seconds=1),
    )
    session.commit()
    assert requested.state == "cancel_requested" and requested.changed is True
    assert jobs.request_cancel(
        session,
        scope=SCOPE,
        job_id=lease.fence.job_id,
        actor="another-actor",
        reason_code="USER_CANCELLED",
        test_only_now=NOW + timedelta(seconds=2),
    ).changed is False
    with pytest.raises(JobFenceError):
        jobs.lock_result_publish_fence(
            session,
            scope=SCOPE,
            fence=lease.fence,
            test_only_now=NOW + timedelta(seconds=2),
        )
    jobs.acknowledge_cancel(
        session,
        scope=SCOPE,
        fence=lease.fence,
        test_only_now=NOW + timedelta(seconds=2),
    )
    session.commit()
    attempt = session.get(BackgroundJobAttempt, lease.fence.attempt_id)
    job = session.get(BackgroundJob, lease.fence.job_id)
    assert attempt is not None and attempt.error_classification == "cancelled"
    assert job is not None and job.state == "cancelled"
    with pytest.raises(JobFenceError):
        jobs.complete_attempt(
            session,
            scope=SCOPE,
            fence=lease.fence,
            actual_result_digest="f" * 64,
            test_only_now=NOW + timedelta(seconds=3),
        )


def test_cancel_queued_and_retry_wait_never_creates_an_extra_attempt(
    session: Session,
) -> None:
    queued = _enqueue(session, "cancel-queued")
    result = jobs.request_cancel(
        session,
        scope=SCOPE,
        job_id=queued.job_id,
        actor="local-owner",
        reason_code="USER_CANCELLED",
        test_only_now=NOW,
    )
    session.commit()
    assert result.state == "cancelled"
    assert session.scalar(select(func.count()).select_from(BackgroundJobAttempt)) == 0

    _enqueue(session, "cancel-backoff", digest_character="b")
    lease = _claim(session, now=NOW)
    failure = jobs.fail_attempt(
        session,
        scope=SCOPE,
        fence=lease.fence,
        classification="retryable",
        error_code="TEMPORARY_FAILURE",
        test_only_now=NOW + timedelta(seconds=1),
    )
    session.commit()
    assert failure.state == "retry_wait"
    cancelled = jobs.request_cancel(
        session,
        scope=SCOPE,
        job_id=lease.fence.job_id,
        actor="local-owner",
        reason_code="USER_CANCELLED",
        test_only_now=NOW + timedelta(seconds=2),
    )
    session.commit()
    assert cancelled.state == "cancelled"
    assert session.scalar(select(func.count()).select_from(BackgroundJobAttempt)) == 1


def test_expired_attempt_reconciliation_retries_deadletters_and_cancels(
    session: Session,
) -> None:
    retry_job = _enqueue(session, "expired-retry", max_attempts=2)
    retry_lease = _claim(session, now=NOW, lease_seconds=10)
    reconciled = jobs.reconcile_expired_attempts(
        session, scope=SCOPE, test_only_now=NOW + timedelta(seconds=11)
    )
    session.commit()
    assert reconciled == (
        jobs.ReconciledAttempt(
            job_id=retry_job.job_id,
            attempt_id=retry_lease.fence.attempt_id,
            resulting_state="retry_wait",
        ),
    )

    dead_job = _enqueue(
        session,
        "expired-dead",
        now=NOW + timedelta(seconds=20),
        digest_character="b",
        max_attempts=1,
    )
    dead_lease = _claim(session, now=NOW + timedelta(seconds=20), lease_seconds=10)
    dead = jobs.reconcile_expired_attempts(
        session, scope=SCOPE, test_only_now=NOW + timedelta(seconds=31)
    )
    session.commit()
    assert any(
        item.job_id == dead_job.job_id and item.resulting_state == "dead_letter"
        for item in dead
    )
    assert session.get(BackgroundJobAttempt, dead_lease.fence.attempt_id).error_code == (
        "LEASE_EXPIRED"
    )

    cancel_job = _enqueue(
        session,
        "expired-cancel",
        now=NOW + timedelta(seconds=40),
        digest_character="c",
    )
    cancel_lease = _claim(
        session, now=NOW + timedelta(seconds=40), lease_seconds=10
    )
    jobs.request_cancel(
        session,
        scope=SCOPE,
        job_id=cancel_job.job_id,
        actor="local-owner",
        reason_code="USER_CANCELLED",
        test_only_now=NOW + timedelta(seconds=41),
    )
    session.commit()
    cancelled = jobs.reconcile_expired_attempts(
        session, scope=SCOPE, test_only_now=NOW + timedelta(seconds=51)
    )
    session.commit()
    assert any(
        item.job_id == cancel_job.job_id and item.resulting_state == "cancelled"
        for item in cancelled
    )
    assert session.get(BackgroundJobAttempt, cancel_lease.fence.attempt_id).error_code == (
        "CANCELLED_LEASE_EXPIRED"
    )


def test_retry_delay_has_deterministic_exponential_cap() -> None:
    assert jobs.retry_delay_seconds(1) == 5
    assert jobs.retry_delay_seconds(2) == 10
    assert jobs.retry_delay_seconds(10, base_seconds=5, cap_seconds=60) == 60
    with pytest.raises(JobValidationError):
        jobs.retry_delay_seconds(True)


def test_resource_lock_competes_renews_releases_and_prevents_aba(
    session: Session,
) -> None:
    first = resource_locks.acquire_resource_lock(
        session,
        resource_key="moss-nano:inference",
        lease_owner="worker-a",
        lease_seconds=10,
        test_only_now=NOW,
    )
    session.commit()
    with pytest.raises(ResourceBusyError):
        resource_locks.acquire_resource_lock(
            session,
            resource_key="moss-nano:inference",
            lease_owner="worker-b",
            test_only_now=NOW + timedelta(seconds=1),
        )
    with pytest.raises(ResourceFenceError, match="stale"):
        resource_locks.renew_resource_lock(
            session,
            fence=replace(first.fence, lease_token=uuid4()),
            test_only_now=NOW + timedelta(seconds=1),
        )
    renewed = resource_locks.renew_resource_lock(
        session,
        fence=first.fence,
        lease_seconds=20,
        test_only_now=NOW + timedelta(seconds=5),
    )
    session.commit()
    assert renewed.lease_until == NOW + timedelta(seconds=25)
    resource_locks.lock_resource_publish_fence(
        session, fence=first.fence, test_only_now=NOW + timedelta(seconds=6)
    )
    resource_locks.release_resource_lock(
        session, fence=first.fence, test_only_now=NOW + timedelta(seconds=6)
    )
    session.commit()
    with pytest.raises(ResourceFenceError, match="stale"):
        resource_locks.renew_resource_lock(
            session, fence=first.fence, test_only_now=NOW + timedelta(seconds=6)
        )

    second = resource_locks.acquire_resource_lock(
        session,
        resource_key="moss-nano:inference",
        lease_owner="worker-b",
        test_only_now=NOW + timedelta(seconds=6),
    )
    session.commit()
    assert second.fence.lease_generation == first.fence.lease_generation + 1
    assert second.fence.lease_token != first.fence.lease_token
    with pytest.raises(ResourceFenceError, match="stale"):
        resource_locks.release_resource_lock(
            session, fence=first.fence, test_only_now=NOW + timedelta(seconds=7)
        )


def test_expired_resource_lease_can_be_taken_over_with_new_generation(
    session: Session,
) -> None:
    first = resource_locks.acquire_resource_lock(
        session,
        resource_key="cpu-analysis:0",
        lease_owner="worker-a",
        lease_seconds=1,
        test_only_now=NOW,
    )
    session.commit()
    second = resource_locks.acquire_resource_lock(
        session,
        resource_key="cpu-analysis:0",
        lease_owner="worker-b",
        lease_seconds=10,
        test_only_now=NOW + timedelta(seconds=1),
    )
    session.commit()
    assert second.fence.lease_generation == 2
    assert second.fence.lease_token != first.fence.lease_token
    with pytest.raises(ResourceFenceError):
        resource_locks.lock_resource_publish_fence(
            session, fence=first.fence, test_only_now=NOW + timedelta(seconds=2)
        )


def test_service_sources_have_no_commit_rollback_or_physical_delete_calls() -> None:
    for module in (jobs, resource_locks):
        tree = ast.parse(inspect.getsource(module))
        forbidden = [
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and node.attr in {"commit", "rollback", "delete"}
        ]
        assert forbidden == []
    assert not hasattr(jobs, "delete_job")
    assert not hasattr(jobs, "delete_attempt")


def test_public_now_and_integer_inputs_are_exact_and_fail_closed(
    session: Session,
) -> None:
    with pytest.raises(JobValidationError, match="timezone-aware"):
        _enqueue(session, "naive-time", now=NOW.replace(tzinfo=None))
    with pytest.raises(JobValidationError, match="exact integer"):
        jobs.enqueue_job(
            session,
            scope=SCOPE,
            job_kind="test.deterministic",
            input_hash="a" * 64,
            idempotency_key="bool-priority",
            resource_class="cpu-analysis",
            base_priority=True,
            test_only_now=NOW,
        )
    with pytest.raises(JobValidationError, match="interactive_priority requires"):
        jobs.enqueue_job(
            session,
            scope=SCOPE,
            job_kind="test.deterministic",
            input_hash="a" * 64,
            idempotency_key="missing-expiry",
            resource_class="cpu-analysis",
            interactive_priority=10,
            test_only_now=NOW,
        )
    with pytest.raises(JobValidationError, match="sequence"):
        jobs.build_claim_statement(
            scope=SCOPE,
            now=NOW,
            resource_classes="cpu-analysis",
        )


def test_idempotent_queued_replay_joins_boosts_without_weakening(
    session: Session,
) -> None:
    enqueued = _enqueue(session, "boost-join")
    canonical = {
        "scope": SCOPE,
        "job_kind": "test.deterministic",
        "input_hash": "a" * 64,
        "idempotency_key": "boost-join",
        "resource_class": "cpu-analysis",
    }
    jobs.enqueue_job(
        session,
        **canonical,
        interactive_priority=20,
        interactive_priority_expires_at=NOW + timedelta(seconds=30),
        test_only_now=NOW + timedelta(seconds=1),
    )
    session.commit()
    jobs.enqueue_job(
        session,
        **canonical,
        interactive_priority=10,
        interactive_priority_expires_at=NOW + timedelta(seconds=60),
        test_only_now=NOW + timedelta(seconds=2),
    )
    session.commit()
    jobs.enqueue_job(
        session,
        **canonical,
        interactive_priority=30,
        interactive_priority_expires_at=NOW + timedelta(seconds=40),
        test_only_now=NOW + timedelta(seconds=3),
    )
    session.commit()
    row = session.get(BackgroundJob, enqueued.job_id)
    assert row is not None
    assert row.interactive_priority == 30
    assert row.interactive_priority_expires_at.replace(tzinfo=UTC) == (
        NOW + timedelta(seconds=60)
    )

    # Once running, an idempotent prepare-range replay is a read only operation.
    _claim(session, now=NOW + timedelta(seconds=4))
    jobs.enqueue_job(
        session,
        **canonical,
        interactive_priority=40,
        interactive_priority_expires_at=NOW + timedelta(seconds=90),
        test_only_now=NOW + timedelta(seconds=5),
    )
    session.commit()
    row = session.get(BackgroundJob, enqueued.job_id)
    assert row is not None
    assert row.interactive_priority == 30


def test_interactive_boost_is_bounded_future_only_and_strictly_enhancing(
    session: Session,
) -> None:
    for priority, expiry, pattern in (
        (0, NOW + timedelta(seconds=30), "strictly exceed"),
        (10, NOW, "future"),
        (10, NOW + timedelta(minutes=6), "five-minute"),
    ):
        with pytest.raises(JobValidationError, match=pattern):
            jobs.enqueue_job(
                session,
                scope=SCOPE,
                job_kind="test.deterministic",
                input_hash="a" * 64,
                idempotency_key=f"bad-boost-{priority}-{expiry.minute}",
                resource_class="cpu-analysis",
                interactive_priority=priority,
                interactive_priority_expires_at=expiry,
                test_only_now=NOW,
            )


def test_job_identity_map_stale_terminal_state_is_refreshed_before_cancel(
    session: Session,
) -> None:
    enqueued = _enqueue(session, "stale-job")
    stale = session.get(BackgroundJob, enqueued.job_id)
    assert stale is not None and stale.state == "queued"
    session.commit()
    with Session(session.get_bind(), expire_on_commit=False) as other:
        result = jobs.request_cancel(
            other,
            scope=SCOPE,
            job_id=enqueued.job_id,
            actor="other-session",
            reason_code="USER_CANCELLED",
            test_only_now=NOW + timedelta(seconds=1),
        )
        assert result.changed is True
        other.commit()
    assert stale.state == "queued"
    replay = jobs.request_cancel(
        session,
        scope=SCOPE,
        job_id=enqueued.job_id,
        actor="stale-session",
        reason_code="USER_CANCELLED",
        test_only_now=NOW + timedelta(seconds=2),
    )
    assert replay.state == "cancelled" and replay.changed is False
    assert stale.state == "cancelled"


def test_attempt_identity_map_stale_completion_is_refreshed_and_rejected(
    session: Session,
) -> None:
    _enqueue(session, "stale-attempt")
    lease = _claim(session, now=NOW)
    stale_attempt = session.get(BackgroundJobAttempt, lease.fence.attempt_id)
    stale_job = session.get(BackgroundJob, lease.fence.job_id)
    assert stale_attempt is not None and stale_attempt.completed_at is None
    assert stale_job is not None and stale_job.state == "running"
    session.commit()
    with Session(session.get_bind(), expire_on_commit=False) as other:
        jobs.request_cancel(
            other,
            scope=SCOPE,
            job_id=lease.fence.job_id,
            actor="other-session",
            reason_code="USER_CANCELLED",
            test_only_now=NOW + timedelta(seconds=1),
        )
        jobs.acknowledge_cancel(
            other,
            scope=SCOPE,
            fence=lease.fence,
            test_only_now=NOW + timedelta(seconds=2),
        )
        other.commit()
    assert stale_attempt.completed_at is None and stale_job.state == "running"
    with pytest.raises(JobFenceError):
        jobs.complete_attempt(
            session,
            scope=SCOPE,
            fence=lease.fence,
            actual_result_digest="a" * 64,
            test_only_now=NOW + timedelta(seconds=3),
        )
    assert stale_attempt.completed_at is not None
    assert stale_job.state == "cancelled"


def test_resource_identity_map_stale_generation_is_refreshed_and_rejected(
    session: Session,
) -> None:
    first = resource_locks.acquire_resource_lock(
        session,
        resource_key="moss-nano:inference",
        lease_owner="worker-a",
        test_only_now=NOW,
    )
    session.commit()
    stale = session.get(BackgroundResourceLock, first.fence.resource_key)
    assert stale is not None and stale.lease_generation == 1
    session.commit()
    with Session(session.get_bind(), expire_on_commit=False) as other:
        resource_locks.release_resource_lock(
            other,
            fence=first.fence,
            test_only_now=NOW + timedelta(seconds=1),
        )
        second = resource_locks.acquire_resource_lock(
            other,
            resource_key=first.fence.resource_key,
            lease_owner="worker-b",
            test_only_now=NOW + timedelta(seconds=1),
        )
        other.commit()
    assert stale.lease_generation == 1
    with pytest.raises(ResourceFenceError, match="stale"):
        resource_locks.renew_resource_lock(
            session,
            fence=first.fence,
            test_only_now=NOW + timedelta(seconds=2),
        )
    assert stale.lease_generation == second.fence.lease_generation == 2


def test_heavy_publication_requires_combined_job_and_mapped_resource_fences(
    session: Session,
) -> None:
    _enqueue(session, "heavy", resource_class="moss-nano")
    job_lease = _claim(session, now=NOW)
    session.commit()
    assert job_lease.resource_fence is not None
    with pytest.raises(JobFenceError, match="require lock_result_publish_fences"):
        jobs.lock_result_publish_fence(
            session,
            scope=SCOPE,
            fence=job_lease.fence,
            test_only_now=NOW + timedelta(seconds=1),
        )
    wrong = replace(
        job_lease.resource_fence,
        resource_key="voice-generator:generation",
    )
    with pytest.raises(JobFenceError, match="attempt-recorded"):
        jobs.lock_result_publish_fences(
            session,
            scope=SCOPE,
            job_fence=job_lease.fence,
            resource_fence=wrong,
            test_only_now=NOW + timedelta(seconds=1),
        )
    context = jobs.lock_result_publish_fences(
        session,
        scope=SCOPE,
        job_fence=job_lease.fence,
        resource_fence=job_lease.resource_fence,
        test_only_now=NOW + timedelta(seconds=1),
    )
    jobs.complete_attempt(
        session,
        scope=SCOPE,
        fence=job_lease.fence,
        publication_context=context,
        actual_result_digest="b" * 64,
        test_only_now=NOW + timedelta(seconds=1),
    )
    session.commit()
    assert session.get(BackgroundJob, job_lease.fence.job_id).state == "succeeded"


def test_progress_is_logical_job_monotonic_across_automatic_attempts(
    session: Session,
) -> None:
    _enqueue(session, "progress-retry", max_attempts=2)
    first = _claim(session, now=NOW)
    jobs.heartbeat_attempt(
        session,
        scope=SCOPE,
        fence=first.fence,
        progress_current=2,
        progress_total=5,
        test_only_now=NOW + timedelta(seconds=1),
    )
    jobs.fail_attempt(
        session,
        scope=SCOPE,
        fence=first.fence,
        classification="retryable",
        error_code="TEMPORARY_FAILURE",
        test_only_now=NOW + timedelta(seconds=2),
    )
    session.commit()
    jobs.promote_due_retries(
        session,
        scope=SCOPE,
        test_only_now=NOW + timedelta(seconds=7),
    )
    session.commit()
    second = _claim(session, now=NOW + timedelta(seconds=7))
    with pytest.raises(JobValidationError, match="backwards"):
        jobs.heartbeat_attempt(
            session,
            scope=SCOPE,
            fence=second.fence,
            progress_current=1,
            test_only_now=NOW + timedelta(seconds=8),
        )
    jobs.heartbeat_attempt(
        session,
        scope=SCOPE,
        fence=second.fence,
        progress_current=3,
        test_only_now=NOW + timedelta(seconds=8),
    )


def test_combined_publication_context_cannot_cross_transaction_boundary(
    session: Session,
) -> None:
    _enqueue(session, "heavy-context", resource_class="moss-nano")
    job_lease = _claim(session, now=NOW)
    session.commit()
    assert job_lease.resource_fence is not None
    context = jobs.lock_result_publish_fences(
        session,
        scope=SCOPE,
        job_fence=job_lease.fence,
        resource_fence=job_lease.resource_fence,
        test_only_now=NOW + timedelta(seconds=1),
    )
    session.commit()
    with pytest.raises(JobFenceError, match="another transaction"):
        jobs.complete_attempt(
            session,
            scope=SCOPE,
            fence=job_lease.fence,
            publication_context=context,
            actual_result_digest="c" * 64,
            test_only_now=NOW + timedelta(seconds=2),
        )


def test_combined_publication_context_is_invalid_after_rollback(
    session: Session,
) -> None:
    _enqueue(session, "heavy-context-rollback", resource_class="moss-nano")
    job_lease = _claim(session, now=NOW)
    session.commit()
    assert job_lease.resource_fence is not None
    context = jobs.lock_result_publish_fences(
        session,
        scope=SCOPE,
        job_fence=job_lease.fence,
        resource_fence=job_lease.resource_fence,
        test_only_now=NOW + timedelta(seconds=1),
    )
    session.rollback()
    with pytest.raises(JobFenceError, match="another transaction"):
        jobs.complete_attempt(
            session,
            scope=SCOPE,
            fence=job_lease.fence,
            publication_context=context,
            actual_result_digest="c" * 64,
            test_only_now=NOW + timedelta(seconds=2),
        )


def test_combined_publication_context_is_invalid_after_close_or_new_session(
    session: Session,
) -> None:
    _enqueue(session, "heavy-context-close", resource_class="moss-nano")
    job_lease = _claim(session, now=NOW)
    session.commit()
    assert job_lease.resource_fence is not None
    context = jobs.lock_result_publish_fences(
        session,
        scope=SCOPE,
        job_fence=job_lease.fence,
        resource_fence=job_lease.resource_fence,
        test_only_now=NOW + timedelta(seconds=1),
    )
    session.close()
    with Session(session.get_bind(), expire_on_commit=False) as other:
        with pytest.raises(JobFenceError, match="another Session"):
            jobs.complete_attempt(
                other,
                scope=SCOPE,
                fence=job_lease.fence,
                publication_context=context,
                actual_result_digest="c" * 64,
                test_only_now=NOW + timedelta(seconds=2),
            )
    with pytest.raises(JobFenceError, match="another transaction"):
        jobs.complete_attempt(
            session,
            scope=SCOPE,
            fence=job_lease.fence,
            publication_context=context,
            actual_result_digest="c" * 64,
            test_only_now=NOW + timedelta(seconds=2),
        )


def test_unknown_narration_kind_and_registry_mapping_fail_closed(
    session: Session,
) -> None:
    with pytest.raises(JobValidationError, match="not registered"):
        jobs.enqueue_job(
            session,
            scope=SCOPE,
            job_kind="narration.unregistered",
            input_hash="a" * 64,
            idempotency_key="unknown-narration-kind",
            resource_class="cpu-analysis",
            test_only_now=NOW,
        )
    with pytest.raises(JobValidationError, match="not registered"):
        jobs.enqueue_job(
            session,
            scope=SCOPE,
            job_kind="narration.analyze",
            input_hash="a" * 64,
            idempotency_key="wrong-kind-class",
            resource_class="cpu-transcode",
            test_only_now=NOW,
        )
    accepted = jobs.enqueue_job(
        session,
        scope=SCOPE,
        job_kind="narration.analyze",
        input_hash="a" * 64,
        idempotency_key="registered-analyze",
        resource_class="cpu-analysis",
        test_only_now=NOW,
    )
    assert accepted.created is True

    # SQLite has no production registry trigger, so inject a malformed row to
    # prove claim itself also revalidates the migration-owned kind mapping.
    malformed_id = uuid4()
    session.add(
        BackgroundJob(
            id=malformed_id,
            owner_id=SCOPE.owner_id,
            workspace_id=SCOPE.workspace_id,
            novel_id=None,
            request_id=None,
            request_allows_render=None,
            job_kind="narration.unregistered",
            input_hash="b" * 64,
            idempotency_key="direct-unknown-narration-kind",
            resource_class="cpu-analysis",
            base_priority=jobs.MAX_PRIORITY,
            interactive_priority=None,
            interactive_priority_expires_at=None,
            state="queued",
            max_attempts=1,
            attempt_count=0,
            next_retry_at=None,
            cancel_requested_at=None,
            cancel_actor=None,
            cancel_reason_code=None,
            progress_current=0,
            progress_total=None,
            error_code=None,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    session.flush()
    with pytest.raises(JobValidationError, match="not registered"):
        jobs.claim_next_job(
            session,
            scope=SCOPE,
            lease_owner="fail-closed-worker",
            resource_classes=("cpu-analysis",),
            test_only_now=NOW + timedelta(seconds=1),
        )
    assert session.scalar(
        select(func.count())
        .select_from(BackgroundJobAttempt)
        .where(BackgroundJobAttempt.job_id == malformed_id)
    ) == 0


def test_claim_allocates_registered_slots_atomically_and_does_not_leak(
    session: Session,
) -> None:
    # A damaged/over-provisioned registry row must not raise concurrency above
    # the policy's authoritative max_concurrency=2.
    session.add(
        BackgroundResourceClassSlot(
            resource_class="cpu-analysis",
            slot_number=2,
            resource_key="cpu-analysis:out-of-policy",
            enabled=True,
            created_at=NOW,
        )
    )
    session.flush()
    first_job = _enqueue(session, "slot-first", now=NOW)
    second_job = _enqueue(
        session,
        "slot-second",
        now=NOW + timedelta(seconds=1),
        digest_character="b",
    )
    third_job = _enqueue(
        session,
        "slot-third",
        now=NOW + timedelta(seconds=2),
        digest_character="c",
    )
    first = _claim(session, owner="slot-worker-1", now=NOW + timedelta(seconds=2))
    second = _claim(session, owner="slot-worker-2", now=NOW + timedelta(seconds=2))
    assert first.resource_fence is not None and second.resource_fence is not None
    assert {first.resource_fence.resource_key, second.resource_fence.resource_key} == {
        "cpu-analysis:0",
        "cpu-analysis:1",
    }
    unavailable = jobs.claim_next_job(
        session,
        scope=SCOPE,
        lease_owner="slot-worker-3",
        resource_classes=("cpu-analysis",),
        test_only_now=NOW + timedelta(seconds=2),
    )
    assert unavailable is None
    session.commit()
    queued = session.get(BackgroundJob, third_job.job_id)
    assert queued is not None and queued.state == "queued" and queued.attempt_count == 0
    assert session.scalar(select(func.count()).select_from(BackgroundJobAttempt)) == 2

    jobs.fail_attempt(
        session,
        scope=SCOPE,
        fence=first.fence,
        classification="non_retryable",
        error_code="TEST_RELEASE",
        test_only_now=NOW + timedelta(seconds=3),
    )
    session.commit()
    third = _claim(session, owner="slot-worker-3", now=NOW + timedelta(seconds=3))
    assert third.fence.job_id == third_job.job_id
    assert third.resource_fence is not None
    assert third.resource_fence.resource_key == first.resource_fence.resource_key
    assert (
        third.resource_fence.lease_generation
        == first.resource_fence.lease_generation + 1
    )
    assert {first.fence.job_id, second.fence.job_id} == {
        first_job.job_id,
        second_job.job_id,
    }


def test_revoked_executor_epoch_rejects_worker_ops_then_reconciles_safely(
    session: Session,
) -> None:
    _enqueue(session, "revoked-epoch")
    lease = _claim(session, owner="epoch-1-worker", now=NOW, lease_seconds=1)
    assert lease.executor_epoch_id == EXECUTOR_EPOCH_ID
    assert lease.resource_fence is not None
    before_resource = session.get(
        BackgroundResourceLock,
        lease.resource_fence.resource_key,
    )
    assert before_resource is not None
    before_token = before_resource.lease_token
    epoch = session.get(BackgroundExecutorEpoch, EXECUTOR_EPOCH_ID)
    assert epoch is not None
    epoch.state = "revoked"
    epoch.revoked_at = NOW + timedelta(milliseconds=100)
    epoch.revoked_actor = "lifecycle-owner"
    epoch.revoked_reason_code = "PLUGIN_DISABLED"
    session.commit()

    for operation in (
        lambda: jobs.heartbeat_attempt(
            session,
            scope=SCOPE,
            fence=lease.fence,
            test_only_now=NOW + timedelta(milliseconds=500),
        ),
        lambda: jobs.fail_attempt(
            session,
            scope=SCOPE,
            fence=lease.fence,
            classification="non_retryable",
            error_code="OLD_WORKER",
            test_only_now=NOW + timedelta(milliseconds=500),
        ),
        lambda: jobs.complete_attempt(
            session,
            scope=SCOPE,
            fence=lease.fence,
            actual_result_digest="e" * 64,
            test_only_now=NOW + timedelta(milliseconds=500),
        ),
    ):
        with pytest.raises(JobFenceError, match="revoked"):
            operation()
        session.rollback()

    jobs.request_cancel(
        session,
        scope=SCOPE,
        job_id=lease.fence.job_id,
        actor="local-owner",
        reason_code="USER_CANCELLED",
        test_only_now=NOW + timedelta(milliseconds=600),
    )
    session.commit()
    with pytest.raises(JobFenceError, match="revoked"):
        jobs.acknowledge_cancel(
            session,
            scope=SCOPE,
            fence=lease.fence,
            test_only_now=NOW + timedelta(milliseconds=700),
        )
    session.rollback()

    reconciled = jobs.reconcile_expired_attempts(
        session,
        scope=SCOPE,
        test_only_now=NOW + timedelta(seconds=2),
    )
    session.commit()
    assert reconciled[0].resulting_state == "failed"
    attempt = session.get(BackgroundJobAttempt, lease.fence.attempt_id)
    job = session.get(BackgroundJob, lease.fence.job_id)
    released = session.get(
        BackgroundResourceLock,
        lease.resource_fence.resource_key,
    )
    assert attempt is not None
    assert attempt.error_classification == "security_failure"
    assert attempt.error_code == "EXECUTOR_EPOCH_REVOKED"
    assert job is not None and job.state == "failed"
    assert released is not None and released.lease_token != before_token


def test_publication_context_rejects_epoch_revoked_after_initial_check(
    session: Session,
) -> None:
    _enqueue(session, "context-revoked", resource_class="moss-nano")
    lease = _claim(session, owner="context-worker", now=NOW)
    assert lease.resource_fence is not None
    session.commit()
    context = jobs.lock_result_publish_fences(
        session,
        scope=SCOPE,
        job_fence=lease.fence,
        resource_fence=lease.resource_fence,
        test_only_now=NOW + timedelta(seconds=1),
    )
    epoch = session.get(BackgroundExecutorEpoch, EXECUTOR_EPOCH_ID)
    assert epoch is not None
    epoch.state = "revoked"
    epoch.revoked_at = NOW + timedelta(seconds=1)
    epoch.revoked_actor = "lifecycle-owner"
    epoch.revoked_reason_code = "PLUGIN_UPGRADE"
    session.flush()
    with pytest.raises(JobFenceError, match="revoked"):
        jobs.complete_attempt(
            session,
            scope=SCOPE,
            fence=lease.fence,
            publication_context=context,
            actual_result_digest="f" * 64,
            test_only_now=NOW + timedelta(seconds=2),
        )


def test_mutating_apis_expose_only_explicit_sqlite_test_clock_hook() -> None:
    for function in (
        jobs.enqueue_job,
        jobs.claim_next_job,
        jobs.heartbeat_attempt,
        jobs.lock_result_publish_fence,
        jobs.lock_result_publish_fences,
        jobs.complete_attempt,
        jobs.fail_attempt,
        jobs.promote_due_retries,
        jobs.request_cancel,
        jobs.acknowledge_cancel,
        jobs.reconcile_expired_attempts,
        jobs.manual_retry,
        resource_locks.acquire_resource_lock,
        resource_locks.renew_resource_lock,
        resource_locks.release_resource_lock,
        resource_locks.lock_resource_publish_fence,
    ):
        parameters = inspect.signature(function).parameters
        assert "now" not in parameters
        assert "test_only_now" in parameters


def test_claim_priority_aging_compiles_to_bigint_not_integer() -> None:
    compiled = str(
        jobs.build_claim_statement(scope=SCOPE, now=NOW).compile(
            dialect=postgresql.dialect()
        )
    )
    assert "AS BIGINT" in compiled
    assert "AS INTEGER" not in compiled
