"""Runtime core with one globally serialized MLX model residency slot."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
import gc
import hashlib
import importlib.util
import io
import math
import os
import struct
from typing import Any, Callable, Mapping, Protocol, TypeVar
from uuid import UUID
import wave

from backend.narration.contracts import TTSVoiceKind
from backend.narration.providers.local import (
    LOCAL_QWEN_CAPABILITIES_SHA256,
    _canonical_sha256,
)


class RuntimeUnavailable(RuntimeError):
    """Stable runtime failure; the message never includes user content."""


class ModelRole(str, Enum):
    CUSTOM_VOICE = "custom_voice"
    BASE = "base"
    VOICE_DESIGN = "voice_design"


@dataclass(frozen=True, slots=True)
class RuntimeModelConfig:
    model_id: str
    model_revision: str
    quantization: str
    artifact_tree_sha256: str
    local_path_env: str


@dataclass(frozen=True, slots=True)
class GeneratedAudio:
    audio_bytes: bytes
    sample_rate_hz: int = 24_000
    channels: int = 1
    sample_width_bytes: int = 2


class RuntimeBackend(Protocol):
    @property
    def runtime_version(self) -> str: ...

    def dependency_available(self) -> bool: ...

    def load(self, config: RuntimeModelConfig) -> object: ...

    def unload(self, model: object) -> None: ...

    def generate(
        self,
        model: object,
        *,
        text: str,
        language: str,
        voice_id: str | None,
        instruction: str | None,
        reference_audio: bytes | None,
        reference_text: str | None,
        seed: int | None,
    ) -> GeneratedAudio: ...


DEFAULT_MODELS: Mapping[ModelRole, RuntimeModelConfig] = {
    ModelRole.CUSTOM_VOICE: RuntimeModelConfig(
        model_id="mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit",
        model_revision="41d3337e8b7f2843a75841595fc14e4b9a7a4b96",
        quantization="8bit",
        artifact_tree_sha256="728e8b60b4cdb195a1379faf033b428bf93feaceccbdcf3c3a4bd3a6698b4fb6",
        local_path_env="QWEN_TTS_CUSTOM_VOICE_MODEL_PATH",
    ),
    ModelRole.BASE: RuntimeModelConfig(
        model_id="mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit",
        model_revision="e7dd0585652209fa0d7783659aad4e8a324de11c",
        quantization="8bit",
        artifact_tree_sha256="1ce5152917c093872ae50a96e3908e065bf9ece2c5b192cd54ee346a09027094",
        local_path_env="QWEN_TTS_BASE_MODEL_PATH",
    ),
    ModelRole.VOICE_DESIGN: RuntimeModelConfig(
        model_id="mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-bf16",
        model_revision="7d3824abff87e49756bb0f83fb5411de75d160c4",
        quantization="bf16",
        artifact_tree_sha256="2bb6d9c5b17d293701c6b77fe848548f91c29137b5ace8b8c9afa5f1e7cd8ff6",
        local_path_env="QWEN_TTS_VOICE_DESIGN_MODEL_PATH",
    ),
}

_T = TypeVar("_T")


class ModelManager:
    """Own the only inference/model-switch lock in the native process."""

    def __init__(
        self,
        backend: RuntimeBackend,
        *,
        models: Mapping[ModelRole, RuntimeModelConfig] = DEFAULT_MODELS,
    ) -> None:
        if set(models) != set(ModelRole):
            raise ValueError("all three local Qwen model roles must be configured")
        self._backend = backend
        self._models = dict(models)
        self._lock = asyncio.Lock()
        self._loaded_role: ModelRole | None = None
        self._loaded_model: object | None = None

    @property
    def dependency_available(self) -> bool:
        return self._backend.dependency_available()

    @property
    def loaded_role(self) -> ModelRole | None:
        return self._loaded_role

    @property
    def loaded_config(self) -> RuntimeModelConfig | None:
        return self._models[self._loaded_role] if self._loaded_role is not None else None

    @property
    def runtime_version(self) -> str:
        return self._backend.runtime_version

    async def run(self, role: ModelRole, operation: Callable[[object], _T]) -> _T:
        async with self._lock:
            if not self.dependency_available:
                raise RuntimeUnavailable("MLX_RUNTIME_DEPENDENCY_UNAVAILABLE")
            await self._switch_locked(role)
            assert self._loaded_model is not None
            return await asyncio.to_thread(operation, self._loaded_model)

    async def warmup(self, role: ModelRole) -> RuntimeModelConfig:
        async with self._lock:
            if not self.dependency_available:
                raise RuntimeUnavailable("MLX_RUNTIME_DEPENDENCY_UNAVAILABLE")
            await self._switch_locked(role)
            return self._models[role]

    async def shutdown(self) -> None:
        """Release the resident model before the native process exits."""
        async with self._lock:
            if self._loaded_model is None:
                return
            old_model = self._loaded_model
            self._loaded_model = None
            self._loaded_role = None
            await asyncio.to_thread(self._backend.unload, old_model)
            gc.collect()

    async def _switch_locked(self, role: ModelRole) -> None:
        if self._loaded_role is role:
            return
        if self._loaded_model is not None:
            old_model = self._loaded_model
            self._loaded_model = None
            self._loaded_role = None
            await asyncio.to_thread(self._backend.unload, old_model)
            gc.collect()
        config = self._models[role]
        try:
            loaded = await asyncio.to_thread(self._backend.load, config)
        except Exception as error:
            self._loaded_model = None
            self._loaded_role = None
            raise RuntimeUnavailable("MLX_MODEL_LOAD_FAILED") from error
        self._loaded_model = loaded
        self._loaded_role = role


class DeterministicFakeBackend:
    """Dependency-free test backend; never enabled implicitly by the server."""

    runtime_version = "deterministic-fake/1"

    def __init__(self) -> None:
        self.loads: list[str] = []
        self.unloads: list[str] = []

    def dependency_available(self) -> bool:
        return True

    def load(self, config: RuntimeModelConfig) -> object:
        self.loads.append(config.model_id)
        return config

    def unload(self, model: object) -> None:
        assert isinstance(model, RuntimeModelConfig)
        self.unloads.append(model.model_id)

    def generate(
        self,
        model: object,
        *,
        text: str,
        language: str,
        voice_id: str | None,
        instruction: str | None,
        reference_audio: bytes | None,
        reference_text: str | None,
        seed: int | None,
    ) -> GeneratedAudio:
        del model
        digest = hashlib.sha256(
            "\x00".join(
                (
                    text,
                    language,
                    voice_id or "",
                    instruction or "",
                    reference_text or "",
                    str(seed),
                    hashlib.sha256(reference_audio or b"").hexdigest(),
                )
            ).encode("utf-8")
        ).digest()
        frequency = 180 + digest[0]
        sample_rate = 24_000
        frames = sample_rate // 20
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(
                b"".join(
                    struct.pack(
                        "<h",
                        int(2_000 * math.sin(2 * math.pi * frequency * index / sample_rate)),
                    )
                    for index in range(frames)
                )
            )
        return GeneratedAudio(audio_bytes=buffer.getvalue())


class MLXAudioBackend:
    """Thin lazy bridge to mlx-audio.

    Importing this module never imports MLX.  Dependency/model/API failures are
    converted by the service boundary into stable unavailable responses.
    """

    runtime_version = "mlx-audio"

    def dependency_available(self) -> bool:
        return importlib.util.find_spec("mlx_audio") is not None

    def load(self, config: RuntimeModelConfig) -> object:
        from mlx_audio.tts.utils import load_model  # type: ignore[import-not-found]

        model_source = os.environ.get(config.local_path_env, "").strip() or config.model_id
        return load_model(model_source, revision=config.model_revision)

    def unload(self, model: object) -> None:
        del model
        try:
            import mlx.core as mx  # type: ignore[import-not-found]

            mx.clear_cache()
        except (ImportError, AttributeError):
            pass

    def generate(
        self,
        model: object,
        *,
        text: str,
        language: str,
        voice_id: str | None,
        instruction: str | None,
        reference_audio: bytes | None,
        reference_text: str | None,
        seed: int | None,
    ) -> GeneratedAudio:
        kwargs: dict[str, Any] = {
            "text": text,
            "lang_code": _mlx_language(language),
            # Segmentation and ordering remain owned by the narration service.
            "split_pattern": "",
        }
        if voice_id:
            kwargs["voice"] = voice_id
        if instruction:
            kwargs["instruct"] = instruction
        if reference_audio is not None:
            from mlx_audio.audio_io import read as audio_read  # type: ignore[import-not-found]
            import mlx.core as mx  # type: ignore[import-not-found]

            samples, _sample_rate = audio_read(
                io.BytesIO(reference_audio),
                dtype="float32",
                sample_rate=int(getattr(model, "sample_rate", 24_000)),
                nchannels=1,
            )
            kwargs["ref_audio"] = mx.array(samples)
            kwargs["ref_text"] = reference_text
        try:
            if seed is not None:
                import mlx.core as mx  # type: ignore[import-not-found]

                mx.random.seed(seed)
            results = list(model.generate(**kwargs))  # type: ignore[attr-defined]
            if len(results) != 1 or not hasattr(results[0], "audio"):
                raise RuntimeUnavailable("MLX_GENERATION_RESULT_INVALID")
            result = results[0]
            audio = result.audio
            sample_rate = int(getattr(result, "sample_rate", 24_000))
            return GeneratedAudio(
                audio_bytes=_pcm_or_wav_bytes(audio, sample_rate),
                sample_rate_hz=sample_rate,
            )
        except Exception as error:
            if isinstance(error, RuntimeUnavailable):
                raise
            raise RuntimeUnavailable("MLX_GENERATION_FAILED") from error


def _mlx_language(language: str) -> str:
    normalized = language.strip().lower().replace("_", "-")
    primary = normalized.split("-", 1)[0]
    return {
        "zh": "chinese",
        "en": "english",
        "ja": "japanese",
        "ko": "korean",
        "de": "german",
        "fr": "french",
        "ru": "russian",
        "pt": "portuguese",
        "es": "spanish",
        "it": "italian",
    }.get(primary, "auto")


def _pcm_or_wav_bytes(audio: Any, sample_rate: int) -> bytes:
    if isinstance(audio, bytes):
        if audio.startswith(b"RIFF"):
            return audio
        pcm = audio
    else:
        try:
            values = audio.tolist()
            pcm = b"".join(
                struct.pack("<h", max(-32768, min(32767, int(float(value) * 32767))))
                for value in values
            )
        except Exception as error:
            raise RuntimeUnavailable("MLX_AUDIO_FORMAT_INVALID") from error
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buffer.getvalue()


class LocalRuntimeService:
    """Provider protocol implementation independent of HTTP framework types."""

    def __init__(self, manager: ModelManager) -> None:
        self._manager = manager
        self._voice_roles: dict[str, ModelRole] = {}
        self._voice_descriptions: dict[str, str] = {}
        self._cancelled: set[UUID] = set()

    def health_payload(self) -> dict[str, object]:
        if not self._manager.dependency_available:
            return {
                "status": "unavailable",
                "capabilities_sha256": LOCAL_QWEN_CAPABILITIES_SHA256,
                "model_fingerprint_sha256": None,
                "reason_code": "MLX_RUNTIME_DEPENDENCY_UNAVAILABLE",
            }
        return {
            "status": "healthy" if self._manager.loaded_role else "degraded",
            "capabilities_sha256": LOCAL_QWEN_CAPABILITIES_SHA256,
            "model_fingerprint_sha256": self.model_fingerprint_sha256(),
            "reason_code": None,
        }

    def model_identity_payload(self) -> dict[str, object]:
        return {"model_identity": self._identity_payload()}

    async def warmup(self, role: ModelRole) -> dict[str, object]:
        await self._manager.warmup(role)
        return self.health_payload()

    async def shutdown(self) -> None:
        await self._manager.shutdown()

    async def synthesize(self, payload: Mapping[str, Any]) -> dict[str, object]:
        request_id = UUID(_required_str(payload, "request_id"))
        if request_id in self._cancelled:
            raise RuntimeUnavailable("TTS_PROVIDER_CANCELLED")
        voice = payload.get("voice")
        if not isinstance(voice, Mapping):
            raise ValueError("INVALID_REQUEST")
        kind = TTSVoiceKind(_required_str(voice, "kind"))
        voice_id = _required_str(voice, "provider_voice_id")
        role = self._role_for_voice(kind, voice_id)
        designed_instruction = (
            self._voice_descriptions.get(voice_id)
            if kind is TTSVoiceKind.DESIGNED
            else None
        )
        generated = await self._manager.run(
            role,
            lambda model: self._manager._backend.generate(
                model,
                text=_required_str(payload, "text"),
                language=_required_str(payload, "language"),
                voice_id=voice_id,
                instruction=designed_instruction or _optional_str(payload.get("instruction")),
                reference_audio=_optional_base64(voice.get("reference_audio_base64")),
                reference_text=_optional_str(voice.get("reference_text")),
                seed=_optional_int(payload.get("seed")),
            ),
        )
        return self._audio_result(request_id, generated)

    async def prepare_voice(
        self,
        payload: Mapping[str, Any],
        *,
        kind: TTSVoiceKind,
    ) -> dict[str, object]:
        request_id = UUID(_required_str(payload, "request_id"))
        role = ModelRole.BASE if kind is TTSVoiceKind.REFERENCE_CLONE else ModelRole.VOICE_DESIGN
        material = (
            _required_str(payload, "reference_audio_sha256")
            if kind is TTSVoiceKind.REFERENCE_CLONE
            else _required_str(payload, "description")
        )
        voice_id = f"local:{kind.value}:{hashlib.sha256(material.encode('utf-8')).hexdigest()}"
        generated = await self._manager.run(
            role,
            lambda model: self._manager._backend.generate(
                model,
                text=_required_str(payload, "preview_text"),
                language=_required_str(payload, "language"),
                voice_id=None,
                instruction=_optional_str(payload.get("description")),
                reference_audio=_optional_base64(payload.get("reference_audio_base64")),
                reference_text=_optional_str(payload.get("reference_text")),
                seed=_optional_int(payload.get("seed")),
            ),
        )
        self._voice_roles[voice_id] = role
        if kind is TTSVoiceKind.DESIGNED:
            self._voice_descriptions[voice_id] = material
        identity = self._identity_payload()
        assert identity is not None
        digest = hashlib.sha256(generated.audio_bytes).hexdigest()
        import base64

        return {
            "request_id": str(request_id),
            "provider_voice_id": voice_id,
            "preview_audio_base64": base64.b64encode(generated.audio_bytes).decode("ascii"),
            "actual_output_sha256": digest,
            "model_identity": identity,
            "voice_kind": kind.value,
        }

    def cancel(self, request_id: UUID) -> dict[str, str]:
        self._cancelled.add(request_id)
        return {"disposition": "requested"}

    def _role_for_voice(self, kind: TTSVoiceKind, voice_id: str) -> ModelRole:
        if kind is TTSVoiceKind.PRESET:
            return ModelRole.CUSTOM_VOICE
        if kind is TTSVoiceKind.REFERENCE_CLONE:
            return ModelRole.BASE
        role = self._voice_roles.get(voice_id)
        if role is None:
            raise RuntimeUnavailable("TTS_VOICE_UNAVAILABLE")
        return role

    def _audio_result(self, request_id: UUID, generated: GeneratedAudio) -> dict[str, object]:
        import base64

        identity = self._identity_payload()
        assert identity is not None
        return {
            "request_id": str(request_id),
            "audio_base64": base64.b64encode(generated.audio_bytes).decode("ascii"),
            "actual_output_sha256": hashlib.sha256(generated.audio_bytes).hexdigest(),
            "sample_rate_hz": generated.sample_rate_hz,
            "channels": generated.channels,
            "sample_width_bytes": generated.sample_width_bytes,
            "content_type": "audio/wav",
            "model_identity": identity,
        }

    def _identity_payload(self) -> dict[str, object] | None:
        config = self._manager.loaded_config
        if config is None:
            return None
        return {
            "provider_id": "local_qwen3_tts",
            "model_id": config.model_id,
            "model_revision": config.model_revision,
            "runtime_id": "mlx-audio",
            "runtime_version": self._manager.runtime_version,
            "quantization": config.quantization,
            "artifact_tree_sha256": config.artifact_tree_sha256,
            "schema_version": "qwen-tts-model-fingerprint/1",
        }

    def model_fingerprint_sha256(self) -> str | None:
        identity = self._identity_payload()
        return _canonical_sha256(identity) if identity is not None else None


def _required_str(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError("INVALID_REQUEST")
    return value


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError("INVALID_REQUEST")
    return value


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("INVALID_REQUEST")
    return value


def _optional_base64(value: Any) -> bytes | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError("INVALID_REQUEST")
    import base64

    try:
        return base64.b64decode(value, validate=True)
    except ValueError as error:
        raise ValueError("INVALID_REQUEST") from error
