"""Install and manage the native Qwen3-TTS runtime as a macOS LaunchAgent.

The generated plist contains paths and non-secret process settings only. The
runtime reads its bearer token from the existing 0600 file at process start.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import plistlib
import stat
import subprocess
import tempfile
from typing import Final, Sequence


SERVICE_LABEL: Final = "com.ai-novel-world-2026.qwen-tts"
DEFAULT_PORT: Final = 8766


class RuntimeServiceError(RuntimeError):
    """The host runtime service could not be safely configured."""


@dataclass(frozen=True, slots=True)
class RuntimeServicePaths:
    repository_root: Path
    application_root: Path
    launch_agents_root: Path

    @property
    def python(self) -> Path:
        return self.application_root / "runtime-venv" / "bin" / "python"

    @property
    def token_file(self) -> Path:
        return self.application_root / "local-token"

    @property
    def custom_voice_model(self) -> Path:
        return self.application_root / "models" / "customvoice-8bit-modelscope"

    @property
    def base_model(self) -> Path:
        return self.application_root / "models" / "base-8bit-modelscope"

    @property
    def voice_design_model(self) -> Path:
        return self.application_root / "models" / "voice-design-bf16-modelscope"

    @property
    def logs_root(self) -> Path:
        return self.application_root / "logs"

    @property
    def plist_path(self) -> Path:
        return self.launch_agents_root / f"{SERVICE_LABEL}.plist"


def default_paths() -> RuntimeServicePaths:
    repository_root = Path(__file__).resolve().parents[2]
    user_home = Path.home()
    return RuntimeServicePaths(
        repository_root=repository_root,
        application_root=(
            user_home
            / "Library"
            / "Application Support"
            / "AI小说世界2026"
            / "qwen-tts"
        ),
        launch_agents_root=user_home / "Library" / "LaunchAgents",
    )


def validate_paths(paths: RuntimeServicePaths) -> None:
    if not (paths.repository_root / "tts_runtime" / "__main__.py").is_file():
        raise RuntimeServiceError("repository does not contain the Qwen TTS runtime")
    if not paths.python.is_file() or not os.access(paths.python, os.X_OK):
        raise RuntimeServiceError("Qwen TTS runtime Python is unavailable")
    for model_path in (
        paths.custom_voice_model,
        paths.base_model,
        paths.voice_design_model,
    ):
        if not model_path.is_dir():
            raise RuntimeServiceError("one or more frozen Qwen TTS models are unavailable")
    try:
        token_mode = stat.S_IMODE(paths.token_file.stat().st_mode)
    except OSError as error:
        raise RuntimeServiceError("Qwen TTS token file is unavailable") from error
    if token_mode != 0o600:
        raise RuntimeServiceError("Qwen TTS token file permissions must be 0600")


def launch_agent_payload(
    paths: RuntimeServicePaths,
    *,
    port: int = DEFAULT_PORT,
) -> dict[str, object]:
    if type(port) is not int or not 1 <= port <= 65_535:
        raise RuntimeServiceError("Qwen TTS runtime port is invalid")
    environment = {
        # launchd does not inherit this macOS user-session encoding marker.
        # Without it, Python can block while resolving a Unicode PYTHONPATH
        # before the codec registry is ready (the repository path is Chinese).
        "__CF_USER_TEXT_ENCODING": f"0x{os.getuid():X}:0x0:0x0",
        "LANG": "en_US.UTF-8",
        "LC_ALL": "en_US.UTF-8",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "PYTHONPATH": str(paths.repository_root),
        "QWEN_TTS_LOCAL_BIND": "0.0.0.0",
        "QWEN_TTS_LOCAL_PORT": str(port),
        "QWEN_TTS_LOCAL_TOKEN_FILE": str(paths.token_file),
        "QWEN_TTS_CUSTOM_VOICE_MODEL_PATH": str(paths.custom_voice_model),
        "QWEN_TTS_BASE_MODEL_PATH": str(paths.base_model),
        "QWEN_TTS_VOICE_DESIGN_MODEL_PATH": str(paths.voice_design_model),
    }
    return {
        "Label": SERVICE_LABEL,
        "ProgramArguments": [str(paths.python), "-m", "tts_runtime"],
        "WorkingDirectory": str(paths.repository_root),
        "EnvironmentVariables": environment,
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
        "Umask": 0o077,
        "ThrottleInterval": 10,
        "ExitTimeOut": 30,
        "StandardOutPath": str(paths.logs_root / "runtime.stdout.log"),
        "StandardErrorPath": str(paths.logs_root / "runtime.stderr.log"),
    }


def render_launch_agent(paths: RuntimeServicePaths) -> bytes:
    return plistlib.dumps(launch_agent_payload(paths), sort_keys=True)


def _launchctl(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("/bin/launchctl", *arguments),
        check=check,
        capture_output=True,
        text=True,
    )


def install(paths: RuntimeServicePaths) -> None:
    validate_paths(paths)
    paths.logs_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    paths.logs_root.chmod(0o700)
    paths.launch_agents_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = render_launch_agent(paths)
    with tempfile.NamedTemporaryFile(
        dir=paths.launch_agents_root,
        prefix=f".{SERVICE_LABEL}.",
        suffix=".plist",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
    try:
        temporary.chmod(0o600)
        os.replace(temporary, paths.plist_path)
    finally:
        temporary.unlink(missing_ok=True)
    domain = f"gui/{os.getuid()}"
    _launchctl("bootout", f"{domain}/{SERVICE_LABEL}", check=False)
    _launchctl("bootstrap", domain, str(paths.plist_path))
    _launchctl("kickstart", "-k", f"{domain}/{SERVICE_LABEL}")


def status() -> int:
    result = _launchctl(
        "print",
        f"gui/{os.getuid()}/{SERVICE_LABEL}",
        check=False,
    )
    if result.returncode == 0:
        print(f"{SERVICE_LABEL}: loaded")
        return 0
    print(f"{SERVICE_LABEL}: not loaded")
    return 1


def uninstall(paths: RuntimeServicePaths) -> None:
    _launchctl(
        "bootout",
        f"gui/{os.getuid()}/{SERVICE_LABEL}",
        check=False,
    )
    paths.plist_path.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("check", "install", "status", "uninstall"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    command = _parser().parse_args(argv).command
    paths = default_paths()
    if command == "check":
        validate_paths(paths)
        print(f"{SERVICE_LABEL}: configuration ready")
        return 0
    if command == "install":
        install(paths)
        return status()
    if command == "uninstall":
        uninstall(paths)
        return 0
    return status()


if __name__ == "__main__":
    raise SystemExit(main())
