"""HTTP integration for creative authority and versioned private-library data."""

from __future__ import annotations

import hashlib
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
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
from .creative_data_models import PrivateAssetVersion
from .models import (
    CandidateRevision,
    Document,
    DocumentWorkingCopy,
    PrivateAsset,
)
from .novel_lifecycle import require_active_novel
from .novel_lifecycle_errors import NovelLifecycleError
from .private_library import (
    PrivateLibraryConflictError,
    PrivateLibraryIdempotencyConflict,
    PrivateLibraryNotFoundError,
    PrivateLibraryValidationError,
    UsagePolicy,
    VersionSelection,
    apply_preset_to_novel,
    create_asset,
    list_asset_history,
    list_novel_bindings,
    list_preset_views,
    replace_novel_bindings,
    restore_asset,
    update_asset,
)
from .private_library.lexicon_contracts import LexiconEntry, LexiconPack
from .private_library.lexicon_reports import (
    append_check_decisions,
    check_report_payload,
    create_or_reuse_check_report,
    get_check_report,
)
from .private_library.lexicon_service import (
    get_or_create_collection_pack,
    get_scoped_asset_view,
    list_scoped_assets,
    require_asset_scope,
    resolve_effective_lexicon_policy,
    lexicon_pack_from_version,
    merge_lexicon_entries,
    save_lexicon_pack,
)
from .private_library.lexicon_renderer import render_lexicon_pack
from .private_library.maintenance_contracts import LibraryCheckTextRef
from .private_library.service import set_novel_asset_enabled
from .private_library.selection_application import resolve_selection_application_source


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


class LibraryCheckCreate(_Strict):
    source_kind: str
    document_id: UUID
    source_id: UUID | None = None
    source_version: int = Field(ge=0)
    text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    accepted_segment_ids: list[str] | None = Field(default=None, max_length=200)


class LibraryCheckDecisionPut(_Strict):
    expected_version: int = Field(gt=0)
    keep_hit_ids: list[UUID] = Field(default_factory=list, max_length=200)
    skip_incomplete: bool = False


class PrivateLibraryAssetCreate(_Strict):
    asset_type: Literal["vocabulary", "writing_style", "plot", "idea"]
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(default="", max_length=30_000)
    tags: list[str] = Field(default_factory=list, max_length=50)
    scope_kind: Literal["library", "novel"] = "library"
    scope_novel_id: UUID | None = None
    enable_for_novel_id: UUID | None = None
    operation_key: str = Field(min_length=8, max_length=160)


class PrivateLibraryAssetUpdate(_Strict):
    expected_root_version: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(default="", max_length=30_000)
    tags: list[str] = Field(default_factory=list, max_length=50)
    operation_key: str = Field(min_length=8, max_length=160)


class PrivateLibraryEntryPut(_Strict):
    expected_root_version: int = Field(gt=0)
    operation_key: str = Field(min_length=8, max_length=160)
    entry: LexiconEntry


class PrivateLibraryEnabledPut(_Strict):
    expected_binding_version: int = Field(ge=0)
    enabled: bool
    operation_key: str = Field(min_length=8, max_length=160)


class PrivateLibraryPresetApply(_Strict):
    operation_key: str = Field(min_length=8, max_length=160)


class PrivateLibraryArchivedPut(_Strict):
    expected_root_version: int = Field(gt=0)
    archived: bool
    operation_key: str = Field(min_length=8, max_length=160)


class PrivateLibraryVersionRestore(_Strict):
    expected_root_version: int = Field(gt=0)
    operation_key: str = Field(min_length=8, max_length=160)


class PrivateLibraryCaptureCreate(_Strict):
    selection_id: UUID
    selected_text: str = Field(min_length=1, max_length=12_000)
    selected_text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_value_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_document_id: str = Field(min_length=1, max_length=240)
    field_id: str = Field(min_length=1, max_length=200)
    category: Literal["vocabulary", "writing_style", "plot", "idea"]
    action: Literal["recommend", "watch", "forbid"] = "recommend"
    destination: Literal["collect", "use_current_novel"]
    novel_id: UUID | None = None
    target_asset_id: UUID | None = None
    operation_key: str = Field(min_length=8, max_length=160)


def _raise(error: Exception) -> None:
    if isinstance(error, NovelLifecycleError):
        raise HTTPException(
            error.http_status,
            detail={"type": error.code, "message": str(error)},
        ) from error
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


def _require_active(session: Session, novel_id: UUID) -> None:
    try:
        require_active_novel(session, novel_id)
    except NovelLifecycleError as error:
        _raise(error)


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
    _require_active(session, novel_id)
    return _outline_payload(get_outline(session, novel_id))


@router.patch("/novels/{novel_id}/outline")
def outline_patch(
    novel_id: UUID, request: OutlinePatch, session: Session = Depends(get_session)
) -> dict[str, object]:
    _require_active(session, novel_id)
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
    _require_active(session, novel_id)
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
    _require_active(session, novel_id)
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
    _require_active(session, novel_id)
    return _setting_payload(get_settings(session, novel_id))


@router.patch("/novels/{novel_id}/story-settings")
def settings_patch(
    novel_id: UUID, request: SettingPatch, session: Session = Depends(get_session)
) -> dict[str, object]:
    _require_active(session, novel_id)
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
    _require_active(session, novel_id)
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
    _require_active(session, novel_id)
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
    novel_id: UUID | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[dict[str, object]]:
    try:
        asset = session.get(PrivateAsset, asset_id)
        if asset is None:
            raise PrivateLibraryNotFoundError("private asset not found")
        require_asset_scope(asset, novel_id=novel_id)
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
    asset_id: UUID,
    request: AssetRestoreRequest,
    novel_id: UUID | None = Query(default=None),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        asset = session.get(PrivateAsset, asset_id)
        if asset is None:
            raise PrivateLibraryNotFoundError("private asset not found")
        require_asset_scope(asset, novel_id=novel_id)
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
    _require_active(session, novel_id)
    try:
        return [_binding_payload(item) for item in list_novel_bindings(session, novel_id)]
    except Exception as error:
        _raise(error); raise


@router.put("/novels/{novel_id}/asset-bindings")
def bindings_put(
    novel_id: UUID, request: BindingPut, session: Session = Depends(get_session)
) -> dict[str, object]:
    _require_active(session, novel_id)
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


@router.get("/private-library/presets")
def private_library_presets_get(
    session: Session = Depends(get_session),
) -> dict[str, object]:
    """Return legacy combinations without reopening their management UI."""

    try:
        items = list_preset_views(session)
        return {"items": items, "total": len(items)}
    except Exception as error:
        _raise(error); raise


@router.post("/novels/{novel_id}/private-library/presets/{preset_id}/apply")
def private_library_preset_apply(
    novel_id: UUID,
    preset_id: UUID,
    request: PrivateLibraryPresetApply,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    _require_active(session, novel_id)
    try:
        result = apply_preset_to_novel(
            session,
            novel_id,
            preset_id,
            operation_key=request.operation_key,
        )
        session.commit()
        return {
            "changed": result.changed,
            "bindings": [_binding_payload(item) for item in result.bindings],
        }
    except Exception as error:
        session.rollback(); _raise(error); raise


@router.get("/private-library/assets")
def private_library_assets_get(
    novel_id: UUID | None = Query(default=None),
    asset_type: str | None = Query(default=None),
    query: str = Query(default="", max_length=200),
    include_archived: bool = Query(default=False),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    scope_filter: Literal["all", "library", "novel"] = Query(default="all"),
    enabled_filter: Literal["all", "enabled", "disabled"] = Query(default="all"),
    projection: Literal["full", "summary"] = Query(default="full"),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    """Return a bounded personal-library page plus the selected novel's copies."""

    try:
        page = list_scoped_assets(
            session,
            novel_id=novel_id,
            asset_type=asset_type,
            query=query,
            include_archived=include_archived,
            offset=offset,
            limit=limit,
            scope_filter=scope_filter,
            enabled_filter=enabled_filter,
            projection=projection,
        )
        return {
            "items": list(page.items),
            "offset": page.offset,
            "limit": page.limit,
            "total": page.total,
            "has_more": page.has_more,
            "next_offset": page.next_offset,
        }
    except Exception as error:
        _raise(error); raise


@router.get("/private-library/assets/{asset_id}")
def private_library_asset_get(
    asset_id: UUID,
    novel_id: UUID | None = Query(default=None),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return get_scoped_asset_view(session, asset_id, novel_id=novel_id)
    except Exception as error:
        _raise(error); raise


@router.put("/private-library/assets/{asset_id}/archived")
def private_library_asset_archived_put(
    asset_id: UUID,
    request: PrivateLibraryArchivedPut,
    novel_id: UUID | None = Query(default=None),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        asset = session.scalar(
            select(PrivateAsset).where(PrivateAsset.id == asset_id).with_for_update()
        )
        if asset is None:
            raise PrivateLibraryNotFoundError("private asset not found")
        require_asset_scope(asset, novel_id=novel_id)
        changed = bool(asset.archived) != request.archived
        # Desired-state PUTs are safely replayable: a repeated request that has
        # already reached its target is a no-op even if its old CAS version was
        # consumed by the first successful call.
        if changed and int(asset.version) != request.expected_root_version:
            raise PrivateLibraryConflictError(
                "asset_root_version_conflict",
                current={"asset_id": str(asset.id), "root_version": int(asset.version)},
            )
        if changed:
            asset.archived = request.archived
            asset.version = int(asset.version) + 1
            session.flush()
        session.commit()
        return {
            **get_scoped_asset_view(session, asset.id, novel_id=novel_id),
            "changed": changed,
        }
    except Exception as error:
        session.rollback(); _raise(error); raise


@router.get("/private-library/assets/{asset_id}/versions")
def private_library_asset_versions_get(
    asset_id: UUID,
    novel_id: UUID | None = Query(default=None),
    before_version_number: int | None = Query(default=None, gt=0),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        asset = session.get(PrivateAsset, asset_id)
        if asset is None:
            raise PrivateLibraryNotFoundError("private asset not found")
        require_asset_scope(asset, novel_id=novel_id)
        rows = list_asset_history(
            session,
            asset_id,
            before_version_number=before_version_number,
            limit=limit,
        )
        return {
            "items": [{
                "id": str(item.id),
                "version_number": int(item.version_number),
                "title": item.title,
                "content_hash": item.content_hash,
                "created_at": item.created_at,
                "current": item.id == asset.current_version_id,
            } for item in rows],
            "has_more": len(rows) == limit,
        }
    except Exception as error:
        _raise(error); raise


@router.post("/private-library/assets/{asset_id}/versions/{asset_version_id}/restore")
def private_library_asset_version_restore(
    asset_id: UUID,
    asset_version_id: UUID,
    request: PrivateLibraryVersionRestore,
    novel_id: UUID | None = Query(default=None),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        asset = session.get(PrivateAsset, asset_id)
        if asset is None:
            raise PrivateLibraryNotFoundError("private asset not found")
        require_asset_scope(asset, novel_id=novel_id)
        restore_asset(
            session,
            asset_id,
            asset_version_id,
            expected_root_version=request.expected_root_version,
            operation_key=request.operation_key,
        )
        session.commit()
        return get_scoped_asset_view(session, asset.id, novel_id=novel_id)
    except Exception as error:
        session.rollback(); _raise(error); raise




@router.post("/private-library/assets", status_code=status.HTTP_201_CREATED)
def private_library_asset_create(
    request: PrivateLibraryAssetCreate,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    if (request.scope_kind == "library") != (request.scope_novel_id is None):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="通用库不能携带小说范围，本书资料必须指定小说",
        )
    if request.scope_novel_id is not None:
        _require_active(session, request.scope_novel_id)
    if (
        request.scope_kind == "novel"
        and request.enable_for_novel_id not in (None, request.scope_novel_id)
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="本书专用资料不能启用到其他作品",
        )
    try:
        pack = LexiconPack() if request.asset_type == "vocabulary" else None
        rendered = render_lexicon_pack(pack) if pack is not None else None
        result = create_asset(
            session,
            asset_id=uuid4(),
            asset_type=request.asset_type,
            title=request.title,
            content=rendered.content if rendered is not None else request.content,
            metadata=pack.model_dump(mode="json") if pack is not None else {},
            operation_key=request.operation_key,
            tags=request.tags,
            source={"kind": "author_ui"},
            rights={"usage": "private_author_material"},
        )
        result.asset.scope_kind = request.scope_kind
        result.asset.scope_novel_id = request.scope_novel_id
        session.flush()
        enable_novel_id = request.enable_for_novel_id
        if enable_novel_id is not None:
            set_novel_asset_enabled(
                session,
                novel_id=enable_novel_id,
                asset_id=result.asset.id,
                expected_binding_version=0,
                enabled=True,
                operation_key=f"{request.operation_key}:enable",
            )
        session.commit()
        return get_scoped_asset_view(
            session,
            result.asset.id,
            novel_id=enable_novel_id or request.scope_novel_id,
        )
    except Exception as error:
        session.rollback(); _raise(error); raise


@router.put("/private-library/assets/{asset_id}")
def private_library_asset_update(
    asset_id: UUID,
    request: PrivateLibraryAssetUpdate,
    novel_id: UUID | None = Query(default=None),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        asset = session.get(PrivateAsset, asset_id)
        if asset is None:
            raise PrivateLibraryNotFoundError("private asset not found")
        require_asset_scope(asset, novel_id=novel_id)
        if asset.current_version_id is None:
            raise PrivateLibraryConflictError("asset_current_version_missing")
        current = session.get(PrivateAssetVersion, asset.current_version_id)
        if current is None:
            raise PrivateLibraryConflictError("asset_current_version_missing")
        content = request.content
        metadata = None
        if asset.asset_type == "vocabulary":
            pack = lexicon_pack_from_version(current)
            content = render_lexicon_pack(pack).content
            metadata = pack.model_dump(mode="json")
        update_asset(
            session,
            asset_id,
            expected_root_version=request.expected_root_version,
            operation_key=request.operation_key,
            title=request.title,
            content=content,
            tags=request.tags,
            metadata=metadata,
        )
        session.commit()
        return get_scoped_asset_view(session, asset_id, novel_id=novel_id)
    except Exception as error:
        session.rollback(); _raise(error); raise


@router.put("/private-library/assets/{asset_id}/entries")
def private_library_entry_put(
    asset_id: UUID,
    request: PrivateLibraryEntryPut,
    novel_id: UUID | None = Query(default=None),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        asset = session.get(PrivateAsset, asset_id)
        if asset is None or asset.asset_type != "vocabulary":
            raise PrivateLibraryNotFoundError("vocabulary asset not found")
        require_asset_scope(asset, novel_id=novel_id)
        if asset.current_version_id is None:
            raise PrivateLibraryConflictError("asset_current_version_missing")
        current = session.get(PrivateAssetVersion, asset.current_version_id)
        if current is None:
            raise PrivateLibraryConflictError("asset_current_version_missing")
        pack = merge_lexicon_entries(
            lexicon_pack_from_version(current),
            [request.entry],
        )
        save_lexicon_pack(
            session,
            asset_id=asset_id,
            expected_root_version=request.expected_root_version,
            pack=pack,
            operation_key=request.operation_key,
            novel_id=novel_id,
        )
        session.commit()
        return get_scoped_asset_view(session, asset_id, novel_id=novel_id)
    except Exception as error:
        session.rollback(); _raise(error); raise


@router.put("/novels/{novel_id}/private-library/assets/{asset_id}/enabled")
def private_library_asset_enabled_put(
    novel_id: UUID,
    asset_id: UUID,
    request: PrivateLibraryEnabledPut,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    _require_active(session, novel_id)
    try:
        set_novel_asset_enabled(
            session,
            novel_id=novel_id,
            asset_id=asset_id,
            expected_binding_version=request.expected_binding_version,
            enabled=request.enabled,
            operation_key=request.operation_key,
        )
        session.commit()
        return get_scoped_asset_view(session, asset_id, novel_id=novel_id)
    except Exception as error:
        session.rollback(); _raise(error); raise


@router.post("/private-library/captures", status_code=status.HTTP_201_CREATED)
def private_library_capture_create(
    request: PrivateLibraryCaptureCreate,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    actual_text_hash = hashlib.sha256(
        request.selected_text.encode("utf-8")
    ).hexdigest()
    if actual_text_hash != request.selected_text_sha256:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "selection_text_changed", "text_sha256": actual_text_hash},
        )
    novel_id = request.novel_id
    if (request.destination == "use_current_novel") != (novel_id is not None):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="用于本书必须指定当前作品；仅收藏不能携带作品范围",
        )
    if novel_id is not None:
        _require_active(session, novel_id)
    source = {
        "kind": "unsynced_selection",
        "selection_id": str(request.selection_id),
        "document_id": request.source_document_id,
        "field_id": request.field_id,
        "text_sha256": request.selected_text_sha256,
        "source_value_sha256": request.source_value_sha256,
    }
    try:
        if request.category == "vocabulary":
            if request.target_asset_id is None:
                asset, version, _ = get_or_create_collection_pack(
                    session,
                    novel_id=novel_id,
                    operation_key=f"{request.operation_key}:collection",
                )
            else:
                asset = session.get(PrivateAsset, request.target_asset_id)
                if asset is None or asset.asset_type != "vocabulary":
                    raise PrivateLibraryNotFoundError("vocabulary asset not found")
                require_asset_scope(asset, novel_id=novel_id, allow_library=novel_id is None)
                if asset.current_version_id is None:
                    raise PrivateLibraryConflictError("asset_current_version_missing")
                version = session.get(PrivateAssetVersion, asset.current_version_id)
                if version is None:
                    raise PrivateLibraryConflictError("asset_current_version_missing")
            entry = LexiconEntry(
                entry_id=f"selection_{request.selection_id.hex}",
                term=request.selected_text.strip(),
                action=request.action,
                source_refs=[{
                    "source_type": "selection",
                    "label": "作者选区收藏",
                    "locator": (
                        f"{request.source_document_id}:{request.field_id}:"
                        f"{request.selection_id}"
                    ),
                    "verified_popularity": False,
                }],
            )
            pack = merge_lexicon_entries(
                lexicon_pack_from_version(version),
                [entry],
            )
            save_lexicon_pack(
                session,
                asset_id=asset.id,
                expected_root_version=int(asset.version),
                pack=pack,
                operation_key=f"{request.operation_key}:entry",
                novel_id=novel_id,
            )
        else:
            if request.target_asset_id is None:
                result = create_asset(
                    session,
                    asset_id=uuid4(),
                    asset_type=request.category,
                    title=request.selected_text.strip().splitlines()[0][:24],
                    content=request.selected_text,
                    operation_key=request.operation_key,
                    tags=["选区收藏"],
                    source=source,
                    rights={"usage": "private_author_material"},
                )
                asset = result.asset
                asset.scope_kind = "novel" if novel_id is not None else "library"
                asset.scope_novel_id = novel_id
                session.flush()
            else:
                asset = session.get(PrivateAsset, request.target_asset_id)
                if asset is None or asset.asset_type != request.category:
                    raise PrivateLibraryNotFoundError("capture target asset not found")
                require_asset_scope(asset, novel_id=novel_id, allow_library=novel_id is None)
                if asset.current_version_id is None:
                    raise PrivateLibraryConflictError("asset_current_version_missing")
                current = session.get(PrivateAssetVersion, asset.current_version_id)
                if current is None:
                    raise PrivateLibraryConflictError("asset_current_version_missing")
                update_asset(
                    session,
                    asset.id,
                    expected_root_version=int(asset.version),
                    operation_key=request.operation_key,
                    title=current.title,
                    content=(current.content.rstrip() + "\n\n" + request.selected_text).strip(),
                    source=source,
                )
        if novel_id is not None:
            views = list_novel_bindings(session, novel_id)
            current = next((item for item in views if item.asset.id == asset.id), None)
            if current is None:
                set_novel_asset_enabled(
                    session,
                    novel_id=novel_id,
                    asset_id=asset.id,
                    expected_binding_version=0,
                    enabled=True,
                    operation_key=f"{request.operation_key}:enable",
                )
        session.commit()
        return {
            "saved": True,
            "source": source,
            "asset": get_scoped_asset_view(session, asset.id, novel_id=novel_id),
            "used_by_current_novel": novel_id is not None,
        }
    except Exception as error:
        session.rollback(); _raise(error); raise


def _library_check_source(
    session: Session,
    novel_id: UUID,
    request: LibraryCheckCreate,
) -> tuple[str, UUID, tuple[str, int, int] | None]:
    document = session.get(Document, request.document_id)
    if document is None or document.novel_id != novel_id:
        raise PrivateLibraryNotFoundError("document is outside the selected novel")
    if request.source_kind == "working_copy":
        if request.source_id is not None:
            raise PrivateLibraryValidationError("working copy cannot carry source_id")
        source = session.get(DocumentWorkingCopy, request.document_id)
        if source is None or int(source.draft_version) != request.source_version:
            raise PrivateLibraryConflictError(
                "library_check_source_changed",
                current={
                    "source_version": int(source.draft_version) if source else None,
                    "text_hash": source.content_hash if source else None,
                },
            )
        if source.content_hash != request.text_sha256:
            raise PrivateLibraryConflictError(
                "library_check_source_changed",
                current={"text_hash": source.content_hash},
            )
        # Working copies have no independent row id; the immutable source
        # identity is the document id plus the guarded draft version/hash.
        return source.content_markdown, request.document_id, None
    if request.source_kind == "candidate":
        if request.source_id is None:
            raise PrivateLibraryValidationError("candidate source_id is required")
        candidate = session.get(CandidateRevision, request.source_id)
        if candidate is None or candidate.document_id != request.document_id:
            raise PrivateLibraryNotFoundError("candidate is outside the selected document")
        if request.source_version != 1 or candidate.content_hash != request.text_sha256:
            raise PrivateLibraryConflictError(
                "library_check_source_changed",
                current={"source_version": 1, "text_hash": candidate.content_hash},
            )
        return candidate.content_markdown, candidate.id, None
    if request.source_kind == "selection_result":
        if request.source_id is None:
            raise PrivateLibraryValidationError("selection result source_id is required")
        final_markdown, unchanged_baseline = resolve_selection_application_source(
            session, novel_id, request.document_id, request.source_id,
            request.source_version, request.text_sha256, request.accepted_segment_ids,
        )
        return final_markdown, request.source_id, unchanged_baseline
    raise PrivateLibraryValidationError("check source kind is not supported by this endpoint")


@router.post("/novels/{novel_id}/library-checks", status_code=status.HTTP_201_CREATED)
def library_check_create(
    novel_id: UUID,
    request: LibraryCheckCreate,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    _require_active(session, novel_id)
    try:
        source_markdown, source_id, unchanged_baseline = _library_check_source(
            session, novel_id, request
        )
        source_text_sha256 = hashlib.sha256(
            source_markdown.encode("utf-8")
        ).hexdigest()
        policy = resolve_effective_lexicon_policy(session, novel_id, lock=False)
        result = create_or_reuse_check_report(
            session,
            text_ref=LibraryCheckTextRef(
                source_kind=request.source_kind,
                novel_id=novel_id,
                document_id=request.document_id,
                version=request.source_version,
                text_sha256=source_text_sha256,
            ),
            source_markdown=source_markdown,
            policy=policy,
            source_id=source_id,
            unchanged_baseline=unchanged_baseline,
        )
        session.commit()
        return {**check_report_payload(result.report), "replayed": result.replayed}
    except Exception as error:
        session.rollback(); _raise(error); raise


@router.get("/novels/{novel_id}/library-checks/{report_id}")
def library_check_get(
    novel_id: UUID,
    report_id: UUID,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=200),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    _require_active(session, novel_id)
    try:
        return check_report_payload(
            get_check_report(session, novel_id=novel_id, report_id=report_id),
            offset=offset,
            limit=limit,
        )
    except Exception as error:
        _raise(error); raise


@router.post("/novels/{novel_id}/library-checks/{report_id}/decisions")
def library_check_decisions(
    novel_id: UUID,
    report_id: UUID,
    request: LibraryCheckDecisionPut,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    _require_active(session, novel_id)
    try:
        report = append_check_decisions(
            session,
            novel_id=novel_id,
            report_id=report_id,
            expected_version=request.expected_version,
            keep_hit_ids=request.keep_hit_ids,
            skip_incomplete=request.skip_incomplete,
        )
        session.commit()
        return check_report_payload(report)
    except Exception as error:
        session.rollback(); _raise(error); raise
