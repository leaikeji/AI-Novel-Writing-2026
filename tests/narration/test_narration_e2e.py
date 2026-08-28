from __future__ import annotations

import json
from dataclasses import replace

import pytest

from backend.models import (
    BackgroundJob,
    DocumentWorkingCopy,
    NarrationEdition,
    NarrationEditionSegment,
    NarrationManifest,
    NarrationRequest,
    NarrationScriptVersion,
    NarrationSegmentRender,
)
from backend.narration.edition_service import orchestrate_narration_request
from backend.narration.editions import advance_edition_segment_state
from backend.narration.manifest import load_public_manifest
from backend.narration.renders import render_job_input_hash
from backend.narration.services import InvalidNarrationState
from tests.narration.test_domain_services import _seed_render_assets
from tests.narration.test_edition_service import (
    NOW,
    POLICY,
    MemoryRenderQueue,
    _workflow_seed,
)


def _working_copy_snapshot(store, document_id):
    row = store.find_one(DocumentWorkingCopy, document_id=document_id)
    assert row is not None
    return (
        row.base_revision_id,
        row.draft_version,
        row.content_markdown,
        row.content_hash,
    )


def test_zero_blocker_explicit_request_auto_freezes_and_queues_one_edition() -> None:
    store, _novel, document, _revision, _seed_request, command = _workflow_seed(
        "林晚说道：“你终于来了。”"
    )
    before = _working_copy_snapshot(store, document.id)
    queue = MemoryRenderQueue(store)

    result = orchestrate_narration_request(store, queue, command, POLICY)

    request = store.get(NarrationRequest, result.request_id)
    script = store.get(NarrationScriptVersion, result.script_version_id)
    assert request is not None and script is not None
    assert result.workflow_state == "queued"
    assert result.blocker_count == 0
    assert result.edition_id is not None
    assert request.explicit_generation_intent_at == NOW
    assert request.explicit_generation_actor == command.actor
    assert script.state == "approved"
    assert script.approval_kind == "auto_no_blockers"
    assert len(store.find_all(NarrationEdition, request_id=result.request_id)) == 1
    segments = store.find_all(
        NarrationEditionSegment,
        edition_id=result.edition_id,
        order_by=("ordinal",),
    )
    assert segments
    assert len(queue.calls) == len(segments) == len(result.job_ids)
    assert all(segment.render_state == "queued" for segment in segments)
    assert _working_copy_snapshot(store, document.id) == before


def test_duplicate_canonical_segments_share_request_owned_jobs_and_renders() -> None:
    store, _novel, _document, _revision, _seed_request, command = _workflow_seed(
        "林晚说道：“别怕。”\n林晚说道：“别怕。”"
    )
    queue = MemoryRenderQueue(store)

    result = orchestrate_narration_request(store, queue, command, POLICY)

    segments = store.find_all(
        NarrationEditionSegment,
        edition_id=result.edition_id,
        order_by=("ordinal",),
    )
    renders = store.find_all(
        NarrationSegmentRender,
        request_id=result.request_id,
    )
    jobs = store.find_all(BackgroundJob, request_id=result.request_id)
    fingerprints = {segment.render_fingerprint for segment in segments}
    assert len(segments) == 4
    assert len(fingerprints) == len(renders) == len(jobs) == 2
    assert len(queue.calls) == len(result.job_ids) == 2
    assert all(segment.render_state == "queued" for segment in segments)
    for render in renders:
        source_job = store.get(BackgroundJob, render.source_job_id)
        assert source_job is not None
        matching_segments = [
            segment
            for segment in segments
            if segment.render_fingerprint == render.render_fingerprint
        ]
        assert len(matching_segments) == 2
        assert source_job.input_hash in {
            render_job_input_hash(
                edition_segment_id=segment.id,
                render_fingerprint=segment.render_fingerprint,
            )
            for segment in matching_segments
        }


def test_duplicate_in_flight_render_still_cannot_cross_request_fence() -> None:
    source = "林晚说道：“别怕。”\n林晚说道：“别怕。”"
    store, _novel, _document, _revision, _seed_request, command = (
        _workflow_seed(source)
    )
    queue = MemoryRenderQueue(store)
    first = orchestrate_narration_request(store, queue, command, POLICY)
    first_job_ids = first.job_ids

    with pytest.raises(
        InvalidNarrationState,
        match="cross-request in-flight render reuse",
    ):
        orchestrate_narration_request(
            store,
            queue,
            replace(
                command,
                idempotency_key="duplicate-cross-request-0002",
            ),
            POLICY,
        )

    assert first.job_ids == first_job_ids
    assert len(queue.calls) == 2


def test_blockers_only_pauses_unknown_speaker_without_production_or_body_write() -> None:
    store, _novel, document, _revision, _seed_request, command = _workflow_seed(
        "“没有任何说话提示。”"
    )
    before = _working_copy_snapshot(store, document.id)
    queue = MemoryRenderQueue(store, fail=True)

    result = orchestrate_narration_request(store, queue, command, POLICY)

    assert result.workflow_state == "review_required"
    assert result.blocker_count >= 3
    assert result.edition_id is None
    assert result.job_ids == ()
    assert queue.calls == []
    assert store.find_all(NarrationEdition, request_id=result.request_id) == []
    assert store.find_all(BackgroundJob, request_id=result.request_id) == []
    assert store.find_all(NarrationSegmentRender, request_id=result.request_id) == []
    assert _working_copy_snapshot(store, document.id) == before


def test_ready_cache_recovery_finishes_a_new_edition_with_one_private_safe_manifest() -> None:
    store, novel, document, _revision, _seed_request, command = _workflow_seed(
        "林晚说道：“缓存恢复也不能泄露台词。”"
    )
    before = _working_copy_snapshot(store, document.id)
    queue = MemoryRenderQueue(store)
    first = orchestrate_narration_request(store, queue, command, POLICY)
    first_queue_count = len(queue.calls)
    first_segments = store.find_all(
        NarrationEditionSegment,
        edition_id=first.edition_id,
        order_by=("ordinal",),
    )
    first_renders = store.find_all(
        NarrationSegmentRender,
        request_id=first.request_id,
    )
    assert len(first_segments) == len(first_renders) == first_queue_count
    render_by_fingerprint = {
        render.render_fingerprint: render for render in first_renders
    }
    assert len(render_by_fingerprint) == len(first_renders)
    for marker, segment in enumerate(first_segments):
        render = render_by_fingerprint[segment.render_fingerprint]
        render.state = "ready"
        render.duration_ms = 1_200
        render.ready_at = NOW
        _seed_render_assets(store, novel=novel, render=render, marker=marker)
        advance_edition_segment_state(store, segment.id, new_state="ready")

    cache_command = replace(
        command,
        idempotency_key="production-create-cache-recovery-0002",
    )
    recovered = orchestrate_narration_request(store, queue, cache_command, POLICY)

    assert recovered.workflow_state == "ready"
    assert recovered.edition_id != first.edition_id
    assert recovered.job_ids == ()
    assert len(queue.calls) == first_queue_count
    recovered_segments = store.find_all(
        NarrationEditionSegment,
        edition_id=recovered.edition_id,
        order_by=("ordinal",),
    )
    assert [row.render_fingerprint for row in recovered_segments] == [
        row.render_fingerprint for row in first_segments
    ]
    assert all(row.render_state == "ready" for row in recovered_segments)

    manifests = store.find_all(NarrationManifest, edition_id=recovered.edition_id)
    assert len(manifests) == 1
    public = load_public_manifest(store, edition_id=recovered.edition_id)
    assert public.manifest_revision == recovered.current_manifest_revision == 1
    assert public.payload["source_sha256"] == command.expected_content_hash
    wire = json.dumps(public.payload, ensure_ascii=False, sort_keys=True)
    for forbidden in (
        "缓存恢复也不能泄露台词",
        "source_text",
        "spoken_text",
        "text_sha256",
        "text_hmac",
        "voice_version_id",
        "profile_id",
        "resolution_json",
    ):
        assert forbidden not in wire
    assert all(
        render.canonical_input_json["schema_version"] == "narration-render-input/3"
        and "canonical_spoken_text_hash" not in render.canonical_input_json
        and "canonical_spoken_text_hmac_sha256" in render.canonical_input_json
        for render in first_renders
    )

    counts = (
        len(store.find_all(NarrationRequest)),
        len(store.find_all(NarrationEdition)),
        len(store.find_all(NarrationManifest)),
        len(store.find_all(BackgroundJob)),
    )
    replay = orchestrate_narration_request(store, queue, cache_command, POLICY)
    assert replay.replayed is True
    assert replay.edition_id == recovered.edition_id
    assert replay.current_manifest_revision == 1
    assert (
        len(store.find_all(NarrationRequest)),
        len(store.find_all(NarrationEdition)),
        len(store.find_all(NarrationManifest)),
        len(store.find_all(BackgroundJob)),
    ) == counts
    assert _working_copy_snapshot(store, document.id) == before
