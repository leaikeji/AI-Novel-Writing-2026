from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parent


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


watchdog = load_module(ROOT / "macos_memory_watchdog.py", "macos_memory_watchdog")
orchestrator = load_module(ROOT / "t1_orchestrator.py", "t1_orchestrator")


def snapshot(*, available=8 * watchdog.GIB, pressure=watchdog.MemoryPressure.NORMAL, nano=False):
    return watchdog.MetricSnapshot(
        monotonic_seconds=time.monotonic(),
        observed_at=datetime.now(timezone.utc).isoformat(),
        child_pid=None,
        child_rss_bytes=None,
        child_phys_footprint_bytes=None,
        physical_memory_bytes=16 * watchdog.GIB,
        available_memory_estimate_bytes=available,
        memory_pressure=pressure,
        swap_used_bytes=0,
        pageins=0,
        pageouts=0,
        nano_model_loaded=nano,
    )


def result(*, safe=True, stop_reason=None, outcome=watchdog.ProcessOutcome.COMPLETED):
    event = watchdog.WatchdogEvent("child_started", time.monotonic(), "123")
    return watchdog.WatchdogResult(
        outcome=outcome,
        stop_reason=stop_reason,
        return_code=0 if outcome is watchdog.ProcessOutcome.COMPLETED else -15,
        started_at=datetime.now(timezone.utc).isoformat(),
        finished_at=datetime.now(timezone.utc).isoformat(),
        elapsed_seconds=1.0,
        safe_for_this_run=safe,
        resource_limits_enforced=True,
        maximum_swap_delta_bytes=0,
        minimum_headroom_bytes=4 * watchdog.GIB,
        maximum_child_rss_bytes=1,
        maximum_child_phys_footprint_bytes=1,
        pageout_delta_pages=0,
        maximum_continuous_pageout_seconds=0,
        maximum_continuous_critical_pressure_seconds=0,
        samples=(),
        events=(event,),
        recovery=None,
        stdout_bytes=0,
        stdout_sha256="0" * 64,
        stderr_bytes=0,
        stderr_sha256="0" * 64,
    )


def valid_payload():
    return {
        "schema_version": "vg40-mps-probe/1",
        "passed": True,
        "version_match": True,
        "fallback_disabled": True,
        "mps_built": True,
        "mps_available": True,
        "operations": [
            {"name": name, "passed": True}
            for name in sorted(orchestrator.EXPECTED_OPERATIONS)
        ],
    }


class T1OrchestratorTests(unittest.TestCase):
    def test_requires_exactly_fifteen_safe_baselines(self):
        incomplete = orchestrator.assess_preflight([snapshot()] * 14)
        self.assertEqual(incomplete.reason_code, "VG40_T1_EVIDENCE_INCOMPLETE")
        low = orchestrator.assess_preflight(
            [snapshot()] * 14 + [snapshot(available=int(3.9 * watchdog.GIB))]
        )
        self.assertEqual(low.reason_code, "VG40_T1_PREFLIGHT_HEADROOM_INSUFFICIENT")
        self.assertFalse(low.probe_started)

    def test_nano_and_unknown_pressure_hold_without_probe(self):
        nano = orchestrator.assess_preflight([snapshot()] * 14 + [snapshot(nano=True)])
        unknown = orchestrator.assess_preflight(
            [snapshot()] * 14
            + [snapshot(pressure=watchdog.MemoryPressure.UNKNOWN)]
        )
        self.assertEqual(nano.reason_code, "VG40_T1_NANO_RESIDENCY_CONFLICT")
        self.assertEqual(unknown.reason_code, "VG40_T1_MEASUREMENT_UNAVAILABLE")

    def test_safe_complete_probe_passes_only_with_full_operation_set(self):
        assessment = orchestrator.assess_probe(
            [snapshot()] * 15, result(), valid_payload()
        )
        self.assertEqual(assessment.verdict, orchestrator.T1Verdict.PASS)
        payload = valid_payload()
        payload["operations"] = payload["operations"][:-1]
        rejected = orchestrator.assess_probe([snapshot()] * 15, result(), payload)
        self.assertEqual(rejected.reason_code, "VG40_T1_MPS_UNSUPPORTED")

    def test_memory_abort_and_measurement_loss_are_distinct(self):
        blocked = orchestrator.assess_probe(
            [snapshot()] * 15,
            result(
                safe=False,
                stop_reason=watchdog.StopReason.HEADROOM_BELOW_ABORT_FLOOR,
                outcome=watchdog.ProcessOutcome.SAFETY_TERMINATED,
            ),
            None,
        )
        held = orchestrator.assess_probe(
            [snapshot()] * 15,
            result(
                safe=False,
                stop_reason=watchdog.StopReason.MEASUREMENT_UNAVAILABLE,
                outcome=watchdog.ProcessOutcome.SAFETY_TERMINATED,
            ),
            None,
        )
        self.assertEqual(blocked.reason_code, "VG40_T1_MEMORY_ABORTED")
        self.assertEqual(held.verdict, orchestrator.T1Verdict.HOLD)

    def test_probe_file_is_bounded_regular_json_and_evidence_is_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / "probe.json"
            probe.write_text('{"passed": true}', encoding="utf-8")
            self.assertTrue(orchestrator.load_probe_payload(probe)["passed"])
            evidence = root / "assessment.json"
            orchestrator.atomic_write_json(evidence, {"status": "HOLD"})
            with self.assertRaises(FileExistsError):
                orchestrator.atomic_write_json(evidence, {"status": "PASS"})


if __name__ == "__main__":
    unittest.main()
