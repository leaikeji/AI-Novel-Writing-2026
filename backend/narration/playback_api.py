"""Strict Manifest v2 and byte-stream playback facade.

The router is intentionally not installed into the PawApp here.  T4-GATE owns
that shared entry point and must explicitly install a request-scoped backend.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import re
from typing import Annotated, Callable, Final, Iterable, Iterator, Literal, Protocol
from uuid import RFC_4122, UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.routing import APIRoute
from pydantic import (
    AwareDatetime,
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse, Response, StreamingResponse

from ..database import DatabaseNotConfigured, get_session
from ..models import (
    MediaAsset,
    NarrationEdition,
    NarrationEditionSegment,
    NarrationManifest,
)
from .contracts import NarrationRequestScope
from .jobs import MAX_PRIORITY, JobServiceError, enqueue_job
from .narration_api import (
    NARRATION_PRODUCTION_API_VERSION,
    NARRATION_PRODUCTION_ERROR_STATUS,
    NarrationProductionApiFault,
    NarrationProductionErrorCode,
    NarrationProductionErrorDetail,
)
from .manifest import (
    ManifestRead,
    PrepareRangeCommand,
    PrepareRangeResult,
    load_public_manifest,
    prepare_manifest_range,
    parse_manifest_v2,
    resolve_playback_media_asset,
)
from .progress import (
    PlaybackResumeProjection,
    SavePlaybackProgress,
    restore_playback_progress,
    save_playback_progress,
)
from .release_gate import require_narration_t4_http_access
from .media import (
    MediaPolicyError,
    MediaReadDecision,
    plan_media_read,
    stream_read_decision,
)
from .services import (
    InvalidNarrationState,
    NarrationCasConflict,
    NarrationNotFound,
    NarrationScopeMismatch,
    NarrationServiceError,
    SqlAlchemyNarrationStore,
    utc_now,
)
from .storage import NarrationStorage, StorageError


_IDEMPOTENCY_KEY_PATTERN: Final = r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$"
_PLAYBACK_PROFILE_PATTERN: Final = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$"
_STRONG_ETAG_PATTERN: Final = r'^"[a-f0-9]{64}"$'


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _rfc4122_uuid(value: UUID, *, field_name: str) -> UUID:
    if value.variant != RFC_4122 or value.version not in {1, 2, 3, 4, 5}:
        raise ValueError(f"{field_name} must be an RFC-4122 UUID v1-v5")
    return value


def _canonical_uuid(value: UUID) -> UUID:
    return _rfc4122_uuid(value, field_name="identity")


CanonicalUuid = Annotated[UUID, AfterValidator(_canonical_uuid)]


PlaybackApiErrorCode = NarrationProductionErrorCode
PlaybackApiErrorDetail = NarrationProductionErrorDetail


class PrepareRangeRequest(_StrictModel):
    start_segment_id: CanonicalUuid
    reason: Literal["user_seek", "resume"]
    expected_manifest_revision: int = Field(ge=1, strict=True)

    @field_validator("start_segment_id")
    @classmethod
    def validate_start_segment_id(cls, value: UUID) -> UUID:
        return _rfc4122_uuid(value, field_name="start_segment_id")


class ReadyRangeResource(_StrictModel):
    start_ordinal: int = Field(ge=0, strict=True)
    end_ordinal_exclusive: int = Field(ge=1, strict=True)
    segment_count: int = Field(ge=1, strict=True)
    duration_ms: int = Field(ge=1, strict=True)
    last_playable_start_ordinal: int = Field(ge=0, strict=True)

    @model_validator(mode="after")
    def validate_bounds(self) -> "ReadyRangeResource":
        if (
            self.end_ordinal_exclusive <= self.start_ordinal
            or self.segment_count
            != self.end_ordinal_exclusive - self.start_ordinal
            or self.last_playable_start_ordinal < self.start_ordinal
            or self.last_playable_start_ordinal >= self.end_ordinal_exclusive
        ):
            raise ValueError("ready range bounds are inconsistent")
        return self


class PrepareRangeResponse(_StrictModel):
    contract_version: Literal["narration-production-api/1"] = (
        NARRATION_PRODUCTION_API_VERSION
    )
    edition_id: CanonicalUuid
    start_segment_id: CanonicalUuid
    start_ordinal: int = Field(ge=0, strict=True)
    state: Literal["ready", "preparing", "failed"]
    manifest_revision: int = Field(ge=1, strict=True)
    manifest_etag: str = Field(pattern=r'^"[a-f0-9]{64}"$')
    ready_range: ReadyRangeResource | None
    promoted_job_ids: list[CanonicalUuid]

    @field_validator("edition_id", "start_segment_id")
    @classmethod
    def validate_scope_ids(cls, value: UUID) -> UUID:
        return _rfc4122_uuid(value, field_name="playback identity")

    @field_validator("promoted_job_ids")
    @classmethod
    def validate_promoted_job_ids(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("promoted_job_ids must be unique")
        return [_rfc4122_uuid(item, field_name="job_id") for item in value]

    @model_validator(mode="after")
    def validate_state_shape(self) -> "PrepareRangeResponse":
        if (self.state == "ready") != (self.ready_range is not None):
            raise ValueError("ready_range must exist exactly when state is ready")
        if self.ready_range is not None and not (
            self.ready_range.start_ordinal
            <= self.start_ordinal
            <= self.ready_range.last_playable_start_ordinal
        ):
            raise ValueError("ready_range does not authorize the requested start")
        if self.state != "preparing" and self.promoted_job_ids:
            raise ValueError("only preparing responses may expose promoted jobs")
        return self


class SavePlaybackProgressRequest(_StrictModel):
    profile_id: str = Field(
        min_length=1,
        max_length=160,
        pattern=_PLAYBACK_PROFILE_PATTERN,
        strict=True,
    )
    manifest_revision: int = Field(ge=1, strict=True)
    manifest_etag: str = Field(pattern=_STRONG_ETAG_PATTERN, strict=True)
    edition_segment_id: CanonicalUuid | None = None
    segment_id: CanonicalUuid
    offset_ms: int = Field(ge=0, strict=True)
    last_legal_start_ordinal: int = Field(ge=0, strict=True)
    playback_rate_millis: int = Field(ge=250, le=4000, strict=True)
    expected_updated_at: AwareDatetime | None

    @field_validator("edition_segment_id", "segment_id")
    @classmethod
    def validate_segment_ids(cls, value: UUID | None) -> UUID | None:
        if value is None:
            return None
        return _rfc4122_uuid(value, field_name="playback segment identity")


class PlaybackProgressResource(_StrictModel):
    manifest_revision: int = Field(ge=1, strict=True)
    manifest_etag: str = Field(pattern=_STRONG_ETAG_PATTERN, strict=True)
    edition_segment_id: CanonicalUuid
    segment_id: CanonicalUuid
    ordinal: int = Field(ge=0, strict=True)
    offset_ms: int = Field(ge=0, strict=True)
    last_legal_start_ordinal: int = Field(ge=0, strict=True)
    playback_rate_millis: int = Field(ge=250, le=4000, strict=True)
    manifest_advanced: bool
    progress_updated_at: AwareDatetime

    @field_validator("edition_segment_id", "segment_id")
    @classmethod
    def validate_segment_ids(cls, value: UUID) -> UUID:
        return _rfc4122_uuid(value, field_name="playback segment identity")

    @model_validator(mode="after")
    def validate_resume_position(self) -> "PlaybackProgressResource":
        if self.last_legal_start_ordinal > self.ordinal:
            raise ValueError("saved legal start cannot follow playback position")
        return self


class PlaybackProgressResponse(_StrictModel):
    contract_version: Literal["narration-production-api/1"] = (
        NARRATION_PRODUCTION_API_VERSION
    )
    edition_id: CanonicalUuid
    profile_id: str = Field(
        min_length=1,
        max_length=160,
        pattern=_PLAYBACK_PROFILE_PATTERN,
        strict=True,
    )
    progress: PlaybackProgressResource | None

    @field_validator("edition_id")
    @classmethod
    def validate_edition_id(cls, value: UUID) -> UUID:
        return _rfc4122_uuid(value, field_name="edition_id")


@dataclass(frozen=True, slots=True)
class PlaybackMediaRead:
    decision: MediaReadDecision
    body: Iterable[bytes]


class PlaybackApiBackend(Protocol):
    def get_manifest(
        self, edition_id: UUID, manifest_revision: int | None
    ) -> ManifestRead: ...

    def prepare_range(
        self,
        edition_id: UUID,
        payload: PrepareRangeRequest,
        idempotency_key: str,
    ) -> PrepareRangeResult: ...

    def restore_progress(
        self,
        edition_id: UUID,
        profile_id: str,
    ) -> PlaybackResumeProjection | None: ...

    def save_progress(
        self,
        edition_id: UUID,
        payload: SavePlaybackProgressRequest,
    ) -> PlaybackResumeProjection: ...

    def read_media(
        self,
        *,
        asset_id: UUID,
        edition_id: UUID | None,
        manifest_revision: int | None,
        voice_preview_id: UUID | None,
        generic_voice_slot_id: UUID | None,
        method: str,
        range_header: str | None,
        if_range: str | None,
        if_none_match: str | None,
    ) -> PlaybackMediaRead: ...


PlaybackApiBackendFactory = Callable[[Session], PlaybackApiBackend]
VoicePreviewMediaResolver = Callable[[Session, UUID, UUID], MediaAsset]
GenericVoiceSlotMediaResolver = Callable[[Session, UUID, UUID], MediaAsset]


PlaybackApiFault = NarrationProductionApiFault
PLAYBACK_API_ERROR_HTTP_STATUS = NARRATION_PRODUCTION_ERROR_STATUS


def _detail(fault: PlaybackApiFault) -> PlaybackApiErrorDetail:
    return PlaybackApiErrorDetail(
        code=fault.code,
        message=fault.message,
        retryable=fault.retryable,
        field=fault.field,
        current_version=fault.current_version,
    )


class _UnavailableBackend:
    def _raise(self) -> None:
        raise PlaybackApiFault(
            PlaybackApiErrorCode.BACKEND_NOT_INSTALLED,
            "朗读播放后端尚未通过 T4-GATE 接线。",
        )

    def get_manifest(
        self, edition_id: UUID, manifest_revision: int | None
    ) -> ManifestRead:
        del edition_id, manifest_revision
        self._raise()

    def prepare_range(
        self,
        edition_id: UUID,
        payload: PrepareRangeRequest,
        idempotency_key: str,
    ) -> PrepareRangeResult:
        del edition_id, payload, idempotency_key
        self._raise()

    def restore_progress(
        self,
        edition_id: UUID,
        profile_id: str,
    ) -> PlaybackResumeProjection | None:
        del edition_id, profile_id
        self._raise()

    def save_progress(
        self,
        edition_id: UUID,
        payload: SavePlaybackProgressRequest,
    ) -> PlaybackResumeProjection:
        del edition_id, payload
        self._raise()

    def read_media(self, **kwargs: object) -> PlaybackMediaRead:
        del kwargs
        self._raise()


class _StorageUnavailableBackend(_UnavailableBackend):
    def _raise(self) -> None:
        raise PlaybackApiFault(
            PlaybackApiErrorCode.STORAGE_UNAVAILABLE,
            "朗读播放存储当前不可用。",
            retryable=True,
        )


_backend_factory: PlaybackApiBackendFactory | None = None


def install_playback_api_backend_factory(factory: PlaybackApiBackendFactory) -> None:
    global _backend_factory
    if not callable(factory):
        raise TypeError("playback API backend factory must be callable")
    if _backend_factory is not None and _backend_factory is not factory:
        raise RuntimeError("playback API backend factory is already installed")
    _backend_factory = factory


def uninstall_playback_api_backend_factory(
    factory: PlaybackApiBackendFactory | None = None,
) -> None:
    global _backend_factory
    if factory is not None and _backend_factory is not None and _backend_factory is not factory:
        raise RuntimeError("refusing to remove another playback API backend factory")
    _backend_factory = None


def get_playback_api_backend() -> Iterator[PlaybackApiBackend]:
    factory = _backend_factory
    if factory is None:
        yield _UnavailableBackend()
        return
    dependency = get_session()
    try:
        session = next(dependency)
    except DatabaseNotConfigured:
        yield _StorageUnavailableBackend()
        return
    try:
        yield factory(session)
    finally:
        dependency.close()


class SqlAlchemyPlaybackApiBackend:
    """Production adapter; callers inject the already-configured storage roots."""

    def __init__(
        self,
        session: Session,
        storage: NarrationStorage,
        *,
        can_promote_jobs: Callable[[], bool] | None = None,
        resolve_voice_preview_media: VoicePreviewMediaResolver | None = None,
        resolve_generic_voice_slot_media: GenericVoiceSlotMediaResolver | None = None,
    ) -> None:
        self.session = session
        self.storage = storage
        self._can_promote_jobs = (
            can_promote_jobs if can_promote_jobs is not None else (lambda: True)
        )
        self._resolve_voice_preview_media = resolve_voice_preview_media
        self._resolve_generic_voice_slot_media = resolve_generic_voice_slot_media

    def get_manifest(
        self, edition_id: UUID, manifest_revision: int | None
    ) -> ManifestRead:
        return load_public_manifest(
            SqlAlchemyNarrationStore(self.session),
            edition_id=edition_id,
            manifest_revision=manifest_revision,
        )

    def prepare_range(
        self,
        edition_id: UUID,
        payload: PrepareRangeRequest,
        idempotency_key: str,
    ) -> PrepareRangeResult:
        with self.session.begin():
            store = SqlAlchemyNarrationStore(self.session)

            def promote(job):  # type: ignore[no-untyped-def]
                try:
                    production_ready = self._can_promote_jobs()
                except Exception as error:
                    raise PlaybackApiFault(
                        PlaybackApiErrorCode.BACKEND_NOT_INSTALLED,
                        "朗读生产服务当前不可用，未提升待生成任务。",
                        retryable=True,
                    ) from error
                if production_ready is not True:
                    raise PlaybackApiFault(
                        PlaybackApiErrorCode.BACKEND_NOT_INSTALLED,
                        "朗读生产服务当前不可用，未提升待生成任务。",
                        retryable=True,
                    )
                if job.base_priority >= MAX_PRIORITY:
                    return False
                before = (job.interactive_priority, job.interactive_priority_expires_at)
                enqueue_job(
                    self.session,
                    scope=NarrationRequestScope.fixed_local(),
                    job_kind=job.job_kind,
                    input_hash=job.input_hash,
                    idempotency_key=job.idempotency_key,
                    resource_class=job.resource_class,
                    novel_id=job.novel_id,
                    request_id=job.request_id,
                    base_priority=job.base_priority,
                    max_attempts=job.max_attempts,
                    interactive_priority=min(
                        MAX_PRIORITY, max(100, job.base_priority + 1)
                    ),
                    interactive_priority_expires_at=utc_now()
                    + timedelta(seconds=60),
                )
                return before != (
                    job.interactive_priority,
                    job.interactive_priority_expires_at,
                )

            return prepare_manifest_range(
                store,
                PrepareRangeCommand(
                    edition_id=edition_id,
                    start_segment_id=payload.start_segment_id,
                    reason=payload.reason,
                    expected_manifest_revision=payload.expected_manifest_revision,
                    idempotency_key=idempotency_key,
                ),
                promote_job=promote,
            )

    def restore_progress(
        self,
        edition_id: UUID,
        profile_id: str,
    ) -> PlaybackResumeProjection | None:
        return restore_playback_progress(
            SqlAlchemyNarrationStore(self.session),
            edition_id=edition_id,
            profile_id=profile_id,
        )

    def save_progress(
        self,
        edition_id: UUID,
        payload: SavePlaybackProgressRequest,
    ) -> PlaybackResumeProjection:
        with self.session.begin():
            store = SqlAlchemyNarrationStore(self.session)
            scope = NarrationRequestScope.fixed_local()
            edition = store.get(NarrationEdition, edition_id, for_update=True)
            if edition is None:
                raise NarrationNotFound("Edition not found")
            if (
                edition.owner_id != scope.owner_id
                or edition.workspace_id != scope.workspace_id
            ):
                raise NarrationScopeMismatch("Edition is outside fixed local scope")
            manifest = store.find_one(
                NarrationManifest,
                edition_id=edition.id,
                manifest_revision=payload.manifest_revision,
            )
            if manifest is None:
                raise NarrationNotFound("Manifest revision not found")
            if f'"{manifest.etag_sha256}"' != payload.manifest_etag:
                raise NarrationCasConflict("playback Manifest ETag changed")
            edition_segment = (
                store.get(NarrationEditionSegment, payload.edition_segment_id)
                if payload.edition_segment_id is not None
                else store.find_one(
                    NarrationEditionSegment,
                    edition_id=edition.id,
                    segment_id=payload.segment_id,
                )
            )
            if edition_segment is None:
                raise NarrationNotFound("Edition segment not found")
            if (
                edition_segment.edition_id != edition.id
                or edition_segment.segment_id != payload.segment_id
                or (
                    payload.edition_segment_id is not None
                    and edition_segment.id != payload.edition_segment_id
                )
            ):
                raise NarrationScopeMismatch(
                    "playback segment identity belongs to another Edition"
                )
            saved = save_playback_progress(
                store,
                SavePlaybackProgress(
                    profile_id=payload.profile_id,
                    edition_id=edition_id,
                    manifest_revision=payload.manifest_revision,
                    edition_segment_id=edition_segment.id,
                    offset_ms=payload.offset_ms,
                    last_legal_start_ordinal=payload.last_legal_start_ordinal,
                    playback_rate_millis=payload.playback_rate_millis,
                    expected_updated_at=payload.expected_updated_at,
                ),
            )
            restored = restore_playback_progress(
                store,
                edition_id=edition_id,
                profile_id=payload.profile_id,
            )
            if restored is None or restored.progress_updated_at != saved.updated_at:
                raise InvalidNarrationState(
                    "saved playback progress cannot be restored exactly"
                )
            return restored

    def read_media(
        self,
        *,
        asset_id: UUID,
        edition_id: UUID | None,
        manifest_revision: int | None,
        voice_preview_id: UUID | None,
        generic_voice_slot_id: UUID | None,
        method: str,
        range_header: str | None,
        if_range: str | None,
        if_none_match: str | None,
    ) -> PlaybackMediaRead:
        preview_branch = voice_preview_id is not None
        generic_branch = generic_voice_slot_id is not None
        edition_branch = edition_id is not None or manifest_revision is not None
        edition_complete = edition_id is not None and manifest_revision is not None
        if sum((preview_branch, generic_branch, edition_complete)) != 1 or (
            edition_branch and not edition_complete
        ):
            raise PlaybackApiFault(
                PlaybackApiErrorCode.REQUEST_VALIDATION_FAILED,
                "媒体读取必须且只能选择一种授权。",
            )
        if preview_branch:
            resolver = self._resolve_voice_preview_media
            if resolver is None:
                raise PlaybackApiFault(
                    PlaybackApiErrorCode.BACKEND_NOT_INSTALLED,
                    "音色试听媒体后端尚未通过产品门禁。",
                )
            assert voice_preview_id is not None
            asset = resolver(self.session, voice_preview_id, asset_id)
        elif generic_branch:
            resolver = self._resolve_generic_voice_slot_media
            if resolver is None:
                raise PlaybackApiFault(
                    PlaybackApiErrorCode.BACKEND_NOT_INSTALLED,
                    "通用音色试听媒体后端尚未通过产品门禁。",
                )
            assert generic_voice_slot_id is not None
            asset = resolver(self.session, generic_voice_slot_id, asset_id)
        else:
            if edition_id is None or manifest_revision is None:
                raise PlaybackApiFault(
                    PlaybackApiErrorCode.REQUEST_VALIDATION_FAILED,
                    "Edition 媒体读取缺少 Manifest 授权。",
                )
            store = SqlAlchemyNarrationStore(self.session)
            asset = resolve_playback_media_asset(
                store,
                edition_id=edition_id,
                manifest_revision=manifest_revision,
                asset_id=asset_id,
            )
        # The reachability check is a bounded DB read.  Detach its immutable
        # evidence and close the read transaction before hashing/opening media
        # bytes; the returned read plan still fences the exact inode/size.
        self.session.expunge(asset)
        self.session.rollback()
        decision = plan_media_read(
            self.storage,
            asset,
            method=method,
            range_header=range_header,
            if_range=if_range,
            if_none_match=if_none_match,
        )
        return PlaybackMediaRead(
            decision=decision,
            body=stream_read_decision(self.storage, decision),
        )


def build_playback_api_backend_factory(
    storage: NarrationStorage,
    *,
    can_promote_jobs: Callable[[], bool] | None = None,
    resolve_voice_preview_media: VoicePreviewMediaResolver | None = None,
    resolve_generic_voice_slot_media: GenericVoiceSlotMediaResolver | None = None,
) -> PlaybackApiBackendFactory:
    if type(storage) is not NarrationStorage:
        raise TypeError("playback backend factory requires NarrationStorage")
    if can_promote_jobs is not None and not callable(can_promote_jobs):
        raise TypeError("playback promotion guard must be callable")
    if resolve_voice_preview_media is not None and not callable(
        resolve_voice_preview_media
    ):
        raise TypeError("voice preview media resolver must be callable")
    if resolve_generic_voice_slot_media is not None and not callable(
        resolve_generic_voice_slot_media
    ):
        raise TypeError("generic voice slot media resolver must be callable")

    def factory(session: Session) -> PlaybackApiBackend:
        return SqlAlchemyPlaybackApiBackend(
            session,
            storage,
            can_promote_jobs=can_promote_jobs,
            resolve_voice_preview_media=resolve_voice_preview_media,
            resolve_generic_voice_slot_media=resolve_generic_voice_slot_media,
        )

    return factory


def _fault_from_error(error: Exception) -> PlaybackApiFault:
    if isinstance(error, PlaybackApiFault):
        return error
    if isinstance(error, NarrationNotFound):
        return PlaybackApiFault(
            PlaybackApiErrorCode.RESOURCE_NOT_FOUND, "找不到请求的朗读资源。"
        )
    if isinstance(error, NarrationScopeMismatch):
        return PlaybackApiFault(
            PlaybackApiErrorCode.SCOPE_VIOLATION, "找不到请求的朗读资源。"
        )
    if isinstance(error, NarrationCasConflict):
        return PlaybackApiFault(
            PlaybackApiErrorCode.VERSION_CONFLICT,
            "Manifest 已更新，请刷新后重试。",
        )
    if isinstance(error, InvalidNarrationState):
        if str(error) == "unavailable_private_voice_deleted":
            return PlaybackApiFault(
                PlaybackApiErrorCode.INVALID_STATE,
                "这个历史朗读使用的私人音色已删除，声音文件不再可用。",
                retryable=False,
            )
        return PlaybackApiFault(
            PlaybackApiErrorCode.INVALID_STATE,
            "当前朗读版本尚不可播放。",
            retryable=True,
        )
    if isinstance(error, MediaPolicyError):
        return PlaybackApiFault(
            PlaybackApiErrorCode.RESOURCE_NOT_FOUND, "找不到请求的朗读媒体。"
        )
    if isinstance(error, (StorageError, SQLAlchemyError, JobServiceError)):
        return PlaybackApiFault(
            PlaybackApiErrorCode.STORAGE_UNAVAILABLE,
            "朗读播放存储当前不可用。",
            retryable=True,
        )
    if isinstance(error, NarrationServiceError):
        return PlaybackApiFault(
            PlaybackApiErrorCode.INVALID_STATE, "朗读资源未通过领域校验。"
        )
    return PlaybackApiFault(
        PlaybackApiErrorCode.RESPONSE_CONTRACT_VIOLATION,
        "朗读播放服务返回了不兼容的数据。",
    )


def _raise_http(error: Exception) -> None:
    fault = _fault_from_error(error)
    raise HTTPException(
        status_code=PLAYBACK_API_ERROR_HTTP_STATUS[fault.code],
        detail=_detail(fault).model_dump(mode="json"),
    ) from error


def _error_response(fault: PlaybackApiFault) -> JSONResponse:
    return JSONResponse(
        status_code=PLAYBACK_API_ERROR_HTTP_STATUS[fault.code],
        content={"detail": _detail(fault).model_dump(mode="json")},
        headers={"Cache-Control": "no-store"},
    )


class PlaybackContractRoute(APIRoute):
    def get_route_handler(self):  # type: ignore[no-untyped-def]
        original = super().get_route_handler()

        async def route_handler(request: Request) -> Response:
            try:
                response = await original(request)
            except RequestValidationError:
                return _error_response(
                    PlaybackApiFault(
                        PlaybackApiErrorCode.REQUEST_VALIDATION_FAILED,
                        "请求字段不符合朗读播放契约。",
                    )
                )
            except ResponseValidationError:
                return _error_response(
                    PlaybackApiFault(
                        PlaybackApiErrorCode.RESPONSE_CONTRACT_VIOLATION,
                        "朗读播放服务返回了不兼容的数据。",
                    )
                )
            except HTTPException as error:
                response = JSONResponse(
                    status_code=error.status_code,
                    content={"detail": jsonable_encoder(error.detail)},
                    headers=error.headers,
                )
            response.headers.setdefault("Cache-Control", "no-store")
            return response

        return route_handler


router = APIRouter(
    route_class=PlaybackContractRoute,
    dependencies=[Depends(require_narration_t4_http_access)],
)


def _if_none_match_matches(value: str | None, etag: str) -> bool:
    if value is None:
        return False
    return any(
        candidate.strip() in {"*", etag, f"W/{etag}"}
        for candidate in value.split(",")
    )


@router.get("/narration-editions/{edition_id}/manifest")
def get_manifest(
    edition_id: CanonicalUuid,
    manifest_revision: int | None = Query(default=None, ge=1),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    backend: PlaybackApiBackend = Depends(get_playback_api_backend),
) -> Response:
    try:
        result = backend.get_manifest(edition_id, manifest_revision)
    except Exception as error:
        _raise_http(error)
    try:
        payload = parse_manifest_v2(result.payload)
        segments = payload["segments"]
        if (
            result.edition_id != edition_id
            or payload["edition_id"] != str(edition_id)
            or result.manifest_revision != payload["manifest_revision"]
            or result.etag != payload["etag"]
            or (
                manifest_revision is not None
                and result.manifest_revision != manifest_revision
            )
            or not isinstance(segments, list)
            or segments[0]["render_status"] != "ready"
        ):
            raise PlaybackApiFault(
                PlaybackApiErrorCode.RESPONSE_CONTRACT_VIOLATION,
                "朗读播放服务返回了错误的 Manifest 范围。",
            )
    except PlaybackApiFault as error:
        _raise_http(error)
    except Exception as error:
        _raise_http(
            PlaybackApiFault(
                PlaybackApiErrorCode.RESPONSE_CONTRACT_VIOLATION,
                "朗读播放服务返回了不兼容的 Manifest。",
            )
        )
    if _if_none_match_matches(if_none_match, result.etag):
        return Response(
            status_code=status.HTTP_304_NOT_MODIFIED,
            headers={"ETag": result.etag, "Cache-Control": "private, no-cache"},
        )
    return JSONResponse(
        content=jsonable_encoder(payload),
        headers={"ETag": result.etag, "Cache-Control": "private, no-cache"},
    )


def _progress_response(
    *,
    edition_id: UUID,
    profile_id: str,
    progress: PlaybackResumeProjection | None,
) -> PlaybackProgressResponse:
    if progress is None:
        return PlaybackProgressResponse(
            edition_id=edition_id,
            profile_id=profile_id,
            progress=None,
        )
    if progress.edition_id != edition_id or progress.profile_id != profile_id:
        raise PlaybackApiFault(
            PlaybackApiErrorCode.RESPONSE_CONTRACT_VIOLATION,
            "朗读播放服务返回了错误的进度范围。",
        )
    return PlaybackProgressResponse(
        edition_id=edition_id,
        profile_id=profile_id,
        progress=PlaybackProgressResource(
            manifest_revision=progress.manifest_revision,
            manifest_etag=progress.manifest_etag,
            edition_segment_id=progress.edition_segment_id,
            segment_id=progress.segment_id,
            ordinal=progress.ordinal,
            offset_ms=progress.offset_ms,
            last_legal_start_ordinal=progress.last_legal_start_ordinal,
            playback_rate_millis=progress.playback_rate_millis,
            manifest_advanced=progress.manifest_advanced,
            progress_updated_at=progress.progress_updated_at,
        ),
    )


@router.get(
    "/narration-editions/{edition_id}/playback-progress",
    response_model=PlaybackProgressResponse,
)
def get_playback_progress(
    edition_id: CanonicalUuid,
    profile_id: str = Query(
        min_length=1,
        max_length=160,
        pattern=_PLAYBACK_PROFILE_PATTERN,
    ),
    backend: PlaybackApiBackend = Depends(get_playback_api_backend),
) -> PlaybackProgressResponse:
    try:
        return _progress_response(
            edition_id=edition_id,
            profile_id=profile_id,
            progress=backend.restore_progress(edition_id, profile_id),
        )
    except Exception as error:
        _raise_http(error)


@router.put(
    "/narration-editions/{edition_id}/playback-progress",
    response_model=PlaybackProgressResponse,
)
def put_playback_progress(
    edition_id: CanonicalUuid,
    payload: SavePlaybackProgressRequest,
    profile_id: str = Query(
        min_length=1,
        max_length=160,
        pattern=_PLAYBACK_PROFILE_PATTERN,
    ),
    backend: PlaybackApiBackend = Depends(get_playback_api_backend),
) -> PlaybackProgressResponse:
    try:
        if payload.profile_id != profile_id:
            raise PlaybackApiFault(
                PlaybackApiErrorCode.REQUEST_VALIDATION_FAILED,
                "查询与请求体的播放 profile_id 必须完全一致。",
                field="profile_id",
            )
        progress = backend.save_progress(edition_id, payload)
        if progress is None:
            raise PlaybackApiFault(
                PlaybackApiErrorCode.RESPONSE_CONTRACT_VIOLATION,
                "朗读播放服务未返回已保存的进度。",
            )
        return _progress_response(
            edition_id=edition_id,
            profile_id=profile_id,
            progress=progress,
        )
    except Exception as error:
        _raise_http(error)


@router.post(
    "/narration-editions/{edition_id}/prepare-range",
    response_model=PrepareRangeResponse,
)
def prepare_range(
    edition_id: CanonicalUuid,
    payload: PrepareRangeRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
        pattern=_IDEMPOTENCY_KEY_PATTERN,
    ),
    backend: PlaybackApiBackend = Depends(get_playback_api_backend),
) -> PrepareRangeResponse:
    try:
        result = backend.prepare_range(edition_id, payload, idempotency_key)
        if result.edition_id != edition_id or result.start_segment_id != payload.start_segment_id:
            raise PlaybackApiFault(
                PlaybackApiErrorCode.RESPONSE_CONTRACT_VIOLATION,
                "朗读播放服务返回了错误的请求范围。",
            )
        return PrepareRangeResponse(
            edition_id=result.edition_id,
            start_segment_id=result.start_segment_id,
            start_ordinal=result.start_ordinal,
            state=result.state,
            manifest_revision=result.manifest_revision,
            manifest_etag=result.manifest_etag,
            ready_range=result.ready_range,  # type: ignore[arg-type]
            promoted_job_ids=list(result.promoted_job_ids),
        )
    except Exception as error:
        _raise_http(error)


def _media_response(
    result: PlaybackMediaRead, *, method: Literal["GET", "HEAD"]
) -> Response:
    decision = result.decision
    headers: dict[str, str] = dict(decision.headers)
    headers["Vary"] = (
        "X-Narration-Edition-Id, X-Narration-Manifest-Revision, "
        "X-Narration-Voice-Preview-Id, "
        "X-Narration-Generic-Voice-Slot-Id, "
        "Range, If-Range, If-None-Match"
    )
    if decision.status not in {200, 206, 304, 416}:
        raise PlaybackApiFault(
            PlaybackApiErrorCode.RESPONSE_CONTRACT_VIOLATION,
            "朗读媒体服务返回了不支持的状态。",
        )
    etag = headers.get("ETag")
    if etag is None or not re.fullmatch(r'"[a-f0-9]{64}"', etag):
        raise PlaybackApiFault(
            PlaybackApiErrorCode.RESPONSE_CONTRACT_VIOLATION,
            "朗读媒体服务缺少强 ETag。",
        )
    if decision.status == 206 and (
        decision.byte_range is None or "Content-Range" not in headers
    ):
        raise PlaybackApiFault(
            PlaybackApiErrorCode.RESPONSE_CONTRACT_VIOLATION,
            "朗读媒体服务返回了不完整的 Range。",
        )
    if decision.status in {304, 416} and decision.send_body:
        raise PlaybackApiFault(
            PlaybackApiErrorCode.RESPONSE_CONTRACT_VIOLATION,
            "无正文媒体状态不能发送正文。",
        )
    if method == "HEAD" and decision.send_body:
        raise PlaybackApiFault(
            PlaybackApiErrorCode.RESPONSE_CONTRACT_VIOLATION,
            "HEAD 朗读媒体响应不能发送正文。",
        )
    if method == "GET" and decision.status in {200, 206} and not decision.send_body:
        raise PlaybackApiFault(
            PlaybackApiErrorCode.RESPONSE_CONTRACT_VIOLATION,
            "GET 朗读媒体响应缺少正文计划。",
        )
    if decision.status in {200, 206}:
        content_type = headers.get("Content-Type", "").split(";", 1)[0].strip()
        if (
            not content_type.startswith("audio/")
            or headers.get("Accept-Ranges") != "bytes"
            or not re.fullmatch(r"\d+", headers.get("Content-Length", ""))
        ):
            raise PlaybackApiFault(
                PlaybackApiErrorCode.RESPONSE_CONTRACT_VIOLATION,
                "朗读媒体响应缺少类型、Range 或长度证据。",
            )
    if decision.status == 206 and not re.fullmatch(
        r"bytes \d+-\d+/\d+", headers.get("Content-Range", "")
    ):
        raise PlaybackApiFault(
            PlaybackApiErrorCode.RESPONSE_CONTRACT_VIOLATION,
            "朗读媒体响应包含无效的满足范围。",
        )
    if decision.status == 416 and not re.fullmatch(
        r"bytes \*/\d+", headers.get("Content-Range", "")
    ):
        raise PlaybackApiFault(
            PlaybackApiErrorCode.RESPONSE_CONTRACT_VIOLATION,
            "朗读媒体响应包含无效的不可满足范围。",
        )
    if not decision.send_body:
        return Response(status_code=decision.status, headers=headers)
    return StreamingResponse(
        result.body,
        status_code=decision.status,
        headers=headers,
        media_type=None,
    )


def _read_media(
    *,
    method: Literal["GET", "HEAD"],
    asset_id: UUID,
    edition_id: UUID | None,
    manifest_revision: int | None,
    voice_preview_id: UUID | None,
    generic_voice_slot_id: UUID | None,
    range_header: str | None,
    if_range: str | None,
    if_none_match: str | None,
    backend: PlaybackApiBackend,
) -> Response:
    preview_branch = voice_preview_id is not None
    generic_branch = generic_voice_slot_id is not None
    edition_branch = edition_id is not None or manifest_revision is not None
    edition_complete = edition_id is not None and manifest_revision is not None
    if sum((preview_branch, generic_branch, edition_complete)) != 1 or (
        edition_branch and not edition_complete
    ):
        _raise_http(
            PlaybackApiFault(
                PlaybackApiErrorCode.REQUEST_VALIDATION_FAILED,
                "媒体读取必须且只能提供一种完整授权头。",
            )
        )
    try:
        result = backend.read_media(
            asset_id=asset_id,
            edition_id=edition_id,
            manifest_revision=manifest_revision,
            voice_preview_id=voice_preview_id,
            generic_voice_slot_id=generic_voice_slot_id,
            method=method,
            range_header=range_header,
            if_range=if_range,
            if_none_match=if_none_match,
        )
        return _media_response(result, method=method)
    except Exception as error:
        _raise_http(error)


def _reject_media_query(request: Request) -> None:
    if request.url.query:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_detail(
                PlaybackApiFault(
                    PlaybackApiErrorCode.REQUEST_VALIDATION_FAILED,
                    "朗读媒体 URL 不接受 query 或 token。",
                )
            ).model_dump(mode="json"),
        )


@router.get("/media-assets/{asset_id}/content")
def get_media_content(
    asset_id: CanonicalUuid,
    request: Request,
    edition_id: CanonicalUuid | None = Header(
        default=None, alias="X-Narration-Edition-Id"
    ),
    manifest_revision: int | None = Header(
        default=None, alias="X-Narration-Manifest-Revision", ge=1
    ),
    voice_preview_id: CanonicalUuid | None = Header(
        default=None, alias="X-Narration-Voice-Preview-Id"
    ),
    generic_voice_slot_id: CanonicalUuid | None = Header(
        default=None, alias="X-Narration-Generic-Voice-Slot-Id"
    ),
    range_header: str | None = Header(default=None, alias="Range"),
    if_range: str | None = Header(default=None, alias="If-Range"),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    backend: PlaybackApiBackend = Depends(get_playback_api_backend),
) -> Response:
    _reject_media_query(request)
    return _read_media(
        method="GET",
        asset_id=asset_id,
        edition_id=edition_id,
        manifest_revision=manifest_revision,
        voice_preview_id=voice_preview_id,
        generic_voice_slot_id=generic_voice_slot_id,
        range_header=range_header,
        if_range=if_range,
        if_none_match=if_none_match,
        backend=backend,
    )


@router.head("/media-assets/{asset_id}/content")
def head_media_content(
    asset_id: CanonicalUuid,
    request: Request,
    edition_id: CanonicalUuid | None = Header(
        default=None, alias="X-Narration-Edition-Id"
    ),
    manifest_revision: int | None = Header(
        default=None, alias="X-Narration-Manifest-Revision", ge=1
    ),
    voice_preview_id: CanonicalUuid | None = Header(
        default=None, alias="X-Narration-Voice-Preview-Id"
    ),
    generic_voice_slot_id: CanonicalUuid | None = Header(
        default=None, alias="X-Narration-Generic-Voice-Slot-Id"
    ),
    range_header: str | None = Header(default=None, alias="Range"),
    if_range: str | None = Header(default=None, alias="If-Range"),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    backend: PlaybackApiBackend = Depends(get_playback_api_backend),
) -> Response:
    _reject_media_query(request)
    return _read_media(
        method="HEAD",
        asset_id=asset_id,
        edition_id=edition_id,
        manifest_revision=manifest_revision,
        voice_preview_id=voice_preview_id,
        generic_voice_slot_id=generic_voice_slot_id,
        range_header=range_header,
        if_range=if_range,
        if_none_match=if_none_match,
        backend=backend,
    )


__all__ = [
    "NARRATION_PRODUCTION_API_VERSION",
    "PLAYBACK_API_ERROR_HTTP_STATUS",
    "PlaybackApiBackend",
    "PlaybackApiBackendFactory",
    "PlaybackApiErrorCode",
    "PlaybackApiErrorDetail",
    "PlaybackApiFault",
    "PlaybackMediaRead",
    "GenericVoiceSlotMediaResolver",
    "PlaybackProgressResource",
    "PlaybackProgressResponse",
    "VoicePreviewMediaResolver",
    "PrepareRangeRequest",
    "PrepareRangeResponse",
    "ReadyRangeResource",
    "SavePlaybackProgressRequest",
    "SqlAlchemyPlaybackApiBackend",
    "build_playback_api_backend_factory",
    "get_playback_api_backend",
    "install_playback_api_backend_factory",
    "router",
    "uninstall_playback_api_backend_factory",
]
