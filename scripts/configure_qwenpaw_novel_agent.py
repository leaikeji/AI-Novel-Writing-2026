"""Idempotently create the novel Agent and enable the project Skills for it."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


AGENT_ID = "ai-novel-writer"
SKILLS = [
    "novel-direction",
    "story-bible",
    "chapter-outline",
    "prose-writing",
    "continuity-check",
    "style-review",
]
TOOLS = [
    "novel_get_context",
    "novel_get_document",
    "novel_search",
    "novel_get_workspace_context",
    "novel_prepare_selection_edit",
]
BASE_URL = os.environ.get("QWENPAW_BASE_URL", "http://127.0.0.1:18088").rstrip("/")
ROOT = Path(__file__).resolve().parents[1]
PROMPT_FILE = "AI_NOVEL_WORLD.md"
PROMPT_SOURCE = ROOT / "qwenpaw-agent" / PROMPT_FILE


def desired_agent_payload() -> dict[str, object]:
    return {
        "id": AGENT_ID,
        "name": "AI小说作家",
        "description": (
            "AI小说世界2026 专用写作助手；使用项目版本化 Skills 与小说工作台，"
            "不替代 QwenPaw 原生设置。"
        ),
        "language": "zh",
    }


def request_json(
    path: str,
    *,
    method: str = "GET",
    body: object | None = None,
    agent_id: str | None = None,
) -> object:
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    if agent_id:
        headers["X-Agent-Id"] = agent_id
    request = Request(
        f"{BASE_URL}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    with urlopen(request, timeout=15) as response:  # noqa: S310 - fixed local lab URL
        return json.load(response)


def configure() -> dict[str, object]:
    agents = request_json("/api/agents")
    assert isinstance(agents, dict)
    agent_ids = {item["id"] for item in agents.get("agents", [])}
    created = AGENT_ID not in agent_ids
    if created:
        request_json(
            "/api/agents",
            method="POST",
            body={**desired_agent_payload(), "skill_names": []},
        )
    else:
        # Runtime uninstall removes plugin tools from each existing Agent's
        # materialized tool registry.  A public no-op Agent update rebuilds
        # that registry after reinstall without deleting the workspace,
        # chats, model selection, channel settings, or system-prompt files.
        request_json(
            f"/api/agents/{AGENT_ID}",
            method="PUT",
            body=desired_agent_payload(),
        )

    available = request_json("/api/skills", agent_id=AGENT_ID)
    assert isinstance(available, list)
    available_names = {
        str(item["name"])
        for item in available
        if isinstance(item, dict) and item.get("source") == "plugin:ai-novel-world-2026"
    }
    missing = sorted(set(SKILLS) - available_names)
    if missing:
        raise RuntimeError(f"plugin Skills missing from {AGENT_ID}: {missing}")

    enabled = request_json(
        "/api/skills/batch-enable",
        method="POST",
        body=SKILLS,
        agent_id=AGENT_ID,
    )
    assert isinstance(enabled, dict)
    failed = {
        name: result
        for name, result in enabled.get("results", {}).items()
        if not result.get("success")
    }
    if failed:
        raise RuntimeError(f"failed to enable novel Skills: {failed}")

    available_tools = request_json("/api/tools", agent_id=AGENT_ID)
    assert isinstance(available_tools, list)
    tool_by_name = {
        str(item["name"]): item for item in available_tools if isinstance(item, dict)
    }
    missing_tools = sorted(set(TOOLS) - set(tool_by_name))
    if missing_tools:
        raise RuntimeError(f"plugin tools missing from {AGENT_ID}: {missing_tools}")
    for tool_name in TOOLS:
        if tool_by_name[tool_name].get("enabled") is not True:
            request_json(
                f"/api/tools/{tool_name}/toggle",
                method="PATCH",
                agent_id=AGENT_ID,
            )

    # Project tools are intentionally scoped to the dedicated novel Agent.
    # Toggle only an observed enabled state, keeping repeated configuration
    # idempotent and leaving unrelated tools untouched.
    for agent_id in sorted(agent_ids - {AGENT_ID}):
        other_tools = request_json("/api/tools", agent_id=agent_id)
        assert isinstance(other_tools, list)
        other_tool_by_name = {
            str(item["name"]): item
            for item in other_tools
            if isinstance(item, dict)
        }
        for tool_name in TOOLS:
            tool = other_tool_by_name.get(tool_name)
            if tool is not None and tool.get("enabled") is True:
                request_json(
                    f"/api/tools/{tool_name}/toggle",
                    method="PATCH",
                    agent_id=agent_id,
                )

    request_json(
        f"/api/workspace/files/{PROMPT_FILE}",
        method="PUT",
        body={"content": PROMPT_SOURCE.read_text(encoding="utf-8")},
        agent_id=AGENT_ID,
    )
    system_prompt_files = request_json(
        "/api/workspace/system-prompt-files",
        agent_id=AGENT_ID,
    )
    assert isinstance(system_prompt_files, list)
    if PROMPT_FILE not in system_prompt_files:
        system_prompt_files.append(PROMPT_FILE)
        system_prompt_files = request_json(
            "/api/workspace/system-prompt-files",
            method="PUT",
            body=system_prompt_files,
            agent_id=AGENT_ID,
        )
        assert isinstance(system_prompt_files, list)

    active_model = request_json(
        f"/api/models/active?scope=effective&agent_id={AGENT_ID}",
    )
    active_llm = (
        active_model.get("active_llm")
        if isinstance(active_model, dict)
        else None
    )
    if (
        not isinstance(active_llm, dict)
        or not str(active_llm.get("provider_id") or "").strip()
        or not str(active_llm.get("model") or "").strip()
    ):
        raise RuntimeError(
            "AI 小说作家没有可用的有效模型；请先在 QwenPaw 设置 Agent "
            "专属模型或全局默认模型"
        )

    return {
        "agent_id": AGENT_ID,
        "created": created,
        "effective_model": active_llm,
        "enabled_skills": SKILLS,
        "enabled_tools": TOOLS,
        "system_prompt_files": system_prompt_files,
    }


def main() -> None:
    try:
        print(json.dumps(configure(), ensure_ascii=False, indent=2))
    except (AssertionError, HTTPError, URLError, TimeoutError, RuntimeError) as error:
        print(f"Novel Agent configuration failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
