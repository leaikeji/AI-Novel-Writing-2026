"""PostgreSQL gate for per-attempt worker model-run audit evidence.

The module only runs against the exact disposable loopback PostgreSQL 18
database selected by ``TTS_TEST_DATABASE_URL``.  It exercises the production
short-transaction worker repository and proves that success and terminal
failure paths retain one HMAC-backed ``ModelRunRecord`` per exact attempt.

Cancellation uses the fix-forward 0019 fence: only ``cancelled`` evidence may
be inserted while the exact live job is ``cancel_requested``; all other model
results still require ``running``.
"""

from __future__ import annotations

import re
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.models import (
    BackgroundJob,
    BackgroundJobAttempt,
    ModelRunRecord,
    NarrationSegmentRender,
)
from backend.narration import worker as worker_module
from backend.narration.contracts import NarrationRequestScope
from backend.narration.jobs import JobFenceError, request_cancel
from backend.narration.publication import ModelRunSuccessEvidence
from backend.narration.runtime import canonical_sidecar_synthesis_metadata
from backend.narration.services import InvalidNarrationState
from backend.narration.worker import (
    PreparedRender,
    SegmentWorkItem,
    SqlAlchemyNarrationWorkerRepository,
    derive_model_input_digest,
)
from tests.narration.digest_fixtures import TEST_DIGEST_KEYRING
from tests.narration.test_publication_postgres import (
    EXPECTED_DATABASE,
    EXPECTED_USERNAME,
    PendingPublication,
    _live_url,
    _publish_files,
    _repository_head,
    _seed_pending_publication,
    _storage,
)


SCOPE = NarrationRequestScope.fixed_local()
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@pytest.fixture(scope="module")
def worker_model_run_pg_engine() -> Engine:
    """Open only the existing exact disposable PostgreSQL integration gate."""

    engine = create_engine(_live_url(), pool_pre_ping=True)
    with engine.connect() as connection:
        server_version = connection.scalar(text("SHOW server_version"))
        assert isinstance(server_version, str) and server_version.startswith("18.")
        assert connection.scalar(text("SELECT current_database()")) == EXPECTED_DATABASE
        assert connection.scalar(text("SELECT current_user")) == EXPECTED_USERNAME
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            _repository_head()
        )
        constraints = set(
            connection.scalars(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE conrelid='model_run_records'::regclass"
                )
            )
        )
        assert "uq_model_run_attempt" in constraints
        assert "ck_model_run_result_classification" in constraints
        assert connection.scalar(
            text(
                "SELECT count(*) FROM pg_trigger "
                "WHERE tgrelid='model_run_records'::regclass "
                "AND tgname='trg_model_run_execution_fence' "
                "AND NOT tgisinternal"
            )
        ) == 1
    try:
        yield engine
    finally:
        engine.dispose()


def _repository(engine: Engine) -> SqlAlchemyNarrationWorkerRepository:
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return SqlAlchemyNarrationWorkerRepository(
        factory,
        digest_keyring=TEST_DIGEST_KEYRING,
        scope=SCOPE,
    )


def _load_work(
    engine: Engine,
) -> tuple[
    PendingPublication,
    SqlAlchemyNarrationWorkerRepository,
    SegmentWorkItem,
    str,
]:
    pending = _seed_pending_publication(engine)
    repository = _repository(engine)
    work = repository.load_and_mark_running(
        pending.lease,
        default_max_new_frames=375,
        actor="worker-model-run-pg",
    )
    with Session(engine) as session:
        render_fingerprint = session.scalar(
            select(NarrationSegmentRender.render_fingerprint).where(
                NarrationSegmentRender.id == pending.render_id
            )
        )
    assert isinstance(render_fingerprint, str)
    _assert_hmac_input(work, render_fingerprint=render_fingerprint)
    return pending, repository, work, render_fingerprint


def _assert_hmac_input(work: SegmentWorkItem, *, render_fingerprint: str) -> None:
    reference = work.reference_media
    metadata = canonical_sidecar_synthesis_metadata(
        request_id=work.lease.fence.attempt_id,
        scope=SCOPE,
        requested_model_fingerprint_sha256=work.expected_model_fingerprint,
        text=work.text,
        voice=work.voice,
        seed=work.seed,
        sample_mode=work.sample_mode,
        max_new_frames=work.max_new_frames,
        reference_content_type=(reference.content_type if reference else None),
        reference_actual_sha256=(reference.actual_sha256 if reference else None),
        reference_size_bytes=(reference.byte_size if reference else None),
    )
    expected_key_id, expected_digest = derive_model_input_digest(
        TEST_DIGEST_KEYRING.active,
        sidecar_metadata=metadata,
    )
    assert work.input_digest_key_id == expected_key_id
    assert work.input_digest == expected_digest
    assert HEX_SHA256.fullmatch(work.input_digest)
    assert work.input_digest != render_fingerprint
    assert work.input_digest_key_id != render_fingerprint


def _model_runs(engine: Engine, attempt_id: UUID) -> list[ModelRunRecord]:
    with Session(engine) as session:
        return list(
            session.scalars(
                select(ModelRunRecord).where(ModelRunRecord.attempt_id == attempt_id)
            )
        )


def _assert_exact_model_run(
    engine: Engine,
    *,
    work: SegmentWorkItem,
    render_fingerprint: str,
    result_classification: str,
    output_digest: str | None,
) -> ModelRunRecord:
    rows = _model_runs(engine, work.lease.fence.attempt_id)
    assert len(rows) == 1
    row = rows[0]
    assert row.attempt_id == work.lease.fence.attempt_id
    assert row.result_classification == result_classification
    assert row.input_digest_key_id == TEST_DIGEST_KEYRING.active_key_id
    assert row.input_digest_key_id == work.input_digest_key_id
    assert row.input_digest == work.input_digest
    assert HEX_SHA256.fullmatch(row.input_digest)
    assert row.input_digest != render_fingerprint
    assert row.input_digest_key_id != render_fingerprint
    assert row.output_digest == output_digest
    if output_digest is None:
        assert row.actual_provider_id is None
        assert row.actual_model_id is None
        assert row.actual_revision is None
        assert row.model_fingerprint is None
        assert row.duration_ms is None
    return row


def _success_evidence(work: SegmentWorkItem, *, duration_ms: int) -> ModelRunSuccessEvidence:
    return ModelRunSuccessEvidence(
        requested_provider_id=work.requested_provider_id,
        requested_model_id=work.requested_model_id,
        requested_revision=work.requested_revision,
        actual_provider_id=work.requested_provider_id,
        actual_model_id=work.requested_model_id,
        actual_revision=work.requested_revision,
        model_fingerprint=work.expected_model_fingerprint,
        parameters_digest=work.parameters_digest,
        input_digest_key_id=work.input_digest_key_id,
        input_digest=work.input_digest,
        duration_ms=duration_ms,
        provider_request_id=str(work.lease.fence.attempt_id),
    )


def test_success_records_one_hmac_model_run_in_atomic_publication(
    worker_model_run_pg_engine: Engine,
    tmp_path: Path,
) -> None:
    engine = worker_model_run_pg_engine
    pending, repository, work, render_fingerprint = _load_work(engine)
    storage = _storage(tmp_path)
    audio = _publish_files(storage, pending)
    repository.bind_storage(storage)

    repository.publish(
        work,
        PreparedRender(
            audio=audio,
            model=_success_evidence(work, duration_ms=audio.duration_ms),
        ),
        actor="worker-model-run-pg",
    )

    row = _assert_exact_model_run(
        engine,
        work=work,
        render_fingerprint=render_fingerprint,
        result_classification="success",
        output_digest=audio.playback.actual_sha256,
    )
    assert row.model_fingerprint == work.expected_model_fingerprint
    assert row.duration_ms == audio.duration_ms
    with Session(engine) as session:
        job = session.get(BackgroundJob, pending.job_id)
        attempt = session.get(BackgroundJobAttempt, pending.attempt_id)
        assert job is not None and job.state == "succeeded"
        assert attempt is not None and attempt.completed_at is not None
        assert attempt.actual_result_digest == audio.playback.actual_sha256

    with pytest.raises((InvalidNarrationState, JobFenceError)):
        repository.publish(
            work,
            PreparedRender(
                audio=audio,
                model=_success_evidence(work, duration_ms=audio.duration_ms),
            ),
            actor="worker-model-run-pg",
        )
    assert len(_model_runs(engine, pending.attempt_id)) == 1


@pytest.mark.parametrize(
    ("classification", "record_classification", "expected_job_state"),
    (
        ("retryable", "retryable_failure", "retry_wait"),
        ("non_retryable", "non_retryable_failure", "failed"),
        ("security_failure", "security_failure", "failed"),
    ),
)
def test_failure_records_one_hmac_model_run_without_output(
    worker_model_run_pg_engine: Engine,
    classification: str,
    record_classification: str,
    expected_job_state: str,
) -> None:
    engine = worker_model_run_pg_engine
    pending, repository, work, render_fingerprint = _load_work(engine)

    result = repository.fail(
        work,
        classification=classification,  # type: ignore[arg-type]
        error_code="WORKER_MODEL_RUN_PG_FAILURE",
    )

    assert result.state == expected_job_state
    _assert_exact_model_run(
        engine,
        work=work,
        render_fingerprint=render_fingerprint,
        result_classification=record_classification,
        output_digest=None,
    )
    with Session(engine) as session:
        job = session.get(BackgroundJob, pending.job_id)
        attempt = session.get(BackgroundJobAttempt, pending.attempt_id)
        assert job is not None and job.state == expected_job_state
        assert attempt is not None and attempt.completed_at is not None
        assert attempt.error_classification == classification
        assert attempt.actual_result_digest is None

    with pytest.raises(InvalidNarrationState, match="already has model-run evidence"):
        repository.fail(
            work,
            classification=classification,  # type: ignore[arg-type]
            error_code="WORKER_MODEL_RUN_PG_DUPLICATE",
        )
    assert len(_model_runs(engine, pending.attempt_id)) == 1


def test_terminal_audio_failure_persists_only_canonical_validation_evidence(
    worker_model_run_pg_engine: Engine,
) -> None:
    engine = worker_model_run_pg_engine
    pending, repository, work, render_fingerprint = _load_work(engine)
    evidence = {
        "schema_version": "narration-audio-validation-failure/1",
        "reason_code": "SHORT_CHINESE_DURATION_IMPLAUSIBLE",
    }

    result = repository.fail(
        work,
        classification="non_retryable",
        error_code="NANO_AUDIO_INVALID",
        failure_evidence=evidence,
    )

    assert result.state == "failed"
    _assert_exact_model_run(
        engine,
        work=work,
        render_fingerprint=render_fingerprint,
        result_classification="non_retryable_failure",
        output_digest=None,
    )
    with Session(engine) as session:
        render = session.get(NarrationSegmentRender, pending.render_id)
        assert render is not None and render.state == "failed"
        assert render.audio_validation_json == evidence
        assert set(render.audio_validation_json) == {"schema_version", "reason_code"}
        assert "正文" not in repr(render.audio_validation_json)


def test_failure_transaction_rollback_leaves_no_half_model_run(
    worker_model_run_pg_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = worker_model_run_pg_engine
    pending, repository, work, render_fingerprint = _load_work(engine)

    with monkeypatch.context() as fault:
        fault.setattr(
            worker_module,
            "advance_edition_segment_state",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("fault after failure evidence assignment")
            ),
        )
        with pytest.raises(
            RuntimeError,
            match="fault after failure evidence assignment",
        ):
            repository.fail(
                work,
                classification="non_retryable",
                error_code="WORKER_MODEL_RUN_PG_ROLLBACK",
                failure_evidence={
                    "schema_version": "narration-audio-validation-failure/1",
                    "reason_code": "WAV_SILENT",
                },
            )

    assert _model_runs(engine, pending.attempt_id) == []
    with Session(engine) as session:
        job = session.get(BackgroundJob, pending.job_id)
        attempt = session.get(BackgroundJobAttempt, pending.attempt_id)
        render = session.get(NarrationSegmentRender, pending.render_id)
        assert job is not None and job.state == "running"
        assert attempt is not None and attempt.completed_at is None
        assert attempt.error_classification is None
        assert render is not None and render.state == "rendering"
        assert render.audio_validation_json == {}

    recovered = repository.fail(
        work,
        classification="security_failure",
        error_code="WORKER_MODEL_RUN_PG_RECOVERED",
    )
    assert recovered.state == "failed"
    _assert_exact_model_run(
        engine,
        work=work,
        render_fingerprint=render_fingerprint,
        result_classification="security_failure",
        output_digest=None,
    )


def test_cancelled_model_run_records_one_live_fenced_audit_row(
    worker_model_run_pg_engine: Engine,
) -> None:
    engine = worker_model_run_pg_engine
    pending, repository, work, render_fingerprint = _load_work(engine)
    with Session(engine) as session, session.begin():
        cancelled = request_cancel(
            session,
            scope=SCOPE,
            job_id=pending.job_id,
            actor="worker-model-run-pg",
            reason_code="USER_CANCELLED_NARRATION",
        )
        assert cancelled.state == "cancel_requested"

    repository.acknowledge_cancel(work)

    _assert_exact_model_run(
        engine,
        work=work,
        render_fingerprint=render_fingerprint,
        result_classification="cancelled",
        output_digest=None,
    )
    with Session(engine) as session:
        job = session.get(BackgroundJob, pending.job_id)
        attempt = session.get(BackgroundJobAttempt, pending.attempt_id)
        assert job is not None and job.state == "cancelled"
        assert attempt is not None and attempt.completed_at is not None
        assert attempt.error_classification == "cancelled"
        assert attempt.actual_result_digest is None
    with pytest.raises((InvalidNarrationState, JobFenceError)):
        repository.acknowledge_cancel(work)
    assert len(_model_runs(engine, pending.attempt_id)) == 1
