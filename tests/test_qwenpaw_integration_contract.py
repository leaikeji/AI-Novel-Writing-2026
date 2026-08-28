import ast
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import textwrap

import pytest


ROOT = Path(__file__).resolve().parents[1]

PACKAGED_TTS_PUBLIC_FILES = frozenset(
    {
        "bootstrap_digest_keyring.py",
        "manage_digest_keyring.py",
    }
)
HOST_ONLY_TTS_AUDIT_PATHS = frozenset(
    {
        "scripts/tts/chapter_e2e_browser_observer.py",
        "scripts/tts/chapter_e2e_collector.py",
        "scripts/tts/chapter_e2e_controller_build.py",
        "scripts/tts/chapter_e2e_controller_evidence.py",
        "scripts/tts/chapter_e2e_controller_host.py",
        "scripts/tts/chapter_e2e_controller_lifecycle.py",
        "scripts/tts/chapter_e2e_controller_signer.py",
        "scripts/tts/chapter_e2e_controller_trust.py",
        "scripts/tts/chapter_e2e_executor.py",
        "scripts/tts/chapter_e2e_listening.py",
        "scripts/tts/chapter_e2e_metric_chain.py",
        "scripts/tts/chapter_e2e_operator_envelope.py",
        "scripts/tts/chapter_e2e_probe_request.py",
        "scripts/tts/chapter_e2e_probes.py",
        "scripts/tts/chapter_e2e_readiness.py",
        "scripts/tts/chapter_e2e_runtime_audit.py",
        "scripts/tts/chapter_e2e_runtime_observer.py",
        "scripts/tts/diagnose_nano_short_text.py",
        "scripts/tts/generate_nano_strategy_preview.py",
        "scripts/tts/nano_short_regression.py",
        "scripts/tts/run_nano_short_regression.py",
        "scripts/tts/controller_node_runtime.py",
        "scripts/tts/controller_ssh_askpass.sh",
        "scripts/tts/provision_validation_token.py",
        "scripts/tts/local_chapter_e2e_container.py",
        "scripts/tts/run_chapter_e2e_real.py",
        "scripts/tts/run_local_chapter_e2e.py",
        "scripts/tts/run_local_operator_report.py",
        "scripts/tts/trust/controller_allowed_signers",
        "scripts/tts/trust/controller_trust_policy.json",
        "scripts/tts/validate_chapter_e2e.py",
        "scripts/tts/verify_chapter_e2e_teardown.py",
        "tests/fixtures/narration/chapter-e2e-v2.json",
        "tests/fixtures/narration/chapter-e2e-v3.json",
        "tests/fixtures/narration/short-attribution-regression-v1.json",
    }
)
HOST_ONLY_CONTROLLER_MODULES = frozenset(
    path.removesuffix(".py").replace("/", ".")
    for path in HOST_ONLY_TTS_AUDIT_PATHS
    if path.endswith(".py")
)
HOST_ONLY_CONTROLLER_MODULE_BASENAMES = frozenset(
    module.rsplit(".", 1)[-1] for module in HOST_ONLY_CONTROLLER_MODULES
)


def load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def imported_python_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module:
                imported.add(module)
            if module == "scripts.tts":
                imported.update(f"{module}.{alias.name}" for alias in node.names)
            if node.level and not module:
                imported.update(alias.name for alias in node.names)
    return imported


def test_chat_wrapper_is_surface_gated_and_uses_public_route_api() -> None:
    source = (ROOT / "frontend" / "src" / "index.ts").read_text(encoding="utf-8")
    wrapper = (ROOT / "frontend" / "src" / "assistant-route-wrap.ts").read_text(
        encoding="utf-8"
    )
    route_state = (ROOT / "frontend" / "src" / "workbench-route.ts").read_text(encoding="utf-8")

    assert "registerAssistantRouteWrap" in source
    assert "options.route.wrap(" in wrapper
    assert "CORE_CHAT_ROUTE_ID" in source
    assert "isNovelWorkbenchRouteSession(routeSession)" in wrapper
    assert "isCreativeCenterRouteSession(routeSession)" in wrapper
    assert "CreativeCenter: NovelLibraryPage" in source
    assert "class RouteSessionStateMachine" in route_state
    assert 'query.get("novel_workbench") === "1"' in route_state
    assert 'query.get("novel_center") === "1"' in route_state
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


def test_narration_runtime_uses_only_public_pawapp_lifecycle_contracts() -> None:
    app_source = (ROOT / "backend" / "app.py").read_text(encoding="utf-8")
    plugin_source = (ROOT / "plugin.py").read_text(encoding="utf-8")
    app_tree = ast.parse(app_source)
    plugin_tree = ast.parse(plugin_source)

    functions = {
        node.name: node
        for node in app_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    startup = functions["_launch_narration_runtime"]
    shutdown = functions["_stop_narration_runtime"]
    uninstall = functions["_uninstall_narration_runtime"]

    assert [ast.unparse(item) for item in startup.decorator_list] == [
        "pawapp.hook('startup', priority=100)"
    ]
    assert [ast.unparse(item) for item in shutdown.decorator_list] == [
        "pawapp.hook('shutdown', priority=100)"
    ]
    assert [ast.unparse(item) for item in uninstall.decorator_list] == [
        "pawapp.on_uninstall"
    ]
    assert "await launch_narration_runtime()" in ast.unparse(startup)
    assert "await stop_narration_runtime()" in ast.unparse(shutdown)
    assert "await stop_narration_runtime()" in ast.unparse(uninstall)
    assert '"narration": narration_runtime_status()' in app_source

    register_method = next(
        item
        for node in plugin_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "AINovelWorldPlugin"
        for item in node.body
        if isinstance(item, ast.FunctionDef) and item.name == "register"
    )
    register_calls = [
        ast.unparse(node)
        for node in ast.walk(register_method)
        if isinstance(node, ast.Call)
    ]
    assert "pawapp.register(api)" in register_calls
    for forbidden in (
        "register_startup_hook",
        "register_shutdown_hook",
        "register_uninstall_hook",
        "register_runtime_hook",
    ):
        assert f"api.{forbidden}(" not in app_source
        assert f"api.{forbidden}(" not in plugin_source


def test_public_pawapp_register_delegates_lifecycle_hooks_to_plugin_api() -> None:
    probe = textwrap.dedent(
        """
        import asyncio
        from dataclasses import dataclass
        from enum import Enum
        import json
        import sys
        from types import ModuleType

        class PawApp:
            def __init__(self, name="", *, app_id=""):
                self.name = name
                self.app_id = app_id
                self._hooks = []
                self._lifecycle = {}
                self._routers = []

            def hook(self, phase, *, priority=100):
                def decorator(func):
                    self._hooks.append(
                        {"phase": phase, "func": func, "priority": priority}
                    )
                    return func
                return decorator

            def on_uninstall(self, func):
                self._lifecycle["uninstall"] = func
                return func

            def include_router(self, router, **_kwargs):
                self._routers.append(router)

            def register(self, api):
                for router in self._routers:
                    api.register_http_router(
                        router,
                        prefix=f"/{self.app_id}" if self.app_id else "",
                        tags=[f"pawapp:{self.app_id or self.name}"],
                    )
                for hook in self._hooks:
                    payload = {
                        "hook_name": (
                            f"pawapp_{self.app_id}_{id(hook['func'])}"
                        ),
                        "callback": hook["func"],
                        "priority": hook["priority"],
                    }
                    if hook["phase"] == "startup":
                        api.register_startup_hook(**payload)
                    elif hook["phase"] == "shutdown":
                        api.register_shutdown_hook(**payload)
                if "uninstall" in self._lifecycle:
                    api.register_uninstall_hook(
                        hook_name=f"pawapp_{self.app_id}_on_uninstall",
                        callback=self._lifecycle["uninstall"],
                    )

        async def get_ctx():
            return None

        qwenpaw = ModuleType("qwenpaw")
        qwenpaw.__path__ = []
        pawapp_module = ModuleType("qwenpaw.pawapp")
        pawapp_module.PawApp = PawApp
        pawapp_module.get_ctx = get_ctx
        runtime_module = ModuleType("qwenpaw.runtime")
        runtime_module.__path__ = []
        hooks_module = ModuleType("qwenpaw.runtime.hooks")
        phases_module = ModuleType("qwenpaw.runtime.phases")

        class HookBase:
            pass

        @dataclass
        class HookResult:
            pass

        class Phase(str, Enum):
            PRE_EXECUTE = "pre_execute"

        hooks_module.HookBase = HookBase
        hooks_module.HookResult = HookResult
        phases_module.Phase = Phase
        qwenpaw.pawapp = pawapp_module
        qwenpaw.runtime = runtime_module
        runtime_module.hooks = hooks_module
        runtime_module.phases = phases_module
        sys.modules.update(
            {
                "qwenpaw": qwenpaw,
                "qwenpaw.pawapp": pawapp_module,
                "qwenpaw.runtime": runtime_module,
                "qwenpaw.runtime.hooks": hooks_module,
                "qwenpaw.runtime.phases": phases_module,
            }
        )

        import backend.app as app

        class RecordingPluginApi:
            def __init__(self):
                self.startup = []
                self.shutdown = []
                self.uninstall = []
                self.routers = []

            def register_startup_hook(self, **payload):
                self.startup.append(payload)

            def register_shutdown_hook(self, **payload):
                self.shutdown.append(payload)

            def register_uninstall_hook(self, **payload):
                self.uninstall.append(payload)

            def register_http_router(self, router, **payload):
                self.routers.append((router, payload))

        api = RecordingPluginApi()
        app.pawapp.register(api)
        assert len(api.startup) == 1 and api.startup[0]["priority"] == 100
        assert len(api.shutdown) == 1 and api.shutdown[0]["priority"] == 100
        assert len(api.uninstall) == 1
        assert len(api.routers) == 1
        assert api.routers[0][1] == {
            "prefix": "/ai-novel-world-2026",
            "tags": ["pawapp:ai-novel-world-2026"],
        }

        lifecycle_calls = []

        async def launch():
            lifecycle_calls.append("launch")

        async def stop():
            lifecycle_calls.append("stop")

        app.launch_narration_runtime = launch
        app.stop_narration_runtime = stop

        async def exercise():
            await api.startup[0]["callback"]()
            await api.shutdown[0]["callback"]()
            await api.uninstall[0]["callback"]()

        asyncio.run(exercise())
        assert lifecycle_calls == ["launch", "stop", "stop"]

        narration = {
            "technical_enabled": True,
            "lifecycle_status": "ready",
            "sidecar_reachable": True,
            "model_ready": True,
            "product_visible": False,
        }
        app.database_status = lambda: {"connected": True}
        app.narration_runtime_status = lambda: narration
        health = app.health()
        assert health["status"] == "ready"
        assert health["narration"] is narration
        print(
            json.dumps(
                {
                    "startup": len(api.startup),
                    "shutdown": len(api.shutdown),
                    "uninstall": len(api.uninstall),
                    "lifecycle_calls": lifecycle_calls,
                    "product_visible": health["narration"]["product_visible"],
                },
                sort_keys=True,
            )
        )
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "lifecycle_calls": ["launch", "stop", "stop"],
        "product_visible": False,
        "shutdown": 1,
        "startup": 1,
        "uninstall": 1,
    }


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


def test_verifier_strictly_checks_product_runtime_capability() -> None:
    verifier = load_script("verify_qwenpaw_lab")
    verifier.EXPECTED_TTS_PRODUCT = "ready"
    verifier.EXPECTED_TTS_VALIDATION = "disabled"

    expected = verifier.expected_narration_production()

    assert expected == {
        "product_requested": True,
        "lifecycle_status": "ready",
        "playback_installed": True,
        "digest_keyring_loaded": True,
        "production_backend_installed": True,
        "worker_running": True,
        "reference_clone_ready": False,
        "reason_code": None,
    }
    degraded = dict(expected, worker_running=False)
    assert degraded != verifier.expected_narration_production()


def test_verifier_uses_the_same_ready_pipeline_for_hidden_validation() -> None:
    verifier = load_script("verify_qwenpaw_lab")
    verifier.EXPECTED_TTS_PRODUCT = "disabled"
    verifier.EXPECTED_TTS_VALIDATION = "ready"

    assert verifier.expected_narration_production()["worker_running"] is True


def test_verifier_hidden_validation_checks_t2_overview_and_negative_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.narration.privacy import t2_settings_capabilities

    verifier = load_script("verify_qwenpaw_lab")
    novel_id = "10000000-0000-4000-8000-000000000001"
    document_id = "20000000-0000-4000-8000-000000000002"
    verifier.TTS_VALIDATION_NOVEL_ID = novel_id
    verifier.TTS_VALIDATION_DOCUMENT_ID = document_id
    assert verifier.T2_CAPABILITY_MATRIX == t2_settings_capabilities().model_dump(
        mode="json"
    )
    calls: list[tuple[str, dict[str, str]]] = []

    def fake_request_json(
        path: str,
        *,
        agent_id: str | None = None,
        headers: dict[str, str] | None = None,
    ):
        assert agent_id is None
        request_headers = dict(headers or {})
        calls.append((path, request_headers))
        if path.endswith("/narration-overview"):
            return verifier.JsonHttpResponse(
                status=200,
                headers={"cache-control": "no-store"},
                payload={
                    "contract_version": "narration-settings-api/1",
                    "novel_id": novel_id,
                    "capabilities": verifier.T2_CAPABILITY_MATRIX,
                    "runtime": {"product_visible": False},
                },
            )
        return verifier.JsonHttpResponse(
            status=404,
            headers={"cache-control": "no-store"},
            payload=verifier.HIDDEN_TTS_NOT_FOUND,
        )

    monkeypatch.setattr(verifier, "request_json", fake_request_json)

    result = verifier.verify_hidden_validation_http()

    prefix = f"/api/{verifier.APP_ID}"
    assert calls[0] == (
        f"{prefix}/novels/{novel_id}/narration-overview",
        {},
    )
    expected_hidden_paths = {
        f"{prefix}/narration-requests/{document_id}",
        f"{prefix}/narration-script-versions/{document_id}",
        f"{prefix}/narration-editions/{document_id}/manifest",
    }
    assert {path for path, headers in calls[1:] if not headers} == expected_hidden_paths
    assert {
        path
        for path, headers in calls[1:]
        if headers
        == {
            verifier.TTS_VALIDATION_HEADER: verifier.WRONG_TTS_VALIDATION_TOKEN,
        }
    } == expected_hidden_paths
    assert result == {
        "ordinary_overview_tier": "T2",
        "negative_validation_token_classes": ["missing", "wrong"],
        "hidden_route_classes": ["narration", "script", "playback"],
    }


@pytest.mark.parametrize(
    ("status", "cache_control", "payload"),
    [
        (200, "no-store", {"detail": {"code": "RESOURCE_NOT_FOUND"}}),
        (404, "private", {"detail": {"code": "RESOURCE_NOT_FOUND"}}),
        (404, "no-store", {"detail": {"code": "RESOURCE_NOT_FOUND"}}),
    ],
)
def test_verifier_hidden_validation_gate_fails_closed_on_response_drift(
    status: int,
    cache_control: str,
    payload: object,
) -> None:
    verifier = load_script("verify_qwenpaw_lab")

    with pytest.raises(AssertionError):
        verifier._assert_hidden_tts_route(
            verifier.JsonHttpResponse(
                status=status,
                headers={"cache-control": cache_control},
                payload=payload,
            )
        )


def test_verifier_checks_product_chinese_official_catalog() -> None:
    from backend.narration.official_presets import PRODUCT_OFFICIAL_PRESETS

    verifier = load_script("verify_qwenpaw_lab")
    payload = {
        "schema_version": "moss-tts-official-preset-catalog/1.0",
        "items": [
            {
                "preset_id": preset.preset_id,
                "display_name": preset.display_name,
                "group": preset.group,
                "language": preset.language,
                "local_use_status": "available",
                "commercial_distribution_status": "not_evaluated",
                "provenance": preset.provenance(),
            }
            for preset in PRODUCT_OFFICIAL_PRESETS
        ],
    }
    verifier.request_json = lambda _path: verifier.JsonHttpResponse(
        status=200,
        headers={"cache-control": "no-store"},
        payload=payload,
    )

    result = verifier.verify_official_preset_catalog()

    assert result["metadata_only"] is True
    assert result["preset_count"] == 6
    assert "onnx.Trump" not in result["preset_ids"]
    assert "onnx.Xiaoyu" in result["preset_ids"]

    payload["items"][0]["audio_file"] = "must-not-leak.wav"
    with pytest.raises(AssertionError):
        verifier.verify_official_preset_catalog()
    del payload["items"][0]["audio_file"]
    payload["items"] = [
        item for item in payload["items"] if item["preset_id"] != "onnx.Junhao"
    ]
    with pytest.raises(AssertionError):
        verifier.verify_official_preset_catalog()


def test_verifier_only_checks_official_catalog_in_product_ready_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier = load_script("verify_qwenpaw_lab")
    calls: list[str] = []
    monkeypatch.setattr(
        verifier,
        "verify_hidden_validation_http",
        lambda: calls.append("validation") or {},
    )
    monkeypatch.setattr(
        verifier,
        "verify_official_preset_catalog",
        lambda: calls.append("catalog") or {},
    )

    verifier.EXPECTED_TTS_PRODUCT = "disabled"
    verifier.EXPECTED_TTS_VALIDATION = "disabled"
    assert verifier.verify_tts_http_contracts() == {}
    assert calls == []

    verifier.EXPECTED_TTS_VALIDATION = "ready"
    assert verifier.verify_tts_http_contracts() == {"hidden_validation": {}}
    assert calls == ["validation"]

    calls.clear()
    verifier.EXPECTED_TTS_PRODUCT = "ready"
    verifier.EXPECTED_TTS_VALIDATION = "disabled"
    assert verifier.verify_tts_http_contracts() == {"official_preset_catalog": {}}
    assert calls == ["catalog"]


def test_verifier_rejects_reference_clone_inside_limited_validation() -> None:
    verifier = load_script("verify_qwenpaw_lab")
    verifier.EXPECTED_TTS_RUNTIME = "ready"
    verifier.EXPECTED_TTS_PRODUCT = "disabled"
    verifier.EXPECTED_TTS_VALIDATION = "ready"
    verifier.EXPECTED_TTS_REFERENCE_CLONE = "ready"

    with pytest.raises(AssertionError, match="separately approved validation gate"):
        verifier.verify()


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


def test_offline_installer_stages_package_without_host_bind(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    lab = load_script("qwenpaw_lab_plugin")
    package = tmp_path / lab.PLUGIN_ID
    package.mkdir()
    monkeypatch.setattr(lab, "PLUGIN_DIR", package)
    monkeypatch.setattr(lab.time, "sleep", lambda _seconds: None)
    healthy: list[bool] = []
    monkeypatch.setattr(lab, "wait_until_healthy", lambda: healthy.append(True))
    calls: list[tuple[str, ...]] = []
    installer_exists = False

    def fake_run(*args: str, **kwargs: object) -> str:
        nonlocal installer_exists
        calls.append(args)
        capture = kwargs.get("capture") is True
        if args[:3] == ("docker", "inspect", lab.CONTAINER):
            if args[-1] == "{{.Config.Image}}":
                return "runtime:image"
            if args[-1] == "{{.State.Running}}":
                return "false"
        if args[:3] == ("docker", "ps", "-a"):
            if installer_exists:
                return (
                    f"{lab.INSTALLER_CONTAINER}\t"
                    f"{lab.INSTALLER_LABEL_VALUE}"
                )
            return ""
        if args[:2] == ("docker", "create"):
            installer_exists = True
        if args[:3] == ("docker", "wait", lab.INSTALLER_CONTAINER):
            return "0"
        if args[:3] == ("docker", "logs", lab.INSTALLER_CONTAINER):
            return "plugin installed"
        if args[:4] == ("docker", "rm", "-f", lab.INSTALLER_CONTAINER):
            installer_exists = False
        return "" if capture else ""

    monkeypatch.setattr(lab, "run", fake_run)

    lab.offline_plugin_command("install", "--force", "/plugin", stage_plugin=True)

    create = next(call for call in calls if call[:2] == ("docker", "create"))
    assert "--name" in create and lab.INSTALLER_CONTAINER in create
    assert (
        f"{lab.INSTALLER_LABEL_KEY}={lab.INSTALLER_LABEL_VALUE}"
        in create
    )
    assert not any(
        isinstance(argument, str) and argument.endswith(":/plugin:ro")
        for call in calls
        for argument in call
    )
    copy_call = (
        "docker",
        "cp",
        str(package),
        f"{lab.INSTALLER_CONTAINER}:/plugin",
    )
    start_call = (
        "docker",
        "start",
        lab.INSTALLER_CONTAINER,
    )
    wait_call = ("docker", "wait", lab.INSTALLER_CONTAINER)
    logs_call = ("docker", "logs", lab.INSTALLER_CONTAINER)
    cleanup_call = ("docker", "rm", "-f", lab.INSTALLER_CONTAINER)
    restore_call = ("docker", "start", lab.CONTAINER)
    assert calls.index(create) < calls.index(copy_call) < calls.index(start_call)
    assert calls.index(start_call) < calls.index(wait_call) < calls.index(logs_call)
    assert calls.index(logs_call) < calls.index(cleanup_call) < calls.index(restore_call)
    assert not any("--attach" in call for call in calls)
    assert healthy == [True]


def test_hot_installer_uses_public_cli_and_exact_unique_stage_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    lab = load_script("qwenpaw_lab_plugin")
    package = tmp_path / lab.PLUGIN_ID
    package.mkdir()
    monkeypatch.setattr(lab, "PLUGIN_DIR", package)
    monkeypatch.setattr(
        lab,
        "uuid4",
        lambda: type("FixedUUID", (), {"hex": "0123456789abcdef"})(),
    )
    healthy: list[bool] = []
    monkeypatch.setattr(lab, "wait_until_healthy", lambda: healthy.append(True))
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def fake_run(*args: str, **kwargs: object) -> str:
        calls.append((args, kwargs))
        if args[3:6] == ("qwenpaw", "plugin", "install"):
            return "Plugin installed successfully"
        return ""

    monkeypatch.setattr(lab, "run", fake_run)

    lab.hot_install_packaged_plugin()

    stage = "/tmp/ai-novel-world-2026-install-0123456789abcdef"
    assert healthy == [True]
    assert calls == [
        (("docker", "cp", str(package), f"{lab.CONTAINER}:{stage}"), {}),
        (
            (
                "docker",
                "exec",
                lab.CONTAINER,
                "qwenpaw",
                "plugin",
                "install",
                "--force",
                stage,
            ),
            {"capture": True, "capture_stderr": True},
        ),
        (("docker", "exec", lab.CONTAINER, "rm", "-rf", "--", stage), {}),
    ]


@pytest.mark.parametrize(
    "reported_output",
    (
        "❌ API install failed: loader rejected plugin",
        "Plugin installation failed: No module named 'backend'",
    ),
)
def test_hot_installer_rejects_false_success_and_still_cleans_exact_stage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reported_output: str,
) -> None:
    lab = load_script("qwenpaw_lab_plugin")
    package = tmp_path / lab.PLUGIN_ID
    package.mkdir()
    monkeypatch.setattr(lab, "PLUGIN_DIR", package)
    monkeypatch.setattr(
        lab,
        "uuid4",
        lambda: type("FixedUUID", (), {"hex": "false-success"})(),
    )
    monkeypatch.setattr(lab, "wait_until_healthy", lambda: None)
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def fake_run(*args: str, **kwargs: object) -> str:
        calls.append((args, kwargs))
        if args[3:6] == ("qwenpaw", "plugin", "install"):
            return reported_output
        return ""

    monkeypatch.setattr(lab, "run", fake_run)

    with pytest.raises(RuntimeError, match="despite process status 0"):
        lab.hot_install_packaged_plugin()

    stage = "/tmp/ai-novel-world-2026-install-false-success"
    assert calls[-1] == (
        ("docker", "exec", lab.CONTAINER, "rm", "-rf", "--", stage),
        {},
    )
    assert [call for call, _kwargs in calls if call[:3] == ("docker", "exec", lab.CONTAINER)][-1] == (
        "docker",
        "exec",
        lab.CONTAINER,
        "rm",
        "-rf",
        "--",
        stage,
    )


def test_install_does_not_migrate_or_configure_after_hot_install_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lab = load_script("qwenpaw_lab_plugin")
    run_calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(lab, "pnpm_bin", lambda: "pnpm")
    monkeypatch.setattr(lab, "pnpm_environment", lambda _pnpm: {})
    monkeypatch.setattr(
        lab,
        "run",
        lambda *args, **_kwargs: run_calls.append(args) or "",
    )
    monkeypatch.setattr(
        lab,
        "hot_install_packaged_plugin",
        lambda: (_ for _ in ()).throw(RuntimeError("public CLI reported failure")),
    )
    monkeypatch.setattr(lab, "require_live_tts_flags_disabled", lambda: None)
    migrated: list[bool] = []
    verified: list[bool] = []
    monkeypatch.setattr(lab, "migrate_installed_plugin", lambda: migrated.append(True))
    monkeypatch.setattr(lab, "verify", lambda: verified.append(True))

    with pytest.raises(RuntimeError, match="public CLI reported failure"):
        lab.install()

    assert migrated == []
    assert verified == []
    assert not any(
        "configure_qwenpaw_novel_agent.py" in argument
        for call in run_calls
        for argument in call
    )


def test_run_can_capture_public_cli_stderr_with_stdout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lab = load_script("qwenpaw_lab_plugin")
    invocation: dict[str, object] = {}

    def fake_subprocess_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        invocation["args"] = args
        invocation["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="API install failed on stderr\n",
        )

    monkeypatch.setattr(lab.subprocess, "run", fake_subprocess_run)

    output = lab.run("qwenpaw", "plugin", "install", capture=True, capture_stderr=True)

    assert output == "API install failed on stderr"
    assert invocation["kwargs"]["stdout"] is subprocess.PIPE
    assert invocation["kwargs"]["stderr"] is subprocess.STDOUT


def test_runtime_waiter_accepts_disabled_topology_without_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lab = load_script("qwenpaw_lab_plugin")
    monkeypatch.delenv(lab.TTS_RUNTIME_EXPECTATION_ENV, raising=False)
    monkeypatch.setenv(lab.TTS_PRODUCT_EXPECTATION_ENV, "disabled")
    health = {
        "narration": {
            "technical_enabled": False,
            "lifecycle_status": "disabled",
            "sidecar_reachable": False,
            "model_ready": False,
            "worker_generation": None,
            "lease_generation": None,
            "product_visible": False,
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
    monkeypatch.setattr(lab.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(
        lab,
        "read_public_plugin_health",
        lambda *, timeout_seconds: health,
    )
    sleeps: list[float] = []
    monkeypatch.setattr(lab.time, "sleep", sleeps.append)

    assert lab.wait_until_expected_tts_runtime() is health
    assert sleeps == []


def test_runtime_waiter_polls_public_health_until_ready_topology(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lab = load_script("qwenpaw_lab_plugin")
    monkeypatch.setenv(lab.TTS_RUNTIME_EXPECTATION_ENV, "ready")
    monkeypatch.setenv(lab.TTS_PRODUCT_EXPECTATION_ENV, "disabled")
    clock = [20.0]
    monkeypatch.setattr(lab.time, "monotonic", lambda: clock[0])
    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(lab.time, "sleep", fake_sleep)
    health_states = iter(
        (
            {
                "narration": {
                    "technical_enabled": True,
                    "lifecycle_status": "starting",
                    "sidecar_reachable": True,
                    "model_ready": True,
                    "worker_generation": 3,
                    "lease_generation": None,
                    "product_visible": False,
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
            },
            {
                "narration": {
                    "technical_enabled": True,
                    "lifecycle_status": "ready",
                    "sidecar_reachable": True,
                    "model_ready": True,
                    "worker_generation": 3,
                    "lease_generation": 3,
                    "product_visible": False,
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
            },
        )
    )
    request_timeouts: list[float] = []

    def fake_health(*, timeout_seconds: float) -> dict[str, object]:
        request_timeouts.append(timeout_seconds)
        return next(health_states)

    monkeypatch.setattr(lab, "read_public_plugin_health", fake_health)

    result = lab.wait_until_expected_tts_runtime(
        timeout_seconds=2,
        poll_interval_seconds=0.2,
    )

    assert result["narration"]["lease_generation"] == 3
    assert sleeps == [pytest.approx(0.2)]
    assert request_timeouts == [pytest.approx(2.0), pytest.approx(1.8)]


def test_runtime_waiter_times_out_with_last_observed_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lab = load_script("qwenpaw_lab_plugin")
    monkeypatch.setenv(lab.TTS_RUNTIME_EXPECTATION_ENV, "ready")
    monkeypatch.setenv(lab.TTS_PRODUCT_EXPECTATION_ENV, "disabled")
    clock = [0.0]
    monkeypatch.setattr(lab.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        lab.time,
        "sleep",
        lambda seconds: clock.__setitem__(0, clock[0] + seconds),
    )
    monkeypatch.setattr(
        lab,
        "read_public_plugin_health",
        lambda *, timeout_seconds: {
            "narration": {
                "technical_enabled": True,
                "lifecycle_status": "starting",
                "sidecar_reachable": True,
                "model_ready": True,
                "worker_generation": 3,
                "lease_generation": None,
                "product_visible": False,
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
        },
    )

    with pytest.raises(
        RuntimeError,
        match=r"technical='ready'.*last narration state:.*starting",
    ):
        lab.wait_until_expected_tts_runtime(
            timeout_seconds=0.3,
            poll_interval_seconds=0.2,
        )


def test_runtime_waiter_propagates_real_health_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lab = load_script("qwenpaw_lab_plugin")
    monkeypatch.setenv(lab.TTS_RUNTIME_EXPECTATION_ENV, "ready")
    monkeypatch.setenv(lab.TTS_PRODUCT_EXPECTATION_ENV, "disabled")

    def fail_health(*, timeout_seconds: float) -> dict[str, object]:
        raise OSError("real health request failure")

    monkeypatch.setattr(lab, "read_public_plugin_health", fail_health)

    with pytest.raises(OSError, match="real health request failure"):
        lab.wait_until_expected_tts_runtime()


def test_runtime_waiter_rejects_unknown_expectation_before_health_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lab = load_script("qwenpaw_lab_plugin")
    monkeypatch.setenv(lab.TTS_RUNTIME_EXPECTATION_ENV, "starting")
    requested: list[bool] = []
    monkeypatch.setattr(
        lab,
        "read_public_plugin_health",
        lambda *, timeout_seconds: requested.append(True),
    )

    with pytest.raises(RuntimeError, match="must be one of: disabled, ready"):
        lab.wait_until_expected_tts_runtime()

    assert requested == []


def test_runtime_waiter_rejects_product_ready_with_disabled_technical_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lab = load_script("qwenpaw_lab_plugin")
    monkeypatch.setenv(lab.TTS_RUNTIME_EXPECTATION_ENV, "disabled")
    monkeypatch.setenv(lab.TTS_PRODUCT_EXPECTATION_ENV, "ready")
    requested: list[bool] = []
    monkeypatch.setattr(
        lab,
        "read_public_plugin_health",
        lambda *, timeout_seconds: requested.append(True),
    )

    with pytest.raises(RuntimeError, match="requires.*ready"):
        lab.wait_until_expected_tts_runtime()

    assert requested == []


def test_runtime_waiter_requires_strict_production_health_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lab = load_script("qwenpaw_lab_plugin")
    monkeypatch.setenv(lab.TTS_RUNTIME_EXPECTATION_ENV, "disabled")
    monkeypatch.setenv(lab.TTS_PRODUCT_EXPECTATION_ENV, "disabled")
    health = {
        "narration": {
            "technical_enabled": False,
            "lifecycle_status": "disabled",
            "sidecar_reachable": False,
            "model_ready": False,
            "worker_generation": None,
            "lease_generation": None,
            "product_visible": False,
            "reason_code": None,
        }
    }
    monkeypatch.setattr(
        lab,
        "read_public_plugin_health",
        lambda *, timeout_seconds: health,
    )

    with pytest.raises(RuntimeError, match="narration_production object"):
        lab.wait_until_expected_tts_runtime()


def test_runtime_waiter_accepts_only_complete_product_ready_topology(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lab = load_script("qwenpaw_lab_plugin")
    monkeypatch.setenv(lab.TTS_RUNTIME_EXPECTATION_ENV, "ready")
    monkeypatch.setenv(lab.TTS_PRODUCT_EXPECTATION_ENV, "ready")
    health = {
        "narration": {
            "technical_enabled": True,
            "lifecycle_status": "ready",
            "sidecar_reachable": True,
            "model_ready": True,
            "worker_generation": 8,
            "lease_generation": 8,
            "product_visible": True,
            "reason_code": None,
        },
        "narration_production": {
            "product_requested": True,
            "lifecycle_status": "ready",
            "playback_installed": True,
            "digest_keyring_loaded": True,
            "production_backend_installed": True,
            "worker_running": True,
            "reference_clone_ready": False,
            "reason_code": None,
        },
    }
    monkeypatch.setattr(lab.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(
        lab,
        "read_public_plugin_health",
        lambda *, timeout_seconds: health,
    )

    assert lab.wait_until_expected_tts_runtime() is health


def test_runtime_waiter_accepts_hidden_validation_pipeline_without_product_visibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lab = load_script("qwenpaw_lab_plugin")
    monkeypatch.setenv(lab.TTS_RUNTIME_EXPECTATION_ENV, "ready")
    monkeypatch.setenv(lab.TTS_PRODUCT_EXPECTATION_ENV, "disabled")
    monkeypatch.setenv(lab.TTS_VALIDATION_EXPECTATION_ENV, "ready")
    health = {
        "narration": {
            "technical_enabled": True,
            "lifecycle_status": "ready",
            "sidecar_reachable": True,
            "model_ready": True,
            "worker_generation": 9,
            "lease_generation": 9,
            "product_visible": False,
            "reason_code": None,
        },
        "narration_production": {
            "product_requested": True,
            "lifecycle_status": "ready",
            "playback_installed": True,
            "digest_keyring_loaded": True,
            "production_backend_installed": True,
            "worker_running": True,
            "reference_clone_ready": False,
            "reason_code": None,
        },
    }
    monkeypatch.setattr(lab.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(
        lab,
        "read_public_plugin_health",
        lambda *, timeout_seconds: health,
    )

    assert lab.wait_until_expected_tts_runtime() is health


def test_runtime_waiter_rejects_product_and_validation_ready_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lab = load_script("qwenpaw_lab_plugin")
    monkeypatch.setenv(lab.TTS_RUNTIME_EXPECTATION_ENV, "ready")
    monkeypatch.setenv(lab.TTS_PRODUCT_EXPECTATION_ENV, "ready")
    monkeypatch.setenv(lab.TTS_VALIDATION_EXPECTATION_ENV, "ready")
    requested: list[bool] = []
    monkeypatch.setattr(
        lab,
        "read_public_plugin_health",
        lambda *, timeout_seconds: requested.append(True),
    )

    with pytest.raises(RuntimeError, match="mutually exclusive"):
        lab.wait_until_expected_tts_runtime()

    assert requested == []


def test_install_preflight_reads_all_four_exact_container_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lab = load_script("qwenpaw_lab_plugin")
    calls: list[tuple[str, ...]] = []
    healthy: list[bool] = []
    monkeypatch.setattr(lab, "wait_until_healthy", lambda: healthy.append(True))
    monkeypatch.setattr(
        lab,
        "run",
        lambda *args, **_kwargs: calls.append(args) or "",
    )

    lab.require_live_tts_flags_disabled()

    assert healthy == [True]
    assert len(calls) == 1
    assert calls[0][:6] == (
        "docker",
        "exec",
        lab.CONTAINER,
        "/app/venv/bin/python",
        "-c",
        calls[0][5],
    )
    probe = calls[0][5]
    assert "AI_NOVEL_TTS_RUNTIME_ENABLED" in probe
    assert "AI_NOVEL_TTS_PRODUCT_ENABLED" in probe
    assert "AI_NOVEL_TTS_VALIDATION_ENABLED" in probe
    assert "AI_NOVEL_TTS_REFERENCE_CLONE_ENABLED" in probe
    assert "environ" in probe


def test_product_keyring_bootstrap_is_explicit_and_argv_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lab = load_script("qwenpaw_lab_plugin")
    monkeypatch.setenv(lab.TTS_RUNTIME_EXPECTATION_ENV, "ready")
    monkeypatch.setenv(lab.TTS_PRODUCT_EXPECTATION_ENV, "ready")
    monkeypatch.setenv(lab.TTS_FRESH_INSTALL_ENV, "true")
    monkeypatch.setenv(lab.TTS_DIGEST_KEY_ID_ENV, "narration-local-2026-08")
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        lab,
        "run",
        lambda *args, **_kwargs: calls.append(args) or "",
    )

    lab.bootstrap_installed_digest_keyring()

    assert calls == [
        (
            "docker",
            "exec",
            lab.CONTAINER,
            "/app/venv/bin/python",
            f"{lab.INSTALLED_PLUGIN_DIR}/scripts/tts/bootstrap_digest_keyring.py",
            "--path",
            lab.INSTALLED_DIGEST_KEYRING_PATH,
            "--fresh-install",
            "--key-id",
            "narration-local-2026-08",
        )
    ]


def test_hidden_validation_bootstraps_the_same_digest_keyring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lab = load_script("qwenpaw_lab_plugin")
    monkeypatch.setenv(lab.TTS_RUNTIME_EXPECTATION_ENV, "ready")
    monkeypatch.setenv(lab.TTS_PRODUCT_EXPECTATION_ENV, "disabled")
    monkeypatch.setenv(lab.TTS_VALIDATION_EXPECTATION_ENV, "ready")
    monkeypatch.setenv(lab.TTS_FRESH_INSTALL_ENV, "false")
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        lab,
        "run",
        lambda *args, **_kwargs: calls.append(args) or "",
    )

    lab.bootstrap_installed_digest_keyring()

    assert calls == [
        (
            "docker",
            "exec",
            lab.CONTAINER,
            "/app/venv/bin/python",
            f"{lab.INSTALLED_PLUGIN_DIR}/scripts/tts/bootstrap_digest_keyring.py",
            "--path",
            lab.INSTALLED_DIGEST_KEYRING_PATH,
        )
    ]


def test_product_keyring_bootstrap_skips_default_disabled_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lab = load_script("qwenpaw_lab_plugin")
    monkeypatch.delenv(lab.TTS_PRODUCT_EXPECTATION_ENV, raising=False)
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        lab,
        "run",
        lambda *args, **_kwargs: calls.append(args) or "",
    )

    lab.bootstrap_installed_digest_keyring()

    assert calls == []


def test_install_rejects_unknown_product_intent_before_any_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lab = load_script("qwenpaw_lab_plugin")
    monkeypatch.setenv(lab.TTS_PRODUCT_EXPECTATION_ENV, "starting")
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        lab,
        "run",
        lambda *args, **_kwargs: calls.append(args) or "",
    )

    with pytest.raises(RuntimeError, match="must be one of: disabled, ready"):
        lab.install()

    assert calls == []


def test_product_reload_requires_explicit_host_flags_before_compose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lab = load_script("qwenpaw_lab_plugin")
    monkeypatch.setenv(lab.TTS_PRODUCT_EXPECTATION_ENV, "ready")
    monkeypatch.setenv(lab.TTS_RUNTIME_EXPECTATION_ENV, "ready")
    monkeypatch.delenv(lab.TTS_TECHNICAL_ENABLE_ENV, raising=False)
    monkeypatch.setenv(lab.TTS_PRODUCT_ENABLE_ENV, "true")
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        lab,
        "run",
        lambda *args, **_kwargs: calls.append(args) or "",
    )

    with pytest.raises(RuntimeError, match="RUNTIME_ENABLED.*must match"):
        lab.reload_installed_plugin()

    assert calls == []


def test_product_reload_force_recreates_qwenpaw_then_waits_for_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lab = load_script("qwenpaw_lab_plugin")
    monkeypatch.setenv(lab.TTS_PRODUCT_EXPECTATION_ENV, "ready")
    monkeypatch.setenv(lab.TTS_RUNTIME_EXPECTATION_ENV, "ready")
    monkeypatch.setenv(lab.TTS_TECHNICAL_ENABLE_ENV, "true")
    monkeypatch.setenv(lab.TTS_PRODUCT_ENABLE_ENV, "true")
    events: list[object] = []
    monkeypatch.setattr(
        lab,
        "run",
        lambda *args, **_kwargs: events.append(args) or "",
    )
    monkeypatch.setattr(
        lab,
        "wait_until_healthy",
        lambda: events.append("healthy"),
    )

    lab.reload_installed_plugin()

    assert events == [
        (
            "docker",
            "compose",
            "--file",
            str(lab.ROOT / "compose.yaml"),
            "up",
            "-d",
            "--no-deps",
            "--force-recreate",
            "qwenpaw",
        ),
        "healthy",
    ]


def test_technical_only_reload_recreates_with_product_still_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lab = load_script("qwenpaw_lab_plugin")
    monkeypatch.setenv(lab.TTS_RUNTIME_EXPECTATION_ENV, "ready")
    monkeypatch.setenv(lab.TTS_PRODUCT_EXPECTATION_ENV, "disabled")
    monkeypatch.setenv(lab.TTS_TECHNICAL_ENABLE_ENV, "true")
    monkeypatch.setenv(lab.TTS_PRODUCT_ENABLE_ENV, "false")
    events: list[object] = []
    monkeypatch.setattr(
        lab,
        "run",
        lambda *args, **_kwargs: events.append(args) or "",
    )
    monkeypatch.setattr(
        lab,
        "wait_until_healthy",
        lambda: events.append("healthy"),
    )

    lab.reload_installed_plugin()

    assert events[0][:3] == ("docker", "compose", "--file")
    assert events[-1] == "healthy"


def test_hidden_validation_reload_requires_validation_true_and_product_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lab = load_script("qwenpaw_lab_plugin")
    monkeypatch.setenv(lab.TTS_RUNTIME_EXPECTATION_ENV, "ready")
    monkeypatch.setenv(lab.TTS_PRODUCT_EXPECTATION_ENV, "disabled")
    monkeypatch.setenv(lab.TTS_VALIDATION_EXPECTATION_ENV, "ready")
    monkeypatch.setenv(lab.TTS_TECHNICAL_ENABLE_ENV, "true")
    monkeypatch.setenv(lab.TTS_PRODUCT_ENABLE_ENV, "false")
    monkeypatch.setenv(lab.TTS_VALIDATION_ENABLE_ENV, "true")
    events: list[object] = []
    monkeypatch.setattr(
        lab,
        "run",
        lambda *args, **_kwargs: events.append(args) or "",
    )
    monkeypatch.setattr(
        lab,
        "wait_until_healthy",
        lambda: events.append("healthy"),
    )

    lab.reload_installed_plugin()

    assert events[0][:3] == ("docker", "compose", "--file")
    assert events[-1] == "healthy"


def test_install_intent_rejects_hidden_validation_flag_without_expectation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lab = load_script("qwenpaw_lab_plugin")
    monkeypatch.setenv(lab.TTS_RUNTIME_EXPECTATION_ENV, "ready")
    monkeypatch.setenv(lab.TTS_PRODUCT_EXPECTATION_ENV, "disabled")
    monkeypatch.setenv(lab.TTS_VALIDATION_EXPECTATION_ENV, "disabled")
    monkeypatch.setenv(lab.TTS_TECHNICAL_ENABLE_ENV, "true")
    monkeypatch.setenv(lab.TTS_PRODUCT_ENABLE_ENV, "false")
    monkeypatch.setenv(lab.TTS_VALIDATION_ENABLE_ENV, "true")

    with pytest.raises(RuntimeError, match="VALIDATION_ENABLED.*must match"):
        lab.validate_install_intent()


def test_install_intent_rejects_stale_runtime_or_reference_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lab = load_script("qwenpaw_lab_plugin")
    monkeypatch.setenv(lab.TTS_RUNTIME_EXPECTATION_ENV, "disabled")
    monkeypatch.setenv(lab.TTS_PRODUCT_EXPECTATION_ENV, "disabled")
    monkeypatch.setenv(lab.TTS_VALIDATION_EXPECTATION_ENV, "disabled")
    monkeypatch.setenv(lab.TTS_REFERENCE_EXPECTATION_ENV, "disabled")
    monkeypatch.setenv(lab.TTS_TECHNICAL_ENABLE_ENV, "true")
    monkeypatch.setenv(lab.TTS_PRODUCT_ENABLE_ENV, "false")
    monkeypatch.setenv(lab.TTS_VALIDATION_ENABLE_ENV, "false")
    monkeypatch.setenv(lab.TTS_REFERENCE_ENABLE_ENV, "false")

    with pytest.raises(RuntimeError, match="RUNTIME_ENABLED.*must match"):
        lab.validate_install_intent()

    monkeypatch.setenv(lab.TTS_TECHNICAL_ENABLE_ENV, "false")
    monkeypatch.setenv(lab.TTS_REFERENCE_ENABLE_ENV, "true")
    with pytest.raises(RuntimeError, match="REFERENCE_CLONE_ENABLED.*must match"):
        lab.validate_install_intent()


def test_reference_clone_intent_requires_and_matches_one_ready_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    lab = load_script("qwenpaw_lab_plugin")
    monkeypatch.setenv(lab.TTS_RUNTIME_EXPECTATION_ENV, "ready")
    monkeypatch.setenv(lab.TTS_PRODUCT_EXPECTATION_ENV, "disabled")
    monkeypatch.setenv(lab.TTS_VALIDATION_EXPECTATION_ENV, "disabled")
    monkeypatch.setenv(lab.TTS_REFERENCE_EXPECTATION_ENV, "ready")
    monkeypatch.setenv(lab.TTS_TECHNICAL_ENABLE_ENV, "true")
    monkeypatch.setenv(lab.TTS_PRODUCT_ENABLE_ENV, "false")
    monkeypatch.setenv(lab.TTS_VALIDATION_ENABLE_ENV, "false")
    monkeypatch.setenv(lab.TTS_REFERENCE_ENABLE_ENV, "true")

    with pytest.raises(RuntimeError, match="requires a ready product"):
        lab.validate_install_intent()

    monkeypatch.setenv(lab.TTS_VALIDATION_EXPECTATION_ENV, "ready")
    monkeypatch.setenv(lab.TTS_VALIDATION_ENABLE_ENV, "true")
    tmp_path.chmod(0o700)
    monkeypatch.setenv(
        lab.TTS_VALIDATION_HOST_TOKEN_FILE_ENV,
        str(tmp_path / "validation-token"),
    )
    monkeypatch.setenv(
        lab.TTS_VALIDATION_NOVEL_ID_ENV,
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    )
    monkeypatch.setenv(
        lab.TTS_VALIDATION_DOCUMENT_ID_ENV,
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    )
    monkeypatch.setenv(
        lab.TTS_VALIDATION_EXPIRES_AT_ENV,
        (lab.datetime.now(lab.timezone.utc) + lab.timedelta(hours=1)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
    )
    with pytest.raises(RuntimeError, match="reference-clone validation gate"):
        lab.validate_install_intent()

    monkeypatch.setenv(lab.TTS_PRODUCT_EXPECTATION_ENV, "ready")
    monkeypatch.setenv(lab.TTS_VALIDATION_EXPECTATION_ENV, "disabled")
    monkeypatch.setenv(lab.TTS_PRODUCT_ENABLE_ENV, "true")
    monkeypatch.setenv(lab.TTS_VALIDATION_ENABLE_ENV, "false")
    lab.validate_install_intent()


def test_hidden_validation_token_provision_uses_fixed_argv_without_secret(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    lab = load_script("qwenpaw_lab_plugin")
    tmp_path.chmod(0o700)
    token_path = tmp_path / "validation-token"
    monkeypatch.setenv(lab.TTS_VALIDATION_EXPECTATION_ENV, "ready")
    monkeypatch.setenv(
        lab.TTS_VALIDATION_HOST_TOKEN_FILE_ENV,
        str(token_path),
    )
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        lab,
        "run",
        lambda *args, **_kwargs: calls.append(args) or "",
    )

    lab.provision_installed_validation_token()

    assert calls == [
        (
            sys.executable,
            str(lab.ROOT / "scripts" / "tts" / "provision_validation_token.py"),
            "--mode",
            "provision",
            "--host-token-file",
            str(token_path.resolve()),
            "--confirm",
            "PROVISION-T4K-VALIDATION-TOKEN",
        )
    ]
    assert not any("vvvv" in value for value in calls[0])


def test_install_waits_for_expected_runtime_before_final_verify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lab = load_script("qwenpaw_lab_plugin")
    events: list[str] = []
    monkeypatch.setattr(lab, "pnpm_bin", lambda: "pnpm")
    monkeypatch.setattr(lab, "pnpm_environment", lambda _pnpm: {})
    monkeypatch.setattr(lab, "run", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(
        lab,
        "require_live_tts_flags_disabled",
        lambda: events.append("disabled-preflight"),
    )
    monkeypatch.setattr(
        lab,
        "hot_install_packaged_plugin",
        lambda: events.append("hot-install"),
    )
    monkeypatch.setattr(
        lab,
        "migrate_installed_plugin",
        lambda: events.append("migrate"),
    )
    monkeypatch.setattr(
        lab,
        "bootstrap_installed_digest_keyring",
        lambda: events.append("keyring"),
    )
    monkeypatch.setattr(
        lab,
        "provision_installed_validation_token",
        lambda: events.append("validation-token"),
    )
    monkeypatch.setattr(
        lab,
        "reload_installed_plugin",
        lambda: events.append("reload"),
    )
    monkeypatch.setattr(
        lab,
        "wait_until_expected_tts_runtime",
        lambda: events.append("runtime-ready"),
    )
    monkeypatch.setattr(lab, "verify", lambda: events.append("verify"))

    lab.install()

    assert events == [
        "disabled-preflight",
        "hot-install",
        "migrate",
        "keyring",
        "validation-token",
        "reload",
        "runtime-ready",
        "verify",
    ]


def test_install_runs_pytest_in_disabled_tts_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lab = load_script("qwenpaw_lab_plugin")
    monkeypatch.setenv(lab.TTS_RUNTIME_EXPECTATION_ENV, "ready")
    monkeypatch.setenv(lab.TTS_PRODUCT_EXPECTATION_ENV, "disabled")
    monkeypatch.setenv(lab.TTS_VALIDATION_EXPECTATION_ENV, "ready")
    monkeypatch.setenv(lab.TTS_REFERENCE_EXPECTATION_ENV, "disabled")
    monkeypatch.setenv(lab.TTS_TECHNICAL_ENABLE_ENV, "true")
    monkeypatch.setenv(lab.TTS_PRODUCT_ENABLE_ENV, "false")
    monkeypatch.setenv(lab.TTS_VALIDATION_ENABLE_ENV, "true")
    monkeypatch.setenv(lab.TTS_REFERENCE_ENABLE_ENV, "false")
    monkeypatch.setenv(lab.TTS_VALIDATION_HOST_TOKEN_FILE_ENV, "/private/token")
    monkeypatch.setenv(
        lab.TTS_VALIDATION_NOVEL_ID_ENV,
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    )
    monkeypatch.setenv(
        lab.TTS_VALIDATION_DOCUMENT_ID_ENV,
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    )
    monkeypatch.setenv(
        lab.TTS_VALIDATION_EXPIRES_AT_ENV,
        (lab.datetime.now(lab.timezone.utc) + lab.timedelta(hours=1)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
    )
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def fake_run(*args: str, **kwargs: object) -> str:
        calls.append((args, kwargs))
        return ""

    monkeypatch.setattr(lab, "pnpm_bin", lambda: "pnpm")
    monkeypatch.setattr(lab, "pnpm_environment", lambda _pnpm: {})
    monkeypatch.setattr(lab, "run", fake_run)
    monkeypatch.setattr(lab, "require_live_tts_flags_disabled", lambda: None)
    monkeypatch.setattr(lab, "hot_install_packaged_plugin", lambda: None)
    monkeypatch.setattr(lab, "migrate_installed_plugin", lambda: None)
    monkeypatch.setattr(lab, "bootstrap_installed_digest_keyring", lambda: None)
    monkeypatch.setattr(lab, "provision_installed_validation_token", lambda: None)
    monkeypatch.setattr(lab, "reload_installed_plugin", lambda: None)
    monkeypatch.setattr(lab, "wait_until_expected_tts_runtime", lambda: None)
    monkeypatch.setattr(lab, "verify", lambda: None)

    lab.install()

    pytest_calls = [
        kwargs
        for args, kwargs in calls
        if args == (sys.executable, "-m", "pytest")
    ]
    assert len(pytest_calls) == 1
    environment = pytest_calls[0]["environ"]
    assert isinstance(environment, dict)
    assert environment[lab.TTS_RUNTIME_EXPECTATION_ENV] == "disabled"
    assert environment[lab.TTS_PRODUCT_EXPECTATION_ENV] == "disabled"
    assert environment[lab.TTS_VALIDATION_EXPECTATION_ENV] == "disabled"
    assert environment[lab.TTS_REFERENCE_EXPECTATION_ENV] == "disabled"
    assert environment[lab.TTS_TECHNICAL_ENABLE_ENV] == "false"
    assert environment[lab.TTS_PRODUCT_ENABLE_ENV] == "false"
    assert environment[lab.TTS_VALIDATION_ENABLE_ENV] == "false"
    assert environment[lab.TTS_REFERENCE_ENABLE_ENV] == "false"
    for name in (
        lab.TTS_VALIDATION_HOST_TOKEN_FILE_ENV,
        lab.TTS_VALIDATION_NOVEL_ID_ENV,
        lab.TTS_VALIDATION_DOCUMENT_ID_ENV,
        lab.TTS_VALIDATION_EXPIRES_AT_ENV,
    ):
        assert name not in environment


def test_pnpm_environment_discovers_the_bundled_node_sibling(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    lab = load_script("qwenpaw_lab_plugin")
    pnpm = tmp_path / "dependencies" / "bin" / "fallback" / "pnpm"
    node = tmp_path / "dependencies" / "node" / "bin" / "node"
    pnpm.parent.mkdir(parents=True)
    node.parent.mkdir(parents=True)
    pnpm.write_text("#!/bin/sh\n", encoding="utf-8")
    node.write_text("#!/bin/sh\n", encoding="utf-8")
    pnpm.chmod(0o700)
    node.chmod(0o700)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.delenv("NODE_BIN", raising=False)

    environment = lab.pnpm_environment(str(pnpm))

    assert environment["PATH"].split(os.pathsep)[0] == str(node.parent.resolve())


def test_disposable_installer_rejects_nonzero_exit_after_collecting_logs(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lab = load_script("qwenpaw_lab_plugin")
    calls: list[tuple[str, ...]] = []

    def fake_run(*args: str, **_kwargs: object) -> str:
        calls.append(args)
        if args[:3] == ("docker", "wait", lab.INSTALLER_CONTAINER):
            return "17"
        if args[:3] == ("docker", "logs", lab.INSTALLER_CONTAINER):
            return "official cli failed"
        return ""

    monkeypatch.setattr(lab, "run", fake_run)

    with pytest.raises(RuntimeError, match="status 17"):
        lab.run_disposable_installer_container()

    assert calls == [
        ("docker", "start", lab.INSTALLER_CONTAINER),
        ("docker", "wait", lab.INSTALLER_CONTAINER),
        ("docker", "logs", lab.INSTALLER_CONTAINER),
    ]
    assert capsys.readouterr().out == "official cli failed\n"


def test_installer_cleanup_refuses_an_unowned_exact_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lab = load_script("qwenpaw_lab_plugin")

    monkeypatch.setattr(
        lab,
        "run",
        lambda *args, **kwargs: f"{lab.INSTALLER_CONTAINER}\twrong-owner",
    )

    with pytest.raises(RuntimeError, match="refusing to remove unowned"):
        lab.remove_stale_installer_container()


def test_packager_includes_alembic_configuration() -> None:
    source = (ROOT / "scripts" / "package_plugin.py").read_text(encoding="utf-8")

    assert 'copy_file("alembic.ini")' in source


def test_packager_includes_digest_keyring_bootstrap_commands() -> None:
    source = (ROOT / "scripts" / "package_plugin.py").read_text(encoding="utf-8")

    assert 'copy_file("scripts/tts/manage_digest_keyring.py")' in source
    assert 'copy_file("scripts/tts/bootstrap_digest_keyring.py")' in source


def test_packager_keeps_local_t4k_executor_out_of_product_payload() -> None:
    source = (ROOT / "scripts" / "package_plugin.py").read_text(encoding="utf-8")

    # The neutral T4-K executor remains a fixed repository-side audit tool for
    # the local author/operator.  It is deliberately not PawApp payload.
    assert (ROOT / "scripts/tts/run_chapter_e2e_real.py").is_file()
    for fixture_name in ("chapter-e2e-v2.json", "chapter-e2e-v3.json"):
        assert (ROOT / "tests/fixtures/narration" / fixture_name).is_file()
    for relative_path in HOST_ONLY_TTS_AUDIT_PATHS:
        assert f'copy_file("{relative_path}")' not in source
    assert "validation-token" not in source
    assert 'copy_tree("scripts/tts")' not in source
    assert 'copy_tree("scripts/tts/controller-node")' not in source


@pytest.mark.parametrize(
    "relative_path",
    sorted(
        HOST_ONLY_TTS_AUDIT_PATHS
        | {
            "scripts/tts/controller-node/src/observer.mjs",
            "scripts/tts/trust/controller_future_policy.json",
            "controller-authority/agent.sock",
            "controller-authority/controller_ed25519",
            "controller-authority/controller_ed25519.pub",
        }
    ),
)
def test_packager_rejects_host_only_t4k_audit_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative_path: str,
) -> None:
    packager = load_script("package_plugin")
    output_root = tmp_path / "output"
    target = output_root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("host-only placeholder\n", encoding="utf-8")
    monkeypatch.setattr(packager, "OUTPUT", output_root)

    with pytest.raises(
        packager.UnsafePackageInput,
        match="PACKAGE_OUTPUT_HOST_ONLY_FORBIDDEN",
    ):
        packager._audit_output()


def test_packager_rejects_an_empty_controller_node_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    packager = load_script("package_plugin")
    output_root = tmp_path / "output"
    (output_root / "scripts/tts/controller-node").mkdir(parents=True)
    monkeypatch.setattr(packager, "OUTPUT", output_root)

    with pytest.raises(
        packager.UnsafePackageInput,
        match="PACKAGE_OUTPUT_HOST_ONLY_FORBIDDEN",
    ):
        packager._audit_output()


def test_packager_rejects_a_controller_agent_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    packager = load_script("package_plugin")
    with tempfile.TemporaryDirectory(prefix="anw-t4k-", dir="/tmp") as directory:
        output_root = Path(directory)
        agent_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            agent_socket.bind(str(output_root / "agent.sock"))
            monkeypatch.setattr(packager, "OUTPUT", output_root)
            with pytest.raises(
                packager.UnsafePackageInput,
                match="PACKAGE_OUTPUT_HOST_ONLY_FORBIDDEN",
            ):
                packager._audit_output()
        finally:
            agent_socket.close()


def test_packager_fails_closed_for_sensitive_files_and_symlinks(
    tmp_path: Path,
) -> None:
    packager = load_script("package_plugin")
    sensitive = tmp_path / "operator.token"
    sensitive.write_text("not-a-real-token", encoding="utf-8")

    with pytest.raises(
        packager.UnsafePackageInput,
        match="PACKAGE_INPUT_SENSITIVE_NAME",
    ):
        packager._assert_safe_regular_file(sensitive)

    safe_target = tmp_path / "public.py"
    safe_target.write_text("VALUE = 1\n", encoding="utf-8")
    linked = tmp_path / "linked.py"
    linked.symlink_to(safe_target)
    with pytest.raises(
        packager.UnsafePackageInput,
        match="PACKAGE_INPUT_NOT_REGULAR",
    ):
        packager._assert_safe_regular_file(linked)


def test_packager_omits_source_maps_and_audits_final_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    packager = load_script("package_plugin")
    source_root = tmp_path / "source"
    output_root = tmp_path / "output"
    distribution = source_root / "frontend" / "dist"
    distribution.mkdir(parents=True)
    (distribution / "index.js").write_text("export const ready = true;\n")
    (distribution / "index.js.map").write_text('{"sourcesContent":[]}\n')
    monkeypatch.setattr(packager, "ROOT", source_root)
    monkeypatch.setattr(packager, "OUTPUT", output_root)

    packager.copy_tree("frontend/dist")
    packager._audit_output()

    assert (output_root / "frontend" / "dist" / "index.js").is_file()
    assert not (output_root / "frontend" / "dist" / "index.js.map").exists()

    private_key = output_root / "frontend" / "dist" / "private.txt"
    private_key.write_bytes(b"-----BEGIN OPENSSH PRIVATE KEY-----\n")
    with pytest.raises(
        packager.UnsafePackageInput,
        match="PACKAGE_OUTPUT_SECRET_MARKER",
    ):
        packager._audit_output()


@pytest.mark.parametrize(
    "filename",
    (
        "weights.onnx",
        "weights.data",
        "weights.bin",
        "weights.safetensors",
        "controller.sshsig",
    ),
)
def test_packager_rejects_model_and_signature_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
) -> None:
    packager = load_script("package_plugin")
    output_root = tmp_path / "output"
    output_root.mkdir()
    (output_root / filename).write_bytes(b"not-real-model-material")
    monkeypatch.setattr(packager, "OUTPUT", output_root)

    with pytest.raises(
        packager.UnsafePackageInput,
        match="PACKAGE_OUTPUT_SENSITIVE_NAME",
    ):
        packager._audit_output()


def test_packager_rejects_embedded_prompt_codes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    packager = load_script("package_plugin")
    output_root = tmp_path / "output"
    output_root.mkdir()
    (output_root / "manifest.json").write_text(
        '{"prompt_audio_codes":[1,2,3]}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(packager, "OUTPUT", output_root)

    with pytest.raises(
        packager.UnsafePackageInput,
        match="PACKAGE_OUTPUT_SECRET_MARKER",
    ):
        packager._audit_output()


def test_repo_side_t4k_entrypoints_bootstrap_their_project_root() -> None:
    for relative_path in (
        "scripts/tts/run_chapter_e2e_real.py",
        "scripts/tts/chapter_e2e_readiness.py",
        "scripts/tts/chapter_e2e_collector.py",
        "scripts/tts/chapter_e2e_listening.py",
        "scripts/tts/verify_chapter_e2e_teardown.py",
    ):
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "Path(__file__).resolve().parents[2]" in source
        assert "sys.path.insert(0" in source


def test_product_package_excludes_host_side_t4k_audit_tools() -> None:
    packaged = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "package_plugin.py")],
        cwd=ROOT,
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
        },
        check=False,
        capture_output=True,
        text=True,
    )
    assert packaged.returncode == 0, packaged.stderr
    package_root = ROOT / "build" / "ai-novel-world-2026"
    for relative_path in HOST_ONLY_TTS_AUDIT_PATHS:
        assert not (package_root / relative_path).exists()
    assert not (package_root / "scripts/tts/controller-node").exists()
    assert not (package_root / "scripts/tts/trust").exists()
    for fixture_name in ("chapter-e2e-v2.json", "chapter-e2e-v3.json"):
        assert not (
            package_root / "tests/fixtures/narration" / fixture_name
        ).exists()
    assert not tuple(package_root.rglob("agent.sock"))
    assert not tuple(package_root.rglob("controller_ed25519"))
    assert not tuple(package_root.rglob("controller_ed25519.pub"))
    assert not tuple(package_root.rglob("*.sshsig"))

    packaged_tts_root = package_root / "scripts/tts"
    packaged_tts_files = frozenset(
        path.relative_to(packaged_tts_root).as_posix()
        for path in packaged_tts_root.rglob("*")
        if path.is_file()
    )
    assert packaged_tts_files == PACKAGED_TTS_PUBLIC_FILES

    # Audit the complete Python import closure introduced by the only two TTS
    # scripts allowed in product payload.  Repository-side T4-K tools must not
    # be pulled back in through either entrypoint.
    for python_path in packaged_tts_root.rglob("*.py"):
        imported = imported_python_modules(python_path)
        assert not {
            module
            for module in imported
            if module in HOST_ONLY_CONTROLLER_MODULE_BASENAMES
            or any(
                module == forbidden or module.startswith(f"{forbidden}.")
                for forbidden in HOST_ONLY_CONTROLLER_MODULES
            )
        }, python_path.relative_to(package_root).as_posix()


def test_packager_excludes_python_cache_artifacts() -> None:
    source = (ROOT / "scripts" / "package_plugin.py").read_text(encoding="utf-8")

    assert "shutil.ignore_patterns(" in source
    for pattern in ("__pycache__", "*.pyc", "*.pyo", "*.map"):
        assert f'"{pattern}"' in source
    assert "ignore=PLUGIN_COPY_IGNORE" in source
