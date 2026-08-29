"""Read-only HTTP boundary for the authoritative character workspace."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..database import get_session
from .contracts import CharacterWorkspaceError, CharacterWorkspaceErrorCode
from .service import service_for_session


router = APIRouter(tags=["character-workspace-v1"])


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
