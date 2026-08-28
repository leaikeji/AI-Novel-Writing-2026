from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "tts" / "benchmark_nano_topologies.py"
SCRIPTS_TTS = SCRIPT_PATH.parent
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "narration" / "benchmark_manifest.json"
TEXTS_PATH = REPO_ROOT / "tests" / "fixtures" / "narration" / "authorized-texts.json"
MODEL_LOCK_PATH = REPO_ROOT / "prototypes" / "moss-tts-nano" / "model-sources.lock.json"


def load_module():
    spec = importlib.util.spec_from_file_location("benchmark_nano_topologies", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


benchmark = load_module()


class FrozenInputTests(unittest.TestCase):
    def test_repository_fixture_and_lock_are_accepted(self) -> None:
        frozen = benchmark.validate_frozen_inputs(
            repo_root=REPO_ROOT,
            fixture_manifest_path=FIXTURE_PATH,
            model_lock_path=MODEL_LOCK_PATH,
        )
        self.assertEqual(len(frozen.manifest["cases"]), 27)
        self.assertEqual(len(frozen.texts), 26)

    def make_isolated_inputs(self, root: Path) -> tuple[Path, Path]:
        manifest = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        texts = json.loads(TEXTS_PATH.read_text(encoding="utf-8"))
        model_lock = json.loads(MODEL_LOCK_PATH.read_text(encoding="utf-8"))
        manifest["authorized_texts"]["path"] = "authorized-texts.json"
        manifest_path = root / "benchmark_manifest.json"
        texts_path = root / "authorized-texts.json"
        lock_path = root / "model-sources.lock.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        texts_path.write_text(json.dumps(texts, ensure_ascii=False), encoding="utf-8")
        lock_path.write_text(json.dumps(model_lock, ensure_ascii=False), encoding="utf-8")
        return manifest_path, lock_path

    def test_tampered_authorized_text_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path, lock_path = self.make_isolated_inputs(root)
            texts_path = root / "authorized-texts.json"
            texts = json.loads(texts_path.read_text(encoding="utf-8"))
            texts["texts"][0]["text"] += "篡改"
            texts_path.write_text(json.dumps(texts, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(benchmark.BenchmarkError, "hash mismatch"):
                benchmark.validate_frozen_inputs(
                    repo_root=root,
                    fixture_manifest_path=manifest_path,
                    model_lock_path=lock_path,
                )

    def test_missing_required_coverage_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path, lock_path = self.make_isolated_inputs(root)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["cases"] = [
                case for case in manifest["cases"] if case["id"] != "long-sentence"
            ]
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(benchmark.BenchmarkError, "coverage is incomplete"):
                benchmark.validate_frozen_inputs(
                    repo_root=root,
                    fixture_manifest_path=manifest_path,
                    model_lock_path=lock_path,
                )

    def test_placeholder_reference_cannot_gain_an_asset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path, lock_path = self.make_isolated_inputs(root)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["reference_profiles"][0]["asset_path"] = "not-authorized.wav"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(benchmark.BenchmarkError, "contains an asset"):
                benchmark.validate_frozen_inputs(
                    repo_root=root,
                    fixture_manifest_path=manifest_path,
                    model_lock_path=lock_path,
                )


class BoundaryTests(unittest.TestCase):
    def test_runtime_cannot_be_nested_in_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(benchmark.BenchmarkError, "must not be inside"):
                benchmark.ensure_output_boundary(root, root / "audio")

    def test_concat_rejects_different_wav_formats(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.wav"
            second = root / "second.wav"
            for path, rate in ((first, 8000), (second, 16000)):
                import wave

                with wave.open(str(path), "wb") as wav_file:
                    wav_file.setnchannels(1)
                    wav_file.setsampwidth(2)
                    wav_file.setframerate(rate)
                    wav_file.writeframes(b"\0\0" * 8)
            with self.assertRaisesRegex(benchmark.BenchmarkError, "formats differ"):
                benchmark.concatenate_wavs([first, second], root / "combined.wav")


class ManagedWorkerProtocolTests(unittest.TestCase):
    def make_adapter(self, root: Path):
        return benchmark.ManagedSubprocessOnnxAdapter(
            source_root=root / "unused-source",
            model_root=root / "unused-model",
            output_root=root / "runtime",
            cpu_threads=2,
            max_new_frames=123,
            sample_mode="fixed",
            seed=42,
            voice="Junhao",
            fake_worker=True,
        )

    def test_per_request_parameters_events_identity_and_real_rss(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = self.make_adapter(root)
            try:
                first = adapter.synthesize(
                    "同一文本",
                    root / "runtime" / "first.wav",
                    voice="Junhao",
                    seed=42,
                    max_new_frames=100,
                    sample_mode="fixed",
                )
                second = adapter.synthesize(
                    "同一文本",
                    root / "runtime" / "second.wav",
                    voice="Nanqiang",
                    seed=7,
                    max_new_frames=80,
                    sample_mode="greedy",
                )
                self.assertEqual(
                    [event["event"] for event in first.events],
                    ["started", "inference_entered", "ready", "published"],
                )
                self.assertEqual(first.worker_pid, second.worker_pid)
                self.assertEqual(first.worker_generation, second.worker_generation)
                self.assertGreater(first.peak_rss_bytes or 0, 0)
                self.assertGreater(first.process_start_to_ready_ms or 0, 0)
                self.assertIsNone(first.internal_first_audio_ms)
                self.assertNotEqual(
                    benchmark.sha256_file(first.audio_path),
                    benchmark.sha256_file(second.audio_path),
                )
                self.assertEqual(second.events[0]["voice"], "Nanqiang")
                self.assertEqual(second.events[0]["seed"], 7)
                self.assertEqual(second.events[0]["max_new_frames"], 80)
                self.assertEqual(second.events[0]["sample_mode"], "greedy")
            finally:
                adapter.close()

    def test_cancel_is_acknowledged_by_the_live_worker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            adapter = self.make_adapter(Path(directory))
            try:
                self.assertTrue(adapter.acknowledge_between_segment_cancel())
                telemetry = adapter.telemetry()
                self.assertIn("cancelled", [event.get("event") for event in telemetry["events"]])
            finally:
                adapter.close()

    def test_sigkill_recovery_changes_pid_preserves_ready_hash_and_never_publishes_partial(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = self.make_adapter(root)
            first_path = root / "runtime" / "ready.wav"
            interrupted_path = root / "runtime" / "interrupted.wav"
            try:
                first = adapter.synthesize("第一段", first_path)
                ready_hash = benchmark.sha256_file(first_path)
                old_pid = first.worker_pid
                crash = adapter.kill_during_synthesis("不得发布的第二段", interrupted_path)
                self.assertEqual(crash["old_pid"], old_pid)
                self.assertFalse(crash["final_output_published"])
                self.assertFalse(crash["published_event_observed"])
                self.assertFalse(interrupted_path.exists())
                self.assertTrue(adapter.restart())
                telemetry = adapter.telemetry()
                self.assertNotEqual(old_pid, telemetry["current_pid"])
                self.assertEqual(telemetry["worker_generation"], 2)
                self.assertEqual(benchmark.sha256_file(first_path), ready_hash)
                resumed = adapter.synthesize("第二段", root / "runtime" / "resumed.wav")
                self.assertEqual(resumed.worker_generation, 2)
                first_text_hash = benchmark.sha256_bytes("第一段".encode("utf-8"))
                self.assertEqual(
                    adapter.telemetry()["synthesis_counts_by_text_sha256"][first_text_hash],
                    1,
                )
            finally:
                pid = adapter.telemetry()["current_pid"]
                adapter.close()
                self.assertIsNone(adapter._stdout_thread)
                self.assertIsNone(adapter._stdout_queue)
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)

    def test_reader_queue_has_bounded_timeout_without_killing_live_worker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            adapter = self.make_adapter(Path(directory))
            try:
                with self.assertRaisesRegex(benchmark.AdapterUnavailable, "timed out"):
                    adapter._read_response(timeout_seconds=0.05)
                result = adapter.synthesize(
                    "超时后仍可处理下一请求",
                    Path(directory) / "runtime" / "after-timeout.wav",
                )
                self.assertTrue(result.audio_path.is_file())
            finally:
                adapter.close()

    def test_reader_queue_reports_eof_after_worker_exit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            adapter = self.make_adapter(Path(directory))
            try:
                assert adapter._process is not None
                adapter._process.kill()
                adapter._process.wait(timeout=5)
                with self.assertRaisesRegex(
                    benchmark.AdapterUnavailable,
                    "closed stdout|exited unexpectedly",
                ):
                    adapter._read_response(timeout_seconds=1)
            finally:
                adapter.close()

    def test_active_request_timeout_poisons_until_explicit_restart_and_drops_late_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = self.make_adapter(root)
            try:
                request_id = "timeout-request"
                with self.assertRaisesRegex(benchmark.AdapterUnavailable, "timed out"):
                    adapter._request(
                        {
                            "operation": "synthesize",
                            "request_id": request_id,
                            "text": "会产生迟到事件",
                            "output_path": str(root / "runtime" / "late.wav"),
                            "voice": "Junhao",
                            "seed": 42,
                            "max_new_frames": 100,
                            "sample_mode": "fixed",
                        },
                        timeout_seconds=0.01,
                    )
                time.sleep(0.25)
                self.assertTrue(adapter.telemetry()["poisoned"])
                with self.assertRaisesRegex(benchmark.AdapterUnavailable, "poisoned"):
                    adapter.synthesize("不得消费迟到事件", root / "runtime" / "rejected.wav")
                self.assertTrue(adapter.restart())
                recovered = adapter.synthesize(
                    "重启后新请求",
                    root / "runtime" / "after-restart.wav",
                )
                self.assertEqual(recovered.worker_generation, 2)
            finally:
                adapter.close()

    def test_invalid_json_missing_request_id_and_bad_identity_each_poison(self) -> None:
        operations = (
            ("test_invalid_json", "invalid JSON"),
            ("test_missing_request_id", "request_id mismatch"),
            ("test_bad_identity", "PID mismatch"),
        )
        for operation, error_pattern in operations:
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as directory:
                adapter = self.make_adapter(Path(directory))
                try:
                    with self.assertRaisesRegex(benchmark.AdapterUnavailable, error_pattern):
                        adapter._request(
                            {"operation": operation, "request_id": operation},
                            timeout_seconds=1,
                        )
                    self.assertTrue(adapter.telemetry()["poisoned"])
                    self.assertTrue(adapter.restart())
                    self.assertFalse(adapter.telemetry()["poisoned"])
                finally:
                    adapter.close()

    def test_protocol_event_order_error_poisons_worker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = self.make_adapter(root)
            try:
                with self.assertRaisesRegex(benchmark.BenchmarkError, "event order"):
                    adapter.synthesize(
                        "__TEST_BAD_ORDER__",
                        root / "runtime" / "bad-order.wav",
                    )
                self.assertTrue(adapter.telemetry()["poisoned"])
                with self.assertRaisesRegex(benchmark.AdapterUnavailable, "poisoned"):
                    adapter.synthesize("rejected", root / "runtime" / "rejected.wav")
            finally:
                adapter.close()

    def test_concurrent_synthesis_is_fail_closed_single_flight(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = self.make_adapter(root)
            errors: list[BaseException] = []

            def first_request() -> None:
                try:
                    adapter.synthesize("first", root / "runtime" / "first.wav")
                except BaseException as error:  # pragma: no cover - asserted below
                    errors.append(error)

            thread = threading.Thread(target=first_request)
            thread.start()
            deadline = time.monotonic() + 1
            while not adapter._request_lock.locked() and time.monotonic() < deadline:
                time.sleep(0.001)
            try:
                self.assertTrue(adapter._request_lock.locked())
                with self.assertRaisesRegex(benchmark.BenchmarkError, "single-flight"):
                    adapter.synthesize("second", root / "runtime" / "second.wav")
                thread.join(timeout=2)
                self.assertFalse(thread.is_alive())
                self.assertEqual(errors, [])
                self.assertFalse(adapter.telemetry()["poisoned"])
            finally:
                adapter.close()

    def test_same_worker_reuse_probe_records_determinism_without_assuming_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = self.make_adapter(root)
            try:
                probe = benchmark.run_managed_reuse_probe(
                    adapter,
                    text="重复确定性探测",
                    probe_root=root / "runtime" / "probe",
                    repetitions=3,
                )
                assert probe is not None
                self.assertTrue(probe["same_worker"])
                self.assertTrue(probe["same_generation"])
                self.assertTrue(probe["bit_exact_within_worker"])
                self.assertEqual(probe["repetitions"], 3)
            finally:
                adapter.close()

    def test_crash_fixture_reuses_ready_asset_and_records_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frozen = benchmark.validate_frozen_inputs(
                repo_root=REPO_ROOT,
                fixture_manifest_path=FIXTURE_PATH,
                model_lock_path=MODEL_LOCK_PATH,
            )
            case = next(
                row for row in frozen.manifest["cases"] if row["id"] == "crash-and-resume"
            )
            adapter = self.make_adapter(root)
            sys.path.insert(0, str(SCRIPTS_TTS))
            try:
                result = benchmark.execute_case(
                    case,
                    adapter=adapter,
                    texts=frozen.texts,
                    case_root=root / "runtime" / "case",
                    real_audio=False,
                )
                self.assertEqual(result["status"], "passed")
                self.assertTrue(result["control"]["crash_recovered"])
                self.assertEqual(result["control"]["ready_segments_reused"], 1)
                details = result["control"]["recovery_details"]
                self.assertTrue(details["ready_asset_rehashed"])
                self.assertTrue(details["ready_asset_not_resynthesized"])
                self.assertFalse(details["kill_probe"]["final_output_published"])
                self.assertTrue(details["worker_after_restart"]["pid_changed"])
                self.assertEqual(result["control"]["worker_generations"], [1, 2, 2])
            finally:
                adapter.close()

    def test_short_endurance_summary_stays_on_one_worker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = self.make_adapter(root)
            try:
                result = benchmark.run_managed_endurance(
                    adapter,
                    text="耐久测试授权文本",
                    probe_root=root / "runtime" / "endurance",
                    duration_seconds=1,
                )
                assert result is not None
                self.assertGreaterEqual(result["actual_duration_seconds"], 1)
                self.assertGreater(result["completed_requests"], 0)
                self.assertTrue(result["same_worker"])
                self.assertTrue(result["same_generation"])
                self.assertGreater(result["peak_rss_bytes_max"], 0)
            finally:
                adapter.close()


class CliContractTests(unittest.TestCase):
    def run_cli(self, mode: str, root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--fixture-manifest",
                str(FIXTURE_PATH),
                "--output-dir",
                str(root / "evidence"),
                "--runtime-dir",
                str(root / "runtime"),
                "--mode",
                mode,
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_contract_mode_records_four_blocked_runs_without_audio(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            completed = self.run_cli("contract", root)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            summary = json.loads((root / "evidence" / "metrics.json").read_text())
            self.assertEqual(summary["run_count"], 4)
            self.assertEqual(summary["run_statuses"], {"blocked": 4})
            self.assertFalse(list((root / "evidence").rglob("*.wav")))

    def test_fake_mode_exercises_schema_and_recovery_without_evidence_audio(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            completed = self.run_cli("fake", root)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            invocation = json.loads(completed.stdout)
            self.assertEqual(invocation["expected_status_match_count"], 3)
            summary = json.loads((root / "evidence" / "metrics.json").read_text())
            self.assertEqual(summary["schema_version"], "moss-tts-benchmark-summary/1.0")
            self.assertEqual(summary["run_count"], 4)
            self.assertEqual(summary["recovery"]["cancel_acknowledged_cases"], 4)
            self.assertEqual(summary["recovery"]["crash_recovered_cases"], 3)
            self.assertGreater(summary["performance"]["rtf"]["count"], 0)
            self.assertFalse(list((root / "evidence").rglob("*.wav")))
            raw_results = list((root / "runtime").rglob("T0-B-*.json"))
            self.assertEqual(len(raw_results), 4)
            renderer = REPO_ROOT / "scripts" / "tts" / "render_benchmark_report.py"
            validation = subprocess.run(
                [sys.executable, str(renderer), *(str(path) for path in raw_results), "--stdout-format", "json"],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(validation.returncode, 0, validation.stderr)

    def test_exact_case_filter_runs_only_the_requested_case(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--fixture-manifest",
                    str(FIXTURE_PATH),
                    "--output-dir",
                    str(root / "evidence"),
                    "--runtime-dir",
                    str(root / "runtime"),
                    "--mode",
                    "fake",
                    "--topology",
                    "in_process_onnx_cpu",
                    "--case-id",
                    "narration-neutral",
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            summary = json.loads((root / "evidence" / "metrics.json").read_text())
            self.assertEqual(summary["run_count"], 1)
            self.assertEqual(summary["case_count"], 1)
            self.assertEqual(summary["case_statuses"], {"passed": 1})

    def test_unknown_case_filter_fails_before_inference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--fixture-manifest",
                    str(FIXTURE_PATH),
                    "--output-dir",
                    str(root / "evidence"),
                    "--runtime-dir",
                    str(root / "runtime"),
                    "--mode",
                    "contract",
                    "--case-id",
                    "not-a-frozen-case",
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertIn("unknown frozen case id", completed.stderr)
            self.assertFalse((root / "evidence" / "metrics.json").exists())


if __name__ == "__main__":
    unittest.main()
