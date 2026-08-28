from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import pytest

from backend.models import (
    NarrationRequest,
    NarrationScene,
    NarrationScript,
    NarrationScriptIssue,
    NarrationScriptReviewActionRecord,
    NarrationScriptVersion,
    NarrationSegment,
    VoiceProfile,
)
from backend.narration.review_actions import (
    CorrectReviewSegment,
    ReanalyzeReviewSegments,
    correct_review_segment,
    reanalyze_review_segments,
)
from backend.narration.script_analysis import analyze_narration_script
from backend.narration.script_contracts import (
    AttributionOrigin,
    CastingDecision,
    CastingDecisionOrigin,
    CastingTargetKind,
    CastingTargetRef,
    ScriptVersionState,
    SpeakerKind,
    SpeakerRef,
    script_contract_to_dict,
)
from backend.narration.script_versions import freeze_script_version, load_script_contract
from backend.narration.services import (
    IdempotencyConflict,
    InvalidNarrationState,
    NarrationCasConflict,
    NarrationServiceError,
    StaleNarrationInput,
    VoiceRightsUnavailable,
)
from tests.narration.test_script_analysis import _seed


def _row_snapshot(row: object) -> dict[str, object]:
    return {
        column.name: deepcopy(getattr(row, column.name))
        for column in row.__table__.columns
    }


def _review_seed(
    source: str = "“没有任何说话提示。”",
    *,
    include_character_voice: bool = True,
):
    (
        store,
        novel,
        document,
        revision,
        character,
        request,
        analyze_command,
    ) = _seed(
        source,
        intent="create",
        include_character_voice=include_character_voice,
    )
    parent = analyze_narration_script(store, analyze_command)
    assert parent.state is ScriptVersionState.REVIEW_REQUIRED
    assert request.state == "review_required"
    assert request.review_script_id == parent.script_id
    assert request.current_review_version_id == parent.script_version_id
    profile = store.find_one(VoiceProfile, name="narrator")
    assert profile is not None
    target = CastingTargetRef(
        kind=CastingTargetKind.PROFILE,
        profile_id=profile.id,
    )
    casting = CastingDecision(
        candidate_targets=(target,),
        final_target=target,
        origin=CastingDecisionOrigin.NARRATOR_SETTING,
    )
    return (
        store,
        novel,
        document,
        revision,
        character,
        request,
        parent,
        casting,
    )


def _command(
    request,
    contract,
    casting: CastingDecision,
    *,
    segment_index: int = 0,
    key: str = "review-patch-action-0001",
    spoken_text: str = "修正后的朗读文本。",
) -> CorrectReviewSegment:
    segment = contract.segments[segment_index]
    return CorrectReviewSegment(
        request_id=request.id,
        script_version_id=contract.script_version_id,
        segment_id=segment.segment_id,
        expected_request_version=request.version,
        expected_version_number=contract.version_number,
        expected_immutable_hash=contract.immutable_hash,
        expected_local_hash=segment.local_hash,
        idempotency_key=key,
        actor_id="owner",
        speaker=SpeakerRef(SpeakerKind.NARRATOR),
        casting=casting,
        spoken_text=spoken_text,
        reason="作者确认该句应由旁白朗读",
    )


def _counts(store) -> tuple[int, int, int, int, int]:
    return (
        len(store.rows[NarrationScriptVersion]),
        len(store.rows[NarrationScene]),
        len(store.rows[NarrationSegment]),
        len(store.rows[NarrationScriptIssue]),
        len(store.rows[NarrationScriptReviewActionRecord]),
    )


def test_correction_creates_typed_child_regenerates_every_id_and_never_writes_parent() -> None:
    store, _novel, _document, _revision, _character, request, parent, casting = (
        _review_seed()
    )
    parent_row = store.get(NarrationScriptVersion, parent.script_version_id)
    assert parent_row is not None
    parent_scenes = store.find_all(
        NarrationScene,
        script_version_id=parent.script_version_id,
    )
    parent_segments = store.find_all(
        NarrationSegment,
        script_version_id=parent.script_version_id,
    )
    parent_issues = store.find_all(
        NarrationScriptIssue,
        script_version_id=parent.script_version_id,
    )
    frozen_rows = [
        _row_snapshot(row)
        for row in [parent_row, *parent_scenes, *parent_segments, *parent_issues]
    ]
    request_version = request.version

    result = correct_review_segment(store, _command(request, parent, casting))

    assert result.replayed is False
    assert result.parent_version_id == parent.script_version_id
    assert result.result_version_id == result.contract.script_version_id
    assert result.contract.parent_version_id == parent.script_version_id
    assert result.contract.version_number == parent.version_number + 1
    assert result.contract.state is ScriptVersionState.REVIEW_REQUIRED
    assert result.contract.blocker_count == 0
    assert request.current_review_version_id == result.result_version_id
    assert request.review_script_id == parent.script_id
    assert request.version == request_version + 1

    assert {scene.scene_id for scene in result.contract.scenes}.isdisjoint(
        {scene.scene_id for scene in parent.scenes}
    )
    assert {segment.segment_id for segment in result.contract.segments}.isdisjoint(
        {segment.segment_id for segment in parent.segments}
    )
    assert {
        segment.source_block_key for segment in result.contract.segments
    }.isdisjoint({segment.source_block_key for segment in parent.segments})
    corrected = result.contract.segments[0]
    assert corrected.spoken_text == "修正后的朗读文本。"
    assert corrected.confidence.value == "high"
    assert corrected.manual_override is True
    assert corrected.attribution.origin is AttributionOrigin.MANUAL_OVERRIDE
    assert corrected.attribution.override_provenance is not None
    assert corrected.attribution.override_provenance.action_id == result.action_id

    action = store.get(NarrationScriptReviewActionRecord, result.action_id)
    assert action is not None
    assert action.action_kind == "patch_segment"
    assert action.parent_version_id == parent.script_version_id
    assert action.result_version_id == result.result_version_id
    assert action.result_edition_id is None
    assert action.request_version_before == request_version
    assert action.request_version_after == request_version + 1
    assert action.request_hash == result.request_hash

    current_rows = [
        _row_snapshot(row)
        for row in [parent_row, *parent_scenes, *parent_segments, *parent_issues]
    ]
    assert current_rows == frozen_rows
    assert script_contract_to_dict(
        load_script_contract(store, parent.script_version_id)
    ) == script_contract_to_dict(parent)
    assert script_contract_to_dict(
        load_script_contract(store, result.result_version_id)
    ) == script_contract_to_dict(result.contract)


def test_correction_accepts_exact_4000_codepoint_spoken_text() -> None:
    store, _novel, _document, _revision, _character, request, parent, casting = (
        _review_seed()
    )
    spoken_text = "声" * 4000

    result = correct_review_segment(
        store,
        _command(request, parent, casting, spoken_text=spoken_text),
    )

    assert result.contract.segments[0].spoken_text == spoken_text


@pytest.mark.parametrize(
    ("spoken_text", "message"),
    [
        ("声" * 4001, "exceeds 4000"),
        ("e\u0301", "Unicode NFC"),
        ("\ud800", "unpaired Unicode surrogate"),
    ],
    ids=["max-plus-one", "not-nfc", "unpaired-surrogate"],
)
def test_correction_rejects_spoken_text_amplification_or_invalid_unicode(
    spoken_text: str,
    message: str,
) -> None:
    store, _novel, _document, _revision, _character, request, parent, casting = (
        _review_seed()
    )
    before = (*_counts(store), request.version)

    with pytest.raises(NarrationServiceError, match=message):
        correct_review_segment(
            store,
            _command(request, parent, casting, spoken_text=spoken_text),
        )

    assert (*_counts(store), request.version) == before


def test_manual_child_can_freeze_and_reload_through_the_shared_loader() -> None:
    store, _novel, _document, _revision, _character, request, parent, casting = (
        _review_seed()
    )
    corrected = correct_review_segment(store, _command(request, parent, casting))
    assert corrected.contract.blocker_count == 0

    freeze_script_version(
        store,
        corrected.result_version_id,
        request_id=request.id,
        actor_type="owner",
        actor_id="owner",
    )

    approved = load_script_contract(store, corrected.result_version_id)
    assert approved.state is ScriptVersionState.APPROVED
    assert approved.approval is not None
    assert approved.approval.kind.value == "manual_after_review"
    assert approved.approval.request_id == request.id


def test_freeze_helper_locks_request_before_version_and_script() -> None:
    store, _novel, _document, _revision, _character, request, parent, casting = (
        _review_seed()
    )
    corrected = correct_review_segment(store, _command(request, parent, casting))

    class RecordingStore:
        def __init__(self, wrapped: object) -> None:
            self.wrapped = wrapped
            self.locks: list[type[object]] = []

        def __getattr__(self, name: str) -> object:
            return getattr(self.wrapped, name)

        def get(
            self,
            model: type[object],
            row_id: object,
            *,
            for_update: bool = False,
        ) -> object | None:
            if for_update and model in {
                NarrationRequest,
                NarrationScriptVersion,
                NarrationScript,
            }:
                self.locks.append(model)
            return self.wrapped.get(  # type: ignore[attr-defined]
                model,
                row_id,
                for_update=for_update,
            )

    recording = RecordingStore(store)
    freeze_script_version(
        recording,  # type: ignore[arg-type]
        corrected.result_version_id,
        request_id=request.id,
        actor_type="owner",
        actor_id="owner",
    )

    assert recording.locks[:3] == [
        NarrationRequest,
        NarrationScriptVersion,
        NarrationScript,
    ]


def test_same_action_replays_without_writes_and_changed_input_conflicts() -> None:
    store, _novel, _document, _revision, _character, request, parent, casting = (
        _review_seed()
    )
    command = _command(request, parent, casting)
    first = correct_review_segment(store, command)
    counts_after_first = _counts(store)
    request_version = request.version

    replay = correct_review_segment(store, command)

    assert replay.replayed is True
    assert replay.action_id == first.action_id
    assert replay.result_version_id == first.result_version_id
    assert replay.contract.immutable_hash == first.contract.immutable_hash
    assert request.version == request_version
    assert _counts(store) == counts_after_first

    with pytest.raises(IdempotencyConflict, match="canonical input"):
        correct_review_segment(
            store,
            replace(command, spoken_text="同键但不同内容"),
        )
    assert request.version == request_version
    assert _counts(store) == counts_after_first


def test_request_script_and_segment_cas_fail_before_any_write() -> None:
    store, _novel, _document, _revision, _character, request, parent, casting = (
        _review_seed()
    )
    baseline = _counts(store)
    base = _command(request, parent, casting)

    with pytest.raises(NarrationCasConflict, match="request version"):
        correct_review_segment(
            store,
            replace(
                base,
                expected_request_version=request.version + 1,
                idempotency_key="review-patch-stale-request",
            ),
        )
    with pytest.raises(StaleNarrationInput, match="immutable hash"):
        correct_review_segment(
            store,
            replace(
                base,
                expected_immutable_hash="f" * 64,
                idempotency_key="review-patch-stale-script",
            ),
        )
    with pytest.raises(StaleNarrationInput, match="local hash"):
        correct_review_segment(
            store,
            replace(
                base,
                expected_local_hash="e" * 64,
                idempotency_key="review-patch-stale-segment",
            ),
        )
    request.current_review_version_id = uuid4()
    with pytest.raises(NarrationCasConflict, match="current review version"):
        correct_review_segment(
            store,
            replace(base, idempotency_key="review-patch-stale-pointer"),
        )
    request.current_review_version_id = parent.script_version_id

    assert request.version == base.expected_request_version
    assert request.current_review_version_id == parent.script_version_id
    assert _counts(store) == baseline


def test_cross_inconsistent_speaker_and_casting_fails_before_persistence() -> None:
    store, _novel, _document, _revision, character, request, parent, casting = (
        _review_seed()
    )
    baseline = _counts(store)
    command = replace(
        _command(
            request,
            parent,
            casting,
            key="review-patch-invalid-speaker-casting",
        ),
        speaker=SpeakerRef(
            SpeakerKind.CHARACTER,
            character_id=character.id,
        ),
    )

    with pytest.raises(InvalidNarrationState, match="speaker/casting shape"):
        correct_review_segment(store, command)

    assert request.current_review_version_id == parent.script_version_id
    assert _counts(store) == baseline


def test_resolved_casting_is_rechecked_for_current_voice_usability() -> None:
    store, _novel, _document, _revision, _character, request, parent, casting = (
        _review_seed()
    )
    baseline = _counts(store)
    profile = store.find_one(VoiceProfile, name="narrator")
    assert profile is not None
    profile.status = "archived"

    with pytest.raises(VoiceRightsUnavailable, match="not active"):
        correct_review_segment(
            store,
            _command(
                request,
                parent,
                casting,
                key="review-patch-unusable-voice",
            ),
        )

    assert request.current_review_version_id == parent.script_version_id
    assert _counts(store) == baseline


def test_review_required_request_without_pointer_fails_closed() -> None:
    store, _novel, _document, _revision, _character, request, parent, casting = (
        _review_seed()
    )
    baseline = _counts(store)
    request.review_script_id = None
    request.current_review_version_id = None

    with pytest.raises(InvalidNarrationState, match="no complete current"):
        correct_review_segment(store, _command(request, parent, casting))

    assert _counts(store) == baseline


def test_unrelated_voice_blocker_is_preserved_and_repointed_to_child_segment() -> None:
    store, _novel, _document, _revision, _character, request, parent, casting = (
        _review_seed(
            "林晚说道：“走吧。”",
            include_character_voice=False,
        )
    )
    target_index = next(
        index
        for index, segment in enumerate(parent.segments)
        if segment.speaker.kind is SpeakerKind.CHARACTER
    )
    target = parent.segments[target_index]
    assert {
        issue.code
        for issue in parent.issues
        if issue.segment_id == target.segment_id
    } == {"B_CASTING_TARGET_UNRESOLVED", "B_VOICE_MISSING"}

    result = correct_review_segment(
        store,
        _command(
            request,
            parent,
            casting,
            segment_index=target_index,
            key="review-patch-preserve-voice",
        ),
    )

    corrected = result.contract.segments[target_index]
    target_issues = [
        issue
        for issue in result.contract.issues
        if issue.segment_id == corrected.segment_id
    ]
    assert [issue.code for issue in target_issues] == ["B_VOICE_MISSING"]
    assert all(issue.segment_id != target.segment_id for issue in result.contract.issues)
    assert result.contract.blocker_count == 1


def test_two_sequential_corrections_use_same_request_and_manual_parent_chain() -> None:
    store, _novel, _document, _revision, _character, request, parent, casting = (
        _review_seed("“第一句。”\n\n“第二句。”")
    )
    assert len(parent.segments) == 2

    first_command = _command(
        request,
        parent,
        casting,
        segment_index=0,
        key="review-patch-first-segment",
        spoken_text="第一句已修正。",
    )
    first = correct_review_segment(store, first_command)
    first_override = first.contract.segments[0].attribution.override_provenance
    assert first_override is not None
    assert first.contract.blocker_count == 3

    second = correct_review_segment(
        store,
        _command(
            request,
            first.contract,
            casting,
            segment_index=1,
            key="review-patch-second-segment",
            spoken_text="第二句已修正。",
        ),
    )

    assert second.contract.parent_version_id == first.contract.script_version_id
    assert second.contract.version_number == first.contract.version_number + 1
    assert second.contract.blocker_count == 0
    assert request.current_review_version_id == second.contract.script_version_id
    assert request.version == second.request_version_after
    assert {
        segment.segment_id for segment in second.contract.segments
    }.isdisjoint({segment.segment_id for segment in first.contract.segments})
    inherited_manual = second.contract.segments[0].attribution.override_provenance
    assert inherited_manual == first_override
    assert second.contract.segments[0].spoken_text == "第一句已修正。"
    assert second.contract.segments[1].spoken_text == "第二句已修正。"
    assert len(store.rows[NarrationScriptReviewActionRecord]) == 2

    replay_first = correct_review_segment(store, first_command)
    assert replay_first.replayed is True
    assert replay_first.result_version_id == first.result_version_id
    assert request.current_review_version_id == second.result_version_id
    assert request.version == second.request_version_after


def test_partial_reanalysis_interface_is_explicitly_fail_closed_without_writes() -> None:
    store, _novel, _document, _revision, _character, request, parent, _casting = (
        _review_seed()
    )
    baseline = _counts(store)
    command = ReanalyzeReviewSegments(
        request_id=request.id,
        script_version_id=parent.script_version_id,
        segment_ids=(parent.segments[0].segment_id,),
        expected_request_version=request.version,
        expected_version_number=parent.version_number,
        expected_immutable_hash=parent.immutable_hash,
        idempotency_key="review-reanalyze-action-0001",
        actor_id="owner",
    )

    with pytest.raises(InvalidNarrationState, match="shared analyzer adapter"):
        reanalyze_review_segments(store, command)

    assert request.current_review_version_id == parent.script_version_id
    assert _counts(store) == baseline
