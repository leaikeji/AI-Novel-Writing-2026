from __future__ import annotations

import base64
import hashlib
from uuid import uuid4

import httpx
import pytest

from backend.narration.contracts import (
    AdapterHealthStatus,
    CancelDisposition,
    NarrationRequestScope,
    ReferenceAudioInput,
    TTSSynthesisRequest,
    TTSVoiceInput,
    TTSVoiceKind,
    TTSVoicePreparationRequest,
)
from backend.narration.providers.base import TTSProviderError
from backend.narration.providers.local import (
    LOCAL_QWEN_CAPABILITIES_SHA256,
    LOCAL_TTS_PROTOCOL_HEADER,
    LOCAL_TTS_PROTOCOL_VERSION,
    LocalQwenTTSConfig,
    LocalQwenTTSProvider,
    local_auth_token_from_env,
)
from tts_runtime.server import create_app
from tts_runtime.__main__ import main as run_local_runtime
from tts_runtime.service import (
    DEFAULT_MODELS,
    DeterministicFakeBackend,
    LocalRuntimeService,
    MLXAudioBackend,
    ModelManager,
    ModelRole,
    _mlx_language,
)


def _request(text: str = "不会出现在错误信息里的正文") -> TTSSynthesisRequest:
    return TTSSynthesisRequest(
        request_id=uuid4(),
        scope=NarrationRequestScope.fixed_local(),
        text=text,
        language="zh-CN",
        voice=TTSVoiceInput(
            kind=TTSVoiceKind.PRESET,
            provider_voice_id="Vivian",
        ),
        seed=2026,
        instruction="自然、沉稳",
    )


@pytest.mark.asyncio
async def test_local_provider_round_trip_against_deterministic_runtime() -> None:
    backend = DeterministicFakeBackend()
    app = create_app(LocalRuntimeService(ModelManager(backend)), auth_token="local-secret")
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://local-runtime",
    )
    provider = LocalQwenTTSProvider(
        LocalQwenTTSConfig(
            base_url="http://local-runtime",
            auth_token="local-secret",
        ),
        client=client,
    )

    before = await provider.health()
    assert before.status is AdapterHealthStatus.DEGRADED
    assert before.capabilities_sha256 == LOCAL_QWEN_CAPABILITIES_SHA256

    result = await provider.synthesize(_request())
    assert result.audio_bytes.startswith(b"RIFF")
    assert result.actual_output_sha256 == hashlib.sha256(result.audio_bytes).hexdigest()
    assert result.model_identity.model_id == DEFAULT_MODELS[ModelRole.CUSTOM_VOICE].model_id

    after = await provider.health()
    assert after.status is AdapterHealthStatus.HEALTHY
    await provider.aclose()


@pytest.mark.asyncio
async def test_clone_design_cancel_and_model_switches_share_one_runtime_slot() -> None:
    backend = DeterministicFakeBackend()
    app = create_app(LocalRuntimeService(ModelManager(backend)))
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://local-runtime",
    )
    provider = LocalQwenTTSProvider(
        LocalQwenTTSConfig(base_url="http://local-runtime"),
        client=client,
    )
    reference_bytes = b"RIFF-reference-fixture"
    reference = ReferenceAudioInput(
        audio_bytes=reference_bytes,
        actual_sha256=hashlib.sha256(reference_bytes).hexdigest(),
    )

    clone = await provider.clone_voice(
        TTSVoicePreparationRequest(
            request_id=uuid4(),
            scope=NarrationRequestScope.fixed_local(),
            preview_text="克隆试听",
            language="zh-CN",
            reference_audio=reference,
            reference_text="参考文本",
        )
    )
    assert clone.voice_kind is TTSVoiceKind.REFERENCE_CLONE
    assert clone.model_identity.model_id == DEFAULT_MODELS[ModelRole.BASE].model_id

    design = await provider.design_voice(
        TTSVoicePreparationRequest(
            request_id=uuid4(),
            scope=NarrationRequestScope.fixed_local(),
            preview_text="设计试听",
            language="zh-CN",
            description="温和清晰的青年女声",
        )
    )
    assert design.voice_kind is TTSVoiceKind.DESIGNED
    assert design.model_identity.model_id == DEFAULT_MODELS[ModelRole.VOICE_DESIGN].model_id

    assert await provider.cancel(uuid4()) is CancelDisposition.REQUESTED
    assert backend.loads == [
        DEFAULT_MODELS[ModelRole.BASE].model_id,
        DEFAULT_MODELS[ModelRole.VOICE_DESIGN].model_id,
    ]
    assert backend.unloads == [DEFAULT_MODELS[ModelRole.BASE].model_id]
    await provider.aclose()


@pytest.mark.asyncio
async def test_designed_anchor_survives_restart_and_base_uses_only_durable_material() -> None:
    class RecordingBackend(DeterministicFakeBackend):
        def __init__(self) -> None:
            super().__init__()
            self.calls: list[dict[str, object]] = []

        def generate(self, model: object, **kwargs: object):  # type: ignore[no-untyped-def]
            self.calls.append(dict(kwargs))
            return super().generate(model, **kwargs)

    backend = RecordingBackend()
    anchor_text = "晨光落在窗边，她用清晰自然的普通话讲述故事。"
    first_process = LocalRuntimeService(ModelManager(backend))
    designed = await first_process.prepare_voice(
        {
            "request_id": str(uuid4()),
            "preview_text": anchor_text,
            "language": "zh-CN",
            "description": "温和清晰的青年女声",
            "seed": 2026,
        },
        kind=TTSVoiceKind.DESIGNED,
    )
    anchor_audio = base64.b64decode(str(designed["preview_audio_base64"]), validate=True)
    anchor_sha256 = hashlib.sha256(anchor_audio).hexdigest()

    assert designed["provider_voice_id"].startswith("local:designed_reference:")
    assert designed["actual_output_sha256"] == anchor_sha256
    assert backend.loads == [DEFAULT_MODELS[ModelRole.VOICE_DESIGN].model_id]

    # A new service has no process-local voice registry.  Base can still clone
    # from the persisted anchor WAV and the original anchor text alone.
    await first_process.shutdown()
    restarted_process = LocalRuntimeService(ModelManager(backend))
    result = await restarted_process.synthesize(
        {
            "request_id": str(uuid4()),
            "text": "这是服务重启后的另一段试听文本。",
            "language": "zh-CN",
            "voice": {
                "kind": TTSVoiceKind.REFERENCE_CLONE.value,
                "provider_voice_id": f"local:reference_clone:{anchor_sha256}",
                "reference_audio_base64": base64.b64encode(anchor_audio).decode("ascii"),
                "reference_audio_sha256": anchor_sha256,
                "reference_audio_content_type": "audio/wav",
                "reference_text": anchor_text,
            },
            "seed": 2026,
        }
    )

    assert base64.b64decode(str(result["audio_base64"]), validate=True).startswith(b"RIFF")
    assert backend.loads == [
        DEFAULT_MODELS[ModelRole.VOICE_DESIGN].model_id,
        DEFAULT_MODELS[ModelRole.BASE].model_id,
    ]
    assert backend.unloads == [DEFAULT_MODELS[ModelRole.VOICE_DESIGN].model_id]
    assert backend.calls[1]["voice_id"] is None
    assert backend.calls[1]["reference_audio"] == anchor_audio
    assert backend.calls[1]["reference_text"] == anchor_text


@pytest.mark.asyncio
async def test_designed_voice_id_cannot_be_used_for_production_synthesis() -> None:
    backend = DeterministicFakeBackend()
    service = LocalRuntimeService(ModelManager(backend))

    with pytest.raises(RuntimeError, match="TTS_VOICE_UNAVAILABLE"):
        await service.synthesize(
            {
                "request_id": str(uuid4()),
                "text": "不能直接使用声音设计临时身份。",
                "language": "zh-CN",
                "voice": {
                    "kind": TTSVoiceKind.DESIGNED.value,
                    "provider_voice_id": "local:designed_reference:not-a-production-voice",
                },
            }
        )

    assert backend.loads == []


@pytest.mark.asyncio
async def test_reference_clone_rejects_missing_text_or_mismatched_audio_digest() -> None:
    backend = DeterministicFakeBackend()
    service = LocalRuntimeService(ModelManager(backend))
    reference_audio = b"RIFF-durable-reference"
    encoded = base64.b64encode(reference_audio).decode("ascii")

    for reference_text, digest in (
        (None, hashlib.sha256(reference_audio).hexdigest()),
        ("准确的参考文本", "0" * 64),
    ):
        with pytest.raises(ValueError, match="INVALID_REQUEST"):
            await service.synthesize(
                {
                    "request_id": str(uuid4()),
                    "text": "复刻试听",
                    "language": "zh-CN",
                    "voice": {
                        "kind": TTSVoiceKind.REFERENCE_CLONE.value,
                        "provider_voice_id": "local:reference_clone:test",
                        "reference_audio_base64": encoded,
                        "reference_audio_sha256": digest,
                        "reference_text": reference_text,
                    },
                }
            )

    assert backend.loads == []


@pytest.mark.asyncio
async def test_protocol_or_identity_mismatch_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            headers={
                "content-type": "application/json",
                LOCAL_TTS_PROTOCOL_HEADER: "unknown-protocol/99",
            },
            json={
                "status": "degraded",
                "capabilities_sha256": LOCAL_QWEN_CAPABILITIES_SHA256,
                "model_fingerprint_sha256": None,
                "reason_code": None,
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://local-runtime",
    )
    provider = LocalQwenTTSProvider(
        LocalQwenTTSConfig(base_url="http://local-runtime"),
        client=client,
    )
    with pytest.raises(TTSProviderError) as captured:
        await provider.health()
    assert captured.value.code == "TTS_MODEL_IDENTITY_MISMATCH"
    await provider.aclose()


@pytest.mark.asyncio
async def test_runtime_error_is_stable_and_does_not_leak_text() -> None:
    sensitive_text = "绝不能泄露的小说正文"

    async def handler(request: httpx.Request) -> httpx.Response:
        assert sensitive_text in request.content.decode("utf-8")
        return httpx.Response(
            503,
            headers={
                "content-type": "application/json",
                LOCAL_TTS_PROTOCOL_HEADER: LOCAL_TTS_PROTOCOL_VERSION,
            },
            json={"error": {"code": "TTS_PROVIDER_UNAVAILABLE"}},
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://local-runtime",
    )
    provider = LocalQwenTTSProvider(
        LocalQwenTTSConfig(base_url="http://local-runtime"),
        client=client,
    )
    with pytest.raises(TTSProviderError) as captured:
        await provider.synthesize(_request(sensitive_text))
    assert str(captured.value) == "TTS_PROVIDER_UNAVAILABLE"
    assert sensitive_text not in repr(captured.value)
    await provider.aclose()


@pytest.mark.asyncio
async def test_model_manager_unloads_before_switch_and_keeps_one_model() -> None:
    backend = DeterministicFakeBackend()
    manager = ModelManager(backend)
    await manager.warmup(ModelRole.CUSTOM_VOICE)
    await manager.warmup(ModelRole.BASE)
    await manager.warmup(ModelRole.VOICE_DESIGN)

    assert backend.loads == [
        DEFAULT_MODELS[ModelRole.CUSTOM_VOICE].model_id,
        DEFAULT_MODELS[ModelRole.BASE].model_id,
        DEFAULT_MODELS[ModelRole.VOICE_DESIGN].model_id,
    ]
    assert backend.unloads == [
        DEFAULT_MODELS[ModelRole.CUSTOM_VOICE].model_id,
        DEFAULT_MODELS[ModelRole.BASE].model_id,
    ]
    assert manager.loaded_role is ModelRole.VOICE_DESIGN


@pytest.mark.asyncio
async def test_runtime_shutdown_unloads_final_model_and_is_idempotent() -> None:
    backend = DeterministicFakeBackend()
    service = LocalRuntimeService(ModelManager(backend))
    app = create_app(service)
    await service.warmup(ModelRole.CUSTOM_VOICE)

    async with app.router.lifespan_context(app):
        assert service.health_payload()["status"] == "healthy"

    assert backend.unloads == [DEFAULT_MODELS[ModelRole.CUSTOM_VOICE].model_id]
    assert service.health_payload()["status"] == "degraded"

    await service.shutdown()
    assert backend.unloads == [DEFAULT_MODELS[ModelRole.CUSTOM_VOICE].model_id]


def test_mlx_dependency_check_does_not_import_mlx(monkeypatch: pytest.MonkeyPatch) -> None:
    inspected: list[str] = []

    def fake_find_spec(name: str):  # type: ignore[no-untyped-def]
        inspected.append(name)
        return None

    monkeypatch.setattr("importlib.util.find_spec", fake_find_spec)
    backend = MLXAudioBackend()
    assert backend.dependency_available() is False
    assert inspected == ["mlx_audio"]


@pytest.mark.asyncio
async def test_missing_mlx_dependency_health_is_fail_closed() -> None:
    class MissingBackend(DeterministicFakeBackend):
        def dependency_available(self) -> bool:
            return False

    service = LocalRuntimeService(ModelManager(MissingBackend()))
    health = service.health_payload()
    assert health == {
        "status": "unavailable",
        "capabilities_sha256": LOCAL_QWEN_CAPABILITIES_SHA256,
        "model_fingerprint_sha256": None,
        "reason_code": "MLX_RUNTIME_DEPENDENCY_UNAVAILABLE",
    }
    with pytest.raises(RuntimeError, match="MLX_RUNTIME_DEPENDENCY_UNAVAILABLE"):
        await service.warmup(ModelRole.CUSTOM_VOICE)


def test_local_runtime_config_defaults_to_native_mac_bridge() -> None:
    config = LocalQwenTTSConfig()
    assert config.base_url == "http://host.docker.internal:8766"


def test_local_runtime_config_reads_token_file_without_repr_leak(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token_file = tmp_path / "qwen-token"
    token_file.write_text("a-secret-local-token\n", encoding="utf-8")
    monkeypatch.setenv("QWEN_TTS_LOCAL_TOKEN_FILE", str(token_file))
    monkeypatch.delenv("QWEN_TTS_LOCAL_TOKEN", raising=False)

    config = LocalQwenTTSConfig.from_env()

    assert config.auth_token == "a-secret-local-token"
    assert "a-secret-local-token" not in repr(config)


def test_local_runtime_rejects_ambiguous_token_sources(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token_file = tmp_path / "qwen-token"
    token_file.write_text("file-token", encoding="utf-8")
    monkeypatch.setenv("QWEN_TTS_LOCAL_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("QWEN_TTS_LOCAL_TOKEN", "inline-token")

    with pytest.raises(ValueError, match="only one"):
        local_auth_token_from_env()


def test_mlx_bridge_consumes_generator_result_and_maps_bcp47_language() -> None:
    class Audio:
        def tolist(self) -> list[float]:
            return [0.0, 0.1, -0.1]

    class Result:
        audio = Audio()
        sample_rate = 24_000

    class Model:
        def __init__(self) -> None:
            self.kwargs: dict[str, object] = {}

        def generate(self, **kwargs: object):  # type: ignore[no-untyped-def]
            self.kwargs = dict(kwargs)
            yield Result()

    model = Model()
    generated = MLXAudioBackend().generate(
        model,
        text="测试",
        language="zh-CN",
        voice_id="Vivian",
        instruction=None,
        reference_audio=None,
        reference_text=None,
        seed=None,
    )

    assert generated.audio_bytes.startswith(b"RIFF")
    assert model.kwargs["lang_code"] == "chinese"
    assert model.kwargs["split_pattern"] == ""
    assert _mlx_language("en-US") == "english"
    assert _mlx_language("unknown") == "auto"


def test_non_loopback_runtime_requires_shared_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QWEN_TTS_LOCAL_BIND", "0.0.0.0")
    monkeypatch.delenv("QWEN_TTS_LOCAL_TOKEN", raising=False)
    monkeypatch.delenv("QWEN_TTS_LOCAL_TOKEN_FILE", raising=False)

    with pytest.raises(RuntimeError, match="QWEN_TTS_LOCAL_TOKEN"):
        run_local_runtime()
