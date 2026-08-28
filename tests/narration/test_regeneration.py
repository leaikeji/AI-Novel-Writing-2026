from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from backend.models import (
    BackgroundJob,
    Document,
    DocumentNarrationState,
    DocumentRevision,
    DocumentWorkingCopy,
    NarrationEdition,
    NarrationEditionSegment,
    NarrationManifest,
    NarrationRequest,
    NarrationSegmentRender,
    VoiceRightsEvent,
)
from backend.narration.manifest import (
    INITIAL_BUFFER_POLICY,
    ManifestSegmentInput,
    PublishManifest,
    publish_manifest,
)
from backend.narration.progress import (
    SavePlaybackProgress,
    restore_playback_progress,
    save_playback_progress,
    switch_document_edition,
)
from backend.narration.regeneration import (
    finalize_ready_cache_only_edition,
    project_document_edition_history,
    project_failed_segment_retry_eligibility,
    project_local_regeneration,
)
from backend.narration.services import (
    InvalidNarrationState,
    NarrationCasConflict,
    NarrationScopeMismatch,
)
from tests.narration.test_domain_services import (
    MemoryNarrationStore,
    _edition_with_ready_renders,
)
from tests.narration.digest_fixtures import TEST_DIGEST_KEYRING


NOW = datetime(2026, 8, 27, 16, 0, tzinfo=UTC)


class _CacheLockTrackingStore(MemoryNarrationStore):
    def __init__(self) -> None:
        super().__init__()
        self.cache_lock_order: list[type[object]] = []

    def get(
        self,
        model: type[object],
        row_id: object,
        *,
        for_update: bool = False,
    ) -> object | None:
        if for_update and model in {NarrationRequest, Document, NarrationEdition}:
            self.cache_lock_order.append(model)
        return super().get(model, row_id, for_update=for_update)


def _ready_foundation(store: MemoryNarrationStore | None = None):
    target_store = store or MemoryNarrationStore()
    foundation = _edition_with_ready_renders(target_store)
    edition = foundation[4]
    renders = foundation[6]
    rows = target_store.find_all(
        NarrationEditionSegment, edition_id=edition.id, order_by=("ordinal",)
    )
    return target_store, foundation, edition, renders, rows


def _add_matching_working_copy(
    store: MemoryNarrationStore,
    document: Document,
    revision: DocumentRevision,
) -> DocumentWorkingCopy:
    working = DocumentWorkingCopy(
        document_id=document.id,
        base_revision_id=revision.id,
        draft_version=1,
        content_markdown=revision.content_markdown,
        content_hash=revision.content_hash,
    )
    store.add(working)
    return working


def _make_cache_only(
    store: MemoryNarrationStore,
    request: NarrationRequest,
) -> None:
    historical_request_id = uuid4()
    for render in store.rows[NarrationSegmentRender]:
        render.request_id = historical_request_id
    for job in store.rows[BackgroundJob]:
        job.request_id = historical_request_id


def _finalize_cache_only(
    store: MemoryNarrationStore,
    *,
    request: NarrationRequest,
    edition: NarrationEdition,
):
    return finalize_ready_cache_only_edition(
        store,
        edition_id=edition.id,
        request_id=request.id,
        expected_request_version=request.version,
        expected_manifest_revision=0,
        expected_manifest_state_version=0,
        actor="cache-finalizer",
        digest_keyring=TEST_DIGEST_KEYRING,
    )


def _publish_ready(
    store: MemoryNarrationStore,
    edition: NarrationEdition,
    renders: list[NarrationSegmentRender],
    *,
    revision: int = 0,
    state_version: int = 0,
):
    rows = store.find_all(
        NarrationEditionSegment, edition_id=edition.id, order_by=("ordinal",)
    )
    return publish_manifest(
        store,
        PublishManifest(
            edition_id=edition.id,
            expected_current_revision=revision,
            expected_state_version=state_version,
            buffer_policy=INITIAL_BUFFER_POLICY,
            segments=tuple(
                ManifestSegmentInput(row.id, "ready", renders[index].id)
                for index, row in enumerate(rows)
            ),
            updated_actor="test-worker",
        ),
    )


def _clone_projection_target(
    store: MemoryNarrationStore,
    source: NarrationEdition,
    source_rows: list[NarrationEditionSegment],
) -> tuple[NarrationEdition, list[NarrationEditionSegment]]:
    target = NarrationEdition(
        id=uuid4(),
        owner_id=source.owner_id,
        workspace_id=source.workspace_id,
        novel_id=source.novel_id,
        document_id=source.document_id,
        request_id=source.request_id,
        request_allows_edition=True,
        script_version_id=source.script_version_id,
        script_is_approved=True,
        settings_snapshot_id=source.settings_snapshot_id,
        pronunciation_profile_id=source.pronunciation_profile_id,
        tts_fingerprint=source.tts_fingerprint,
        tokenizer_fingerprint=source.tokenizer_fingerprint,
        normalizer_fingerprint=source.normalizer_fingerprint,
        postprocess_fingerprint=source.postprocess_fingerprint,
        context_mode="independent_segment",
        buffer_policy_version=source.buffer_policy_version,
        edition_fingerprint="e" * 64,
        state="created",
        created_actor="test-projection",
        created_at=NOW,
    )
    store.add(target)
    rows: list[NarrationEditionSegment] = []
    for source_row in source_rows:
        row = NarrationEditionSegment(
            id=uuid4(),
            edition_id=target.id,
            script_version_id=source.script_version_id,
            segment_id=source_row.segment_id,
            ordinal=source_row.ordinal,
            slot_id=source_row.slot_id,
            profile_id=source_row.profile_id,
            voice_version_id=source_row.voice_version_id,
            resolution_json=dict(source_row.resolution_json),
            render_fingerprint=source_row.render_fingerprint,
            render_state="ready",
            gap_after_ms=source_row.gap_after_ms,
        )
        store.add(row)
        rows.append(row)
    return target, rows


def test_exact_fingerprint_projection_reuses_only_authoritative_ready_renders() -> None:
    store, _foundation, prior, _renders, prior_rows = _ready_foundation()
    target, target_rows = _clone_projection_target(store, prior, prior_rows)

    exact = project_local_regeneration(
        store, prior_edition_id=prior.id, target_edition_id=target.id
    )

    assert exact.ready_cache_reuse_count == len(target_rows)
    assert exact.render_required_count == 0
    assert exact.invalidated_prior_segment_ids == ()
    assert all(item.invalidation_reason is None for item in exact.segments)

    target_rows[-1].render_fingerprint = "f" * 64
    target_rows[-1].render_state = "pending"
    changed = project_local_regeneration(
        store, prior_edition_id=prior.id, target_edition_id=target.id
    )

    assert changed.ready_cache_reuse_count == len(target_rows) - 1
    assert changed.render_required_count == 1
    assert changed.segments[-1].invalidation_reason == "render_fingerprint_changed"
    assert changed.invalidated_prior_segment_ids == (prior_rows[-1].id,)
    # Projection never invalidates or rewrites immutable historical rows.
    assert all(row.render_state == "ready" for row in prior_rows)


def test_similar_inputs_with_changed_fingerprint_are_never_claimed_as_reused() -> None:
    store, _foundation, prior, _renders, prior_rows = _ready_foundation()
    target, target_rows = _clone_projection_target(store, prior, prior_rows)
    # A new ScriptVersion currently derives new segment IDs and therefore new
    # full render fingerprints even when text/voice/model inputs are similar.
    target_rows[0].render_fingerprint = "9" * 64
    target_rows[0].render_state = "pending"

    result = project_local_regeneration(
        store, prior_edition_id=prior.id, target_edition_id=target.id
    )

    assert result.segments[0].prior_edition_segment_id is None
    assert result.segments[0].reuse_state == "render_required"
    assert result.ready_cache_reuse_count == len(target_rows) - 1


def test_cache_only_zero_job_path_publishes_and_closes_request_idempotently() -> None:
    tracking = _CacheLockTrackingStore()
    store, foundation, edition, _renders, rows = _ready_foundation(tracking)
    _novel, document, revision = foundation[:3]
    request = foundation[3]
    assert isinstance(document, Document)
    assert isinstance(revision, DocumentRevision)
    assert isinstance(request, NarrationRequest)
    _add_matching_working_copy(store, document, revision)
    expected_request_version = request.version
    # Model a historical cache origin: ready renders retain their immutable
    # source jobs, but this new generation request owns no jobs.
    _make_cache_only(store, request)
    tracking.cache_lock_order.clear()

    result = finalize_ready_cache_only_edition(
        store,
        edition_id=edition.id,
        request_id=request.id,
        expected_request_version=expected_request_version,
        expected_manifest_revision=0,
        expected_manifest_state_version=0,
        actor="cache-finalizer",
        digest_keyring=TEST_DIGEST_KEYRING,
    )

    assert result.job_count == 0
    assert result.ready_segment_count == len(rows)
    assert result.request_version == expected_request_version + 2
    assert result.manifest_revision == 1
    assert result.replayed is False
    assert request.state == "ready" and edition.state == "ready"
    assert len(store.rows[NarrationManifest]) == 1
    pointer = store.find_one(
        DocumentNarrationState,
        document_id=document.id,
    )
    assert pointer is not None
    assert pointer.current_edition_id == edition.id
    assert pointer.version == 1
    assert tracking.cache_lock_order[:3] == [
        NarrationRequest,
        Document,
        NarrationEdition,
    ]

    replay = finalize_ready_cache_only_edition(
        store,
        edition_id=edition.id,
        request_id=request.id,
        expected_request_version=expected_request_version,
        expected_manifest_revision=0,
        expected_manifest_state_version=0,
        actor="cache-finalizer",
        digest_keyring=TEST_DIGEST_KEYRING,
    )
    assert replay.manifest_id == result.manifest_id
    assert replay.replayed is True
    assert len(store.rows[NarrationManifest]) == 1
    assert pointer.current_edition_id == edition.id
    assert pointer.version == 1


def test_cache_only_initial_pointer_never_replaces_an_existing_pointer() -> None:
    store, foundation, edition, _renders, _rows = _ready_foundation()
    _novel, document, revision, request = foundation[:4]
    assert isinstance(document, Document)
    assert isinstance(revision, DocumentRevision)
    assert isinstance(request, NarrationRequest)
    _add_matching_working_copy(store, document, revision)
    _make_cache_only(store, request)
    current_edition_id = uuid4()
    current = DocumentNarrationState(
        id=uuid4(),
        owner_id=request.owner_id,
        workspace_id=request.workspace_id,
        document_id=document.id,
        script_id=None,
        current_script_version_id=None,
        current_edition_id=current_edition_id,
        version=5,
        switched_actor="owner",
        switched_at=NOW,
    )
    store.add(current)

    result = _finalize_cache_only(store, request=request, edition=edition)

    assert result.replayed is False
    assert current.current_edition_id == current_edition_id
    assert current.version == 5


def test_cache_only_working_copy_divergence_does_not_install_pointer() -> None:
    store, foundation, edition, _renders, _rows = _ready_foundation()
    _novel, document, revision, request = foundation[:4]
    assert isinstance(document, Document)
    assert isinstance(revision, DocumentRevision)
    assert isinstance(request, NarrationRequest)
    working = _add_matching_working_copy(store, document, revision)
    working.content_hash = "f" * 64
    working.draft_version += 1
    _make_cache_only(store, request)

    result = _finalize_cache_only(store, request=request, edition=edition)

    assert result.replayed is False
    assert store.find_one(
        DocumentNarrationState,
        document_id=document.id,
    ) is None


def test_cache_only_replay_does_not_install_pointer_after_original_divergence() -> None:
    store, foundation, edition, _renders, _rows = _ready_foundation()
    _novel, document, revision, request = foundation[:4]
    assert isinstance(document, Document)
    assert isinstance(revision, DocumentRevision)
    assert isinstance(request, NarrationRequest)
    working = _add_matching_working_copy(store, document, revision)
    working.content_hash = "f" * 64
    working.draft_version += 1
    _make_cache_only(store, request)
    expected_request_version = request.version

    first = finalize_ready_cache_only_edition(
        store,
        edition_id=edition.id,
        request_id=request.id,
        expected_request_version=expected_request_version,
        expected_manifest_revision=0,
        expected_manifest_state_version=0,
        actor="cache-finalizer",
        digest_keyring=TEST_DIGEST_KEYRING,
    )
    assert first.replayed is False
    assert store.find_one(
        DocumentNarrationState,
        document_id=document.id,
    ) is None

    # Exact replay is observationally idempotent.  It cannot install a pointer
    # merely because the working copy later returns to the source hash.
    working.content_hash = revision.content_hash
    replay = finalize_ready_cache_only_edition(
        store,
        edition_id=edition.id,
        request_id=request.id,
        expected_request_version=expected_request_version,
        expected_manifest_revision=0,
        expected_manifest_state_version=0,
        actor="cache-finalizer",
        digest_keyring=TEST_DIGEST_KEYRING,
    )

    assert replay.replayed is True
    assert replay.manifest_id == first.manifest_id
    assert store.find_one(
        DocumentNarrationState,
        document_id=document.id,
    ) is None


def test_cache_only_update_finishes_without_installing_initial_pointer() -> None:
    store, foundation, edition, _renders, _rows = _ready_foundation()
    _novel, document, revision, request = foundation[:4]
    assert isinstance(document, Document)
    assert isinstance(revision, DocumentRevision)
    assert isinstance(request, NarrationRequest)
    _add_matching_working_copy(store, document, revision)
    request.intent = "update"
    _make_cache_only(store, request)

    result = _finalize_cache_only(store, request=request, edition=edition)

    assert result.replayed is False
    assert store.find_one(
        DocumentNarrationState,
        document_id=document.id,
    ) is None


@pytest.mark.parametrize("intent", ["batch", "analyze_only"])
def test_cache_only_rejects_non_document_generation_intents_without_pointer(
    intent: str,
) -> None:
    store, foundation, edition, _renders, _rows = _ready_foundation()
    _novel, document, revision, request = foundation[:4]
    assert isinstance(document, Document)
    assert isinstance(revision, DocumentRevision)
    assert isinstance(request, NarrationRequest)
    _add_matching_working_copy(store, document, revision)
    request.intent = intent
    request.document_id = None
    _make_cache_only(store, request)

    with pytest.raises(NarrationScopeMismatch):
        _finalize_cache_only(store, request=request, edition=edition)
    assert store.find_one(
        DocumentNarrationState,
        document_id=document.id,
    ) is None


def test_cache_only_finalization_rejects_jobs_partial_cache_and_stale_cas() -> None:
    store, foundation, edition, _renders, rows = _ready_foundation()
    _novel, document, revision = foundation[:3]
    request = foundation[3]
    assert isinstance(document, Document)
    assert isinstance(revision, DocumentRevision)
    assert isinstance(request, NarrationRequest)
    _add_matching_working_copy(store, document, revision)
    with pytest.raises(InvalidNarrationState, match="job_ids=0"):
        finalize_ready_cache_only_edition(
            store,
            edition_id=edition.id,
            request_id=request.id,
            expected_request_version=request.version,
            expected_manifest_revision=0,
            expected_manifest_state_version=0,
            actor="cache-finalizer",
            digest_keyring=TEST_DIGEST_KEYRING,
        )
    assert store.find_one(
        DocumentNarrationState,
        document_id=document.id,
    ) is None
    _make_cache_only(store, request)
    rows[0].render_state = "pending"
    with pytest.raises(InvalidNarrationState, match="every segment ready"):
        finalize_ready_cache_only_edition(
            store,
            edition_id=edition.id,
            request_id=request.id,
            expected_request_version=request.version,
            expected_manifest_revision=0,
            expected_manifest_state_version=0,
            actor="cache-finalizer",
            digest_keyring=TEST_DIGEST_KEYRING,
        )
    assert store.find_one(
        DocumentNarrationState,
        document_id=document.id,
    ) is None
    rows[0].render_state = "ready"
    with pytest.raises(NarrationCasConflict):
        finalize_ready_cache_only_edition(
            store,
            edition_id=edition.id,
            request_id=request.id,
            expected_request_version=request.version + 1,
            expected_manifest_revision=0,
            expected_manifest_state_version=0,
            actor="cache-finalizer",
            digest_keyring=TEST_DIGEST_KEYRING,
        )
    assert store.find_one(
        DocumentNarrationState,
        document_id=document.id,
    ) is None


def test_progress_restores_exact_segment_on_new_manifest_revision_only() -> None:
    store, _foundation, edition, renders, rows = _ready_foundation()
    first = _publish_ready(store, edition, renders)
    saved = save_playback_progress(
        store,
        SavePlaybackProgress(
            profile_id="default",
            edition_id=edition.id,
            manifest_revision=first.manifest_revision,
            edition_segment_id=rows[0].id,
            offset_ms=500,
            last_legal_start_ordinal=0,
            playback_rate_millis=1250,
            expected_updated_at=None,
        ),
    )
    second = _publish_ready(
        store, edition, renders, revision=1, state_version=1
    )

    restored = restore_playback_progress(
        store, profile_id="default", edition_id=edition.id
    )

    assert restored is not None
    assert restored.manifest_revision == second.manifest_revision == 2
    assert restored.manifest_advanced is True
    assert restored.segment_id == rows[0].segment_id
    assert restored.offset_ms == 500
    assert saved.manifest_revision == 1  # read recovery never rewrites progress

    second.canonical_json["segments"][0]["render_status"] = "failed"
    with pytest.raises(InvalidNarrationState, match="not ready"):
        restore_playback_progress(
            store, profile_id="default", edition_id=edition.id
        )


def test_history_projection_is_read_only_and_fences_rights_and_working_copy() -> None:
    store, foundation, edition, renders, _rows = _ready_foundation()
    novel, document, revision = foundation[:3]
    edition.created_at = NOW
    _publish_ready(store, edition, renders)
    store.add(
        DocumentWorkingCopy(
            document_id=document.id,
            base_revision_id=revision.id,
            draft_version=4,
            content_markdown=revision.content_markdown,
            content_hash=revision.content_hash,
            updated_at=NOW,
        )
    )
    pointer = switch_document_edition(
        store,
        document_id=document.id,
        edition_id=edition.id,
        expected_version=0,
        actor="owner",
    )

    history = project_document_edition_history(
        store, document_id=document.id, profile_id="default"
    )

    assert history.pointer_version == pointer.version == 1
    assert history.current_edition_id == edition.id
    assert len(history.editions) == 1
    item = history.editions[0]
    assert item.source_status == "current"
    assert item.playable and item.switch_allowed and item.rights_available
    assert item.ready_segment_count == item.total_segment_count

    working = store.find_one(DocumentWorkingCopy, document_id=document.id)
    assert working is not None
    working.content_hash = "b" * 64
    assert project_document_edition_history(
        store, document_id=document.id
    ).editions[0].source_status == "working_copy_diverged"

    rights = foundation[8]
    store.add(
        VoiceRightsEvent(
            id=uuid4(),
            rights_record_id=rights.id,
            event_key="revoke-history",
            event_type="revoked",
            actor="owner",
            occurred_at=NOW,
        )
    )
    blocked = project_document_edition_history(
        store, document_id=document.id
    ).editions[0]
    assert blocked.rights_available is False
    assert blocked.playable is False and blocked.switch_allowed is False
    assert edition.state == "ready"  # rights projection does not rewrite history
    assert novel.id == edition.novel_id


def test_failed_segment_retry_only_projects_existing_manual_retry_eligibility() -> None:
    store, foundation, edition, renders, rows = _ready_foundation()
    row = rows[0]
    render = renders[0]
    job = store.get(BackgroundJob, render.source_job_id)
    assert job is not None
    row.render_state = "failed"
    row.failure_code = "NANO_AUDIO_INVALID"
    render.state = "failed"
    job.state = "failed"
    request = foundation[3]
    request.state = "partial_ready"
    edition.state = "partial_ready"

    projection = project_failed_segment_retry_eligibility(
        store, edition_id=edition.id, edition_segment_id=row.id
    )

    assert projection.job_id == job.id
    assert projection.existing_job_manual_retry_authorizable is True
    assert projection.execution_supported is True
    assert projection.hold_reason is None
    assert projection.fanout_segment_ids == (row.segment_id,)
    assert row.render_state == "failed" and render.state == "failed"
    assert job.state == "failed"  # no implicit manual_retry command or reset

    request.intent = "batch"
    with pytest.raises(InvalidNarrationState, match="outside the T4 local path"):
        project_failed_segment_retry_eligibility(
            store, edition_id=edition.id, edition_segment_id=row.id
        )


def test_failed_segment_retry_compatibility_render_lookup_never_crosses_scope() -> None:
    store, foundation, edition, renders, rows = _ready_foundation()
    row = rows[0]
    render = renders[0]
    job = store.get(BackgroundJob, render.source_job_id)
    assert job is not None
    row.render_state = "failed"
    row.failure_code = "NANO_AUDIO_INVALID"
    render.state = "failed"
    job.state = "failed"
    request = foundation[3]
    request.state = "partial_ready"
    edition.state = "partial_ready"
    foreign = NarrationSegmentRender(
        id=uuid4(),
        owner_id=uuid4(),
        workspace_id=uuid4(),
        novel_id=render.novel_id,
        request_id=render.request_id,
        request_allows_render=True,
        render_fingerprint=render.render_fingerprint,
        canonical_input_json=dict(render.canonical_input_json),
        voice_version_id=render.voice_version_id,
        model_fingerprint=render.model_fingerprint,
        postprocess_fingerprint=render.postprocess_fingerprint,
        state="failed",
        source_job_id=render.source_job_id,
        audio_validation_json={},
    )
    store.rows[NarrationSegmentRender].insert(0, foreign)

    projection = project_failed_segment_retry_eligibility(
        store,
        edition_id=edition.id,
        edition_segment_id=row.id,
    )

    assert projection.render_id == render.id
    assert projection.render_id != foreign.id


def test_regeneration_module_does_not_own_media_or_job_execution() -> None:
    # Architectural guard: this work package projects/reuses authoritative
    # rows but does not create assets, call manual_retry, or add an endpoint.
    from backend.narration import regeneration

    source = open(regeneration.__file__, encoding="utf-8").read()
    assert "manual_retry(" not in source
    assert "MediaAsset(" not in source
    assert "APIRouter(" not in source
