"""Canonical database rows for the small provider-aware Qwen voice catalog."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    VoiceProfile,
    VoiceProfileVersion,
    VoiceRightsEvent,
    VoiceRightsRecord,
)
from .contracts import NarrationRequestScope
from .official_presets import (
    OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256,
    OFFICIAL_PRESET_REPOSITORY,
    OFFICIAL_PRESET_REVISION,
    OFFICIAL_PRESET_RIGHTS_POLICY_VERSION,
    OFFICIAL_PRESET_RUNTIME_INITIAL_SEED,
    OFFICIAL_PRESET_VERSION_SCHEMA_VERSION,
    OfficialPreset,
    official_preset_canonical_profile_id,
    official_preset_canonical_version_id,
    official_preset_direct_version_fingerprint,
    official_preset_version_fingerprint,
    require_official_preset,
    validate_official_version_evidence,
)
from .services import (
    InvalidNarrationState,
    NarrationScopeMismatch,
    VoiceRightsUnavailable,
)


_ROW_SCHEMA_VERSION = "qwen-tts-voice/1"


@dataclass(frozen=True, slots=True)
class OfficialPresetVersionRows:
    rights: VoiceRightsRecord
    event: VoiceRightsEvent
    version: VoiceProfileVersion


@dataclass(frozen=True, slots=True)
class CanonicalOfficialPresetVoice:
    preset: OfficialPreset
    profile: VoiceProfile
    version: VoiceProfileVersion


def _child_uuid(parent: UUID, label: str) -> UUID:
    return uuid5(parent, f"{_ROW_SCHEMA_VERSION}/{label}")


def build_official_preset_version_rows(
    *,
    profile: VoiceProfile,
    preset: OfficialPreset,
    version_id: UUID,
    version_number: int,
    actor: str,
    at: datetime,
    direct_selection: bool,
) -> OfficialPresetVersionRows:
    if (
        type(version_number) is not int
        or version_number < 1
        or type(actor) is not str
        or not actor
        or actor != actor.strip()
        or len(actor) > 120
        or not isinstance(at, datetime)
    ):
        raise InvalidNarrationState("official preset row identity is invalid")
    if preset is not require_official_preset(preset.preset_id):
        raise InvalidNarrationState("official preset object is not canonical")

    rights = VoiceRightsRecord(
        id=_child_uuid(version_id, "official-preset-rights"),
        owner_id=profile.owner_id,
        workspace_id=profile.workspace_id,
        novel_id=profile.novel_id,
        source_kind="official_preset",
        source_identifier=f"qwen-tts-catalog://{preset.preset_id}",
        notice_version=OFFICIAL_PRESET_RIGHTS_POLICY_VERSION,
        purpose="private_novel_narration",
        commercial_use=False,
        redistribution=False,
        voice_cloning=False,
        subject_consent_reference=None,
        confirmed_actor=actor,
        confirmed_at=at,
        expires_at=None,
        risk_flags_json=[],
    )
    event = VoiceRightsEvent(
        id=_child_uuid(version_id, "official-preset-confirmed-event"),
        rights_record_id=rights.id,
        event_key=f"official-preset-confirmed:{version_id.hex}",
        event_type="confirmed",
        actor=actor,
        reason_code=None,
        occurred_at=at,
    )
    version = VoiceProfileVersion(
        id=version_id,
        profile_id=profile.id,
        owner_id=profile.owner_id,
        workspace_id=profile.workspace_id,
        version_number=version_number,
        source_type="preset",
        state="locked" if direct_selection else "draft",
        provider_id="qwen-tts",
        model_id=OFFICIAL_PRESET_REPOSITORY,
        model_revision=OFFICIAL_PRESET_REVISION,
        preset_key=preset.preset_id,
        reference_asset_id=None,
        preview_asset_id=None,
        rights_record_id=rights.id,
        description_digest_key_id=None,
        description_digest=None,
        language=preset.language,
        seed=OFFICIAL_PRESET_RUNTIME_INITIAL_SEED,
        parameters_json={
            "schema_version": OFFICIAL_PRESET_VERSION_SCHEMA_VERSION,
            "voice_kind": "preset",
            "provider_voice_ids": preset.provider_voice_ids,
            "official_preset": preset.provenance(),
        },
        fingerprint=(
            official_preset_direct_version_fingerprint(
                profile_id=profile.id,
                version_id=version_id,
                preset_id=preset.preset_id,
            )
            if direct_selection
            else official_preset_version_fingerprint(
                profile_id=profile.id,
                version_id=version_id,
                preset_id=preset.preset_id,
            )
        ),
        quality_state="pending",
        activation_basis=(
            "explicit_official_preset_selection"
            if direct_selection
            else "preview_confirmed"
        ),
        validation_basis="not_required" if direct_selection else "pending",
        locked_actor=None,
        locked_at=None,
        created_at=at,
    )
    return OfficialPresetVersionRows(rights=rights, event=event, version=version)


def _validate_canonical_rows(
    session: Session,
    *,
    profile: VoiceProfile,
    version: VoiceProfileVersion,
    preset: OfficialPreset,
) -> None:
    expected_version_id = official_preset_canonical_version_id(
        profile_id=profile.id,
        preset_id=preset.preset_id,
    )
    rights = session.scalar(
        select(VoiceRightsRecord)
        .where(VoiceRightsRecord.id == version.rights_record_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if rights is None:
        raise InvalidNarrationState("canonical official rights record is absent")
    try:
        validate_official_version_evidence(
            version,
            rights,
            expected_model_fingerprint=OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256,
        )
    except ValueError as error:
        raise InvalidNarrationState(
            "canonical official voice evidence is inconsistent"
        ) from error
    events = list(
        session.scalars(
            select(VoiceRightsEvent)
            .where(VoiceRightsEvent.rights_record_id == rights.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    expected_event_id = _child_uuid(
        expected_version_id,
        "official-preset-confirmed-event",
    )
    if (
        version.id != expected_version_id
        or version.profile_id != profile.id
        or version.state != "locked"
        or version.activation_basis != "explicit_official_preset_selection"
        or version.validation_basis != "not_required"
        or rights.id != _child_uuid(expected_version_id, "official-preset-rights")
        or rights.novel_id != profile.novel_id
        or rights.source_identifier != f"qwen-tts-catalog://{preset.preset_id}"
        or any(
            event.event_type in {"revoked", "expired", "review_blocked"}
            for event in events
        )
        or not any(
            event.id == expected_event_id
            and event.event_type == "confirmed"
            and event.actor == rights.confirmed_actor
            for event in events
        )
    ):
        raise InvalidNarrationState(
            "canonical official voice evidence is inconsistent"
        )


def ensure_canonical_official_preset_voice(
    session: Session,
    *,
    novel_id: UUID,
    preset_id: str,
    actor: str,
    at: datetime,
) -> CanonicalOfficialPresetVoice:
    scope = NarrationRequestScope.fixed_local()
    preset = require_official_preset(preset_id)
    profile_id = official_preset_canonical_profile_id(
        owner_id=scope.owner_id,
        workspace_id=scope.workspace_id,
        novel_id=novel_id,
        preset_id=preset.preset_id,
    )
    version_id = official_preset_canonical_version_id(
        profile_id=profile_id,
        preset_id=preset.preset_id,
    )
    profile = session.scalar(
        select(VoiceProfile)
        .where(VoiceProfile.id == profile_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if profile is None:
        profile = VoiceProfile(
            id=profile_id,
            owner_id=scope.owner_id,
            workspace_id=scope.workspace_id,
            novel_id=novel_id,
            name=preset.display_name,
            current_version_id=None,
            status="active",
            version=1,
            archived_at=None,
            created_at=at,
            updated_at=at,
        )
        session.add(profile)
        session.flush()
    elif (
        profile.owner_id != scope.owner_id
        or profile.workspace_id != scope.workspace_id
        or profile.novel_id != novel_id
    ):
        raise NarrationScopeMismatch(
            "canonical official voice profile is outside the novel scope"
        )
    elif profile.status == "unavailable":
        raise VoiceRightsUnavailable("canonical official voice is unavailable")

    versions = list(
        session.scalars(
            select(VoiceProfileVersion)
            .where(VoiceProfileVersion.profile_id == profile.id)
            .order_by(VoiceProfileVersion.version_number)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    if any(
        item.source_type != "preset" or item.preset_key != preset.preset_id
        for item in versions
    ):
        raise InvalidNarrationState(
            "canonical official profile contains a foreign voice version"
        )
    version = next((item for item in versions if item.id == version_id), None)
    if version is None:
        rows = build_official_preset_version_rows(
            profile=profile,
            preset=preset,
            version_id=version_id,
            version_number=max((item.version_number for item in versions), default=0) + 1,
            actor=actor,
            at=at,
            direct_selection=True,
        )
        session.add(rows.rights)
        session.flush()
        session.add_all([rows.event, rows.version])
        session.flush()
        version = rows.version
    _validate_canonical_rows(
        session,
        profile=profile,
        version=version,
        preset=preset,
    )
    if (
        profile.status != "active"
        or profile.archived_at is not None
        or profile.current_version_id != version.id
    ):
        profile.status = "active"
        profile.archived_at = None
        profile.current_version_id = version.id
        profile.version += 1
        profile.updated_at = at
        session.flush()
    return CanonicalOfficialPresetVoice(
        preset=preset,
        profile=profile,
        version=version,
    )
