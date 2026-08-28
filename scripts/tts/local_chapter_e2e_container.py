#!/usr/bin/env python3
"""Container-side helper for a transient repository-hosted T4-K run.

This file is copied into the existing QwenPaw container as part of a sealed
per-run tool bundle.  It is not a PawApp payload and it never accepts a URL,
database URL, import path, browser, selector, viewport, output directory or
container name.  All mutable paths are derived from one canonical run UUID.
"""

from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import sys
import time
from typing import Final, Mapping, Sequence
from uuid import UUID


SCHEMA_VERSION: Final = "moss-tts-t4k-local-container/1.0"
BUNDLE_SCHEMA_VERSION: Final = "moss-tts-t4k-tool-bundle/1.0"
SECRET_PROJECT_ROOT: Final = Path(
    "/app/working.secret/ai-novel-world-2026"
)
RUNS_ROOT: Final = SECRET_PROJECT_ROOT / "t4k-runs"
INSTALLED_PLUGIN_ROOT: Final = Path(
    "/app/working/plugins/ai-novel-world-2026"
)
FIXTURE_RELATIVE_PATH: Final = (
    "tests/fixtures/narration/chapter-e2e-v3.json"
)
BUNDLE_MANIFEST_NAME: Final = "bundle-manifest.json"
REPORT_FILENAMES: Final = (
    "collector-report.json",
    "probe-report.json",
    "collector-report.commit.json",
)
EXPECTED_VOICES: Final = (
    ("narrator", "onnx.Zhiming"),
    ("林晚", "onnx.Xiaoyu"),
    ("沈川", "onnx.Junhao"),
)
EXPECTED_CAPTURES: Final = tuple(
    (width, height, assistant_mode)
    for width, height in ((1920, 1080), (2560, 1440))
    for assistant_mode in ("collapsed", "expanded")
)
BUNDLE_RELATIVE_PATHS: Final = (
    "scripts/tts/chapter_e2e_collector.py",
    "scripts/tts/chapter_e2e_controller_trust.py",
    "scripts/tts/chapter_e2e_executor.py",
    "scripts/tts/chapter_e2e_listening.py",
    "scripts/tts/chapter_e2e_metric_chain.py",
    "scripts/tts/chapter_e2e_operator_envelope.py",
    "scripts/tts/chapter_e2e_probe_request.py",
    "scripts/tts/chapter_e2e_probes.py",
    "scripts/tts/chapter_e2e_readiness.py",
    "scripts/tts/chapter_e2e_runtime_audit.py",
    "scripts/tts/local_chapter_e2e_container.py",
    "scripts/tts/run_chapter_e2e_real.py",
    "scripts/tts/validate_chapter_e2e.py",
    FIXTURE_RELATIVE_PATH,
)
CONFIRMATIONS: Final = {
    "verify-stage": "VERIFY-T4K-LOCAL-STAGE",
    "prepare": "PREPARE-T4K-LOCAL-RUN",
    "import-report": "IMPORT-T4K-LOCAL-REPORT",
    "status": "STATUS-T4K-LOCAL-RUN",
    "cleanup": "CLEANUP-T4K-LOCAL-TOOLS",
    "arm-claim-gate": "ARM-T4K-SEGMENT-CLAIM-GATE",
    "release-claim-gate": "RELEASE-T4K-SEGMENT-CLAIM-GATE",
    "stop-launcher": "STOP-T4K-LOCAL-LAUNCHER",
    "require-partial-ready-capability": (
        "REQUIRE-T4K-PARTIAL-READY-CAPABILITY"
    ),
}
VALIDATION_TOKEN_FILE: Final = (
    SECRET_PROJECT_ROOT / "t4k-validation" / "token"
)
VALIDATION_TOKEN_HEADER: Final = "X-AI-Novel-TTS-Validation"
PARTIAL_READY_LAUNCHER_CAPABILITY: Final = (
    "claim-gate-v1/cache-hit-prefix-miss-suffix/partial-ready-browser"
)
PARTIAL_READY_LAUNCHER_MARKER: Final = (
    "T4K_PARTIAL_READY_VALIDATION_CAPABILITY"
)
_VALIDATION_TOKEN: Final = re.compile(r"^[A-Za-z0-9_-]{43,128}$")
_SHA256: Final = re.compile(r"^[0-9a-f]{64}$")
_MAX_JSON_BYTES: Final = 256 * 1024
RESULT_SCHEMA_VERSION: Final = "moss-tts-chapter-e2e-result/2.3"
LEGACY_RECOVERY_SCHEMA_VERSION: Final = "moss-tts-chapter-e2e-recovery/3.0"
PREVIOUS_RECOVERY_SCHEMA_VERSION: Final = "moss-tts-chapter-e2e-recovery/3.1"
RECOVERY_SCHEMA_VERSION: Final = "moss-tts-chapter-e2e-recovery/3.2"
SUPPORTED_RECOVERY_SCHEMA_VERSIONS: Final = frozenset(
    {
        LEGACY_RECOVERY_SCHEMA_VERSION,
        PREVIOUS_RECOVERY_SCHEMA_VERSION,
        RECOVERY_SCHEMA_VERSION,
    }
)
WORK_PACKAGE: Final = "T4-K"
_FINAL_STATUSES: Final = frozenset(
    {"PASS_CANDIDATE", "TECHNICAL_PASS_CANDIDATE", "BASELINE_RESTORED"}
)
_KNOWN_RESULT_STATUSES: Final = frozenset(
    {
        *_FINAL_STATUSES,
        "HUMAN_LISTENING_PENDING",
        "FAILED",
        "RECOVERY_REQUIRED",
    }
)
_RESULT_KEYS: Final = frozenset(
    {
        "schema_version",
        "work_package",
        "run_fingerprint_sha256",
        "created_at",
        "mode",
        "status",
        "fixture",
        "target_scope_sha256",
        "api",
        "duration_minutes",
        "required_viewports",
        "safety",
        "automatic_chain",
        "manual_chain",
        "technical_checks",
        "human_listening",
        "recovery",
        "error_codes",
    }
)
_SIDECAR_PEAK_MEMORY_LIMIT_BYTES: Final = 4 * 1024 * 1024 * 1024
_SIDECAR_MEMORY_GROWTH_MIN_LIMIT_BYTES: Final = 128 * 1024 * 1024
_SIDECAR_MEMORY_GROWTH_PERCENT_NUMERATOR: Final = 5
_SIDECAR_MEMORY_GROWTH_PERCENT_DENOMINATOR: Final = 100
_TECHNICAL_KEYS: Final = frozenset(
    {
        "state",
        "stability_elapsed_seconds",
        "chapter_audio_duration_seconds",
        "request_to_ready_seconds",
        "black_box_rtf",
        "performance_gate",
        "time_to_first_audio_ms",
        "peak_memory_bytes",
        "range_status_codes",
        "seam_pairs_checked",
        "seek_latest_wins",
        "pending_gap_not_skipped",
        "edit_actions_created_tts_writes",
        "evidence_class",
        "evidence_root_sha256",
        "browser_viewports",
        "browser_assistant_modes",
        "browser_console_error_count",
        "browser_overlap_count",
        "sidecar_restart_count",
        "health_failure_count",
        "listening_output_hashes",
        "collector_collected_at",
        "rtf_kind",
    }
)
_PERFORMANCE_GATE_KEYS: Final = frozenset(
    {
        "black_box_rtf_limit",
        "black_box_rtf_passed",
        "progressive_playback_alternative",
        "host_paging_observed",
        "host_paging_interpretation",
        "pageout_delta",
        "swapout_delta",
        "memory_baseline_median_bytes",
        "memory_tail_median_bytes",
        "memory_growth_bytes",
        "memory_growth_limit_bytes",
        "sidecar_memory_growth_observed",
        "qwenpaw_slowdown_observed",
        "sidecar_peak_memory_limit_bytes",
        "memory_safety_passed",
    }
)


class ContainerHelperError(RuntimeError):
    """Stable redacted failure at the container boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # pragma: no cover - argparse text
        del message
        raise ContainerHelperError("LOCAL_CONTAINER_ARGUMENTS_INVALID")


def build_parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--mode", choices=tuple(CONFIRMATIONS), required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--novel-id", required=True)
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--confirm", required=True)
    return parser


def _canonical_uuid(value: object, code: str) -> str:
    if type(value) is not str:
        raise ContainerHelperError(code)
    try:
        canonical = str(UUID(value))
    except (AttributeError, TypeError, ValueError):
        raise ContainerHelperError(code) from None
    if canonical != value:
        raise ContainerHelperError(code)
    return canonical


def _canonical_json_payload_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _canonical_json_bytes(value: object) -> bytes:
    return _canonical_json_payload_bytes(value) + b"\n"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _strict_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ContainerHelperError("LOCAL_CONTAINER_JSON_INVALID")
        result[key] = value
    return result


def _read_json(path: Path, *, code: str) -> tuple[bytes, Mapping[str, object]]:
    try:
        details = path.lstat()
        if (
            not stat.S_ISREG(details.st_mode)
            or stat.S_ISLNK(details.st_mode)
            or details.st_uid != os.getuid()
            or details.st_nlink != 1
            or stat.S_IMODE(details.st_mode) != 0o600
            or not 0 < details.st_size <= _MAX_JSON_BYTES
        ):
            raise ContainerHelperError(code)
        raw = path.read_bytes()
        if len(raw) != details.st_size:
            raise ContainerHelperError(code)
        payload = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ContainerHelperError(code)
            ),
        )
    except ContainerHelperError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ContainerHelperError(code) from None
    if type(payload) is not dict:
        raise ContainerHelperError(code)
    return raw, payload


def _require_directory(path: Path, *, code: str) -> os.stat_result:
    try:
        supplied = path.lstat()
        resolved = path.resolve(strict=True)
        resolved_details = resolved.lstat()
    except OSError:
        raise ContainerHelperError(code) from None
    if (
        resolved != path
        or stat.S_ISLNK(supplied.st_mode)
        or not stat.S_ISDIR(supplied.st_mode)
        or stat.S_IMODE(supplied.st_mode) != 0o700
        or supplied.st_uid != os.getuid()
        or (supplied.st_dev, supplied.st_ino)
        != (resolved_details.st_dev, resolved_details.st_ino)
    ):
        raise ContainerHelperError(code)
    return supplied


def _require_private_file(path: Path, *, code: str) -> os.stat_result:
    try:
        details = path.lstat()
    except OSError:
        raise ContainerHelperError(code) from None
    if (
        stat.S_ISLNK(details.st_mode)
        or not stat.S_ISREG(details.st_mode)
        or stat.S_IMODE(details.st_mode) != 0o600
        or details.st_uid != os.getuid()
        or details.st_nlink != 1
    ):
        raise ContainerHelperError(code)
    return details


def _create_directory(parent: Path, name: str) -> Path:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            parent,
            os.O_RDONLY
            | os.O_DIRECTORY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        os.mkdir(name, 0o700, dir_fd=descriptor)
        os.fsync(descriptor)
    except FileExistsError:
        raise ContainerHelperError("LOCAL_CONTAINER_RUN_EXISTS") from None
    except OSError:
        raise ContainerHelperError("LOCAL_CONTAINER_DIRECTORY_INVALID") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    path = parent / name
    _require_directory(path, code="LOCAL_CONTAINER_DIRECTORY_INVALID")
    return path


def _write_exclusive(path: Path, data: bytes) -> None:
    parent_descriptor: int | None = None
    file_descriptor: int | None = None
    try:
        parent_descriptor = os.open(
            path.parent,
            os.O_RDONLY
            | os.O_DIRECTORY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        file_descriptor = os.open(
            path.name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent_descriptor,
        )
        offset = 0
        while offset < len(data):
            written = os.write(file_descriptor, data[offset:])
            if written <= 0:
                raise ContainerHelperError("LOCAL_CONTAINER_WRITE_FAILED")
            offset += written
        os.fsync(file_descriptor)
        os.fsync(parent_descriptor)
    except FileExistsError:
        raise ContainerHelperError("LOCAL_CONTAINER_OUTPUT_EXISTS") from None
    except ContainerHelperError:
        raise
    except OSError:
        raise ContainerHelperError("LOCAL_CONTAINER_WRITE_FAILED") from None
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        if parent_descriptor is not None:
            os.close(parent_descriptor)
    _require_private_file(path, code="LOCAL_CONTAINER_WRITE_FAILED")


def _run_paths(run_id: str) -> dict[str, Path]:
    root = RUNS_ROOT / run_id
    return {
        "root": root,
        "tool": root / "tool",
        "recovery": root / "recovery",
        "result": root / "result",
        "listening": root / "listening",
        "incoming": root / "incoming",
    }


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        raise ContainerHelperError("LOCAL_CONTAINER_BUNDLE_INVALID") from None
    return digest.hexdigest()


def _python_tree_sha256(root: Path) -> str:
    try:
        paths = sorted(
            path
            for path in root.rglob("*.py")
            if "__pycache__" not in path.parts
        )
    except OSError:
        raise ContainerHelperError("LOCAL_CONTAINER_BACKEND_DRIFT") from None
    if not paths:
        raise ContainerHelperError("LOCAL_CONTAINER_BACKEND_DRIFT")
    entries: list[list[str]] = []
    for path in paths:
        try:
            details = path.lstat()
        except OSError:
            raise ContainerHelperError("LOCAL_CONTAINER_BACKEND_DRIFT") from None
        if stat.S_ISLNK(details.st_mode) or not stat.S_ISREG(details.st_mode):
            raise ContainerHelperError("LOCAL_CONTAINER_BACKEND_DRIFT")
        entries.append([path.relative_to(root).as_posix(), _hash_file(path)])
    return hashlib.sha256(_canonical_json_bytes(entries)).hexdigest()


def _load_and_verify_bundle(
    paths: Mapping[str, Path],
    *,
    require_installed_backend: bool = True,
) -> Mapping[str, object]:
    tool = paths["tool"]
    _require_directory(
        SECRET_PROJECT_ROOT,
        code="LOCAL_CONTAINER_BUNDLE_LOCATION_INVALID",
    )
    _require_directory(
        RUNS_ROOT,
        code="LOCAL_CONTAINER_BUNDLE_LOCATION_INVALID",
    )
    _require_directory(
        paths["root"],
        code="LOCAL_CONTAINER_BUNDLE_LOCATION_INVALID",
    )
    _require_directory(tool, code="LOCAL_CONTAINER_BUNDLE_INVALID")
    expected_tool = Path(__file__).resolve().parents[2]
    if expected_tool != tool:
        raise ContainerHelperError("LOCAL_CONTAINER_BUNDLE_LOCATION_INVALID")
    raw, manifest = _read_json(
        tool / BUNDLE_MANIFEST_NAME,
        code="LOCAL_CONTAINER_BUNDLE_INVALID",
    )
    del raw
    if set(manifest) != {
        "schema_version",
        "files",
        "backend_tree_sha256",
        "bundle_sha256",
    } or manifest["schema_version"] != BUNDLE_SCHEMA_VERSION:
        raise ContainerHelperError("LOCAL_CONTAINER_BUNDLE_INVALID")
    files = manifest["files"]
    if type(files) is not dict or set(files) != set(BUNDLE_RELATIVE_PATHS):
        raise ContainerHelperError("LOCAL_CONTAINER_BUNDLE_INVALID")
    observed_files: set[str] = set()
    for current_root, directory_names, file_names in os.walk(
        tool,
        topdown=True,
        followlinks=False,
    ):
        current = Path(current_root)
        _require_directory(current, code="LOCAL_CONTAINER_BUNDLE_INVALID")
        for directory_name in directory_names:
            _require_directory(
                current / directory_name,
                code="LOCAL_CONTAINER_BUNDLE_INVALID",
            )
        for filename in file_names:
            observed_files.add((current / filename).relative_to(tool).as_posix())
    if observed_files != {*BUNDLE_RELATIVE_PATHS, BUNDLE_MANIFEST_NAME}:
        raise ContainerHelperError("LOCAL_CONTAINER_BUNDLE_INVALID")
    for relative in BUNDLE_RELATIVE_PATHS:
        expected_sha = files.get(relative)
        path = tool / relative
        if type(expected_sha) is not str or _SHA256.fullmatch(expected_sha) is None:
            raise ContainerHelperError("LOCAL_CONTAINER_BUNDLE_INVALID")
        details = _require_private_file(
            path,
            code="LOCAL_CONTAINER_BUNDLE_INVALID",
        )
        if details.st_size <= 0 or _hash_file(path) != expected_sha:
            raise ContainerHelperError("LOCAL_CONTAINER_BUNDLE_INVALID")
    unsigned = {
        "schema_version": manifest["schema_version"],
        "files": manifest["files"],
        "backend_tree_sha256": manifest["backend_tree_sha256"],
    }
    if (
        type(manifest["backend_tree_sha256"]) is not str
        or _SHA256.fullmatch(manifest["backend_tree_sha256"]) is None
        or type(manifest["bundle_sha256"]) is not str
        or manifest["bundle_sha256"]
        != hashlib.sha256(_canonical_json_bytes(unsigned)).hexdigest()
    ):
        raise ContainerHelperError("LOCAL_CONTAINER_BUNDLE_INVALID")
    if require_installed_backend:
        installed_backend = INSTALLED_PLUGIN_ROOT / "backend"
        if _python_tree_sha256(installed_backend) != manifest["backend_tree_sha256"]:
            raise ContainerHelperError("LOCAL_CONTAINER_BACKEND_DRIFT")
    return manifest


def _require_partial_ready_launcher_capability(
    paths: Mapping[str, Path],
) -> None:
    _load_and_verify_bundle(paths)
    launcher = paths["tool"] / "scripts/tts/run_chapter_e2e_real.py"
    details = _require_private_file(
        launcher,
        code="LOCAL_CONTAINER_PARTIAL_READY_LAUNCHER_REQUIRED",
    )
    if not 0 < details.st_size <= 2 * 1024 * 1024:
        raise ContainerHelperError(
            "LOCAL_CONTAINER_PARTIAL_READY_LAUNCHER_REQUIRED"
        )
    try:
        tree = ast.parse(launcher.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, SyntaxError):
        raise ContainerHelperError(
            "LOCAL_CONTAINER_PARTIAL_READY_LAUNCHER_REQUIRED"
        ) from None
    values: list[object] = []
    try:
        for node in tree.body:
            if (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == PARTIAL_READY_LAUNCHER_MARKER
                and node.value is not None
            ):
                values.append(ast.literal_eval(node.value))
            elif isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name)
                and target.id == PARTIAL_READY_LAUNCHER_MARKER
                for target in node.targets
            ):
                values.append(ast.literal_eval(node.value))
    except (TypeError, ValueError):
        raise ContainerHelperError(
            "LOCAL_CONTAINER_PARTIAL_READY_LAUNCHER_REQUIRED"
        ) from None
    if values != [PARTIAL_READY_LAUNCHER_CAPABILITY]:
        raise ContainerHelperError(
            "LOCAL_CONTAINER_PARTIAL_READY_LAUNCHER_REQUIRED"
        )


def _read_validation_token() -> str:
    descriptor: int | None = None
    try:
        details = _require_private_file(
            VALIDATION_TOKEN_FILE,
            code="LOCAL_CONTAINER_VALIDATION_TOKEN_INVALID",
        )
        descriptor = os.open(
            VALIDATION_TOKEN_FILE,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        if (
            (opened.st_dev, opened.st_ino, opened.st_size)
            != (details.st_dev, details.st_ino, details.st_size)
            or not 43 <= opened.st_size <= 128
        ):
            raise ContainerHelperError(
                "LOCAL_CONTAINER_VALIDATION_TOKEN_INVALID"
            )
        raw = os.read(descriptor, 129)
        value = raw.decode("ascii", errors="strict")
    except ContainerHelperError:
        raise
    except (OSError, UnicodeError):
        raise ContainerHelperError(
            "LOCAL_CONTAINER_VALIDATION_TOKEN_INVALID"
        ) from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if len(raw) != details.st_size or _VALIDATION_TOKEN.fullmatch(value) is None:
        raise ContainerHelperError("LOCAL_CONTAINER_VALIDATION_TOKEN_INVALID")
    return value


def _claim_gate_request(
    *,
    action: str,
    run_id: str,
    novel_id: str,
    document_id: str,
) -> None:
    if action not in {"arm", "release"}:
        raise ContainerHelperError("LOCAL_CONTAINER_CLAIM_GATE_INVALID")
    token = _read_validation_token()
    suffix = "" if action == "arm" else "/release"
    path = (
        "/api/ai-novel-world-2026"
        f"/novels/{novel_id}/documents/{document_id}"
        f"/narration-validation-segment-claim-gate{suffix}"
    )
    body = _canonical_json_bytes(
        {
            "run_id": run_id,
            **(
                {"ttl_seconds": 120, "segment_claim_limit": 1}
                if action == "arm"
                else {}
            ),
        }
    )
    connection = http.client.HTTPConnection("127.0.0.1", 8088, timeout=15)
    try:
        connection.request(
            "POST",
            path,
            body=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
                VALIDATION_TOKEN_HEADER: token,
            },
        )
        response = connection.getresponse()
        raw = response.read(_MAX_JSON_BYTES + 1)
    except (OSError, http.client.HTTPException):
        raise ContainerHelperError("LOCAL_CONTAINER_CLAIM_GATE_HOLD") from None
    finally:
        connection.close()
    if response.status != 200 or not 0 < len(raw) <= _MAX_JSON_BYTES:
        raise ContainerHelperError("LOCAL_CONTAINER_CLAIM_GATE_HOLD")
    try:
        payload = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_pairs,
        )
    except (ContainerHelperError, UnicodeError, json.JSONDecodeError):
        raise ContainerHelperError("LOCAL_CONTAINER_CLAIM_GATE_HOLD") from None
    if type(payload) is not dict or set(payload) != {
        "code",
        "state",
        "claim_limit",
        "claimed_count",
        "remaining_count",
        "expires_at",
        "run_fingerprint_sha256",
        "scope_fingerprint_sha256",
    }:
        raise ContainerHelperError("LOCAL_CONTAINER_CLAIM_GATE_HOLD")
    if action == "arm":
        valid = (
            payload.get("code") == "VALIDATION_SEGMENT_CLAIM_GATE_ARMED"
            and payload.get("state") == "armed"
            and payload.get("claim_limit") == 1
            and payload.get("claimed_count") == 0
            and payload.get("remaining_count") == 1
        )
    else:
        valid = (
            payload.get("state") == "default_allow"
            and payload.get("code")
            in {
                "VALIDATION_SEGMENT_CLAIM_GATE_RELEASED",
                "VALIDATION_SEGMENT_CLAIM_GATE_DEFAULT_ALLOW",
            }
        )
    if not valid:
        raise ContainerHelperError("LOCAL_CONTAINER_CLAIM_GATE_HOLD")
    expected_run = hashlib.sha256(
        b"narration-validation-claim-gate-run/1\x00"
        + run_id.encode("ascii")
    ).hexdigest()
    expected_scope = hashlib.sha256(
        b"narration-validation-claim-gate-scope/1\x00"
        + novel_id.encode("ascii")
        + b"\x00"
        + document_id.encode("ascii")
    ).hexdigest()
    if action == "arm" and (
        payload.get("run_fingerprint_sha256") != expected_run
        or payload.get("scope_fingerprint_sha256") != expected_scope
    ):
        raise ContainerHelperError("LOCAL_CONTAINER_CLAIM_GATE_HOLD")
    if action == "release" and (
        payload.get("run_fingerprint_sha256") not in {None, expected_run}
        or payload.get("scope_fingerprint_sha256") not in {None, expected_scope}
    ):
        raise ContainerHelperError("LOCAL_CONTAINER_CLAIM_GATE_HOLD")


def _prepare(
    paths: Mapping[str, Path],
    *,
    run_id: str,
    novel_id: str,
    document_id: str,
) -> None:
    _load_and_verify_bundle(paths)
    _require_directory(paths["root"], code="LOCAL_CONTAINER_RUN_INVALID")
    for key in ("recovery", "result", "listening", "incoming"):
        _create_directory(paths["root"], key)
    recovery = paths["recovery"]
    grant_suffix = run_id
    lock_rows = []
    for name, filename, prefix in (
        ("nano", "lock-nano", "LOCK-NANO"),
        ("browser", "lock-browser", "LOCK-BROWSER"),
        ("data", "lock-data", "LOCK-T4-K-DATA"),
    ):
        lock_path = recovery / filename
        _write_exclusive(lock_path, b"")
        lock_rows.append(
            {
                "name": name,
                "path": str(lock_path),
                "grant": f"{prefix}/{grant_suffix}",
            }
        )
    fixture = paths["tool"] / FIXTURE_RELATIVE_PATH
    attestation = {
        "schema_version": "moss-tts-t4k-readiness-attestation/1.1",
        "fixture_manifest_sha256": _hash_file(fixture),
        "novel_id": novel_id,
        "document_id": document_id,
        "declarations": {
            "dedicated_test_novel": True,
            "dedicated_test_chapter": True,
            "append_only_recovery_accepted": True,
            "official_presets_local_use": True,
        },
        "expected_characters": ["林晚", "沈川"],
        "expected_official_presets": [
            {"role": role, "preset_id": preset}
            for role, preset in EXPECTED_VOICES
        ],
        "required_captures": [
            {
                "width": width,
                "height": height,
                "assistant_mode": assistant_mode,
            }
            for width, height, assistant_mode in EXPECTED_CAPTURES
        ],
        "resource_locks": lock_rows,
    }
    _write_exclusive(
        recovery / "readiness-attestation.json",
        _canonical_json_bytes(attestation),
    )


def _verify_host_commit_marker(
    marker: Mapping[str, object],
    *,
    collector_raw: bytes,
    probe_raw: bytes,
    request_fingerprint_sha256: str,
) -> None:
    if set(marker) != {
        "schema_version",
        "request_fingerprint_sha256",
        "collector",
        "probe",
        "pair_commit_fingerprint_sha256",
    }:
        raise ContainerHelperError("LOCAL_CONTAINER_REPORT_INVALID")
    collector = marker.get("collector")
    probe = marker.get("probe")
    if type(collector) is not dict or type(probe) is not dict:
        raise ContainerHelperError("LOCAL_CONTAINER_REPORT_INVALID")
    expected_collector_sha = hashlib.sha256(collector_raw).hexdigest()
    expected_probe_sha = hashlib.sha256(probe_raw).hexdigest()
    if (
        marker.get("schema_version")
        != "moss-tts-chapter-e2e-local-operator-commit/1.0"
        or marker.get("request_fingerprint_sha256")
        != request_fingerprint_sha256
        or set(collector) != {"filename", "sha256", "file_identity_sha256"}
        or set(probe) != {"filename", "sha256", "file_identity_sha256"}
        or collector.get("filename") != "collector-report.json"
        or collector.get("sha256") != expected_collector_sha
        or probe.get("filename") != "probe-report.json"
        or probe.get("sha256") != expected_probe_sha
        or any(
            type(value) is not str or _SHA256.fullmatch(value) is None
            for value in (
                collector.get("file_identity_sha256"),
                probe.get("file_identity_sha256"),
            )
        )
    ):
        raise ContainerHelperError("LOCAL_CONTAINER_REPORT_INVALID")
    unsigned = dict(marker)
    fingerprint = unsigned.pop("pair_commit_fingerprint_sha256")
    if fingerprint != hashlib.sha256(
        _canonical_json_payload_bytes(unsigned)
    ).hexdigest():
        raise ContainerHelperError("LOCAL_CONTAINER_REPORT_INVALID")


def _import_report(paths: Mapping[str, Path]) -> None:
    _load_and_verify_bundle(paths)
    for key in ("root", "recovery", "incoming"):
        _require_directory(paths[key], code="LOCAL_CONTAINER_RUN_INVALID")
    incoming = paths["incoming"]
    collector_raw, collector_payload = _read_json(
        incoming / "collector-report.json",
        code="LOCAL_CONTAINER_REPORT_INVALID",
    )
    probe_raw, probe_payload = _read_json(
        incoming / "probe-report.json",
        code="LOCAL_CONTAINER_REPORT_INVALID",
    )
    _marker_raw, marker_payload = _read_json(
        incoming / "collector-report.commit.json",
        code="LOCAL_CONTAINER_REPORT_INVALID",
    )

    stage_root = paths["tool"]
    if str(stage_root) not in sys.path:
        sys.path.insert(0, str(stage_root))
    try:
        from scripts.tts import chapter_e2e_collector as collector
    except Exception:
        raise ContainerHelperError("LOCAL_CONTAINER_BUNDLE_INVALID") from None

    request_path = paths["recovery"] / "probe-request.json"
    try:
        request, parent, parent_identity = collector._load_request(
            request_path,
            now=datetime.now(timezone.utc).replace(microsecond=0),
        )
        request_fingerprint, _bound = (
            collector._validate_local_operator_collector_candidate(
                collector_raw=collector_raw,
                collector=collector_payload,
                probe_raw=probe_raw,
                probe=probe_payload,
                expectation=request.expectation,
                now=datetime.now(timezone.utc).replace(microsecond=0),
            )
        )
        if request_fingerprint != request.request_fingerprint_sha256:
            raise ContainerHelperError("LOCAL_CONTAINER_REPORT_INVALID")
        _verify_host_commit_marker(
            marker_payload,
            collector_raw=collector_raw,
            probe_raw=probe_raw,
            request_fingerprint_sha256=request_fingerprint,
        )

        with collector._collector_transaction_lock(
            parent,
            parent_identity,
            exclusive=True,
            create=True,
        ) as parent_fd:
            locked_request, locked_parent, locked_identity = (
                collector._load_request(
                    request_path,
                    now=datetime.now(timezone.utc).replace(microsecond=0),
                )
            )
            if (
                locked_request != request
                or locked_parent != parent
                or locked_identity != parent_identity
            ):
                raise ContainerHelperError("LOCAL_CONTAINER_REPORT_CONFLICT")
            collector._ensure_outputs_absent(parent, parent_identity)
            collector_identity = collector._publish_exact_file(
                parent_fd,
                filename="collector-report.json",
                data=collector_raw,
            )
            probe_identity = collector._publish_exact_file(
                parent_fd,
                filename="probe-report.json",
                data=probe_raw,
            )
            marker_bytes = collector._build_local_operator_commit_marker(
                request_fingerprint_sha256=request_fingerprint,
                collector_bytes=collector_raw,
                collector_identity=collector_identity,
                probe_bytes=probe_raw,
                probe_identity=probe_identity,
            )
            collector._publish_exact_file(
                parent_fd,
                filename="collector-report.commit.json",
                data=marker_bytes,
            )
            collector._assert_parent_identity(parent, parent_fd, parent_identity)
    except ContainerHelperError:
        raise
    except Exception:
        raise ContainerHelperError("LOCAL_CONTAINER_REPORT_INVALID") from None


def _validate_readiness_binding(
    paths: Mapping[str, Path],
    *,
    novel_id: str,
    document_id: str,
) -> str:
    _raw, attestation = _read_json(
        paths["recovery"] / "readiness-attestation.json",
        code="LOCAL_CONTAINER_RESULT_INVALID",
    )
    fixture_sha256 = _hash_file(paths["tool"] / FIXTURE_RELATIVE_PATH)
    if (
        attestation.get("schema_version")
        != "moss-tts-t4k-readiness-attestation/1.1"
        or attestation.get("novel_id") != novel_id
        or attestation.get("document_id") != document_id
        or attestation.get("fixture_manifest_sha256") != fixture_sha256
        or attestation.get("expected_characters") != ["林晚", "沈川"]
        or attestation.get("expected_official_presets")
        != [
            {"role": role, "preset_id": preset}
            for role, preset in EXPECTED_VOICES
        ]
        or attestation.get("required_captures")
        != [
            {
                "width": width,
                "height": height,
                "assistant_mode": assistant_mode,
            }
            for width, height, assistant_mode in EXPECTED_CAPTURES
        ]
    ):
        raise ContainerHelperError("LOCAL_CONTAINER_RESULT_INVALID")
    return fixture_sha256


def _load_verified_operator_evidence_root(paths: Mapping[str, Path]) -> str:
    stage_root = paths["tool"]
    if str(stage_root) not in sys.path:
        sys.path.insert(0, str(stage_root))
    try:
        from scripts.tts import chapter_e2e_collector as collector

        _collector_raw, collector_payload = _read_json(
            paths["recovery"] / "collector-report.json",
            code="LOCAL_CONTAINER_RESULT_INVALID",
        )
        collected_at_raw = collector_payload.get("collected_at")
        if type(collected_at_raw) is not str:
            raise ValueError
        collected_at = datetime.fromisoformat(
            collected_at_raw.replace("Z", "+00:00")
        )
        if collected_at.utcoffset() != timezone.utc.utcoffset(collected_at):
            raise ValueError
        collected_at = collected_at.astimezone(timezone.utc).replace(microsecond=0)
        request, _parent, _identity = collector._load_request(
            paths["recovery"] / "probe-request.json",
            now=collected_at,
        )
        bound = collector.LocalOperatorCollectorReportGuard().load_verified(
            paths["recovery"] / "probe-report.json",
            expectation=request.expectation,
            now=collected_at,
        )
        evidence_root = bound.evidence_root_sha256
    except Exception:
        raise ContainerHelperError("LOCAL_CONTAINER_RESULT_INVALID") from None
    if type(evidence_root) is not str or _SHA256.fullmatch(evidence_root) is None:
        raise ContainerHelperError("LOCAL_CONTAINER_RESULT_INVALID")
    return evidence_root


def _validate_recovery_binding(
    paths: Mapping[str, Path],
    *,
    run_id: str,
    novel_id: str,
    document_id: str,
    fixture_sha256: str,
    expected_state: str | None = None,
    require_baseline_restored: bool = False,
) -> None:
    raw, recovery = _read_json(
        paths["recovery"] / "recovery.json",
        code="LOCAL_CONTAINER_RESULT_INVALID",
    )
    del raw
    unsigned = dict(recovery)
    self_sha256 = unsigned.pop("self_sha256", None)
    fixture = recovery.get("fixture")
    schema_version = recovery.get("schema_version")
    baseline_restored = recovery.get("baseline_restored")
    restoration_evidence = recovery.get("restoration_evidence")
    sealed_technical = recovery.get("sealed_technical_result")
    if (
        schema_version not in SUPPORTED_RECOVERY_SCHEMA_VERSIONS
        or recovery.get("work_package") != WORK_PACKAGE
        or recovery.get("run_id") != run_id
        or recovery.get("novel_id") != novel_id
        or recovery.get("document_id") != document_id
        or recovery.get("state")
        not in {
            "BASELINE_CAPTURED",
            "AUTOMATIC_COMPLETE",
            "MANUAL_COMPLETE",
            "TECHNICAL_COMPLETE",
            "RECOVERY_REQUIRED",
            "LISTENING_PENDING",
            "FINALIZATION_PENDING",
        }
        or (
            expected_state is not None
            and recovery.get("state") != expected_state
        )
        or (
            require_baseline_restored
            and baseline_restored is not True
        )
        or type(baseline_restored) is not bool
        or type(fixture) is not dict
        or fixture.get("manifest_sha256") != fixture_sha256
        or type(self_sha256) is not str
        # validate_chapter_e2e fingerprints the canonical JSON payload, while
        # the durable file itself adds one trailing newline.  Do not include
        # that transport newline in the recovery self hash.
        or self_sha256
        != hashlib.sha256(_canonical_json_payload_bytes(unsigned)).hexdigest()
    ):
        raise ContainerHelperError("LOCAL_CONTAINER_RESULT_INVALID")
    if schema_version == LEGACY_RECOVERY_SCHEMA_VERSION:
        if "restoration_evidence" in recovery:
            raise ContainerHelperError("LOCAL_CONTAINER_RESULT_INVALID")
        if (
            type(sealed_technical) is dict
            and type(sealed_technical.get("result")) is dict
            and "result_schema_version" in sealed_technical["result"]
        ):
            raise ContainerHelperError("LOCAL_CONTAINER_RESULT_INVALID")
        return
    if schema_version == PREVIOUS_RECOVERY_SCHEMA_VERSION:
        if (
            type(sealed_technical) is dict
            and type(sealed_technical.get("result")) is dict
            and "result_schema_version" in sealed_technical["result"]
        ):
            raise ContainerHelperError("LOCAL_CONTAINER_RESULT_INVALID")
    elif sealed_technical is not None:
        if (
            type(sealed_technical) is not dict
            or set(sealed_technical) != {"result", "self_sha256"}
            or type(sealed_technical.get("result")) is not dict
            or sealed_technical["result"].get("result_schema_version")
            != RESULT_SCHEMA_VERSION
        ):
            raise ContainerHelperError("LOCAL_CONTAINER_RESULT_INVALID")
    if baseline_restored is False:
        if "restoration_evidence" in recovery:
            raise ContainerHelperError("LOCAL_CONTAINER_RESULT_INVALID")
        return
    if (
        type(restoration_evidence) is not dict
        or set(restoration_evidence)
        != {
            "working_copy_content_restored",
            "author_visible_edition_restored",
            "append_only_history_retained",
            "new_authoritative_record_count",
        }
        or restoration_evidence.get("working_copy_content_restored") is not True
        or restoration_evidence.get("author_visible_edition_restored") is not True
        or restoration_evidence.get("append_only_history_retained") is not True
        or type(restoration_evidence.get("new_authoritative_record_count")) is not int
        or restoration_evidence["new_authoritative_record_count"] < 0
    ):
        raise ContainerHelperError("LOCAL_CONTAINER_RESULT_INVALID")


def _validate_technical_memory_gate(technical: Mapping[str, object]) -> None:
    performance = technical.get("performance_gate")
    peak_memory_bytes = technical.get("peak_memory_bytes")
    if (
        set(technical) != _TECHNICAL_KEYS
        or type(performance) is not dict
        or set(performance) != _PERFORMANCE_GATE_KEYS
        or type(peak_memory_bytes) is not int
        or peak_memory_bytes < 0
        or peak_memory_bytes > _SIDECAR_PEAK_MEMORY_LIMIT_BYTES
        or performance.get("sidecar_peak_memory_limit_bytes")
        != _SIDECAR_PEAK_MEMORY_LIMIT_BYTES
        or type(performance.get("host_paging_observed")) is not bool
        or type(performance.get("sidecar_memory_growth_observed")) is not bool
        or type(performance.get("qwenpaw_slowdown_observed")) is not bool
        or performance.get("sidecar_memory_growth_observed") is not False
        or performance.get("qwenpaw_slowdown_observed") is not False
        or performance.get("host_paging_interpretation")
        != "whole_host_telemetry_only"
        or performance.get("memory_safety_passed") is not True
        or type(technical.get("sidecar_restart_count")) is not int
        or technical.get("sidecar_restart_count") != 0
        or type(technical.get("health_failure_count")) is not int
        or technical.get("health_failure_count") != 0
    ):
        raise ContainerHelperError("LOCAL_CONTAINER_RESULT_INVALID")
    measurement_keys = (
        "pageout_delta",
        "swapout_delta",
        "memory_baseline_median_bytes",
        "memory_tail_median_bytes",
        "memory_growth_bytes",
        "memory_growth_limit_bytes",
    )
    if any(
        type(performance.get(key)) is not int or performance[key] < 0
        for key in measurement_keys
    ):
        raise ContainerHelperError("LOCAL_CONTAINER_RESULT_INVALID")
    pageout_delta = performance["pageout_delta"]
    swapout_delta = performance["swapout_delta"]
    baseline = performance["memory_baseline_median_bytes"]
    tail = performance["memory_tail_median_bytes"]
    growth = performance["memory_growth_bytes"]
    growth_limit = performance["memory_growth_limit_bytes"]
    measured_growth_limit = max(
        _SIDECAR_MEMORY_GROWTH_MIN_LIMIT_BYTES,
        (
            baseline * _SIDECAR_MEMORY_GROWTH_PERCENT_NUMERATOR
            + _SIDECAR_MEMORY_GROWTH_PERCENT_DENOMINATOR
            - 1
        )
        // _SIDECAR_MEMORY_GROWTH_PERCENT_DENOMINATOR,
    )
    if (
        performance["host_paging_observed"]
        is not (pageout_delta > 0 or swapout_delta > 0)
        or baseline > peak_memory_bytes
        or tail > peak_memory_bytes
        or growth != max(0, tail - baseline)
        or growth_limit != measured_growth_limit
        or performance["sidecar_memory_growth_observed"]
        is not (growth > growth_limit)
    ):
        raise ContainerHelperError("LOCAL_CONTAINER_RESULT_INVALID")


def _load_bound_result(
    paths: Mapping[str, Path],
    *,
    run_id: str,
    novel_id: str,
    document_id: str,
    require_installed_backend: bool = False,
) -> Mapping[str, object] | None:
    _load_and_verify_bundle(
        paths,
        require_installed_backend=require_installed_backend,
    )
    for key in ("root", "recovery", "result", "listening"):
        _require_directory(paths[key], code="LOCAL_CONTAINER_RUN_INVALID")
    fixture_sha256 = _validate_readiness_binding(
        paths,
        novel_id=novel_id,
        document_id=document_id,
    )
    result_path = paths["result"] / "result.json"
    if not result_path.exists():
        return None
    _raw, result = _read_json(result_path, code="LOCAL_CONTAINER_RESULT_INVALID")
    fixture = result.get("fixture")
    automatic_chain = result.get("automatic_chain")
    manual_chain = result.get("manual_chain")
    technical = result.get("technical_checks")
    safety = result.get("safety")
    recovery = result.get("recovery")
    status_value = result.get("status")
    if (
        set(result) != _RESULT_KEYS
        or result.get("schema_version") != RESULT_SCHEMA_VERSION
        or result.get("work_package") != WORK_PACKAGE
        or result.get("run_fingerprint_sha256") != _sha256_text(run_id)
        or result.get("target_scope_sha256")
        != _sha256_text(f"{novel_id}:{document_id}")
        or result.get("mode") != "real"
        or status_value not in _KNOWN_RESULT_STATUSES
        or type(fixture) is not dict
        or fixture.get("manifest_sha256") != fixture_sha256
        or type(automatic_chain) is not dict
        or type(manual_chain) is not dict
        or any(
            type(chain.get(key)) is not str
            or _SHA256.fullmatch(chain[key]) is None
            for chain in (automatic_chain, manual_chain)
            for key in (
                "edition_id_sha256",
                "edition_fingerprint_sha256",
            )
        )
        or type(safety) is not dict
        or safety.get("no_secrets_recorded") is not True
        or safety.get("no_private_paths_recorded") is not True
        or type(recovery) is not dict
    ):
        raise ContainerHelperError("LOCAL_CONTAINER_RESULT_INVALID")
    if status_value in {
        "PASS_CANDIDATE",
        "TECHNICAL_PASS_CANDIDATE",
        "HUMAN_LISTENING_PENDING",
    }:
        evidence_root = _load_verified_operator_evidence_root(paths)
        if (
            type(technical) is not dict
            or technical.get("state") != "PASS"
            or technical.get("evidence_class")
            != "local_operator_observation"
            or technical.get("evidence_root_sha256") != evidence_root
        ):
            raise ContainerHelperError("LOCAL_CONTAINER_RESULT_INVALID")
        _validate_technical_memory_gate(technical)
    recovery_path = paths["recovery"] / "recovery.json"
    if status_value == "HUMAN_LISTENING_PENDING":
        _validate_recovery_binding(
            paths,
            run_id=run_id,
            novel_id=novel_id,
            document_id=document_id,
            fixture_sha256=fixture_sha256,
            expected_state="LISTENING_PENDING",
            require_baseline_restored=True,
        )
    elif status_value in _FINAL_STATUSES:
        if recovery_path.exists() or any(
            recovery.get(key) is not True
            for key in (
                "working_copy_content_restored",
                "author_visible_edition_restored",
                "append_only_history_retained",
            )
        ) or recovery.get("recovery_required") is not False:
            raise ContainerHelperError("LOCAL_CONTAINER_RESULT_INVALID")
    elif status_value == "RECOVERY_REQUIRED":
        _validate_recovery_binding(
            paths,
            run_id=run_id,
            novel_id=novel_id,
            document_id=document_id,
            fixture_sha256=fixture_sha256,
            expected_state="RECOVERY_REQUIRED",
        )
    elif recovery_path.exists():
        _validate_recovery_binding(
            paths,
            run_id=run_id,
            novel_id=novel_id,
            document_id=document_id,
            fixture_sha256=fixture_sha256,
        )
    return result


def _status(
    paths: Mapping[str, Path],
    *,
    run_id: str,
    novel_id: str,
    document_id: str,
) -> str:
    result = _load_bound_result(
        paths,
        run_id=run_id,
        novel_id=novel_id,
        document_id=document_id,
    )
    if result is None:
        return "PREPARED"
    if (
        result["status"] == "FAILED"
        and result.get("error_codes") == ["HUMAN_LISTENING_FAILED"]
    ):
        # The launcher console intentionally exposes only the coarse FAILED
        # status.  Derive this quality hold from the exact, scope-bound result
        # instead of trusting a more detailed unbound process log.
        return "HUMAN_LISTENING_FAILED"
    return str(result["status"])


def _assert_safe_tree(path: Path) -> None:
    _require_directory(path, code="LOCAL_CONTAINER_CLEANUP_UNSAFE")
    for current_root, directory_names, file_names in os.walk(
        path,
        topdown=True,
        followlinks=False,
    ):
        current = Path(current_root)
        for name in (*directory_names, *file_names):
            candidate = current / name
            try:
                details = candidate.lstat()
            except OSError:
                raise ContainerHelperError("LOCAL_CONTAINER_CLEANUP_UNSAFE") from None
            if stat.S_ISLNK(details.st_mode) or details.st_uid != os.getuid():
                raise ContainerHelperError("LOCAL_CONTAINER_CLEANUP_UNSAFE")


def _cleanup(
    paths: Mapping[str, Path],
    *,
    run_id: str,
    novel_id: str,
    document_id: str,
) -> None:
    if (paths["recovery"] / "recovery.json").exists():
        raise ContainerHelperError("LOCAL_CONTAINER_RECOVERY_PENDING")
    result = _load_bound_result(
        paths,
        run_id=run_id,
        novel_id=novel_id,
        document_id=document_id,
    )
    if result is None:
        raise ContainerHelperError("LOCAL_CONTAINER_CLEANUP_HOLD")
    for key in ("root", "recovery", "result", "listening"):
        _require_directory(paths[key], code="LOCAL_CONTAINER_CLEANUP_UNSAFE")
    failed_listening = (
        result.get("status") == "FAILED"
        and result.get("error_codes") == ["HUMAN_LISTENING_FAILED"]
        and isinstance(result.get("human_listening"), dict)
        and result["human_listening"].get("state") == "FAIL"
        and result["recovery"].get("recovery_required") is False
    )
    if result.get("status") not in {
        "PASS_CANDIDATE",
        "TECHNICAL_PASS_CANDIDATE",
    } and not failed_listening:
        raise ContainerHelperError("LOCAL_CONTAINER_CLEANUP_HOLD")
    for filename in REPORT_FILENAMES:
        _require_private_file(
            paths["recovery"] / filename,
            code="LOCAL_CONTAINER_CLEANUP_HOLD",
        )
    cleanup_binding = {
        "schema_version": "moss-tts-t4k-cleanup-authorization/1.0",
        "run_fingerprint_sha256": _sha256_text(run_id),
        "target_scope_sha256": _sha256_text(f"{novel_id}:{document_id}"),
        "result_sha256": _hash_file(paths["result"] / "result.json"),
        "phase": "COMMIT_INTENT",
    }
    cleanup_state = paths["recovery"] / "cleanup-state.json"
    if cleanup_state.exists():
        _raw, observed_cleanup = _read_json(
            cleanup_state,
            code="LOCAL_CONTAINER_CLEANUP_UNSAFE",
        )
        if observed_cleanup != cleanup_binding:
            raise ContainerHelperError("LOCAL_CONTAINER_CLEANUP_UNSAFE")
    else:
        _write_exclusive(cleanup_state, _canonical_json_bytes(cleanup_binding))
    if paths["incoming"].exists():
        _assert_safe_tree(paths["incoming"])
    _assert_safe_tree(paths["tool"])
    try:
        if paths["incoming"].exists():
            shutil.rmtree(paths["incoming"])
        shutil.rmtree(paths["tool"])
        parent_descriptor = os.open(
            paths["root"],
            os.O_RDONLY
            | os.O_DIRECTORY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)
    except OSError:
        raise ContainerHelperError("LOCAL_CONTAINER_CLEANUP_FAILED") from None


def _write_status(stream, *, status: str, code: str) -> None:  # type: ignore[no-untyped-def]
    stream.write(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "status": status,
                "code": code,
                "secret_values_emitted": False,
                "private_paths_emitted": False,
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )


def _stop_launcher(
    paths: Mapping[str, Path],
    *,
    run_id: str,
    novel_id: str,
    document_id: str,
    proc_root: Path = Path("/proc"),
    sleeper=time.sleep,
) -> None:
    """Stop the one exact sealed launcher; never signal a different process."""

    launcher = str(paths["tool"] / "scripts/tts/run_chapter_e2e_real.py")
    required_pairs = {
        "--mode": "real",
        "--run-id": run_id,
        "--novel-id": novel_id,
        "--document-id": document_id,
        "--private-work-dir": str(paths["recovery"]),
        "--output-dir": str(paths["result"]),
    }
    matches: list[tuple[int, Path, bytes]] = []
    try:
        candidates = tuple(proc_root.iterdir())
    except OSError:
        raise ContainerHelperError("LOCAL_CONTAINER_LAUNCHER_STOP_FAILED") from None
    for candidate in candidates:
        if not candidate.name.isdigit():
            continue
        cmdline = candidate / "cmdline"
        try:
            raw = cmdline.read_bytes()
        except OSError:
            continue
        if not raw or len(raw) > 64 * 1024:
            continue
        try:
            argv = tuple(
                item.decode("utf-8", errors="strict")
                for item in raw.rstrip(b"\x00").split(b"\x00")
            )
        except UnicodeError:
            continue
        if len(argv) < 3 or argv[0] != "/app/venv/bin/python" or launcher not in argv:
            continue
        valid = True
        for key, expected in required_pairs.items():
            if argv.count(key) != 1:
                valid = False
                break
            index = argv.index(key)
            if index + 1 >= len(argv) or argv[index + 1] != expected:
                valid = False
                break
        if valid:
            matches.append((int(candidate.name), candidate, raw))
    if len(matches) != 1:
        raise ContainerHelperError("LOCAL_CONTAINER_LAUNCHER_STOP_FAILED")
    pid, process_path, sealed_cmdline = matches[0]
    stop_plan = (
        (signal.SIGINT, 600),
        (signal.SIGTERM, 100),
        (signal.SIGKILL, 100),
    )
    for stop_signal, wait_attempts in stop_plan:
        try:
            if (process_path / "cmdline").read_bytes() != sealed_cmdline:
                raise ContainerHelperError(
                    "LOCAL_CONTAINER_LAUNCHER_STOP_FAILED"
                )
        except FileNotFoundError:
            return
        except OSError:
            raise ContainerHelperError(
                "LOCAL_CONTAINER_LAUNCHER_STOP_FAILED"
            ) from None
        try:
            os.kill(pid, stop_signal)
        except ProcessLookupError:
            return
        except OSError:
            raise ContainerHelperError(
                "LOCAL_CONTAINER_LAUNCHER_STOP_FAILED"
            ) from None
        for _attempt in range(wait_attempts):
            if not process_path.exists():
                return
            sleeper(0.1)
    raise ContainerHelperError("LOCAL_CONTAINER_LAUNCHER_STOP_FAILED")


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        if args.confirm != CONFIRMATIONS[args.mode]:
            raise ContainerHelperError("LOCAL_CONTAINER_CONFIRMATION_REQUIRED")
        run_id = _canonical_uuid(args.run_id, "LOCAL_CONTAINER_RUN_INVALID")
        novel_id = _canonical_uuid(args.novel_id, "LOCAL_CONTAINER_SCOPE_INVALID")
        document_id = _canonical_uuid(
            args.document_id,
            "LOCAL_CONTAINER_SCOPE_INVALID",
        )
        paths = _run_paths(run_id)
        if args.mode == "verify-stage":
            _load_and_verify_bundle(paths)
            code = "STAGE_VERIFIED"
        elif args.mode == "prepare":
            _prepare(
                paths,
                run_id=run_id,
                novel_id=novel_id,
                document_id=document_id,
            )
            code = "RUN_PREPARED"
        elif args.mode == "import-report":
            _import_report(paths)
            code = "REPORT_IMPORTED"
        elif args.mode == "status":
            code = _status(
                paths,
                run_id=run_id,
                novel_id=novel_id,
                document_id=document_id,
            )
        elif args.mode == "require-partial-ready-capability":
            _require_partial_ready_launcher_capability(paths)
            code = "PARTIAL_READY_LAUNCHER_VERIFIED"
        elif args.mode in {"arm-claim-gate", "release-claim-gate"}:
            _load_and_verify_bundle(paths)
            _claim_gate_request(
                action=(
                    "arm" if args.mode == "arm-claim-gate" else "release"
                ),
                run_id=run_id,
                novel_id=novel_id,
                document_id=document_id,
            )
            code = (
                "CLAIM_GATE_ARMED"
                if args.mode == "arm-claim-gate"
                else "CLAIM_GATE_RELEASED"
            )
        elif args.mode == "stop-launcher":
            _load_and_verify_bundle(paths)
            _stop_launcher(
                paths,
                run_id=run_id,
                novel_id=novel_id,
                document_id=document_id,
            )
            code = "LAUNCHER_STOPPED"
        else:
            _cleanup(
                paths,
                run_id=run_id,
                novel_id=novel_id,
                document_id=document_id,
            )
            code = "TOOLS_CLEANED"
        _write_status(sys.stdout, status="OK", code=code)
        return 0
    except ContainerHelperError as error:
        _write_status(sys.stderr, status="HOLD", code=error.code)
        return 2
    except KeyboardInterrupt:
        _write_status(sys.stderr, status="HOLD", code="LOCAL_CONTAINER_INTERRUPTED")
        return 130
    except SystemExit as error:
        return error.code if type(error.code) is int else 0
    except BaseException:
        _write_status(sys.stderr, status="HOLD", code="LOCAL_CONTAINER_INTERNAL_ERROR")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BUNDLE_RELATIVE_PATHS",
    "CONFIRMATIONS",
    "EXPECTED_CAPTURES",
    "EXPECTED_VOICES",
    "ContainerHelperError",
    "build_parser",
    "main",
]
