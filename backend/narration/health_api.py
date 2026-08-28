"""Hidden, exact-scope health observation for the T4 validation controller."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import os
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from .pawapp_runtime import get_ready_narration_adapter
from .production_runtime import (
    PRODUCT_ENABLE_ENV,
    VALIDATION_ENABLE_ENV,
    ValidationSegmentClaimGateSnapshot,
    ValidationRuntimeScope,
    arm_validation_segment_claim_gate,
    current_validation_runtime_scope,
    read_validation_segment_claim_gate,
    release_validation_segment_claim_gate,
)
from .release_gate import require_narration_t4_http_access
from .runtime import SidecarRuntimeError


def _canonical_uuid(value: object) -> object:
    if type(value) is not str:
        raise ValueError("identity must be canonical")
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise ValueError("identity must be canonical") from error
    if str(parsed) != value:
        raise ValueError("identity must be canonical")
    return value


CanonicalUuid = Annotated[UUID, BeforeValidator(_canonical_uuid)]


class ValidationObservationResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_ready: bool = Field(strict=True)
    worker_ready: bool = Field(strict=True)
    active_syntheses: int = Field(ge=0, le=1, strict=True)
    queued_jobs: int = Field(ge=0, le=0, strict=True)
    observed_at: datetime


class ValidationSegmentClaimGateArmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: CanonicalUuid
    segment_claim_limit: int = Field(default=1, ge=1, le=16, strict=True)
    ttl_seconds: int = Field(default=120, ge=1, le=300, strict=True)


class ValidationSegmentClaimGateReleaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: CanonicalUuid


class ValidationSegmentClaimGateResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^VALIDATION_SEGMENT_CLAIM_GATE_[A-Z_]+$")
    state: Literal["default_allow", "armed", "paused"]
    claim_limit: int = Field(ge=0, le=16, strict=True)
    claimed_count: int = Field(ge=0, le=16, strict=True)
    remaining_count: int = Field(ge=0, le=16, strict=True)
    expires_at: datetime | None
    run_fingerprint_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    scope_fingerprint_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "RESOURCE_NOT_FOUND",
            "message": "找不到请求的朗读资源。",
        },
        headers={"Cache-Control": "no-store"},
    )


def _require_exact_validation_scope(
    novel_id: CanonicalUuid,
    document_id: CanonicalUuid,
) -> ValidationRuntimeScope:
    scope = current_validation_runtime_scope()
    if (
        scope is None
        or not scope.active()
        or scope.novel_id != novel_id
        or scope.document_id != document_id
    ):
        raise _not_found()
    return scope


def _require_hidden_validation_mode() -> None:
    if (
        os.environ.get(PRODUCT_ENABLE_ENV, "false") != "false"
        or os.environ.get(VALIDATION_ENABLE_ENV, "false") != "true"
    ):
        raise _not_found()


def _claim_gate_resource(
    snapshot: ValidationSegmentClaimGateSnapshot,
) -> ValidationSegmentClaimGateResource:
    return ValidationSegmentClaimGateResource(**asdict(snapshot))


def _claim_gate_error(error: RuntimeError) -> HTTPException:
    code = getattr(error, "code", None)
    if code == "TTS_VALIDATION_CLAIM_GATE_SCOPE_INVALID":
        return _not_found()
    if type(code) is not str or not code.startswith("TTS_VALIDATION_CLAIM_GATE_"):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "VALIDATION_SEGMENT_CLAIM_GATE_UNAVAILABLE",
                "message": "朗读验证 claim gate 暂不可用。",
            },
            headers={"Cache-Control": "no-store"},
        )
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": code,
            "message": "朗读验证 claim gate 状态冲突。",
        },
        headers={"Cache-Control": "no-store"},
    )


router = APIRouter(
    dependencies=[
        Depends(require_narration_t4_http_access),
        Depends(_require_hidden_validation_mode),
    ]
)


@router.get(
    "/novels/{novel_id}/documents/{document_id}/narration-validation-observation",
    response_model=ValidationObservationResource,
)
async def read_validation_observation(
    novel_id: CanonicalUuid,
    document_id: CanonicalUuid,
    response: Response,
    _scope: ValidationRuntimeScope = Depends(_require_exact_validation_scope),
) -> ValidationObservationResource:
    del _scope
    adapter = get_ready_narration_adapter()
    if adapter is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "VALIDATION_OBSERVATION_UNAVAILABLE",
                "message": "朗读验证观测暂不可用。",
            },
            headers={"Cache-Control": "no-store"},
        )
    try:
        metrics = await adapter.observe_validation_metrics()
    except (SidecarRuntimeError, OSError, TimeoutError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "VALIDATION_OBSERVATION_UNAVAILABLE",
                "message": "朗读验证观测暂不可用。",
            },
            headers={"Cache-Control": "no-store"},
        ) from error
    response.headers["Cache-Control"] = "no-store"
    return ValidationObservationResource(
        model_ready=metrics.model_ready,
        worker_ready=metrics.worker_ready,
        active_syntheses=metrics.active_syntheses,
        queued_jobs=metrics.queued_jobs,
        observed_at=datetime.now(timezone.utc),
    )


_CLAIM_GATE_PATH = (
    "/novels/{novel_id}/documents/{document_id}"
    "/narration-validation-segment-claim-gate"
)


@router.get(
    _CLAIM_GATE_PATH,
    response_model=ValidationSegmentClaimGateResource,
    include_in_schema=False,
)
async def read_validation_segment_claim_gate_state(
    novel_id: CanonicalUuid,
    document_id: CanonicalUuid,
    response: Response,
    _scope: ValidationRuntimeScope = Depends(_require_exact_validation_scope),
) -> ValidationSegmentClaimGateResource:
    del _scope
    try:
        snapshot = read_validation_segment_claim_gate(
            novel_id=novel_id,
            document_id=document_id,
        )
    except RuntimeError as error:
        raise _claim_gate_error(error) from error
    response.headers["Cache-Control"] = "no-store"
    return _claim_gate_resource(snapshot)


@router.post(
    _CLAIM_GATE_PATH,
    response_model=ValidationSegmentClaimGateResource,
    include_in_schema=False,
)
async def arm_validation_segment_claim_gate_state(
    novel_id: CanonicalUuid,
    document_id: CanonicalUuid,
    request: ValidationSegmentClaimGateArmRequest,
    response: Response,
    _scope: ValidationRuntimeScope = Depends(_require_exact_validation_scope),
) -> ValidationSegmentClaimGateResource:
    del _scope
    try:
        snapshot = arm_validation_segment_claim_gate(
            run_id=request.run_id,
            novel_id=novel_id,
            document_id=document_id,
            ttl_seconds=request.ttl_seconds,
            claim_limit=request.segment_claim_limit,
        )
    except RuntimeError as error:
        raise _claim_gate_error(error) from error
    response.headers["Cache-Control"] = "no-store"
    return _claim_gate_resource(snapshot)


@router.post(
    f"{_CLAIM_GATE_PATH}/release",
    response_model=ValidationSegmentClaimGateResource,
    include_in_schema=False,
)
async def release_validation_segment_claim_gate_state(
    novel_id: CanonicalUuid,
    document_id: CanonicalUuid,
    request: ValidationSegmentClaimGateReleaseRequest,
    response: Response,
    _scope: ValidationRuntimeScope = Depends(_require_exact_validation_scope),
) -> ValidationSegmentClaimGateResource:
    del _scope
    try:
        snapshot = release_validation_segment_claim_gate(
            run_id=request.run_id,
            novel_id=novel_id,
            document_id=document_id,
        )
    except RuntimeError as error:
        raise _claim_gate_error(error) from error
    response.headers["Cache-Control"] = "no-store"
    return _claim_gate_resource(snapshot)


__all__ = [
    "ValidationObservationResource",
    "ValidationSegmentClaimGateArmRequest",
    "ValidationSegmentClaimGateReleaseRequest",
    "ValidationSegmentClaimGateResource",
    "router",
]
