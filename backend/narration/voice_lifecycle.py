"""Novel-scoped private voice lifecycle projection and deletion reconciliation.

The lifecycle service keeps eligibility and impact authoritative on the server.
The reconciler is event-driven, performs one startup scan, sleeps until the
nearest durable deadline, and uses a 60-second maximum idle fallback.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import VoiceDeletionRequest, VoiceProfile, VoiceProfileVersion
from .contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID
from .services import NarrationCasConflict, NarrationScopeMismatch
from .storage import StorageError
from .voice_deletion import (
    ACTIVE_REQUEST_STATES,
    PRIVATE_SOURCE_TYPES,
    RECONCILIATION_BATCH_LIMIT,
    SessionFactory,
    VoiceDeletionConflict,
    VoiceDeletionNotFound,
    VoiceDeletionRequestSnapshot,
    VoiceDeletionService,
    _request_snapshot,
    _require_local_novel,
    _transaction,
    compute_voice_deletion_impact,
)


MAX_IDLE_SECONDS: Final = 60.0
RECONCILER_ACTOR: Final = "voice-deletion-reconciler"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class PrivateVoiceLifecycleProfile:
    profile_id: UUID
    novel_id: UUID
    current_version_id: UUID | None
    display_name: str
    source_type: str
    profile_version: int
    eligibility: str
    blocked_reason: str | None
    reference_count: int
    asset_count: int
    total_bytes: int
    impact: dict[str, object]
    impact_summary: str
    active_request: VoiceDeletionRequestSnapshot | None


@dataclass(frozen=True, slots=True)
class PrivateVoiceLifecycleSnapshot:
    schema_version: str
    novel_id: UUID
    server_now: datetime
    items: tuple[PrivateVoiceLifecycleProfile, ...]


class PrivateVoiceLifecycleService:
    def __init__(self, session_factory: SessionFactory) -> None:
        if not callable(session_factory):
            raise TypeError("private voice lifecycle requires a session factory")
        self._session_factory = session_factory

    def list_profiles(self, *, novel_id: UUID) -> PrivateVoiceLifecycleSnapshot:
        if type(novel_id) is not UUID:
            raise ValueError("novel_id must be an exact UUID")

        def operation(session: Session) -> PrivateVoiceLifecycleSnapshot:
            _require_local_novel(session, novel_id, for_update=False)
            now = _utc_now()
            profiles = tuple(
                session.scalars(
                    select(VoiceProfile)
                    .where(
                        VoiceProfile.owner_id == LOCAL_OWNER_ID,
                        VoiceProfile.workspace_id == LOCAL_WORKSPACE_ID,
                        VoiceProfile.novel_id == novel_id,
                        VoiceProfile.status != "unavailable",
                    )
                    .order_by(VoiceProfile.name, VoiceProfile.id)
                ).all()
            )
            if not profiles:
                return PrivateVoiceLifecycleSnapshot(
                    schema_version="private-voice-lifecycle/1",
                    novel_id=novel_id,
                    server_now=now,
                    items=(),
                )
            profile_ids = tuple(profile.id for profile in profiles)
            versions_by_profile: dict[UUID, list[VoiceProfileVersion]] = {
                profile_id: [] for profile_id in profile_ids
            }
            for version in session.scalars(
                select(VoiceProfileVersion)
                .where(VoiceProfileVersion.profile_id.in_(profile_ids))
                .order_by(
                    VoiceProfileVersion.profile_id,
                    VoiceProfileVersion.version_number,
                    VoiceProfileVersion.id,
                )
            ):
                versions_by_profile[version.profile_id].append(version)
            active_by_profile = {
                row.voice_profile_id: row
                for row in session.scalars(
                    select(VoiceDeletionRequest)
                    .where(
                        VoiceDeletionRequest.owner_id == LOCAL_OWNER_ID,
                        VoiceDeletionRequest.workspace_id == LOCAL_WORKSPACE_ID,
                        VoiceDeletionRequest.novel_id == novel_id,
                        VoiceDeletionRequest.state.in_(ACTIVE_REQUEST_STATES),
                    )
                    .order_by(
                        VoiceDeletionRequest.voice_profile_id,
                        VoiceDeletionRequest.requested_at.desc(),
                        VoiceDeletionRequest.id.desc(),
                    )
                )
            }
            items: list[PrivateVoiceLifecycleProfile] = []
            for profile in profiles:
                versions = versions_by_profile[profile.id]
                current = next(
                    (
                        version
                        for version in versions
                        if version.id == profile.current_version_id
                    ),
                    None,
                )
                private_versions = [
                    version
                    for version in versions
                    if version.source_type in PRIVATE_SOURCE_TYPES
                ]
                if current is not None and current.source_type == "preset":
                    continue
                if not private_versions:
                    continue
                source_type = (
                    current.source_type
                    if current is not None
                    and current.source_type in PRIVATE_SOURCE_TYPES
                    else private_versions[-1].source_type
                )
                active_row = active_by_profile.get(profile.id)
                active_request = (
                    _request_snapshot(active_row, now=now)
                    if active_row is not None
                    else None
                )
                if active_request is not None:
                    impact = active_request.impact
                    reference_count = active_request.reference_count
                    eligibility = active_request.eligibility
                    blocked_reason = (
                        active_request.failure_code
                        if active_request.terminal
                        and active_request.state == "failed"
                        else None
                    )
                else:
                    blocked_reason = None
                    if current is None:
                        blocked_reason = "VOICE_DELETE_CURRENT_VERSION_MISSING"
                    elif any(version.source_type == "preset" for version in versions):
                        blocked_reason = "VOICE_DELETE_MIXED_SOURCE_BLOCKED"
                    elif profile.status == "unavailable":
                        blocked_reason = "VOICE_DELETE_PROFILE_UNAVAILABLE"
                    try:
                        deletion_impact = compute_voice_deletion_impact(
                            session,
                            novel_id,
                            profile.id,
                            for_update=False,
                        )
                    except (VoiceDeletionConflict, NarrationScopeMismatch):
                        deletion_impact = None
                        blocked_reason = blocked_reason or "VOICE_DELETE_UNSAFE_EVIDENCE"
                    if deletion_impact is None:
                        impact = {
                            "schema_version": "private-voice-deletion-impact/2",
                            "profile_id": str(profile.id),
                            "novel_id": str(novel_id),
                            "profile_version": profile.version,
                            "voice_version_ids": [],
                            "current_narrator_count": 0,
                            "character_binding_count": 0,
                            "anonymous_speaker_count": 0,
                            "generic_slot_count": 0,
                            "historical_edition_count": 0,
                            "render_count": 0,
                            "export_count": 0,
                            "current_reference_count": 0,
                            "historical_reference_count": 0,
                            "reference_count": 0,
                            "asset_count": 0,
                            "total_bytes": 0,
                            "active_job_count": 0,
                            "external_backup_status": "unmanaged",
                            "historical_audio_consequence": None,
                            "impact_summary": "当前证据不足，删除保持关闭。",
                        }
                        reference_count = 0
                    else:
                        impact = deletion_impact.payload()
                        reference_count = deletion_impact.reference_count
                    eligibility = (
                        "blocked"
                        if blocked_reason is not None
                        else ("referenced" if reference_count else "unreferenced")
                    )
                asset_count = _nonnegative_int(impact.get("asset_count"))
                total_bytes = _nonnegative_int(impact.get("total_bytes"))
                summary = impact.get("impact_summary")
                items.append(
                    PrivateVoiceLifecycleProfile(
                        profile_id=profile.id,
                        novel_id=novel_id,
                        current_version_id=profile.current_version_id,
                        display_name=profile.name,
                        source_type=source_type,
                        profile_version=profile.version,
                        eligibility=eligibility,
                        blocked_reason=blocked_reason,
                        reference_count=reference_count,
                        asset_count=asset_count,
                        total_bytes=total_bytes,
                        impact=impact,
                        impact_summary=(
                            summary if type(summary) is str else "删除影响待重新加载。"
                        ),
                        active_request=active_request,
                    )
                )
            return PrivateVoiceLifecycleSnapshot(
                schema_version="private-voice-lifecycle/1",
                novel_id=novel_id,
                server_now=now,
                items=tuple(items),
            )

        return _transaction(self._session_factory, operation)


def _nonnegative_int(value: object) -> int:
    return value if type(value) is int and value >= 0 else 0


class VoiceDeletionReconciler:
    """One event-driven reconciler for durable voice deletion requests."""

    def __init__(
        self,
        service: VoiceDeletionService,
        *,
        idle_fallback_seconds: float = MAX_IDLE_SECONDS,
        clock: Callable[[], datetime] = _utc_now,
        on_crash: Callable[[BaseException], None] | None = None,
    ) -> None:
        if not isinstance(service, VoiceDeletionService):
            raise TypeError("voice deletion reconciler requires VoiceDeletionService")
        if not 0 < idle_fallback_seconds <= MAX_IDLE_SECONDS:
            raise ValueError("voice deletion idle fallback must be in (0, 60]")
        if not callable(clock):
            raise TypeError("voice deletion reconciler clock must be callable")
        if on_crash is not None and not callable(on_crash):
            raise TypeError("voice deletion reconciler crash callback must be callable")
        self._service = service
        self._idle_fallback_seconds = float(idle_fallback_seconds)
        self._clock = clock
        self._on_crash = on_crash
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake_event: asyncio.Event | None = None
        self._task: asyncio.Task[None] | None = None
        self._accepting = False
        self._pending_wake = False
        self._healthy = False
        self._last_error: BaseException | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def healthy(self) -> bool:
        return self._healthy and self.running

    @property
    def last_error(self) -> BaseException | None:
        return self._last_error

    async def start(self) -> None:
        if self.running:
            return
        self._loop = asyncio.get_running_loop()
        self._wake_event = asyncio.Event()
        if self._pending_wake:
            self._wake_event.set()
            self._pending_wake = False
        self._accepting = True
        self._healthy = True
        self._last_error = None
        self._service.set_state_change_callback(self.wake)
        self._task = asyncio.create_task(
            self._run(),
            name="voice-deletion-reconciler",
        )
        await asyncio.sleep(0)

    def wake(self) -> None:
        loop = self._loop
        event = self._wake_event
        if loop is None or event is None or not loop.is_running():
            self._pending_wake = True
            return
        loop.call_soon_threadsafe(event.set)

    async def stop(self) -> None:
        self._accepting = False
        self._service.set_state_change_callback(None)
        self.wake()
        task = self._task
        if task is not None:
            await task
        self._task = None
        self._loop = None
        self._wake_event = None
        self._healthy = False

    async def _run(self) -> None:
        try:
            while self._accepting:
                event = self._wake_event
                if event is None:
                    raise RuntimeError("voice deletion reconciler event is unavailable")
                event.clear()
                await self._process_ready_sets()
                if not self._accepting:
                    break
                if event.is_set():
                    continue
                deadline = await asyncio.to_thread(
                    self._service.next_reconciliation_deadline
                )
                timeout = self._idle_fallback_seconds
                if deadline is not None:
                    timeout = min(
                        timeout,
                        max(0.0, (deadline - self._clock()).total_seconds()),
                    )
                if timeout <= 0:
                    await asyncio.sleep(0)
                    continue
                try:
                    await asyncio.wait_for(event.wait(), timeout=timeout)
                except TimeoutError:
                    pass
        except asyncio.CancelledError:
            raise
        except BaseException as error:
            self._healthy = False
            self._last_error = error
            callback = self._on_crash
            if callback is not None:
                try:
                    callback(error)
                except Exception:
                    pass
        finally:
            self._accepting = False

    async def _process_ready_sets(self) -> None:
        processed: list[UUID] = []
        while self._accepting:
            batch = await asyncio.to_thread(
                self._service.select_reconciliation_batch,
                exclude_request_ids=tuple(processed),
                limit=RECONCILIATION_BATCH_LIMIT,
            )
            if not batch.request_ids:
                return
            for request_id in batch.request_ids:
                try:
                    await asyncio.to_thread(
                        self._service.reconcile_request,
                        request_id,
                        actor=RECONCILER_ACTOR,
                    )
                except (
                    OSError,
                    StorageError,
                    VoiceDeletionConflict,
                    VoiceDeletionNotFound,
                    NarrationCasConflict,
                    NarrationScopeMismatch,
                ):
                    # Expected per-request races/failures have either converged to
                    # a durable state or will be reconsidered on the next event.
                    pass
                processed.append(request_id)
            if not batch.has_more or not self._accepting:
                return


__all__ = [
    "PrivateVoiceLifecycleProfile",
    "PrivateVoiceLifecycleService",
    "PrivateVoiceLifecycleSnapshot",
    "VoiceDeletionReconciler",
]
