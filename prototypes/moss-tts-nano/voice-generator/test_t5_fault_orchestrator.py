from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parent


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


watchdog = load(ROOT / "macos_memory_watchdog.py", "macos_memory_watchdog")
load(ROOT / "artifact_manifest.py", "artifact_manifest")
load(ROOT / "t2_orchestrator.py", "t2_orchestrator")
faults = load(ROOT / "t5_fault_orchestrator.py", "t5_fault_orchestrator")


def snapshot():
    return watchdog.MetricSnapshot(
        monotonic_seconds=time.monotonic(), observed_at=datetime.now(timezone.utc).isoformat(),
        child_pid=None, child_rss_bytes=None, child_phys_footprint_bytes=None,
        physical_memory_bytes=16 * watchdog.GIB, available_memory_estimate_bytes=2 * watchdog.GIB,
        memory_pressure=watchdog.MemoryPressure.NORMAL, swap_used_bytes=9 * watchdog.GIB,
        pageins=1, pageouts=2, nano_model_loaded=False,
    )


def test_cancel_and_crash_require_recovery_and_no_asset():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        forbidden = (root / "unexpected-result.json", root / "tokens", root / "wav")
        common = {
            "baselines": [snapshot()] * 15,
            "forbidden_paths": forbidden,
        }
        cancelled = faults.assess(
            mode="cancel",
            watchdog_payload={"outcome": "cancelled", "stop_reason": "user_cancelled", "recovery": {"recovered": True, "child_absent": True}},
            phase_payload=None,
            **common,
        )
        assert cancelled["passed"] is True
        crashed = faults.assess(
            mode="crash",
            watchdog_payload={"outcome": "child_failed", "return_code": -9, "recovery": {"recovered": True, "child_absent": True}},
            phase_payload={"phase": "generator_loaded_before_injected_sigkill"},
            **common,
        )
        assert crashed["passed"] is True
        forbidden[0].write_text("published", encoding="utf-8")
        assert faults.assess(
            mode="crash",
            watchdog_payload={"outcome": "child_failed", "return_code": -9, "recovery": {"recovered": True, "child_absent": True}},
            phase_payload={"phase": "generator_loaded_before_injected_sigkill"},
            **common,
        )["passed"] is False
