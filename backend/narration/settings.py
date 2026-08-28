"""CAS updates for mutable per-novel narration settings."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from ..models import NovelNarrationSettings, VoiceProfile, VoiceProfileVersion

from .services import (
    NarrationCasConflict,
    NarrationScopeMismatch,
    NarrationServiceError,
    NarrationStore,
    canonical_payload,
    require_local_novel,
    require_row,
    require_same_novel,
    utc_now,
)


@dataclass(frozen=True, slots=True)
class NarrationSettingsUpdate:
    novel_id: UUID
    script_review_policy: str
    analysis_mode: str
    settings_json: dict[str, object]
    expected_version: int
    narrator_profile_id: UUID | None = None
    narrator_version_id: UUID | None = None


def update_settings(
    store: NarrationStore, command: NarrationSettingsUpdate
) -> NovelNarrationSettings:
    # Every settings/override mutation and settings snapshot shares the Novel
    # row as its aggregate mutex.  This closes the first-row/phantom window when
    # a snapshot is created concurrently with the initial settings write.
    require_local_novel(store, command.novel_id, for_update=True)
    if command.script_review_policy not in {"blockers_only", "always_review"}:
        raise NarrationServiceError("unsupported script review policy")
    if command.analysis_mode not in {"local_rules_only", "cloud_assisted"}:
        raise NarrationServiceError("unsupported analysis mode")
    if (command.narrator_profile_id is None) != (command.narrator_version_id is None):
        raise NarrationServiceError("narrator profile and version must be set together")
    if command.narrator_profile_id:
        profile = require_row(
            store.get(VoiceProfile, command.narrator_profile_id), label="narrator profile"
        )
        version = require_row(
            store.get(VoiceProfileVersion, command.narrator_version_id),
            label="narrator voice version",
        )
        if profile.owner_id != version.owner_id or profile.workspace_id != version.workspace_id:
            raise NarrationScopeMismatch("narrator profile/version scope mismatch")
        if profile.novel_id not in {None, command.novel_id}:
            raise NarrationScopeMismatch("narrator profile belongs to another novel")
        if version.profile_id != profile.id:
            raise NarrationScopeMismatch("narrator version belongs to another profile")

    now = utc_now()
    row = store.find_one(
        NovelNarrationSettings, novel_id=command.novel_id, for_update=True
    )
    if row is None:
        if command.expected_version != 0:
            raise NarrationCasConflict("settings do not exist at expected version")
        row = NovelNarrationSettings(
            id=uuid4(),
            novel_id=command.novel_id,
            narrator_profile_id=command.narrator_profile_id,
            narrator_version_id=command.narrator_version_id,
            script_review_policy=command.script_review_policy,
            analysis_mode=command.analysis_mode,
            settings_json=canonical_payload(command.settings_json),
            version=1,
            updated_at=now,
        )
        store.add(row)
    else:
        require_same_novel(row.novel_id, command.novel_id, label="narration settings")
        if row.version != command.expected_version:
            raise NarrationCasConflict("narration settings version changed")
        row.narrator_profile_id = command.narrator_profile_id
        row.narrator_version_id = command.narrator_version_id
        row.script_review_policy = command.script_review_policy
        row.analysis_mode = command.analysis_mode
        row.settings_json = canonical_payload(command.settings_json)
        row.version = command.expected_version + 1
        row.updated_at = now
    store.flush()
    return row


__all__ = ["NarrationSettingsUpdate", "update_settings"]
