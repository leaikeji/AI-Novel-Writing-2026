#!/usr/bin/env python3
"""Fail-closed, read-only T4-K data readiness inspection.

The command accepts exactly one private operator attestation and the fixed
``readonly`` mode.  It does not accept database URLs, import paths, shell
commands, HTTP endpoints, or output paths.  PostgreSQL is discovered through
the existing project runtime configuration and is inspected only inside a
repeatable-read, read-only transaction.

The only command output is one canonical JSON object on stdout.  Reports never
contain database identifiers, chapter text, filesystem paths, fingerprints,
checksums, grants, credentials, or exception messages.  This command is a
preflight only: even a completely ready result remains ``HOLD`` and can be no
stronger than ``READY_FOR_OPERATOR_REVIEW``.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Final, Iterator, Mapping, Protocol, Sequence
from uuid import UUID


REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from backend.database import get_engine  # noqa: E402
from backend.models import (  # noqa: E402
    CharacterVoiceBinding,
    Document,
    DocumentNarrationState,
    DocumentWorkingCopy,
    MediaAsset,
    NarrationEdition,
    NarrationEditionState,
    NarrationManifest,
    NarrationScript,
    NarrationScriptVersion,
    Novel,
    NovelCharacter,
    NovelNarrationSettings,
    VoiceDeletionRequest,
    VoiceProfile,
    VoiceProfileVersion,
    VoiceReferenceAssetLink,
    VoiceRightsEvent,
    VoiceRightsRecord,
)
from backend.narration.contracts import (  # noqa: E402
    LOCAL_OWNER_ID,
    LOCAL_WORKSPACE_ID,
)
from backend.narration.production_runtime import (  # noqa: E402
    MEDIA_ROOT_ENV,
    MODEL_METADATA_ROOT_ENV,
)
from backend.narration.storage import (  # noqa: E402
    NarrationStorage,
    StorageError,
)
from scripts.tts.validate_chapter_e2e import (  # noqa: E402
    ALLOWED_VIEWPORTS,
    RunnerError,
    load_fixture,
)


ATTESTATION_SCHEMA: Final = "moss-tts-t4k-readiness-attestation/1.1"
REPORT_SCHEMA: Final = "moss-tts-t4k-readiness-report/1.1"
EXPECTED_DATABASE_REVISION: Final = "20260829_0029"
FIXTURE_PATH: Final = (
    REPOSITORY_ROOT / "tests/fixtures/narration/chapter-e2e-v3.json"
)
FIXTURE_AUTOMATIC_CASE: Final = "chapter-auto-zero-blockers"
FIXTURE_MANUAL_CASE: Final = "chapter-real-blocker"
EXPECTED_CHARACTERS: Final = ("林晚", "沈川")
EXPECTED_OFFICIAL_PRESETS: Final = frozenset(
    {
        ("narrator", "onnx.Zhiming"),
        ("林晚", "onnx.Xiaoyu"),
        ("沈川", "onnx.Junhao"),
    }
)
EXPECTED_ASSISTANT_MODES: Final = ("collapsed", "expanded")
EXPECTED_CAPTURES: Final = tuple(
    (width, height, assistant_mode)
    for width, height in ALLOWED_VIEWPORTS
    for assistant_mode in EXPECTED_ASSISTANT_MODES
)
EXPECTED_LOCK_NAMES: Final = ("nano", "browser", "data")
MAX_ATTESTATION_BYTES: Final = 64 * 1024
MAX_FIXTURE_BYTES: Final = 2 * 1024 * 1024
MAX_VOICE_MEDIA_BYTES: Final = 512 * 1024 * 1024
_SHA256_RE: Final = re.compile(r"^[a-f0-9]{64}$")
_OFFICIAL_PRESET_ID_RE: Final = re.compile(r"^onnx\.[A-Za-z][A-Za-z0-9_-]{0,79}$")
_SAFE_CODE_RE: Final = re.compile(r"^[A-Z][A-Z0-9_]{1,95}$")
OFFICIAL_PRESET_REPOSITORY: Final = "OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX"
OFFICIAL_PRESET_REVISION: Final = "f52645cb467506d8e18e746ddd59482685b74e58"
OFFICIAL_PRESET_MANIFEST_PATH: Final = "browser_poc_manifest.json"
OFFICIAL_PRESET_MANIFEST_SHA256: Final = (
    "097d80e993dc29f0bae427590b4f77084a161cb578b50d82c29f455d5faa9eee"
)
OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256: Final = (
    "3c76f3e9e1381699c5555287cf66eeb023632d0c3ee94adc6d8ae1b1d455fd7d"
)
OFFICIAL_PRESET_PROVENANCE_SCHEMA: Final = (
    "moss-tts-official-preset-provenance/1.0"
)
_NEGATIVE_RIGHTS_EVENTS: Final = frozenset(
    {"revoked", "expired", "review_blocked"}
)
_ACTIVE_DELETION_STATES: Final = frozenset(
    {
        "requested",
        "live_deleting",
        "live_deleted_backup_pending",
        "completed",
    }
)
_GRANT_PATTERNS: Final[Mapping[str, re.Pattern[str]]] = {
    "nano": re.compile(r"^LOCK-NANO/[A-Za-z0-9][A-Za-z0-9._-]{7,95}$"),
    "browser": re.compile(
        r"^LOCK-BROWSER/[A-Za-z0-9][A-Za-z0-9._-]{7,95}$"
    ),
    "data": re.compile(
        r"^LOCK-T4-K-DATA/[A-Za-z0-9][A-Za-z0-9._-]{7,95}$"
    ),
}


class ReadinessError(RuntimeError):
    """Stable error boundary that never carries sensitive input values."""

    def __init__(self, code: str) -> None:
        if _SAFE_CODE_RE.fullmatch(code) is None:
            raise ValueError("readiness error code must be stable")
        self.code = code
        super().__init__(code)


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # pragma: no cover - argparse boundary
        del message
        raise ReadinessError("READINESS_ARGUMENTS_INVALID")


@dataclass(frozen=True, slots=True)
class ResourceLockAttestation:
    name: str
    path: Path
    grant: str


@dataclass(frozen=True, slots=True)
class OfficialPresetBindingAttestation:
    role: str
    preset_id: str


@dataclass(frozen=True, slots=True)
class ReadinessAttestation:
    fixture_manifest_sha256: str
    novel_id: UUID
    document_id: UUID
    dedicated_test_novel: bool
    dedicated_test_chapter: bool
    append_only_recovery_accepted: bool
    official_presets_local_use: bool
    expected_official_presets: tuple[OfficialPresetBindingAttestation, ...]
    expected_characters: tuple[str, ...]
    required_captures: tuple[tuple[int, int, str], ...]
    resource_locks: tuple[ResourceLockAttestation, ...]


@dataclass(frozen=True, slots=True)
class DatabaseReadinessEvidence:
    """Redacted aggregate returned by an injectable authority reader."""

    missing_codes: tuple[str, ...]
    voice_role_count: int
    distinct_profile_count: int
    distinct_voice_version_count: int
    official_preset_count: int
    official_provenance_verified_count: int
    database_checks_completed: bool
    authority_fingerprint_sha256: str | None = None

    def __post_init__(self) -> None:
        if (
            tuple(sorted(set(self.missing_codes))) != self.missing_codes
            or any(_SAFE_CODE_RE.fullmatch(code) is None for code in self.missing_codes)
            or any(
                type(value) is not int or value < 0
                for value in (
                    self.voice_role_count,
                    self.distinct_profile_count,
                    self.distinct_voice_version_count,
                    self.official_preset_count,
                    self.official_provenance_verified_count,
                )
            )
            or self.distinct_profile_count > self.voice_role_count
            or self.distinct_voice_version_count > self.voice_role_count
            or self.official_provenance_verified_count
            > self.official_preset_count
            or type(self.database_checks_completed) is not bool
            or (
                self.authority_fingerprint_sha256 is not None
                and _SHA256_RE.fullmatch(
                    self.authority_fingerprint_sha256
                )
                is None
            )
        ):
            raise ValueError("database readiness evidence is invalid")


class ReadinessReader(Protocol):
    def audit(self, attestation: ReadinessAttestation) -> DatabaseReadinessEvidence: ...


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _authority_fingerprint(value: object) -> str:
    """Hash an exact authority snapshot without exposing its identifiers."""

    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _authority_time(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        normalized = value.replace(tzinfo=timezone.utc)
    else:
        normalized = value.astimezone(timezone.utc)
    return normalized.isoformat(timespec="microseconds")


def _official_preset_provenance(
    version: VoiceProfileVersion,
    *,
    expected_preset_id: str,
) -> dict[str, object] | None:
    """Return one exact, hash-closed official preset provenance projection."""

    parameters = version.parameters_json
    if type(parameters) is not dict:
        return None
    provenance = parameters.get("official_preset")
    exact_keys = {
        "schema_version",
        "repository",
        "revision",
        "manifest_path",
        "manifest_sha256",
        "preset_id",
        "manifest_voice",
        "prompt_codes_sha256",
        "prompt_frame_count",
        "prompt_quantizer_count",
        "model_fingerprint_sha256",
        "provenance_fingerprint_sha256",
    }
    if type(provenance) is not dict or set(provenance) != exact_keys:
        return None
    fingerprint = provenance.get("provenance_fingerprint_sha256")
    manifest_voice = provenance.get("manifest_voice")
    if (
        provenance.get("schema_version") != OFFICIAL_PRESET_PROVENANCE_SCHEMA
        or provenance.get("repository") != OFFICIAL_PRESET_REPOSITORY
        or provenance.get("revision") != OFFICIAL_PRESET_REVISION
        or provenance.get("manifest_path") != OFFICIAL_PRESET_MANIFEST_PATH
        or provenance.get("manifest_sha256") != OFFICIAL_PRESET_MANIFEST_SHA256
        or provenance.get("preset_id") != expected_preset_id
        or version.preset_key != expected_preset_id
        or type(manifest_voice) is not str
        or expected_preset_id != f"onnx.{manifest_voice}"
        or type(provenance.get("prompt_frame_count")) is not int
        or provenance["prompt_frame_count"] <= 0
        or provenance.get("prompt_quantizer_count") != 16
        or _SHA256_RE.fullmatch(str(provenance.get("prompt_codes_sha256", "")))
        is None
        or provenance.get("model_fingerprint_sha256")
        != OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256
        or type(fingerprint) is not str
        or _SHA256_RE.fullmatch(fingerprint) is None
    ):
        return None
    unsigned = dict(provenance)
    unsigned.pop("provenance_fingerprint_sha256")
    expected_fingerprint = hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    if fingerprint != expected_fingerprint:
        return None
    return dict(provenance)


def _strict_object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ReadinessError("ATTESTATION_JSON_INVALID")
        result[key] = value
    return result


def _exact_keys(
    value: object,
    keys: set[str],
    *,
    code: str = "ATTESTATION_SCHEMA_INVALID",
) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        raise ReadinessError(code)
    return value


def _private_external_parent(path: Path, *, code: str) -> Path:
    if not path.is_absolute() or ".." in path.parts:
        raise ReadinessError(code)
    try:
        parent_lstat = os.lstat(path.parent)
        parent = path.parent.resolve(strict=True)
        repository = REPOSITORY_ROOT.resolve(strict=True)
    except OSError as error:
        raise ReadinessError(code) from error
    if (
        not stat.S_ISDIR(parent_lstat.st_mode)
        or stat.S_ISLNK(parent_lstat.st_mode)
        or parent_lstat.st_uid != os.getuid()
        or stat.S_IMODE(parent_lstat.st_mode) != 0o700
        or parent == repository
        or parent.is_relative_to(repository)
    ):
        raise ReadinessError(code)
    return parent


def _read_private_file(path: Path) -> bytes:
    parent = _private_external_parent(path, code="ATTESTATION_FILE_UNSAFE")
    descriptor: int | None = None
    try:
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            raise ReadinessError("ATTESTATION_POLICY_UNAVAILABLE")
        descriptor = os.open(
            parent / path.name,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | nofollow,
        )
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != os.getuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size <= 0
            or before.st_size > MAX_ATTESTATION_BYTES
        ):
            raise ReadinessError("ATTESTATION_FILE_UNSAFE")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(16 * 1024, remaining))
            if not chunk:
                raise ReadinessError("ATTESTATION_FILE_UNSAFE")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise ReadinessError("ATTESTATION_FILE_UNSAFE")
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise ReadinessError("ATTESTATION_FILE_UNSAFE")
        return b"".join(chunks)
    except ReadinessError:
        raise
    except OSError as error:
        raise ReadinessError("ATTESTATION_FILE_UNSAFE") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _uuid(value: object) -> UUID:
    if type(value) is not str:
        raise ReadinessError("ATTESTATION_SCOPE_INVALID")
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as error:
        raise ReadinessError("ATTESTATION_SCOPE_INVALID") from error
    if str(parsed) != value:
        raise ReadinessError("ATTESTATION_SCOPE_INVALID")
    return parsed


def load_private_attestation(path: Path) -> ReadinessAttestation:
    """Load one 0600, owner-only, repository-external attestation."""

    if not isinstance(path, Path):
        raise ReadinessError("ATTESTATION_FILE_UNSAFE")
    raw = _read_private_file(path)
    try:
        payload = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_object_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ReadinessError("ATTESTATION_JSON_INVALID")
            ),
        )
    except ReadinessError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReadinessError("ATTESTATION_JSON_INVALID") from error
    value = _exact_keys(
        payload,
        {
            "schema_version",
            "fixture_manifest_sha256",
            "novel_id",
            "document_id",
            "declarations",
            "expected_characters",
            "expected_official_presets",
            "required_captures",
            "resource_locks",
        },
    )
    if value["schema_version"] != ATTESTATION_SCHEMA:
        raise ReadinessError("ATTESTATION_SCHEMA_INVALID")
    fixture_sha = value["fixture_manifest_sha256"]
    if type(fixture_sha) is not str or _SHA256_RE.fullmatch(fixture_sha) is None:
        raise ReadinessError("ATTESTATION_FIXTURE_INVALID")
    declarations = _exact_keys(
        value["declarations"],
        {
            "dedicated_test_novel",
            "dedicated_test_chapter",
            "append_only_recovery_accepted",
            "official_presets_local_use",
        },
    )
    if any(type(item) is not bool for item in declarations.values()):
        raise ReadinessError("ATTESTATION_DECLARATIONS_INVALID")
    characters = value["expected_characters"]
    if (
        type(characters) is not list
        or any(type(item) is not str or not item for item in characters)
        or len(characters) != len(set(characters))
    ):
        raise ReadinessError("ATTESTATION_CAST_INVALID")
    raw_presets = value["expected_official_presets"]
    if type(raw_presets) is not list or len(raw_presets) != 3:
        raise ReadinessError("ATTESTATION_OFFICIAL_PRESETS_INVALID")
    preset_bindings: list[OfficialPresetBindingAttestation] = []
    for item in raw_presets:
        binding = _exact_keys(
            item,
            {"role", "preset_id"},
            code="ATTESTATION_OFFICIAL_PRESETS_INVALID",
        )
        role = binding["role"]
        preset_id = binding["preset_id"]
        if (
            type(role) is not str
            or type(preset_id) is not str
            or _OFFICIAL_PRESET_ID_RE.fullmatch(preset_id) is None
        ):
            raise ReadinessError("ATTESTATION_OFFICIAL_PRESETS_INVALID")
        preset_bindings.append(
            OfficialPresetBindingAttestation(role=role, preset_id=preset_id)
        )
    if (
        frozenset((item.role, item.preset_id) for item in preset_bindings)
        != EXPECTED_OFFICIAL_PRESETS
    ):
        raise ReadinessError("ATTESTATION_OFFICIAL_PRESETS_INVALID")
    captures_value = value["required_captures"]
    if type(captures_value) is not list:
        raise ReadinessError("ATTESTATION_VIEWPORTS_INVALID")
    captures: list[tuple[int, int, str]] = []
    for item in captures_value:
        capture = _exact_keys(
            item,
            {"width", "height", "assistant_mode"},
            code="ATTESTATION_VIEWPORTS_INVALID",
        )
        width = capture["width"]
        height = capture["height"]
        mode = capture["assistant_mode"]
        if (
            type(width) is not int
            or type(height) is not int
            or width <= 0
            or height <= 0
            or type(mode) is not str
        ):
            raise ReadinessError("ATTESTATION_VIEWPORTS_INVALID")
        captures.append((width, height, mode))
    raw_locks = value["resource_locks"]
    if type(raw_locks) is not list:
        raise ReadinessError("ATTESTATION_LOCKS_INVALID")
    locks: list[ResourceLockAttestation] = []
    for item in raw_locks:
        lock = _exact_keys(
            item,
            {"name", "path", "grant"},
            code="ATTESTATION_LOCKS_INVALID",
        )
        name = lock["name"]
        raw_path = lock["path"]
        grant = lock["grant"]
        if (
            type(name) is not str
            or name not in EXPECTED_LOCK_NAMES
            or type(raw_path) is not str
            or not raw_path
            or type(grant) is not str
            or _GRANT_PATTERNS[name].fullmatch(grant) is None
        ):
            raise ReadinessError("ATTESTATION_LOCKS_INVALID")
        locks.append(
            ResourceLockAttestation(name=name, path=Path(raw_path), grant=grant)
        )
    if len({item.name for item in locks}) != len(locks):
        raise ReadinessError("ATTESTATION_LOCKS_INVALID")
    return ReadinessAttestation(
        fixture_manifest_sha256=fixture_sha,
        novel_id=_uuid(value["novel_id"]),
        document_id=_uuid(value["document_id"]),
        dedicated_test_novel=declarations["dedicated_test_novel"],  # type: ignore[arg-type]
        dedicated_test_chapter=declarations["dedicated_test_chapter"],  # type: ignore[arg-type]
        append_only_recovery_accepted=declarations[
            "append_only_recovery_accepted"
        ],  # type: ignore[arg-type]
        official_presets_local_use=declarations[
            "official_presets_local_use"
        ],  # type: ignore[arg-type]
        expected_official_presets=tuple(preset_bindings),
        expected_characters=tuple(characters),
        required_captures=tuple(captures),
        resource_locks=tuple(locks),
    )


def _fixed_fixture_missing(attestation: ReadinessAttestation) -> set[str]:
    missing: set[str] = set()
    try:
        fixture = load_fixture(
            FIXTURE_PATH,
            automatic_case_id=FIXTURE_AUTOMATIC_CASE,
            manual_case_id=FIXTURE_MANUAL_CASE,
        )
        if fixture.manifest_sha256 != attestation.fixture_manifest_sha256:
            missing.add("FIXTURE_BINDING_NOT_READY")
        if (
            fixture.voice_scope != "local_personal_use"
            or fixture.production_eligible is not True
            or fixture.commercial_distribution_status != "not_evaluated"
            or fixture.minimum_character_speakers != 2
            or fixture.minimum_distinct_voice_versions != 3
            or fixture.expected_formal_speakers != EXPECTED_CHARACTERS
            or fixture.required_viewports != ALLOWED_VIEWPORTS
            or any(
                character not in fixture.automatic.source_text
                or character not in fixture.manual.source_text
                for character in EXPECTED_CHARACTERS
            )
        ):
            missing.add("FIXTURE_AUTHORITY_NOT_READY")
    except (OSError, RunnerError):
        missing.add("FIXTURE_AUTHORITY_NOT_READY")
    return missing


def _resource_lock_missing(
    attestation: ReadinessAttestation,
) -> tuple[set[str], int]:
    by_name = {item.name: item for item in attestation.resource_locks}
    if set(by_name) != set(EXPECTED_LOCK_NAMES):
        return {"RESOURCE_LOCK_SET_NOT_READY"}, 0
    if len({item.path for item in by_name.values()}) != len(EXPECTED_LOCK_NAMES):
        return {"RESOURCE_LOCK_SET_NOT_READY"}, 0
    descriptors: list[int] = []
    ready = 0
    try:
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            return {"RESOURCE_LOCK_POLICY_UNAVAILABLE"}, 0
        for name in EXPECTED_LOCK_NAMES:
            item = by_name[name]
            parent = _private_external_parent(
                item.path,
                code="RESOURCE_LOCK_IDENTITY_NOT_READY",
            )
            descriptor = os.open(
                parent / item.path.name,
                os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | nofollow,
            )
            descriptors.append(descriptor)
            details = os.fstat(descriptor)
            if (
                not stat.S_ISREG(details.st_mode)
                or details.st_nlink != 1
                or details.st_uid != os.getuid()
                or stat.S_IMODE(details.st_mode) != 0o600
            ):
                return {"RESOURCE_LOCK_IDENTITY_NOT_READY"}, ready
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return {"RESOURCE_LOCK_BUSY"}, ready
            ready += 1
        return set(), ready
    except ReadinessError as error:
        return {error.code}, ready
    except OSError:
        return {"RESOURCE_LOCK_IDENTITY_NOT_READY"}, ready
    finally:
        for descriptor in reversed(descriptors):
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)


class SqlAlchemyReadinessReader:
    """Read the current T4-K authority using one existing PostgreSQL DB."""

    def __init__(
        self,
        session_factory: object,
        *,
        storage: NarrationStorage | None,
    ) -> None:
        if not callable(session_factory):
            raise ReadinessError("DATABASE_CONFIGURATION_NOT_READY")
        self._session_factory = session_factory
        self._storage = storage

    @contextmanager
    def _read_session(self) -> Iterator[Session]:
        try:
            with self._session_factory() as session:  # type: ignore[operator]
                bind = session.get_bind()
                if bind.dialect.name != "postgresql":
                    raise ReadinessError("DATABASE_POSTGRESQL_REQUIRED")
                session.execute(
                    text(
                        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                    )
                )
                read_only = session.scalar(
                    text("SELECT current_setting('transaction_read_only')")
                )
                isolation = session.scalar(
                    text("SELECT current_setting('transaction_isolation')")
                )
                if read_only != "on" or isolation != "repeatable read":
                    raise ReadinessError("DATABASE_READ_ONLY_REQUIRED")
                try:
                    yield session
                finally:
                    session.rollback()
        except ReadinessError:
            raise
        except Exception as error:
            raise ReadinessError("DATABASE_READ_FAILED") from error

    def audit(self, attestation: ReadinessAttestation) -> DatabaseReadinessEvidence:
        if type(attestation) is not ReadinessAttestation:
            raise ReadinessError("ATTESTATION_SCOPE_INVALID")
        missing: set[str] = set()
        with self._read_session() as session:
            revisions = tuple(
                str(value)
                for value in session.scalars(
                    text("SELECT version_num FROM alembic_version")
                )
            )
            if revisions != (EXPECTED_DATABASE_REVISION,):
                missing.add("DATABASE_SCHEMA_NOT_READY")

            novel = session.get(Novel, attestation.novel_id)
            document = session.get(Document, attestation.document_id)
            working = session.get(DocumentWorkingCopy, attestation.document_id)
            if novel is None:
                missing.add("DEDICATED_NOVEL_NOT_READY")
            elif (
                novel.owner_id != LOCAL_OWNER_ID
                or novel.workspace_id != LOCAL_WORKSPACE_ID
            ):
                missing.add("DEDICATED_NOVEL_SCOPE_INVALID")
            if (
                document is None
                or document.novel_id != attestation.novel_id
                or document.kind != "chapter"
            ):
                missing.add("DEDICATED_CHAPTER_NOT_READY")
            if working is None or working.document_id != attestation.document_id:
                missing.add("WORKING_COPY_NOT_READY")

            state = session.scalar(
                select(DocumentNarrationState).where(
                    DocumentNarrationState.owner_id == LOCAL_OWNER_ID,
                    DocumentNarrationState.workspace_id == LOCAL_WORKSPACE_ID,
                    DocumentNarrationState.document_id == attestation.document_id,
                )
            )
            edition = (
                session.get(NarrationEdition, state.current_edition_id)
                if state is not None and state.current_edition_id is not None
                else None
            )
            script = (
                session.get(NarrationScript, state.script_id)
                if state is not None and state.script_id is not None
                else None
            )
            script_version = (
                session.get(
                    NarrationScriptVersion,
                    state.current_script_version_id,
                )
                if state is not None
                and state.current_script_version_id is not None
                else None
            )
            if (
                state is None
                or state.current_edition_id is None
                or edition is None
                or edition.id != state.current_edition_id
                or edition.owner_id != LOCAL_OWNER_ID
                or edition.workspace_id != LOCAL_WORKSPACE_ID
                or edition.novel_id != attestation.novel_id
                or edition.document_id != attestation.document_id
                or edition.state != "ready"
            ):
                missing.add("CURRENT_EDITION_NOT_READY")
            if (
                state is None
                or script is None
                or script_version is None
                or script.id != state.script_id
                or script_version.id != state.current_script_version_id
                or script_version.script_id != script.id
                or script.novel_id != attestation.novel_id
                or script.document_id != attestation.document_id
                or working is None
                or script.content_hash != working.content_hash
                or script_version.state != "approved"
                or script_version.is_approved is not True
                or script_version.blocker_count != 0
                or edition is None
                or edition.script_version_id != script_version.id
            ):
                missing.add("CURRENT_APPROVED_SCRIPT_NOT_READY")

            edition_state = (
                session.get(NarrationEditionState, edition.id)
                if edition is not None
                else None
            )
            manifest = (
                session.get(NarrationManifest, edition_state.current_manifest_id)
                if edition_state is not None
                and edition_state.current_manifest_id is not None
                else None
            )
            if (
                edition is None
                or edition_state is None
                or manifest is None
                or edition_state.edition_id != edition.id
                or edition_state.current_manifest_revision
                != manifest.manifest_revision
                or manifest.edition_id != edition.id
                or manifest.schema_version != "narration-manifest/2.0"
                or manifest.status != "ready"
                or manifest.ready_prefix_count <= 0
                or manifest.total_duration_ms <= 0
            ):
                missing.add("CURRENT_MANIFEST_NOT_READY")

            voice = self._audit_voice_authority(session, attestation)
            missing.update(voice.missing_codes)
            authority_fingerprint: str | None = None
            if (
                not missing
                and voice.authority_fingerprint_sha256 is not None
                and novel is not None
                and document is not None
                and working is not None
                and state is not None
                and edition is not None
                and script is not None
                and script_version is not None
                and edition_state is not None
                and manifest is not None
            ):
                authority_fingerprint = _authority_fingerprint(
                    {
                        "database_revision": list(revisions),
                        "scope": {
                            "novel_id": str(novel.id),
                            "document_id": str(document.id),
                        },
                        "working_copy": {
                            "draft_version": working.draft_version,
                            "content_hash": working.content_hash,
                            "base_revision_id": (
                                str(working.base_revision_id)
                                if working.base_revision_id is not None
                                else None
                            ),
                        },
                        "narration_state": {
                            "state_id": str(state.id),
                            "version": state.version,
                            "script_id": str(state.script_id),
                            "script_version_id": str(
                                state.current_script_version_id
                            ),
                            "edition_id": str(state.current_edition_id),
                        },
                        "script": {
                            "id": str(script.id),
                            "content_hash": script.content_hash,
                            "version_id": str(script_version.id),
                            "state": script_version.state,
                            "blocker_count": script_version.blocker_count,
                        },
                        "edition": {
                            "id": str(edition.id),
                            "script_version_id": str(
                                edition.script_version_id
                            ),
                            "settings_snapshot_id": str(
                                edition.settings_snapshot_id
                            ),
                            "tts_fingerprint": edition.tts_fingerprint,
                            "tokenizer_fingerprint": (
                                edition.tokenizer_fingerprint
                            ),
                            "normalizer_fingerprint": (
                                edition.normalizer_fingerprint
                            ),
                            "postprocess_fingerprint": (
                                edition.postprocess_fingerprint
                            ),
                            "edition_fingerprint": (
                                edition.edition_fingerprint
                            ),
                            "state": edition.state,
                        },
                        "manifest": {
                            "state_version": edition_state.version,
                            "id": str(manifest.id),
                            "revision": manifest.manifest_revision,
                            "etag_sha256": manifest.etag_sha256,
                            "ready_prefix_count": (
                                manifest.ready_prefix_count
                            ),
                            "total_duration_ms": (
                                manifest.total_duration_ms
                            ),
                        },
                        "voice_authority_sha256": (
                            voice.authority_fingerprint_sha256
                        ),
                    }
                )
        return DatabaseReadinessEvidence(
            missing_codes=tuple(sorted(missing)),
            voice_role_count=voice.voice_role_count,
            distinct_profile_count=voice.distinct_profile_count,
            distinct_voice_version_count=voice.distinct_voice_version_count,
            official_preset_count=voice.official_preset_count,
            official_provenance_verified_count=(
                voice.official_provenance_verified_count
            ),
            database_checks_completed=True,
            authority_fingerprint_sha256=authority_fingerprint,
        )

    def _audit_voice_authority(
        self,
        session: Session,
        attestation: ReadinessAttestation,
    ) -> DatabaseReadinessEvidence:
        missing: set[str] = set()
        role_authority: list[dict[str, object]] = []
        expected_preset_by_role = {
            item.role: item.preset_id
            for item in attestation.expected_official_presets
        }
        settings = session.scalar(
            select(NovelNarrationSettings).where(
                NovelNarrationSettings.novel_id == attestation.novel_id
            )
        )
        characters = session.scalars(
            select(NovelCharacter).where(
                NovelCharacter.novel_id == attestation.novel_id,
                NovelCharacter.lifecycle_state == "active",
                NovelCharacter.name.in_(EXPECTED_CHARACTERS),
            )
        ).all()
        character_by_name = {row.name: row for row in characters}
        if set(character_by_name) != set(EXPECTED_CHARACTERS):
            missing.add("REQUIRED_CHARACTER_CAST_NOT_READY")
        bindings = session.scalars(
            select(CharacterVoiceBinding).where(
                CharacterVoiceBinding.novel_id == attestation.novel_id,
                CharacterVoiceBinding.character_id.in_(
                    tuple(row.id for row in characters)
                ),
            )
        ).all()
        binding_by_character = {row.character_id: row for row in bindings}

        roles: list[tuple[str, UUID, UUID]] = []
        if (
            settings is None
            or settings.narrator_profile_id is None
            or settings.narrator_version_id is None
            or settings.script_review_policy != "blockers_only"
        ):
            missing.add("NARRATOR_VOICE_NOT_READY")
        else:
            roles.append(
                (
                    "narrator",
                    settings.narrator_profile_id,
                    settings.narrator_version_id,
                )
            )
            role_authority.append(
                {
                    "role": "narrator",
                    "profile_id": str(settings.narrator_profile_id),
                    "voice_version_id": str(settings.narrator_version_id),
                    "settings_id": str(settings.id),
                    "settings_version": settings.version,
                }
            )
        for name in EXPECTED_CHARACTERS:
            character = character_by_name.get(name)
            binding = (
                binding_by_character.get(character.id)
                if character is not None
                else None
            )
            if (
                binding is None
                or binding.binding_policy != "dedicated"
                or binding.profile_id is None
                or binding.voice_version_id is None
            ):
                missing.add("DEDICATED_CHARACTER_VOICES_NOT_READY")
                continue
            roles.append((name, binding.profile_id, binding.voice_version_id))
            role_authority.append(
                {
                    "role": "character",
                    "character_name": name,
                    "character_id": str(character.id),
                    "character_version": character.version,
                    "binding_id": str(binding.id),
                    "binding_version": binding.version,
                    "profile_id": str(binding.profile_id),
                    "voice_version_id": str(binding.voice_version_id),
                }
            )
        profile_ids = {profile_id for _role, profile_id, _version_id in roles}
        version_ids = {version_id for _role, _profile_id, version_id in roles}
        if len(roles) != 3 or len(profile_ids) != 3 or len(version_ids) != 3:
            missing.add("THREE_DISTINCT_VOICES_NOT_READY")
        if not roles:
            return DatabaseReadinessEvidence(
                missing_codes=tuple(sorted(missing)),
                voice_role_count=0,
                distinct_profile_count=0,
                distinct_voice_version_count=0,
                official_preset_count=0,
                official_provenance_verified_count=0,
                database_checks_completed=True,
                authority_fingerprint_sha256=None,
            )
        expected_profiles = {
            version_id: profile_id
            for _role, profile_id, version_id in roles
        }
        role_by_version = {
            version_id: role for role, _profile_id, version_id in roles
        }
        versions = {
            row.id: row
            for row in session.scalars(
                select(VoiceProfileVersion).where(
                    VoiceProfileVersion.id.in_(tuple(version_ids))
                )
            ).all()
        }
        profiles = {
            row.id: row
            for row in session.scalars(
                select(VoiceProfile).where(VoiceProfile.id.in_(tuple(profile_ids)))
            ).all()
        }
        if set(versions) != version_ids or set(profiles) != profile_ids:
            missing.add("VOICE_AUTHORITY_ROWS_NOT_READY")
        rights_ids = {row.rights_record_id for row in versions.values()}
        rights = {
            row.id: row
            for row in session.scalars(
                select(VoiceRightsRecord).where(
                    VoiceRightsRecord.id.in_(tuple(rights_ids))
                )
            ).all()
        }
        confirmed_rights = set(
            session.scalars(
                select(VoiceRightsEvent.rights_record_id).where(
                    VoiceRightsEvent.rights_record_id.in_(tuple(rights_ids)),
                    VoiceRightsEvent.event_type == "confirmed",
                )
            ).all()
        )
        negative_rights = set(
            session.scalars(
                select(VoiceRightsEvent.rights_record_id).where(
                    VoiceRightsEvent.rights_record_id.in_(tuple(rights_ids)),
                    VoiceRightsEvent.event_type.in_(tuple(_NEGATIVE_RIGHTS_EVENTS)),
                )
            ).all()
        )
        deletion_profiles = set(
            session.scalars(
                select(VoiceDeletionRequest.voice_profile_id).where(
                    VoiceDeletionRequest.voice_profile_id.in_(tuple(profile_ids)),
                    VoiceDeletionRequest.state.in_(tuple(_ACTIVE_DELETION_STATES)),
                )
            ).all()
        )
        if deletion_profiles:
            missing.add("VOICE_DELETION_RISK_PRESENT")

        verified_provenance: dict[UUID, dict[str, object]] = {}
        now = datetime.now(timezone.utc)
        for version_id, profile_id in expected_profiles.items():
            version = versions.get(version_id)
            profile = profiles.get(profile_id)
            role = role_by_version[version_id]
            expected_preset_id = expected_preset_by_role.get(role)
            if (
                version is None
                or expected_preset_id is None
                or version.profile_id != profile_id
                or version.owner_id != LOCAL_OWNER_ID
                or version.workspace_id != LOCAL_WORKSPACE_ID
                or version.source_type != "preset"
                or version.reference_asset_id is not None
                or version.state != "locked"
                or version.quality_state != "accepted"
                or version.locked_actor is None
                or version.locked_at is None
                or _SHA256_RE.fullmatch(version.fingerprint) is None
                or profile is None
                or profile.owner_id != LOCAL_OWNER_ID
                or profile.workspace_id != LOCAL_WORKSPACE_ID
                or profile.novel_id != attestation.novel_id
                or profile.status != "active"
                or profile.current_version_id != version_id
            ):
                missing.add("VOICE_VERSION_NOT_READY")
                continue
            right = rights.get(version.rights_record_id)
            if (
                right is None
                or right.owner_id != LOCAL_OWNER_ID
                or right.workspace_id != LOCAL_WORKSPACE_ID
                or right.novel_id != attestation.novel_id
                or right.source_kind != "official_preset"
                or right.purpose != "private_novel_narration"
                or right.commercial_use is not False
                or right.redistribution is not False
                or right.voice_cloning is not False
                or right.subject_consent_reference is not None
                or not right.confirmed_actor
                or right.confirmed_at is None
                or right.id not in confirmed_rights
                or right.id in negative_rights
                or (right.expires_at is not None and right.expires_at <= now)
            ):
                missing.add("VOICE_RIGHTS_NOT_READY")
            provenance = _official_preset_provenance(
                version,
                expected_preset_id=expected_preset_id,
            )
            if provenance is None:
                missing.add("OFFICIAL_PRESET_PROVENANCE_NOT_READY")
            else:
                verified_provenance[version.id] = provenance

        preset_ids = {
            str(row["preset_id"]) for row in verified_provenance.values()
        }
        if len(preset_ids) != 3:
            missing.add("THREE_DISTINCT_OFFICIAL_PRESETS_NOT_READY")
        authority_fingerprint: str | None = None
        if not missing:
            authority_fingerprint = _authority_fingerprint(
                {
                    "roles": role_authority,
                    "profiles": [
                        {
                            "id": str(row.id),
                            "current_version_id": str(row.current_version_id),
                            "status": row.status,
                            "version": row.version,
                        }
                        for row in sorted(
                            profiles.values(), key=lambda item: str(item.id)
                        )
                    ],
                    "versions": [
                        {
                            "id": str(row.id),
                            "profile_id": str(row.profile_id),
                            "version_number": row.version_number,
                            "preset_id": row.preset_key,
                            "rights_record_id": str(row.rights_record_id),
                            "fingerprint": row.fingerprint,
                            "state": row.state,
                            "quality_state": row.quality_state,
                            "locked_at": _authority_time(row.locked_at),
                            "official_preset": verified_provenance[row.id],
                        }
                        for row in sorted(
                            versions.values(), key=lambda item: str(item.id)
                        )
                    ],
                    "rights": [
                        {
                            "id": str(row.id),
                            "source_kind": row.source_kind,
                            "source_identifier_sha256": _authority_fingerprint(
                                row.source_identifier
                            ),
                            "notice_version": row.notice_version,
                            "purpose": row.purpose,
                            "commercial_use": row.commercial_use,
                            "redistribution": row.redistribution,
                            "voice_cloning": row.voice_cloning,
                            "confirmed_at": _authority_time(row.confirmed_at),
                            "expires_at": _authority_time(row.expires_at),
                            "risk_flags": sorted(row.risk_flags_json),
                        }
                        for row in sorted(
                            rights.values(), key=lambda item: str(item.id)
                        )
                    ],
                    "confirmed_rights": sorted(
                        str(value) for value in confirmed_rights
                    ),
                    "negative_rights": sorted(
                        str(value) for value in negative_rights
                    ),
                    "deletion_profiles": sorted(
                        str(value) for value in deletion_profiles
                    ),
                }
            )
        return DatabaseReadinessEvidence(
            missing_codes=tuple(sorted(missing)),
            voice_role_count=len(roles),
            distinct_profile_count=len(profile_ids),
            distinct_voice_version_count=len(version_ids),
            official_preset_count=len(preset_ids),
            official_provenance_verified_count=len(verified_provenance),
            database_checks_completed=True,
            authority_fingerprint_sha256=authority_fingerprint,
        )

    @staticmethod
    def _media_metadata_ready(
        asset: MediaAsset | None,
        *,
        novel_id: UUID,
        asset_class: str,
        retention: str,
    ) -> bool:
        if asset is None or asset.content_hash is None:
            return False
        suffix = Path(asset.storage_path).suffix
        expected = (
            f"assets/{asset.id.hex[:2]}/{asset.id.hex}/"
            f"{asset.content_hash}{suffix}"
        )
        normalized_reference = asset_class == "voice_reference"
        return (
            asset.owner_id == LOCAL_OWNER_ID
            and asset.workspace_id == LOCAL_WORKSPACE_ID
            and asset.novel_id == novel_id
            and asset.asset_class == asset_class
            and asset.storage_backend == "local"
            and asset.state == "ready"
            and asset.retention_policy == retention
            and type(asset.mime_type) is str
            and asset.mime_type.startswith("audio/")
            and type(asset.byte_size) is int
            and 0 < asset.byte_size <= MAX_VOICE_MEDIA_BYTES
            and type(asset.duration_ms) is int
            and asset.duration_ms > 0
            and (not normalized_reference or asset.sample_rate == 48_000)
            and (not normalized_reference or asset.channels == 2)
            and asset.checksum_algorithm == "sha256"
            and _SHA256_RE.fullmatch(asset.content_hash) is not None
            and asset.verified_at is not None
            and asset.expires_at is None
            and asset.deleted_at is None
            and asset.gc_marked_at is None
            and suffix in {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav"}
            and asset.storage_path == expected
        )

    def _verify_physical_media(self, asset: MediaAsset) -> bool:
        if self._storage is None or asset.byte_size is None:
            return False
        try:
            self._storage.verify_media_identity(
                asset.storage_path,
                expected_sha256=asset.content_hash,
                expected_size=asset.byte_size,
                max_bytes=MAX_VOICE_MEDIA_BYTES,
            )
            return True
        except (StorageError, OSError, ValueError):
            return False


def evaluate_readiness(
    attestation: ReadinessAttestation,
    *,
    reader: ReadinessReader,
    _preheld_resource_locks: tuple[str, ...] | None = None,
    _include_authority_fingerprint: bool = False,
) -> dict[str, object]:
    """Return a fully redacted HOLD report; never return a PASS verdict."""

    if type(attestation) is not ReadinessAttestation:
        raise ReadinessError("ATTESTATION_SCOPE_INVALID")
    missing = _fixed_fixture_missing(attestation)
    if not attestation.dedicated_test_novel:
        missing.add("DEDICATED_NOVEL_DECLARATION_REQUIRED")
    if not attestation.dedicated_test_chapter:
        missing.add("DEDICATED_CHAPTER_DECLARATION_REQUIRED")
    if not attestation.append_only_recovery_accepted:
        missing.add("APPEND_ONLY_RECOVERY_DECLARATION_REQUIRED")
    if not attestation.official_presets_local_use:
        missing.add("OFFICIAL_PRESET_LOCAL_USE_DECLARATION_REQUIRED")
    if (
        len(attestation.expected_official_presets) != 3
        or frozenset(
            (item.role, item.preset_id)
            for item in attestation.expected_official_presets
        )
        != EXPECTED_OFFICIAL_PRESETS
    ):
        missing.add("THREE_DISTINCT_OFFICIAL_PRESETS_NOT_READY")
    if attestation.expected_characters != EXPECTED_CHARACTERS:
        missing.add("REQUIRED_CHARACTER_CAST_NOT_READY")
    if attestation.required_captures != EXPECTED_CAPTURES:
        missing.add("EXACT_DESKTOP_CAPTURE_MATRIX_NOT_READY")
    if _preheld_resource_locks is None:
        lock_missing, ready_locks = _resource_lock_missing(attestation)
    elif _preheld_resource_locks == EXPECTED_LOCK_NAMES:
        # The fixed launcher owns these three exact lock descriptors for the
        # enclosing call.  Re-opening and flocking the same inode would report
        # a false busy result on platforms whose flock locks are open-file
        # scoped.  This internal seam does not weaken the standalone CLI,
        # which always performs its own non-blocking lock acquisition.
        lock_missing, ready_locks = set(), len(EXPECTED_LOCK_NAMES)
    else:
        raise ReadinessError("RESOURCE_LOCK_SET_NOT_READY")
    missing.update(lock_missing)
    try:
        evidence = reader.audit(attestation)
        if type(evidence) is not DatabaseReadinessEvidence:
            raise ReadinessError("DATABASE_EVIDENCE_INVALID")
        missing.update(evidence.missing_codes)
        if evidence.database_checks_completed is not True:
            missing.add("DATABASE_CHECKS_NOT_READY")
        if (
            evidence.voice_role_count != 3
            or evidence.distinct_profile_count != 3
            or evidence.distinct_voice_version_count != 3
        ):
            missing.add("THREE_DISTINCT_VOICES_NOT_READY")
        if (
            evidence.official_preset_count != 3
            or evidence.official_provenance_verified_count != 3
        ):
            missing.add("OFFICIAL_PRESET_PROVENANCE_NOT_READY")
        if (
            evidence.authority_fingerprint_sha256 is None
            or _SHA256_RE.fullmatch(
                evidence.authority_fingerprint_sha256
            )
            is None
        ):
            missing.add("AUTHORITY_FINGERPRINT_NOT_READY")
    except ReadinessError as error:
        missing.add(error.code)
        evidence = DatabaseReadinessEvidence(
            missing_codes=(),
            voice_role_count=0,
            distinct_profile_count=0,
            distinct_voice_version_count=0,
            official_preset_count=0,
            official_provenance_verified_count=0,
            database_checks_completed=False,
            authority_fingerprint_sha256=None,
        )
    codes = tuple(sorted(missing))
    summary: dict[str, object] = {
        "database_checks_completed": evidence.database_checks_completed,
        "required_capture_count": len(EXPECTED_CAPTURES),
        "resource_locks_ready_count": ready_locks,
        "voice_role_count": evidence.voice_role_count,
        "distinct_profile_count": evidence.distinct_profile_count,
        "distinct_voice_version_count": evidence.distinct_voice_version_count,
        "official_preset_count": evidence.official_preset_count,
        "official_provenance_verified_count": (
            evidence.official_provenance_verified_count
        ),
    }
    if _include_authority_fingerprint:
        summary["authority_fingerprint_sha256"] = (
            evidence.authority_fingerprint_sha256
        )
    return {
        "schema_version": REPORT_SCHEMA,
        "status": "HOLD",
        "decision": (
            "READY_FOR_OPERATOR_REVIEW" if not codes else "NOT_READY"
        ),
        "mode": "readonly",
        "release_gate_passed": False,
        "missing_codes": list(codes),
        "summary": summary,
    }


def _failure_report(code: str) -> dict[str, object]:
    safe = code if _SAFE_CODE_RE.fullmatch(code) is not None else "READINESS_INTERNAL_ERROR"
    return {
        "schema_version": REPORT_SCHEMA,
        "status": "HOLD",
        "decision": "NOT_READY",
        "mode": "readonly",
        "release_gate_passed": False,
        "missing_codes": [safe],
        "summary": {
            "database_checks_completed": False,
            "required_capture_count": len(EXPECTED_CAPTURES),
            "resource_locks_ready_count": 0,
            "voice_role_count": 0,
            "distinct_profile_count": 0,
            "distinct_voice_version_count": 0,
            "official_preset_count": 0,
            "official_provenance_verified_count": 0,
        },
    }


def _storage_from_environment() -> NarrationStorage | None:
    model_value = os.environ.get(MODEL_METADATA_ROOT_ENV, "")
    media_value = os.environ.get(MEDIA_ROOT_ENV, "")
    if not model_value or not media_value:
        return None
    model_path = Path(model_value)
    media_path = Path(media_value)
    if not model_path.is_absolute() or not media_path.is_absolute():
        return None
    try:
        return NarrationStorage(models_root=model_path, media_root=media_path)
    except (StorageError, OSError, ValueError):
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(description=__doc__, add_help=False)
    parser.add_argument("--mode", choices=("readonly",), required=True)
    parser.add_argument("--attestation-file", type=Path, required=True)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    reader: ReadinessReader | None = None,
) -> int:
    try:
        args = build_parser().parse_args(argv)
        attestation = load_private_attestation(args.attestation_file)
        authority_reader = reader
        if authority_reader is None:
            authority_reader = SqlAlchemyReadinessReader(
                sessionmaker(bind=get_engine(), expire_on_commit=False),
                storage=_storage_from_environment(),
            )
        report = evaluate_readiness(attestation, reader=authority_reader)
        sys.stdout.write(_canonical_json(report) + "\n")
        return 0 if report["decision"] == "READY_FOR_OPERATOR_REVIEW" else 2
    except ReadinessError as error:
        sys.stdout.write(_canonical_json(_failure_report(error.code)) + "\n")
        return 2
    except BaseException:
        sys.stdout.write(
            _canonical_json(_failure_report("READINESS_INTERNAL_ERROR")) + "\n"
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ATTESTATION_SCHEMA",
    "DatabaseReadinessEvidence",
    "EXPECTED_CAPTURES",
    "REPORT_SCHEMA",
    "ReadinessAttestation",
    "ReadinessError",
    "SqlAlchemyReadinessReader",
    "evaluate_readiness",
    "load_private_attestation",
    "main",
]
