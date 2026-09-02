"""HTTP boundary for the whole-novel Story Ledger read model."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..database import get_session
from .contracts import (
    LedgerBatchImpactPreview,
    LedgerFactDetail,
    LedgerFactImpactPreview,
    LedgerFactPage,
    LedgerSourceExcerpt,
    LedgerSummary,
)
from .query import LedgerQueryFilters
from .service import StoryLedgerError, StoryLedgerErrorCode, StoryLedgerService


router = APIRouter(tags=["story-ledger-v1"])

EffectiveState = Literal[
    "current",
    "historical",
    "superseded",
    "source_invalid",
    "batch_reverted",
]
Health = Literal["ok", "conflict", "ambiguous"]
EntityType = Literal[
    "character",
    "character_instance",
    "relationship",
    "storyline",
    "foreshadow",
]


def _raise(error: StoryLedgerError) -> None:
    if error.code in {
        StoryLedgerErrorCode.NOVEL_NOT_FOUND,
        StoryLedgerErrorCode.FACT_NOT_FOUND,
        StoryLedgerErrorCode.BATCH_NOT_FOUND,
        StoryLedgerErrorCode.TIMELINE_NOT_FOUND,
    }:
        http_status = status.HTTP_404_NOT_FOUND
    elif error.code in {
        StoryLedgerErrorCode.STALE_PAGE,
        StoryLedgerErrorCode.SNAPSHOT_CONFLICT,
    }:
        http_status = status.HTTP_409_CONFLICT
    elif error.code is StoryLedgerErrorCode.SNAPSHOT_TRANSACTION_INVALID:
        http_status = status.HTTP_500_INTERNAL_SERVER_ERROR
    else:
        http_status = status.HTTP_422_UNPROCESSABLE_CONTENT
    raise HTTPException(
        status_code=http_status,
        detail={
            "code": error.code.value,
            "message": str(error),
            "current": error.current,
        },
    ) from error


def _filters(
    *,
    fact_type: list[str] | None,
    effective_state: EffectiveState | None,
    health: Health | None,
    dimension: str | None,
    source_document_id: UUID | None,
    commit_batch_id: UUID | None,
    fact_timeline_id: UUID | None,
    entity_type: EntityType | None,
    entity_id: UUID | None,
    review_only: bool,
) -> LedgerQueryFilters:
    return LedgerQueryFilters(
        fact_types=tuple(fact_type or ()),
        effective_state=effective_state,
        health=health,
        dimension=dimension,
        source_document_id=source_document_id,
        commit_batch_id=commit_batch_id,
        fact_timeline_id=fact_timeline_id,
        entity_type=entity_type,
        entity_id=entity_id,
        review_only=review_only,
    )


@router.get(
    "/novels/{novel_id}/story-ledger/summary", response_model=LedgerSummary
)
def story_ledger_summary(
    novel_id: UUID,
    timeline_id: UUID | None = None,
    narrative_cutoff: Annotated[int | None, Query(ge=0)] = None,
    snapshot_token: Annotated[str | None, Query(max_length=2_048)] = None,
    fact_type: Annotated[list[str] | None, Query(max_length=40)] = None,
    effective_state: EffectiveState | None = None,
    health: Health | None = None,
    dimension: Annotated[str | None, Query(max_length=80)] = None,
    source_document_id: UUID | None = None,
    commit_batch_id: UUID | None = None,
    fact_timeline_id: UUID | None = None,
    entity_type: EntityType | None = None,
    entity_id: UUID | None = None,
    review_only: bool = False,
    session: Session = Depends(get_session),
) -> LedgerSummary:
    try:
        return StoryLedgerService(session).summary(
            novel_id,
            timeline_id=timeline_id,
            narrative_cutoff=narrative_cutoff,
            snapshot_token=snapshot_token,
            filters=_filters(
                fact_type=fact_type,
                effective_state=effective_state,
                health=health,
                dimension=dimension,
                source_document_id=source_document_id,
                commit_batch_id=commit_batch_id,
                fact_timeline_id=fact_timeline_id,
                entity_type=entity_type,
                entity_id=entity_id,
                review_only=review_only,
            ),
        )
    except StoryLedgerError as error:
        _raise(error)
        raise


@router.get(
    "/novels/{novel_id}/story-ledger/facts", response_model=LedgerFactPage
)
def story_ledger_facts(
    novel_id: UUID,
    timeline_id: UUID | None = None,
    narrative_cutoff: Annotated[int | None, Query(ge=0)] = None,
    snapshot_token: Annotated[str | None, Query(max_length=2_048)] = None,
    cursor: Annotated[str | None, Query(max_length=4_096)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    fact_type: Annotated[list[str] | None, Query(max_length=40)] = None,
    effective_state: EffectiveState | None = None,
    health: Health | None = None,
    dimension: Annotated[str | None, Query(max_length=80)] = None,
    source_document_id: UUID | None = None,
    commit_batch_id: UUID | None = None,
    fact_timeline_id: UUID | None = None,
    entity_type: EntityType | None = None,
    entity_id: UUID | None = None,
    review_only: bool = False,
    session: Session = Depends(get_session),
) -> LedgerFactPage:
    try:
        return StoryLedgerService(session).list_facts(
            novel_id,
            timeline_id=timeline_id,
            narrative_cutoff=narrative_cutoff,
            snapshot_token=snapshot_token,
            cursor=cursor,
            limit=limit,
            filters=_filters(
                fact_type=fact_type,
                effective_state=effective_state,
                health=health,
                dimension=dimension,
                source_document_id=source_document_id,
                commit_batch_id=commit_batch_id,
                fact_timeline_id=fact_timeline_id,
                entity_type=entity_type,
                entity_id=entity_id,
                review_only=review_only,
            ),
        )
    except StoryLedgerError as error:
        _raise(error)
        raise


@router.get(
    "/novels/{novel_id}/story-ledger/facts/{fact_id}",
    response_model=LedgerFactDetail,
)
def story_ledger_fact_detail(
    novel_id: UUID,
    fact_id: UUID,
    timeline_id: UUID | None = None,
    narrative_cutoff: Annotated[int | None, Query(ge=0)] = None,
    snapshot_token: Annotated[str | None, Query(max_length=2_048)] = None,
    session: Session = Depends(get_session),
) -> LedgerFactDetail:
    try:
        return StoryLedgerService(session).detail(
            novel_id,
            fact_id,
            timeline_id=timeline_id,
            narrative_cutoff=narrative_cutoff,
            snapshot_token=snapshot_token,
        )
    except StoryLedgerError as error:
        _raise(error)
        raise


@router.get(
    "/novels/{novel_id}/story-ledger/facts/{fact_id}/source",
    response_model=LedgerSourceExcerpt,
)
def story_ledger_fact_source(
    novel_id: UUID,
    fact_id: UUID,
    timeline_id: UUID | None = None,
    narrative_cutoff: Annotated[int | None, Query(ge=0)] = None,
    snapshot_token: Annotated[str | None, Query(max_length=2_048)] = None,
    session: Session = Depends(get_session),
) -> LedgerSourceExcerpt:
    try:
        return StoryLedgerService(session).source(
            novel_id,
            fact_id,
            timeline_id=timeline_id,
            narrative_cutoff=narrative_cutoff,
            snapshot_token=snapshot_token,
        )
    except StoryLedgerError as error:
        _raise(error)
        raise


@router.get(
    "/novels/{novel_id}/story-ledger/facts/{fact_id}/impact-preview",
    response_model=LedgerFactImpactPreview,
)
def story_ledger_fact_impact_preview(
    novel_id: UUID,
    fact_id: UUID,
    timeline_id: UUID | None = None,
    narrative_cutoff: Annotated[int | None, Query(ge=0)] = None,
    snapshot_token: Annotated[str | None, Query(max_length=2_048)] = None,
    session: Session = Depends(get_session),
) -> LedgerFactImpactPreview:
    try:
        return StoryLedgerService(session).fact_impact_preview(
            novel_id,
            fact_id,
            timeline_id=timeline_id,
            narrative_cutoff=narrative_cutoff,
            snapshot_token=snapshot_token,
        )
    except StoryLedgerError as error:
        _raise(error)
        raise


@router.get(
    "/novels/{novel_id}/story-ledger/batches/{batch_id}/impact-preview",
    response_model=LedgerBatchImpactPreview,
)
def story_ledger_batch_impact_preview(
    novel_id: UUID,
    batch_id: UUID,
    timeline_id: UUID | None = None,
    narrative_cutoff: Annotated[int | None, Query(ge=0)] = None,
    snapshot_token: Annotated[str | None, Query(max_length=2_048)] = None,
    session: Session = Depends(get_session),
) -> LedgerBatchImpactPreview:
    try:
        return StoryLedgerService(session).batch_impact_preview(
            novel_id,
            batch_id,
            timeline_id=timeline_id,
            narrative_cutoff=narrative_cutoff,
            snapshot_token=snapshot_token,
        )
    except StoryLedgerError as error:
        _raise(error)
        raise


__all__ = ["router"]
