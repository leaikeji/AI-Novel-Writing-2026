"""Disabled-by-default, non-persistent writing evaluation runtime."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import hmac
import os
from pathlib import Path
import time
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status

from .generation_dependencies import (
    get_novel_effective_model,
    get_novel_generation_ctx,
)
from .model_runtime import (
    NOVEL_AGENT_ID,
    ModelAudit,
    ModelVerificationError,
    ensure_prompt_within_effective_limit,
    reply_final_text,
    reply_model_audit,
)
from .writing_eval_contract import (
    CANDIDATE_OVERLAY_SHA256,
    EXPERIMENT_ID,
    MANIFEST_SHA256,
    PROMPT_CONTRACT_VERSION,
    RIGHTS_BASIS,
    RUBRIC_SHA256,
    SCHEMA_VERSION,
    SOURCE_SUITE_SHA256,
    WritingEvalContractError,
    build_sample,
    deterministic_output_checks,
    experiment_contract,
    sha256_text,
)


WRITING_EVAL_ENABLED_ENV = "AI_NOVEL_WRITING_EVAL_ENABLED"
WRITING_EVAL_HEADER = "X-AI-Novel-Writing-Eval"
WRITING_EVAL_TIMEOUT_SECONDS = 600.0
_SKILL_ID = "prose-writing"
_RUN_LOCK = asyncio.Lock()

router = APIRouter(prefix="/research/writing-evaluations", tags=["research"])


class WritingEvalTimeoutError(TimeoutError):
    """Raised when a bounded research generation does not return in time."""


def _enabled() -> bool:
    return os.environ.get(WRITING_EVAL_ENABLED_ENV, "false").strip().lower() == "true"


def require_writing_eval_enabled(
    experiment_header: str | None = Header(default=None, alias=WRITING_EVAL_HEADER),
) -> None:
    """Require a short-lived local research opt-in and exact experiment intent."""

    if not _enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if experiment_header is None or not hmac.compare_digest(
        experiment_header, EXPERIMENT_ID
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"type": "writing_evaluation_not_authorized"},
        )


def _contract_error(error: WritingEvalContractError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"type": error.code, "message": str(error)},
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _consume_cancelled_task(task: asyncio.Task[Any]) -> None:
    try:
        task.result()
    except BaseException:
        pass


async def _await_reply(awaitable: Any) -> Any:
    task = asyncio.create_task(awaitable)
    try:
        done, _ = await asyncio.wait({task}, timeout=WRITING_EVAL_TIMEOUT_SECONDS)
        if task in done:
            return task.result()
        task.cancel()
        task.add_done_callback(_consume_cancelled_task)
        raise WritingEvalTimeoutError(
            f"写作研究样本等待超过 {int(WRITING_EVAL_TIMEOUT_SECONDS)} 秒"
        )
    except BaseException:
        if not task.done():
            task.cancel()
            task.add_done_callback(_consume_cancelled_task)
        raise


def _strict_public_usage(reply: Any) -> dict[str, Any]:
    """Return strict usage from a closing assistant message in raw reply chunks."""

    chunks = getattr(reply, "chunks", None)
    if not isinstance(chunks, (list, tuple)) or not chunks:
        raise ModelVerificationError(
            "模型身份未核验：研究运行器要求结构化 PawApp reply chunks"
        )
    for chunk in reversed(chunks):
        output = getattr(chunk, "output", None)
        if not isinstance(output, (list, tuple)) or not output:
            continue
        closing = output[-1]
        role = getattr(closing, "role", None)
        if not isinstance(role, str) or role.lower() not in {"assistant", "model"}:
            continue
        metadata = getattr(closing, "metadata", None)
        if not isinstance(metadata, dict):
            continue
        envelope = metadata.get("qwenpaw_turn_usage")
        usage = envelope.get("usage") if isinstance(envelope, dict) else None
        if not isinstance(usage, dict):
            continue
        provider_id = usage.get("provider_id")
        model_id = usage.get("model_name") or usage.get("model_id")
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise ModelVerificationError("模型身份未核验：actual provider 无效")
        if not isinstance(model_id, str) or not model_id.strip():
            raise ModelVerificationError("模型身份未核验：actual model 无效")
        token_values = {
            name: usage.get(name)
            for name in ("prompt_tokens", "completion_tokens", "total_tokens")
        }
        for name, value in token_values.items():
            if value is not None and (type(value) is not int or value < 0):
                raise ModelVerificationError(f"模型用量元数据无效：{name}")
        if all(value is None for value in token_values.values()):
            raise ModelVerificationError("模型身份未核验：回复没有可用 token 用量")
        return usage
    raise ModelVerificationError(
        "模型身份未核验：closing assistant message 缺少 provider usage"
    )


def _skill_sha256() -> str:
    path = Path(__file__).resolve().parents[1] / "skills" / _SKILL_ID / "SKILL.md"
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise ModelVerificationError("研究运行器无法读取固定 prose-writing Skill") from error
    return hashlib.sha256(payload).hexdigest()


def _model_payload(audit: ModelAudit) -> dict[str, Any]:
    return {
        "provider_id": audit.provider_id,
        "model_id": audit.model_id,
        "source": audit.source,
        "agent_id": audit.agent_id,
        "effective_max_input_length": audit.effective_max_input_length,
    }


@router.get("/{experiment_id}", dependencies=[Depends(require_writing_eval_enabled)])
def writing_evaluation_contract_get(
    experiment_id: str, response: Response
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    try:
        return experiment_contract(experiment_id)
    except WritingEvalContractError as error:
        raise _contract_error(error) from error


@router.post(
    "/{experiment_id}/samples/{sample_id}/generate",
    dependencies=[Depends(require_writing_eval_enabled)],
)
async def writing_evaluation_generate(
    experiment_id: str,
    sample_id: str,
    response: Response,
    ctx=Depends(get_novel_generation_ctx),
    configured_model: ModelAudit = Depends(get_novel_effective_model),
) -> dict[str, Any]:
    """Generate one registered sample without touching novel persistence."""

    response.headers["Cache-Control"] = "no-store"
    try:
        sample = build_sample(experiment_id, sample_id)
    except WritingEvalContractError as error:
        raise _contract_error(error) from error
    if _RUN_LOCK.locked():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"type": "writing_evaluation_busy"},
        )

    session_id = (
        f"novel-writing-eval:{EXPERIMENT_ID}:{sample.sample_id}:{uuid4()}"
    )
    started_at = _utc_now()
    started_monotonic = time.monotonic()
    actual_model: ModelAudit | None = None
    try:
        async with _RUN_LOCK:
            ensure_prompt_within_effective_limit(sample.prompt, configured_model)
            reply = await _await_reply(
                ctx.chat(
                    sample.prompt,
                    skill=_SKILL_ID,
                    session_id=session_id,
                )
            )
            _strict_public_usage(reply)
            # Deliberately omit session_id: research evidence may only use the
            # raw public PawApp reply, never QwenPaw's internal usage buffer.
            actual_model = reply_model_audit(reply)
            actual_model.ensure_matches(configured_model)
            final_text = reply_final_text(reply)
    except WritingEvalTimeoutError as error:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={"type": "writing_evaluation_timed_out", "sample_id": sample_id},
        ) from error
    except ModelVerificationError as error:
        detail: dict[str, Any] = {
            "type": "writing_evaluation_model_verification_failed",
            "sample_id": sample_id,
            "message": str(error),
        }
        if actual_model is not None:
            detail["actual_model"] = _model_payload(actual_model)
            detail["usage"] = {
                "prompt_tokens": actual_model.prompt_tokens,
                "completion_tokens": actual_model.completion_tokens,
                "total_tokens": actual_model.total_tokens,
            }
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=detail,
        ) from error
    except asyncio.CancelledError:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "type": "writing_evaluation_provider_failed",
                "sample_id": sample_id,
                "error_class": type(error).__name__,
            },
        ) from error

    finished_at = _utc_now()
    duration_ms = max(0, round((time.monotonic() - started_monotonic) * 1000))
    assert actual_model is not None
    return {
        "schema_version": SCHEMA_VERSION,
        "state": "generated",
        "experiment_id": EXPERIMENT_ID,
        "sample_id": sample.sample_id,
        "case_id": sample.case_id,
        "variant": sample.variant,
        "attempt": sample.attempt,
        "rights_basis": RIGHTS_BASIS,
        "execution_agent_id": NOVEL_AGENT_ID,
        "skill_id": _SKILL_ID,
        "skill_sha256": _skill_sha256(),
        "source_suite_sha256": SOURCE_SUITE_SHA256,
        "manifest_sha256": MANIFEST_SHA256,
        "rubric_sha256": RUBRIC_SHA256,
        "prompt_contract": PROMPT_CONTRACT_VERSION,
        "candidate_overlay_sha256": CANDIDATE_OVERLAY_SHA256,
        "base_prompt_sha256": sha256_text(sample.base_prompt),
        "prompt_sha256": sha256_text(sample.prompt),
        "requested_model": _model_payload(configured_model),
        "actual_model": _model_payload(actual_model),
        "usage": {
            "prompt_tokens": actual_model.prompt_tokens,
            "completion_tokens": actual_model.completion_tokens,
            "total_tokens": actual_model.total_tokens,
        },
        "sampling_parameters": "not_exposed",
        "session_id": session_id,
        "started_at": _iso(started_at),
        "finished_at": _iso(finished_at),
        "duration_ms": duration_ms,
        "final_text_source": "structured_reply_chunks",
        "output_text": final_text,
        "output_sha256": sha256_text(final_text),
        "deterministic_checks": deterministic_output_checks(
            sample.case_id, final_text
        ),
        "server_persistence": "none",
    }
