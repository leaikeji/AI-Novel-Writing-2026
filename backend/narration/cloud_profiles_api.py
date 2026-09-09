"""Fail-closed FastAPI facade for cloud TTS profile configuration."""

from __future__ import annotations

from typing import Callable, Final, TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ValidationError
from starlette.responses import JSONResponse, Response

from .cloud_profiles import (
    CloudProfileCollection,
    CloudProfileError,
    CloudProfileMutationRequest,
    CloudProfileService,
    CloudProfileTestResponse,
    CreateCloudProfileRequest,
    PatchCloudProfileRequest,
    TestCloudProfileRequest,
)


CloudProfileServiceFactory = Callable[[Request], CloudProfileService]
_ResponseModel = TypeVar("_ResponseModel", bound=BaseModel)

_ERROR_CONTRACT: Final[dict[str, tuple[int, str]]] = {
    "TTS_CLOUD_PROFILE_NOT_FOUND": (
        status.HTTP_404_NOT_FOUND,
        "找不到请求的云端语音渠道。",
    ),
    "TTS_CLOUD_PROFILE_VERSION_CONFLICT": (
        status.HTTP_409_CONFLICT,
        "配置已更新，请刷新后重试。",
    ),
    "TTS_CLOUD_PROFILE_NAME_CONFLICT": (
        status.HTTP_409_CONFLICT,
        "渠道名称已存在。",
    ),
    "TTS_CLOUD_PROFILE_ACTIVE": (
        status.HTTP_409_CONFLICT,
        "正在使用的云端语音渠道不能删除。",
    ),
    "TTS_CLOUD_PROFILE_ACTIVE_EDIT_FORBIDDEN": (
        status.HTTP_409_CONFLICT,
        "正在使用的云端语音渠道必须先停用再修改连接配置。",
    ),
    "TTS_CLOUD_PROFILE_IN_FLIGHT": (
        status.HTTP_409_CONFLICT,
        "云端语音渠道仍被在途任务引用。",
    ),
    "TTS_CLOUD_PROFILE_NOT_VERIFIED": (
        status.HTTP_409_CONFLICT,
        "云端语音渠道尚未完成验证。",
    ),
    "TTS_CLOUD_PROFILE_CREDENTIAL_REQUIRED": (
        status.HTTP_409_CONFLICT,
        "云端语音渠道尚未配置密钥。",
    ),
    "TTS_CLOUD_PROFILE_MODEL_SLOT_UNAVAILABLE": (
        status.HTTP_409_CONFLICT,
        "该渠道没有配置所选模型。",
    ),
    "TTS_CLOUD_PROFILE_IDEMPOTENCY_CONFLICT": (
        status.HTTP_409_CONFLICT,
        "幂等键已用于另一项操作。",
    ),
    "TTS_CLOUD_PROFILE_OPERATION_IN_PROGRESS": (
        status.HTTP_409_CONFLICT,
        "相同操作正在处理中。",
    ),
    "TTS_CLOUD_PROFILE_BILLING_CONFIRMATION_REQUIRED": (
        status.HTTP_412_PRECONDITION_FAILED,
        "测试可能产生费用，请先明确确认。",
    ),
    "TTS_CLOUD_PROFILE_INVARIANT_FAILED": (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "云端语音渠道状态暂不可用。",
    ),
    "TTS_CLOUD_PROFILE_IDEMPOTENCY_INVALID": (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "操作记录暂不可用。",
    ),
}


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"detail": {"code": code, "message": message}},
        headers={"Cache-Control": "no-store"},
    )


class CloudProfileContractRoute(APIRoute):
    """Remove Pydantic input echoes so URLs and write-only keys cannot leak."""

    def get_route_handler(self):  # type: ignore[no-untyped-def]
        original = super().get_route_handler()

        async def route_handler(request: Request) -> Response:
            try:
                response = await original(request)
            except RequestValidationError:
                return _error_response(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    "TTS_CLOUD_PROFILE_REQUEST_INVALID",
                    "云端语音渠道请求字段不符合契约。",
                )
            except ResponseValidationError:
                return _error_response(
                    status.HTTP_500_INTERNAL_SERVER_ERROR,
                    "TTS_CLOUD_PROFILE_RESPONSE_INVALID",
                    "云端语音渠道服务返回了不兼容的数据。",
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


def _run(call: Callable[[], object], model: type[_ResponseModel]) -> _ResponseModel:
    try:
        return model.model_validate(call())
    except CloudProfileError as error:
        public_code = error.code
        contract = _ERROR_CONTRACT.get(public_code)
        if contract is None:
            public_code = "TTS_CLOUD_PROFILE_UNAVAILABLE"
            contract = (
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "云端语音渠道服务暂不可用。",
            )
        status_code, message = contract
        raise HTTPException(
            status_code=status_code,
            detail={"code": public_code, "message": message},
        ) from error
    except ValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "TTS_CLOUD_PROFILE_RESPONSE_INVALID",
                "message": "云端语音渠道服务返回了不兼容的数据。",
            },
        ) from error


def build_tts_cloud_profiles_router(
    service_factory: CloudProfileServiceFactory,
) -> APIRouter:
    """Build an inert-until-included router around an application-owned factory."""

    if not callable(service_factory):
        raise TypeError("cloud profile service factory must be callable")
    router = APIRouter(route_class=CloudProfileContractRoute)

    def service(request: Request) -> CloudProfileService:
        try:
            return service_factory(request)
        except CloudProfileError as error:
            raise HTTPException(
                status_code=_ERROR_STATUS.get(
                    error.code,
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                ),
                detail={"code": error.code, "message": error.message},
            ) from error

    @router.get(
        "/tts-cloud-profiles",
        response_model=CloudProfileCollection,
    )
    def list_profiles(
        backend: CloudProfileService = Depends(service),
    ) -> CloudProfileCollection:
        return _run(backend.list, CloudProfileCollection)

    @router.post(
        "/tts-cloud-profiles",
        response_model=CloudProfileCollection,
        status_code=status.HTTP_201_CREATED,
    )
    def create_profile(
        payload: CreateCloudProfileRequest,
        backend: CloudProfileService = Depends(service),
    ) -> CloudProfileCollection:
        return _run(lambda: backend.create(payload), CloudProfileCollection)

    @router.patch(
        "/tts-cloud-profiles/{profile_id}",
        response_model=CloudProfileCollection,
    )
    def patch_profile(
        profile_id: UUID,
        payload: PatchCloudProfileRequest,
        backend: CloudProfileService = Depends(service),
    ) -> CloudProfileCollection:
        return _run(lambda: backend.patch(profile_id, payload), CloudProfileCollection)

    @router.post(
        "/tts-cloud-profiles/{profile_id}/test",
        response_model=CloudProfileTestResponse,
    )
    def test_profile(
        profile_id: UUID,
        payload: TestCloudProfileRequest,
        backend: CloudProfileService = Depends(service),
    ) -> CloudProfileTestResponse:
        return _run(lambda: backend.test(profile_id, payload), CloudProfileTestResponse)

    @router.post(
        "/tts-cloud-profiles/{profile_id}/activate",
        response_model=CloudProfileCollection,
    )
    def activate_profile(
        profile_id: UUID,
        payload: CloudProfileMutationRequest,
        backend: CloudProfileService = Depends(service),
    ) -> CloudProfileCollection:
        return _run(lambda: backend.activate(profile_id, payload), CloudProfileCollection)

    @router.post(
        "/tts-cloud-profiles/{profile_id}/disable",
        response_model=CloudProfileCollection,
    )
    def disable_profile(
        profile_id: UUID,
        payload: CloudProfileMutationRequest,
        backend: CloudProfileService = Depends(service),
    ) -> CloudProfileCollection:
        return _run(lambda: backend.disable(profile_id, payload), CloudProfileCollection)

    @router.delete(
        "/tts-cloud-profiles/{profile_id}",
        response_model=CloudProfileCollection,
    )
    def delete_profile(
        profile_id: UUID,
        payload: CloudProfileMutationRequest,
        backend: CloudProfileService = Depends(service),
    ) -> CloudProfileCollection:
        return _run(lambda: backend.delete(profile_id, payload), CloudProfileCollection)

    return router


__all__ = [
    "CloudProfileContractRoute",
    "CloudProfileServiceFactory",
    "build_tts_cloud_profiles_router",
]
