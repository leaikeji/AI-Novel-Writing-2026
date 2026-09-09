"""Qwen-Audio native HTTP TTS Provider.

The adapter accepts public HTTPS gateways that implement the documented
Qwen-Audio native HTTP contract. Credentials, HTTP response objects, vendor
error messages, signed URLs, and reference-audio upload details never cross
the Provider boundary.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import ipaddress
import inspect
import io
import json
import posixpath
import socket
import wave
from collections.abc import Awaitable, Callable, Iterable
from typing import Final
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from uuid import UUID

import httpx

from ..contracts import (
    AdapterHealth,
    AdapterHealthStatus,
    CancellationGranularity,
    CancelDisposition,
    ReferenceAudioInput,
    TTSModelIdentity,
    TTSProviderCapabilities,
    TTSProviderId,
    TTSSynthesisRequest,
    TTSSynthesisResult,
    TTSVoiceKind,
    TTSVoicePreparationRequest,
    TTSVoicePreparationResult,
)
from .base import TTSProvider, TTSProviderError

ALIYUN_QWEN_AUDIO_TTS_PLUS: Final = "qwen-audio-3.0-tts-plus"
ALIYUN_QWEN_AUDIO_TTS_FLASH: Final = "qwen-audio-3.0-tts-flash"
CANONICAL_MODEL_SLOTS: Final[frozenset[str]] = frozenset(
    {ALIYUN_QWEN_AUDIO_TTS_PLUS, ALIYUN_QWEN_AUDIO_TTS_FLASH}
)

# Keep vendor paths centralized.  Alibaba Cloud may version these independently
# of our Provider contract, and a future change must remain adapter-local.
SYNTHESIS_PATH: Final = "/api/v1/services/audio/tts/SpeechSynthesizer"
VOICE_CUSTOMIZATION_PATH: Final = "/api/v1/services/audio/tts/customization"
VOICE_ENROLLMENT_MODEL: Final = "voice-enrollment"
DEFAULT_SAMPLE_RATE_HZ: Final = 24_000
MODEL_REVISION: Final = "vendor-managed-alias"
RUNTIME_ID: Final = "aliyun-model-studio-http"
RUNTIME_VERSION: Final = "api-contract-2026-09-08"

_LANGUAGE_HINTS: Final = frozenset(
    {
        "zh",
        "en",
        "fr",
        "de",
        "ja",
        "ko",
        "ru",
        "pt",
        "th",
        "id",
        "vi",
        "es",
        "it",
        "ms",
        "fil",
        "ar",
    }
)
MAX_BASE_URL_CHARS: Final = 2_048
MAX_MODEL_ID_CHARS: Final = 240
MAX_JSON_RESPONSE_BYTES: Final = 16 * 1024 * 1024
MAX_AUDIO_RESPONSE_BYTES: Final = 64 * 1024 * 1024

ReferenceAudioURLFactory = Callable[
    [ReferenceAudioInput],
    str | Awaitable[str],
]
HostResolver = Callable[
    [str, int],
    Iterable[str | ipaddress.IPv4Address | ipaddress.IPv6Address]
    | Awaitable[Iterable[str | ipaddress.IPv4Address | ipaddress.IPv6Address]],
]


class AliyunQwenAudioTTSProvider(TTSProvider):
    """Non-streaming HTTP adapter for Qwen-Audio 3.0 Plus or Flash."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model_id: str = ALIYUN_QWEN_AUDIO_TTS_PLUS,
        timeout_seconds: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
        reference_audio_url_factory: ReferenceAudioURLFactory | None = None,
        host_resolver: HostResolver | None = None,
        product_released: bool = False,
    ) -> None:
        normalized_model_id = _normalize_model_id(model_id)
        normalized_url = normalize_qwen_audio_base_url(base_url)
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
            raise TypeError("timeout_seconds must be numeric")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if type(product_released) is not bool:
            raise TypeError("product_released must be an exact boolean")

        self._api_key = api_key.strip()
        self._base_url = normalized_url
        self._model_id = normalized_model_id
        self._timeout_seconds = float(timeout_seconds)
        self._transport = transport
        self._reference_audio_url_factory = reference_audio_url_factory
        self._host_resolver = host_resolver or _resolve_host_addresses
        self._identity = _model_identity(normalized_model_id)
        self._capabilities = TTSProviderCapabilities(
            provider_id=TTSProviderId.ALIYUN_QWEN_AUDIO_TTS,
            supports_synthesis=True,
            supports_presets=True,
            supports_reference_clone=True,
            supports_voice_design=True,
            supports_instructions=True,
            # This adapter deliberately uses the documented non-streaming HTTP
            # response. Segment-level background generation remains upstream.
            supports_streaming_first_audio=False,
            supports_warmup=False,
            supports_cancel=False,
            cancellation_granularity=CancellationGranularity.NONE,
            max_inference_concurrency=4,
            product_visible=product_released,
            production_ready=product_released,
        )

    def __repr__(self) -> str:
        return (
            "AliyunQwenAudioTTSProvider("
            f"model_id={self._model_id!r}, configured={bool(self._api_key)!r})"
        )

    @property
    def capabilities(self) -> TTSProviderCapabilities:
        return self._capabilities

    async def health(self) -> AdapterHealth:
        if not self._api_key:
            return AdapterHealth(
                status=AdapterHealthStatus.DISABLED,
                capabilities_sha256=_capabilities_sha256(self._capabilities),
                model_fingerprint_sha256=None,
                reason_code="TTS_PROVIDER_DISABLED",
            )
        # The documented service has no non-billable readiness endpoint. An
        # API key therefore proves configuration only; a real smoke request is
        # required before product release.
        return AdapterHealth(
            status=AdapterHealthStatus.DEGRADED,
            capabilities_sha256=_capabilities_sha256(self._capabilities),
            model_fingerprint_sha256=self._identity.artifact_tree_sha256,
            reason_code="TTS_PROVIDER_NOT_PROBED",
        )

    async def model_identity(self) -> TTSModelIdentity:
        return self._identity

    async def warmup(self) -> AdapterHealth:
        # Managed HTTP inference has no non-billable warmup operation.
        return await self.health()

    async def synthesize(self, request: TTSSynthesisRequest) -> TTSSynthesisResult:
        self._ensure_configured()
        payload_input: dict[str, object] = {
            "text": request.text,
            "voice": request.voice.provider_voice_id,
            "format": "wav",
            "sample_rate": DEFAULT_SAMPLE_RATE_HZ,
        }
        language_hint = _language_hint(request.language)
        if language_hint is not None:
            payload_input["language_hints"] = [language_hint]
        if request.instruction is not None:
            payload_input["instruction"] = request.instruction
        if request.seed is not None:
            # The shared contract permits signed 64-bit seeds while this API is
            # explicitly 16-bit. Preserve deterministic behavior adapter-locally.
            payload_input["seed"] = request.seed % 65_536

        response = await self._post_json(
            SYNTHESIS_PATH,
            {"model": self._model_id, "input": payload_input},
        )
        audio_url = _synthesis_audio_url(response)
        audio_bytes = await self._download_audio(audio_url)
        sample_rate_hz, channels, sample_width_bytes = _wav_metadata(audio_bytes)
        return TTSSynthesisResult(
            request_id=request.request_id,
            audio_bytes=audio_bytes,
            actual_output_sha256=hashlib.sha256(audio_bytes).hexdigest(),
            sample_rate_hz=sample_rate_hz,
            channels=channels,
            sample_width_bytes=sample_width_bytes,
            model_identity=self._identity,
        )

    async def clone_voice(
        self,
        request: TTSVoicePreparationRequest,
    ) -> TTSVoicePreparationResult:
        self._ensure_configured()
        if request.reference_audio is None or request.description is not None:
            raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False)
        if self._reference_audio_url_factory is None:
            raise TTSProviderError("TTS_PROVIDER_UNAVAILABLE", retryable=False)

        try:
            audio_url_or_awaitable = self._reference_audio_url_factory(
                request.reference_audio
            )
            if inspect.isawaitable(audio_url_or_awaitable):
                audio_url = await audio_url_or_awaitable
            else:
                audio_url = audio_url_or_awaitable
        except TTSProviderError:
            raise
        except Exception:
            raise TTSProviderError("TTS_PROVIDER_UNAVAILABLE", retryable=True) from None
        await self._ensure_public_https_url(audio_url)

        input_payload: dict[str, object] = {
            "action": "create_voice",
            "target_model": self._model_id,
            "prefix": _voice_prefix(request.request_id),
            "url": audio_url,
        }
        language_hint = _language_hint(request.language)
        if language_hint is not None:
            input_payload["language_hints"] = [language_hint]
        response = await self._post_json(
            VOICE_CUSTOMIZATION_PATH,
            {"model": VOICE_ENROLLMENT_MODEL, "input": input_payload},
        )
        voice_id = _prepared_voice_id(response, expected_model=self._model_id)

        preview = await self.synthesize(
            TTSSynthesisRequest(
                request_id=request.request_id,
                scope=request.scope,
                text=request.preview_text,
                language=request.language,
                voice=_prepared_voice_input(
                    TTSVoiceKind.REFERENCE_CLONE,
                    voice_id,
                    reference_audio=request.reference_audio,
                    reference_text=request.reference_text,
                ),
                seed=request.seed,
            )
        )
        return TTSVoicePreparationResult(
            request_id=request.request_id,
            provider_voice_id=voice_id,
            preview_audio_bytes=preview.audio_bytes,
            actual_output_sha256=preview.actual_output_sha256,
            model_identity=self._identity,
            voice_kind=TTSVoiceKind.REFERENCE_CLONE,
        )

    async def design_voice(
        self,
        request: TTSVoicePreparationRequest,
    ) -> TTSVoicePreparationResult:
        self._ensure_configured()
        if request.description is None or request.reference_audio is not None:
            raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False)

        input_payload: dict[str, object] = {
            "action": "create_voice",
            "target_model": self._model_id,
            "voice_prompt": request.description,
            "preview_text": request.preview_text,
            "prefix": _voice_prefix(request.request_id),
        }
        language_hint = _language_hint(request.language)
        if language_hint in {"zh", "en"}:
            input_payload["language_hints"] = [language_hint]
        response = await self._post_json(
            VOICE_CUSTOMIZATION_PATH,
            {
                "model": VOICE_ENROLLMENT_MODEL,
                "input": input_payload,
                "parameters": {
                    "sample_rate": DEFAULT_SAMPLE_RATE_HZ,
                    "response_format": "wav",
                },
            },
        )
        voice_id = _prepared_voice_id(response, expected_model=self._model_id)
        preview_audio = _design_preview_audio(response)
        _wav_metadata(preview_audio)
        return TTSVoicePreparationResult(
            request_id=request.request_id,
            provider_voice_id=voice_id,
            preview_audio_bytes=preview_audio,
            actual_output_sha256=hashlib.sha256(preview_audio).hexdigest(),
            model_identity=self._identity,
            voice_kind=TTSVoiceKind.DESIGNED,
        )

    async def cancel(self, request_id: UUID) -> CancelDisposition:
        del request_id
        return CancelDisposition.UNSUPPORTED

    def _ensure_configured(self) -> None:
        if not self._api_key:
            raise TTSProviderError("TTS_PROVIDER_AUTH_FAILED", retryable=False)

    async def _post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        target_url = f"{self._base_url}{path}"
        await self._ensure_public_https_url(target_url)
        try:
            async with self._new_client() as client:
                async with client.stream(
                    "POST",
                    target_url,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                ) as response:
                    response_body = await _read_limited_body(
                        response,
                        limit=MAX_JSON_RESPONSE_BYTES,
                    )
        except httpx.TimeoutException:
            raise TTSProviderError("TTS_PROVIDER_TIMEOUT", retryable=True) from None
        except httpx.TransportError:
            raise TTSProviderError("TTS_PROVIDER_UNAVAILABLE", retryable=True) from None
        if response.is_redirect:
            raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False)
        if response.status_code != 200:
            raise _http_error(response, response_body)
        try:
            parsed = json.loads(response_body)
        except (UnicodeDecodeError, ValueError):
            raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False) from None
        if not isinstance(parsed, dict):
            raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False)
        return parsed

    async def _download_audio(self, url: str) -> bytes:
        download_url = _normalize_audio_download_url(url)
        await self._ensure_public_https_url(download_url)
        try:
            async with self._new_client() as client:
                async with client.stream("GET", download_url) as response:
                    response_body = await _read_limited_body(
                        response,
                        limit=MAX_AUDIO_RESPONSE_BYTES,
                    )
        except httpx.TimeoutException:
            raise TTSProviderError("TTS_PROVIDER_TIMEOUT", retryable=True) from None
        except httpx.TransportError:
            raise TTSProviderError("TTS_PROVIDER_UNAVAILABLE", retryable=True) from None
        if response.is_redirect:
            raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False)
        if response.status_code != 200:
            raise _http_error(response, response_body)
        if not response_body:
            raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False)
        return response_body

    async def _ensure_public_https_url(self, url: str) -> None:
        parsed = _parse_external_https_url(url)
        hostname = parsed.hostname
        if hostname is None:  # Kept explicit for the type checker.
            raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False)
        try:
            resolved_or_awaitable = self._host_resolver(
                hostname,
                parsed.port or 443,
            )
            if inspect.isawaitable(resolved_or_awaitable):
                resolved = await resolved_or_awaitable
            else:
                resolved = resolved_or_awaitable
            addresses = tuple(resolved)
        except TTSProviderError:
            raise
        except Exception:
            raise TTSProviderError("TTS_PROVIDER_UNAVAILABLE", retryable=True) from None
        if not addresses:
            raise TTSProviderError("TTS_PROVIDER_UNAVAILABLE", retryable=True)
        for address in addresses:
            try:
                parsed_address = ipaddress.ip_address(address)
            except ValueError:
                raise TTSProviderError(
                    "TTS_PROVIDER_RESPONSE_INVALID",
                    retryable=False,
                ) from None
            if not _is_public_address(parsed_address):
                raise TTSProviderError(
                    "TTS_PROVIDER_RESPONSE_INVALID",
                    retryable=False,
                )

    def _new_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self._transport,
            timeout=self._timeout_seconds,
            follow_redirects=False,
            trust_env=False,
        )


def _model_identity(model_id: str) -> TTSModelIdentity:
    identity_material = (
        f"aliyun-qwen-audio-tts\n{model_id}\n{MODEL_REVISION}\n"
        f"{RUNTIME_ID}\n{RUNTIME_VERSION}\nmanaged"
    ).encode("utf-8")
    return TTSModelIdentity(
        provider_id=TTSProviderId.ALIYUN_QWEN_AUDIO_TTS,
        model_id=model_id,
        model_revision=MODEL_REVISION,
        runtime_id=RUNTIME_ID,
        runtime_version=RUNTIME_VERSION,
        quantization="managed",
        artifact_tree_sha256=hashlib.sha256(identity_material).hexdigest(),
    )


def _capabilities_sha256(capabilities: TTSProviderCapabilities) -> str:
    serialized = json.dumps(
        {
            "provider_id": capabilities.provider_id.value,
            "supports_synthesis": capabilities.supports_synthesis,
            "supports_presets": capabilities.supports_presets,
            "supports_reference_clone": capabilities.supports_reference_clone,
            "supports_voice_design": capabilities.supports_voice_design,
            "supports_instructions": capabilities.supports_instructions,
            "supports_streaming_first_audio": capabilities.supports_streaming_first_audio,
            "supports_warmup": capabilities.supports_warmup,
            "supports_cancel": capabilities.supports_cancel,
            "cancellation_granularity": capabilities.cancellation_granularity.value,
            "max_inference_concurrency": capabilities.max_inference_concurrency,
            "contract_version": capabilities.contract_version,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _http_error(response: httpx.Response, response_body: bytes) -> TTSProviderError:
    # Vendor messages may contain request fragments or account details. Inspect
    # only a normalized code and never expose response text through our error.
    provider_code = ""
    try:
        payload = json.loads(response_body)
        if isinstance(payload, dict):
            raw_code = payload.get("code")
            if isinstance(raw_code, str):
                provider_code = "".join(ch for ch in raw_code.lower() if ch.isalnum())
    except (UnicodeDecodeError, ValueError):
        pass
    if response.status_code in {401, 403} or provider_code in {
        "invalidapikey",
        "unauthorized",
        "accessdenied",
        "permissiondenied",
        "forbidden",
    }:
        return TTSProviderError("TTS_PROVIDER_AUTH_FAILED", retryable=False)
    if response.status_code == 429 or any(
        marker in provider_code for marker in ("ratelimit", "throttl", "toomanyrequests")
    ):
        return TTSProviderError("TTS_PROVIDER_RATE_LIMITED", retryable=True)
    if response.status_code >= 500:
        return TTSProviderError("TTS_PROVIDER_UNAVAILABLE", retryable=True)
    if "voice" in provider_code:
        return TTSProviderError("TTS_VOICE_UNAVAILABLE", retryable=False)
    return TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False)


def _synthesis_audio_url(payload: dict[str, object]) -> str:
    output = payload.get("output")
    if not isinstance(output, dict) or output.get("finish_reason") != "stop":
        raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False)
    audio = output.get("audio")
    if not isinstance(audio, dict):
        raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False)
    url = audio.get("url")
    if not isinstance(url, str) or not url:
        raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False)
    return url


def _prepared_voice_id(payload: dict[str, object], *, expected_model: str) -> str:
    output = payload.get("output")
    if not isinstance(output, dict):
        raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False)
    target_model = output.get("target_model")
    if target_model is not None and target_model != expected_model:
        raise TTSProviderError("TTS_MODEL_IDENTITY_MISMATCH", retryable=False)
    voice_id = output.get("voice_id")
    if not isinstance(voice_id, str) or not voice_id.strip():
        raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False)
    return voice_id


def _design_preview_audio(payload: dict[str, object]) -> bytes:
    output = payload.get("output")
    if not isinstance(output, dict):
        raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False)
    preview = output.get("preview_audio")
    if not isinstance(preview, dict) or preview.get("response_format") != "wav":
        raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False)
    encoded = preview.get("data")
    if not isinstance(encoded, str) or not encoded:
        raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False)
    if len(encoded) > ((MAX_AUDIO_RESPONSE_BYTES + 2) // 3) * 4:
        raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False)
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False) from None
    if len(decoded) > MAX_AUDIO_RESPONSE_BYTES:
        raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False)
    return decoded


def _wav_metadata(audio_bytes: bytes) -> tuple[int, int, int]:
    try:
        with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
            sample_rate_hz = wav_file.getframerate()
            channels = wav_file.getnchannels()
            sample_width_bytes = wav_file.getsampwidth()
            if wav_file.getnframes() <= 0:
                raise wave.Error("empty WAV")
    except (EOFError, wave.Error):
        raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False) from None
    if min(sample_rate_hz, channels, sample_width_bytes) <= 0:
        raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False)
    return sample_rate_hz, channels, sample_width_bytes


def _language_hint(language: str) -> str | None:
    normalized = language.strip().lower().replace("_", "-").split("-", 1)[0]
    return normalized if normalized in _LANGUAGE_HINTS else None


def _voice_prefix(request_id: UUID) -> str:
    return f"v{request_id.hex[:9]}"


def _prepared_voice_input(
    kind: TTSVoiceKind,
    voice_id: str,
    *,
    reference_audio: ReferenceAudioInput | None = None,
    reference_text: str | None = None,
):
    # Local import keeps the public boundary imports at the top easy to audit.
    from ..contracts import TTSVoiceInput

    return TTSVoiceInput(
        kind=kind,
        provider_voice_id=voice_id,
        reference_audio=reference_audio,
        reference_text=reference_text,
    )


def _normalize_model_id(model_id: str) -> str:
    if not isinstance(model_id, str):
        raise TypeError("model_id must be a string")
    normalized = model_id.strip()
    if (
        not normalized
        or len(normalized) > MAX_MODEL_ID_CHARS
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
    ):
        raise ValueError("Qwen-Audio TTS model ID must be a non-empty safe value")
    return normalized


def normalize_qwen_audio_base_url(base_url: str) -> str:
    if not isinstance(base_url, str):
        raise TypeError("base_url must be a string")
    candidate = base_url.strip()
    if (
        not candidate
        or len(candidate) > MAX_BASE_URL_CHARS
        or "\\" in candidate
        or any(ord(character) < 32 or ord(character) == 127 for character in candidate)
    ):
        raise ValueError("Qwen-Audio TTS base URL must be a safe HTTPS URL")
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError:
        raise ValueError("Qwen-Audio TTS base URL must be a safe HTTPS URL") from None
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Qwen-Audio TTS base URL must be a safe HTTPS URL")
    hostname = _normalize_hostname(parsed.hostname)
    if port == 0 or _is_forbidden_hostname(hostname):
        raise ValueError("Qwen-Audio TTS base URL must use a public host")
    decoded_path = unquote(parsed.path)
    if "\\" in decoded_path or any(
        ord(character) < 32 or ord(character) == 127 for character in decoded_path
    ):
        raise ValueError("Qwen-Audio TTS base URL contains an unsafe path")
    normalized_path = posixpath.normpath(f"/{decoded_path.lstrip('/')}")
    if normalized_path == "/":
        normalized_path = ""
    normalized_path = quote(normalized_path, safe="/:@-._~!$&'()*+,;=")
    host_for_url = f"[{hostname}]" if ":" in hostname else hostname
    netloc = host_for_url if port is None else f"{host_for_url}:{port}"
    return urlunsplit(("https", netloc, normalized_path, "", ""))


def _parse_external_https_url(url: str):
    if (
        not isinstance(url, str)
        or not url
        or len(url) > MAX_BASE_URL_CHARS
        or "\\" in url
        or any(ord(character) < 32 or ord(character) == 127 for character in url)
    ):
        raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False)
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False) from None
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False)
    try:
        normalized_hostname = _normalize_hostname(parsed.hostname)
    except ValueError:
        raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False) from None
    if port == 0 or _is_forbidden_hostname(normalized_hostname):
        raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False)
    return parsed


def _normalize_audio_download_url(url: str) -> str:
    """Upgrade Alibaba's documented HTTP OSS result URL before downloading."""

    if not isinstance(url, str):
        raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False)
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False) from None
    if parsed.scheme.lower() == "https":
        _parse_external_https_url(url)
        return url
    if (
        parsed.scheme.lower() != "http"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or port is not None
    ):
        raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False)
    try:
        hostname = _normalize_hostname(parsed.hostname)
    except ValueError:
        raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False) from None
    if not hostname.endswith(".oss-cn-beijing.aliyuncs.com"):
        raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False)
    upgraded = urlunsplit(("https", hostname, parsed.path, parsed.query, ""))
    _parse_external_https_url(upgraded)
    return upgraded


def _normalize_hostname(hostname: str) -> str:
    try:
        normalized = hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise ValueError("Qwen-Audio TTS base URL contains an invalid host") from None
    if not normalized or len(normalized) > 253:
        raise ValueError("Qwen-Audio TTS base URL contains an invalid host")
    try:
        ipaddress.ip_address(normalized)
    except ValueError:
        labels = normalized.split(".")
        if any(
            not label
            or len(label) > 63
            or label.startswith("-")
            or label.endswith("-")
            or any(not (character.isalnum() or character == "-") for character in label)
            for label in labels
        ):
            raise ValueError("Qwen-Audio TTS base URL contains an invalid host")
    return normalized


def _is_forbidden_hostname(hostname: str) -> bool:
    normalized = hostname.rstrip(".").lower()
    if normalized == "localhost" or normalized.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return not _is_public_address(address)


def _is_public_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    return address.is_global and not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


async def _resolve_host_addresses(hostname: str, port: int) -> tuple[str, ...]:
    records = await asyncio.get_running_loop().getaddrinfo(
        hostname,
        port,
        family=socket.AF_UNSPEC,
        type=socket.SOCK_STREAM,
    )
    return tuple({str(record[4][0]) for record in records})


async def _read_limited_body(response: httpx.Response, *, limit: int) -> bytes:
    content_length = response.headers.get("Content-Length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError:
            raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False) from None
        if declared_length < 0 or declared_length > limit:
            raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False)
    body = bytearray()
    async for chunk in response.aiter_bytes():
        if len(body) + len(chunk) > limit:
            raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False)
        body.extend(chunk)
    return bytes(body)
