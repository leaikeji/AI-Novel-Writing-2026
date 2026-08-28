"""T4 failed-segment manual retry projection and SQLAlchemy transaction.

The read projection is persistence-port based and therefore unit-testable.  The
write path deliberately accepts a real SQLAlchemy ``Session``: a MemoryStore can
prove canonical selection and state transitions, but it cannot prove PostgreSQL
row-lock ordering.  The caller owns commit/rollback; this module never publishes
a Manifest and never performs model or media I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Final, TypeVar
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    BackgroundJob,
    BackgroundJobAttempt,
    BackgroundManualRetryCommand,
    NarrationEdition,
    NarrationEditionSegment,
    NarrationEditionState,
    NarrationRequest,
    NarrationSegmentRender,
)
from .contracts import NarrationRequestScope
from .jobs import ManualRetryResult, manual_retry
from .renders import render_job_input_hash
from .services import (
    IdempotencyConflict,
    InvalidNarrationState,
    NarrationCasConflict,
    NarrationScopeMismatch,
    NarrationStore,
    SqlAlchemyNarrationStore,
    VoiceRightsUnavailable,
    canonical_sha256,
    require_exact_int,
    require_fixed_scope,
    require_local_novel,
    require_nonempty,
    require_row,
    require_sha256,
    require_usable_voice,
    utc_now,
)


FAILED_SEGMENT_RETRY_CONTRACT_VERSION: Final = "narration-failed-segment-retry/1"
_FAILURE_CODE: Final = re.compile(r"^[A-Z][A-Z0-9_]{0,95}$")
_ROOT_PREFIX: Final = "fsr:"
_REASON_PREFIX: Final = "FAILED_SEGMENT_RETRY:"
_T = TypeVar("_T")


class _UnlockedProjectionStore:
    """Read through a SQL adapter without pretending projection reads are locks."""

    def __init__(self, delegate: SqlAlchemyNarrationStore) -> None:
        self._delegate = delegate

    def add(self, row: object) -> None:
        self._delegate.add(row)

    def flush(self) -> None:
        self._delegate.flush()

    def get(self, model: type[_T], row_id: object, *, for_update: bool = False) -> _T | None:
        del for_update
        return self._delegate.get(model, row_id, for_update=False)

    def find_one(
        self, model: type[_T], *, for_update: bool = False, **filters: object
    ) -> _T | None:
        del for_update
        return self._delegate.find_one(model, for_update=False, **filters)

    def find_all(
        self,
        model: type[_T],
        *,
        order_by: tuple[str, ...] = (),
        for_update: bool = False,
        **filters: object,
    ) -> list[_T]:
        del for_update
        return self._delegate.find_all(
            model, order_by=order_by, for_update=False, **filters
        )

    def consume_render_publication_context(self, **kwargs: object) -> None:
        self._delegate.consume_render_publication_context(**kwargs)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class FailedSegmentRetryItem:
    segment_id: UUID
    ordinal: int
    failure_code: str
    retryable: bool
    retry_reason_code: str | None
    job_id: UUID
    fanout_segment_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class FailedSegmentRetryProjection:
    contract_version: str
    edition_id: UUID
    request_id: UUID
    request_version: int
    manifest_revision: int | None
    request_state: str
    edition_state: str
    items: tuple[FailedSegmentRetryItem, ...]


@dataclass(frozen=True, slots=True)
class RetryFailedSegmentsCommand:
    edition_id: UUID
    segment_ids: tuple[UUID, ...]
    expected_request_version: int
    expected_manifest_revision: int | None
    idempotency_key: str
    actor: str
    scope: NarrationRequestScope = NarrationRequestScope.fixed_local()


@dataclass(frozen=True, slots=True)
class FailedSegmentRetryGroup:
    render_id: UUID
    render_fingerprint: str
    job_id: UUID
    segment_ids: tuple[UUID, ...]
    edition_segment_ids: tuple[UUID, ...]
    edition_ids: tuple[UUID, ...]
    retryable: bool
    retry_reason_code: str | None


@dataclass(frozen=True, slots=True)
class FailedSegmentRetryPlan:
    edition_id: UUID
    request_id: UUID
    request_version: int
    manifest_revision: int | None
    request_state: str
    edition_state: str
    full_failure: bool
    accepted_segment_ids: tuple[UUID, ...]
    affected_segment_ids: tuple[UUID, ...]
    groups: tuple[FailedSegmentRetryGroup, ...]


@dataclass(frozen=True, slots=True)
class FailedSegmentRetryCommandResult:
    command_id: UUID
    job_id: UUID
    affected_segment_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class RetryFailedSegmentsResult:
    contract_version: str
    edition_id: UUID
    request_id: UUID
    accepted_segment_ids: tuple[UUID, ...]
    affected_segment_ids: tuple[UUID, ...]
    commands: tuple[FailedSegmentRetryCommandResult, ...]
    request_version: int
    request_state: str
    edition_state: str
    replayed: bool


@dataclass(frozen=True, slots=True)
class _RetryContext:
    edition: NarrationEdition
    request: NarrationRequest
    request_editions: tuple[NarrationEdition, ...]
    rows: tuple[NarrationEditionSegment, ...]
    manifest_revision: int | None


def _context(
    store: NarrationStore,
    *,
    edition_id: UUID,
    scope: NarrationRequestScope,
) -> _RetryContext:
    require_fixed_scope(scope)
    edition = require_row(store.get(NarrationEdition, edition_id), label="narration Edition")
    if edition.owner_id != scope.owner_id or edition.workspace_id != scope.workspace_id:
        raise NarrationScopeMismatch("Edition is outside fixed local scope")
    require_local_novel(store, edition.novel_id)
    request = require_row(store.get(NarrationRequest, edition.request_id), label="narration request")
    if (
        request.owner_id != scope.owner_id
        or request.workspace_id != scope.workspace_id
        or request.novel_id != edition.novel_id
        or request.document_id != edition.document_id
    ):
        raise NarrationScopeMismatch("failed-segment request provenance is invalid")
    if request.intent not in {"create", "update"}:
        raise InvalidNarrationState("batch/analyze retry is outside the T4 local path")
    editions = store.find_all(
        NarrationEdition,
        owner_id=scope.owner_id,
        workspace_id=scope.workspace_id,
        request_id=request.id,
        order_by=("id",),
    )
    if not editions or edition.id not in {row.id for row in editions}:
        raise InvalidNarrationState("request has no retryable Edition")
    if len(editions) != 1:
        # The current worker derives request completion from only the Editions
        # that share the completed render fingerprint.  Reopening a failed
        # multi-Edition request for a subset could therefore mark the request
        # ready while another Edition remains unavailable.  Keep this topology
        # fail-closed until request-wide completion is made authoritative.
        raise InvalidNarrationState(
            "failed segment retry requires exactly one Edition per request"
        )
    rows: list[NarrationEditionSegment] = []
    for candidate in editions:
        if candidate.novel_id != edition.novel_id or candidate.document_id != edition.document_id:
            raise NarrationScopeMismatch("retry fanout crosses Edition scope")
        candidate_rows = store.find_all(
            NarrationEditionSegment,
            edition_id=candidate.id,
            order_by=("ordinal",),
        )
        if not candidate_rows or [row.ordinal for row in candidate_rows] != list(range(len(candidate_rows))):
            raise InvalidNarrationState("Edition segments must be complete and contiguous")
        for row in candidate_rows:
            require_sha256(row.render_fingerprint, field="render_fingerprint")
            if row.script_version_id != candidate.script_version_id:
                raise NarrationScopeMismatch("retry segment belongs to another script version")
        rows.extend(candidate_rows)
    pointer = store.find_one(NarrationEditionState, edition_id=edition.id)
    manifest_revision = None
    if pointer is not None:
        if pointer.current_manifest_id is None and pointer.current_manifest_revision is None:
            manifest_revision = None
        elif pointer.current_manifest_id is None or pointer.current_manifest_revision is None:
            raise InvalidNarrationState("Manifest pointer identity is incomplete")
        else:
            manifest_revision = require_exact_int(
                pointer.current_manifest_revision,
                field="current_manifest_revision",
                minimum=1,
            )
    return _RetryContext(
        edition=edition,
        request=request,
        request_editions=tuple(editions),
        rows=tuple(rows),
        manifest_revision=manifest_revision,
    )


def _aggregate_failure_mode(context: _RetryContext) -> tuple[bool, str | None]:
    states = [row.render_state for row in context.rows]
    all_failed = all(state == "failed" for state in states)
    if all_failed:
        if context.request.state != "failed" or any(
            edition.state != "unavailable" for edition in context.request_editions
        ):
            return True, "AGGREGATE_FULL_FAILURE_STATE_INVALID"
        return True, None
    legal_partial_states = {"failed", "pending", "queued", "rendering", "ready"}
    if (
        any(state == "failed" for state in states)
        and any(state != "failed" for state in states)
        and all(state in legal_partial_states for state in states)
        and context.request.state in {"rendering", "partial_ready"}
        and all(
            edition.state in {"rendering", "partial_ready"}
            for edition in context.request_editions
        )
    ):
        return False, None
    return False, "AGGREGATE_PARTIAL_FAILURE_STATE_INVALID"


def _render_and_job(
    store: NarrationStore,
    *,
    context: _RetryContext,
    fingerprint: str,
    fanout: tuple[NarrationEditionSegment, ...],
) -> tuple[NarrationSegmentRender, BackgroundJob]:
    render = require_row(
        store.find_one(
            NarrationSegmentRender,
            owner_id=context.edition.owner_id,
            workspace_id=context.edition.workspace_id,
            render_fingerprint=fingerprint,
        ),
        label="failed segment render",
    )
    if (
        render.novel_id != context.edition.novel_id
        or render.request_id != context.request.id
        or render.render_fingerprint != fingerprint
        or render.model_fingerprint != context.edition.tts_fingerprint
        or render.postprocess_fingerprint != context.edition.postprocess_fingerprint
    ):
        raise NarrationScopeMismatch("failed render provenance is invalid")
    if any(row.voice_version_id != render.voice_version_id for row in fanout):
        raise NarrationScopeMismatch("retry fanout changes voice identity")
    job = require_row(store.get(BackgroundJob, render.source_job_id), label="render job")
    source_matches = [
        row
        for row in fanout
        if job.input_hash
        == render_job_input_hash(
            edition_segment_id=row.id,
            render_fingerprint=fingerprint,
        )
    ]
    if (
        job.owner_id != context.edition.owner_id
        or job.workspace_id != context.edition.workspace_id
        or job.novel_id != context.edition.novel_id
        or job.request_id != context.request.id
        or job.job_kind != "narration.segment_render"
        or job.resource_class != "moss-nano"
        or job.request_allows_render is not True
        or len(source_matches) != 1
    ):
        raise NarrationScopeMismatch("failed render source job provenance is invalid")
    return render, job


def _group(
    store: NarrationStore,
    *,
    context: _RetryContext,
    fingerprint: str,
    aggregate_reason: str | None,
) -> FailedSegmentRetryGroup:
    fanout = tuple(
        sorted(
            (row for row in context.rows if row.render_fingerprint == fingerprint),
            key=lambda row: (str(row.edition_id), row.ordinal),
        )
    )
    render, job = _render_and_job(
        store, context=context, fingerprint=fingerprint, fanout=fanout
    )
    reason = aggregate_reason
    if render.state != "failed" or any(row.render_state != "failed" for row in fanout):
        reason = reason or "FANOUT_NOT_ALL_FAILED"
    if job.state not in {"failed", "dead_letter"}:
        reason = reason or "JOB_NOT_MANUALLY_RETRYABLE"
    if job.attempt_count:
        attempt = store.find_one(
            BackgroundJobAttempt,
            job_id=job.id,
            attempt_number=job.attempt_count,
        )
        if attempt is None or attempt.completed_at is None:
            reason = reason or "LATEST_ATTEMPT_NOT_COMPLETE"
    try:
        for voice_version_id in sorted({row.voice_version_id for row in fanout}, key=str):
            require_usable_voice(
                store,
                voice_version_id,
                novel_id=context.edition.novel_id,
            )
    except VoiceRightsUnavailable:
        reason = reason or "VOICE_RIGHTS_UNAVAILABLE"
    return FailedSegmentRetryGroup(
        render_id=render.id,
        render_fingerprint=fingerprint,
        job_id=job.id,
        segment_ids=tuple(sorted({row.segment_id for row in fanout}, key=str)),
        edition_segment_ids=tuple(row.id for row in fanout),
        edition_ids=tuple(sorted({row.edition_id for row in fanout}, key=str)),
        retryable=reason is None,
        retry_reason_code=reason,
    )


def project_failed_segment_retries(
    store: NarrationStore,
    *,
    edition_id: UUID,
    scope: NarrationRequestScope = NarrationRequestScope.fixed_local(),
) -> FailedSegmentRetryProjection:
    """List failed public segment IDs with exact request/fingerprint fanout."""

    context = _context(store, edition_id=edition_id, scope=scope)
    _full_failure, aggregate_reason = _aggregate_failure_mode(context)
    own_rows = [row for row in context.rows if row.edition_id == edition_id]
    groups: dict[str, FailedSegmentRetryGroup] = {}
    items: list[FailedSegmentRetryItem] = []
    for row in own_rows:
        if row.render_state != "failed":
            continue
        failure_code = row.failure_code or "SEGMENT_RENDER_FAILED"
        if not _FAILURE_CODE.fullmatch(failure_code):
            raise InvalidNarrationState("failed segment has no stable failure code")
        group = groups.get(row.render_fingerprint)
        if group is None:
            group = _group(
                store,
                context=context,
                fingerprint=row.render_fingerprint,
                aggregate_reason=aggregate_reason,
            )
            groups[row.render_fingerprint] = group
        items.append(
            FailedSegmentRetryItem(
                segment_id=row.segment_id,
                ordinal=row.ordinal,
                failure_code=failure_code,
                retryable=group.retryable,
                retry_reason_code=group.retry_reason_code,
                job_id=group.job_id,
                fanout_segment_ids=group.segment_ids,
            )
        )
    return FailedSegmentRetryProjection(
        contract_version=FAILED_SEGMENT_RETRY_CONTRACT_VERSION,
        edition_id=context.edition.id,
        request_id=context.request.id,
        request_version=context.request.version,
        manifest_revision=context.manifest_revision,
        request_state=context.request.state,
        edition_state=context.edition.state,
        items=tuple(items),
    )


def plan_failed_segment_retry(
    store: NarrationStore,
    command: RetryFailedSegmentsCommand,
    *,
    require_currently_retryable: bool = True,
    enforce_cas: bool = True,
) -> FailedSegmentRetryPlan:
    require_fixed_scope(command.scope)
    if type(command.segment_ids) is not tuple:
        raise InvalidNarrationState("segment_ids must be a frozen tuple")
    if not 1 <= len(command.segment_ids) <= 100 or len(set(command.segment_ids)) != len(command.segment_ids):
        raise InvalidNarrationState("segment_ids must contain 1..100 unique IDs")
    require_exact_int(
        command.expected_request_version,
        field="expected_request_version",
        minimum=1,
    )
    if command.expected_manifest_revision is not None:
        require_exact_int(
            command.expected_manifest_revision,
            field="expected_manifest_revision",
            minimum=1,
        )
    require_nonempty(command.idempotency_key, field="idempotency_key")
    require_nonempty(command.actor, field="actor")
    context = _context(store, edition_id=command.edition_id, scope=command.scope)
    if enforce_cas and context.request.version != command.expected_request_version:
        raise NarrationCasConflict("narration request version changed")
    if enforce_cas and context.manifest_revision != command.expected_manifest_revision:
        raise NarrationCasConflict("Manifest current revision changed")
    own_by_public_id: dict[UUID, NarrationEditionSegment] = {}
    for row in context.rows:
        if row.edition_id != context.edition.id:
            continue
        if row.segment_id in own_by_public_id:
            raise InvalidNarrationState("Edition exposes duplicate public segment IDs")
        own_by_public_id[row.segment_id] = row
    try:
        selected = [own_by_public_id[segment_id] for segment_id in command.segment_ids]
    except KeyError as error:
        raise NarrationScopeMismatch("retry selection names a segment outside the Edition") from error
    full_failure, aggregate_reason = _aggregate_failure_mode(context)
    groups = tuple(
        _group(
            store,
            context=context,
            fingerprint=fingerprint,
            aggregate_reason=aggregate_reason,
        )
        for fingerprint in sorted({row.render_fingerprint for row in selected})
    )
    if require_currently_retryable and any(not group.retryable for group in groups):
        reason = next(group.retry_reason_code for group in groups if not group.retryable)
        raise InvalidNarrationState(f"failed segment retry is unavailable: {reason}")
    return FailedSegmentRetryPlan(
        edition_id=context.edition.id,
        request_id=context.request.id,
        request_version=context.request.version,
        manifest_revision=context.manifest_revision,
        request_state=context.request.state,
        edition_state=context.edition.state,
        full_failure=full_failure,
        accepted_segment_ids=tuple(sorted(command.segment_ids, key=str)),
        affected_segment_ids=tuple(
            sorted({segment_id for group in groups for segment_id in group.segment_ids}, key=str)
        ),
        groups=tuple(sorted(groups, key=lambda group: str(group.job_id))),
    )


def _operation_hash(command: RetryFailedSegmentsCommand, plan: FailedSegmentRetryPlan) -> str:
    return canonical_sha256(
        {
            "contract_version": FAILED_SEGMENT_RETRY_CONTRACT_VERSION,
            "edition_id": str(command.edition_id),
            "accepted_segment_ids": [str(value) for value in plan.accepted_segment_ids],
            "affected_segment_ids": [str(value) for value in plan.affected_segment_ids],
            "expected_request_version": command.expected_request_version,
            "expected_manifest_revision": command.expected_manifest_revision,
        }
    )


def _root_is_replay(
    existing: list[BackgroundManualRetryCommand],
    *,
    selected_job_ids: set[UUID],
    actor: str,
    reason: str,
) -> bool:
    if not existing:
        return False
    if (
        {row.job_id for row in existing} != selected_job_ids
        or any(row.actor != actor or row.reason != reason for row in existing)
    ):
        raise IdempotencyConflict(
            "failed segment retry root key names different canonical input"
        )
    return True


def _reset_failed_segment_retry_rows(
    store: NarrationStore,
    *,
    plan: FailedSegmentRetryPlan,
    expected_request_version: int,
) -> tuple[NarrationRequest, NarrationEdition]:
    """Apply only the domain reverse edges after manual commands exist.

    Production calls this after the SQL executor acquired the frozen locks.
    Unit tests use it to prove state/CAS behavior; it is not a substitute for
    the SQL executor's row locks.
    """

    request = require_row(
        store.get(NarrationRequest, plan.request_id), label="narration request"
    )
    edition = require_row(
        store.get(NarrationEdition, plan.edition_id), label="narration Edition"
    )
    if request.version != expected_request_version:
        raise NarrationCasConflict("narration request version changed")
    expected_pair = (
        {("failed", "unavailable")}
        if plan.full_failure
        else {
            ("rendering", "rendering"),
            ("partial_ready", "partial_ready"),
        }
    )
    if (request.state, edition.state) not in expected_pair:
        raise InvalidNarrationState("retry aggregate state changed")
    renders = [
        require_row(store.get(NarrationSegmentRender, group.render_id), label="failed render")
        for group in plan.groups
    ]
    rows = [
        require_row(store.get(NarrationEditionSegment, row_id), label="fanout segment")
        for group in plan.groups
        for row_id in group.edition_segment_ids
    ]
    if any(render.state != "failed" for render in renders) or any(
        row.render_state != "failed" for row in rows
    ):
        raise InvalidNarrationState("retry rows are no longer terminal failed")
    affected_editions = [
        require_row(store.get(NarrationEdition, edition_id), label="fanout Edition")
        for edition_id in sorted({row.edition_id for row in rows}, key=str)
    ]
    if plan.full_failure and any(
        affected_edition.state != "unavailable"
        for affected_edition in affected_editions
    ):
        raise InvalidNarrationState("full-failure fanout Edition changed")
    if not plan.full_failure and any(
        affected_edition.state not in {"rendering", "partial_ready"}
        for affected_edition in affected_editions
    ):
        raise InvalidNarrationState("partial-failure fanout Edition changed")
    now = utc_now()
    request.version += 1
    request.updated_at = now
    if plan.full_failure:
        request.state = "queued"
        request.failure_code = None
        request.completed_at = None
        for affected_edition in affected_editions:
            affected_edition.state = "rendering"
            affected_edition.unavailable_reason = None
    for render in renders:
        render.state = "pending"
        render.audio_validation_json = {}
        render.ready_at = None
        render.duration_ms = None
    for row in rows:
        row.render_state = "queued"
        row.failure_code = None
    store.flush()
    return request, edition


def retry_failed_segments(
    session: Session,
    command: RetryFailedSegmentsCommand,
) -> RetryFailedSegmentsResult:
    """Authorize and reset failed fanout rows in one caller-owned transaction.

    Lock order is all request render jobs by UUID, retry command/latest attempt,
    Request, target Edition, target EditionState, renders by UUID, then
    EditionSegments by ``(edition_id, ordinal)``.  Edition precedes EditionState
    to match ``publish_manifest`` and avoid an inverse-lock deadlock.  A replay
    only re-reads immutable manual commands and never applies reverse edges.
    """

    store = SqlAlchemyNarrationStore(session)
    projection_store = _UnlockedProjectionStore(store)
    # Resolve stable scope and fanout without locks.  Every decision is repeated
    # after the request-wide job mutex has been acquired.
    initial = plan_failed_segment_retry(
        projection_store,
        command,
        require_currently_retryable=False,
        enforce_cas=False,
    )
    all_jobs = list(
        session.scalars(
            select(BackgroundJob)
            .where(
                BackgroundJob.owner_id == command.scope.owner_id,
                BackgroundJob.workspace_id == command.scope.workspace_id,
                BackgroundJob.request_id == initial.request_id,
                BackgroundJob.job_kind == "narration.segment_render",
            )
            .order_by(BackgroundJob.id.asc())
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    selected_job_ids = {group.job_id for group in initial.groups}
    if not selected_job_ids.issubset({job.id for job in all_jobs}):
        raise NarrationScopeMismatch("retry source jobs changed request scope")
    root_digest = canonical_sha256({"idempotency_key": command.idempotency_key})
    root_prefix = f"{_ROOT_PREFIX}{root_digest}:"
    operation_hash = _operation_hash(command, initial)
    reason = f"{_REASON_PREFIX}{operation_hash}"
    existing = list(
        session.scalars(
            select(BackgroundManualRetryCommand)
            .where(
                BackgroundManualRetryCommand.owner_id == command.scope.owner_id,
                BackgroundManualRetryCommand.workspace_id == command.scope.workspace_id,
                BackgroundManualRetryCommand.idempotency_key.like(f"{root_prefix}%"),
            )
            .order_by(BackgroundManualRetryCommand.job_id.asc())
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    root_replay = _root_is_replay(
        existing,
        selected_job_ids=selected_job_ids,
        actor=command.actor,
        reason=reason,
    )
    locked_plan = initial
    if not root_replay:
        locked_plan = plan_failed_segment_retry(
            projection_store,
            command,
            require_currently_retryable=True,
            enforce_cas=False,
        )
    manual_results: list[ManualRetryResult] = []
    for group in initial.groups:
        manual_results.append(
            manual_retry(
                session,
                scope=command.scope,
                job_id=group.job_id,
                actor=command.actor,
                reason=reason,
                idempotency_key=f"{root_prefix}{group.job_id}",
            )
        )
    created_flags = {result.created for result in manual_results}
    if created_flags == {False}:
        if not root_replay:
            raise InvalidNarrationState("manual retry replay lacks its root command set")
        current = plan_failed_segment_retry(
            projection_store,
            command,
            require_currently_retryable=False,
            enforce_cas=False,
        )
        edition = require_row(
            store.get(NarrationEdition, current.edition_id), label="narration Edition"
        )
        request = require_row(
            store.get(NarrationRequest, current.request_id), label="narration request"
        )
        return RetryFailedSegmentsResult(
            contract_version=FAILED_SEGMENT_RETRY_CONTRACT_VERSION,
            edition_id=current.edition_id,
            request_id=current.request_id,
            accepted_segment_ids=current.accepted_segment_ids,
            affected_segment_ids=current.affected_segment_ids,
            commands=tuple(
                FailedSegmentRetryCommandResult(
                    command_id=result.command_id,
                    job_id=result.job_id,
                    affected_segment_ids=next(
                        group.segment_ids
                        for group in current.groups
                        if group.job_id == result.job_id
                    ),
                )
                for result in manual_results
            ),
            request_version=request.version,
            request_state=request.state,
            edition_state=edition.state,
            replayed=True,
        )
    if created_flags != {True}:
        raise InvalidNarrationState("retry root has a partial child-command history")
    if root_replay:
        raise InvalidNarrationState("retry root replay created a new child command")
    # New command: CAS and eligibility are evaluated after command/attempt locks.
    request = session.scalar(
        select(NarrationRequest)
        .where(NarrationRequest.id == initial.request_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if request is None or request.version != command.expected_request_version:
        raise NarrationCasConflict("narration request version changed")
    locked_edition = session.scalar(
        select(NarrationEdition)
        .where(NarrationEdition.id == command.edition_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked_edition is None or locked_edition.request_id != initial.request_id:
        raise NarrationScopeMismatch("retry Edition changed request scope")
    pointer = session.scalar(
        select(NarrationEditionState)
        .where(NarrationEditionState.edition_id == command.edition_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    current_revision = pointer.current_manifest_revision if pointer is not None else None
    if current_revision != command.expected_manifest_revision:
        raise NarrationCasConflict("Manifest current revision changed")
    locked_renders = list(
        session.scalars(
            select(NarrationSegmentRender)
            .where(NarrationSegmentRender.id.in_([group.render_id for group in locked_plan.groups]))
            .order_by(NarrationSegmentRender.id.asc())
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    locked_segments = list(
        session.scalars(
            select(NarrationEditionSegment)
            .where(
                NarrationEditionSegment.id.in_(
                    [row_id for group in locked_plan.groups for row_id in group.edition_segment_ids]
                )
            )
            .order_by(
                NarrationEditionSegment.edition_id.asc(),
                NarrationEditionSegment.ordinal.asc(),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    if len(locked_renders) != len(locked_plan.groups) or len(locked_segments) != sum(
        len(group.edition_segment_ids) for group in locked_plan.groups
    ):
        raise InvalidNarrationState("retry fanout rows disappeared")
    for voice_version_id in sorted(
        {
            row.voice_version_id
            for row in locked_segments
        },
        key=str,
    ):
        require_usable_voice(
            store,
            voice_version_id,
            novel_id=request.novel_id,
        )
    current = locked_plan
    request, edition = _reset_failed_segment_retry_rows(
        store,
        plan=current,
        expected_request_version=command.expected_request_version,
    )
    return RetryFailedSegmentsResult(
        contract_version=FAILED_SEGMENT_RETRY_CONTRACT_VERSION,
        edition_id=current.edition_id,
        request_id=current.request_id,
        accepted_segment_ids=current.accepted_segment_ids,
        affected_segment_ids=current.affected_segment_ids,
        commands=tuple(
            FailedSegmentRetryCommandResult(
                command_id=result.command_id,
                job_id=result.job_id,
                affected_segment_ids=next(
                    group.segment_ids
                    for group in current.groups
                    if group.job_id == result.job_id
                ),
            )
            for result in manual_results
        ),
        request_version=request.version,
        request_state=request.state,
        edition_state=edition.state,
        replayed=False,
    )


__all__ = [
    "FAILED_SEGMENT_RETRY_CONTRACT_VERSION",
    "FailedSegmentRetryCommandResult",
    "FailedSegmentRetryGroup",
    "FailedSegmentRetryItem",
    "FailedSegmentRetryPlan",
    "FailedSegmentRetryProjection",
    "RetryFailedSegmentsCommand",
    "RetryFailedSegmentsResult",
    "plan_failed_segment_retry",
    "project_failed_segment_retries",
    "retry_failed_segments",
]
