#!/usr/bin/env python3
"""Validate and orchestrate the guarded T4-K chapter acceptance contract.

The command is deliberately fail-closed.  Its default ``validate-only`` mode
validates an authorized chapter fixture and writes redacted evidence without
opening a network connection.  ``real`` mode additionally requires two exact
operator confirmations and an injected execution backend.  Invoking this
validator directly therefore cannot mutate a chapter; the separately owned
launcher must inject the fixed executor and its browser/runtime probes.

An execution backend must capture a complete baseline before its first write.
This runner persists that baseline in a 0600 recovery record outside the
repository, updates the record at every phase boundary, and attempts restoration
for success, failure, and interruption.  Evidence receives hashes and aggregate
metrics only: never chapter text, secrets, audio bytes, or private paths.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from typing import Callable, Final, Literal, Mapping, Protocol, Sequence
import unicodedata
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4


REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
CURRENT_PAWAPP_ROOT: Final = Path(__file__).resolve().parents[2]
FIXTURE_SCHEMA: Final = "moss-tts-chapter-e2e-fixture/2.1"
RESULT_SCHEMA: Final = "moss-tts-chapter-e2e-result/2.3"
LEGACY_RECOVERY_SCHEMA: Final = "moss-tts-chapter-e2e-recovery/3.0"
PREVIOUS_RECOVERY_SCHEMA: Final = "moss-tts-chapter-e2e-recovery/3.1"
RECOVERY_SCHEMA: Final = "moss-tts-chapter-e2e-recovery/3.2"
LISTENING_SCHEMA: Final = "moss-tts-chapter-listening/1.1"
LISTENING_FINALIZATION_RECEIPT_SCHEMA: Final = (
    "moss-tts-chapter-listening-finalization-receipt/1.2"
)
LISTENING_FINALIZATION_RECEIPT_FILENAME: Final = (
    "listening-finalization-receipt.json"
)
LISTENING_CLAIM_SCHEMA: Final = "moss-tts-chapter-listening-claim/1.2"
LISTENING_COMMIT_SCHEMA: Final = "moss-tts-chapter-listening-commit/1.0"
LISTENING_CLAIM_REGISTRY_DIRECTORY: Final = Path(
    "/app/working.secret/ai-novel-world-2026/t4k-listening-claims"
)
WORK_PACKAGE: Final = "T4-K"
FORMAL_MINIMUM_DURATION_MINUTES: Final = 30.0
FORMAL_MINIMUM_CHAPTER_CODEPOINTS: Final = 500
BLACK_BOX_RTF_LIMIT: Final = 1.0
SIDECAR_PEAK_MEMORY_LIMIT_BYTES: Final = 4 * 1024 * 1024 * 1024
SIDECAR_MEMORY_GROWTH_MIN_LIMIT_BYTES: Final = 128 * 1024 * 1024
SIDECAR_MEMORY_GROWTH_PERCENT_NUMERATOR: Final = 5
SIDECAR_MEMORY_GROWTH_PERCENT_DENOMINATOR: Final = 100
ALLOWED_VIEWPORTS: Final = ((1920, 1080), (2560, 1440))
REAL_RUN_CONFIRMATION: Final = "RUN-T4-K-REAL-CHAPTER"
RESTORE_CONFIRMATION: Final = "RESTORE-T4-K-BASELINE"
PRIVATE_WORK_DIR_CONFIRMATION: Final = "PRIVATE-WORK-DIR-LOCAL-NON-SYNCED"
API_PATH: Final = "/api/ai-novel-world-2026"
LOOPBACK_HOSTS: Final = frozenset({"127.0.0.1", "::1", "localhost"})
SHA256_PATTERN: Final = re.compile(r"^[a-f0-9]{64}$")
SAFE_ID_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
SAFE_CODE_PATTERN: Final = re.compile(r"^[A-Z][A-Z0-9_]{1,95}$")
MAX_SOURCE_CODEPOINTS: Final = 1_000_000
MAX_SPOKEN_CODEPOINTS: Final = 4_000
MAX_FIXTURE_BYTES: Final = 8 * 1024 * 1024
MAX_RECOVERY_BYTES: Final = 8 * 1024 * 1024
LISTENING_AUTHORIZATION_MAX_SECONDS: Final = 4 * 60 * 60
ALLOWED_BLOCKER_CODES: Final = frozenset(
    {
        "B_SPEAKER_UNKNOWN",
        "B_SPEAKER_LOW_CONFIDENCE",
        "B_CHARACTER_ALIAS_CONFLICT",
        "B_CHARACTER_REFERENCE_INVALID",
        "B_ANONYMOUS_IDENTITY_CONFLICT",
        "B_CASTING_TARGET_UNRESOLVED",
        "B_VOICE_MISSING",
        "B_VOICE_VERSION_UNAVAILABLE",
        "B_VOICE_RIGHTS_UNAVAILABLE",
        "B_PRONUNCIATION_HARD_CONFLICT",
        "B_CLOUD_DECISION_UNAVAILABLE",
    }
)


class RunnerError(RuntimeError):
    """A stable, redacted runner error safe for evidence and stderr."""

    def __init__(self, code: str):
        if not SAFE_CODE_PATTERN.fullmatch(code):
            raise ValueError("runner error code must be stable")
        super().__init__(code)
        self.code = code


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # pragma: no cover - argparse owns text
        del message
        raise RunnerError("ARGUMENTS_INVALID")


@dataclass(frozen=True, slots=True)
class Correction:
    segment_ordinal: int
    expected_source_local_hash: str
    expected_source_start_utf16: int
    expected_source_end_utf16: int
    speaker_kind: Literal["narrator", "character", "anonymous"]
    speaker_label: str
    spoken_text: str
    reason: str


@dataclass(frozen=True, slots=True)
class ChapterCase:
    case_id: str
    mode: Literal["automatic_zero_blockers", "manual_blocker_resolution"]
    source_text: str
    source_sha256: str
    review_policy: Literal["blockers_only"]
    expected_initial_blocker_codes: tuple[str, ...]
    corrections: tuple[Correction, ...]


@dataclass(frozen=True, slots=True)
class ChapterFixture:
    fixture_id: str
    manifest_sha256: str
    authorization_reference: str
    voice_scope: Literal[
        "isolated_test_only", "local_personal_use", "production_approved"
    ]
    production_eligible: bool
    commercial_distribution_status: Literal["not_evaluated"]
    minimum_character_speakers: int
    minimum_distinct_voice_versions: int
    expected_formal_speakers: tuple[str, ...]
    require_uncached_nano_model_run: bool
    restoration_policy: Literal["dedicated_append_only_author_visible"]
    automatic: ChapterCase
    manual: ChapterCase
    required_viewports: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class RunnerConfig:
    run_id: UUID
    mode: Literal["validate-only", "real"]
    fixture_manifest: Path
    api_base: str
    novel_id: UUID
    document_id: UUID
    automatic_case_id: str
    manual_case_id: str
    private_work_dir: Path
    output_dir: Path
    duration_minutes: float
    listening_record: Path | None
    resume: bool
    expected_formal_speakers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BaselineSnapshot:
    draft_version: int
    content_hash: str
    content_markdown: str
    base_revision_id: UUID | None
    pointer_version: int
    current_edition_id: UUID
    current_script_version_id: UUID
    edition_history_count: int


@dataclass(frozen=True, slots=True)
class RecoveryFence:
    """Exact last state owned by this run before a recovery write."""

    draft_version: int
    content_hash: str
    current_edition_id: UUID
    current_script_version_id: UUID
    pointer_version: int


@dataclass(frozen=True, slots=True)
class RecoveryWriteIntent:
    """Durable write-ahead proof for one potentially committed authority write."""

    operation_kind: str
    operation_fingerprint_sha256: str
    old_fence: RecoveryFence
    next_fence: RecoveryFence


@dataclass(frozen=True, slots=True)
class RecoveryClaimBinding:
    """Digest-only binding supplied by the fixed operator-claim lease."""

    claim_identity_sha256: str
    envelope_fingerprint_sha256: str
    private_work_dir_canonical_sha256: str
    private_work_dir_identity_sha256: str


@dataclass(frozen=True, slots=True)
class RecoveryClaimSnapshot:
    """Mutable claim head observed while its per-run flock is held."""

    state: str
    recovery_generation: int
    latest_recovery_sha256: str | None


@dataclass(frozen=True, slots=True)
class LoadedRecovery:
    schema_version: str
    run_id: str
    state: str
    baseline: BaselineSnapshot
    fence: RecoveryFence
    write_intent: RecoveryWriteIntent | None
    completed_steps: tuple[str, ...]
    baseline_restored: bool
    restoration_evidence: Mapping[str, object] | None
    sealed_technical_result: Mapping[str, object] | None
    sealed_final_result: Mapping[str, object] | None
    generation: int
    previous_record_sha256: str | None
    record_sha256: str


@dataclass(frozen=True, slots=True)
class ChainOutcome:
    request_id: UUID
    script_version_id: UUID
    edition_id: UUID
    edition_fingerprint: str
    approval_kind: Literal["auto_no_blockers", "manual_after_review"]
    initial_blocker_count: int
    final_blocker_count: int
    edition_count_for_request: int
    manifest_revision: int
    narrator_segment_count: int
    character_segment_count: int
    distinct_character_count: int
    distinct_voice_version_count: int
    uncached_nano_job_count: int
    model_run_fingerprints: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TechnicalOutcome:
    stability_elapsed_seconds: float
    chapter_audio_duration_seconds: float
    request_to_ready_seconds: float
    time_to_first_audio_ms: int
    peak_memory_bytes: int
    range_status_codes: tuple[int, ...]
    seam_pairs_checked: int
    seek_latest_wins: bool
    pending_gap_not_skipped: bool
    edit_actions_created_tts_writes: int
    browser_viewports: tuple[tuple[int, int], ...]
    browser_assistant_modes: tuple[Literal["collapsed", "expanded"], ...]
    browser_console_error_count: int
    browser_overlap_count: int
    sidecar_restart_count: int
    health_failure_count: int
    listening_output_hashes: tuple[str, ...]
    collector_collected_at: str
    # Optional additions keep older executor construction source-compatible,
    # while the formal gate remains fail-closed until the trusted collector
    # supplies the two host-safety observations.  The progressive flag is
    # reserved for a future strictly bound ready-window proof; it is not an
    # RTF override by itself.
    progressive_playback_gate_passed: bool | None = None
    host_paging_observed: bool | None = None
    pageout_delta: int | None = None
    swapout_delta: int | None = None
    memory_baseline_median_bytes: int | None = None
    memory_tail_median_bytes: int | None = None
    memory_growth_bytes: int | None = None
    memory_growth_limit_bytes: int | None = None
    sidecar_memory_growth_observed: bool | None = None
    qwenpaw_slowdown_observed: bool | None = None
    evidence_class: str | None = None
    evidence_root_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class RecoveryOutcome:
    restored_draft_version: int
    restored_content_hash: str
    restored_current_edition_id: UUID
    restored_current_script_version_id: UUID
    pointer_version_after_restore: int
    append_only_history_retained: bool
    new_authoritative_record_count: int


class ChapterE2EExecutor(Protocol):
    """Write-capable adapter supplied only by a separately approved owner."""

    def capture_baseline(self, config: RunnerConfig) -> BaselineSnapshot: ...

    def set_recovery_checkpoint(
        self,
        checkpoint: Callable[
            [RecoveryFence, RecoveryWriteIntent | None],
            None,
        ],
    ) -> None: ...

    def run_automatic(
        self,
        config: RunnerConfig,
        case: ChapterCase,
    ) -> ChainOutcome: ...

    def run_manual(
        self,
        config: RunnerConfig,
        case: ChapterCase,
    ) -> ChainOutcome: ...

    def run_technical_checks(
        self,
        config: RunnerConfig,
        fixture: ChapterFixture,
    ) -> TechnicalOutcome: ...

    def capture_recovery_fence(
        self,
        config: RunnerConfig,
    ) -> RecoveryFence: ...

    def restore_baseline(
        self,
        config: RunnerConfig,
        baseline: BaselineSnapshot,
        fence: RecoveryFence,
        write_intent: RecoveryWriteIntent | None,
    ) -> RecoveryOutcome: ...


class ChapterE2ERecoveryExecutor(Protocol):
    """Restore-only port; resume must not construct the normal write executor."""

    def set_recovery_checkpoint(
        self,
        checkpoint: Callable[
            [RecoveryFence, RecoveryWriteIntent | None],
            None,
        ],
    ) -> None: ...

    def restore_baseline(
        self,
        config: RunnerConfig,
        baseline: BaselineSnapshot,
        fence: RecoveryFence,
        write_intent: RecoveryWriteIntent | None,
    ) -> RecoveryOutcome: ...


ExecutorFactory = Callable[[RunnerConfig], ChapterE2EExecutor]
RecoveryExecutorFactory = Callable[[RunnerConfig], ChapterE2ERecoveryExecutor]
RecoveryStateObserver = Callable[[str, int, str], None]
RecoveryClaimStateReader = Callable[[], RecoveryClaimSnapshot]


@dataclass(slots=True)
class _RecoveryRecordCursor:
    """In-process head of the canonical, append-linked recovery record."""

    generation: int = 0
    record_sha256: str | None = None

    @classmethod
    def from_loaded(cls, loaded: LoadedRecovery) -> _RecoveryRecordCursor:
        return cls(
            generation=loaded.generation,
            record_sha256=loaded.record_sha256,
        )

    def next_metadata(self) -> tuple[int, str | None]:
        return self.generation + 1, self.record_sha256

    def committed(self, payload: Mapping[str, object]) -> None:
        generation = payload.get("generation")
        previous = payload.get("previous_record_sha256")
        expected_generation, expected_previous = self.next_metadata()
        if (
            type(generation) is not int
            or generation != expected_generation
            or previous != expected_previous
        ):
            raise RunnerError("RECOVERY_RECORD_INVALID")
        self.generation = generation
        self.record_sha256 = _recovery_record_sha256(payload)


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _run_unique_execution_fixture(
    fixture: ChapterFixture,
    run_id: UUID,
) -> ChapterFixture:
    """Add deterministic per-run Chinese lines so real Nano cannot be all-cache."""

    alphabet = "零一二三四五六七八九甲乙丙丁戊己"
    run_code = "".join(alphabet[int(value, 16)] for value in run_id.hex)

    def derived(case: ChapterCase, label: str, code: str) -> ChapterCase:
        suffix = (
            f"本地朗读{label}验收{code}只用于本次真实纳米语音推理，"
            "不作为作者正文或可导出音频保留。"
        )
        source = f"{case.source_text.rstrip()}\n\n{suffix}"
        return replace(
            case,
            source_text=source,
            source_sha256=_sha256_text(source),
        )

    return replace(
        fixture,
        automatic=derived(fixture.automatic, "自动链", run_code),
        manual=derived(fixture.manual, "人工链", run_code[::-1]),
    )


def _recovery_record_sha256(payload: Mapping[str, object]) -> str:
    """Hash the exact canonical bytes installed by ``_atomic_*_json``."""

    return _sha256_bytes(_canonical_json_bytes(payload) + b"\n")


def recovery_private_directory_binding(
    path: Path,
    identity: tuple[int, ...],
) -> tuple[str, str]:
    """Return path and physical-directory digests without exposing either."""

    if (
        not isinstance(path, Path)
        or not path.is_absolute()
        or ".." in path.parts
        or type(identity) is not tuple
        or len(identity) != 4
        or any(type(value) is not int or value < 0 for value in identity)
    ):
        raise RunnerError("PRIVATE_WORK_DIR_BINDING_INVALID")
    canonical = str(path)
    return (
        _sha256_text(canonical),
        _sha256_bytes(
            _canonical_json_bytes(
                {
                    "device": identity[0],
                    "inode": identity[1],
                    "mode": identity[2],
                    "uid": identity[3],
                }
            )
        ),
    )


def _validate_recovery_claim_binding(
    value: object,
) -> RecoveryClaimBinding:
    if type(value) is not RecoveryClaimBinding:
        raise RunnerError("RECOVERY_CLAIM_BINDING_REQUIRED")
    for digest in (
        value.claim_identity_sha256,
        value.envelope_fingerprint_sha256,
        value.private_work_dir_canonical_sha256,
        value.private_work_dir_identity_sha256,
    ):
        _validate_sha256(digest, "RECOVERY_CLAIM_BINDING_INVALID")
    return value


def _baseline_recovery_fence(baseline: BaselineSnapshot) -> RecoveryFence:
    return RecoveryFence(
        draft_version=baseline.draft_version,
        content_hash=baseline.content_hash,
        current_edition_id=baseline.current_edition_id,
        current_script_version_id=baseline.current_script_version_id,
        pointer_version=baseline.pointer_version,
    )


def _validate_recovery_fence(value: object) -> RecoveryFence:
    if (
        type(value) is not RecoveryFence
        or type(value.draft_version) is not int
        or value.draft_version < 1
        or type(value.pointer_version) is not int
        or value.pointer_version < 1
        or type(value.current_edition_id) is not UUID
        or type(value.current_script_version_id) is not UUID
    ):
        raise RunnerError("RECOVERY_FENCE_INVALID")
    _validate_sha256(value.content_hash, "RECOVERY_FENCE_INVALID")
    return value


def _recovery_fence_payload(fence: RecoveryFence) -> dict[str, object]:
    fence = _validate_recovery_fence(fence)
    return {
        "draft_version": fence.draft_version,
        "content_hash": fence.content_hash,
        "current_edition_id": str(fence.current_edition_id),
        "current_script_version_id": str(fence.current_script_version_id),
        "pointer_version": fence.pointer_version,
    }


def _parse_recovery_fence_payload(
    value: object,
    code: str,
) -> RecoveryFence:
    if not isinstance(value, dict):
        raise RunnerError(code)
    _require_exact_keys(
        value,
        {
            "draft_version",
            "content_hash",
            "current_edition_id",
            "current_script_version_id",
            "pointer_version",
        },
        code,
    )
    try:
        return _validate_recovery_fence(
            RecoveryFence(
                draft_version=(
                    value["draft_version"]
                    if type(value["draft_version"]) is int
                    else -1
                ),
                content_hash=_validate_sha256(value["content_hash"], code),
                current_edition_id=_parse_uuid(
                    value["current_edition_id"],
                    code,
                ),
                current_script_version_id=_parse_uuid(
                    value["current_script_version_id"],
                    code,
                ),
                pointer_version=(
                    value["pointer_version"]
                    if type(value["pointer_version"]) is int
                    else -1
                ),
            )
        )
    except RunnerError as error:
        raise RunnerError(code) from error


def _validate_recovery_write_intent(
    value: object,
) -> RecoveryWriteIntent:
    if (
        type(value) is not RecoveryWriteIntent
        or value.operation_kind
        not in {"DRAFT_WRITE", "EDITION_SWITCH", "AUTHORITY_WRITE"}
    ):
        raise RunnerError("RECOVERY_WRITE_INTENT_INVALID")
    _validate_sha256(
        value.operation_fingerprint_sha256,
        "RECOVERY_WRITE_INTENT_INVALID",
    )
    _validate_recovery_fence(value.old_fence)
    _validate_recovery_fence(value.next_fence)
    return value


def _recovery_write_intent_payload(
    value: RecoveryWriteIntent,
) -> dict[str, object]:
    value = _validate_recovery_write_intent(value)
    return {
        "operation_kind": value.operation_kind,
        "operation_fingerprint_sha256": (
            value.operation_fingerprint_sha256
        ),
        "old_fence": _recovery_fence_payload(value.old_fence),
        "next_fence": _recovery_fence_payload(value.next_fence),
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc_second(value: object, code: str) -> datetime:
    if type(value) is not str or len(value) != 20:
        raise RunnerError(code)
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as error:
        raise RunnerError(code) from error
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise RunnerError(code)
    return parsed


def _require_exact_keys(
    value: Mapping[str, object],
    expected: set[str],
    code: str,
) -> None:
    if set(value) != expected:
        raise RunnerError(code)


def _reject_duplicate_json_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


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


def _directory_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
    )


def _decode_json_object(raw: bytes, code: str) -> dict[str, object]:
    try:
        payload = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise RunnerError(code) from error
    if type(payload) is not dict:
        raise RunnerError(code)
    return payload


def _read_stable_regular_file(
    path: Path,
    code: str,
    *,
    maximum_bytes: int,
) -> bytes:
    """Read exactly one stable regular-file descriptor without path switching."""

    if (
        not isinstance(path, Path)
        or not path.is_absolute()
        or ".." in path.parts
        or type(maximum_bytes) is not int
        or maximum_bytes <= 0
    ):
        raise RunnerError(code)
    _reject_symlink_components(path, code)
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise RunnerError(code)
    parent_descriptor: int | None = None
    file_descriptor: int | None = None
    try:
        parent_before = path.parent.lstat()
        if not stat.S_ISDIR(parent_before.st_mode):
            raise RunnerError(code)
        parent_descriptor = os.open(
            path.parent,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | nofollow,
        )
        opened_parent = os.fstat(parent_descriptor)
        if _directory_identity(opened_parent) != _directory_identity(parent_before):
            raise RunnerError(code)
        before = os.stat(path.name, dir_fd=parent_descriptor, follow_symlinks=False)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink < 1
            or before.st_size <= 0
            or before.st_size > maximum_bytes
        ):
            raise RunnerError(code)
        file_descriptor = os.open(
            path.name,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | nofollow,
            dir_fd=parent_descriptor,
        )
        opened = os.fstat(file_descriptor)
        if _file_identity(opened) != _file_identity(before):
            raise RunnerError(code)
        chunks: list[bytes] = []
        remaining = opened.st_size
        while remaining:
            chunk = os.read(file_descriptor, min(64 * 1024, remaining))
            if not chunk:
                raise RunnerError(code)
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(file_descriptor, 1):
            raise RunnerError(code)
        after = os.fstat(file_descriptor)
        path_after = os.stat(
            path.name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        parent_after = os.fstat(parent_descriptor)
        parent_path_after = path.parent.lstat()
        _reject_symlink_components(path, code)
        if (
            _file_identity(after) != _file_identity(opened)
            or _file_identity(path_after) != _file_identity(opened)
            or _directory_identity(parent_after)
            != _directory_identity(opened_parent)
            or _directory_identity(parent_path_after)
            != _directory_identity(opened_parent)
        ):
            raise RunnerError(code)
        return b"".join(chunks)
    except RunnerError:
        raise
    except OSError as error:
        raise RunnerError(code) from error
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        if parent_descriptor is not None:
            os.close(parent_descriptor)


def _load_private_json_document(
    path: Path,
    code: str,
    *,
    maximum_bytes: int = 64 * 1024,
) -> tuple[bytes, dict[str, object]]:
    """Read one repository-external owner-only JSON file without path races."""

    if (
        not isinstance(path, Path)
        or not path.is_absolute()
        or ".." in path.parts
        or type(maximum_bytes) is not int
        or maximum_bytes <= 0
    ):
        raise RunnerError(code)
    _reject_symlink_components(path, code)
    parent_descriptor: int | None = None
    file_descriptor: int | None = None
    try:
        supplied_parent = path.parent.lstat()
        parent = path.parent.resolve(strict=True)
        parent_before = parent.lstat()
        if (
            not stat.S_ISDIR(supplied_parent.st_mode)
            or stat.S_ISLNK(supplied_parent.st_mode)
            or supplied_parent.st_uid != os.getuid()
            or stat.S_IMODE(supplied_parent.st_mode) != 0o700
            or (supplied_parent.st_dev, supplied_parent.st_ino)
            != (parent_before.st_dev, parent_before.st_ino)
            or _overlaps_protected_code(parent)
        ):
            raise RunnerError(code)
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            raise RunnerError(code)
        parent_descriptor = os.open(
            parent,
            os.O_RDONLY
            | os.O_DIRECTORY
            | getattr(os, "O_CLOEXEC", 0)
            | nofollow,
        )
        opened_parent = os.fstat(parent_descriptor)
        if (
            (opened_parent.st_dev, opened_parent.st_ino)
            != (parent_before.st_dev, parent_before.st_ino)
            or not stat.S_ISDIR(opened_parent.st_mode)
            or opened_parent.st_uid != os.getuid()
            or stat.S_IMODE(opened_parent.st_mode) != 0o700
        ):
            raise RunnerError(code)
        path_before = os.stat(
            path.name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        file_descriptor = os.open(
            path.name,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | nofollow,
            dir_fd=parent_descriptor,
        )
        before = os.fstat(file_descriptor)
        if (
            _file_identity(path_before) != _file_identity(before)
            or not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != os.getuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size <= 0
            or before.st_size > maximum_bytes
        ):
            raise RunnerError(code)
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(file_descriptor, min(16 * 1024, remaining))
            if not chunk:
                raise RunnerError(code)
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(file_descriptor, 1):
            raise RunnerError(code)
        after = os.fstat(file_descriptor)
        path_after = os.stat(
            path.name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        parent_after = os.fstat(parent_descriptor)
        supplied_parent_after = path.parent.lstat()
        resolved_parent_after = parent.lstat()
        _reject_symlink_components(path, code)
        if (
            _file_identity(after) != _file_identity(before)
            or _file_identity(path_after) != _file_identity(before)
            or _directory_identity(parent_after)
            != _directory_identity(opened_parent)
            or _directory_identity(supplied_parent_after)
            != _directory_identity(opened_parent)
            or _directory_identity(resolved_parent_after)
            != _directory_identity(opened_parent)
            or supplied_parent_after.st_uid != os.getuid()
            or resolved_parent_after.st_uid != os.getuid()
            or stat.S_IMODE(supplied_parent_after.st_mode) != 0o700
            or stat.S_IMODE(resolved_parent_after.st_mode) != 0o700
        ):
            raise RunnerError(code)
        raw = b"".join(chunks)
        try:
            payload = json.loads(
                raw.decode("utf-8", errors="strict"),
                object_pairs_hook=_reject_duplicate_json_keys,
                parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise RunnerError(code) from error
        if type(payload) is not dict:
            raise RunnerError(code)
        return raw, payload
    except RunnerError:
        raise
    except OSError as error:
        raise RunnerError(code) from error
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        if parent_descriptor is not None:
            os.close(parent_descriptor)


def _parse_uuid(value: object, code: str) -> UUID:
    if not isinstance(value, str):
        raise RunnerError(code)
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as error:
        raise RunnerError(code) from error
    if parsed.variant != "specified in RFC 4122" or parsed.version is None:
        raise RunnerError(code)
    return parsed


def _parse_canonical_uuid(value: object, code: str) -> UUID:
    parsed = _parse_uuid(value, code)
    if value != str(parsed):
        raise RunnerError(code)
    return parsed


def _validate_sha256(value: object, code: str) -> str:
    if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
        raise RunnerError(code)
    return value


def _safe_identifier(value: object, code: str) -> str:
    if not isinstance(value, str) or not SAFE_ID_PATTERN.fullmatch(value):
        raise RunnerError(code)
    return value


def _validate_nfc_text(
    value: object,
    *,
    code: str,
    maximum: int,
    allow_newline: bool,
) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise RunnerError(code)
    if value != unicodedata.normalize("NFC", value):
        raise RunnerError(code)
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise RunnerError(code) from error
    if not allow_newline and any(character in value for character in "\r\n"):
        raise RunnerError(code)
    return value


def _validate_correction(value: object) -> Correction:
    if not isinstance(value, dict):
        raise RunnerError("FIXTURE_CORRECTION_INVALID")
    _require_exact_keys(
        value,
        {
            "segment_ordinal",
            "expected_source_local_hash",
            "expected_source_start_utf16",
            "expected_source_end_utf16",
            "speaker_kind",
            "speaker_label",
            "spoken_text",
            "reason",
        },
        "FIXTURE_CORRECTION_INVALID",
    )
    ordinal = value["segment_ordinal"]
    if type(ordinal) is not int or ordinal < 0:
        raise RunnerError("FIXTURE_CORRECTION_INVALID")
    source_start = value["expected_source_start_utf16"]
    source_end = value["expected_source_end_utf16"]
    if (
        type(source_start) is not int
        or type(source_end) is not int
        or source_start < 0
        or source_end <= source_start
    ):
        raise RunnerError("FIXTURE_CORRECTION_INVALID")
    speaker_kind = value["speaker_kind"]
    if speaker_kind not in {"narrator", "character", "anonymous"}:
        raise RunnerError("FIXTURE_CORRECTION_INVALID")
    return Correction(
        segment_ordinal=ordinal,
        expected_source_local_hash=_validate_sha256(
            value["expected_source_local_hash"],
            "FIXTURE_CORRECTION_INVALID",
        ),
        expected_source_start_utf16=source_start,
        expected_source_end_utf16=source_end,
        speaker_kind=speaker_kind,
        speaker_label=_validate_nfc_text(
            value["speaker_label"],
            code="FIXTURE_CORRECTION_INVALID",
            maximum=160,
            allow_newline=False,
        ),
        spoken_text=_validate_nfc_text(
            value["spoken_text"],
            code="FIXTURE_CORRECTION_INVALID",
            maximum=MAX_SPOKEN_CODEPOINTS,
            allow_newline=True,
        ),
        reason=_validate_nfc_text(
            value["reason"],
            code="FIXTURE_CORRECTION_INVALID",
            maximum=400,
            allow_newline=False,
        ),
    )


def _utf16_slice(value: str, start: int, end: int) -> str:
    encoded = value.encode("utf-16-le", errors="strict")
    if end * 2 > len(encoded):
        raise RunnerError("FIXTURE_CORRECTION_INVALID")
    try:
        return encoded[start * 2 : end * 2].decode("utf-16-le", errors="strict")
    except UnicodeDecodeError as error:
        raise RunnerError("FIXTURE_CORRECTION_INVALID") from error


def _validate_case(value: object) -> ChapterCase:
    if not isinstance(value, dict):
        raise RunnerError("FIXTURE_CASE_INVALID")
    _require_exact_keys(
        value,
        {
            "id",
            "mode",
            "source_text",
            "source_sha256",
            "review_policy",
            "expected_initial_blocker_codes",
            "corrections",
        },
        "FIXTURE_CASE_INVALID",
    )
    case_id = _safe_identifier(value["id"], "FIXTURE_CASE_INVALID")
    mode = value["mode"]
    if mode not in {"automatic_zero_blockers", "manual_blocker_resolution"}:
        raise RunnerError("FIXTURE_CASE_INVALID")
    source_text = _validate_nfc_text(
        value["source_text"],
        code="FIXTURE_CASE_INVALID",
        maximum=MAX_SOURCE_CODEPOINTS,
        allow_newline=True,
    )
    if len(source_text) < FORMAL_MINIMUM_CHAPTER_CODEPOINTS:
        raise RunnerError("FIXTURE_CHAPTER_TOO_SHORT")
    source_sha256 = _validate_sha256(
        value["source_sha256"], "FIXTURE_CASE_INVALID"
    )
    if source_sha256 != _sha256_text(source_text):
        raise RunnerError("FIXTURE_SOURCE_HASH_MISMATCH")
    if value["review_policy"] != "blockers_only":
        raise RunnerError("FIXTURE_CASE_INVALID")
    raw_codes = value["expected_initial_blocker_codes"]
    if (
        not isinstance(raw_codes, list)
        or not all(
            isinstance(code, str) and SAFE_CODE_PATTERN.fullmatch(code)
            for code in raw_codes
        )
        or raw_codes != sorted(set(raw_codes))
        or any(code not in ALLOWED_BLOCKER_CODES for code in raw_codes)
    ):
        raise RunnerError("FIXTURE_CASE_INVALID")
    raw_corrections = value["corrections"]
    if not isinstance(raw_corrections, list):
        raise RunnerError("FIXTURE_CASE_INVALID")
    corrections = tuple(_validate_correction(item) for item in raw_corrections)
    if mode == "automatic_zero_blockers" and (raw_codes or corrections):
        raise RunnerError("FIXTURE_AUTOMATIC_CASE_INVALID")
    if mode == "manual_blocker_resolution" and (not raw_codes or not corrections):
        raise RunnerError("FIXTURE_MANUAL_CASE_INVALID")
    for correction in corrections:
        source_slice = _utf16_slice(
            source_text,
            correction.expected_source_start_utf16,
            correction.expected_source_end_utf16,
        )
        if _sha256_text(source_slice) != correction.expected_source_local_hash:
            raise RunnerError("FIXTURE_CORRECTION_SOURCE_MISMATCH")
    correction_keys = [
        (
            item.segment_ordinal,
            item.expected_source_local_hash,
            item.expected_source_start_utf16,
            item.expected_source_end_utf16,
        )
        for item in corrections
    ]
    if len(correction_keys) != len(set(correction_keys)):
        raise RunnerError("FIXTURE_CORRECTION_INVALID")
    return ChapterCase(
        case_id=case_id,
        mode=mode,
        source_text=source_text,
        source_sha256=source_sha256,
        review_policy="blockers_only",
        expected_initial_blocker_codes=tuple(raw_codes),
        corrections=corrections,
    )


def load_fixture(
    path: Path,
    *,
    automatic_case_id: str,
    manual_case_id: str,
) -> ChapterFixture:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    candidate = candidate.absolute()
    _reject_symlink_components(candidate, "FIXTURE_UNREADABLE")
    candidate = candidate.resolve(strict=False)
    raw = _read_stable_regular_file(
        candidate,
        "FIXTURE_UNREADABLE",
        maximum_bytes=MAX_FIXTURE_BYTES,
    )
    payload = _decode_json_object(raw, "FIXTURE_UNREADABLE")
    _require_exact_keys(
        payload,
        {
            "schema_version",
            "fixture_id",
            "authorization",
            "voice_scope",
            "production_eligible",
            "commercial_distribution_status",
            "minimum_character_speakers",
            "minimum_distinct_voice_versions",
            "expected_formal_speakers",
            "require_uncached_nano_model_run",
            "restoration_policy",
            "minimum_duration_minutes",
            "required_viewports",
            "chapter_cases",
        },
        "FIXTURE_SCHEMA_INVALID",
    )
    if payload["schema_version"] != FIXTURE_SCHEMA:
        raise RunnerError("FIXTURE_SCHEMA_INVALID")
    fixture_id = _safe_identifier(payload["fixture_id"], "FIXTURE_SCHEMA_INVALID")
    authorization = payload["authorization"]
    if not isinstance(authorization, dict):
        raise RunnerError("FIXTURE_AUTHORIZATION_INVALID")
    _require_exact_keys(
        authorization,
        {
            "text_owner",
            "authorization_reference",
            "authorized_for_tts",
            "contains_private_reference_audio",
        },
        "FIXTURE_AUTHORIZATION_INVALID",
    )
    if (
        authorization["text_owner"] not in {"project_owned", "user_authorized"}
        or authorization["authorized_for_tts"] is not True
        or authorization["contains_private_reference_audio"] is not False
    ):
        raise RunnerError("FIXTURE_AUTHORIZATION_INVALID")
    authorization_reference = _safe_identifier(
        authorization["authorization_reference"],
        "FIXTURE_AUTHORIZATION_INVALID",
    )
    voice_scope = payload["voice_scope"]
    production_eligible = payload["production_eligible"]
    commercial_distribution_status = payload["commercial_distribution_status"]
    if (
        voice_scope
        not in {"isolated_test_only", "local_personal_use", "production_approved"}
        or type(production_eligible) is not bool
        or production_eligible
        != (voice_scope in {"local_personal_use", "production_approved"})
        or commercial_distribution_status != "not_evaluated"
    ):
        raise RunnerError("FIXTURE_VOICE_SCOPE_INVALID")
    minimum_character_speakers = payload["minimum_character_speakers"]
    minimum_distinct_voice_versions = payload["minimum_distinct_voice_versions"]
    raw_formal_speakers = payload["expected_formal_speakers"]
    if (
        type(minimum_character_speakers) is not int
        or minimum_character_speakers < 2
        or type(minimum_distinct_voice_versions) is not int
        or minimum_distinct_voice_versions < minimum_character_speakers + 1
        or payload["require_uncached_nano_model_run"] is not True
        or payload["restoration_policy"]
        != "dedicated_append_only_author_visible"
    ):
        raise RunnerError("FIXTURE_REAL_CHAIN_REQUIREMENTS_INVALID")
    if (
        not isinstance(raw_formal_speakers, list)
        or len(raw_formal_speakers) != minimum_character_speakers
        or len(raw_formal_speakers) != len(set(raw_formal_speakers))
        or any(
            type(value) is not str
            or not value
            or value != value.strip()
            or len(value) > 240
            for value in raw_formal_speakers
        )
    ):
        raise RunnerError("FIXTURE_FORMAL_SPEAKERS_INVALID")
    minimum = payload["minimum_duration_minutes"]
    if type(minimum) not in {int, float} or float(minimum) < FORMAL_MINIMUM_DURATION_MINUTES:
        raise RunnerError("FIXTURE_DURATION_INVALID")
    raw_viewports = payload["required_viewports"]
    if not isinstance(raw_viewports, list):
        raise RunnerError("FIXTURE_VIEWPORTS_INVALID")
    viewports: list[tuple[int, int]] = []
    for item in raw_viewports:
        if not isinstance(item, dict):
            raise RunnerError("FIXTURE_VIEWPORTS_INVALID")
        _require_exact_keys(item, {"width", "height"}, "FIXTURE_VIEWPORTS_INVALID")
        width = item["width"]
        height = item["height"]
        if type(width) is not int or type(height) is not int:
            raise RunnerError("FIXTURE_VIEWPORTS_INVALID")
        viewports.append((width, height))
    if tuple(viewports) != ALLOWED_VIEWPORTS:
        raise RunnerError("FIXTURE_VIEWPORTS_INVALID")
    raw_cases = payload["chapter_cases"]
    if not isinstance(raw_cases, list) or len(raw_cases) < 2:
        raise RunnerError("FIXTURE_CASE_INVALID")
    cases = tuple(_validate_case(item) for item in raw_cases)
    case_ids = [item.case_id for item in cases]
    if len(case_ids) != len(set(case_ids)):
        raise RunnerError("FIXTURE_CASE_INVALID")
    by_id = {item.case_id: item for item in cases}
    try:
        automatic = by_id[automatic_case_id]
        manual = by_id[manual_case_id]
    except KeyError as error:
        raise RunnerError("FIXTURE_CASE_NOT_FOUND") from error
    if automatic.mode != "automatic_zero_blockers":
        raise RunnerError("FIXTURE_AUTOMATIC_CASE_INVALID")
    if manual.mode != "manual_blocker_resolution":
        raise RunnerError("FIXTURE_MANUAL_CASE_INVALID")
    return ChapterFixture(
        fixture_id=fixture_id,
        manifest_sha256=_sha256_bytes(raw),
        authorization_reference=authorization_reference,
        voice_scope=voice_scope,
        production_eligible=production_eligible,
        commercial_distribution_status="not_evaluated",
        minimum_character_speakers=minimum_character_speakers,
        minimum_distinct_voice_versions=minimum_distinct_voice_versions,
        expected_formal_speakers=tuple(raw_formal_speakers),
        require_uncached_nano_model_run=True,
        restoration_policy="dedicated_append_only_author_visible",
        automatic=automatic,
        manual=manual,
        required_viewports=tuple(viewports),
    )


def _revalidate_case_object(value: object, code: str) -> ChapterCase:
    if type(value) is not ChapterCase:
        raise RunnerError(code)
    if (
        type(value.corrections) is not tuple
        or type(value.expected_initial_blocker_codes) is not tuple
    ):
        raise RunnerError(code)
    corrections: list[dict[str, object]] = []
    for correction in value.corrections:
        if type(correction) is not Correction:
            raise RunnerError(code)
        corrections.append(
            {
                "segment_ordinal": correction.segment_ordinal,
                "expected_source_local_hash": (
                    correction.expected_source_local_hash
                ),
                "expected_source_start_utf16": (
                    correction.expected_source_start_utf16
                ),
                "expected_source_end_utf16": (
                    correction.expected_source_end_utf16
                ),
                "speaker_kind": correction.speaker_kind,
                "speaker_label": correction.speaker_label,
                "spoken_text": correction.spoken_text,
                "reason": correction.reason,
            }
        )
    try:
        rebuilt = _validate_case(
            {
                "id": value.case_id,
                "mode": value.mode,
                "source_text": value.source_text,
                "source_sha256": value.source_sha256,
                "review_policy": value.review_policy,
                "expected_initial_blocker_codes": list(
                    value.expected_initial_blocker_codes
                ),
                "corrections": corrections,
            }
        )
    except RunnerError as error:
        raise RunnerError(code) from error
    if rebuilt != value:
        raise RunnerError(code)
    return value


def _validate_fixture_override(
    value: object,
    config: RunnerConfig,
) -> ChapterFixture:
    """Revalidate an already loaded fixture without reopening its manifest."""

    code = "FIXTURE_OVERRIDE_INVALID"
    if type(value) is not ChapterFixture:
        raise RunnerError(code)
    if (
        type(value.fixture_id) is not str
        or type(value.manifest_sha256) is not str
        or type(value.authorization_reference) is not str
        or type(value.expected_formal_speakers) is not tuple
        or any(type(speaker) is not str for speaker in value.expected_formal_speakers)
    ):
        raise RunnerError(code)
    if (
        SAFE_ID_PATTERN.fullmatch(value.fixture_id) is None
        or SHA256_PATTERN.fullmatch(value.manifest_sha256) is None
        or SAFE_ID_PATTERN.fullmatch(value.authorization_reference) is None
        or value.voice_scope
        not in {"isolated_test_only", "local_personal_use", "production_approved"}
        or type(value.production_eligible) is not bool
        or value.production_eligible
        != (value.voice_scope in {"local_personal_use", "production_approved"})
        or value.commercial_distribution_status != "not_evaluated"
        or type(value.minimum_character_speakers) is not int
        or value.minimum_character_speakers < 2
        or type(value.minimum_distinct_voice_versions) is not int
        or value.minimum_distinct_voice_versions
        < value.minimum_character_speakers + 1
        or value.require_uncached_nano_model_run is not True
        or value.restoration_policy
        != "dedicated_append_only_author_visible"
        or value.required_viewports != ALLOWED_VIEWPORTS
        or len(value.expected_formal_speakers)
        != value.minimum_character_speakers
        or len(value.expected_formal_speakers)
        != len(set(value.expected_formal_speakers))
        or any(
            type(speaker) is not str
            or not speaker
            or speaker != speaker.strip()
            or len(speaker) > 240
            for speaker in value.expected_formal_speakers
        )
    ):
        raise RunnerError(code)
    automatic = _revalidate_case_object(value.automatic, code)
    manual = _revalidate_case_object(value.manual, code)
    if (
        automatic.mode != "automatic_zero_blockers"
        or manual.mode != "manual_blocker_resolution"
        or automatic.case_id == manual.case_id
        or automatic.case_id != config.automatic_case_id
        or manual.case_id != config.manual_case_id
        or config.expected_formal_speakers
        not in {(), value.expected_formal_speakers}
    ):
        raise RunnerError(code)
    return value


def _normalize_api_base(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError as error:
        raise RunnerError("API_BASE_NOT_LOOPBACK") from error
    if (
        parsed.scheme != "http"
        or parsed.hostname not in LOOPBACK_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != API_PATH
    ):
        raise RunnerError("API_BASE_NOT_LOOPBACK")
    try:
        port = parsed.port
    except ValueError as error:
        raise RunnerError("API_BASE_NOT_LOOPBACK") from error
    if port is None or not 1 <= port <= 65535:
        raise RunnerError("API_BASE_NOT_LOOPBACK")
    host = "[::1]" if parsed.hostname == "::1" else parsed.hostname
    return urlunsplit(("http", f"{host}:{port}", API_PATH, "", ""))


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _reject_symlink_components(path: Path, code: str) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise RunnerError(code) from error
        if stat.S_ISLNK(metadata.st_mode):
            raise RunnerError(code)


def _protected_code_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    for candidate in (REPOSITORY_ROOT, CURRENT_PAWAPP_ROOT):
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as error:
            raise RunnerError("PROTECTED_CODE_ROOT_UNAVAILABLE") from error
        if resolved not in roots:
            roots.append(resolved)
    return tuple(roots)


def _overlaps_protected_code(path: Path) -> bool:
    return any(
        path == root
        or path.is_relative_to(root)
        or root.is_relative_to(path)
        for root in _protected_code_roots()
    )


def _normalize_paths(args: argparse.Namespace) -> tuple[Path, Path, Path, Path | None]:
    fixture = Path(args.fixture_manifest).expanduser()
    if not fixture.is_absolute():
        fixture = Path.cwd() / fixture
    output = Path(args.output_dir).expanduser()
    if not output.is_absolute():
        output = Path.cwd() / output
    private = Path(args.private_work_dir)
    listening = (
        Path(args.listening_record).expanduser()
        if args.listening_record is not None
        else None
    )
    # Recovery storage is security-sensitive: require a syntactically absolute
    # path rather than silently expanding ``~`` through process environment.
    if not private.is_absolute():
        raise RunnerError("PRIVATE_WORK_DIR_NOT_ABSOLUTE")
    if listening is not None and not listening.is_absolute():
        listening = Path.cwd() / listening

    # Inspect the operator-supplied path graph before ``resolve`` erases a
    # symlink component.  No output or recovery path may acquire an alternate
    # target through an existing link.
    fixture = fixture.absolute()
    output = output.absolute()
    private = private.absolute()
    listening = listening.absolute() if listening is not None else None
    _reject_symlink_components(fixture, "FIXTURE_PATH_UNSAFE")
    _reject_symlink_components(output, "OUTPUT_PATH_UNSAFE")
    _reject_symlink_components(private, "PRIVATE_WORK_DIR_UNSAFE")
    if listening is not None:
        _reject_symlink_components(listening, "LISTENING_RECORD_UNSAFE")

    fixture = fixture.resolve(strict=False)
    output = output.resolve(strict=False)
    private = private.resolve(strict=False)
    listening = listening.resolve(strict=False) if listening is not None else None
    filesystem_root = Path(private.anchor).resolve()
    user_home = Path.home().resolve()
    if private in {filesystem_root, user_home} or _overlaps_protected_code(private):
        raise RunnerError("PRIVATE_WORK_DIR_TOO_BROAD")
    if output in {
        Path(output.anchor).resolve(),
        user_home,
    } or _overlaps_protected_code(output):
        raise RunnerError("OUTPUT_PATH_TOO_BROAD")
    if _is_within(output, private) or _is_within(private, output):
        raise RunnerError("OUTPUT_PRIVATE_PATH_OVERLAP")
    return fixture, output, private, listening


@dataclass(slots=True)
class _SecureDirectory:
    path: Path
    descriptor: int
    opened_identity: tuple[int, ...]
    code: str

    def assert_stable(self) -> None:
        try:
            opened = os.fstat(self.descriptor)
            path_metadata = self.path.lstat()
        except OSError as error:
            raise RunnerError(self.code) from error
        if (
            _directory_identity(opened) != self.opened_identity
            or _directory_identity(path_metadata) != self.opened_identity
            or not stat.S_ISDIR(opened.st_mode)
            or stat.S_ISLNK(path_metadata.st_mode)
            or opened.st_uid != os.getuid()
            or path_metadata.st_uid != os.getuid()
            or stat.S_IMODE(opened.st_mode) != 0o700
            or stat.S_IMODE(path_metadata.st_mode) != 0o700
        ):
            raise RunnerError(self.code)

    def close(self) -> None:
        try:
            self.assert_stable()
        finally:
            os.close(self.descriptor)


def _open_secure_directory(
    path: Path,
    code: str,
    *,
    create_missing: bool = True,
) -> _SecureDirectory:
    """Create missing path components without replacement, then pin a dirfd."""

    if (
        not path.is_absolute()
        or ".." in path.parts
        or type(create_missing) is not bool
    ):
        raise RunnerError(code)
    _reject_symlink_components(path, code)
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise RunnerError(code)
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    current_descriptor: int | None = None
    try:
        current_descriptor = os.open(
            path.anchor,
            os.O_RDONLY | directory_flag | cloexec | nofollow,
        )
        for part in path.parts[1:]:
            next_descriptor: int | None = None
            try:
                next_descriptor = os.open(
                    part,
                    os.O_RDONLY | directory_flag | cloexec | nofollow,
                    dir_fd=current_descriptor,
                )
            except FileNotFoundError:
                if not create_missing:
                    raise RunnerError(code)
                try:
                    os.mkdir(part, 0o700, dir_fd=current_descriptor)
                except FileExistsError:
                    pass
                next_descriptor = os.open(
                    part,
                    os.O_RDONLY | directory_flag | cloexec | nofollow,
                    dir_fd=current_descriptor,
                )
            metadata = os.fstat(next_descriptor)
            if not stat.S_ISDIR(metadata.st_mode):
                raise RunnerError(code)
            os.close(current_descriptor)
            current_descriptor = next_descriptor
        opened = os.fstat(current_descriptor)
        path_metadata = path.lstat()
        identity = _directory_identity(opened)
        if (
            _directory_identity(path_metadata) != identity
            or not stat.S_ISDIR(opened.st_mode)
            or stat.S_ISLNK(path_metadata.st_mode)
            or opened.st_uid != os.getuid()
            or path_metadata.st_uid != os.getuid()
            or stat.S_IMODE(opened.st_mode) != 0o700
            or stat.S_IMODE(path_metadata.st_mode) != 0o700
        ):
            raise RunnerError(code)
        secured = _SecureDirectory(path, current_descriptor, identity, code)
        current_descriptor = None
        return secured
    except RunnerError:
        raise
    except OSError as error:
        raise RunnerError(code) from error
    finally:
        if current_descriptor is not None:
            os.close(current_descriptor)


def _validate_internal_name(name: str, code: str) -> None:
    if (
        type(name) is not str
        or not name
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or "\x00" in name
    ):
        raise RunnerError(code)


def _secure_file(metadata: os.stat_result, *, maximum_bytes: int | None = None) -> bool:
    return (
        stat.S_ISREG(metadata.st_mode)
        and metadata.st_uid == os.getuid()
        and stat.S_IMODE(metadata.st_mode) == 0o600
        and metadata.st_nlink == 1
        and (maximum_bytes is None or 0 < metadata.st_size <= maximum_bytes)
    )


def _open_named_file(
    directory: _SecureDirectory,
    name: str,
    code: str,
    *,
    maximum_bytes: int | None = None,
) -> tuple[int, os.stat_result]:
    _validate_internal_name(name, code)
    directory.assert_stable()
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise RunnerError(code)
    descriptor: int | None = None
    try:
        before = os.stat(name, dir_fd=directory.descriptor, follow_symlinks=False)
        if not _secure_file(before, maximum_bytes=maximum_bytes):
            raise RunnerError(code)
        descriptor = os.open(
            name,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | nofollow,
            dir_fd=directory.descriptor,
        )
        opened = os.fstat(descriptor)
        path_after = os.stat(
            name,
            dir_fd=directory.descriptor,
            follow_symlinks=False,
        )
        if (
            _file_identity(opened) != _file_identity(before)
            or _file_identity(path_after) != _file_identity(opened)
            or not _secure_file(opened, maximum_bytes=maximum_bytes)
        ):
            raise RunnerError(code)
        directory.assert_stable()
        result = (descriptor, opened)
        descriptor = None
        return result
    except RunnerError:
        raise
    except OSError as error:
        raise RunnerError(code) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _entry_exists(directory: _SecureDirectory, name: str, code: str) -> bool:
    _validate_internal_name(name, code)
    directory.assert_stable()
    try:
        os.stat(name, dir_fd=directory.descriptor, follow_symlinks=False)
    except FileNotFoundError:
        exists = False
    except OSError as error:
        raise RunnerError(code) from error
    else:
        exists = True
    directory.assert_stable()
    return exists


def _read_directory_json(
    directory: _SecureDirectory,
    name: str,
    code: str,
    *,
    maximum_bytes: int,
) -> dict[str, object]:
    descriptor: int | None = None
    try:
        descriptor, opened = _open_named_file(
            directory,
            name,
            code,
            maximum_bytes=maximum_bytes,
        )
        chunks: list[bytes] = []
        remaining = opened.st_size
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                raise RunnerError(code)
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise RunnerError(code)
        after = os.fstat(descriptor)
        path_after = os.stat(
            name,
            dir_fd=directory.descriptor,
            follow_symlinks=False,
        )
        if (
            _file_identity(after) != _file_identity(opened)
            or _file_identity(path_after) != _file_identity(opened)
        ):
            raise RunnerError(code)
        directory.assert_stable()
        return _decode_json_object(b"".join(chunks), code)
    except RunnerError:
        raise
    except OSError as error:
        raise RunnerError(code) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _write_descriptor(descriptor: int, data: bytes, code: str) -> None:
    view = memoryview(data)
    try:
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise RunnerError(code)
            view = view[written:]
        os.fsync(descriptor)
    except RunnerError:
        raise
    except OSError as error:
        raise RunnerError(code) from error


def _atomic_write(
    directory: _SecureDirectory,
    name: str,
    data: bytes,
    code: str,
    *,
    exclusive: bool = False,
    exists_code: str | None = None,
) -> None:
    _validate_internal_name(name, code)
    if type(data) is not bytes:
        raise RunnerError(code)
    directory.assert_stable()
    existing_identity: tuple[int, ...] | None = None
    if _entry_exists(directory, name, code):
        descriptor, existing = _open_named_file(directory, name, code)
        os.close(descriptor)
        existing_identity = _file_identity(existing)
        if exclusive:
            raise RunnerError(exists_code or code)

    temporary_name = f".{name}.{uuid4().hex}.tmp"
    temporary_descriptor: int | None = None
    installed = False
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise RunnerError(code)
    try:
        temporary_descriptor = os.open(
            temporary_name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | nofollow,
            0o600,
            dir_fd=directory.descriptor,
        )
        os.fchmod(temporary_descriptor, 0o600)
        _write_descriptor(temporary_descriptor, data, code)
        temporary = os.fstat(temporary_descriptor)
        if (
            not _secure_file(temporary)
            or temporary.st_size != len(data)
        ):
            raise RunnerError(code)
        directory.assert_stable()
        temporary_path_metadata = os.stat(
            temporary_name,
            dir_fd=directory.descriptor,
            follow_symlinks=False,
        )
        if _file_identity(temporary_path_metadata) != _file_identity(temporary):
            raise RunnerError(code)

        if existing_identity is None:
            if _entry_exists(directory, name, code):
                raise RunnerError(exists_code or code)
        else:
            current_descriptor, current = _open_named_file(directory, name, code)
            os.close(current_descriptor)
            if _file_identity(current) != existing_identity:
                raise RunnerError(code)

        if exclusive:
            try:
                os.link(
                    temporary_name,
                    name,
                    src_dir_fd=directory.descriptor,
                    dst_dir_fd=directory.descriptor,
                    follow_symlinks=False,
                )
            except FileExistsError as error:
                raise RunnerError(exists_code or code) from error
        else:
            os.replace(
                temporary_name,
                name,
                src_dir_fd=directory.descriptor,
                dst_dir_fd=directory.descriptor,
            )
        installed = True
        try:
            os.unlink(temporary_name, dir_fd=directory.descriptor)
        except FileNotFoundError:
            pass
        temporary_after = os.fstat(temporary_descriptor)
        installed_descriptor, final_metadata = _open_named_file(
            directory,
            name,
            code,
        )
        os.close(installed_descriptor)
        if (
            final_metadata.st_dev != temporary.st_dev
            or final_metadata.st_ino != temporary.st_ino
            or final_metadata.st_size != len(data)
            or temporary_after.st_dev != temporary.st_dev
            or temporary_after.st_ino != temporary.st_ino
            or temporary_after.st_size != len(data)
            or not _secure_file(temporary_after)
        ):
            raise RunnerError(code)
        os.fsync(directory.descriptor)
        directory.assert_stable()
    except RunnerError:
        raise
    except OSError as error:
        raise RunnerError(code) from error
    finally:
        if temporary_descriptor is not None:
            os.close(temporary_descriptor)
        if not installed:
            try:
                os.unlink(temporary_name, dir_fd=directory.descriptor)
            except OSError:
                pass


def _atomic_write_json(
    directory: _SecureDirectory,
    name: str,
    payload: Mapping[str, object],
    code: str,
) -> None:
    _atomic_write(
        directory,
        name,
        _canonical_json_bytes(payload) + b"\n",
        code,
    )


def _atomic_create_json(
    directory: _SecureDirectory,
    name: str,
    payload: Mapping[str, object],
    *,
    code: str,
    exists_code: str,
) -> None:
    _atomic_write(
        directory,
        name,
        _canonical_json_bytes(payload) + b"\n",
        code,
        exclusive=True,
        exists_code=exists_code,
    )


def _unlink_secure(directory: _SecureDirectory, name: str) -> None:
    code = "RECOVERY_RECORD_UNSAFE"
    descriptor: int | None = None
    try:
        descriptor, opened = _open_named_file(directory, name, code)
        path_before = os.stat(
            name,
            dir_fd=directory.descriptor,
            follow_symlinks=False,
        )
        if _file_identity(path_before) != _file_identity(opened):
            raise RunnerError(code)
        os.unlink(name, dir_fd=directory.descriptor)
        after = os.fstat(descriptor)
        if (
            after.st_dev != opened.st_dev
            or after.st_ino != opened.st_ino
            or after.st_nlink != 0
        ):
            raise RunnerError(code)
        try:
            os.stat(name, dir_fd=directory.descriptor, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise RunnerError(code)
        os.fsync(directory.descriptor)
        directory.assert_stable()
    except RunnerError:
        raise
    except OSError as error:
        raise RunnerError("RECOVERY_RECORD_DELETE_FAILED") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def build_parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", choices=("validate-only", "real"), default="validate-only"
    )
    parser.add_argument("--run-id")
    parser.add_argument("--fixture-manifest", required=True)
    parser.add_argument("--api-base", required=True)
    parser.add_argument("--novel-id", required=True)
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--automatic-case-id", required=True)
    parser.add_argument("--manual-case-id", required=True)
    parser.add_argument("--private-work-dir", required=True)
    parser.add_argument("--confirm-dedicated-test-document", required=True)
    parser.add_argument("--confirm-dedicated-test-novel", required=True)
    parser.add_argument("--duration-minutes", required=True, type=float)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--listening-record")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--confirm-real-run")
    parser.add_argument("--confirm-baseline-restore")
    parser.add_argument("--confirm-private-work-dir-local-non-synced")
    return parser


def _build_config(
    args: argparse.Namespace,
    *,
    minimum_duration_minutes: float,
) -> RunnerConfig:
    if minimum_duration_minutes <= 0:
        raise RunnerError("INTERNAL_DURATION_POLICY_INVALID")
    novel_id = _parse_uuid(args.novel_id, "NOVEL_ID_INVALID")
    document_id = _parse_uuid(args.document_id, "DOCUMENT_ID_INVALID")
    confirmed = _parse_uuid(
        args.confirm_dedicated_test_document,
        "DEDICATED_DOCUMENT_CONFIRMATION_INVALID",
    )
    if confirmed != document_id:
        raise RunnerError("DEDICATED_DOCUMENT_CONFIRMATION_MISMATCH")
    confirmed_novel = _parse_uuid(
        args.confirm_dedicated_test_novel,
        "DEDICATED_NOVEL_CONFIRMATION_INVALID",
    )
    if confirmed_novel != novel_id:
        raise RunnerError("DEDICATED_NOVEL_CONFIRMATION_MISMATCH")
    if (
        not math.isfinite(args.duration_minutes)
        or args.duration_minutes < minimum_duration_minutes
    ):
        raise RunnerError("STABILITY_DURATION_TOO_SHORT")
    if args.mode == "real" and (
        args.confirm_real_run != REAL_RUN_CONFIRMATION
        or args.confirm_baseline_restore != RESTORE_CONFIRMATION
        or args.confirm_private_work_dir_local_non_synced
        != PRIVATE_WORK_DIR_CONFIRMATION
    ):
        raise RunnerError("REAL_MODE_CONFIRMATION_REQUIRED")
    if args.resume and args.mode != "real":
        raise RunnerError("RESUME_REQUIRES_REAL_MODE")
    fixture, output, private, listening = _normalize_paths(args)
    run_id = (
        _parse_uuid(args.run_id, "RUN_ID_INVALID")
        if args.run_id is not None
        else uuid4()
    )
    return RunnerConfig(
        run_id=run_id,
        mode=args.mode,
        fixture_manifest=fixture,
        api_base=_normalize_api_base(args.api_base),
        novel_id=novel_id,
        document_id=document_id,
        automatic_case_id=_safe_identifier(
            args.automatic_case_id, "AUTOMATIC_CASE_ID_INVALID"
        ),
        manual_case_id=_safe_identifier(
            args.manual_case_id, "MANUAL_CASE_ID_INVALID"
        ),
        private_work_dir=private,
        output_dir=output,
        duration_minutes=float(args.duration_minutes),
        listening_record=listening,
        resume=args.resume,
    )


def build_runner_config(
    args: argparse.Namespace,
    *,
    minimum_duration_minutes: float = FORMAL_MINIMUM_DURATION_MINUTES,
) -> RunnerConfig:
    """Build the deterministic runner config for fixed launcher preflight.

    The public seam lets the formal launcher verify an operator envelope before
    constructing database/executor ports.  It performs the same validation as
    :func:`main` and does not create directories or contact external services.
    """

    return _build_config(
        args,
        minimum_duration_minutes=minimum_duration_minutes,
    )


def _case_evidence(case: ChapterCase) -> dict[str, object]:
    return {
        "case_id": case.case_id,
        "mode": case.mode,
        "source_sha256": case.source_sha256,
        "expected_initial_blocker_codes": list(
            case.expected_initial_blocker_codes
        ),
        "correction_count": len(case.corrections),
    }


def _base_result(
    config: RunnerConfig,
    fixture: ChapterFixture,
    *,
    run_id: str,
) -> dict[str, object]:
    return {
        "schema_version": RESULT_SCHEMA,
        "work_package": WORK_PACKAGE,
        "run_fingerprint_sha256": _sha256_text(run_id),
        "created_at": _utc_now(),
        "mode": config.mode,
        "status": "RUNNING",
        "fixture": {
            "fixture_id": fixture.fixture_id,
            "manifest_sha256": fixture.manifest_sha256,
            "authorization_reference_sha256": _sha256_text(
                fixture.authorization_reference
            ),
            "voice_scope": fixture.voice_scope,
            "production_eligible": fixture.production_eligible,
            "commercial_distribution_status": (
                fixture.commercial_distribution_status
            ),
            "minimum_character_speakers": fixture.minimum_character_speakers,
            "minimum_distinct_voice_versions": (
                fixture.minimum_distinct_voice_versions
            ),
            "require_uncached_nano_model_run": (
                fixture.require_uncached_nano_model_run
            ),
            "restoration_policy": fixture.restoration_policy,
            "minimum_chapter_codepoints": (
                FORMAL_MINIMUM_CHAPTER_CODEPOINTS
            ),
            "automatic": _case_evidence(fixture.automatic),
            "manual": _case_evidence(fixture.manual),
        },
        "target_scope_sha256": _sha256_text(
            f"{config.novel_id}:{config.document_id}"
        ),
        "api": {
            "loopback_only": True,
            "contract_path": API_PATH,
        },
        "duration_minutes": config.duration_minutes,
        "required_viewports": [
            {"width": width, "height": height}
            for width, height in ALLOWED_VIEWPORTS
        ],
        "safety": {
            "dedicated_document_confirmation_matched": True,
            "dedicated_novel_confirmation_matched": True,
            "private_work_dir_external": True,
            "private_work_dir_local_non_synced_confirmed": (
                config.mode == "real"
            ),
            "no_chapter_text_recorded": True,
            "no_secrets_recorded": True,
            "no_audio_bytes_recorded": True,
            "no_private_paths_recorded": True,
        },
        "automatic_chain": {"state": "NOT_RUN"},
        "manual_chain": {"state": "NOT_RUN"},
        "technical_checks": {"state": "NOT_RUN"},
        "human_listening": {"state": "PENDING"},
        "recovery": {
            "record_created": False,
            "working_copy_content_restored": False,
            "author_visible_edition_restored": False,
            "append_only_history_retained": False,
            "new_authoritative_record_count": 0,
            "recovery_required": False,
        },
        "error_codes": [],
    }


def _chain_evidence(outcome: ChainOutcome) -> dict[str, object]:
    return {
        "state": "PASS",
        "request_fingerprint_sha256": _sha256_text(str(outcome.request_id)),
        "script_version_fingerprint_sha256": _sha256_text(
            str(outcome.script_version_id)
        ),
        "edition_id_sha256": _sha256_text(str(outcome.edition_id)),
        "edition_fingerprint_sha256": outcome.edition_fingerprint,
        "approval_kind": outcome.approval_kind,
        "initial_blocker_count": outcome.initial_blocker_count,
        "final_blocker_count": outcome.final_blocker_count,
        "edition_count_for_request": outcome.edition_count_for_request,
        "manifest_revision": outcome.manifest_revision,
        "narrator_segment_count": outcome.narrator_segment_count,
        "character_segment_count": outcome.character_segment_count,
        "distinct_character_count": outcome.distinct_character_count,
        "distinct_voice_version_count": outcome.distinct_voice_version_count,
        "uncached_nano_job_count": outcome.uncached_nano_job_count,
        "model_run_fingerprints": sorted(outcome.model_run_fingerprints),
    }


def _validate_chain(
    outcome: object,
    *,
    manual: bool,
    minimum_character_speakers: int,
    minimum_distinct_voice_versions: int,
    require_uncached_nano_model_run: bool,
) -> ChainOutcome:
    if type(outcome) is not ChainOutcome:
        raise RunnerError("EXECUTOR_RESULT_INVALID")
    expected_approval = "manual_after_review" if manual else "auto_no_blockers"
    if (
        not all(
            type(value) is UUID
            for value in (
                outcome.request_id,
                outcome.script_version_id,
                outcome.edition_id,
            )
        )
        or any(
            value.variant != "specified in RFC 4122" or value.version is None
            for value in (
                outcome.request_id,
                outcome.script_version_id,
                outcome.edition_id,
            )
        )
        or outcome.approval_kind != expected_approval
        or type(outcome.edition_fingerprint) is not str
        or SHA256_PATTERN.fullmatch(outcome.edition_fingerprint) is None
        or type(outcome.initial_blocker_count) is not int
        or type(outcome.final_blocker_count) is not int
        or type(outcome.edition_count_for_request) is not int
        or type(outcome.manifest_revision) is not int
        or type(outcome.narrator_segment_count) is not int
        or type(outcome.character_segment_count) is not int
        or type(outcome.distinct_character_count) is not int
        or type(outcome.distinct_voice_version_count) is not int
        or type(outcome.uncached_nano_job_count) is not int
        or outcome.final_blocker_count != 0
        or outcome.edition_count_for_request != 1
        or outcome.manifest_revision < 1
        or outcome.narrator_segment_count < 1
        or outcome.character_segment_count < minimum_character_speakers
        or outcome.distinct_character_count < minimum_character_speakers
        or outcome.distinct_voice_version_count < minimum_distinct_voice_versions
        or (
            require_uncached_nano_model_run
            and outcome.uncached_nano_job_count < 1
        )
        or not outcome.model_run_fingerprints
        or len(outcome.model_run_fingerprints)
        != len(set(outcome.model_run_fingerprints))
        or any(
            type(value) is not str or SHA256_PATTERN.fullmatch(value) is None
            for value in outcome.model_run_fingerprints
        )
        or (manual and outcome.initial_blocker_count < 1)
        or (not manual and outcome.initial_blocker_count != 0)
    ):
        raise RunnerError("CHAIN_GATE_FAILED")
    return outcome


def _validate_technical(
    outcome: object,
    *,
    required_seconds: float,
) -> TechnicalOutcome:
    if type(outcome) is not TechnicalOutcome:
        raise RunnerError("EXECUTOR_RESULT_INVALID")
    _parse_utc_second(
        outcome.collector_collected_at,
        "TECHNICAL_GATE_FAILED",
    )
    numeric_valid = (
        all(
            type(value) in {int, float} and math.isfinite(float(value))
            for value in (
                outcome.stability_elapsed_seconds,
                outcome.chapter_audio_duration_seconds,
                outcome.request_to_ready_seconds,
            )
        )
        and type(outcome.time_to_first_audio_ms) is int
        and type(outcome.peak_memory_bytes) is int
        and type(outcome.seam_pairs_checked) is int
        and outcome.stability_elapsed_seconds >= required_seconds
        and outcome.chapter_audio_duration_seconds > 0
        and outcome.request_to_ready_seconds >= 0
        and outcome.time_to_first_audio_ms >= 0
        and outcome.peak_memory_bytes >= 0
        and outcome.seam_pairs_checked >= 1
    )
    if (
        not numeric_valid
        or any(type(code) is not int for code in outcome.range_status_codes)
        or set(outcome.range_status_codes) != {200, 206, 304, 416}
        or outcome.browser_viewports != ALLOWED_VIEWPORTS
        or outcome.browser_assistant_modes != ("collapsed", "expanded")
        or type(outcome.browser_console_error_count) is not int
        or outcome.browser_console_error_count != 0
        or type(outcome.browser_overlap_count) is not int
        or outcome.browser_overlap_count != 0
        or type(outcome.sidecar_restart_count) is not int
        or outcome.sidecar_restart_count != 0
        or type(outcome.health_failure_count) is not int
        or outcome.health_failure_count != 0
        or outcome.seek_latest_wins is not True
        or outcome.pending_gap_not_skipped is not True
        or type(outcome.edit_actions_created_tts_writes) is not int
        or outcome.edit_actions_created_tts_writes != 0
        or not outcome.listening_output_hashes
        or len(outcome.listening_output_hashes)
        != len(set(outcome.listening_output_hashes))
        or any(
            type(value) is not str or SHA256_PATTERN.fullmatch(value) is None
            for value in outcome.listening_output_hashes
        )
    ):
        raise RunnerError("TECHNICAL_GATE_FAILED")

    if (
        outcome.progressive_playback_gate_passed is not None
        and type(outcome.progressive_playback_gate_passed) is not bool
    ):
        raise RunnerError("TECHNICAL_PROGRESSIVE_EVIDENCE_INVALID")

    # The current signed report does not contain the ready-prefix/window
    # measurements required to prove the documented progressive-playback
    # alternative.  A caller-provided boolean therefore cannot waive the
    # prewarmed black-box RTF limit.
    black_box_rtf = (
        float(outcome.request_to_ready_seconds)
        / float(outcome.chapter_audio_duration_seconds)
    )
    if black_box_rtf > BLACK_BOX_RTF_LIMIT:
        raise RunnerError("TECHNICAL_RTF_GATE_FAILED")

    memory_observations = (
        outcome.host_paging_observed,
        outcome.sidecar_memory_growth_observed,
        outcome.qwenpaw_slowdown_observed,
    )
    memory_measurements = (
        outcome.pageout_delta,
        outcome.swapout_delta,
        outcome.memory_baseline_median_bytes,
        outcome.memory_tail_median_bytes,
        outcome.memory_growth_bytes,
        outcome.memory_growth_limit_bytes,
    )
    if any(value is None for value in (*memory_observations, *memory_measurements)):
        raise RunnerError("TECHNICAL_MEMORY_SAFETY_EVIDENCE_MISSING")
    if any(type(value) is not bool for value in memory_observations) or any(
        type(value) is not int or value < 0 for value in memory_measurements
    ):
        raise RunnerError("TECHNICAL_MEMORY_SAFETY_EVIDENCE_INVALID")
    measured_host_paging = (
        outcome.pageout_delta > 0 or outcome.swapout_delta > 0
    )
    measured_growth = max(
        0,
        outcome.memory_tail_median_bytes
        - outcome.memory_baseline_median_bytes,
    )
    measured_growth_limit = max(
        SIDECAR_MEMORY_GROWTH_MIN_LIMIT_BYTES,
        (
            outcome.memory_baseline_median_bytes
            * SIDECAR_MEMORY_GROWTH_PERCENT_NUMERATOR
            + SIDECAR_MEMORY_GROWTH_PERCENT_DENOMINATOR
            - 1
        )
        // SIDECAR_MEMORY_GROWTH_PERCENT_DENOMINATOR,
    )
    if (
        outcome.host_paging_observed is not measured_host_paging
        or outcome.memory_baseline_median_bytes > outcome.peak_memory_bytes
        or outcome.memory_tail_median_bytes > outcome.peak_memory_bytes
        or outcome.memory_growth_bytes != measured_growth
        or outcome.memory_growth_limit_bytes != measured_growth_limit
        or outcome.sidecar_memory_growth_observed
        is not (outcome.memory_growth_bytes > outcome.memory_growth_limit_bytes)
    ):
        raise RunnerError("TECHNICAL_MEMORY_SAFETY_EVIDENCE_INVALID")
    # ``host_paging_observed`` is derived from whole-host macOS vm_stat
    # counters.  It remains mandatory telemetry, but a background process can
    # increment it and the value cannot be attributed to this PawApp.  Enforce
    # the Sidecar's real 4 GiB container ceiling plus the independently
    # measured QwenPaw slowdown/restart/health gates instead.
    if (
        outcome.peak_memory_bytes > SIDECAR_PEAK_MEMORY_LIMIT_BYTES
        or outcome.sidecar_memory_growth_observed is True
        or outcome.qwenpaw_slowdown_observed is True
    ):
        raise RunnerError("TECHNICAL_MEMORY_SAFETY_GATE_FAILED")
    if (
        outcome.evidence_class not in {
            "local_operator_observation",
            "signed_controller_evidence",
        }
        or type(outcome.evidence_root_sha256) is not str
        or SHA256_PATTERN.fullmatch(outcome.evidence_root_sha256) is None
    ):
        raise RunnerError("TECHNICAL_EVIDENCE_PROVENANCE_INVALID")
    return outcome


def _technical_evidence(outcome: TechnicalOutcome) -> dict[str, object]:
    black_box_rtf = (
        float(outcome.request_to_ready_seconds)
        / float(outcome.chapter_audio_duration_seconds)
    )
    return {
        "state": "PASS",
        "stability_elapsed_seconds": round(outcome.stability_elapsed_seconds, 3),
        "chapter_audio_duration_seconds": round(
            outcome.chapter_audio_duration_seconds, 3
        ),
        "request_to_ready_seconds": round(outcome.request_to_ready_seconds, 3),
        "black_box_rtf": round(black_box_rtf, 6),
        "performance_gate": {
            "black_box_rtf_limit": BLACK_BOX_RTF_LIMIT,
            "black_box_rtf_passed": black_box_rtf <= BLACK_BOX_RTF_LIMIT,
            "progressive_playback_alternative": (
                "not_eligible_without_strict_ready_window_evidence"
            ),
            "host_paging_observed": outcome.host_paging_observed,
            "host_paging_interpretation": "whole_host_telemetry_only",
            "pageout_delta": outcome.pageout_delta,
            "swapout_delta": outcome.swapout_delta,
            "memory_baseline_median_bytes": (
                outcome.memory_baseline_median_bytes
            ),
            "memory_tail_median_bytes": outcome.memory_tail_median_bytes,
            "memory_growth_bytes": outcome.memory_growth_bytes,
            "memory_growth_limit_bytes": outcome.memory_growth_limit_bytes,
            "sidecar_memory_growth_observed": (
                outcome.sidecar_memory_growth_observed
            ),
            "qwenpaw_slowdown_observed": outcome.qwenpaw_slowdown_observed,
            "sidecar_peak_memory_limit_bytes": (
                SIDECAR_PEAK_MEMORY_LIMIT_BYTES
            ),
            "memory_safety_passed": (
                outcome.peak_memory_bytes
                <= SIDECAR_PEAK_MEMORY_LIMIT_BYTES
                and outcome.sidecar_memory_growth_observed is False
                and outcome.qwenpaw_slowdown_observed is False
            ),
        },
        "time_to_first_audio_ms": outcome.time_to_first_audio_ms,
        "peak_memory_bytes": outcome.peak_memory_bytes,
        "range_status_codes": sorted(outcome.range_status_codes),
        "seam_pairs_checked": outcome.seam_pairs_checked,
        "seek_latest_wins": outcome.seek_latest_wins,
        "pending_gap_not_skipped": outcome.pending_gap_not_skipped,
        "edit_actions_created_tts_writes": (
            outcome.edit_actions_created_tts_writes
        ),
        "evidence_class": outcome.evidence_class,
        "evidence_root_sha256": outcome.evidence_root_sha256,
        "browser_viewports": [
            {"width": width, "height": height}
            for width, height in outcome.browser_viewports
        ],
        "browser_assistant_modes": list(outcome.browser_assistant_modes),
        "browser_console_error_count": outcome.browser_console_error_count,
        "browser_overlap_count": outcome.browser_overlap_count,
        "sidecar_restart_count": outcome.sidecar_restart_count,
        "health_failure_count": outcome.health_failure_count,
        "listening_output_hashes": sorted(outcome.listening_output_hashes),
        "collector_collected_at": outcome.collector_collected_at,
        "rtf_kind": "request_to_ready_black_box",
    }


def _validate_baseline(value: object) -> BaselineSnapshot:
    if type(value) is not BaselineSnapshot:
        raise RunnerError("BASELINE_INVALID")
    if (
        type(value.draft_version) is not int
        or value.draft_version < 1
        or type(value.pointer_version) is not int
        or value.pointer_version < 1
        or type(value.edition_history_count) is not int
        or value.edition_history_count < 1
    ):
        raise RunnerError("BASELINE_INVALID")
    identity_values = (
        value.current_edition_id,
        value.current_script_version_id,
    )
    if (
        not all(type(item) is UUID for item in identity_values)
        or any(
            item.variant != "specified in RFC 4122" or item.version is None
            for item in identity_values
        )
        or (
            value.base_revision_id is not None
            and (
                type(value.base_revision_id) is not UUID
                or value.base_revision_id.variant != "specified in RFC 4122"
                or value.base_revision_id.version is None
            )
        )
    ):
        raise RunnerError("BASELINE_INVALID")
    _validate_sha256(value.content_hash, "BASELINE_INVALID")
    if (
        type(value.content_markdown) is not str
        or len(value.content_markdown) > MAX_SOURCE_CODEPOINTS
        or value.content_markdown
        != unicodedata.normalize("NFC", value.content_markdown)
    ):
        raise RunnerError("BASELINE_INVALID")
    try:
        value.content_markdown.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise RunnerError("BASELINE_INVALID") from error
    if _sha256_text(value.content_markdown) != value.content_hash:
        raise RunnerError("BASELINE_INVALID")
    return value


def _validate_recovery_outcome(
    value: object,
    *,
    baseline: BaselineSnapshot,
) -> RecoveryOutcome:
    if type(value) is not RecoveryOutcome:
        raise RunnerError("RECOVERY_RESULT_INVALID")
    identities = (
        value.restored_current_edition_id,
        value.restored_current_script_version_id,
    )
    if (
        type(value.restored_draft_version) is not int
        or value.restored_draft_version < baseline.draft_version
        or type(value.pointer_version_after_restore) is not int
        or value.pointer_version_after_restore < baseline.pointer_version
        or type(value.new_authoritative_record_count) is not int
        or value.new_authoritative_record_count < 0
        or value.append_only_history_retained is not True
        or value.restored_content_hash != baseline.content_hash
        or value.restored_current_edition_id != baseline.current_edition_id
        or value.restored_current_script_version_id
        != baseline.current_script_version_id
        or not all(type(item) is UUID for item in identities)
    ):
        raise RunnerError("RECOVERY_GATE_FAILED")
    return value


def _restoration_evidence(
    outcome: RecoveryOutcome,
) -> dict[str, object]:
    return {
        "working_copy_content_restored": True,
        "author_visible_edition_restored": True,
        "append_only_history_retained": outcome.append_only_history_retained,
        "new_authoritative_record_count": (
            outcome.new_authoritative_record_count
        ),
    }


def _validate_restoration_evidence(
    value: object,
) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise RunnerError("RECOVERY_RECORD_INVALID")
    _require_exact_keys(
        value,
        {
            "working_copy_content_restored",
            "author_visible_edition_restored",
            "append_only_history_retained",
            "new_authoritative_record_count",
        },
        "RECOVERY_RECORD_INVALID",
    )
    if (
        value["working_copy_content_restored"] is not True
        or value["author_visible_edition_restored"] is not True
        or value["append_only_history_retained"] is not True
        or type(value["new_authoritative_record_count"]) is not int
        or value["new_authoritative_record_count"] < 0
    ):
        raise RunnerError("RECOVERY_RECORD_INVALID")
    return value


def _recovery_payload(
    config: RunnerConfig,
    fixture: ChapterFixture,
    baseline: BaselineSnapshot,
    fence: RecoveryFence,
    claim_binding: RecoveryClaimBinding,
    private_directory: _SecureDirectory,
    *,
    run_id: str,
    state: str,
    completed_steps: Sequence[str],
    generation: int,
    previous_record_sha256: str | None,
    baseline_restored: bool = False,
    restoration_evidence: Mapping[str, object] | None = None,
    sealed_technical_result: Mapping[str, object] | None = None,
    sealed_final_result: Mapping[str, object] | None = None,
    write_intent: RecoveryWriteIntent | None = None,
    error_code: str | None = None,
    schema_version: str = RECOVERY_SCHEMA,
) -> dict[str, object]:
    fence = _validate_recovery_fence(fence)
    claim_binding = _validate_recovery_claim_binding(claim_binding)
    private_directory.assert_stable()
    path_digest, identity_digest = recovery_private_directory_binding(
        private_directory.path,
        private_directory.opened_identity,
    )
    if (
        path_digest != claim_binding.private_work_dir_canonical_sha256
        or identity_digest != claim_binding.private_work_dir_identity_sha256
    ):
        raise RunnerError("RECOVERY_CLAIM_DIRECTORY_MISMATCH")
    if restoration_evidence is not None:
        restoration_evidence = _validate_restoration_evidence(
            restoration_evidence
        )
    if (
        type(schema_version) is not str
        or schema_version
        not in {
            LEGACY_RECOVERY_SCHEMA,
            PREVIOUS_RECOVERY_SCHEMA,
            RECOVERY_SCHEMA,
        }
        or (
            schema_version == LEGACY_RECOVERY_SCHEMA
            and restoration_evidence is not None
        )
        or (
            schema_version in {PREVIOUS_RECOVERY_SCHEMA, RECOVERY_SCHEMA}
            and baseline_restored
            and restoration_evidence is None
        )
        or (not baseline_restored and restoration_evidence is not None)
        or type(generation) is not int
        or generation < 1
        or (
            generation == 1
            and previous_record_sha256 is not None
        )
        or (
            generation > 1
            and (
                not isinstance(previous_record_sha256, str)
                or SHA256_PATTERN.fullmatch(previous_record_sha256) is None
            )
        )
    ):
        raise RunnerError("RECOVERY_RECORD_INVALID")
    unsigned: dict[str, object] = {
        "schema_version": schema_version,
        "work_package": WORK_PACKAGE,
        "run_id": run_id,
        "created_at": _utc_now(),
        "state": state,
        "generation": generation,
        "previous_record_sha256": previous_record_sha256,
        "novel_id": str(config.novel_id),
        "document_id": str(config.document_id),
        "fixture": {
            "fixture_id": fixture.fixture_id,
            "manifest_sha256": fixture.manifest_sha256,
            "automatic_case_id": fixture.automatic.case_id,
            "manual_case_id": fixture.manual.case_id,
        },
        "claim": {
            "claim_identity_sha256": claim_binding.claim_identity_sha256,
            "envelope_fingerprint_sha256": (
                claim_binding.envelope_fingerprint_sha256
            ),
            "private_work_dir_canonical_sha256": path_digest,
            "private_work_dir_identity_sha256": identity_digest,
        },
        "baseline_restored": baseline_restored,
        "completed_steps": list(completed_steps),
        "ownership_fence": _recovery_fence_payload(fence),
        "baseline": {
            "draft_version": baseline.draft_version,
            "content_hash": baseline.content_hash,
            "content_markdown": baseline.content_markdown,
            "base_revision_id": (
                str(baseline.base_revision_id)
                if baseline.base_revision_id is not None
                else None
            ),
            "pointer_version": baseline.pointer_version,
            "current_edition_id": str(baseline.current_edition_id),
            "current_script_version_id": str(
                baseline.current_script_version_id
            ),
            "edition_history_count": baseline.edition_history_count,
        },
    }
    if restoration_evidence is not None:
        unsigned["restoration_evidence"] = dict(restoration_evidence)
    if sealed_technical_result is not None:
        sealed_value = dict(sealed_technical_result)
        if (
            schema_version == RECOVERY_SCHEMA
            and sealed_value.get("result_schema_version") != RESULT_SCHEMA
        ):
            raise RunnerError("RECOVERY_RECORD_INVALID")
        if (
            schema_version != RECOVERY_SCHEMA
            and "result_schema_version" in sealed_value
        ):
            raise RunnerError("RECOVERY_RECORD_INVALID")
        unsigned["sealed_technical_result"] = {
            "result": sealed_value,
            "self_sha256": _sha256_bytes(
                _canonical_json_bytes(sealed_value)
            ),
        }
    if sealed_final_result is not None:
        final_value = dict(sealed_final_result)
        unsigned["sealed_final_result"] = {
            "result": final_value,
            "self_sha256": _sha256_bytes(
                _canonical_json_bytes(final_value)
            ),
        }
    if write_intent is not None:
        if write_intent.old_fence != fence:
            raise RunnerError("RECOVERY_WRITE_INTENT_INVALID")
        unsigned["write_intent"] = _recovery_write_intent_payload(
            write_intent
        )
    if error_code is not None:
        unsigned["error_code"] = error_code
    return {
        **unsigned,
        "self_sha256": _sha256_bytes(_canonical_json_bytes(unsigned)),
    }


def _load_recovery_baseline(
    private_directory: _SecureDirectory,
    config: RunnerConfig,
    fixture: ChapterFixture,
    claim_binding: RecoveryClaimBinding,
) -> LoadedRecovery:
    if not _entry_exists(
        private_directory,
        "recovery.json",
        "RECOVERY_RECORD_UNSAFE",
    ):
        raise RunnerError("RECOVERY_RECORD_NOT_FOUND")
    payload = _read_directory_json(
        private_directory,
        "recovery.json",
        "RECOVERY_RECORD_INVALID",
        maximum_bytes=MAX_RECOVERY_BYTES,
    )
    required = {
        "schema_version",
        "work_package",
        "run_id",
        "created_at",
        "state",
        "generation",
        "previous_record_sha256",
        "novel_id",
        "document_id",
        "fixture",
        "claim",
        "baseline_restored",
        "completed_steps",
        "ownership_fence",
        "baseline",
        "self_sha256",
    }
    optional = {
        "error_code",
        "restoration_evidence",
        "sealed_technical_result",
        "sealed_final_result",
        "write_intent",
    }
    if (
        not required.issubset(payload)
        or not (set(payload) - required).issubset(optional)
    ):
        raise RunnerError("RECOVERY_RECORD_INVALID")
    supplied_self = _validate_sha256(
        payload["self_sha256"],
        "RECOVERY_RECORD_INVALID",
    )
    unsigned = dict(payload)
    del unsigned["self_sha256"]
    if _sha256_bytes(_canonical_json_bytes(unsigned)) != supplied_self:
        raise RunnerError("RECOVERY_RECORD_INVALID")
    generation = payload["generation"]
    previous_record_sha256 = payload["previous_record_sha256"]
    if (
        type(generation) is not int
        or generation < 1
        or (
            generation == 1
            and previous_record_sha256 is not None
        )
        or (
            generation > 1
            and (
                not isinstance(previous_record_sha256, str)
                or SHA256_PATTERN.fullmatch(previous_record_sha256) is None
            )
        )
    ):
        raise RunnerError("RECOVERY_RECORD_INVALID")
    claim_binding = _validate_recovery_claim_binding(claim_binding)
    private_directory.assert_stable()
    path_digest, identity_digest = recovery_private_directory_binding(
        private_directory.path,
        private_directory.opened_identity,
    )
    claim_payload = payload["claim"]
    if not isinstance(claim_payload, dict):
        raise RunnerError("RECOVERY_RECORD_INVALID")
    _require_exact_keys(
        claim_payload,
        {
            "claim_identity_sha256",
            "envelope_fingerprint_sha256",
            "private_work_dir_canonical_sha256",
            "private_work_dir_identity_sha256",
        },
        "RECOVERY_RECORD_INVALID",
    )
    expected_claim = {
        "claim_identity_sha256": claim_binding.claim_identity_sha256,
        "envelope_fingerprint_sha256": (
            claim_binding.envelope_fingerprint_sha256
        ),
        "private_work_dir_canonical_sha256": path_digest,
        "private_work_dir_identity_sha256": identity_digest,
    }
    if claim_payload != expected_claim:
        raise RunnerError("RECOVERY_RECORD_CLAIM_MISMATCH")
    fixture_payload = payload["fixture"]
    if not isinstance(fixture_payload, dict):
        raise RunnerError("RECOVERY_RECORD_INVALID")
    _require_exact_keys(
        fixture_payload,
        {
            "fixture_id",
            "manifest_sha256",
            "automatic_case_id",
            "manual_case_id",
        },
        "RECOVERY_RECORD_INVALID",
    )
    schema_version = payload["schema_version"]
    if (
        type(schema_version) is not str
        or schema_version
        not in {
            LEGACY_RECOVERY_SCHEMA,
            PREVIOUS_RECOVERY_SCHEMA,
            RECOVERY_SCHEMA,
        }
        or payload["work_package"] != WORK_PACKAGE
        or fixture_payload
        != {
            "fixture_id": fixture.fixture_id,
            "manifest_sha256": fixture.manifest_sha256,
            "automatic_case_id": fixture.automatic.case_id,
            "manual_case_id": fixture.manual.case_id,
        }
        or _parse_uuid(payload["novel_id"], "RECOVERY_RECORD_INVALID")
        != config.novel_id
        or _parse_uuid(payload["document_id"], "RECOVERY_RECORD_INVALID")
        != config.document_id
    ):
        raise RunnerError("RECOVERY_RECORD_SCOPE_MISMATCH")
    recovered_run_id = _parse_canonical_uuid(
        payload["run_id"],
        "RECOVERY_RECORD_INVALID",
    )
    if recovered_run_id != config.run_id:
        raise RunnerError("RECOVERY_RECORD_RUN_MISMATCH")
    run_id = str(recovered_run_id)
    state_value = payload["state"]
    if state_value not in {
        "BASELINE_CAPTURED",
        "AUTOMATIC_COMPLETE",
        "MANUAL_COMPLETE",
        "TECHNICAL_COMPLETE",
        "RECOVERY_REQUIRED",
        "LISTENING_PENDING",
        "FINALIZATION_PENDING",
    }:
        raise RunnerError("RECOVERY_RECORD_INVALID")
    completed_steps = payload["completed_steps"]
    allowed_steps = ["automatic_chain", "manual_chain", "technical_checks"]
    if (
        not isinstance(completed_steps, list)
        or completed_steps != allowed_steps[: len(completed_steps)]
    ):
        raise RunnerError("RECOVERY_RECORD_INVALID")
    baseline_restored = payload["baseline_restored"]
    if type(baseline_restored) is not bool:
        raise RunnerError("RECOVERY_RECORD_INVALID")
    restoration_evidence: Mapping[str, object] | None = None
    if "restoration_evidence" in payload:
        restoration_evidence = _validate_restoration_evidence(
            payload["restoration_evidence"]
        )
    if (
        (
            schema_version == LEGACY_RECOVERY_SCHEMA
            and restoration_evidence is not None
        )
        or (
            schema_version in {PREVIOUS_RECOVERY_SCHEMA, RECOVERY_SCHEMA}
            and baseline_restored
            and restoration_evidence is None
        )
        or (not baseline_restored and restoration_evidence is not None)
    ):
        raise RunnerError("RECOVERY_RECORD_INVALID")
    if "error_code" in payload and (
        not isinstance(payload["error_code"], str)
        or not SAFE_CODE_PATTERN.fullmatch(payload["error_code"])
    ):
        raise RunnerError("RECOVERY_RECORD_INVALID")
    baseline_payload = payload["baseline"]
    if not isinstance(baseline_payload, dict):
        raise RunnerError("RECOVERY_RECORD_INVALID")
    _require_exact_keys(
        baseline_payload,
        {
            "draft_version",
            "content_hash",
            "content_markdown",
            "base_revision_id",
            "pointer_version",
            "current_edition_id",
            "current_script_version_id",
            "edition_history_count",
        },
        "RECOVERY_RECORD_INVALID",
    )
    draft_version = baseline_payload["draft_version"]
    if type(draft_version) is not int:
        raise RunnerError("RECOVERY_RECORD_INVALID")
    base_revision_raw = baseline_payload["base_revision_id"]
    baseline_markdown = baseline_payload["content_markdown"]
    if type(baseline_markdown) is not str:
        raise RunnerError("RECOVERY_RECORD_INVALID")
    baseline = _validate_baseline(
        BaselineSnapshot(
            draft_version=draft_version,
            content_hash=_validate_sha256(
                baseline_payload["content_hash"], "RECOVERY_RECORD_INVALID"
            ),
            content_markdown=baseline_markdown,
            base_revision_id=(
                _parse_uuid(base_revision_raw, "RECOVERY_RECORD_INVALID")
                if base_revision_raw is not None
                else None
            ),
            pointer_version=(
                baseline_payload["pointer_version"]
                if type(baseline_payload["pointer_version"]) is int
                else -1
            ),
            current_edition_id=_parse_uuid(
                baseline_payload["current_edition_id"],
                "RECOVERY_RECORD_INVALID",
            ),
            current_script_version_id=_parse_uuid(
                baseline_payload["current_script_version_id"],
                "RECOVERY_RECORD_INVALID",
            ),
            edition_history_count=(
                baseline_payload["edition_history_count"]
                if type(baseline_payload["edition_history_count"]) is int
                else -1
            ),
        )
    )
    fence = _parse_recovery_fence_payload(
        payload["ownership_fence"],
        "RECOVERY_RECORD_INVALID",
    )
    write_intent: RecoveryWriteIntent | None = None
    if "write_intent" in payload:
        intent_payload = payload["write_intent"]
        if not isinstance(intent_payload, dict):
            raise RunnerError("RECOVERY_RECORD_INVALID")
        _require_exact_keys(
            intent_payload,
            {
                "operation_kind",
                "operation_fingerprint_sha256",
                "old_fence",
                "next_fence",
            },
            "RECOVERY_RECORD_INVALID",
        )
        write_intent = _validate_recovery_write_intent(
            RecoveryWriteIntent(
                operation_kind=(
                    intent_payload["operation_kind"]
                    if isinstance(intent_payload["operation_kind"], str)
                    else ""
                ),
                operation_fingerprint_sha256=_validate_sha256(
                    intent_payload["operation_fingerprint_sha256"],
                    "RECOVERY_RECORD_INVALID",
                ),
                old_fence=_parse_recovery_fence_payload(
                    intent_payload["old_fence"],
                    "RECOVERY_RECORD_INVALID",
                ),
                next_fence=_parse_recovery_fence_payload(
                    intent_payload["next_fence"],
                    "RECOVERY_RECORD_INVALID",
                ),
            )
        )
        if write_intent.old_fence != fence:
            raise RunnerError("RECOVERY_RECORD_INVALID")
    sealed: Mapping[str, object] | None = None
    if "sealed_technical_result" in payload:
        sealed_payload = payload["sealed_technical_result"]
        if not isinstance(sealed_payload, dict):
            raise RunnerError("RECOVERY_RECORD_INVALID")
        _require_exact_keys(
            sealed_payload,
            {"result", "self_sha256"},
            "RECOVERY_RECORD_INVALID",
        )
        sealed_value = sealed_payload["result"]
        if not isinstance(sealed_value, dict):
            raise RunnerError("RECOVERY_RECORD_INVALID")
        sealed_keys = {
            "automatic_chain",
            "manual_chain",
            "technical_checks",
        }
        if schema_version == RECOVERY_SCHEMA:
            sealed_keys.add("result_schema_version")
        _require_exact_keys(
            sealed_value,
            sealed_keys,
            "RECOVERY_RECORD_INVALID",
        )
        if (
            (
                schema_version == RECOVERY_SCHEMA
                and sealed_value.get("result_schema_version") != RESULT_SCHEMA
            )
            or
            _validate_sha256(
                sealed_payload["self_sha256"],
                "RECOVERY_RECORD_INVALID",
            )
            != _sha256_bytes(_canonical_json_bytes(sealed_value))
        ):
            raise RunnerError("RECOVERY_RECORD_INVALID")
        sealed = sealed_value
    sealed_final: Mapping[str, object] | None = None
    if "sealed_final_result" in payload:
        final_payload = payload["sealed_final_result"]
        if not isinstance(final_payload, dict):
            raise RunnerError("RECOVERY_RECORD_INVALID")
        _require_exact_keys(
            final_payload,
            {"result", "self_sha256"},
            "RECOVERY_RECORD_INVALID",
        )
        final_value = final_payload["result"]
        if not isinstance(final_value, dict):
            raise RunnerError("RECOVERY_RECORD_INVALID")
        _require_exact_keys(
            final_value,
            {"exit_code", "evidence"},
            "RECOVERY_RECORD_INVALID",
        )
        if (
            type(final_value["exit_code"]) is not int
            or final_value["exit_code"] not in {0, 2, 130}
            or not isinstance(final_value["evidence"], dict)
            or _validate_sha256(
                final_payload["self_sha256"],
                "RECOVERY_RECORD_INVALID",
            )
            != _sha256_bytes(_canonical_json_bytes(final_value))
        ):
            raise RunnerError("RECOVERY_RECORD_INVALID")
        sealed_final = final_value
    if (
        (state_value == "LISTENING_PENDING" and not baseline_restored)
        or (state_value == "LISTENING_PENDING" and sealed is None)
        or (sealed is not None and completed_steps != allowed_steps)
        or (
            state_value == "FINALIZATION_PENDING"
            and (
                not baseline_restored
                or sealed_final is None
                or write_intent is not None
            )
        )
        or (
            state_value != "FINALIZATION_PENDING"
            and sealed_final is not None
        )
    ):
        raise RunnerError("RECOVERY_RECORD_INVALID")
    return LoadedRecovery(
        schema_version=schema_version,
        run_id=run_id,
        state=state_value,
        baseline=baseline,
        fence=fence,
        write_intent=write_intent,
        completed_steps=tuple(completed_steps),
        baseline_restored=baseline_restored,
        restoration_evidence=restoration_evidence,
        sealed_technical_result=sealed,
        sealed_final_result=sealed_final,
        generation=generation,
        previous_record_sha256=previous_record_sha256,
        record_sha256=_recovery_record_sha256(payload),
    )


def _install_recovery_payload(
    private_directory: _SecureDirectory,
    payload: Mapping[str, object],
    cursor: _RecoveryRecordCursor,
    *,
    exclusive: bool = False,
) -> None:
    if exclusive:
        _atomic_create_json(
            private_directory,
            "recovery.json",
            payload,
            code="RECOVERY_RECORD_WRITE_FAILED",
            exists_code="RECOVERY_RECORD_EXISTS",
        )
    else:
        _atomic_write_json(
            private_directory,
            "recovery.json",
            payload,
            "RECOVERY_RECORD_WRITE_FAILED",
        )
    cursor.committed(payload)


def _load_listening_files(
    path: Path,
) -> tuple[
    bytes,
    dict[str, object],
    bytes,
    dict[str, object],
    dict[str, str],
]:
    output_directory = _open_secure_directory(
        path.parent,
        "LISTENING_RECORD_INVALID",
    )
    try:
        raw_record, payload = _load_private_json_document(
            path,
            "LISTENING_RECORD_INVALID",
        )
        raw_receipt, receipt = _load_private_json_document(
            path.with_name(LISTENING_FINALIZATION_RECEIPT_FILENAME),
            "LISTENING_RECEIPT_INVALID",
        )
        output_directory.assert_stable()
        output_metadata = os.fstat(output_directory.descriptor)
        output_binding = {
            "output_directory_canonical_sha256": _sha256_text(
                str(output_directory.path)
            ),
            "output_directory_identity_sha256": _sha256_bytes(
                _canonical_json_bytes(
                    {
                        "st_dev": output_metadata.st_dev,
                        "st_ino": output_metadata.st_ino,
                        "st_uid": output_metadata.st_uid,
                        "st_mode": output_metadata.st_mode,
                    }
                )
            ),
        }
        output_directory.assert_stable()
        return raw_record, payload, raw_receipt, receipt, output_binding
    finally:
        output_directory.close()


def _load_listening_record(
    path: Path | None,
    *,
    run_id: UUID,
    novel_id: UUID,
    document_id: UUID,
    automatic_edition_id_sha256: str,
    automatic_edition_fingerprint_sha256: str,
    manual_edition_id_sha256: str,
    manual_edition_fingerprint_sha256: str,
    expected_output_hashes: tuple[str, ...],
    collector_collected_at: str,
) -> dict[str, object]:
    if path is None:
        return {"state": "PENDING"}
    if (
        not isinstance(path, Path)
        or path.name != "listening.json"
        or any(type(value) is not UUID for value in (run_id, novel_id, document_id))
    ):
        raise RunnerError("LISTENING_RECORD_INVALID")
    _validate_sha256(
        automatic_edition_id_sha256,
        "LISTENING_RECORD_INVALID",
    )
    _validate_sha256(
        automatic_edition_fingerprint_sha256,
        "LISTENING_RECORD_INVALID",
    )
    collected_at = _parse_utc_second(
        collector_collected_at,
        "LISTENING_RECORD_INVALID",
    )
    _validate_sha256(
        manual_edition_id_sha256,
        "LISTENING_RECORD_INVALID",
    )
    _validate_sha256(
        manual_edition_fingerprint_sha256,
        "LISTENING_RECORD_INVALID",
    )
    raw_record, payload, raw_receipt, receipt, output_binding = (
        _load_listening_files(path)
    )
    _require_exact_keys(
        payload,
        {
            "schema_version",
            "reviewer_pseudonym",
            "reviewed_at",
            "verdict",
            "output_hashes",
            "checks",
        },
        "LISTENING_RECORD_INVALID",
    )
    if payload["schema_version"] != LISTENING_SCHEMA:
        raise RunnerError("LISTENING_RECORD_INVALID")
    reviewer = _safe_identifier(
        payload["reviewer_pseudonym"], "LISTENING_RECORD_INVALID"
    )
    reviewed_at = payload["reviewed_at"]
    if not isinstance(reviewed_at, str) or len(reviewed_at) != 20:
        raise RunnerError("LISTENING_RECORD_INVALID")
    parsed_reviewed_at = _parse_utc_second(
        reviewed_at,
        "LISTENING_RECORD_INVALID",
    )
    if (
        parsed_reviewed_at < collected_at
        or parsed_reviewed_at
        > collected_at
        + timedelta(seconds=LISTENING_AUTHORIZATION_MAX_SECONDS)
    ):
        raise RunnerError("LISTENING_TIME_INVALID")
    verdict = payload["verdict"]
    if verdict not in {"pass", "fail"}:
        raise RunnerError("LISTENING_RECORD_INVALID")
    hashes = payload["output_hashes"]
    if (
        type(hashes) is not list
        or not hashes
        or hashes != sorted(set(hashes))
        or not all(
            type(item) is str and SHA256_PATTERN.fullmatch(item)
            for item in hashes
        )
    ):
        raise RunnerError("LISTENING_RECORD_INVALID")
    if tuple(hashes) != tuple(sorted(expected_output_hashes)):
        raise RunnerError("LISTENING_OUTPUT_MISMATCH")
    checks = payload["checks"]
    expected_checks = {
        "narrator_character_distinguishable",
        "voices_stable",
        "no_missing_or_repeated_text",
        "all_samples_intelligible_mandarin",
        "no_abnormal_pause_or_seam",
        "loudness_consistent",
    }
    if not isinstance(checks, dict):
        raise RunnerError("LISTENING_RECORD_INVALID")
    _require_exact_keys(checks, expected_checks, "LISTENING_RECORD_INVALID")
    if any(type(checks[key]) is not bool for key in expected_checks):
        raise RunnerError("LISTENING_RECORD_INVALID")

    expected_binding = {
        "run_fingerprint_sha256": _sha256_text(str(run_id)),
        "target_scope_sha256": _sha256_text(f"{novel_id}:{document_id}"),
        "automatic_edition_id_sha256": automatic_edition_id_sha256,
        "automatic_edition_fingerprint_sha256": (
            automatic_edition_fingerprint_sha256
        ),
        "manual_edition_id_sha256": manual_edition_id_sha256,
        "manual_edition_fingerprint_sha256": (
            manual_edition_fingerprint_sha256
        ),
    }
    _require_exact_keys(
        receipt,
        {
            "schema_version",
            "finalized_at",
            "verdict",
            "probe_request_fingerprint_sha256",
            *expected_binding,
            "listening_record_sha256",
            "reviewed_roles",
        },
        "LISTENING_RECEIPT_INVALID",
    )
    record_sha256 = _sha256_bytes(raw_record)
    if (
        receipt["schema_version"]
        != LISTENING_FINALIZATION_RECEIPT_SCHEMA
        or receipt["finalized_at"] != reviewed_at
        or receipt["verdict"] != verdict
        or receipt["listening_record_sha256"] != record_sha256
        or receipt["reviewed_roles"] != ["旁白", "林晚", "沈川"]
        or not isinstance(receipt["probe_request_fingerprint_sha256"], str)
        or SHA256_PATTERN.fullmatch(
            receipt["probe_request_fingerprint_sha256"]
        )
        is None
        or any(receipt[key] != value for key, value in expected_binding.items())
    ):
        raise RunnerError("LISTENING_RECEIPT_INVALID")

    claim_path = LISTENING_CLAIM_REGISTRY_DIRECTORY / (
        f"{expected_binding['run_fingerprint_sha256']}.claim"
    )
    raw_claim, claim = _load_private_json_document(
        claim_path,
        "LISTENING_CLAIM_INVALID",
    )
    commit_path = claim_path.with_suffix(".commit")
    _raw_commit, commit = _load_private_json_document(
        commit_path,
        "LISTENING_COMMIT_INVALID",
    )
    _require_exact_keys(
        claim,
        {
            "schema_version",
            "state",
            "claimed_at",
            "verdict",
            "probe_request_fingerprint_sha256",
            *expected_binding,
            "listening_record_sha256",
            "finalization_receipt_sha256",
            *output_binding,
            "self_sha256",
        },
        "LISTENING_CLAIM_INVALID",
    )
    claim_self = _validate_sha256(
        claim["self_sha256"],
        "LISTENING_CLAIM_INVALID",
    )
    unsigned_claim = dict(claim)
    del unsigned_claim["self_sha256"]
    receipt_sha256 = _sha256_bytes(raw_receipt)
    if (
        claim["schema_version"] != LISTENING_CLAIM_SCHEMA
        or claim["state"] != "PREPARED"
        or claim["claimed_at"] != reviewed_at
        or claim["verdict"] != verdict
        or claim["probe_request_fingerprint_sha256"]
        != receipt["probe_request_fingerprint_sha256"]
        or claim["listening_record_sha256"] != record_sha256
        or claim["finalization_receipt_sha256"]
        != receipt_sha256
        or any(claim[key] != value for key, value in expected_binding.items())
        or any(claim[key] != value for key, value in output_binding.items())
        or claim_self != _sha256_bytes(_canonical_json_bytes(unsigned_claim))
    ):
        raise RunnerError("LISTENING_CLAIM_INVALID")
    _require_exact_keys(
        commit,
        {
            "schema_version",
            "state",
            "committed_at",
            "claim_sha256",
            "run_fingerprint_sha256",
            "listening_record_sha256",
            "finalization_receipt_sha256",
            *output_binding,
            "self_sha256",
        },
        "LISTENING_COMMIT_INVALID",
    )
    commit_self = _validate_sha256(
        commit["self_sha256"],
        "LISTENING_COMMIT_INVALID",
    )
    unsigned_commit = dict(commit)
    del unsigned_commit["self_sha256"]
    committed_at = _parse_utc_second(
        commit["committed_at"],
        "LISTENING_COMMIT_INVALID",
    )
    if (
        commit["schema_version"] != LISTENING_COMMIT_SCHEMA
        or commit["state"] != "COMMITTED"
        or committed_at < parsed_reviewed_at
        or commit["claim_sha256"] != _sha256_bytes(raw_claim)
        or commit["run_fingerprint_sha256"]
        != expected_binding["run_fingerprint_sha256"]
        or commit["listening_record_sha256"] != record_sha256
        or commit["finalization_receipt_sha256"] != receipt_sha256
        or any(commit[key] != value for key, value in output_binding.items())
        or commit_self != _sha256_bytes(_canonical_json_bytes(unsigned_commit))
    ):
        raise RunnerError("LISTENING_COMMIT_INVALID")
    passed = verdict == "pass" and all(checks.values())
    return {
        "state": "PASS" if passed else "FAIL",
        "reviewer_fingerprint_sha256": _sha256_text(reviewer),
        "reviewed_at": reviewed_at,
        "output_hashes": sorted(hashes),
        "checks": dict(checks),
    }


def _listening_template() -> bytes:
    return (
        "# T4-K 人工听感记录\n\n"
        "状态：`PENDING`。未实际听完前不得改为通过。\n\n"
        "必须另行提供 `moss-tts-chapter-listening/1.0` JSON，记录：\n\n"
        "- 旁白与人物可辨识；\n"
        "- 人物音色稳定；\n"
        "- 无严重漏字或重复；\n"
        "- 无异常停顿、爆音、吞字或长空白；\n"
        "- 响度基本一致。\n"
    ).encode("utf-8")


def _write_evidence(
    output_directory: _SecureDirectory,
    result: Mapping[str, object],
) -> None:
    _atomic_write_json(
        output_directory,
        "result.json",
        result,
        "EVIDENCE_WRITE_FAILED",
    )
    _atomic_write(
        output_directory,
        "listening-template.md",
        _listening_template(),
        "EVIDENCE_WRITE_FAILED",
    )


def _result_error(result: dict[str, object], code: str, status_value: str) -> None:
    result["status"] = status_value
    errors = result["error_codes"]
    assert isinstance(errors, list)
    if code not in errors:
        errors.append(code)


def _notify_recovery_state(
    observer: RecoveryStateObserver | None,
    state_value: str,
    cursor: _RecoveryRecordCursor,
) -> None:
    if observer is None:
        return
    if cursor.generation < 1 or cursor.record_sha256 is None:
        raise RunnerError("RECOVERY_RECORD_INVALID")
    try:
        observer(
            state_value,
            cursor.generation,
            cursor.record_sha256,
        )
    except RunnerError:
        raise
    except Exception as error:
        raise RunnerError("RECOVERY_CLAIM_TRANSITION_FAILED") from error


def _claim_state_for_recovery_state(state_value: str) -> str:
    mapping = {
        "BASELINE_CAPTURED": "BASELINE_SEALED",
        "AUTOMATIC_COMPLETE": "BASELINE_SEALED",
        "MANUAL_COMPLETE": "BASELINE_SEALED",
        "TECHNICAL_COMPLETE": "TECHNICAL_COMPLETE",
        "RECOVERY_REQUIRED": "RECOVERY_REQUIRED",
        "LISTENING_PENDING": "LISTENING_PENDING",
        "FINALIZATION_PENDING": "FINALIZATION_PENDING",
    }
    try:
        return mapping[state_value]
    except KeyError as error:
        raise RunnerError("RECOVERY_RECORD_INVALID") from error


def _validate_claim_recovery_head(
    loaded: LoadedRecovery,
    reader: RecoveryClaimStateReader | None,
    observer: RecoveryStateObserver | None,
) -> None:
    if reader is None:
        raise RunnerError("RECOVERY_CLAIM_STATE_READER_REQUIRED")
    try:
        snapshot = reader()
    except RunnerError:
        raise
    except Exception as error:
        raise RunnerError("RECOVERY_CLAIM_STATE_INVALID") from error
    if type(snapshot) is not RecoveryClaimSnapshot:
        raise RunnerError("RECOVERY_CLAIM_STATE_INVALID")
    expected_state = _claim_state_for_recovery_state(loaded.state)
    state_matches = snapshot.state == expected_state
    # FINALIZED may retain the exact FINALIZATION_PENDING record only across
    # the narrow crash window between claim finalization and secure unlink.
    if snapshot.state == "FINALIZED" and loaded.state == "FINALIZATION_PENDING":
        state_matches = True
    exact = (
        state_matches
        and snapshot.recovery_generation == loaded.generation
        and snapshot.latest_recovery_sha256 == loaded.record_sha256
    )
    if exact:
        return
    allowed_one_ahead = {
        "PREPARED": {"BASELINE_SEALED"},
        "BASELINE_SEALED": {
            "BASELINE_SEALED",
            "TECHNICAL_COMPLETE",
            "RECOVERY_REQUIRED",
            "FINALIZATION_PENDING",
        },
        "TECHNICAL_COMPLETE": {
            "TECHNICAL_COMPLETE",
            "RECOVERY_REQUIRED",
            "LISTENING_PENDING",
            "FINALIZATION_PENDING",
        },
        "RECOVERY_REQUIRED": {
            "RECOVERY_REQUIRED",
            "LISTENING_PENDING",
            "FINALIZATION_PENDING",
        },
        "LISTENING_PENDING": {
            "LISTENING_PENDING",
            "FINALIZATION_PENDING",
        },
        "FINALIZATION_PENDING": {"FINALIZATION_PENDING"},
    }
    one_ahead = (
        loaded.generation == snapshot.recovery_generation + 1
        and loaded.previous_record_sha256
        == snapshot.latest_recovery_sha256
        and expected_state in allowed_one_ahead.get(snapshot.state, set())
    )
    if not one_ahead or observer is None:
        raise RunnerError("RECOVERY_CLAIM_HEAD_MISMATCH")
    _notify_recovery_state(
        observer,
        expected_state,
        _RecoveryRecordCursor.from_loaded(loaded),
    )
    try:
        reconciled = reader()
    except RunnerError:
        raise
    except Exception as error:
        raise RunnerError("RECOVERY_CLAIM_STATE_INVALID") from error
    if reconciled != RecoveryClaimSnapshot(
        state=expected_state,
        recovery_generation=loaded.generation,
        latest_recovery_sha256=loaded.record_sha256,
    ):
        raise RunnerError("RECOVERY_CLAIM_HEAD_MISMATCH")


def _validate_fresh_claim_head(
    reader: RecoveryClaimStateReader | None,
) -> None:
    if reader is None:
        raise RunnerError("RECOVERY_CLAIM_STATE_READER_REQUIRED")
    try:
        snapshot = reader()
    except RunnerError:
        raise
    except Exception as error:
        raise RunnerError("RECOVERY_CLAIM_STATE_INVALID") from error
    if snapshot != RecoveryClaimSnapshot(
        state="PREPARED",
        recovery_generation=0,
        latest_recovery_sha256=None,
    ):
        raise RunnerError("RECOVERY_CLAIM_HEAD_MISMATCH")


def _sealed_technical_result(
    result: Mapping[str, object],
) -> dict[str, object]:
    value = {
        "result_schema_version": RESULT_SCHEMA,
        **{
            name: result[name]
            for name in (
                "automatic_chain",
                "manual_chain",
                "technical_checks",
            )
        },
    }
    # Round-trip the already-redacted evidence to detach it from mutable state.
    return _decode_json_object(
        _canonical_json_bytes(value),
        "RECOVERY_RECORD_INVALID",
    )


def _apply_sealed_technical_result(
    result: dict[str, object],
    sealed: Mapping[str, object],
) -> None:
    if sealed.get("result_schema_version") != RESULT_SCHEMA:
        raise RunnerError("RECOVERY_EVIDENCE_SCHEMA_STALE")
    for name in ("automatic_chain", "manual_chain", "technical_checks"):
        value = sealed.get(name)
        if not isinstance(value, dict):
            raise RunnerError("RECOVERY_RECORD_INVALID")
        result[name] = dict(value)


def _prepare_finalization(
    *,
    config: RunnerConfig,
    fixture: ChapterFixture,
    result: Mapping[str, object],
    exit_code: int,
    baseline: BaselineSnapshot,
    fence: RecoveryFence,
    claim_binding: RecoveryClaimBinding,
    private_directory: _SecureDirectory,
    run_id: str,
    completed_steps: Sequence[str],
    sealed_technical_result: Mapping[str, object] | None,
    restoration_evidence: Mapping[str, object] | None,
    recovery_state_observer: RecoveryStateObserver | None,
    recovery_cursor: _RecoveryRecordCursor,
    recovery_schema_version: str = RECOVERY_SCHEMA,
) -> None:
    final_value = {
        "exit_code": exit_code,
        "evidence": _decode_json_object(
            _canonical_json_bytes(dict(result)),
            "RECOVERY_RECORD_INVALID",
        ),
    }
    generation, previous_record_sha256 = recovery_cursor.next_metadata()
    payload = _recovery_payload(
        config,
        fixture,
        baseline,
        fence,
        claim_binding,
        private_directory,
        run_id=run_id,
        state="FINALIZATION_PENDING",
        completed_steps=completed_steps,
        generation=generation,
        previous_record_sha256=previous_record_sha256,
        baseline_restored=True,
        restoration_evidence=restoration_evidence,
        sealed_technical_result=sealed_technical_result,
        sealed_final_result=final_value,
        schema_version=recovery_schema_version,
    )
    _install_recovery_payload(private_directory, payload, recovery_cursor)
    _notify_recovery_state(
        recovery_state_observer,
        "FINALIZATION_PENDING",
        recovery_cursor,
    )


def _listening_from_sealed(
    config: RunnerConfig,
    sealed: Mapping[str, object],
) -> dict[str, object]:
    automatic = sealed.get("automatic_chain")
    manual = sealed.get("manual_chain")
    technical = sealed.get("technical_checks")
    if not all(isinstance(value, dict) for value in (automatic, manual, technical)):
        raise RunnerError("RECOVERY_RECORD_INVALID")
    assert isinstance(automatic, dict)
    assert isinstance(manual, dict)
    assert isinstance(technical, dict)
    hashes = technical.get("listening_output_hashes")
    if not isinstance(hashes, list):
        raise RunnerError("RECOVERY_RECORD_INVALID")
    return _load_listening_record(
        config.listening_record,
        run_id=config.run_id,
        novel_id=config.novel_id,
        document_id=config.document_id,
        automatic_edition_id_sha256=_validate_sha256(
            automatic.get("edition_id_sha256"),
            "RECOVERY_RECORD_INVALID",
        ),
        automatic_edition_fingerprint_sha256=_validate_sha256(
            automatic.get("edition_fingerprint_sha256"),
            "RECOVERY_RECORD_INVALID",
        ),
        manual_edition_id_sha256=_validate_sha256(
            manual.get("edition_id_sha256"),
            "RECOVERY_RECORD_INVALID",
        ),
        manual_edition_fingerprint_sha256=_validate_sha256(
            manual.get("edition_fingerprint_sha256"),
            "RECOVERY_RECORD_INVALID",
        ),
        expected_output_hashes=tuple(hashes),
        collector_collected_at=(
            technical.get("collector_collected_at")
            if isinstance(technical.get("collector_collected_at"), str)
            else ""
        ),
    )


def _run_real(
    config: RunnerConfig,
    fixture: ChapterFixture,
    result: dict[str, object],
    executor: ChapterE2EExecutor,
    private_directory: _SecureDirectory,
    claim_binding: RecoveryClaimBinding,
    *,
    run_id: str,
    recovery_state_observer: RecoveryStateObserver | None,
) -> int:
    baseline: BaselineSnapshot | None = None
    fence: RecoveryFence | None = None
    pending_write_intent: RecoveryWriteIntent | None = None
    sealed: dict[str, object] | None = None
    recovery_owned = False
    completed_steps: list[str] = []
    primary_code: str | None = None
    interrupted = False
    checkpoint_state = "BASELINE_CAPTURED"
    recovery_cursor = _RecoveryRecordCursor()
    if _entry_exists(
        private_directory,
        "recovery.json",
        "RECOVERY_RECORD_UNSAFE",
    ):
        _result_error(result, "RECOVERY_RECORD_EXISTS", "FAILED")
        return 2
    try:
        baseline = _validate_baseline(executor.capture_baseline(config))
        fence = _baseline_recovery_fence(baseline)
        generation, previous_record_sha256 = recovery_cursor.next_metadata()
        payload = _recovery_payload(
            config,
            fixture,
            baseline,
            fence,
            claim_binding,
            private_directory,
            run_id=run_id,
            state="BASELINE_CAPTURED",
            completed_steps=completed_steps,
            generation=generation,
            previous_record_sha256=previous_record_sha256,
        )
        _install_recovery_payload(
            private_directory,
            payload,
            recovery_cursor,
            exclusive=True,
        )
        recovery_owned = True

        def durable_checkpoint(
            value: RecoveryFence,
            write_intent: RecoveryWriteIntent | None,
        ) -> None:
            nonlocal fence, pending_write_intent
            candidate = _validate_recovery_fence(value)
            if write_intent is not None:
                write_intent = _validate_recovery_write_intent(write_intent)
                if write_intent.old_fence != candidate:
                    raise RunnerError("RECOVERY_WRITE_INTENT_INVALID")
            elif (
                pending_write_intent is not None
                and candidate
                not in {
                    pending_write_intent.old_fence,
                    pending_write_intent.next_fence,
                }
            ):
                raise RunnerError("RECOVERY_WRITE_INTENT_INVALID")
            generation, previous_record_sha256 = (
                recovery_cursor.next_metadata()
            )
            payload = _recovery_payload(
                config,
                fixture,
                baseline,
                candidate,
                claim_binding,
                private_directory,
                run_id=run_id,
                state=checkpoint_state,
                completed_steps=completed_steps,
                generation=generation,
                previous_record_sha256=previous_record_sha256,
                sealed_technical_result=sealed,
                write_intent=write_intent,
            )
            _install_recovery_payload(
                private_directory,
                payload,
                recovery_cursor,
            )
            fence = candidate
            pending_write_intent = write_intent
            _notify_recovery_state(
                recovery_state_observer,
                _claim_state_for_recovery_state(checkpoint_state),
                recovery_cursor,
            )

        executor.set_recovery_checkpoint(durable_checkpoint)
        _notify_recovery_state(
            recovery_state_observer,
            "BASELINE_SEALED",
            recovery_cursor,
        )
        recovery = result["recovery"]
        assert isinstance(recovery, dict)
        recovery["record_created"] = True

        execution_fixture = _run_unique_execution_fixture(fixture, config.run_id)

        automatic = _validate_chain(
            executor.run_automatic(config, execution_fixture.automatic),
            manual=False,
            minimum_character_speakers=fixture.minimum_character_speakers,
            minimum_distinct_voice_versions=(
                fixture.minimum_distinct_voice_versions
            ),
            require_uncached_nano_model_run=(
                fixture.require_uncached_nano_model_run
            ),
        )
        result["automatic_chain"] = _chain_evidence(automatic)
        fence = _validate_recovery_fence(
            executor.capture_recovery_fence(config)
        )
        completed_steps.append("automatic_chain")
        generation, previous_record_sha256 = recovery_cursor.next_metadata()
        payload = _recovery_payload(
            config,
            fixture,
            baseline,
            fence,
            claim_binding,
            private_directory,
            run_id=run_id,
            state="AUTOMATIC_COMPLETE",
            completed_steps=completed_steps,
            generation=generation,
            previous_record_sha256=previous_record_sha256,
        )
        _install_recovery_payload(private_directory, payload, recovery_cursor)
        _notify_recovery_state(
            recovery_state_observer,
            "BASELINE_SEALED",
            recovery_cursor,
        )
        checkpoint_state = "AUTOMATIC_COMPLETE"

        manual = _validate_chain(
            executor.run_manual(config, execution_fixture.manual),
            manual=True,
            minimum_character_speakers=fixture.minimum_character_speakers,
            minimum_distinct_voice_versions=(
                fixture.minimum_distinct_voice_versions
            ),
            require_uncached_nano_model_run=(
                fixture.require_uncached_nano_model_run
            ),
        )
        result["manual_chain"] = _chain_evidence(manual)
        fence = _validate_recovery_fence(
            executor.capture_recovery_fence(config)
        )
        completed_steps.append("manual_chain")
        generation, previous_record_sha256 = recovery_cursor.next_metadata()
        payload = _recovery_payload(
            config,
            fixture,
            baseline,
            fence,
            claim_binding,
            private_directory,
            run_id=run_id,
            state="MANUAL_COMPLETE",
            completed_steps=completed_steps,
            generation=generation,
            previous_record_sha256=previous_record_sha256,
        )
        _install_recovery_payload(private_directory, payload, recovery_cursor)
        _notify_recovery_state(
            recovery_state_observer,
            "BASELINE_SEALED",
            recovery_cursor,
        )
        checkpoint_state = "MANUAL_COMPLETE"

        technical = _validate_technical(
            executor.run_technical_checks(config, execution_fixture),
            required_seconds=config.duration_minutes * 60,
        )
        result["technical_checks"] = _technical_evidence(technical)
        fence = _validate_recovery_fence(
            executor.capture_recovery_fence(config)
        )
        completed_steps.append("technical_checks")
        sealed = _sealed_technical_result(result)
        generation, previous_record_sha256 = recovery_cursor.next_metadata()
        payload = _recovery_payload(
            config,
            fixture,
            baseline,
            fence,
            claim_binding,
            private_directory,
            run_id=run_id,
            state="TECHNICAL_COMPLETE",
            completed_steps=completed_steps,
            generation=generation,
            previous_record_sha256=previous_record_sha256,
            sealed_technical_result=sealed,
        )
        _install_recovery_payload(private_directory, payload, recovery_cursor)
        checkpoint_state = "TECHNICAL_COMPLETE"
        _notify_recovery_state(
            recovery_state_observer,
            "TECHNICAL_COMPLETE",
            recovery_cursor,
        )
    except KeyboardInterrupt:
        primary_code = "INTERRUPTED"
        interrupted = True
    except RunnerError as error:
        primary_code = error.code
    except BaseException:
        primary_code = "EXECUTION_FAILED"

    restore_code: str | None = None
    restoration: Mapping[str, object] | None = None
    if baseline is not None and fence is not None and recovery_owned:
        try:
            restored = _validate_recovery_outcome(
                executor.restore_baseline(
                    config,
                    baseline,
                    fence,
                    pending_write_intent,
                ),
                baseline=baseline,
            )
            if primary_code is None and (
                restored.restored_draft_version <= baseline.draft_version
                or restored.new_authoritative_record_count < 1
            ):
                raise RunnerError("RECOVERY_GATE_FAILED")
            recovery = result["recovery"]
            assert isinstance(recovery, dict)
            restoration = _restoration_evidence(restored)
            recovery.update(restoration)
        except BaseException as error:
            restore_code = (
                error.code
                if isinstance(error, RunnerError)
                else "BASELINE_RESTORE_FAILED"
            )
            try:
                generation, previous_record_sha256 = (
                    recovery_cursor.next_metadata()
                )
                payload = _recovery_payload(
                    config,
                    fixture,
                    baseline,
                    fence,
                    claim_binding,
                    private_directory,
                    run_id=run_id,
                    state="RECOVERY_REQUIRED",
                    completed_steps=completed_steps,
                    generation=generation,
                    previous_record_sha256=previous_record_sha256,
                    sealed_technical_result=sealed,
                    write_intent=pending_write_intent,
                    error_code=restore_code,
                )
                _install_recovery_payload(
                    private_directory,
                    payload,
                    recovery_cursor,
                )
            except RunnerError:
                restore_code = "RECOVERY_RECORD_WRITE_FAILED"
            recovery = result["recovery"]
            assert isinstance(recovery, dict)
            recovery["recovery_required"] = True
            try:
                _notify_recovery_state(
                    recovery_state_observer,
                    "RECOVERY_REQUIRED",
                    recovery_cursor,
                )
            except RunnerError:
                restore_code = "RECOVERY_CLAIM_TRANSITION_FAILED"

    if restore_code is not None:
        _result_error(result, restore_code, "RECOVERY_REQUIRED")
        if primary_code is not None:
            _result_error(result, primary_code, "RECOVERY_REQUIRED")
        return 4
    if primary_code is not None:
        _result_error(
            result,
            primary_code,
            "INTERRUPTED" if interrupted else "FAILED",
        )
        exit_code = 130 if interrupted else 2
        _prepare_finalization(
            config=config,
            fixture=fixture,
            result=result,
            exit_code=exit_code,
            baseline=baseline,
            fence=fence,
            claim_binding=claim_binding,
            private_directory=private_directory,
            run_id=run_id,
            completed_steps=completed_steps,
            sealed_technical_result=sealed,
            restoration_evidence=restoration,
            recovery_state_observer=recovery_state_observer,
            recovery_cursor=recovery_cursor,
        )
        return exit_code

    assert sealed is not None
    try:
        listening = _listening_from_sealed(config, sealed)
    except RunnerError as error:
        generation, previous_record_sha256 = recovery_cursor.next_metadata()
        payload = _recovery_payload(
            config,
            fixture,
            baseline,
            fence,
            claim_binding,
            private_directory,
            run_id=run_id,
            state="LISTENING_PENDING",
            completed_steps=completed_steps,
            generation=generation,
            previous_record_sha256=previous_record_sha256,
            baseline_restored=True,
            restoration_evidence=restoration,
            sealed_technical_result=sealed,
            error_code=error.code,
        )
        _install_recovery_payload(private_directory, payload, recovery_cursor)
        _notify_recovery_state(
            recovery_state_observer,
            "LISTENING_PENDING",
            recovery_cursor,
        )
        _result_error(result, error.code, "FAILED")
        return 2
    result["human_listening"] = listening
    if listening["state"] == "PENDING":
        generation, previous_record_sha256 = recovery_cursor.next_metadata()
        payload = _recovery_payload(
            config,
            fixture,
            baseline,
            fence,
            claim_binding,
            private_directory,
            run_id=run_id,
            state="LISTENING_PENDING",
            completed_steps=completed_steps,
            generation=generation,
            previous_record_sha256=previous_record_sha256,
            baseline_restored=True,
            restoration_evidence=restoration,
            sealed_technical_result=sealed,
        )
        _install_recovery_payload(private_directory, payload, recovery_cursor)
        _notify_recovery_state(
            recovery_state_observer,
            "LISTENING_PENDING",
            recovery_cursor,
        )
        result["status"] = "HUMAN_LISTENING_PENDING"
        return 3
    if listening["state"] == "FAIL":
        _result_error(result, "HUMAN_LISTENING_FAILED", "FAILED")
        _prepare_finalization(
            config=config,
            fixture=fixture,
            result=result,
            exit_code=2,
            baseline=baseline,
            fence=fence,
            claim_binding=claim_binding,
            private_directory=private_directory,
            run_id=run_id,
            completed_steps=completed_steps,
            sealed_technical_result=sealed,
            restoration_evidence=restoration,
            recovery_state_observer=recovery_state_observer,
            recovery_cursor=recovery_cursor,
        )
        return 2
    result["status"] = (
        "PASS_CANDIDATE"
        if fixture.production_eligible
        else "TECHNICAL_PASS_CANDIDATE"
    )
    _prepare_finalization(
        config=config,
        fixture=fixture,
        result=result,
        exit_code=0,
        baseline=baseline,
        fence=fence,
        claim_binding=claim_binding,
        private_directory=private_directory,
        run_id=run_id,
        completed_steps=completed_steps,
        sealed_technical_result=sealed,
        restoration_evidence=restoration,
        recovery_state_observer=recovery_state_observer,
        recovery_cursor=recovery_cursor,
    )
    return 0


def _resume_recovery(
    config: RunnerConfig,
    fixture: ChapterFixture,
    result: dict[str, object],
    private_directory: _SecureDirectory,
    recovery_executor_factory: RecoveryExecutorFactory | None,
    claim_binding: RecoveryClaimBinding,
    recovery_state_observer: RecoveryStateObserver | None,
    recovery_claim_state_reader: RecoveryClaimStateReader | None,
) -> int:
    try:
        loaded = _load_recovery_baseline(
            private_directory,
            config,
            fixture,
            claim_binding,
        )
    except RunnerError as error:
        _result_error(result, error.code, "FAILED")
        return 2
    try:
        _validate_claim_recovery_head(
            loaded,
            recovery_claim_state_reader,
            recovery_state_observer,
        )
    except RunnerError as error:
        _result_error(result, error.code, "FAILED")
        return 2
    recovery_cursor = _RecoveryRecordCursor.from_loaded(loaded)
    recovery = result["recovery"]
    assert isinstance(recovery, dict)
    recovery["record_created"] = True
    recovery["recovered_run_fingerprint_sha256"] = _sha256_text(loaded.run_id)
    if loaded.sealed_technical_result is not None:
        if loaded.schema_version == RECOVERY_SCHEMA:
            _apply_sealed_technical_result(
                result,
                loaded.sealed_technical_result,
            )
        elif loaded.state in {"LISTENING_PENDING", "FINALIZATION_PENDING"}:
            _result_error(
                result,
                "RECOVERY_EVIDENCE_SCHEMA_STALE",
                "FAILED",
            )
            return 2
    if loaded.restoration_evidence is not None:
        recovery.update(loaded.restoration_evidence)
    # Legacy 3.0 LISTENING_PENDING records prove only the coarse
    # baseline_restored fact.  They do not prove the three result booleans or
    # the actual authoritative-record count, so those fields remain the
    # conservative false/0 defaults instead of being guessed.
    if loaded.state == "FINALIZATION_PENDING":
        final = loaded.sealed_final_result
        if not isinstance(final, dict):
            _result_error(result, "RECOVERY_RECORD_INVALID", "FAILED")
            return 2
        evidence = final.get("evidence")
        exit_code = final.get("exit_code")
        if not isinstance(evidence, dict) or type(exit_code) is not int:
            _result_error(result, "RECOVERY_RECORD_INVALID", "FAILED")
            return 2
        result.clear()
        result.update(evidence)
        return exit_code
    if loaded.state == "LISTENING_PENDING":
        try:
            assert loaded.sealed_technical_result is not None
            listening = _listening_from_sealed(
                config,
                loaded.sealed_technical_result,
            )
        except RunnerError as error:
            recovery["recovery_required"] = False
            _result_error(result, error.code, "FAILED")
            return 2
        result["human_listening"] = listening
        if listening["state"] == "PENDING":
            result["status"] = "HUMAN_LISTENING_PENDING"
            return 3
        if listening["state"] == "FAIL":
            _result_error(result, "HUMAN_LISTENING_FAILED", "FAILED")
            _prepare_finalization(
                config=config,
                fixture=fixture,
                result=result,
                exit_code=2,
                baseline=loaded.baseline,
                fence=loaded.fence,
                claim_binding=claim_binding,
                private_directory=private_directory,
                run_id=loaded.run_id,
                completed_steps=loaded.completed_steps,
                sealed_technical_result=loaded.sealed_technical_result,
                restoration_evidence=loaded.restoration_evidence,
                recovery_state_observer=recovery_state_observer,
                recovery_cursor=recovery_cursor,
                recovery_schema_version=loaded.schema_version,
            )
            return 2
        result["status"] = (
            "PASS_CANDIDATE"
            if fixture.production_eligible
            else "TECHNICAL_PASS_CANDIDATE"
        )
        _prepare_finalization(
            config=config,
            fixture=fixture,
            result=result,
            exit_code=0,
            baseline=loaded.baseline,
            fence=loaded.fence,
            claim_binding=claim_binding,
            private_directory=private_directory,
            run_id=loaded.run_id,
            completed_steps=loaded.completed_steps,
            sealed_technical_result=loaded.sealed_technical_result,
            restoration_evidence=loaded.restoration_evidence,
            recovery_state_observer=recovery_state_observer,
            recovery_cursor=recovery_cursor,
            recovery_schema_version=loaded.schema_version,
        )
        return 0
    if recovery_executor_factory is None:
        _result_error(result, "REAL_RECOVERY_EXECUTOR_UNAVAILABLE", "FAILED")
        return 2
    resume_fence = loaded.fence
    resume_write_intent = loaded.write_intent
    try:
        executor = recovery_executor_factory(config)

        def durable_checkpoint(
            value: RecoveryFence,
            write_intent: RecoveryWriteIntent | None,
        ) -> None:
            nonlocal resume_fence, resume_write_intent
            candidate = _validate_recovery_fence(value)
            if write_intent is not None:
                write_intent = _validate_recovery_write_intent(write_intent)
                if write_intent.old_fence != candidate:
                    raise RunnerError("RECOVERY_WRITE_INTENT_INVALID")
            elif (
                resume_write_intent is not None
                and candidate
                not in {
                    resume_write_intent.old_fence,
                    resume_write_intent.next_fence,
                }
            ):
                raise RunnerError("RECOVERY_WRITE_INTENT_INVALID")
            generation, previous_record_sha256 = (
                recovery_cursor.next_metadata()
            )
            payload = _recovery_payload(
                config,
                fixture,
                loaded.baseline,
                candidate,
                claim_binding,
                private_directory,
                run_id=loaded.run_id,
                state="RECOVERY_REQUIRED",
                completed_steps=loaded.completed_steps,
                generation=generation,
                previous_record_sha256=previous_record_sha256,
                sealed_technical_result=loaded.sealed_technical_result,
                write_intent=write_intent,
            )
            _install_recovery_payload(
                private_directory,
                payload,
                recovery_cursor,
            )
            resume_fence = candidate
            resume_write_intent = write_intent
            _notify_recovery_state(
                recovery_state_observer,
                "RECOVERY_REQUIRED",
                recovery_cursor,
            )

        executor.set_recovery_checkpoint(durable_checkpoint)
        restored = _validate_recovery_outcome(
            executor.restore_baseline(
                config,
                loaded.baseline,
                resume_fence,
                resume_write_intent,
            ),
            baseline=loaded.baseline,
        )
    except KeyboardInterrupt:
        recovery["recovery_required"] = True
        _result_error(result, "INTERRUPTED", "INTERRUPTED")
        return 130
    except Exception as error:
        recovery["recovery_required"] = True
        error_code = (
            error.code
            if isinstance(error, RunnerError)
            else "BASELINE_RESTORE_FAILED"
        )
        try:
            generation, previous_record_sha256 = (
                recovery_cursor.next_metadata()
            )
            payload = _recovery_payload(
                config,
                fixture,
                loaded.baseline,
                resume_fence,
                claim_binding,
                private_directory,
                run_id=loaded.run_id,
                state="RECOVERY_REQUIRED",
                completed_steps=loaded.completed_steps,
                generation=generation,
                previous_record_sha256=previous_record_sha256,
                sealed_technical_result=loaded.sealed_technical_result,
                write_intent=resume_write_intent,
                error_code=error_code,
            )
            _install_recovery_payload(
                private_directory,
                payload,
                recovery_cursor,
            )
            _notify_recovery_state(
                recovery_state_observer,
                "RECOVERY_REQUIRED",
                recovery_cursor,
            )
        except RunnerError:
            error_code = "RECOVERY_RECORD_WRITE_FAILED"
        _result_error(
            result,
            error_code,
            "RECOVERY_REQUIRED",
        )
        return 4
    restoration = _restoration_evidence(restored)
    recovery.update(restoration)
    if loaded.sealed_technical_result is not None:
        generation, previous_record_sha256 = recovery_cursor.next_metadata()
        payload = _recovery_payload(
            config,
            fixture,
            loaded.baseline,
            resume_fence,
            claim_binding,
            private_directory,
            run_id=loaded.run_id,
            state="LISTENING_PENDING",
            completed_steps=loaded.completed_steps,
            generation=generation,
            previous_record_sha256=previous_record_sha256,
            baseline_restored=True,
            restoration_evidence=restoration,
            sealed_technical_result=loaded.sealed_technical_result,
        )
        _install_recovery_payload(private_directory, payload, recovery_cursor)
        _notify_recovery_state(
            recovery_state_observer,
            "LISTENING_PENDING",
            recovery_cursor,
        )
        result["human_listening"] = {"state": "PENDING"}
        result["status"] = "HUMAN_LISTENING_PENDING"
        return 3
    result["status"] = "BASELINE_RESTORED"
    _prepare_finalization(
        config=config,
        fixture=fixture,
        result=result,
        exit_code=0,
        baseline=loaded.baseline,
        fence=resume_fence,
        claim_binding=claim_binding,
        private_directory=private_directory,
        run_id=loaded.run_id,
        completed_steps=loaded.completed_steps,
        sealed_technical_result=loaded.sealed_technical_result,
        restoration_evidence=restoration,
        recovery_state_observer=recovery_state_observer,
        recovery_cursor=recovery_cursor,
    )
    return 0


def _safe_console(code: str, status_value: str) -> None:
    print(
        json.dumps(
            {
                "schema_version": RESULT_SCHEMA,
                "status": status_value,
                "code": code,
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _main_impl(
    argv: Sequence[str] | None = None,
    *,
    executor_factory: ExecutorFactory | None = None,
    recovery_executor_factory: RecoveryExecutorFactory | None = None,
    fixture_override: ChapterFixture | None = None,
    recovery_claim_binding: RecoveryClaimBinding | None = None,
    recovery_state_observer: RecoveryStateObserver | None = None,
    recovery_claim_state_reader: RecoveryClaimStateReader | None = None,
    minimum_duration_minutes: float = FORMAL_MINIMUM_DURATION_MINUTES,
) -> tuple[int, str, str]:
    args = build_parser().parse_args(argv)
    config = build_runner_config(
        args,
        minimum_duration_minutes=minimum_duration_minutes,
    )
    fixture = (
        load_fixture(
            config.fixture_manifest,
            automatic_case_id=config.automatic_case_id,
            manual_case_id=config.manual_case_id,
        )
        if fixture_override is None
        else _validate_fixture_override(fixture_override, config)
    )
    config = replace(
        config,
        expected_formal_speakers=fixture.expected_formal_speakers,
    )
    private_directory = _open_secure_directory(
        config.private_work_dir,
        "PRIVATE_WORK_DIR_UNSAFE",
    )
    output_directory: _SecureDirectory | None = None
    try:
        output_directory = _open_secure_directory(
            config.output_dir,
            "OUTPUT_PATH_UNSAFE",
        )
        run_id = str(config.run_id)
        result = _base_result(config, fixture, run_id=run_id)
        if config.mode == "validate-only":
            result["status"] = "VALIDATED_ONLY"
            exit_code = 0
        else:
            claim_binding = _validate_recovery_claim_binding(
                recovery_claim_binding
            )
            path_digest, identity_digest = recovery_private_directory_binding(
                private_directory.path,
                private_directory.opened_identity,
            )
            if (
                path_digest
                != claim_binding.private_work_dir_canonical_sha256
                or identity_digest
                != claim_binding.private_work_dir_identity_sha256
            ):
                raise RunnerError("RECOVERY_CLAIM_DIRECTORY_MISMATCH")
            if (
                not callable(recovery_state_observer)
                or not callable(recovery_claim_state_reader)
            ):
                raise RunnerError("RECOVERY_CLAIM_COORDINATOR_REQUIRED")
            if config.resume:
                exit_code = _resume_recovery(
                    config,
                    fixture,
                    result,
                    private_directory,
                    recovery_executor_factory,
                    claim_binding,
                    recovery_state_observer,
                    recovery_claim_state_reader,
                )
            elif _entry_exists(
                private_directory,
                "recovery.json",
                "RECOVERY_RECORD_UNSAFE",
            ):
                # Fresh execution never consumes or advances a recovery head.
                # Keep the record byte-for-byte for an explicit resume.
                _result_error(result, "RECOVERY_RECORD_EXISTS", "FAILED")
                exit_code = 2
            elif executor_factory is None:
                _result_error(result, "REAL_EXECUTOR_UNAVAILABLE", "FAILED")
                exit_code = 2
            else:
                _validate_fresh_claim_head(recovery_claim_state_reader)
                executor = executor_factory(config)
                exit_code = _run_real(
                    config,
                    fixture,
                    result,
                    executor,
                    private_directory,
                    claim_binding,
                    run_id=run_id,
                    recovery_state_observer=recovery_state_observer,
                )
        _write_evidence(output_directory, result)
        if config.mode == "real" and _entry_exists(
            private_directory,
            "recovery.json",
            "RECOVERY_RECORD_UNSAFE",
        ):
            finalized = _load_recovery_baseline(
                private_directory,
                config,
                fixture,
                claim_binding,
            )
            if finalized.state == "FINALIZATION_PENDING":
                _validate_claim_recovery_head(
                    finalized,
                    recovery_claim_state_reader,
                    recovery_state_observer,
                )
                final_value = finalized.sealed_final_result
                if (
                    not isinstance(final_value, dict)
                    or final_value.get("exit_code") != exit_code
                    or final_value.get("evidence") != result
                ):
                    raise RunnerError("RECOVERY_RECORD_INVALID")
                final_cursor = _RecoveryRecordCursor.from_loaded(finalized)
                original_output_identity = output_directory.opened_identity
                try:
                    output_directory.close()
                finally:
                    # close() closes the descriptor even if its final identity
                    # assertion fails. Never let the outer finally re-use it.
                    output_directory = None

                verified_output_directory: _SecureDirectory | None = None
                try:
                    _notify_recovery_state(
                        recovery_state_observer,
                        "FINALIZED",
                        final_cursor,
                    )
                    # The callback is outside the output dirfd trust boundary.
                    # Re-open without creating anything and require the exact
                    # physical directory that durably received the evidence.
                    verified_output_directory = _open_secure_directory(
                        config.output_dir,
                        "OUTPUT_PATH_UNSAFE",
                        create_missing=False,
                    )
                    if (
                        verified_output_directory.opened_identity
                        != original_output_identity
                    ):
                        raise RunnerError("OUTPUT_PATH_UNSAFE")
                    try:
                        verified_output_directory.close()
                    finally:
                        verified_output_directory = None
                except BaseException:
                    # Whether FINALIZED persisted before a callback failure is
                    # intentionally opaque here. Both same-state retry and this
                    # narrow rollback are legal under the held claim flock.
                    try:
                        _notify_recovery_state(
                            recovery_state_observer,
                            "FINALIZATION_PENDING",
                            final_cursor,
                        )
                    except BaseException as rollback_error:
                        raise RunnerError(
                            "RECOVERY_CLAIM_TRANSITION_FAILED"
                        ) from rollback_error
                    raise
                finally:
                    if verified_output_directory is not None:
                        try:
                            verified_output_directory.close()
                        except RunnerError:
                            pass
                _unlink_secure(private_directory, "recovery.json")
        return exit_code, str(result["status"]), str(result["status"])
    finally:
        close_error: RunnerError | None = None
        for directory in (output_directory, private_directory):
            if directory is None:
                continue
            try:
                directory.close()
            except RunnerError as error:
                if close_error is None:
                    close_error = error
        if close_error is not None:
            raise close_error


def main(
    argv: Sequence[str] | None = None,
    *,
    executor_factory: ExecutorFactory | None = None,
    recovery_executor_factory: RecoveryExecutorFactory | None = None,
    fixture_override: ChapterFixture | None = None,
    recovery_claim_binding: RecoveryClaimBinding | None = None,
    recovery_state_observer: RecoveryStateObserver | None = None,
    recovery_claim_state_reader: RecoveryClaimStateReader | None = None,
    minimum_duration_minutes: float = FORMAL_MINIMUM_DURATION_MINUTES,
) -> int:
    """Run with one stable redacted console record and no traceback leakage."""

    try:
        exit_code, console_code, console_status = _main_impl(
            argv,
            executor_factory=executor_factory,
            recovery_executor_factory=recovery_executor_factory,
            fixture_override=fixture_override,
            recovery_claim_binding=recovery_claim_binding,
            recovery_state_observer=recovery_state_observer,
            recovery_claim_state_reader=recovery_claim_state_reader,
            minimum_duration_minutes=minimum_duration_minutes,
        )
    except KeyboardInterrupt:
        _safe_console("INTERRUPTED", "INTERRUPTED")
        return 130
    except RunnerError as error:
        _safe_console(error.code, "FAILED")
        return 2
    except Exception:
        _safe_console("UNEXPECTED_FAILURE", "FAILED")
        return 2
    _safe_console(console_code, console_status)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
