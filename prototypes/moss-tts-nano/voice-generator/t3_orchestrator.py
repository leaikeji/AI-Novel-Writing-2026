"""Serial T3 orchestrator for one neutral VoiceGenerator token run."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import secrets
from typing import Sequence

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
from t2_orchestrator import NanoResidencyInterlock, collect_baselines


SCHEMA = "vg40-t3-assessment/1"


class T3OrchestratorError(RuntimeError):
    pass


def assess(
    *,
    baselines: Sequence[MetricSnapshot],
    watchdog_payload: dict[str, object],
    child_payload: dict[str, object] | None,
    artifact_path: Path,
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
    artifact_sha256 = _sha256(artifact_path) if artifact_path.is_file() else None
    artifact_bytes = artifact_path.stat().st_size if artifact_path.is_file() else None
    artifact_valid = (
        isinstance(child_payload, dict)
        and child_payload.get("token_schema_version") == "vg40-audio-codes/1"
        and child_payload.get("artifact_sha256") == artifact_sha256
        and child_payload.get("artifact_bytes") == artifact_bytes
        and child_payload.get("token_dtype") == "int64"
        and child_payload.get("generation_completed") is True
        and isinstance(child_payload.get("token_shape"), list)
    )
    passed = (
        baseline_ready
        and watchdog_payload.get("outcome") == "completed"
        and watchdog_payload.get("safe_for_this_run") is True
        and watchdog_payload.get("resource_limits_enforced") is False
        and isinstance(child_payload, dict)
        and child_payload.get("passed") is True
        and artifact_valid
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
        "artifact_valid": artifact_valid,
        "artifact_bytes": artifact_bytes,
        "artifact_sha256": artifact_sha256,
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(4 * MIB):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--runtime-python", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--health-url", default="http://127.0.0.1:18088/api/ai-novel-world-2026/health")
    parser.add_argument("--nano-container-name", default="ai-novel-2026-moss-tts-sidecar")
    parser.add_argument("--docker-binary", type=Path, default=Path("/usr/local/bin/docker"))
    parser.add_argument("--seed", type=int, default=104729)
    parser.add_argument("--mps-memory-fraction", type=float, default=0.55)
    arguments = parser.parse_args(argv)

    if arguments.run_dir.exists() or arguments.run_dir.is_symlink():
        raise T3OrchestratorError("run directory must not exist")
    if not arguments.run_dir.is_absolute():
        raise T3OrchestratorError("run directory must be absolute")
    arguments.run_dir.mkdir(mode=0o700, parents=False)
    manifest = load_manifest(arguments.manifest)
    component = next(
        item
        for item in manifest["components"]  # type: ignore[index]
        if item["id"] == "voice-generator"
    )
    verification = verify_snapshot(arguments.model_dir, component)

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
    child_result = arguments.run_dir / "generator.json"
    artifact_path = arguments.run_dir / "intermediate.safetensors"
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
                artifact_path=artifact_path,
                verification=verification,
            ),
        )
        return 1
    if nano_interlock.require_fresh():
        raise T3OrchestratorError("Nano became resident before T3 spawn")

    policy = SafetyPolicy(
        hard_timeout_seconds=300,
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
    probe_script = Path(__file__).with_name("t3_generate_probe.py")
    result = OneShotProcessWatchdog(sampler, policy).run(
        (
            str(arguments.runtime_python),
            str(probe_script),
            "--model-dir",
            str(arguments.model_dir),
            "--revision",
            str(component["revision"]),
            "--result",
            str(child_result),
            "--artifact",
            str(artifact_path),
            "--seed",
            str(arguments.seed),
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
        artifact_path=artifact_path,
        verification=verification,
    )
    _write_json(arguments.run_dir / "assessment.json", assessment)
    return 0 if assessment["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
