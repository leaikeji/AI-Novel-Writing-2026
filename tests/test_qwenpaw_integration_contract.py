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
    wrapper = (ROOT / "frontend" / "src" / "assistant-route-wrap.ts").read_text(
        encoding="utf-8"
    )
    route_state = (ROOT / "frontend" / "src" / "workbench-route.ts").read_text(encoding="utf-8")

    assert "registerAssistantRouteWrap" in source
    assert "options.route.wrap(" in wrapper
    assert "CORE_CHAT_ROUTE_ID" in source
    assert "isWorkbenchRoute(routeSession)" in wrapper
    assert "class RouteSessionStateMachine" in route_state
    assert 'query.get("novel_workbench") !== "1"' in route_state
    assert 'query.get("novel_id")' not in route_state
    assert 'nonEmptyQueryValue(query, "novel_id")' in route_state
    assert "window.sessionStorage" in route_state
    assert "return h(Inner);" in wrapper
    assert "createQwenPawAssistantPane" in wrapper
    assert "registerAssistantRequestPayload" in source
    assert "createAssistantContextRefCoordinator" in source
    assert "createAssistantContextRefHttpClient" in source
    assert "registerAssistantToolCard" in source
    assert "window.QwenPaw.chat.disposeAll(APP_ID)" in source


def test_page_context_uses_the_public_middleware_contract() -> None:
    source = (ROOT / "plugin.py").read_text(encoding="utf-8")
    context_source = (ROOT / "backend" / "assistant_context.py").read_text(
        encoding="utf-8"
    )

    assert "api.register_middleware(" in source
    assert "create_ai_novel_page_context_middleware" in source
    assert "priority=80" in source
    assert "api.register_runtime_hook(" not in source
    assert "class AINovelPageContextHook(HookBase)" in context_source
    assert "class AINovelPageContextMiddleware(MiddlewareBase)" in context_source
    assert "phase = Phase.PRE_EXECUTE" in context_source
    assert "ctx.inject_context(" in context_source


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


def test_existing_agent_is_refreshed_after_plugin_reinstall(monkeypatch) -> None:
    configure = load_script("configure_qwenpaw_novel_agent")
    calls: list[tuple[str, str, object | None, str | None]] = []

    def fake_request_json(
        path: str,
        *,
        method: str = "GET",
        body: object | None = None,
        agent_id: str | None = None,
    ) -> object:
        calls.append((path, method, body, agent_id))
        if path == "/api/agents":
            return {"agents": [{"id": configure.AGENT_ID}]}
        if path == f"/api/agents/{configure.AGENT_ID}":
            return {"id": configure.AGENT_ID}
        if path == "/api/skills":
            return [
                {
                    "name": name,
                    "source": "plugin:ai-novel-world-2026",
                }
                for name in configure.SKILLS
            ]
        if path == "/api/skills/batch-enable":
            return {
                "results": {
                    name: {"success": True} for name in configure.SKILLS
                },
            }
        if path == "/api/tools":
            return [
                {"name": name, "enabled": True}
                for name in configure.TOOLS
            ]
        if path.startswith("/api/workspace/files/"):
            return {"ok": True}
        if path == "/api/workspace/system-prompt-files":
            return [configure.PROMPT_FILE]
        if path.startswith("/api/models/active"):
            return {
                "active_llm": {
                    "provider_id": "provider-from-fixture",
                    "model": "model-from-fixture",
                },
            }
        raise AssertionError(f"unexpected request: {path}")

    monkeypatch.setattr(configure, "request_json", fake_request_json)

    result = configure.configure()

    refresh_index = calls.index(
        (
            f"/api/agents/{configure.AGENT_ID}",
            "PUT",
            configure.desired_agent_payload(),
            None,
        ),
    )
    tools_index = next(
        index for index, call in enumerate(calls) if call[0] == "/api/tools"
    )
    assert refresh_index < tools_index
    assert result["created"] is False


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


def test_packager_excludes_python_cache_artifacts() -> None:
    source = (ROOT / "scripts" / "package_plugin.py").read_text(encoding="utf-8")

    assert 'shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")' in source
    assert "ignore=PLUGIN_COPY_IGNORE" in source
