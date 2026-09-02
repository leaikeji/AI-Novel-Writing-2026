"""Public, fail-closed HTTP boundary for timeline and character instances."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from ..database import get_session

from .contracts import (
    CharacterContinuityKind,
    LifecycleState,
    StoryStateError,
    StoryStateErrorCode,
    StoryEventLinkType,
    TimelineLinkType,
)
from .persistence import (
    PersistenceErrorCode,
    StoryStatePersistenceError,
    create_character_instance,
    create_merge_timeline,
    create_story_event_link,
    create_timeline_link,
    ensure_default_story_state,
    fork_timeline,
    get_story_projection_payload,
    list_character_instance_payloads,
    list_story_event_link_payloads,
    list_timeline_link_payloads,
    list_timeline_payloads,
    patch_character_instance,
    patch_timeline,
)
from .mappings import (
    MappingServiceError,
    MappingServiceErrorCode,
    TimelineMappingSegmentInput,
    get_revision_timeline_mapping,
    list_revision_timeline_mapping_history,
    save_revision_timeline_mapping,
)
from .revisions import (
    CharacterInstanceProfileV1,
    CharacterInstanceProfileV2,
    RevisionServiceError,
    RevisionServiceErrorCode,
    get_character_instance_profile,
    list_character_instance_profile_history,
    restore_character_instance_profile,
    save_character_instance_profile,
)


router = APIRouter(tags=["story-state-v2"])


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class InitializeTimelineRequest(_Strict):
    expected_story_ledger_version: int = Field(ge=1)


class TimelinePatchRequest(_Strict):
    expected_story_ledger_version: int = Field(ge=1)
    expected_timeline_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=240)
    lifecycle_state: LifecycleState | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> "TimelinePatchRequest":
        changed = self.model_fields_set - {
            "expected_story_ledger_version", "expected_timeline_version"
        }
        if not changed or any(getattr(self, field) is None for field in changed):
            raise ValueError("timeline patch requires at least one non-null field")
        return self


class TimelineForkRequest(_Strict):
    expected_story_ledger_version: int = Field(ge=1)
    expected_source_timeline_version: int = Field(ge=1)
    timeline_key: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    name: str = Field(min_length=1, max_length=240)
    fork_story_sequence: int = Field(ge=0)
    fork_anchor: dict[str, Any] = Field(default_factory=dict)


class TimelineLinkRequest(_Strict):
    expected_story_ledger_version: int = Field(ge=1)
    source_timeline_id: UUID
    target_timeline_id: UUID
    link_type: TimelineLinkType
    expected_source_timeline_version: int = Field(ge=1)
    expected_target_timeline_version: int = Field(ge=1)
    source_story_sequence: int | None = Field(default=None, ge=0)
    target_story_sequence: int | None = Field(default=None, ge=0)
    details: dict[str, Any] = Field(default_factory=dict)


class TimelineMergeRequest(_Strict):
    expected_story_ledger_version: int = Field(ge=1)
    primary_timeline_id: UUID
    input_timeline_ids: list[UUID] = Field(min_length=2)
    expected_timeline_versions: dict[UUID, int]
    timeline_key: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    name: str = Field(min_length=1, max_length=240)
    merge_story_sequence: int = Field(ge=0)
    merge_anchor: dict[str, Any] = Field(default_factory=dict)


class StoryEventLinkRequest(_Strict):
    expected_story_ledger_version: int = Field(ge=1)
    source_fact_id: UUID
    target_fact_id: UUID
    link_type: StoryEventLinkType
    details: dict[str, Any] = Field(default_factory=dict)


class CharacterInstanceCreateRequest(_Strict):
    expected_story_ledger_version: int = Field(ge=1)
    expected_timeline_version: int = Field(ge=1)
    character_id: UUID
    timeline_id: UUID | None = None
    continuity_kind: CharacterContinuityKind = CharacterContinuityKind.NATIVE
    display_label: str = Field(default="", max_length=240)
    derived_from_instance_id: UUID | None = None


class CharacterInstancePatchRequest(_Strict):
    expected_story_ledger_version: int = Field(ge=1)
    expected_instance_version: int = Field(ge=1)
    display_label: str | None = Field(default=None, max_length=240)
    lifecycle_state: LifecycleState | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> "CharacterInstancePatchRequest":
        changed = self.model_fields_set - {
            "expected_story_ledger_version", "expected_instance_version"
        }
        if not changed or any(getattr(self, field) is None for field in changed):
            raise ValueError("character instance patch requires at least one non-null field")
        return self


class CharacterInstanceProfileSaveRequest(_Strict):
    expected_story_ledger_version: int = Field(ge=1)
    expected_instance_version: int = Field(ge=1)
    operation_key: str = Field(
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    source_kind: Literal["manual", "ai_adopt"] = "manual"
    profile: CharacterInstanceProfileV1 | CharacterInstanceProfileV2


class CharacterInstanceProfileRestoreRequest(_Strict):
    expected_story_ledger_version: int = Field(ge=1)
    expected_instance_version: int = Field(ge=1)
    target_revision_id: UUID
    operation_key: str = Field(
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )


class RevisionTimelineMappingSaveRequest(_Strict):
    expected_head_version: int = Field(ge=0)
    operation_key: str = Field(
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    segments: list[TimelineMappingSegmentInput] | None = None


def _raise(error: Exception) -> None:
    if isinstance(error, RevisionServiceError):
        http_status = (
            status.HTTP_404_NOT_FOUND
            if error.code is RevisionServiceErrorCode.REVISION_NOT_FOUND
            else status.HTTP_409_CONFLICT
            if error.code
            in {
                RevisionServiceErrorCode.VERSION_CONFLICT,
                RevisionServiceErrorCode.IDEMPOTENCY_CONFLICT,
            }
            else status.HTTP_422_UNPROCESSABLE_CONTENT
        )
        raise HTTPException(
            http_status,
            detail={
                "code": error.code.value,
                "message": str(error),
                "current": error.current,
            },
        ) from error
    if isinstance(error, MappingServiceError):
        http_status = (
            status.HTTP_404_NOT_FOUND
            if error.code
            in {
                MappingServiceErrorCode.NOVEL_NOT_FOUND,
                MappingServiceErrorCode.DOCUMENT_NOT_FOUND,
                MappingServiceErrorCode.REVISION_NOT_FOUND,
                MappingServiceErrorCode.MAPPING_NOT_FOUND,
            }
            else status.HTTP_409_CONFLICT
            if error.code
            in {
                MappingServiceErrorCode.VERSION_CONFLICT,
                MappingServiceErrorCode.IDEMPOTENCY_CONFLICT,
            }
            else status.HTTP_422_UNPROCESSABLE_CONTENT
        )
        raise HTTPException(
            http_status,
            detail={
                "code": error.code.value,
                "message": str(error),
                "current": error.current,
            },
        ) from error
    if isinstance(error, StoryStatePersistenceError):
        http_status = (
            status.HTTP_404_NOT_FOUND
            if error.code in {
                PersistenceErrorCode.NOVEL_NOT_FOUND,
                PersistenceErrorCode.CHARACTER_NOT_FOUND,
                PersistenceErrorCode.FACT_NOT_FOUND,
            }
            else status.HTTP_409_CONFLICT
            if error.code
            in {
                PersistenceErrorCode.VERSION_CONFLICT,
                PersistenceErrorCode.IDEMPOTENCY_CONFLICT,
            }
            else status.HTTP_422_UNPROCESSABLE_CONTENT
        )
        raise HTTPException(
            http_status,
            detail={
                "code": error.code.value,
                "message": str(error),
                "current": error.current,
            },
        ) from error
    if isinstance(error, StoryStateError):
        not_found = {
            StoryStateErrorCode.TIMELINE_NOT_FOUND,
            StoryStateErrorCode.CHARACTER_INSTANCE_NOT_FOUND,
        }
        required = {
            StoryStateErrorCode.TIMELINE_REQUIRED,
            StoryStateErrorCode.CHARACTER_INSTANCE_REQUIRED,
        }
        http_status = (
            status.HTTP_404_NOT_FOUND
            if error.code in not_found
            else status.HTTP_422_UNPROCESSABLE_CONTENT
            if error.code in required
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(
            http_status,
            detail={
                "code": error.code.value,
                "message": str(error),
                "details": error.details,
            },
        ) from error
    raise error


@router.get("/novels/{novel_id}/timelines")
def timelines_index(
    novel_id: UUID, session: Session = Depends(get_session)
) -> dict[str, object]:
    try:
        items = list_timeline_payloads(session, novel_id)
        return {"single_timeline_mode": len(items) <= 1, "items": items}
    except Exception as error:
        _raise(error); raise


@router.post("/novels/{novel_id}/timelines", status_code=status.HTTP_201_CREATED)
def timelines_initialize(
    novel_id: UUID,
    request: InitializeTimelineRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    """Create the one default primary timeline; branches use the fork route."""

    try:
        result = ensure_default_story_state(
            session,
            novel_id,
            expected_story_ledger_version=request.expected_story_ledger_version,
        )
        session.commit()
        return result
    except Exception as error:
        session.rollback(); _raise(error); raise


@router.patch("/novels/{novel_id}/timelines/{timeline_id}")
def timelines_patch(
    novel_id: UUID,
    timeline_id: UUID,
    request: TimelinePatchRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    fields = request.model_fields_set
    kwargs: dict[str, object] = {}
    if "name" in fields:
        kwargs["name"] = request.name
    if "lifecycle_state" in fields:
        kwargs["lifecycle_state"] = request.lifecycle_state
    try:
        result = patch_timeline(
            session,
            novel_id,
            timeline_id,
            expected_story_ledger_version=request.expected_story_ledger_version,
            expected_timeline_version=request.expected_timeline_version,
            **kwargs,
        )
        session.commit()
        return result
    except Exception as error:
        session.rollback(); _raise(error); raise


@router.post("/novels/{novel_id}/timelines/{timeline_id}/fork", status_code=status.HTTP_201_CREATED)
def timelines_fork(
    novel_id: UUID,
    timeline_id: UUID,
    request: TimelineForkRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        result = fork_timeline(
            session,
            novel_id,
            timeline_id,
            expected_story_ledger_version=request.expected_story_ledger_version,
            expected_source_timeline_version=request.expected_source_timeline_version,
            timeline_key=request.timeline_key,
            name=request.name,
            fork_story_sequence=request.fork_story_sequence,
            fork_anchor=request.fork_anchor,
        )
        session.commit()
        return result
    except Exception as error:
        session.rollback(); _raise(error); raise


@router.post("/novels/{novel_id}/timeline-links", status_code=status.HTTP_201_CREATED)
def timeline_links_create(
    novel_id: UUID,
    request: TimelineLinkRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        result = create_timeline_link(
            session,
            novel_id,
            source_timeline_id=request.source_timeline_id,
            target_timeline_id=request.target_timeline_id,
            link_type=request.link_type,
            expected_story_ledger_version=request.expected_story_ledger_version,
            expected_source_timeline_version=request.expected_source_timeline_version,
            expected_target_timeline_version=request.expected_target_timeline_version,
            source_story_sequence=request.source_story_sequence,
            target_story_sequence=request.target_story_sequence,
            details=request.details,
        )
        session.commit()
        return result
    except Exception as error:
        session.rollback(); _raise(error); raise


@router.post("/novels/{novel_id}/timelines/merge", status_code=status.HTTP_201_CREATED)
def timelines_merge(
    novel_id: UUID,
    request: TimelineMergeRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        result = create_merge_timeline(
            session,
            novel_id,
            primary_timeline_id=request.primary_timeline_id,
            input_timeline_ids=request.input_timeline_ids,
            expected_story_ledger_version=request.expected_story_ledger_version,
            expected_timeline_versions=request.expected_timeline_versions,
            timeline_key=request.timeline_key,
            name=request.name,
            merge_story_sequence=request.merge_story_sequence,
            merge_anchor=request.merge_anchor,
        )
        session.commit()
        return result
    except Exception as error:
        session.rollback(); _raise(error); raise


@router.get("/novels/{novel_id}/timeline-links")
def timeline_links_index(
    novel_id: UUID, session: Session = Depends(get_session)
) -> list[dict[str, object]]:
    try:
        return list_timeline_link_payloads(session, novel_id)
    except Exception as error:
        _raise(error); raise


@router.get("/novels/{novel_id}/story-event-links")
def story_event_links_index(
    novel_id: UUID, session: Session = Depends(get_session)
) -> list[dict[str, object]]:
    try:
        return list_story_event_link_payloads(session, novel_id)
    except Exception as error:
        _raise(error); raise


@router.post("/novels/{novel_id}/story-event-links", status_code=status.HTTP_201_CREATED)
def story_event_links_create(
    novel_id: UUID,
    request: StoryEventLinkRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        result = create_story_event_link(
            session,
            novel_id,
            source_fact_id=request.source_fact_id,
            target_fact_id=request.target_fact_id,
            link_type=request.link_type,
            expected_story_ledger_version=request.expected_story_ledger_version,
            details=request.details,
        )
        session.commit()
        return result
    except Exception as error:
        session.rollback(); _raise(error); raise


@router.get("/novels/{novel_id}/story-state")
def story_state_get(
    novel_id: UUID,
    timeline_id: UUID | None = Query(default=None),
    narrative_cutoff: int | None = Query(default=None, ge=0),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return get_story_projection_payload(
            session,
            novel_id,
            timeline_id=timeline_id,
            narrative_cutoff=narrative_cutoff,
        )
    except Exception as error:
        _raise(error); raise


@router.get("/novels/{novel_id}/character-instances")
def character_instances_index(
    novel_id: UUID,
    timeline_id: UUID | None = Query(default=None),
    character_id: UUID | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[dict[str, object]]:
    try:
        return list_character_instance_payloads(
            session, novel_id, timeline_id=timeline_id, character_id=character_id
        )
    except Exception as error:
        _raise(error); raise


@router.post("/novels/{novel_id}/character-instances", status_code=status.HTTP_201_CREATED)
def character_instances_create(
    novel_id: UUID,
    request: CharacterInstanceCreateRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        result = create_character_instance(
            session,
            novel_id,
            character_id=request.character_id,
            timeline_id=request.timeline_id,
            continuity_kind=request.continuity_kind,
            display_label=request.display_label,
            expected_story_ledger_version=request.expected_story_ledger_version,
            expected_timeline_version=request.expected_timeline_version,
            derived_from_instance_id=request.derived_from_instance_id,
        )
        session.commit()
        return result
    except Exception as error:
        session.rollback(); _raise(error); raise


@router.patch("/novels/{novel_id}/character-instances/{instance_id}")
def character_instances_patch(
    novel_id: UUID,
    instance_id: UUID,
    request: CharacterInstancePatchRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    fields = request.model_fields_set
    kwargs: dict[str, object] = {}
    if "display_label" in fields:
        kwargs["display_label"] = request.display_label
    if "lifecycle_state" in fields:
        kwargs["lifecycle_state"] = request.lifecycle_state
    try:
        result = patch_character_instance(
            session,
            novel_id,
            instance_id,
            expected_story_ledger_version=request.expected_story_ledger_version,
            expected_instance_version=request.expected_instance_version,
            **kwargs,
        )
        session.commit()
        return result
    except Exception as error:
        session.rollback(); _raise(error); raise


@router.get("/novels/{novel_id}/character-instances/{instance_id}/profile")
def character_instance_profile_get(
    novel_id: UUID,
    instance_id: UUID,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return get_character_instance_profile(session, novel_id, instance_id)
    except Exception as error:
        _raise(error); raise


@router.get("/novels/{novel_id}/character-instances/{instance_id}/profile/history")
def character_instance_profile_history(
    novel_id: UUID,
    instance_id: UUID,
    session: Session = Depends(get_session),
) -> list[dict[str, object]]:
    try:
        return list_character_instance_profile_history(session, novel_id, instance_id)
    except Exception as error:
        _raise(error); raise


@router.put("/novels/{novel_id}/character-instances/{instance_id}/profile")
def character_instance_profile_save(
    novel_id: UUID,
    instance_id: UUID,
    request: CharacterInstanceProfileSaveRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        result = save_character_instance_profile(
            session,
            novel_id,
            instance_id,
            expected_story_ledger_version=request.expected_story_ledger_version,
            expected_instance_version=request.expected_instance_version,
            operation_key=request.operation_key,
            source_kind=request.source_kind,
            profile=request.profile,
        )
        session.commit()
        return result
    except Exception as error:
        session.rollback(); _raise(error); raise


@router.post("/novels/{novel_id}/character-instances/{instance_id}/profile/restore")
def character_instance_profile_restore(
    novel_id: UUID,
    instance_id: UUID,
    request: CharacterInstanceProfileRestoreRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        result = restore_character_instance_profile(
            session,
            novel_id,
            instance_id,
            request.target_revision_id,
            expected_story_ledger_version=request.expected_story_ledger_version,
            expected_instance_version=request.expected_instance_version,
            operation_key=request.operation_key,
        )
        session.commit()
        return result
    except Exception as error:
        session.rollback(); _raise(error); raise


@router.get(
    "/novels/{novel_id}/documents/{document_id}/revisions/{revision_id}/timeline-mapping"
)
def revision_timeline_mapping_get(
    novel_id: UUID,
    document_id: UUID,
    revision_id: UUID,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return get_revision_timeline_mapping(
            session, novel_id, document_id, revision_id
        )
    except Exception as error:
        _raise(error); raise


@router.get(
    "/novels/{novel_id}/documents/{document_id}/revisions/{revision_id}/timeline-mapping/history"
)
def revision_timeline_mapping_history(
    novel_id: UUID,
    document_id: UUID,
    revision_id: UUID,
    session: Session = Depends(get_session),
) -> list[dict[str, object]]:
    try:
        return list_revision_timeline_mapping_history(
            session, novel_id, document_id, revision_id
        )
    except Exception as error:
        _raise(error); raise


@router.put(
    "/novels/{novel_id}/documents/{document_id}/revisions/{revision_id}/timeline-mapping"
)
def revision_timeline_mapping_save(
    novel_id: UUID,
    document_id: UUID,
    revision_id: UUID,
    request: RevisionTimelineMappingSaveRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        result = save_revision_timeline_mapping(
            session,
            novel_id,
            document_id,
            revision_id,
            expected_head_version=request.expected_head_version,
            operation_key=request.operation_key,
            segments=request.segments,
        )
        session.commit()
        return result
    except Exception as error:
        session.rollback(); _raise(error); raise
