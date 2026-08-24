"""FastAPI dependencies for the single novel-generation runtime path."""

from __future__ import annotations

from dataclasses import replace

from fastapi import Depends, HTTPException, Request, status
from qwenpaw.pawapp import get_ctx

from .model_runtime import (
    NOVEL_AGENT_ID,
    ModelAudit,
    ModelVerificationError,
    effective_model_audit,
)


async def get_novel_generation_ctx(ctx=Depends(get_ctx)):
    """Return a per-request PawApp context forced to the novel Agent."""

    return replace(ctx, agent_id=NOVEL_AGENT_ID)


async def get_novel_effective_model(request: Request) -> ModelAudit:
    """Resolve the novel Agent's effective model through QwenPaw's public API."""

    try:
        return await effective_model_audit(request.app, agent_id=NOVEL_AGENT_ID)
    except ModelVerificationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"type": "generation_model_unavailable", "message": str(error)},
        ) from error
