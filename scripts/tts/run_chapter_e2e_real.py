#!/usr/bin/env python3
"""Fixed, lock-owning launcher for the destructive T4-K real chapter run.

This is the only supported path that injects the real HTTP executor.  It does
not accept import paths, plugins, shell commands, database URLs, or probe JSON
on the command line.  The database URL comes from the existing project
environment; the browser/runtime report is a private external 0600 file; and
three pre-created private lock files remain held for the whole run.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Iterator, Literal, Mapping, Sequence
from uuid import UUID

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from sqlalchemy.orm import sessionmaker

from backend.database import get_engine
from scripts.tts.chapter_e2e_executor import (
    LoopbackHttpTransport,
    PartialReadyValidationEvidence,
    ValidationClaimGateEvidence,
    build_real_executor_factory,
    build_real_recovery_executor_factory,
    verify_t4k_hidden_release_gate,
)
from scripts.tts.chapter_e2e_probes import (
    BoundProbeReportCache,
    ProbeReportError,
    StrictReportBrowserProbe,
)
from scripts.tts.chapter_e2e_collector import (
    LocalOperatorCollectorReportGuard,
    PROBE_CONTROLLER_AUTHORITY_HOLD_ERROR,
)
from scripts.tts.chapter_e2e_controller_trust import (
    CONTROLLER_TRUST_ROOT_HOLD_ERROR,
    FIXED_REQUIRED_CAPTURES,
    MAX_PREFLIGHT_BYTES,
    MAX_SIGNATURE_BYTES,
    ControllerTrustError,
    FixedControllerTrustVerifier,
    PreflightExpectation,
    canonical_json_bytes,
)
from scripts.tts.chapter_e2e_probe_request import (
    PROBE_REPORT_FILENAME,
    PrivateProbeRequestPublisher,
)
from scripts.tts.chapter_e2e_operator_envelope import (
    OperatorEnvelopeError,
    claim_operator_envelope,
    load_operator_envelope,
    private_lock_identity_from_stat,
    verify_operator_envelope_binding,
)
from scripts.tts.chapter_e2e_readiness import (
    EXPECTED_LOCK_NAMES,
    ReadinessError,
    SqlAlchemyReadinessReader,
    _storage_from_environment,
    evaluate_readiness,
    load_private_attestation,
)
from scripts.tts.chapter_e2e_runtime_audit import (
    ReportBackedRuntimeAuditProbe,
    SqlAlchemyRuntimeAuditReader,
)
from scripts.tts import validate_chapter_e2e as validator
from scripts.tts.validate_chapter_e2e import RunnerError


FIXED_LAUNCHER_CONFIRMATION = "RUN-T4-K-FIXED-LAUNCHER"
T4K_PARTIAL_READY_VALIDATION_CAPABILITY = (
    "claim-gate-v1/cache-hit-prefix-miss-suffix/partial-ready-browser"
)
PARTIAL_READY_MARKER_FILENAME = "partial-ready-validation.json"
PARTIAL_READY_MARKER_SCHEMA = "moss-tts-t4k-partial-ready-validation/1.0"
FIXED_VALIDATION_TOKEN_FILE = Path(
    "/app/working.secret/ai-novel-world-2026/t4k-validation/token"
)
CONTROLLER_PREFLIGHT_FILENAME = "controller-preflight.json"
CONTROLLER_PREFLIGHT_SIGNATURE_FILENAME = "controller-preflight.sshsig"
_GRANT_PATTERNS = {
    "nano": re.compile(r"^LOCK-NANO/[A-Za-z0-9][A-Za-z0-9._-]{7,95}$"),
    "browser": re.compile(
        r"^LOCK-BROWSER/[A-Za-z0-9][A-Za-z0-9._-]{7,95}$"
    ),
    "data": re.compile(
        r"^LOCK-T4-K-DATA/[A-Za-z0-9][A-Za-z0-9._-]{7,95}$"
    ),
}
_VALIDATION_TOKEN = re.compile(r"^[A-Za-z0-9_-]{43,128}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_MARKER_ERROR = re.compile(r"^[A-Z][A-Z0-9_]{0,95}$")


class _PartialReadyCoordinator:
    """Exact-scope hidden gate client plus a private hash-chained journal."""

    _GATE_KEYS = {
        "code",
        "state",
        "claim_limit",
        "claimed_count",
        "remaining_count",
        "expires_at",
        "run_fingerprint_sha256",
        "scope_fingerprint_sha256",
    }

    def __init__(
        self,
        config: validator.RunnerConfig,
        *,
        transport: LoopbackHttpTransport,
        private_directory: validator._SecureDirectory,
    ) -> None:
        self._config = config
        self._transport = transport
        self._private_directory = private_directory
        self._generation = 0
        self._previous_record_sha256: str | None = None

    @staticmethod
    def _fingerprint(prefix: bytes, *identities: UUID) -> str:
        digest = hashlib.sha256(prefix)
        for identity in identities:
            digest.update(b"\x00")
            digest.update(str(identity).encode("ascii"))
        return digest.hexdigest()

    def _require_config(self, config: validator.RunnerConfig) -> None:
        fields = (
            "run_id",
            "mode",
            "fixture_manifest",
            "api_base",
            "novel_id",
            "document_id",
            "automatic_case_id",
            "manual_case_id",
            "private_work_dir",
            "output_dir",
            "duration_minutes",
            "listening_record",
            "resume",
        )
        if type(config) is not validator.RunnerConfig or any(
            getattr(config, field) != getattr(self._config, field)
            for field in fields
        ):
            raise RunnerError("PARTIAL_READY_COORDINATOR_SCOPE_INVALID")

    @staticmethod
    def _strict_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise RunnerError("PARTIAL_READY_GATE_INVALID")
            value[key] = item
        return value

    def _request(
        self,
        config: validator.RunnerConfig,
        *,
        method: Literal["GET", "POST"],
        release: bool = False,
        arm: bool = False,
    ) -> ValidationClaimGateEvidence:
        self._require_config(config)
        if method == "GET" and (release or arm):
            raise RunnerError("PARTIAL_READY_GATE_INVALID")
        path = (
            f"/novels/{config.novel_id}/documents/{config.document_id}"
            "/narration-validation-segment-claim-gate"
            + ("/release" if release else "")
        )
        body: Mapping[str, object] | None = None
        if method == "POST":
            body = {
                "run_id": str(config.run_id),
                **(
                    {"ttl_seconds": 300, "segment_claim_limit": 1}
                    if arm
                    else {}
                ),
            }
        response = self._transport.request(
            method=method,
            path=path,
            json_body=body,
            timeout_seconds=30,
        )
        if (
            response.status != 200
            or response.header("Cache-Control") != "no-store"
            or not response.body
            or len(response.body) > 64 * 1024
        ):
            raise RunnerError("PARTIAL_READY_GATE_INVALID")
        try:
            payload = json.loads(
                response.body.decode("utf-8", errors="strict"),
                object_pairs_hook=self._strict_pairs,
            )
        except RunnerError:
            raise
        except (UnicodeError, json.JSONDecodeError) as error:
            raise RunnerError("PARTIAL_READY_GATE_INVALID") from error
        if type(payload) is not dict or set(payload) != self._GATE_KEYS:
            raise RunnerError("PARTIAL_READY_GATE_INVALID")
        state = payload.get("state")
        if state not in {"default_allow", "armed", "paused"}:
            raise RunnerError("PARTIAL_READY_GATE_INVALID")
        run_fingerprint = payload.get("run_fingerprint_sha256")
        scope_fingerprint = payload.get("scope_fingerprint_sha256")
        expected_run = self._fingerprint(
            b"narration-validation-claim-gate-run/1",
            config.run_id,
        )
        expected_scope = self._fingerprint(
            b"narration-validation-claim-gate-scope/1",
            config.novel_id,
            config.document_id,
        )
        if (
            type(payload.get("code")) is not str
            or _MARKER_ERROR.fullmatch(payload["code"]) is None
            or type(payload.get("claim_limit")) is not int
            or type(payload.get("claimed_count")) is not int
            or type(payload.get("remaining_count")) is not int
            or not 0 <= payload["claim_limit"] <= 16
            or not 0 <= payload["claimed_count"] <= payload["claim_limit"]
            or payload["remaining_count"]
            != max(0, payload["claim_limit"] - payload["claimed_count"])
            or (
                payload.get("expires_at") is not None
                and (
                    type(payload["expires_at"]) is not str
                    or not 20 <= len(payload["expires_at"]) <= 40
                )
            )
            or (
                run_fingerprint is not None
                and run_fingerprint != expected_run
            )
            or (
                scope_fingerprint is not None
                and scope_fingerprint != expected_scope
            )
            or (
                state in {"armed", "paused"}
                and (
                    run_fingerprint != expected_run
                    or scope_fingerprint != expected_scope
                    or type(payload.get("expires_at")) is not str
                )
            )
            or (
                state == "armed"
                and (
                    payload["code"] != "VALIDATION_SEGMENT_CLAIM_GATE_ARMED"
                    or payload["remaining_count"] == 0
                )
            )
            or (
                state == "paused"
                and (
                    payload["code"] != "VALIDATION_SEGMENT_CLAIM_GATE_PAUSED"
                    or payload["remaining_count"] != 0
                )
            )
            or (
                state == "default_allow"
                and payload["code"]
                not in {
                    "VALIDATION_SEGMENT_CLAIM_GATE_RELEASED",
                    "VALIDATION_SEGMENT_CLAIM_GATE_DEFAULT_ALLOW",
                }
            )
        ):
            raise RunnerError("PARTIAL_READY_GATE_INVALID")
        return ValidationClaimGateEvidence(
            code=payload["code"],
            state=state,
            claim_limit=payload["claim_limit"],
            claimed_count=payload["claimed_count"],
            remaining_count=payload["remaining_count"],
            expires_at=payload.get("expires_at"),
            run_fingerprint_sha256=run_fingerprint,
            scope_fingerprint_sha256=scope_fingerprint,
        )

    def require_host_prearm_and_release(self) -> None:
        armed = self.read(self._config)
        if (
            armed.code != "VALIDATION_SEGMENT_CLAIM_GATE_ARMED"
            or armed.state != "armed"
            or armed.claim_limit != 1
            or armed.claimed_count != 0
            or armed.remaining_count != 1
        ):
            raise RunnerError("PARTIAL_READY_HOST_GATE_INVALID")
        released = self.release(self._config)
        if (
            released.state != "default_allow"
            or released.code
            not in {
                "VALIDATION_SEGMENT_CLAIM_GATE_RELEASED",
                "VALIDATION_SEGMENT_CLAIM_GATE_DEFAULT_ALLOW",
            }
        ):
            raise RunnerError("PARTIAL_READY_HOST_GATE_INVALID")

    def arm(
        self,
        config: validator.RunnerConfig,
    ) -> ValidationClaimGateEvidence:
        return self._request(config, method="POST", arm=True)

    def read(
        self,
        config: validator.RunnerConfig,
    ) -> ValidationClaimGateEvidence:
        return self._request(config, method="GET")

    def release(
        self,
        config: validator.RunnerConfig,
    ) -> ValidationClaimGateEvidence:
        return self._request(config, method="POST", release=True)

    @staticmethod
    def _optional_uuid(value: UUID | None) -> str | None:
        return str(value) if value is not None else None

    @staticmethod
    def _optional_sha256(value: str | None) -> str | None:
        if value is not None and (
            type(value) is not str or _SHA256.fullmatch(value) is None
        ):
            raise RunnerError("PARTIAL_READY_MARKER_INVALID")
        return value

    def record(
        self,
        config: validator.RunnerConfig,
        *,
        state: Literal[
            "staging",
            "gate_armed",
            "partial_ready",
            "browser_observed",
            "gate_released",
            "completed_restored",
            "recovery_required",
        ],
        evidence: PartialReadyValidationEvidence,
    ) -> None:
        self._require_config(config)
        allowed_states = {
            "staging",
            "gate_armed",
            "partial_ready",
            "browser_observed",
            "gate_released",
            "completed_restored",
            "recovery_required",
        }
        if (
            type(evidence) is not PartialReadyValidationEvidence
            or state not in allowed_states
            or any(
                value is not None and type(value) is not UUID
                for value in (
                    evidence.request_id,
                    evidence.script_version_id,
                    evidence.edition_id,
                )
            )
            or any(
                value is not None and (type(value) is not int or value < 0)
                for value in (
                    evidence.manifest_revision,
                    evidence.ready_prefix_count,
                    evidence.ready_prefix_duration_ms,
                    evidence.cache_hit_prefix_count,
                    evidence.cache_miss_job_count,
                    evidence.gate_claimed_count,
                )
            )
        ):
            raise RunnerError("PARTIAL_READY_MARKER_INVALID")
        for required_hash in (
            evidence.source_content_sha256,
            evidence.return_fence_sha256,
        ):
            if (
                type(required_hash) is not str
                or _SHA256.fullmatch(required_hash) is None
            ):
                raise RunnerError("PARTIAL_READY_MARKER_INVALID")
        if evidence.error_code is not None and _MARKER_ERROR.fullmatch(
            evidence.error_code
        ) is None:
            raise RunnerError("PARTIAL_READY_MARKER_INVALID")
        if state in {"partial_ready", "browser_observed", "completed_restored"}:
            if (
                any(
                    value is None
                    for value in (
                        evidence.request_id,
                        evidence.script_version_id,
                        evidence.edition_id,
                        evidence.manifest_revision,
                        evidence.manifest_etag_sha256,
                        evidence.manifest_payload_sha256,
                        evidence.ready_prefix_count,
                        evidence.ready_prefix_duration_ms,
                        evidence.cache_hit_prefix_count,
                        evidence.cache_miss_job_count,
                        evidence.gate_claimed_count,
                    )
                )
                or (evidence.ready_prefix_count or 0) < 3
                or (evidence.ready_prefix_duration_ms or 0) < 8_000
                or (evidence.cache_hit_prefix_count or 0) < 3
                or (evidence.cache_miss_job_count or 0) < 2
                or evidence.gate_claimed_count != 1
            ):
                raise RunnerError("PARTIAL_READY_MARKER_INVALID")
        if state == "completed_restored" and evidence.restored_fence_sha256 is None:
            raise RunnerError("PARTIAL_READY_MARKER_INVALID")
        if state == "recovery_required" and evidence.error_code is None:
            raise RunnerError("PARTIAL_READY_MARKER_INVALID")
        generation = self._generation + 1
        payload: dict[str, object] = {
            "schema_version": PARTIAL_READY_MARKER_SCHEMA,
            "generation": generation,
            "previous_record_sha256": self._previous_record_sha256,
            "state": state,
            "run_id": str(config.run_id),
            "novel_id": str(config.novel_id),
            "document_id": str(config.document_id),
            "source_content_sha256": evidence.source_content_sha256,
            "return_fence_sha256": evidence.return_fence_sha256,
            "request_id": self._optional_uuid(evidence.request_id),
            "script_version_id": self._optional_uuid(
                evidence.script_version_id
            ),
            "edition_id": self._optional_uuid(evidence.edition_id),
            "manifest_revision": evidence.manifest_revision,
            "manifest_etag_sha256": self._optional_sha256(
                evidence.manifest_etag_sha256
            ),
            "manifest_payload_sha256": self._optional_sha256(
                evidence.manifest_payload_sha256
            ),
            "ready_prefix_count": evidence.ready_prefix_count,
            "ready_prefix_duration_ms": evidence.ready_prefix_duration_ms,
            "cache_hit_prefix_count": evidence.cache_hit_prefix_count,
            "cache_miss_job_count": evidence.cache_miss_job_count,
            "gate_claimed_count": evidence.gate_claimed_count,
            "gate_run_fingerprint_sha256": self._optional_sha256(
                evidence.gate_run_fingerprint_sha256
            ),
            "gate_scope_fingerprint_sha256": self._optional_sha256(
                evidence.gate_scope_fingerprint_sha256
            ),
            "restored_fence_sha256": self._optional_sha256(
                evidence.restored_fence_sha256
            ),
            "error_code": evidence.error_code,
        }
        if self._generation == 0:
            validator._atomic_create_json(
                self._private_directory,
                PARTIAL_READY_MARKER_FILENAME,
                payload,
                code="PARTIAL_READY_MARKER_WRITE_FAILED",
                exists_code="PARTIAL_READY_MARKER_EXISTS",
            )
        else:
            validator._atomic_write_json(
                self._private_directory,
                PARTIAL_READY_MARKER_FILENAME,
                payload,
                "PARTIAL_READY_MARKER_WRITE_FAILED",
            )
        raw = validator._canonical_json_bytes(payload) + b"\n"
        self._generation = generation
        self._previous_record_sha256 = hashlib.sha256(raw).hexdigest()


class _SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # pragma: no cover - argparse owns text
        del message
        raise RunnerError("REAL_LAUNCHER_ARGUMENTS_INVALID")


def build_parser() -> argparse.ArgumentParser:
    parser = _SafeParser(description=__doc__)
    parser.add_argument("--mode", choices=("real",), required=True)
    parser.add_argument("--operator-envelope-file", type=Path, required=True)
    parser.add_argument("--readiness-attestation-file", type=Path, required=True)
    parser.add_argument("--probe-report", type=Path, required=True)
    parser.add_argument("--validation-token-file", type=Path, required=True)
    parser.add_argument("--lock-nano-file", type=Path, required=True)
    parser.add_argument("--lock-browser-file", type=Path, required=True)
    parser.add_argument("--lock-data-file", type=Path, required=True)
    parser.add_argument("--lock-nano-grant", required=True)
    parser.add_argument("--lock-browser-grant", required=True)
    parser.add_argument("--lock-data-grant", required=True)
    parser.add_argument("--confirm-fixed-launcher", required=True)
    return parser


def _validate_launcher_args(args: argparse.Namespace) -> None:
    if args.confirm_fixed_launcher != FIXED_LAUNCHER_CONFIRMATION:
        raise RunnerError("REAL_LAUNCHER_CONFIRMATION_REQUIRED")
    grants = {
        "nano": args.lock_nano_grant,
        "browser": args.lock_browser_grant,
        "data": args.lock_data_grant,
    }
    if any(
        type(value) is not str or _GRANT_PATTERNS[name].fullmatch(value) is None
        for name, value in grants.items()
    ):
        raise RunnerError("REAL_LAUNCHER_GRANT_INVALID")
    paths = (
        args.operator_envelope_file,
        args.readiness_attestation_file,
        args.probe_report,
        args.validation_token_file,
        args.lock_nano_file,
        args.lock_browser_file,
        args.lock_data_file,
    )
    if any(not isinstance(path, Path) or not path.is_absolute() for path in paths):
        raise RunnerError("REAL_LAUNCHER_PATH_INVALID")
    if args.validation_token_file != FIXED_VALIDATION_TOKEN_FILE:
        raise RunnerError("VALIDATION_TOKEN_FILE_INVALID")
    try:
        if (
            args.validation_token_file.resolve(strict=True)
            != FIXED_VALIDATION_TOKEN_FILE.resolve(strict=True)
        ):
            raise RunnerError("VALIDATION_TOKEN_FILE_INVALID")
    except OSError as error:
        raise RunnerError("VALIDATION_TOKEN_FILE_INVALID") from error
    private_paths = (
        args.operator_envelope_file,
        args.readiness_attestation_file,
        args.probe_report,
        args.validation_token_file,
        args.lock_nano_file,
        args.lock_browser_file,
        args.lock_data_file,
    )
    if len(set(private_paths)) != len(private_paths):
        raise RunnerError("REAL_LAUNCHER_LOCK_INVALID")


def _read_private_validation_token(path: Path) -> str:
    parent_descriptor: int | None = None
    descriptor: int | None = None
    try:
        supplied_parent = path.parent.lstat()
        parent = path.parent.resolve(strict=True)
        resolved_file = path.resolve(strict=True)
        repository = REPOSITORY_ROOT.resolve(strict=True)
        if (
            not stat.S_ISDIR(supplied_parent.st_mode)
            or stat.S_ISLNK(supplied_parent.st_mode)
            or stat.S_IMODE(supplied_parent.st_mode) != 0o700
            or supplied_parent.st_uid != os.getuid()
            or parent == repository
            or parent.is_relative_to(repository)
            or resolved_file == repository
            or resolved_file.is_relative_to(repository)
        ):
            raise RunnerError("VALIDATION_TOKEN_FILE_INVALID")
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            raise RunnerError("VALIDATION_TOKEN_POLICY_UNAVAILABLE")
        parent_descriptor = os.open(
            parent,
            os.O_RDONLY
            | os.O_DIRECTORY
            | getattr(os, "O_CLOEXEC", 0)
            | nofollow,
        )
        opened_parent = os.fstat(parent_descriptor)
        entry_before = os.stat(
            path.name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        descriptor = os.open(
            path.name,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | nofollow,
            dir_fd=parent_descriptor,
        )
        details = os.fstat(descriptor)
        resolved_details = resolved_file.stat()
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_nlink != 1
            or stat.S_IMODE(details.st_mode) != 0o600
            or details.st_uid != os.getuid()
            or not 43 <= details.st_size <= 128
            or details.st_dev != resolved_details.st_dev
            or details.st_ino != resolved_details.st_ino
            or details.st_dev != entry_before.st_dev
            or details.st_ino != entry_before.st_ino
        ):
            raise RunnerError("VALIDATION_TOKEN_FILE_INVALID")
        raw = os.read(descriptor, 129)
        after = os.fstat(descriptor)
        post_parent = path.parent.resolve(strict=True)
        post_file = path.resolve(strict=True)
        post_details = post_file.stat()
        entry_after = os.stat(
            path.name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        parent_after = os.fstat(parent_descriptor)
        if (
            (details.st_dev, details.st_ino, details.st_size, details.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            or after.st_dev != post_details.st_dev
            or after.st_ino != post_details.st_ino
            or after.st_dev != entry_after.st_dev
            or after.st_ino != entry_after.st_ino
            or (parent_after.st_dev, parent_after.st_ino)
            != (opened_parent.st_dev, opened_parent.st_ino)
            or post_parent != parent
            or post_file != resolved_file
            or post_parent == repository
            or post_parent.is_relative_to(repository)
            or post_file == repository
            or post_file.is_relative_to(repository)
        ):
            raise RunnerError("VALIDATION_TOKEN_FILE_INVALID")
        try:
            value = raw.decode("ascii", errors="strict")
        except UnicodeDecodeError as error:
            raise RunnerError("VALIDATION_TOKEN_FILE_INVALID") from error
        if len(raw) != details.st_size or _VALIDATION_TOKEN.fullmatch(value) is None:
            raise RunnerError("VALIDATION_TOKEN_FILE_INVALID")
        return value
    except RunnerError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise RunnerError("VALIDATION_TOKEN_FILE_INVALID") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if parent_descriptor is not None:
            os.close(parent_descriptor)


def _read_private_controller_artifact(
    directory: validator._SecureDirectory,
    name: str,
    *,
    maximum_bytes: int,
    ascii_only: bool = False,
) -> bytes:
    code = "CONTROLLER_PREFLIGHT_FILE_INVALID"
    descriptor: int | None = None
    try:
        descriptor, opened = validator._open_named_file(
            directory,
            name,
            code,
            maximum_bytes=maximum_bytes,
        )
        chunks: list[bytes] = []
        remaining = opened.st_size
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                raise RunnerError(code)
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise RunnerError(code)
        after = os.fstat(descriptor)
        path_after = os.stat(
            name,
            dir_fd=directory.descriptor,
            follow_symlinks=False,
        )
        if (
            validator._file_identity(after)
            != validator._file_identity(opened)
            or validator._file_identity(path_after)
            != validator._file_identity(opened)
        ):
            raise RunnerError(code)
        raw = b"".join(chunks)
        if ascii_only:
            try:
                raw.decode("ascii", errors="strict")
            except UnicodeDecodeError as error:
                raise RunnerError(code) from error
        directory.assert_stable()
        return raw
    except RunnerError:
        raise
    except OSError as error:
        raise RunnerError(code) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _preflight_expectation(
    *,
    envelope: object,
    config: validator.RunnerConfig,
    fixture: validator.ChapterFixture,
) -> PreflightExpectation:
    if (
        getattr(envelope, "required_captures", None)
        != FIXED_REQUIRED_CAPTURES
    ):
        raise RunnerError("CONTROLLER_PREFLIGHT_BINDING_INVALID")
    nonce = getattr(envelope, "nonce", None)
    run_id = getattr(envelope, "run_id", None)
    novel_id = getattr(envelope, "novel_id", None)
    document_id = getattr(envelope, "document_id", None)
    fixture_sha256 = getattr(envelope, "fixture_manifest_sha256", None)
    envelope_sha256 = getattr(
        envelope,
        "envelope_fingerprint_sha256",
        None,
    )
    if (
        type(nonce) is not str
        or run_id != config.run_id
        or novel_id != config.novel_id
        or document_id != config.document_id
        or fixture_sha256 != fixture.manifest_sha256
        or type(envelope_sha256) is not str
    ):
        raise RunnerError("CONTROLLER_PREFLIGHT_BINDING_INVALID")
    scope = canonical_json_bytes(
        {
            "document_id": str(document_id),
            "novel_id": str(novel_id),
        }
    )
    try:
        return PreflightExpectation(
            nonce_sha256=hashlib.sha256(nonce.encode("utf-8")).hexdigest(),
            run_fingerprint_sha256=hashlib.sha256(
                str(run_id).encode("utf-8")
            ).hexdigest(),
            target_scope_sha256=hashlib.sha256(scope).hexdigest(),
            operator_envelope_sha256=envelope_sha256,
            fixture_manifest_sha256=fixture_sha256,
        )
    except (ControllerTrustError, UnicodeError) as error:
        raise RunnerError("CONTROLLER_PREFLIGHT_BINDING_INVALID") from error


def _verify_controller_preflight(
    *,
    private_directory: validator._SecureDirectory,
    envelope: object,
    config: validator.RunnerConfig,
    fixture: validator.ChapterFixture,
) -> str:
    payload = _read_private_controller_artifact(
        private_directory,
        CONTROLLER_PREFLIGHT_FILENAME,
        maximum_bytes=MAX_PREFLIGHT_BYTES,
    )
    signature = _read_private_controller_artifact(
        private_directory,
        CONTROLLER_PREFLIGHT_SIGNATURE_FILENAME,
        maximum_bytes=MAX_SIGNATURE_BYTES,
        ascii_only=True,
    )
    expectation = _preflight_expectation(
        envelope=envelope,
        config=config,
        fixture=fixture,
    )
    try:
        FixedControllerTrustVerifier().verify_preflight(
            payload,
            signature,
            expectation=expectation,
        )
    except ControllerTrustError as error:
        if error.code == CONTROLLER_TRUST_ROOT_HOLD_ERROR:
            raise RunnerError(PROBE_CONTROLLER_AUTHORITY_HOLD_ERROR) from None
        raise RunnerError(error.code) from None
    return hashlib.sha256(payload).hexdigest()


def _local_executor_binding_sha256(
    *,
    envelope: object,
    config: validator.RunnerConfig,
    fixture: validator.ChapterFixture,
) -> str:
    """Bind the local executor to the exact run without a signature claim."""

    expectation = _preflight_expectation(
        envelope=envelope,
        config=config,
        fixture=fixture,
    )
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "schema_version": (
                    "moss-tts-t4k-local-executor-binding/1.0"
                ),
                "run_fingerprint_sha256": (
                    expectation.run_fingerprint_sha256
                ),
                "target_scope_sha256": expectation.target_scope_sha256,
                "operator_envelope_sha256": (
                    expectation.operator_envelope_sha256
                ),
                "fixture_manifest_sha256": (
                    expectation.fixture_manifest_sha256
                ),
            }
        )
    ).hexdigest()


@contextmanager
def _private_work_directory(
    path: Path,
) -> Iterator[validator._SecureDirectory]:
    try:
        supplied = path.lstat()
    except OSError as error:
        raise RunnerError("REAL_LAUNCHER_PRIVATE_DIR_INVALID") from error
    if (
        not path.is_absolute()
        or ".." in path.parts
        or not stat.S_ISDIR(supplied.st_mode)
        or stat.S_ISLNK(supplied.st_mode)
        or supplied.st_uid != os.getuid()
        or stat.S_IMODE(supplied.st_mode) != 0o700
    ):
        raise RunnerError("REAL_LAUNCHER_PRIVATE_DIR_INVALID")
    directory = validator._open_secure_directory(
        path,
        "REAL_LAUNCHER_PRIVATE_DIR_INVALID",
    )
    try:
        yield directory
        directory.assert_stable()
    finally:
        directory.close()


def _require_private_work_parent(
    path: Path,
    directory: validator._SecureDirectory,
) -> None:
    try:
        supplied_parent = path.parent.lstat()
        resolved_parent = path.parent.resolve(strict=True)
    except OSError as error:
        raise RunnerError("REAL_LAUNCHER_PRIVATE_FILE_MISMATCH") from error
    if (
        path.parent != directory.path
        or resolved_parent != directory.path
        or validator._directory_identity(supplied_parent)
        != directory.opened_identity
    ):
        raise RunnerError("REAL_LAUNCHER_PRIVATE_FILE_MISMATCH")
    directory.assert_stable()


@contextmanager
def _private_lock(
    path: Path,
    *,
    private_directory: validator._SecureDirectory,
    name: str,
    grant: str,
    expected_identity_sha256: str,
    busy_code: str,
) -> Iterator[str]:
    descriptor: int | None = None
    try:
        _require_private_work_parent(path, private_directory)
        private_directory.assert_stable()
        flags = os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            raise RunnerError("REAL_LAUNCHER_LOCK_POLICY_UNAVAILABLE")
        entry_before = os.stat(
            path.name,
            dir_fd=private_directory.descriptor,
            follow_symlinks=False,
        )
        descriptor = os.open(
            path.name,
            flags | nofollow,
            dir_fd=private_directory.descriptor,
        )
        details = os.fstat(descriptor)
        if (
            (entry_before.st_dev, entry_before.st_ino)
            != (details.st_dev, details.st_ino)
        ):
            raise RunnerError("REAL_LAUNCHER_LOCK_INVALID")
        actual_identity = private_lock_identity_from_stat(
            details,
            name=name,
            grant=grant,
        )
        if actual_identity != expected_identity_sha256:
            raise RunnerError("REAL_LAUNCHER_LOCK_INVALID")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RunnerError(busy_code) from error
        entry_locked = os.stat(
            path.name,
            dir_fd=private_directory.descriptor,
            follow_symlinks=False,
        )
        if (entry_locked.st_dev, entry_locked.st_ino) != (
            details.st_dev,
            details.st_ino,
        ):
            raise RunnerError("REAL_LAUNCHER_LOCK_INVALID")
        yield actual_identity
        entry_after = os.stat(
            path.name,
            dir_fd=private_directory.descriptor,
            follow_symlinks=False,
        )
        if (
            (entry_after.st_dev, entry_after.st_ino)
            != (details.st_dev, details.st_ino)
        ):
            raise RunnerError("REAL_LAUNCHER_LOCK_INVALID")
        private_directory.assert_stable()
    except RunnerError:
        raise
    except OSError as error:
        raise RunnerError("REAL_LAUNCHER_LOCK_INVALID") from error
    finally:
        if descriptor is not None:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)


def _safe_console(code: str) -> None:
    sys.stderr.write(
        json.dumps(
            {"status": "FAILED", "code": code},
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )


def main(argv: Sequence[str] | None = None) -> int:
    try:
        launcher_args, runner_argv = build_parser().parse_known_args(argv)
        _validate_launcher_args(launcher_args)
        runner_args = validator.build_parser().parse_args(
            ["--mode", "real", *runner_argv]
        )
        if runner_args.run_id is None:
            raise RunnerError("OPERATOR_ENVELOPE_RUN_REQUIRED")
        config = validator.build_runner_config(runner_args)
        if launcher_args.probe_report != (
            config.private_work_dir / PROBE_REPORT_FILENAME
        ):
            raise RunnerError("REAL_LAUNCHER_PROBE_PATH_MISMATCH")
        fixture = validator.load_fixture(
            config.fixture_manifest,
            automatic_case_id=config.automatic_case_id,
            manual_case_id=config.manual_case_id,
        )
        with _private_work_directory(config.private_work_dir) as private_directory:
            for private_path in (
                launcher_args.operator_envelope_file,
                launcher_args.readiness_attestation_file,
                launcher_args.probe_report,
                launcher_args.lock_nano_file,
                launcher_args.lock_browser_file,
                launcher_args.lock_data_file,
            ):
                _require_private_work_parent(private_path, private_directory)
            envelope = load_operator_envelope(
                launcher_args.operator_envelope_file,
                require_fresh=not config.resume,
            )
            attestation = load_private_attestation(
                launcher_args.readiness_attestation_file
            )
            lock_paths = {
                "nano": launcher_args.lock_nano_file,
                "browser": launcher_args.lock_browser_file,
                "data": launcher_args.lock_data_file,
            }
            lock_grants = {
                "nano": launcher_args.lock_nano_grant,
                "browser": launcher_args.lock_browser_grant,
                "data": launcher_args.lock_data_grant,
            }
            envelope_locks = {item.name: item for item in envelope.locks}
            if set(envelope_locks) != set(EXPECTED_LOCK_NAMES):
                raise RunnerError("REAL_LAUNCHER_LOCK_INVALID")
            with ExitStack() as locks:
                lock_identities = {}
                for name, path, grant, busy_code in (
                    (
                        "nano",
                        launcher_args.lock_nano_file,
                        launcher_args.lock_nano_grant,
                        "LOCK_NANO_BUSY",
                    ),
                    (
                        "browser",
                        launcher_args.lock_browser_file,
                        launcher_args.lock_browser_grant,
                        "LOCK_BROWSER_BUSY",
                    ),
                    (
                        "data",
                        launcher_args.lock_data_file,
                        launcher_args.lock_data_grant,
                        "LOCK_T4_K_DATA_BUSY",
                    ),
                ):
                    lock_identities[name] = locks.enter_context(
                        _private_lock(
                            path,
                            private_directory=private_directory,
                            name=name,
                            grant=grant,
                            expected_identity_sha256=(
                                envelope_locks[name].identity_sha256
                            ),
                            busy_code=busy_code,
                        )
                    )
                session_factory = None
                readiness_report = None
                if not config.resume:
                    session_factory = sessionmaker(
                        bind=get_engine(),
                        expire_on_commit=False,
                    )
                    readiness_report = evaluate_readiness(
                        attestation,
                        reader=SqlAlchemyReadinessReader(
                            session_factory,
                            storage=_storage_from_environment(),
                        ),
                        _preheld_resource_locks=EXPECTED_LOCK_NAMES,
                        _include_authority_fingerprint=True,
                    )
                verify_operator_envelope_binding(
                    envelope,
                    config=config,
                    fixture=fixture,
                    attestation=attestation,
                    lock_paths=lock_paths,
                    lock_grants=lock_grants,
                    lock_identity_sha256=lock_identities,
                    readiness_report=readiness_report,
                    resume=config.resume,
                )
                validation_token = _read_private_validation_token(
                    launcher_args.validation_token_file
                )
                partial_ready_coordinator: _PartialReadyCoordinator | None = None
                if not config.resume:
                    verify_t4k_hidden_release_gate(
                        config,
                        validation_token=validation_token,
                    )
                    # The personal local product trusts the fixed executor and
                    # its author/operator.  Bind the exact run, scope,
                    # envelope and fixture without claiming an independent
                    # signing authority or remote attestation.
                    executor_binding_sha256 = _local_executor_binding_sha256(
                        envelope=envelope,
                        config=config,
                        fixture=fixture,
                    )
                    partial_ready_coordinator = _PartialReadyCoordinator(
                        config,
                        transport=LoopbackHttpTransport(
                            config.api_base,
                            validation_token=validation_token,
                        ),
                        private_directory=private_directory,
                    )
                    partial_ready_coordinator.require_host_prearm_and_release()
                else:
                    executor_binding_sha256 = None

                def transport_factory(config):  # type: ignore[no-untyped-def]
                    return LoopbackHttpTransport(
                        config.api_base,
                        validation_token=validation_token,
                    )

                validator_kwargs: dict[str, object]
                if config.resume:
                    validator_kwargs = {
                        "recovery_executor_factory": (
                            build_real_recovery_executor_factory(
                                transport_factory=transport_factory,
                            )
                        )
                    }
                else:
                    if executor_binding_sha256 is None:
                        raise RunnerError(
                            "LOCAL_EXECUTOR_BINDING_INVALID"
                        )
                    cache = BoundProbeReportCache(
                        launcher_args.probe_report,
                        request_publisher=PrivateProbeRequestPublisher(
                            preflight_payload_sha256=(
                                executor_binding_sha256
                            ),
                        ),
                        report_guard=LocalOperatorCollectorReportGuard(),
                    )

                    def browser_factory(config):  # type: ignore[no-untyped-def]
                        return StrictReportBrowserProbe(config, cache=cache)

                    def runtime_factory(config):  # type: ignore[no-untyped-def]
                        assert session_factory is not None
                        reader = SqlAlchemyRuntimeAuditReader(session_factory)
                        return ReportBackedRuntimeAuditProbe(
                            config,
                            reader=reader,
                            cache=cache,
                        )

                    validator_kwargs = {
                        "executor_factory": build_real_executor_factory(
                            transport_factory=transport_factory,
                            browser_probe_factory=browser_factory,
                            runtime_audit_probe_factory=runtime_factory,
                            partial_ready_coordinator=(
                                partial_ready_coordinator
                            ),
                        )
                    }
                with claim_operator_envelope(
                    launcher_args.operator_envelope_file,
                    envelope,
                    private_work_dir=config.private_work_dir,
                    private_work_dir_identity=private_directory.opened_identity,
                    resume=config.resume,
                    now=datetime.now(timezone.utc),
                ) as claim:
                    return validator.main(
                        ["--mode", "real", *runner_argv],
                        fixture_override=fixture,
                        recovery_claim_binding=claim.binding,
                        recovery_state_observer=claim.transition,
                        recovery_claim_state_reader=claim.snapshot,
                        **validator_kwargs,
                    )
    except (
        RunnerError,
        ProbeReportError,
        OperatorEnvelopeError,
        ReadinessError,
    ) as error:
        _safe_console(error.code)
        return 2
    except KeyboardInterrupt:
        _safe_console("REAL_LAUNCHER_INTERRUPTED")
        return 130
    except SystemExit as error:
        if error.code == 0:
            return 0
        _safe_console("REAL_LAUNCHER_ARGUMENTS_INVALID")
        return 2
    except BaseException:
        _safe_console("REAL_LAUNCHER_INTERNAL_ERROR")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
