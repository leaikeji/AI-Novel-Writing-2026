"""Build, install, verify, or explicitly uninstall the PawApp in the local lab."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
CONTAINER = os.environ.get("QWENPAW_CONTAINER", "ai-novel-2026-qwenpaw-lab")
BASE_URL = os.environ.get("QWENPAW_BASE_URL", "http://127.0.0.1:18088").rstrip("/")
PLUGIN_ID = "ai-novel-world-2026"
PLUGIN_DIR = ROOT / "build" / PLUGIN_ID
VOLUMES = (
    "ai-novel-2026-qwenpaw-data:/app/working",
    "ai-novel-2026-qwenpaw-secrets:/app/working.secret",
    "ai-novel-2026-qwenpaw-backups:/app/working.backups",
)


def run(
    *args: str,
    cwd: Path = ROOT,
    capture: bool = False,
) -> str:
    completed = subprocess.run(
        args,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return completed.stdout.strip() if capture else ""


def pnpm_bin() -> str:
    configured = os.environ.get("PNPM_BIN")
    resolved = configured or shutil.which("pnpm")
    if not resolved:
        raise RuntimeError("pnpm not found; set PNPM_BIN or install the pinned pnpm version")
    return resolved


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


def offline_plugin_command(
    *plugin_args: str,
    mount_plugin: bool = False,
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
        command = [
            "docker",
            "run",
            "--rm",
            "--platform",
            "linux/arm64",
            "-e",
            "TZ=Asia/Shanghai",
        ]
        for volume in VOLUMES:
            command.extend(("-v", volume))
        if mount_plugin:
            command.extend(("-v", f"{PLUGIN_DIR}:/plugin:ro"))
        command.extend((image, "qwenpaw", "plugin", *plugin_args))
        run(*command)
    finally:
        run("docker", "start", CONTAINER)
    wait_until_healthy()


def install() -> None:
    pnpm = pnpm_bin()
    run(pnpm, "typecheck")
    run(pnpm, "test")
    run(pnpm, "build")
    run(sys.executable, "-m", "pytest")
    run(sys.executable, str(ROOT / "scripts" / "package_plugin.py"))
    offline_plugin_command("install", "--force", "/plugin", mount_plugin=True)
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
    verify()


def verify() -> None:
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
