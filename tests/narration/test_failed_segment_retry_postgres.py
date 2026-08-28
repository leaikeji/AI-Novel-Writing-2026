"""PostgreSQL 18 integration gate for failed-segment manual retry.

The module is inert unless ``TTS_TEST_DATABASE_URL`` identifies the exact
loopback disposable TTS test database.  Each test runs on an externally owned
transaction and commits service savepoints, then rolls the outer transaction
back so no fixture data survives.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Connection, Engine, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import TextClause

from backend.models import (
    BackgroundJob,
    BackgroundManualRetryCommand,
    NarrationEdition,
    NarrationEditionSegment,
    NarrationEditionState,
    NarrationManifest,
    NarrationRequest,
    NarrationSegment,
    NarrationSegmentRender,
)
from backend.narration.contracts import NarrationRequestScope
from backend.narration.editions import CreateEdition, EditionSegmentInput, create_edition
from backend.narration.failed_segment_retry import (
    RetryFailedSegmentsCommand,
    retry_failed_segments,
)
from backend.narration.jobs import claim_next_job, enqueue_job, fail_attempt
from backend.narration.manifest import (
    INITIAL_BUFFER_POLICY,
    ManifestFailure,
    ManifestSegmentInput,
    PublishManifest,
    append_manifest_revision,
)
from backend.narration.renders import (
    CreateRender,
    create_or_reuse_render,
    render_job_input_hash,
)
from backend.narration.requests import (
    CreateNarrationRequest,
    advance_request_state,
    create_request,
)
from backend.narration.script_versions import (
    CreateScriptDraft,
    approve_script_version,
    create_script_draft,
)
from backend.narration.services import NarrationCasConflict, SqlAlchemyNarrationStore
from backend.narration.settings import NarrationSettingsUpdate, update_settings
from backend.narration.snapshots import CreateSettingsSnapshot, create_settings_snapshot
from backend.narration.worker import SqlAlchemyNarrationWorkerRepository
from tests.narration.digest_fixtures import TEST_DIGEST_KEYRING
from tests.narration.test_domain_services import (
    NOW,
    SHA_A,
    SHA_B,
    SHA_C,
    _script_segments,
)
from tests.narration.test_foundation_integration import POSTPROCESS_FINGERPRINT
from tests.narration.test_publication_postgres import _seed_scope_foundation


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_DATABASE = "ai_novel_world_2026_tts_test"
EXPECTED_USERNAME = "tts_test"
EXPECTED_REVISION = "20260828_0024"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
SCOPE = NarrationRequestScope.fixed_local()
FAILURE_CODE = "NANO_AUDIO_INVALID"


def _repository_head() -> str:
    config = Config(str(ROOT / "alembic.ini"))
    heads = ScriptDirectory.from_config(config).get_heads()
    if heads != [EXPECTED_REVISION]:
        raise RuntimeError(f"failed-segment gate requires head {EXPECTED_REVISION}")
    return heads[0]


def _live_url() -> str:
    raw = os.environ.get("TTS_TEST_DATABASE_URL", "").strip()
    if not raw:
        pytest.skip("TTS_TEST_DATABASE_URL is not configured")
    parsed = make_url(raw)
    if not parsed.drivername.startswith("postgresql"):
        raise RuntimeError("TTS_TEST_DATABASE_URL must use PostgreSQL")
    if (
        parsed.database != EXPECTED_DATABASE
        or parsed.username != EXPECTED_USERNAME
        or parsed.host not in LOOPBACK_HOSTS
    ):
        raise RuntimeError(
            "failed-segment tests require the exact loopback disposable TTS database"
        )
    production = os.environ.get("AI_NOVEL_DATABASE_URL", "").strip()
    if production:
        live = make_url(production)
        if (parsed.host, parsed.port, parsed.database) == (
            live.host,
            live.port,
            live.database,
        ):
            raise RuntimeError("failed-segment test database must differ from production")
    return raw


@pytest.fixture(scope="module")
def failed_retry_pg_engine() -> Engine:
    engine = create_engine(_live_url(), pool_pre_ping=True)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT current_database()")) == EXPECTED_DATABASE
        assert connection.scalar(text("SELECT current_user")) == EXPECTED_USERNAME
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            _repository_head()
        )
        server_version = connection.scalar(text("SHOW server_version"))
        assert isinstance(server_version, str) and server_version.startswith("18.")
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def failed_retry_pg_connection(failed_retry_pg_engine: Engine) -> Connection:
    connection = failed_retry_pg_engine.connect()
    outer = connection.begin()
    try:
        yield connection
    finally:
        if outer.is_active:
            outer.rollback()
        connection.close()


@pytest.fixture
def failed_retry_pg_session(failed_retry_pg_connection: Connection) -> Session:
    with Session(
        bind=failed_retry_pg_connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    ) as session:
        yield session


@dataclass(frozen=True, slots=True)
class RetryCase:
    novel_id: UUID
    request_id: UUID
    edition_id: UUID
    segment_ids: tuple[UUID, ...]
    edition_segment_ids: tuple[UUID, ...]
    render_ids: tuple[UUID, ...]
    job_ids: tuple[UUID, ...]
    request_version: int


def _assert_deferred_constraints(session: Session) -> None:
    """Force every deferred guard, then restore service-compatible ordering."""

    session.flush()
    session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    session.execute(text("SET CONSTRAINTS ALL DEFERRED"))


def _seed_retry_case(session: Session, *, full_failure: bool) -> RetryCase:
    store, novel, document, revision, profile, voice = _seed_scope_foundation(session)
    settings = update_settings(
        store,
        NarrationSettingsUpdate(
            novel_id=novel.id,
            script_review_policy="blockers_only",
            analysis_mode="local_rules_only",
            settings_json={"language": "zh-CN"},
            expected_version=0,
        ),
    )
    snapshot = create_settings_snapshot(
        store,
        CreateSettingsSnapshot(
            novel_id=novel.id,
            settings_version=settings.version,
        ),
    )
    request = create_request(
        store,
        CreateNarrationRequest(
            novel_id=novel.id,
            document_id=document.id,
            source_revision_id=revision.id,
            source_content_hash=revision.content_hash,
            intent="create",
            idempotency_key=f"failed-retry-request-{uuid4()}",
            settings_fingerprint=snapshot.fingerprint,
            explicit_generation_intent_at=NOW,
            explicit_generation_actor="failed-retry-owner",
        ),
    )
    script = create_script_draft(
        store,
        CreateScriptDraft(
            novel_id=novel.id,
            document_id=document.id,
            revision_id=revision.id,
            content_hash=revision.content_hash,
            settings_fingerprint=snapshot.fingerprint,
            analyzer_fingerprint=SHA_A,
            rules_fingerprint=SHA_B,
            idempotency_key=f"failed-retry-script-{uuid4()}",
            effective_policy="blockers_only",
            segments=_script_segments(),
        ),
    )
    request = advance_request_state(
        store,
        request.id,
        expected_version=request.version,
        new_state="analyzing",
        novel_id=novel.id,
        actor="failed-retry-analyzer",
    )
    # Mirror the production analyzer's server-owned review-pointer bind before
    # approval.  PostgreSQL deliberately rejects a queued request that merely
    # has an approved version elsewhere but does not point at that exact
    # candidate with the request CAS advanced.
    request.review_script_id = script.script_id
    request.current_review_version_id = script.id
    request.version += 1
    request.updated_at = NOW
    store.flush()
    script = approve_script_version(
        store,
        script.id,
        request_id=request.id,
        actor_type="system",
        actor_id="failed-retry-rules",
    )
    request = advance_request_state(
        store,
        request.id,
        expected_version=request.version,
        new_state="analyzed",
        novel_id=novel.id,
        actor="failed-retry-analyzer",
    )
    request = advance_request_state(
        store,
        request.id,
        expected_version=request.version,
        new_state="queued",
        novel_id=novel.id,
        actor="failed-retry-orchestrator",
    )
    segments = store.find_all(
        NarrationSegment,
        script_version_id=script.id,
        order_by=("ordinal",),
    )
    edition = create_edition(
        store,
        CreateEdition(
            novel_id=novel.id,
            document_id=document.id,
            request_id=request.id,
            script_version_id=script.id,
            settings_snapshot_id=snapshot.id,
            tts_fingerprint=SHA_A,
            tokenizer_fingerprint=SHA_B,
            normalizer_fingerprint=SHA_C,
            postprocess_fingerprint=POSTPROCESS_FINGERPRINT,
            buffer_policy_version=INITIAL_BUFFER_POLICY.version,
            created_actor="failed-retry-owner",
            digest_keyring=TEST_DIGEST_KEYRING,
            segments=tuple(
                EditionSegmentInput(
                    segment_id=segment.id,
                    ordinal=segment.ordinal,
                    profile_id=profile.id,
                    voice_version_id=voice.id,
                    resolution_json={"source": "narrator"},
                )
                for segment in segments
            ),
        ),
    )
    rows = store.find_all(
        NarrationEditionSegment,
        edition_id=edition.id,
        order_by=("ordinal",),
    )
    jobs: list[BackgroundJob] = []
    renders: list[NarrationSegmentRender] = []
    target_rows = rows if full_failure else rows[:1]
    for row in target_rows:
        enqueued = enqueue_job(
            session,
            scope=SCOPE,
            job_kind="narration.segment_render",
            input_hash=render_job_input_hash(
                edition_segment_id=row.id,
                render_fingerprint=row.render_fingerprint,
            ),
            idempotency_key=f"failed-retry-job-{uuid4()}",
            resource_class="moss-nano",
            novel_id=novel.id,
            request_id=request.id,
        )
        render, reused = create_or_reuse_render(
            store,
            CreateRender(
                edition_segment_id=row.id,
                digest_keyring=TEST_DIGEST_KEYRING,
                source_job_id=enqueued.job_id,
            ),
        )
        assert reused is False
        job = store.get(BackgroundJob, enqueued.job_id)
        assert job is not None
        jobs.append(job)
        renders.append(render)

    edition.state = "rendering"
    # Prove the queued request/Edition/job foundation before simulating worker
    # outcomes, then restore DEFERRED for multi-row job state transitions.
    _assert_deferred_constraints(session)
    request = advance_request_state(
        store,
        request.id,
        expected_version=request.version,
        new_state="rendering",
        novel_id=novel.id,
        actor="failed-retry-worker",
    )
    remaining_job_ids = {job.id for job in jobs}
    while remaining_job_ids:
        lease = claim_next_job(
            session,
            scope=SCOPE,
            lease_owner=f"failed-retry-worker-{uuid4()}",
            resource_classes=("moss-nano",),
            novel_ids=(novel.id,),
            job_kinds=("narration.segment_render",),
            lease_seconds=900,
        )
        assert lease is not None and lease.fence.job_id in remaining_job_ids
        failed = fail_attempt(
            session,
            scope=SCOPE,
            fence=lease.fence,
            classification="non_retryable",
            error_code=FAILURE_CODE,
        )
        assert failed.state == "failed"
        remaining_job_ids.remove(lease.fence.job_id)
    for index in range(len(target_rows)):
        renders[index].state = "failed"
        rows[index].render_state = "failed"
        rows[index].failure_code = FAILURE_CODE
    if full_failure:
        edition.state = "unavailable"
        edition.unavailable_reason = FAILURE_CODE
        request = advance_request_state(
            store,
            request.id,
            expected_version=request.version,
            new_state="failed",
            novel_id=novel.id,
            actor="failed-retry-worker",
            reason_code=FAILURE_CODE,
        )
    else:
        for row in rows[1:]:
            row.render_state = "ready"
        edition.state = "partial_ready"
        request = advance_request_state(
            store,
            request.id,
            expected_version=request.version,
            new_state="partial_ready",
            novel_id=novel.id,
            actor="failed-retry-worker",
        )
    # The outer fixture transaction is intentionally never committed.  Force
    # every final deferred invariant so rollback isolation cannot hide a
    # failure that production commit would reject.
    _assert_deferred_constraints(session)
    return RetryCase(
        novel_id=novel.id,
        request_id=request.id,
        edition_id=edition.id,
        segment_ids=tuple(row.segment_id for row in rows),
        edition_segment_ids=tuple(row.id for row in rows),
        render_ids=tuple(render.id for render in renders),
        job_ids=tuple(job.id for job in jobs),
        request_version=request.version,
    )


def _command(
    case: RetryCase,
    *segment_ids: UUID,
    manifest_revision: int | None = None,
    idempotency_key: str | None = None,
) -> RetryFailedSegmentsCommand:
    return RetryFailedSegmentsCommand(
        edition_id=case.edition_id,
        segment_ids=tuple(segment_ids),
        expected_request_version=case.request_version,
        expected_manifest_revision=manifest_revision,
        idempotency_key=idempotency_key or f"failed-retry-root-{uuid4()}",
        actor="local-owner",
    )


def test_partial_failure_manual_retry_commits_all_reverse_edges_atomically(
    failed_retry_pg_session: Session,
) -> None:
    session = failed_retry_pg_session
    with session.begin():
        case = _seed_retry_case(session, full_failure=False)
    command = _command(case, case.segment_ids[0])

    with session.begin():
        result = retry_failed_segments(session, command)
        _assert_deferred_constraints(session)

    session.expire_all()
    request = session.get(NarrationRequest, case.request_id)
    edition = session.get(NarrationEdition, case.edition_id)
    render = session.get(NarrationSegmentRender, case.render_ids[0])
    row = session.get(NarrationEditionSegment, case.edition_segment_ids[0])
    job = session.get(BackgroundJob, case.job_ids[0])
    assert result.replayed is False and result.request_version == case.request_version + 1
    assert request is not None and request.state == "partial_ready"
    assert edition is not None and edition.state == "partial_ready"
    assert render is not None and render.state == "pending"
    assert row is not None and row.render_state == "queued" and row.failure_code is None
    assert job is not None and job.state == "queued" and job.error_code is None
    assert session.scalar(
        select(func.count()).select_from(BackgroundManualRetryCommand).where(
            BackgroundManualRetryCommand.job_id == job.id,
            BackgroundManualRetryCommand.state == "pending",
        )
    ) == 1


def test_full_failure_retry_reopens_request_and_edition_only_with_proof(
    failed_retry_pg_session: Session,
) -> None:
    session = failed_retry_pg_session
    with session.begin():
        case = _seed_retry_case(session, full_failure=True)
    command = _command(case, *case.segment_ids)

    with session.begin():
        result = retry_failed_segments(session, command)
        _assert_deferred_constraints(session)

    session.expire_all()
    request = session.get(NarrationRequest, case.request_id)
    edition = session.get(NarrationEdition, case.edition_id)
    assert result.replayed is False
    assert request is not None and request.state == "queued"
    assert request.failure_code is None and request.completed_at is None
    assert edition is not None and edition.state == "rendering"
    assert edition.unavailable_reason is None
    assert set(
        session.scalars(
            select(NarrationSegmentRender.state).where(
                NarrationSegmentRender.id.in_(case.render_ids)
            )
        )
    ) == {"pending"}
    assert set(
        session.scalars(
            select(NarrationEditionSegment.render_state).where(
                NarrationEditionSegment.id.in_(case.edition_segment_ids)
            )
        )
    ) == {"queued"}


@pytest.mark.parametrize(
    ("row_kind", "statement"),
    [
        pytest.param(
            "request",
            text(
                "UPDATE narration_requests SET state='queued', failure_code=NULL, "
                "completed_at=NULL, version=version+1 WHERE id=:row_id"
            ),
            id="request-failed-to-queued",
        ),
        pytest.param(
            "edition",
            text(
                "UPDATE narration_editions SET state='rendering', "
                "unavailable_reason=NULL WHERE id=:row_id"
            ),
            id="edition-unavailable-to-rendering",
        ),
        pytest.param(
            "render",
            text(
                "UPDATE narration_segment_renders SET state='pending' WHERE id=:row_id"
            ),
            id="render-failed-to-pending",
        ),
        pytest.param(
            "segment",
            text(
                "UPDATE narration_edition_segments SET render_state='queued', "
                "failure_code=NULL WHERE id=:row_id"
            ),
            id="edition-segment-failed-to-queued",
        ),
    ],
)
def test_0024_four_reverse_edges_reject_missing_pending_command(
    failed_retry_pg_session: Session,
    row_kind: str,
    statement: TextClause,
) -> None:
    session = failed_retry_pg_session
    with session.begin():
        case = _seed_retry_case(session, full_failure=True)
    row_id = {
        "request": case.request_id,
        "edition": case.edition_id,
        "render": case.render_ids[0],
        "segment": case.edition_segment_ids[0],
    }[row_kind]

    with pytest.raises(DBAPIError):
        with session.begin_nested():
            session.execute(statement, {"row_id": row_id})
    assert session.scalar(
        select(func.count()).select_from(BackgroundManualRetryCommand).where(
            BackgroundManualRetryCommand.job_id == case.job_ids[0]
        )
    ) == 0


def test_manifest_cas_conflict_rolls_back_manual_command_and_every_state(
    failed_retry_pg_session: Session,
) -> None:
    session = failed_retry_pg_session
    with session.begin():
        case = _seed_retry_case(session, full_failure=False)
    command = _command(case, case.segment_ids[0], manifest_revision=1)

    with pytest.raises(NarrationCasConflict, match="Manifest"):
        with session.begin():
            retry_failed_segments(session, command)

    session.expire_all()
    request = session.get(NarrationRequest, case.request_id)
    render = session.get(NarrationSegmentRender, case.render_ids[0])
    row = session.get(NarrationEditionSegment, case.edition_segment_ids[0])
    job = session.get(BackgroundJob, case.job_ids[0])
    assert request is not None and request.version == case.request_version
    assert render is not None and render.state == "failed"
    assert row is not None and row.render_state == "failed"
    assert job is not None and job.state == "failed"
    assert session.scalar(
        select(func.count()).select_from(BackgroundManualRetryCommand).where(
            BackgroundManualRetryCommand.job_id == case.job_ids[0]
        )
    ) == 0


def test_same_root_replay_does_not_reset_rows_or_increment_version_twice(
    failed_retry_pg_session: Session,
) -> None:
    session = failed_retry_pg_session
    with session.begin():
        case = _seed_retry_case(session, full_failure=False)
    command = _command(
        case,
        case.segment_ids[0],
        idempotency_key="failed-retry-root-stable-replay",
    )
    with session.begin():
        first = retry_failed_segments(session, command)
        _assert_deferred_constraints(session)
    with session.begin():
        replay = retry_failed_segments(session, command)
        _assert_deferred_constraints(session)

    assert first.replayed is False and replay.replayed is True
    assert replay.request_version == first.request_version == case.request_version + 1
    assert replay.commands == first.commands
    assert session.scalar(
        select(func.count()).select_from(BackgroundManualRetryCommand).where(
            BackgroundManualRetryCommand.job_id == case.job_ids[0]
        )
    ) == 1


def _append_failed_manifest(session: Session, case: RetryCase) -> NarrationManifest:
    store = SqlAlchemyNarrationStore(session)
    rows = store.find_all(
        NarrationEditionSegment,
        edition_id=case.edition_id,
        order_by=("ordinal",),
    )
    return append_manifest_revision(
        store,
        PublishManifest(
            edition_id=case.edition_id,
            expected_current_revision=0,
            expected_state_version=0,
            buffer_policy=INITIAL_BUFFER_POLICY,
            segments=tuple(
                ManifestSegmentInput(
                    edition_segment_id=row.id,
                    render_status="failed",
                    failure=ManifestFailure(
                        code=row.failure_code or FAILURE_CODE,
                        retryable=False,
                        message="该句段生成失败，可稍后重新生成。",
                    ),
                )
                for row in rows
            ),
            updated_actor="failed-retry-baseline",
        ),
    )


def test_terminal_retry_failure_appends_manifest_and_preserves_old_revision(
    failed_retry_pg_session: Session,
) -> None:
    session = failed_retry_pg_session
    with session.begin():
        case = _seed_retry_case(session, full_failure=True)
        old_manifest = _append_failed_manifest(session, case)
        old_payload = dict(old_manifest.canonical_json)
        old_etag = old_manifest.etag_sha256
        _assert_deferred_constraints(session)
    command = _command(case, case.segment_ids[0], manifest_revision=1)
    with session.begin():
        retry_failed_segments(session, command)
        _assert_deferred_constraints(session)
    with session.begin():
        lease = claim_next_job(
            session,
            scope=SCOPE,
            lease_owner=f"failed-retry-terminal-{uuid4()}",
            resource_classes=("moss-nano",),
            novel_ids=(case.novel_id,),
            job_kinds=("narration.segment_render",),
            lease_seconds=900,
        )
        assert lease is not None and lease.fence.job_id == case.job_ids[0]
        failure = fail_attempt(
            session,
            scope=SCOPE,
            fence=lease.fence,
            classification="non_retryable",
            error_code="LEASE_EXPIRED",
        )
        assert failure.state == "failed"
        repository = object.__new__(SqlAlchemyNarrationWorkerRepository)
        repository._scope = SCOPE
        assert repository.terminalize_job_in_session(
            session, job_id=lease.fence.job_id
        ) is True
        _assert_deferred_constraints(session)

    session.expire_all()
    manifests = list(
        session.scalars(
            select(NarrationManifest)
            .where(NarrationManifest.edition_id == case.edition_id)
            .order_by(NarrationManifest.manifest_revision)
        )
    )
    pointer = session.get(NarrationEditionState, case.edition_id)
    assert [manifest.manifest_revision for manifest in manifests] == [1, 2]
    assert manifests[0].canonical_json == old_payload
    assert manifests[0].etag_sha256 == old_etag
    assert manifests[1].canonical_json["segments"][0]["failure"]["code"] == (
        "LEASE_EXPIRED"
    )
    assert pointer is not None and pointer.current_manifest_revision == 2
