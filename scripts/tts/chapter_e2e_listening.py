#!/usr/bin/env python3
"""Finalize one human T4-K listening decision from a bound probe request.

The command is intentionally narrow: it does not open audio, infer a verdict,
or collect technical probes.  A reviewer must explicitly provide a verdict and
all six fixed listening checks.  The command then writes the exact private
``moss-tts-chapter-listening/1.1`` record consumed by the frozen validator and
one redacted, non-overwriting receipt.

Only hashes already published by the real runner's private ``probe-request``
are copied into the listening record or receipt.  Paths, reviewer pseudonyms,
hashes, and other private values are never printed by this command.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import stat
import sys
from typing import Callable, Final, Literal, Mapping


CURRENT_PAWAPP_ROOT: Final = Path(__file__).resolve().parents[2]
if str(CURRENT_PAWAPP_ROOT) not in sys.path:
    sys.path.insert(0, str(CURRENT_PAWAPP_ROOT))

from scripts.tts.chapter_e2e_probe_request import (
    PROBE_REQUEST_FILENAME,
    PROBE_REQUEST_SCHEMA_VERSION,
)
from scripts.tts.chapter_e2e_probes import (
    ALLOWED_ASSISTANT_MODES,
    EXPECTED_RANGE_STATUS_CODES,
    EXPECTED_SIDECAR_CONTAINER_NAME,
    PROBE_SCHEMA_VERSION,
)
from scripts.tts.validate_chapter_e2e import (
    ALLOWED_VIEWPORTS,
    FORMAL_MINIMUM_DURATION_MINUTES,
    LISTENING_CLAIM_REGISTRY_DIRECTORY,
    LISTENING_COMMIT_SCHEMA,
    LISTENING_FINALIZATION_RECEIPT_FILENAME as FINALIZATION_RECEIPT_FILENAME,
    REPOSITORY_ROOT as VALIDATOR_REPOSITORY_ROOT,
    RunnerError,
    SAFE_ID_PATTERN,
)


LISTENING_RECORD_FILENAME: Final = "listening.json"
LISTENING_SCHEMA: Final = "moss-tts-chapter-listening/1.1"
FINALIZATION_RECEIPT_SCHEMA: Final = (
    "moss-tts-chapter-listening-finalization-receipt/1.2"
)
LISTENING_CLAIM_SCHEMA: Final = "moss-tts-chapter-listening-claim/1.2"
# Historical 1.0 records remain immutable audit evidence.  This finalizer only
# emits 1.1 and its non-overwriting transaction cannot reuse a 1.0 decision.
LEGACY_LISTENING_SCHEMA: Final = "moss-tts-chapter-listening/1.0"
HUMAN_LISTENING_CONFIRMATION: Final = (
    "AUTHOR-REVIEWED-T4-K-LISTENING"
)
REVIEWED_ROLES: Final = ("旁白", "林晚", "沈川")
CHECK_NAMES: Final = (
    "narrator_character_distinguishable",
    "voices_stable",
    "no_missing_or_repeated_text",
    "all_samples_intelligible_mandarin",
    "no_abnormal_pause_or_seam",
    "loudness_consistent",
)
MAX_PROBE_REQUEST_BYTES: Final = 64 * 1024
MAX_REGISTRY_DOCUMENT_BYTES: Final = 64 * 1024
# The collector itself must observe a full 30-minute stability window after
# this request is published. Human listening is a later, independent step, so
# its authorization must also cover a reasonable same-day author review.
DEFAULT_MAX_REQUEST_AGE_SECONDS: Final = 4 * 60 * 60
DEFAULT_MAX_FUTURE_SKEW_SECONDS: Final = 30
# Kept as a local binding so installed-PawApp tests can distinguish the source
# repository root from the currently executing PawApp root.
REPOSITORY_ROOT: Final = VALIDATOR_REPOSITORY_ROOT
_SHA256_LENGTH: Final = 64
_EXPECTED_CAPTURES: Final = tuple(
    (width, height, assistant_mode)
    for width, height in ALLOWED_VIEWPORTS
    for assistant_mode in ALLOWED_ASSISTANT_MODES
)
_CLAIM_KEYS: Final = frozenset(
    {
        "schema_version",
        "state",
        "claimed_at",
        "verdict",
        "probe_request_fingerprint_sha256",
        "run_fingerprint_sha256",
        "target_scope_sha256",
        "automatic_edition_id_sha256",
        "manual_edition_id_sha256",
        "automatic_edition_fingerprint_sha256",
        "manual_edition_fingerprint_sha256",
        "listening_record_sha256",
        "finalization_receipt_sha256",
        "output_directory_canonical_sha256",
        "output_directory_identity_sha256",
        "self_sha256",
    }
)
_COMMIT_KEYS: Final = frozenset(
    {
        "schema_version",
        "state",
        "committed_at",
        "claim_sha256",
        "run_fingerprint_sha256",
        "listening_record_sha256",
        "finalization_receipt_sha256",
        "output_directory_canonical_sha256",
        "output_directory_identity_sha256",
        "self_sha256",
    }
)


class ListeningFinalizeError(RunnerError):
    """Stable, redacted failure safe to emit on the command line."""

    def __init__(self, code: str):
        super().__init__(code)


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # pragma: no cover - argparse owns text
        del message
        raise ListeningFinalizeError("LISTENING_ARGUMENTS_INVALID")


class _DuplicateJsonKey(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class BoundListeningRequest:
    """Minimum validated authority needed to create a listening record."""

    created_at: datetime
    request_fingerprint_sha256: str
    run_fingerprint_sha256: str
    target_scope_sha256: str
    automatic_edition_id_sha256: str
    manual_edition_id_sha256: str
    automatic_edition_fingerprint_sha256: str
    manual_edition_fingerprint_sha256: str
    listening_output_hashes: tuple[str, ...]


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise ListeningFinalizeError(
            "LISTENING_PROBE_REQUEST_INVALID"
        ) from None


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == _SHA256_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def _reject_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey
        result[key] = value
    return result


def _reject_nonfinite_json(_: str) -> object:
    raise ValueError


def _require_exact_mapping(
    value: object,
    keys: frozenset[str],
    *,
    code: str,
) -> Mapping[str, object]:
    if type(value) is not dict or frozenset(value) != keys:
        raise ListeningFinalizeError(code)
    return value


def _parse_utc_timestamp(value: object) -> datetime:
    if type(value) is not str or len(value) != 20:
        raise ListeningFinalizeError("LISTENING_PROBE_TIME_INVALID")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        raise ListeningFinalizeError(
            "LISTENING_PROBE_TIME_INVALID"
        ) from None
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise ListeningFinalizeError("LISTENING_PROBE_TIME_INVALID")
    return parsed


def _same_object(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _file_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _secure_parent(metadata: os.stat_result) -> bool:
    return (
        stat.S_ISDIR(metadata.st_mode)
        and not stat.S_ISLNK(metadata.st_mode)
        and metadata.st_uid == os.getuid()
        and stat.S_IMODE(metadata.st_mode) == 0o700
    )


def _secure_input_file(metadata: os.stat_result) -> bool:
    return (
        stat.S_ISREG(metadata.st_mode)
        and not stat.S_ISLNK(metadata.st_mode)
        and metadata.st_uid == os.getuid()
        and metadata.st_nlink == 1
        and stat.S_IMODE(metadata.st_mode) == 0o600
        and 0 < metadata.st_size <= MAX_PROBE_REQUEST_BYTES
    )


def _secure_output_file(
    metadata: os.stat_result,
    *,
    expected_size: int,
) -> bool:
    return (
        stat.S_ISREG(metadata.st_mode)
        and not stat.S_ISLNK(metadata.st_mode)
        and metadata.st_uid == os.getuid()
        and metadata.st_nlink == 1
        and stat.S_IMODE(metadata.st_mode) == 0o600
        and metadata.st_size == expected_size
    )


def _reject_symlink_components(
    path: Path,
    *,
    allow_missing_final: bool,
    code: str,
) -> None:
    if not path.is_absolute() or ".." in path.parts:
        raise ListeningFinalizeError(code)
    current = Path(path.anchor)
    final_index = len(path.parts) - 1
    for index, part in enumerate(path.parts[1:], start=1):
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            if allow_missing_final and index == final_index:
                return
            raise ListeningFinalizeError(code) from None
        except OSError:
            raise ListeningFinalizeError(code) from None
        if stat.S_ISLNK(metadata.st_mode):
            raise ListeningFinalizeError(code)


def _protected_code_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    for candidate in (REPOSITORY_ROOT, CURRENT_PAWAPP_ROOT):
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            raise ListeningFinalizeError(
                "LISTENING_PRIVATE_PATH_UNSAFE"
            ) from None
        if resolved not in roots:
            roots.append(resolved)
    return tuple(roots)


def _is_protected(path: Path) -> bool:
    return any(
        path == root or path.is_relative_to(root)
        for root in _protected_code_roots()
    )


def _open_secure_parent(
    supplied_parent: Path,
    *,
    code: str,
) -> tuple[int, Path, os.stat_result]:
    try:
        supplied_before = supplied_parent.lstat()
        resolved_parent = supplied_parent.resolve(strict=True)
        resolved_before = resolved_parent.lstat()
    except OSError:
        raise ListeningFinalizeError(code) from None
    if (
        _is_protected(resolved_parent)
        or not _same_object(supplied_before, resolved_before)
        or not _secure_parent(supplied_before)
        or not _secure_parent(resolved_before)
    ):
        raise ListeningFinalizeError(code)
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise ListeningFinalizeError(code)
    descriptor: int | None = None
    try:
        descriptor = os.open(
            resolved_parent,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | nofollow,
        )
        opened = os.fstat(descriptor)
        if (
            not _same_object(opened, resolved_before)
            or not _secure_parent(opened)
        ):
            raise ListeningFinalizeError(code)
        return descriptor, resolved_parent, opened
    except ListeningFinalizeError:
        if descriptor is not None:
            os.close(descriptor)
        raise
    except OSError:
        if descriptor is not None:
            os.close(descriptor)
        raise ListeningFinalizeError(code) from None


def _open_or_create_claim_registry() -> tuple[int, Path, os.stat_result]:
    """Create only the fixed central claim registry, then pin its dirfd.

    The ordinary input/output parent checker intentionally never creates an
    operator-supplied path.  The claim registry is different: its absolute
    location is fixed by this PawApp and must also work on a clean secrets
    volume.  Every component is traversed with ``O_NOFOLLOW`` and only the
    final directory may be created/accepted as a current-uid ``0700`` target.
    """

    path = LISTENING_CLAIM_REGISTRY_DIRECTORY
    if (
        not isinstance(path, Path)
        or not path.is_absolute()
        or ".." in path.parts
    ):
        raise ListeningFinalizeError("LISTENING_CLAIM_REGISTRY_UNSAFE")
    try:
        unresolved = path.resolve(strict=False)
    except OSError:
        raise ListeningFinalizeError(
            "LISTENING_CLAIM_REGISTRY_UNSAFE"
        ) from None
    if _is_protected(unresolved):
        raise ListeningFinalizeError("LISTENING_CLAIM_REGISTRY_UNSAFE")
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise ListeningFinalizeError("LISTENING_CLAIM_REGISTRY_UNSAFE")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | nofollow
    )
    descriptor: int | None = None
    try:
        descriptor = os.open(path.anchor, flags)
        for index, component in enumerate(path.parts[1:], start=1):
            next_descriptor: int | None = None
            try:
                next_descriptor = os.open(
                    component,
                    flags,
                    dir_fd=descriptor,
                )
            except FileNotFoundError:
                try:
                    os.mkdir(component, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                next_descriptor = os.open(
                    component,
                    flags,
                    dir_fd=descriptor,
                )
            metadata = os.fstat(next_descriptor)
            if not stat.S_ISDIR(metadata.st_mode):
                raise ListeningFinalizeError(
                    "LISTENING_CLAIM_REGISTRY_UNSAFE"
                )
            if index == len(path.parts) - 1 and not _secure_parent(metadata):
                raise ListeningFinalizeError(
                    "LISTENING_CLAIM_REGISTRY_UNSAFE"
                )
            os.close(descriptor)
            descriptor = next_descriptor
        opened = os.fstat(descriptor)
        supplied = path.lstat()
        resolved = path.resolve(strict=True)
        resolved_metadata = resolved.lstat()
        if (
            not _secure_parent(opened)
            or not _secure_parent(supplied)
            or not _secure_parent(resolved_metadata)
            or not _same_object(opened, supplied)
            or not _same_object(opened, resolved_metadata)
        ):
            raise ListeningFinalizeError(
                "LISTENING_CLAIM_REGISTRY_UNSAFE"
            )
        result = descriptor, resolved, opened
        descriptor = None
        return result
    except ListeningFinalizeError:
        raise
    except OSError:
        raise ListeningFinalizeError(
            "LISTENING_CLAIM_REGISTRY_UNSAFE"
        ) from None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _read_secure_probe_request(path: Path) -> bytes:
    try:
        candidate = Path(path)
    except (TypeError, ValueError, OSError):
        raise ListeningFinalizeError(
            "LISTENING_PROBE_PATH_UNSAFE"
        ) from None
    if candidate.name != PROBE_REQUEST_FILENAME:
        raise ListeningFinalizeError("LISTENING_PROBE_PATH_UNSAFE")
    _reject_symlink_components(
        candidate,
        allow_missing_final=False,
        code="LISTENING_PROBE_PATH_UNSAFE",
    )
    parent_descriptor: int | None = None
    file_descriptor: int | None = None
    try:
        parent_descriptor, resolved_parent, opened_parent = _open_secure_parent(
            candidate.parent,
            code="LISTENING_PROBE_FILE_UNSAFE",
        )
        before = os.stat(
            candidate.name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        if not _secure_input_file(before):
            raise ListeningFinalizeError("LISTENING_PROBE_FILE_UNSAFE")
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            raise ListeningFinalizeError("LISTENING_PROBE_FILE_UNSAFE")
        file_descriptor = os.open(
            candidate.name,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | nofollow,
            dir_fd=parent_descriptor,
        )
        opened = os.fstat(file_descriptor)
        if (
            _file_identity(opened) != _file_identity(before)
            or not _secure_input_file(opened)
        ):
            raise ListeningFinalizeError("LISTENING_PROBE_FILE_UNSAFE")
        chunks: list[bytes] = []
        remaining = opened.st_size
        while remaining:
            chunk = os.read(file_descriptor, min(remaining, 16 * 1024))
            if not chunk:
                raise ListeningFinalizeError("LISTENING_PROBE_FILE_UNSAFE")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(file_descriptor, 1):
            raise ListeningFinalizeError("LISTENING_PROBE_FILE_UNSAFE")

        after = os.fstat(file_descriptor)
        path_after = os.stat(
            candidate.name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        parent_after = os.fstat(parent_descriptor)
        supplied_parent_after = candidate.parent.lstat()
        resolved_parent_after = resolved_parent.lstat()
        _reject_symlink_components(
            candidate,
            allow_missing_final=False,
            code="LISTENING_PROBE_PATH_UNSAFE",
        )
        if (
            _file_identity(after) != _file_identity(opened)
            or _file_identity(path_after) != _file_identity(opened)
            or not _secure_input_file(after)
            or not _secure_input_file(path_after)
            or not _same_object(parent_after, opened_parent)
            or not _same_object(supplied_parent_after, opened_parent)
            or not _same_object(resolved_parent_after, opened_parent)
            or not _secure_parent(parent_after)
            or not _secure_parent(supplied_parent_after)
            or not _secure_parent(resolved_parent_after)
        ):
            raise ListeningFinalizeError("LISTENING_PROBE_FILE_UNSAFE")
        return b"".join(chunks)
    except ListeningFinalizeError:
        raise
    except OSError:
        raise ListeningFinalizeError("LISTENING_PROBE_FILE_UNSAFE") from None
    finally:
        if file_descriptor is not None:
            try:
                os.close(file_descriptor)
            except OSError:
                pass
        if parent_descriptor is not None:
            try:
                os.close(parent_descriptor)
            except OSError:
                pass


def _parse_probe_request(
    raw: bytes,
    *,
    now: datetime,
    max_age: timedelta,
    max_future_skew: timedelta,
    allow_expired_prepared_recovery: bool = False,
) -> BoundListeningRequest:
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_json,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise ListeningFinalizeError(
            "LISTENING_PROBE_REQUEST_INVALID"
        ) from None
    request = _require_exact_mapping(
        value,
        frozenset(
            {
                "schema_version",
                "report_schema_version",
                "created_at",
                "controller_preflight_payload_sha256",
                "binding_seed",
                "performance_seed",
                "required_captures",
                "runtime_contract",
                "request_fingerprint_sha256",
            }
        ),
        code="LISTENING_PROBE_REQUEST_INVALID",
    )
    if (
        request["schema_version"] != PROBE_REQUEST_SCHEMA_VERSION
        or request["report_schema_version"] != PROBE_SCHEMA_VERSION
    ):
        raise ListeningFinalizeError("LISTENING_PROBE_SCHEMA_INVALID")
    if not _is_sha256(request["controller_preflight_payload_sha256"]):
        raise ListeningFinalizeError(
            "LISTENING_PROBE_CONTROLLER_BINDING_INVALID"
        )

    created_at = _parse_utc_timestamp(request["created_at"])
    if created_at > now + max_future_skew:
        raise ListeningFinalizeError("LISTENING_PROBE_TIME_FUTURE")
    if (
        not allow_expired_prepared_recovery
        and now - created_at > max_age
    ):
        raise ListeningFinalizeError("LISTENING_PROBE_REQUEST_EXPIRED")

    binding = _require_exact_mapping(
        request["binding_seed"],
        frozenset(
            {
                "run_fingerprint_sha256",
                "target_scope_sha256",
                "automatic_edition_id_sha256",
                "manual_edition_id_sha256",
                "automatic_edition_fingerprint_sha256",
                "manual_edition_fingerprint_sha256",
                "listening_output_hashes",
                "required_stability_seconds",
            }
        ),
        code="LISTENING_PROBE_BINDING_INVALID",
    )
    for key in (
        "run_fingerprint_sha256",
        "target_scope_sha256",
        "automatic_edition_id_sha256",
        "manual_edition_id_sha256",
        "automatic_edition_fingerprint_sha256",
        "manual_edition_fingerprint_sha256",
    ):
        if not _is_sha256(binding[key]):
            raise ListeningFinalizeError("LISTENING_PROBE_BINDING_INVALID")
    if (
        binding["automatic_edition_id_sha256"]
        == binding["manual_edition_id_sha256"]
        or binding["automatic_edition_fingerprint_sha256"]
        == binding["manual_edition_fingerprint_sha256"]
    ):
        raise ListeningFinalizeError("LISTENING_PROBE_BINDING_INVALID")
    output_hashes = binding["listening_output_hashes"]
    if (
        type(output_hashes) is not list
        or not output_hashes
        or any(not _is_sha256(item) for item in output_hashes)
        or output_hashes != sorted(set(output_hashes))
    ):
        raise ListeningFinalizeError("LISTENING_OUTPUT_HASHES_INVALID")
    required_stability = binding["required_stability_seconds"]
    if (
        type(required_stability) not in {int, float}
        or not math.isfinite(float(required_stability))
        or float(required_stability)
        < FORMAL_MINIMUM_DURATION_MINUTES * 60.0
    ):
        raise ListeningFinalizeError("LISTENING_PROBE_BINDING_INVALID")

    captures = request["required_captures"]
    if type(captures) is not list or len(captures) != len(_EXPECTED_CAPTURES):
        raise ListeningFinalizeError("LISTENING_PROBE_CAPTURES_INVALID")
    normalized_captures: list[tuple[int, int, object]] = []
    for capture_value in captures:
        capture = _require_exact_mapping(
            capture_value,
            frozenset({"width", "height", "assistant_mode"}),
            code="LISTENING_PROBE_CAPTURES_INVALID",
        )
        if (
            type(capture["width"]) is not int
            or type(capture["height"]) is not int
            or type(capture["assistant_mode"]) is not str
        ):
            raise ListeningFinalizeError("LISTENING_PROBE_CAPTURES_INVALID")
        normalized_captures.append(
            (
                capture["width"],
                capture["height"],
                capture["assistant_mode"],
            )
        )
    if tuple(normalized_captures) != _EXPECTED_CAPTURES:
        raise ListeningFinalizeError("LISTENING_PROBE_CAPTURES_INVALID")

    performance = _require_exact_mapping(
        request["performance_seed"],
        frozenset(
            {
                "request_to_ready_seconds",
                "observed_http_first_audio_ms",
                "chapter_audio_duration_seconds",
            }
        ),
        code="LISTENING_PROBE_PERFORMANCE_INVALID",
    )
    request_to_ready = performance["request_to_ready_seconds"]
    first_audio = performance["observed_http_first_audio_ms"]
    chapter_duration = performance["chapter_audio_duration_seconds"]
    if (
        type(request_to_ready) is not list
        or len(request_to_ready) != 2
        or any(
            type(value) not in {int, float}
            or not math.isfinite(float(value))
            or float(value) < 0
            for value in request_to_ready
        )
        or type(first_audio) is not list
        or len(first_audio) != 2
        or any(type(value) is not int or value < 0 for value in first_audio)
        or type(chapter_duration) not in {int, float}
        or not math.isfinite(float(chapter_duration))
        or float(chapter_duration) <= 0
    ):
        raise ListeningFinalizeError("LISTENING_PROBE_PERFORMANCE_INVALID")

    runtime = _require_exact_mapping(
        request["runtime_contract"],
        frozenset({"sidecar_container_name", "range_status_codes"}),
        code="LISTENING_PROBE_RUNTIME_INVALID",
    )
    range_codes = runtime["range_status_codes"]
    if (
        runtime["sidecar_container_name"] != EXPECTED_SIDECAR_CONTAINER_NAME
        or type(range_codes) is not list
        or any(type(item) is not int for item in range_codes)
        or tuple(range_codes) != EXPECTED_RANGE_STATUS_CODES
    ):
        raise ListeningFinalizeError("LISTENING_PROBE_RUNTIME_INVALID")

    fingerprint = request["request_fingerprint_sha256"]
    if not _is_sha256(fingerprint):
        raise ListeningFinalizeError("LISTENING_PROBE_FINGERPRINT_INVALID")
    unsigned = dict(request)
    del unsigned["request_fingerprint_sha256"]
    expected_fingerprint = _sha256_bytes(_canonical_json(unsigned))
    assert isinstance(fingerprint, str)
    if not hmac.compare_digest(fingerprint, expected_fingerprint):
        raise ListeningFinalizeError("LISTENING_PROBE_FINGERPRINT_INVALID")

    run_fingerprint = binding["run_fingerprint_sha256"]
    assert isinstance(run_fingerprint, str)
    return BoundListeningRequest(
        created_at=created_at,
        request_fingerprint_sha256=fingerprint,
        run_fingerprint_sha256=run_fingerprint,
        target_scope_sha256=binding["target_scope_sha256"],  # type: ignore[arg-type]
        automatic_edition_id_sha256=(
            binding["automatic_edition_id_sha256"]  # type: ignore[arg-type]
        ),
        manual_edition_id_sha256=(
            binding["manual_edition_id_sha256"]  # type: ignore[arg-type]
        ),
        automatic_edition_fingerprint_sha256=(
            binding["automatic_edition_fingerprint_sha256"]  # type: ignore[arg-type]
        ),
        manual_edition_fingerprint_sha256=(
            binding["manual_edition_fingerprint_sha256"]  # type: ignore[arg-type]
        ),
        listening_output_hashes=tuple(output_hashes),
    )


def _validated_output_parent(
    listening_record: Path,
    receipt: Path,
) -> tuple[int, Path, os.stat_result]:
    try:
        listening_candidate = Path(listening_record)
        receipt_candidate = Path(receipt)
    except (TypeError, ValueError, OSError):
        raise ListeningFinalizeError("LISTENING_OUTPUT_PATH_UNSAFE") from None
    if (
        listening_candidate.name != LISTENING_RECORD_FILENAME
        or receipt_candidate.name != FINALIZATION_RECEIPT_FILENAME
        or listening_candidate.parent != receipt_candidate.parent
    ):
        raise ListeningFinalizeError("LISTENING_OUTPUT_PATH_UNSAFE")
    _reject_symlink_components(
        listening_candidate,
        allow_missing_final=True,
        code="LISTENING_OUTPUT_PATH_UNSAFE",
    )
    _reject_symlink_components(
        receipt_candidate,
        allow_missing_final=True,
        code="LISTENING_OUTPUT_PATH_UNSAFE",
    )
    return _open_secure_parent(
        listening_candidate.parent,
        code="LISTENING_OUTPUT_PATH_UNSAFE",
    )


def _write_all(file_descriptor: int, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        written = os.write(file_descriptor, data[offset:])
        if written <= 0:
            raise ListeningFinalizeError("LISTENING_WRITE_FAILED")
        offset += written


def _write_exclusive_at(
    parent_descriptor: int,
    filename: str,
    data: bytes,
) -> tuple[int, int]:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise ListeningFinalizeError("LISTENING_WRITE_FAILED")
    file_descriptor: int | None = None
    created_identity: tuple[int, int] | None = None
    completed = False
    try:
        file_descriptor = os.open(
            filename,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | nofollow,
            0o600,
            dir_fd=parent_descriptor,
        )
        opened = os.fstat(file_descriptor)
        created_identity = (opened.st_dev, opened.st_ino)
        os.fchmod(file_descriptor, 0o600)
        _write_all(file_descriptor, data)
        os.fsync(file_descriptor)
        after = os.fstat(file_descriptor)
        if (
            not _same_object(opened, after)
            or not _secure_output_file(after, expected_size=len(data))
        ):
            raise ListeningFinalizeError("LISTENING_WRITE_FAILED")
        completed = True
        return created_identity
    except FileExistsError:
        raise ListeningFinalizeError("LISTENING_FINALIZATION_EXISTS") from None
    except ListeningFinalizeError:
        raise
    except OSError:
        raise ListeningFinalizeError("LISTENING_WRITE_FAILED") from None
    finally:
        if file_descriptor is not None:
            try:
                os.close(file_descriptor)
            except OSError:
                pass
        if not completed and created_identity is not None:
            _unlink_created_if_same(
                parent_descriptor,
                filename,
                created_identity,
            )


def _unlink_created_if_same(
    parent_descriptor: int,
    filename: str,
    identity: tuple[int, int],
) -> None:
    """Best-effort rollback of a file created by this failed invocation."""

    try:
        metadata = os.stat(
            filename,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        if (
            (metadata.st_dev, metadata.st_ino) == identity
            and stat.S_ISREG(metadata.st_mode)
            and metadata.st_uid == os.getuid()
            and metadata.st_nlink == 1
        ):
            os.unlink(filename, dir_fd=parent_descriptor)
    except OSError:
        pass


def _read_exact_file_at(
    parent_descriptor: int,
    filename: str,
    expected: bytes,
    *,
    code: str,
) -> bool:
    """Return False for absence, True for one exact secure immutable file."""

    file_descriptor: int | None = None
    try:
        try:
            before = os.stat(
                filename,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return False
        if not _secure_output_file(before, expected_size=len(expected)):
            raise ListeningFinalizeError(code)
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            raise ListeningFinalizeError(code)
        file_descriptor = os.open(
            filename,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | nofollow,
            dir_fd=parent_descriptor,
        )
        opened = os.fstat(file_descriptor)
        if (
            _file_identity(opened) != _file_identity(before)
            or not _secure_output_file(opened, expected_size=len(expected))
        ):
            raise ListeningFinalizeError(code)
        chunks: list[bytes] = []
        remaining = len(expected)
        while remaining:
            chunk = os.read(file_descriptor, min(remaining, 16 * 1024))
            if not chunk:
                raise ListeningFinalizeError(code)
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(file_descriptor, 1):
            raise ListeningFinalizeError(code)
        after = os.fstat(file_descriptor)
        path_after = os.stat(
            filename,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        if (
            _file_identity(after) != _file_identity(opened)
            or _file_identity(path_after) != _file_identity(opened)
            or not hmac.compare_digest(b"".join(chunks), expected)
        ):
            raise ListeningFinalizeError(code)
        return True
    except ListeningFinalizeError:
        raise
    except OSError:
        raise ListeningFinalizeError(code) from None
    finally:
        if file_descriptor is not None:
            try:
                os.close(file_descriptor)
            except OSError:
                pass


def _read_registry_document_at(
    registry_descriptor: int,
    filename: str,
    *,
    code: str,
) -> tuple[bytes, Mapping[str, object]] | None:
    file_descriptor: int | None = None
    try:
        try:
            before = os.stat(
                filename,
                dir_fd=registry_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return None
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or before.st_uid != os.getuid()
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size <= 0
            or before.st_size > MAX_REGISTRY_DOCUMENT_BYTES
        ):
            raise ListeningFinalizeError(code)
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            raise ListeningFinalizeError(code)
        file_descriptor = os.open(
            filename,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | nofollow,
            dir_fd=registry_descriptor,
        )
        opened = os.fstat(file_descriptor)
        if _file_identity(opened) != _file_identity(before):
            raise ListeningFinalizeError(code)
        chunks: list[bytes] = []
        remaining = opened.st_size
        while remaining:
            chunk = os.read(file_descriptor, min(remaining, 16 * 1024))
            if not chunk:
                raise ListeningFinalizeError(code)
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(file_descriptor, 1):
            raise ListeningFinalizeError(code)
        after = os.fstat(file_descriptor)
        path_after = os.stat(
            filename,
            dir_fd=registry_descriptor,
            follow_symlinks=False,
        )
        if (
            _file_identity(after) != _file_identity(opened)
            or _file_identity(path_after) != _file_identity(opened)
        ):
            raise ListeningFinalizeError(code)
        raw = b"".join(chunks)
        try:
            value = json.loads(
                raw.decode("utf-8", errors="strict"),
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_nonfinite_json,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            raise ListeningFinalizeError(code) from None
        if type(value) is not dict:
            raise ListeningFinalizeError(code)
        return raw, value
    except ListeningFinalizeError:
        raise
    except OSError:
        raise ListeningFinalizeError(code) from None
    finally:
        if file_descriptor is not None:
            try:
                os.close(file_descriptor)
            except OSError:
                pass


def _seal_document(payload: Mapping[str, object]) -> dict[str, object]:
    unsigned = dict(payload)
    if "self_sha256" in unsigned:
        raise ListeningFinalizeError("LISTENING_INTERNAL_ERROR")
    return {
        **unsigned,
        "self_sha256": _sha256_bytes(_canonical_json(unsigned)),
    }


def _validate_self_digest(
    payload: Mapping[str, object],
    *,
    code: str,
) -> None:
    digest = payload.get("self_sha256")
    if not _is_sha256(digest):
        raise ListeningFinalizeError(code)
    unsigned = dict(payload)
    del unsigned["self_sha256"]
    expected = _sha256_bytes(_canonical_json(unsigned))
    assert isinstance(digest, str)
    if not hmac.compare_digest(digest, expected):
        raise ListeningFinalizeError(code)


def _output_directory_bindings(
    resolved_parent: Path,
    metadata: os.stat_result,
) -> tuple[str, str]:
    canonical = _sha256_bytes(str(resolved_parent).encode("utf-8"))
    identity = _sha256_bytes(
        _canonical_json(
            {
                "st_dev": metadata.st_dev,
                "st_ino": metadata.st_ino,
                "st_uid": metadata.st_uid,
                "st_mode": metadata.st_mode,
            }
        )
    )
    return canonical, identity


def _assert_directory_path_stable(
    resolved_path: Path,
    descriptor: int,
    opened: os.stat_result,
    *,
    code: str,
) -> None:
    try:
        descriptor_metadata = os.fstat(descriptor)
        path_metadata = resolved_path.lstat()
        resolved_again = resolved_path.resolve(strict=True)
        resolved_metadata = resolved_again.lstat()
    except OSError:
        raise ListeningFinalizeError(code) from None
    if (
        resolved_again != resolved_path
        or not _same_object(descriptor_metadata, opened)
        or not _same_object(path_metadata, opened)
        or not _same_object(resolved_metadata, opened)
        or not _secure_parent(descriptor_metadata)
        or not _secure_parent(path_metadata)
        or not _secure_parent(resolved_metadata)
    ):
        raise ListeningFinalizeError(code)


def _ensure_names_absent(
    parent_descriptor: int,
    filenames: tuple[str, ...],
    *,
    code: str,
) -> None:
    for filename in filenames:
        try:
            os.stat(
                filename,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            continue
        except OSError:
            raise ListeningFinalizeError(code) from None
        raise ListeningFinalizeError(code)


def _build_output_documents(
    bound: BoundListeningRequest,
    *,
    reviewer_pseudonym: str,
    reviewed_at: str,
    verdict: str,
    checks: Mapping[str, bool],
) -> tuple[bytes, bytes]:
    ordered_checks = {name: checks[name] for name in CHECK_NAMES}
    record: dict[str, object] = {
        "schema_version": LISTENING_SCHEMA,
        "reviewer_pseudonym": reviewer_pseudonym,
        "reviewed_at": reviewed_at,
        "verdict": verdict,
        "output_hashes": list(bound.listening_output_hashes),
        "checks": ordered_checks,
    }
    record_data = _canonical_json(record) + b"\n"
    receipt_payload: dict[str, object] = {
        "schema_version": FINALIZATION_RECEIPT_SCHEMA,
        "finalized_at": reviewed_at,
        "verdict": verdict,
        "probe_request_fingerprint_sha256": (
            bound.request_fingerprint_sha256
        ),
        "run_fingerprint_sha256": bound.run_fingerprint_sha256,
        "target_scope_sha256": bound.target_scope_sha256,
        "automatic_edition_id_sha256": (
            bound.automatic_edition_id_sha256
        ),
        "manual_edition_id_sha256": bound.manual_edition_id_sha256,
        "automatic_edition_fingerprint_sha256": (
            bound.automatic_edition_fingerprint_sha256
        ),
        "manual_edition_fingerprint_sha256": (
            bound.manual_edition_fingerprint_sha256
        ),
        "listening_record_sha256": _sha256_bytes(record_data),
        "reviewed_roles": list(REVIEWED_ROLES),
    }
    return record_data, _canonical_json(receipt_payload) + b"\n"


def _validated_claim(
    value: Mapping[str, object],
    *,
    bound: BoundListeningRequest,
    verdict: str,
    output_canonical_sha256: str,
    output_identity_sha256: str,
    now: datetime,
    max_request_age: timedelta,
    max_future_skew: timedelta,
) -> str:
    claim = _require_exact_mapping(
        value,
        _CLAIM_KEYS,
        code="LISTENING_CLAIM_INVALID",
    )
    _validate_self_digest(claim, code="LISTENING_CLAIM_INVALID")
    claimed_at_value = claim["claimed_at"]
    try:
        claimed_at = _parse_utc_timestamp(claimed_at_value)
    except ListeningFinalizeError:
        raise ListeningFinalizeError("LISTENING_CLAIM_INVALID") from None
    expected = {
        "schema_version": LISTENING_CLAIM_SCHEMA,
        "state": "PREPARED",
        "verdict": verdict,
        "probe_request_fingerprint_sha256": (
            bound.request_fingerprint_sha256
        ),
        "run_fingerprint_sha256": bound.run_fingerprint_sha256,
        "target_scope_sha256": bound.target_scope_sha256,
        "automatic_edition_id_sha256": (
            bound.automatic_edition_id_sha256
        ),
        "manual_edition_id_sha256": bound.manual_edition_id_sha256,
        "automatic_edition_fingerprint_sha256": (
            bound.automatic_edition_fingerprint_sha256
        ),
        "manual_edition_fingerprint_sha256": (
            bound.manual_edition_fingerprint_sha256
        ),
        "output_directory_canonical_sha256": output_canonical_sha256,
        "output_directory_identity_sha256": output_identity_sha256,
    }
    if (
        claimed_at > now + max_future_skew
        or claimed_at < bound.created_at - max_future_skew
        or claimed_at > bound.created_at + max_request_age
        or any(claim.get(key) != expected_value for key, expected_value in expected.items())
        or not _is_sha256(claim.get("listening_record_sha256"))
        or not _is_sha256(claim.get("finalization_receipt_sha256"))
    ):
        raise ListeningFinalizeError("LISTENING_FINALIZATION_CONFLICT")
    assert isinstance(claimed_at_value, str)
    return claimed_at_value


def _publish_or_accept_outputs(
    parent_descriptor: int,
    opened_parent: os.stat_result,
    *,
    record_data: bytes,
    receipt_data: bytes,
) -> tuple[tuple[str, tuple[int, int]], ...]:
    created: list[tuple[str, tuple[int, int]]] = []
    for filename, data in (
        (FINALIZATION_RECEIPT_FILENAME, receipt_data),
        (LISTENING_RECORD_FILENAME, record_data),
    ):
        if _read_exact_file_at(
            parent_descriptor,
            filename,
            data,
            code="LISTENING_FINALIZATION_CONFLICT",
        ):
            continue
        identity = _write_exclusive_at(parent_descriptor, filename, data)
        created.append((filename, identity))
    parent_after = os.fstat(parent_descriptor)
    if (
        not _same_object(parent_after, opened_parent)
        or not _secure_parent(parent_after)
    ):
        raise ListeningFinalizeError("LISTENING_WRITE_FAILED")
    os.fsync(parent_descriptor)
    return tuple(created)


def _finalize_transaction(
    bound: BoundListeningRequest,
    listening_record: Path,
    receipt: Path,
    *,
    proposed_reviewed_at: str,
    reviewer_pseudonym: str,
    verdict: str,
    checks: Mapping[str, bool],
    now: datetime,
    max_request_age: timedelta,
    max_future_skew: timedelta,
) -> None:
    """Durably prepare, resume, and commit one exact author decision."""

    registry_descriptor: int | None = None
    lock_descriptor: int | None = None
    output_descriptor: int | None = None
    created_claim: tuple[int, int] | None = None
    created_commit: tuple[int, int] | None = None
    created_outputs: tuple[tuple[str, tuple[int, int]], ...] = ()
    path_integrity_failed = False
    claim_name = f"{bound.run_fingerprint_sha256}.claim"
    commit_name = f"{bound.run_fingerprint_sha256}.commit"
    lock_name = f"{bound.run_fingerprint_sha256}.lock"
    try:
        output_descriptor, resolved_output, opened_output = (
            _validated_output_parent(listening_record, receipt)
        )
        output_canonical, output_identity = _output_directory_bindings(
            resolved_output,
            opened_output,
        )
        registry_descriptor, _resolved_registry, opened_registry = (
            _open_or_create_claim_registry()
        )

        def assert_paths_stable() -> None:
            nonlocal path_integrity_failed
            try:
                assert output_descriptor is not None
                assert registry_descriptor is not None
                _assert_directory_path_stable(
                    resolved_output,
                    output_descriptor,
                    opened_output,
                    code="LISTENING_OUTPUT_PATH_UNSAFE",
                )
                _assert_directory_path_stable(
                    _resolved_registry,
                    registry_descriptor,
                    opened_registry,
                    code="LISTENING_CLAIM_REGISTRY_UNSAFE",
                )
            except ListeningFinalizeError:
                path_integrity_failed = True
                raise

        assert_paths_stable()
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            raise ListeningFinalizeError("LISTENING_CLAIM_REGISTRY_UNSAFE")
        lock_descriptor = os.open(
            lock_name,
            os.O_RDWR
            | os.O_CREAT
            | getattr(os, "O_CLOEXEC", 0)
            | nofollow,
            0o600,
            dir_fd=registry_descriptor,
        )
        lock_metadata = os.fstat(lock_descriptor)
        lock_path_metadata = os.stat(
            lock_name,
            dir_fd=registry_descriptor,
            follow_symlinks=False,
        )
        if (
            not _same_object(lock_metadata, lock_path_metadata)
            or not _secure_output_file(
                lock_metadata,
                expected_size=lock_metadata.st_size,
            )
        ):
            raise ListeningFinalizeError("LISTENING_CLAIM_REGISTRY_UNSAFE")
        try:
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ListeningFinalizeError("LISTENING_DECISION_BUSY") from None
        assert_paths_stable()

        loaded_claim = _read_registry_document_at(
            registry_descriptor,
            claim_name,
            code="LISTENING_CLAIM_INVALID",
        )
        if loaded_claim is None:
            if now - bound.created_at > max_request_age:
                raise ListeningFinalizeError(
                    "LISTENING_PROBE_REQUEST_EXPIRED"
                )
            _ensure_names_absent(
                output_descriptor,
                (
                    FINALIZATION_RECEIPT_FILENAME,
                    LISTENING_RECORD_FILENAME,
                ),
                code="LISTENING_FINALIZATION_EXISTS",
            )
            _ensure_names_absent(
                registry_descriptor,
                (commit_name,),
                code="LISTENING_CLAIM_INVALID",
            )
            reviewed_at = proposed_reviewed_at
            record_data, receipt_data = _build_output_documents(
                bound,
                reviewer_pseudonym=reviewer_pseudonym,
                reviewed_at=reviewed_at,
                verdict=verdict,
                checks=checks,
            )
            claim = _seal_document(
                {
                    "schema_version": LISTENING_CLAIM_SCHEMA,
                    "state": "PREPARED",
                    "claimed_at": reviewed_at,
                    "verdict": verdict,
                    "probe_request_fingerprint_sha256": (
                        bound.request_fingerprint_sha256
                    ),
                    "run_fingerprint_sha256": bound.run_fingerprint_sha256,
                    "target_scope_sha256": bound.target_scope_sha256,
                    "automatic_edition_id_sha256": (
                        bound.automatic_edition_id_sha256
                    ),
                    "manual_edition_id_sha256": (
                        bound.manual_edition_id_sha256
                    ),
                    "automatic_edition_fingerprint_sha256": (
                        bound.automatic_edition_fingerprint_sha256
                    ),
                    "manual_edition_fingerprint_sha256": (
                        bound.manual_edition_fingerprint_sha256
                    ),
                    "listening_record_sha256": _sha256_bytes(record_data),
                    "finalization_receipt_sha256": _sha256_bytes(receipt_data),
                    "output_directory_canonical_sha256": output_canonical,
                    "output_directory_identity_sha256": output_identity,
                }
            )
            raw_claim = _canonical_json(claim) + b"\n"
            created_claim = _write_exclusive_at(
                registry_descriptor,
                claim_name,
                raw_claim,
            )
            os.fsync(registry_descriptor)
        else:
            raw_claim, claim = loaded_claim
            reviewed_at = _validated_claim(
                claim,
                bound=bound,
                verdict=verdict,
                output_canonical_sha256=output_canonical,
                output_identity_sha256=output_identity,
                now=now,
                max_request_age=max_request_age,
                max_future_skew=max_future_skew,
            )
            record_data, receipt_data = _build_output_documents(
                bound,
                reviewer_pseudonym=reviewer_pseudonym,
                reviewed_at=reviewed_at,
                verdict=verdict,
                checks=checks,
            )
            if (
                claim["listening_record_sha256"]
                != _sha256_bytes(record_data)
                or claim["finalization_receipt_sha256"]
                != _sha256_bytes(receipt_data)
            ):
                raise ListeningFinalizeError(
                    "LISTENING_FINALIZATION_CONFLICT"
                )

        assert_paths_stable()
        created_outputs = _publish_or_accept_outputs(
            output_descriptor,
            opened_output,
            record_data=record_data,
            receipt_data=receipt_data,
        )
        assert_paths_stable()
        commit = _seal_document(
            {
                "schema_version": LISTENING_COMMIT_SCHEMA,
                "state": "COMMITTED",
                "committed_at": reviewed_at,
                "claim_sha256": _sha256_bytes(raw_claim),
                "run_fingerprint_sha256": bound.run_fingerprint_sha256,
                "listening_record_sha256": _sha256_bytes(record_data),
                "finalization_receipt_sha256": _sha256_bytes(receipt_data),
                "output_directory_canonical_sha256": output_canonical,
                "output_directory_identity_sha256": output_identity,
            }
        )
        raw_commit = _canonical_json(commit) + b"\n"
        loaded_commit = _read_registry_document_at(
            registry_descriptor,
            commit_name,
            code="LISTENING_COMMIT_INVALID",
        )
        if loaded_commit is None:
            created_commit = _write_exclusive_at(
                registry_descriptor,
                commit_name,
                raw_commit,
            )
            os.fsync(registry_descriptor)
        else:
            existing_raw, existing_commit = loaded_commit
            _require_exact_mapping(
                existing_commit,
                _COMMIT_KEYS,
                code="LISTENING_COMMIT_INVALID",
            )
            _validate_self_digest(
                existing_commit,
                code="LISTENING_COMMIT_INVALID",
            )
            if not hmac.compare_digest(existing_raw, raw_commit):
                raise ListeningFinalizeError("LISTENING_COMMIT_INVALID")
        assert_paths_stable()
    except ListeningFinalizeError:
        if path_integrity_failed:
            if registry_descriptor is not None:
                if created_commit is not None:
                    _unlink_created_if_same(
                        registry_descriptor,
                        commit_name,
                        created_commit,
                    )
                if created_claim is not None:
                    _unlink_created_if_same(
                        registry_descriptor,
                        claim_name,
                        created_claim,
                    )
                try:
                    os.fsync(registry_descriptor)
                except OSError:
                    pass
            if output_descriptor is not None:
                for filename, identity in reversed(created_outputs):
                    _unlink_created_if_same(
                        output_descriptor,
                        filename,
                        identity,
                    )
                try:
                    os.fsync(output_descriptor)
                except OSError:
                    pass
        raise
    except OSError:
        raise ListeningFinalizeError("LISTENING_WRITE_FAILED") from None
    finally:
        if lock_descriptor is not None:
            try:
                fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(lock_descriptor)
            except OSError:
                pass
        if registry_descriptor is not None:
            try:
                os.close(registry_descriptor)
            except OSError:
                pass
        if output_descriptor is not None:
            try:
                os.close(output_descriptor)
            except OSError:
                pass


class ListeningFinalizer:
    """Validate one probe request and persist one explicit human decision."""

    def __init__(
        self,
        *,
        now: Callable[[], datetime] | None = None,
        max_request_age_seconds: int = DEFAULT_MAX_REQUEST_AGE_SECONDS,
        max_future_skew_seconds: int = DEFAULT_MAX_FUTURE_SKEW_SECONDS,
    ) -> None:
        if (
            (now is not None and not callable(now))
            or type(max_request_age_seconds) is not int
            or max_request_age_seconds <= 0
            or type(max_future_skew_seconds) is not int
            or max_future_skew_seconds < 0
        ):
            raise ListeningFinalizeError("LISTENING_POLICY_INVALID")
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._max_age = timedelta(seconds=max_request_age_seconds)
        self._max_future_skew = timedelta(seconds=max_future_skew_seconds)

    def finalize(
        self,
        probe_request: Path,
        listening_record: Path,
        receipt: Path,
        *,
        reviewer_pseudonym: str,
        verdict: Literal["pass", "fail"],
        checks: Mapping[str, bool],
        confirmation: str,
    ) -> None:
        if (
            type(reviewer_pseudonym) is not str
            or not SAFE_ID_PATTERN.fullmatch(reviewer_pseudonym)
            or verdict not in {"pass", "fail"}
            or confirmation != HUMAN_LISTENING_CONFIRMATION
            or type(checks) is not dict
            or frozenset(checks) != frozenset(CHECK_NAMES)
            or any(type(checks[name]) is not bool for name in CHECK_NAMES)
        ):
            raise ListeningFinalizeError("LISTENING_REVIEW_INVALID")
        if verdict == "pass" and not all(checks[name] for name in CHECK_NAMES):
            raise ListeningFinalizeError(
                "LISTENING_PASS_REQUIRES_ALL_YES"
            )

        current = self._now()
        if type(current) is not datetime or current.tzinfo is None:
            raise ListeningFinalizeError("LISTENING_TIME_INVALID")
        current = current.astimezone(timezone.utc)
        raw_request = _read_secure_probe_request(probe_request)
        bound = _parse_probe_request(
            raw_request,
            now=current,
            max_age=self._max_age,
            max_future_skew=self._max_future_skew,
            allow_expired_prepared_recovery=True,
        )
        reviewed_at = current.replace(microsecond=0).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        _finalize_transaction(
            bound,
            listening_record,
            receipt,
            proposed_reviewed_at=reviewed_at,
            reviewer_pseudonym=reviewer_pseudonym,
            verdict=verdict,
            checks=checks,
            now=current,
            max_request_age=self._max_age,
            max_future_skew=self._max_future_skew,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(
        description="Finalize one explicit T4-K human listening decision.",
        allow_abbrev=False,
    )
    parser.add_argument("--mode", required=True)
    parser.add_argument("--probe-request-file", required=True)
    parser.add_argument("--listening-record", required=True)
    parser.add_argument("--finalization-receipt", required=True)
    parser.add_argument("--reviewer-pseudonym", required=True)
    parser.add_argument("--verdict", required=True)
    parser.add_argument(
        "--narrator-character-distinguishable",
        required=True,
    )
    parser.add_argument("--voices-stable", required=True)
    parser.add_argument("--no-missing-or-repeated-text", required=True)
    parser.add_argument("--all-samples-intelligible-mandarin", required=True)
    parser.add_argument("--no-abnormal-pause-or-seam", required=True)
    parser.add_argument("--loudness-consistent", required=True)
    parser.add_argument("--confirm-human-listening", required=True)
    return parser


def _yes_no(value: object) -> bool:
    if value == "yes":
        return True
    if value == "no":
        return False
    raise ListeningFinalizeError("LISTENING_REVIEW_INVALID")


def main(
    argv: list[str] | None = None,
    *,
    finalizer: ListeningFinalizer | None = None,
) -> int:
    try:
        args = build_parser().parse_args(argv)
        if args.mode != "finalize":
            raise ListeningFinalizeError("LISTENING_MODE_INVALID")
        reviewer = args.reviewer_pseudonym
        verdict = args.verdict
        confirmation = args.confirm_human_listening
        checks = {
            "narrator_character_distinguishable": _yes_no(
                args.narrator_character_distinguishable
            ),
            "voices_stable": _yes_no(args.voices_stable),
            "no_missing_or_repeated_text": _yes_no(
                args.no_missing_or_repeated_text
            ),
            "all_samples_intelligible_mandarin": _yes_no(
                args.all_samples_intelligible_mandarin
            ),
            "no_abnormal_pause_or_seam": _yes_no(
                args.no_abnormal_pause_or_seam
            ),
            "loudness_consistent": _yes_no(args.loudness_consistent),
        }
        (finalizer or ListeningFinalizer()).finalize(
            Path(args.probe_request_file),
            Path(args.listening_record),
            Path(args.finalization_receipt),
            reviewer_pseudonym=reviewer,
            verdict=verdict,
            checks=checks,
            confirmation=confirmation,
        )
    except ListeningFinalizeError as error:
        print(error.code, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("LISTENING_INTERRUPTED", file=sys.stderr)
        return 130
    except SystemExit as error:
        # ``argparse`` uses SystemExit(0) for the standard help path. Parser
        # errors are already converted to ListeningFinalizeError above.
        return error.code if type(error.code) is int else 0
    except BaseException:
        print("LISTENING_INTERNAL_ERROR", file=sys.stderr)
        return 2
    print("LISTENING_FINALIZED")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "CHECK_NAMES",
    "DEFAULT_MAX_FUTURE_SKEW_SECONDS",
    "DEFAULT_MAX_REQUEST_AGE_SECONDS",
    "FINALIZATION_RECEIPT_FILENAME",
    "FINALIZATION_RECEIPT_SCHEMA",
    "HUMAN_LISTENING_CONFIRMATION",
    "LEGACY_LISTENING_SCHEMA",
    "LISTENING_CLAIM_SCHEMA",
    "LISTENING_RECORD_FILENAME",
    "LISTENING_SCHEMA",
    "ListeningFinalizeError",
    "ListeningFinalizer",
    "REVIEWED_ROLES",
    "build_parser",
    "main",
]
