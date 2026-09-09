from __future__ import annotations

from uuid import uuid4

import pytest

from backend.narration.contracts import TTSProviderId
from backend.narration.providers.aliyun import (
    ALIYUN_QWEN_AUDIO_TTS_FLASH,
    ALIYUN_QWEN_AUDIO_TTS_PLUS,
    AliyunQwenAudioTTSProvider,
)
from backend.narration.providers.base import TTSProviderError
from backend.narration.providers.local import LocalQwenTTSProvider
from backend.narration.providers.registry import (
    TTSProviderBinding,
    TTSProviderRegistry,
    build_qwen_tts_provider_registry_from_env,
)


ALIYUN_BASE_URL = "https://member-gateway.example.com/qwen/v1"


def _cloud(model_id: str) -> AliyunQwenAudioTTSProvider:
    return AliyunQwenAudioTTSProvider(
        api_key="test-key",
        base_url=ALIYUN_BASE_URL,
        model_id=model_id,
    )


def test_registry_resolves_only_the_exact_manual_selection() -> None:
    local = LocalQwenTTSProvider()
    plus = _cloud(ALIYUN_QWEN_AUDIO_TTS_PLUS)
    flash = _cloud(ALIYUN_QWEN_AUDIO_TTS_FLASH)
    registry = TTSProviderRegistry(
        (
            TTSProviderBinding(TTSProviderId.LOCAL_QWEN3_TTS, local),
            TTSProviderBinding(
                TTSProviderId.ALIYUN_QWEN_AUDIO_TTS,
                plus,
                ALIYUN_QWEN_AUDIO_TTS_PLUS,
            ),
            TTSProviderBinding(
                TTSProviderId.ALIYUN_QWEN_AUDIO_TTS,
                flash,
                ALIYUN_QWEN_AUDIO_TTS_FLASH,
            ),
        )
    )

    assert registry.resolve(provider_id="local_qwen3_tts") is local
    assert registry.resolve(
        provider_id="aliyun_qwen_audio_tts",
        aliyun_model_id=ALIYUN_QWEN_AUDIO_TTS_PLUS,
    ) is plus
    assert registry.resolve(
        provider_id="aliyun_qwen_audio_tts",
        aliyun_model_id=ALIYUN_QWEN_AUDIO_TTS_FLASH,
    ) is flash


@pytest.mark.asyncio
async def test_canonical_slot_can_bind_a_channel_specific_actual_model() -> None:
    actual_model_id = "membership-qwen-quality-2026"
    provider = _cloud(actual_model_id)
    registry = TTSProviderRegistry(
        (
            TTSProviderBinding(
                TTSProviderId.ALIYUN_QWEN_AUDIO_TTS,
                provider,
                ALIYUN_QWEN_AUDIO_TTS_PLUS,
            ),
        )
    )

    resolved = registry.resolve(
        provider_id="aliyun_qwen_audio_tts",
        aliyun_model_id=ALIYUN_QWEN_AUDIO_TTS_PLUS,
    )
    assert resolved is provider
    assert (await resolved.model_identity()).model_id == actual_model_id

    with pytest.raises(TTSProviderError):
        registry.resolve(
            provider_id="aliyun_qwen_audio_tts",
            aliyun_model_id=actual_model_id,
        )


def test_missing_selected_provider_fails_without_cross_provider_fallback() -> None:
    local = LocalQwenTTSProvider()
    registry = TTSProviderRegistry(
        (TTSProviderBinding(TTSProviderId.LOCAL_QWEN3_TTS, local),)
    )

    with pytest.raises(TTSProviderError) as unavailable:
        registry.resolve(
            provider_id="aliyun_qwen_audio_tts",
            aliyun_model_id=ALIYUN_QWEN_AUDIO_TTS_PLUS,
        )
    assert unavailable.value.code == "TTS_PROVIDER_DISABLED"
    assert unavailable.value.retryable is False


def test_frozen_cloud_binding_uses_dynamic_profile_resolver() -> None:
    profile_id = uuid4()
    provider = _cloud("member-qwen-quality")
    calls: list[tuple[object, ...]] = []

    def resolve(*args):  # type: ignore[no-untyped-def]
        calls.append(args)
        return provider

    registry = TTSProviderRegistry((), cloud_provider_resolver=resolve)
    selected = registry.resolve(
        provider_id="aliyun_qwen_audio_tts",
        aliyun_model_id=ALIYUN_QWEN_AUDIO_TTS_PLUS,
        cloud_profile_id=profile_id,
        cloud_profile_version=7,
        cloud_protocol="qwen_audio_native_http/1",
        cloud_actual_model_id="member-qwen-quality",
        cloud_base_url_fingerprint="b" * 64,
        cloud_verification_fingerprint="c" * 64,
    )

    assert selected is provider
    assert calls == [
        (
            profile_id,
            7,
            "qwen_audio_native_http/1",
            "member-qwen-quality",
            "b" * 64,
            "c" * 64,
        )
    ]


def test_environment_registry_keeps_cloud_disabled_without_database_resolver() -> None:
    registry = build_qwen_tts_provider_registry_from_env()

    assert isinstance(
        registry.resolve(provider_id="local_qwen3_tts"),
        LocalQwenTTSProvider,
    )
    with pytest.raises(TTSProviderError):
        registry.resolve(
            provider_id="aliyun_qwen_audio_tts",
            aliyun_model_id=ALIYUN_QWEN_AUDIO_TTS_PLUS,
        )


def test_legacy_cloud_environment_cannot_enable_a_provider() -> None:
    registry = build_qwen_tts_provider_registry_from_env(
        environ={
            "QWEN_TTS_LOCAL_URL": "http://127.0.0.1:8766",
            "QWEN_TTS_ALIYUN_BASE_URL": ALIYUN_BASE_URL,
            "QWEN_TTS_ALIYUN_PRODUCT_ENABLED": "1",
        }
    )

    with pytest.raises(TTSProviderError):
        registry.resolve(
            provider_id="aliyun_qwen_audio_tts",
            aliyun_model_id=ALIYUN_QWEN_AUDIO_TTS_PLUS,
        )


def test_environment_registry_uses_the_injected_runtime_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QWEN_TTS_LOCAL_URL", "not-a-url")

    registry = build_qwen_tts_provider_registry_from_env(
        environ={"QWEN_TTS_LOCAL_URL": "http://127.0.0.1:8766"}
    )

    assert isinstance(
        registry.resolve(provider_id="local_qwen3_tts"),
        LocalQwenTTSProvider,
    )
