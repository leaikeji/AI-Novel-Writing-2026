"""Disabled-by-default, non-persistent writing evaluation runtime."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timezone
import hashlib
import hmac
import os
from pathlib import Path
import re
import time
from typing import Any
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Request,
    Response,
    status,
)

from .generation_dependencies import (
    get_novel_effective_model,
    get_novel_generation_ctx,
)
from .model_runtime import (
    NOVEL_AGENT_ID,
    ModelAudit,
    ModelVerificationError,
    effective_model_audit,
    ensure_prompt_within_effective_limit,
    reply_final_text,
    reply_model_audit,
)
from .writing_eval_contract import (
    ACTUAL_MODEL_POLICY,
    CANDIDATE_OVERLAY_SHA256,
    EXPERIMENT_ID,
    MANIFEST_SHA256,
    MODEL_EVIDENCE_CONTRACT_VERSION,
    OUTPUT_PURITY_CONTRACT_VERSION,
    PROMPT_CONTRACT_VERSION,
    RIGHTS_BASIS,
    RUBRIC_SHA256,
    SCHEMA_VERSION,
    SKILL_SELECTION_ENFORCEMENT,
    SOURCE_SUITE_SHA256,
    STREAM_DIAGNOSTIC_CONTRACT_VERSION,
    TOOL_POLICY_ENFORCEMENT,
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
_DIAGNOSTIC_LABEL = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_DIAGNOSTIC_MAX_LABELS = 32

router = APIRouter(prefix="/research/writing-evaluations", tags=["research"])


class WritingEvalTimeoutError(TimeoutError):
    """Raised when a bounded research generation does not return in time."""


class _ObservedReply:
    """Minimal public-reply shape consumed by the existing audit helpers."""

    def __init__(self, chunks: list[Any]) -> None:
        self.chunks = tuple(chunks)


def _field(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _diagnostic_label(value: Any, *, fallback: str) -> str:
    candidates = (value, fallback)
    for candidate in candidates:
        if not isinstance(candidate, str):
            candidate = getattr(candidate, "value", None)
        if isinstance(candidate, str):
            normalized = candidate.strip().lower()
            if _DIAGNOSTIC_LABEL.fullmatch(normalized):
                return normalized
    return "unknown"


def _increment_bounded(counter: dict[str, int], label: str) -> None:
    if label not in counter and len(counter) >= _DIAGNOSTIC_MAX_LABELS:
        label = "other"
    counter[label] = counter.get(label, 0) + 1


class _StreamDiagnostics:
    """Collect content-free event structure from one public chat stream."""

    def __init__(self, *, started_monotonic: float) -> None:
        self.started_monotonic = started_monotonic
        self.event_count = 0
        self.first_event_elapsed_ms: int | None = None
        self.last_event_elapsed_ms: int | None = None
        self.event_type_counts: dict[str, int] = {}
        self.message_role_counts: dict[str, int] = {}
        self.message_type_counts: dict[str, int] = {}
        self.content_part_type_counts: dict[str, int] = {}
        self.stream_completed = False

    def observe(self, event: Any) -> None:
        elapsed_ms = max(
            0, round((time.monotonic() - self.started_monotonic) * 1000)
        )
        if self.first_event_elapsed_ms is None:
            self.first_event_elapsed_ms = elapsed_ms
        self.last_event_elapsed_ms = elapsed_ms
        self.event_count += 1
        _increment_bounded(
            self.event_type_counts,
            _diagnostic_label(
                _field(event, "type"), fallback=type(event).__name__.lower()
            ),
        )
        output = _field(event, "output")
        messages = output if isinstance(output, (list, tuple)) else (event,)
        for message in messages:
            role = _field(message, "role")
            message_type = _field(message, "type")
            if role is not None:
                _increment_bounded(
                    self.message_role_counts,
                    _diagnostic_label(role, fallback="unknown"),
                )
            if message_type is not None:
                _increment_bounded(
                    self.message_type_counts,
                    _diagnostic_label(message_type, fallback="unknown"),
                )
            content = _field(message, "content")
            parts = content if isinstance(content, (list, tuple)) else (content,)
            for part in parts:
                if part is None or isinstance(part, str):
                    continue
                part_type = _field(part, "type")
                _increment_bounded(
                    self.content_part_type_counts,
                    _diagnostic_label(part_type, fallback="unknown"),
                )

    def snapshot(self) -> dict[str, Any]:
        return {
            "contract": STREAM_DIAGNOSTIC_CONTRACT_VERSION,
            "content_recorded": False,
            "stream_completed": self.stream_completed,
            "event_count": self.event_count,
            "first_event_elapsed_ms": self.first_event_elapsed_ms,
            "last_event_elapsed_ms": self.last_event_elapsed_ms,
            "event_type_counts": dict(sorted(self.event_type_counts.items())),
            "message_role_counts": dict(sorted(self.message_role_counts.items())),
            "message_type_counts": dict(sorted(self.message_type_counts.items())),
            "content_part_type_counts": dict(
                sorted(self.content_part_type_counts.items())
            ),
        }


async def _collect_stream_reply(
    stream: AsyncIterator[Any], diagnostics: _StreamDiagnostics
) -> _ObservedReply:
    chunks: list[Any] = []
    async for event in stream:
        diagnostics.observe(event)
        chunks.append(event)
    diagnostics.stream_completed = True
    return _ObservedReply(chunks)


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


def _public_usage(
    reply: Any, *, required: bool
) -> dict[str, Any] | None:
    """Return validated public usage, or ``None`` when it is not exposed."""

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
        if "qwenpaw_turn_usage" not in metadata:
            continue
        envelope = metadata["qwenpaw_turn_usage"]
        if not isinstance(envelope, dict):
            raise ModelVerificationError("模型用量元数据无效：qwenpaw_turn_usage")
        usage = envelope.get("usage")
        if not isinstance(usage, dict):
            raise ModelVerificationError("模型用量元数据无效：usage")
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
    if required:
        raise ModelVerificationError(
            "模型身份未核验：closing assistant message 缺少 provider usage"
        )
    return None


def _strict_public_usage(reply: Any) -> dict[str, Any]:
    """Return strict usage from a closing assistant message in raw reply chunks."""

    usage = _public_usage(reply, required=True)
    assert usage is not None
    return usage


def _optional_public_usage(reply: Any) -> dict[str, Any] | None:
    """Keep missing public usage explicit without consulting private buffers."""

    return _public_usage(reply, required=False)


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


def _execution_diagnostics(
    *,
    session_id: str,
    started_at: datetime,
    configured_model: ModelAudit,
    stream: _StreamDiagnostics,
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "started_at": _iso(started_at),
        "timeout_seconds": WRITING_EVAL_TIMEOUT_SECONDS,
        "requested_model": _model_payload(configured_model),
        "skill_id": _SKILL_ID,
        "skill_selection_enforcement": SKILL_SELECTION_ENFORCEMENT,
        "tool_policy_enforcement": TOOL_POLICY_ENFORCEMENT,
        "stream_diagnostics": stream.snapshot(),
    }


def _postflight_model_probe(
    request: Request,
) -> Callable[[], Awaitable[ModelAudit]]:
    """Create a public effective-model probe that runs after the response stream."""

    async def probe() -> ModelAudit:
        return await effective_model_audit(request.app, agent_id=NOVEL_AGENT_ID)

    return probe


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
    postflight_model_probe: Callable[[], Awaitable[ModelAudit]] = Depends(
        _postflight_model_probe
    ),
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
    stream_diagnostics = _StreamDiagnostics(started_monotonic=started_monotonic)
    actual_model: ModelAudit | None = None
    postflight_model: ModelAudit | None = None
    try:
        async with _RUN_LOCK:
            ensure_prompt_within_effective_limit(sample.prompt, configured_model)
            reply = await _await_reply(
                _collect_stream_reply(
                    ctx.chat_stream(
                        sample.prompt,
                        skill=_SKILL_ID,
                        session_id=session_id,
                    ),
                    stream_diagnostics,
                )
            )
            final_text = reply_final_text(reply)
            postflight_model = await postflight_model_probe()
            postflight_model.ensure_matches(configured_model)
            public_usage = _optional_public_usage(reply)
            if public_usage is not None:
                # Deliberately omit session_id: research evidence may only use
                # public reply metadata, never QwenPaw's internal usage buffer.
                actual_model = reply_model_audit(reply)
                actual_model.ensure_matches(configured_model)
    except WritingEvalTimeoutError as error:
        diagnostics = _execution_diagnostics(
            session_id=session_id,
            started_at=started_at,
            configured_model=configured_model,
            stream=stream_diagnostics,
        )
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={
                "type": "writing_evaluation_timed_out",
                "sample_id": sample_id,
                **diagnostics,
            },
        ) from error
    except ModelVerificationError as error:
        detail: dict[str, Any] = {
            "type": "writing_evaluation_model_verification_failed",
            "sample_id": sample_id,
            "message": str(error),
            **_execution_diagnostics(
                session_id=session_id,
                started_at=started_at,
                configured_model=configured_model,
                stream=stream_diagnostics,
            ),
        }
        if actual_model is not None:
            detail["actual_model"] = _model_payload(actual_model)
            detail["usage"] = {
                "prompt_tokens": actual_model.prompt_tokens,
                "completion_tokens": actual_model.completion_tokens,
                "total_tokens": actual_model.total_tokens,
            }
        if postflight_model is not None:
            detail["postflight_model"] = _model_payload(postflight_model)
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
                **_execution_diagnostics(
                    session_id=session_id,
                    started_at=started_at,
                    configured_model=configured_model,
                    stream=stream_diagnostics,
                ),
            },
        ) from error

    finished_at = _utc_now()
    duration_ms = max(0, round((time.monotonic() - started_monotonic) * 1000))
    assert postflight_model is not None
    actual_model_status = (
        "verified_from_provider_usage" if actual_model is not None else "not_exposed"
    )
    usage_status = "exposed" if actual_model is not None else "not_exposed"
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
        "output_purity_contract": OUTPUT_PURITY_CONTRACT_VERSION,
        "candidate_overlay_sha256": CANDIDATE_OVERLAY_SHA256,
        "base_prompt_sha256": sha256_text(sample.base_prompt),
        "prompt_sha256": sha256_text(sample.prompt),
        "requested_model": _model_payload(configured_model),
        "postflight_model": _model_payload(postflight_model),
        "actual_model": (
            _model_payload(actual_model) if actual_model is not None else None
        ),
        "usage": (
            {
                "prompt_tokens": actual_model.prompt_tokens,
                "completion_tokens": actual_model.completion_tokens,
                "total_tokens": actual_model.total_tokens,
            }
            if actual_model is not None
            else None
        ),
        "model_evidence": {
            "contract": MODEL_EVIDENCE_CONTRACT_VERSION,
            "actual_model_policy": ACTUAL_MODEL_POLICY,
            "effective_model_pre_post_match": True,
            "actual_model_status": actual_model_status,
            "usage_status": usage_status,
            "private_usage_buffer_used": False,
        },
        "sampling_parameters": "not_exposed",
        "session_id": session_id,
        "started_at": _iso(started_at),
        "finished_at": _iso(finished_at),
        "duration_ms": duration_ms,
        "skill_selection_enforcement": SKILL_SELECTION_ENFORCEMENT,
        "tool_policy_enforcement": TOOL_POLICY_ENFORCEMENT,
        "stream_diagnostics": stream_diagnostics.snapshot(),
        "final_text_source": "structured_reply_chunks",
        "output_text": final_text,
        "output_sha256": sha256_text(final_text),
        "deterministic_checks": deterministic_output_checks(
            sample.case_id, final_text
        ),
        "server_persistence": "none",
    }
