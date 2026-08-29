from pathlib import Path
from types import SimpleNamespace
from threading import Event
from uuid import uuid4

import asyncio

import pytest

from backend.embedding.indexing import _batch_chunks
from backend.embedding.lifecycle import EmbeddingLifecycleError
from backend.embedding import worker
from backend.embedding import runtime
from backend.narration.scheduler import SchedulerConfig
from backend.embedding.runtime import EMBEDDING_JOB_LEASE_SECONDS


def test_embedding_scheduler_contract_is_explicit() -> None:
    config = SchedulerConfig(
        lease_owner="embedding-worker:test",
        executor_key="embedding-worker",
        resource_classes=("dashscope-embedding",),
        job_kinds=("embedding.index_batch",),
    )
    config.validate()
    assert EMBEDDING_JOB_LEASE_SECONDS == 600
    assert worker.EMBEDDING_CALL_DEADLINE_SECONDS == 60


def test_runtime_owns_a_cancellable_daemon_thread() -> None:
    source = Path(runtime.__file__).read_text(encoding="utf-8")

    assert "Thread(" in source
    assert "daemon=True" in source
    assert "asyncio.run(runner())" in source
    assert "loop.call_soon_threadsafe(task.cancel)" in source
    assert "ThreadPoolExecutor" not in source
    assert 'code="EMBEDDING_WORKER_INTERRUPTED"' in Path(worker.__file__).read_text(
        encoding="utf-8"
    )
    assert "lease.attempt_id" not in Path(worker.__file__).read_text(encoding="utf-8")
    app_source = (Path(runtime.__file__).parents[1] / "app.py").read_text(encoding="utf-8")
    assert '"vector_retrieval_enabled": False' not in app_source
    assert '"vector_retrieval_enabled": semantic_retrieval_enabled()' in app_source


@pytest.mark.asyncio
async def test_runtime_thread_survives_launch_hook_and_stops_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = Event()

    async def fake_run(stop_event: Event) -> None:
        started.set()
        while not stop_event.is_set():
            await asyncio.sleep(0.01)

    await runtime.stop_embedding_runtime()
    monkeypatch.setattr(runtime, "_run", fake_run)

    await runtime.launch_embedding_runtime()
    for _ in range(50):
        if started.is_set():
            break
        await asyncio.sleep(0.01)

    assert started.is_set()
    assert runtime._thread is not None and runtime._thread.is_alive()
    await runtime.stop_embedding_runtime()
    assert runtime.embedding_runtime_status()["state"] == "stopped"


def test_long_embedding_batches_keep_ten_item_cap_and_character_budget() -> None:
    chunks = [SimpleNamespace(content_text="x" * 1_200) for _ in range(11)]
    batches = _batch_chunks(chunks)

    assert [len(batch) for batch in batches] == [1] * 11
    assert all(len(batch) <= 10 for batch in batches)
    assert all(sum(len(item.content_text) for item in batch) <= 1_200 for batch in batches)

    short_batches = _batch_chunks(
        [SimpleNamespace(content_text="short") for _ in range(3)]
    )
    assert [len(batch) for batch in short_batches] == [1, 1, 1]


def test_semantic_migration_registers_executor_and_all_kinds_fail_closed() -> None:
    root = Path(__file__).resolve().parents[2]
    source = (
        root
        / "backend/migrations/versions/20260829_0028_semantic_index_schema.py"
    ).read_text(encoding="utf-8")
    assert "'embedding.index_batch','dashscope-embedding','embedding-worker'" in source
    upgraded = source.split("def downgrade() -> None:", 1)[0]
    assert "IF NOT EXISTS (" in upgraded
    assert "NEW.job_kind LIKE 'narration.%'" not in upgraded


def test_preflight_generation_cancel_settles_job_and_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batch = SimpleNamespace(state="queued", failure_code=None, completed_at=None)
    job = SimpleNamespace(state="running")
    session = SimpleNamespace(
        scalar=lambda _statement: batch,
        get=lambda model, _identity: job if model is worker.BackgroundJob else None,
        flush=lambda: None,
    )
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        worker,
        "fail_attempt",
        lambda _session, **kwargs: calls.append(kwargs),
    )
    lease = SimpleNamespace(fence=SimpleNamespace(job_id=uuid4()))

    worker._settle_preflight_failure(
        session,
        lease=lease,
        error=EmbeddingLifecycleError(
            "generation_cancelled", "novel index build is not active"
        ),
    )

    assert calls[0]["classification"] == "non_retryable"
    assert calls[0]["error_code"] == "GENERATION_CANCELLED"
    assert batch.state == "cancelled"
    assert batch.failure_code == "GENERATION_CANCELLED"
    assert batch.completed_at is not None
