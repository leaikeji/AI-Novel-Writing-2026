from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.narration.cloud_profiles import (
    CloudProfileCollection,
    CloudProfileError,
    CloudProfileLifecycle,
    CloudProfileModelSlot,
    CloudProfileMutationRequest,
    CloudProfileResource,
    CloudProfileTestResponse,
    CloudProfileTestState,
    CreateCloudProfileRequest,
    PatchCloudProfileRequest,
    TestCloudProfileRequest as _TestCloudProfileRequest,
)
from backend.narration.cloud_profiles_api import build_tts_cloud_profiles_router


PROFILE_ID = UUID("61000000-0000-4000-8000-000000000010")
PREFIX = "/api/ai-novel-world-2026"


def resource() -> CloudProfileResource:
    now = datetime.now(UTC)
    return CloudProfileResource(
        id=PROFILE_ID,
        name="会员渠道 A",
        protocol="qwen_audio_native_http/1",
        base_url="https://tts.partner.example/v1",
        credential_configured=True,
        api_key_masked="••••5678",
        api_key_updated_at=now,
        quality_model_id="partner-plus",
        speed_model_id="partner-flash",
        quality_test_state=CloudProfileTestState.PASSED,
        speed_test_state=CloudProfileTestState.UNTESTED,
        lifecycle_state=CloudProfileLifecycle.VERIFIED,
        version=3,
        last_tested_at=now,
        failure_code=None,
        created_at=now,
        updated_at=now,
    )


class ApiService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.failure: CloudProfileError | None = None

    def _collection(self) -> CloudProfileCollection:
        if self.failure:
            raise self.failure
        return CloudProfileCollection(items=[resource()], active_profile_id=None)

    def list(self) -> CloudProfileCollection:
        self.calls.append(("list", None))
        return self._collection()

    def create(self, payload: CreateCloudProfileRequest) -> CloudProfileCollection:
        self.calls.append(("create", payload))
        return self._collection()

    def patch(
        self, profile_id: UUID, payload: PatchCloudProfileRequest
    ) -> CloudProfileCollection:
        self.calls.append(("patch", (profile_id, payload)))
        return self._collection()

    def test(
        self, profile_id: UUID, payload: _TestCloudProfileRequest
    ) -> CloudProfileTestResponse:
        self.calls.append(("test", (profile_id, payload)))
        if self.failure:
            raise self.failure
        return CloudProfileTestResponse(
            profile=resource(),
            slot=payload.slot,
            status="passed",
            actual_model_id="partner-plus",
            audio_base64="UklGRg==",
            content_type="audio/wav",
            sample_rate_hz=24000,
            failure_code=None,
        )

    def activate(
        self, profile_id: UUID, payload: CloudProfileMutationRequest
    ) -> CloudProfileCollection:
        self.calls.append(("activate", (profile_id, payload)))
        return self._collection()

    def disable(
        self, profile_id: UUID, payload: CloudProfileMutationRequest
    ) -> CloudProfileCollection:
        self.calls.append(("disable", (profile_id, payload)))
        return self._collection()

    def delete(
        self, profile_id: UUID, payload: CloudProfileMutationRequest
    ) -> CloudProfileCollection:
        self.calls.append(("delete", (profile_id, payload)))
        return self._collection()


@pytest.fixture
def api() -> tuple[ApiService, TestClient]:
    service = ApiService()
    app = FastAPI()

    def factory(request: Request) -> ApiService:
        assert request.url.path.startswith(PREFIX)
        return service

    app.include_router(build_tts_cloud_profiles_router(factory), prefix=PREFIX)
    return service, TestClient(app)


def mutation() -> dict[str, object]:
    return {"expected_version": 3, "idempotency_key": "profile-action-0001"}


@pytest.mark.parametrize(
    ("method", "path", "json_body", "operation", "status_code"),
    [
        ("get", "/tts-cloud-profiles", None, "list", 200),
        (
            "post",
            "/tts-cloud-profiles",
            {
                "expected_version": 0,
                "idempotency_key": "profile-create-0001",
                "name": "会员渠道 A",
                "protocol": "qwen_audio_native_http/1",
                "base_url": "https://tts.partner.example/v1",
                "quality_model_id": "partner-plus",
                "speed_model_id": None,
                "api_key": "secret-key-12345678",
            },
            "create",
            201,
        ),
        (
            "patch",
            f"/tts-cloud-profiles/{PROFILE_ID}",
            {
                "expected_version": 3,
                "idempotency_key": "profile-patch-0001",
                "name": "渠道新名称",
            },
            "patch",
            200,
        ),
        (
            "post",
            f"/tts-cloud-profiles/{PROFILE_ID}/test",
            {
                **mutation(),
                "idempotency_key": "profile-test-0001",
                "slot": "quality",
                "billing_confirmed": True,
            },
            "test",
            200,
        ),
        (
            "post",
            f"/tts-cloud-profiles/{PROFILE_ID}/activate",
            mutation(),
            "activate",
            200,
        ),
        (
            "post",
            f"/tts-cloud-profiles/{PROFILE_ID}/disable",
            mutation(),
            "disable",
            200,
        ),
        (
            "delete",
            f"/tts-cloud-profiles/{PROFILE_ID}",
            mutation(),
            "delete",
            200,
        ),
    ],
)
def test_router_exposes_frozen_paths_and_no_store(
    api: tuple[ApiService, TestClient],
    method: str,
    path: str,
    json_body: dict[str, object] | None,
    operation: str,
    status_code: int,
) -> None:
    service, client = api
    kwargs = {"json": json_body} if json_body is not None else {}
    response = client.request(method.upper(), f"{PREFIX}{path}", **kwargs)

    assert response.status_code == status_code, response.text
    assert response.headers["cache-control"] == "no-store"
    assert service.calls[-1][0] == operation
    payload = response.json()
    assert payload["schema_version"] == "tts-cloud-profiles/1"
    serialized = response.text
    assert "secret-key-12345678" not in serialized
    assert "credential_ref" not in serialized


def test_request_validation_never_echoes_key_or_url(
    api: tuple[ApiService, TestClient],
) -> None:
    service, client = api
    secret = "plain-secret-that-must-not-leak"
    unsafe_url = "http://localhost:9000/private?key=also-secret"
    response = client.post(
        f"{PREFIX}/tts-cloud-profiles",
        json={
            "expected_version": 0,
            "idempotency_key": "bad",
            "name": "渠道 A",
            "base_url": unsafe_url,
            "quality_model_id": "plus",
            "api_key": secret,
        },
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": {
            "code": "TTS_CLOUD_PROFILE_REQUEST_INVALID",
            "message": "云端语音渠道请求字段不符合契约。",
        }
    }
    assert secret not in response.text
    assert unsafe_url not in response.text
    assert service.calls == []


def test_domain_fault_maps_to_stable_redacted_detail(
    api: tuple[ApiService, TestClient],
) -> None:
    service, client = api
    service.failure = CloudProfileError(
        "TTS_CLOUD_PROFILE_ACTIVE_EDIT_FORBIDDEN",
        "https://secret-member-host.example/plain-secret-key",
    )
    response = client.patch(
        f"{PREFIX}/tts-cloud-profiles/{PROFILE_ID}",
        json={
            "expected_version": 3,
            "idempotency_key": "profile-patch-0002",
            "base_url": "https://secret-member-host.example/account/path",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "TTS_CLOUD_PROFILE_ACTIVE_EDIT_FORBIDDEN",
        "message": "正在使用的云端语音渠道必须先停用再修改连接配置。",
    }
    assert "secret-member-host" not in response.text


def test_test_endpoint_requires_explicit_boolean_confirmation(
    api: tuple[ApiService, TestClient],
) -> None:
    service, client = api
    response = client.post(
        f"{PREFIX}/tts-cloud-profiles/{PROFILE_ID}/test",
        json={
            **mutation(),
            "slot": CloudProfileModelSlot.QUALITY.value,
            "billing_confirmed": "true",
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "TTS_CLOUD_PROFILE_REQUEST_INVALID"
    assert service.calls == []
