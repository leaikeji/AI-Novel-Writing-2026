from __future__ import annotations

import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys

import pytest

from scripts.tts import manage_voice_generator_host as manager
from scripts.tts import provision_validation_token as token_provisioner
from scripts.tts.voice_generator import native_runtime


def _source_tree(root: Path) -> None:
    for index, relative in enumerate(manager.SOURCE_FILES):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"# source {index}\n", encoding="utf-8")


def test_release_is_content_addressed_private_and_tamper_evident(tmp_path: Path) -> None:
    project = tmp_path / "project"
    releases = tmp_path / "releases"
    _source_tree(project)

    release = manager.stage_release(project, releases)
    assert release.parent == releases
    assert len(release.name) == 64
    manifest = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert set(manifest["files"]) == set(manager.SOURCE_FILES)
    assert manager.stage_release(project, releases) == release

    changed = release / manager.SOURCE_FILES[-1]
    changed.chmod(0o600)
    changed.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(manager.HostManagementError, match="HOST_RELEASE_INVALID"):
        manager.stage_release(project, releases)


def test_launch_agent_only_exposes_fixed_paths_and_offline_runtime(tmp_path: Path) -> None:
    release = tmp_path / "release"
    value = manager.build_launch_agent(release)
    arguments = value["ProgramArguments"]
    assert arguments[1:3] == ["-m", "scripts.tts.voice_generator.host_entrypoint"]
    assert "--model-root" in arguments
    assert "--token-file" in arguments
    assert value["WorkingDirectory"] == str(release)
    assert value["EnvironmentVariables"]["HF_HUB_OFFLINE"] == "1"
    assert value["EnvironmentVariables"]["TRANSFORMERS_OFFLINE"] == "1"
    assert "token" not in plistlib.dumps(value).decode("utf-8").lower().replace(
        "--token-file", ""
    ).replace(str(manager.HOST_TOKEN_FILE).lower(), "")


def test_shared_token_port_rejects_arbitrary_container_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(token_provisioner.shutil, "which", lambda _: "/usr/bin/docker")
    with pytest.raises(
        token_provisioner.TokenProvisionError,
        match="CONTAINER_TOKEN_TARGET_INVALID",
    ):
        token_provisioner.DockerContainerTokenPort(
            token_directory="/tmp/arbitrary",
            token_file="/tmp/arbitrary/token",
        )


def test_product_runtime_uses_the_pinned_snapshot_directory_layout() -> None:
    assert native_runtime.GENERATOR_SNAPSHOT_PATH == (
        "OpenMOSS-Team--MOSS-VoiceGenerator",
        native_runtime.VOICE_GENERATOR_REVISION,
    )
    assert native_runtime.CODEC_SNAPSHOT_PATH == (
        "OpenMOSS-Team--MOSS-Audio-Tokenizer",
        native_runtime.CODEC_REVISION,
    )


def test_real_staged_release_can_import_host_entrypoint(tmp_path: Path) -> None:
    release = manager.stage_release(manager.PROJECT_ROOT, tmp_path / "releases")
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": str(release),
        "PYTHONNOUSERSITE": "1",
    }
    completed = subprocess.run(
        [sys.executable, "-c", "import scripts.tts.voice_generator.host_server"],
        cwd=release,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
