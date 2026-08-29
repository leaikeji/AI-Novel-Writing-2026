"""Fail-closed PawApp owner for playback, production API, and one local worker.

This module adds no service, queue, or database.  It composes the existing
PostgreSQL job authority, private Sidecar adapter, immutable media storage, and
fixed FFmpeg toolchain inside the PawApp process.  Importing it performs no I/O.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
from pathlib import Path
import re
import stat
from threading import Lock
from typing import Callable, Mapping
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..database import DatabaseNotConfigured, get_engine
from ..models import Document, MediaAsset
from . import schemas as wire
from .audio_pipeline import audio_processing_fingerprint
from .contracts import ModelFingerprint
from .digest_keyring import DigestKeyringError, load_digest_keyring
from .disk_guard import NarrationDiskGuard
from .edition_service import NarrationProductionPolicy
from .fingerprints import model_fingerprint_sha256
from .narration_api import (
    NarrationProductionBackendFactory,
    build_narration_production_backend_factory,
    install_narration_production_backend_factory,
    uninstall_narration_production_backend_factory,
)
from .pawapp_runtime import (
    PRODUCT_ENABLE_ENV,
    get_ready_narration_adapter,
    launch_narration_runtime,
    narration_runtime_status,
    wait_narration_runtime_initialized,
)
from .playback_api import (
    PlaybackApiBackendFactory,
    build_playback_api_backend_factory,
    install_playback_api_backend_factory,
    uninstall_playback_api_backend_factory,
)
from .pronunciations import (
    NarrationCacheRuntime,
    SqlAlchemyNarrationCacheRuntime,
)
from .scheduler import NarrationJobScheduler, SchedulerConfig
from .services import canonical_sha256
from .storage import NarrationStorage, StorageError
from .runtime import SidecarMossNanoTTSAdapter
from .transcoding import (
    DEFAULT_TRANSCODING_POLICY,
    TranscodingPolicy,
    transcoding_fingerprint,
    validate_fixed_toolchain,
)
from .voice_media import (
    DEFAULT_REFERENCE_NORMALIZATION_POLICY,
    NormalizedReferenceAudio,
    normalize_reference_audio,
)
from .voice_product import (
    VOICE_PREVIEW_JOB_KIND,
    SqlAlchemyVoicePreviewRepository,
    VoicePreviewNotFound,
    VoicePreviewPolicy,
    VoicePreviewProcessor,
    VoiceProductService,
    resolve_voice_preview_media,
)
from .voices import ParsedUploadedVoice
from .worker import (
    FixedFfmpegTranscoder,
    NarrationSegmentWorker,
    NarrationWorkerConfig,
    SqlAlchemyNarrationWorkerRepository,
)


DIGEST_KEYRING_FILE_ENV = "AI_NOVEL_TTS_DIGEST_KEYRING_FILE"
MODEL_METADATA_ROOT_ENV = "AI_NOVEL_TTS_MODEL_METADATA_ROOT"
MEDIA_ROOT_ENV = "AI_NOVEL_TTS_MEDIA_ROOT"
FFMPEG_PATH_ENV = "AI_NOVEL_TTS_FFMPEG_PATH"
FFPROBE_PATH_ENV = "AI_NOVEL_TTS_FFPROBE_PATH"
FFMPEG_BUILD_ID_ENV = "MOSS_FFMPEG_BUILD_ID"
TECHNICAL_RUNTIME_ENABLE_ENV = "AI_NOVEL_TTS_RUNTIME_ENABLED"
VALIDATION_ENABLE_ENV = "AI_NOVEL_TTS_VALIDATION_ENABLED"
VALIDATION_TOKEN_FILE_ENV = "AI_NOVEL_TTS_VALIDATION_TOKEN_FILE"
VALIDATION_NOVEL_ID_ENV = "AI_NOVEL_TTS_VALIDATION_NOVEL_ID"
VALIDATION_DOCUMENT_ID_ENV = "AI_NOVEL_TTS_VALIDATION_DOCUMENT_ID"
VALIDATION_EXPIRES_AT_ENV = "AI_NOVEL_TTS_VALIDATION_EXPIRES_AT"
REFERENCE_CLONE_ENABLE_ENV = "AI_NOVEL_TTS_REFERENCE_CLONE_ENABLED"

TOKENIZER_FINGERPRINT_VERSION = "narration-moss-tokenizer-fingerprint/1"
NORMALIZER_FINGERPRINT_VERSION = "narration-spoken-text-normalizer/1"
WORKER_TASK_NAME = "ai-novel-moss-tts-production-worker"
WORKER_CYCLE_TASK_NAME = "ai-novel-moss-tts-worker-cycle"
SIDECAR_RETRY_SECONDS = 1.0
EXPECTED_DATABASE_REVISION = "20260829_0032"
PRODUCTION_TRANSCODING_POLICY = replace(
    DEFAULT_TRANSCODING_POLICY,
    allow_wav_fallback=False,
)

_SAFE_REASON = re.compile(r"^[A-Z][A-Z0-9_]{0,95}$")
_VALIDATION_TOKEN = re.compile(r"^[A-Za-z0-9_-]{43,128}$")
_VALIDATION_EXPIRY = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
MAX_VALIDATION_LIFETIME = timedelta(hours=24)


class NarrationProductionRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class ValidationRuntimeScope:
    """Non-secret, expiring scope for one dedicated T4-K chapter run."""

    novel_id: UUID
    document_id: UUID
    expires_at: datetime

    def active(self, *, now: datetime | None = None) -> bool:
        current = datetime.now(timezone.utc) if now is None else now
        return current.tzinfo is not None and current < self.expires_at


@dataclass(frozen=True, slots=True)
class ValidationSegmentClaimGateSnapshot:
    """Redacted state returned to the fixed local validation controller."""

    code: str
    state: str
    claim_limit: int
    claimed_count: int
    remaining_count: int
    expires_at: datetime | None
    run_fingerprint_sha256: str | None
    scope_fingerprint_sha256: str | None


@dataclass(slots=True)
class _ValidationSegmentClaimGateState:
    generation: int
    run_id: UUID
    novel_id: UUID
    document_id: UUID
    expires_at: datetime
    claim_limit: int
    claimed_count: int = 0
    reserved_count: int = 0


class _ValidationSegmentClaimReservation:
    def __init__(
        self,
        gate: "ValidationSegmentClaimGate",
        *,
        allowed_job_kinds: tuple[str, ...],
        generation: int | None,
        reserved_segment: bool,
    ) -> None:
        self.allowed_job_kinds = allowed_job_kinds
        self._gate = gate
        self._generation = generation
        self._reserved_segment = reserved_segment
        self._settled = False
        self._lock = Lock()

    def settle(self, claimed_job_kind: str | None) -> None:
        with self._lock:
            if self._settled:
                raise RuntimeError("validation claim reservation is already settled")
            self._settled = True
        if claimed_job_kind is not None and claimed_job_kind not in self.allowed_job_kinds:
            self._gate._settle_reservation(
                self._generation,
                reserved_segment=self._reserved_segment,
                claimed_job_kind=None,
            )
            raise RuntimeError("validation claim reservation kind mismatch")
        self._gate._settle_reservation(
            self._generation,
            reserved_segment=self._reserved_segment,
            claimed_job_kind=claimed_job_kind,
        )


class ValidationSegmentClaimGate:
    """One-process validation-only segment claim limiter.

    An unarmed or expired gate is deliberately default-allow. An armed gate
    reserves a bounded segment allowance before a scheduler transaction and
    consumes it only after a real segment job is claimed. Other job kinds and
    scheduler maintenance are never paused.
    """

    _SEGMENT_KIND = "narration.segment_render"

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = Lock()
        self._state: _ValidationSegmentClaimGateState | None = None
        self._next_generation = 1

    def _now(self) -> datetime:
        current = self._clock()
        if current.tzinfo is None or current.utcoffset() is None:
            raise NarrationProductionRuntimeError(
                "TTS_VALIDATION_CLAIM_GATE_CLOCK_INVALID",
                "validation claim gate clock must be timezone-aware",
            )
        return current.astimezone(timezone.utc)

    def _expire_locked(self, now: datetime) -> None:
        state = self._state
        if state is not None and now >= state.expires_at:
            self._state = None

    @staticmethod
    def _fingerprint(prefix: bytes, *identities: UUID) -> str:
        digest = hashlib.sha256(prefix)
        for identity in identities:
            digest.update(b"\x00")
            digest.update(str(identity).encode("ascii"))
        return digest.hexdigest()

    def _snapshot_locked(
        self,
        *,
        code: str | None = None,
        released: _ValidationSegmentClaimGateState | None = None,
    ) -> ValidationSegmentClaimGateSnapshot:
        state = self._state if released is None else released
        if state is None:
            return ValidationSegmentClaimGateSnapshot(
                code=code or "VALIDATION_SEGMENT_CLAIM_GATE_DEFAULT_ALLOW",
                state="default_allow",
                claim_limit=0,
                claimed_count=0,
                remaining_count=0,
                expires_at=None,
                run_fingerprint_sha256=None,
                scope_fingerprint_sha256=None,
            )
        remaining = max(0, state.claim_limit - state.claimed_count)
        return ValidationSegmentClaimGateSnapshot(
            code=code or (
                "VALIDATION_SEGMENT_CLAIM_GATE_PAUSED"
                if remaining == 0
                else "VALIDATION_SEGMENT_CLAIM_GATE_ARMED"
            ),
            state=("default_allow" if released is not None else (
                "paused" if remaining == 0 else "armed"
            )),
            claim_limit=state.claim_limit,
            claimed_count=state.claimed_count,
            remaining_count=remaining,
            expires_at=state.expires_at,
            run_fingerprint_sha256=self._fingerprint(
                b"narration-validation-claim-gate-run/1",
                state.run_id,
            ),
            scope_fingerprint_sha256=self._fingerprint(
                b"narration-validation-claim-gate-scope/1",
                state.novel_id,
                state.document_id,
            ),
        )

    def arm(
        self,
        *,
        run_id: UUID,
        novel_id: UUID,
        document_id: UUID,
        runtime_expires_at: datetime,
        ttl_seconds: int = 120,
        claim_limit: int = 1,
    ) -> ValidationSegmentClaimGateSnapshot:
        if any(type(value) is not UUID for value in (run_id, novel_id, document_id)):
            raise NarrationProductionRuntimeError(
                "TTS_VALIDATION_CLAIM_GATE_SCOPE_INVALID",
                "validation claim gate identity is invalid",
            )
        if (
            runtime_expires_at.tzinfo is None
            or runtime_expires_at.utcoffset() is None
            or type(ttl_seconds) is not int
            or not 1 <= ttl_seconds <= 300
            or type(claim_limit) is not int
            or not 1 <= claim_limit <= 16
        ):
            raise NarrationProductionRuntimeError(
                "TTS_VALIDATION_CLAIM_GATE_INPUT_INVALID",
                "validation claim gate bounds are invalid",
            )
        now = self._now()
        expires_at = min(
            now + timedelta(seconds=ttl_seconds),
            runtime_expires_at.astimezone(timezone.utc),
        )
        if expires_at <= now:
            raise NarrationProductionRuntimeError(
                "TTS_VALIDATION_CLAIM_GATE_EXPIRED",
                "validation claim gate expiry is unavailable",
            )
        with self._lock:
            self._expire_locked(now)
            existing = self._state
            if existing is not None:
                if (
                    existing.run_id == run_id
                    and existing.novel_id == novel_id
                    and existing.document_id == document_id
                    and existing.claim_limit == claim_limit
                ):
                    return self._snapshot_locked()
                raise NarrationProductionRuntimeError(
                    "TTS_VALIDATION_CLAIM_GATE_ALREADY_ARMED",
                    "another validation claim gate is already armed",
                )
            self._state = _ValidationSegmentClaimGateState(
                generation=self._next_generation,
                run_id=run_id,
                novel_id=novel_id,
                document_id=document_id,
                expires_at=expires_at,
                claim_limit=claim_limit,
            )
            self._next_generation += 1
            return self._snapshot_locked()

    def reserve(
        self,
        configured_job_kinds: tuple[str, ...],
    ) -> _ValidationSegmentClaimReservation:
        if (
            type(configured_job_kinds) is not tuple
            or len(configured_job_kinds) != len(set(configured_job_kinds))
            or any(type(kind) is not str or not kind for kind in configured_job_kinds)
        ):
            raise NarrationProductionRuntimeError(
                "TTS_VALIDATION_CLAIM_GATE_INPUT_INVALID",
                "validation claim kinds are invalid",
            )
        now = self._now()
        with self._lock:
            self._expire_locked(now)
            state = self._state
            if state is None or self._SEGMENT_KIND not in configured_job_kinds:
                return _ValidationSegmentClaimReservation(
                    self,
                    allowed_job_kinds=configured_job_kinds,
                    generation=None,
                    reserved_segment=False,
                )
            available = (
                state.claimed_count + state.reserved_count < state.claim_limit
            )
            allowed = tuple(
                kind
                for kind in configured_job_kinds
                if kind != self._SEGMENT_KIND or available
            )
            if available:
                state.reserved_count += 1
            return _ValidationSegmentClaimReservation(
                self,
                allowed_job_kinds=allowed,
                generation=state.generation,
                reserved_segment=available,
            )

    def _settle_reservation(
        self,
        generation: int | None,
        *,
        reserved_segment: bool,
        claimed_job_kind: str | None,
    ) -> None:
        if generation is None or not reserved_segment:
            return
        with self._lock:
            state = self._state
            if state is None or state.generation != generation:
                return
            state.reserved_count = max(0, state.reserved_count - 1)
            if claimed_job_kind == self._SEGMENT_KIND:
                state.claimed_count = min(state.claim_limit, state.claimed_count + 1)

    def snapshot(self) -> ValidationSegmentClaimGateSnapshot:
        now = self._now()
        with self._lock:
            self._expire_locked(now)
            return self._snapshot_locked()

    def release(
        self,
        *,
        run_id: UUID,
        novel_id: UUID,
        document_id: UUID,
    ) -> ValidationSegmentClaimGateSnapshot:
        now = self._now()
        with self._lock:
            self._expire_locked(now)
            state = self._state
            if state is None:
                return self._snapshot_locked()
            if (
                state.run_id != run_id
                or state.novel_id != novel_id
                or state.document_id != document_id
            ):
                raise NarrationProductionRuntimeError(
                    "TTS_VALIDATION_CLAIM_GATE_BINDING_MISMATCH",
                    "validation claim gate binding does not match",
                )
            self._state = None
            return self._snapshot_locked(
                code="VALIDATION_SEGMENT_CLAIM_GATE_RELEASED",
                released=state,
            )

    def clear(self) -> None:
        with self._lock:
            self._state = None


@dataclass(frozen=True, slots=True)
class NarrationProductionRuntimeSnapshot:
    # Historical field name retained for the public health contract.  It means
    # that the production pipeline was explicitly requested either by the
    # released product gate or by the mutually-exclusive, hidden T4 validation
    # gate.  Public product visibility remains owned only by PRODUCT_ENABLE_ENV.
    product_requested: bool = False
    lifecycle_status: str = "disabled"
    playback_installed: bool = False
    digest_keyring_loaded: bool = False
    production_backend_installed: bool = False
    worker_running: bool = False
    reference_clone_ready: bool = False
    reason_code: str | None = None

    def public_dict(self) -> dict[str, object]:
        return asdict(self)


_lifecycle_lock = asyncio.Lock()
_runtime_task: asyncio.Task[None] | None = None
_stop_event: asyncio.Event | None = None
_playback_factory: PlaybackApiBackendFactory | None = None
_production_factory: NarrationProductionBackendFactory | None = None
_production_policy: NarrationProductionPolicy | None = None
_voice_product_port: VoiceProductService | None = None
_disk_guard: NarrationDiskGuard | None = None
_cache_runtime: NarrationCacheRuntime | None = None
_validation_token_digest: bytes | None = None
_validation_runtime_scope: ValidationRuntimeScope | None = None
_validation_segment_claim_gate = ValidationSegmentClaimGate()
_snapshot = NarrationProductionRuntimeSnapshot()


def _safe_reason(error: BaseException, fallback: str) -> str:
    code = getattr(error, "code", None)
    if isinstance(code, str) and _SAFE_REASON.fullmatch(code):
        return code
    return fallback


def narration_production_runtime_status() -> dict[str, object]:
    """Return a path-, key-, and text-free health snapshot without I/O."""

    snapshot = _snapshot
    guard = _disk_guard
    if (
        guard is not None
        and snapshot.lifecycle_status == "ready"
        and snapshot.reason_code is None
    ):
        reason_code = guard.status().reason_code
        if reason_code is not None:
            snapshot = replace(snapshot, reason_code=reason_code)
    return snapshot.public_dict()


def _exact_flag(values: Mapping[str, str], name: str) -> bool:
    raw = values.get(name, "false")
    if raw not in {"true", "false"}:
        raise NarrationProductionRuntimeError(
            "TTS_PRODUCT_CONFIGURATION_INVALID",
            "narration product feature flag is invalid",
        )
    return raw == "true"


def _absolute_path(values: Mapping[str, str], name: str) -> Path:
    value = values.get(name, "")
    path = Path(value)
    if not value or not path.is_absolute():
        raise NarrationProductionRuntimeError(
            "TTS_PRODUCT_CONFIGURATION_INVALID",
            "narration production path configuration is invalid",
        )
    return path


def _required_exact_value(values: Mapping[str, str], name: str) -> str:
    value = values.get(name, "")
    if not value or value.strip() != value:
        raise NarrationProductionRuntimeError(
            "TTS_PRODUCT_CONFIGURATION_INVALID",
            "narration production identity configuration is invalid",
        )
    return value


def _load_validation_token_digest(path: Path) -> bytes:
    """Load one private, non-linked token without returning or logging it."""

    descriptor: int | None = None
    try:
        if not path.is_absolute() or path.parent == path:
            raise NarrationProductionRuntimeError(
                "TTS_VALIDATION_TOKEN_INVALID",
                "hidden validation token path is invalid",
            )
        parent = path.parent.lstat()
        if (
            not stat.S_ISDIR(parent.st_mode)
            or stat.S_ISLNK(parent.st_mode)
            or parent.st_uid != os.geteuid()
            or stat.S_IMODE(parent.st_mode) != 0o700
        ):
            raise NarrationProductionRuntimeError(
                "TTS_VALIDATION_TOKEN_INVALID",
                "hidden validation token directory is invalid",
            )
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            raise NarrationProductionRuntimeError(
                "TTS_VALIDATION_TOKEN_INVALID",
                "hidden validation token policy is unavailable",
            )
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | nofollow,
        )
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or not 43 <= metadata.st_size <= 128
        ):
            raise NarrationProductionRuntimeError(
                "TTS_VALIDATION_TOKEN_INVALID",
                "hidden validation token file is invalid",
            )
        raw = os.read(descriptor, 129)
        try:
            token = raw.decode("ascii", errors="strict")
        except UnicodeDecodeError as error:
            raise NarrationProductionRuntimeError(
                "TTS_VALIDATION_TOKEN_INVALID",
                "hidden validation token is invalid",
            ) from error
        if len(raw) != metadata.st_size or _VALIDATION_TOKEN.fullmatch(token) is None:
            raise NarrationProductionRuntimeError(
                "TTS_VALIDATION_TOKEN_INVALID",
                "hidden validation token is invalid",
            )
        return hashlib.sha256(raw).digest()
    except NarrationProductionRuntimeError:
        raise
    except OSError as error:
        raise NarrationProductionRuntimeError(
            "TTS_VALIDATION_TOKEN_INVALID",
            "hidden validation token is unavailable",
        ) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _load_validation_runtime_scope(
    values: Mapping[str, str],
    *,
    now: datetime | None = None,
) -> ValidationRuntimeScope:
    """Parse one canonical, short-lived novel/document validation boundary."""

    current = datetime.now(timezone.utc) if now is None else now
    if current.tzinfo is None:
        raise NarrationProductionRuntimeError(
            "TTS_VALIDATION_SCOPE_INVALID",
            "hidden validation clock must be timezone-aware",
        )
    current = current.astimezone(timezone.utc)
    try:
        novel_raw = _required_exact_value(values, VALIDATION_NOVEL_ID_ENV)
        document_raw = _required_exact_value(values, VALIDATION_DOCUMENT_ID_ENV)
        novel_id = UUID(novel_raw)
        document_id = UUID(document_raw)
    except (ValueError, AttributeError) as error:
        raise NarrationProductionRuntimeError(
            "TTS_VALIDATION_SCOPE_INVALID",
            "hidden validation scope identity is invalid",
        ) from error
    if str(novel_id) != novel_raw or str(document_id) != document_raw:
        raise NarrationProductionRuntimeError(
            "TTS_VALIDATION_SCOPE_INVALID",
            "hidden validation scope identity is not canonical",
        )
    expiry_raw = _required_exact_value(values, VALIDATION_EXPIRES_AT_ENV)
    if _VALIDATION_EXPIRY.fullmatch(expiry_raw) is None:
        raise NarrationProductionRuntimeError(
            "TTS_VALIDATION_SCOPE_INVALID",
            "hidden validation expiry is invalid",
        )
    try:
        expires_at = datetime.strptime(
            expiry_raw,
            "%Y-%m-%dT%H:%M:%SZ",
        ).replace(tzinfo=timezone.utc)
    except ValueError as error:
        raise NarrationProductionRuntimeError(
            "TTS_VALIDATION_SCOPE_INVALID",
            "hidden validation expiry is invalid",
        ) from error
    if expires_at <= current or expires_at - current > MAX_VALIDATION_LIFETIME:
        raise NarrationProductionRuntimeError(
            "TTS_VALIDATION_SCOPE_INVALID",
            "hidden validation expiry is outside the bounded window",
        )
    return ValidationRuntimeScope(
        novel_id=novel_id,
        document_id=document_id,
        expires_at=expires_at,
    )


def _verify_validation_runtime_scope(
    engine: Engine,
    scope: ValidationRuntimeScope,
) -> None:
    """Require the dedicated target to be one chapter in the selected novel."""

    with Session(engine) as session:
        matched = session.scalar(
            select(Document.id).where(
                Document.id == scope.document_id,
                Document.novel_id == scope.novel_id,
                Document.kind == "chapter",
            )
        )
    if matched != scope.document_id:
        raise NarrationProductionRuntimeError(
            "TTS_VALIDATION_SCOPE_INVALID",
            "hidden validation target is not the dedicated chapter",
        )


def current_validation_runtime_scope() -> ValidationRuntimeScope | None:
    """Return an active scope without exposing token material or health details."""

    scope = _validation_runtime_scope
    return scope if scope is not None and scope.active() else None


def validation_route_token_authorized(value: str | None) -> bool:
    """Compare one header value against the in-memory hidden-run digest."""

    digest = _validation_token_digest
    if (
        current_validation_runtime_scope() is None
        or digest is None
        or type(value) is not str
        or _VALIDATION_TOKEN.fullmatch(value) is None
    ):
        return False
    return hmac.compare_digest(
        digest,
        hashlib.sha256(value.encode("ascii", errors="strict")).digest(),
    )


def _require_validation_claim_gate_scope(
    novel_id: UUID,
    document_id: UUID,
) -> ValidationRuntimeScope:
    scope = current_validation_runtime_scope()
    if (
        scope is None
        or type(novel_id) is not UUID
        or type(document_id) is not UUID
        or scope.novel_id != novel_id
        or scope.document_id != document_id
    ):
        raise NarrationProductionRuntimeError(
            "TTS_VALIDATION_CLAIM_GATE_SCOPE_INVALID",
            "validation claim gate scope is unavailable",
        )
    return scope


def arm_validation_segment_claim_gate(
    *,
    run_id: UUID,
    novel_id: UUID,
    document_id: UUID,
    ttl_seconds: int = 120,
    claim_limit: int = 1,
) -> ValidationSegmentClaimGateSnapshot:
    """Arm one exact hidden-run gate; no database or Manifest state is touched."""

    scope = _require_validation_claim_gate_scope(novel_id, document_id)
    return _validation_segment_claim_gate.arm(
        run_id=run_id,
        novel_id=novel_id,
        document_id=document_id,
        runtime_expires_at=scope.expires_at,
        ttl_seconds=ttl_seconds,
        claim_limit=claim_limit,
    )


def read_validation_segment_claim_gate(
    *,
    novel_id: UUID,
    document_id: UUID,
) -> ValidationSegmentClaimGateSnapshot:
    _require_validation_claim_gate_scope(novel_id, document_id)
    return _validation_segment_claim_gate.snapshot()


def release_validation_segment_claim_gate(
    *,
    run_id: UUID,
    novel_id: UUID,
    document_id: UUID,
) -> ValidationSegmentClaimGateSnapshot:
    _require_validation_claim_gate_scope(novel_id, document_id)
    return _validation_segment_claim_gate.release(
        run_id=run_id,
        novel_id=novel_id,
        document_id=document_id,
    )


def _storage_from_environment(values: Mapping[str, str]) -> NarrationStorage | None:
    model_value = values.get(MODEL_METADATA_ROOT_ENV, "")
    media_value = values.get(MEDIA_ROOT_ENV, "")
    if not model_value and not media_value:
        return None
    if not model_value or not media_value:
        raise NarrationProductionRuntimeError(
            "TTS_STORAGE_CONFIGURATION_INVALID",
            "narration storage roots are incomplete",
        )
    return NarrationStorage(
        models_root=_absolute_path(values, MODEL_METADATA_ROOT_ENV),
        media_root=_absolute_path(values, MEDIA_ROOT_ENV),
    )


def _verify_database(engine: Engine) -> None:
    with engine.connect() as connection:
        connection.execute(text("select 1"))
        revisions = tuple(
            str(value)
            for value in connection.scalars(
                text("select version_num from alembic_version")
            )
        )
    if revisions != (EXPECTED_DATABASE_REVISION,):
        raise NarrationProductionRuntimeError(
            "TTS_DATABASE_SCHEMA_OUTDATED",
            "narration production database schema is not at the frozen head",
        )


def _tokenizer_fingerprint(tts_fingerprint: str) -> str:
    return canonical_sha256(
        {
            "schema_version": TOKENIZER_FINGERPRINT_VERSION,
            "tts_model_fingerprint": tts_fingerprint,
            "component": "OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX",
        }
    )


def _normalizer_fingerprint() -> str:
    return canonical_sha256(
        {
            "schema_version": NORMALIZER_FINGERPRINT_VERSION,
            "unicode_normalization": "NFC",
            "context_mode": "independent_segment",
        }
    )


def _postprocess_fingerprint(policy: TranscodingPolicy) -> str:
    return transcoding_fingerprint(audio_processing_fingerprint(), policy)


def _production_job_promotion_allowed() -> bool:
    snapshot = _snapshot
    return (
        snapshot.lifecycle_status == "ready"
        and snapshot.production_backend_installed
        and snapshot.worker_running
    )


async def _wait_for_stop(stop_event: asyncio.Event, timeout_seconds: float) -> bool:
    if stop_event.is_set():
        return True
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=timeout_seconds)
    except TimeoutError:
        return False
    return True


async def _set_snapshot_if_current(
    task: asyncio.Task[None],
    snapshot: NarrationProductionRuntimeSnapshot,
) -> bool:
    global _snapshot
    async with _lifecycle_lock:
        if _runtime_task is not task:
            return False
        _snapshot = snapshot
        return True


async def _resolve_ready_sidecar(
    values: Mapping[str, str],
    stop_event: asyncio.Event,
    current_task: asyncio.Task[None],
) -> tuple[SidecarMossNanoTTSAdapter, ModelFingerprint] | None:
    """Re-resolve the technical adapter after startup races or lease loss."""

    while not stop_event.is_set():
        adapter = get_ready_narration_adapter()
        if adapter is not None:
            try:
                model = await adapter.model_fingerprint()
            except Exception as error:
                await _set_snapshot_if_current(
                    current_task,
                    NarrationProductionRuntimeSnapshot(
                        product_requested=True,
                        lifecycle_status="waiting_sidecar",
                        playback_installed=True,
                        digest_keyring_loaded=True,
                        reason_code=_safe_reason(
                            error,
                            "TTS_MODEL_IDENTITY_UNAVAILABLE",
                        ),
                    ),
                )
            else:
                if model is None:
                    model = getattr(adapter, "expected_model_fingerprint", None)
                if model is not None:
                    return adapter, model
        runtime = narration_runtime_status()
        if runtime.get("lifecycle_status") == "configuration_error":
            raise NarrationProductionRuntimeError(
                "TTS_SIDECAR_CONFIGURATION_INVALID",
                "private narration Sidecar configuration is invalid",
            )
        await launch_narration_runtime(values)
        try:
            await wait_narration_runtime_initialized(timeout_seconds=5.0)
        except TimeoutError:
            await _set_snapshot_if_current(
                current_task,
                NarrationProductionRuntimeSnapshot(
                    product_requested=True,
                    lifecycle_status="waiting_sidecar",
                    playback_installed=True,
                    digest_keyring_loaded=True,
                    reason_code="TTS_SIDECAR_STARTING",
                ),
            )
            continue
        adapter = get_ready_narration_adapter()
        if adapter is not None:
            try:
                model = await adapter.model_fingerprint()
            except Exception as error:
                await _set_snapshot_if_current(
                    current_task,
                    NarrationProductionRuntimeSnapshot(
                        product_requested=True,
                        lifecycle_status="waiting_sidecar",
                        playback_installed=True,
                        digest_keyring_loaded=True,
                        reason_code=_safe_reason(
                            error,
                            "TTS_MODEL_IDENTITY_UNAVAILABLE",
                        ),
                    ),
                )
            else:
                if model is None:
                    model = getattr(adapter, "expected_model_fingerprint", None)
                if model is not None:
                    return adapter, model
        runtime = narration_runtime_status()
        reason = runtime.get("reason_code")
        await _set_snapshot_if_current(
            current_task,
            NarrationProductionRuntimeSnapshot(
                product_requested=True,
                lifecycle_status="waiting_sidecar",
                playback_installed=True,
                digest_keyring_loaded=True,
                reason_code=(
                    reason
                    if isinstance(reason, str) and _SAFE_REASON.fullmatch(reason)
                    else "TTS_SIDECAR_NOT_READY"
                ),
            ),
        )
        if await _wait_for_stop(stop_event, SIDECAR_RETRY_SECONDS):
            return None
    return None


async def _run_worker_cycle(
    worker: NarrationSegmentWorker,
    adapter: SidecarMossNanoTTSAdapter,
    stop_event: asyncio.Event,
    *,
    scheduler: NarrationJobScheduler | None = None,
    voice_preview_processor: VoicePreviewProcessor | None = None,
) -> str:
    """Run one worker only while its exact leased adapter remains authoritative."""

    cycle_stop = asyncio.Event()
    if voice_preview_processor is None:
        worker_coroutine = worker.run_until_stopped(
            cycle_stop,
            on_error=lambda _error: None,
        )
    else:
        if scheduler is None:
            raise NarrationProductionRuntimeError(
                "TTS_WORKER_CONFIGURATION_INVALID",
                "voice preview dispatch requires the shared scheduler",
            )
        worker_coroutine = _run_shared_nano_worker(
            scheduler,
            worker,
            voice_preview_processor,
            cycle_stop,
        )
    worker_task = asyncio.create_task(worker_coroutine, name=WORKER_CYCLE_TASK_NAME)
    try:
        while not stop_event.is_set():
            if worker_task.done():
                await worker_task
                return "TTS_WORKER_STOPPED"
            if get_ready_narration_adapter() is not adapter:
                return "TTS_SIDECAR_LEASE_CHANGED"
            if await _wait_for_stop(stop_event, SIDECAR_RETRY_SECONDS):
                return "TTS_PRODUCTION_STOPPED"
        return "TTS_PRODUCTION_STOPPED"
    finally:
        cycle_stop.set()
        if not worker_task.done():
            try:
                await asyncio.wait_for(worker_task, timeout=5.0)
            except TimeoutError:
                worker_task.cancel()
                try:
                    await worker_task
                except asyncio.CancelledError:
                    pass


async def _run_shared_nano_worker(
    scheduler: NarrationJobScheduler,
    segment_worker: NarrationSegmentWorker,
    voice_preview_processor: VoicePreviewProcessor,
    stop_event: asyncio.Event,
    *,
    idle_poll_seconds: float = 1.0,
    maintenance_interval_seconds: float = 30.0,
) -> None:
    """Fairly dispatch both Nano job kinds through one single-concurrency loop."""

    loop = asyncio.get_running_loop()
    next_maintenance = 0.0
    while not stop_event.is_set():
        try:
            current = loop.time()
            if current >= next_maintenance:
                await asyncio.to_thread(scheduler.maintain_once)
                next_maintenance = current + maintenance_interval_seconds
            scheduled = await asyncio.to_thread(scheduler.claim_next_typed_job)
            if scheduled is None:
                wait_seconds = idle_poll_seconds
            elif scheduled.job_kind == "narration.segment_render":
                await segment_worker.process(scheduled.lease)
                wait_seconds = 0.0
            elif scheduled.job_kind == VOICE_PREVIEW_JOB_KIND:
                await voice_preview_processor.process(scheduled.lease)
                wait_seconds = 0.0
            else:
                raise NarrationProductionRuntimeError(
                    "TTS_WORKER_DISPATCH_INVALID",
                    "shared Nano scheduler returned an unsupported job kind",
                )
        except asyncio.CancelledError:
            raise
        except NarrationProductionRuntimeError:
            raise
        except Exception:
            # Preserve the existing bounded outage retry behavior. Persistent
            # leases and reconciliation remain the authority after recovery.
            wait_seconds = idle_poll_seconds
        if wait_seconds <= 0:
            await asyncio.sleep(0)
            continue
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=wait_seconds)
        except TimeoutError:
            pass


def _detach_production_factory(
    factory: NarrationProductionBackendFactory | None,
    voice_product: VoiceProductService | None = None,
) -> None:
    global _production_factory, _production_policy, _voice_product_port
    global _validation_token_digest, _validation_runtime_scope
    _validation_segment_claim_gate.clear()
    if factory is None:
        return
    try:
        uninstall_narration_production_backend_factory(factory)
    except RuntimeError:
        pass
    if _production_factory is factory:
        _production_factory = None
        _production_policy = None
        _validation_token_digest = None
        _validation_runtime_scope = None
    if voice_product is not None and _voice_product_port is voice_product:
        _voice_product_port = None


def current_narration_production_policy() -> NarrationProductionPolicy | None:
    """Return the exact policy of the currently installed production backend."""

    return _production_policy


def current_voice_product_port() -> VoiceProductService | None:
    """Return the exact reference-clone port for the current Sidecar lease."""

    return _voice_product_port


def current_narration_cache_runtime() -> NarrationCacheRuntime | None:
    """Return the installed read/status runtime; mutation remains capability-gated."""

    return _cache_runtime


def _resolve_current_voice_preview_media(
    session: Session,
    preview_id: UUID,
    asset_id: UUID,
) -> MediaAsset:
    if _voice_product_port is None:
        raise VoicePreviewNotFound("voice preview media is unavailable")
    return resolve_voice_preview_media(session, preview_id, asset_id)


async def _run_production(
    values: Mapping[str, str],
    storage: NarrationStorage,
    stop_event: asyncio.Event,
    *,
    reference_clone_enabled: bool,
    validation_enabled: bool,
) -> None:
    global _production_factory, _production_policy, _runtime_task, _snapshot
    global _voice_product_port, _disk_guard, _cache_runtime
    global _validation_token_digest, _validation_runtime_scope
    current_task = asyncio.current_task()
    if current_task is None:
        return
    installed_factory: NarrationProductionBackendFactory | None = None
    installed_voice_product: VoiceProductService | None = None
    keyring_loaded = False
    try:
        validation_token_digest = (
            await asyncio.to_thread(
                _load_validation_token_digest,
                _absolute_path(values, VALIDATION_TOKEN_FILE_ENV),
            )
            if validation_enabled
            else None
        )
        validation_scope = (
            _load_validation_runtime_scope(values) if validation_enabled else None
        )
        keyring_path = _absolute_path(values, DIGEST_KEYRING_FILE_ENV)
        keyring = await asyncio.to_thread(load_digest_keyring, keyring_path)
        keyring_loaded = True
        engine = get_engine()
        await asyncio.to_thread(_verify_database, engine)
        if validation_scope is not None:
            await asyncio.to_thread(
                _verify_validation_runtime_scope,
                engine,
                validation_scope,
            )
        ffmpeg_path = _absolute_path(values, FFMPEG_PATH_ENV)
        ffprobe_path = _absolute_path(values, FFPROBE_PATH_ENV)
        await asyncio.to_thread(
            validate_fixed_toolchain,
            ffmpeg_path=ffmpeg_path,
            ffprobe_path=ffprobe_path,
            expected_build_id=_required_exact_value(values, FFMPEG_BUILD_ID_ENV),
            policy=PRODUCTION_TRANSCODING_POLICY,
        )
        session_factory = sessionmaker(
            bind=engine,
            expire_on_commit=False,
        )
        disk_guard = NarrationDiskGuard(storage)
        await asyncio.to_thread(disk_guard.refresh)
        active_digest_key = keyring.active
        cache_runtime = SqlAlchemyNarrationCacheRuntime(
            session_factory=session_factory,
            storage=storage,
            cleanup_capability=wire.FeatureCapability(
                key=wire.CapabilityKey.CACHE_CLEANUP,
                state=wire.CapabilityState.ENABLED,
                visible=True,
                actionable=True,
                reason_code=None,
                required_gate=None,
            ),
            token_secret=hmac.new(
                active_digest_key.secret,
                b"narration-cache-token/1",
                hashlib.sha256,
            ).digest(),
            tombstone_digest_key_id=active_digest_key.key_id,
            tombstone_digest_key=hmac.new(
                active_digest_key.secret,
                b"narration-cache-tombstone/1",
                hashlib.sha256,
            ).digest(),
        )
        async with _lifecycle_lock:
            if _runtime_task is not current_task:
                return
            _disk_guard = disk_guard
            _cache_runtime = cache_runtime
        repository = SqlAlchemyNarrationWorkerRepository(
            session_factory,
            digest_keyring=keyring,
        )
        transcoder = FixedFfmpegTranscoder(
            ffmpeg_path=ffmpeg_path,
            ffprobe_path=ffprobe_path,
            policy=PRODUCTION_TRANSCODING_POLICY,
        )
        postprocess_fingerprint = _postprocess_fingerprint(
            PRODUCTION_TRANSCODING_POLICY
        )
        ffmpeg_build_id = _required_exact_value(values, FFMPEG_BUILD_ID_ENV)
        reference_policy = replace(
            DEFAULT_REFERENCE_NORMALIZATION_POLICY,
            ffmpeg_build_id=ffmpeg_build_id,
        )

        def normalize_reference(
            parsed: ParsedUploadedVoice,
        ) -> NormalizedReferenceAudio:
            return normalize_reference_audio(
                parsed.reference_audio,
                mime_type=parsed.mime_type,
                declared_sha256=parsed.checksum_sha256,
                ffmpeg_path=ffmpeg_path,
                ffprobe_path=ffprobe_path,
                expected_ffmpeg_build_id=ffmpeg_build_id,
                policy=reference_policy,
            )

        while not stop_event.is_set():
            resolved = await _resolve_ready_sidecar(values, stop_event, current_task)
            if resolved is None:
                return
            adapter, model = resolved
            tts_fingerprint = model_fingerprint_sha256(model)
            policy = NarrationProductionPolicy(
                tts_fingerprint=tts_fingerprint,
                tokenizer_fingerprint=_tokenizer_fingerprint(tts_fingerprint),
                normalizer_fingerprint=_normalizer_fingerprint(),
                postprocess_fingerprint=postprocess_fingerprint,
                digest_keyring=keyring,
            )
            preview_policy = VoicePreviewPolicy(
                expected_model_fingerprint=tts_fingerprint,
                requested_model_id=model.model_name,
                requested_revision=model.model_revision,
            )
            preview_repository = SqlAlchemyVoicePreviewRepository(
                session_factory,
                digest_keyring=keyring,
                policy=preview_policy,
            )
            scheduler = NarrationJobScheduler(
                session_factory,
                config=SchedulerConfig(
                    lease_owner="ai-novel-world-2026:narration-worker",
                    novel_ids=(
                        (validation_scope.novel_id,)
                        if validation_scope is not None
                        else None
                    ),
                    document_ids=(
                        (validation_scope.document_id,)
                        if validation_scope is not None
                        else None
                    ),
                    not_after=(
                        validation_scope.expires_at
                        if validation_scope is not None
                        else None
                    ),
                    job_kinds=("narration.segment_render", VOICE_PREVIEW_JOB_KIND),
                ),
                terminalizers={
                    "narration.segment_render": repository.terminalize_job_in_session,
                    VOICE_PREVIEW_JOB_KIND: preview_repository.terminalize_job_in_session,
                },
                claim_guard=disk_guard.claim_allowed,
                job_kind_claim_gate=(
                    _validation_segment_claim_gate.reserve
                    if validation_scope is not None
                    else None
                ),
            )
            worker = NarrationSegmentWorker(
                scheduler=scheduler,
                repository=repository,
                adapter=adapter,
                storage=storage,
                transcode=transcoder,
                config=NarrationWorkerConfig(
                    actor="narration-production-worker",
                ),
                disk_guard=disk_guard.require_available,
            )
            installed_voice_product = VoiceProductService(
                session_factory,
                storage=storage,
                normalize_reference=normalize_reference,
                digest_keyring=keyring,
                preview_policy=preview_policy,
            )
            voice_preview_processor = VoicePreviewProcessor(
                repository=preview_repository,
                adapter=adapter,
                storage=storage,
                policy=preview_policy,
            )
            installed_factory = build_narration_production_backend_factory(policy)
            install_narration_production_backend_factory(installed_factory)
            async with _lifecycle_lock:
                if _runtime_task is not current_task:
                    _detach_production_factory(installed_factory)
                    installed_factory = None
                    return
                _production_factory = installed_factory
                _production_policy = policy
                _voice_product_port = installed_voice_product
                _validation_token_digest = validation_token_digest
                _validation_runtime_scope = validation_scope
            ready = NarrationProductionRuntimeSnapshot(
                product_requested=True,
                lifecycle_status="ready",
                playback_installed=True,
                digest_keyring_loaded=True,
                production_backend_installed=True,
                worker_running=True,
                reference_clone_ready=(
                    reference_clone_enabled and installed_voice_product is not None
                ),
            )
            if not await _set_snapshot_if_current(current_task, ready):
                return
            try:
                cycle_reason = await _run_worker_cycle(
                    worker,
                    adapter,
                    stop_event,
                    scheduler=scheduler,
                    voice_preview_processor=voice_preview_processor,
                )
            except Exception as error:
                cycle_reason = _safe_reason(error, "TTS_WORKER_CYCLE_FAILED")
            _detach_production_factory(installed_factory, installed_voice_product)
            installed_factory = None
            installed_voice_product = None
            if stop_event.is_set():
                return
            await _set_snapshot_if_current(
                current_task,
                NarrationProductionRuntimeSnapshot(
                    product_requested=True,
                    lifecycle_status="reconnecting",
                    playback_installed=True,
                    digest_keyring_loaded=True,
                    reason_code=cycle_reason,
                ),
            )
            if await _wait_for_stop(stop_event, SIDECAR_RETRY_SECONDS):
                return
    except asyncio.CancelledError:
        raise
    except (
        DatabaseNotConfigured,
        DigestKeyringError,
        NarrationProductionRuntimeError,
        StorageError,
        OSError,
        RuntimeError,
        ValueError,
    ) as error:
        await _set_snapshot_if_current(
            current_task,
            NarrationProductionRuntimeSnapshot(
                product_requested=True,
                lifecycle_status="unavailable",
                playback_installed=True,
                digest_keyring_loaded=keyring_loaded,
                reason_code=_safe_reason(error, "TTS_PRODUCTION_START_FAILED"),
            ),
        )
    finally:
        _detach_production_factory(installed_factory, installed_voice_product)
        async with _lifecycle_lock:
            if _runtime_task is current_task:
                _disk_guard = None
                _cache_runtime = None
                _runtime_task = None
                if _snapshot.lifecycle_status == "ready":
                    _snapshot = NarrationProductionRuntimeSnapshot(
                        product_requested=True,
                        lifecycle_status="stopped",
                        playback_installed=_playback_factory is not None,
                        digest_keyring_loaded=keyring_loaded,
                    )


async def launch_narration_production_runtime(
    environ: Mapping[str, str] | None = None,
) -> None:
    """Install historical playback, then optionally start production in background."""

    global _playback_factory, _runtime_task, _stop_event, _snapshot
    values = dict(os.environ if environ is None else environ)
    async with _lifecycle_lock:
        if _runtime_task is not None or _playback_factory is not None:
            return
        try:
            product_requested = _exact_flag(values, PRODUCT_ENABLE_ENV)
            validation_requested = _exact_flag(values, VALIDATION_ENABLE_ENV)
            if product_requested and validation_requested:
                raise NarrationProductionRuntimeError(
                    "TTS_PRODUCT_CONFIGURATION_INVALID",
                    "product release and hidden validation modes are mutually exclusive",
                )
            requested = product_requested or validation_requested
            reference_clone_requested = _exact_flag(
                values,
                REFERENCE_CLONE_ENABLE_ENV,
            )
            if validation_requested and reference_clone_requested:
                raise NarrationProductionRuntimeError(
                    "TTS_PRODUCT_CONFIGURATION_INVALID",
                    "reference clone requires its own release gate and is forbidden "
                    "inside limited-core validation",
                )
            technical_enabled = _exact_flag(values, TECHNICAL_RUNTIME_ENABLE_ENV)
            if reference_clone_requested and not requested:
                raise NarrationProductionRuntimeError(
                    "TTS_PRODUCT_CONFIGURATION_INVALID",
                    "reference clone requires a released or hidden validation runtime",
                )
            storage = _storage_from_environment(values)
            if storage is None:
                if requested:
                    raise NarrationProductionRuntimeError(
                        "TTS_STORAGE_CONFIGURATION_INVALID",
                        "narration production requires configured storage roots",
                    )
                _snapshot = NarrationProductionRuntimeSnapshot()
                return
            playback_factory = build_playback_api_backend_factory(
                storage,
                can_promote_jobs=_production_job_promotion_allowed,
                resolve_voice_preview_media=_resolve_current_voice_preview_media,
            )
            install_playback_api_backend_factory(playback_factory)
            _playback_factory = playback_factory
            _snapshot = NarrationProductionRuntimeSnapshot(
                product_requested=requested,
                lifecycle_status=("playback_only" if not requested else "starting"),
                playback_installed=True,
            )
            if not requested:
                return
            if not technical_enabled:
                raise NarrationProductionRuntimeError(
                    "TTS_TECHNICAL_RUNTIME_DISABLED",
                    "narration production requires the private technical runtime",
                )
            stop_event = asyncio.Event()
            _stop_event = stop_event
            _runtime_task = asyncio.create_task(
                _run_production(
                    values,
                    storage,
                    stop_event,
                    reference_clone_enabled=reference_clone_requested,
                    validation_enabled=validation_requested,
                ),
                name=WORKER_TASK_NAME,
            )
        except (
            NarrationProductionRuntimeError,
            StorageError,
            OSError,
            RuntimeError,
            ValueError,
        ) as error:
            _snapshot = NarrationProductionRuntimeSnapshot(
                product_requested=(
                    values.get(PRODUCT_ENABLE_ENV) == "true"
                    or values.get(VALIDATION_ENABLE_ENV) == "true"
                ),
                lifecycle_status="configuration_error",
                playback_installed=_playback_factory is not None,
                reason_code=_safe_reason(error, "TTS_PRODUCT_CONFIGURATION_INVALID"),
            )


async def stop_narration_production_runtime() -> None:
    """Detach HTTP factories first, then stop the sole in-process worker."""

    global _playback_factory, _production_factory, _production_policy
    global _voice_product_port, _disk_guard, _cache_runtime
    global _validation_token_digest, _validation_runtime_scope
    global _runtime_task, _stop_event, _snapshot
    _validation_segment_claim_gate.clear()
    async with _lifecycle_lock:
        task = _runtime_task
        stop_event = _stop_event
        playback_factory = _playback_factory
        production_factory = _production_factory
        _runtime_task = None
        _stop_event = None
        _playback_factory = None
        _production_factory = None
        _production_policy = None
        _voice_product_port = None
        _disk_guard = None
        _cache_runtime = None
        _validation_token_digest = None
        _validation_runtime_scope = None
        _snapshot = NarrationProductionRuntimeSnapshot(lifecycle_status="stopping")
    if production_factory is not None:
        try:
            uninstall_narration_production_backend_factory(production_factory)
        except RuntimeError:
            pass
    if stop_event is not None:
        stop_event.set()
    if task is not None and task is not asyncio.current_task():
        try:
            await asyncio.wait_for(task, timeout=5.0)
        except TimeoutError:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        except asyncio.CancelledError:
            pass
    if playback_factory is not None:
        try:
            uninstall_playback_api_backend_factory(playback_factory)
        except RuntimeError:
            pass
    async with _lifecycle_lock:
        _snapshot = NarrationProductionRuntimeSnapshot()


__all__ = [
    "DIGEST_KEYRING_FILE_ENV",
    "FFMPEG_PATH_ENV",
    "FFPROBE_PATH_ENV",
    "FFMPEG_BUILD_ID_ENV",
    "EXPECTED_DATABASE_REVISION",
    "MEDIA_ROOT_ENV",
    "MODEL_METADATA_ROOT_ENV",
    "NarrationProductionRuntimeSnapshot",
    "PRODUCT_ENABLE_ENV",
    "VALIDATION_ENABLE_ENV",
    "VALIDATION_DOCUMENT_ID_ENV",
    "VALIDATION_EXPIRES_AT_ENV",
    "VALIDATION_NOVEL_ID_ENV",
    "VALIDATION_TOKEN_FILE_ENV",
    "ValidationRuntimeScope",
    "ValidationSegmentClaimGate",
    "ValidationSegmentClaimGateSnapshot",
    "arm_validation_segment_claim_gate",
    "current_validation_runtime_scope",
    "REFERENCE_CLONE_ENABLE_ENV",
    "PRODUCTION_TRANSCODING_POLICY",
    "WORKER_TASK_NAME",
    "WORKER_CYCLE_TASK_NAME",
    "current_voice_product_port",
    "current_narration_cache_runtime",
    "current_narration_production_policy",
    "launch_narration_production_runtime",
    "narration_production_runtime_status",
    "read_validation_segment_claim_gate",
    "release_validation_segment_claim_gate",
    "stop_narration_production_runtime",
    "validation_route_token_authorized",
]
