#!/usr/bin/env python3
"""Read a packaged candidate's Alembic identity without executing its code.

This module is intentionally independent from Alembic.  A candidate is
untrusted until its migration graph has been parsed with the narrow grammar
below, so importing candidate modules or asking Alembic to load them on the
host would cross the release boundary.
"""

from __future__ import annotations

import ast
import configparser
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Final


CANONICAL_BASE_REVISION: Final = "20260823_0001"
REVISION_RE: Final = re.compile(r"^[0-9]{8}_[0-9]{4}$")
MAX_MIGRATION_FILES: Final = 512
MAX_MIGRATION_FILE_BYTES: Final = 1024 * 1024
MAX_MIGRATION_TOTAL_BYTES: Final = 16 * 1024 * 1024

_IDENTITY_NAMES: Final = frozenset(
    {"revision", "down_revision", "branch_labels", "depends_on"}
)


class CandidateMigrationError(ValueError):
    """A stable, output-safe candidate migration validation failure."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class CandidateMigrationIdentity:
    """The complete single-line migration identity of one candidate."""

    base: str
    head: str
    revisions: tuple[str, ...]
    file_count: int
    total_bytes: int


@dataclass(frozen=True)
class _MigrationNode:
    revision: str
    down_revision: str | None


def _canonical_candidate_root(candidate_root: Path) -> Path:
    if not candidate_root.is_absolute():
        raise CandidateMigrationError("CANDIDATE_MUST_BE_ABSOLUTE")
    try:
        resolved = candidate_root.resolve(strict=True)
    except OSError as error:
        raise CandidateMigrationError("CANDIDATE_NOT_FOUND") from error
    if (
        resolved != candidate_root
        or candidate_root.is_symlink()
        or not candidate_root.is_dir()
    ):
        raise CandidateMigrationError("CANDIDATE_PATH_NOT_CANONICAL")
    return resolved


def _require_regular_unlinked_file(path: Path, *, code: str) -> os.stat_result:
    try:
        identity = path.lstat()
    except OSError as error:
        raise CandidateMigrationError(code) from error
    if not stat.S_ISREG(identity.st_mode) or identity.st_nlink != 1:
        raise CandidateMigrationError(code)
    return identity


def _read_small_file(path: Path, *, maximum_bytes: int, code: str) -> bytes:
    before = _require_regular_unlinked_file(path, code=code)
    if before.st_size > maximum_bytes:
        raise CandidateMigrationError("MIGRATION_FILE_TOO_LARGE")
    if not hasattr(os, "O_NOFOLLOW"):
        raise CandidateMigrationError("MIGRATION_NOFOLLOW_UNAVAILABLE")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise CandidateMigrationError(code) from error
    try:
        opened = os.fstat(descriptor)
        if _file_identity(opened) != _file_identity(before):
            raise CandidateMigrationError("MIGRATION_FILE_IDENTITY_CHANGED")
        chunks: list[bytes] = []
        total = 0
        try:
            while True:
                chunk = os.read(
                    descriptor,
                    min(64 * 1024, maximum_bytes + 1 - total),
                )
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > maximum_bytes:
                    raise CandidateMigrationError("MIGRATION_FILE_TOO_LARGE")
            after = os.fstat(descriptor)
        except OSError as error:
            raise CandidateMigrationError(code) from error
    finally:
        os.close(descriptor)
    try:
        final_path = path.lstat()
    except OSError as error:
        raise CandidateMigrationError("MIGRATION_FILE_IDENTITY_CHANGED") from error
    if (
        _file_identity(after) != _file_identity(opened)
        or _file_identity(final_path) != _file_identity(before)
        or total != before.st_size
    ):
        raise CandidateMigrationError("MIGRATION_FILE_IDENTITY_CHANGED")
    return b"".join(chunks)


def _file_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        stat.S_IFMT(value.st_mode),
        value.st_dev,
        value.st_ino,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
    )


def _validate_alembic_config(candidate_root: Path) -> None:
    path = candidate_root / "alembic.ini"
    raw = _read_small_file(
        path,
        maximum_bytes=MAX_MIGRATION_FILE_BYTES,
        code="ALEMBIC_CONFIG_INVALID",
    )
    try:
        text = raw.decode("utf-8")
        parser = configparser.RawConfigParser(interpolation=None)
        parser.read_string(text)
    except (UnicodeError, configparser.Error) as error:
        raise CandidateMigrationError("ALEMBIC_CONFIG_INVALID") from error
    if not parser.has_section("alembic"):
        raise CandidateMigrationError("ALEMBIC_CONFIG_INVALID")
    if parser.get("alembic", "script_location", fallback="").strip() != (
        "backend/migrations"
    ):
        raise CandidateMigrationError("ALEMBIC_SCRIPT_LOCATION_INVALID")
    version_locations = parser.get(
        "alembic", "version_locations", fallback=""
    ).strip()
    recursive = parser.get(
        "alembic", "recursive_version_locations", fallback="false"
    ).strip().lower()
    sourceless = parser.get("alembic", "sourceless", fallback="false").strip().lower()
    if version_locations or recursive not in {"", "false", "0", "no", "off"}:
        raise CandidateMigrationError("ALEMBIC_VERSION_LOCATIONS_UNSUPPORTED")
    if sourceless not in {"", "false", "0", "no", "off"}:
        raise CandidateMigrationError("ALEMBIC_SOURCELESS_UNSUPPORTED")


def _assignment_value(statement: ast.stmt) -> tuple[str, ast.expr] | None:
    if isinstance(statement, ast.Assign):
        matching = [
            target.id
            for target in statement.targets
            if isinstance(target, ast.Name) and target.id in _IDENTITY_NAMES
        ]
        if not matching:
            return None
        if len(statement.targets) != 1 or len(matching) != 1:
            raise CandidateMigrationError("MIGRATION_IDENTITY_ASSIGNMENT_INVALID")
        return matching[0], statement.value
    if isinstance(statement, ast.AnnAssign):
        if not isinstance(statement.target, ast.Name):
            return None
        name = statement.target.id
        if name not in _IDENTITY_NAMES:
            return None
        if statement.value is None:
            raise CandidateMigrationError("MIGRATION_IDENTITY_ASSIGNMENT_INVALID")
        return name, statement.value
    return None


def _parse_migration(path: Path, raw: bytes) -> _MigrationNode:
    try:
        source = raw.decode("utf-8")
        tree = ast.parse(source, filename=path.name, mode="exec")
    except (UnicodeError, SyntaxError, ValueError) as error:
        raise CandidateMigrationError("MIGRATION_SOURCE_INVALID", path.name) from error

    values: dict[str, object] = {}
    for statement in tree.body:
        assignment = _assignment_value(statement)
        if assignment is None:
            continue
        name, expression = assignment
        if name in values:
            raise CandidateMigrationError("MIGRATION_IDENTITY_DUPLICATE", path.name)
        try:
            values[name] = ast.literal_eval(expression)
        except (ValueError, TypeError) as error:
            raise CandidateMigrationError(
                "MIGRATION_IDENTITY_NOT_LITERAL", path.name
            ) from error
    if set(values) != _IDENTITY_NAMES:
        raise CandidateMigrationError("MIGRATION_IDENTITY_INCOMPLETE", path.name)

    revision = values["revision"]
    down_revision = values["down_revision"]
    if type(revision) is not str or REVISION_RE.fullmatch(revision) is None:
        raise CandidateMigrationError("MIGRATION_REVISION_INVALID", path.name)
    if down_revision is not None and (
        type(down_revision) is not str
        or REVISION_RE.fullmatch(down_revision) is None
    ):
        raise CandidateMigrationError("MIGRATION_DOWN_REVISION_INVALID", path.name)
    if values["branch_labels"] is not None or values["depends_on"] is not None:
        raise CandidateMigrationError("MIGRATION_BRANCHING_UNSUPPORTED", path.name)
    if not path.name.startswith(f"{revision}_"):
        raise CandidateMigrationError("MIGRATION_FILENAME_MISMATCH", path.name)
    return _MigrationNode(revision=revision, down_revision=down_revision)


def inspect_candidate_migrations(candidate_root: Path) -> CandidateMigrationIdentity:
    """Return the candidate's complete single linear migration identity."""

    root = _canonical_candidate_root(candidate_root)
    _validate_alembic_config(root)
    versions = root / "backend" / "migrations" / "versions"
    try:
        versions_identity = versions.lstat()
    except OSError as error:
        raise CandidateMigrationError("MIGRATION_DIRECTORY_MISSING") from error
    if not stat.S_ISDIR(versions_identity.st_mode) or versions.is_symlink():
        raise CandidateMigrationError("MIGRATION_DIRECTORY_INVALID")

    try:
        migration_paths = sorted(
            (path for path in versions.iterdir() if path.name.endswith(".py")),
            key=lambda path: path.name,
        )
    except OSError as error:
        raise CandidateMigrationError("MIGRATION_DIRECTORY_INVALID") from error
    if not migration_paths:
        raise CandidateMigrationError("MIGRATION_GRAPH_EMPTY")
    if len(migration_paths) > MAX_MIGRATION_FILES:
        raise CandidateMigrationError("MIGRATION_FILE_COUNT_EXCEEDED")

    nodes: dict[str, _MigrationNode] = {}
    total_bytes = 0
    for path in migration_paths:
        raw = _read_small_file(
            path,
            maximum_bytes=MAX_MIGRATION_FILE_BYTES,
            code="MIGRATION_FILE_INVALID",
        )
        total_bytes += len(raw)
        if total_bytes > MAX_MIGRATION_TOTAL_BYTES:
            raise CandidateMigrationError("MIGRATION_TOTAL_BYTES_EXCEEDED")
        node = _parse_migration(path, raw)
        if node.revision in nodes:
            raise CandidateMigrationError("MIGRATION_REVISION_DUPLICATE", node.revision)
        nodes[node.revision] = node

    base = nodes.get(CANONICAL_BASE_REVISION)
    if base is None or base.down_revision is not None:
        raise CandidateMigrationError("MIGRATION_CANONICAL_BASE_MISSING")
    roots = [node.revision for node in nodes.values() if node.down_revision is None]
    if roots != [CANONICAL_BASE_REVISION]:
        raise CandidateMigrationError("MIGRATION_BASE_CARDINALITY_INVALID")
    for node in nodes.values():
        if node.down_revision is not None and node.down_revision not in nodes:
            raise CandidateMigrationError("MIGRATION_PARENT_MISSING", node.revision)

    parent_revisions = {
        node.down_revision for node in nodes.values() if node.down_revision is not None
    }
    heads = sorted(set(nodes) - parent_revisions)
    if len(heads) != 1:
        raise CandidateMigrationError("MIGRATION_HEAD_CARDINALITY_INVALID")

    head = heads[0]
    ordered_reversed: list[str] = []
    seen: set[str] = set()
    current: str | None = head
    while current is not None:
        if current in seen:
            raise CandidateMigrationError("MIGRATION_CYCLE_DETECTED")
        seen.add(current)
        ordered_reversed.append(current)
        current = nodes[current].down_revision
    if ordered_reversed[-1] != CANONICAL_BASE_REVISION or seen != set(nodes):
        raise CandidateMigrationError("MIGRATION_GRAPH_NOT_SINGLE_LINEAR_CHAIN")
    revisions = tuple(reversed(ordered_reversed))
    return CandidateMigrationIdentity(
        base=CANONICAL_BASE_REVISION,
        head=head,
        revisions=revisions,
        file_count=len(migration_paths),
        total_bytes=total_bytes,
    )


__all__ = [
    "CANONICAL_BASE_REVISION",
    "CandidateMigrationError",
    "CandidateMigrationIdentity",
    "inspect_candidate_migrations",
]
