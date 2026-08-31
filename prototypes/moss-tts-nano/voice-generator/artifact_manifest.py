"""Strict local artifact manifest validation for the Plan 40 model snapshot.

The module performs no network access and cannot download anything.  A later
serial downloader may use the validated manifest, but a snapshot is accepted
only when every regular file exactly matches the frozen allowlist, byte size,
and SHA-256 digest.  Unknown files and symlinks fail closed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
from typing import Mapping


GIB = 1024**3
MANIFEST_SCHEMA = "vg40-model-source-manifest/1"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REVISION = re.compile(r"^[0-9a-f]{40}$")
ALLOWED_COMPONENTS = {
    "voice-generator": ("OpenMOSS-Team/MOSS-VoiceGenerator", "hugging_face"),
    "audio-tokenizer": ("OpenMOSS-Team/MOSS-Audio-Tokenizer", "hugging_face"),
    "moss-tts-source": ("OpenMOSS/MOSS-TTS", "github_raw"),
}


class ManifestError(ValueError):
    pass


def load_manifest(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ManifestError("manifest must be a regular non-symlink file")
    if path.stat().st_size <= 0 or path.stat().st_size > 1024 * 1024:
        raise ManifestError("manifest size is outside the fixed bound")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ManifestError("manifest must be a JSON object")
    validate_manifest(payload)
    return payload


def validate_manifest(payload: Mapping[str, object]) -> None:
    if payload.get("schema_version") != MANIFEST_SCHEMA:
        raise ManifestError("unsupported manifest schema")
    if payload.get("download_ready") is not True:
        raise ManifestError("manifest allowlist is not frozen")
    components = payload.get("components")
    if not isinstance(components, list) or not components:
        raise ManifestError("manifest has no components")
    component_ids: set[str] = set()
    selected_total = 0
    for component in components:
        if not isinstance(component, dict):
            raise ManifestError("component must be an object")
        component_id = component.get("id")
        repository = component.get("repository")
        revision = component.get("revision")
        provider = component.get("provider")
        resolve_base_url = component.get("resolve_base_url")
        selected_bytes = component.get("selected_bytes")
        files = component.get("files")
        if not isinstance(component_id, str) or not component_id:
            raise ManifestError("component id is invalid")
        if component_id in component_ids:
            raise ManifestError("component id is duplicated")
        component_ids.add(component_id)
        expected_identity = ALLOWED_COMPONENTS.get(component_id)
        if expected_identity != (repository, provider):
            raise ManifestError("component identity is outside the exact allowlist")
        if not isinstance(revision, str) or REVISION.fullmatch(revision) is None:
            raise ManifestError("component revision must be a fixed commit")
        expected_base = (
            f"https://huggingface.co/{repository}/resolve/{revision}/"
            if provider == "hugging_face"
            else f"https://raw.githubusercontent.com/{repository}/{revision}/"
        )
        if resolve_base_url != expected_base:
            raise ManifestError("component resolve base URL is not fixed")
        if not isinstance(files, list) or not files:
            raise ManifestError("component file allowlist is empty")
        paths: set[str] = set()
        component_total = 0
        for item in files:
            if not isinstance(item, dict):
                raise ManifestError("file entry must be an object")
            relative = item.get("path")
            size = item.get("bytes")
            digest = item.get("sha256")
            if not isinstance(relative, str) or not _safe_relative_path(relative):
                raise ManifestError("file path is unsafe")
            if relative in paths:
                raise ManifestError("file path is duplicated")
            paths.add(relative)
            if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                raise ManifestError("file byte size is invalid")
            if not isinstance(digest, str) or SHA256.fullmatch(digest) is None:
                raise ManifestError("file SHA-256 is invalid")
            component_total += size
        if selected_bytes != component_total:
            raise ManifestError("component selected byte total does not match")
        selected_total += component_total
    if payload.get("selected_total_bytes") != selected_total:
        raise ManifestError("manifest selected byte total does not match")


def verify_snapshot(
    snapshot_root: Path, component: Mapping[str, object]
) -> dict[str, object]:
    if snapshot_root.is_symlink() or not snapshot_root.is_dir():
        raise ManifestError("snapshot root must be a regular directory")
    root = snapshot_root.resolve(strict=True)
    if snapshot_root.absolute() != root:
        raise ManifestError("snapshot root path traverses a symlink")
    entries = component.get("files")
    if not isinstance(entries, list):
        raise ManifestError("component files are invalid")
    expected = {item["path"]: item for item in entries if isinstance(item, dict)}
    observed: set[str] = set()
    verified: list[dict[str, object]] = []
    for path in root.rglob("*"):
        if path.is_dir() and not path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        observed.add(relative)
        if relative not in expected:
            raise ManifestError("snapshot contains a file outside the allowlist")
        if path.is_symlink() or not path.is_file():
            raise ManifestError("snapshot entry is not a regular file")
        if path.stat().st_nlink != 1:
            raise ManifestError("snapshot entry must have an exclusive inode")
        resolved = path.resolve(strict=True)
        if root not in resolved.parents:
            raise ManifestError("snapshot entry escaped its root")
        specification = expected[relative]
        size = path.stat().st_size
        if size != specification["bytes"]:
            raise ManifestError("snapshot file size does not match")
        digest = _sha256(path)
        if digest != specification["sha256"]:
            raise ManifestError("snapshot file digest does not match")
        verified.append({"path": relative, "bytes": size, "sha256": digest})
    missing = set(expected) - observed
    if missing:
        raise ManifestError("snapshot is missing allowlisted files")
    return {
        "component_id": component.get("id"),
        "revision": component.get("revision"),
        "file_count": len(verified),
        "total_bytes": sum(int(item["bytes"]) for item in verified),
        "files": sorted(verified, key=lambda item: str(item["path"])),
    }


def assert_disk_gate(filesystem_path: Path, projected_download_bytes: int) -> None:
    if projected_download_bytes <= 0:
        raise ManifestError("projected download size must be positive")
    free = shutil.disk_usage(filesystem_path).free
    if free < 42 * GIB:
        raise ManifestError("download filesystem has less than 42 GiB free")
    if free - projected_download_bytes < 24 * GIB:
        raise ManifestError("projected snapshot would leave less than 24 GiB free")


def _safe_relative_path(value: str) -> bool:
    candidate = Path(value)
    return (
        value == candidate.as_posix()
        and not candidate.is_absolute()
        and value not in {"", "."}
        and ".." not in candidate.parts
        and not any(part in {".git", ".cache"} for part in candidate.parts)
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
