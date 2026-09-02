"""HTTP boundary for the authoritative character workspace."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..creative_authority import (
    AuthorityConflictError,
    AuthorityIdempotencyConflict,
    AuthorityNotFoundError,
    AuthorityValidationError,
)
from ..database import get_session
from ..services import NotFoundError, ValidationError
from ..story_state.contracts import StoryStateError
from ..story_state.revisions import (
    CharacterInstanceProfileV1,
    CharacterInstanceProfileV2,
    RevisionServiceError,
    RevisionServiceErrorCode,
)
from .commands import save_character_workspace
from .contracts import CharacterWorkspaceError, CharacterWorkspaceErrorCode
from .service import service_for_session


router = APIRouter(tags=["character-workspace-v2"])


class _StrictWriteModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CharacterRootPatchV2(_StrictWriteModel):
    name: str = Field(min_length=1, max_length=240)
    role_type: str = Field(min_length=1, max_length=40)
    description: str = Field(default="", max_length=20_000)
    gender: str = Field(default="", max_length=240)
    core_theme: str = Field(default="", max_length=4_000)


class CharacterWorkspaceSaveRequestV2(_StrictWriteModel):
    schema_version: Literal["character-workspace-save/2"] = (
        "character-workspace-save/2"
    )
    operation_key: str = Field(
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    selected_timeline_id: UUID
    selected_instance_id: UUID
    expected_character_catalog_version: int = Field(ge=0)
    expected_story_ledger_version: int = Field(ge=1)
    expected_character_version: int = Field(ge=1)
    expected_instance_version: int = Field(ge=1)
    root_patch: CharacterRootPatchV2 | None = None
    profile: CharacterInstanceProfileV1 | CharacterInstanceProfileV2 | None = None


def _raise_workspace_error(error: CharacterWorkspaceError) -> None:
    status_code = (
        status.HTTP_404_NOT_FOUND
        if error.code
        in {
            CharacterWorkspaceErrorCode.CHARACTER_NOT_FOUND,
            CharacterWorkspaceErrorCode.TIMELINE_NOT_FOUND,
            CharacterWorkspaceErrorCode.CHARACTER_INSTANCE_NOT_FOUND,
        }
        else status.HTTP_422_UNPROCESSABLE_CONTENT
    )
    raise HTTPException(
        status_code=status_code,
        detail={
            "type": error.code.value,
            "message": str(error),
            "details": error.details,
        },
    ) from error


@router.get("/novels/{novel_id}/characters/{character_id}/workspace")
def character_workspace_get(
    novel_id: UUID,
    character_id: UUID,
    timeline_id: UUID | None = Query(default=None),
    character_instance_id: UUID | None = Query(default=None),
    narrative_cutoff: int | None = Query(default=None, ge=0),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    """Aggregate stable identity, timeline profile, and deterministic state."""

    try:
        workspace = service_for_session(session).get_workspace(
            novel_id,
            character_id,
            timeline_id=timeline_id,
            character_instance_id=character_instance_id,
            narrative_cutoff=narrative_cutoff,
        )
    except CharacterWorkspaceError as error:
        _raise_workspace_error(error)
        raise
    return workspace.model_dump(mode="json")


@router.get("/novels/{novel_id}/characters/{character_id}/facts")
def character_facts_get(
    novel_id: UUID,
    character_id: UUID,
    timeline_id: UUID | None = Query(default=None),
    character_instance_id: UUID | None = Query(default=None),
    narrative_cutoff: int | None = Query(default=None, ge=0),
    effective_state: Literal[
        "all",
        "current",
        "historical",
        "superseded",
        "source_invalid",
        "batch_reverted",
    ] = Query(default="all"),
    health: Literal["all", "ok", "conflict", "ambiguous"] = Query(default="all"),
    dimension: str | None = Query(default=None, min_length=1, max_length=80),
    source_document_id: UUID | None = Query(default=None),
    cursor: str | None = Query(default=None, min_length=1, max_length=1024),
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    """Page one character's facts with orthogonal state and health filters."""

    try:
        page = service_for_session(session).list_facts(
            novel_id,
            character_id,
            timeline_id=timeline_id,
            character_instance_id=character_instance_id,
            narrative_cutoff=narrative_cutoff,
            effective_state=effective_state,
            health=health,
            dimension=dimension,
            source_document_id=source_document_id,
            cursor=cursor,
            limit=limit,
        )
    except CharacterWorkspaceError as error:
        _raise_workspace_error(error)
        raise
    return page.model_dump(mode="json")


def _current_workspace(
    session: Session,
    novel_id: UUID,
    character_id: UUID,
    request: CharacterWorkspaceSaveRequestV2,
) -> dict[str, object] | None:
    try:
        return service_for_session(session).get_workspace(
            novel_id,
            character_id,
            timeline_id=request.selected_timeline_id,
            character_instance_id=request.selected_instance_id,
        ).model_dump(mode="json")
    except Exception:
        return None


def _raise_write_error(
    session: Session,
    novel_id: UUID,
    character_id: UUID,
    request: CharacterWorkspaceSaveRequestV2,
    error: Exception,
) -> None:
    current = _current_workspace(session, novel_id, character_id, request)
    field_errors: dict[str, str] = {}
    message = str(error)
    code = "character_workspace_invalid"
    http_status = status.HTTP_422_UNPROCESSABLE_CONTENT
    if isinstance(error, (AuthorityConflictError, RevisionServiceError)) and (
        isinstance(error, AuthorityConflictError)
        or error.code is RevisionServiceErrorCode.VERSION_CONFLICT
    ):
        code = "cas_conflict"
        http_status = status.HTTP_409_CONFLICT
    elif isinstance(error, (AuthorityIdempotencyConflict, RevisionServiceError)) and (
        isinstance(error, AuthorityIdempotencyConflict)
        or error.code is RevisionServiceErrorCode.IDEMPOTENCY_CONFLICT
    ):
        code = "idempotency_conflict"
        http_status = status.HTTP_409_CONFLICT
    elif isinstance(error, (AuthorityNotFoundError, NotFoundError)):
        code = "character_workspace_not_found"
        http_status = status.HTTP_404_NOT_FOUND
    elif isinstance(error, StoryStateError):
        code = error.code.value
        http_status = (
            status.HTTP_404_NOT_FOUND
            if code.endswith("_not_found")
            else status.HTTP_422_UNPROCESSABLE_CONTENT
        )
    elif isinstance(error, CharacterWorkspaceError):
        code = error.code.value
    elif isinstance(error, (AuthorityValidationError, ValidationError)):
        if "姓名" in message or "同名" in message:
            field_errors["character.name"] = message
        elif "角色类型" in message:
            field_errors["character.role_type"] = message
    elif isinstance(error, RevisionServiceError):
        code = error.code.value
    else:
        raise error
    raise HTTPException(
        status_code=http_status,
        detail={
            "code": code,
            "message": message,
            "field_errors": field_errors,
            "current_workspace": current,
        },
    ) from error


@router.put("/novels/{novel_id}/characters/{character_id}/workspace")
def character_workspace_put(
    novel_id: UUID,
    character_id: UUID,
    request: CharacterWorkspaceSaveRequestV2,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    """Atomically save root/profile changes and return a fresh V2 workspace."""

    try:
        save_character_workspace(
            session,
            novel_id,
            character_id,
            selected_timeline_id=request.selected_timeline_id,
            selected_instance_id=request.selected_instance_id,
            operation_key=request.operation_key,
            expected_character_catalog_version=(
                request.expected_character_catalog_version
            ),
            expected_story_ledger_version=request.expected_story_ledger_version,
            expected_character_version=request.expected_character_version,
            expected_instance_version=request.expected_instance_version,
            root_patch=(
                request.root_patch.model_dump(mode="python")
                if request.root_patch is not None
                else None
            ),
            profile=request.profile,
        )
        workspace = service_for_session(session).get_workspace(
            novel_id,
            character_id,
            timeline_id=request.selected_timeline_id,
            character_instance_id=request.selected_instance_id,
        )
        session.commit()
        return workspace.model_dump(mode="json")
    except Exception as error:
        session.rollback()
        _raise_write_error(
            session,
            novel_id,
            character_id,
            request,
            error,
        )
        raise


@router.get("/novels/{novel_id}/characters/{character_id}/archive-impact")
def character_archive_impact_get(
    novel_id: UUID,
    character_id: UUID,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    """Preview dependencies before an explicit archive operation; never writes."""

    try:
        impact = service_for_session(session).archive_impact(novel_id, character_id)
    except CharacterWorkspaceError as error:
        _raise_workspace_error(error)
        raise
    return impact.model_dump(mode="json")
