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


def test_product_catalog_publishes_all_eighteen_presets_without_codes_or_audio() -> None:
    catalog = list_official_presets()

    assert catalog.schema_version == "moss-tts-official-preset-catalog/2.0"
    assert len(catalog.items) == 18
    assert tuple(item.preset_id for item in catalog.items) == tuple(
        item.preset_id for item in OFFICIAL_PRESETS
    )
    assert "onnx.Trump" in {item.preset_id for item in catalog.items}
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
    assert {
        item.preset_id
        for item in catalog.items
        if item.validation_tier == "canonical_chapter_verified"
    } == CANONICAL_CHAPTER_VERIFIED_PRESET_IDS == {
        "onnx.Junhao",
        "onnx.Zhiming",
        "onnx.Xiaoyu",
    }
    assert all(
        item.language_scope == item.language
        and item.selectable_now
        and item.previewable_now
        and item.renderable_existing
        and item.usage_notice == "private_local_writing_tool"
        for item in catalog.items
    )


def test_product_catalog_outer_contract_rejects_missing_or_reordered_inventory() -> None:
    product = list_official_presets().model_dump(mode="python")

    missing = {**product, "items": product["items"][:-1]}
    with pytest.raises(ValidationError, match="all 18 pinned presets in order"):
        wire.OfficialPresetCatalogResponse.model_validate(missing)

    reordered_items = list(product["items"])
    reordered_items[0], reordered_items[1] = reordered_items[1], reordered_items[0]
    with pytest.raises(ValidationError, match="all 18 pinned presets in order"):
        wire.OfficialPresetCatalogResponse.model_validate(
            {**product, "items": reordered_items}
        )
    assert official_preset_validation_tier("onnx.Junhao") == (
        "canonical_chapter_verified"
    )
    assert official_preset_validation_tier("onnx.Trump") == (
        "pinned_catalog_unreviewed"
    )


def test_low_level_inventory_and_get_by_id_still_cover_all_18_presets() -> None:
    assert len(OFFICIAL_PRESETS) == 18
    trump = require_official_preset("onnx.Trump")
    assert trump.manifest_voice == "Trump"
    assert validate_official_preset_provenance(trump.provenance()) is trump

    assert OFFICIAL_PRESET_IDS == tuple(preset.preset_id for preset in OFFICIAL_PRESETS)
    assert tuple(
        require_official_preset(preset_id).preset_id for preset_id in OFFICIAL_PRESET_IDS
    ) == OFFICIAL_PRESET_IDS
    assert {preset.language for preset in OFFICIAL_PRESETS} == {"zh-CN", "en", "ja-JP"}


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


def test_shared_official_evidence_validator_covers_v1_and_direct_v2() -> None:
    preset = require_official_preset("onnx.Junhao")
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
            provider_id="local-sidecar",
            model_id="OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX",
            model_revision="f52645cb467506d8e18e746ddd59482685b74e58",
            preset_key=preset.preset_id,
            reference_asset_id=None,
            language=preset.language,
            seed=1234,
            parameters_json={
                "schema_version": "narration-official-preset-version/1.0",
                "official_preset": preset.provenance(),
                "sample_mode": "fixed",
                "max_new_frames": 375,
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
            source_identifier=(
                "hf://OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX@"
                "f52645cb467506d8e18e746ddd59482685b74e58/"
                f"browser_poc_manifest.json#{preset.preset_id}"
            ),
            notice_version="moss-tts-official-preset-local-use/1.0",
            purpose="private_novel_narration",
            commercial_use=False,
            redistribution=False,
            voice_cloning=False,
            subject_consent_reference=None,
            confirmed_actor="local-owner",
            confirmed_at=now,
            expires_at=None,
            risk_flags_json=["COMMERCIAL_DISTRIBUTION_NOT_EVALUATED"],
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
    with pytest.raises(ValueError, match="rights policy"):
        validate_official_version_evidence(
            direct_version,
            direct_rights,
            expected_model_fingerprint=OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256,
        )


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
        activation_basis="preview_confirmed",
        validation_basis="pending",
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
