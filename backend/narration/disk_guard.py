"""Fail-closed free-space guard for the fixed narration media root.

The guard never creates or removes files.  Each observation opens the already
bound media root without following symlinks, verifies its device/inode, and
uses ``fstatvfs`` on that descriptor so path replacement cannot redirect the
capacity check.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import stat
from threading import Lock
from typing import Final

from .storage import NarrationStorage, StorageRootChanged


MINIMUM_MEDIA_FREE_BYTES: Final = 1024 * 1024 * 1024
DISK_SPACE_INSUFFICIENT: Final = "DISK_SPACE_INSUFFICIENT"
STORAGE_IDENTITY_FAILURE: Final = "STORAGE_IDENTITY_FAILURE"

_UNSAFE_DIRECTORY_WRITE_BITS = stat.S_IWGRP | stat.S_IWOTH


class NarrationDiskGuardError(RuntimeError):
    """Stable, path-free refusal raised before external or media work."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__("narration media capacity is unavailable")


@dataclass(frozen=True, slots=True)
class NarrationDiskStatus:
    free_bytes: int | None
    total_bytes: int | None
    minimum_free_bytes: int
    reason_code: str | None

    @property
    def available(self) -> bool:
        return self.reason_code is None


def secure_media_disk_usage(storage: NarrationStorage) -> tuple[int, int]:
    """Return free/total bytes after descriptor-bound root verification."""

    if type(storage) is not NarrationStorage:
        raise TypeError("disk usage requires NarrationStorage")
    root = storage.media
    descriptor: int | None = None
    try:
        directory = getattr(os, "O_DIRECTORY", None)
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if directory is None or nofollow is None:
            raise StorageRootChanged("controlled media identity checks are unavailable")
        descriptor = os.open(
            root.path,
            os.O_RDONLY | directory | getattr(os, "O_CLOEXEC", 0) | nofollow,
        )
        before = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(before.st_mode)
            or (before.st_dev, before.st_ino) != (root.device, root.inode)
            or before.st_mode & _UNSAFE_DIRECTORY_WRITE_BITS
        ):
            raise StorageRootChanged("controlled media root identity changed")
        usage = os.fstatvfs(descriptor)
        free_bytes = usage.f_bavail * usage.f_frsize
        total_bytes = usage.f_blocks * usage.f_frsize
        after = os.fstat(descriptor)
        if (
            (after.st_dev, after.st_ino) != (root.device, root.inode)
            or not stat.S_ISDIR(after.st_mode)
            or after.st_mode & _UNSAFE_DIRECTORY_WRITE_BITS
        ):
            raise StorageRootChanged("controlled media root changed during inspection")
        if (
            type(free_bytes) is not int
            or type(total_bytes) is not int
            or total_bytes < 1
            or free_bytes < 0
            or free_bytes > total_bytes
        ):
            raise StorageRootChanged("controlled media capacity is invalid")
        return free_bytes, total_bytes
    except StorageRootChanged:
        raise
    except OSError as error:
        raise StorageRootChanged("controlled media capacity is unavailable") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


class NarrationDiskGuard:
    """Cache only path-free status; perform fresh I/O for every gate check."""

    def __init__(
        self,
        storage: NarrationStorage,
        *,
        minimum_free_bytes: int = MINIMUM_MEDIA_FREE_BYTES,
    ) -> None:
        if type(storage) is not NarrationStorage:
            raise TypeError("disk guard requires NarrationStorage")
        if type(minimum_free_bytes) is not int or minimum_free_bytes < 1:
            raise ValueError("minimum media free bytes must be a positive integer")
        self._storage = storage
        self._minimum_free_bytes = minimum_free_bytes
        self._lock = Lock()
        self._status = NarrationDiskStatus(
            free_bytes=None,
            total_bytes=None,
            minimum_free_bytes=minimum_free_bytes,
            reason_code=STORAGE_IDENTITY_FAILURE,
        )

    def status(self) -> NarrationDiskStatus:
        with self._lock:
            return self._status

    def refresh(self) -> NarrationDiskStatus:
        try:
            free_bytes, total_bytes = secure_media_disk_usage(self._storage)
            reason_code = (
                None
                if free_bytes >= self._minimum_free_bytes
                else DISK_SPACE_INSUFFICIENT
            )
            current = NarrationDiskStatus(
                free_bytes=free_bytes,
                total_bytes=total_bytes,
                minimum_free_bytes=self._minimum_free_bytes,
                reason_code=reason_code,
            )
        except Exception:
            current = NarrationDiskStatus(
                free_bytes=None,
                total_bytes=None,
                minimum_free_bytes=self._minimum_free_bytes,
                reason_code=STORAGE_IDENTITY_FAILURE,
            )
        with self._lock:
            self._status = current
        return current

    def claim_allowed(self) -> bool:
        """Refresh before a scheduler transaction; false means do not claim."""

        return self.refresh().available

    def require_available(self) -> None:
        """Recheck before synthesis/publication and raise one stable refusal."""

        current = self.refresh()
        if current.reason_code is not None:
            raise NarrationDiskGuardError(current.reason_code)


__all__ = [
    "DISK_SPACE_INSUFFICIENT",
    "MINIMUM_MEDIA_FREE_BYTES",
    "NarrationDiskGuard",
    "NarrationDiskGuardError",
    "NarrationDiskStatus",
    "STORAGE_IDENTITY_FAILURE",
    "secure_media_disk_usage",
]
