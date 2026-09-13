"""Idempotently create the novel Agent and enable the project Skills for it."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


AGENT_ID = "ai-novel-writer"
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from backend.writing_skills.catalog import published_skill_ids

SKILLS = sorted(published_skill_ids(ROOT / "skills"))
TOOLS = [
    "novel_get_context",
    "novel_get_document",
    "novel_search",
    "novel_get_workspace_context",
    "novel_prepare_selection_edit",
    "novel_library_query",
    "novel_library_prepare_change",
    "novel_library_apply_change",
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


def skill_enable_plan(*, created: bool, previous: dict[str, bool] | None) -> list[str]:
    """Caller supplies a frozen pre-install public snapshot under install lock."""
    if previous is not None and any(type(value) is not bool for value in previous.values()):
        raise ValueError("invalid previous Skill state")
    if previous == {} and not created:
        raise ValueError("empty Skill baseline cannot initialize an existing Agent")
    if created and not previous:
        return list(SKILLS)
    return [name for name in SKILLS if previous is not None and (
        name not in previous or previous[name] is True
    )]


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


def read_skill_state() -> dict[str, bool]:
    """Read only this plugin's explicit switches on the dedicated Agent."""
    available = request_json("/api/skills", agent_id=AGENT_ID)
    if not isinstance(available, list):
        raise RuntimeError("invalid public Skill inventory")
    previous: dict[str, bool] = {}
    for item in available:
        if not isinstance(item, dict) or item.get("source") != "plugin:ai-novel-world-2026":
            continue
        name = item.get("name")
        enabled = item.get("enabled")
        if not isinstance(name, str) or not name or type(enabled) is not bool or name in previous:
            raise RuntimeError("invalid public Skill state")
        previous[name] = enabled
    return previous


def capture_skill_state() -> dict[str, object]:
    """Public pre-install snapshot; absence and disabled are different states."""
    agents = request_json("/api/agents")
    if not isinstance(agents, dict) or not isinstance(agents.get("agents"), list):
        raise RuntimeError("invalid public Agent inventory")
    ids = [item.get("id") if isinstance(item, dict) else None for item in agents["agents"]]
    if any(not isinstance(item, str) or not item for item in ids) or len(set(ids)) != len(ids):
        raise RuntimeError("invalid public Agent inventory")
    exists = AGENT_ID in ids
    previous = read_skill_state() if exists else {}
    if exists and not previous:
        raise RuntimeError("existing Agent has no plugin Skill inventory; cannot capture baseline")
    return {"schema": "skill-enable-state/1", "base_url": BASE_URL,
            "agent_id": AGENT_ID, "skills": previous}


def load_previous_skill_state(path: Path) -> dict[str, bool]:
    if path.stat().st_size > 65536:
        raise ValueError("previous Skill state too large")
    value = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(value, dict) or set(value) != {"schema", "base_url", "agent_id", "skills"}
            or value["schema"] != "skill-enable-state/1" or value["base_url"] != BASE_URL
            or value["agent_id"] != AGENT_ID or not isinstance(value["skills"], dict)):
        raise ValueError("previous Skill state scope mismatch")
    previous = value["skills"]
    if any(not isinstance(name, str) or not name or type(enabled) is not bool
           for name, enabled in previous.items()):
        raise ValueError("invalid previous Skill state")
    return previous


def restore_skill_state(previous: dict[str, bool] | None, *, created: bool = False) -> dict[str, object]:
    """Narrow public restore: no Agent, prompt, tool or model writes.

    One initial difference batch and at most one compensating batch. Public
    readback, not batch acknowledgement, is the authority after an error.
    """
    enable_ids = skill_enable_plan(created=created, previous=previous)
    observed = read_skill_state()
    missing = sorted(set(SKILLS) - observed.keys())
    if missing:
        raise RuntimeError(f"plugin Skills missing from {AGENT_ID}: {missing}")
    expected = ({name: name in enable_ids for name in SKILLS}
                if previous is not None or created else {})
    compensation = False
    for round_index in range(2):
        differences = {name: value for name, value in expected.items() if observed.get(name) is not value}
        if not differences:
            break
        compensation = round_index == 1
        for enabled in (False, True):
            names = sorted(name for name, value in differences.items() if value is enabled)
            if not names:
                continue
            try:
                request_json("/api/skills/batch-enable" if enabled else "/api/skills/batch-disable",
                             method="POST", body=names, agent_id=AGENT_ID)
            except (HTTPError, URLError, TimeoutError, OSError):
                # A lost acknowledgement can still mean applied. Never replay
                # without reading the actual state first.
                pass
        observed = read_skill_state()
    differences = sorted(name for name, value in expected.items() if observed.get(name) is not value)
    if differences:
        raise RuntimeError(f"public Skill enablement readback mismatch: {differences}")
    return {
        "agent_id": AGENT_ID,
        "state_preserved": True if previous else None,
        "restore_status": "restored" if previous else ("initialized" if created else "no_baseline"),
        "requested_enable_skills": enable_ids,
        "enabled_skills": sorted(name for name in SKILLS if observed.get(name) is True),
        "added_skills": sorted(set(SKILLS) - previous.keys()) if previous is not None else [],
        "removed_skills": sorted(previous.keys() - set(SKILLS)) if previous is not None else [],
        "compensation_used": compensation,
    }


def configure(*, previous_skill_state: dict[str, bool] | None = None) -> dict[str, object]:
    agents = request_json("/api/agents")
    assert isinstance(agents, dict)
    agent_ids = {item["id"] for item in agents.get("agents", [])}
    created = AGENT_ID not in agent_ids
    # Reject an ambiguous old snapshot before any Agent/configuration write.
    skill_enable_plan(created=created, previous=previous_skill_state)
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

    skill_result = restore_skill_state(previous_skill_state, created=created)

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

    final_skills = read_skill_state()
    if sorted(name for name in SKILLS if final_skills.get(name) is True) != skill_result["enabled_skills"]:
        raise RuntimeError("public Skill enablement readback mismatch")
    return {
        **skill_result,
        "agent_id": AGENT_ID,
        "created": created,
        "effective_model": active_llm,
        "enabled_tools": TOOLS,
        "system_prompt_files": system_prompt_files,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous-skill-state", type=Path)
    parser.add_argument("--restore-skills-only", action="store_true")
    args = parser.parse_args()
    try:
        previous = load_previous_skill_state(args.previous_skill_state) if args.previous_skill_state else None
        if args.restore_skills_only and not previous:
            raise ValueError("narrow restore requires a nonempty previous Skill baseline")
        result = restore_skill_state(previous) if args.restore_skills_only else configure(previous_skill_state=previous)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (AssertionError, OSError, ValueError, HTTPError, URLError, TimeoutError, RuntimeError) as error:
        print(f"Novel Agent configuration failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
