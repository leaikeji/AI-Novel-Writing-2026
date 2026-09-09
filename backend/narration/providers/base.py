"""Provider boundary shared by local Qwen3-TTS and Alibaba Cloud."""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from ..contracts import (
    AdapterHealth,
    CancelDisposition,
    TTSModelIdentity,
    TTSProviderCapabilities,
    TTS_PROVIDER_ERROR_CODES,
    TTSSynthesisRequest,
    TTSSynthesisResult,
    TTSVoicePreparationRequest,
    TTSVoicePreparationResult,
)


class TTSProviderError(RuntimeError):
    """Stable, redacted Provider failure safe to persist in task evidence."""

    def __init__(self, code: str, *, retryable: bool) -> None:
        if code not in TTS_PROVIDER_ERROR_CODES:
            raise ValueError("unknown TTS Provider error code")
        if type(retryable) is not bool:
            raise TypeError("retryable must be an exact boolean")
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class TTSProvider(ABC):
    """No SDK, HTTP, tensor, or filesystem type may cross this boundary."""

    @property
    @abstractmethod
    def capabilities(self) -> TTSProviderCapabilities: ...

    @abstractmethod
    async def health(self) -> AdapterHealth: ...

    @abstractmethod
    async def model_identity(self) -> TTSModelIdentity | None: ...

    @abstractmethod
    async def warmup(self) -> AdapterHealth: ...

    @abstractmethod
    async def synthesize(self, request: TTSSynthesisRequest) -> TTSSynthesisResult: ...

    @abstractmethod
    async def clone_voice(
        self,
        request: TTSVoicePreparationRequest,
    ) -> TTSVoicePreparationResult: ...

    @abstractmethod
    async def design_voice(
        self,
        request: TTSVoicePreparationRequest,
    ) -> TTSVoicePreparationResult: ...

    @abstractmethod
    async def cancel(self, request_id: UUID) -> CancelDisposition: ...
