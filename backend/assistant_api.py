"""Ephemeral page-context transport exposed through the PawApp namespace."""

from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .assistant_context import TARGET_AGENT_ID
from .assistant_context_registry import (
    AssistantContextRefRegistry,
    CONTEXT_REF_MAX_REQUEST_BYTES,
    ContextRefBinding,
    ContextRefCreateError,
    ContextRefCreateErrorCode,
)
from .database import get_session
from .creative_services import get_novel_creation_draft
from .models import Document, Novel
from .novel_lifecycle import require_active_novel
from .novel_lifecycle_errors import NovelLifecycleNotFound, NovelRecycledError
from .services import NotFoundError, get_document, get_novel


router = APIRouter()
assistant_context_registry = AssistantContextRefRegistry()


_REQUIRED_NOVEL_CREATE_KEYS = frozenset(
    {"ownerToken", "tabInstance", "agentId", "novelId", "snapshot"},
)
_OPTIONAL_NOVEL_CREATE_KEYS = frozenset({"documentId", "sessionId"})
_REQUIRED_CREATION_CREATE_KEYS = frozenset({
    "ownerToken", "tabInstance", "agentId", "scopeKind", "scopeId", "snapshot",
})
_OPTIONAL_CREATION_CREATE_KEYS = frozenset({"sessionId"})
_REQUIRED_LIBRARY_CREATE_KEYS = frozenset({
    "ownerToken", "tabInstance", "agentId", "scopeKind", "scopeId", "snapshot",
})
_OPTIONAL_LIBRARY_CREATE_KEYS = frozenset({"sessionId", "novelId"})


async def _bounded_body(request: Request) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > CONTEXT_REF_MAX_REQUEST_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail={"type": "assistant_context_rejected", "reason": "request-too-large"},
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _safe_create_payload(raw: bytes) -> Mapping[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"type": "assistant_context_rejected", "reason": "invalid-request"},
        ) from None
    if not isinstance(value, Mapping):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"type": "assistant_context_rejected", "reason": "invalid-request"},
        )
    keys = set(value)
    novel_shape = (
        _REQUIRED_NOVEL_CREATE_KEYS <= keys
        and keys <= _REQUIRED_NOVEL_CREATE_KEYS | _OPTIONAL_NOVEL_CREATE_KEYS
    )
    creation_shape = (
        _REQUIRED_CREATION_CREATE_KEYS <= keys
        and keys <= _REQUIRED_CREATION_CREATE_KEYS | _OPTIONAL_CREATION_CREATE_KEYS
        and value.get("scopeKind") == "creation_draft"
    )
    library_shape = (
        _REQUIRED_LIBRARY_CREATE_KEYS <= keys
        and keys <= _REQUIRED_LIBRARY_CREATE_KEYS | _OPTIONAL_LIBRARY_CREATE_KEYS
        and value.get("scopeKind") == "private_library"
        and value.get("scopeId") == "personal"
    )
    if not (novel_shape or creation_shape or library_shape):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"type": "assistant_context_rejected", "reason": "invalid-request"},
        )
    return value


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"type": "assistant_context_rejected", "reason": "invalid-request"},
        )
    return value


def _optional_string(payload: Mapping[str, Any], key: str) -> str | None:
    if key not in payload:
        return None
    return _required_string(payload, key)


def _verify_local_novel_scope(
    session: Session,
    *,
    novel_id: str,
    document_id: str | None,
) -> None:
    """Verify local database membership without accepting a model scope."""

    try:
        novel_uuid = UUID(novel_id)
        if type(session).__module__.startswith("sqlalchemy."):
            require_active_novel(session, novel_uuid)
            novel = None
        elif not hasattr(session, "get"):
            get_novel(session, novel_uuid)
            novel = None
        else:
            novel = session.get(Novel, novel_uuid)
            if novel is None:
                raise NotFoundError("novel is outside the selected scope")
            if getattr(novel, "recycled_at", None) is not None:
                raise NovelRecycledError("小说已移入回收站")
        if document_id is not None:
            document_uuid = UUID(document_id)
            if type(session).__module__.startswith("sqlalchemy.") or hasattr(session, "get"):
                document_row = session.get(Document, document_uuid)
                if document_row is None or document_row.novel_id != novel_uuid:
                    raise NotFoundError("document is outside the selected novel")
            else:
                document = get_document(session, document_uuid)
                if str(document.get("novel_id") or "") != novel_id:
                    raise NotFoundError("document is outside the selected novel")
    except NovelRecycledError as error:
        raise HTTPException(
            status_code=error.http_status,
            detail={"type": error.code, "message": str(error)},
        ) from error
    except (ValueError, NotFoundError, NovelLifecycleNotFound):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"type": "assistant_context_scope_unavailable"},
        ) from None


def _verify_local_creation_scope(
    session: Session,
    *,
    draft_id: str,
    snapshot: Mapping[str, Any],
) -> None:
    try:
        draft = get_novel_creation_draft(session, UUID(draft_id))
    except (ValueError, NotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"type": "assistant_context_scope_unavailable"},
        ) from None
    snapshot_draft = snapshot.get("creationDraft")
    if (
        not isinstance(snapshot_draft, Mapping)
        or snapshot_draft.get("id") != draft["id"]
        or snapshot_draft.get("version") != draft["version"]
        or snapshot_draft.get("step") != draft["step"]
        or snapshot_draft.get("state") != draft["state"]
        or draft["state"] != "draft"
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"type": "assistant_context_scope_changed"},
        )


def _creation_error(error: ContextRefCreateError) -> HTTPException:
    if error.code is ContextRefCreateErrorCode.REQUEST_TOO_LARGE:
        response_status = status.HTTP_413_CONTENT_TOO_LARGE
    elif error.code is ContextRefCreateErrorCode.RATE_LIMITED:
        response_status = status.HTTP_429_TOO_MANY_REQUESTS
    else:
        response_status = status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(
        status_code=response_status,
        detail={"type": "assistant_context_rejected", "reason": error.code.value},
    )


@router.post("/assistant-contexts", status_code=status.HTTP_201_CREATED)
async def assistant_contexts_create(
    request: Request,
    session: Session = Depends(get_session),
) -> JSONResponse:
    """Create one bounded in-memory ref without echoing author content."""

    raw = await _bounded_body(request)
    payload = _safe_create_payload(raw)
    snapshot = payload.get("snapshot")
    if not isinstance(snapshot, Mapping):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"type": "assistant_context_rejected", "reason": "invalid-request"},
        )

    creation_scope = payload.get("scopeKind") == "creation_draft"
    library_scope = payload.get("scopeKind") == "private_library"
    binding = ContextRefBinding(
        owner_token=_required_string(payload, "ownerToken"),
        tab_instance=_required_string(payload, "tabInstance"),
        agent_id=_required_string(payload, "agentId"),
        novel_id=(
            None if creation_scope else (
                _optional_string(payload, "novelId")
                if library_scope
                else _required_string(payload, "novelId")
            )
        ),
        document_id=(
            None
            if creation_scope or library_scope
            else _optional_string(payload, "documentId")
        ),
        session_id=_optional_string(payload, "sessionId"),
        creation_draft_id=(
            _required_string(payload, "scopeId") if creation_scope else None
        ),
        private_library_id=(
            _required_string(payload, "scopeId") if library_scope else None
        ),
    )
    if binding.agent_id != TARGET_AGENT_ID:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"type": "assistant_context_rejected", "reason": "invalid-binding"},
        )
    if creation_scope:
        assert binding.creation_draft_id is not None
        _verify_local_creation_scope(
            session,
            draft_id=binding.creation_draft_id,
            snapshot=snapshot,
        )
    elif library_scope:
        if binding.novel_id is not None:
            snapshot_novel = snapshot.get("novel")
            if (
                not isinstance(snapshot_novel, Mapping)
                or snapshot_novel.get("id") != binding.novel_id
            ):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail={"type": "assistant_context_rejected", "reason": "invalid-binding"},
                )
            _verify_local_novel_scope(
                session,
                novel_id=binding.novel_id,
                document_id=None,
            )
    else:
        assert binding.novel_id is not None
        _verify_local_novel_scope(
            session,
            novel_id=binding.novel_id,
            document_id=binding.document_id,
        )

    try:
        created = assistant_context_registry.create(
            binding=binding,
            snapshot=snapshot,
            request_body_size=len(raw),
            runtime_app=request.app,
        )
    except ContextRefCreateError as error:
        raise _creation_error(error) from None

    expires_at = created.expires_at.isoformat().replace("+00:00", "Z")
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        headers={"Cache-Control": "no-store"},
        content={
            "contextRef": created.context_ref,
            "writingActionId": str(created.writing_action_id),
            "expiresAt": expires_at,
            "contextRevision": created.context_revision,
            "payloadCharacters": created.payload_characters,
        },
    )


__all__ = ["assistant_context_registry", "router"]
