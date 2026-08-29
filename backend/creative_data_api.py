"""HTTP integration for creative authority and versioned private-library data."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from .creative_authority import (
    AuthorityConflictError,
    AuthorityIdempotencyConflict,
    AuthorityNotFoundError,
    AuthorityValidationError,
    get_outline,
    get_settings,
    list_outline_history,
    list_settings_history,
    restore_outline,
    restore_settings,
    save_outline,
    save_settings,
)
from .database import get_session
from .private_library import (
    PrivateLibraryConflictError,
    PrivateLibraryIdempotencyConflict,
    PrivateLibraryNotFoundError,
    PrivateLibraryValidationError,
    UsagePolicy,
    VersionSelection,
    list_asset_history,
    list_novel_bindings,
    replace_novel_bindings,
    restore_asset,
)


router = APIRouter(tags=["creative-data-v2"])


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class OutlinePatch(_Strict):
    expected_head_version: int = Field(ge=0)
    idempotency_key: str = Field(min_length=1, max_length=160)
    source_kind: str = Field(default="manual", min_length=1, max_length=40)
    target_chapter_count: int = Field(gt=0)
    background_text: str = ""
    plot_text: str = ""
    highlight_text: str = ""
    character_revision_refs: list[dict[str, Any]] = Field(default_factory=list)
    change_set: dict[str, Any] = Field(default_factory=dict)


class SettingPatch(_Strict):
    expected_head_version: int = Field(ge=0)
    idempotency_key: str = Field(min_length=1, max_length=160)
    source_kind: str = Field(default="manual", min_length=1, max_length=40)
    schema_id: str = Field(min_length=1, max_length=80)
    schema_version: int = Field(gt=0)
    settings: dict[str, Any]
    change_set: dict[str, Any] = Field(default_factory=dict)


class RestoreRequest(_Strict):
    expected_head_version: int = Field(ge=0)
    idempotency_key: str = Field(min_length=1, max_length=160)
    revision_id: UUID


class AssetRestoreRequest(_Strict):
    expected_root_version: int = Field(gt=0)
    operation_key: str = Field(min_length=1, max_length=160)
    asset_version_id: UUID


class BindingSelection(_Strict):
    asset_id: UUID
    asset_version_id: UUID
    usage_policy: UsagePolicy = UsagePolicy.PREFERRED
    position: int = Field(ge=0)


class BindingPut(_Strict):
    expected_binding_versions: dict[UUID, int]
    selections: list[BindingSelection]
    operation_key: str = Field(min_length=1, max_length=160)


def _raise(error: Exception) -> None:
    if isinstance(error, (AuthorityNotFoundError, PrivateLibraryNotFoundError)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    if isinstance(
        error,
        (
            AuthorityConflictError,
            AuthorityIdempotencyConflict,
            PrivateLibraryConflictError,
            PrivateLibraryIdempotencyConflict,
        ),
    ):
        current = getattr(error, "current", None)
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": type(error).__name__, "message": str(error), "current": current},
        ) from error
    if isinstance(error, (AuthorityValidationError, PrivateLibraryValidationError)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    raise error


def _outline_payload(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    head, revision = value  # type: ignore[misc]
    return {
        "novel_id": str(head.novel_id), "head_version": head.version,
        "current_revision_id": str(head.current_revision_id),
        "revision_number": revision.revision_number,
        "parent_revision_id": str(revision.parent_revision_id) if revision.parent_revision_id else None,
        "restored_from_revision_id": str(revision.restored_from_revision_id) if revision.restored_from_revision_id else None,
        "source_kind": revision.source_kind,
        "target_chapter_count": revision.target_chapter_count,
        "background_text": revision.background_text, "plot_text": revision.plot_text,
        "highlight_text": revision.highlight_text,
        "character_revision_refs": list(revision.character_revision_refs_json),
        "content_hash": revision.content_hash, "created_at": revision.created_at,
    }


def _setting_payload(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    head, revision = value  # type: ignore[misc]
    return {
        "novel_id": str(head.novel_id), "head_version": head.version,
        "current_revision_id": str(head.current_revision_id),
        "revision_number": revision.revision_number,
        "parent_revision_id": str(revision.parent_revision_id) if revision.parent_revision_id else None,
        "restored_from_revision_id": str(revision.restored_from_revision_id) if revision.restored_from_revision_id else None,
        "source_kind": revision.source_kind, "schema_id": revision.schema_id,
        "schema_version": revision.schema_version,
        "settings": dict(revision.settings_json), "content_hash": revision.content_hash,
        "created_at": revision.created_at,
    }


@router.get("/novels/{novel_id}/outline")
def outline_get(novel_id: UUID, session: Session = Depends(get_session)) -> dict[str, object] | None:
    return _outline_payload(get_outline(session, novel_id))


@router.patch("/novels/{novel_id}/outline")
def outline_patch(
    novel_id: UUID, request: OutlinePatch, session: Session = Depends(get_session)
) -> dict[str, object]:
    try:
        save_outline(
            session, novel_id, expected_head_version=request.expected_head_version,
            idempotency_key=request.idempotency_key, source_kind=request.source_kind,
            target_chapter_count=request.target_chapter_count,
            background_text=request.background_text, plot_text=request.plot_text,
            highlight_text=request.highlight_text,
            character_revision_refs=request.character_revision_refs,
            change_set=request.change_set,
        )
        session.commit()
        return _outline_payload(get_outline(session, novel_id)) or {}
    except Exception as error:
        session.rollback(); _raise(error); raise


@router.post("/novels/{novel_id}/outline/restore")
def outline_restore(
    novel_id: UUID, request: RestoreRequest, session: Session = Depends(get_session)
) -> dict[str, object]:
    try:
        restore_outline(
            session, novel_id, request.revision_id,
            expected_head_version=request.expected_head_version,
            idempotency_key=request.idempotency_key,
        )
        session.commit()
        return _outline_payload(get_outline(session, novel_id)) or {}
    except Exception as error:
        session.rollback(); _raise(error); raise


@router.get("/novels/{novel_id}/outline/history")
def outline_history(
    novel_id: UUID, before_revision_number: int | None = Query(default=None, gt=0),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
) -> list[dict[str, object]]:
    return [
        {
            "id": str(item.id), "revision_number": item.revision_number,
            "parent_revision_id": str(item.parent_revision_id) if item.parent_revision_id else None,
            "restored_from_revision_id": str(item.restored_from_revision_id) if item.restored_from_revision_id else None,
            "source_kind": item.source_kind, "content_hash": item.content_hash,
            "created_at": item.created_at,
        }
        for item in list_outline_history(
            session, novel_id, before_revision_number=before_revision_number, limit=limit
        )
    ]


@router.get("/novels/{novel_id}/story-settings")
def settings_get(novel_id: UUID, session: Session = Depends(get_session)) -> dict[str, object] | None:
    return _setting_payload(get_settings(session, novel_id))


@router.patch("/novels/{novel_id}/story-settings")
def settings_patch(
    novel_id: UUID, request: SettingPatch, session: Session = Depends(get_session)
) -> dict[str, object]:
    try:
        save_settings(
            session, novel_id, expected_head_version=request.expected_head_version,
            idempotency_key=request.idempotency_key, source_kind=request.source_kind,
            schema_id=request.schema_id, schema_version=request.schema_version,
            settings=request.settings, change_set=request.change_set,
        )
        session.commit()
        return _setting_payload(get_settings(session, novel_id)) or {}
    except Exception as error:
        session.rollback(); _raise(error); raise


@router.post("/novels/{novel_id}/story-settings/restore")
def settings_restore(
    novel_id: UUID, request: RestoreRequest, session: Session = Depends(get_session)
) -> dict[str, object]:
    try:
        restore_settings(
            session, novel_id, request.revision_id,
            expected_head_version=request.expected_head_version,
            idempotency_key=request.idempotency_key,
        )
        session.commit()
        return _setting_payload(get_settings(session, novel_id)) or {}
    except Exception as error:
        session.rollback(); _raise(error); raise


@router.get("/novels/{novel_id}/story-settings/history")
def settings_history(
    novel_id: UUID, before_revision_number: int | None = Query(default=None, gt=0),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
) -> list[dict[str, object]]:
    return [
        {
            "id": str(item.id), "revision_number": item.revision_number,
            "parent_revision_id": str(item.parent_revision_id) if item.parent_revision_id else None,
            "restored_from_revision_id": str(item.restored_from_revision_id) if item.restored_from_revision_id else None,
            "source_kind": item.source_kind, "schema_id": item.schema_id,
            "schema_version": item.schema_version, "content_hash": item.content_hash,
            "created_at": item.created_at,
        }
        for item in list_settings_history(
            session, novel_id, before_revision_number=before_revision_number, limit=limit
        )
    ]


@router.get("/private-assets/{asset_id}/versions")
def asset_versions(
    asset_id: UUID, before_version_number: int | None = Query(default=None, gt=0),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
) -> list[dict[str, object]]:
    try:
        return [
            {
                "id": str(item.id), "asset_id": str(item.asset_id),
                "version_number": item.version_number, "title": item.title,
                "content_hash": item.content_hash, "created_at": item.created_at,
            }
            for item in list_asset_history(
                session, asset_id, before_version_number=before_version_number, limit=limit
            )
        ]
    except Exception as error:
        _raise(error); raise


@router.post("/private-assets/{asset_id}/restore")
def asset_restore(
    asset_id: UUID, request: AssetRestoreRequest, session: Session = Depends(get_session)
) -> dict[str, object]:
    try:
        result = restore_asset(
            session, asset_id, request.asset_version_id,
            expected_root_version=request.expected_root_version,
            operation_key=request.operation_key,
        )
        session.commit()
        return {
            "asset_id": str(result.asset.id), "root_version": result.asset.version,
            "current_version_id": str(result.asset_version.id),
            "restored_from_version_id": str(result.restored_from_version_id),
            "content_hash": result.asset_version.content_hash, "replayed": result.replayed,
        }
    except Exception as error:
        session.rollback(); _raise(error); raise


def _binding_payload(item: object) -> dict[str, object]:
    view = item  # type: ignore[assignment]
    return {
        "id": str(view.binding.id), "asset_id": str(view.asset.id),
        "asset_version_id": str(view.asset_version.id),
        "usage_policy": view.binding.usage_policy, "position": view.binding.position,
        "version": view.binding.version, "title": view.asset_version.title,
        "content_hash": view.asset_version.content_hash,
        "update_available": view.update_available,
    }


@router.get("/novels/{novel_id}/asset-bindings")
def bindings_get(
    novel_id: UUID, session: Session = Depends(get_session)
) -> list[dict[str, object]]:
    try:
        return [_binding_payload(item) for item in list_novel_bindings(session, novel_id)]
    except Exception as error:
        _raise(error); raise


@router.put("/novels/{novel_id}/asset-bindings")
def bindings_put(
    novel_id: UUID, request: BindingPut, session: Session = Depends(get_session)
) -> dict[str, object]:
    try:
        result = replace_novel_bindings(
            session, novel_id,
            expected_binding_versions=request.expected_binding_versions,
            selections=tuple(
                VersionSelection(
                    asset_id=item.asset_id, asset_version_id=item.asset_version_id,
                    usage_policy=item.usage_policy, position=item.position,
                )
                for item in request.selections
            ),
            operation_key=request.operation_key,
        )
        session.commit()
        return {"changed": result.changed, "bindings": [_binding_payload(item) for item in result.bindings]}
    except Exception as error:
        session.rollback(); _raise(error); raise
