"""Production adapters for workspace-scoped cloud TTS profiles.

The configuration API is deliberately small: PostgreSQL owns profile state,
the existing AES-GCM vault owns write-only credentials under a separate
``tts-cloud`` namespace, and a provider is built only for an exact frozen
profile binding.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Mapping
from uuid import UUID, uuid4

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from ..database import get_engine
from ..embedding.api import SECRET_DIR_ENV, SECRET_ROOT_ENV
from ..embedding.secrets import EmbeddingSecretError, EmbeddingSecretStore
from ..models import (
    NarrationCloudConsent,
    NarrationEdition,
    NarrationSettingsSnapshot,
    TTSCloudProfile,
)
from .cloud_profiles import (
    CloudProfileError,
    CloudProfileLifecycle,
    CloudProfileProviderTestCommand,
    CloudProfileProviderTestResult,
    CloudProfileRecord,
    CloudProfileRepository,
    CloudProfileScope,
    CloudProfileSecretPort,
    CloudProfileService,
    CloudProfileTestState,
    IdempotencyClaim,
    IdempotencyClaimState,
    NARRATION_CLOUD_TTS_CONSENT_PURPOSE,
    StoredCloudCredential,
)
from .contracts import NarrationRequestScope, TTSSynthesisRequest, TTSVoiceInput, TTSVoiceKind
from .official_presets import OFFICIAL_PRESETS
from .providers.aliyun import AliyunQwenAudioTTSProvider
from .providers.base import TTSProvider, TTSProviderError


SessionFactory = Callable[[], Session]
_MAX_IDEMPOTENCY_ENTRIES = 512


@dataclass(slots=True)
class _Operation:
    request_fingerprint: str
    response: Mapping[str, object] | None = None


class _ProcessIdempotency:
    """Bound duplicate paid clicks in this single-process personal PawApp."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._entries: OrderedDict[tuple[UUID, UUID, str], _Operation] = OrderedDict()

    def begin(
        self,
        scope: CloudProfileScope,
        key: str,
        fingerprint: str,
    ) -> IdempotencyClaim:
        identity = (scope.owner_id, scope.workspace_id, key)
        with self._lock:
            existing = self._entries.get(identity)
            if existing is not None:
                if existing.request_fingerprint != fingerprint:
                    raise CloudProfileError(
                        "TTS_CLOUD_PROFILE_IDEMPOTENCY_CONFLICT",
                        "相同幂等键已用于另一项操作。",
                    )
                self._entries.move_to_end(identity)
                if existing.response is None:
                    return IdempotencyClaim(IdempotencyClaimState.IN_PROGRESS)
                return IdempotencyClaim(
                    IdempotencyClaimState.REPLAY,
                    response=existing.response,
                )
            self._entries[identity] = _Operation(fingerprint)
            self._trim()
            return IdempotencyClaim(IdempotencyClaimState.ACQUIRED)

    def complete(
        self,
        scope: CloudProfileScope,
        key: str,
        fingerprint: str,
        response: Mapping[str, object],
    ) -> None:
        identity = (scope.owner_id, scope.workspace_id, key)
        with self._lock:
            existing = self._entries.get(identity)
            if existing is None or existing.request_fingerprint != fingerprint:
                raise CloudProfileError(
                    "TTS_CLOUD_PROFILE_IDEMPOTENCY_INVALID",
                    "操作记录暂不可用。",
                )
            existing.response = dict(response)
            self._entries.move_to_end(identity)
            self._trim()

    def abort(self, scope: CloudProfileScope, key: str, fingerprint: str) -> None:
        identity = (scope.owner_id, scope.workspace_id, key)
        with self._lock:
            existing = self._entries.get(identity)
            if (
                existing is not None
                and existing.request_fingerprint == fingerprint
                and existing.response is None
            ):
                self._entries.pop(identity, None)

    def _trim(self) -> None:
        while len(self._entries) > _MAX_IDEMPOTENCY_ENTRIES:
            first_key, first = next(iter(self._entries.items()))
            if first.response is None:
                break
            self._entries.pop(first_key, None)


_IDEMPOTENCY = _ProcessIdempotency()


def _record(row: TTSCloudProfile) -> CloudProfileRecord:
    return CloudProfileRecord(
        id=row.id,
        owner_id=row.owner_id,
        workspace_id=row.workspace_id,
        name=row.name,
        protocol=row.protocol,
        base_url=row.base_url,
        credential_ref=row.credential_ref,
        api_key_last4=row.api_key_last4,
        api_key_updated_at=row.api_key_updated_at,
        quality_model_id=row.quality_model_id,
        speed_model_id=row.speed_model_id,
        quality_test_state=CloudProfileTestState(row.quality_test_state),
        speed_test_state=CloudProfileTestState(row.speed_test_state),
        lifecycle_state=CloudProfileLifecycle(row.lifecycle_state),
        verification_fingerprint=row.verification_fingerprint,
        version=row.version,
        last_tested_at=row.last_tested_at,
        failure_code=row.failure_code,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _apply(row: TTSCloudProfile, record: CloudProfileRecord) -> None:
    row.name = record.name
    row.protocol = record.protocol
    row.base_url = record.base_url
    row.credential_ref = record.credential_ref
    row.api_key_last4 = record.api_key_last4
    row.api_key_updated_at = record.api_key_updated_at
    row.quality_model_id = record.quality_model_id
    row.speed_model_id = record.speed_model_id
    row.quality_test_state = record.quality_test_state.value
    row.speed_test_state = record.speed_test_state.value
    row.lifecycle_state = record.lifecycle_state.value
    row.verification_fingerprint = record.verification_fingerprint
    row.version = record.version
    row.last_tested_at = record.last_tested_at
    row.failure_code = record.failure_code
    row.updated_at = record.updated_at


class SqlAlchemyCloudProfileRepository(CloudProfileRepository):
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def list_profiles(self, scope: CloudProfileScope) -> list[CloudProfileRecord]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(TTSCloudProfile)
                .where(
                    TTSCloudProfile.owner_id == scope.owner_id,
                    TTSCloudProfile.workspace_id == scope.workspace_id,
                )
                .order_by(TTSCloudProfile.created_at, TTSCloudProfile.id)
            ).all()
            return [_record(row) for row in rows]

    def get_profile(
        self, scope: CloudProfileScope, profile_id: UUID
    ) -> CloudProfileRecord | None:
        with self._session_factory() as session:
            row = session.scalar(
                select(TTSCloudProfile).where(
                    TTSCloudProfile.id == profile_id,
                    TTSCloudProfile.owner_id == scope.owner_id,
                    TTSCloudProfile.workspace_id == scope.workspace_id,
                )
            )
            return _record(row) if row is not None else None

    def create_profile(
        self, scope: CloudProfileScope, record: CloudProfileRecord
    ) -> CloudProfileRecord:
        row = TTSCloudProfile(
            id=record.id,
            owner_id=scope.owner_id,
            workspace_id=scope.workspace_id,
            name=record.name,
            protocol=record.protocol,
            base_url=record.base_url,
            credential_ref=record.credential_ref,
            api_key_last4=record.api_key_last4,
            api_key_updated_at=record.api_key_updated_at,
            quality_model_id=record.quality_model_id,
            speed_model_id=record.speed_model_id,
            quality_test_state=record.quality_test_state.value,
            speed_test_state=record.speed_test_state.value,
            lifecycle_state=record.lifecycle_state.value,
            verification_fingerprint=record.verification_fingerprint,
            version=record.version,
            last_tested_at=record.last_tested_at,
            failure_code=record.failure_code,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
        with self._session_factory() as session:
            session.add(row)
            try:
                session.commit()
            except IntegrityError as error:
                session.rollback()
                raise CloudProfileError(
                    "TTS_CLOUD_PROFILE_NAME_CONFLICT",
                    "同名云端语音渠道已经存在。",
                ) from error
        return record

    def replace_profile(
        self,
        scope: CloudProfileScope,
        record: CloudProfileRecord,
        *,
        expected_version: int,
    ) -> CloudProfileRecord:
        with self._session_factory() as session:
            row = session.scalar(
                select(TTSCloudProfile)
                .where(
                    TTSCloudProfile.id == record.id,
                    TTSCloudProfile.owner_id == scope.owner_id,
                    TTSCloudProfile.workspace_id == scope.workspace_id,
                )
                .with_for_update()
            )
            if row is None:
                raise CloudProfileError(
                    "TTS_CLOUD_PROFILE_NOT_FOUND",
                    "找不到请求的云端语音渠道。",
                )
            if row.version != expected_version:
                raise CloudProfileError(
                    "TTS_CLOUD_PROFILE_VERSION_CONFLICT",
                    "配置已更新，请刷新后重试。",
                )
            _apply(row, record)
            try:
                session.commit()
            except IntegrityError as error:
                session.rollback()
                raise CloudProfileError(
                    "TTS_CLOUD_PROFILE_NAME_CONFLICT",
                    "同名云端语音渠道已经存在。",
                ) from error
            session.refresh(row)
            return _record(row)

    def activate_profile(
        self,
        scope: CloudProfileScope,
        profile_id: UUID,
        *,
        expected_version: int,
        updated_at: datetime,
        revoke_consent_purpose: str,
    ) -> list[CloudProfileRecord]:
        if revoke_consent_purpose != NARRATION_CLOUD_TTS_CONSENT_PURPOSE:
            raise CloudProfileError(
                "TTS_CLOUD_PROFILE_INVARIANT_FAILED",
                "云端语音授权范围不兼容。",
            )
        with self._session_factory() as session:
            rows = session.scalars(
                select(TTSCloudProfile)
                .where(
                    TTSCloudProfile.owner_id == scope.owner_id,
                    TTSCloudProfile.workspace_id == scope.workspace_id,
                )
                .order_by(TTSCloudProfile.id)
                .with_for_update()
            ).all()
            target = next((row for row in rows if row.id == profile_id), None)
            if target is None:
                raise CloudProfileError(
                    "TTS_CLOUD_PROFILE_NOT_FOUND",
                    "找不到请求的云端语音渠道。",
                )
            if target.version != expected_version:
                raise CloudProfileError(
                    "TTS_CLOUD_PROFILE_VERSION_CONFLICT",
                    "配置已更新，请刷新后重试。",
                )
            changed = target.lifecycle_state != CloudProfileLifecycle.ACTIVE.value
            for row in rows:
                if row.id == profile_id:
                    if changed:
                        row.lifecycle_state = CloudProfileLifecycle.ACTIVE.value
                        row.version += 1
                        row.updated_at = updated_at
                elif row.lifecycle_state == CloudProfileLifecycle.ACTIVE.value:
                    row.lifecycle_state = (
                        CloudProfileLifecycle.VERIFIED.value
                        if row.quality_test_state == "passed"
                        and (
                            row.speed_model_id is None
                            or row.speed_test_state == "passed"
                        )
                        else CloudProfileLifecycle.DRAFT.value
                    )
                    row.version += 1
                    row.updated_at = updated_at
            if changed:
                active_consents = session.scalars(
                    select(NarrationCloudConsent)
                    .where(
                        NarrationCloudConsent.purpose == revoke_consent_purpose,
                        NarrationCloudConsent.revoked_at.is_(None),
                    )
                    .with_for_update()
                ).all()
                for consent in active_consents:
                    consent.revoked_at = updated_at
            session.commit()
            return [_record(row) for row in rows]

    def delete_profile(
        self,
        scope: CloudProfileScope,
        profile_id: UUID,
        *,
        expected_version: int,
    ) -> None:
        with self._session_factory() as session:
            row = session.scalar(
                select(TTSCloudProfile)
                .where(
                    TTSCloudProfile.id == profile_id,
                    TTSCloudProfile.owner_id == scope.owner_id,
                    TTSCloudProfile.workspace_id == scope.workspace_id,
                )
                .with_for_update()
            )
            if row is None:
                raise CloudProfileError(
                    "TTS_CLOUD_PROFILE_NOT_FOUND",
                    "找不到请求的云端语音渠道。",
                )
            if row.version != expected_version:
                raise CloudProfileError(
                    "TTS_CLOUD_PROFILE_VERSION_CONFLICT",
                    "配置已更新，请刷新后重试。",
                )
            session.delete(row)
            session.commit()

    def has_in_flight_references(
        self, scope: CloudProfileScope, profile_id: UUID
    ) -> bool:
        try:
            with self._session_factory() as session:
                profile_path = (
                    NarrationSettingsSnapshot.snapshot_json["resolved_settings"]
                    ["settings"]["tts_provider"]["cloud_profile_id"].astext
                )
                return session.scalar(
                    select(NarrationEdition.id)
                    .join(
                        NarrationSettingsSnapshot,
                        NarrationSettingsSnapshot.id
                        == NarrationEdition.settings_snapshot_id,
                    )
                    .where(
                        NarrationEdition.owner_id == scope.owner_id,
                        NarrationEdition.workspace_id == scope.workspace_id,
                        NarrationEdition.state.in_(
                            ("created", "rendering", "partial_ready")
                        ),
                        profile_path == str(profile_id),
                    )
                    .limit(1)
                ) is not None
        except Exception:
            return True

    def begin_idempotent_operation(
        self,
        scope: CloudProfileScope,
        *,
        operation: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> IdempotencyClaim:
        claim = _IDEMPOTENCY.begin(scope, idempotency_key, request_fingerprint)
        if claim.state is not IdempotencyClaimState.ACQUIRED or not operation.startswith(
            "test:"
        ):
            return claim
        try:
            profile_id = UUID(operation.split(":", 1)[1])
            with self._session_factory() as session:
                row = session.scalar(
                    select(TTSCloudProfile)
                    .where(
                        TTSCloudProfile.id == profile_id,
                        TTSCloudProfile.owner_id == scope.owner_id,
                        TTSCloudProfile.workspace_id == scope.workspace_id,
                    )
                    .with_for_update()
                )
                if row is None:
                    return claim
                if row.last_operation_key == idempotency_key:
                    _IDEMPOTENCY.abort(scope, idempotency_key, request_fingerprint)
                    if row.last_operation_hash != request_fingerprint:
                        raise CloudProfileError(
                            "TTS_CLOUD_PROFILE_IDEMPOTENCY_CONFLICT",
                            "相同幂等键已用于另一项操作。",
                        )
                    return IdempotencyClaim(IdempotencyClaimState.IN_PROGRESS)
                row.last_operation_key = idempotency_key
                row.last_operation_hash = request_fingerprint
                session.commit()
            return claim
        except Exception:
            _IDEMPOTENCY.abort(scope, idempotency_key, request_fingerprint)
            raise

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
        _IDEMPOTENCY.complete(
            scope, idempotency_key, request_fingerprint, response
        )

    def abort_idempotent_operation(
        self,
        scope: CloudProfileScope,
        *,
        operation: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> None:
        del operation
        _IDEMPOTENCY.abort(scope, idempotency_key, request_fingerprint)


class EncryptedCloudProfileSecretStore(CloudProfileSecretPort):
    def __init__(self, store: EmbeddingSecretStore) -> None:
        self._store = store

    def put(self, api_key: SecretStr) -> StoredCloudCredential:
        try:
            stored = self._store.put(api_key.get_secret_value())
        except EmbeddingSecretError as error:
            raise CloudProfileError(
                "TTS_CLOUD_PROFILE_INVARIANT_FAILED",
                "语音渠道密钥保存失败。",
            ) from error
        return StoredCloudCredential(
            credential_ref=stored.credential_ref,
            last4=stored.last4,
            updated_at=datetime.now(UTC),
        )

    def get(self, credential_ref: str) -> SecretStr:
        try:
            return SecretStr(self._store.get(credential_ref))
        except EmbeddingSecretError as error:
            raise CloudProfileError(
                "TTS_CLOUD_PROFILE_INVARIANT_FAILED",
                "语音渠道密钥暂不可用。",
            ) from error

    def delete(self, credential_ref: str) -> None:
        try:
            self._store.delete(credential_ref)
        except EmbeddingSecretError as error:
            raise CloudProfileError(
                "TTS_CLOUD_PROFILE_INVARIANT_FAILED",
                "语音渠道密钥清理失败。",
            ) from error


class QwenAudioCloudProfileTester:
    """One explicit, billed, fixed-text synthesis used by the settings page."""

    def test(
        self, command: CloudProfileProviderTestCommand
    ) -> CloudProfileProviderTestResult:
        provider = AliyunQwenAudioTTSProvider(
            api_key=command.api_key.get_secret_value(),
            base_url=command.base_url,
            model_id=command.model_id,
            product_released=False,
        )
        voice_id = (
            OFFICIAL_PRESETS[0].aliyun_plus_voice_id
            if command.slot.value == "quality"
            else OFFICIAL_PRESETS[0].aliyun_flash_voice_id
        )
        request = TTSSynthesisRequest(
            request_id=uuid4(),
            scope=NarrationRequestScope.fixed_local(),
            text=command.sample_text,
            language="zh-CN",
            voice=TTSVoiceInput(
                kind=TTSVoiceKind.PRESET,
                provider_voice_id=voice_id,
            ),
            seed=7,
        )
        try:
            result = asyncio.run(provider.synthesize(request))
        except TTSProviderError as error:
            return CloudProfileProviderTestResult(
                passed=False,
                failure_code=error.code,
            )
        return CloudProfileProviderTestResult(
            passed=True,
            actual_model_id=result.model_identity.model_id,
            audio=result.audio_bytes,
            content_type=result.content_type,
            sample_rate_hz=result.sample_rate_hz,
        )


def cloud_secret_store_from_environment(
    environ: Mapping[str, str],
) -> EncryptedCloudProfileSecretStore:
    root = environ.get(SECRET_ROOT_ENV, "").strip()
    records = environ.get(SECRET_DIR_ENV, "").strip()
    if not root or not records:
        raise CloudProfileError(
            "TTS_CLOUD_PROFILE_INVARIANT_FAILED",
            "语音渠道密钥保险箱尚未配置。",
        )
    try:
        store = EmbeddingSecretStore(
            root_key_path=Path(root),
            records_dir=Path(records),
            namespace="tts-cloud",
        )
        store.validate()
    except EmbeddingSecretError as error:
        raise CloudProfileError(
            "TTS_CLOUD_PROFILE_INVARIANT_FAILED",
            "语音渠道密钥保险箱暂不可用。",
        ) from error
    return EncryptedCloudProfileSecretStore(store)


def default_cloud_profile_session_factory() -> SessionFactory:
    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return factory


def build_cloud_profile_service(
    environ: Mapping[str, str] | None = None,
) -> CloudProfileService:
    values = os.environ if environ is None else environ
    session_factory = default_cloud_profile_session_factory()
    return CloudProfileService(
        SqlAlchemyCloudProfileRepository(session_factory),
        cloud_secret_store_from_environment(values),
        QwenAudioCloudProfileTester(),
    )


def build_cloud_provider_resolver(
    session_factory: SessionFactory,
    secrets: EncryptedCloudProfileSecretStore,
) -> Callable[[UUID, int, str, str, str, str], TTSProvider]:
    def resolve(
        profile_id: UUID,
        profile_version: int,
        protocol: str,
        actual_model_id: str,
        base_url_fingerprint: str,
        verification_fingerprint: str,
    ) -> TTSProvider:
        with session_factory() as session:
            row = session.scalar(
                select(TTSCloudProfile).where(TTSCloudProfile.id == profile_id)
            )
            if (
                row is None
                or row.version < profile_version
                or row.protocol != protocol
                or row.lifecycle_state
                not in {
                    CloudProfileLifecycle.ACTIVE.value,
                    CloudProfileLifecycle.VERIFIED.value,
                }
                or row.credential_ref is None
                or row.verification_fingerprint != verification_fingerprint
                or hashlib.sha256(row.base_url.encode("utf-8")).hexdigest()
                != base_url_fingerprint
                or actual_model_id not in {row.quality_model_id, row.speed_model_id}
            ):
                raise TTSProviderError("TTS_PROVIDER_DISABLED", retryable=False)
            credential_ref = row.credential_ref
            base_url = row.base_url
        try:
            api_key = secrets.get(credential_ref).get_secret_value()
        except (CloudProfileError, EmbeddingSecretError):
            raise TTSProviderError("TTS_PROVIDER_DISABLED", retryable=False) from None
        return AliyunQwenAudioTTSProvider(
            api_key=api_key,
            base_url=base_url,
            model_id=actual_model_id,
            product_released=True,
        )

    return resolve


__all__ = [
    "EncryptedCloudProfileSecretStore",
    "QwenAudioCloudProfileTester",
    "SqlAlchemyCloudProfileRepository",
    "build_cloud_provider_resolver",
    "build_cloud_profile_service",
    "cloud_secret_store_from_environment",
    "default_cloud_profile_session_factory",
]
