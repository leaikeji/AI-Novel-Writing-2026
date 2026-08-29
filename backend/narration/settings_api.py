"""Frozen T2 narration settings/voice HTTP facade.

This router owns the wire surface only.  A later T2 integration gate installs
one scoped backend factory whose implementation delegates to the settings,
voice, voice-pool, pronunciation, privacy, and cache domain modules.  Until
that happens every operation fails closed with a stable error code.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Final, Iterator, Protocol, TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse, Response

from ..database import DatabaseNotConfigured, get_session

from . import schemas as wire
from .services import (
    IdempotencyConflict,
    InvalidNarrationState,
    NarrationCasConflict,
    NarrationNotFound,
    NarrationScopeMismatch,
    NarrationServiceError,
    VoiceRightsUnavailable,
)


_ResponseModel = TypeVar("_ResponseModel", bound=BaseModel)
_MULTIPART_ENVELOPE_ALLOWANCE: Final = 64 * 1024
_IDEMPOTENCY_HEADER_PATTERN: Final = r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$"


class NarrationSettingsOperation(str, Enum):
    GET_OVERVIEW = "get_overview"
    GET_SETTINGS = "get_settings"
    PUT_SETTINGS = "put_settings"
    PUT_PLAYBACK_PREFERENCES = "put_playback_preferences"
    LIST_SCOPE_OVERRIDES = "list_scope_overrides"
    PUT_SCOPE_OVERRIDE = "put_scope_override"
    CREATE_CLOUD_CONSENT = "create_cloud_consent"
    REVOKE_CLOUD_CONSENT = "revoke_cloud_consent"
    LIST_OFFICIAL_PRESETS = "list_official_presets"
    SELECT_OFFICIAL_VOICE = "select_official_voice"
    LIST_VOICE_PROFILES = "list_voice_profiles"
    CREATE_VOICE_PROFILE = "create_voice_profile"
    GET_VOICE_PROFILE = "get_voice_profile"
    PUT_VOICE_PROFILE = "put_voice_profile"
    ARCHIVE_VOICE_PROFILE = "archive_voice_profile"
    CREATE_PRESET_VOICE_VERSION = "create_preset_voice_version"
    CREATE_UPLOADED_VOICE_VERSION = "create_uploaded_voice_version"
    CREATE_VOICE_PREVIEW = "create_voice_preview"
    GET_VOICE_PREVIEW = "get_voice_preview"
    LOCK_VOICE_PROFILE = "lock_voice_profile"
    LIST_CHARACTER_VOICE_BINDINGS = "list_character_voice_bindings"
    GET_CHARACTER_VOICE_BINDING = "get_character_voice_binding"
    PUT_CHARACTER_VOICE_BINDING = "put_character_voice_binding"
    GET_GENERIC_VOICE_POOL = "get_generic_voice_pool"
    PUT_GENERIC_VOICE_POOL = "put_generic_voice_pool"
    GET_CASTING_RULES = "get_casting_rules"
    PUT_CASTING_RULES = "put_casting_rules"
    GET_PRONUNCIATION_PROFILE = "get_pronunciation_profile"
    PUT_PRONUNCIATION_PROFILE = "put_pronunciation_profile"
    GET_CACHE_STATUS = "get_cache_status"
    PREVIEW_CACHE_CLEANUP = "preview_cache_cleanup"
    EXECUTE_CACHE_CLEANUP = "execute_cache_cleanup"


@dataclass(frozen=True, slots=True)
class NarrationSettingsApiCommand:
    operation: NarrationSettingsOperation
    novel_id: UUID | None = None
    profile_id: UUID | None = None
    preview_id: UUID | None = None
    character_id: UUID | None = None
    scope_kind: wire.NarrationScopeKind | None = None
    scope_id: UUID | None = None
    payload: BaseModel | None = None
    expected_version: int | None = None
    include_library: bool | None = None
    idempotency_key: str | None = None
    multipart_content_type: str | None = None
    multipart_body: bytes | None = None


class NarrationSettingsApiBackend(Protocol):
    """Single typed dispatch boundary consumed by the frozen route facade."""

    def dispatch(self, command: NarrationSettingsApiCommand) -> object: ...


NarrationSettingsBackendFactory = Callable[
    [Session, Request], NarrationSettingsApiBackend
]


class NarrationApiFault(RuntimeError):
    def __init__(
        self,
        code: wire.NarrationErrorCode,
        message: str,
        *,
        retryable: bool = False,
        field: str | None = None,
        current_version: int | None = None,
        capability: wire.CapabilityKey | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.field = field
        self.current_version = current_version
        self.capability = capability


NARRATION_ERROR_HTTP_STATUS: Final[dict[wire.NarrationErrorCode, int]] = {
    wire.NarrationErrorCode.REQUEST_VALIDATION_FAILED: status.HTTP_422_UNPROCESSABLE_CONTENT,
    wire.NarrationErrorCode.RESPONSE_CONTRACT_VIOLATION: status.HTTP_500_INTERNAL_SERVER_ERROR,
    wire.NarrationErrorCode.SETTINGS_BACKEND_NOT_INSTALLED: status.HTTP_503_SERVICE_UNAVAILABLE,
    wire.NarrationErrorCode.CAPABILITY_DISABLED: status.HTTP_409_CONFLICT,
    wire.NarrationErrorCode.MODEL_UNAVAILABLE: status.HTTP_503_SERVICE_UNAVAILABLE,
    wire.NarrationErrorCode.STORAGE_UNAVAILABLE: status.HTTP_503_SERVICE_UNAVAILABLE,
    wire.NarrationErrorCode.DISK_SPACE_INSUFFICIENT: status.HTTP_507_INSUFFICIENT_STORAGE,
    wire.NarrationErrorCode.RESOURCE_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    wire.NarrationErrorCode.SCOPE_VIOLATION: status.HTTP_404_NOT_FOUND,
    wire.NarrationErrorCode.VERSION_CONFLICT: status.HTTP_409_CONFLICT,
    wire.NarrationErrorCode.INVALID_STATE: status.HTTP_409_CONFLICT,
    wire.NarrationErrorCode.IDEMPOTENCY_CONFLICT: status.HTTP_409_CONFLICT,
    wire.NarrationErrorCode.VOICE_PROFILE_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    wire.NarrationErrorCode.VOICE_VERSION_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    wire.NarrationErrorCode.VOICE_VERSION_NOT_LOCKED: status.HTTP_409_CONFLICT,
    wire.NarrationErrorCode.VOICE_RIGHTS_REQUIRED: status.HTTP_403_FORBIDDEN,
    wire.NarrationErrorCode.VOICE_RIGHTS_UNAVAILABLE: status.HTTP_403_FORBIDDEN,
    wire.NarrationErrorCode.VOICE_SOURCE_UNAVAILABLE: status.HTTP_409_CONFLICT,
    wire.NarrationErrorCode.REFERENCE_AUDIO_INVALID: status.HTTP_422_UNPROCESSABLE_CONTENT,
    wire.NarrationErrorCode.PREVIEW_UNAVAILABLE: status.HTTP_503_SERVICE_UNAVAILABLE,
    wire.NarrationErrorCode.PREVIEW_FAILED: status.HTTP_502_BAD_GATEWAY,
    wire.NarrationErrorCode.CLOUD_CONSENT_REQUIRED: status.HTTP_412_PRECONDITION_FAILED,
    wire.NarrationErrorCode.CLOUD_CONSENT_REVOKED: status.HTTP_412_PRECONDITION_FAILED,
    wire.NarrationErrorCode.GENERIC_VOICE_POOL_UNAVAILABLE: status.HTTP_409_CONFLICT,
    wire.NarrationErrorCode.UNSUPPORTED_MEDIA_TYPE: status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    wire.NarrationErrorCode.PAYLOAD_TOO_LARGE: status.HTTP_413_CONTENT_TOO_LARGE,
    wire.NarrationErrorCode.VALIDATION_FAILED: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


def narration_error_detail(fault: NarrationApiFault) -> wire.NarrationApiErrorDetail:
    return wire.NarrationApiErrorDetail(
        code=fault.code,
        message=fault.message,
        retryable=fault.retryable,
        field=fault.field,
        current_version=fault.current_version,
        capability=fault.capability,
    )


class _UnavailableBackend:
    def dispatch(self, command: NarrationSettingsApiCommand) -> object:
        del command
        raise NarrationApiFault(
            wire.NarrationErrorCode.SETTINGS_BACKEND_NOT_INSTALLED,
            "朗读设置后端尚未通过 T2-GATE 接线。",
            retryable=False,
            capability=wire.CapabilityKey.READING_SETTINGS,
        )


class _StorageUnavailableBackend:
    def dispatch(self, command: NarrationSettingsApiCommand) -> object:
        del command
        raise NarrationApiFault(
            wire.NarrationErrorCode.STORAGE_UNAVAILABLE,
            "朗读设置数据库当前不可用。",
            retryable=True,
        )


_backend_factory: NarrationSettingsBackendFactory | None = None


def install_narration_settings_backend_factory(
    factory: NarrationSettingsBackendFactory,
) -> None:
    """Install one integration-owned factory without silently replacing it."""

    global _backend_factory
    if not callable(factory):
        raise TypeError("narration settings backend factory must be callable")
    if _backend_factory is not None and _backend_factory is not factory:
        raise RuntimeError("narration settings backend factory is already installed")
    _backend_factory = factory


def uninstall_narration_settings_backend_factory(
    factory: NarrationSettingsBackendFactory | None = None,
) -> None:
    """Remove only the expected factory so PawApp unload is idempotent."""

    global _backend_factory
    if (
        factory is not None
        and _backend_factory is not None
        and _backend_factory is not factory
    ):
        raise RuntimeError("refusing to remove another narration backend factory")
    _backend_factory = None


def get_narration_settings_backend(
    request: Request,
) -> Iterator[NarrationSettingsApiBackend]:
    """Resolve no database dependency until the integration factory exists."""

    factory = _backend_factory
    if factory is None:
        yield _UnavailableBackend()
        return
    session_dependency = get_session()
    try:
        session = next(session_dependency)
    except DatabaseNotConfigured:
        yield _StorageUnavailableBackend()
        return
    try:
        yield factory(session, request)
    finally:
        session_dependency.close()


def _field_from_validation(error: RequestValidationError) -> str | None:
    errors = error.errors()
    if not errors:
        return None
    parts = [
        str(item).replace("-", "_").lower()
        for item in errors[0].get("loc", ())
        if isinstance(item, str) and item not in {"body", "path", "query", "header"}
    ]
    candidate = ".".join(parts)
    return candidate if candidate and len(candidate) <= 160 else None


def _error_response(fault: NarrationApiFault) -> JSONResponse:
    detail = narration_error_detail(fault)
    return JSONResponse(
        status_code=NARRATION_ERROR_HTTP_STATUS[fault.code],
        content={"detail": detail.model_dump(mode="json")},
        headers={"Cache-Control": "no-store"},
    )


class NarrationContractRoute(APIRoute):
    """Normalize request/response validation without echoing private inputs."""

    def get_route_handler(self):  # type: ignore[no-untyped-def]
        original = super().get_route_handler()

        async def route_handler(request: Request) -> Response:
            try:
                response = await original(request)
            except RequestValidationError as error:
                return _error_response(
                    NarrationApiFault(
                        wire.NarrationErrorCode.REQUEST_VALIDATION_FAILED,
                        "请求字段不符合朗读设置契约。",
                        field=_field_from_validation(error),
                    )
                )
            except ResponseValidationError:
                return _error_response(
                    NarrationApiFault(
                        wire.NarrationErrorCode.RESPONSE_CONTRACT_VIOLATION,
                        "朗读设置服务返回了不兼容的数据。",
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


router = APIRouter(route_class=NarrationContractRoute)


def _fault_from_service(error: NarrationServiceError) -> NarrationApiFault:
    if isinstance(error, NarrationNotFound):
        return NarrationApiFault(
            wire.NarrationErrorCode.RESOURCE_NOT_FOUND,
            "找不到请求的朗读资源。",
        )
    if isinstance(error, NarrationScopeMismatch):
        return NarrationApiFault(
            wire.NarrationErrorCode.SCOPE_VIOLATION,
            "找不到请求的朗读资源。",
        )
    if isinstance(error, NarrationCasConflict):
        return NarrationApiFault(
            wire.NarrationErrorCode.VERSION_CONFLICT,
            "设置已被其他操作更新，请刷新后重试。",
        )
    if isinstance(error, IdempotencyConflict):
        return NarrationApiFault(
            wire.NarrationErrorCode.IDEMPOTENCY_CONFLICT,
            "幂等键已用于另一份请求。",
        )
    if isinstance(error, InvalidNarrationState):
        return NarrationApiFault(
            wire.NarrationErrorCode.INVALID_STATE,
            "当前朗读资源状态不允许此操作。",
        )
    if isinstance(error, VoiceRightsUnavailable):
        return NarrationApiFault(
            wire.NarrationErrorCode.VOICE_RIGHTS_UNAVAILABLE,
            "该音色的授权当前不可用于新的试听或合成。",
        )
    return NarrationApiFault(
        wire.NarrationErrorCode.VALIDATION_FAILED,
        "朗读设置未通过领域校验。",
    )


def _run(
    backend: NarrationSettingsApiBackend,
    command: NarrationSettingsApiCommand,
    response_model: type[_ResponseModel],
) -> _ResponseModel:
    try:
        raw = backend.dispatch(command)
        return response_model.model_validate(raw)
    except NarrationApiFault as fault:
        raise HTTPException(
            status_code=NARRATION_ERROR_HTTP_STATUS[fault.code],
            detail=narration_error_detail(fault).model_dump(mode="json"),
        ) from fault
    except NarrationServiceError as error:
        fault = _fault_from_service(error)
        raise HTTPException(
            status_code=NARRATION_ERROR_HTTP_STATUS[fault.code],
            detail=narration_error_detail(fault).model_dump(mode="json"),
        ) from error
    except ValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=wire.NarrationApiErrorDetail(
                code=wire.NarrationErrorCode.RESPONSE_CONTRACT_VIOLATION,
                message="朗读设置服务返回了不兼容的数据。",
                retryable=False,
            ).model_dump(mode="json"),
        ) from error


@router.get(
    "/novels/{novel_id}/narration-overview",
    response_model=wire.NarrationOverviewResponse,
)
def narration_overview_get(
    novel_id: UUID,
    backend: NarrationSettingsApiBackend = Depends(get_narration_settings_backend),
) -> wire.NarrationOverviewResponse:
    return _run(
        backend,
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.GET_OVERVIEW,
            novel_id=novel_id,
        ),
        wire.NarrationOverviewResponse,
    )


@router.get(
    "/novels/{novel_id}/narration-settings",
    response_model=wire.NarrationSettingsResource,
)
def narration_settings_get(
    novel_id: UUID,
    backend: NarrationSettingsApiBackend = Depends(get_narration_settings_backend),
) -> wire.NarrationSettingsResource:
    return _run(
        backend,
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.GET_SETTINGS,
            novel_id=novel_id,
        ),
        wire.NarrationSettingsResource,
    )


@router.put(
    "/novels/{novel_id}/narration-settings",
    response_model=wire.NarrationSettingsResource,
)
def narration_settings_put(
    novel_id: UUID,
    payload: wire.UpdateNarrationSettingsRequest,
    backend: NarrationSettingsApiBackend = Depends(get_narration_settings_backend),
) -> wire.NarrationSettingsResource:
    return _run(
        backend,
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.PUT_SETTINGS,
            novel_id=novel_id,
            payload=payload,
        ),
        wire.NarrationSettingsResource,
    )


@router.patch(
    "/novels/{novel_id}/narration-settings/playback-preferences",
    response_model=wire.NarrationSettingsResource,
)
def narration_playback_preferences_put(
    novel_id: UUID,
    payload: wire.UpdateNarrationPlaybackPreferencesRequest,
    backend: NarrationSettingsApiBackend = Depends(get_narration_settings_backend),
) -> wire.NarrationSettingsResource:
    return _run(
        backend,
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.PUT_PLAYBACK_PREFERENCES,
            novel_id=novel_id,
            payload=payload,
        ),
        wire.NarrationSettingsResource,
    )


@router.get(
    "/novels/{novel_id}/narration-scope-overrides",
    response_model=wire.NarrationScopeOverrideListResponse,
)
def narration_scope_overrides_get(
    novel_id: UUID,
    backend: NarrationSettingsApiBackend = Depends(get_narration_settings_backend),
) -> wire.NarrationScopeOverrideListResponse:
    return _run(
        backend,
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.LIST_SCOPE_OVERRIDES,
            novel_id=novel_id,
        ),
        wire.NarrationScopeOverrideListResponse,
    )


@router.put(
    "/novels/{novel_id}/narration-scope-overrides/{scope_kind}/{scope_id}",
    response_model=wire.NarrationScopeOverrideResource,
)
def narration_scope_override_put(
    novel_id: UUID,
    scope_kind: wire.NarrationScopeKind,
    scope_id: UUID,
    payload: wire.PutNarrationScopeOverrideRequest,
    backend: NarrationSettingsApiBackend = Depends(get_narration_settings_backend),
) -> wire.NarrationScopeOverrideResource:
    return _run(
        backend,
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.PUT_SCOPE_OVERRIDE,
            novel_id=novel_id,
            scope_kind=scope_kind,
            scope_id=scope_id,
            payload=payload,
        ),
        wire.NarrationScopeOverrideResource,
    )


@router.post(
    "/novels/{novel_id}/narration-cloud-consents",
    response_model=wire.NarrationCloudConsent,
    status_code=status.HTTP_201_CREATED,
)
def narration_cloud_consent_create(
    novel_id: UUID,
    payload: wire.CreateNarrationCloudConsentRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
        pattern=_IDEMPOTENCY_HEADER_PATTERN,
    ),
    backend: NarrationSettingsApiBackend = Depends(get_narration_settings_backend),
) -> wire.NarrationCloudConsent:
    return _run(
        backend,
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.CREATE_CLOUD_CONSENT,
            novel_id=novel_id,
            payload=payload,
            idempotency_key=idempotency_key,
        ),
        wire.NarrationCloudConsent,
    )


@router.delete(
    "/novels/{novel_id}/narration-cloud-consents/current",
    response_model=wire.NarrationCloudConsent,
)
def narration_cloud_consent_revoke(
    novel_id: UUID,
    payload: wire.RevokeNarrationCloudConsentRequest,
    backend: NarrationSettingsApiBackend = Depends(get_narration_settings_backend),
) -> wire.NarrationCloudConsent:
    return _run(
        backend,
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.REVOKE_CLOUD_CONSENT,
            novel_id=novel_id,
            payload=payload,
            expected_version=payload.expected_version,
        ),
        wire.NarrationCloudConsent,
    )


@router.get("/voice-presets", response_model=wire.OfficialPresetCatalogResponse)
def official_voice_presets_get(
    backend: NarrationSettingsApiBackend = Depends(get_narration_settings_backend),
) -> wire.OfficialPresetCatalogResponse:
    return _run(
        backend,
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.LIST_OFFICIAL_PRESETS,
        ),
        wire.OfficialPresetCatalogResponse,
    )


@router.post(
    "/novels/{novel_id}/official-voice-selections",
    response_model=wire.OfficialVoiceSelectionResponse,
)
def official_voice_selection_create(
    novel_id: UUID,
    payload: wire.OfficialVoiceSelectionRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
        pattern=_IDEMPOTENCY_HEADER_PATTERN,
    ),
    backend: NarrationSettingsApiBackend = Depends(get_narration_settings_backend),
) -> wire.OfficialVoiceSelectionResponse:
    return _run(
        backend,
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.SELECT_OFFICIAL_VOICE,
            novel_id=novel_id,
            character_id=payload.character_id,
            payload=payload,
            idempotency_key=idempotency_key,
        ),
        wire.OfficialVoiceSelectionResponse,
    )


@router.get("/voice-profiles", response_model=wire.VoiceProfileListResponse)
def voice_profiles_get(
    novel_id: UUID | None = Query(default=None),
    include_library: bool = Query(default=True),
    backend: NarrationSettingsApiBackend = Depends(get_narration_settings_backend),
) -> wire.VoiceProfileListResponse:
    return _run(
        backend,
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.LIST_VOICE_PROFILES,
            novel_id=novel_id,
            include_library=include_library,
        ),
        wire.VoiceProfileListResponse,
    )


@router.post(
    "/voice-profiles",
    response_model=wire.VoiceProfileResource,
    status_code=status.HTTP_201_CREATED,
)
def voice_profile_create(
    payload: wire.CreateVoiceProfileRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
        pattern=_IDEMPOTENCY_HEADER_PATTERN,
    ),
    backend: NarrationSettingsApiBackend = Depends(get_narration_settings_backend),
) -> wire.VoiceProfileResource:
    return _run(
        backend,
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.CREATE_VOICE_PROFILE,
            novel_id=payload.novel_id,
            payload=payload,
            idempotency_key=idempotency_key,
        ),
        wire.VoiceProfileResource,
    )


@router.get(
    "/voice-profiles/{profile_id}", response_model=wire.VoiceProfileResource
)
def voice_profile_get(
    profile_id: UUID,
    backend: NarrationSettingsApiBackend = Depends(get_narration_settings_backend),
) -> wire.VoiceProfileResource:
    return _run(
        backend,
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.GET_VOICE_PROFILE,
            profile_id=profile_id,
        ),
        wire.VoiceProfileResource,
    )


@router.put(
    "/voice-profiles/{profile_id}", response_model=wire.VoiceProfileResource
)
def voice_profile_put(
    profile_id: UUID,
    payload: wire.UpdateVoiceProfileRequest,
    backend: NarrationSettingsApiBackend = Depends(get_narration_settings_backend),
) -> wire.VoiceProfileResource:
    return _run(
        backend,
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.PUT_VOICE_PROFILE,
            profile_id=profile_id,
            payload=payload,
        ),
        wire.VoiceProfileResource,
    )


@router.delete(
    "/voice-profiles/{profile_id}", response_model=wire.VoiceProfileResource
)
def voice_profile_archive(
    profile_id: UUID,
    expected_version: int = Query(ge=1),
    backend: NarrationSettingsApiBackend = Depends(get_narration_settings_backend),
) -> wire.VoiceProfileResource:
    return _run(
        backend,
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.ARCHIVE_VOICE_PROFILE,
            profile_id=profile_id,
            expected_version=expected_version,
        ),
        wire.VoiceProfileResource,
    )


@router.post(
    "/voice-profiles/{profile_id}/versions/preset",
    response_model=wire.VoiceProfileVersionResource,
    status_code=status.HTTP_201_CREATED,
)
def preset_voice_version_create(
    profile_id: UUID,
    payload: wire.CreatePresetVoiceVersionRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
        pattern=_IDEMPOTENCY_HEADER_PATTERN,
    ),
    backend: NarrationSettingsApiBackend = Depends(get_narration_settings_backend),
) -> wire.VoiceProfileVersionResource:
    return _run(
        backend,
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.CREATE_PRESET_VOICE_VERSION,
            profile_id=profile_id,
            payload=payload,
            idempotency_key=idempotency_key,
        ),
        wire.VoiceProfileVersionResource,
    )


@router.post(
    "/voice-profiles/{profile_id}/versions/uploaded",
    response_model=wire.VoiceProfileVersionResource,
    status_code=status.HTTP_201_CREATED,
)
async def uploaded_voice_version_create(
    profile_id: UUID,
    request: Request,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
        pattern=_IDEMPOTENCY_HEADER_PATTERN,
    ),
    backend: NarrationSettingsApiBackend = Depends(get_narration_settings_backend),
) -> wire.VoiceProfileVersionResource:
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data;") or "boundary=" not in content_type.lower():
        fault = NarrationApiFault(
            wire.NarrationErrorCode.UNSUPPORTED_MEDIA_TYPE,
            "参考录音必须使用 multipart/form-data，且只包含 metadata 与 reference_audio。",
            field="reference_audio",
            capability=wire.CapabilityKey.REFERENCE_CLONE,
        )
        raise HTTPException(
            status_code=NARRATION_ERROR_HTTP_STATUS[fault.code],
            detail=narration_error_detail(fault).model_dump(mode="json"),
        )
    maximum = wire.REFERENCE_UPLOAD_MAX_BYTES + _MULTIPART_ENVELOPE_ALLOWANCE
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared = int(content_length)
        except ValueError:
            declared = maximum + 1
        if declared < 0 or declared > maximum:
            fault = NarrationApiFault(
                wire.NarrationErrorCode.PAYLOAD_TOO_LARGE,
                "参考录音上传超过允许大小。",
                field="reference_audio",
                capability=wire.CapabilityKey.REFERENCE_CLONE,
            )
            raise HTTPException(
                status_code=NARRATION_ERROR_HTTP_STATUS[fault.code],
                detail=narration_error_detail(fault).model_dump(mode="json"),
            )
    body = await request.body()
    if len(body) > maximum:
        fault = NarrationApiFault(
            wire.NarrationErrorCode.PAYLOAD_TOO_LARGE,
            "参考录音上传超过允许大小。",
            field="reference_audio",
            capability=wire.CapabilityKey.REFERENCE_CLONE,
        )
        raise HTTPException(
            status_code=NARRATION_ERROR_HTTP_STATUS[fault.code],
            detail=narration_error_detail(fault).model_dump(mode="json"),
        )
    # Multipart parsing, fixed FFmpeg normalization and immutable file
    # publication are bounded but blocking.  Keep them off the application
    # event loop; the product port itself still owns its short DB phases.
    return await asyncio.to_thread(
        _run,
        backend,
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.CREATE_UPLOADED_VOICE_VERSION,
            profile_id=profile_id,
            idempotency_key=idempotency_key,
            multipart_content_type=content_type,
            multipart_body=body,
        ),
        wire.VoiceProfileVersionResource,
    )


@router.post(
    "/voice-profiles/{profile_id}/previews",
    response_model=wire.VoicePreviewResource,
    status_code=status.HTTP_202_ACCEPTED,
)
def voice_preview_create(
    profile_id: UUID,
    payload: wire.CreateVoicePreviewRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
        pattern=_IDEMPOTENCY_HEADER_PATTERN,
    ),
    backend: NarrationSettingsApiBackend = Depends(get_narration_settings_backend),
) -> wire.VoicePreviewResource:
    return _run(
        backend,
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.CREATE_VOICE_PREVIEW,
            profile_id=profile_id,
            payload=payload,
            idempotency_key=idempotency_key,
        ),
        wire.VoicePreviewResource,
    )


@router.get(
    "/voice-previews/{preview_id}",
    response_model=wire.VoicePreviewResource,
)
def voice_preview_get(
    preview_id: UUID,
    backend: NarrationSettingsApiBackend = Depends(get_narration_settings_backend),
) -> wire.VoicePreviewResource:
    return _run(
        backend,
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.GET_VOICE_PREVIEW,
            preview_id=preview_id,
        ),
        wire.VoicePreviewResource,
    )


@router.post(
    "/voice-profiles/{profile_id}/lock",
    response_model=wire.VoiceProfileResource,
)
def voice_profile_lock(
    profile_id: UUID,
    payload: wire.LockVoiceProfileRequest,
    backend: NarrationSettingsApiBackend = Depends(get_narration_settings_backend),
) -> wire.VoiceProfileResource:
    return _run(
        backend,
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.LOCK_VOICE_PROFILE,
            profile_id=profile_id,
            payload=payload,
        ),
        wire.VoiceProfileResource,
    )


@router.get(
    "/novels/{novel_id}/characters/{character_id}/voice-binding",
    response_model=wire.CharacterVoiceBindingResource,
)
def character_voice_binding_get(
    novel_id: UUID,
    character_id: UUID,
    backend: NarrationSettingsApiBackend = Depends(get_narration_settings_backend),
) -> wire.CharacterVoiceBindingResource:
    return _run(
        backend,
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.GET_CHARACTER_VOICE_BINDING,
            novel_id=novel_id,
            character_id=character_id,
        ),
        wire.CharacterVoiceBindingResource,
    )


@router.get(
    "/novels/{novel_id}/character-voice-bindings",
    response_model=wire.CharacterVoiceBindingListResponse,
)
def character_voice_bindings_get(
    novel_id: UUID,
    backend: NarrationSettingsApiBackend = Depends(get_narration_settings_backend),
) -> wire.CharacterVoiceBindingListResponse:
    return _run(
        backend,
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.LIST_CHARACTER_VOICE_BINDINGS,
            novel_id=novel_id,
        ),
        wire.CharacterVoiceBindingListResponse,
    )


@router.put(
    "/novels/{novel_id}/characters/{character_id}/voice-binding",
    response_model=wire.CharacterVoiceBindingResource,
)
def character_voice_binding_put(
    novel_id: UUID,
    character_id: UUID,
    payload: wire.PutCharacterVoiceBindingRequest,
    backend: NarrationSettingsApiBackend = Depends(get_narration_settings_backend),
) -> wire.CharacterVoiceBindingResource:
    return _run(
        backend,
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.PUT_CHARACTER_VOICE_BINDING,
            novel_id=novel_id,
            character_id=character_id,
            payload=payload,
        ),
        wire.CharacterVoiceBindingResource,
    )


@router.get(
    "/novels/{novel_id}/generic-voice-pools",
    response_model=wire.GenericVoicePoolResource,
)
def generic_voice_pool_get(
    novel_id: UUID,
    backend: NarrationSettingsApiBackend = Depends(get_narration_settings_backend),
) -> wire.GenericVoicePoolResource:
    return _run(
        backend,
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.GET_GENERIC_VOICE_POOL,
            novel_id=novel_id,
        ),
        wire.GenericVoicePoolResource,
    )


@router.put(
    "/novels/{novel_id}/generic-voice-pools",
    response_model=wire.GenericVoicePoolResource,
)
def generic_voice_pool_put(
    novel_id: UUID,
    payload: wire.PutGenericVoicePoolRequest,
    backend: NarrationSettingsApiBackend = Depends(get_narration_settings_backend),
) -> wire.GenericVoicePoolResource:
    return _run(
        backend,
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.PUT_GENERIC_VOICE_POOL,
            novel_id=novel_id,
            payload=payload,
        ),
        wire.GenericVoicePoolResource,
    )


@router.get(
    "/novels/{novel_id}/casting-rules",
    response_model=wire.VoiceCastingRulesResource,
)
def casting_rules_get(
    novel_id: UUID,
    backend: NarrationSettingsApiBackend = Depends(get_narration_settings_backend),
) -> wire.VoiceCastingRulesResource:
    return _run(
        backend,
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.GET_CASTING_RULES,
            novel_id=novel_id,
        ),
        wire.VoiceCastingRulesResource,
    )


@router.put(
    "/novels/{novel_id}/casting-rules",
    response_model=wire.VoiceCastingRulesResource,
)
def casting_rules_put(
    novel_id: UUID,
    payload: wire.PutVoiceCastingRulesRequest,
    backend: NarrationSettingsApiBackend = Depends(get_narration_settings_backend),
) -> wire.VoiceCastingRulesResource:
    return _run(
        backend,
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.PUT_CASTING_RULES,
            novel_id=novel_id,
            payload=payload,
        ),
        wire.VoiceCastingRulesResource,
    )


@router.get(
    "/novels/{novel_id}/pronunciation-profile",
    response_model=wire.PronunciationProfileResource,
)
def pronunciation_profile_get(
    novel_id: UUID,
    backend: NarrationSettingsApiBackend = Depends(get_narration_settings_backend),
) -> wire.PronunciationProfileResource:
    return _run(
        backend,
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.GET_PRONUNCIATION_PROFILE,
            novel_id=novel_id,
        ),
        wire.PronunciationProfileResource,
    )


@router.put(
    "/novels/{novel_id}/pronunciation-profile",
    response_model=wire.PronunciationProfileResource,
)
def pronunciation_profile_put(
    novel_id: UUID,
    payload: wire.PutPronunciationProfileRequest,
    backend: NarrationSettingsApiBackend = Depends(get_narration_settings_backend),
) -> wire.PronunciationProfileResource:
    return _run(
        backend,
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.PUT_PRONUNCIATION_PROFILE,
            novel_id=novel_id,
            payload=payload,
        ),
        wire.PronunciationProfileResource,
    )


@router.get(
    "/novels/{novel_id}/narration-cache",
    response_model=wire.NarrationCacheStatus,
)
def narration_cache_get(
    novel_id: UUID,
    backend: NarrationSettingsApiBackend = Depends(get_narration_settings_backend),
) -> wire.NarrationCacheStatus:
    return _run(
        backend,
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.GET_CACHE_STATUS,
            novel_id=novel_id,
        ),
        wire.NarrationCacheStatus,
    )


@router.post(
    "/novels/{novel_id}/narration-cache/cleanup-preview",
    response_model=wire.NarrationCacheCleanupPreview,
)
def narration_cache_cleanup_preview(
    novel_id: UUID,
    payload: wire.PreviewNarrationCacheCleanupRequest,
    backend: NarrationSettingsApiBackend = Depends(get_narration_settings_backend),
) -> wire.NarrationCacheCleanupPreview:
    return _run(
        backend,
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.PREVIEW_CACHE_CLEANUP,
            novel_id=novel_id,
            payload=payload,
        ),
        wire.NarrationCacheCleanupPreview,
    )


@router.post(
    "/novels/{novel_id}/narration-cache/cleanup",
    response_model=wire.NarrationCacheCleanupResult,
)
def narration_cache_cleanup_execute(
    novel_id: UUID,
    payload: wire.ExecuteNarrationCacheCleanupRequest,
    backend: NarrationSettingsApiBackend = Depends(get_narration_settings_backend),
) -> wire.NarrationCacheCleanupResult:
    return _run(
        backend,
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.EXECUTE_CACHE_CLEANUP,
            novel_id=novel_id,
            payload=payload,
        ),
        wire.NarrationCacheCleanupResult,
    )


__all__ = [
    "NARRATION_ERROR_HTTP_STATUS",
    "NarrationApiFault",
    "NarrationContractRoute",
    "NarrationSettingsApiBackend",
    "NarrationSettingsApiCommand",
    "NarrationSettingsBackendFactory",
    "NarrationSettingsOperation",
    "get_narration_settings_backend",
    "install_narration_settings_backend_factory",
    "narration_error_detail",
    "router",
    "uninstall_narration_settings_backend_factory",
]
