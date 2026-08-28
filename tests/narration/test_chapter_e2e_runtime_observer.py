from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json

import pytest

import scripts.tts.chapter_e2e_runtime_observer as observer
from scripts.tts.chapter_e2e_runtime_observer import (
    RUNTIME_OBSERVER_DOCKER_INVALID,
    RUNTIME_OBSERVER_ENVIRONMENT_INVALID,
    RUNTIME_OBSERVER_HTTP_INVALID,
    RUNTIME_OBSERVER_HTTP_UNAVAILABLE,
    RUNTIME_OBSERVER_INPUT_INVALID,
    RUNTIME_OBSERVER_SCHEDULE_INVALID,
    RUNTIME_OBSERVER_SIDECAR_UNHEALTHY,
    RUNTIME_OBSERVER_VM_STAT_INVALID,
    RuntimeObserverError,
)


NOW = datetime(2026, 8, 27, 10, 0, 0, tzinfo=timezone.utc)
NOVEL_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
DOCUMENT_ID = "01234567-89ab-4cde-8fab-0123456789ab"
TOKEN = "A" * 43


def _memory_samples(values: list[int]) -> tuple[observer.RuntimeMetricObservation, ...]:
    return tuple(
        observer.RuntimeMetricObservation(
            observed_at=NOW + timedelta(minutes=index),
            sidecar_healthy=True,
            sidecar_restart_count=0,
            health_failure_count=0,
            active_synthesis_count=0,
            queued_job_count=0,
            resident_memory_bytes=value,
        )
        for index, value in enumerate(values)
    )


class FakeClock:
    def __init__(self) -> None:
        self.value = 100.0
        self.sleep_calls: list[float] = []

    def monotonic(self) -> float:
        return self.value

    def utc_now(self) -> datetime:
        return NOW + timedelta(seconds=self.value - 100.0)

    def sleep(self, seconds: float) -> None:
        self.sleep_calls.append(seconds)
        self.value += seconds


class Harness:
    def __init__(self) -> None:
        self.clock = FakeClock()
        self.http_calls: list[tuple[str, str, float, int]] = []
        self.command_calls: list[tuple[tuple[str, ...], float]] = []
        self.active_syntheses = 0
        self.queued_jobs = 0
        self.model_ready = True
        self.worker_ready = True
        self.api_extra: dict[str, object] = {}
        self.api_status = 200
        self.api_headers = {
            "cache-control": "no-store",
            "content-type": "application/json; charset=utf-8",
        }
        self.api_observed_offset = 0
        self.http_latency_seconds = 0.0
        self.restart_count = 0
        self.running = True
        self.container_status = "running"
        self.health_status = "healthy"
        self.failing_streak = 0
        self.memory = "256.5MiB / 7.653GiB"
        self.vm_calls = 0
        self.initial_pageouts = 10
        self.final_pageouts = 10
        self.initial_swapouts = 4
        self.final_swapouts = 4

    def http_get(
        self, path: str, token: str, timeout: float, maximum_bytes: int
    ) -> observer._HttpResult:
        self.http_calls.append((path, token, timeout, maximum_bytes))
        self.clock.value += self.http_latency_seconds
        payload = {
            "model_ready": self.model_ready,
            "worker_ready": self.worker_ready,
            "active_syntheses": self.active_syntheses,
            "queued_jobs": self.queued_jobs,
            "observed_at": (
                self.clock.utc_now()
                + timedelta(seconds=self.api_observed_offset)
            ).isoformat(),
            **self.api_extra,
        }
        return observer._HttpResult(
            status=self.api_status,
            headers=dict(self.api_headers),
            body=json.dumps(payload, separators=(",", ":")).encode(),
        )

    def run_command(
        self, argv: tuple[str, ...], timeout: float
    ) -> observer._CommandResult:
        self.command_calls.append((argv, timeout))
        if argv == (str(observer.FIXED_VM_STAT_PATH),):
            pageouts = (
                self.initial_pageouts if self.vm_calls == 0 else self.final_pageouts
            )
            swapouts = (
                self.initial_swapouts if self.vm_calls == 0 else self.final_swapouts
            )
            self.vm_calls += 1
            raw = (
                "Mach Virtual Memory Statistics: (page size of 16384 bytes)\n"
                "Pages free:                               123.\n"
                f"Pageouts:                                  {pageouts}.\n"
                f"Swapouts:                                  {swapouts}.\n"
            ).encode()
            return observer._CommandResult(0, raw)
        if len(argv) > 1 and argv[1] == "inspect":
            raw = json.dumps(
                {
                    "state": {
                        "Running": self.running,
                        "Status": self.container_status,
                        "Health": {
                            "Status": self.health_status,
                            "FailingStreak": self.failing_streak,
                        },
                    },
                    "restart_count": self.restart_count,
                },
                separators=(",", ":"),
            ).encode()
            return observer._CommandResult(0, raw)
        if len(argv) > 1 and argv[1] == "stats":
            return observer._CommandResult(0, (self.memory + "\n").encode())
        raise AssertionError(f"unexpected command shape: {argv!r}")

    def dependencies(self, *, platform: str = "darwin") -> observer._RuntimeObserverDependencies:
        return observer._RuntimeObserverDependencies(
            http_get=self.http_get,
            run_command=self.run_command,
            monotonic=self.clock.monotonic,
            utc_now=self.clock.utc_now,
            sleep=self.clock.sleep,
            platform=platform,
        )

    def collect(self) -> observer.RuntimeObservationResult:
        return observer._collect_runtime_observations(
            NOVEL_ID,
            DOCUMENT_ID,
            TOKEN,
            dependencies=self.dependencies(),
        )


def test_collects_fixed_31_point_30_minute_window_without_secret_in_authorities() -> None:
    harness = Harness()

    result = harness.collect()

    assert len(result.metric_samples) == 31
    assert result.metric_samples[0].observed_at == NOW
    assert result.metric_samples[-1].observed_at == NOW + timedelta(minutes=30)
    assert all(
        right.observed_at - left.observed_at == timedelta(seconds=60)
        for left, right in zip(
            result.metric_samples, result.metric_samples[1:]
        )
    )
    assert result.host_paging.host_paging_observed is False
    assert result.host_paging.pageout_delta == 0
    assert result.host_paging.swapout_delta == 0
    assert result.max_qwenpaw_observation_latency_ms == 0
    assert result.qwenpaw_slowdown_observed is False
    assert len(harness.http_calls) == 31
    expected_path = (
        f"/api/ai-novel-world-2026/novels/{NOVEL_ID}/documents/{DOCUMENT_ID}/"
        "narration-validation-observation"
    )
    assert {call[0] for call in harness.http_calls} == {expected_path}
    assert {call[1] for call in harness.http_calls} == {TOKEN}
    assert {call[2:] for call in harness.http_calls} == {
        (observer.HTTP_TIMEOUT_SECONDS, observer.MAX_HTTP_BYTES)
    }
    assert TOKEN not in expected_path
    assert TOKEN not in repr(harness.command_calls)
    assert len(harness.clock.sleep_calls) == 30
    assert sum(harness.clock.sleep_calls) == 30 * 60


def test_projects_api_counts_docker_health_memory_and_fixed_container() -> None:
    harness = Harness()
    harness.active_syntheses = 1
    harness.memory = "1.25GiB / 7.653GiB"

    result = harness.collect()

    assert all(sample.sidecar_healthy is True for sample in result.metric_samples)
    assert all(sample.sidecar_restart_count == 0 for sample in result.metric_samples)
    assert all(sample.health_failure_count == 0 for sample in result.metric_samples)
    assert all(sample.active_synthesis_count == 1 for sample in result.metric_samples)
    assert all(sample.queued_job_count == 0 for sample in result.metric_samples)
    assert all(
        sample.resident_memory_bytes == round(1.25 * 1024**3)
        for sample in result.metric_samples
    )
    docker_calls = [call[0] for call in harness.command_calls if len(call[0]) > 1]
    assert len(docker_calls) == 64
    assert all(call[0] == "/usr/local/bin/docker" for call in docker_calls)
    assert all(call[-1] == observer.FIXED_SIDECAR_CONTAINER for call in docker_calls)
    assert {call[1] for call in docker_calls} == {"inspect", "stats"}


def test_reports_host_paging_deltas_from_window_endpoints() -> None:
    harness = Harness()
    harness.final_pageouts = 13
    harness.final_swapouts = 6

    result = harness.collect()

    assert result.host_paging.host_paging_observed is True
    assert result.host_paging.pageout_delta == 3
    assert result.host_paging.swapout_delta == 2
    assert harness.vm_calls == 2


def test_derives_robust_sidecar_memory_trend_and_allows_equal_limit() -> None:
    baseline = 1_000_000_000
    limit = observer.MEMORY_GROWTH_MIN_LIMIT_BYTES
    values = [baseline] * observer.SAMPLE_COUNT
    # The edge medians ignore one low/high fluctuation in each five-point set.
    values[:5] = [0, baseline, baseline, baseline, 9_000_000_000]
    values[-5:] = [
        baseline,
        baseline + limit,
        baseline + limit,
        baseline + limit,
        9_000_000_000,
    ]

    trend = observer.derive_sidecar_memory_trend(_memory_samples(values))

    assert trend.memory_baseline_median_bytes == baseline
    assert trend.memory_tail_median_bytes == baseline + limit
    assert trend.memory_growth_bytes == limit
    assert trend.memory_growth_limit_bytes == limit
    assert trend.sidecar_memory_growth_observed is False


def test_sidecar_memory_trend_uses_ceil_five_percent_and_strict_growth() -> None:
    baseline = 4_000_000_001
    percentage_limit = (baseline * 5 + 99) // 100
    values = [baseline] * observer.SAMPLE_COUNT
    values[-5:] = [baseline + percentage_limit + 1] * 5

    trend = observer.derive_sidecar_memory_trend(_memory_samples(values))

    assert trend.memory_growth_limit_bytes == percentage_limit
    assert trend.memory_growth_bytes == percentage_limit + 1
    assert trend.sidecar_memory_growth_observed is True


@pytest.mark.parametrize(
    "samples",
    (
        (),
        tuple([object()] * observer.SAMPLE_COUNT),
        _memory_samples([0] * (observer.SAMPLE_COUNT - 1)),
        _memory_samples([0] * (observer.SAMPLE_COUNT - 1) + [-1]),
    ),
)
def test_sidecar_memory_trend_rejects_invalid_sample_windows(samples: object) -> None:
    with pytest.raises(
        RuntimeObserverError,
        match=f"^{RUNTIME_OBSERVER_DOCKER_INVALID}$",
    ):
        observer.derive_sidecar_memory_trend(samples)


def test_derives_qwenpaw_slowdown_only_from_measured_http_latency() -> None:
    harness = Harness()
    harness.http_latency_seconds = 2.0

    result = harness.collect()

    assert result.max_qwenpaw_observation_latency_ms == 2_000
    assert result.qwenpaw_slowdown_observed is True


@pytest.mark.parametrize(
    ("novel_id", "document_id", "token"),
    [
        (NOVEL_ID.upper(), DOCUMENT_ID, TOKEN),
        ("not-a-uuid", DOCUMENT_ID, TOKEN),
        (NOVEL_ID, DOCUMENT_ID.upper(), TOKEN),
        (NOVEL_ID, DOCUMENT_ID, "short"),
        (NOVEL_ID, DOCUMENT_ID, "A" * 42 + "\n"),
    ],
)
def test_rejects_noncanonical_scope_and_invalid_token_without_io(
    novel_id: str, document_id: str, token: str
) -> None:
    harness = Harness()

    with pytest.raises(RuntimeObserverError) as captured:
        observer._collect_runtime_observations(
            novel_id,
            document_id,
            token,
            dependencies=harness.dependencies(),
        )

    assert captured.value.code == RUNTIME_OBSERVER_INPUT_INVALID
    assert str(captured.value) == RUNTIME_OBSERVER_INPUT_INVALID
    assert not harness.http_calls
    assert not harness.command_calls


def test_rejects_non_macos_environment_before_observation_io() -> None:
    harness = Harness()

    with pytest.raises(RuntimeObserverError) as captured:
        observer._collect_runtime_observations(
            NOVEL_ID,
            DOCUMENT_ID,
            TOKEN,
            dependencies=harness.dependencies(platform="linux"),
        )

    assert captured.value.code == RUNTIME_OBSERVER_ENVIRONMENT_INVALID
    assert not harness.http_calls
    assert not harness.command_calls


@pytest.mark.parametrize(
    "mutation",
    [
        lambda harness: setattr(harness, "api_status", 503),
        lambda harness: harness.api_headers.pop("cache-control"),
        lambda harness: harness.api_headers.update({"content-type": "text/plain"}),
        lambda harness: harness.api_extra.update({"unexpected": True}),
        lambda harness: setattr(harness, "model_ready", False),
        lambda harness: setattr(harness, "worker_ready", False),
        lambda harness: setattr(harness, "active_syntheses", 2),
        lambda harness: setattr(harness, "queued_jobs", 1),
        lambda harness: setattr(harness, "api_observed_offset", 31),
    ],
)
def test_hidden_api_projection_is_exact_and_fail_closed(mutation) -> None:
    harness = Harness()
    mutation(harness)

    with pytest.raises(RuntimeObserverError) as captured:
        harness.collect()

    assert captured.value.code == RUNTIME_OBSERVER_HTTP_INVALID
    assert str(captured.value) == RUNTIME_OBSERVER_HTTP_INVALID


def test_transport_exception_is_redacted_to_stable_code() -> None:
    harness = Harness()

    def broken_http(
        path: str, token: str, timeout: float, maximum_bytes: int
    ) -> observer._HttpResult:
        del path, timeout, maximum_bytes
        raise RuntimeError(f"transport accidentally mentioned {token}")

    dependencies = replace(harness.dependencies(), http_get=broken_http)
    with pytest.raises(RuntimeObserverError) as captured:
        observer._collect_runtime_observations(
            NOVEL_ID, DOCUMENT_ID, TOKEN, dependencies=dependencies
        )

    assert captured.value.code == RUNTIME_OBSERVER_HTTP_UNAVAILABLE
    assert str(captured.value) == RUNTIME_OBSERVER_HTTP_UNAVAILABLE
    assert TOKEN not in str(captured.value)


def test_rejects_duplicate_json_members() -> None:
    harness = Harness()
    observed = NOW.isoformat()

    def duplicate_http(
        path: str, token: str, timeout: float, maximum_bytes: int
    ) -> observer._HttpResult:
        del path, token, timeout, maximum_bytes
        return observer._HttpResult(
            200,
            {
                "cache-control": "no-store",
                "content-type": "application/json",
            },
            (
                '{"model_ready":true,"model_ready":true,'
                '"worker_ready":true,"active_syntheses":0,'
                f'"queued_jobs":0,"observed_at":"{observed}"}}'
            ).encode(),
        )

    dependencies = replace(harness.dependencies(), http_get=duplicate_http)
    with pytest.raises(RuntimeObserverError) as captured:
        observer._collect_runtime_observations(
            NOVEL_ID, DOCUMENT_ID, TOKEN, dependencies=dependencies
        )

    assert captured.value.code == RUNTIME_OBSERVER_HTTP_INVALID


@pytest.mark.parametrize(
    "mutation",
    [
        lambda harness: setattr(harness, "restart_count", 1),
        lambda harness: setattr(harness, "running", False),
        lambda harness: setattr(harness, "container_status", "exited"),
        lambda harness: setattr(harness, "health_status", "unhealthy"),
        lambda harness: setattr(harness, "failing_streak", 1),
    ],
)
def test_unhealthy_or_restarted_fixed_sidecar_never_starts_the_window(mutation) -> None:
    harness = Harness()
    mutation(harness)

    with pytest.raises(RuntimeObserverError) as captured:
        harness.collect()

    assert captured.value.code == RUNTIME_OBSERVER_SIDECAR_UNHEALTHY
    assert len(harness.http_calls) == 0


def test_transient_post_synthesis_health_recovers_before_the_fixed_window() -> None:
    harness = Harness()
    original = harness.run_command
    unhealthy_inspects = 1

    def transient_run_command(
        argv: tuple[str, ...], timeout: float
    ) -> observer._CommandResult:
        nonlocal unhealthy_inspects
        if len(argv) > 1 and argv[1] == "inspect" and unhealthy_inspects:
            unhealthy_inspects -= 1
            current = harness.health_status
            harness.health_status = "unhealthy"
            try:
                return original(argv, timeout)
            finally:
                harness.health_status = current
        return original(argv, timeout)

    dependencies = replace(
        harness.dependencies(),
        run_command=transient_run_command,
    )

    result = observer._collect_runtime_observations(
        NOVEL_ID,
        DOCUMENT_ID,
        TOKEN,
        dependencies=dependencies,
    )

    assert len(result.metric_samples) == observer.SAMPLE_COUNT
    assert harness.clock.sleep_calls[0] == observer.SIDECAR_READY_POLL_INTERVAL_SECONDS
    assert result.metric_samples[0].observed_at == NOW + timedelta(seconds=2)


@pytest.mark.parametrize("memory", ["", "NaNMiB / 1GiB", "12XB / 1GiB", "1MiB"])
def test_rejects_ambiguous_docker_memory(memory: str) -> None:
    harness = Harness()
    harness.memory = memory

    with pytest.raises(RuntimeObserverError) as captured:
        harness.collect()

    assert captured.value.code == RUNTIME_OBSERVER_DOCKER_INVALID


def test_rejects_vm_stat_counter_regression() -> None:
    harness = Harness()
    harness.final_pageouts = 9

    with pytest.raises(RuntimeObserverError) as captured:
        harness.collect()

    assert captured.value.code == RUNTIME_OBSERVER_VM_STAT_INVALID


def test_monotonic_deadline_overrun_is_stable_failure() -> None:
    harness = Harness()

    def late_sleep(seconds: float) -> None:
        harness.clock.value += seconds + observer.SAMPLE_DEADLINE_GRACE_SECONDS + 1

    dependencies = replace(harness.dependencies(), sleep=late_sleep)
    with pytest.raises(RuntimeObserverError) as captured:
        observer._collect_runtime_observations(
            NOVEL_ID, DOCUMENT_ID, TOKEN, dependencies=dependencies
        )

    assert captured.value.code == RUNTIME_OBSERVER_SCHEDULE_INVALID
    assert len(harness.http_calls) == 1
