#!/usr/bin/env python3
"""Install and manage the fixed macOS VoiceGenerator launch agent."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Final, Mapping, Sequence
import urllib.error
import urllib.request

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.narration.voice_generator_runtime import read_host_token


APP_ROOT: Final = (
    Path.home()
    / "Library"
    / "Application Support"
    / "AI小说世界2026"
    / "voice-generator-vg40"
)
RUNTIME_PYTHON: Final = APP_ROOT / "runtime" / "venv" / "bin" / "python"
MODEL_ROOT: Final = APP_ROOT / "models"
HOST_TOKEN_FILE: Final = APP_ROOT / "secrets" / "host-token"
STORE_ROOT: Final = APP_ROOT / "product-store"
DEPLOY_ROOT: Final = APP_ROOT / "product-host"
RELEASES_ROOT: Final = DEPLOY_ROOT / "releases"
LOG_ROOT: Final = DEPLOY_ROOT / "logs"
LAUNCH_AGENT_LABEL: Final = "com.ai-novel-world-2026.voice-generator"
LAUNCH_AGENT_FILE: Final = (
    Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"
)
HOST_URL: Final = "http://127.0.0.1:18765/v1/health"
INSTALL_CONFIRMATION: Final = "INSTALL-VOICE-GENERATOR-HOST"
UNINSTALL_CONFIRMATION: Final = "UNINSTALL-VOICE-GENERATOR-HOST"
HOST_PROTOCOL_VERSION: Final = "moss-voice-generator-host/1"
SOURCE_FILES: Final = (
    "backend/__init__.py",
    "backend/narration/__init__.py",
    "backend/narration/adapters.py",
    "backend/narration/contracts.py",
    "backend/narration/fingerprints.py",
    "backend/narration/voice_generator_runtime.py",
    "scripts/tts/voice_generator/__init__.py",
    "scripts/tts/voice_generator/host_entrypoint.py",
    "scripts/tts/voice_generator/host_server.py",
    "scripts/tts/voice_generator/native_runtime.py",
    "scripts/tts/voice_generator/native_worker.py",
    "scripts/tts/voice_generator/product_adapters.py",
)


class HostManagementError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _source_manifest(project_root: Path = PROJECT_ROOT) -> dict[str, str]:
    manifest: dict[str, str] = {}
    resolved_root = project_root.resolve(strict=True)
    for relative in SOURCE_FILES:
        source = resolved_root / relative
        if source.is_symlink() or not source.is_file() or source.resolve(strict=True) != source:
            raise HostManagementError("HOST_SOURCE_INVALID")
        manifest[relative] = _sha256(source)
    return manifest


def _release_digest(manifest: Mapping[str, str]) -> str:
    payload = json.dumps(
        {"schema_version": 1, "files": dict(manifest)},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _ensure_private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    details = path.lstat()
    if (
        not stat.S_ISDIR(details.st_mode)
        or stat.S_ISLNK(details.st_mode)
        or details.st_uid != os.getuid()
    ):
        raise HostManagementError("HOST_DIRECTORY_INVALID")
    path.chmod(0o700)


def _verify_release(release: Path, manifest: Mapping[str, str]) -> None:
    if release.is_symlink() or not release.is_dir():
        raise HostManagementError("HOST_RELEASE_INVALID")
    for relative, expected in manifest.items():
        candidate = release / relative
        if candidate.is_symlink() or not candidate.is_file() or _sha256(candidate) != expected:
            raise HostManagementError("HOST_RELEASE_INVALID")
    manifest_file = release / "manifest.json"
    if manifest_file.is_symlink() or not manifest_file.is_file():
        raise HostManagementError("HOST_RELEASE_INVALID")
    value = json.loads(manifest_file.read_text(encoding="utf-8"))
    if value != {"schema_version": 1, "files": dict(manifest)}:
        raise HostManagementError("HOST_RELEASE_INVALID")


def stage_release(
    project_root: Path = PROJECT_ROOT,
    releases_root: Path = RELEASES_ROOT,
) -> Path:
    manifest = _source_manifest(project_root)
    digest = _release_digest(manifest)
    _ensure_private_directory(releases_root)
    release = releases_root / digest
    if release.exists():
        _verify_release(release, manifest)
        return release
    staging = Path(tempfile.mkdtemp(prefix=f".{digest}.", dir=releases_root))
    try:
        for relative in SOURCE_FILES:
            target = staging / relative
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            shutil.copyfile(project_root / relative, target)
            target.chmod(0o400)
        manifest_file = staging / "manifest.json"
        manifest_file.write_text(
            json.dumps(
                {"schema_version": 1, "files": manifest},
                sort_keys=True,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        manifest_file.chmod(0o400)
        for directory, _, _ in os.walk(staging):
            Path(directory).chmod(0o500)
        staging.rename(release)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    _verify_release(release, manifest)
    return release


def build_launch_agent(release: Path) -> dict[str, object]:
    return {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": [
            str(RUNTIME_PYTHON),
            "-m",
            "scripts.tts.voice_generator.host_entrypoint",
            "--token-file",
            str(HOST_TOKEN_FILE),
            "--store-root",
            str(STORE_ROOT),
            "--runtime-python",
            str(RUNTIME_PYTHON),
            "--model-root",
            str(MODEL_ROOT),
        ],
        "WorkingDirectory": str(release),
        "EnvironmentVariables": {
            "PYTHONPATH": str(release),
            "PYTHONNOUSERSITE": "1",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        },
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ProcessType": "Background",
        "ThrottleInterval": 15,
        "StandardOutPath": str(LOG_ROOT / "host.stdout.log"),
        "StandardErrorPath": str(LOG_ROOT / "host.stderr.log"),
    }


def _atomic_plist(path: Path, value: Mapping[str, object]) -> None:
    if not path.parent.exists():
        path.parent.mkdir(mode=0o700, parents=False)
    parent = path.parent.lstat()
    if (
        not stat.S_ISDIR(parent.st_mode)
        or stat.S_ISLNK(parent.st_mode)
        or parent.st_uid != os.getuid()
    ):
        raise HostManagementError("LAUNCH_AGENT_DIRECTORY_INVALID")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            descriptor = -1
            plistlib.dump(dict(value), output, fmt=plistlib.FMT_XML, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _launchctl(*arguments: str, allow_missing: bool = False) -> str:
    executable = shutil.which("launchctl")
    if executable is None:
        raise HostManagementError("LAUNCHCTL_UNAVAILABLE")
    completed = subprocess.run(
        [executable, *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        env={"PATH": "/usr/bin:/bin"},
    )
    if completed.returncode != 0 and not allow_missing:
        raise HostManagementError("LAUNCHCTL_FAILED")
    return completed.stdout


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _validate_runtime_inputs() -> None:
    try:
        runtime_executable = RUNTIME_PYTHON.resolve(strict=True)
        read_host_token(HOST_TOKEN_FILE)
    except (OSError, RuntimeError, ValueError) as error:
        raise HostManagementError("HOST_INPUT_MISSING") from error
    if not runtime_executable.is_file() or not os.access(runtime_executable, os.X_OK):
        raise HostManagementError("HOST_INPUT_MISSING")
    for path in (APP_ROOT, MODEL_ROOT):
        if path.is_symlink() or not path.is_dir():
            raise HostManagementError("HOST_INPUT_MISSING")


def install() -> dict[str, object]:
    _validate_runtime_inputs()
    from scripts.tts.voice_generator.native_runtime import NativeRuntimeBackend

    backend = NativeRuntimeBackend(
        runtime_python=RUNTIME_PYTHON,
        model_root=MODEL_ROOT,
    )
    if not backend.readiness():
        raise HostManagementError("HOST_RUNTIME_NOT_READY")
    _ensure_private_directory(STORE_ROOT)
    _ensure_private_directory(LOG_ROOT)
    release = stage_release()
    _launchctl("bootout", _domain(), str(LAUNCH_AGENT_FILE), allow_missing=True)
    _atomic_plist(LAUNCH_AGENT_FILE, build_launch_agent(release))
    _launchctl("bootstrap", _domain(), str(LAUNCH_AGENT_FILE))
    _launchctl("kickstart", "-k", f"{_domain()}/{LAUNCH_AGENT_LABEL}")
    return {
        "schema_version": 1,
        "status": "INSTALLED",
        "release_digest": release.name,
        "secret_values_emitted": False,
    }


def _health() -> dict[str, object]:
    token = read_host_token(HOST_TOKEN_FILE)
    request = urllib.request.Request(
        HOST_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "X-MOSS-Protocol-Version": HOST_PROTOCOL_VERSION,
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            value = json.loads(response.read(64 * 1024).decode("utf-8"))
    except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError) as error:
        raise HostManagementError("HOST_HEALTH_UNAVAILABLE") from error
    if (
        type(value) is not dict
        or value.get("protocol_version") != HOST_PROTOCOL_VERSION
        or type(value.get("ready")) is not bool
    ):
        raise HostManagementError("HOST_HEALTH_INVALID")
    return {
        "schema_version": 1,
        "status": "READY" if value["ready"] else "NOT_READY",
        "ready": value["ready"],
        "runtime_fingerprint": value.get("runtime_fingerprint"),
        "secret_values_emitted": False,
    }


def verify() -> dict[str, object]:
    _validate_runtime_inputs()
    _launchctl("print", f"{_domain()}/{LAUNCH_AGENT_LABEL}")
    return _health()


def stop() -> dict[str, object]:
    _launchctl("bootout", _domain(), str(LAUNCH_AGENT_FILE), allow_missing=True)
    return {"schema_version": 1, "status": "STOPPED", "secret_values_emitted": False}


def uninstall() -> dict[str, object]:
    stop()
    if LAUNCH_AGENT_FILE.is_symlink():
        raise HostManagementError("LAUNCH_AGENT_INVALID")
    LAUNCH_AGENT_FILE.unlink(missing_ok=True)
    return {
        "schema_version": 1,
        "status": "UNINSTALLED",
        "models_preserved": True,
        "store_preserved": True,
        "token_preserved": True,
        "secret_values_emitted": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("install", "verify", "stop", "uninstall"), required=True)
    parser.add_argument("--confirm")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        arguments = build_parser().parse_args(argv)
        if arguments.mode == "install":
            if arguments.confirm != INSTALL_CONFIRMATION:
                raise HostManagementError("CONFIRMATION_REQUIRED")
            result = install()
        elif arguments.mode == "uninstall":
            if arguments.confirm != UNINSTALL_CONFIRMATION:
                raise HostManagementError("CONFIRMATION_REQUIRED")
            result = uninstall()
        elif arguments.mode == "stop":
            result = stop()
        else:
            result = verify()
        sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
        return 0
    except HostManagementError as error:
        sys.stderr.write(
            json.dumps(
                {"status": "FAILED", "code": error.code},
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
