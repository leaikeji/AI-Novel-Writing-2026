#!/usr/bin/env python3
"""Run the T1 isolated QwenPaw plugin lifecycle gate.

The real mode deliberately creates exactly two disposable containers: one
QwenPaw 2.1.0 candidate host and one PostgreSQL 18 database.  Every mutable
resource has a unique name and two ownership labels.  The candidate PawApp is
installed through QwenPaw's public runtime API, force-reinstalled, uninstalled
through the public DELETE endpoint, and installed again.

This runner never invokes the repository Compose project or the legacy lab
helper because both own long-lived project resources.  It also never starts a
MOSS-TTS Sidecar, mounts model/token paths, or prints command output.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import quote


APP_ID = "ai-novel-world-2026"
APP_VERSION = "0.4.0"
EXPECTED_MIGRATION_HEAD = "20260828_0024"
TTS_PROTOCOL_VERSION = "moss-tts-sidecar/1.1"

QWENPAW_IMAGE = "ai-novel-2026-qwenpaw-runtime:2.1.0-mvp0"
POSTGRES_IMAGE = (
    "pgvector/pgvector:0.8.6-pg18@"
    "sha256:2ba9ca5f2e7daa0f0e7723cba1ee9167bab54efd3640516a44ac1a928dd67e7a"
)
CONTAINER_PLATFORM = "linux/arm64"

GATE_LABEL_KEY = "ai.novel.world.gate"
GATE_LABEL_VALUE = "t1-qwenpaw-plugin-lifecycle"
RUN_LABEL_KEY = "ai.novel.world.validation-run"
RESOURCE_PREFIX = "ai-novel-2026-t1gate"
REAL_CONFIRMATION = "RUN-T1-GATE-ISOLATED-QWENPAW"

DATABASE_NAME = "t1_gate"
DATABASE_USER = "t1_gate"
DATABASE_HOST_ALIAS = "postgres"

NOVEL_SKILLS = frozenset(
    {
        "novel-direction",
        "story-foundation",
        "character-craft",
        "chapter-outline",
        "scene-craft",
        "dialogue-craft",
        "prose-writing",
        "continuity-check",
        "style-review",
    }
)
NOVEL_TOOLS = frozenset(
    {
        "novel_get_context",
        "novel_get_document",
        "novel_search",
        "novel_get_workspace_context",
        "novel_prepare_selection_edit",
    }
)

EXPECTED_DISABLED_NARRATION = {
    "technical_enabled": False,
    "lifecycle_status": "disabled",
    "sidecar_reachable": False,
    "model_ready": False,
    "product_visible": False,
    "protocol_version": TTS_PROTOCOL_VERSION,
    "worker_generation": None,
    "lease_generation": None,
    "model_fingerprint_sha256": None,
    "reason_code": None,
}

EXPECTED_DISABLED_NARRATION_PRODUCTION = {
    "product_requested": False,
    "lifecycle_status": "disabled",
    "playback_installed": False,
    "digest_keyring_loaded": False,
    "production_backend_installed": False,
    "worker_running": False,
    "reference_clone_ready": False,
    "reason_code": None,
}

T4_PROBE_UUID = "00000000-0000-4000-8000-000000000001"
T4_DISABLED_ROUTE_PROBES = (
    (
        "narration",
        f"/api/{APP_ID}/narration-requests/{T4_PROBE_UUID}",
    ),
    (
        "script",
        f"/api/{APP_ID}/narration-scripts/{T4_PROBE_UUID}",
    ),
    (
        "playback",
        f"/api/{APP_ID}/narration-editions/{T4_PROBE_UUID}/manifest",
    ),
)

FORBIDDEN_CONTAINER_NAMES = frozenset(
    {
        "ai-novel-2026-qwenpaw-lab",
        "ai-novel-2026-postgres",
        "ai-novel-2026-moss-tts-sidecar",
        "ai-novel-2026-moss-tts-runtime-init",
        "ai-novel-2026-moss-tts-model-installer",
    }
)
FORBIDDEN_VOLUME_NAMES = frozenset(
    {
        "ai-novel-2026-qwenpaw-data",
        "ai-novel-2026-qwenpaw-secrets",
        "ai-novel-2026-qwenpaw-backups",
        "ai-novel-2026-postgres-data",
        "ai-novel-2026-novel-media",
        "ai-novel-2026-moss-models",
        "ai-novel-2026-moss-tts-secrets",
    }
)
FORBIDDEN_NETWORK_NAMES = frozenset(
    {
        "ai-novel-world-2026_default",
        "ai-novel-2026-tts-private",
        "ai-novel-2026-tts-download",
    }
)

RUN_ID_RE = re.compile(r"^[a-z0-9]{8,20}$")
SAFE_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CANDIDATE = PROJECT_ROOT / "build" / APP_ID


class GateError(RuntimeError):
    """A deliberately output-safe lifecycle gate failure."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class ResourceNames:
    """All resources uniquely owned by one validation run."""

    run_id: str
    qwenpaw_container: str
    postgres_container: str
    network: str
    qwenpaw_data: str
    qwenpaw_secrets: str
    qwenpaw_backups: str
    novel_media: str
    postgres_data: str

    @property
    def containers(self) -> tuple[str, str]:
        return (self.qwenpaw_container, self.postgres_container)

    @property
    def volumes(self) -> tuple[str, ...]:
        return (
            self.qwenpaw_data,
            self.qwenpaw_secrets,
            self.qwenpaw_backups,
            self.novel_media,
            self.postgres_data,
        )


@dataclass(frozen=True)
class GateConfig:
    """Validated immutable inputs for one lifecycle run."""

    mode: str
    run_id: str
    candidate: Path
    transcript: Path | None
    confirmation: str | None
    candidate_tree_sha256: str = ""
    startup_timeout_seconds: int = 180
    registry_timeout_seconds: int = 45


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class RegistrySnapshot:
    """Only plugin-owned registry state; contains no user content."""

    agent_ids: tuple[str, ...]
    skills_by_agent: Mapping[str, tuple[str, ...]]
    tools_by_agent: Mapping[str, tuple[str, ...]]

    def as_dict(self) -> dict[str, object]:
        return {
            "agent_ids": list(self.agent_ids),
            "skills_by_agent": {
                key: list(value) for key, value in self.skills_by_agent.items()
            },
            "tools_by_agent": {
                key: list(value) for key, value in self.tools_by_agent.items()
            },
        }


@dataclass
class Evidence:
    """Sanitized evidence accumulated during the run."""

    run_id: str
    mode: str
    status: str = "running"
    phases: list[str] = field(default_factory=list)
    checks: dict[str, object] = field(default_factory=dict)
    cleanup: dict[str, object] = field(default_factory=dict)
    failure_code: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "gate": "T1-GATE-INSTALL",
            "run_id": self.run_id,
            "mode": self.mode,
            "status": self.status,
            "phases": list(self.phases),
            "checks": dict(self.checks),
            "cleanup": dict(self.cleanup),
            "failure_code": self.failure_code,
        }


class SubprocessExecutor:
    """Argument-vector-only process executor; shell expansion is impossible."""

    def run(
        self,
        argv: Sequence[str],
        *,
        timeout: float,
        check: bool = True,
    ) -> CommandResult:
        try:
            result = subprocess.run(  # noqa: S603 - fixed argv, no shell
                list(argv),
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=_minimal_process_environment(),
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise GateError("COMMAND_EXECUTION_FAILED") from error
        command_result = CommandResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
        if check and command_result.returncode != 0:
            raise GateError("COMMAND_FAILED")
        return command_result


def _minimal_process_environment() -> dict[str, str]:
    """Pass only process-discovery/locale variables, never project secrets."""

    allowed = ("HOME", "PATH", "LANG", "LC_ALL", "TMPDIR")
    return {key: os.environ[key] for key in allowed if key in os.environ}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _resource_is_absent(kind: str, result: CommandResult) -> bool:
    if result.returncode == 0:
        return False
    message = f"{result.stdout}\n{result.stderr}".lower()
    markers = {
        "container": ("no such container",),
        "volume": ("no such volume",),
        "network": ("no such network", "network ", " not found"),
    }
    expected = markers.get(kind, ())
    if kind == "network":
        return expected[0] in message or (
            expected[1] in message and expected[2] in message
        )
    return any(marker in message for marker in expected)


def create_resource_names(run_id: str) -> ResourceNames:
    if not RUN_ID_RE.fullmatch(run_id):
        raise GateError("INVALID_RUN_ID")
    prefix = f"{RESOURCE_PREFIX}-{run_id}"
    names = ResourceNames(
        run_id=run_id,
        qwenpaw_container=f"{prefix}-qwenpaw",
        postgres_container=f"{prefix}-postgres",
        network=f"{prefix}-net",
        qwenpaw_data=f"{prefix}-qwen-data",
        qwenpaw_secrets=f"{prefix}-qwen-secrets",
        qwenpaw_backups=f"{prefix}-qwen-backups",
        novel_media=f"{prefix}-novel-media",
        postgres_data=f"{prefix}-postgres-data",
    )
    validate_resource_names(names)
    return names


def validate_resource_names(names: ResourceNames) -> None:
    """Reject any name that could address the formal/lab resources."""

    expected_prefix = f"{RESOURCE_PREFIX}-{names.run_id}-"
    groups: tuple[tuple[Iterable[str], frozenset[str]], ...] = (
        (names.containers, FORBIDDEN_CONTAINER_NAMES),
        (names.volumes, FORBIDDEN_VOLUME_NAMES),
        ((names.network,), FORBIDDEN_NETWORK_NAMES),
    )
    seen: set[str] = set()
    for values, forbidden in groups:
        for value in values:
            if value in forbidden or not value.startswith(expected_prefix):
                raise GateError("UNSAFE_RESOURCE_NAME")
            if value in seen:
                raise GateError("DUPLICATE_RESOURCE_NAME")
            seen.add(value)


def validate_candidate(candidate: Path) -> tuple[Path, str]:
    """Validate that an immutable, complete 0.4.0 candidate was supplied."""

    if not candidate.is_absolute():
        raise GateError("CANDIDATE_MUST_BE_ABSOLUTE")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as error:
        raise GateError("CANDIDATE_NOT_FOUND") from error
    if resolved != candidate or candidate.is_symlink() or not candidate.is_dir():
        raise GateError("CANDIDATE_PATH_NOT_CANONICAL")
    if any(character in str(candidate) for character in (",", "\r", "\n")):
        raise GateError("CANDIDATE_PATH_UNSUPPORTED")

    required = (
        "plugin.json",
        "plugin.py",
        "requirements.txt",
        "alembic.ini",
        "frontend/dist/index.js",
        "backend/app.py",
        "backend/narration/pawapp_runtime.py",
        (
            "backend/migrations/versions/"
            "20260826_0015_narration_domain_concurrency_guards.py"
        ),
    ) + tuple(f"skills/{name}/SKILL.md" for name in sorted(NOVEL_SKILLS))
    for relative in required:
        path = candidate / relative
        if not path.is_file() or path.is_symlink():
            raise GateError("CANDIDATE_INCOMPLETE", relative)
    try:
        manifest = json.loads((candidate / "plugin.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise GateError("CANDIDATE_MANIFEST_INVALID") from error
    if not isinstance(manifest, dict):
        raise GateError("CANDIDATE_MANIFEST_INVALID")
    if manifest.get("id") != APP_ID or manifest.get("version") != APP_VERSION:
        raise GateError("CANDIDATE_ID_OR_VERSION_MISMATCH")
    tools = manifest.get("meta", {}).get("tools", [])
    tool_names = {
        item.get("name") for item in tools if isinstance(item, dict)
    }
    if tool_names != NOVEL_TOOLS:
        raise GateError("CANDIDATE_TOOL_CONTRACT_MISMATCH")

    digest = hashlib.sha256()
    files = 0
    for path in sorted(candidate.rglob("*"), key=lambda item: item.relative_to(candidate).as_posix()):
        if path.is_symlink():
            raise GateError("CANDIDATE_SYMLINK_FORBIDDEN")
        if path.is_dir():
            continue
        if not path.is_file():
            raise GateError("CANDIDATE_SPECIAL_FILE_FORBIDDEN")
        relative = path.relative_to(candidate).as_posix()
        data = path.read_bytes()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
        files += 1
    if files == 0:
        raise GateError("CANDIDATE_EMPTY")
    return candidate, digest.hexdigest()


def build_dry_run_plan(config: GateConfig, names: ResourceNames) -> dict[str, object]:
    """Return a secret-free plan.  This function performs no Docker calls."""

    return {
        "schema_version": 1,
        "gate": "T1-GATE-INSTALL",
        "mode": "dry-run",
        "run_id": config.run_id,
        "candidate": {
            "plugin": f"{APP_ID}@{APP_VERSION}",
            "staging": "docker-cp-to-qwenpaw-container-layer",
            "container_path": "/gate/candidate",
            "host_copy_detached_after_staging": True,
            "integrity_rechecked_before_each_install": True,
        },
        "topology": {
            "container_count": 2,
            "containers": [names.qwenpaw_container, names.postgres_container],
            "qwenpaw_image": QWENPAW_IMAGE,
            "postgres_image": POSTGRES_IMAGE,
            "network": names.network,
            "network_internal": True,
            "outbound_network_route": False,
            "python_package_index_access": False,
            "volume_count": len(names.volumes),
            "volumes": list(names.volumes),
            "sidecar_started": False,
            "model_mount_count": 0,
            "token_mount_count": 0,
            "host_bind_mount_count": 0,
            "tts_runtime_enabled": False,
            "tts_product_enabled": False,
            "tts_validation_enabled": False,
            "tts_reference_clone_enabled": False,
            "tts_storage_root_env_count": 0,
            "published_ports": [],
            "public_api_probe": "docker-exec-to-container-loopback-127.0.0.1:8088",
            "postgres_published": False,
        },
        "lifecycle": [
            "preflight-owned-names-and-images",
            "create-network-and-volumes",
            "start-postgresql-18",
            "start-qwenpaw-with-tts-disabled",
            "docker-cp-candidate-and-verify-tree-hash",
            "public-install",
            "migrate-to-20260828_0024",
            "verify-disabled-narration-production-t4-routes-and-registries",
            "create-db-and-volume-sentinels",
            "public-force-reinstall",
            "verify-idempotency-and-sentinels",
            "public-delete-uninstall",
            "verify-zero-residue-native-routes-and-sentinels",
            "public-reinstall",
            "verify-restored-contract-and-sentinels",
            "finally-remove-only-owned-run-resources",
        ],
        "public_api_operations": [
            {"method": "POST", "path": "/api/plugins/install", "force": False},
            {"method": "POST", "path": "/api/plugins/install", "force": True},
            {"method": "DELETE", "path": f"/api/plugins/{APP_ID}"},
            {"method": "POST", "path": "/api/plugins/install", "force": False},
        ],
        "cleanup": {
            "strategy": "exact-name+ownership-label",
            "always": True,
            "compose_used": False,
            "broad_down_or_volume_prune": False,
            "formal_resources_allowed": False,
        },
    }


class LifecycleGate:
    """Stateful real-mode lifecycle validator with exact cleanup ownership."""

    def __init__(
        self,
        config: GateConfig,
        names: ResourceNames,
        *,
        executor: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.names = names
        self.executor = executor or SubprocessExecutor()
        self.sleep = sleep
        self.monotonic = monotonic
        self.evidence = Evidence(config.run_id, config.mode)
        self.base_url: str | None = None
        self.database_password = secrets.token_urlsafe(24)
        self._attempted: list[tuple[str, str]] = []

    @property
    def ownership_labels(self) -> tuple[str, str]:
        return (
            f"{GATE_LABEL_KEY}={GATE_LABEL_VALUE}",
            f"{RUN_LABEL_KEY}={self.config.run_id}",
        )

    def run(self) -> dict[str, object]:
        failure: GateError | None = None
        cleanup_failure: GateError | None = None
        try:
            self._phase("preflight")
            self._preflight()
            self._phase("create-isolated-runtime")
            self._create_resources()
            self._phase("stage-candidate-with-docker-cp")
            self._stage_candidate()
            self._wait_for_services()

            self._phase("install")
            self._install(force=False, step="initial-install")
            self._migrate_and_verify_head()
            initial_registry = self._wait_for_installed_contract()
            sentinels = self._create_sentinels()
            self._verify_sentinels(sentinels)

            self._phase("force-reinstall")
            self._install(force=True, step="force-reinstall")
            self._migrate_and_verify_head()
            force_registry = self._wait_for_installed_contract()
            if force_registry != initial_registry:
                raise GateError("FORCE_REINSTALL_REGISTRY_NOT_IDEMPOTENT")
            self._verify_sentinels(sentinels)

            self._phase("uninstall")
            status, payload = self._http_json(
                "DELETE",
                f"/api/plugins/{APP_ID}",
                expected_statuses=(200,),
                step="public-delete-uninstall",
            )
            if status != 200 or not isinstance(payload, dict) or payload.get("id") != APP_ID:
                raise GateError("PUBLIC_UNINSTALL_RESPONSE_INVALID")
            self._wait_for_uninstalled_contract()
            self._verify_sentinels(sentinels)

            self._phase("reinstall")
            self._install(force=False, step="reinstall")
            self._migrate_and_verify_head()
            reinstall_registry = self._wait_for_installed_contract()
            if reinstall_registry != initial_registry:
                raise GateError("REINSTALL_REGISTRY_NOT_RESTORED")
            self._verify_sentinels(sentinels)
            self._verify_novel_route(sentinels["novel_id"])
            self.evidence.status = "passed"
        except GateError as error:
            failure = error
            self.evidence.status = "failed"
            self.evidence.failure_code = error.code
            self.evidence.checks["failure-context"] = {
                "detail": error.detail or None,
            }
            self._collect_failure_diagnostics()
        except Exception as error:  # defensive: still guarantee exact cleanup
            failure = GateError("UNEXPECTED_GATE_FAILURE")
            self.evidence.status = "failed"
            self.evidence.failure_code = failure.code
            failure.__cause__ = error
            self.evidence.checks["failure-context"] = {"detail": None}
            self._collect_failure_diagnostics()
        finally:
            try:
                self._cleanup()
            except GateError as error:
                cleanup_failure = error
                self.evidence.cleanup = {
                    "status": "failed",
                    "failure_code": error.code,
                }
                if failure is None:
                    self.evidence.status = "failed"
                    self.evidence.failure_code = error.code
            try:
                self._write_transcript()
            except Exception:
                transcript_failure = GateError("TRANSCRIPT_WRITE_FAILED")
                if failure is None and cleanup_failure is None:
                    failure = transcript_failure
                    self.evidence.status = "failed"
                    self.evidence.failure_code = transcript_failure.code

        if failure is not None:
            raise failure
        if cleanup_failure is not None:
            raise cleanup_failure
        return self.evidence.as_dict()

    def _phase(self, name: str) -> None:
        self.evidence.phases.append(name)

    def _run_command(
        self,
        argv: Sequence[str],
        *,
        step: str,
        timeout: float = 60,
        check: bool = True,
    ) -> CommandResult:
        try:
            # Always request the raw result so a non-zero command is captured in
            # the sanitized transcript before the gate raises.  Command argv and
            # output bodies are deliberately never persisted.
            result = self.executor.run(argv, timeout=timeout, check=False)
        except GateError as error:
            self.evidence.checks[f"command:{step}"] = {
                "returncode": None,
                "execution_failure_code": error.code,
                "stdout_sha256": None,
                "stderr_sha256": None,
            }
            raise GateError(error.code, step) from error
        self.evidence.checks[f"command:{step}"] = {
            "returncode": result.returncode,
            "stdout_sha256": _sha256_text(result.stdout),
            "stderr_sha256": _sha256_text(result.stderr),
        }
        if check and result.returncode != 0:
            raise GateError("COMMAND_FAILED", step)
        return result

    def _collect_failure_diagnostics(self) -> None:
        """Record secret-free state/log fingerprints before exact cleanup."""

        diagnostics: dict[str, object] = {}
        attempted_containers = [
            name for kind, name in self._attempted if kind == "container"
        ]
        for name in attempted_containers:
            key = "qwenpaw" if name == self.names.qwenpaw_container else "postgres"
            try:
                state = self.executor.run(
                    [
                        "docker",
                        "container",
                        "inspect",
                        "--format",
                        (
                            "{{.State.Status}}|{{.State.ExitCode}}|"
                            "{{.State.OOMKilled}}|{{.State.Dead}}|{{.Image}}"
                        ),
                        name,
                    ],
                    timeout=15,
                    check=False,
                )
                state_record: dict[str, object] = {
                    "inspect_returncode": state.returncode,
                    "inspect_stdout_sha256": _sha256_text(state.stdout),
                    "inspect_stderr_sha256": _sha256_text(state.stderr),
                }
                fields = state.stdout.strip().split("|")
                if state.returncode == 0 and len(fields) == 5:
                    status, exit_code, oom_killed, dead, image_id = fields
                    state_record.update(
                        {
                            "status": status,
                            "exit_code": int(exit_code),
                            "oom_killed": oom_killed.lower() == "true",
                            "dead": dead.lower() == "true",
                            "image_id": image_id,
                        }
                    )
                logs = self.executor.run(
                    ["docker", "logs", "--tail", "200", name],
                    timeout=15,
                    check=False,
                )
                combined_logs = f"{logs.stdout}\n{logs.stderr}".lower()
                state_record["logs"] = {
                    "returncode": logs.returncode,
                    "stdout_bytes": len(logs.stdout.encode("utf-8")),
                    "stderr_bytes": len(logs.stderr.encode("utf-8")),
                    "stdout_sha256": _sha256_text(logs.stdout),
                    "stderr_sha256": _sha256_text(logs.stderr),
                    "markers": {
                        "traceback": "traceback (most recent call last)" in combined_logs,
                        "permission_denied": "permission denied" in combined_logs,
                        "module_not_found": "modulenotfounderror" in combined_logs,
                        "database_error": any(
                            marker in combined_logs
                            for marker in (
                                "connection refused",
                                "could not connect",
                                "database error",
                            )
                        ),
                        "address_in_use": "address already in use" in combined_logs,
                    },
                }
                diagnostics[key] = state_record
            except Exception as error:  # diagnostics must never block cleanup
                diagnostics[key] = {
                    "diagnostic_failure_type": type(error).__name__,
                }
        self.evidence.checks["failure-diagnostics"] = diagnostics

    def _preflight(self) -> None:
        validate_resource_names(self.names)
        self._run_command(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            step="docker-server-available",
            timeout=15,
        )
        for image_name, image in (("qwenpaw", QWENPAW_IMAGE), ("postgres", POSTGRES_IMAGE)):
            self._run_command(
                ["docker", "image", "inspect", "--format", "{{.Id}}", image],
                step=f"image-present-{image_name}",
                timeout=30,
            )
        for kind, names in (
            ("container", self.names.containers),
            ("volume", self.names.volumes),
            ("network", (self.names.network,)),
        ):
            for name in names:
                result = self.executor.run(
                    ["docker", kind, "inspect", name],
                    timeout=10,
                    check=False,
                )
                if result.returncode == 0:
                    raise GateError("RUN_RESOURCE_ALREADY_EXISTS")
                if not _resource_is_absent(kind, result):
                    raise GateError("RUN_RESOURCE_INSPECTION_FAILED")
                self.evidence.checks[f"preflight-absent:{kind}:{name}"] = True

    def _remember(self, kind: str, name: str) -> None:
        item = (kind, name)
        if item not in self._attempted:
            self._attempted.append(item)

    def _create_resources(self) -> None:
        label_args = [
            "--label",
            self.ownership_labels[0],
            "--label",
            self.ownership_labels[1],
        ]
        self._remember("network", self.names.network)
        self._run_command(
            [
                "docker",
                "network",
                "create",
                "--internal",
                *label_args,
                self.names.network,
            ],
            step="create-network",
        )
        for volume in self.names.volumes:
            self._remember("volume", volume)
            self._run_command(
                ["docker", "volume", "create", *label_args, volume],
                step=f"create-volume-{volume}",
            )

        self._remember("container", self.names.postgres_container)
        self._run_command(
            self._postgres_run_command(),
            step="start-postgres",
            timeout=90,
        )
        self._remember("container", self.names.qwenpaw_container)
        self._run_command(
            self._qwenpaw_run_command(),
            step="start-qwenpaw",
            timeout=90,
        )
        self.evidence.checks["isolated-topology"] = {
            "container_count": 2,
            "sidecar_started": False,
            "model_mount_count": 0,
            "token_mount_count": 0,
            "host_bind_mount_count": 0,
            "postgres_host_port": False,
            "qwenpaw_host_port": False,
            "network_internal": True,
            "outbound_network_route": False,
        }

    def _postgres_run_command(self) -> list[str]:
        labels = self.ownership_labels
        return [
            "docker",
            "run",
            "--detach",
            "--name",
            self.names.postgres_container,
            "--label",
            labels[0],
            "--label",
            labels[1],
            "--restart",
            "no",
            "--network",
            self.names.network,
            "--network-alias",
            DATABASE_HOST_ALIAS,
            "--env",
            f"POSTGRES_DB={DATABASE_NAME}",
            "--env",
            f"POSTGRES_USER={DATABASE_USER}",
            "--env",
            f"POSTGRES_PASSWORD={self.database_password}",
            "--mount",
            f"type=volume,src={self.names.postgres_data},dst=/var/lib/postgresql",
            POSTGRES_IMAGE,
        ]

    def _qwenpaw_run_command(self) -> list[str]:
        labels = self.ownership_labels
        encoded_password = quote(self.database_password, safe="")
        database_url = (
            f"postgresql+psycopg://{DATABASE_USER}:{encoded_password}@"
            f"{DATABASE_HOST_ALIAS}:5432/{DATABASE_NAME}"
        )
        return [
            "docker",
            "run",
            "--detach",
            "--name",
            self.names.qwenpaw_container,
            "--label",
            labels[0],
            "--label",
            labels[1],
            "--platform",
            CONTAINER_PLATFORM,
            "--restart",
            "no",
            "--network",
            self.names.network,
            "--network-alias",
            "qwenpaw",
            "--env",
            "TZ=Asia/Shanghai",
            "--env",
            f"AI_NOVEL_DATABASE_URL={database_url}",
            "--env",
            "AI_NOVEL_TTS_RUNTIME_ENABLED=false",
            "--env",
            "AI_NOVEL_TTS_PRODUCT_ENABLED=false",
            "--env",
            "AI_NOVEL_TTS_VALIDATION_ENABLED=false",
            "--env",
            "AI_NOVEL_TTS_REFERENCE_CLONE_ENABLED=false",
            "--env",
            "PIP_NO_INDEX=1",
            "--env",
            "PIP_DISABLE_PIP_VERSION_CHECK=1",
            "--mount",
            f"type=volume,src={self.names.qwenpaw_data},dst=/app/working",
            "--mount",
            f"type=volume,src={self.names.qwenpaw_secrets},dst=/app/working.secret",
            "--mount",
            f"type=volume,src={self.names.qwenpaw_backups},dst=/app/working.backups",
            "--mount",
            (
                f"type=volume,src={self.names.novel_media},"
                "dst=/app/working/ai-novel-world-2026/novel-media"
            ),
            QWENPAW_IMAGE,
        ]

    def _candidate_copy_command(self) -> list[str]:
        source_contents = f"{self.config.candidate}{os.sep}."
        return [
            "docker",
            "cp",
            source_contents,
            f"{self.names.qwenpaw_container}:/gate/candidate",
        ]

    def _stage_candidate(self) -> None:
        self._run_command(
            [
                "docker",
                "exec",
                "--user",
                "0:0",
                self.names.qwenpaw_container,
                "/bin/sh",
                "-lc",
                (
                    "test ! -e /gate/candidate && "
                    "umask 022 && mkdir -p /gate/candidate"
                ),
            ],
            step="prepare-candidate-staging-directory",
        )
        self._run_command(
            self._candidate_copy_command(),
            step="docker-cp-candidate",
            timeout=120,
        )
        staged_digest = self._read_staged_candidate_digest(
            step="hash-staged-candidate"
        )
        self.evidence.checks["candidate-staging"] = {
            "method": "docker-cp",
            "container_path": "/gate/candidate",
            "tree_sha256": staged_digest,
            "host_bind_mount_count": 0,
            "helper_container_count": 0,
            "host_copy_detached": True,
            "integrity_rechecked_before_each_install": True,
        }

    def _read_staged_candidate_digest(self, *, step: str) -> str:
        digest_program = (
            "from pathlib import Path; import hashlib; "
            "root=Path('/gate/candidate'); digest=hashlib.sha256(); "
            "paths=sorted(root.rglob('*'), key=lambda p:p.relative_to(root).as_posix()); "
            "assert paths; "
            "assert all(not p.is_symlink() for p in paths); "
            "[(lambda rel,data: (digest.update(rel.encode('utf-8')), "
            "digest.update(b'\\0'), digest.update(data), digest.update(b'\\0')))"
            "(p.relative_to(root).as_posix(), p.read_bytes()) for p in paths "
            "if p.is_file() and not p.is_symlink()]; "
            "assert all((p.is_dir() or (p.is_file() and not p.is_symlink())) "
            "for p in paths); print(digest.hexdigest())"
        )
        result = self._run_command(
            [
                "docker",
                "exec",
                self.names.qwenpaw_container,
                "/app/venv/bin/python",
                "-c",
                digest_program,
            ],
            step=step,
            timeout=120,
        )
        staged_digest = result.stdout.strip()
        expected_digest = self.config.candidate_tree_sha256
        if not expected_digest or staged_digest != expected_digest:
            raise GateError("STAGED_CANDIDATE_DIGEST_MISMATCH")
        return staged_digest

    def _wait_for_services(self) -> None:
        deadline = self.monotonic() + self.config.startup_timeout_seconds
        attempts = 0
        while self.monotonic() < deadline:
            attempts += 1
            result = self.executor.run(
                [
                    "docker",
                    "exec",
                    self.names.postgres_container,
                    "pg_isready",
                    "-U",
                    DATABASE_USER,
                    "-d",
                    DATABASE_NAME,
                ],
                timeout=10,
                check=False,
            )
            if result.returncode == 0:
                break
            self.sleep(1)
        else:
            raise GateError("POSTGRES_STARTUP_TIMEOUT")
        self.evidence.checks["postgres-ready"] = {"attempts": attempts}

        # Docker Desktop does not publish ports from an --internal network.
        # Probe QwenPaw's public HTTP contract from its own loopback instead;
        # this preserves full network isolation and requires no helper client.
        self.base_url = "http://127.0.0.1:8088"

        deadline = self.monotonic() + self.config.startup_timeout_seconds
        attempts = 0
        while self.monotonic() < deadline:
            attempts += 1
            try:
                status, payload = self._raw_http_json("GET", "/api/plugins")
                if status == 200 and isinstance(payload, list):
                    break
            except GateError:
                pass
            self.sleep(1)
        else:
            raise GateError("QWENPAW_STARTUP_TIMEOUT")
        self.evidence.checks["qwenpaw-ready"] = {"attempts": attempts}
        self._verify_runtime_topology()

    def _verify_runtime_topology(self) -> None:
        internal = self._run_command(
            [
                "docker",
                "network",
                "inspect",
                "--format",
                "{{.Internal}}",
                self.names.network,
            ],
            step="verify-internal-network",
        )
        if internal.stdout.strip().lower() != "true":
            raise GateError("GATE_NETWORK_NOT_INTERNAL")
        labeled = self._run_command(
            [
                "docker",
                "container",
                "ls",
                "--all",
                "--filter",
                f"label={RUN_LABEL_KEY}={self.config.run_id}",
                "--filter",
                f"label={GATE_LABEL_KEY}={GATE_LABEL_VALUE}",
                "--format",
                "{{.Names}}",
            ],
            step="list-owned-containers",
        )
        owned_containers = {
            line.strip() for line in labeled.stdout.splitlines() if line.strip()
        }
        if owned_containers != set(self.names.containers):
            raise GateError("OWNED_CONTAINER_TOPOLOGY_INVALID")
        result = self._run_command(
            ["docker", "container", "inspect", self.names.qwenpaw_container],
            step="inspect-qwenpaw-topology",
        )
        try:
            payload = json.loads(result.stdout)
            record = payload[0]
            env = record["Config"]["Env"]
            mounts = record["Mounts"]
            networks = record["NetworkSettings"]["Networks"]
            ports = record["NetworkSettings"]["Ports"]
            port_bindings = record["HostConfig"]["PortBindings"]
        except (IndexError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise GateError("QWENPAW_INSPECT_SHAPE_INVALID") from error
        if not isinstance(env, list) or env.count("AI_NOVEL_TTS_RUNTIME_ENABLED=false") != 1:
            raise GateError("TTS_RUNTIME_NOT_EXPLICITLY_DISABLED")
        if env.count("AI_NOVEL_TTS_PRODUCT_ENABLED=false") != 1:
            raise GateError("TTS_PRODUCT_NOT_EXPLICITLY_DISABLED")
        if env.count("AI_NOVEL_TTS_VALIDATION_ENABLED=false") != 1:
            raise GateError("TTS_VALIDATION_NOT_EXPLICITLY_DISABLED")
        if env.count("AI_NOVEL_TTS_REFERENCE_CLONE_ENABLED=false") != 1:
            raise GateError("TTS_REFERENCE_CLONE_NOT_EXPLICITLY_DISABLED")
        if any(
            str(item).startswith(
                (
                    "AI_NOVEL_TTS_MODEL_METADATA_ROOT=",
                    "AI_NOVEL_TTS_MEDIA_ROOT=",
                )
            )
            for item in env
        ):
            raise GateError("TTS_STORAGE_ROOT_ENV_PRESENT")
        if env.count("PIP_NO_INDEX=1") != 1 or env.count("PIP_DISABLE_PIP_VERSION_CHECK=1") != 1:
            raise GateError("PACKAGE_INDEX_NOT_DISABLED")
        if any(str(item).startswith("MOSS_TTS_") for item in env):
            raise GateError("TTS_CONTROL_ENV_PRESENT")
        if not isinstance(mounts, list):
            raise GateError("QWENPAW_INSPECT_SHAPE_INVALID")
        destinations = {str(item.get("Destination")) for item in mounts if isinstance(item, dict)}
        if "/run/moss-tts-secrets" in destinations or "/opt/moss-assets" in destinations:
            raise GateError("TTS_SECRET_OR_MODEL_MOUNT_PRESENT")
        if any(
            isinstance(item, dict) and item.get("Type") == "bind"
            for item in mounts
        ):
            raise GateError("HOST_BIND_MOUNT_PRESENT")
        if "/gate/candidate" in destinations:
            raise GateError("CANDIDATE_MUST_NOT_BE_A_MOUNT")
        if set(networks) != {self.names.network}:
            raise GateError("QWENPAW_NETWORK_NOT_ISOLATED")
        if not isinstance(ports, dict) or any(ports.values()):
            raise GateError("QWENPAW_HOST_PORT_PRESENT")
        if not isinstance(port_bindings, dict) or any(port_bindings.values()):
            raise GateError("QWENPAW_HOST_PORT_PRESENT")
        self.evidence.checks["tts-disabled-by-construction"] = {
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

    def _install(self, *, force: bool, step: str) -> None:
        self._read_staged_candidate_digest(step=f"verify-candidate-before-{step}")
        status, payload = self._http_json(
            "POST",
            "/api/plugins/install",
            body={"source": "/gate/candidate", "force": force},
            expected_statuses=(200,),
            step=step,
        )
        if (
            status != 200
            or not isinstance(payload, dict)
            or payload.get("id") != APP_ID
            or payload.get("version") != APP_VERSION
            or payload.get("loaded") is not True
        ):
            raise GateError("PUBLIC_INSTALL_RESPONSE_INVALID")

    def _migrate_and_verify_head(self) -> None:
        plugin_dir = f"/app/working/plugins/{APP_ID}"
        self._run_command(
            [
                "docker",
                "exec",
                "--env",
                "AI_NOVEL_TTS_RUNTIME_ENABLED=false",
                "--env",
                "AI_NOVEL_TTS_PRODUCT_ENABLED=false",
                "--env",
                "AI_NOVEL_TTS_VALIDATION_ENABLED=false",
                "--env",
                "AI_NOVEL_TTS_REFERENCE_CLONE_ENABLED=false",
                self.names.qwenpaw_container,
                "/bin/sh",
                "-lc",
                (
                    f"cd {plugin_dir} && "
                    "/app/venv/bin/python -m alembic -c alembic.ini upgrade head"
                ),
            ],
            step="migrate-plugin-to-head",
            timeout=180,
        )
        result = self._run_command(
            [
                "docker",
                "exec",
                self.names.postgres_container,
                "psql",
                "-U",
                DATABASE_USER,
                "-d",
                DATABASE_NAME,
                "-Atqc",
                "SELECT version_num FROM alembic_version",
            ],
            step="read-migration-head",
        )
        if result.stdout.strip() != EXPECTED_MIGRATION_HEAD:
            raise GateError("MIGRATION_HEAD_MISMATCH")
        self.evidence.checks["migration-head"] = EXPECTED_MIGRATION_HEAD

    def _wait_for_installed_contract(self) -> RegistrySnapshot:
        deadline = self.monotonic() + self.config.registry_timeout_seconds
        last_error: GateError | None = None
        while self.monotonic() < deadline:
            try:
                return self._verify_installed_contract()
            except GateError as error:
                last_error = error
                self.sleep(0.5)
        raise GateError(
            "INSTALLED_CONTRACT_TIMEOUT",
            last_error.code if last_error else "",
        )

    def _verify_installed_contract(self) -> RegistrySnapshot:
        plugins = self._get_list("/api/plugins", step="list-plugins-installed")
        plugin_matches = [item for item in plugins if item.get("id") == APP_ID]
        if len(plugin_matches) != 1:
            raise GateError("PLUGIN_REGISTRY_CARDINALITY_INVALID")
        plugin = plugin_matches[0]
        if plugin.get("version") != APP_VERSION or plugin.get("loaded") is not True:
            raise GateError("PLUGIN_REGISTRY_CONTRACT_INVALID")

        _, pawapps_payload = self._http_json(
            "GET", "/api/pawapps", expected_statuses=(200,), step="list-pawapps-installed"
        )
        if not isinstance(pawapps_payload, dict) or not isinstance(pawapps_payload.get("apps"), list):
            raise GateError("PAWAPP_LIST_SHAPE_INVALID")
        pawapps = [item for item in pawapps_payload["apps"] if isinstance(item, dict)]
        pawapp_matches = [item for item in pawapps if item.get("id") == APP_ID]
        if len(pawapp_matches) != 1 or pawapp_matches[0].get("version") != APP_VERSION:
            raise GateError("PAWAPP_REGISTRY_CARDINALITY_INVALID")

        frontend_status, frontend_bytes = self._http_bytes(
            "GET",
            f"/api/plugins/{APP_ID}/files/frontend/dist/index.js",
            expected_statuses=(200,),
            step="frontend-asset-installed",
        )
        if frontend_status != 200 or not frontend_bytes:
            raise GateError("FRONTEND_ASSET_NOT_AVAILABLE")

        status, health = self._http_json(
            "GET",
            f"/api/{APP_ID}/health",
            expected_statuses=(200,),
            step="app-health-installed",
        )
        if status != 200 or not isinstance(health, dict):
            raise GateError("APP_HEALTH_INVALID")
        if health.get("app_id") != APP_ID or health.get("version") != APP_VERSION:
            raise GateError("APP_HEALTH_IDENTITY_INVALID")
        if health.get("narration") != EXPECTED_DISABLED_NARRATION:
            raise GateError("NARRATION_DISABLED_CONTRACT_INVALID")
        if (
            health.get("narration_production")
            != EXPECTED_DISABLED_NARRATION_PRODUCTION
        ):
            raise GateError("NARRATION_PRODUCTION_DISABLED_CONTRACT_INVALID")
        self.evidence.checks["narration-disabled"] = dict(EXPECTED_DISABLED_NARRATION)
        self.evidence.checks["narration-production-disabled"] = dict(
            EXPECTED_DISABLED_NARRATION_PRODUCTION
        )
        self._verify_t4_routes_disabled_without_token()

        snapshot = self._registry_snapshot()
        if not snapshot.agent_ids:
            raise GateError("NO_NATIVE_AGENT_AVAILABLE")
        for agent_id in snapshot.agent_ids:
            if set(snapshot.skills_by_agent[agent_id]) != NOVEL_SKILLS:
                raise GateError("PLUGIN_SKILL_REGISTRY_INVALID")
            if set(snapshot.tools_by_agent[agent_id]) != NOVEL_TOOLS:
                raise GateError("PLUGIN_TOOL_REGISTRY_INVALID")
        self.evidence.checks["installed-registry"] = snapshot.as_dict()
        return snapshot

    def _verify_t4_routes_disabled_without_token(self) -> None:
        checks: dict[str, object] = {}
        for route_class, path in T4_DISABLED_ROUTE_PROBES:
            status, cache_control, payload = self._raw_http_response(
                "GET",
                path,
            )
            self.evidence.checks[
                f"http:t4-{route_class}-disabled-without-token"
            ] = {
                "method": "GET",
                "path": path,
                "status": status,
                "cache_control": cache_control,
                "response_bytes": len(payload),
                "response_sha256": _sha256_bytes(payload),
                "validation_token_sent": False,
            }
            if status != 404 or cache_control != "no-store":
                raise GateError("T4_DISABLED_ROUTE_CONTRACT_INVALID", route_class)
            checks[route_class] = {
                "status": 404,
                "cache_control": "no-store",
                "validation_token_sent": False,
            }
        self.evidence.checks["t4-routes-disabled-without-token"] = checks

    def _wait_for_uninstalled_contract(self) -> None:
        deadline = self.monotonic() + self.config.registry_timeout_seconds
        last_error: GateError | None = None
        while self.monotonic() < deadline:
            try:
                self._verify_uninstalled_contract()
                return
            except GateError as error:
                last_error = error
                self.sleep(0.5)
        raise GateError(
            "UNINSTALLED_CONTRACT_TIMEOUT",
            last_error.code if last_error else "",
        )

    def _verify_uninstalled_contract(self) -> None:
        plugins = self._get_list("/api/plugins", step="list-plugins-uninstalled")
        if any(item.get("id") == APP_ID for item in plugins):
            raise GateError("PLUGIN_RESIDUE_PRESENT")
        _, pawapps_payload = self._http_json(
            "GET", "/api/pawapps", expected_statuses=(200,), step="list-pawapps-uninstalled"
        )
        if not isinstance(pawapps_payload, dict) or not isinstance(pawapps_payload.get("apps"), list):
            raise GateError("PAWAPP_LIST_SHAPE_INVALID")
        if any(
            isinstance(item, dict) and item.get("id") == APP_ID
            for item in pawapps_payload["apps"]
        ):
            raise GateError("PAWAPP_RESIDUE_PRESENT")
        snapshot = self._registry_snapshot()
        if not snapshot.agent_ids:
            raise GateError("NATIVE_AGENT_REGRESSION")
        if any(snapshot.skills_by_agent[agent_id] for agent_id in snapshot.agent_ids):
            raise GateError("PLUGIN_SKILL_RESIDUE_PRESENT")
        if any(snapshot.tools_by_agent[agent_id] for agent_id in snapshot.agent_ids):
            raise GateError("PLUGIN_TOOL_RESIDUE_PRESENT")

        for path, step in (
            (f"/api/{APP_ID}/health", "health-route-removed"),
            (f"/api/{APP_ID}/novels", "novel-route-removed"),
            (f"/api/plugins/{APP_ID}/status", "plugin-status-removed"),
            (f"/api/pawapps/{APP_ID}", "pawapp-detail-removed"),
            (
                f"/api/plugins/{APP_ID}/files/frontend/dist/index.js",
                "frontend-static-route-removed",
            ),
        ):
            status, _ = self._http_bytes(
                "GET", path, expected_statuses=(404,), step=step
            )
            if status != 404:
                raise GateError("PLUGIN_ROUTE_RESIDUE_PRESENT")

        # /frontend_plugin is QwenPaw's native SPA shell, not a JSON plugin
        # registry.  It must remain responsive after uninstall; plugin-owned
        # frontend residue is proved absent by the /api/plugins/.../files 404.
        shell_status, shell_bytes = self._http_bytes(
            "GET",
            "/frontend_plugin",
            expected_statuses=(200,),
            step="native-frontend-shell-after-uninstall",
        )
        if shell_status != 200 or not shell_bytes:
            raise GateError("NATIVE_FRONTEND_ROUTE_REGRESSION")

        result = self._run_command(
            [
                "docker",
                "exec",
                self.names.qwenpaw_container,
                "test",
                "!",
                "-e",
                f"/app/working/plugins/{APP_ID}",
            ],
            step="plugin-directory-removed",
        )
        if result.returncode != 0:
            raise GateError("PLUGIN_DIRECTORY_RESIDUE_PRESENT")

        # Native public APIs remain responsive after the plugin is removed.
        for path in ("/api/agents", "/api/skills", "/api/tools"):
            headers: dict[str, str] | None = None
            if path != "/api/agents":
                headers = {"X-Agent-Id": snapshot.agent_ids[0]}
            status, _ = self._http_json(
                "GET",
                path,
                headers=headers,
                expected_statuses=(200,),
                step=f"native-route-{path.rsplit('/', 1)[-1]}",
            )
            if status != 200:
                raise GateError("NATIVE_ROUTE_REGRESSION")
        self.evidence.checks["uninstalled-zero-residue"] = snapshot.as_dict()

    def _registry_snapshot(self) -> RegistrySnapshot:
        _, agents_payload = self._http_json(
            "GET", "/api/agents", expected_statuses=(200,), step="list-agents"
        )
        if not isinstance(agents_payload, dict) or not isinstance(agents_payload.get("agents"), list):
            raise GateError("AGENT_LIST_SHAPE_INVALID")
        agent_ids = tuple(
            sorted(
                {
                    str(item.get("id"))
                    for item in agents_payload["agents"]
                    if isinstance(item, dict) and str(item.get("id") or "").strip()
                }
            )
        )
        skills_by_agent: dict[str, tuple[str, ...]] = {}
        tools_by_agent: dict[str, tuple[str, ...]] = {}
        for agent_id in agent_ids:
            headers = {"X-Agent-Id": agent_id}
            skills = self._get_list(
                "/api/skills", headers=headers, step=f"list-skills-{_sha256_text(agent_id)[:8]}"
            )
            skills_by_agent[agent_id] = tuple(
                sorted(
                    {
                        str(item.get("name"))
                        for item in skills
                        if item.get("source") == f"plugin:{APP_ID}"
                        and str(item.get("name") or "")
                    }
                )
            )
            tools = self._get_list(
                "/api/tools", headers=headers, step=f"list-tools-{_sha256_text(agent_id)[:8]}"
            )
            tools_by_agent[agent_id] = tuple(
                sorted(
                    {
                        str(item.get("name"))
                        for item in tools
                        if str(item.get("name") or "") in NOVEL_TOOLS
                    }
                )
            )
        return RegistrySnapshot(agent_ids, skills_by_agent, tools_by_agent)

    def _create_sentinels(self) -> dict[str, str]:
        title = f"T1 lifecycle sentinel {self.config.run_id}"
        description = "Disposable isolated validation row"
        status, novel = self._http_json(
            "POST",
            f"/api/{APP_ID}/novels",
            body={"title": title, "description": description},
            expected_statuses=(201,),
            step="create-db-sentinel",
        )
        if status != 201 or not isinstance(novel, dict):
            raise GateError("DB_SENTINEL_CREATE_FAILED")
        novel_id = str(novel.get("id") or "")
        if SAFE_UUID_RE.fullmatch(novel_id) is None or novel.get("title") != title:
            raise GateError("DB_SENTINEL_RESPONSE_INVALID")

        paths = {
            "working": "/app/working/.t1-gate-sentinel",
            "secrets_volume": "/app/working.secret/.t1-gate-sentinel",
            "backups": "/app/working.backups/.t1-gate-sentinel",
            "media": (
                "/app/working/ai-novel-world-2026/novel-media/"
                ".t1-gate-sentinel"
            ),
        }
        content = f"T1 disposable sentinel\n{self.config.run_id}\n"
        program = (
            "from pathlib import Path; "
            f"paths={list(paths.values())!r}; content={content!r}; "
            "[(Path(p).parent.mkdir(parents=True, exist_ok=True), "
            "Path(p).write_text(content, encoding='utf-8')) for p in paths]"
        )
        self._run_command(
            [
                "docker",
                "exec",
                self.names.qwenpaw_container,
                "/app/venv/bin/python",
                "-c",
                program,
            ],
            step="create-volume-sentinels",
        )
        expected_file_hash = _sha256_text(content)
        db_digest = self._database_sentinel_digest(novel_id)
        sentinels = {
            "novel_id": novel_id,
            "db_digest": db_digest,
            "file_digest": expected_file_hash,
            **{f"path:{name}": path for name, path in paths.items()},
        }
        self.evidence.checks["sentinels-created"] = {
            "db_digest": db_digest,
            "file_digest": expected_file_hash,
            "volume_sentinel_count": len(paths),
        }
        return sentinels

    def _database_sentinel_digest(self, novel_id: str) -> str:
        if SAFE_UUID_RE.fullmatch(novel_id) is None:
            raise GateError("DB_SENTINEL_ID_INVALID")
        query = (
            "SELECT id::text, title, COALESCE(description, '') "
            f"FROM novels WHERE id = '{novel_id}'::uuid"
        )
        result = self._run_command(
            [
                "docker",
                "exec",
                self.names.postgres_container,
                "psql",
                "-U",
                DATABASE_USER,
                "-d",
                DATABASE_NAME,
                "-At",
                "-F",
                "|",
                "-c",
                query,
            ],
            step="read-db-sentinel",
        )
        value = result.stdout.strip()
        if not value.startswith(f"{novel_id}|"):
            raise GateError("DB_SENTINEL_MISSING")
        return _sha256_text(value)

    def _verify_sentinels(self, sentinels: Mapping[str, str]) -> None:
        novel_id = sentinels["novel_id"]
        if self._database_sentinel_digest(novel_id) != sentinels["db_digest"]:
            raise GateError("DB_SENTINEL_CHANGED")
        paths = [value for key, value in sentinels.items() if key.startswith("path:")]
        result = self._run_command(
            [
                "docker",
                "exec",
                self.names.qwenpaw_container,
                "sha256sum",
                *paths,
            ],
            step="read-volume-sentinels",
        )
        rows = [line.split() for line in result.stdout.splitlines() if line.strip()]
        if len(rows) != len(paths):
            raise GateError("VOLUME_SENTINEL_MISSING")
        if any(len(row) < 2 or row[0] != sentinels["file_digest"] for row in rows):
            raise GateError("VOLUME_SENTINEL_CHANGED")
        self.evidence.checks["sentinels-preserved"] = {
            "db_digest": sentinels["db_digest"],
            "file_digest": sentinels["file_digest"],
            "volume_sentinel_count": len(paths),
        }

    def _verify_novel_route(self, novel_id: str) -> None:
        status, novel = self._http_json(
            "GET",
            f"/api/{APP_ID}/novels/{novel_id}",
            expected_statuses=(200,),
            step="read-db-sentinel-after-reinstall",
        )
        if status != 200 or not isinstance(novel, dict) or str(novel.get("id")) != novel_id:
            raise GateError("DB_SENTINEL_ROUTE_NOT_RESTORED")

    def _get_list(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        step: str,
    ) -> list[dict[str, Any]]:
        _, payload = self._http_json(
            "GET", path, headers=headers, expected_statuses=(200,), step=step
        )
        if not isinstance(payload, list):
            raise GateError("PUBLIC_LIST_SHAPE_INVALID")
        return [item for item in payload if isinstance(item, dict)]

    def _raw_http_response(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, object] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> tuple[int, str | None, bytes]:
        if self.base_url != "http://127.0.0.1:8088":
            raise GateError("HTTP_BASE_URL_NOT_ISOLATED")
        if not path.startswith("/") or "\r" in path or "\n" in path:
            raise GateError("HTTP_PATH_INVALID")
        request_headers = {"Accept": "application/json"}
        if headers:
            for key, value in headers.items():
                if key.lower() not in {"x-agent-id"}:
                    raise GateError("HTTP_HEADER_NOT_ALLOWED")
                request_headers[key] = value
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        body_json = json.dumps(
            body, ensure_ascii=True, separators=(",", ":")
        )
        headers_json = json.dumps(
            request_headers, ensure_ascii=True, separators=(",", ":")
        )
        probe_program = (
            "import base64,json,sys,urllib.error,urllib.request; "
            "method,path,body_json,headers_json=sys.argv[1:5]; "
            "body=json.loads(body_json); headers=json.loads(headers_json); "
            "data=None if body is None else json.dumps(body,ensure_ascii=True,"
            "separators=(',',':')).encode('utf-8'); "
            "request=urllib.request.Request('http://127.0.0.1:8088'+path,"
            "data=data,headers=headers,method=method); "
            "status=0; raw=b''; cache_control=None; "
            "exec(\"try:\\n response=urllib.request.urlopen(request,timeout=15)\\n"
            " status=int(response.status)\\n"
            " cache_control=response.headers.get('Cache-Control')\\n"
            " raw=response.read()\\n response.close()\\n"
            "except urllib.error.HTTPError as error:\\n status=int(error.code)\\n"
            " cache_control=error.headers.get('Cache-Control')\\n"
            " raw=error.read()\"); "
            "print(json.dumps({'status':status,'cache_control':cache_control,"
            "'body_base64':"
            "base64.b64encode(raw).decode('ascii')},separators=(',',':')))"
        )
        transport_step = (
            f"container-http-{method.lower()}-{_sha256_text(path)[:12]}"
        )
        result = self._run_command(
            [
                "docker",
                "exec",
                self.names.qwenpaw_container,
                "/app/venv/bin/python",
                "-c",
                probe_program,
                method,
                path,
                body_json,
                headers_json,
            ],
            step=transport_step,
            timeout=30,
        )
        try:
            wrapper = json.loads(result.stdout)
            status = int(wrapper["status"])
            cache_control = wrapper["cache_control"]
            raw = base64.b64decode(wrapper["body_base64"], validate=True)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise GateError("HTTP_TRANSPORT_RESPONSE_INVALID") from error
        if (
            cache_control is not None
            and (
                not isinstance(cache_control, str)
                or "\r" in cache_control
                or "\n" in cache_control
            )
        ):
            raise GateError("HTTP_TRANSPORT_RESPONSE_INVALID")
        return status, cache_control, raw

    def _raw_http_bytes(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, object] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> tuple[int, bytes]:
        status, _cache_control, raw = self._raw_http_response(
            method,
            path,
            body=body,
            headers=headers,
        )
        return status, raw

    def _raw_http_json(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, object] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> tuple[int, object | None]:
        status, raw = self._raw_http_bytes(
            method, path, body=body, headers=headers
        )
        if not raw:
            return status, None
        try:
            return status, json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise GateError("HTTP_RESPONSE_NOT_JSON") from error

    def _http_bytes(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, object] | None = None,
        headers: Mapping[str, str] | None = None,
        expected_statuses: Sequence[int],
        step: str,
    ) -> tuple[int, bytes]:
        status, payload = self._raw_http_bytes(
            method, path, body=body, headers=headers
        )
        self.evidence.checks[f"http:{step}"] = {
            "method": method,
            "path": path,
            "status": status,
            "response_bytes": len(payload),
            "response_sha256": _sha256_bytes(payload),
        }
        if status not in expected_statuses:
            raise GateError("HTTP_STATUS_UNEXPECTED", step)
        return status, payload

    def _http_json(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, object] | None = None,
        headers: Mapping[str, str] | None = None,
        expected_statuses: Sequence[int],
        step: str,
    ) -> tuple[int, object | None]:
        status, payload = self._raw_http_json(method, path, body=body, headers=headers)
        self.evidence.checks[f"http:{step}"] = {
            "method": method,
            "path": path,
            "status": status,
            "response_sha256": _sha256_text(
                json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
            ),
        }
        if status not in expected_statuses:
            raise GateError("HTTP_STATUS_UNEXPECTED", step)
        return status, payload

    def _cleanup(self) -> None:
        removed: list[str] = []
        skipped_absent: list[str] = []
        failures: list[str] = []
        for kind, name in reversed(self._attempted):
            inspect = self.executor.run(
                [
                    "docker",
                    kind,
                    "inspect",
                    "--format",
                    f"{{{{ index .Config.Labels \"{RUN_LABEL_KEY}\" }}}}|"
                    f"{{{{ index .Config.Labels \"{GATE_LABEL_KEY}\" }}}}",
                    name,
                ] if kind == "container" else [
                    "docker",
                    kind,
                    "inspect",
                    "--format",
                    f"{{{{ index .Labels \"{RUN_LABEL_KEY}\" }}}}|"
                    f"{{{{ index .Labels \"{GATE_LABEL_KEY}\" }}}}",
                    name,
                ],
                timeout=15,
                check=False,
            )
            if inspect.returncode != 0:
                if _resource_is_absent(kind, inspect):
                    skipped_absent.append(f"{kind}:{name}")
                else:
                    failures.append(f"inspect-failed:{kind}:{name}")
                continue
            expected = f"{self.config.run_id}|{GATE_LABEL_VALUE}"
            if inspect.stdout.strip() != expected:
                failures.append(f"foreign-label:{kind}:{name}")
                continue
            if kind == "container":
                argv = ["docker", "container", "rm", "--force", name]
            elif kind == "volume":
                argv = ["docker", "volume", "rm", name]
            elif kind == "network":
                argv = ["docker", "network", "rm", name]
            else:
                failures.append(f"unknown-kind:{kind}:{name}")
                continue
            result = self.executor.run(argv, timeout=45, check=False)
            if result.returncode == 0:
                removed.append(f"{kind}:{name}")
            else:
                failures.append(f"remove-failed:{kind}:{name}")
        self.evidence.cleanup = {
            "status": "passed" if not failures else "failed",
            "removed_exact_resources": removed,
            "already_absent": skipped_absent,
            "failures": failures,
            "broad_cleanup_used": False,
        }
        if failures:
            raise GateError("EXACT_CLEANUP_FAILED")

    def _write_transcript(self) -> None:
        if self.config.transcript is None:
            return
        target = self.config.transcript
        if not target.is_absolute():
            raise GateError("TRANSCRIPT_PATH_MUST_BE_ABSOLUTE")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{self.config.run_id}.tmp")
        payload = json.dumps(
            self.evidence.as_dict(), ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        descriptor = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.link(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify an isolated QwenPaw plugin lifecycle without formal resources."
    )
    parser.add_argument("--mode", choices=("dry-run", "real"), default="dry-run")
    parser.add_argument(
        "--candidate",
        type=Path,
        default=DEFAULT_CANDIDATE,
        help="Absolute path to a prebuilt candidate directory.",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="8-20 lowercase alphanumeric characters; generated when omitted.",
    )
    parser.add_argument("--transcript", type=Path, default=None)
    parser.add_argument("--confirm", default=None)
    parser.add_argument("--startup-timeout-seconds", type=int, default=180)
    parser.add_argument("--registry-timeout-seconds", type=int, default=45)
    return parser


def _validated_config(arguments: argparse.Namespace) -> tuple[GateConfig, str]:
    run_id = arguments.run_id or uuid.uuid4().hex[:12]
    create_resource_names(run_id)
    candidate, candidate_digest = validate_candidate(arguments.candidate)
    if arguments.startup_timeout_seconds < 30 or arguments.startup_timeout_seconds > 900:
        raise GateError("STARTUP_TIMEOUT_OUT_OF_RANGE")
    if arguments.registry_timeout_seconds < 10 or arguments.registry_timeout_seconds > 300:
        raise GateError("REGISTRY_TIMEOUT_OUT_OF_RANGE")
    if arguments.mode == "real" and arguments.confirm != REAL_CONFIRMATION:
        raise GateError("REAL_MODE_CONFIRMATION_REQUIRED")
    if arguments.transcript is not None and not arguments.transcript.is_absolute():
        raise GateError("TRANSCRIPT_PATH_MUST_BE_ABSOLUTE")
    if arguments.transcript is not None and arguments.transcript.exists():
        raise GateError("TRANSCRIPT_ALREADY_EXISTS")
    return (
        GateConfig(
            mode=arguments.mode,
            run_id=run_id,
            candidate=candidate,
            transcript=arguments.transcript,
            confirmation=arguments.confirm,
            candidate_tree_sha256=candidate_digest,
            startup_timeout_seconds=arguments.startup_timeout_seconds,
            registry_timeout_seconds=arguments.registry_timeout_seconds,
        ),
        candidate_digest,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    try:
        config, candidate_digest = _validated_config(parser.parse_args(argv))
        names = create_resource_names(config.run_id)
        if config.mode == "dry-run":
            report = build_dry_run_plan(config, names)
            report["candidate"]["tree_sha256"] = candidate_digest
        else:
            gate = LifecycleGate(config, names)
            gate.evidence.checks["candidate-tree-sha256"] = candidate_digest
            report = gate.run()
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except GateError as error:
        print(
            json.dumps(
                {
                    "gate": "T1-GATE-INSTALL",
                    "status": "failed",
                    "failure_code": error.code,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    except Exception:
        print(
            json.dumps(
                {
                    "gate": "T1-GATE-INSTALL",
                    "status": "failed",
                    "failure_code": "UNEXPECTED_VALIDATION_FAILURE",
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
