from __future__ import annotations

from datetime import UTC, datetime
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from backend.narration import schemas as wire
from backend.narration.official_presets import (
    OFFICIAL_PRESET_MANIFEST_SHA256,
    OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256,
    OFFICIAL_PRESET_REPOSITORY,
    OFFICIAL_PRESET_REVISION,
    OFFICIAL_PRESET_RIGHTS_POLICY_VERSION,
    OFFICIAL_PRESET_IDS,
    OFFICIAL_PRESETS,
    CANONICAL_CHAPTER_VERIFIED_PRESET_IDS,
    official_preset_decode_parameters_fingerprint,
    official_preset_direct_version_fingerprint,
    official_preset_validation_tier,
    official_preset_version_fingerprint,
    require_official_preset,
    validate_official_preset_provenance,
    validate_official_version_evidence,
)
from backend.narration.privacy import t4_product_capabilities
from backend.narration.voices import list_official_presets


def test_product_catalog_publishes_small_qwen_catalog_without_audio_payloads() -> None:
    catalog = list_official_presets()

    assert catalog.schema_version == "qwen-tts-preset-catalog/1"
    assert len(catalog.items) == 2
    assert tuple(item.preset_id for item in catalog.items) == tuple(
        item.preset_id for item in OFFICIAL_PRESETS
    )
    assert {item.preset_id for item in catalog.items} == {
        "qwen.WarmFemale",
        "qwen.ClearMale",
    }
    serialized = json.dumps(catalog.model_dump(mode="json"), ensure_ascii=False)
    assert "prompt_audio_codes" not in serialized
    assert "audio_file" not in serialized
    assert "qwen-provider-voice-map/1" in serialized
    assert OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256 in serialized
    assert all(item.local_use_status == "available" for item in catalog.items)
    assert all(
        item.commercial_distribution_status == "not_evaluated"
        for item in catalog.items
    )
    assert {
        item.preset_id
        for item in catalog.items
        if item.validation_tier == "canonical_chapter_verified"
    } == CANONICAL_CHAPTER_VERIFIED_PRESET_IDS == set(OFFICIAL_PRESET_IDS)
    assert all(
        item.language_scope == item.language
        and item.selectable_now
        and not item.previewable_now
        and item.renderable_existing
        and item.usage_notice == "private_local_writing_tool"
        for item in catalog.items
    )


def test_product_catalog_outer_contract_rejects_missing_or_reordered_inventory() -> None:
    product = list_official_presets().model_dump(mode="python")

    missing = {**product, "items": product["items"][:-1]}
    with pytest.raises(ValidationError, match="every pinned preset in order"):
        wire.OfficialPresetCatalogResponse.model_validate(missing)

    reordered_items = list(product["items"])
    reordered_items[0], reordered_items[1] = reordered_items[1], reordered_items[0]
    with pytest.raises(ValidationError, match="every pinned preset in order"):
        wire.OfficialPresetCatalogResponse.model_validate(
            {**product, "items": reordered_items}
        )
    assert official_preset_validation_tier("qwen.WarmFemale") == (
        "canonical_chapter_verified"
    )


def test_low_level_inventory_and_get_by_id_cover_qwen_presets() -> None:
    assert len(OFFICIAL_PRESETS) == 2
    warm = require_official_preset("qwen.WarmFemale")
    assert warm.local_voice_id == "Serena"
    assert validate_official_preset_provenance(warm.provenance()) is warm

    assert OFFICIAL_PRESET_IDS == tuple(preset.preset_id for preset in OFFICIAL_PRESETS)
    assert tuple(
        require_official_preset(preset_id).preset_id for preset_id in OFFICIAL_PRESET_IDS
    ) == OFFICIAL_PRESET_IDS
    assert {preset.language for preset in OFFICIAL_PRESETS} == {"zh-CN"}


def test_provenance_tampering_and_name_guessing_fail_closed() -> None:
    provenance = OFFICIAL_PRESETS[0].provenance()
    assert validate_official_preset_provenance(provenance) is OFFICIAL_PRESETS[0]

    tampered = {**provenance, "catalog_id": "qwen-provider-voice-map/2"}
    with pytest.raises(ValueError, match="pinned catalog"):
        validate_official_preset_provenance(tampered)
    with pytest.raises(ValidationError):
        wire.OfficialPresetProvenance.model_validate(tampered)
    with pytest.raises(ValidationError, match="pinned Qwen catalog"):
        wire.CreatePresetVoiceVersionRequest(
            expected_profile_version=1,
            preset_id="qwen.Unknown",
        )


def test_official_default_fingerprints_are_stable_and_bind_every_identity() -> None:
    profile_id = UUID("11111111-1111-4111-8111-111111111111")
    version_id = UUID("22222222-2222-4222-8222-222222222222")

    decode = official_preset_decode_parameters_fingerprint("qwen.WarmFemale")
    fingerprint = official_preset_version_fingerprint(
        profile_id=profile_id,
        version_id=version_id,
        preset_id="qwen.WarmFemale",
    )

    assert decode == "e1e6bfac5c3a320e73423ad8a3461dad9533e47582992bb8d952f7ff8824e1c2"
    assert fingerprint == "bff17007fdbc7a9b1e1546ca66668511a209852a5e5c671f152fa2e6d303dbc8"
    assert fingerprint == official_preset_version_fingerprint(
        profile_id=str(profile_id),
        version_id=str(version_id),
        preset_id="qwen.WarmFemale",
    )
    assert len(
        {
            fingerprint,
            official_preset_version_fingerprint(
                profile_id=UUID("33333333-3333-4333-8333-333333333333"),
                version_id=version_id,
                preset_id="qwen.WarmFemale",
            ),
            official_preset_version_fingerprint(
                profile_id=profile_id,
                version_id=UUID("44444444-4444-4444-8444-444444444444"),
                preset_id="qwen.WarmFemale",
            ),
            official_preset_version_fingerprint(
                profile_id=profile_id,
                version_id=version_id,
                preset_id="qwen.ClearMale",
            ),
        }
    ) == 4
    assert decode != official_preset_decode_parameters_fingerprint("qwen.ClearMale")


def test_shared_official_evidence_validator_covers_v1_and_direct_v2() -> None:
    preset = require_official_preset("qwen.WarmFemale")
    profile_id = uuid4()
    owner_id = uuid4()
    workspace_id = uuid4()
    now = datetime.now(UTC)

    def evidence(*, direct: bool) -> tuple[SimpleNamespace, SimpleNamespace]:
        version_id = uuid4()
        version = SimpleNamespace(
            id=version_id,
            profile_id=profile_id,
            owner_id=owner_id,
            workspace_id=workspace_id,
            source_type="preset",
            state="locked" if direct else "draft",
            provider_id="qwen-tts",
            model_id=OFFICIAL_PRESET_REPOSITORY,
            model_revision=OFFICIAL_PRESET_REVISION,
            preset_key=preset.preset_id,
            reference_asset_id=None,
            language=preset.language,
            seed=1234,
            parameters_json={
                "schema_version": "qwen-tts-voice/1",
                "voice_kind": "preset",
                "provider_voice_ids": preset.provider_voice_ids,
                "official_preset": preset.provenance(),
            },
            activation_basis=(
                "explicit_official_preset_selection"
                if direct
                else "preview_confirmed"
            ),
            validation_basis="not_required" if direct else "pending",
            quality_state="pending",
            locked_actor=None,
            locked_at=None,
        )
        version.fingerprint = (
            official_preset_direct_version_fingerprint(
                profile_id=profile_id,
                version_id=version_id,
                preset_id=preset.preset_id,
            )
            if direct
            else official_preset_version_fingerprint(
                profile_id=profile_id,
                version_id=version_id,
                preset_id=preset.preset_id,
            )
        )
        rights = SimpleNamespace(
            owner_id=owner_id,
            workspace_id=workspace_id,
            source_kind="official_preset",
            source_identifier=f"qwen-tts-catalog://{preset.preset_id}",
            notice_version=OFFICIAL_PRESET_RIGHTS_POLICY_VERSION,
            purpose="private_novel_narration",
            commercial_use=False,
            redistribution=False,
            voice_cloning=False,
            subject_consent_reference=None,
            confirmed_actor="local-owner",
            confirmed_at=now,
            expires_at=None,
            risk_flags_json=[],
        )
        return version, rights

    legacy_version, legacy_rights = evidence(direct=False)
    direct_version, direct_rights = evidence(direct=True)
    assert validate_official_version_evidence(
        legacy_version,
        legacy_rights,
        expected_model_fingerprint=OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256,
    ) is preset
    assert validate_official_version_evidence(
        direct_version,
        direct_rights,
        expected_model_fingerprint=OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256,
    ) is preset
    assert direct_version.fingerprint != official_preset_version_fingerprint(
        profile_id=profile_id,
        version_id=direct_version.id,
        preset_id=preset.preset_id,
    )
    direct_rights.notice_version = "drifted-policy"
    with pytest.raises(ValueError, match="rights or runtime identity"):
        validate_official_version_evidence(
            direct_version,
            direct_rights,
            expected_model_fingerprint=OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256,
        )


def test_official_version_resource_requires_exact_provenance_and_rights_kind() -> None:
    preset = OFFICIAL_PRESETS[1]
    now = datetime.now(UTC)
    resource = wire.VoiceProfileVersionResource(
        version_id=uuid4(),
        profile_id=uuid4(),
        version_number=1,
        source_type="preset",
        state="draft",
        provider_id="qwen-tts",
        model_id=OFFICIAL_PRESET_REPOSITORY,
        model_revision=OFFICIAL_PRESET_REVISION,
        preset_key=preset.preset_id,
        language=preset.language,
        fingerprint="a" * 64,
        quality_state="pending",
        activation_basis="preview_confirmed",
        validation_basis="pending",
        rights=wire.VoiceRightsSummary(
            rights_record_id=uuid4(),
            state="active",
            notice_version=OFFICIAL_PRESET_RIGHTS_POLICY_VERSION,
            source_kind="official_preset",
            source_identifier_sha256="b" * 64,
            purpose="private_novel_narration",
            commercial_use=False,
            redistribution=False,
            voice_cloning=False,
            subject_consent_recorded=False,
            confirmed_at=now,
            risk_flags=[],
        ),
        official_preset=preset.provenance(),
        reference_asset_id=None,
        preview_asset=None,
        description_available=False,
        created_at=now,
    )
    assert resource.preset_key == "qwen.ClearMale"

    with pytest.raises(ValidationError, match="exact pinned provenance"):
        wire.VoiceProfileVersionResource.model_validate(
            {**resource.model_dump(mode="python"), "official_preset": None}
        )


def test_official_preset_capability_has_independent_exact_release_flag() -> None:
    held = t4_product_capabilities()
    released = t4_product_capabilities(official_presets_released=True)

    assert held.item(
        wire.CapabilityKey.PRESET_VOICE_SOURCE
    ).state is not wire.CapabilityState.ENABLED
    assert released.item(
        wire.CapabilityKey.PRESET_VOICE_SOURCE
    ).state is wire.CapabilityState.ENABLED
    assert released.item(
        wire.CapabilityKey.VOICE_PREVIEW
    ).state is wire.CapabilityState.UNAVAILABLE
    assert held.item(wire.CapabilityKey.REFERENCE_CLONE).state is wire.CapabilityState.HOLD
    with pytest.raises(TypeError, match="exact boolean"):
        t4_product_capabilities(official_presets_released=1)  # type: ignore[arg-type]
