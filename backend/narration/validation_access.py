"""Database-backed scope check for the hidden T4-K HTTP surface.

The bearer token is deliberately insufficient on its own.  Every hidden
validation request must also resolve to the one pre-attested novel/chapter
scope loaded by the production runtime.  Unknown route shapes fail closed.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    MediaAsset,
    NarrationEdition,
    NarrationRequest,
    NarrationScript,
    NarrationScriptVersion,
    VoicePreview,
    VoiceProfile,
)
from .production_runtime import ValidationRuntimeScope


def _canonical_uuid(value: object) -> UUID | None:
    if type(value) is UUID:
        return value
    if type(value) is not str:
        return None
    try:
        parsed = UUID(value)
    except ValueError:
        return None
    return parsed if str(parsed) == value else None


def _one_uuid_header(request: Request, name: str) -> UUID | None:
    values = request.headers.getlist(name)
    return _canonical_uuid(values[0]) if len(values) == 1 else None


def _matches_scope(
    row: tuple[UUID, UUID | None] | None,
    scope: ValidationRuntimeScope,
) -> bool:
    return row == (scope.novel_id, scope.document_id)


def validation_request_scope_authorized(
    session: Session,
    request: Request,
    scope: ValidationRuntimeScope,
) -> bool:
    """Resolve a T4 route to the exact validation novel/chapter.

    This function performs SELECT-only lookups.  The domain backends still
    enforce their own fixed-local ownership and relationship guards.
    """

    if not scope.active():
        return False
    path = request.path_params
    direct_document = _canonical_uuid(path.get("document_id"))
    if direct_document is not None:
        return direct_document == scope.document_id
    direct_novel = _canonical_uuid(path.get("novel_id"))
    if direct_novel is not None:
        return direct_novel == scope.novel_id

    request_id = _canonical_uuid(path.get("request_id"))
    if request_id is not None:
        row = session.execute(
            select(NarrationRequest.novel_id, NarrationRequest.document_id).where(
                NarrationRequest.id == request_id
            )
        ).one_or_none()
        return _matches_scope(row, scope)

    edition_id = _canonical_uuid(path.get("edition_id"))
    if edition_id is not None:
        row = session.execute(
            select(NarrationEdition.novel_id, NarrationEdition.document_id).where(
                NarrationEdition.id == edition_id
            )
        ).one_or_none()
        return _matches_scope(row, scope)

    script_id = _canonical_uuid(path.get("script_id"))
    if script_id is not None:
        row = session.execute(
            select(NarrationScript.novel_id, NarrationScript.document_id).where(
                NarrationScript.id == script_id
            )
        ).one_or_none()
        return _matches_scope(row, scope)

    version_id = _canonical_uuid(path.get("version_id"))
    if version_id is not None:
        row = session.execute(
            select(NarrationScript.novel_id, NarrationScript.document_id)
            .join(
                NarrationScriptVersion,
                NarrationScriptVersion.script_id == NarrationScript.id,
            )
            .where(NarrationScriptVersion.id == version_id)
        ).one_or_none()
        return _matches_scope(row, scope)

    profile_id = _canonical_uuid(path.get("profile_id"))
    if profile_id is not None:
        novel_id = session.scalar(
            select(VoiceProfile.novel_id).where(VoiceProfile.id == profile_id)
        )
        return novel_id == scope.novel_id

    preview_id = _canonical_uuid(path.get("preview_id"))
    if preview_id is not None:
        novel_id = session.scalar(
            select(VoicePreview.novel_id).where(VoicePreview.id == preview_id)
        )
        return novel_id == scope.novel_id

    asset_id = _canonical_uuid(path.get("asset_id"))
    if asset_id is not None:
        asset_novel_id = session.scalar(
            select(MediaAsset.novel_id).where(MediaAsset.id == asset_id)
        )
        if asset_novel_id != scope.novel_id:
            return False
        header_edition_id = _one_uuid_header(request, "X-Narration-Edition-Id")
        header_preview_id = _one_uuid_header(
            request,
            "X-Narration-Voice-Preview-Id",
        )
        if (header_edition_id is None) == (header_preview_id is None):
            return False
        if header_edition_id is not None:
            row = session.execute(
                select(
                    NarrationEdition.novel_id,
                    NarrationEdition.document_id,
                ).where(NarrationEdition.id == header_edition_id)
            ).one_or_none()
            return _matches_scope(row, scope)
        preview_row = session.execute(
            select(VoicePreview.novel_id, VoicePreview.result_asset_id).where(
                VoicePreview.id == header_preview_id
            )
        ).one_or_none()
        return preview_row == (scope.novel_id, asset_id)

    query_novel = _canonical_uuid(request.query_params.get("novel_id"))
    return query_novel == scope.novel_id if query_novel is not None else False


__all__ = ["validation_request_scope_authorized"]
