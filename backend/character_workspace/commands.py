"""Atomic write commands for the formal character workspace."""

from __future__ import annotations

from hashlib import sha256
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..creative_authority import save_character_root
from ..creative_data_models import CharacterInstance, StoryTimeline
from ..creative_services import validate_character_root_update
from ..models import Novel, NovelCharacter
from ..services import NotFoundError, ValidationError
from ..story_state.revisions import (
    CharacterInstanceProfile,
    save_character_instance_profile,
)


def _child_operation_key(operation_key: str, component: str) -> str:
    digest = sha256(operation_key.encode("utf-8")).hexdigest()
    return f"cw2:{component}:{digest}"


def save_character_workspace(
    session: Session,
    novel_id: UUID,
    character_id: UUID,
    *,
    selected_timeline_id: UUID,
    selected_instance_id: UUID,
    operation_key: str,
    expected_character_catalog_version: int,
    expected_story_ledger_version: int,
    expected_character_version: int,
    expected_instance_version: int,
    root_patch: Mapping[str, Any] | None,
    profile: CharacterInstanceProfile | None,
) -> dict[str, object]:
    """Save root and selected instance in one caller-owned transaction.

    Lock order is stable across both aggregates: novel, character, instance,
    then the immutable revision collections locked by the authority services.
    CAS is applied only to aggregates that are actually changing.
    """

    novel = session.scalar(
        select(Novel).where(Novel.id == novel_id).with_for_update()
    )
    if novel is None:
        raise NotFoundError(f"novel {novel_id} not found")
    character = session.scalar(
        select(NovelCharacter)
        .where(
            NovelCharacter.id == character_id,
            NovelCharacter.novel_id == novel_id,
        )
        .with_for_update()
    )
    if character is None:
        raise NotFoundError(f"character {character_id} not found")
    instance = session.scalar(
        select(CharacterInstance)
        .where(
            CharacterInstance.id == selected_instance_id,
            CharacterInstance.novel_id == novel_id,
            CharacterInstance.character_id == character_id,
        )
        .with_for_update()
    )
    if instance is None or instance.lifecycle_state != "active":
        raise ValidationError("所选人物实例不存在、已归档或不属于当前人物")
    timeline = session.scalar(
        select(StoryTimeline).where(
            StoryTimeline.id == selected_timeline_id,
            StoryTimeline.novel_id == novel_id,
            StoryTimeline.lifecycle_state == "active",
        )
    )
    if timeline is None:
        raise ValidationError("所选时间线不存在或已失效")

    if root_patch is None and profile is None:
        return {
            "no_changes": True,
            "root_replayed": False,
            "profile_replayed": False,
        }

    root_replayed = False
    profile_replayed = False
    if root_patch is not None:
        validated = validate_character_root_update(
            session,
            character,
            role_type=str(root_patch["role_type"]),
            name=str(root_patch["name"]),
            description=str(root_patch.get("description") or ""),
            details_patch={
                "gender": root_patch.get("gender", ""),
                "core_theme": root_patch.get("core_theme", ""),
            },
        )
        root_result = save_character_root(
            session,
            novel_id,
            character_id,
            expected_catalog_version=expected_character_catalog_version,
            expected_character_version=expected_character_version,
            operation_key=_child_operation_key(operation_key, "root"),
            source_kind="manual",
            role_type=validated["role_type"],
            name=validated["name"],
            description=validated["description"],
            details=validated["details"],
            lifecycle_state=character.lifecycle_state,
            position=character.position,
            change_set={
                "edited_fields": [
                    "role_type",
                    "name",
                    "description",
                    "details.gender",
                    "details.core_theme",
                ]
            },
        )
        root_replayed = root_result.replayed

    if profile is not None:
        profile_result = save_character_instance_profile(
            session,
            novel_id,
            selected_instance_id,
            expected_story_ledger_version=expected_story_ledger_version,
            expected_instance_version=expected_instance_version,
            operation_key=_child_operation_key(operation_key, "profile"),
            profile=profile,
            source_kind="manual",
        )
        profile_replayed = bool(profile_result["replayed"])

    return {
        "no_changes": False,
        "root_replayed": root_replayed,
        "profile_replayed": profile_replayed,
    }


__all__ = ["save_character_workspace"]
