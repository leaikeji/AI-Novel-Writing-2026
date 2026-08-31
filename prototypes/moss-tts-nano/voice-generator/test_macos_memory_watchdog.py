from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


watchdog = load_module(ROOT / "macos_memory_watchdog.py", "macos_memory_watchdog")
staged = load_module(ROOT / "staged_runtime.py", "staged_runtime")


class FakeSampler:
    def __init__(self, snapshots, *, fail_at=None):
        self.snapshots = list(snapshots)
        self.index = 0
        self.fail_at = fail_at

    def sample(self, child_pid):
        if self.fail_at is not None and self.index == self.fail_at:
            self.index += 1
            raise watchdog.MeasurementUnavailable(
                "deliberate detail must be redacted",
                category="deliberate_probe",
            )
        template = self.snapshots[min(self.index, len(self.snapshots) - 1)]
        self.index += 1
        return watchdog.MetricSnapshot(
            monotonic_seconds=time.monotonic(),
            observed_at=datetime.now(timezone.utc).isoformat(),
            child_pid=child_pid,
            child_rss_bytes=template.get("rss") if child_pid is not None else None,
            child_phys_footprint_bytes=(
                template.get("footprint") if child_pid is not None else None
            ),
            physical_memory_bytes=16 * watchdog.GIB,
            available_memory_estimate_bytes=template.get(
                "available", 8 * watchdog.GIB
            ),
            memory_pressure=template.get(
                "pressure", watchdog.MemoryPressure.NORMAL
            ),
            swap_used_bytes=template.get("swap", 0),
            pageins=template.get("pageins", 0),
            pageouts=template.get("pageouts", 0),
            nano_model_loaded=template.get("nano", False),
        )


def policy(**overrides):
    values = {
        "hard_timeout_seconds": 1.0,
        "pageout_budget_pages": 2,
        "recovery_tolerance_bytes": 256 * watchdog.MIB,
        "sample_interval_seconds": 0.01,
        "termination_grace_seconds": 0.1,
        "sustained_pageout_seconds": 0.02,
        "recovery_offsets_seconds": (0.0, 0.0, 0.0),
        "critical_pressure_grace_seconds": 0.015,
    }
    values.update(overrides)
    return watchdog.SafetyPolicy(**values)


def command_sleep(seconds=0.2, exit_code=0):
    return (
        sys.executable,
        "-c",
        f"import time; time.sleep({seconds}); raise SystemExit({exit_code})",
    )


class WatchdogTests(unittest.TestCase):
    def run_child(self, sampler, *, chosen_policy=None, command=None, **kwargs):
        with tempfile.TemporaryDirectory() as temporary:
            return watchdog.OneShotProcessWatchdog(
                sampler, chosen_policy or policy()
            ).run(
                command or command_sleep(),
                cwd=Path(temporary),
                **kwargs,
            )

    def test_success_records_metrics_and_recovery(self):
        samples = [
            {"available": 8 * watchdog.GIB, "swap": 100, "pageouts": 10},
            {
                "available": 7 * watchdog.GIB,
                "swap": 200,
                "pageouts": 10,
                "rss": 123,
                "footprint": 456,
            },
            {"available": 8 * watchdog.GIB, "swap": 200, "pageouts": 10},
        ]
        result = self.run_child(
            FakeSampler(samples), command=command_sleep(0.03)
        )
        self.assertEqual(result.outcome, watchdog.ProcessOutcome.COMPLETED)
        self.assertTrue(result.safe_for_this_run)
        self.assertTrue(result.recovery and result.recovery.recovered)
        self.assertEqual(result.maximum_child_rss_bytes, 123)
        self.assertEqual(result.maximum_child_phys_footprint_bytes, 456)

    def test_completed_child_is_not_safe_when_memory_does_not_recover(self):
        result = self.run_child(
            FakeSampler(
                [
                    {"available": 8 * watchdog.GIB},
                    {"available": 7 * watchdog.GIB},
                    {"available": 6 * watchdog.GIB},
                ]
            ),
            command=command_sleep(0.02),
        )
        self.assertEqual(result.outcome, watchdog.ProcessOutcome.COMPLETED)
        self.assertFalse(result.safe_for_this_run)
        self.assertEqual(
            result.recovery.reason if result.recovery else None,
            "host_memory_did_not_return_to_baseline",
        )

    def test_critical_pressure_terminates_process_group(self):
        result = self.run_child(
            FakeSampler(
                [
                    {"available": 8 * watchdog.GIB},
                    {
                        "available": 8 * watchdog.GIB,
                        "pressure": watchdog.MemoryPressure.CRITICAL,
                    },
                    {
                        "available": 8 * watchdog.GIB,
                        "pressure": watchdog.MemoryPressure.CRITICAL,
                    },
                    {
                        "available": 8 * watchdog.GIB,
                        "pressure": watchdog.MemoryPressure.CRITICAL,
                    },
                    {"available": 8 * watchdog.GIB},
                ]
            )
        )
        self.assertEqual(result.outcome, watchdog.ProcessOutcome.SAFETY_TERMINATED)
        self.assertEqual(
            result.stop_reason, watchdog.StopReason.CRITICAL_MEMORY_PRESSURE
        )
        self.assertTrue(any(event.kind == "termination_requested" for event in result.events))

    def test_headroom_swap_and_nano_interlocks_fail_closed(self):
        cases = (
            (
                {"available": 3 * watchdog.GIB},
                watchdog.StopReason.HEADROOM_BELOW_ABORT_FLOOR,
            ),
            (
                {"available": 8 * watchdog.GIB, "swap": 513 * watchdog.MIB},
                watchdog.StopReason.SWAP_BUDGET_EXCEEDED,
            ),
            (
                {"available": 8 * watchdog.GIB, "nano": True},
                watchdog.StopReason.NANO_RELOADED,
            ),
        )
        for unsafe, reason in cases:
            with self.subTest(reason=reason):
                result = self.run_child(
                    FakeSampler(
                        [
                            {"available": 8 * watchdog.GIB},
                            unsafe,
                            {"available": 8 * watchdog.GIB},
                        ]
                    )
                )
                self.assertEqual(result.stop_reason, reason)
                self.assertFalse(result.safe_for_this_run)

    def test_user_accepted_local_policy_observes_but_does_not_gate_resources(self):
        relaxed = policy(enforce_headroom_swap_pageout_limits=False)
        result = self.run_child(
            FakeSampler(
                [
                    {"available": 3 * watchdog.GIB, "swap": 0, "pageouts": 0},
                    {
                        "available": watchdog.GIB,
                        "swap": 2 * watchdog.GIB,
                        "pageouts": 100_000,
                        "rss": 123,
                        "footprint": 456,
                    },
                    {"available": watchdog.GIB, "swap": 2 * watchdog.GIB, "pageouts": 100_000},
                ]
            ),
            chosen_policy=relaxed,
            command=command_sleep(0.03),
        )
        self.assertEqual(result.outcome, watchdog.ProcessOutcome.COMPLETED)
        self.assertTrue(result.safe_for_this_run)
        self.assertFalse(result.resource_limits_enforced)
        self.assertEqual(result.minimum_headroom_bytes, watchdog.GIB)
        self.assertEqual(result.maximum_swap_delta_bytes, 2 * watchdog.GIB)
        self.assertTrue(result.recovery and result.recovery.recovered)

        nano_result = self.run_child(
            FakeSampler(
                [
                    {"available": 3 * watchdog.GIB},
                    {"available": watchdog.GIB, "nano": True},
                ]
            ),
            chosen_policy=relaxed,
        )
        self.assertEqual(nano_result.stop_reason, watchdog.StopReason.NANO_RELOADED)

    def test_sustained_pageouts_over_explicit_budget_terminate(self):
        result = self.run_child(
            FakeSampler(
                [
                    {"pageouts": 0},
                    {"pageouts": 1},
                    {"pageouts": 2},
                    {"pageouts": 3},
                    {"pageouts": 4},
                    {"pageouts": 4},
                ]
            ),
            chosen_policy=policy(sustained_pageout_seconds=0.015),
        )
        self.assertEqual(result.stop_reason, watchdog.StopReason.PAGEOUT_BUDGET_EXCEEDED)

    def test_timeout_cancel_and_heartbeat_stall_have_distinct_outcomes(self):
        normal = [{"available": 8 * watchdog.GIB}]
        timed_out = self.run_child(
            FakeSampler(normal),
            chosen_policy=policy(hard_timeout_seconds=0.02),
        )
        self.assertEqual(timed_out.outcome, watchdog.ProcessOutcome.TIMED_OUT)

        cancel = threading.Event()
        timer = threading.Timer(0.02, cancel.set)
        timer.start()
        try:
            cancelled = self.run_child(FakeSampler(normal), cancel_event=cancel)
        finally:
            timer.cancel()
        self.assertEqual(cancelled.outcome, watchdog.ProcessOutcome.CANCELLED)

        with tempfile.TemporaryDirectory() as temporary:
            stalled = watchdog.OneShotProcessWatchdog(
                FakeSampler(normal),
                policy(heartbeat_stall_seconds=0.02),
            ).run(
                command_sleep(),
                cwd=Path(temporary),
                heartbeat_path=Path("heartbeat"),
            )
        self.assertEqual(stalled.stop_reason, watchdog.StopReason.HEARTBEAT_STALLED)

    def test_measurement_failure_is_redacted_and_fails_closed(self):
        result = self.run_child(
            FakeSampler([{"available": 8 * watchdog.GIB}], fail_at=1)
        )
        self.assertEqual(result.stop_reason, watchdog.StopReason.MEASUREMENT_UNAVAILABLE)
        event = next(event for event in result.events if event.kind == "measurement_error")
        self.assertEqual(
            event.detail,
            "MeasurementUnavailable:deliberate_probe",
        )

    def test_recovery_rejects_nano_reload_even_under_local_risk_policy(self):
        chosen_policy = policy(enforce_headroom_swap_pageout_limits=False)
        runner = watchdog.OneShotProcessWatchdog(
            FakeSampler([{"available": watchdog.GIB, "nano": True}]),
            chosen_policy,
        )
        baseline = FakeSampler([{"available": 2 * watchdog.GIB}]).sample(None)
        recovery = runner._observe_recovery(
            999_999,
            baseline,
            time.monotonic(),
            [],
        )
        self.assertFalse(recovery.recovered)
        self.assertEqual(
            recovery.reason,
            "nano_reloaded_during_recovery",
        )

    def test_environment_does_not_inherit_credentials(self):
        environment = watchdog.sanitized_child_environment({"SAFE_VALUE": "yes"})
        self.assertEqual(environment["SAFE_VALUE"], "yes")
        self.assertNotIn("HOME", environment)
        self.assertFalse(any("KEY" in key or "TOKEN" in key for key in environment))
        with self.assertRaises(ValueError):
            watchdog.sanitized_child_environment({"SERVICE_API_KEY": "not-allowed"})

    def test_preflight_below_pass_floor_does_not_spawn_child(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = watchdog.OneShotProcessWatchdog(
                FakeSampler([{"available": int(3.9 * watchdog.GIB)}]), policy()
            ).run(
                (
                    sys.executable,
                    "-c",
                    "from pathlib import Path; Path('should-not-exist').touch()",
                ),
                cwd=root,
            )
            self.assertFalse((root / "should-not-exist").exists())
        self.assertEqual(
            result.stop_reason,
            watchdog.StopReason.PREFLIGHT_HEADROOM_INSUFFICIENT,
        )
        self.assertFalse(any(event.kind == "child_started" for event in result.events))

    def test_already_cancelled_request_does_not_spawn_child(self):
        cancel = threading.Event()
        cancel.set()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = watchdog.OneShotProcessWatchdog(
                FakeSampler([{"available": 8 * watchdog.GIB}]), policy()
            ).run(
                (
                    sys.executable,
                    "-c",
                    "from pathlib import Path; Path('should-not-exist').touch()",
                ),
                cwd=root,
                cancel_event=cancel,
            )
            self.assertFalse((root / "should-not-exist").exists())
        self.assertEqual(result.outcome, watchdog.ProcessOutcome.CANCELLED)

    def test_child_output_is_hashed_without_copying_content(self):
        result = self.run_child(
            FakeSampler([{"available": 8 * watchdog.GIB}]),
            command=(sys.executable, "-c", "print('private prompt')"),
            capture_output_digest=True,
        )
        payload = result.to_dict()
        self.assertGreater(payload["stdout_bytes"], 0)
        self.assertNotIn("private prompt", repr(payload))
        self.assertNotIn("stdout_tail", payload)

    def test_captured_output_is_bounded(self):
        result = self.run_child(
            FakeSampler([{"available": 8 * watchdog.GIB}]),
            chosen_policy=policy(maximum_captured_output_bytes=128),
            command=(sys.executable, "-c", "print('x' * 10000)"),
            capture_output_digest=True,
        )
        self.assertEqual(result.stop_reason, watchdog.StopReason.OUTPUT_BUDGET_EXCEEDED)

    def test_policy_rejects_unfrozen_or_inverted_thresholds(self):
        with self.assertRaises(ValueError):
            policy(pageout_budget_pages=-1)
        with self.assertRaises(ValueError):
            policy(
                minimum_abort_headroom_bytes=4 * watchdog.GIB,
                minimum_pass_headroom_bytes=4 * watchdog.GIB,
            )

    def test_vm_stat_and_swap_parsers_keep_units_and_counters(self):
        vm_output = """Mach Virtual Memory Statistics: (page size of 16384 bytes)\nPages free: 10.\nPages inactive: 20.\nPages speculative: 3.\nPages purgeable: 999.\nPageins: 41.\nPageouts: 42.\n"""
        with patch.object(watchdog.MacOSMetricsSampler, "_run", return_value=vm_output):
            available, pageins, pageouts = watchdog.MacOSMetricsSampler._read_vm_stat()
        self.assertEqual(available, 33 * 16384)
        self.assertEqual((pageins, pageouts), (41, 42))
        with patch.object(
            watchdog.MacOSMetricsSampler,
            "_run",
            return_value="total = 8.00G used = 1.50G free = 6.50G",
        ):
            self.assertEqual(
                watchdog.MacOSMetricsSampler._read_swap_used_bytes(),
                int(1.5 * watchdog.GIB),
            )

    def test_non_macos_sampler_is_explicitly_unavailable(self):
        with patch.object(watchdog.platform, "system", return_value="Linux"):
            with self.assertRaises(watchdog.MeasurementUnavailable):
                watchdog.MacOSMetricsSampler(lambda: False)


class StagedRuntimeTests(unittest.TestCase):
    def test_codec_starts_only_after_stage_a_exit_recovery_and_artifact_hash(self):
        samplers = {
            "voice_generator": FakeSampler([{"available": 8 * watchdog.GIB}]),
            "audio_tokenizer": FakeSampler([{"available": 8 * watchdog.GIB}]),
        }
        runtime = staged.StagedRuntime(
            lambda name: watchdog.OneShotProcessWatchdog(samplers[name], policy())
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = runtime.run(
                stage_a_command=(
                    sys.executable,
                    "-c",
                    "from pathlib import Path; Path('tokens.bin').write_bytes(b'tokens')",
                ),
                stage_b_command=(
                    sys.executable,
                    "-c",
                    "from pathlib import Path; assert Path('tokens.bin').read_bytes() == b'tokens'",
                ),
                working_directory=root,
                intermediate_path=Path("tokens.bin"),
                maximum_intermediate_bytes=1024,
            )
        self.assertEqual(result.outcome, staged.StagedOutcome.COMPLETED)
        self.assertEqual(result.artifact.byte_size if result.artifact else None, 6)
        self.assertFalse(result.stage_pid_overlap)

    def test_invalid_artifact_prevents_codec_launch(self):
        calls = []

        def factory(name):
            calls.append(name)
            return watchdog.OneShotProcessWatchdog(
                FakeSampler([{"available": 8 * watchdog.GIB}]), policy()
            )

        with tempfile.TemporaryDirectory() as temporary:
            result = staged.StagedRuntime(factory).run(
                stage_a_command=(sys.executable, "-c", "pass"),
                stage_b_command=(sys.executable, "-c", "raise SystemExit(99)"),
                working_directory=Path(temporary),
                intermediate_path=Path("missing.bin"),
                maximum_intermediate_bytes=1024,
            )
        self.assertEqual(result.outcome, staged.StagedOutcome.ARTIFACT_INVALID)
        self.assertEqual(calls, ["voice_generator"])
        self.assertIsNone(result.stage_b)

    def test_failed_stage_a_never_starts_codec(self):
        calls = []

        def factory(name):
            calls.append(name)
            return watchdog.OneShotProcessWatchdog(
                FakeSampler([{"available": 8 * watchdog.GIB}]), policy()
            )

        with tempfile.TemporaryDirectory() as temporary:
            result = staged.StagedRuntime(factory).run(
                stage_a_command=command_sleep(0.01, exit_code=7),
                stage_b_command=(sys.executable, "-c", "pass"),
                working_directory=Path(temporary),
                intermediate_path=Path("tokens.bin"),
                maximum_intermediate_bytes=1024,
            )
        self.assertEqual(result.outcome, staged.StagedOutcome.STAGE_A_FAILED)
        self.assertEqual(calls, ["voice_generator"])


if __name__ == "__main__":
    unittest.main()
