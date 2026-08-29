"""In-process lifecycle for the persistent embedding worker."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
import os
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from ..background.scheduler import NarrationJobScheduler, SchedulerConfig
from ..database import get_engine
from .api import SECRET_DIR_ENV, SECRET_ROOT_ENV
from .secrets import EmbeddingSecretStore
from .worker import execute_embedding_batch


@dataclass(frozen=True, slots=True)
class EmbeddingRuntimeSnapshot:
    state: str = "stopped"
    claimed_count: int = 0
    completed_count: int = 0
    last_job_at: datetime | None = None
    error_code: str | None = None


_lock = asyncio.Lock()
_task: asyncio.Task[None] | None = None
_snapshot = EmbeddingRuntimeSnapshot()


def embedding_runtime_status() -> dict[str, object]:
    return asdict(_snapshot)


def _store_from_environment() -> EmbeddingSecretStore:
    root = os.environ.get(SECRET_ROOT_ENV, "").strip()
    records = os.environ.get(SECRET_DIR_ENV, "").strip()
    if not root or not records:
        raise RuntimeError("EMBEDDING_SECRET_PATHS_UNCONFIGURED")
    return EmbeddingSecretStore(root_key_path=Path(root), records_dir=Path(records))


async def _run() -> None:
    global _snapshot
    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    scheduler = NarrationJobScheduler(
        factory,
        config=SchedulerConfig(
            lease_owner="embedding-worker:local",
            executor_key="embedding-worker",
            resource_classes=("dashscope-embedding",),
            job_kinds=("embedding.index_batch",),
        ),
    )
    _snapshot = EmbeddingRuntimeSnapshot(state="ready")
    while True:
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
                lease=scheduled.lease, session_factory=factory,
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


async def launch_embedding_runtime() -> None:
    global _task
    async with _lock:
        if _task is not None and not _task.done():
            return
        _task = asyncio.create_task(_run(), name="ai-novel-embedding-worker")


async def stop_embedding_runtime() -> None:
    global _task, _snapshot
    async with _lock:
        task = _task
        _task = None
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    _snapshot = EmbeddingRuntimeSnapshot(state="stopped")
