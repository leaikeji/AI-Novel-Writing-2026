"""Domain contract for workspace-scoped Qwen cloud TTS profiles.

This module deliberately contains no ORM, HTTP client, encryption, or real provider
implementation.  The application integration owns those adapters and their transaction
boundaries; tests can use in-memory ports without touching credentials or the network.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import Enum
from typing import Final, Literal, Mapping, Protocol
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from .contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID
from .providers.aliyun import normalize_qwen_audio_base_url


TTS_CLOUD_PROFILES_SCHEMA_VERSION: Final = "tts-cloud-profiles/1"
QWEN_AUDIO_NATIVE_HTTP_PROTOCOL: Final = "qwen_audio_native_http/1"
TTS_CLOUD_TEST_SAMPLE_TEXT: Final = "你好，这是一段语音模型连接测试。"
NARRATION_CLOUD_TTS_CONSENT_PURPOSE: Final = "narration_tts_synthesis"

_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
_FAILURE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,95}$")
_CONTROL_CHARACTER = re.compile(r"[\x00-\x1f\x7f]")


class CloudProfileLifecycle(str, Enum):
    DRAFT = "draft"
    VERIFIED = "verified"
    ACTIVE = "active"
    DISABLED = "disabled"


class CloudProfileTestState(str, Enum):
    UNTESTED = "untested"
    TESTING = "testing"
    PASSED = "passed"
    FAILED = "failed"


class CloudProfileModelSlot(str, Enum):
    QUALITY = "quality"
    SPEED = "speed"


class _StrictWireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _require_text(value: str, *, field_name: str, maximum: int) -> str:
    if not value or len(value) > maximum or _CONTROL_CHARACTER.search(value):
        raise ValueError(f"{field_name} is invalid")
    return value


def normalize_cloud_base_url(value: str) -> str:
    """Apply non-network URL checks; the provider adapter must also resolve DNS safely."""

    value = _require_text(value, field_name="base_url", maximum=2048)
    try:
        return normalize_qwen_audio_base_url(value)
    except (TypeError, ValueError) as error:
        raise ValueError("base_url must be a safe HTTPS URL") from error


def _validate_model_id(value: str) -> str:
    return _require_text(value, field_name="model_id", maximum=240)


def _validate_optional_model_id(value: str | None) -> str | None:
    return None if value is None else _validate_model_id(value)


class CreateCloudProfileRequest(_StrictWireModel):
    expected_version: Literal[0]
    idempotency_key: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=80)
    protocol: Literal["qwen_audio_native_http/1"] = QWEN_AUDIO_NATIVE_HTTP_PROTOCOL
    base_url: str = Field(min_length=1, max_length=2048)
    quality_model_id: str = Field(min_length=1, max_length=240)
    speed_model_id: str | None = Field(default=None, min_length=1, max_length=240)
    api_key: SecretStr | None = Field(default=None, min_length=16, max_length=4096)

    @field_validator("idempotency_key")
    @classmethod
    def validate_idempotency_key(cls, value: str) -> str:
        if not _IDEMPOTENCY_KEY.fullmatch(value):
            raise ValueError("idempotency_key is invalid")
        return value

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _require_text(value, field_name="name", maximum=80)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        return normalize_cloud_base_url(value)

    @field_validator("quality_model_id")
    @classmethod
    def validate_quality_model_id(cls, value: str) -> str:
        return _validate_model_id(value)

    @field_validator("speed_model_id")
    @classmethod
    def validate_speed_model_id(cls, value: str | None) -> str | None:
        return _validate_optional_model_id(value)


class PatchCloudProfileRequest(_StrictWireModel):
    expected_version: int = Field(ge=1, strict=True)
    idempotency_key: str = Field(min_length=8, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=80)
    protocol: Literal["qwen_audio_native_http/1"] | None = None
    base_url: str | None = Field(default=None, min_length=1, max_length=2048)
    quality_model_id: str | None = Field(default=None, min_length=1, max_length=240)
    speed_model_id: str | None = Field(default=None, min_length=1, max_length=240)
    api_key: SecretStr | None = Field(default=None, min_length=16, max_length=4096)
    clear_api_key: bool = Field(default=False, strict=True)

    @field_validator("idempotency_key")
    @classmethod
    def validate_idempotency_key(cls, value: str) -> str:
        if not _IDEMPOTENCY_KEY.fullmatch(value):
            raise ValueError("idempotency_key is invalid")
        return value

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        return None if value is None else _require_text(value, field_name="name", maximum=80)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        return None if value is None else normalize_cloud_base_url(value)

    @field_validator("quality_model_id", "speed_model_id")
    @classmethod
    def validate_model_id(cls, value: str | None) -> str | None:
        return _validate_optional_model_id(value)

    @model_validator(mode="after")
    def validate_patch(self) -> "PatchCloudProfileRequest":
        changed = self.model_fields_set - {"expected_version", "idempotency_key"}
        if not changed:
            raise ValueError("patch must include a change")
        if self.api_key is not None and self.clear_api_key:
            raise ValueError("api_key and clear_api_key cannot be used together")
        return self


class CloudProfileMutationRequest(_StrictWireModel):
    expected_version: int = Field(ge=1, strict=True)
    idempotency_key: str = Field(min_length=8, max_length=128)

    @field_validator("idempotency_key")
    @classmethod
    def validate_idempotency_key(cls, value: str) -> str:
        if not _IDEMPOTENCY_KEY.fullmatch(value):
            raise ValueError("idempotency_key is invalid")
        return value


class TestCloudProfileRequest(CloudProfileMutationRequest):
    slot: CloudProfileModelSlot
    billing_confirmed: bool = Field(strict=True)


class CloudProfileResource(_StrictWireModel):
    id: UUID
    name: str
    protocol: Literal["qwen_audio_native_http/1"]
    base_url: str
    credential_configured: bool
    api_key_masked: str | None
    api_key_updated_at: datetime | None
    quality_model_id: str
    speed_model_id: str | None
    quality_test_state: CloudProfileTestState
    speed_test_state: CloudProfileTestState
    lifecycle_state: CloudProfileLifecycle
    version: int = Field(ge=1, strict=True)
    last_tested_at: datetime | None
    failure_code: str | None
    created_at: datetime
    updated_at: datetime

    @field_validator("failure_code")
    @classmethod
    def validate_failure_code(cls, value: str | None) -> str | None:
        if value is not None and not _FAILURE_CODE.fullmatch(value):
            raise ValueError("failure_code is invalid")
        return value


class CloudProfileCollection(_StrictWireModel):
    schema_version: Literal["tts-cloud-profiles/1"] = TTS_CLOUD_PROFILES_SCHEMA_VERSION
    items: list[CloudProfileResource]
    active_profile_id: UUID | None


class CloudProfileTestResponse(_StrictWireModel):
    schema_version: Literal["tts-cloud-profiles/1"] = TTS_CLOUD_PROFILES_SCHEMA_VERSION
    profile: CloudProfileResource
    slot: CloudProfileModelSlot
    status: Literal["passed", "failed"]
    actual_model_id: str | None
    audio_base64: str | None
    content_type: str | None
    sample_rate_hz: int | None = Field(default=None, ge=1, le=384000)
    failure_code: str | None

    @field_validator("failure_code")
    @classmethod
    def validate_failure_code(cls, value: str | None) -> str | None:
        if value is not None and not _FAILURE_CODE.fullmatch(value):
            raise ValueError("failure_code is invalid")
        return value


@dataclass(frozen=True, slots=True)
class CloudProfileScope:
    owner_id: UUID
    workspace_id: UUID

    @classmethod
    def fixed_local(cls) -> "CloudProfileScope":
        return cls(owner_id=LOCAL_OWNER_ID, workspace_id=LOCAL_WORKSPACE_ID)


@dataclass(frozen=True, slots=True)
class CloudProfileRecord:
    id: UUID
    owner_id: UUID
    workspace_id: UUID
    name: str
    protocol: str
    base_url: str
    credential_ref: str | None
    api_key_last4: str | None
    api_key_updated_at: datetime | None
    quality_model_id: str
    speed_model_id: str | None
    quality_test_state: CloudProfileTestState
    speed_test_state: CloudProfileTestState
    lifecycle_state: CloudProfileLifecycle
    verification_fingerprint: str | None
    version: int
    last_tested_at: datetime | None
    failure_code: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class StoredCloudCredential:
    credential_ref: str
    last4: str
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class CloudProfileProviderTestCommand:
    profile_id: UUID
    profile_version: int
    protocol: str
    base_url: str
    model_id: str
    slot: CloudProfileModelSlot
    api_key: SecretStr
    sample_text: str = TTS_CLOUD_TEST_SAMPLE_TEXT


@dataclass(frozen=True, slots=True)
class CloudProfileProviderTestResult:
    passed: bool
    actual_model_id: str | None = None
    audio: bytes | None = None
    content_type: str | None = None
    sample_rate_hz: int | None = None
    failure_code: str | None = None


class IdempotencyClaimState(str, Enum):
    ACQUIRED = "acquired"
    REPLAY = "replay"
    IN_PROGRESS = "in_progress"


@dataclass(frozen=True, slots=True)
class IdempotencyClaim:
    state: IdempotencyClaimState
    response: Mapping[str, object] | None = None


class CloudProfileRepository(Protocol):
    """Atomic persistence port; production methods must enforce scope and CAS."""

    def list_profiles(self, scope: CloudProfileScope) -> list[CloudProfileRecord]: ...

    def get_profile(
        self, scope: CloudProfileScope, profile_id: UUID
    ) -> CloudProfileRecord | None: ...

    def create_profile(
        self, scope: CloudProfileScope, record: CloudProfileRecord
    ) -> CloudProfileRecord: ...

    def replace_profile(
        self,
        scope: CloudProfileScope,
        record: CloudProfileRecord,
        *,
        expected_version: int,
    ) -> CloudProfileRecord: ...

    def activate_profile(
        self,
        scope: CloudProfileScope,
        profile_id: UUID,
        *,
        expected_version: int,
        updated_at: datetime,
        revoke_consent_purpose: Literal["narration_tts_synthesis"],
    ) -> list[CloudProfileRecord]: ...

    def delete_profile(
        self,
        scope: CloudProfileScope,
        profile_id: UUID,
        *,
        expected_version: int,
    ) -> None: ...

    def has_in_flight_references(
        self, scope: CloudProfileScope, profile_id: UUID
    ) -> bool: ...

    def begin_idempotent_operation(
        self,
        scope: CloudProfileScope,
        *,
        operation: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> IdempotencyClaim: ...

    def complete_idempotent_operation(
        self,
        scope: CloudProfileScope,
        *,
        operation: str,
        idempotency_key: str,
        request_fingerprint: str,
        response: Mapping[str, object],
    ) -> None: ...

    def abort_idempotent_operation(
        self,
        scope: CloudProfileScope,
        *,
        operation: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> None: ...


class CloudProfileSecretPort(Protocol):
    """Credential vault boundary.

    Production deletion must be recoverable or commit-aware because profile persistence
    and the filesystem vault cannot share a database transaction.
    """

    def put(self, api_key: SecretStr) -> StoredCloudCredential: ...

    def get(self, credential_ref: str) -> SecretStr: ...

    def delete(self, credential_ref: str) -> None: ...


class CloudProfileProviderTestPort(Protocol):
    def test(
        self, command: CloudProfileProviderTestCommand
    ) -> CloudProfileProviderTestResult: ...


class CloudProfileError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _fault(code: str, message: str) -> CloudProfileError:
    return CloudProfileError(code, message)


def _configuration_fingerprint(record: CloudProfileRecord) -> str:
    payload = {
        "schema": TTS_CLOUD_PROFILES_SCHEMA_VERSION,
        "protocol": record.protocol,
        "base_url": record.base_url,
        "credential_ref": record.credential_ref,
        "quality_model_id": record.quality_model_id,
        "speed_model_id": record.speed_model_id,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _request_fingerprint(operation: str, payload: BaseModel) -> str:
    body = payload.model_dump(mode="json", exclude={"idempotency_key", "api_key"})
    if "api_key" in payload.model_fields_set:
        secret = getattr(payload, "api_key", None)
        body["api_key_sha256"] = (
            hashlib.sha256(secret.get_secret_value().encode()).hexdigest()
            if secret is not None
            else None
        )
    canonical = {"operation": operation, "payload": body}
    return hashlib.sha256(
        json.dumps(canonical, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _resource(record: CloudProfileRecord) -> CloudProfileResource:
    configured = record.credential_ref is not None
    return CloudProfileResource(
        id=record.id,
        name=record.name,
        protocol=record.protocol,
        base_url=record.base_url,
        credential_configured=configured,
        api_key_masked=(
            f"••••{record.api_key_last4}"
            if configured and record.api_key_last4
            else None
        ),
        api_key_updated_at=record.api_key_updated_at if configured else None,
        quality_model_id=record.quality_model_id,
        speed_model_id=record.speed_model_id,
        quality_test_state=record.quality_test_state,
        speed_test_state=record.speed_test_state,
        lifecycle_state=record.lifecycle_state,
        version=record.version,
        last_tested_at=record.last_tested_at,
        failure_code=record.failure_code,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _collection(records: list[CloudProfileRecord]) -> CloudProfileCollection:
    ordered = sorted(records, key=lambda item: (item.created_at, str(item.id)))
    active = [item.id for item in ordered if item.lifecycle_state is CloudProfileLifecycle.ACTIVE]
    if len(active) > 1:
        raise _fault("TTS_CLOUD_PROFILE_INVARIANT_FAILED", "云端语音渠道状态暂不可用。")
    return CloudProfileCollection(
        items=[_resource(item) for item in ordered],
        active_profile_id=active[0] if active else None,
    )


def _completed_response(claim: IdempotencyClaim, model: type[BaseModel]) -> BaseModel | None:
    if claim.state is IdempotencyClaimState.REPLAY:
        if claim.response is None:
            raise _fault("TTS_CLOUD_PROFILE_IDEMPOTENCY_INVALID", "操作记录暂不可用。")
        return model.model_validate(claim.response)
    if claim.state is IdempotencyClaimState.IN_PROGRESS:
        raise _fault("TTS_CLOUD_PROFILE_OPERATION_IN_PROGRESS", "相同操作正在处理中。")
    return None


class CloudProfileService:
    """Small application service coordinating injected persistence and I/O ports."""

    def __init__(
        self,
        repository: CloudProfileRepository,
        secrets: CloudProfileSecretPort,
        provider_tests: CloudProfileProviderTestPort,
        *,
        scope: CloudProfileScope | None = None,
    ) -> None:
        self.repository = repository
        self.secrets = secrets
        self.provider_tests = provider_tests
        self.scope = scope or CloudProfileScope.fixed_local()

    def list(self) -> CloudProfileCollection:
        return _collection(self.repository.list_profiles(self.scope))

    def _begin(self, operation: str, payload: BaseModel) -> tuple[str, IdempotencyClaim]:
        fingerprint = _request_fingerprint(operation, payload)
        claim = self.repository.begin_idempotent_operation(
            self.scope,
            operation=operation,
            idempotency_key=payload.idempotency_key,  # type: ignore[attr-defined]
            request_fingerprint=fingerprint,
        )
        return fingerprint, claim

    def _complete(
        self,
        operation: str,
        payload: BaseModel,
        fingerprint: str,
        response: BaseModel,
    ) -> None:
        self.repository.complete_idempotent_operation(
            self.scope,
            operation=operation,
            idempotency_key=payload.idempotency_key,  # type: ignore[attr-defined]
            request_fingerprint=fingerprint,
            response=response.model_dump(mode="json"),
        )

    def _abort(self, operation: str, payload: BaseModel, fingerprint: str) -> None:
        self.repository.abort_idempotent_operation(
            self.scope,
            operation=operation,
            idempotency_key=payload.idempotency_key,  # type: ignore[attr-defined]
            request_fingerprint=fingerprint,
        )

    def create(self, payload: CreateCloudProfileRequest) -> CloudProfileCollection:
        operation = "create"
        fingerprint, claim = self._begin(operation, payload)
        replay = _completed_response(claim, CloudProfileCollection)
        if replay is not None:
            return CloudProfileCollection.model_validate(replay)
        stored: StoredCloudCredential | None = None
        try:
            if payload.api_key is not None:
                stored = self.secrets.put(payload.api_key)
            now = datetime.now(UTC)
            record = CloudProfileRecord(
                id=uuid4(),
                owner_id=self.scope.owner_id,
                workspace_id=self.scope.workspace_id,
                name=payload.name,
                protocol=payload.protocol,
                base_url=payload.base_url,
                credential_ref=stored.credential_ref if stored else None,
                api_key_last4=stored.last4 if stored else None,
                api_key_updated_at=stored.updated_at if stored else None,
                quality_model_id=payload.quality_model_id,
                speed_model_id=payload.speed_model_id,
                quality_test_state=CloudProfileTestState.UNTESTED,
                speed_test_state=CloudProfileTestState.UNTESTED,
                lifecycle_state=CloudProfileLifecycle.DRAFT,
                verification_fingerprint=None,
                version=1,
                last_tested_at=None,
                failure_code=None,
                created_at=now,
                updated_at=now,
            )
            self.repository.create_profile(self.scope, record)
            response = self.list()
            self._complete(operation, payload, fingerprint, response)
            return response
        except Exception:
            if stored is not None:
                try:
                    self.secrets.delete(stored.credential_ref)
                except Exception:
                    pass
            self._abort(operation, payload, fingerprint)
            raise

    def patch(
        self, profile_id: UUID, payload: PatchCloudProfileRequest
    ) -> CloudProfileCollection:
        operation = f"patch:{profile_id}"
        fingerprint, claim = self._begin(operation, payload)
        replay = _completed_response(claim, CloudProfileCollection)
        if replay is not None:
            return CloudProfileCollection.model_validate(replay)
        new_secret: StoredCloudCredential | None = None
        old_secret_ref: str | None = None
        try:
            current = self._get(profile_id)
            self._require_version(current, payload.expected_version)
            active_configuration_change = (
                payload.base_url is not None and payload.base_url != current.base_url
            ) or (
                payload.protocol is not None and payload.protocol != current.protocol
            ) or payload.api_key is not None or payload.clear_api_key or (
                payload.quality_model_id is not None
                and payload.quality_model_id != current.quality_model_id
            ) or (
                "speed_model_id" in payload.model_fields_set
                and payload.speed_model_id != current.speed_model_id
            )
            if (
                current.lifecycle_state is CloudProfileLifecycle.ACTIVE
                and active_configuration_change
            ):
                raise _fault(
                    "TTS_CLOUD_PROFILE_ACTIVE_EDIT_FORBIDDEN",
                    "正在使用的云端语音渠道必须先停用再修改连接配置。",
                )
            if payload.api_key is not None:
                new_secret = self.secrets.put(payload.api_key)
                old_secret_ref = current.credential_ref
            elif payload.clear_api_key:
                old_secret_ref = current.credential_ref
            credential_ref = (
                new_secret.credential_ref
                if new_secret
                else None if payload.clear_api_key else current.credential_ref
            )
            last4 = (
                new_secret.last4
                if new_secret
                else None if payload.clear_api_key else current.api_key_last4
            )
            key_updated_at = (
                new_secret.updated_at
                if new_secret
                else None if payload.clear_api_key else current.api_key_updated_at
            )
            base_url = payload.base_url if payload.base_url is not None else current.base_url
            protocol = payload.protocol if payload.protocol is not None else current.protocol
            quality_model_id = (
                payload.quality_model_id
                if payload.quality_model_id is not None
                else current.quality_model_id
            )
            speed_model_id = (
                payload.speed_model_id
                if "speed_model_id" in payload.model_fields_set
                else current.speed_model_id
            )
            invalidate_all = (
                base_url != current.base_url
                or protocol != current.protocol
                or credential_ref != current.credential_ref
            )
            quality_changed = quality_model_id != current.quality_model_id
            speed_changed = speed_model_id != current.speed_model_id
            quality_state = (
                CloudProfileTestState.UNTESTED
                if invalidate_all or quality_changed
                else current.quality_test_state
            )
            speed_state = (
                CloudProfileTestState.UNTESTED
                if invalidate_all or speed_changed
                else current.speed_test_state
            )
            verification_invalidated = invalidate_all or quality_changed or speed_changed
            lifecycle = (
                CloudProfileLifecycle.DRAFT
                if verification_invalidated
                else current.lifecycle_state
            )
            updated = replace(
                current,
                name=payload.name if payload.name is not None else current.name,
                protocol=protocol,
                base_url=base_url,
                credential_ref=credential_ref,
                api_key_last4=last4,
                api_key_updated_at=key_updated_at,
                quality_model_id=quality_model_id,
                speed_model_id=speed_model_id,
                quality_test_state=quality_state,
                speed_test_state=speed_state,
                lifecycle_state=lifecycle,
                verification_fingerprint=(
                    None if verification_invalidated else current.verification_fingerprint
                ),
                failure_code=None if verification_invalidated else current.failure_code,
                version=current.version + 1,
                updated_at=datetime.now(UTC),
            )
            self.repository.replace_profile(
                self.scope, updated, expected_version=payload.expected_version
            )
            if old_secret_ref is not None and old_secret_ref != credential_ref:
                self.secrets.delete(old_secret_ref)
            response = self.list()
            self._complete(operation, payload, fingerprint, response)
            return response
        except Exception:
            if new_secret is not None:
                try:
                    self.secrets.delete(new_secret.credential_ref)
                except Exception:
                    pass
            self._abort(operation, payload, fingerprint)
            raise

    def activate(
        self, profile_id: UUID, payload: CloudProfileMutationRequest
    ) -> CloudProfileCollection:
        operation = f"activate:{profile_id}"
        fingerprint, claim = self._begin(operation, payload)
        replay = _completed_response(claim, CloudProfileCollection)
        if replay is not None:
            return CloudProfileCollection.model_validate(replay)
        try:
            current = self._get(profile_id)
            self._require_version(current, payload.expected_version)
            if current.credential_ref is None or not self._all_configured_slots_passed(
                current
            ):
                raise _fault("TTS_CLOUD_PROFILE_NOT_VERIFIED", "云端语音渠道尚未完成验证。")
            records = self.repository.activate_profile(
                self.scope,
                profile_id,
                expected_version=payload.expected_version,
                updated_at=datetime.now(UTC),
                revoke_consent_purpose=NARRATION_CLOUD_TTS_CONSENT_PURPOSE,
            )
            response = _collection(records)
            self._complete(operation, payload, fingerprint, response)
            return response
        except Exception:
            self._abort(operation, payload, fingerprint)
            raise

    def disable(
        self, profile_id: UUID, payload: CloudProfileMutationRequest
    ) -> CloudProfileCollection:
        operation = f"disable:{profile_id}"
        fingerprint, claim = self._begin(operation, payload)
        replay = _completed_response(claim, CloudProfileCollection)
        if replay is not None:
            return CloudProfileCollection.model_validate(replay)
        try:
            current = self._get(profile_id)
            self._require_version(current, payload.expected_version)
            disabled = replace(
                current,
                lifecycle_state=CloudProfileLifecycle.DISABLED,
                version=current.version + 1,
                updated_at=datetime.now(UTC),
            )
            self.repository.replace_profile(
                self.scope, disabled, expected_version=payload.expected_version
            )
            response = self.list()
            self._complete(operation, payload, fingerprint, response)
            return response
        except Exception:
            self._abort(operation, payload, fingerprint)
            raise

    def delete(
        self, profile_id: UUID, payload: CloudProfileMutationRequest
    ) -> CloudProfileCollection:
        operation = f"delete:{profile_id}"
        fingerprint, claim = self._begin(operation, payload)
        replay = _completed_response(claim, CloudProfileCollection)
        if replay is not None:
            return CloudProfileCollection.model_validate(replay)
        try:
            current = self._get(profile_id)
            self._require_version(current, payload.expected_version)
            if current.lifecycle_state is CloudProfileLifecycle.ACTIVE:
                raise _fault("TTS_CLOUD_PROFILE_ACTIVE", "正在使用的云端语音渠道不能删除。")
            if self.repository.has_in_flight_references(self.scope, profile_id):
                raise _fault("TTS_CLOUD_PROFILE_IN_FLIGHT", "云端语音渠道仍被在途任务引用。")
            self.repository.delete_profile(
                self.scope, profile_id, expected_version=payload.expected_version
            )
            if current.credential_ref is not None:
                try:
                    self.secrets.delete(current.credential_ref)
                except Exception:
                    # The authoritative profile is already gone. A failed
                    # encrypted-record cleanup must not resurrect or expose it;
                    # a later maintenance sweep may remove the orphan.
                    pass
            response = self.list()
            self._complete(operation, payload, fingerprint, response)
            return response
        except Exception:
            self._abort(operation, payload, fingerprint)
            raise

    def test(
        self, profile_id: UUID, payload: TestCloudProfileRequest
    ) -> CloudProfileTestResponse:
        operation = f"test:{profile_id}"
        fingerprint, claim = self._begin(operation, payload)
        replay = _completed_response(claim, CloudProfileTestResponse)
        if replay is not None:
            return CloudProfileTestResponse.model_validate(replay)
        try:
            if payload.billing_confirmed is not True:
                raise _fault(
                    "TTS_CLOUD_PROFILE_BILLING_CONFIRMATION_REQUIRED",
                    "测试可能产生费用，请先明确确认。",
                )
            current = self._get(profile_id)
            self._require_version(current, payload.expected_version)
            model_id = self._model_for_slot(current, payload.slot)
            if current.credential_ref is None:
                raise _fault("TTS_CLOUD_PROFILE_CREDENTIAL_REQUIRED", "云端语音渠道尚未配置密钥。")
            api_key = self.secrets.get(current.credential_ref)
            testing = self._with_test_state(
                current,
                payload.slot,
                CloudProfileTestState.TESTING,
                lifecycle=current.lifecycle_state,
                failure_code=None,
            )
            testing = replace(
                testing,
                version=current.version + 1,
                updated_at=datetime.now(UTC),
            )
            self.repository.replace_profile(
                self.scope, testing, expected_version=payload.expected_version
            )
            try:
                result = self.provider_tests.test(
                    CloudProfileProviderTestCommand(
                        profile_id=testing.id,
                        profile_version=testing.version,
                        protocol=testing.protocol,
                        base_url=testing.base_url,
                        model_id=model_id,
                        slot=payload.slot,
                        api_key=api_key,
                    )
                )
            except Exception:
                result = CloudProfileProviderTestResult(
                    passed=False,
                    failure_code="TTS_CLOUD_PROVIDER_UNAVAILABLE",
                )
            result = self._normalized_test_result(result, expected_model_id=model_id)
            completed = self._complete_test(testing, payload.slot, result)
            saved = self.repository.replace_profile(
                self.scope, completed, expected_version=testing.version
            )
            response = self._test_response(saved, payload.slot, result)
            self._complete(operation, payload, fingerprint, response)
            return response
        except Exception:
            self._abort(operation, payload, fingerprint)
            raise

    def _get(self, profile_id: UUID) -> CloudProfileRecord:
        record = self.repository.get_profile(self.scope, profile_id)
        if record is None:
            raise _fault("TTS_CLOUD_PROFILE_NOT_FOUND", "找不到请求的云端语音渠道。")
        if (
            record.owner_id != self.scope.owner_id
            or record.workspace_id != self.scope.workspace_id
        ):
            raise _fault("TTS_CLOUD_PROFILE_NOT_FOUND", "找不到请求的云端语音渠道。")
        return record

    @staticmethod
    def _require_version(record: CloudProfileRecord, expected_version: int) -> None:
        if record.version != expected_version:
            raise _fault("TTS_CLOUD_PROFILE_VERSION_CONFLICT", "配置已更新，请刷新后重试。")

    @staticmethod
    def _all_configured_slots_passed(record: CloudProfileRecord) -> bool:
        return record.quality_test_state is CloudProfileTestState.PASSED and (
            record.speed_model_id is None
            or record.speed_test_state is CloudProfileTestState.PASSED
        )

    @staticmethod
    def _model_for_slot(record: CloudProfileRecord, slot: CloudProfileModelSlot) -> str:
        if slot is CloudProfileModelSlot.QUALITY:
            return record.quality_model_id
        if record.speed_model_id is None:
            raise _fault("TTS_CLOUD_PROFILE_MODEL_SLOT_UNAVAILABLE", "该渠道没有配置速度模型。")
        return record.speed_model_id

    @staticmethod
    def _with_test_state(
        record: CloudProfileRecord,
        slot: CloudProfileModelSlot,
        state: CloudProfileTestState,
        *,
        lifecycle: CloudProfileLifecycle,
        failure_code: str | None,
    ) -> CloudProfileRecord:
        return replace(
            record,
            quality_test_state=(
                state
                if slot is CloudProfileModelSlot.QUALITY
                else record.quality_test_state
            ),
            speed_test_state=(
                state if slot is CloudProfileModelSlot.SPEED else record.speed_test_state
            ),
            lifecycle_state=lifecycle,
            failure_code=failure_code,
        )

    def _complete_test(
        self,
        testing: CloudProfileRecord,
        slot: CloudProfileModelSlot,
        result: CloudProfileProviderTestResult,
    ) -> CloudProfileRecord:
        now = datetime.now(UTC)
        passed = result.passed is True
        state = CloudProfileTestState.PASSED if passed else CloudProfileTestState.FAILED
        failure_code = None if passed else self._safe_failure_code(result.failure_code)
        intermediate = self._with_test_state(
            testing,
            slot,
            state,
            lifecycle=testing.lifecycle_state,
            failure_code=failure_code,
        )
        all_passed = self._all_configured_slots_passed(intermediate)
        lifecycle = testing.lifecycle_state
        if lifecycle is not CloudProfileLifecycle.ACTIVE:
            lifecycle = (
                CloudProfileLifecycle.VERIFIED
                if all_passed
                else CloudProfileLifecycle.DRAFT
            )
        return replace(
            intermediate,
            lifecycle_state=lifecycle,
            verification_fingerprint=(
                _configuration_fingerprint(intermediate) if all_passed else None
            ),
            version=testing.version + 1,
            last_tested_at=now,
            updated_at=now,
        )

    @staticmethod
    def _safe_failure_code(value: str | None) -> str:
        if value is not None and _FAILURE_CODE.fullmatch(value):
            return value
        return "TTS_CLOUD_PROVIDER_TEST_FAILED"

    @staticmethod
    def _normalized_test_result(
        result: CloudProfileProviderTestResult,
        *,
        expected_model_id: str,
    ) -> CloudProfileProviderTestResult:
        if not result.passed:
            return result
        if (
            not result.actual_model_id
            or result.actual_model_id != expected_model_id
            or not result.audio
            or result.content_type != "audio/wav"
            or result.sample_rate_hz is None
            or result.sample_rate_hz < 1
            or result.sample_rate_hz > 384000
        ):
            return CloudProfileProviderTestResult(
                passed=False,
                failure_code="TTS_CLOUD_PROVIDER_RESPONSE_INVALID",
            )
        return result

    @staticmethod
    def _test_response(
        record: CloudProfileRecord,
        slot: CloudProfileModelSlot,
        result: CloudProfileProviderTestResult,
    ) -> CloudProfileTestResponse:
        passed = result.passed is True
        failure_code = (
            None
            if passed
            else CloudProfileService._safe_failure_code(result.failure_code)
        )
        return CloudProfileTestResponse(
            profile=_resource(record),
            slot=slot,
            status="passed" if passed else "failed",
            actual_model_id=result.actual_model_id if passed else None,
            audio_base64=(
                base64.b64encode(result.audio).decode("ascii")
                if passed and result.audio
                else None
            ),
            content_type=result.content_type if passed else None,
            sample_rate_hz=result.sample_rate_hz if passed else None,
            failure_code=failure_code,
        )


__all__ = [
    "CloudProfileCollection",
    "CloudProfileError",
    "CloudProfileLifecycle",
    "CloudProfileModelSlot",
    "CloudProfileMutationRequest",
    "CloudProfileProviderTestCommand",
    "CloudProfileProviderTestPort",
    "CloudProfileProviderTestResult",
    "CloudProfileRecord",
    "CloudProfileRepository",
    "CloudProfileResource",
    "CloudProfileScope",
    "CloudProfileSecretPort",
    "CloudProfileService",
    "CloudProfileTestResponse",
    "CloudProfileTestState",
    "CreateCloudProfileRequest",
    "IdempotencyClaim",
    "IdempotencyClaimState",
    "PatchCloudProfileRequest",
    "NARRATION_CLOUD_TTS_CONSENT_PURPOSE",
    "QWEN_AUDIO_NATIVE_HTTP_PROTOCOL",
    "StoredCloudCredential",
    "TTS_CLOUD_PROFILES_SCHEMA_VERSION",
    "TTS_CLOUD_TEST_SAMPLE_TEXT",
    "TestCloudProfileRequest",
    "normalize_cloud_base_url",
]
