from __future__ import annotations

from fastapi import HTTPException
import pytest

from backend.story_state import api
from backend.story_state.mappings import MappingServiceError, MappingServiceErrorCode

from .test_persistence_contract import uid


class TransactionProbe:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def test_router_exposes_profile_revision_and_timeline_mapping_contracts() -> None:
    routes = {
        (method, route.path)
        for route in api.router.routes
        for method in (route.methods or set())
    }
    profile = "/novels/{novel_id}/character-instances/{instance_id}/profile"
    profile_history = profile + "/history"
    profile_restore = profile + "/restore"
    mapping = (
        "/novels/{novel_id}/documents/{document_id}/revisions/{revision_id}"
        "/timeline-mapping"
    )
    assert ("GET", profile) in routes
    assert ("PUT", profile) in routes
    assert ("GET", profile_history) in routes
    assert ("POST", profile_restore) in routes
    assert ("GET", mapping) in routes
    assert ("PUT", mapping) in routes
    assert ("GET", mapping + "/history") in routes
    assert ("POST", "/novels/{novel_id}/timelines/merge") in routes
    assert ("GET", "/novels/{novel_id}/story-event-links") in routes
    assert ("POST", "/novels/{novel_id}/story-event-links") in routes


def test_profile_save_api_owns_commit_and_passes_short_operation_key(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_save(session, novel_id, instance_id, **kwargs):
        captured.update(kwargs)
        return {"revision": {"id": "new"}, "replayed": False}

    monkeypatch.setattr(api, "save_character_instance_profile", fake_save)
    session = TransactionProbe()
    request = api.CharacterInstanceProfileSaveRequest(
        expected_story_ledger_version=3,
        expected_instance_version=2,
        operation_key="profile.save.web-1",
        profile={"public_identity": "巡查员", "true_identity": "失踪王女"},
    )
    result = api.character_instance_profile_save(
        uid(1), uid(30), request, session  # type: ignore[arg-type]
    )
    assert result["revision"] == {"id": "new"}
    assert captured["operation_key"] == "profile.save.web-1"
    assert captured["profile"].true_identity == "失踪王女"
    assert session.commits == 1
    assert session.rollbacks == 0


def test_profile_save_api_accepts_explicit_v2_note_without_numeric_coercion(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_save(session, novel_id, instance_id, **kwargs):
        captured.update(kwargs)
        return {"revision": {"profile_schema_version": 2}, "replayed": False}

    monkeypatch.setattr(api, "save_character_instance_profile", fake_save)
    session = TransactionProbe()
    request = api.CharacterInstanceProfileSaveRequest(
        expected_story_ledger_version=3,
        expected_instance_version=2,
        operation_key="profile.save.web-v2",
        profile={
            "schema_version": "character-instance-profile/2",
            "public_identity": "巡查员",
            "age_at_story_start_note": "约十八岁，不作为计算值",
        },
    )

    api.character_instance_profile_save(
        uid(1), uid(30), request, session  # type: ignore[arg-type]
    )

    profile = captured["profile"]
    assert type(profile).__name__ == "CharacterInstanceProfileV2"
    assert profile.age_at_story_start_note == "约十八岁，不作为计算值"
    assert profile.birth_year is None
    assert session.commits == 1


def test_mapping_save_api_passes_explicit_ranges_and_commits(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_save(session, novel_id, document_id, revision_id, **kwargs):
        captured.update(kwargs)
        return {"mapping": {"id": "mapping"}, "replayed": False}

    monkeypatch.setattr(api, "save_revision_timeline_mapping", fake_save)
    session = TransactionProbe()
    request = api.RevisionTimelineMappingSaveRequest(
        expected_head_version=0,
        operation_key="mapping.web-1",
        segments=[
            {
                "timeline_id": uid(10),
                "source_start": 0,
                "source_end": 4,
                "story_sequence": 7,
            }
        ],
    )
    result = api.revision_timeline_mapping_save(
        uid(1), uid(50), uid(51), request, session  # type: ignore[arg-type]
    )
    assert result["mapping"] == {"id": "mapping"}
    assert captured["expected_head_version"] == 0
    assert captured["segments"][0].source_end == 4
    assert session.commits == 1
    assert session.rollbacks == 0


def test_timeline_required_error_is_structured_422() -> None:
    error = MappingServiceError(
        MappingServiceErrorCode.TIMELINE_REQUIRED,
        "multi-timeline documents require explicit character ranges",
        current={"active_timeline_count": 2},
    )
    with pytest.raises(HTTPException) as caught:
        api._raise(error)
    assert caught.value.status_code == 422
    assert caught.value.detail == {
        "code": "timeline_required",
        "message": "multi-timeline documents require explicit character ranges",
        "current": {"active_timeline_count": 2},
    }
