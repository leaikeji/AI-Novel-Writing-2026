"""T2 reading settings, privacy, character binding, and aggregate dispatcher.

This module is the single T2 domain dispatcher behind the frozen HTTP facade.
It keeps product capability gates separate from technical runtime health, uses
the Novel row as the mutable settings/consent aggregate lock, and never calls
the Sidecar or a cloud model.  The SQLAlchemy adapter owns the short database
transaction for one command; external cache cleanup keeps its separately
fenced T1-E transaction protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Callable, Final, Mapping, Protocol, TypeVar
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models import (
    BackgroundJob,
    CharacterVoiceBinding,
    Document,
    NarrationCloudConsent as NarrationCloudConsentRow,
    NarrationEdition,
    NarrationScript,
    NarrationScriptVersion,
    NarrationSegment,
    NovelCharacter,
    NovelNarrationSettings,
    NarrationScopeOverride,
    VoiceProfile,
    VoiceProfileVersion,
    VoiceRightsEvent,
    VoiceRightsRecord,
    Volume,
)

from . import schemas as wire
from .contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID
from .pawapp_runtime import narration_runtime_status
from .pronunciations import (
    CacheRuntimeUnavailable,
    NarrationCacheRuntime,
    PronunciationSettingsHandler,
    UnavailableNarrationCacheRuntime,
)
from .services import (
    IdempotencyConflict,
    InvalidNarrationState,
    NarrationCasConflict,
    NarrationNotFound,
    NarrationScopeMismatch,
    NarrationServiceError,
    NarrationStore,
    SqlAlchemyNarrationStore,
    VoiceRightsUnavailable,
    canonical_sha256,
    require_local_novel,
    require_same_novel,
    require_usable_voice,
    utc_now,
    voice_activation_evidence_is_usable,
)
from .settings import NarrationSettingsUpdate, update_settings
from .settings_api import (
    NarrationApiFault,
    NarrationSettingsApiCommand,
    NarrationSettingsOperation,
)
from .voice_pool import GenericCastingUnavailable, VoicePoolHandlers
from .voices import (
    OfficialVoiceSelectionPort,
    VoiceProductPort,
    VoiceProfileCreationReceiptPort,
    VoiceSettingsHandler,
)


_PayloadModel = TypeVar("_PayloadModel", bound=BaseModel)
_IDEMPOTENCY_KEY: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
_SAFE_REASON: Final = re.compile(r"^[A-Z][A-Z0-9_]{0,95}$")
_BOUNDED_DECIMAL: Final = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,17})?$")
_CLOUD_PURPOSE: Final = "narration_speaker_analysis"
_CLOUD_DATA_SCOPE: Final = "uncertain_segments_with_minimal_context"
_CLOUD_NOTICE_VERSION: Final = "narration-cloud-consent/1"
_CONSENT_ACTOR: Final = "local-owner"
_RUNTIME_PROTOCOL_FALLBACK: Final = "moss-tts-sidecar/1.1"


READING_PRIVACY_OPERATIONS: Final[frozenset[NarrationSettingsOperation]] = frozenset(
    {
        NarrationSettingsOperation.GET_OVERVIEW,
        NarrationSettingsOperation.GET_SETTINGS,
        NarrationSettingsOperation.PUT_SETTINGS,
        NarrationSettingsOperation.PUT_PLAYBACK_PREFERENCES,
        NarrationSettingsOperation.LIST_SCOPE_OVERRIDES,
        NarrationSettingsOperation.PUT_SCOPE_OVERRIDE,
        NarrationSettingsOperation.CREATE_CLOUD_CONSENT,
        NarrationSettingsOperation.REVOKE_CLOUD_CONSENT,
        NarrationSettingsOperation.LIST_CHARACTER_VOICE_BINDINGS,
        NarrationSettingsOperation.GET_CHARACTER_VOICE_BINDING,
        NarrationSettingsOperation.PUT_CHARACTER_VOICE_BINDING,
    }
)


_MUTATION_CAPABILITY: Final[dict[NarrationSettingsOperation, wire.CapabilityKey]] = {
    NarrationSettingsOperation.LIST_OFFICIAL_PRESETS: wire.CapabilityKey.PRESET_VOICE_SOURCE,
    NarrationSettingsOperation.CREATE_OFFICIAL_VOICE_PREVIEW: wire.CapabilityKey.VOICE_PREVIEW,
    NarrationSettingsOperation.SELECT_OFFICIAL_VOICE: wire.CapabilityKey.PRESET_VOICE_SOURCE,
    NarrationSettingsOperation.PUT_SETTINGS: wire.CapabilityKey.READING_SETTINGS,
    NarrationSettingsOperation.PUT_PLAYBACK_PREFERENCES: wire.CapabilityKey.READING_SETTINGS,
    NarrationSettingsOperation.PUT_SCOPE_OVERRIDE: wire.CapabilityKey.READING_SETTINGS,
    NarrationSettingsOperation.CREATE_CLOUD_CONSENT: wire.CapabilityKey.CLOUD_ASSISTED_ANALYSIS,
    NarrationSettingsOperation.CREATE_VOICE_PROFILE: wire.CapabilityKey.READING_SETTINGS,
    NarrationSettingsOperation.PUT_VOICE_PROFILE: wire.CapabilityKey.READING_SETTINGS,
    NarrationSettingsOperation.ARCHIVE_VOICE_PROFILE: wire.CapabilityKey.READING_SETTINGS,
    NarrationSettingsOperation.CREATE_PRESET_VOICE_VERSION: wire.CapabilityKey.PRESET_VOICE_SOURCE,
    NarrationSettingsOperation.CREATE_UPLOADED_VOICE_VERSION: wire.CapabilityKey.REFERENCE_CLONE,
    NarrationSettingsOperation.CREATE_VOICE_PREVIEW: wire.CapabilityKey.VOICE_PREVIEW,
    NarrationSettingsOperation.LOCK_VOICE_PROFILE: wire.CapabilityKey.READING_SETTINGS,
    NarrationSettingsOperation.PUT_CHARACTER_VOICE_BINDING: wire.CapabilityKey.READING_SETTINGS,
    NarrationSettingsOperation.PUT_PRONUNCIATION_PROFILE: wire.CapabilityKey.READING_SETTINGS,
    NarrationSettingsOperation.PREVIEW_CACHE_CLEANUP: wire.CapabilityKey.CACHE_CLEANUP,
    NarrationSettingsOperation.EXECUTE_CACHE_CLEANUP: wire.CapabilityKey.CACHE_CLEANUP,
}


_TRANSACTIONAL_OPERATIONS: Final[frozenset[NarrationSettingsOperation]] = frozenset(
    operation
    for operation in NarrationSettingsOperation
    if operation.value.startswith(("put_", "create_", "archive_", "revoke_", "lock_"))
    and operation
    not in {
        # Product voice operations own their own short transactions because
        # normalization/publication and Nano work must never run while the
        # request-scoped settings transaction is open.
        NarrationSettingsOperation.CREATE_UPLOADED_VOICE_VERSION,
        NarrationSettingsOperation.CREATE_PRESET_VOICE_VERSION,
        NarrationSettingsOperation.CREATE_OFFICIAL_VOICE_PREVIEW,
        NarrationSettingsOperation.CREATE_VOICE_PREVIEW,
        NarrationSettingsOperation.LOCK_VOICE_PROFILE,
        NarrationSettingsOperation.SELECT_OFFICIAL_VOICE,
        NarrationSettingsOperation.PREVIEW_CACHE_CLEANUP,
        NarrationSettingsOperation.EXECUTE_CACHE_CLEANUP,
    }
)


@dataclass(frozen=True, slots=True)
class NarrationRequestAuthorization:
    """Trusted server-side decision for one narration API trust domain.

    The browser never supplies this object.  The default is deliberately deny-all;
    the PawApp integration must opt into the audited fixed-local-owner boundary or
    later replace it with a request-scoped host authorization adapter.
    """

    can_read: bool = False
    can_configure: bool = False
    can_manage_voice_assets: bool = False
    can_confirm_voice_rights: bool = False


DENY_NARRATION_AUTHORIZATION: Final = NarrationRequestAuthorization()
FIXED_LOCAL_OWNER_NARRATION_AUTHORIZATION: Final = NarrationRequestAuthorization(
    can_read=True,
    can_configure=True,
    can_manage_voice_assets=True,
    can_confirm_voice_rights=True,
)


def _released_capabilities(
    enabled: frozenset[wire.CapabilityKey],
) -> wire.NarrationCapabilities:
    baseline = wire.t2_hold_capabilities()
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
            for item in baseline.items
        ]
    )


def t2_settings_capabilities() -> wire.NarrationCapabilities:
    """Open only the product shell and settings proven by T2-GATE.

    Runtime synthesis, playback, voice sources, automatic casting, cloud analysis,
    VoiceGenerator, and cache cleanup retain their independently audited holds.
    Technical Sidecar health never changes this product matrix implicitly.
    """

    return _released_capabilities(
        frozenset(
            {
                wire.CapabilityKey.NARRATION_PRODUCT,
                wire.CapabilityKey.READING_SETTINGS,
            }
        )
    )


def t4_product_capabilities(
    *,
    reference_clone_released: bool = False,
    official_presets_released: bool = False,
) -> wire.NarrationCapabilities:
    """Expose only the core T4 chain after an explicit product release flag.

    The flag is owned by the PawApp integration and defaults to false.  Runtime
    health never calls this function or upgrades the matrix implicitly.  Voice
    sources, generic casting, cloud and VoiceGenerator keep their own independent
    holds.  Minimal cache cleanup is part of the finite T4 product chain, while
    its runtime-projected nested capability remains an independent fail-closed
    execution gate.
    """

    if type(reference_clone_released) is not bool:
        raise TypeError("reference_clone_released must be an exact boolean")
    if type(official_presets_released) is not bool:
        raise TypeError("official_presets_released must be an exact boolean")
    enabled = wire.T4_PRODUCT_CAPABILITY_KEYS
    if reference_clone_released:
        enabled = enabled | frozenset(
            {
                wire.CapabilityKey.REFERENCE_CLONE,
                wire.CapabilityKey.VOICE_PREVIEW,
            }
        )
    if official_presets_released:
        enabled = enabled | frozenset(
            {
                wire.CapabilityKey.PRESET_VOICE_SOURCE,
                wire.CapabilityKey.VOICE_PREVIEW,
            }
        )
    return _released_capabilities(enabled)


def _t4_product_is_released(capabilities: wire.NarrationCapabilities) -> bool:
    return all(
        (
            (item := capabilities.item(key)).state
            is wire.CapabilityState.ENABLED
        )
        and item.visible
        and item.actionable
        for key in wire.T4_PRODUCT_CAPABILITY_KEYS
    )


_READ_ONLY_OPERATIONS: Final[frozenset[NarrationSettingsOperation]] = frozenset(
    {
        NarrationSettingsOperation.GET_OVERVIEW,
        NarrationSettingsOperation.LIST_OFFICIAL_PRESETS,
        NarrationSettingsOperation.GET_SETTINGS,
        NarrationSettingsOperation.LIST_SCOPE_OVERRIDES,
        NarrationSettingsOperation.LIST_VOICE_PROFILES,
        NarrationSettingsOperation.GET_VOICE_PROFILE,
        NarrationSettingsOperation.GET_VOICE_PREVIEW,
        NarrationSettingsOperation.LIST_CHARACTER_VOICE_BINDINGS,
        NarrationSettingsOperation.GET_CHARACTER_VOICE_BINDING,
        NarrationSettingsOperation.GET_GENERIC_VOICE_POOL,
        NarrationSettingsOperation.GET_CASTING_RULES,
        NarrationSettingsOperation.GET_PRONUNCIATION_PROFILE,
        NarrationSettingsOperation.GET_CACHE_STATUS,
    }
)
_CONFIGURE_OPERATIONS: Final[frozenset[NarrationSettingsOperation]] = frozenset(
    {
        NarrationSettingsOperation.PUT_SETTINGS,
        NarrationSettingsOperation.PUT_PLAYBACK_PREFERENCES,
        NarrationSettingsOperation.PUT_SCOPE_OVERRIDE,
        NarrationSettingsOperation.CREATE_CLOUD_CONSENT,
        NarrationSettingsOperation.REVOKE_CLOUD_CONSENT,
        NarrationSettingsOperation.PUT_CHARACTER_VOICE_BINDING,
        NarrationSettingsOperation.PUT_PRONUNCIATION_PROFILE,
        NarrationSettingsOperation.PREVIEW_CACHE_CLEANUP,
        NarrationSettingsOperation.EXECUTE_CACHE_CLEANUP,
    }
)
_VOICE_ASSET_OPERATIONS: Final[frozenset[NarrationSettingsOperation]] = frozenset(
    {
        NarrationSettingsOperation.CREATE_VOICE_PROFILE,
        NarrationSettingsOperation.PUT_VOICE_PROFILE,
        NarrationSettingsOperation.ARCHIVE_VOICE_PROFILE,
        NarrationSettingsOperation.CREATE_PRESET_VOICE_VERSION,
        NarrationSettingsOperation.CREATE_OFFICIAL_VOICE_PREVIEW,
        NarrationSettingsOperation.CREATE_VOICE_PREVIEW,
    }
)
_VOICE_RIGHTS_OPERATIONS: Final[frozenset[NarrationSettingsOperation]] = frozenset(
    {
        NarrationSettingsOperation.CREATE_UPLOADED_VOICE_VERSION,
        NarrationSettingsOperation.LOCK_VOICE_PROFILE,
    }
)
_VOICE_SELECTION_OPERATIONS: Final[frozenset[NarrationSettingsOperation]] = frozenset(
    {NarrationSettingsOperation.SELECT_OFFICIAL_VOICE}
)
_AUTHORIZATION_OPERATION_GROUPS: Final = (
    _READ_ONLY_OPERATIONS,
    _CONFIGURE_OPERATIONS,
    _VOICE_ASSET_OPERATIONS,
    _VOICE_RIGHTS_OPERATIONS,
    _VOICE_SELECTION_OPERATIONS,
)


def _require_authorized(
    authorization: NarrationRequestAuthorization,
    operation: NarrationSettingsOperation,
) -> None:
    """Fail before capability lookup or store access to avoid scope disclosure."""

    allowed = authorization.can_read
    if operation in _CONFIGURE_OPERATIONS:
        allowed = allowed and authorization.can_configure
    elif operation in _VOICE_ASSET_OPERATIONS:
        allowed = allowed and authorization.can_manage_voice_assets
    elif operation in _VOICE_RIGHTS_OPERATIONS:
        allowed = (
            allowed
            and authorization.can_manage_voice_assets
            and authorization.can_confirm_voice_rights
        )
    elif operation in _VOICE_SELECTION_OPERATIONS:
        allowed = (
            allowed
            and authorization.can_configure
            and authorization.can_manage_voice_assets
        )
    elif operation not in _READ_ONLY_OPERATIONS:
        raise AssertionError(f"unclassified narration authorization operation: {operation.value}")
    if not allowed:
        raise NarrationApiFault(
            wire.NarrationErrorCode.SCOPE_VIOLATION,
            "找不到请求的朗读资源。",
        )


class NarrationSettingsMutationStore(NarrationStore, Protocol):
    def delete(self, row: object) -> None: ...


@dataclass(frozen=True, slots=True)
class _BindingImpactAggregate:
    affected_chapter_count: int
    affected_segment_count: int
    historical_edition_count: int


class SqlAlchemyNarrationSettingsStore(SqlAlchemyNarrationStore):
    """T2 settings adapter with bounded read projections and replacement PUTs."""

    def delete(self, row: object) -> None:
        self.session.delete(row)

    def require_character_scope(
        self,
        *,
        novel_id: UUID,
        character_ids: tuple[UUID, ...],
    ) -> None:
        target_ids = tuple(sorted(set(character_ids), key=str))
        if not target_ids:
            return
        rows = self.session.execute(
            select(NovelCharacter.id, NovelCharacter.novel_id).where(
                NovelCharacter.id.in_(target_ids)
            )
        ).all()
        by_id = {row.id: row.novel_id for row in rows}
        if any(character_id not in by_id for character_id in target_ids):
            raise NarrationNotFound("character not found")
        if any(by_id[character_id] != novel_id for character_id in target_ids):
            raise NarrationScopeMismatch("character belongs to another novel")

    def character_binding_impacts(
        self,
        *,
        novel_id: UUID,
        character_ids: tuple[UUID, ...],
    ) -> dict[UUID, _BindingImpactAggregate]:
        """Aggregate historical impact without hydrating segment text or N+1 rows."""

        target_ids = tuple(sorted(set(character_ids), key=str))
        if not target_ids:
            return {}
        scoped_segments = (
            select(
                NarrationSegment.character_id.label("character_id"),
                NarrationSegment.script_version_id.label("script_version_id"),
                NarrationScriptVersion.id.label("resolved_version_id"),
                NarrationScript.id.label("script_id"),
                NarrationScript.novel_id.label("script_novel_id"),
                NarrationScript.document_id.label("document_id"),
            )
            .select_from(NarrationSegment)
            .outerjoin(
                NarrationScriptVersion,
                NarrationScriptVersion.id == NarrationSegment.script_version_id,
            )
            .outerjoin(
                NarrationScript,
                NarrationScript.id == NarrationScriptVersion.script_id,
            )
            .where(NarrationSegment.character_id.in_(target_ids))
            .cte("character_binding_scoped_segments")
        )
        segment_stats = (
            select(
                scoped_segments.c.character_id,
                func.count().label("segment_count"),
                func.count(func.distinct(scoped_segments.c.document_id)).label(
                    "chapter_count"
                ),
                func.bool_and(
                    scoped_segments.c.resolved_version_id.is_not(None)
                ).label("versions_complete"),
                func.bool_and(scoped_segments.c.script_id.is_not(None)).label(
                    "scripts_complete"
                ),
                func.bool_and(scoped_segments.c.script_novel_id == novel_id).label(
                    "scripts_in_scope"
                ),
            )
            .group_by(scoped_segments.c.character_id)
            .cte("character_binding_segment_stats")
        )
        character_versions = (
            select(
                scoped_segments.c.character_id,
                scoped_segments.c.script_version_id,
            )
            .distinct()
            .cte("character_binding_versions")
        )
        edition_stats = (
            select(
                character_versions.c.character_id,
                func.count(NarrationEdition.id).label("edition_count"),
                func.bool_and(
                    or_(
                        NarrationEdition.id.is_(None),
                        NarrationEdition.novel_id == novel_id,
                    )
                ).label("editions_in_scope"),
            )
            .select_from(character_versions)
            .outerjoin(
                NarrationEdition,
                NarrationEdition.script_version_id
                == character_versions.c.script_version_id,
            )
            .group_by(character_versions.c.character_id)
            .cte("character_binding_edition_stats")
        )
        rows = self.session.execute(
            select(
                segment_stats.c.character_id,
                segment_stats.c.segment_count,
                segment_stats.c.chapter_count,
                segment_stats.c.versions_complete,
                segment_stats.c.scripts_complete,
                segment_stats.c.scripts_in_scope,
                edition_stats.c.edition_count,
                edition_stats.c.editions_in_scope,
            ).join(
                edition_stats,
                edition_stats.c.character_id == segment_stats.c.character_id,
            )
        ).all()
        aggregates = {
            character_id: _BindingImpactAggregate(0, 0, 0)
            for character_id in target_ids
        }
        for row in rows:
            if row.versions_complete is not True:
                raise InvalidNarrationState(
                    "character segment names a missing script version"
                )
            if row.scripts_complete is not True:
                raise InvalidNarrationState(
                    "character segment names a missing narration script"
                )
            if row.scripts_in_scope is not True:
                raise NarrationScopeMismatch(
                    "character segment script left its novel"
                )
            if row.editions_in_scope is not True:
                raise NarrationScopeMismatch(
                    "character binding impact edition left its novel"
                )
            aggregates[row.character_id] = _BindingImpactAggregate(
                affected_chapter_count=int(row.chapter_count),
                affected_segment_count=int(row.segment_count),
                historical_edition_count=int(row.edition_count),
            )
        return aggregates


RuntimeStatusProvider = Callable[[], Mapping[str, object]]


def default_narration_settings_values() -> wire.NarrationSettingsValues:
    return wire.NarrationSettingsValues(
        narrator=None,
        language="zh-CN",
        output_format=wire.OutputAudioFormat.M4A_AAC_LC,
        script_review_policy=wire.ScriptReviewPolicy.BLOCKERS_ONLY,
        analysis_mode=wire.AnalysisMode.LOCAL_RULES_ONLY,
        text_rules=wire.NarrationTextRules(
            read_chapter_title=True,
            read_author_notes=False,
            read_section_breaks=False,
            first_person_mode=wire.FirstPersonVoiceMode.NARRATOR,
            first_person_character_id=None,
            inner_monologue_mode=wire.InnerMonologueVoiceMode.CHARACTER,
        ),
        timing=wire.NarrationTimingSettings(
            sentence_gap_ms=220,
            paragraph_gap_ms=480,
            section_gap_ms=850,
        ),
        casting=wire.NarrationCastingSettings(
            anonymous_reuse_scope=wire.AnonymousReuseScope.SCENE,
            same_scene_voice_deduplication=True,
            unknown_speaker_action=wire.UnknownSpeakerAction.BLOCK,
        ),
        playback=wire.NarrationPlaybackPreferences(playback_rate=1.0, volume=1.0),
    )


def _payload(
    command: NarrationSettingsApiCommand,
    model: type[_PayloadModel],
) -> _PayloadModel:
    if type(command.payload) is not model:
        raise NarrationServiceError("command payload does not match its operation")
    return command.payload


def _required_novel_id(command: NarrationSettingsApiCommand) -> UUID:
    if not isinstance(command.novel_id, UUID):
        raise NarrationApiFault(
            wire.NarrationErrorCode.REQUEST_VALIDATION_FAILED,
            "缺少作品标识。",
            field="novel_id",
        )
    return command.novel_id


def _require_enabled(
    capabilities: wire.NarrationCapabilities,
    key: wire.CapabilityKey,
) -> None:
    capability = capabilities.item(key)
    if not (
        capability.state is wire.CapabilityState.ENABLED
        and capability.visible
        and capability.actionable
    ):
        raise NarrationApiFault(
            wire.NarrationErrorCode.CAPABILITY_DISABLED,
            "该朗读能力尚未通过当前产品门禁。",
            capability=key,
        )


def _storage_settings(values: wire.NarrationSettingsValues) -> dict[str, object]:
    payload = values.model_dump(mode="json")
    for key in ("narrator", "script_review_policy", "analysis_mode"):
        payload.pop(key)
    # Project fingerprints reject binary floats.  Persist the two playback-only
    # values as bounded round-trip decimal strings and restore them on read;
    # synthesis-affecting values remain integer milliseconds elsewhere.
    payload["playback"] = {
        "playback_rate": str(values.playback.playback_rate),
        "volume": str(values.playback.volume),
    }
    return payload


def _settings_values_from_row(row: NovelNarrationSettings) -> wire.NarrationSettingsValues:
    if type(row.settings_json) is not dict:
        raise InvalidNarrationState("narration settings JSON is malformed")
    if (row.narrator_profile_id is None) != (row.narrator_version_id is None):
        raise InvalidNarrationState("persisted narrator identity is incomplete")
    payload = dict(row.settings_json)
    playback = payload.get("playback")
    if (
        type(playback) is not dict
        or set(playback) != {"playback_rate", "volume"}
        or any(
            type(playback[key]) is not str
            or not _BOUNDED_DECIMAL.fullmatch(playback[key])
            for key in ("playback_rate", "volume")
        )
    ):
        raise InvalidNarrationState("persisted playback preferences are malformed")
    payload["playback"] = {
        "playback_rate": float(playback["playback_rate"]),
        "volume": float(playback["volume"]),
    }
    payload.update(
        {
            "narrator": None
            if row.narrator_profile_id is None
            else {
                "profile_id": row.narrator_profile_id,
                "version_id": row.narrator_version_id,
            },
            "script_review_policy": row.script_review_policy,
            "analysis_mode": row.analysis_mode,
        }
    )
    try:
        return wire.NarrationSettingsValues.model_validate(payload)
    except ValidationError as error:
        raise InvalidNarrationState("persisted narration settings violate the wire contract") from error


def get_narration_settings(
    store: NarrationStore,
    *,
    novel_id: UUID,
) -> wire.NarrationSettingsResource:
    require_local_novel(store, novel_id)
    row = store.find_one(NovelNarrationSettings, novel_id=novel_id)
    if row is None:
        return wire.NarrationSettingsResource(
            novel_id=novel_id,
            settings_id=None,
            exists=False,
            version=0,
            values=default_narration_settings_values(),
            updated_at=None,
        )
    require_same_novel(row.novel_id, novel_id, label="narration settings")
    if type(row.version) is not int or row.version < 1:
        raise InvalidNarrationState("narration settings version is invalid")
    return wire.NarrationSettingsResource(
        novel_id=novel_id,
        settings_id=row.id,
        exists=True,
        version=row.version,
        values=_settings_values_from_row(row),
        updated_at=row.updated_at,
    )


def _require_character(
    store: NarrationStore,
    *,
    novel_id: UUID,
    character_id: UUID,
    for_update: bool = False,
) -> NovelCharacter:
    character = store.get(NovelCharacter, character_id, for_update=for_update)
    if character is None:
        raise NarrationNotFound("character not found")
    if character.novel_id != novel_id:
        raise NarrationScopeMismatch("character belongs to another novel")
    return character


def _require_characters(
    store: NarrationStore,
    *,
    novel_id: UUID,
    character_ids: tuple[UUID, ...],
) -> None:
    validator = getattr(store, "require_character_scope", None)
    if callable(validator):
        validator(novel_id=novel_id, character_ids=character_ids)
        return
    for character_id in character_ids:
        _require_character(store, novel_id=novel_id, character_id=character_id)


def _validate_text_character(
    store: NarrationStore,
    *,
    novel_id: UUID,
    rules: wire.NarrationTextRules,
) -> None:
    if rules.first_person_character_id is None:
        return
    character = _require_character(
        store,
        novel_id=novel_id,
        character_id=rules.first_person_character_id,
    )
    if character.lifecycle_state != "active":
        raise InvalidNarrationState("first-person character is not active")


def _validate_voice_selection(
    store: NarrationStore,
    *,
    novel_id: UUID,
    selection: wire.NarratorVoiceSelection | None,
) -> None:
    if selection is None:
        return
    profile, version, _rights = require_usable_voice(
        store,
        selection.version_id,
        novel_id=novel_id,
    )
    if profile.id != selection.profile_id or version.profile_id != selection.profile_id:
        raise NarrationScopeMismatch("narrator profile/version identity changed")


def _current_consent_row(
    store: NarrationStore,
    *,
    novel_id: UUID,
    for_update: bool = False,
) -> NarrationCloudConsentRow | None:
    rows = store.find_all(
        NarrationCloudConsentRow,
        novel_id=novel_id,
        order_by=("confirmed_at", "id"),
        for_update=for_update,
    )
    if any(
        row.purpose != _CLOUD_PURPOSE or row.data_scope != _CLOUD_DATA_SCOPE
        for row in rows
    ):
        raise InvalidNarrationState("cloud consent purpose or data scope drifted")
    active = [row for row in rows if row.revoked_at is None]
    if len(active) > 1:
        raise InvalidNarrationState("multiple active cloud consents are ambiguous")
    return active[0] if active else (rows[-1] if rows else None)


def cloud_consent_resource(
    row: NarrationCloudConsentRow | None,
) -> wire.NarrationCloudConsent:
    if row is None:
        return wire.NarrationCloudConsent(
            consent_id=None,
            version=0,
            state=wire.CloudConsentState.NOT_GRANTED,
            notice_version=None,
            provider_id=None,
            model_id=None,
            confirmed_at=None,
            revoked_at=None,
        )
    if row.confirmed_at is None:
        raise InvalidNarrationState("cloud consent confirmation timestamp is absent")
    if row.confirmed_actor != _CONSENT_ACTOR:
        raise InvalidNarrationState("cloud consent actor left the local owner scope")
    if (row.provider_id is None) != (row.model_id is None):
        raise InvalidNarrationState("cloud consent provider/model identity is incomplete")
    revoked = row.revoked_at is not None
    return wire.NarrationCloudConsent(
        consent_id=row.id,
        version=2 if revoked else 1,
        state=wire.CloudConsentState.REVOKED if revoked else wire.CloudConsentState.ACTIVE,
        notice_version=row.notice_version,
        provider_id=row.provider_id,
        model_id=row.model_id,
        confirmed_at=row.confirmed_at,
        revoked_at=row.revoked_at,
    )


def _require_active_cloud_consent(store: NarrationStore, novel_id: UUID) -> None:
    current = _current_consent_row(store, novel_id=novel_id)
    if current is None:
        raise NarrationApiFault(
            wire.NarrationErrorCode.CLOUD_CONSENT_REQUIRED,
            "启用云端辅助前必须显式确认最小数据范围授权。",
            capability=wire.CapabilityKey.CLOUD_ASSISTED_ANALYSIS,
        )
    if current.revoked_at is not None:
        raise NarrationApiFault(
            wire.NarrationErrorCode.CLOUD_CONSENT_REVOKED,
            "作品级云端授权已撤销，后续正文不会外发。",
            capability=wire.CapabilityKey.CLOUD_ASSISTED_ANALYSIS,
        )
    projected = cloud_consent_resource(current)
    if (
        projected.state is not wire.CloudConsentState.ACTIVE
        or projected.notice_version != _CLOUD_NOTICE_VERSION
    ):
        raise NarrationApiFault(
            wire.NarrationErrorCode.CLOUD_CONSENT_REQUIRED,
            "云端授权告知版本已变化，请重新确认最小数据范围。",
            capability=wire.CapabilityKey.CLOUD_ASSISTED_ANALYSIS,
        )


def put_narration_settings(
    store: NarrationStore,
    *,
    novel_id: UUID,
    request: wire.UpdateNarrationSettingsRequest,
    capabilities: wire.NarrationCapabilities,
) -> wire.NarrationSettingsResource:
    require_local_novel(store, novel_id, for_update=True)
    _validate_voice_selection(store, novel_id=novel_id, selection=request.values.narrator)
    _validate_text_character(store, novel_id=novel_id, rules=request.values.text_rules)
    if request.values.analysis_mode is wire.AnalysisMode.CLOUD_ASSISTED:
        _require_enabled(capabilities, wire.CapabilityKey.CLOUD_ASSISTED_ANALYSIS)
        _require_active_cloud_consent(store, novel_id)
    current = get_narration_settings(store, novel_id=novel_id)
    if current.version != request.expected_version:
        raise NarrationCasConflict("narration settings version changed")
    if current.exists and current.values == request.values:
        return current
    selection = request.values.narrator
    update_settings(
        store,
        NarrationSettingsUpdate(
            novel_id=novel_id,
            script_review_policy=request.values.script_review_policy.value,
            analysis_mode=request.values.analysis_mode.value,
            settings_json=_storage_settings(request.values),
            expected_version=request.expected_version,
            narrator_profile_id=selection.profile_id if selection is not None else None,
            narrator_version_id=selection.version_id if selection is not None else None,
        ),
    )
    return get_narration_settings(store, novel_id=novel_id)


def put_playback_preferences(
    store: NarrationStore,
    *,
    novel_id: UUID,
    request: wire.UpdateNarrationPlaybackPreferencesRequest,
    capabilities: wire.NarrationCapabilities,
) -> wire.NarrationSettingsResource:
    current = get_narration_settings(store, novel_id=novel_id)
    return put_narration_settings(
        store,
        novel_id=novel_id,
        request=wire.UpdateNarrationSettingsRequest(
            expected_version=request.expected_version,
            values=current.values.model_copy(update={"playback": request.playback}),
        ),
        capabilities=capabilities,
    )


def _require_scope_target(
    store: NarrationStore,
    *,
    novel_id: UUID,
    scope_kind: wire.NarrationScopeKind,
    scope_id: UUID,
) -> None:
    model = Volume if scope_kind is wire.NarrationScopeKind.VOLUME else Document
    target = store.get(model, scope_id)
    if target is None:
        raise NarrationNotFound("narration scope target not found")
    if target.novel_id != novel_id:
        raise NarrationScopeMismatch("narration scope target belongs to another novel")
    if scope_kind is wire.NarrationScopeKind.CHAPTER and target.kind != "chapter":
        raise NarrationScopeMismatch("narration chapter scope is not a chapter document")


def _empty_scope_override(
    *,
    novel_id: UUID,
    scope_kind: wire.NarrationScopeKind,
    scope_id: UUID,
) -> wire.NarrationScopeOverrideResource:
    return wire.NarrationScopeOverrideResource(
        override_id=None,
        novel_id=novel_id,
        scope_kind=scope_kind,
        scope_id=scope_id,
        enabled=False,
        version=0,
        overrides=wire.NarrationScopeOverrideValues(
            narrator=None,
            language=None,
            text_rules=None,
            timing=None,
        ),
    )


def _scope_override_resource(
    row: NarrationScopeOverride,
) -> wire.NarrationScopeOverrideResource:
    if type(row.settings_json) is not dict:
        raise InvalidNarrationState("scope override JSON is malformed")
    try:
        values = wire.NarrationScopeOverrideValues.model_validate(row.settings_json)
    except ValidationError as error:
        raise InvalidNarrationState("persisted scope override violates the wire contract") from error
    if values.is_empty() or type(row.version) is not int or row.version < 1:
        raise InvalidNarrationState("persisted scope override is empty or unversioned")
    try:
        kind = wire.NarrationScopeKind(row.scope_kind)
    except ValueError as error:
        raise InvalidNarrationState("persisted scope kind is unsupported") from error
    return wire.NarrationScopeOverrideResource(
        override_id=row.id,
        novel_id=row.novel_id,
        scope_kind=kind,
        scope_id=row.scope_id,
        enabled=True,
        version=row.version,
        overrides=values,
    )


def list_scope_overrides(
    store: NarrationStore,
    *,
    novel_id: UUID,
) -> wire.NarrationScopeOverrideListResponse:
    require_local_novel(store, novel_id)
    rows = store.find_all(
        NarrationScopeOverride,
        novel_id=novel_id,
        order_by=("scope_kind", "scope_id"),
    )
    items: list[wire.NarrationScopeOverrideResource] = []
    for row in rows:
        resource = _scope_override_resource(row)
        _require_scope_target(
            store,
            novel_id=novel_id,
            scope_kind=resource.scope_kind,
            scope_id=resource.scope_id,
        )
        items.append(resource)
    return wire.NarrationScopeOverrideListResponse(novel_id=novel_id, items=items)


def put_scope_override(
    store: NarrationSettingsMutationStore,
    *,
    novel_id: UUID,
    scope_kind: wire.NarrationScopeKind,
    scope_id: UUID,
    request: wire.PutNarrationScopeOverrideRequest,
) -> wire.NarrationScopeOverrideResource:
    require_local_novel(store, novel_id, for_update=True)
    _require_scope_target(
        store,
        novel_id=novel_id,
        scope_kind=scope_kind,
        scope_id=scope_id,
    )
    row = store.find_one(
        NarrationScopeOverride,
        novel_id=novel_id,
        scope_kind=scope_kind.value,
        scope_id=scope_id,
        for_update=True,
    )
    current_version = 0 if row is None else row.version
    if current_version != request.expected_version:
        raise NarrationCasConflict("narration scope override version changed")
    if not request.enabled:
        if row is not None:
            store.delete(row)
            store.flush()
        return _empty_scope_override(
            novel_id=novel_id,
            scope_kind=scope_kind,
            scope_id=scope_id,
        )
    _validate_voice_selection(store, novel_id=novel_id, selection=request.overrides.narrator)
    if request.overrides.text_rules is not None:
        _validate_text_character(
            store,
            novel_id=novel_id,
            rules=request.overrides.text_rules,
        )
    replacement = request.overrides.model_dump(mode="json")
    if row is not None and row.settings_json == replacement:
        return _scope_override_resource(row)
    if row is None:
        row = NarrationScopeOverride(
            id=uuid4(),
            novel_id=novel_id,
            scope_kind=scope_kind.value,
            scope_id=scope_id,
            settings_json=replacement,
            version=1,
        )
        store.add(row)
    else:
        row.settings_json = replacement
        row.version += 1
    store.flush()
    return _scope_override_resource(row)


def _required_idempotency_key(value: str | None) -> str:
    if value is None or not _IDEMPOTENCY_KEY.fullmatch(value):
        raise NarrationServiceError("cloud consent idempotency key is invalid")
    return value


def _consent_id(novel_id: UUID, key: str) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"ai-novel-world-2026/narration/cloud-consent/{novel_id}/{key}",
    )


def _consent_matches(
    row: NarrationCloudConsentRow,
    request: wire.CreateNarrationCloudConsentRequest,
) -> bool:
    return (
        row.purpose == _CLOUD_PURPOSE
        and row.data_scope == request.data_scope
        and row.notice_version == request.notice_version
        and row.provider_id == request.provider_id
        and row.model_id == request.model_id
    )


def create_cloud_consent(
    store: NarrationStore,
    *,
    novel_id: UUID,
    request: wire.CreateNarrationCloudConsentRequest,
    idempotency_key: str,
) -> wire.NarrationCloudConsent:
    require_local_novel(store, novel_id, for_update=True)
    if request.notice_version != _CLOUD_NOTICE_VERSION:
        raise NarrationServiceError("cloud consent notice version is unsupported")
    key = _required_idempotency_key(idempotency_key)
    row_id = _consent_id(novel_id, key)
    existing = store.get(NarrationCloudConsentRow, row_id, for_update=True)
    if existing is not None:
        if existing.novel_id != novel_id:
            raise NarrationScopeMismatch("cloud consent idempotency identity left its novel")
        if not _consent_matches(existing, request):
            raise IdempotencyConflict("cloud consent key names another payload")
        return cloud_consent_resource(existing)
    current = _current_consent_row(store, novel_id=novel_id, for_update=True)
    if current is not None and current.revoked_at is None:
        raise InvalidNarrationState("an active cloud consent already exists")
    now = utc_now()
    row = NarrationCloudConsentRow(
        id=row_id,
        novel_id=novel_id,
        purpose=_CLOUD_PURPOSE,
        data_scope=_CLOUD_DATA_SCOPE,
        notice_version=request.notice_version,
        provider_id=request.provider_id,
        model_id=request.model_id,
        confirmed_actor=_CONSENT_ACTOR,
        confirmed_at=now,
        revoked_at=None,
    )
    store.add(row)
    store.flush()
    return cloud_consent_resource(row)


def revoke_cloud_consent(
    store: NarrationStore,
    *,
    novel_id: UUID,
    request: wire.RevokeNarrationCloudConsentRequest,
) -> wire.NarrationCloudConsent:
    require_local_novel(store, novel_id, for_update=True)
    row = store.get(NarrationCloudConsentRow, request.consent_id, for_update=True)
    if row is None:
        raise NarrationNotFound("cloud consent not found")
    if row.novel_id != novel_id:
        raise NarrationScopeMismatch("cloud consent belongs to another novel")
    current = cloud_consent_resource(row)
    if current.version != request.expected_version:
        raise NarrationCasConflict("cloud consent version changed")
    if row.revoked_at is not None:
        return current
    row.revoked_at = utc_now()
    store.flush()
    return cloud_consent_resource(row)


def _binding_impact(
    store: NarrationStore,
    *,
    novel_id: UUID,
    character_id: UUID,
) -> wire.VoiceBindingImpact:
    segments = store.find_all(NarrationSegment, character_id=character_id)
    version_ids = {segment.script_version_id for segment in segments}
    script_ids: set[UUID] = set()
    for version_id in version_ids:
        version = store.get(NarrationScriptVersion, version_id)
        if version is None:
            raise InvalidNarrationState("character segment names a missing script version")
        script_ids.add(version.script_id)
    documents: set[UUID] = set()
    for script_id in script_ids:
        script = store.get(NarrationScript, script_id)
        if script is None or script.novel_id != novel_id:
            raise NarrationScopeMismatch("character segment script left its novel")
        documents.add(script.document_id)
    historical_editions = 0
    for version_id in version_ids:
        editions = store.find_all(NarrationEdition, script_version_id=version_id)
        if any(edition.novel_id != novel_id for edition in editions):
            raise NarrationScopeMismatch("character binding impact edition left its novel")
        historical_editions += len(editions)
    return wire.VoiceBindingImpact(
        affected_chapter_count=len(documents),
        affected_segment_count=len(segments),
        historical_edition_count=historical_editions,
        regeneration_required=bool(segments),
    )


def _binding_impacts(
    store: NarrationStore,
    *,
    novel_id: UUID,
    character_ids: tuple[UUID, ...],
) -> dict[UUID, wire.VoiceBindingImpact]:
    target_ids = tuple(sorted(set(character_ids), key=str))
    projector = getattr(store, "character_binding_impacts", None)
    if callable(projector):
        aggregates = projector(novel_id=novel_id, character_ids=target_ids)
        if set(aggregates) != set(target_ids):
            raise InvalidNarrationState(
                "character binding impact projection is incomplete"
            )
        return {
            character_id: wire.VoiceBindingImpact(
                affected_chapter_count=aggregate.affected_chapter_count,
                affected_segment_count=aggregate.affected_segment_count,
                historical_edition_count=aggregate.historical_edition_count,
                regeneration_required=aggregate.affected_segment_count > 0,
            )
            for character_id, aggregate in aggregates.items()
        }
    return {
        character_id: _binding_impact(
            store,
            novel_id=novel_id,
            character_id=character_id,
        )
        for character_id in target_ids
    }


def _binding_resource(
    store: NarrationStore,
    *,
    novel_id: UUID,
    character_id: UUID,
    row: CharacterVoiceBinding | None,
    impact: wire.VoiceBindingImpact | None = None,
) -> wire.CharacterVoiceBindingResource:
    resolved_impact = (
        impact
        if impact is not None
        else _binding_impacts(
            store,
            novel_id=novel_id,
            character_ids=(character_id,),
        )[character_id]
    )
    if row is None:
        return wire.CharacterVoiceBindingResource(
            binding_id=None,
            novel_id=novel_id,
            character_id=character_id,
            binding_policy=wire.CharacterVoiceBindingPolicy.UNSET,
            profile_id=None,
            version_id=None,
            language="zh-CN",
            version=0,
            impact=resolved_impact,
            updated_at=None,
        )
    if row.novel_id != novel_id or row.character_id != character_id:
        raise NarrationScopeMismatch("character voice binding scope changed")
    if row.binding_policy == wire.CharacterVoiceBindingPolicy.UNSET.value:
        raise InvalidNarrationState("unset character binding must not be persisted")
    return wire.CharacterVoiceBindingResource(
        binding_id=row.id,
        novel_id=novel_id,
        character_id=character_id,
        binding_policy=row.binding_policy,
        profile_id=row.profile_id,
        version_id=row.voice_version_id,
        language=row.language,
        version=row.version,
        impact=resolved_impact,
        updated_at=row.updated_at,
    )


def get_character_voice_binding(
    store: NarrationStore,
    *,
    novel_id: UUID,
    character_id: UUID,
) -> wire.CharacterVoiceBindingResource:
    require_local_novel(store, novel_id)
    _require_character(store, novel_id=novel_id, character_id=character_id)
    row = store.find_one(CharacterVoiceBinding, character_id=character_id)
    return _binding_resource(
        store,
        novel_id=novel_id,
        character_id=character_id,
        row=row,
    )


def list_character_voice_bindings(
    store: NarrationStore,
    *,
    novel_id: UUID,
) -> wire.CharacterVoiceBindingListResponse:
    require_local_novel(store, novel_id)
    rows = store.find_all(
        CharacterVoiceBinding,
        novel_id=novel_id,
        order_by=("character_id",),
    )
    _require_characters(
        store,
        novel_id=novel_id,
        character_ids=tuple(row.character_id for row in rows),
    )
    impacts = _binding_impacts(
        store,
        novel_id=novel_id,
        character_ids=tuple(row.character_id for row in rows),
    )
    items = [
        _binding_resource(
            store,
            novel_id=novel_id,
            character_id=row.character_id,
            row=row,
            impact=impacts[row.character_id],
        )
        for row in rows
    ]
    return wire.CharacterVoiceBindingListResponse(novel_id=novel_id, items=items)


def put_character_voice_binding(
    store: NarrationSettingsMutationStore,
    *,
    novel_id: UUID,
    character_id: UUID,
    request: wire.PutCharacterVoiceBindingRequest,
) -> wire.CharacterVoiceBindingResource:
    require_local_novel(store, novel_id, for_update=True)
    character = _require_character(
        store,
        novel_id=novel_id,
        character_id=character_id,
        for_update=True,
    )
    if character.lifecycle_state != "active":
        raise InvalidNarrationState("archived character voice binding cannot change")
    row = store.find_one(CharacterVoiceBinding, character_id=character_id, for_update=True)
    current_version = 0 if row is None else row.version
    if current_version != request.expected_version:
        raise NarrationCasConflict("character voice binding version changed")
    if request.binding_policy is wire.CharacterVoiceBindingPolicy.UNSET:
        if row is not None:
            store.delete(row)
            store.flush()
        return _binding_resource(
            store,
            novel_id=novel_id,
            character_id=character_id,
            row=None,
        )
    if request.profile_id is None or request.version_id is None:
        raise NarrationServiceError("configured binding requires a voice identity")
    profile, version, _rights = require_usable_voice(
        store,
        request.version_id,
        novel_id=novel_id,
    )
    if profile.id != request.profile_id or version.profile_id != request.profile_id:
        raise NarrationScopeMismatch("character voice profile/version identity changed")
    if row is not None and (
        row.binding_policy == request.binding_policy.value
        and row.profile_id == request.profile_id
        and row.voice_version_id == request.version_id
        and row.language == request.language
    ):
        return _binding_resource(
            store,
            novel_id=novel_id,
            character_id=character_id,
            row=row,
        )
    now = utc_now()
    if row is None:
        row = CharacterVoiceBinding(
            id=uuid4(),
            novel_id=novel_id,
            character_id=character_id,
            profile_id=request.profile_id,
            voice_version_id=request.version_id,
            binding_policy=request.binding_policy.value,
            language=request.language,
            parameters_json={},
            version=1,
            updated_at=now,
        )
        store.add(row)
    else:
        row.profile_id = request.profile_id
        row.voice_version_id = request.version_id
        row.binding_policy = request.binding_policy.value
        row.language = request.language
        row.version += 1
        row.updated_at = now
    store.flush()
    return _binding_resource(
        store,
        novel_id=novel_id,
        character_id=character_id,
        row=row,
    )


def narration_runtime_resource(
    snapshot: Mapping[str, object],
    *,
    product_visible_allowed: bool = False,
) -> wire.NarrationRuntimeStatus:
    technical = snapshot.get("technical_enabled") is True
    reachable = snapshot.get("sidecar_reachable") is True
    model_ready = snapshot.get("model_ready") is True
    raw_lifecycle = snapshot.get("lifecycle_status")
    fingerprint = snapshot.get("model_fingerprint_sha256")
    if type(fingerprint) is not str or not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
        fingerprint = None
    raw_reason = snapshot.get("reason_code")
    reason = raw_reason if type(raw_reason) is str and _SAFE_REASON.fullmatch(raw_reason) else None
    lifecycle_map = {
        "disabled": wire.RuntimeLifecycleStatus.DISABLED,
        "starting": wire.RuntimeLifecycleStatus.STARTING,
        "ready": wire.RuntimeLifecycleStatus.READY,
        "unavailable": wire.RuntimeLifecycleStatus.UNAVAILABLE,
        "stopping": wire.RuntimeLifecycleStatus.STOPPING,
    }
    lifecycle = lifecycle_map.get(raw_lifecycle) if type(raw_lifecycle) is str else None
    protocol = snapshot.get("protocol_version")
    protocol_matches = protocol == _RUNTIME_PROTOCOL_FALLBACK
    if lifecycle is wire.RuntimeLifecycleStatus.READY and not (
        technical
        and reachable
        and model_ready
        and fingerprint is not None
        and protocol_matches
        and raw_reason is None
    ):
        lifecycle = wire.RuntimeLifecycleStatus.UNAVAILABLE
        reason = (
            "RUNTIME_PROTOCOL_MISMATCH"
            if not protocol_matches
            else "RUNTIME_READY_EVIDENCE_INVALID"
        )
        reachable = False
        model_ready = False
        fingerprint = None
    if lifecycle is None:
        lifecycle = wire.RuntimeLifecycleStatus.UNAVAILABLE
        reason = reason or "RUNTIME_STATUS_UNAVAILABLE"
        reachable = False
        model_ready = False
        fingerprint = None
    if lifecycle is wire.RuntimeLifecycleStatus.DISABLED:
        reason = reason or "TTS_RUNTIME_DISABLED"
        reachable = False
        model_ready = False
        fingerprint = None
    if lifecycle is wire.RuntimeLifecycleStatus.UNAVAILABLE:
        reason = reason or "TTS_RUNTIME_UNAVAILABLE"
        reachable = False
        model_ready = False
        fingerprint = None
    if lifecycle is not wire.RuntimeLifecycleStatus.READY:
        reachable = False
        model_ready = False
        fingerprint = None
    if not protocol_matches:
        protocol = _RUNTIME_PROTOCOL_FALLBACK
    return wire.NarrationRuntimeStatus(
        technical_enabled=technical,
        lifecycle_status=lifecycle,
        sidecar_reachable=reachable,
        model_ready=model_ready,
        product_visible=(
            product_visible_allowed
            and snapshot.get("product_visible") is True
            and lifecycle is wire.RuntimeLifecycleStatus.READY
            and model_ready
        ),
        protocol_version=protocol,
        model_fingerprint_sha256=fingerprint,
        reason_code=reason,
    )


def _voice_sources(
    capabilities: wire.NarrationCapabilities,
) -> list[wire.VoiceSourceAvailability]:
    definitions = (
        (wire.VoiceSourceType.PRESET, wire.CapabilityKey.PRESET_VOICE_SOURCE),
        (wire.VoiceSourceType.UPLOADED, wire.CapabilityKey.REFERENCE_CLONE),
        (wire.VoiceSourceType.GENERATED, wire.CapabilityKey.VOICE_GENERATOR),
    )
    items: list[wire.VoiceSourceAvailability] = []
    for source_type, key in definitions:
        capability = capabilities.item(key)
        available = (
            capability.state is wire.CapabilityState.ENABLED
            and capability.visible
            and capability.actionable
        )
        items.append(
            wire.VoiceSourceAvailability(
                source_type=source_type,
                capability=key,
                available=available,
                reason_code=None if available else capability.reason_code,
                accepted_mime_types=list(wire.REFERENCE_UPLOAD_MIME_TYPES)
                if source_type is wire.VoiceSourceType.UPLOADED
                else [],
                maximum_bytes=wire.REFERENCE_UPLOAD_MAX_BYTES
                if source_type is wire.VoiceSourceType.UPLOADED
                else None,
            )
        )
    return items


def _binding_is_currently_usable(
    store: NarrationStore,
    row: CharacterVoiceBinding,
    *,
    novel_id: UUID,
) -> bool:
    if row.profile_id is None or row.voice_version_id is None:
        return False
    profile = store.get(VoiceProfile, row.profile_id)
    version = store.get(VoiceProfileVersion, row.voice_version_id)
    if profile is None or version is None or version.profile_id != profile.id:
        return False
    rights = store.get(VoiceRightsRecord, version.rights_record_id)
    if rights is None or rights.expires_at is not None and rights.expires_at <= utc_now():
        return False
    if (
        profile.owner_id != LOCAL_OWNER_ID
        or profile.workspace_id != LOCAL_WORKSPACE_ID
        or version.owner_id != LOCAL_OWNER_ID
        or version.workspace_id != LOCAL_WORKSPACE_ID
        or rights.owner_id != LOCAL_OWNER_ID
        or rights.workspace_id != LOCAL_WORKSPACE_ID
        or profile.novel_id not in {None, novel_id}
        or profile.status != "active"
        or version.state != "locked"
    ):
        return False
    if rights.novel_id not in {None, novel_id}:
        return False
    if not voice_activation_evidence_is_usable(version, rights):
        return False
    if version.source_type == "uploaded" and not rights.voice_cloning:
        return False
    return not any(
        event.event_type in {"revoked", "expired", "review_blocked"}
        for event in store.find_all(VoiceRightsEvent, rights_record_id=rights.id)
    )


def narration_coverage(
    store: NarrationStore,
    *,
    novel_id: UUID,
    generic_ready_slot_count: int,
) -> wire.NarrationCoverageSummary:
    characters = [
        row
        for row in store.find_all(NovelCharacter, novel_id=novel_id)
        if row.lifecycle_state == "active"
    ]
    active_character_ids = {row.id for row in characters}
    bindings = [
        row
        for row in store.find_all(CharacterVoiceBinding, novel_id=novel_id)
        if row.binding_policy in {"dedicated", "inherited"}
        and row.character_id in active_character_ids
    ]
    scripts = store.find_all(NarrationScript, novel_id=novel_id)
    latest_versions: list[NarrationScriptVersion] = []
    for script in scripts:
        versions = store.find_all(
            NarrationScriptVersion,
            script_id=script.id,
            order_by=("version_number",),
        )
        if versions:
            latest_versions.append(versions[-1])
    editions = store.find_all(NarrationEdition, novel_id=novel_id)
    generated_documents = {
        edition.document_id
        for edition in editions
        if edition.state in {"partial_ready", "ready"}
    }
    failed_jobs = [
        job
        for job in store.find_all(
            BackgroundJob,
            owner_id=LOCAL_OWNER_ID,
            workspace_id=LOCAL_WORKSPACE_ID,
            novel_id=novel_id,
        )
        if job.state in {"failed", "dead_letter"}
    ]
    return wire.NarrationCoverageSummary(
        character_count=len(characters),
        configured_character_count=len(bindings),
        locked_character_voice_count=sum(
            _binding_is_currently_usable(store, row, novel_id=novel_id)
            for row in bindings
        ),
        generic_required_slot_count=24,
        generic_ready_slot_count=generic_ready_slot_count,
        pending_review_script_count=sum(
            version.state == "review_required" for version in latest_versions
        ),
        blocker_count=sum(version.blocker_count for version in latest_versions),
        warning_count=sum(version.warning_count for version in latest_versions),
        generated_chapter_count=len(generated_documents),
        failed_job_count=len(failed_jobs),
    )


def _fallback_cache_status(
    novel_id: UUID,
    global_capability: wire.FeatureCapability,
) -> wire.NarrationCacheStatus:
    nested = (
        global_capability.model_copy(deep=True)
        if global_capability.state in {
            wire.CapabilityState.DISABLED,
            wire.CapabilityState.UNAVAILABLE,
        }
        else wire.FeatureCapability(
            key=wire.CapabilityKey.CACHE_CLEANUP,
            state=wire.CapabilityState.UNAVAILABLE,
            visible=global_capability.visible,
            actionable=False,
            reason_code="CACHE_RUNTIME_UNAVAILABLE",
            required_gate=global_capability.required_gate,
        )
    )
    return wire.NarrationCacheStatus(
        novel_id=novel_id,
        snapshot_fingerprint=canonical_sha256(
            {"schema": wire.NARRATION_CACHE_SCHEMA_VERSION, "novel_id": str(novel_id), "state": "unavailable"}
        ),
        source_asset_bytes=0,
        locked_voice_bytes=0,
        referenced_edition_bytes=0,
        derived_cache_bytes=0,
        reclaimable_bytes=0,
        pending_job_count=0,
        disk_free_bytes=0,
        disk_total_bytes=1,
        cleanup_capability=nested,
    )


class NarrationSettingsBackend:
    """All frozen settings operations, with one capability and scope boundary."""

    def __init__(
        self,
        store: NarrationSettingsMutationStore,
        *,
        authorization: NarrationRequestAuthorization = DENY_NARRATION_AUTHORIZATION,
        capabilities: wire.NarrationCapabilities | None = None,
        runtime_status_provider: RuntimeStatusProvider = narration_runtime_status,
        cache_runtime: NarrationCacheRuntime | None = None,
        profile_creation_receipts: VoiceProfileCreationReceiptPort | None = None,
        voice_product: VoiceProductPort | None = None,
        official_voice_selection: OfficialVoiceSelectionPort | None = None,
    ) -> None:
        self.store = store
        self.authorization = authorization
        self.capabilities = (capabilities or wire.t2_hold_capabilities()).model_copy(deep=True)
        self.runtime_status_provider = runtime_status_provider
        self.cache_runtime = cache_runtime or UnavailableNarrationCacheRuntime()
        self.voice_handler = VoiceSettingsHandler(
            store,
            profile_creation_receipts=profile_creation_receipts,
            voice_product=voice_product,
            official_voice_selection=official_voice_selection,
        )
        self.voice_pool = VoicePoolHandlers(store)
        self.pronunciation_handler = PronunciationSettingsHandler(
            store,
            cache_runtime=self.cache_runtime,
        )

    def dispatch(self, command: NarrationSettingsApiCommand) -> object:
        _require_authorized(self.authorization, command.operation)
        capability_key = _MUTATION_CAPABILITY.get(command.operation)
        if capability_key is not None:
            _require_enabled(self.capabilities, wire.CapabilityKey.NARRATION_PRODUCT)
            _require_enabled(self.capabilities, capability_key)
        if command.operation in READING_PRIVACY_OPERATIONS:
            return self._dispatch_reading(command)
        if self.voice_handler.handles(command.operation):
            return self.voice_handler.dispatch(command)
        if self.pronunciation_handler.handles(command.operation):
            return self.pronunciation_handler.dispatch(command)
        try:
            novel_id = _required_novel_id(command)
            if command.operation is NarrationSettingsOperation.GET_GENERIC_VOICE_POOL:
                return self.voice_pool.get_pool(novel_id)
            if command.operation is NarrationSettingsOperation.GET_CASTING_RULES:
                return self.voice_pool.get_casting_rules(novel_id)
        except GenericCastingUnavailable as error:
            raise NarrationApiFault(
                wire.NarrationErrorCode.GENERIC_VOICE_POOL_UNAVAILABLE,
                "自动通用选角尚未通过后续门禁。",
                capability=wire.CapabilityKey.AUTOMATIC_GENERIC_CASTING,
            ) from error
        raise AssertionError(f"unowned narration operation: {command.operation.value}")

    def _dispatch_reading(self, command: NarrationSettingsApiCommand) -> object:
        novel_id = _required_novel_id(command)
        operation = command.operation
        if operation is NarrationSettingsOperation.GET_SETTINGS:
            return get_narration_settings(self.store, novel_id=novel_id)
        if operation is NarrationSettingsOperation.PUT_SETTINGS:
            return put_narration_settings(
                self.store,
                novel_id=novel_id,
                request=_payload(command, wire.UpdateNarrationSettingsRequest),
                capabilities=self.capabilities,
            )
        if operation is NarrationSettingsOperation.PUT_PLAYBACK_PREFERENCES:
            return put_playback_preferences(
                self.store,
                novel_id=novel_id,
                request=_payload(
                    command,
                    wire.UpdateNarrationPlaybackPreferencesRequest,
                ),
                capabilities=self.capabilities,
            )
        if operation is NarrationSettingsOperation.LIST_SCOPE_OVERRIDES:
            return list_scope_overrides(self.store, novel_id=novel_id)
        if operation is NarrationSettingsOperation.PUT_SCOPE_OVERRIDE:
            if command.scope_kind is None or command.scope_id is None:
                raise NarrationServiceError("scope override command is incomplete")
            return put_scope_override(
                self.store,
                novel_id=novel_id,
                scope_kind=command.scope_kind,
                scope_id=command.scope_id,
                request=_payload(command, wire.PutNarrationScopeOverrideRequest),
            )
        if operation is NarrationSettingsOperation.CREATE_CLOUD_CONSENT:
            return create_cloud_consent(
                self.store,
                novel_id=novel_id,
                request=_payload(command, wire.CreateNarrationCloudConsentRequest),
                idempotency_key=_required_idempotency_key(command.idempotency_key),
            )
        if operation is NarrationSettingsOperation.REVOKE_CLOUD_CONSENT:
            return revoke_cloud_consent(
                self.store,
                novel_id=novel_id,
                request=_payload(command, wire.RevokeNarrationCloudConsentRequest),
            )
        if operation is NarrationSettingsOperation.GET_CHARACTER_VOICE_BINDING:
            if command.character_id is None:
                raise NarrationServiceError("character binding command is incomplete")
            return get_character_voice_binding(
                self.store,
                novel_id=novel_id,
                character_id=command.character_id,
            )
        if operation is NarrationSettingsOperation.LIST_CHARACTER_VOICE_BINDINGS:
            return list_character_voice_bindings(self.store, novel_id=novel_id)
        if operation is NarrationSettingsOperation.PUT_CHARACTER_VOICE_BINDING:
            if command.character_id is None:
                raise NarrationServiceError("character binding command is incomplete")
            return put_character_voice_binding(
                self.store,
                novel_id=novel_id,
                character_id=command.character_id,
                request=_payload(command, wire.PutCharacterVoiceBindingRequest),
            )
        if operation is NarrationSettingsOperation.GET_OVERVIEW:
            require_local_novel(self.store, novel_id)
            settings = get_narration_settings(self.store, novel_id=novel_id)
            consent = cloud_consent_resource(
                _current_consent_row(self.store, novel_id=novel_id)
            )
            authorization = wire.NarrationAuthorizationState(
                can_read=self.authorization.can_read,
                can_configure=self.authorization.can_configure,
                can_manage_voice_assets=self.authorization.can_manage_voice_assets,
                can_confirm_voice_rights=self.authorization.can_confirm_voice_rights,
                cloud_consent=consent,
            )
            pool = self.voice_pool.get_pool(novel_id)
            try:
                cache = self.cache_runtime.status(novel_id)
            except (NarrationServiceError, OSError):
                cache = _fallback_cache_status(
                    novel_id,
                    self.capabilities.item(wire.CapabilityKey.CACHE_CLEANUP),
                )
            try:
                runtime_snapshot = self.runtime_status_provider()
            except Exception:
                runtime_snapshot = {
                    "lifecycle_status": "unavailable",
                    "reason_code": "RUNTIME_STATUS_UNAVAILABLE",
                }
            return wire.NarrationOverviewResponse(
                novel_id=novel_id,
                capabilities=self.capabilities,
                authorization=authorization,
                runtime=narration_runtime_resource(
                    runtime_snapshot,
                    product_visible_allowed=_t4_product_is_released(
                        self.capabilities
                    ),
                ),
                settings=settings,
                coverage=narration_coverage(
                    self.store,
                    novel_id=novel_id,
                    generic_ready_slot_count=pool.ready_slot_count,
                ),
                voice_sources=_voice_sources(self.capabilities),
                cache=cache,
            )
        raise AssertionError("unreachable reading/privacy operation")


class TransactionalNarrationSettingsBackend:
    """Commit one authoritative settings mutation and rollback every failure."""

    def __init__(self, session: Session, core: NarrationSettingsBackend) -> None:
        self.session = session
        self.core = core

    def dispatch(self, command: NarrationSettingsApiCommand) -> object:
        if command.operation not in _TRANSACTIONAL_OPERATIONS:
            return self.core.dispatch(command)
        if self.session.in_transaction():
            raise RuntimeError("narration command received a pre-opened transaction")
        with self.session.begin():
            return self.core.dispatch(command)


def build_narration_settings_backend(
    session: Session,
    *,
    authorization: NarrationRequestAuthorization = DENY_NARRATION_AUTHORIZATION,
    capabilities: wire.NarrationCapabilities | None = None,
    runtime_status_provider: RuntimeStatusProvider = narration_runtime_status,
    cache_runtime: NarrationCacheRuntime | None = None,
    profile_creation_receipts: VoiceProfileCreationReceiptPort | None = None,
    voice_product: VoiceProductPort | None = None,
    official_voice_selection: OfficialVoiceSelectionPort | None = None,
) -> TransactionalNarrationSettingsBackend:
    store = SqlAlchemyNarrationSettingsStore(session)
    core = NarrationSettingsBackend(
        store,
        authorization=authorization,
        capabilities=capabilities,
        runtime_status_provider=runtime_status_provider,
        cache_runtime=cache_runtime,
        profile_creation_receipts=profile_creation_receipts,
        voice_product=voice_product,
        official_voice_selection=official_voice_selection,
    )
    return TransactionalNarrationSettingsBackend(session, core)


_DISPATCH_OPERATION_GROUPS: Final = (
    READING_PRIVACY_OPERATIONS,
    VoiceSettingsHandler.operations,
    PronunciationSettingsHandler.operations,
    frozenset(
        {
            NarrationSettingsOperation.GET_GENERIC_VOICE_POOL,
            NarrationSettingsOperation.GET_CASTING_RULES,
        }
    ),
)


def _assert_exact_disjoint_operation_groups(
    label: str,
    groups: tuple[frozenset[NarrationSettingsOperation], ...],
) -> None:
    union: set[NarrationSettingsOperation] = set()
    for group in groups:
        overlap = union & group
        if overlap:
            names = ", ".join(sorted(item.value for item in overlap))
            raise RuntimeError(f"{label} operation groups overlap: {names}")
        union.update(group)
    if union != set(NarrationSettingsOperation):
        raise RuntimeError(f"{label} does not own the exact frozen operation set")


_assert_exact_disjoint_operation_groups("T2 narration dispatcher", _DISPATCH_OPERATION_GROUPS)
_assert_exact_disjoint_operation_groups("T2 narration authorization", _AUTHORIZATION_OPERATION_GROUPS)


__all__ = [
    "DENY_NARRATION_AUTHORIZATION",
    "FIXED_LOCAL_OWNER_NARRATION_AUTHORIZATION",
    "NarrationSettingsBackend",
    "NarrationRequestAuthorization",
    "READING_PRIVACY_OPERATIONS",
    "SqlAlchemyNarrationSettingsStore",
    "TransactionalNarrationSettingsBackend",
    "build_narration_settings_backend",
    "cloud_consent_resource",
    "create_cloud_consent",
    "default_narration_settings_values",
    "get_character_voice_binding",
    "get_narration_settings",
    "list_character_voice_bindings",
    "list_scope_overrides",
    "narration_coverage",
    "narration_runtime_resource",
    "put_character_voice_binding",
    "put_narration_settings",
    "put_scope_override",
    "revoke_cloud_consent",
    "t2_settings_capabilities",
    "t4_product_capabilities",
]
