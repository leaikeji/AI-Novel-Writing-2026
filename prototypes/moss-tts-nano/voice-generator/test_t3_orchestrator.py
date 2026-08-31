from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
import tempfile
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
load_module(ROOT / "artifact_manifest.py", "artifact_manifest")
load_module(ROOT / "t2_orchestrator.py", "t2_orchestrator")
orchestrator = load_module(ROOT / "t3_orchestrator.py", "vg40_t3_orchestrator")


def snapshot():
    return watchdog.MetricSnapshot(
        monotonic_seconds=time.monotonic(),
        observed_at=datetime.now(timezone.utc).isoformat(),
        child_pid=None,
        child_rss_bytes=None,
        child_phys_footprint_bytes=None,
        physical_memory_bytes=16 * watchdog.GIB,
        available_memory_estimate_bytes=2 * watchdog.GIB,
        memory_pressure=watchdog.MemoryPressure.NORMAL,
        swap_used_bytes=8 * watchdog.GIB,
        pageins=1,
        pageouts=2,
        nano_model_loaded=False,
    )


def test_assessment_requires_exact_token_artifact_identity():
    with tempfile.TemporaryDirectory() as temporary:
        artifact = Path(temporary) / "intermediate.safetensors"
        artifact.write_bytes(b"fixed-token-artifact")
        digest = orchestrator._sha256(artifact)
        child = {
            "passed": True,
            "token_schema_version": "vg40-audio-codes/1",
            "artifact_sha256": digest,
            "artifact_bytes": artifact.stat().st_size,
            "token_dtype": "int64",
            "token_shape": [50, 16],
            "generation_completed": True,
        }
        result = orchestrator.assess(
            baselines=[snapshot()] * 15,
            watchdog_payload={
                "outcome": "completed",
                "safe_for_this_run": True,
                "resource_limits_enforced": False,
            },
            child_payload=child,
            artifact_path=artifact,
            verification={},
        )
        assert result["passed"] is True
        artifact.write_bytes(b"tampered")
        tampered = orchestrator.assess(
            baselines=[snapshot()] * 15,
            watchdog_payload=result["watchdog"],
            child_payload=child,
            artifact_path=artifact,
            verification={},
        )
        assert tampered["passed"] is False
        assert tampered["artifact_valid"] is False
