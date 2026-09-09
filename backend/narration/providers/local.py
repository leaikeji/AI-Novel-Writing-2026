"""HTTP Provider for the native macOS Qwen3-TTS MLX runtime.

The application process only exchanges validated JSON and WAV bytes with the
runtime.  MLX objects and model-library types remain behind the local runtime
boundary so the implementation can later be replaced by the official Qwen
runtime without changing narration services.
"""

from __future__ import annotations

import base64
from dataclasses import asdict, dataclass, field
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Final, Mapping
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from ..contracts import (
    AdapterHealth,
    AdapterHealthStatus,
    CancelDisposition,
    CancellationGranularity,
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


LOCAL_TTS_PROTOCOL_VERSION: Final = "qwen-tts-local-runtime/1"
LOCAL_TTS_PROTOCOL_HEADER: Final = "X-Qwen-TTS-Protocol-Version"
LOCAL_TTS_TOKEN_HEADER: Final = "X-Qwen-TTS-Token"
DEFAULT_LOCAL_TTS_URL: Final = "http://host.docker.internal:8766"
MAX_JSON_RESPONSE_BYTES: Final = 32 * 1024 * 1024
MAX_LOCAL_TOKEN_BYTES: Final = 4 * 1024

LOCAL_QWEN_CAPABILITIES: Final = TTSProviderCapabilities(
    provider_id=TTSProviderId.LOCAL_QWEN3_TTS,
    supports_synthesis=True,
    supports_presets=True,
    supports_reference_clone=True,
    supports_voice_design=True,
    supports_instructions=True,
    supports_streaming_first_audio=False,
    supports_warmup=True,
    supports_cancel=True,
    cancellation_granularity=CancellationGranularity.SEGMENT_BOUNDARY,
    max_inference_concurrency=1,
    # Q0 machine benchmark, model hashes, and owner listening passed on
    # 2026-09-08. Runtime reachability remains a separate health concern.
    product_visible=True,
    production_ready=True,
)


def _json_scalar(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_scalar(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_scalar(item) for item in value]
    return value


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            _json_scalar(value),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


LOCAL_QWEN_CAPABILITIES_SHA256: Final = _canonical_sha256(
    asdict(LOCAL_QWEN_CAPABILITIES)
)


@dataclass(frozen=True, slots=True)
class LocalQwenTTSConfig:
    base_url: str = DEFAULT_LOCAL_TTS_URL
    timeout_seconds: float = 180.0
    auth_token: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        parsed = urlsplit(self.base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("local Qwen TTS base URL is invalid")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not 0 < self.timeout_seconds <= 600
        ):
            raise ValueError("local Qwen TTS timeout is invalid")
        if self.auth_token is not None and not self.auth_token:
            raise ValueError("local Qwen TTS token cannot be empty")

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "LocalQwenTTSConfig":
        values = os.environ if environ is None else environ
        return cls(
            base_url=values.get("QWEN_TTS_LOCAL_URL", DEFAULT_LOCAL_TTS_URL),
            timeout_seconds=float(values.get("QWEN_TTS_LOCAL_TIMEOUT_SECONDS", "180")),
            auth_token=local_auth_token_from_env(values),
        )


def local_auth_token_from_env(
    environ: Mapping[str, str] | None = None,
) -> str | None:
    values = os.environ if environ is None else environ
    inline = values.get("QWEN_TTS_LOCAL_TOKEN", "")
    token_file = values.get("QWEN_TTS_LOCAL_TOKEN_FILE", "")
    if inline and token_file:
        raise ValueError("configure only one local Qwen TTS token source")
    if token_file:
        payload = Path(token_file).read_bytes()
        if len(payload) > MAX_LOCAL_TOKEN_BYTES:
            raise ValueError("local Qwen TTS token file is too large")
        try:
            token = payload.decode("utf-8").strip()
        except UnicodeDecodeError as error:
            raise ValueError("local Qwen TTS token file must be UTF-8") from error
    else:
        token = inline.strip()
    if not token:
        return None
    if any(character.isspace() for character in token):
        raise ValueError("local Qwen TTS token cannot contain whitespace")
    return token


class LocalQwenTTSProvider(TTSProvider):
    """Strict client for the native MLX runtime protocol."""

    def __init__(
        self,
        config: LocalQwenTTSConfig | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config or LocalQwenTTSConfig.from_env()
        self._client = client

    @property
    def capabilities(self) -> TTSProviderCapabilities:
        return LOCAL_QWEN_CAPABILITIES

    async def health(self) -> AdapterHealth:
        payload = await self._request_json("GET", "/v1/health")
        _require_exact_keys(
            payload,
            {"status", "capabilities_sha256", "model_fingerprint_sha256", "reason_code"},
        )
        if payload["capabilities_sha256"] != LOCAL_QWEN_CAPABILITIES_SHA256:
            raise TTSProviderError("TTS_MODEL_IDENTITY_MISMATCH", retryable=False)
        try:
            return AdapterHealth(
                status=AdapterHealthStatus(payload["status"]),
                capabilities_sha256=payload["capabilities_sha256"],
                model_fingerprint_sha256=payload["model_fingerprint_sha256"],
                reason_code=payload["reason_code"],
            )
        except (TypeError, ValueError) as error:
            raise _invalid_response() from error

    async def model_identity(self) -> TTSModelIdentity | None:
        payload = await self._request_json("GET", "/v1/model-identity")
        _require_exact_keys(payload, {"model_identity"})
        if payload["model_identity"] is None:
            return None
        return _parse_identity(payload["model_identity"])

    async def warmup(self) -> AdapterHealth:
        payload = await self._request_json(
            "POST",
            "/v1/warmup",
            json_body={"model_role": "custom_voice"},
        )
        _require_exact_keys(
            payload,
            {"status", "capabilities_sha256", "model_fingerprint_sha256", "reason_code"},
        )
        if payload["capabilities_sha256"] != LOCAL_QWEN_CAPABILITIES_SHA256:
            raise TTSProviderError("TTS_MODEL_IDENTITY_MISMATCH", retryable=False)
        try:
            return AdapterHealth(
                status=AdapterHealthStatus(payload["status"]),
                capabilities_sha256=payload["capabilities_sha256"],
                model_fingerprint_sha256=payload["model_fingerprint_sha256"],
                reason_code=payload["reason_code"],
            )
        except (TypeError, ValueError) as error:
            raise _invalid_response() from error

    async def synthesize(self, request: TTSSynthesisRequest) -> TTSSynthesisResult:
        payload = await self._request_json(
            "POST",
            "/v1/synthesize",
            json_body={
                "request_id": str(request.request_id),
                "text": request.text,
                "language": request.language,
                "voice": _voice_payload(request),
                "seed": request.seed,
                "instruction": request.instruction,
                "audio_format": request.audio_format.value,
            },
        )
        _require_exact_keys(
            payload,
            {
                "request_id",
                "audio_base64",
                "actual_output_sha256",
                "sample_rate_hz",
                "channels",
                "sample_width_bytes",
                "content_type",
                "model_identity",
            },
        )
        if payload["request_id"] != str(request.request_id):
            raise _invalid_response()
        audio = _decode_audio(payload["audio_base64"])
        try:
            return TTSSynthesisResult(
                request_id=request.request_id,
                audio_bytes=audio,
                actual_output_sha256=payload["actual_output_sha256"],
                sample_rate_hz=payload["sample_rate_hz"],
                channels=payload["channels"],
                sample_width_bytes=payload["sample_width_bytes"],
                content_type=payload["content_type"],
                model_identity=_parse_identity(payload["model_identity"]),
            )
        except (TypeError, ValueError) as error:
            raise _invalid_response() from error

    async def clone_voice(
        self,
        request: TTSVoicePreparationRequest,
    ) -> TTSVoicePreparationResult:
        if request.reference_audio is None or request.description is not None:
            raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False)
        return await self._prepare_voice("clone", request)

    async def design_voice(
        self,
        request: TTSVoicePreparationRequest,
    ) -> TTSVoicePreparationResult:
        if request.description is None or request.reference_audio is not None:
            raise TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False)
        return await self._prepare_voice("design", request)

    async def _prepare_voice(
        self,
        operation: str,
        request: TTSVoicePreparationRequest,
    ) -> TTSVoicePreparationResult:
        reference = request.reference_audio
        payload = await self._request_json(
            "POST",
            f"/v1/voices/{operation}",
            json_body={
                "request_id": str(request.request_id),
                "preview_text": request.preview_text,
                "language": request.language,
                "description": request.description,
                "reference_audio_base64": (
                    base64.b64encode(reference.audio_bytes).decode("ascii")
                    if reference is not None
                    else None
                ),
                "reference_audio_sha256": (
                    reference.actual_sha256 if reference is not None else None
                ),
                "reference_audio_content_type": (
                    reference.content_type if reference is not None else None
                ),
                "reference_text": request.reference_text,
                "seed": request.seed,
            },
        )
        _require_exact_keys(
            payload,
            {
                "request_id",
                "provider_voice_id",
                "preview_audio_base64",
                "actual_output_sha256",
                "model_identity",
                "voice_kind",
            },
        )
        if payload["request_id"] != str(request.request_id):
            raise _invalid_response()
        try:
            return TTSVoicePreparationResult(
                request_id=request.request_id,
                provider_voice_id=payload["provider_voice_id"],
                preview_audio_bytes=_decode_audio(payload["preview_audio_base64"]),
                actual_output_sha256=payload["actual_output_sha256"],
                model_identity=_parse_identity(payload["model_identity"]),
                voice_kind=TTSVoiceKind(payload["voice_kind"]),
            )
        except (TypeError, ValueError) as error:
            raise _invalid_response() from error

    async def cancel(self, request_id: UUID) -> CancelDisposition:
        payload = await self._request_json(
            "POST",
            f"/v1/cancel/{request_id}",
            json_body={},
        )
        _require_exact_keys(payload, {"disposition"})
        try:
            return CancelDisposition(payload["disposition"])
        except (TypeError, ValueError) as error:
            raise _invalid_response() from error

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_body: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {LOCAL_TTS_PROTOCOL_HEADER: LOCAL_TTS_PROTOCOL_VERSION}
        if self._config.auth_token is not None:
            headers[LOCAL_TTS_TOKEN_HEADER] = self._config.auth_token
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            base_url=self._config.base_url,
            timeout=self._config.timeout_seconds,
        )
        try:
            response = await client.request(method, path, json=json_body, headers=headers)
        except httpx.TimeoutException as error:
            raise TTSProviderError("TTS_PROVIDER_TIMEOUT", retryable=True) from error
        except httpx.HTTPError as error:
            raise TTSProviderError("TTS_PROVIDER_UNAVAILABLE", retryable=True) from error
        finally:
            if owns_client:
                await client.aclose()
        if response.headers.get(LOCAL_TTS_PROTOCOL_HEADER) != LOCAL_TTS_PROTOCOL_VERSION:
            raise TTSProviderError("TTS_MODEL_IDENTITY_MISMATCH", retryable=False)
        if len(response.content) > MAX_JSON_RESPONSE_BYTES:
            raise _invalid_response()
        if response.status_code >= 400:
            raise _http_error(response)
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip()
        if content_type != "application/json":
            raise _invalid_response()
        try:
            payload = response.json()
        except ValueError as error:
            raise _invalid_response() from error
        if not isinstance(payload, dict):
            raise _invalid_response()
        return payload


def _voice_payload(request: TTSSynthesisRequest) -> dict[str, Any]:
    reference = request.voice.reference_audio
    return {
        "kind": request.voice.kind.value,
        "provider_voice_id": request.voice.provider_voice_id,
        "reference_audio_base64": (
            base64.b64encode(reference.audio_bytes).decode("ascii")
            if reference is not None
            else None
        ),
        "reference_audio_sha256": (
            reference.actual_sha256 if reference is not None else None
        ),
        "reference_audio_content_type": (
            reference.content_type if reference is not None else None
        ),
        "reference_text": request.voice.reference_text,
    }


def _parse_identity(raw: Any) -> TTSModelIdentity:
    if not isinstance(raw, dict):
        raise _invalid_response()
    _require_exact_keys(
        raw,
        {
            "provider_id",
            "model_id",
            "model_revision",
            "runtime_id",
            "runtime_version",
            "quantization",
            "artifact_tree_sha256",
            "schema_version",
        },
    )
    try:
        identity = TTSModelIdentity(
            provider_id=TTSProviderId(raw["provider_id"]),
            model_id=raw["model_id"],
            model_revision=raw["model_revision"],
            runtime_id=raw["runtime_id"],
            runtime_version=raw["runtime_version"],
            quantization=raw["quantization"],
            artifact_tree_sha256=raw["artifact_tree_sha256"],
            schema_version=raw["schema_version"],
        )
    except (TypeError, ValueError) as error:
        raise _invalid_response() from error
    if identity.provider_id is not TTSProviderId.LOCAL_QWEN3_TTS:
        raise TTSProviderError("TTS_MODEL_IDENTITY_MISMATCH", retryable=False)
    if identity.runtime_id != "mlx-audio" or not identity.model_id.startswith(
        "mlx-community/Qwen3-TTS-12Hz-1.7B-"
    ):
        raise TTSProviderError("TTS_MODEL_IDENTITY_MISMATCH", retryable=False)
    return identity


def _decode_audio(raw: Any) -> bytes:
    if not isinstance(raw, str) or not raw:
        raise _invalid_response()
    try:
        return base64.b64decode(raw, validate=True)
    except (ValueError, TypeError) as error:
        raise _invalid_response() from error


def _require_exact_keys(payload: Mapping[str, Any], expected: set[str]) -> None:
    if set(payload) != expected:
        raise _invalid_response()


def _invalid_response() -> TTSProviderError:
    return TTSProviderError("TTS_PROVIDER_RESPONSE_INVALID", retryable=False)


def _http_error(response: httpx.Response) -> TTSProviderError:
    default_code, retryable = {
        401: ("TTS_PROVIDER_AUTH_FAILED", False),
        403: ("TTS_PROVIDER_AUTH_FAILED", False),
        404: ("TTS_PROVIDER_UNAVAILABLE", False),
        408: ("TTS_PROVIDER_TIMEOUT", True),
        409: ("TTS_PROVIDER_UNAVAILABLE", True),
        422: ("TTS_PROVIDER_RESPONSE_INVALID", False),
        429: ("TTS_PROVIDER_RATE_LIMITED", True),
        503: ("TTS_PROVIDER_UNAVAILABLE", True),
        504: ("TTS_PROVIDER_TIMEOUT", True),
    }.get(response.status_code, ("TTS_PROVIDER_UNAVAILABLE", response.status_code >= 500))
    try:
        body = response.json()
        raw_code = body.get("error", {}).get("code") if isinstance(body, dict) else None
    except ValueError:
        raw_code = None
    allowed = {
        "TTS_PROVIDER_DISABLED",
        "TTS_PROVIDER_UNAVAILABLE",
        "TTS_PROVIDER_TIMEOUT",
        "TTS_PROVIDER_RESPONSE_INVALID",
        "TTS_PROVIDER_CANCELLED",
        "TTS_VOICE_UNAVAILABLE",
        "TTS_MODEL_IDENTITY_MISMATCH",
    }
    code = raw_code if raw_code in allowed else default_code
    return TTSProviderError(code, retryable=retryable)
