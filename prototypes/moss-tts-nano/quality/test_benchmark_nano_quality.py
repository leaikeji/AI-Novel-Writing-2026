from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
import wave


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DRIVER_PATH = REPOSITORY_ROOT / "scripts" / "tts" / "benchmark_nano_quality.py"
MANIFEST_PATH = REPOSITORY_ROOT / "tests" / "fixtures" / "narration" / "benchmark_manifest.json"
AUTHORIZED_PATH = REPOSITORY_ROOT / "tests" / "fixtures" / "narration" / "authorized-texts.json"
OFFICIAL_RUNNER = Path(__file__).with_name("official_onnx_quality_runner.py")
REPORT_RENDERER = REPOSITORY_ROOT / "scripts" / "tts" / "render_benchmark_report.py"


def load_driver():
    spec = importlib.util.spec_from_file_location("benchmark_nano_quality", DRIVER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_reference_wav(
    path: Path,
    *,
    duration_seconds: int = 3,
    sample_rate: int = 48_000,
    channels: int = 2,
) -> None:
    with wave.open(str(path), "wb") as target:
        target.setnchannels(channels)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        frame = struct.pack("<" + "h" * channels, *([120] * channels))
        target.writeframes(frame * (duration_seconds * sample_rate))


class NanoQualityDriverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.driver = load_driver()

    def test_frozen_fixture_validates(self) -> None:
        manifest, texts, cases = self.driver.validate_fixture_manifest(MANIFEST_PATH)
        self.assertEqual(manifest["schema_version"], "moss-tts-benchmark-manifest/1.0")
        self.assertEqual(len(texts), 26)
        self.assertEqual(len(cases), 27)

    def test_authorized_text_hash_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
            authorized = json.loads(AUTHORIZED_PATH.read_text(encoding="utf-8"))
            authorized["texts"][0]["text"] += "漂移"
            manifest["authorized_texts"]["path"] = "authorized-texts.json"
            (root / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
            )
            (root / "authorized-texts.json").write_text(
                json.dumps(authorized, ensure_ascii=False), encoding="utf-8"
            )
            with self.assertRaisesRegex(self.driver.BenchmarkError, "hash drift"):
                self.driver.validate_fixture_manifest(root / "manifest.json")

    def test_dry_run_never_marks_a_case_passed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"
            exit_code = self.driver.main(
                [
                    "--fixture-manifest",
                    str(MANIFEST_PATH),
                    "--output-dir",
                    str(output),
                    "--dry-run",
                ]
            )
            self.assertEqual(exit_code, 0)
            metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8"))
            statuses = {case["status"] for case in metrics["cases"]}
            self.assertNotIn("passed", statuses)
            self.assertEqual(statuses, {"skipped", "blocked"})
            reference_cases = [case for case in metrics["cases"] if case["input"]["reference_profile_id"]]
            self.assertTrue(reference_cases)
            self.assertTrue(all(case["status"] == "blocked" for case in reference_cases))

    def test_quality_matrix_selects_exactly_twenty_non_control_cases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"
            exit_code = self.driver.main(
                [
                    "--fixture-manifest",
                    str(MANIFEST_PATH),
                    "--output-dir",
                    str(output),
                    "--quality-matrix",
                    "--dry-run",
                ]
            )
            self.assertEqual(exit_code, 0)
            metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8"))
            case_ids = [case["case_id"] for case in metrics["cases"]]
            self.assertEqual(case_ids, list(self.driver.QUALITY_MATRIX_CASE_IDS))
            self.assertEqual(len(case_ids), 20)
            self.assertFalse(any(case["input"]["reference_profile_id"] for case in metrics["cases"]))
            self.assertTrue(all(case["status"] == "skipped" for case in metrics["cases"]))

    def test_fake_worker_reuses_one_process_and_joins_independent_segments(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            model = root / "model"
            media = root / "media"
            evidence = root / "evidence"
            source.mkdir()
            model.mkdir()
            (source / "runtime.py").write_text("# fixture source\n", encoding="utf-8")
            (model / "model.bin").write_bytes(b"fixture-model")
            exit_code = self.driver.main(
                [
                    "--fixture-manifest",
                    str(MANIFEST_PATH),
                    "--output-dir",
                    str(evidence),
                    "--source-dir",
                    str(source),
                    "--model-dir",
                    str(model),
                    "--media-output-dir",
                    str(media),
                    "--source-revision",
                    "fixture-source",
                    "--model-revision",
                    "fixture-model",
                    "--case-id",
                    "independent-segment-seams",
                    "--same-worker-probe-case-id",
                    "narration-neutral",
                    "--same-worker-probe-repetitions",
                    "3",
                    "--allow-fake-worker-for-tests",
                ]
            )
            self.assertEqual(exit_code, 0)
            metrics_text = (evidence / "metrics.json").read_text(encoding="utf-8")
            self.assertNotIn(str(root), metrics_text)
            metrics = json.loads(metrics_text)
            case = metrics["cases"][0]
            self.assertEqual(case["status"], "passed")
            self.assertEqual(case["diagnostics"]["runner_invocations"], 3)
            self.assertEqual(len(case["output"]["ready_segment_sha256"]), 3)
            self.assertTrue(case["diagnostics"]["independent_segments_joined_without_crossfade"])
            segments = case["diagnostics"]["managed_worker_segments"]
            self.assertEqual(len({segment["worker_pid"] for segment in segments}), 1)
            self.assertEqual(len({segment["worker_generation"] for segment in segments}), 1)
            self.assertTrue(
                case["diagnostics"]["timing_semantics"][
                    "internal_first_audio_is_not_client_playable"
                ]
            )
            self.assertEqual(case["timing"]["first_packet_ms"], segments[0]["request_to_ready_wav_ms"])
            worker = metrics["run"]["parameters"]["managed_worker"]
            self.assertTrue(worker["single_process_for_selected_cases"])
            self.assertGreater(worker["process_start_to_ready_ms"], 0)
            probe = metrics["run"]["parameters"]["managed_worker_same_request_probe"]
            self.assertTrue(probe["same_pid"])
            self.assertTrue(probe["same_generation"])
            self.assertEqual(probe["repetitions"], 3)
            self.assertEqual(case["listening"]["status"], "pending")
            self.assertNotEqual(case["listening"]["verdict"], "pass")
            rendered = subprocess.run(
                [str(REPOSITORY_ROOT / "prototypes" / "moss-tts-nano" / ".venv" / "bin" / "python"), str(REPORT_RENDERER), str(evidence / "metrics.json"), "--stdout-format", "json"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(rendered.returncode, 0, rendered.stderr)
            original_metrics_hash = hashlib.sha256((evidence / "metrics.json").read_bytes()).hexdigest()
            replace_exit = self.driver.main(
                [
                    "--fixture-manifest",
                    str(MANIFEST_PATH),
                    "--output-dir",
                    str(evidence),
                    "--dry-run",
                    "--replace-existing",
                ]
            )
            self.assertEqual(replace_exit, 2)
            self.assertEqual(
                hashlib.sha256((evidence / "metrics.json").read_bytes()).hexdigest(),
                original_metrics_hash,
            )

    def test_fake_worker_cannot_write_repository_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            model = root / "model"
            media = root / "media"
            source.mkdir()
            model.mkdir()
            (source / "runtime.py").write_text("# fixture source\n", encoding="utf-8")
            (model / "model.bin").write_bytes(b"fixture-model")
            forbidden_output = Path(__file__).parent / "forbidden-evidence"
            try:
                exit_code = self.driver.main(
                    [
                        "--fixture-manifest",
                        str(MANIFEST_PATH),
                        "--output-dir",
                        str(forbidden_output),
                        "--source-dir",
                        str(source),
                        "--model-dir",
                        str(model),
                        "--media-output-dir",
                        str(media),
                        "--source-revision",
                        "fixture-source",
                        "--model-revision",
                        "fixture-model",
                        "--case-id",
                        "narration-neutral",
                        "--allow-fake-worker-for-tests",
                    ]
                )
                self.assertEqual(exit_code, 2)
                self.assertFalse((forbidden_output / "metrics.json").exists())
            finally:
                shutil.rmtree(forbidden_output, ignore_errors=True)

    def test_reference_audio_is_not_silently_ignored_by_managed_worker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            model = root / "model"
            media = root / "media"
            evidence = root / "evidence"
            source.mkdir()
            model.mkdir()
            (source / "runtime.py").write_text("# fixture source\n", encoding="utf-8")
            (model / "model.bin").write_bytes(b"fixture-model")
            reference = root / "reference-03s.wav"
            write_reference_wav(reference)
            reference_hash = hashlib.sha256(reference.read_bytes()).hexdigest()
            exit_code = self.driver.main(
                [
                    "--fixture-manifest",
                    str(MANIFEST_PATH),
                    "--output-dir",
                    str(evidence),
                    "--source-dir",
                    str(source),
                    "--model-dir",
                    str(model),
                    "--media-output-dir",
                    str(media),
                    "--source-revision",
                    "fixture-source",
                    "--model-revision",
                    "fixture-model",
                    "--case-id",
                    "reference-placeholder-03s",
                    "--reference-audio",
                    f"ref-placeholder-03s={reference}",
                    "--reference-sha256",
                    f"ref-placeholder-03s={reference_hash}",
                    "--allow-fake-worker-for-tests",
                ]
            )
            self.assertEqual(exit_code, 0)
            metrics_text = (evidence / "metrics.json").read_text(encoding="utf-8")
            self.assertNotIn(str(root), metrics_text)
            metrics = json.loads(metrics_text)
            case = metrics["cases"][0]
            self.assertEqual(case["status"], "blocked")
            self.assertEqual(case["error"]["code"], "managed_worker_reference_audio_unsupported")
            telemetry = metrics["run"]["parameters"]["managed_worker"]["telemetry"]
            self.assertEqual(telemetry["synthesis_counts_by_text_sha256"], {})

    def test_reference_cli_rejects_unpaired_values_and_redacts_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            private_reference = root / "private-reference.wav"
            write_reference_wav(private_reference)
            sanitized = self.driver.sanitize_argv(
                [
                    "--reference-audio",
                    f"ref-placeholder-03s={private_reference}",
                ]
            )
            self.assertNotIn(str(private_reference), json.dumps(sanitized))
            self.assertIn("<profile>=<external-reference-audio>", sanitized)

            output = root / "evidence"
            exit_code = self.driver.main(
                [
                    "--fixture-manifest",
                    str(MANIFEST_PATH),
                    "--output-dir",
                    str(output),
                    "--reference-audio",
                    f"ref-placeholder-03s={private_reference}",
                    "--dry-run",
                ]
            )
            self.assertEqual(exit_code, 2)
            self.assertFalse((output / "metrics.json").exists())

    def test_reference_validation_rejects_hash_duration_format_and_symlink(self) -> None:
        profile = {"id": "ref-placeholder-03s", "target_duration_seconds": 3}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            valid = root / "valid.wav"
            write_reference_wav(valid)
            valid_hash = hashlib.sha256(valid.read_bytes()).hexdigest()
            observed_hash, inspection = self.driver.validate_reference_audio(
                profile=profile,
                reference_path=valid,
                expected_hash=valid_hash,
                tolerance_seconds=0.0,
            )
            self.assertEqual(observed_hash, valid_hash)
            self.assertEqual(inspection["duration_seconds"], 3.0)

            with self.assertRaisesRegex(self.driver.BenchmarkError, "hash mismatch"):
                self.driver.validate_reference_audio(
                    profile=profile,
                    reference_path=valid,
                    expected_hash="0" * 64,
                    tolerance_seconds=0.0,
                )

            short = root / "short.wav"
            write_reference_wav(short, duration_seconds=1)
            with self.assertRaisesRegex(self.driver.BenchmarkError, "duration"):
                self.driver.validate_reference_audio(
                    profile=profile,
                    reference_path=short,
                    expected_hash=hashlib.sha256(short.read_bytes()).hexdigest(),
                    tolerance_seconds=0.0,
                )

            mono = root / "mono.wav"
            write_reference_wav(mono, channels=1)
            with self.assertRaisesRegex(self.driver.BenchmarkError, "48 kHz stereo"):
                self.driver.validate_reference_audio(
                    profile=profile,
                    reference_path=mono,
                    expected_hash=hashlib.sha256(mono.read_bytes()).hexdigest(),
                    tolerance_seconds=0.0,
                )

            link = root / "link.wav"
            link.symlink_to(valid)
            with self.assertRaisesRegex(self.driver.BenchmarkError, "symbolic link"):
                self.driver.validate_reference_audio(
                    profile=profile,
                    reference_path=link,
                    expected_hash=valid_hash,
                    tolerance_seconds=0.0,
                )

            with self.assertRaisesRegex(self.driver.BenchmarkError, "external controlled"):
                self.driver.validate_reference_audio(
                    profile=profile,
                    reference_path=AUTHORIZED_PATH,
                    expected_hash=hashlib.sha256(AUTHORIZED_PATH.read_bytes()).hexdigest(),
                    tolerance_seconds=0.0,
                )

    def test_official_runner_rejects_bad_text_hash_before_model_import(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            model = root / "model"
            source.mkdir()
            model.mkdir()
            for name in ("onnx_tts_runtime.py", "ort_cpu_runtime.py", "text_normalization_pipeline.py"):
                (source / name).write_text("# must not be imported\n", encoding="utf-8")
            request_path = root / "request.json"
            response_path = root / "response.json"
            output_path = root / "output.wav"
            request = {
                "schema_version": "moss-tts-quality-runner-request/1.0",
                "text": "哈希必须拒绝",
                "text_sha256": hashlib.sha256("不同文本".encode("utf-8")).hexdigest(),
                "source_dir": str(source),
                "model_dir": str(model),
                "output_wav": str(output_path),
                "reference_audio": None,
                "voice": "default",
                "seed": 0,
                "cpu_threads": 4,
                "execution_backend": "onnx-cpu",
                "sample_mode": "fixed",
                "streaming": True,
                "max_new_frames": 375,
                "voice_clone_max_text_tokens": 75,
                "enable_wetext": False,
                "enable_normalize_tts_text": True,
            }
            request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
            import subprocess
            import sys

            completed = subprocess.run(
                [
                    sys.executable,
                    str(OFFICIAL_RUNNER),
                    "--request",
                    str(request_path),
                    "--response",
                    str(response_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 2)
            response = json.loads(response_path.read_text(encoding="utf-8"))
            self.assertEqual(response["status"], "failed")
            self.assertEqual(response["error"]["code"], "RunnerInputError")
            self.assertFalse(output_path.exists())


if __name__ == "__main__":
    unittest.main()
