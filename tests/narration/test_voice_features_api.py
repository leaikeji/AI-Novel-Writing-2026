from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from fastapi.routing import APIRoute
import pytest
from pydantic import ValidationError

from backend.model_runtime import ModelAudit, ModelVerificationError
from backend.narration import schemas as wire
from backend.narration.character_cast_plan_service import CharacterCastPlanLease
import backend.narration.voice_features_api as voice_features_api
from backend.narration.voice_features_api import (
    CharacterCastPlanListResource,
    CharacterCastPlanResource,
    CharacterVoiceGeneratorCommandListResource,
    CharacterVoiceGeneratorCommandResource,
    CharacterVoiceMatchRequest,
    CharacterVoiceMatchResource,
    CreateCharacterCastPlanRequest,
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
    assert CreateCharacterCastPlanRequest is wire.CreateCharacterCastPlanRequest
    assert CharacterCastPlanResource is wire.CharacterCastPlanResource
    assert CharacterCastPlanListResource is wire.CharacterCastPlanListResource
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


def test_voice_preparation_projects_active_generic_pack_or_starts_one_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = uuid4()
    events: list[tuple[str, object]] = []

    class Service:
        ready = True

        def active_pack_ready(self) -> bool:
            return self.ready

        def ensure_novel_projection(self, value) -> None:
            events.append(("project", value))

        def build(self, *, idempotency_key: str) -> None:
            events.append(("build", idempotency_key))

    service = Service()
    monkeypatch.setattr(
        voice_features_api,
        "current_generic_voice_pack_service",
        lambda: service,
    )

    voice_features_api._prepare_generic_voice_pack_for_novel(novel_id)
    service.ready = False
    voice_features_api._prepare_generic_voice_pack_for_novel(novel_id)

    assert events == [
        ("project", novel_id),
        ("build", voice_features_api.AUTOMATIC_GENERIC_PACK_BUILD_KEY),
    ]


def test_generic_pack_failure_never_blocks_existing_official_narration_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Service:
        def active_pack_ready(self) -> bool:
            raise RuntimeError("isolated failure")

    monkeypatch.setattr(
        voice_features_api,
        "current_generic_voice_pack_service",
        lambda: Service(),
    )

    voice_features_api._prepare_generic_voice_pack_for_novel(uuid4())


def test_plan35_plan40_and_plan47_routes_and_idempotency_boundaries_are_exact() -> None:
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
        ("/novels/{novel_id}/character-cast-plans", "GET"),
        ("/novels/{novel_id}/character-cast-plans", "POST"),
        (
            "/novels/{novel_id}/character-cast-plans/{command_id}",
            "GET",
        ),
        (
            "/novels/{novel_id}/character-cast-plans/{command_id}/advance",
            "POST",
        ),
        (
            "/novels/{novel_id}/character-cast-plans/{command_id}/retry",
            "POST",
        ),
        ("/novels/{novel_id}/voice-preparation-commands", "GET"),
        ("/novels/{novel_id}/voice-preparation-commands", "POST"),
        ("/novels/{novel_id}/voice-preparation-commands/{command_id}", "GET"),
        (
            "/novels/{novel_id}/voice-preparation-commands/{command_id}/resume",
            "POST",
        ),
        (
            "/novels/{novel_id}/voice-preparation-commands/{command_id}/retry",
            "POST",
        ),
        (
            "/novels/{novel_id}/voice-preparation-commands/{command_id}/cancel",
            "POST",
        ),
        ("/voice-library/generic-pack", "GET"),
        ("/voice-library/generic-pack/build-commands", "POST"),
        ("/voice-library/generic-pack/build-commands/{command_id}", "GET"),
        (
            "/voice-library/generic-pack/build-commands/{command_id}/retry",
            "POST",
        ),
        (
            "/voice-library/generic-pack/build-commands/{command_id}/cancel",
            "POST",
        ),
        ("/voice-library/generic-pack/slots/{slot_key}/regenerate", "POST"),
        ("/voice-library/generic-pack/slots/{slot_key}/reject", "POST"),
    }

    creation_paths = {
        "/novels/{novel_id}/nano-voice-experiments",
        "/novels/{novel_id}/voice-profiles/{profile_id}/deletion-requests",
        "/novels/{novel_id}/characters/{character_id}/official-voice-match",
        "/novels/{novel_id}/characters/{character_id}/voice-generator-commands",
        "/novels/{novel_id}/character-cast-plans",
        "/novels/{novel_id}/voice-preparation-commands",
        "/voice-library/generic-pack/build-commands",
        "/voice-library/generic-pack/slots/{slot_key}/regenerate",
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


@pytest.mark.asyncio
async def test_cast_advance_claims_before_model_call_and_persists_before_finalize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = uuid4()
    command_id = uuid4()
    item_id = uuid4()
    timeline_id = uuid4()
    fence = uuid4()
    events: list[str] = []
    lease = CharacterCastPlanLease(
        command_id=command_id,
        item_id=item_id,
        target_key="narrator",
        target_kind="narrator",
        character_id=None,
        timeline_id=timeline_id,
        attempt=1,
        fence_token=fence,
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=15),
        workspace_digest="a" * 64,
        prompt_payload={
            "narration_settings": {"language": "zh-CN"},
            "novel": {
                "title": "雾港来信",
                "genre": "悬疑",
                "subgenre": "刑侦",
                "description": "克制冷峻的调查故事",
                "idea": "旧案重启",
                "highlight": "多线索收束",
                "background": "沿海旧城",
                "main_plot": "刑警追查旧案",
            },
        },
        narration_language="zh-CN",
    )
    terminal = object()

    class FakeService:
        def claim_next(self, **kwargs):
            events.append("claim")
            assert kwargs == {"novel_id": novel_id, "command_id": command_id}
            return lease

        def finish_analysis(self, **kwargs):
            events.append("finish")
            assert kwargs["item_id"] == item_id
            assert kwargs["attempt"] == 1
            assert kwargs["fence_token"] == fence
            assert kwargs["analysis"].workspace_digest == "a" * 64
            return True

        def fail_analysis(self, **_kwargs):
            raise AssertionError("successful analysis must not be failed")

        def finalize_if_ready(self, **kwargs):
            events.append("finalize")
            assert kwargs == {"novel_id": novel_id, "command_id": command_id}
            return terminal

    class FakeContext:
        async def chat(self, _prompt, **kwargs):
            events.append("model")
            assert kwargs["skill"] == "character-craft"
            assert str(command_id) in kwargs["session_id"]
            return object()

    class FakeEvidence:
        def as_dict(self):
            return {"schema_version": "model-execution-evidence/2"}

    async def verify(*_args, **_kwargs):
        events.append("verify")
        return FakeEvidence()

    monkeypatch.setattr(voice_features_api, "_require_capability", lambda _key: None)
    monkeypatch.setattr(
        voice_features_api,
        "_character_cast_plan_service",
        lambda: FakeService(),
    )
    monkeypatch.setattr(voice_features_api, "verify_novel_model_reply", verify)
    monkeypatch.setattr(voice_features_api, "reply_final_text", lambda _reply: "{}")
    monkeypatch.setattr(
        voice_features_api,
        "parse_model_json",
        lambda _text: {
            "schema_version": "narrator-voice-brief/1",
            "language": "zh-CN",
            "presentation": "androgynous",
            "pitch": -1,
            "pace": 0,
            "energy": 1,
            "texture": "dark",
            "evidence_fields": [
                "language:narration_settings.language",
                "presentation:novel.genre",
                "pitch:novel.description",
                "pace:novel.main_plot",
                "energy:novel.highlight",
                "texture:novel.background",
            ],
        },
    )
    monkeypatch.setattr(
        voice_features_api,
        "ensure_prompt_within_effective_limit",
        lambda _prompt, _model: events.append("prompt_checked"),
    )
    configured_model = ModelAudit(
        provider_id="provider-a",
        model_id="model-a",
        source="effective-model-api",
        agent_id="ai-novel-writer",
        effective_max_input_length=131_072,
    )

    async def effective_model(_app, *, agent_id):
        assert agent_id == "ai-novel-writer"
        return configured_model

    monkeypatch.setattr(voice_features_api, "effective_model_audit", effective_model)

    result = await voice_features_api.character_cast_plan_advance(
        novel_id,
        command_id,
        request=SimpleNamespace(app=object()),
        ctx=FakeContext(),
    )

    assert result is terminal
    assert events == [
        "claim",
        "prompt_checked",
        "model",
        "verify",
        "finish",
        "finalize",
    ]


@pytest.mark.asyncio
async def test_cast_advance_persists_preflight_model_outage_after_durable_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = uuid4()
    command_id = uuid4()
    item_id = uuid4()
    fence = uuid4()
    events: list[str] = []
    lease = CharacterCastPlanLease(
        command_id=command_id,
        item_id=item_id,
        target_key="narrator",
        target_kind="narrator",
        character_id=None,
        timeline_id=uuid4(),
        attempt=2,
        fence_token=fence,
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=15),
        workspace_digest="b" * 64,
        prompt_payload={},
        narration_language="zh-CN",
    )
    terminal = object()

    class FakeService:
        def claim_next(self, **_kwargs):
            events.append("claim")
            return lease

        def finish_analysis(self, **_kwargs):
            raise AssertionError("model outage must not finish analysis")

        def fail_analysis(self, **kwargs):
            events.append("fail")
            assert kwargs == {
                "novel_id": novel_id,
                "command_id": command_id,
                "item_id": item_id,
                "attempt": 2,
                "fence_token": fence,
                "failure_code": "CAST_PLAN_MODEL_UNAVAILABLE",
            }
            return True

        def finalize_if_ready(self, **_kwargs):
            events.append("finalize")
            return terminal

    async def unavailable(_app, *, agent_id):
        events.append("preflight")
        assert agent_id == "ai-novel-writer"
        raise ModelVerificationError("model unavailable")

    monkeypatch.setattr(voice_features_api, "_require_capability", lambda _key: None)
    monkeypatch.setattr(
        voice_features_api,
        "_character_cast_plan_service",
        lambda: FakeService(),
    )
    monkeypatch.setattr(voice_features_api, "effective_model_audit", unavailable)

    result = await voice_features_api.character_cast_plan_advance(
        novel_id,
        command_id,
        request=SimpleNamespace(app=object()),
        ctx=SimpleNamespace(),
    )

    assert result is terminal
    assert events == ["claim", "preflight", "fail", "finalize"]
