from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from backend.narration.narration_api import (
    PRIVATE_VOICE_DELETION_RELEASED,
    PrivateVoiceDeletionRequestResource,
    _require_private_voice_deletion_release,
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
        and ("voice-deletion" in route.path or "discard-unreferenced" in route.path)
    }

    assert methods_by_path == {
        "/voice-profiles/{profile_id}/discard-unreferenced": {"POST"},
        "/voice-deletion-requests/{request_id}": {"GET"},
        "/voice-deletion-requests/{request_id}/confirm": {"POST"},
        "/voice-deletion-requests/{request_id}/cancel": {"POST"},
        "/voice-deletion-requests/{request_id}/retry": {"POST"},
    }
    create_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == "/voice-profiles/{profile_id}/deletion-requests"
    )
    assert create_route.methods == {"POST"}


def test_private_voice_deletion_routes_fail_closed_until_reconciler_is_released() -> None:
    assert PRIVATE_VOICE_DELETION_RELEASED is False

    with pytest.raises(HTTPException) as caught:
        _require_private_voice_deletion_release()

    assert caught.value.status_code == 503
    assert caught.value.detail == {
        "contract_version": "narration-production-api/1",
        "code": "NARRATION_PRODUCTION_BACKEND_NOT_INSTALLED",
        "message": "私人音色删除尚未完成后台恢复闭环，当前不对外开放。",
        "retryable": False,
        "field": None,
        "current_version": None,
    }


def test_private_voice_deletion_resource_keeps_backup_and_impact_truthful() -> None:
    now = datetime.now(timezone.utc)
    resource = PrivateVoiceDeletionRequestResource.model_validate(
        {
            "request_id": uuid4(),
            "profile_id": uuid4(),
            "novel_id": uuid4(),
            "command": "true_delete_private_voice",
            "state": "requested",
            "expected_profile_version": 3,
            "impact_digest": "a" * 64,
            "impact": {
                "historical_edition_count": 2,
                "historical_audio_consequence": "unavailable_private_voice_deleted",
                "external_backup_status": "unmanaged",
            },
            "execute_after": None,
            "impact_expires_at": now,
            "asset_count": 4,
            "total_bytes": 1024,
            "external_backup_status": "unmanaged",
            "confirmed_at": None,
            "cancelled_at": None,
            "completed_at": None,
            "failure_code": None,
        }
    )

    assert resource.contract_version == "private-voice-deletion/1"
    assert resource.external_backup_status == "unmanaged"
    assert resource.impact["historical_audio_consequence"] == (
        "unavailable_private_voice_deleted"
    )


def test_deleted_private_voice_playback_failure_is_stable_and_not_retryable() -> None:
    fault = _fault_from_error(
        InvalidNarrationState("unavailable_private_voice_deleted")
    )

    assert fault.code is PlaybackApiErrorCode.INVALID_STATE
    assert fault.retryable is False
    assert fault.message == "这个历史朗读使用的私人音色已删除，声音文件不再可用。"
