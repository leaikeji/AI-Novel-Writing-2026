from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
PROTOTYPE_ROOT = ROOT.parents[1]


def compose_config(path: Path, environment: dict[str, str]) -> dict[str, object]:
    completed = subprocess.run(
        ["docker", "compose", "-f", str(path), "config", "--format", "json"],
        cwd=PROTOTYPE_ROOT,
        env=os.environ | environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


class ContainerPolicyTests(unittest.TestCase):
    def test_production_compose_is_private_and_sidecar_has_no_business_mount(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            token = root / "token"
            token.write_text("f" * 64, encoding="ascii")
            for name in ("models", "source", "reference"):
                (root / name).mkdir()
            (root / "media").mkdir()
            config = compose_config(
                ROOT / "compose.production.yaml",
                {
                    "MOSS_SIDECAR_TOKEN_FILE": str(token),
                    "MOSS_MODEL_ROOT": str(root / "models"),
                    "MOSS_SOURCE_ROOT": str(root / "source"),
                    "MOSS_REFERENCE_FIXTURE_ROOT": str(root / "reference"),
                    "MOSS_PAWAPP_MEDIA_ROOT": str(root / "media"),
                    "MOSS_MODEL_TREE_SHA256": "1" * 64,
                    "MOSS_SOURCE_TREE_SHA256": "2" * 64,
                },
            )
        services = config["services"]
        sidecar = services["sidecar"]
        self.assertNotIn("ports", sidecar)
        self.assertEqual(sidecar["expose"], ["8765"])
        self.assertEqual(sidecar["platform"], "linux/arm64")
        self.assertTrue(sidecar["read_only"])
        self.assertEqual(sidecar["user"], "65532:65532")
        self.assertEqual(sidecar["cap_drop"], ["ALL"])
        self.assertIn("no-new-privileges:true", sidecar["security_opt"])
        self.assertNotIn("build", sidecar)
        self.assertEqual(
            sidecar["image"],
            "ai-novel-world/moss-tts-sidecar@sha256:56bb12bdef8f0c8c174ec86aa4dfbeac1dee1dd9cb9a215ff305eca7c8307fe0",
        )
        self.assertEqual(services["pawapp-harness"]["image"], sidecar["image"])
        self.assertEqual(set(sidecar["networks"]), {"tts_private"})
        self.assertTrue(config["networks"]["tts_private"]["internal"])
        mounts = {row["target"]: row for row in sidecar["volumes"]}
        self.assertEqual(set(mounts), {"/models", "/source"})
        self.assertTrue(all(row["read_only"] for row in mounts.values()))
        serialized = json.dumps(sidecar, sort_keys=True).lower()
        self.assertNotIn("novel-media", serialized)
        self.assertNotIn("database", serialized)
        self.assertNotIn("postgres", serialized)
        self.assertEqual(sidecar["environment"]["MOSS_SIDECAR_TOKEN_FILE"], "/run/secrets/moss_sidecar_token")
        self.assertNotIn("MOSS_SIDECAR_TOKEN", sidecar["environment"])
        pawapp_mounts = {row["target"] for row in services["pawapp-harness"]["volumes"]}
        self.assertIn("/pawapp-media", pawapp_mounts)
        self.assertNotIn("/pawapp-media", mounts)

    def test_dockerfile_pins_base_wheels_ffmpeg_and_non_root_runtime(self) -> None:
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("python:3.11.16-slim-bookworm@sha256:", dockerfile)
        self.assertIn("--require-hashes --only-binary=:all:", dockerfile)
        self.assertIn("cf38e0e28c7e5605942c4a77755349b0145804a397af37eb1fb4c77cb237f635", dockerfile)
        for flag in ("--disable-network", "--disable-gpl", "--disable-nonfree", "--disable-everything"):
            self.assertIn(flag, dockerfile)
        self.assertIn("printf '' > /etc/apt/sources.list.d/debian.sources", dockerfile)
        self.assertIn("https://snapshot.debian.org/archive/debian/%s", dockerfile)
        self.assertNotIn("deb.debian.org", dockerfile)
        self.assertIn(
            "COPY --from=ffmpeg-builder /usr/lib/aarch64-linux-gnu/libgomp.so.1* /usr/lib/aarch64-linux-gnu/",
            dockerfile,
        )
        self.assertIn("USER 65532:65532", dockerfile)

    def test_candidate_image_lock_matches_build_inputs(self) -> None:
        lock = json.loads((ROOT / "image-lock.json").read_text(encoding="utf-8"))
        self.assertTrue(lock["candidate_only"])
        self.assertEqual(lock["platform"], "linux/arm64")
        inputs = lock["build_inputs"]
        expected = {
            "dockerfile_sha256": ROOT / "Dockerfile",
            "compose_production_sha256": ROOT / "compose.production.yaml",
            "python_requirements_lock_sha256": PROTOTYPE_ROOT / "python-requirements.lock",
            "model_sources_lock_sha256": PROTOTYPE_ROOT / "model-sources.lock.json",
            "sidecar_protocol_sha256": ROOT / "sidecar_protocol.py",
            "sidecar_server_sha256": ROOT / "sidecar_server.py",
            "sidecar_client_sha256": ROOT / "sidecar_client.py",
            "pawapp_harness_sha256": ROOT / "pawapp_harness.py",
        }
        for key, path in expected.items():
            self.assertEqual(inputs[key], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertRegex(lock["image"]["manifest_list_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(lock["image"]["arm64_manifest_sha256"], r"^[0-9a-f]{64}$")
        wheel_names = {row["name"] for row in lock["python_wheels"]}
        self.assertEqual(
            wheel_names,
            {"numpy", "onnxruntime", "soundfile", "tokenizers", "torch", "torchaudio", "transformers"},
        )

    def test_production_request_schema_has_no_sidecar_path_or_url(self) -> None:
        from sidecar_protocol import REQUEST_KEYS, REQUEST_KEYS_WITH_REFERENCE

        self.assertEqual(REQUEST_KEYS, {"request_id", "asset_id", "text", "parameters"})
        self.assertEqual(REQUEST_KEYS_WITH_REFERENCE - REQUEST_KEYS, {"reference_audio"})
        protocol_source = (ROOT / "sidecar_protocol.py").read_text(encoding="utf-8")
        self.assertIn('FORBIDDEN_KEY_FRAGMENTS = ("path", "directory", "database", "dsn", "url", "token")', protocol_source)


if __name__ == "__main__":
    unittest.main()
