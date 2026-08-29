from __future__ import annotations

import ast
import base64
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Sequence

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = PROJECT_ROOT / "scripts" / "tts" / "verify_qwenpaw_plugin_lifecycle.py"


def _load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("qwenpaw_plugin_lifecycle_runner", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def runner() -> ModuleType:
    return _load_runner()


@pytest.fixture()
def candidate(tmp_path: Path) -> Path:
    root = tmp_path / "candidate"
    files = {
        "plugin.json": json.dumps(
            {
                "id": "ai-novel-world-2026",
                "version": "0.4.0",
                "meta": {
                    "tools": [
                        {"name": "novel_get_context"},
                        {"name": "novel_get_document"},
                        {"name": "novel_search"},
                        {"name": "novel_get_workspace_context"},
                        {"name": "novel_prepare_selection_edit"},
                    ]
                },
            }
        ),
        "plugin.py": "plugin = object()\n",
        "requirements.txt": "",
        "alembic.ini": "[alembic]\n",
        "frontend/dist/index.js": "export {};\n",
        "backend/app.py": "",
        "backend/narration/pawapp_runtime.py": "",
        (
            "backend/migrations/versions/"
            "20260826_0015_narration_domain_concurrency_guards.py"
        ): "revision = '20260826_0015'\n",
    }
    for skill in (
        "novel-direction",
        "story-foundation",
        "character-craft",
        "chapter-outline",
        "scene-craft",
        "dialogue-craft",
        "prose-writing",
        "continuity-check",
        "style-review",
    ):
        files[f"skills/{skill}/SKILL.md"] = f"# {skill}\n"
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def test_dry_run_never_touches_docker_or_http(
    runner: ModuleType,
    candidate: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("dry-run performed external I/O")

    monkeypatch.setattr(subprocess, "run", forbidden)

    result = runner.main(
        [
            "--mode",
            "dry-run",
            "--candidate",
            str(candidate),
            "--run-id",
            "abcd1234",
        ]
    )

    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["topology"]["container_count"] == 2
    assert output["topology"]["sidecar_started"] is False
    assert output["topology"]["model_mount_count"] == 0
    assert output["topology"]["token_mount_count"] == 0
    assert output["topology"]["host_bind_mount_count"] == 0
    assert output["topology"]["tts_runtime_enabled"] is False
    assert output["topology"]["tts_product_enabled"] is False
    assert output["topology"]["tts_validation_enabled"] is False
    assert output["topology"]["tts_reference_clone_enabled"] is False
    assert output["topology"]["tts_storage_root_env_count"] == 0
    assert output["topology"]["network_internal"] is True
    assert output["topology"]["outbound_network_route"] is False
    assert output["topology"]["published_ports"] == []
    assert output["topology"]["public_api_probe"].startswith("docker-exec")
    assert output["candidate"]["staging"] == "docker-cp-to-qwenpaw-container-layer"
    assert output["cleanup"]["compose_used"] is False
    assert output["cleanup"]["broad_down_or_volume_prune"] is False
    assert output["public_api_operations"] == [
        {"method": "POST", "path": "/api/plugins/install", "force": False},
        {"method": "POST", "path": "/api/plugins/install", "force": True},
        {"method": "DELETE", "path": "/api/plugins/ai-novel-world-2026"},
        {"method": "POST", "path": "/api/plugins/install", "force": False},
    ]


def test_command_topology_is_exactly_two_containers_without_moss_mounts(
    runner: ModuleType,
    candidate: Path,
) -> None:
    run_id = "abcd1234"
    names = runner.create_resource_names(run_id)
    config = runner.GateConfig("real", run_id, candidate, None, runner.REAL_CONFIRMATION)
    gate = runner.LifecycleGate(config, names)

    commands = [gate._postgres_run_command(), gate._qwenpaw_run_command()]
    assert len(commands) == 2
    assert all(command[:3] == ["docker", "run", "--detach"] for command in commands)
    assert commands[0][-1] == runner.POSTGRES_IMAGE
    assert commands[1][-1] == runner.QWENPAW_IMAGE
    assert "AI_NOVEL_TTS_RUNTIME_ENABLED=false" in commands[1]
    assert "AI_NOVEL_TTS_PRODUCT_ENABLED=false" in commands[1]
    assert "AI_NOVEL_TTS_VALIDATION_ENABLED=false" in commands[1]
    assert "AI_NOVEL_TTS_REFERENCE_CLONE_ENABLED=false" in commands[1]
    assert "PIP_NO_INDEX=1" in commands[1]
    assert "PIP_DISABLE_PIP_VERSION_CHECK=1" in commands[1]
    joined = "\n".join(" ".join(command) for command in commands)
    assert "docker compose" not in joined
    assert "moss-tts" not in joined.lower()
    assert "MOSS_TTS_" not in joined
    assert "/run/moss-tts-secrets" not in joined
    assert "/opt/moss-assets" not in joined
    assert "type=bind" not in joined
    assert "/gate/candidate" not in joined
    assert "--publish" not in commands[1]
    assert "5432:5432" not in joined
    copy_command = gate._candidate_copy_command()
    assert copy_command[:2] == ["docker", "cp"]
    assert copy_command[-1] == f"{names.qwenpaw_container}:/gate/candidate"
    assert copy_command[2].endswith("/candidate/.")
    assert "run" not in copy_command
    assert "create" not in copy_command


def test_source_contains_only_two_container_creation_vectors() -> None:
    tree = ast.parse(RUNNER_PATH.read_text(encoding="utf-8"))
    docker_run_vectors: list[int] = []
    docker_create_vectors: list[int] = []
    docker_compose_vectors: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.List):
            continue
        values = [
            item.value
            for item in node.elts[:3]
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        ]
        if values[:2] == ["docker", "run"]:
            docker_run_vectors.append(node.lineno)
        if values[:2] == ["docker", "create"]:
            docker_create_vectors.append(node.lineno)
        if values[:2] == ["docker", "compose"]:
            docker_compose_vectors.append(node.lineno)
    assert len(docker_run_vectors) == 2
    assert docker_create_vectors == []
    assert docker_compose_vectors == []


def _topology_executor(
    runner: ModuleType,
    names: object,
    env: list[str],
) -> object:
    class TopologyExecutor:
        def run(
            self,
            argv: Sequence[str],
            *,
            timeout: float,
            check: bool = True,
        ) -> object:
            del timeout, check
            command = list(argv)
            if command[:3] == ["docker", "network", "inspect"]:
                return runner.CommandResult(0, "true\n", "")
            if command[:3] == ["docker", "container", "ls"]:
                return runner.CommandResult(
                    0,
                    f"{names.qwenpaw_container}\n{names.postgres_container}\n",
                    "",
                )
            if command[:3] == ["docker", "container", "inspect"]:
                payload = [
                    {
                        "Config": {"Env": env},
                        "Mounts": [
                            {
                                "Type": "volume",
                                "Destination": "/app/working",
                            }
                        ],
                        "NetworkSettings": {
                            "Networks": {names.network: {}},
                            "Ports": {},
                        },
                        "HostConfig": {"PortBindings": {}},
                    }
                ]
                return runner.CommandResult(0, json.dumps(payload), "")
            raise AssertionError(f"unexpected command: {command}")

    return TopologyExecutor()


def _explicit_disabled_env() -> list[str]:
    return [
        "AI_NOVEL_TTS_RUNTIME_ENABLED=false",
        "AI_NOVEL_TTS_PRODUCT_ENABLED=false",
        "AI_NOVEL_TTS_VALIDATION_ENABLED=false",
        "AI_NOVEL_TTS_REFERENCE_CLONE_ENABLED=false",
        "PIP_NO_INDEX=1",
        "PIP_DISABLE_PIP_VERSION_CHECK=1",
    ]


def test_runtime_topology_strictly_verifies_all_four_tts_flags(
    runner: ModuleType,
    candidate: Path,
) -> None:
    names = runner.create_resource_names("abcd1234")
    gate = runner.LifecycleGate(
        runner.GateConfig(
            "real",
            "abcd1234",
            candidate,
            None,
            runner.REAL_CONFIRMATION,
        ),
        names,
        executor=_topology_executor(runner, names, _explicit_disabled_env()),
    )

    gate._verify_runtime_topology()

    assert gate.evidence.checks["tts-disabled-by-construction"] == {
        "runtime_env": False,
        "product_env": False,
        "validation_env": False,
        "reference_clone_env": False,
        "storage_root_env_count": 0,
        "moss_env_count": 0,
        "token_mount_count": 0,
        "model_mount_count": 0,
        "host_bind_mount_count": 0,
        "sidecar_network_present": False,
        "outbound_network_route": False,
        "python_package_index_access": False,
        "qwenpaw_host_port": False,
        "public_api_probe": "container-loopback",
    }


@pytest.mark.parametrize(
    ("removed", "code"),
    [
        (
            "AI_NOVEL_TTS_RUNTIME_ENABLED=false",
            "TTS_RUNTIME_NOT_EXPLICITLY_DISABLED",
        ),
        (
            "AI_NOVEL_TTS_PRODUCT_ENABLED=false",
            "TTS_PRODUCT_NOT_EXPLICITLY_DISABLED",
        ),
        (
            "AI_NOVEL_TTS_VALIDATION_ENABLED=false",
            "TTS_VALIDATION_NOT_EXPLICITLY_DISABLED",
        ),
        (
            "AI_NOVEL_TTS_REFERENCE_CLONE_ENABLED=false",
            "TTS_REFERENCE_CLONE_NOT_EXPLICITLY_DISABLED",
        ),
    ],
)
def test_runtime_topology_fails_when_any_tts_flag_is_not_explicit(
    runner: ModuleType,
    candidate: Path,
    removed: str,
    code: str,
) -> None:
    names = runner.create_resource_names("abcd1234")
    env = [item for item in _explicit_disabled_env() if item != removed]
    gate = runner.LifecycleGate(
        runner.GateConfig(
            "real",
            "abcd1234",
            candidate,
            None,
            runner.REAL_CONFIRMATION,
        ),
        names,
        executor=_topology_executor(runner, names, env),
    )

    with pytest.raises(runner.GateError, match=code):
        gate._verify_runtime_topology()


def test_runtime_topology_rejects_configured_tts_storage_roots(
    runner: ModuleType,
    candidate: Path,
) -> None:
    names = runner.create_resource_names("abcd1234")
    env = [
        *_explicit_disabled_env(),
        "AI_NOVEL_TTS_MEDIA_ROOT=/unexpected",
    ]
    gate = runner.LifecycleGate(
        runner.GateConfig(
            "real",
            "abcd1234",
            candidate,
            None,
            runner.REAL_CONFIRMATION,
        ),
        names,
        executor=_topology_executor(runner, names, env),
    )

    with pytest.raises(runner.GateError, match="TTS_STORAGE_ROOT_ENV_PRESENT"):
        gate._verify_runtime_topology()


class _InstalledContractGate:
    """Factory namespace for a concrete runner-owned lifecycle gate."""

    @staticmethod
    def build(
        runner: ModuleType,
        candidate: Path,
        *,
        production: dict[str, object] | None = None,
        route_cache_control: str | None = "no-store",
    ) -> object:
        names = runner.create_resource_names("abcd1234")
        config = runner.GateConfig(
            "real",
            "abcd1234",
            candidate,
            None,
            runner.REAL_CONFIRMATION,
        )
        snapshot = runner.RegistrySnapshot(
            ("default",),
            {"default": tuple(sorted(runner.NOVEL_SKILLS))},
            {"default": tuple(sorted(runner.NOVEL_TOOLS))},
        )

        class InstalledGate(runner.LifecycleGate):
            def __init__(self) -> None:
                super().__init__(config, names, executor=object())
                self.route_calls: list[tuple[str, str]] = []

            def _get_list(
                self,
                path: str,
                *,
                headers: object = None,
                step: str,
            ) -> list[dict[str, object]]:
                del headers, step
                assert path == "/api/plugins"
                return [
                    {
                        "id": runner.APP_ID,
                        "version": runner.APP_VERSION,
                        "loaded": True,
                    }
                ]

            def _http_json(
                self,
                method: str,
                path: str,
                **_kwargs: object,
            ) -> tuple[int, object]:
                assert method == "GET"
                if path == "/api/pawapps":
                    return 200, {
                        "apps": [
                            {
                                "id": runner.APP_ID,
                                "version": runner.APP_VERSION,
                            }
                        ]
                    }
                if path == f"/api/{runner.APP_ID}/health":
                    return 200, {
                        "app_id": runner.APP_ID,
                        "version": runner.APP_VERSION,
                        "narration": dict(runner.EXPECTED_DISABLED_NARRATION),
                        "narration_production": (
                            dict(runner.EXPECTED_DISABLED_NARRATION_PRODUCTION)
                            if production is None
                            else production
                        ),
                    }
                raise AssertionError(f"unexpected JSON route: {path}")

            def _http_bytes(
                self,
                method: str,
                path: str,
                **_kwargs: object,
            ) -> tuple[int, bytes]:
                assert method == "GET"
                assert path.endswith("/files/frontend/dist/index.js")
                return 200, b"export {};"

            def _raw_http_response(
                self,
                method: str,
                path: str,
                *,
                body: object = None,
                headers: object = None,
            ) -> tuple[int, str | None, bytes]:
                assert method == "GET"
                assert body is None
                assert headers is None
                self.route_calls.append((method, path))
                return 404, route_cache_control, b'{"detail":"not found"}'

            def _registry_snapshot(self) -> object:
                return snapshot

        return InstalledGate()


def test_installed_contract_requires_full_disabled_production_shape_and_routes(
    runner: ModuleType,
    candidate: Path,
) -> None:
    gate = _InstalledContractGate.build(runner, candidate)

    snapshot = gate._verify_installed_contract()

    assert snapshot.agent_ids == ("default",)
    assert gate.route_calls == [
        ("GET", path) for _route_class, path in runner.T4_DISABLED_ROUTE_PROBES
    ]
    assert gate.evidence.checks["narration-production-disabled"] == (
        runner.EXPECTED_DISABLED_NARRATION_PRODUCTION
    )
    assert gate.evidence.checks["t4-routes-disabled-without-token"] == {
        route_class: {
            "status": 404,
            "cache_control": "no-store",
            "validation_token_sent": False,
        }
        for route_class, _path in runner.T4_DISABLED_ROUTE_PROBES
    }


@pytest.mark.parametrize("variant", ["playback_only", "missing_reference_clone"])
def test_installed_contract_rejects_non_full_disabled_production_shape(
    runner: ModuleType,
    candidate: Path,
    variant: str,
) -> None:
    production = dict(runner.EXPECTED_DISABLED_NARRATION_PRODUCTION)
    if variant == "playback_only":
        production["lifecycle_status"] = "playback_only"
        production["playback_installed"] = True
    else:
        production.pop("reference_clone_ready")
    gate = _InstalledContractGate.build(
        runner,
        candidate,
        production=production,
    )

    with pytest.raises(
        runner.GateError,
        match="NARRATION_PRODUCTION_DISABLED_CONTRACT_INVALID",
    ):
        gate._verify_installed_contract()


def test_installed_contract_rejects_t4_404_without_no_store(
    runner: ModuleType,
    candidate: Path,
) -> None:
    gate = _InstalledContractGate.build(
        runner,
        candidate,
        route_cache_control="private, no-cache",
    )

    with pytest.raises(
        runner.GateError,
        match="T4_DISABLED_ROUTE_CONTRACT_INVALID",
    ):
        gate._verify_installed_contract()


def test_http_transport_captures_only_cache_control_header(
    runner: ModuleType,
    candidate: Path,
) -> None:
    class TransportExecutor:
        def __init__(self) -> None:
            self.command: list[str] | None = None

        def run(
            self,
            argv: Sequence[str],
            *,
            timeout: float,
            check: bool = True,
        ) -> object:
            del timeout, check
            self.command = list(argv)
            wrapper = {
                "status": 404,
                "cache_control": "no-store",
                "body_base64": base64.b64encode(b"hidden").decode("ascii"),
            }
            return runner.CommandResult(0, json.dumps(wrapper), "")

    names = runner.create_resource_names("abcd1234")
    executor = TransportExecutor()
    gate = runner.LifecycleGate(
        runner.GateConfig(
            "real",
            "abcd1234",
            candidate,
            None,
            runner.REAL_CONFIRMATION,
        ),
        names,
        executor=executor,
    )
    gate.base_url = "http://127.0.0.1:8088"

    result = gate._raw_http_response(
        "GET",
        runner.T4_DISABLED_ROUTE_PROBES[0][1],
    )

    assert result == (404, "no-store", b"hidden")
    assert executor.command is not None
    program_index = executor.command.index("-c") + 1
    compile(executor.command[program_index], "<container-http-probe>", "exec")
    assert json.loads(executor.command[-1]) == {"Accept": "application/json"}


def test_migration_exec_reasserts_all_four_disabled_flags(
    runner: ModuleType,
    candidate: Path,
) -> None:
    assert runner.EXPECTED_MIGRATION_HEAD == "20260829_0032"

    class MigrationExecutor:
        def __init__(self) -> None:
            self.commands: list[list[str]] = []

        def run(
            self,
            argv: Sequence[str],
            *,
            timeout: float,
            check: bool = True,
        ) -> object:
            del timeout, check
            command = list(argv)
            self.commands.append(command)
            stdout = (
                f"{runner.EXPECTED_MIGRATION_HEAD}\n"
                if "psql" in command
                else ""
            )
            return runner.CommandResult(0, stdout, "")

    names = runner.create_resource_names("abcd1234")
    executor = MigrationExecutor()
    gate = runner.LifecycleGate(
        runner.GateConfig(
            "real",
            "abcd1234",
            candidate,
            None,
            runner.REAL_CONFIRMATION,
        ),
        names,
        executor=executor,
    )
    plan = runner.build_dry_run_plan(gate.config, names)
    assert "migrate-to-20260829_0032" in plan["lifecycle"]

    gate._migrate_and_verify_head()

    migration = executor.commands[0]
    for item in _explicit_disabled_env()[:4]:
        assert migration.count(item) == 1


@pytest.mark.parametrize(
    "run_id",
    ["short", "UPPERCASE1", "bad-hyphen", "../../formal", "a" * 21],
)
def test_run_id_guard_rejects_unsafe_values(runner: ModuleType, run_id: str) -> None:
    with pytest.raises(runner.GateError, match="INVALID_RUN_ID"):
        runner.create_resource_names(run_id)


def test_resource_guard_rejects_formal_container_name(runner: ModuleType) -> None:
    names = runner.create_resource_names("abcd1234")
    unsafe = runner.ResourceNames(
        run_id=names.run_id,
        qwenpaw_container="ai-novel-2026-qwenpaw-lab",
        postgres_container=names.postgres_container,
        network=names.network,
        qwenpaw_data=names.qwenpaw_data,
        qwenpaw_secrets=names.qwenpaw_secrets,
        qwenpaw_backups=names.qwenpaw_backups,
        novel_media=names.novel_media,
        postgres_data=names.postgres_data,
    )
    with pytest.raises(runner.GateError, match="UNSAFE_RESOURCE_NAME"):
        runner.validate_resource_names(unsafe)


def test_candidate_staging_uses_docker_cp_and_no_helper_container(
    runner: ModuleType,
    candidate: Path,
) -> None:
    _, digest = runner.validate_candidate(candidate)
    run_id = "abcd1234"
    names = runner.create_resource_names(run_id)

    class StageExecutor:
        def __init__(self) -> None:
            self.commands: list[list[str]] = []

        def run(
            self,
            argv: Sequence[str],
            *,
            timeout: float,
            check: bool = True,
        ) -> object:
            del timeout, check
            command = list(argv)
            self.commands.append(command)
            stdout = ""
            if "/app/venv/bin/python" in command:
                stdout = f"{digest}\n"
            return runner.CommandResult(0, stdout, "")

    executor = StageExecutor()
    config = runner.GateConfig(
        "real",
        run_id,
        candidate,
        None,
        runner.REAL_CONFIRMATION,
        candidate_tree_sha256=digest,
    )
    gate = runner.LifecycleGate(config, names, executor=executor)

    gate._stage_candidate()

    assert [command[:2] for command in executor.commands] == [
        ["docker", "exec"],
        ["docker", "cp"],
        ["docker", "exec"],
    ]
    flattened = [part for command in executor.commands for part in command]
    assert "run" not in flattened
    assert "create" not in flattened
    assert "type=bind" not in flattened
    assert gate.evidence.checks["candidate-staging"] == {
        "method": "docker-cp",
        "container_path": "/gate/candidate",
        "tree_sha256": digest,
        "host_bind_mount_count": 0,
        "helper_container_count": 0,
        "host_copy_detached": True,
        "integrity_rechecked_before_each_install": True,
    }


def test_failed_command_is_recorded_before_safe_error(
    runner: ModuleType,
    candidate: Path,
) -> None:
    class FailingExecutor:
        def run(
            self,
            _argv: Sequence[str],
            *,
            timeout: float,
            check: bool = True,
        ) -> object:
            del timeout
            assert check is False
            return runner.CommandResult(17, "sensitive stdout", "sensitive stderr")

    run_id = "abcd1234"
    names = runner.create_resource_names(run_id)
    config = runner.GateConfig(
        "real", run_id, candidate, None, runner.REAL_CONFIRMATION
    )
    gate = runner.LifecycleGate(config, names, executor=FailingExecutor())

    with pytest.raises(runner.GateError, match="COMMAND_FAILED") as raised:
        gate._run_command(["example", "command"], step="diagnostic-step")

    assert raised.value.detail == "diagnostic-step"
    recorded = gate.evidence.checks["command:diagnostic-step"]
    assert recorded == {
        "returncode": 17,
        "stdout_sha256": runner._sha256_text("sensitive stdout"),
        "stderr_sha256": runner._sha256_text("sensitive stderr"),
    }
    assert "sensitive" not in json.dumps(recorded)


class CleanupExecutor:
    def __init__(self, runner: ModuleType, run_id: str) -> None:
        self.runner = runner
        self.run_id = run_id
        self.commands: list[list[str]] = []

    def run(
        self,
        argv: Sequence[str],
        *,
        timeout: float,
        check: bool = True,
    ) -> object:
        del timeout, check
        command = list(argv)
        self.commands.append(command)
        if "inspect" in command and "--format" in command:
            return self.runner.CommandResult(
                0,
                f"{self.run_id}|{self.runner.GATE_LABEL_VALUE}\n",
                "",
            )
        return self.runner.CommandResult(0, "", "")


def test_cleanup_checks_labels_and_removes_only_exact_run_resources(
    runner: ModuleType,
    candidate: Path,
) -> None:
    run_id = "abcd1234"
    names = runner.create_resource_names(run_id)
    executor = CleanupExecutor(runner, run_id)
    config = runner.GateConfig("real", run_id, candidate, None, runner.REAL_CONFIRMATION)
    gate = runner.LifecycleGate(config, names, executor=executor)
    gate._attempted = [
        ("network", names.network),
        *[("volume", name) for name in names.volumes],
        ("container", names.postgres_container),
        ("container", names.qwenpaw_container),
    ]

    gate._cleanup()

    flattened = [part for command in executor.commands for part in command]
    assert "compose" not in flattened
    assert "down" not in flattened
    assert "prune" not in flattened
    assert "-v" not in flattened
    removal_commands = [
        command
        for command in executor.commands
        if "rm" in command and "inspect" not in command
    ]
    assert len(removal_commands) == 8
    allowed = set(names.containers) | set(names.volumes) | {names.network}
    for command in removal_commands:
        assert command[-1] in allowed
    assert gate.evidence.cleanup["status"] == "passed"
    assert gate.evidence.cleanup["broad_cleanup_used"] is False


def test_cleanup_refuses_foreign_labels(
    runner: ModuleType,
    candidate: Path,
) -> None:
    run_id = "abcd1234"
    names = runner.create_resource_names(run_id)
    executor = CleanupExecutor(runner, "foreignrun")
    config = runner.GateConfig("real", run_id, candidate, None, runner.REAL_CONFIRMATION)
    gate = runner.LifecycleGate(config, names, executor=executor)
    gate._attempted = [("volume", names.postgres_data)]

    with pytest.raises(runner.GateError, match="EXACT_CLEANUP_FAILED"):
        gate._cleanup()

    assert not any("rm" in command for command in executor.commands)


def test_dry_run_output_is_sanitized(
    runner: ModuleType,
    candidate: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = runner.main(
        [
            "--mode",
            "dry-run",
            "--candidate",
            str(candidate),
            "--run-id",
            "abcd1234",
        ]
    )
    assert result == 0
    output = capsys.readouterr().out
    assert str(candidate) not in output
    assert "POSTGRES_PASSWORD" not in output
    assert "AI_NOVEL_DATABASE_URL" not in output
    assert "X-MOSS" not in output
    assert runner.REAL_CONFIRMATION not in output


def test_real_mode_requires_exact_confirmation(
    runner: ModuleType,
    candidate: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("confirmation guard ran Docker")
        ),
    )
    result = runner.main(
        [
            "--mode",
            "real",
            "--candidate",
            str(candidate),
            "--run-id",
            "abcd1234",
        ]
    )
    assert result == 1
    error = json.loads(capsys.readouterr().err)
    assert error["failure_code"] == "REAL_MODE_CONFIRMATION_REQUIRED"


def test_resource_absence_requires_a_specific_not_found_error(runner: ModuleType) -> None:
    assert runner._resource_is_absent(
        "container", runner.CommandResult(1, "", "No such container: isolated")
    )
    assert runner._resource_is_absent(
        "volume", runner.CommandResult(1, "", "No such volume: isolated")
    )
    assert runner._resource_is_absent(
        "network",
        runner.CommandResult(1, "", "network isolated not found"),
    )
    assert not runner._resource_is_absent(
        "container",
        runner.CommandResult(1, "", "Cannot connect to the Docker daemon"),
    )


def test_orchestration_uses_public_lifecycle_order_and_finally_cleanup(
    runner: ModuleType,
    candidate: Path,
) -> None:
    run_id = "abcd1234"
    names = runner.create_resource_names(run_id)
    config = runner.GateConfig("real", run_id, candidate, None, runner.REAL_CONFIRMATION)
    snapshot = runner.RegistrySnapshot(
        ("default",),
        {"default": tuple(sorted(runner.NOVEL_SKILLS))},
        {"default": tuple(sorted(runner.NOVEL_TOOLS))},
    )

    class OrchestrationGate(runner.LifecycleGate):
        def __init__(self) -> None:
            super().__init__(config, names, executor=object())
            self.actions: list[object] = []

        def _preflight(self) -> None:
            self.actions.append("preflight")

        def _create_resources(self) -> None:
            self.actions.append("create")

        def _wait_for_services(self) -> None:
            self.actions.append("wait")

        def _stage_candidate(self) -> None:
            self.actions.append("stage-candidate")

        def _install(self, *, force: bool, step: str) -> None:
            self.actions.append(("install", force, step))

        def _migrate_and_verify_head(self) -> None:
            self.actions.append("migrate")

        def _wait_for_installed_contract(self) -> object:
            self.actions.append("verify-installed")
            return snapshot

        def _create_sentinels(self) -> dict[str, str]:
            self.actions.append("create-sentinels")
            return {"novel_id": "sentinel"}

        def _verify_sentinels(self, _sentinels: object) -> None:
            self.actions.append("verify-sentinels")

        def _http_json(self, method: str, path: str, **_kwargs: object) -> object:
            self.actions.append((method, path))
            return 200, {"id": runner.APP_ID}

        def _wait_for_uninstalled_contract(self) -> None:
            self.actions.append("verify-uninstalled")

        def _verify_novel_route(self, _novel_id: str) -> None:
            self.actions.append("verify-novel-route")

        def _cleanup(self) -> None:
            self.actions.append("cleanup")
            self.evidence.cleanup = {"status": "passed"}

        def _write_transcript(self) -> None:
            self.actions.append("transcript")

    gate = OrchestrationGate()
    result = gate.run()

    assert result["status"] == "passed"
    assert [action for action in gate.actions if isinstance(action, tuple)] == [
        ("install", False, "initial-install"),
        ("install", True, "force-reinstall"),
        ("DELETE", f"/api/plugins/{runner.APP_ID}"),
        ("install", False, "reinstall"),
    ]
    assert gate.actions[-2:] == ["cleanup", "transcript"]
    assert gate.actions.index("stage-candidate") < gate.actions.index("wait")


def test_orchestration_cleans_up_when_a_phase_fails(
    runner: ModuleType,
    candidate: Path,
) -> None:
    run_id = "abcd1234"
    names = runner.create_resource_names(run_id)
    config = runner.GateConfig("real", run_id, candidate, None, runner.REAL_CONFIRMATION)

    class FailingGate(runner.LifecycleGate):
        def __init__(self) -> None:
            super().__init__(config, names, executor=object())
            self.cleaned = False

        def _preflight(self) -> None:
            raise runner.GateError("EXPECTED_TEST_FAILURE")

        def _cleanup(self) -> None:
            self.cleaned = True
            self.evidence.cleanup = {"status": "passed"}

        def _write_transcript(self) -> None:
            return None

    gate = FailingGate()
    with pytest.raises(runner.GateError, match="EXPECTED_TEST_FAILURE"):
        gate.run()
    assert gate.cleaned is True
