"""Fd-relative, fail-closed storage for immutable narration media.

All public methods accept server-created relative identifiers, never client paths.
The model root is read-only; only the media root supports staging/publication.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable, Iterator
from uuid import UUID, uuid4


_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_EXTENSION = re.compile(r"^[a-z0-9]{1,10}$")
_ALLOWED_MEDIA_EXTENSIONS = frozenset({"aac", "flac", "m4a", "mp3", "ogg", "opus", "wav"})
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
_READ_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NONBLOCK", 0)
)
_WRITE_BITS = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
_UNSAFE_DIRECTORY_WRITE_BITS = stat.S_IWGRP | stat.S_IWOTH


class StorageError(RuntimeError):
    pass


class UnsafeStoragePath(StorageError):
    pass


class StorageRootChanged(StorageError):
    pass


class ModelRootReadOnly(StorageError):
    pass


class PublicationValidationError(StorageError):
    pass


class TargetCollision(StorageError):
    pass


class PublicationDurabilityError(StorageError):
    """Publication did not reach the directory durability boundary.

    ``staging_relative_path`` names the validated, fsynced recovery copy.  It is
    deliberately retained; automatic cleanup must not remove it while the
    content-addressed destination is absent.
    """

    def __init__(self, message: str, *, staging_relative_path: str, target_relative_path: str):
        super().__init__(message)
        self.staging_relative_path = staging_relative_path
        self.target_relative_path = target_relative_path


@dataclass(frozen=True, slots=True)
class RootIdentity:
    path: Path
    device: int
    inode: int


@dataclass(frozen=True, slots=True)
class PublishedFile:
    asset_id: UUID
    relative_path: str
    actual_sha256: str
    byte_size: int
    strong_etag: str
    device: int
    inode: int


@dataclass(frozen=True, slots=True)
class StoredFileIdentity:
    relative_path: str
    device: int
    inode: int
    byte_size: int


def _open_root(identity: RootIdentity) -> int:
    try:
        fd = os.open(identity.path, _DIRECTORY_FLAGS)
    except OSError as error:
        raise StorageRootChanged("controlled storage root is unavailable or a symlink") from error
    info = os.fstat(fd)
    if (info.st_dev, info.st_ino) != (identity.device, identity.inode):
        os.close(fd)
        raise StorageRootChanged("controlled storage root identity changed")
    if info.st_mode & _UNSAFE_DIRECTORY_WRITE_BITS:
        os.close(fd)
        raise StorageRootChanged("controlled storage root is group/world writable")
    return fd


def _root_identity(path: Path) -> RootIdentity:
    if not path.is_absolute():
        raise UnsafeStoragePath("storage root must be absolute")
    try:
        fd = os.open(path, _DIRECTORY_FLAGS)
    except OSError as error:
        raise UnsafeStoragePath("storage root must be an existing non-symlink directory") from error
    try:
        info = os.fstat(fd)
        if info.st_mode & _UNSAFE_DIRECTORY_WRITE_BITS:
            raise UnsafeStoragePath("storage root must not be group/world writable")
        return RootIdentity(path=path, device=info.st_dev, inode=info.st_ino)
    finally:
        os.close(fd)


def validate_relative_path(value: str) -> tuple[str, ...]:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 1024
        or "//" in value
        or "\\" in value
        or value.endswith("/")
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise UnsafeStoragePath("invalid relative storage path")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise UnsafeStoragePath("control characters are forbidden in storage paths")
    path = PurePosixPath(value)
    if path.is_absolute():
        raise UnsafeStoragePath("absolute storage paths are forbidden")
    parts = path.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise UnsafeStoragePath("dot/path traversal is forbidden")
    if any(not _COMPONENT.fullmatch(part) for part in parts):
        raise UnsafeStoragePath("storage path component is outside the safe alphabet")
    return parts


def _open_directory_chain(
    root_fd: int,
    parts: tuple[str, ...],
    *,
    create: bool,
    fsync_fn: Callable[[int], None] = os.fsync,
) -> int:
    current = os.dup(root_fd)
    try:
        for part in parts:
            created = False
            if create:
                try:
                    os.mkdir(part, mode=0o750, dir_fd=current)
                    created = True
                except FileExistsError:
                    pass
            if created:
                # Persist the directory entry before anything inside the new
                # directory can be treated as a durable recovery copy.
                fsync_fn(current)
            try:
                child = os.open(part, _DIRECTORY_FLAGS, dir_fd=current)
            except FileNotFoundError:
                raise
            except OSError as error:
                raise UnsafeStoragePath("storage directory is missing, replaced, or a symlink") from error
            child_info = os.fstat(child)
            if child_info.st_mode & _UNSAFE_DIRECTORY_WRITE_BITS:
                os.close(child)
                raise UnsafeStoragePath("storage directory is group/world writable")
            os.close(current)
            current = child
        return current
    except BaseException:
        os.close(current)
        raise


class NarrationStorage:
    """Two fixed roots with inode identity and fd-relative operations."""

    def __init__(self, *, models_root: Path, media_root: Path) -> None:
        self.models = _root_identity(models_root)
        self.media = _root_identity(media_root)
        if (self.models.device, self.models.inode) == (self.media.device, self.media.inode):
            raise UnsafeStoragePath("model and media roots must not alias the same inode")
        models_real = models_root.resolve(strict=True)
        media_real = media_root.resolve(strict=True)
        if models_real == media_real or models_real in media_real.parents or media_real in models_real.parents:
            raise UnsafeStoragePath("model and media roots must be disjoint")

    def open_model_readonly(self, relative_path: str) -> int:
        return self._open_read(self.models, relative_path)

    def reject_model_write(self, _relative_path: str) -> None:
        raise ModelRootReadOnly("moss-models is owned by the model lifecycle and read-only here")

    def _open_read(
        self,
        root: RootIdentity,
        relative_path: str,
        *,
        require_immutable: bool = False,
    ) -> int:
        parts = validate_relative_path(relative_path)
        root_fd = _open_root(root)
        try:
            parent_fd = _open_directory_chain(root_fd, parts[:-1], create=False)
            try:
                try:
                    fd = os.open(parts[-1], _READ_FLAGS, dir_fd=parent_fd)
                except OSError as error:
                    raise UnsafeStoragePath("media file is missing, replaced, or a symlink") from error
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode):
                    os.close(fd)
                    raise UnsafeStoragePath("storage target is not a regular file")
                if require_immutable and info.st_nlink != 1:
                    os.close(fd)
                    raise UnsafeStoragePath("immutable media must have exactly one filesystem link")
                if require_immutable and info.st_mode & _WRITE_BITS:
                    os.close(fd)
                    raise UnsafeStoragePath("published media unexpectedly has writable mode bits")
                return fd
            finally:
                os.close(parent_fd)
        finally:
            os.close(root_fd)

    def publish_media(
        self,
        chunks: Iterable[bytes],
        *,
        asset_id: UUID,
        expected_sha256: str,
        expected_size: int,
        extension: str,
        max_bytes: int,
        write_fn: Callable[[int, bytes | memoryview], int] = os.write,
        fsync_fn: Callable[[int], None] = os.fsync,
    ) -> PublishedFile:
        if type(asset_id) is not UUID:
            raise PublicationValidationError("asset_id must be an exact UUID")
        if not _SHA256.fullmatch(expected_sha256):
            raise PublicationValidationError("expected_sha256 must be lowercase SHA-256")
        if expected_size < 0 or max_bytes < 0 or expected_size > max_bytes:
            raise PublicationValidationError("declared media size exceeds the bounded limit")
        if not _EXTENSION.fullmatch(extension) or extension not in _ALLOWED_MEDIA_EXTENSIONS:
            raise PublicationValidationError("unsafe media extension")
        asset_key = asset_id.hex
        relative_path = (
            f"assets/{asset_key[:2]}/{asset_key}/{expected_sha256}.{extension}"
        )
        destination_parts = validate_relative_path(relative_path)
        staging_name = (
            f"{asset_key}.{expected_sha256}.{extension}.{uuid4().hex}.part"
        )
        staging_relative_path = f".staging/{staging_name}"
        root_fd = _open_root(self.media)
        staging_fd = destination_fd = destination_file_fd = file_fd = None
        staging_exists = False
        staging_durable = False
        preserve_staging = False
        try:
            staging_fd = _open_directory_chain(
                root_fd, (".staging",), create=True, fsync_fn=fsync_fn
            )
            file_fd = os.open(
                staging_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o640,
                dir_fd=staging_fd,
            )
            staging_exists = True
            digest = hashlib.sha256()
            total = 0
            for raw_chunk in chunks:
                if not isinstance(raw_chunk, bytes):
                    raise PublicationValidationError("media stream chunks must be bytes")
                if not raw_chunk:
                    continue
                total += len(raw_chunk)
                if total > max_bytes or total > expected_size:
                    raise PublicationValidationError("media stream exceeded declared/bounded size")
                digest.update(raw_chunk)
                view = memoryview(raw_chunk)
                while view:
                    # Pass the remaining view directly.  Converting it to bytes
                    # on every short write makes adversarial one-byte writes
                    # quadratic in both allocation and copy volume.
                    written = write_fn(file_fd, view)
                    if written <= 0 or written > len(view):
                        raise PublicationValidationError("short media write made no progress")
                    view = view[written:]
            if total != expected_size or digest.hexdigest() != expected_sha256:
                raise PublicationValidationError("actual media bytes do not match size/hash")
            fsync_fn(file_fd)
            os.fchmod(file_fd, 0o440)
            fsync_fn(file_fd)
            os.close(file_fd)
            file_fd = None
            try:
                fsync_fn(staging_fd)
            except OSError as error:
                # The file itself has been hashed, made read-only, and fsynced.
                # Even when its directory entry cannot yet be proven durable,
                # deleting it would discard the only recoverable copy.
                preserve_staging = True
                raise PublicationDurabilityError(
                    "staging directory fsync failed; validated staging was retained",
                    staging_relative_path=staging_relative_path,
                    target_relative_path=relative_path,
                ) from error
            staging_durable = True
            staging_info = os.stat(
                staging_name, dir_fd=staging_fd, follow_symlinks=False
            )
            destination_fd = _open_directory_chain(
                root_fd, destination_parts[:-1], create=True, fsync_fn=fsync_fn
            )
            try:
                # linkat is an atomic no-replace publication; unlinking staging
                # afterward is equivalent to rename for immutable content.
                os.link(
                    staging_name,
                    destination_parts[-1],
                    src_dir_fd=staging_fd,
                    dst_dir_fd=destination_fd,
                    follow_symlinks=False,
                )
            except FileExistsError as error:
                # A collision is redundant only when the existing immutable
                # target reproduces the complete size/hash evidence.  Otherwise
                # the staging inode may be the only valid durable copy.
                try:
                    existing_fd = os.open(
                        destination_parts[-1], _READ_FLAGS, dir_fd=destination_fd
                    )
                    try:
                        existing_info = os.fstat(existing_fd)
                        existing_digest = hashlib.sha256()
                        existing_offset = 0
                        existing_valid = (
                            stat.S_ISREG(existing_info.st_mode)
                            and not existing_info.st_mode & _WRITE_BITS
                            and existing_info.st_nlink == 1
                            and existing_info.st_size == total
                        )
                        while existing_valid and existing_offset < total:
                            existing_chunk = os.pread(
                                existing_fd,
                                min(64 * 1024, total - existing_offset),
                                existing_offset,
                            )
                            if not existing_chunk:
                                existing_valid = False
                                break
                            existing_digest.update(existing_chunk)
                            existing_offset += len(existing_chunk)
                        existing_final = os.fstat(existing_fd)
                        existing_entry = os.stat(
                            destination_parts[-1],
                            dir_fd=destination_fd,
                            follow_symlinks=False,
                        )
                        existing_valid = existing_valid and (
                            existing_digest.hexdigest() == expected_sha256
                            and (
                                existing_final.st_dev,
                                existing_final.st_ino,
                                existing_final.st_size,
                                existing_final.st_mode,
                                existing_final.st_nlink,
                            )
                            == (
                                existing_info.st_dev,
                                existing_info.st_ino,
                                existing_info.st_size,
                                existing_info.st_mode,
                                existing_info.st_nlink,
                            )
                            and (
                                existing_entry.st_dev,
                                existing_entry.st_ino,
                                existing_entry.st_size,
                                existing_entry.st_mode,
                                existing_entry.st_nlink,
                            )
                            == (
                                existing_final.st_dev,
                                existing_final.st_ino,
                                existing_final.st_size,
                                existing_final.st_mode,
                                existing_final.st_nlink,
                            )
                        )
                    finally:
                        os.close(existing_fd)
                except OSError:
                    existing_valid = False
                if existing_valid:
                    try:
                        fsync_fn(destination_fd)
                    except OSError as durability_error:
                        preserve_staging = True
                        raise PublicationDurabilityError(
                            "colliding target directory fsync failed; staging was retained",
                            staging_relative_path=staging_relative_path,
                            target_relative_path=relative_path,
                        ) from durability_error
                    durable_entry = os.stat(
                        destination_parts[-1],
                        dir_fd=destination_fd,
                        follow_symlinks=False,
                    )
                    if (
                        durable_entry.st_dev,
                        durable_entry.st_ino,
                        durable_entry.st_size,
                        durable_entry.st_mode,
                        durable_entry.st_nlink,
                    ) != (
                        existing_entry.st_dev,
                        existing_entry.st_ino,
                        existing_entry.st_size,
                        existing_entry.st_mode,
                        existing_entry.st_nlink,
                    ):
                        preserve_staging = True
                        raise PublicationDurabilityError(
                            "colliding target changed while making it durable",
                            staging_relative_path=staging_relative_path,
                            target_relative_path=relative_path,
                        )
                    staging_durable = False
                    raise TargetCollision(
                        "verified immutable media target already exists"
                    ) from error
                preserve_staging = True
                raise PublicationDurabilityError(
                    "colliding target is unsafe; validated staging was retained",
                    staging_relative_path=staging_relative_path,
                    target_relative_path=relative_path,
                ) from error
            destination_file_fd = os.open(
                destination_parts[-1], _READ_FLAGS, dir_fd=destination_fd
            )
            linked_info = os.fstat(destination_file_fd)
            if (
                not stat.S_ISREG(linked_info.st_mode)
                or linked_info.st_mode & _WRITE_BITS
                or linked_info.st_nlink != 2
                or (linked_info.st_dev, linked_info.st_ino, linked_info.st_size)
                != (staging_info.st_dev, staging_info.st_ino, total)
            ):
                preserve_staging = True
                raise PublicationDurabilityError(
                    "published target no longer matches the durable staging inode",
                    staging_relative_path=staging_relative_path,
                    target_relative_path=relative_path,
                )
            try:
                fsync_fn(destination_fd)
            except OSError as error:
                preserve_staging = True
                raise PublicationDurabilityError(
                    "media target directory fsync failed; validated staging was retained",
                    staging_relative_path=staging_relative_path,
                    target_relative_path=relative_path,
                ) from error
            current_destination = os.stat(
                destination_parts[-1], dir_fd=destination_fd, follow_symlinks=False
            )
            current_staging = os.stat(
                staging_name, dir_fd=staging_fd, follow_symlinks=False
            )
            expected_linked_identity = (
                staging_info.st_dev,
                staging_info.st_ino,
                total,
                2,
            )
            if (
                current_destination.st_dev,
                current_destination.st_ino,
                current_destination.st_size,
                current_destination.st_nlink,
            ) != expected_linked_identity or (
                current_staging.st_dev,
                current_staging.st_ino,
                current_staging.st_size,
                current_staging.st_nlink,
            ) != expected_linked_identity:
                preserve_staging = True
                raise PublicationDurabilityError(
                    "publication links changed before staging cleanup",
                    staging_relative_path=staging_relative_path,
                    target_relative_path=relative_path,
                )
            os.unlink(staging_name, dir_fd=staging_fd)
            staging_exists = False
            fsync_fn(staging_fd)
            os.close(destination_file_fd)
            destination_file_fd = None
            final_fd = os.open(
                destination_parts[-1], _READ_FLAGS, dir_fd=destination_fd
            )
            try:
                destination_info = os.fstat(final_fd)
                if (
                    not stat.S_ISREG(destination_info.st_mode)
                    or destination_info.st_mode & _WRITE_BITS
                    or destination_info.st_nlink != 1
                    or (
                        destination_info.st_dev,
                        destination_info.st_ino,
                        destination_info.st_size,
                    )
                    != (staging_info.st_dev, staging_info.st_ino, total)
                ):
                    raise StorageError("published target changed after staging cleanup")
            finally:
                os.close(final_fd)
            return PublishedFile(
                asset_id=asset_id,
                relative_path=relative_path,
                actual_sha256=expected_sha256,
                byte_size=total,
                strong_etag=f'"{expected_sha256}"',
                device=destination_info.st_dev,
                inode=destination_info.st_ino,
            )
        except PublicationDurabilityError:
            preserve_staging = True
            raise
        except BaseException as error:
            if staging_durable and staging_exists:
                preserve_staging = True
                raise PublicationDurabilityError(
                    "media publication failed after staging became durable; staging was retained",
                    staging_relative_path=staging_relative_path,
                    target_relative_path=relative_path,
                ) from error
            raise
        finally:
            if file_fd is not None:
                os.close(file_fd)
            if staging_exists and staging_fd is not None and not preserve_staging:
                try:
                    os.unlink(staging_name, dir_fd=staging_fd)
                    fsync_fn(staging_fd)
                except FileNotFoundError:
                    pass
            if destination_fd is not None:
                os.close(destination_fd)
            if destination_file_fd is not None:
                os.close(destination_file_fd)
            if staging_fd is not None:
                os.close(staging_fd)
            os.close(root_fd)

    def stream_media(
        self,
        relative_path: str,
        *,
        start: int = 0,
        end_exclusive: int | None = None,
        chunk_size: int = 64 * 1024,
        expected_device: int | None = None,
        expected_inode: int | None = None,
        expected_size: int | None = None,
    ) -> Iterator[bytes]:
        if start < 0 or chunk_size < 1 or chunk_size > 1024 * 1024:
            raise StorageError("invalid bounded stream parameters")
        fd = self._open_read(self.media, relative_path, require_immutable=True)
        try:
            info = os.fstat(fd)
            size = info.st_size
            expected_values = (expected_device, expected_inode, expected_size)
            if any(value is not None for value in expected_values):
                if any(value is None for value in expected_values):
                    raise StorageError("verified stream requires complete device/inode/size identity")
                if (info.st_dev, info.st_ino, info.st_size) != expected_values:
                    raise StorageError("media changed between HTTP planning and streaming")
            end = size if end_exclusive is None else end_exclusive
            if end < start or end > size:
                raise StorageError("stream range is outside media bytes")
            offset = start
            while offset < end:
                chunk = os.pread(fd, min(chunk_size, end - offset), offset)
                if not chunk:
                    raise StorageError("media file shortened during bounded stream")
                offset += len(chunk)
                yield chunk
        finally:
            os.close(fd)

    def media_stat(self, relative_path: str) -> os.stat_result:
        fd = self._open_read(self.media, relative_path, require_immutable=True)
        try:
            return os.fstat(fd)
        finally:
            os.close(fd)

    def verify_existing_media(
        self,
        relative_path: str,
        *,
        expected_sha256: str,
        expected_size: int,
        max_bytes: int,
        chunk_size: int = 64 * 1024,
    ) -> PublishedFile:
        """Re-adopt immutable bytes after publish succeeded but the DB tx failed."""

        if not _SHA256.fullmatch(expected_sha256):
            raise PublicationValidationError("expected_sha256 must be lowercase SHA-256")
        if expected_size < 0 or expected_size > max_bytes or not 1 <= chunk_size <= 1024 * 1024:
            raise PublicationValidationError("invalid bounded verification parameters")
        identity = self.verify_media_identity(
            relative_path,
            expected_sha256=expected_sha256,
            expected_size=expected_size,
            max_bytes=max_bytes,
            chunk_size=chunk_size,
        )
        parts = validate_relative_path(relative_path)
        if (
            len(parts) != 4
            or parts[0] != "assets"
            or len(parts[1]) != 2
            or len(parts[2]) != 32
            or parts[1] != parts[2][:2]
        ):
            raise PublicationValidationError("existing media path lacks its logical asset ID")
        try:
            asset_id = UUID(hex=parts[2])
        except ValueError as error:
            raise PublicationValidationError("existing media path has an invalid asset ID") from error
        expected_name = f"{expected_sha256}{PurePosixPath(relative_path).suffix}"
        if parts[3] != expected_name:
            raise PublicationValidationError("existing media path and SHA-256 disagree")
        return PublishedFile(
            asset_id=asset_id,
            relative_path=relative_path,
            actual_sha256=expected_sha256,
            byte_size=identity.byte_size,
            strong_etag=f'"{expected_sha256}"',
            device=identity.device,
            inode=identity.inode,
        )

    def verify_media_identity(
        self,
        relative_path: str,
        *,
        expected_sha256: str,
        expected_size: int,
        max_bytes: int,
        chunk_size: int = 64 * 1024,
    ) -> StoredFileIdentity:
        """Hash and freeze one immutable media inode through a single open fd."""

        if not _SHA256.fullmatch(expected_sha256):
            raise PublicationValidationError("expected_sha256 must be lowercase SHA-256")
        if expected_size < 0 or expected_size > max_bytes or not 1 <= chunk_size <= 1024 * 1024:
            raise PublicationValidationError("invalid bounded verification parameters")
        fd = self._open_read(self.media, relative_path, require_immutable=True)
        try:
            info = os.fstat(fd)
            if info.st_size != expected_size:
                raise PublicationValidationError("existing media size differs from DB evidence")
            digest = hashlib.sha256()
            offset = 0
            while offset < expected_size:
                chunk = os.pread(fd, min(chunk_size, expected_size - offset), offset)
                if not chunk:
                    raise PublicationValidationError("existing media shortened during verification")
                digest.update(chunk)
                offset += len(chunk)
            if digest.hexdigest() != expected_sha256:
                raise PublicationValidationError("existing media does not match SHA-256")
            final_info = os.fstat(fd)
            if (final_info.st_dev, final_info.st_ino, final_info.st_size) != (
                info.st_dev,
                info.st_ino,
                info.st_size,
            ):
                raise PublicationValidationError("existing media changed during verification")
            return StoredFileIdentity(
                relative_path=relative_path,
                device=info.st_dev,
                inode=info.st_ino,
                byte_size=info.st_size,
            )
        finally:
            os.close(fd)

    def capture_media_identity(
        self,
        relative_path: str,
        *,
        missing_ok: bool = False,
    ) -> StoredFileIdentity | None:
        try:
            fd = self._open_read(self.media, relative_path, require_immutable=True)
        except (FileNotFoundError, UnsafeStoragePath):
            if missing_ok and not self.media_path_exists(relative_path):
                return None
            raise
        try:
            info = os.fstat(fd)
            return StoredFileIdentity(
                relative_path=relative_path,
                device=info.st_dev,
                inode=info.st_ino,
                byte_size=info.st_size,
            )
        finally:
            os.close(fd)

    def _media_entry_stat(self, relative_path: str) -> os.stat_result | None:
        parts = validate_relative_path(relative_path)
        root_fd = _open_root(self.media)
        try:
            try:
                parent_fd = _open_directory_chain(root_fd, parts[:-1], create=False)
            except FileNotFoundError:
                return None
            try:
                try:
                    return os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
                except FileNotFoundError:
                    return None
            finally:
                os.close(parent_fd)
        finally:
            os.close(root_fd)

    def media_path_exists(self, relative_path: str) -> bool:
        return self._media_entry_stat(relative_path) is not None

    def ensure_media_absent(self, relative_path: str) -> None:
        if self.media_path_exists(relative_path):
            raise UnsafeStoragePath("media target still exists at GC finalization")

    def delete_media_verified(
        self,
        relative_path: str,
        *,
        expected_sha256: str,
        expected_size: int,
        expected_device: int | None,
        expected_inode: int | None,
        expected_present: bool,
        missing_ok: bool = False,
        chunk_size: int = 64 * 1024,
    ) -> bool:
        """Delete only the exact immutable file frozen by the DB deletion plan."""

        if not _SHA256.fullmatch(expected_sha256) or expected_size < 0:
            raise PublicationValidationError("GC identity requires SHA-256 and nonnegative size")
        if not 1 <= chunk_size <= 1024 * 1024:
            raise PublicationValidationError("invalid GC verification chunk size")
        if expected_present != (expected_device is not None and expected_inode is not None):
            raise PublicationValidationError("GC presence and inode/device identity disagree")
        parts = validate_relative_path(relative_path)
        root_fd = _open_root(self.media)
        try:
            try:
                parent_fd = _open_directory_chain(root_fd, parts[:-1], create=False)
            except FileNotFoundError:
                if missing_ok or not expected_present:
                    return False
                raise
            try:
                try:
                    fd = os.open(parts[-1], _READ_FLAGS, dir_fd=parent_fd)
                except FileNotFoundError:
                    if missing_ok or not expected_present:
                        return False
                    raise
                try:
                    info = os.fstat(fd)
                    if not expected_present:
                        raise UnsafeStoragePath("a file appeared after GC froze an absent target")
                    if not stat.S_ISREG(info.st_mode):
                        raise UnsafeStoragePath("refusing to delete a non-regular target")
                    if info.st_nlink != 1:
                        raise UnsafeStoragePath("refusing to delete a hard-linked media target")
                    if info.st_mode & _WRITE_BITS:
                        raise UnsafeStoragePath("refusing to delete mutable media bytes")
                    if (info.st_dev, info.st_ino, info.st_size) != (
                        expected_device,
                        expected_inode,
                        expected_size,
                    ):
                        raise UnsafeStoragePath("GC target no longer matches frozen physical identity")
                    digest = hashlib.sha256()
                    offset = 0
                    while offset < expected_size:
                        chunk = os.pread(fd, min(chunk_size, expected_size - offset), offset)
                        if not chunk:
                            raise UnsafeStoragePath("GC target shortened during verification")
                        digest.update(chunk)
                        offset += len(chunk)
                    if digest.hexdigest() != expected_sha256:
                        raise UnsafeStoragePath("GC target bytes differ from frozen SHA-256")
                    current = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
                    if (current.st_dev, current.st_ino, current.st_size, current.st_nlink) != (
                        info.st_dev,
                        info.st_ino,
                        info.st_size,
                        1,
                    ):
                        raise UnsafeStoragePath("GC directory entry changed during verification")
                    os.unlink(parts[-1], dir_fd=parent_fd)
                    os.fsync(parent_fd)
                    return True
                finally:
                    os.close(fd)
            finally:
                os.close(parent_fd)
        finally:
            os.close(root_fd)

    def cleanup_staging(
        self,
        *,
        older_than_epoch: float,
        fsync_fn: Callable[[int], None] = os.fsync,
    ) -> list[str]:
        """Remove only stale regular `.part` files in the private staging dir."""

        root_fd = _open_root(self.media)
        removed: list[str] = []
        try:
            staging_fd = _open_directory_chain(
                root_fd, (".staging",), create=True, fsync_fn=fsync_fn
            )
            try:
                # Names are read from the fd-backed directory path on supported POSIX.
                for name in os.listdir(staging_fd):
                    legacy = re.fullmatch(r"[a-f0-9]{32}\.part", name)
                    legacy_recoverable = re.fullmatch(
                        r"([a-f0-9]{64})\.([a-z0-9]{1,10})\.[a-f0-9]{32}\.part", name
                    )
                    recoverable = re.fullmatch(
                        r"([a-f0-9]{32})\.([a-f0-9]{64})\.([a-z0-9]{1,10})\."
                        r"[a-f0-9]{32}\.part",
                        name,
                    )
                    if legacy is None and legacy_recoverable is None and recoverable is None:
                        continue
                    try:
                        candidate_fd = os.open(name, _READ_FLAGS, dir_fd=staging_fd)
                    except OSError:
                        continue
                    try:
                        info = os.fstat(candidate_fd)
                        if (
                            not stat.S_ISREG(info.st_mode)
                            or info.st_mtime > older_than_epoch
                        ):
                            continue
                        # A read-only verified staging file may be the only
                        # durable copy after destination-directory fsync failed.
                        # Preserve it unless its exact target twin is made
                        # durable before this recovery link is removed.
                        if (recoverable is not None or legacy_recoverable is not None) and not (
                            info.st_mode & _WRITE_BITS
                        ):
                            extension = (
                                recoverable.group(3)
                                if recoverable is not None
                                else legacy_recoverable.group(2)
                            )
                            if extension not in _ALLOWED_MEDIA_EXTENSIONS:
                                continue
                            if recoverable is not None:
                                asset_key = recoverable.group(1)
                                digest = recoverable.group(2)
                                target = (
                                    f"assets/{asset_key[:2]}/{asset_key}/"
                                    f"{digest}.{extension}"
                                )
                            else:
                                digest = legacy_recoverable.group(1)
                                target = (
                                    f"assets/{digest[:2]}/{digest}.{extension}"
                                )
                            target_parts = validate_relative_path(target)
                            try:
                                target_parent_fd = _open_directory_chain(
                                    root_fd, target_parts[:-1], create=False
                                )
                            except FileNotFoundError:
                                continue
                            try:
                                try:
                                    target_info = os.stat(
                                        target_parts[-1],
                                        dir_fd=target_parent_fd,
                                        follow_symlinks=False,
                                    )
                                except FileNotFoundError:
                                    continue
                                if (
                                    not stat.S_ISREG(target_info.st_mode)
                                    or target_info.st_mode & _WRITE_BITS
                                    or info.st_nlink != 2
                                    or target_info.st_nlink != 2
                                ):
                                    continue
                                # The publication protocol uses linkat; only the
                                # same inode proves the destination is the durable
                                # twin of this recovery copy.  A replacement path,
                                # even with the same name, must not consume it.
                                if (
                                    target_info.st_dev,
                                    target_info.st_ino,
                                    target_info.st_size,
                                ) != (info.st_dev, info.st_ino, info.st_size):
                                    continue
                                # A previous publication could not prove this
                                # directory durable.  Re-establish that proof
                                # before consuming the known-durable staging link.
                                fsync_fn(target_parent_fd)
                                try:
                                    durable_target = os.stat(
                                        target_parts[-1],
                                        dir_fd=target_parent_fd,
                                        follow_symlinks=False,
                                    )
                                except FileNotFoundError:
                                    continue
                                if (
                                    durable_target.st_dev,
                                    durable_target.st_ino,
                                    durable_target.st_size,
                                    durable_target.st_mode,
                                    durable_target.st_nlink,
                                ) != (
                                    target_info.st_dev,
                                    target_info.st_ino,
                                    target_info.st_size,
                                    target_info.st_mode,
                                    target_info.st_nlink,
                                ):
                                    continue
                            finally:
                                os.close(target_parent_fd)
                        current = os.stat(
                            name, dir_fd=staging_fd, follow_symlinks=False
                        )
                        if (
                            current.st_dev,
                            current.st_ino,
                            current.st_size,
                            current.st_mode,
                            current.st_nlink,
                        ) != (
                            info.st_dev,
                            info.st_ino,
                            info.st_size,
                            info.st_mode,
                            info.st_nlink,
                        ):
                            continue
                        os.unlink(name, dir_fd=staging_fd)
                        removed.append(name)
                    finally:
                        os.close(candidate_fd)
                if removed:
                    fsync_fn(staging_fd)
            finally:
                os.close(staging_fd)
        finally:
            os.close(root_fd)
        return removed


__all__ = [
    "ModelRootReadOnly",
    "NarrationStorage",
    "PublicationDurabilityError",
    "PublicationValidationError",
    "PublishedFile",
    "RootIdentity",
    "StoredFileIdentity",
    "StorageError",
    "StorageRootChanged",
    "TargetCollision",
    "UnsafeStoragePath",
    "validate_relative_path",
]
