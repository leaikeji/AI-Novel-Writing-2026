"""Execute one real T5 cancellation or crash-recovery injection."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import threading
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


SCHEMA = "vg40-t5-fault-assessment/1"


def assess(
    *,
    mode: str,
    baselines: Sequence[MetricSnapshot],
    watchdog_payload: dict[str, object],
    phase_payload: dict[str, object] | None,
    forbidden_paths: Sequence[Path],
) -> dict[str, object]:
    recovery = watchdog_payload.get("recovery")
    baseline_ready = (
        len(baselines) == 15
        and all(not item.nano_model_loaded for item in baselines)
        and all(item.memory_pressure not in {MemoryPressure.CRITICAL, MemoryPressure.UNKNOWN} for item in baselines)
    )
    no_asset = all(not path.exists() and not path.is_symlink() for path in forbidden_paths)
    no_temporary = not any(forbidden_paths[0].parent.glob(".*.tmp"))
    if mode == "cancel":
        expected_outcome = (
            watchdog_payload.get("outcome") == "cancelled"
            and watchdog_payload.get("stop_reason") == "user_cancelled"
            and phase_payload is None
        )
    else:
        expected_outcome = (
            watchdog_payload.get("outcome") == "child_failed"
            and watchdog_payload.get("return_code") == -9
            and isinstance(phase_payload, dict)
            and phase_payload.get("phase") == "generator_loaded_before_injected_sigkill"
        )
    recovered = isinstance(recovery, dict) and recovery.get("recovered") is True and recovery.get("child_absent") is True
    passed = baseline_ready and expected_outcome and recovered and no_asset and no_temporary
    return {
        "schema_version": SCHEMA,
        "mode": mode,
        "passed": passed,
        "status": "PASS_LOCAL_RISK_ACCEPTED" if passed else "FAIL",
        "baseline_ready": baseline_ready,
        "expected_outcome": expected_outcome,
        "resource_limits_enforced": False,
        "recovered": recovered,
        "no_voice_token_or_audio_asset": no_asset,
        "no_temporary_asset": no_temporary,
        "phase": phase_payload,
        "watchdog": watchdog_payload,
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }


def _write_json(path: Path, payload: object) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError("evidence path already exists")
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2) + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    with temporary.open("xb") as target:
        target.write(encoded)
        target.flush()
    temporary.replace(path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("cancel", "crash"), required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--runtime-python", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--cancel-after-seconds", type=float, default=3.0)
    parser.add_argument("--health-url", default="http://127.0.0.1:18088/api/ai-novel-world-2026/health")
    parser.add_argument("--nano-container-name", default="ai-novel-2026-moss-tts-sidecar")
    parser.add_argument("--docker-binary", type=Path, default=Path("/usr/local/bin/docker"))
    arguments = parser.parse_args(argv)

    if arguments.run_dir.exists() or arguments.run_dir.is_symlink() or not arguments.run_dir.is_absolute():
        raise ValueError("run directory must be a new absolute path")
    arguments.run_dir.mkdir(mode=0o700, parents=False)
    manifest = load_manifest(arguments.manifest)
    component = next(item for item in manifest["components"] if item["id"] == "voice-generator")
    verification = verify_snapshot(arguments.model_dir, component)
    interlock = NanoResidencyInterlock(arguments.health_url, container_name=arguments.nano_container_name, docker_binary=arguments.docker_binary)
    sampler = MacOSMetricsSampler(interlock)
    baselines = collect_baselines(sampler)
    _write_json(arguments.run_dir / "baselines.json", [item.to_dict() for item in baselines])
    if any(item.nano_model_loaded or item.memory_pressure in {MemoryPressure.CRITICAL, MemoryPressure.UNKNOWN} for item in baselines):
        return 1
    if interlock.require_fresh():
        raise RuntimeError("Nano became resident before fault injection")

    phase_marker = arguments.run_dir / "phase.json"
    result_path = arguments.run_dir / "unexpected-result.json"
    token_path = arguments.run_dir / "intermediate.safetensors"
    wav_path = arguments.run_dir / "sample.wav"
    if arguments.mode == "cancel":
        command = (
            str(arguments.runtime_python), str(Path(__file__).with_name("t2_load_probe.py")),
            "--component", "voice-generator", "--model-dir", str(arguments.model_dir),
            "--revision", str(component["revision"]), "--result", str(result_path),
            "--mps-memory-fraction", "0.65", "--stabilize-seconds", "30",
        )
        cancel_event = threading.Event()
        timer = threading.Timer(arguments.cancel_after_seconds, cancel_event.set)
        timer.start()
    else:
        command = (
            str(arguments.runtime_python), str(Path(__file__).with_name("t5_crash_probe.py")),
            "--model-dir", str(arguments.model_dir), "--revision", str(component["revision"]),
            "--phase-marker", str(phase_marker), "--mps-memory-fraction", "0.65",
        )
        cancel_event = None
        timer = None

    policy = SafetyPolicy(
        hard_timeout_seconds=180, pageout_budget_pages=15_360,
        recovery_tolerance_bytes=512 * MIB, sample_interval_seconds=1,
        termination_grace_seconds=10, minimum_abort_headroom_bytes=int(3.5 * GIB),
        minimum_pass_headroom_bytes=4 * GIB, maximum_swap_delta_bytes=512 * MIB,
        sustained_pageout_seconds=60, recovery_offsets_seconds=(10, 30, 60),
        enforce_headroom_swap_pageout_limits=False, critical_pressure_grace_seconds=20,
    )
    try:
        result = OneShotProcessWatchdog(sampler, policy).run(
            command,
            cwd=arguments.run_dir,
            cancel_event=cancel_event,
            environment={
                "HF_HOME": str(arguments.runtime_root / "hf-home"),
                "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                "HF_HUB_DISABLE_TELEMETRY": "1", "PYTORCH_ENABLE_MPS_FALLBACK": "0",
            },
        )
    finally:
        if timer is not None:
            timer.cancel()
    watchdog_payload = result.to_dict()
    _write_json(arguments.run_dir / "watchdog.json", watchdog_payload)
    phase_payload = json.loads(phase_marker.read_text(encoding="utf-8")) if phase_marker.is_file() else None
    assessment = assess(
        mode=arguments.mode,
        baselines=baselines,
        watchdog_payload=watchdog_payload,
        phase_payload=phase_payload,
        forbidden_paths=(result_path, token_path, wav_path),
    )
    assessment["verification"] = verification
    _write_json(arguments.run_dir / "assessment.json", assessment)
    _write_json(arguments.run_dir / "fault.json", {
        "schema_version": "vg40-t5-fault/1", "fault_id": f"t5_{arguments.mode}",
        "phase": "generator_load_before_publish", "method": "watchdog_cancel" if arguments.mode == "cancel" else "child_sigkill_after_load",
        "expected": "cancelled_without_asset" if arguments.mode == "cancel" else "child_failed_without_asset",
        "actual": watchdog_payload.get("outcome"),
    })
    _write_json(arguments.run_dir / "recovery.json", {
        "schema_version": "vg40-t5-recovery/1", "mode": arguments.mode,
        "recovered": assessment["recovered"], "no_voice_token_or_audio_asset": assessment["no_voice_token_or_audio_asset"],
        "no_temporary_asset": assessment["no_temporary_asset"],
    })
    return 0 if assessment["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
