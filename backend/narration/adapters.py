"""Public adapter abstractions and fail-closed test/disabled implementations."""

from __future__ import annotations

import hashlib
import io
import wave
from abc import ABC, abstractmethod
from dataclasses import replace
from typing import Final
from uuid import UUID

from .contracts import (
    AdapterCapabilities,
    AdapterHealth,
    AdapterHealthStatus,
    AdapterKind,
    CancelDisposition,
    CancellationGranularity,
    MOSS_NANO_ADAPTER_CONTRACT_VERSION,
    ModelFingerprint,
    SynthesisRequest,
    SynthesisResult,
    VOICE_DESIGN_ADAPTER_CONTRACT_VERSION,
    VoiceDesignRequest,
    VoiceDesignResult,
)
from .fingerprints import capabilities_fingerprint, model_fingerprint_sha256


class AdapterUnavailableError(RuntimeError):
    """Raised when a disabled or unhealthy adapter is invoked."""


MOSS_NANO_SIDECAR_CONTRACT_CAPABILITIES: Final = AdapterCapabilities(
    adapter_kind=AdapterKind.MOSS_NANO_TTS,
    supports_warmup=True,
    supports_synthesis=True,
    supports_cancel=True,
    cancellation_granularity=CancellationGranularity.SEGMENT_BOUNDARY,
    supports_reference_audio=True,
    supports_streaming_response_bytes=True,
    supports_voice_design=False,
    max_inference_concurrency=1,
    product_visible=False,
    production_ready=False,
    is_test_double=False,
)

VOICE_DESIGN_NO_GO_CAPABILITIES: Final = AdapterCapabilities(
    adapter_kind=AdapterKind.VOICE_DESIGN,
    supports_warmup=False,
    supports_synthesis=False,
    supports_cancel=False,
    cancellation_granularity=CancellationGranularity.NONE,
    supports_reference_audio=False,
    supports_streaming_response_bytes=False,
    supports_voice_design=False,
    max_inference_concurrency=0,
    product_visible=False,
    production_ready=False,
    is_test_double=False,
)


class MossNanoTTSAdapter(ABC):
    """Topology-independent Nano TTS contract consumed by domain services."""

    @property
    @abstractmethod
    def capabilities(self) -> AdapterCapabilities: ...

    @abstractmethod
    async def health(self) -> AdapterHealth: ...

    @abstractmethod
    async def model_fingerprint(self) -> ModelFingerprint | None: ...

    @abstractmethod
    async def warmup(self) -> AdapterHealth: ...

    @abstractmethod
    async def synthesize(self, request: SynthesisRequest) -> SynthesisResult: ...

    @abstractmethod
    async def cancel(self, request_id: UUID) -> CancelDisposition: ...


class VoiceDesignAdapter(ABC):
    """Optional voice-design boundary; current product capability is disabled."""

    @property
    @abstractmethod
    def capabilities(self) -> AdapterCapabilities: ...

    @abstractmethod
    async def health(self) -> AdapterHealth: ...

    @abstractmethod
    async def model_fingerprint(self) -> ModelFingerprint | None: ...

    @abstractmethod
    async def warmup(self) -> AdapterHealth: ...

    @abstractmethod
    async def design_voice(self, request: VoiceDesignRequest) -> VoiceDesignResult: ...

    @abstractmethod
    async def cancel(self, request_id: UUID) -> CancelDisposition: ...


def _fake_model_fingerprint(adapter_contract_version: str, model_name: str) -> ModelFingerprint:
    return ModelFingerprint(
        adapter_contract_version=adapter_contract_version,
        model_name=model_name,
        model_revision="test-double/1",
        artifact_tree_sha256=hashlib.sha256(model_name.encode("utf-8")).hexdigest(),
        runtime_name="python-stdlib-fake",
        runtime_version="1",
        execution_backend="deterministic-test-double",
        protocol_version="in-process-fake/1",
        deployment_topology="test-only",
        parameters={"test_double": True},
    )


class FakeMossNanoTTSAdapter(MossNanoTTSAdapter):
    """Deterministic fake that can never be surfaced as a product adapter."""

    def __init__(self) -> None:
        self._capabilities = replace(
            MOSS_NANO_SIDECAR_CONTRACT_CAPABILITIES,
            is_test_double=True,
        )
        self._fingerprint = _fake_model_fingerprint(
            MOSS_NANO_ADAPTER_CONTRACT_VERSION,
            "fake-moss-nano",
        )
        self._cancelled: set[UUID] = set()
        self.requests: list[SynthesisRequest] = []

    @property
    def capabilities(self) -> AdapterCapabilities:
        return self._capabilities

    async def health(self) -> AdapterHealth:
        return AdapterHealth(
            status=AdapterHealthStatus.HEALTHY,
            capabilities_sha256=capabilities_fingerprint(self.capabilities),
            model_fingerprint_sha256=model_fingerprint_sha256(self._fingerprint),
        )

    async def model_fingerprint(self) -> ModelFingerprint:
        return self._fingerprint

    async def warmup(self) -> AdapterHealth:
        return await self.health()

    async def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        request.scope.ensure_fixed_local()
        if request.request_id in self._cancelled:
            raise AdapterUnavailableError("request was cancelled before fake synthesis")
        self.requests.append(request)
        audio_bytes = _deterministic_wav_bytes(
            f"{request.text}\0{request.voice}\0{request.seed}\0{request.sample_mode}"
        )
        return SynthesisResult(
            request_id=request.request_id,
            audio_bytes=audio_bytes,
            actual_output_sha256=hashlib.sha256(audio_bytes).hexdigest(),
            sample_rate_hz=48_000,
            channels=2,
            sample_width_bytes=2,
            model_fingerprint=self._fingerprint,
            worker_generation=1,
        )

    async def cancel(self, request_id: UUID) -> CancelDisposition:
        if request_id in self._cancelled:
            return CancelDisposition.ALREADY_TERMINAL
        self._cancelled.add(request_id)
        return CancelDisposition.REQUESTED


class FakeVoiceDesignAdapter(VoiceDesignAdapter):
    """Test-only voice-design fake; product visibility remains false."""

    def __init__(self) -> None:
        self._capabilities = AdapterCapabilities(
            adapter_kind=AdapterKind.VOICE_DESIGN,
            supports_warmup=True,
            supports_synthesis=False,
            supports_cancel=True,
            cancellation_granularity=CancellationGranularity.SEGMENT_BOUNDARY,
            supports_reference_audio=False,
            supports_streaming_response_bytes=True,
            supports_voice_design=True,
            max_inference_concurrency=1,
            product_visible=False,
            production_ready=False,
            is_test_double=True,
        )
        self._fingerprint = _fake_model_fingerprint(
            VOICE_DESIGN_ADAPTER_CONTRACT_VERSION,
            "fake-voice-design",
        )
        self._cancelled: set[UUID] = set()

    @property
    def capabilities(self) -> AdapterCapabilities:
        return self._capabilities

    async def health(self) -> AdapterHealth:
        return AdapterHealth(
            status=AdapterHealthStatus.HEALTHY,
            capabilities_sha256=capabilities_fingerprint(self.capabilities),
            model_fingerprint_sha256=model_fingerprint_sha256(self._fingerprint),
        )

    async def model_fingerprint(self) -> ModelFingerprint:
        return self._fingerprint

    async def warmup(self) -> AdapterHealth:
        return await self.health()

    async def design_voice(self, request: VoiceDesignRequest) -> VoiceDesignResult:
        request.scope.ensure_fixed_local()
        if request.request_id in self._cancelled:
            raise AdapterUnavailableError("request was cancelled before fake voice design")
        audio_bytes = _deterministic_wav_bytes(
            f"{request.description}\0{request.preview_text}\0{request.seed}"
        )
        return VoiceDesignResult(
            request_id=request.request_id,
            candidate_audio_bytes=audio_bytes,
            actual_output_sha256=hashlib.sha256(audio_bytes).hexdigest(),
            model_fingerprint=self._fingerprint,
        )

    async def cancel(self, request_id: UUID) -> CancelDisposition:
        if request_id in self._cancelled:
            return CancelDisposition.ALREADY_TERMINAL
        self._cancelled.add(request_id)
        return CancelDisposition.REQUESTED


class DisabledVoiceDesignAdapter(VoiceDesignAdapter):
    """Fail-closed implementation for the current VoiceGenerator NO-GO."""

    REASON_CODE = "VOICE_GENERATOR_NO_GO"

    def __init__(self) -> None:
        self._capabilities = VOICE_DESIGN_NO_GO_CAPABILITIES

    @property
    def capabilities(self) -> AdapterCapabilities:
        return self._capabilities

    async def health(self) -> AdapterHealth:
        return AdapterHealth(
            status=AdapterHealthStatus.DISABLED,
            capabilities_sha256=capabilities_fingerprint(self.capabilities),
            model_fingerprint_sha256=None,
            reason_code=self.REASON_CODE,
        )

    async def model_fingerprint(self) -> None:
        return None

    async def warmup(self) -> AdapterHealth:
        return await self.health()

    async def design_voice(self, request: VoiceDesignRequest) -> VoiceDesignResult:
        del request
        raise AdapterUnavailableError(self.REASON_CODE)

    async def cancel(self, request_id: UUID) -> CancelDisposition:
        del request_id
        return CancelDisposition.UNSUPPORTED


def _deterministic_wav_bytes(key: str) -> bytes:
    """Return a tiny valid 48 kHz stereo PCM WAV derived from a test key."""

    digest = hashlib.sha256(key.encode("utf-8")).digest()
    samples = bytearray()
    for index in range(480):
        raw = digest[index % len(digest)] - 128
        sample = int(raw * 64).to_bytes(2, "little", signed=True)
        samples.extend(sample)
        samples.extend(sample)
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(48_000)
        wav.writeframes(bytes(samples))
    return output.getvalue()
