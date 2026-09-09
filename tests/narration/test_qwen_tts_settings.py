from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from uuid import uuid4

import pytest

from backend.narration import schemas as wire
from backend.narration.privacy import default_narration_settings_values
from backend.models import NovelNarrationSettings, TTSCloudProfile
from backend.narration.snapshots import CreateSettingsSnapshot, snapshot_payload
from backend.narration.tts_selection import (
    selection_fingerprint,
    selection_from_settings_snapshot,
    tokenizer_fingerprint,
)


def test_tts_provider_defaults_to_local_and_cloud_plus() -> None:
    values = default_narration_settings_values()

    assert values.tts_provider.provider_id == "local_qwen3_tts"
    assert values.tts_provider.aliyun_model_id == "qwen-audio-3.0-tts-plus"


def test_settings_written_before_provider_selection_get_safe_default() -> None:
    current = default_narration_settings_values().model_dump(mode="json")
    current.pop("tts_provider")

    restored = wire.NarrationSettingsValues.model_validate(current)

    assert restored.tts_provider == wire.TTSProviderSelection()


def test_cloud_flash_is_explicit_and_does_not_change_provider() -> None:
    selection = wire.TTSProviderSelection(
        aliyun_model_id="qwen-audio-3.0-tts-flash",
    )

    assert selection.provider_id == "local_qwen3_tts"
    assert selection.aliyun_model_id == "qwen-audio-3.0-tts-flash"


def test_only_active_provider_model_affects_execution_fingerprint() -> None:
    local_plus = wire.TTSProviderSelection()
    local_flash = wire.TTSProviderSelection(
        aliyun_model_id="qwen-audio-3.0-tts-flash"
    )
    cloud_plus = wire.TTSProviderSelection(
        provider_id="aliyun_qwen_audio_tts"
    )
    cloud_flash = wire.TTSProviderSelection(
        provider_id="aliyun_qwen_audio_tts",
        aliyun_model_id="qwen-audio-3.0-tts-flash",
    )

    assert selection_fingerprint(local_plus) == selection_fingerprint(local_flash)
    assert selection_fingerprint(local_plus) != selection_fingerprint(cloud_plus)
    assert selection_fingerprint(cloud_plus) != selection_fingerprint(cloud_flash)
    assert tokenizer_fingerprint(local_plus) != tokenizer_fingerprint(cloud_plus)


def test_snapshot_selection_defaults_old_settings_to_local() -> None:
    selection = selection_from_settings_snapshot(
        {"resolved_settings": {"settings": {}}}
    )

    assert selection == wire.TTSProviderSelection()


def test_cloud_snapshot_binding_is_complete_and_separates_channel_cache() -> None:
    common = {
        "provider_id": "aliyun_qwen_audio_tts",
        "cloud_profile_version": 4,
        "cloud_protocol": "qwen_audio_native_http/1",
        "cloud_actual_model_id": "member-qwen-quality",
        "cloud_base_url_fingerprint": "a" * 64,
        "cloud_verification_fingerprint": "c" * 64,
    }
    first = wire.TTSProviderSelection(cloud_profile_id=uuid4(), **common)
    second = wire.TTSProviderSelection(cloud_profile_id=uuid4(), **common)

    assert selection_fingerprint(first) != selection_fingerprint(second)

    with pytest.raises(ValueError, match="must be complete"):
        wire.TTSProviderSelection(
            provider_id="aliyun_qwen_audio_tts",
            cloud_profile_id=uuid4(),
        )


def test_snapshot_maps_logical_quality_slot_to_exact_active_channel() -> None:
    novel_id = uuid4()
    profile_id = uuid4()
    now = datetime.now(UTC)
    settings = NovelNarrationSettings(
        id=uuid4(),
        novel_id=novel_id,
        script_review_policy="blockers_only",
        analysis_mode="local_rules_only",
        settings_json={
            "tts_provider": {
                "provider_id": "aliyun_qwen_audio_tts",
                "aliyun_model_id": "qwen-audio-3.0-tts-plus",
            }
        },
        version=3,
    )
    profile = TTSCloudProfile(
        id=profile_id,
        owner_id=uuid4(),
        workspace_id=uuid4(),
        name="会员渠道",
        protocol="qwen_audio_native_http/1",
        base_url="https://member.example.com/qwen",
        credential_ref="tts-cloud/00000000-0000-0000-0000-000000000001",
        api_key_last4="1234",
        quality_model_id="member-qwen-quality",
        speed_model_id="member-qwen-speed",
        quality_test_state="passed",
        speed_test_state="passed",
        lifecycle_state="active",
        verification_fingerprint="d" * 64,
        version=7,
        created_at=now,
        updated_at=now,
    )

    payload = snapshot_payload(
        CreateSettingsSnapshot(novel_id=novel_id, settings_version=3),
        settings,
        [],
        cloud_profile=profile,
    )
    selection = selection_from_settings_snapshot(payload)

    assert selection.cloud_profile_id == profile_id
    assert selection.cloud_profile_version == 7
    assert selection.cloud_actual_model_id == "member-qwen-quality"
    assert selection.cloud_verification_fingerprint == "d" * 64
    assert selection.cloud_base_url_fingerprint == hashlib.sha256(
        profile.base_url.encode("utf-8")
    ).hexdigest()
