#!/usr/bin/env python3
"""Explicit, fail-closed lifecycle operations for the narration HMAC keyring.

This command never discovers configuration from ``.env``, never connects to a
database, and never repairs a missing keyring.  Fresh initialization requires
two operator attestations; rotation requires a valid existing keyring.  Output
is deliberately limited to a stable code and, on success, the new key id.
"""

from __future__ import annotations

import argparse
import base64
from collections.abc import Callable
import errno
import fcntl
import json
import os
from pathlib import Path
import secrets
import stat
import sys
from typing import Final


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.narration.digest_keyring import (  # noqa: E402
    DIGEST_KEYRING_SCHEMA_VERSION,
    MAX_KEY_COUNT,
    DigestKeyring,
    DigestKeyringError,
    HmacDigestKey,
    load_digest_keyring,
)


_SECRET_BYTES: Final = 32
_TEMP_CREATE_ATTEMPTS: Final = 8


class DigestKeyringOperationError(RuntimeError):
    """Secret- and path-free lifecycle failure with a stable code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class _SafeArgumentParser(argparse.ArgumentParser):
    """Prevent argparse from reflecting operator-supplied paths in errors."""

    def error(self, message: str) -> None:  # pragma: no cover - exercised via main
        del message
        raise DigestKeyringOperationError(
            "DIGEST_KEYRING_ARGUMENTS_INVALID",
            "narration digest keyring command arguments are invalid",
        )


def _operation_error(code: str, message: str) -> DigestKeyringOperationError:
    return DigestKeyringOperationError(code, message)


def _validate_key_id(key_id: str) -> None:
    try:
        HmacDigestKey(key_id=key_id, secret=b"0" * _SECRET_BYTES)
    except (TypeError, ValueError) as error:
        raise _operation_error(
            "DIGEST_KEY_ID_INVALID",
            "new narration digest key identity is invalid",
        ) from None


def _validate_secret(secret: bytes) -> bytes:
    if type(secret) is not bytes or len(secret) != _SECRET_BYTES:
        raise _operation_error(
            "DIGEST_KEY_GENERATION_FAILED",
            "new narration digest key material is invalid",
        )
    return secret


def _generate_secret(secret_factory: Callable[[int], bytes] | None) -> bytes:
    factory = secrets.token_bytes if secret_factory is None else secret_factory
    try:
        return _validate_secret(factory(_SECRET_BYTES))
    except DigestKeyringOperationError:
        raise
    except Exception as error:
        raise _operation_error(
            "DIGEST_KEY_GENERATION_FAILED",
            "new narration digest key generation failed",
        ) from None


def _validate_target_path(path: Path) -> None:
    if not isinstance(path, Path) or not path.is_absolute() or path.name in {"", ".", ".."}:
        raise _operation_error(
            "DIGEST_KEYRING_PATH_INVALID",
            "narration digest keyring path is invalid",
        )
    if Path(os.path.normpath(os.fspath(path))) != path:
        raise _operation_error(
            "DIGEST_KEYRING_PATH_INVALID",
            "narration digest keyring path is invalid",
        )


def _open_secure_parent(path: Path) -> int:
    """Open an existing operator-owned parent without following its final link."""

    _validate_target_path(path)
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise _operation_error(
            "DIGEST_KEYRING_OPEN_POLICY_UNAVAILABLE",
            "secure narration digest keyring write policy is unavailable",
        )
    try:
        if path.parent.resolve(strict=True) != path.parent:
            raise _operation_error(
                "DIGEST_KEYRING_PARENT_INVALID",
                "narration digest keyring parent is invalid",
            )
        descriptor = os.open(
            path.parent,
            os.O_RDONLY | directory | nofollow | getattr(os, "O_CLOEXEC", 0),
        )
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) & 0o022
        ):
            os.close(descriptor)
            raise _operation_error(
                "DIGEST_KEYRING_PARENT_INVALID",
                "narration digest keyring parent is invalid",
            )
        return descriptor
    except DigestKeyringOperationError:
        raise
    except OSError as error:
        raise _operation_error(
            "DIGEST_KEYRING_PARENT_UNAVAILABLE",
            "narration digest keyring parent is unavailable",
        ) from None


def _lock_parent(parent_descriptor: int) -> None:
    """Serialize cooperating init/rotate commands across atomic publication."""

    try:
        fcntl.flock(parent_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        raise _operation_error(
            "DIGEST_KEYRING_BUSY",
            "another narration digest keyring operation is active",
        ) from None
    except OSError as error:
        raise _operation_error(
            "DIGEST_KEYRING_LOCK_FAILED",
            "narration digest keyring operation lock failed",
        ) from None


def _lstat_at(parent_descriptor: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise _operation_error(
            "DIGEST_KEYRING_FILE_INVALID",
            "narration digest keyring file identity is invalid",
        ) from None


def _validate_existing_metadata(metadata: os.stat_result | None) -> os.stat_result:
    if metadata is None:
        raise _operation_error(
            "DIGEST_KEYRING_MISSING",
            "existing narration digest keyring is required for rotation",
        )
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise _operation_error(
            "DIGEST_KEYRING_FILE_INVALID",
            "existing narration digest keyring file is invalid",
        )
    return metadata


def _identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _encode_keyring(keyring: DigestKeyring) -> bytes:
    rows = [
        {
            "key_id": key.key_id,
            "status": key.status,
            "secret_base64": base64.b64encode(key.secret).decode("ascii"),
        }
        for key in keyring.keys.values()
    ]
    payload = {
        "schema_version": DIGEST_KEYRING_SCHEMA_VERSION,
        "active_key_id": keyring.active_key_id,
        "keys": rows,
    }
    return (
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )


def _write_all(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:  # pragma: no cover - defensive kernel contract guard
            raise OSError(errno.EIO, "short keyring write")
        view = view[written:]


def _write_validated_temp(
    path: Path,
    parent_descriptor: int,
    payload: bytes,
) -> str:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | nofollow
        | getattr(os, "O_CLOEXEC", 0)
    )
    for _ in range(_TEMP_CREATE_ATTEMPTS):
        try:
            temporary_name = f".{path.name}.new-{secrets.token_hex(16)}"
        except Exception as error:
            raise _operation_error(
                "DIGEST_KEYRING_TEMP_UNAVAILABLE",
                "temporary narration digest keyring name is unavailable",
            ) from None
        descriptor: int | None = None
        created = False
        try:
            descriptor = os.open(
                temporary_name,
                flags,
                0o600,
                dir_fd=parent_descriptor,
            )
            created = True
            os.fchmod(descriptor, 0o600)
            _write_all(descriptor, payload)
            os.fsync(descriptor)
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or metadata.st_uid != os.geteuid()
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_size != len(payload)
            ):
                raise _operation_error(
                    "DIGEST_KEYRING_TEMP_INVALID",
                    "temporary narration digest keyring is invalid",
                )
            os.close(descriptor)
            descriptor = None
            load_digest_keyring(path.parent / temporary_name)
            created = False
            return temporary_name
        except FileExistsError:
            continue
        except DigestKeyringOperationError:
            raise
        except DigestKeyringError as error:
            raise _operation_error(error.code, str(error)) from None
        except OSError as error:
            raise _operation_error(
                "DIGEST_KEYRING_WRITE_FAILED",
                "narration digest keyring write failed",
            ) from None
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if created:
                _unlink_if_present(parent_descriptor, temporary_name)
    raise _operation_error(
        "DIGEST_KEYRING_TEMP_UNAVAILABLE",
        "temporary narration digest keyring name is unavailable",
    )


def _unlink_if_present(parent_descriptor: int, name: str) -> None:
    try:
        os.unlink(name, dir_fd=parent_descriptor)
    except FileNotFoundError:
        return
    except OSError:
        return


def _publish_fresh(
    path: Path,
    parent_descriptor: int,
    temporary_name: str,
) -> None:
    linked = False
    try:
        # link(2) is the portable no-replace publication primitive.  The final
        # name cannot be overwritten even if another process wins the race.
        os.link(
            temporary_name,
            path.name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        linked = True
        os.unlink(temporary_name, dir_fd=parent_descriptor)
        os.fsync(parent_descriptor)
    except FileExistsError as error:
        raise _operation_error(
            "DIGEST_KEYRING_ALREADY_EXISTS",
            "narration digest keyring already exists",
        ) from None
    except OSError as error:
        if linked:
            _unlink_if_present(parent_descriptor, path.name)
        raise _operation_error(
            "DIGEST_KEYRING_PUBLISH_FAILED",
            "narration digest keyring publication failed",
        ) from None
    finally:
        _unlink_if_present(parent_descriptor, temporary_name)


def _new_keyring(key_id: str, secret: bytes) -> DigestKeyring:
    key = HmacDigestKey(key_id=key_id, secret=secret, status="active")
    return DigestKeyring(active_key_id=key_id, keys={key_id: key})


def initialize_digest_keyring(
    path: Path,
    key_id: str,
    *,
    fresh_install: bool,
    assert_no_db_references: bool,
    no_db_references_check: Callable[[], bool] | None = None,
    secret_factory: Callable[[int], bytes] | None = None,
) -> str:
    """Create one fresh keyring; never overwrite or infer recovery intent.

    ``no_db_references_check`` is an optional dependency-injected gate for an
    operator wrapper or a test.  The standalone command performs no database
    access and therefore still requires the explicit operator assertion.
    """

    _validate_target_path(path)
    _validate_key_id(key_id)
    if not fresh_install or not assert_no_db_references:
        raise _operation_error(
            "DIGEST_KEYRING_FRESH_INIT_ATTESTATION_REQUIRED",
            "fresh narration digest keyring initialization requires explicit attestations",
        )
    if no_db_references_check is not None:
        try:
            no_references = no_db_references_check()
        except Exception as error:
            raise _operation_error(
                "DIGEST_KEYRING_REFERENCE_CHECK_FAILED",
                "narration digest reference check failed",
            ) from None
        if no_references is not True:
            raise _operation_error(
                "DIGEST_KEYRING_DATABASE_REFERENCES_PRESENT",
                "narration digest database references prevent fresh initialization",
            )

    parent_descriptor = _open_secure_parent(path)
    temporary_name: str | None = None
    try:
        _lock_parent(parent_descriptor)
        if _lstat_at(parent_descriptor, path.name) is not None:
            raise _operation_error(
                "DIGEST_KEYRING_ALREADY_EXISTS",
                "narration digest keyring already exists",
            )
        keyring = _new_keyring(key_id, _generate_secret(secret_factory))
        temporary_name = _write_validated_temp(
            path,
            parent_descriptor,
            _encode_keyring(keyring),
        )
        _publish_fresh(path, parent_descriptor, temporary_name)
        temporary_name = None
        published = load_digest_keyring(path)
        _validate_existing_metadata(_lstat_at(parent_descriptor, path.name))
        if (
            published.active_key_id != key_id
            or len(published.keys) != 1
            or not secrets.compare_digest(
                published.active.secret,
                keyring.active.secret,
            )
        ):
            raise _operation_error(
                "DIGEST_KEYRING_POSTCONDITION_FAILED",
                "fresh narration digest keyring validation failed",
            )
        return key_id
    except DigestKeyringOperationError:
        raise
    except DigestKeyringError as error:
        raise _operation_error(error.code, str(error)) from None
    except (OSError, TypeError, ValueError) as error:
        raise _operation_error(
            "DIGEST_KEYRING_OPERATION_FAILED",
            "fresh narration digest keyring initialization failed",
        ) from None
    finally:
        if temporary_name is not None:
            _unlink_if_present(parent_descriptor, temporary_name)
        os.close(parent_descriptor)


def _rotated_keyring(
    current: DigestKeyring,
    new_key_id: str,
    new_secret: bytes,
) -> DigestKeyring:
    if new_key_id in current.keys:
        raise _operation_error(
            "DIGEST_KEY_ID_ALREADY_EXISTS",
            "new narration digest key identity already exists",
        )
    if len(current.keys) >= MAX_KEY_COUNT:
        raise _operation_error(
            "DIGEST_KEYRING_CAPACITY_EXCEEDED",
            "narration digest keyring cannot retain another historical key",
        )
    keys: dict[str, HmacDigestKey] = {}
    for key_id, key in current.keys.items():
        keys[key_id] = HmacDigestKey(
            key_id=key_id,
            secret=key.secret,
            status="verify_only",
        )
    keys[new_key_id] = HmacDigestKey(
        key_id=new_key_id,
        secret=new_secret,
        status="active",
    )
    return DigestKeyring(active_key_id=new_key_id, keys=keys)


def rotate_digest_keyring(
    path: Path,
    new_key_id: str,
    *,
    secret_factory: Callable[[int], bytes] | None = None,
) -> str:
    """Atomically replace a valid keyring while retaining every old key."""

    _validate_target_path(path)
    _validate_key_id(new_key_id)
    parent_descriptor = _open_secure_parent(path)
    temporary_name: str | None = None
    try:
        _lock_parent(parent_descriptor)
        before = _validate_existing_metadata(
            _lstat_at(parent_descriptor, path.name),
        )
        try:
            current = load_digest_keyring(path)
        except DigestKeyringError as error:
            raise _operation_error(error.code, str(error)) from None
        after_load = _validate_existing_metadata(
            _lstat_at(parent_descriptor, path.name),
        )
        if _identity(before) != _identity(after_load):
            raise _operation_error(
                "DIGEST_KEYRING_CHANGED",
                "narration digest keyring changed during rotation",
            )

        rotated = _rotated_keyring(
            current,
            new_key_id,
            _generate_secret(secret_factory),
        )
        temporary_name = _write_validated_temp(
            path,
            parent_descriptor,
            _encode_keyring(rotated),
        )
        before_replace = _validate_existing_metadata(
            _lstat_at(parent_descriptor, path.name),
        )
        if _identity(before) != _identity(before_replace):
            raise _operation_error(
                "DIGEST_KEYRING_CHANGED",
                "narration digest keyring changed during rotation",
            )
        try:
            os.replace(
                temporary_name,
                path.name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
            )
            temporary_name = None
            os.fsync(parent_descriptor)
        except OSError as error:
            raise _operation_error(
                "DIGEST_KEYRING_REPLACE_FAILED",
                "narration digest keyring atomic replacement failed",
            ) from None

        published = load_digest_keyring(path)
        _validate_existing_metadata(_lstat_at(parent_descriptor, path.name))
        if (
            published.active_key_id != new_key_id
            or set(published.keys) != set(rotated.keys)
            or any(
                published.require(key_id).status != key.status
                or not secrets.compare_digest(
                    published.require(key_id).secret,
                    key.secret,
                )
                for key_id, key in rotated.keys.items()
            )
        ):
            raise _operation_error(
                "DIGEST_KEYRING_POSTCONDITION_FAILED",
                "rotated narration digest keyring validation failed",
            )
        return new_key_id
    except DigestKeyringOperationError:
        raise
    except DigestKeyringError as error:
        raise _operation_error(error.code, str(error)) from None
    except (OSError, TypeError, ValueError) as error:
        raise _operation_error(
            "DIGEST_KEYRING_OPERATION_FAILED",
            "narration digest keyring rotation failed",
        ) from None
    finally:
        if temporary_name is not None:
            _unlink_if_present(parent_descriptor, temporary_name)
        os.close(parent_descriptor)


def build_parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(
        description="Create or rotate the local narration HMAC digest keyring",
    )
    subparsers = parser.add_subparsers(dest="operation", required=True)

    initialize = subparsers.add_parser(
        "init",
        help="create a keyring only for a confirmed fresh installation",
    )
    initialize.add_argument("--path", type=Path, required=True)
    initialize.add_argument("--key-id", required=True)
    initialize.add_argument("--fresh-install", action="store_true")
    initialize.add_argument("--assert-no-db-references", action="store_true")

    rotate = subparsers.add_parser(
        "rotate",
        help="retain historical keys and publish one new active key",
    )
    rotate.add_argument("--path", type=Path, required=True)
    rotate.add_argument("--key-id", required=True)
    return parser


def _safe_result(code: str, key_id: str | None = None) -> None:
    payload = {"code": code}
    if key_id is not None:
        payload["key_id"] = key_id
    print(json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True))


def main(
    argv: list[str] | None = None,
    *,
    no_db_references_check: Callable[[], bool] | None = None,
) -> int:
    try:
        args = build_parser().parse_args(argv)
        if args.operation == "init":
            key_id = initialize_digest_keyring(
                args.path,
                args.key_id,
                fresh_install=args.fresh_install,
                assert_no_db_references=args.assert_no_db_references,
                no_db_references_check=no_db_references_check,
            )
            _safe_result("DIGEST_KEYRING_CREATED", key_id)
            return 0
        if args.operation == "rotate":
            key_id = rotate_digest_keyring(args.path, args.key_id)
            _safe_result("DIGEST_KEYRING_ROTATED", key_id)
            return 0
        raise _operation_error(
            "DIGEST_KEYRING_ARGUMENTS_INVALID",
            "narration digest keyring command arguments are invalid",
        )
    except (DigestKeyringOperationError, DigestKeyringError) as error:
        _safe_result(error.code)
        return 2
    except Exception:
        _safe_result("DIGEST_KEYRING_OPERATION_FAILED")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
