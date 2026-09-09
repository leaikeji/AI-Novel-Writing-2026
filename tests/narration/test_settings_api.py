from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import importlib
import json
from pathlib import Path
import sys
from types import ModuleType
from typing import Any, Iterator, cast
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
import pytest
from sqlalchemy.orm import Session

from backend.narration import schemas as wire
from backend.narration import settings_api
from backend.narration.official_presets import OFFICIAL_PRESETS
from backend.narration.voices import list_official_presets


NOVEL_ID = UUID("20000000-0000-4000-8000-000000000001")
PROFILE_ID = UUID("20000000-0000-4000-8000-000000000003")
VOICE_VERSION_ID = UUID("20000000-0000-4000-8000-000000000004")
PREVIEW_ID = UUID("20000000-0000-4000-8000-000000000005")
CHARACTER_ID = UUID("20000000-0000-4000-8000-000000000006")
SCOPE_ID = UUID("20000000-0000-4000-8000-000000000007")
CONSENT_ID = UUID("20000000-0000-4000-8000-000000000008")


def _settings_values() -> dict[str, object]:
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
            "sentence_gap_ms": 200,
            "paragraph_gap_ms": 500,
            "section_gap_ms": 900,
        },
        "casting": {
            "anonymous_reuse_scope": "scene",
            "same_scene_voice_deduplication": True,
            "unknown_speaker_action": "block",
        },
        "playback": {"playback_rate": 1.0, "volume": 0.8},
    }


@dataclass(frozen=True, slots=True)
class ApiCase:
    name: str
    operation: settings_api.NarrationSettingsOperation
    method: str
    path: str
    request_kwargs: dict[str, Any] = field(default_factory=dict)
    command_fields: dict[str, object] = field(default_factory=dict)
    payload_type: type[BaseModel] | None = None


def _api_cases() -> list[ApiCase]:
    idempotency = {"Idempotency-Key": "tts-api-case-0001"}
    fingerprint = "a" * 64
    cases = [
        ApiCase(
            "overview-get",
            settings_api.NarrationSettingsOperation.GET_OVERVIEW,
            "GET",
            f"/novels/{NOVEL_ID}/narration-overview",
            command_fields={"novel_id": NOVEL_ID},
        ),
        ApiCase(
            "settings-get",
            settings_api.NarrationSettingsOperation.GET_SETTINGS,
            "GET",
            f"/novels/{NOVEL_ID}/narration-settings",
            command_fields={"novel_id": NOVEL_ID},
        ),
        ApiCase(
            "settings-put",
            settings_api.NarrationSettingsOperation.PUT_SETTINGS,
            "PUT",
            f"/novels/{NOVEL_ID}/narration-settings",
            {"json": {"expected_version": 0, "values": _settings_values()}},
            {"novel_id": NOVEL_ID},
            wire.UpdateNarrationSettingsRequest,
        ),
        ApiCase(
            "playback-preferences-patch",
            settings_api.NarrationSettingsOperation.PUT_PLAYBACK_PREFERENCES,
            "PATCH",
            f"/novels/{NOVEL_ID}/narration-settings/playback-preferences",
            {
                "json": {
                    "expected_version": 0,
                    "playback": {"playback_rate": 1.25, "volume": 0.7},
                }
            },
            {"novel_id": NOVEL_ID},
            wire.UpdateNarrationPlaybackPreferencesRequest,
        ),
        ApiCase(
            "scope-list",
            settings_api.NarrationSettingsOperation.LIST_SCOPE_OVERRIDES,
            "GET",
            f"/novels/{NOVEL_ID}/narration-scope-overrides",
            command_fields={"novel_id": NOVEL_ID},
        ),
        ApiCase(
            "scope-put",
            settings_api.NarrationSettingsOperation.PUT_SCOPE_OVERRIDE,
            "PUT",
            f"/novels/{NOVEL_ID}/narration-scope-overrides/chapter/{SCOPE_ID}",
            {
                "json": {
                    "expected_version": 0,
                    "enabled": True,
                    "overrides": {
                        "narrator": None,
                        "language": "zh-CN",
                        "text_rules": None,
                        "timing": None,
                    },
                }
            },
            {
                "novel_id": NOVEL_ID,
                "scope_kind": wire.NarrationScopeKind.CHAPTER,
                "scope_id": SCOPE_ID,
            },
            wire.PutNarrationScopeOverrideRequest,
        ),
        ApiCase(
            "cloud-consent-create",
            settings_api.NarrationSettingsOperation.CREATE_CLOUD_CONSENT,
            "POST",
            f"/novels/{NOVEL_ID}/narration-cloud-consents",
            {
                "headers": idempotency,
                "json": {
                    "notice_version": "narration-cloud/1",
                    "data_scope": "uncertain_segments_with_minimal_context",
                    "provider_id": None,
                    "model_id": None,
                    "confirmed": True,
                },
            },
            {"novel_id": NOVEL_ID, "idempotency_key": "tts-api-case-0001"},
            wire.CreateNarrationCloudConsentRequest,
        ),
        ApiCase(
            "cloud-consent-revoke",
            settings_api.NarrationSettingsOperation.REVOKE_CLOUD_CONSENT,
            "DELETE",
            f"/novels/{NOVEL_ID}/narration-cloud-consents/current",
            {"json": {"consent_id": str(CONSENT_ID), "expected_version": 3}},
            {"novel_id": NOVEL_ID, "expected_version": 3},
            wire.RevokeNarrationCloudConsentRequest,
        ),
        ApiCase(
            "cloud-tts-consent-get",
            settings_api.NarrationSettingsOperation.GET_CLOUD_TTS_CONSENT,
            "GET",
            f"/novels/{NOVEL_ID}/narration-cloud-tts-consents/current",
            command_fields={"novel_id": NOVEL_ID},
        ),
        ApiCase(
            "cloud-tts-consent-create",
            settings_api.NarrationSettingsOperation.CREATE_CLOUD_TTS_CONSENT,
            "POST",
            f"/novels/{NOVEL_ID}/narration-cloud-tts-consents",
            {
                "headers": idempotency,
                "json": {
                    "notice_version": "narration-cloud-tts-consent/1",
                    "data_scope": "narration_text_and_selected_voice_reference",
                    "provider_id": "aliyun_qwen_audio_tts",
                    "model_id": "qwen-audio-3.0-tts-plus",
                    "confirmed": True,
                },
            },
            {"novel_id": NOVEL_ID, "idempotency_key": "tts-api-case-0001"},
            wire.CreateNarrationCloudTTSConsentRequest,
        ),
        ApiCase(
            "cloud-tts-consent-revoke",
            settings_api.NarrationSettingsOperation.REVOKE_CLOUD_TTS_CONSENT,
            "DELETE",
            f"/novels/{NOVEL_ID}/narration-cloud-tts-consents/current",
            {"json": {"consent_id": str(CONSENT_ID), "expected_version": 1}},
            {"novel_id": NOVEL_ID, "expected_version": 1},
            wire.RevokeNarrationCloudTTSConsentRequest,
        ),
        ApiCase(
            "official-presets-list",
            settings_api.NarrationSettingsOperation.LIST_OFFICIAL_PRESETS,
            "GET",
            "/voice-presets",
        ),
        ApiCase(
            "official-voice-select",
            settings_api.NarrationSettingsOperation.SELECT_OFFICIAL_VOICE,
            "POST",
            f"/novels/{NOVEL_ID}/official-voice-selections",
            {
                "headers": idempotency,
                "json": {
                    "preset_id": "qwen.WarmFemale",
                    "target_kind": "narrator",
                    "character_id": None,
                    "expected_settings_version": 0,
                    "expected_binding_version": None,
                },
            },
            {
                "novel_id": NOVEL_ID,
                "character_id": None,
                "idempotency_key": "tts-api-case-0001",
            },
            wire.OfficialVoiceSelectionRequest,
        ),
        ApiCase(
            "official-voice-preview",
            settings_api.NarrationSettingsOperation.CREATE_OFFICIAL_VOICE_PREVIEW,
            "POST",
            f"/novels/{NOVEL_ID}/official-voice-previews",
            {
                "headers": idempotency,
                "json": {"preset_id": "qwen.WarmFemale"},
            },
            {
                "novel_id": NOVEL_ID,
                "idempotency_key": "tts-api-case-0001",
            },
            wire.OfficialVoicePreviewRequest,
        ),
        ApiCase(
            "voice-profile-list",
            settings_api.NarrationSettingsOperation.LIST_VOICE_PROFILES,
            "GET",
            f"/voice-profiles?novel_id={NOVEL_ID}&include_library=false",
            command_fields={"novel_id": NOVEL_ID, "include_library": False},
        ),
        ApiCase(
            "voice-profile-create",
            settings_api.NarrationSettingsOperation.CREATE_VOICE_PROFILE,
            "POST",
            "/voice-profiles",
            {
                "headers": idempotency,
                "json": {"novel_id": str(NOVEL_ID), "name": "旁白 A"},
            },
            {"novel_id": NOVEL_ID, "idempotency_key": "tts-api-case-0001"},
            wire.CreateVoiceProfileRequest,
        ),
        ApiCase(
            "voice-profile-get",
            settings_api.NarrationSettingsOperation.GET_VOICE_PROFILE,
            "GET",
            f"/voice-profiles/{PROFILE_ID}",
            command_fields={"profile_id": PROFILE_ID},
        ),
        ApiCase(
            "voice-profile-put",
            settings_api.NarrationSettingsOperation.PUT_VOICE_PROFILE,
            "PUT",
            f"/voice-profiles/{PROFILE_ID}",
            {"json": {"expected_version": 1, "name": "旁白 B"}},
            {"profile_id": PROFILE_ID},
            wire.UpdateVoiceProfileRequest,
        ),
        ApiCase(
            "voice-profile-archive",
            settings_api.NarrationSettingsOperation.ARCHIVE_VOICE_PROFILE,
            "DELETE",
            f"/voice-profiles/{PROFILE_ID}?expected_version=2",
            command_fields={"profile_id": PROFILE_ID, "expected_version": 2},
        ),
        ApiCase(
            "preset-version-create",
            settings_api.NarrationSettingsOperation.CREATE_PRESET_VOICE_VERSION,
            "POST",
            f"/voice-profiles/{PROFILE_ID}/versions/preset",
            {
                "headers": idempotency,
                "json": {
                    "expected_profile_version": 1,
                    "preset_id": "qwen.ClearMale",
                },
            },
            {"profile_id": PROFILE_ID, "idempotency_key": "tts-api-case-0001"},
            wire.CreatePresetVoiceVersionRequest,
        ),
        ApiCase(
            "uploaded-version-create",
            settings_api.NarrationSettingsOperation.CREATE_UPLOADED_VOICE_VERSION,
            "POST",
            f"/voice-profiles/{PROFILE_ID}/versions/uploaded",
            {
                "headers": idempotency,
                "files": {
                    "metadata": (
                        None,
                        json.dumps(
                            {
                                "expected_profile_version": 1,
                                "language": "zh-CN",
                                "original_filename": "reference.wav",
                                "reference_sha256": "b" * 64,
                                "rights": {
                                    "notice_version": "voice-rights/1",
                                    "source_identifier": "owned reference recording",
                                    "purpose": "private_novel_narration",
                                    "commercial_use": False,
                                    "redistribution": False,
                                    "voice_cloning": True,
                                    "subject_consent_reference": "owner-self-recording",
                                    "confirmed": True,
                                },
                            }
                        ),
                        "application/json",
                    ),
                    "reference_audio": (
                        "reference.wav",
                        b"RIFF-authorized-test-bytes",
                        "audio/wav",
                    ),
                },
            },
            {"profile_id": PROFILE_ID, "idempotency_key": "tts-api-case-0001"},
        ),
        ApiCase(
            "voice-preview-create",
            settings_api.NarrationSettingsOperation.CREATE_VOICE_PREVIEW,
            "POST",
            f"/voice-profiles/{PROFILE_ID}/previews",
            {
                "headers": idempotency,
                "json": {
                    "version_id": str(VOICE_VERSION_ID),
                    "preview_text": "仅用于测试的短句",
                },
            },
            {"profile_id": PROFILE_ID, "idempotency_key": "tts-api-case-0001"},
            wire.CreateVoicePreviewRequest,
        ),
        ApiCase(
            "voice-preview-get",
            settings_api.NarrationSettingsOperation.GET_VOICE_PREVIEW,
            "GET",
            f"/voice-previews/{PREVIEW_ID}",
            command_fields={"preview_id": PREVIEW_ID},
        ),
        ApiCase(
            "voice-profile-lock",
            settings_api.NarrationSettingsOperation.LOCK_VOICE_PROFILE,
            "POST",
            f"/voice-profiles/{PROFILE_ID}/lock",
            {
                "json": {
                    "expected_profile_version": 2,
                    "version_id": str(VOICE_VERSION_ID),
                    "quality_confirmed": True,
                }
            },
            {"profile_id": PROFILE_ID},
            wire.LockVoiceProfileRequest,
        ),
        ApiCase(
            "character-binding-list",
            settings_api.NarrationSettingsOperation.LIST_CHARACTER_VOICE_BINDINGS,
            "GET",
            f"/novels/{NOVEL_ID}/character-voice-bindings",
            command_fields={"novel_id": NOVEL_ID},
        ),
        ApiCase(
            "character-binding-get",
            settings_api.NarrationSettingsOperation.GET_CHARACTER_VOICE_BINDING,
            "GET",
            f"/novels/{NOVEL_ID}/characters/{CHARACTER_ID}/voice-binding",
            command_fields={"novel_id": NOVEL_ID, "character_id": CHARACTER_ID},
        ),
        ApiCase(
            "character-binding-put",
            settings_api.NarrationSettingsOperation.PUT_CHARACTER_VOICE_BINDING,
            "PUT",
            f"/novels/{NOVEL_ID}/characters/{CHARACTER_ID}/voice-binding",
            {
                "json": {
                    "expected_version": 0,
                    "binding_policy": "unset",
                    "profile_id": None,
                    "version_id": None,
                    "language": "zh-CN",
                }
            },
            {"novel_id": NOVEL_ID, "character_id": CHARACTER_ID},
            wire.PutCharacterVoiceBindingRequest,
        ),
        ApiCase(
            "pronunciation-get",
            settings_api.NarrationSettingsOperation.GET_PRONUNCIATION_PROFILE,
            "GET",
            f"/novels/{NOVEL_ID}/pronunciation-profile",
            command_fields={"novel_id": NOVEL_ID},
        ),
        ApiCase(
            "pronunciation-put",
            settings_api.NarrationSettingsOperation.PUT_PRONUNCIATION_PROFILE,
            "PUT",
            f"/novels/{NOVEL_ID}/pronunciation-profile",
            {"json": {"expected_version": 0, "entries": []}},
            {"novel_id": NOVEL_ID},
            wire.PutPronunciationProfileRequest,
        ),
        ApiCase(
            "cache-status-get",
            settings_api.NarrationSettingsOperation.GET_CACHE_STATUS,
            "GET",
            f"/novels/{NOVEL_ID}/narration-cache",
            command_fields={"novel_id": NOVEL_ID},
        ),
        ApiCase(
            "cache-cleanup-preview",
            settings_api.NarrationSettingsOperation.PREVIEW_CACHE_CLEANUP,
            "POST",
            f"/novels/{NOVEL_ID}/narration-cache/cleanup-preview",
            {"json": {"snapshot_fingerprint": fingerprint}},
            {"novel_id": NOVEL_ID},
            wire.PreviewNarrationCacheCleanupRequest,
        ),
        ApiCase(
            "cache-cleanup-execute",
            settings_api.NarrationSettingsOperation.EXECUTE_CACHE_CLEANUP,
            "POST",
            f"/novels/{NOVEL_ID}/narration-cache/cleanup",
            {
                "json": {
                    "snapshot_fingerprint": fingerprint,
                    "cleanup_token": "cleanup-token-" + "x" * 32,
                    "confirmed": True,
                }
            },
            {"novel_id": NOVEL_ID},
            wire.ExecuteNarrationCacheCleanupRequest,
        ),
    ]
    assert len(cases) == 32
    assert {case.operation for case in cases} == set(
        settings_api.NarrationSettingsOperation
    )
    return cases


class RecordingNoGoBackend:
    def __init__(self, fault: settings_api.NarrationApiFault | None = None) -> None:
        self.commands: list[settings_api.NarrationSettingsApiCommand] = []
        self.fault = fault or settings_api.NarrationApiFault(
            wire.NarrationErrorCode.CAPABILITY_DISABLED,
            "当前朗读能力尚未通过产品门禁。",
            capability=wire.CapabilityKey.READING_SETTINGS,
        )

    def dispatch(self, command: settings_api.NarrationSettingsApiCommand) -> object:
        self.commands.append(command)
        raise self.fault


def _client(backend: settings_api.NarrationSettingsApiBackend) -> TestClient:
    app = FastAPI()
    app.include_router(settings_api.router)
    app.dependency_overrides[settings_api.get_narration_settings_backend] = (
        lambda: backend
    )
    return TestClient(app)


def test_voice_presets_http_surface_exposes_all_pinned_presets() -> None:
    class ProductPresetBackend:
        def dispatch(
            self,
            command: settings_api.NarrationSettingsApiCommand,
        ) -> object:
            assert (
                command.operation
                is settings_api.NarrationSettingsOperation.LIST_OFFICIAL_PRESETS
            )
            return list_official_presets()

    with _client(ProductPresetBackend()) as client:
        response = client.get("/voice-presets")

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert tuple(item["preset_id"] for item in response.json()["items"]) == (
        tuple(item.preset_id for item in OFFICIAL_PRESETS)
    )


def test_voice_presets_http_surface_uses_shared_response_contract() -> None:
    class IncompletePresetBackend:
        def dispatch(
            self,
            command: settings_api.NarrationSettingsApiCommand,
        ) -> object:
            assert (
                command.operation
                is settings_api.NarrationSettingsOperation.LIST_OFFICIAL_PRESETS
            )
            catalog = list_official_presets().model_dump(mode="python")
            return {**catalog, "items": catalog["items"][:-1]}

    with _client(IncompletePresetBackend()) as client:
        response = client.get("/voice-presets")

    assert response.status_code == 500
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["detail"]["code"] == "RESPONSE_CONTRACT_VIOLATION"
    source = Path(settings_api.__file__).read_text(encoding="utf-8")
    assert "_run_product_preset_catalog" not in source


def test_voice_source_unavailable_reason_is_stable_on_http_surface() -> None:
    backend = RecordingNoGoBackend(
        settings_api.NarrationApiFault(
            wire.NarrationErrorCode.VOICE_SOURCE_UNAVAILABLE,
            "VOICE_PRODUCT_UNAVAILABLE",
            field="preset_id",
            capability=wire.CapabilityKey.PRESET_VOICE_SOURCE,
        )
    )
    with _client(backend) as client:
        response = client.post(
            f"/voice-profiles/{PROFILE_ID}/versions/preset",
            headers={"Idempotency-Key": "preset-scope-0001"},
            json={
                "expected_profile_version": 1,
                "preset_id": "qwen.WarmFemale",
            },
        )

    assert response.status_code == 409
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["detail"] == {
        "contract_version": "narration-settings-api/1",
        "code": "VOICE_SOURCE_UNAVAILABLE",
        "message": "VOICE_PRODUCT_UNAVAILABLE",
        "retryable": False,
        "field": "preset_id",
        "current_version": None,
        "capability": "preset_voice_source",
    }


@pytest.mark.parametrize("case", _api_cases(), ids=lambda case: case.name)
def test_all_29_http_operations_dispatch_one_frozen_typed_command(
    case: ApiCase,
) -> None:
    backend = RecordingNoGoBackend()
    with _client(backend) as client:
        response = client.request(case.method, case.path, **case.request_kwargs)

    assert response.status_code == 409, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["detail"]["code"] == "CAPABILITY_DISABLED"
    assert response.json()["detail"]["capability"] == "reading_settings"
    assert len(backend.commands) == 1
    command = backend.commands[0]
    assert command.operation is case.operation
    for name, expected in case.command_fields.items():
        assert getattr(command, name) == expected
    if case.payload_type is None:
        assert command.payload is None
    else:
        assert type(command.payload) is case.payload_type
        request_json = case.request_kwargs.get("json")
        assert command.payload is not None
        payload_json = command.payload.model_dump(mode="json")
        if isinstance(request_json, dict):
            for protected_field in (
                "expected_version",
                "expected_profile_version",
                "snapshot_fingerprint",
                "cleanup_token",
                "confirmed",
            ):
                if protected_field in request_json:
                    assert payload_json[protected_field] == request_json[protected_field]
    if case.operation is settings_api.NarrationSettingsOperation.CREATE_UPLOADED_VOICE_VERSION:
        assert command.payload is None
        assert command.multipart_content_type is not None
        assert "multipart/form-data" in command.multipart_content_type
        assert command.multipart_body is not None
        assert b"RIFF-authorized-test-bytes" in command.multipart_body


@pytest.mark.parametrize(
    "code",
    list(wire.NarrationErrorCode),
    ids=lambda code: code.value,
)
def test_every_frozen_error_code_has_a_real_no_store_http_response(
    code: wire.NarrationErrorCode,
) -> None:
    fault = settings_api.NarrationApiFault(
        code,
        "稳定且不包含私人输入的错误说明。",
        retryable=code in {
            wire.NarrationErrorCode.MODEL_UNAVAILABLE,
            wire.NarrationErrorCode.STORAGE_UNAVAILABLE,
        },
        current_version=7 if code is wire.NarrationErrorCode.VERSION_CONFLICT else None,
        capability=(
            wire.CapabilityKey.READING_SETTINGS
            if code is wire.NarrationErrorCode.CAPABILITY_DISABLED
            else None
        ),
    )
    backend = RecordingNoGoBackend(fault)
    with _client(backend) as client:
        response = client.get(f"/novels/{NOVEL_ID}/narration-settings")

    assert response.status_code == settings_api.NARRATION_ERROR_HTTP_STATUS[code]
    assert response.headers["cache-control"] == "no-store"
    detail = response.json()["detail"]
    assert detail["contract_version"] == wire.NARRATION_SETTINGS_API_VERSION
    assert detail["code"] == code.value
    assert detail["current_version"] == (
        7 if code is wire.NarrationErrorCode.VERSION_CONFLICT else None
    )


def test_factory_lifecycle_uses_one_session_then_uninstall_returns_to_zero_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings_api.uninstall_narration_settings_backend_factory()
    session_sentinel = object()
    session_opens: list[object] = []
    factory_sessions: list[object] = []

    def fake_get_session() -> Iterator[Session]:
        session_opens.append(session_sentinel)
        yield cast(Session, session_sentinel)

    def factory(session: Session, _request: object) -> RecordingNoGoBackend:
        factory_sessions.append(session)
        return RecordingNoGoBackend()

    monkeypatch.setattr(settings_api, "get_session", fake_get_session)
    app = FastAPI()
    app.include_router(settings_api.router)
    try:
        settings_api.install_narration_settings_backend_factory(factory)
        with TestClient(app) as client:
            installed = client.get(f"/novels/{NOVEL_ID}/narration-settings")
        settings_api.uninstall_narration_settings_backend_factory(factory)
        with TestClient(app) as client:
            uninstalled = client.get(f"/novels/{NOVEL_ID}/narration-settings")
    finally:
        settings_api.uninstall_narration_settings_backend_factory()

    assert installed.status_code == 409
    assert factory_sessions == [session_sentinel]
    assert session_opens == [session_sentinel]
    assert uninstalled.status_code == 503
    assert uninstalled.json()["detail"]["code"] == "SETTINGS_BACKEND_NOT_INSTALLED"
    assert session_opens == [session_sentinel], "uninstalled facade must not touch DB"


def test_upload_rejects_missing_boundary_oversize_and_missing_idempotency_before_dispatch() -> None:
    backend = RecordingNoGoBackend()
    maximum = wire.REFERENCE_UPLOAD_MAX_BYTES + 64 * 1024
    with _client(backend) as client:
        missing_boundary = client.post(
            f"/voice-profiles/{PROFILE_ID}/versions/uploaded",
            headers={
                "Idempotency-Key": "upload-guard-0001",
                "Content-Type": "multipart/form-data",
            },
            content=b"private-reference-must-not-be-echoed",
        )
        oversized = client.post(
            f"/voice-profiles/{PROFILE_ID}/versions/uploaded",
            headers={
                "Idempotency-Key": "upload-guard-0002",
                "Content-Type": "multipart/form-data; boundary=safe-boundary",
                "Content-Length": str(maximum + 1),
            },
            content=b"x",
        )
        missing_key = client.post(
            f"/voice-profiles/{PROFILE_ID}/versions/uploaded",
            files={
                "metadata": (None, "{}", "application/json"),
                "reference_audio": ("private.wav", b"RIFF", "audio/wav"),
            },
        )

    assert missing_boundary.status_code == 415
    assert missing_boundary.json()["detail"]["code"] == "UNSUPPORTED_MEDIA_TYPE"
    assert "private-reference-must-not-be-echoed" not in missing_boundary.text
    assert oversized.status_code == 413
    assert oversized.json()["detail"]["code"] == "PAYLOAD_TOO_LARGE"
    assert missing_key.status_code == 422
    assert missing_key.json()["detail"]["code"] == "REQUEST_VALIDATION_FAILED"
    assert backend.commands == []


def test_surface_has_no_removed_tts_mode_routes() -> None:
    operations = {
        (method, route.path)
        for route in settings_api.router.routes
        for method in (route.methods or set())
    }
    paths = {path for _, path in operations}

    assert len(operations) == 32
    assert all("synthesis" not in path for path in paths)
    assert all("player" not in path for path in paths)
    assert all("voice-generator" not in path for path in paths)
    assert all("automatic-speaker" not in path for path in paths)
    assert all("generic-voice" not in path for path in paths)
    assert all("casting-rules" not in path for path in paths)


def test_narration_gate_router_and_factory_are_installed_by_pawapp_lifecycle() -> None:
    """Keep the shared router/factory lifecycle behind one explicit release flag."""

    source = Path("backend/app.py").read_text(encoding="utf-8")
    required_integration_tokens = (
        "router.include_router(narration_settings_router)",
        "install_narration_settings_backend_factory(",
        "uninstall_narration_settings_backend_factory(",
        "profile_creation_receipts=SqlAlchemyVoiceActionReceiptPort(session)",
        "voice_product=None",
        "runtime_status_provider=narration_production_runtime_status",
        "def _t4_product_release_runtime_ready()",
        "install_narration_t4_http_access_policy(",
        "uninstall_narration_t4_http_access_policy(",
        "production.get(\"worker_running\") is True",
    )
    missing = [token for token in required_integration_tokens if token not in source]
    assert not missing, (
        "T2_GATE_INTEGRATION_MISSING: backend.app has not included the frozen narration "
        f"router and symmetric factory lifecycle; missing={missing}"
    )
    assert "authorization=FIXED_LOCAL_OWNER_NARRATION_AUTHORIZATION" in source
    assert "t4_product_capabilities(" in source
    assert "reference_clone_released=False" in source
    assert "official_presets_released=True" in source
    assert "OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256" not in source
    assert 'os.environ.get(REFERENCE_CLONE_ENABLE_ENV, "false")' in source
    assert "else t2_settings_capabilities()" in source
    assert 'os.environ.get(PRODUCT_ENABLE_ENV, "false") != "true"' in source
    assert 'os.environ.get(VALIDATION_ENABLE_ENV, "false") != "false"' in source
    compose = Path("compose.yaml").read_text(encoding="utf-8")
    assert '"127.0.0.1:18088:8088"' in compose

def test_qwen_gate_factory_uses_one_production_runtime_and_keeps_legacy_voice_modes_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.narration.privacy import (
        FIXED_LOCAL_OWNER_NARRATION_AUTHORIZATION,
    )

    class FakePawApp:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def hook(self, *_args: object, **_kwargs: object):
            return lambda function: function

        def on_uninstall(self, function):
            return function

        def include_router(self, _router: object) -> None:
            pass

    async def fake_get_ctx() -> None:
        return None

    qwenpaw_module = ModuleType("qwenpaw")
    qwenpaw_module.__path__ = []  # type: ignore[attr-defined]
    pawapp_module = ModuleType("qwenpaw.pawapp")
    pawapp_module.PawApp = FakePawApp  # type: ignore[attr-defined]
    pawapp_module.get_ctx = fake_get_ctx  # type: ignore[attr-defined]
    runtime_module = ModuleType("qwenpaw.runtime")
    runtime_module.__path__ = []  # type: ignore[attr-defined]
    hooks_module = ModuleType("qwenpaw.runtime.hooks")
    hooks_module.HookBase = type("HookBase", (), {})  # type: ignore[attr-defined]
    hooks_module.HookResult = type("HookResult", (), {})  # type: ignore[attr-defined]
    phases_module = ModuleType("qwenpaw.runtime.phases")
    phases_module.Phase = type("Phase", (), {"PRE_EXECUTE": "pre_execute"})  # type: ignore[attr-defined]
    qwenpaw_module.pawapp = pawapp_module  # type: ignore[attr-defined]
    qwenpaw_module.runtime = runtime_module  # type: ignore[attr-defined]
    runtime_module.hooks = hooks_module  # type: ignore[attr-defined]
    runtime_module.phases = phases_module  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "qwenpaw", qwenpaw_module)
    monkeypatch.setitem(sys.modules, "qwenpaw.pawapp", pawapp_module)
    monkeypatch.setitem(sys.modules, "qwenpaw.runtime", runtime_module)
    monkeypatch.setitem(sys.modules, "qwenpaw.runtime.hooks", hooks_module)
    monkeypatch.setitem(sys.modules, "qwenpaw.runtime.phases", phases_module)
    monkeypatch.delenv("AI_NOVEL_TTS_PRODUCT_ENABLED", raising=False)
    monkeypatch.delenv("AI_NOVEL_TTS_VALIDATION_ENABLED", raising=False)
    monkeypatch.delenv("AI_NOVEL_TTS_REFERENCE_CLONE_ENABLED", raising=False)
    sys.modules.pop("backend.app", None)
    backend_app = importlib.import_module("backend.app")

    captured: dict[str, object] = {}
    expected_backend = object()

    def fake_build(session: Session, **kwargs: object) -> object:
        captured["session"] = session
        captured.update(kwargs)
        return expected_backend

    monkeypatch.setattr(backend_app, "build_narration_settings_backend", fake_build)
    session = cast(Session, object())

    actual = backend_app._build_fixed_local_owner_narration_backend(session)
    assert actual is expected_backend
    assert captured["authorization"] is FIXED_LOCAL_OWNER_NARRATION_AUTHORIZATION
    assert captured["runtime_status_provider"] is (
        backend_app.narration_production_runtime_status
    )
    assert captured["voice_product"] is None
    assert captured["official_voice_selection"] is None
    baseline = backend_app.t2_settings_capabilities()
    assert captured["capabilities"].item(
        wire.CapabilityKey.NARRATION_SYNTHESIS
    ) == baseline.item(wire.CapabilityKey.NARRATION_SYNTHESIS)

    ready = {
        "product_requested": True,
        "lifecycle_status": "ready",
        "playback_installed": True,
        "digest_keyring_loaded": True,
        "production_backend_installed": True,
        "worker_running": True,
        "provider_selection_fingerprint_sha256": "d" * 64,
        "reason_code": None,
    }
    monkeypatch.setattr(
        backend_app,
        "narration_production_runtime_status",
        lambda: dict(ready),
    )
    monkeypatch.setenv("AI_NOVEL_TTS_PRODUCT_ENABLED", "true")
    captured.clear()
    assert backend_app._build_fixed_local_owner_narration_backend(session) is expected_backend
    released = captured["capabilities"]
    assert released.item(
        wire.CapabilityKey.NARRATION_SYNTHESIS
    ).state is wire.CapabilityState.ENABLED
    for key in (
        wire.CapabilityKey.VOICE_PREVIEW,
        wire.CapabilityKey.REFERENCE_CLONE,
        wire.CapabilityKey.VOICE_DESIGN,
    ):
        assert released.item(key).actionable is False
    assert released.item(wire.CapabilityKey.PRESET_VOICE_SOURCE).actionable is True
    assert captured["voice_product"] is None
    assert isinstance(
        captured["official_voice_selection"],
        backend_app.OfficialVoiceSelectionService,
    )

    monkeypatch.setenv("AI_NOVEL_TTS_REFERENCE_CLONE_ENABLED", "true")
    captured.clear()
    assert backend_app._build_fixed_local_owner_narration_backend(session) is expected_backend
    assert captured["capabilities"].item(
        wire.CapabilityKey.NARRATION_SYNTHESIS
    ).actionable is False
