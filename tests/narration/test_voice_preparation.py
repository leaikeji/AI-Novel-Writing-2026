from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from backend.narration.services import IdempotencyConflict, NarrationCasConflict
from backend.narration.voice_preparation import (
    VOICE_PREPARATION_BINDING_DRIFTED,
    VOICE_PREPARATION_CONTINUATION_LEASE,
    VOICE_PREPARATION_MODE,
    VOICE_PREPARATION_SOURCE_DRIFTED,
    AnalyzeOnlyPreflightAdapter,
    AnalyzeOnlyPreflightRequest,
    ContinuationResultState,
    ExistingVoiceKind,
    ExistingVoiceSnapshot,
    FrozenSpeakerSegment,
    NarrationContinuationRequest,
    NarrationContinuationResult,
    OfficialFallbackRequest,
    OfficialFallbackResult,
    OfficialFallbackState,
    VoiceGeneratorChild,
    VoiceGeneratorChildState,
    VoiceGeneratorReserveRequest,
    VoicePreparationCommand,
    VoicePreparationCommandState,
    VoicePreparationContinuationState,
    VoicePreparationCreateRequest,
    VoicePreparationError,
    VoicePreparationItemState,
    VoicePreparationPreflight,
    VoicePreparationReservation,
    VoicePreparationService,
    VoicePreparationTarget,
    ensure_command_transition,
    ensure_item_transition,
    speaker_summary_digest,
)


NOVEL_ID = UUID("10000000-0000-4000-8000-000000000001")
DOCUMENT_ID = UUID("10000000-0000-4000-8000-000000000002")
REVISION_ID = UUID("10000000-0000-4000-8000-000000000003")
PREFLIGHT_REQUEST_ID = UUID("10000000-0000-4000-8000-000000000004")
SCRIPT_VERSION_ID = UUID("10000000-0000-4000-8000-000000000005")
MAIN_ID = UUID("20000000-0000-4000-8000-000000000001")
SUPPORT_ID = UUID("20000000-0000-4000-8000-000000000002")
BACKGROUND_ID = UUID("20000000-0000-4000-8000-000000000003")
PROFILE_ID = UUID("30000000-0000-4000-8000-000000000001")
VERSION_ID = UUID("30000000-0000-4000-8000-000000000002")
CHILD_ID = UUID("40000000-0000-4000-8000-000000000001")
REQUEST_ID = UUID("50000000-0000-4000-8000-000000000001")
CONTENT_HASH = "a" * 64
SETTINGS_FINGERPRINT = "b" * 64
WORKSPACE_DIGEST = "c" * 64
NOW = datetime(2026, 9, 3, 8, 0, tzinfo=UTC)


class MemoryRepository:
    def __init__(self) -> None:
        self.rows: dict[UUID, VoicePreparationCommand] = {}
        self.by_key: dict[str, UUID] = {}
        self.fail_next_save = False

    def reserve(self, command: VoicePreparationCommand) -> VoicePreparationReservation:
        existing_id = self.by_key.get(command.external_idempotency_digest)
        if existing_id is not None:
            existing = self.rows[existing_id]
            if (
                existing.novel_id != command.novel_id
                or existing.request_hash != command.request_hash
            ):
                raise IdempotencyConflict("voice preparation idempotency key was reused")
            return VoicePreparationReservation(existing.command_id, True)
        self.rows[command.command_id] = command
        self.by_key[command.external_idempotency_digest] = command.command_id
        return VoicePreparationReservation(command.command_id, False)

    def get(self, *, novel_id: UUID, command_id: UUID) -> VoicePreparationCommand:
        result = self.rows[command_id]
        assert result.novel_id == novel_id
        return result

    def compare_and_swap(
        self,
        *,
        expected_aggregate_version: int,
        command: VoicePreparationCommand,
    ) -> bool:
        if self.fail_next_save:
            self.fail_next_save = False
            return False
        current = self.rows[command.command_id]
        if current.aggregate_version != expected_aggregate_version:
            return False
        assert command.aggregate_version == expected_aggregate_version + 1
        self.rows[command.command_id] = command
        return True


class FixedPreflight:
    def __init__(self, result: VoicePreparationPreflight, events: list[str]) -> None:
        self.result = result
        self.events = events
        self.requests: list[AnalyzeOnlyPreflightRequest] = []

    def analyze(self, request: AnalyzeOnlyPreflightRequest) -> VoicePreparationPreflight:
        self.events.append("preflight")
        self.requests.append(request)
        return self.result


class FixedInventory:
    def __init__(self, targets: tuple[VoicePreparationTarget, ...], events: list[str]) -> None:
        self.targets = targets
        self.events = events

    def load_targets(
        self,
        *,
        novel_id: UUID,
        preflight: VoicePreparationPreflight | None,
    ) -> tuple[VoicePreparationTarget, ...]:
        assert novel_id == NOVEL_ID
        self.events.append("inventory")
        return self.targets


class FakeVoiceGenerator:
    def __init__(self) -> None:
        self.calls: list[VoiceGeneratorReserveRequest] = []
        self.cancelled: list[UUID] = []
        self.children: dict[UUID, VoiceGeneratorChild] = {}

    def reserve(self, request: VoiceGeneratorReserveRequest) -> VoiceGeneratorChild:
        self.calls.append(request)
        child = next(
            (
                value
                for value in self.children.values()
                if value.command_id == CHILD_ID
            ),
            VoiceGeneratorChild(CHILD_ID, VoiceGeneratorChildState.ACTIVE),
        )
        self.children[child.command_id] = child
        return child

    def get(self, *, novel_id: UUID, command_id: UUID) -> VoiceGeneratorChild:
        assert novel_id == NOVEL_ID
        return self.children[command_id]

    def cancel(self, *, novel_id: UUID, command_id: UUID) -> None:
        assert novel_id == NOVEL_ID
        self.cancelled.append(command_id)


class FakeFallback:
    def __init__(self) -> None:
        self.calls: list[OfficialFallbackRequest] = []
        self.result = OfficialFallbackResult(
            OfficialFallbackState.APPLIED,
            profile_id=PROFILE_ID,
            voice_version_id=VERSION_ID,
            binding_version=1,
        )

    def ensure(self, request: OfficialFallbackRequest) -> OfficialFallbackResult:
        self.calls.append(request)
        return self.result


class FakeContinuation:
    def __init__(self) -> None:
        self.calls: list[NarrationContinuationRequest] = []
        self.result = NarrationContinuationResult(
            ContinuationResultState.CREATED,
            REQUEST_ID,
        )
        self.requests_by_key: dict[str, UUID] = {}

    def create_or_replay(
        self, request: NarrationContinuationRequest
    ) -> NarrationContinuationResult:
        self.calls.append(request)
        request_id = self.requests_by_key.setdefault(request.idempotency_key, REQUEST_ID)
        if self.result.state is ContinuationResultState.CREATED:
            return NarrationContinuationResult(ContinuationResultState.CREATED, request_id)
        return self.result


class MutableClock:
    def __init__(self) -> None:
        self.value = NOW

    def __call__(self) -> datetime:
        return self.value


def _segments(*character_ids: UUID) -> tuple[FrozenSpeakerSegment, ...]:
    rows = [
        FrozenSpeakerSegment(0, "paragraph", 0, 4, "narrator"),
    ]
    rows.extend(
        FrozenSpeakerSegment(
            index,
            "dialogue",
            index * 4,
            index * 4 + 4,
            "character",
            character_id=character_id,
        )
        for index, character_id in enumerate(character_ids, start=1)
    )
    return tuple(rows)


def _preflight(*character_ids: UUID) -> VoicePreparationPreflight:
    segments = _segments(*character_ids)
    return VoicePreparationPreflight(
        novel_id=NOVEL_ID,
        request_id=PREFLIGHT_REQUEST_ID,
        script_version_id=SCRIPT_VERSION_ID,
        document_id=DOCUMENT_ID,
        source_revision_id=REVISION_ID,
        draft_version=3,
        content_hash=CONTENT_HASH,
        settings_version=4,
        settings_fingerprint=SETTINGS_FINGERPRINT,
        segments=segments,
        speaker_digest=speaker_summary_digest(segments),
    )


def _voice(
    kind: ExistingVoiceKind = ExistingVoiceKind.NONE,
    *,
    usable: bool = False,
) -> ExistingVoiceSnapshot:
    if kind is ExistingVoiceKind.NONE:
        return ExistingVoiceSnapshot(kind, 0)
    return ExistingVoiceSnapshot(
        kind,
        7,
        profile_id=PROFILE_ID,
        voice_version_id=VERSION_ID,
        usable=usable,
    )


def _target(
    character_id: UUID,
    *,
    role_type: str = "supporting",
    voice: ExistingVoiceSnapshot | None = None,
    active: bool = True,
    saved: bool = True,
) -> VoicePreparationTarget:
    return VoicePreparationTarget(
        character_id=character_id,
        role_type=role_type,
        active=active,
        has_saved_character_card=saved,
        workspace_digest=WORKSPACE_DIGEST,
        voice=voice or _voice(),
    )


def _request(
    *,
    chapter: bool = True,
    key: str = "voice-prepare-key",
) -> VoicePreparationCreateRequest:
    return VoicePreparationCreateRequest(
        novel_id=NOVEL_ID,
        idempotency_key=key,
        actor="local-owner",
        explicit_requested_at=NOW,
        document_id=DOCUMENT_ID if chapter else None,
        expected_draft_version=3 if chapter else None,
        expected_content_hash=CONTENT_HASH if chapter else None,
        expected_settings_version=4 if chapter else None,
    )


def _service(
    *,
    targets: tuple[VoicePreparationTarget, ...] = (),
    preflight: VoicePreparationPreflight | None = None,
    repository: MemoryRepository | None = None,
    voice_generator: FakeVoiceGenerator | None = None,
    fallback: FakeFallback | None = None,
    continuation: FakeContinuation | None = None,
    clock: MutableClock | None = None,
) -> tuple[
    VoicePreparationService,
    MemoryRepository,
    FakeVoiceGenerator,
    FakeFallback,
    FakeContinuation,
    list[str],
]:
    events: list[str] = []
    repo = repository or MemoryRepository()
    generator = voice_generator or FakeVoiceGenerator()
    official = fallback or FakeFallback()
    final = continuation or FakeContinuation()
    service = VoicePreparationService(
        repository=repo,
        preflight=FixedPreflight(preflight or _preflight(), events),
        inventory=FixedInventory(targets, events),
        voice_generator=generator,
        official_fallback=official,
        continuation=final,
        clock=clock or MutableClock(),
        fence_factory=lambda: UUID("60000000-0000-4000-8000-000000000001"),
    )
    return service, repo, generator, official, final, events


def test_state_taxonomies_are_monotonic_and_fail_closed() -> None:
    assert ensure_command_transition(
        VoicePreparationCommandState.RESERVED,
        VoicePreparationCommandState.PREPARING,
    ) is VoicePreparationCommandState.PREPARING
    assert ensure_item_transition(
        VoicePreparationItemState.PENDING,
        VoicePreparationItemState.QUEUED,
    ) is VoicePreparationItemState.QUEUED
    with pytest.raises(ValueError, match="invalid voice preparation transition"):
        ensure_command_transition(
            VoicePreparationCommandState.READY,
            VoicePreparationCommandState.PREPARING,
        )
    with pytest.raises(ValueError, match="invalid voice preparation item"):
        ensure_item_transition(
            VoicePreparationItemState.READY_APPLIED,
            VoicePreparationItemState.GENERATING,
        )


def test_speaker_digest_uses_only_order_coordinates_kind_and_stable_identity() -> None:
    segments = _segments(MAIN_ID)
    first = speaker_summary_digest(segments)
    assert len(first) == 64
    assert first == speaker_summary_digest(tuple(replace(item) for item in segments))
    assert first != speaker_summary_digest(_segments(SUPPORT_ID))
    with pytest.raises(ValueError, match="contiguous"):
        speaker_summary_digest((replace(segments[0], ordinal=2),))


def test_preflight_adapter_rejects_source_cas_drift() -> None:
    request = AnalyzeOnlyPreflightRequest(
        NOVEL_ID,
        DOCUMENT_ID,
        3,
        CONTENT_HASH,
        4,
        "preflight-key-1",
    )
    adapter = AnalyzeOnlyPreflightAdapter(lambda _request: replace(_preflight(), draft_version=5))
    with pytest.raises(NarrationCasConflict, match="source changed"):
        adapter.analyze(request)


def test_service_maps_preflight_cas_drift_to_frozen_parent_failure_code() -> None:
    service, _repo, _generator, _fallback, _continuation, _events = _service()
    service._preflight = AnalyzeOnlyPreflightAdapter(  # noqa: SLF001
        lambda _request: replace(_preflight(), content_hash="d" * 64)
    )
    with pytest.raises(VoicePreparationError) as caught:
        service.create(_request())
    assert caught.value.code == VOICE_PREPARATION_SOURCE_DRIFTED
    assert caught.value.retryable is True


def test_preflight_runs_before_inventory_and_same_create_replays_parent() -> None:
    service, repo, _generator, _fallback, _continuation, events = _service(
        targets=(_target(MAIN_ID, role_type="main"),),
        preflight=_preflight(MAIN_ID),
    )
    first = service.create(_request())
    second = service.create(_request())
    assert first.replayed is False
    assert second == VoicePreparationReservation(first.command_id, True)
    assert events == ["preflight", "inventory", "preflight", "inventory"]
    assert len(repo.rows) == 1


def test_same_idempotency_key_ignores_server_generated_request_timestamp() -> None:
    service, _repo, _generator, _fallback, _continuation, _events = _service(
        preflight=_preflight(),
    )
    first = service.create(_request())
    replay = service.create(
        replace(
            _request(),
            explicit_requested_at=NOW + timedelta(seconds=1),
        )
    )
    assert replay == VoicePreparationReservation(first.command_id, True)


def test_same_idempotency_key_rejects_changed_source_cas() -> None:
    service, _repo, _generator, _fallback, _continuation, _events = _service(
        preflight=_preflight(),
    )
    service.create(_request())
    with pytest.raises(IdempotencyConflict, match="reused"):
        service.create(
            replace(
                _request(),
                expected_settings_version=5,
            )
        )


def test_chapter_speakers_then_main_then_supporting_use_stable_order() -> None:
    service, _repo, _generator, _fallback, _continuation, _events = _service(
        targets=(
            _target(BACKGROUND_ID, role_type="main"),
            _target(SUPPORT_ID),
            _target(MAIN_ID, role_type="main"),
        ),
        preflight=_preflight(SUPPORT_ID),
    )
    reservation = service.create(_request())
    command = service.get(novel_id=NOVEL_ID, command_id=reservation.command_id)
    assert tuple(item.character_id for item in command.items) == (
        SUPPORT_ID,
        MAIN_ID,
        BACKGROUND_ID,
    )
    assert command.items[0].chapter_speaker is True


def test_private_uploaded_and_generated_bindings_are_preserved_without_child_jobs() -> None:
    service, _repo, generator, _fallback, continuation, _events = _service(
        targets=(
            _target(MAIN_ID, voice=_voice(ExistingVoiceKind.PRIVATE, usable=True)),
            _target(SUPPORT_ID, voice=_voice(ExistingVoiceKind.UPLOADED, usable=True)),
            _target(BACKGROUND_ID, voice=_voice(ExistingVoiceKind.GENERATED, usable=True)),
        ),
        preflight=_preflight(MAIN_ID),
    )
    command_id = service.create(_request()).command_id
    first = service.advance(novel_id=NOVEL_ID, command_id=command_id)
    assert first.continuation_state is VoicePreparationContinuationState.CREATED
    final = service.advance(novel_id=NOVEL_ID, command_id=command_id)
    assert final.state is VoicePreparationCommandState.READY
    assert all(item.state is VoicePreparationItemState.PRESERVED for item in final.items)
    assert generator.calls == []
    assert len(continuation.calls) == 1


def test_unusable_protected_voice_is_not_replaced_and_blocks_chapter_continuation() -> None:
    service, _repo, generator, fallback, continuation, _events = _service(
        targets=(
            _target(MAIN_ID, voice=_voice(ExistingVoiceKind.UPLOADED, usable=False)),
        ),
        preflight=_preflight(MAIN_ID),
    )
    command_id = service.create(_request()).command_id
    result = service.get(novel_id=NOVEL_ID, command_id=command_id)
    assert result.state is VoicePreparationCommandState.FAILED
    assert result.items[0].state is VoicePreparationItemState.PRESERVED
    assert result.items[0].usable_for_narration is False
    assert generator.calls == []
    assert fallback.calls == []
    assert continuation.calls == []


def test_official_voice_remains_bound_until_generated_voice_is_validated() -> None:
    generator = FakeVoiceGenerator()
    service, _repo, _generator, _fallback, _continuation, _events = _service(
        targets=(_target(MAIN_ID, voice=_voice(ExistingVoiceKind.OFFICIAL, usable=True)),),
        preflight=_preflight(MAIN_ID),
        voice_generator=generator,
    )
    command_id = service.create(_request()).command_id
    active = service.advance(novel_id=NOVEL_ID, command_id=command_id)
    assert active.items[0].state is VoicePreparationItemState.GENERATING
    assert active.items[0].result_voice_version_id is None
    generator.children[CHILD_ID] = VoiceGeneratorChild(
        CHILD_ID,
        VoiceGeneratorChildState.READY_APPLIED,
        profile_id=UUID("30000000-0000-4000-8000-000000000010"),
        voice_version_id=UUID("30000000-0000-4000-8000-000000000011"),
        applied_binding_version=8,
        current_binding_usable=True,
    )
    ready = service.advance(novel_id=NOVEL_ID, command_id=command_id)
    assert ready.items[0].state is VoicePreparationItemState.READY_APPLIED
    assert ready.items[0].applied_binding_version == 8


def test_only_one_voice_generator_child_is_reserved_at_a_time() -> None:
    service, _repo, generator, _fallback, _continuation, _events = _service(
        targets=(_target(MAIN_ID), _target(SUPPORT_ID)),
        preflight=_preflight(MAIN_ID, SUPPORT_ID),
    )
    command_id = service.create(_request()).command_id
    service.advance(novel_id=NOVEL_ID, command_id=command_id)
    service.advance(novel_id=NOVEL_ID, command_id=command_id)
    assert len(generator.calls) == 1
    assert generator.calls[0].idempotency_key.startswith("voice-prepare-character:")


def test_failed_generation_keeps_existing_official_voice_as_visible_fallback() -> None:
    generator = FakeVoiceGenerator()
    fallback = FakeFallback()
    service, _repo, _generator, _fallback, _continuation, _events = _service(
        targets=(_target(MAIN_ID, voice=_voice(ExistingVoiceKind.OFFICIAL, usable=True)),),
        preflight=_preflight(MAIN_ID),
        voice_generator=generator,
        fallback=fallback,
    )
    command_id = service.create(_request()).command_id
    service.advance(novel_id=NOVEL_ID, command_id=command_id)
    generator.children[CHILD_ID] = VoiceGeneratorChild(
        CHILD_ID,
        VoiceGeneratorChildState.FAILED,
        failure_code="upstream-private-code",
    )
    result = service.advance(novel_id=NOVEL_ID, command_id=command_id)
    assert result.items[0].state is VoicePreparationItemState.FALLBACK_OFFICIAL
    assert result.items[0].result_voice_version_id == VERSION_ID
    assert fallback.calls == []


def test_failed_generation_without_voice_uses_official_matching_adapter() -> None:
    generator = FakeVoiceGenerator()
    fallback = FakeFallback()
    service, _repo, _generator, _fallback, _continuation, _events = _service(
        targets=(_target(MAIN_ID),),
        preflight=_preflight(MAIN_ID),
        voice_generator=generator,
        fallback=fallback,
    )
    command_id = service.create(_request()).command_id
    service.advance(novel_id=NOVEL_ID, command_id=command_id)
    generator.children[CHILD_ID] = VoiceGeneratorChild(
        CHILD_ID,
        VoiceGeneratorChildState.FAILED,
    )
    result = service.advance(novel_id=NOVEL_ID, command_id=command_id)
    assert result.items[0].state is VoicePreparationItemState.FALLBACK_OFFICIAL
    assert len(fallback.calls) == 1
    assert fallback.calls[0].expected_binding_version == 0


def test_generator_binding_cas_drift_is_ready_unapplied_and_never_force_applied() -> None:
    generator = FakeVoiceGenerator()
    service, _repo, _generator, fallback, _continuation, _events = _service(
        targets=(_target(MAIN_ID),),
        preflight=_preflight(MAIN_ID),
        voice_generator=generator,
    )
    command_id = service.create(_request()).command_id
    service.advance(novel_id=NOVEL_ID, command_id=command_id)
    generator.children[CHILD_ID] = VoiceGeneratorChild(
        CHILD_ID,
        VoiceGeneratorChildState.READY_UNAPPLIED,
        profile_id=PROFILE_ID,
        voice_version_id=VERSION_ID,
        current_binding_usable=True,
    )
    result = service.advance(novel_id=NOVEL_ID, command_id=command_id)
    assert result.items[0].state is VoicePreparationItemState.READY_UNAPPLIED
    assert result.items[0].failure_code == VOICE_PREPARATION_BINDING_DRIFTED
    assert fallback.calls == []


def test_chapter_continuation_does_not_wait_for_background_characters() -> None:
    service, _repo, generator, _fallback, continuation, _events = _service(
        targets=(
            _target(MAIN_ID, voice=_voice(ExistingVoiceKind.GENERATED, usable=True)),
            _target(BACKGROUND_ID),
        ),
        preflight=_preflight(MAIN_ID),
    )
    command_id = service.create(_request()).command_id
    continued = service.advance(novel_id=NOVEL_ID, command_id=command_id)
    assert continued.continuation_state is VoicePreparationContinuationState.CREATED
    assert continued.narration_request_id == REQUEST_ID
    assert continued.background_remaining == 1
    assert generator.calls == []
    assert len(continuation.calls) == 1
    assert continuation.calls[0].speaker_digest == _preflight(MAIN_ID).speaker_digest
    service.advance(novel_id=NOVEL_ID, command_id=command_id)
    assert len(generator.calls) == 1


def test_lost_continuation_response_replays_same_request_after_fence_expiry() -> None:
    clock = MutableClock()
    repo = MemoryRepository()
    continuation = FakeContinuation()
    service, _repo, _generator, _fallback, _continuation, _events = _service(
        targets=(),
        preflight=_preflight(),
        repository=repo,
        continuation=continuation,
        clock=clock,
    )
    command_id = service.create(_request()).command_id
    # reserved -> preparing succeeds, continuation claim succeeds, but the
    # publication CAS is lost as though the process died after the response.
    original_compare = repo.compare_and_swap
    save_count = 0

    def lose_third_save(
        *,
        expected_aggregate_version: int,
        command: VoicePreparationCommand,
    ) -> bool:
        nonlocal save_count
        save_count += 1
        if save_count == 3:
            return False
        return original_compare(
            expected_aggregate_version=expected_aggregate_version,
            command=command,
        )

    repo.compare_and_swap = lose_third_save  # type: ignore[method-assign]
    first = service.advance(novel_id=NOVEL_ID, command_id=command_id)
    assert first.continuation_state is VoicePreparationContinuationState.CREATING
    assert len(continuation.calls) == 1
    same_lease = service.advance(novel_id=NOVEL_ID, command_id=command_id)
    assert same_lease.continuation_state is VoicePreparationContinuationState.CREATING
    assert len(continuation.calls) == 1
    clock.value += VOICE_PREPARATION_CONTINUATION_LEASE + timedelta(seconds=1)
    recovered = service.advance(novel_id=NOVEL_ID, command_id=command_id)
    assert recovered.continuation_state is VoicePreparationContinuationState.CREATED
    assert recovered.narration_request_id == REQUEST_ID
    assert len(continuation.calls) == 2
    assert len(continuation.requests_by_key) == 1
    assert continuation.calls[0].idempotency_key == continuation.calls[1].idempotency_key
    assert continuation.calls[0].preparation_fence == continuation.calls[1].preparation_fence
    assert continuation.calls[0].preparation_attempt == 1
    assert continuation.calls[1].preparation_attempt == 2


def test_source_drift_supersedes_parent_without_a_narration_request() -> None:
    continuation = FakeContinuation()
    continuation.result = NarrationContinuationResult(ContinuationResultState.SOURCE_DRIFTED)
    service, _repo, _generator, _fallback, _continuation, _events = _service(
        preflight=_preflight(),
        continuation=continuation,
    )
    command_id = service.create(_request()).command_id
    result = service.advance(novel_id=NOVEL_ID, command_id=command_id)
    assert result.state is VoicePreparationCommandState.SUPERSEDED
    assert result.failure_code == VOICE_PREPARATION_SOURCE_DRIFTED
    assert result.narration_request_id is None


def test_cancel_stops_new_targets_but_does_not_revoke_created_narration() -> None:
    service, _repo, generator, _fallback, _continuation, _events = _service(
        targets=(
            _target(MAIN_ID, voice=_voice(ExistingVoiceKind.GENERATED, usable=True)),
            _target(BACKGROUND_ID),
        ),
        preflight=_preflight(MAIN_ID),
    )
    command_id = service.create(_request()).command_id
    service.advance(novel_id=NOVEL_ID, command_id=command_id)
    service.advance(novel_id=NOVEL_ID, command_id=command_id)
    cancelled = service.cancel(novel_id=NOVEL_ID, command_id=command_id)
    assert cancelled.state is VoicePreparationCommandState.CANCELLED
    assert cancelled.continuation_state is VoicePreparationContinuationState.CREATED
    assert cancelled.narration_request_id == REQUEST_ID
    assert generator.cancelled == [CHILD_ID]
    assert cancelled.items[1].state is VoicePreparationItemState.CANCELLED


def test_whole_book_command_has_no_preflight_or_continuation() -> None:
    service, _repo, generator, _fallback, continuation, events = _service(
        targets=(_target(MAIN_ID),),
    )
    command_id = service.create(_request(chapter=False)).command_id
    result = service.advance(novel_id=NOVEL_ID, command_id=command_id)
    assert result.continuation_state is VoicePreparationContinuationState.NOT_APPLICABLE
    assert continuation.calls == []
    assert events == ["inventory"]
    assert len(generator.calls) == 1


def test_retry_creates_one_idempotent_successor_from_server_refreshed_request() -> None:
    generator = FakeVoiceGenerator()
    fallback = FakeFallback()
    fallback.result = OfficialFallbackResult(OfficialFallbackState.FAILED)
    service, repo, _generator, _fallback, _continuation, _events = _service(
        targets=(_target(MAIN_ID),),
        voice_generator=generator,
        fallback=fallback,
    )
    command_id = service.create(_request(chapter=False)).command_id
    service.advance(novel_id=NOVEL_ID, command_id=command_id)
    generator.children[CHILD_ID] = VoiceGeneratorChild(
        CHILD_ID,
        VoiceGeneratorChildState.FAILED,
        runtime_unavailable=True,
    )
    failed = service.advance(novel_id=NOVEL_ID, command_id=command_id)
    assert failed.state is VoicePreparationCommandState.FAILED
    first = service.retry(
        novel_id=NOVEL_ID,
        command_id=command_id,
        refreshed_request=_request(chapter=False, key="ignored-key-1"),
    )
    second = service.retry(
        novel_id=NOVEL_ID,
        command_id=command_id,
        refreshed_request=_request(chapter=False, key="ignored-key-2"),
    )
    assert first.replayed is False
    assert second == VoicePreparationReservation(first.command_id, True)
    assert len(repo.rows) == 2


def test_unsaved_or_archived_characters_never_enter_dedicated_generation() -> None:
    service, _repo, generator, _fallback, _continuation, _events = _service(
        targets=(
            _target(MAIN_ID, saved=False),
            _target(SUPPORT_ID, active=False),
        ),
        preflight=_preflight(MAIN_ID, SUPPORT_ID),
    )
    command_id = service.create(_request()).command_id
    result = service.advance(novel_id=NOVEL_ID, command_id=command_id)
    assert result.items == ()
    assert result.chapter_ready is True
    assert generator.calls == []
    assert result.continuation_state is VoicePreparationContinuationState.CREATED


def test_request_rejects_partial_chapter_cas_and_changed_mode() -> None:
    with pytest.raises(ValueError, match="complete draft/settings CAS"):
        VoicePreparationCreateRequest(
            novel_id=NOVEL_ID,
            idempotency_key="voice-prepare-key",
            actor="local-owner",
            explicit_requested_at=NOW,
            document_id=DOCUMENT_ID,
        )
    with pytest.raises(ValueError, match="request changed"):
        replace(_request(), mode="generate_everything")
