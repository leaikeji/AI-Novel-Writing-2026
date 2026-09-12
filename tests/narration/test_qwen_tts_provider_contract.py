from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest

from backend.narration.contracts import (
    CancellationGranularity,
    ContractError,
    LOCAL_OWNER_ID,
    NarrationRequestScope,
    ReferenceAudioInput,
    TTSModelIdentity,
    TTSProviderCapabilities,
    TTSProviderId,
    TTSSynthesisRequest,
    TTSVoiceInput,
    TTSVoiceKind,
    TTSVoicePreparationRequest,
)
from backend.narration.providers import TTSProvider, TTSProviderError
from backend.narration.fingerprints import tts_model_identity_sha256


def _reference() -> ReferenceAudioInput:
    raw = b"not-a-real-wave-but-hash-bound-at-contract-layer"
    return ReferenceAudioInput(
        audio_bytes=raw,
        actual_sha256=hashlib.sha256(raw).hexdigest(),
    )


def test_provider_contract_accepts_explicit_local_preset() -> None:
    voice = TTSVoiceInput(
        kind=TTSVoiceKind.PRESET,
        provider_voice_id="Vivian",
    )
    request = TTSSynthesisRequest(
        request_id=uuid4(),
        scope=NarrationRequestScope.fixed_local(),
        text="这是一段本地朗读。",
        language="zh-CN",
        voice=voice,
        seed=2026,
        instruction="自然、沉稳",
    )

    assert request.scope.owner_id == LOCAL_OWNER_ID
    assert request.voice.provider_voice_id == "Vivian"


def test_reference_material_is_only_allowed_for_clone_voice() -> None:
    with pytest.raises(ContractError, match="only reference clone"):
        TTSVoiceInput(
            kind=TTSVoiceKind.PRESET,
            provider_voice_id="Vivian",
            reference_audio=_reference(),
        )

    clone = TTSVoiceInput(
        kind=TTSVoiceKind.REFERENCE_CLONE,
        provider_voice_id="reference:sha256",
        reference_audio=_reference(),
        reference_text="参考音频转写",
    )
    assert clone.kind is TTSVoiceKind.REFERENCE_CLONE
    registered_cloud_clone = TTSVoiceInput(
        kind=TTSVoiceKind.REFERENCE_CLONE,
        provider_voice_id="qwen-audio-3.0-tts-plus-character-abc123",
    )
    assert registered_cloud_clone.reference_audio is None


def test_voice_preparation_requires_exactly_one_source() -> None:
    common = {
        "request_id": uuid4(),
        "scope": NarrationRequestScope.fixed_local(),
        "preview_text": "试听文本",
        "language": "zh-CN",
    }
    with pytest.raises(ContractError, match="exactly one"):
        TTSVoicePreparationRequest(**common)
    with pytest.raises(ContractError, match="exactly one"):
        TTSVoicePreparationRequest(
            **common,
            description="年轻女声",
            reference_audio=_reference(),
        )


@pytest.mark.parametrize("language", ["en", "ja-JP", "zh-HK", "yue-CN"])
def test_voice_preparation_rejects_every_non_mandarin_language(language: str) -> None:
    with pytest.raises(ContractError, match="must be zh-CN"):
        TTSVoicePreparationRequest(
            request_id=uuid4(),
            scope=NarrationRequestScope.fixed_local(),
            preview_text="试听文本",
            language=language,
            description="年轻清晰女声",
        )


@pytest.mark.parametrize("description", ["四川话女声", "粤语旁白", "带一点北京腔"])
def test_voice_preparation_rejects_dialect_designs(description: str) -> None:
    with pytest.raises(ContractError, match="without dialect"):
        TTSVoicePreparationRequest(
            request_id=uuid4(),
            scope=NarrationRequestScope.fixed_local(),
            preview_text="试听文本",
            language="zh-CN",
            description=description,
        )


def test_capabilities_reject_hidden_non_ready_mismatch() -> None:
    with pytest.raises(ContractError, match="product-visible"):
        TTSProviderCapabilities(
            provider_id=TTSProviderId.LOCAL_QWEN3_TTS,
            supports_synthesis=True,
            supports_presets=True,
            supports_reference_clone=True,
            supports_voice_design=True,
            supports_instructions=True,
            supports_streaming_first_audio=True,
            supports_warmup=True,
            supports_cancel=True,
            cancellation_granularity=CancellationGranularity.SEGMENT_BOUNDARY,
            max_inference_concurrency=1,
            product_visible=True,
            production_ready=False,
        )


def test_model_identity_includes_provider_runtime_and_quantization() -> None:
    identity = TTSModelIdentity(
        provider_id=TTSProviderId.ALIYUN_QWEN_AUDIO_TTS,
        model_id="qwen-audio-3.0-tts-plus",
        model_revision="2026-07-14",
        runtime_id="aliyun-model-studio-http",
        runtime_version="2026-07-14",
        quantization="managed",
        artifact_tree_sha256="0" * 64,
    )
    assert identity.provider_id is TTSProviderId.ALIYUN_QWEN_AUDIO_TTS
    assert tts_model_identity_sha256(identity) == tts_model_identity_sha256(identity)
    assert len(tts_model_identity_sha256(identity)) == 64


def test_provider_error_is_stable_and_redacted() -> None:
    error = TTSProviderError("TTS_PROVIDER_RATE_LIMITED", retryable=True)
    assert str(error) == "TTS_PROVIDER_RATE_LIMITED"
    assert error.retryable is True
    with pytest.raises(ValueError, match="unknown"):
        TTSProviderError("raw vendor message", retryable=False)


def test_provider_boundary_remains_abstract() -> None:
    with pytest.raises(TypeError):
        TTSProvider()
