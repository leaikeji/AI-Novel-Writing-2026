from __future__ import annotations

import builtins
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DRIVER_PATH = REPOSITORY_ROOT / "scripts" / "tts" / "benchmark_voice_generator.py"
MANIFEST_PATH = (
    REPOSITORY_ROOT / "tests" / "fixtures" / "narration" / "benchmark_manifest.json"
)
AUTHORIZED_PATH = (
    REPOSITORY_ROOT / "tests" / "fixtures" / "narration" / "authorized-texts.json"
)
BASELINE_PATH = Path(__file__).with_name("metadata-baseline.json")
MODEL_LOCK_PATH = REPOSITORY_ROOT / "prototypes" / "moss-tts-nano" / "model-sources.lock.json"
REPORT_PATH = REPOSITORY_ROOT / "scripts" / "tts" / "render_benchmark_report.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VoiceGeneratorAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.driver = load_module(DRIVER_PATH, "benchmark_voice_generator")
        cls.report = load_module(REPORT_PATH, "render_benchmark_report_t0d")

    def test_frozen_metadata_matches_t0a_lock_and_fails_closed(self) -> None:
        baseline, _model_lock = self.driver.validate_metadata_baseline(
            BASELINE_PATH, MODEL_LOCK_PATH
        )
        feasibility = self.driver.derive_feasibility(baseline)
        self.assertEqual(feasibility["decision"], "hide")
        self.assertEqual(feasibility["real_model_downloads"], 0)
        self.assertEqual(feasibility["real_model_loads"], 0)
        self.assertEqual(feasibility["combined_snapshot_bytes"], 11_345_349_008)
        self.assertEqual(feasibility["cpu_static_weight_estimate_bytes"], 15_555_019_472)
        self.assertFalse(feasibility["cpu_headroom_gate_passed"])
        self.assertFalse(feasibility["official_mps_path_claimed"])
        self.assertFalse(feasibility["full_codec_revision_frozen_in_t0_a"])

    def test_default_run_emits_contract_valid_blocked_result_without_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"
            exit_code = self.driver.main(
                [
                    "--fixture-manifest",
                    str(MANIFEST_PATH),
                    "--output-dir",
                    str(output),
                    "--metadata-baseline",
                    str(BASELINE_PATH),
                    "--model-lock",
                    str(MODEL_LOCK_PATH),
                    "--dry-run",
                ]
            )
            self.assertEqual(exit_code, 0)
            metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8"))
            self.report.validate_result(metrics, "metrics.json")
            self.assertEqual(metrics["run"]["status"], "blocked")
            self.assertEqual(metrics["run"]["model"]["execution_backend"], "metadata-audit-no-model-import")
            self.assertTrue(metrics["cases"])
            self.assertEqual({case["status"] for case in metrics["cases"]}, {"blocked"})
            self.assertTrue(
                all(case["output"]["audio_sha256"] is None for case in metrics["cases"])
            )
            self.assertTrue(
                all(case["diagnostics"]["audio_files_created"] == 0 for case in metrics["cases"])
            )

    def test_corrupt_fixture_is_rejected_before_source_or_model_import(self) -> None:
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
            output = root / "evidence"
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                exit_code = self.driver.main(
                    [
                        "--fixture-manifest",
                        str(root / "manifest.json"),
                        "--output-dir",
                        str(output),
                        "--metadata-baseline",
                        str(BASELINE_PATH),
                        "--model-lock",
                        str(MODEL_LOCK_PATH),
                        "--source-audit-dir",
                        str(root / "deliberately-missing-source"),
                    ]
                )
            self.assertEqual(exit_code, 2)
            self.assertIn("hash drift", stderr.getvalue())
            self.assertNotIn("source audit directory", stderr.getvalue())
            self.assertFalse((output / "metrics.json").exists())

    def test_reference_placeholders_cannot_silently_claim_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
            manifest["authorized_texts"]["path"] = "authorized-texts.json"
            manifest["reference_profiles"][0]["asset_path"] = "invented.wav"
            manifest["reference_profiles"][0]["sha256"] = "0" * 64
            (root / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
            )
            (root / "authorized-texts.json").write_bytes(AUTHORIZED_PATH.read_bytes())
            with self.assertRaisesRegex(self.driver.AuditError, "must not claim an asset"):
                self.driver.validate_fixture_manifest(root / "manifest.json")

    def test_source_text_audit_checks_cuda_cpu_and_codec_without_importing(self) -> None:
        model_card = '''
import torch
device = "cuda" if torch.cuda.is_available() else "cpu"
dtype = torch.bfloat16 if device == "cuda" else torch.float32
'''
        processor = '''
audio_tokenizer_name_or_path = kwargs.pop(
    "codec_path", "OpenMOSS-Team/MOSS-Audio-Tokenizer"
)
'''
        config = {
            "dtype": "bfloat16",
            "language_config": {"_name_or_path": "Qwen/Qwen3-1.7B"},
        }
        pyproject = '"torch==2.9.1+cu128"\n"transformers==5.0.0"\n'
        original_import = builtins.__import__

        def refuse_model_import(name, *args, **kwargs):
            if name.split(".", 1)[0] in {"torch", "transformers", "torchaudio"}:
                raise AssertionError("model library import attempted")
            return original_import(name, *args, **kwargs)

        builtins.__import__ = refuse_model_import
        try:
            audit = self.driver.audit_fixed_source_text(
                model_card, processor, config, pyproject
            )
        finally:
            builtins.__import__ = original_import
        self.assertTrue(audit["metadata_audit_passed"])
        self.assertFalse(audit["explicit_mps_branch_present"])
        self.assertFalse(audit["official_mps_path_supported"])
        self.assertTrue(audit["default_full_codec_path_present"])

    def test_existing_metrics_are_not_overwritten_without_explicit_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"
            args = [
                "--fixture-manifest",
                str(MANIFEST_PATH),
                "--output-dir",
                str(output),
                "--metadata-baseline",
                str(BASELINE_PATH),
                "--model-lock",
                str(MODEL_LOCK_PATH),
            ]
            self.assertEqual(self.driver.main(args), 0)
            original = (output / "metrics.json").read_bytes()
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                self.assertEqual(self.driver.main(args), 2)
            self.assertEqual((output / "metrics.json").read_bytes(), original)
            self.assertIn("already exists", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
