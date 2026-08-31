"""Single-copy HTTPS downloader and atomic publisher for Plan 40 artifacts."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import stat
import subprocess
from typing import Callable, Mapping
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from artifact_manifest import ManifestError, assert_disk_gate, verify_snapshot


CHUNK_BYTES = 4 * 1024 * 1024


class DownloadError(RuntimeError):
    pass


UrlOpen = Callable[..., object]


def download_component(
    component: Mapping[str, object],
    *,
    staging_parent: Path,
    filesystem_gate_path: Path,
    projected_release_bytes: int,
    opener: UrlOpen = urlopen,
) -> Path:
    _require_regular_directory(staging_parent)
    assert_disk_gate(filesystem_gate_path, projected_release_bytes)
    component_id = str(component["id"])
    staging = staging_parent / f"{component_id}-{secrets.token_hex(8)}.partial"
    staging.mkdir(mode=0o700)
    base_url = str(component["resolve_base_url"])
    try:
        for item in component["files"]:  # type: ignore[index]
            if not isinstance(item, dict):
                raise DownloadError("invalid manifest file entry")
            relative = str(item["path"])
            target = staging / relative
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            _download_one(
                base_url + quote(relative, safe="/"),
                target,
                expected_bytes=int(item["bytes"]),
                expected_sha256=str(item["sha256"]),
                opener=opener,
            )
            assert_disk_gate(filesystem_gate_path, projected_release_bytes)
        verify_snapshot(staging, component)
    except BaseException:
        # Keep the exact partial directory for diagnosis/resume.  It is never
        # considered a model snapshot because its name ends in .partial.
        raise
    return staging


def publish_component(
    staging: Path,
    final: Path,
    component: Mapping[str, object],
) -> dict[str, object]:
    _require_regular_directory(staging)
    if final.exists() or final.is_symlink():
        raise FileExistsError("final component already exists")
    final.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if staging.stat().st_dev != final.parent.stat().st_dev:
        raise DownloadError("staging and final directories must share a filesystem")
    verified = verify_snapshot(staging, component)
    for path in sorted(staging.rglob("*"), reverse=True):
        if path.is_file():
            path.chmod(0o444)
        elif path.is_dir():
            path.chmod(0o555)
    os.replace(staging, final)
    final.chmod(0o555)
    _fsync_directory(final.parent)
    return verified


def download_file_with_curl(
    url: str,
    target: Path,
    *,
    expected_bytes: int,
    expected_sha256: str,
) -> None:
    """Download one small fixed file through bounded macOS IPv4/HTTP1 curl."""

    if urlparse(url).scheme != "https":
        raise DownloadError("download URL must use HTTPS")
    if target.exists() or target.is_symlink():
        raise FileExistsError("staging target already exists")
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    partial = target.with_name(f".{target.name}.{secrets.token_hex(4)}.curl-download")
    try:
        result = subprocess.run(
            [
                "/usr/bin/curl",
                "--ipv4",
                "--http1.1",
                "--location",
                "--fail",
                "--silent",
                "--show-error",
                "--connect-timeout",
                "15",
                "--max-time",
                "300",
                "--speed-limit",
                "1024",
                "--speed-time",
                "30",
                "--retry",
                "5",
                "--retry-all-errors",
                "--retry-delay",
                "2",
                "--output",
                str(partial),
                "--write-out",
                "%{url_effective}\n%{http_code}\n",
                url,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=330,
        )
        if result.returncode != 0:
            raise DownloadError("curl download failed")
        lines = result.stdout.splitlines()
        if len(lines) < 2 or urlparse(lines[-2]).scheme != "https" or lines[-1] != "200":
            raise DownloadError("curl final response identity was invalid")
        if partial.stat().st_size != expected_bytes:
            raise DownloadError("curl download byte size did not match")
        if _sha256(partial) != expected_sha256:
            raise DownloadError("curl download SHA-256 did not match")
        os.replace(partial, target)
        _fsync_directory(target.parent)
    finally:
        partial.unlink(missing_ok=True)


def write_release_marker(
    path: Path,
    *,
    manifest_sha256: str,
    components: list[Mapping[str, object]],
) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError("release marker already exists")
    payload = {
        "schema_version": "vg40-model-release/1",
        "manifest_sha256": manifest_sha256,
        "components": components,
    }
    encoded = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2)
        + "\n"
    ).encode("utf-8")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{secrets.token_hex(8)}.tmp"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(encoded)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _download_one(
    url: str,
    target: Path,
    *,
    expected_bytes: int,
    expected_sha256: str,
    opener: UrlOpen,
) -> None:
    if urlparse(url).scheme != "https":
        raise DownloadError("download URL must use HTTPS")
    if target.exists() or target.is_symlink():
        raise FileExistsError("staging target already exists")
    partial = target.with_name(f".{target.name}.download")
    descriptor = os.open(
        partial,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    digest = hashlib.sha256()
    size = 0
    try:
        request = Request(url, headers={"User-Agent": "AI-Novel-World-VG40/1"})
        with opener(request, timeout=60) as response:  # type: ignore[misc]
            final_url = response.geturl()  # type: ignore[attr-defined]
            if urlparse(final_url).scheme != "https":
                raise DownloadError("download redirect left HTTPS")
            with os.fdopen(descriptor, "wb") as output:
                descriptor = -1
                while chunk := response.read(CHUNK_BYTES):  # type: ignore[attr-defined]
                    size += len(chunk)
                    if size > expected_bytes:
                        raise DownloadError("download exceeded expected byte size")
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
        if size != expected_bytes:
            raise DownloadError("download byte size did not match")
        if digest.hexdigest() != expected_sha256:
            raise DownloadError("download SHA-256 did not match")
        os.replace(partial, target)
        _fsync_directory(target.parent)
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        partial.unlink(missing_ok=True)
        raise


def _require_regular_directory(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        raise DownloadError("directory must exist and may not be a symlink")
    resolved = path.resolve(strict=True)
    if path.absolute() != resolved:
        raise DownloadError("directory path traverses a symlink")
    mode = path.stat().st_mode
    if not stat.S_ISDIR(mode):
        raise DownloadError("path is not a directory")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()
