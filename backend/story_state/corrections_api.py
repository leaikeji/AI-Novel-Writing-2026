"""HTTP boundary for auditable fact correction and batch revert."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..database import get_session
from .corrections import (
    StoryCorrectionError,
    StoryCorrectionErrorCode,
    correct_story_fact,
    intelligence_batch_revert_impact,
    revert_intelligence_batch,
)


router = APIRouter(tags=["story-fact-corrections-v1"])


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class StoryFactReplacement(_Strict):
    predicate: str | None = Field(default=None, min_length=1, max_length=240)
    object_text: str | None = Field(default=None, min_length=1, max_length=10_000)
    details: dict[str, Any] | None = None
    dimension: str | None = Field(default=None, min_length=1, max_length=80)
    event_kind: str | None = Field(default=None, min_length=1, max_length=80)
    story_sequence: int | None = Field(default=None, ge=0)
    story_time: dict[str, Any] | None = None
    visibility: dict[str, Any] | None = None


class StoryFactCorrectionRequest(_Strict):
    schema_version: str = Field(pattern=r"^story-fact-correction/1$")
    operation_key: str = Field(
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    expected_story_ledger_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1_000)
    replacement: StoryFactReplacement


class IntelligenceBatchRevertRequest(_Strict):
    operation_key: str = Field(
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    expected_story_ledger_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=500)


def _raise(error: StoryCorrectionError) -> None:
    http_status = (
        status.HTTP_404_NOT_FOUND
        if error.code
        in {
            StoryCorrectionErrorCode.NOT_FOUND,
            StoryCorrectionErrorCode.BATCH_NOT_FOUND,
        }
        else status.HTTP_409_CONFLICT
        if error.code
        in {
            StoryCorrectionErrorCode.VERSION_CONFLICT,
            StoryCorrectionErrorCode.IDEMPOTENCY_CONFLICT,
        }
        else status.HTTP_422_UNPROCESSABLE_CONTENT
    )
    raise HTTPException(
        status_code=http_status,
        detail={
            "code": error.code.value,
            "message": str(error),
            "current": error.current,
        },
    ) from error


@router.post("/novels/{novel_id}/story-facts/{fact_id}/corrections")
def story_fact_correction_create(
    novel_id: UUID,
    fact_id: UUID,
    request: StoryFactCorrectionRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        result = correct_story_fact(
            session,
            novel_id,
            fact_id,
            expected_story_ledger_version=request.expected_story_ledger_version,
            operation_key=request.operation_key,
            reason=request.reason,
            replacement=request.replacement.model_dump(exclude_none=True),
        )
        session.commit()
        return result
    except StoryCorrectionError as error:
        session.rollback()
        _raise(error)
        raise
    except Exception:
        session.rollback()
        raise


@router.get(
    "/novels/{novel_id}/intelligence-commit-batches/{batch_id}/revert-impact"
)
def intelligence_batch_revert_impact_get(
    novel_id: UUID,
    batch_id: UUID,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return intelligence_batch_revert_impact(session, novel_id, batch_id)
    except StoryCorrectionError as error:
        _raise(error)
        raise


@router.post("/novels/{novel_id}/intelligence-commit-batches/{batch_id}/revert")
def intelligence_batch_revert_create(
    novel_id: UUID,
    batch_id: UUID,
    request: IntelligenceBatchRevertRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        result = revert_intelligence_batch(
            session,
            novel_id,
            batch_id,
            expected_story_ledger_version=request.expected_story_ledger_version,
            operation_key=request.operation_key,
            reason=request.reason,
        )
        session.commit()
        return result
    except StoryCorrectionError as error:
        session.rollback()
        _raise(error)
        raise
    except Exception:
        session.rollback()
        raise
