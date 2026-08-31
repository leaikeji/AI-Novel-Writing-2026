from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parent


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


watchdog = load_module(ROOT / "macos_memory_watchdog.py", "macos_memory_watchdog")
orchestrator = load_module(ROOT / "t2_orchestrator.py", "vg40_t2_orchestrator")


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def snapshot(*, nano=False, pressure=watchdog.MemoryPressure.NORMAL, available=2 * watchdog.GIB):
    return watchdog.MetricSnapshot(
        monotonic_seconds=time.monotonic(),
        observed_at=datetime.now(timezone.utc).isoformat(),
        child_pid=None,
        child_rss_bytes=None,
        child_phys_footprint_bytes=None,
        physical_memory_bytes=16 * watchdog.GIB,
        available_memory_estimate_bytes=available,
        memory_pressure=pressure,
        swap_used_bytes=8 * watchdog.GIB,
        pageins=1,
        pageouts=2,
        nano_model_loaded=nano,
    )


def test_loopback_health_probe_requires_boolean_residency():
    loaded = orchestrator.probe_nano_loaded(
        "http://127.0.0.1:18088/api/ai-novel-world-2026/health",
        opener=lambda *args, **kwargs: Response(b'{"narration":{"model_loaded":false}}'),
    )
    assert loaded is False
    for url in ("https://127.0.0.1/health", "http://example.com/health"):
        try:
            orchestrator.probe_nano_loaded(url, opener=lambda *args, **kwargs: None)
        except orchestrator.T2OrchestratorError:
            pass
        else:
            raise AssertionError("non-loopback health URL must fail closed")


def test_stopped_container_proves_nano_absent_without_health_request():
    docker_binary = Path(sys.executable)
    calls = []

    def runner(*args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args[0], 0, stdout="false\n", stderr="")

    assert orchestrator.probe_nano_loaded_or_stopped(
        "http://127.0.0.1:18088/api/ai-novel-world-2026/health",
        container_name="ai-novel-2026-moss-tts-sidecar",
        docker_binary=docker_binary,
        opener=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("stopped container must not call health")
        ),
        runner=runner,
    ) is False
    assert calls


def test_running_container_requires_authoritative_health():
    docker_binary = Path(sys.executable)

    def runner(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, stdout="true\n", stderr="")

    loaded = orchestrator.probe_nano_loaded_or_stopped(
        "http://127.0.0.1:18088/api/ai-novel-world-2026/health",
        container_name="ai-novel-2026-moss-tts-sidecar",
        docker_binary=docker_binary,
        opener=lambda *args, **kwargs: Response(
            b'{"narration":{"model_loaded":true}}'
        ),
        runner=runner,
    )
    assert loaded is True


def test_stopped_interlock_tolerates_only_bounded_docker_stall():
    docker_binary = Path(sys.executable)
    now = [100.0]
    outcomes = ["false\n", subprocess.TimeoutExpired("docker", 5), subprocess.TimeoutExpired("docker", 5)]

    def runner(*args, **kwargs):
        outcome = outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return subprocess.CompletedProcess(args[0], 0, stdout=outcome, stderr="")

    interlock = orchestrator.NanoResidencyInterlock(
        "http://127.0.0.1:18088/api/ai-novel-world-2026/health",
        container_name="ai-novel-2026-moss-tts-sidecar",
        docker_binary=docker_binary,
        stopped_proof_grace_seconds=15,
        clock=lambda: now[0],
        runner=runner,
    )
    assert interlock.require_fresh() is False
    now[0] = 114.0
    assert interlock() is False
    now[0] = 116.0
    try:
        interlock()
    except orchestrator.T2OrchestratorError:
        pass
    else:
        raise AssertionError("stale stopped-container proof must fail closed")


def test_assessment_accepts_low_headroom_only_under_explicit_local_policy():
    baselines = [snapshot()] * 15
    assessment = orchestrator.assess(
        baselines=baselines,
        watchdog_payload={
            "outcome": "completed",
            "safe_for_this_run": True,
            "resource_limits_enforced": False,
        },
        child_payload={"passed": True},
        verification={"component_id": "voice-generator"},
    )
    assert assessment["passed"] is True
    assert assessment["status"] == "PASS_LOCAL_RISK_ACCEPTED"
    assert assessment["minimum_baseline_available_bytes"] == 2 * watchdog.GIB

    strict_result = dict(assessment["watchdog"])
    strict_result["resource_limits_enforced"] = True
    rejected = orchestrator.assess(
        baselines=baselines,
        watchdog_payload=strict_result,
        child_payload={"passed": True},
        verification={},
    )
    assert rejected["passed"] is False


def test_baseline_rejects_nano_or_unknown_pressure():
    baselines = [snapshot()] * 14 + [snapshot(nano=True)]
    assessment = orchestrator.assess(
        baselines=baselines,
        watchdog_payload={},
        child_payload=None,
        verification={},
    )
    assert assessment["baseline_ready"] is False
    assert assessment["passed"] is False
