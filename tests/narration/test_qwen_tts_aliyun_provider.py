from __future__ import annotations

import base64
import hashlib
import io
import wave
from typing import Any
from uuid import uuid4

import httpx
import pytest

import backend.narration.providers.aliyun as aliyun_provider_module

from backend.narration.contracts import (
    AdapterHealthStatus,
    CancelDisposition,
    NarrationRequestScope,
    ReferenceAudioInput,
    TTSProviderId,
    TTSSynthesisRequest,
    TTSVoiceInput,
    TTSVoiceKind,
    TTSVoicePreparationRequest,
)
from backend.narration.providers import TTSProviderError
from backend.narration.providers.aliyun import (
    ALIYUN_QWEN_AUDIO_TTS_FLASH,
    ALIYUN_QWEN_AUDIO_TTS_PLUS,
    SYNTHESIS_PATH,
    VOICE_CUSTOMIZATION_PATH,
    AliyunQwenAudioTTSProvider,
)

BASE_URL = "https://workspace.cn-beijing.maas.aliyuncs.com"
AUDIO_URL = "https://audio.example.test/result.wav"
API_KEY = "test-secret-that-must-never-be-exposed"
PUBLIC_IP = "8.8.8.8"


def _wav_bytes(*, sample_rate: int = 24_000) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * 24)
    return output.getvalue()


def _reference() -> ReferenceAudioInput:
    audio = _wav_bytes(sample_rate=16_000)
    return ReferenceAudioInput(
        audio_bytes=audio,
        actual_sha256=hashlib.sha256(audio).hexdigest(),
    )


def _synthesis_request(
    *, model_voice: str = "longanhuan_v3.6", seed: int | None = 7
) -> TTSSynthesisRequest:
    return TTSSynthesisRequest(
        request_id=uuid4(),
        scope=NarrationRequestScope.fixed_local(),
        text="这是一段云端朗读。",
        language="zh-CN",
        voice=TTSVoiceInput(
            kind=TTSVoiceKind.PRESET,
            provider_voice_id=model_voice,
        ),
        seed=seed,
        instruction="自然、沉稳",
    )


def _synthesis_response() -> dict[str, object]:
    return {
        "request_id": "vendor-request-id",
        "output": {
            "finish_reason": "stop",
            "audio": {"data": "", "url": AUDIO_URL, "id": "audio-id"},
        },
        "usage": {"characters": 10},
    }


def _synthesis_response_with_audio_url(audio_url: str) -> dict[str, object]:
    response = _synthesis_response()
    output = response["output"]
    assert isinstance(output, dict)
    audio = output["audio"]
    assert isinstance(audio, dict)
    audio["url"] = audio_url
    return response


def _provider(
    handler,
    *,
    model_id: str = ALIYUN_QWEN_AUDIO_TTS_PLUS,
    api_key: str = API_KEY,
    base_url: str = BASE_URL,
    reference_audio_url_factory=None,
    host_resolver=None,
    product_released: bool = False,
) -> AliyunQwenAudioTTSProvider:
    return AliyunQwenAudioTTSProvider(
        api_key=api_key,
        base_url=base_url,
        model_id=model_id,
        transport=httpx.MockTransport(handler),
        reference_audio_url_factory=reference_audio_url_factory,
        host_resolver=host_resolver or (lambda _host, _port: (PUBLIC_IP,)),
        product_released=product_released,
    )


@pytest.mark.asyncio
async def test_capabilities_identity_health_and_no_secret_repr() -> None:
    provider = _provider(lambda _request: httpx.Response(500))

    assert provider.capabilities.provider_id is TTSProviderId.ALIYUN_QWEN_AUDIO_TTS
    assert provider.capabilities.supports_reference_clone is True
    assert provider.capabilities.supports_voice_design is True
    assert provider.capabilities.supports_streaming_first_audio is False
    assert provider.capabilities.supports_cancel is False
    assert provider.capabilities.production_ready is False
    assert await provider.cancel(uuid4()) is CancelDisposition.UNSUPPORTED
    identity = await provider.model_identity()
    assert identity.model_id == ALIYUN_QWEN_AUDIO_TTS_PLUS
    assert identity.quantization == "managed"
    assert (await provider.health()).status is AdapterHealthStatus.DEGRADED
    assert (await provider.health()).reason_code == "TTS_PROVIDER_NOT_PROBED"
    assert (await provider.warmup()).status is AdapterHealthStatus.DEGRADED
    assert API_KEY not in repr(provider)

    disabled = _provider(lambda _request: httpx.Response(500), api_key="")
    disabled_health = await disabled.health()
    assert disabled_health.status is AdapterHealthStatus.DISABLED
    assert disabled_health.reason_code == "TTS_PROVIDER_DISABLED"


def test_product_release_is_an_explicit_switch() -> None:
    provider = _provider(
        lambda _request: httpx.Response(500),
        product_released=True,
    )

    assert provider.capabilities.product_visible is True
    assert provider.capabilities.production_ready is True


def test_accepts_channel_model_alias_and_rejects_unsafe_model_ids() -> None:
    provider = AliyunQwenAudioTTSProvider(
        api_key=API_KEY,
        base_url="https://member-gateway.example.com/qwen",
        model_id="member/qwen-tts-premium-v7",
    )
    assert "member/qwen-tts-premium-v7" in repr(provider)

    for model_id in ("", "   ", "qwen\nprivate"):
        with pytest.raises(ValueError, match="model ID"):
            AliyunQwenAudioTTSProvider(
                api_key=API_KEY,
                base_url=BASE_URL,
                model_id=model_id,
            )


@pytest.mark.parametrize(
    "base_url",
    [
        "http://gateway.example.com",
        "https://user:secret@gateway.example.com",
        "https://gateway.example.com?tenant=author",
        "https://gateway.example.com/#private",
        "https://localhost/qwen",
        "https://127.0.0.1/qwen",
        "https://10.1.2.3/qwen",
        "https://169.254.169.254/latest/meta-data",
        "https://0.0.0.0/qwen",
        "https://192.0.2.1/qwen",
        "https://224.0.0.1/qwen",
        "https://[::1]/qwen",
        "https://[ff02::1]/qwen",
        "https://gateway.example.com:0/qwen",
        "https://gateway.example.com:99999/qwen",
        "https://bad host.example.com/qwen",
        "https://./qwen",
        "https://gateway.example.com/qwen\\private",
    ],
)
def test_rejects_unsafe_or_non_public_base_urls(base_url: str) -> None:
    with pytest.raises(
        ValueError,
        match="HTTPS URL|public host|unsafe path|invalid host",
    ):
        AliyunQwenAudioTTSProvider(
            api_key=API_KEY,
            base_url=base_url,
        )


@pytest.mark.asyncio
async def test_public_gateway_path_prefix_is_normalized_and_kept() -> None:
    called_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        called_urls.append(str(request.url))
        return httpx.Response(401, json={"code": "InvalidApiKey"})

    provider = _provider(
        handler,
        base_url="https://MEMBER-GATEWAY.example.com/member//v1/../tenant/",
    )
    with pytest.raises(TTSProviderError, match="TTS_PROVIDER_AUTH_FAILED"):
        await provider.synthesize(_synthesis_request())

    assert called_urls == [
        "https://member-gateway.example.com/member/tenant" + SYNTHESIS_PATH
    ]


@pytest.mark.asyncio
async def test_synthesize_maps_plus_payload_and_downloads_valid_wav() -> None:
    calls: list[tuple[str, str, dict[str, Any] | None]] = []
    audio = _wav_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        body = None if request.method == "GET" else _json_body(request)
        calls.append((request.method, str(request.url), body))
        if request.method == "POST":
            assert request.headers["Authorization"] == f"Bearer {API_KEY}"
            return httpx.Response(200, json=_synthesis_response())
        return httpx.Response(200, content=audio, headers={"Content-Type": "audio/wav"})

    provider = _provider(handler)
    result = await provider.synthesize(_synthesis_request(seed=65_537))

    assert calls[0][0:2] == ("POST", f"{BASE_URL}{SYNTHESIS_PATH}")
    assert calls[0][2] == {
        "model": ALIYUN_QWEN_AUDIO_TTS_PLUS,
        "input": {
            "text": "这是一段云端朗读。",
            "voice": "longanhuan_v3.6",
            "format": "wav",
            "sample_rate": 24_000,
            "language_hints": ["zh"],
            "instruction": "自然、沉稳",
            "seed": 1,
        },
    }
    assert calls[1][0:2] == ("GET", AUDIO_URL)
    assert result.audio_bytes == audio
    assert result.sample_rate_hz == 24_000
    assert result.channels == 1
    assert result.sample_width_bytes == 2
    assert result.model_identity.model_id == ALIYUN_QWEN_AUDIO_TTS_PLUS


@pytest.mark.asyncio
async def test_synthesize_upgrades_documented_aliyun_http_audio_url_to_https() -> None:
    http_audio_url = (
        "http://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/pre/result.wav"
        "?Expires=123&Signature=signed"
    )
    expected_https_url = http_audio_url.replace("http://", "https://", 1)
    calls: list[str] = []
    audio = _wav_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.method == "POST":
            return httpx.Response(
                200,
                json=_synthesis_response_with_audio_url(http_audio_url),
            )
        return httpx.Response(200, content=audio, headers={"Content-Type": "audio/wav"})

    result = await _provider(handler).synthesize(_synthesis_request())

    assert calls == [f"{BASE_URL}{SYNTHESIS_PATH}", expected_https_url]
    assert result.audio_bytes == audio


@pytest.mark.asyncio
async def test_synthesize_rejects_non_aliyun_http_audio_url() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(
            200,
            json=_synthesis_response_with_audio_url(
                "http://audio.example.test/result.wav"
            ),
        )

    with pytest.raises(TTSProviderError) as captured:
        await _provider(handler).synthesize(_synthesis_request())

    assert captured.value.code == "TTS_PROVIDER_RESPONSE_INVALID"
    assert calls == [f"{BASE_URL}{SYNTHESIS_PATH}"]


@pytest.mark.asyncio
async def test_flash_is_an_explicit_model_not_a_fallback() -> None:
    posted_models: list[str] = []
    audio = _wav_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            posted_models.append(_json_body(request)["model"])
            return httpx.Response(200, json=_synthesis_response())
        return httpx.Response(200, content=audio)

    provider = _provider(handler, model_id=ALIYUN_QWEN_AUDIO_TTS_FLASH)
    result = await provider.synthesize(_synthesis_request())

    assert posted_models == [ALIYUN_QWEN_AUDIO_TTS_FLASH]
    assert result.model_identity.model_id == ALIYUN_QWEN_AUDIO_TTS_FLASH


@pytest.mark.asyncio
async def test_channel_model_alias_is_sent_unchanged_without_fallback() -> None:
    posted_models: list[str] = []
    audio = _wav_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            posted_models.append(_json_body(request)["model"])
            return httpx.Response(200, json=_synthesis_response())
        return httpx.Response(200, content=audio)

    provider = _provider(handler, model_id="member-qwen-tts-quality-2026")
    result = await provider.synthesize(_synthesis_request())

    assert posted_models == ["member-qwen-tts-quality-2026"]
    assert result.model_identity.model_id == "member-qwen-tts-quality-2026"


@pytest.mark.asyncio
async def test_clone_maps_public_reference_url_then_synthesizes_preview() -> None:
    posts: list[tuple[str, dict[str, Any]]] = []
    audio = _wav_bytes()
    reference = _reference()

    async def reference_url_factory(received: ReferenceAudioInput) -> str:
        assert received.actual_sha256 == reference.actual_sha256
        return "https://author-media.example.test/reference.wav"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, content=audio)
        body = _json_body(request)
        posts.append((request.url.path, body))
        if request.url.path == VOICE_CUSTOMIZATION_PATH:
            return httpx.Response(
                200,
                json={
                    "request_id": "vendor-clone-id",
                    "output": {"voice_id": "qwen-audio-clone-123"},
                    "usage": {"count": 1},
                },
            )
        return httpx.Response(200, json=_synthesis_response())

    provider = _provider(handler, reference_audio_url_factory=reference_url_factory)
    request = TTSVoicePreparationRequest(
        request_id=uuid4(),
        scope=NarrationRequestScope.fixed_local(),
        preview_text="这是复刻试听。",
        language="zh-CN",
        reference_audio=reference,
        reference_text="参考文本不会误发到不支持该字段的 API。",
        seed=8,
    )
    result = await provider.clone_voice(request)

    assert posts[0][0] == VOICE_CUSTOMIZATION_PATH
    assert posts[0][1]["model"] == "voice-enrollment"
    assert posts[0][1]["input"] == {
        "action": "create_voice",
        "target_model": ALIYUN_QWEN_AUDIO_TTS_PLUS,
        "prefix": f"v{request.request_id.hex[:9]}",
        "url": "https://author-media.example.test/reference.wav",
        "language_hints": ["zh"],
    }
    assert posts[1][0] == SYNTHESIS_PATH
    assert posts[1][1]["input"]["voice"] == "qwen-audio-clone-123"
    assert result.provider_voice_id == "qwen-audio-clone-123"
    assert result.voice_kind is TTSVoiceKind.REFERENCE_CLONE
    assert result.preview_audio_bytes == audio


@pytest.mark.asyncio
async def test_clone_requires_an_injected_reference_url_boundary() -> None:
    provider = _provider(lambda _request: httpx.Response(500))
    request = TTSVoicePreparationRequest(
        request_id=uuid4(),
        scope=NarrationRequestScope.fixed_local(),
        preview_text="试听",
        language="zh-CN",
        reference_audio=_reference(),
    )

    with pytest.raises(TTSProviderError) as captured:
        await provider.clone_voice(request)
    assert captured.value.code == "TTS_PROVIDER_UNAVAILABLE"
    assert captured.value.retryable is False


@pytest.mark.asyncio
async def test_design_voice_maps_contract_and_decodes_preview_wav() -> None:
    audio = _wav_bytes()
    posted: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        posted.append(_json_body(request))
        return httpx.Response(
            200,
            json={
                "request_id": "vendor-design-id",
                "output": {
                    "voice_id": "qwen-audio-designed-123",
                    "target_model": ALIYUN_QWEN_AUDIO_TTS_PLUS,
                    "preview_audio": {
                        "data": base64.b64encode(audio).decode("ascii"),
                        "sample_rate": 24_000,
                        "response_format": "wav",
                    },
                },
                "usage": {"count": 1},
            },
        )

    provider = _provider(handler)
    request = TTSVoicePreparationRequest(
        request_id=uuid4(),
        scope=NarrationRequestScope.fixed_local(),
        preview_text="这是设计试听。",
        language="zh-CN",
        description="沉稳、清晰的中年女性声音",
        seed=9,
    )
    result = await provider.design_voice(request)

    assert posted == [
        {
            "model": "voice-enrollment",
            "input": {
                "action": "create_voice",
                "target_model": ALIYUN_QWEN_AUDIO_TTS_PLUS,
                "voice_prompt": "沉稳、清晰的中年女性声音",
                "preview_text": "这是设计试听。",
                "prefix": f"v{request.request_id.hex[:9]}",
                "language_hints": ["zh"],
            },
            "parameters": {"sample_rate": 24_000, "response_format": "wav"},
        }
    ]
    assert result.provider_voice_id == "qwen-audio-designed-123"
    assert result.voice_kind is TTSVoiceKind.DESIGNED
    assert result.preview_audio_bytes == audio


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "body", "expected_code", "retryable"),
    [
        (401, {"code": "InvalidApiKey", "message": API_KEY}, "TTS_PROVIDER_AUTH_FAILED", False),
        (
            429,
            {"code": "Throttling.RateQuota", "message": "private text"},
            "TTS_PROVIDER_RATE_LIMITED",
            True,
        ),
        (
            503,
            {"code": "InternalError", "message": "private text"},
            "TTS_PROVIDER_UNAVAILABLE",
            True,
        ),
    ],
)
async def test_http_failures_are_stable_and_redacted(
    status_code: int,
    body: dict[str, str],
    expected_code: str,
    retryable: bool,
) -> None:
    provider = _provider(lambda _request: httpx.Response(status_code, json=body))

    with pytest.raises(TTSProviderError) as captured:
        await provider.synthesize(_synthesis_request())
    assert captured.value.code == expected_code
    assert captured.value.retryable is retryable
    assert str(captured.value) == expected_code
    assert API_KEY not in str(captured.value)
    assert body["message"] not in str(captured.value)


@pytest.mark.asyncio
async def test_timeout_is_retryable_and_redacted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("response leaked author text", request=request)

    provider = _provider(handler)
    with pytest.raises(TTSProviderError) as captured:
        await provider.synthesize(_synthesis_request())
    assert captured.value.code == "TTS_PROVIDER_TIMEOUT"
    assert captured.value.retryable is True
    assert "author text" not in str(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__suppress_context__ is True


@pytest.mark.asyncio
async def test_dns_resolution_blocks_private_or_mixed_addresses_before_network() -> None:
    network_called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal network_called
        network_called = True
        return httpx.Response(200)

    for addresses in (("127.0.0.1",), (PUBLIC_IP, "10.0.0.8")):
        provider = _provider(
            handler,
            base_url="https://membership.example.com/qwen",
            host_resolver=lambda _host, _port, result=addresses: result,
        )
        with pytest.raises(TTSProviderError) as captured:
            await provider.synthesize(_synthesis_request())
        assert captured.value.code == "TTS_PROVIDER_RESPONSE_INVALID"
        assert captured.value.retryable is False
    assert network_called is False


@pytest.mark.asyncio
async def test_audio_result_dns_is_revalidated_before_download() -> None:
    methods: list[str] = []

    def resolver(host: str, _port: int):
        return ("10.0.0.9",) if host == "audio.example.test" else (PUBLIC_IP,)

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return httpx.Response(200, json=_synthesis_response())

    provider = _provider(handler, host_resolver=resolver)
    with pytest.raises(TTSProviderError) as captured:
        await provider.synthesize(_synthesis_request())

    assert captured.value.code == "TTS_PROVIDER_RESPONSE_INVALID"
    assert methods == ["POST"]


@pytest.mark.asyncio
async def test_redirects_are_never_followed() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(307, headers={"Location": "https://redirect.example/private"})

    provider = _provider(handler)
    with pytest.raises(TTSProviderError) as captured:
        await provider.synthesize(_synthesis_request())

    assert captured.value.code == "TTS_PROVIDER_RESPONSE_INVALID"
    assert calls == [f"{BASE_URL}{SYNTHESIS_PATH}"]

    def audio_redirect_handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.method == "POST":
            return httpx.Response(200, json=_synthesis_response())
        return httpx.Response(
            302,
            headers={"Location": "https://redirect.example/private.wav"},
        )

    audio_redirect = _provider(audio_redirect_handler)
    with pytest.raises(TTSProviderError) as audio_error:
        await audio_redirect.synthesize(_synthesis_request())
    assert audio_error.value.code == "TTS_PROVIDER_RESPONSE_INVALID"
    assert calls[-2:] == [f"{BASE_URL}{SYNTHESIS_PATH}", AUDIO_URL]


@pytest.mark.asyncio
async def test_http_client_ignores_environment_proxies_and_disables_redirects() -> None:
    provider = _provider(lambda _request: httpx.Response(500))
    client = provider._new_client()
    try:
        assert client._trust_env is False
        assert client.follow_redirects is False
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_json_and_audio_responses_are_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(aliyun_provider_module, "MAX_JSON_RESPONSE_BYTES", 64)
    oversized_json = _provider(
        lambda _request: httpx.Response(200, content=b"x" * 65)
    )
    with pytest.raises(TTSProviderError) as json_error:
        await oversized_json.synthesize(_synthesis_request())
    assert json_error.value.code == "TTS_PROVIDER_RESPONSE_INVALID"

    monkeypatch.setattr(aliyun_provider_module, "MAX_JSON_RESPONSE_BYTES", 1_024)
    monkeypatch.setattr(aliyun_provider_module, "MAX_AUDIO_RESPONSE_BYTES", 64)

    def audio_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json=_synthesis_response())
        return httpx.Response(200, content=b"x" * 65)

    oversized_audio = _provider(audio_handler)
    with pytest.raises(TTSProviderError) as audio_error:
        await oversized_audio.synthesize(_synthesis_request())
    assert audio_error.value.code == "TTS_PROVIDER_RESPONSE_INVALID"


@pytest.mark.asyncio
async def test_invalid_or_model_mismatched_response_fails_closed() -> None:
    malformed = _provider(lambda _request: httpx.Response(200, text="author private text"))
    with pytest.raises(TTSProviderError) as malformed_error:
        await malformed.synthesize(_synthesis_request())
    assert malformed_error.value.code == "TTS_PROVIDER_RESPONSE_INVALID"
    assert "author private text" not in str(malformed_error.value)

    def mismatch_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "output": {
                    "voice_id": "voice-id",
                    "target_model": ALIYUN_QWEN_AUDIO_TTS_FLASH,
                    "preview_audio": {
                        "data": base64.b64encode(_wav_bytes()).decode("ascii"),
                        "response_format": "wav",
                    },
                }
            },
        )

    mismatch = _provider(mismatch_handler)
    with pytest.raises(TTSProviderError) as mismatch_error:
        await mismatch.design_voice(
            TTSVoicePreparationRequest(
                request_id=uuid4(),
                scope=NarrationRequestScope.fixed_local(),
                preview_text="试听",
                language="zh-CN",
                description="温和声音",
            )
        )
    assert mismatch_error.value.code == "TTS_MODEL_IDENTITY_MISMATCH"


@pytest.mark.asyncio
async def test_unconfigured_operations_fail_as_auth_without_network() -> None:
    network_called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal network_called
        network_called = True
        return httpx.Response(200)

    provider = _provider(handler, api_key="")
    with pytest.raises(TTSProviderError) as captured:
        await provider.synthesize(_synthesis_request())
    assert captured.value.code == "TTS_PROVIDER_AUTH_FAILED"
    assert network_called is False


def _json_body(request: httpx.Request) -> dict[str, Any]:
    import json

    decoded = json.loads(request.content.decode("utf-8"))
    assert isinstance(decoded, dict)
    return decoded
