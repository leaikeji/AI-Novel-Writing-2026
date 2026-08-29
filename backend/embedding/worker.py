"""One-batch embedding worker with no database transaction across cloud I/O."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from time import monotonic
from typing import Callable
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..background.contracts import LocalWorkspaceScope
from ..background.jobs import (
    JobLease,
    acknowledge_cancel,
    complete_attempt,
    fail_attempt,
)
from ..creative_data_models import (
    EmbeddingConfiguration,
    EmbeddingGeneration,
    EmbeddingGenerationNovel,
    EmbeddingIndexBatch,
    EmbeddingIndexBatchItem,
    EmbeddingProfile,
    NovelEmbeddingConsent,
    SemanticChunk,
    SemanticEmbedding,
)
from .adapter import (
    DashScopeEmbeddingAdapter,
    EmbeddingAdapterError,
    EmbeddingBatchResult,
)
from .lifecycle import EmbeddingLifecycleError
from .secrets import EmbeddingSecretError, EmbeddingSecretStore
from ..models import BackgroundJob, ModelRunRecord


SessionFactory = Callable[[], Session]
EMBEDDING_CALL_DEADLINE_SECONDS = 60


def _consume_abandoned_task(task: asyncio.Task[EmbeddingBatchResult]) -> None:
    """Observe a late transport outcome without allowing it to publish vectors."""

    if task.cancelled():
        return
    try:
        task.exception()
    except (asyncio.CancelledError, Exception):
        return


async def _embed_with_hard_deadline(
    adapter: DashScopeEmbeddingAdapter,
    *,
    api_key: str,
    texts: tuple[str, ...],
    model_id: str,
    dimension: int,
) -> EmbeddingBatchResult:
    task = asyncio.create_task(
        adapter.embed(
            api_key=api_key,
            texts=texts,
            text_type="document",
            model_id=model_id,
            dimension=dimension,
        )
    )
    try:
        done, _ = await asyncio.wait({task}, timeout=EMBEDDING_CALL_DEADLINE_SECONDS)
    except asyncio.CancelledError:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        raise
    if task not in done:
        task.add_done_callback(_consume_abandoned_task)
        task.cancel()
        raise TimeoutError("embedding call exceeded the total deadline")
    return task.result()


@dataclass(frozen=True, slots=True)
class BatchCallSnapshot:
    batch_id: UUID
    generation_id: UUID
    novel_id: UUID
    profile_id: UUID
    credential_ref: str
    base_url: str
    model_id: str
    model_revision: str | None
    dimension: int
    input_hash: str
    chunk_ids: tuple[UUID, ...]
    texts: tuple[str, ...]


def _hash(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(raw.encode("utf-8")).hexdigest()


def _load_call(session: Session, *, lease: JobLease) -> BatchCallSnapshot:
    batch = session.scalar(
        select(EmbeddingIndexBatch)
        .where(EmbeddingIndexBatch.background_job_id == lease.fence.job_id)
        .with_for_update()
    )
    if batch is None:
        raise EmbeddingLifecycleError("batch_not_found", "embedding batch was not found")
    if batch.state not in {"queued", "running"}:
        raise EmbeddingLifecycleError("batch_state_invalid", "embedding batch cannot run")
    build = session.scalar(
        select(EmbeddingGenerationNovel).where(
            EmbeddingGenerationNovel.generation_id == batch.generation_id,
            EmbeddingGenerationNovel.novel_id == batch.novel_id,
        )
    )
    if build is None or build.state not in {"building", "pending"}:
        raise EmbeddingLifecycleError("generation_cancelled", "novel index build is not active")
    consent = session.scalar(
        select(NovelEmbeddingConsent).where(
            NovelEmbeddingConsent.id == build.consent_id,
            NovelEmbeddingConsent.novel_id == build.novel_id,
            NovelEmbeddingConsent.revoked_at.is_(None),
        )
    )
    if consent is None:
        raise EmbeddingLifecycleError("consent_revoked", "cloud embedding consent is not active")
    generation = session.get(EmbeddingGeneration, batch.generation_id)
    if generation is None or generation.state not in {"building", "draft"}:
        raise EmbeddingLifecycleError("generation_state_invalid", "embedding generation is not buildable")
    profile = session.get(EmbeddingProfile, generation.profile_id)
    if profile is None or profile.connection_state != "available":
        raise EmbeddingLifecycleError("profile_unavailable", "embedding profile is unavailable")
    configuration = session.scalar(
        select(EmbeddingConfiguration).where(
            EmbeddingConfiguration.owner_id == generation.owner_id,
            EmbeddingConfiguration.workspace_id == generation.workspace_id,
        )
    )
    if configuration is None or configuration.credential_ref is None:
        raise EmbeddingLifecycleError(
            "embedding_not_configured", "embedding credential is missing"
        )
    rows = session.execute(
        select(EmbeddingIndexBatchItem, SemanticChunk)
        .join(SemanticChunk, SemanticChunk.id == EmbeddingIndexBatchItem.chunk_id)
        .where(EmbeddingIndexBatchItem.batch_id == batch.id)
        .order_by(EmbeddingIndexBatchItem.ordinal)
    ).all()
    if len(rows) != batch.item_count or not rows:
        raise EmbeddingLifecycleError("batch_shape_invalid", "embedding batch items are incomplete")
    chunk_ids = tuple(chunk.id for _, chunk in rows)
    texts = tuple(chunk.content_text for _, chunk in rows)
    if _hash([str(chunk_id) + ":" + chunk.content_hash for (_, chunk), chunk_id in zip(rows, chunk_ids)]) != batch.input_hash:
        raise EmbeddingLifecycleError("batch_hash_mismatch", "embedding batch input changed")
    batch.state = "running"
    batch.attempt_count += 1
    session.flush()
    return BatchCallSnapshot(
        batch_id=batch.id, generation_id=batch.generation_id, novel_id=batch.novel_id,
        profile_id=profile.id, credential_ref=configuration.credential_ref,
        base_url=profile.base_url, model_id=profile.actual_model_id,
        model_revision=profile.actual_revision, dimension=profile.dimension,
        input_hash=batch.input_hash, chunk_ids=chunk_ids, texts=texts,
    )


def _record_failure(
    session: Session,
    *,
    lease: JobLease,
    snapshot: BatchCallSnapshot,
    code: str,
    retryable: bool,
    duration_ms: int,
) -> None:
    session.add(
        ModelRunRecord(
            id=uuid4(), attempt_id=lease.fence.attempt_id,
            requested_provider_id="aliyun-bailian", requested_model_id=snapshot.model_id,
            requested_revision=snapshot.model_revision, actual_provider_id=None,
            actual_model_id=None, actual_revision=None, model_fingerprint=None,
            parameters_digest=_hash({"dimension": snapshot.dimension, "text_type": "document"}),
            input_digest_key_id="semantic-batch-sha256/1", input_digest=snapshot.input_hash,
            output_digest=None, duration_ms=duration_ms, provider_request_id=None,
            result_classification="retryable_failure" if retryable else "non_retryable_failure",
        )
    )
    outcome = fail_attempt(
        session, scope=LocalWorkspaceScope.fixed_local(), fence=lease.fence,
        classification="retryable" if retryable else "non_retryable",
        error_code=code,
    )
    batch = session.get(EmbeddingIndexBatch, snapshot.batch_id)
    if batch is not None:
        batch.state = "queued" if outcome.state == "retry_wait" else "failed"
        batch.failure_code = code
    session.flush()


def _settle_preflight_failure(
    session: Session,
    *,
    lease: JobLease,
    error: EmbeddingLifecycleError,
) -> None:
    """Settle a claimed job that became invalid before cloud I/O starts."""

    batch = session.scalar(
        select(EmbeddingIndexBatch)
        .where(EmbeddingIndexBatch.background_job_id == lease.fence.job_id)
        .with_for_update()
    )
    job = session.get(BackgroundJob, lease.fence.job_id)
    if job is not None and job.state == "cancel_requested":
        acknowledge_cancel(
            session,
            scope=LocalWorkspaceScope.fixed_local(),
            fence=lease.fence,
        )
    else:
        fail_attempt(
            session,
            scope=LocalWorkspaceScope.fixed_local(),
            fence=lease.fence,
            classification="non_retryable",
            error_code=error.code.upper(),
        )
    if batch is not None:
        batch.state = (
            "cancelled"
            if error.code
            in {"generation_cancelled", "generation_state_invalid", "consent_revoked"}
            else "failed"
        )
        batch.failure_code = error.code.upper()
        batch.completed_at = datetime.now(UTC)
    session.flush()


def _acknowledge_requested_cancel(
    session: Session,
    *,
    lease: JobLease,
    snapshot: BatchCallSnapshot,
) -> bool:
    """Discard a late transport result when cancellation won the race."""

    job = session.get(BackgroundJob, lease.fence.job_id)
    if job is None or job.state != "cancel_requested":
        return False
    acknowledge_cancel(
        session,
        scope=LocalWorkspaceScope.fixed_local(),
        fence=lease.fence,
    )
    batch = session.get(EmbeddingIndexBatch, snapshot.batch_id)
    if batch is not None:
        batch.state = "cancelled"
        batch.failure_code = "JOB_CANCELLED"
        batch.completed_at = datetime.now(UTC)
    session.flush()
    return True


def _record_success(
    session: Session,
    *,
    lease: JobLease,
    snapshot: BatchCallSnapshot,
    result: EmbeddingBatchResult,
    duration_ms: int,
) -> None:
    batch = session.scalar(
        select(EmbeddingIndexBatch)
        .where(EmbeddingIndexBatch.id == snapshot.batch_id)
        .with_for_update()
    )
    build = session.scalar(
        select(EmbeddingGenerationNovel)
        .where(
            EmbeddingGenerationNovel.generation_id == snapshot.generation_id,
            EmbeddingGenerationNovel.novel_id == snapshot.novel_id,
        )
        .with_for_update()
    )
    if batch is None or build is None or batch.state != "running":
        raise EmbeddingLifecycleError("batch_state_invalid", "embedding result is stale")
    consent = session.scalar(
        select(NovelEmbeddingConsent).where(
            NovelEmbeddingConsent.id == build.consent_id,
            NovelEmbeddingConsent.revoked_at.is_(None),
        )
    )
    if consent is None:
        raise EmbeddingLifecycleError("consent_revoked", "consent was revoked before publication")
    if len(result.vectors) != len(snapshot.chunk_ids):
        raise EmbeddingLifecycleError("response_count_invalid", "embedding response count changed")
    output_digest = _hash([list(vector.values) for vector in result.vectors])
    run = ModelRunRecord(
        id=uuid4(), attempt_id=lease.fence.attempt_id,
        requested_provider_id="aliyun-bailian", requested_model_id=snapshot.model_id,
        requested_revision=snapshot.model_revision, actual_provider_id="aliyun-bailian",
        actual_model_id=snapshot.model_id, actual_revision=snapshot.model_revision,
        model_fingerprint=_hash(
            [
                snapshot.model_id,
                snapshot.model_revision,
                snapshot.dimension,
                str(snapshot.profile_id),
            ]
        ),
        parameters_digest=_hash({"dimension": snapshot.dimension, "text_type": "document"}),
        input_digest_key_id="semantic-batch-sha256/1", input_digest=snapshot.input_hash,
        output_digest=output_digest, duration_ms=duration_ms,
        provider_request_id=result.request_id, result_classification="success",
    )
    session.add(run)
    session.flush()
    for ordinal, (chunk_id, vector) in enumerate(zip(snapshot.chunk_ids, result.vectors)):
        session.add(
            SemanticEmbedding(
                id=uuid4(), generation_id=snapshot.generation_id, chunk_id=chunk_id,
                batch_id=batch.id, dimension=snapshot.dimension,
                embedding=list(vector.values), embedding_hash=_hash(list(vector.values)),
                model_run_id=run.id, response_ordinal=ordinal,
            )
        )
    batch.state = "ready"
    batch.result_count = len(result.vectors)
    batch.failure_code = None
    batch.completed_at = datetime.now(UTC)
    build.embedded_count += len(result.vectors)
    remaining = int(
        session.scalar(
            select(func.count()).select_from(EmbeddingIndexBatch).where(
                EmbeddingIndexBatch.generation_id == snapshot.generation_id,
                EmbeddingIndexBatch.novel_id == snapshot.novel_id,
                EmbeddingIndexBatch.id != batch.id,
                EmbeddingIndexBatch.state != "ready",
            )
        )
        or 0
    )
    if remaining == 0 and build.embedded_count == build.chunk_count:
        build.state = "ready"
        build.completed_at = datetime.now(UTC)
    complete_attempt(
        session, scope=LocalWorkspaceScope.fixed_local(), fence=lease.fence,
        actual_result_digest=output_digest,
    )
    generation = session.get(EmbeddingGeneration, snapshot.generation_id)
    if generation is not None:
        not_ready = int(
            session.scalar(
                select(func.count()).select_from(EmbeddingGenerationNovel).where(
                    EmbeddingGenerationNovel.generation_id == generation.id,
                    EmbeddingGenerationNovel.state != "ready",
                )
            )
            or 0
        )
        if not_ready == 0:
            generation.state = "ready"
            generation.ready_at = datetime.now(UTC)
    configuration = session.scalar(
        select(EmbeddingConfiguration).where(
            EmbeddingConfiguration.candidate_generation_id == snapshot.generation_id
        )
    )
    if configuration is not None:
        summary = dict(configuration.connection_summary_json)
        summary.update(
            {
                "request_id": result.request_id,
                "total_tokens": result.total_tokens,
                "latency_ms": duration_ms,
            }
        )
        configuration.connection_summary_json = summary
    session.flush()


async def execute_embedding_batch(
    *,
    lease: JobLease,
    session_factory: SessionFactory,
    secret_store: EmbeddingSecretStore,
) -> None:
    """Execute one claimed batch.  Caller owns scheduler heartbeat/retry loops."""

    with session_factory() as session:
        try:
            snapshot = _load_call(session, lease=lease)
        except EmbeddingLifecycleError as error:
            _settle_preflight_failure(session, lease=lease, error=error)
            session.commit()
            return
        session.commit()
    try:
        api_key = secret_store.get(snapshot.credential_ref)
    except EmbeddingSecretError:
        with session_factory() as session:
            if _acknowledge_requested_cancel(session, lease=lease, snapshot=snapshot):
                session.commit()
                return
            _record_failure(
                session, lease=lease, snapshot=snapshot,
                code="EMBEDDING_SECRET_UNAVAILABLE", retryable=False, duration_ms=0,
            )
            session.commit()
        return
    adapter = DashScopeEmbeddingAdapter(base_url=snapshot.base_url)
    started = monotonic()
    try:
        result = await _embed_with_hard_deadline(
            adapter,
            api_key=api_key,
            texts=snapshot.texts,
            model_id=snapshot.model_id,
            dimension=snapshot.dimension,
        )
    except asyncio.CancelledError:
        elapsed = max(0, int((monotonic() - started) * 1000))
        with session_factory() as session:
            if not _acknowledge_requested_cancel(
                session, lease=lease, snapshot=snapshot
            ):
                _record_failure(
                    session,
                    lease=lease,
                    snapshot=snapshot,
                    code="EMBEDDING_WORKER_INTERRUPTED",
                    retryable=True,
                    duration_ms=elapsed,
                )
            session.commit()
        raise
    except TimeoutError:
        elapsed = max(0, int((monotonic() - started) * 1000))
        with session_factory() as session:
            if _acknowledge_requested_cancel(session, lease=lease, snapshot=snapshot):
                session.commit()
                return
            _record_failure(
                session, lease=lease, snapshot=snapshot,
                code="EMBEDDING_TOTAL_TIMEOUT", retryable=False, duration_ms=elapsed,
            )
            session.commit()
        return
    except EmbeddingAdapterError as error:
        elapsed = max(0, int((monotonic() - started) * 1000))
        with session_factory() as session:
            if _acknowledge_requested_cancel(session, lease=lease, snapshot=snapshot):
                session.commit()
                return
            _record_failure(
                session, lease=lease, snapshot=snapshot, code=error.code,
                retryable=error.retryable, duration_ms=elapsed,
            )
            session.commit()
        return
    elapsed = max(0, int((monotonic() - started) * 1000))
    try:
        with session_factory() as session:
            if _acknowledge_requested_cancel(session, lease=lease, snapshot=snapshot):
                session.commit()
                return
            _record_success(
                session, lease=lease, snapshot=snapshot, result=result, duration_ms=elapsed
            )
            session.commit()
    except EmbeddingLifecycleError as error:
        with session_factory() as session:
            _record_failure(
                session, lease=lease, snapshot=snapshot,
                code=error.code.upper(), retryable=False, duration_ms=elapsed,
            )
            session.commit()
