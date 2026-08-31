from __future__ import annotations

import hashlib
import wave
from dataclasses import replace
from io import BytesIO
from uuid import uuid4

import pytest

from backend.narration.adapters import (
    AdapterUnavailableError,
    DisabledVoiceDesignAdapter,
    FakeMossNanoTTSAdapter,
    FakeVoiceDesignAdapter,
    MOSS_NANO_SIDECAR_CONTRACT_CAPABILITIES,
    MossNanoTTSAdapter,
    VoiceDesignAdapter,
    VOICE_DESIGN_NO_GO_CAPABILITIES,
)
from backend.narration.contracts import (
    AdapterHealthStatus,
    AdapterKind,
    CancelDisposition,
    NarrationRequestScope,
    SynthesisRequest,
    VoiceDesignRequest,
)
from backend.narration.fingerprints import (
    capabilities_fingerprint,
    model_fingerprint_sha256,
)


def _synthesis_request(request_id=None) -> SynthesisRequest:
    return SynthesisRequest(
        request_id=request_id or uuid4(),
        scope=NarrationRequestScope.fixed_local(),
        text="雨停了，城墙上的风仍带着潮气。",
        voice="Junhao",
        seed=0,
        sample_mode="fixed",
        max_new_frames=375,
    )


def test_adapter_abstractions_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError):
        MossNanoTTSAdapter()
    with pytest.raises(TypeError):
        VoiceDesignAdapter()


@pytest.mark.asyncio
async def test_fake_nano_exposes_technical_contract_but_never_product_readiness() -> None:
    adapter = FakeMossNanoTTSAdapter()
    assert adapter.capabilities == replace(
        MOSS_NANO_SIDECAR_CONTRACT_CAPABILITIES,
        is_test_double=True,
    )
    assert adapter.capabilities.adapter_kind is AdapterKind.MOSS_NANO_TTS
    assert adapter.capabilities.supports_synthesis is True
    assert adapter.capabilities.supports_reference_audio is True
    assert adapter.capabilities.supports_nano_decode_parameters is True
    assert adapter.capabilities.is_test_double is True
    assert adapter.capabilities.product_visible is False
    assert adapter.capabilities.production_ready is False

    health = await adapter.health()
    fingerprint = await adapter.model_fingerprint()
    assert health.status is AdapterHealthStatus.HEALTHY
    assert health.capabilities_sha256 == capabilities_fingerprint(adapter.capabilities)
    assert health.model_fingerprint_sha256 == model_fingerprint_sha256(fingerprint)


@pytest.mark.asyncio
async def test_fake_nano_returns_deterministic_valid_wav_and_actual_hash() -> None:
    adapter = FakeMossNanoTTSAdapter()
    request_id = uuid4()
    first = await adapter.synthesize(_synthesis_request(request_id))
    second = await adapter.synthesize(_synthesis_request(request_id))
    assert first.audio_bytes == second.audio_bytes
    assert first.actual_output_sha256 == hashlib.sha256(first.audio_bytes).hexdigest()
    assert first.model_fingerprint == await adapter.model_fingerprint()
    assert first.worker_generation == 1

    with wave.open(BytesIO(first.audio_bytes), "rb") as wav:
        assert wav.getframerate() == 48_000
        assert wav.getnchannels() == 2
        assert wav.getsampwidth() == 2
        assert wav.getnframes() == 480


@pytest.mark.asyncio
async def test_fake_nano_cancel_is_explicit_and_fail_closed() -> None:
    adapter = FakeMossNanoTTSAdapter()
    request = _synthesis_request()
    assert await adapter.cancel(request.request_id) is CancelDisposition.REQUESTED
    assert await adapter.cancel(request.request_id) is CancelDisposition.ALREADY_TERMINAL
    with pytest.raises(AdapterUnavailableError, match="cancelled"):
        await adapter.synthesize(request)


@pytest.mark.asyncio
async def test_voice_design_is_disabled_by_default_for_current_no_go() -> None:
    adapter = DisabledVoiceDesignAdapter()
    assert adapter.capabilities == VOICE_DESIGN_NO_GO_CAPABILITIES
    assert adapter.capabilities.adapter_kind is AdapterKind.VOICE_DESIGN
    assert adapter.capabilities.supports_voice_design is False
    assert adapter.capabilities.product_visible is False
    assert adapter.capabilities.production_ready is False
    health = await adapter.health()
    assert health.status is AdapterHealthStatus.DISABLED
    assert health.reason_code == "VOICE_GENERATOR_NO_GO"
    assert await adapter.model_fingerprint() is None
    assert await adapter.cancel(uuid4()) is CancelDisposition.UNSUPPORTED
    with pytest.raises(AdapterUnavailableError, match="VOICE_GENERATOR_NO_GO"):
        await adapter.design_voice(
            VoiceDesignRequest(
                request_id=uuid4(),
                scope=NarrationRequestScope.fixed_local(),
                description="温和、沉稳的中年女性声音",
                preview_text="这是一段测试文本。",
                seed=0,
            )
        )


@pytest.mark.asyncio
async def test_fake_voice_design_remains_test_only_and_hashes_actual_bytes() -> None:
    adapter = FakeVoiceDesignAdapter()
    request = VoiceDesignRequest(
        request_id=uuid4(),
        scope=NarrationRequestScope.fixed_local(),
        description="温和、沉稳的中年女性声音",
        preview_text="这是一段测试文本。",
        seed=0,
    )
    result = await adapter.design_voice(request)
    assert adapter.capabilities.is_test_double is True
    assert adapter.capabilities.product_visible is False
    assert adapter.capabilities.production_ready is False
    assert result.actual_output_sha256 == hashlib.sha256(
        result.candidate_audio_bytes
    ).hexdigest()
