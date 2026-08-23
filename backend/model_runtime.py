"""Runtime model verification for every AI-assisted writing operation.

QwenPaw's PawApp context currently exposes a placeholder ``ctx.config`` value,
so model identity must be resolved from the agent profile before a call and from
the provider usage metadata attached to the completed reply after a call.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable


MINIMAX_M3_MODEL_ID = "MiniMax-M3"


class ModelVerificationError(RuntimeError):
    """Raised when a generation cannot be proven to have used MiniMax M3."""


def _normalized_model_id(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def is_minimax_m3(value: str | None) -> bool:
    """Return true only for the exact MiniMax M3 model family identifier."""

    return _normalized_model_id(value) == "minimaxm3"


@dataclass(frozen=True)
class ModelAudit:
    provider_id: str
    model_id: str
    source: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None

    def ensure_minimax_m3(self) -> "ModelAudit":
        if not is_minimax_m3(self.model_id):
            raise ModelVerificationError(
                "当前实际模型不是 MiniMax M3，生成结果已作废："
                f"{self.provider_id or 'unknown'}/{self.model_id or 'unknown'}"
            )
        return self

    def ensure_matches(self, configured: "ModelAudit") -> "ModelAudit":
        """Reject a reply if the provider/model changed after preflight."""

        if (
            self.provider_id != configured.provider_id
            or _normalized_model_id(self.model_id)
            != _normalized_model_id(configured.model_id)
        ):
            raise ModelVerificationError(
                "本次回复模型与调用前活动模型不一致，生成结果已作废："
                f"configured={configured.provider_id}/{configured.model_id}, "
                f"actual={self.provider_id}/{self.model_id}"
            )
        return self

    @property
    def fingerprint(self) -> str:
        parts = [
            "qwenpaw",
            self.source,
            self.provider_id or "unknown",
            self.model_id or "unknown",
        ]
        if self.prompt_tokens is not None:
            parts.append(f"in={self.prompt_tokens}")
        if self.completion_tokens is not None:
            parts.append(f"out={self.completion_tokens}")
        return ":".join(parts)[:160]


def configured_model_audit(agent_id: str) -> ModelAudit:
    """Read the authoritative QwenPaw agent-scoped model configuration."""

    try:
        # Imported lazily because the standalone test environment intentionally
        # contains only this PawApp's dependencies, while QwenPaw injects its
        # package in the production runtime.
        from qwenpaw.config.config import load_agent_config

        config = load_agent_config(agent_id)
        slot = getattr(config, "active_model", None)
        provider_id = str(getattr(slot, "provider_id", "") or "").strip()
        model_id = str(getattr(slot, "model", "") or "").strip()
    except Exception as error:  # pragma: no cover - production runtime boundary
        raise ModelVerificationError(
            f"无法读取 AI 小说作家活动模型：{type(error).__name__}: {error}"
        ) from error
    if not provider_id or not model_id:
        raise ModelVerificationError("AI 小说作家尚未配置活动模型")
    return ModelAudit(
        provider_id=provider_id,
        model_id=model_id,
        source="agent-config",
    ).ensure_minimax_m3()


def _iter_metadata_dicts(value: Any) -> Iterable[dict[str, Any]]:
    """Yield nested metadata dictionaries without traversing arbitrary objects."""

    stack: list[tuple[Any, int]] = [(value, 0)]
    seen: set[int] = set()
    while stack:
        current, depth = stack.pop()
        if current is None or depth > 8:
            continue
        marker = id(current)
        if marker in seen:
            continue
        seen.add(marker)
        if isinstance(current, dict):
            yield current
            stack.extend((item, depth + 1) for item in current.values())
            continue
        if isinstance(current, (list, tuple)):
            stack.extend((item, depth + 1) for item in current)
            continue
        for attribute in ("metadata", "output", "content"):
            nested = getattr(current, attribute, None)
            if nested is not None:
                stack.append((nested, depth + 1))


def reply_model_audit(reply: Any, *, session_id: str | None = None) -> ModelAudit:
    """Resolve the actual provider/model recorded by QwenPaw for one reply.

    The token recording wrapper stores ``provider_id`` and ``model_name`` under
    ``qwenpaw_turn_usage.usage`` on the closing assistant message. We search the
    raw PawApp reply chunks because the convenience ``reply.text`` intentionally
    discards metadata.
    """

    chunks = getattr(reply, "chunks", None)
    for metadata in _iter_metadata_dicts(chunks):
        audit = _audit_from_usage(metadata, source="provider-usage")
        if audit is not None:
            return audit.ensure_minimax_m3()
    if session_id:
        try:
            from qwenpaw.token_usage.model_wrapper import TokenRecordingModelWrapper

            buffered_usage = TokenRecordingModelWrapper.pop_usage_for_session(
                session_id
            )
        except Exception:  # pragma: no cover - production runtime boundary
            buffered_usage = None
        audit = _audit_from_usage(
            buffered_usage,
            source="provider-usage-buffer",
        )
        if audit is not None:
            return audit.ensure_minimax_m3()
    raise ModelVerificationError(
        "QwenPaw 回复缺少实际 provider/model 用量元数据，生成结果已作废"
    )


def _audit_from_usage(
    metadata: dict[str, Any] | None,
    *,
    source: str,
) -> ModelAudit | None:
    if metadata:
        provider_id = str(metadata.get("provider_id") or "").strip()
        model_id = str(
            metadata.get("model_name") or metadata.get("model_id") or ""
        ).strip()
        if not provider_id or not model_id:
            return None
        prompt_tokens = _optional_int(metadata.get("prompt_tokens"))
        completion_tokens = _optional_int(metadata.get("completion_tokens"))
        total_tokens = _optional_int(metadata.get("total_tokens"))
        if prompt_tokens is None and completion_tokens is None and total_tokens is None:
            return None
        return ModelAudit(
            provider_id=provider_id,
            model_id=model_id,
            source=source,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
    return None


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def parse_model_json(text: str) -> dict[str, Any]:
    """Parse a strict JSON object while tolerating one surrounding code fence."""

    candidate = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate, re.DOTALL)
    if fenced:
        candidate = fenced.group(1).strip()
    try:
        payload = json.loads(candidate)
        if isinstance(payload, list):
            return {"items": payload}
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for index, character in enumerate(candidate):
        if character not in "[{":
            continue
        try:
            payload, _ = decoder.raw_decode(candidate[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, list):
            return {"items": payload}
        if isinstance(payload, dict):
            return payload
    raise ModelVerificationError("MiniMax M3 没有返回可解析的 JSON 对象")
