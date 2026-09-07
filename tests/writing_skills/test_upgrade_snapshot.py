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
