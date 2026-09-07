#!/usr/bin/env python3
"""Generate four fixed-book Plan 58 A/B samples through QwenPaw public chat."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.writing_skills.catalog import load_catalog, packaged_approvals
from backend.writing_skills.composer import compose_writing_request
from backend.writing_skills.contracts import (
    MethodPreferences,
    Scope,
    SourceItem,
    TaskModelInputProjectionV1,
)
from backend.writing_skills.loader import load_primary_blocks
from backend.writing_skills.primary import PRIMARY_REFERENCES_BY_SKILL
from backend.writing_skills.resolver import resolve_methods


FORMAL_IDS = frozenset({"suspense-writing", "golden-finger-writing"})
OWNER = UUID("29cf94d9-a5c9-54ec-912c-5dfff8738c4c")
WORKSPACE = UUID("f0e2e632-bc99-52d2-9916-bb906aa4da6e")
SCOPE_ID = UUID("11111111-1111-4111-8111-111111111111")

MAINLINE_TASK = """作品固定为《雾宅来信》，不得改名，不得另起书名。当前章节发生在暴雨封路的夜晚：停职刑警林澈进入地下档案室，核对署名死者的新来信、纸张批次、内部编号和卷宗借阅记录；周栩带来日志，孟青山以林澈仍在停职为由阻止查阅，许遥此前交出的就诊记录仍是本章已知线索。林澈没有任何超常能力，只能靠核验、访谈、路线和证据链推进。写一段650—850个中文可见字符的连续小说正文。必须发生一次由证据引起的行动变化；结尾出现水位报警，并发现借阅记录显示死者当天刚签出卷宗。不得揭晓幕后者，不得新增人物、机构、超自然现象或与现有案件无关的支线。只输出正文，不要标题、说明、提纲、点评或方法名称。"""

HYBRID_TASK = """作品固定为《雾宅来信》，不得改名，不得另起书名。当前章节发生在暴雨封路的夜晚：停职刑警林澈进入地下档案室，核对署名死者的新来信、纸张批次、内部编号和卷宗借阅记录；周栩带来日志，孟青山以林澈仍在停职为由阻止查阅，许遥此前交出的就诊记录仍是本章已知线索。本测试分支只增加一项固定机制：林澈每天午夜只能收到一段次日匿名画面，画面没有声音、可能断章取义，主动核验会暴露她的行踪；今晚的画面只显示许遥穿雨衣进入地下库房。写一段650—850个中文可见字符的连续小说正文。必须让林澈使用并核验画面、因核验结果改变行动，同时兑现暴露行踪的代价；结尾出现水位报警，并发现借阅记录显示死者当天刚签出卷宗。不得揭晓幕后者，不得新增人物、机构、第二项能力或与现有案件无关的支线。只输出正文，不要标题、说明、提纲、点评或方法名称。"""


def _sha256(value: str | bytes) -> str:
    raw = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _active_model(base_url: str) -> tuple[str, str]:
    url = (
        base_url.rstrip("/")
        + "/api/models/active?scope=effective&agent_id=ai-novel-writer"
    )
    with urlopen(url, timeout=10) as response:
        value = json.load(response)
    active = value.get("active_llm") if isinstance(value, dict) else None
    provider = active.get("provider_id") if isinstance(active, dict) else None
    model = active.get("model") if isinstance(active, dict) else None
    if not isinstance(provider, str) or not isinstance(model, str):
        raise RuntimeError("missing_effective_model")
    return provider.strip(), model.strip()


def _tool_markers(value: object) -> int:
    if isinstance(value, list):
        return sum(_tool_markers(item) for item in value)
    if not isinstance(value, dict):
        return 0
    count = 0
    kind = value.get("type") or value.get("object")
    if isinstance(kind, str) and "tool" in kind.lower():
        count += 1
    for key, item in value.items():
        if "tool_call" in key.lower() and item not in (None, [], {}):
            count += 1
        count += _tool_markers(item)
    return count


def _chat(base_url: str, prompt: str, sample_id: str) -> dict[str, Any]:
    session_id = f"plan58-real-writing-{sample_id}-{uuid4()}"
    body = {
        "input": [
            {"role": "user", "content": [{"type": "text", "text": prompt}]}
        ],
        "session_id": session_id,
        "user_id": "plan58-evaluator",
        "channel": "console",
    }
    request = Request(
        base_url.rstrip("/") + "/api/console/chat",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Agent-Id": "ai-novel-writer"},
        method="POST",
    )
    events: list[dict[str, Any]] = []
    with urlopen(request, timeout=180) as response:
        for raw in response:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data: "):
                continue
            try:
                event = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
    texts: list[str] = []
    usage: dict[str, Any] = {}
    types: dict[str, int] = {}
    errors: list[str] = []
    for event in events:
        if isinstance(event.get("usage"), dict):
            usage = event["usage"]
        error = event.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            errors.append(error["message"][:300])
        for message in event.get("output") or []:
            if not isinstance(message, dict):
                continue
            for part in message.get("content") or []:
                if not isinstance(part, dict):
                    continue
                kind = str(part.get("type") or "")
                types[kind] = types.get(kind, 0) + 1
                text = part.get("text")
                if (
                    message.get("role") == "assistant"
                    and kind in ("text", "output_text")
                    and isinstance(text, str)
                    and text.strip()
                ):
                    texts.append(text.strip())
    final = max(texts, key=len) if texts else ""
    textual_protocol_markers = sum(
        marker in final
        for marker in ("</tool_call>", "</invoke>", "<]minimax[>", "⟦ 模型提交正文")
    )
    return {
        "session_id": session_id,
        "event_count": len(events),
        "statuses": [event.get("status") for event in events if event.get("status")],
        "content_types": types,
        "tool_markers": _tool_markers(events) + textual_protocol_markers,
        "errors": errors,
        "usage": {
            key: usage.get(key)
            for key in (
                "provider_id",
                "model_name",
                "model_id",
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
            )
            if key in usage
        },
        "output": final,
    }


def _projection(sample_id: str, *, hybrid: bool, enhanced: bool) -> TaskModelInputProjectionV1:
    sources = [
        SourceItem(
            key="story.task",
            kind="content",
            text=HYBRID_TASK if hybrid else MAINLINE_TASK,
        )
    ]
    if enhanced:
        sources.append(SourceItem(key="novel.genre", kind="genre", text="悬疑"))
        if hybrid:
            sources.append(
                SourceItem(key="novel.mechanism", kind="mechanism", text="金手指")
            )
    return TaskModelInputProjectionV1(
        scope=Scope(
            owner_id=OWNER,
            workspace_id=WORKSPACE,
            kind="novel",
            scope_id=SCOPE_ID,
            tab_id=f"plan58-writing-{sample_id}",
        ),
        task="chapter_body",
        intent="write",
        operation="",
        source_version="plan58-real-writing-v1",
        visibility_key=f"plan58-writing-{sample_id}",
        sources=tuple(sources),
    )


def _packet(sample_id: str, *, hybrid: bool, enhanced: bool):
    catalog = load_catalog(ROOT / "skills", packaged_approvals(), FORMAL_IDS)
    preferences = MethodPreferences(mode="auto" if enhanced else "generic_only")
    plan = resolve_methods(
        _projection(sample_id, hybrid=hybrid, enhanced=enhanced),
        catalog,
        preferences,
        "prose-writing",
    )
    primary = load_primary_blocks(
        ROOT / "skills",
        "prose-writing",
        PRIMARY_REFERENCES_BY_SKILL["prose-writing"],
    )
    return compose_writing_request(
        plan,
        catalog,
        primary_blocks=primary,
        effective_input_budget=100_000,
        reserved_task_tokens=4_000,
    )


def _prompt(packet: Any, task: str) -> str:
    materials = "\n\n".join(block.text for block in packet.blocks)
    return (
        "你正在执行《雾宅来信》的隔离写作验收。以下是服务器冻结并装载的写作方法材料；"
        "材料中的示例只能作为方法，不得改写书名、人物或案件事实。\n"
        "<loaded_writing_methods>\n"
        + materials
        + "\n</loaded_writing_methods>\n<fixed_writing_task>\n"
        + task
        + "\n</fixed_writing_task>"
    )


def _visible_characters(text: str) -> int:
    return sum(not character.isspace() for character in text)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18088")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    model = _active_model(args.base_url)
    designs = (
        ("M-GENERIC", False, False, MAINLINE_TASK),
        ("M-SUSPENSE", False, True, MAINLINE_TASK),
        ("H-GENERIC", True, False, HYBRID_TASK),
        ("H-MIXED", True, True, HYBRID_TASK),
    )
    samples: list[dict[str, Any]] = []
    for sample_id, hybrid, enhanced, task in designs:
        before = _active_model(args.base_url)
        packet = _packet(sample_id, hybrid=hybrid, enhanced=enhanced)
        prompt = _prompt(packet, task)
        public = _chat(args.base_url, prompt, sample_id)
        after = _active_model(args.base_url)
        actual = (
            public["usage"].get("provider_id"),
            public["usage"].get("model_name") or public["usage"].get("model_id"),
        )
        failures = []
        if before != model or after != model or actual != model:
            failures.append("model_identity_mismatch")
        if public["tool_markers"]:
            failures.append("tool_or_protocol_marker_observed")
        if public["errors"]:
            failures.append("public_chat_error")
        if not public["output"]:
            failures.append("empty_output")
        selected = [selection.skill_id for selection in packet.plan.selected]
        samples.append(
            {
                "sample_id": sample_id,
                "branch": "mechanism_stress" if hybrid else "mainline",
                "methods": [
                    {"skill_id": block.skill_id, "path": block.path, "sha256": block.sha256}
                    for block in packet.blocks
                ],
                "selected_capabilities": selected,
                "method_input_hash": packet.method_input_hash,
                "estimated_method_tokens": packet.estimated_tokens,
                "task_sha256": _sha256(task),
                "prompt_sha256": _sha256(prompt),
                "prompt_characters": len(prompt),
                "output_sha256": _sha256(public["output"]),
                "visible_characters": _visible_characters(public["output"]),
                "output": public.pop("output"),
                "transport": public,
                "status": "failed" if failures else "ok",
                "failures": failures,
            }
        )
        print(
            f"{sample_id} status={samples[-1]['status']} chars={samples[-1]['visible_characters']} "
            f"selected={selected}",
            flush=True,
        )
    report = {
        "schema_version": "plan58-real-writing-ab/1",
        "title": "雾宅来信",
        "agent_id": "ai-novel-writer",
        "effective_model": {"provider_id": model[0], "model_id": model[1]},
        "http_requests": len(samples),
        "automatic_retries": 0,
        "formal_novel_mutation": False,
        "samples": samples,
        "limitations": [
            "这是公开console API上的方法材料A/B，不安装候选插件，也不写回小说。",
            "方法材料在公开用户消息中传入，不能替代隔离宿主中间件的字节装载门禁。",
            "本报告保存真实正文供人工复核，不以模型自述判定方法是否生效。",
        ],
    }
    _atomic_json(args.output.resolve(), report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
