"""Fail-closed watchdog for one-shot heavyweight processes on macOS.

This prototype deliberately has no Torch, Transformers, or model dependency.  It
owns the child process group, samples host/process memory, and records enough
structured evidence for the Plan 40 hardware spike.  Product code may adapt the
module later, but it must not weaken the policy or run a model in-process.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import signal
import struct
import subprocess
import tempfile
import threading
import time
from typing import Callable, Mapping, Protocol, Sequence


GIB = 1024**3
MIB = 1024**2


class MeasurementUnavailable(RuntimeError):
    """Raised when a safety-critical metric cannot be read reliably.

    ``category`` is deliberately a fixed, non-sensitive identifier.  Evidence
    may retain it to distinguish a host command failure from a Nano interlock
    failure without copying command output, paths, or exception messages.
    """

    def __init__(self, message: str, *, category: str = "unspecified") -> None:
        super().__init__(message)
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", category):
            raise ValueError("measurement category is invalid")
        self.category = category


class MemoryPressure(str, Enum):
    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class ProcessOutcome(str, Enum):
    COMPLETED = "completed"
    CHILD_FAILED = "child_failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    SAFETY_TERMINATED = "safety_terminated"
    SPAWN_FAILED = "spawn_failed"


class StopReason(str, Enum):
    USER_CANCELLED = "user_cancelled"
    HARD_TIMEOUT = "hard_timeout"
    CRITICAL_MEMORY_PRESSURE = "critical_memory_pressure"
    PREFLIGHT_HEADROOM_INSUFFICIENT = "preflight_headroom_insufficient"
    HEADROOM_BELOW_ABORT_FLOOR = "headroom_below_abort_floor"
    SWAP_BUDGET_EXCEEDED = "swap_budget_exceeded"
    PAGEOUT_BUDGET_EXCEEDED = "pageout_budget_exceeded"
    OUTPUT_BUDGET_EXCEEDED = "output_budget_exceeded"
    NANO_RELOADED = "nano_reloaded"
    HEARTBEAT_STALLED = "heartbeat_stalled"
    MEASUREMENT_UNAVAILABLE = "measurement_unavailable"


@dataclass(frozen=True)
class MetricSnapshot:
    monotonic_seconds: float
    observed_at: str
    child_pid: int | None
    child_rss_bytes: int | None
    child_phys_footprint_bytes: int | None
    physical_memory_bytes: int
    available_memory_estimate_bytes: int
    memory_pressure: MemoryPressure
    swap_used_bytes: int
    pageins: int
    pageouts: int
    nano_model_loaded: bool

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["memory_pressure"] = self.memory_pressure.value
        return payload


class MetricsSampler(Protocol):
    def sample(self, child_pid: int | None) -> MetricSnapshot:
        """Return one coherent host/process snapshot or raise."""


@dataclass(frozen=True)
class SafetyPolicy:
    """Thresholds for one monitored process.

    ``pageout_budget_pages`` and ``recovery_tolerance_bytes`` are intentionally
    required.  Plan 40 does not yet freeze their numeric values, so a caller may
    not inherit an invented production threshold silently.
    """

    hard_timeout_seconds: float
    pageout_budget_pages: int
    recovery_tolerance_bytes: int
    sample_interval_seconds: float = 1.0
    termination_grace_seconds: float = 5.0
    minimum_abort_headroom_bytes: int = int(3.5 * GIB)
    minimum_pass_headroom_bytes: int = 4 * GIB
    maximum_swap_delta_bytes: int = 512 * MIB
    sustained_pageout_seconds: float = 60.0
    heartbeat_stall_seconds: float | None = None
    maximum_captured_output_bytes: int = 16 * MIB
    recovery_offsets_seconds: tuple[float, ...] = (10.0, 30.0, 60.0)
    enforce_headroom_swap_pageout_limits: bool = True
    critical_pressure_grace_seconds: float = 20.0

    def __post_init__(self) -> None:
        positive = {
            "hard_timeout_seconds": self.hard_timeout_seconds,
            "sample_interval_seconds": self.sample_interval_seconds,
            "termination_grace_seconds": self.termination_grace_seconds,
            "minimum_abort_headroom_bytes": self.minimum_abort_headroom_bytes,
            "minimum_pass_headroom_bytes": self.minimum_pass_headroom_bytes,
            "maximum_swap_delta_bytes": self.maximum_swap_delta_bytes,
            "sustained_pageout_seconds": self.sustained_pageout_seconds,
            "recovery_tolerance_bytes": self.recovery_tolerance_bytes,
            "maximum_captured_output_bytes": self.maximum_captured_output_bytes,
            "critical_pressure_grace_seconds": self.critical_pressure_grace_seconds,
        }
        invalid = [name for name, value in positive.items() if value <= 0]
        if invalid:
            raise ValueError(f"policy values must be positive: {', '.join(invalid)}")
        if self.pageout_budget_pages < 0:
            raise ValueError("pageout_budget_pages must be non-negative")
        if self.minimum_abort_headroom_bytes >= self.minimum_pass_headroom_bytes:
            raise ValueError("abort headroom must be lower than pass headroom")
        if self.heartbeat_stall_seconds is not None and self.heartbeat_stall_seconds <= 0:
            raise ValueError("heartbeat_stall_seconds must be positive")
        if not self.recovery_offsets_seconds:
            raise ValueError("at least one recovery offset is required")
        if tuple(sorted(self.recovery_offsets_seconds)) != self.recovery_offsets_seconds:
            raise ValueError("recovery offsets must be sorted")
        if self.recovery_offsets_seconds[0] < 0:
            raise ValueError("recovery offsets cannot be negative")


@dataclass(frozen=True)
class WatchdogEvent:
    kind: str
    monotonic_seconds: float
    detail: str


@dataclass(frozen=True)
class RecoveryAssessment:
    recovered: bool
    baseline_available_bytes: int
    final_available_bytes: int | None
    allowed_drop_bytes: int
    child_absent: bool
    resource_limits_enforced: bool
    samples: tuple[MetricSnapshot, ...]
    reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["samples"] = [sample.to_dict() for sample in self.samples]
        return payload


@dataclass(frozen=True)
class WatchdogResult:
    outcome: ProcessOutcome
    stop_reason: StopReason | None
    return_code: int | None
    started_at: str
    finished_at: str
    elapsed_seconds: float
    safe_for_this_run: bool
    resource_limits_enforced: bool
    maximum_swap_delta_bytes: int
    minimum_headroom_bytes: int | None
    maximum_child_rss_bytes: int | None
    maximum_child_phys_footprint_bytes: int | None
    pageout_delta_pages: int
    maximum_continuous_pageout_seconds: float
    maximum_continuous_critical_pressure_seconds: float
    samples: tuple[MetricSnapshot, ...]
    events: tuple[WatchdogEvent, ...]
    recovery: RecoveryAssessment | None
    stdout_bytes: int
    stdout_sha256: str
    stderr_bytes: int
    stderr_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "outcome": self.outcome.value,
            "stop_reason": self.stop_reason.value if self.stop_reason else None,
            "return_code": self.return_code,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_seconds": self.elapsed_seconds,
            "safe_for_this_run": self.safe_for_this_run,
            "resource_limits_enforced": self.resource_limits_enforced,
            "maximum_swap_delta_bytes": self.maximum_swap_delta_bytes,
            "minimum_headroom_bytes": self.minimum_headroom_bytes,
            "maximum_child_rss_bytes": self.maximum_child_rss_bytes,
            "maximum_child_phys_footprint_bytes": self.maximum_child_phys_footprint_bytes,
            "pageout_delta_pages": self.pageout_delta_pages,
            "maximum_continuous_pageout_seconds": self.maximum_continuous_pageout_seconds,
            "maximum_continuous_critical_pressure_seconds": self.maximum_continuous_critical_pressure_seconds,
            "samples": [sample.to_dict() for sample in self.samples],
            "events": [asdict(event) for event in self.events],
            "recovery": self.recovery.to_dict() if self.recovery else None,
            "stdout_bytes": self.stdout_bytes,
            "stdout_sha256": self.stdout_sha256,
            "stderr_bytes": self.stderr_bytes,
            "stderr_sha256": self.stderr_sha256,
        }

    def write_json(self, path: Path) -> None:
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def sanitized_child_environment(
    overrides: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build a narrow environment without inheriting credentials or HOME."""

    allowed = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR")
    environment = {key: os.environ[key] for key in allowed if key in os.environ}
    environment["PYTHONUNBUFFERED"] = "1"
    if overrides:
        for key, value in overrides.items():
            if not key or "=" in key or "\x00" in key or "\x00" in value:
                raise ValueError("invalid child environment override")
            upper_key = key.upper()
            if any(
                marker in upper_key
                for marker in ("TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "API_KEY")
            ):
                raise ValueError("credential-like child environment override is forbidden")
            environment[key] = value
    return environment


class MacOSMetricsSampler:
    """Read macOS metrics without importing model/runtime libraries."""

    _VM_LINE = re.compile(r"^([^:]+):\s+([0-9]+)\.")
    _SWAP_VALUE = re.compile(r"used\s*=\s*([0-9.]+)([KMGTP])", re.IGNORECASE)

    def __init__(self, nano_loaded_probe: Callable[[], bool]) -> None:
        if platform.system() != "Darwin":
            raise MeasurementUnavailable("macOS metrics sampler requires Darwin")
        if nano_loaded_probe is None:
            raise ValueError("an authoritative Nano residency probe is required")
        self._nano_loaded_probe = nano_loaded_probe
        try:
            self._physical_memory_bytes = self._read_sysctl_integer("hw.memsize")
        except MeasurementUnavailable as error:
            raise MeasurementUnavailable(
                "physical-memory metric unavailable",
                category="physical_memory",
            ) from error

    @staticmethod
    def _run(command: Sequence[str]) -> str:
        try:
            result = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
                env=sanitized_child_environment(),
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise MeasurementUnavailable(f"metric command failed: {command[0]}") from error
        return result.stdout

    @classmethod
    def _read_sysctl_integer(cls, name: str) -> int:
        output = cls._run(("/usr/sbin/sysctl", "-n", name)).strip()
        try:
            return int(output)
        except ValueError as error:
            raise MeasurementUnavailable(f"invalid integer sysctl: {name}") from error

    @classmethod
    def _read_swap_used_bytes(cls) -> int:
        output = cls._run(("/usr/sbin/sysctl", "-n", "vm.swapusage"))
        match = cls._SWAP_VALUE.search(output)
        if not match:
            raise MeasurementUnavailable("vm.swapusage did not expose used bytes")
        value = float(match.group(1))
        multiplier = {
            "K": 1024,
            "M": 1024**2,
            "G": 1024**3,
            "T": 1024**4,
            "P": 1024**5,
        }[match.group(2).upper()]
        return int(value * multiplier)

    @classmethod
    def _read_vm_stat(cls) -> tuple[int, int, int]:
        output = cls._run(("/usr/bin/vm_stat",))
        first_line, *lines = output.splitlines()
        page_size_match = re.search(r"page size of ([0-9]+) bytes", first_line)
        if not page_size_match:
            raise MeasurementUnavailable("vm_stat page size missing")
        page_size = int(page_size_match.group(1))
        values: dict[str, int] = {}
        for line in lines:
            match = cls._VM_LINE.match(line.strip())
            if match:
                values[match.group(1)] = int(match.group(2))
        required = ("Pages free", "Pages inactive", "Pageins", "Pageouts")
        if any(name not in values for name in required):
            raise MeasurementUnavailable("vm_stat required counters missing")
        available_pages = (
            values["Pages free"]
            + values["Pages inactive"]
            + values.get("Pages speculative", 0)
        )
        return available_pages * page_size, values["Pageins"], values["Pageouts"]

    @classmethod
    def _read_pressure(cls) -> MemoryPressure:
        # The kernel flag uses dispatch memory-pressure values: normal=1,
        # warning=2, critical=4.  If the private counter is absent we report
        # unknown; the watchdog then fails closed instead of guessing from a
        # free-memory percentage.
        try:
            level = cls._read_sysctl_integer("kern.memorystatus_vm_pressure_level")
        except MeasurementUnavailable:
            return MemoryPressure.UNKNOWN
        return {
            1: MemoryPressure.NORMAL,
            2: MemoryPressure.WARNING,
            4: MemoryPressure.CRITICAL,
        }.get(level, MemoryPressure.UNKNOWN)

    @staticmethod
    def _read_process_usage(child_pid: int | None) -> tuple[int | None, int | None]:
        if child_pid is None:
            return None, None
        # rusage_info_v2 begins with a 16-byte UUID followed by uint64 values.
        # resident_size is item 6 and phys_footprint item 7.
        library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        buffer = ctypes.create_string_buffer(256)
        result = library.proc_pid_rusage(
            ctypes.c_int(child_pid), ctypes.c_int(2), ctypes.byref(buffer)
        )
        if result != 0:
            if ctypes.get_errno() in {3}:  # ESRCH: the child exited between reads.
                return None, None
            raise MeasurementUnavailable("proc_pid_rusage failed")
        resident_size = struct.unpack_from("=Q", buffer.raw, 16 + (6 * 8))[0]
        phys_footprint = struct.unpack_from("=Q", buffer.raw, 16 + (7 * 8))[0]
        return resident_size, phys_footprint

    def sample(self, child_pid: int | None) -> MetricSnapshot:
        try:
            available, pageins, pageouts = self._read_vm_stat()
        except MeasurementUnavailable as error:
            raise MeasurementUnavailable(
                "virtual-memory metrics unavailable",
                category="vm_stat",
            ) from error
        try:
            rss, footprint = self._read_process_usage(child_pid)
        except MeasurementUnavailable as error:
            raise MeasurementUnavailable(
                "process metrics unavailable",
                category="process_usage",
            ) from error
        try:
            nano_loaded = bool(self._nano_loaded_probe())
        except Exception as error:  # The interlock itself is safety critical.
            raise MeasurementUnavailable(
                "Nano residency probe failed",
                category="nano_residency",
            ) from error
        try:
            pressure = self._read_pressure()
        except MeasurementUnavailable as error:
            raise MeasurementUnavailable(
                "memory-pressure metric unavailable",
                category="memory_pressure",
            ) from error
        try:
            swap_used = self._read_swap_used_bytes()
        except MeasurementUnavailable as error:
            raise MeasurementUnavailable(
                "swap metric unavailable",
                category="swap_usage",
            ) from error
        return MetricSnapshot(
            monotonic_seconds=time.monotonic(),
            observed_at=datetime.now(timezone.utc).isoformat(),
            child_pid=child_pid,
            child_rss_bytes=rss,
            child_phys_footprint_bytes=footprint,
            physical_memory_bytes=self._physical_memory_bytes,
            available_memory_estimate_bytes=min(
                available, self._physical_memory_bytes
            ),
            memory_pressure=pressure,
            swap_used_bytes=swap_used,
            pageins=pageins,
            pageouts=pageouts,
            nano_model_loaded=nano_loaded,
        )


class OneShotProcessWatchdog:
    """Run exactly one child process and terminate its process group safely."""

    def __init__(self, sampler: MetricsSampler, policy: SafetyPolicy) -> None:
        self._sampler = sampler
        self._policy = policy

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        cancel_event: threading.Event | None = None,
        heartbeat_path: Path | None = None,
        environment: Mapping[str, str] | None = None,
        capture_output_digest: bool = False,
    ) -> WatchdogResult:
        if not command or any("\x00" in item for item in command):
            raise ValueError("command must contain non-NUL arguments")
        if not cwd.is_dir():
            raise ValueError("child working directory must exist")
        if heartbeat_path is not None and not heartbeat_path.is_absolute():
            heartbeat_path = cwd / heartbeat_path

        started_wall = datetime.now(timezone.utc).isoformat()
        started = time.monotonic()
        samples: list[MetricSnapshot] = []
        events: list[WatchdogEvent] = []
        stop_reason: StopReason | None = None
        return_code: int | None = None

        try:
            baseline = self._sampler.sample(None)
        except Exception as error:
            finished = time.monotonic()
            events.append(
                WatchdogEvent("measurement_error", finished, _safe_error_name(error))
            )
            return self._result_without_child(
                ProcessOutcome.SAFETY_TERMINATED,
                StopReason.MEASUREMENT_UNAVAILABLE,
                started_wall,
                started,
                finished,
                events,
            )

        preflight_reason = _preflight_stop_reason(baseline, self._policy)
        if preflight_reason is not None:
            finished = time.monotonic()
            events.append(
                WatchdogEvent("preflight_rejected", finished, preflight_reason.value)
            )
            return self._result_without_child(
                ProcessOutcome.SAFETY_TERMINATED,
                preflight_reason,
                started_wall,
                started,
                finished,
                events,
            )
        if cancel_event is not None and cancel_event.is_set():
            finished = time.monotonic()
            events.append(
                WatchdogEvent("preflight_cancelled", finished, StopReason.USER_CANCELLED.value)
            )
            return self._result_without_child(
                ProcessOutcome.CANCELLED,
                StopReason.USER_CANCELLED,
                started_wall,
                started,
                finished,
                events,
            )

        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            stdout_target = stdout_file if capture_output_digest else subprocess.DEVNULL
            stderr_target = stderr_file if capture_output_digest else subprocess.DEVNULL
            try:
                process = subprocess.Popen(
                    tuple(command),
                    cwd=str(cwd),
                    env=sanitized_child_environment(environment),
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_target,
                    stderr=stderr_target,
                    start_new_session=True,
                    close_fds=True,
                )
            except OSError as error:
                finished = time.monotonic()
                events.append(WatchdogEvent("spawn_error", finished, _safe_error_name(error)))
                return self._result_without_child(
                    ProcessOutcome.SPAWN_FAILED,
                    None,
                    started_wall,
                    started,
                    finished,
                    events,
                )

            events.append(WatchdogEvent("child_started", time.monotonic(), str(process.pid)))
            initial_swap = baseline.swap_used_bytes
            initial_pageouts = baseline.pageouts
            maximum_swap_delta = 0
            pageout_active_since: float | None = None
            maximum_pageout_duration = 0.0
            critical_pressure_since: float | None = None
            maximum_critical_pressure_duration = 0.0
            previous_pageouts = baseline.pageouts
            last_heartbeat_change = started
            heartbeat_signature = _heartbeat_signature(heartbeat_path)

            while True:
                now = time.monotonic()
                if cancel_event is not None and cancel_event.is_set():
                    stop_reason = StopReason.USER_CANCELLED
                elif capture_output_digest and (
                    os.fstat(stdout_file.fileno()).st_size
                    + os.fstat(stderr_file.fileno()).st_size
                    > self._policy.maximum_captured_output_bytes
                ):
                    stop_reason = StopReason.OUTPUT_BUDGET_EXCEEDED
                elif now - started >= self._policy.hard_timeout_seconds:
                    stop_reason = StopReason.HARD_TIMEOUT
                elif (
                    heartbeat_path is not None
                    and self._policy.heartbeat_stall_seconds is not None
                ):
                    signature = _heartbeat_signature(heartbeat_path)
                    if signature != heartbeat_signature:
                        heartbeat_signature = signature
                        last_heartbeat_change = now
                    elif now - last_heartbeat_change >= self._policy.heartbeat_stall_seconds:
                        stop_reason = StopReason.HEARTBEAT_STALLED

                if stop_reason is None:
                    try:
                        snapshot = self._sampler.sample(process.pid)
                    except Exception as error:
                        events.append(
                            WatchdogEvent(
                                "measurement_error", now, _safe_error_name(error)
                            )
                        )
                        stop_reason = StopReason.MEASUREMENT_UNAVAILABLE
                    else:
                        samples.append(snapshot)
                        swap_delta = max(0, snapshot.swap_used_bytes - initial_swap)
                        maximum_swap_delta = max(maximum_swap_delta, swap_delta)
                        if snapshot.pageouts > previous_pageouts:
                            if pageout_active_since is None:
                                pageout_active_since = now
                            maximum_pageout_duration = max(
                                maximum_pageout_duration, now - pageout_active_since
                            )
                        else:
                            pageout_active_since = None
                        previous_pageouts = snapshot.pageouts

                        pageout_delta = max(0, snapshot.pageouts - initial_pageouts)
                        if snapshot.memory_pressure is MemoryPressure.CRITICAL:
                            if critical_pressure_since is None:
                                critical_pressure_since = now
                                events.append(
                                    WatchdogEvent(
                                        "critical_pressure_observed",
                                        now,
                                        "grace_started",
                                    )
                                )
                            maximum_critical_pressure_duration = max(
                                maximum_critical_pressure_duration,
                                now - critical_pressure_since,
                            )
                        elif critical_pressure_since is not None:
                            events.append(
                                WatchdogEvent(
                                    "critical_pressure_cleared",
                                    now,
                                    "before_grace_expired",
                                )
                            )
                            critical_pressure_since = None
                        if snapshot.nano_model_loaded:
                            stop_reason = StopReason.NANO_RELOADED
                        elif (
                            critical_pressure_since is not None
                            and now - critical_pressure_since
                            >= self._policy.critical_pressure_grace_seconds
                        ):
                            stop_reason = StopReason.CRITICAL_MEMORY_PRESSURE
                        elif snapshot.memory_pressure is MemoryPressure.UNKNOWN:
                            stop_reason = StopReason.MEASUREMENT_UNAVAILABLE
                        elif self._policy.enforce_headroom_swap_pageout_limits and (
                            snapshot.available_memory_estimate_bytes
                            < self._policy.minimum_abort_headroom_bytes
                        ):
                            stop_reason = StopReason.HEADROOM_BELOW_ABORT_FLOOR
                        elif (
                            self._policy.enforce_headroom_swap_pageout_limits
                            and maximum_swap_delta > self._policy.maximum_swap_delta_bytes
                        ):
                            stop_reason = StopReason.SWAP_BUDGET_EXCEEDED
                        elif (
                            self._policy.enforce_headroom_swap_pageout_limits
                            and
                            pageout_active_since is not None
                            and now - pageout_active_since
                            >= self._policy.sustained_pageout_seconds
                            and pageout_delta > self._policy.pageout_budget_pages
                        ):
                            stop_reason = StopReason.PAGEOUT_BUDGET_EXCEEDED

                return_code = process.poll()
                if return_code is not None:
                    break
                if stop_reason is not None:
                    events.extend(self._terminate_process_group(process, stop_reason))
                    return_code = process.poll()
                    break
                if cancel_event is not None:
                    cancel_event.wait(self._policy.sample_interval_seconds)
                else:
                    time.sleep(self._policy.sample_interval_seconds)

            if return_code is None:
                try:
                    return_code = process.wait(timeout=self._policy.termination_grace_seconds)
                except subprocess.TimeoutExpired:
                    events.extend(self._kill_process_group(process))
                    return_code = process.wait()

            finished_process = time.monotonic()
            events.append(
                WatchdogEvent("child_exited", finished_process, str(return_code))
            )
            recovery = self._observe_recovery(process.pid, baseline, finished_process, events)
            finished = time.monotonic()
            if capture_output_digest:
                stdout_bytes, stdout_sha256 = _stream_summary(stdout_file)
                stderr_bytes, stderr_sha256 = _stream_summary(stderr_file)
            else:
                stdout_bytes, stdout_sha256 = 0, hashlib.sha256(b"").hexdigest()
                stderr_bytes, stderr_sha256 = 0, hashlib.sha256(b"").hexdigest()

        outcome = _derive_outcome(stop_reason, return_code)
        headrooms = [baseline.available_memory_estimate_bytes] + [
            item.available_memory_estimate_bytes for item in samples
        ]
        rss_values = [item.child_rss_bytes for item in samples if item.child_rss_bytes is not None]
        footprints = [
            item.child_phys_footprint_bytes
            for item in samples
            if item.child_phys_footprint_bytes is not None
        ]
        pageout_delta = max(
            (max(0, item.pageouts - baseline.pageouts) for item in samples),
            default=0,
        )
        safe_for_this_run = (
            outcome is ProcessOutcome.COMPLETED
            and bool(samples)
            and recovery.recovered
            and (
                not self._policy.enforce_headroom_swap_pageout_limits
                or (
                    min(headrooms) >= self._policy.minimum_pass_headroom_bytes
                    and maximum_swap_delta <= self._policy.maximum_swap_delta_bytes
                    and maximum_pageout_duration
                    < self._policy.sustained_pageout_seconds
                )
            )
        )
        return WatchdogResult(
            outcome=outcome,
            stop_reason=stop_reason,
            return_code=return_code,
            started_at=started_wall,
            finished_at=datetime.now(timezone.utc).isoformat(),
            elapsed_seconds=finished - started,
            safe_for_this_run=safe_for_this_run,
            resource_limits_enforced=self._policy.enforce_headroom_swap_pageout_limits,
            maximum_swap_delta_bytes=maximum_swap_delta,
            minimum_headroom_bytes=min(headrooms) if headrooms else None,
            maximum_child_rss_bytes=max(rss_values) if rss_values else None,
            maximum_child_phys_footprint_bytes=max(footprints) if footprints else None,
            pageout_delta_pages=pageout_delta,
            maximum_continuous_pageout_seconds=maximum_pageout_duration,
            maximum_continuous_critical_pressure_seconds=(
                maximum_critical_pressure_duration
            ),
            samples=tuple(samples),
            events=tuple(events),
            recovery=recovery,
            stdout_bytes=stdout_bytes,
            stdout_sha256=stdout_sha256,
            stderr_bytes=stderr_bytes,
            stderr_sha256=stderr_sha256,
        )

    def _observe_recovery(
        self,
        child_pid: int,
        baseline: MetricSnapshot,
        process_finished: float,
        events: list[WatchdogEvent],
    ) -> RecoveryAssessment:
        snapshots: list[MetricSnapshot] = []
        for offset in self._policy.recovery_offsets_seconds:
            remaining = (process_finished + offset) - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
            try:
                snapshots.append(self._sampler.sample(child_pid))
            except Exception as error:
                events.append(
                    WatchdogEvent(
                        "recovery_measurement_error",
                        time.monotonic(),
                        _safe_error_name(error),
                    )
                )
                return RecoveryAssessment(
                    recovered=False,
                    baseline_available_bytes=baseline.available_memory_estimate_bytes,
                    final_available_bytes=None,
                    allowed_drop_bytes=self._policy.recovery_tolerance_bytes,
                    child_absent=False,
                    resource_limits_enforced=self._policy.enforce_headroom_swap_pageout_limits,
                    samples=tuple(snapshots),
                    reason="measurement_unavailable",
                )
        final = snapshots[-1]
        child_absent = (
            final.child_rss_bytes in {None, 0}
            and final.child_phys_footprint_bytes in {None, 0}
        )
        memory_recovered = (
            not self._policy.enforce_headroom_swap_pageout_limits
            or final.available_memory_estimate_bytes
            >= baseline.available_memory_estimate_bytes
            - self._policy.recovery_tolerance_bytes
        )
        pressure_recovered = final.memory_pressure not in {
            MemoryPressure.CRITICAL,
            MemoryPressure.UNKNOWN,
        }
        nano_remained_unloaded = all(
            not snapshot.nano_model_loaded for snapshot in snapshots
        )
        reason = None
        if not child_absent:
            reason = "child_memory_still_present"
        elif not nano_remained_unloaded:
            reason = "nano_reloaded_during_recovery"
        elif not pressure_recovered:
            reason = "host_memory_pressure_not_recovered"
        elif not memory_recovered:
            reason = "host_memory_did_not_return_to_baseline"
        return RecoveryAssessment(
            recovered=(
                child_absent
                and memory_recovered
                and pressure_recovered
                and nano_remained_unloaded
            ),
            baseline_available_bytes=baseline.available_memory_estimate_bytes,
            final_available_bytes=final.available_memory_estimate_bytes,
            allowed_drop_bytes=self._policy.recovery_tolerance_bytes,
            child_absent=child_absent,
            resource_limits_enforced=self._policy.enforce_headroom_swap_pageout_limits,
            samples=tuple(snapshots),
            reason=reason,
        )

    def _terminate_process_group(
        self, process: subprocess.Popen[bytes], reason: StopReason
    ) -> list[WatchdogEvent]:
        now = time.monotonic()
        events = [WatchdogEvent("termination_requested", now, reason.value)]
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return events
        except PermissionError:
            # A very short-lived child can leave no signalable process group
            # between poll and killpg on macOS.  Fall back only to the Popen
            # child we own; never broaden the target to another PID or group.
            events.append(
                WatchdogEvent("process_group_signal_denied", time.monotonic(), "SIGTERM")
            )
            try:
                process.terminate()
            except ProcessLookupError:
                return events
        try:
            process.wait(timeout=self._policy.termination_grace_seconds)
        except subprocess.TimeoutExpired:
            events.extend(self._kill_process_group(process))
        return events

    @staticmethod
    def _kill_process_group(process: subprocess.Popen[bytes]) -> list[WatchdogEvent]:
        now = time.monotonic()
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            return [WatchdogEvent("child_killed", now, "SIGKILL")]
        return [WatchdogEvent("process_group_killed", now, "SIGKILL")]

    def _result_without_child(
        self,
        outcome: ProcessOutcome,
        stop_reason: StopReason | None,
        started_wall: str,
        started: float,
        finished: float,
        events: list[WatchdogEvent],
    ) -> WatchdogResult:
        return WatchdogResult(
            outcome=outcome,
            stop_reason=stop_reason,
            return_code=None,
            started_at=started_wall,
            finished_at=datetime.now(timezone.utc).isoformat(),
            elapsed_seconds=finished - started,
            safe_for_this_run=False,
            resource_limits_enforced=self._policy.enforce_headroom_swap_pageout_limits,
            maximum_swap_delta_bytes=0,
            minimum_headroom_bytes=None,
            maximum_child_rss_bytes=None,
            maximum_child_phys_footprint_bytes=None,
            pageout_delta_pages=0,
            maximum_continuous_pageout_seconds=0.0,
            maximum_continuous_critical_pressure_seconds=0.0,
            samples=(),
            events=tuple(events),
            recovery=None,
            stdout_bytes=0,
            stdout_sha256=hashlib.sha256(b"").hexdigest(),
            stderr_bytes=0,
            stderr_sha256=hashlib.sha256(b"").hexdigest(),
        )


def _preflight_stop_reason(
    baseline: MetricSnapshot, policy: SafetyPolicy
) -> StopReason | None:
    if baseline.nano_model_loaded:
        return StopReason.NANO_RELOADED
    if baseline.memory_pressure is MemoryPressure.CRITICAL:
        return StopReason.CRITICAL_MEMORY_PRESSURE
    if baseline.memory_pressure is MemoryPressure.UNKNOWN:
        return StopReason.MEASUREMENT_UNAVAILABLE
    if (
        policy.enforce_headroom_swap_pageout_limits
        and baseline.available_memory_estimate_bytes < policy.minimum_pass_headroom_bytes
    ):
        return StopReason.PREFLIGHT_HEADROOM_INSUFFICIENT
    return None


def _derive_outcome(
    stop_reason: StopReason | None, return_code: int | None
) -> ProcessOutcome:
    if stop_reason is StopReason.USER_CANCELLED:
        return ProcessOutcome.CANCELLED
    if stop_reason is StopReason.HARD_TIMEOUT:
        return ProcessOutcome.TIMED_OUT
    if stop_reason is not None:
        return ProcessOutcome.SAFETY_TERMINATED
    if return_code == 0:
        return ProcessOutcome.COMPLETED
    return ProcessOutcome.CHILD_FAILED


def _heartbeat_signature(path: Path | None) -> tuple[int, int] | None:
    if path is None:
        return None
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return stat.st_mtime_ns, stat.st_size


def _safe_error_name(error: BaseException) -> str:
    """Avoid copying paths, commands, model prompts, or secrets into evidence."""

    if isinstance(error, MeasurementUnavailable):
        return f"MeasurementUnavailable:{error.category}"
    return type(error).__name__


def _stream_summary(file_object: object) -> tuple[int, str]:
    """Hash child output without copying prompts, paths, or secrets to evidence."""

    file_object.seek(0)  # type: ignore[attr-defined]
    digest = hashlib.sha256()
    size = 0
    while payload := file_object.read(64 * 1024):  # type: ignore[attr-defined]
        size += len(payload)
        digest.update(payload)
    return size, digest.hexdigest()
