#!/usr/bin/env python3
"""Content identity for the fixed T4-K controller implementation."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Final


CONTROLLER_BUILD_SCHEMA: Final = "moss-tts-t4k-controller-build/1.0"
REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
CONTROLLER_SOURCE_PATHS: Final = (
    "backend/narration/release_gate.py",
    "scripts/tts/chapter_e2e_browser_observer.py",
    "scripts/tts/chapter_e2e_collector.py",
    "scripts/tts/chapter_e2e_controller_build.py",
    "scripts/tts/chapter_e2e_controller_evidence.py",
    "scripts/tts/chapter_e2e_controller_host.py",
    "scripts/tts/chapter_e2e_controller_lifecycle.py",
    "scripts/tts/chapter_e2e_controller_signer.py",
    "scripts/tts/chapter_e2e_controller_trust.py",
    "scripts/tts/chapter_e2e_executor.py",
    "scripts/tts/chapter_e2e_metric_chain.py",
    "scripts/tts/chapter_e2e_probe_request.py",
    "scripts/tts/chapter_e2e_probes.py",
    "scripts/tts/chapter_e2e_runtime_observer.py",
    "scripts/tts/validate_chapter_e2e.py",
    "scripts/tts/controller_node_runtime.py",
    "scripts/tts/controller_ssh_askpass.sh",
    "scripts/tts/controller-node/bootstrap_node_runtime.py",
    "scripts/tts/controller-node/runtime-lock.json",
    "scripts/tts/controller-node/package.json",
    "scripts/tts/controller-node/pnpm-lock.yaml",
    "scripts/tts/controller-node/bin/observe.mjs",
    "scripts/tts/controller-node/src/contracts.mjs",
    "scripts/tts/controller-node/src/observer.mjs",
    "scripts/tts/controller-node/src/runtime-identity.mjs",
)
LOCAL_OPERATOR_SOURCE_PATHS: Final = tuple(
    path
    for path in CONTROLLER_SOURCE_PATHS
    if path
    not in {
        "scripts/tts/chapter_e2e_controller_host.py",
        "scripts/tts/chapter_e2e_controller_signer.py",
        "scripts/tts/chapter_e2e_controller_trust.py",
        "scripts/tts/controller_ssh_askpass.sh",
    }
)


class ControllerBuildError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("CONTROLLER_BUILD_IDENTITY_INVALID")


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")


def _source_set_sha256(paths: tuple[str, ...]) -> str:
    """Hash one fixed controller source set in a stable order."""

    files: list[dict[str, str]] = []
    try:
        for relative in paths:
            path = REPOSITORY_ROOT / relative
            details = path.lstat()
            resolved = path.resolve(strict=True)
            if (
                stat.S_ISLNK(details.st_mode)
                or not stat.S_ISREG(details.st_mode)
                or details.st_uid != os.getuid()
                or stat.S_IMODE(details.st_mode) & 0o022
                or details.st_nlink != 1
                or not resolved.is_relative_to(REPOSITORY_ROOT)
            ):
                raise ControllerBuildError
            with path.open("rb") as handle:
                digest = hashlib.file_digest(handle, "sha256").hexdigest()
            files.append({"path": relative, "sha256": digest})
    except ControllerBuildError:
        raise
    except OSError:
        raise ControllerBuildError from None
    return hashlib.sha256(
        _canonical({"files": files, "schema_version": CONTROLLER_BUILD_SCHEMA})
    ).hexdigest()


def fixed_controller_build_sha256() -> str:
    """Hash the historical signed-controller candidate source set."""

    return _source_set_sha256(CONTROLLER_SOURCE_PATHS)


def fixed_local_operator_build_sha256() -> str:
    """Hash only the active unsigned local-operator executor source set."""

    return _source_set_sha256(LOCAL_OPERATOR_SOURCE_PATHS)


__all__ = [
    "CONTROLLER_BUILD_SCHEMA",
    "LOCAL_OPERATOR_SOURCE_PATHS",
    "ControllerBuildError",
    "fixed_controller_build_sha256",
    "fixed_local_operator_build_sha256",
]
