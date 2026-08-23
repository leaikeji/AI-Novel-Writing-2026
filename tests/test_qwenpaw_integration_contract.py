import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_chat_wrapper_is_workbench_gated_and_uses_public_route_api() -> None:
    source = (ROOT / "frontend" / "src" / "index.ts").read_text(encoding="utf-8")
    route_state = (ROOT / "frontend" / "src" / "workbench-route.ts").read_text(encoding="utf-8")

    assert "window.QwenPaw.route.wrap" in source
    assert "CORE_CHAT_ROUTE_ID" in source
    assert "activeWorkbenchRoute() !== null" in source
    assert 'get("novel_workbench") === "1"' in route_state
    assert "window.sessionStorage" in route_state
    assert "return React.createElement(Inner);" in source


def test_agent_configuration_and_verifier_use_the_same_skill_set() -> None:
    configure = load_script("configure_qwenpaw_novel_agent")
    verifier = load_script("verify_qwenpaw_lab")

    assert configure.AGENT_ID == verifier.NOVEL_AGENT_ID
    assert set(configure.SKILLS) == verifier.NOVEL_SKILLS
    assert set(configure.TOOLS) == verifier.NOVEL_TOOLS


def test_uninstall_requires_the_exact_plugin_id() -> None:
    lab = load_script("qwenpaw_lab_plugin")

    with pytest.raises(RuntimeError, match="requires --confirm"):
        lab.uninstall("wrong-plugin")
