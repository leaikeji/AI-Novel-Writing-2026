from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from dataclasses import replace
from unittest.mock import AsyncMock, Mock
from types import SimpleNamespace
from uuid import UUID

import pytest

from backend.narration.contracts import (
    ModelFingerprint,
    NarrationRequestScope,
    SynthesisRequest,
    SynthesisResult,
)
from backend.narration.jobs import JobFence, JobFenceError, JobLease
from backend.narration.voice_generator_processor import (
    VoiceGeneratorProcessor,
    VoiceGeneratorWorkItem,
    _require_production_nano_result,
    _transport_instruction_digest,
)
from backend.narration.voice_generator_runtime import (
    EXPECTED_RUNTIME_FINGERPRINT,
    EXPECTED_RUNTIME_IDENTITY,
    HostGenerationReceipt,
    HostGenerationStatus,
    VoiceGeneratorHostHealth,
    VoiceGeneratorHostRequest,
    VoiceGeneratorRuntimeError,
)
from backend.narration.voice_generator_service import VoiceGeneratorCommandState
from backend.narration.runtime import (
    EXPECTED_PRODUCTION_MODEL_FINGERPRINT,
    SidecarRuntimeError,
)
from backend.narration.audio_pipeline import AudioQualityError
from tests.narration.digest_fixtures import TEST_DIGEST_KEYRING


def _lease() -> JobLease:
    now = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    return JobLease(
        fence=JobFence(
            job_id=UUID("cf572b95-2b37-48d0-8bed-e82df99778de"),
            attempt_id=UUID("ce870ebe-dd01-4849-88b8-b21a63e1a18f"),
            lease_token=UUID("dc1bd8e9-a303-4351-9f06-4c22dc2c93ec"),
            lease_generation=1,
        ),
        attempt_number=1,
        retry_kind="initial",
        lease_owner="voice-generator-test",
        lease_until=now + timedelta(minutes=2),
    )


def test_transport_instruction_digest_is_plain_sha256_not_durable_hmac() -> None:
    instruction = "声音克制清晰，语速沉稳。"

    assert _transport_instruction_digest(instruction) == hashlib.sha256(
        instruction.encode("utf-8")
    ).hexdigest()


def _work() -> VoiceGeneratorWorkItem:
    lease = _lease()
    return VoiceGeneratorWorkItem(
        lease=lease,
        command_id=UUID("d23fbdf5-b047-4f26-8046-f42dac6d699c"),
        novel_id=UUID("e0b84831-e448-482b-8d71-75b8d09d5153"),
        character_id=UUID("7528868b-3c78-4bcb-85df-f292e1da48ed"),
        host_request=VoiceGeneratorHostRequest(
            request_id=UUID("0ca3e097-ece7-430f-aa6e-59743a7fca84"),
            instruction="声音克制清晰，语速沉稳。",
            instruction_digest=hashlib.sha256(
                "声音克制清晰，语速沉稳。".encode("utf-8")
            ).hexdigest(),
            language="zh-CN",
            seed=104729,
        ),
        draft_fingerprint=hashlib.sha256(b"draft").hexdigest(),
        parameters_digest=hashlib.sha256(b"parameters").hexdigest(),
        language="zh-CN",
        seed=104729,
    )


def _request(work: VoiceGeneratorWorkItem) -> SynthesisRequest:
    return SynthesisRequest(
        request_id=work.lease.fence.attempt_id,
        scope=NarrationRequestScope.fixed_local(),
        text="雨停之后，旧钟楼的回声依然清晰。",
        voice="uploaded-reference",
        seed=work.seed,
        sample_mode="full",
        max_new_frames=375,
    )


def _result(request: SynthesisRequest) -> SynthesisResult:
    audio = b"RIFF-valid-test-audio"
    return SynthesisResult(
        request_id=request.request_id,
        audio_bytes=audio,
        actual_output_sha256=hashlib.sha256(audio).hexdigest(),
        sample_rate_hz=48_000,
        channels=2,
        sample_width_bytes=2,
        model_fingerprint=ModelFingerprint(
            adapter_contract_version="moss-nano-tts-adapter/1",
            model_name="test-nano",
            model_revision="test-revision",
            artifact_tree_sha256="a" * 64,
            runtime_name="onnxruntime",
            runtime_version="1",
            execution_backend="cpu",
            protocol_version="sidecar/1",
            deployment_topology="single-sidecar",
            parameters={},
        ),
        worker_generation=1,
    )


class _Repository:
    def __init__(self, states: list[str] | None = None) -> None:
        self.states = list(states or ["running"])
        self.heartbeats = 0
        self.cancelled = 0
        self.failures: list[tuple[VoiceGeneratorCommandState, str]] = []
        self.host_terminals: list[HostGenerationReceipt] = []

    def load_and_mark_generating(self, lease: JobLease) -> VoiceGeneratorWorkItem:
        assert lease == _lease()
        return _work()

    def heartbeat_and_job_state(self, work: VoiceGeneratorWorkItem) -> str:
        self.heartbeats += 1
        return self.states.pop(0) if len(self.states) > 1 else self.states[0]

    def acknowledge_cancel(self, work: VoiceGeneratorWorkItem) -> None:
        self.cancelled += 1

    def record_host_terminal(
        self, work: VoiceGeneratorWorkItem, receipt: HostGenerationReceipt
    ) -> None:
        self.host_terminals.append(receipt)

    def fail(
        self,
        work: VoiceGeneratorWorkItem,
        *,
        state: VoiceGeneratorCommandState,
        failure_code: str,
    ) -> None:
        self.failures.append((state, failure_code))


class _Nano:
    def __init__(
        self,
        *,
        delay: float = 0.0,
        release_delay: float = 0.0,
        release_error: bool = False,
    ) -> None:
        self.delay = delay
        self.release_delay = release_delay
        self.release_error = release_error
        self.cancel_calls = 0
        self.cancelled = asyncio.Event()

    async def release_model_for_heavy_runtime(self) -> None:
        if self.release_delay:
            await asyncio.sleep(self.release_delay)
        if self.release_error:
            raise SidecarRuntimeError("SIDECAR_UNAVAILABLE", "unavailable")

    async def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        if self.delay:
            try:
                await asyncio.wait_for(self.cancelled.wait(), timeout=self.delay)
            except TimeoutError:
                pass
        return _result(request)

    async def cancel(self, request_id: UUID) -> object:
        self.cancel_calls += 1
        self.cancelled.set()
        return object()


def _processor(repository: _Repository, nano: _Nano, *, poll: float = 0.01):
    return VoiceGeneratorProcessor(
        repository=repository,  # type: ignore[arg-type]
        host=object(),  # type: ignore[arg-type]
        nano_adapter=nano,  # type: ignore[arg-type]
        storage=object(),  # type: ignore[arg-type]
        digest_keyring=object(),  # type: ignore[arg-type]
        poll_seconds=poll,
    )


class _FailedHost:
    async def health(self) -> VoiceGeneratorHostHealth:
        return VoiceGeneratorHostHealth(
            ready=True,
            status="ready",
            runtime_identity=EXPECTED_RUNTIME_IDENTITY,
            runtime_fingerprint=EXPECTED_RUNTIME_FINGERPRINT,
            active_request_id=None,
        )

    async def create(
        self, request: VoiceGeneratorHostRequest
    ) -> HostGenerationReceipt:
        return HostGenerationReceipt.from_wire(
            {
                "protocol_version": "moss-voice-generator-host/1",
                "request_id": str(request.request_id),
                "request_digest": request.request_digest,
                "status": "failed",
                "terminal": True,
                "cancellable": False,
                "retryable": True,
                "failure_code": "GENERATOR_PROCESS_FAILED",
                "runtime_identity": EXPECTED_RUNTIME_IDENTITY.wire_payload(),
                "runtime_fingerprint": EXPECTED_RUNTIME_FINGERPRINT,
                "token_sha256": None,
                "audio_sha256": None,
                "audio_size_bytes": None,
                "memory_summary": None,
                "started_at": "2026-08-30T08:00:00Z",
                "completed_at": "2026-08-30T08:00:01Z",
            }
        )


@pytest.mark.asyncio
async def test_nano_validation_heartbeats_while_synthesis_is_running() -> None:
    repository = _Repository()
    nano = _Nano(delay=0.15)
    work = _work()

    result = await _processor(repository, nano, poll=0.1)._validate_with_nano(
        work, _request(work)
    )

    assert result.request_id == work.lease.fence.attempt_id
    assert repository.heartbeats >= 1
    assert nano.cancel_calls == 0


@pytest.mark.asyncio
async def test_nano_release_heartbeats_while_sidecar_process_is_replaced() -> None:
    repository = _Repository()
    nano = _Nano(release_delay=0.15)
    work = _work()

    await _processor(repository, nano, poll=0.1)._release_nano_for_heavy_runtime(
        work
    )

    assert repository.heartbeats >= 2


@pytest.mark.asyncio
async def test_nano_validation_propagates_durable_cancel_and_acknowledges_it() -> None:
    repository = _Repository(["cancel_requested"])
    nano = _Nano(delay=5)
    work = _work()

    with pytest.raises(JobFenceError):
        await _processor(repository, nano, poll=0.1)._validate_with_nano(
            work, _request(work)
        )

    assert nano.cancel_calls == 1
    assert repository.cancelled == 1


@pytest.mark.asyncio
async def test_heavy_runtime_release_failure_is_not_reported_as_generation_failure() -> None:
    repository = _Repository()
    nano = _Nano(release_error=True)

    await _processor(repository, nano).process(_lease())

    assert repository.failures == [
        (
            VoiceGeneratorCommandState.FAILED_RUNTIME_UNAVAILABLE,
            "SIDECAR_UNAVAILABLE",
        )
    ]


def test_nano_validation_rejects_a_success_shaped_but_unpinned_model() -> None:
    request = _request(_work())
    with pytest.raises(SidecarRuntimeError) as failure:
        _require_production_nano_result(_result(request))
    assert failure.value.code == "MODEL_FINGERPRINT_MISMATCH"

    audio = b"RIFF-production-test-audio"
    result = SynthesisResult(
        request_id=request.request_id,
        audio_bytes=audio,
        actual_output_sha256=hashlib.sha256(audio).hexdigest(),
        sample_rate_hz=48_000,
        channels=2,
        sample_width_bytes=2,
        model_fingerprint=EXPECTED_PRODUCTION_MODEL_FINGERPRINT,
        worker_generation=1,
    )
    assert _require_production_nano_result(result) == (
        "3c76f3e9e1381699c5555287cf66eeb023632d0c3ee94adc6d8ae1b1d455fd7d"
    )


@pytest.mark.asyncio
async def test_terminal_host_failure_is_persisted_before_it_is_projected() -> None:
    repository = _Repository()
    processor = VoiceGeneratorProcessor(
        repository=repository,  # type: ignore[arg-type]
        host=_FailedHost(),  # type: ignore[arg-type]
        nano_adapter=_Nano(),  # type: ignore[arg-type]
        storage=object(),  # type: ignore[arg-type]
        digest_keyring=object(),  # type: ignore[arg-type]
    )

    with pytest.raises(Exception) as failure:
        await processor._generate(_work())

    assert getattr(failure.value, "code", None) == "GENERATOR_PROCESS_FAILED"
    assert len(repository.host_terminals) == 1
    assert repository.host_terminals[0].status.value == "failed"


async def _polling_host(errors: list[Exception]):
    terminal = await _FailedHost().create(_work().host_request)
    active = replace(
        terminal, status=HostGenerationStatus.GENERATING,
        terminal=False, cancellable=True, retryable=False,
        failure_code=None, completed_at=None,
    )
    host = _FailedHost()
    host.create = AsyncMock(return_value=active)
    host.get = AsyncMock(side_effect=[*errors, terminal])
    host.cancel = AsyncMock()
    return host


@pytest.mark.asyncio
async def test_missing_poll_responses_retry_same_native_request_with_job_heartbeats() -> None:
    repository = _Repository()
    processor = _processor(repository, _Nano(), poll=0)
    host = await _polling_host([
        VoiceGeneratorRuntimeError("HOST_UNREACHABLE", "timeout", retryable=True),
        VoiceGeneratorRuntimeError("HOST_UNREACHABLE", "timeout", retryable=True),
    ])
    processor._host = host
    with pytest.raises(VoiceGeneratorRuntimeError) as failure:
        await processor._generate(_work())
    assert failure.value.code == "GENERATOR_PROCESS_FAILED"
    assert host.create.await_count == 1
    assert host.get.await_count == 3
    assert all(call.args == (_work().host_request,) for call in host.get.await_args_list)
    assert repository.heartbeats == 3
    assert len(repository.host_terminals) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("code,retryable,count", [
    ("HOST_UNREACHABLE", True, 3),
    ("HOST_UNREACHABLE", False, 1),
    ("RESPONSE_SIZE_INVALID", True, 1),
])
async def test_host_poll_recovery_is_bounded_and_never_retries_invalid_evidence(
    code: str, retryable: bool, count: int,
) -> None:
    repository = _Repository()
    processor = _processor(repository, _Nano(), poll=0)
    host = await _polling_host([
        VoiceGeneratorRuntimeError(code, "unavailable", retryable=retryable)
        for _ in range(4)
    ])
    processor._host = host
    with pytest.raises(VoiceGeneratorRuntimeError) as failure:
        await processor._generate(_work())
    assert failure.value.code == code
    assert host.get.await_count == count
    assert host.create.await_count == 1
    assert repository.host_terminals == []


@pytest.mark.asyncio
async def test_lost_job_fence_stops_poll_recovery_before_another_host_read() -> None:
    repository = _Repository(["running", "failed"])
    processor = _processor(repository, _Nano(), poll=0)
    host = await _polling_host([
        VoiceGeneratorRuntimeError("HOST_UNREACHABLE", "timeout", retryable=True),
    ])
    processor._host = host
    with pytest.raises(JobFenceError):
        await processor._generate(_work())
    assert host.get.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("stage,expected_state,expected_code", [
    ("duration", "failed_nano_validation", "NANO_SHORT_CHINESE_DURATION_IMPLAUSIBLE"),
    ("unknown_audio", "failed_nano_validation", "NANO_AUDIO_VALIDATION_UNKNOWN"),
    ("storage", "failed_storage", "VOICE_GENERATOR_STORAGE_FAILED"),
    ("publication", "failed_storage", "VOICE_GENERATOR_PUBLICATION_FAILED"),
])
async def test_validation_and_publication_failures_keep_bounded_stage_evidence(
    monkeypatch: pytest.MonkeyPatch, stage: str, expected_state: str, expected_code: str
) -> None:
    repository = _Repository()
    repository.advance = Mock()
    repository.publish = Mock(side_effect=RuntimeError("private SQL statement"))
    processor = _processor(repository, _Nano())
    processor._digest_keyring = TEST_DIGEST_KEYRING
    processor._generate = AsyncMock(return_value=SimpleNamespace(
        audio_bytes=b"reference", audio_digest=hashlib.sha256(b"reference").hexdigest(),
    ))
    processor._storage = SimpleNamespace(publish_media=Mock(
        side_effect=[object(), OSError("private storage path")] if stage == "storage" else None,
        return_value=object(),
    ))
    monkeypatch.setattr(
        "backend.narration.voice_generator_processor._require_production_nano_result",
        lambda _result: "b" * 64,
    )
    processing = Mock(return_value=SimpleNamespace(
        wav_bytes=b"validation", actual_sha256="c" * 64,
        duration_ms=4000, sample_rate_hz=48000, channels=2,
    ))
    if stage in {"duration", "unknown_audio"}:
        processing.side_effect = AudioQualityError(
            "synthesis WAV duration is implausible for short Chinese text"
            if stage == "duration" else "private novel text and token"
        )
    monkeypatch.setattr("backend.narration.voice_generator_processor.process_synthesis_wav", processing)

    await processor.process(_lease())

    assert repository.failures == [(VoiceGeneratorCommandState(expected_state), expected_code)]
    assert repository.publish.call_count == (1 if stage == "publication" else 0)
    assert "private" not in repr(repository.failures)
