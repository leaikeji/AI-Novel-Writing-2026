from __future__ import annotations

from dataclasses import replace
import inspect
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from backend.models import (
    BackgroundJob,
    BackgroundManualRetryCommand,
    NarrationEditionSegment,
    NarrationEditionState,
    NarrationRequest,
    NarrationSegmentRender,
    VoiceRightsEvent,
)
from backend.narration.failed_segment_retry import (
    FAILED_SEGMENT_RETRY_CONTRACT_VERSION,
    RetryFailedSegmentsCommand,
    _operation_hash,
    _reset_failed_segment_retry_rows,
    _root_is_replay,
    plan_failed_segment_retry,
    project_failed_segment_retries,
    retry_failed_segments,
)
from backend.narration.services import (
    IdempotencyConflict,
    InvalidNarrationState,
    NarrationCasConflict,
)
from tests.narration.test_domain_services import (
    MemoryNarrationStore,
    _edition_with_ready_renders,
)
from tests.narration.test_regeneration import _clone_projection_target


NOW = datetime(2026, 8, 28, 5, 30, tzinfo=UTC)


def _foundation():
    store = MemoryNarrationStore()
    foundation = _edition_with_ready_renders(store)
    request = foundation[3]
    edition = foundation[4]
    renders = foundation[6]
    rows = store.find_all(
        NarrationEditionSegment,
        edition_id=edition.id,
        order_by=("ordinal",),
    )
    assert isinstance(request, NarrationRequest)
    assert len(rows) >= 2
    return store, foundation, request, edition, renders, rows


def _fail(
    store: MemoryNarrationStore,
    row: NarrationEditionSegment,
    render: NarrationSegmentRender,
    *,
    code: str = "NANO_AUDIO_INVALID",
) -> BackgroundJob:
    job = store.get(BackgroundJob, render.source_job_id)
    assert job is not None
    row.render_state = "failed"
    row.failure_code = code
    render.state = "failed"
    job.state = "failed"
    job.error_code = code
    return job


def _command(request: NarrationRequest, edition_id, *segment_ids, revision=None):
    return RetryFailedSegmentsCommand(
        edition_id=edition_id,
        segment_ids=tuple(segment_ids),
        expected_request_version=request.version,
        expected_manifest_revision=revision,
        idempotency_key="retry-root-0001",
        actor="local-owner",
    )


def test_partial_failure_projection_and_reset_preserve_aggregate_state() -> None:
    store, _foundation_rows, request, edition, renders, rows = _foundation()
    job = _fail(store, rows[0], renders[0])
    request.state = "partial_ready"
    edition.state = "partial_ready"

    projection = project_failed_segment_retries(store, edition_id=edition.id)

    assert projection.contract_version == FAILED_SEGMENT_RETRY_CONTRACT_VERSION
    assert projection.request_version == request.version
    assert projection.manifest_revision is None
    assert len(projection.items) == 1
    item = projection.items[0]
    assert item.segment_id == rows[0].segment_id
    assert item.job_id == job.id
    assert item.retryable is True and item.retry_reason_code is None
    plan = plan_failed_segment_retry(
        store,
        _command(request, edition.id, rows[0].segment_id),
    )
    before_version = request.version

    reset_request, reset_edition = _reset_failed_segment_retry_rows(
        store,
        plan=plan,
        expected_request_version=before_version,
    )

    assert reset_request.version == before_version + 1
    assert reset_request.state == "partial_ready"
    assert reset_edition.state == "partial_ready"
    assert renders[0].state == "pending"
    assert renders[0].audio_validation_json == {}
    assert rows[0].render_state == "queued" and rows[0].failure_code is None
    assert job.state == "failed"  # jobs.manual_retry owns this independent edge


def test_partial_failure_without_any_ready_segment_remains_retryable() -> None:
    store, _foundation_rows, request, edition, renders, rows = _foundation()
    _fail(store, rows[0], renders[0])
    rows[1].render_state = "queued"
    request.state = "rendering"
    edition.state = "rendering"

    projection = project_failed_segment_retries(store, edition_id=edition.id)

    assert len(projection.items) == 1
    assert projection.items[0].retryable is True
    plan = plan_failed_segment_retry(
        store,
        _command(request, edition.id, rows[0].segment_id),
    )
    assert plan.full_failure is False


@pytest.mark.parametrize("illegal_state", ["cancelled", "quarantined"])
def test_partial_failure_rejects_nonproductive_terminal_fanout(
    illegal_state: str,
) -> None:
    store, _foundation_rows, request, edition, renders, rows = _foundation()
    _fail(store, rows[0], renders[0])
    rows[1].render_state = illegal_state
    request.state = "rendering"
    edition.state = "rendering"

    projection = project_failed_segment_retries(store, edition_id=edition.id)

    assert projection.items[0].retryable is False
    assert (
        projection.items[0].retry_reason_code
        == "AGGREGATE_PARTIAL_FAILURE_STATE_INVALID"
    )
    with pytest.raises(
        InvalidNarrationState,
        match="AGGREGATE_PARTIAL_FAILURE_STATE_INVALID",
    ):
        plan_failed_segment_retry(
            store,
            _command(request, edition.id, rows[0].segment_id),
        )


def test_non_source_fanout_segment_resolves_the_single_source_job() -> None:
    store, _foundation_rows, request, edition, renders, rows = _foundation()
    source = rows[0]
    non_source = rows[1]
    non_source.render_fingerprint = source.render_fingerprint
    source_job = _fail(store, source, renders[0])
    non_source.render_state = "failed"
    non_source.failure_code = "NANO_AUDIO_INVALID"
    for remaining in rows[2:]:
        matching = next(
            render
            for render in renders
            if render.render_fingerprint == remaining.render_fingerprint
        )
        _fail(store, remaining, matching)
    request.state = "failed"
    request.failure_code = "NANO_AUDIO_INVALID"
    edition.state = "unavailable"
    edition.unavailable_reason = "NANO_AUDIO_INVALID"

    projection = project_failed_segment_retries(store, edition_id=edition.id)
    selected = next(item for item in projection.items if item.segment_id == non_source.segment_id)

    assert selected.retryable is True
    assert selected.job_id == source_job.id
    assert selected.fanout_segment_ids == tuple(
        sorted({source.segment_id, non_source.segment_id}, key=str)
    )
    plan = plan_failed_segment_retry(
        store,
        _command(request, edition.id, non_source.segment_id),
    )
    assert plan.full_failure is True
    assert plan.accepted_segment_ids == (non_source.segment_id,)
    assert plan.affected_segment_ids == selected.fanout_segment_ids
    assert plan.groups[0].edition_segment_ids == (source.id, non_source.id)


def test_full_failure_reset_reopens_request_edition_and_only_selected_fanout() -> None:
    store, _foundation_rows, request, edition, renders, rows = _foundation()
    for row, render in zip(rows, renders, strict=True):
        _fail(store, row, render)
    request.state = "failed"
    request.failure_code = "NANO_AUDIO_INVALID"
    request.completed_at = NOW
    edition.state = "unavailable"
    edition.unavailable_reason = "NANO_AUDIO_INVALID"
    command = _command(request, edition.id, *(row.segment_id for row in rows))
    plan = plan_failed_segment_retry(store, command)
    before_version = request.version

    reset_request, reset_edition = _reset_failed_segment_retry_rows(
        store,
        plan=plan,
        expected_request_version=before_version,
    )

    assert reset_request.state == "queued"
    assert reset_request.version == before_version + 1
    assert reset_request.failure_code is None and reset_request.completed_at is None
    assert reset_edition.state == "rendering"
    assert reset_edition.unavailable_reason is None
    assert all(render.state == "pending" for render in renders)
    assert all(row.render_state == "queued" and row.failure_code is None for row in rows)


def test_multi_edition_request_retry_is_fail_closed_until_completion_is_request_wide() -> None:
    store, _foundation_rows, request, edition, renders, rows = _foundation()
    _fail(store, rows[0], renders[0])
    request.state = "partial_ready"
    edition.state = "partial_ready"
    duplicate, _duplicate_rows = _clone_projection_target(store, edition, rows)
    duplicate.state = "partial_ready"

    with pytest.raises(InvalidNarrationState, match="exactly one Edition"):
        project_failed_segment_retries(store, edition_id=edition.id)


def test_selection_cas_and_manifest_revision_are_checked_before_reset() -> None:
    store, _foundation_rows, request, edition, renders, rows = _foundation()
    _fail(store, rows[0], renders[0])
    request.state = "partial_ready"
    edition.state = "partial_ready"
    pointer = NarrationEditionState(
        edition_id=edition.id,
        current_manifest_id=uuid4(),
        current_manifest_revision=4,
        version=4,
        updated_actor="worker",
        updated_at=NOW,
    )
    store.add(pointer)

    good = _command(request, edition.id, rows[0].segment_id, revision=4)
    assert plan_failed_segment_retry(store, good).manifest_revision == 4
    stale_request = replace(good, expected_request_version=request.version - 1)
    with pytest.raises(NarrationCasConflict, match="request version"):
        plan_failed_segment_retry(store, stale_request)
    stale_manifest = replace(good, expected_manifest_revision=3)
    with pytest.raises(NarrationCasConflict, match="Manifest"):
        plan_failed_segment_retry(store, stale_manifest)
    assert rows[0].render_state == "failed" and renders[0].state == "failed"


def test_incomplete_fanout_and_revoked_voice_fail_closed() -> None:
    store, foundation, request, edition, renders, rows = _foundation()
    rows[1].render_fingerprint = rows[0].render_fingerprint
    _fail(store, rows[0], renders[0])
    request.state = "partial_ready"
    edition.state = "partial_ready"

    projection = project_failed_segment_retries(store, edition_id=edition.id)
    assert projection.items[0].retryable is False
    assert projection.items[0].retry_reason_code == "FANOUT_NOT_ALL_FAILED"
    with pytest.raises(InvalidNarrationState, match="FANOUT_NOT_ALL_FAILED"):
        plan_failed_segment_retry(
            store,
            _command(request, edition.id, rows[0].segment_id),
        )

    rows[1].render_fingerprint = renders[1].render_fingerprint
    rights = foundation[8]
    store.add(
        VoiceRightsEvent(
            id=uuid4(),
            rights_record_id=rights.id,
            event_key="revoke-retry",
            event_type="revoked",
            actor="local-owner",
            occurred_at=NOW,
        )
    )
    blocked = project_failed_segment_retries(store, edition_id=edition.id)
    assert blocked.items[0].retryable is False
    assert blocked.items[0].retry_reason_code == "VOICE_RIGHTS_UNAVAILABLE"


def test_reset_validates_every_row_before_any_reverse_edge() -> None:
    store, _foundation_rows, request, edition, renders, rows = _foundation()
    _fail(store, rows[0], renders[0])
    request.state = "partial_ready"
    edition.state = "partial_ready"
    plan = plan_failed_segment_retry(
        store,
        _command(request, edition.id, rows[0].segment_id),
    )
    version = request.version
    renders[0].state = "pending"

    with pytest.raises(InvalidNarrationState, match="no longer terminal"):
        _reset_failed_segment_retry_rows(
            store,
            plan=plan,
            expected_request_version=version,
        )

    assert request.version == version and request.state == "partial_ready"
    assert rows[0].render_state == "failed"


def test_root_and_child_idempotency_are_canonical_and_conflicting_payloads_fail() -> None:
    store, _foundation_rows, request, edition, renders, rows = _foundation()
    job = _fail(store, rows[0], renders[0])
    request.state = "partial_ready"
    edition.state = "partial_ready"
    command = _command(request, edition.id, rows[0].segment_id)
    plan = plan_failed_segment_retry(store, command)
    operation_hash = _operation_hash(command, plan)
    reason = f"FAILED_SEGMENT_RETRY:{operation_hash}"
    existing = BackgroundManualRetryCommand(
        id=uuid4(),
        job_id=job.id,
        owner_id=job.owner_id,
        workspace_id=job.workspace_id,
        idempotency_key=f"fsr:{'a' * 64}:{job.id}",
        actor=command.actor,
        reason=reason,
        requested_at=NOW,
        state="pending",
    )

    assert _root_is_replay(
        [existing],
        selected_job_ids={job.id},
        actor=command.actor,
        reason=reason,
    ) is True
    with pytest.raises(IdempotencyConflict, match="different canonical input"):
        _root_is_replay(
            [existing],
            selected_job_ids={job.id},
            actor=command.actor,
            reason=f"FAILED_SEGMENT_RETRY:{'b' * 64}",
        )
    with pytest.raises(IdempotencyConflict, match="different canonical input"):
        _root_is_replay(
            [existing],
            selected_job_ids={job.id, uuid4()},
            actor=command.actor,
            reason=reason,
        )


def test_sql_executor_owns_no_manifest_and_freezes_the_documented_lock_order() -> None:
    source = inspect.getsource(retry_failed_segments)
    assert "manual_retry(" in source
    assert "publish_manifest(" not in source
    assert "BackgroundJob.id.asc()" in source
    assert "BackgroundManualRetryCommand.job_id.asc()" in source
    assert source.index("BackgroundJob.id.asc()") < source.index("manual_retry(")
    assert source.index("manual_retry(") < source.index("select(NarrationRequest)")
    request_lock = source.index("select(NarrationRequest)")
    edition_lock = source.index("locked_edition =")
    state_lock = source.index("select(NarrationEditionState)")
    render_lock = source.index("select(NarrationSegmentRender)")
    assert request_lock < edition_lock < state_lock < render_lock
    state_block = source[state_lock:render_lock]
    assert ".with_for_update()" in state_block
    assert render_lock < source.index("select(NarrationEditionSegment)")
    replay_branch = source.index("if created_flags == {False}")
    replay_return = source.index("replayed=True", replay_branch)
    reset_call = source.rindex("_reset_failed_segment_retry_rows(")
    assert replay_branch < replay_return < reset_call
