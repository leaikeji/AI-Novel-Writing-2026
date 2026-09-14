from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
from types import ModuleType
from urllib.error import HTTPError, URLError

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_configure() -> ModuleType:
    path = ROOT / "scripts" / "configure_qwenpaw_novel_agent.py"
    spec = importlib.util.spec_from_file_location("plan83_configure", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def add_managed_installed(
    manifest: dict[str, object], content: str, *, prompt_version: str,
) -> None:
    source = (content + "\n").encode("utf-8")
    installed = content.encode("utf-8")
    managed = manifest["managed_prompts"]
    assert isinstance(managed, list)
    managed.append({
        "prompt_version": prompt_version,
        "plugin_version": "0.4.0",
        "qwenpaw_version": "2.2.1",
        "filename": "AI_NOVEL_WORLD.md",
        "source_type": "repository-managed",
        "prompt_files_policy": "preserve-current",
        "source_bytes": len(source),
        "source_sha256": digest(source),
        "installed_bytes": len(installed),
        "installed_sha256": digest(installed),
    })


def set_official_installed(
    manifest: dict[str, object], filename: str, content: str,
) -> None:
    official = manifest["official_templates"]
    assert isinstance(official, list)
    entry = next(item for item in official if item["filename"] == filename)
    raw = (content + "\n").encode("utf-8")
    installed = content.encode("utf-8")
    entry.update({
        "source_bytes": len(raw),
        "source_sha256": digest(raw),
        "installed_bytes": len(installed),
        "installed_sha256": digest(installed),
    })


class PromptApi:
    def __init__(
        self, configure: ModuleType, *, prompt: str,
        prompt_files: list[str] | None = None,
    ) -> None:
        self.configure = configure
        self.files = {
            configure.PROMPT_FILE: prompt,
            "AGENTS.md": "author-specific-agents",
            "SOUL.md": "official-soul",
            "PROFILE.md": "official-profile",
        }
        self.prompt_files = prompt_files or [
            "AGENTS.md", "SOUL.md", "PROFILE.md", configure.PROMPT_FILE,
        ]
        self.calls: list[tuple[str, str]] = []
        self.fail_list_put_once = False

    def request_json(
        self, path: str, *, method: str = "GET", body: object | None = None,
        agent_id: str | None = None,
    ) -> object:
        self.calls.append((method, path))
        if path == "/api/agents":
            assert method == "GET" and agent_id is None
            return {"agents": [{"id": self.configure.AGENT_ID}]}
        if path.startswith("/api/workspace/files/"):
            assert agent_id == self.configure.AGENT_ID
            filename = path.rsplit("/", 1)[-1]
            if method == "PUT":
                assert isinstance(body, dict) and isinstance(body.get("content"), str)
                self.files[filename] = body["content"]
                return {"content": self.files[filename]}
            assert method == "GET"
            return {"content": self.files[filename]}
        if path == "/api/workspace/system-prompt-files":
            assert agent_id == self.configure.AGENT_ID
            if method == "PUT":
                assert isinstance(body, list)
                self.prompt_files = list(body)
                if self.fail_list_put_once:
                    self.fail_list_put_once = False
                    raise URLError("lost acknowledgement")
            else:
                assert method == "GET"
            return list(self.prompt_files)
        raise AssertionError(f"prompt-only path touched unrelated API: {method} {path}")


class FreshPromptApi(PromptApi):
    def __init__(self, configure: ModuleType) -> None:
        super().__init__(configure, prompt="unused")
        del self.files[configure.PROMPT_FILE]

    def request_json(
        self, path: str, *, method: str = "GET", body: object | None = None,
        agent_id: str | None = None,
    ) -> object:
        if path == f"/api/workspace/files/{self.configure.PROMPT_FILE}":
            self.calls.append((method, path))
            assert agent_id == self.configure.AGENT_ID
            if method == "GET" and self.configure.PROMPT_FILE not in self.files:
                raise HTTPError(path, 404, "missing", None, None)
            if method == "PUT":
                assert isinstance(body, dict) and isinstance(body.get("content"), str)
                self.files[self.configure.PROMPT_FILE] = body["content"]
                return {"content": body["content"]}
            return {"content": self.files[self.configure.PROMPT_FILE]}
        return super().request_json(path, method=method, body=body, agent_id=agent_id)


def prompt_manifest(configure: ModuleType) -> dict[str, object]:
    manifest = deepcopy(configure.load_prompt_baselines())
    set_official_installed(manifest, "SOUL.md", "official-soul")
    set_official_installed(manifest, "PROFILE.md", "official-profile")
    return manifest


def test_manifest_freezes_official_v221_and_both_managed_prompt_generations() -> None:
    configure = load_configure()
    manifest = configure.load_prompt_baselines()

    assert manifest["schema"] == "agent-prompt-baselines/2"
    assert manifest["serialization"] == "utf8-remove-single-trailing-lf/1"
    official = {item["filename"]: item for item in manifest["official_templates"]}
    assert official["AGENTS.md"]["source_sha256"] == "240b79beb71ca8799ce50f23b9c28615e99cdda8727543a70dd84ec6bb5f472c"
    assert official["SOUL.md"]["installed_sha256"] == "6da1cb358b16ae88214b6cbbfb478d7b5b1abc0ff40306a8053fee5094433489"
    assert official["PROFILE.md"]["installed_sha256"] == "3b40f9b7c03403164ec55dba589010482a135f7c0a42b326a92be11823966b75"
    managed = {item["prompt_version"]: item for item in manifest["managed_prompts"]}
    assert set(managed) == {"pre-plan83-v0.3", "plan83-v0.4-candidate"}
    active = configure.desired_prompt_candidate(baselines=manifest)
    candidate = configure.desired_prompt_candidate(
        source=configure.PLAN83_CANDIDATE_SOURCE, baselines=manifest,
    )
    assert active["baseline"]["prompt_version"] == "pre-plan83-v0.3"
    assert candidate["baseline"]["prompt_version"] == "plan83-v0.4-candidate"


def test_serialization_removes_exactly_one_terminal_lf_without_stripping() -> None:
    configure = load_configure()

    assert configure.serialize_prompt_source(b"text \n") == b"text "
    assert configure.serialize_prompt_source(b"text\n\n") == b"text\n"
    assert configure.serialize_prompt_source("中文 ".encode()) == "中文 ".encode()


def test_plan_excludes_only_exact_official_soul_and_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure = load_configure()
    manifest = prompt_manifest(configure)
    candidate = configure.desired_prompt_candidate(
        source=configure.PLAN83_CANDIDATE_SOURCE, baselines=manifest,
    )["content"]
    api = PromptApi(configure, prompt=candidate)
    monkeypatch.setattr(configure, "request_json", api.request_json)

    plan = configure.build_prompt_configuration_plan(
        baselines=manifest, source=configure.PLAN83_CANDIDATE_SOURCE,
    )

    assert plan["desired_files"] == ["AGENTS.md", configure.PROMPT_FILE]
    assert plan["default_prompt_decisions"] == {
        "SOUL.md": "exclude-exact-official-match",
        "PROFILE.md": "exclude-exact-official-match",
    }
    assert api.files["SOUL.md"] == "official-soul"
    assert api.files["PROFILE.md"] == "official-profile"
    assert not any(method == "PUT" for method, _path in api.calls)


def test_prompt_file_policy_is_not_coupled_to_candidate_version_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure = load_configure()
    manifest = prompt_manifest(configure)
    candidate_entry = next(
        item for item in manifest["managed_prompts"]
        if item["prompt_files_policy"] == "exclude-exact-official-defaults"
    )
    candidate_entry["prompt_version"] = "renamed-future-candidate"
    candidate = configure.desired_prompt_candidate(
        source=configure.PLAN83_CANDIDATE_SOURCE, baselines=manifest,
    )["content"]
    api = PromptApi(configure, prompt=candidate)
    monkeypatch.setattr(configure, "request_json", api.request_json)

    plan = configure.build_prompt_configuration_plan(
        baselines=manifest, source=configure.PLAN83_CANDIDATE_SOURCE,
    )

    assert plan["managed_prompt_version"] == "renamed-future-candidate"
    assert plan["desired_files"] == ["AGENTS.md", configure.PROMPT_FILE]


def test_unknown_author_prompt_fails_before_any_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure = load_configure()
    api = PromptApi(configure, prompt="author changed this prompt")
    monkeypatch.setattr(configure, "request_json", api.request_json)

    with pytest.raises(RuntimeError, match="author-modified"):
        configure.configure_prompt_only()

    assert not any(method != "GET" for method, _path in api.calls)
    assert all(not path.startswith(("/api/models", "/api/skills", "/api/tools"))
               for _method, path in api.calls)


def test_default_prompt_only_keeps_stable_a_and_full_host_prompt_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure = load_configure()
    manifest = prompt_manifest(configure)
    active = configure.desired_prompt_candidate(baselines=manifest)["content"]
    api = PromptApi(configure, prompt=active)
    monkeypatch.setattr(configure, "request_json", api.request_json)
    monkeypatch.setattr(configure, "load_prompt_baselines", lambda: manifest)

    result = configure.configure_prompt_only()

    assert result["managed_prompt_version"] == "pre-plan83-v0.3"
    assert result["system_prompt_files"] == [
        "AGENTS.md", "SOUL.md", "PROFILE.md", configure.PROMPT_FILE,
    ]
    assert not any(method == "PUT" for method, _path in api.calls)


def test_regular_configure_unknown_prompt_stops_before_agent_skill_or_tool_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure = load_configure()
    api = PromptApi(configure, prompt="author changed this prompt")
    monkeypatch.setattr(configure, "request_json", api.request_json)

    with pytest.raises(RuntimeError, match="author-modified"):
        configure.configure()

    assert not any(method != "GET" for method, _path in api.calls)


def test_fresh_agent_initialization_writes_managed_prompt_and_keeps_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure = load_configure()
    manifest = prompt_manifest(configure)
    api = FreshPromptApi(configure)
    monkeypatch.setattr(configure, "request_json", api.request_json)

    result = configure.initialize_created_agent_prompt(baselines=manifest)

    assert result["managed_prompt_version"] == "pre-plan83-v0.3"
    assert api.prompt_files == [
        "AGENTS.md", "SOUL.md", "PROFILE.md", configure.PROMPT_FILE,
    ]
    assert set(api.files) == {
        "AGENTS.md", "SOUL.md", "PROFILE.md", configure.PROMPT_FILE,
    }
    assert api.files[configure.PROMPT_FILE] == configure.desired_prompt_candidate(
        baselines=manifest,
    )["content"]


def test_prompt_only_writes_prompt_then_list_and_touches_no_other_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure = load_configure()
    manifest = prompt_manifest(configure)
    old_prompt = "old-managed-prompt"
    add_managed_installed(manifest, old_prompt, prompt_version="fixture-old")
    api = PromptApi(configure, prompt=old_prompt)
    monkeypatch.setattr(configure, "request_json", api.request_json)
    monkeypatch.setattr(configure, "load_prompt_baselines", lambda: manifest)

    result = configure.configure_prompt_only(source=configure.PLAN83_CANDIDATE_SOURCE)

    puts = [path for method, path in api.calls if method == "PUT"]
    assert puts == [
        f"/api/workspace/files/{configure.PROMPT_FILE}",
        "/api/workspace/system-prompt-files",
    ]
    assert result["prompt_only"] is True
    assert result["system_prompt_files"] == ["AGENTS.md", configure.PROMPT_FILE]
    assert all(not path.startswith(("/api/models", "/api/skills", "/api/tools"))
               for _method, path in api.calls)


def test_lost_list_acknowledgement_gets_one_bounded_safe_order_compensation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure = load_configure()
    manifest = prompt_manifest(configure)
    old_prompt = "old-managed-prompt"
    add_managed_installed(manifest, old_prompt, prompt_version="fixture-old")
    api = PromptApi(configure, prompt=old_prompt)
    api.fail_list_put_once = True
    monkeypatch.setattr(configure, "request_json", api.request_json)

    plan = configure.build_prompt_configuration_plan(
        baselines=manifest, source=configure.PLAN83_CANDIDATE_SOURCE,
    )
    with pytest.raises(RuntimeError, match="original state restored"):
        configure.apply_prompt_configuration(plan)

    assert api.prompt_files == plan["expected_files"]
    assert api.files[configure.PROMPT_FILE] == old_prompt
    puts = [path for method, path in api.calls if method == "PUT"]
    assert puts == [
        f"/api/workspace/files/{configure.PROMPT_FILE}",
        "/api/workspace/system-prompt-files",
        "/api/workspace/system-prompt-files",
        f"/api/workspace/files/{configure.PROMPT_FILE}",
    ]


def test_default_prompt_change_before_list_write_aborts_and_restores_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure = load_configure()
    manifest = prompt_manifest(configure)
    old_prompt = "old-managed-prompt"
    add_managed_installed(manifest, old_prompt, prompt_version="fixture-old")
    api = PromptApi(configure, prompt=old_prompt)
    monkeypatch.setattr(configure, "request_json", api.request_json)
    plan = configure.build_prompt_configuration_plan(
        baselines=manifest, source=configure.PLAN83_CANDIDATE_SOURCE,
    )
    api.files["SOUL.md"] = "author changed soul"

    with pytest.raises(RuntimeError, match="original state restored"):
        configure.apply_prompt_configuration(plan)

    assert api.prompt_files == plan["expected_files"]
    assert api.files[configure.PROMPT_FILE] == old_prompt
    assert api.files["SOUL.md"] == "author changed soul"
