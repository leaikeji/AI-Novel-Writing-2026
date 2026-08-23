"""Verify the installed AI小说世界2026 contract against a local QwenPaw lab."""

from __future__ import annotations

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


APP_ID = "ai-novel-world-2026"
APP_VERSION = "0.3.0"
NOVEL_AGENT_ID = "ai-novel-writer"
NOVEL_SKILLS = {
    "novel-direction",
    "story-bible",
    "chapter-outline",
    "prose-writing",
    "continuity-check",
    "style-review",
}
NOVEL_TOOLS = {"novel_get_context", "novel_get_document", "novel_search"}
NOVEL_PROMPT_FILE = "AI_NOVEL_WORLD.md"
BASE_URL = os.environ.get("QWENPAW_BASE_URL", "http://127.0.0.1:18088").rstrip("/")


def get_json(path: str, *, agent_id: str | None = None) -> object:
    headers = {"Accept": "application/json"}
    if agent_id:
        headers["X-Agent-Id"] = agent_id
    request = Request(f"{BASE_URL}{path}", headers=headers)
    with urlopen(request, timeout=10) as response:  # noqa: S310 - fixed local lab URL
        return json.load(response)


def plugin_skills(agent_id: str) -> dict[str, dict[str, object]]:
    payload = get_json("/api/skills", agent_id=agent_id)
    assert isinstance(payload, list)
    return {
        str(item["name"]): item
        for item in payload
        if isinstance(item, dict) and item.get("source") == f"plugin:{APP_ID}"
    }


def verify() -> dict[str, object]:
    pawapps = get_json("/api/pawapps")
    assert isinstance(pawapps, dict)
    installed = [app for app in pawapps.get("apps", []) if app.get("id") == APP_ID]
    assert len(installed) == 1, f"expected one installed PawApp, got {len(installed)}"
    assert installed[0].get("version") == APP_VERSION

    health = get_json(f"/api/{APP_ID}/health")
    assert isinstance(health, dict)
    assert health.get("app_id") == APP_ID
    assert health.get("ai_candidate_generation_enabled") is True
    assert health.get("ai_authoritative_write_enabled") is False

    agent_payload = get_json("/api/agents")
    assert isinstance(agent_payload, dict)
    agent_ids = {agent["id"] for agent in agent_payload.get("agents", [])}
    assert NOVEL_AGENT_ID in agent_ids
    assert {"default", "QwenPaw_QA_Agent_0.2"}.issubset(agent_ids)

    enabled_scope: dict[str, list[str]] = {}
    for agent_id in ("default", "QwenPaw_QA_Agent_0.2", NOVEL_AGENT_ID):
        skills = plugin_skills(agent_id)
        assert set(skills) == NOVEL_SKILLS, f"unexpected novel skills in {agent_id}"
        enabled_scope[agent_id] = sorted(
            name for name, item in skills.items() if item.get("enabled") is True
        )

    assert enabled_scope["default"] == []
    assert enabled_scope["QwenPaw_QA_Agent_0.2"] == []
    assert set(enabled_scope[NOVEL_AGENT_ID]) == NOVEL_SKILLS

    enabled_tools: dict[str, list[str]] = {}
    for agent_id in ("default", "QwenPaw_QA_Agent_0.2", NOVEL_AGENT_ID):
        tools = get_json("/api/tools", agent_id=agent_id)
        assert isinstance(tools, list)
        novel_tools = {
            str(tool["name"]): tool
            for tool in tools
            if isinstance(tool, dict) and str(tool.get("name", "")).startswith("novel_")
        }
        assert set(novel_tools).issubset(NOVEL_TOOLS)
        if agent_id == NOVEL_AGENT_ID:
            assert set(novel_tools) == NOVEL_TOOLS
        enabled_tools[agent_id] = sorted(
            name for name, item in novel_tools.items() if item.get("enabled") is True
        )
    assert enabled_tools["default"] == []
    assert enabled_tools["QwenPaw_QA_Agent_0.2"] == []
    assert set(enabled_tools[NOVEL_AGENT_ID]) == NOVEL_TOOLS

    system_prompt_files = get_json(
        "/api/workspace/system-prompt-files",
        agent_id=NOVEL_AGENT_ID,
    )
    assert isinstance(system_prompt_files, list)
    assert NOVEL_PROMPT_FILE in system_prompt_files
    prompt_payload = get_json(
        f"/api/workspace/files/{NOVEL_PROMPT_FILE}",
        agent_id=NOVEL_AGENT_ID,
    )
    assert isinstance(prompt_payload, dict)
    assert "正文生成或重写必须调用 `prose-writing`" in str(
        prompt_payload.get("content", "")
    )
    workspace_files = get_json("/api/workspace/files", agent_id=NOVEL_AGENT_ID)
    assert isinstance(workspace_files, list)
    workspace_names = {
        str(item.get("filename")) for item in workspace_files if isinstance(item, dict)
    }
    assert "BOOTSTRAP.md" not in workspace_names

    return {
        "base_url": BASE_URL,
        "pawapp": f"{APP_ID}@{APP_VERSION}",
        "health": health.get("status"),
        "agents": sorted(agent_ids),
        "enabled_novel_skills": enabled_scope,
        "enabled_novel_tools": enabled_tools,
        "system_prompt_files": system_prompt_files,
    }


def main() -> None:
    try:
        print(json.dumps(verify(), ensure_ascii=False, indent=2))
    except (AssertionError, HTTPError, URLError, TimeoutError) as error:
        print(f"QwenPaw lab verification failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
