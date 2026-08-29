"""Persistent background-job leases, fencing, retry, and cancellation.

Every mutating function expects a caller-owned *short* database transaction.
The functions flush but never commit or roll back.  Callers must finish external
I/O before opening the transaction that validates a result fence and publishes
authoritative database links.

PostgreSQL is the production database.  A deliberately narrower SQLite path is
kept only so deterministic service behavior can be unit-tested; PostgreSQL lock
semantics remain an integration-gate responsibility.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Final, Literal, Sequence
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    DateTime,
    and_,
    bindparam,
    case,
    cast,
    exists,
    func,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session, SessionTransaction

from ..models import (
    BackgroundExecutorEpoch,
    BackgroundJob,
    BackgroundJobAttempt,
    BackgroundJobKindPolicy,
    BackgroundManualRetryCommand,
    BackgroundResourceClassPolicy,
    BackgroundResourceClassSlot,
    BackgroundResourceLock,
    NarrationRequest,
)

from . import resource_locks as _resource_locks
from .contracts import NarrationRequestScope
from .resource_locks import ResourceFence, ResourceLease


UTC: Final = timezone.utc
DEFAULT_LEASE_SECONDS: Final = 120
MIN_LEASE_SECONDS: Final = 1
MAX_LEASE_SECONDS: Final = 3_600
DEFAULT_MAX_ATTEMPTS: Final = 3
MAX_MAX_ATTEMPTS: Final = 100
DEFAULT_RETRY_BASE_SECONDS: Final = 5
MAX_RETRY_DELAY_SECONDS: Final = 15 * 60
DEFAULT_AGING_QUANTUM_SECONDS: Final = 60
MIN_PRIORITY: Final = -1_000
MAX_PRIORITY: Final = 1_000
MAX_INTERACTIVE_BOOST_SECONDS: Final = 5 * 60
DEFAULT_EXECUTOR_KEY: Final = "narration-worker"

RENDER_JOB_KINDS: Final[frozenset[str]] = frozenset(
    {"narration.segment_render", "narration.export"}
)
TERMINAL_JOB_STATES: Final[frozenset[str]] = frozenset(
    {"succeeded", "failed", "dead_letter", "cancelled"}
)

_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,95}$")

RetryClassification = Literal["retryable", "non_retryable", "security_failure"]


class JobServiceError(RuntimeError):
    """Base class for fail-closed job service failures."""


class JobValidationError(JobServiceError, ValueError):
    """A caller supplied a value outside the frozen job contract."""


class JobNotFoundError(JobServiceError):
    """No job exists in the fixed local scope."""


class JobStateError(JobServiceError):
    """The requested operation is illegal for the current job state."""


class JobFenceError(JobServiceError):
    """An attempt lease is stale, expired, completed, or not current."""


class JobIdempotencyConflict(JobServiceError):
    """An idempotency key already names different canonical job input."""


class ManualRetryCommandRequired(JobStateError):
    """Compatibility alias retained for callers compiled against pre-0012."""


@dataclass(frozen=True, slots=True)
class EnqueueResult:
    job_id: UUID
    created: bool


@dataclass(frozen=True, slots=True)
class JobFence:
    job_id: UUID
    attempt_id: UUID
    lease_token: UUID
    lease_generation: int


@dataclass(frozen=True, slots=True)
class JobLease:
    fence: JobFence
    attempt_number: int
    retry_kind: Literal["initial", "automatic", "manual"]
    lease_owner: str
    lease_until: datetime
    executor_epoch_id: UUID | None = None
    resource_fence: ResourceFence | None = None


@dataclass(frozen=True, slots=True)
class ManualRetryResult:
    command_id: UUID
    job_id: UUID
    created: bool


@dataclass(frozen=True, slots=True)
class CancelRequestResult:
    job_id: UUID
    state: str
    changed: bool


@dataclass(frozen=True, slots=True)
class FailureResult:
    job_id: UUID
    state: Literal["retry_wait", "failed", "dead_letter"]
    next_retry_at: datetime | None


@dataclass(frozen=True, slots=True)
class ReconciledAttempt:
    job_id: UUID
    attempt_id: UUID
    resulting_state: Literal["retry_wait", "dead_letter", "failed", "cancelled"]


@dataclass(frozen=True, slots=True)
class PublicationFenceContext:
    """Proof that job -> attempt -> resource were locked in canonical order.

    It is intentionally transaction-scoped.  ``complete_attempt`` validates
    the exact fences again before success, while the caller may insert media or
    model-run rows between the initial check and completion in the same short
    transaction.
    """

    scope: NarrationRequestScope
    job_lease: JobLease
    resource_lease: ResourceLease
    resource_class: str
    checked_at: datetime
    _session: Session = field(repr=False, compare=False)
    _transaction: SessionTransaction = field(repr=False, compare=False)


def _bounded_text(value: str, *, field_name: str, maximum: int) -> str:
    if type(value) is not str:
        raise JobValidationError(f"{field_name} must be a string")
    if not value or value != value.strip() or len(value) > maximum:
        raise JobValidationError(
            f"{field_name} must be non-empty, trimmed, and at most {maximum} characters"
        )
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise JobValidationError(f"{field_name} cannot contain control characters")
    return value


def _uuid(value: UUID | None, *, field_name: str, optional: bool = False) -> UUID | None:
    if value is None and optional:
        return None
    if type(value) is not UUID:
        raise JobValidationError(f"{field_name} must be a UUID")
    return value


def _uuid_filter(
    values: Sequence[UUID] | None,
    *,
    field_name: str,
) -> tuple[UUID, ...] | None:
    """Normalize one optional, non-empty UUID filter without widening scope."""

    if values is None:
        return None
    if isinstance(values, (str, bytes)):
        raise JobValidationError(f"{field_name} must be a sequence of UUIDs")
    normalized = tuple(
        dict.fromkeys(
            _uuid(value, field_name=field_name.removesuffix("s"))
            for value in values
        )
    )
    if not normalized:
        raise JobValidationError(f"{field_name} cannot be empty")
    return normalized  # type: ignore[return-value]


def _text_filter(
    values: Sequence[str] | None,
    *,
    field_name: str,
    item_name: str,
) -> tuple[str, ...] | None:
    """Normalize one optional, non-empty scheduler text filter."""

    if values is None:
        return None
    if isinstance(values, (str, bytes)):
        raise JobValidationError(
            f"{field_name} must be a sequence of complete {item_name} names"
        )
    normalized = tuple(
        dict.fromkeys(
            _bounded_text(value, field_name=item_name, maximum=80)
            for value in values
        )
    )
    if not normalized:
        raise JobValidationError(f"{field_name} cannot be empty")
    return normalized


def _apply_background_job_filters(
    statement,  # type: ignore[no-untyped-def]
    *,
    novel_ids: Sequence[UUID] | None = None,
    document_ids: Sequence[UUID] | None = None,
    resource_classes: Sequence[str] | None = None,
    job_kinds: Sequence[str] | None = None,
):  # type: ignore[no-untyped-def]
    """Apply the same fail-closed job scope to claim and maintenance paths."""

    normalized_novel_ids = _uuid_filter(novel_ids, field_name="novel_ids")
    normalized_document_ids = _uuid_filter(
        document_ids,
        field_name="document_ids",
    )
    normalized_resource_classes = _text_filter(
        resource_classes,
        field_name="resource_classes",
        item_name="resource_class",
    )
    normalized_job_kinds = _text_filter(
        job_kinds,
        field_name="job_kinds",
        item_name="job_kind",
    )
    if normalized_novel_ids is not None:
        statement = statement.where(BackgroundJob.novel_id.in_(normalized_novel_ids))
    if normalized_document_ids is not None:
        statement = statement.where(
            or_(
                BackgroundJob.request_id.is_(None),
                BackgroundJob.request_id.in_(
                    select(NarrationRequest.id).where(
                        NarrationRequest.document_id.in_(normalized_document_ids)
                    )
                )
            )
        )
    if normalized_resource_classes is not None:
        statement = statement.where(
            BackgroundJob.resource_class.in_(normalized_resource_classes)
        )
    if normalized_job_kinds is not None:
        statement = statement.where(BackgroundJob.job_kind.in_(normalized_job_kinds))
    return statement


def _sha256(value: str, *, field_name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise JobValidationError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _error_code(value: str) -> str:
    if type(value) is not str or _ERROR_CODE.fullmatch(value) is None:
        raise JobValidationError("error_code must be a frozen-style uppercase code")
    return value


def _exact_int(
    value: int,
    *,
    field_name: str,
    minimum: int,
    maximum: int,
) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise JobValidationError(
            f"{field_name} must be an exact integer in [{minimum}, {maximum}]"
        )
    return value


def _lease_duration(seconds: int) -> timedelta:
    return timedelta(
        seconds=_exact_int(
            seconds,
            field_name="lease_seconds",
            minimum=MIN_LEASE_SECONDS,
            maximum=MAX_LEASE_SECONDS,
        )
    )


def _input_now(value: datetime) -> datetime:
    if type(value) is not datetime or value.tzinfo is None:
        raise JobValidationError("now must be a timezone-aware datetime")
    return value.astimezone(UTC)


def _database_datetime(value: datetime, *, field_name: str) -> datetime:
    if type(value) is not datetime:
        raise JobServiceError(f"database returned a non-datetime {field_name}")
    # SQLite drops timezone metadata.  It is test-only and all values written by
    # this module are UTC, so a naive test value is interpreted as UTC.
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _dialect_name(session: Session) -> str:
    return session.get_bind().dialect.name


def _validate_test_clock_hook(
    session: Session, test_only_now: datetime | None
) -> None:
    """Fail closed unless caller time is the explicit SQLite-only test hook."""

    dialect = _dialect_name(session)
    if dialect not in {"postgresql", "sqlite"}:
        raise JobServiceError(f"unsupported job database dialect {dialect!r}")
    if test_only_now is not None:
        _input_now(test_only_now)
        if dialect != "sqlite":
            raise JobValidationError(
                "test_only_now is permitted only by the SQLite test path"
            )


def _clock_after_lock(
    session: Session, test_only_now: datetime | None
) -> datetime:
    """Read a single authoritative time after all required rows are locked."""

    if _dialect_name(session) == "sqlite":
        if test_only_now is not None:
            return _input_now(test_only_now)
        value = session.scalar(select(func.current_timestamp()))
    else:
        # ``now()`` is transaction-start time in PostgreSQL and can therefore
        # resurrect an expired fence after a lock wait.  clock_timestamp() is
        # wall-clock time at this exact statement.
        value = session.scalar(select(func.clock_timestamp()))
    return _database_datetime(value, field_name="authoritative clock")


def _selection_clock(
    session: Session, test_only_now: datetime | None
) -> datetime:
    """Clock for SKIP LOCKED candidate selection (which never waits on rows)."""

    _validate_test_clock_hook(session, test_only_now)
    return _clock_after_lock(session, test_only_now)


def _scope(scope: NarrationRequestScope) -> NarrationRequestScope:
    if type(scope) is not NarrationRequestScope:
        raise JobValidationError("scope must be the frozen NarrationRequestScope")
    return scope.ensure_fixed_local()


def fairness_score(
    *,
    base_priority: int,
    created_at: datetime,
    now: datetime,
    interactive_priority: int | None = None,
    interactive_priority_expires_at: datetime | None = None,
    aging_quantum_seconds: int = DEFAULT_AGING_QUANTUM_SECONDS,
) -> int:
    """Return the exact stable score used by the claim query.

    Priority is higher-first.  One point is added for every full aging quantum,
    so a bounded old job eventually overtakes every fresh bounded priority.
    """

    base = _exact_int(
        base_priority,
        field_name="base_priority",
        minimum=MIN_PRIORITY,
        maximum=MAX_PRIORITY,
    )
    created = _input_now(created_at)
    current = _input_now(now)
    quantum = _exact_int(
        aging_quantum_seconds,
        field_name="aging_quantum_seconds",
        minimum=1,
        maximum=86_400,
    )
    effective_base = base
    if interactive_priority is not None:
        temporary = _exact_int(
            interactive_priority,
            field_name="interactive_priority",
            minimum=MIN_PRIORITY,
            maximum=MAX_PRIORITY,
        )
        if interactive_priority_expires_at is None:
            raise JobValidationError(
                "interactive_priority requires interactive_priority_expires_at"
            )
        expiry = _input_now(interactive_priority_expires_at)
        if expiry > current:
            effective_base = max(effective_base, temporary)
    elif interactive_priority_expires_at is not None:
        raise JobValidationError(
            "interactive_priority_expires_at requires interactive_priority"
        )
    age_seconds = max(0, int((current - created).total_seconds()))
    return effective_base + age_seconds // quantum


def build_claim_statement(
    *,
    scope: NarrationRequestScope,
    now: datetime,
    novel_ids: Sequence[UUID] | None = None,
    document_ids: Sequence[UUID] | None = None,
    resource_classes: Sequence[str] | None = None,
    job_kinds: Sequence[str] | None = None,
    aging_quantum_seconds: int = DEFAULT_AGING_QUANTUM_SECONDS,
    dialect_name: str = "postgresql",
):
    """Build the production fair-claim statement for inspection/integration."""

    fixed_scope = _scope(scope)
    current = _input_now(now)
    quantum = _exact_int(
        aging_quantum_seconds,
        field_name="aging_quantum_seconds",
        minimum=1,
        maximum=86_400,
    )
    current_param = bindparam(
        "claim_now", value=current, type_=DateTime(timezone=True)
    )
    active_temporary = and_(
        BackgroundJob.interactive_priority.is_not(None),
        BackgroundJob.interactive_priority_expires_at.is_not(None),
        BackgroundJob.interactive_priority_expires_at > current_param,
        BackgroundJob.interactive_priority > BackgroundJob.base_priority,
    )
    scheduling_priority = case(
        (active_temporary, BackgroundJob.interactive_priority),
        else_=BackgroundJob.base_priority,
    )
    if dialect_name == "sqlite":
        age_seconds = (
            func.julianday(current_param) - func.julianday(BackgroundJob.created_at)
        ) * 86_400
    else:
        age_seconds = func.extract(
            "epoch", current_param - BackgroundJob.created_at
        )
    nonnegative_age = case(
        (BackgroundJob.created_at < current_param, age_seconds), else_=0
    )
    # INTEGER overflows after long retention with small test quantums.  The
    # database score uses BIGINT while public priority inputs remain bounded.
    age_steps = cast(func.floor(nonnegative_age / quantum), BigInteger)
    effective_priority = scheduling_priority + age_steps
    pending_manual_command = exists(
        select(BackgroundManualRetryCommand.id).where(
            BackgroundManualRetryCommand.job_id == BackgroundJob.id,
            BackgroundManualRetryCommand.owner_id == fixed_scope.owner_id,
            BackgroundManualRetryCommand.workspace_id == fixed_scope.workspace_id,
            BackgroundManualRetryCommand.state == "pending",
        )
    )
    statement = (
        select(BackgroundJob)
        .where(
            BackgroundJob.owner_id == fixed_scope.owner_id,
            BackgroundJob.workspace_id == fixed_scope.workspace_id,
            BackgroundJob.state == "queued",
            or_(
                BackgroundJob.attempt_count < BackgroundJob.max_attempts,
                pending_manual_command,
            ),
            or_(
                BackgroundJob.next_retry_at.is_(None),
                BackgroundJob.next_retry_at <= current_param,
            ),
        )
        .order_by(
            effective_priority.desc(),
            BackgroundJob.created_at.asc(),
            BackgroundJob.id.asc(),
        )
        .limit(1)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    return _apply_background_job_filters(
        statement,
        novel_ids=novel_ids,
        document_ids=document_ids,
        resource_classes=resource_classes,
        job_kinds=job_kinds,
    )


def _existing_job_statement(
    *, scope: NarrationRequestScope, idempotency_key: str
):
    return (
        select(BackgroundJob)
        .where(
            BackgroundJob.owner_id == scope.owner_id,
            BackgroundJob.workspace_id == scope.workspace_id,
            BackgroundJob.idempotency_key == idempotency_key,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _ensure_same_canonical_job(
    job: BackgroundJob,
    *,
    input_hash: str,
    job_kind: str,
    resource_class: str,
    novel_id: UUID | None,
    request_id: UUID | None,
    request_allows_render: bool | None,
    base_priority: int,
    max_attempts: int,
) -> None:
    expected = (
        input_hash,
        job_kind,
        resource_class,
        novel_id,
        request_id,
        request_allows_render,
        base_priority,
        max_attempts,
    )
    actual = (
        job.input_hash,
        job.job_kind,
        job.resource_class,
        job.novel_id,
        job.request_id,
        job.request_allows_render,
        job.base_priority,
        job.max_attempts,
    )
    if actual != expected:
        raise JobIdempotencyConflict(
            "idempotency key already names different canonical job input"
        )


def _resolve_request_provenance(
    session: Session,
    *,
    scope: NarrationRequestScope,
    job_kind: str,
    novel_id: UUID | None,
    request_id: UUID | None,
) -> tuple[UUID | None, bool | None]:
    if request_id is None:
        if job_kind in RENDER_JOB_KINDS:
            raise JobValidationError(
                "render/export jobs require a server-authoritative narration request"
            )
        return novel_id, None
    request = session.scalar(
        select(NarrationRequest).where(
            NarrationRequest.id == request_id,
            NarrationRequest.owner_id == scope.owner_id,
            NarrationRequest.workspace_id == scope.workspace_id,
        )
        .execution_options(populate_existing=True)
    )
    if request is None:
        raise JobNotFoundError("narration request was not found in the fixed scope")
    if novel_id is not None and novel_id != request.novel_id:
        raise JobValidationError("job novel_id differs from its narration request")
    allows_render = request.allows_render
    if type(allows_render) is not bool:
        raise JobServiceError("database returned an invalid allows_render guard")
    if job_kind in RENDER_JOB_KINDS and allows_render is not True:
        raise JobValidationError("analyze-only requests cannot enqueue render/export jobs")
    return request.novel_id, allows_render


def _resource_policy(
    session: Session, *, resource_class: str
) -> BackgroundResourceClassPolicy:
    """Read the migration-owned resource registry, never a caller mapping."""

    policy = session.scalar(
        select(BackgroundResourceClassPolicy)
        .where(BackgroundResourceClassPolicy.resource_class == resource_class)
        .execution_options(populate_existing=True)
    )
    if policy is None:
        raise JobValidationError("resource_class is not registered")
    if type(policy.requires_publish_fence) is not bool or policy.max_concurrency < 1:
        raise JobServiceError("resource policy registry row is malformed")
    if policy.requires_publish_fence and not policy.exact_resource_key:
        raise JobServiceError("fenced resource policy has no exact resource key")
    return policy


def _validate_registered_job_kind(
    session: Session,
    *,
    job_kind: str,
    resource_class: str,
) -> BackgroundResourceClassPolicy:
    policy = _resource_policy(session, resource_class=resource_class)
    kind_policy = _registered_job_kind_policy(
        session,
        job_kind=job_kind,
        resource_class=resource_class,
    )
    if not kind_policy.executor_key:
        raise JobServiceError("job kind policy has no executor key")
    return policy


def _registered_job_kind_policy(
    session: Session,
    *,
    job_kind: str,
    resource_class: str,
) -> BackgroundJobKindPolicy:
    kind_policy = session.scalar(
        select(BackgroundJobKindPolicy)
        .where(
            BackgroundJobKindPolicy.job_kind == job_kind,
            BackgroundJobKindPolicy.resource_class == resource_class,
        )
        .execution_options(populate_existing=True)
    )
    if kind_policy is None:
        raise JobValidationError("background job kind/resource_class is not registered")
    return kind_policy


def _merge_queued_interactive_boost(
    job: BackgroundJob,
    *,
    requested_priority: int | None,
    requested_expiry: datetime | None,
    current: datetime,
) -> bool:
    """Join an idempotent replay's boost without ever weakening stored state.

    Active boosts form a component-wise max lattice over ``(priority, expiry)``.
    That is deliberately conservative: two racing requests can only produce a
    priority at least as high and an expiry at least as long as either input.
    Expired requests are ignored and expired stored pairs are replaced.  Only
    queued jobs are mutable; running/terminal replay is a pure idempotent read.
    """

    if requested_priority is None or requested_expiry is None or job.state != "queued":
        return False
    if requested_expiry <= current:
        return False
    if requested_expiry > current + timedelta(seconds=MAX_INTERACTIVE_BOOST_SECONDS):
        raise JobValidationError(
            "interactive priority expiry exceeds the five-minute boost window"
        )
    stored_priority = job.interactive_priority
    stored_expiry = job.interactive_priority_expires_at
    if (stored_priority is None) != (stored_expiry is None):
        raise JobServiceError("database contains an incomplete interactive boost")
    if stored_priority is None:
        next_priority = requested_priority
        next_expiry = requested_expiry
    else:
        checked_stored_priority = _exact_int(
            stored_priority,
            field_name="stored interactive_priority",
            minimum=MIN_PRIORITY,
            maximum=MAX_PRIORITY,
        )
        checked_stored_expiry = _database_datetime(
            stored_expiry, field_name="interactive_priority_expires_at"
        )
        if checked_stored_expiry <= current:
            next_priority = requested_priority
            next_expiry = requested_expiry
        else:
            next_priority = max(checked_stored_priority, requested_priority)
            next_expiry = max(checked_stored_expiry, requested_expiry)
    changed = (
        job.interactive_priority != next_priority
        or job.interactive_priority_expires_at is None
        or _database_datetime(
            job.interactive_priority_expires_at,
            field_name="interactive_priority_expires_at",
        )
        != next_expiry
    )
    if changed:
        job.interactive_priority = next_priority
        job.interactive_priority_expires_at = next_expiry
        job.updated_at = current
    return changed


def enqueue_job(
    session: Session,
    *,
    scope: NarrationRequestScope,
    job_kind: str,
    input_hash: str,
    idempotency_key: str,
    resource_class: str,
    novel_id: UUID | None = None,
    request_id: UUID | None = None,
    base_priority: int = 0,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    interactive_priority: int | None = None,
    interactive_priority_expires_at: datetime | None = None,
    test_only_now: datetime | None = None,
) -> EnqueueResult:
    """Idempotently insert/boost a queued job without committing.

    ``test_only_now`` is rejected by PostgreSQL and exists solely for the
    SQLite deterministic test path.
    """

    fixed_scope = _scope(scope)
    kind = _bounded_text(job_kind, field_name="job_kind", maximum=80)
    digest = _sha256(input_hash, field_name="input_hash")
    key = _bounded_text(idempotency_key, field_name="idempotency_key", maximum=160)
    resource = _bounded_text(resource_class, field_name="resource_class", maximum=80)
    resolved_novel = _uuid(novel_id, field_name="novel_id", optional=True)
    resolved_request = _uuid(request_id, field_name="request_id", optional=True)
    priority = _exact_int(
        base_priority,
        field_name="base_priority",
        minimum=MIN_PRIORITY,
        maximum=MAX_PRIORITY,
    )
    attempts = _exact_int(
        max_attempts,
        field_name="max_attempts",
        minimum=1,
        maximum=MAX_MAX_ATTEMPTS,
    )
    temporary_priority: int | None = None
    temporary_expiry: datetime | None = None
    if interactive_priority is not None:
        temporary_priority = _exact_int(
            interactive_priority,
            field_name="interactive_priority",
            minimum=MIN_PRIORITY,
            maximum=MAX_PRIORITY,
        )
        if interactive_priority_expires_at is None:
            raise JobValidationError(
                "interactive_priority requires interactive_priority_expires_at"
            )
        temporary_expiry = _input_now(interactive_priority_expires_at)
        if temporary_priority <= priority:
            raise JobValidationError(
                "interactive_priority must strictly exceed base_priority"
            )
    elif interactive_priority_expires_at is not None:
        raise JobValidationError(
            "interactive_priority_expires_at requires interactive_priority"
        )
    _validate_test_clock_hook(session, test_only_now)
    _validate_registered_job_kind(
        session,
        job_kind=kind,
        resource_class=resource,
    )
    # Enqueue has no pre-existing row to lock on the insert path.  PostgreSQL
    # still uses clock_timestamp(), never transaction-start now().  Conflict
    # replays take a second clock reading *after* locking the existing row.
    current = _clock_after_lock(session, test_only_now)
    if temporary_expiry is not None:
        if temporary_expiry <= current:
            raise JobValidationError("interactive priority expiry must be in the future")
        if temporary_expiry > current + timedelta(
            seconds=MAX_INTERACTIVE_BOOST_SECONDS
        ):
            raise JobValidationError(
                "interactive priority expiry exceeds the five-minute boost window"
            )
    resolved_novel, allows_render = _resolve_request_provenance(
        session,
        scope=fixed_scope,
        job_kind=kind,
        novel_id=resolved_novel,
        request_id=resolved_request,
    )
    values = {
        "id": uuid4(),
        "owner_id": fixed_scope.owner_id,
        "workspace_id": fixed_scope.workspace_id,
        "novel_id": resolved_novel,
        "request_id": resolved_request,
        "request_allows_render": allows_render,
        "job_kind": kind,
        "input_hash": digest,
        "idempotency_key": key,
        "resource_class": resource,
        "base_priority": priority,
        "interactive_priority": temporary_priority,
        "interactive_priority_expires_at": temporary_expiry,
        "state": "queued",
        "max_attempts": attempts,
        "attempt_count": 0,
        "next_retry_at": None,
        "cancel_requested_at": None,
        "cancel_actor": None,
        "cancel_reason_code": None,
        "progress_current": 0,
        "progress_total": None,
        "error_code": None,
        "created_at": current,
        "updated_at": current,
    }

    created = False
    job: BackgroundJob | None
    if _dialect_name(session) == "postgresql":
        statement = (
            postgresql_insert(BackgroundJob.__table__)
            .values(**values)
            .on_conflict_do_nothing(
                constraint="uq_background_job_idempotency"
            )
            .returning(BackgroundJob.id)
        )
        inserted_id = session.scalar(statement)
        if inserted_id is not None:
            created = True
            job = session.scalar(
                select(BackgroundJob)
                .where(BackgroundJob.id == inserted_id)
                .execution_options(populate_existing=True)
            )
        else:
            job = session.scalar(
                _existing_job_statement(scope=fixed_scope, idempotency_key=key)
            )
    else:
        # Unit-test/unsupported-dialect fallback.  Production race safety comes
        # from the PostgreSQL ON CONFLICT path above.
        job = session.scalar(
            _existing_job_statement(scope=fixed_scope, idempotency_key=key)
        )
        if job is None:
            job = BackgroundJob(**values)
            session.add(job)
            session.flush()
            created = True
    if job is None:
        raise JobServiceError("idempotent enqueue could not reload its job")
    _ensure_same_canonical_job(
        job,
        input_hash=digest,
        job_kind=kind,
        resource_class=resource,
        novel_id=resolved_novel,
        request_id=resolved_request,
        request_allows_render=allows_render,
        base_priority=priority,
        max_attempts=attempts,
    )
    if not created:
        replay_current = _clock_after_lock(session, test_only_now)
        if _merge_queued_interactive_boost(
            job,
            requested_priority=temporary_priority,
            requested_expiry=temporary_expiry,
            current=replay_current,
        ):
            session.flush()
    return EnqueueResult(job_id=job.id, created=created)


def _job_for_update(
    session: Session,
    *,
    scope: NarrationRequestScope,
    job_id: UUID,
) -> BackgroundJob:
    identifier = _uuid(job_id, field_name="job_id")
    job = session.scalar(
        select(BackgroundJob)
        .where(
            BackgroundJob.id == identifier,
            BackgroundJob.owner_id == scope.owner_id,
            BackgroundJob.workspace_id == scope.workspace_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if job is None:
        raise JobNotFoundError("job was not found in the fixed scope")
    return job


def _attempt_for_update(
    session: Session,
    *,
    job: BackgroundJob,
    fence: JobFence,
) -> BackgroundJobAttempt:
    if type(fence) is not JobFence:
        raise JobValidationError("fence must be a JobFence")
    _uuid(fence.job_id, field_name="fence.job_id")
    _uuid(fence.attempt_id, field_name="fence.attempt_id")
    _uuid(fence.lease_token, field_name="fence.lease_token")
    if fence.job_id != job.id:
        raise JobFenceError("attempt fence names a different job")
    _exact_int(
        fence.lease_generation,
        field_name="lease_generation",
        minimum=1,
        maximum=2**63 - 1,
    )
    attempt = session.scalar(
        select(BackgroundJobAttempt)
        .where(
            BackgroundJobAttempt.id == fence.attempt_id,
            BackgroundJobAttempt.job_id == job.id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if attempt is None:
        raise JobFenceError("attempt fence does not exist for this job")
    return attempt


def _validate_active_attempt(
    *,
    job: BackgroundJob,
    attempt: BackgroundJobAttempt,
    fence: JobFence,
    now: datetime,
    allowed_job_states: frozenset[str],
) -> BackgroundJobAttempt:
    generation = _exact_int(
        fence.lease_generation,
        field_name="lease_generation",
        minimum=1,
        maximum=2**63 - 1,
    )
    if (
        attempt.lease_token != fence.lease_token
        or attempt.lease_generation != generation
        or attempt.attempt_number != job.attempt_count
    ):
        raise JobFenceError("attempt fence is stale or not the current generation")
    if attempt.completed_at is not None:
        raise JobFenceError("attempt is already complete")
    if job.state not in allowed_job_states:
        raise JobFenceError("job state no longer accepts this fenced operation")
    lease_until = _database_datetime(attempt.lease_until, field_name="lease_until")
    if lease_until <= now:
        raise JobFenceError("attempt lease has expired")
    return attempt


def _new_attempt(
    *,
    job: BackgroundJob,
    retry_kind: Literal["initial", "automatic", "manual"],
    lease_owner: str,
    lease_until: datetime,
    started_at: datetime,
    executor_epoch_id: UUID,
    resource_lease: ResourceLease,
    manual_retry_command_id: UUID | None = None,
    manual_actor: str | None = None,
    manual_reason: str | None = None,
) -> BackgroundJobAttempt:
    attempt_number = _exact_int(
        job.attempt_count,
        field_name="stored attempt_count",
        minimum=0,
        maximum=2**31 - 2,
    ) + 1
    return BackgroundJobAttempt(
        id=uuid4(),
        job_id=job.id,
        attempt_number=attempt_number,
        retry_kind=retry_kind,
        manual_retry_command_id=manual_retry_command_id,
        manual_actor=manual_actor,
        manual_reason=manual_reason,
        executor_epoch_id=executor_epoch_id,
        resource_key=resource_lease.fence.resource_key,
        resource_lease_token=resource_lease.fence.lease_token,
        resource_lease_generation=resource_lease.fence.lease_generation,
        lease_owner=lease_owner,
        lease_token=uuid4(),
        lease_generation=attempt_number,
        lease_until=lease_until,
        heartbeat_at=started_at,
        started_at=started_at,
        completed_at=None,
        error_classification=None,
        error_code=None,
        actual_result_digest=None,
    )


def _lease(attempt: BackgroundJobAttempt) -> JobLease:
    resource_fence = ResourceFence(
        resource_key=attempt.resource_key,
        lease_owner=attempt.lease_owner,
        lease_token=attempt.resource_lease_token,
        lease_generation=attempt.resource_lease_generation,
    )
    return JobLease(
        fence=JobFence(
            job_id=attempt.job_id,
            attempt_id=attempt.id,
            lease_token=attempt.lease_token,
            lease_generation=attempt.lease_generation,
        ),
        attempt_number=attempt.attempt_number,
        retry_kind=attempt.retry_kind,
        lease_owner=attempt.lease_owner,
        lease_until=_database_datetime(attempt.lease_until, field_name="lease_until"),
        executor_epoch_id=attempt.executor_epoch_id,
        resource_fence=resource_fence,
    )


def _executor_epoch_for_update(
    session: Session,
    *,
    epoch_id: UUID,
) -> BackgroundExecutorEpoch:
    epoch = session.scalar(
        select(BackgroundExecutorEpoch)
        .where(BackgroundExecutorEpoch.id == epoch_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if epoch is None:
        raise JobFenceError("attempt executor epoch does not exist")
    return epoch


def _active_executor_epoch_for_update(
    session: Session, *, executor_key: str
) -> BackgroundExecutorEpoch:
    epoch = session.scalar(
        select(BackgroundExecutorEpoch)
        .where(
            BackgroundExecutorEpoch.executor_key == executor_key,
            BackgroundExecutorEpoch.state == "active",
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if epoch is None:
        raise JobStateError("no active background executor epoch is installed")
    return epoch


def _attempt_resource_fence(attempt: BackgroundJobAttempt) -> ResourceFence:
    return ResourceFence(
        resource_key=_bounded_text(
            attempt.resource_key,
            field_name="stored resource_key",
            maximum=160,
        ),
        lease_owner=_bounded_text(
            attempt.lease_owner,
            field_name="stored lease_owner",
            maximum=160,
        ),
        lease_token=_uuid(
            attempt.resource_lease_token,
            field_name="stored resource_lease_token",
        ),
        lease_generation=_exact_int(
            attempt.resource_lease_generation,
            field_name="stored resource_lease_generation",
            minimum=1,
            maximum=2**63 - 1,
        ),
    )


@dataclass(frozen=True, slots=True)
class _LockedExecution:
    job: BackgroundJob
    attempt: BackgroundJobAttempt
    epoch: BackgroundExecutorEpoch
    resource_row: BackgroundResourceLock
    resource_is_current: bool
    policy: BackgroundResourceClassPolicy
    current: datetime


def _validate_attempt_resource_policy(
    session: Session,
    *,
    job: BackgroundJob,
    attempt: BackgroundJobAttempt,
) -> BackgroundResourceClassPolicy:
    # Revalidate the migration-owned kind mapping on every fenced mutation, not
    # only at enqueue.  This makes an unknown ``narration.*`` row fail closed
    # even if it entered a SQLite test fixture or a damaged database by bypassing
    # the normal service/trigger path.
    policy = _validate_registered_job_kind(
        session,
        job_kind=job.job_kind,
        resource_class=job.resource_class,
    )
    slot = session.scalar(
        select(BackgroundResourceClassSlot)
        .where(
            BackgroundResourceClassSlot.resource_key == attempt.resource_key,
            BackgroundResourceClassSlot.resource_class == job.resource_class,
            BackgroundResourceClassSlot.enabled.is_(True),
        )
        .execution_options(populate_existing=True)
    )
    if slot is None:
        raise JobFenceError("attempt resource slot is not registered and enabled")
    if (
        policy.exact_resource_key is not None
        and attempt.resource_key != policy.exact_resource_key
    ):
        raise JobFenceError("attempt resource key differs from registered exact key")
    return policy


def _lock_job_attempt_fence(
    session: Session,
    *,
    scope: NarrationRequestScope,
    fence: JobFence,
    allowed_job_states: frozenset[str],
    test_only_now: datetime | None,
    require_active_epoch: bool = True,
    require_live_attempt: bool = True,
    require_live_resource: bool = True,
) -> _LockedExecution:
    """Lock job -> attempt -> executor epoch -> resource, then validate."""

    _validate_test_clock_hook(session, test_only_now)
    if type(fence) is not JobFence:
        raise JobValidationError("fence must be a JobFence")
    job = _job_for_update(session, scope=scope, job_id=fence.job_id)
    attempt = _attempt_for_update(session, job=job, fence=fence)
    epoch = _executor_epoch_for_update(
        session,
        epoch_id=_uuid(attempt.executor_epoch_id, field_name="executor_epoch_id"),
    )
    resource_fence = _attempt_resource_fence(attempt)
    resource_row = _resource_locks._row_for_update(  # noqa: SLF001
        session,
        resource_key=resource_fence.resource_key,
    )
    current = _clock_after_lock(session, test_only_now)
    if require_live_attempt:
        _validate_active_attempt(
            job=job,
            attempt=attempt,
            fence=fence,
            now=current,
            allowed_job_states=allowed_job_states,
        )
    else:
        if attempt.completed_at is not None:
            raise JobFenceError("attempt is already complete")
        if job.state not in allowed_job_states:
            raise JobFenceError("job state no longer accepts this fenced operation")
        if (
            attempt.lease_token != fence.lease_token
            or attempt.lease_generation != fence.lease_generation
            or attempt.attempt_number != job.attempt_count
        ):
            raise JobFenceError("attempt fence is stale or not the current generation")
    if require_active_epoch and epoch.state != "active":
        raise JobFenceError("attempt executor epoch has been revoked")
    if resource_row is None:
        raise JobFenceError("attempt resource lease row does not exist")
    resource_is_current = True
    if require_live_resource:
        _resource_locks._validate_fence(  # noqa: SLF001
            resource_row,
            fence=resource_fence,
            now=current,
        )
    elif (
        resource_row.lease_owner != resource_fence.lease_owner
        or resource_row.lease_token != resource_fence.lease_token
        or resource_row.lease_generation != resource_fence.lease_generation
    ):
        if resource_row.lease_generation < resource_fence.lease_generation:
            raise JobFenceError("resource generation moved backwards")
        resource_is_current = False
    policy = _validate_attempt_resource_policy(
        session,
        job=job,
        attempt=attempt,
    )
    kind_policy = _registered_job_kind_policy(
        session,
        job_kind=job.job_kind,
        resource_class=job.resource_class,
    )
    if epoch.executor_key != kind_policy.executor_key:
        raise JobFenceError("attempt executor does not match the registered job kind")
    return _LockedExecution(
        job=job,
        attempt=attempt,
        epoch=epoch,
        resource_row=resource_row,
        resource_is_current=resource_is_current,
        policy=policy,
        current=current,
    )


def _lock_combined_publication_fences(
    session: Session,
    *,
    scope: NarrationRequestScope,
    job_fence: JobFence,
    resource_fence: ResourceFence,
    test_only_now: datetime | None,
) -> tuple[_LockedExecution, PublicationFenceContext]:
    """Lock job -> attempt -> resource, then validate both with one clock."""

    _validate_test_clock_hook(session, test_only_now)
    if type(job_fence) is not JobFence:
        raise JobValidationError("job_fence must be a JobFence")
    if type(resource_fence) is not ResourceFence:
        raise JobValidationError("resource_fence must be a ResourceFence")
    locked = _lock_job_attempt_fence(
        session,
        scope=scope,
        fence=job_fence,
        allowed_job_states=frozenset({"running"}),
        test_only_now=test_only_now,
    )
    if not locked.policy.requires_publish_fence:
        raise JobFenceError(
            "combined publication fence is reserved for registered fenced resources"
        )
    recorded_resource_fence = _attempt_resource_fence(locked.attempt)
    if resource_fence != recorded_resource_fence:
        raise JobFenceError(
            "resource fence differs from the attempt-recorded resource fence"
        )
    transaction = session.get_transaction()
    if transaction is None or not transaction.is_active:
        raise JobFenceError("publication fence requires an active transaction")
    context = PublicationFenceContext(
        scope=scope,
        job_lease=_lease(locked.attempt),
        resource_lease=_resource_locks._lease(locked.resource_row),  # noqa: SLF001
        resource_class=locked.job.resource_class,
        checked_at=locked.current,
        _session=session,
        _transaction=transaction,
    )
    return locked, context


def _release_locked_resource(locked: _LockedExecution) -> None:
    """Rotate the exact attempt-owned resource token inside the locked txn."""

    if not locked.resource_is_current:
        return
    locked.resource_row.lease_token = uuid4()
    locked.resource_row.lease_until = locked.current
    locked.resource_row.updated_at = locked.current


def _pending_manual_command_for_update(
    session: Session,
    *,
    job: BackgroundJob,
) -> BackgroundManualRetryCommand | None:
    return session.scalar(
        select(BackgroundManualRetryCommand)
        .where(
            BackgroundManualRetryCommand.job_id == job.id,
            BackgroundManualRetryCommand.owner_id == job.owner_id,
            BackgroundManualRetryCommand.workspace_id == job.workspace_id,
            BackgroundManualRetryCommand.state == "pending",
        )
        .order_by(
            BackgroundManualRetryCommand.requested_at.asc(),
            BackgroundManualRetryCommand.id.asc(),
        )
        .limit(1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _acquire_job_resource_slot(
    session: Session,
    *,
    job: BackgroundJob,
    policy: BackgroundResourceClassPolicy,
    lease_owner: str,
    lease_seconds: int,
    test_only_now: datetime | None,
) -> ResourceLease | None:
    """Lock one enabled registered slot and acquire its persistent fence.

    The job and executor epoch are already locked by the caller.  Slot rows are
    migration-owned, so ``FOR UPDATE SKIP LOCKED`` is used only as an allocation
    mutex; no registry field is ever mutated here.
    """

    slot_count = _exact_int(
        policy.max_concurrency,
        field_name="registered max_concurrency",
        minimum=1,
        maximum=10_000,
    )
    excluded_keys: list[str] = []
    for _ in range(slot_count):
        selection_current = _clock_after_lock(session, test_only_now)
        statement = (
            select(BackgroundResourceClassSlot)
            .outerjoin(
                BackgroundResourceLock,
                BackgroundResourceLock.resource_key
                == BackgroundResourceClassSlot.resource_key,
            )
            .where(
                BackgroundResourceClassSlot.resource_class == job.resource_class,
                BackgroundResourceClassSlot.enabled.is_(True),
                BackgroundResourceClassSlot.slot_number < slot_count,
                or_(
                    BackgroundResourceLock.resource_key.is_(None),
                    BackgroundResourceLock.lease_until <= selection_current,
                ),
            )
            .order_by(BackgroundResourceClassSlot.slot_number.asc())
            .limit(1)
            .with_for_update(
                skip_locked=True,
                of=BackgroundResourceClassSlot,
            )
            .execution_options(populate_existing=True)
        )
        if excluded_keys:
            statement = statement.where(
                BackgroundResourceClassSlot.resource_key.not_in(excluded_keys)
            )
        if policy.exact_resource_key is not None:
            statement = statement.where(
                BackgroundResourceClassSlot.resource_key
                == policy.exact_resource_key
            )
        slot = session.scalar(statement)
        if slot is None:
            return None
        if (
            policy.exact_resource_key is not None
            and slot.resource_key != policy.exact_resource_key
        ):
            raise JobServiceError(
                "registered exact resource policy points at a different slot"
            )
        try:
            return _resource_locks.acquire_resource_lock(
                session,
                resource_key=slot.resource_key,
                lease_owner=lease_owner,
                lease_seconds=lease_seconds,
                test_only_now=test_only_now,
            )
        except _resource_locks.ResourceBusyError:
            # A heartbeat may have extended an apparently expired row between
            # selection and its row lock.  Keep the slot allocation safe and
            # look for another registered slot in this same transaction.
            excluded_keys.append(slot.resource_key)
    return None


def claim_next_job(
    session: Session,
    *,
    scope: NarrationRequestScope,
    lease_owner: str,
    novel_ids: Sequence[UUID] | None = None,
    document_ids: Sequence[UUID] | None = None,
    resource_classes: Sequence[str] | None = None,
    job_kinds: Sequence[str] | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    aging_quantum_seconds: int = DEFAULT_AGING_QUANTUM_SECONDS,
    executor_key: str = DEFAULT_EXECUTOR_KEY,
    test_only_now: datetime | None = None,
) -> JobLease | None:
    """Claim one fair queued job and append its immutable attempt identity."""

    fixed_scope = _scope(scope)
    worker = _bounded_text(lease_owner, field_name="lease_owner", maximum=160)
    duration = _lease_duration(lease_seconds)
    selection_current = _selection_clock(session, test_only_now)
    statement = build_claim_statement(
        scope=fixed_scope,
        now=selection_current,
        novel_ids=novel_ids,
        document_ids=document_ids,
        resource_classes=resource_classes,
        job_kinds=job_kinds,
        aging_quantum_seconds=aging_quantum_seconds,
        dialect_name=_dialect_name(session),
    )
    job = session.scalar(statement)
    if job is None:
        return None
    manual_command = _pending_manual_command_for_update(session, job=job)
    if manual_command is None and job.attempt_count >= job.max_attempts:
        raise JobStateError("queued job exhausted attempts without a manual command")
    policy = _validate_registered_job_kind(
        session,
        job_kind=job.job_kind,
        resource_class=job.resource_class,
    )
    kind_policy = _registered_job_kind_policy(
        session,
        job_kind=job.job_kind,
        resource_class=job.resource_class,
    )
    trusted_executor_key = _bounded_text(
        executor_key, field_name="executor_key", maximum=80
    )
    if kind_policy.executor_key != trusted_executor_key:
        raise JobStateError("scheduler executor does not own the selected job kind")
    epoch = _active_executor_epoch_for_update(
        session, executor_key=trusted_executor_key
    )
    resource_lease = _acquire_job_resource_slot(
        session,
        job=job,
        policy=policy,
        lease_owner=worker,
        lease_seconds=lease_seconds,
        test_only_now=test_only_now,
    )
    if resource_lease is None:
        return None
    # All authority rows are now locked.  One final clock sample defines the
    # attempt lease and manual-command claim timestamp.
    current = _clock_after_lock(session, test_only_now)
    retry_kind: Literal["initial", "automatic", "manual"]
    if manual_command is not None:
        retry_kind = "manual"
    else:
        retry_kind = "initial" if job.attempt_count == 0 else "automatic"
    attempt = _new_attempt(
        job=job,
        retry_kind=retry_kind,
        lease_owner=worker,
        lease_until=current + duration,
        started_at=current,
        executor_epoch_id=epoch.id,
        resource_lease=resource_lease,
        manual_retry_command_id=(
            manual_command.id if manual_command is not None else None
        ),
        manual_actor=(manual_command.actor if manual_command is not None else None),
        manual_reason=(manual_command.reason if manual_command is not None else None),
    )
    session.add(attempt)
    if manual_command is not None:
        manual_command.state = "claimed"
        manual_command.claimed_attempt_id = attempt.id
        manual_command.claimed_at = current
    job.attempt_count += 1
    job.state = "running"
    job.next_retry_at = None
    job.error_code = None
    job.updated_at = current
    session.flush()
    return _lease(attempt)


def heartbeat_attempt(
    session: Session,
    *,
    scope: NarrationRequestScope,
    fence: JobFence,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    progress_current: int | None = None,
    progress_total: int | None = None,
    test_only_now: datetime | None = None,
) -> JobLease:
    """Extend a live attempt; progress is logical-job monotonic across retries."""

    fixed_scope = _scope(scope)
    duration = _lease_duration(lease_seconds)
    locked = _lock_job_attempt_fence(
        session,
        scope=fixed_scope,
        fence=fence,
        allowed_job_states=frozenset({"running"}),
        test_only_now=test_only_now,
    )
    job = locked.job
    attempt = locked.attempt
    current = locked.current
    next_progress = job.progress_current
    next_total = job.progress_total
    if progress_current is not None:
        next_progress = _exact_int(
            progress_current,
            field_name="progress_current",
            minimum=0,
            maximum=2**31 - 1,
        )
        if next_progress < job.progress_current:
            raise JobValidationError("progress_current cannot move backwards")
    if progress_total is not None:
        next_total = _exact_int(
            progress_total,
            field_name="progress_total",
            minimum=0,
            maximum=2**31 - 1,
        )
        if job.progress_total is not None and next_total != job.progress_total:
            raise JobValidationError("progress_total is write-once")
    if next_total is not None and next_progress > next_total:
        raise JobValidationError("progress_current cannot exceed progress_total")
    job.progress_current = next_progress
    job.progress_total = next_total
    old_until = _database_datetime(attempt.lease_until, field_name="lease_until")
    attempt.heartbeat_at = current
    attempt.lease_until = max(old_until, current + duration)
    resource_until = _database_datetime(
        locked.resource_row.lease_until,
        field_name="resource lease_until",
    )
    locked.resource_row.lease_until = max(resource_until, current + duration)
    locked.resource_row.updated_at = current
    job.updated_at = current
    session.flush()
    return _lease(attempt)


def lock_result_publish_fence(
    session: Session,
    *,
    scope: NarrationRequestScope,
    fence: JobFence,
    test_only_now: datetime | None = None,
) -> JobLease:
    """Lock and validate a result fence for the caller's current transaction.

    The authoritative media/link insert and ``complete_attempt`` must occur in
    this same short transaction.  A check followed by external I/O is unsafe.
    """

    fixed_scope = _scope(scope)
    locked = _lock_job_attempt_fence(
        session,
        scope=fixed_scope,
        fence=fence,
        allowed_job_states=frozenset({"running"}),
        test_only_now=test_only_now,
    )
    if locked.policy.requires_publish_fence:
        raise JobFenceError(
            "fenced jobs require lock_result_publish_fences with the recorded resource fence"
        )
    return _lease(locked.attempt)


def lock_result_publish_fences(
    session: Session,
    *,
    scope: NarrationRequestScope,
    job_fence: JobFence,
    resource_fence: ResourceFence,
    test_only_now: datetime | None = None,
) -> PublicationFenceContext:
    """Atomically validate both fences for a heavy result publication.

    Lock order is fixed as job -> current attempt -> mapped resource.  The
    caller may then add media/model-run rows and must call ``complete_attempt``
    with the returned context before committing this same short transaction.
    """

    fixed_scope = _scope(scope)
    _locked, context = _lock_combined_publication_fences(
        session,
        scope=fixed_scope,
        job_fence=job_fence,
        resource_fence=resource_fence,
        test_only_now=test_only_now,
    )
    return context


def complete_attempt(
    session: Session,
    *,
    scope: NarrationRequestScope,
    fence: JobFence,
    actual_result_digest: str,
    publication_context: PublicationFenceContext | None = None,
    test_only_now: datetime | None = None,
) -> None:
    """Fence and record a successful result digest, then finish the job."""

    digest = _sha256(actual_result_digest, field_name="actual_result_digest")
    fixed_scope = _scope(scope)
    if publication_context is not None:
        if type(publication_context) is not PublicationFenceContext:
            raise JobValidationError(
                "publication_context must be a PublicationFenceContext"
            )
        if publication_context._session is not session:
            raise JobFenceError("publication context belongs to another Session")
        if (
            not publication_context._transaction.is_active
            or session.get_transaction() is not publication_context._transaction
        ):
            raise JobFenceError("publication context belongs to another transaction")
        if publication_context.scope != fixed_scope:
            raise JobFenceError("publication context belongs to another scope")
        if publication_context.job_lease.fence != fence:
            raise JobFenceError("publication context names another job fence")
        if (
            publication_context.job_lease.resource_fence
            != publication_context.resource_lease.fence
        ):
            raise JobFenceError(
                "publication context resource fence is internally inconsistent"
            )
        locked, refreshed = _lock_combined_publication_fences(
            session,
            scope=fixed_scope,
            job_fence=fence,
            resource_fence=publication_context.resource_lease.fence,
            test_only_now=test_only_now,
        )
        if publication_context.resource_class != locked.job.resource_class:
            raise JobFenceError("publication context names another resource class")
        if publication_context.job_lease.executor_epoch_id != locked.epoch.id:
            raise JobFenceError("publication context names another executor epoch")
        current = refreshed.checked_at
    else:
        locked = _lock_job_attempt_fence(
            session,
            scope=fixed_scope,
            fence=fence,
            allowed_job_states=frozenset({"running"}),
            test_only_now=test_only_now,
        )
        if locked.policy.requires_publish_fence:
            raise JobFenceError(
                "fenced completion requires a combined publication context"
            )
        current = locked.current
    job = locked.job
    attempt = locked.attempt
    attempt.completed_at = current
    attempt.actual_result_digest = digest
    job.state = "succeeded"
    job.next_retry_at = None
    job.error_code = None
    if job.progress_total is not None:
        job.progress_current = job.progress_total
    job.updated_at = current
    # The database publication guard observes the exact live attempt-recorded
    # resource fence at the success transition.  Release only after that
    # authoritative transition has flushed in this same transaction.
    session.flush()
    _release_locked_resource(locked)
    session.flush()


def retry_delay_seconds(
    attempt_count: int,
    *,
    base_seconds: int = DEFAULT_RETRY_BASE_SECONDS,
    cap_seconds: int = MAX_RETRY_DELAY_SECONDS,
) -> int:
    """Return capped exponential backoff for the completed attempt count."""

    count = _exact_int(
        attempt_count,
        field_name="attempt_count",
        minimum=1,
        maximum=2**31 - 1,
    )
    base = _exact_int(
        base_seconds,
        field_name="base_seconds",
        minimum=1,
        maximum=86_400,
    )
    cap = _exact_int(
        cap_seconds,
        field_name="cap_seconds",
        minimum=base,
        maximum=7 * 86_400,
    )
    exponent = min(count - 1, 62)
    return min(base * (2**exponent), cap)


def _finish_failed_attempt(
    *,
    job: BackgroundJob,
    attempt: BackgroundJobAttempt,
    classification: RetryClassification,
    error_code: str,
    current: datetime,
    retry_base_seconds: int,
    retry_cap_seconds: int,
) -> FailureResult:
    attempt.completed_at = current
    attempt.error_classification = classification
    attempt.error_code = error_code
    job.error_code = error_code
    job.updated_at = current
    next_retry_at: datetime | None = None
    if classification == "retryable" and job.attempt_count < job.max_attempts:
        next_retry_at = current + timedelta(
            seconds=retry_delay_seconds(
                job.attempt_count,
                base_seconds=retry_base_seconds,
                cap_seconds=retry_cap_seconds,
            )
        )
        job.state = "retry_wait"
        job.next_retry_at = next_retry_at
        state: Literal["retry_wait", "failed", "dead_letter"] = "retry_wait"
    elif classification == "retryable":
        job.state = "dead_letter"
        job.next_retry_at = None
        state = "dead_letter"
    else:
        job.state = "failed"
        job.next_retry_at = None
        state = "failed"
    return FailureResult(job_id=job.id, state=state, next_retry_at=next_retry_at)


def fail_attempt(
    session: Session,
    *,
    scope: NarrationRequestScope,
    fence: JobFence,
    classification: RetryClassification,
    error_code: str,
    retry_base_seconds: int = DEFAULT_RETRY_BASE_SECONDS,
    retry_cap_seconds: int = MAX_RETRY_DELAY_SECONDS,
    test_only_now: datetime | None = None,
) -> FailureResult:
    """Fence a worker failure and choose retry, failure, or dead-letter."""

    if classification not in {"retryable", "non_retryable", "security_failure"}:
        raise JobValidationError("unknown attempt error classification")
    code = _error_code(error_code)
    if classification == "retryable":
        # Validate policy before any ORM row becomes dirty.
        retry_delay_seconds(
            1,
            base_seconds=retry_base_seconds,
            cap_seconds=retry_cap_seconds,
        )
    fixed_scope = _scope(scope)
    locked = _lock_job_attempt_fence(
        session,
        scope=fixed_scope,
        fence=fence,
        allowed_job_states=frozenset({"running"}),
        test_only_now=test_only_now,
    )
    result = _finish_failed_attempt(
        job=locked.job,
        attempt=locked.attempt,
        classification=classification,
        error_code=code,
        current=locked.current,
        retry_base_seconds=retry_base_seconds,
        retry_cap_seconds=retry_cap_seconds,
    )
    _release_locked_resource(locked)
    session.flush()
    return result


def promote_due_retries(
    session: Session,
    *,
    scope: NarrationRequestScope,
    novel_ids: Sequence[UUID] | None = None,
    document_ids: Sequence[UUID] | None = None,
    resource_classes: Sequence[str] | None = None,
    job_kinds: Sequence[str] | None = None,
    limit: int = 100,
    test_only_now: datetime | None = None,
) -> tuple[UUID, ...]:
    """Move due retry_wait jobs back to queued under skip-locked row locks."""

    fixed_scope = _scope(scope)
    batch_limit = _exact_int(
        limit, field_name="limit", minimum=1, maximum=1_000
    )
    selection_current = _selection_clock(session, test_only_now)
    statement = (
        select(BackgroundJob)
        .where(
            BackgroundJob.owner_id == fixed_scope.owner_id,
            BackgroundJob.workspace_id == fixed_scope.workspace_id,
            BackgroundJob.state == "retry_wait",
            BackgroundJob.next_retry_at.is_not(None),
            BackgroundJob.next_retry_at <= selection_current,
            BackgroundJob.attempt_count < BackgroundJob.max_attempts,
        )
        .order_by(BackgroundJob.next_retry_at.asc(), BackgroundJob.id.asc())
        .limit(batch_limit)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    statement = _apply_background_job_filters(
        statement,
        novel_ids=novel_ids,
        document_ids=document_ids,
        resource_classes=resource_classes,
        job_kinds=job_kinds,
    )
    due_jobs = session.scalars(statement).all()
    if not due_jobs:
        return ()
    current = _clock_after_lock(session, test_only_now)
    for job in due_jobs:
        job.state = "queued"
        job.next_retry_at = None
        job.updated_at = current
    session.flush()
    return tuple(job.id for job in due_jobs)


def request_cancel(
    session: Session,
    *,
    scope: NarrationRequestScope,
    job_id: UUID,
    actor: str,
    reason_code: str,
    test_only_now: datetime | None = None,
) -> CancelRequestResult:
    """Request cancellation without trusting a worker-owned fence."""

    fixed_scope = _scope(scope)
    cancel_actor = _bounded_text(actor, field_name="actor", maximum=120)
    cancel_reason = _error_code(reason_code)
    _validate_test_clock_hook(session, test_only_now)
    job = _job_for_update(
        session, scope=fixed_scope, job_id=job_id
    )
    pending_manual = (
        _pending_manual_command_for_update(session, job=job)
        if job.state == "queued"
        else None
    )
    current = _clock_after_lock(session, test_only_now)
    if job.state == "cancel_requested":
        return CancelRequestResult(job_id=job.id, state=job.state, changed=False)
    if job.state in TERMINAL_JOB_STATES:
        return CancelRequestResult(job_id=job.id, state=job.state, changed=False)
    job.cancel_requested_at = current
    job.cancel_actor = cancel_actor
    job.cancel_reason_code = cancel_reason
    job.updated_at = current
    if job.state == "running":
        job.state = "cancel_requested"
    elif job.state == "retry_wait":
        # Preserve the frozen transition graph: retry_wait -> queued -> cancelled.
        job.state = "queued"
        job.next_retry_at = None
        session.flush()
        job.state = "cancelled"
    elif job.state == "queued":
        if pending_manual is not None:
            pending_manual.state = "cancelled"
            pending_manual.cancelled_at = current
            pending_manual.cancelled_actor = cancel_actor
            pending_manual.cancelled_reason_code = cancel_reason
        job.state = "cancelled"
    else:
        raise JobStateError(f"job state {job.state!r} cannot be cancelled")
    session.flush()
    return CancelRequestResult(job_id=job.id, state=job.state, changed=True)


def acknowledge_cancel(
    session: Session,
    *,
    scope: NarrationRequestScope,
    fence: JobFence,
    test_only_now: datetime | None = None,
) -> None:
    """Fence the active worker's cancellation acknowledgement."""

    fixed_scope = _scope(scope)
    locked = _lock_job_attempt_fence(
        session,
        scope=fixed_scope,
        fence=fence,
        allowed_job_states=frozenset({"cancel_requested"}),
        test_only_now=test_only_now,
    )
    job = locked.job
    attempt = locked.attempt
    current = locked.current
    attempt.completed_at = current
    attempt.error_classification = "cancelled"
    attempt.error_code = "JOB_CANCELLED"
    job.state = "cancelled"
    job.next_retry_at = None
    job.error_code = None
    job.updated_at = current
    _release_locked_resource(locked)
    session.flush()


def manual_retry(
    session: Session,
    *,
    scope: NarrationRequestScope,
    job_id: UUID,
    actor: str,
    reason: str,
    idempotency_key: str,
    test_only_now: datetime | None = None,
) -> ManualRetryResult:
    """Persist one immutable retry authorisation and queue without leasing."""

    fixed_scope = _scope(scope)
    retry_actor = _bounded_text(actor, field_name="actor", maximum=120)
    retry_reason = _bounded_text(reason, field_name="reason", maximum=240)
    retry_key = _bounded_text(
        idempotency_key,
        field_name="idempotency_key",
        maximum=160,
    )
    _validate_test_clock_hook(session, test_only_now)
    job = _job_for_update(
        session, scope=fixed_scope, job_id=job_id
    )

    def locked_existing() -> BackgroundManualRetryCommand | None:
        return session.scalar(
            select(BackgroundManualRetryCommand)
            .where(
                BackgroundManualRetryCommand.owner_id == fixed_scope.owner_id,
                BackgroundManualRetryCommand.workspace_id == fixed_scope.workspace_id,
                BackgroundManualRetryCommand.idempotency_key == retry_key,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def replay_result(command: BackgroundManualRetryCommand) -> ManualRetryResult:
        if (
            command.job_id != job.id
            or command.actor != retry_actor
            or command.reason != retry_reason
        ):
            raise JobIdempotencyConflict(
                "manual retry idempotency key names different canonical input"
            )
        return ManualRetryResult(
            command_id=command.id,
            job_id=command.job_id,
            created=False,
        )

    existing = locked_existing()
    if existing is not None:
        return replay_result(existing)
    if job.state not in {"failed", "dead_letter"}:
        raise JobStateError("manual retry requires a failed or dead-letter job")
    if job.attempt_count:
        latest = session.scalar(
            select(BackgroundJobAttempt)
            .where(
                BackgroundJobAttempt.job_id == job.id,
                BackgroundJobAttempt.attempt_number == job.attempt_count,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if latest is None or latest.completed_at is None:
            raise JobStateError("manual retry requires a completed latest attempt")
    current = _clock_after_lock(session, test_only_now)
    command_id = uuid4()
    values = {
        "id": command_id,
        "job_id": job.id,
        "owner_id": fixed_scope.owner_id,
        "workspace_id": fixed_scope.workspace_id,
        "idempotency_key": retry_key,
        "actor": retry_actor,
        "reason": retry_reason,
        "requested_at": current,
        "state": "pending",
        "claimed_attempt_id": None,
        "claimed_at": None,
        "cancelled_at": None,
        "cancelled_actor": None,
        "cancelled_reason_code": None,
    }
    created = False
    command: BackgroundManualRetryCommand | None
    if _dialect_name(session) == "postgresql":
        inserted_id = session.scalar(
            postgresql_insert(BackgroundManualRetryCommand.__table__)
            .values(**values)
            .on_conflict_do_nothing()
            .returning(BackgroundManualRetryCommand.id)
        )
        if inserted_id is None:
            command = locked_existing()
            if command is None:
                raise JobStateError(
                    "another pending manual retry command already exists for this job"
                )
            return replay_result(command)
        command = session.scalar(
            select(BackgroundManualRetryCommand)
            .where(BackgroundManualRetryCommand.id == inserted_id)
            .execution_options(populate_existing=True)
        )
        created = True
    else:
        command = BackgroundManualRetryCommand(**values)
        session.add(command)
        created = True
    if command is None:
        raise JobServiceError("manual retry command insert could not be reloaded")
    job.state = "queued"
    job.next_retry_at = None
    job.error_code = None
    job.updated_at = current
    session.flush()
    return ManualRetryResult(
        command_id=command.id,
        job_id=job.id,
        created=created,
    )


def reconcile_expired_attempts(
    session: Session,
    *,
    scope: NarrationRequestScope,
    novel_ids: Sequence[UUID] | None = None,
    document_ids: Sequence[UUID] | None = None,
    resource_classes: Sequence[str] | None = None,
    job_kinds: Sequence[str] | None = None,
    limit: int = 100,
    retry_base_seconds: int = DEFAULT_RETRY_BASE_SECONDS,
    retry_cap_seconds: int = MAX_RETRY_DELAY_SECONDS,
    test_only_now: datetime | None = None,
) -> tuple[ReconciledAttempt, ...]:
    """Recover one expired attempt using the canonical execution-lock order.

    The public ``limit`` remains validated for compatibility, but a caller-owned
    transaction processes at most one attempt.  Holding resource A and then
    locking job B would invert the frozen job -> attempt -> epoch -> resource
    order; supervisors obtain batching by committing between calls.
    """

    fixed_scope = _scope(scope)
    _exact_int(
        limit, field_name="limit", minimum=1, maximum=1_000
    )
    # Validate policy before locking or mutating a recovery batch.
    retry_delay_seconds(
        1,
        base_seconds=retry_base_seconds,
        cap_seconds=retry_cap_seconds,
    )
    selection_current = _selection_clock(session, test_only_now)
    statement = (
        select(BackgroundJob)
        .join(
            BackgroundJobAttempt,
            and_(
                BackgroundJobAttempt.job_id == BackgroundJob.id,
                BackgroundJobAttempt.attempt_number == BackgroundJob.attempt_count,
            ),
        )
        .where(
            BackgroundJob.owner_id == fixed_scope.owner_id,
            BackgroundJob.workspace_id == fixed_scope.workspace_id,
            BackgroundJob.state.in_(("running", "cancel_requested")),
            BackgroundJobAttempt.completed_at.is_(None),
            BackgroundJobAttempt.lease_until <= selection_current,
        )
        .order_by(
            BackgroundJobAttempt.lease_until.asc(), BackgroundJob.id.asc()
        )
        .limit(1)
        .with_for_update(
            skip_locked=True, of=BackgroundJob
        )
        .execution_options(populate_existing=True)
    )
    statement = _apply_background_job_filters(
        statement,
        novel_ids=novel_ids,
        document_ids=document_ids,
        resource_classes=resource_classes,
        job_kinds=job_kinds,
    )
    job = session.scalar(statement)
    if job is None:
        return ()
    attempt = session.scalar(
        select(BackgroundJobAttempt)
        .where(
            BackgroundJobAttempt.job_id == job.id,
            BackgroundJobAttempt.attempt_number == job.attempt_count,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if attempt is None:
        raise JobServiceError("expired job has no current attempt")
    fence = JobFence(
        job_id=job.id,
        attempt_id=attempt.id,
        lease_token=attempt.lease_token,
        lease_generation=attempt.lease_generation,
    )
    locked = _lock_job_attempt_fence(
        session,
        scope=fixed_scope,
        fence=fence,
        allowed_job_states=frozenset({"running", "cancel_requested"}),
        test_only_now=test_only_now,
        require_active_epoch=False,
        require_live_attempt=False,
        require_live_resource=False,
    )
    if _database_datetime(
        locked.attempt.lease_until,
        field_name="lease_until",
    ) > locked.current:
        return ()
    if locked.epoch.state != "active":
        failure = _finish_failed_attempt(
            job=locked.job,
            attempt=locked.attempt,
            classification="security_failure",
            error_code="EXECUTOR_EPOCH_REVOKED",
            current=locked.current,
            retry_base_seconds=retry_base_seconds,
            retry_cap_seconds=retry_cap_seconds,
        )
        resulting_state: Literal[
            "retry_wait", "dead_letter", "failed", "cancelled"
        ] = failure.state
    elif locked.job.state == "cancel_requested":
        locked.attempt.completed_at = locked.current
        locked.attempt.error_classification = "cancelled"
        locked.attempt.error_code = "CANCELLED_LEASE_EXPIRED"
        locked.job.state = "cancelled"
        locked.job.next_retry_at = None
        locked.job.error_code = None
        locked.job.updated_at = locked.current
        resulting_state = "cancelled"
    else:
        failure = _finish_failed_attempt(
            job=locked.job,
            attempt=locked.attempt,
            classification="retryable",
            error_code="LEASE_EXPIRED",
            current=locked.current,
            retry_base_seconds=retry_base_seconds,
            retry_cap_seconds=retry_cap_seconds,
        )
        if failure.state == "failed":
            raise JobServiceError(
                "lease expiry reconciliation produced an impossible failed state"
            )
        resulting_state = failure.state
    _release_locked_resource(locked)
    session.flush()
    return (
        ReconciledAttempt(
            job_id=locked.job.id,
            attempt_id=locked.attempt.id,
            resulting_state=resulting_state,
        ),
    )


__all__ = (
    "CancelRequestResult",
    "EnqueueResult",
    "FailureResult",
    "JobFence",
    "JobFenceError",
    "JobIdempotencyConflict",
    "JobLease",
    "ManualRetryCommandRequired",
    "JobNotFoundError",
    "JobServiceError",
    "JobStateError",
    "JobValidationError",
    "ManualRetryResult",
    "PublicationFenceContext",
    "ReconciledAttempt",
    "acknowledge_cancel",
    "build_claim_statement",
    "claim_next_job",
    "complete_attempt",
    "enqueue_job",
    "fail_attempt",
    "fairness_score",
    "heartbeat_attempt",
    "lock_result_publish_fence",
    "lock_result_publish_fences",
    "manual_retry",
    "promote_due_retries",
    "reconcile_expired_attempts",
    "request_cancel",
    "retry_delay_seconds",
)
