from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi.routing import APIRoute

from backend.narration.voice_features_api import (
    PrivateVoiceDeletionRequestResource,
    router,
)
from backend.narration.playback_api import (
    PlaybackApiErrorCode,
    _fault_from_error,
)
from backend.narration.services import InvalidNarrationState


def test_private_voice_deletion_routes_are_single_layer_commands() -> None:
    methods_by_path = {
        route.path: route.methods
        for route in router.routes
        if isinstance(route, APIRoute)
        and ("voice-deletion" in route.path or "private-voice-lifecycle" in route.path)
    }

    assert methods_by_path == {
        "/novels/{novel_id}/private-voice-lifecycle": {"GET"},
        "/novels/{novel_id}/voice-deletion-requests/{request_id}": {"GET"},
        "/novels/{novel_id}/voice-deletion-requests/{request_id}/confirm": {"POST"},
        "/novels/{novel_id}/voice-deletion-requests/{request_id}/cancel": {"POST"},
        "/novels/{novel_id}/voice-deletion-requests/{request_id}/retry": {"POST"},
    }
    create_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path
        == "/novels/{novel_id}/voice-profiles/{profile_id}/deletion-requests"
    )
    assert create_route.methods == {"POST"}


def test_private_voice_deletion_resource_keeps_backup_and_impact_truthful() -> None:
    now = datetime.now(timezone.utc)
    profile_id = uuid4()
    novel_id = uuid4()
    resource = PrivateVoiceDeletionRequestResource.model_validate(
        {
            "request_id": uuid4(),
            "profile_id": profile_id,
            "novel_id": novel_id,
            "command": "true_delete_private_voice",
            "state": "requested",
            "server_now": now,
            "expected_profile_version": 3,
            "impact_digest": "a" * 64,
            "impact": {
                "schema_version": "private-voice-deletion-impact/2",
                "profile_id": profile_id,
                "novel_id": novel_id,
                "profile_version": 3,
                "voice_version_ids": [uuid4()],
                "current_narrator_count": 0,
                "character_binding_count": 0,
                "anonymous_speaker_count": 0,
                "generic_slot_count": 0,
                "historical_edition_count": 2,
                "render_count": 0,
                "export_count": 0,
                "current_reference_count": 0,
                "historical_reference_count": 2,
                "reference_count": 2,
                "asset_count": 4,
                "total_bytes": 1024,
                "active_job_count": 0,
                "historical_audio_consequence": "unavailable_private_voice_deleted",
                "external_backup_status": "unmanaged",
                "impact_summary": "将使 2 项历史朗读证据不可播放，并删除 4 个资产。",
            },
            "execute_after": None,
            "impact_expires_at": now,
            "eligibility": "referenced",
            "reference_count": 2,
            "asset_count": 4,
            "total_bytes": 1024,
            "external_backup_status": "unmanaged",
            "confirmed_at": None,
            "cancelled_at": None,
            "completed_at": None,
            "superseded_at": None,
            "job_drain_started_at": None,
            "job_drain_deadline": None,
            "failure_code": None,
            "cancellable": True,
            "retryable": False,
            "terminal": False,
        }
    )

    assert resource.contract_version == "private-voice-deletion/2"
    assert resource.external_backup_status == "unmanaged"
    assert resource.impact.historical_audio_consequence == (
        "unavailable_private_voice_deleted"
    )


def test_deleted_private_voice_playback_failure_is_stable_and_not_retryable() -> None:
    fault = _fault_from_error(
        InvalidNarrationState("unavailable_private_voice_deleted")
    )

    assert fault.code is PlaybackApiErrorCode.INVALID_STATE
    assert fault.retryable is False
    assert fault.message == "这个历史朗读使用的私人音色已删除，声音文件不再可用。"
