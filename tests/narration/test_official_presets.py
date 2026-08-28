from __future__ import annotations

from datetime import UTC, datetime
import json
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from backend.narration import schemas as wire
from backend.narration.official_presets import (
    OFFICIAL_PRESET_MANIFEST_SHA256,
    OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256,
    OFFICIAL_PRESETS,
    PRODUCT_OFFICIAL_PRESET_IDS,
    PRODUCT_OFFICIAL_PRESETS,
    PRODUCT_PRESET_OUT_OF_SCOPE,
    official_preset_decode_parameters_fingerprint,
    official_preset_version_fingerprint,
    require_official_preset,
    require_product_official_preset,
    validate_official_preset_provenance,
)
from backend.narration.privacy import t4_product_capabilities
from backend.narration.voices import list_official_presets


def test_product_catalog_publishes_only_six_chinese_presets_without_codes_or_audio() -> None:
    catalog = list_official_presets()

    assert len(catalog.items) == 6
    assert tuple(item.preset_id for item in catalog.items) == (
        PRODUCT_OFFICIAL_PRESET_IDS
    )
    assert tuple(item.preset_id for item in PRODUCT_OFFICIAL_PRESETS) == (
        PRODUCT_OFFICIAL_PRESET_IDS
    )
    assert "onnx.Trump" not in {item.preset_id for item in catalog.items}
    serialized = json.dumps(catalog.model_dump(mode="json"), ensure_ascii=False)
    assert "prompt_audio_codes" not in serialized
    assert "audio_file" not in serialized
    assert OFFICIAL_PRESET_MANIFEST_SHA256 in serialized
    assert OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256 in serialized
    assert all(item.local_use_status == "available" for item in catalog.items)
    assert all(
        item.commercial_distribution_status == "not_evaluated"
        for item in catalog.items
    )


def test_product_catalog_outer_contract_rejects_missing_reordered_or_full_inventory() -> None:
    product = list_official_presets().model_dump(mode="python")

    missing = {**product, "items": product["items"][:-1]}
    with pytest.raises(ValidationError, match="six product presets in order"):
        wire.OfficialPresetCatalogResponse.model_validate(missing)

    reordered_items = list(product["items"])
    reordered_items[0], reordered_items[1] = reordered_items[1], reordered_items[0]
    with pytest.raises(ValidationError, match="six product presets in order"):
        wire.OfficialPresetCatalogResponse.model_validate(
            {**product, "items": reordered_items}
        )

    full_inventory = {
        **product,
        "items": [
            wire.OfficialPresetCatalogItem(
                preset_id=preset.preset_id,
                display_name=preset.display_name,
                group=preset.group,
                language=preset.language,
                local_use_status="available",
                commercial_distribution_status="not_evaluated",
                provenance=preset.provenance(),
            ).model_dump(mode="python")
            for preset in OFFICIAL_PRESETS
        ],
    }
    with pytest.raises(ValidationError, match="six product presets in order"):
        wire.OfficialPresetCatalogResponse.model_validate(full_inventory)


def test_low_level_inventory_and_get_by_id_still_cover_all_18_presets() -> None:
    assert len(OFFICIAL_PRESETS) == 18
    trump = require_official_preset("onnx.Trump")
    assert trump.manifest_voice == "Trump"
    assert validate_official_preset_provenance(trump.provenance()) is trump

    assert tuple(
        require_product_official_preset(preset_id).preset_id
        for preset_id in PRODUCT_OFFICIAL_PRESET_IDS
    ) == PRODUCT_OFFICIAL_PRESET_IDS
    assert all(
        require_product_official_preset(preset_id).language == "zh-CN"
        for preset_id in PRODUCT_OFFICIAL_PRESET_IDS
    )
    non_product_ids = {
        preset.preset_id for preset in OFFICIAL_PRESETS
    } - set(PRODUCT_OFFICIAL_PRESET_IDS)
    assert len(non_product_ids) == 12
    for preset_id in non_product_ids:
        with pytest.raises(ValueError, match=PRODUCT_PRESET_OUT_OF_SCOPE):
            require_product_official_preset(preset_id)


def test_provenance_tampering_and_name_guessing_fail_closed() -> None:
    provenance = OFFICIAL_PRESETS[0].provenance()
    assert validate_official_preset_provenance(provenance) is OFFICIAL_PRESETS[0]

    tampered = {**provenance, "prompt_frame_count": 99}
    with pytest.raises(ValueError, match="pinned manifest"):
        validate_official_preset_provenance(tampered)
    with pytest.raises(ValidationError, match="pinned ONNX manifest"):
        wire.OfficialPresetProvenance.model_validate(tampered)
    with pytest.raises(ValidationError, match="pinned ONNX manifest"):
        wire.CreatePresetVoiceVersionRequest(
            expected_profile_version=1,
            preset_id="onnx.lingyu",
        )


def test_official_default_fingerprints_are_stable_and_bind_every_identity() -> None:
    profile_id = UUID("11111111-1111-4111-8111-111111111111")
    version_id = UUID("22222222-2222-4222-8222-222222222222")

    decode = official_preset_decode_parameters_fingerprint("onnx.Zhiming")
    fingerprint = official_preset_version_fingerprint(
        profile_id=profile_id,
        version_id=version_id,
        preset_id="onnx.Zhiming",
    )

    assert decode == "1f1d169116eecdb4788109598305cb72458f73e171a497c6de03db223151b892"
    assert fingerprint == "31ab58e6818aeb9b654566d7205e1ba16d4628a3b69dc71a3d996b0433a24c5c"
    assert fingerprint == official_preset_version_fingerprint(
        profile_id=str(profile_id),
        version_id=str(version_id),
        preset_id="onnx.Zhiming",
    )
    assert len(
        {
            fingerprint,
            official_preset_version_fingerprint(
                profile_id=UUID("33333333-3333-4333-8333-333333333333"),
                version_id=version_id,
                preset_id="onnx.Zhiming",
            ),
            official_preset_version_fingerprint(
                profile_id=profile_id,
                version_id=UUID("44444444-4444-4444-8444-444444444444"),
                preset_id="onnx.Zhiming",
            ),
            official_preset_version_fingerprint(
                profile_id=profile_id,
                version_id=version_id,
                preset_id="onnx.Junhao",
            ),
        }
    ) == 4
    assert decode != official_preset_decode_parameters_fingerprint("onnx.Junhao")


def test_official_version_resource_requires_exact_provenance_and_rights_kind() -> None:
    preset = OFFICIAL_PRESETS[5]
    now = datetime.now(UTC)
    resource = wire.VoiceProfileVersionResource(
        version_id=uuid4(),
        profile_id=uuid4(),
        version_number=1,
        source_type="preset",
        state="draft",
        provider_id="local-sidecar",
        model_id="OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX",
        model_revision="f52645cb467506d8e18e746ddd59482685b74e58",
        preset_key=preset.preset_id,
        language=preset.language,
        fingerprint="a" * 64,
        quality_state="pending",
        rights=wire.VoiceRightsSummary(
            rights_record_id=uuid4(),
            state="active",
            notice_version="moss-tts-official-preset-local-use/1.0",
            source_kind="official_preset",
            source_identifier_sha256="b" * 64,
            purpose="private_novel_narration",
            commercial_use=False,
            redistribution=False,
            voice_cloning=False,
            subject_consent_recorded=False,
            confirmed_at=now,
            risk_flags=["COMMERCIAL_DISTRIBUTION_NOT_EVALUATED"],
        ),
        official_preset=preset.provenance(),
        reference_asset_id=None,
        preview_asset=None,
        description_available=False,
        created_at=now,
    )
    assert resource.preset_key == "onnx.Lingyu"

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
    ).state is wire.CapabilityState.ENABLED
    assert held.item(wire.CapabilityKey.REFERENCE_CLONE).state is wire.CapabilityState.HOLD
    with pytest.raises(TypeError, match="exact boolean"):
        t4_product_capabilities(official_presets_released=1)  # type: ignore[arg-type]
