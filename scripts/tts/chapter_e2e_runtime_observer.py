#!/usr/bin/env python3
"""Fixed, read-only T4-K runtime metrics observer.

The public entry point accepts only the exact validation scope and its
in-memory bearer token.  Network authority, API path, Docker container,
sampling cadence and sample count are fixed here.  The token is sent only in
the validation header and is never included in a URL, command, result or
error message.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import http.client
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Callable, Final, Mapping
from uuid import UUID

from scripts.tts.chapter_e2e_controller_host import RuntimeMetricObservation


FIXED_HOST: Final = "127.0.0.1"
FIXED_PORT: Final = 18088
FIXED_API_PREFIX: Final = "/api/ai-novel-world-2026"
FIXED_OBSERVATION_SUFFIX: Final = "narration-validation-observation"
FIXED_SIDECAR_CONTAINER: Final = "ai-novel-2026-moss-tts-sidecar"
VALIDATION_HEADER: Final = "X-AI-Novel-TTS-Validation"
FIXED_DOCKER_PATH: Final = Path("/usr/local/bin/docker")
FIXED_VM_STAT_PATH: Final = Path("/usr/bin/vm_stat")
SAMPLE_INTERVAL_SECONDS: Final = 60
SAMPLE_COUNT: Final = 31
REQUIRED_WINDOW_SECONDS: Final = 30 * 60
SAMPLE_DEADLINE_GRACE_SECONDS: Final = 5
HTTP_TIMEOUT_SECONDS: Final = 4
COMMAND_TIMEOUT_SECONDS: Final = 4
MAX_HTTP_BYTES: Final = 16 * 1024
MAX_COMMAND_BYTES: Final = 64 * 1024
MAX_CLOCK_SKEW_SECONDS: Final = 30
MAX_API_OBSERVATION_GAP_SECONDS: Final = 65
QWENPAW_SLOW_OBSERVATION_MILLISECONDS: Final = 2_000
MEMORY_TREND_WINDOW_SIZE: Final = 5
MEMORY_GROWTH_MIN_LIMIT_BYTES: Final = 128 * 1024 * 1024
MEMORY_GROWTH_PERCENT_NUMERATOR: Final = 5
MEMORY_GROWTH_PERCENT_DENOMINATOR: Final = 100

RUNTIME_OBSERVER_INPUT_INVALID: Final = "RUNTIME_OBSERVER_INPUT_INVALID"
RUNTIME_OBSERVER_ENVIRONMENT_INVALID: Final = (
    "RUNTIME_OBSERVER_ENVIRONMENT_INVALID"
)
RUNTIME_OBSERVER_HTTP_UNAVAILABLE: Final = (
    "RUNTIME_OBSERVER_HTTP_UNAVAILABLE"
)
RUNTIME_OBSERVER_HTTP_INVALID: Final = "RUNTIME_OBSERVER_HTTP_INVALID"
RUNTIME_OBSERVER_DOCKER_UNAVAILABLE: Final = (
    "RUNTIME_OBSERVER_DOCKER_UNAVAILABLE"
)
RUNTIME_OBSERVER_DOCKER_INVALID: Final = "RUNTIME_OBSERVER_DOCKER_INVALID"
RUNTIME_OBSERVER_VM_STAT_UNAVAILABLE: Final = (
    "RUNTIME_OBSERVER_VM_STAT_UNAVAILABLE"
)
RUNTIME_OBSERVER_VM_STAT_INVALID: Final = "RUNTIME_OBSERVER_VM_STAT_INVALID"
RUNTIME_OBSERVER_SIDECAR_UNHEALTHY: Final = (
    "RUNTIME_OBSERVER_SIDECAR_UNHEALTHY"
)
SIDECAR_READY_POLL_ATTEMPTS: Final = 30
SIDECAR_READY_POLL_INTERVAL_SECONDS: Final = 2.0
RUNTIME_OBSERVER_SCHEDULE_INVALID: Final = (
    "RUNTIME_OBSERVER_SCHEDULE_INVALID"
)

_TOKEN = re.compile(r"^[A-Za-z0-9_-]{43,128}$")
_MEMORY = re.compile(
    r"^(?P<value>(?:0|[1-9][0-9]*)(?:\.[0-9]+)?)"
    r"(?P<unit>B|kB|KB|KiB|MB|MiB|GB|GiB|TB|TiB)$"
)
_VM_COUNTER = re.compile(r"^(?P<name>[A-Za-z ]+):\s+(?P<value>[0-9]+)\.$")
_VM_PAGE_SIZE = re.compile(r"page size of (?P<size>[0-9]+) bytes")


class RuntimeObserverError(RuntimeError):
    """Fail-closed observer error exposing only a stable code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class HostPagingSummary:
    """Host paging delta observed across the same fixed sample window."""

    host_paging_observed: bool
    pageout_delta: int
    swapout_delta: int


@dataclass(frozen=True, slots=True)
class SidecarMemoryTrendSummary:
    """Deterministic trend derived from the fixed Sidecar memory samples."""

    memory_baseline_median_bytes: int
    memory_tail_median_bytes: int
    memory_growth_bytes: int
    memory_growth_limit_bytes: int
    sidecar_memory_growth_observed: bool


@dataclass(frozen=True, slots=True)
class RuntimeObservationResult:
    metric_samples: tuple[RuntimeMetricObservation, ...]
    host_paging: HostPagingSummary
    max_qwenpaw_observation_latency_ms: int
    qwenpaw_slowdown_observed: bool


@dataclass(frozen=True, slots=True)
class _HttpResult:
    status: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True, slots=True)
class _CommandResult:
    returncode: int
    stdout: bytes


@dataclass(frozen=True, slots=True)
class _DockerObservation:
    healthy: bool
    restart_count: int
    health_failure_count: int
    resident_memory_bytes: int


@dataclass(frozen=True, slots=True)
class _PagingCounters:
    pageouts: int
    swapouts: int


@dataclass(frozen=True, slots=True)
class _RuntimeObserverDependencies:
    http_get: Callable[[str, str, float, int], _HttpResult]
    run_command: Callable[[tuple[str, ...], float], _CommandResult]
    monotonic: Callable[[], float]
    utc_now: Callable[[], datetime]
    sleep: Callable[[float], None]
    platform: str


def derive_sidecar_memory_trend(
    metric_samples: object,
) -> SidecarMemoryTrendSummary:
    """Derive a robust, Sidecar-scoped trend without using host paging.

    The fixed observation window is already prewarmed.  Five-point medians at
    each edge avoid turning a single ``docker stats`` fluctuation into a leak
    verdict.  The threshold is intentionally integer-only and equality passes.
    """

    if (
        type(metric_samples) is not tuple
        or len(metric_samples) != SAMPLE_COUNT
        or any(
            type(sample) is not RuntimeMetricObservation
            or type(sample.resident_memory_bytes) is not int
            or sample.resident_memory_bytes < 0
            for sample in metric_samples
        )
    ):
        raise _error(RUNTIME_OBSERVER_DOCKER_INVALID)

    baseline_values = sorted(
        sample.resident_memory_bytes
        for sample in metric_samples[:MEMORY_TREND_WINDOW_SIZE]
    )
    tail_values = sorted(
        sample.resident_memory_bytes
        for sample in metric_samples[-MEMORY_TREND_WINDOW_SIZE:]
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
    return SidecarMemoryTrendSummary(
        memory_baseline_median_bytes=baseline,
        memory_tail_median_bytes=tail,
        memory_growth_bytes=growth,
        memory_growth_limit_bytes=limit,
        sidecar_memory_growth_observed=growth > limit,
    )


def _error(code: str) -> RuntimeObserverError:
    return RuntimeObserverError(code)


def _canonical_uuid(value: object) -> str:
    if type(value) is not str:
        raise _error(RUNTIME_OBSERVER_INPUT_INVALID)
    try:
        canonical = str(UUID(value))
    except (AttributeError, ValueError):
        raise _error(RUNTIME_OBSERVER_INPUT_INVALID) from None
    if value != canonical:
        raise _error(RUNTIME_OBSERVER_INPUT_INVALID)
    return canonical


def _validate_token(value: object) -> str:
    if type(value) is not str or _TOKEN.fullmatch(value) is None:
        raise _error(RUNTIME_OBSERVER_INPUT_INVALID)
    return value


def _fixed_path(novel_id: str, document_id: str) -> str:
    return (
        f"{FIXED_API_PREFIX}/novels/{novel_id}/documents/{document_id}/"
        f"{FIXED_OBSERVATION_SUFFIX}"
    )


def _http_get(
    path: str,
    token: str,
    timeout: float,
    maximum_bytes: int,
) -> _HttpResult:
    connection = http.client.HTTPConnection(
        FIXED_HOST, FIXED_PORT, timeout=timeout
    )
    try:
        connection.request(
            "GET",
            path,
            headers={
                "Accept": "application/json",
                "Cache-Control": "no-store",
                VALIDATION_HEADER: token,
            },
        )
        response = connection.getresponse()
        body = response.read(maximum_bytes + 1)
        if len(body) > maximum_bytes:
            raise _error(RUNTIME_OBSERVER_HTTP_INVALID)
        return _HttpResult(
            status=response.status,
            headers={key.lower(): value for key, value in response.getheaders()},
            body=body,
        )
    except RuntimeObserverError:
        raise
    except (OSError, TimeoutError, http.client.HTTPException):
        raise _error(RUNTIME_OBSERVER_HTTP_UNAVAILABLE) from None
    finally:
        connection.close()


def _run_command(argv: tuple[str, ...], timeout: float) -> _CommandResult:
    try:
        completed = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                "LANG": "C",
                "LC_ALL": "C",
            },
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        raise _error(RUNTIME_OBSERVER_ENVIRONMENT_INVALID) from None
    if len(completed.stdout) > MAX_COMMAND_BYTES:
        raise _error(RUNTIME_OBSERVER_ENVIRONMENT_INVALID)
    return _CommandResult(completed.returncode, completed.stdout)


def _default_dependencies() -> _RuntimeObserverDependencies:
    return _RuntimeObserverDependencies(
        http_get=_http_get,
        run_command=_run_command,
        monotonic=time.monotonic,
        utc_now=lambda: datetime.now(timezone.utc),
        sleep=time.sleep,
        platform=sys.platform,
    )


def _monotonic(
    dependencies: _RuntimeObserverDependencies,
) -> float:
    try:
        value = dependencies.monotonic()
    except Exception:
        raise _error(RUNTIME_OBSERVER_SCHEDULE_INVALID) from None
    if type(value) not in {int, float} or not math.isfinite(float(value)):
        raise _error(RUNTIME_OBSERVER_SCHEDULE_INVALID)
    return float(value)


def _utc_now(dependencies: _RuntimeObserverDependencies) -> datetime:
    try:
        value = dependencies.utc_now()
    except Exception:
        raise _error(RUNTIME_OBSERVER_SCHEDULE_INVALID) from None
    if type(value) is not datetime or value.tzinfo is None:
        raise _error(RUNTIME_OBSERVER_SCHEDULE_INVALID)
    return value.astimezone(timezone.utc)


def _json_mapping(raw: bytes, *, code: str) -> Mapping[str, object]:
    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    def invalid_constant(value: str) -> object:
        del value
        raise ValueError

    try:
        decoded = raw.decode("utf-8", errors="strict")
        value = json.loads(
            decoded,
            object_pairs_hook=object_pairs,
            parse_constant=invalid_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise _error(code) from None
    if type(value) is not dict:
        raise _error(code)
    return value


def _parse_api_observation(
    result: _HttpResult,
    *,
    current_time: datetime,
) -> tuple[int, int, datetime]:
    if (
        type(result) is not _HttpResult
        or type(result.status) is not int
        or result.status != 200
        or type(result.headers) is not dict
        or result.headers.get("cache-control", "").lower() != "no-store"
        or not result.headers.get("content-type", "").lower().startswith(
            "application/json"
        )
        or type(result.body) is not bytes
        or not result.body
        or len(result.body) > MAX_HTTP_BYTES
    ):
        raise _error(RUNTIME_OBSERVER_HTTP_INVALID)
    value = _json_mapping(result.body, code=RUNTIME_OBSERVER_HTTP_INVALID)
    if set(value) != {
        "model_ready",
        "worker_ready",
        "active_syntheses",
        "queued_jobs",
        "observed_at",
    }:
        raise _error(RUNTIME_OBSERVER_HTTP_INVALID)
    model_ready = value["model_ready"]
    worker_ready = value["worker_ready"]
    active = value["active_syntheses"]
    queued = value["queued_jobs"]
    observed_raw = value["observed_at"]
    if (
        type(model_ready) is not bool
        or type(worker_ready) is not bool
        or model_ready is not True
        or worker_ready is not True
        or type(active) is not int
        or not 0 <= active <= 1
        or type(queued) is not int
        or queued != 0
        or type(observed_raw) is not str
        or type(current_time) is not datetime
        or current_time.tzinfo is None
    ):
        raise _error(RUNTIME_OBSERVER_HTTP_INVALID)
    try:
        observed = datetime.fromisoformat(observed_raw.replace("Z", "+00:00"))
    except ValueError:
        raise _error(RUNTIME_OBSERVER_HTTP_INVALID) from None
    if (
        observed.tzinfo is None
        or observed.utcoffset() != timedelta(0)
        or abs((observed - current_time.astimezone(timezone.utc)).total_seconds())
        > MAX_CLOCK_SKEW_SECONDS
    ):
        raise _error(RUNTIME_OBSERVER_HTTP_INVALID)
    return active, queued, observed.astimezone(timezone.utc)


def _parse_memory(value: object) -> int:
    if type(value) is not str:
        raise _error(RUNTIME_OBSERVER_DOCKER_INVALID)
    match = _MEMORY.fullmatch(value.strip())
    if match is None:
        raise _error(RUNTIME_OBSERVER_DOCKER_INVALID)
    factors = {
        "B": 1,
        "kB": 1000,
        "KB": 1000,
        "KiB": 1024,
        "MB": 1000**2,
        "MiB": 1024**2,
        "GB": 1000**3,
        "GiB": 1024**3,
        "TB": 1000**4,
        "TiB": 1024**4,
    }
    amount = float(match.group("value"))
    result = round(amount * factors[match.group("unit")])
    if not math.isfinite(amount) or result < 0 or result > 2**63 - 1:
        raise _error(RUNTIME_OBSERVER_DOCKER_INVALID)
    return result


def _docker_observation(
    run_command: Callable[[tuple[str, ...], float], _CommandResult],
) -> _DockerObservation:
    inspect_argv = (
        str(FIXED_DOCKER_PATH),
        "inspect",
        "--type",
        "container",
        "--format",
        '{"state":{{json .State}},"restart_count":{{json .RestartCount}}}',
        FIXED_SIDECAR_CONTAINER,
    )
    stats_argv = (
        str(FIXED_DOCKER_PATH),
        "stats",
        "--no-stream",
        "--format",
        "{{.MemUsage}}",
        FIXED_SIDECAR_CONTAINER,
    )
    try:
        inspected = run_command(inspect_argv, COMMAND_TIMEOUT_SECONDS)
        stats = run_command(stats_argv, COMMAND_TIMEOUT_SECONDS)
    except RuntimeObserverError:
        raise
    except Exception:
        raise _error(RUNTIME_OBSERVER_DOCKER_UNAVAILABLE) from None
    if (
        type(inspected) is not _CommandResult
        or type(stats) is not _CommandResult
        or inspected.returncode != 0
        or stats.returncode != 0
        or type(inspected.stdout) is not bytes
        or type(stats.stdout) is not bytes
        or len(inspected.stdout) > MAX_COMMAND_BYTES
        or len(stats.stdout) > MAX_COMMAND_BYTES
    ):
        raise _error(RUNTIME_OBSERVER_DOCKER_UNAVAILABLE)
    value = _json_mapping(
        inspected.stdout.strip(), code=RUNTIME_OBSERVER_DOCKER_INVALID
    )
    if set(value) != {"state", "restart_count"}:
        raise _error(RUNTIME_OBSERVER_DOCKER_INVALID)
    state = value["state"]
    restart_count = value["restart_count"]
    if (
        type(state) is not dict
        or type(restart_count) is not int
        or restart_count < 0
    ):
        raise _error(RUNTIME_OBSERVER_DOCKER_INVALID)
    health = state.get("Health")
    running = state.get("Running")
    status = state.get("Status")
    if type(health) is not dict:
        raise _error(RUNTIME_OBSERVER_DOCKER_INVALID)
    health_status = health.get("Status")
    failing_streak = health.get("FailingStreak")
    if (
        type(running) is not bool
        or type(status) is not str
        or type(health_status) is not str
        or type(failing_streak) is not int
        or failing_streak < 0
    ):
        raise _error(RUNTIME_OBSERVER_DOCKER_INVALID)
    try:
        memory_text = stats.stdout.decode("ascii", errors="strict").strip()
    except UnicodeDecodeError:
        raise _error(RUNTIME_OBSERVER_DOCKER_INVALID) from None
    if "\n" in memory_text or " / " not in memory_text:
        raise _error(RUNTIME_OBSERVER_DOCKER_INVALID)
    resident = _parse_memory(memory_text.split(" / ", 1)[0])
    healthy = (
        running is True
        and status == "running"
        and health_status == "healthy"
    )
    if not healthy or restart_count != 0 or failing_streak != 0:
        raise _error(RUNTIME_OBSERVER_SIDECAR_UNHEALTHY)
    return _DockerObservation(
        healthy=True,
        restart_count=restart_count,
        health_failure_count=failing_streak,
        resident_memory_bytes=resident,
    )


def _paging_counters(
    run_command: Callable[[tuple[str, ...], float], _CommandResult],
) -> _PagingCounters:
    try:
        result = run_command((str(FIXED_VM_STAT_PATH),), COMMAND_TIMEOUT_SECONDS)
    except RuntimeObserverError:
        raise
    except Exception:
        raise _error(RUNTIME_OBSERVER_VM_STAT_UNAVAILABLE) from None
    if (
        type(result) is not _CommandResult
        or result.returncode != 0
        or type(result.stdout) is not bytes
        or not result.stdout
        or len(result.stdout) > MAX_COMMAND_BYTES
    ):
        raise _error(RUNTIME_OBSERVER_VM_STAT_UNAVAILABLE)
    try:
        text = result.stdout.decode("ascii", errors="strict")
    except UnicodeDecodeError:
        raise _error(RUNTIME_OBSERVER_VM_STAT_INVALID) from None
    lines = text.splitlines()
    if not lines or _VM_PAGE_SIZE.search(lines[0]) is None:
        raise _error(RUNTIME_OBSERVER_VM_STAT_INVALID)
    counters: dict[str, int] = {}
    for line in lines[1:]:
        match = _VM_COUNTER.fullmatch(line.strip())
        if match is not None:
            counters[match.group("name")] = int(match.group("value"))
    if "Pageouts" not in counters or "Swapouts" not in counters:
        raise _error(RUNTIME_OBSERVER_VM_STAT_INVALID)
    return _PagingCounters(
        pageouts=counters["Pageouts"],
        swapouts=counters["Swapouts"],
    )


def _collect_runtime_observations(
    novel_id: str,
    document_id: str,
    validation_token: str,
    *,
    dependencies: _RuntimeObserverDependencies,
) -> RuntimeObservationResult:
    novel = _canonical_uuid(novel_id)
    document = _canonical_uuid(document_id)
    token = _validate_token(validation_token)
    if (
        type(dependencies) is not _RuntimeObserverDependencies
        or dependencies.platform != "darwin"
    ):
        raise _error(RUNTIME_OBSERVER_ENVIRONMENT_INVALID)
    path = _fixed_path(novel, document)
    # A real Nano synthesis can finish just before Docker's next successful
    # health probe is published.  Start the fixed 30-minute measurement only
    # from a freshly observed healthy, non-restarted Sidecar; every one of the
    # subsequent 31 samples remains subject to the original strict gate.
    for attempt in range(SIDECAR_READY_POLL_ATTEMPTS):
        try:
            _docker_observation(dependencies.run_command)
            break
        except RuntimeObserverError as error:
            if (
                error.code != RUNTIME_OBSERVER_SIDECAR_UNHEALTHY
                or attempt == SIDECAR_READY_POLL_ATTEMPTS - 1
            ):
                raise
            try:
                dependencies.sleep(SIDECAR_READY_POLL_INTERVAL_SECONDS)
            except Exception:
                raise _error(RUNTIME_OBSERVER_SCHEDULE_INVALID) from None
    monotonic_started = _monotonic(dependencies)
    wall_started = _utc_now(dependencies)
    wall_anchor = wall_started.replace(microsecond=0)
    paging_started = _paging_counters(dependencies.run_command)
    samples: list[RuntimeMetricObservation] = []
    observation_latencies_ms: list[int] = []
    previous_api_observed_at: datetime | None = None
    for index in range(SAMPLE_COUNT):
        target = float(monotonic_started) + index * SAMPLE_INTERVAL_SECONDS
        before_sleep = _monotonic(dependencies)
        remaining = target - before_sleep
        if remaining > 0:
            try:
                dependencies.sleep(remaining)
            except Exception:
                raise _error(RUNTIME_OBSERVER_SCHEDULE_INVALID) from None
        sample_started = _monotonic(dependencies)
        if (
            sample_started < target
            or sample_started > target + SAMPLE_DEADLINE_GRACE_SECONDS
        ):
            raise _error(RUNTIME_OBSERVER_SCHEDULE_INVALID)
        try:
            http_started = _monotonic(dependencies)
            http_result = dependencies.http_get(
                path, token, HTTP_TIMEOUT_SECONDS, MAX_HTTP_BYTES
            )
            http_ended = _monotonic(dependencies)
        except RuntimeObserverError:
            raise
        except Exception:
            raise _error(RUNTIME_OBSERVER_HTTP_UNAVAILABLE) from None
        latency_ms = round((http_ended - http_started) * 1_000)
        if latency_ms < 0 or latency_ms > HTTP_TIMEOUT_SECONDS * 1_000:
            raise _error(RUNTIME_OBSERVER_SCHEDULE_INVALID)
        observation_latencies_ms.append(latency_ms)
        active, queued, api_observed_at = _parse_api_observation(
            http_result, current_time=_utc_now(dependencies)
        )
        if previous_api_observed_at is not None and (
            api_observed_at <= previous_api_observed_at
            or (api_observed_at - previous_api_observed_at).total_seconds()
            > MAX_API_OBSERVATION_GAP_SECONDS
        ):
            raise _error(RUNTIME_OBSERVER_HTTP_INVALID)
        previous_api_observed_at = api_observed_at
        docker = _docker_observation(dependencies.run_command)
        samples.append(
            RuntimeMetricObservation(
                observed_at=wall_anchor
                + timedelta(seconds=index * SAMPLE_INTERVAL_SECONDS),
                sidecar_healthy=docker.healthy,
                sidecar_restart_count=docker.restart_count,
                health_failure_count=docker.health_failure_count,
                active_synthesis_count=active,
                queued_job_count=queued,
                resident_memory_bytes=docker.resident_memory_bytes,
            )
        )
    monotonic_ended = _monotonic(dependencies)
    if monotonic_ended - monotonic_started < REQUIRED_WINDOW_SECONDS:
        raise _error(RUNTIME_OBSERVER_SCHEDULE_INVALID)
    paging_ended = _paging_counters(dependencies.run_command)
    pageout_delta = paging_ended.pageouts - paging_started.pageouts
    swapout_delta = paging_ended.swapouts - paging_started.swapouts
    if pageout_delta < 0 or swapout_delta < 0:
        raise _error(RUNTIME_OBSERVER_VM_STAT_INVALID)
    return RuntimeObservationResult(
        metric_samples=tuple(samples),
        host_paging=HostPagingSummary(
            host_paging_observed=pageout_delta > 0 or swapout_delta > 0,
            pageout_delta=pageout_delta,
            swapout_delta=swapout_delta,
        ),
        max_qwenpaw_observation_latency_ms=max(observation_latencies_ms),
        qwenpaw_slowdown_observed=(
            max(observation_latencies_ms)
            >= QWENPAW_SLOW_OBSERVATION_MILLISECONDS
        ),
    )


def collect_runtime_observations(
    novel_id: str,
    document_id: str,
    validation_token: str,
) -> RuntimeObservationResult:
    """Collect the fixed 31-point/30-minute T4-K observation window."""

    return _collect_runtime_observations(
        novel_id,
        document_id,
        validation_token,
        dependencies=_default_dependencies(),
    )


__all__ = [
    "HostPagingSummary",
    "SidecarMemoryTrendSummary",
    "RuntimeObservationResult",
    "RuntimeObserverError",
    "collect_runtime_observations",
    "derive_sidecar_memory_trend",
]
