"""AI小说世界2026 PawApp HTTP API."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from qwenpaw.pawapp import PawApp
from sqlalchemy.orm import Session

from .contracts import APP_ID, APP_VERSION
from .database import database_status, get_session
from .schemas import (
    CheckpointRequest,
    CreateDocumentRequest,
    CreateNovelRequest,
    CreateVolumeRequest,
    RestoreRevisionRequest,
    SaveDraftRequest,
)
from .services import (
    DraftConflictError,
    NotFoundError,
    ValidationError,
    create_checkpoint,
    create_document,
    create_novel,
    create_volume,
    get_document,
    get_novel,
    get_novel_context,
    get_revision,
    list_novels,
    restore_revision,
    save_draft,
    search_novel,
)


pawapp = PawApp(name="AI小说世界2026", app_id=APP_ID)
router = APIRouter()


def _raise_domain(error: Exception) -> None:
    if isinstance(error, DraftConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"type": "draft_conflict", "current": error.current},
        ) from error
    if isinstance(error, NotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    if isinstance(error, ValidationError):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    raise error


@router.get("/health")
def health() -> dict[str, object]:
    database = database_status()
    return {
        "app_id": APP_ID,
        "version": APP_VERSION,
        "status": "ready" if database["connected"] else "degraded",
        "database": database,
        "ai_write_enabled": False,
        "vector_retrieval_enabled": False,
    }


@router.get("/novels")
def novels_index(session: Session = Depends(get_session)) -> list[dict[str, object]]:
    return list_novels(session)


@router.post("/novels", status_code=status.HTTP_201_CREATED)
def novels_create(
    request: CreateNovelRequest, session: Session = Depends(get_session)
) -> dict[str, object]:
    try:
        return create_novel(session, request.title, request.description)
    except Exception as error:
        _raise_domain(error)
        raise


@router.get("/novels/{novel_id}")
def novels_get(novel_id: UUID, session: Session = Depends(get_session)) -> dict[str, object]:
    try:
        return get_novel(session, novel_id)
    except Exception as error:
        _raise_domain(error)
        raise


@router.get("/novels/{novel_id}/tree")
def novels_tree(novel_id: UUID, session: Session = Depends(get_session)) -> list[dict[str, object]]:
    try:
        return get_novel(session, novel_id)["tree"]
    except Exception as error:
        _raise_domain(error)
        raise


@router.post("/novels/{novel_id}/volumes", status_code=status.HTTP_201_CREATED)
def volumes_create(
    novel_id: UUID,
    request: CreateVolumeRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return create_volume(session, novel_id, request.title)
    except Exception as error:
        _raise_domain(error)
        raise


@router.post("/novels/{novel_id}/documents", status_code=status.HTTP_201_CREATED)
def documents_create(
    novel_id: UUID,
    request: CreateDocumentRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return create_document(
            session,
            novel_id,
            request.title,
            kind=request.kind,
            volume_id=request.volume_id,
        )
    except Exception as error:
        _raise_domain(error)
        raise


@router.get("/documents/{document_id}")
def documents_get(
    document_id: UUID, session: Session = Depends(get_session)
) -> dict[str, object]:
    try:
        return get_document(session, document_id)
    except Exception as error:
        _raise_domain(error)
        raise


@router.patch("/documents/{document_id}/draft")
def documents_save_draft(
    document_id: UUID,
    request: SaveDraftRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return save_draft(
            session,
            document_id,
            expected_draft_version=request.expected_draft_version,
            content_markdown=request.content_markdown,
            client_hash=request.content_hash,
        )
    except Exception as error:
        session.rollback()
        _raise_domain(error)
        raise


@router.post("/documents/{document_id}/checkpoints", status_code=status.HTTP_201_CREATED)
def documents_checkpoint(
    document_id: UUID,
    request: CheckpointRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return create_checkpoint(
            session, document_id, expected_draft_version=request.expected_draft_version
        )
    except Exception as error:
        session.rollback()
        _raise_domain(error)
        raise


@router.get("/documents/{document_id}/revisions/{revision_id}")
def revisions_get(
    document_id: UUID,
    revision_id: UUID,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return get_revision(session, document_id, revision_id)
    except Exception as error:
        _raise_domain(error)
        raise


@router.post(
    "/documents/{document_id}/revisions/{revision_id}/restore",
    status_code=status.HTTP_201_CREATED,
)
def revisions_restore(
    document_id: UUID,
    revision_id: UUID,
    request: RestoreRevisionRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return restore_revision(
            session,
            document_id,
            revision_id,
            expected_draft_version=request.expected_draft_version,
        )
    except Exception as error:
        session.rollback()
        _raise_domain(error)
        raise


@router.get("/novels/{novel_id}/search")
def novels_search(
    novel_id: UUID,
    q: str,
    limit: int = 20,
    session: Session = Depends(get_session),
) -> list[dict[str, object]]:
    try:
        return search_novel(session, novel_id, q, limit=limit)
    except Exception as error:
        _raise_domain(error)
        raise


@router.get("/novels/{novel_id}/context")
def novels_context(
    novel_id: UUID,
    document_id: UUID | None = None,
    max_chars: int = 12_000,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return get_novel_context(
            session, novel_id, document_id=document_id, max_chars=max_chars
        )
    except Exception as error:
        _raise_domain(error)
        raise


pawapp.include_router(router)
