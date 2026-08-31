"""Serial T2 orchestrator for one verified, one-shot model load."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import secrets
import subprocess
import time
from typing import Callable, Sequence
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from artifact_manifest import load_manifest, verify_snapshot
from macos_memory_watchdog import (
    GIB,
    MIB,
    MacOSMetricsSampler,
    MemoryPressure,
    MetricSnapshot,
    OneShotProcessWatchdog,
    SafetyPolicy,
)


SCHEMA = "vg40-t2-assessment/1"
CONTAINER_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")


class T2OrchestratorError(RuntimeError):
    pass


class NanoResidencyInterlock:
    """Retain only a very short proof that a manually stopped container stayed off."""

    def __init__(
        self,
        health_url: str,
        *,
        container_name: str,
        docker_binary: Path,
        stopped_proof_grace_seconds: float = 15.0,
        clock: Callable[[], float] = time.monotonic,
        opener: Callable[..., object] = urlopen,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        if not 0 < stopped_proof_grace_seconds <= 15:
            raise T2OrchestratorError("stopped-container proof grace exceeds the fixed bound")
        self._health_url = health_url
        self._container_name = container_name
        self._docker_binary = docker_binary
        self._grace = stopped_proof_grace_seconds
        self._clock = clock
        self._opener = opener
        self._runner = runner
        self._last_stopped_proof: float | None = None

    def __call__(self) -> bool:
        try:
            return self.require_fresh()
        except T2OrchestratorError:
            now = self._clock()
            if (
                self._last_stopped_proof is not None
                and now - self._last_stopped_proof <= self._grace
            ):
                return False
            raise

    def require_fresh(self) -> bool:
        loaded = probe_nano_loaded_or_stopped(
            self._health_url,
            container_name=self._container_name,
            docker_binary=self._docker_binary,
            opener=self._opener,
            runner=self._runner,
        )
        if loaded:
            self._last_stopped_proof = None
        else:
            self._last_stopped_proof = self._clock()
        return loaded


def probe_nano_loaded(
    health_url: str, *, opener: Callable[..., object] = urlopen
) -> bool:
    parsed = urlparse(health_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise T2OrchestratorError("Nano health URL must be loopback HTTP")
    request = Request(health_url, headers={"Accept": "application/json"})
    with opener(request, timeout=5) as response:  # type: ignore[misc]
        payload = response.read(64 * 1024 + 1)  # type: ignore[attr-defined]
    if len(payload) > 64 * 1024:
        raise T2OrchestratorError("health response exceeded the fixed bound")
    decoded = json.loads(payload)
    value = decoded.get("narration", {}).get("model_loaded")
    if not isinstance(value, bool):
        raise T2OrchestratorError("health response lacks authoritative model residency")
    return value


def probe_nano_loaded_or_stopped(
    health_url: str,
    *,
    container_name: str,
    docker_binary: Path,
    opener: Callable[..., object] = urlopen,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> bool:
    """Use public health while running, or Docker state while fully stopped.

    A stopped Sidecar container is an authoritative proof that its Nano model
    cannot be resident.  A running container must still provide the normal
    application health contract; a missing or malformed health response fails
    closed through the caller's metric sampler.
    """

    if CONTAINER_NAME.fullmatch(container_name) is None:
        raise T2OrchestratorError("Nano container name is invalid")
    if not docker_binary.is_absolute() or not docker_binary.is_file():
        raise T2OrchestratorError("Docker binary must be an existing absolute file")
    try:
        completed = runner(
            (
                str(docker_binary),
                "inspect",
                "--format",
                "{{.State.Running}}",
                container_name,
            ),
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise T2OrchestratorError("Nano container state is unavailable") from error
    state = completed.stdout.strip()
    if state == "false":
        return False
    if state != "true":
        raise T2OrchestratorError("Nano container state is invalid")
    return probe_nano_loaded(health_url, opener=opener)


def collect_baselines(
    sampler: MacOSMetricsSampler,
    *,
    count: int = 15,
    interval_seconds: float = 2.0,
    sleeper: Callable[[float], None] = time.sleep,
) -> tuple[MetricSnapshot, ...]:
    if count != 15 or interval_seconds != 2.0:
        raise T2OrchestratorError("T2 baseline cadence is frozen at 15 x 2 seconds")
    samples: list[MetricSnapshot] = []
    for index in range(count):
        samples.append(sampler.sample(None))
        if index + 1 < count:
            sleeper(interval_seconds)
    return tuple(samples)


def assess(
    *,
    baselines: Sequence[MetricSnapshot],
    watchdog_payload: dict[str, object],
    child_payload: dict[str, object] | None,
    verification: dict[str, object],
) -> dict[str, object]:
    baseline_ready = (
        len(baselines) == 15
        and all(not item.nano_model_loaded for item in baselines)
        and all(
            item.memory_pressure not in {MemoryPressure.CRITICAL, MemoryPressure.UNKNOWN}
            for item in baselines
        )
    )
    passed = (
        baseline_ready
        and watchdog_payload.get("outcome") == "completed"
        and watchdog_payload.get("safe_for_this_run") is True
        and watchdog_payload.get("resource_limits_enforced") is False
        and isinstance(child_payload, dict)
        and child_payload.get("passed") is True
    )
    return {
        "schema_version": SCHEMA,
        "passed": passed,
        "status": "PASS_LOCAL_RISK_ACCEPTED" if passed else "FAIL",
        "baseline_ready": baseline_ready,
        "baseline_count": len(baselines),
        "minimum_baseline_available_bytes": min(
            (item.available_memory_estimate_bytes for item in baselines), default=None
        ),
        "resource_limits_enforced": False,
        "verification": verification,
        "watchdog": watchdog_payload,
        "child": child_payload,
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }


def _write_json(path: Path, payload: object) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError("evidence path already exists")
    encoded = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2)
        + "\n"
    ).encode("utf-8")
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    descriptor = temporary.open("xb")
    try:
        with descriptor as target:
            target.write(encoded)
            target.flush()
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _manifest_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--component", choices=("voice-generator", "audio-tokenizer"), required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--runtime-python", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--health-url", default="http://127.0.0.1:18088/api/ai-novel-world-2026/health")
    parser.add_argument("--nano-container-name", default="ai-novel-2026-moss-tts-sidecar")
    parser.add_argument("--docker-binary", type=Path, default=Path("/usr/local/bin/docker"))
    parser.add_argument("--mps-memory-fraction", type=float, default=0.55)
    arguments = parser.parse_args(argv)

    if arguments.run_dir.exists() or arguments.run_dir.is_symlink():
        raise T2OrchestratorError("run directory must not exist")
    if not arguments.run_dir.is_absolute():
        raise T2OrchestratorError("run directory must be absolute")
    arguments.run_dir.mkdir(mode=0o700, parents=False)
    manifest = load_manifest(arguments.manifest)
    component = next(
        item
        for item in manifest["components"]  # type: ignore[index]
        if item["id"] == arguments.component
    )
    verification = verify_snapshot(arguments.model_dir, component)
    verification["manifest_sha256"] = _manifest_sha256(arguments.manifest)

    nano_interlock = NanoResidencyInterlock(
        arguments.health_url,
        container_name=arguments.nano_container_name,
        docker_binary=arguments.docker_binary,
    )
    sampler = MacOSMetricsSampler(nano_interlock)
    baselines = collect_baselines(sampler)
    _write_json(
        arguments.run_dir / "baselines.json",
        [sample.to_dict() for sample in baselines],
    )
    if any(item.nano_model_loaded for item in baselines) or any(
        item.memory_pressure in {MemoryPressure.CRITICAL, MemoryPressure.UNKNOWN}
        for item in baselines
    ):
        _write_json(
            arguments.run_dir / "assessment.json",
            assess(
                baselines=baselines,
                watchdog_payload={},
                child_payload=None,
                verification=verification,
            ),
        )
        return 1

    # Do not carry a cached baseline observation into the model start.  The
    # bounded grace applies only after this fresh, immediately pre-spawn proof.
    if nano_interlock.require_fresh():
        _write_json(
            arguments.run_dir / "assessment.json",
            assess(
                baselines=baselines,
                watchdog_payload={},
                child_payload=None,
                verification=verification,
            ),
        )
        return 1

    child_result = arguments.run_dir / "child.json"
    policy = SafetyPolicy(
        hard_timeout_seconds=900,
        pageout_budget_pages=15_360,
        recovery_tolerance_bytes=512 * MIB,
        sample_interval_seconds=2,
        termination_grace_seconds=10,
        minimum_abort_headroom_bytes=int(3.5 * GIB),
        minimum_pass_headroom_bytes=4 * GIB,
        maximum_swap_delta_bytes=512 * MIB,
        sustained_pageout_seconds=60,
        recovery_offsets_seconds=(10, 30, 60),
        enforce_headroom_swap_pageout_limits=False,
        critical_pressure_grace_seconds=20,
    )
    probe_script = Path(__file__).with_name("t2_load_probe.py")
    try:
        result = OneShotProcessWatchdog(sampler, policy).run(
            (
                str(arguments.runtime_python),
                str(probe_script),
                "--component",
                arguments.component,
                "--model-dir",
                str(arguments.model_dir),
                "--revision",
                str(component["revision"]),
                "--result",
                str(child_result),
                "--mps-memory-fraction",
                str(arguments.mps_memory_fraction),
            ),
            cwd=arguments.run_dir,
            environment={
                "HF_HOME": str(arguments.runtime_root / "hf-home"),
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "HF_HUB_DISABLE_TELEMETRY": "1",
                "PYTORCH_ENABLE_MPS_FALLBACK": "0",
            },
        )
    except Exception as error:
        _write_json(
            arguments.run_dir / "assessment.json",
            {
                "schema_version": SCHEMA,
                "passed": False,
                "status": "FAIL_PRESPAWN",
                "error_type": type(error).__name__,
                "baseline_count": len(baselines),
                "resource_limits_enforced": False,
                "verification": verification,
                "observed_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return 1
    watchdog_payload = result.to_dict()
    _write_json(arguments.run_dir / "watchdog.json", watchdog_payload)
    child_payload = (
        json.loads(child_result.read_text(encoding="utf-8"))
        if child_result.is_file() and not child_result.is_symlink()
        else None
    )
    assessment = assess(
        baselines=baselines,
        watchdog_payload=watchdog_payload,
        child_payload=child_payload,
        verification=verification,
    )
    _write_json(arguments.run_dir / "assessment.json", assessment)
    return 0 if assessment["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
