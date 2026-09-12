from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import io
from types import SimpleNamespace
from uuid import UUID
import wave

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.narration.contracts import (
    TTSModelIdentity,
    TTSProviderId,
    TTSSynthesisRequest,
    TTSSynthesisResult,
)
from backend.narration.official_preview_audio import (
    OfficialVoicePreviewAudioService,
    OfficialVoicePreviewFailure,
    PREVIEW_ROUTE,
    build_official_voice_preview_audio_router,
    require_narration_t4_http_access,
)
from backend.narration.official_presets import require_official_preset
from backend.narration.providers.base import TTSProviderError
from backend.novel_lifecycle_errors import NovelLifecycleNotFound


NOVEL_ID = UUID("75000000-0000-4000-8000-000000000001")
MODEL_ID = "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit"
MODEL_REVISION = "41d3337e8b7f2843a75841595fc14e4b9a7a4b96"


def _wav_bytes(*, frames: int = 48) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(24_000)
        target.writeframes(b"\x01\x00" * frames)
    return output.getvalue()


def _identity(
    provider_id: TTSProviderId = TTSProviderId.LOCAL_QWEN3_TTS,
    *,
    model_id: str = MODEL_ID,
    model_revision: str = MODEL_REVISION,
    artifact_tree_sha256: str = (
        "728e8b60b4cdb195a1379faf033b428bf93feaceccbdcf3c3a4bd3a6698b4fb6"
    ),
) -> TTSModelIdentity:
    return TTSModelIdentity(
        provider_id=provider_id,
        model_id=model_id,
        model_revision=model_revision,
        runtime_id="qwen-tts-local-runtime",
        runtime_version="1",
        quantization="8bit",
        artifact_tree_sha256=artifact_tree_sha256,
    )


class RecordingSession:
    def __init__(self) -> None:
        self.open = False
        self.closed = False
        self.write_calls: list[str] = []

    def __enter__(self) -> "RecordingSession":
        self.open = True
        return self

    def __exit__(self, *_args: object) -> None:
        self.open = False
        self.closed = True

    def add(self, _value: object) -> None:
        self.write_calls.append("add")

    def flush(self) -> None:
        self.write_calls.append("flush")

    def commit(self) -> None:
        self.write_calls.append("commit")


@dataclass
class RecordingExecution:
    session: RecordingSession
    block: bool = False
    result_override: object | None = None

    def __post_init__(self) -> None:
        self.requests: list[tuple[UUID, object, TTSSynthesisRequest]] = []
        self.cancelled: list[tuple[object, UUID]] = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def synthesize(
        self,
        *,
        novel_id: UUID,
        selection: object,
        request: TTSSynthesisRequest,
    ) -> TTSSynthesisResult:
        assert self.session.closed is True
        self.requests.append((novel_id, selection, request))
        self.started.set()
        if self.block:
            await self.release.wait()
        if self.result_override is not None:
            if getattr(self.result_override, "request_id", None) is None:
                self.result_override.request_id = request.request_id
            return self.result_override  # type: ignore[return-value]
        audio = _wav_bytes()
        return TTSSynthesisResult(
            request_id=request.request_id,
            audio_bytes=audio,
            actual_output_sha256=hashlib.sha256(audio).hexdigest(),
            sample_rate_hz=24_000,
            channels=1,
            sample_width_bytes=2,
            model_identity=_identity(),
        )

    async def cancel(self, *, selection: object, request_id: UUID) -> object:
        self.cancelled.append((selection, request_id))
        return "requested"


def _service(
    execution: RecordingExecution,
    session: RecordingSession,
    *,
    timeout_seconds: float = 45,
    max_audio_bytes: int = 16 * 1024 * 1024,
) -> OfficialVoicePreviewAudioService:
    def validate_scope(current: RecordingSession, novel_id: UUID) -> object:
        assert current is session
        assert current.open is True
        assert novel_id == NOVEL_ID
        return object()

    return OfficialVoicePreviewAudioService(
        session_factory=lambda: session,  # type: ignore[arg-type,return-value]
        execution_service=execution,
        novel_scope_validator=validate_scope,  # type: ignore[arg-type]
        timeout_seconds=timeout_seconds,
        max_audio_bytes=max_audio_bytes,
        disconnect_poll_seconds=0.001,
    )


async def _never_disconnected() -> bool:
    return False


def _router(service: OfficialVoicePreviewAudioService):
    return build_official_voice_preview_audio_router(
        lambda _request: service,
        disconnect_probe_factory=lambda _request: _never_disconnected,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["zh-CN", "en", "ja-JP", "ko-KR"])
async def test_preview_forces_local_fixed_text_and_returns_valid_wav(
    language: str,
) -> None:
    session = RecordingSession()
    execution = RecordingExecution(session)
    service = _service(execution, session)

    result = await service.preview(
        novel_id=NOVEL_ID,
        preset_id="qwen.WarmFemale",
        language=language,  # type: ignore[arg-type]
    )

    assert result.audio_bytes[:4] == b"RIFF"
    assert result.audio_bytes[8:12] == b"WAVE"
    assert result.provider_id == "local_qwen3_tts"
    assert result.model_id == MODEL_ID
    assert result.model_revision == MODEL_REVISION
    assert result.speaker_id == require_official_preset("qwen.WarmFemale").local_voice_id
    assert session.write_calls == []
    assert len(execution.requests) == 1
    novel_id, selection, request = execution.requests[0]
    assert novel_id == NOVEL_ID
    assert selection.provider_id == "local_qwen3_tts"
    assert selection.cloud_profile_id is None
    assert request.request_id.version == 4
    assert request.language == language
    assert request.voice.provider_voice_id == result.speaker_id
    assert request.text
    assert "novel text supplied by client" not in request.text


@pytest.mark.asyncio
async def test_missing_novel_scope_closes_session_and_never_calls_provider() -> None:
    session = RecordingSession()
    execution = RecordingExecution(session)

    def missing_scope(_session: RecordingSession, _novel_id: UUID) -> object:
        raise NovelLifecycleNotFound("missing")

    service = OfficialVoicePreviewAudioService(
        session_factory=lambda: session,  # type: ignore[arg-type,return-value]
        execution_service=execution,
        novel_scope_validator=missing_scope,  # type: ignore[arg-type]
    )

    with pytest.raises(OfficialVoicePreviewFailure) as captured:
        await service.preview(
            novel_id=NOVEL_ID,
            preset_id="qwen.WarmFemale",
            language="zh-CN",
        )

    assert captured.value.code == "TTS_PREVIEW_NOVEL_NOT_FOUND"
    assert session.closed is True
    assert session.write_calls == []
    assert execution.requests == []


def test_router_returns_wav_identity_headers_and_no_store() -> None:
    session = RecordingSession()
    execution = RecordingExecution(session)
    service = _service(execution, session)
    app = FastAPI()
    app.dependency_overrides[require_narration_t4_http_access] = lambda: None
    app.include_router(_router(service), prefix="/api/ai-novel-world-2026")

    with TestClient(app) as client:
        response = client.post(
            "/api/ai-novel-world-2026"
            + PREVIEW_ROUTE.format(novel_id=NOVEL_ID),
            json={"preset_id": "qwen.WarmFemale", "language": "zh-CN"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-tts-provider-id"] == "local_qwen3_tts"
    assert response.headers["x-tts-model-id"] == MODEL_ID
    assert response.headers["x-tts-model-revision"] == MODEL_REVISION
    assert response.headers["x-tts-speaker-id"] == "Serena"
    assert response.content[:4] == b"RIFF"


def test_router_rejects_unknown_language_extra_text_and_unknown_preset() -> None:
    session = RecordingSession()
    execution = RecordingExecution(session)
    service = _service(execution, session)
    app = FastAPI()
    app.dependency_overrides[require_narration_t4_http_access] = lambda: None
    app.include_router(_router(service))
    path = PREVIEW_ROUTE.format(novel_id=NOVEL_ID)

    with TestClient(app) as client:
        invalid_language = client.post(
            path,
            json={"preset_id": "qwen.WarmFemale", "language": "fr"},
        )
        client_text = client.post(
            path,
            json={
                "preset_id": "qwen.WarmFemale",
                "language": "zh-CN",
                "text": "novel text supplied by client",
            },
        )
        unknown_preset = client.post(
            path,
            json={"preset_id": "qwen.Unknown", "language": "zh-CN"},
        )

    assert invalid_language.status_code == 422
    assert client_text.status_code == 422
    assert unknown_preset.status_code == 404
    assert unknown_preset.json()["detail"]["code"] == "TTS_PREVIEW_PRESET_NOT_FOUND"
    assert execution.requests == []


@pytest.mark.asyncio
async def test_timeout_cancels_the_same_server_request_id() -> None:
    session = RecordingSession()
    execution = RecordingExecution(session, block=True)
    service = _service(execution, session, timeout_seconds=0.01)

    with pytest.raises(OfficialVoicePreviewFailure) as captured:
        await service.preview(
            novel_id=NOVEL_ID,
            preset_id="qwen.WarmFemale",
            language="zh-CN",
        )

    assert captured.value.code == "TTS_PROVIDER_TIMEOUT"
    assert len(execution.cancelled) == 1
    assert execution.cancelled[0][0].provider_id == "local_qwen3_tts"
    assert execution.cancelled[0][1] == execution.requests[0][2].request_id


@pytest.mark.asyncio
async def test_client_disconnect_and_task_cancellation_call_provider_cancel() -> None:
    session = RecordingSession()
    execution = RecordingExecution(session, block=True)
    service = _service(execution, session)
    disconnected = False

    async def probe() -> bool:
        return disconnected

    preview_task = asyncio.create_task(
        service.preview(
            novel_id=NOVEL_ID,
            preset_id="qwen.WarmFemale",
            language="zh-CN",
            disconnect_probe=probe,
        )
    )
    await execution.started.wait()
    disconnected = True
    with pytest.raises(OfficialVoicePreviewFailure) as disconnected_error:
        await preview_task
    assert disconnected_error.value.code == "TTS_PREVIEW_CLIENT_DISCONNECTED"
    assert len(execution.cancelled) == 1

    second_session = RecordingSession()
    second_execution = RecordingExecution(second_session, block=True)
    second_service = _service(second_execution, second_session)
    cancelled_task = asyncio.create_task(
        second_service.preview(
            novel_id=NOVEL_ID,
            preset_id="qwen.WarmFemale",
            language="zh-CN",
        )
    )
    await second_execution.started.wait()
    cancelled_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled_task
    assert len(second_execution.cancelled) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "override,max_bytes",
    [
        (
            SimpleNamespace(
                request_id=None,
                audio_bytes=_wav_bytes(),
                actual_output_sha256="b" * 64,
                sample_rate_hz=24_000,
                channels=1,
                sample_width_bytes=2,
                model_identity=_identity(),
                content_type="audio/wav",
            ),
            16 * 1024 * 1024,
        ),
        (
            SimpleNamespace(
                request_id=None,
                audio_bytes=b"RIFF-not-a-wave",
                actual_output_sha256=hashlib.sha256(b"RIFF-not-a-wave").hexdigest(),
                sample_rate_hz=24_000,
                channels=1,
                sample_width_bytes=2,
                model_identity=_identity(),
                content_type="audio/wav",
            ),
            16 * 1024 * 1024,
        ),
        (
            SimpleNamespace(
                request_id=None,
                audio_bytes=_wav_bytes(),
                actual_output_sha256=hashlib.sha256(_wav_bytes()).hexdigest(),
                sample_rate_hz=24_000,
                channels=1,
                sample_width_bytes=2,
                model_identity=_identity(TTSProviderId.ALIYUN_QWEN_AUDIO_TTS),
                content_type="audio/wav",
            ),
            16 * 1024 * 1024,
        ),
        (
            SimpleNamespace(
                request_id=None,
                audio_bytes=_wav_bytes(),
                actual_output_sha256=hashlib.sha256(_wav_bytes()).hexdigest(),
                sample_rate_hz=24_000,
                channels=1,
                sample_width_bytes=2,
                model_identity=_identity(),
                content_type="audio/mpeg",
            ),
            16 * 1024 * 1024,
        ),
    ],
)
async def test_invalid_hash_wav_identity_or_content_type_fails_closed(
    override: object,
    max_bytes: int,
) -> None:
    session = RecordingSession()
    execution = RecordingExecution(session, result_override=override)
    service = _service(execution, session, max_audio_bytes=max_bytes)

    with pytest.raises(TTSProviderError) as captured:
        await service.preview(
            novel_id=NOVEL_ID,
            preset_id="qwen.WarmFemale",
            language="zh-CN",
        )

    expected = (
        "TTS_MODEL_IDENTITY_MISMATCH"
        if override.model_identity.provider_id
        is TTSProviderId.ALIYUN_QWEN_AUDIO_TTS
        else "TTS_PROVIDER_RESPONSE_INVALID"
    )
    assert str(captured.value) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "identity",
    [
        _identity(model_id="mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit"),
        _identity(model_revision="0" * 40),
        _identity(artifact_tree_sha256="b" * 64),
    ],
)
async def test_preview_rejects_the_wrong_local_model_identity(
    identity: TTSModelIdentity,
) -> None:
    audio = _wav_bytes()
    override = SimpleNamespace(
        request_id=None,
        audio_bytes=audio,
        actual_output_sha256=hashlib.sha256(audio).hexdigest(),
        sample_rate_hz=24_000,
        channels=1,
        sample_width_bytes=2,
        model_identity=identity,
        content_type="audio/wav",
    )
    session = RecordingSession()
    execution = RecordingExecution(session, result_override=override)

    with pytest.raises(TTSProviderError) as captured:
        await _service(execution, session).preview(
            novel_id=NOVEL_ID,
            preset_id="qwen.WarmFemale",
            language="zh-CN",
        )

    assert str(captured.value) == "TTS_MODEL_IDENTITY_MISMATCH"


@pytest.mark.asyncio
async def test_audio_size_limit_is_enforced_without_persistence() -> None:
    audio = _wav_bytes()
    override = SimpleNamespace(
        request_id=None,
        audio_bytes=audio,
        actual_output_sha256=hashlib.sha256(audio).hexdigest(),
        sample_rate_hz=24_000,
        channels=1,
        sample_width_bytes=2,
        model_identity=_identity(),
        content_type="audio/wav",
    )
    session = RecordingSession()
    execution = RecordingExecution(session, result_override=override)
    service = _service(execution, session, max_audio_bytes=len(audio) - 1)

    with pytest.raises(TTSProviderError) as captured:
        await service.preview(
            novel_id=NOVEL_ID,
            preset_id="qwen.WarmFemale",
            language="zh-CN",
        )

    assert str(captured.value) == "TTS_PROVIDER_RESPONSE_INVALID"
    assert session.write_calls == []
