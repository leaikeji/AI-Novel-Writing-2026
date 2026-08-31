from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import sys
import tempfile

import pytest


MODULE_PATH = Path(__file__).with_name("artifact_manifest.py")
SPEC = importlib.util.spec_from_file_location("vg40_artifact_manifest", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MANIFEST = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MANIFEST
SPEC.loader.exec_module(MANIFEST)


def component(payload=b"fixed"):
    return {
        "id": "voice-generator",
        "repository": "OpenMOSS-Team/MOSS-VoiceGenerator",
        "provider": "hugging_face",
        "revision": "9" * 40,
        "resolve_base_url": (
            "https://huggingface.co/OpenMOSS-Team/MOSS-VoiceGenerator/resolve/"
            + "9" * 40
            + "/"
        ),
        "selected_bytes": len(payload),
        "files": [
            {
                "path": "weights/model.bin",
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        ],
    }


def manifest():
    return {
        "schema_version": "vg40-model-source-manifest/1",
        "download_ready": True,
        "selected_total_bytes": len(b"fixed"),
        "components": [component()],
    }


def test_manifest_requires_frozen_official_revision_and_ready_allowlist():
    MANIFEST.validate_manifest(manifest())
    draft = manifest()
    draft["download_ready"] = False
    with pytest.raises(MANIFEST.ManifestError):
        MANIFEST.validate_manifest(draft)
    floating = manifest()
    floating["components"][0]["revision"] = "main"
    with pytest.raises(MANIFEST.ManifestError):
        MANIFEST.validate_manifest(floating)
    zero_sized_init = manifest()
    zero_sized_init["components"][0]["files"][0].update(
        {
            "path": "__init__.py",
            "bytes": 0,
            "sha256": hashlib.sha256(b"").hexdigest(),
        }
    )
    zero_sized_init["components"][0]["selected_bytes"] = 0
    zero_sized_init["selected_total_bytes"] = 0
    MANIFEST.validate_manifest(zero_sized_init)

    fake_official = manifest()
    fake_official["components"][0]["repository"] = "OpenMOSS-Team/Unknown"
    with pytest.raises(MANIFEST.ManifestError):
        MANIFEST.validate_manifest(fake_official)


def test_snapshot_requires_exact_regular_file_set_size_and_digest():
    payload = b"fixed"
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        target = root / "weights" / "model.bin"
        target.parent.mkdir()
        target.write_bytes(payload)
        verified = MANIFEST.verify_snapshot(root, component(payload))
        assert verified["file_count"] == 1
        (root / "unknown.txt").write_text("no", encoding="utf-8")
        with pytest.raises(MANIFEST.ManifestError):
            MANIFEST.verify_snapshot(root, component(payload))


def test_snapshot_rejects_missing_digest_mismatch_and_symlink():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        target = root / "weights" / "model.bin"
        target.parent.mkdir()
        with pytest.raises(MANIFEST.ManifestError):
            MANIFEST.verify_snapshot(root, component())
        target.write_bytes(b"wrong")
        with pytest.raises(MANIFEST.ManifestError):
            MANIFEST.verify_snapshot(root, component())
        target.unlink()
        external = root.parent / "vg40-manifest-external"
        external.write_bytes(b"fixed")
        try:
            target.symlink_to(external)
            with pytest.raises(MANIFEST.ManifestError):
                MANIFEST.verify_snapshot(root, component())
        finally:
            external.unlink(missing_ok=True)


def test_disk_gate_enforces_both_before_and_after_thresholds(monkeypatch):
    usage_type = type("Usage", (), {})
    usage = usage_type()
    usage.total = 100 * MANIFEST.GIB
    usage.used = 50 * MANIFEST.GIB
    usage.free = 43 * MANIFEST.GIB
    monkeypatch.setattr(MANIFEST.shutil, "disk_usage", lambda _: usage)
    MANIFEST.assert_disk_gate(Path("."), 10 * MANIFEST.GIB)
    with pytest.raises(MANIFEST.ManifestError):
        MANIFEST.assert_disk_gate(Path("."), 20 * MANIFEST.GIB)
    usage.free = 41 * MANIFEST.GIB
    with pytest.raises(MANIFEST.ManifestError):
        MANIFEST.assert_disk_gate(Path("."), MANIFEST.GIB)
