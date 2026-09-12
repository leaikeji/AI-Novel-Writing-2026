from __future__ import annotations

import ast
import base64
import importlib.util
import json
import os
import shutil
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
        "alembic.ini": "[alembic]\nscript_location = backend/migrations\n",
        "frontend/dist/index.js": "export {};\n",
        "backend/app.py": "",
        "backend/narration/providers/local.py": "",
        (
            "backend/migrations/versions/"
            "20260823_0001_fixture.py"
        ): (
            "revision = '20260823_0001'\n"
            "down_revision = None\n"
            "branch_labels = None\n"
            "depends_on = None\n"
        ),
        (
            "backend/migrations/versions/"
            "20260901_0036_fixture.py"
        ): (
            "revision = '20260901_0036'\n"
            "down_revision = '20260823_0001'\n"
            "branch_labels = None\n"
            "depends_on = None\n"
        ),
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
    assert output["candidate"]["migration_head"] == "20260901_0036"
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
        expected_skills: frozenset[str] | None = None,
        registered_skills: frozenset[str] | None = None,
    ) -> object:
        names = runner.create_resource_names("abcd1234")
        config = runner.GateConfig(
            "real",
            "abcd1234",
            candidate,
            None,
            runner.REAL_CONFIRMATION,
            candidate_skill_ids=runner.NOVEL_SKILLS if expected_skills is None else expected_skills,
        )
        snapshot = runner.RegistrySnapshot(
            ("default",),
            {"default": tuple(sorted(runner.NOVEL_SKILLS if registered_skills is None else registered_skills))},
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


def _copy_approved_skills(candidate: Path) -> frozenset[str]:
    relative = "backend/writing_skills/approved-capabilities.json"
    target = candidate / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PROJECT_ROOT / relative, target)
    approvals = json.loads(target.read_text(encoding="utf-8"))
    for approval in approvals:
        skill_id = approval["skill_id"]
        shutil.copytree(PROJECT_ROOT / "skills" / skill_id, candidate / "skills" / skill_id)
    return frozenset(approval["skill_id"] for approval in approvals)


def test_candidate_skill_inventory_uses_frozen_approved_catalog(runner: ModuleType, candidate: Path) -> None:
    approved = _copy_approved_skills(candidate)
    assert runner.candidate_published_skill_ids(candidate) == runner.NOVEL_SKILLS | approved
    runner.validate_candidate(candidate)


@pytest.mark.parametrize("variant", ["missing_index", "missing_skill", "changed_asset", "unapproved_extra", "bad_index"])
def test_candidate_skill_inventory_rejects_invalid_publication(
    runner: ModuleType, candidate: Path, variant: str,
) -> None:
    approved = _copy_approved_skills(candidate)
    approval_path = candidate / "backend/writing_skills/approved-capabilities.json"
    skill_path = candidate / "skills" / sorted(approved)[0] / "SKILL.md"
    if variant == "missing_index":
        approval_path.unlink()
    elif variant == "missing_skill":
        skill_path.unlink()
    elif variant == "changed_asset":
        skill_path.write_text("changed content", encoding="utf-8")
    elif variant == "bad_index":
        approval_path.write_text("{}", encoding="utf-8")
    else:
        extra = candidate / "skills" / "unapproved-extra"
        extra.mkdir()
        (extra / "SKILL.md").write_text("unapproved", encoding="utf-8")
    with pytest.raises(runner.GateError, match="CANDIDATE_SKILL_CATALOG_INVALID"):
        runner.validate_candidate(candidate)


@pytest.mark.parametrize("variant", ["exact", "missing", "extra"])
def test_installed_registry_matches_frozen_approved_inventory(
    runner: ModuleType, candidate: Path, variant: str,
) -> None:
    approved = _copy_approved_skills(candidate)
    expected = runner.candidate_published_skill_ids(candidate)
    actual = expected if variant == "exact" else (
        expected - approved if variant == "missing" else expected | {"unapproved-extra"}
    )
    gate = _InstalledContractGate.build(runner, candidate, expected_skills=expected, registered_skills=actual)
    if variant == "exact":
        gate._verify_installed_contract()
        assert gate.evidence.checks["expected-published-skill-ids"] == sorted(expected)
    else:
        with pytest.raises(runner.GateError, match="PLUGIN_SKILL_REGISTRY_INVALID"):
            gate._verify_installed_contract()


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


def test_non_json_failure_records_status_without_response_contents(
    runner: ModuleType, candidate: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = _InstalledContractGate.build(runner, candidate)
    private_body = b"internal error with confidential response details"
    monkeypatch.setattr(gate, "_raw_http_bytes", lambda *args, **kwargs: (500, private_body))
    with pytest.raises(runner.GateError, match="HTTP_RESPONSE_NOT_JSON"):
        gate._raw_http_json("POST", f"/api/{runner.APP_ID}/novels")
    evidence = gate.evidence.checks["http-invalid-json"]
    assert evidence["status"] == 500
    assert evidence["response_sha256"] == runner._sha256_bytes(private_body)
    assert private_body.decode() not in json.dumps(evidence)


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


def test_install_retries_only_the_exact_public_loader_not_ready_response(
    runner: ModuleType,
    candidate: Path,
) -> None:
    names = runner.create_resource_names("abcd1234")
    sleeps: list[float] = []

    class InstallGate(runner.LifecycleGate):
        def __init__(self) -> None:
            super().__init__(
                runner.GateConfig(
                    "real",
                    "abcd1234",
                    candidate,
                    None,
                    runner.REAL_CONFIRMATION,
                ),
                names,
                executor=object(),
                sleep=sleeps.append,
                monotonic=lambda: 0,
            )
            self.responses = iter(
                (
                    (503, dict(runner.PLUGIN_LOADER_NOT_READY)),
                    (
                        200,
                        {
                            "id": runner.APP_ID,
                            "version": runner.APP_VERSION,
                            "loaded": True,
                        },
                    ),
                )
            )

        def _read_staged_candidate_digest(self, *, step: str) -> str:
            assert step == "verify-candidate-before-initial-install"
            return "a" * 64

        def _raw_http_json(self, *args: object, **kwargs: object) -> tuple[int, object]:
            del args, kwargs
            return next(self.responses)

    gate = InstallGate()
    gate._install(force=False, step="initial-install")

    assert sleeps == [1]
    assert gate.evidence.checks["http:initial-install"] == {
        "method": "POST",
        "path": "/api/plugins/install",
        "status": 200,
        "attempts": 2,
        "response_sha256": runner._sha256_text(
            json.dumps(
                {
                    "id": runner.APP_ID,
                    "version": runner.APP_VERSION,
                    "loaded": True,
                },
                sort_keys=True,
                ensure_ascii=True,
                separators=(",", ":"),
            )
        ),
    }


def test_install_does_not_retry_an_unrecognized_503(
    runner: ModuleType,
    candidate: Path,
) -> None:
    names = runner.create_resource_names("abcd1234")
    sleeps: list[float] = []

    class InstallGate(runner.LifecycleGate):
        def __init__(self) -> None:
            super().__init__(
                runner.GateConfig(
                    "real",
                    "abcd1234",
                    candidate,
                    None,
                    runner.REAL_CONFIRMATION,
                ),
                names,
                executor=object(),
                sleep=sleeps.append,
                monotonic=lambda: 0,
            )

        def _read_staged_candidate_digest(self, *, step: str) -> str:
            del step
            return "a" * 64

        def _raw_http_json(self, *args: object, **kwargs: object) -> tuple[int, object]:
            del args, kwargs
            return 503, {"detail": "different failure"}

    gate = InstallGate()
    with pytest.raises(runner.GateError, match="HTTP_STATUS_UNEXPECTED"):
        gate._install(force=False, step="initial-install")

    assert sleeps == []


def test_migration_exec_reasserts_all_four_disabled_flags(
    runner: ModuleType,
    candidate: Path,
) -> None:
    expected_head = "20260901_0036"

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
            stdout = ""
            if "psql" in command:
                stdout = f"{expected_head}\n"
            elif any(part.endswith("alembic.ini heads") for part in command):
                stdout = f"{expected_head} (head)\n"
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
            candidate_migration_head=expected_head,
        ),
        names,
        executor=executor,
    )
    plan = runner.build_dry_run_plan(gate.config, names)
    assert f"migrate-to-{expected_head}" in plan["lifecycle"]

    gate._migrate_and_verify_head()

    assert gate.evidence.checks["candidate-alembic-head"] == expected_head
    assert gate.evidence.checks["migration-head"] == expected_head
    for command in executor.commands[:2]:
        for item in _explicit_disabled_env()[:4]:
            assert command.count(item) == 1


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
    _, digest, candidate_head = runner.validate_candidate(candidate)
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
        candidate_migration_head=candidate_head,
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
        "migration_head": candidate_head,
        "host_bind_mount_count": 0,
        "helper_container_count": 0,
        "host_copy_detached": True,
        "integrity_rechecked_before_each_install": True,
    }


@pytest.mark.parametrize(
    ("limit_name", "limit_value", "failure_code"),
    [
        (
            "CANDIDATE_TREE_MAX_ENTRIES",
            0,
            "CANDIDATE_TREE_ENTRY_LIMIT_EXCEEDED",
        ),
        ("CANDIDATE_TREE_MAX_FILES", 0, "CANDIDATE_TREE_FILE_LIMIT_EXCEEDED"),
        ("CANDIDATE_TREE_MAX_FILE_BYTES", 0, "CANDIDATE_TREE_FILE_TOO_LARGE"),
        (
            "CANDIDATE_TREE_MAX_TOTAL_BYTES",
            0,
            "CANDIDATE_TREE_TOTAL_BYTES_EXCEEDED",
        ),
    ],
)
def test_candidate_tree_resource_limits_fail_before_external_io(
    runner: ModuleType,
    candidate: Path,
    monkeypatch: pytest.MonkeyPatch,
    limit_name: str,
    limit_value: int,
    failure_code: str,
) -> None:
    monkeypatch.setattr(runner, limit_name, limit_value)

    with pytest.raises(runner.GateError, match=failure_code):
        runner._candidate_tree_sha256(candidate)


def test_validate_candidate_applies_tree_limits_before_manifest_parsing(
    runner: ModuleType,
    candidate: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (candidate / "plugin.json").write_text("not json", encoding="utf-8")
    monkeypatch.setattr(runner, "CANDIDATE_TREE_MAX_ENTRIES", 0)

    with pytest.raises(
        runner.GateError,
        match="CANDIDATE_TREE_ENTRY_LIMIT_EXCEEDED",
    ):
        runner.validate_candidate(candidate)


def test_candidate_tree_detects_file_identity_drift_during_hash(
    runner: ModuleType,
    candidate: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = runner._hash_candidate_file
    target = "frontend/dist/index.js"
    changed = False

    def drift_before_read(
        root_descriptor: int,
        relative: str,
        before: object,
        digest: object,
    ) -> None:
        nonlocal changed
        if relative == target and not changed:
            changed = True
            path = candidate / target
            path.write_text("export const drift = true;\n", encoding="utf-8")
        original(root_descriptor, relative, before, digest)

    monkeypatch.setattr(runner, "_hash_candidate_file", drift_before_read)

    with pytest.raises(runner.GateError, match="CANDIDATE_TREE_IDENTITY_CHANGED"):
        runner._candidate_tree_sha256(candidate)
    assert changed is True


def test_candidate_tree_digest_includes_empty_directories(
    runner: ModuleType,
    candidate: Path,
) -> None:
    original = runner._candidate_tree_sha256(candidate)
    empty = candidate / "empty-contract-directory"
    empty.mkdir()

    changed = runner._candidate_tree_sha256(candidate)

    assert changed != original


def test_candidate_tree_rejects_symlinks_hardlinks_and_special_files(
    runner: ModuleType,
    candidate: Path,
) -> None:
    link = candidate / "candidate-link"
    link.symlink_to(candidate / "plugin.json")
    with pytest.raises(runner.GateError, match="CANDIDATE_SYMLINK_FORBIDDEN"):
        runner._candidate_tree_sha256(candidate)
    link.unlink()

    hardlink = candidate / "candidate-hardlink"
    os.link(candidate / "plugin.json", hardlink)
    with pytest.raises(runner.GateError, match="CANDIDATE_HARDLINK_FORBIDDEN"):
        runner._candidate_tree_sha256(candidate)
    hardlink.unlink()

    fifo = candidate / "candidate-fifo"
    os.mkfifo(fifo)
    try:
        with pytest.raises(
            runner.GateError,
            match="CANDIDATE_SPECIAL_FILE_FORBIDDEN",
        ):
            runner._candidate_tree_sha256(candidate)
    finally:
        fifo.unlink()


def test_candidate_is_rehashed_before_docker_copy(
    runner: ModuleType,
    candidate: Path,
) -> None:
    _, digest, candidate_head = runner.validate_candidate(candidate)
    (candidate / "frontend" / "dist" / "index.js").write_text(
        "export const changed = true;\n",
        encoding="utf-8",
    )

    class ForbiddenExecutor:
        def run(self, *_args: object, **_kwargs: object) -> object:
            raise AssertionError("drift must fail before Docker")

    names = runner.create_resource_names("abcd1234")
    gate = runner.LifecycleGate(
        runner.GateConfig(
            "real",
            "abcd1234",
            candidate,
            None,
            runner.REAL_CONFIRMATION,
            candidate_tree_sha256=digest,
            candidate_migration_head=candidate_head,
        ),
        names,
        executor=ForbiddenExecutor(),
    )

    with pytest.raises(runner.GateError, match="HOST_CANDIDATE_DIGEST_MISMATCH"):
        gate._stage_candidate()


def test_gate_config_head_cannot_drift_to_a_different_candidate_head(
    runner: ModuleType,
    candidate: Path,
) -> None:
    _, _, frozen_head = runner.validate_candidate(candidate)
    versions = candidate / "backend" / "migrations" / "versions"
    (versions / "20260901_0036_fixture.py").unlink()
    (versions / "20260902_0037_fixture.py").write_text(
        (
            "revision = '20260902_0037'\n"
            "down_revision = '20260823_0001'\n"
            "branch_labels = None\n"
            "depends_on = None\n"
        ),
        encoding="utf-8",
    )
    changed_digest = runner._candidate_tree_sha256(candidate)

    class ForbiddenExecutor:
        def run(self, *_args: object, **_kwargs: object) -> object:
            raise AssertionError("head drift must fail before Docker")

    gate = runner.LifecycleGate(
        runner.GateConfig(
            "real",
            "abcd1234",
            candidate,
            None,
            runner.REAL_CONFIRMATION,
            candidate_tree_sha256=changed_digest,
            candidate_migration_head=frozen_head,
        ),
        runner.create_resource_names("abcd1234"),
        executor=ForbiddenExecutor(),
    )

    with pytest.raises(
        runner.GateError,
        match="HOST_CANDIDATE_MIGRATION_HEAD_MISMATCH",
    ):
        gate._stage_candidate()


def test_container_hash_probe_is_bounded_streaming_and_no_follow(
    runner: ModuleType,
    candidate: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected_digest = runner._candidate_tree_sha256(candidate)
    program = runner._container_candidate_hash_program(str(candidate))

    compile(program, "<container-candidate-hash>", "exec")
    exec(program, {})
    assert capsys.readouterr().out.strip() == expected_digest
    assert "read_bytes" not in program
    assert "os.walk" not in program
    assert "os.scandir(directory_descriptor)" in program
    assert "O_NOFOLLOW" in program
    assert "dir_fd=" in program
    assert f"MAX_ENTRIES = {runner.CANDIDATE_TREE_MAX_ENTRIES}" in program
    assert f"MAX_FILES = {runner.CANDIDATE_TREE_MAX_FILES}" in program
    assert f"MAX_FILE_BYTES = {runner.CANDIDATE_TREE_MAX_FILE_BYTES}" in program
    assert f"MAX_TOTAL_BYTES = {runner.CANDIDATE_TREE_MAX_TOTAL_BYTES}" in program


@pytest.mark.parametrize(
    ("limit_name", "failure_code"),
    [
        ("CANDIDATE_TREE_MAX_ENTRIES", "ENTRY_LIMIT"),
        ("CANDIDATE_TREE_MAX_FILES", "FILE_COUNT"),
        ("CANDIDATE_TREE_MAX_FILE_BYTES", "FILE_TOO_LARGE"),
        ("CANDIDATE_TREE_MAX_TOTAL_BYTES", "TOTAL_BYTES"),
    ],
)
def test_container_hash_probe_enforces_each_resource_limit(
    runner: ModuleType,
    candidate: Path,
    monkeypatch: pytest.MonkeyPatch,
    limit_name: str,
    failure_code: str,
) -> None:
    monkeypatch.setattr(runner, limit_name, 0)
    program = runner._container_candidate_hash_program(str(candidate))

    with pytest.raises(RuntimeError, match=failure_code):
        exec(program, {})


def test_container_hash_probe_detects_identity_drift(
    runner: ModuleType,
    candidate: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_read = os.read
    changed = False

    def mutate_first_file(descriptor: int, count: int) -> bytes:
        nonlocal changed
        if not changed:
            changed = True
            (candidate / "alembic.ini").write_text(
                "[alembic]\nscript_location = backend/migrations\n# drift\n",
                encoding="utf-8",
            )
        return original_read(descriptor, count)

    monkeypatch.setattr(os, "read", mutate_first_file)
    program = runner._container_candidate_hash_program(str(candidate))

    with pytest.raises(RuntimeError, match="FILE_IDENTITY"):
        exec(program, {})
    assert changed is True


def test_candidate_failure_context_never_exposes_candidate_filename(
    runner: ModuleType,
    candidate: Path,
) -> None:
    versions = candidate / "backend" / "migrations" / "versions"
    source = versions / "20260901_0036_fixture.py"
    controlled_name = "20260901_9999_candidate-controlled-secret.py"
    source.rename(versions / controlled_name)

    with pytest.raises(runner.GateError) as raised:
        runner.validate_candidate(candidate)

    assert raised.value.code == "MIGRATION_FILENAME_MISMATCH"
    assert raised.value.detail == ""
    assert controlled_name not in raised.value.detail


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


@pytest.fixture
def skill_gate(runner: ModuleType, candidate: Path, tmp_path: Path,
               monkeypatch: pytest.MonkeyPatch):
    """Run real project install/restore functions against in-memory public I/O."""
    shutil.copytree(PROJECT_ROOT / "skills", candidate / "skills", dirs_exist_ok=True)
    approval = candidate / "backend/writing_skills/approved-capabilities.json"
    approval.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PROJECT_ROOT / "backend/writing_skills/approved-capabilities.json", approval)
    resolved, digest, head = runner.validate_candidate(candidate)
    names = runner.create_resource_names("s69fake001")
    config = runner.GateConfig(
        "real", names.run_id, resolved, tmp_path / "transcript.json", runner.REAL_CONFIRMATION,
        candidate_tree_sha256=digest, candidate_migration_head=head,
        candidate_skill_ids=runner.candidate_published_skill_ids(candidate), skill_state_check=True,
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("fake Skill gate escaped to subprocess")

    monkeypatch.setattr(subprocess, "run", forbidden)

    class SkillGate(runner.LifecycleGate):
        def __init__(self):
            super().__init__(config, names, executor=object())
            self.agents = {"default": {}, "QwenPaw_QA_Agent_0.2": {}}
            self.native = {"default": True, "QwenPaw_QA_Agent_0.2": False}
            self.installed = False
            self.running = True
            self.helper_exists = False
            self.cleaned = False
            self.fault = None
            self.ack_lost = False
            self.http_calls = []
            self.commands = []
            self.events = []

        def _preflight(self):
            self.events.append("preflight")

        def _create_resources(self):
            self.events.append("create")

        def _stage_candidate(self):
            self.events.append("stage")

        def _wait_for_services(self):
            assert self.running
            self.base_url = "http://127.0.0.1:8088"

        def _read_staged_candidate_digest(self, *, step):
            return digest

        def _replace(self):
            self.installed = True
            for agent in self.agents:
                self.agents[agent] = {name: False for name in config.candidate_skill_ids}

        def _install(self, *, force, step):
            self.events.append(step)
            self._replace()

        def _migrate_and_verify_head(self):
            assert self.running
            self.events.append("migrate")

        def _wait_for_installed_contract(self):
            assert self.installed
            return self._registry_snapshot()

        def _create_sentinels(self):
            return {"novel_id": "sentinel"}

        def _verify_sentinels(self, sentinels):
            assert sentinels == {"novel_id": "sentinel"}
            self.events.append("sentinels")

        def _verify_novel_route(self, novel_id):
            assert self.installed and novel_id == "sentinel"

        def _http_json(self, method, path, *, body=None, headers=None, **kwargs):
            assert self.running
            agent_id = (headers or {}).get("X-Agent-Id")
            self.http_calls.append((method, path, agent_id, body))
            if path == "/api/agents":
                if method == "POST":
                    assert body["id"] not in self.agents
                    assert not {"model", "provider_id", "model_id"} & body.keys()
                    self.agents[body["id"]] = {name: False for name in config.candidate_skill_ids}
                    self.native[body["id"]] = False
                    return 200, {"id": body["id"]}
                return 200, {"agents": [{"id": agent} for agent in sorted(self.agents)]}
            if path == "/api/skills":
                rows = [{"name": "native-helper", "source": "builtin", "enabled": self.native[agent_id]}]
                rows.extend({"name": name, "source": f"plugin:{runner.APP_ID}", "enabled": enabled}
                            for name, enabled in self.agents[agent_id].items())
                return 200, rows
            if path in {"/api/skills/batch-enable", "/api/skills/batch-disable"}:
                assert method == "POST" and agent_id == "ai-novel-writer"
                if self.fault != "lost-restore" or "hot-install" not in self.events:
                    for name in body:
                        self.agents[agent_id][name] = path.endswith("batch-enable")
                if self.fault == "ack-lost" and "hot-install" in self.events and not self.ack_lost:
                    self.ack_lost = True
                    return 500, {"detail": "simulated lost acknowledgement after applying"}
                return 200, {"results": {name: {"success": True} for name in body}}
            if path == "/api/tools":
                return 200, [{"name": name} for name in runner.NOVEL_TOOLS] if self.installed else []
            if method == "DELETE" and path == f"/api/plugins/{runner.APP_ID}":
                self.events.append("uninstall")
                self.installed = False
                for agent in self.agents:
                    self.agents[agent] = {}
                if self.fault == "uninstall-residue":
                    self.agents["default"]["prose-writing"] = False
                return 200, {"id": runner.APP_ID}
            raise AssertionError((method, path))

        def _wait_for_uninstalled_contract(self):
            snapshot = self._registry_snapshot()
            if any(snapshot.skills_by_agent.values()) or any(snapshot.tools_by_agent.values()):
                raise runner.GateError("PLUGIN_SKILL_RESIDUE_PRESENT")
            self.evidence.checks["uninstalled-zero-residue"] = snapshot.as_dict()

        def _run_command(self, argv, *, step, **kwargs):
            argv = list(argv)
            self.commands.append(argv)
            helper = f"{names.qwenpaw_container}-plugin-installer"
            assert argv[0] == "docker"
            verb = argv[1]
            if verb == "restart":
                assert argv[2:] == [names.qwenpaw_container]
                self.events.append("restart")
                if self.fault == "restart-drift":
                    self.agents["ai-novel-writer"]["prose-writing"] = False
            elif verb == "stop":
                assert argv[-1] == names.qwenpaw_container
                self.events.append("offline-stop")
                self.running = False
            elif verb == "inspect":
                assert argv[2] == names.qwenpaw_container
                return runner.CommandResult(0, json.dumps([{
                    "Name": f"/{names.qwenpaw_container}", "Id": "a" * 64,
                    "Image": "sha256:" + "b" * 64, "State": {"Running": self.running},
                    "Mounts": [{"Type": "volume", "Name": name, "Destination": destination, "RW": True}
                               for name, destination in (
                                   (names.qwenpaw_data, "/app/working"),
                                   (names.qwenpaw_secrets, "/app/working.secret"),
                                   (names.qwenpaw_backups, "/app/working.backups"),
                               )],
                }]))
            elif verb == "exec":
                assert argv[2] == names.qwenpaw_container
                if argv[3:6] == ["qwenpaw", "plugin", "install"]:
                    self.events.append("hot-install")
                    self._replace()
                    if self.fault == "other-agent-drift":
                        self.native["default"] = False
                    return runner.CommandResult(0, "private log must not be printed")
                assert argv[3:6] == ["rm", "-rf", "--"]
                assert argv[-1].startswith(f"/tmp/{runner.APP_ID}-install-")
            elif verb == "cp":
                if argv[2].startswith(f"{helper}:"):
                    shutil.copytree(candidate, Path(argv[3]), dirs_exist_ok=True)
            elif verb == "create":
                assert not self.running
                assert argv[argv.index("--name") + 1] == helper
                assert argv[argv.index("--network") + 1] == "none"
                assert all(label in argv for label in self.ownership_labels)
                assert "PIP_NO_INDEX=1" in argv
                self.helper_exists = True
                self.events.append("offline-create")
            elif verb == "ps":
                return runner.CommandResult(0, f"{helper}\tqwenpaw-plugin-installer" if self.helper_exists else "")
            elif verb == "start":
                if argv[2] == helper:
                    assert not self.running
                    self.events.append("offline-install")
                    self._replace()
                    if self.fault == "offline-started-host":
                        self.running = True
                else:
                    assert argv[2] == names.qwenpaw_container and not self.running
                    self.events.append("offline-start")
                    self.running = True
            elif verb == "wait":
                assert argv[2] == helper
                return runner.CommandResult(0, "0")
            elif verb == "logs":
                return runner.CommandResult(0, "private offline log must not be printed")
            elif verb == "rm":
                assert argv[2:] == ["-f", helper]
                self.helper_exists = False
            else:
                raise AssertionError(argv)
            return runner.CommandResult(0)

        def _cleanup(self):
            self.cleaned = True
            self.evidence.cleanup = {"status": "passed"}

        def _collect_failure_diagnostics(self):
            pass

    return SkillGate()


def test_plan69_runs_actual_project_restore_hot_and_offline_functions(
    skill_gate, capsys: pytest.CaptureFixture[str],
) -> None:
    result = skill_gate.run()
    assert result["status"] == "passed" and skill_gate.cleaned
    assert skill_gate.events.count("hot-install") == 3
    assert skill_gate.events.count("restart") == 3
    assert skill_gate.events.index("offline-stop") < skill_gate.events.index("offline-create")
    assert skill_gate.events.index("offline-install") < skill_gate.events.index("offline-start")
    checks = result["checks"]
    assert checks["skills:initialized"]["writing_skills_ready"] is True
    assert all(checks["skills:initialized"]["current_skill_state"].values())
    assert checks["skills:all-off-hot-restart"]["state_preserved"] is True
    assert checks["skills:all-off-hot-restart"]["writing_skills_ready"] is False
    assert checks["skills:mixed-reinstall"]["current_skill_state"] == skill_gate.mixed_skill_state
    assert checks["skill-offline-install"]["host_still_stopped"] is True
    assert checks["skill-offline-install"]["restore_status"] == "pending_skill_restore"
    assert checks["skills:offline-restored-final"]["writing_skills_ready"] is True
    assert checks["other-skills:offline-restored-final"] == checks["other-skills:baseline"]
    snapshots = list(skill_gate.config.transcript.parent.glob("*-skill-state.json"))
    assert len(snapshots) == 6
    for path in snapshots:
        snapshot = json.loads(path.read_text())
        assert set(snapshot) == {"schema", "base_url", "agent_id", "skills"}
        assert snapshot["schema"] == "skill-enable-state/1"
        assert snapshot["base_url"] == f"http://{skill_gate.names.qwenpaw_container}:8088"
    assert ("container", skill_gate.skill_installer.INSTALLER_CONTAINER) in skill_gate._attempted
    assert skill_gate.helper_exists is False
    assert skill_gate.skill_installer.skill_configuration() is skill_gate.skill_configuration
    assert "private" not in capsys.readouterr().out
    assert "private log must not be printed" not in skill_gate.config.transcript.read_text()
    assert "private offline log must not be printed" not in skill_gate.config.transcript.read_text()
    assert not any("model" in path for _method, path, _agent, _body in skill_gate.http_calls)
    assert all(agent == "ai-novel-writer" for method, path, agent, _body in skill_gate.http_calls
               if method != "GET" and path.startswith("/api/skills"))


@pytest.mark.parametrize("fault", [
    "lost-restore", "restart-drift", "other-agent-drift", "offline-started-host", "uninstall-residue",
])
def test_plan69_failures_cannot_be_reported_as_pass_and_cleanup_runs(runner, skill_gate, fault):
    skill_gate.fault = fault
    with pytest.raises(runner.GateError):
        skill_gate.run()
    assert skill_gate.cleaned
    assert skill_gate.evidence.status == "failed"
    assert skill_gate.evidence.failure_code
    assert skill_gate.config.transcript.exists()


def test_plan69_requires_snapshot_location_without_external_io(runner, candidate, capsys):
    assert runner.main(["--candidate", str(candidate), "--skill-state-check"]) == 1
    assert "SKILL_GATE_REQUIRES_DURABLE_TRANSCRIPT" in capsys.readouterr().err


def test_plan69_dry_run_is_explicit_and_never_runs_installer(runner, skill_gate, capsys):
    assert runner.main([
        "--candidate", str(skill_gate.config.candidate), "--skill-state-check",
        "--run-id", skill_gate.config.run_id, "--transcript", str(skill_gate.config.transcript),
    ]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["skill_state_check"] is True
    assert plan["topology"]["published_ports"] == []
    assert plan["topology"]["offline_installer"]["network"] == "none"
    assert skill_gate.commands == [] and not skill_gate.config.transcript.exists()


@pytest.mark.parametrize("change", ["container", "volumes", "base_url"])
def test_skill_adapter_rejects_identity_drift_before_commands(runner, skill_gate, change):
    skill_gate._load_skill_adapters()
    installer = skill_gate.skill_installer
    if change == "container":
        installer.CONTAINER = "ai-novel-2026-qwenpaw-lab"
    elif change == "volumes":
        installer.VOLUMES = ("ai-novel-2026-qwenpaw-data:/app/working",)
    else:
        installer.BASE_URL = "http://127.0.0.1:18088"
    with pytest.raises(runner.GateError, match="SKILL_ADAPTER_IDENTITY_CHANGED"):
        installer.run("docker", "inspect", installer.CONTAINER, capture=True)
    assert skill_gate.commands == []


def test_skill_snapshot_never_overwrites_existing_evidence(runner, skill_gate):
    path = skill_gate.config.transcript.parent / f"{skill_gate.config.run_id}-initialized-skill-state.json"
    path.write_text("existing evidence", encoding="utf-8")
    with pytest.raises(runner.GateError):
        skill_gate.run()
    assert path.read_text() == "existing evidence"
    assert "hot-install" not in skill_gate.events


def test_skill_adapter_preserves_project_readback_after_lost_acknowledgement(skill_gate):
    skill_gate.fault = "ack-lost"
    assert skill_gate.run()["status"] == "passed"
    assert skill_gate.ack_lost
    assert skill_gate.events.count("hot-install") == 3


def test_skill_adapter_keeps_shared_project_configuration_untouched(skill_gate):
    from scripts import configure_qwenpaw_novel_agent as shared_configuration

    original_url = shared_configuration.BASE_URL
    original_request = shared_configuration.request_json
    assert skill_gate.run()["status"] == "passed"
    assert shared_configuration.BASE_URL == original_url
    assert shared_configuration.request_json is original_request
    assert skill_gate.skill_configuration is not shared_configuration
    assert skill_gate.skill_installer.skill_configuration() is skill_gate.skill_configuration


def test_skill_initialization_requires_public_agent_absence(runner, skill_gate):
    skill_gate.agents["ai-novel-writer"] = {}
    skill_gate.native["ai-novel-writer"] = False
    with pytest.raises(runner.GateError, match="SKILL_INITIAL_AGENT_PRECONDITION_FAILED"):
        skill_gate.run()
    assert not any(method == "POST" and path == "/api/agents"
                   for method, path, _agent, _body in skill_gate.http_calls)


@pytest.mark.parametrize("args", [
    ("docker", "exec", "ai-novel-2026-qwenpaw-lab", "true"),
    ("docker", "start", "ai-novel-2026-qwenpaw-lab"),
    ("docker", "compose", "up"),
])
def test_skill_installer_adapter_rejects_unscoped_vectors(runner, skill_gate, args):
    skill_gate._load_skill_adapters()
    with pytest.raises(runner.GateError, match="SKILL_INSTALL_COMMAND_OUT_OF_SCOPE"):
        skill_gate.skill_installer.run(*args)
    assert skill_gate.commands == []
