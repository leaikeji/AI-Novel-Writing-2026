#!/usr/bin/env python3
"""Initialize the two private TTS volumes without exposing secret bytes."""

from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import stat


SIDECAR_UID = 65532
SIDECAR_GID = 65532
MODEL_ROOT = Path("/opt/moss-assets")
SECRET_ROOT = Path("/run/moss-tts-secrets")
TOKEN_NAME = "moss_tts_sidecar_token"
STAGING_PREFIX = ".moss-token.staging."
MIN_TOKEN_CHARS = 32
MAX_TOKEN_CHARS = 128


class InitError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _open_directory(path: Path) -> int:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise InitError("NOFOLLOW_UNAVAILABLE")
    descriptor = os.open(path, flags | nofollow)
    details = os.fstat(descriptor)
    if not stat.S_ISDIR(details.st_mode):
        os.close(descriptor)
        raise InitError("VOLUME_ROOT_INVALID")
    return descriptor


def _prepare_volume_root(path: Path) -> int:
    descriptor = _open_directory(path)
    try:
        os.fchown(descriptor, SIDECAR_UID, SIDECAR_GID)
        os.fchmod(descriptor, 0o750)
        os.fsync(descriptor)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _read_exact_token(directory_fd: int) -> bytes | None:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise InitError("NOFOLLOW_UNAVAILABLE")
    try:
        descriptor = os.open(
            TOKEN_NAME,
            os.O_RDONLY | os.O_CLOEXEC | nofollow,
            dir_fd=directory_fd,
        )
    except FileNotFoundError:
        return None
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != SIDECAR_UID
            or before.st_gid != SIDECAR_GID
            or stat.S_IMODE(before.st_mode) != 0o400
            or not (MIN_TOKEN_CHARS <= before.st_size <= MAX_TOKEN_CHARS)
        ):
            raise InitError("TOKEN_FILE_INVALID")
        payload = os.read(descriptor, MAX_TOKEN_CHARS + 1)
        after = os.fstat(descriptor)
        if (
            len(payload) != before.st_size
            or (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
            != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            )
            or any(not 0x21 <= byte <= 0x7E for byte in payload)
        ):
            raise InitError("TOKEN_VALUE_INVALID")
        return payload
    finally:
        os.close(descriptor)


def _cleanup_owned_staging(directory_fd: int) -> None:
    for name in os.listdir(directory_fd):
        if not name.startswith(STAGING_PREFIX):
            continue
        details = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_nlink != 1
            or details.st_uid not in {0, SIDECAR_UID}
        ):
            raise InitError("TOKEN_STAGING_INVALID")
        os.unlink(name, dir_fd=directory_fd)
    os.fsync(directory_fd)


def _create_token(directory_fd: int) -> None:
    payload = secrets.token_urlsafe(48).encode("ascii")
    if not (MIN_TOKEN_CHARS <= len(payload) <= MAX_TOKEN_CHARS) or any(
        not 0x21 <= byte <= 0x7E for byte in payload
    ):
        raise InitError("TOKEN_GENERATION_INVALID")
    staging_name = f"{STAGING_PREFIX}{secrets.token_hex(16)}"
    descriptor: int | None = None
    linked = False
    try:
        descriptor = os.open(
            staging_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
            0o600,
            dir_fd=directory_fd,
        )
        os.fchown(descriptor, SIDECAR_UID, SIDECAR_GID)
        os.fchmod(descriptor, 0o400)
        written = 0
        while written < len(payload):
            written += os.write(descriptor, payload[written:])
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.link(
            staging_name,
            TOKEN_NAME,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
            follow_symlinks=False,
        )
        linked = True
        os.unlink(staging_name, dir_fd=directory_fd)
        os.fsync(directory_fd)
    except FileExistsError as error:
        raise InitError("TOKEN_CREATE_RACE") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if not linked:
            try:
                os.unlink(staging_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass


def main() -> int:
    model_fd: int | None = None
    secret_fd: int | None = None
    try:
        model_fd = _prepare_volume_root(MODEL_ROOT)
        secret_fd = _prepare_volume_root(SECRET_ROOT)
        _cleanup_owned_staging(secret_fd)
        if _read_exact_token(secret_fd) is None:
            _create_token(secret_fd)
        _read_exact_token(secret_fd)
    except (InitError, OSError) as error:
        code = error.code if isinstance(error, InitError) else "VOLUME_INIT_IO_FAILURE"
        print(json.dumps({"status": "failed", "error_code": code}, sort_keys=True))
        return 78
    finally:
        if secret_fd is not None:
            os.close(secret_fd)
        if model_fd is not None:
            os.close(model_fd)
    print(
        json.dumps(
            {
                "status": "passed",
                "model_root_owner": SIDECAR_UID,
                "token_owner": SIDECAR_UID,
                "token_mode": "0400",
                "secret_value_recorded": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
