from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import sys
from types import ModuleType
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TOOLS = {
    "novel_get_context",
    "novel_get_document",
    "novel_search",
    "novel_get_workspace_context",
    "novel_prepare_selection_edit",
}


def load_script(name: str) -> ModuleType:
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ConfigureApi:
    def __init__(self, configure: ModuleType) -> None:
        self.configure = configure
        self.calls: list[tuple[str, str, object | None, str | None]] = []
        self.model = {
            "provider_id": "current-provider",
            "model": "MiniMax-M3",
        }
        self.agent_updates: list[dict[str, object]] = []
        self.tool_states = {
            configure.AGENT_ID: {
                name: name != "novel_get_workspace_context"
                for name in configure.TOOLS
            },
            "default": {
                name: name == "novel_get_workspace_context"
                for name in configure.TOOLS
            },
            "QwenPaw_QA_Agent_0.2": {
                name: name == "novel_search"
                for name in configure.TOOLS
            },
            "custom-agent": {name: False for name in configure.TOOLS},
        }

    def request_json(
        self,
        path: str,
        *,
        method: str = "GET",
        body: object | None = None,
        agent_id: str | None = None,
    ) -> object:
        self.calls.append((path, method, body, agent_id))
        if path == "/api/agents" and method == "GET":
            return {
                "agents": [
                    {"id": agent}
                    for agent in self.tool_states
                ],
            }
        if path == f"/api/agents/{self.configure.AGENT_ID}":
            assert method == "PUT"
            assert isinstance(body, dict)
            self.agent_updates.append(dict(body))
            return {"id": self.configure.AGENT_ID}
        if path == "/api/skills":
            assert agent_id == self.configure.AGENT_ID
            return [
                {
                    "name": name,
                    "source": "plugin:ai-novel-world-2026",
                    "enabled": False,
                }
                for name in self.configure.SKILLS
            ]
        if path == "/api/skills/batch-enable":
            assert agent_id == self.configure.AGENT_ID
            return {
                "results": {
                    name: {"success": True}
                    for name in self.configure.SKILLS
                },
            }
        if path == "/api/tools":
            assert agent_id in self.tool_states
            return [
                {"name": name, "enabled": enabled}
                for name, enabled in self.tool_states[agent_id].items()
            ]
        if path.startswith("/api/tools/") and path.endswith("/toggle"):
            assert method == "PATCH"
            assert agent_id in self.tool_states
            name = path.removeprefix("/api/tools/").removesuffix("/toggle")
            self.tool_states[agent_id][name] = not self.tool_states[agent_id][name]
            return {"enabled": self.tool_states[agent_id][name]}
        if path.startswith("/api/workspace/files/"):
            assert agent_id == self.configure.AGENT_ID
            return {"ok": True}
        if path == "/api/workspace/system-prompt-files":
            assert agent_id == self.configure.AGENT_ID
            return [self.configure.PROMPT_FILE]
        if path.startswith("/api/models/active"):
            assert method == "GET"
            return {"active_llm": dict(self.model)}
        raise AssertionError(f"unexpected request: {method} {path}")


class VerifyApi:
    def __init__(self, verifier: ModuleType) -> None:
        self.verifier = verifier
        self.calls: list[tuple[str, str | None]] = []
        self.agent_ids = {
            "default",
            "QwenPaw_QA_Agent_0.2",
            "custom-agent",
            verifier.NOVEL_AGENT_ID,
        }
        self.tool_states = {
            agent_id: {
                name: agent_id == verifier.NOVEL_AGENT_ID
                for name in verifier.NOVEL_TOOLS
            }
            for agent_id in self.agent_ids
        }
        self.skill_states = {
            agent_id: {name: agent_id == verifier.NOVEL_AGENT_ID
                       for name in verifier.NOVEL_SKILLS}
            for agent_id in self.agent_ids
        }
        self.model = {
            "provider_id": "current-provider",
            "model": "MiniMax-M3",
        }

    def get_json(self, path: str, *, agent_id: str | None = None) -> object:
        self.calls.append((path, agent_id))
        if path == "/api/pawapps":
            return {
                "apps": [
                    {
                        "id": self.verifier.APP_ID,
                        "version": self.verifier.APP_VERSION,
                    },
                ],
            }
        if path == f"/api/{self.verifier.APP_ID}/health":
            return {
                "app_id": self.verifier.APP_ID,
                "status": "ok",
                "ai_candidate_generation_enabled": True,
                "ai_authoritative_write_enabled": False,
                "generation_agent_id": self.verifier.NOVEL_AGENT_ID,
                "generation_model_policy": "follow-agent-effective",
                "model_verification_mode": "preflight-effective+provider-usage",
                "selection_edit_enabled": True,
                "selection_edit_operations": list(
                    self.verifier.SELECTION_EDIT_OPERATIONS
                ),
                "narration": {
                    "product_requested": False,
                    "lifecycle_status": "playback_only",
                    "playback_installed": True,
                    "digest_keyring_loaded": False,
                    "production_backend_installed": False,
                    "worker_running": False,
                    "reference_clone_ready": False,
                    "provider_selection_fingerprint_sha256": None,
                    "reason_code": None,
                },
                "narration_production": {
                    "product_requested": False,
                    "lifecycle_status": "playback_only",
                    "playback_installed": True,
                    "digest_keyring_loaded": False,
                    "production_backend_installed": False,
                    "worker_running": False,
                    "reference_clone_ready": False,
                    "reason_code": None,
                },
            }
        if path == "/api/agents":
            return {
                "agents": [
                    {"id": current_agent_id}
                    for current_agent_id in self.agent_ids
                ],
            }
        if path.startswith("/api/models/active"):
            return {"active_llm": dict(self.model)}
        if path == f"/api/{self.verifier.APP_ID}/generation-model":
            return {
                "agent_id": self.verifier.NOVEL_AGENT_ID,
                "policy": "follow-agent-effective",
                "provider_id": self.model["provider_id"],
                "model_id": self.model["model"],
            }
        if path == "/api/skills":
            return [
                {
                    "name": name,
                    "source": f"plugin:{self.verifier.APP_ID}",
                    "enabled": enabled,
                }
                for name, enabled in self.skill_states[agent_id].items()
            ]
        if path == "/api/tools":
            assert agent_id in self.tool_states
            return [
                {"name": name, "enabled": enabled}
                for name, enabled in self.tool_states[agent_id].items()
            ]
        if path == "/api/workspace/system-prompt-files":
            return [self.verifier.NOVEL_PROMPT_FILE]
        if path.startswith("/api/workspace/files/"):
            return {
                "content": (
                    "正文生成或重写必须调用 `prose-writing`；"
                    "每条命令最多一次成功调用 `novel_prepare_selection_edit`；"
                    "insufficient-shortening；insufficient-expansion；"
                    "review-size-mismatch"
                ),
            }
        if path == "/api/workspace/files":
            return [{"filename": self.verifier.NOVEL_PROMPT_FILE}]
        raise AssertionError(f"unexpected read: {path}")


def test_scripts_freeze_the_same_five_tool_contract_without_model_fields() -> None:
    configure = load_script("configure_qwenpaw_novel_agent")
    verifier = load_script("verify_qwenpaw_lab")

    assert set(configure.TOOLS) == EXPECTED_TOOLS
    assert verifier.NOVEL_TOOLS == EXPECTED_TOOLS
    assert configure.AGENT_ID == verifier.NOVEL_AGENT_ID
    payload = configure.desired_agent_payload()
    assert set(payload) == {"id", "name", "description", "language"}
    assert not {"model", "model_id", "provider", "provider_id"} & set(payload)


def test_repeated_configuration_converges_scope_without_rewriting_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure = load_script("configure_qwenpaw_novel_agent")
    api = ConfigureApi(configure)
    monkeypatch.setattr(configure, "request_json", api.request_json)

    first = configure.configure()
    first_toggle_count = sum(
        path.endswith("/toggle") for path, _method, _body, _agent in api.calls
    )
    second = configure.configure()
    final_toggle_count = sum(
        path.endswith("/toggle") for path, _method, _body, _agent in api.calls
    )

    assert first_toggle_count == 3
    assert final_toggle_count == first_toggle_count
    assert all(api.tool_states[configure.AGENT_ID].values())
    assert all(
        not enabled
        for agent_id, tools_by_name in api.tool_states.items()
        if agent_id != configure.AGENT_ID
        for enabled in tools_by_name.values()
    )
    assert first["enabled_tools"] == second["enabled_tools"] == configure.TOOLS
    assert first["effective_model"] == second["effective_model"] == api.model
    assert all(
        not {"model", "model_id", "provider", "provider_id"} & set(payload)
        for payload in api.agent_updates
    )
    assert not any(
        path.startswith("/api/models") and method != "GET"
        for path, method, _body, _agent in api.calls
    )


def test_verifier_reads_all_agent_tool_scopes_and_accepts_target_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier = load_script("verify_qwenpaw_lab")
    monkeypatch.setattr(verifier, "EXPECTED_TTS_RUNTIME", "disabled")
    monkeypatch.setattr(verifier, "EXPECTED_TTS_PRODUCT", "disabled")
    monkeypatch.setattr(verifier, "EXPECTED_TTS_VALIDATION", "disabled")
    api = VerifyApi(verifier)
    monkeypatch.setattr(verifier, "get_json", api.get_json)

    result = verifier.verify()

    enabled = result["enabled_novel_tools"]
    assert set(enabled[verifier.NOVEL_AGENT_ID]) == EXPECTED_TOOLS
    assert all(
        names == []
        for agent_id, names in enabled.items()
        if agent_id != verifier.NOVEL_AGENT_ID
    )
    queried_tool_agents = {
        agent_id
        for path, agent_id in api.calls
        if path == "/api/tools"
    }
    assert queried_tool_agents == api.agent_ids
    assert result["novel_model"] == api.model


def test_verifier_requires_the_complete_selection_edit_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier = load_script("verify_qwenpaw_lab")
    monkeypatch.setattr(verifier, "EXPECTED_TTS_RUNTIME", "disabled")
    monkeypatch.setattr(verifier, "EXPECTED_TTS_PRODUCT", "disabled")
    monkeypatch.setattr(verifier, "EXPECTED_TTS_VALIDATION", "disabled")
    api = VerifyApi(verifier)
    original_get_json = api.get_json

    def get_json(path: str, *, agent_id: str | None = None) -> object:
        payload = original_get_json(path, agent_id=agent_id)
        if path == f"/api/{verifier.APP_ID}/health":
            assert isinstance(payload, dict)
            return {
                **payload,
                "selection_edit_operations": verifier.SELECTION_EDIT_OPERATIONS[:-1],
            }
        return payload

    monkeypatch.setattr(verifier, "get_json", get_json)

    with pytest.raises(AssertionError):
        verifier.verify()


@pytest.mark.parametrize("failure", ["missing-target", "enabled-non-target"])
def test_verifier_rejects_missing_or_leaked_workspace_tool_scope(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    verifier = load_script("verify_qwenpaw_lab")
    monkeypatch.setattr(verifier, "EXPECTED_TTS_RUNTIME", "disabled")
    monkeypatch.setattr(verifier, "EXPECTED_TTS_PRODUCT", "disabled")
    monkeypatch.setattr(verifier, "EXPECTED_TTS_VALIDATION", "disabled")
    api = VerifyApi(verifier)
    if failure == "missing-target":
        del api.tool_states[verifier.NOVEL_AGENT_ID][
            "novel_get_workspace_context"
        ]
    else:
        api.tool_states["custom-agent"]["novel_get_workspace_context"] = True
    monkeypatch.setattr(verifier, "get_json", api.get_json)

    with pytest.raises(AssertionError):
        verifier.verify()


def test_verifier_accepts_ready_hidden_validation_pipeline_without_visibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier = load_script("verify_qwenpaw_lab")
    monkeypatch.setattr(verifier, "EXPECTED_TTS_RUNTIME", "ready")
    monkeypatch.setattr(verifier, "EXPECTED_TTS_PRODUCT", "disabled")
    monkeypatch.setattr(verifier, "EXPECTED_TTS_VALIDATION", "ready")
    monkeypatch.setattr(
        verifier,
        "TTS_VALIDATION_NOVEL_ID",
        "11111111-1111-4111-8111-111111111111",
    )
    monkeypatch.setattr(
        verifier,
        "TTS_VALIDATION_DOCUMENT_ID",
        "22222222-2222-4222-8222-222222222222",
    )
    api = VerifyApi(verifier)
    original_get_json = api.get_json

    def get_json(path: str, *, agent_id: str | None = None) -> object:
        payload = original_get_json(path, agent_id=agent_id)
        if path != f"/api/{verifier.APP_ID}/health":
            return payload
        assert isinstance(payload, dict)
        return {
                **payload,
                "narration": {
                    "product_requested": True,
                    "lifecycle_status": "ready",
                    "playback_installed": True,
                    "digest_keyring_loaded": True,
                    "production_backend_installed": True,
                    "worker_running": True,
                    "reference_clone_ready": False,
                    "provider_selection_fingerprint_sha256": "a" * 64,
                    "reason_code": None,
                },
            "narration_production": {
                **verifier.expected_narration_production(),
                "provider_selection_fingerprint_sha256": "a" * 64,
            },
        }

    monkeypatch.setattr(verifier, "get_json", get_json)

    def request_json(
        path: str,
        *,
        agent_id: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> object:
        del agent_id, headers
        overview = (
            f"/api/{verifier.APP_ID}/novels/"
            f"{verifier.TTS_VALIDATION_NOVEL_ID}/narration-overview"
        )
        if path == overview:
            return verifier.JsonHttpResponse(
                status=200,
                headers={"cache-control": "no-store"},
                payload={
                    "contract_version": "narration-settings-api/1",
                    "novel_id": verifier.TTS_VALIDATION_NOVEL_ID,
                    "capabilities": verifier.T2_CAPABILITY_MATRIX,
                    "runtime": {"product_visible": False},
                },
            )
        return verifier.JsonHttpResponse(
            status=404,
            headers={"cache-control": "no-store"},
            payload=verifier.HIDDEN_TTS_NOT_FOUND,
        )

    monkeypatch.setattr(verifier, "request_json", request_json)

    result = verifier.verify()

    assert result["narration"]["product_requested"] is True
    assert result["narration"]["lifecycle_status"] == "ready"
    assert result["narration_production"]["worker_running"] is True


@pytest.fixture
def skill_verifier(monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, VerifyApi]:
    verifier = load_script("verify_qwenpaw_lab")
    for name in ("EXPECTED_TTS_RUNTIME", "EXPECTED_TTS_PRODUCT", "EXPECTED_TTS_VALIDATION"):
        monkeypatch.setattr(verifier, name, "disabled")
    api = VerifyApi(verifier)
    monkeypatch.setattr(verifier, "get_json", api.get_json)
    return verifier, api


@pytest.mark.parametrize("state", ["all-on", "mixed", "all-off", "unknown"])
def test_skill_preservation_and_readiness_are_independent(
    skill_verifier: tuple[ModuleType, VerifyApi], state: str,
) -> None:
    verifier, api = skill_verifier
    current = api.skill_states[verifier.NOVEL_AGENT_ID]
    optional_ids = {item.skill_id for item in verifier.packaged_approvals()}
    if state == "mixed":
        current.update({name: False for name in optional_ids})
        # These generic helpers are not the primary dependency of every task.
        current.update({name: False for name in (
            "scene-craft", "dialogue-craft", "continuity-check",
        )})
    elif state == "all-off":
        current.update({name: False for name in current})
    previous = None if state == "unknown" else dict(current)

    result = verifier.verify_skill_state(previous)

    assert result["state_preserved"] is (None if state == "unknown" else True)
    assert result["writing_skills_ready"] is (state != "all-off")
    assert result["scope_isolated"] is True
    assert result["current_skill_state"] == current
    assert set(result["optional_skill_status"]) == optional_ids
    assert all(item["ready"] is (state in {"all-on", "unknown"})
               for item in result["optional_skill_status"].values())
    assert {path for path, _agent in api.calls} == {"/api/agents", "/api/skills"}
    assert {agent for path, agent in api.calls if path == "/api/skills"} == api.agent_ids
    if state == "all-off":
        with pytest.raises(AssertionError, match="Skill verification failed"):
            verifier.verify(previous)
    else:
        assert verifier.verify(previous)["writing_skills_ready"] is True


@pytest.mark.parametrize("failure", ["disabled", "missing", "empty-inventory", "missing-agent"])
def test_skill_readiness_reports_only_the_affected_tasks(
    skill_verifier: tuple[ModuleType, VerifyApi], failure: str,
) -> None:
    verifier, api = skill_verifier
    current = api.skill_states[verifier.NOVEL_AGENT_ID]
    previous = dict(current)
    if failure == "disabled":
        current["prose-writing"] = False
    elif failure == "missing":
        del current["prose-writing"]
    elif failure == "empty-inventory":
        current.clear()
    else:
        api.agent_ids.remove(verifier.NOVEL_AGENT_ID)

    result = verifier.verify_skill_state(previous)

    assert result["state_preserved"] is False
    assert result["writing_skills_ready"] is False
    assert "prose-writing" in result["missing_primary_skills"]
    assert result["skill_state_differences"]["prose-writing"] == {
        "previous": True, "current": False if failure == "disabled" else None,
    }
    tasks = result["task_readiness"]
    assert tasks["chapter_body"]["ready"] is False
    assert tasks["selection_edit:rewrite"]["ready"] is False
    other_tasks_ready = failure not in {"missing-agent", "empty-inventory"}
    assert tasks["selection_edit:review"]["ready"] is other_tasks_ready
    assert tasks["chapter_outline"]["ready"] is other_tasks_ready


def test_preservation_lists_added_and_removed_skills_without_hiding_supported_losses(
    skill_verifier: tuple[ModuleType, VerifyApi],
) -> None:
    verifier, api = skill_verifier
    previous = dict(api.skill_states[verifier.NOVEL_AGENT_ID])
    added = verifier.packaged_approvals()[0].skill_id
    previous.pop(added)
    previous["retired-method"] = True
    result = verifier.verify_skill_state(previous)
    assert result["state_preserved"] is True
    assert result["added_skills"] == [added]
    assert result["removed_skills"] == ["retired-method"]
    del api.skill_states[verifier.NOVEL_AGENT_ID]["continuity-check"]
    result = verifier.verify_skill_state(previous)
    assert result["state_preserved"] is False
    assert "continuity-check" in result["skill_state_differences"]
    assert result["writing_skills_ready"] is True


@pytest.mark.parametrize("agent_id", ["default", "QwenPaw_QA_Agent_0.2", "custom-agent"])
def test_skill_scope_rejects_pollution_in_every_other_agent(
    skill_verifier: tuple[ModuleType, VerifyApi], agent_id: str,
) -> None:
    verifier, api = skill_verifier
    api.skill_states[agent_id]["prose-writing"] = True
    result = verifier.verify_skill_state()
    assert result["scope_isolated"] is False
    assert result["writing_skills_ready"] is True
    with pytest.raises(AssertionError, match="Skill verification failed"):
        verifier.verify()


@pytest.mark.parametrize("failure", ["missing-skill", "missing-reference", "symlink", "invalid-optional"])
def test_skill_readiness_checks_trusted_local_method_files(
    skill_verifier: tuple[ModuleType, VerifyApi],
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str,
) -> None:
    verifier, _api = skill_verifier
    local_root = tmp_path / "skills"
    shutil.copytree(verifier.SKILLS_ROOT, local_root)
    monkeypatch.setattr(verifier, "SKILLS_ROOT", local_root)
    if failure == "invalid-optional":
        optional = verifier.packaged_approvals()[0].skill_id
        (local_root / optional / "SKILL.md").write_text("changed", encoding="utf-8")
    elif failure == "missing-skill":
        (local_root / "prose-writing" / "SKILL.md").unlink()
    else:
        reference = local_root / "prose-writing" / "references" / "narrative-craft.md"
        reference.unlink()
        if failure == "symlink":
            reference.symlink_to(verifier._PROJECT_ROOT / "skills" / "prose-writing"
                                 / "references" / "narrative-craft.md")
    result = verifier.verify_skill_state()
    if failure == "invalid-optional":
        assert result["writing_skills_ready"] is True
        assert result["optional_skill_status"][optional]["method_available"] is False
        assert result["optional_skill_status"][optional]["ready"] is False
    else:
        assert result["writing_skills_ready"] is False
        assert result["missing_methods"] == {"prose-writing": "asset_missing_or_unsafe"}
        assert result["missing_primary_skills"] == ["prose-writing"]


@pytest.mark.parametrize("invalid", [{}, {"prose-writing": 1}, {"": True}])
def test_verifier_rejects_empty_or_non_boolean_previous_state(
    skill_verifier: tuple[ModuleType, VerifyApi], invalid: dict[str, Any],
) -> None:
    verifier, _api = skill_verifier
    with pytest.raises(ValueError, match="nonempty explicit boolean snapshot"):
        verifier.verify_skill_state(invalid)


@pytest.mark.parametrize("failure", ["unknown-enabled", "duplicate"])
def test_verifier_does_not_treat_ambiguous_public_state_as_disabled(
    skill_verifier: tuple[ModuleType, VerifyApi],
    monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    verifier, api = skill_verifier

    def get_json(path: str, *, agent_id: str | None = None) -> object:
        result = api.get_json(path, agent_id=agent_id)
        if path == "/api/skills":
            if failure == "duplicate":
                result.append(dict(result[0]))
            else:
                result[0].pop("enabled")
        return result

    monkeypatch.setattr(verifier, "get_json", get_json)
    with pytest.raises(AssertionError, match="public Skill"):
        verifier.verify_skill_state()


@pytest.mark.parametrize("failure", [None, "all-off", "changed", "polluted"])
def test_skills_only_cli_emits_diagnostics_and_enforces_each_gate(
    skill_verifier: tuple[ModuleType, VerifyApi], monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path, capsys: pytest.CaptureFixture[str], failure: str | None,
) -> None:
    verifier, api = skill_verifier
    current = api.skill_states[verifier.NOVEL_AGENT_ID]
    if failure == "all-off":
        current.update({name: False for name in current})
    previous = dict(current)
    if failure == "changed":
        # A disabled optional module breaks preservation but not task readiness.
        current[verifier.packaged_approvals()[0].skill_id] = False
    if failure == "polluted":
        api.skill_states["custom-agent"]["prose-writing"] = True
    snapshot = tmp_path / "previous.json"
    snapshot.write_text(json.dumps({
        "schema": "skill-enable-state/1", "base_url": verifier.BASE_URL,
        "agent_id": verifier.NOVEL_AGENT_ID, "skills": previous,
    }), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["verify", "--skills-only", "--previous-skill-state", str(snapshot)])
    if failure is None:
        verifier.main()
    else:
        with pytest.raises(SystemExit) as error:
            verifier.main()
        assert error.value.code == 1
    result = json.loads(capsys.readouterr().out)
    assert result["state_preserved"] is (failure != "changed")
    assert result["writing_skills_ready"] is (failure != "all-off")
    assert result["scope_isolated"] is (failure != "polluted")
    assert {path for path, _agent in api.calls} == {"/api/agents", "/api/skills"}


def test_skills_only_cli_without_baseline_reports_unknown(
    skill_verifier: tuple[ModuleType, VerifyApi], monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    verifier, _api = skill_verifier
    monkeypatch.setattr(sys, "argv", ["verify", "--skills-only"])
    verifier.main()
    assert json.loads(capsys.readouterr().out)["state_preserved"] is None


def test_default_cli_preserves_existing_health_and_tool_checks(
    skill_verifier: tuple[ModuleType, VerifyApi], monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    verifier, api = skill_verifier
    monkeypatch.setattr(sys, "argv", ["verify"])
    verifier.main()
    result = json.loads(capsys.readouterr().out)
    assert result["health"] == "ok"
    assert result["state_preserved"] is None
    assert result["writing_skills_ready"] is True
    assert result["scope_isolated"] is True
    assert set(result["enabled_novel_tools"]) == api.agent_ids
    assert result["novel_model"] == api.model


@pytest.mark.parametrize("field", ["schema", "base_url", "agent_id"])
def test_skills_cli_reuses_snapshot_identity_validation_before_api_reads(
    skill_verifier: tuple[ModuleType, VerifyApi], monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path, field: str,
) -> None:
    verifier, api = skill_verifier
    previous = {
        "schema": "skill-enable-state/1", "base_url": verifier.BASE_URL,
        "agent_id": verifier.NOVEL_AGENT_ID,
        "skills": api.skill_states[verifier.NOVEL_AGENT_ID],
    }
    previous[field] = "wrong-identity"
    snapshot = tmp_path / "previous.json"
    snapshot.write_text(json.dumps(previous), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["verify", "--skills-only", "--previous-skill-state", str(snapshot)])
    with pytest.raises(SystemExit) as error:
        verifier.main()
    assert error.value.code == 1
    assert api.calls == []
