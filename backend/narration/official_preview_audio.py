"""Stateless local previews for pinned Qwen official speakers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
import hashlib
import io
from typing import Final, Literal, Protocol
from uuid import UUID, uuid4
import wave

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from starlette.responses import Response

from ..novel_lifecycle import require_active_novel
from ..novel_lifecycle_errors import NovelLifecycleNotFound, NovelRecycledError
from . import schemas as wire
from .contracts import (
    NarrationRequestScope,
    TTSProviderId,
    TTSSynthesisRequest,
    TTSSynthesisResult,
    TTSVoiceInput,
    TTSVoiceKind,
)
from .official_presets import (
    OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256,
    OFFICIAL_PRESET_REPOSITORY,
    OFFICIAL_PRESET_REVISION,
    OFFICIAL_PRESET_RUNTIME_INITIAL_SEED,
    OfficialPreset,
    require_official_preset,
)
from .providers.base import TTSProviderError
from .release_gate import require_narration_t4_http_access
from .tts_execution import TTSExecutionService


PREVIEW_TIMEOUT_SECONDS: Final = 45.0
PREVIEW_MAX_AUDIO_BYTES: Final = 16 * 1024 * 1024
PREVIEW_DISCONNECT_POLL_SECONDS: Final = 0.1
PREVIEW_CACHE_MAX_ENTRIES: Final = 9
PREVIEW_ROUTE: Final = (
    "/novels/{novel_id}/official-voice-preview-audio"
)

PreviewLanguage = Literal["zh-CN"]
SessionFactory = Callable[[], Session]
NovelScopeValidator = Callable[[Session, UUID], object]
DisconnectProbe = Callable[[], Awaitable[bool]]

_PREVIEW_TEXT: Final[dict[str, str]] = {
    "zh-CN": "你好，这是一段本地声音试听，愿故事在文字与声音之间自然展开。",
}


class OfficialVoicePreviewAudioRequest(BaseModel):
    """The client chooses only a preset and target language, never the text."""

    model_config = ConfigDict(extra="forbid", strict=True)

    preset_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^qwen\.[A-Za-z][A-Za-z0-9]*$",
    )
    language: PreviewLanguage


@dataclass(frozen=True, slots=True)
class OfficialVoicePreviewAudio:
    audio_bytes: bytes
    provider_id: str
    model_id: str
    model_revision: str
    speaker_id: str
    cache_status: Literal["hit", "miss"] = "miss"

    @property
    def response_headers(self) -> dict[str, str]:
        return {
            "Cache-Control": "no-store",
            "X-TTS-Provider-Id": self.provider_id,
            "X-TTS-Model-Id": self.model_id,
            "X-TTS-Model-Revision": self.model_revision,
            "X-TTS-Speaker-Id": self.speaker_id,
            "X-TTS-Preview-Cache": self.cache_status,
        }


class OfficialVoicePreviewFailure(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class PreviewExecutionPort(Protocol):
    async def synthesize(
        self,
        *,
        novel_id: UUID,
        selection: wire.TTSProviderSelection,
        request: TTSSynthesisRequest,
    ) -> TTSSynthesisResult: ...

    async def cancel(
        self,
        *,
        selection: wire.TTSProviderSelection,
        request_id: UUID,
    ) -> object: ...


class OfficialVoicePreviewAudioService:
    """Validate briefly in SQL, then synthesize outside every DB session."""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        execution_service: TTSExecutionService | PreviewExecutionPort,
        novel_scope_validator: NovelScopeValidator = require_active_novel,
        timeout_seconds: float = PREVIEW_TIMEOUT_SECONDS,
        max_audio_bytes: int = PREVIEW_MAX_AUDIO_BYTES,
        disconnect_poll_seconds: float = PREVIEW_DISCONNECT_POLL_SECONDS,
    ) -> None:
        if not callable(session_factory):
            raise TypeError("session_factory must be callable")
        if not callable(novel_scope_validator):
            raise TypeError("novel_scope_validator must be callable")
        if isinstance(timeout_seconds, bool) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if type(max_audio_bytes) is not int or max_audio_bytes <= 0:
            raise ValueError("max_audio_bytes must be a positive integer")
        if isinstance(disconnect_poll_seconds, bool) or disconnect_poll_seconds <= 0:
            raise ValueError("disconnect_poll_seconds must be positive")
        self._session_factory = session_factory
        self._execution_service = execution_service
        self._novel_scope_validator = novel_scope_validator
        self._timeout_seconds = float(timeout_seconds)
        self._max_audio_bytes = max_audio_bytes
        self._disconnect_poll_seconds = float(disconnect_poll_seconds)
        # The request accepts nine pinned presets in the product's only language,
        # so this process-local cache is naturally bounded to nine immutable WAVs.
        # It avoids repeated inference without creating database or media records.
        self._preview_cache: dict[
            tuple[str, PreviewLanguage], OfficialVoicePreviewAudio
        ] = {}

    async def preview(
        self,
        *,
        novel_id: UUID,
        preset_id: str,
        language: PreviewLanguage,
        disconnect_probe: DisconnectProbe | None = None,
    ) -> OfficialVoicePreviewAudio:
        preset = self._validate_request_scope(novel_id, preset_id)
        cache_key = (preset.preset_id, language)
        cached = self._preview_cache.get(cache_key)
        if cached is not None:
            return replace(cached, cache_status="hit")
        selection = wire.TTSProviderSelection(
            provider_id=TTSProviderId.LOCAL_QWEN3_TTS.value
        )
        request_id = uuid4()
        synthesis_request = TTSSynthesisRequest(
            request_id=request_id,
            scope=NarrationRequestScope.fixed_local(),
            text=_PREVIEW_TEXT[language],
            language=language,
            voice=TTSVoiceInput(
                kind=TTSVoiceKind.PRESET,
                provider_voice_id=preset.local_voice_id,
            ),
            seed=OFFICIAL_PRESET_RUNTIME_INITIAL_SEED,
        )
        synthesis_task = asyncio.create_task(
            self._execution_service.synthesize(
                novel_id=novel_id,
                selection=selection,
                request=synthesis_request,
            )
        )
        disconnect_task = (
            asyncio.create_task(self._wait_for_disconnect(disconnect_probe))
            if disconnect_probe is not None
            else None
        )
        try:
            waiters = {synthesis_task}
            if disconnect_task is not None:
                waiters.add(disconnect_task)
            done, _ = await asyncio.wait(
                waiters,
                timeout=self._timeout_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if synthesis_task in done:
                result = synthesis_task.result()
                validated = self._validated_audio(result, synthesis_request, preset)
                if len(self._preview_cache) < PREVIEW_CACHE_MAX_ENTRIES:
                    self._preview_cache[cache_key] = validated
                return validated
            if disconnect_task is not None and disconnect_task in done:
                await self._abort(selection, request_id, synthesis_task)
                raise OfficialVoicePreviewFailure("TTS_PREVIEW_CLIENT_DISCONNECTED")
            await self._abort(selection, request_id, synthesis_task)
            raise OfficialVoicePreviewFailure("TTS_PROVIDER_TIMEOUT")
        except asyncio.CancelledError:
            await self._abort(selection, request_id, synthesis_task)
            raise
        finally:
            if disconnect_task is not None and not disconnect_task.done():
                disconnect_task.cancel()
                await asyncio.gather(disconnect_task, return_exceptions=True)

    def _validate_request_scope(
        self,
        novel_id: UUID,
        preset_id: str,
    ) -> OfficialPreset:
        try:
            with self._session_factory() as session:
                self._novel_scope_validator(session, novel_id)
                try:
                    return require_official_preset(preset_id)
                except ValueError as error:
                    raise OfficialVoicePreviewFailure(
                        "TTS_PREVIEW_PRESET_NOT_FOUND"
                    ) from error
        except NovelLifecycleNotFound as error:
            raise OfficialVoicePreviewFailure("TTS_PREVIEW_NOVEL_NOT_FOUND") from error
        except NovelRecycledError as error:
            raise OfficialVoicePreviewFailure("TTS_PREVIEW_NOVEL_RECYCLED") from error
        except OfficialVoicePreviewFailure:
            raise
        except Exception as error:
            raise OfficialVoicePreviewFailure("TTS_PREVIEW_SCOPE_UNAVAILABLE") from error

    async def _wait_for_disconnect(self, probe: DisconnectProbe) -> None:
        while not await probe():
            await asyncio.sleep(self._disconnect_poll_seconds)

    async def _abort(
        self,
        selection: wire.TTSProviderSelection,
        request_id: UUID,
        synthesis_task: asyncio.Task[TTSSynthesisResult],
    ) -> None:
        try:
            await self._execution_service.cancel(
                selection=selection,
                request_id=request_id,
            )
        except Exception:
            # Cancellation is best effort at the Provider boundary. The stable
            # timeout/disconnect result must not leak a secondary failure.
            pass
        if not synthesis_task.done():
            synthesis_task.cancel()
        await asyncio.gather(synthesis_task, return_exceptions=True)

    def _validated_audio(
        self,
        result: TTSSynthesisResult,
        request: TTSSynthesisRequest,
        preset: OfficialPreset,
    ) -> OfficialVoicePreviewAudio:
        audio = result.audio_bytes
        identity = result.model_identity
        if (
            result.request_id != request.request_id
            or result.content_type != "audio/wav"
            or not audio
            or len(audio) > self._max_audio_bytes
            or hashlib.sha256(audio).hexdigest() != result.actual_output_sha256
        ):
            raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False)
        if (
            identity.provider_id is not TTSProviderId.LOCAL_QWEN3_TTS
            or identity.model_id != OFFICIAL_PRESET_REPOSITORY
            or identity.model_revision != OFFICIAL_PRESET_REVISION
            or identity.artifact_tree_sha256
            != OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256
        ):
            raise TTSProviderError("TTS_MODEL_IDENTITY_MISMATCH", retryable=False)
        try:
            if audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
                raise wave.Error("not a RIFF/WAVE stream")
            with wave.open(io.BytesIO(audio), "rb") as reader:
                if (
                    reader.getnframes() <= 0
                    or reader.getframerate() != result.sample_rate_hz
                    or reader.getnchannels() != result.channels
                    or reader.getsampwidth() != result.sample_width_bytes
                ):
                    raise wave.Error("WAV metadata mismatch")
        except (EOFError, wave.Error):
            raise TTSProviderError(
                "TTS_PROVIDER_RESPONSE_INVALID",
                retryable=False,
            ) from None
        headers = (
            identity.provider_id.value,
            identity.model_id,
            identity.model_revision,
            preset.local_voice_id,
        )
        if any(not _safe_header_value(value) for value in headers):
            raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False)
        return OfficialVoicePreviewAudio(
            audio_bytes=audio,
            provider_id=identity.provider_id.value,
            model_id=identity.model_id,
            model_revision=identity.model_revision,
            speaker_id=preset.local_voice_id,
        )


OfficialVoicePreviewServiceFactory = Callable[
    [Request], OfficialVoicePreviewAudioService
]
DisconnectProbeFactory = Callable[[Request], DisconnectProbe]

_FAILURE_HTTP: Final[dict[str, tuple[int, str]]] = {
    "TTS_PREVIEW_NOVEL_NOT_FOUND": (
        status.HTTP_404_NOT_FOUND,
        "找不到请求的小说。",
    ),
    "TTS_PREVIEW_NOVEL_RECYCLED": (
        status.HTTP_410_GONE,
        "小说已移入回收站。",
    ),
    "TTS_PREVIEW_PRESET_NOT_FOUND": (
        status.HTTP_404_NOT_FOUND,
        "找不到请求的官方音色。",
    ),
    "TTS_PREVIEW_SCOPE_UNAVAILABLE": (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "暂时无法核验小说范围。",
    ),
    "TTS_PROVIDER_TIMEOUT": (
        status.HTTP_504_GATEWAY_TIMEOUT,
        "本地音色试听超时。",
    ),
    "TTS_PREVIEW_CLIENT_DISCONNECTED": (499, "客户端已断开连接。"),
}

_PROVIDER_HTTP: Final[dict[str, tuple[int, str]]] = {
    "TTS_PROVIDER_TIMEOUT": (status.HTTP_504_GATEWAY_TIMEOUT, "本地音色试听超时。"),
    "TTS_PROVIDER_RESPONSE_INVALID": (
        status.HTTP_502_BAD_GATEWAY,
        "本地语音模型返回了无效音频。",
    ),
    "TTS_MODEL_IDENTITY_MISMATCH": (
        status.HTTP_502_BAD_GATEWAY,
        "本地语音模型身份不匹配。",
    ),
    "TTS_VOICE_UNAVAILABLE": (
        status.HTTP_409_CONFLICT,
        "该官方音色当前不可用。",
    ),
}


def _safe_header_value(value: str) -> bool:
    return bool(value) and len(value) <= 512 and all(
        32 <= ord(character) < 127 for character in value
    )


def _http_error(code: str, *, provider_error: bool = False) -> HTTPException:
    contract = (
        _PROVIDER_HTTP.get(code) if provider_error else _FAILURE_HTTP.get(code)
    )
    if contract is None:
        contract = (
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "本地音色试听暂不可用。",
        )
    status_code, message = contract
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
        headers={"Cache-Control": "no-store"},
    )


def build_official_voice_preview_audio_router(
    service_factory: OfficialVoicePreviewServiceFactory,
    *,
    disconnect_probe_factory: DisconnectProbeFactory | None = None,
) -> APIRouter:
    """Build an inert router for later application-owned runtime wiring."""

    if not callable(service_factory):
        raise TypeError("official preview service factory must be callable")
    if disconnect_probe_factory is not None and not callable(disconnect_probe_factory):
        raise TypeError("disconnect_probe_factory must be callable")
    router = APIRouter(dependencies=[Depends(require_narration_t4_http_access)])

    def service(request: Request) -> OfficialVoicePreviewAudioService:
        try:
            return service_factory(request)
        except Exception:
            raise _http_error("TTS_PREVIEW_SERVICE_UNAVAILABLE") from None

    @router.post(PREVIEW_ROUTE, response_class=Response)
    async def preview_audio(
        novel_id: UUID,
        payload: OfficialVoicePreviewAudioRequest,
        request: Request,
        backend: OfficialVoicePreviewAudioService = Depends(service),
    ) -> Response:
        disconnect_probe = (
            disconnect_probe_factory(request)
            if disconnect_probe_factory is not None
            else request.is_disconnected
        )
        try:
            result = await backend.preview(
                novel_id=novel_id,
                preset_id=payload.preset_id,
                language=payload.language,
                disconnect_probe=disconnect_probe,
            )
        except OfficialVoicePreviewFailure as error:
            raise _http_error(error.code) from error
        except TTSProviderError as error:
            raise _http_error(error.code, provider_error=True) from error
        return Response(
            content=result.audio_bytes,
            media_type="audio/wav",
            headers=result.response_headers,
        )

    return router


__all__ = [
    "OfficialVoicePreviewAudio",
    "OfficialVoicePreviewAudioRequest",
    "OfficialVoicePreviewAudioService",
    "OfficialVoicePreviewFailure",
    "PREVIEW_CACHE_MAX_ENTRIES",
    "PREVIEW_MAX_AUDIO_BYTES",
    "PREVIEW_ROUTE",
    "PREVIEW_TIMEOUT_SECONDS",
    "PreviewExecutionPort",
    "PreviewLanguage",
    "DisconnectProbeFactory",
    "build_official_voice_preview_audio_router",
]
