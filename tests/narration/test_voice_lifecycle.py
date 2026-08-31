from __future__ import annotations

import asyncio
import threading
from collections import deque
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy.dialects import postgresql

from backend.narration.voice_deletion import (
    RECONCILIATION_BATCH_LIMIT,
    VoiceDeletionReconciliationBatch,
    VoiceDeletionService,
    _reconciliation_candidate_statement,
)
from backend.narration.voice_lifecycle import (
    MAX_IDLE_SECONDS,
    PrivateVoiceLifecycleProfile,
    PrivateVoiceLifecycleSnapshot,
    VoiceDeletionReconciler,
)


class _FakeDeletionService(VoiceDeletionService):
    def __init__(self) -> None:
        self.callback = None
        self.batches: deque[VoiceDeletionReconciliationBatch] = deque()
        self.processed: list[UUID] = []
        self.select_calls: list[tuple[tuple[UUID, ...], int]] = []
        self.next_deadline: datetime | None = None
        self.selected = threading.Event()
        self.finished = threading.Event()
        self.deadline_error: BaseException | None = None

    def set_state_change_callback(self, callback):  # type: ignore[no-untyped-def]
        self.callback = callback

    def select_reconciliation_batch(
        self,
        *,
        exclude_request_ids=(),  # type: ignore[no-untyped-def]
        limit=RECONCILIATION_BATCH_LIMIT,  # type: ignore[no-untyped-def]
        now=None,  # type: ignore[no-untyped-def]
    ) -> VoiceDeletionReconciliationBatch:
        del now
        self.select_calls.append((tuple(exclude_request_ids), limit))
        self.selected.set()
        if self.batches:
            return self.batches.popleft()
        return VoiceDeletionReconciliationBatch(request_ids=(), has_more=False)

    def reconcile_request(
        self,
        request_id: UUID,
        *,
        actor: str = "voice-deletion-reconciler",
    ):  # type: ignore[no-untyped-def]
        assert actor == "voice-deletion-reconciler"
        self.processed.append(request_id)
        if not self.batches:
            self.finished.set()
        return object()

    def next_reconciliation_deadline(self, *, now=None):  # type: ignore[no-untyped-def]
        del now
        if self.deadline_error is not None:
            raise self.deadline_error
        return self.next_deadline


def test_reconciliation_query_is_bounded_skip_locked_and_stably_ordered() -> None:
    now = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
    excluded = (uuid4(), uuid4())
    statement = _reconciliation_candidate_statement(
        current=now,
        exclude_request_ids=excluded,
        limit=RECONCILIATION_BATCH_LIMIT,
    )
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "LIMIT 25" in sql
    assert "voice_deletion_requests.requested_at" in sql
    assert all(str(request_id) in sql for request_id in excluded)


def test_lifecycle_projection_contract_has_server_authoritative_fields() -> None:
    now = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
    novel_id = uuid4()
    profile = PrivateVoiceLifecycleProfile(
        profile_id=uuid4(),
        novel_id=novel_id,
        current_version_id=uuid4(),
        display_name="私人音色",
        source_type="generated",
        profile_version=2,
        eligibility="unreferenced",
        blocked_reason=None,
        reference_count=0,
        asset_count=1,
        total_bytes=42,
        impact={"impact_summary": "未发现当前或历史朗读引用。"},
        impact_summary="未发现当前或历史朗读引用。",
        active_request=None,
    )
    snapshot = PrivateVoiceLifecycleSnapshot(
        schema_version="private-voice-lifecycle/1",
        novel_id=novel_id,
        server_now=now,
        items=(profile,),
    )
    assert snapshot.server_now == now
    assert snapshot.items[0].eligibility == "unreferenced"
    assert snapshot.items[0].reference_count == 0


def test_reconciler_rejects_a_polling_interval_above_sixty_seconds() -> None:
    service = _FakeDeletionService()
    with pytest.raises(ValueError, match="60"):
        VoiceDeletionReconciler(
            service,
            idle_fallback_seconds=MAX_IDLE_SECONDS + 0.1,
        )


@pytest.mark.asyncio
async def test_reconciler_startup_scan_processes_bounded_batches_and_stops_cleanly() -> None:
    service = _FakeDeletionService()
    first = tuple(uuid4() for _ in range(RECONCILIATION_BATCH_LIMIT))
    second = tuple(uuid4() for _ in range(2))
    service.batches.extend(
        (
            VoiceDeletionReconciliationBatch(request_ids=first, has_more=True),
            VoiceDeletionReconciliationBatch(request_ids=second, has_more=False),
        )
    )
    service.next_deadline = datetime.now(timezone.utc) + timedelta(hours=1)
    reconciler = VoiceDeletionReconciler(service)

    await reconciler.start()
    assert await asyncio.wait_for(asyncio.to_thread(service.finished.wait), timeout=1.0)
    assert reconciler.healthy is True
    await reconciler.stop()

    assert service.processed == [*first, *second]
    assert all(limit == RECONCILIATION_BATCH_LIMIT for _excluded, limit in service.select_calls)
    assert service.select_calls[0][0] == ()
    assert service.select_calls[1][0] == first
    assert service.callback is None
    assert reconciler.running is False


@pytest.mark.asyncio
async def test_reconciler_event_wakes_an_idle_cycle_without_five_second_polling() -> None:
    service = _FakeDeletionService()
    service.next_deadline = datetime.now(timezone.utc) + timedelta(hours=1)
    reconciler = VoiceDeletionReconciler(service)
    await reconciler.start()
    assert await asyncio.wait_for(asyncio.to_thread(service.selected.wait), timeout=1.0)

    request_id = uuid4()
    service.finished.clear()
    service.batches.append(
        VoiceDeletionReconciliationBatch(request_ids=(request_id,), has_more=False)
    )
    assert service.callback is not None
    service.callback()

    assert await asyncio.wait_for(asyncio.to_thread(service.finished.wait), timeout=1.0)
    await reconciler.stop()
    assert request_id in service.processed


@pytest.mark.asyncio
async def test_reconciler_crash_is_observable_for_readiness_fail_closed() -> None:
    service = _FakeDeletionService()
    service.deadline_error = RuntimeError("database unavailable")
    crashed = threading.Event()
    observed: list[BaseException] = []

    def on_crash(error: BaseException) -> None:
        observed.append(error)
        crashed.set()

    reconciler = VoiceDeletionReconciler(service, on_crash=on_crash)
    await reconciler.start()
    assert await asyncio.wait_for(asyncio.to_thread(crashed.wait), timeout=1.0)
    assert reconciler.healthy is False
    assert isinstance(reconciler.last_error, RuntimeError)
    assert observed and str(observed[0]) == "database unavailable"
    await reconciler.stop()
