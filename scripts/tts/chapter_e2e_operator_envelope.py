#!/usr/bin/env python3
"""Issue and verify the private, one-run T4-K operator envelope.

The envelope closes the gap between the read-only T4-K readiness audit and the
destructive real launcher.  Issuance re-runs readiness, requires an explicit
author review confirmation, and writes one short-lived, private envelope.  The
launcher independently re-checks every binding and atomically claims it before
starting a fresh real run.  A recovery run may only reuse the exact prior claim.

No command output contains raw scope identifiers, paths, nonces, grants,
fingerprints, credentials, chapter text, or media details.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import fcntl
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import sys
from typing import Callable, Final, Iterator, Mapping, Sequence
from uuid import UUID


REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from sqlalchemy.orm import sessionmaker  # noqa: E402

from backend.database import get_engine  # noqa: E402
from scripts.tts.chapter_e2e_readiness import (  # noqa: E402
    EXPECTED_ASSISTANT_MODES,
    EXPECTED_CAPTURES,
    EXPECTED_LOCK_NAMES,
    FIXTURE_AUTOMATIC_CASE,
    FIXTURE_MANUAL_CASE,
    ReadinessAttestation,
    ReadinessError,
    SqlAlchemyReadinessReader,
    _storage_from_environment,
    evaluate_readiness,
    load_private_attestation,
)
from scripts.tts.validate_chapter_e2e import (  # noqa: E402
    ALLOWED_VIEWPORTS,
    ChapterFixture,
    RecoveryClaimBinding,
    RecoveryClaimSnapshot,
    RunnerConfig,
    RunnerError,
    _SecureDirectory,
    _atomic_create_json,
    _atomic_write,
    _atomic_write_json,
    _directory_identity,
    _entry_exists,
    _open_named_file,
    _open_secure_directory,
    _read_directory_json,
    recovery_private_directory_binding,
)


ENVELOPE_SCHEMA: Final = "moss-tts-t4k-operator-envelope/1.0"
CLAIM_SCHEMA: Final = "moss-tts-t4k-operator-envelope-claim/2.1"
CLAIM_REGISTRY_DIRECTORY: Final = Path(
    "/app/working.secret/ai-novel-world-2026/t4k-operator-claims"
)
AUTHOR_REVIEW_CONFIRMATION: Final = "AUTHOR-REVIEWED-T4-K-READINESS"
FORMAL_DURATION_MINUTES: Final = 30.0
MAX_ENVELOPE_LIFETIME_SECONDS: Final = 15 * 60
MAX_FUTURE_SKEW_SECONDS: Final = 30
MAX_PRIVATE_JSON_BYTES: Final = 64 * 1024
_SHA256_RE: Final = re.compile(r"^[a-f0-9]{64}$")
_NONCE_RE: Final = re.compile(r"^[A-Za-z0-9_-]{43,128}$")
_SAFE_CODE_RE: Final = re.compile(r"^[A-Z][A-Z0-9_]{1,95}$")
_GRANT_PATTERNS: Final[Mapping[str, re.Pattern[str]]] = {
    "nano": re.compile(r"^LOCK-NANO/[A-Za-z0-9][A-Za-z0-9._-]{7,95}$"),
    "browser": re.compile(
        r"^LOCK-BROWSER/[A-Za-z0-9][A-Za-z0-9._-]{7,95}$"
    ),
    "data": re.compile(
        r"^LOCK-T4-K-DATA/[A-Za-z0-9][A-Za-z0-9._-]{7,95}$"
    ),
}


class OperatorEnvelopeError(RunnerError):
    """Stable, redacted operator-envelope failure."""

    def __init__(self, code: str) -> None:
        if _SAFE_CODE_RE.fullmatch(code) is None:
            raise ValueError("operator envelope error code must be stable")
        super().__init__(code)


class _SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # pragma: no cover - argparse boundary
        del message
        raise OperatorEnvelopeError("OPERATOR_ENVELOPE_ARGUMENTS_INVALID")


@dataclass(frozen=True, slots=True)
class OperatorLockBinding:
    name: str
    grant: str
    identity_sha256: str


@dataclass(frozen=True, slots=True)
class OperatorEnvelope:
    issued_at: datetime
    reviewed_at: datetime
    expires_at: datetime
    run_id: UUID
    nonce: str
    novel_id: UUID
    document_id: UUID
    fixture_manifest_sha256: str
    automatic_case_id: str
    manual_case_id: str
    duration_minutes: float
    required_captures: tuple[tuple[int, int, str], ...]
    locks: tuple[OperatorLockBinding, ...]
    attestation_semantic_sha256: str
    readiness_report_sha256: str
    envelope_fingerprint_sha256: str


@dataclass(slots=True)
class OperatorClaimLease:
    """One flock-held, per-run claim lease used through validator completion."""

    registry: _SecureDirectory
    claim_name: str
    lock_descriptor: int
    binding: RecoveryClaimBinding
    state: str
    recovery_generation: int
    latest_recovery_sha256: str | None
    immutable: Mapping[str, object]

    def snapshot(self) -> RecoveryClaimSnapshot:
        return RecoveryClaimSnapshot(
            state=self.state,
            recovery_generation=self.recovery_generation,
            latest_recovery_sha256=self.latest_recovery_sha256,
        )

    def transition(
        self,
        state_value: str,
        recovery_generation: int,
        recovery_record_sha256: str,
        *,
        now: datetime | None = None,
    ) -> None:
        if not _claim_transition_allowed(self.state, state_value):
            raise OperatorEnvelopeError("OPERATOR_CLAIM_TRANSITION_INVALID")
        if (
            type(recovery_generation) is not int
            or recovery_generation < 1
            or type(recovery_record_sha256) is not str
            or _SHA256_RE.fullmatch(recovery_record_sha256) is None
            or recovery_generation < self.recovery_generation
            or recovery_generation > self.recovery_generation + 1
            or (
                recovery_generation == self.recovery_generation
                and recovery_record_sha256 != self.latest_recovery_sha256
            )
            or (
                recovery_generation == self.recovery_generation + 1
                and recovery_record_sha256 == self.latest_recovery_sha256
            )
        ):
            raise OperatorEnvelopeError("OPERATOR_CLAIM_HEAD_INVALID")
        current = _claim_timestamp(now)
        observed, immutable, binding = _load_claim(
            self.registry,
            self.claim_name,
        )
        if (
            observed["state"] != self.state
            or observed["recovery_generation"] != self.recovery_generation
            or observed["latest_recovery_sha256"]
            != self.latest_recovery_sha256
            or immutable != self.immutable
            or binding != self.binding
        ):
            raise OperatorEnvelopeError("OPERATOR_ENVELOPE_CLAIM_INVALID")
        payload = _claim_payload(
            immutable,
            state=state_value,
            updated_at=_canonical_timestamp(current),
            recovery_generation=recovery_generation,
            latest_recovery_sha256=recovery_record_sha256,
        )
        _atomic_write_json(
            self.registry,
            self.claim_name,
            payload,
            "OPERATOR_ENVELOPE_CLAIM_FILE_UNSAFE",
        )
        self.state = state_value
        self.recovery_generation = recovery_generation
        self.latest_recovery_sha256 = recovery_record_sha256


@dataclass(frozen=True, slots=True)
class _RecoveryRecordHead:
    state: str
    generation: int
    previous_record_sha256: str | None
    record_sha256: str


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _canonical_file_sha256(value: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical_bytes(value) + b"\n").hexdigest()


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _canonical_timestamp(value: datetime) -> str:
    if type(value) is not datetime or value.tzinfo is None:
        raise OperatorEnvelopeError("OPERATOR_ENVELOPE_TIME_INVALID")
    normalized = value.astimezone(timezone.utc)
    if normalized.microsecond != 0:
        raise OperatorEnvelopeError("OPERATOR_ENVELOPE_TIME_INVALID")
    return normalized.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_timestamp(value: object) -> datetime:
    if type(value) is not str or len(value) != 20:
        raise OperatorEnvelopeError("OPERATOR_ENVELOPE_TIME_INVALID")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as error:
        raise OperatorEnvelopeError("OPERATOR_ENVELOPE_TIME_INVALID") from error
    if _canonical_timestamp(parsed) != value:
        raise OperatorEnvelopeError("OPERATOR_ENVELOPE_TIME_INVALID")
    return parsed


def _canonical_uuid(value: object, *, code: str) -> UUID:
    if type(value) is not str:
        raise OperatorEnvelopeError(code)
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as error:
        raise OperatorEnvelopeError(code) from error
    if (
        str(parsed) != value
        or parsed.variant != "specified in RFC 4122"
        or parsed.version is None
    ):
        raise OperatorEnvelopeError(code)
    return parsed


def _exact_object(value: object, keys: set[str], *, code: str) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        raise OperatorEnvelopeError(code)
    return value


def _strict_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise OperatorEnvelopeError("OPERATOR_ENVELOPE_JSON_INVALID")
        result[key] = value
    return result


def _reject_symlink_components(path: Path, *, code: str) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise OperatorEnvelopeError(code) from error
        if stat.S_ISLNK(metadata.st_mode):
            raise OperatorEnvelopeError(code)


def _private_external_parent(path: Path, *, code: str) -> Path:
    if not isinstance(path, Path) or not path.is_absolute() or ".." in path.parts:
        raise OperatorEnvelopeError(code)
    _reject_symlink_components(path, code=code)
    try:
        supplied = path.parent.lstat()
        resolved = path.parent.resolve(strict=True)
        resolved_details = resolved.lstat()
        repository = REPOSITORY_ROOT.resolve(strict=True)
    except OSError as error:
        raise OperatorEnvelopeError(code) from error
    if (
        not stat.S_ISDIR(supplied.st_mode)
        or stat.S_ISLNK(supplied.st_mode)
        or supplied.st_uid != os.getuid()
        or stat.S_IMODE(supplied.st_mode) != 0o700
        or (supplied.st_dev, supplied.st_ino)
        != (resolved_details.st_dev, resolved_details.st_ino)
        or resolved == repository
        or resolved.is_relative_to(repository)
    ):
        raise OperatorEnvelopeError(code)
    return resolved


def _read_private_json(path: Path, *, code: str) -> bytes:
    parent = _private_external_parent(path, code=code)
    parent_descriptor: int | None = None
    descriptor: int | None = None
    try:
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            raise OperatorEnvelopeError("OPERATOR_ENVELOPE_POLICY_UNAVAILABLE")
        parent_before = parent.lstat()
        parent_descriptor = os.open(
            parent,
            os.O_RDONLY
            | os.O_DIRECTORY
            | getattr(os, "O_CLOEXEC", 0)
            | nofollow,
        )
        opened_parent = os.fstat(parent_descriptor)
        if (
            (opened_parent.st_dev, opened_parent.st_ino)
            != (parent_before.st_dev, parent_before.st_ino)
            or not stat.S_ISDIR(opened_parent.st_mode)
            or opened_parent.st_uid != os.getuid()
            or stat.S_IMODE(opened_parent.st_mode) != 0o700
        ):
            raise OperatorEnvelopeError(code)
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
        before = os.fstat(descriptor)
        if (
            (entry_before.st_dev, entry_before.st_ino)
            != (before.st_dev, before.st_ino)
            or not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != os.getuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size <= 0
            or before.st_size > MAX_PRIVATE_JSON_BYTES
        ):
            raise OperatorEnvelopeError(code)
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(16 * 1024, remaining))
            if not chunk:
                raise OperatorEnvelopeError(code)
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise OperatorEnvelopeError(code)
        after = os.fstat(descriptor)
        entry_after = os.stat(
            path.name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        parent_after = os.fstat(parent_descriptor)
        supplied_parent_after = path.parent.lstat()
        resolved_parent_after = parent.lstat()
        _reject_symlink_components(path, code=code)
        if (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_uid,
            before.st_nlink,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_uid,
            after.st_nlink,
            after.st_size,
            after.st_mtime_ns,
        ) or (
            entry_after.st_dev,
            entry_after.st_ino,
            entry_after.st_mode,
            entry_after.st_uid,
            entry_after.st_nlink,
            entry_after.st_size,
            entry_after.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_uid,
            after.st_nlink,
            after.st_size,
            after.st_mtime_ns,
        ) or any(
            (item.st_dev, item.st_ino)
            != (opened_parent.st_dev, opened_parent.st_ino)
            for item in (
                parent_after,
                supplied_parent_after,
                resolved_parent_after,
            )
        ) or any(
            not stat.S_ISDIR(item.st_mode)
            or item.st_uid != os.getuid()
            or stat.S_IMODE(item.st_mode) != 0o700
            for item in (
                parent_after,
                supplied_parent_after,
                resolved_parent_after,
            )
        ):
            raise OperatorEnvelopeError(code)
        return b"".join(chunks)
    except OperatorEnvelopeError:
        raise
    except OSError as error:
        raise OperatorEnvelopeError(code) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if parent_descriptor is not None:
            os.close(parent_descriptor)


def _write_private_exclusive(
    path: Path,
    data: bytes,
    *,
    unsafe_code: str,
    exists_code: str,
) -> None:
    parent = _private_external_parent(path, code=unsafe_code)
    directory_descriptor: int | None = None
    file_descriptor: int | None = None
    try:
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            raise OperatorEnvelopeError("OPERATOR_ENVELOPE_POLICY_UNAVAILABLE")
        directory_descriptor = os.open(
            parent,
            os.O_RDONLY
            | os.O_DIRECTORY
            | getattr(os, "O_CLOEXEC", 0)
            | nofollow,
        )
        opened_parent = os.fstat(directory_descriptor)
        if (
            not stat.S_ISDIR(opened_parent.st_mode)
            or opened_parent.st_uid != os.getuid()
            or stat.S_IMODE(opened_parent.st_mode) != 0o700
        ):
            raise OperatorEnvelopeError(unsafe_code)
        file_descriptor = os.open(
            path.name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | nofollow,
            0o600,
            dir_fd=directory_descriptor,
        )
        opened = os.fstat(file_descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_uid != os.getuid()
            or stat.S_IMODE(opened.st_mode) != 0o600
        ):
            raise OperatorEnvelopeError(unsafe_code)
        offset = 0
        while offset < len(data):
            written = os.write(file_descriptor, data[offset:])
            if written <= 0:
                raise OperatorEnvelopeError(unsafe_code)
            offset += written
        os.fsync(file_descriptor)
        os.fsync(directory_descriptor)
    except FileExistsError as error:
        raise OperatorEnvelopeError(exists_code) from error
    except OperatorEnvelopeError:
        raise
    except OSError as error:
        raise OperatorEnvelopeError(unsafe_code) from error
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        if directory_descriptor is not None:
            os.close(directory_descriptor)


def attestation_semantic_sha256(attestation: ReadinessAttestation) -> str:
    if type(attestation) is not ReadinessAttestation:
        raise OperatorEnvelopeError("OPERATOR_ATTESTATION_INVALID")
    return _sha256(
        {
            "fixture_manifest_sha256": attestation.fixture_manifest_sha256,
            "scope": {
                "novel_id": str(attestation.novel_id),
                "document_id": str(attestation.document_id),
            },
            "declarations": {
                "dedicated_test_novel": attestation.dedicated_test_novel,
                "dedicated_test_chapter": attestation.dedicated_test_chapter,
                "append_only_recovery_accepted": (
                    attestation.append_only_recovery_accepted
                ),
                "official_presets_local_use": (
                    attestation.official_presets_local_use
                ),
            },
            "expected_characters": list(attestation.expected_characters),
            "expected_official_presets": [
                {"role": item.role, "preset_id": item.preset_id}
                for item in sorted(
                    attestation.expected_official_presets,
                    key=lambda item: item.role,
                )
            ],
            "required_captures": [
                {"width": width, "height": height, "assistant_mode": mode}
                for width, height, mode in attestation.required_captures
            ],
            "resource_locks": [
                {"name": item.name, "grant": item.grant}
                for item in sorted(
                    attestation.resource_locks,
                    key=lambda item: EXPECTED_LOCK_NAMES.index(item.name),
                )
            ],
        }
    )


def readiness_report_sha256(report: Mapping[str, object]) -> str:
    if type(report) is not dict:
        raise OperatorEnvelopeError("OPERATOR_READINESS_REPORT_INVALID")
    return _sha256(report)


def private_lock_identity_from_stat(
    metadata: os.stat_result,
    *,
    name: str,
    grant: str,
) -> str:
    if (
        name not in EXPECTED_LOCK_NAMES
        or _GRANT_PATTERNS[name].fullmatch(grant) is None
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise OperatorEnvelopeError("OPERATOR_LOCK_BINDING_INVALID")
    return _sha256(
        {
            "name": name,
            "grant": grant,
            "device": metadata.st_dev,
            "inode": metadata.st_ino,
            "uid": metadata.st_uid,
            "mode": stat.S_IMODE(metadata.st_mode),
        }
    )


def private_lock_identity_sha256(path: Path, *, name: str, grant: str) -> str:
    if name not in EXPECTED_LOCK_NAMES or _GRANT_PATTERNS[name].fullmatch(grant) is None:
        raise OperatorEnvelopeError("OPERATOR_LOCK_BINDING_INVALID")
    parent = _private_external_parent(path, code="OPERATOR_LOCK_FILE_UNSAFE")
    descriptor: int | None = None
    try:
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            raise OperatorEnvelopeError("OPERATOR_ENVELOPE_POLICY_UNAVAILABLE")
        descriptor = os.open(
            parent / path.name,
            os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | nofollow,
        )
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != os.getuid()
            or stat.S_IMODE(before.st_mode) != 0o600
        ):
            raise OperatorEnvelopeError("OPERATOR_LOCK_FILE_UNSAFE")
        result = private_lock_identity_from_stat(
            before,
            name=name,
            grant=grant,
        )
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_nlink,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_nlink,
        ) or path.parent.resolve(strict=True) != parent:
            raise OperatorEnvelopeError("OPERATOR_LOCK_FILE_UNSAFE")
        return result
    except OperatorEnvelopeError:
        raise
    except OSError as error:
        raise OperatorEnvelopeError("OPERATOR_LOCK_FILE_UNSAFE") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _envelope_unsigned(
    *,
    issued_at: datetime,
    reviewed_at: datetime,
    expires_at: datetime,
    run_id: UUID,
    nonce: str,
    attestation: ReadinessAttestation,
    locks: Sequence[OperatorLockBinding],
    readiness_digest: str,
) -> dict[str, object]:
    return {
        "schema_version": ENVELOPE_SCHEMA,
        "issued_at": _canonical_timestamp(issued_at),
        "expires_at": _canonical_timestamp(expires_at),
        "run_id": str(run_id),
        "nonce": nonce,
        "scope": {
            "novel_id": str(attestation.novel_id),
            "document_id": str(attestation.document_id),
        },
        "fixture": {
            "manifest_sha256": attestation.fixture_manifest_sha256,
            "automatic_case_id": FIXTURE_AUTOMATIC_CASE,
            "manual_case_id": FIXTURE_MANUAL_CASE,
        },
        "runtime": {
            "duration_minutes": FORMAL_DURATION_MINUTES,
            "required_captures": [
                {"width": width, "height": height, "assistant_mode": mode}
                for width, height, mode in EXPECTED_CAPTURES
            ],
        },
        "locks": [
            {
                "name": item.name,
                "grant": item.grant,
                "identity_sha256": item.identity_sha256,
            }
            for item in locks
        ],
        "readiness": {
            "attestation_semantic_sha256": attestation_semantic_sha256(
                attestation
            ),
            "report_sha256": readiness_digest,
        },
        "author_review": {
            "confirmation": AUTHOR_REVIEW_CONFIRMATION,
            "reviewed_at": _canonical_timestamp(reviewed_at),
        },
    }


def issue_operator_envelope(
    *,
    attestation: ReadinessAttestation,
    reader: object,
    run_id: UUID,
    output_file: Path,
    confirmation: str,
    now: datetime,
    nonce: str,
) -> OperatorEnvelope:
    if confirmation != AUTHOR_REVIEW_CONFIRMATION:
        raise OperatorEnvelopeError("OPERATOR_AUTHOR_REVIEW_REQUIRED")
    if type(run_id) is not UUID or type(now) is not datetime or now.tzinfo is None:
        raise OperatorEnvelopeError("OPERATOR_ENVELOPE_INPUT_INVALID")
    issued_at = now.astimezone(timezone.utc).replace(microsecond=0)
    reviewed_at = issued_at
    expires_at = issued_at + timedelta(seconds=MAX_ENVELOPE_LIFETIME_SECONDS)
    if type(nonce) is not str or _NONCE_RE.fullmatch(nonce) is None:
        raise OperatorEnvelopeError("OPERATOR_ENVELOPE_NONCE_INVALID")
    try:
        report = evaluate_readiness(  # type: ignore[arg-type]
            attestation,
            reader=reader,
            _include_authority_fingerprint=True,
        )
    except ReadinessError as error:
        raise OperatorEnvelopeError("OPERATOR_READINESS_NOT_READY") from error
    if report.get("decision") != "READY_FOR_OPERATOR_REVIEW":
        raise OperatorEnvelopeError("OPERATOR_READINESS_NOT_READY")
    by_name = {item.name: item for item in attestation.resource_locks}
    if set(by_name) != set(EXPECTED_LOCK_NAMES):
        raise OperatorEnvelopeError("OPERATOR_LOCK_BINDING_INVALID")
    locks = tuple(
        OperatorLockBinding(
            name=name,
            grant=by_name[name].grant,
            identity_sha256=private_lock_identity_sha256(
                by_name[name].path,
                name=name,
                grant=by_name[name].grant,
            ),
        )
        for name in EXPECTED_LOCK_NAMES
    )
    unsigned = _envelope_unsigned(
        issued_at=issued_at,
        reviewed_at=reviewed_at,
        expires_at=expires_at,
        run_id=run_id,
        nonce=nonce,
        attestation=attestation,
        locks=locks,
        readiness_digest=readiness_report_sha256(report),
    )
    payload = {**unsigned, "envelope_fingerprint_sha256": _sha256(unsigned)}
    _write_private_exclusive(
        output_file,
        _canonical_bytes(payload) + b"\n",
        unsafe_code="OPERATOR_ENVELOPE_WRITE_FAILED",
        exists_code="OPERATOR_ENVELOPE_EXISTS",
    )
    return load_operator_envelope(output_file, now=issued_at)


def _capture_matrix(value: object) -> tuple[tuple[int, int, str], ...]:
    if type(value) is not list:
        raise OperatorEnvelopeError("OPERATOR_ENVELOPE_RUNTIME_INVALID")
    captures: list[tuple[int, int, str]] = []
    for item in value:
        capture = _exact_object(
            item,
            {"width", "height", "assistant_mode"},
            code="OPERATOR_ENVELOPE_RUNTIME_INVALID",
        )
        width = capture["width"]
        height = capture["height"]
        mode = capture["assistant_mode"]
        if (
            type(width) is not int
            or type(height) is not int
            or type(mode) is not str
        ):
            raise OperatorEnvelopeError("OPERATOR_ENVELOPE_RUNTIME_INVALID")
        captures.append((width, height, mode))
    return tuple(captures)


def load_operator_envelope(
    path: Path,
    *,
    now: datetime | None = None,
    require_fresh: bool = True,
) -> OperatorEnvelope:
    raw = _read_private_json(path, code="OPERATOR_ENVELOPE_FILE_UNSAFE")
    try:
        payload = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                OperatorEnvelopeError("OPERATOR_ENVELOPE_JSON_INVALID")
            ),
        )
    except OperatorEnvelopeError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OperatorEnvelopeError("OPERATOR_ENVELOPE_JSON_INVALID") from error
    value = _exact_object(
        payload,
        {
            "schema_version",
            "issued_at",
            "expires_at",
            "run_id",
            "nonce",
            "scope",
            "fixture",
            "runtime",
            "locks",
            "readiness",
            "author_review",
            "envelope_fingerprint_sha256",
        },
        code="OPERATOR_ENVELOPE_SCHEMA_INVALID",
    )
    if value["schema_version"] != ENVELOPE_SCHEMA:
        raise OperatorEnvelopeError("OPERATOR_ENVELOPE_SCHEMA_INVALID")
    unsigned = dict(value)
    fingerprint = unsigned.pop("envelope_fingerprint_sha256")
    if (
        type(fingerprint) is not str
        or _SHA256_RE.fullmatch(fingerprint) is None
        or fingerprint != _sha256(unsigned)
    ):
        raise OperatorEnvelopeError("OPERATOR_ENVELOPE_FINGERPRINT_INVALID")
    issued_at = _parse_timestamp(value["issued_at"])
    expires_at = _parse_timestamp(value["expires_at"])
    if (
        expires_at <= issued_at
        or expires_at - issued_at
        > timedelta(seconds=MAX_ENVELOPE_LIFETIME_SECONDS)
    ):
        raise OperatorEnvelopeError("OPERATOR_ENVELOPE_TIME_INVALID")
    current = now or datetime.now(timezone.utc)
    if type(current) is not datetime or current.tzinfo is None:
        raise OperatorEnvelopeError("OPERATOR_ENVELOPE_TIME_INVALID")
    current = current.astimezone(timezone.utc)
    if issued_at > current + timedelta(seconds=MAX_FUTURE_SKEW_SECONDS):
        raise OperatorEnvelopeError("OPERATOR_ENVELOPE_NOT_YET_VALID")
    if require_fresh and current > expires_at:
        raise OperatorEnvelopeError("OPERATOR_ENVELOPE_EXPIRED")
    nonce = value["nonce"]
    if type(nonce) is not str or _NONCE_RE.fullmatch(nonce) is None:
        raise OperatorEnvelopeError("OPERATOR_ENVELOPE_NONCE_INVALID")
    scope = _exact_object(
        value["scope"],
        {"novel_id", "document_id"},
        code="OPERATOR_ENVELOPE_SCOPE_INVALID",
    )
    fixture = _exact_object(
        value["fixture"],
        {"manifest_sha256", "automatic_case_id", "manual_case_id"},
        code="OPERATOR_ENVELOPE_FIXTURE_INVALID",
    )
    if (
        type(fixture["manifest_sha256"]) is not str
        or _SHA256_RE.fullmatch(fixture["manifest_sha256"]) is None
        or fixture["automatic_case_id"] != FIXTURE_AUTOMATIC_CASE
        or fixture["manual_case_id"] != FIXTURE_MANUAL_CASE
    ):
        raise OperatorEnvelopeError("OPERATOR_ENVELOPE_FIXTURE_INVALID")
    runtime = _exact_object(
        value["runtime"],
        {"duration_minutes", "required_captures"},
        code="OPERATOR_ENVELOPE_RUNTIME_INVALID",
    )
    duration = runtime["duration_minutes"]
    captures = _capture_matrix(runtime["required_captures"])
    if (
        type(duration) not in {int, float}
        or not math.isfinite(float(duration))
        or float(duration) != FORMAL_DURATION_MINUTES
        or captures != EXPECTED_CAPTURES
        or tuple(
            (width, height, mode)
            for width, height in ALLOWED_VIEWPORTS
            for mode in EXPECTED_ASSISTANT_MODES
        )
        != EXPECTED_CAPTURES
    ):
        raise OperatorEnvelopeError("OPERATOR_ENVELOPE_RUNTIME_INVALID")
    raw_locks = value["locks"]
    if type(raw_locks) is not list or len(raw_locks) != len(EXPECTED_LOCK_NAMES):
        raise OperatorEnvelopeError("OPERATOR_ENVELOPE_LOCKS_INVALID")
    locks: list[OperatorLockBinding] = []
    for expected_name, item in zip(EXPECTED_LOCK_NAMES, raw_locks, strict=True):
        lock = _exact_object(
            item,
            {"name", "grant", "identity_sha256"},
            code="OPERATOR_ENVELOPE_LOCKS_INVALID",
        )
        name = lock["name"]
        grant = lock["grant"]
        identity = lock["identity_sha256"]
        if (
            name != expected_name
            or type(grant) is not str
            or _GRANT_PATTERNS[expected_name].fullmatch(grant) is None
            or type(identity) is not str
            or _SHA256_RE.fullmatch(identity) is None
        ):
            raise OperatorEnvelopeError("OPERATOR_ENVELOPE_LOCKS_INVALID")
        locks.append(
            OperatorLockBinding(
                name=expected_name,
                grant=grant,
                identity_sha256=identity,
            )
        )
    readiness = _exact_object(
        value["readiness"],
        {"attestation_semantic_sha256", "report_sha256"},
        code="OPERATOR_ENVELOPE_READINESS_INVALID",
    )
    if any(
        type(readiness[key]) is not str
        or _SHA256_RE.fullmatch(readiness[key]) is None
        for key in ("attestation_semantic_sha256", "report_sha256")
    ):
        raise OperatorEnvelopeError("OPERATOR_ENVELOPE_READINESS_INVALID")
    review = _exact_object(
        value["author_review"],
        {"confirmation", "reviewed_at"},
        code="OPERATOR_ENVELOPE_AUTHOR_REVIEW_INVALID",
    )
    reviewed_at = _parse_timestamp(review["reviewed_at"])
    if (
        review["confirmation"] != AUTHOR_REVIEW_CONFIRMATION
        or reviewed_at < issued_at
        or reviewed_at > expires_at
    ):
        raise OperatorEnvelopeError("OPERATOR_ENVELOPE_AUTHOR_REVIEW_INVALID")
    return OperatorEnvelope(
        issued_at=issued_at,
        reviewed_at=reviewed_at,
        expires_at=expires_at,
        run_id=_canonical_uuid(
            value["run_id"], code="OPERATOR_ENVELOPE_RUN_INVALID"
        ),
        nonce=nonce,
        novel_id=_canonical_uuid(
            scope["novel_id"], code="OPERATOR_ENVELOPE_SCOPE_INVALID"
        ),
        document_id=_canonical_uuid(
            scope["document_id"], code="OPERATOR_ENVELOPE_SCOPE_INVALID"
        ),
        fixture_manifest_sha256=fixture["manifest_sha256"],  # type: ignore[arg-type]
        automatic_case_id=fixture["automatic_case_id"],  # type: ignore[arg-type]
        manual_case_id=fixture["manual_case_id"],  # type: ignore[arg-type]
        duration_minutes=float(duration),
        required_captures=captures,
        locks=tuple(locks),
        attestation_semantic_sha256=readiness[
            "attestation_semantic_sha256"
        ],  # type: ignore[arg-type]
        readiness_report_sha256=readiness["report_sha256"],  # type: ignore[arg-type]
        envelope_fingerprint_sha256=fingerprint,
    )


def verify_operator_envelope_binding(
    envelope: OperatorEnvelope,
    *,
    config: RunnerConfig,
    fixture: ChapterFixture,
    attestation: ReadinessAttestation,
    lock_paths: Mapping[str, Path],
    lock_grants: Mapping[str, str],
    lock_identity_sha256: Mapping[str, str],
    readiness_report: Mapping[str, object] | None,
    resume: bool,
) -> None:
    if (
        type(envelope) is not OperatorEnvelope
        or type(config) is not RunnerConfig
        or type(fixture) is not ChapterFixture
        or type(attestation) is not ReadinessAttestation
        or type(resume) is not bool
    ):
        raise OperatorEnvelopeError("OPERATOR_ENVELOPE_BINDING_INVALID")
    fixture_sha = fixture.manifest_sha256
    if (
        _SHA256_RE.fullmatch(fixture_sha) is None
        or envelope.run_id != config.run_id
        or envelope.novel_id != config.novel_id
        or envelope.document_id != config.document_id
        or envelope.fixture_manifest_sha256 != fixture_sha
        or envelope.automatic_case_id != config.automatic_case_id
        or envelope.manual_case_id != config.manual_case_id
        or fixture.automatic.case_id != config.automatic_case_id
        or fixture.manual.case_id != config.manual_case_id
        or envelope.duration_minutes != config.duration_minutes
        or envelope.required_captures != EXPECTED_CAPTURES
        or attestation.novel_id != config.novel_id
        or attestation.document_id != config.document_id
        or attestation.fixture_manifest_sha256 != fixture_sha
        or attestation.required_captures != EXPECTED_CAPTURES
        or attestation_semantic_sha256(attestation)
        != envelope.attestation_semantic_sha256
        or set(lock_paths) != set(EXPECTED_LOCK_NAMES)
        or set(lock_grants) != set(EXPECTED_LOCK_NAMES)
        or set(lock_identity_sha256) != set(EXPECTED_LOCK_NAMES)
    ):
        raise OperatorEnvelopeError("OPERATOR_ENVELOPE_BINDING_INVALID")
    attestation_locks = {item.name: item for item in attestation.resource_locks}
    envelope_locks = {item.name: item for item in envelope.locks}
    if set(attestation_locks) != set(EXPECTED_LOCK_NAMES):
        raise OperatorEnvelopeError("OPERATOR_ENVELOPE_BINDING_INVALID")
    for name in EXPECTED_LOCK_NAMES:
        attested = attestation_locks[name]
        expected = envelope_locks[name]
        try:
            same_path = attested.path.resolve(strict=True) == lock_paths[name].resolve(
                strict=True
            )
        except OSError as error:
            raise OperatorEnvelopeError("OPERATOR_LOCK_FILE_UNSAFE") from error
        if (
            not same_path
            or attested.grant != lock_grants[name]
            or expected.grant != lock_grants[name]
            or type(lock_identity_sha256[name]) is not str
            or _SHA256_RE.fullmatch(lock_identity_sha256[name]) is None
            or expected.identity_sha256 != lock_identity_sha256[name]
        ):
            raise OperatorEnvelopeError("OPERATOR_ENVELOPE_BINDING_INVALID")
    if resume:
        if readiness_report is not None:
            raise OperatorEnvelopeError("OPERATOR_ENVELOPE_BINDING_INVALID")
    elif (
        readiness_report is None
        or readiness_report.get("decision") != "READY_FOR_OPERATOR_REVIEW"
        or readiness_report_sha256(readiness_report)
        != envelope.readiness_report_sha256
    ):
        raise OperatorEnvelopeError("OPERATOR_READINESS_NOT_READY")


def _claim_path(envelope: OperatorEnvelope) -> Path:
    """Return the one fixed registry key for a run, independent of envelope path."""

    run_fingerprint = hashlib.sha256(
        str(envelope.run_id).encode("ascii")
    ).hexdigest()
    return CLAIM_REGISTRY_DIRECTORY / f"{run_fingerprint}.claim"


def _claim_timestamp(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if type(current) is not datetime or current.tzinfo is None:
        raise OperatorEnvelopeError("OPERATOR_ENVELOPE_TIME_INVALID")
    return current.astimezone(timezone.utc).replace(microsecond=0)


def _claim_payload(
    immutable: Mapping[str, object],
    *,
    state: str,
    updated_at: str,
    recovery_generation: int,
    latest_recovery_sha256: str | None,
) -> dict[str, object]:
    claim_identity = _sha256(dict(immutable))
    unsigned = {
        **dict(immutable),
        "state": state,
        "updated_at": updated_at,
        "recovery_generation": recovery_generation,
        "latest_recovery_sha256": latest_recovery_sha256,
        "claim_identity_sha256": claim_identity,
    }
    return {**unsigned, "self_sha256": _sha256(unsigned)}


def _load_claim(
    registry: _SecureDirectory,
    claim_name: str,
) -> tuple[dict[str, object], dict[str, object], RecoveryClaimBinding]:
    claim = _read_directory_json(
        registry,
        claim_name,
        "OPERATOR_ENVELOPE_CLAIM_INVALID",
        maximum_bytes=MAX_PRIVATE_JSON_BYTES,
    )
    expected = {
        "schema_version",
        "run_id",
        "envelope_fingerprint_sha256",
        "private_work_dir_canonical_sha256",
        "private_work_dir_identity_sha256",
        "claimed_at",
        "state",
        "updated_at",
        "recovery_generation",
        "latest_recovery_sha256",
        "claim_identity_sha256",
        "self_sha256",
    }
    if set(claim) != expected:
        raise OperatorEnvelopeError("OPERATOR_ENVELOPE_CLAIM_INVALID")
    supplied_self = claim["self_sha256"]
    if type(supplied_self) is not str or _SHA256_RE.fullmatch(supplied_self) is None:
        raise OperatorEnvelopeError("OPERATOR_ENVELOPE_CLAIM_INVALID")
    unsigned = dict(claim)
    del unsigned["self_sha256"]
    if _sha256(unsigned) != supplied_self:
        raise OperatorEnvelopeError("OPERATOR_ENVELOPE_CLAIM_INVALID")
    immutable = {
        key: claim[key]
        for key in (
            "schema_version",
            "run_id",
            "envelope_fingerprint_sha256",
            "private_work_dir_canonical_sha256",
            "private_work_dir_identity_sha256",
            "claimed_at",
        )
    }
    claim_identity = claim["claim_identity_sha256"]
    if (
        claim["schema_version"] != CLAIM_SCHEMA
        or _canonical_uuid(
            claim["run_id"],
            code="OPERATOR_ENVELOPE_CLAIM_INVALID",
        )
        is None
        or type(claim_identity) is not str
        or _SHA256_RE.fullmatch(claim_identity) is None
        or claim_identity != _sha256(immutable)
        or claim["state"]
        not in {
            "PREPARED",
            "BASELINE_SEALED",
            "TECHNICAL_COMPLETE",
            "RECOVERY_REQUIRED",
            "LISTENING_PENDING",
            "FINALIZATION_PENDING",
            "FINALIZED",
        }
        or type(claim["recovery_generation"]) is not int
        or claim["recovery_generation"] < 0
        or (
            claim["recovery_generation"] == 0
            and claim["latest_recovery_sha256"] is not None
        )
        or (
            claim["recovery_generation"] > 0
            and (
                type(claim["latest_recovery_sha256"]) is not str
                or _SHA256_RE.fullmatch(claim["latest_recovery_sha256"])
                is None
            )
        )
        or (
            claim["state"] == "PREPARED"
            and claim["recovery_generation"] != 0
        )
        or (
            claim["state"] != "PREPARED"
            and claim["recovery_generation"] == 0
        )
        or any(
            type(claim[key]) is not str
            or _SHA256_RE.fullmatch(claim[key]) is None
            for key in (
                "envelope_fingerprint_sha256",
                "private_work_dir_canonical_sha256",
                "private_work_dir_identity_sha256",
            )
        )
    ):
        raise OperatorEnvelopeError("OPERATOR_ENVELOPE_CLAIM_INVALID")
    claimed_at = _parse_timestamp(claim["claimed_at"])
    updated_at = _parse_timestamp(claim["updated_at"])
    if updated_at < claimed_at:
        raise OperatorEnvelopeError("OPERATOR_ENVELOPE_CLAIM_INVALID")
    binding = RecoveryClaimBinding(
        claim_identity_sha256=claim_identity,
        envelope_fingerprint_sha256=claim["envelope_fingerprint_sha256"],  # type: ignore[arg-type]
        private_work_dir_canonical_sha256=claim[
            "private_work_dir_canonical_sha256"
        ],  # type: ignore[arg-type]
        private_work_dir_identity_sha256=claim[
            "private_work_dir_identity_sha256"
        ],  # type: ignore[arg-type]
    )
    return claim, immutable, binding


def _claim_private_directory(
    path: Path,
    identity: tuple[int, ...],
) -> tuple[str, str, _RecoveryRecordHead | None]:
    if not isinstance(path, Path) or not path.is_absolute() or ".." in path.parts:
        raise OperatorEnvelopeError("OPERATOR_CLAIM_DIRECTORY_INVALID")
    try:
        if path.resolve(strict=True) != path:
            raise OperatorEnvelopeError("OPERATOR_CLAIM_DIRECTORY_INVALID")
        directory = _open_secure_directory(
            path,
            "OPERATOR_CLAIM_DIRECTORY_INVALID",
        )
    except RunnerError as error:
        raise OperatorEnvelopeError("OPERATOR_CLAIM_DIRECTORY_INVALID") from error
    try:
        if directory.opened_identity != identity:
            raise OperatorEnvelopeError("OPERATOR_CLAIM_DIRECTORY_INVALID")
        path_digest, identity_digest = recovery_private_directory_binding(
            path,
            identity,
        )
        recovery_exists = _entry_exists(
            directory,
            "recovery.json",
            "OPERATOR_CLAIM_DIRECTORY_INVALID",
        )
        recovery_head: _RecoveryRecordHead | None = None
        if recovery_exists:
            payload = _read_directory_json(
                directory,
                "recovery.json",
                "OPERATOR_CLAIM_DIRECTORY_INVALID",
                maximum_bytes=8 * 1024 * 1024,
            )
            required = {
                "state",
                "generation",
                "previous_record_sha256",
                "self_sha256",
            }
            if not required.issubset(payload):
                raise OperatorEnvelopeError(
                    "OPERATOR_CLAIM_RECOVERY_HEAD_INVALID"
                )
            unsigned = dict(payload)
            supplied_self = unsigned.pop("self_sha256")
            state_value = payload["state"]
            generation = payload["generation"]
            previous = payload["previous_record_sha256"]
            if (
                type(state_value) is not str
                or type(generation) is not int
                or generation < 1
                or type(supplied_self) is not str
                or _SHA256_RE.fullmatch(supplied_self) is None
                or _sha256(unsigned) != supplied_self
                or (
                    generation == 1
                    and previous is not None
                )
                or (
                    generation > 1
                    and (
                        type(previous) is not str
                        or _SHA256_RE.fullmatch(previous) is None
                    )
                )
            ):
                raise OperatorEnvelopeError(
                    "OPERATOR_CLAIM_RECOVERY_HEAD_INVALID"
                )
            recovery_head = _RecoveryRecordHead(
                state=state_value,
                generation=generation,
                previous_record_sha256=previous,
                record_sha256=_canonical_file_sha256(payload),
            )
        return path_digest, identity_digest, recovery_head
    finally:
        directory.close()


def _open_claim_lock(
    registry: _SecureDirectory,
    lock_name: str,
) -> int:
    if not _entry_exists(
        registry,
        lock_name,
        "OPERATOR_ENVELOPE_CLAIM_FILE_UNSAFE",
    ):
        try:
            _atomic_write(
                registry,
                lock_name,
                b"",
                "OPERATOR_ENVELOPE_CLAIM_FILE_UNSAFE",
                exclusive=True,
                exists_code="OPERATOR_ENVELOPE_CLAIM_LOCK_RACE",
            )
        except RunnerError as error:
            if error.code != "OPERATOR_ENVELOPE_CLAIM_LOCK_RACE":
                raise
    descriptor, opened = _open_named_file(
        registry,
        lock_name,
        "OPERATOR_ENVELOPE_CLAIM_FILE_UNSAFE",
    )
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        after = os.stat(
            lock_name,
            dir_fd=registry.descriptor,
            follow_symlinks=False,
        )
        if (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino):
            raise OperatorEnvelopeError("OPERATOR_ENVELOPE_CLAIM_FILE_UNSAFE")
        return descriptor
    except BlockingIOError as error:
        os.close(descriptor)
        raise OperatorEnvelopeError("OPERATOR_ENVELOPE_CLAIM_BUSY") from error
    except BaseException:
        os.close(descriptor)
        raise


def _open_or_create_claim_registry() -> _SecureDirectory:
    """Create missing registry components through pinned directory FDs."""

    path = CLAIM_REGISTRY_DIRECTORY
    code = "OPERATOR_ENVELOPE_CLAIM_REGISTRY_UNSAFE"
    repository = REPOSITORY_ROOT.resolve(strict=True)
    if (
        not path.is_absolute()
        or ".." in path.parts
        or path == repository
        or path.is_relative_to(repository)
    ):
        raise OperatorEnvelopeError(code)
    descriptor: int | None = None
    try:
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            raise OperatorEnvelopeError(code)
        descriptor = os.open(
            "/",
            os.O_RDONLY
            | os.O_DIRECTORY
            | getattr(os, "O_CLOEXEC", 0)
            | nofollow,
        )
        for component in path.parts[1:]:
            if not component or component in {".", ".."}:
                raise OperatorEnvelopeError(code)
            created = False
            try:
                metadata = os.stat(
                    component,
                    dir_fd=descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                os.mkdir(component, 0o700, dir_fd=descriptor)
                created = True
                metadata = os.stat(
                    component,
                    dir_fd=descriptor,
                    follow_symlinks=False,
                )
            if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(
                metadata.st_mode
            ):
                raise OperatorEnvelopeError(code)
            child = os.open(
                component,
                os.O_RDONLY
                | os.O_DIRECTORY
                | getattr(os, "O_CLOEXEC", 0)
                | nofollow,
                dir_fd=descriptor,
            )
            opened = os.fstat(child)
            if (opened.st_dev, opened.st_ino) != (
                metadata.st_dev,
                metadata.st_ino,
            ):
                os.close(child)
                raise OperatorEnvelopeError(code)
            if created:
                os.fchmod(child, 0o700)
                os.fsync(descriptor)
            os.close(descriptor)
            descriptor = child
        final = os.fstat(descriptor)
        if (
            final.st_uid != os.getuid()
            or stat.S_IMODE(final.st_mode) != 0o700
        ):
            raise OperatorEnvelopeError(code)
    except OperatorEnvelopeError:
        raise
    except OSError as error:
        raise OperatorEnvelopeError(code) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    try:
        return _open_secure_directory(path, code)
    except RunnerError as error:
        raise OperatorEnvelopeError(code) from error


def _claim_state_for_recovery(state_value: str) -> str:
    mapping = {
        "BASELINE_CAPTURED": "BASELINE_SEALED",
        "AUTOMATIC_COMPLETE": "BASELINE_SEALED",
        "MANUAL_COMPLETE": "BASELINE_SEALED",
        "TECHNICAL_COMPLETE": "TECHNICAL_COMPLETE",
        "RECOVERY_REQUIRED": "RECOVERY_REQUIRED",
        "LISTENING_PENDING": "LISTENING_PENDING",
        "FINALIZATION_PENDING": "FINALIZATION_PENDING",
    }
    try:
        return mapping[state_value]
    except KeyError as error:
        raise OperatorEnvelopeError(
            "OPERATOR_CLAIM_RECOVERY_HEAD_INVALID"
        ) from error


def _claim_transition_allowed(current: str, target: str) -> bool:
    allowed = {
        "PREPARED": {"PREPARED", "BASELINE_SEALED"},
        "BASELINE_SEALED": {
            "BASELINE_SEALED",
            "TECHNICAL_COMPLETE",
            "RECOVERY_REQUIRED",
            "FINALIZATION_PENDING",
        },
        "TECHNICAL_COMPLETE": {
            "TECHNICAL_COMPLETE",
            "RECOVERY_REQUIRED",
            "LISTENING_PENDING",
            "FINALIZATION_PENDING",
        },
        "RECOVERY_REQUIRED": {
            "RECOVERY_REQUIRED",
            "LISTENING_PENDING",
            "FINALIZATION_PENDING",
        },
        "LISTENING_PENDING": {
            "LISTENING_PENDING",
            "FINALIZATION_PENDING",
        },
        "FINALIZATION_PENDING": {"FINALIZATION_PENDING", "FINALIZED"},
        # Narrow publication rollback: if canonical evidence identity changes
        # during the FINALIZED callback, the validator retains recovery and
        # returns this claim to FINALIZATION_PENDING under the same flock.
        "FINALIZED": {"FINALIZED", "FINALIZATION_PENDING"},
    }
    return target in allowed.get(current, set())


@contextmanager
def claim_operator_envelope(
    envelope_path: Path,
    envelope: OperatorEnvelope,
    *,
    private_work_dir: Path,
    private_work_dir_identity: tuple[int, ...],
    resume: bool,
    now: datetime | None = None,
) -> Iterator[OperatorClaimLease]:
    current = _claim_timestamp(now)
    if not isinstance(envelope_path, Path) or not envelope_path.is_absolute():
        raise OperatorEnvelopeError("OPERATOR_ENVELOPE_FILE_UNSAFE")
    observed = load_operator_envelope(
        envelope_path,
        now=current,
        require_fresh=not resume,
    )
    if observed != envelope:
        raise OperatorEnvelopeError("OPERATOR_ENVELOPE_CLAIM_INVALID")
    claim_path = _claim_path(envelope)
    path_digest, identity_digest, recovery_head = _claim_private_directory(
        private_work_dir,
        private_work_dir_identity,
    )
    registry = _open_or_create_claim_registry()
    lock_descriptor: int | None = None
    try:
        run_fingerprint = claim_path.stem
        claim_name = claim_path.name
        lock_name = f"{run_fingerprint}.lock"
        lock_descriptor = _open_claim_lock(registry, lock_name)
        immutable = {
            "schema_version": CLAIM_SCHEMA,
            "run_id": str(envelope.run_id),
            "envelope_fingerprint_sha256": (
                envelope.envelope_fingerprint_sha256
            ),
            "private_work_dir_canonical_sha256": path_digest,
            "private_work_dir_identity_sha256": identity_digest,
            "claimed_at": _canonical_timestamp(current),
        }
        if _entry_exists(
            registry,
            claim_name,
            "OPERATOR_ENVELOPE_CLAIM_FILE_UNSAFE",
        ):
            claim, stored_immutable, binding = _load_claim(
                registry,
                claim_name,
            )
            expected_immutable = dict(stored_immutable)
            if (
                expected_immutable["schema_version"] != CLAIM_SCHEMA
                or expected_immutable["run_id"] != str(envelope.run_id)
                or expected_immutable["envelope_fingerprint_sha256"]
                != envelope.envelope_fingerprint_sha256
                or expected_immutable["private_work_dir_canonical_sha256"]
                != path_digest
                or expected_immutable["private_work_dir_identity_sha256"]
                != identity_digest
            ):
                raise OperatorEnvelopeError("OPERATOR_ENVELOPE_CLAIM_INVALID")
            state_value = claim["state"]
            assert isinstance(state_value, str)
            if resume:
                if state_value == "FINALIZED" and recovery_head is None:
                    raise OperatorEnvelopeError(
                        "OPERATOR_ENVELOPE_ALREADY_RECOVERED"
                    )
                if state_value == "PREPARED" and recovery_head is None:
                    raise OperatorEnvelopeError(
                        "OPERATOR_ENVELOPE_RESUME_CLAIM_REQUIRED"
                    )
            elif not (state_value == "PREPARED" and recovery_head is None):
                raise OperatorEnvelopeError("OPERATOR_ENVELOPE_ALREADY_CLAIMED")
            immutable = expected_immutable
        else:
            if resume:
                raise OperatorEnvelopeError(
                    "OPERATOR_ENVELOPE_RESUME_CLAIM_REQUIRED"
                )
            if recovery_head is not None:
                raise OperatorEnvelopeError(
                    "OPERATOR_ENVELOPE_ALREADY_CLAIMED"
                )
            if current > envelope.expires_at:
                raise OperatorEnvelopeError("OPERATOR_ENVELOPE_EXPIRED")
            payload = _claim_payload(
                immutable,
                state="PREPARED",
                updated_at=_canonical_timestamp(current),
                recovery_generation=0,
                latest_recovery_sha256=None,
            )
            _atomic_create_json(
                registry,
                claim_name,
                payload,
                code="OPERATOR_ENVELOPE_CLAIM_FILE_UNSAFE",
                exists_code="OPERATOR_ENVELOPE_ALREADY_CLAIMED",
            )
            claim, immutable, binding = _load_claim(registry, claim_name)
            state_value = "PREPARED"
        lease = OperatorClaimLease(
            registry=registry,
            claim_name=claim_name,
            lock_descriptor=lock_descriptor,
            binding=binding,
            state=state_value,
            recovery_generation=claim["recovery_generation"],  # type: ignore[arg-type]
            latest_recovery_sha256=claim["latest_recovery_sha256"],  # type: ignore[arg-type]
            immutable=immutable,
        )
        if resume:
            assert recovery_head is not None
            expected_state = _claim_state_for_recovery(recovery_head.state)
            exact_head = (
                recovery_head.generation == lease.recovery_generation
                and recovery_head.record_sha256
                == lease.latest_recovery_sha256
            )
            one_ahead = (
                recovery_head.generation == lease.recovery_generation + 1
                and recovery_head.previous_record_sha256
                == lease.latest_recovery_sha256
            )
            state_compatible = lease.state == expected_state or (
                lease.state == "FINALIZED"
                and expected_state == "FINALIZATION_PENDING"
            )
            if exact_head:
                if not state_compatible:
                    raise OperatorEnvelopeError(
                        "OPERATOR_CLAIM_RECOVERY_HEAD_INVALID"
                    )
            elif one_ahead:
                # Do not persist this head yet.  The validator first verifies
                # the complete recovery schema, run/scope/fixture and claim
                # binding, then advances the claim through this held lease.
                if not _claim_transition_allowed(lease.state, expected_state):
                    raise OperatorEnvelopeError(
                        "OPERATOR_CLAIM_RECOVERY_HEAD_INVALID"
                    )
            else:
                raise OperatorEnvelopeError(
                    "OPERATOR_CLAIM_RECOVERY_HEAD_INVALID"
                )
        yield lease
        registry.assert_stable()
        path_after = os.stat(
            lock_name,
            dir_fd=registry.descriptor,
            follow_symlinks=False,
        )
        opened_after = os.fstat(lock_descriptor)
        if (path_after.st_dev, path_after.st_ino) != (
            opened_after.st_dev,
            opened_after.st_ino,
        ):
            raise OperatorEnvelopeError("OPERATOR_ENVELOPE_CLAIM_FILE_UNSAFE")
    finally:
        if lock_descriptor is not None:
            try:
                fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
            finally:
                os.close(lock_descriptor)
        registry.close()


def build_parser() -> argparse.ArgumentParser:
    parser = _SafeParser(description=__doc__, add_help=False)
    parser.add_argument("--mode", choices=("issue",), required=True)
    parser.add_argument("--attestation-file", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-file", type=Path, required=True)
    parser.add_argument("--confirm-author-review", required=True)
    return parser


def _safe_console(status_value: str, code: str) -> None:
    sys.stdout.write(
        json.dumps(
            {
                "schema_version": ENVELOPE_SCHEMA,
                "status": status_value,
                "code": code,
                "release_gate_passed": False,
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    reader: object | None = None,
    now: Callable[[], datetime] | None = None,
    nonce_factory: Callable[[], str] | None = None,
) -> int:
    try:
        args = build_parser().parse_args(argv)
        run_id = _canonical_uuid(args.run_id, code="OPERATOR_ENVELOPE_RUN_INVALID")
        attestation = load_private_attestation(args.attestation_file)
        authority_reader = reader
        if authority_reader is None:
            authority_reader = SqlAlchemyReadinessReader(
                sessionmaker(bind=get_engine(), expire_on_commit=False),
                storage=_storage_from_environment(),
            )
        current_factory = now or (lambda: datetime.now(timezone.utc))
        random_factory = nonce_factory or (lambda: secrets.token_urlsafe(32))
        issue_operator_envelope(
            attestation=attestation,
            reader=authority_reader,
            run_id=run_id,
            output_file=args.output_file,
            confirmation=args.confirm_author_review,
            now=current_factory(),
            nonce=random_factory(),
        )
        _safe_console("ISSUED", "READY_FOR_FIXED_LAUNCHER")
        return 0
    except (OperatorEnvelopeError, ReadinessError) as error:
        code = (
            error.code
            if isinstance(error, (OperatorEnvelopeError, ReadinessError))
            else "OPERATOR_ENVELOPE_FAILED"
        )
        _safe_console("HOLD", code)
        return 2
    except BaseException:
        _safe_console("HOLD", "OPERATOR_ENVELOPE_INTERNAL_ERROR")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AUTHOR_REVIEW_CONFIRMATION",
    "CLAIM_SCHEMA",
    "ENVELOPE_SCHEMA",
    "FORMAL_DURATION_MINUTES",
    "OperatorEnvelope",
    "OperatorEnvelopeError",
    "OperatorClaimLease",
    "OperatorLockBinding",
    "attestation_semantic_sha256",
    "claim_operator_envelope",
    "issue_operator_envelope",
    "load_operator_envelope",
    "main",
    "private_lock_identity_sha256",
    "private_lock_identity_from_stat",
    "readiness_report_sha256",
    "verify_operator_envelope_binding",
]
