from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from backend.models import (
    CharacterVoiceBinding,
    Document,
    NarrationCloudConsent as NarrationCloudConsentRow,
    NarrationEdition,
    NarrationScript,
    NarrationScriptVersion,
    NarrationSegment,
    Novel,
    NovelCharacter,
    NovelNarrationSettings,
    NarrationScopeOverride,
    VoiceProfile,
    VoiceProfileVersion,
    VoiceRightsEvent,
    VoiceRightsRecord,
    Volume,
)
from backend.narration import schemas as wire
from backend.narration.contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID
from backend.narration.privacy import (
    FIXED_LOCAL_OWNER_NARRATION_AUTHORIZATION,
    NarrationRequestAuthorization,
    NarrationSettingsBackend,
    READING_PRIVACY_OPERATIONS,
    TransactionalNarrationSettingsBackend,
    cloud_consent_resource,
    create_cloud_consent,
    default_narration_settings_values,
    get_narration_settings,
    narration_coverage,
    narration_runtime_resource,
    revoke_cloud_consent,
    t2_settings_capabilities,
    t4_product_capabilities,
)
from backend.narration.pronunciations import CacheCleanupDisabled, PronunciationSettingsHandler
from backend.narration.services import (
    IdempotencyConflict,
    InvalidNarrationState,
    NarrationCasConflict,
    NarrationScopeMismatch,
    NarrationServiceError,
)
from backend.narration.settings_api import (
    NarrationApiFault,
    NarrationSettingsApiCommand,
    NarrationSettingsOperation,
)
from backend.narration.voices import VoiceSettingsHandler


NOW = datetime(2026, 8, 26, 9, 0, tzinfo=UTC)
NOVEL_ID = UUID("20000000-0000-4000-8000-000000000001")
OTHER_NOVEL_ID = UUID("20000000-0000-4000-8000-000000000002")
CHARACTER_ID = UUID("20000000-0000-4000-8000-000000000003")
PROFILE_ID = UUID("20000000-0000-4000-8000-000000000004")
VOICE_VERSION_ID = UUID("20000000-0000-4000-8000-000000000005")
RIGHTS_ID = UUID("20000000-0000-4000-8000-000000000006")


class MemoryStore:
    def __init__(self, *rows: object) -> None:
        self.rows: dict[type[object], list[object]] = {}
        self.flush_count = 0
        self.deleted: list[object] = []
        for row in rows:
            self.add(row)

    def add(self, row: object) -> None:
        self.rows.setdefault(type(row), []).append(row)

    def delete(self, row: object) -> None:
        self.rows[type(row)].remove(row)
        self.deleted.append(row)

    def flush(self) -> None:
        self.flush_count += 1

    def get(
        self,
        model: type[Any],
        row_id: object,
        *,
        for_update: bool = False,
    ) -> Any | None:
        del for_update
        return next(
            (row for row in self.rows.get(model, []) if getattr(row, "id", None) == row_id),
            None,
        )

    def find_one(
        self,
        model: type[Any],
        *,
        for_update: bool = False,
        **filters: object,
    ) -> Any | None:
        del for_update
        return next(iter(self.find_all(model, **filters)), None)

    def find_all(
        self,
        model: type[Any],
        *,
        order_by: tuple[str, ...] = (),
        for_update: bool = False,
        **filters: object,
    ) -> list[Any]:
        del for_update
        rows = [
            row
            for row in self.rows.get(model, [])
            if all(getattr(row, key, None) == value for key, value in filters.items())
        ]
        if order_by:
            rows.sort(key=lambda row: tuple(str(getattr(row, key, "")) for key in order_by))
        return rows

    def consume_render_publication_context(self, **kwargs: object) -> None:
        del kwargs
        raise AssertionError("not used by T2 settings")


def novel(novel_id: UUID = NOVEL_ID) -> Novel:
    return Novel(
        id=novel_id,
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        title="测试作品",
    )


def character(
    character_id: UUID = CHARACTER_ID,
    *,
    novel_id: UUID = NOVEL_ID,
    lifecycle_state: str = "active",
) -> NovelCharacter:
    return NovelCharacter(
        id=character_id,
        novel_id=novel_id,
        name="林岚",
        role_type="protagonist",
        description="",
        details={},
        lifecycle_state=lifecycle_state,
        position=0,
        version=1,
    )


def enabled_capabilities(
    *keys: wire.CapabilityKey,
) -> wire.NarrationCapabilities:
    enabled = set(keys)
    return wire.NarrationCapabilities(
        items=[
            wire.FeatureCapability(
                key=item.key,
                state=wire.CapabilityState.ENABLED,
                visible=True,
                actionable=True,
                reason_code=None,
                required_gate=None,
            )
            if item.key in enabled
            else item.model_copy(deep=True)
            for item in wire.t2_hold_capabilities().items
        ]
    )


def authorized_backend(
    store: MemoryStore,
    **kwargs: object,
) -> NarrationSettingsBackend:
    return NarrationSettingsBackend(
        store,
        authorization=FIXED_LOCAL_OWNER_NARRATION_AUTHORIZATION,
        **kwargs,
    )


def consent_request(
    *,
    notice_version: str = "narration-cloud-consent/1",
    provider_id: str | None = "writer-agent",
    model_id: str | None = "selected-model",
) -> wire.CreateNarrationCloudConsentRequest:
    return wire.CreateNarrationCloudConsentRequest(
        notice_version=notice_version,
        data_scope="uncertain_segments_with_minimal_context",
        provider_id=provider_id,
        model_id=model_id,
        confirmed=True,
    )


def voice_rows() -> tuple[VoiceProfile, VoiceProfileVersion, VoiceRightsRecord]:
    rights = VoiceRightsRecord(
        id=RIGHTS_ID,
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        novel_id=NOVEL_ID,
        source_kind="user_upload",
        source_identifier="private-reference",
        notice_version="voice-rights/1",
        purpose="private_novel_narration",
        commercial_use=False,
        redistribution=False,
        voice_cloning=True,
        subject_consent_reference="consent-evidence",
        confirmed_actor="local-owner",
        confirmed_at=NOW,
        expires_at=None,
        risk_flags_json=[],
    )
    profile = VoiceProfile(
        id=PROFILE_ID,
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        novel_id=NOVEL_ID,
        name="林岚专属",
        current_version_id=VOICE_VERSION_ID,
        status="active",
        version=1,
        archived_at=None,
        created_at=NOW,
        updated_at=NOW,
    )
    version = VoiceProfileVersion(
        id=VOICE_VERSION_ID,
        profile_id=PROFILE_ID,
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        version_number=1,
        source_type="uploaded",
        state="locked",
        reference_asset_id=uuid4(),
        rights_record_id=RIGHTS_ID,
        language="zh-CN",
        parameters_json={},
        fingerprint="a" * 64,
        quality_state="accepted",
        locked_actor="local-owner",
        locked_at=NOW,
        created_at=NOW,
    )
    return profile, version, rights


def settings_request(
    *,
    expected_version: int = 0,
    analysis_mode: wire.AnalysisMode = wire.AnalysisMode.LOCAL_RULES_ONLY,
) -> wire.UpdateNarrationSettingsRequest:
    values = default_narration_settings_values().model_copy(
        update={"analysis_mode": analysis_mode},
        deep=True,
    )
    return wire.UpdateNarrationSettingsRequest(
        expected_version=expected_version,
        values=values,
    )


def test_default_settings_and_corrupt_persisted_identity_fail_closed() -> None:
    store = MemoryStore(novel())
    resource = get_narration_settings(store, novel_id=NOVEL_ID)
    assert resource.exists is False
    assert resource.version == 0
    assert resource.values == default_narration_settings_values()

    row = NovelNarrationSettings(
        id=uuid4(),
        novel_id=NOVEL_ID,
        narrator_profile_id=None,
        narrator_version_id=VOICE_VERSION_ID,
        script_review_policy="blockers_only",
        analysis_mode="local_rules_only",
        settings_json={},
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    store.add(row)
    with pytest.raises(InvalidNarrationState):
        get_narration_settings(store, novel_id=NOVEL_ID)


def test_hold_overview_is_truthful_and_all_mutation_stays_blocked() -> None:
    store = MemoryStore(novel(), character())
    backend = authorized_backend(
        store,
        runtime_status_provider=lambda: {
            "technical_enabled": True,
            "lifecycle_status": "ready",
            "sidecar_reachable": True,
            "model_ready": True,
            "product_visible": True,
            "protocol_version": "moss-tts-sidecar/1.1",
            "model_fingerprint_sha256": "b" * 64,
        },
    )
    overview = backend.dispatch(
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.GET_OVERVIEW,
            novel_id=NOVEL_ID,
        )
    )
    assert isinstance(overview, wire.NarrationOverviewResponse)
    assert overview.runtime.lifecycle_status is wire.RuntimeLifecycleStatus.READY
    assert overview.runtime.product_visible is False
    assert overview.capabilities.item(wire.CapabilityKey.NARRATION_PRODUCT).actionable is False
    assert overview.authorization.can_configure is True
    assert overview.authorization.cloud_consent.state is wire.CloudConsentState.NOT_GRANTED
    assert overview.coverage.character_count == 1
    assert overview.coverage.generic_ready_slot_count == 0
    assert overview.cache.cleanup_capability.reason_code == "CACHE_RUNTIME_UNAVAILABLE"
    assert {item.source_type for item in overview.voice_sources} == set(wire.VoiceSourceType)
    assert all(not item.available for item in overview.voice_sources)

    with pytest.raises(NarrationApiFault) as blocked:
        backend.dispatch(
            NarrationSettingsApiCommand(
                operation=NarrationSettingsOperation.PUT_SETTINGS,
                novel_id=NOVEL_ID,
                payload=settings_request(),
            )
        )
    assert blocked.value.code is wire.NarrationErrorCode.CAPABILITY_DISABLED


def test_t4_overview_product_visibility_matches_the_complete_release_chain() -> None:
    store = MemoryStore(novel(), character())
    ready_snapshot = {
        "technical_enabled": True,
        "lifecycle_status": "ready",
        "sidecar_reachable": True,
        "model_ready": True,
        "product_visible": True,
        "protocol_version": "moss-tts-sidecar/1.1",
        "model_fingerprint_sha256": "b" * 64,
    }
    backend = authorized_backend(
        store,
        capabilities=t4_product_capabilities(),
        runtime_status_provider=lambda: ready_snapshot,
    )

    overview = backend.dispatch(
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.GET_OVERVIEW,
            novel_id=NOVEL_ID,
        )
    )
    assert isinstance(overview, wire.NarrationOverviewResponse)
    assert overview.runtime.product_visible is True

    gated = overview.model_copy(update={"capabilities": t2_settings_capabilities()})
    with pytest.raises(ValueError, match="T4 product chain is gated"):
        gated.validate_overview_scope()


def test_t2_overview_does_not_propagate_a_product_visible_runtime_snapshot() -> None:
    store = MemoryStore(novel(), character())
    backend = authorized_backend(
        store,
        capabilities=t2_settings_capabilities(),
        runtime_status_provider=lambda: {
            "technical_enabled": True,
            "lifecycle_status": "ready",
            "sidecar_reachable": True,
            "model_ready": True,
            "product_visible": True,
            "protocol_version": "moss-tts-sidecar/1.1",
            "model_fingerprint_sha256": "b" * 64,
        },
    )

    overview = backend.dispatch(
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.GET_OVERVIEW,
            novel_id=NOVEL_ID,
        )
    )
    assert isinstance(overview, wire.NarrationOverviewResponse)
    assert overview.runtime.lifecycle_status is wire.RuntimeLifecycleStatus.READY
    assert overview.runtime.product_visible is False
    assert store.find_all(NovelNarrationSettings) == []


def test_authorization_defaults_to_deny_and_blocks_all_operations_before_store_access() -> None:
    class NoAccessStore(MemoryStore):
        def get(self, *args: object, **kwargs: object) -> object:
            del args, kwargs
            raise AssertionError("authorization denial must happen before store access")

        def find_one(self, *args: object, **kwargs: object) -> object:
            del args, kwargs
            raise AssertionError("authorization denial must happen before store access")

        def find_all(self, *args: object, **kwargs: object) -> list[object]:
            del args, kwargs
            raise AssertionError("authorization denial must happen before store access")

        def add(self, row: object) -> None:
            del row
            raise AssertionError("authorization denial must happen before store access")

        def flush(self) -> None:
            raise AssertionError("authorization denial must happen before store access")

    backend = NarrationSettingsBackend(NoAccessStore())
    for operation in NarrationSettingsOperation:
        with pytest.raises(NarrationApiFault) as denied:
            backend.dispatch(NarrationSettingsApiCommand(operation=operation))
        assert denied.value.code is wire.NarrationErrorCode.SCOPE_VIOLATION


def test_partial_authorization_is_projected_and_each_mutation_class_fails_closed() -> None:
    read_only = NarrationRequestAuthorization(can_read=True)
    store = MemoryStore(novel())
    backend = NarrationSettingsBackend(store, authorization=read_only)
    overview = backend.dispatch(
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.GET_OVERVIEW,
            novel_id=NOVEL_ID,
        )
    )
    assert overview.authorization.model_dump(exclude={"cloud_consent"}) == {
        "mode": "fixed_local_owner_workspace",
        "can_read": True,
        "can_configure": False,
        "can_manage_voice_assets": False,
        "can_confirm_voice_rights": False,
    }

    denied_commands = (
        NarrationSettingsApiCommand(operation=NarrationSettingsOperation.PUT_SETTINGS),
        NarrationSettingsApiCommand(operation=NarrationSettingsOperation.CREATE_VOICE_PROFILE),
        NarrationSettingsApiCommand(operation=NarrationSettingsOperation.CREATE_UPLOADED_VOICE_VERSION),
    )
    for command in denied_commands:
        with pytest.raises(NarrationApiFault) as denied:
            backend.dispatch(command)
        assert denied.value.code is wire.NarrationErrorCode.SCOPE_VIOLATION


def test_consent_revoke_requires_configure_permission_but_not_cloud_capability() -> None:
    row = NarrationCloudConsentRow(
        id=uuid4(),
        novel_id=NOVEL_ID,
        purpose="narration_speaker_analysis",
        data_scope="uncertain_segments_with_minimal_context",
        notice_version="narration-cloud-consent/1",
        provider_id=None,
        model_id=None,
        confirmed_actor="local-owner",
        confirmed_at=NOW,
        revoked_at=None,
    )
    store = MemoryStore(novel(), row)
    read_only_backend = NarrationSettingsBackend(
        store,
        authorization=NarrationRequestAuthorization(can_read=True),
    )
    command = NarrationSettingsApiCommand(
        operation=NarrationSettingsOperation.REVOKE_CLOUD_CONSENT,
        novel_id=NOVEL_ID,
        payload=wire.RevokeNarrationCloudConsentRequest(
            consent_id=row.id,
            expected_version=1,
        ),
    )
    with pytest.raises(NarrationApiFault) as denied:
        read_only_backend.dispatch(command)
    assert denied.value.code is wire.NarrationErrorCode.SCOPE_VIOLATION
    assert row.revoked_at is None

    configure_backend = NarrationSettingsBackend(
        store,
        authorization=NarrationRequestAuthorization(
            can_read=True,
            can_configure=True,
        ),
    )
    revoked = configure_backend.dispatch(command)
    assert revoked.state is wire.CloudConsentState.REVOKED


def test_voice_profile_lock_requires_asset_and_rights_permissions_before_store_access() -> None:
    class NoStoreAccess(MemoryStore):
        def get(self, *args: object, **kwargs: object) -> object:
            del args, kwargs
            raise AssertionError("rights denial must happen before store access")

        def find_one(self, *args: object, **kwargs: object) -> object:
            del args, kwargs
            raise AssertionError("rights denial must happen before store access")

        def find_all(self, *args: object, **kwargs: object) -> list[object]:
            del args, kwargs
            raise AssertionError("rights denial must happen before store access")

    backend = NarrationSettingsBackend(
        NoStoreAccess(),
        authorization=NarrationRequestAuthorization(
            can_read=True,
            can_manage_voice_assets=True,
            can_confirm_voice_rights=False,
        ),
    )
    with pytest.raises(NarrationApiFault) as denied:
        backend.dispatch(
            NarrationSettingsApiCommand(
                operation=NarrationSettingsOperation.LOCK_VOICE_PROFILE,
                profile_id=PROFILE_ID,
                payload=wire.LockVoiceProfileRequest(
                    expected_profile_version=1,
                    version_id=VOICE_VERSION_ID,
                    quality_confirmed=True,
                ),
            )
        )
    assert denied.value.code is wire.NarrationErrorCode.SCOPE_VIOLATION


def test_settings_cas_noop_and_cloud_requires_active_consent() -> None:
    store = MemoryStore(novel())
    capabilities = enabled_capabilities(
        wire.CapabilityKey.NARRATION_PRODUCT,
        wire.CapabilityKey.READING_SETTINGS,
        wire.CapabilityKey.CLOUD_ASSISTED_ANALYSIS,
    )
    backend = authorized_backend(store, capabilities=capabilities)
    local = backend.dispatch(
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.PUT_SETTINGS,
            novel_id=NOVEL_ID,
            payload=settings_request(),
        )
    )
    assert isinstance(local, wire.NarrationSettingsResource)
    assert local.exists and local.version == 1
    assert store.flush_count == 1
    flushes = store.flush_count

    same = backend.dispatch(
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.PUT_SETTINGS,
            novel_id=NOVEL_ID,
            payload=settings_request(expected_version=1),
        )
    )
    assert same.version == 1
    assert store.flush_count == flushes

    with pytest.raises(NarrationApiFault) as missing:
        backend.dispatch(
            NarrationSettingsApiCommand(
                operation=NarrationSettingsOperation.PUT_SETTINGS,
                novel_id=NOVEL_ID,
                payload=settings_request(
                    expected_version=1,
                    analysis_mode=wire.AnalysisMode.CLOUD_ASSISTED,
                ),
            )
        )
    assert missing.value.code is wire.NarrationErrorCode.CLOUD_CONSENT_REQUIRED

    consent = backend.dispatch(
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.CREATE_CLOUD_CONSENT,
            novel_id=NOVEL_ID,
            payload=consent_request(),
            idempotency_key="cloud-key-0001",
        )
    )
    assert consent.state is wire.CloudConsentState.ACTIVE
    cloud = backend.dispatch(
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.PUT_SETTINGS,
            novel_id=NOVEL_ID,
            payload=settings_request(
                expected_version=1,
                analysis_mode=wire.AnalysisMode.CLOUD_ASSISTED,
            ),
        )
    )
    assert cloud.version == 2
    assert cloud.values.analysis_mode is wire.AnalysisMode.CLOUD_ASSISTED
    with pytest.raises(NarrationCasConflict):
        backend.dispatch(
            NarrationSettingsApiCommand(
                operation=NarrationSettingsOperation.PUT_SETTINGS,
                novel_id=NOVEL_ID,
                payload=settings_request(expected_version=1),
            )
        )


def test_t2_gate_opens_only_the_proven_settings_capabilities() -> None:
    baseline = wire.t2_hold_capabilities()
    released = t2_settings_capabilities()

    for key in wire.CapabilityKey:
        item = released.item(key)
        if key in {
            wire.CapabilityKey.NARRATION_PRODUCT,
            wire.CapabilityKey.READING_SETTINGS,
        }:
            assert item.state is wire.CapabilityState.ENABLED
            assert item.visible and item.actionable
            assert item.reason_code is None and item.required_gate is None
        else:
            assert item == baseline.item(key)


def test_t4_product_gate_opens_only_the_core_playback_chain() -> None:
    baseline = wire.t2_hold_capabilities()
    released = t4_product_capabilities()
    enabled = {
        wire.CapabilityKey.NARRATION_PRODUCT,
        wire.CapabilityKey.READING_SETTINGS,
        wire.CapabilityKey.NARRATION_SYNTHESIS,
        wire.CapabilityKey.PRODUCT_PLAYER,
        wire.CapabilityKey.EDITOR_PRODUCTION,
        wire.CapabilityKey.AUTOMATIC_SPEAKER_DETECTION,
        wire.CapabilityKey.CACHE_CLEANUP,
    }

    for key in wire.CapabilityKey:
        item = released.item(key)
        if key in enabled:
            assert item.state is wire.CapabilityState.ENABLED
            assert item.visible and item.actionable
            assert item.reason_code is None and item.required_gate is None
        else:
            assert item == baseline.item(key)


def test_reference_clone_has_an_independent_exact_release_gate() -> None:
    baseline = t4_product_capabilities()
    released = t4_product_capabilities(reference_clone_released=True)

    for key in wire.CapabilityKey:
        item = released.item(key)
        if key in {
            *wire.T4_PRODUCT_CAPABILITY_KEYS,
            wire.CapabilityKey.REFERENCE_CLONE,
            wire.CapabilityKey.VOICE_PREVIEW,
        }:
            assert item.state is wire.CapabilityState.ENABLED
            assert item.visible and item.actionable
        else:
            assert item == baseline.item(key)
    assert baseline.item(wire.CapabilityKey.REFERENCE_CLONE).state is wire.CapabilityState.HOLD
    assert baseline.item(
        wire.CapabilityKey.VOICE_PREVIEW
    ).state is not wire.CapabilityState.ENABLED

    with pytest.raises(TypeError, match="exact boolean"):
        t4_product_capabilities(reference_clone_released=1)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "operation",
    [
        NarrationSettingsOperation.CREATE_CLOUD_CONSENT,
        NarrationSettingsOperation.CREATE_PRESET_VOICE_VERSION,
        NarrationSettingsOperation.CREATE_UPLOADED_VOICE_VERSION,
        NarrationSettingsOperation.CREATE_VOICE_PREVIEW,
        NarrationSettingsOperation.PUT_GENERIC_VOICE_POOL,
        NarrationSettingsOperation.PUT_CASTING_RULES,
        NarrationSettingsOperation.PREVIEW_CACHE_CLEANUP,
        NarrationSettingsOperation.EXECUTE_CACHE_CLEANUP,
    ],
)
def test_t2_gate_persistent_no_go_operations_stop_before_store_access(
    operation: NarrationSettingsOperation,
) -> None:
    class NoStoreAccess(MemoryStore):
        def get(self, *args: object, **kwargs: object) -> object:
            del args, kwargs
            raise AssertionError("held operation must not access the store")

        def find_one(self, *args: object, **kwargs: object) -> object:
            del args, kwargs
            raise AssertionError("held operation must not access the store")

        def find_all(self, *args: object, **kwargs: object) -> list[object]:
            del args, kwargs
            raise AssertionError("held operation must not access the store")

    backend = NarrationSettingsBackend(
        NoStoreAccess(),
        authorization=FIXED_LOCAL_OWNER_NARRATION_AUTHORIZATION,
        capabilities=t2_settings_capabilities(),
    )
    with pytest.raises(NarrationApiFault) as held:
        backend.dispatch(NarrationSettingsApiCommand(operation=operation))
    assert held.value.code is wire.NarrationErrorCode.CAPABILITY_DISABLED


def test_cloud_consent_idempotency_exact_revoke_and_regrant() -> None:
    store = MemoryStore(novel())
    first = create_cloud_consent(
        store,
        novel_id=NOVEL_ID,
        request=consent_request(),
        idempotency_key="cloud-key-0001",
    )
    replay = create_cloud_consent(
        store,
        novel_id=NOVEL_ID,
        request=consent_request(),
        idempotency_key="cloud-key-0001",
    )
    assert replay.consent_id == first.consent_id
    assert len(store.find_all(NarrationCloudConsentRow)) == 1
    with pytest.raises(IdempotencyConflict):
        create_cloud_consent(
            store,
            novel_id=NOVEL_ID,
            request=consent_request(model_id="another-selected-model"),
            idempotency_key="cloud-key-0001",
        )
    with pytest.raises(NarrationServiceError, match="notice version is unsupported"):
        create_cloud_consent(
            store,
            novel_id=NOVEL_ID,
            request=consent_request(notice_version="narration-cloud-consent/2"),
            idempotency_key="cloud-key-unsupported",
        )
    with pytest.raises(InvalidNarrationState):
        create_cloud_consent(
            store,
            novel_id=NOVEL_ID,
            request=consent_request(),
            idempotency_key="cloud-key-0002",
        )

    revoked = revoke_cloud_consent(
        store,
        novel_id=NOVEL_ID,
        request=wire.RevokeNarrationCloudConsentRequest(
            consent_id=first.consent_id,
            expected_version=1,
        ),
    )
    assert revoked.state is wire.CloudConsentState.REVOKED
    assert revoked.version == 2
    regranted = create_cloud_consent(
        store,
        novel_id=NOVEL_ID,
        request=consent_request(),
        idempotency_key="cloud-key-0002",
    )
    assert regranted.state is wire.CloudConsentState.ACTIVE

    with pytest.raises(NarrationCasConflict):
        revoke_cloud_consent(
            store,
            novel_id=NOVEL_ID,
            request=wire.RevokeNarrationCloudConsentRequest(
                consent_id=first.consent_id,
                expected_version=1,
            ),
        )
    delayed_replay = revoke_cloud_consent(
        store,
        novel_id=NOVEL_ID,
        request=wire.RevokeNarrationCloudConsentRequest(
            consent_id=first.consent_id,
            expected_version=2,
        ),
    )
    assert delayed_replay.consent_id == first.consent_id
    assert delayed_replay.state is wire.CloudConsentState.REVOKED
    current = create_cloud_consent(
        store,
        novel_id=NOVEL_ID,
        request=consent_request(),
        idempotency_key="cloud-key-0002",
    )
    assert current.consent_id == regranted.consent_id
    assert current.state is wire.CloudConsentState.ACTIVE


def test_revoke_remains_available_when_cloud_capability_is_disabled() -> None:
    store = MemoryStore(novel())
    row = NarrationCloudConsentRow(
        id=uuid4(),
        novel_id=NOVEL_ID,
        purpose="narration_speaker_analysis",
        data_scope="uncertain_segments_with_minimal_context",
        notice_version="narration-cloud-consent/1",
        provider_id=None,
        model_id=None,
        confirmed_actor="local-owner",
        confirmed_at=NOW,
        revoked_at=None,
    )
    store.add(row)
    backend = authorized_backend(store)
    result = backend.dispatch(
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.REVOKE_CLOUD_CONSENT,
            novel_id=NOVEL_ID,
            payload=wire.RevokeNarrationCloudConsentRequest(
                consent_id=row.id,
                expected_version=1,
            ),
        )
    )
    assert result.state is wire.CloudConsentState.REVOKED


@pytest.mark.parametrize(
    ("notice_version", "revoked_at", "expected_code"),
    [
        (
            "narration-cloud-consent/1",
            NOW + timedelta(minutes=1),
            wire.NarrationErrorCode.CLOUD_CONSENT_REVOKED,
        ),
        (
            "narration-cloud-consent/0",
            None,
            wire.NarrationErrorCode.CLOUD_CONSENT_REQUIRED,
        ),
    ],
)
def test_cloud_mode_distinguishes_revoked_and_stale_notice_consent(
    notice_version: str,
    revoked_at: datetime | None,
    expected_code: wire.NarrationErrorCode,
) -> None:
    store = MemoryStore(
        novel(),
        NarrationCloudConsentRow(
            id=uuid4(),
            novel_id=NOVEL_ID,
            purpose="narration_speaker_analysis",
            data_scope="uncertain_segments_with_minimal_context",
            notice_version=notice_version,
            provider_id=None,
            model_id=None,
            confirmed_actor="local-owner",
            confirmed_at=NOW,
            revoked_at=revoked_at,
        ),
    )
    backend = authorized_backend(
        store,
        capabilities=enabled_capabilities(
            wire.CapabilityKey.NARRATION_PRODUCT,
            wire.CapabilityKey.READING_SETTINGS,
            wire.CapabilityKey.CLOUD_ASSISTED_ANALYSIS,
        ),
    )
    with pytest.raises(NarrationApiFault) as blocked:
        backend.dispatch(
            NarrationSettingsApiCommand(
                operation=NarrationSettingsOperation.PUT_SETTINGS,
                novel_id=NOVEL_ID,
                payload=settings_request(analysis_mode=wire.AnalysisMode.CLOUD_ASSISTED),
            )
        )
    assert blocked.value.code is expected_code


def test_cloud_consent_projection_rejects_actor_and_provider_identity_drift() -> None:
    row = NarrationCloudConsentRow(
        id=uuid4(),
        novel_id=NOVEL_ID,
        purpose="narration_speaker_analysis",
        data_scope="uncertain_segments_with_minimal_context",
        notice_version="narration-cloud-consent/1",
        provider_id="writer-agent",
        model_id=None,
        confirmed_actor="foreign-actor",
        confirmed_at=NOW,
        revoked_at=None,
    )
    with pytest.raises(InvalidNarrationState, match="actor"):
        cloud_consent_resource(row)
    row.confirmed_actor = "local-owner"
    with pytest.raises(InvalidNarrationState, match="provider/model"):
        cloud_consent_resource(row)


def test_scope_override_complete_replacement_noop_delete_and_scope_fence() -> None:
    volume_id = uuid4()
    chapter_id = uuid4()
    other_volume_id = uuid4()
    store = MemoryStore(
        novel(),
        novel(OTHER_NOVEL_ID),
        Volume(id=volume_id, novel_id=NOVEL_ID, title="第一卷", position=0),
        Document(
            id=chapter_id,
            novel_id=NOVEL_ID,
            kind="chapter",
            title="第一章",
            position=0,
        ),
        Volume(id=other_volume_id, novel_id=OTHER_NOVEL_ID, title="外卷", position=0),
    )
    backend = authorized_backend(
        store,
        capabilities=enabled_capabilities(
            wire.CapabilityKey.NARRATION_PRODUCT,
            wire.CapabilityKey.READING_SETTINGS,
        ),
    )
    values = wire.NarrationScopeOverrideValues(
        narrator=None,
        language="zh-CN",
        text_rules=None,
        timing=wire.NarrationTimingSettings(
            sentence_gap_ms=250,
            paragraph_gap_ms=500,
            section_gap_ms=900,
        ),
    )
    create_request = wire.PutNarrationScopeOverrideRequest(
        expected_version=0,
        enabled=True,
        overrides=values,
    )
    created = backend.dispatch(
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.PUT_SCOPE_OVERRIDE,
            novel_id=NOVEL_ID,
            scope_kind=wire.NarrationScopeKind.VOLUME,
            scope_id=volume_id,
            payload=create_request,
        )
    )
    assert created.enabled and created.version == 1
    flushes = store.flush_count
    same = backend.dispatch(
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.PUT_SCOPE_OVERRIDE,
            novel_id=NOVEL_ID,
            scope_kind=wire.NarrationScopeKind.VOLUME,
            scope_id=volume_id,
            payload=wire.PutNarrationScopeOverrideRequest(
                expected_version=1,
                enabled=True,
                overrides=values,
            ),
        )
    )
    assert same.version == 1 and store.flush_count == flushes

    disabled = backend.dispatch(
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.PUT_SCOPE_OVERRIDE,
            novel_id=NOVEL_ID,
            scope_kind=wire.NarrationScopeKind.VOLUME,
            scope_id=volume_id,
            payload=wire.PutNarrationScopeOverrideRequest(
                expected_version=1,
                enabled=False,
                overrides=wire.NarrationScopeOverrideValues(
                    narrator=None,
                    language=None,
                    text_rules=None,
                    timing=None,
                ),
            ),
        )
    )
    assert not disabled.enabled and disabled.version == 0
    assert store.find_all(NarrationScopeOverride) == []

    with pytest.raises(NarrationScopeMismatch):
        backend.dispatch(
            NarrationSettingsApiCommand(
                operation=NarrationSettingsOperation.PUT_SCOPE_OVERRIDE,
                novel_id=NOVEL_ID,
                scope_kind=wire.NarrationScopeKind.VOLUME,
                scope_id=other_volume_id,
                payload=create_request,
            )
        )


def test_character_binding_cas_rights_history_impact_and_unset_deletes_only_binding() -> None:
    document_id = uuid4()
    script_id = uuid4()
    script_version_id = uuid4()
    segment_id = uuid4()
    edition_id = uuid4()
    profile, version, rights = voice_rows()
    store = MemoryStore(
        novel(),
        character(),
        profile,
        version,
        rights,
        NarrationScript(
            id=script_id,
            novel_id=NOVEL_ID,
            document_id=document_id,
            revision_id=uuid4(),
            content_hash="c" * 64,
            version=1,
            created_at=NOW,
        ),
        NarrationScriptVersion(
            id=script_version_id,
            script_id=script_id,
            version_number=1,
            state="approved",
            blocker_count=0,
            warning_count=0,
        ),
        NarrationSegment(
            id=segment_id,
            script_version_id=script_version_id,
            character_id=CHARACTER_ID,
            speaker_kind="character",
        ),
        NarrationEdition(
            id=edition_id,
            novel_id=NOVEL_ID,
            document_id=document_id,
            script_version_id=script_version_id,
            state="ready",
        ),
    )
    backend = authorized_backend(
        store,
        capabilities=enabled_capabilities(
            wire.CapabilityKey.NARRATION_PRODUCT,
            wire.CapabilityKey.READING_SETTINGS,
        ),
    )
    empty = backend.dispatch(
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.GET_CHARACTER_VOICE_BINDING,
            novel_id=NOVEL_ID,
            character_id=CHARACTER_ID,
        )
    )
    assert empty.binding_policy is wire.CharacterVoiceBindingPolicy.UNSET
    assert empty.impact.model_dump() == {
        "affected_chapter_count": 1,
        "affected_segment_count": 1,
        "historical_edition_count": 1,
        "regeneration_required": True,
    }
    configured = backend.dispatch(
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.PUT_CHARACTER_VOICE_BINDING,
            novel_id=NOVEL_ID,
            character_id=CHARACTER_ID,
            payload=wire.PutCharacterVoiceBindingRequest(
                expected_version=0,
                binding_policy=wire.CharacterVoiceBindingPolicy.DEDICATED,
                profile_id=PROFILE_ID,
                version_id=VOICE_VERSION_ID,
                language="zh-CN",
            ),
        )
    )
    assert configured.version == 1
    assert configured.impact.historical_edition_count == 1
    unchanged_edition = store.get(NarrationEdition, edition_id)
    flushes = store.flush_count
    replay = backend.dispatch(
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.PUT_CHARACTER_VOICE_BINDING,
            novel_id=NOVEL_ID,
            character_id=CHARACTER_ID,
            payload=wire.PutCharacterVoiceBindingRequest(
                expected_version=1,
                binding_policy=wire.CharacterVoiceBindingPolicy.DEDICATED,
                profile_id=PROFILE_ID,
                version_id=VOICE_VERSION_ID,
                language="zh-CN",
            ),
        )
    )
    assert replay.version == 1 and store.flush_count == flushes

    cleared = backend.dispatch(
        NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.PUT_CHARACTER_VOICE_BINDING,
            novel_id=NOVEL_ID,
            character_id=CHARACTER_ID,
            payload=wire.PutCharacterVoiceBindingRequest(
                expected_version=1,
                binding_policy=wire.CharacterVoiceBindingPolicy.UNSET,
                profile_id=None,
                version_id=None,
                language="zh-CN",
            ),
        )
    )
    assert cleared.version == 0
    assert store.find_all(CharacterVoiceBinding) == []
    assert store.get(NarrationEdition, edition_id) is unchanged_edition


def test_revoked_voice_blocks_binding_without_changing_history() -> None:
    profile, version, rights = voice_rows()
    event = VoiceRightsEvent(
        id=uuid4(),
        rights_record_id=RIGHTS_ID,
        event_key="revoke-1",
        event_type="revoked",
        actor="local-owner",
        occurred_at=NOW + timedelta(minutes=1),
    )
    store = MemoryStore(novel(), character(), profile, version, rights, event)
    backend = authorized_backend(
        store,
        capabilities=enabled_capabilities(
            wire.CapabilityKey.NARRATION_PRODUCT,
            wire.CapabilityKey.READING_SETTINGS,
        ),
    )
    with pytest.raises(Exception) as blocked:
        backend.dispatch(
            NarrationSettingsApiCommand(
                operation=NarrationSettingsOperation.PUT_CHARACTER_VOICE_BINDING,
                novel_id=NOVEL_ID,
                character_id=CHARACTER_ID,
                payload=wire.PutCharacterVoiceBindingRequest(
                    expected_version=0,
                    binding_policy=wire.CharacterVoiceBindingPolicy.DEDICATED,
                    profile_id=PROFILE_ID,
                    version_id=VOICE_VERSION_ID,
                    language="zh-CN",
                ),
            )
        )
    assert blocked.type.__name__ == "VoiceRightsUnavailable"
    assert store.find_all(CharacterVoiceBinding) == []


def test_overview_coverage_counts_only_currently_usable_character_voices() -> None:
    profile, version, rights = voice_rows()
    binding = CharacterVoiceBinding(
        id=uuid4(),
        novel_id=NOVEL_ID,
        character_id=CHARACTER_ID,
        profile_id=PROFILE_ID,
        voice_version_id=VOICE_VERSION_ID,
        binding_policy="dedicated",
        language="zh-CN",
        parameters_json={},
        version=1,
        updated_at=NOW,
    )
    store = MemoryStore(novel(), character(), profile, version, rights, binding)

    ready = narration_coverage(store, novel_id=NOVEL_ID, generic_ready_slot_count=0)
    assert ready.configured_character_count == 1
    assert ready.locked_character_voice_count == 1

    store.add(VoiceRightsEvent(
        id=uuid4(),
        rights_record_id=RIGHTS_ID,
        event_key="coverage-revoke-1",
        event_type="revoked",
        actor="local-owner",
        occurred_at=NOW + timedelta(minutes=1),
    ))
    revoked = narration_coverage(store, novel_id=NOVEL_ID, generic_ready_slot_count=0)
    assert revoked.configured_character_count == 1
    assert revoked.locked_character_voice_count == 0


@pytest.mark.parametrize(
    ("snapshot", "expected", "reason"),
    [
        ({"lifecycle_status": ["ready"]}, "unavailable", "RUNTIME_STATUS_UNAVAILABLE"),
        (
            {
                "technical_enabled": True,
                "lifecycle_status": "ready",
                "sidecar_reachable": True,
                "model_ready": True,
                "protocol_version": "moss-tts-sidecar/1.1",
                "model_fingerprint_sha256": "bad",
            },
            "unavailable",
            "RUNTIME_READY_EVIDENCE_INVALID",
        ),
        (
            {
                "technical_enabled": True,
                "lifecycle_status": "ready",
                "sidecar_reachable": True,
                "model_ready": True,
                "protocol_version": "moss-tts-sidecar/1.1",
                "model_fingerprint_sha256": "d" * 64,
                "reason_code": ["SIDECAR_FAILED"],
            },
            "unavailable",
            "RUNTIME_READY_EVIDENCE_INVALID",
        ),
        (
            {
                "technical_enabled": True,
                "lifecycle_status": "ready",
                "sidecar_reachable": True,
                "model_ready": True,
                "model_fingerprint_sha256": "d" * 64,
            },
            "unavailable",
            "RUNTIME_PROTOCOL_MISMATCH",
        ),
        (
            {
                "technical_enabled": True,
                "lifecycle_status": "ready",
                "sidecar_reachable": True,
                "model_ready": True,
                "protocol_version": "moss-tts-sidecar/1.1",
                "model_fingerprint_sha256": "d" * 64,
                "reason_code": "SIDECAR_FAILED",
            },
            "unavailable",
            "RUNTIME_READY_EVIDENCE_INVALID",
        ),
        (
            {
                "technical_enabled": True,
                "lifecycle_status": "unavailable",
                "sidecar_reachable": True,
                "model_ready": True,
                "model_fingerprint_sha256": "d" * 64,
                "reason_code": "SIDECAR_FAILED",
            },
            "unavailable",
            "SIDECAR_FAILED",
        ),
        ({"lifecycle_status": "disabled"}, "disabled", "TTS_RUNTIME_DISABLED"),
    ],
)
def test_runtime_projection_is_secret_free_and_fail_closed(
    snapshot: dict[str, object],
    expected: str,
    reason: str,
) -> None:
    resource = narration_runtime_resource(snapshot)
    assert resource.lifecycle_status.value == expected
    assert resource.reason_code == reason
    assert resource.product_visible is False
    if expected != "ready":
        assert resource.model_fingerprint_sha256 is None
        assert resource.model_ready is False
        assert resource.sidecar_reachable is False


def test_runtime_projection_requires_both_release_and_ready_evidence_for_product() -> None:
    ready = {
        "technical_enabled": True,
        "lifecycle_status": "ready",
        "sidecar_reachable": True,
        "model_ready": True,
        "product_visible": True,
        "protocol_version": "moss-tts-sidecar/1.1",
        "model_fingerprint_sha256": "d" * 64,
    }

    assert narration_runtime_resource(ready).product_visible is False
    assert (
        narration_runtime_resource(ready, product_visible_allowed=True).product_visible
        is True
    )
    unavailable = {
        **ready,
        "lifecycle_status": "unavailable",
        "reason_code": "SIDECAR_FAILED",
    }
    assert (
        narration_runtime_resource(
            unavailable,
            product_visible_allowed=True,
        ).product_visible
        is False
    )


def test_dispatcher_owns_exact_30_operations_and_preserves_specific_holds() -> None:
    owned = (
        READING_PRIVACY_OPERATIONS
        | VoiceSettingsHandler.operations
        | PronunciationSettingsHandler.operations
        | {
            NarrationSettingsOperation.GET_GENERIC_VOICE_POOL,
            NarrationSettingsOperation.PUT_GENERIC_VOICE_POOL,
            NarrationSettingsOperation.GET_CASTING_RULES,
            NarrationSettingsOperation.PUT_CASTING_RULES,
        }
    )
    assert owned == set(NarrationSettingsOperation)
    assert len(owned) == 30

    store = MemoryStore(novel())
    blocked = authorized_backend(store)
    command = NarrationSettingsApiCommand(
        operation=NarrationSettingsOperation.CREATE_VOICE_PROFILE,
        novel_id=NOVEL_ID,
        payload=wire.CreateVoiceProfileRequest(novel_id=NOVEL_ID, name="旁白"),
        idempotency_key="profile-key-0001",
    )
    with pytest.raises(NarrationApiFault) as product_hold:
        blocked.dispatch(command)
    assert product_hold.value.code is wire.NarrationErrorCode.CAPABILITY_DISABLED
    assert product_hold.value.capability is wire.CapabilityKey.NARRATION_PRODUCT

    feature_only = authorized_backend(
        store,
        capabilities=enabled_capabilities(wire.CapabilityKey.READING_SETTINGS),
    )
    with pytest.raises(NarrationApiFault) as partial_gate:
        feature_only.dispatch(command)
    assert partial_gate.value.capability is wire.CapabilityKey.NARRATION_PRODUCT

    readable = authorized_backend(
        store,
        capabilities=enabled_capabilities(
            wire.CapabilityKey.NARRATION_PRODUCT,
            wire.CapabilityKey.READING_SETTINGS,
        ),
    )
    with pytest.raises(NarrationApiFault) as receipt_hold:
        readable.dispatch(command)
    assert receipt_hold.value.code is wire.NarrationErrorCode.STORAGE_UNAVAILABLE


def test_cache_cleanup_requires_both_global_and_runtime_gates() -> None:
    class CacheRuntime:
        def __init__(self, *, enabled: bool) -> None:
            self.enabled = enabled
            self.preview_calls = 0

        def preview(
            self,
            novel_id: UUID,
            request: wire.PreviewNarrationCacheCleanupRequest,
        ) -> wire.NarrationCacheCleanupPreview:
            self.preview_calls += 1
            if not self.enabled:
                raise CacheCleanupDisabled("nested cache gate is disabled")
            return wire.NarrationCacheCleanupPreview(
                novel_id=novel_id,
                snapshot_fingerprint=request.snapshot_fingerprint,
                cleanup_token="x" * 32,
                expires_at=NOW + timedelta(minutes=5),
                reclaimable_bytes=0,
                protected_asset_count=0,
                candidate_asset_count=0,
            )

    request = wire.PreviewNarrationCacheCleanupRequest(snapshot_fingerprint="c" * 64)
    command = NarrationSettingsApiCommand(
        operation=NarrationSettingsOperation.PREVIEW_CACHE_CLEANUP,
        novel_id=NOVEL_ID,
        payload=request,
    )

    assert (
        t2_settings_capabilities()
        .item(wire.CapabilityKey.CACHE_CLEANUP)
        .state
        is wire.CapabilityState.HOLD
    )
    assert (
        t4_product_capabilities()
        .item(wire.CapabilityKey.CACHE_CLEANUP)
        .state
        is wire.CapabilityState.ENABLED
    )

    product_hold_runtime = CacheRuntime(enabled=True)
    with pytest.raises(NarrationApiFault) as product_hold:
        authorized_backend(
            MemoryStore(novel()),
            cache_runtime=product_hold_runtime,
        ).dispatch(command)
    assert product_hold.value.capability is wire.CapabilityKey.NARRATION_PRODUCT
    assert product_hold_runtime.preview_calls == 0

    global_hold_runtime = CacheRuntime(enabled=True)
    with pytest.raises(NarrationApiFault) as global_hold:
        authorized_backend(
            MemoryStore(novel()),
            capabilities=enabled_capabilities(wire.CapabilityKey.NARRATION_PRODUCT),
            cache_runtime=global_hold_runtime,
        ).dispatch(command)
    assert global_hold.value.capability is wire.CapabilityKey.CACHE_CLEANUP
    assert global_hold_runtime.preview_calls == 0

    nested_hold_runtime = CacheRuntime(enabled=False)
    with pytest.raises(NarrationApiFault) as nested_hold:
        authorized_backend(
            MemoryStore(novel()),
            capabilities=enabled_capabilities(
                wire.CapabilityKey.NARRATION_PRODUCT,
                wire.CapabilityKey.CACHE_CLEANUP,
            ),
            cache_runtime=nested_hold_runtime,
        ).dispatch(command)
    assert nested_hold.value.capability is wire.CapabilityKey.CACHE_CLEANUP
    assert nested_hold_runtime.preview_calls == 1

    enabled_runtime = CacheRuntime(enabled=True)
    preview = authorized_backend(
        MemoryStore(novel()),
        capabilities=enabled_capabilities(
            wire.CapabilityKey.NARRATION_PRODUCT,
            wire.CapabilityKey.CACHE_CLEANUP,
        ),
        cache_runtime=enabled_runtime,
    ).dispatch(command)
    assert preview.snapshot_fingerprint == "c" * 64
    assert enabled_runtime.preview_calls == 1


class FakeSession:
    def __init__(self) -> None:
        self.active = False
        self.commits = 0
        self.rollbacks = 0

    def in_transaction(self) -> bool:
        return self.active

    def begin(self) -> "FakeSession":
        assert not self.active
        self.active = True
        return self

    def __enter__(self) -> "FakeSession":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        del exc, traceback
        self.active = False
        if exc_type is None:
            self.commits += 1
        else:
            self.rollbacks += 1
        return False


class CoreStub:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls = 0

    def dispatch(self, command: NarrationSettingsApiCommand) -> object:
        del command
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        return {"ok": True}


def test_transaction_adapter_commits_one_mutation_rolls_back_failure_and_skips_read_tx() -> None:
    session = FakeSession()
    core = CoreStub()
    backend = TransactionalNarrationSettingsBackend(session, core)  # type: ignore[arg-type]
    assert backend.dispatch(
        NarrationSettingsApiCommand(operation=NarrationSettingsOperation.PUT_SETTINGS)
    ) == {"ok": True}
    assert (session.commits, session.rollbacks) == (1, 0)
    backend.dispatch(
        NarrationSettingsApiCommand(operation=NarrationSettingsOperation.GET_SETTINGS)
    )
    assert (session.commits, session.rollbacks) == (1, 0)
    for operation in (
        NarrationSettingsOperation.CREATE_UPLOADED_VOICE_VERSION,
        NarrationSettingsOperation.CREATE_VOICE_PREVIEW,
        NarrationSettingsOperation.LOCK_VOICE_PROFILE,
    ):
        backend.dispatch(NarrationSettingsApiCommand(operation=operation))
    assert (session.commits, session.rollbacks) == (1, 0)

    failure_session = FakeSession()
    failing = TransactionalNarrationSettingsBackend(
        failure_session,
        CoreStub(failure=InvalidNarrationState("no write")),  # type: ignore[arg-type]
    )
    with pytest.raises(InvalidNarrationState):
        failing.dispatch(
            NarrationSettingsApiCommand(operation=NarrationSettingsOperation.PUT_SETTINGS)
        )
    assert (failure_session.commits, failure_session.rollbacks) == (0, 1)


def test_consent_projection_rejects_missing_confirmation_time() -> None:
    row = NarrationCloudConsentRow(
        id=uuid4(),
        novel_id=NOVEL_ID,
        purpose="narration_speaker_analysis",
        data_scope="uncertain_segments_with_minimal_context",
        notice_version="narration-cloud-consent/1",
        confirmed_actor="local-owner",
        confirmed_at=None,
        revoked_at=None,
    )
    with pytest.raises(InvalidNarrationState):
        cloud_consent_resource(row)
