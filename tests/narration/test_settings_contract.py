from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import re
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from backend.narration import schemas as wire
from backend.narration import settings_api


NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
NOVEL_ID = UUID("10000000-0000-4000-8000-000000000001")
PROFILE_ID = UUID("10000000-0000-4000-8000-000000000002")
VOICE_VERSION_ID = UUID("10000000-0000-4000-8000-000000000003")
RIGHTS_ID = UUID("10000000-0000-4000-8000-000000000004")
CHARACTER_ID = UUID("10000000-0000-4000-8000-000000000005")


def settings_values() -> dict[str, object]:
    return {
        "narrator": None,
        "language": "zh-CN",
        "output_format": "m4a_aac_lc",
        "script_review_policy": "blockers_only",
        "analysis_mode": "local_rules_only",
        "text_rules": {
            "read_chapter_title": True,
            "read_author_notes": False,
            "read_section_breaks": False,
            "first_person_mode": "narrator",
            "first_person_character_id": None,
            "inner_monologue_mode": "character",
        },
        "timing": {
            "sentence_gap_ms": 220,
            "paragraph_gap_ms": 480,
            "section_gap_ms": 850,
        },
        "casting": {
            "anonymous_reuse_scope": "scene",
            "same_scene_voice_deduplication": True,
            "unknown_speaker_action": "block",
        },
        "playback": {"playback_rate": 1.0, "volume": 1.0},
    }


def default_settings_resource() -> dict[str, object]:
    return {
        "contract_version": wire.NARRATION_SETTINGS_API_VERSION,
        "schema_version": wire.NARRATION_SETTINGS_SCHEMA_VERSION,
        "novel_id": NOVEL_ID,
        "settings_id": None,
        "exists": False,
        "version": 0,
        "values": settings_values(),
        "updated_at": None,
    }


def rights_summary() -> dict[str, object]:
    return {
        "rights_record_id": RIGHTS_ID,
        "state": "active",
        "notice_version": "voice-rights/1",
        "source_kind": "user_upload",
        "source_identifier_sha256": "d" * 64,
        "purpose": "private_novel_narration",
        "commercial_use": False,
        "redistribution": False,
        "voice_cloning": True,
        "subject_consent_recorded": True,
        "confirmed_at": NOW,
        "expires_at": None,
        "risk_flags": [],
    }


def locked_voice_version() -> dict[str, object]:
    return {
        "schema_version": wire.NARRATION_VOICE_SCHEMA_VERSION,
        "version_id": VOICE_VERSION_ID,
        "profile_id": PROFILE_ID,
        "version_number": 1,
        "source_type": "uploaded",
        "state": "locked",
        "provider_id": "moss-nano",
        "model_id": "MOSS-TTS-Nano-100M-ONNX",
        "model_revision": "frozen-revision",
        "preset_key": None,
        "language": "zh-CN",
        "fingerprint": "a" * 64,
        "quality_state": "accepted",
        "activation_basis": "preview_confirmed",
        "validation_basis": "human_accepted",
        "rights": rights_summary(),
        "reference_asset_id": uuid4(),
        "preview_asset": None,
        "description_available": False,
        "locked_at": NOW,
        "created_at": NOW - timedelta(minutes=5),
    }


def profile_resource() -> dict[str, object]:
    return {
        "contract_version": wire.NARRATION_SETTINGS_API_VERSION,
        "schema_version": wire.NARRATION_VOICE_SCHEMA_VERSION,
        "profile_id": PROFILE_ID,
        "novel_id": NOVEL_ID,
        "name": "女主角",
        "status": "active",
        "version": 2,
        "current_version_id": VOICE_VERSION_ID,
        "versions": [locked_voice_version()],
        "created_at": NOW - timedelta(hours=1),
        "updated_at": NOW,
        "archived_at": None,
    }


def test_capability_baseline_is_complete_and_fail_closed() -> None:
    matrix = wire.t2_hold_capabilities()

    assert {item.key for item in matrix.items} == set(wire.CapabilityKey)
    assert all(not item.actionable for item in matrix.items)
    assert matrix.item(wire.CapabilityKey.READING_SETTINGS).state is wire.CapabilityState.HOLD
    assert matrix.item(wire.CapabilityKey.REFERENCE_CLONE).visible is False
    assert matrix.item(wire.CapabilityKey.VOICE_GENERATOR).visible is False
    assert matrix.item(wire.CapabilityKey.GENERIC_VOICE_POOL).reason_code == (
        "GENERIC_VOICE_ASSETS_UNAVAILABLE"
    )


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ({"state": "enabled", "actionable": False}, "enabled capability"),
        ({"state": "hold", "actionable": True}, "non-enabled capability"),
        ({"state": "unavailable", "reason_code": None}, "non-enabled capability"),
        ({"visible": False, "actionable": True}, "non-enabled capability"),
    ],
)
def test_capability_shape_cannot_claim_an_unusable_feature(
    patch: dict[str, object], message: str
) -> None:
    value: dict[str, object] = {
        "key": "reference_clone",
        "state": "hold",
        "visible": False,
        "actionable": False,
        "reason_code": "REFERENCE_CLONE_PRODUCT_GATE_HOLD",
        "required_gate": "T2-D",
    }
    value.update(patch)
    with pytest.raises(ValidationError, match=message):
        wire.FeatureCapability.model_validate(value)


def test_settings_contract_is_strict_and_has_safe_defaults() -> None:
    resource = wire.NarrationSettingsResource.model_validate(default_settings_resource())

    assert resource.version == 0
    assert resource.values.script_review_policy is wire.ScriptReviewPolicy.BLOCKERS_ONLY
    assert resource.values.analysis_mode is wire.AnalysisMode.LOCAL_RULES_ONLY
    assert resource.values.playback.playback_rate == 1.0

    invalid = default_settings_resource()
    invalid["owner_id"] = uuid4()
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        wire.NarrationSettingsResource.model_validate(invalid)


def test_settings_reject_invalid_first_person_target_and_non_exact_scalars() -> None:
    values = settings_values()
    values["text_rules"] = {
        **values["text_rules"],  # type: ignore[arg-type]
        "first_person_mode": "character",
        "first_person_character_id": None,
    }
    with pytest.raises(ValidationError, match="requires a character id"):
        wire.NarrationSettingsValues.model_validate(values)

    values = settings_values()
    values["text_rules"] = {
        **values["text_rules"],  # type: ignore[arg-type]
        "read_chapter_title": 1,
    }
    with pytest.raises(ValidationError):
        wire.NarrationSettingsValues.model_validate(values)

    values = settings_values()
    values["playback"] = {
        **values["playback"],  # type: ignore[arg-type]
        "playback_rate": "1.25",
    }
    with pytest.raises(ValidationError):
        wire.NarrationSettingsValues.model_validate(values)


def test_scope_override_uses_replace_semantics_and_exact_cas() -> None:
    enabled = wire.PutNarrationScopeOverrideRequest.model_validate(
        {
            "expected_version": 0,
            "enabled": True,
            "overrides": {
                "narrator": None,
                "language": "zh-CN",
                "text_rules": None,
                "timing": None,
            },
        }
    )
    assert enabled.overrides.language == "zh-CN"

    with pytest.raises(ValidationError, match="enabled override must contain"):
        wire.PutNarrationScopeOverrideRequest.model_validate(
            {
                "expected_version": 0,
                "enabled": True,
                "overrides": {
                    "narrator": None,
                    "language": None,
                    "text_rules": None,
                    "timing": None,
                },
            }
        )

    scope_id = uuid4()
    item = {
        "contract_version": wire.NARRATION_SETTINGS_API_VERSION,
        "override_id": uuid4(),
        "novel_id": NOVEL_ID,
        "scope_kind": "chapter",
        "scope_id": scope_id,
        "enabled": True,
        "version": 1,
        "overrides": {
            "narrator": None,
            "language": "zh-CN",
            "text_rules": None,
            "timing": None,
        },
    }
    wire.NarrationScopeOverrideListResponse.model_validate(
        {
            "contract_version": wire.NARRATION_SETTINGS_API_VERSION,
            "novel_id": NOVEL_ID,
            "items": [item],
        }
    )
    with pytest.raises(ValidationError, match="response novel"):
        wire.NarrationScopeOverrideListResponse.model_validate(
            {
                "contract_version": wire.NARRATION_SETTINGS_API_VERSION,
                "novel_id": uuid4(),
                "items": [item],
            }
        )
    with pytest.raises(ValidationError, match="unique per kind"):
        wire.NarrationScopeOverrideListResponse.model_validate(
            {
                "contract_version": wire.NARRATION_SETTINGS_API_VERSION,
                "novel_id": NOVEL_ID,
                "items": [item, {**item, "override_id": uuid4()}],
            }
        )


def test_cloud_consent_requires_explicit_confirmation_and_scoped_model_pair() -> None:
    with pytest.raises(ValidationError, match="explicitly confirmed"):
        wire.CreateNarrationCloudConsentRequest.model_validate(
            {
                "notice_version": "narration-cloud/1",
                "data_scope": "uncertain_segments_with_minimal_context",
                "provider_id": None,
                "model_id": None,
                "confirmed": False,
            }
        )

    with pytest.raises(ValidationError, match="must be set together"):
        wire.CreateNarrationCloudConsentRequest.model_validate(
            {
                "notice_version": "narration-cloud/1",
                "data_scope": "uncertain_segments_with_minimal_context",
                "provider_id": "provider",
                "model_id": None,
                "confirmed": True,
            }
        )

    not_granted = wire.NarrationCloudConsent.model_validate(
        {
            "consent_id": None,
            "version": 0,
            "state": "not_granted",
            "purpose": "narration_speaker_analysis",
            "data_scope": "uncertain_segments_with_minimal_context",
            "notice_version": None,
            "provider_id": None,
            "model_id": None,
            "confirmed_at": None,
            "revoked_at": None,
        }
    )
    assert not_granted.version == 0
    with pytest.raises(ValidationError, match="empty version-zero"):
        wire.NarrationCloudConsent.model_validate(
            {**not_granted.model_dump(mode="json"), "version": 1}
        )
    assert wire.RevokeNarrationCloudConsentRequest.model_validate(
        {"consent_id": uuid4(), "expected_version": 1}
    ).expected_version == 1


def test_uploaded_voice_rights_cannot_be_silently_inferred() -> None:
    base = {
        "notice_version": "voice-rights/1",
        "source_identifier": "recording-1",
        "purpose": "private_novel_narration",
        "commercial_use": False,
        "redistribution": False,
        "voice_cloning": True,
        "subject_consent_reference": "consent-local-1",
        "confirmed": True,
    }
    assert wire.VoiceRightsDeclarationRequest.model_validate(base).voice_cloning

    with pytest.raises(ValidationError, match="voice-cloning permission"):
        wire.VoiceRightsDeclarationRequest.model_validate(
            {**base, "voice_cloning": False}
        )
    with pytest.raises(ValidationError, match="explicitly confirmed"):
        wire.VoiceRightsDeclarationRequest.model_validate(
            {**base, "confirmed": False}
        )


def test_voice_version_and_profile_freeze_locked_identity() -> None:
    version = wire.VoiceProfileVersionResource.model_validate(locked_voice_version())
    profile = wire.VoiceProfileResource.model_validate(profile_resource())

    assert version.state is wire.VoiceVersionState.LOCKED
    assert profile.current_version_id == VOICE_VERSION_ID

    invalid = locked_voice_version()
    invalid["quality_state"] = "pending"
    with pytest.raises(ValidationError, match="activation evidence is inconsistent"):
        wire.VoiceProfileVersionResource.model_validate(invalid)

    invalid_profile = profile_resource()
    invalid_profile["current_version_id"] = uuid4()
    with pytest.raises(ValidationError, match="current version must name"):
        wire.VoiceProfileResource.model_validate(invalid_profile)


def test_official_voice_selection_request_has_one_exact_target_shape() -> None:
    narrator = wire.OfficialVoiceSelectionRequest.model_validate(
        {
            "preset_id": "onnx.Junhao",
            "target_kind": "narrator",
            "character_id": None,
            "expected_settings_version": 0,
            "expected_binding_version": None,
        }
    )
    assert narrator.target_kind is wire.OfficialVoiceSelectionTargetKind.NARRATOR

    character = wire.OfficialVoiceSelectionRequest.model_validate(
        {
            "preset_id": "onnx.Arisa",
            "target_kind": "character",
            "character_id": CHARACTER_ID,
            "expected_settings_version": 3,
            "expected_binding_version": 0,
        }
    )
    assert character.target_kind is wire.OfficialVoiceSelectionTargetKind.CHARACTER

    with pytest.raises(ValidationError, match="cannot carry character"):
        wire.OfficialVoiceSelectionRequest.model_validate(
            {
                **narrator.model_dump(mode="python"),
                "character_id": CHARACTER_ID,
                "expected_binding_version": 0,
            }
        )
    with pytest.raises(ValidationError, match="absent from the pinned"):
        wire.OfficialVoiceSelectionRequest.model_validate(
            {**narrator.model_dump(mode="python"), "preset_id": "onnx.Unknown"}
        )

    wrong_parent = locked_voice_version()
    wrong_parent["profile_id"] = uuid4()
    with pytest.raises(ValidationError, match="enclosing profile"):
        wire.VoiceProfileResource.model_validate(
            {**profile_resource(), "versions": [wrong_parent]}
        )


def test_character_binding_shape_matches_database_guard() -> None:
    configured = wire.PutCharacterVoiceBindingRequest.model_validate(
        {
            "expected_version": 0,
            "binding_policy": "dedicated",
            "profile_id": PROFILE_ID,
            "version_id": VOICE_VERSION_ID,
            "language": "zh-CN",
        }
    )
    assert configured.binding_policy is wire.CharacterVoiceBindingPolicy.DEDICATED

    with pytest.raises(ValidationError, match="configured binding requires"):
        wire.PutCharacterVoiceBindingRequest.model_validate(
            {
                "expected_version": 0,
                "binding_policy": "inherited",
                "profile_id": None,
                "version_id": None,
                "language": "zh-CN",
            }
        )
    with pytest.raises(ValidationError, match="unset binding cannot"):
        wire.PutCharacterVoiceBindingRequest.model_validate(
            {
                "expected_version": 0,
                "binding_policy": "unset",
                "profile_id": PROFILE_ID,
                "version_id": VOICE_VERSION_ID,
                "language": "zh-CN",
            }
        )

    unset_resource = {
        "contract_version": wire.NARRATION_SETTINGS_API_VERSION,
        "binding_id": None,
        "novel_id": NOVEL_ID,
        "character_id": CHARACTER_ID,
        "binding_policy": "unset",
        "profile_id": None,
        "version_id": None,
        "language": "zh-CN",
        "version": 0,
        "impact": {
            "affected_chapter_count": 0,
            "affected_segment_count": 0,
            "historical_edition_count": 0,
            "regeneration_required": False,
        },
        "updated_at": None,
    }
    wire.CharacterVoiceBindingResource.model_validate(unset_resource)
    with pytest.raises(ValidationError, match="empty version-zero"):
        wire.CharacterVoiceBindingResource.model_validate(
            {**unset_resource, "updated_at": NOW}
        )


def test_casting_rule_request_cannot_forge_server_identity_or_target_shape() -> None:
    rule = {
        "priority": 10,
        "enabled": True,
        "condition": {
            "speaker_kinds": ["anonymous"],
            "genders": ["female"],
            "age_bands": ["elderly"],
            "context_kinds": ["dialogue"],
            "role_tags": ["路人"],
        },
        "target": {
            "kind": "require_review",
            "pool_id": None,
            "slot_key": None,
            "profile_id": None,
            "version_id": None,
        },
    }
    request = wire.PutVoiceCastingRulesRequest.model_validate(
        {"expected_version": 0, "items": [rule]}
    )
    assert request.items[0].target.kind is wire.VoiceCastingTargetKind.REQUIRE_REVIEW

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        wire.PutVoiceCastingRulesRequest.model_validate(
            {
                "expected_version": 0,
                "items": [{**rule, "rule_id": uuid4(), "source": "user"}],
            }
        )
    with pytest.raises(ValidationError, match="cannot carry a voice"):
        wire.VoiceCastingTarget.model_validate(
            {
                "kind": "require_review",
                "pool_id": None,
                "slot_key": None,
                "profile_id": PROFILE_ID,
                "version_id": VOICE_VERSION_ID,
            }
        )


def test_generic_pool_update_uses_server_derived_slot_state() -> None:
    slots = [
        {
            "slot_key": f"slot-{index}",
            "voice_version_id": uuid4(),
            "enabled": True,
            "priority": index,
        }
        for index in range(24)
    ]
    request = wire.PutGenericVoicePoolRequest.model_validate(
        {"expected_version": 0, "slots": slots}
    )
    assert len(request.slots) == 24

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        wire.PutGenericVoicePoolRequest.model_validate(
            {
                "expected_version": 0,
                "slots": [{**item, "state": "ready"} for item in slots],
            }
        )


def test_media_links_never_expose_filesystem_or_supplier_urls() -> None:
    asset_id = uuid4()
    valid = {
        "asset_id": asset_id,
        "content_path": f"/media-assets/{asset_id}/content",
        "mime_type": "audio/mp4",
        "byte_size": 100,
        "duration_ms": 500,
        "checksum_sha256": "b" * 64,
    }
    assert wire.MediaAssetLink.model_validate(valid).content_path.startswith("/")

    for path in ("file:///tmp/private.wav", "https://supplier.test/audio", "/media-assets/../secret/content"):
        with pytest.raises(ValidationError):
            wire.MediaAssetLink.model_validate({**valid, "content_path": path})

    with pytest.raises(ValidationError, match="exactly match asset_id"):
        wire.MediaAssetLink.model_validate(
            {**valid, "content_path": f"/media-assets/{uuid4()}/content"}
        )


def test_voice_source_capability_mapping_cannot_open_no_go_source() -> None:
    base = {
        "source_type": "generated",
        "capability": "voice_generator",
        "available": False,
        "reason_code": "VOICE_GENERATOR_NO_GO",
        "accepted_mime_types": [],
        "maximum_bytes": None,
    }
    wire.VoiceSourceAvailability.model_validate(base)
    with pytest.raises(ValidationError, match="frozen capability"):
        wire.VoiceSourceAvailability.model_validate(
            {**base, "capability": "preset_voice_source"}
        )


def test_overview_cache_cleanup_projection_cannot_exceed_global_gate() -> None:
    capabilities = wire.t2_hold_capabilities()
    sources = [
        wire.VoiceSourceAvailability(
            source_type="preset",
            capability="preset_voice_source",
            available=False,
            reason_code="OFFICIAL_PRESET_CATALOG_NOT_RELEASED",
            accepted_mime_types=[],
            maximum_bytes=None,
        ),
        wire.VoiceSourceAvailability(
            source_type="uploaded",
            capability="reference_clone",
            available=False,
            reason_code="REFERENCE_CLONE_PRODUCT_GATE_HOLD",
            accepted_mime_types=list(wire.REFERENCE_UPLOAD_MIME_TYPES),
            maximum_bytes=wire.REFERENCE_UPLOAD_MAX_BYTES,
        ),
        wire.VoiceSourceAvailability(
            source_type="generated",
            capability="voice_generator",
            available=False,
            reason_code="VOICE_GENERATOR_NO_GO",
            accepted_mime_types=[],
            maximum_bytes=None,
        ),
    ]
    runtime = wire.NarrationRuntimeStatus(
        technical_enabled=False,
        lifecycle_status="disabled",
        sidecar_reachable=False,
        model_ready=False,
        product_visible=False,
        protocol_version="moss-tts-sidecar/1.1",
        model_fingerprint_sha256=None,
        reason_code="RUNTIME_DISABLED",
    )
    cache = wire.NarrationCacheStatus.model_construct(
        novel_id=NOVEL_ID,
        cleanup_capability=wire.FeatureCapability(
            key="cache_cleanup",
            state="enabled",
            visible=True,
            actionable=True,
            reason_code=None,
            required_gate=None,
        ),
    )
    overview = wire.NarrationOverviewResponse.model_construct(
        novel_id=NOVEL_ID,
        capabilities=capabilities,
        runtime=runtime,
        settings=wire.NarrationSettingsResource.model_validate(default_settings_resource()),
        voice_sources=sources,
        cache=cache,
    )
    with pytest.raises(ValueError, match="cannot exceed the global gate"):
        overview.validate_overview_scope()


def test_product_visible_runtime_must_be_ready() -> None:
    with pytest.raises(ValidationError, match="product-visible runtime must be ready"):
        wire.NarrationRuntimeStatus(
            technical_enabled=True,
            lifecycle_status="starting",
            sidecar_reachable=True,
            model_ready=True,
            product_visible=True,
            protocol_version="moss-tts-sidecar/1.1",
            model_fingerprint_sha256="d" * 64,
            reason_code=None,
        )


def test_ready_generic_pool_requires_all_24_approved_slots() -> None:
    slot = lambda index: {
        "slot_key": f"slot-{index}",
        "label": f"声音 {index}",
        "category": "adult_female",
        "state": "ready",
        "voice_version_id": uuid4(),
        "enabled": True,
        "priority": index,
        "reason_code": None,
    }
    pool = {
        "contract_version": wire.NARRATION_SETTINGS_API_VERSION,
        "novel_id": NOVEL_ID,
        "pool_id": uuid4(),
        "state": "ready",
        "version": 1,
        "required_slot_count": 24,
        "ready_slot_count": 24,
        "rights_approved_slot_count": 24,
        "quality_approved_slot_count": 24,
        "production_ready_slot_count": 24,
        "slots": [slot(index) for index in range(24)],
        "reason_codes": [],
    }
    assert wire.GenericVoicePoolResource.model_validate(pool).state is wire.GenericVoicePoolState.READY

    with pytest.raises(ValidationError, match="ready pool requires 24"):
        wire.GenericVoicePoolResource.model_validate(
            {**pool, "production_ready_slot_count": 0}
        )

    with pytest.raises(ValidationError, match="enabled voice"):
        wire.GenericVoicePoolResource.model_validate(
            {
                **pool,
                "slots": [{**slot(0), "enabled": False}]
                + [slot(index) for index in range(1, 24)],
            }
        )

    missing = {
        **pool,
        "pool_id": None,
        "state": "missing",
        "version": 0,
        "reason_codes": ["GENERIC_VOICE_ASSETS_UNAVAILABLE"],
    }
    with pytest.raises(ValidationError, match="missing pool cannot claim"):
        wire.GenericVoicePoolResource.model_validate(missing)


def test_cache_cleanup_result_cannot_claim_source_or_referenced_deletion() -> None:
    valid = {
        "contract_version": wire.NARRATION_SETTINGS_API_VERSION,
        "novel_id": NOVEL_ID,
        "deleted_asset_count": 2,
        "reclaimed_bytes": 42,
        "source_asset_deleted_count": 0,
        "locked_voice_deleted_count": 0,
        "referenced_asset_deleted_count": 0,
    }
    wire.NarrationCacheCleanupResult.model_validate(valid)
    with pytest.raises(ValidationError):
        wire.NarrationCacheCleanupResult.model_validate(
            {**valid, "source_asset_deleted_count": 1}
        )


def test_error_taxonomy_has_one_http_mapping_per_code() -> None:
    assert set(settings_api.NARRATION_ERROR_HTTP_STATUS) == set(wire.NarrationErrorCode)
    assert len(settings_api.NARRATION_ERROR_HTTP_STATUS) == len(wire.NarrationErrorCode)
    assert (
        settings_api.NARRATION_ERROR_HTTP_STATUS[
            wire.NarrationErrorCode.SCOPE_VIOLATION
        ]
        == 404
    )
    assert (
        settings_api.NARRATION_ERROR_HTTP_STATUS[
            wire.NarrationErrorCode.PAYLOAD_TOO_LARGE
        ]
        == 413
    )


def test_python_and_typescript_freeze_identical_enums_and_versions() -> None:
    source = Path("frontend/src/narration/contracts.ts").read_text(encoding="utf-8")

    def string_array(name: str) -> tuple[str, ...]:
        match = re.search(
            rf"export const {name} = \[(.*?)\] as const;",
            source,
            flags=re.DOTALL,
        )
        assert match is not None
        return tuple(re.findall(r'"([A-Za-z0-9_]+)"', match.group(1)))

    assert string_array("CAPABILITY_KEYS") == tuple(
        item.value for item in wire.CapabilityKey
    )
    assert string_array("NARRATION_ERROR_CODES") == tuple(
        item.value for item in wire.NarrationErrorCode
    )
    for version in (
        wire.NARRATION_SETTINGS_API_VERSION,
        wire.NARRATION_SETTINGS_SCHEMA_VERSION,
        wire.NARRATION_CAPABILITY_SCHEMA_VERSION,
        wire.NARRATION_VOICE_SCHEMA_VERSION,
        wire.NARRATION_CACHE_SCHEMA_VERSION,
    ):
        assert f'"{version}"' in source


def test_router_freezes_all_t2_paths_and_methods() -> None:
    actual = {
        (method, route.path)
        for route in settings_api.router.routes
        for method in (route.methods or set())
    }
    expected = {
        ("GET", "/novels/{novel_id}/narration-overview"),
        ("GET", "/novels/{novel_id}/narration-settings"),
        ("PUT", "/novels/{novel_id}/narration-settings"),
        ("PATCH", "/novels/{novel_id}/narration-settings/playback-preferences"),
        ("GET", "/novels/{novel_id}/narration-scope-overrides"),
        ("PUT", "/novels/{novel_id}/narration-scope-overrides/{scope_kind}/{scope_id}"),
        ("POST", "/novels/{novel_id}/narration-cloud-consents"),
        ("DELETE", "/novels/{novel_id}/narration-cloud-consents/current"),
        ("GET", "/voice-presets"),
        ("POST", "/novels/{novel_id}/official-voice-selections"),
        ("GET", "/voice-profiles"),
        ("POST", "/voice-profiles"),
        ("GET", "/voice-profiles/{profile_id}"),
        ("PUT", "/voice-profiles/{profile_id}"),
        ("DELETE", "/voice-profiles/{profile_id}"),
        ("POST", "/voice-profiles/{profile_id}/versions/preset"),
        ("POST", "/voice-profiles/{profile_id}/versions/uploaded"),
        ("POST", "/voice-profiles/{profile_id}/previews"),
        ("GET", "/voice-previews/{preview_id}"),
        ("POST", "/voice-profiles/{profile_id}/lock"),
        ("GET", "/novels/{novel_id}/character-voice-bindings"),
        ("GET", "/novels/{novel_id}/characters/{character_id}/voice-binding"),
        ("PUT", "/novels/{novel_id}/characters/{character_id}/voice-binding"),
        ("GET", "/novels/{novel_id}/generic-voice-pools"),
        ("PUT", "/novels/{novel_id}/generic-voice-pools"),
        ("GET", "/novels/{novel_id}/casting-rules"),
        ("PUT", "/novels/{novel_id}/casting-rules"),
        ("GET", "/novels/{novel_id}/pronunciation-profile"),
        ("PUT", "/novels/{novel_id}/pronunciation-profile"),
        ("GET", "/novels/{novel_id}/narration-cache"),
        ("POST", "/novels/{novel_id}/narration-cache/cleanup-preview"),
        ("POST", "/novels/{novel_id}/narration-cache/cleanup"),
    }
    assert actual == expected


class _FakeBackend:
    def __init__(self, result: object) -> None:
        self.result = result
        self.commands: list[settings_api.NarrationSettingsApiCommand] = []

    def dispatch(self, command: settings_api.NarrationSettingsApiCommand) -> object:
        self.commands.append(command)
        return self.result


def client_for(backend: settings_api.NarrationSettingsApiBackend | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(settings_api.router)
    if backend is not None:
        app.dependency_overrides[settings_api.get_narration_settings_backend] = (
            lambda: backend
        )
    return TestClient(app)


def test_router_fails_closed_before_gate_and_sets_no_store() -> None:
    with client_for() as client:
        response = client.get(f"/novels/{NOVEL_ID}/narration-settings")

    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["detail"]["code"] == "SETTINGS_BACKEND_NOT_INSTALLED"
    assert response.json()["detail"]["capability"] == "reading_settings"


def test_router_dispatches_typed_command_and_validates_response() -> None:
    backend = _FakeBackend(default_settings_resource())
    with client_for(backend) as client:
        response = client.get(f"/novels/{NOVEL_ID}/narration-settings")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    command = backend.commands[0]
    assert command.operation is settings_api.NarrationSettingsOperation.GET_SETTINGS
    assert command.novel_id == NOVEL_ID
    assert response.json()["version"] == 0


def test_cloud_consent_routes_require_idempotency_and_exact_cas_target() -> None:
    consent_id = uuid4()
    active = {
        "consent_id": consent_id,
        "version": 1,
        "state": "active",
        "purpose": "narration_speaker_analysis",
        "data_scope": "uncertain_segments_with_minimal_context",
        "notice_version": "narration-cloud/1",
        "provider_id": None,
        "model_id": None,
        "confirmed_at": NOW,
        "revoked_at": None,
    }
    backend = _FakeBackend(active)
    create_body = {
        "notice_version": "narration-cloud/1",
        "data_scope": "uncertain_segments_with_minimal_context",
        "provider_id": None,
        "model_id": None,
        "confirmed": True,
    }
    with client_for(backend) as client:
        missing_key = client.post(
            f"/novels/{NOVEL_ID}/narration-cloud-consents",
            json=create_body,
        )
        created = client.post(
            f"/novels/{NOVEL_ID}/narration-cloud-consents",
            headers={"Idempotency-Key": "cloud-consent-0001"},
            json=create_body,
        )
        backend.result = {
            **active,
            "version": 2,
            "state": "revoked",
            "revoked_at": NOW,
        }
        revoked = client.request(
            "DELETE",
            f"/novels/{NOVEL_ID}/narration-cloud-consents/current",
            json={"consent_id": str(consent_id), "expected_version": 1},
        )

    assert missing_key.status_code == 422
    assert created.status_code == 201
    assert revoked.status_code == 200
    create_command, revoke_command = backend.commands
    assert create_command.idempotency_key == "cloud-consent-0001"
    assert revoke_command.payload == wire.RevokeNarrationCloudConsentRequest(
        consent_id=consent_id,
        expected_version=1,
    )
    assert revoke_command.expected_version == 1


def test_router_normalizes_request_validation_without_echoing_private_text() -> None:
    backend = _FakeBackend({})
    private_text = "这句私人台词绝不能回显"
    with client_for(backend) as client:
        response = client.post(
            f"/voice-profiles/{PROFILE_ID}/previews",
            headers={"Idempotency-Key": "preview-key-0001"},
            json={"version_id": str(VOICE_VERSION_ID), "preview_text": private_text, "extra": True},
        )

    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["detail"]["code"] == "REQUEST_VALIDATION_FAILED"
    assert private_text not in response.text
    assert backend.commands == []


def test_router_rejects_backend_wire_drift_as_internal_contract_violation() -> None:
    backend = _FakeBackend({**default_settings_resource(), "unexpected": True})
    with client_for(backend) as client:
        response = client.get(f"/novels/{NOVEL_ID}/narration-settings")

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "RESPONSE_CONTRACT_VIOLATION"
    assert "unexpected" not in response.text


def test_uploaded_voice_endpoint_requires_narrow_multipart_before_dispatch() -> None:
    backend = _FakeBackend(locked_voice_version())
    with client_for(backend) as client:
        response = client.post(
            f"/voice-profiles/{PROFILE_ID}/versions/uploaded",
            headers={
                "Idempotency-Key": "upload-key-00001",
                "Content-Type": "application/json",
            },
            json={"audio": "forbidden-base64"},
        )

    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "UNSUPPORTED_MEDIA_TYPE"
    assert backend.commands == []


def test_backend_factory_install_and_uninstall_are_identity_safe() -> None:
    settings_api.uninstall_narration_settings_backend_factory()
    first = lambda _session: _FakeBackend(default_settings_resource())
    second = lambda _session: _FakeBackend(default_settings_resource())
    try:
        settings_api.install_narration_settings_backend_factory(first)
        settings_api.install_narration_settings_backend_factory(first)
        with pytest.raises(RuntimeError, match="already installed"):
            settings_api.install_narration_settings_backend_factory(second)
        with pytest.raises(RuntimeError, match="another narration backend"):
            settings_api.uninstall_narration_settings_backend_factory(second)
    finally:
        settings_api.uninstall_narration_settings_backend_factory(first)

    class UnhashableFactory:
        __hash__ = None  # type: ignore[assignment]

        def __call__(self, _session: object) -> _FakeBackend:
            return _FakeBackend(default_settings_resource())

    unhashable = UnhashableFactory()
    settings_api.install_narration_settings_backend_factory(unhashable)
    settings_api.uninstall_narration_settings_backend_factory(unhashable)
