"""Measure the current full hybrid retrieval path without a provider call."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from math import ceil
from pathlib import Path
from statistics import median
from time import perf_counter
import tracemalloc
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, insert, select, text, update
from sqlalchemy.orm import Session

try:
    from .benchmark_current_paths import PROFILES, cleanup, guarded_engine, seed_profile
except ImportError:  # Direct script execution from the repository root.
    from benchmark_current_paths import PROFILES, cleanup, guarded_engine, seed_profile

from backend.creative_data_models import (
    EmbeddingConfiguration,
    EmbeddingGeneration,
    EmbeddingGenerationNovel,
    EmbeddingIndexBatch,
    SemanticEmbedding,
)
from backend.embedding import api as embedding_api
from backend.embedding.adapter import EmbeddingBatchResult, EmbeddingVector
from backend.embedding.contracts import (
    EmbeddingCorpus,
    RetrievalPurpose,
    SemanticPerspective,
    SemanticSearchRequest,
)
from backend.models import (
    BackgroundExecutorEpoch,
    BackgroundJob,
    BackgroundJobAttempt,
    BackgroundResourceLock,
    ModelRunRecord,
)
from backend.narration.contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID


SAMPLES = 5


def _hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _vector(first: float, second: float) -> str:
    return "[" + ",".join((str(first), str(second), *("0" for _ in range(2046)))) + "]"


class _FakeSecretStore:
    def get(self, _reference: str) -> str:
        return "plan52-synthetic-not-a-real-key"


class _FakeAdapter:
    def __init__(self, **_kwargs: Any) -> None:
        pass

    async def embed(self, **_kwargs: Any) -> EmbeddingBatchResult:
        return EmbeddingBatchResult(
            request_id="plan52-local-fake",
            vectors=(EmbeddingVector(text_index=0, values=(1.0, 0.0, *(0.0 for _ in range(2046)))),),
            total_tokens=4,
            input_tokens=4,
        )


def _augment_with_vectors(engine, seed, row_count: int) -> tuple[UUID, UUID]:  # type: ignore[no-untyped-def]
    job_id = uuid4()
    attempt_id = uuid4()
    run_id = uuid4()
    batch_id = uuid4()
    resource_lease_token = uuid4()
    now = datetime.now(UTC)
    with engine.begin() as connection:
        epoch_id = connection.scalar(
            select(BackgroundExecutorEpoch.id).where(
                BackgroundExecutorEpoch.executor_key == "embedding-worker",
                BackgroundExecutorEpoch.state == "active",
            )
        )
        if epoch_id is None:
            raise RuntimeError("embedding-worker epoch is missing in the isolated database")
        connection.execute(
            update(EmbeddingGeneration)
            .where(EmbeddingGeneration.id == seed.generation_id)
            .values(state="active", activated_at=now)
        )
        connection.execute(
            insert(EmbeddingConfiguration.__table__),
            {
                "id": uuid4(),
                "owner_id": LOCAL_OWNER_ID,
                "workspace_id": LOCAL_WORKSPACE_ID,
                "base_url": "https://plan52.maas.aliyuncs.com/api/v1",
                "credential_ref": "plan52-fake",
                "api_key_last4": "fake",
                "active_generation_id": seed.generation_id,
                "connection_state": "ready",
                "connection_summary_json": {"synthetic": True},
                "retrieval_policy_version": "writing-retrieval/2",
                "version": 1,
            },
        )
        connection.execute(
            insert(BackgroundJob.__table__),
            {
                "id": job_id,
                "owner_id": LOCAL_OWNER_ID,
                "workspace_id": LOCAL_WORKSPACE_ID,
                "novel_id": seed.novel_id,
                "request_id": None,
                "request_allows_render": None,
                "job_kind": "embedding.index_batch",
                "input_hash": _hash(f"job:{seed.generation_id}"),
                "idempotency_key": f"plan52-hybrid:{seed.generation_id}",
                "resource_class": "dashscope-embedding",
                "state": "queued",
                "max_attempts": 1,
                "attempt_count": 0,
                "progress_current": 0,
                "progress_total": row_count,
            },
        )
        connection.execute(
            insert(BackgroundResourceLock.__table__),
            {
                "resource_key": "dashscope-embedding:0",
                "lease_owner": "plan52-benchmark",
                "lease_token": resource_lease_token,
                "lease_generation": 1,
                "lease_until": now + timedelta(minutes=1),
            },
        )
        connection.execute(
            insert(BackgroundJobAttempt.__table__),
            {
                "id": attempt_id,
                "job_id": job_id,
                "attempt_number": 1,
                "retry_kind": "initial",
                "executor_epoch_id": epoch_id,
                "resource_key": "dashscope-embedding:0",
                "resource_lease_token": resource_lease_token,
                "resource_lease_generation": 1,
                "lease_owner": "plan52-benchmark",
                "lease_token": uuid4(),
                "lease_generation": 1,
                "lease_until": now + timedelta(minutes=1),
                "started_at": now,
                "completed_at": None,
                "actual_result_digest": None,
            },
        )
        connection.execute(
            update(BackgroundJob)
            .where(BackgroundJob.id == job_id)
            .values(state="running", attempt_count=1)
        )
        connection.execute(
            insert(ModelRunRecord.__table__),
            {
                "id": run_id,
                "attempt_id": attempt_id,
                "requested_provider_id": "plan52-no-provider",
                "requested_model_id": "synthetic-2048",
                "actual_provider_id": "plan52-no-provider",
                "actual_model_id": "synthetic-2048",
                "actual_revision": "g0",
                "model_fingerprint": _hash("synthetic-model"),
                "parameters_digest": _hash("parameters"),
                "input_digest_key_id": "plan52",
                "input_digest": _hash("input"),
                "output_digest": _hash("output"),
                "duration_ms": 0,
                "provider_request_id": "plan52-local-fake",
                "result_classification": "success",
            },
        )
        connection.execute(
            update(BackgroundJobAttempt)
            .where(BackgroundJobAttempt.id == attempt_id)
            .values(
                completed_at=now,
                actual_result_digest=_hash(f"attempt:{seed.generation_id}"),
            )
        )
        connection.execute(
            update(BackgroundJob)
            .where(BackgroundJob.id == job_id)
            .values(state="succeeded", progress_current=row_count)
        )
        connection.execute(
            insert(EmbeddingIndexBatch.__table__),
            {
                "id": batch_id,
                "generation_id": seed.generation_id,
                "novel_id": seed.novel_id,
                "batch_number": 0,
                "background_job_id": job_id,
                "input_hash": _hash(f"batch:{seed.generation_id}"),
                "item_count": 10,
                "state": "ready",
                "attempt_count": 1,
                "result_count": row_count,
            },
        )
        connection.execute(
            text(
                "INSERT INTO semantic_embeddings "
                "(id, generation_id, chunk_id, batch_id, dimension, embedding, "
                " embedding_hash, model_run_id, response_ordinal) "
                "SELECT gen_random_uuid(), :generation_id, c.id, :batch_id, 2048, "
                "CASE WHEN c.content_text LIKE '%蓝钥匙%' "
                "THEN CAST(:target AS vector(2048)) ELSE CAST(:other AS vector(2048)) END, "
                ":embedding_hash, :run_id, 0 "
                "FROM semantic_chunks c WHERE c.generation_id = :generation_id"
            ),
            {
                "generation_id": seed.generation_id,
                "batch_id": batch_id,
                "target": _vector(1.0, 0.0),
                "other": _vector(0.0, 1.0),
                "embedding_hash": _hash("synthetic-vector"),
                "run_id": run_id,
            },
        )
        connection.execute(
            update(EmbeddingGenerationNovel)
            .where(
                EmbeddingGenerationNovel.generation_id == seed.generation_id,
                EmbeddingGenerationNovel.novel_id == seed.novel_id,
            )
            .values(embedded_count=row_count)
        )
        connection.execute(text("ANALYZE semantic_embeddings"))
    return run_id, job_id


def _cleanup(engine, seed, run_id: UUID) -> None:  # type: ignore[no-untyped-def]
    with engine.begin() as connection:
        # These three registries are immutable by ordinary DELETE and contain
        # only Plan 52 synthetic rows in this exact disposable database.
        connection.execute(
            text(
                "TRUNCATE TABLE background_jobs, model_run_records, "
                "background_resource_locks CASCADE"
            )
        )
        connection.execute(
            delete(EmbeddingConfiguration).where(
                EmbeddingConfiguration.active_generation_id == seed.generation_id
            )
        )
        connection.execute(
            delete(SemanticEmbedding).where(
                SemanticEmbedding.generation_id == seed.generation_id
            )
        )
    cleanup(engine, seed)


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, ceil(len(ordered) * fraction) - 1))]


def benchmark(label: str) -> dict[str, Any]:
    engine = guarded_engine()
    seed, seed_evidence = seed_profile(engine, PROFILES[label])
    run_id: UUID | None = None
    original_adapter = embedding_api.DashScopeEmbeddingAdapter
    original_store = embedding_api._secret_store
    try:
        run_id, _job_id = _augment_with_vectors(
            engine, seed, seed_evidence["semantic_chunk_count"]
        )
        embedding_api.DashScopeEmbeddingAdapter = _FakeAdapter  # type: ignore[assignment]
        embedding_api._secret_store = lambda: _FakeSecretStore()  # type: ignore[assignment]
        request = SemanticSearchRequest(
            query="谁保管蓝钥匙",
            retrieval_purpose=RetrievalPurpose.CHAPTER_BODY,
            corpora=(EmbeddingCorpus.MANUSCRIPT,),
            top_k=10,
            timeline_id=seed.timeline_id,
            narrative_sequence=PROFILES[label].chapter_count,
            story_sequence_cutoff=PROFILES[label].chapter_count,
            perspective=SemanticPerspective(),
        )
        timings: list[float] = []
        sql_counts: list[int] = []
        peak_mib = 0.0
        payload: dict[str, Any] = {}
        for _ in range(SAMPLES):
            sql_count = 0

            def count_sql(*_args: Any, **_kwargs: Any) -> None:
                nonlocal sql_count
                sql_count += 1

            from sqlalchemy import event

            event.listen(engine, "before_cursor_execute", count_sql)
            tracemalloc.start()
            started = perf_counter()
            try:
                with Session(engine) as session:
                    payload = asyncio.run(
                        embedding_api.semantic_search(seed.novel_id, request, session)
                    )
                    session.rollback()
                timings.append((perf_counter() - started) * 1_000)
                _, peak = tracemalloc.get_traced_memory()
                peak_mib = max(peak_mib, peak / 1024 / 1024)
            finally:
                tracemalloc.stop()
                event.remove(engine, "before_cursor_execute", count_sql)
            sql_counts.append(sql_count)
        return {
            "profile": label,
            "seed": seed_evidence,
            "provider_calls": 0,
            "fake_query_adapter_calls": SAMPLES,
            "mode": payload.get("mode"),
            "hit_count": len(payload.get("hits", [])),
            "top_hit_contains_target": bool(
                payload.get("hits") and "蓝钥匙" in payload["hits"][0].get("snippet", "")
            ),
            "p50_ms": round(median(timings), 3),
            "p95_ms": round(_percentile(timings, 0.95), 3),
            "peak_tracemalloc_mib": round(peak_mib, 3),
            "sql_count_min": min(sql_counts),
            "sql_count_max": max(sql_counts),
        }
    finally:
        embedding_api.DashScopeEmbeddingAdapter = original_adapter
        embedding_api._secret_store = original_store
        try:
            if run_id is not None:
                _cleanup(engine, seed, run_id)
            else:
                cleanup(engine, seed)
        finally:
            engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles", default="1m,5m")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    labels = [item.strip() for item in args.profiles.split(",") if item.strip()]
    payload = {
        "schema_version": "plan52-g0-hybrid-evidence/1",
        "database_name": "ai_novel_world_2026_plan52_test",
        "samples": SAMPLES,
        "profiles": [benchmark(label) for label in labels],
    }
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)


if __name__ == "__main__":
    main()
