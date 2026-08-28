from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import wave

SIDECAR_ROOT = Path(__file__).resolve().parent
if str(SIDECAR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIDECAR_ROOT))

from run_sidecar_gate import ReferenceManifestError, load_reference_manifest, reference_recheck


PROFILES = (("03", 3), ("05", 5), ("08", 8), ("12", 12))


def write_wav(path: Path, duration_seconds: float) -> dict[str, object]:
    sample_rate = 48_000
    frame_count = int(duration_seconds * sample_rate)
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(2)
        stream.setsampwidth(2)
        stream.setframerate(sample_rate)
        stream.writeframes(b"\x00\x00\x00\x00" * frame_count)
    payload = path.read_bytes()
    return {
        "file_size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "actual_duration_seconds": duration_seconds,
        "frame_count": frame_count,
        "sample_rate_hz": sample_rate,
        "channels": 2,
        "sample_width_bytes": 2,
    }


class ReferenceManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        assets: list[dict[str, object]] = []
        for profile, seconds in PROFILES:
            name = f"reference-{seconds}s.wav"
            descriptor = write_wav(self.root / name, float(seconds))
            assets.append(
                {
                    "technical_profile_id": f"isolated-tech-ref-{profile}s",
                    "target_duration_seconds": seconds,
                    "atrim_end_sample": 48_000 * seconds,
                    "file_name": name,
                    **descriptor,
                    "pcm_sha256": "0" * 64,
                    "codec": "pcm_sle",
                    "container": "WAV",
                    "source_pcm_prefix_exact": True,
                    "repeat_build_byte_exact": True,
                }
            )
        self.manifest = {
            "schema_version": "moss-tts-reference-prep/1.0",
            "status": "prepared_isolated_test_only",
            "repository_contains_audio": False,
            "assets": assets,
            "rights_and_scope": {
                "classification": "isolated-test-only technical reference candidate",
                "production_rights_granted": False,
                "product_voice_asset": False,
                "distribution_allowed": False,
            },
        }
        self.manifest_path = self.root / "asset-manifest.json"
        self.write_manifest()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_manifest(self) -> None:
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")

    def test_valid_manifest_and_four_files_return_machine_auditable_inputs(self) -> None:
        fixtures = load_reference_manifest(self.manifest_path, self.root)
        self.assertEqual([row.file_name for row in fixtures], ["reference-3s.wav", "reference-5s.wav", "reference-8s.wav", "reference-12s.wav"])
        for fixture, (_, seconds) in zip(fixtures, PROFILES, strict=True):
            audit = fixture.evidence()
            self.assertEqual(audit["expected_sha256"], audit["actual_sha256"])
            self.assertEqual(audit["expected_size_bytes"], audit["actual_size_bytes"])
            self.assertEqual(audit["expected_duration_seconds"], float(seconds))
            self.assertEqual(audit["actual_duration_seconds"], float(seconds))
            self.assertEqual(audit["duration_tolerance_seconds"], 1 / 48_000)
            self.assertNotIn("path", audit)

    def test_reference_recheck_persists_pre_and_post_input_audits(self) -> None:
        fixtures = load_reference_manifest(self.manifest_path, self.root)

        class FakeGate:
            def compose(self, *_args: object, **_kwargs: object) -> bytes:
                return b""

            def wait_healthy(self) -> None:
                return None

            def inspect_sidecar(self) -> dict[str, object]:
                return {"health": "healthy"}

            def docker_stats(self, _container: str) -> dict[str, object]:
                return {"MemUsage": "1GiB / 4GiB"}

            def container_id(self, _service: str) -> str:
                return "sidecar-id"

            def qwenpaw_snapshot(self) -> dict[str, object]:
                return {"health": "healthy"}

            def host_memory_snapshot(self) -> dict[str, object]:
                return {"causality": "snapshot_only"}

            def capability(self) -> dict[str, object]:
                return {"status": "ready"}

            def scratch_audit(self) -> dict[str, object]:
                return {"scratch_file_count": 0, "partial_count": 0}

            def harness(self, row: dict[str, object]) -> dict[str, object]:
                if row["operation"] == "audit_storage":
                    return {"wav_count": 4, "partial_count": 0, "unexpected_file_count": 0}
                return {"status": "published", "sha256": "a" * 64}

        result = reference_recheck(FakeGate(), fixtures, self.manifest_path, self.root)  # type: ignore[arg-type]
        self.assertEqual(result["status"], "passed")
        events = result["events"]
        self.assertEqual(len(events), 4)
        for event in events:
            before = event["reference_input"]["pre_request"]
            after = event["reference_input"]["post_request"]
            self.assertEqual(before, after)
            self.assertEqual(before["expected_sha256"], before["actual_sha256"])

    def test_schema_status_and_rights_are_strict(self) -> None:
        mutations = (
            ("schema_version", "wrong/1.0"),
            ("status", "product_ready"),
            ("repository_contains_audio", True),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                original = self.manifest[field]
                self.manifest[field] = value
                self.write_manifest()
                with self.assertRaises(ReferenceManifestError):
                    load_reference_manifest(self.manifest_path, self.root)
                self.manifest[field] = original
        self.manifest["rights_and_scope"]["production_rights_granted"] = True
        self.write_manifest()
        with self.assertRaisesRegex(ReferenceManifestError, "rights"):
            load_reference_manifest(self.manifest_path, self.root)

    def test_filename_profile_count_and_order_fail_closed(self) -> None:
        self.manifest["assets"][0]["file_name"] = "../reference-3s.wav"
        self.write_manifest()
        with self.assertRaisesRegex(ReferenceManifestError, "filename"):
            load_reference_manifest(self.manifest_path, self.root)
        self.manifest["assets"] = self.manifest["assets"][:-1]
        self.write_manifest()
        with self.assertRaisesRegex(ReferenceManifestError, "four profiles"):
            load_reference_manifest(self.manifest_path, self.root)

    def test_declared_size_and_sha_must_match_actual_bytes(self) -> None:
        for field, value, pattern in (
            ("file_size_bytes", 1, "size"),
            ("sha256", "f" * 64, "SHA-256"),
        ):
            with self.subTest(field=field):
                original = self.manifest["assets"][0][field]
                self.manifest["assets"][0][field] = value
                self.write_manifest()
                with self.assertRaisesRegex(ReferenceManifestError, pattern):
                    load_reference_manifest(self.manifest_path, self.root)
                self.manifest["assets"][0][field] = original

    def test_format_and_exact_duration_with_one_frame_tolerance(self) -> None:
        self.manifest["assets"][0]["container"] = "FLAC"
        self.write_manifest()
        with self.assertRaisesRegex(ReferenceManifestError, "format"):
            load_reference_manifest(self.manifest_path, self.root)

        self.manifest["assets"][0]["container"] = "WAV"
        self.manifest["assets"][0]["actual_duration_seconds"] = 3.01
        self.write_manifest()
        with self.assertRaisesRegex(ReferenceManifestError, "duration"):
            load_reference_manifest(self.manifest_path, self.root)

        descriptor = write_wav(self.root / "reference-3s.wav", 3.01)
        self.manifest["assets"][0].update(descriptor)
        self.manifest["assets"][0]["actual_duration_seconds"] = 3.0
        self.manifest["assets"][0]["frame_count"] = 144_000
        self.write_manifest()
        with self.assertRaisesRegex(ReferenceManifestError, "duration"):
            load_reference_manifest(self.manifest_path, self.root)


if __name__ == "__main__":
    unittest.main()
