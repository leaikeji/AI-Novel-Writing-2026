"""In-process lifecycle for the persistent embedding worker."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
import os
from pathlib import Path
from threading import Event, Lock, Thread, current_thread

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from ..background.scheduler import NarrationJobScheduler, SchedulerConfig
from ..creative_data_models import (
    EmbeddingConfiguration,
    EmbeddingGeneration,
    EmbeddingGenerationNovel,
)
from ..database import get_engine
from ..narration.contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID
from .api import SECRET_DIR_ENV, SECRET_ROOT_ENV
from .secrets import EmbeddingSecretStore
from .worker import execute_embedding_batch


# A 10-item, 2048-dimension response can remain active for longer than the
# narration scheduler's generic lease while the transport is still making
# progress.  The longer lease prevents maintenance from duplicating an
# in-flight external request.
EMBEDDING_JOB_LEASE_SECONDS = 600


@dataclass(frozen=True, slots=True)
class EmbeddingRuntimeSnapshot:
    state: str = "stopped"
    claimed_count: int = 0
    completed_count: int = 0
    last_job_at: datetime | None = None
    error_code: str | None = None


_thread_lock = Lock()
_thread: Thread | None = None
_stop_event: Event | None = None
_thread_loop: asyncio.AbstractEventLoop | None = None
_thread_task: asyncio.Task[None] | None = None
_snapshot = EmbeddingRuntimeSnapshot()


def embedding_runtime_status() -> dict[str, object]:
    return asdict(_snapshot)


def semantic_retrieval_enabled() -> bool:
    """Return whether one active generation can serve at least one novel."""

    try:
        factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
        with factory() as session:
            configuration = session.scalar(
                select(EmbeddingConfiguration).where(
                    EmbeddingConfiguration.owner_id == LOCAL_OWNER_ID,
                    EmbeddingConfiguration.workspace_id == LOCAL_WORKSPACE_ID,
                )
            )
            if configuration is None or configuration.active_generation_id is None:
                return False
            generation = session.get(
                EmbeddingGeneration, configuration.active_generation_id
            )
            if generation is None or generation.state != "active":
                return False
            ready_novels = int(
                session.scalar(
                    select(func.count())
                    .select_from(EmbeddingGenerationNovel)
                    .where(
                        EmbeddingGenerationNovel.generation_id == generation.id,
                        EmbeddingGenerationNovel.state == "ready",
                    )
                )
                or 0
            )
            return ready_novels > 0
    except Exception:
        return False


def _store_from_environment() -> EmbeddingSecretStore:
    root = os.environ.get(SECRET_ROOT_ENV, "").strip()
    records = os.environ.get(SECRET_DIR_ENV, "").strip()
    if not root or not records:
        raise RuntimeError("EMBEDDING_SECRET_PATHS_UNCONFIGURED")
    return EmbeddingSecretStore(root_key_path=Path(root), records_dir=Path(records))


async def _run(stop_event: Event) -> None:
    global _snapshot
    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    scheduler = NarrationJobScheduler(
        factory,
        config=SchedulerConfig(
            lease_owner="embedding-worker:local",
            executor_key="embedding-worker",
            resource_classes=("dashscope-embedding",),
            job_kinds=("embedding.index_batch",),
            lease_seconds=EMBEDDING_JOB_LEASE_SECONDS,
        ),
    )
    _snapshot = EmbeddingRuntimeSnapshot(state="ready")
    while not stop_event.is_set():
        try:
            scheduler.maintain_once()
            scheduled = scheduler.claim_next_typed_job()
            if scheduled is None:
                await asyncio.sleep(1.0)
                continue
            _snapshot = replace(
                _snapshot, claimed_count=_snapshot.claimed_count + 1,
                last_job_at=datetime.now(UTC), error_code=None,
            )
            await execute_embedding_batch(
                lease=scheduled.lease,
                session_factory=factory,
                secret_store=_store_from_environment(),
            )
            _snapshot = replace(
                _snapshot, completed_count=_snapshot.completed_count + 1,
                last_job_at=datetime.now(UTC), error_code=None,
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            code = getattr(error, "code", None)
            _snapshot = replace(
                _snapshot,
                state="degraded",
                error_code=(code if isinstance(code, str) else type(error).__name__)[:96],
            )
            await asyncio.sleep(2.0)


def _thread_main(stop_event: Event) -> None:
    """Own the complete scheduler and network event-loop lifecycle."""

    async def runner() -> None:
        global _thread_loop, _thread_task
        loop = asyncio.get_running_loop()
        task = asyncio.current_task()
        with _thread_lock:
            _thread_loop = loop
            _thread_task = task
        try:
            await _run(stop_event)
        finally:
            with _thread_lock:
                if _thread_loop is loop:
                    _thread_loop = None
                if _thread_task is task:
                    _thread_task = None

    try:
        asyncio.run(runner())
    except asyncio.CancelledError:
        global _snapshot
        _snapshot = EmbeddingRuntimeSnapshot(
            state="stopped",
            error_code="EMBEDDING_WORKER_CANCELLED",
        )
    except BaseException as error:
        _snapshot = EmbeddingRuntimeSnapshot(
            state="degraded",
            error_code=type(error).__name__[:96],
        )
    finally:
        global _thread, _stop_event
        worker = current_thread()
        with _thread_lock:
            if _thread is worker:
                _thread = None
                _stop_event = None


async def launch_embedding_runtime() -> None:
    global _stop_event, _thread
    with _thread_lock:
        if _thread is not None and _thread.is_alive():
            return
        stop_event = Event()
        thread = Thread(
            target=_thread_main,
            args=(stop_event,),
            name="ai-novel-embedding-worker",
            daemon=True,
        )
        _stop_event = stop_event
        _thread = thread
        thread.start()


async def stop_embedding_runtime() -> None:
    global _snapshot
    with _thread_lock:
        thread = _thread
        stop_event = _stop_event
        loop = _thread_loop
        task = _thread_task
    if stop_event is not None:
        stop_event.set()
    if loop is not None and task is not None:
        loop.call_soon_threadsafe(task.cancel)
    if thread is not None and thread is not current_thread():
        thread.join(timeout=5.0)
    alive = thread is not None and thread.is_alive()
    _snapshot = EmbeddingRuntimeSnapshot(
        state="stopping" if alive else "stopped",
        error_code="EMBEDDING_WORKER_STOP_PENDING" if alive else None,
    )
