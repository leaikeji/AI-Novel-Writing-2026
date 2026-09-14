"""Idempotently create the novel Agent and enable the project Skills for it."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable
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
PLAN83_CANDIDATE_SOURCE = (
    ROOT / "qwenpaw-agent" / "candidates" / "AI_NOVEL_WORLD.plan83-v0.4.md"
)
PROMPT_BASELINES = ROOT / "qwenpaw-agent" / "prompt-baselines.json"
QWENPAW_VERSION = "2.2.1"
PROMPT_BASELINE_SCHEMA = "agent-prompt-baselines/2"
PROMPT_SERIALIZATION = "utf8-remove-single-trailing-lf/1"
EXCLUDABLE_DEFAULT_PROMPTS = frozenset({"SOUL.md", "PROFILE.md"})


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def serialize_prompt_source(value: bytes) -> bytes:
    """Mirror the public workspace API's deterministic text readback.

    QwenPaw 2.2.1 removes one source-terminal LF when workspace text is
    installed.  This is deliberately not ``strip``: author whitespace and
    every other trailing byte remain part of the managed identity.
    """
    value.decode("utf-8", errors="strict")
    return value[:-1] if value.endswith(b"\n") else value


def load_prompt_baselines(path: Path = PROMPT_BASELINES) -> dict[str, Any]:
    if path.stat().st_size > 131072:
        raise ValueError("prompt baseline manifest too large")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != {
        "schema", "serialization", "official_templates", "managed_prompts",
    }:
        raise ValueError("invalid prompt baseline manifest")
    if value["schema"] != PROMPT_BASELINE_SCHEMA or value["serialization"] != PROMPT_SERIALIZATION:
        raise ValueError("unsupported prompt baseline manifest")
    official = value["official_templates"]
    managed = value["managed_prompts"]
    if not isinstance(official, list) or not isinstance(managed, list) or not managed:
        raise ValueError("invalid prompt baseline entries")
    common = {
        "filename", "source_bytes", "source_sha256", "installed_bytes", "installed_sha256",
    }
    seen_official: set[tuple[str, str]] = set()
    for item in official:
        if not isinstance(item, dict) or set(item) != common | {
            "qwenpaw_version", "source_type", "source_url",
        }:
            raise ValueError("invalid official prompt baseline")
        if any(not isinstance(item[field], str) or not item[field] for field in (
            "qwenpaw_version", "source_type", "source_url",
        )):
            raise ValueError("invalid official prompt identity")
        identity = (item["qwenpaw_version"], item["filename"])
        if identity in seen_official:
            raise ValueError("duplicate official prompt baseline")
        seen_official.add(identity)
        _validate_prompt_hash_entry(item)
        if (item["source_type"] != "official-github-tag"
                or not item["source_url"].startswith(
                    "https://github.com/agentscope-ai/QwenPaw/blob/"
                )):
            raise ValueError("untrusted official prompt baseline source")
    seen_managed: set[str] = set()
    seen_managed_installed: set[tuple[int, str]] = set()
    for item in managed:
        if not isinstance(item, dict) or set(item) != common | {
            "prompt_version", "plugin_version", "qwenpaw_version", "source_type",
            "prompt_files_policy",
        }:
            raise ValueError("invalid managed prompt baseline")
        if any(not isinstance(item[field], str) or not item[field] for field in (
            "prompt_version", "plugin_version", "qwenpaw_version", "source_type",
            "prompt_files_policy",
        )):
            raise ValueError("invalid managed prompt identity")
        if item["filename"] != PROMPT_FILE or item["source_type"] != "repository-managed":
            raise ValueError("invalid managed prompt identity")
        if item["prompt_files_policy"] not in {
            "preserve-current", "exclude-exact-official-defaults",
        }:
            raise ValueError("invalid managed prompt files policy")
        if item["prompt_version"] in seen_managed:
            raise ValueError("duplicate managed prompt baseline")
        seen_managed.add(item["prompt_version"])
        _validate_prompt_hash_entry(item)
        installed_identity = (item["installed_bytes"], item["installed_sha256"])
        if installed_identity in seen_managed_installed:
            raise ValueError("ambiguous managed installed prompt baseline")
        seen_managed_installed.add(installed_identity)
    return value


def _validate_prompt_hash_entry(item: dict[str, Any]) -> None:
    for field in ("filename", "source_sha256", "installed_sha256"):
        if not isinstance(item.get(field), str) or not item[field]:
            raise ValueError("invalid prompt baseline value")
    for field in ("source_sha256", "installed_sha256"):
        digest = item[field]
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("invalid prompt baseline digest")
    for field in ("source_bytes", "installed_bytes"):
        if type(item.get(field)) is not int or item[field] < 0:
            raise ValueError("invalid prompt baseline size")


def desired_prompt_candidate(
    *, source: Path = PROMPT_SOURCE, baselines: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = baselines if baselines is not None else load_prompt_baselines()
    source_bytes = source.read_bytes()
    source_identity = (len(source_bytes), _sha256(source_bytes))
    matches = [
        item for item in manifest["managed_prompts"]
        if item["qwenpaw_version"] == QWENPAW_VERSION
        and (item["source_bytes"], item["source_sha256"]) == source_identity
    ]
    if len(matches) != 1:
        raise RuntimeError("repository prompt is not a unique managed baseline")
    installed = serialize_prompt_source(source_bytes)
    entry = matches[0]
    if (len(installed), _sha256(installed)) != (
        entry["installed_bytes"], entry["installed_sha256"],
    ):
        raise RuntimeError("managed prompt serialization mismatch")
    return {"content": installed.decode("utf-8"), "baseline": entry}


def _validate_prompt_file_list(value: object) -> list[str]:
    if (not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value)
            or len(set(value)) != len(value)):
        raise RuntimeError("invalid public system prompt file list")
    return list(value)


def read_workspace_prompt(filename: str = PROMPT_FILE) -> str:
    value = request_json(f"/api/workspace/files/{filename}", agent_id=AGENT_ID)
    if not isinstance(value, dict) or not isinstance(value.get("content"), str):
        raise RuntimeError(f"invalid public workspace file readback: {filename}")
    return value["content"]


def read_system_prompt_files() -> list[str]:
    return _validate_prompt_file_list(request_json(
        "/api/workspace/system-prompt-files", agent_id=AGENT_ID,
    ))


def _official_installed_identity(
    baselines: dict[str, Any], filename: str,
) -> tuple[int, str] | None:
    matches = [
        item for item in baselines["official_templates"]
        if item["qwenpaw_version"] == QWENPAW_VERSION and item["filename"] == filename
    ]
    if len(matches) > 1:
        raise RuntimeError(f"ambiguous official prompt baseline: {filename}")
    if not matches:
        return None
    return matches[0]["installed_bytes"], matches[0]["installed_sha256"]


def build_prompt_configuration_plan(
    *, baselines: dict[str, Any] | None = None,
    current_prompt: str | None = None,
    current_files: list[str] | None = None,
    source: Path = PROMPT_SOURCE,
) -> dict[str, Any]:
    """Read and freeze an existing Agent's safe prompt-only transition."""
    manifest = baselines if baselines is not None else load_prompt_baselines()
    candidate = desired_prompt_candidate(source=source, baselines=manifest)
    observed_prompt = read_workspace_prompt() if current_prompt is None else current_prompt
    observed_bytes = observed_prompt.encode("utf-8")
    observed_identity = (len(observed_bytes), _sha256(observed_bytes))
    observed_matches = [
        item for item in manifest["managed_prompts"]
        if item["qwenpaw_version"] == QWENPAW_VERSION
        and (item["installed_bytes"], item["installed_sha256"]) == observed_identity
    ]
    if len(observed_matches) != 1:
        raise RuntimeError("existing AI_NOVEL_WORLD.md is missing, unknown, or author-modified")
    observed_files = read_system_prompt_files() if current_files is None else _validate_prompt_file_list(current_files)
    if candidate["baseline"]["prompt_files_policy"] == "exclude-exact-official-defaults":
        desired_files, decisions, excluded_contents = _desired_system_prompt_files(
            manifest, observed_files,
        )
    else:
        # The stable A prompt remains paired with the full host safety list.
        # An unadopted candidate must never narrow a fresh/current Agent.
        desired_files, decisions, excluded_contents = list(observed_files), {}, {}
    return {
        "expected_prompt": observed_prompt,
        "expected_files": observed_files,
        "desired_prompt": candidate["content"],
        "desired_files": desired_files,
        "managed_prompt_version": candidate["baseline"]["prompt_version"],
        "observed_managed_prompt_version": observed_matches[0]["prompt_version"],
        "default_prompt_decisions": decisions,
        "excluded_default_contents": excluded_contents,
    }


def _desired_system_prompt_files(
    manifest: dict[str, Any], observed_files: list[str],
) -> tuple[list[str], dict[str, str], dict[str, str]]:
    desired_files: list[str] = []
    decisions: dict[str, str] = {}
    excluded_contents: dict[str, str] = {}
    for filename in observed_files:
        if filename not in EXCLUDABLE_DEFAULT_PROMPTS:
            desired_files.append(filename)
            continue
        content = read_workspace_prompt(filename)
        content_bytes = content.encode("utf-8")
        official_identity = _official_installed_identity(manifest, filename)
        if official_identity is not None and (len(content_bytes), _sha256(content_bytes)) == official_identity:
            decisions[filename] = "exclude-exact-official-match"
            excluded_contents[filename] = content
        else:
            decisions[filename] = "preserve-not-exact-official-match"
            desired_files.append(filename)
    if PROMPT_FILE not in desired_files:
        desired_files.append(PROMPT_FILE)
    return desired_files, decisions, excluded_contents


def _verify_excluded_default_prompts(plan: dict[str, Any]) -> None:
    for filename, expected in plan["excluded_default_contents"].items():
        if read_workspace_prompt(filename) != expected:
            raise RuntimeError(f"concurrent default prompt change detected: {filename}")


def initialize_created_agent_prompt(
    *, baselines: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Initialize a freshly created Agent without claiming old workspace data."""
    manifest = baselines if baselines is not None else load_prompt_baselines()
    candidate = desired_prompt_candidate(baselines=manifest)
    try:
        existing = read_workspace_prompt()
    except HTTPError as error:
        if error.code != 404:
            raise
    else:
        # A recreated Agent can expose a retained workspace.  Treat it exactly
        # like an existing Agent and never overwrite an unknown prompt.
        return apply_prompt_configuration(build_prompt_configuration_plan(
            baselines=manifest, current_prompt=existing,
        ))
    observed_files = read_system_prompt_files()
    if candidate["baseline"]["prompt_files_policy"] == "exclude-exact-official-defaults":
        desired_files, decisions, excluded_contents = _desired_system_prompt_files(
            manifest, observed_files,
        )
    else:
        desired_files, decisions, excluded_contents = list(observed_files), {}, {}
    _put_workspace_prompt(candidate["content"])
    if read_workspace_prompt() != candidate["content"]:
        raise RuntimeError("public managed prompt initialization readback mismatch")
    _verify_excluded_default_prompts({
        "excluded_default_contents": excluded_contents,
    })
    _replace_verified(
        label="system prompt list", expected=observed_files,
        desired=desired_files, read=read_system_prompt_files,
        write=_put_system_prompt_files,
    )
    return {
        "prompt_updated": True,
        "system_prompt_files_updated": observed_files != desired_files,
        "managed_prompt_version": candidate["baseline"]["prompt_version"],
        "system_prompt_files": desired_files,
        "default_prompt_decisions": decisions,
        "compensation_used": False,
    }


def _put_workspace_prompt(content: str) -> None:
    request_json(
        f"/api/workspace/files/{PROMPT_FILE}", method="PUT",
        body={"content": content}, agent_id=AGENT_ID,
    )


def _put_system_prompt_files(files: list[str]) -> None:
    request_json(
        "/api/workspace/system-prompt-files", method="PUT",
        body=files, agent_id=AGENT_ID,
    )


def _replace_verified(
    *, label: str, expected: object, desired: object,
    read: Callable[[], object], write: Callable[[Any], None],
) -> bool:
    before = read()
    if before != expected:
        raise RuntimeError(f"concurrent {label} change detected before write")
    if expected == desired:
        return False
    write(desired)
    if read() != desired:
        raise RuntimeError(f"public {label} write readback mismatch")
    return True


def _compensate_prompt_configuration(plan: dict[str, Any]) -> None:
    """One bounded compensation, restoring the safer list-before-prompt order."""
    for label, expected, candidate, read, write in (
        ("system prompt list", plan["expected_files"], plan["desired_files"],
         read_system_prompt_files, _put_system_prompt_files),
        ("managed prompt", plan["expected_prompt"], plan["desired_prompt"],
         read_workspace_prompt, _put_workspace_prompt),
    ):
        observed = read()
        if observed == expected:
            continue
        if observed != candidate:
            raise RuntimeError(f"concurrent {label} change detected; compensation refused")
        write(expected)
        if read() != expected:
            raise RuntimeError(f"{label} compensation readback mismatch")


def apply_prompt_configuration(plan: dict[str, Any]) -> dict[str, Any]:
    """Apply candidate prompt first, then narrow the prompt list, with readback."""
    changed_prompt = False
    changed_files = False
    try:
        changed_prompt = _replace_verified(
            label="managed prompt", expected=plan["expected_prompt"],
            desired=plan["desired_prompt"], read=read_workspace_prompt,
            write=_put_workspace_prompt,
        )
        _verify_excluded_default_prompts(plan)
        changed_files = _replace_verified(
            label="system prompt list", expected=plan["expected_files"],
            desired=plan["desired_files"], read=read_system_prompt_files,
            write=_put_system_prompt_files,
        )
    except (HTTPError, URLError, TimeoutError, OSError, RuntimeError) as error:
        try:
            _compensate_prompt_configuration(plan)
        except (HTTPError, URLError, TimeoutError, OSError, RuntimeError) as compensation_error:
            raise RuntimeError(
                f"prompt configuration failed and bounded compensation failed: {compensation_error}"
            ) from error
        raise RuntimeError("prompt configuration failed; original state restored") from error
    return {
        "prompt_updated": changed_prompt,
        "system_prompt_files_updated": changed_files,
        "managed_prompt_version": plan["managed_prompt_version"],
        "system_prompt_files": list(plan["desired_files"]),
        "default_prompt_decisions": dict(plan["default_prompt_decisions"]),
        "compensation_used": False,
    }


def configure_prompt_only(*, source: Path = PROMPT_SOURCE) -> dict[str, Any]:
    """Update only the managed prompt and ordered prompt list of an existing Agent."""
    agents = request_json("/api/agents")
    if not isinstance(agents, dict) or not isinstance(agents.get("agents"), list):
        raise RuntimeError("invalid public Agent inventory")
    ids = [item.get("id") if isinstance(item, dict) else None for item in agents["agents"]]
    if AGENT_ID not in ids:
        raise RuntimeError("prompt-only update requires the existing novel Agent")
    return {"agent_id": AGENT_ID, "prompt_only": True, **apply_prompt_configuration(
        build_prompt_configuration_plan(source=source),
    )}


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
    if not isinstance(agents, dict) or not isinstance(agents.get("agents"), list):
        raise RuntimeError("invalid public Agent inventory")
    agent_ids = {
        item["id"] for item in agents["agents"]
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]
    }
    if len(agent_ids) != len(agents["agents"]):
        raise RuntimeError("invalid public Agent inventory")
    created = AGENT_ID not in agent_ids
    # Reject an ambiguous old snapshot before any Agent/configuration write.
    skill_enable_plan(created=created, previous=previous_skill_state)
    baselines = load_prompt_baselines()
    # Existing prompt ownership conflicts must fail before the no-op Agent
    # update, Skill restoration, or any tool toggle.
    prompt_plan = None if created else build_prompt_configuration_plan(baselines=baselines)
    if created:
        request_json(
            "/api/agents",
            method="POST",
            body={**desired_agent_payload(), "skill_names": []},
        )
        prompt_result = initialize_created_agent_prompt(baselines=baselines)
    else:
        assert prompt_plan is not None
        # Routine plugin reinstall/configuration never adopts a new prompt.
        # The explicit prompt-only path is the sole existing-Agent writer.
        prompt_result = {
            "prompt_updated": False,
            "system_prompt_files_updated": False,
            "managed_prompt_version": prompt_plan["observed_managed_prompt_version"],
            "system_prompt_files": list(prompt_plan["expected_files"]),
            "default_prompt_decisions": {
                filename: (
                    "eligible-but-preserved; use explicit prompt-only"
                    if decision == "exclude-exact-official-match" else decision
                )
                for filename, decision in prompt_plan["default_prompt_decisions"].items()
            },
            "compensation_used": False,
        }
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
        **prompt_result,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous-skill-state", type=Path)
    parser.add_argument("--restore-skills-only", action="store_true")
    parser.add_argument("--prompt-only", action="store_true")
    args = parser.parse_args()
    try:
        previous = load_previous_skill_state(args.previous_skill_state) if args.previous_skill_state else None
        if args.restore_skills_only and args.prompt_only:
            raise ValueError("restore-skills-only and prompt-only are mutually exclusive")
        if args.prompt_only and args.previous_skill_state:
            raise ValueError("prompt-only does not accept a Skill baseline")
        if args.restore_skills_only and not previous:
            raise ValueError("narrow restore requires a nonempty previous Skill baseline")
        if args.prompt_only:
            result = configure_prompt_only()
        elif args.restore_skills_only:
            result = restore_skill_state(previous)
        else:
            result = configure(previous_skill_state=previous)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (AssertionError, OSError, ValueError, HTTPError, URLError, TimeoutError, RuntimeError) as error:
        print(f"Novel Agent configuration failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
