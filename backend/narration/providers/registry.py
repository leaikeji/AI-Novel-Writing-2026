"""Explicit Qwen TTS Provider selection with no automatic fallback."""

from __future__ import annotations

from dataclasses import dataclass
import os
from collections.abc import Callable
from typing import Iterable, Mapping
from uuid import UUID

from ..contracts import TTSProviderId
from .aliyun import (
    CANONICAL_MODEL_SLOTS,
)
from .base import TTSProvider, TTSProviderError
from .local import LocalQwenTTSConfig, LocalQwenTTSProvider


CloudProviderResolver = Callable[
    [UUID, int, str, str, str, str],
    TTSProvider,
]


@dataclass(frozen=True, slots=True)
class TTSProviderBinding:
    provider_id: TTSProviderId
    provider: TTSProvider
    model_id: str | None = None

    def __post_init__(self) -> None:
        if self.provider.capabilities.provider_id is not self.provider_id:
            raise ValueError("TTS Provider binding identity mismatch")
        if self.provider_id is TTSProviderId.LOCAL_QWEN3_TTS and self.model_id is not None:
            raise ValueError("local Qwen TTS binding must not pin one model role")
        if self.provider_id is TTSProviderId.ALIYUN_QWEN_AUDIO_TTS and not self.model_id:
            raise ValueError("Alibaba Cloud TTS binding requires an exact model")


class TTSProviderRegistry:
    """Resolve only the exact user-selected Provider/model pair."""

    def __init__(
        self,
        bindings: Iterable[TTSProviderBinding],
        *,
        cloud_provider_resolver: CloudProviderResolver | None = None,
    ) -> None:
        indexed: dict[tuple[TTSProviderId, str | None], TTSProvider] = {}
        for binding in bindings:
            key = (binding.provider_id, binding.model_id)
            if key in indexed:
                raise ValueError("duplicate TTS Provider binding")
            indexed[key] = binding.provider
        self._providers: Mapping[
            tuple[TTSProviderId, str | None], TTSProvider
        ] = indexed
        self._cloud_provider_resolver = cloud_provider_resolver

    def resolve(
        self,
        *,
        provider_id: TTSProviderId | str,
        aliyun_model_id: str | None = None,
        cloud_profile_id: UUID | None = None,
        cloud_profile_version: int | None = None,
        cloud_protocol: str | None = None,
        cloud_actual_model_id: str | None = None,
        cloud_base_url_fingerprint: str | None = None,
        cloud_verification_fingerprint: str | None = None,
    ) -> TTSProvider:
        try:
            selected = TTSProviderId(provider_id)
        except ValueError:
            raise TTSProviderError("TTS_PROVIDER_DISABLED", retryable=False) from None
        if selected is TTSProviderId.LOCAL_QWEN3_TTS:
            key = (selected, None)
        else:
            if aliyun_model_id not in CANONICAL_MODEL_SLOTS:
                raise TTSProviderError("TTS_PROVIDER_DISABLED", retryable=False)
            cloud_binding = (
                cloud_profile_id,
                cloud_profile_version,
                cloud_protocol,
                cloud_actual_model_id,
                cloud_base_url_fingerprint,
                cloud_verification_fingerprint,
            )
            if any(value is not None for value in cloud_binding):
                if (
                    not all(value is not None for value in cloud_binding)
                    or self._cloud_provider_resolver is None
                ):
                    raise TTSProviderError("TTS_PROVIDER_DISABLED", retryable=False)
                assert cloud_profile_id is not None
                assert cloud_profile_version is not None
                assert cloud_protocol is not None
                assert cloud_actual_model_id is not None
                assert cloud_base_url_fingerprint is not None
                assert cloud_verification_fingerprint is not None
                provider = self._cloud_provider_resolver(
                    cloud_profile_id,
                    cloud_profile_version,
                    cloud_protocol,
                    cloud_actual_model_id,
                    cloud_base_url_fingerprint,
                    cloud_verification_fingerprint,
                )
                if provider.capabilities.provider_id is not selected:
                    raise TTSProviderError("TTS_PROVIDER_DISABLED", retryable=False)
                return provider
            key = (selected, aliyun_model_id)
        provider = self._providers.get(key)
        if provider is None:
            raise TTSProviderError("TTS_PROVIDER_DISABLED", retryable=False)
        return provider


def build_qwen_tts_provider_registry_from_env(
    *,
    environ: Mapping[str, str] | None = None,
    cloud_provider_resolver: CloudProviderResolver | None = None,
) -> TTSProviderRegistry:
    """Build local runtime plus the database-backed cloud resolver, without I/O."""

    values = os.environ if environ is None else environ
    bindings = [
        TTSProviderBinding(
            provider_id=TTSProviderId.LOCAL_QWEN3_TTS,
            provider=LocalQwenTTSProvider(LocalQwenTTSConfig.from_env(values)),
        )
    ]
    return TTSProviderRegistry(
        bindings,
        cloud_provider_resolver=cloud_provider_resolver,
    )


__all__ = [
    "CloudProviderResolver",
    "TTSProviderBinding",
    "TTSProviderRegistry",
    "build_qwen_tts_provider_registry_from_env",
]
