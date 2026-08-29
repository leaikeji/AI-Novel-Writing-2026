"""FastAPI dependencies for the single novel-generation runtime path."""

from __future__ import annotations

from dataclasses import replace
import time
from typing import Awaitable, Callable

from fastapi import Depends, HTTPException, Request, status
from qwenpaw.pawapp import get_ctx

from .model_runtime import (
    NOVEL_AGENT_ID,
    ModelAudit,
    ModelVerificationError,
    effective_model_audit,
)
from .model_execution import (
    ModelExecutionEvidenceStatus,
    ModelExecutionEvidenceV2,
    ModelExecutionRejectionReason,
    ModelIdentity,
    determine_model_execution_evidence,
    rejected_model_execution_evidence,
)


EffectiveModelProbe = Callable[[], Awaitable[ModelAudit]]


class NovelModelEvidenceRejected(ModelVerificationError):
    def __init__(self, message: str, evidence: ModelExecutionEvidenceV2) -> None:
        super().__init__(message)
        self.evidence = evidence


def _identity(audit: ModelAudit) -> ModelIdentity:
    return ModelIdentity(provider_id=audit.provider_id, model_id=audit.model_id)


def failed_novel_model_evidence(
    configured: ModelAudit,
    *,
    started_monotonic: float,
) -> ModelExecutionEvidenceV2:
    return rejected_model_execution_evidence(
        preflight_identity=_identity(configured),
        postflight_identity=None,
        agent_id=NOVEL_AGENT_ID,
        duration_ms=max(0, round((time.monotonic() - started_monotonic) * 1000)),
        reason=ModelExecutionRejectionReason.EXECUTION_FAILED,
        preflight_source=configured.source,
        effective_max_input_length=configured.effective_max_input_length,
    )


async def verify_novel_model_reply(
    reply: object,
    *,
    configured: ModelAudit,
    probe: EffectiveModelProbe,
    started_monotonic: float,
) -> ModelExecutionEvidenceV2:
    """Verify one Agent reply using only public pre/post/closing metadata."""

    try:
        # Direct unit calls bypass FastAPI dependency resolution and therefore
        # receive a ``Depends`` marker. Runtime HTTP calls always receive the
        # public probe; use the supplied preflight only for that test boundary.
        postflight = await probe() if callable(probe) else configured
    except Exception as error:
        evidence = rejected_model_execution_evidence(
            preflight_identity=_identity(configured),
            postflight_identity=None,
            agent_id=NOVEL_AGENT_ID,
            duration_ms=max(
                0, round((time.monotonic() - started_monotonic) * 1000)
            ),
            reason=ModelExecutionRejectionReason.POSTFLIGHT_UNAVAILABLE,
            preflight_source=configured.source,
            effective_max_input_length=configured.effective_max_input_length,
        )
        raise NovelModelEvidenceRejected(
            "模型调用完成，但无法通过公开接口完成调用后模型核验",
            evidence,
        ) from error
    evidence = determine_model_execution_evidence(
        preflight_identity=_identity(configured),
        postflight_identity=_identity(postflight),
        reply_chunks=getattr(reply, "chunks", None),
        agent_id=NOVEL_AGENT_ID,
        duration_ms=max(0, round((time.monotonic() - started_monotonic) * 1000)),
        preflight_source=configured.source,
        postflight_source=postflight.source,
        effective_max_input_length=configured.effective_max_input_length,
    )
    if evidence.status is ModelExecutionEvidenceStatus.REJECTED:
        reason = evidence.rejection_reason.value if evidence.rejection_reason else "rejected"
        message_by_reason = {
            ModelExecutionRejectionReason.PROVIDER_USAGE_IDENTITY_MISMATCH.value: (
                "公开 usage 报告的模型与调用前活动模型不一致："
                "provider_usage_identity_mismatch"
            ),
            ModelExecutionRejectionReason.PREFLIGHT_POSTFLIGHT_IDENTITY_MISMATCH.value: (
                "调用期间活动模型发生变化"
            ),
            ModelExecutionRejectionReason.PUBLIC_USAGE_MALFORMED.value: (
                "宿主公开的 usage 信息格式不完整"
            ),
        }
        raise NovelModelEvidenceRejected(
            message_by_reason.get(reason, f"模型公开证据核验失败：{reason}"),
            evidence,
        )
    return evidence


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


def get_novel_effective_model_probe(request: Request) -> EffectiveModelProbe:
    """Return a public postflight probe bound to the current host app."""

    async def probe() -> ModelAudit:
        return await effective_model_audit(request.app, agent_id=NOVEL_AGENT_ID)

    return probe
