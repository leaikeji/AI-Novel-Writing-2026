"""Short-transaction scheduler for persistent narration render jobs.

The scheduler is intentionally small: retry promotion, expired-attempt
reconciliation, and one fair claim are each committed before the caller starts
Nano, FFmpeg, filesystem, or network work.  The existing job service remains
the sole authority for priority aging, leases, fencing, and the single
``moss-nano:inference`` resource slot.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import BackgroundJob
from .contracts import NarrationRequestScope
from .jobs import (
    DEFAULT_AGING_QUANTUM_SECONDS,
    DEFAULT_LEASE_SECONDS,
    JobLease,
    ReconciledAttempt,
    claim_next_job,
    promote_due_retries,
    reconcile_expired_attempts,
)


class SessionFactory(Protocol):
    def __call__(self) -> Session: ...


class JobTerminalizer(Protocol):
    def __call__(self, session: Session, *, job_id: UUID) -> bool: ...


class ClaimGuard(Protocol):
    def __call__(self) -> bool: ...


class JobKindClaimReservation(Protocol):
    allowed_job_kinds: tuple[str, ...]

    def settle(self, claimed_job_kind: str | None) -> None: ...


class JobKindClaimGate(Protocol):
    def __call__(
        self,
        configured_job_kinds: tuple[str, ...],
    ) -> JobKindClaimReservation: ...


@dataclass(frozen=True, slots=True)
class SchedulerConfig:
    lease_owner: str
    executor_key: str = "narration-worker"
    resource_classes: tuple[str, ...] = ("moss-nano",)
    job_kinds: tuple[str, ...] = ("narration.segment_render",)
    novel_ids: tuple[UUID, ...] | None = None
    document_ids: tuple[UUID, ...] | None = None
    not_after: datetime | None = None
    lease_seconds: int = DEFAULT_LEASE_SECONDS
    aging_quantum_seconds: int = DEFAULT_AGING_QUANTUM_SECONDS
    retry_promotion_limit: int = 100
    reconciliation_limit: int = 1

    def validate(self) -> None:
        if (
            type(self.lease_owner) is not str
            or not self.lease_owner
            or self.lease_owner != self.lease_owner.strip()
            or len(self.lease_owner) > 160
        ):
            raise ValueError("scheduler lease_owner must be a normalized value")
        if (
            type(self.executor_key) is not str
            or not self.executor_key
            or self.executor_key != self.executor_key.strip()
            or len(self.executor_key) > 80
        ):
            raise ValueError("scheduler executor_key must be a normalized value")
        if (
            type(self.resource_classes) is not tuple
            or not self.resource_classes
            or len(self.resource_classes) != len(set(self.resource_classes))
            or any(
                type(value) is not str
                or not value
                or value != value.strip()
                or len(value) > 80
                for value in self.resource_classes
            )
        ):
            raise ValueError("scheduler resource_classes must be a unique normalized tuple")
        if (
            type(self.job_kinds) is not tuple
            or not self.job_kinds
            or len(self.job_kinds) != len(set(self.job_kinds))
            or any(
                type(value) is not str
                or not value
                or value != value.strip()
                or len(value) > 80
                for value in self.job_kinds
            )
        ):
            raise ValueError("scheduler job_kinds must be a unique normalized tuple")
        if self.novel_ids is not None and (
            type(self.novel_ids) is not tuple
            or not self.novel_ids
            or len(self.novel_ids) != len(set(self.novel_ids))
            or any(type(value) is not UUID for value in self.novel_ids)
        ):
            raise ValueError("scheduler novel_ids must be a unique non-empty UUID tuple")
        if self.document_ids is not None and (
            type(self.document_ids) is not tuple
            or not self.document_ids
            or len(self.document_ids) != len(set(self.document_ids))
            or any(type(value) is not UUID for value in self.document_ids)
        ):
            raise ValueError(
                "scheduler document_ids must be a unique non-empty UUID tuple"
            )
        if self.not_after is not None and (
            type(self.not_after) is not datetime
            or self.not_after.tzinfo is None
            or self.not_after.utcoffset() is None
        ):
            raise ValueError("scheduler not_after must be timezone-aware")
        for name, value, maximum in (
            ("lease_seconds", self.lease_seconds, 3_600),
            ("aging_quantum_seconds", self.aging_quantum_seconds, 86_400),
            ("retry_promotion_limit", self.retry_promotion_limit, 1_000),
            ("reconciliation_limit", self.reconciliation_limit, 1_000),
        ):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f"scheduler {name} is outside its bounded range")


@dataclass(frozen=True, slots=True)
class SchedulerMaintenance:
    promoted_job_ids: tuple[UUID, ...]
    reconciled_attempts: tuple[ReconciledAttempt, ...]


@dataclass(frozen=True, slots=True)
class ScheduledJob:
    """One claimed lease plus the frozen kind used for safe dispatch."""

    job_kind: str
    lease: JobLease


class NarrationJobScheduler:
    """Commit-bounded production adapter over ``backend.narration.jobs``."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        config: SchedulerConfig,
        scope: NarrationRequestScope = NarrationRequestScope.fixed_local(),
        terminalizers: Mapping[str, JobTerminalizer] | None = None,
        claim_guard: ClaimGuard | None = None,
        job_kind_claim_gate: JobKindClaimGate | None = None,
    ) -> None:
        if not callable(session_factory):
            raise TypeError("scheduler requires a callable Session factory")
        config.validate()
        scope.ensure_fixed_local()
        self._session_factory = session_factory
        self._config = config
        self._scope = scope
        resolved_terminalizers = dict(terminalizers or {})
        if any(
            type(job_kind) is not str
            or not job_kind
            or job_kind != job_kind.strip()
            or not callable(terminalizer)
            for job_kind, terminalizer in resolved_terminalizers.items()
        ):
            raise TypeError("scheduler terminalizers must map normalized kinds to callables")
        self._terminalizers = resolved_terminalizers
        if claim_guard is not None and not callable(claim_guard):
            raise TypeError("scheduler claim_guard must be callable")
        self._claim_guard = claim_guard
        if job_kind_claim_gate is not None and not callable(job_kind_claim_gate):
            raise TypeError("scheduler job_kind_claim_gate must be callable")
        self._job_kind_claim_gate = job_kind_claim_gate

    def _claim_allowed(self) -> bool:
        guard = self._claim_guard
        if guard is None:
            return True
        try:
            allowed = guard()
        except Exception:
            return False
        return allowed is True

    def _active(self) -> bool:
        deadline = self._config.not_after
        return deadline is None or datetime.now(timezone.utc) < deadline

    def _reserve_job_kinds(self) -> JobKindClaimReservation | None:
        gate = self._job_kind_claim_gate
        if gate is None:
            return _UnrestrictedJobKindReservation(self._config.job_kinds)
        try:
            reservation = gate(self._config.job_kinds)
            allowed = reservation.allowed_job_kinds
        except Exception:
            return None
        if (
            type(allowed) is not tuple
            or len(allowed) != len(set(allowed))
            or any(kind not in self._config.job_kinds for kind in allowed)
            or not callable(getattr(reservation, "settle", None))
        ):
            return None
        return reservation

    def _transaction(self, operation: Callable[[Session], object]) -> object:
        with self._session_factory() as session:
            try:
                result = operation(session)
                session.commit()
                return result
            except BaseException:
                session.rollback()
                raise

    def maintain_once(self) -> SchedulerMaintenance:
        """Promote due retries and reconcile at most one expired attempt.

        The two operations use separate commits so recovery never holds one
        attempt/resource lock while inspecting another job.
        """

        if not self._active():
            return SchedulerMaintenance(promoted_job_ids=(), reconciled_attempts=())
        promoted = self._transaction(
            lambda session: promote_due_retries(
                session,
                scope=self._scope,
                novel_ids=self._config.novel_ids,
                document_ids=self._config.document_ids,
                resource_classes=self._config.resource_classes,
                job_kinds=self._config.job_kinds,
                limit=self._config.retry_promotion_limit,
            )
        )

        def reconcile(session: Session) -> tuple[ReconciledAttempt, ...]:
            results = reconcile_expired_attempts(
                session,
                scope=self._scope,
                novel_ids=self._config.novel_ids,
                document_ids=self._config.document_ids,
                resource_classes=self._config.resource_classes,
                job_kinds=self._config.job_kinds,
                limit=self._config.reconciliation_limit,
            )
            terminal_ids = tuple(
                item.job_id
                for item in results
                if item.resulting_state in {"failed", "dead_letter", "cancelled"}
            )
            if terminal_ids and self._terminalizers:
                kinds = dict(
                    session.execute(
                        select(BackgroundJob.id, BackgroundJob.job_kind).where(
                            BackgroundJob.id.in_(terminal_ids)
                        )
                    ).all()
                )
                for job_id in terminal_ids:
                    terminalizer = self._terminalizers.get(kinds.get(job_id, ""))
                    if terminalizer is not None:
                        terminalizer(session, job_id=job_id)
            return results

        reconciled = self._transaction(reconcile)
        if type(promoted) is not tuple or type(reconciled) is not tuple:
            raise RuntimeError("job maintenance returned an invalid result")
        return SchedulerMaintenance(
            promoted_job_ids=promoted,
            reconciled_attempts=reconciled,
        )

    def _claim_next_typed_job(self) -> ScheduledJob | None:
        if not self._active() or not self._claim_allowed():
            return None
        reservation = self._reserve_job_kinds()
        if reservation is None:
            return None
        if not reservation.allowed_job_kinds:
            reservation.settle(None)
            return None
        allowed_job_kinds = reservation.allowed_job_kinds

        def claim(session: Session) -> ScheduledJob | None:
            lease = claim_next_job(
                session,
                scope=self._scope,
                lease_owner=self._config.lease_owner,
                novel_ids=self._config.novel_ids,
                document_ids=self._config.document_ids,
                resource_classes=self._config.resource_classes,
                job_kinds=allowed_job_kinds,
                lease_seconds=self._config.lease_seconds,
                aging_quantum_seconds=self._config.aging_quantum_seconds,
                executor_key=self._config.executor_key,
            )
            if lease is None:
                return None
            job_kind = (
                allowed_job_kinds[0]
                if len(allowed_job_kinds) == 1
                else session.scalar(
                    select(BackgroundJob.job_kind).where(
                        BackgroundJob.id == lease.fence.job_id
                    )
                )
            )
            if type(job_kind) is not str or job_kind not in allowed_job_kinds:
                raise RuntimeError("claimed job kind differs from the scheduler contract")
            return ScheduledJob(job_kind=job_kind, lease=lease)

        try:
            result = self._transaction(claim)
        except BaseException:
            reservation.settle(None)
            raise
        if result is not None and type(result) is not ScheduledJob:
            reservation.settle(None)
            raise RuntimeError("job claim returned an invalid lease")
        reservation.settle(result.job_kind if result is not None else None)
        return result

    def claim_next_typed_job(self) -> ScheduledJob | None:
        """Claim one fair configured Nano job and preserve its dispatch kind."""

        return self._claim_next_typed_job()

    def claim_next_job(self) -> JobLease | None:
        """Compatibility claim returning only the persistent lease."""

        scheduled = self._claim_next_typed_job()
        return scheduled.lease if scheduled is not None else None

    def claim_next_segment(self) -> JobLease | None:
        """Compatibility name retained for the segment worker protocol."""

        return self.claim_next_job()


__all__ = [
    "ClaimGuard",
    "JobKindClaimGate",
    "JobKindClaimReservation",
    "JobTerminalizer",
    "NarrationJobScheduler",
    "ScheduledJob",
    "SchedulerConfig",
    "SchedulerMaintenance",
    "SessionFactory",
]


@dataclass(frozen=True, slots=True)
class _UnrestrictedJobKindReservation:
    allowed_job_kinds: tuple[str, ...]

    def settle(self, claimed_job_kind: str | None) -> None:
        del claimed_job_kind
