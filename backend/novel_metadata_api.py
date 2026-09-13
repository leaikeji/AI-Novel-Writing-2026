"""PawApp-only metadata endpoint; no model/tool dispatch."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from .creative_authority.errors import AuthorityConflictError, AuthorityIdempotencyConflict, AuthorityValidationError
from .database import get_session
from .novel_lifecycle_errors import NovelLifecycleError
from .novel_metadata_service import update_novel_metadata

router = APIRouter()


class NovelMetadataRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_version: int = Field(ge=1, strict=True)
    title: str = Field(min_length=1, max_length=240)
    author_name: str = Field(min_length=1, max_length=120)


@router.put("/novels/{novel_id}/metadata")
def edit_novel_metadata(
    novel_id: UUID, request: NovelMetadataRequest,
    session: Session = Depends(get_session),
):
    try:
        return update_novel_metadata(session, novel_id, **request.model_dump())
    except (ValueError, AuthorityValidationError) as error:
        session.rollback()
        raise HTTPException(422, detail={"message": str(error)}) from error
    except NovelLifecycleError as error:
        session.rollback()
        raise HTTPException(error.http_status, detail={"type": error.code, "message": str(error)}) from error
    except (AuthorityConflictError, AuthorityIdempotencyConflict) as error:
        session.rollback()
        raise HTTPException(409, detail={"message": "作品资料已更新，请载入最新资料后重试"}) from error
    except Exception:
        session.rollback()
        raise
