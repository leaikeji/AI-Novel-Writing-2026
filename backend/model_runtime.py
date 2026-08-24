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

INTELLIGENCE_ITEM_TYPES = {
    "fact",
    "character_state",
    "relationship",
    "storyline_event",
    "foreshadow_progress",
    "foreshadow_new",
    "next_chapter_required_role",
}


class ModelVerificationError(RuntimeError):
    """Raised when a generation cannot be proven to have used MiniMax M3."""


def _repair_character_array_boundaries(candidate: str) -> str:
    """Close an item when a long ``characters`` array drops a boundary brace.

    MiniMax occasionally emits ``...details:{...},{\"name\":...`` instead of
    ``...details:{...}},{\"name\":...`` in an otherwise complete response.
    We only repair structural boundaries inside the named array and never
    touch quoted text.
    """

    match = re.search(r'"characters"\s*:\s*\[', candidate)
    if match is None:
        return candidate
    start = match.end()
    output = [candidate[:start]]
    index = start
    in_string = False
    escaped = False
    object_depth = 0
    array_depth = 1
    while index < len(candidate):
        character = candidate[index]
        if in_string:
            output.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            index += 1
            continue
        if character == '"':
            in_string = True
            output.append(character)
            index += 1
            continue
        if character == "[":
            array_depth += 1
        elif character == "]":
            if array_depth == 1 and object_depth > 0:
                output.append("}" * object_depth)
                object_depth = 0
            array_depth -= 1
            output.append(character)
            index += 1
            if array_depth == 0:
                output.append(candidate[index:])
                return "".join(output)
            continue
        elif character == "{":
            object_depth += 1
        elif character == "}":
            object_depth = max(0, object_depth - 1)
        elif character == "," and array_depth == 1 and object_depth > 0:
            remainder = candidate[index + 1 :]
            if re.match(r'\s*\{\s*"name"\s*:', remainder):
                output.append("}" * object_depth)
                object_depth = 0
        output.append(character)
        index += 1
    return candidate


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
    repaired = _repair_character_array_boundaries(candidate)
    if repaired != candidate:
        try:
            payload = json.loads(repaired)
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


def normalize_creative_generation_json(
    kind: str,
    payload: dict[str, Any],
    output_text: str,
) -> dict[str, Any]:
    """Validate and recover the structured payload required by one helper kind.

    A malformed top-level review object can still contain individually valid issue
    objects.  The generic parser deliberately accepts embedded JSON, so without a
    kind-aware check it may mistake the first issue for the entire review report.
    Recover the report envelope and every independently valid issue, while refusing
    to mark an incomplete negative review as successful.
    """

    text_field_by_kind = {
        "outline_background": "background_text",
        "outline_plot": "plot_text",
        "outline_highlight": "highlight_text",
    }
    if kind in text_field_by_kind:
        field = text_field_by_kind[kind]
        candidates = [
            str(payload.get(field) or "").strip(),
            _extract_json_string_field(output_text, field),
            _extract_relaxed_json_string_field(output_text, field),
            _plain_model_text(output_text, expected_field=field),
        ]
        # MiniMax occasionally emits an otherwise complete JSON string with
        # unescaped quotation marks inside prose.  The generic repair parser can
        # then return only the prefix before the first quotation mark.  Prefer the
        # longest recoverable single-field value so a short fragment can never
        # silently replace the complete model response.
        value = max((item for item in candidates if item), key=len, default="")
        if not value:
            raise ModelVerificationError(
                f"MiniMax M3 {kind} 结果结构不完整，请重新生成"
            )
        if kind == "outline_plot" and len(value) < 800:
            raise ModelVerificationError("MiniMax M3 故事情节结果过短，请重新生成")
        if kind == "outline_background" and len(value) > 220:
            shortened = value[:220]
            punctuation = max(shortened.rfind("。"), shortened.rfind("！"), shortened.rfind("？"))
            value = shortened[: punctuation + 1] if punctuation >= 80 else shortened.rstrip("，、；： ") + "。"
        return {field: value}

    if kind == "novel_naming":
        raw_titles = payload.get("titles")
        if not isinstance(raw_titles, list):
            raw_titles = payload.get("items")
        titles = [str(item).strip() for item in raw_titles or [] if str(item).strip()]
        if not titles:
            raise ModelVerificationError("MiniMax M3 书名结果结构不完整，请重新生成")
        return {"titles": titles}

    if kind == "novel_template":
        required_fields = [
            "protagonist_identity",
            "background_setting",
            "core_conflict",
            "emotional_mainline",
            "style_features",
        ]
        genre = str(payload.get("genre") or "").strip()
        template_name = str(payload.get("template_name") or "").strip()
        template_key = str(payload.get("template_key") or "").strip()
        template_data = payload.get("template_data")
        if not isinstance(template_data, dict):
            template_data = {}
        normalized_data = {
            field: str(template_data.get(field) or "").strip()
            for field in required_fields
        }
        if not genre or not template_name or not template_key or any(
            not value for value in normalized_data.values()
        ):
            raise ModelVerificationError("MiniMax M3 模板结果结构不完整，请重新生成")
        if any(len(value) > 24 for value in normalized_data.values()):
            raise ModelVerificationError("MiniMax M3 模板字段过长，请重新生成")
        return {
            "genre": genre,
            "template_key": template_key,
            "template_name": template_name,
            "template_fields": required_fields,
            "template_data": normalized_data,
        }

    if kind == "novel_cover":
        cover_prompt = str(payload.get("cover_prompt") or "").strip()
        if not cover_prompt:
            cover_prompt = _extract_json_string_field(output_text, "cover_prompt")
        if not cover_prompt:
            cover_prompt = _plain_model_text(output_text, expected_field="cover_prompt")
        if not cover_prompt:
            raise ModelVerificationError("MiniMax M3 封面结果结构不完整，请重新生成")
        keywords = payload.get("keywords")
        return {
            "cover_prompt": cover_prompt,
            "subtitle": str(payload.get("subtitle") or "").strip(),
            "keywords": [
                str(item).strip()
                for item in keywords or []
                if str(item).strip()
            ] if isinstance(keywords, list) else [],
        }

    if kind == "outline_characters":
        raw_characters = payload.get("characters")
        if not isinstance(raw_characters, list):
            raw_characters = payload.get("items")
        if not isinstance(raw_characters, list) and payload.get("name"):
            raw_characters = [payload]
        characters = [
            item for item in raw_characters or []
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        ]
        if not characters:
            raise ModelVerificationError("MiniMax M3 角色结果结构不完整，请重新生成")
        return {"characters": characters}

    if kind == "chapter_storyline_recommendation":
        raw_ids = payload.get("storyline_ids")
        if not isinstance(raw_ids, list):
            raise ModelVerificationError("MiniMax M3 故事线推荐结构不完整，请重新生成")
        return {
            "storyline_ids": [str(item).strip() for item in raw_ids if str(item).strip()],
            "reason": str(payload.get("reason") or "").strip(),
        }

    if kind == "chapter_outline":
        title = str(payload.get("title") or "").strip()
        outline_text = str(payload.get("outline_text") or "").strip()
        if not title:
            title = _extract_json_string_field(output_text, "title")
        if not outline_text:
            outline_text = _extract_json_string_field(output_text, "outline_text")
        if not title or not outline_text:
            raise ModelVerificationError("MiniMax M3 章纲结果结构不完整，请重新生成")
        return {"title": title, "outline_text": outline_text}

    if kind != "review":
        raise ModelVerificationError("MiniMax M3 返回了未知的创作生成结果")

    passed = payload.get("passed") if isinstance(payload.get("passed"), bool) else None
    summary = payload.get("summary") if isinstance(payload.get("summary"), str) else ""
    summary = summary.strip()
    issues = _normalized_review_issues(payload.get("issues"))

    if passed is None:
        match = re.search(r'"passed"\s*:\s*(true|false)', output_text, re.IGNORECASE)
        if match is not None:
            passed = match.group(1).lower() == "true"
    if not summary:
        summary = _extract_json_string_field(output_text, "summary")

    recovered_issues = _review_issues_from_embedded_objects(output_text)
    if not issues:
        issues = recovered_issues
    elif recovered_issues:
        issues = _deduplicate_review_issues([*issues, *recovered_issues])

    # ``parse_model_json`` may have returned one embedded issue object directly.
    direct_issue = _normalized_review_issue(payload)
    if direct_issue is not None:
        issues = _deduplicate_review_issues([direct_issue, *issues])

    if passed is None:
        passed = False if issues else None
    if issues:
        passed = False
    if passed is None or not summary or (passed is False and not issues):
        raise ModelVerificationError(
            "MiniMax M3 审稿结果结构不完整，请重新审稿"
        )
    return {"passed": passed, "summary": summary, "issues": issues}


def normalize_intelligence_generation_json(
    payload: dict[str, Any],
    output_text: str,
) -> list[dict[str, Any]]:
    """Recover and validate story-ledger items from a MiniMax response.

    Long Chinese evidence strings occasionally contain unescaped ASCII quotes.
    That can invalidate the outer JSON envelope while leaving many individual
    item objects intact.  ``parse_model_json`` intentionally returns the first
    independently valid object in that situation, so this kind-aware layer also
    scans every embedded object and deduplicates the valid intelligence items.
    An empty result is never accepted as a successful synchronization.
    """

    candidates: list[dict[str, Any]] = []
    raw_items = payload.get("items")
    if isinstance(raw_items, list):
        candidates.extend(item for item in raw_items if isinstance(item, dict))
    if payload.get("item_type"):
        candidates.append(payload)
    candidates.extend(_intelligence_items_from_embedded_objects(output_text))

    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for candidate in candidates:
        item = _normalized_intelligence_item(candidate)
        if item is None:
            continue
        marker = (
            item["item_type"],
            item["subject"],
            item["predicate"],
            item["object"],
            item["source_text"],
        )
        if marker in seen:
            continue
        seen.add(marker)
        output.append(item)
        if len(output) >= 200:
            break
    if not output:
        raise ModelVerificationError(
            "MiniMax M3 未返回可用的章节情报，请重新同步"
        )
    return output


def _plain_model_text(output_text: str, *, expected_field: str) -> str:
    """Recover useful prose when MiniMax returns text instead of a JSON envelope.

    This fallback is intentionally limited to helpers whose entire result is one
    text field.  If the expected JSON key is present but malformed, fail closed so
    a partial JSON fragment is never saved as story content.
    """

    candidate = output_text.strip()
    fenced = re.fullmatch(r"```(?:json|text)?\s*(.*?)\s*```", candidate, re.DOTALL)
    if fenced:
        candidate = fenced.group(1).strip()
    if not candidate or f'"{expected_field}"' in candidate:
        return ""
    if candidate.startswith(("{", "[")):
        return ""
    return candidate


def _extract_json_string_field(text: str, field: str) -> str:
    match = re.search(rf'"{re.escape(field)}"\s*:\s*', text)
    if match is None:
        return ""
    try:
        value, _ = json.JSONDecoder().raw_decode(text[match.end() :])
    except json.JSONDecodeError:
        return ""
    return value.strip() if isinstance(value, str) else ""


def _extract_relaxed_json_string_field(text: str, field: str) -> str:
    """Recover a single JSON text field containing unescaped prose quotes.

    This deliberately requires the field to occupy the complete top-level JSON
    envelope.  It is therefore safe only for the single-text helper kinds that
    call it above, and cannot accidentally consume a neighbouring JSON field.
    """

    start = re.search(rf'"{re.escape(field)}"\s*:\s*"', text)
    if start is None:
        return ""
    remainder = text[start.end() :]
    # Some MiniMax replies append a status capsule after the JSON despite the
    # prompt.  Use the final string-and-object terminator rather than requiring
    # the JSON object itself to be the final bytes of the reply.
    endings = list(re.finditer(r'"\s*}', remainder))
    if not endings:
        return ""
    end = endings[-1]
    raw_value = remainder[: end.start()]

    def replace_escape(match: re.Match[str]) -> str:
        token = match.group(1)
        if token.startswith("u"):
            return chr(int(token[1:], 16))
        return {
            '"': '"',
            "\\": "\\",
            "/": "/",
            "b": "\b",
            "f": "\f",
            "n": "\n",
            "r": "\r",
            "t": "\t",
        }[token]

    return re.sub(r'\\(u[0-9a-fA-F]{4}|["\\/bfnrt])', replace_escape, raw_value).strip()


def _normalized_intelligence_item(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    item_type = str(value.get("item_type") or "").strip()
    subject = str(value.get("subject") or "").strip()
    predicate = str(value.get("predicate") or "").strip()
    object_text = str(value.get("object") or "").strip()
    source_text = str(value.get("source_text") or "").strip()
    if item_type not in INTELLIGENCE_ITEM_TYPES:
        return None
    if not subject or not predicate or not object_text or not source_text:
        return None
    try:
        confidence = int(value.get("confidence", 50))
    except (TypeError, ValueError):
        confidence = 50
    return {
        "item_type": item_type,
        "subject": subject,
        "predicate": predicate,
        "object": object_text,
        "source_text": source_text,
        "reasoning_summary": str(value.get("reasoning_summary") or "").strip(),
        "confidence": max(0, min(confidence, 100)),
    }


def _intelligence_items_from_embedded_objects(
    text: str,
) -> list[dict[str, Any]]:
    decoder = json.JSONDecoder()
    output: list[dict[str, Any]] = []
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            candidate, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        item = _normalized_intelligence_item(candidate)
        if item is not None:
            output.append(item)
    return output


def _normalized_review_issue(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    severity = str(value.get("severity") or "").strip().upper()
    issue_type = str(value.get("type") or "").strip()
    evidence = str(value.get("evidence") or "").strip()
    suggestion = str(value.get("suggestion") or "").strip()
    if severity not in {"P0", "P1", "P2", "P3"}:
        return None
    if not issue_type or not evidence or not suggestion:
        return None
    return {
        "severity": severity,
        "type": issue_type[:160],
        "evidence": evidence[:4000],
        "suggestion": suggestion[:4000],
    }


def _normalized_review_issues(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    return _deduplicate_review_issues(
        issue
        for item in value
        if (issue := _normalized_review_issue(item)) is not None
    )


def _review_issues_from_embedded_objects(text: str) -> list[dict[str, str]]:
    decoder = json.JSONDecoder()
    issues: list[dict[str, str]] = []
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            candidate, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        issue = _normalized_review_issue(candidate)
        if issue is not None:
            issues.append(issue)
    return _deduplicate_review_issues(issues)


def _deduplicate_review_issues(
    values: Iterable[dict[str, str]],
) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for value in values:
        marker = (
            value["severity"],
            value["type"],
            value["evidence"],
            value["suggestion"],
        )
        if marker in seen:
            continue
        seen.add(marker)
        output.append(value)
        if len(output) >= 100:
            break
    return output
