"""Build, install, verify, or explicitly uninstall the PawApp in the local lab."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.request import Request, urlopen
from uuid import UUID, uuid4


ROOT = Path(__file__).resolve().parents[1]
CONTAINER = os.environ.get("QWENPAW_CONTAINER", "ai-novel-2026-qwenpaw-lab")
BASE_URL = os.environ.get("QWENPAW_BASE_URL", "http://127.0.0.1:18088").rstrip("/")
PLUGIN_ID = "ai-novel-world-2026"
PLUGIN_DIR = ROOT / "build" / PLUGIN_ID
INSTALLER_CONTAINER = f"{CONTAINER}-plugin-installer"
INSTALLER_LABEL_KEY = "ai-novel-world-2026.resource"
INSTALLER_LABEL_VALUE = "qwenpaw-plugin-installer"
PLUGIN_INSTALL_FAILURE_MARKERS = (
    "api install failed",
    "plugin installation failed",
)
TTS_RUNTIME_EXPECTATION_ENV = "QWENPAW_EXPECT_TTS_RUNTIME"
TTS_RUNTIME_EXPECTATIONS = frozenset({"disabled", "ready"})
TTS_PRODUCT_EXPECTATION_ENV = "QWENPAW_EXPECT_TTS_PRODUCT"
TTS_PRODUCT_EXPECTATIONS = frozenset({"disabled", "ready"})
TTS_VALIDATION_EXPECTATION_ENV = "QWENPAW_EXPECT_TTS_VALIDATION"
TTS_VALIDATION_EXPECTATIONS = frozenset({"disabled", "ready"})
TTS_REFERENCE_EXPECTATION_ENV = "QWENPAW_EXPECT_TTS_REFERENCE_CLONE"
TTS_REFERENCE_EXPECTATIONS = frozenset({"disabled", "ready"})
TTS_FRESH_INSTALL_ENV = "QWENPAW_TTS_FRESH_INSTALL"
TTS_DIGEST_KEY_ID_ENV = "QWENPAW_TTS_DIGEST_KEY_ID"
TTS_VALIDATION_HOST_TOKEN_FILE_ENV = "QWENPAW_TTS_VALIDATION_TOKEN_HOST_FILE"
TTS_TECHNICAL_ENABLE_ENV = "AI_NOVEL_TTS_RUNTIME_ENABLED"
TTS_PRODUCT_ENABLE_ENV = "AI_NOVEL_TTS_PRODUCT_ENABLED"
TTS_VALIDATION_ENABLE_ENV = "AI_NOVEL_TTS_VALIDATION_ENABLED"
TTS_REFERENCE_ENABLE_ENV = "AI_NOVEL_TTS_REFERENCE_CLONE_ENABLED"
TTS_VALIDATION_NOVEL_ID_ENV = "AI_NOVEL_TTS_VALIDATION_NOVEL_ID"
TTS_VALIDATION_DOCUMENT_ID_ENV = "AI_NOVEL_TTS_VALIDATION_DOCUMENT_ID"
TTS_VALIDATION_EXPIRES_AT_ENV = "AI_NOVEL_TTS_VALIDATION_EXPIRES_AT"
INSTALLED_PLUGIN_DIR = f"/app/working/plugins/{PLUGIN_ID}"
INSTALLED_DIGEST_KEYRING_PATH = (
    "/app/working.secret/ai-novel-world-2026/narration-hmac-keyring.json"
)
VOLUMES = (
    "ai-novel-2026-qwenpaw-data:/app/working",
    "ai-novel-2026-qwenpaw-secrets:/app/working.secret",
    "ai-novel-2026-qwenpaw-backups:/app/working.backups",
)


def run(
    *args: str,
    cwd: Path = ROOT,
    capture: bool = False,
    capture_stderr: bool = False,
    timeout_seconds: float | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    if capture_stderr and not capture:
        raise ValueError("capture_stderr requires capture=True")
    completed = subprocess.run(
        args,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture_stderr else None,
        timeout=timeout_seconds,
        env=None if environ is None else dict(environ),
    )
    return completed.stdout.strip() if capture else ""


def pnpm_bin() -> str:
    configured = os.environ.get("PNPM_BIN")
    resolved = configured or shutil.which("pnpm")
    if not resolved:
        raise RuntimeError("pnpm not found; set PNPM_BIN or install the pinned pnpm version")
    return resolved


def pnpm_environment(pnpm: str) -> dict[str, str]:
    """Return an environment where a discovered pnpm can also execute Node."""

    environment = dict(os.environ)
    current_path = environment.get("PATH", "")
    existing = shutil.which("node", path=current_path)
    if existing:
        return environment

    candidates: list[Path] = []
    configured = environment.get("NODE_BIN")
    if configured:
        candidates.append(Path(configured))
    pnpm_path = Path(pnpm).resolve()
    candidates.append(pnpm_path.parent / "node")
    if len(pnpm_path.parents) >= 3:
        candidates.append(pnpm_path.parents[2] / "node" / "bin" / "node")
    node = next(
        (
            candidate.resolve()
            for candidate in candidates
            if candidate.is_file() and os.access(candidate, os.X_OK)
        ),
        None,
    )
    if node is None:
        raise RuntimeError(
            "node not found for pnpm; set NODE_BIN or add the pinned Node runtime to PATH"
        )
    environment["PATH"] = (
        f"{node.parent}{os.pathsep}{current_path}" if current_path else str(node.parent)
    )
    return environment


def test_environment() -> dict[str, str]:
    """Run pre-install tests independently of the requested live TTS matrix."""

    environment = dict(os.environ)
    environment.update(
        {
            TTS_RUNTIME_EXPECTATION_ENV: "disabled",
            TTS_PRODUCT_EXPECTATION_ENV: "disabled",
            TTS_VALIDATION_EXPECTATION_ENV: "disabled",
            TTS_REFERENCE_EXPECTATION_ENV: "disabled",
            TTS_TECHNICAL_ENABLE_ENV: "false",
            TTS_PRODUCT_ENABLE_ENV: "false",
            TTS_VALIDATION_ENABLE_ENV: "false",
            TTS_REFERENCE_ENABLE_ENV: "false",
        }
    )
    for name in (
        TTS_FRESH_INSTALL_ENV,
        TTS_DIGEST_KEY_ID_ENV,
        TTS_VALIDATION_HOST_TOKEN_FILE_ENV,
        TTS_VALIDATION_NOVEL_ID_ENV,
        TTS_VALIDATION_DOCUMENT_ID_ENV,
        TTS_VALIDATION_EXPIRES_AT_ENV,
    ):
        environment.pop(name, None)
    return environment


def wait_until_healthy(timeout_seconds: int = 60) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        status = run(
            "docker",
            "inspect",
            CONTAINER,
            "--format",
            "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
            capture=True,
        )
        if status == "healthy":
            return
        time.sleep(2)
    raise RuntimeError(f"{CONTAINER} did not become healthy within {timeout_seconds}s")


def expected_tts_runtime() -> str:
    expected = os.environ.get(TTS_RUNTIME_EXPECTATION_ENV, "disabled")
    if expected not in TTS_RUNTIME_EXPECTATIONS:
        choices = ", ".join(sorted(TTS_RUNTIME_EXPECTATIONS))
        raise RuntimeError(
            f"{TTS_RUNTIME_EXPECTATION_ENV} must be one of: {choices}; got {expected!r}"
        )
    return expected


def expected_tts_product() -> str:
    expected = os.environ.get(TTS_PRODUCT_EXPECTATION_ENV, "disabled")
    if expected not in TTS_PRODUCT_EXPECTATIONS:
        choices = ", ".join(sorted(TTS_PRODUCT_EXPECTATIONS))
        raise RuntimeError(
            f"{TTS_PRODUCT_EXPECTATION_ENV} must be one of: {choices}; got {expected!r}"
        )
    return expected


def expected_tts_validation() -> str:
    expected = os.environ.get(TTS_VALIDATION_EXPECTATION_ENV, "disabled")
    if expected not in TTS_VALIDATION_EXPECTATIONS:
        choices = ", ".join(sorted(TTS_VALIDATION_EXPECTATIONS))
        raise RuntimeError(
            f"{TTS_VALIDATION_EXPECTATION_ENV} must be one of: {choices}; "
            f"got {expected!r}"
        )
    return expected


def expected_tts_reference_clone() -> str:
    expected = os.environ.get(TTS_REFERENCE_EXPECTATION_ENV, "disabled")
    if expected not in TTS_REFERENCE_EXPECTATIONS:
        choices = ", ".join(sorted(TTS_REFERENCE_EXPECTATIONS))
        raise RuntimeError(
            f"{TTS_REFERENCE_EXPECTATION_ENV} must be one of: {choices}; "
            f"got {expected!r}"
        )
    return expected


def _exact_environment_flag(name: str, *, default: str = "false") -> bool:
    value = os.environ.get(name, default)
    if value not in {"true", "false"}:
        raise RuntimeError(f"{name} must be exactly 'true' or 'false'")
    return value == "true"


def validation_host_token_path() -> Path:
    value = os.environ.get(TTS_VALIDATION_HOST_TOKEN_FILE_ENV, "")
    path = Path(value)
    if not value or not path.is_absolute() or path.parent == path:
        raise RuntimeError(
            f"{TTS_VALIDATION_HOST_TOKEN_FILE_ENV} must be an absolute private path"
        )
    try:
        parent = path.parent.resolve(strict=True)
    except OSError as error:
        raise RuntimeError(
            f"{TTS_VALIDATION_HOST_TOKEN_FILE_ENV} parent is unavailable"
        ) from error
    resolved = parent / path.name
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        raise RuntimeError(
            f"{TTS_VALIDATION_HOST_TOKEN_FILE_ENV} must be outside the repository"
        )
    return resolved


def validate_hidden_validation_scope(*, now: datetime | None = None) -> None:
    current = datetime.now(timezone.utc) if now is None else now
    for name in (TTS_VALIDATION_NOVEL_ID_ENV, TTS_VALIDATION_DOCUMENT_ID_ENV):
        value = os.environ.get(name, "")
        try:
            parsed = UUID(value)
        except (ValueError, AttributeError) as error:
            raise RuntimeError(f"{name} must be a canonical UUID") from error
        if str(parsed) != value:
            raise RuntimeError(f"{name} must be a canonical UUID")
    expiry_value = os.environ.get(TTS_VALIDATION_EXPIRES_AT_ENV, "")
    try:
        expiry = datetime.strptime(
            expiry_value,
            "%Y-%m-%dT%H:%M:%SZ",
        ).replace(tzinfo=timezone.utc)
    except ValueError as error:
        raise RuntimeError(
            f"{TTS_VALIDATION_EXPIRES_AT_ENV} must be UTC second precision"
        ) from error
    if current.tzinfo is None:
        raise RuntimeError("hidden validation preflight clock must be timezone-aware")
    current = current.astimezone(timezone.utc)
    if expiry <= current or expiry - current > timedelta(hours=24):
        raise RuntimeError(
            f"{TTS_VALIDATION_EXPIRES_AT_ENV} must be within the next 24 hours"
        )


def validate_install_intent() -> None:
    """Reject an inconsistent product release intent before any install write."""

    runtime = expected_tts_runtime()
    product = expected_tts_product()
    validation = expected_tts_validation()
    reference = expected_tts_reference_clone()
    if product == "ready" and validation == "ready":
        raise RuntimeError(
            f"{TTS_PRODUCT_EXPECTATION_ENV}=ready and "
            f"{TTS_VALIDATION_EXPECTATION_ENV}=ready are mutually exclusive"
        )
    if validation == "ready" and reference == "ready":
        raise RuntimeError(
            f"{TTS_VALIDATION_EXPECTATION_ENV}=ready and "
            f"{TTS_REFERENCE_EXPECTATION_ENV}=ready are forbidden until the "
            "reference-clone validation gate is approved"
        )
    if (product == "ready" or validation == "ready") and runtime != "ready":
        raise RuntimeError(
            "a ready product or hidden-validation pipeline requires "
            f"{TTS_RUNTIME_EXPECTATION_ENV}=ready"
        )
    if reference == "ready" and product != "ready" and validation != "ready":
        raise RuntimeError(
            "reference clone requires a ready product or hidden-validation pipeline"
        )
    runtime_enabled = _exact_environment_flag(TTS_TECHNICAL_ENABLE_ENV)
    if runtime_enabled is not (runtime == "ready"):
        raise RuntimeError(
            f"{TTS_TECHNICAL_ENABLE_ENV} must match "
            f"{TTS_RUNTIME_EXPECTATION_ENV}"
        )
    product_enabled = _exact_environment_flag(TTS_PRODUCT_ENABLE_ENV)
    validation_enabled = _exact_environment_flag(TTS_VALIDATION_ENABLE_ENV)
    reference_enabled = _exact_environment_flag(TTS_REFERENCE_ENABLE_ENV)
    if product_enabled is not (product == "ready"):
        raise RuntimeError(
            f"{TTS_PRODUCT_ENABLE_ENV} must match "
            f"{TTS_PRODUCT_EXPECTATION_ENV}"
        )
    if validation_enabled is not (validation == "ready"):
        raise RuntimeError(
            f"{TTS_VALIDATION_ENABLE_ENV} must match "
            f"{TTS_VALIDATION_EXPECTATION_ENV}"
        )
    if reference_enabled is not (reference == "ready"):
        raise RuntimeError(
            f"{TTS_REFERENCE_ENABLE_ENV} must match "
            f"{TTS_REFERENCE_EXPECTATION_ENV}"
        )
    if validation == "ready":
        validation_host_token_path()
        validate_hidden_validation_scope()
    if product == "disabled" and validation == "disabled":
        return
    fresh_install = _exact_environment_flag(TTS_FRESH_INSTALL_ENV)
    key_id = os.environ.get(TTS_DIGEST_KEY_ID_ENV)
    if fresh_install and (not key_id or key_id.strip() != key_id):
        raise RuntimeError(
            f"{TTS_DIGEST_KEY_ID_ENV} is required for a fresh product install"
        )


def read_public_plugin_health(*, timeout_seconds: float) -> dict[str, object]:
    request = Request(
        f"{BASE_URL}/api/{PLUGIN_ID}/health",
        headers={"Accept": "application/json"},
    )
    with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise RuntimeError("QwenPaw PawApp health response must be a JSON object")
    return payload


def narration_matches_expected_topology(
    narration: dict[str, object],
    *,
    expected: str,
    expected_product: str = "disabled",
    expected_validation: str = "disabled",
) -> bool:
    if expected == "disabled":
        return (
            narration.get("technical_enabled") is False
            and narration.get("lifecycle_status") == "disabled"
            and narration.get("sidecar_reachable") is False
            and narration.get("model_ready") is False
            and narration.get("worker_generation") is None
            and narration.get("lease_generation") is None
            and narration.get("product_visible") is False
            and narration.get("reason_code") is None
        )

    def is_positive_generation(value: object) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and value > 0

    return (
        narration.get("technical_enabled") is True
        and narration.get("lifecycle_status") == "ready"
        and narration.get("sidecar_reachable") is True
        and narration.get("model_ready") is True
        and is_positive_generation(narration.get("worker_generation"))
        and is_positive_generation(narration.get("lease_generation"))
        and narration.get("product_visible")
        is (expected_product == "ready" and expected_validation != "ready")
        and narration.get("reason_code") is None
    )


def narration_production_matches_expected_topology(
    production: dict[str, object],
    *,
    expected: str,
    expected_reference: str = "disabled",
) -> bool:
    if expected == "disabled":
        return production == {
            "product_requested": False,
            "lifecycle_status": "playback_only",
            "playback_installed": True,
            "digest_keyring_loaded": False,
            "production_backend_installed": False,
            "worker_running": False,
            "reference_clone_ready": False,
            "reason_code": None,
        }
    return production == {
        "product_requested": True,
        "lifecycle_status": "ready",
        "playback_installed": True,
        "digest_keyring_loaded": True,
        "production_backend_installed": True,
        "worker_running": True,
        "reference_clone_ready": expected_reference == "ready",
        "reason_code": None,
    }


def wait_until_expected_tts_runtime(
    *,
    timeout_seconds: float = 30,
    poll_interval_seconds: float = 0.2,
) -> dict[str, object]:
    """Wait on the PawApp's public health contract, never a fixed startup sleep."""

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if poll_interval_seconds <= 0:
        raise ValueError("poll_interval_seconds must be positive")
    expected = expected_tts_runtime()
    expected_product = expected_tts_product()
    expected_validation = expected_tts_validation()
    expected_reference = expected_tts_reference_clone()
    if expected_product == "ready" and expected_validation == "ready":
        raise RuntimeError(
            f"{TTS_PRODUCT_EXPECTATION_ENV}=ready and "
            f"{TTS_VALIDATION_EXPECTATION_ENV}=ready are mutually exclusive"
        )
    if (
        expected_product == "ready" or expected_validation == "ready"
    ) and expected != "ready":
        raise RuntimeError(
            "a ready product or hidden-validation pipeline requires "
            f"{TTS_RUNTIME_EXPECTATION_ENV}=ready"
        )
    if (
        expected_reference == "ready"
        and expected_product != "ready"
        and expected_validation != "ready"
    ):
        raise RuntimeError(
            "reference clone requires a ready product or hidden-validation pipeline"
        )
    expected_pipeline = (
        "ready"
        if expected_product == "ready" or expected_validation == "ready"
        else "disabled"
    )
    deadline = time.monotonic() + timeout_seconds
    last_narration: dict[str, object] | None = None
    last_production: dict[str, object] | None = None
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(
                "PawApp narration runtime did not reach "
                f"technical={expected!r}, product={expected_product!r}, "
                f"validation={expected_validation!r} "
                f"within {timeout_seconds:g}s; last narration state: "
                f"{last_narration!r}; last production state: {last_production!r}"
            )
        health = read_public_plugin_health(timeout_seconds=min(5.0, remaining))
        narration = health.get("narration")
        if not isinstance(narration, dict):
            raise RuntimeError(
                "QwenPaw PawApp health response must contain a narration object"
            )
        production = health.get("narration_production")
        if not isinstance(production, dict):
            raise RuntimeError(
                "QwenPaw PawApp health response must contain a "
                "narration_production object"
            )
        last_narration = narration
        last_production = production
        if (
            narration_matches_expected_topology(
                narration,
                expected=expected,
                expected_product=expected_product,
                expected_validation=expected_validation,
            )
            and narration_production_matches_expected_topology(
                production,
                expected=expected_pipeline,
                expected_reference=expected_reference,
            )
        ):
            return health
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            continue
        time.sleep(min(poll_interval_seconds, remaining))


def remove_stale_installer_container() -> None:
    """Remove only this script's exact, labelled disposable installer."""

    descriptor = run(
        "docker",
        "ps",
        "-a",
        "--filter",
        f"name=^/{INSTALLER_CONTAINER}$",
        "--format",
        f'{{{{.Names}}}}\t{{{{.Label "{INSTALLER_LABEL_KEY}"}}}}',
        capture=True,
    )
    if not descriptor:
        return
    rows = descriptor.splitlines()
    if rows != [f"{INSTALLER_CONTAINER}\t{INSTALLER_LABEL_VALUE}"]:
        raise RuntimeError(
            f"refusing to remove unowned installer container: {descriptor!r}"
        )
    run("docker", "rm", "-f", INSTALLER_CONTAINER)


def run_disposable_installer_container(*, timeout_seconds: float = 120) -> None:
    """Run the one-shot installer without Docker Desktop's attach-start path."""

    try:
        run(
            "docker",
            "start",
            INSTALLER_CONTAINER,
            timeout_seconds=30,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("installer container did not start within 30 seconds") from error
    try:
        exit_code = run(
            "docker",
            "wait",
            INSTALLER_CONTAINER,
            capture=True,
            timeout_seconds=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            f"installer did not finish within {timeout_seconds:g} seconds"
        ) from error
    logs = run("docker", "logs", INSTALLER_CONTAINER, capture=True)
    if logs:
        print(logs)
    if exit_code != "0":
        raise RuntimeError(f"installer exited with status {exit_code or 'unknown'}")


def hot_install_packaged_plugin() -> None:
    """Install through QwenPaw's public hot-load CLI in the running container."""

    if not PLUGIN_DIR.is_dir():
        raise RuntimeError(f"packaged plugin is missing: {PLUGIN_DIR}")
    wait_until_healthy()
    stage_path = f"/tmp/{PLUGIN_ID}-install-{uuid4().hex}"
    try:
        run("docker", "cp", str(PLUGIN_DIR), f"{CONTAINER}:{stage_path}")
        install_output = run(
            "docker",
            "exec",
            CONTAINER,
            "qwenpaw",
            "plugin",
            "install",
            "--force",
            stage_path,
            capture=True,
            capture_stderr=True,
        )
        if install_output:
            print(install_output)
        normalized_output = install_output.casefold()
        reported_failure = next(
            (
                marker
                for marker in PLUGIN_INSTALL_FAILURE_MARKERS
                if marker in normalized_output
            ),
            None,
        )
        if reported_failure is not None:
            raise RuntimeError(
                "QwenPaw public plugin install reported failure "
                f"({reported_failure!r}) despite process status 0"
            )
    finally:
        run("docker", "exec", CONTAINER, "rm", "-rf", "--", stage_path)


def offline_plugin_command(
    *plugin_args: str,
    stage_plugin: bool = False,
) -> None:
    image = run(
        "docker",
        "inspect",
        CONTAINER,
        "--format",
        "{{.Config.Image}}",
        capture=True,
    )
    # QwenPaw may need more than Docker's short default grace period to flush
    # its chat/session files. Wait for a clean stop and give Desktop time to
    # release the named volumes before mounting them in the installer container.
    run("docker", "stop", "--timeout", "30", CONTAINER)
    stopped = run(
        "docker",
        "inspect",
        CONTAINER,
        "--format",
        "{{.State.Running}}",
        capture=True,
    )
    if stopped != "false":
        raise RuntimeError(f"{CONTAINER} did not stop cleanly")
    time.sleep(2)
    try:
        remove_stale_installer_container()
        command = [
            "docker",
            "create",
            "--name",
            INSTALLER_CONTAINER,
            "--platform",
            "linux/arm64",
            "--label",
            f"{INSTALLER_LABEL_KEY}={INSTALLER_LABEL_VALUE}",
            "-e",
            "TZ=Asia/Shanghai",
        ]
        for volume in VOLUMES:
            command.extend(("-v", volume))
        command.extend((image, "qwenpaw", "plugin", *plugin_args))
        run(*command)
        try:
            if stage_plugin:
                if not PLUGIN_DIR.is_dir():
                    raise RuntimeError(f"packaged plugin is missing: {PLUGIN_DIR}")
                # Docker Desktop can deadlock while starting a container whose
                # bind source contains non-ASCII path components.  Staging the
                # already-packaged tree into the disposable container layer
                # avoids that host bind and leaves the named data volumes as
                # the only shared writable state.
                run("docker", "cp", str(PLUGIN_DIR), f"{INSTALLER_CONTAINER}:/plugin")
            run_disposable_installer_container()
        finally:
            remove_stale_installer_container()
    finally:
        run("docker", "start", CONTAINER)
    wait_until_healthy()


def install() -> None:
    validate_install_intent()
    pnpm = pnpm_bin()
    pnpm_environ = pnpm_environment(pnpm)
    run(pnpm, "typecheck", environ=pnpm_environ)
    run(pnpm, "test", environ=pnpm_environ)
    run(pnpm, "build", environ=pnpm_environ)
    run(sys.executable, "-m", "pytest", environ=test_environment())
    run(sys.executable, str(ROOT / "scripts" / "package_plugin.py"))
    require_live_tts_flags_disabled()
    hot_install_packaged_plugin()
    migrate_installed_plugin()
    bootstrap_installed_digest_keyring()
    provision_installed_validation_token()
    run(sys.executable, str(ROOT / "scripts" / "configure_qwenpaw_novel_agent.py"))
    run(
        "docker",
        "exec",
        CONTAINER,
        "sh",
        "-lc",
        "if [ -f /app/working/workspaces/ai-novel-writer/BOOTSTRAP.md ]; then "
        "mv /app/working/workspaces/ai-novel-writer/BOOTSTRAP.md "
        "/app/working/workspaces/ai-novel-writer/BOOTSTRAP.md.completed; fi",
    )
    reload_installed_plugin()
    wait_until_expected_tts_runtime()
    verify()


def migrate_installed_plugin() -> None:
    """Bring the installed plugin schema to the packaged Alembic head."""

    run(
        "docker",
        "exec",
        CONTAINER,
        "sh",
        "-lc",
        f"cd {INSTALLED_PLUGIN_DIR} && "
        "/app/venv/bin/python -m alembic -c alembic.ini upgrade head",
    )


def require_live_tts_flags_disabled() -> None:
    """Prove the first plugin load cannot start either narration runtime."""

    wait_until_healthy()
    probe = (
        "import os,sys; "
        "technical=os.environ.get('AI_NOVEL_TTS_RUNTIME_ENABLED','false'); "
        "product=os.environ.get('AI_NOVEL_TTS_PRODUCT_ENABLED','false'); "
        "validation=os.environ.get('AI_NOVEL_TTS_VALIDATION_ENABLED','false'); "
        "reference=os.environ.get('AI_NOVEL_TTS_REFERENCE_CLONE_ENABLED','false'); "
        "sys.exit(0 if technical == product == validation == reference == 'false' else 64)"
    )
    try:
        run(
            "docker",
            "exec",
            CONTAINER,
            "/app/venv/bin/python",
            "-c",
            probe,
        )
    except subprocess.CalledProcessError as error:
        raise RuntimeError(
            "installation requires the running QwenPaw container to have all "
            "narration runtime, product, validation, and reference flags exactly disabled"
        ) from error


def bootstrap_installed_digest_keyring() -> None:
    """Validate/create the keyring only for an explicit production pipeline."""

    product = expected_tts_product()
    validation = expected_tts_validation()
    reference = expected_tts_reference_clone()
    if product == "ready" and validation == "ready":
        raise RuntimeError(
            f"{TTS_PRODUCT_EXPECTATION_ENV}=ready and "
            f"{TTS_VALIDATION_EXPECTATION_ENV}=ready are mutually exclusive"
        )
    if validation == "ready" and reference == "ready":
        raise RuntimeError(
            f"{TTS_VALIDATION_EXPECTATION_ENV}=ready and "
            f"{TTS_REFERENCE_EXPECTATION_ENV}=ready are forbidden until the "
            "reference-clone validation gate is approved"
        )
    if product == "disabled" and validation == "disabled":
        if reference != "disabled":
            raise RuntimeError(
                "reference clone requires a ready product or hidden-validation pipeline"
            )
        return
    if expected_tts_runtime() != "ready":
        raise RuntimeError(
            "a ready product or hidden-validation pipeline requires "
            f"{TTS_RUNTIME_EXPECTATION_ENV}=ready"
        )
    fresh_install = _exact_environment_flag(TTS_FRESH_INSTALL_ENV)
    key_id = os.environ.get(TTS_DIGEST_KEY_ID_ENV)
    if fresh_install and (not key_id or key_id.strip() != key_id):
        raise RuntimeError(
            f"{TTS_DIGEST_KEY_ID_ENV} is required for a fresh product install"
        )
    command = [
        "docker",
        "exec",
        CONTAINER,
        "/app/venv/bin/python",
        f"{INSTALLED_PLUGIN_DIR}/scripts/tts/bootstrap_digest_keyring.py",
        "--path",
        INSTALLED_DIGEST_KEYRING_PATH,
    ]
    if fresh_install:
        command.extend(("--fresh-install", "--key-id", key_id or ""))
    run(*command)


def provision_installed_validation_token() -> None:
    """Create/verify one same-value host and container token before reload."""

    if expected_tts_validation() != "ready":
        return
    run(
        sys.executable,
        str(ROOT / "scripts" / "tts" / "provision_validation_token.py"),
        "--mode",
        "provision",
        "--host-token-file",
        str(validation_host_token_path()),
        "--confirm",
        "PROVISION-T4K-VALIDATION-TOKEN",
    )


def verify_installed_validation_token() -> None:
    if expected_tts_validation() != "ready":
        return
    run(
        sys.executable,
        str(ROOT / "scripts" / "tts" / "provision_validation_token.py"),
        "--mode",
        "verify",
        "--host-token-file",
        str(validation_host_token_path()),
        "--confirm",
        "PROVISION-T4K-VALIDATION-TOKEN",
    )


def reload_installed_plugin() -> None:
    """Explicitly reload QwenPaw only after schema/keyring prerequisites exist."""

    product = expected_tts_product()
    validation = expected_tts_validation()
    runtime = expected_tts_runtime()
    reference = expected_tts_reference_clone()
    if product == "ready" and validation == "ready":
        raise RuntimeError(
            f"{TTS_PRODUCT_EXPECTATION_ENV}=ready and "
            f"{TTS_VALIDATION_EXPECTATION_ENV}=ready are mutually exclusive"
        )
    if validation == "ready" and reference == "ready":
        raise RuntimeError(
            f"{TTS_VALIDATION_EXPECTATION_ENV}=ready and "
            f"{TTS_REFERENCE_EXPECTATION_ENV}=ready are forbidden until the "
            "reference-clone validation gate is approved"
        )
    if (product == "ready" or validation == "ready") and runtime != "ready":
        raise RuntimeError(
            "a ready product or hidden-validation pipeline requires "
            f"{TTS_RUNTIME_EXPECTATION_ENV}=ready"
        )
    if reference == "ready" and product != "ready" and validation != "ready":
        raise RuntimeError(
            "reference clone requires a ready product or hidden-validation pipeline"
        )
    runtime_enabled = _exact_environment_flag(TTS_TECHNICAL_ENABLE_ENV)
    product_enabled = _exact_environment_flag(TTS_PRODUCT_ENABLE_ENV)
    validation_enabled = _exact_environment_flag(TTS_VALIDATION_ENABLE_ENV)
    reference_enabled = _exact_environment_flag(TTS_REFERENCE_ENABLE_ENV)
    if runtime_enabled is not (runtime == "ready"):
        raise RuntimeError(
            f"{TTS_TECHNICAL_ENABLE_ENV} must match "
            f"{TTS_RUNTIME_EXPECTATION_ENV}"
        )
    if product_enabled is not (product == "ready"):
        raise RuntimeError(
            f"{TTS_PRODUCT_ENABLE_ENV} must match "
            f"{TTS_PRODUCT_EXPECTATION_ENV}"
        )
    if validation_enabled is not (validation == "ready"):
        raise RuntimeError(
            f"{TTS_VALIDATION_ENABLE_ENV} must match "
            f"{TTS_VALIDATION_EXPECTATION_ENV}"
        )
    if reference_enabled is not (reference == "ready"):
        raise RuntimeError(
            f"{TTS_REFERENCE_ENABLE_ENV} must match "
            f"{TTS_REFERENCE_EXPECTATION_ENV}"
        )
    if runtime == "ready" or product == "ready" or validation == "ready":
        run(
            "docker",
            "compose",
            "--file",
            str(ROOT / "compose.yaml"),
            "up",
            "-d",
            "--no-deps",
            "--force-recreate",
            "qwenpaw",
        )
    else:
        run("docker", "restart", CONTAINER)
    wait_until_healthy()


def verify() -> None:
    verify_installed_validation_token()
    run(sys.executable, str(ROOT / "scripts" / "verify_qwenpaw_lab.py"))


def uninstall(confirm: str) -> None:
    if confirm != PLUGIN_ID:
        raise RuntimeError(f"uninstall requires --confirm {PLUGIN_ID}")
    request = Request(
        f"{BASE_URL}/api/plugins/{PLUGIN_ID}",
        method="DELETE",
        headers={"Accept": "application/json"},
    )
    with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed local lab URL
        if response.status != 200:
            raise RuntimeError(f"runtime uninstall returned HTTP {response.status}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("install")
    subparsers.add_parser("verify")
    uninstall_parser = subparsers.add_parser("uninstall")
    uninstall_parser.add_argument("--confirm", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "install":
        install()
    elif args.command == "verify":
        verify()
    else:
        uninstall(args.confirm)


if __name__ == "__main__":
    main()
