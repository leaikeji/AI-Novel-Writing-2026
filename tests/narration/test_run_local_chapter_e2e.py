from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import signal
import stat

import pytest

from scripts.tts import run_local_chapter_e2e as command


RUN_ID = "11111111-2222-4333-8444-555555555555"
NOVEL_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
DOCUMENT_ID = "01234567-89ab-4cde-8fab-0123456789ab"


def _token(tmp_path: Path) -> Path:
    tmp_path.chmod(0o700)
    path = tmp_path / "token"
    path.write_text("v" * 43, encoding="ascii")
    path.chmod(0o600)
    return path


def _argv(tmp_path: Path, mode: str = "prepare") -> list[str]:
    return [
        "--mode",
        mode,
        "--run-id",
        RUN_ID,
        "--novel-id",
        NOVEL_ID,
        "--document-id",
        DOCUMENT_ID,
        "--host-token-file",
        str(_token(tmp_path)),
        "--confirm",
        command.CONFIRMATIONS[mode],
    ]


def _config(tmp_path: Path, mode: str) -> command.RunConfig:
    return command._config_from_args(command.build_parser().parse_args(_argv(tmp_path, mode)))


def _bundle_manifest_for_fixture(fixture_relative_path: str) -> dict[str, object]:
    manifest = command.build_bundle_manifest()
    files = dict(manifest["files"])
    fresh_digest = files.pop(command.FRESH_FIXTURE_RELATIVE_PATH)
    assert fresh_digest == command.SUPPORTED_FIXTURE_SHA256[
        command.FRESH_FIXTURE_RELATIVE_PATH
    ]
    files[fixture_relative_path] = command.SUPPORTED_FIXTURE_SHA256[
        fixture_relative_path
    ]
    unsigned: dict[str, object] = {
        "schema_version": manifest["schema_version"],
        "files": files,
        "backend_tree_sha256": manifest["backend_tree_sha256"],
    }
    return {
        **unsigned,
        "bundle_sha256": hashlib.sha256(
            command._canonical_json_bytes(unsigned)
        ).hexdigest(),
    }


def _write_sealed_bundle_manifest(
    config: command.RunConfig,
    *,
    fixture_relative_path: str = command.FRESH_FIXTURE_RELATIVE_PATH,
    payload: dict[str, object] | None = None,
) -> Path:
    path = config.host_exchange_dir / "bundle-manifest.json"
    manifest = payload or _bundle_manifest_for_fixture(fixture_relative_path)
    path.write_bytes(command._canonical_json_bytes(manifest))
    path.chmod(0o600)
    return path


def test_parser_is_narrow_and_rejects_every_free_execution_surface(
    tmp_path: Path,
) -> None:
    parser = command.build_parser()
    actions = {action.dest for action in parser._actions if action.dest != "help"}
    assert actions == {
        "mode",
        "run_id",
        "novel_id",
        "document_id",
        "host_token_file",
        "confirm",
    }
    for option in (
        "--url",
        "--api-base",
        "--browser",
        "--selector",
        "--viewport",
        "--import",
        "--database-url",
        "--output-dir",
        "--private-work-dir",
        "--container",
    ):
        with pytest.raises(command.OrchestratorError, match="ARGUMENTS_INVALID"):
            parser.parse_args([*_argv(tmp_path), option, "injected"])


def test_local_validation_bundle_stages_listening_finalizer_exactly_once() -> None:
    assert "scripts/tts/chapter_e2e_listening.py" in command.BUNDLE_RELATIVE_PATHS
    assert len(command.BUNDLE_RELATIVE_PATHS) == len(set(command.BUNDLE_RELATIVE_PATHS))


def test_fresh_bundle_seals_only_pinned_v3_fixture() -> None:
    manifest = command.build_bundle_manifest()
    files = manifest["files"]
    assert type(files) is dict
    assert files[command.FRESH_FIXTURE_RELATIVE_PATH] == (
        command.SUPPORTED_FIXTURE_SHA256[command.FRESH_FIXTURE_RELATIVE_PATH]
    )
    assert command.LEGACY_FIXTURE_RELATIVE_PATH not in files
    assert command.FIXTURE_RELATIVE_PATH == command.FRESH_FIXTURE_RELATIVE_PATH


def test_config_requires_canonical_scope_external_private_token_and_mode_confirmation(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, "prepare")
    assert config.run_id == RUN_ID
    assert config.host_token_file.is_absolute()
    assert config.host_exchange_dir.parent.name == "t4k-runs"
    assert str(config.host_exchange_dir).startswith(str(tmp_path))

    bad = _argv(tmp_path)
    bad[-1] = "wrong"
    with pytest.raises(command.OrchestratorError, match="CONFIRMATION_REQUIRED"):
        command._config_from_args(command.build_parser().parse_args(bad))

    token = Path(bad[bad.index("--host-token-file") + 1])
    token.chmod(0o644)
    private_mode_argv = _argv(tmp_path)
    Path(private_mode_argv[private_mode_argv.index("--host-token-file") + 1]).chmod(
        0o644
    )
    with pytest.raises(command.OrchestratorError, match="TOKEN_PATH_INVALID"):
        command._config_from_args(
            command.build_parser().parse_args(private_mode_argv)
        )


class FakeProcess:
    def __init__(self, returncode: int = 3) -> None:
        self.returncode: int | None = None
        self.final_returncode = returncode
        self.signals: list[int] = []
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        self.returncode = self.final_returncode
        return self.final_returncode

    def send_signal(self, sig: int) -> None:
        self.signals.append(sig)
        self.returncode = 130

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 130

    def kill(self) -> None:
        self.killed = True
        self.returncode = 137


class FakeRunner:
    def __init__(self, config: command.RunConfig, *, interrupt_operator: bool = False) -> None:
        self.config = config
        self.interrupt_operator = interrupt_operator
        self.calls: list[tuple[str, ...]] = []
        self.status_files: list[Path] = []
        self.process = FakeProcess()

    def run(self, argv, *, timeout=None):  # type: ignore[no-untyped-def]
        del timeout
        call = tuple(str(item) for item in argv)
        self.calls.append(call)
        if call[:2] == ("docker", "inspect") and call[-1] == "{{json .Mounts}}":
            topology = command.EXPECTED_CONTAINER_TOPOLOGY[call[2]]
            rows = [
                {
                    "Destination": destination,
                    "Type": details[0],
                    "Name": details[1],
                    "RW": details[2],
                }
                for destination, details in topology["mounts"].items()
            ]
            return command.CommandResult(0, json.dumps(rows), "")
        if call[:2] == ("docker", "inspect") and call[-1] == "{{.Config.Image}}":
            return command.CommandResult(
                0,
                str(command.EXPECTED_CONTAINER_TOPOLOGY[call[2]]["image"]) + "\n",
                "",
            )
        if (
            call[:2] == ("docker", "inspect")
            and call[-1] == "{{json .NetworkSettings.Networks}}"
        ):
            networks = command.EXPECTED_CONTAINER_TOPOLOGY[call[2]]["networks"]
            return command.CommandResult(
                0,
                json.dumps({name: {} for name in networks}),
                "",
            )
        if call[:2] == ("docker", "inspect"):
            return command.CommandResult(0, "healthy\n", "")
        if call[:2] == ("docker", "cp"):
            destination = call[-1]
            if destination.endswith("probe-request.json") and not destination.startswith(
                f"{command.QWENPAW_CONTAINER}:"
            ):
                target = Path(destination)
                target.write_text("{}\n", encoding="utf-8")
            return command.CommandResult(0, "", "")
        if "chapter_e2e_readiness.py" in " ".join(call):
            return command.CommandResult(
                0,
                json.dumps(
                    {
                        "status": "HOLD",
                        "decision": "READY_FOR_OPERATOR_REVIEW",
                        "missing_codes": [],
                    }
                ),
                "",
            )
        if "chapter_e2e_operator_envelope.py" in " ".join(call):
            return command.CommandResult(0, '{"status":"ISSUED"}\n', "")
        if (
            "local_chapter_e2e_container.py" in " ".join(call)
            and "--mode" in call
        ):
            mode = call[call.index("--mode") + 1]
            code = {
                "verify-stage": "STAGE_VERIFIED",
                "prepare": "RUN_PREPARED",
                "import-report": "REPORT_IMPORTED",
                "cleanup": "TOOLS_CLEANED",
                "status": "HUMAN_LISTENING_PENDING",
                "require-partial-ready-capability": (
                    "PARTIAL_READY_LAUNCHER_VERIFIED"
                ),
                "arm-claim-gate": "CLAIM_GATE_ARMED",
                "release-claim-gate": "CLAIM_GATE_RELEASED",
                "stop-launcher": "LAUNCHER_STOPPED",
            }[mode]
            return command.CommandResult(
                0,
                json.dumps(
                    {
                        "status": "OK",
                        "code": code,
                        "secret_values_emitted": False,
                        "private_paths_emitted": False,
                    }
                ),
                "",
            )
        if call[:4] == (
            "docker",
            "exec",
            command.QWENPAW_CONTAINER,
            "test",
        ):
            return command.CommandResult(0, "", "")
        if call and call[0] == command.sys.executable and call[1].endswith(
            "run_local_operator_report.py"
        ):
            if self.interrupt_operator:
                raise KeyboardInterrupt
            collector = b'{"collector":true}\n'
            probe = b'{"probe":true}\n'
            marker = b'{"marker":true}\n'
            for name, data in zip(command.REPORT_FILENAMES, (collector, probe, marker)):
                path = self.config.host_exchange_dir / name
                path.write_bytes(data)
                path.chmod(0o600)
            return command.CommandResult(
                0,
                json.dumps(
                    {
                        "status": "LOCAL_OPERATOR_OBSERVATION_COMMITTED",
                        "collector_report_sha256": hashlib.sha256(collector).hexdigest(),
                        "probe_report_sha256": hashlib.sha256(probe).hexdigest(),
                        "secret_values_emitted": False,
                    }
                ),
                "",
            )
        return command.CommandResult(0, "", "")

    def popen(self, argv, *, status_file):  # type: ignore[no-untyped-def]
        self.calls.append(tuple(str(item) for item in argv))
        self.status_files.append(status_file)
        return self.process


def test_topology_preflight_is_read_only_and_uses_only_three_fixed_containers(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, "run")
    runner = FakeRunner(config)
    command.preflight_existing_topology(runner)
    flattened = [item for call in runner.calls for item in call]
    assert all(call[:2] == ("docker", "inspect") for call in runner.calls)
    assert set(command.FIXED_CONTAINERS).issubset(flattened)
    assert not ({"run", "create", "compose", "volume"} & set(flattened))
    assert ".Config.Env" not in flattened


@pytest.mark.parametrize(
    "field",
    ["mount_name", "mount_rw", "mount_duplicate", "image", "network"],
)
def test_topology_preflight_rejects_wrong_physical_identity(
    tmp_path: Path,
    field: str,
) -> None:
    config = _config(tmp_path, "run")
    runner = FakeRunner(config)
    original_run = runner.run

    def run(argv, *, timeout=None):  # type: ignore[no-untyped-def]
        result = original_run(argv, timeout=timeout)
        call = tuple(str(item) for item in argv)
        if call[:3] != ("docker", "inspect", command.QWENPAW_CONTAINER):
            return result
        if call[-1] == "{{json .Mounts}}" and field.startswith("mount_"):
            rows = json.loads(result.stdout)
            if field == "mount_name":
                rows[0]["Name"] = "foreign-volume"
            elif field == "mount_rw":
                rows[0]["RW"] = not rows[0]["RW"]
            else:
                rows.append(dict(rows[0]))
            return command.CommandResult(0, json.dumps(rows), "")
        if call[-1] == "{{.Config.Image}}" and field == "image":
            return command.CommandResult(0, "foreign:latest\n", "")
        if call[-1] == "{{json .NetworkSettings.Networks}}" and field == "network":
            return command.CommandResult(0, '{"foreign":{}}\n', "")
        return result

    runner.run = run  # type: ignore[method-assign]
    with pytest.raises(command.OrchestratorError, match="TOPOLOGY_HOLD"):
        command.preflight_existing_topology(runner)


def test_launcher_argv_is_fully_fixed_and_never_contains_host_secret_or_database_url(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, "run")
    argv = command._launcher_argv(
        config,
        resume=False,
        fixture_relative_path=command.FRESH_FIXTURE_RELATIVE_PATH,
    )
    pythonpath = next(item for item in argv if item.startswith("PYTHONPATH="))
    assert pythonpath == (
        f"PYTHONPATH={config.tool_root}:{command.INSTALLED_PLUGIN_ROOT}"
    )
    assert "--api-base" in argv
    assert argv[argv.index("--api-base") + 1] == command.CONTAINER_API_BASE
    assert "--duration-minutes" in argv
    assert argv[argv.index("--duration-minutes") + 1] == "30"
    assert str(config.host_token_file) not in argv
    assert "AI_NOVEL_DATABASE_URL" not in " ".join(argv)
    assert "postgresql" not in " ".join(argv)
    assert "--browser" not in argv
    assert "--selector" not in argv
    assert "--viewport" not in argv
    assert "--import" not in argv
    assert argv[argv.index("--fixture-manifest") + 1] == str(
        config.tool_root / command.FRESH_FIXTURE_RELATIVE_PATH
    )


def test_legacy_v2_sealed_manifest_drives_run_launcher_without_global_v3_switch(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, "run")
    command._ensure_host_exchange(config, new=True)
    _write_sealed_bundle_manifest(
        config,
        fixture_relative_path=command.LEGACY_FIXTURE_RELATIVE_PATH,
    )
    runner = FakeRunner(config)

    result = command.run_workflow(
        runner,
        config,
        monotonic=lambda: 0.0,
        sleeper=lambda _seconds: None,
    )

    assert result.code == "HUMAN_LISTENING_PENDING"
    launcher = next(
        call
        for call in runner.calls
        if "run_chapter_e2e_real.py" in " ".join(call)
    )
    assert launcher[launcher.index("--fixture-manifest") + 1] == str(
        config.tool_root / command.LEGACY_FIXTURE_RELATIVE_PATH
    )


@pytest.mark.parametrize(
    "variant",
    [
        "missing",
        "ambiguous",
        "unsupported",
        "traversal",
        "fixture_digest",
        "bundle_digest",
        "invalid_json",
        "duplicate_key",
    ],
)
@pytest.mark.parametrize("mode", ["run", "resume"])
def test_run_and_resume_reject_invalid_or_unbound_sealed_fixture_manifest_before_launcher(
    tmp_path: Path,
    variant: str,
    mode: str,
) -> None:
    config = _config(tmp_path, mode)
    command._ensure_host_exchange(config, new=True)
    manifest = _bundle_manifest_for_fixture(
        command.FRESH_FIXTURE_RELATIVE_PATH
    )
    files = dict(manifest["files"])
    files.pop(command.FRESH_FIXTURE_RELATIVE_PATH)
    if variant == "ambiguous":
        files.update(command.SUPPORTED_FIXTURE_SHA256)
    elif variant == "unsupported":
        files["tests/fixtures/narration/chapter-e2e-v4.json"] = "1" * 64
    elif variant == "traversal":
        files["../chapter-e2e-v3.json"] = command.SUPPORTED_FIXTURE_SHA256[
            command.FRESH_FIXTURE_RELATIVE_PATH
        ]
    elif variant in {"fixture_digest", "bundle_digest"}:
        files[command.FRESH_FIXTURE_RELATIVE_PATH] = (
            "0" * 64
            if variant == "fixture_digest"
            else command.SUPPORTED_FIXTURE_SHA256[
                command.FRESH_FIXTURE_RELATIVE_PATH
            ]
        )
    unsigned: dict[str, object] = {
        "schema_version": manifest["schema_version"],
        "files": files,
        "backend_tree_sha256": manifest["backend_tree_sha256"],
    }
    candidate = {
        **unsigned,
        "bundle_sha256": hashlib.sha256(
            command._canonical_json_bytes(unsigned)
        ).hexdigest(),
    }
    if variant == "bundle_digest":
        candidate["bundle_sha256"] = "f" * 64
    path = config.host_exchange_dir / "bundle-manifest.json"
    if variant == "invalid_json":
        path.write_bytes(b"{not-json\n")
        path.chmod(0o600)
    elif variant == "duplicate_key":
        path.write_bytes(
            b'{"schema_version":"x","schema_version":"x"}\n'
        )
        path.chmod(0o600)
    else:
        _write_sealed_bundle_manifest(config, payload=candidate)
    runner = FakeRunner(config)

    with pytest.raises(
        command.OrchestratorError,
        match="LOCAL_ORCHESTRATOR_FIXTURE_MANIFEST_HOLD",
    ):
        if mode == "run":
            command.run_workflow(runner, config)
        else:
            command.resume_workflow(runner, config)

    assert all("run_chapter_e2e_real.py" not in call for call in runner.calls)


def test_prepare_uses_fixed_preflight_stage_verify_prepare_readiness_order(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, "prepare")
    runner = FakeRunner(config)

    result = command.prepare_workflow(runner, config)

    assert result.code == "READY_FOR_OPERATOR_REVIEW"
    rendered = [" ".join(call) for call in runner.calls]
    last_inspect = max(
        index
        for index, call in enumerate(runner.calls)
        if call[:2] == ("docker", "inspect")
    )
    first_stage = next(
        index
        for index, call in enumerate(runner.calls)
        if call[:3] == ("docker", "exec", command.QWENPAW_CONTAINER)
        and "mkdir" in call
    )
    directory_commands = [
        call
        for call in runner.calls
        if call[:3] == ("docker", "exec", command.QWENPAW_CONTAINER)
        and "mkdir" in call
    ]
    rendered_directories = {call[-1] for call in directory_commands}
    assert str(config.tool_root / "scripts") in rendered_directories
    assert str(config.tool_root / "scripts/tts") in rendered_directories
    assert str(config.tool_root / "tests") in rendered_directories
    assert str(config.tool_root / "tests/fixtures") in rendered_directories
    assert str(config.tool_root / "tests/fixtures/narration") in rendered_directories
    nested_directory_commands = [
        call
        for call in directory_commands
        if call[-1].startswith(f"{config.tool_root}/")
    ]
    assert all("-p" not in call for call in nested_directory_commands)
    staged_chowns = [
        call
        for call in runner.calls
        if call[:5]
        == (
            "docker",
            "exec",
            command.QWENPAW_CONTAINER,
            "chown",
            "--no-dereference",
        )
    ]
    assert len(staged_chowns) == len(command.BUNDLE_RELATIVE_PATHS) + 1
    assert all(call[5] == "0:0" for call in staged_chowns)
    helper_modes = [
        (index, call[call.index("--mode") + 1])
        for index, call in enumerate(runner.calls)
        if "--mode" in call
        and any(item.endswith("local_chapter_e2e_container.py") for item in call)
    ]
    verify = next(index for index, mode in helper_modes if mode == "verify-stage")
    prepare = next(index for index, mode in helper_modes if mode == "prepare")
    readiness = next(
        index
        for index, call in enumerate(runner.calls)
        if "-B" in call
        and any(item.endswith("chapter_e2e_readiness.py") for item in call)
    )
    assert last_inspect < first_stage < verify < prepare < readiness
    assert all(
        "docker run" not in row and "docker create" not in row
        for row in rendered
    )


def test_run_coordinates_probe_operator_and_commit_without_cleanup(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, "run")
    command._ensure_host_exchange(config, new=True)
    _write_sealed_bundle_manifest(config)
    runner = FakeRunner(config)
    result = command.run_workflow(
        runner,
        config,
        monotonic=lambda: 0.0,
        sleeper=lambda _seconds: None,
    )
    assert result.code == "HUMAN_LISTENING_PENDING"
    assert result.report_sha256 is not None
    rendered = "\n".join(" ".join(call) for call in runner.calls)
    assert "run_local_operator_report.py" in rendered
    assert "import-report" in rendered
    assert "arm-claim-gate" in rendered
    assert "release-claim-gate" in rendered
    assert sum("release-claim-gate" in call for call in runner.calls) == 1
    assert rendered.index("arm-claim-gate") < rendered.index(
        "run_chapter_e2e_real.py"
    )
    assert rendered.index("import-report") < rendered.index(
        "release-claim-gate"
    )
    assert " cleanup " not in f" {rendered} "
    assert "docker run" not in rendered
    assert "docker create" not in rendered


def test_report_copy_sets_root_owner_and_private_mode_before_import(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, "run")
    runner = FakeRunner(config)

    command._copy_report_to_container(runner, config)

    expected: list[tuple[str, ...]] = []
    for filename in command.REPORT_FILENAMES:
        source = config.host_exchange_dir / filename
        target = config.incoming_dir / filename
        expected.extend(
            [
                (
                    "docker",
                    "cp",
                    str(source),
                    f"{command.QWENPAW_CONTAINER}:{target}",
                ),
                (
                    "docker",
                    "exec",
                    command.QWENPAW_CONTAINER,
                    "chown",
                    "--no-dereference",
                    "0:0",
                    str(target),
                ),
                (
                    "docker",
                    "exec",
                    command.QWENPAW_CONTAINER,
                    "chmod",
                    "0600",
                    str(target),
                ),
            ]
        )

    assert runner.calls[: len(expected)] == expected
    assert len(runner.calls) == len(expected) + 1
    import_call = runner.calls[-1]
    assert "--mode" in import_call
    assert import_call[import_call.index("--mode") + 1] == "import-report"


@pytest.mark.parametrize("failed_permission_step", ["chown", "chmod"])
@pytest.mark.parametrize("failed_report_index", range(len(command.REPORT_FILENAMES)))
def test_report_copy_permission_failure_never_imports(
    tmp_path: Path,
    failed_permission_step: str,
    failed_report_index: int,
) -> None:
    config = _config(tmp_path, "run")
    runner = FakeRunner(config)
    original_run = runner.run
    failed_target = str(
        config.incoming_dir / command.REPORT_FILENAMES[failed_report_index]
    )

    def run(argv, *, timeout=None):  # type: ignore[no-untyped-def]
        call = tuple(str(item) for item in argv)
        if (
            call[:3] == ("docker", "exec", command.QWENPAW_CONTAINER)
            and call[3] == failed_permission_step
            and call[-1] == failed_target
        ):
            runner.calls.append(call)
            return command.CommandResult(1, "", "permission transition failed")
        return original_run(argv, timeout=timeout)

    runner.run = run  # type: ignore[method-assign]

    with pytest.raises(
        command.OrchestratorError,
        match="LOCAL_ORCHESTRATOR_REPORT_IMPORT_HOLD",
    ):
        command._copy_report_to_container(runner, config)

    assert all(
        not (
            "--mode" in call
            and call[call.index("--mode") + 1] == "import-report"
        )
        for call in runner.calls
    )
    assert sum(call[:2] == ("docker", "cp") for call in runner.calls) == (
        failed_report_index + 1
    )


def test_run_fails_closed_before_arm_when_launcher_lacks_partial_ready_contract(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, "run")
    command._ensure_host_exchange(config, new=True)
    _write_sealed_bundle_manifest(config)
    runner = FakeRunner(config)
    original_run = runner.run

    def run(argv, *, timeout=None):  # type: ignore[no-untyped-def]
        call = tuple(str(item) for item in argv)
        if "--mode" in call and (
            call[call.index("--mode") + 1]
            == "require-partial-ready-capability"
        ):
            runner.calls.append(call)
            return command.CommandResult(2, "", '{"status":"HOLD"}\n')
        return original_run(argv, timeout=timeout)

    runner.run = run  # type: ignore[method-assign]
    with pytest.raises(
        command.OrchestratorError,
        match="PARTIAL_READY_LAUNCHER_REQUIRED",
    ):
        command.run_workflow(runner, config)
    assert all("arm-claim-gate" not in call for call in runner.calls)
    assert all("run_chapter_e2e_real.py" not in call for call in runner.calls)


def test_interrupt_preserves_tool_and_recovery_for_resume(tmp_path: Path) -> None:
    config = _config(tmp_path, "run")
    command._ensure_host_exchange(config, new=True)
    _write_sealed_bundle_manifest(config)
    runner = FakeRunner(config, interrupt_operator=True)
    with pytest.raises(KeyboardInterrupt):
        command.run_workflow(
            runner,
            config,
            monotonic=lambda: 0.0,
            sleeper=lambda _seconds: None,
        )
    assert runner.process.signals == [signal.SIGINT]
    assert not runner.process.terminated
    assert all("cleanup" not in call for call in runner.calls)
    assert any("release-claim-gate" in call for call in runner.calls)


def test_stop_escalates_and_reaps_before_returning() -> None:
    class StubbornProcess(FakeProcess):
        def wait(self, timeout: float | None = None) -> int:
            del timeout
            if not self.killed:
                raise command.subprocess.TimeoutExpired("launcher", 1)
            self.returncode = 137
            return 137

        def send_signal(self, sig: int) -> None:
            self.signals.append(sig)

        def terminate(self) -> None:
            self.terminated = True

    process = StubbornProcess()
    command._stop_process(process)
    assert process.signals == [signal.SIGINT]
    assert process.terminated is True
    assert process.killed is True
    assert process.poll() == 137


def test_primary_error_is_not_replaced_by_release_failure(tmp_path: Path) -> None:
    config = _config(tmp_path, "run")
    command._ensure_host_exchange(config, new=True)
    _write_sealed_bundle_manifest(config)
    runner = FakeRunner(config, interrupt_operator=True)
    original_run = runner.run

    def run(argv, *, timeout=None):  # type: ignore[no-untyped-def]
        call = tuple(str(item) for item in argv)
        if "release-claim-gate" in call:
            assert runner.process.poll() is not None
            runner.calls.append(call)
            return command.CommandResult(2, "", "")
        return original_run(argv, timeout=timeout)

    runner.run = run  # type: ignore[method-assign]
    with pytest.raises(KeyboardInterrupt):
        command.run_workflow(runner, config)
    assert runner.process.poll() is not None


def test_stop_helper_failure_still_reaps_local_wrapper(tmp_path: Path) -> None:
    config = _config(tmp_path, "run")
    command._ensure_host_exchange(config, new=True)
    _write_sealed_bundle_manifest(config)
    runner = FakeRunner(config, interrupt_operator=True)
    original_run = runner.run

    def run(argv, *, timeout=None):  # type: ignore[no-untyped-def]
        call = tuple(str(item) for item in argv)
        if "stop-launcher" in call:
            runner.calls.append(call)
            return command.CommandResult(2, "", "")
        return original_run(argv, timeout=timeout)

    runner.run = run  # type: ignore[method-assign]

    with pytest.raises(KeyboardInterrupt):
        command.run_workflow(runner, config)

    assert runner.process.signals == [signal.SIGINT]
    assert runner.process.poll() is not None


def test_stop_helper_timeout_has_stable_redacted_code(tmp_path: Path) -> None:
    config = _config(tmp_path, "run")

    class TimeoutRunner(FakeRunner):
        def run(self, argv, *, timeout=None):  # type: ignore[no-untyped-def]
            call = tuple(str(item) for item in argv)
            if "stop-launcher" in call:
                assert timeout == 120
                raise command.subprocess.TimeoutExpired("helper", timeout)
            return super().run(argv, timeout=timeout)

    runner = TimeoutRunner(config)
    with pytest.raises(command.OrchestratorError) as captured:
        command._run_helper(runner, config, "stop-launcher")

    assert captured.value.code == "LOCAL_ORCHESTRATOR_STOP_LAUNCHER_HOLD"


def test_real_popen_uses_private_file_instead_of_pipes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def popen(argv, **kwargs):  # type: ignore[no-untyped-def]
        observed.update(kwargs)
        return FakeProcess()

    monkeypatch.setattr(command.subprocess, "Popen", popen)
    status_file = tmp_path / "launcher-status.log"
    command.SubprocessCommandRunner().popen(
        ("fixed", "argv"),
        status_file=status_file,
    )
    assert observed["shell"] is False
    assert observed["stdin"] is command.subprocess.DEVNULL
    assert type(observed["stdout"]) is int
    assert observed["stderr"] == observed["stdout"]
    assert stat.S_IMODE(status_file.stat().st_mode) == 0o600


def test_launcher_failure_code_returns_only_bounded_stable_code(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, "run")
    command._ensure_host_exchange(config, new=True)
    config.launcher_status_file.write_text(
        "untrusted detail\nPARTIAL_READY_HOST_GATE_INVALID\n",
        encoding="ascii",
    )
    config.launcher_status_file.chmod(0o600)
    assert command._launcher_failure_code(
        config,
        fallback="LOCAL_ORCHESTRATOR_LAUNCHER_HOLD",
    ) == "PARTIAL_READY_HOST_GATE_INVALID"
    config.launcher_status_file.write_text(
        '{"code":"T4_VALIDATION_OVERVIEW_T4_FAILED","status":"FAILED"}\n',
        encoding="ascii",
    )
    config.launcher_status_file.chmod(0o600)
    assert command._launcher_failure_code(
        config,
        fallback="LOCAL_ORCHESTRATOR_LAUNCHER_HOLD",
    ) == "T4_VALIDATION_OVERVIEW_T4_FAILED"


def test_local_operator_failure_preserves_only_its_stable_redacted_code(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, "run")
    command._ensure_host_exchange(config, new=True)

    class FailingOperatorRunner:
        def run(self, argv, *, timeout=None):  # type: ignore[no-untyped-def]
            del argv, timeout
            return command.CommandResult(
                2,
                "",
                json.dumps(
                    {
                        "schema_version": "moss-tts-t4k-local-operator-cli/1.0",
                        "status": "HOLD",
                        "code": "CONTROLLER_LIFECYCLE_RUNTIME_HOLD",
                        "secret_values_emitted": False,
                        "private_paths_emitted": False,
                    }
                ),
            )

    with pytest.raises(
        command.OrchestratorError,
        match="CONTROLLER_LIFECYCLE_RUNTIME_HOLD",
    ):
        command._run_local_operator(  # noqa: SLF001
            FailingOperatorRunner(),  # type: ignore[arg-type]
            config,
            config.host_exchange_dir / "probe-request.json",
        )


def test_fresh_stage_verify_retries_only_the_read_only_helper_once(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, "prepare")
    runner = FakeRunner(config)
    original_run = runner.run
    verify_calls: list[tuple[str, ...]] = []

    def run(argv, *, timeout=None):  # type: ignore[no-untyped-def]
        call = tuple(str(item) for item in argv)
        if "local_chapter_e2e_container.py" in " ".join(call) and "--mode" in call:
            mode = call[call.index("--mode") + 1]
            if mode == "verify-stage":
                verify_calls.append(call)
                if len(verify_calls) == 1:
                    return command.CommandResult(2, "", "")
        return original_run(argv, timeout=timeout)

    runner.run = run  # type: ignore[method-assign]
    sleeps: list[float] = []

    command._verify_fresh_stage_with_retry(  # noqa: SLF001
        runner,
        config,
        sleeper=sleeps.append,
    )

    assert len(verify_calls) == 2
    assert verify_calls[0] == verify_calls[1]
    assert sleeps == [0.5]
    between = runner.calls[
        runner.calls.index(verify_calls[0]) + 1 : runner.calls.index(verify_calls[1])
    ]
    assert between == []


def test_fresh_stage_verify_second_failure_remains_hold(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, "prepare")
    runner = FakeRunner(config)
    original_run = runner.run
    verify_count = 0

    def run(argv, *, timeout=None):  # type: ignore[no-untyped-def]
        nonlocal verify_count
        call = tuple(str(item) for item in argv)
        if "local_chapter_e2e_container.py" in " ".join(call) and "--mode" in call:
            mode = call[call.index("--mode") + 1]
            if mode == "verify-stage":
                verify_count += 1
                return command.CommandResult(2, "", "")
        return original_run(argv, timeout=timeout)

    runner.run = run  # type: ignore[method-assign]

    with pytest.raises(
        command.OrchestratorError,
        match="LOCAL_ORCHESTRATOR_VERIFY_STAGE_HOLD",
    ):
        command._verify_fresh_stage_with_retry(  # noqa: SLF001
            runner,
            config,
            sleeper=lambda _seconds: None,
        )

    assert verify_count == 2


def test_resume_uses_same_run_and_fixed_listening_path_without_browser_rerun(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, "resume")
    command._ensure_host_exchange(config, new=True)
    _write_sealed_bundle_manifest(
        config,
        fixture_relative_path=command.LEGACY_FIXTURE_RELATIVE_PATH,
    )
    runner = FakeRunner(config)
    runner.process.final_returncode = 0
    original_run = runner.run

    def run(argv, *, timeout=None):  # type: ignore[no-untyped-def]
        call = tuple(str(item) for item in argv)
        if "local_chapter_e2e_container.py" in " ".join(call) and "status" in call:
            return command.CommandResult(
                0,
                json.dumps(
                    {
                        "status": "OK",
                        "code": "PASS_CANDIDATE",
                        "secret_values_emitted": False,
                    }
                ),
                "",
            )
        return original_run(argv, timeout=timeout)

    runner.run = run  # type: ignore[method-assign]
    result = command.resume_workflow(runner, config)
    assert result.code == "PASS_CANDIDATE"
    launcher = next(call for call in runner.calls if "run_chapter_e2e_real.py" in " ".join(call))
    assert "--resume" in launcher
    assert str(config.listening_dir / "listening.json") in launcher
    assert launcher[launcher.index("--fixture-manifest") + 1] == str(
        config.tool_root / command.LEGACY_FIXTURE_RELATIVE_PATH
    )
    assert all("run_local_operator_report.py" not in call for call in runner.calls)


def test_resume_reports_explicit_human_listening_failure_as_quality_hold(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, "resume")
    command._ensure_host_exchange(config, new=True)
    _write_sealed_bundle_manifest(config)
    runner = FakeRunner(config)
    runner.process.final_returncode = 2
    config.launcher_resume_status_file.write_text(
        json.dumps(
            {
                "status": "FAILED",
                "code": "FAILED",
            }
        )
        + "\n",
        encoding="ascii",
    )
    config.launcher_resume_status_file.chmod(0o600)
    original_run = runner.run

    def run(argv, *, timeout=None):  # type: ignore[no-untyped-def]
        call = tuple(str(item) for item in argv)
        if "local_chapter_e2e_container.py" in " ".join(call) and "status" in call:
            return command.CommandResult(
                0,
                json.dumps(
                    {
                        "status": "OK",
                        "code": "HUMAN_LISTENING_FAILED",
                        "secret_values_emitted": False,
                    }
                ),
                "",
            )
        return original_run(argv, timeout=timeout)

    runner.run = run  # type: ignore[method-assign]

    result = command.resume_workflow(runner, config)

    assert result == command.WorkflowResult(
        status="HOLD",
        code="HUMAN_LISTENING_FAILED",
    )
    launcher = next(
        call for call in runner.calls if "run_chapter_e2e_real.py" in " ".join(call)
    )
    assert "--resume" in launcher
    assert all("run_local_operator_report.py" not in call for call in runner.calls)


def test_recovery_only_resume_accepts_bounded_launcher_baseline_proof(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, "resume")
    command._ensure_host_exchange(config, new=True)
    _write_sealed_bundle_manifest(config)
    runner = FakeRunner(config)
    runner.process.final_returncode = 0
    config.launcher_resume_status_file.write_text(
        json.dumps(
            {
                "schema_version": "moss-tts-chapter-e2e-result/2.3",
                "status": "BASELINE_RESTORED",
                "code": "BASELINE_RESTORED",
            }
        )
        + "\n",
        encoding="ascii",
    )
    config.launcher_resume_status_file.chmod(0o600)

    result = command.resume_workflow(runner, config)

    assert result == command.WorkflowResult(
        status="OK",
        code="BASELINE_RESTORED",
    )
    assert all(
        not (
            "local_chapter_e2e_container.py" in " ".join(call)
            and "status" in call
        )
        for call in runner.calls
    )


@pytest.mark.parametrize(
    "terminal_code",
    ["PASS_CANDIDATE", "TECHNICAL_PASS_CANDIDATE"],
)
def test_resume_accepts_bounded_launcher_final_pass_proof(
    tmp_path: Path,
    terminal_code: str,
) -> None:
    config = _config(tmp_path, "resume")
    command._ensure_host_exchange(config, new=True)
    _write_sealed_bundle_manifest(config)
    runner = FakeRunner(config)
    runner.process.final_returncode = 0
    config.launcher_resume_status_file.write_text(
        json.dumps(
            {
                "schema_version": "moss-tts-chapter-e2e-result/2.3",
                "status": terminal_code,
                "code": terminal_code,
            }
        )
        + "\n",
        encoding="ascii",
    )
    config.launcher_resume_status_file.chmod(0o600)

    result = command.resume_workflow(runner, config)

    assert result == command.WorkflowResult(status="OK", code=terminal_code)


def test_cleanup_does_not_reverify_current_backend_before_bound_helper_cleanup(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, "cleanup")
    command._ensure_host_exchange(config, new=True)
    runner = FakeRunner(config)
    result = command.cleanup_workflow(runner, config)
    assert result.code == "TOOLS_CLEANED"
    helper_modes = [
        call[call.index("--mode") + 1]
        for call in runner.calls
        if "--mode" in call
        and any(item.endswith("local_chapter_e2e_container.py") for item in call)
    ]
    assert helper_modes == ["cleanup"]


def test_redacted_console_result_never_contains_scope_token_or_paths(tmp_path: Path) -> None:
    config = _config(tmp_path, "prepare")
    stream = io.StringIO()
    command._write_result(
        stream,
        command.WorkflowResult("HOLD", "READY_FOR_OPERATOR_REVIEW", "a" * 64),
    )
    rendered = stream.getvalue()
    assert RUN_ID not in rendered
    assert NOVEL_ID not in rendered
    assert DOCUMENT_ID not in rendered
    assert str(config.host_token_file) not in rendered
    assert json.loads(rendered)["secret_values_emitted"] is False
