import json

import pytest

from scripts import configure_qwenpaw_novel_agent as configuration


def test_capture_preserves_disabled_and_removed_ids_without_private_reads(monkeypatch):
    calls = []
    def public(path, **kwargs):
        calls.append((path, kwargs))
        if path == "/api/agents":
            return {"agents": [{"id": configuration.AGENT_ID}]}
        return [
            {"name": "old-module", "source": "plugin:ai-novel-world-2026", "enabled": False},
            {"name": "prose-writing", "source": "plugin:ai-novel-world-2026", "enabled": True},
            {"name": "unrelated", "source": "builtin", "enabled": True},
        ]
    monkeypatch.setattr(configuration, "request_json", public)
    result = configuration.capture_skill_state()
    assert result["skills"] == {"old-module": False, "prose-writing": True}
    assert [path for path, _ in calls] == ["/api/agents", "/api/skills"]


def test_capture_new_agent_never_reads_default_agent_skills(monkeypatch):
    def public(path, **kwargs):
        assert path == "/api/agents"
        return {"agents": [{"id": "default"}]}
    monkeypatch.setattr(configuration, "request_json", public)
    assert configuration.capture_skill_state()["skills"] == {}


@pytest.mark.parametrize("enabled", [None, "false", 0])
def test_ambiguous_enabled_state_stops_before_install(monkeypatch, enabled):
    def public(path, **kwargs):
        if path == "/api/agents":
            return {"agents": [{"id": configuration.AGENT_ID}]}
        return [{"name": "prose-writing", "source": "plugin:ai-novel-world-2026", "enabled": enabled}]
    monkeypatch.setattr(configuration, "request_json", public)
    with pytest.raises(RuntimeError, match="invalid public Skill state"):
        configuration.capture_skill_state()


def test_recovery_snapshot_is_bound_to_public_host_and_agent(tmp_path):
    path = tmp_path / "state.json"
    value = {"schema": "skill-enable-state/1", "base_url": configuration.BASE_URL,
             "agent_id": configuration.AGENT_ID, "skills": {"prose-writing": False}}
    path.write_text(json.dumps(value))
    assert configuration.load_previous_skill_state(path) == {"prose-writing": False}
    for key, wrong in (("base_url", "http://another-instance"), ("agent_id", "default"),
                       ("skills", {"prose-writing": "false"}), ("schema", "other")):
        path.write_text(json.dumps({**value, key: wrong}))
        with pytest.raises(ValueError):
            configuration.load_previous_skill_state(path)


def test_existing_empty_inventory_is_not_a_new_install(monkeypatch):
    monkeypatch.setattr(configuration, "request_json", lambda path, **kw:
                        {"agents": [{"id": configuration.AGENT_ID}]} if path == "/api/agents" else [])
    with pytest.raises(RuntimeError, match="cannot capture"):
        configuration.capture_skill_state()
    with pytest.raises(ValueError, match="empty Skill baseline"):
        configuration.configure(previous_skill_state={})


@pytest.mark.parametrize("agents", [[{}], [None], [{"id": "default"}, {"id": "default"}]])
def test_ambiguous_agent_inventory_cannot_authorize_initialization(monkeypatch, agents):
    monkeypatch.setattr(configuration, "request_json", lambda path, **kw: {"agents": agents})
    with pytest.raises(RuntimeError, match="invalid public Agent"):
        configuration.capture_skill_state()


@pytest.mark.parametrize("mode", ["all-on", "mixed", "all-off"])
def test_narrow_restore_exact_choices_no_other_configuration_writes(monkeypatch, mode):
    state = {name: False for name in configuration.SKILLS}
    previous = {name: mode == "all-on" or (mode == "mixed" and i % 2 == 0)
                for i, name in enumerate(configuration.SKILLS)}
    calls = []
    def public(path, *, method="GET", body=None, agent_id=None):
        assert agent_id == configuration.AGENT_ID
        calls.append((path, method, body))
        if path == "/api/skills":
            return [{"name": name, "source": "plugin:ai-novel-world-2026", "enabled": value}
                    for name, value in state.items()]
        assert path in {"/api/skills/batch-enable", "/api/skills/batch-disable"}
        assert method == "POST"
        for name in body:
            state[name] = path.endswith("batch-enable")
        return {"results": {name: {"success": True} for name in body}}
    monkeypatch.setattr(configuration, "request_json", public)
    result = configuration.restore_skill_state(previous)
    assert result["state_preserved"] is True
    assert state == previous
    assert result["compensation_used"] is False
    calls.clear()
    configuration.restore_skill_state(previous)
    assert [method for _, method, _ in calls] == ["GET"]


@pytest.mark.parametrize("applied", [True, False])
def test_lost_acknowledgement_reads_back_before_one_compensation(monkeypatch, applied):
    state = {name: False for name in configuration.SKILLS}
    calls = []
    def public(path, *, method="GET", body=None, **kwargs):
        calls.append(method)
        if method == "GET":
            return [{"name": name, "source": "plugin:ai-novel-world-2026", "enabled": value}
                    for name, value in state.items()]
        if applied or calls.count("POST") == 2:
            state.update({name: True for name in body})
        raise TimeoutError("response lost")
    monkeypatch.setattr(configuration, "request_json", public)
    result = configuration.restore_skill_state({name: True for name in configuration.SKILLS})
    assert result["compensation_used"] is (not applied)
    assert calls == (["GET", "POST", "GET"] if applied else ["GET", "POST", "GET", "POST", "GET"])


def test_restore_stops_after_single_failed_compensation(monkeypatch):
    calls = []
    def public(path, *, method="GET", **kwargs):
        calls.append(method)
        return ([{"name": name, "source": "plugin:ai-novel-world-2026", "enabled": False}
                 for name in configuration.SKILLS] if method == "GET" else {"results": {}})
    monkeypatch.setattr(configuration, "request_json", public)
    with pytest.raises(RuntimeError, match="readback mismatch"):
        configuration.restore_skill_state({name: True for name in configuration.SKILLS})
    assert calls == ["GET", "POST", "GET", "POST", "GET"]


def test_added_removed_and_recreated_agent_preserve_explicit_disabled():
    previous = {"prose-writing": False, "retired-skill": True}
    expected = sorted(set(configuration.SKILLS) - {"prose-writing"})
    assert configuration.skill_enable_plan(created=False, previous=previous) == expected
    assert configuration.skill_enable_plan(created=True, previous=previous) == expected
