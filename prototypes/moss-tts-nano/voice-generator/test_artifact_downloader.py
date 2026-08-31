from __future__ import annotations

import hashlib
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import tempfile

import pytest


ROOT = Path(__file__).resolve().parent


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


manifest_module = load(ROOT / "artifact_manifest.py", "artifact_manifest")
downloader = load(ROOT / "artifact_downloader.py", "artifact_downloader")


class Response(io.BytesIO):
    def __init__(self, payload: bytes, url: str = "https://cdn.example/fixed"):
        super().__init__(payload)
        self._url = url

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def component(payload: bytes):
    return {
        "id": "voice-generator",
        "resolve_base_url": "https://example.invalid/fixed/",
        "files": [
            {
                "path": "model.bin",
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        ],
    }


def test_single_copy_download_verify_and_atomic_publish(monkeypatch):
    payload = b"fixed-artifact"
    monkeypatch.setattr(downloader, "assert_disk_gate", lambda *args: None)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        staging_parent = root / "staging"
        models = root / "models"
        staging_parent.mkdir()
        models.mkdir()
        staging = downloader.download_component(
            component(payload),
            staging_parent=staging_parent,
            filesystem_gate_path=root,
            projected_release_bytes=len(payload),
            opener=lambda *args, **kwargs: Response(payload),
        )
        final = models / "voice-generator"
        verified = downloader.publish_component(staging, final, component(payload))
        assert verified["file_count"] == 1
        assert final.is_dir()
        assert not staging.exists()


def test_download_rejects_size_hash_https_redirect_and_existing_target(monkeypatch):
    monkeypatch.setattr(downloader, "assert_disk_gate", lambda *args: None)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        root.mkdir(exist_ok=True)
        target = root / "model.bin"
        with pytest.raises(downloader.DownloadError):
            downloader._download_one(
                "http://example.invalid/model",
                target,
                expected_bytes=1,
                expected_sha256=hashlib.sha256(b"x").hexdigest(),
                opener=lambda *args, **kwargs: Response(b"x"),
            )
        with pytest.raises(downloader.DownloadError):
            downloader._download_one(
                "https://example.invalid/model",
                target,
                expected_bytes=1,
                expected_sha256=hashlib.sha256(b"x").hexdigest(),
                opener=lambda *args, **kwargs: Response(b"too-long"),
            )
        with pytest.raises(downloader.DownloadError):
            downloader._download_one(
                "https://example.invalid/model",
                target,
                expected_bytes=1,
                expected_sha256=hashlib.sha256(b"x").hexdigest(),
                opener=lambda *args, **kwargs: Response(b"x", "http://bad/final"),
            )
        target.write_bytes(b"existing")
        with pytest.raises(FileExistsError):
            downloader._download_one(
                "https://example.invalid/model",
                target,
                expected_bytes=1,
                expected_sha256=hashlib.sha256(b"x").hexdigest(),
                opener=lambda *args, **kwargs: Response(b"x"),
            )


def test_release_marker_is_atomic_and_never_overwrites():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        marker = root / "release.json"
        downloader.write_release_marker(
            marker,
            manifest_sha256="a" * 64,
            components=[{"id": "voice-generator"}],
        )
        with pytest.raises(FileExistsError):
            downloader.write_release_marker(
                marker,
                manifest_sha256="b" * 64,
                components=[],
            )


def test_curl_small_file_download_is_verified_and_atomic(monkeypatch):
    payload = b"small-fixed-file"

    def fake_run(command, **kwargs):
        output = Path(command[command.index("--output") + 1])
        output.write_bytes(payload)
        return subprocess.CompletedProcess(
            command,
            0,
            "https://cdn.example/fixed\n200\n",
            "",
        )

    monkeypatch.setattr(downloader.subprocess, "run", fake_run)
    with tempfile.TemporaryDirectory() as temporary:
        target = Path(temporary).resolve() / "config.json"
        downloader.download_file_with_curl(
            "https://example.invalid/config.json",
            target,
            expected_bytes=len(payload),
            expected_sha256=hashlib.sha256(payload).hexdigest(),
        )
        assert target.read_bytes() == payload
        with pytest.raises(FileExistsError):
            downloader.download_file_with_curl(
                "https://example.invalid/config.json",
                target,
                expected_bytes=len(payload),
                expected_sha256=hashlib.sha256(payload).hexdigest(),
            )
