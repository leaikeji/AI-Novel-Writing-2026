from __future__ import annotations

from array import array
import hashlib
import io
from uuid import UUID
import wave

import pytest

from backend.narration.voice_generator_runtime import (
    EXPECTED_RUNTIME_FINGERPRINT,
    EXPECTED_RUNTIME_IDENTITY,
    HostGenerationReceipt,
    VoiceGeneratorAudioResult,
    VoiceGeneratorHostRequest,
    VoiceGeneratorRuntimeError,
    inspect_generated_wav,
)
from backend.narration.voice_generator_service import (
    VoiceGeneratorCommandState,
    command_state_for_host_receipt,
    ensure_command_transition,
    state_view,
    terminal_state_for_runtime_error,
    validate_runtime_completion,
)


REQUEST_ID = UUID("7bcd9011-e5c0-4f60-a8ec-138e2eb49bb7")
INSTRUCTION = "声音克制、清晰，节奏沉稳。"
INSTRUCTION_DIGEST = hashlib.sha256(INSTRUCTION.encode("utf-8")).hexdigest()


def _request() -> VoiceGeneratorHostRequest:
    return VoiceGeneratorHostRequest(
        request_id=REQUEST_ID,
        instruction=INSTRUCTION,
        instruction_digest=INSTRUCTION_DIGEST,
        language="zh-CN",
        seed=104729,
    )


def _audio() -> bytes:
    samples = array("h")
    for index in range(48_000 * 3):
        sample = 2_500 if (index // 60) % 2 else -2_500
        samples.extend((sample, sample))
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(2)
        target.setsampwidth(2)
        target.setframerate(48_000)
        target.writeframes(samples.tobytes())
    return output.getvalue()


def _receipt(request: VoiceGeneratorHostRequest, audio: bytes) -> HostGenerationReceipt:
    digest = hashlib.sha256(audio).hexdigest()
    return HostGenerationReceipt.from_wire(
        {
            "protocol_version": "moss-voice-generator-host/1",
            "request_id": str(request.request_id),
            "request_digest": request.request_digest,
            "status": "completed",
            "terminal": True,
            "cancellable": False,
            "retryable": False,
            "failure_code": None,
            "runtime_identity": EXPECTED_RUNTIME_IDENTITY.wire_payload(),
            "runtime_fingerprint": EXPECTED_RUNTIME_FINGERPRINT,
            "token_sha256": hashlib.sha256(b"tokens").hexdigest(),
            "audio_sha256": digest,
            "audio_size_bytes": len(audio),
            "memory_summary": {
                "minimum_available_memory_bytes": 1_900_000_000,
                "maximum_swap_delta_bytes": 500_000_000,
                "maximum_pageouts_per_second": 0,
                "critical_pressure_milliseconds": 0,
                "stage_pid_overlap": False,
                "recovered_within_60_seconds": True,
            },
            "started_at": "2026-08-30T08:00:00Z",
            "completed_at": "2026-08-30T08:01:00Z",
        }
    )


def test_state_machine_is_monotonic_and_exposes_derived_flags() -> None:
    route = [
        VoiceGeneratorCommandState.QUEUED,
        VoiceGeneratorCommandState.ANALYZING_CHARACTER,
        VoiceGeneratorCommandState.WAITING_FOR_HEAVY_RUNTIME,
        VoiceGeneratorCommandState.GENERATING_VOICE,
        VoiceGeneratorCommandState.UNLOADING_VOICE_GENERATOR,
        VoiceGeneratorCommandState.VALIDATING_WITH_NANO,
        VoiceGeneratorCommandState.READY_UNAPPLIED,
        VoiceGeneratorCommandState.READY_APPLIED,
    ]
    for current, target in zip(route, route[1:]):
        assert ensure_command_transition(current, target) is target
    assert state_view(VoiceGeneratorCommandState.GENERATING_VOICE).progress_current == 3
    assert state_view(VoiceGeneratorCommandState.GENERATING_VOICE).cancellable is True
    assert state_view(VoiceGeneratorCommandState.READY_APPLIED).terminal is True
    assert state_view(VoiceGeneratorCommandState.FAILED_GENERATION).retryable is True
    with pytest.raises(ValueError):
        ensure_command_transition(
            VoiceGeneratorCommandState.READY_APPLIED,
            VoiceGeneratorCommandState.GENERATING_VOICE,
        )


def test_active_commands_can_cancel_or_supersede_without_skipping_forward_states() -> None:
    assert ensure_command_transition(
        VoiceGeneratorCommandState.GENERATING_VOICE,
        VoiceGeneratorCommandState.CANCELLED,
    ) is VoiceGeneratorCommandState.CANCELLED
    assert ensure_command_transition(
        VoiceGeneratorCommandState.WAITING_FOR_HEAVY_RUNTIME,
        VoiceGeneratorCommandState.SUPERSEDED,
    ) is VoiceGeneratorCommandState.SUPERSEDED
    with pytest.raises(ValueError):
        ensure_command_transition(
            VoiceGeneratorCommandState.QUEUED,
            VoiceGeneratorCommandState.GENERATING_VOICE,
        )


def test_runtime_completion_closes_request_receipt_audio_and_returns_path_free_evidence() -> None:
    request = _request()
    payload = _audio()
    digest = hashlib.sha256(payload).hexdigest()
    receipt = _receipt(request, payload)
    audio = VoiceGeneratorAudioResult(
        request_id=request.request_id,
        audio_bytes=payload,
        audio_sha256=digest,
        runtime_fingerprint=EXPECTED_RUNTIME_FINGERPRINT,
        metrics=inspect_generated_wav(payload),
    )
    result = validate_runtime_completion(request, receipt, audio)
    assert result.request_id == request.request_id
    assert result.instruction_digest == INSTRUCTION_DIGEST
    assert result.audio_digest == digest
    assert result.result_classification == "success"
    assert result.exit_reason_code == "COMPLETED"
    assert "instruction" not in result.memory_summary
    assert "path" not in result.memory_summary
    assert "克制" not in repr(result)
    assert command_state_for_host_receipt(receipt) is VoiceGeneratorCommandState.VALIDATING_WITH_NANO


def test_runtime_completion_rejects_audio_or_request_identity_drift() -> None:
    request = _request()
    payload = _audio()
    receipt = _receipt(request, payload)
    audio = VoiceGeneratorAudioResult(
        request_id=UUID("1dc1d9da-a01d-4ec9-bced-f21a12e58756"),
        audio_bytes=payload,
        audio_sha256=hashlib.sha256(payload).hexdigest(),
        runtime_fingerprint=EXPECTED_RUNTIME_FINGERPRINT,
        metrics=inspect_generated_wav(payload),
    )
    with pytest.raises(VoiceGeneratorRuntimeError) as failure:
        validate_runtime_completion(request, receipt, audio)
    assert failure.value.code == "RUNTIME_RESULT_IDENTITY_MISMATCH"


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("HOST_UNREACHABLE", VoiceGeneratorCommandState.FAILED_RUNTIME_UNAVAILABLE),
        ("MEMORY_PRESSURE_CRITICAL", VoiceGeneratorCommandState.FAILED_MEMORY_SAFETY),
        ("AUDIO_FORMAT_DRIFT", VoiceGeneratorCommandState.FAILED_AUDIO_VALIDATION),
        ("TOKEN_CONTRACT_MISMATCH", VoiceGeneratorCommandState.FAILED_GENERATION),
        ("GENERATOR_PROCESS_FAILED", VoiceGeneratorCommandState.FAILED_GENERATION),
        ("USER_CANCELLED", VoiceGeneratorCommandState.CANCELLED),
    ],
)
def test_runtime_failures_map_to_stable_product_terminal_states(
    code: str,
    expected: VoiceGeneratorCommandState,
) -> None:
    error = VoiceGeneratorRuntimeError(code, "redacted")
    assert terminal_state_for_runtime_error(error) is expected
