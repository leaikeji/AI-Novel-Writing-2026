#!/usr/bin/env python3
"""Verify or safely initialize the narration digest keyring after migration.

The command is deliberately narrow: it proves the installed database is at
the frozen schema head, serializes against new edition-segment references,
and then either validates an existing keyring or creates one for an explicitly
declared fresh installation.  It never prints a database URL, filesystem path,
or key material.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterator
from contextlib import contextmanager
import json
import os
from pathlib import Path
import stat
import sys
from typing import ContextManager, Final


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from sqlalchemy import text  # noqa: E402

from backend.database import get_engine  # noqa: E402
from backend.narration.digest_keyring import (  # noqa: E402
    DigestKeyringError,
    load_digest_keyring,
)
from backend.narration.schema_readiness import (  # noqa: E402
    database_revision_satisfies,
)
from scripts.tts.manage_digest_keyring import (  # noqa: E402
    DigestKeyringOperationError,
    initialize_digest_keyring,
)


MINIMUM_ALEMBIC_REVISION: Final = "20260829_0032"
_LOCK_REFERENCES_SQL: Final = (
    "LOCK TABLE narration_edition_segments IN SHARE ROW EXCLUSIVE MODE"
)
_COUNT_REFERENCES_SQL: Final = (
    "SELECT count(*) FROM narration_edition_segments "
    "WHERE render_digest_key_id IS NOT NULL"
)


class DigestKeyringBootstrapError(RuntimeError):
    """Secret-, path-, and DSN-free bootstrap failure."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # pragma: no cover - main boundary
        del message
        raise DigestKeyringBootstrapError(
            "DIGEST_KEYRING_BOOTSTRAP_ARGUMENTS_INVALID",
            "narration digest keyring bootstrap arguments are invalid",
        )


def _error(code: str, message: str) -> DigestKeyringBootstrapError:
    return DigestKeyringBootstrapError(code, message)


@contextmanager
def database_reference_guard() -> Iterator[bool]:
    """Hold the reference table stable while a caller validates or creates.

    The table lock prevents a render transaction from adding a historical key
    reference after the zero-reference proof but before atomic key publication.
    """

    try:
        engine = get_engine()
        with engine.begin() as connection:
            revisions = tuple(
                str(value)
                for value in connection.scalars(
                    text("SELECT version_num FROM alembic_version")
                )
            )
            if not database_revision_satisfies(
                revisions,
                minimum_revision=MINIMUM_ALEMBIC_REVISION,
            ):
                raise _error(
                    "DIGEST_KEYRING_SCHEMA_NOT_READY",
                    "narration digest keyring bootstrap requires its minimum migration",
                )
            connection.execute(text(_LOCK_REFERENCES_SQL))
            reference_count = connection.scalar(text(_COUNT_REFERENCES_SQL))
            if type(reference_count) is not int or reference_count < 0:
                raise _error(
                    "DIGEST_KEYRING_REFERENCE_CHECK_FAILED",
                    "narration digest reference check returned an invalid result",
                )
            yield reference_count == 0
    except DigestKeyringBootstrapError:
        raise
    except Exception:
        raise _error(
            "DIGEST_KEYRING_REFERENCE_CHECK_FAILED",
            "narration digest reference check failed",
        ) from None


def _path_exists_without_following(path: Path) -> bool:
    try:
        os.lstat(path)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        raise _error(
            "DIGEST_KEYRING_FILE_INVALID",
            "narration digest keyring file identity is invalid",
        ) from None


def _validate_existing_identity(path: Path) -> None:
    try:
        metadata = os.lstat(path)
        parent = os.lstat(path.parent)
    except OSError:
        raise _error(
            "DIGEST_KEYRING_FILE_INVALID",
            "narration digest keyring file identity is invalid",
        ) from None
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != os.geteuid()
        or stat.S_IMODE(parent.st_mode) & 0o022
    ):
        raise _error(
            "DIGEST_KEYRING_FILE_INVALID",
            "narration digest keyring file identity is invalid",
        )


def _ensure_fresh_parent(path: Path) -> None:
    """Create at most the final private directory for an authorized fresh init."""

    parent = path.parent
    try:
        os.lstat(parent)
        return
    except FileNotFoundError:
        pass
    except OSError:
        raise _error(
            "DIGEST_KEYRING_PARENT_INVALID",
            "narration digest keyring parent is invalid",
        ) from None
    try:
        ancestor = os.lstat(parent.parent)
        if (
            not stat.S_ISDIR(ancestor.st_mode)
            or ancestor.st_uid != os.geteuid()
            or stat.S_IMODE(ancestor.st_mode) & 0o022
        ):
            raise _error(
                "DIGEST_KEYRING_PARENT_INVALID",
                "narration digest keyring parent is invalid",
            )
        os.mkdir(parent, mode=0o700)
    except FileExistsError:
        return
    except DigestKeyringBootstrapError:
        raise
    except OSError:
        raise _error(
            "DIGEST_KEYRING_PARENT_UNAVAILABLE",
            "narration digest keyring parent is unavailable",
        ) from None


def bootstrap_digest_keyring(
    path: Path,
    *,
    key_id: str | None,
    fresh_install: bool,
    reference_guard: Callable[[], ContextManager[bool]] = database_reference_guard,
) -> tuple[str, str]:
    """Return ``(stable_code, active_key_id)`` without exposing key material."""

    if (
        not isinstance(path, Path)
        or not path.is_absolute()
        or path.name in {"", ".", ".."}
        or Path(os.path.normpath(os.fspath(path))) != path
    ):
        raise _error(
            "DIGEST_KEYRING_PATH_INVALID",
            "narration digest keyring path is invalid",
        )
    with reference_guard() as no_database_references:
        if _path_exists_without_following(path):
            _validate_existing_identity(path)
            try:
                existing = load_digest_keyring(path)
            except DigestKeyringError as error:
                raise _error(error.code, str(error)) from None
            return "DIGEST_KEYRING_VALID", existing.active_key_id

        if not fresh_install:
            raise _error(
                "DIGEST_KEYRING_MISSING",
                "narration digest keyring is missing and fresh initialization was not authorized",
            )
        if not key_id:
            raise _error(
                "DIGEST_KEY_ID_REQUIRED",
                "fresh narration digest keyring initialization requires a key identity",
            )
        if no_database_references is not True:
            raise _error(
                "DIGEST_KEYRING_DATABASE_REFERENCES_PRESENT",
                "narration digest database references prevent fresh initialization",
            )
        _ensure_fresh_parent(path)
        try:
            created_key_id = initialize_digest_keyring(
                path,
                key_id,
                fresh_install=True,
                assert_no_db_references=True,
                no_db_references_check=lambda: no_database_references,
            )
        except DigestKeyringOperationError as error:
            raise _error(error.code, str(error)) from None
        return "DIGEST_KEYRING_CREATED", created_key_id


def build_parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, required=True)
    parser.add_argument("--key-id")
    parser.add_argument("--fresh-install", action="store_true")
    return parser


def _safe_result(code: str, key_id: str | None = None) -> None:
    payload = {"code": code}
    if key_id is not None:
        payload["key_id"] = key_id
    print(json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        code, key_id = bootstrap_digest_keyring(
            args.path,
            key_id=args.key_id,
            fresh_install=args.fresh_install,
        )
        _safe_result(code, key_id)
        return 0
    except (DigestKeyringBootstrapError, DigestKeyringError) as error:
        _safe_result(error.code)
        return 2
    except Exception:
        _safe_result("DIGEST_KEYRING_BOOTSTRAP_FAILED")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
