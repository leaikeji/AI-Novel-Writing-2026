from __future__ import annotations

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "docker/tts-sidecar/Dockerfile"
PINNED_RUNTIME_SOURCES = {
    ROOT / "backend/narration/sidecar_server.py": "runtime/sidecar_server.py",
    ROOT / "backend/narration/runtime.py": "runtime/runtime.py",
    ROOT / "backend/narration/model_assets.py": "runtime/model_assets.py",
    ROOT / "scripts/tts/install_models.py": "runtime/install_models.py",
    ROOT / "docker/tts-sidecar/init_runtime_volumes.py": (
        "runtime/init_runtime_volumes.py"
    ),
}


def test_production_sidecar_pins_every_copied_runtime_source_by_current_sha256() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    for source, image_path in PINNED_RUNTIME_SOURCES.items():
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        assert f'{digest}  {image_path}" | sha256sum --check --strict' in dockerfile
