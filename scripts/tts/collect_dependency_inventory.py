#!/usr/bin/env python3
"""Validate and optionally refresh the Stage 0 MOSS-TTS dependency inventory.

The default command is network-free and read-only.  Network refreshes, report
writes, and artifact downloads each require an explicit flag.  The script uses
only the Python standard library so the inventory can be checked before model
dependencies are installed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PROTOTYPE_ROOT = REPOSITORY_ROOT / "prototypes" / "moss-tts-nano"
DEFAULT_POLICY = PROTOTYPE_ROOT / "dependencies" / "model-source-policy.json"
DEFAULT_MODEL_LOCK = PROTOTYPE_ROOT / "model-sources.lock.json"
DEFAULT_PYTHON_LOCK = PROTOTYPE_ROOT / "python-requirements.lock"
DEFAULT_PACKAGE_JSON = PROTOTYPE_ROOT / "package.json"
DEFAULT_PNPM_LOCK = PROTOTYPE_ROOT / "pnpm-lock.yaml"

HEX_40 = re.compile(r"^[0-9a-f]{40}$")
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
EXACT_VERSION = re.compile(r"^[0-9]+(?:\.[0-9A-Za-z-]+)+(?:\+[0-9A-Za-z.-]+)?$")
HASH_PATTERN = re.compile(r"--hash=sha256:([0-9a-f]{64})")
USER_AGENT = "ai-novel-world-2026-t0a-inventory/1"


class InventoryError(RuntimeError):
    """Raised for an invalid lock, unsafe target, or upstream mismatch."""


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _pretty_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_blob_sha1_file(path: Path) -> str:
    size = path.stat().st_size
    digest = hashlib.sha1()  # noqa: S324 - Git object identity, not a security primitive.
    digest.update(f"blob {size}\0".encode("ascii"))
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise InventoryError(f"required file is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise InventoryError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise InventoryError(f"top-level JSON value must be an object: {path}")
    return value


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.chmod(0o644)
        temporary_path.replace(path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _request_json(url: str) -> dict[str, Any]:
    payload = _request_bytes(url, accept="application/json")
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise InventoryError(f"upstream returned invalid JSON: {url}: {exc}") from exc
    if not isinstance(value, dict):
        raise InventoryError(f"upstream returned a non-object JSON value: {url}")
    return value


def _request_bytes(url: str, *, accept: str = "application/octet-stream") -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    last_error: Exception | None = None
    for _attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
    raise InventoryError(f"upstream request failed after 3 attempts: {url}: {last_error}")


def _quoted_path(value: str) -> str:
    return urllib.parse.quote(value, safe="/")


def _artifact_from_huggingface(
    *, repository: str, revision: str, path: str, sibling: dict[str, Any]
) -> dict[str, Any]:
    size = sibling.get("size")
    if not isinstance(size, int) or size < 0:
        raise InventoryError(f"Hugging Face metadata has invalid size for {repository}:{path}")
    lfs = sibling.get("lfs")
    if isinstance(lfs, dict) and isinstance(lfs.get("sha256"), str):
        hash_algorithm = "sha256"
        hash_value = lfs["sha256"]
    else:
        hash_algorithm = "git-blob-sha1"
        hash_value = sibling.get("blobId")
    if not isinstance(hash_value, str):
        raise InventoryError(f"Hugging Face metadata has no usable hash for {repository}:{path}")
    return {
        "path": path,
        "url": f"https://huggingface.co/{repository}/resolve/{revision}/{_quoted_path(path)}",
        "size": size,
        "hash_algorithm": hash_algorithm,
        "hash": hash_value,
    }


def _refresh_huggingface(component: dict[str, Any]) -> dict[str, Any]:
    repository = str(component["repository"])
    revision = str(component["revision"])
    encoded_repository = urllib.parse.quote(repository, safe="/")
    metadata_url = f"https://huggingface.co/api/models/{encoded_repository}/revision/{revision}?blobs=true"
    metadata = _request_json(metadata_url)
    if metadata.get("sha") != revision:
        raise InventoryError(
            f"Hugging Face revision mismatch for {repository}: expected {revision}, observed {metadata.get('sha')}"
        )
    siblings = metadata.get("siblings")
    if not isinstance(siblings, list):
        raise InventoryError(f"Hugging Face metadata has no siblings list: {repository}@{revision}")
    sibling_map = {
        str(item.get("rfilename")): item for item in siblings if isinstance(item, dict) and item.get("rfilename")
    }
    artifacts: list[dict[str, Any]] = []
    for path in component.get("include_paths", []):
        sibling = sibling_map.get(str(path))
        if sibling is None:
            raise InventoryError(f"pinned Hugging Face artifact is missing: {repository}@{revision}:{path}")
        artifacts.append(
            _artifact_from_huggingface(
                repository=repository,
                revision=revision,
                path=str(path),
                sibling=sibling,
            )
        )
    observed_license = None
    card_data = metadata.get("cardData")
    if isinstance(card_data, dict):
        observed_license = card_data.get("license")
    if observed_license is None:
        for tag in metadata.get("tags") or []:
            if isinstance(tag, str) and tag.startswith("license:"):
                observed_license = tag.partition(":")[2]
                break
    expected_license = str(component["license"]["spdx"]).lower()
    if isinstance(observed_license, str) and observed_license.lower() != expected_license:
        raise InventoryError(
            f"Hugging Face license mismatch for {repository}: expected {expected_license}, observed {observed_license}"
        )
    selected_bytes = sum(int(item["size"]) for item in artifacts)
    snapshot_bytes = sum(int(item.get("size") or 0) for item in siblings if isinstance(item, dict))
    result = {key: value for key, value in component.items() if key != "include_paths"}
    result.update(
        {
            "metadata_url": metadata_url,
            "observed_license": observed_license,
            "selected_bytes": selected_bytes,
            "snapshot_bytes": snapshot_bytes,
            "artifacts": artifacts,
        }
    )
    return result


def _refresh_github(component: dict[str, Any]) -> dict[str, Any]:
    repository = str(component["repository"])
    revision = str(component["revision"])
    commit_url = f"https://api.github.com/repos/{repository}/commits/{revision}"
    commit = _request_json(commit_url)
    if commit.get("sha") != revision:
        raise InventoryError(
            f"GitHub revision mismatch for {repository}: expected {revision}, observed {commit.get('sha')}"
        )
    artifacts: list[dict[str, Any]] = []
    for path in component.get("include_paths", []):
        raw_url = f"https://raw.githubusercontent.com/{repository}/{revision}/{_quoted_path(str(path))}"
        payload = _request_bytes(raw_url)
        digest = hashlib.sha1()  # noqa: S324 - Git object identity, not a security primitive.
        digest.update(f"blob {len(payload)}\0".encode("ascii"))
        digest.update(payload)
        artifacts.append(
            {
                "path": str(path),
                "url": raw_url,
                "size": len(payload),
                "hash_algorithm": "git-blob-sha1",
                "hash": digest.hexdigest(),
            }
        )
    result = {key: value for key, value in component.items() if key != "include_paths"}
    result.update(
        {
            "metadata_url": commit_url,
            "selected_bytes": sum(int(item["size"]) for item in artifacts),
            "artifacts": artifacts,
        }
    )
    return result


def build_model_lock(policy: dict[str, Any]) -> dict[str, Any]:
    if policy.get("schema_version") != 1:
        raise InventoryError("model source policy schema_version must be 1")
    policy_components = policy.get("components")
    if not isinstance(policy_components, list) or not policy_components:
        raise InventoryError("model source policy components must be a non-empty list")
    components: list[dict[str, Any]] = []
    for component in policy_components:
        if not isinstance(component, dict):
            raise InventoryError("model source policy contains a non-object component")
        provider = component.get("provider")
        if provider == "huggingface":
            refreshed = _refresh_huggingface(component)
        elif provider == "github":
            refreshed = _refresh_github(component)
        elif provider == "static":
            refreshed = dict(component)
            refreshed.pop("include_paths", None)
            refreshed["selected_bytes"] = sum(
                int(item.get("size") or 0) for item in refreshed.get("artifacts", []) if isinstance(item, dict)
            )
        else:
            raise InventoryError(f"unsupported model source provider: {provider}")
        components.append(refreshed)
    return {
        "schema_version": 1,
        "captured_on": policy.get("captured_on"),
        "python_target": policy.get("python_target"),
        "platform_target": policy.get("platform_target"),
        "policy_sha256": _sha256_bytes(_json_bytes(policy)),
        "component_count": len(components),
        "components": components,
    }


def _validate_model_lock(lock: dict[str, Any], local_assets_root: Path | None) -> tuple[list[dict[str, Any]], int]:
    findings: list[dict[str, Any]] = []
    skipped_local = 0
    if lock.get("schema_version") != 1:
        findings.append({"severity": "error", "code": "model-lock-schema", "message": "schema_version must be 1"})
    components = lock.get("components")
    if not isinstance(components, list) or not components:
        findings.append({"severity": "error", "code": "model-lock-components", "message": "components are missing"})
        return findings, skipped_local
    seen_components: set[str] = set()
    for component in components:
        if not isinstance(component, dict):
            findings.append({"severity": "error", "code": "component-type", "message": "component is not an object"})
            continue
        component_id = str(component.get("component_id") or "")
        if not component_id or component_id in seen_components:
            findings.append(
                {"severity": "error", "code": "component-id", "message": f"missing or duplicate component id: {component_id}"}
            )
        seen_components.add(component_id)
        revision = str(component.get("revision") or "")
        if not HEX_40.fullmatch(revision):
            findings.append(
                {"severity": "error", "code": "revision", "component": component_id, "message": "revision is not a 40-hex commit"}
            )
        license_data = component.get("license")
        if not isinstance(license_data, dict) or not license_data.get("spdx") or not license_data.get("status"):
            findings.append(
                {"severity": "error", "code": "license", "component": component_id, "message": "license metadata is incomplete"}
            )
        artifacts = component.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            findings.append(
                {"severity": "error", "code": "artifacts", "component": component_id, "message": "artifact list is empty"}
            )
            continue
        seen_paths: set[str] = set()
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                findings.append(
                    {"severity": "error", "code": "artifact-type", "component": component_id, "message": "artifact is not an object"}
                )
                continue
            relative_path = str(artifact.get("path") or "")
            path_object = Path(relative_path)
            if not relative_path or path_object.is_absolute() or ".." in path_object.parts or relative_path in seen_paths:
                findings.append(
                    {"severity": "error", "code": "artifact-path", "component": component_id, "message": f"unsafe or duplicate path: {relative_path}"}
                )
            seen_paths.add(relative_path)
            url = str(artifact.get("url") or "")
            if not url.startswith("https://"):
                findings.append(
                    {"severity": "error", "code": "artifact-url", "component": component_id, "message": f"non-HTTPS URL: {relative_path}"}
                )
            algorithm = artifact.get("hash_algorithm")
            hash_value = str(artifact.get("hash") or "")
            if algorithm == "sha256":
                valid_hash = HEX_64.fullmatch(hash_value) is not None
            elif algorithm == "git-blob-sha1":
                valid_hash = HEX_40.fullmatch(hash_value) is not None
            else:
                valid_hash = False
            if not valid_hash:
                findings.append(
                    {"severity": "error", "code": "artifact-hash", "component": component_id, "message": f"invalid hash: {relative_path}"}
                )
            if not isinstance(artifact.get("size"), int) or int(artifact.get("size") or 0) < 0:
                findings.append(
                    {"severity": "error", "code": "artifact-size", "component": component_id, "message": f"invalid size: {relative_path}"}
                )
            if local_assets_root is None:
                skipped_local += 1
                continue
            local_path = (local_assets_root / component_id / relative_path).resolve()
            expected_root = (local_assets_root / component_id).resolve()
            if expected_root != local_path and expected_root not in local_path.parents:
                findings.append(
                    {"severity": "error", "code": "local-path", "component": component_id, "message": f"escaped local root: {relative_path}"}
                )
                continue
            if not local_path.is_file():
                skipped_local += 1
                continue
            observed_size = local_path.stat().st_size
            observed_hash = _sha256_file(local_path) if algorithm == "sha256" else _git_blob_sha1_file(local_path)
            if observed_size != artifact["size"] or observed_hash != hash_value:
                findings.append(
                    {"severity": "error", "code": "local-integrity", "component": component_id, "message": f"local artifact mismatch: {relative_path}"}
                )
    return findings, skipped_local


def _current_runtime_target() -> str:
    machine = platform.machine().lower()
    if machine == "aarch64":
        machine = "arm64"
    return f"{platform.system().lower()}-{machine}"


def _validate_tool_runtimes(
    lock: dict[str, Any], runtime_root: Path | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate locked, locally built tool artifacts without relying on PATH."""

    findings: list[dict[str, Any]] = []
    observed_builds: list[dict[str, Any]] = []
    matching_builds = 0
    target = _current_runtime_target()
    for component in lock.get("components", []):
        if not isinstance(component, dict):
            continue
        component_id = str(component.get("component_id") or "")
        runtime_builds = component.get("runtime_builds") or []
        if not isinstance(runtime_builds, list):
            findings.append(
                {
                    "severity": "error",
                    "code": "tool-runtime-builds",
                    "component": component_id,
                    "message": "runtime_builds must be a list",
                }
            )
            continue
        for build in runtime_builds:
            if not isinstance(build, dict):
                findings.append(
                    {
                        "severity": "error",
                        "code": "tool-runtime-build",
                        "component": component_id,
                        "message": "runtime build is not an object",
                    }
                )
                continue
            build_id = str(build.get("build_id") or "")
            build_target = str(build.get("target") or "")
            layout = str(build.get("runtime_layout") or "")
            layout_path = Path(layout)
            if not build_id or not build_target or not layout or layout_path.is_absolute() or ".." in layout_path.parts:
                findings.append(
                    {
                        "severity": "error",
                        "code": "tool-runtime-identity",
                        "component": component_id,
                        "message": f"invalid runtime build identity/layout: {build_id}",
                    }
                )
                continue
            configure_arguments = build.get("configure_arguments")
            if not isinstance(configure_arguments, list) or not configure_arguments or not all(
                isinstance(item, str) and item.startswith("--") for item in configure_arguments
            ):
                findings.append(
                    {
                        "severity": "error",
                        "code": "tool-runtime-configure",
                        "component": component_id,
                        "message": f"invalid configure arguments: {build_id}",
                    }
                )
            artifacts = build.get("runtime_artifacts")
            if not isinstance(artifacts, list) or not artifacts:
                findings.append(
                    {
                        "severity": "error",
                        "code": "tool-runtime-artifacts",
                        "component": component_id,
                        "message": f"runtime artifact list is empty: {build_id}",
                    }
                )
                continue
            if runtime_root is None or build_target != target:
                continue
            matching_builds += 1
            observed_artifacts: list[dict[str, Any]] = []
            for artifact in artifacts:
                if not isinstance(artifact, dict):
                    findings.append(
                        {
                            "severity": "error",
                            "code": "tool-runtime-artifact",
                            "component": component_id,
                            "message": f"runtime artifact is not an object: {build_id}",
                        }
                    )
                    continue
                relative_path = str(artifact.get("path") or "")
                path_object = Path(relative_path)
                expected_hash = str(artifact.get("sha256") or "")
                expected_size = artifact.get("size")
                if (
                    not relative_path
                    or path_object.is_absolute()
                    or ".." in path_object.parts
                    or HEX_64.fullmatch(expected_hash) is None
                    or not isinstance(expected_size, int)
                    or expected_size < 0
                ):
                    findings.append(
                        {
                            "severity": "error",
                            "code": "tool-runtime-artifact-lock",
                            "component": component_id,
                            "message": f"invalid locked runtime artifact: {build_id}/{relative_path}",
                        }
                    )
                    continue
                build_root = (runtime_root / layout).resolve()
                local_path = (build_root / relative_path).resolve()
                if build_root != local_path and build_root not in local_path.parents:
                    findings.append(
                        {
                            "severity": "error",
                            "code": "tool-runtime-path",
                            "component": component_id,
                            "message": f"escaped runtime root: {build_id}/{relative_path}",
                        }
                    )
                    continue
                if not local_path.is_file():
                    findings.append(
                        {
                            "severity": "error",
                            "code": "tool-runtime-missing",
                            "component": component_id,
                            "message": f"missing runtime artifact: {build_id}/{relative_path}",
                        }
                    )
                    continue
                observed_size = local_path.stat().st_size
                observed_hash = _sha256_file(local_path)
                status = "present" if observed_size == expected_size and observed_hash == expected_hash else "mismatch"
                if status == "mismatch":
                    findings.append(
                        {
                            "severity": "error",
                            "code": "tool-runtime-integrity",
                            "component": component_id,
                            "message": f"runtime artifact mismatch: {build_id}/{relative_path}",
                        }
                    )
                if relative_path.startswith("bin/") and not os.access(local_path, os.X_OK):
                    findings.append(
                        {
                            "severity": "error",
                            "code": "tool-runtime-executable",
                            "component": component_id,
                            "message": f"runtime binary is not executable: {build_id}/{relative_path}",
                        }
                    )
                observed_artifacts.append(
                    {
                        "path": relative_path,
                        "sha256": observed_hash,
                        "size": observed_size,
                        "status": status,
                    }
                )
            observed_builds.append(
                {
                    "component_id": component_id,
                    "build_id": build_id,
                    "target": build_target,
                    "runtime_layout": layout,
                    "status": "present"
                    if len(observed_artifacts) == len(artifacts)
                    and all(item["status"] == "present" for item in observed_artifacts)
                    else "incomplete",
                    "artifacts": observed_artifacts,
                }
            )
    if runtime_root is not None and matching_builds == 0:
        findings.append(
            {
                "severity": "error",
                "code": "tool-runtime-target",
                "message": f"no locked runtime build matches {target}",
            }
        )
    return findings, observed_builds


def _logical_requirement_lines(text: str) -> Iterable[str]:
    current = ""
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.endswith("\\"):
            current += stripped[:-1].strip() + " "
            continue
        current += stripped
        yield current.strip()
        current = ""
    if current:
        yield current.strip()


def _validate_python_lock(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    packages: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [{"severity": "error", "code": "python-lock-missing", "message": str(path)}], packages
    for line in _logical_requirement_lines(text):
        if line.startswith("--"):
            continue
        requirement = line.split(" --hash=", 1)[0].strip()
        hashes = HASH_PATTERN.findall(line)
        if "==" not in requirement:
            findings.append({"severity": "error", "code": "python-unpinned", "message": requirement})
            continue
        name, version = requirement.split("==", 1)
        version = version.split(";", 1)[0].strip()
        if not name.strip() or not EXACT_VERSION.fullmatch(version):
            findings.append({"severity": "error", "code": "python-version", "message": requirement})
        if not hashes:
            findings.append({"severity": "error", "code": "python-hash", "message": requirement})
        packages.append({"name": name.strip().lower(), "version": version, "sha256_count": len(set(hashes))})
    if not packages:
        findings.append({"severity": "error", "code": "python-lock-empty", "message": str(path)})
    packages.sort(key=lambda item: item["name"])
    return findings, packages


def _validate_node_locks(package_path: Path, pnpm_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    findings: list[dict[str, Any]] = []
    packages: list[dict[str, Any]] = []
    try:
        package_data = _load_json(package_path)
    except InventoryError as exc:
        return [{"severity": "error", "code": "package-json", "message": str(exc)}], packages, 0
    for section in ("dependencies", "devDependencies"):
        values = package_data.get(section) or {}
        if not isinstance(values, dict):
            findings.append({"severity": "error", "code": "package-section", "message": section})
            continue
        for name, version_value in values.items():
            version = str(version_value)
            if not EXACT_VERSION.fullmatch(version):
                findings.append(
                    {"severity": "error", "code": "node-unpinned", "message": f"{name}@{version}"}
                )
            packages.append({"name": str(name), "version": version, "scope": section})
    packages.sort(key=lambda item: (item["scope"], item["name"]))
    try:
        pnpm_text = pnpm_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        findings.append({"severity": "error", "code": "pnpm-lock-missing", "message": str(pnpm_path)})
        return findings, packages, 0
    if not re.search(r"^lockfileVersion:\s*['\"]?9\.0['\"]?\s*$", pnpm_text, re.MULTILINE):
        findings.append({"severity": "error", "code": "pnpm-lock-version", "message": "expected lockfileVersion 9.0"})
    integrity_count = len(re.findall(r"\bintegrity:\s*sha512-", pnpm_text))
    if integrity_count == 0:
        findings.append({"severity": "error", "code": "pnpm-integrity", "message": "no sha512 integrity entries"})
    return findings, packages, integrity_count


def _verify_artifact(path: Path, artifact: dict[str, Any]) -> None:
    expected_size = int(artifact["size"])
    observed_size = path.stat().st_size
    if observed_size != expected_size:
        raise InventoryError(f"size mismatch for {path}: expected {expected_size}, observed {observed_size}")
    algorithm = artifact["hash_algorithm"]
    observed_hash = _sha256_file(path) if algorithm == "sha256" else _git_blob_sha1_file(path)
    if observed_hash != artifact["hash"]:
        raise InventoryError(
            f"hash mismatch for {path}: expected {artifact['hash']}, observed {observed_hash}"
        )


def _download_components(
    *,
    lock: dict[str, Any],
    component_ids: list[str],
    download_dir: Path,
    max_download_bytes: int,
    allow_large_downloads: bool,
) -> list[dict[str, Any]]:
    component_map = {
        str(item.get("component_id")): item for item in lock.get("components", []) if isinstance(item, dict)
    }
    results: list[dict[str, Any]] = []
    download_root = download_dir.resolve()
    download_root.mkdir(parents=True, exist_ok=True)
    for component_id in component_ids:
        component = component_map.get(component_id)
        if component is None:
            raise InventoryError(f"unknown download component: {component_id}")
        if component.get("download_allowed") is not True:
            raise InventoryError(f"download is forbidden by policy for component: {component_id}")
        for artifact in component.get("artifacts", []):
            size = int(artifact["size"])
            if size > max_download_bytes and not allow_large_downloads:
                raise InventoryError(
                    f"artifact exceeds --max-download-bytes ({max_download_bytes}): "
                    f"{component_id}/{artifact['path']} ({size}); use --allow-large-downloads explicitly"
                )
            target = (download_root / component_id / str(artifact["path"])).resolve()
            if download_root != target and download_root not in target.parents:
                raise InventoryError(f"unsafe download target: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_file():
                _verify_artifact(target, artifact)
                results.append({"component_id": component_id, "path": artifact["path"], "status": "reused"})
                continue
            temporary = target.with_name(f".{target.name}.part")
            request = urllib.request.Request(str(artifact["url"]), headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as output:
                    shutil.copyfileobj(response, output, length=1024 * 1024)
                _verify_artifact(temporary, artifact)
                temporary.replace(target)
            except Exception:
                temporary.unlink(missing_ok=True)
                raise
            results.append({"component_id": component_id, "path": artifact["path"], "status": "downloaded"})
    return results


def _path_argument(value: str) -> Path:
    return Path(value).expanduser().resolve()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate the frozen MOSS-TTS Stage 0 dependency/model inventory without downloading by default."
    )
    parser.add_argument("--policy", type=_path_argument, default=DEFAULT_POLICY)
    parser.add_argument("--model-lock", type=_path_argument, default=DEFAULT_MODEL_LOCK)
    parser.add_argument("--python-lock", type=_path_argument, default=DEFAULT_PYTHON_LOCK)
    parser.add_argument("--package-json", type=_path_argument, default=DEFAULT_PACKAGE_JSON)
    parser.add_argument("--pnpm-lock", type=_path_argument, default=DEFAULT_PNPM_LOCK)
    parser.add_argument(
        "--refresh-model-lock",
        action="store_true",
        help="Explicitly read official upstream metadata and atomically rewrite --model-lock.",
    )
    parser.add_argument(
        "--check-remote",
        action="store_true",
        help="Read official upstream metadata and require it to match the existing lock; does not write.",
    )
    parser.add_argument(
        "--local-assets-root",
        type=_path_argument,
        help="Optionally verify present files under ROOT/<component_id>/<artifact path>; missing files are skipped.",
    )
    parser.add_argument(
        "--local-tool-runtime-root",
        type=_path_argument,
        help="Verify the current platform's locked tool build under ROOT/<runtime_layout>; missing files fail.",
    )
    parser.add_argument(
        "--download-component",
        action="append",
        default=[],
        metavar="COMPONENT_ID",
        help="Explicit opt-in download for one pinned component. May be repeated and requires --download-dir.",
    )
    parser.add_argument("--download-dir", type=_path_argument)
    parser.add_argument("--max-download-bytes", type=int, default=25_000_000)
    parser.add_argument(
        "--allow-large-downloads",
        action="store_true",
        help="Second opt-in required for any artifact larger than --max-download-bytes.",
    )
    parser.add_argument(
        "--output",
        type=_path_argument,
        help="Explicitly write the stable JSON validation report. Without this flag only stdout is used.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.download_component and args.download_dir is None:
            raise InventoryError("--download-component requires --download-dir")
        if args.allow_large_downloads and not args.download_component:
            raise InventoryError("--allow-large-downloads is only valid with --download-component")
        policy = _load_json(args.policy)
        if args.refresh_model_lock:
            refreshed_lock = build_model_lock(policy)
            _atomic_write(args.model_lock, _pretty_json(refreshed_lock).encode("utf-8"))
        lock = _load_json(args.model_lock)
        findings, skipped_local = _validate_model_lock(lock, args.local_assets_root)
        tool_findings, tool_runtime_builds = _validate_tool_runtimes(lock, args.local_tool_runtime_root)
        findings.extend(tool_findings)
        python_findings, python_packages = _validate_python_lock(args.python_lock)
        node_findings, node_packages, pnpm_integrity_count = _validate_node_locks(
            args.package_json, args.pnpm_lock
        )
        findings.extend(python_findings)
        findings.extend(node_findings)
        if args.check_remote:
            remote_lock = build_model_lock(policy)
            if _json_bytes(remote_lock) != _json_bytes(lock):
                findings.append(
                    {
                        "severity": "error",
                        "code": "remote-lock-drift",
                        "message": "official metadata differs from model-sources.lock.json",
                    }
                )
        download_results: list[dict[str, Any]] = []
        if args.download_component:
            download_results = _download_components(
                lock=lock,
                component_ids=args.download_component,
                download_dir=args.download_dir,
                max_download_bytes=args.max_download_bytes,
                allow_large_downloads=args.allow_large_downloads,
            )
        error_count = sum(1 for item in findings if item.get("severity") == "error")
        warning_count = sum(1 for item in findings if item.get("severity") == "warning")
        artifact_count = sum(
            len(item.get("artifacts", [])) for item in lock.get("components", []) if isinstance(item, dict)
        )
        report = {
            "schema_version": 1,
            "status": "pass" if error_count == 0 else "fail",
            "inputs": {
                "model_lock": str(args.model_lock.relative_to(REPOSITORY_ROOT))
                if args.model_lock.is_relative_to(REPOSITORY_ROOT)
                else args.model_lock.name,
                "model_lock_sha256": _sha256_file(args.model_lock),
                "python_lock": str(args.python_lock.relative_to(REPOSITORY_ROOT))
                if args.python_lock.is_relative_to(REPOSITORY_ROOT)
                else args.python_lock.name,
                "python_lock_sha256": _sha256_file(args.python_lock),
                "package_json_sha256": _sha256_file(args.package_json),
                "pnpm_lock_sha256": _sha256_file(args.pnpm_lock),
                "remote_checked": bool(args.check_remote or args.refresh_model_lock),
                "tool_runtime_checked": args.local_tool_runtime_root is not None,
            },
            "runtime": {
                "python": platform.python_version(),
                "implementation": platform.python_implementation(),
                "machine": platform.machine(),
                "system": platform.system(),
            },
            "counts": {
                "components": len(lock.get("components", [])),
                "artifacts": artifact_count,
                "python_packages": len(python_packages),
                "node_direct_packages": len(node_packages),
                "pnpm_sha512_integrities": pnpm_integrity_count,
                "errors": error_count,
                "warnings": warning_count,
                "local_artifacts_present": artifact_count - skipped_local,
                "skipped_local_artifacts": skipped_local,
                "downloads": len(download_results),
                "tool_runtime_builds_present": sum(
                    1 for item in tool_runtime_builds if item.get("status") == "present"
                ),
                "tool_runtime_artifacts_present": sum(
                    1
                    for build in tool_runtime_builds
                    for item in build.get("artifacts", [])
                    if item.get("status") == "present"
                ),
            },
            "python_packages": python_packages,
            "node_direct_packages": node_packages,
            "tool_runtime_builds": tool_runtime_builds,
            "findings": sorted(findings, key=lambda item: (str(item.get("severity")), str(item.get("code")), str(item.get("message")))),
            "downloads": download_results,
        }
        rendered = _pretty_json(report)
        if args.output is not None:
            _atomic_write(args.output, rendered.encode("utf-8"))
        sys.stdout.write(rendered)
        return 0 if error_count == 0 else 1
    except (InventoryError, OSError, ValueError, urllib.error.URLError) as exc:
        failure = {"schema_version": 1, "status": "error", "error": str(exc)}
        sys.stdout.write(_pretty_json(failure))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
