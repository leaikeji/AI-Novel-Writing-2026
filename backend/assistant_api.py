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
from .services import NotFoundError, get_document, get_novel


router = APIRouter()
assistant_context_registry = AssistantContextRefRegistry()


_REQUIRED_CREATE_KEYS = frozenset(
    {"ownerToken", "tabInstance", "agentId", "novelId", "snapshot"},
)
_OPTIONAL_CREATE_KEYS = frozenset({"documentId", "sessionId"})


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
    if not _REQUIRED_CREATE_KEYS <= keys or not keys <= (
        _REQUIRED_CREATE_KEYS | _OPTIONAL_CREATE_KEYS
    ):
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


def _verify_local_scope(
    session: Session,
    *,
    novel_id: str,
    document_id: str | None,
) -> None:
    """Verify local database membership without accepting a model scope."""

    try:
        novel_uuid = UUID(novel_id)
        get_novel(session, novel_uuid)
        if document_id is not None:
            document = get_document(session, UUID(document_id))
            if str(document.get("novel_id") or "") != novel_id:
                raise NotFoundError("document is outside the selected novel")
    except (ValueError, NotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"type": "assistant_context_scope_unavailable"},
        ) from None


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

    binding = ContextRefBinding(
        owner_token=_required_string(payload, "ownerToken"),
        tab_instance=_required_string(payload, "tabInstance"),
        agent_id=_required_string(payload, "agentId"),
        novel_id=_required_string(payload, "novelId"),
        document_id=_optional_string(payload, "documentId"),
        session_id=_optional_string(payload, "sessionId"),
    )
    if binding.agent_id != TARGET_AGENT_ID:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"type": "assistant_context_rejected", "reason": "invalid-binding"},
        )
    _verify_local_scope(
        session,
        novel_id=binding.novel_id,
        document_id=binding.document_id,
    )

    try:
        created = assistant_context_registry.create(
            binding=binding,
            snapshot=snapshot,
            request_body_size=len(raw),
        )
    except ContextRefCreateError as error:
        raise _creation_error(error) from None

    expires_at = created.expires_at.isoformat().replace("+00:00", "Z")
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        headers={"Cache-Control": "no-store"},
        content={
            "contextRef": created.context_ref,
            "expiresAt": expires_at,
            "contextRevision": created.context_revision,
            "payloadCharacters": created.payload_characters,
        },
    )


__all__ = ["assistant_context_registry", "router"]
