from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import pytest

from scripts.tts.isolate_retired_tts_media import (
    inspect_isolation,
    isolate,
    purge_isolation,
    restore,
)


def _manifest(tmp_path: Path, payload: bytes) -> tuple[Path, Path, Path, Path]:
    media_root = tmp_path / "media"
    isolation_root = tmp_path / "isolation"
    relative = Path("assets/aa/asset-id/audio.wav")
    source = media_root / relative
    source.parent.mkdir(parents=True)
    source.write_bytes(payload)
    manifest = tmp_path / "retired-media.csv"
    with manifest.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(
            target,
            fieldnames=["id", "storage_backend", "storage_path", "byte_size", "content_hash"],
        )
        writer.writeheader()
        writer.writerow({
            "id": "asset-id",
            "storage_backend": "local",
            "storage_path": relative.as_posix(),
            "byte_size": len(payload),
            "content_hash": hashlib.sha256(payload).hexdigest(),
        })
    return manifest, media_root, isolation_root, source


def test_isolation_can_be_restored_only_with_the_frozen_manifest(tmp_path: Path) -> None:
    manifest, media_root, isolation_root, source = _manifest(tmp_path, b"retired-audio")
    manifest_sha256 = hashlib.sha256(manifest.read_bytes()).hexdigest()

    result = isolate(
        manifest_path=manifest,
        media_root=media_root,
        isolation_root=isolation_root,
        apply=True,
        confirmed_manifest_sha256=manifest_sha256,
    )
    assert result["moved_count"] == 1
    assert not source.exists()

    inspected = inspect_isolation(
        manifest_path=manifest,
        media_root=media_root,
        isolation_root=isolation_root,
        confirmed_manifest_sha256=manifest_sha256,
    )
    assert inspected["verified_count"] == 1

    with pytest.raises(ValueError, match="exact frozen manifest"):
        restore(
            manifest_path=manifest,
            media_root=media_root,
            isolation_root=isolation_root,
            confirmed_manifest_sha256="0" * 64,
        )

    restored = restore(
        manifest_path=manifest,
        media_root=media_root,
        isolation_root=isolation_root,
        confirmed_manifest_sha256=manifest_sha256,
    )
    assert restored["moved_count"] == 1
    assert source.read_bytes() == b"retired-audio"


def test_isolation_purge_removes_only_verified_allowlisted_files(tmp_path: Path) -> None:
    manifest, media_root, isolation_root, source = _manifest(tmp_path, b"retired-audio")
    manifest_sha256 = hashlib.sha256(manifest.read_bytes()).hexdigest()
    isolate(
        manifest_path=manifest,
        media_root=media_root,
        isolation_root=isolation_root,
        apply=True,
        confirmed_manifest_sha256=manifest_sha256,
    )

    result = purge_isolation(
        manifest_path=manifest,
        media_root=media_root,
        isolation_root=isolation_root,
        confirmed_manifest_sha256=manifest_sha256,
    )

    assert result["purged_count"] == 1
    assert result["byte_size"] == len(b"retired-audio")
    assert not source.exists()
    assert list(isolation_root.iterdir()) == []
