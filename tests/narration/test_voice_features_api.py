from __future__ import annotations

from fastapi.routing import APIRoute
import pytest
from pydantic import ValidationError

from backend.narration import schemas as wire
import backend.narration.voice_features_api as voice_features_api
from backend.narration.voice_features_api import (
    CharacterVoiceGeneratorCommandListResource,
    CharacterVoiceGeneratorCommandResource,
    CharacterVoiceMatchRequest,
    CharacterVoiceMatchResource,
    CreateCharacterVoiceGeneratorCommandRequest,
    CreateNanoVoiceExperimentRequest,
    NanoDecodeParametersResource,
    NanoVoiceExperimentListResource,
    NanoVoiceExperimentResource,
    PrivateVoiceDeletionRequestResource,
    PrivateVoiceLifecycleResource,
    router,
)


def _route(path: str, method: str) -> APIRoute:
    return next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == path
        and method in route.methods
    )


def test_feature_routes_reuse_the_single_public_wire_dto_source() -> None:
    assert NanoDecodeParametersResource is wire.NanoDecodeParametersResource
    assert CreateNanoVoiceExperimentRequest is wire.CreateNanoVoiceExperimentRequest
    assert NanoVoiceExperimentResource is wire.NanoVoiceExperimentResource
    assert NanoVoiceExperimentListResource is wire.NanoVoiceExperimentListResource
    assert CharacterVoiceMatchRequest is wire.CharacterVoiceMatchRequest
    assert CharacterVoiceMatchResource is wire.CharacterVoiceMatchResource
    assert (
        CreateCharacterVoiceGeneratorCommandRequest
        is wire.CreateCharacterVoiceGeneratorCommandRequest
    )
    assert (
        CharacterVoiceGeneratorCommandResource
        is wire.CharacterVoiceGeneratorCommandResource
    )
    assert (
        CharacterVoiceGeneratorCommandListResource
        is wire.CharacterVoiceGeneratorCommandListResource
    )
    assert (
        PrivateVoiceDeletionRequestResource
        is wire.PrivateVoiceDeletionRequestResource
    )
    assert PrivateVoiceLifecycleResource is wire.PrivateVoiceLifecycleResource


def test_voice_generator_one_click_uses_the_real_run_validated_default_seed() -> None:
    assert voice_features_api._resolved_voice_generator_seed(None) == 104_729
    assert voice_features_api._resolved_voice_generator_seed("130363") == 130_363


def test_existing_voice_generator_resources_remain_recoverable_during_host_outage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = object()
    capability_checks: list[wire.CapabilityKey] = []
    monkeypatch.setattr(
        voice_features_api,
        "current_voice_generator_service",
        lambda: service,
    )
    monkeypatch.setattr(
        voice_features_api,
        "_require_capability",
        lambda key: capability_checks.append(key),
    )

    assert (
        voice_features_api._voice_generator_service(require_actionable=False)
        is service
    )
    assert capability_checks == []
    assert voice_features_api._voice_generator_service() is service
    assert capability_checks == [wire.CapabilityKey.VOICE_GENERATOR]


def test_plan35_and_plan40_feature_routes_and_idempotency_boundaries_are_exact() -> None:
    methods_by_path = {
        (route.path, method)
        for route in router.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }
    assert methods_by_path == {
        ("/novels/{novel_id}/nano-voice-experiments", "GET"),
        ("/novels/{novel_id}/nano-voice-experiments", "POST"),
        ("/novels/{novel_id}/nano-voice-experiments/{command_id}", "GET"),
        (
            "/novels/{novel_id}/nano-voice-experiments/{command_id}/binding",
            "PUT",
        ),
        ("/novels/{novel_id}/private-voice-lifecycle", "GET"),
        (
            "/novels/{novel_id}/voice-profiles/{profile_id}/deletion-requests",
            "POST",
        ),
        ("/novels/{novel_id}/voice-deletion-requests/{request_id}", "GET"),
        (
            "/novels/{novel_id}/voice-deletion-requests/{request_id}/confirm",
            "POST",
        ),
        (
            "/novels/{novel_id}/voice-deletion-requests/{request_id}/cancel",
            "POST",
        ),
        (
            "/novels/{novel_id}/voice-deletion-requests/{request_id}/retry",
            "POST",
        ),
        (
            "/novels/{novel_id}/characters/{character_id}/official-voice-match",
            "POST",
        ),
        (
            "/novels/{novel_id}/characters/{character_id}/voice-generator-commands",
            "GET",
        ),
        (
            "/novels/{novel_id}/characters/{character_id}/voice-generator-commands",
            "POST",
        ),
        ("/novels/{novel_id}/voice-generator-commands/{command_id}", "GET"),
        (
            "/novels/{novel_id}/voice-generator-commands/{command_id}/cancel",
            "POST",
        ),
        (
            "/novels/{novel_id}/voice-generator-commands/{command_id}/retry",
            "POST",
        ),
        (
            "/novels/{novel_id}/voice-generator-commands/{command_id}/binding",
            "PUT",
        ),
    }

    creation_paths = {
        "/novels/{novel_id}/nano-voice-experiments",
        "/novels/{novel_id}/voice-profiles/{profile_id}/deletion-requests",
        "/novels/{novel_id}/characters/{character_id}/official-voice-match",
        "/novels/{novel_id}/characters/{character_id}/voice-generator-commands",
    }
    for path, method in methods_by_path:
        headers = [field.alias for field in _route(path, method).dependant.header_params]
        assert headers == (["Idempotency-Key"] if path in creation_paths and method == "POST" else [])


def test_nano_http_seed_is_a_lossless_canonical_signed_int64_string() -> None:
    payload = {
        "schema_version": "nano-decode-parameters/3",
        "seed": "9223372036854775807",
        "text_temperature_milli": 1_000,
        "text_top_p_milli": 1_000,
        "text_top_k": 50,
        "audio_temperature_milli": 800,
        "audio_top_p_milli": 950,
        "audio_top_k": 25,
        "audio_repetition_penalty_milli": 1_200,
        "sample_mode": "full",
        "max_new_frames": 375,
    }
    resource = NanoDecodeParametersResource.model_validate(payload)

    assert resource.domain().seed == 9_223_372_036_854_775_807
    assert NanoDecodeParametersResource.from_domain(resource.domain()).seed == payload["seed"]

    for invalid_seed in (
        9_223_372_036_854_775_807,
        "9223372036854775808",
        "01",
        "-1",
        "1e3",
    ):
        with pytest.raises(ValidationError):
            NanoDecodeParametersResource.model_validate(
                {**payload, "seed": invalid_seed}
            )
