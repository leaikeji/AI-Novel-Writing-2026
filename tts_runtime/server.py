"""FastAPI surface for the native Qwen3-TTS runtime.

FastAPI is imported only by ``create_app``.  MLX is imported even later, when
the first model is loaded by :class:`MLXAudioBackend`.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import hmac
from typing import Any, Mapping
from uuid import UUID

from backend.narration.providers.local import (
    LOCAL_TTS_PROTOCOL_HEADER,
    LOCAL_TTS_PROTOCOL_VERSION,
    LOCAL_TTS_TOKEN_HEADER,
    local_auth_token_from_env,
)

from .service import LocalRuntimeService, MLXAudioBackend, ModelManager, ModelRole


def create_app(
    service: LocalRuntimeService | None = None,
    *,
    auth_token: str | None = None,
) -> Any:
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse

    runtime = service or LocalRuntimeService(ModelManager(MLXAudioBackend()))
    expected_token = auth_token if auth_token is not None else local_auth_token_from_env()

    @asynccontextmanager
    async def lifespan(_app: Any):  # type: ignore[no-untyped-def]
        del _app
        try:
            yield
        finally:
            await runtime.shutdown()

    app = FastAPI(
        title="Qwen3-TTS local runtime",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def protocol_guard(request: Request, call_next: Any) -> Any:
        if request.headers.get(LOCAL_TTS_PROTOCOL_HEADER) != LOCAL_TTS_PROTOCOL_VERSION:
            return _error(JSONResponse, 409, "TTS_MODEL_IDENTITY_MISMATCH")
        if expected_token is not None and not hmac.compare_digest(
            request.headers.get(LOCAL_TTS_TOKEN_HEADER, ""), expected_token
        ):
            return _error(JSONResponse, 401, "TTS_PROVIDER_AUTH_FAILED")
        try:
            response = await call_next(request)
        except ValueError:
            response = _error(JSONResponse, 422, "TTS_PROVIDER_RESPONSE_INVALID")
        except Exception as error:
            code = str(error)
            allowed = {
                "MLX_RUNTIME_DEPENDENCY_UNAVAILABLE": "TTS_PROVIDER_UNAVAILABLE",
                "MLX_MODEL_LOAD_FAILED": "TTS_PROVIDER_UNAVAILABLE",
                "MLX_GENERATION_FAILED": "TTS_PROVIDER_UNAVAILABLE",
                "MLX_AUDIO_FORMAT_INVALID": "TTS_PROVIDER_RESPONSE_INVALID",
                "TTS_PROVIDER_CANCELLED": "TTS_PROVIDER_CANCELLED",
                "TTS_VOICE_UNAVAILABLE": "TTS_VOICE_UNAVAILABLE",
            }
            response = _error(JSONResponse, 503, allowed.get(code, "TTS_PROVIDER_UNAVAILABLE"))
        response.headers[LOCAL_TTS_PROTOCOL_HEADER] = LOCAL_TTS_PROTOCOL_VERSION
        return response

    @app.get("/v1/health")
    async def health() -> Mapping[str, object]:
        return runtime.health_payload()

    @app.get("/v1/model-identity")
    async def model_identity() -> Mapping[str, object]:
        return runtime.model_identity_payload()

    @app.post("/v1/warmup")
    async def warmup(payload: Mapping[str, Any]) -> Mapping[str, object]:
        return await runtime.warmup(ModelRole(payload.get("model_role")))

    @app.post("/v1/synthesize")
    async def synthesize(payload: Mapping[str, Any]) -> Mapping[str, object]:
        return await runtime.synthesize(payload)

    @app.post("/v1/voices/clone")
    async def clone_voice(payload: Mapping[str, Any]) -> Mapping[str, object]:
        from backend.narration.contracts import TTSVoiceKind

        return await runtime.prepare_voice(payload, kind=TTSVoiceKind.REFERENCE_CLONE)

    @app.post("/v1/voices/design")
    async def design_voice(payload: Mapping[str, Any]) -> Mapping[str, object]:
        from backend.narration.contracts import TTSVoiceKind

        return await runtime.prepare_voice(payload, kind=TTSVoiceKind.DESIGNED)

    @app.post("/v1/cancel/{request_id}")
    async def cancel(request_id: UUID) -> Mapping[str, str]:
        return runtime.cancel(request_id)

    return app


def _error(response_type: Any, status_code: int, code: str) -> Any:
    response = response_type(status_code=status_code, content={"error": {"code": code}})
    response.headers[LOCAL_TTS_PROTOCOL_HEADER] = LOCAL_TTS_PROTOCOL_VERSION
    return response
