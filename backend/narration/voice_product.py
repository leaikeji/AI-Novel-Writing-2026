"""Product-grade uploaded voices and real Nano preview orchestration.

The module keeps the three expensive boundaries -- FFmpeg normalization,
immutable media publication, and Sidecar inference -- outside database
transactions.  Database phases are deliberately short and persist enough
identity/state evidence for cross-process idempotency and crash recovery.

No function logs or returns reference bytes or private preview text.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
import re
from typing import Callable, Final, Literal, Protocol, TypeVar
import unicodedata
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session

from ..models import (
    ActiveJobAsset,
    BackgroundJob,
    BackgroundJobAttempt,
    MediaAsset,
    ModelRunRecord,
    VoiceActionReceipt,
    VoicePreview,
    VoiceProfile,
    VoiceProfileVersion,
    VoiceReferenceAssetLink,
    VoiceRightsEvent,
    VoiceRightsRecord,
)
from . import schemas as wire
from .adapters import (
    MOSS_NANO_SIDECAR_CONTRACT_CAPABILITIES,
    AdapterUnavailableError,
    MossNanoTTSAdapter,
)
from .audio_pipeline import (
    AudioFormatError,
    AudioPipelineError,
    AudioQualityError,
    ProcessedPcmWav,
    process_synthesis_wav,
)
from .contracts import (
    NarrationRequestScope,
    PRODUCTION_NANO_MAX_NEW_FRAMES,
    PRODUCTION_NANO_MAX_SEED,
    PRODUCTION_NANO_SAMPLE_MODES,
    ReferenceAudioInput,
    SynthesisRequest,
    SynthesisResult,
)
from .digest_keyring import (
    DigestKeyring,
    historical_private_text_digest,
    private_text_digest,
)
from .fingerprints import model_fingerprint_sha256
from .jobs import (
    FailureResult,
    JobFenceError,
    JobLease,
    acknowledge_cancel,
    complete_attempt,
    enqueue_job,
    fail_attempt,
    heartbeat_attempt,
    lock_result_publish_fences,
)
from .official_presets import (
    OFFICIAL_PRESET_DECODE_PARAMETERS_SCHEMA_VERSION,
    OFFICIAL_PRESET_MAX_NEW_FRAMES,
    OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256,
    OFFICIAL_PRESET_REPOSITORY,
    OFFICIAL_PRESET_REVISION,
    OFFICIAL_PRESET_RUNTIME_INITIAL_SEED,
    OFFICIAL_PRESET_SAMPLE_MODE,
    OFFICIAL_PRESET_VERSION_SCHEMA_VERSION,
    OfficialPreset,
    official_preset_decode_parameters_fingerprint,
    official_preset_version_fingerprint,
    require_official_preset,
    validate_official_preset_provenance,
)
from .media import release_active_job_assets_in_session
from .runtime import canonical_sidecar_synthesis_metadata
from .services import (
    IdempotencyConflict,
    InvalidNarrationState,
    NarrationCasConflict,
    NarrationNotFound,
    NarrationScopeMismatch,
    NarrationServiceError,
    SqlAlchemyNarrationStore,
    VoiceRightsUnavailable,
    canonical_sha256,
)
from .storage import (
    NarrationStorage,
    PublicationValidationError,
    PublishedFile,
    StorageError,
    StorageRootChanged,
    TargetCollision,
    UnsafeStoragePath,
)
from .voice_media import (
    NormalizedReferenceAudio,
    ReferenceAudioInvalid,
    ReferenceAudioQualityRejected,
    ReferenceToolchainUnavailable,
)
from .voices import (
    ParsedUploadedVoice,
    VoiceProfileCreationReceipt,
    VoiceProfileNotFound,
    VoiceUploadValidationError,
    VoiceVersionNotFound,
    voice_profile_resource,
)


VOICE_UPLOAD_OPERATION: Final = "create_uploaded_voice_version"
VOICE_PRESET_OPERATION: Final = "create_official_preset_voice_version"
VOICE_PREVIEW_OPERATION: Final = "create_voice_preview"
VOICE_PROFILE_CREATE_OPERATION: Final = "create_voice_profile"
VOICE_LOCK_OPERATION: Final = "lock_voice_profile"
VOICE_PREVIEW_JOB_KIND: Final = "narration.voice_preview"
VOICE_PREVIEW_RESOURCE_CLASS: Final = "moss-nano"
VOICE_PREVIEW_INPUT_PURPOSE: Final = "moss-nano-voice-preview"
VOICE_PREVIEW_TEXT_PURPOSE: Final = "voice-preview"
VOICE_PRODUCT_SCHEMA_VERSION: Final = OFFICIAL_PRESET_DECODE_PARAMETERS_SCHEMA_VERSION
MAX_PREVIEW_MEDIA_BYTES: Final = 16 * 1024 * 1024

_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_T = TypeVar("_T")


class VoiceProductError(NarrationServiceError):
    """Base error with no private media/text material in its message."""


class VoicePreviewNotFound(NarrationNotFound):
    pass


class VoiceProductSecurityError(VoiceProductError):
    pass


class VoiceProductContractError(VoiceProductError):
    pass


SessionFactory = Callable[[], Session]
ReferenceNormalizer = Callable[[ParsedUploadedVoice], NormalizedReferenceAudio]


@dataclass(frozen=True, slots=True)
class VoicePreviewPolicy:
    expected_model_fingerprint: str
    requested_provider_id: str | None = "local-sidecar"
    requested_model_id: str = "OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX"
    requested_revision: str | None = None
    actor: str = "local-owner"
    voice_key: str = "uploaded-reference"
    seed: int = OFFICIAL_PRESET_RUNTIME_INITIAL_SEED
    sample_mode: str = OFFICIAL_PRESET_SAMPLE_MODE
    max_new_frames: int = OFFICIAL_PRESET_MAX_NEW_FRAMES
    preview_ttl_seconds: int = 24 * 60 * 60
    heartbeat_seconds: float = 30.0
    max_reference_bytes: int = 4 * 1024 * 1024

    def validate(self) -> None:
        if _SHA256.fullmatch(self.expected_model_fingerprint) is None:
            raise ValueError("voice preview expected model fingerprint is invalid")
        for value, label, maximum in (
            (self.requested_model_id, "requested model", 160),
            (self.actor, "actor", 120),
            (self.voice_key, "voice key", 160),
            (self.sample_mode, "sample mode", 80),
        ):
            if (
                type(value) is not str
                or not value
                or value != value.strip()
                or len(value) > maximum
            ):
                raise ValueError(f"voice preview {label} is invalid")
        for optional, label in (
            (self.requested_provider_id, "requested provider"),
            (self.requested_revision, "requested revision"),
        ):
            if optional is not None and (
                type(optional) is not str
                or not optional
                or optional != optional.strip()
                or len(optional) > 160
            ):
                raise ValueError(f"voice preview {label} is invalid")
        if type(self.seed) is not int or not 0 <= self.seed <= PRODUCTION_NANO_MAX_SEED:
            raise ValueError("voice preview seed is outside the Nano runtime bound")
        if self.sample_mode not in PRODUCTION_NANO_SAMPLE_MODES:
            raise ValueError("voice preview sample mode is unsupported by Nano")
        if (
            type(self.max_new_frames) is not int
            or not 1 <= self.max_new_frames <= PRODUCTION_NANO_MAX_NEW_FRAMES
        ):
            raise ValueError("voice preview frame bound is invalid")
        if type(self.preview_ttl_seconds) is not int or not 60 <= self.preview_ttl_seconds <= 7 * 86_400:
            raise ValueError("voice preview expiry is invalid")
        if not isinstance(self.heartbeat_seconds, (int, float)) or not 0.01 <= float(self.heartbeat_seconds) <= 1_800:
            raise ValueError("voice preview heartbeat is invalid")
        if type(self.max_reference_bytes) is not int or not 1 <= self.max_reference_bytes <= 16 * 1024 * 1024:
            raise ValueError("voice preview reference bound is invalid")

    @property
    def parameters_fingerprint(self) -> str:
        return self.parameters_fingerprint_for(self.voice_key)

    def parameters_fingerprint_for(self, voice: str) -> str:
        return canonical_sha256(
            {
                "schema_version": VOICE_PRODUCT_SCHEMA_VERSION,
                "sample_mode": self.sample_mode,
                "max_new_frames": self.max_new_frames,
                "seed": self.seed,
                "voice_key": voice,
            }
        )

    def parameters_fingerprint_for_version(
        self,
        version: VoiceProfileVersion,
        voice: str,
    ) -> str:
        seed, sample_mode, max_new_frames = _version_decode_parameters(version)
        return canonical_sha256(
            {
                "schema_version": VOICE_PRODUCT_SCHEMA_VERSION,
                "sample_mode": sample_mode,
                "max_new_frames": max_new_frames,
                "seed": seed,
                "voice_key": voice,
            }
        )


def _version_decode_parameters(
    version: VoiceProfileVersion,
) -> tuple[int, str, int]:
    """Resolve the immutable decode inputs shared by preview and chapters.

    Legacy uploaded versions predate explicit mode/frame fields.  They were
    created only under the frozen fixed/375 defaults, so those exact values
    remain their compatibility interpretation instead of following mutable
    process defaults.
    """

    if type(version) is not VoiceProfileVersion:
        raise VoiceProductSecurityError("voice decode version is invalid")
    parameters = version.parameters_json
    if type(parameters) is not dict:
        raise VoiceProductSecurityError("voice decode parameters are malformed")
    seed = version.seed
    sample_mode = parameters.get("sample_mode", "fixed")
    max_new_frames = parameters.get(
        "max_new_frames", PRODUCTION_NANO_MAX_NEW_FRAMES
    )
    if type(seed) is not int or not 0 <= seed <= PRODUCTION_NANO_MAX_SEED:
        raise VoiceProductSecurityError("voice decode seed is outside the Nano bound")
    if type(sample_mode) is not str or sample_mode not in PRODUCTION_NANO_SAMPLE_MODES:
        raise VoiceProductSecurityError("voice decode sample mode is invalid")
    if (
        type(max_new_frames) is not int
        or not 1 <= max_new_frames <= PRODUCTION_NANO_MAX_NEW_FRAMES
    ):
        raise VoiceProductSecurityError("voice decode frame bound is invalid")
    return seed, sample_mode, max_new_frames


@dataclass(frozen=True, slots=True)
class _ReceiptReservation:
    row_id: UUID
    resource_id: UUID
    state: Literal["reserved", "completed"]
    replay: bool


@dataclass(frozen=True, slots=True)
class _UploadReservation:
    version_id: UUID
    source_asset_id: UUID
    reference_asset_id: UUID
    rights_record_id: UUID
    link_id: UUID
    event_id: UUID
    completed: bool


@dataclass(frozen=True, slots=True)
class VoiceReferenceMedia:
    relative_path: str = field(repr=False)
    actual_sha256: str
    byte_size: int
    content_type: str


@dataclass(frozen=True, slots=True)
class VoicePreviewWorkItem:
    lease: JobLease
    preview_id: UUID
    profile_id: UUID
    version_id: UUID
    rights_record_id: UUID
    novel_id: UUID | None
    text: str = field(repr=False)
    voice: str
    seed: int
    sample_mode: str
    max_new_frames: int
    expected_model_fingerprint: str
    reference_fingerprint: str
    parameters_fingerprint: str
    input_digest_key_id: str
    input_digest: str
    reference: VoiceReferenceMedia | None = field(repr=False)


@dataclass(frozen=True, slots=True)
class PreparedVoicePreview:
    published: PublishedFile
    duration_ms: int
    sample_rate_hz: int
    channels: int
    audio_validation: dict[str, object]
    requested_provider_id: str | None
    requested_model_id: str
    requested_revision: str | None
    actual_provider_id: str | None
    actual_model_id: str
    actual_revision: str
    model_fingerprint: str
    parameters_digest: str
    input_digest_key_id: str
    input_digest: str
    output_digest: str
    provider_request_id: str


@dataclass(frozen=True, slots=True)
class VoicePreviewWorkerOutcome:
    status: Literal[
        "succeeded",
        "cancelled",
        "retry_wait",
        "failed",
        "dead_letter",
        "stale",
    ]
    job_id: UUID
    preview_id: UUID | None = None
    error_code: str | None = None


class VoicePreviewRepository(Protocol):
    def load_and_mark_running(self, lease: JobLease) -> VoicePreviewWorkItem: ...

    def read_job_state(self, lease: JobLease) -> str: ...

    def heartbeat_and_read_state(self, lease: JobLease) -> str: ...

    def publish(self, work: VoicePreviewWorkItem, prepared: PreparedVoicePreview) -> None: ...

    def fail(
        self,
        work: VoicePreviewWorkItem,
        *,
        classification: Literal["retryable", "non_retryable", "security_failure"],
        error_code: str,
    ) -> FailureResult: ...

    def fail_claim(
        self,
        lease: JobLease,
        *,
        classification: Literal["retryable", "non_retryable", "security_failure"],
        error_code: str,
    ) -> FailureResult: ...

    def acknowledge_cancel(self, work: VoicePreviewWorkItem) -> None: ...


def _stable_uuid(operation: str, key: str) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        (
            "ai-novel-world-2026/narration/voice-product/"
            f"{NarrationRequestScope.fixed_local().owner_id}/"
            f"{NarrationRequestScope.fixed_local().workspace_id}/{operation}/{key}"
        ),
    )


def _child_uuid(parent: UUID, label: str) -> UUID:
    return uuid5(parent, f"{VOICE_PRODUCT_SCHEMA_VERSION}/{label}")


def _canonical_asset_path(asset_id: UUID, digest: str, extension: str) -> str:
    return f"assets/{asset_id.hex[:2]}/{asset_id.hex}/{digest}.{extension}"


def _json_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _db_now(session: Session) -> datetime:
    bind = session.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        value = session.scalar(select(func.clock_timestamp()))
        if not isinstance(value, datetime):
            raise InvalidNarrationState("database clock did not return a timestamp")
        return value
    return datetime.now(UTC)


def _transaction(factory: SessionFactory, operation: Callable[[Session], _T]) -> _T:
    with factory() as session:
        with session.begin():
            return operation(session)


def _assert_receipt(
    row: VoiceActionReceipt,
    *,
    operation: str,
    idempotency_key: str,
    request_hash: str,
    resource_id: UUID,
) -> None:
    scope = NarrationRequestScope.fixed_local()
    if (
        row.owner_id != scope.owner_id
        or row.workspace_id != scope.workspace_id
        or row.operation != operation
        or row.idempotency_key != idempotency_key
        or row.resource_id != resource_id
    ):
        raise InvalidNarrationState("voice action receipt identity is inconsistent")
    if row.request_hash != request_hash:
        raise IdempotencyConflict("voice action key already names another request")
    if row.state not in {"reserved", "completed"}:
        raise InvalidNarrationState("voice action receipt state is invalid")
    if (row.state == "completed") != (row.completed_at is not None):
        raise InvalidNarrationState("voice action receipt lifecycle is inconsistent")


def _reserve_receipt(
    session: Session,
    *,
    operation: str,
    idempotency_key: str,
    request_hash: str,
    resource_id: UUID,
) -> _ReceiptReservation:
    scope = NarrationRequestScope.fixed_local()
    receipt_id = _child_uuid(resource_id, f"receipt:{operation}")
    created = False
    if session.get_bind().dialect.name == "postgresql":
        statement = (
            postgresql_insert(VoiceActionReceipt.__table__)
            .values(
                id=receipt_id,
                owner_id=scope.owner_id,
                workspace_id=scope.workspace_id,
                operation=operation,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                resource_id=resource_id,
                state="reserved",
                reserved_at=func.clock_timestamp(),
                completed_at=None,
            )
            .on_conflict_do_nothing()
            .returning(VoiceActionReceipt.id)
        )
        created = session.scalar(statement) == receipt_id
    else:
        existing = session.scalar(
            select(VoiceActionReceipt).where(
                VoiceActionReceipt.owner_id == scope.owner_id,
                VoiceActionReceipt.workspace_id == scope.workspace_id,
                VoiceActionReceipt.operation == operation,
                VoiceActionReceipt.idempotency_key == idempotency_key,
            )
        )
        if existing is None:
            session.add(
                VoiceActionReceipt(
                    id=receipt_id,
                    owner_id=scope.owner_id,
                    workspace_id=scope.workspace_id,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                    resource_id=resource_id,
                    state="reserved",
                    reserved_at=_db_now(session),
                    completed_at=None,
                )
            )
            session.flush()
            created = True
    row = session.scalar(
        select(VoiceActionReceipt)
        .where(
            VoiceActionReceipt.owner_id == scope.owner_id,
            VoiceActionReceipt.workspace_id == scope.workspace_id,
            VoiceActionReceipt.operation == operation,
            VoiceActionReceipt.idempotency_key == idempotency_key,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        collision = session.scalar(
            select(VoiceActionReceipt)
            .where(
                VoiceActionReceipt.owner_id == scope.owner_id,
                VoiceActionReceipt.workspace_id == scope.workspace_id,
                VoiceActionReceipt.operation == operation,
                VoiceActionReceipt.resource_id == resource_id,
            )
            .with_for_update()
        )
        if collision is not None:
            raise IdempotencyConflict("voice action resource already has another key")
        raise InvalidNarrationState("voice action receipt reservation disappeared")
    _assert_receipt(
        row,
        operation=operation,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        resource_id=resource_id,
    )
    return _ReceiptReservation(
        row_id=row.id,
        resource_id=row.resource_id,
        state=row.state,  # type: ignore[arg-type]
        replay=not created,
    )


def _complete_receipt(session: Session, row_id: UUID, *, at: datetime) -> None:
    row = session.scalar(
        select(VoiceActionReceipt)
        .where(VoiceActionReceipt.id == row_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise InvalidNarrationState("voice action receipt disappeared before completion")
    if row.state == "completed":
        return
    if row.state != "reserved" or row.completed_at is not None:
        raise InvalidNarrationState("voice action receipt cannot be completed")
    if not isinstance(row.reserved_at, datetime):
        raise InvalidNarrationState("voice action receipt reservation time is invalid")
    row.state = "completed"
    # PostgreSQL uses clock_timestamp() for the INSERT default.  Some callers
    # capture their operation timestamp before reserving the receipt, so that
    # value can be a few milliseconds earlier than reserved_at and violate the
    # lifecycle CHECK.  Preserve the caller's timestamp when legal and clamp
    # only the impossible backwards edge.
    row.completed_at = max(at, row.reserved_at)


class SqlAlchemyVoiceActionReceiptPort:
    """Request-transaction adapter for ``create_voice_profile``."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._reserved_by_profile: dict[UUID, UUID] = {}

    def reserve(
        self,
        *,
        idempotency_key: str,
        payload_sha256: str,
        profile_id: UUID,
    ) -> VoiceProfileCreationReceipt:
        reservation = _reserve_receipt(
            self._session,
            operation=VOICE_PROFILE_CREATE_OPERATION,
            idempotency_key=idempotency_key,
            request_hash=payload_sha256,
            resource_id=profile_id,
        )
        self._reserved_by_profile[profile_id] = reservation.row_id
        return VoiceProfileCreationReceipt(
            profile_id=profile_id,
            payload_sha256=payload_sha256,
            replay=reservation.replay,
        )

    def complete(self, *, profile_id: UUID) -> None:
        receipt_id = self._reserved_by_profile.get(profile_id)
        if receipt_id is None:
            raise InvalidNarrationState("profile receipt was not reserved in this transaction")
        _complete_receipt(self._session, receipt_id, at=_db_now(self._session))


def _published_or_adopted(
    storage: NarrationStorage,
    payload: bytes,
    *,
    asset_id: UUID,
    digest: str,
    extension: str,
    max_bytes: int,
) -> PublishedFile:
    expected_path = _canonical_asset_path(asset_id, digest, extension)
    try:
        published = storage.publish_media(
            (payload,),
            asset_id=asset_id,
            expected_sha256=digest,
            expected_size=len(payload),
            extension=extension,
            max_bytes=max_bytes,
        )
    except TargetCollision:
        published = storage.verify_existing_media(
            expected_path,
            expected_sha256=digest,
            expected_size=len(payload),
            max_bytes=max_bytes,
        )
    if (
        published.asset_id != asset_id
        or published.relative_path != expected_path
        or published.actual_sha256 != digest
        or published.byte_size != len(payload)
    ):
        raise VoiceProductSecurityError("published voice media identity is inconsistent")
    return published


def _required_profile(session: Session, profile_id: UUID, *, for_update: bool) -> VoiceProfile:
    statement = select(VoiceProfile).where(VoiceProfile.id == profile_id)
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    profile = session.scalar(statement)
    scope = NarrationRequestScope.fixed_local()
    if profile is None:
        raise VoiceProfileNotFound("voice profile not found")
    if profile.owner_id != scope.owner_id or profile.workspace_id != scope.workspace_id:
        raise NarrationScopeMismatch("voice profile is outside fixed local scope")
    return profile


def _required_version(
    session: Session,
    profile_id: UUID,
    version_id: UUID,
    *,
    for_update: bool,
) -> VoiceProfileVersion:
    statement = select(VoiceProfileVersion).where(VoiceProfileVersion.id == version_id)
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    version = session.scalar(statement)
    scope = NarrationRequestScope.fixed_local()
    if version is None:
        raise VoiceVersionNotFound("voice version not found")
    if (
        version.profile_id != profile_id
        or version.owner_id != scope.owner_id
        or version.workspace_id != scope.workspace_id
    ):
        raise NarrationScopeMismatch("voice version belongs to another profile or scope")
    return version


def _required_active_rights(
    session: Session,
    profile: VoiceProfile,
    version: VoiceProfileVersion,
    *,
    at: datetime,
    for_update: bool,
) -> VoiceRightsRecord:
    statement = select(VoiceRightsRecord).where(
        VoiceRightsRecord.id == version.rights_record_id
    )
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    rights = session.scalar(statement)
    if rights is None:
        raise VoiceRightsUnavailable("voice rights record is absent")
    if (
        rights.owner_id != profile.owner_id
        or rights.workspace_id != profile.workspace_id
        or rights.novel_id != profile.novel_id
    ):
        raise NarrationScopeMismatch("voice rights are outside the profile scope")
    if profile.status in {"archived", "unavailable"} or version.state in {"unavailable", "deleted"}:
        raise VoiceRightsUnavailable("voice profile or version is unavailable")
    if rights.expires_at is not None and rights.expires_at <= at:
        raise VoiceRightsUnavailable("voice rights expired")
    events_statement = select(VoiceRightsEvent).where(
        VoiceRightsEvent.rights_record_id == rights.id
    ).order_by(VoiceRightsEvent.occurred_at, VoiceRightsEvent.id)
    if for_update:
        events_statement = events_statement.with_for_update().execution_options(populate_existing=True)
    events = list(session.scalars(events_statement))
    if not any(event.event_type == "confirmed" for event in events) or any(
        event.event_type in {"revoked", "expired", "review_blocked"}
        for event in events
    ):
        raise VoiceRightsUnavailable("voice rights lack active confirmation evidence")
    if version.source_type == "uploaded" and not rights.voice_cloning:
        raise VoiceRightsUnavailable("uploaded voice lacks cloning permission")
    return rights


def _required_reference_link(
    session: Session,
    version: VoiceProfileVersion,
    *,
    for_update: bool,
) -> VoiceReferenceAssetLink:
    statement = select(VoiceReferenceAssetLink).where(
        VoiceReferenceAssetLink.voice_version_id == version.id
    )
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    link = session.scalar(statement)
    if link is None:
        raise InvalidNarrationState("uploaded voice has no reference provenance link")
    if (
        link.profile_id != version.profile_id
        or link.rights_record_id != version.rights_record_id
        or link.reference_asset_id != version.reference_asset_id
    ):
        raise VoiceProductSecurityError("voice reference provenance is inconsistent")
    return link


def _required_reference_asset(
    session: Session,
    profile: VoiceProfile,
    version: VoiceProfileVersion,
    link: VoiceReferenceAssetLink,
    *,
    for_update: bool,
) -> MediaAsset:
    statement = select(MediaAsset).where(MediaAsset.id == link.reference_asset_id)
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    asset = session.scalar(statement)
    if asset is None:
        raise InvalidNarrationState("voice reference asset is absent")
    if (
        asset.owner_id != profile.owner_id
        or asset.workspace_id != profile.workspace_id
        or asset.novel_id != profile.novel_id
        or asset.asset_class != "voice_reference"
        or asset.state != "ready"
        or asset.retention_policy != "locked_voice"
        or asset.mime_type != "audio/wav"
        or asset.checksum_algorithm != "sha256"
        or asset.byte_size is None
        or asset.byte_size <= 0
        or asset.duration_ms is None
        or asset.duration_ms <= 0
        or asset.sample_rate != 48_000
        or asset.channels != 2
        or asset.verified_at is None
        or _SHA256.fullmatch(asset.content_hash) is None
        or asset.storage_path
        != _canonical_asset_path(asset.id, asset.content_hash, "wav")
    ):
        raise VoiceProductSecurityError("voice reference asset is not authoritative")
    return asset


def _reference_fingerprint(
    version: VoiceProfileVersion,
    link: VoiceReferenceAssetLink,
    asset: MediaAsset,
) -> str:
    return canonical_sha256(
        {
            "schema_version": VOICE_PRODUCT_SCHEMA_VERSION,
            "version_id": str(version.id),
            "voice_fingerprint": version.fingerprint,
            "reference_asset_id": str(asset.id),
            "reference_sha256": asset.content_hash,
            "normalization_fingerprint": link.normalization_fingerprint,
            "validation_fingerprint": link.validation_fingerprint,
        }
    )


def _required_official_preset(
    version: VoiceProfileVersion,
    rights: VoiceRightsRecord,
    *,
    expected_model_fingerprint: str,
) -> OfficialPreset:
    """Verify an official version only by its pinned manifest identity."""

    if (
        version.source_type != "preset"
        or rights.source_kind != "official_preset"
        or version.reference_asset_id is not None
        or version.provider_id != "local-sidecar"
        or version.model_id != OFFICIAL_PRESET_REPOSITORY
        or version.model_revision != OFFICIAL_PRESET_REVISION
        or version.preset_key is None
        or expected_model_fingerprint != OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256
    ):
        raise VoiceProductSecurityError("official preset runtime identity changed")
    parameters = version.parameters_json
    if type(parameters) is not dict or parameters.get(
        "schema_version"
    ) != OFFICIAL_PRESET_VERSION_SCHEMA_VERSION:
        raise VoiceProductSecurityError("official preset version parameters are malformed")
    allowed = {
        "schema_version",
        "official_preset",
        "sample_mode",
        "max_new_frames",
    }
    if set(parameters) - allowed:
        raise VoiceProductSecurityError("official preset version has unknown parameters")
    try:
        preset = validate_official_preset_provenance(parameters.get("official_preset"))
    except ValueError as error:
        raise VoiceProductSecurityError(
            "official preset provenance disagrees with pinned manifest"
        ) from error
    if preset.preset_id != version.preset_key:
        raise VoiceProductSecurityError("official preset ID mapping changed")
    if (
        version.seed != OFFICIAL_PRESET_RUNTIME_INITIAL_SEED
        or parameters.get("sample_mode") != OFFICIAL_PRESET_SAMPLE_MODE
        or parameters.get("max_new_frames")
        != OFFICIAL_PRESET_MAX_NEW_FRAMES
    ):
        raise VoiceProductSecurityError(
            "official preset decode parameters differ from the pinned runtime"
        )
    return preset


class VoiceProductService:
    """Production port installed behind ``VoiceSettingsHandler``.

    The service owns its own short transactions.  Integration must not wrap
    these commands in the settings facade's generic request transaction.
    """

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        storage: NarrationStorage,
        normalize_reference: ReferenceNormalizer,
        digest_keyring: DigestKeyring,
        preview_policy: VoicePreviewPolicy,
    ) -> None:
        if not callable(session_factory) or not callable(normalize_reference):
            raise TypeError("voice product requires session and normalization factories")
        if not hasattr(storage, "publish_media") or not hasattr(
            storage, "verify_existing_media"
        ):
            raise TypeError("voice product requires immutable narration storage")
        if type(digest_keyring) is not DigestKeyring:
            raise TypeError("voice product requires a digest keyring")
        preview_policy.validate()
        self._session_factory = session_factory
        self._storage = storage
        self._normalize_reference = normalize_reference
        self._digest_keyring = digest_keyring
        self._preview_policy = preview_policy

    def create_preset_version(
        self,
        *,
        profile_id: UUID,
        request: wire.CreatePresetVoiceVersionRequest,
        idempotency_key: str,
    ) -> wire.VoiceProfileVersionResource:
        """Create one immutable official preset version without media upload."""

        if (
            self._preview_policy.expected_model_fingerprint
            != OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256
        ):
            raise VoiceProductSecurityError(
                "official preset catalog does not match the active Nano model"
            )
        try:
            preset = require_official_preset(request.preset_id)
        except ValueError as error:
            raise VoiceProductContractError("unknown official ONNX preset_id") from error
        if (
            self._preview_policy.seed,
            self._preview_policy.sample_mode,
            self._preview_policy.max_new_frames,
        ) != (
            OFFICIAL_PRESET_RUNTIME_INITIAL_SEED,
            OFFICIAL_PRESET_SAMPLE_MODE,
            OFFICIAL_PRESET_MAX_NEW_FRAMES,
        ):
            raise VoiceProductSecurityError(
                "official preset decode parameters differ from the pinned runtime"
            )
        decode_parameters_fingerprint = (
            official_preset_decode_parameters_fingerprint(preset.preset_id)
        )
        request_hash = canonical_sha256(
            {
                "schema_version": OFFICIAL_PRESET_VERSION_SCHEMA_VERSION,
                "operation": VOICE_PRESET_OPERATION,
                "profile_id": str(profile_id),
                "expected_profile_version": request.expected_profile_version,
                "preset_id": preset.preset_id,
                "provenance_fingerprint_sha256": preset.provenance()[
                    "provenance_fingerprint_sha256"
                ],
                "decode_parameters_fingerprint": decode_parameters_fingerprint,
            }
        )
        version_id = _stable_uuid(VOICE_PRESET_OPERATION, idempotency_key)

        def operation(session: Session) -> wire.VoiceProfileVersionResource:
            profile = _required_profile(session, profile_id, for_update=True)
            receipt = _reserve_receipt(
                session,
                operation=VOICE_PRESET_OPERATION,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                resource_id=version_id,
            )
            existing = session.get(VoiceProfileVersion, version_id)
            if receipt.state == "completed":
                if (
                    existing is None
                    or existing.profile_id != profile.id
                    or existing.preset_key != preset.preset_id
                ):
                    raise InvalidNarrationState(
                        "completed official preset receipt has no matching version"
                    )
                resource = voice_profile_resource(
                    SqlAlchemyNarrationStore(session), profile, at=_db_now(session)
                )
                return next(
                    item for item in resource.versions if item.version_id == existing.id
                )
            if existing is not None:
                raise InvalidNarrationState(
                    "new official preset receipt names an existing version"
                )
            if profile.version != request.expected_profile_version:
                raise NarrationCasConflict("voice profile version changed")
            if profile.status in {"archived", "unavailable"}:
                raise InvalidNarrationState(
                    "voice profile cannot accept an official preset"
                )
            now = _db_now(session)
            rights_id = _child_uuid(version_id, "official-preset-rights")
            rights = VoiceRightsRecord(
                id=rights_id,
                owner_id=profile.owner_id,
                workspace_id=profile.workspace_id,
                novel_id=profile.novel_id,
                source_kind="official_preset",
                source_identifier=(
                    f"hf://{OFFICIAL_PRESET_REPOSITORY}@{OFFICIAL_PRESET_REVISION}/"
                    f"browser_poc_manifest.json#{preset.preset_id}"
                ),
                notice_version="moss-tts-official-preset-local-use/1.0",
                purpose="private_novel_narration",
                commercial_use=False,
                redistribution=False,
                voice_cloning=False,
                subject_consent_reference=None,
                confirmed_actor=self._preview_policy.actor,
                confirmed_at=now,
                expires_at=None,
                risk_flags_json=["COMMERCIAL_DISTRIBUTION_NOT_EVALUATED"],
            )
            event = VoiceRightsEvent(
                id=_child_uuid(version_id, "official-preset-confirmed-event"),
                rights_record_id=rights.id,
                event_key=f"official-preset-confirmed:{version_id.hex}",
                event_type="confirmed",
                actor=self._preview_policy.actor,
                reason_code=None,
                occurred_at=now,
            )
            version_number = (
                session.scalar(
                    select(func.max(VoiceProfileVersion.version_number)).where(
                        VoiceProfileVersion.profile_id == profile.id
                    )
                )
                or 0
            ) + 1
            parameters = {
                "schema_version": OFFICIAL_PRESET_VERSION_SCHEMA_VERSION,
                "official_preset": preset.provenance(),
                "sample_mode": self._preview_policy.sample_mode,
                "max_new_frames": self._preview_policy.max_new_frames,
            }
            version = VoiceProfileVersion(
                id=version_id,
                profile_id=profile.id,
                owner_id=profile.owner_id,
                workspace_id=profile.workspace_id,
                version_number=version_number,
                source_type="preset",
                state="draft",
                provider_id="local-sidecar",
                model_id=OFFICIAL_PRESET_REPOSITORY,
                model_revision=OFFICIAL_PRESET_REVISION,
                preset_key=preset.preset_id,
                reference_asset_id=None,
                preview_asset_id=None,
                rights_record_id=rights.id,
                description_digest_key_id=None,
                description_digest=None,
                language=preset.language,
                seed=self._preview_policy.seed,
                parameters_json=parameters,
                fingerprint=official_preset_version_fingerprint(
                    profile_id=profile.id,
                    version_id=version_id,
                    preset_id=preset.preset_id,
                ),
                quality_state="pending",
                locked_actor=None,
                locked_at=None,
                created_at=now,
            )
            # PostgreSQL's cross-table scope trigger validates the referenced
            # rights row at version INSERT time.  Persist that parent first;
            # mapper dependency ordering alone is not sufficient because no
            # ORM relationship joins these independently modelled records.
            session.add(rights)
            session.flush()
            session.add_all([event, version])
            profile.version += 1
            profile.updated_at = now
            _complete_receipt(session, receipt.row_id, at=now)
            session.flush()
            resource = voice_profile_resource(
                SqlAlchemyNarrationStore(session), profile, at=now
            )
            return next(
                item for item in resource.versions if item.version_id == version.id
            )

        return _transaction(self._session_factory, operation)

    def _upload_request_hash(
        self,
        profile_id: UUID,
        parsed: ParsedUploadedVoice,
        normalized: NormalizedReferenceAudio,
    ) -> str:
        rights = parsed.metadata.rights
        source_identifier = unicodedata.normalize("NFC", rights.source_identifier)
        consent_reference = (
            unicodedata.normalize("NFC", rights.subject_consent_reference)
            if rights.subject_consent_reference is not None
            else None
        )
        source_identifier_digest = hashlib.sha256(
            source_identifier.encode("utf-8")
        ).hexdigest()
        consent_reference_digest = (
            hashlib.sha256(consent_reference.encode("utf-8")).hexdigest()
            if consent_reference is not None
            else None
        )
        return canonical_sha256(
            {
                "schema_version": VOICE_PRODUCT_SCHEMA_VERSION,
                "operation": VOICE_UPLOAD_OPERATION,
                "profile_id": str(profile_id),
                "expected_profile_version": parsed.metadata.expected_profile_version,
                "language": parsed.metadata.language,
                "source_sha256": parsed.checksum_sha256,
                "source_byte_size": parsed.byte_size,
                "source_mime_type": parsed.mime_type,
                "normalized_sha256": normalized.normalized_sha256,
                "normalization_fingerprint": normalized.normalization_fingerprint,
                "rights": {
                    "notice_version": rights.notice_version,
                    "source_identifier_digest": source_identifier_digest,
                    "purpose": rights.purpose,
                    "commercial_use": rights.commercial_use,
                    "redistribution": rights.redistribution,
                    "voice_cloning": rights.voice_cloning,
                    "subject_consent_reference_digest": consent_reference_digest,
                    "confirmed": rights.confirmed,
                },
            }
        )

    def _reserve_upload(
        self,
        session: Session,
        *,
        profile_id: UUID,
        parsed: ParsedUploadedVoice,
        normalized: NormalizedReferenceAudio,
        idempotency_key: str,
        request_hash: str,
    ) -> _UploadReservation:
        profile = _required_profile(session, profile_id, for_update=True)
        version_id = _stable_uuid(VOICE_UPLOAD_OPERATION, idempotency_key)
        source_id = _child_uuid(version_id, "source-original")
        reference_id = _child_uuid(version_id, "reference-normalized")
        rights_id = _child_uuid(version_id, "rights")
        link_id = _child_uuid(version_id, "reference-link")
        event_id = _child_uuid(version_id, "rights-confirmed-event")
        receipt = _reserve_receipt(
            session,
            operation=VOICE_UPLOAD_OPERATION,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            resource_id=version_id,
        )
        if receipt.state == "completed":
            existing = session.get(VoiceProfileVersion, version_id)
            if existing is None or existing.profile_id != profile.id:
                raise InvalidNarrationState("completed upload receipt has no voice version")
            return _UploadReservation(
                version_id,
                source_id,
                reference_id,
                rights_id,
                link_id,
                event_id,
                True,
            )
        if profile.version != parsed.metadata.expected_profile_version:
            raise NarrationCasConflict("voice profile version changed")
        if profile.status in {"archived", "unavailable"}:
            raise InvalidNarrationState("voice profile cannot accept a new source")
        source_extension = "wav" if parsed.mime_type == "audio/wav" else "flac"
        exact_assets = (
            (
                source_id,
                "narration_voice_reference_source",
                "source",
                parsed.mime_type,
                parsed.byte_size,
                normalized.source.duration_ms,
                normalized.source.sample_rate_hz,
                normalized.source.channels,
                "uploaded_original",
                parsed.checksum_sha256,
                source_extension,
            ),
            (
                reference_id,
                "narration_voice_reference",
                "voice_reference",
                "audio/wav",
                normalized.normalized_byte_size,
                normalized.duration_ms,
                normalized.sample_rate_hz,
                normalized.channels,
                "locked_voice",
                normalized.normalized_sha256,
                "wav",
            ),
        )
        existing_assets = {
            asset.id: asset
            for asset in session.scalars(
                select(MediaAsset)
                .where(MediaAsset.id.in_([source_id, reference_id]))
                .order_by(MediaAsset.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        }
        now = _db_now(session)
        for (
            asset_id,
            kind,
            asset_class,
            mime_type,
            byte_size,
            duration_ms,
            sample_rate,
            channels,
            retention,
            digest,
            extension,
        ) in exact_assets:
            expected_path = _canonical_asset_path(asset_id, digest, extension)
            existing = existing_assets.get(asset_id)
            if existing is not None:
                actual = (
                    existing.owner_id,
                    existing.workspace_id,
                    existing.novel_id,
                    existing.kind,
                    existing.asset_class,
                    existing.mime_type,
                    existing.byte_size,
                    existing.duration_ms,
                    existing.sample_rate,
                    existing.channels,
                    existing.storage_backend,
                    existing.state,
                    existing.retention_policy,
                    existing.checksum_algorithm,
                    existing.storage_path,
                    existing.content_hash,
                )
                expected = (
                    profile.owner_id,
                    profile.workspace_id,
                    profile.novel_id,
                    kind,
                    asset_class,
                    mime_type,
                    byte_size,
                    duration_ms,
                    sample_rate,
                    channels,
                    "local",
                    "staging",
                    retention,
                    "sha256",
                    expected_path,
                    digest,
                )
                if actual != expected:
                    raise VoiceProductSecurityError("reserved upload asset identity changed")
                continue
            filename_digest = hashlib.sha256(
                parsed.filename.encode("utf-8")
            ).hexdigest()
            session.add(
                MediaAsset(
                    id=asset_id,
                    owner_id=profile.owner_id,
                    workspace_id=profile.workspace_id,
                    novel_id=profile.novel_id,
                    source_revision_id=None,
                    kind=kind,
                    asset_class=asset_class,
                    mime_type=mime_type,
                    byte_size=byte_size,
                    duration_ms=duration_ms,
                    sample_rate=sample_rate,
                    channels=channels,
                    storage_backend="local",
                    state="staging",
                    retention_policy=retention,
                    checksum_algorithm="sha256",
                    validation_json={},
                    verified_at=None,
                    last_accessed_at=None,
                    expires_at=None,
                    deleted_at=None,
                    gc_generation=0,
                    gc_marked_at=None,
                    storage_path=expected_path,
                    content_hash=digest,
                    metadata_json={
                        "schema_version": VOICE_PRODUCT_SCHEMA_VERSION,
                        "voice_version_id": str(version_id),
                        "filename_sha256": filename_digest,
                    },
                    created_at=now,
                )
            )
        session.flush()
        return _UploadReservation(
            version_id,
            source_id,
            reference_id,
            rights_id,
            link_id,
            event_id,
            False,
        )

    def _finalize_upload(
        self,
        session: Session,
        *,
        reservation: _UploadReservation,
        profile_id: UUID,
        parsed: ParsedUploadedVoice,
        normalized: NormalizedReferenceAudio,
        idempotency_key: str,
        request_hash: str,
        source_publication: PublishedFile,
        reference_publication: PublishedFile,
    ) -> wire.VoiceProfileVersionResource:
        profile = _required_profile(session, profile_id, for_update=True)
        receipt = session.scalar(
            select(VoiceActionReceipt)
            .where(
                VoiceActionReceipt.owner_id == profile.owner_id,
                VoiceActionReceipt.workspace_id == profile.workspace_id,
                VoiceActionReceipt.operation == VOICE_UPLOAD_OPERATION,
                VoiceActionReceipt.idempotency_key == idempotency_key,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if receipt is None:
            raise InvalidNarrationState("upload receipt disappeared before finalization")
        _assert_receipt(
            receipt,
            operation=VOICE_UPLOAD_OPERATION,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            resource_id=reservation.version_id,
        )
        existing_version = session.get(VoiceProfileVersion, reservation.version_id)
        if receipt.state == "completed":
            if existing_version is None or existing_version.profile_id != profile.id:
                raise InvalidNarrationState("completed upload has no matching version")
            resource = voice_profile_resource(SqlAlchemyNarrationStore(session), profile)
            return next(
                item for item in resource.versions if item.version_id == existing_version.id
            )
        if existing_version is not None:
            raise InvalidNarrationState("reserved upload unexpectedly has a voice version")
        if profile.version != parsed.metadata.expected_profile_version:
            raise NarrationCasConflict("voice profile version changed during normalization")
        assets = {
            asset.id: asset
            for asset in session.scalars(
                select(MediaAsset)
                .where(
                    MediaAsset.id.in_(
                        [reservation.source_asset_id, reservation.reference_asset_id]
                    )
                )
                .order_by(MediaAsset.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        }
        if set(assets) != {reservation.source_asset_id, reservation.reference_asset_id}:
            raise InvalidNarrationState("reserved upload assets are incomplete")
        source = assets[reservation.source_asset_id]
        reference = assets[reservation.reference_asset_id]
        for asset, publication in (
            (source, source_publication),
            (reference, reference_publication),
        ):
            if (
                asset.state != "staging"
                or publication.asset_id != asset.id
                or publication.actual_sha256 != asset.content_hash
                or publication.byte_size != asset.byte_size
                or publication.relative_path != asset.storage_path
            ):
                raise VoiceProductSecurityError("upload publication evidence changed")
        validation_fingerprint = _json_sha256(normalized.validation_evidence)
        now = _db_now(session)
        source.state = "ready"
        source.verified_at = now
        source.validation_json = {
            "schema_version": VOICE_PRODUCT_SCHEMA_VERSION,
            "source": asdict(normalized.source),
            "checks": {
                "single_audio_stream": True,
                "fully_decoded": True,
                "declared_sha256_matches": True,
            },
        }
        reference.state = "ready"
        reference.verified_at = now
        reference.validation_json = normalized.validation_evidence
        rights_request = parsed.metadata.rights
        rights = VoiceRightsRecord(
            id=reservation.rights_record_id,
            owner_id=profile.owner_id,
            workspace_id=profile.workspace_id,
            novel_id=profile.novel_id,
            source_kind="user_upload",
            source_identifier=unicodedata.normalize(
                "NFC", rights_request.source_identifier
            ),
            notice_version=rights_request.notice_version,
            purpose=rights_request.purpose,
            commercial_use=rights_request.commercial_use,
            redistribution=rights_request.redistribution,
            voice_cloning=rights_request.voice_cloning,
            subject_consent_reference=(
                unicodedata.normalize(
                    "NFC", rights_request.subject_consent_reference
                )
                if rights_request.subject_consent_reference is not None
                else None
            ),
            confirmed_actor=self._preview_policy.actor,
            confirmed_at=now,
            expires_at=None,
            risk_flags_json=[],
        )
        event = VoiceRightsEvent(
            id=reservation.event_id,
            rights_record_id=rights.id,
            event_key=f"upload-confirmed:{reservation.version_id.hex}",
            event_type="confirmed",
            actor=self._preview_policy.actor,
            reason_code=None,
            occurred_at=now,
        )
        version_number = (
            session.scalar(
                select(func.max(VoiceProfileVersion.version_number)).where(
                    VoiceProfileVersion.profile_id == profile.id
                )
            )
            or 0
        ) + 1
        voice_fingerprint = canonical_sha256(
            {
                "schema_version": VOICE_PRODUCT_SCHEMA_VERSION,
                "profile_id": str(profile.id),
                "version_id": str(reservation.version_id),
                "source_type": "uploaded",
                "reference_sha256": normalized.normalized_sha256,
                "normalization_fingerprint": normalized.normalization_fingerprint,
                "validation_fingerprint": validation_fingerprint,
                "rights_record_id": str(rights.id),
                "language": parsed.metadata.language,
                "decode_parameters_fingerprint": (
                    self._preview_policy.parameters_fingerprint
                ),
            }
        )
        version = VoiceProfileVersion(
            id=reservation.version_id,
            profile_id=profile.id,
            owner_id=profile.owner_id,
            workspace_id=profile.workspace_id,
            version_number=version_number,
            source_type="uploaded",
            state="draft",
            provider_id=None,
            model_id=None,
            model_revision=None,
            preset_key=None,
            reference_asset_id=reference.id,
            preview_asset_id=None,
            rights_record_id=rights.id,
            description_digest_key_id=None,
            description_digest=None,
            language=parsed.metadata.language,
            seed=self._preview_policy.seed,
            parameters_json={
                "schema_version": VOICE_PRODUCT_SCHEMA_VERSION,
                "normalization_fingerprint": normalized.normalization_fingerprint,
                "validation_fingerprint": validation_fingerprint,
                "sample_mode": self._preview_policy.sample_mode,
                "max_new_frames": self._preview_policy.max_new_frames,
            },
            fingerprint=voice_fingerprint,
            quality_state="pending",
            locked_actor=None,
            locked_at=None,
            created_at=now,
        )
        link = VoiceReferenceAssetLink(
            id=reservation.link_id,
            owner_id=profile.owner_id,
            workspace_id=profile.workspace_id,
            novel_id=profile.novel_id,
            profile_id=profile.id,
            voice_version_id=version.id,
            rights_record_id=rights.id,
            source_asset_id=source.id,
            reference_asset_id=reference.id,
            normalization_fingerprint=normalized.normalization_fingerprint,
            validation_fingerprint=validation_fingerprint,
            created_at=now,
        )
        # The version scope trigger must observe its immutable rights parent.
        # Flush only that parent before adding the event/version/link closure;
        # the enclosing transaction still commits or rolls back atomically.
        session.add(rights)
        session.flush()
        session.add_all([event, version, link])
        profile.version += 1
        profile.updated_at = now
        _complete_receipt(session, receipt.id, at=now)
        session.flush()
        resource = voice_profile_resource(SqlAlchemyNarrationStore(session), profile, at=now)
        return next(item for item in resource.versions if item.version_id == version.id)

    def create_uploaded_version(
        self,
        *,
        profile_id: UUID,
        parsed: ParsedUploadedVoice,
        idempotency_key: str,
    ) -> wire.VoiceProfileVersionResource:
        """Normalize -> reserve -> publish -> finalize without long DB tx."""

        try:
            normalized = self._normalize_reference(parsed)
        except ReferenceToolchainUnavailable as error:
            from .settings_api import NarrationApiFault

            raise NarrationApiFault(
                wire.NarrationErrorCode.STORAGE_UNAVAILABLE,
                "参考录音标准化工具链当前不可用。",
                retryable=True,
                capability=wire.CapabilityKey.REFERENCE_CLONE,
            ) from error
        except (ReferenceAudioInvalid, ReferenceAudioQualityRejected) as error:
            raise VoiceUploadValidationError(
                wire.NarrationErrorCode.REFERENCE_AUDIO_INVALID,
                "reference audio did not pass fixed validation",
                field_name="reference_audio",
            ) from error
        request_hash = self._upload_request_hash(profile_id, parsed, normalized)
        reservation = _transaction(
            self._session_factory,
            lambda session: self._reserve_upload(
                session,
                profile_id=profile_id,
                parsed=parsed,
                normalized=normalized,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            ),
        )
        if reservation.completed:
            return _transaction(
                self._session_factory,
                lambda session: self._completed_upload_resource(
                    session,
                    profile_id=profile_id,
                    version_id=reservation.version_id,
                ),
            )
        source_extension = "wav" if parsed.mime_type == "audio/wav" else "flac"
        source_publication = _published_or_adopted(
            self._storage,
            parsed.reference_audio,
            asset_id=reservation.source_asset_id,
            digest=parsed.checksum_sha256,
            extension=source_extension,
            max_bytes=wire.REFERENCE_UPLOAD_MAX_BYTES,
        )
        reference_publication = _published_or_adopted(
            self._storage,
            normalized.normalized_bytes,
            asset_id=reservation.reference_asset_id,
            digest=normalized.normalized_sha256,
            extension="wav",
            max_bytes=max(normalized.normalized_byte_size, 4 * 1024 * 1024),
        )
        return _transaction(
            self._session_factory,
            lambda session: self._finalize_upload(
                session,
                reservation=reservation,
                profile_id=profile_id,
                parsed=parsed,
                normalized=normalized,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                source_publication=source_publication,
                reference_publication=reference_publication,
            ),
        )

    @staticmethod
    def _completed_upload_resource(
        session: Session,
        *,
        profile_id: UUID,
        version_id: UUID,
    ) -> wire.VoiceProfileVersionResource:
        profile = _required_profile(session, profile_id, for_update=False)
        version = _required_version(
            session, profile_id, version_id, for_update=False
        )
        resource = voice_profile_resource(SqlAlchemyNarrationStore(session), profile)
        return next(item for item in resource.versions if item.version_id == version.id)

    def _create_preview_in_session(
        self,
        session: Session,
        *,
        profile_id: UUID,
        request: wire.CreateVoicePreviewRequest,
        idempotency_key: str,
        text: str,
        text_digest: str,
        text_digest_key_id: str,
    ) -> wire.VoicePreviewResource:
        scope = NarrationRequestScope.fixed_local()

        def completed_replay(
            receipt: VoiceActionReceipt,
        ) -> wire.VoicePreviewResource:
            replay = session.scalar(
                select(VoicePreview)
                .where(VoicePreview.id == receipt.resource_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if receipt.state != "completed" or replay is None:
                raise InvalidNarrationState(
                    "preview receipt has no completed resource"
                )
            if (
                receipt.request_hash != replay.request_fingerprint
                or replay.profile_id != profile_id
                or replay.version_id != request.version_id
            ):
                raise IdempotencyConflict(
                    "preview key already names another request"
                )
            historical_key = self._digest_keyring.require(
                replay.preview_text_digest_key_id
            )
            historical_digest = historical_private_text_digest(
                historical_key,
                purpose=VOICE_PREVIEW_TEXT_PURPOSE,
                text=text,
            )
            if not hmac.compare_digest(
                historical_digest, replay.preview_text_digest
            ):
                raise IdempotencyConflict(
                    "preview key already names another request"
                )
            return self._preview_resource(session, replay, at=_db_now(session))

        replay_receipt = session.scalar(
            select(VoiceActionReceipt)
            .where(
                VoiceActionReceipt.owner_id == scope.owner_id,
                VoiceActionReceipt.workspace_id == scope.workspace_id,
                VoiceActionReceipt.operation == VOICE_PREVIEW_OPERATION,
                VoiceActionReceipt.idempotency_key == idempotency_key,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if replay_receipt is not None:
            return completed_replay(replay_receipt)
        # Global voice authority lock order is Version -> Profile -> Rights.
        version = _required_version(
            session, profile_id, request.version_id, for_update=True
        )
        profile = _required_profile(session, profile_id, for_update=True)
        now = _db_now(session)
        rights = _required_active_rights(
            session, profile, version, at=now, for_update=True
        )
        if version.source_type not in {"uploaded", "preset"} or version.state not in {
            "draft",
            "preview_ready",
            "locked",
        }:
            raise InvalidNarrationState("voice version cannot create a Nano preview")
        reference: MediaAsset | None = None
        if version.source_type == "uploaded":
            link = _required_reference_link(session, version, for_update=False)
            reference = _required_reference_asset(
                session, profile, version, link, for_update=True
            )
            source_fingerprint = _reference_fingerprint(version, link, reference)
            voice_key = self._preview_policy.voice_key
        else:
            preset = _required_official_preset(
                version,
                rights,
                expected_model_fingerprint=(
                    self._preview_policy.expected_model_fingerprint
                ),
            )
            source_fingerprint = str(
                preset.provenance()["provenance_fingerprint_sha256"]
            )
            voice_key = preset.preset_id
        parameters_fingerprint = (
            self._preview_policy.parameters_fingerprint_for_version(
                version, voice_key
            )
        )
        request_fingerprint = canonical_sha256(
            {
                "schema_version": VOICE_PRODUCT_SCHEMA_VERSION,
                "operation": VOICE_PREVIEW_OPERATION,
                "profile_id": str(profile.id),
                "version_id": str(version.id),
                "preview_text_digest_key_id": text_digest_key_id,
                "preview_text_digest": text_digest,
                "model_fingerprint": self._preview_policy.expected_model_fingerprint,
                "source_fingerprint": source_fingerprint,
                "parameters_fingerprint": parameters_fingerprint,
            }
        )
        preview_id = _stable_uuid(VOICE_PREVIEW_OPERATION, idempotency_key)
        # The first lookup intentionally precedes authority locks for the
        # common replay path. Repeat it after those locks so a concurrent first
        # writer that committed while we waited also replays across an HMAC-key
        # rotation instead of becoming a false conflict.
        concurrent_receipt = session.scalar(
            select(VoiceActionReceipt)
            .where(
                VoiceActionReceipt.owner_id == scope.owner_id,
                VoiceActionReceipt.workspace_id == scope.workspace_id,
                VoiceActionReceipt.operation == VOICE_PREVIEW_OPERATION,
                VoiceActionReceipt.idempotency_key == idempotency_key,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if concurrent_receipt is not None:
            return completed_replay(concurrent_receipt)
        receipt = _reserve_receipt(
            session,
            operation=VOICE_PREVIEW_OPERATION,
            idempotency_key=idempotency_key,
            request_hash=request_fingerprint,
            resource_id=preview_id,
        )
        existing = session.scalar(
            select(VoicePreview)
            .where(VoicePreview.id == preview_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if receipt.replay:
            if existing is None or receipt.state != "completed":
                raise InvalidNarrationState("preview receipt has no completed resource")
            return self._preview_resource(session, existing, at=now)
        if existing is not None:
            raise InvalidNarrationState("new preview receipt names an existing preview")
        enqueue = enqueue_job(
            session,
            scope=NarrationRequestScope.fixed_local(),
            job_kind=VOICE_PREVIEW_JOB_KIND,
            input_hash=request_fingerprint,
            idempotency_key=f"voice-preview:{preview_id.hex}",
            resource_class=VOICE_PREVIEW_RESOURCE_CLASS,
            novel_id=profile.novel_id,
            request_id=None,
            base_priority=50,
            max_attempts=3,
            interactive_priority=100,
            interactive_priority_expires_at=now + timedelta(minutes=5),
        )
        preview = VoicePreview(
            id=preview_id,
            owner_id=profile.owner_id,
            workspace_id=profile.workspace_id,
            novel_id=profile.novel_id,
            profile_id=profile.id,
            version_id=version.id,
            rights_record_id=rights.id,
            job_id=enqueue.job_id,
            reference_asset_id=(reference.id if reference is not None else None),
            result_asset_id=None,
            preview_text=text,
            preview_text_digest_key_id=text_digest_key_id,
            preview_text_digest=text_digest,
            model_fingerprint=self._preview_policy.expected_model_fingerprint,
            reference_fingerprint=source_fingerprint,
            parameters_fingerprint=parameters_fingerprint,
            request_fingerprint=request_fingerprint,
            status="queued",
            started_at=None,
            completed_at=None,
            expires_at=None,
            failure_code=None,
            created_at=now,
            updated_at=now,
        )
        session.add(preview)
        if reference is not None:
            session.add(
                ActiveJobAsset(
                    job_id=enqueue.job_id,
                    asset_id=reference.id,
                    owner_id=profile.owner_id,
                    workspace_id=profile.workspace_id,
                    novel_id=profile.novel_id,
                    role="input",
                    acquired_at=now,
                    released_at=None,
                )
            )
        _complete_receipt(session, receipt.row_id, at=now)
        session.flush()
        return self._preview_resource(session, preview, at=now)

    def create_preview(
        self,
        *,
        profile_id: UUID,
        request: wire.CreateVoicePreviewRequest,
        idempotency_key: str,
    ) -> wire.VoicePreviewResource:
        text = unicodedata.normalize("NFC", request.preview_text)
        if not text.strip() or len(text) > 500:
            raise VoiceProductContractError("preview text is outside the frozen bounds")
        key = self._digest_keyring.active
        text_digest = private_text_digest(
            key,
            purpose=VOICE_PREVIEW_TEXT_PURPOSE,
            text=text,
        )
        return _transaction(
            self._session_factory,
            lambda session: self._create_preview_in_session(
                session,
                profile_id=profile_id,
                request=request,
                idempotency_key=idempotency_key,
                text=text,
                text_digest=text_digest,
                text_digest_key_id=key.key_id,
            ),
        )

    @staticmethod
    def _preview_resource(
        session: Session,
        preview: VoicePreview,
        *,
        at: datetime,
    ) -> wire.VoicePreviewResource:
        scope = NarrationRequestScope.fixed_local()
        if preview.owner_id != scope.owner_id or preview.workspace_id != scope.workspace_id:
            raise NarrationScopeMismatch("voice preview is outside fixed local scope")
        status = wire.VoicePreviewStatus(preview.status)
        asset_link: wire.MediaAssetLink | None = None
        failure_code: wire.NarrationErrorCode | None = None
        expires_at = preview.expires_at
        if status is wire.VoicePreviewStatus.READY:
            if expires_at is None or expires_at <= at:
                status = wire.VoicePreviewStatus.UNAVAILABLE
                failure_code = wire.NarrationErrorCode.PREVIEW_UNAVAILABLE
                expires_at = preview.expires_at
            else:
                profile = _required_profile(
                    session, preview.profile_id, for_update=False
                )
                from .voices import _media_link

                asset_link = _media_link(
                    SqlAlchemyNarrationStore(session),
                    profile,
                    preview.result_asset_id,
                )
        elif status is wire.VoicePreviewStatus.FAILED:
            failure_code = wire.NarrationErrorCode.PREVIEW_FAILED
        return wire.VoicePreviewResource(
            preview_id=preview.id,
            profile_id=preview.profile_id,
            version_id=preview.version_id,
            status=status,
            job_id=(
                preview.job_id
                if status
                in {wire.VoicePreviewStatus.QUEUED, wire.VoicePreviewStatus.RUNNING}
                else None
            ),
            asset=asset_link,
            temporary=True,
            expires_at=expires_at,
            failure_code=failure_code,
        )

    def get_preview(self, *, preview_id: UUID) -> wire.VoicePreviewResource:
        def operation(session: Session) -> wire.VoicePreviewResource:
            preview = session.get(VoicePreview, preview_id)
            if preview is None:
                raise VoicePreviewNotFound("voice preview not found")
            return self._preview_resource(session, preview, at=_db_now(session))

        return _transaction(self._session_factory, operation)

    def _lock_in_session(
        self,
        session: Session,
        *,
        profile_id: UUID,
        request: wire.LockVoiceProfileRequest,
    ) -> wire.VoiceProfileResource:
        if request.quality_confirmed is not True:
            raise VoiceProductContractError(
                "voice quality must be explicitly confirmed"
            )
        version = _required_version(
            session, profile_id, request.version_id, for_update=True
        )
        profile = _required_profile(session, profile_id, for_update=True)
        now = _db_now(session)
        rights = _required_active_rights(
            session, profile, version, at=now, for_update=True
        )
        reference: MediaAsset | None = None
        if version.source_type == "uploaded":
            link = _required_reference_link(session, version, for_update=False)
            reference = _required_reference_asset(
                session, profile, version, link, for_update=True
            )
            expected_source = _reference_fingerprint(version, link, reference)
            voice_key = self._preview_policy.voice_key
        elif version.source_type == "preset":
            preset = _required_official_preset(
                version,
                rights,
                expected_model_fingerprint=(
                    self._preview_policy.expected_model_fingerprint
                ),
            )
            expected_source = str(
                preset.provenance()["provenance_fingerprint_sha256"]
            )
            voice_key = preset.preset_id
        else:
            raise InvalidNarrationState("voice version cannot be locked by Nano preview")
        request_hash = canonical_sha256(
            {
                "schema_version": VOICE_PRODUCT_SCHEMA_VERSION,
                "operation": VOICE_LOCK_OPERATION,
                "profile_id": str(profile.id),
                "expected_profile_version": request.expected_profile_version,
                "version_id": str(version.id),
                "quality_confirmed": request.quality_confirmed,
            }
        )
        lock_key = f"lock:{version.id.hex}:{request.expected_profile_version}"
        receipt = _reserve_receipt(
            session,
            operation=VOICE_LOCK_OPERATION,
            idempotency_key=lock_key,
            request_hash=request_hash,
            resource_id=version.id,
        )
        if receipt.state == "completed":
            if (
                profile.current_version_id != version.id
                or profile.status != "active"
                or version.state != "locked"
                or version.quality_state != "accepted"
            ):
                raise InvalidNarrationState("completed lock receipt has no locked version")
            return voice_profile_resource(SqlAlchemyNarrationStore(session), profile, at=now)
        if profile.version != request.expected_profile_version:
            raise NarrationCasConflict("voice profile version changed")
        if version.state != "preview_ready" or version.quality_state != "pending":
            raise InvalidNarrationState("voice version must have a real preview before lock")
        previews = list(
            session.scalars(
                select(VoicePreview)
                .where(
                    VoicePreview.profile_id == profile.id,
                    VoicePreview.version_id == version.id,
                    VoicePreview.rights_record_id == rights.id,
                    VoicePreview.status == "ready",
                    VoicePreview.expires_at.is_not(None),
                    VoicePreview.expires_at > now,
                )
                .order_by(VoicePreview.completed_at.desc(), VoicePreview.id.desc())
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        if not previews:
            raise InvalidNarrationState("voice lock requires an unexpired Nano preview")
        preview = previews[0]
        if (
            preview.reference_asset_id
            != (reference.id if reference is not None else None)
            or preview.reference_fingerprint != expected_source
            or preview.model_fingerprint
            != self._preview_policy.expected_model_fingerprint
            or preview.parameters_fingerprint
            != self._preview_policy.parameters_fingerprint_for_version(
                version, voice_key
            )
            or preview.result_asset_id is None
        ):
            raise VoiceProductSecurityError("voice preview fingerprint no longer matches")
        result_asset = session.scalar(
            select(MediaAsset)
            .where(MediaAsset.id == preview.result_asset_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            result_asset is None
            or result_asset.asset_class != "preview"
            or result_asset.kind != "narration_voice_preview"
            or result_asset.retention_policy != "temporary_preview"
            or result_asset.state != "ready"
            or result_asset.expires_at != preview.expires_at
            or result_asset.owner_id != profile.owner_id
            or result_asset.workspace_id != profile.workspace_id
            or result_asset.novel_id != profile.novel_id
        ):
            raise VoiceProductSecurityError("voice preview media is not authoritative")
        model_run = session.scalar(
            select(ModelRunRecord)
            .join(
                BackgroundJobAttempt,
                BackgroundJobAttempt.id == ModelRunRecord.attempt_id,
            )
            .where(
                BackgroundJobAttempt.job_id == preview.job_id,
                ModelRunRecord.result_classification == "success",
            )
        )
        if (
            model_run is None
            or model_run.model_fingerprint != preview.model_fingerprint
            or model_run.parameters_digest != preview.parameters_fingerprint
            or model_run.output_digest != result_asset.content_hash
        ):
            raise VoiceProductSecurityError("voice preview lacks matching model-run evidence")
        version.state = "locked"
        version.quality_state = "accepted"
        version.locked_actor = self._preview_policy.actor
        version.locked_at = now
        profile.current_version_id = version.id
        profile.status = "active"
        profile.version += 1
        profile.updated_at = now
        _complete_receipt(session, receipt.row_id, at=now)
        session.flush()
        return voice_profile_resource(SqlAlchemyNarrationStore(session), profile, at=now)

    def lock_profile(
        self,
        *,
        profile_id: UUID,
        request: wire.LockVoiceProfileRequest,
    ) -> wire.VoiceProfileResource:
        return _transaction(
            self._session_factory,
            lambda session: self._lock_in_session(
                session, profile_id=profile_id, request=request
            ),
        )


def _model_input_digest(
    keyring: DigestKeyring,
    *,
    key_id: str,
    metadata: bytes,
) -> str:
    key = keyring.require(key_id)
    domain = (
        VOICE_PRODUCT_SCHEMA_VERSION.encode("ascii")
        + b"\0"
        + VOICE_PREVIEW_INPUT_PURPOSE.encode("ascii")
        + b"\0"
    )
    return key.digest_for_verification(domain + metadata)


class _SqlAlchemyVoicePreviewRepositoryBase:
    """Fenced, short-transaction persistence for the preview worker."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        digest_keyring: DigestKeyring,
        policy: VoicePreviewPolicy,
    ) -> None:
        if not callable(session_factory):
            raise TypeError("voice preview repository requires a Session factory")
        if type(digest_keyring) is not DigestKeyring:
            raise TypeError("voice preview repository requires a digest keyring")
        policy.validate()
        self._session_factory = session_factory
        self._digest_keyring = digest_keyring
        self._policy = policy
        self._scope = NarrationRequestScope.fixed_local()

    def _job(
        self, session: Session, lease: JobLease, *, for_update: bool
    ) -> BackgroundJob:
        statement = select(BackgroundJob).where(
            BackgroundJob.id == lease.fence.job_id,
            BackgroundJob.owner_id == self._scope.owner_id,
            BackgroundJob.workspace_id == self._scope.workspace_id,
        )
        if for_update:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        job = session.scalar(statement)
        if (
            job is None
            or job.job_kind != VOICE_PREVIEW_JOB_KIND
            or job.resource_class != VOICE_PREVIEW_RESOURCE_CLASS
        ):
            raise VoiceProductSecurityError("worker claim is not a voice preview job")
        return job

    @staticmethod
    def _preview_for_job(
        session: Session, job_id: UUID, *, for_update: bool
    ) -> VoicePreview:
        statement = select(VoicePreview).where(VoicePreview.job_id == job_id)
        if for_update:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        preview = session.scalar(statement)
        if preview is None:
            raise InvalidNarrationState("voice preview job has no product resource")
        return preview

    def load_and_mark_running(self, lease: JobLease) -> VoicePreviewWorkItem:
        def operation(session: Session) -> VoicePreviewWorkItem:
            heartbeat_attempt(session, scope=self._scope, fence=lease.fence)
            job = self._job(session, lease, for_update=True)
            preview_hint = self._preview_for_job(session, job.id, for_update=False)
            # Keep the global voice authority order after the job fence.
            version = _required_version(
                session,
                preview_hint.profile_id,
                preview_hint.version_id,
                for_update=True,
            )
            profile = _required_profile(
                session, preview_hint.profile_id, for_update=True
            )
            now = _db_now(session)
            rights = _required_active_rights(
                session, profile, version, at=now, for_update=True
            )
            preview = self._preview_for_job(session, job.id, for_update=True)
            if (
                preview.id != preview_hint.id
                or preview.profile_id != profile.id
                or preview.version_id != version.id
                or preview.rights_record_id != rights.id
                or preview.novel_id != job.novel_id
                or preview.owner_id != job.owner_id
                or preview.workspace_id != job.workspace_id
                or preview.preview_text is None
            ):
                raise VoiceProductSecurityError("voice preview job provenance changed")
            if preview.status not in {"queued", "running"}:
                raise InvalidNarrationState("voice preview is already terminal")
            reference: MediaAsset | None = None
            if version.source_type == "uploaded":
                link = _required_reference_link(session, version, for_update=False)
                reference = _required_reference_asset(
                    session, profile, version, link, for_update=True
                )
                source_fingerprint = _reference_fingerprint(
                    version, link, reference
                )
                voice_key = self._policy.voice_key
            elif version.source_type == "preset":
                preset = _required_official_preset(
                    version,
                    rights,
                    expected_model_fingerprint=(
                        self._policy.expected_model_fingerprint
                    ),
                )
                source_fingerprint = str(
                    preset.provenance()["provenance_fingerprint_sha256"]
                )
                voice_key = preset.preset_id
            else:
                raise VoiceProductSecurityError(
                    "voice preview source type is unsupported"
                )
            seed, sample_mode, max_new_frames = _version_decode_parameters(version)
            version_parameters_fingerprint = (
                self._policy.parameters_fingerprint_for_version(version, voice_key)
            )
            if (
                preview.reference_asset_id
                != (reference.id if reference is not None else None)
                or preview.reference_fingerprint != source_fingerprint
                or preview.model_fingerprint
                != self._policy.expected_model_fingerprint
                or preview.parameters_fingerprint
                != version_parameters_fingerprint
            ):
                raise VoiceProductSecurityError("voice preview input fingerprint changed")
            key = self._digest_keyring.require(preview.preview_text_digest_key_id)
            expected_text_digest = historical_private_text_digest(
                key,
                purpose=VOICE_PREVIEW_TEXT_PURPOSE,
                text=preview.preview_text,
            )
            if not hmac.compare_digest(
                expected_text_digest, preview.preview_text_digest
            ):
                raise VoiceProductSecurityError("private preview text digest changed")
            metadata = canonical_sidecar_synthesis_metadata(
                request_id=lease.fence.attempt_id,
                scope=self._scope,
                requested_model_fingerprint_sha256=preview.model_fingerprint,
                text=preview.preview_text,
                voice=voice_key,
                seed=seed,
                sample_mode=sample_mode,
                max_new_frames=max_new_frames,
                reference_content_type=(
                    reference.mime_type if reference is not None else None
                ),
                reference_actual_sha256=(
                    reference.content_hash if reference is not None else None
                ),
                reference_size_bytes=(
                    reference.byte_size if reference is not None else None
                ),
            )
            input_digest = _model_input_digest(
                self._digest_keyring,
                key_id=self._digest_keyring.active_key_id,
                metadata=metadata,
            )
            if preview.status == "queued":
                preview.status = "running"
                preview.started_at = now
                preview.updated_at = now
            session.flush()
            return VoicePreviewWorkItem(
                lease=lease,
                preview_id=preview.id,
                profile_id=profile.id,
                version_id=version.id,
                rights_record_id=rights.id,
                novel_id=profile.novel_id,
                text=preview.preview_text,
                voice=voice_key,
                seed=seed,
                sample_mode=sample_mode,
                max_new_frames=max_new_frames,
                expected_model_fingerprint=preview.model_fingerprint,
                reference_fingerprint=preview.reference_fingerprint,
                parameters_fingerprint=preview.parameters_fingerprint,
                input_digest_key_id=self._digest_keyring.active_key_id,
                input_digest=input_digest,
                reference=(
                    VoiceReferenceMedia(
                        relative_path=reference.storage_path,
                        actual_sha256=reference.content_hash,
                        byte_size=reference.byte_size,
                        content_type=reference.mime_type,
                    )
                    if reference is not None
                    else None
                ),
            )

        return _transaction(self._session_factory, operation)


class VoicePreviewProcessor:
    """Execute one already-claimed ``narration.voice_preview`` Nano job."""

    def __init__(
        self,
        *,
        repository: VoicePreviewRepository,
        adapter: MossNanoTTSAdapter,
        storage: NarrationStorage,
        policy: VoicePreviewPolicy,
    ) -> None:
        policy.validate()
        capabilities = adapter.capabilities
        if capabilities != MOSS_NANO_SIDECAR_CONTRACT_CAPABILITIES:
            raise TypeError("voice preview processor requires a real reference-capable Nano adapter")
        self._repository = repository
        self._adapter = adapter
        self._storage = storage
        self._policy = policy

    def _reference_input(self, reference: VoiceReferenceMedia) -> ReferenceAudioInput:
        if reference.byte_size > self._policy.max_reference_bytes:
            raise VoiceProductSecurityError("voice reference exceeds worker byte bound")
        identity = self._storage.verify_media_identity(
            reference.relative_path,
            expected_sha256=reference.actual_sha256,
            expected_size=reference.byte_size,
            max_bytes=self._policy.max_reference_bytes,
        )
        payload = b"".join(
            self._storage.stream_media(
                reference.relative_path,
                expected_device=identity.device,
                expected_inode=identity.inode,
                expected_size=identity.byte_size,
            )
        )
        return ReferenceAudioInput(
            audio_bytes=payload,
            actual_sha256=reference.actual_sha256,
            content_type=reference.content_type,
        )

    async def _synthesize(self, work: VoicePreviewWorkItem) -> SynthesisResult:
        reference = (
            await asyncio.to_thread(self._reference_input, work.reference)
            if work.reference is not None
            else None
        )
        request = SynthesisRequest(
            request_id=work.lease.fence.attempt_id,
            scope=NarrationRequestScope.fixed_local(),
            text=work.text,
            voice=work.voice,
            seed=work.seed,
            sample_mode=work.sample_mode,
            max_new_frames=work.max_new_frames,
            reference_audio=reference,
        )
        task = asyncio.create_task(self._adapter.synthesize(request))
        cancellation_sent = False
        try:
            while True:
                try:
                    result = await asyncio.wait_for(
                        asyncio.shield(task),
                        timeout=float(self._policy.heartbeat_seconds),
                    )
                    if type(result) is not SynthesisResult:
                        raise VoiceProductContractError("Nano returned an invalid result")
                    return result
                except TimeoutError:
                    state = await asyncio.to_thread(
                        self._repository.heartbeat_and_read_state, work.lease
                    )
                    if state == "cancel_requested" and not cancellation_sent:
                        cancellation_sent = True
                        await self._adapter.cancel(request.request_id)
                    elif state not in {"running", "cancel_requested"}:
                        task.cancel()
                        try:
                            await task
                        except (asyncio.CancelledError, Exception):
                            pass
                        raise JobFenceError("preview job became terminal during synthesis")
        except asyncio.CancelledError:
            if not task.done():
                try:
                    await self._adapter.cancel(request.request_id)
                finally:
                    task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
            raise

    def _prepare(
        self,
        work: VoicePreviewWorkItem,
        synthesis: SynthesisResult,
    ) -> PreparedVoicePreview:
        if synthesis.request_id != work.lease.fence.attempt_id:
            raise VoiceProductSecurityError("Nano result belongs to another attempt")
        actual_fingerprint = model_fingerprint_sha256(synthesis.model_fingerprint)
        if actual_fingerprint != work.expected_model_fingerprint:
            raise VoiceProductSecurityError("Nano model fingerprint changed")
        processed: ProcessedPcmWav = process_synthesis_wav(synthesis.audio_bytes)
        result_asset_id = _child_uuid(work.preview_id, "preview-result")
        published = _published_or_adopted(
            self._storage,
            processed.wav_bytes,
            asset_id=result_asset_id,
            digest=processed.actual_sha256,
            extension="wav",
            max_bytes=MAX_PREVIEW_MEDIA_BYTES,
        )
        return PreparedVoicePreview(
            published=published,
            duration_ms=processed.duration_ms,
            sample_rate_hz=processed.sample_rate_hz,
            channels=processed.channels,
            audio_validation={
                "schema_version": VOICE_PRODUCT_SCHEMA_VERSION,
                "input": asdict(processed.input_inspection),
                "output": asdict(processed.output_inspection),
                "processing_fingerprint": processed.processing_fingerprint,
                "applied_gain_db": processed.applied_gain_db,
                "seam_fade_ms": processed.seam_fade_ms,
            },
            requested_provider_id=self._policy.requested_provider_id,
            requested_model_id=self._policy.requested_model_id,
            requested_revision=self._policy.requested_revision,
            actual_provider_id=self._policy.requested_provider_id,
            actual_model_id=synthesis.model_fingerprint.model_name,
            actual_revision=synthesis.model_fingerprint.model_revision,
            model_fingerprint=actual_fingerprint,
            parameters_digest=work.parameters_fingerprint,
            input_digest_key_id=work.input_digest_key_id,
            input_digest=work.input_digest,
            output_digest=processed.actual_sha256,
            provider_request_id=str(work.lease.fence.attempt_id),
        )

    @staticmethod
    def _classification(
        error: BaseException,
    ) -> tuple[
        Literal["retryable", "non_retryable", "security_failure"], str
    ]:
        if isinstance(error, (VoiceProductSecurityError, UnsafeStoragePath, StorageRootChanged)):
            return "security_failure", "VOICE_PREVIEW_SECURITY_FAILURE"
        if isinstance(error, AdapterUnavailableError):
            return "retryable", "NANO_ADAPTER_UNAVAILABLE"
        if isinstance(error, (AudioFormatError, AudioQualityError)):
            return "non_retryable", "NANO_PREVIEW_AUDIO_INVALID"
        if isinstance(error, PublicationValidationError):
            return "non_retryable", "PREVIEW_PUBLICATION_INVALID"
        if isinstance(error, (StorageError, OSError)):
            return "retryable", "PREVIEW_STORAGE_TEMPORARY_FAILURE"
        if isinstance(
            error,
            (
                VoiceProductContractError,
                AudioPipelineError,
                InvalidNarrationState,
            ),
        ):
            return "non_retryable", "VOICE_PREVIEW_INPUT_INVALID"
        return "retryable", "VOICE_PREVIEW_UNEXPECTED_FAILURE"

    async def process(self, lease: JobLease) -> VoicePreviewWorkerOutcome:
        if lease.resource_fence is None:
            try:
                failure = await asyncio.to_thread(
                    self._repository.fail_claim,
                    lease,
                    classification="security_failure",
                    error_code="RESOURCE_FENCE_MISSING",
                )
            except JobFenceError:
                return VoicePreviewWorkerOutcome("stale", lease.fence.job_id)
            return VoicePreviewWorkerOutcome(
                failure.state,
                lease.fence.job_id,
                error_code="RESOURCE_FENCE_MISSING",
            )
        try:
            work = await asyncio.to_thread(
                self._repository.load_and_mark_running, lease
            )
        except JobFenceError:
            return VoicePreviewWorkerOutcome("stale", lease.fence.job_id)
        except BaseException as error:
            classification, code = self._classification(error)
            try:
                failure = await asyncio.to_thread(
                    self._repository.fail_claim,
                    lease,
                    classification=classification,
                    error_code=code,
                )
            except JobFenceError:
                return VoicePreviewWorkerOutcome("stale", lease.fence.job_id)
            return VoicePreviewWorkerOutcome(
                failure.state, lease.fence.job_id, error_code=code
            )
        try:
            initial_state = await asyncio.to_thread(
                self._repository.read_job_state, lease
            )
            if initial_state == "cancel_requested":
                await asyncio.to_thread(self._repository.acknowledge_cancel, work)
                return VoicePreviewWorkerOutcome(
                    "cancelled", lease.fence.job_id, work.preview_id
                )
            if initial_state != "running":
                raise JobFenceError("preview job left running state before synthesis")
            synthesis = await self._synthesize(work)
            final_state = await asyncio.to_thread(
                self._repository.read_job_state, lease
            )
            if final_state == "cancel_requested":
                await asyncio.to_thread(self._repository.acknowledge_cancel, work)
                return VoicePreviewWorkerOutcome(
                    "cancelled", lease.fence.job_id, work.preview_id
                )
            if final_state != "running":
                raise JobFenceError("preview job left running state before publication")
            prepared = await asyncio.to_thread(self._prepare, work, synthesis)
            await asyncio.to_thread(self._repository.publish, work, prepared)
            return VoicePreviewWorkerOutcome(
                "succeeded", lease.fence.job_id, work.preview_id
            )
        except JobFenceError:
            return VoicePreviewWorkerOutcome(
                "stale", lease.fence.job_id, work.preview_id
            )
        except asyncio.CancelledError:
            raise
        except BaseException as error:
            classification, code = self._classification(error)
            try:
                failure = await asyncio.to_thread(
                    self._repository.fail,
                    work,
                    classification=classification,
                    error_code=code,
                )
            except JobFenceError:
                return VoicePreviewWorkerOutcome(
                    "stale", lease.fence.job_id, work.preview_id
                )
            return VoicePreviewWorkerOutcome(
                failure.state,
                lease.fence.job_id,
                work.preview_id,
                error_code=code,
            )


class SqlAlchemyVoicePreviewRepository(
    _SqlAlchemyVoicePreviewRepositoryBase
):
    """Continuation kept separate so the processor can depend on the Protocol."""

    def read_job_state(self, lease: JobLease) -> str:
        return _transaction(
            self._session_factory,
            lambda session: self._job(session, lease, for_update=False).state,
        )

    def heartbeat_and_read_state(self, lease: JobLease) -> str:
        def operation(session: Session) -> str:
            job = self._job(session, lease, for_update=True)
            if job.state == "running":
                heartbeat_attempt(session, scope=self._scope, fence=lease.fence)
            return job.state

        return _transaction(self._session_factory, operation)

    def _append_model_run(
        self,
        session: Session,
        work: VoicePreviewWorkItem,
        *,
        result_classification: Literal[
            "success",
            "retryable_failure",
            "non_retryable_failure",
            "cancelled",
            "security_failure",
        ],
        prepared: PreparedVoicePreview | None = None,
    ) -> None:
        existing = session.scalar(
            select(ModelRunRecord).where(
                ModelRunRecord.attempt_id == work.lease.fence.attempt_id
            )
        )
        if existing is not None:
            raise InvalidNarrationState("preview attempt already has model-run evidence")
        success = result_classification == "success"
        if success != (prepared is not None):
            raise InvalidNarrationState("preview model-run success evidence is incomplete")
        session.add(
            ModelRunRecord(
                attempt_id=work.lease.fence.attempt_id,
                requested_provider_id=(
                    prepared.requested_provider_id
                    if prepared
                    else self._policy.requested_provider_id
                ),
                requested_model_id=(
                    prepared.requested_model_id
                    if prepared
                    else self._policy.requested_model_id
                ),
                requested_revision=(
                    prepared.requested_revision
                    if prepared
                    else self._policy.requested_revision
                ),
                actual_provider_id=(prepared.actual_provider_id if prepared else None),
                actual_model_id=(prepared.actual_model_id if prepared else None),
                actual_revision=(prepared.actual_revision if prepared else None),
                model_fingerprint=(prepared.model_fingerprint if prepared else None),
                parameters_digest=work.parameters_fingerprint,
                input_digest_key_id=work.input_digest_key_id,
                input_digest=work.input_digest,
                output_digest=(prepared.output_digest if prepared else None),
                duration_ms=(prepared.duration_ms if prepared else None),
                provider_request_id=(
                    prepared.provider_request_id
                    if prepared
                    else str(work.lease.fence.attempt_id)
                ),
                result_classification=result_classification,
            )
        )

    @staticmethod
    def _terminal_preview(
        preview: VoicePreview,
        *,
        status: Literal["failed", "cancelled"],
        at: datetime,
        failure_code: str | None,
    ) -> None:
        if preview.status not in {"queued", "running"}:
            raise InvalidNarrationState("voice preview cannot enter another terminal state")
        preview.status = status
        preview.preview_text = None
        preview.result_asset_id = None
        preview.completed_at = at
        preview.expires_at = None
        preview.failure_code = failure_code
        preview.updated_at = at

    def publish(
        self, work: VoicePreviewWorkItem, prepared: PreparedVoicePreview
    ) -> None:
        def operation(session: Session) -> None:
            if work.lease.resource_fence is None:
                raise VoiceProductSecurityError("Nano preview lease has no resource fence")
            context = lock_result_publish_fences(
                session,
                scope=self._scope,
                job_fence=work.lease.fence,
                resource_fence=work.lease.resource_fence,
            )
            job = self._job(session, work.lease, for_update=True)
            version = _required_version(
                session, work.profile_id, work.version_id, for_update=True
            )
            profile = _required_profile(session, work.profile_id, for_update=True)
            now = _db_now(session)
            rights = _required_active_rights(
                session, profile, version, at=now, for_update=True
            )
            preview = self._preview_for_job(session, job.id, for_update=True)
            reference: MediaAsset | None = None
            if version.source_type == "uploaded":
                link = _required_reference_link(session, version, for_update=False)
                reference = _required_reference_asset(
                    session, profile, version, link, for_update=True
                )
                expected_source = _reference_fingerprint(version, link, reference)
                voice_key = self._policy.voice_key
            elif version.source_type == "preset":
                preset = _required_official_preset(
                    version,
                    rights,
                    expected_model_fingerprint=(
                        self._policy.expected_model_fingerprint
                    ),
                )
                expected_source = str(
                    preset.provenance()["provenance_fingerprint_sha256"]
                )
                voice_key = preset.preset_id
            else:
                raise VoiceProductSecurityError(
                    "voice preview source type is unsupported"
                )
            version_parameters_fingerprint = (
                self._policy.parameters_fingerprint_for_version(version, voice_key)
            )
            if (
                preview.id != work.preview_id
                or preview.status != "running"
                or preview.preview_text is None
                or preview.rights_record_id != rights.id
                or preview.reference_asset_id
                != (reference.id if reference is not None else None)
                or preview.reference_fingerprint != work.reference_fingerprint
                or preview.reference_fingerprint != expected_source
                or preview.model_fingerprint != prepared.model_fingerprint
                or preview.parameters_fingerprint
                != version_parameters_fingerprint
                or preview.parameters_fingerprint != prepared.parameters_digest
                or prepared.output_digest != prepared.published.actual_sha256
            ):
                raise VoiceProductSecurityError("voice preview publication provenance changed")
            result_asset_id = _child_uuid(preview.id, "preview-result")
            expected_path = _canonical_asset_path(
                result_asset_id, prepared.output_digest, "wav"
            )
            if (
                prepared.published.asset_id != result_asset_id
                or prepared.published.relative_path != expected_path
            ):
                raise VoiceProductSecurityError("voice preview publication names another asset")
            existing_asset = session.get(MediaAsset, result_asset_id)
            if existing_asset is not None:
                raise InvalidNarrationState("voice preview result asset already exists")
            expires_at = now + timedelta(seconds=self._policy.preview_ttl_seconds)
            asset = MediaAsset(
                id=result_asset_id,
                owner_id=profile.owner_id,
                workspace_id=profile.workspace_id,
                novel_id=profile.novel_id,
                source_revision_id=None,
                kind="narration_voice_preview",
                asset_class="preview",
                mime_type="audio/wav",
                byte_size=prepared.published.byte_size,
                duration_ms=prepared.duration_ms,
                sample_rate=prepared.sample_rate_hz,
                channels=prepared.channels,
                storage_backend="local",
                state="ready",
                retention_policy="temporary_preview",
                checksum_algorithm="sha256",
                validation_json=prepared.audio_validation,
                verified_at=now,
                last_accessed_at=None,
                expires_at=expires_at,
                deleted_at=None,
                gc_generation=0,
                gc_marked_at=None,
                storage_path=prepared.published.relative_path,
                content_hash=prepared.output_digest,
                metadata_json={
                    "schema_version": VOICE_PRODUCT_SCHEMA_VERSION,
                    "preview_id": str(preview.id),
                    "model_fingerprint": prepared.model_fingerprint,
                },
                created_at=now,
            )
            session.add(asset)
            self._append_model_run(
                session, work, result_classification="success", prepared=prepared
            )
            preview.status = "ready"
            preview.preview_text = None
            preview.result_asset_id = asset.id
            preview.completed_at = now
            preview.expires_at = expires_at
            preview.failure_code = None
            preview.updated_at = now
            if version.state == "draft":
                version.state = "preview_ready"
            elif version.state not in {"preview_ready", "locked"}:
                raise InvalidNarrationState("voice version cannot accept preview success")
            release_active_job_assets_in_session(session, job_id=job.id)
            complete_attempt(
                session,
                scope=self._scope,
                fence=work.lease.fence,
                actual_result_digest=prepared.output_digest,
                publication_context=context,
            )
            session.flush()

        _transaction(self._session_factory, operation)

    def fail(
        self,
        work: VoicePreviewWorkItem,
        *,
        classification: Literal["retryable", "non_retryable", "security_failure"],
        error_code: str,
    ) -> FailureResult:
        def operation(session: Session) -> FailureResult:
            heartbeat_attempt(session, scope=self._scope, fence=work.lease.fence)
            self._job(session, work.lease, for_update=True)
            preview = self._preview_for_job(
                session, work.lease.fence.job_id, for_update=True
            )
            self._append_model_run(
                session,
                work,
                result_classification={
                    "retryable": "retryable_failure",
                    "non_retryable": "non_retryable_failure",
                    "security_failure": "security_failure",
                }[classification],  # type: ignore[arg-type]
            )
            result = fail_attempt(
                session,
                scope=self._scope,
                fence=work.lease.fence,
                classification=classification,
                error_code=error_code,
            )
            if result.state in {"failed", "dead_letter"}:
                now = _db_now(session)
                self._terminal_preview(
                    preview, status="failed", at=now, failure_code=error_code
                )
                release_active_job_assets_in_session(
                    session, job_id=work.lease.fence.job_id
                )
            session.flush()
            return result

        return _transaction(self._session_factory, operation)

    def fail_claim(
        self,
        lease: JobLease,
        *,
        classification: Literal["retryable", "non_retryable", "security_failure"],
        error_code: str,
    ) -> FailureResult:
        def operation(session: Session) -> FailureResult:
            self._job(session, lease, for_update=True)
            preview = self._preview_for_job(session, lease.fence.job_id, for_update=True)
            result = fail_attempt(
                session,
                scope=self._scope,
                fence=lease.fence,
                classification=classification,
                error_code=error_code,
            )
            if result.state in {"failed", "dead_letter"}:
                self._terminal_preview(
                    preview,
                    status="failed",
                    at=_db_now(session),
                    failure_code=error_code,
                )
                release_active_job_assets_in_session(
                    session, job_id=lease.fence.job_id
                )
            session.flush()
            return result

        return _transaction(self._session_factory, operation)

    def acknowledge_cancel(self, work: VoicePreviewWorkItem) -> None:
        def operation(session: Session) -> None:
            self._job(session, work.lease, for_update=True)
            preview = self._preview_for_job(
                session, work.lease.fence.job_id, for_update=True
            )
            self._append_model_run(
                session, work, result_classification="cancelled"
            )
            self._terminal_preview(
                preview, status="cancelled", at=_db_now(session), failure_code=None
            )
            release_active_job_assets_in_session(
                session, job_id=work.lease.fence.job_id
            )
            acknowledge_cancel(
                session, scope=self._scope, fence=work.lease.fence
            )
            session.flush()

        _transaction(self._session_factory, operation)

    def terminalize_job_in_session(
        self,
        session: Session,
        *,
        job_id: UUID,
    ) -> bool:
        """Join an out-of-band job terminal transition in its exact tx.

        The generic cancellation/failure path must mutate the job, call this
        method, and commit once.  Calling it after a terminal job commit is too
        late: the database guard correctly rejects terminal jobs that still
        retain private preview text or active input assets.
        """

        job = session.scalar(
            select(BackgroundJob)
            .where(
                BackgroundJob.id == job_id,
                BackgroundJob.owner_id == self._scope.owner_id,
                BackgroundJob.workspace_id == self._scope.workspace_id,
                BackgroundJob.job_kind == VOICE_PREVIEW_JOB_KIND,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if job is None:
            raise NarrationNotFound("voice preview job not found")
        preview = self._preview_for_job(session, job.id, for_update=True)
        if preview.status not in {"queued", "running"}:
            return False
        if job.state == "cancelled":
            self._terminal_preview(
                preview,
                status="cancelled",
                at=_db_now(session),
                failure_code=None,
            )
        elif job.state in {"failed", "dead_letter"}:
            self._terminal_preview(
                preview,
                status="failed",
                at=_db_now(session),
                failure_code=job.error_code or "PREVIEW_JOB_FAILED",
            )
        else:
            return False
        release_active_job_assets_in_session(session, job_id=job.id)
        session.flush()
        return True


def resolve_voice_preview_media(
    session: Session,
    preview_id: UUID,
    asset_id: UUID,
) -> MediaAsset:
    """Resolve one unexpired preview asset for the dedicated media route.

    The route must still invoke the shared physical-media read planner after
    this authorization/provenance check.
    """

    scope = NarrationRequestScope.fixed_local()
    now = _db_now(session)
    preview = session.scalar(
        select(VoicePreview).where(
            VoicePreview.id == preview_id,
            VoicePreview.owner_id == scope.owner_id,
            VoicePreview.workspace_id == scope.workspace_id,
        )
    )
    if (
        preview is None
        or preview.status != "ready"
        or preview.result_asset_id != asset_id
        or preview.expires_at is None
        or preview.expires_at <= now
        or preview.preview_text is not None
    ):
        raise VoicePreviewNotFound("voice preview media is unavailable")
    asset = session.get(MediaAsset, asset_id)
    if (
        asset is None
        or asset.owner_id != preview.owner_id
        or asset.workspace_id != preview.workspace_id
        or asset.novel_id != preview.novel_id
        or asset.kind != "narration_voice_preview"
        or asset.asset_class != "preview"
        or asset.retention_policy != "temporary_preview"
        or asset.state != "ready"
        or asset.expires_at != preview.expires_at
        or asset.mime_type != "audio/wav"
        or asset.byte_size is None
        or asset.byte_size <= 0
        or asset.duration_ms is None
        or asset.duration_ms <= 0
        or asset.verified_at is None
        or _SHA256.fullmatch(asset.content_hash) is None
        or asset.storage_path
        != _canonical_asset_path(asset.id, asset.content_hash, "wav")
    ):
        raise VoicePreviewNotFound("voice preview media is unavailable")
    return asset


__all__ = [
    "PreparedVoicePreview",
    "SqlAlchemyVoiceActionReceiptPort",
    "SqlAlchemyVoicePreviewRepository",
    "VOICE_LOCK_OPERATION",
    "VOICE_PREVIEW_JOB_KIND",
    "VOICE_PREVIEW_OPERATION",
    "VOICE_PROFILE_CREATE_OPERATION",
    "VOICE_UPLOAD_OPERATION",
    "VoicePreviewNotFound",
    "VoicePreviewPolicy",
    "VoicePreviewProcessor",
    "VoicePreviewRepository",
    "VoicePreviewWorkItem",
    "VoicePreviewWorkerOutcome",
    "VoiceProductContractError",
    "VoiceProductError",
    "VoiceProductSecurityError",
    "VoiceProductService",
    "VoiceReferenceMedia",
    "resolve_voice_preview_media",
]
