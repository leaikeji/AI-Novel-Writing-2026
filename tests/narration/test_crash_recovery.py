from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.engine import Engine, make_url
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
    MediaAsset,
)
from backend.narration import jobs
from backend.narration.contracts import (
    LOCAL_OWNER_ID,
    LOCAL_WORKSPACE_ID,
    NarrationRequestScope,
)
from backend.narration.jobs import JobFenceError
from backend.narration.media import (
    MediaNotEligible,
    ReferenceRoots,
    begin_gc_deletion,
    evaluate_gc,
    mark_gc_candidate,
)
from backend.narration.storage import NarrationStorage


NOW = datetime(2026, 8, 26, 13, 0, tzinfo=UTC)
SCOPE = NarrationRequestScope.fixed_local()
EXPECTED_DATABASE = "ai_novel_world_2026_tts_test"
EXPECTED_USERNAME = "tts_test"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
EXPECTED_KIND_REGISTRY = {
    "narration.segment_render": "moss-nano",
    "narration.export": "cpu-transcode",
    "narration.voice_generate": "voice-generator",
    "narration.analyze": "cpu-analysis",
    "narration.voice_preview": "moss-nano",
}
EXPECTED_RESOURCE_POLICIES = {
    "moss-nano": (True, "moss-nano:inference", 1),
    "voice-generator": (True, "voice-generator:generation", 1),
    "cpu-transcode": (False, None, 2),
    "cpu-analysis": (False, None, 2),
}


def _create_job_schema(engine: Engine) -> None:
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


def _seed_execution_catalog(session: Session, *, epoch_id: UUID) -> None:
    for resource_class, (requires_fence, exact_key, concurrency) in (
        EXPECTED_RESOURCE_POLICIES.items()
    ):
        session.add(
            BackgroundResourceClassPolicy(
                resource_class=resource_class,
                requires_publish_fence=requires_fence,
                exact_resource_key=exact_key,
                max_concurrency=concurrency,
                version=1,
                created_actor="t1-g-sqlite-seed",
                created_at=NOW,
            )
        )
    for resource_class, keys in (
        ("moss-nano", ("moss-nano:inference",)),
        ("voice-generator", ("voice-generator:generation",)),
        ("cpu-transcode", ("cpu-transcode:0", "cpu-transcode:1")),
        ("cpu-analysis", ("cpu-analysis:0", "cpu-analysis:1")),
    ):
        for slot_number, resource_key in enumerate(keys):
            session.add(
                BackgroundResourceClassSlot(
                    resource_class=resource_class,
                    slot_number=slot_number,
                    resource_key=resource_key,
                    enabled=True,
                    created_at=NOW,
                )
            )
    for job_kind, resource_class in EXPECTED_KIND_REGISTRY.items():
        session.add(
            BackgroundJobKindPolicy(
                job_kind=job_kind,
                resource_class=resource_class,
                version=1,
                created_actor="t1-g-sqlite-seed",
                created_at=NOW,
            )
        )
    session.add(
        BackgroundExecutorEpoch(
            id=epoch_id,
            executor_key="narration-worker",
            generation=1,
            state="active",
            activated_at=NOW,
            activated_actor="t1-g-sqlite-seed",
            revoked_at=None,
            revoked_actor=None,
            revoked_reason_code=None,
        )
    )
    session.commit()


@pytest.fixture
def sqlite_job_engine(tmp_path: Path) -> tuple[Engine, UUID]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'jobs.sqlite3'}")
    _create_job_schema(engine)
    epoch_id = uuid4()
    with Session(engine, expire_on_commit=False) as session:
        _seed_execution_catalog(session, epoch_id=epoch_id)
    try:
        yield engine, epoch_id
    finally:
        engine.dispose()


def _enqueue(
    session: Session,
    *,
    key: str,
    resource_class: str = "cpu-analysis",
    now: datetime = NOW,
    max_attempts: int = 3,
) -> jobs.EnqueueResult:
    return jobs.enqueue_job(
        session,
        scope=SCOPE,
        job_kind="test.t1g.integration",
        input_hash="a" * 64,
        idempotency_key=key,
        resource_class=resource_class,
        max_attempts=max_attempts,
        test_only_now=now,
    )


def _claim(
    session: Session,
    *,
    owner: str,
    resource_class: str,
    now: datetime,
    lease_seconds: int = 1,
) -> jobs.JobLease:
    lease = jobs.claim_next_job(
        session,
        scope=SCOPE,
        lease_owner=owner,
        resource_classes=(resource_class,),
        lease_seconds=lease_seconds,
        test_only_now=now,
    )
    assert lease is not None
    assert lease.resource_fence is not None
    assert lease.executor_epoch_id is not None
    return lease


def _revoke_epoch(
    session: Session,
    *,
    old_epoch_id: UUID,
    now: datetime,
) -> None:
    old = session.get(BackgroundExecutorEpoch, old_epoch_id)
    assert old is not None and old.state == "active"
    old.state = "revoked"
    old.revoked_at = now
    old.revoked_actor = "t1-g-lifecycle"
    old.revoked_reason_code = "PLUGIN_UPGRADE"
    session.commit()


def test_crash_before_claim_commit_replays_once_without_attempt_or_slot_leak(
    sqlite_job_engine: tuple[Engine, UUID],
) -> None:
    engine, _epoch_id = sqlite_job_engine
    key = f"crash-replay-{uuid4()}"
    with Session(engine, expire_on_commit=False) as producer:
        created = _enqueue(producer, key=key, resource_class="moss-nano")
        producer.commit()

    with Session(engine, expire_on_commit=False) as crashed_worker:
        lease = _claim(
            crashed_worker,
            owner="worker-before-crash",
            resource_class="moss-nano",
            now=NOW,
            lease_seconds=30,
        )
        assert lease.fence.job_id == created.job_id
        assert crashed_worker.scalar(
            select(func.count()).select_from(BackgroundJobAttempt)
        ) == 1
        crashed_worker.rollback()

    with Session(engine, expire_on_commit=False) as restarted:
        job = restarted.get(BackgroundJob, created.job_id)
        assert job is not None and job.state == "queued" and job.attempt_count == 0
        assert restarted.scalar(
            select(func.count()).select_from(BackgroundJobAttempt)
        ) == 0
        assert restarted.scalar(
            select(func.count()).select_from(BackgroundResourceLock)
        ) == 0
        replay = _enqueue(
            restarted,
            key=key,
            resource_class="moss-nano",
            now=NOW + timedelta(seconds=1),
        )
        assert replay == jobs.EnqueueResult(job_id=created.job_id, created=False)
        recovered = _claim(
            restarted,
            owner="worker-after-restart",
            resource_class="moss-nano",
            now=NOW + timedelta(seconds=1),
            lease_seconds=30,
        )
        jobs.fail_attempt(
            restarted,
            scope=SCOPE,
            fence=recovered.fence,
            classification="non_retryable",
            error_code="INJECTED_FAILURE",
            test_only_now=NOW + timedelta(seconds=2),
        )
        restarted.commit()
        assert restarted.scalar(select(func.count()).select_from(BackgroundJob)) == 1
        assert restarted.scalar(
            select(func.count()).select_from(BackgroundJobAttempt)
        ) == 1
        resource = restarted.get(
            BackgroundResourceLock,
            recovered.resource_fence.resource_key,  # type: ignore[union-attr]
        )
        assert resource is not None
        assert resource.lease_token != recovered.resource_fence.lease_token  # type: ignore[union-attr]


def test_restart_reconciles_expired_lease_and_rejects_old_fence(
    sqlite_job_engine: tuple[Engine, UUID],
) -> None:
    engine, _epoch_id = sqlite_job_engine
    with Session(engine, expire_on_commit=False) as first_process:
        created = _enqueue(
            first_process,
            key=f"expired-{uuid4()}",
            resource_class="cpu-analysis",
            max_attempts=2,
        )
        first_process.commit()
        first = _claim(
            first_process,
            owner="crashed-worker",
            resource_class="cpu-analysis",
            now=NOW,
            lease_seconds=1,
        )
        first_process.commit()

    with Session(engine, expire_on_commit=False) as supervisor_after_restart:
        reconciled = jobs.reconcile_expired_attempts(
            supervisor_after_restart,
            scope=SCOPE,
            test_only_now=NOW + timedelta(seconds=2),
        )
        assert len(reconciled) == 1
        assert reconciled[0].job_id == created.job_id
        assert reconciled[0].resulting_state == "retry_wait"
        supervisor_after_restart.commit()
        failed_attempt = supervisor_after_restart.get(
            BackgroundJobAttempt,
            first.fence.attempt_id,
        )
        job = supervisor_after_restart.get(BackgroundJob, created.job_id)
        assert failed_attempt is not None and failed_attempt.error_code == "LEASE_EXPIRED"
        assert job is not None and job.next_retry_at is not None
        retry_at = job.next_retry_at.replace(tzinfo=UTC)
        jobs.promote_due_retries(
            supervisor_after_restart,
            scope=SCOPE,
            test_only_now=retry_at,
        )
        second = _claim(
            supervisor_after_restart,
            owner="replacement-worker",
            resource_class="cpu-analysis",
            now=retry_at,
            lease_seconds=30,
        )
        assert second.fence.lease_generation == 2
        with pytest.raises(JobFenceError):
            jobs.complete_attempt(
                supervisor_after_restart,
                scope=SCOPE,
                fence=first.fence,
                actual_result_digest="b" * 64,
                test_only_now=retry_at + timedelta(seconds=1),
            )
        jobs.fail_attempt(
            supervisor_after_restart,
            scope=SCOPE,
            fence=second.fence,
            classification="non_retryable",
            error_code="RECOVERY_PROBE_DONE",
            test_only_now=retry_at + timedelta(seconds=1),
        )


def test_new_epoch_blocks_old_worker_and_stale_publication_context(
    sqlite_job_engine: tuple[Engine, UUID],
) -> None:
    engine, epoch_id = sqlite_job_engine
    with Session(engine, expire_on_commit=False) as worker:
        _enqueue(
            worker,
            key=f"epoch-{uuid4()}",
            resource_class="moss-nano",
        )
        worker.commit()
        old_lease = _claim(
            worker,
            owner="old-epoch-worker",
            resource_class="moss-nano",
            now=NOW,
            lease_seconds=1,
        )
        worker.commit()
        old_context = jobs.lock_result_publish_fences(
            worker,
            scope=SCOPE,
            job_fence=old_lease.fence,
            resource_fence=old_lease.resource_fence,  # type: ignore[arg-type]
            test_only_now=NOW,
        )
        worker.commit()

    with Session(engine, expire_on_commit=False) as lifecycle:
        _revoke_epoch(
            lifecycle,
            old_epoch_id=epoch_id,
            now=NOW + timedelta(milliseconds=100),
        )

    with Session(engine, expire_on_commit=False) as stale_worker:
        with pytest.raises(JobFenceError, match="another Session"):
            jobs.complete_attempt(
                stale_worker,
                scope=SCOPE,
                fence=old_lease.fence,
                publication_context=old_context,
                actual_result_digest="c" * 64,
                test_only_now=NOW + timedelta(milliseconds=200),
            )
        with pytest.raises(JobFenceError, match="revoked"):
            jobs.heartbeat_attempt(
                stale_worker,
                scope=SCOPE,
                fence=old_lease.fence,
                test_only_now=NOW + timedelta(milliseconds=200),
            )
        stale_worker.rollback()

    with Session(engine, expire_on_commit=False) as recovery:
        result = jobs.reconcile_expired_attempts(
            recovery,
            scope=SCOPE,
            test_only_now=NOW + timedelta(seconds=2),
        )
        assert len(result) == 1 and result[0].resulting_state == "failed"
        recovery.commit()
        released = recovery.get(
            BackgroundResourceLock,
            old_lease.resource_fence.resource_key,  # type: ignore[union-attr]
        )
        assert released is not None
        assert released.lease_token != old_lease.resource_fence.lease_token  # type: ignore[union-attr]


def _gc_storage(tmp_path: Path) -> NarrationStorage:
    models = tmp_path / "models"
    media = tmp_path / "media"
    models.mkdir(mode=0o750)
    media.mkdir(mode=0o750)
    models.chmod(0o750)
    media.chmod(0o750)
    return NarrationStorage(models_root=models, media_root=media)


def test_gc_never_marks_or_deletes_an_asset_with_a_live_job_reference(
    tmp_path: Path,
) -> None:
    digest = "e" * 64
    asset_id = uuid4()
    asset = MediaAsset(
        id=asset_id,
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        novel_id=uuid4(),
        kind="narration_preview",
        asset_class="preview",
        mime_type="audio/wav",
        byte_size=16,
        duration_ms=100,
        sample_rate=48_000,
        channels=2,
        storage_backend="local",
        state="ready",
        retention_policy="narration",
        checksum_algorithm="sha256",
        validation_json={"validated": True},
        verified_at=NOW - timedelta(days=30),
        gc_generation=0,
        storage_path=(
            f"assets/{asset_id.hex[:2]}/{asset_id.hex}/{digest}.wav"
        ),
        content_hash=digest,
        metadata_json={},
        created_at=NOW - timedelta(days=30),
    )
    active_roots = ReferenceRoots(active_job_assets=frozenset({asset.id}))
    decision = evaluate_gc(asset, active_roots, now=NOW)
    assert decision.action == "retain"
    assert decision.reason == "structured_reference:active_job_assets"
    with pytest.raises(MediaNotEligible, match="active_job_assets"):
        mark_gc_candidate(asset, active_roots, now=NOW)
    assert asset.gc_generation == 0 and asset.gc_marked_at is None

    generation = mark_gc_candidate(asset, ReferenceRoots(), now=NOW)
    assert generation == 1
    with pytest.raises(MediaNotEligible, match="active_job_assets"):
        begin_gc_deletion(
            asset,
            active_roots,
            expected_generation=generation,
            now=NOW + timedelta(days=8),
            storage=_gc_storage(tmp_path),
        )
    assert asset.state == "ready"


def _t1g_live_url() -> str:
    raw = os.environ.get("TTS_T1G_TEST_DATABASE_URL", "").strip()
    if not raw:
        pytest.skip(
            "TTS_T1G_TEST_DATABASE_URL is not configured; live T1-G PostgreSQL gate is pending"
        )
    parsed = make_url(raw)
    if not parsed.drivername.startswith("postgresql"):
        raise RuntimeError("TTS_T1G_TEST_DATABASE_URL must use PostgreSQL")
    if (
        parsed.database != EXPECTED_DATABASE
        or parsed.username != EXPECTED_USERNAME
        or parsed.host not in LOOPBACK_HOSTS
    ):
        raise RuntimeError(
            "T1-G tests require the exact loopback disposable TTS database identity"
        )
    production = os.environ.get("AI_NOVEL_DATABASE_URL", "").strip()
    if production:
        prod = make_url(production)
        if (parsed.host, parsed.port, parsed.database) == (
            prod.host,
            prod.port,
            prod.database,
        ):
            raise RuntimeError("T1-G test database must differ from production")
    return raw


@pytest.fixture(scope="module")
def t1g_pg_engine() -> Engine:
    engine = create_engine(_t1g_live_url(), pool_pre_ping=True)
    with engine.connect() as connection:
        version = connection.scalar(text("SHOW server_version"))
        head = connection.scalar(text("SELECT version_num FROM alembic_version"))
        if not isinstance(version, str) or not version.startswith("18."):
            raise RuntimeError("T1-G live gate requires PostgreSQL 18.x")
        if head != "20260826_0015":
            raise RuntimeError("T1-G live gate requires exact Alembic head 0015")
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def t1g_pg_session(t1g_pg_engine: Engine) -> Session:
    connection = t1g_pg_engine.connect()
    outer = connection.begin()
    session = Session(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        yield session
    finally:
        session.close()
        if outer.is_active:
            outer.rollback()
        connection.close()


def test_live_postgresql_catalog_matches_0012_frozen_execution_contract(
    t1g_pg_engine: Engine,
) -> None:
    with t1g_pg_engine.connect() as connection:
        table_names = set(inspect(connection).get_table_names())
        required_tables = {
            "background_jobs",
            "background_job_attempts",
            "background_executor_epochs",
            "background_resource_class_policies",
            "background_resource_class_slots",
            "background_job_kind_policies",
            "background_resource_locks",
            "narration_requests",
            "narration_settings_snapshots",
            "narration_script_versions",
            "narration_editions",
            "narration_segment_renders",
            "media_assets",
            "active_job_assets",
        }
        assert required_tables <= table_names
        attempt_columns = {
            column["name"]
            for column in inspect(connection).get_columns("background_job_attempts")
        }
        assert {
            "executor_epoch_id",
            "resource_key",
            "resource_lease_token",
            "resource_lease_generation",
            "actual_result_digest",
        } <= attempt_columns
        kind_rows = connection.execute(
            text(
                "SELECT job_kind, resource_class FROM background_job_kind_policies "
                "WHERE job_kind LIKE 'narration.%' ORDER BY job_kind"
            )
        ).all()
        assert dict(kind_rows) == EXPECTED_KIND_REGISTRY
        policy_rows = connection.execute(
            text(
                "SELECT resource_class, requires_publish_fence, exact_resource_key, "
                "max_concurrency FROM background_resource_class_policies "
                "ORDER BY resource_class"
            )
        ).all()
        assert {
            row.resource_class: (
                row.requires_publish_fence,
                row.exact_resource_key,
                row.max_concurrency,
            )
            for row in policy_rows
        } == EXPECTED_RESOURCE_POLICIES
        triggers = set(
            connection.scalars(
                text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")
            )
        )
        assert {
            "trg_background_job_registered_kind",
            "trg_background_executor_epoch_guard",
            "trg_background_attempt_execution_fence",
            "trg_background_job_execution_invariant",
            "trg_t1e_active_job_asset_ready",
            "trg_t1_media_gc_plan_reachability",
        } <= triggers


def test_live_postgresql_epoch_fence_recovery_and_slot_release_roll_back(
    t1g_pg_session: Session,
) -> None:
    session = t1g_pg_session
    key = f"t1-g-pg-{uuid4()}"
    created = jobs.enqueue_job(
        session,
        scope=SCOPE,
        job_kind="test.t1g.postgresql",
        input_hash="f" * 64,
        idempotency_key=key,
        resource_class="moss-nano",
        max_attempts=2,
    )
    lease = jobs.claim_next_job(
        session,
        scope=SCOPE,
        lease_owner=f"t1-g-old-{uuid4()}",
        resource_classes=("moss-nano",),
        lease_seconds=1,
    )
    assert lease is not None and lease.resource_fence is not None
    context = jobs.lock_result_publish_fences(
        session,
        scope=SCOPE,
        job_fence=lease.fence,
        resource_fence=lease.resource_fence,
    )
    current = session.scalar(
        select(BackgroundExecutorEpoch)
        .where(BackgroundExecutorEpoch.id == lease.executor_epoch_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert current is not None and current.state == "active"
    database_now = session.scalar(select(func.clock_timestamp()))
    assert isinstance(database_now, datetime)
    current.state = "revoked"
    current.revoked_at = database_now
    current.revoked_actor = "t1-g-lifecycle"
    current.revoked_reason_code = "PLUGIN_UPGRADE"
    replacement_epoch_id = uuid4()
    session.add(
        BackgroundExecutorEpoch(
            id=replacement_epoch_id,
            executor_key="narration-worker",
            generation=current.generation + 1,
            state="active",
            activated_at=database_now,
            activated_actor="t1-g-lifecycle",
            revoked_at=None,
            revoked_actor=None,
            revoked_reason_code=None,
        )
    )
    session.flush()
    with pytest.raises(JobFenceError, match="revoked"):
        jobs.complete_attempt(
            session,
            scope=SCOPE,
            fence=lease.fence,
            publication_context=context,
            actual_result_digest="1" * 64,
        )
    time.sleep(1.05)
    reconciled = jobs.reconcile_expired_attempts(session, scope=SCOPE)
    assert len(reconciled) == 1
    assert reconciled[0].job_id == created.job_id
    assert reconciled[0].resulting_state == "failed"
    old_job = session.get(BackgroundJob, created.job_id)
    old_attempt = session.get(BackgroundJobAttempt, lease.fence.attempt_id)
    assert old_job is not None and old_job.state == "failed"
    assert old_attempt is not None and old_attempt.error_code == "EXECUTOR_EPOCH_REVOKED"

    second = jobs.enqueue_job(
        session,
        scope=SCOPE,
        job_kind="test.t1g.postgresql",
        input_hash="2" * 64,
        idempotency_key=f"{key}-replacement",
        resource_class="moss-nano",
    )
    replacement = jobs.claim_next_job(
        session,
        scope=SCOPE,
        lease_owner=f"t1-g-new-{uuid4()}",
        resource_classes=("moss-nano",),
    )
    assert replacement is not None and replacement.resource_fence is not None
    assert replacement.fence.job_id == second.job_id
    assert replacement.executor_epoch_id == replacement_epoch_id
    assert replacement.resource_fence.lease_generation > lease.resource_fence.lease_generation
    jobs.fail_attempt(
        session,
        scope=SCOPE,
        fence=replacement.fence,
        classification="non_retryable",
        error_code="T1_G_ROLLBACK_PROBE_DONE",
    )
    session.flush()
    session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    session.execute(text("SET CONSTRAINTS ALL DEFERRED"))
