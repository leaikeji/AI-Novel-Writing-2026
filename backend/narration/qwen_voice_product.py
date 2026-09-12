"""Qwen-only private voice creation, preview, and locking.

The HTTP-facing service keeps normalization, Qwen inference, and immutable
media publication outside database transactions.  The repository uses short,
fenced transactions and stores enough content identity to replay safely after
a process restart.  Private text is never included in errors or logs.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta
import hashlib
import hmac
from io import BytesIO
import re
from typing import Callable, Final, Literal, Protocol, TypeVar
import unicodedata
from uuid import UUID, uuid5
import wave

from sqlalchemy import func, select
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
from .audio_pipeline import (
    AudioFormatError,
    AudioPipelineError,
    AudioQualityError,
    ProcessedPcmWav,
    process_provider_synthesis_wav,
)
from .contracts import (
    NarrationRequestScope,
    ReferenceAudioInput,
    TTSProviderId,
    TTSVoiceKind,
    TTSVoicePreparationRequest,
    TTSVoicePreparationResult,
    require_mandarin_language,
    require_mandarin_voice_design,
)
from .digest_keyring import (
    DigestKeyring,
    historical_private_text_digest,
    private_text_digest,
)
from .fingerprints import tts_model_identity_sha256
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
from .media import release_active_job_assets_in_session
from .providers.base import TTSProviderError
from .services import (
    IdempotencyConflict,
    InvalidNarrationState,
    NarrationCasConflict,
    NarrationNotFound,
    NarrationScopeMismatch,
    NarrationServiceError,
    SqlAlchemyNarrationStore,
    VoiceRightsUnavailable,
    VoiceSourceUnavailable,
    canonical_sha256,
)
from .storage import (
    NarrationStorage,
    PublicationValidationError,
    PublishedFile,
    StorageError,
    StorageRootChanged,
    UnsafeStoragePath,
)
from .tts_execution import TTSExecutionService
from .voice_media import (
    NormalizedReferenceAudio,
    ReferenceAudioInvalid,
    ReferenceAudioQualityRejected,
    ReferenceToolchainUnavailable,
)
from .voice_receipts import (
    complete_voice_action_receipt,
    database_now,
    reserve_voice_action_receipt,
    stable_voice_action_uuid,
)
from .voices import (
    ParsedUploadedVoice,
    VoiceProfileNotFound,
    VoiceUploadValidationError,
    VoiceVersionNotFound,
    voice_preview_media_link,
    voice_profile_resource,
)


VOICE_UPLOAD_OPERATION: Final = "create_uploaded_voice_version"
VOICE_DESIGN_OPERATION: Final = "create_designed_voice_version"
VOICE_PREVIEW_OPERATION: Final = "create_voice_preview"
VOICE_LOCK_OPERATION: Final = "lock_voice_profile"
VOICE_PREVIEW_JOB_KIND: Final = "narration.voice_preview"
VOICE_PREVIEW_RESOURCE_CLASS: Final = "qwen-tts"
VOICE_PRODUCT_SCHEMA_VERSION: Final = "qwen-tts-private-voice/1"
VOICE_PARAMETERS_SCHEMA_VERSION: Final = "qwen-tts-voice/1"
VOICE_DESIGN_POLICY_VERSION: Final = "qwen-tts-mandarin-only/1"
VOICE_PREVIEW_TEXT_PURPOSE: Final = "voice-preview"
VOICE_DESCRIPTION_PURPOSE: Final = "voice-design-description"
VOICE_MODEL_INPUT_PURPOSE: Final = "qwen-voice-preview-input"
VOICE_REFERENCE_PROVIDER_ID: Final = "durable-reference"
VOICE_PRODUCT_PROVIDER_ID: Final = "qwen-tts"
VOICE_LANGUAGE: Final = "zh-CN"
VOICE_DESIGN_ANCHOR_TEXT: Final = (
    "晨光落在窗前，我用自然清晰的普通话，为你讲述这个故事。"
)
VOICE_DESIGN_MODEL_ID: Final = (
    "mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-bf16"
)
VOICE_DESIGN_MODEL_REVISION: Final = "7d3824abff87e49756bb0f83fb5411de75d160c4"
VOICE_DESIGN_ARTIFACT_SHA256: Final = (
    "2bb6d9c5b17d293701c6b77fe848548f91c29137b5ace8b8c9afa5f1e7cd8ff6"
)
VOICE_BASE_MODEL_ID: Final = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit"
VOICE_BASE_MODEL_REVISION: Final = "e7dd0585652209fa0d7783659aad4e8a324de11c"
VOICE_BASE_ARTIFACT_SHA256: Final = (
    "1ce5152917c093872ae50a96e3908e065bf9ece2c5b192cd54ee346a09027094"
)
VOICE_BASE_PRODUCT_FINGERPRINT: Final = canonical_sha256(
    {
        "schema_version": VOICE_PRODUCT_SCHEMA_VERSION,
        "provider_id": TTSProviderId.LOCAL_QWEN3_TTS.value,
        "model_id": VOICE_BASE_MODEL_ID,
        "model_revision": VOICE_BASE_MODEL_REVISION,
        "artifact_tree_sha256": VOICE_BASE_ARTIFACT_SHA256,
        "quantization": "8bit",
    }
)
MAX_REFERENCE_MEDIA_BYTES: Final = 25 * 1024 * 1024
MAX_PREVIEW_MEDIA_BYTES: Final = 32 * 1024 * 1024
DEFAULT_PREVIEW_TTL_SECONDS: Final = 24 * 60 * 60
DEFAULT_VOICE_SEED: Final = 1234

_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_T = TypeVar("_T")
SessionFactory = Callable[[], Session]
ReferenceNormalizer = Callable[[ParsedUploadedVoice], NormalizedReferenceAudio]


class QwenVoiceProductError(NarrationServiceError):
    """Safe base failure for the Qwen private-voice product."""


class QwenVoiceProductSecurityError(QwenVoiceProductError):
    pass


class QwenVoiceProductContractError(QwenVoiceProductError):
    pass


class QwenVoicePreviewNotFound(NarrationNotFound):
    pass


@dataclass(frozen=True, slots=True)
class QwenVoiceProductPolicy:
    actor: str = "local-owner"
    seed: int = DEFAULT_VOICE_SEED
    preview_ttl_seconds: int = DEFAULT_PREVIEW_TTL_SECONDS
    heartbeat_seconds: float = 30.0
    max_reference_bytes: int = MAX_REFERENCE_MEDIA_BYTES

    def validate(self) -> None:
        if (
            type(self.actor) is not str
            or not self.actor
            or self.actor != self.actor.strip()
            or len(self.actor) > 120
        ):
            raise ValueError("Qwen voice actor is invalid")
        if type(self.seed) is not int or not 0 <= self.seed <= 2**63 - 1:
            raise ValueError("Qwen voice seed is invalid")
        if (
            type(self.preview_ttl_seconds) is not int
            or not 60 <= self.preview_ttl_seconds <= 7 * 86_400
        ):
            raise ValueError("Qwen voice preview expiry is invalid")
        if not isinstance(self.heartbeat_seconds, (int, float)) or not (
            0.01 <= float(self.heartbeat_seconds) <= 1_800
        ):
            raise ValueError("Qwen voice heartbeat is invalid")
        if (
            type(self.max_reference_bytes) is not int
            or not 1 <= self.max_reference_bytes <= 256 * 1024 * 1024
        ):
            raise ValueError("Qwen voice reference bound is invalid")


@dataclass(frozen=True, slots=True)
class QwenReferenceMedia:
    asset_id: UUID
    relative_path: str = field(repr=False)
    actual_sha256: str
    byte_size: int
    content_type: str
    reference_text: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class QwenVoicePreviewWorkItem:
    lease: JobLease
    preview_id: UUID
    profile_id: UUID
    version_id: UUID
    rights_record_id: UUID
    novel_id: UUID
    preview_text: str = field(repr=False)
    description: str | None = field(default=None, repr=False)
    seed: int = DEFAULT_VOICE_SEED
    request_fingerprint: str = ""
    parameters_fingerprint: str = ""
    input_digest_key_id: str = ""
    input_digest: str = ""
    reference: QwenReferenceMedia | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class PreparedQwenVoiceAudio:
    published: PublishedFile
    processed: ProcessedPcmWav = field(repr=False)
    model_identity: object
    model_fingerprint: str
    requested_model_id: str
    requested_revision: str
    provider_request_id: str


@dataclass(frozen=True, slots=True)
class QwenVoicePreviewWorkerOutcome:
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


class QwenVoicePreviewRepository(Protocol):
    def load_and_mark_running(self, lease: JobLease) -> QwenVoicePreviewWorkItem: ...

    def read_job_state(self, lease: JobLease) -> str: ...

    def heartbeat_and_read_state(self, lease: JobLease) -> str: ...

    def publish_generated_reference(
        self,
        work: QwenVoicePreviewWorkItem,
        prepared: PreparedQwenVoiceAudio,
    ) -> QwenReferenceMedia: ...

    def publish_preview(
        self,
        work: QwenVoicePreviewWorkItem,
        reference: QwenReferenceMedia,
        prepared: PreparedQwenVoiceAudio,
    ) -> None: ...

    def fail(
        self,
        work: QwenVoicePreviewWorkItem,
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

    def acknowledge_cancel(self, work: QwenVoicePreviewWorkItem) -> None: ...


def _stable_uuid(operation: str, key: str) -> UUID:
    return stable_voice_action_uuid(operation, key)


def _child_uuid(parent: UUID, label: str) -> UUID:
    return uuid5(parent, f"{VOICE_PRODUCT_SCHEMA_VERSION}/{label}")


def _canonical_asset_path(asset_id: UUID, digest: str, extension: str) -> str:
    return f"assets/{asset_id.hex[:2]}/{asset_id.hex}/{digest}.{extension}"


def _required_key(value: str) -> str:
    if type(value) is not str or _IDEMPOTENCY_KEY.fullmatch(value) is None:
        raise QwenVoiceProductContractError("idempotency key is invalid")
    return value


def _db_now(session: Session) -> datetime:
    return database_now(session)


def _transaction(factory: SessionFactory, operation: Callable[[Session], _T]) -> _T:
    with factory() as session:
        try:
            value = operation(session)
            session.commit()
            return value
        except BaseException:
            session.rollback()
            raise


def _required_profile(
    session: Session, profile_id: UUID, *, for_update: bool
) -> VoiceProfile:
    statement = select(VoiceProfile).where(VoiceProfile.id == profile_id)
    if for_update:
        statement = statement.with_for_update()
    profile = session.scalar(statement.execution_options(populate_existing=True))
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
        statement = statement.with_for_update()
    version = session.scalar(statement.execution_options(populate_existing=True))
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
        statement = statement.with_for_update()
    rights = session.scalar(statement.execution_options(populate_existing=True))
    expected = {
        "uploaded": "user_upload",
        "generated": "qwen_synthetic_design",
    }.get(version.source_type)
    if (
        rights is None
        or expected is None
        or rights.source_kind != expected
        or rights.owner_id != profile.owner_id
        or rights.workspace_id != profile.workspace_id
        or rights.novel_id not in {None, profile.novel_id}
    ):
        raise VoiceRightsUnavailable("voice rights evidence is unavailable")
    if profile.status in {"archived", "unavailable"}:
        raise VoiceRightsUnavailable("voice profile is unavailable")
    if rights.expires_at is not None and rights.expires_at <= at:
        raise VoiceRightsUnavailable("voice rights expired")
    events = session.scalars(
        select(VoiceRightsEvent).where(
            VoiceRightsEvent.rights_record_id == rights.id
        )
    )
    event_types = {event.event_type for event in events}
    if "confirmed" not in event_types or event_types & {
        "revoked",
        "expired",
        "review_blocked",
    }:
        raise VoiceRightsUnavailable("voice rights have negative history")
    if not rights.voice_cloning:
        raise VoiceRightsUnavailable("voice source lacks cloning permission")
    return rights


def _reference_asset(
    session: Session,
    profile: VoiceProfile,
    version: VoiceProfileVersion,
    *,
    for_update: bool,
) -> MediaAsset | None:
    if version.reference_asset_id is None:
        return None
    statement = select(MediaAsset).where(MediaAsset.id == version.reference_asset_id)
    if for_update:
        statement = statement.with_for_update()
    asset = session.scalar(statement.execution_options(populate_existing=True))
    if (
        asset is None
        or asset.owner_id != profile.owner_id
        or asset.workspace_id != profile.workspace_id
        or asset.novel_id != profile.novel_id
        or asset.kind != "narration_voice_reference"
        or asset.asset_class != "voice_reference"
        or asset.state != "ready"
        or asset.mime_type != "audio/wav"
        or not asset.byte_size
        or not asset.duration_ms
        or asset.checksum_algorithm != "sha256"
        or _SHA256.fullmatch(asset.content_hash) is None
        or asset.verified_at is None
    ):
        raise QwenVoiceProductSecurityError("voice reference media is invalid")
    return asset


def _reference_text(version: VoiceProfileVersion) -> str:
    parameters = version.parameters_json
    value = parameters.get("reference_text") if type(parameters) is dict else None
    if (
        type(value) is not str
        or not value.strip()
        or value != unicodedata.normalize("NFC", value)
        or len(value) > 500
    ):
        raise QwenVoiceProductSecurityError("voice reference text is invalid")
    return value


def _reference_media(asset: MediaAsset, version: VoiceProfileVersion) -> QwenReferenceMedia:
    return QwenReferenceMedia(
        asset_id=asset.id,
        relative_path=asset.storage_path,
        actual_sha256=asset.content_hash,
        byte_size=asset.byte_size,
        content_type=asset.mime_type,
        reference_text=_reference_text(version),
    )


def _version_resource(
    session: Session,
    profile: VoiceProfile,
    version_id: UUID,
    *,
    at: datetime,
) -> wire.VoiceProfileVersionResource:
    resource = voice_profile_resource(SqlAlchemyNarrationStore(session), profile, at=at)
    try:
        return next(item for item in resource.versions if item.version_id == version_id)
    except StopIteration as error:
        raise InvalidNarrationState("voice version projection is absent") from error


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
    asset = None
    failure_code = None
    expires_at = preview.expires_at
    if status is wire.VoicePreviewStatus.READY:
        if expires_at is None or expires_at <= at:
            status = wire.VoicePreviewStatus.UNAVAILABLE
            failure_code = wire.NarrationErrorCode.PREVIEW_UNAVAILABLE
        else:
            profile = _required_profile(session, preview.profile_id, for_update=False)
            asset = voice_preview_media_link(
                SqlAlchemyNarrationStore(session), profile, preview.result_asset_id
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
            if status in {wire.VoicePreviewStatus.QUEUED, wire.VoicePreviewStatus.RUNNING}
            else None
        ),
        asset=asset,
        temporary=True,
        expires_at=expires_at,
        failure_code=failure_code,
    )


def _ready_media_row(
    *,
    asset_id: UUID,
    profile: VoiceProfile,
    kind: str,
    asset_class: str,
    retention_policy: str,
    publication: PublishedFile,
    duration_ms: int,
    sample_rate: int,
    channels: int,
    validation_json: dict[str, object],
    metadata_json: dict[str, object],
    at: datetime,
    expires_at: datetime | None = None,
) -> MediaAsset:
    return MediaAsset(
        id=asset_id,
        owner_id=profile.owner_id,
        workspace_id=profile.workspace_id,
        novel_id=profile.novel_id,
        source_revision_id=None,
        kind=kind,
        asset_class=asset_class,
        mime_type="audio/wav",
        byte_size=publication.byte_size,
        duration_ms=duration_ms,
        sample_rate=sample_rate,
        channels=channels,
        storage_backend="local",
        state="ready",
        retention_policy=retention_policy,
        checksum_algorithm="sha256",
        validation_json=validation_json,
        verified_at=at,
        last_accessed_at=None,
        expires_at=expires_at,
        deleted_at=None,
        gc_generation=0,
        gc_marked_at=None,
        storage_path=publication.relative_path,
        content_hash=publication.actual_sha256,
        metadata_json=metadata_json,
        created_at=at,
    )


class SqlAlchemyQwenVoiceProductRepository:
    """Short-transaction persistence for the Qwen voice product."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        digest_keyring: DigestKeyring,
        policy: QwenVoiceProductPolicy,
    ) -> None:
        if not callable(session_factory):
            raise TypeError("Qwen voice repository requires a session factory")
        if type(digest_keyring) is not DigestKeyring:
            raise TypeError("Qwen voice repository requires a digest keyring")
        policy.validate()
        self._session_factory = session_factory
        self._digest_keyring = digest_keyring
        self._policy = policy
        self._scope = NarrationRequestScope.fixed_local()

    def _tx(self, operation: Callable[[Session], _T]) -> _T:
        return _transaction(self._session_factory, operation)

    @staticmethod
    def _max_version_number(session: Session, profile_id: UUID) -> int:
        return int(
            session.scalar(
                select(func.max(VoiceProfileVersion.version_number)).where(
                    VoiceProfileVersion.profile_id == profile_id
                )
            )
            or 0
        )

    def create_uploaded_version(
        self,
        *,
        profile_id: UUID,
        parsed: ParsedUploadedVoice,
        normalized: NormalizedReferenceAudio,
        source_publication: PublishedFile,
        reference_publication: PublishedFile,
        idempotency_key: str,
        request_hash: str,
        version_id: UUID,
        source_asset_id: UUID,
        reference_asset_id: UUID,
    ) -> wire.VoiceProfileVersionResource:
        def operation(session: Session) -> wire.VoiceProfileVersionResource:
            profile = _required_profile(session, profile_id, for_update=True)
            now = _db_now(session)
            receipt = reserve_voice_action_receipt(
                session,
                operation=VOICE_UPLOAD_OPERATION,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                resource_id=version_id,
            )
            existing = session.get(VoiceProfileVersion, version_id)
            if receipt.state == "completed":
                if existing is None or existing.profile_id != profile.id:
                    raise InvalidNarrationState(
                        "completed upload receipt has no matching voice version"
                    )
                return _version_resource(session, profile, existing.id, at=now)
            if existing is not None:
                raise InvalidNarrationState("reserved upload names an existing version")
            if profile.version != parsed.metadata.expected_profile_version:
                raise NarrationCasConflict("voice profile version changed")
            if profile.status in {"archived", "unavailable"}:
                raise InvalidNarrationState("voice profile cannot accept a new source")
            if parsed.metadata.language != VOICE_LANGUAGE:
                raise QwenVoiceProductContractError("voice language must be zh-CN")
            source_extension = "wav" if parsed.mime_type == "audio/wav" else "flac"
            expected_source_path = _canonical_asset_path(
                source_asset_id, parsed.checksum_sha256, source_extension
            )
            expected_reference_path = _canonical_asset_path(
                reference_asset_id, normalized.normalized_sha256, "wav"
            )
            if (
                source_publication.asset_id != source_asset_id
                or source_publication.relative_path != expected_source_path
                or source_publication.actual_sha256 != parsed.checksum_sha256
                or source_publication.byte_size != parsed.byte_size
                or reference_publication.asset_id != reference_asset_id
                or reference_publication.relative_path != expected_reference_path
                or reference_publication.actual_sha256 != normalized.normalized_sha256
                or reference_publication.byte_size != normalized.normalized_byte_size
            ):
                raise QwenVoiceProductSecurityError(
                    "uploaded voice publication identity changed"
                )
            if session.get(MediaAsset, source_asset_id) is not None or session.get(
                MediaAsset, reference_asset_id
            ) is not None:
                raise InvalidNarrationState("uploaded voice asset identity is occupied")
            filename_digest = hashlib.sha256(parsed.filename.encode("utf-8")).hexdigest()
            source = MediaAsset(
                id=source_asset_id,
                owner_id=profile.owner_id,
                workspace_id=profile.workspace_id,
                novel_id=profile.novel_id,
                source_revision_id=None,
                kind="narration_voice_reference_source",
                asset_class="source",
                mime_type=parsed.mime_type,
                byte_size=parsed.byte_size,
                duration_ms=normalized.source.duration_ms,
                sample_rate=normalized.source.sample_rate_hz,
                channels=normalized.source.channels,
                storage_backend="local",
                state="ready",
                retention_policy="uploaded_original",
                checksum_algorithm="sha256",
                validation_json={
                    "schema_version": VOICE_PRODUCT_SCHEMA_VERSION,
                    "source": asdict(normalized.source),
                    "checks": {
                        "fully_decoded": True,
                        "declared_sha256_matches": True,
                    },
                },
                verified_at=now,
                last_accessed_at=None,
                expires_at=None,
                deleted_at=None,
                gc_generation=0,
                gc_marked_at=None,
                storage_path=source_publication.relative_path,
                content_hash=source_publication.actual_sha256,
                metadata_json={
                    "schema_version": VOICE_PRODUCT_SCHEMA_VERSION,
                    "filename_sha256": filename_digest,
                },
                created_at=now,
            )
            reference = _ready_media_row(
                asset_id=reference_asset_id,
                profile=profile,
                kind="narration_voice_reference",
                asset_class="voice_reference",
                retention_policy="locked_voice",
                publication=reference_publication,
                duration_ms=normalized.duration_ms,
                sample_rate=normalized.sample_rate_hz,
                channels=normalized.channels,
                validation_json=normalized.validation_evidence,
                metadata_json={
                    "schema_version": VOICE_PRODUCT_SCHEMA_VERSION,
                    "source_asset_id": str(source_asset_id),
                },
                at=now,
            )
            rights_request = parsed.metadata.rights
            rights_id = _child_uuid(version_id, "rights")
            rights = VoiceRightsRecord(
                id=rights_id,
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
                confirmed_actor=self._policy.actor,
                confirmed_at=now,
                expires_at=None,
                risk_flags_json=[],
            )
            event = VoiceRightsEvent(
                id=_child_uuid(version_id, "rights-confirmed"),
                rights_record_id=rights.id,
                event_key=f"upload-confirmed:{version_id.hex}",
                event_type="confirmed",
                actor=self._policy.actor,
                reason_code=None,
                occurred_at=now,
            )
            validation_fingerprint = canonical_sha256(
                normalized.validation_evidence
            )
            parameters = {
                "schema_version": VOICE_PARAMETERS_SCHEMA_VERSION,
                "voice_kind": TTSVoiceKind.REFERENCE_CLONE.value,
                "provider_voice_id": VOICE_REFERENCE_PROVIDER_ID,
                "reference_text": unicodedata.normalize(
                    "NFC", parsed.metadata.reference_text
                ),
                "reference_policy_version": VOICE_PRODUCT_SCHEMA_VERSION,
                "normalization_fingerprint": normalized.normalization_fingerprint,
                "validation_fingerprint": validation_fingerprint,
            }
            version = VoiceProfileVersion(
                id=version_id,
                profile_id=profile.id,
                owner_id=profile.owner_id,
                workspace_id=profile.workspace_id,
                version_number=self._max_version_number(session, profile.id) + 1,
                source_type="uploaded",
                state="draft",
                provider_id=VOICE_PRODUCT_PROVIDER_ID,
                model_id=VOICE_BASE_MODEL_ID,
                model_revision=VOICE_BASE_MODEL_REVISION,
                preset_key=None,
                reference_asset_id=reference.id,
                preview_asset_id=None,
                model_run_id=None,
                rights_record_id=rights.id,
                description_digest_key_id=None,
                description_digest=None,
                language=VOICE_LANGUAGE,
                seed=self._policy.seed,
                parameters_json=parameters,
                fingerprint=canonical_sha256(
                    {
                        "schema_version": VOICE_PRODUCT_SCHEMA_VERSION,
                        "profile_id": str(profile.id),
                        "version_id": str(version_id),
                        "source_type": "uploaded",
                        "reference_sha256": normalized.normalized_sha256,
                        "reference_text_sha256": hashlib.sha256(
                            parameters["reference_text"].encode("utf-8")
                        ).hexdigest(),
                        "rights_record_id": str(rights.id),
                        "model_id": VOICE_BASE_MODEL_ID,
                        "model_revision": VOICE_BASE_MODEL_REVISION,
                    }
                ),
                quality_state="pending",
                activation_basis="preview_confirmed",
                validation_basis="pending",
                locked_actor=None,
                locked_at=None,
                created_at=now,
            )
            link = VoiceReferenceAssetLink(
                id=_child_uuid(version_id, "reference-link"),
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
            session.add_all([source, reference, rights])
            session.flush()
            session.add_all([event, version, link])
            profile.version += 1
            profile.updated_at = now
            complete_voice_action_receipt(session, receipt.row_id, at=now)
            session.flush()
            return _version_resource(session, profile, version.id, at=now)

        return self._tx(operation)

    def _job(
        self, session: Session, lease: JobLease, *, for_update: bool
    ) -> BackgroundJob:
        statement = select(BackgroundJob).where(
            BackgroundJob.id == lease.fence.job_id,
            BackgroundJob.owner_id == self._scope.owner_id,
            BackgroundJob.workspace_id == self._scope.workspace_id,
        )
        if for_update:
            statement = statement.with_for_update()
        job = session.scalar(statement.execution_options(populate_existing=True))
        if (
            job is None
            or job.job_kind != VOICE_PREVIEW_JOB_KIND
            or job.resource_class != VOICE_PREVIEW_RESOURCE_CLASS
        ):
            raise QwenVoiceProductSecurityError(
                "worker claim is not a Qwen voice preview job"
            )
        return job

    @staticmethod
    def _preview_for_job(
        session: Session, job_id: UUID, *, for_update: bool
    ) -> VoicePreview:
        statement = select(VoicePreview).where(VoicePreview.job_id == job_id)
        if for_update:
            statement = statement.with_for_update()
        preview = session.scalar(statement.execution_options(populate_existing=True))
        if preview is None:
            raise InvalidNarrationState("voice preview job has no product resource")
        return preview

    def _validated_work_rows(
        self,
        session: Session,
        lease: JobLease,
        *,
        for_update: bool,
    ) -> tuple[
        BackgroundJob,
        VoicePreview,
        VoiceProfileVersion,
        VoiceProfile,
        VoiceRightsRecord,
    ]:
        job = self._job(session, lease, for_update=for_update)
        preview_hint = self._preview_for_job(session, job.id, for_update=False)
        version = _required_version(
            session,
            preview_hint.profile_id,
            preview_hint.version_id,
            for_update=for_update,
        )
        profile = _required_profile(
            session, preview_hint.profile_id, for_update=for_update
        )
        rights = _required_active_rights(
            session,
            profile,
            version,
            at=_db_now(session),
            for_update=for_update,
        )
        preview = self._preview_for_job(session, job.id, for_update=for_update)
        if (
            preview.id != preview_hint.id
            or preview.profile_id != profile.id
            or preview.version_id != version.id
            or preview.rights_record_id != rights.id
            or preview.novel_id != profile.novel_id
            or preview.novel_id != job.novel_id
            or preview.owner_id != job.owner_id
            or preview.workspace_id != job.workspace_id
            or profile.novel_id is None
            or version.language != VOICE_LANGUAGE
        ):
            raise QwenVoiceProductSecurityError(
                "voice preview job provenance changed"
            )
        return job, preview, version, profile, rights

    def load_and_mark_running(self, lease: JobLease) -> QwenVoicePreviewWorkItem:
        def operation(session: Session) -> QwenVoicePreviewWorkItem:
            heartbeat_attempt(session, scope=self._scope, fence=lease.fence)
            job, preview, version, profile, _rights = self._validated_work_rows(
                session, lease, for_update=True
            )
            if preview.status not in {"queued", "running"} or preview.preview_text is None:
                raise InvalidNarrationState("voice preview is already terminal")
            key = self._digest_keyring.require(preview.preview_text_digest_key_id)
            expected_text_digest = historical_private_text_digest(
                key,
                purpose=VOICE_PREVIEW_TEXT_PURPOSE,
                text=preview.preview_text,
            )
            if not hmac.compare_digest(
                expected_text_digest, preview.preview_text_digest
            ):
                raise QwenVoiceProductSecurityError(
                    "private preview text digest changed"
                )
            reference_asset = _reference_asset(
                session, profile, version, for_update=True
            )
            description: str | None = None
            if reference_asset is None:
                if version.source_type != "generated":
                    raise QwenVoiceProductSecurityError(
                        "voice preview reference disappeared"
                    )
                parameters = version.parameters_json
                description = (
                    parameters.get("design_description")
                    if type(parameters) is dict
                    else None
                )
                if type(description) is not str:
                    raise QwenVoiceProductSecurityError(
                        "designed voice description disappeared"
                    )
                require_mandarin_voice_design(description)
                if (
                    version.description_digest_key_id is None
                    or version.description_digest is None
                ):
                    raise QwenVoiceProductSecurityError(
                        "designed voice description digest is absent"
                    )
                description_key = self._digest_keyring.require(
                    version.description_digest_key_id
                )
                expected_description_digest = historical_private_text_digest(
                    description_key,
                    purpose=VOICE_DESCRIPTION_PURPOSE,
                    text=description,
                )
                if not hmac.compare_digest(
                    expected_description_digest, version.description_digest
                ):
                    raise QwenVoiceProductSecurityError(
                        "designed voice description digest changed"
                    )
                expected_reference_fingerprint = canonical_sha256(
                    {
                        "state": "design_pending",
                        "version_fingerprint": version.fingerprint,
                        "description_digest": version.description_digest,
                    }
                )
                reference = None
            else:
                reference = _reference_media(reference_asset, version)
                expected_reference_fingerprint = reference.actual_sha256
            if preview.reference_asset_id not in {
                None,
                reference.asset_id if reference is not None else None,
            }:
                raise QwenVoiceProductSecurityError(
                    "voice preview reference identity changed"
                )
            if (
                preview.model_fingerprint != VOICE_BASE_PRODUCT_FINGERPRINT
                or preview.reference_fingerprint != expected_reference_fingerprint
            ):
                # A generated preview created before its reference was published
                # retains its design-pending fingerprint.  Publication updates it
                # atomically after the durable anchor exists.
                generated_transition = (
                    version.source_type == "generated"
                    and reference is not None
                    and preview.reference_asset_id == reference.asset_id
                    and preview.reference_fingerprint == reference.actual_sha256
                )
                if not generated_transition:
                    raise QwenVoiceProductSecurityError(
                        "voice preview input fingerprint changed"
                    )
            metadata = {
                "schema_version": VOICE_PRODUCT_SCHEMA_VERSION,
                "attempt_id": str(lease.fence.attempt_id),
                "preview_id": str(preview.id),
                "request_fingerprint": preview.request_fingerprint,
                "reference_fingerprint": preview.reference_fingerprint,
                "parameters_fingerprint": preview.parameters_fingerprint,
                "preview_text_digest": preview.preview_text_digest,
            }
            digest_key = self._digest_keyring.active
            input_digest = digest_key.digest(
                VOICE_MODEL_INPUT_PURPOSE.encode("ascii")
                + b"\0"
                + canonical_sha256(metadata).encode("ascii")
            )
            now = _db_now(session)
            if preview.status == "queued":
                preview.status = "running"
                preview.started_at = now
                preview.updated_at = now
            session.flush()
            return QwenVoicePreviewWorkItem(
                lease=lease,
                preview_id=preview.id,
                profile_id=profile.id,
                version_id=version.id,
                rights_record_id=version.rights_record_id,
                novel_id=profile.novel_id,
                preview_text=preview.preview_text,
                description=description,
                seed=version.seed if version.seed is not None else self._policy.seed,
                request_fingerprint=preview.request_fingerprint,
                parameters_fingerprint=preview.parameters_fingerprint,
                input_digest_key_id=digest_key.key_id,
                input_digest=input_digest,
                reference=reference,
            )

        return self._tx(operation)

    def read_job_state(self, lease: JobLease) -> str:
        return self._tx(
            lambda session: self._job(session, lease, for_update=False).state
        )

    def heartbeat_and_read_state(self, lease: JobLease) -> str:
        def operation(session: Session) -> str:
            job = self._job(session, lease, for_update=True)
            if job.state == "running":
                heartbeat_attempt(session, scope=self._scope, fence=lease.fence)
            return job.state

        return self._tx(operation)

    def _append_model_run(
        self,
        session: Session,
        work: QwenVoicePreviewWorkItem,
        *,
        requested_model_id: str,
        requested_revision: str,
        classification: Literal[
            "success",
            "retryable_failure",
            "non_retryable_failure",
            "cancelled",
            "security_failure",
        ],
        prepared: PreparedQwenVoiceAudio | None = None,
    ) -> None:
        existing = session.scalar(
            select(ModelRunRecord).where(
                ModelRunRecord.attempt_id == work.lease.fence.attempt_id,
                ModelRunRecord.requested_model_id == requested_model_id,
            )
        )
        if existing is not None:
            if classification == "success" and existing.result_classification == "success":
                return
            raise InvalidNarrationState(
                "voice preview attempt already has model evidence"
            )
        success = classification == "success"
        if success != (prepared is not None):
            raise InvalidNarrationState("voice model evidence is incomplete")
        identity = prepared.model_identity if prepared is not None else None
        session.add(
            ModelRunRecord(
                attempt_id=work.lease.fence.attempt_id,
                requested_provider_id=TTSProviderId.LOCAL_QWEN3_TTS.value,
                requested_model_id=requested_model_id,
                requested_revision=requested_revision,
                actual_provider_id=(
                    identity.provider_id.value if identity is not None else None
                ),
                actual_model_id=(identity.model_id if identity is not None else None),
                actual_revision=(
                    identity.model_revision if identity is not None else None
                ),
                model_fingerprint=(
                    prepared.model_fingerprint if prepared is not None else None
                ),
                parameters_digest=work.parameters_fingerprint,
                input_digest_key_id=work.input_digest_key_id,
                input_digest=work.input_digest,
                output_digest=(
                    prepared.processed.actual_sha256 if prepared is not None else None
                ),
                duration_ms=(
                    prepared.processed.duration_ms if prepared is not None else None
                ),
                provider_request_id=(
                    prepared.provider_request_id
                    if prepared is not None
                    else str(work.lease.fence.attempt_id)
                ),
                result_classification=classification,
            )
        )

    def publish_generated_reference(
        self,
        work: QwenVoicePreviewWorkItem,
        prepared: PreparedQwenVoiceAudio,
    ) -> QwenReferenceMedia:
        def operation(session: Session) -> QwenReferenceMedia:
            if work.lease.resource_fence is None:
                raise QwenVoiceProductSecurityError(
                    "voice preview lease has no resource fence"
                )
            lock_result_publish_fences(
                session,
                scope=self._scope,
                job_fence=work.lease.fence,
                resource_fence=work.lease.resource_fence,
            )
            _job, preview, version, profile, _rights = self._validated_work_rows(
                session, work.lease, for_update=True
            )
            if (
                preview.id != work.preview_id
                or preview.status != "running"
                or preview.preview_text is None
                or version.id != work.version_id
                or version.source_type != "generated"
            ):
                raise QwenVoiceProductSecurityError(
                    "designed voice publication provenance changed"
                )
            asset_id = _child_uuid(version.id, "generated-reference")
            expected_path = _canonical_asset_path(
                asset_id, prepared.processed.actual_sha256, "wav"
            )
            if (
                prepared.requested_model_id != VOICE_DESIGN_MODEL_ID
                or prepared.requested_revision != VOICE_DESIGN_MODEL_REVISION
                or prepared.published.asset_id != asset_id
                or prepared.published.relative_path != expected_path
                or prepared.published.actual_sha256
                != prepared.processed.actual_sha256
            ):
                raise QwenVoiceProductSecurityError(
                    "designed voice media identity changed"
                )
            existing = session.get(MediaAsset, asset_id)
            if version.reference_asset_id is not None:
                if version.reference_asset_id != asset_id or existing is None:
                    raise QwenVoiceProductSecurityError(
                        "designed voice reference was replaced"
                    )
                return _reference_media(existing, version)
            if existing is not None:
                raise InvalidNarrationState(
                    "designed voice reference asset is already occupied"
                )
            now = _db_now(session)
            asset = _ready_media_row(
                asset_id=asset_id,
                profile=profile,
                kind="narration_voice_reference",
                asset_class="voice_reference",
                retention_policy="locked_voice",
                publication=prepared.published,
                duration_ms=prepared.processed.duration_ms,
                sample_rate=prepared.processed.sample_rate_hz,
                channels=prepared.processed.channels,
                validation_json={
                    "schema_version": VOICE_PRODUCT_SCHEMA_VERSION,
                    "input": asdict(prepared.processed.input_inspection),
                    "output": asdict(prepared.processed.output_inspection),
                    "processing_fingerprint": prepared.processed.processing_fingerprint,
                },
                metadata_json={
                    "schema_version": VOICE_PRODUCT_SCHEMA_VERSION,
                    "voice_version_id": str(version.id),
                    "design_model_id": VOICE_DESIGN_MODEL_ID,
                    "design_model_revision": VOICE_DESIGN_MODEL_REVISION,
                    "design_model_fingerprint": prepared.model_fingerprint,
                    "anchor_text_sha256": hashlib.sha256(
                        VOICE_DESIGN_ANCHOR_TEXT.encode("utf-8")
                    ).hexdigest(),
                },
                at=now,
            )
            parameters = dict(version.parameters_json)
            description = parameters.pop("design_description", None)
            if description != work.description:
                raise QwenVoiceProductSecurityError(
                    "designed voice description changed before publication"
                )
            parameters["design_model_fingerprint"] = prepared.model_fingerprint
            parameters["anchor_text_sha256"] = hashlib.sha256(
                VOICE_DESIGN_ANCHOR_TEXT.encode("utf-8")
            ).hexdigest()
            version.parameters_json = parameters
            version.reference_asset_id = asset.id
            preview.reference_asset_id = asset.id
            preview.reference_fingerprint = asset.content_hash
            preview.parameters_fingerprint = canonical_sha256(
                {
                    "schema_version": VOICE_PRODUCT_SCHEMA_VERSION,
                    "provider_id": TTSProviderId.LOCAL_QWEN3_TTS.value,
                    "base_model_fingerprint": VOICE_BASE_PRODUCT_FINGERPRINT,
                    "version_fingerprint": version.fingerprint,
                    "reference_fingerprint": asset.content_hash,
                    "seed": version.seed,
                    "language": VOICE_LANGUAGE,
                }
            )
            session.add(asset)
            # The active-input guard is immediate and cannot rely on ORM flush
            # ordering without a mapped relationship. Publish the ready asset
            # first, then attach its job reference in the same transaction.
            session.flush([asset])
            session.add(
                ActiveJobAsset(
                    job_id=work.lease.fence.job_id,
                    asset_id=asset.id,
                    owner_id=profile.owner_id,
                    workspace_id=profile.workspace_id,
                    novel_id=profile.novel_id,
                    role="input",
                    acquired_at=now,
                    released_at=None,
                )
            )
            self._append_model_run(
                session,
                work,
                requested_model_id=VOICE_DESIGN_MODEL_ID,
                requested_revision=VOICE_DESIGN_MODEL_REVISION,
                classification="success",
                prepared=prepared,
            )
            session.flush()
            return _reference_media(asset, version)

        return self._tx(operation)

    def publish_preview(
        self,
        work: QwenVoicePreviewWorkItem,
        reference: QwenReferenceMedia,
        prepared: PreparedQwenVoiceAudio,
    ) -> None:
        def operation(session: Session) -> None:
            if work.lease.resource_fence is None:
                raise QwenVoiceProductSecurityError(
                    "voice preview lease has no resource fence"
                )
            context = lock_result_publish_fences(
                session,
                scope=self._scope,
                job_fence=work.lease.fence,
                resource_fence=work.lease.resource_fence,
            )
            job, preview, version, profile, _rights = self._validated_work_rows(
                session, work.lease, for_update=True
            )
            reference_asset = _reference_asset(
                session, profile, version, for_update=True
            )
            if (
                preview.id != work.preview_id
                or preview.status != "running"
                or preview.preview_text is None
                or preview.reference_asset_id != reference.asset_id
                or reference_asset is None
                or reference_asset.id != reference.asset_id
                or reference_asset.content_hash != reference.actual_sha256
                or prepared.requested_model_id != VOICE_BASE_MODEL_ID
                or prepared.requested_revision != VOICE_BASE_MODEL_REVISION
            ):
                raise QwenVoiceProductSecurityError(
                    "voice preview publication provenance changed"
                )
            asset_id = _child_uuid(preview.id, "preview-result")
            expected_path = _canonical_asset_path(
                asset_id, prepared.processed.actual_sha256, "wav"
            )
            if (
                prepared.published.asset_id != asset_id
                or prepared.published.relative_path != expected_path
                or prepared.published.actual_sha256
                != prepared.processed.actual_sha256
                or session.get(MediaAsset, asset_id) is not None
            ):
                raise QwenVoiceProductSecurityError(
                    "voice preview result identity changed"
                )
            now = _db_now(session)
            expires_at = now + timedelta(seconds=self._policy.preview_ttl_seconds)
            asset = _ready_media_row(
                asset_id=asset_id,
                profile=profile,
                kind="narration_voice_preview",
                asset_class="preview",
                retention_policy="temporary_preview",
                publication=prepared.published,
                duration_ms=prepared.processed.duration_ms,
                sample_rate=prepared.processed.sample_rate_hz,
                channels=prepared.processed.channels,
                validation_json={
                    "schema_version": VOICE_PRODUCT_SCHEMA_VERSION,
                    "input": asdict(prepared.processed.input_inspection),
                    "output": asdict(prepared.processed.output_inspection),
                    "processing_fingerprint": prepared.processed.processing_fingerprint,
                },
                metadata_json={
                    "schema_version": VOICE_PRODUCT_SCHEMA_VERSION,
                    "preview_id": str(preview.id),
                    "model_id": VOICE_BASE_MODEL_ID,
                    "model_revision": VOICE_BASE_MODEL_REVISION,
                    "model_fingerprint": prepared.model_fingerprint,
                },
                at=now,
                expires_at=expires_at,
            )
            session.add(asset)
            session.flush([asset])
            self._append_model_run(
                session,
                work,
                requested_model_id=VOICE_BASE_MODEL_ID,
                requested_revision=VOICE_BASE_MODEL_REVISION,
                classification="success",
                prepared=prepared,
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
                version.preview_asset_id = asset.id
            elif version.state not in {"preview_ready", "locked"}:
                raise InvalidNarrationState(
                    "voice version cannot accept preview success"
                )
            release_active_job_assets_in_session(session, job_id=job.id)
            complete_attempt(
                session,
                scope=self._scope,
                fence=work.lease.fence,
                actual_result_digest=prepared.processed.actual_sha256,
                publication_context=context,
            )
            session.flush()

        self._tx(operation)

    def create_designed_version(
        self,
        *,
        profile_id: UUID,
        request: wire.CreateDesignedVoiceVersionRequest,
        idempotency_key: str,
        request_hash: str,
        description: str,
        description_digest_key_id: str,
        description_digest: str,
        version_id: UUID,
    ) -> wire.VoiceProfileVersionResource:
        def operation(session: Session) -> wire.VoiceProfileVersionResource:
            profile = _required_profile(session, profile_id, for_update=True)
            now = _db_now(session)
            receipt = reserve_voice_action_receipt(
                session,
                operation=VOICE_DESIGN_OPERATION,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                resource_id=version_id,
            )
            existing = session.get(VoiceProfileVersion, version_id)
            if receipt.state == "completed":
                if existing is None or existing.profile_id != profile.id:
                    raise InvalidNarrationState(
                        "completed design receipt has no matching voice version"
                    )
                return _version_resource(session, profile, existing.id, at=now)
            if existing is not None:
                raise InvalidNarrationState("reserved design names an existing version")
            if profile.version != request.expected_profile_version:
                raise NarrationCasConflict("voice profile version changed")
            if profile.status in {"archived", "unavailable"}:
                raise InvalidNarrationState("voice profile cannot accept a new source")
            if request.language != VOICE_LANGUAGE:
                raise QwenVoiceProductContractError("voice language must be zh-CN")
            rights_id = _child_uuid(version_id, "rights")
            rights = VoiceRightsRecord(
                id=rights_id,
                owner_id=profile.owner_id,
                workspace_id=profile.workspace_id,
                novel_id=profile.novel_id,
                source_kind="qwen_synthetic_design",
                source_identifier=f"qwen-synthetic-design:{description_digest}",
                notice_version="qwen-synthetic-design-rights/1",
                purpose="private_novel_narration",
                commercial_use=False,
                redistribution=False,
                voice_cloning=True,
                subject_consent_reference=None,
                confirmed_actor=self._policy.actor,
                confirmed_at=now,
                expires_at=None,
                risk_flags_json=[],
            )
            event = VoiceRightsEvent(
                id=_child_uuid(version_id, "rights-confirmed"),
                rights_record_id=rights.id,
                event_key=f"design-confirmed:{version_id.hex}",
                event_type="confirmed",
                actor=self._policy.actor,
                reason_code=None,
                occurred_at=now,
            )
            seed = request.seed if request.seed is not None else self._policy.seed
            parameters = {
                "schema_version": VOICE_PARAMETERS_SCHEMA_VERSION,
                "voice_kind": TTSVoiceKind.REFERENCE_CLONE.value,
                "provider_voice_id": VOICE_REFERENCE_PROVIDER_ID,
                "reference_text": VOICE_DESIGN_ANCHOR_TEXT,
                "design_description": description,
                "design_policy_version": VOICE_DESIGN_POLICY_VERSION,
                "design_seed": seed,
                "design_model_id": VOICE_DESIGN_MODEL_ID,
                "design_model_revision": VOICE_DESIGN_MODEL_REVISION,
                "design_artifact_tree_sha256": VOICE_DESIGN_ARTIFACT_SHA256,
            }
            version = VoiceProfileVersion(
                id=version_id,
                profile_id=profile.id,
                owner_id=profile.owner_id,
                workspace_id=profile.workspace_id,
                version_number=self._max_version_number(session, profile.id) + 1,
                source_type="generated",
                state="draft",
                provider_id=VOICE_PRODUCT_PROVIDER_ID,
                model_id=VOICE_BASE_MODEL_ID,
                model_revision=VOICE_BASE_MODEL_REVISION,
                preset_key=None,
                reference_asset_id=None,
                preview_asset_id=None,
                model_run_id=None,
                rights_record_id=rights.id,
                description_digest_key_id=description_digest_key_id,
                description_digest=description_digest,
                language=VOICE_LANGUAGE,
                seed=seed,
                parameters_json=parameters,
                fingerprint=canonical_sha256(
                    {
                        "schema_version": VOICE_PRODUCT_SCHEMA_VERSION,
                        "profile_id": str(profile.id),
                        "version_id": str(version_id),
                        "source_type": "generated",
                        "description_digest_key_id": description_digest_key_id,
                        "description_digest": description_digest,
                        "design_policy_version": VOICE_DESIGN_POLICY_VERSION,
                        "seed": seed,
                        "model_id": VOICE_BASE_MODEL_ID,
                        "model_revision": VOICE_BASE_MODEL_REVISION,
                    }
                ),
                quality_state="pending",
                activation_basis="preview_confirmed",
                validation_basis="pending",
                locked_actor=None,
                locked_at=None,
                created_at=now,
            )
            session.add(rights)
            session.flush()
            session.add_all([event, version])
            profile.version += 1
            profile.updated_at = now
            complete_voice_action_receipt(session, receipt.row_id, at=now)
            session.flush()
            return _version_resource(session, profile, version.id, at=now)

        return self._tx(operation)

    def create_preview(
        self,
        *,
        profile_id: UUID,
        request: wire.CreateVoicePreviewRequest,
        idempotency_key: str,
        preview_text: str,
        text_digest_key_id: str,
        text_digest: str,
    ) -> wire.VoicePreviewResource:
        def operation(session: Session) -> wire.VoicePreviewResource:
            existing_receipt = session.scalar(
                select(VoiceActionReceipt)
                .where(
                    VoiceActionReceipt.owner_id == self._scope.owner_id,
                    VoiceActionReceipt.workspace_id == self._scope.workspace_id,
                    VoiceActionReceipt.operation == VOICE_PREVIEW_OPERATION,
                    VoiceActionReceipt.idempotency_key == idempotency_key,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if existing_receipt is not None:
                existing_preview = session.get(
                    VoicePreview, existing_receipt.resource_id
                )
                if existing_receipt.state != "completed" or existing_preview is None:
                    raise InvalidNarrationState(
                        "preview receipt has no completed resource"
                    )
                historical = self._digest_keyring.require(
                    existing_preview.preview_text_digest_key_id
                )
                expected_digest = historical_private_text_digest(
                    historical,
                    purpose=VOICE_PREVIEW_TEXT_PURPOSE,
                    text=preview_text,
                )
                if (
                    existing_preview.profile_id != profile_id
                    or existing_preview.version_id != request.version_id
                    or not hmac.compare_digest(
                        expected_digest, existing_preview.preview_text_digest
                    )
                ):
                    raise IdempotencyConflict(
                        "preview key already names another request"
                    )
                return _preview_resource(
                    session, existing_preview, at=_db_now(session)
                )

            # Keep the established voice authority order: version, profile, rights.
            version = _required_version(
                session, profile_id, request.version_id, for_update=True
            )
            profile = _required_profile(session, profile_id, for_update=True)
            now = _db_now(session)
            rights = _required_active_rights(
                session, profile, version, at=now, for_update=True
            )
            if version.source_type not in {"uploaded", "generated"} or version.state not in {
                "draft",
                "preview_ready",
                "locked",
            }:
                raise InvalidNarrationState("voice version cannot create a preview")
            if version.language != VOICE_LANGUAGE:
                raise QwenVoiceProductSecurityError("voice language changed")
            reference = _reference_asset(
                session, profile, version, for_update=True
            )
            if version.source_type == "uploaded" and reference is None:
                raise QwenVoiceProductSecurityError(
                    "uploaded voice has no durable reference"
                )
            if reference is None:
                parameters = version.parameters_json
                description = (
                    parameters.get("design_description")
                    if type(parameters) is dict
                    else None
                )
                if type(description) is not str or not description.strip():
                    raise QwenVoiceProductSecurityError(
                        "designed voice has no recoverable description"
                    )
                source_fingerprint = canonical_sha256(
                    {
                        "state": "design_pending",
                        "version_fingerprint": version.fingerprint,
                        "description_digest": version.description_digest,
                    }
                )
            else:
                _reference_text(version)
                source_fingerprint = reference.content_hash
            parameters_fingerprint = canonical_sha256(
                {
                    "schema_version": VOICE_PRODUCT_SCHEMA_VERSION,
                    "provider_id": TTSProviderId.LOCAL_QWEN3_TTS.value,
                    "base_model_fingerprint": VOICE_BASE_PRODUCT_FINGERPRINT,
                    "version_fingerprint": version.fingerprint,
                    "reference_fingerprint": source_fingerprint,
                    "seed": version.seed,
                    "language": VOICE_LANGUAGE,
                }
            )
            request_fingerprint = canonical_sha256(
                {
                    "schema_version": VOICE_PRODUCT_SCHEMA_VERSION,
                    "operation": VOICE_PREVIEW_OPERATION,
                    "profile_id": str(profile.id),
                    "version_id": str(version.id),
                    "preview_text_digest_key_id": text_digest_key_id,
                    "preview_text_digest": text_digest,
                    "source_fingerprint": source_fingerprint,
                    "parameters_fingerprint": parameters_fingerprint,
                }
            )
            preview_id = _stable_uuid(VOICE_PREVIEW_OPERATION, idempotency_key)
            receipt = reserve_voice_action_receipt(
                session,
                operation=VOICE_PREVIEW_OPERATION,
                idempotency_key=idempotency_key,
                request_hash=request_fingerprint,
                resource_id=preview_id,
            )
            if session.get(VoicePreview, preview_id) is not None:
                raise InvalidNarrationState("new preview receipt names an existing preview")
            enqueue = enqueue_job(
                session,
                scope=self._scope,
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
                reference_asset_id=reference.id if reference is not None else None,
                result_asset_id=None,
                preview_text=preview_text,
                preview_text_digest_key_id=text_digest_key_id,
                preview_text_digest=text_digest,
                model_fingerprint=VOICE_BASE_PRODUCT_FINGERPRINT,
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
            complete_voice_action_receipt(session, receipt.row_id, at=now)
            session.flush()
            return _preview_resource(session, preview, at=now)

        return self._tx(operation)

    def get_preview(self, *, preview_id: UUID) -> wire.VoicePreviewResource:
        def operation(session: Session) -> wire.VoicePreviewResource:
            preview = session.get(VoicePreview, preview_id)
            if preview is None:
                raise QwenVoicePreviewNotFound("voice preview not found")
            return _preview_resource(session, preview, at=_db_now(session))

        return self._tx(operation)

    def lock_profile(
        self,
        *,
        profile_id: UUID,
        request: wire.LockVoiceProfileRequest,
    ) -> wire.VoiceProfileResource:
        def operation(session: Session) -> wire.VoiceProfileResource:
            version = _required_version(
                session, profile_id, request.version_id, for_update=True
            )
            profile = _required_profile(session, profile_id, for_update=True)
            now = _db_now(session)
            rights = _required_active_rights(
                session, profile, version, at=now, for_update=True
            )
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
            receipt = reserve_voice_action_receipt(
                session,
                operation=VOICE_LOCK_OPERATION,
                idempotency_key=(
                    f"lock:{version.id.hex}:{request.expected_profile_version}"
                ),
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
                    raise InvalidNarrationState(
                        "completed lock receipt has no locked version"
                    )
                return voice_profile_resource(
                    SqlAlchemyNarrationStore(session), profile, at=now
                )
            if request.quality_confirmed is not True:
                raise QwenVoiceProductContractError(
                    "voice quality must be explicitly confirmed"
                )
            if profile.version != request.expected_profile_version:
                raise NarrationCasConflict("voice profile version changed")
            if (
                version.source_type not in {"uploaded", "generated"}
                or version.state != "preview_ready"
                or version.quality_state != "pending"
                or version.language != VOICE_LANGUAGE
            ):
                raise InvalidNarrationState(
                    "voice version requires a successful preview before lock"
                )
            reference = _reference_asset(
                session, profile, version, for_update=True
            )
            if reference is None:
                raise QwenVoiceProductSecurityError(
                    "voice lock requires a durable reference"
                )
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
                raise InvalidNarrationState(
                    "voice lock requires an unexpired preview"
                )
            preview = previews[0]
            if (
                preview.reference_asset_id != reference.id
                or preview.result_asset_id is None
                or preview.model_fingerprint != VOICE_BASE_PRODUCT_FINGERPRINT
            ):
                raise QwenVoiceProductSecurityError(
                    "voice preview evidence no longer matches"
                )
            result_asset = session.get(MediaAsset, preview.result_asset_id)
            if (
                result_asset is None
                or result_asset.owner_id != profile.owner_id
                or result_asset.workspace_id != profile.workspace_id
                or result_asset.novel_id != profile.novel_id
                or result_asset.kind != "narration_voice_preview"
                or result_asset.asset_class != "preview"
                or result_asset.retention_policy != "temporary_preview"
                or result_asset.state != "ready"
                or result_asset.expires_at != preview.expires_at
            ):
                raise QwenVoiceProductSecurityError(
                    "voice preview media is not authoritative"
                )
            run = session.scalar(
                select(ModelRunRecord)
                .join(
                    BackgroundJobAttempt,
                    BackgroundJobAttempt.id == ModelRunRecord.attempt_id,
                )
                .where(
                    BackgroundJobAttempt.job_id == preview.job_id,
                    ModelRunRecord.requested_model_id == VOICE_BASE_MODEL_ID,
                    ModelRunRecord.result_classification == "success",
                )
            )
            if (
                run is None
                or run.actual_model_id != VOICE_BASE_MODEL_ID
                or run.actual_revision != VOICE_BASE_MODEL_REVISION
                or run.output_digest != result_asset.content_hash
            ):
                raise QwenVoiceProductSecurityError(
                    "voice preview lacks matching Base model evidence"
                )
            version.state = "locked"
            version.quality_state = "accepted"
            version.validation_basis = "human_accepted"
            version.activation_basis = "preview_confirmed"
            version.locked_actor = self._policy.actor
            version.locked_at = now
            profile.current_version_id = version.id
            profile.status = "active"
            profile.version += 1
            profile.updated_at = now
            complete_voice_action_receipt(session, receipt.row_id, at=now)
            session.flush()
            return voice_profile_resource(
                SqlAlchemyNarrationStore(session), profile, at=now
            )

        return self._tx(operation)

    @staticmethod
    def _terminal_preview(
        preview: VoicePreview,
        *,
        status: Literal["failed", "cancelled"],
        at: datetime,
        failure_code: str | None,
    ) -> None:
        if preview.status not in {"queued", "running"}:
            raise InvalidNarrationState(
                "voice preview cannot enter another terminal state"
            )
        preview.status = status
        preview.preview_text = None
        preview.result_asset_id = None
        preview.completed_at = at
        preview.expires_at = None
        preview.failure_code = failure_code
        preview.updated_at = at

    def fail(
        self,
        work: QwenVoicePreviewWorkItem,
        *,
        classification: Literal["retryable", "non_retryable", "security_failure"],
        error_code: str,
    ) -> FailureResult:
        def operation(session: Session) -> FailureResult:
            heartbeat_attempt(session, scope=self._scope, fence=work.lease.fence)
            job = self._job(session, work.lease, for_update=True)
            preview = self._preview_for_job(session, job.id, for_update=True)
            requested_model = (
                VOICE_DESIGN_MODEL_ID
                if work.description is not None and work.reference is None
                else VOICE_BASE_MODEL_ID
            )
            requested_revision = (
                VOICE_DESIGN_MODEL_REVISION
                if requested_model == VOICE_DESIGN_MODEL_ID
                else VOICE_BASE_MODEL_REVISION
            )
            self._append_model_run(
                session,
                work,
                requested_model_id=requested_model,
                requested_revision=requested_revision,
                classification={
                    "retryable": "retryable_failure",
                    "non_retryable": "non_retryable_failure",
                    "security_failure": "security_failure",
                }[classification],
            )
            result = fail_attempt(
                session,
                scope=self._scope,
                fence=work.lease.fence,
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
                release_active_job_assets_in_session(session, job_id=job.id)
            session.flush()
            return result

        return self._tx(operation)

    def fail_claim(
        self,
        lease: JobLease,
        *,
        classification: Literal["retryable", "non_retryable", "security_failure"],
        error_code: str,
    ) -> FailureResult:
        def operation(session: Session) -> FailureResult:
            job = self._job(session, lease, for_update=True)
            preview = self._preview_for_job(session, job.id, for_update=True)
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
                release_active_job_assets_in_session(session, job_id=job.id)
            session.flush()
            return result

        return self._tx(operation)

    def acknowledge_cancel(self, work: QwenVoicePreviewWorkItem) -> None:
        def operation(session: Session) -> None:
            job = self._job(session, work.lease, for_update=True)
            preview = self._preview_for_job(session, job.id, for_update=True)
            requested_model = (
                VOICE_DESIGN_MODEL_ID
                if work.description is not None and work.reference is None
                else VOICE_BASE_MODEL_ID
            )
            requested_revision = (
                VOICE_DESIGN_MODEL_REVISION
                if requested_model == VOICE_DESIGN_MODEL_ID
                else VOICE_BASE_MODEL_REVISION
            )
            self._append_model_run(
                session,
                work,
                requested_model_id=requested_model,
                requested_revision=requested_revision,
                classification="cancelled",
            )
            self._terminal_preview(
                preview,
                status="cancelled",
                at=_db_now(session),
                failure_code=None,
            )
            release_active_job_assets_in_session(session, job_id=job.id)
            acknowledge_cancel(session, scope=self._scope, fence=work.lease.fence)
            session.flush()

        self._tx(operation)

    def terminalize_job_in_session(self, session: Session, *, job_id: UUID) -> bool:
        """Join generic cancellation/failure in the same transaction."""

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
                failure_code=job.error_code or "VOICE_PREVIEW_FAILED",
            )
        else:
            return False
        release_active_job_assets_in_session(session, job_id=job.id)
        session.flush()
        return True


class QwenVoiceProductService:
    """Production implementation of the existing private-voice port."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        storage: NarrationStorage,
        normalize_reference: ReferenceNormalizer,
        digest_keyring: DigestKeyring,
        policy: QwenVoiceProductPolicy = QwenVoiceProductPolicy(),
        repository: SqlAlchemyQwenVoiceProductRepository | None = None,
    ) -> None:
        if not callable(session_factory) or not callable(normalize_reference):
            raise TypeError("Qwen voice product requires callable dependencies")
        if not hasattr(storage, "publish_or_verify_media"):
            raise TypeError("Qwen voice product requires immutable storage")
        if type(digest_keyring) is not DigestKeyring:
            raise TypeError("Qwen voice product requires a digest keyring")
        policy.validate()
        self._storage = storage
        self._normalize_reference = normalize_reference
        self._digest_keyring = digest_keyring
        self._policy = policy
        self.repository = repository or SqlAlchemyQwenVoiceProductRepository(
            session_factory,
            digest_keyring=digest_keyring,
            policy=policy,
        )

    def create_uploaded_version(
        self,
        *,
        profile_id: UUID,
        parsed: ParsedUploadedVoice,
        idempotency_key: str,
    ) -> wire.VoiceProfileVersionResource:
        key = _required_key(idempotency_key)
        require_mandarin_language(parsed.metadata.language)
        reference_text = unicodedata.normalize(
            "NFC", parsed.metadata.reference_text
        )
        if not reference_text.strip() or len(reference_text) > 500:
            raise QwenVoiceProductContractError(
                "reference text is outside the frozen bounds"
            )
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
        version_id = _stable_uuid(VOICE_UPLOAD_OPERATION, key)
        source_asset_id = _child_uuid(version_id, "source-original")
        reference_asset_id = _child_uuid(version_id, "reference-normalized")
        request_hash = canonical_sha256(
            {
                "schema_version": VOICE_PRODUCT_SCHEMA_VERSION,
                "operation": VOICE_UPLOAD_OPERATION,
                "profile_id": str(profile_id),
                "expected_profile_version": parsed.metadata.expected_profile_version,
                "language": parsed.metadata.language,
                "source_sha256": parsed.checksum_sha256,
                "source_byte_size": parsed.byte_size,
                "normalized_sha256": normalized.normalized_sha256,
                "normalization_fingerprint": normalized.normalization_fingerprint,
                "reference_text_sha256": hashlib.sha256(
                    reference_text.encode("utf-8")
                ).hexdigest(),
                "rights": parsed.metadata.rights.model_dump(mode="json"),
            }
        )
        source_extension = "wav" if parsed.mime_type == "audio/wav" else "flac"
        source_publication = self._storage.publish_or_verify_media(
            (parsed.reference_audio,),
            asset_id=source_asset_id,
            expected_sha256=parsed.checksum_sha256,
            expected_size=parsed.byte_size,
            extension=source_extension,
            max_bytes=wire.REFERENCE_UPLOAD_MAX_BYTES,
        )
        reference_publication = self._storage.publish_or_verify_media(
            (normalized.normalized_bytes,),
            asset_id=reference_asset_id,
            expected_sha256=normalized.normalized_sha256,
            expected_size=normalized.normalized_byte_size,
            extension="wav",
            max_bytes=max(normalized.normalized_byte_size, 4 * 1024 * 1024),
        )
        return self.repository.create_uploaded_version(
            profile_id=profile_id,
            parsed=parsed,
            normalized=normalized,
            source_publication=source_publication,
            reference_publication=reference_publication,
            idempotency_key=key,
            request_hash=request_hash,
            version_id=version_id,
            source_asset_id=source_asset_id,
            reference_asset_id=reference_asset_id,
        )

    def create_designed_version(
        self,
        *,
        profile_id: UUID,
        request: wire.CreateDesignedVoiceVersionRequest,
        idempotency_key: str,
    ) -> wire.VoiceProfileVersionResource:
        key = _required_key(idempotency_key)
        require_mandarin_language(request.language)
        description = unicodedata.normalize("NFC", request.description).strip()
        require_mandarin_voice_design(description)
        if len(description) > 500:
            raise QwenVoiceProductContractError(
                "voice description is outside the frozen bounds"
            )
        digest_key = self._digest_keyring.active
        description_digest = private_text_digest(
            digest_key,
            purpose=VOICE_DESCRIPTION_PURPOSE,
            text=description,
        )
        request_hash = canonical_sha256(
            {
                "schema_version": VOICE_PRODUCT_SCHEMA_VERSION,
                "operation": VOICE_DESIGN_OPERATION,
                "profile_id": str(profile_id),
                "expected_profile_version": request.expected_profile_version,
                "language": request.language,
                "seed": request.seed,
                "description_digest_key_id": digest_key.key_id,
                "description_digest": description_digest,
            }
        )
        return self.repository.create_designed_version(
            profile_id=profile_id,
            request=request,
            idempotency_key=key,
            request_hash=request_hash,
            description=description,
            description_digest_key_id=digest_key.key_id,
            description_digest=description_digest,
            version_id=_stable_uuid(VOICE_DESIGN_OPERATION, key),
        )

    def create_preset_version(
        self,
        *,
        profile_id: UUID,
        request: wire.CreatePresetVoiceVersionRequest,
        idempotency_key: str,
    ) -> wire.VoiceProfileVersionResource:
        del profile_id, request, idempotency_key
        raise VoiceSourceUnavailable(
            "official voice selection uses its dedicated Qwen service"
        )

    def create_preview(
        self,
        *,
        profile_id: UUID,
        request: wire.CreateVoicePreviewRequest,
        idempotency_key: str,
    ) -> wire.VoicePreviewResource:
        key = _required_key(idempotency_key)
        preview_text = unicodedata.normalize("NFC", request.preview_text).strip()
        if not preview_text or len(preview_text) > 500:
            raise QwenVoiceProductContractError(
                "preview text is outside the frozen bounds"
            )
        digest_key = self._digest_keyring.active
        text_digest = private_text_digest(
            digest_key,
            purpose=VOICE_PREVIEW_TEXT_PURPOSE,
            text=preview_text,
        )
        return self.repository.create_preview(
            profile_id=profile_id,
            request=request,
            idempotency_key=key,
            preview_text=preview_text,
            text_digest_key_id=digest_key.key_id,
            text_digest=text_digest,
        )

    def get_preview(self, *, preview_id: UUID) -> wire.VoicePreviewResource:
        return self.repository.get_preview(preview_id=preview_id)

    def lock_profile(
        self,
        *,
        profile_id: UUID,
        request: wire.LockVoiceProfileRequest,
    ) -> wire.VoiceProfileResource:
        return self.repository.lock_profile(profile_id=profile_id, request=request)


def _wav_format(payload: bytes) -> tuple[int, int, int]:
    try:
        with wave.open(BytesIO(payload), "rb") as reader:
            if reader.getcomptype() != "NONE" or reader.getnframes() <= 0:
                raise AudioFormatError("Qwen voice WAV is not non-empty PCM")
            return (
                reader.getframerate(),
                reader.getnchannels(),
                reader.getsampwidth(),
            )
    except AudioPipelineError:
        raise
    except (EOFError, ValueError, wave.Error) as error:
        raise AudioFormatError("Qwen voice WAV is invalid") from error


def _require_exact_model_identity(
    result: TTSVoicePreparationResult,
    *,
    model_id: str,
    model_revision: str,
    artifact_tree_sha256: str,
    voice_kind: TTSVoiceKind,
) -> str:
    identity = result.model_identity
    if (
        result.voice_kind is not voice_kind
        or identity.provider_id is not TTSProviderId.LOCAL_QWEN3_TTS
        or identity.model_id != model_id
        or identity.model_revision != model_revision
        or identity.artifact_tree_sha256 != artifact_tree_sha256
    ):
        raise QwenVoiceProductSecurityError("Qwen voice model identity changed")
    return tts_model_identity_sha256(identity)


class QwenVoicePreviewProcessor:
    """Process one already-claimed ``narration.voice_preview`` job."""

    def __init__(
        self,
        *,
        repository: QwenVoicePreviewRepository,
        execution: TTSExecutionService,
        storage: NarrationStorage,
        policy: QwenVoiceProductPolicy = QwenVoiceProductPolicy(),
        disk_guard: Callable[[], None] | None = None,
    ) -> None:
        policy.validate()
        if not hasattr(storage, "publish_or_verify_media"):
            raise TypeError("Qwen preview processor requires immutable storage")
        if disk_guard is not None and not callable(disk_guard):
            raise TypeError("Qwen preview disk guard must be callable")
        self._repository = repository
        self._execution = execution
        self._storage = storage
        self._policy = policy
        self._disk_guard = disk_guard
        self._selection = wire.TTSProviderSelection(provider_id="local_qwen3_tts")

    def _read_reference(self, reference: QwenReferenceMedia) -> ReferenceAudioInput:
        if reference.byte_size > self._policy.max_reference_bytes:
            raise QwenVoiceProductSecurityError(
                "voice reference exceeds the worker bound"
            )
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

    async def _await_with_heartbeat(
        self,
        work: QwenVoicePreviewWorkItem,
        request_id: UUID,
        awaitable,
    ) -> TTSVoicePreparationResult:
        task = asyncio.create_task(awaitable)
        cancellation_sent = False
        try:
            while True:
                try:
                    result = await asyncio.wait_for(
                        asyncio.shield(task),
                        timeout=float(self._policy.heartbeat_seconds),
                    )
                    if type(result) is not TTSVoicePreparationResult:
                        raise QwenVoiceProductContractError(
                            "Qwen Provider returned an invalid preparation result"
                        )
                    return result
                except TimeoutError:
                    state = await asyncio.to_thread(
                        self._repository.heartbeat_and_read_state, work.lease
                    )
                    if state == "cancel_requested" and not cancellation_sent:
                        cancellation_sent = True
                        await self._execution.cancel(
                            selection=self._selection, request_id=request_id
                        )
                    elif state not in {"running", "cancel_requested"}:
                        task.cancel()
                        try:
                            await task
                        except (asyncio.CancelledError, Exception):
                            pass
                        raise JobFenceError(
                            "voice preview job became terminal during inference"
                        )
        except asyncio.CancelledError:
            if not task.done():
                try:
                    await self._execution.cancel(
                        selection=self._selection, request_id=request_id
                    )
                finally:
                    task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
            raise

    def _prepare_and_publish(
        self,
        *,
        payload: bytes,
        result: TTSVoicePreparationResult,
        asset_id: UUID,
        model_id: str,
        model_revision: str,
        artifact_tree_sha256: str,
        voice_kind: TTSVoiceKind,
        spoken_text: str,
    ) -> PreparedQwenVoiceAudio:
        model_fingerprint = _require_exact_model_identity(
            result,
            model_id=model_id,
            model_revision=model_revision,
            artifact_tree_sha256=artifact_tree_sha256,
            voice_kind=voice_kind,
        )
        sample_rate, channels, sample_width = _wav_format(payload)
        processed = process_provider_synthesis_wav(
            payload,
            declared_sample_rate_hz=sample_rate,
            declared_channels=channels,
            declared_sample_width_bytes=sample_width,
            spoken_text=spoken_text,
        )
        if self._disk_guard is not None:
            self._disk_guard()
        publication = self._storage.publish_or_verify_media(
            (processed.wav_bytes,),
            asset_id=asset_id,
            expected_sha256=processed.actual_sha256,
            expected_size=len(processed.wav_bytes),
            extension="wav",
            max_bytes=(
                MAX_REFERENCE_MEDIA_BYTES
                if voice_kind is TTSVoiceKind.DESIGNED
                else MAX_PREVIEW_MEDIA_BYTES
            ),
        )
        return PreparedQwenVoiceAudio(
            published=publication,
            processed=processed,
            model_identity=result.model_identity,
            model_fingerprint=model_fingerprint,
            requested_model_id=model_id,
            requested_revision=model_revision,
            provider_request_id=str(result.request_id),
        )

    async def _design_reference(
        self, work: QwenVoicePreviewWorkItem
    ) -> tuple[QwenVoicePreviewWorkItem, QwenReferenceMedia]:
        if work.description is None:
            raise QwenVoiceProductSecurityError(
                "designed voice has no verified description"
            )
        request_id = uuid5(work.lease.fence.attempt_id, "voice-design")
        request = TTSVoicePreparationRequest(
            request_id=request_id,
            scope=NarrationRequestScope.fixed_local(),
            preview_text=VOICE_DESIGN_ANCHOR_TEXT,
            language=VOICE_LANGUAGE,
            description=work.description,
            seed=work.seed,
        )
        result = await self._await_with_heartbeat(
            work,
            request_id,
            self._execution.design_voice(
                novel_id=work.novel_id,
                selection=self._selection,
                request=request,
            ),
        )
        asset_id = _child_uuid(work.version_id, "generated-reference")
        prepared = await asyncio.to_thread(
            self._prepare_and_publish,
            payload=result.preview_audio_bytes,
            result=result,
            asset_id=asset_id,
            model_id=VOICE_DESIGN_MODEL_ID,
            model_revision=VOICE_DESIGN_MODEL_REVISION,
            artifact_tree_sha256=VOICE_DESIGN_ARTIFACT_SHA256,
            voice_kind=TTSVoiceKind.DESIGNED,
            spoken_text=VOICE_DESIGN_ANCHOR_TEXT,
        )
        reference = await asyncio.to_thread(
            self._repository.publish_generated_reference, work, prepared
        )
        return replace(work, description=None, reference=reference), reference

    async def _clone_preview(
        self,
        work: QwenVoicePreviewWorkItem,
        reference: QwenReferenceMedia,
    ) -> PreparedQwenVoiceAudio:
        reference_input = await asyncio.to_thread(self._read_reference, reference)
        request_id = uuid5(work.lease.fence.attempt_id, "voice-clone")
        request = TTSVoicePreparationRequest(
            request_id=request_id,
            scope=NarrationRequestScope.fixed_local(),
            preview_text=work.preview_text,
            language=VOICE_LANGUAGE,
            reference_audio=reference_input,
            reference_text=reference.reference_text,
            seed=work.seed,
        )
        result = await self._await_with_heartbeat(
            work,
            request_id,
            self._execution.clone_voice(
                novel_id=work.novel_id,
                selection=self._selection,
                request=request,
            ),
        )
        return await asyncio.to_thread(
            self._prepare_and_publish,
            payload=result.preview_audio_bytes,
            result=result,
            asset_id=_child_uuid(work.preview_id, "preview-result"),
            model_id=VOICE_BASE_MODEL_ID,
            model_revision=VOICE_BASE_MODEL_REVISION,
            artifact_tree_sha256=VOICE_BASE_ARTIFACT_SHA256,
            voice_kind=TTSVoiceKind.REFERENCE_CLONE,
            spoken_text=work.preview_text,
        )

    @staticmethod
    def _classification(
        error: BaseException,
    ) -> tuple[
        Literal["retryable", "non_retryable", "security_failure"], str
    ]:
        if isinstance(
            error,
            (QwenVoiceProductSecurityError, UnsafeStoragePath, StorageRootChanged),
        ):
            return "security_failure", "VOICE_PREVIEW_SECURITY_FAILURE"
        if isinstance(error, TTSProviderError):
            return (
                "retryable" if error.retryable else "non_retryable",
                error.code,
            )
        if isinstance(error, (AudioFormatError, AudioQualityError)):
            return "non_retryable", "QWEN_PREVIEW_AUDIO_INVALID"
        if isinstance(error, PublicationValidationError):
            return "non_retryable", "PREVIEW_PUBLICATION_INVALID"
        if isinstance(error, (StorageError, OSError)):
            return "retryable", "PREVIEW_STORAGE_TEMPORARY_FAILURE"
        if isinstance(
            error,
            (QwenVoiceProductContractError, AudioPipelineError, InvalidNarrationState),
        ):
            return "non_retryable", "VOICE_PREVIEW_INPUT_INVALID"
        return "retryable", "VOICE_PREVIEW_UNEXPECTED_FAILURE"

    async def process(self, lease: JobLease) -> QwenVoicePreviewWorkerOutcome:
        """Run exactly one claimed task without claiming another job."""

        if type(lease) is not JobLease:
            raise TypeError("Qwen voice preview processor requires a JobLease")
        if lease.resource_fence is None:
            try:
                failure = await asyncio.to_thread(
                    self._repository.fail_claim,
                    lease,
                    classification="security_failure",
                    error_code="RESOURCE_FENCE_MISSING",
                )
            except JobFenceError:
                return QwenVoicePreviewWorkerOutcome("stale", lease.fence.job_id)
            return QwenVoicePreviewWorkerOutcome(
                failure.state,
                lease.fence.job_id,
                error_code="RESOURCE_FENCE_MISSING",
            )
        try:
            work = await asyncio.to_thread(
                self._repository.load_and_mark_running, lease
            )
        except JobFenceError:
            return QwenVoicePreviewWorkerOutcome("stale", lease.fence.job_id)
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
                return QwenVoicePreviewWorkerOutcome("stale", lease.fence.job_id)
            return QwenVoicePreviewWorkerOutcome(
                failure.state, lease.fence.job_id, error_code=code
            )
        try:
            state = await asyncio.to_thread(
                self._repository.read_job_state, work.lease
            )
            if state == "cancel_requested":
                await asyncio.to_thread(self._repository.acknowledge_cancel, work)
                return QwenVoicePreviewWorkerOutcome(
                    "cancelled", lease.fence.job_id, work.preview_id
                )
            if state != "running":
                raise JobFenceError(
                    "voice preview left running state before inference"
                )
            reference = work.reference
            if reference is None:
                work, reference = await self._design_reference(work)
            prepared = await self._clone_preview(work, reference)
            state = await asyncio.to_thread(
                self._repository.read_job_state, work.lease
            )
            if state == "cancel_requested":
                await asyncio.to_thread(self._repository.acknowledge_cancel, work)
                return QwenVoicePreviewWorkerOutcome(
                    "cancelled", lease.fence.job_id, work.preview_id
                )
            if state != "running":
                raise JobFenceError(
                    "voice preview left running state before publication"
                )
            await asyncio.to_thread(
                self._repository.publish_preview, work, reference, prepared
            )
            return QwenVoicePreviewWorkerOutcome(
                "succeeded", lease.fence.job_id, work.preview_id
            )
        except JobFenceError:
            return QwenVoicePreviewWorkerOutcome(
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
                return QwenVoicePreviewWorkerOutcome(
                    "stale", lease.fence.job_id, work.preview_id
                )
            return QwenVoicePreviewWorkerOutcome(
                failure.state,
                lease.fence.job_id,
                work.preview_id,
                error_code=code,
            )


async def process_qwen_voice_preview_job(
    processor: QwenVoicePreviewProcessor,
    lease: JobLease,
) -> QwenVoicePreviewWorkerOutcome:
    """Small dispatcher entry point for the shared narration worker."""

    return await processor.process(lease)


__all__ = [
    "QwenReferenceMedia",
    "QwenVoicePreviewNotFound",
    "QwenVoicePreviewProcessor",
    "QwenVoicePreviewRepository",
    "QwenVoicePreviewWorkItem",
    "QwenVoicePreviewWorkerOutcome",
    "QwenVoiceProductContractError",
    "QwenVoiceProductError",
    "QwenVoiceProductPolicy",
    "QwenVoiceProductSecurityError",
    "QwenVoiceProductService",
    "SqlAlchemyQwenVoiceProductRepository",
    "VOICE_BASE_ARTIFACT_SHA256",
    "VOICE_BASE_MODEL_ID",
    "VOICE_BASE_MODEL_REVISION",
    "VOICE_DESIGN_ANCHOR_TEXT",
    "VOICE_DESIGN_ARTIFACT_SHA256",
    "VOICE_DESIGN_MODEL_ID",
    "VOICE_DESIGN_MODEL_REVISION",
    "VOICE_PREVIEW_JOB_KIND",
    "process_qwen_voice_preview_job",
]
