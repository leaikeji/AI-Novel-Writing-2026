"""Strict importer for externally collected T4-K browser/runtime probes.

This module does not launch a browser, contact the Sidecar, or write evidence.
It only accepts one narrowly shaped, private ``0600`` JSON report collected by
the separately owned T4-K harness.  The report is bound to the frozen v2 run,
scope, automatic/manual Editions, listening outputs, and collection time before
its values can be converted to :class:`TechnicalOutcome`.

Report schema ``moss-tts-chapter-e2e-probes/2.3``::

    {
      "schema_version": "moss-tts-chapter-e2e-probes/2.3",
      "collected_at": "2026-08-27T12:00:00Z",
      "binding": { ... exact hashed run fields ... },
      "browser": { ... four fixed viewport/assistant captures ... },
      "runtime": { ... fixed Sidecar and aggregate metrics ... }
    }

The schema intentionally has no free-form path, text, log, screenshot, or
audio field.  Stable error codes never include the private report path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import time
from typing import Callable, Final, Literal, Mapping, Protocol, Sequence
from uuid import UUID

from scripts.tts.chapter_e2e_executor import (
    BrowserManifestObservation,
    BrowserTechnicalEvidence,
    TechnicalProbeContext,
)
from scripts.tts.validate_chapter_e2e import (
    ALLOWED_VIEWPORTS,
    ChapterFixture,
    REPOSITORY_ROOT,
    RunnerConfig,
    RunnerError,
    TechnicalOutcome,
)


PROBE_SCHEMA_VERSION: Final = "moss-tts-chapter-e2e-probes/2.3"
EXPECTED_SIDECAR_CONTAINER_NAME: Final = "ai-novel-2026-moss-tts-sidecar"
ALLOWED_ASSISTANT_MODES: Final = ("collapsed", "expanded")
EXPECTED_RANGE_STATUS_CODES: Final = (200, 206, 304, 416)
MAX_REPORT_BYTES: Final = 64 * 1024
DEFAULT_MAX_REPORT_AGE_SECONDS: Final = 15 * 60
DEFAULT_MAX_FUTURE_SKEW_SECONDS: Final = 30
# A formal report cannot exist until the full 30-minute post-request window
# has elapsed. Reserve five additional minutes for the final sample, report
# assembly, fsync and controller-to-runner handoff.
DEFAULT_REPORT_WAIT_TIMEOUT_SECONDS: Final = 35 * 60
_RETRYABLE_COLLECTOR_GUARD_CODES: Final = frozenset(
    {"PROBE_COLLECTOR_BUSY", "PROBE_COLLECTOR_INCOMPLETE"}
)
_SHA256_LENGTH: Final = 64
CURRENT_PAWAPP_ROOT: Final = Path(__file__).resolve().parents[2]
MEMORY_GROWTH_MIN_LIMIT_BYTES: Final = 128 * 1024 * 1024
MEMORY_GROWTH_PERCENT_NUMERATOR: Final = 5
MEMORY_GROWTH_PERCENT_DENOMINATOR: Final = 100


class ProbeReportError(RunnerError):
    """Fail-closed probe error whose message cannot leak private data."""

    def __init__(self, code: str):
        super().__init__(code)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _is_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == _SHA256_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def _normalized_hashes(
    values: Sequence[str],
    *,
    code: str,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)):
        raise ProbeReportError(code)
    items = tuple(values)
    if (
        not items
        or any(not _is_sha256(item) for item in items)
        or len(items) != len(set(items))
    ):
        raise ProbeReportError(code)
    return tuple(sorted(items))


def _canonical_utc_timestamp(value: datetime) -> str:
    if type(value) is not datetime or value.tzinfo is None:
        raise ProbeReportError("PROBE_COLLECTION_TIME_INVALID")
    normalized = value.astimezone(timezone.utc)
    if normalized.microsecond != 0:
        raise ProbeReportError("PROBE_COLLECTION_TIME_INVALID")
    return normalized.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc_timestamp(value: object) -> datetime:
    if type(value) is not str or len(value) != 20:
        raise ProbeReportError("PROBE_COLLECTION_TIME_INVALID")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        raise ProbeReportError("PROBE_COLLECTION_TIME_INVALID") from None
    if _canonical_utc_timestamp(parsed) != value:
        raise ProbeReportError("PROBE_COLLECTION_TIME_INVALID")
    return parsed


@dataclass(frozen=True, slots=True)
class ProbeExpectation:
    """Redacted Edition identity and content authority from the executor."""

    run_fingerprint_sha256: str
    target_scope_sha256: str
    automatic_edition_id_sha256: str
    manual_edition_id_sha256: str
    automatic_edition_fingerprint_sha256: str
    manual_edition_fingerprint_sha256: str
    listening_output_hashes: tuple[str, ...]
    required_stability_seconds: float

    def __post_init__(self) -> None:
        if (
            any(
                not _is_sha256(value)
                for value in (
                    self.run_fingerprint_sha256,
                    self.target_scope_sha256,
                    self.automatic_edition_id_sha256,
                    self.manual_edition_id_sha256,
                    self.automatic_edition_fingerprint_sha256,
                    self.manual_edition_fingerprint_sha256,
                )
            )
            or _normalized_hashes(
                self.listening_output_hashes,
                code="PROBE_EXPECTATION_INVALID",
            )
            != self.listening_output_hashes
            or type(self.required_stability_seconds) not in {int, float}
            or not math.isfinite(float(self.required_stability_seconds))
            or self.required_stability_seconds <= 0
        ):
            raise ProbeReportError("PROBE_EXPECTATION_INVALID")

    @classmethod
    def from_runner(
        cls,
        config: RunnerConfig,
        *,
        automatic_edition_id: UUID,
        automatic_edition_fingerprint: str,
        manual_edition_id: UUID,
        manual_edition_fingerprint: str,
        listening_output_hashes: Sequence[str],
    ) -> "ProbeExpectation":
        if (
            type(config) is not RunnerConfig
            or type(config.run_id) is not UUID
            or type(config.novel_id) is not UUID
            or type(config.document_id) is not UUID
            or type(automatic_edition_id) is not UUID
            or type(manual_edition_id) is not UUID
            or not _is_sha256(automatic_edition_fingerprint)
            or not _is_sha256(manual_edition_fingerprint)
            or type(config.duration_minutes) not in {int, float}
            or not math.isfinite(float(config.duration_minutes))
            or config.duration_minutes <= 0
        ):
            raise ProbeReportError("PROBE_EXPECTATION_INVALID")
        hashes = _normalized_hashes(
            listening_output_hashes,
            code="PROBE_EXPECTATION_INVALID",
        )
        return cls(
            run_fingerprint_sha256=_sha256_text(str(config.run_id)),
            target_scope_sha256=_sha256_text(
                f"{config.novel_id}:{config.document_id}"
            ),
            automatic_edition_id_sha256=_sha256_text(
                str(automatic_edition_id)
            ),
            manual_edition_id_sha256=_sha256_text(str(manual_edition_id)),
            automatic_edition_fingerprint_sha256=(
                automatic_edition_fingerprint
            ),
            manual_edition_fingerprint_sha256=(
                manual_edition_fingerprint
            ),
            listening_output_hashes=hashes,
            required_stability_seconds=float(config.duration_minutes) * 60.0,
        )

    def report_binding(self, *, collected_at: datetime) -> dict[str, object]:
        """Return the exact safe binding object a collector must serialize."""

        timestamp = _canonical_utc_timestamp(collected_at)
        unsigned: dict[str, object] = {
            "run_fingerprint_sha256": self.run_fingerprint_sha256,
            "target_scope_sha256": self.target_scope_sha256,
            "automatic_edition_id_sha256": self.automatic_edition_id_sha256,
            "manual_edition_id_sha256": self.manual_edition_id_sha256,
            "automatic_edition_fingerprint_sha256": (
                self.automatic_edition_fingerprint_sha256
            ),
            "manual_edition_fingerprint_sha256": (
                self.manual_edition_fingerprint_sha256
            ),
            "listening_output_hashes": list(self.listening_output_hashes),
            "required_stability_seconds": self.required_stability_seconds,
        }
        digest_input = {
            "schema_version": PROBE_SCHEMA_VERSION,
            "collected_at": timestamp,
            **unsigned,
        }
        return {
            **unsigned,
            "binding_fingerprint_sha256": hashlib.sha256(
                _canonical_json_bytes(digest_input)
            ).hexdigest(),
        }


@dataclass(frozen=True, slots=True)
class BoundTechnicalProbe:
    """Validated probe values safe to pass into the frozen T4-K validator."""

    collected_at: datetime
    report_sha256: str
    binding_fingerprint_sha256: str
    stability_elapsed_seconds: float
    chapter_audio_duration_seconds: float
    request_to_ready_seconds: float
    time_to_first_audio_ms: int
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
    range_status_codes: tuple[int, ...]
    seam_pairs_checked: int
    listening_output_hashes: tuple[str, ...]
    evidence_class: str = "unclassified_probe"
    evidence_root_sha256: str | None = None

    def to_technical_outcome(self) -> TechnicalOutcome:
        """Assemble only measured values; no duration or pass result is invented."""

        return TechnicalOutcome(
            collector_collected_at=_canonical_utc_timestamp(self.collected_at),
            stability_elapsed_seconds=self.stability_elapsed_seconds,
            chapter_audio_duration_seconds=self.chapter_audio_duration_seconds,
            request_to_ready_seconds=self.request_to_ready_seconds,
            time_to_first_audio_ms=self.time_to_first_audio_ms,
            peak_memory_bytes=self.peak_memory_bytes,
            host_paging_observed=self.host_paging_observed,
            pageout_delta=self.pageout_delta,
            swapout_delta=self.swapout_delta,
            memory_baseline_median_bytes=(
                self.memory_baseline_median_bytes
            ),
            memory_tail_median_bytes=self.memory_tail_median_bytes,
            memory_growth_bytes=self.memory_growth_bytes,
            memory_growth_limit_bytes=self.memory_growth_limit_bytes,
            sidecar_memory_growth_observed=(
                self.sidecar_memory_growth_observed
            ),
            qwenpaw_slowdown_observed=self.qwenpaw_slowdown_observed,
            range_status_codes=self.range_status_codes,
            seam_pairs_checked=self.seam_pairs_checked,
            seek_latest_wins=True,
            pending_gap_not_skipped=True,
            edit_actions_created_tts_writes=0,
            browser_viewports=ALLOWED_VIEWPORTS,
            browser_assistant_modes=ALLOWED_ASSISTANT_MODES,
            browser_console_error_count=0,
            browser_overlap_count=0,
            sidecar_restart_count=0,
            health_failure_count=0,
            listening_output_hashes=self.listening_output_hashes,
            evidence_class=self.evidence_class,
            evidence_root_sha256=self.evidence_root_sha256,
        )


class ChapterE2EProbeLoader(Protocol):
    """Executor-facing seam for importing an already collected private report."""

    def load(
        self,
        report_path: Path,
        *,
        expectation: ProbeExpectation,
        now: datetime | None = None,
    ) -> BoundTechnicalProbe: ...


class ProbeRequestPublisher(Protocol):
    """Optional fixed-launcher handshake published before report waiting."""

    def publish(
        self,
        config: RunnerConfig,
        expectation: ProbeExpectation,
        context: TechnicalProbeContext,
    ) -> None: ...


class ProbeReportGuard(Protocol):
    """Formal-launcher provenance guard for a paired collector report."""

    def load_verified(
        self,
        report_path: Path,
        *,
        expectation: ProbeExpectation,
    ) -> BoundTechnicalProbe: ...


class BoundProbeReportCache:
    """Load one external report once and share the immutable result across ports."""

    def __init__(
        self,
        report_path: Path,
        *,
        loader: ChapterE2EProbeLoader | None = None,
        wait_timeout_seconds: float = DEFAULT_REPORT_WAIT_TIMEOUT_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        poll_interval_seconds: float = 0.5,
        request_publisher: ProbeRequestPublisher | None = None,
        report_guard: ProbeReportGuard | None = None,
    ) -> None:
        if (
            not isinstance(report_path, Path)
            or not report_path.is_absolute()
            or type(wait_timeout_seconds) not in {int, float}
            or not math.isfinite(float(wait_timeout_seconds))
            or not 1 <= float(wait_timeout_seconds) <= 3600
            or type(poll_interval_seconds) not in {int, float}
            or not math.isfinite(float(poll_interval_seconds))
            or not 0 < float(poll_interval_seconds) <= 5
            or not callable(monotonic)
            or not callable(sleeper)
            or (
                request_publisher is not None
                and not callable(getattr(request_publisher, "publish", None))
            )
            or (
                report_guard is not None
                and not callable(
                    getattr(report_guard, "load_verified", None)
                )
            )
        ):
            raise ProbeReportError("PROBE_CACHE_POLICY_INVALID")
        self._report_path = report_path
        self._loader = loader or StrictJsonChapterE2EProbeLoader()
        self._wait_timeout_seconds = float(wait_timeout_seconds)
        self._monotonic = monotonic
        self._sleeper = sleeper
        self._poll_interval_seconds = float(poll_interval_seconds)
        self._request_publisher = request_publisher
        self._report_guard = report_guard
        self._expectation: ProbeExpectation | None = None
        self._bound: BoundTechnicalProbe | None = None

    def load(
        self,
        config: RunnerConfig,
        context: TechnicalProbeContext,
    ) -> BoundTechnicalProbe:
        if type(config) is not RunnerConfig or type(context) is not TechnicalProbeContext:
            raise ProbeReportError("PROBE_EXPECTATION_INVALID")
        expectation = ProbeExpectation.from_runner(
            config,
            automatic_edition_id=context.automatic_edition_id,
            automatic_edition_fingerprint=(
                context.automatic_edition_fingerprint
            ),
            manual_edition_id=context.manual_edition_id,
            manual_edition_fingerprint=context.manual_edition_fingerprint,
            listening_output_hashes=context.listening_output_hashes,
        )
        if self._expectation is not None and self._expectation != expectation:
            raise ProbeReportError("PROBE_BINDING_MISMATCH")
        if self._bound is not None:
            return self._bound
        if self._expectation is None:
            if self._request_publisher is not None:
                self._request_publisher.publish(config, expectation, context)
            self._expectation = expectation
        deadline = self._monotonic() + self._wait_timeout_seconds
        if self._report_guard is not None:
            # The guard owns the collector transaction protocol.  In formal
            # mode the report filename alone is not a completion signal: only
            # a verified report/collector/commit triple may escape this loop.
            while True:
                try:
                    bound = self._report_guard.load_verified(
                        self._report_path,
                        expectation=expectation,
                    )
                    break
                except ProbeReportError as error:
                    if error.code not in _RETRYABLE_COLLECTOR_GUARD_CODES:
                        raise
                    if self._monotonic() >= deadline:
                        raise ProbeReportError("PROBE_REPORT_TIMEOUT") from None
                    self._sleeper(self._poll_interval_seconds)
        else:
            while True:
                try:
                    self._report_path.lstat()
                except FileNotFoundError:
                    if self._monotonic() >= deadline:
                        raise ProbeReportError("PROBE_REPORT_TIMEOUT")
                    self._sleeper(self._poll_interval_seconds)
                    continue
                except OSError:
                    raise ProbeReportError("PROBE_FILE_UNSAFE") from None
                break
            bound = self._loader.load(
                self._report_path,
                expectation=expectation,
            )
        self._bound = bound
        return bound


class StrictReportBrowserProbe:
    """Browser port backed only by one externally collected, run-bound report."""

    def __init__(self, config: RunnerConfig, *, cache: BoundProbeReportCache) -> None:
        if type(config) is not RunnerConfig or type(cache) is not BoundProbeReportCache:
            raise ProbeReportError("PROBE_BROWSER_PORT_INVALID")
        self._config = config
        self._cache = cache
        self._active_chain: Literal["automatic", "manual"] | None = None
        self._begun: list[Literal["automatic", "manual"]] = []
        self._observations: dict[
            Literal["automatic", "manual"], list[BrowserManifestObservation]
        ] = {"automatic": [], "manual": []}
        self._completed: dict[
            Literal["automatic", "manual"], tuple[UUID, UUID]
        ] = {}

    def _require_config(self, config: RunnerConfig) -> None:
        if config != self._config:
            raise ProbeReportError("PROBE_BROWSER_SCOPE_MISMATCH")

    def begin_chain(
        self,
        config: RunnerConfig,
        chain_label: Literal["automatic", "manual"],
    ) -> None:
        self._require_config(config)
        expected = "automatic" if not self._begun else "manual"
        if (
            chain_label != expected
            or self._active_chain is not None
            or chain_label in self._completed
        ):
            raise ProbeReportError("PROBE_BROWSER_SEQUENCE_INVALID")
        self._active_chain = chain_label
        self._begun.append(chain_label)

    def observe_manifest(
        self,
        config: RunnerConfig,
        observation: BrowserManifestObservation,
    ) -> None:
        self._require_config(config)
        if (
            type(observation) is not BrowserManifestObservation
            or observation.chain_label != self._active_chain
            or observation.ready_segment_count < 1
            or observation.total_segment_count < observation.ready_segment_count
            or observation.manifest_revision < 1
            or observation.elapsed_ms < 0
        ):
            raise ProbeReportError("PROBE_BROWSER_OBSERVATION_INVALID")
        rows = self._observations[observation.chain_label]
        if rows and (
            rows[-1].request_id != observation.request_id
            or rows[-1].edition_id != observation.edition_id
            or rows[-1].manifest_revision >= observation.manifest_revision
            or rows[-1].ready_segment_count > observation.ready_segment_count
            or rows[-1].total_segment_count != observation.total_segment_count
            or rows[-1].elapsed_ms > observation.elapsed_ms
        ):
            raise ProbeReportError("PROBE_BROWSER_OBSERVATION_INVALID")
        rows.append(observation)

    def complete_chain(
        self,
        config: RunnerConfig,
        *,
        chain_label: Literal["automatic", "manual"],
        request_id: UUID,
        edition_id: UUID,
    ) -> None:
        self._require_config(config)
        rows = self._observations.get(chain_label, [])
        if (
            chain_label != self._active_chain
            or not rows
            or rows[-1].request_id != request_id
            or rows[-1].edition_id != edition_id
            or rows[-1].workflow_state != "ready"
            or rows[-1].ready_segment_count != rows[-1].total_segment_count
        ):
            raise ProbeReportError("PROBE_BROWSER_SEQUENCE_INVALID")
        self._completed[chain_label] = (request_id, edition_id)
        self._active_chain = None

    def collect(
        self,
        config: RunnerConfig,
        fixture: ChapterFixture,
        context: TechnicalProbeContext,
    ) -> BrowserTechnicalEvidence:
        self._require_config(config)
        expected_completed = {
            "automatic": (
                context.automatic_request_id,
                context.automatic_edition_id,
            ),
            "manual": (context.manual_request_id, context.manual_edition_id),
        }
        if (
            type(fixture) is not ChapterFixture
            or type(context) is not TechnicalProbeContext
            or fixture.required_viewports != ALLOWED_VIEWPORTS
            or self._active_chain is not None
            or self._begun != ["automatic", "manual"]
            or self._completed != expected_completed
        ):
            raise ProbeReportError("PROBE_BROWSER_SEQUENCE_INVALID")
        bound = self._cache.load(config, context)
        outcome = bound.to_technical_outcome()
        return BrowserTechnicalEvidence(
            collector_collected_at=outcome.collector_collected_at,
            time_to_first_audio_ms=outcome.time_to_first_audio_ms,
            seek_latest_wins=outcome.seek_latest_wins,
            pending_gap_not_skipped=outcome.pending_gap_not_skipped,
            edit_actions_created_tts_writes=(
                outcome.edit_actions_created_tts_writes
            ),
            browser_viewports=outcome.browser_viewports,
            browser_assistant_modes=outcome.browser_assistant_modes,
            browser_console_error_count=outcome.browser_console_error_count,
            browser_overlap_count=outcome.browser_overlap_count,
            evidence_class=outcome.evidence_class,
            evidence_root_sha256=outcome.evidence_root_sha256,
        )


def _require_exact_keys(
    value: object,
    expected: frozenset[str],
    *,
    code: str,
) -> Mapping[str, object]:
    if type(value) is not dict or frozenset(value) != expected:
        raise ProbeReportError(code)
    return value


def _reject_symlink_components(path: Path) -> None:
    if not path.is_absolute() or ".." in path.parts:
        raise ProbeReportError("PROBE_PATH_UNSAFE")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            metadata = current.lstat()
        except OSError:
            raise ProbeReportError("PROBE_FILE_UNSAFE") from None
        if stat.S_ISLNK(metadata.st_mode):
            raise ProbeReportError("PROBE_PATH_UNSAFE")


def _same_object(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _secure_parent(metadata: os.stat_result) -> bool:
    return (
        stat.S_ISDIR(metadata.st_mode)
        and not stat.S_ISLNK(metadata.st_mode)
        and stat.S_IMODE(metadata.st_mode) == 0o700
        and metadata.st_uid == os.getuid()
    )


def _secure_report_file(metadata: os.stat_result) -> bool:
    return (
        stat.S_ISREG(metadata.st_mode)
        and not stat.S_ISLNK(metadata.st_mode)
        and metadata.st_nlink == 1
        and stat.S_IMODE(metadata.st_mode) == 0o600
        and metadata.st_uid == os.getuid()
        and 0 < metadata.st_size <= MAX_REPORT_BYTES
    )


def _file_identity(metadata: os.stat_result) -> tuple[int, ...]:
    """Capture identity plus mutable fields that could change bytes mid-read."""

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


def _protected_code_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    for candidate in (REPOSITORY_ROOT, CURRENT_PAWAPP_ROOT):
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            raise ProbeReportError("PROBE_PATH_UNSAFE") from None
        if resolved not in roots:
            roots.append(resolved)
    return tuple(roots)


def _read_secure_report(path: Path) -> bytes:
    try:
        candidate = Path(path)
    except (TypeError, ValueError, OSError):
        raise ProbeReportError("PROBE_PATH_UNSAFE") from None
    _reject_symlink_components(candidate)
    try:
        supplied_parent_before = candidate.parent.lstat()
        resolved_parent = candidate.parent.resolve(strict=True)
        resolved_parent_before = resolved_parent.lstat()
    except OSError:
        raise ProbeReportError("PROBE_FILE_UNSAFE") from None
    if any(
        resolved_parent == root or resolved_parent.is_relative_to(root)
        for root in _protected_code_roots()
    ):
        raise ProbeReportError("PROBE_PATH_UNSAFE")
    if (
        not _same_object(supplied_parent_before, resolved_parent_before)
        or not _secure_parent(supplied_parent_before)
        or not _secure_parent(resolved_parent_before)
    ):
        raise ProbeReportError("PROBE_FILE_UNSAFE")

    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise ProbeReportError("PROBE_FILE_UNSAFE")
    parent_descriptor: int | None = None
    file_descriptor: int | None = None
    try:
        parent_descriptor = os.open(
            resolved_parent,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | nofollow,
        )
        opened_parent = os.fstat(parent_descriptor)
        if (
            not _same_object(resolved_parent_before, opened_parent)
            or not _secure_parent(opened_parent)
        ):
            raise ProbeReportError("PROBE_FILE_UNSAFE")

        before = os.stat(
            candidate.name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        if not _secure_report_file(before):
            raise ProbeReportError("PROBE_FILE_UNSAFE")
        file_descriptor = os.open(
            candidate.name,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | nofollow,
            dir_fd=parent_descriptor,
        )
        opened = os.fstat(file_descriptor)
        if (
            _file_identity(opened) != _file_identity(before)
            or not _secure_report_file(opened)
        ):
            raise ProbeReportError("PROBE_FILE_UNSAFE")
        chunks: list[bytes] = []
        remaining = opened.st_size
        while remaining:
            chunk = os.read(file_descriptor, min(remaining, 64 * 1024))
            if not chunk:
                raise ProbeReportError("PROBE_FILE_UNSAFE")
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if os.read(file_descriptor, 1):
            raise ProbeReportError("PROBE_FILE_UNSAFE")
        after = os.fstat(file_descriptor)
        path_after = os.stat(
            candidate.name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        parent_after = os.fstat(parent_descriptor)
        supplied_parent_after = candidate.parent.lstat()
        resolved_parent_after = resolved_parent.lstat()
        _reject_symlink_components(candidate)
        if (
            _file_identity(after) != _file_identity(opened)
            or _file_identity(path_after) != _file_identity(opened)
            or not _secure_report_file(after)
            or not _secure_report_file(path_after)
            or not _same_object(parent_after, opened_parent)
            or not _same_object(supplied_parent_after, opened_parent)
            or not _same_object(resolved_parent_after, opened_parent)
            or not _secure_parent(parent_after)
            or not _secure_parent(supplied_parent_after)
            or not _secure_parent(resolved_parent_after)
        ):
            raise ProbeReportError("PROBE_FILE_UNSAFE")

        os.close(file_descriptor)
        file_descriptor = None
        os.close(parent_descriptor)
        parent_descriptor = None
        return data
    except ProbeReportError:
        raise
    except OSError:
        raise ProbeReportError("PROBE_FILE_UNSAFE") from None
    finally:
        if file_descriptor is not None:
            try:
                os.close(file_descriptor)
            except OSError:
                pass
        if parent_descriptor is not None:
            try:
                os.close(parent_descriptor)
            except OSError:
                pass


class _DuplicateJsonKey(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateJsonKey
        value[key] = item
    return value


def _reject_nonfinite_json(_: str) -> object:
    raise ValueError


def _parse_report(data: bytes) -> Mapping[str, object]:
    try:
        decoded = data.decode("utf-8", errors="strict")
        value = json.loads(
            decoded,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_json,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise ProbeReportError("PROBE_REPORT_INVALID") from None
    return _require_exact_keys(
        value,
        frozenset(
            {"schema_version", "collected_at", "binding", "browser", "runtime"}
        ),
        code="PROBE_REPORT_INVALID",
    )


def _number(value: object, *, positive: bool = False) -> float:
    if type(value) not in {int, float} or not math.isfinite(float(value)):
        raise ProbeReportError("PROBE_RUNTIME_GATE_FAILED")
    result = float(value)
    if result < 0 or (positive and result <= 0):
        raise ProbeReportError("PROBE_RUNTIME_GATE_FAILED")
    return result


class StrictJsonChapterE2EProbeLoader:
    """Load one bound report without performing any collection or I/O writes."""

    def __init__(
        self,
        *,
        max_report_age_seconds: int = DEFAULT_MAX_REPORT_AGE_SECONDS,
        max_future_skew_seconds: int = DEFAULT_MAX_FUTURE_SKEW_SECONDS,
    ) -> None:
        if (
            type(max_report_age_seconds) is not int
            or max_report_age_seconds <= 0
            or type(max_future_skew_seconds) is not int
            or max_future_skew_seconds < 0
        ):
            raise ProbeReportError("PROBE_LOADER_POLICY_INVALID")
        self._max_age = timedelta(seconds=max_report_age_seconds)
        self._max_future_skew = timedelta(seconds=max_future_skew_seconds)

    def load(
        self,
        report_path: Path,
        *,
        expectation: ProbeExpectation,
        now: datetime | None = None,
    ) -> BoundTechnicalProbe:
        if type(expectation) is not ProbeExpectation:
            raise ProbeReportError("PROBE_EXPECTATION_INVALID")
        raw = _read_secure_report(report_path)
        return self.load_bytes(raw, expectation=expectation, now=now)

    def load_bytes(
        self,
        raw: bytes,
        *,
        expectation: ProbeExpectation,
        now: datetime | None = None,
    ) -> BoundTechnicalProbe:
        """Validate the exact bytes already pinned by a provenance guard."""

        if (
            type(expectation) is not ProbeExpectation
            or type(raw) is not bytes
            or not raw
            or len(raw) > MAX_REPORT_BYTES
        ):
            raise ProbeReportError("PROBE_EXPECTATION_INVALID")
        report = _parse_report(raw)
        if report["schema_version"] != PROBE_SCHEMA_VERSION:
            raise ProbeReportError("PROBE_SCHEMA_INVALID")
        collected_at = _parse_utc_timestamp(report["collected_at"])
        current = now or datetime.now(timezone.utc)
        if type(current) is not datetime or current.tzinfo is None:
            raise ProbeReportError("PROBE_COLLECTION_TIME_INVALID")
        current = current.astimezone(timezone.utc)
        if collected_at > current + self._max_future_skew:
            raise ProbeReportError("PROBE_COLLECTION_TIME_FUTURE")
        if current - collected_at > self._max_age:
            raise ProbeReportError("PROBE_REPORT_EXPIRED")

        binding = _require_exact_keys(
            report["binding"],
            frozenset(
                {
                    "run_fingerprint_sha256",
                    "target_scope_sha256",
                    "automatic_edition_id_sha256",
                    "manual_edition_id_sha256",
                    "automatic_edition_fingerprint_sha256",
                    "manual_edition_fingerprint_sha256",
                    "listening_output_hashes",
                    "required_stability_seconds",
                    "binding_fingerprint_sha256",
                }
            ),
            code="PROBE_BINDING_INVALID",
        )
        hashes_value = binding["listening_output_hashes"]
        if not isinstance(hashes_value, list):
            raise ProbeReportError("PROBE_BINDING_INVALID")
        report_hashes = _normalized_hashes(
            hashes_value,
            code="PROBE_BINDING_INVALID",
        )
        expected_binding = expectation.report_binding(collected_at=collected_at)
        if (
            binding["run_fingerprint_sha256"]
            != expectation.run_fingerprint_sha256
            or binding["target_scope_sha256"] != expectation.target_scope_sha256
            or binding["automatic_edition_id_sha256"]
            != expectation.automatic_edition_id_sha256
            or binding["manual_edition_id_sha256"]
            != expectation.manual_edition_id_sha256
            or binding["automatic_edition_fingerprint_sha256"]
            != expectation.automatic_edition_fingerprint_sha256
            or binding["manual_edition_fingerprint_sha256"]
            != expectation.manual_edition_fingerprint_sha256
            or report_hashes != expectation.listening_output_hashes
            or type(binding["required_stability_seconds"]) not in {int, float}
            or not math.isfinite(float(binding["required_stability_seconds"]))
            or float(binding["required_stability_seconds"])
            != expectation.required_stability_seconds
            or binding["binding_fingerprint_sha256"]
            != expected_binding["binding_fingerprint_sha256"]
        ):
            raise ProbeReportError("PROBE_BINDING_MISMATCH")

        browser = self._validate_browser(report["browser"])
        runtime = self._validate_runtime(
            report["runtime"],
            required_stability_seconds=expectation.required_stability_seconds,
        )
        return BoundTechnicalProbe(
            collected_at=collected_at,
            report_sha256=hashlib.sha256(raw).hexdigest(),
            binding_fingerprint_sha256=str(
                binding["binding_fingerprint_sha256"]
            ),
            stability_elapsed_seconds=runtime["stability_elapsed_seconds"],
            chapter_audio_duration_seconds=runtime[
                "chapter_audio_duration_seconds"
            ],
            request_to_ready_seconds=runtime["request_to_ready_seconds"],
            time_to_first_audio_ms=browser["time_to_first_audio_ms"],
            peak_memory_bytes=runtime["peak_memory_bytes"],
            host_paging_observed=runtime["host_paging_observed"],
            pageout_delta=runtime["pageout_delta"],
            swapout_delta=runtime["swapout_delta"],
            memory_baseline_median_bytes=runtime[
                "memory_baseline_median_bytes"
            ],
            memory_tail_median_bytes=runtime["memory_tail_median_bytes"],
            memory_growth_bytes=runtime["memory_growth_bytes"],
            memory_growth_limit_bytes=runtime["memory_growth_limit_bytes"],
            sidecar_memory_growth_observed=runtime[
                "sidecar_memory_growth_observed"
            ],
            qwenpaw_slowdown_observed=runtime[
                "qwenpaw_slowdown_observed"
            ],
            range_status_codes=EXPECTED_RANGE_STATUS_CODES,
            seam_pairs_checked=browser["seam_pairs_checked"],
            listening_output_hashes=expectation.listening_output_hashes,
        )

    @staticmethod
    def _validate_browser(value: object) -> dict[str, int]:
        browser = _require_exact_keys(
            value,
            frozenset(
                {
                    "observer_report_sha256",
                    "captures",
                    "range_status_codes",
                    "time_to_first_audio_ms",
                    "seam_pairs_checked",
                    "seek_latest_wins",
                    "pending_gap_not_skipped",
                    "edit_actions_created_tts_writes",
                }
            ),
            code="PROBE_BROWSER_GATE_FAILED",
        )
        captures = browser["captures"]
        if not isinstance(captures, list) or len(captures) != 4:
            raise ProbeReportError("PROBE_BROWSER_GATE_FAILED")
        observed: set[tuple[int, int, str]] = set()
        allowed = {
            (width, height, mode)
            for width, height in ALLOWED_VIEWPORTS
            for mode in ALLOWED_ASSISTANT_MODES
        }
        for raw_capture in captures:
            capture = _require_exact_keys(
                raw_capture,
                frozenset(
                    {
                        "width",
                        "height",
                        "assistant_mode",
                        "console_error_count",
                        "overlap_count",
                    }
                ),
                code="PROBE_BROWSER_GATE_FAILED",
            )
            if (
                type(capture["width"]) is not int
                or type(capture["height"]) is not int
                or type(capture["assistant_mode"]) is not str
                or type(capture["console_error_count"]) is not int
                or capture["console_error_count"] != 0
                or type(capture["overlap_count"]) is not int
                or capture["overlap_count"] != 0
            ):
                raise ProbeReportError("PROBE_BROWSER_GATE_FAILED")
            key = (
                capture["width"],
                capture["height"],
                capture["assistant_mode"],
            )
            if key in observed or key not in allowed:
                raise ProbeReportError("PROBE_BROWSER_GATE_FAILED")
            observed.add(key)
        statuses = browser["range_status_codes"]
        if (
            not _is_sha256(browser["observer_report_sha256"])
            or not isinstance(statuses, list)
            or any(type(item) is not int for item in statuses)
            or len(statuses) != len(set(statuses))
            or tuple(sorted(statuses)) != EXPECTED_RANGE_STATUS_CODES
            or observed != allowed
            or type(browser["time_to_first_audio_ms"]) is not int
            or browser["time_to_first_audio_ms"] < 0
            or type(browser["seam_pairs_checked"]) is not int
            or browser["seam_pairs_checked"] < 1
            or browser["seek_latest_wins"] is not True
            or browser["pending_gap_not_skipped"] is not True
            or type(browser["edit_actions_created_tts_writes"]) is not int
            or browser["edit_actions_created_tts_writes"] != 0
        ):
            raise ProbeReportError("PROBE_BROWSER_GATE_FAILED")
        return {
            "time_to_first_audio_ms": browser["time_to_first_audio_ms"],
            "seam_pairs_checked": browser["seam_pairs_checked"],
        }

    @staticmethod
    def _validate_runtime(
        value: object,
        *,
        required_stability_seconds: float,
    ) -> dict[str, float | int | bool]:
        runtime = _require_exact_keys(
            value,
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
            code="PROBE_RUNTIME_GATE_FAILED",
        )
        stability = _number(runtime["stability_elapsed_seconds"])
        audio_duration = _number(
            runtime["chapter_audio_duration_seconds"], positive=True
        )
        request_to_ready = _number(runtime["request_to_ready_seconds"])
        integer_fields = (
            "peak_memory_bytes",
            "pageout_delta",
            "swapout_delta",
            "memory_baseline_median_bytes",
            "memory_tail_median_bytes",
            "memory_growth_bytes",
            "memory_growth_limit_bytes",
        )
        integers_valid = all(
            type(runtime[field]) is int and runtime[field] >= 0
            for field in integer_fields
        )
        if integers_valid:
            measured_growth = max(
                0,
                runtime["memory_tail_median_bytes"]
                - runtime["memory_baseline_median_bytes"],
            )
            percentage_limit = (
                runtime["memory_baseline_median_bytes"]
                * MEMORY_GROWTH_PERCENT_NUMERATOR
                + MEMORY_GROWTH_PERCENT_DENOMINATOR
                - 1
            ) // MEMORY_GROWTH_PERCENT_DENOMINATOR
            measured_growth_limit = max(
                MEMORY_GROWTH_MIN_LIMIT_BYTES,
                percentage_limit,
            )
            measured_host_paging = (
                runtime["pageout_delta"] > 0
                or runtime["swapout_delta"] > 0
            )
            measured_growth_observed = (
                measured_growth > measured_growth_limit
            )
        if (
            runtime["sidecar_container_name"]
            != EXPECTED_SIDECAR_CONTAINER_NAME
            or stability < required_stability_seconds
            or not integers_valid
            or type(runtime["host_paging_observed"]) is not bool
            or runtime["host_paging_observed"] is not measured_host_paging
            or type(runtime["sidecar_memory_growth_observed"]) is not bool
            or runtime["memory_baseline_median_bytes"]
            > runtime["peak_memory_bytes"]
            or runtime["memory_tail_median_bytes"]
            > runtime["peak_memory_bytes"]
            or runtime["memory_growth_bytes"] != measured_growth
            or runtime["memory_growth_limit_bytes"]
            != measured_growth_limit
            or runtime["sidecar_memory_growth_observed"]
            is not measured_growth_observed
            or type(runtime["qwenpaw_slowdown_observed"]) is not bool
            or type(runtime["sidecar_restart_count"]) is not int
            or runtime["sidecar_restart_count"] != 0
            or type(runtime["health_failure_count"]) is not int
            or runtime["health_failure_count"] != 0
        ):
            raise ProbeReportError("PROBE_RUNTIME_GATE_FAILED")
        return {
            "stability_elapsed_seconds": stability,
            "chapter_audio_duration_seconds": audio_duration,
            "request_to_ready_seconds": request_to_ready,
            "peak_memory_bytes": runtime["peak_memory_bytes"],
            "host_paging_observed": runtime["host_paging_observed"],
            "pageout_delta": runtime["pageout_delta"],
            "swapout_delta": runtime["swapout_delta"],
            "memory_baseline_median_bytes": runtime[
                "memory_baseline_median_bytes"
            ],
            "memory_tail_median_bytes": runtime["memory_tail_median_bytes"],
            "memory_growth_bytes": runtime["memory_growth_bytes"],
            "memory_growth_limit_bytes": runtime[
                "memory_growth_limit_bytes"
            ],
            "sidecar_memory_growth_observed": runtime[
                "sidecar_memory_growth_observed"
            ],
            "qwenpaw_slowdown_observed": runtime[
                "qwenpaw_slowdown_observed"
            ],
        }


def load_chapter_e2e_probe_report(
    report_path: Path,
    *,
    expectation: ProbeExpectation,
    now: datetime | None = None,
) -> BoundTechnicalProbe:
    """Convenience entry point used by the future T4-K executor wiring."""

    return StrictJsonChapterE2EProbeLoader().load(
        report_path,
        expectation=expectation,
        now=now,
    )


__all__ = [
    "ALLOWED_ASSISTANT_MODES",
    "BoundProbeReportCache",
    "BoundTechnicalProbe",
    "ChapterE2EProbeLoader",
    "EXPECTED_SIDECAR_CONTAINER_NAME",
    "PROBE_SCHEMA_VERSION",
    "ProbeExpectation",
    "ProbeReportGuard",
    "ProbeRequestPublisher",
    "ProbeReportError",
    "StrictJsonChapterE2EProbeLoader",
    "StrictReportBrowserProbe",
    "load_chapter_e2e_probe_report",
]
