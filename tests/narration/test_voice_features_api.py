from __future__ import annotations

from fastapi.routing import APIRoute
import pytest
from pydantic import ValidationError

from backend.narration import schemas as wire
from backend.narration.voice_features_api import (
    CharacterVoiceMatchRequest,
    CharacterVoiceMatchResource,
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
        PrivateVoiceDeletionRequestResource
        is wire.PrivateVoiceDeletionRequestResource
    )
    assert PrivateVoiceLifecycleResource is wire.PrivateVoiceLifecycleResource


def test_plan35_feature_routes_and_idempotency_boundaries_are_exact() -> None:
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
    }

    creation_paths = {
        "/novels/{novel_id}/nano-voice-experiments",
        "/novels/{novel_id}/voice-profiles/{profile_id}/deletion-requests",
        "/novels/{novel_id}/characters/{character_id}/official-voice-match",
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
