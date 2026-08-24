import ast
import importlib.util
from pathlib import Path
import re

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


def test_agent_configuration_never_writes_a_model_setting() -> None:
    source = (ROOT / "scripts" / "configure_qwenpaw_novel_agent.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)

    assert re.search(r"QWENPAW_[A-Z0-9_]*MODEL", source) is None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "request_json" or not node.args:
            continue
        path = ast.get_source_segment(source, node.args[0]) or ""
        if "/api/models" not in path:
            continue
        method = next(
            (
                keyword.value.value
                for keyword in node.keywords
                if keyword.arg == "method"
                and isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, str)
            ),
            "GET",
        )
        assert method == "GET"


def test_verifier_compares_runtime_model_with_agent_effective_model() -> None:
    source = (ROOT / "scripts" / "verify_qwenpaw_lab.py").read_text(
        encoding="utf-8"
    )

    assert "MiniMax" not in source
    assert 'get_json(f"/api/{APP_ID}/generation-model")' in source
    assert (
        'runtime_model.get("provider_id") == active_llm.get("provider_id")'
        in source
    )
    assert 'runtime_model.get("model_id") == active_llm.get("model")' in source


def test_uninstall_requires_the_exact_plugin_id() -> None:
    lab = load_script("qwenpaw_lab_plugin")

    with pytest.raises(RuntimeError, match="requires --confirm"):
        lab.uninstall("wrong-plugin")


def test_installed_plugin_migration_uses_packaged_alembic_head(monkeypatch) -> None:
    lab = load_script("qwenpaw_lab_plugin")
    calls: list[tuple[str, ...]] = []

    monkeypatch.setattr(lab, "run", lambda *args, **kwargs: calls.append(args) or "")
    lab.migrate_installed_plugin()

    assert calls == [
        (
            "docker",
            "exec",
            lab.CONTAINER,
            "sh",
            "-lc",
            "cd /app/working/plugins/ai-novel-world-2026 && "
            "/app/venv/bin/python -m alembic -c alembic.ini upgrade head",
        )
    ]


def test_packager_includes_alembic_configuration() -> None:
    source = (ROOT / "scripts" / "package_plugin.py").read_text(encoding="utf-8")

    assert 'copy_file("alembic.ini")' in source
