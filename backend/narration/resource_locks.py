"""Independent persistent resource leases for single-flight work.

Resource leases are intentionally separate from job-attempt leases.  A heavy
worker must hold both fences, and must validate both inside the same short
database transaction before publishing an authoritative result.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Final
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session

from ..models import BackgroundResourceClassSlot, BackgroundResourceLock


UTC: Final = timezone.utc
DEFAULT_RESOURCE_LEASE_SECONDS: Final = 120
MIN_RESOURCE_LEASE_SECONDS: Final = 1
MAX_RESOURCE_LEASE_SECONDS: Final = 3_600


class ResourceLockError(RuntimeError):
    """Base class for persistent resource-lock failures."""


class ResourceLockValidationError(ResourceLockError, ValueError):
    """A resource lease input violates the frozen storage contract."""


class ResourceBusyError(ResourceLockError):
    """A non-expired resource lease is already owned."""


class ResourceFenceError(ResourceLockError):
    """A resource token/generation is stale, expired, or absent."""


@dataclass(frozen=True, slots=True)
class ResourceFence:
    resource_key: str
    lease_owner: str
    lease_token: UUID
    lease_generation: int


@dataclass(frozen=True, slots=True)
class ResourceLease:
    fence: ResourceFence
    lease_until: datetime


def _bounded_text(value: str, *, field_name: str, maximum: int) -> str:
    if type(value) is not str:
        raise ResourceLockValidationError(f"{field_name} must be a string")
    if not value or value != value.strip() or len(value) > maximum:
        raise ResourceLockValidationError(
            f"{field_name} must be non-empty, trimmed, and at most {maximum} characters"
        )
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ResourceLockValidationError(
            f"{field_name} cannot contain control characters"
        )
    return value


def _exact_int(
    value: int,
    *,
    field_name: str,
    minimum: int,
    maximum: int,
) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ResourceLockValidationError(
            f"{field_name} must be an exact integer in [{minimum}, {maximum}]"
        )
    return value


def _duration(seconds: int) -> timedelta:
    return timedelta(
        seconds=_exact_int(
            seconds,
            field_name="lease_seconds",
            minimum=MIN_RESOURCE_LEASE_SECONDS,
            maximum=MAX_RESOURCE_LEASE_SECONDS,
        )
    )


def _input_now(value: datetime) -> datetime:
    if type(value) is not datetime or value.tzinfo is None:
        raise ResourceLockValidationError(
            "now must be a timezone-aware datetime"
        )
    return value.astimezone(UTC)


def _database_datetime(value: datetime, *, field_name: str) -> datetime:
    if type(value) is not datetime:
        raise ResourceLockError(f"database returned a non-datetime {field_name}")
    # SQLite is test-only and drops timezone metadata for UTC values.
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _dialect_name(session: Session) -> str:
    return session.get_bind().dialect.name


def _validate_test_clock_hook(
    session: Session, test_only_now: datetime | None
) -> None:
    """Reject caller-controlled production time before taking any lock.

    ``test_only_now`` deliberately exists only for the SQLite transaction fake.
    PostgreSQL always reads ``clock_timestamp()`` *after* acquiring the rows it
    will use for a fencing decision.  Supporting an arbitrary third dialect
    would silently weaken that guarantee, so it is rejected.
    """

    dialect = _dialect_name(session)
    if dialect not in {"postgresql", "sqlite"}:
        raise ResourceLockError(
            f"unsupported resource-lock database dialect {dialect!r}"
        )
    if test_only_now is not None:
        _input_now(test_only_now)
        if dialect != "sqlite":
            raise ResourceLockValidationError(
                "test_only_now is permitted only by the SQLite test path"
            )


def _clock_after_lock(
    session: Session, test_only_now: datetime | None
) -> datetime:
    """Read one authoritative mutation time after the relevant row lock."""

    if _dialect_name(session) == "sqlite":
        if test_only_now is not None:
            return _input_now(test_only_now)
        value = session.scalar(select(func.current_timestamp()))
    else:
        # PostgreSQL ``now()`` is the transaction-start timestamp.  It can be
        # stale after waiting on FOR UPDATE and must never decide lease expiry.
        value = session.scalar(select(func.clock_timestamp()))
    return _database_datetime(value, field_name="authoritative clock")


def _lease(row: BackgroundResourceLock) -> ResourceLease:
    return ResourceLease(
        fence=ResourceFence(
            resource_key=row.resource_key,
            lease_owner=row.lease_owner,
            lease_token=row.lease_token,
            lease_generation=row.lease_generation,
        ),
        lease_until=_database_datetime(row.lease_until, field_name="lease_until"),
    )


def _row_for_update(
    session: Session, *, resource_key: str
) -> BackgroundResourceLock | None:
    return session.scalar(
        select(BackgroundResourceLock)
        .where(BackgroundResourceLock.resource_key == resource_key)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _registered_slot(
    session: Session,
    *,
    resource_key: str,
    for_update: bool,
) -> BackgroundResourceClassSlot:
    statement = (
        select(BackgroundResourceClassSlot)
        .where(
            BackgroundResourceClassSlot.resource_key == resource_key,
            BackgroundResourceClassSlot.enabled.is_(True),
        )
        .execution_options(populate_existing=True)
    )
    if for_update:
        statement = statement.with_for_update()
    slot = session.scalar(statement)
    if slot is None:
        raise ResourceLockValidationError(
            "resource_key is not an enabled registered resource slot"
        )
    return slot


def _validate_fence(
    row: BackgroundResourceLock | None,
    *,
    fence: ResourceFence,
    now: datetime,
) -> BackgroundResourceLock:
    if type(fence) is not ResourceFence:
        raise ResourceLockValidationError("fence must be a ResourceFence")
    _bounded_text(fence.lease_owner, field_name="lease_owner", maximum=160)
    if type(fence.lease_token) is not UUID:
        raise ResourceLockValidationError("lease_token must be a UUID")
    generation = _exact_int(
        fence.lease_generation,
        field_name="lease_generation",
        minimum=1,
        maximum=2**63 - 1,
    )
    if row is None:
        raise ResourceFenceError("resource lease does not exist")
    if (
        row.lease_owner != fence.lease_owner
        or row.lease_token != fence.lease_token
        or row.lease_generation != generation
    ):
        raise ResourceFenceError("resource lease token/generation is stale")
    if _database_datetime(row.lease_until, field_name="lease_until") <= now:
        raise ResourceFenceError("resource lease has expired")
    return row


def acquire_resource_lock(
    session: Session,
    *,
    resource_key: str,
    lease_owner: str,
    lease_seconds: int = DEFAULT_RESOURCE_LEASE_SECONDS,
    test_only_now: datetime | None = None,
) -> ResourceLease:
    """Acquire a free/expired resource and issue a fresh token/generation."""

    key = _bounded_text(resource_key, field_name="resource_key", maximum=160)
    owner = _bounded_text(lease_owner, field_name="lease_owner", maximum=160)
    duration = _duration(lease_seconds)
    _validate_test_clock_hook(session, test_only_now)
    _registered_slot(session, resource_key=key, for_update=True)
    initial_token = uuid4()
    row: BackgroundResourceLock | None
    inserted = False
    if _dialect_name(session) == "postgresql":
        statement = (
            postgresql_insert(BackgroundResourceLock.__table__)
            .values(
                resource_key=key,
                lease_owner=owner,
                lease_token=initial_token,
                lease_generation=1,
                # Provisional database-side values avoid accepting any caller
                # clock before the insert-or-conflict path owns the row.  They
                # are refreshed below with one post-lock clock read.
                lease_until=func.clock_timestamp() + duration,
                updated_at=func.clock_timestamp(),
            )
            .on_conflict_do_nothing(index_elements=["resource_key"])
            .returning(BackgroundResourceLock.resource_key)
        )
        inserted_key = session.scalar(statement)
        inserted = inserted_key is not None
        row = _row_for_update(session, resource_key=key)
    else:
        # Deterministic unit-test fallback.  Production races use the atomic
        # PostgreSQL insert-or-lock path above.
        row = _row_for_update(session, resource_key=key)
    current = _clock_after_lock(session, test_only_now)
    if inserted:
        if row is None:
            raise ResourceLockError("resource lock insert could not reload its row")
        row.lease_until = current + duration
        row.updated_at = current
        session.flush()
        return _lease(row)
    if _dialect_name(session) == "sqlite":
        if row is None:
            row = BackgroundResourceLock(
                resource_key=key,
                lease_owner=owner,
                lease_token=initial_token,
                lease_generation=1,
                lease_until=current + duration,
                updated_at=current,
            )
            session.add(row)
            session.flush()
            return _lease(row)
    if row is None:
        raise ResourceLockError("resource lock conflict could not reload its row")
    if _database_datetime(row.lease_until, field_name="lease_until") > current:
        raise ResourceBusyError(f"resource {key!r} has a live lease")
    previous_generation = _exact_int(
        row.lease_generation,
        field_name="stored lease_generation",
        minimum=1,
        maximum=2**63 - 2,
    )
    row.lease_owner = owner
    row.lease_token = uuid4()
    row.lease_generation = previous_generation + 1
    row.lease_until = current + duration
    row.updated_at = current
    session.flush()
    return _lease(row)


def lock_resource_publish_fence(
    session: Session,
    *,
    fence: ResourceFence,
    test_only_now: datetime | None = None,
) -> ResourceLease:
    """Lock/validate a resource fence for same-transaction publication."""

    if type(fence) is not ResourceFence:
        raise ResourceLockValidationError("fence must be a ResourceFence")
    _validate_test_clock_hook(session, test_only_now)
    _registered_slot(
        session,
        resource_key=_bounded_text(
            fence.resource_key, field_name="resource_key", maximum=160
        ),
        for_update=False,
    )
    row = _row_for_update(
        session,
        resource_key=_bounded_text(
            fence.resource_key, field_name="resource_key", maximum=160
        ),
    )
    current = _clock_after_lock(session, test_only_now)
    return _lease(_validate_fence(row, fence=fence, now=current))


def renew_resource_lock(
    session: Session,
    *,
    fence: ResourceFence,
    lease_seconds: int = DEFAULT_RESOURCE_LEASE_SECONDS,
    test_only_now: datetime | None = None,
) -> ResourceLease:
    """Extend only the exact current resource token/generation."""

    if type(fence) is not ResourceFence:
        raise ResourceLockValidationError("fence must be a ResourceFence")
    duration = _duration(lease_seconds)
    _validate_test_clock_hook(session, test_only_now)
    _registered_slot(
        session,
        resource_key=_bounded_text(
            fence.resource_key, field_name="resource_key", maximum=160
        ),
        for_update=False,
    )
    row = _row_for_update(
        session,
        resource_key=_bounded_text(
            fence.resource_key, field_name="resource_key", maximum=160
        ),
    )
    current = _clock_after_lock(session, test_only_now)
    locked = _validate_fence(row, fence=fence, now=current)
    old_until = _database_datetime(locked.lease_until, field_name="lease_until")
    locked.lease_until = max(old_until, current + duration)
    locked.updated_at = current
    session.flush()
    return _lease(locked)


def release_resource_lock(
    session: Session,
    *,
    fence: ResourceFence,
    test_only_now: datetime | None = None,
) -> None:
    """Fence a release while retaining the row for monotonic generations."""

    if type(fence) is not ResourceFence:
        raise ResourceLockValidationError("fence must be a ResourceFence")
    _validate_test_clock_hook(session, test_only_now)
    _registered_slot(
        session,
        resource_key=_bounded_text(
            fence.resource_key, field_name="resource_key", maximum=160
        ),
        for_update=False,
    )
    row = _row_for_update(
        session,
        resource_key=_bounded_text(
            fence.resource_key, field_name="resource_key", maximum=160
        ),
    )
    current = _clock_after_lock(session, test_only_now)
    locked = _validate_fence(row, fence=fence, now=current)
    # Do not physically delete: retaining the row makes every later acquisition
    # increment generation and prevents ABA after a normal release.
    # Rotate the secret token immediately.  The generation remains the last
    # issued generation while the row is free; the next acquisition advances
    # it exactly once.  Thus a cached generation-1 fence fails immediately on
    # release, and the next owner receives generation 2 (no ABA window).
    locked.lease_token = uuid4()
    locked.lease_until = current
    locked.updated_at = current
    session.flush()


__all__ = (
    "ResourceBusyError",
    "ResourceFence",
    "ResourceFenceError",
    "ResourceLease",
    "ResourceLockError",
    "ResourceLockValidationError",
    "acquire_resource_lock",
    "lock_resource_publish_fence",
    "release_resource_lock",
    "renew_resource_lock",
)
