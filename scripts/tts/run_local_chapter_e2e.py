#!/usr/bin/env python3
"""Repository-host orchestrator for one local, recoverable T4-K run.

The command coordinates only the three existing project containers.  It does
not create a container, database, service or mount, and it does not expose a
URL, browser, selector, viewport, import, database URL, container name, output
directory or private container path as caller input.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import stat
import subprocess
import sys
import time
from typing import Callable, Final, Mapping, Protocol, Sequence
from uuid import UUID


REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA_VERSION: Final = "moss-tts-t4k-local-orchestrator/1.0"
BUNDLE_SCHEMA_VERSION: Final = "moss-tts-t4k-tool-bundle/1.0"
QWENPAW_CONTAINER: Final = "ai-novel-2026-qwenpaw-lab"
POSTGRES_CONTAINER: Final = "ai-novel-2026-postgres"
SIDECAR_CONTAINER: Final = "ai-novel-2026-moss-tts-sidecar"
FIXED_CONTAINERS: Final = (
    QWENPAW_CONTAINER,
    POSTGRES_CONTAINER,
    SIDECAR_CONTAINER,
)
EXPECTED_CONTAINER_TOPOLOGY: Final = {
    QWENPAW_CONTAINER: {
        "image": "ai-novel-2026-qwenpaw-runtime:2.1.0-mvp0",
        "networks": frozenset(
            {"ai-novel-world-2026_default", "ai-novel-2026-tts-private"}
        ),
        "mounts": {
            "/app/working": ("volume", "ai-novel-2026-qwenpaw-data", True),
            "/app/working.secret": (
                "volume",
                "ai-novel-2026-qwenpaw-secrets",
                True,
            ),
            "/app/working.backups": (
                "volume",
                "ai-novel-2026-qwenpaw-backups",
                True,
            ),
            "/app/working/ai-novel-world-2026/novel-media": (
                "volume",
                "ai-novel-2026-novel-media",
                True,
            ),
            "/run/moss-tts-secrets": (
                "volume",
                "ai-novel-2026-moss-tts-secrets",
                False,
            ),
        },
    },
    POSTGRES_CONTAINER: {
        "image": (
            "pgvector/pgvector:0.8.6-pg18@sha256:"
            "2ba9ca5f2e7daa0f0e7723cba1ee9167bab54efd3640516a44ac1a928dd67e7a"
        ),
        "networks": frozenset({"ai-novel-world-2026_default"}),
        "mounts": {
            "/var/lib/postgresql": (
                "volume",
                "ai-novel-2026-postgres-data",
                True,
            )
        },
    },
    SIDECAR_CONTAINER: {
        "image": "ai-novel-world/moss-tts-sidecar:t1-b-linux-arm64",
        "networks": frozenset({"ai-novel-2026-tts-private"}),
        "mounts": {
            "/opt/moss-assets": (
                "volume",
                "ai-novel-2026-moss-models",
                False,
            ),
            "/run/moss-tts-secrets": (
                "volume",
                "ai-novel-2026-moss-tts-secrets",
                False,
            ),
        },
    },
}
EXPECTED_QWENPAW_MOUNTS: Final = frozenset(
    EXPECTED_CONTAINER_TOPOLOGY[QWENPAW_CONTAINER]["mounts"]
)
SECRET_PROJECT_ROOT: Final = Path(
    "/app/working.secret/ai-novel-world-2026"
)
CONTAINER_RUNS_ROOT: Final = SECRET_PROJECT_ROOT / "t4k-runs"
INSTALLED_PLUGIN_ROOT: Final = Path(
    "/app/working/plugins/ai-novel-world-2026"
)
CONTAINER_PYTHON: Final = "/app/venv/bin/python"
CONTAINER_API_BASE: Final = (
    "http://127.0.0.1:8088/api/ai-novel-world-2026"
)
FRESH_FIXTURE_RELATIVE_PATH: Final = (
    "tests/fixtures/narration/chapter-e2e-v3.json"
)
LEGACY_FIXTURE_RELATIVE_PATH: Final = (
    "tests/fixtures/narration/chapter-e2e-v2.json"
)
# Fresh runs always seal v3.  The legacy v2 identity remains an explicit,
# read-only compatibility entry so an already prepared run can be resumed
# from its own sealed bundle instead of silently switching fixtures.
FIXTURE_RELATIVE_PATH: Final = FRESH_FIXTURE_RELATIVE_PATH
SUPPORTED_FIXTURE_SHA256: Final = {
    FRESH_FIXTURE_RELATIVE_PATH: (
        "3cfb094c3a3374eb233ccff5c08963adaba5cac55e5ec056ff5257d32e421913"
    ),
    LEGACY_FIXTURE_RELATIVE_PATH: (
        "e970e4f837d2f96b2675e8922e43bb5dfcffc352e86f0f96b84e34db1065380b"
    ),
}
AUTOMATIC_CASE_ID: Final = "chapter-auto-zero-blockers"
MANUAL_CASE_ID: Final = "chapter-real-blocker"
DURATION_MINUTES: Final = "30"
CONTAINER_TOKEN_FILE: Final = (
    "/app/working.secret/ai-novel-world-2026/t4k-validation/token"
)
REPORT_FILENAMES: Final = (
    "collector-report.json",
    "probe-report.json",
    "collector-report.commit.json",
)
BUNDLE_RELATIVE_PATHS: Final = (
    "scripts/tts/chapter_e2e_collector.py",
    "scripts/tts/chapter_e2e_controller_trust.py",
    "scripts/tts/chapter_e2e_executor.py",
    "scripts/tts/chapter_e2e_listening.py",
    "scripts/tts/chapter_e2e_metric_chain.py",
    "scripts/tts/chapter_e2e_operator_envelope.py",
    "scripts/tts/chapter_e2e_probe_request.py",
    "scripts/tts/chapter_e2e_probes.py",
    "scripts/tts/chapter_e2e_readiness.py",
    "scripts/tts/chapter_e2e_runtime_audit.py",
    "scripts/tts/local_chapter_e2e_container.py",
    "scripts/tts/run_chapter_e2e_real.py",
    "scripts/tts/validate_chapter_e2e.py",
    FIXTURE_RELATIVE_PATH,
)
CONFIRMATIONS: Final = {
    "prepare": "PREPARE-T4K-LOCAL-RUN",
    "run": "AUTHOR-REVIEWED-T4-K-READINESS",
    "resume": "RESUME-T4K-LOCAL-RUN",
    "cleanup": "CLEANUP-T4K-LOCAL-TOOLS",
}
HELPER_CONFIRMATIONS: Final = {
    "verify-stage": "VERIFY-T4K-LOCAL-STAGE",
    "prepare": "PREPARE-T4K-LOCAL-RUN",
    "import-report": "IMPORT-T4K-LOCAL-REPORT",
    "status": "STATUS-T4K-LOCAL-RUN",
    "cleanup": "CLEANUP-T4K-LOCAL-TOOLS",
    "arm-claim-gate": "ARM-T4K-SEGMENT-CLAIM-GATE",
    "release-claim-gate": "RELEASE-T4K-SEGMENT-CLAIM-GATE",
    "stop-launcher": "STOP-T4K-LOCAL-LAUNCHER",
    "require-partial-ready-capability": (
        "REQUIRE-T4K-PARTIAL-READY-CAPABILITY"
    ),
}
LOCAL_OPERATOR_CONFIRMATION: Final = "AUTHOR-OPERATOR-LOCAL-EVIDENCE"
ENVELOPE_CONFIRMATION: Final = "AUTHOR-REVIEWED-T4-K-READINESS"
_SHA256: Final = re.compile(r"^[0-9a-f]{64}$")
_STABLE_CODE: Final = re.compile(r"^[A-Z][A-Z0-9_]{0,95}$")
_PROBE_WAIT_SECONDS: Final = 30 * 60
_MAX_LAUNCHER_STATUS_BYTES: Final = 64 * 1024
_MAX_BUNDLE_MANIFEST_BYTES: Final = 1024 * 1024


class OrchestratorError(RuntimeError):
    """Stable redacted host-boundary failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # pragma: no cover - argparse text
        del message
        raise OrchestratorError("LOCAL_ORCHESTRATOR_ARGUMENTS_INVALID")


@dataclass(frozen=True, slots=True)
class RunConfig:
    mode: str
    run_id: str
    novel_id: str
    document_id: str
    host_token_file: Path

    @property
    def container_root(self) -> Path:
        return CONTAINER_RUNS_ROOT / self.run_id

    @property
    def tool_root(self) -> Path:
        return self.container_root / "tool"

    @property
    def recovery_dir(self) -> Path:
        return self.container_root / "recovery"

    @property
    def result_dir(self) -> Path:
        return self.container_root / "result"

    @property
    def listening_dir(self) -> Path:
        return self.container_root / "listening"

    @property
    def incoming_dir(self) -> Path:
        return self.container_root / "incoming"

    @property
    def host_exchange_dir(self) -> Path:
        fingerprint = hashlib.sha256(self.run_id.encode("ascii")).hexdigest()
        return self.host_token_file.parent / "t4k-runs" / fingerprint

    @property
    def launcher_status_file(self) -> Path:
        return self.host_exchange_dir / "launcher-status.log"

    @property
    def launcher_resume_status_file(self) -> Path:
        return self.host_exchange_dir / "launcher-resume-status.log"


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True, slots=True)
class WorkflowResult:
    status: str
    code: str
    report_sha256: str | None = None


class RunningProcess(Protocol):
    returncode: int | None

    def poll(self) -> int | None: ...

    def wait(self, timeout: float | None = None) -> int: ...

    def send_signal(self, sig: int) -> None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


class CommandRunner(Protocol):
    def run(
        self,
        argv: Sequence[str],
        *,
        timeout: float | None = None,
    ) -> CommandResult: ...

    def popen(
        self,
        argv: Sequence[str],
        *,
        status_file: Path,
    ) -> RunningProcess: ...


class SubprocessCommandRunner:
    def run(
        self,
        argv: Sequence[str],
        *,
        timeout: float | None = None,
    ) -> CommandResult:
        completed = subprocess.run(
            list(argv),
            shell=False,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return CommandResult(
            completed.returncode,
            completed.stdout,
            completed.stderr,
        )

    def popen(
        self,
        argv: Sequence[str],
        *,
        status_file: Path,
    ) -> RunningProcess:
        descriptor: int | None = None
        try:
            descriptor = os.open(
                status_file,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            process = subprocess.Popen(  # type: ignore[return-value]
                list(argv),
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=descriptor,
                stderr=descriptor,
                text=False,
            )
            return process
        except OSError as error:
            raise OrchestratorError(
                "LOCAL_ORCHESTRATOR_LAUNCHER_STATUS_HOLD"
            ) from error
        finally:
            if descriptor is not None:
                os.close(descriptor)


def build_parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--mode", choices=tuple(CONFIRMATIONS), required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--novel-id", required=True)
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--host-token-file", type=Path, required=True)
    parser.add_argument("--confirm", required=True)
    return parser


def _canonical_uuid(value: object, code: str) -> str:
    if type(value) is not str:
        raise OrchestratorError(code)
    try:
        canonical = str(UUID(value))
    except (AttributeError, TypeError, ValueError):
        raise OrchestratorError(code) from None
    if canonical != value:
        raise OrchestratorError(code)
    return canonical


def _validate_host_token_path(path: Path) -> Path:
    if not isinstance(path, Path) or not path.is_absolute():
        raise OrchestratorError("LOCAL_ORCHESTRATOR_TOKEN_PATH_INVALID")
    try:
        repository = REPOSITORY_ROOT.resolve(strict=True)
        supplied_parent = path.parent.lstat()
        parent = path.parent.resolve(strict=True)
        supplied = path.lstat()
        resolved = path.resolve(strict=True)
        resolved_details = resolved.lstat()
    except OSError:
        raise OrchestratorError("LOCAL_ORCHESTRATOR_TOKEN_PATH_INVALID") from None
    if (
        parent == repository
        or parent.is_relative_to(repository)
        or resolved == repository
        or resolved.is_relative_to(repository)
        or path.parent != parent
        or path != resolved
        or stat.S_ISLNK(supplied_parent.st_mode)
        or not stat.S_ISDIR(supplied_parent.st_mode)
        or stat.S_IMODE(supplied_parent.st_mode) != 0o700
        or supplied_parent.st_uid != os.getuid()
        or stat.S_ISLNK(supplied.st_mode)
        or not stat.S_ISREG(supplied.st_mode)
        or supplied.st_nlink != 1
        or stat.S_IMODE(supplied.st_mode) != 0o600
        or supplied.st_uid != os.getuid()
        or (supplied.st_dev, supplied.st_ino)
        != (resolved_details.st_dev, resolved_details.st_ino)
    ):
        raise OrchestratorError("LOCAL_ORCHESTRATOR_TOKEN_PATH_INVALID")
    return resolved


def _config_from_args(args: argparse.Namespace) -> RunConfig:
    if args.confirm != CONFIRMATIONS[args.mode]:
        raise OrchestratorError("LOCAL_ORCHESTRATOR_CONFIRMATION_REQUIRED")
    return RunConfig(
        mode=args.mode,
        run_id=_canonical_uuid(args.run_id, "LOCAL_ORCHESTRATOR_RUN_INVALID"),
        novel_id=_canonical_uuid(
            args.novel_id,
            "LOCAL_ORCHESTRATOR_SCOPE_INVALID",
        ),
        document_id=_canonical_uuid(
            args.document_id,
            "LOCAL_ORCHESTRATOR_SCOPE_INVALID",
        ),
        host_token_file=_validate_host_token_path(args.host_token_file),
    )


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        details = path.lstat()
        if stat.S_ISLNK(details.st_mode) or not stat.S_ISREG(details.st_mode):
            raise OrchestratorError("LOCAL_ORCHESTRATOR_SOURCE_INVALID")
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OrchestratorError:
        raise
    except OSError:
        raise OrchestratorError("LOCAL_ORCHESTRATOR_SOURCE_INVALID") from None
    return digest.hexdigest()


def _python_tree_sha256(root: Path) -> str:
    paths = sorted(
        path
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
    )
    if not paths:
        raise OrchestratorError("LOCAL_ORCHESTRATOR_SOURCE_INVALID")
    entries = [
        [path.relative_to(root).as_posix(), _hash_file(path)] for path in paths
    ]
    return hashlib.sha256(_canonical_json_bytes(entries)).hexdigest()


def build_bundle_manifest() -> dict[str, object]:
    files: dict[str, str] = {}
    for relative in BUNDLE_RELATIVE_PATHS:
        source = REPOSITORY_ROOT / relative
        if not source.is_file():
            raise OrchestratorError("LOCAL_ORCHESTRATOR_SOURCE_INVALID")
        digest = _hash_file(source)
        pinned_digest = SUPPORTED_FIXTURE_SHA256.get(relative)
        if pinned_digest is not None and digest != pinned_digest:
            raise OrchestratorError("LOCAL_ORCHESTRATOR_SOURCE_INVALID")
        files[relative] = digest
    unsigned: dict[str, object] = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "files": files,
        "backend_tree_sha256": _python_tree_sha256(REPOSITORY_ROOT / "backend"),
    }
    return {
        **unsigned,
        "bundle_sha256": hashlib.sha256(
            _canonical_json_bytes(unsigned)
        ).hexdigest(),
    }


def _validate_bundle_relative_path(value: object) -> str:
    if type(value) is not str or not value:
        raise OrchestratorError("LOCAL_ORCHESTRATOR_FIXTURE_MANIFEST_HOLD")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
        or "\\" in value
    ):
        raise OrchestratorError("LOCAL_ORCHESTRATOR_FIXTURE_MANIFEST_HOLD")
    return value


def _sealed_fixture_relative_path(config: RunConfig) -> str:
    """Resolve one pinned fixture from this run's private sealed manifest."""

    manifest_path = config.host_exchange_dir / "bundle-manifest.json"
    try:
        details = manifest_path.lstat()
        if (
            stat.S_ISLNK(details.st_mode)
            or not stat.S_ISREG(details.st_mode)
            or details.st_nlink != 1
            or stat.S_IMODE(details.st_mode) != 0o600
            or details.st_uid != os.getuid()
            or details.st_size <= 0
            or details.st_size > _MAX_BUNDLE_MANIFEST_BYTES
        ):
            raise OrchestratorError(
                "LOCAL_ORCHESTRATOR_FIXTURE_MANIFEST_HOLD"
            )
        raw = manifest_path.read_bytes()
    except OrchestratorError:
        raise
    except OSError:
        raise OrchestratorError(
            "LOCAL_ORCHESTRATOR_FIXTURE_MANIFEST_HOLD"
        ) from None
    if len(raw) != details.st_size:
        raise OrchestratorError("LOCAL_ORCHESTRATOR_FIXTURE_MANIFEST_HOLD")

    def reject_duplicate_keys(
        pairs: list[tuple[str, object]],
    ) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    try:
        payload = json.loads(raw, object_pairs_hook=reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise OrchestratorError(
            "LOCAL_ORCHESTRATOR_FIXTURE_MANIFEST_HOLD"
        ) from None
    if (
        type(payload) is not dict
        or set(payload)
        != {"schema_version", "files", "backend_tree_sha256", "bundle_sha256"}
        or payload.get("schema_version") != BUNDLE_SCHEMA_VERSION
        or type(payload.get("files")) is not dict
        or type(payload.get("backend_tree_sha256")) is not str
        or _SHA256.fullmatch(payload["backend_tree_sha256"]) is None
        or type(payload.get("bundle_sha256")) is not str
        or _SHA256.fullmatch(payload["bundle_sha256"]) is None
    ):
        raise OrchestratorError("LOCAL_ORCHESTRATOR_FIXTURE_MANIFEST_HOLD")

    files = payload["files"]
    assert type(files) is dict
    normalized_files: dict[str, str] = {}
    for raw_path, raw_digest in files.items():
        relative = _validate_bundle_relative_path(raw_path)
        if (
            type(raw_digest) is not str
            or _SHA256.fullmatch(raw_digest) is None
        ):
            raise OrchestratorError(
                "LOCAL_ORCHESTRATOR_FIXTURE_MANIFEST_HOLD"
            )
        normalized_files[relative] = raw_digest
    unsigned = {
        "schema_version": payload["schema_version"],
        "files": normalized_files,
        "backend_tree_sha256": payload["backend_tree_sha256"],
    }
    if hashlib.sha256(_canonical_json_bytes(unsigned)).hexdigest() != payload[
        "bundle_sha256"
    ]:
        raise OrchestratorError("LOCAL_ORCHESTRATOR_FIXTURE_MANIFEST_HOLD")

    fixture_directory = PurePosixPath("tests/fixtures/narration")
    fixtures = [
        relative
        for relative in normalized_files
        if PurePosixPath(relative).parent == fixture_directory
        and PurePosixPath(relative).suffix == ".json"
    ]
    if len(fixtures) != 1 or fixtures[0] not in SUPPORTED_FIXTURE_SHA256:
        raise OrchestratorError("LOCAL_ORCHESTRATOR_FIXTURE_MANIFEST_HOLD")
    fixture = fixtures[0]
    if normalized_files[fixture] != SUPPORTED_FIXTURE_SHA256[fixture]:
        raise OrchestratorError("LOCAL_ORCHESTRATOR_FIXTURE_MANIFEST_HOLD")
    return fixture


def _parse_json_output(raw: str, *, code: str) -> Mapping[str, object]:
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        raise OrchestratorError(code) from None
    if type(payload) is not dict:
        raise OrchestratorError(code)
    return payload


def _require_ok(result: CommandResult, *, code: str) -> str:
    if result.returncode != 0:
        raise OrchestratorError(code)
    return result.stdout


def preflight_existing_topology(runner: CommandRunner) -> None:
    for container in FIXED_CONTAINERS:
        result = runner.run(
            (
                "docker",
                "inspect",
                container,
                "--format",
                "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
            ),
            timeout=30,
        )
        if result.returncode != 0 or result.stdout.strip() != "healthy":
            raise OrchestratorError("LOCAL_ORCHESTRATOR_TOPOLOGY_HOLD")
    for container, expected in EXPECTED_CONTAINER_TOPOLOGY.items():
        mounts = runner.run(
            (
                "docker",
                "inspect",
                container,
                "--format",
                "{{json .Mounts}}",
            ),
            timeout=30,
        )
        image = runner.run(
            (
                "docker",
                "inspect",
                container,
                "--format",
                "{{.Config.Image}}",
            ),
            timeout=30,
        )
        networks = runner.run(
            (
                "docker",
                "inspect",
                container,
                "--format",
                "{{json .NetworkSettings.Networks}}",
            ),
            timeout=30,
        )
        if any(item.returncode != 0 for item in (mounts, image, networks)):
            raise OrchestratorError("LOCAL_ORCHESTRATOR_TOPOLOGY_HOLD")
        try:
            rows = json.loads(mounts.stdout)
            network_rows = json.loads(networks.stdout)
            if type(rows) is not list or type(network_rows) is not dict:
                raise TypeError
            observed_mounts: dict[str, tuple[str, str, bool]] = {}
            for row in rows:
                if (
                    type(row) is not dict
                    or type(row.get("Destination")) is not str
                    or type(row.get("Type")) is not str
                    or type(row.get("Name")) is not str
                    or type(row.get("RW")) is not bool
                    or row["Destination"] in observed_mounts
                ):
                    raise TypeError
                observed_mounts[row["Destination"]] = (
                    row["Type"],
                    row["Name"],
                    row["RW"],
                )
            observed_networks = frozenset(network_rows)
        except (TypeError, json.JSONDecodeError):
            raise OrchestratorError(
                "LOCAL_ORCHESTRATOR_TOPOLOGY_HOLD"
            ) from None
        if (
            image.stdout.strip() != expected["image"]
            or observed_mounts != expected["mounts"]
            or observed_networks != expected["networks"]
        ):
            raise OrchestratorError("LOCAL_ORCHESTRATOR_TOPOLOGY_HOLD")


def _docker_exec_prefix(config: RunConfig) -> tuple[str, ...]:
    return (
        "docker",
        "exec",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--env",
        f"PYTHONPATH={config.tool_root}:{INSTALLED_PLUGIN_ROOT}",
        "--workdir",
        str(config.tool_root),
        QWENPAW_CONTAINER,
    )


def _helper_argv(config: RunConfig, mode: str) -> tuple[str, ...]:
    return (
        *_docker_exec_prefix(config),
        CONTAINER_PYTHON,
        "-B",
        str(config.tool_root / "scripts/tts/local_chapter_e2e_container.py"),
        "--mode",
        mode,
        "--run-id",
        config.run_id,
        "--novel-id",
        config.novel_id,
        "--document-id",
        config.document_id,
        "--confirm",
        HELPER_CONFIRMATIONS[mode],
    )


def _run_helper(
    runner: CommandRunner,
    config: RunConfig,
    mode: str,
) -> Mapping[str, object]:
    try:
        result = runner.run(_helper_argv(config, mode), timeout=120)
    except subprocess.TimeoutExpired:
        raise OrchestratorError(
            f"LOCAL_ORCHESTRATOR_{mode.upper().replace('-', '_')}_HOLD"
        ) from None
    if result.returncode != 0:
        if mode == "require-partial-ready-capability":
            raise OrchestratorError(
                "LOCAL_ORCHESTRATOR_PARTIAL_READY_LAUNCHER_REQUIRED"
            )
        raise OrchestratorError(f"LOCAL_ORCHESTRATOR_{mode.upper().replace('-', '_')}_HOLD")
    payload = _parse_json_output(
        result.stdout,
        code="LOCAL_ORCHESTRATOR_HELPER_INVALID",
    )
    if payload.get("status") != "OK" or payload.get("secret_values_emitted") is not False:
        raise OrchestratorError("LOCAL_ORCHESTRATOR_HELPER_INVALID")
    return payload


def _create_host_directory(path: Path, *, exclusive: bool) -> None:
    try:
        if exclusive:
            path.mkdir(mode=0o700, parents=False, exist_ok=False)
        else:
            path.mkdir(mode=0o700, parents=False, exist_ok=True)
        details = path.lstat()
    except FileExistsError:
        raise OrchestratorError("LOCAL_ORCHESTRATOR_HOST_RUN_EXISTS") from None
    except OSError:
        raise OrchestratorError("LOCAL_ORCHESTRATOR_HOST_PATH_INVALID") from None
    if (
        stat.S_ISLNK(details.st_mode)
        or not stat.S_ISDIR(details.st_mode)
        or stat.S_IMODE(details.st_mode) != 0o700
        or details.st_uid != os.getuid()
        or path.resolve(strict=True) != path
    ):
        raise OrchestratorError("LOCAL_ORCHESTRATOR_HOST_PATH_INVALID")


def _ensure_host_exchange(config: RunConfig, *, new: bool) -> None:
    runs = config.host_exchange_dir.parent
    if not runs.exists():
        _create_host_directory(runs, exclusive=True)
    else:
        _create_host_directory(runs, exclusive=False)
    _create_host_directory(config.host_exchange_dir, exclusive=new)


def _stage_bundle(
    runner: CommandRunner,
    config: RunConfig,
    manifest: Mapping[str, object],
) -> None:
    _ensure_host_exchange(config, new=True)
    mkdir = lambda path, parents=False: runner.run(  # noqa: E731
        (
            "docker",
            "exec",
            QWENPAW_CONTAINER,
            "mkdir",
            *(('-p',) if parents else ()),
            "-m",
            "0700",
            str(path),
        ),
        timeout=30,
    )
    _require_ok(mkdir(CONTAINER_RUNS_ROOT, parents=True), code="LOCAL_ORCHESTRATOR_STAGE_HOLD")
    _require_ok(mkdir(config.container_root), code="LOCAL_ORCHESTRATOR_STAGE_HOLD")
    _require_ok(mkdir(config.tool_root), code="LOCAL_ORCHESTRATOR_STAGE_HOLD")
    directory_set: set[Path] = set()
    for relative in BUNDLE_RELATIVE_PATHS:
        current = (config.tool_root / relative).parent
        while current != config.tool_root:
            if not current.is_relative_to(config.tool_root):
                raise OrchestratorError("LOCAL_ORCHESTRATOR_STAGE_HOLD")
            directory_set.add(current)
            current = current.parent
    directories = sorted(
        directory_set,
        key=lambda value: (len(value.parts), str(value)),
    )
    for directory in directories:
        _require_ok(mkdir(directory), code="LOCAL_ORCHESTRATOR_STAGE_HOLD")
    for relative in BUNDLE_RELATIVE_PATHS:
        source = REPOSITORY_ROOT / relative
        target = config.tool_root / relative
        _require_ok(
            runner.run(
                ("docker", "cp", str(source), f"{QWENPAW_CONTAINER}:{target}"),
                timeout=60,
            ),
            code="LOCAL_ORCHESTRATOR_STAGE_HOLD",
        )
        # Docker Desktop preserves the host's numeric uid on ``docker cp``.
        # The fixed container helper runs as uid 0 and deliberately rejects
        # private files owned by any other uid, so converge ownership before
        # the 0600 verification step instead of weakening that gate.
        _require_ok(
            runner.run(
                (
                    "docker",
                    "exec",
                    QWENPAW_CONTAINER,
                    "chown",
                    "--no-dereference",
                    "0:0",
                    str(target),
                ),
                timeout=30,
            ),
            code="LOCAL_ORCHESTRATOR_STAGE_HOLD",
        )
        _require_ok(
            runner.run(
                ("docker", "exec", QWENPAW_CONTAINER, "chmod", "0600", str(target)),
                timeout=30,
            ),
            code="LOCAL_ORCHESTRATOR_STAGE_HOLD",
        )
    manifest_path = config.host_exchange_dir / "bundle-manifest.json"
    try:
        descriptor = os.open(
            manifest_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        try:
            data = _canonical_json_bytes(manifest)
            offset = 0
            while offset < len(data):
                written = os.write(descriptor, data[offset:])
                if written <= 0:
                    raise OrchestratorError("LOCAL_ORCHESTRATOR_STAGE_HOLD")
                offset += written
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        raise OrchestratorError("LOCAL_ORCHESTRATOR_STAGE_HOLD") from None
    target_manifest = config.tool_root / "bundle-manifest.json"
    _require_ok(
        runner.run(
            (
                "docker",
                "cp",
                str(manifest_path),
                f"{QWENPAW_CONTAINER}:{target_manifest}",
            ),
            timeout=30,
        ),
        code="LOCAL_ORCHESTRATOR_STAGE_HOLD",
    )
    _require_ok(
        runner.run(
            (
                "docker",
                "exec",
                QWENPAW_CONTAINER,
                "chown",
                "--no-dereference",
                "0:0",
                str(target_manifest),
            ),
            timeout=30,
        ),
        code="LOCAL_ORCHESTRATOR_STAGE_HOLD",
    )
    _require_ok(
        runner.run(
            (
                "docker",
                "exec",
                QWENPAW_CONTAINER,
                "chmod",
                "0600",
                str(target_manifest),
            ),
            timeout=30,
        ),
        code="LOCAL_ORCHESTRATOR_STAGE_HOLD",
    )
    _verify_fresh_stage_with_retry(runner, config)


def _verify_fresh_stage_with_retry(
    runner: CommandRunner,
    config: RunConfig,
    *,
    sleeper: Callable[[float], None] = time.sleep,
) -> None:
    """Retry only the read-only verification at a freshly copied boundary."""

    try:
        _run_helper(runner, config, "verify-stage")
    except OrchestratorError as error:
        if error.code != "LOCAL_ORCHESTRATOR_VERIFY_STAGE_HOLD":
            raise
        sleeper(0.5)
        _run_helper(runner, config, "verify-stage")


def _readiness_argv(config: RunConfig) -> tuple[str, ...]:
    return (
        *_docker_exec_prefix(config),
        CONTAINER_PYTHON,
        "-B",
        str(config.tool_root / "scripts/tts/chapter_e2e_readiness.py"),
        "--mode",
        "readonly",
        "--attestation-file",
        str(config.recovery_dir / "readiness-attestation.json"),
    )


def _run_readiness(runner: CommandRunner, config: RunConfig) -> str:
    result = runner.run(_readiness_argv(config), timeout=120)
    payload = _parse_json_output(
        result.stdout,
        code="LOCAL_ORCHESTRATOR_READINESS_INVALID",
    )
    if (
        result.returncode != 0
        or payload.get("status") != "HOLD"
        or payload.get("decision") != "READY_FOR_OPERATOR_REVIEW"
        or payload.get("missing_codes") != []
    ):
        raise OrchestratorError("LOCAL_ORCHESTRATOR_READINESS_HOLD")
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _issue_envelope(runner: CommandRunner, config: RunConfig) -> None:
    argv = (
        *_docker_exec_prefix(config),
        CONTAINER_PYTHON,
        "-B",
        str(config.tool_root / "scripts/tts/chapter_e2e_operator_envelope.py"),
        "--mode",
        "issue",
        "--attestation-file",
        str(config.recovery_dir / "readiness-attestation.json"),
        "--run-id",
        config.run_id,
        "--output-file",
        str(config.recovery_dir / "operator-envelope.json"),
        "--confirm-author-review",
        ENVELOPE_CONFIRMATION,
    )
    result = runner.run(argv, timeout=120)
    payload = _parse_json_output(
        result.stdout,
        code="LOCAL_ORCHESTRATOR_ENVELOPE_INVALID",
    )
    if result.returncode != 0 or payload.get("status") != "ISSUED":
        raise OrchestratorError("LOCAL_ORCHESTRATOR_ENVELOPE_HOLD")


def _launcher_argv(
    config: RunConfig,
    *,
    resume: bool,
    fixture_relative_path: str,
) -> tuple[str, ...]:
    fixture_relative_path = _validate_bundle_relative_path(
        fixture_relative_path
    )
    if fixture_relative_path not in SUPPORTED_FIXTURE_SHA256:
        raise OrchestratorError("LOCAL_ORCHESTRATOR_FIXTURE_MANIFEST_HOLD")
    recovery = config.recovery_dir
    argv: list[str] = [
        *_docker_exec_prefix(config),
        CONTAINER_PYTHON,
        "-B",
        str(config.tool_root / "scripts/tts/run_chapter_e2e_real.py"),
        "--mode",
        "real",
        "--operator-envelope-file",
        str(recovery / "operator-envelope.json"),
        "--readiness-attestation-file",
        str(recovery / "readiness-attestation.json"),
        "--probe-report",
        str(recovery / "probe-report.json"),
        "--validation-token-file",
        CONTAINER_TOKEN_FILE,
        "--lock-nano-file",
        str(recovery / "lock-nano"),
        "--lock-browser-file",
        str(recovery / "lock-browser"),
        "--lock-data-file",
        str(recovery / "lock-data"),
        "--lock-nano-grant",
        f"LOCK-NANO/{config.run_id}",
        "--lock-browser-grant",
        f"LOCK-BROWSER/{config.run_id}",
        "--lock-data-grant",
        f"LOCK-T4-K-DATA/{config.run_id}",
        "--confirm-fixed-launcher",
        "RUN-T4-K-FIXED-LAUNCHER",
        "--run-id",
        config.run_id,
        "--fixture-manifest",
        str(config.tool_root / fixture_relative_path),
        "--api-base",
        CONTAINER_API_BASE,
        "--novel-id",
        config.novel_id,
        "--document-id",
        config.document_id,
        "--automatic-case-id",
        AUTOMATIC_CASE_ID,
        "--manual-case-id",
        MANUAL_CASE_ID,
        "--private-work-dir",
        str(recovery),
        "--confirm-dedicated-test-novel",
        config.novel_id,
        "--confirm-dedicated-test-document",
        config.document_id,
        "--duration-minutes",
        DURATION_MINUTES,
        "--output-dir",
        str(config.result_dir),
        "--confirm-real-run",
        "RUN-T4-K-REAL-CHAPTER",
        "--confirm-baseline-restore",
        "RESTORE-T4-K-BASELINE",
        "--confirm-private-work-dir-local-non-synced",
        "PRIVATE-WORK-DIR-LOCAL-NON-SYNCED",
    ]
    if resume:
        argv.extend(
            (
                "--resume",
                "--listening-record",
                str(config.listening_dir / "listening.json"),
            )
        )
    return tuple(argv)


def _poll_probe_request(
    runner: CommandRunner,
    config: RunConfig,
    process: RunningProcess,
    *,
    monotonic: Callable[[], float],
    sleeper: Callable[[float], None],
) -> None:
    deadline = monotonic() + _PROBE_WAIT_SECONDS
    request = config.recovery_dir / "probe-request.json"
    while monotonic() < deadline:
        if process.poll() is not None:
            raise OrchestratorError(
                _launcher_failure_code(
                    config,
                    fallback="LOCAL_ORCHESTRATOR_LAUNCHER_EARLY_EXIT",
                )
            )
        result = runner.run(
            ("docker", "exec", QWENPAW_CONTAINER, "test", "-f", str(request)),
            timeout=15,
        )
        if result.returncode == 0:
            return
        sleeper(0.5)
    raise OrchestratorError("LOCAL_ORCHESTRATOR_PROBE_TIMEOUT")


def _launcher_failure_code(
    config: RunConfig,
    *,
    fallback: str,
    status_file: Path | None = None,
) -> str:
    """Return only a bounded stable code from the private launcher log."""

    path = status_file or config.launcher_status_file
    try:
        details = path.lstat()
        if (
            stat.S_ISLNK(details.st_mode)
            or not stat.S_ISREG(details.st_mode)
            or details.st_nlink != 1
            or stat.S_IMODE(details.st_mode) != 0o600
            or details.st_uid != os.getuid()
            or details.st_size > _MAX_LAUNCHER_STATUS_BYTES
        ):
            return fallback
        raw = path.read_bytes()
    except OSError:
        return fallback
    if len(raw) != details.st_size:
        return fallback
    try:
        lines = raw.decode("ascii", errors="strict").splitlines()
    except UnicodeDecodeError:
        return fallback
    for line in reversed(lines):
        if _STABLE_CODE.fullmatch(line):
            return line
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if type(payload) is dict:
            code = payload.get("code")
            if (
                type(code) is str
                and _STABLE_CODE.fullmatch(code)
                and payload.get("status")
                in {
                    "FAILED",
                    "HOLD",
                    "BASELINE_RESTORED",
                    "HUMAN_LISTENING_PENDING",
                    "PASS_CANDIDATE",
                    "TECHNICAL_PASS_CANDIDATE",
                }
            ):
                return code
    return fallback


def _copy_probe_to_host(runner: CommandRunner, config: RunConfig) -> Path:
    target = config.host_exchange_dir / "probe-request.json"
    if target.exists():
        raise OrchestratorError("LOCAL_ORCHESTRATOR_HOST_REPORT_EXISTS")
    result = runner.run(
        (
            "docker",
            "cp",
            f"{QWENPAW_CONTAINER}:{config.recovery_dir / 'probe-request.json'}",
            str(target),
        ),
        timeout=60,
    )
    _require_ok(result, code="LOCAL_ORCHESTRATOR_PROBE_COPY_HOLD")
    try:
        os.chmod(target, 0o600, follow_symlinks=False)
        details = target.lstat()
    except OSError:
        raise OrchestratorError("LOCAL_ORCHESTRATOR_PROBE_COPY_HOLD") from None
    if (
        stat.S_ISLNK(details.st_mode)
        or not stat.S_ISREG(details.st_mode)
        or details.st_nlink != 1
        or stat.S_IMODE(details.st_mode) != 0o600
        or details.st_uid != os.getuid()
    ):
        raise OrchestratorError("LOCAL_ORCHESTRATOR_PROBE_COPY_HOLD")
    return target


def _run_local_operator(
    runner: CommandRunner,
    config: RunConfig,
    probe_request: Path,
) -> str:
    argv = (
        sys.executable,
        str(REPOSITORY_ROOT / "scripts/tts/run_local_operator_report.py"),
        "--probe-request-file",
        str(probe_request),
        "--host-token-file",
        str(config.host_token_file),
        "--novel-id",
        config.novel_id,
        "--document-id",
        config.document_id,
        "--confirm",
        LOCAL_OPERATOR_CONFIRMATION,
    )
    result = runner.run(argv, timeout=40 * 60)
    if result.returncode != 0:
        payload = _parse_json_output(
            result.stderr,
            code="LOCAL_ORCHESTRATOR_OPERATOR_REPORT_INVALID",
        )
        code = payload.get("code")
        if (
            payload.get("status") == "HOLD"
            and type(code) is str
            and _STABLE_CODE.fullmatch(code) is not None
            and payload.get("secret_values_emitted") is False
            and payload.get("private_paths_emitted") is False
        ):
            raise OrchestratorError(code)
        raise OrchestratorError("LOCAL_ORCHESTRATOR_OPERATOR_REPORT_INVALID")
    payload = _parse_json_output(
        result.stdout,
        code="LOCAL_ORCHESTRATOR_OPERATOR_REPORT_INVALID",
    )
    report_sha = payload.get("collector_report_sha256")
    probe_sha = payload.get("probe_report_sha256")
    if (
        payload.get("status") != "LOCAL_OPERATOR_OBSERVATION_COMMITTED"
        or type(report_sha) is not str
        or _SHA256.fullmatch(report_sha) is None
        or type(probe_sha) is not str
        or _SHA256.fullmatch(probe_sha) is None
        or payload.get("secret_values_emitted") is not False
    ):
        raise OrchestratorError("LOCAL_ORCHESTRATOR_OPERATOR_REPORT_HOLD")
    for filename in REPORT_FILENAMES:
        path = config.host_exchange_dir / filename
        try:
            details = path.lstat()
        except OSError:
            raise OrchestratorError("LOCAL_ORCHESTRATOR_OPERATOR_REPORT_HOLD") from None
        if (
            stat.S_ISLNK(details.st_mode)
            or not stat.S_ISREG(details.st_mode)
            or details.st_nlink != 1
            or stat.S_IMODE(details.st_mode) != 0o600
            or details.st_uid != os.getuid()
        ):
            raise OrchestratorError("LOCAL_ORCHESTRATOR_OPERATOR_REPORT_HOLD")
    if _hash_file(config.host_exchange_dir / "collector-report.json") != report_sha:
        raise OrchestratorError("LOCAL_ORCHESTRATOR_OPERATOR_REPORT_HOLD")
    if _hash_file(config.host_exchange_dir / "probe-report.json") != probe_sha:
        raise OrchestratorError("LOCAL_ORCHESTRATOR_OPERATOR_REPORT_HOLD")
    return report_sha


def _copy_report_to_container(runner: CommandRunner, config: RunConfig) -> None:
    for filename in REPORT_FILENAMES:
        source = config.host_exchange_dir / filename
        target = config.incoming_dir / filename
        result = runner.run(
            ("docker", "cp", str(source), f"{QWENPAW_CONTAINER}:{target}"),
            timeout=60,
        )
        _require_ok(result, code="LOCAL_ORCHESTRATOR_REPORT_IMPORT_HOLD")
        # Docker Desktop preserves the host numeric uid on ``docker cp``.
        # The fixed container helper intentionally accepts only uid-0 private
        # inputs, matching the sealed tool staging path above.  Converge the
        # copied report owner before the 0600 parse/import gate.
        _require_ok(
            runner.run(
                (
                    "docker",
                    "exec",
                    QWENPAW_CONTAINER,
                    "chown",
                    "--no-dereference",
                    "0:0",
                    str(target),
                ),
                timeout=30,
            ),
            code="LOCAL_ORCHESTRATOR_REPORT_IMPORT_HOLD",
        )
        _require_ok(
            runner.run(
                ("docker", "exec", QWENPAW_CONTAINER, "chmod", "0600", str(target)),
                timeout=30,
            ),
            code="LOCAL_ORCHESTRATOR_REPORT_IMPORT_HOLD",
        )
    _run_helper(runner, config, "import-report")


def _stop_process(process: RunningProcess) -> None:
    if process.poll() is not None:
        return
    actions = (
        (lambda: process.send_signal(signal.SIGINT), 10.0),
        (process.terminate, 10.0),
        (process.kill, 10.0),
    )
    for action, timeout in actions:
        if process.poll() is not None:
            return
        try:
            action()
        except Exception:
            pass
        try:
            process.wait(timeout=timeout)
            return
        except Exception:
            continue
    if process.poll() is None:
        raise OrchestratorError("LOCAL_ORCHESTRATOR_PROCESS_STOP_HOLD")


def _wait_process(
    process: RunningProcess,
    *,
    timeout: float,
) -> int:
    try:
        return process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        raise OrchestratorError("LOCAL_ORCHESTRATOR_LAUNCHER_TIMEOUT") from None


def prepare_workflow(runner: CommandRunner, config: RunConfig) -> WorkflowResult:
    preflight_existing_topology(runner)
    manifest = build_bundle_manifest()
    _stage_bundle(runner, config, manifest)
    _run_helper(runner, config, "prepare")
    readiness_sha = _run_readiness(runner, config)
    return WorkflowResult(
        status="HOLD",
        code="READY_FOR_OPERATOR_REVIEW",
        report_sha256=readiness_sha,
    )


def run_workflow(
    runner: CommandRunner,
    config: RunConfig,
    *,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> WorkflowResult:
    preflight_existing_topology(runner)
    _ensure_host_exchange(config, new=False)
    fixture_relative_path = _sealed_fixture_relative_path(config)
    _run_helper(runner, config, "verify-stage")
    _run_readiness(runner, config)
    _run_helper(runner, config, "require-partial-ready-capability")
    _issue_envelope(runner, config)
    _run_helper(runner, config, "arm-claim-gate")
    process: RunningProcess | None = None
    primary_error: BaseException | None = None
    primary_traceback = None
    release_required = True
    result: WorkflowResult | None = None
    try:
        process = runner.popen(
            _launcher_argv(
                config,
                resume=False,
                fixture_relative_path=fixture_relative_path,
            ),
            status_file=config.launcher_status_file,
        )
        _poll_probe_request(
            runner,
            config,
            process,
            monotonic=monotonic,
            sleeper=sleeper,
        )
        request = _copy_probe_to_host(runner, config)
        report_sha = _run_local_operator(runner, config, request)
        _copy_report_to_container(runner, config)
        # The launcher deliberately waits for this release before completing.
        _run_helper(runner, config, "release-claim-gate")
        release_required = False
        exit_code = _wait_process(process, timeout=10 * 60)
        launcher_code = _launcher_failure_code(
            config,
            fallback="LOCAL_ORCHESTRATOR_LAUNCHER_HOLD",
        )
        if exit_code == 3 and launcher_code == "HUMAN_LISTENING_PENDING":
            status = launcher_code
        else:
            status = _run_helper(runner, config, "status").get("code")
        if exit_code != 3 or status != "HUMAN_LISTENING_PENDING":
            raise OrchestratorError(
                _launcher_failure_code(
                    config,
                    fallback="LOCAL_ORCHESTRATOR_LAUNCHER_HOLD",
                )
            )
        result = WorkflowResult(
            status="HOLD",
            code="HUMAN_LISTENING_PENDING",
            report_sha256=report_sha,
        )
    except BaseException as error:
        primary_error = error
        primary_traceback = error.__traceback__

    stop_error: BaseException | None = None
    if primary_error is not None and process is not None:
        if process.poll() is None:
            try:
                _run_helper(runner, config, "stop-launcher")
            except BaseException as error:
                stop_error = error
        try:
            _stop_process(process)
        except BaseException as error:
            if stop_error is None:
                stop_error = error
    if release_required and (process is None or process.poll() is not None):
        try:
            _run_helper(runner, config, "release-claim-gate")
            release_required = False
        except BaseException:
            # Preserve the primary launcher/operator error.  A release failure
            # remains fail-closed and the short claim TTL is the final fallback.
            if primary_error is None:
                raise
    if primary_error is not None:
        raise primary_error.with_traceback(primary_traceback)
    if stop_error is not None:
        raise stop_error
    if release_required:
        raise OrchestratorError("LOCAL_ORCHESTRATOR_RELEASE_CLAIM_GATE_HOLD")
    assert result is not None
    return result


def resume_workflow(runner: CommandRunner, config: RunConfig) -> WorkflowResult:
    preflight_existing_topology(runner)
    _ensure_host_exchange(config, new=False)
    fixture_relative_path = _sealed_fixture_relative_path(config)
    _run_helper(runner, config, "verify-stage")
    process = runner.popen(
        _launcher_argv(
            config,
            resume=True,
            fixture_relative_path=fixture_relative_path,
        ),
        status_file=config.launcher_resume_status_file,
    )
    try:
        exit_code = _wait_process(process, timeout=15 * 60)
    except BaseException:
        _stop_process(process)
        raise
    launcher_code = _launcher_failure_code(
        config,
        fallback="LOCAL_ORCHESTRATOR_RESUME_HOLD",
        status_file=config.launcher_resume_status_file,
    )
    # A recovery-only resume finalizes and removes its private recovery record
    # after the launcher has durably restored the baseline.  In that terminal
    # state the container status helper intentionally has no live record left
    # to inspect, so accept only the launcher's bounded 0600 terminal proof.
    if exit_code == 0 and launcher_code in {
        "BASELINE_RESTORED",
        "PASS_CANDIDATE",
        "TECHNICAL_PASS_CANDIDATE",
    }:
        return WorkflowResult(status="OK", code=launcher_code)
    if exit_code == 2 and launcher_code == "HUMAN_LISTENING_FAILED":
        return WorkflowResult(status="HOLD", code=launcher_code)
    status = _run_helper(runner, config, "status").get("code")
    if exit_code == 2 and status == "HUMAN_LISTENING_FAILED":
        return WorkflowResult(status="HOLD", code="HUMAN_LISTENING_FAILED")
    if exit_code != 0 or status not in {
        "PASS_CANDIDATE",
        "TECHNICAL_PASS_CANDIDATE",
        "BASELINE_RESTORED",
    }:
        raise OrchestratorError(
            _launcher_failure_code(
                config,
                fallback="LOCAL_ORCHESTRATOR_RESUME_HOLD",
                status_file=config.launcher_resume_status_file,
            )
        )
    return WorkflowResult(status="OK", code=str(status))


def cleanup_workflow(runner: CommandRunner, config: RunConfig) -> WorkflowResult:
    preflight_existing_topology(runner)
    _ensure_host_exchange(config, new=False)
    payload = _run_helper(runner, config, "cleanup")
    if payload.get("code") != "TOOLS_CLEANED":
        raise OrchestratorError("LOCAL_ORCHESTRATOR_CLEANUP_HOLD")
    return WorkflowResult(status="OK", code="TOOLS_CLEANED")


def execute(
    config: RunConfig,
    *,
    runner: CommandRunner | None = None,
) -> WorkflowResult:
    command_runner = runner or SubprocessCommandRunner()
    if config.mode == "prepare":
        return prepare_workflow(command_runner, config)
    if config.mode == "run":
        return run_workflow(command_runner, config)
    if config.mode == "resume":
        return resume_workflow(command_runner, config)
    return cleanup_workflow(command_runner, config)


def _write_result(stream, result: WorkflowResult) -> None:  # type: ignore[no-untyped-def]
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "status": result.status,
        "code": result.code,
        "secret_values_emitted": False,
        "private_paths_emitted": False,
    }
    if result.report_sha256 is not None:
        payload["report_sha256"] = result.report_sha256
    stream.write(
        json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        config = _config_from_args(args)
        result = execute(config)
        _write_result(sys.stdout, result)
        return 0 if result.status == "OK" else 3
    except OrchestratorError as error:
        _write_result(sys.stderr, WorkflowResult(status="HOLD", code=error.code))
        return 2
    except KeyboardInterrupt:
        _write_result(
            sys.stderr,
            WorkflowResult(status="HOLD", code="LOCAL_ORCHESTRATOR_INTERRUPTED"),
        )
        return 130
    except SystemExit as error:
        return error.code if type(error.code) is int else 0
    except BaseException:
        _write_result(
            sys.stderr,
            WorkflowResult(status="HOLD", code="LOCAL_ORCHESTRATOR_INTERNAL_ERROR"),
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BUNDLE_RELATIVE_PATHS",
    "CONFIRMATIONS",
    "FRESH_FIXTURE_RELATIVE_PATH",
    "LEGACY_FIXTURE_RELATIVE_PATH",
    "SUPPORTED_FIXTURE_SHA256",
    "CommandResult",
    "OrchestratorError",
    "RunConfig",
    "WorkflowResult",
    "build_bundle_manifest",
    "build_parser",
    "cleanup_workflow",
    "execute",
    "main",
    "preflight_existing_topology",
    "prepare_workflow",
    "resume_workflow",
    "run_workflow",
]
