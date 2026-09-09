from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Mapping
from uuid import UUID

import pytest
from pydantic import SecretStr, ValidationError

from backend.narration.cloud_profiles import (
    NARRATION_CLOUD_TTS_CONSENT_PURPOSE,
    TTS_CLOUD_TEST_SAMPLE_TEXT,
    CloudProfileError,
    CloudProfileLifecycle,
    CloudProfileModelSlot,
    CloudProfileMutationRequest,
    CloudProfileProviderTestCommand,
    CloudProfileProviderTestResult,
    CloudProfileRecord,
    CloudProfileScope,
    CloudProfileService,
    CloudProfileTestState,
    CreateCloudProfileRequest,
    IdempotencyClaim,
    IdempotencyClaimState,
    PatchCloudProfileRequest,
    StoredCloudCredential,
    TestCloudProfileRequest as _TestCloudProfileRequest,
)


PROFILE_A = UUID("61000000-0000-4000-8000-000000000001")
PROFILE_B = UUID("61000000-0000-4000-8000-000000000002")


class FakeRepository:
    def __init__(self) -> None:
        self.rows: dict[UUID, CloudProfileRecord] = {}
        self.operations: dict[tuple[UUID, str], dict[str, object]] = {}
        self.in_flight: set[UUID] = set()
        self.consent_revocations: list[str] = []

    def list_profiles(self, scope: CloudProfileScope) -> list[CloudProfileRecord]:
        return [
            row
            for row in self.rows.values()
            if row.owner_id == scope.owner_id and row.workspace_id == scope.workspace_id
        ]

    def get_profile(
        self, scope: CloudProfileScope, profile_id: UUID
    ) -> CloudProfileRecord | None:
        row = self.rows.get(profile_id)
        if row is None or row.owner_id != scope.owner_id or row.workspace_id != scope.workspace_id:
            return None
        return row

    def create_profile(
        self, scope: CloudProfileScope, record: CloudProfileRecord
    ) -> CloudProfileRecord:
        if any(row.name == record.name for row in self.list_profiles(scope)):
            raise CloudProfileError("TTS_CLOUD_PROFILE_NAME_CONFLICT", "渠道名称已存在。")
        self.rows[record.id] = record
        return record

    def replace_profile(
        self,
        scope: CloudProfileScope,
        record: CloudProfileRecord,
        *,
        expected_version: int,
    ) -> CloudProfileRecord:
        current = self.get_profile(scope, record.id)
        if current is None:
            raise CloudProfileError("TTS_CLOUD_PROFILE_NOT_FOUND", "not found")
        if current.version != expected_version:
            raise CloudProfileError("TTS_CLOUD_PROFILE_VERSION_CONFLICT", "conflict")
        if any(
            row.id != record.id and row.name == record.name
            for row in self.list_profiles(scope)
        ):
            raise CloudProfileError("TTS_CLOUD_PROFILE_NAME_CONFLICT", "duplicate")
        self.rows[record.id] = record
        return record

    def activate_profile(
        self,
        scope: CloudProfileScope,
        profile_id: UUID,
        *,
        expected_version: int,
        updated_at: datetime,
        revoke_consent_purpose: str,
    ) -> list[CloudProfileRecord]:
        target = self.get_profile(scope, profile_id)
        assert target is not None
        if target.version != expected_version:
            raise CloudProfileError("TTS_CLOUD_PROFILE_VERSION_CONFLICT", "conflict")
        assert revoke_consent_purpose == NARRATION_CLOUD_TTS_CONSENT_PURPOSE
        self.consent_revocations.append(revoke_consent_purpose)
        for row in list(self.list_profiles(scope)):
            if row.lifecycle_state is CloudProfileLifecycle.ACTIVE:
                self.rows[row.id] = replace(
                    row,
                    lifecycle_state=CloudProfileLifecycle.VERIFIED,
                    version=row.version + 1,
                    updated_at=updated_at,
                )
        target = self.rows[profile_id]
        self.rows[profile_id] = replace(
            target,
            lifecycle_state=CloudProfileLifecycle.ACTIVE,
            version=target.version + 1,
            updated_at=updated_at,
        )
        return self.list_profiles(scope)

    def delete_profile(
        self,
        scope: CloudProfileScope,
        profile_id: UUID,
        *,
        expected_version: int,
    ) -> None:
        current = self.get_profile(scope, profile_id)
        assert current is not None
        if current.version != expected_version:
            raise CloudProfileError("TTS_CLOUD_PROFILE_VERSION_CONFLICT", "conflict")
        del self.rows[profile_id]

    def has_in_flight_references(
        self, scope: CloudProfileScope, profile_id: UUID
    ) -> bool:
        assert self.get_profile(scope, profile_id) is not None
        return profile_id in self.in_flight

    def begin_idempotent_operation(
        self,
        scope: CloudProfileScope,
        *,
        operation: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> IdempotencyClaim:
        del operation
        key = (scope.workspace_id, idempotency_key)
        stored = self.operations.get(key)
        if stored is None:
            self.operations[key] = {"fingerprint": request_fingerprint, "response": None}
            return IdempotencyClaim(IdempotencyClaimState.ACQUIRED)
        if stored["fingerprint"] != request_fingerprint:
            raise CloudProfileError(
                "TTS_CLOUD_PROFILE_IDEMPOTENCY_CONFLICT", "idempotency conflict"
            )
        response = stored["response"]
        if response is None:
            return IdempotencyClaim(IdempotencyClaimState.IN_PROGRESS)
        assert isinstance(response, Mapping)
        return IdempotencyClaim(IdempotencyClaimState.REPLAY, response)

    def complete_idempotent_operation(
        self,
        scope: CloudProfileScope,
        *,
        operation: str,
        idempotency_key: str,
        request_fingerprint: str,
        response: Mapping[str, object],
    ) -> None:
        del operation
        self.operations[(scope.workspace_id, idempotency_key)] = {
            "fingerprint": request_fingerprint,
            "response": dict(response),
        }

    def abort_idempotent_operation(
        self,
        scope: CloudProfileScope,
        *,
        operation: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> None:
        del operation
        key = (scope.workspace_id, idempotency_key)
        current = self.operations.get(key)
        if current is not None and current["fingerprint"] == request_fingerprint:
            self.operations.pop(key)


class FakeSecrets:
    def __init__(self) -> None:
        self.values: dict[str, SecretStr] = {}
        self.put_count = 0
        self.deleted: list[str] = []

    def put(self, api_key: SecretStr) -> StoredCloudCredential:
        self.put_count += 1
        reference = f"tts-cloud/{self.put_count}"
        self.values[reference] = api_key
        return StoredCloudCredential(
            credential_ref=reference,
            last4=api_key.get_secret_value()[-4:],
            updated_at=datetime.now(UTC),
        )

    def get(self, credential_ref: str) -> SecretStr:
        return self.values[credential_ref]

    def delete(self, credential_ref: str) -> None:
        self.deleted.append(credential_ref)
        self.values.pop(credential_ref, None)


class FakeProviderTests:
    def __init__(self) -> None:
        self.commands: list[CloudProfileProviderTestCommand] = []
        self.result = CloudProfileProviderTestResult(
            passed=True,
            actual_model_id="partner-plus",
            audio=b"RIFF-test-wave",
            content_type="audio/wav",
            sample_rate_hz=24000,
        )

    def test(self, command: CloudProfileProviderTestCommand) -> CloudProfileProviderTestResult:
        self.commands.append(command)
        return self.result


@pytest.fixture
def ports() -> tuple[FakeRepository, FakeSecrets, FakeProviderTests, CloudProfileService]:
    repository = FakeRepository()
    secrets = FakeSecrets()
    provider = FakeProviderTests()
    return repository, secrets, provider, CloudProfileService(repository, secrets, provider)


def create_payload(
    *, key: str = "profile-create-0001", name: str = "会员渠道 A"
) -> CreateCloudProfileRequest:
    return CreateCloudProfileRequest(
        expected_version=0,
        idempotency_key=key,
        name=name,
        base_url="https://tts.partner.example/gateway/v1/",
        quality_model_id="partner-plus",
        api_key="secret-key-12345678",
    )


def first_profile(service: CloudProfileService) -> CloudProfileRecord:
    records = service.repository.list_profiles(service.scope)
    assert len(records) == 1
    return records[0]


def test_create_is_idempotent_and_never_exposes_plaintext_key(
    ports: tuple[FakeRepository, FakeSecrets, FakeProviderTests, CloudProfileService],
) -> None:
    _, secrets, provider, service = ports
    payload = create_payload()

    first = service.create(payload)
    replay = service.create(payload)

    assert replay == first
    assert secrets.put_count == 1
    assert provider.commands == []
    dumped = first.model_dump_json()
    assert "secret-key" not in dumped
    assert "credential_ref" not in dumped
    assert first.items[0].api_key_masked == "••••5678"
    assert first.items[0].base_url == "https://tts.partner.example/gateway/v1"
    assert first.items[0].lifecycle_state is CloudProfileLifecycle.DRAFT
    assert first.active_profile_id is None


def test_request_contract_is_strict_and_does_not_accept_test_text() -> None:
    with pytest.raises(ValidationError):
        CreateCloudProfileRequest.model_validate(
            {**create_payload().model_dump(), "unknown": "value"}
        )
    with pytest.raises(ValidationError):
        _TestCloudProfileRequest.model_validate(
            {
                "expected_version": 1,
                "idempotency_key": "profile-test-0001",
                "slot": "quality",
                "billing_confirmed": True,
                "text": "小说正文不允许进入测试命令",
            }
        )
    with pytest.raises(ValidationError):
        CreateCloudProfileRequest.model_validate(
            {**create_payload().model_dump(), "base_url": "http://localhost:8000"}
        )


def test_test_requires_billing_confirmation_and_uses_fixed_sample(
    ports: tuple[FakeRepository, FakeSecrets, FakeProviderTests, CloudProfileService],
) -> None:
    _, _, provider, service = ports
    service.create(create_payload())
    profile = first_profile(service)
    denied = _TestCloudProfileRequest(
        expected_version=profile.version,
        idempotency_key="profile-test-denied",
        slot="quality",
        billing_confirmed=False,
    )
    with pytest.raises(CloudProfileError, match="确认") as caught:
        service.test(profile.id, denied)
    assert caught.value.code == "TTS_CLOUD_PROFILE_BILLING_CONFIRMATION_REQUIRED"
    assert provider.commands == []

    allowed = denied.model_copy(
        update={"billing_confirmed": True, "idempotency_key": "profile-test-allowed"}
    )
    response = service.test(profile.id, allowed)
    assert response.status == "passed"
    assert response.audio_base64 is not None
    assert response.profile.lifecycle_state is CloudProfileLifecycle.VERIFIED
    assert len(provider.commands) == 1
    assert provider.commands[0].sample_text == TTS_CLOUD_TEST_SAMPLE_TEXT
    assert provider.commands[0].api_key.get_secret_value() == "secret-key-12345678"

    replay = service.test(profile.id, allowed)
    assert replay == response
    assert len(provider.commands) == 1


def test_editing_connection_invalidates_verification_and_active_requires_disable(
    ports: tuple[FakeRepository, FakeSecrets, FakeProviderTests, CloudProfileService],
) -> None:
    _, _, _, service = ports
    service.create(create_payload())
    profile = first_profile(service)
    tested = service.test(
        profile.id,
        _TestCloudProfileRequest(
            expected_version=profile.version,
            idempotency_key="profile-test-0002",
            slot="quality",
            billing_confirmed=True,
        ),
    ).profile
    active = service.activate(
        profile.id,
        CloudProfileMutationRequest(
            expected_version=tested.version,
            idempotency_key="profile-activate-0001",
        ),
    ).items[0]

    with pytest.raises(CloudProfileError) as active_delete:
        service.delete(
            profile.id,
            CloudProfileMutationRequest(
                expected_version=active.version,
                idempotency_key="profile-delete-active",
            ),
        )
    assert active_delete.value.code == "TTS_CLOUD_PROFILE_ACTIVE"

    renamed = service.patch(
        profile.id,
        PatchCloudProfileRequest(
            expected_version=active.version,
            idempotency_key="profile-rename-0001",
            name="只改显示名称",
        ),
    ).items[0]
    assert renamed.lifecycle_state is CloudProfileLifecycle.ACTIVE
    with pytest.raises(CloudProfileError) as caught:
        service.patch(
            profile.id,
            PatchCloudProfileRequest(
                expected_version=renamed.version,
                idempotency_key="profile-url-edit-0001",
                base_url="https://other.partner.example/v1",
            ),
        )
    assert caught.value.code == "TTS_CLOUD_PROFILE_ACTIVE_EDIT_FORBIDDEN"

    disabled = service.disable(
        profile.id,
        CloudProfileMutationRequest(
            expected_version=renamed.version,
            idempotency_key="profile-disable-0001",
        ),
    ).items[0]
    changed = service.patch(
        profile.id,
        PatchCloudProfileRequest(
            expected_version=disabled.version,
            idempotency_key="profile-url-edit-0002",
            base_url="https://other.partner.example/v1",
            speed_model_id="partner-flash",
        ),
    ).items[0]
    assert changed.lifecycle_state is CloudProfileLifecycle.DRAFT
    assert changed.quality_test_state is CloudProfileTestState.UNTESTED
    assert changed.speed_test_state is CloudProfileTestState.UNTESTED


def test_activate_is_atomic_single_active_and_revokes_cloud_tts_consent(
    ports: tuple[FakeRepository, FakeSecrets, FakeProviderTests, CloudProfileService],
) -> None:
    repository, _, _, service = ports
    first = service.create(create_payload()).items[0]
    service.test(
        first.id,
        _TestCloudProfileRequest(
            expected_version=first.version,
            idempotency_key="profile-test-a001",
            slot=CloudProfileModelSlot.QUALITY,
            billing_confirmed=True,
        ),
    )
    first = service.list().items[0]
    service.activate(
        first.id,
        CloudProfileMutationRequest(
            expected_version=first.version,
            idempotency_key="profile-activate-a",
        ),
    )

    created = service.create(
        create_payload(key="profile-create-0002", name="会员渠道 B")
    )
    second = next(item for item in created.items if item.name == "会员渠道 B")
    service.test(
        second.id,
        _TestCloudProfileRequest(
            expected_version=second.version,
            idempotency_key="profile-test-b001",
            slot="quality",
            billing_confirmed=True,
        ),
    )
    second = next(item for item in service.list().items if item.name == "会员渠道 B")
    switched = service.activate(
        second.id,
        CloudProfileMutationRequest(
            expected_version=second.version,
            idempotency_key="profile-activate-b",
        ),
    )
    assert switched.active_profile_id == second.id
    assert sum(item.lifecycle_state is CloudProfileLifecycle.ACTIVE for item in switched.items) == 1
    assert repository.consent_revocations == [
        NARRATION_CLOUD_TTS_CONSENT_PURPOSE,
        NARRATION_CLOUD_TTS_CONSENT_PURPOSE,
    ]


def test_delete_rejects_active_and_in_flight_then_removes_secret(
    ports: tuple[FakeRepository, FakeSecrets, FakeProviderTests, CloudProfileService],
) -> None:
    repository, secrets, _, service = ports
    profile = service.create(create_payload()).items[0]
    repository.in_flight.add(profile.id)
    mutation = CloudProfileMutationRequest(
        expected_version=profile.version,
        idempotency_key="profile-delete-0001",
    )
    with pytest.raises(CloudProfileError) as caught:
        service.delete(profile.id, mutation)
    assert caught.value.code == "TTS_CLOUD_PROFILE_IN_FLIGHT"
    repository.in_flight.clear()

    emptied = service.delete(
        profile.id,
        mutation.model_copy(update={"idempotency_key": "profile-delete-0002"}),
    )
    assert emptied.items == []
    assert emptied.active_profile_id is None
    assert secrets.deleted == ["tts-cloud/1"]


def test_missing_speed_slot_and_stale_version_fail_before_provider_call(
    ports: tuple[FakeRepository, FakeSecrets, FakeProviderTests, CloudProfileService],
) -> None:
    _, _, provider, service = ports
    profile = service.create(create_payload()).items[0]
    with pytest.raises(CloudProfileError) as missing:
        service.test(
            profile.id,
            _TestCloudProfileRequest(
                expected_version=profile.version,
                idempotency_key="profile-speed-0001",
                slot="speed",
                billing_confirmed=True,
            ),
        )
    assert missing.value.code == "TTS_CLOUD_PROFILE_MODEL_SLOT_UNAVAILABLE"
    with pytest.raises(CloudProfileError) as stale:
        service.disable(
            profile.id,
            CloudProfileMutationRequest(
                expected_version=99,
                idempotency_key="profile-disable-stale",
            ),
        )
    assert stale.value.code == "TTS_CLOUD_PROFILE_VERSION_CONFLICT"
    assert provider.commands == []
