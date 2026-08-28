#!/usr/bin/env python3
"""Fixed T4-K browser/Sidecar collector protocol and report finalizer.

The actual browser controller owns browser interaction.  This module owns the
much narrower trust boundary after collection: it accepts only the fixed public
PawApp page, the four frozen desktop captures, digest-only observations and the
same private ``probe-request.json`` created by the real chapter runner.

Two private, non-overwriting files are emitted for a real fixed-controller
observation:

* ``collector-report.json`` contains the auditable screenshot, console,
  network, Range/ETag, interaction, editor-write and Sidecar digest summaries;
* ``probe-report.json`` is the exact v2 projection consumed by
  :mod:`scripts.tts.chapter_e2e_probes`.

The collector report binds the SHA-256 of the exact probe-report bytes.  The
pair is published under one private advisory lock and is formal only after a
separately fsynced commit marker binds both exact file identities.  Complete
identical retries are idempotent; foreign or ambiguous residue is never
overwritten or removed.  An explicit synthetic observation can validate the
protocol in unit tests, but is unconditionally forbidden from writing formal
artifacts.

No raw scope identifier, chapter text, audio, screenshot, log, URL token,
filesystem path or database/model detail is accepted by the evidence schema.
Stable exceptions never include private values.

The current product threat model is personal, single-user and local.  A fixed
Node/Playwright controller may therefore publish a local operator observation
without a cryptographic signing authority.  Its report is still bound to the
exact request, scope, Editions, output hashes, four observed desktop captures
and the thirty-minute runtime window.  The older SSHSIG path remains available
only as a non-blocking experimental candidate and is not required by the local
acceptance path.  The HTTP validation bearer is never a report-signing key.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import errno
import fcntl
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import sys
from typing import Final, Iterator, Mapping, Sequence


CURRENT_PAWAPP_ROOT: Final = Path(__file__).resolve().parents[2]
if str(CURRENT_PAWAPP_ROOT) not in sys.path:
    sys.path.insert(0, str(CURRENT_PAWAPP_ROOT))

from scripts.tts.chapter_e2e_probe_request import (
    PROBE_REQUEST_FILENAME,
    PROBE_REPORT_FILENAME,
    PROBE_REQUEST_SCHEMA_VERSION,
)
from scripts.tts.chapter_e2e_probes import (
    ALLOWED_ASSISTANT_MODES,
    BoundTechnicalProbe,
    EXPECTED_RANGE_STATUS_CODES,
    EXPECTED_SIDECAR_CONTAINER_NAME,
    PROBE_SCHEMA_VERSION,
    ProbeExpectation,
    ProbeReportError,
    StrictJsonChapterE2EProbeLoader,
)
from scripts.tts.chapter_e2e_controller_trust import (
    CONTROLLER_ID as ASYMMETRIC_CONTROLLER_ID,
    CONTROLLER_REPORT_BINDING_SCHEMA_VERSION,
    CONTROLLER_REPORT_BINDING_MISMATCH_ERROR,
    CONTROLLER_PREFLIGHT_BINDING_MISMATCH_ERROR,
    CONTROLLER_TRUST_ROOT_HOLD_ERROR,
    FIXED_REQUIRED_STABILITY_MILLISECONDS,
    REPORT_SIGNATURE_NAMESPACE,
    ControllerTrustError,
    FixedControllerTrustVerifier,
    ObservedCaptureBinding,
    PreflightExpectation,
    ReportExpectation,
    VerifiedControllerPreflight,
    VerifiedControllerReportBinding,
    canonical_json_bytes as _canonical_controller_json,
)
from scripts.tts.chapter_e2e_metric_chain import (
    build_metric_sample_chain_sha256,
)
from scripts.tts.validate_chapter_e2e import ALLOWED_VIEWPORTS, REPOSITORY_ROOT


LEGACY_COLLECTOR_SCHEMA_VERSION: Final = (
    "moss-tts-chapter-e2e-collector/1.2"
)
COLLECTOR_SCHEMA_VERSION: Final = "moss-tts-chapter-e2e-collector/2.1"
LOCAL_OPERATOR_COLLECTOR_SCHEMA_VERSION: Final = (
    "moss-tts-chapter-e2e-local-operator/1.2"
)
COLLECTOR_REPORT_FILENAME: Final = "collector-report.json"
LEGACY_COLLECTOR_COMMIT_SCHEMA_VERSION: Final = (
    "moss-tts-chapter-e2e-collector-commit/1.0"
)
COLLECTOR_COMMIT_SCHEMA_VERSION: Final = (
    "moss-tts-chapter-e2e-collector-commit/2.0"
)
LOCAL_OPERATOR_COMMIT_SCHEMA_VERSION: Final = (
    "moss-tts-chapter-e2e-local-operator-commit/1.0"
)
COLLECTOR_COMMIT_MARKER_FILENAME: Final = "collector-report.commit.json"
CONTROLLER_PREFLIGHT_FILENAME: Final = "controller-preflight.json"
CONTROLLER_PREFLIGHT_SIGNATURE_FILENAME: Final = (
    "controller-preflight.sshsig"
)
CONTROLLER_ATTESTATION_CAPABILITY_FILENAME: Final = (
    "controller-attestation.capability"
)
PROBE_COLLECTOR_INCOMPLETE_ERROR: Final = "PROBE_COLLECTOR_INCOMPLETE"
PROBE_COLLECTOR_BUSY_ERROR: Final = "PROBE_COLLECTOR_BUSY"
PROBE_CONTROLLER_AUTHORITY_HOLD_ERROR: Final = (
    "PROBE_CONTROLLER_AUTHORITY_HOLD"
)
PROBE_CONTROLLER_ATTESTATION_REQUIRED_ERROR: Final = (
    PROBE_CONTROLLER_AUTHORITY_HOLD_ERROR
)
COLLECTOR_TRANSACTION_BUSY_ERROR: Final = "COLLECTOR_TRANSACTION_BUSY"
COLLECTOR_CONTROLLER_AUTHORITY_HOLD_ERROR: Final = (
    "COLLECTOR_CONTROLLER_AUTHORITY_HOLD"
)
FIXED_CONTROLLER_ID: Final = ASYMMETRIC_CONTROLLER_ID
FIXED_PUBLIC_PAGE_URL: Final = (
    "http://127.0.0.1:18088/chat"
)
FIXED_REQUIRED_STABILITY_SECONDS: Final = 30.0 * 60.0
FIXED_MIN_METRIC_SAMPLE_COUNT: Final = 31
FIXED_MAX_METRIC_SAMPLE_GAP_SECONDS: Final = 65.0
MEMORY_TREND_WINDOW_SIZE: Final = 5
MEMORY_GROWTH_MIN_LIMIT_BYTES: Final = 128 * 1024 * 1024
MEMORY_GROWTH_PERCENT_NUMERATOR: Final = 5
MEMORY_GROWTH_PERCENT_DENOMINATOR: Final = 100
MAX_PRIVATE_JSON_BYTES: Final = 128 * 1024
MAX_REQUEST_AGE_SECONDS: Final = 60 * 60
MAX_REPORT_AGE_SECONDS: Final = 15 * 60
MAX_FUTURE_SKEW_SECONDS: Final = 30
_SHA256_LENGTH: Final = 64
_VALIDATION_TOKEN_RE: Final = re.compile(r"^[A-Za-z0-9_-]{43,128}$")
_ATTESTATION_DOMAIN: Final = b"moss-tts-t4k-fixed-collector/1\0"
_COMMIT_ATTESTATION_DOMAIN: Final = b"moss-tts-t4k-collector-commit/1\0"
_TRANSACTION_LOCK_FILENAME: Final = ".collector-report.lock"
_STAGE_SUFFIX: Final = ".stage"
_TRANSACTION_NOT_STARTED_ERROR: Final = "COLLECTOR_TRANSACTION_NOT_STARTED"


class CollectorError(RuntimeError):
    """Fail-closed collector error carrying only a stable public code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ControllerAttestationCapability:
    """Compatibility-only placeholder; it conveys no formal authority.

    A same-uid readable secret is not a controller provenance boundary.  No
    instance can be provisioned by this module until a separately approved,
    non-forgeable controller port exists.
    """

    __slots__ = ()

    def __new__(cls) -> ControllerAttestationCapability:
        raise TypeError("controller authority unavailable")


@dataclass(frozen=True, slots=True)
class CollectorRequest:
    """Validated digest-only authority from one private probe request."""

    created_at: datetime
    request_sha256: str
    request_fingerprint_sha256: str
    preflight_payload_sha256: str
    expectation: ProbeExpectation
    performance_seed: PerformanceSeed


@dataclass(frozen=True, slots=True)
class PerformanceSeed:
    """Executor-measured, digest-safe chapter performance authority."""

    request_to_ready_seconds: tuple[float, float]
    observed_http_first_audio_ms: tuple[int, int]
    chapter_audio_duration_seconds: float


@dataclass(frozen=True, slots=True)
class _VerifiedRequestPreflight:
    verified: VerifiedControllerPreflight
    payload_identity: tuple[int, ...]
    signature_identity: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class CaptureDigest:
    """Digest-only observation for one exact viewport/assistant combination."""

    width: int
    height: int
    assistant_mode: str
    observed_inner_width: int
    observed_inner_height: int
    device_pixel_ratio: float
    screenshot_pixel_width: int
    screenshot_pixel_height: int
    calibration_summary_sha256: str
    screenshot_sha256: str
    screenshot_bytes: int
    console_summary_sha256: str
    network_summary_sha256: str
    network_request_count: int
    console_error_count: int
    overlap_count: int


@dataclass(frozen=True, slots=True)
class BrowserCollectorEvidence:
    """Fixed browser observations without logs, bodies or screenshots."""

    observer_report_sha256: str
    captures: tuple[CaptureDigest, ...]
    range_status_codes: tuple[int, ...]
    range_summary_sha256: str
    etag_summary_sha256: str
    etag_observed: bool
    if_none_match_304_observed: bool
    if_range_206_observed: bool
    unsatisfied_range_416_observed: bool
    time_to_first_audio_ms: int
    seam_pairs_checked: int
    seek_latest_wins: bool
    pending_gap_not_skipped: bool
    interaction_summary_sha256: str
    edit_actions_observed: int
    edit_actions_created_tts_writes: int
    editor_summary_sha256: str


@dataclass(frozen=True, slots=True)
class SidecarMetricSampleDigest:
    """One timestamped digest in the ordered Sidecar metric sample chain."""

    observed_at: datetime
    sample_sha256: str
    # ``None`` exists only so legacy/HOLD chain comparisons remain readable.
    # Formal evidence rejects it and requires every sample to carry the
    # controller-observed resident-memory scalar.
    resident_memory_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class SidecarCollectorEvidence:
    """Digest-only, request-bound Sidecar stability window evidence."""

    sidecar_container_name: str
    window_started_at: datetime
    window_ended_at: datetime
    request_fingerprint_sha256: str
    stability_elapsed_seconds: float
    chapter_audio_duration_seconds: float
    request_to_ready_seconds: float
    peak_memory_bytes: int
    host_paging_observed: bool
    pageout_delta: int
    swapout_delta: int
    memory_baseline_median_bytes: int
    memory_tail_median_bytes: int
    memory_growth_bytes: int
    memory_growth_limit_bytes: int
    sidecar_memory_growth_observed: bool
    qwenpaw_slowdown_observed: bool
    sidecar_restart_count: int
    health_failure_count: int
    metric_sample_count: int
    metric_samples: tuple[SidecarMetricSampleDigest, ...]
    metric_sample_chain_sha256: str
    metrics_summary_sha256: str


@dataclass(frozen=True, slots=True)
class FixedControllerEvidence:
    """One observation returned by the approved fixed controller boundary."""

    controller_id: str
    page_url: str
    request_fingerprint_sha256: str
    collected_at: datetime
    synthetic: bool
    browser: BrowserCollectorEvidence
    runtime: SidecarCollectorEvidence


@dataclass(frozen=True, slots=True)
class SyntheticProtocolResult:
    """Redacted proof that a fake exercised only the protocol validator."""

    status: str
    formal_validation_eligible: bool


@dataclass(frozen=True, slots=True)
class CollectorResult:
    """Digest-only result; private paths are intentionally not returned."""

    status: str
    collector_report_sha256: str
    probe_report_sha256: str


@dataclass(frozen=True, slots=True)
class ControllerReportPreparation:
    """Digest-only input for the host controller's fixed signing ceremony.

    ``collector_report_sha256`` is deliberately the SHA-256 of the canonical
    unsigned collector core, before ``controller_report_binding`` and its
    SSHSIG are attached.  It is not the final collector-report file hash; the
    v2 commit marker alone binds that final file hash and physical identity.
    """

    expectation: ReportExpectation


@dataclass(frozen=True, slots=True)
class ControllerReportSigningContext:
    """Public metadata used to construct the one canonical SSHSIG payload."""

    signed_at: datetime
    controller_build_sha256: str
    browser_binary_sha256: str
    signing_key_id: str
    signer_principal: str
    trust_policy_sha256: str
    allowed_signers_sha256: str
    observed_captures: tuple[ObservedCaptureBinding, ...]


class _DuplicateJsonKey(ValueError):
    pass


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise CollectorError("COLLECTOR_JSON_INVALID") from None


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _evidence_root_sha256(
    *,
    collector_raw: bytes,
    probe_raw: bytes,
    marker_raw: bytes,
) -> str:
    """Hash the exact committed triple with explicit file-role labels."""

    return _sha256_bytes(
        _canonical_json(
            {
                "collector_report_sha256": _sha256_bytes(collector_raw),
                "probe_report_sha256": _sha256_bytes(probe_raw),
                "commit_marker_sha256": _sha256_bytes(marker_raw),
            }
        )
    )


def _validate_validation_token(validation_token: object) -> None:
    if (
        type(validation_token) is not str
        or _VALIDATION_TOKEN_RE.fullmatch(validation_token) is None
    ):
        raise ValueError


def _validate_controller_capability(
    capability: object,
) -> ControllerAttestationCapability:
    if type(capability) is not ControllerAttestationCapability:
        raise ValueError
    return capability


def _collector_attestation_hmac(key: bytes, payload: object) -> str:
    return hmac.new(
        key,
        _ATTESTATION_DOMAIN + _canonical_json(payload),
        hashlib.sha256,
    ).hexdigest()


def _commit_attestation_hmac(key: bytes, payload: object) -> str:
    return hmac.new(
        key,
        _COMMIT_ATTESTATION_DOMAIN + _canonical_json(payload),
        hashlib.sha256,
    ).hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == _SHA256_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def _require_sha256(value: object, *, code: str) -> str:
    if not _is_sha256(value):
        raise CollectorError(code)
    return value


def _exact_mapping(
    value: object,
    keys: frozenset[str],
    *,
    code: str,
) -> Mapping[str, object]:
    if type(value) is not dict or frozenset(value) != keys:
        raise CollectorError(code)
    return value


def _canonical_timestamp(value: datetime, *, code: str) -> str:
    if type(value) is not datetime or value.tzinfo is None:
        raise CollectorError(code)
    normalized = value.astimezone(timezone.utc)
    if normalized.microsecond != 0:
        raise CollectorError(code)
    return normalized.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_timestamp(value: object, *, code: str) -> datetime:
    if type(value) is not str or len(value) != 20:
        raise CollectorError(code)
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        raise CollectorError(code) from None
    if _canonical_timestamp(parsed, code=code) != value:
        raise CollectorError(code)
    return parsed


def build_sidecar_metric_sample_chain_sha256(
    *,
    request_fingerprint_sha256: str,
    window_started_at: datetime,
    window_ended_at: datetime,
    metrics_summary_sha256: str,
    samples: Sequence[SidecarMetricSampleDigest],
) -> str:
    """Return the canonical request/window-bound digest chain for samples.

    The external fixed controller may use this narrow helper when assembling
    digest-only evidence.  The finalizer independently recomputes the same
    value and never treats a caller-provided elapsed scalar or terminal digest
    as sufficient proof of the 30-minute window.
    """

    code = "COLLECTOR_RUNTIME_GATE_FAILED"
    if (
        not _is_sha256(request_fingerprint_sha256)
        or not _is_sha256(metrics_summary_sha256)
        or isinstance(samples, (str, bytes, bytearray))
    ):
        raise CollectorError(code)
    items = tuple(samples)
    if len(items) < FIXED_MIN_METRIC_SAMPLE_COUNT:
        raise CollectorError(code)
    started_at = _canonical_timestamp(window_started_at, code=code)
    ended_at = _canonical_timestamp(window_ended_at, code=code)
    previous_observed: datetime | None = None
    serialized_samples: list[dict[str, object]] = []
    for index, sample in enumerate(items):
        if type(sample) is not SidecarMetricSampleDigest:
            raise CollectorError(code)
        observed_at = _canonical_timestamp(sample.observed_at, code=code)
        observed = _parse_timestamp(observed_at, code=code)
        if (
            not _is_sha256(sample.sample_sha256)
            or (
                sample.resident_memory_bytes is not None
                and (
                    type(sample.resident_memory_bytes) is not int
                    or sample.resident_memory_bytes < 0
                )
            )
            or (previous_observed is not None and observed <= previous_observed)
            or (
                previous_observed is not None
                and (observed - previous_observed).total_seconds()
                > FIXED_MAX_METRIC_SAMPLE_GAP_SECONDS
            )
        ):
            raise CollectorError(code)
        previous_observed = observed
        serialized_samples.append(
            {
                "index": index,
                "observed_at": observed_at,
                "sample_sha256": sample.sample_sha256,
            }
        )
    if (
        serialized_samples[0]["observed_at"] != started_at
        or serialized_samples[-1]["observed_at"] != ended_at
    ):
        raise CollectorError(code)
    seed: dict[str, object] = {
        "request_fingerprint_sha256": request_fingerprint_sha256,
        "window_started_at": started_at,
        "window_ended_at": ended_at,
        "metric_sample_count": len(serialized_samples),
        "metrics_summary_sha256": metrics_summary_sha256,
    }
    return build_metric_sample_chain_sha256(
        request_fingerprint_sha256=str(seed["request_fingerprint_sha256"]),
        window_started_at=str(seed["window_started_at"]),
        window_ended_at=str(seed["window_ended_at"]),
        metrics_summary_sha256=str(seed["metrics_summary_sha256"]),
        samples=serialized_samples,
    )


def _reject_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey
        result[key] = value
    return result


def _reject_nonfinite_json(_: str) -> object:
    raise ValueError


def _protected_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    for candidate in (REPOSITORY_ROOT, CURRENT_PAWAPP_ROOT):
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            raise CollectorError("COLLECTOR_PATH_UNSAFE") from None
        if resolved not in roots:
            roots.append(resolved)
    return tuple(roots)


def _reject_symlink_components(path: Path) -> None:
    if not path.is_absolute() or ".." in path.parts:
        raise CollectorError("COLLECTOR_PATH_UNSAFE")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            metadata = current.lstat()
        except OSError:
            raise CollectorError("COLLECTOR_FILE_UNSAFE") from None
        if stat.S_ISLNK(metadata.st_mode):
            raise CollectorError("COLLECTOR_PATH_UNSAFE")


def _same_object(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _directory_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
    )


def _secure_parent(metadata: os.stat_result) -> bool:
    return (
        stat.S_ISDIR(metadata.st_mode)
        and not stat.S_ISLNK(metadata.st_mode)
        and stat.S_IMODE(metadata.st_mode) == 0o700
        and metadata.st_uid == os.getuid()
    )


def _secure_file(metadata: os.stat_result, *, require_bytes: bool) -> bool:
    size_valid = (
        0 < metadata.st_size <= MAX_PRIVATE_JSON_BYTES
        if require_bytes
        else metadata.st_size <= MAX_PRIVATE_JSON_BYTES
    )
    return (
        stat.S_ISREG(metadata.st_mode)
        and not stat.S_ISLNK(metadata.st_mode)
        and metadata.st_nlink == 1
        and stat.S_IMODE(metadata.st_mode) == 0o600
        and metadata.st_uid == os.getuid()
        and size_valid
    )


def _file_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _resolve_private_parent(
    path: Path,
    *,
    allow_missing_leaf: bool = False,
) -> tuple[Path, os.stat_result]:
    _reject_symlink_components(path.parent if allow_missing_leaf else path)
    try:
        supplied = path.parent.lstat()
        resolved = path.parent.resolve(strict=True)
        resolved_metadata = resolved.lstat()
    except OSError:
        raise CollectorError("COLLECTOR_FILE_UNSAFE") from None
    if any(
        resolved == root or resolved.is_relative_to(root)
        for root in _protected_roots()
    ):
        raise CollectorError("COLLECTOR_PATH_UNSAFE")
    if (
        not _same_object(supplied, resolved_metadata)
        or not _secure_parent(supplied)
        or not _secure_parent(resolved_metadata)
    ):
        raise CollectorError("COLLECTOR_FILE_UNSAFE")
    return resolved, resolved_metadata


def _read_private_json(
    path: Path,
    *,
    expected_filename: str,
    name_error_code: str,
    json_error_code: str,
) -> tuple[
    bytes,
    Mapping[str, object],
    Path,
    tuple[int, ...],
    tuple[int, ...],
]:
    try:
        candidate = Path(path)
    except (TypeError, ValueError, OSError):
        raise CollectorError("COLLECTOR_PATH_UNSAFE") from None
    if candidate.name != expected_filename:
        raise CollectorError(name_error_code)
    resolved_parent, parent_before = _resolve_private_parent(candidate)
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise CollectorError("COLLECTOR_FILE_UNSAFE")
    parent_fd: int | None = None
    file_fd: int | None = None
    try:
        parent_fd = os.open(
            resolved_parent,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | nofollow,
        )
        opened_parent = os.fstat(parent_fd)
        if (
            not _same_object(opened_parent, parent_before)
            or not _secure_parent(opened_parent)
        ):
            raise CollectorError("COLLECTOR_FILE_UNSAFE")
        before = os.stat(
            candidate.name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        if not _secure_file(before, require_bytes=True):
            raise CollectorError("COLLECTOR_FILE_UNSAFE")
        file_fd = os.open(
            candidate.name,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | nofollow,
            dir_fd=parent_fd,
        )
        opened = os.fstat(file_fd)
        if (
            _file_identity(opened) != _file_identity(before)
            or not _secure_file(opened, require_bytes=True)
        ):
            raise CollectorError("COLLECTOR_FILE_UNSAFE")
        chunks: list[bytes] = []
        remaining = opened.st_size
        while remaining:
            chunk = os.read(file_fd, min(remaining, 64 * 1024))
            if not chunk:
                raise CollectorError("COLLECTOR_FILE_UNSAFE")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(file_fd, 1):
            raise CollectorError("COLLECTOR_FILE_UNSAFE")
        after = os.fstat(file_fd)
        path_after = os.stat(
            candidate.name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        parent_after = os.fstat(parent_fd)
        supplied_parent_after = candidate.parent.lstat()
        resolved_parent_after = resolved_parent.lstat()
        _reject_symlink_components(candidate)
        if (
            _file_identity(after) != _file_identity(opened)
            or _file_identity(path_after) != _file_identity(opened)
            or not _secure_file(after, require_bytes=True)
            or not _secure_file(path_after, require_bytes=True)
            or not _same_object(parent_after, opened_parent)
            or not _same_object(supplied_parent_after, opened_parent)
            or not _same_object(resolved_parent_after, opened_parent)
            or not _secure_parent(parent_after)
            or not _secure_parent(supplied_parent_after)
            or not _secure_parent(resolved_parent_after)
        ):
            raise CollectorError("COLLECTOR_FILE_UNSAFE")
        raw = b"".join(chunks)
    except CollectorError:
        raise
    except OSError:
        raise CollectorError("COLLECTOR_FILE_UNSAFE") from None
    finally:
        if file_fd is not None:
            try:
                os.close(file_fd)
            except OSError:
                pass
        if parent_fd is not None:
            try:
                os.close(parent_fd)
            except OSError:
                pass
    value = _decode_json_mapping(raw, code=json_error_code)
    return (
        raw,
        value,
        resolved_parent,
        _directory_identity(opened_parent),
        _file_identity(opened),
    )


def _decode_json_mapping(raw: bytes, *, code: str) -> Mapping[str, object]:
    try:
        decoded = raw.decode("utf-8", errors="strict")
        value = json.loads(
            decoded,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_json,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise CollectorError(code) from None
    if type(value) is not dict:
        raise CollectorError(code)
    return value


def load_controller_attestation_capability(
    private_work_dir: Path,
) -> ControllerAttestationCapability:
    """Compatibility port that is intentionally disabled fail-closed.

    Reading a secret from a same-uid file would put that signing authority in
    the ordinary launcher/validator process and let the same caller self-sign
    arbitrary ``synthetic=False`` evidence.  A future implementation must use
    an independently trusted controller port or asymmetric verification key;
    the fixed directory argument is retained only to avoid inventing a new
    launcher interface while that architecture remains on HOLD.
    """

    del private_work_dir
    require_formal_controller_authority()
    raise AssertionError("unreachable")


def require_formal_controller_authority() -> None:
    """Require the independently trusted authority that is not yet present.

    This frozen, zero-argument gate deliberately performs no filesystem, lock,
    network, validation-token or capability operation.  Its implementation may
    change only after approval and implementation of either an OS-isolated
    controller signing port or an asymmetric public trust root whose signing
    secret is unavailable to ordinary collector/validator processes.  A
    same-uid secret file, bearer token, or caller-supplied evidence can never
    satisfy this authority boundary.
    """

    raise ProbeReportError(PROBE_CONTROLLER_AUTHORITY_HOLD_ERROR)


def _load_request(
    path: Path,
    *,
    now: datetime,
) -> tuple[CollectorRequest, Path, tuple[int, ...]]:
    raw, payload, parent, parent_identity, _request_identity = (
        _read_private_json(
            path,
            expected_filename=PROBE_REQUEST_FILENAME,
            name_error_code="COLLECTOR_REQUEST_NAME_INVALID",
            json_error_code="COLLECTOR_REQUEST_INVALID",
        )
    )
    request = _exact_mapping(
        payload,
        frozenset(
            {
                "schema_version",
                "report_schema_version",
                "created_at",
                "controller_preflight_payload_sha256",
                "binding_seed",
                "performance_seed",
                "required_captures",
                "runtime_contract",
                "request_fingerprint_sha256",
            }
        ),
        code="COLLECTOR_REQUEST_INVALID",
    )
    if (
        request["schema_version"] != PROBE_REQUEST_SCHEMA_VERSION
        or request["report_schema_version"] != PROBE_SCHEMA_VERSION
    ):
        raise CollectorError("COLLECTOR_REQUEST_SCHEMA_INVALID")
    preflight_payload_sha256 = _require_sha256(
        request["controller_preflight_payload_sha256"],
        code="COLLECTOR_CONTROLLER_BINDING_INVALID",
    )
    created_at = _parse_timestamp(
        request["created_at"], code="COLLECTOR_REQUEST_TIME_INVALID"
    )
    current_text = _canonical_timestamp(now, code="COLLECTOR_TIME_INVALID")
    current = _parse_timestamp(current_text, code="COLLECTOR_TIME_INVALID")
    if created_at > current + timedelta(seconds=MAX_FUTURE_SKEW_SECONDS):
        raise CollectorError("COLLECTOR_REQUEST_TIME_INVALID")
    if current - created_at > timedelta(seconds=MAX_REQUEST_AGE_SECONDS):
        raise CollectorError("COLLECTOR_REQUEST_EXPIRED")

    supplied_fingerprint = _require_sha256(
        request["request_fingerprint_sha256"],
        code="COLLECTOR_REQUEST_FINGERPRINT_INVALID",
    )
    unsigned = dict(request)
    unsigned.pop("request_fingerprint_sha256")
    if supplied_fingerprint != _sha256_bytes(_canonical_json(unsigned)):
        raise CollectorError("COLLECTOR_REQUEST_FINGERPRINT_MISMATCH")

    expected_captures = [
        {
            "width": width,
            "height": height,
            "assistant_mode": assistant_mode,
        }
        for width, height in ALLOWED_VIEWPORTS
        for assistant_mode in ALLOWED_ASSISTANT_MODES
    ]
    if request["required_captures"] != expected_captures:
        raise CollectorError("COLLECTOR_CAPTURE_MATRIX_INVALID")
    runtime_contract = _exact_mapping(
        request["runtime_contract"],
        frozenset({"sidecar_container_name", "range_status_codes"}),
        code="COLLECTOR_RUNTIME_CONTRACT_INVALID",
    )
    if runtime_contract != {
        "sidecar_container_name": EXPECTED_SIDECAR_CONTAINER_NAME,
        "range_status_codes": list(EXPECTED_RANGE_STATUS_CODES),
    }:
        raise CollectorError("COLLECTOR_RUNTIME_CONTRACT_INVALID")

    seed = _exact_mapping(
        request["binding_seed"],
        frozenset(
            {
                "run_fingerprint_sha256",
                "target_scope_sha256",
                "automatic_edition_id_sha256",
                "automatic_edition_fingerprint_sha256",
                "manual_edition_id_sha256",
                "manual_edition_fingerprint_sha256",
                "listening_output_hashes",
                "required_stability_seconds",
            }
        ),
        code="COLLECTOR_BINDING_INVALID",
    )
    hashes = seed["listening_output_hashes"]
    if (
        type(hashes) is not list
        or not hashes
        or any(not _is_sha256(item) for item in hashes)
        or hashes != sorted(set(hashes))
        or type(seed["required_stability_seconds"]) not in {int, float}
        or not math.isfinite(float(seed["required_stability_seconds"]))
        or float(seed["required_stability_seconds"])
        != FIXED_REQUIRED_STABILITY_SECONDS
    ):
        raise CollectorError("COLLECTOR_BINDING_INVALID")
    try:
        expectation = ProbeExpectation(
            run_fingerprint_sha256=_require_sha256(
                seed["run_fingerprint_sha256"],
                code="COLLECTOR_BINDING_INVALID",
            ),
            target_scope_sha256=_require_sha256(
                seed["target_scope_sha256"],
                code="COLLECTOR_BINDING_INVALID",
            ),
            automatic_edition_id_sha256=_require_sha256(
                seed["automatic_edition_id_sha256"],
                code="COLLECTOR_BINDING_INVALID",
            ),
            automatic_edition_fingerprint_sha256=_require_sha256(
                seed["automatic_edition_fingerprint_sha256"],
                code="COLLECTOR_BINDING_INVALID",
            ),
            manual_edition_id_sha256=_require_sha256(
                seed["manual_edition_id_sha256"],
                code="COLLECTOR_BINDING_INVALID",
            ),
            manual_edition_fingerprint_sha256=_require_sha256(
                seed["manual_edition_fingerprint_sha256"],
                code="COLLECTOR_BINDING_INVALID",
            ),
            listening_output_hashes=tuple(hashes),
            required_stability_seconds=float(
                seed["required_stability_seconds"]
            ),
        )
    except ProbeReportError:
        raise CollectorError("COLLECTOR_BINDING_INVALID") from None
    performance = _exact_mapping(
        request["performance_seed"],
        frozenset(
            {
                "request_to_ready_seconds",
                "observed_http_first_audio_ms",
                "chapter_audio_duration_seconds",
            }
        ),
        code="COLLECTOR_PERFORMANCE_SEED_INVALID",
    )
    request_to_ready = performance["request_to_ready_seconds"]
    first_audio = performance["observed_http_first_audio_ms"]
    duration = performance["chapter_audio_duration_seconds"]
    if (
        type(request_to_ready) is not list
        or len(request_to_ready) != 2
        or any(
            type(value) not in {int, float}
            or not math.isfinite(float(value))
            or float(value) < 0
            for value in request_to_ready
        )
        or type(first_audio) is not list
        or len(first_audio) != 2
        or any(type(value) is not int or value < 0 for value in first_audio)
        or type(duration) not in {int, float}
        or not math.isfinite(float(duration))
        or float(duration) <= 0
    ):
        raise CollectorError("COLLECTOR_PERFORMANCE_SEED_INVALID")
    return (
        CollectorRequest(
            created_at=created_at,
            request_sha256=_sha256_bytes(raw),
            request_fingerprint_sha256=supplied_fingerprint,
            preflight_payload_sha256=preflight_payload_sha256,
            expectation=expectation,
            performance_seed=PerformanceSeed(
                request_to_ready_seconds=tuple(
                    float(value) for value in request_to_ready
                ),
                observed_http_first_audio_ms=tuple(first_audio),
                chapter_audio_duration_seconds=float(duration),
            ),
        ),
        parent,
        parent_identity,
    )


def _read_private_sibling_bytes(
    parent: Path,
    parent_identity: tuple[int, ...],
    *,
    filename: str,
) -> tuple[bytes, tuple[int, ...]]:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise CollectorError("COLLECTOR_CONTROLLER_PREFLIGHT_INVALID")
    parent_fd: int | None = None
    try:
        parent_fd = os.open(
            parent,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | nofollow,
        )
        _assert_parent_identity(parent, parent_fd, parent_identity)
        raw, identity = _read_locked_bytes(
            parent_fd,
            filename,
            allow_multiple_links=False,
        )
        _assert_parent_identity(parent, parent_fd, parent_identity)
        return raw, identity
    except CollectorError as error:
        if error.code == "COLLECTOR_FILE_UNSAFE":
            raise CollectorError(
                "COLLECTOR_CONTROLLER_PREFLIGHT_INVALID"
            ) from None
        raise
    except OSError:
        raise CollectorError(
            "COLLECTOR_CONTROLLER_PREFLIGHT_INVALID"
        ) from None
    finally:
        if parent_fd is not None:
            try:
                os.close(parent_fd)
            except OSError:
                pass


def _verify_request_controller_preflight(
    request: CollectorRequest,
    parent: Path,
    parent_identity: tuple[int, ...],
) -> _VerifiedRequestPreflight:
    try:
        (
            payload_raw,
            payload,
            payload_parent,
            payload_parent_identity,
            payload_identity,
        ) = _read_private_json(
            parent / CONTROLLER_PREFLIGHT_FILENAME,
            expected_filename=CONTROLLER_PREFLIGHT_FILENAME,
            name_error_code="COLLECTOR_CONTROLLER_PREFLIGHT_INVALID",
            json_error_code="COLLECTOR_CONTROLLER_PREFLIGHT_INVALID",
        )
        signature_raw, signature_identity = _read_private_sibling_bytes(
            parent,
            parent_identity,
            filename=CONTROLLER_PREFLIGHT_SIGNATURE_FILENAME,
        )
    except CollectorError as error:
        if error.code == "COLLECTOR_CONTROLLER_PREFLIGHT_INVALID":
            raise
        raise CollectorError(
            "COLLECTOR_CONTROLLER_PREFLIGHT_INVALID"
        ) from None
    if (
        payload_parent != parent
        or payload_parent_identity != parent_identity
        or _sha256_bytes(payload_raw) != request.preflight_payload_sha256
    ):
        raise CollectorError("COLLECTOR_CONTROLLER_PREFLIGHT_INVALID")
    try:
        expectation = PreflightExpectation(
            nonce_sha256=_require_sha256(
                payload.get("nonce_sha256"),
                code="COLLECTOR_CONTROLLER_PREFLIGHT_INVALID",
            ),
            run_fingerprint_sha256=(
                request.expectation.run_fingerprint_sha256
            ),
            target_scope_sha256=(
                request.expectation.target_scope_sha256
            ),
            operator_envelope_sha256=_require_sha256(
                payload.get("operator_envelope_sha256"),
                code="COLLECTOR_CONTROLLER_PREFLIGHT_INVALID",
            ),
            fixture_manifest_sha256=_require_sha256(
                payload.get("fixture_manifest_sha256"),
                code="COLLECTOR_CONTROLLER_PREFLIGHT_INVALID",
            ),
        )
        verified = FixedControllerTrustVerifier().verify_preflight(
            payload_raw,
            signature_raw,
            expectation=expectation,
            now=request.created_at,
        )
    except ControllerTrustError as error:
        if error.code == CONTROLLER_TRUST_ROOT_HOLD_ERROR:
            raise CollectorError(
                COLLECTOR_CONTROLLER_AUTHORITY_HOLD_ERROR
            ) from None
        if error.code == CONTROLLER_PREFLIGHT_BINDING_MISMATCH_ERROR:
            raise CollectorError(
                "COLLECTOR_CONTROLLER_PREFLIGHT_BINDING_MISMATCH"
            ) from None
        raise CollectorError(
            "COLLECTOR_CONTROLLER_PREFLIGHT_INVALID"
        ) from None
    if (
        verified.payload_sha256 != request.preflight_payload_sha256
        or not verified.issued_at <= request.created_at < verified.expires_at
    ):
        raise CollectorError("COLLECTOR_CONTROLLER_PREFLIGHT_INVALID")
    return _VerifiedRequestPreflight(
        verified=verified,
        payload_identity=payload_identity,
        signature_identity=signature_identity,
    )


def _number(value: object, *, positive: bool, code: str) -> float:
    if type(value) not in {int, float} or not math.isfinite(float(value)):
        raise CollectorError(code)
    result = float(value)
    if result < 0 or (positive and result <= 0):
        raise CollectorError(code)
    return result


def _derive_memory_summary(
    samples: Sequence[SidecarMetricSampleDigest],
    *,
    code: str,
) -> tuple[int, int, int, int, bool]:
    """Derive the fixed five-point edge medians from exactly 31 samples."""

    if (
        isinstance(samples, (str, bytes, bytearray))
        or len(samples) != FIXED_MIN_METRIC_SAMPLE_COUNT
        or any(
            type(sample) is not SidecarMetricSampleDigest
            or type(sample.resident_memory_bytes) is not int
            or sample.resident_memory_bytes < 0
            for sample in samples
        )
    ):
        raise CollectorError(code)
    baseline_values = sorted(
        sample.resident_memory_bytes
        for sample in samples[:MEMORY_TREND_WINDOW_SIZE]
    )
    tail_values = sorted(
        sample.resident_memory_bytes
        for sample in samples[-MEMORY_TREND_WINDOW_SIZE:]
    )
    median_index = MEMORY_TREND_WINDOW_SIZE // 2
    baseline = baseline_values[median_index]
    tail = tail_values[median_index]
    growth = max(0, tail - baseline)
    percentage_limit = (
        baseline * MEMORY_GROWTH_PERCENT_NUMERATOR
        + MEMORY_GROWTH_PERCENT_DENOMINATOR
        - 1
    ) // MEMORY_GROWTH_PERCENT_DENOMINATOR
    limit = max(MEMORY_GROWTH_MIN_LIMIT_BYTES, percentage_limit)
    return baseline, tail, growth, limit, growth > limit


def _validated_runtime_payload(
    request: CollectorRequest,
    runtime: SidecarCollectorEvidence,
    *,
    collected_at: datetime,
) -> dict[str, object]:
    code = "COLLECTOR_RUNTIME_GATE_FAILED"
    if type(runtime) is not SidecarCollectorEvidence:
        raise CollectorError("COLLECTOR_RUNTIME_INVALID")
    started_text = _canonical_timestamp(runtime.window_started_at, code=code)
    ended_text = _canonical_timestamp(runtime.window_ended_at, code=code)
    started = _parse_timestamp(started_text, code=code)
    ended = _parse_timestamp(ended_text, code=code)
    normalized_collected = _parse_timestamp(
        _canonical_timestamp(collected_at, code=code),
        code=code,
    )
    elapsed = (ended - started).total_seconds()
    supplied_elapsed = _number(
        runtime.stability_elapsed_seconds,
        positive=True,
        code=code,
    )
    supplied_duration = _number(
        runtime.chapter_audio_duration_seconds,
        positive=True,
        code=code,
    )
    supplied_request_to_ready = _number(
        runtime.request_to_ready_seconds,
        positive=False,
        code=code,
    )
    expected_duration = request.performance_seed.chapter_audio_duration_seconds
    expected_request_to_ready = max(
        request.performance_seed.request_to_ready_seconds
    )
    if (
        runtime.sidecar_container_name != EXPECTED_SIDECAR_CONTAINER_NAME
        or runtime.request_fingerprint_sha256
        != request.request_fingerprint_sha256
        or started < request.created_at
        or ended != normalized_collected
        or elapsed < request.expectation.required_stability_seconds
        or supplied_elapsed != elapsed
        or supplied_duration != expected_duration
        or supplied_request_to_ready != expected_request_to_ready
        or type(runtime.peak_memory_bytes) is not int
        or runtime.peak_memory_bytes < 0
        or type(runtime.host_paging_observed) is not bool
        or type(runtime.pageout_delta) is not int
        or runtime.pageout_delta < 0
        or type(runtime.swapout_delta) is not int
        or runtime.swapout_delta < 0
        or type(runtime.memory_baseline_median_bytes) is not int
        or runtime.memory_baseline_median_bytes < 0
        or type(runtime.memory_tail_median_bytes) is not int
        or runtime.memory_tail_median_bytes < 0
        or type(runtime.memory_growth_bytes) is not int
        or runtime.memory_growth_bytes < 0
        or type(runtime.memory_growth_limit_bytes) is not int
        or runtime.memory_growth_limit_bytes < 0
        or type(runtime.sidecar_memory_growth_observed) is not bool
        or type(runtime.qwenpaw_slowdown_observed) is not bool
        or type(runtime.sidecar_restart_count) is not int
        or runtime.sidecar_restart_count != 0
        or type(runtime.health_failure_count) is not int
        or runtime.health_failure_count != 0
        or type(runtime.metric_sample_count) is not int
        or type(runtime.metric_samples) is not tuple
        or runtime.metric_sample_count != len(runtime.metric_samples)
        or runtime.metric_sample_count != FIXED_MIN_METRIC_SAMPLE_COUNT
        or any(
            type(sample) is not SidecarMetricSampleDigest
            or type(sample.resident_memory_bytes) is not int
            or sample.resident_memory_bytes < 0
            for sample in runtime.metric_samples
        )
        or not _is_sha256(runtime.metric_sample_chain_sha256)
        or not _is_sha256(runtime.metrics_summary_sha256)
    ):
        raise CollectorError(code)
    expected_chain = build_sidecar_metric_sample_chain_sha256(
        request_fingerprint_sha256=request.request_fingerprint_sha256,
        window_started_at=started,
        window_ended_at=ended,
        metrics_summary_sha256=runtime.metrics_summary_sha256,
        samples=runtime.metric_samples,
    )
    if not hmac.compare_digest(
        runtime.metric_sample_chain_sha256,
        expected_chain,
    ):
        raise CollectorError(code)
    measured_peak_memory_bytes = max(
        sample.resident_memory_bytes for sample in runtime.metric_samples
    )
    (
        measured_baseline,
        measured_tail,
        measured_growth,
        measured_growth_limit,
        measured_growth_observed,
    ) = _derive_memory_summary(runtime.metric_samples, code=code)
    measured_host_paging = (
        runtime.pageout_delta > 0 or runtime.swapout_delta > 0
    )
    if (
        runtime.peak_memory_bytes != measured_peak_memory_bytes
        or runtime.host_paging_observed is not measured_host_paging
        or runtime.memory_baseline_median_bytes != measured_baseline
        or runtime.memory_tail_median_bytes != measured_tail
        or runtime.memory_growth_bytes != measured_growth
        or runtime.memory_growth_limit_bytes != measured_growth_limit
        or runtime.sidecar_memory_growth_observed
        is not measured_growth_observed
    ):
        raise CollectorError(code)
    return {
        "sidecar_container_name": runtime.sidecar_container_name,
        "window_started_at": started_text,
        "window_ended_at": ended_text,
        "request_fingerprint_sha256": request.request_fingerprint_sha256,
        # This is intentionally computed from the signed window, not copied
        # from the caller-provided compatibility scalar.
        "stability_elapsed_seconds": elapsed,
        "chapter_audio_duration_seconds": expected_duration,
        "request_to_ready_seconds": expected_request_to_ready,
        "peak_memory_bytes": measured_peak_memory_bytes,
        "host_paging_observed": measured_host_paging,
        "pageout_delta": runtime.pageout_delta,
        "swapout_delta": runtime.swapout_delta,
        "memory_baseline_median_bytes": measured_baseline,
        "memory_tail_median_bytes": measured_tail,
        "memory_growth_bytes": measured_growth,
        "memory_growth_limit_bytes": measured_growth_limit,
        "sidecar_memory_growth_observed": measured_growth_observed,
        "qwenpaw_slowdown_observed": runtime.qwenpaw_slowdown_observed,
        "sidecar_restart_count": runtime.sidecar_restart_count,
        "health_failure_count": runtime.health_failure_count,
        "metric_sample_count": runtime.metric_sample_count,
        "metric_samples": [
            {
                "observed_at": _canonical_timestamp(
                    sample.observed_at,
                    code=code,
                ),
                "sample_sha256": sample.sample_sha256,
                "resident_memory_bytes": sample.resident_memory_bytes,
            }
            for sample in runtime.metric_samples
        ],
        "metric_sample_chain_sha256": expected_chain,
        "metrics_summary_sha256": runtime.metrics_summary_sha256,
    }


def _validate_evidence(
    request: CollectorRequest,
    evidence: FixedControllerEvidence,
    *,
    now: datetime,
    require_real: bool,
) -> None:
    if type(evidence) is not FixedControllerEvidence:
        raise CollectorError("COLLECTOR_EVIDENCE_INVALID")
    if (
        evidence.controller_id != FIXED_CONTROLLER_ID
        or evidence.page_url != FIXED_PUBLIC_PAGE_URL
        or evidence.request_fingerprint_sha256
        != request.request_fingerprint_sha256
        or type(evidence.synthetic) is not bool
    ):
        raise CollectorError("COLLECTOR_SOURCE_INVALID")
    if require_real and evidence.synthetic:
        raise CollectorError("COLLECTOR_SYNTHETIC_NOT_FORMAL")
    if not require_real and not evidence.synthetic:
        raise CollectorError("COLLECTOR_SYNTHETIC_MODE_REQUIRED")

    collected_text = _canonical_timestamp(
        evidence.collected_at, code="COLLECTOR_COLLECTION_TIME_INVALID"
    )
    collected = _parse_timestamp(
        collected_text, code="COLLECTOR_COLLECTION_TIME_INVALID"
    )
    current_text = _canonical_timestamp(now, code="COLLECTOR_TIME_INVALID")
    current = _parse_timestamp(current_text, code="COLLECTOR_TIME_INVALID")
    if (
        collected < request.created_at
        or collected - request.created_at
        > timedelta(seconds=MAX_REQUEST_AGE_SECONDS)
        or collected > current + timedelta(seconds=MAX_FUTURE_SKEW_SECONDS)
        or current - collected > timedelta(seconds=MAX_REPORT_AGE_SECONDS)
    ):
        raise CollectorError("COLLECTOR_COLLECTION_TIME_INVALID")

    browser = evidence.browser
    if type(browser) is not BrowserCollectorEvidence:
        raise CollectorError("COLLECTOR_BROWSER_INVALID")
    captures = browser.captures
    expected = {
        (width, height, mode)
        for width, height in ALLOWED_VIEWPORTS
        for mode in ALLOWED_ASSISTANT_MODES
    }
    observed: set[tuple[int, int, str]] = set()
    screenshot_hashes: set[str] = set()
    if type(captures) is not tuple or len(captures) != len(expected):
        raise CollectorError("COLLECTOR_CAPTURE_MATRIX_INVALID")
    for capture in captures:
        if type(capture) is not CaptureDigest:
            raise CollectorError("COLLECTOR_CAPTURE_INVALID")
        key = (capture.width, capture.height, capture.assistant_mode)
        if (
            type(capture.width) is not int
            or type(capture.height) is not int
            or type(capture.assistant_mode) is not str
            or key not in expected
            or key in observed
            or capture.observed_inner_width != capture.width
            or capture.observed_inner_height != capture.height
            or type(capture.device_pixel_ratio) not in {int, float}
            or not math.isfinite(float(capture.device_pixel_ratio))
            or float(capture.device_pixel_ratio) <= 0
            or type(capture.screenshot_pixel_width) is not int
            or capture.screenshot_pixel_width <= 0
            or type(capture.screenshot_pixel_height) is not int
            or capture.screenshot_pixel_height <= 0
            or not _is_sha256(capture.calibration_summary_sha256)
            or not _is_sha256(capture.screenshot_sha256)
            or capture.screenshot_sha256 in screenshot_hashes
            or type(capture.screenshot_bytes) is not int
            or capture.screenshot_bytes <= 0
            or not _is_sha256(capture.console_summary_sha256)
            or not _is_sha256(capture.network_summary_sha256)
            or type(capture.network_request_count) is not int
            or capture.network_request_count <= 0
            or type(capture.console_error_count) is not int
            or capture.console_error_count != 0
            or type(capture.overlap_count) is not int
            or capture.overlap_count != 0
        ):
            raise CollectorError("COLLECTOR_CAPTURE_INVALID")
        observed.add(key)
        screenshot_hashes.add(capture.screenshot_sha256)
    if observed != expected:
        raise CollectorError("COLLECTOR_CAPTURE_MATRIX_INVALID")

    if (
        not _is_sha256(browser.observer_report_sha256)
        or type(browser.range_status_codes) is not tuple
        or browser.range_status_codes != EXPECTED_RANGE_STATUS_CODES
        or not _is_sha256(browser.range_summary_sha256)
        or not _is_sha256(browser.etag_summary_sha256)
        or browser.etag_observed is not True
        or browser.if_none_match_304_observed is not True
        or browser.if_range_206_observed is not True
        or browser.unsatisfied_range_416_observed is not True
        or type(browser.time_to_first_audio_ms) is not int
        or browser.time_to_first_audio_ms < 0
        or browser.time_to_first_audio_ms
        != max(request.performance_seed.observed_http_first_audio_ms)
        or type(browser.seam_pairs_checked) is not int
        or browser.seam_pairs_checked < 1
        or browser.seek_latest_wins is not True
        or browser.pending_gap_not_skipped is not True
        or not _is_sha256(browser.interaction_summary_sha256)
        or type(browser.edit_actions_observed) is not int
        or browser.edit_actions_observed < 1
        or type(browser.edit_actions_created_tts_writes) is not int
        or browser.edit_actions_created_tts_writes != 0
        or not _is_sha256(browser.editor_summary_sha256)
    ):
        raise CollectorError("COLLECTOR_BROWSER_GATE_FAILED")

    _validated_runtime_payload(
        request,
        evidence.runtime,
        collected_at=collected,
    )


def _capture_payload(capture: CaptureDigest) -> dict[str, object]:
    return {
        "width": capture.width,
        "height": capture.height,
        "assistant_mode": capture.assistant_mode,
        "observed_inner_width": capture.observed_inner_width,
        "observed_inner_height": capture.observed_inner_height,
        "device_pixel_ratio": capture.device_pixel_ratio,
        "screenshot_pixel_width": capture.screenshot_pixel_width,
        "screenshot_pixel_height": capture.screenshot_pixel_height,
        "calibration_summary_sha256": (
            capture.calibration_summary_sha256
        ),
        "screenshot_sha256": capture.screenshot_sha256,
        "screenshot_bytes": capture.screenshot_bytes,
        "console_summary_sha256": capture.console_summary_sha256,
        "network_summary_sha256": capture.network_summary_sha256,
        "network_request_count": capture.network_request_count,
        "console_error_count": capture.console_error_count,
        "overlap_count": capture.overlap_count,
    }


def _ordered_captures(
    captures: Sequence[CaptureDigest],
) -> tuple[CaptureDigest, ...]:
    order = {
        (width, height, mode): index
        for index, (width, height, mode) in enumerate(
            (
                (width, height, mode)
                for width, height in ALLOWED_VIEWPORTS
                for mode in ALLOWED_ASSISTANT_MODES
            )
        )
    }
    return tuple(
        sorted(
            captures,
            key=lambda item: order[
                (item.width, item.height, item.assistant_mode)
            ],
        )
    )


def _build_report_core(
    request: CollectorRequest,
    evidence: FixedControllerEvidence,
) -> tuple[bytes, bytes]:
    collected_at = _canonical_timestamp(
        evidence.collected_at, code="COLLECTOR_COLLECTION_TIME_INVALID"
    )
    binding = request.expectation.report_binding(
        collected_at=evidence.collected_at
    )
    runtime_payload = _validated_runtime_payload(
        request,
        evidence.runtime,
        collected_at=evidence.collected_at,
    )
    captures = _ordered_captures(evidence.browser.captures)
    probe_payload: dict[str, object] = {
        "schema_version": PROBE_SCHEMA_VERSION,
        "collected_at": collected_at,
        "binding": binding,
        "browser": {
            "observer_report_sha256": (
                evidence.browser.observer_report_sha256
            ),
            "captures": [
                {
                    "width": capture.width,
                    "height": capture.height,
                    "assistant_mode": capture.assistant_mode,
                    "console_error_count": capture.console_error_count,
                    "overlap_count": capture.overlap_count,
                }
                for capture in captures
            ],
            "range_status_codes": list(
                evidence.browser.range_status_codes
            ),
            "time_to_first_audio_ms": (
                evidence.browser.time_to_first_audio_ms
            ),
            "seam_pairs_checked": evidence.browser.seam_pairs_checked,
            "seek_latest_wins": evidence.browser.seek_latest_wins,
            "pending_gap_not_skipped": (
                evidence.browser.pending_gap_not_skipped
            ),
            "edit_actions_created_tts_writes": (
                evidence.browser.edit_actions_created_tts_writes
            ),
        },
        "runtime": {
            "sidecar_container_name": runtime_payload[
                "sidecar_container_name"
            ],
            "stability_elapsed_seconds": runtime_payload[
                "stability_elapsed_seconds"
            ],
            "chapter_audio_duration_seconds": runtime_payload[
                "chapter_audio_duration_seconds"
            ],
            "request_to_ready_seconds": runtime_payload[
                "request_to_ready_seconds"
            ],
            "peak_memory_bytes": runtime_payload["peak_memory_bytes"],
            "host_paging_observed": runtime_payload[
                "host_paging_observed"
            ],
            "pageout_delta": runtime_payload["pageout_delta"],
            "swapout_delta": runtime_payload["swapout_delta"],
            "memory_baseline_median_bytes": runtime_payload[
                "memory_baseline_median_bytes"
            ],
            "memory_tail_median_bytes": runtime_payload[
                "memory_tail_median_bytes"
            ],
            "memory_growth_bytes": runtime_payload["memory_growth_bytes"],
            "memory_growth_limit_bytes": runtime_payload[
                "memory_growth_limit_bytes"
            ],
            "sidecar_memory_growth_observed": runtime_payload[
                "sidecar_memory_growth_observed"
            ],
            "qwenpaw_slowdown_observed": runtime_payload[
                "qwenpaw_slowdown_observed"
            ],
            "sidecar_restart_count": runtime_payload[
                "sidecar_restart_count"
            ],
            "health_failure_count": runtime_payload[
                "health_failure_count"
            ],
        },
    }
    probe_bytes = _canonical_json(probe_payload) + b"\n"
    detailed_captures = [_capture_payload(item) for item in captures]
    screenshot_set = [item["screenshot_sha256"] for item in detailed_captures]
    console_set = [item["console_summary_sha256"] for item in detailed_captures]
    network_set = [item["network_summary_sha256"] for item in detailed_captures]
    unsigned_collector: dict[str, object] = {
        "schema_version": COLLECTOR_SCHEMA_VERSION,
        "collected_at": collected_at,
        "formal_validation_eligible": True,
        "source": {
            "controller_id": FIXED_CONTROLLER_ID,
            "page_url": FIXED_PUBLIC_PAGE_URL,
            "synthetic": False,
        },
        "request": {
            "schema_version": PROBE_REQUEST_SCHEMA_VERSION,
            "report_schema_version": PROBE_SCHEMA_VERSION,
            "created_at": _canonical_timestamp(
                request.created_at, code="COLLECTOR_REQUEST_TIME_INVALID"
            ),
            "request_fingerprint_sha256": (
                request.request_fingerprint_sha256
            ),
            "request_sha256": request.request_sha256,
        },
        "binding": binding,
        "browser": {
            "observer_report_sha256": (
                evidence.browser.observer_report_sha256
            ),
            "captures": detailed_captures,
            "screenshot_set_sha256": _sha256_bytes(
                _canonical_json(screenshot_set)
            ),
            "console_set_sha256": _sha256_bytes(_canonical_json(console_set)),
            "network_set_sha256": _sha256_bytes(_canonical_json(network_set)),
            "range_etag": {
                "range_status_codes": list(
                    evidence.browser.range_status_codes
                ),
                "range_summary_sha256": (
                    evidence.browser.range_summary_sha256
                ),
                "etag_summary_sha256": evidence.browser.etag_summary_sha256,
                "etag_observed": evidence.browser.etag_observed,
                "if_none_match_304_observed": (
                    evidence.browser.if_none_match_304_observed
                ),
                "if_range_206_observed": (
                    evidence.browser.if_range_206_observed
                ),
                "unsatisfied_range_416_observed": (
                    evidence.browser.unsatisfied_range_416_observed
                ),
            },
            "interaction": {
                "time_to_first_audio_ms": (
                    evidence.browser.time_to_first_audio_ms
                ),
                "seam_pairs_checked": evidence.browser.seam_pairs_checked,
                "seek_latest_wins": evidence.browser.seek_latest_wins,
                "pending_gap_not_skipped": (
                    evidence.browser.pending_gap_not_skipped
                ),
                "interaction_summary_sha256": (
                    evidence.browser.interaction_summary_sha256
                ),
            },
            "editor": {
                "edit_actions_observed": (
                    evidence.browser.edit_actions_observed
                ),
                "edit_actions_created_tts_writes": (
                    evidence.browser.edit_actions_created_tts_writes
                ),
                "editor_summary_sha256": (
                    evidence.browser.editor_summary_sha256
                ),
            },
        },
        "runtime": runtime_payload,
        "probe_report_sha256": _sha256_bytes(probe_bytes),
    }
    return _canonical_json(unsigned_collector) + b"\n", probe_bytes


def _build_reports(
    request: CollectorRequest,
    evidence: FixedControllerEvidence,
    *,
    attestation_key: bytes,
) -> tuple[bytes, bytes]:
    """Build a legacy HMAC candidate that is permanently non-formal.

    This compatibility primitive exists only for recognizing interrupted
    historical test transactions.  The v2 formal path never calls it and the
    guard never upgrades its result beyond controller-authority HOLD.
    """

    core_bytes, probe_bytes = _build_report_core(request, evidence)
    core = dict(
        _decode_json_mapping(
            core_bytes,
            code="COLLECTOR_REPORT_INVALID",
        )
    )
    core["schema_version"] = LEGACY_COLLECTOR_SCHEMA_VERSION
    legacy_request = dict(core["request"])
    legacy_request.pop("request_sha256")
    core["request"] = legacy_request
    fingerprinted_collector = {
        **core,
        "collector_report_fingerprint_sha256": _sha256_bytes(
            _canonical_json(core)
        ),
    }
    collector_payload = {
        **fingerprinted_collector,
        "controller_attestation_hmac_sha256": (
            _collector_attestation_hmac(
                attestation_key,
                fingerprinted_collector,
            )
        ),
    }
    collector_bytes = _canonical_json(collector_payload) + b"\n"
    return collector_bytes, probe_bytes


def _prepare_controller_report(
    request: CollectorRequest,
    evidence: FixedControllerEvidence,
    *,
    preflight_payload_sha256: str,
) -> tuple[ControllerReportPreparation, bytes, bytes]:
    if not _is_sha256(preflight_payload_sha256):
        raise CollectorError("COLLECTOR_CONTROLLER_BINDING_INVALID")
    collector_core_bytes, probe_bytes = _build_report_core(request, evidence)
    try:
        expectation = ReportExpectation(
            preflight_payload_sha256=preflight_payload_sha256,
            run_fingerprint_sha256=(
                request.expectation.run_fingerprint_sha256
            ),
            target_scope_sha256=request.expectation.target_scope_sha256,
            probe_request_sha256=request.request_sha256,
            request_fingerprint_sha256=request.request_fingerprint_sha256,
            automatic_edition_fingerprint_sha256=(
                request.expectation.automatic_edition_fingerprint_sha256
            ),
            manual_edition_fingerprint_sha256=(
                request.expectation.manual_edition_fingerprint_sha256
            ),
            listening_output_hashes=(
                request.expectation.listening_output_hashes
            ),
            # This field name is frozen by the controller trust DTO.  Its
            # precise collector meaning is the canonical unsigned core hash,
            # not the final collector-report file hash.  The final hash is
            # bound only by the v2 commit marker after authority is attached.
            collector_report_sha256=_sha256_bytes(collector_core_bytes),
            probe_report_sha256=_sha256_bytes(probe_bytes),
        )
    except ControllerTrustError:
        raise CollectorError("COLLECTOR_CONTROLLER_BINDING_INVALID") from None
    return (
        ControllerReportPreparation(expectation=expectation),
        collector_core_bytes,
        probe_bytes,
    )


def prepare_controller_report_binding(
    probe_request_path: Path,
    evidence: FixedControllerEvidence,
    *,
    now: datetime | None = None,
) -> ControllerReportPreparation:
    """Prepare hashes for the host's fixed signing ceremony without writes."""

    current = now or datetime.now(timezone.utc).replace(microsecond=0)
    request, parent, parent_identity = _load_request(
        probe_request_path,
        now=current,
    )
    _validate_evidence(request, evidence, now=current, require_real=True)
    _verify_request_controller_preflight(
        request,
        parent,
        parent_identity,
    )
    preparation, _core, _probe = _prepare_controller_report(
        request,
        evidence,
        preflight_payload_sha256=request.preflight_payload_sha256,
    )
    return preparation


def build_controller_report_binding_payload(
    preparation: ControllerReportPreparation,
    evidence: FixedControllerEvidence,
    context: ControllerReportSigningContext,
) -> bytes:
    """Build the exact canonical bytes the host controller may SSHSIG-sign."""

    if (
        type(preparation) is not ControllerReportPreparation
        or type(evidence) is not FixedControllerEvidence
        or type(context) is not ControllerReportSigningContext
    ):
        raise CollectorError("COLLECTOR_CONTROLLER_BINDING_INVALID")
    expected = preparation.expectation
    try:
        signed_at = _canonical_timestamp(
            context.signed_at,
            code="COLLECTOR_CONTROLLER_BINDING_INVALID",
        )
        runtime = evidence.runtime
        started = _canonical_timestamp(
            runtime.window_started_at,
            code="COLLECTOR_CONTROLLER_BINDING_INVALID",
        )
        ended = _canonical_timestamp(
            runtime.window_ended_at,
            code="COLLECTOR_CONTROLLER_BINDING_INVALID",
        )
        elapsed_milliseconds = int(
            (runtime.window_ended_at - runtime.window_started_at)
            .total_seconds()
            * 1000
        )
        payload: dict[str, object] = {
            "schema_version": CONTROLLER_REPORT_BINDING_SCHEMA_VERSION,
            "signed_at": signed_at,
            "preflight_payload_sha256": (
                expected.preflight_payload_sha256
            ),
            "run_fingerprint_sha256": expected.run_fingerprint_sha256,
            "target_scope_sha256": expected.target_scope_sha256,
            "probe_request_sha256": expected.probe_request_sha256,
            "request_fingerprint_sha256": (
                expected.request_fingerprint_sha256
            ),
            "automatic_edition_fingerprint_sha256": (
                expected.automatic_edition_fingerprint_sha256
            ),
            "manual_edition_fingerprint_sha256": (
                expected.manual_edition_fingerprint_sha256
            ),
            "listening_output_hashes": list(
                expected.listening_output_hashes
            ),
            "required_stability_milliseconds": (
                FIXED_REQUIRED_STABILITY_MILLISECONDS
            ),
            "observed_captures": [
                item.to_payload() for item in context.observed_captures
            ],
            "window_started_at": started,
            "window_ended_at": ended,
            "stability_elapsed_milliseconds": elapsed_milliseconds,
            "metric_sample_count": runtime.metric_sample_count,
            "metric_sample_chain_sha256": (
                runtime.metric_sample_chain_sha256
            ),
            "collector_report_sha256": (
                expected.collector_report_sha256
            ),
            "probe_report_sha256": expected.probe_report_sha256,
            "controller_id": FIXED_CONTROLLER_ID,
            "controller_build_sha256": (
                context.controller_build_sha256
            ),
            "browser_binary_sha256": context.browser_binary_sha256,
            "signing_key_id": context.signing_key_id,
            "signer_principal": context.signer_principal,
            "signature_namespace": REPORT_SIGNATURE_NAMESPACE,
            "trust_policy_sha256": context.trust_policy_sha256,
            "allowed_signers_sha256": (
                context.allowed_signers_sha256
            ),
        }
        return _canonical_controller_json(payload)
    except (AttributeError, TypeError, ValueError, ControllerTrustError):
        raise CollectorError("COLLECTOR_CONTROLLER_BINDING_INVALID") from None


def _build_formal_collector_report(
    collector_core_bytes: bytes,
    controller_report_binding: bytes,
    controller_report_signature: bytes,
) -> bytes:
    try:
        core = _decode_json_mapping(
            collector_core_bytes,
            code="COLLECTOR_REPORT_INVALID",
        )
        binding = _decode_json_mapping(
            controller_report_binding,
            code="COLLECTOR_CONTROLLER_BINDING_INVALID",
        )
        signature = controller_report_signature.decode(
            "ascii", errors="strict"
        )
    except UnicodeDecodeError:
        raise CollectorError("COLLECTOR_CONTROLLER_ATTESTATION_INVALID") from None
    if (
        not signature.startswith("-----BEGIN SSH SIGNATURE-----\n")
        or not signature.rstrip("\n").endswith(
            "-----END SSH SIGNATURE-----"
        )
    ):
        raise CollectorError("COLLECTOR_CONTROLLER_ATTESTATION_INVALID")
    final = {
        **core,
        "controller_authority": {
            "report_binding": binding,
            "report_binding_sha256": _sha256_bytes(
                controller_report_binding
            ),
            "report_binding_sshsig": signature,
        },
    }
    return _canonical_json(final) + b"\n"


def _build_local_operator_collector_report(
    collector_core_bytes: bytes,
    *,
    controller_build_sha256: str,
    browser_binary_sha256: str,
    node_binary_sha256: str,
) -> bytes:
    """Label one fixed local run without claiming signing authority."""

    core = dict(
        _decode_json_mapping(
            collector_core_bytes,
            code="COLLECTOR_REPORT_INVALID",
        )
    )
    for value in (
        controller_build_sha256,
        browser_binary_sha256,
        node_binary_sha256,
    ):
        _require_sha256(
            value,
            code="COLLECTOR_LOCAL_OPERATOR_BINDING_INVALID",
        )
    core["schema_version"] = LOCAL_OPERATOR_COLLECTOR_SCHEMA_VERSION
    core["formal_validation_eligible"] = False
    core["evidence_class"] = "local_operator_observation"
    core["acceptance_scope"] = "technical_observation_only"
    core["local_executor"] = {
        "controller_build_sha256": controller_build_sha256,
        "browser_binary_sha256": browser_binary_sha256,
        "node_binary_sha256": node_binary_sha256,
    }
    return _canonical_json(core) + b"\n"


def _file_identity_sha256(
    filename: str,
    identity: tuple[int, ...],
) -> str:
    return _sha256_bytes(
        _canonical_json(
            {
                "filename": filename,
                "identity": list(identity),
            }
        )
    )


def _secure_transaction_file(
    metadata: os.stat_result,
    *,
    require_bytes: bool,
    allow_multiple_links: bool,
) -> bool:
    size_valid = (
        0 < metadata.st_size <= MAX_PRIVATE_JSON_BYTES
        if require_bytes
        else metadata.st_size <= MAX_PRIVATE_JSON_BYTES
    )
    links_valid = (
        metadata.st_nlink >= 1
        if allow_multiple_links
        else metadata.st_nlink == 1
    )
    return (
        stat.S_ISREG(metadata.st_mode)
        and not stat.S_ISLNK(metadata.st_mode)
        and links_valid
        and stat.S_IMODE(metadata.st_mode) == 0o600
        and metadata.st_uid == os.getuid()
        and size_valid
    )


def _assert_parent_identity(
    parent: Path,
    parent_fd: int,
    parent_identity: tuple[int, ...],
) -> None:
    try:
        opened = os.fstat(parent_fd)
        supplied = parent.lstat()
        resolved = parent.resolve(strict=True).lstat()
    except OSError:
        raise CollectorError("COLLECTOR_FILE_UNSAFE") from None
    if (
        not _secure_parent(opened)
        or not _secure_parent(supplied)
        or not _secure_parent(resolved)
        or _directory_identity(opened) != parent_identity
        or _directory_identity(supplied) != parent_identity
        or _directory_identity(resolved) != parent_identity
    ):
        raise CollectorError("COLLECTOR_FILE_UNSAFE")


def _ensure_outputs_absent(
    parent: Path,
    parent_identity: tuple[int, ...],
) -> None:
    """Compatibility preflight hook that pins the private parent identity.

    Existing exact outputs are intentionally not rejected here: under the
    transaction lock they can represent an interrupted identical commit.
    """

    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise CollectorError("COLLECTOR_WRITE_FAILED")
    parent_fd: int | None = None
    try:
        parent_fd = os.open(
            parent,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | nofollow,
        )
        _assert_parent_identity(parent, parent_fd, parent_identity)
    except CollectorError:
        raise
    except OSError:
        raise CollectorError("COLLECTOR_WRITE_FAILED") from None
    finally:
        if parent_fd is not None:
            try:
                os.close(parent_fd)
            except OSError:
                pass


def _require_guard_lock_or_clean_start(
    parent: Path,
    parent_identity: tuple[int, ...],
) -> None:
    """Distinguish a clean not-yet-started run from lockless foreign residue."""

    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise CollectorError("COLLECTOR_FILE_UNSAFE")
    parent_fd: int | None = None
    try:
        parent_fd = os.open(
            parent,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | nofollow,
        )
        _assert_parent_identity(parent, parent_fd, parent_identity)
        try:
            os.stat(
                _TRANSACTION_LOCK_FILENAME,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
            return
        except FileNotFoundError:
            pass
        except OSError:
            raise CollectorError("COLLECTOR_FILE_UNSAFE") from None
        fixed_names = {
            COLLECTOR_REPORT_FILENAME,
            PROBE_REPORT_FILENAME,
            COLLECTOR_COMMIT_MARKER_FILENAME,
        }
        try:
            names = os.listdir(parent_fd)
        except OSError:
            raise CollectorError("COLLECTOR_FILE_UNSAFE") from None
        suspicious = any(
            name in fixed_names
            or any(name.startswith(f".{fixed}.") for fixed in fixed_names)
            for name in names
        )
        if suspicious:
            # A writer may have created the lock immediately after the first
            # lookup and then published a stage.  Recheck before classifying
            # residue as foreign; the subsequent nonblocking flock resolves
            # that race as BUSY or reads the completed state.
            try:
                os.stat(
                    _TRANSACTION_LOCK_FILENAME,
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
                return
            except FileNotFoundError:
                pass
            except OSError:
                raise CollectorError("COLLECTOR_FILE_UNSAFE") from None
            raise CollectorError("COLLECTOR_REPORT_INVALID")
        raise CollectorError("COLLECTOR_COMMIT_INCOMPLETE")
    except CollectorError:
        raise
    except OSError:
        raise CollectorError("COLLECTOR_FILE_UNSAFE") from None
    finally:
        if parent_fd is not None:
            try:
                os.close(parent_fd)
            except OSError:
                pass


@contextmanager
def _collector_transaction_lock(
    parent: Path,
    parent_identity: tuple[int, ...],
    *,
    exclusive: bool,
    create: bool,
) -> Iterator[int]:
    """Hold the one controlled lock while yielding an identity-pinned dirfd."""

    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise CollectorError("COLLECTOR_WRITE_FAILED")
    parent_fd: int | None = None
    lock_fd: int | None = None
    created = False
    try:
        parent_fd = os.open(
            parent,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | nofollow,
        )
        _assert_parent_identity(parent, parent_fd, parent_identity)
        if create:
            try:
                lock_fd = os.open(
                    _TRANSACTION_LOCK_FILENAME,
                    os.O_RDWR
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_CLOEXEC", 0)
                    | nofollow,
                    0o600,
                    dir_fd=parent_fd,
                )
                created = True
            except FileExistsError:
                lock_fd = None
        if lock_fd is None:
            try:
                lock_fd = os.open(
                    _TRANSACTION_LOCK_FILENAME,
                    os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | nofollow,
                    dir_fd=parent_fd,
                )
            except FileNotFoundError:
                if not create:
                    raise CollectorError(
                        _TRANSACTION_NOT_STARTED_ERROR
                    ) from None
                raise
        opened_lock = os.fstat(lock_fd)
        if not (
            stat.S_ISREG(opened_lock.st_mode)
            and not stat.S_ISLNK(opened_lock.st_mode)
            and opened_lock.st_nlink == 1
            and stat.S_IMODE(opened_lock.st_mode) == 0o600
            and opened_lock.st_uid == os.getuid()
            and opened_lock.st_size == 0
        ):
            raise CollectorError("COLLECTOR_FILE_UNSAFE")
        if created:
            os.fsync(lock_fd)
            os.fsync(parent_fd)
        try:
            fcntl.flock(
                lock_fd,
                (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
                | fcntl.LOCK_NB,
            )
        except OSError as error:
            if error.errno in {errno.EACCES, errno.EAGAIN}:
                raise CollectorError(
                    COLLECTOR_TRANSACTION_BUSY_ERROR
                ) from None
            raise
        path_lock = os.stat(
            _TRANSACTION_LOCK_FILENAME,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        if _file_identity(path_lock) != _file_identity(opened_lock):
            raise CollectorError("COLLECTOR_FILE_UNSAFE")
        _assert_parent_identity(parent, parent_fd, parent_identity)
        yield parent_fd
        _assert_parent_identity(parent, parent_fd, parent_identity)
    except CollectorError:
        raise
    except (OSError, ValueError):
        raise CollectorError("COLLECTOR_WRITE_FAILED") from None
    finally:
        if lock_fd is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(lock_fd)
            except OSError:
                pass
        if parent_fd is not None:
            try:
                os.close(parent_fd)
            except OSError:
                pass


def _read_locked_bytes(
    parent_fd: int,
    filename: str,
    *,
    allow_multiple_links: bool,
) -> tuple[bytes, tuple[int, ...]]:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise CollectorError("COLLECTOR_FILE_UNSAFE")
    file_fd: int | None = None
    try:
        before = os.stat(filename, dir_fd=parent_fd, follow_symlinks=False)
        if not _secure_transaction_file(
            before,
            require_bytes=True,
            allow_multiple_links=allow_multiple_links,
        ):
            raise CollectorError("COLLECTOR_FILE_UNSAFE")
        file_fd = os.open(
            filename,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | nofollow,
            dir_fd=parent_fd,
        )
        opened = os.fstat(file_fd)
        if (
            _file_identity(opened) != _file_identity(before)
            or not _secure_transaction_file(
                opened,
                require_bytes=True,
                allow_multiple_links=allow_multiple_links,
            )
        ):
            raise CollectorError("COLLECTOR_FILE_UNSAFE")
        chunks: list[bytes] = []
        remaining = opened.st_size
        while remaining:
            chunk = os.read(file_fd, min(remaining, 64 * 1024))
            if not chunk:
                raise CollectorError("COLLECTOR_FILE_UNSAFE")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(file_fd, 1):
            raise CollectorError("COLLECTOR_FILE_UNSAFE")
        after = os.fstat(file_fd)
        path_after = os.stat(
            filename,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        if (
            _file_identity(after) != _file_identity(opened)
            or _file_identity(path_after) != _file_identity(opened)
            or not _secure_transaction_file(
                after,
                require_bytes=True,
                allow_multiple_links=allow_multiple_links,
            )
        ):
            raise CollectorError("COLLECTOR_FILE_UNSAFE")
        return b"".join(chunks), _file_identity(after)
    except CollectorError:
        raise
    except OSError:
        raise CollectorError("COLLECTOR_FILE_UNSAFE") from None
    finally:
        if file_fd is not None:
            try:
                os.close(file_fd)
            except OSError:
                pass


def _stage_prefix(filename: str, digest: str) -> str:
    return f".{filename}.{digest}."


def _is_recognized_stage_name(
    name: object,
    *,
    filename: str,
    digest: str,
) -> bool:
    if type(name) is not str:
        return False
    prefix = _stage_prefix(filename, digest)
    if not name.startswith(prefix) or not name.endswith(_STAGE_SUFFIX):
        return False
    nonce = name[len(prefix) : -len(_STAGE_SUFFIX)]
    return len(nonce) == 32 and all(
        character in "0123456789abcdef" for character in nonce
    )


def _has_exact_linked_transaction_stage(
    parent_fd: int,
    *,
    filename: str,
    raw: bytes,
    final_identity: tuple[int, ...],
) -> bool:
    """Recognize only the writer's one-link-before-cleanup crash state."""

    if final_identity[4] != 2:
        return False
    digest = _sha256_bytes(raw)
    matches = 0
    try:
        names = os.listdir(parent_fd)
    except OSError:
        raise CollectorError("COLLECTOR_FILE_UNSAFE") from None
    for name in names:
        if not _is_recognized_stage_name(
            name,
            filename=filename,
            digest=digest,
        ):
            continue
        try:
            metadata = os.stat(
                name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            continue
        except OSError:
            raise CollectorError("COLLECTOR_FILE_UNSAFE") from None
        if (
            (metadata.st_dev, metadata.st_ino)
            == (final_identity[0], final_identity[1])
            and _file_identity(metadata) == final_identity
            and _secure_transaction_file(
                metadata,
                require_bytes=True,
                allow_multiple_links=True,
            )
        ):
            matches += 1
    return matches == 1


def _read_optional_transaction_json(
    parent_fd: int,
    *,
    filename: str,
) -> tuple[
    bytes,
    Mapping[str, object],
    tuple[int, ...],
    bool,
] | None:
    try:
        os.stat(filename, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError:
        raise CollectorError("COLLECTOR_FILE_UNSAFE") from None
    raw, identity = _read_locked_bytes(
        parent_fd,
        filename,
        allow_multiple_links=True,
    )
    if identity[4] == 1:
        transient = False
    elif _has_exact_linked_transaction_stage(
        parent_fd,
        filename=filename,
        raw=raw,
        final_identity=identity,
    ):
        transient = True
    else:
        raise CollectorError("COLLECTOR_FILE_UNSAFE")
    return (
        raw,
        _decode_json_mapping(raw, code="COLLECTOR_REPORT_INVALID"),
        identity,
        transient,
    )


def _cleanup_linked_transaction_stages(
    parent_fd: int,
    *,
    filename: str,
    digest: str,
    final_identity: tuple[int, ...],
) -> None:
    prefix = _stage_prefix(filename, digest)
    try:
        names = os.listdir(parent_fd)
    except OSError:
        raise CollectorError("COLLECTOR_FILE_UNSAFE") from None
    changed = False
    for name in names:
        if (
            type(name) is not str
            or not name.startswith(prefix)
            or not name.endswith(_STAGE_SUFFIX)
        ):
            continue
        try:
            metadata = os.stat(
                name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            continue
        except OSError:
            raise CollectorError("COLLECTOR_FILE_UNSAFE") from None
        if (
            (metadata.st_dev, metadata.st_ino)
            == (final_identity[0], final_identity[1])
            and _secure_transaction_file(
                metadata,
                require_bytes=True,
                allow_multiple_links=True,
            )
        ):
            try:
                os.unlink(name, dir_fd=parent_fd)
            except OSError:
                raise CollectorError("COLLECTOR_WRITE_FAILED") from None
            changed = True
    if changed:
        try:
            os.fsync(parent_fd)
        except OSError:
            raise CollectorError("COLLECTOR_WRITE_FAILED") from None


def _existing_exact_identity(
    parent_fd: int,
    *,
    filename: str,
    data: bytes,
) -> tuple[int, ...] | None:
    try:
        raw, identity = _read_locked_bytes(
            parent_fd,
            filename,
            allow_multiple_links=True,
        )
    except CollectorError as error:
        try:
            os.stat(filename, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return None
        except OSError:
            raise CollectorError("COLLECTOR_FILE_UNSAFE") from None
        if error.code == "COLLECTOR_FILE_UNSAFE":
            raise
        raise CollectorError("COLLECTOR_REPORT_EXISTS") from None
    if raw != data:
        raise CollectorError("COLLECTOR_REPORT_EXISTS")
    if identity[4] > 1:
        _cleanup_linked_transaction_stages(
            parent_fd,
            filename=filename,
            digest=_sha256_bytes(data),
            final_identity=identity,
        )
        raw, identity = _read_locked_bytes(
            parent_fd,
            filename,
            allow_multiple_links=False,
        )
        if raw != data:
            raise CollectorError("COLLECTOR_REPORT_EXISTS")
    return identity


def _write_staged_file(
    parent_fd: int,
    *,
    filename: str,
    data: bytes,
) -> tuple[str, tuple[int, ...]]:
    if (
        filename
        not in {
            COLLECTOR_REPORT_FILENAME,
            PROBE_REPORT_FILENAME,
            COLLECTOR_COMMIT_MARKER_FILENAME,
        }
        or not data
        or len(data) > MAX_PRIVATE_JSON_BYTES
    ):
        raise CollectorError("COLLECTOR_WRITE_POLICY_INVALID")
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise CollectorError("COLLECTOR_WRITE_FAILED")
    digest = _sha256_bytes(data)
    stage_name: str | None = None
    file_fd: int | None = None
    try:
        for _ in range(32):
            candidate = (
                f"{_stage_prefix(filename, digest)}"
                f"{secrets.token_hex(16)}{_STAGE_SUFFIX}"
            )
            try:
                file_fd = os.open(
                    candidate,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_CLOEXEC", 0)
                    | nofollow,
                    0o600,
                    dir_fd=parent_fd,
                )
                stage_name = candidate
                break
            except FileExistsError:
                continue
        if file_fd is None or stage_name is None:
            raise CollectorError("COLLECTOR_WRITE_FAILED")
        opened = os.fstat(file_fd)
        if not _secure_file(opened, require_bytes=False):
            raise CollectorError("COLLECTOR_FILE_UNSAFE")
        offset = 0
        while offset < len(data):
            written = os.write(file_fd, data[offset:])
            if written <= 0:
                raise CollectorError("COLLECTOR_WRITE_FAILED")
            offset += written
        os.fsync(file_fd)
        after = os.fstat(file_fd)
        path_after = os.stat(
            stage_name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        if (
            not _secure_file(after, require_bytes=True)
            or _file_identity(after) != _file_identity(path_after)
            or after.st_size != len(data)
        ):
            raise CollectorError("COLLECTOR_WRITE_FAILED")
        os.fsync(parent_fd)
        return stage_name, _file_identity(after)
    except CollectorError:
        raise
    except OSError:
        raise CollectorError("COLLECTOR_WRITE_FAILED") from None
    finally:
        if file_fd is not None:
            try:
                os.close(file_fd)
            except OSError:
                pass


def _publish_staged_file(
    parent_fd: int,
    *,
    filename: str,
    data: bytes,
    stage_name: str,
    stage_identity: tuple[int, ...],
) -> tuple[int, ...]:
    try:
        current_stage = os.stat(
            stage_name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        if (
            _file_identity(current_stage) != stage_identity
            or not _secure_file(current_stage, require_bytes=True)
        ):
            raise CollectorError("COLLECTOR_FILE_UNSAFE")
        try:
            os.link(
                stage_name,
                filename,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileExistsError:
            identity = _existing_exact_identity(
                parent_fd,
                filename=filename,
                data=data,
            )
            if identity is None:
                raise CollectorError("COLLECTOR_WRITE_FAILED")
            return identity
        linked = os.stat(
            filename,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        if not _same_object(linked, current_stage):
            raise CollectorError("COLLECTOR_WRITE_FAILED")
        os.fsync(parent_fd)
        # This exact stage was created by the current invocation.  No other
        # residue is removed; interrupted linked stages are recovered only by
        # exact inode identity in ``_existing_exact_identity``.
        stage_after_link = os.stat(
            stage_name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        if not _same_object(stage_after_link, linked):
            raise CollectorError("COLLECTOR_FILE_UNSAFE")
        os.unlink(stage_name, dir_fd=parent_fd)
        os.fsync(parent_fd)
        raw, identity = _read_locked_bytes(
            parent_fd,
            filename,
            allow_multiple_links=False,
        )
        if raw != data:
            raise CollectorError("COLLECTOR_WRITE_FAILED")
        return identity
    except CollectorError:
        raise
    except OSError:
        raise CollectorError("COLLECTOR_WRITE_FAILED") from None


def _publish_exact_file(
    parent_fd: int,
    *,
    filename: str,
    data: bytes,
) -> tuple[int, ...]:
    existing = _existing_exact_identity(
        parent_fd,
        filename=filename,
        data=data,
    )
    if existing is not None:
        return existing
    stage_name, stage_identity = _write_staged_file(
        parent_fd,
        filename=filename,
        data=data,
    )
    return _publish_staged_file(
        parent_fd,
        filename=filename,
        data=data,
        stage_name=stage_name,
        stage_identity=stage_identity,
    )


def _build_commit_marker(
    *,
    request_fingerprint_sha256: str,
    collector_bytes: bytes,
    collector_identity: tuple[int, ...],
    probe_bytes: bytes,
    probe_identity: tuple[int, ...],
    attestation_key: bytes,
) -> bytes:
    unsigned: dict[str, object] = {
        "schema_version": LEGACY_COLLECTOR_COMMIT_SCHEMA_VERSION,
        "request_fingerprint_sha256": request_fingerprint_sha256,
        "collector": {
            "filename": COLLECTOR_REPORT_FILENAME,
            "sha256": _sha256_bytes(collector_bytes),
            "file_identity_sha256": _file_identity_sha256(
                COLLECTOR_REPORT_FILENAME,
                collector_identity,
            ),
        },
        "probe": {
            "filename": PROBE_REPORT_FILENAME,
            "sha256": _sha256_bytes(probe_bytes),
            "file_identity_sha256": _file_identity_sha256(
                PROBE_REPORT_FILENAME,
                probe_identity,
            ),
        },
    }
    fingerprinted = {
        **unsigned,
        "pair_commit_fingerprint_sha256": _sha256_bytes(
            _canonical_json(unsigned)
        ),
    }
    marker = {
        **fingerprinted,
        "pair_commit_hmac_sha256": _commit_attestation_hmac(
            attestation_key,
            fingerprinted,
        ),
    }
    return _canonical_json(marker) + b"\n"


def _build_formal_commit_marker(
    *,
    request_fingerprint_sha256: str,
    collector_bytes: bytes,
    collector_identity: tuple[int, ...],
    probe_bytes: bytes,
    probe_identity: tuple[int, ...],
) -> bytes:
    """Bind the two final files without claiming signing authority.

    The SSHSIG embedded in ``collector_bytes`` is the sole provenance proof.
    This marker is only an fsynced local transaction boundary.
    """

    unsigned: dict[str, object] = {
        "schema_version": COLLECTOR_COMMIT_SCHEMA_VERSION,
        "request_fingerprint_sha256": request_fingerprint_sha256,
        "collector": {
            "filename": COLLECTOR_REPORT_FILENAME,
            "sha256": _sha256_bytes(collector_bytes),
            "file_identity_sha256": _file_identity_sha256(
                COLLECTOR_REPORT_FILENAME,
                collector_identity,
            ),
        },
        "probe": {
            "filename": PROBE_REPORT_FILENAME,
            "sha256": _sha256_bytes(probe_bytes),
            "file_identity_sha256": _file_identity_sha256(
                PROBE_REPORT_FILENAME,
                probe_identity,
            ),
        },
    }
    return _canonical_json(
        {
            **unsigned,
            "pair_commit_fingerprint_sha256": _sha256_bytes(
                _canonical_json(unsigned)
            ),
        }
    ) + b"\n"


def _build_local_operator_commit_marker(
    *,
    request_fingerprint_sha256: str,
    collector_bytes: bytes,
    collector_identity: tuple[int, ...],
    probe_bytes: bytes,
    probe_identity: tuple[int, ...],
) -> bytes:
    """Create an fsynced local pair boundary, not a signature or attestation."""

    unsigned: dict[str, object] = {
        "schema_version": LOCAL_OPERATOR_COMMIT_SCHEMA_VERSION,
        "request_fingerprint_sha256": request_fingerprint_sha256,
        "collector": {
            "filename": COLLECTOR_REPORT_FILENAME,
            "sha256": _sha256_bytes(collector_bytes),
            "file_identity_sha256": _file_identity_sha256(
                COLLECTOR_REPORT_FILENAME,
                collector_identity,
            ),
        },
        "probe": {
            "filename": PROBE_REPORT_FILENAME,
            "sha256": _sha256_bytes(probe_bytes),
            "file_identity_sha256": _file_identity_sha256(
                PROBE_REPORT_FILENAME,
                probe_identity,
            ),
        },
    }
    return _canonical_json(
        {
            **unsigned,
            "pair_commit_fingerprint_sha256": _sha256_bytes(
                _canonical_json(unsigned)
            ),
        }
    ) + b"\n"


def _validate_signed_runtime_report(
    *,
    request_payload: object,
    runtime_payload: object,
    probe_runtime_payload: object,
    collected_at: datetime,
    expectation: ProbeExpectation,
) -> str:
    code = "COLLECTOR_REPORT_INVALID"
    request_keys = frozenset(
        {
            "schema_version",
            "report_schema_version",
            "created_at",
            "request_fingerprint_sha256",
        }
    )
    if type(request_payload) is not dict or frozenset(request_payload) not in {
        request_keys,
        request_keys | {"request_sha256"},
    }:
        raise CollectorError(code)
    request = request_payload
    if (
        request["schema_version"] != PROBE_REQUEST_SCHEMA_VERSION
        or request["report_schema_version"] != PROBE_SCHEMA_VERSION
        or not _is_sha256(request["request_fingerprint_sha256"])
        or (
            "request_sha256" in request
            and not _is_sha256(request["request_sha256"])
        )
    ):
        raise CollectorError(code)
    request_created_at = _parse_timestamp(request["created_at"], code=code)
    runtime = _exact_mapping(
        runtime_payload,
        frozenset(
            {
                "sidecar_container_name",
                "window_started_at",
                "window_ended_at",
                "request_fingerprint_sha256",
                "stability_elapsed_seconds",
                "chapter_audio_duration_seconds",
                "request_to_ready_seconds",
                "peak_memory_bytes",
                "host_paging_observed",
                "pageout_delta",
                "swapout_delta",
                "memory_baseline_median_bytes",
                "memory_tail_median_bytes",
                "memory_growth_bytes",
                "memory_growth_limit_bytes",
                "sidecar_memory_growth_observed",
                "qwenpaw_slowdown_observed",
                "sidecar_restart_count",
                "health_failure_count",
                "metric_sample_count",
                "metric_samples",
                "metric_sample_chain_sha256",
                "metrics_summary_sha256",
            }
        ),
        code=code,
    )
    probe_runtime = _exact_mapping(
        probe_runtime_payload,
        frozenset(
            {
                "sidecar_container_name",
                "stability_elapsed_seconds",
                "chapter_audio_duration_seconds",
                "request_to_ready_seconds",
                "peak_memory_bytes",
                "host_paging_observed",
                "pageout_delta",
                "swapout_delta",
                "memory_baseline_median_bytes",
                "memory_tail_median_bytes",
                "memory_growth_bytes",
                "memory_growth_limit_bytes",
                "sidecar_memory_growth_observed",
                "qwenpaw_slowdown_observed",
                "sidecar_restart_count",
                "health_failure_count",
            }
        ),
        code=code,
    )
    started = _parse_timestamp(runtime["window_started_at"], code=code)
    ended = _parse_timestamp(runtime["window_ended_at"], code=code)
    elapsed = (ended - started).total_seconds()
    supplied_elapsed = _number(
        runtime["stability_elapsed_seconds"],
        positive=True,
        code=code,
    )
    _number(
        runtime["chapter_audio_duration_seconds"],
        positive=True,
        code=code,
    )
    _number(
        runtime["request_to_ready_seconds"],
        positive=False,
        code=code,
    )
    raw_samples = runtime["metric_samples"]
    if type(raw_samples) is not list:
        raise CollectorError(code)
    samples: list[SidecarMetricSampleDigest] = []
    for raw_sample in raw_samples:
        sample = _exact_mapping(
            raw_sample,
            frozenset(
                {
                    "observed_at",
                    "sample_sha256",
                    "resident_memory_bytes",
                }
            ),
            code=code,
        )
        samples.append(
            SidecarMetricSampleDigest(
                observed_at=_parse_timestamp(sample["observed_at"], code=code),
                sample_sha256=_require_sha256(
                    sample["sample_sha256"],
                    code=code,
                ),
                resident_memory_bytes=(
                    sample["resident_memory_bytes"]
                    if type(sample["resident_memory_bytes"]) is int
                    and sample["resident_memory_bytes"] >= 0
                    else -1
                ),
            )
        )
    if (
        runtime["sidecar_container_name"]
        != EXPECTED_SIDECAR_CONTAINER_NAME
        or runtime["request_fingerprint_sha256"]
        != request["request_fingerprint_sha256"]
        or started < request_created_at
        or ended != collected_at
        or elapsed < expectation.required_stability_seconds
        or supplied_elapsed != elapsed
        or type(runtime["peak_memory_bytes"]) is not int
        or runtime["peak_memory_bytes"] < 0
        or not samples
        or any(sample.resident_memory_bytes < 0 for sample in samples)
        or runtime["peak_memory_bytes"]
        != max(sample.resident_memory_bytes for sample in samples)
        or type(runtime["host_paging_observed"]) is not bool
        or type(runtime["pageout_delta"]) is not int
        or runtime["pageout_delta"] < 0
        or type(runtime["swapout_delta"]) is not int
        or runtime["swapout_delta"] < 0
        or type(runtime["memory_baseline_median_bytes"]) is not int
        or runtime["memory_baseline_median_bytes"] < 0
        or type(runtime["memory_tail_median_bytes"]) is not int
        or runtime["memory_tail_median_bytes"] < 0
        or type(runtime["memory_growth_bytes"]) is not int
        or runtime["memory_growth_bytes"] < 0
        or type(runtime["memory_growth_limit_bytes"]) is not int
        or runtime["memory_growth_limit_bytes"] < 0
        or type(runtime["sidecar_memory_growth_observed"]) is not bool
        or type(runtime["qwenpaw_slowdown_observed"]) is not bool
        or type(probe_runtime["host_paging_observed"]) is not bool
        or type(probe_runtime["pageout_delta"]) is not int
        or probe_runtime["pageout_delta"] < 0
        or type(probe_runtime["swapout_delta"]) is not int
        or probe_runtime["swapout_delta"] < 0
        or type(probe_runtime["memory_baseline_median_bytes"]) is not int
        or probe_runtime["memory_baseline_median_bytes"] < 0
        or type(probe_runtime["memory_tail_median_bytes"]) is not int
        or probe_runtime["memory_tail_median_bytes"] < 0
        or type(probe_runtime["memory_growth_bytes"]) is not int
        or probe_runtime["memory_growth_bytes"] < 0
        or type(probe_runtime["memory_growth_limit_bytes"]) is not int
        or probe_runtime["memory_growth_limit_bytes"] < 0
        or type(probe_runtime["sidecar_memory_growth_observed"]) is not bool
        or type(probe_runtime["qwenpaw_slowdown_observed"]) is not bool
        or type(runtime["sidecar_restart_count"]) is not int
        or runtime["sidecar_restart_count"] != 0
        or type(runtime["health_failure_count"]) is not int
        or runtime["health_failure_count"] != 0
        or type(runtime["metric_sample_count"]) is not int
        or runtime["metric_sample_count"] != len(samples)
        or len(samples) != FIXED_MIN_METRIC_SAMPLE_COUNT
        or not _is_sha256(runtime["metric_sample_chain_sha256"])
        or not _is_sha256(runtime["metrics_summary_sha256"])
    ):
        raise CollectorError(code)
    (
        measured_baseline,
        measured_tail,
        measured_growth,
        measured_growth_limit,
        measured_growth_observed,
    ) = _derive_memory_summary(tuple(samples), code=code)
    measured_host_paging = (
        runtime["pageout_delta"] > 0 or runtime["swapout_delta"] > 0
    )
    expected_chain = build_sidecar_metric_sample_chain_sha256(
        request_fingerprint_sha256=str(
            request["request_fingerprint_sha256"]
        ),
        window_started_at=started,
        window_ended_at=ended,
        metrics_summary_sha256=str(runtime["metrics_summary_sha256"]),
        samples=tuple(samples),
    )
    projection_keys = (
        "sidecar_container_name",
        "stability_elapsed_seconds",
        "chapter_audio_duration_seconds",
        "request_to_ready_seconds",
        "peak_memory_bytes",
        "host_paging_observed",
        "pageout_delta",
        "swapout_delta",
        "memory_baseline_median_bytes",
        "memory_tail_median_bytes",
        "memory_growth_bytes",
        "memory_growth_limit_bytes",
        "sidecar_memory_growth_observed",
        "qwenpaw_slowdown_observed",
        "sidecar_restart_count",
        "health_failure_count",
    )
    if (
        not hmac.compare_digest(
            str(runtime["metric_sample_chain_sha256"]),
            expected_chain,
        )
        or runtime["host_paging_observed"] is not measured_host_paging
        or runtime["memory_baseline_median_bytes"] != measured_baseline
        or runtime["memory_tail_median_bytes"] != measured_tail
        or runtime["memory_growth_bytes"] != measured_growth
        or runtime["memory_growth_limit_bytes"] != measured_growth_limit
        or runtime["sidecar_memory_growth_observed"]
        is not measured_growth_observed
        or any(probe_runtime[key] != runtime[key] for key in projection_keys)
    ):
        raise CollectorError(code)
    return str(request["request_fingerprint_sha256"])


def _validate_untrusted_collector_candidate(
    *,
    collector_raw: bytes,
    collector: Mapping[str, object],
    probe_raw: bytes | None,
    probe: Mapping[str, object] | None,
    expectation: ProbeExpectation,
    now: datetime | None,
) -> str | None:
    """Validate candidate structure without granting controller provenance."""

    code = "COLLECTOR_REPORT_INVALID"
    detailed = _exact_mapping(
        collector,
        frozenset(
            {
                "schema_version",
                "collected_at",
                "formal_validation_eligible",
                "source",
                "request",
                "binding",
                "browser",
                "runtime",
                "probe_report_sha256",
                "collector_report_fingerprint_sha256",
                "controller_attestation_hmac_sha256",
            }
        ),
        code=code,
    )
    source = _exact_mapping(
        detailed["source"],
        frozenset({"controller_id", "page_url", "synthetic"}),
        code=code,
    )
    collected_at = _parse_timestamp(detailed["collected_at"], code=code)
    probe_digest = _require_sha256(
        detailed["probe_report_sha256"],
        code=code,
    )
    signed = dict(detailed)
    signature = signed.pop("controller_attestation_hmac_sha256")
    fingerprinted = dict(signed)
    fingerprint = fingerprinted.pop(
        "collector_report_fingerprint_sha256"
    )
    if (
        detailed["schema_version"] != LEGACY_COLLECTOR_SCHEMA_VERSION
        or detailed["formal_validation_eligible"] is not True
        or source
        != {
            "controller_id": FIXED_CONTROLLER_ID,
            "page_url": FIXED_PUBLIC_PAGE_URL,
            "synthetic": False,
        }
        or detailed["binding"]
        != expectation.report_binding(collected_at=collected_at)
        or not _is_sha256(signature)
        or not _is_sha256(fingerprint)
        or fingerprint != _sha256_bytes(_canonical_json(fingerprinted))
        or _sha256_bytes(collector_raw)
        != _sha256_bytes(_canonical_json(detailed) + b"\n")
    ):
        raise CollectorError(code)
    if probe_raw is None or probe is None:
        return None
    if (
        probe_digest != _sha256_bytes(probe_raw)
        or probe.get("schema_version") != PROBE_SCHEMA_VERSION
        or probe.get("collected_at") != detailed["collected_at"]
        or probe.get("binding") != detailed["binding"]
    ):
        raise CollectorError(code)
    request_fingerprint = _validate_signed_runtime_report(
        request_payload=detailed["request"],
        runtime_payload=detailed["runtime"],
        probe_runtime_payload=probe.get("runtime"),
        collected_at=collected_at,
        expectation=expectation,
    )
    StrictJsonChapterE2EProbeLoader().load_bytes(
        probe_raw,
        expectation=expectation,
        now=now,
    )
    return request_fingerprint


def _validate_untrusted_commit_marker(
    *,
    marker: Mapping[str, object],
    request_fingerprint_sha256: str,
    collector_raw: bytes,
    collector_identity: tuple[int, ...],
    probe_raw: bytes,
    probe_identity: tuple[int, ...],
) -> None:
    """Validate exact committed identities, but never trust the legacy HMAC."""

    code = "COLLECTOR_REPORT_INVALID"
    committed = _exact_mapping(
        marker,
        frozenset(
            {
                "schema_version",
                "request_fingerprint_sha256",
                "collector",
                "probe",
                "pair_commit_fingerprint_sha256",
                "pair_commit_hmac_sha256",
            }
        ),
        code=code,
    )
    collector_commit = _exact_mapping(
        committed["collector"],
        frozenset({"filename", "sha256", "file_identity_sha256"}),
        code=code,
    )
    probe_commit = _exact_mapping(
        committed["probe"],
        frozenset({"filename", "sha256", "file_identity_sha256"}),
        code=code,
    )
    unsigned = {
        "schema_version": committed["schema_version"],
        "request_fingerprint_sha256": committed[
            "request_fingerprint_sha256"
        ],
        "collector": collector_commit,
        "probe": probe_commit,
    }
    if (
        committed["schema_version"]
        != LEGACY_COLLECTOR_COMMIT_SCHEMA_VERSION
        or committed["request_fingerprint_sha256"]
        != request_fingerprint_sha256
        or collector_commit
        != {
            "filename": COLLECTOR_REPORT_FILENAME,
            "sha256": _sha256_bytes(collector_raw),
            "file_identity_sha256": _file_identity_sha256(
                COLLECTOR_REPORT_FILENAME,
                collector_identity,
            ),
        }
        or probe_commit
        != {
            "filename": PROBE_REPORT_FILENAME,
            "sha256": _sha256_bytes(probe_raw),
            "file_identity_sha256": _file_identity_sha256(
                PROBE_REPORT_FILENAME,
                probe_identity,
            ),
        }
        or committed["pair_commit_fingerprint_sha256"]
        != _sha256_bytes(_canonical_json(unsigned))
        or not _is_sha256(committed["pair_commit_hmac_sha256"])
    ):
        raise CollectorError(code)


def _validate_formal_commit_marker(
    *,
    marker: Mapping[str, object],
    request_fingerprint_sha256: str,
    collector_raw: bytes,
    collector_identity: tuple[int, ...],
    probe_raw: bytes,
    probe_identity: tuple[int, ...],
    expected_schema_version: str = COLLECTOR_COMMIT_SCHEMA_VERSION,
) -> None:
    code = "COLLECTOR_REPORT_INVALID"
    committed = _exact_mapping(
        marker,
        frozenset(
            {
                "schema_version",
                "request_fingerprint_sha256",
                "collector",
                "probe",
                "pair_commit_fingerprint_sha256",
            }
        ),
        code=code,
    )
    collector_commit = _exact_mapping(
        committed["collector"],
        frozenset({"filename", "sha256", "file_identity_sha256"}),
        code=code,
    )
    probe_commit = _exact_mapping(
        committed["probe"],
        frozenset({"filename", "sha256", "file_identity_sha256"}),
        code=code,
    )
    unsigned = {
        "schema_version": committed["schema_version"],
        "request_fingerprint_sha256": committed[
            "request_fingerprint_sha256"
        ],
        "collector": collector_commit,
        "probe": probe_commit,
    }
    if (
        committed["schema_version"] != expected_schema_version
        or committed["request_fingerprint_sha256"]
        != request_fingerprint_sha256
        or collector_commit
        != {
            "filename": COLLECTOR_REPORT_FILENAME,
            "sha256": _sha256_bytes(collector_raw),
            "file_identity_sha256": _file_identity_sha256(
                COLLECTOR_REPORT_FILENAME,
                collector_identity,
            ),
        }
        or probe_commit
        != {
            "filename": PROBE_REPORT_FILENAME,
            "sha256": _sha256_bytes(probe_raw),
            "file_identity_sha256": _file_identity_sha256(
                PROBE_REPORT_FILENAME,
                probe_identity,
            ),
        }
        or committed["pair_commit_fingerprint_sha256"]
        != _sha256_bytes(_canonical_json(unsigned))
    ):
        raise CollectorError(code)


def _validate_formal_collector_candidate(
    *,
    collector_raw: bytes,
    collector: Mapping[str, object],
    probe_raw: bytes | None,
    probe: Mapping[str, object] | None,
    expectation: ProbeExpectation,
    now: datetime | None,
) -> tuple[str, BoundTechnicalProbe] | None:
    """Verify the v2 core, exact projection and fixed public SSHSIG."""

    code = "COLLECTOR_REPORT_INVALID"
    detailed = _exact_mapping(
        collector,
        frozenset(
            {
                "schema_version",
                "collected_at",
                "formal_validation_eligible",
                "source",
                "request",
                "binding",
                "browser",
                "runtime",
                "probe_report_sha256",
                "controller_authority",
            }
        ),
        code=code,
    )
    authority = _exact_mapping(
        detailed["controller_authority"],
        frozenset(
            {
                "report_binding",
                "report_binding_sha256",
                "report_binding_sshsig",
            }
        ),
        code=code,
    )
    core = dict(detailed)
    core.pop("controller_authority")
    core_bytes = _canonical_json(core) + b"\n"
    try:
        binding_bytes = _canonical_controller_json(
            authority["report_binding"]
        )
    except ControllerTrustError:
        raise CollectorError(code) from None
    source = _exact_mapping(
        core["source"],
        frozenset({"controller_id", "page_url", "synthetic"}),
        code=code,
    )
    collected_at = _parse_timestamp(core["collected_at"], code=code)
    if (
        core["schema_version"] != COLLECTOR_SCHEMA_VERSION
        or core["formal_validation_eligible"] is not True
        or source
        != {
            "controller_id": FIXED_CONTROLLER_ID,
            "page_url": FIXED_PUBLIC_PAGE_URL,
            "synthetic": False,
        }
        or core["binding"]
        != expectation.report_binding(collected_at=collected_at)
        or not _is_sha256(core["probe_report_sha256"])
        or authority["report_binding_sha256"]
        != _sha256_bytes(binding_bytes)
        or type(authority["report_binding_sshsig"]) is not str
        or _canonical_json(detailed) + b"\n" != collector_raw
    ):
        raise CollectorError(code)
    request = _exact_mapping(
        core["request"],
        frozenset(
            {
                "schema_version",
                "report_schema_version",
                "created_at",
                "request_fingerprint_sha256",
                "request_sha256",
            }
        ),
        code=code,
    )
    report_binding = _exact_mapping(
        authority["report_binding"],
        frozenset(
            {
                "schema_version",
                "signed_at",
                "preflight_payload_sha256",
                "run_fingerprint_sha256",
                "target_scope_sha256",
                "probe_request_sha256",
                "request_fingerprint_sha256",
                "automatic_edition_fingerprint_sha256",
                "manual_edition_fingerprint_sha256",
                "listening_output_hashes",
                "required_stability_milliseconds",
                "observed_captures",
                "window_started_at",
                "window_ended_at",
                "stability_elapsed_milliseconds",
                "metric_sample_count",
                "metric_sample_chain_sha256",
                "collector_report_sha256",
                "probe_report_sha256",
                "controller_id",
                "controller_build_sha256",
                "browser_binary_sha256",
                "signing_key_id",
                "signer_principal",
                "signature_namespace",
                "trust_policy_sha256",
                "allowed_signers_sha256",
            }
        ),
        code=code,
    )
    if probe_raw is None or probe is None:
        return None
    if (
        core["probe_report_sha256"] != _sha256_bytes(probe_raw)
        or probe.get("schema_version") != PROBE_SCHEMA_VERSION
        or probe.get("collected_at") != core["collected_at"]
        or probe.get("binding") != core["binding"]
    ):
        raise CollectorError(code)
    request_fingerprint = _validate_signed_runtime_report(
        request_payload=request,
        runtime_payload=core["runtime"],
        probe_runtime_payload=probe.get("runtime"),
        collected_at=collected_at,
        expectation=expectation,
    )
    try:
        report_expectation = ReportExpectation(
            preflight_payload_sha256=_require_sha256(
                report_binding["preflight_payload_sha256"], code=code
            ),
            run_fingerprint_sha256=expectation.run_fingerprint_sha256,
            target_scope_sha256=expectation.target_scope_sha256,
            probe_request_sha256=_require_sha256(
                request["request_sha256"], code=code
            ),
            request_fingerprint_sha256=request_fingerprint,
            automatic_edition_fingerprint_sha256=(
                expectation.automatic_edition_fingerprint_sha256
            ),
            manual_edition_fingerprint_sha256=(
                expectation.manual_edition_fingerprint_sha256
            ),
            listening_output_hashes=expectation.listening_output_hashes,
            # Frozen semantic: hash of the canonical unsigned core, not the
            # final collector-report file containing authority material.
            collector_report_sha256=_sha256_bytes(core_bytes),
            probe_report_sha256=_sha256_bytes(probe_raw),
        )
        verified = FixedControllerTrustVerifier().verify_report_binding(
            binding_bytes,
            str(authority["report_binding_sshsig"]).encode("ascii"),
            expectation=report_expectation,
            now=now,
        )
    except ControllerTrustError as error:
        if error.code == CONTROLLER_TRUST_ROOT_HOLD_ERROR:
            raise CollectorError(
                COLLECTOR_CONTROLLER_AUTHORITY_HOLD_ERROR
            ) from None
        if error.code == CONTROLLER_REPORT_BINDING_MISMATCH_ERROR:
            raise CollectorError(
                "COLLECTOR_CONTROLLER_BINDING_MISMATCH"
            ) from None
        raise CollectorError(
            "COLLECTOR_CONTROLLER_ATTESTATION_INVALID"
        ) from None
    except (UnicodeEncodeError, TypeError, ValueError):
        raise CollectorError(
            "COLLECTOR_CONTROLLER_ATTESTATION_INVALID"
        ) from None
    runtime = _exact_mapping(
        core["runtime"],
        frozenset(
            {
                "sidecar_container_name",
                "window_started_at",
                "window_ended_at",
                "request_fingerprint_sha256",
                "stability_elapsed_seconds",
                "chapter_audio_duration_seconds",
                "request_to_ready_seconds",
                "peak_memory_bytes",
                "host_paging_observed",
                "pageout_delta",
                "swapout_delta",
                "memory_baseline_median_bytes",
                "memory_tail_median_bytes",
                "memory_growth_bytes",
                "memory_growth_limit_bytes",
                "sidecar_memory_growth_observed",
                "qwenpaw_slowdown_observed",
                "sidecar_restart_count",
                "health_failure_count",
                "metric_sample_count",
                "metric_samples",
                "metric_sample_chain_sha256",
                "metrics_summary_sha256",
            }
        ),
        code=code,
    )
    browser = _exact_mapping(
        core["browser"],
        frozenset(
            {
                "observer_report_sha256",
                "captures",
                "screenshot_set_sha256",
                "console_set_sha256",
                "network_set_sha256",
                "range_etag",
                "interaction",
                "editor",
            }
        ),
        code=code,
    )
    signed_capture_projection = tuple(
        (
            item.target_css_width,
            item.target_css_height,
            item.assistant_mode_observed,
            item.screenshot_sha256,
            item.console_summary_sha256,
            item.network_summary_sha256,
        )
        for item in verified.captures
    )
    core_capture_projection = tuple(
        (
            item.get("width"),
            item.get("height"),
            item.get("assistant_mode"),
            item.get("screenshot_sha256"),
            item.get("console_summary_sha256"),
            item.get("network_summary_sha256"),
        )
        for item in browser["captures"]
        if type(item) is dict
    ) if type(browser["captures"]) is list else ()
    expected_elapsed_milliseconds = int(
        float(runtime["stability_elapsed_seconds"]) * 1000
    )
    if (
        not _is_sha256(browser["observer_report_sha256"])
        or signed_capture_projection != core_capture_projection
        or verified.stability_elapsed_milliseconds
        != expected_elapsed_milliseconds
        or verified.metric_sample_count != runtime["metric_sample_count"]
        or verified.metric_sample_chain_sha256
        != runtime["metric_sample_chain_sha256"]
    ):
        raise CollectorError("COLLECTOR_CONTROLLER_BINDING_MISMATCH")
    bound = StrictJsonChapterE2EProbeLoader().load_bytes(
        probe_raw,
        expectation=expectation,
        now=now,
    )
    return request_fingerprint, bound


def _validate_local_operator_collector_candidate(
    *,
    collector_raw: bytes,
    collector: Mapping[str, object],
    probe_raw: bytes,
    probe: Mapping[str, object],
    expectation: ProbeExpectation,
    now: datetime | None,
) -> tuple[str, BoundTechnicalProbe]:
    """Validate an author-operated local report without crypto claims."""

    code = "COLLECTOR_REPORT_INVALID"
    detailed = _exact_mapping(
        collector,
        frozenset(
            {
                "schema_version",
                "collected_at",
                "formal_validation_eligible",
                "evidence_class",
                "acceptance_scope",
                "local_executor",
                "source",
                "request",
                "binding",
                "browser",
                "runtime",
                "probe_report_sha256",
            }
        ),
        code=code,
    )
    source = _exact_mapping(
        detailed["source"],
        frozenset({"controller_id", "page_url", "synthetic"}),
        code=code,
    )
    executor = _exact_mapping(
        detailed["local_executor"],
        frozenset(
            {
                "controller_build_sha256",
                "browser_binary_sha256",
                "node_binary_sha256",
            }
        ),
        code=code,
    )
    collected_at = _parse_timestamp(detailed["collected_at"], code=code)
    if (
        detailed["schema_version"]
        != LOCAL_OPERATOR_COLLECTOR_SCHEMA_VERSION
        or detailed["formal_validation_eligible"] is not False
        or detailed["evidence_class"] != "local_operator_observation"
        or detailed["acceptance_scope"] != "technical_observation_only"
        or source
        != {
            "controller_id": FIXED_CONTROLLER_ID,
            "page_url": FIXED_PUBLIC_PAGE_URL,
            "synthetic": False,
        }
        or any(not _is_sha256(value) for value in executor.values())
        or detailed["binding"]
        != expectation.report_binding(collected_at=collected_at)
        or detailed["probe_report_sha256"] != _sha256_bytes(probe_raw)
        or probe.get("schema_version") != PROBE_SCHEMA_VERSION
        or probe.get("collected_at") != detailed["collected_at"]
        or probe.get("binding") != detailed["binding"]
        or _canonical_json(detailed) + b"\n" != collector_raw
    ):
        raise CollectorError(code)
    request = _exact_mapping(
        detailed["request"],
        frozenset(
            {
                "schema_version",
                "report_schema_version",
                "created_at",
                "request_fingerprint_sha256",
                "request_sha256",
            }
        ),
        code=code,
    )
    request_fingerprint = _validate_signed_runtime_report(
        request_payload=request,
        runtime_payload=detailed["runtime"],
        probe_runtime_payload=probe.get("runtime"),
        collected_at=collected_at,
        expectation=expectation,
    )
    browser = _exact_mapping(
        detailed["browser"],
        frozenset(
            {
                "observer_report_sha256",
                "captures",
                "screenshot_set_sha256",
                "console_set_sha256",
                "network_set_sha256",
                "range_etag",
                "interaction",
                "editor",
            }
        ),
        code=code,
    )
    if not _is_sha256(browser["observer_report_sha256"]):
        raise CollectorError(code)
    bound = StrictJsonChapterE2EProbeLoader().load_bytes(
        probe_raw,
        expectation=expectation,
        now=now,
    )
    return request_fingerprint, bound


class LocalOperatorCollectorReportGuard:
    """Accept only a complete local-operator transaction for this run."""

    def load_verified(
        self,
        report_path: Path,
        *,
        expectation: ProbeExpectation,
        now: datetime | None = None,
    ) -> BoundTechnicalProbe:
        try:
            if type(expectation) is not ProbeExpectation:
                raise CollectorError("COLLECTOR_BINDING_INVALID")
            candidate = Path(report_path)
            if candidate.name != PROBE_REPORT_FILENAME:
                raise CollectorError("COLLECTOR_REPORT_NAME_INVALID")
            resolved_parent, parent_metadata = _resolve_private_parent(
                candidate,
                allow_missing_leaf=True,
            )
            parent_identity = _directory_identity(parent_metadata)
            _require_guard_lock_or_clean_start(
                resolved_parent,
                parent_identity,
            )
            with _collector_transaction_lock(
                resolved_parent,
                parent_identity,
                exclusive=False,
                create=False,
            ) as locked_parent_fd:
                collector_record = _read_optional_transaction_json(
                    locked_parent_fd,
                    filename=COLLECTOR_REPORT_FILENAME,
                )
                probe_record = _read_optional_transaction_json(
                    locked_parent_fd,
                    filename=PROBE_REPORT_FILENAME,
                )
                marker_record = _read_optional_transaction_json(
                    locked_parent_fd,
                    filename=COLLECTOR_COMMIT_MARKER_FILENAME,
                )
                if (
                    collector_record is None
                    and probe_record is None
                    and marker_record is None
                ):
                    raise CollectorError("COLLECTOR_COMMIT_INCOMPLETE")
                if (
                    collector_record is None
                    or probe_record is None
                    or marker_record is None
                ):
                    raise CollectorError("COLLECTOR_COMMIT_INCOMPLETE")
                (
                    collector_raw,
                    collector_payload,
                    collector_identity,
                    collector_transient,
                ) = collector_record
                (
                    probe_raw,
                    probe_payload,
                    probe_identity,
                    probe_transient,
                ) = probe_record
                (
                    marker_raw,
                    marker_payload,
                    _marker_identity,
                    marker_transient,
                ) = marker_record
                if (
                    collector_transient
                    or probe_transient
                    or marker_transient
                ):
                    raise CollectorError("COLLECTOR_COMMIT_INCOMPLETE")
                request_fingerprint, bound = (
                    _validate_local_operator_collector_candidate(
                        collector_raw=collector_raw,
                        collector=collector_payload,
                        probe_raw=probe_raw,
                        probe=probe_payload,
                        expectation=expectation,
                        now=now,
                    )
                )
                _validate_formal_commit_marker(
                    marker=marker_payload,
                    request_fingerprint_sha256=request_fingerprint,
                    collector_raw=collector_raw,
                    collector_identity=collector_identity,
                    probe_raw=probe_raw,
                    probe_identity=probe_identity,
                    expected_schema_version=(
                        LOCAL_OPERATOR_COMMIT_SCHEMA_VERSION
                    ),
                )
                return replace(
                    bound,
                    evidence_class="local_operator_observation",
                    evidence_root_sha256=_evidence_root_sha256(
                        collector_raw=collector_raw,
                        probe_raw=probe_raw,
                        marker_raw=marker_raw,
                    ),
                )
        except CollectorError as error:
            if error.code == COLLECTOR_TRANSACTION_BUSY_ERROR:
                raise ProbeReportError(PROBE_COLLECTOR_BUSY_ERROR) from None
            if error.code in {
                "COLLECTOR_COMMIT_INCOMPLETE",
                _TRANSACTION_NOT_STARTED_ERROR,
            }:
                raise ProbeReportError(PROBE_COLLECTOR_INCOMPLETE_ERROR) from None
            raise ProbeReportError(
                "PROBE_COLLECTOR_LOCAL_EVIDENCE_INVALID"
            ) from None
        except (OSError, TypeError, ValueError):
            raise ProbeReportError(
                "PROBE_COLLECTOR_LOCAL_EVIDENCE_INVALID"
            ) from None


class SignedCollectorReportGuard:
    """Classify transaction state without granting missing provenance.

    ``validation_token`` and the legacy capability argument remain only for
    launcher-call compatibility.  Neither is a controller signing authority.
    A complete, internally consistent legacy HMAC triple reaches the stable
    ``PROBE_CONTROLLER_AUTHORITY_HOLD`` state; it can never yield a
    :class:`BoundTechnicalProbe` until an independently trusted controller port
    is designed and approved.
    """

    def __init__(
        self,
        *,
        validation_token: str,
        controller_attestation_capability: (
            ControllerAttestationCapability | None
        ) = None,
    ) -> None:
        try:
            _validate_validation_token(validation_token)
            if controller_attestation_capability is not None:
                _validate_controller_capability(
                    controller_attestation_capability
                )
        except ValueError:
            raise ProbeReportError(
                "PROBE_COLLECTOR_ATTESTATION_INVALID"
            ) from None

    def load_verified(
        self,
        report_path: Path,
        *,
        expectation: ProbeExpectation,
        now: datetime | None = None,
    ) -> BoundTechnicalProbe:
        try:
            if type(expectation) is not ProbeExpectation:
                raise CollectorError("COLLECTOR_BINDING_INVALID")
            candidate = Path(report_path)
            if candidate.name != PROBE_REPORT_FILENAME:
                raise CollectorError("COLLECTOR_REPORT_NAME_INVALID")
            resolved_parent, parent_metadata = _resolve_private_parent(
                candidate,
                allow_missing_leaf=True,
            )
            parent_identity = _directory_identity(parent_metadata)
            _require_guard_lock_or_clean_start(
                resolved_parent,
                parent_identity,
            )
            with _collector_transaction_lock(
                resolved_parent,
                parent_identity,
                exclusive=False,
                create=False,
            ) as locked_parent_fd:
                collector_record = _read_optional_transaction_json(
                    locked_parent_fd,
                    filename=COLLECTOR_REPORT_FILENAME,
                )
                probe_record = _read_optional_transaction_json(
                    locked_parent_fd,
                    filename=PROBE_REPORT_FILENAME,
                )
                marker_record = _read_optional_transaction_json(
                    locked_parent_fd,
                    filename=COLLECTOR_COMMIT_MARKER_FILENAME,
                )
                if (
                    collector_record is None
                    and probe_record is None
                    and marker_record is None
                ):
                    raise CollectorError("COLLECTOR_COMMIT_INCOMPLETE")
                if collector_record is None:
                    raise CollectorError("COLLECTOR_REPORT_INVALID")
                (
                    collector_raw,
                    collector,
                    collector_file_identity,
                    collector_transient,
                ) = collector_record
                if probe_record is None:
                    if marker_record is not None:
                        raise CollectorError("COLLECTOR_REPORT_INVALID")
                    if collector.get("schema_version") == (
                        LEGACY_COLLECTOR_SCHEMA_VERSION
                    ):
                        _validate_untrusted_collector_candidate(
                            collector_raw=collector_raw,
                            collector=collector,
                            probe_raw=None,
                            probe=None,
                            expectation=expectation,
                            now=now,
                        )
                    elif collector.get("schema_version") == (
                        COLLECTOR_SCHEMA_VERSION
                    ):
                        _validate_formal_collector_candidate(
                            collector_raw=collector_raw,
                            collector=collector,
                            probe_raw=None,
                            probe=None,
                            expectation=expectation,
                            now=now,
                        )
                    else:
                        raise CollectorError("COLLECTOR_REPORT_INVALID")
                    raise CollectorError("COLLECTOR_COMMIT_INCOMPLETE")
                (
                    probe_raw,
                    probe,
                    probe_file_identity,
                    probe_transient,
                ) = probe_record
                legacy = collector.get("schema_version") == (
                    LEGACY_COLLECTOR_SCHEMA_VERSION
                )
                bound: BoundTechnicalProbe | None = None
                if legacy:
                    request_fingerprint = (
                        _validate_untrusted_collector_candidate(
                            collector_raw=collector_raw,
                            collector=collector,
                            probe_raw=probe_raw,
                            probe=probe,
                            expectation=expectation,
                            now=now,
                        )
                    )
                elif collector.get("schema_version") == (
                    COLLECTOR_SCHEMA_VERSION
                ):
                    formal = _validate_formal_collector_candidate(
                        collector_raw=collector_raw,
                        collector=collector,
                        probe_raw=probe_raw,
                        probe=probe,
                        expectation=expectation,
                        now=now,
                    )
                    if formal is None:
                        raise CollectorError("COLLECTOR_REPORT_INVALID")
                    request_fingerprint, bound = formal
                else:
                    raise CollectorError("COLLECTOR_REPORT_INVALID")
                if request_fingerprint is None:
                    raise CollectorError("COLLECTOR_REPORT_INVALID")
                if marker_record is None:
                    raise CollectorError("COLLECTOR_COMMIT_INCOMPLETE")
                if collector_transient or probe_transient:
                    raise CollectorError("COLLECTOR_COMMIT_INCOMPLETE")
                (
                    marker_raw,
                    marker,
                    _marker_file_identity,
                    marker_transient,
                ) = marker_record
                if legacy:
                    _validate_untrusted_commit_marker(
                        marker=marker,
                        request_fingerprint_sha256=request_fingerprint,
                        collector_raw=collector_raw,
                        collector_identity=collector_file_identity,
                        probe_raw=probe_raw,
                        probe_identity=probe_file_identity,
                    )
                else:
                    _validate_formal_commit_marker(
                        marker=marker,
                        request_fingerprint_sha256=request_fingerprint,
                        collector_raw=collector_raw,
                        collector_identity=collector_file_identity,
                        probe_raw=probe_raw,
                        probe_identity=probe_file_identity,
                    )
                if marker_transient:
                    raise CollectorError("COLLECTOR_COMMIT_INCOMPLETE")
                if legacy:
                    raise CollectorError(
                        COLLECTOR_CONTROLLER_AUTHORITY_HOLD_ERROR
                    )
                if bound is None:
                    raise CollectorError("COLLECTOR_REPORT_INVALID")
                return replace(
                    bound,
                    evidence_class="signed_controller_evidence",
                    evidence_root_sha256=_evidence_root_sha256(
                        collector_raw=collector_raw,
                        probe_raw=probe_raw,
                        marker_raw=marker_raw,
                    ),
                )
        except CollectorError as error:
            if error.code == COLLECTOR_TRANSACTION_BUSY_ERROR:
                raise ProbeReportError(PROBE_COLLECTOR_BUSY_ERROR) from None
            if error.code in {
                "COLLECTOR_COMMIT_INCOMPLETE",
                _TRANSACTION_NOT_STARTED_ERROR,
            }:
                raise ProbeReportError(
                    PROBE_COLLECTOR_INCOMPLETE_ERROR
                ) from None
            if error.code == COLLECTOR_CONTROLLER_AUTHORITY_HOLD_ERROR:
                raise ProbeReportError(
                    PROBE_CONTROLLER_AUTHORITY_HOLD_ERROR
                ) from None
            raise ProbeReportError(
                "PROBE_COLLECTOR_ATTESTATION_INVALID"
            ) from None
        except (OSError, TypeError, ValueError):
            raise ProbeReportError(
                "PROBE_COLLECTOR_ATTESTATION_INVALID"
            ) from None

    def verify(
        self,
        report_path: Path,
        *,
        expectation: ProbeExpectation,
        now: datetime | None = None,
    ) -> None:
        self.load_verified(
            report_path,
            expectation=expectation,
            now=now,
        )


class FixedChapterE2ECollector:
    """Validate fixed-controller evidence for local or experimental use."""

    def __init__(
        self,
        *,
        validation_token: str | None = None,
        controller_attestation_capability: (
            ControllerAttestationCapability | None
        ) = None,
    ) -> None:
        try:
            if validation_token is not None:
                _validate_validation_token(validation_token)
            if controller_attestation_capability is not None:
                _validate_controller_capability(
                    controller_attestation_capability
                )
        except ValueError:
            raise CollectorError(
                "COLLECTOR_ATTESTATION_KEY_INVALID"
            ) from None

    def validate_synthetic(
        self,
        probe_request_path: Path,
        evidence: FixedControllerEvidence,
        *,
        now: datetime | None = None,
    ) -> SyntheticProtocolResult:
        current = now or datetime.now(timezone.utc).replace(microsecond=0)
        request, _, _ = _load_request(probe_request_path, now=current)
        _validate_evidence(
            request,
            evidence,
            now=current,
            require_real=False,
        )
        return SyntheticProtocolResult(
            status="SYNTHETIC_PROTOCOL_ONLY",
            formal_validation_eligible=False,
        )

    def finalize_local_operator(
        self,
        probe_request_path: Path,
        evidence: FixedControllerEvidence,
        *,
        controller_build_sha256: str,
        browser_binary_sha256: str,
        node_binary_sha256: str,
        now: datetime | None = None,
    ) -> CollectorResult:
        """Publish local author/operator evidence without signing claims."""

        current = now or datetime.now(timezone.utc).replace(microsecond=0)
        request, parent, parent_identity = _load_request(
            probe_request_path,
            now=current,
        )
        _validate_evidence(
            request,
            evidence,
            now=current,
            require_real=True,
        )
        _preparation, collector_core, probe_bytes = (
            _prepare_controller_report(
                request,
                evidence,
                preflight_payload_sha256=request.preflight_payload_sha256,
            )
        )
        collector_bytes = _build_local_operator_collector_report(
            collector_core,
            controller_build_sha256=controller_build_sha256,
            browser_binary_sha256=browser_binary_sha256,
            node_binary_sha256=node_binary_sha256,
        )
        collector_payload = _decode_json_mapping(
            collector_bytes,
            code="COLLECTOR_REPORT_INVALID",
        )
        probe_payload = _decode_json_mapping(
            probe_bytes,
            code="COLLECTOR_REPORT_INVALID",
        )
        validated_request_fingerprint, _bound = (
            _validate_local_operator_collector_candidate(
                collector_raw=collector_bytes,
                collector=collector_payload,
                probe_raw=probe_bytes,
                probe=probe_payload,
                expectation=request.expectation,
                now=current,
            )
        )
        if validated_request_fingerprint != request.request_fingerprint_sha256:
            raise CollectorError("COLLECTOR_LOCAL_OPERATOR_BINDING_INVALID")
        _ensure_outputs_absent(parent, parent_identity)
        with _collector_transaction_lock(
            parent,
            parent_identity,
            exclusive=True,
            create=True,
        ) as parent_fd:
            locked_request, locked_parent, locked_parent_identity = (
                _load_request(probe_request_path, now=current)
            )
            if (
                locked_request != request
                or locked_parent != parent
                or locked_parent_identity != parent_identity
            ):
                raise CollectorError("COLLECTOR_FILE_UNSAFE")
            _validate_evidence(
                locked_request,
                evidence,
                now=current,
                require_real=True,
            )
            _locked_preparation, locked_core, locked_probe = (
                _prepare_controller_report(
                    locked_request,
                    evidence,
                    preflight_payload_sha256=(
                        locked_request.preflight_payload_sha256
                    ),
                )
            )
            locked_collector = _build_local_operator_collector_report(
                locked_core,
                controller_build_sha256=controller_build_sha256,
                browser_binary_sha256=browser_binary_sha256,
                node_binary_sha256=node_binary_sha256,
            )
            if (
                locked_collector != collector_bytes
                or locked_probe != probe_bytes
            ):
                raise CollectorError("COLLECTOR_FILE_UNSAFE")
            collector_identity = _publish_exact_file(
                parent_fd,
                filename=COLLECTOR_REPORT_FILENAME,
                data=collector_bytes,
            )
            probe_identity = _publish_exact_file(
                parent_fd,
                filename=PROBE_REPORT_FILENAME,
                data=probe_bytes,
            )
            marker_bytes = _build_local_operator_commit_marker(
                request_fingerprint_sha256=(
                    request.request_fingerprint_sha256
                ),
                collector_bytes=collector_bytes,
                collector_identity=collector_identity,
                probe_bytes=probe_bytes,
                probe_identity=probe_identity,
            )
            _publish_exact_file(
                parent_fd,
                filename=COLLECTOR_COMMIT_MARKER_FILENAME,
                data=marker_bytes,
            )
            _assert_parent_identity(parent, parent_fd, parent_identity)
        return CollectorResult(
            status="LOCAL_OPERATOR_OBSERVATION_COMMITTED",
            collector_report_sha256=_sha256_bytes(collector_bytes),
            probe_report_sha256=_sha256_bytes(probe_bytes),
        )

    def finalize_real(
        self,
        probe_request_path: Path,
        evidence: FixedControllerEvidence,
        *,
        controller_report_binding: bytes | None = None,
        controller_report_signature: bytes | None = None,
        now: datetime | None = None,
    ) -> CollectorResult:
        """Verify fixed public SSHSIG authority, then publish one v2 triple.

        Missing authority remains a stable HOLD.  Neither this method nor the
        ordinary collector ever receives a private key or ssh-agent socket.
        """

        current = now or datetime.now(timezone.utc).replace(microsecond=0)
        request, parent, parent_identity = _load_request(
            probe_request_path,
            now=current,
        )
        _validate_evidence(
            request,
            evidence,
            now=current,
            require_real=True,
        )
        verified_preflight = _verify_request_controller_preflight(
            request,
            parent,
            parent_identity,
        )
        if (
            controller_report_binding is None
            or controller_report_signature is None
        ):
            raise CollectorError(COLLECTOR_CONTROLLER_AUTHORITY_HOLD_ERROR)
        preparation, collector_core_bytes, probe_bytes = (
            _prepare_controller_report(
                request,
                evidence,
                preflight_payload_sha256=request.preflight_payload_sha256,
            )
        )
        try:
            FixedControllerTrustVerifier().verify_report_binding(
                controller_report_binding,
                controller_report_signature,
                expectation=preparation.expectation,
                now=current,
            )
        except ControllerTrustError as error:
            if error.code == CONTROLLER_TRUST_ROOT_HOLD_ERROR:
                raise CollectorError(
                    COLLECTOR_CONTROLLER_AUTHORITY_HOLD_ERROR
                ) from None
            if error.code == CONTROLLER_REPORT_BINDING_MISMATCH_ERROR:
                raise CollectorError(
                    "COLLECTOR_CONTROLLER_BINDING_MISMATCH"
                ) from None
            raise CollectorError(
                "COLLECTOR_CONTROLLER_ATTESTATION_INVALID"
            ) from None
        collector_bytes = _build_formal_collector_report(
            collector_core_bytes,
            controller_report_binding,
            controller_report_signature,
        )
        probe = _decode_json_mapping(
            probe_bytes,
            code="COLLECTOR_REPORT_INVALID",
        )
        collector = _decode_json_mapping(
            collector_bytes,
            code="COLLECTOR_REPORT_INVALID",
        )
        formal = _validate_formal_collector_candidate(
            collector_raw=collector_bytes,
            collector=collector,
            probe_raw=probe_bytes,
            probe=probe,
            expectation=request.expectation,
            now=current,
        )
        if formal is None:
            raise CollectorError("COLLECTOR_CONTROLLER_ATTESTATION_INVALID")
        _ensure_outputs_absent(parent, parent_identity)
        with _collector_transaction_lock(
            parent,
            parent_identity,
            exclusive=True,
            create=True,
        ) as parent_fd:
            locked_request, locked_parent, locked_parent_identity = (
                _load_request(probe_request_path, now=current)
            )
            if (
                locked_request != request
                or locked_parent != parent
                or locked_parent_identity != parent_identity
            ):
                raise CollectorError("COLLECTOR_FILE_UNSAFE")
            _validate_evidence(
                locked_request,
                evidence,
                now=current,
                require_real=True,
            )
            locked_preflight = _verify_request_controller_preflight(
                locked_request,
                locked_parent,
                locked_parent_identity,
            )
            if locked_preflight != verified_preflight:
                raise CollectorError("COLLECTOR_FILE_UNSAFE")
            locked_preparation, locked_core, locked_probe = (
                _prepare_controller_report(
                    locked_request,
                    evidence,
                    preflight_payload_sha256=(
                        locked_request.preflight_payload_sha256
                    ),
                )
            )
            if (
                locked_preparation != preparation
                or locked_core != collector_core_bytes
                or locked_probe != probe_bytes
            ):
                raise CollectorError("COLLECTOR_FILE_UNSAFE")
            collector_identity = _publish_exact_file(
                parent_fd,
                filename=COLLECTOR_REPORT_FILENAME,
                data=collector_bytes,
            )
            probe_identity = _publish_exact_file(
                parent_fd,
                filename=PROBE_REPORT_FILENAME,
                data=probe_bytes,
            )
            marker_bytes = _build_formal_commit_marker(
                request_fingerprint_sha256=(
                    request.request_fingerprint_sha256
                ),
                collector_bytes=collector_bytes,
                collector_identity=collector_identity,
                probe_bytes=probe_bytes,
                probe_identity=probe_identity,
            )
            _publish_exact_file(
                parent_fd,
                filename=COLLECTOR_COMMIT_MARKER_FILENAME,
                data=marker_bytes,
            )
            _assert_parent_identity(parent, parent_fd, parent_identity)
        return CollectorResult(
            status="FORMAL_CONTROLLER_REPORT_COMMITTED",
            collector_report_sha256=_sha256_bytes(collector_bytes),
            probe_report_sha256=_sha256_bytes(probe_bytes),
        )


__all__ = [
    "BrowserCollectorEvidence",
    "COLLECTOR_COMMIT_MARKER_FILENAME",
    "COLLECTOR_COMMIT_SCHEMA_VERSION",
    "COLLECTOR_CONTROLLER_AUTHORITY_HOLD_ERROR",
    "COLLECTOR_REPORT_FILENAME",
    "COLLECTOR_SCHEMA_VERSION",
    "COLLECTOR_TRANSACTION_BUSY_ERROR",
    "CONTROLLER_ATTESTATION_CAPABILITY_FILENAME",
    "CaptureDigest",
    "CollectorError",
    "CollectorResult",
    "ControllerReportPreparation",
    "ControllerReportSigningContext",
    "ControllerAttestationCapability",
    "FIXED_CONTROLLER_ID",
    "FIXED_PUBLIC_PAGE_URL",
    "FixedChapterE2ECollector",
    "FixedControllerEvidence",
    "LOCAL_OPERATOR_COLLECTOR_SCHEMA_VERSION",
    "LOCAL_OPERATOR_COMMIT_SCHEMA_VERSION",
    "LocalOperatorCollectorReportGuard",
    "PROBE_REPORT_FILENAME",
    "PROBE_COLLECTOR_BUSY_ERROR",
    "PROBE_COLLECTOR_INCOMPLETE_ERROR",
    "PROBE_CONTROLLER_ATTESTATION_REQUIRED_ERROR",
    "PROBE_CONTROLLER_AUTHORITY_HOLD_ERROR",
    "SidecarCollectorEvidence",
    "SidecarMetricSampleDigest",
    "SignedCollectorReportGuard",
    "SyntheticProtocolResult",
    "build_sidecar_metric_sample_chain_sha256",
    "build_controller_report_binding_payload",
    "load_controller_attestation_capability",
    "require_formal_controller_authority",
    "prepare_controller_report_binding",
]
