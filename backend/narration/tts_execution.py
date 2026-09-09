"""Provider-neutral TTS execution seam used by narration workers and previews."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from . import schemas as wire
from .contracts import (
    CancelDisposition,
    TTSProviderId,
    TTSSynthesisRequest,
    TTSSynthesisResult,
    TTSVoicePreparationRequest,
    TTSVoicePreparationResult,
)
from .providers.base import TTSProvider, TTSProviderError
from .providers.registry import TTSProviderRegistry


CloudTTSConsentAuthorizer = Callable[[UUID, str], None]


class TTSExecutionService:
    """Execute against the selected Provider and never select a fallback."""

    def __init__(
        self,
        registry: TTSProviderRegistry,
        *,
        authorize_cloud_tts: CloudTTSConsentAuthorizer,
    ) -> None:
        self._registry = registry
        self._authorize_cloud_tts = authorize_cloud_tts

    async def synthesize(
        self,
        *,
        novel_id: UUID,
        selection: wire.TTSProviderSelection,
        request: TTSSynthesisRequest,
    ) -> TTSSynthesisResult:
        provider = self._resolve(novel_id=novel_id, selection=selection)
        result = await provider.synthesize(request)
        if result.request_id != request.request_id:
            raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False)
        await self._validate_result_identity(provider, selection, result)
        return result

    async def clone_voice(
        self,
        *,
        novel_id: UUID,
        selection: wire.TTSProviderSelection,
        request: TTSVoicePreparationRequest,
    ) -> TTSVoicePreparationResult:
        provider = self._resolve(novel_id=novel_id, selection=selection)
        result = await provider.clone_voice(request)
        if result.request_id != request.request_id:
            raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False)
        await self._validate_preparation_identity(provider, selection, result)
        return result

    async def design_voice(
        self,
        *,
        novel_id: UUID,
        selection: wire.TTSProviderSelection,
        request: TTSVoicePreparationRequest,
    ) -> TTSVoicePreparationResult:
        provider = self._resolve(novel_id=novel_id, selection=selection)
        result = await provider.design_voice(request)
        if result.request_id != request.request_id:
            raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False)
        await self._validate_preparation_identity(provider, selection, result)
        return result

    async def cancel(
        self,
        *,
        selection: wire.TTSProviderSelection,
        request_id: UUID,
    ) -> CancelDisposition:
        provider = self._registry.resolve(
            provider_id=selection.provider_id,
            aliyun_model_id=selection.aliyun_model_id,
            cloud_profile_id=selection.cloud_profile_id,
            cloud_profile_version=selection.cloud_profile_version,
            cloud_protocol=selection.cloud_protocol,
            cloud_actual_model_id=selection.cloud_actual_model_id,
            cloud_base_url_fingerprint=selection.cloud_base_url_fingerprint,
            cloud_verification_fingerprint=selection.cloud_verification_fingerprint,
        )
        if not provider.capabilities.production_ready:
            raise TTSProviderError("TTS_PROVIDER_DISABLED", retryable=False)
        return await provider.cancel(request_id)

    def _resolve(
        self,
        *,
        novel_id: UUID,
        selection: wire.TTSProviderSelection,
    ) -> TTSProvider:
        provider = self._registry.resolve(
            provider_id=selection.provider_id,
            aliyun_model_id=selection.aliyun_model_id,
            cloud_profile_id=selection.cloud_profile_id,
            cloud_profile_version=selection.cloud_profile_version,
            cloud_protocol=selection.cloud_protocol,
            cloud_actual_model_id=selection.cloud_actual_model_id,
            cloud_base_url_fingerprint=selection.cloud_base_url_fingerprint,
            cloud_verification_fingerprint=selection.cloud_verification_fingerprint,
        )
        if not provider.capabilities.production_ready:
            raise TTSProviderError("TTS_PROVIDER_DISABLED", retryable=False)
        if selection.provider_id == TTSProviderId.ALIYUN_QWEN_AUDIO_TTS.value:
            self._authorize_cloud_tts(novel_id, selection.aliyun_model_id)
        return provider

    @classmethod
    async def _validate_result_identity(
        cls,
        provider: TTSProvider,
        selection: wire.TTSProviderSelection,
        result: TTSSynthesisResult,
    ) -> None:
        await cls._validate_identity(provider, selection, result.model_identity)

    @classmethod
    async def _validate_preparation_identity(
        cls,
        provider: TTSProvider,
        selection: wire.TTSProviderSelection,
        result: TTSVoicePreparationResult,
    ) -> None:
        await cls._validate_identity(provider, selection, result.model_identity)

    @staticmethod
    async def _validate_identity(
        provider: TTSProvider,
        selection: wire.TTSProviderSelection,
        actual_identity: object,
    ) -> None:
        expected_identity = await provider.model_identity()
        if expected_identity is None or actual_identity != expected_identity:
            raise TTSProviderError("TTS_MODEL_IDENTITY_MISMATCH", retryable=False)
        actual_provider_id = expected_identity.provider_id
        if actual_provider_id.value != selection.provider_id:
            raise TTSProviderError("TTS_MODEL_IDENTITY_MISMATCH", retryable=False)
        expected_model_id = (
            selection.cloud_actual_model_id
            if selection.cloud_actual_model_id is not None
            else selection.aliyun_model_id
        )
        if (
            actual_provider_id is TTSProviderId.ALIYUN_QWEN_AUDIO_TTS
            and expected_identity.model_id != expected_model_id
        ):
            raise TTSProviderError("TTS_MODEL_IDENTITY_MISMATCH", retryable=False)


__all__ = ["CloudTTSConsentAuthorizer", "TTSExecutionService"]
