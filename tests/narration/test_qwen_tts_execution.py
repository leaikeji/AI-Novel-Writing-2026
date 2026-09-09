from __future__ import annotations

import hashlib
import io
import wave
from uuid import UUID, uuid4

import pytest

from backend.narration import schemas as wire
from backend.narration.contracts import (
    AdapterHealth,
    CancelDisposition,
    CancellationGranularity,
    NarrationRequestScope,
    TTSModelIdentity,
    TTSProviderCapabilities,
    TTSProviderId,
    TTSSynthesisRequest,
    TTSSynthesisResult,
    TTSVoiceInput,
    TTSVoiceKind,
)
from backend.narration.providers.base import TTSProvider, TTSProviderError
from backend.narration.providers.registry import TTSProviderBinding, TTSProviderRegistry
from backend.narration.tts_execution import TTSExecutionService


NOVEL_ID = UUID("20000000-0000-4000-8000-000000000001")


def _wav() -> bytes:
    target = io.BytesIO()
    with wave.open(target, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(24_000)
        output.writeframes(b"\x00\x00" * 24)
    return target.getvalue()


class RecordingProvider(TTSProvider):
    def __init__(
        self,
        provider_id: TTSProviderId,
        model_id: str,
        *,
        production_ready: bool = True,
        response_request_id: UUID | None = None,
    ) -> None:
        self.calls = 0
        self.cancelled: list[UUID] = []
        self.model_id = model_id
        self.response_request_id = response_request_id
        self._capabilities = TTSProviderCapabilities(
            provider_id=provider_id,
            supports_synthesis=True,
            supports_presets=True,
            supports_reference_clone=True,
            supports_voice_design=True,
            supports_instructions=True,
            supports_streaming_first_audio=False,
            supports_warmup=False,
            supports_cancel=False,
            cancellation_granularity=CancellationGranularity.NONE,
            max_inference_concurrency=1,
            product_visible=production_ready,
            production_ready=production_ready,
        )

    @property
    def capabilities(self) -> TTSProviderCapabilities:
        return self._capabilities

    async def health(self) -> AdapterHealth:
        raise AssertionError("unused")

    async def model_identity(self) -> TTSModelIdentity:
        return self._identity()

    async def warmup(self) -> AdapterHealth:
        raise AssertionError("unused")

    async def synthesize(self, request: TTSSynthesisRequest) -> TTSSynthesisResult:
        self.calls += 1
        audio = _wav()
        return TTSSynthesisResult(
            request_id=self.response_request_id or request.request_id,
            audio_bytes=audio,
            actual_output_sha256=hashlib.sha256(audio).hexdigest(),
            sample_rate_hz=24_000,
            channels=1,
            sample_width_bytes=2,
            model_identity=self._identity(),
        )

    async def clone_voice(self, request):  # type: ignore[no-untyped-def]
        raise AssertionError("unused")

    async def design_voice(self, request):  # type: ignore[no-untyped-def]
        raise AssertionError("unused")

    async def cancel(self, request_id):  # type: ignore[no-untyped-def]
        self.cancelled.append(request_id)
        return CancelDisposition.UNSUPPORTED

    def _identity(self) -> TTSModelIdentity:
        return TTSModelIdentity(
            provider_id=self._capabilities.provider_id,
            model_id=self.model_id,
            model_revision="test",
            runtime_id="test",
            runtime_version="1",
            quantization="managed",
            artifact_tree_sha256="a" * 64,
        )


def _request() -> TTSSynthesisRequest:
    return TTSSynthesisRequest(
        request_id=uuid4(),
        scope=NarrationRequestScope.fixed_local(),
        text="测试正文",
        language="zh-CN",
        voice=TTSVoiceInput(TTSVoiceKind.PRESET, "Vivian"),
    )


@pytest.mark.asyncio
async def test_local_selection_never_calls_cloud_or_consent_gate() -> None:
    local = RecordingProvider(TTSProviderId.LOCAL_QWEN3_TTS, "local-model")
    cloud = RecordingProvider(
        TTSProviderId.ALIYUN_QWEN_AUDIO_TTS,
        "qwen-audio-3.0-tts-plus",
    )
    consent_calls: list[tuple[UUID, str]] = []
    service = TTSExecutionService(
        TTSProviderRegistry(
            (
                TTSProviderBinding(TTSProviderId.LOCAL_QWEN3_TTS, local),
                TTSProviderBinding(
                    TTSProviderId.ALIYUN_QWEN_AUDIO_TTS,
                    cloud,
                    "qwen-audio-3.0-tts-plus",
                ),
            )
        ),
        authorize_cloud_tts=lambda novel_id, model_id: consent_calls.append(
            (novel_id, model_id)
        ),
    )

    await service.synthesize(
        novel_id=NOVEL_ID,
        selection=wire.TTSProviderSelection(),
        request=_request(),
    )
    assert local.calls == 1
    assert cloud.calls == 0
    assert consent_calls == []


@pytest.mark.asyncio
async def test_cloud_consent_denial_makes_zero_provider_calls_and_no_fallback() -> None:
    local = RecordingProvider(TTSProviderId.LOCAL_QWEN3_TTS, "local-model")
    cloud = RecordingProvider(
        TTSProviderId.ALIYUN_QWEN_AUDIO_TTS,
        "qwen-audio-3.0-tts-plus",
    )

    def deny(_novel_id: UUID, _model_id: str) -> None:
        raise TTSProviderError("TTS_PROVIDER_CONSENT_REQUIRED", retryable=False)

    service = TTSExecutionService(
        TTSProviderRegistry(
            (
                TTSProviderBinding(TTSProviderId.LOCAL_QWEN3_TTS, local),
                TTSProviderBinding(
                    TTSProviderId.ALIYUN_QWEN_AUDIO_TTS,
                    cloud,
                    "qwen-audio-3.0-tts-plus",
                ),
            )
        ),
        authorize_cloud_tts=deny,
    )

    with pytest.raises(TTSProviderError) as denied:
        await service.synthesize(
            novel_id=NOVEL_ID,
            selection=wire.TTSProviderSelection(provider_id="aliyun_qwen_audio_tts"),
            request=_request(),
        )
    assert denied.value.code == "TTS_PROVIDER_CONSENT_REQUIRED"
    assert cloud.calls == 0
    assert local.calls == 0


@pytest.mark.asyncio
async def test_unreleased_provider_fails_before_consent_or_provider_call() -> None:
    cloud = RecordingProvider(
        TTSProviderId.ALIYUN_QWEN_AUDIO_TTS,
        "qwen-audio-3.0-tts-plus",
        production_ready=False,
    )
    consent_calls: list[tuple[UUID, str]] = []
    service = TTSExecutionService(
        TTSProviderRegistry(
            (
                TTSProviderBinding(
                    TTSProviderId.ALIYUN_QWEN_AUDIO_TTS,
                    cloud,
                    "qwen-audio-3.0-tts-plus",
                ),
            )
        ),
        authorize_cloud_tts=lambda novel_id, model_id: consent_calls.append(
            (novel_id, model_id)
        ),
    )

    with pytest.raises(TTSProviderError) as disabled:
        await service.synthesize(
            novel_id=NOVEL_ID,
            selection=wire.TTSProviderSelection(provider_id="aliyun_qwen_audio_tts"),
            request=_request(),
        )
    assert disabled.value.code == "TTS_PROVIDER_DISABLED"
    assert cloud.calls == 0
    assert consent_calls == []


@pytest.mark.asyncio
async def test_cloud_result_identity_mismatch_fails_closed() -> None:
    cloud = RecordingProvider(
        TTSProviderId.ALIYUN_QWEN_AUDIO_TTS,
        "qwen-audio-3.0-tts-flash",
    )
    service = TTSExecutionService(
        TTSProviderRegistry(
            (
                TTSProviderBinding(
                    TTSProviderId.ALIYUN_QWEN_AUDIO_TTS,
                    cloud,
                    "qwen-audio-3.0-tts-plus",
                ),
            )
        ),
        authorize_cloud_tts=lambda _novel_id, _model_id: None,
    )

    with pytest.raises(TTSProviderError) as mismatch:
        await service.synthesize(
            novel_id=NOVEL_ID,
            selection=wire.TTSProviderSelection(provider_id="aliyun_qwen_audio_tts"),
            request=_request(),
        )
    assert mismatch.value.code == "TTS_MODEL_IDENTITY_MISMATCH"


@pytest.mark.asyncio
async def test_result_request_identity_mismatch_fails_closed() -> None:
    local = RecordingProvider(
        TTSProviderId.LOCAL_QWEN3_TTS,
        "local-model",
        response_request_id=uuid4(),
    )
    service = TTSExecutionService(
        TTSProviderRegistry(
            (TTSProviderBinding(TTSProviderId.LOCAL_QWEN3_TTS, local),)
        ),
        authorize_cloud_tts=lambda _novel_id, _model_id: None,
    )

    with pytest.raises(TTSProviderError) as mismatch:
        await service.synthesize(
            novel_id=NOVEL_ID,
            selection=wire.TTSProviderSelection(),
            request=_request(),
        )
    assert mismatch.value.code == "TTS_PROVIDER_RESPONSE_INVALID"


@pytest.mark.asyncio
async def test_cancel_uses_only_the_explicit_selection_without_fallback() -> None:
    local = RecordingProvider(TTSProviderId.LOCAL_QWEN3_TTS, "local-model")
    cloud = RecordingProvider(
        TTSProviderId.ALIYUN_QWEN_AUDIO_TTS,
        "qwen-audio-3.0-tts-plus",
    )
    service = TTSExecutionService(
        TTSProviderRegistry(
            (
                TTSProviderBinding(TTSProviderId.LOCAL_QWEN3_TTS, local),
                TTSProviderBinding(
                    TTSProviderId.ALIYUN_QWEN_AUDIO_TTS,
                    cloud,
                    "qwen-audio-3.0-tts-plus",
                ),
            )
        ),
        authorize_cloud_tts=lambda _novel_id, _model_id: None,
    )
    request_id = uuid4()

    disposition = await service.cancel(
        selection=wire.TTSProviderSelection(),
        request_id=request_id,
    )

    assert disposition is CancelDisposition.UNSUPPORTED
    assert local.cancelled == [request_id]
    assert cloud.cancelled == []
