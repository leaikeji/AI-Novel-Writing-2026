from __future__ import annotations

import os
from pathlib import Path
import plistlib

import pytest

from scripts.qwen_tts.macos_runtime_service import (
    RuntimeServiceError,
    RuntimeServicePaths,
    SERVICE_LABEL,
    launch_agent_payload,
    render_launch_agent,
    validate_paths,
)


def _paths(tmp_path: Path) -> RuntimeServicePaths:
    repository = tmp_path / "repository"
    application = tmp_path / "application"
    launch_agents = tmp_path / "LaunchAgents"
    (repository / "tts_runtime").mkdir(parents=True)
    (repository / "tts_runtime" / "__main__.py").write_text("", encoding="utf-8")
    python = application / "runtime-venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")
    python.chmod(0o700)
    for name in (
        "customvoice-8bit-modelscope",
        "base-8bit-modelscope",
        "voice-design-bf16-modelscope",
    ):
        (application / "models" / name).mkdir(parents=True)
    token = application / "local-token"
    token.write_text("a-private-token-value", encoding="ascii")
    token.chmod(0o600)
    return RuntimeServicePaths(repository, application, launch_agents)


def test_launch_agent_is_restartable_utf8_and_never_embeds_token(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    validate_paths(paths)

    encoded = render_launch_agent(paths)
    payload = plistlib.loads(encoded)
    environment = payload["EnvironmentVariables"]

    assert payload["Label"] == SERVICE_LABEL
    assert payload["RunAtLoad"] is True
    assert payload["KeepAlive"] is True
    assert payload["Umask"] == 0o077
    assert payload["ProgramArguments"] == [
        str(paths.python),
        "-m",
        "tts_runtime",
    ]
    assert environment["PYTHONUTF8"] == "1"
    assert environment["PYTHONIOENCODING"] == "utf-8"
    assert environment["__CF_USER_TEXT_ENCODING"] == f"0x{os.getuid():X}:0x0:0x0"
    assert environment["QWEN_TTS_LOCAL_BIND"] == "0.0.0.0"
    assert environment["QWEN_TTS_LOCAL_TOKEN_FILE"] == str(paths.token_file)
    assert b"a-private-token-value" not in encoded


def test_launch_agent_rejects_public_token_permissions(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.token_file.chmod(0o644)

    with pytest.raises(RuntimeServiceError, match="permissions"):
        validate_paths(paths)


def test_launch_agent_rejects_missing_model_without_creating_files(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    missing = paths.base_model
    missing.rmdir()

    with pytest.raises(RuntimeServiceError, match="models"):
        validate_paths(paths)
    assert not paths.launch_agents_root.exists()
    assert os.access(paths.python, os.X_OK)


def test_launch_agent_rejects_invalid_port(tmp_path: Path) -> None:
    paths = _paths(tmp_path)

    with pytest.raises(RuntimeServiceError, match="port"):
        launch_agent_payload(paths, port=0)
