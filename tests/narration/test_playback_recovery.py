from __future__ import annotations

from uuid import uuid4

import pytest

from backend.models import NarrationEditionSegment, NarrationPlaybackProgress
from backend.narration.manifest import (
    INITIAL_BUFFER_POLICY,
    ManifestSegmentInput,
    PrepareRangeCommand,
    PublishManifest,
    prepare_manifest_range,
    publish_manifest,
)
from backend.narration.progress import (
    SavePlaybackProgress,
    restore_playback_progress,
    save_playback_progress,
)
from backend.narration.services import InvalidNarrationState, NarrationCasConflict
from tests.narration.test_domain_services import (
    MemoryNarrationStore,
    _edition_with_ready_renders,
)
from tests.narration.test_regeneration import _clone_projection_target


def _ready_playback_foundation():
    store = MemoryNarrationStore()
    foundation = _edition_with_ready_renders(store)
    edition = foundation[4]
    renders = foundation[6]
    rows = store.find_all(
        NarrationEditionSegment,
        edition_id=edition.id,
        order_by=("ordinal",),
    )
    return store, edition, renders, rows


def _publish_all_ready(store, edition, renders, rows, *, revision: int):
    return publish_manifest(
        store,
        PublishManifest(
            edition_id=edition.id,
            expected_current_revision=revision,
            expected_state_version=revision,
            buffer_policy=INITIAL_BUFFER_POLICY,
            segments=tuple(
                ManifestSegmentInput(row.id, "ready", renders[index].id)
                for index, row in enumerate(rows)
            ),
            updated_actor="t4-j-recovery",
        ),
    )


def test_saved_position_restores_on_a_new_manifest_and_prepares_the_exact_resume_range() -> None:
    store, edition, renders, rows = _ready_playback_foundation()
    first = _publish_all_ready(store, edition, renders, rows, revision=0)
    saved = save_playback_progress(
        store,
        SavePlaybackProgress(
            profile_id="default",
            edition_id=edition.id,
            manifest_revision=first.manifest_revision,
            edition_segment_id=rows[0].id,
            offset_ms=450,
            last_legal_start_ordinal=0,
            playback_rate_millis=1_250,
            expected_updated_at=None,
        ),
    )
    second = _publish_all_ready(store, edition, renders, rows, revision=1)
    promoted = []

    restored = restore_playback_progress(
        store,
        profile_id="default",
        edition_id=edition.id,
    )
    assert restored is not None
    prepared = prepare_manifest_range(
        store,
        PrepareRangeCommand(
            edition_id=edition.id,
            start_segment_id=restored.segment_id,
            reason="resume",
            expected_manifest_revision=restored.manifest_revision,
            idempotency_key="t4-j:resume:latest-manifest:0001",
        ),
        promote_job=lambda job: not promoted.append(job.id),
    )

    assert restored.manifest_revision == second.manifest_revision == 2
    assert restored.manifest_etag == f'"{second.etag_sha256}"'
    assert restored.manifest_advanced is True
    assert restored.edition_segment_id == rows[0].id
    assert restored.segment_id == rows[0].segment_id
    assert restored.offset_ms == 450
    assert restored.playback_rate_millis == 1_250
    assert prepared.state == "ready"
    assert prepared.start_segment_id == rows[0].segment_id
    assert prepared.manifest_revision == 2
    assert prepared.promoted_job_ids == ()
    assert promoted == []
    assert saved.manifest_revision == 1
    assert store.find_one(
        NarrationPlaybackProgress,
        profile_id="default",
        edition_id=edition.id,
    ) is saved


def test_restore_never_guesses_across_editions_or_changed_segment_mapping() -> None:
    store, edition, renders, rows = _ready_playback_foundation()
    first = _publish_all_ready(store, edition, renders, rows, revision=0)
    saved = save_playback_progress(
        store,
        SavePlaybackProgress(
            profile_id="default",
            edition_id=edition.id,
            manifest_revision=first.manifest_revision,
            edition_segment_id=rows[0].id,
            offset_ms=200,
            last_legal_start_ordinal=0,
            playback_rate_millis=1_000,
            expected_updated_at=None,
        ),
    )
    second = _publish_all_ready(store, edition, renders, rows, revision=1)
    second.canonical_json["segments"][0]["segment_id"] = str(uuid4())

    with pytest.raises(InvalidNarrationState, match="not ready"):
        restore_playback_progress(
            store,
            profile_id="default",
            edition_id=edition.id,
        )

    other_edition, _other_rows = _clone_projection_target(store, edition, rows)
    assert restore_playback_progress(
        store,
        profile_id="default",
        edition_id=other_edition.id,
    ) is None
    assert saved.edition_id == edition.id
    assert saved.manifest_revision == 1
    assert saved.edition_segment_id == rows[0].id


def test_stale_progress_writer_cannot_overwrite_the_last_recoverable_position() -> None:
    store, edition, renders, rows = _ready_playback_foundation()
    manifest = _publish_all_ready(store, edition, renders, rows, revision=0)
    first = save_playback_progress(
        store,
        SavePlaybackProgress(
            profile_id="default",
            edition_id=edition.id,
            manifest_revision=manifest.manifest_revision,
            edition_segment_id=rows[0].id,
            offset_ms=100,
            last_legal_start_ordinal=0,
            playback_rate_millis=1_000,
            expected_updated_at=None,
        ),
    )
    stale_token = first.updated_at
    latest = save_playback_progress(
        store,
        SavePlaybackProgress(
            profile_id="default",
            edition_id=edition.id,
            manifest_revision=manifest.manifest_revision,
            edition_segment_id=rows[1].id,
            offset_ms=300,
            last_legal_start_ordinal=1,
            playback_rate_millis=1_500,
            expected_updated_at=stale_token,
        ),
    )

    with pytest.raises(NarrationCasConflict, match="changed"):
        save_playback_progress(
            store,
            SavePlaybackProgress(
                profile_id="default",
                edition_id=edition.id,
                manifest_revision=manifest.manifest_revision,
                edition_segment_id=rows[0].id,
                offset_ms=0,
                last_legal_start_ordinal=0,
                playback_rate_millis=750,
                expected_updated_at=stale_token,
            ),
        )

    restored = restore_playback_progress(
        store,
        profile_id="default",
        edition_id=edition.id,
    )
    assert restored is not None
    assert restored.edition_segment_id == rows[1].id
    assert restored.segment_id == rows[1].segment_id
    assert restored.offset_ms == 300
    assert restored.playback_rate_millis == 1_500
    assert restored.progress_updated_at == latest.updated_at
