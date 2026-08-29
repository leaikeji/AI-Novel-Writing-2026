from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from typing import Iterator
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from backend.models import (
    BackgroundJob,
    DocumentNarrationState,
    DocumentWorkingCopy,
    MediaAsset,
    NarrationEdition,
    NarrationEditionState,
    NarrationEditionSegment,
    NarrationManifest,
    NarrationRequest,
    NarrationSegmentRender,
)
from backend.narration import document_state
from backend.narration import edition_service as edition_service_module
from backend.narration.contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID
from backend.narration.edition_service import (
    NarrationProductionPolicy,
    SqlAlchemyNarrationWorkflowService,
    StartNarrationWorkflow,
    orchestrate_narration_request,
    project_edition,
    project_edition_voice_identities,
    project_workflow,
)
from backend.narration.editions import advance_edition_segment_state
from backend.narration.jobs import EnqueueResult
from backend.narration.renders import render_job_input_hash
from backend.narration.services import (
    IdempotencyConflict,
    InvalidNarrationState,
    NarrationCasConflict,
    StaleNarrationInput,
)
from tests.narration.test_domain_services import (
    MemoryNarrationStore,
    _seed_render_assets,
)
from tests.narration.test_document_narration_state import (
    _chapter_with_current_edition,
)
from tests.narration.digest_fixtures import TEST_DIGEST_KEYRING
from tests.narration.test_script_analysis import _seed


NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
POLICY = NarrationProductionPolicy(
    tts_fingerprint="a" * 64,
    tokenizer_fingerprint="b" * 64,
    normalizer_fingerprint="c" * 64,
    postprocess_fingerprint="d" * 64,
    digest_keyring=TEST_DIGEST_KEYRING,
)


class MemoryRenderQueue:
    def __init__(self, store: MemoryNarrationStore, *, fail: bool = False) -> None:
        self.store = store
        self.fail = fail
        self.calls: list[dict[str, object]] = []

    def enqueue_segment_render(self, **values: object) -> EnqueueResult:
        self.calls.append(values)
        if self.fail:
            raise RuntimeError("injected queue failure")
        job = BackgroundJob(
            id=uuid4(),
            owner_id=LOCAL_OWNER_ID,
            workspace_id=LOCAL_WORKSPACE_ID,
            novel_id=values["novel_id"],
            request_id=values["request_id"],
            request_allows_render=True,
            job_kind="narration.segment_render",
            input_hash=render_job_input_hash(
                edition_segment_id=values["edition_segment_id"],
                render_fingerprint=values["render_fingerprint"],
            ),
            idempotency_key=f"memory-render-{uuid4()}",
            resource_class="moss-nano",
            base_priority=values["base_priority"],
            state="queued",
            max_attempts=values["max_attempts"],
            attempt_count=0,
            progress_current=0,
        )
        self.store.add(job)
        self.store.flush()
        return EnqueueResult(job_id=job.id, created=True)


def _workflow_seed(source: str = "林晚说道：\u201c你终于来了。\u201d"):
    store, novel, document, revision, _character, seed_request, _command = _seed(
        source,
        intent="create",
    )
    store.add(
        DocumentWorkingCopy(
            document_id=document.id,
            base_revision_id=revision.id,
            draft_version=7,
            content_markdown=revision.content_markdown,
            content_hash=revision.content_hash,
        )
    )
    command = StartNarrationWorkflow(
        document_id=document.id,
        intent="create",
        expected_draft_version=7,
        expected_content_hash=revision.content_hash,
        expected_settings_version=1,
        force_review=False,
        idempotency_key="production-create-0001",
        explicitly_requested=True,
        requested_at=NOW,
    )
    return store, novel, document, revision, seed_request, command


def test_generation_creates_one_approved_edition_and_fenced_render_candidates() -> None:
    store, _novel, _document, _revision, _seed_request, command = _workflow_seed()
    queue = MemoryRenderQueue(store)

    result = orchestrate_narration_request(store, queue, command, POLICY)

    request = store.get(NarrationRequest, result.request_id)
    assert request is not None
    # created→analyzing, request-owned review-pointer CAS, analysis completion,
    # and queued production are four distinct authoritative mutations.
    assert (result.workflow_state, result.request_version) == ("queued", 5)
    # T3 analysis completion is an intermediate milestone for generation; T4
    # must clear it when production resumes.
    assert request.completed_at is None
    editions = store.find_all(NarrationEdition, request_id=request.id)
    assert len(editions) == 1 and result.edition_id == editions[0].id
    segments = store.find_all(
        NarrationEditionSegment,
        edition_id=editions[0].id,
        order_by=("ordinal",),
    )
    assert segments
    assert all(segment.render_state == "queued" for segment in segments)
    assert all(
        segment.resolution_json.get("contract_version")
        == "narration-edition-resolution/2"
        for segment in segments
    )
    frozen_identities = project_edition_voice_identities(store, editions[0])
    assert frozen_identities
    assert all(not item.legacy_fallback for item in frozen_identities)
    assert all(item.display_name != "旧版未保存名称" for item in frozen_identities)
    assert len(queue.calls) == len(segments)
    assert len(store.find_all(BackgroundJob, request_id=request.id)) == len(segments)
    assert len(store.find_all(NarrationSegmentRender, request_id=request.id)) == len(segments)
    assert len(result.job_ids) == len(segments)
    assert store.rows[MediaAsset] == []


def test_legacy_edition_identity_uses_stable_ids_without_joining_mutable_name() -> None:
    store, _novel, _document, _revision, _seed_request, command = _workflow_seed()
    result = orchestrate_narration_request(store, MemoryRenderQueue(store), command, POLICY)
    edition = store.find_one(NarrationEdition, request_id=result.request_id)
    assert edition is not None
    segments = store.find_all(
        NarrationEditionSegment,
        edition_id=edition.id,
        order_by=("ordinal",),
    )
    for segment in segments:
        segment.resolution_json = {"contract_version": "narration-edition-resolution/1"}

    identities = project_edition_voice_identities(store, edition)

    assert identities
    assert all(item.legacy_fallback for item in identities)
    assert all(item.display_name == "旧版未保存名称" for item in identities)
    assert {item.voice_version_id for item in identities} == {
        segment.voice_version_id for segment in segments
    }


def test_projections_resolve_edition_state_by_edition_id_not_missing_id() -> None:
    store, _novel, _document, _revision, _seed_request, command = _workflow_seed()
    result = orchestrate_narration_request(
        store,
        MemoryRenderQueue(store),
        command,
        POLICY,
    )
    request = store.get(NarrationRequest, result.request_id)
    edition = store.find_one(NarrationEdition, request_id=result.request_id)
    assert request is not None and edition is not None
    state = NarrationEditionState(
        edition_id=edition.id,
        current_manifest_id=uuid4(),
        current_manifest_revision=7,
        version=1,
        updated_actor="projection-test",
    )
    store.add(state)

    class RejectEditionStateGet:
        def __init__(self, wrapped: object) -> None:
            self.wrapped = wrapped

        def __getattr__(self, name: str) -> object:
            return getattr(self.wrapped, name)

        def get(
            self,
            model: type[object],
            row_id: object,
            *,
            for_update: bool = False,
        ) -> object | None:
            if model is NarrationEditionState:
                raise AssertionError(
                    "NarrationEditionState has edition_id, not an id attribute"
                )
            return self.wrapped.get(  # type: ignore[attr-defined]
                model,
                row_id,
                for_update=for_update,
            )

    strict_store = RejectEditionStateGet(store)
    workflow = project_workflow(
        strict_store,  # type: ignore[arg-type]
        request,
        replayed=False,
    )
    edition_projection = project_edition(
        strict_store,  # type: ignore[arg-type]
        edition,
    )

    assert workflow.current_manifest_revision == state.current_manifest_revision
    assert (
        edition_projection.current_manifest_revision
        == state.current_manifest_revision
    )


def test_exact_replay_reuses_request_edition_jobs_and_renders() -> None:
    store, _novel, _document, _revision, _seed_request, command = _workflow_seed()
    queue = MemoryRenderQueue(store)
    first = orchestrate_narration_request(store, queue, command, POLICY)
    counts = tuple(
        len(store.rows[model])
        for model in (
            NarrationRequest,
            NarrationEdition,
            NarrationEditionSegment,
            BackgroundJob,
            NarrationSegmentRender,
        )
    )

    replay = orchestrate_narration_request(store, queue, command, POLICY)

    assert replay.request_id == first.request_id
    assert replay.edition_id == first.edition_id
    assert replay.job_ids == first.job_ids
    assert replay.replayed is True
    assert tuple(
        len(store.rows[model])
        for model in (
            NarrationRequest,
            NarrationEdition,
            NarrationEditionSegment,
            BackgroundJob,
            NarrationSegmentRender,
        )
    ) == counts
    assert len(queue.calls) == len(store.rows[NarrationEditionSegment])

    with pytest.raises(IdempotencyConflict):
        orchestrate_narration_request(
            store,
            queue,
            replace(command, expected_draft_version=8),
            POLICY,
        )
    with pytest.raises(IdempotencyConflict):
        orchestrate_narration_request(
            store,
            queue,
            replace(command, expected_settings_version=2),
            POLICY,
        )


def test_new_request_reuses_v2_ready_renders_and_finishes_without_jobs() -> None:
    store, novel, _document, _revision, _seed_request, command = _workflow_seed()
    queue = MemoryRenderQueue(store)
    first = orchestrate_narration_request(store, queue, command, POLICY)
    assert first.workflow_state == "queued"
    first_job_count = len(queue.calls)

    first_edition = store.get(NarrationEdition, first.edition_id)
    assert first_edition is not None
    first_segments = store.find_all(
        NarrationEditionSegment,
        edition_id=first_edition.id,
        order_by=("ordinal",),
    )
    first_renders = store.find_all(
        NarrationSegmentRender,
        request_id=first.request_id,
    )
    assert len(first_segments) == len(first_renders) == first_job_count
    for marker, (segment, render) in enumerate(
        zip(first_segments, first_renders, strict=True)
    ):
        render.state = "ready"
        render.duration_ms = 1200
        render.ready_at = NOW
        _seed_render_assets(store, novel=novel, render=render, marker=marker)
        advance_edition_segment_state(store, segment.id, new_state="ready")

    second = orchestrate_narration_request(
        store,
        queue,
        replace(command, idempotency_key="production-create-cache-only-0002"),
        POLICY,
    )

    assert second.request_id != first.request_id
    assert second.edition_id != first.edition_id
    assert second.workflow_state == "ready"
    assert second.job_ids == ()
    assert len(queue.calls) == first_job_count
    second_segments = store.find_all(
        NarrationEditionSegment,
        edition_id=second.edition_id,
        order_by=("ordinal",),
    )
    assert [row.render_fingerprint for row in second_segments] == [
        row.render_fingerprint for row in first_segments
    ]
    assert all(row.render_state == "ready" for row in second_segments)
    manifests = store.find_all(NarrationManifest, edition_id=second.edition_id)
    assert len(manifests) == 1 and manifests[0].status == "ready"


def test_analyze_only_creates_no_edition_job_render_or_media() -> None:
    store, _novel, _document, _revision, _seed_request, base = _workflow_seed(
        "林晚走进房间。"
    )
    queue = MemoryRenderQueue(store, fail=True)
    command = replace(
        base,
        intent="analyze_only",
        idempotency_key="production-analyze-0001",
    )

    result = orchestrate_narration_request(store, queue, command, POLICY)

    assert result.intent == "analyze_only"
    assert result.workflow_state == "analyzed"
    assert result.script_version_id is not None
    assert result.edition_id is None
    assert result.job_ids == ()
    assert queue.calls == []
    assert store.rows[NarrationEdition] == []
    assert store.rows[BackgroundJob] == []
    assert store.rows[NarrationSegmentRender] == []
    assert store.rows[MediaAsset] == []


def test_force_review_tightens_policy_and_stops_before_production() -> None:
    store, _novel, _document, _revision, _seed_request, base = _workflow_seed(
        "林晚走进房间。"
    )
    queue = MemoryRenderQueue(store, fail=True)

    result = orchestrate_narration_request(
        store,
        queue,
        replace(
            base,
            force_review=True,
            idempotency_key="production-force-review-0001",
        ),
        POLICY,
    )

    assert result.workflow_state == "review_required"
    assert result.blocker_count == 0
    assert result.edition_id is None and result.job_ids == ()
    assert queue.calls == []
    assert store.rows[NarrationEdition] == []
    assert store.rows[BackgroundJob] == []
    assert store.rows[NarrationSegmentRender] == []
    assert store.rows[MediaAsset] == []


def test_stale_working_copy_and_settings_barriers_fail_before_request_creation() -> None:
    store, _novel, _document, _revision, _seed_request, command = _workflow_seed()
    initial_request_count = len(store.rows[NarrationRequest])
    queue = MemoryRenderQueue(store)

    with pytest.raises(NarrationCasConflict):
        orchestrate_narration_request(
            store,
            queue,
            replace(command, expected_draft_version=6),
            POLICY,
        )
    with pytest.raises(StaleNarrationInput):
        orchestrate_narration_request(
            store,
            queue,
            replace(command, expected_content_hash="f" * 64),
            POLICY,
        )
    with pytest.raises(IdempotencyConflict):
        orchestrate_narration_request(
            store,
            queue,
            replace(command, expected_settings_version=2),
            POLICY,
        )
    assert len(store.rows[NarrationRequest]) == initial_request_count
    assert queue.calls == []


@contextmanager
def _memory_transaction(store: MemoryNarrationStore) -> Iterator[None]:
    """Model the rollback guarantee supplied by Session.begin in production."""

    snapshot = deepcopy(store.rows)
    try:
        yield
    except Exception:
        store.rows = defaultdict(list, snapshot)
        raise


def test_queue_failure_rolls_back_queued_request_edition_and_render_candidates() -> None:
    store, _novel, _document, _revision, _seed_request, command = _workflow_seed()
    queue = MemoryRenderQueue(store, fail=True)

    with pytest.raises(RuntimeError, match="injected queue failure"):
        with _memory_transaction(store):
            orchestrate_narration_request(store, queue, command, POLICY)

    assert all(request.state != "queued" for request in store.rows[NarrationRequest])
    assert store.rows[NarrationEdition] == []
    assert store.rows[BackgroundJob] == []
    assert store.rows[NarrationSegmentRender] == []
    assert store.rows[MediaAsset] == []


def test_update_requires_an_explicit_author_action_before_any_production_write() -> None:
    store, _novel, _document, _revision, _seed_request, base = _workflow_seed()
    queue = MemoryRenderQueue(store)
    initial_counts = {
        model: len(store.rows[model])
        for model in (
            NarrationRequest,
            NarrationEdition,
            NarrationEditionSegment,
            BackgroundJob,
            NarrationSegmentRender,
            MediaAsset,
        )
    }

    with pytest.raises(
        InvalidNarrationState,
        match="narration workflow requires an explicit author action",
    ):
        orchestrate_narration_request(
            store,
            queue,
            replace(
                base,
                intent="update",
                explicitly_requested=False,
                idempotency_key="production-update-not-explicit-0001",
            ),
            POLICY,
        )

    assert queue.calls == []
    assert {
        model: len(store.rows[model])
        for model in initial_counts
    } == initial_counts


def test_explicit_update_locks_saved_copy_and_current_pointer_until_orchestration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, foundation, edition, _renders, _rows, working, pointer = (
        _chapter_with_current_edition()
    )
    find_one = store.find_one
    reads: list[tuple[type[object], bool, dict[str, object]]] = []

    def recording_find_one(
        model: type[object],
        *,
        for_update: bool = False,
        **filters: object,
    ) -> object | None:
        reads.append((model, for_update, filters))
        return find_one(model, for_update=for_update, **filters)

    monkeypatch.setattr(store, "find_one", recording_find_one)

    intent = document_state.create_explicit_narration_update_intent(
        store,
        document_id=foundation[1].id,
        expected_draft_version=working.draft_version,
        expected_content_hash=working.content_hash,
        expected_settings_version=1,
        force_review=False,
        idempotency_key="production-update-locks-0001",
        explicitly_requested=True,
    )

    assert intent.prior_current_edition_id == edition.id
    assert intent.expected_pointer_version == pointer.version
    assert [
        (model, for_update, filters)
        for model, for_update, filters in reads
        if model in {DocumentWorkingCopy, DocumentNarrationState}
    ] == [
        (DocumentWorkingCopy, True, {"document_id": foundation[1].id}),
        (
            DocumentNarrationState,
            True,
            {
                "owner_id": pointer.owner_id,
                "workspace_id": pointer.workspace_id,
                "document_id": foundation[1].id,
            },
        ),
    ]


def test_update_intent_and_orchestration_share_one_caller_owned_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _store, _novel, document, revision, _seed_request, base = _workflow_seed()
    command = replace(
        base,
        document_id=document.id,
        intent="update",
        expected_content_hash=revision.content_hash,
        idempotency_key="production-update-explicit-0001",
        explicitly_requested=True,
    )
    sentinel = object()
    calls: list[tuple[str, object, bool]] = []
    intent_values: dict[str, object] = {}

    with Session() as session:
        service = SqlAlchemyNarrationWorkflowService(session, POLICY)

        def fake_update_intent(_store: object, **values: object) -> object:
            transaction = session.get_transaction()
            assert transaction is not None
            calls.append(("intent", transaction, session.in_transaction()))
            intent_values.update(values)
            return object()

        def fake_orchestrate(
            store: object,
            queue: object,
            actual_command: StartNarrationWorkflow,
            policy: NarrationProductionPolicy,
        ) -> object:
            transaction = session.get_transaction()
            assert transaction is not None
            assert store is service.store
            assert queue is service.queue
            assert actual_command is command
            assert policy is POLICY
            calls.append(("orchestrate", transaction, session.in_transaction()))
            return sentinel

        monkeypatch.setattr(
            document_state,
            "create_explicit_narration_update_intent",
            fake_update_intent,
        )
        monkeypatch.setattr(
            edition_service_module,
            "orchestrate_narration_request",
            fake_orchestrate,
        )

        assert service.start(command) is sentinel
        assert session.in_transaction() is False

    assert [name for name, _transaction, _active in calls] == [
        "intent",
        "orchestrate",
    ]
    assert calls[0][1] is calls[1][1]
    assert all(active for _name, _transaction, active in calls)
    assert intent_values == {
        "document_id": command.document_id,
        "expected_draft_version": command.expected_draft_version,
        "expected_content_hash": command.expected_content_hash,
        "expected_settings_version": command.expected_settings_version,
        "force_review": command.force_review,
        "idempotency_key": command.idempotency_key,
        "explicitly_requested": True,
        "scope": command.scope,
    }
