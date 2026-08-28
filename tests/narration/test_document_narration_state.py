from __future__ import annotations

from uuid import uuid4

import pytest

from backend.models import (
    BackgroundJob,
    DocumentNarrationState,
    DocumentWorkingCopy,
    NarrationEdition,
    NarrationEditionSegment,
    NarrationRequest,
    NarrationPlaybackProgress,
    NarrationSegmentRender,
)
from backend.narration.document_state import (
    DOCUMENT_NARRATION_CONTEXT_VERSION,
    create_explicit_narration_update_intent,
    project_document_narration_context,
    project_edition_switch_confirmation,
    switch_document_narration_edition_explicitly,
)
from backend.narration.manifest import (
    INITIAL_BUFFER_POLICY,
    ManifestSegmentInput,
    PublishManifest,
    publish_manifest,
)
from backend.narration.progress import switch_document_edition
from backend.narration.services import (
    InvalidNarrationState,
    NarrationCasConflict,
    NarrationScopeMismatch,
    StaleNarrationInput,
)
from tests.narration.test_domain_services import MemoryNarrationStore
from tests.narration.test_regeneration import (
    _clone_projection_target,
    _publish_ready,
    _ready_foundation,
)


def _chapter_with_current_edition():
    store, foundation, edition, renders, rows = _ready_foundation()
    _novel, document, revision, _request = foundation[:4]
    working = DocumentWorkingCopy(
        document_id=document.id,
        base_revision_id=revision.id,
        draft_version=7,
        content_markdown=revision.content_markdown,
        content_hash=revision.content_hash,
    )
    store.add(working)
    _publish_ready(store, edition, renders)
    pointer = switch_document_edition(
        store,
        document_id=document.id,
        edition_id=edition.id,
        expected_version=0,
        actor="owner",
    )
    return store, foundation, edition, renders, rows, working, pointer


def _add_ready_historical_edition(
    store: MemoryNarrationStore,
    source: NarrationEdition,
    source_rows: list[NarrationEditionSegment],
    renders: list[NarrationSegmentRender],
) -> NarrationEdition:
    target, _target_rows = _clone_projection_target(store, source, source_rows)
    _publish_ready(store, target, renders)
    return target


def _add_middle_only_historical_edition(
    store: MemoryNarrationStore,
    source: NarrationEdition,
    source_rows: list[NarrationEditionSegment],
    renders: list[NarrationSegmentRender],
) -> tuple[NarrationEdition, NarrationEditionSegment]:
    target, target_rows = _clone_projection_target(store, source, source_rows)
    target_rows[0].render_state = "pending"
    publish_manifest(
        store,
        PublishManifest(
            edition_id=target.id,
            expected_current_revision=0,
            expected_state_version=0,
            buffer_policy=INITIAL_BUFFER_POLICY,
            segments=(
                ManifestSegmentInput(target_rows[0].id, "pending"),
                ManifestSegmentInput(target_rows[1].id, "ready", renders[1].id),
            ),
            updated_actor="test-worker",
        ),
    )
    return target, target_rows[1]


def test_projects_current_source_without_writing_authority_rows() -> None:
    store, foundation, edition, _renders, _rows, working, pointer = (
        _chapter_with_current_edition()
    )
    before_flush = store.flush_count
    before_counts = {model: len(rows) for model, rows in store.rows.items()}

    result = project_document_narration_context(
        store,
        document_id=foundation[1].id,
    )

    assert result.contract_version == DOCUMENT_NARRATION_CONTEXT_VERSION
    assert result.current_edition_id == edition.id
    assert result.active_edition_id == edition.id
    assert result.pointer_version == pointer.version
    assert result.compatibility == "current"
    assert result.source_notice_code == "CURRENT_SOURCE_SNAPSHOT"
    assert result.editor_timeline_mode == "exact_working_copy"
    assert result.old_draft_subtitle_required is False
    assert result.explicit_update_required is False
    assert result.source_snapshot is not None
    assert result.source_snapshot.content_hash == working.content_hash
    assert result.source_snapshot.matches_working_copy is True
    assert store.flush_count == before_flush
    assert {model: len(rows) for model, rows in store.rows.items()} == before_counts


def test_working_copy_divergence_is_derived_and_keeps_old_edition_immutable() -> None:
    store, foundation, edition, _renders, _rows, working, pointer = (
        _chapter_with_current_edition()
    )
    prior_state = edition.state
    prior_pointer_version = pointer.version
    working.content_markdown = "新正文不会按键触发朗读"
    working.content_hash = "9" * 64
    working.draft_version += 1
    job_count = len(store.rows[BackgroundJob])
    request_count = len(store.rows[NarrationRequest])

    result = project_document_narration_context(
        store,
        document_id=foundation[1].id,
    )

    assert result.compatibility == "working_copy_diverged"
    assert result.source_notice_code == "OLD_SOURCE_SNAPSHOT"
    assert result.editor_timeline_mode == "immutable_edition_only"
    assert result.old_draft_subtitle_required is True
    assert result.explicit_update_required is True
    assert edition.state == prior_state
    assert pointer.version == prior_pointer_version
    assert len(store.rows[BackgroundJob]) == job_count
    assert len(store.rows[NarrationRequest]) == request_count


def test_explicit_update_intent_requires_exact_saved_source_barrier() -> None:
    store, foundation, edition, _renders, _rows, working, pointer = (
        _chapter_with_current_edition()
    )
    working.content_hash = "8" * 64
    working.draft_version = 8
    job_count = len(store.rows[BackgroundJob])
    request_count = len(store.rows[NarrationRequest])

    intent = create_explicit_narration_update_intent(
        store,
        document_id=foundation[1].id,
        expected_draft_version=8,
        expected_content_hash="8" * 64,
        expected_settings_version=3,
        force_review=False,
        idempotency_key="narration:update:chapter-8",
        explicitly_requested=True,
    )

    assert intent.intent == "update"
    assert intent.prior_current_edition_id == edition.id
    assert intent.expected_pointer_version == pointer.version
    assert intent.expected_draft_version == 8
    assert len(store.rows[BackgroundJob]) == job_count
    assert len(store.rows[NarrationRequest]) == request_count


@pytest.mark.parametrize(
    ("draft_version", "content_hash"),
    [(6, "a" * 64), (7, "b" * 64)],
)
def test_explicit_update_rejects_a_stale_save_barrier(
    draft_version: int,
    content_hash: str,
) -> None:
    store, foundation, _edition, _renders, _rows, _working, _pointer = (
        _chapter_with_current_edition()
    )
    with pytest.raises(StaleNarrationInput):
        create_explicit_narration_update_intent(
            store,
            document_id=foundation[1].id,
            expected_draft_version=draft_version,
            expected_content_hash=content_hash,
            expected_settings_version=1,
            force_review=False,
            idempotency_key="narration:update:stale",
            explicitly_requested=True,
        )


def test_autosave_cannot_masquerade_as_an_explicit_update() -> None:
    store, foundation, _edition, _renders, _rows, working, _pointer = (
        _chapter_with_current_edition()
    )
    with pytest.raises(InvalidNarrationState, match="explicit author action"):
        create_explicit_narration_update_intent(
            store,
            document_id=foundation[1].id,
            expected_draft_version=working.draft_version,
            expected_content_hash=working.content_hash,
            expected_settings_version=1,
            force_review=False,
            idempotency_key="narration:update:autosave",
            explicitly_requested=False,
        )


def test_history_selection_projects_confirmation_without_switching_pointer() -> None:
    store, foundation, edition, renders, rows, _working, pointer = (
        _chapter_with_current_edition()
    )
    historical = _add_ready_historical_edition(store, edition, rows, renders)
    prior_pointer = (pointer.current_edition_id, pointer.version)

    result = project_edition_switch_confirmation(
        store,
        document_id=foundation[1].id,
        target_edition_id=historical.id,
    )

    assert result.target_edition_id == historical.id
    assert result.current_edition_id == edition.id
    assert result.expected_pointer_version == pointer.version
    assert result.source_status == "superseded"
    assert result.confirmation_required is True
    assert (pointer.current_edition_id, pointer.version) == prior_pointer
    assert edition.state == "ready"
    assert historical.state == "ready"


def test_explicit_historical_view_never_becomes_current_by_projection() -> None:
    store, foundation, edition, renders, rows, _working, pointer = (
        _chapter_with_current_edition()
    )
    historical = _add_ready_historical_edition(store, edition, rows, renders)

    result = project_document_narration_context(
        store,
        document_id=foundation[1].id,
        active_edition_id=historical.id,
    )

    assert result.active_edition_id == historical.id
    assert result.active_is_current is False
    assert result.current_edition_id == edition.id
    assert result.compatibility == "superseded"
    assert result.source_notice_code == "HISTORICAL_EDITION"
    assert pointer.current_edition_id == edition.id


def test_unplayable_history_target_cannot_produce_switch_confirmation() -> None:
    store, foundation, edition, renders, rows, _working, _pointer = (
        _chapter_with_current_edition()
    )
    historical = _add_ready_historical_edition(store, edition, rows, renders)
    historical.state = "unavailable"
    historical.unavailable_reason = "VOICE_RIGHTS_UNAVAILABLE"

    with pytest.raises(InvalidNarrationState, match="no legal playable"):
        project_edition_switch_confirmation(
            store,
            document_id=foundation[1].id,
            target_edition_id=historical.id,
        )


def test_confirmed_next_playback_switches_only_the_pointer_and_keeps_editions() -> None:
    store, foundation, edition, renders, rows, _working, pointer = (
        _chapter_with_current_edition()
    )
    target = _add_ready_historical_edition(store, edition, rows, renders)
    current_state = edition.state
    target_state = target.state

    result = switch_document_narration_edition_explicitly(
        store,
        document_id=foundation[1].id,
        target_edition_id=target.id,
        expected_pointer_version=pointer.version,
        switch_mode="next_playback",
        start_segment_id=None,
        profile_id="local-reader",
        playback_rate_millis=1000,
        actor="owner",
        confirmed=True,
    )

    assert result.current_edition_id == target.id
    assert result.pointer_version == pointer.version
    assert result.start_segment_id is None
    assert result.playback_progress_id is None
    assert pointer.current_edition_id == target.id
    assert edition.state == current_state
    assert target.state == target_state


def test_confirmed_immediate_switch_saves_exact_ready_start_in_same_unit_of_work() -> None:
    store, foundation, edition, renders, rows, _working, pointer = (
        _chapter_with_current_edition()
    )
    target = _add_ready_historical_edition(store, edition, rows, renders)
    target_rows = store.find_all(
        NarrationEditionSegment,
        edition_id=target.id,
        order_by=("ordinal",),
    )
    start = target_rows[-1]

    result = switch_document_narration_edition_explicitly(
        store,
        document_id=foundation[1].id,
        target_edition_id=target.id,
        expected_pointer_version=pointer.version,
        switch_mode="immediate",
        start_segment_id=start.segment_id,
        profile_id="local-reader",
        playback_rate_millis=1250,
        actor="owner",
        confirmed=True,
    )

    progress = store.get(NarrationPlaybackProgress, result.playback_progress_id)
    assert progress is not None
    assert progress.edition_id == target.id
    assert progress.edition_segment_id == start.id
    assert progress.offset_ms == 0
    assert progress.last_legal_start_ordinal == start.ordinal
    assert progress.playback_rate_millis == 1250
    assert result.start_segment_id == start.segment_id
    assert pointer.current_edition_id == target.id


def test_switch_rejects_missing_confirmation_and_stale_pointer_before_any_write() -> None:
    store, foundation, edition, renders, rows, _working, pointer = (
        _chapter_with_current_edition()
    )
    target = _add_ready_historical_edition(store, edition, rows, renders)
    progress_count = len(store.rows[NarrationPlaybackProgress])
    with pytest.raises(InvalidNarrationState, match="explicit confirmation"):
        switch_document_narration_edition_explicitly(
            store,
            document_id=foundation[1].id,
            target_edition_id=target.id,
            expected_pointer_version=pointer.version,
            switch_mode="immediate",
            start_segment_id=rows[0].segment_id,
            profile_id="local-reader",
            playback_rate_millis=1000,
            actor="owner",
            confirmed=False,
        )
    with pytest.raises(NarrationCasConflict, match="pointer changed"):
        switch_document_narration_edition_explicitly(
            store,
            document_id=foundation[1].id,
            target_edition_id=target.id,
            expected_pointer_version=pointer.version + 1,
            switch_mode="next_playback",
            start_segment_id=None,
            profile_id="local-reader",
            playback_rate_millis=1000,
            actor="owner",
            confirmed=True,
        )
    assert pointer.current_edition_id == edition.id
    assert len(store.rows[NarrationPlaybackProgress]) == progress_count


def test_immediate_switch_rejects_an_unknown_start_without_moving_pointer() -> None:
    store, foundation, edition, renders, rows, _working, pointer = (
        _chapter_with_current_edition()
    )
    target = _add_ready_historical_edition(store, edition, rows, renders)
    with pytest.raises(InvalidNarrationState, match="start segment is not ready"):
        switch_document_narration_edition_explicitly(
            store,
            document_id=foundation[1].id,
            target_edition_id=target.id,
            expected_pointer_version=pointer.version,
            switch_mode="immediate",
            start_segment_id=uuid4(),
            profile_id="local-reader",
            playback_rate_millis=1000,
            actor="owner",
            confirmed=True,
        )
    assert pointer.current_edition_id == edition.id
    assert store.rows[NarrationPlaybackProgress] == []


def test_manifest_verified_middle_start_can_switch_without_chapter_prefix_or_resume() -> None:
    store, foundation, edition, renders, rows, _working, pointer = (
        _chapter_with_current_edition()
    )
    target, start = _add_middle_only_historical_edition(
        store,
        edition,
        rows,
        renders,
    )
    with pytest.raises(InvalidNarrationState, match="no legal playable"):
        project_edition_switch_confirmation(
            store,
            document_id=foundation[1].id,
            target_edition_id=target.id,
            profile_id="local-reader",
        )

    confirmation = project_edition_switch_confirmation(
        store,
        document_id=foundation[1].id,
        target_edition_id=target.id,
        profile_id="local-reader",
        explicit_start_segment_id=start.segment_id,
    )
    assert confirmation.default_start_ready is False
    assert confirmation.resume_available is False
    assert confirmation.explicit_start_segment_id == start.segment_id

    result = switch_document_narration_edition_explicitly(
        store,
        document_id=foundation[1].id,
        target_edition_id=target.id,
        expected_pointer_version=pointer.version,
        switch_mode="immediate",
        start_segment_id=start.segment_id,
        profile_id="local-reader",
        playback_rate_millis=1000,
        actor="owner",
        confirmed=True,
    )
    assert result.start_segment_id == start.segment_id
    assert pointer.current_edition_id == target.id


def test_document_without_current_pointer_stays_unbound_despite_ready_history() -> None:
    store, foundation, edition, renders, _rows = _ready_foundation()
    _novel, document, revision, _request = foundation[:4]
    store.add(
        DocumentWorkingCopy(
            document_id=document.id,
            base_revision_id=revision.id,
            draft_version=1,
            content_markdown=revision.content_markdown,
            content_hash=revision.content_hash,
        )
    )
    _publish_ready(store, edition, renders)

    result = project_document_narration_context(store, document_id=document.id)

    assert result.current_edition_id is None
    assert result.active_edition_id is None
    assert result.compatibility == "no_current_edition"
    assert result.can_request_update is False
    assert store.rows[DocumentNarrationState] == []


def test_cross_document_active_edition_is_rejected() -> None:
    store, foundation, _edition, _renders, _rows, _working, _pointer = (
        _chapter_with_current_edition()
    )
    with pytest.raises(NarrationScopeMismatch):
        project_document_narration_context(
            store,
            document_id=foundation[1].id,
            active_edition_id=uuid4(),
        )
