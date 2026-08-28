from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.narration import disk_guard as guard_module
from backend.narration.disk_guard import (
    DISK_SPACE_INSUFFICIENT,
    MINIMUM_MEDIA_FREE_BYTES,
    NarrationDiskGuard,
    NarrationDiskGuardError,
    STORAGE_IDENTITY_FAILURE,
)
from backend.narration.storage import NarrationStorage


def _storage(tmp_path: Path) -> NarrationStorage:
    models = tmp_path / "models"
    media = tmp_path / "media"
    models.mkdir(mode=0o750)
    media.mkdir(mode=0o750)
    return NarrationStorage(models_root=models, media_root=media)


def _capacity(free_bytes: int) -> SimpleNamespace:
    block_size = 4096
    return SimpleNamespace(
        f_bavail=free_bytes // block_size,
        f_frsize=block_size,
        f_blocks=(MINIMUM_MEDIA_FREE_BYTES * 8) // block_size,
    )


def test_disk_guard_blocks_below_one_gib_and_recovers_without_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = _storage(tmp_path)
    observations = iter(
        (
            _capacity(MINIMUM_MEDIA_FREE_BYTES - 4096),
            _capacity(MINIMUM_MEDIA_FREE_BYTES + 4096),
        )
    )
    monkeypatch.setattr(guard_module.os, "fstatvfs", lambda _fd: next(observations))
    guard = NarrationDiskGuard(storage)

    assert guard.claim_allowed() is False
    assert guard.status().reason_code == DISK_SPACE_INSUFFICIENT
    assert guard.claim_allowed() is True
    assert guard.status().reason_code is None
    assert list((tmp_path / "media").iterdir()) == []


def test_disk_guard_raises_stable_path_free_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = _storage(tmp_path)
    monkeypatch.setattr(
        guard_module.os,
        "fstatvfs",
        lambda _fd: _capacity(MINIMUM_MEDIA_FREE_BYTES - 4096),
    )
    guard = NarrationDiskGuard(storage)

    with pytest.raises(NarrationDiskGuardError) as captured:
        guard.require_available()

    assert captured.value.code == DISK_SPACE_INSUFFICIENT
    assert str(tmp_path) not in str(captured.value)


def test_disk_guard_fails_closed_when_bound_media_root_is_replaced(
    tmp_path: Path,
) -> None:
    storage = _storage(tmp_path)
    media = tmp_path / "media"
    original = tmp_path / "media-original"
    os.rename(media, original)
    media.mkdir(mode=0o750)
    guard = NarrationDiskGuard(storage)

    status = guard.refresh()

    assert status.reason_code == STORAGE_IDENTITY_FAILURE
    assert status.free_bytes is None
    assert status.total_bytes is None
    assert str(tmp_path) not in NarrationDiskGuardError(status.reason_code).args[0]
