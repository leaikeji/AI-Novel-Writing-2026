"""Immutable character-instance profile revision service."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from enum import Enum
from hashlib import sha256
import json
import re
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..creative_data_models import CharacterInstance, CharacterInstanceRevision

from .contracts import StoryStateError, StoryStateErrorCode
from .persistence import _iso, _require_novel, character_instance_payload


IdFactory = Callable[[], UUID]
Clock = Callable[[], datetime]
_OPERATION_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")


def _now() -> datetime:
    return datetime.now(UTC)


class RevisionServiceErrorCode(str, Enum):
    VERSION_CONFLICT = "version_conflict"
    REVISION_NOT_FOUND = "character_instance_revision_not_found"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    INVALID_OPERATION_KEY = "invalid_operation_key"


class RevisionServiceError(ValueError):
    def __init__(
        self,
        code: RevisionServiceErrorCode,
        message: str,
        *,
        current: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.current = current


class CharacterInstanceProfileV1(BaseModel):
    """Initial/profile attributes only; story-time changes remain StoryFacts."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    schema_version: Literal["character-instance-profile/1"] = "character-instance-profile/1"
    public_identity: str | None = Field(default=None, max_length=2_000)
    true_identity: str | None = Field(default=None, max_length=2_000)
    cover_identity: str | None = Field(default=None, max_length=2_000)
    birth_year: int | None = Field(default=None, ge=-100_000, le=100_000)
    birth_calendar_id: str | None = Field(default=None, max_length=80)
    birth_information: str | None = Field(default=None, max_length=2_000)
    occupation: str | None = Field(default=None, max_length=2_000)
    personality: str | None = Field(default=None, max_length=4_000)
    goals: tuple[str, ...] = ()
    flaws: tuple[str, ...] = ()
    secrets: tuple[str, ...] = ()
    growth_direction: str | None = Field(default=None, max_length=4_000)

    @field_validator("goals", "flaws", "secrets")
    @classmethod
    def validate_unique_items(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(item.strip() for item in value if item.strip())
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("profile list fields must not contain duplicates")
        return cleaned


def _validate_operation_key(operation_key: str) -> str:
    cleaned = operation_key.strip()
    if not _OPERATION_KEY_RE.fullmatch(cleaned):
        raise RevisionServiceError(
            RevisionServiceErrorCode.INVALID_OPERATION_KEY,
            "operation_key must be 1-120 safe ASCII characters",
        )
    return cleaned


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def character_instance_revision_payload(
    row: CharacterInstanceRevision,
) -> dict[str, object]:
    return {
        "id": str(row.id),
        "novel_id": str(row.novel_id),
        "character_instance_id": str(row.character_instance_id),
        "revision_number": row.revision_number,
        "parent_revision_id": str(row.parent_revision_id) if row.parent_revision_id else None,
        "restored_from_revision_id": (
            str(row.restored_from_revision_id) if row.restored_from_revision_id else None
        ),
        "source_kind": row.source_kind,
        "operation_key": row.operation_key,
        "profile_schema_version": row.profile_schema_version,
        "profile": dict(row.profile_json or {}),
        "change_set": dict(row.change_set_json or {}),
        "content_hash": row.content_hash,
        "created_at": _iso(row.created_at),
    }


def _instance_revisions(
    session: Session,
    novel_id: UUID,
    instance_id: UUID,
    *,
    for_update: bool,
) -> list[CharacterInstanceRevision]:
    statement = (
        select(CharacterInstanceRevision)
        .where(
            CharacterInstanceRevision.novel_id == novel_id,
            CharacterInstanceRevision.character_instance_id == instance_id,
        )
        .order_by(CharacterInstanceRevision.revision_number, CharacterInstanceRevision.id)
    )
    if for_update:
        statement = statement.with_for_update()
    return list(session.scalars(statement))


def _locked_instance(
    session: Session,
    novel_id: UUID,
    instance_id: UUID,
) -> CharacterInstance:
    row = session.scalar(
        select(CharacterInstance)
        .where(
            CharacterInstance.id == instance_id,
            CharacterInstance.novel_id == novel_id,
        )
        .with_for_update()
    )
    if row is None:
        raise StoryStateError(
            StoryStateErrorCode.CHARACTER_INSTANCE_NOT_FOUND,
            "character instance was not found in the novel",
        )
    return row


def _changed_fields(
    previous: dict[str, object], current: dict[str, object]
) -> list[str]:
    return sorted(
        key for key in set(previous) | set(current) if previous.get(key) != current.get(key)
    )


def _append_revision(
    session: Session,
    *,
    novel,
    instance: CharacterInstance,
    revisions: list[CharacterInstanceRevision],
    expected_story_ledger_version: int,
    expected_instance_version: int,
    operation_key: str,
    operation_hash: str,
    profile_schema_version: int,
    profile_json: dict[str, object],
    source_kind: str,
    restored_from_revision_id: UUID | None,
    id_factory: IdFactory,
    clock: Clock,
) -> dict[str, object]:
    replay = next((row for row in revisions if row.operation_key == operation_key), None)
    if replay is not None:
        if replay.operation_hash != operation_hash:
            raise RevisionServiceError(
                RevisionServiceErrorCode.IDEMPOTENCY_CONFLICT,
                "operation_key was already used with another revision payload",
            )
        return {
            "revision": character_instance_revision_payload(replay),
            "instance": character_instance_payload(instance),
            "story_ledger_version": novel.story_ledger_version,
            "replayed": True,
        }
    if novel.story_ledger_version != expected_story_ledger_version:
        raise RevisionServiceError(
            RevisionServiceErrorCode.VERSION_CONFLICT,
            "story ledger version changed",
            current={"story_ledger_version": novel.story_ledger_version},
        )
    if instance.version != expected_instance_version:
        raise RevisionServiceError(
            RevisionServiceErrorCode.VERSION_CONFLICT,
            "character instance version changed",
            current=character_instance_payload(instance),
        )
    current_revision = next(
        (row for row in revisions if row.id == instance.current_revision_id), None
    )
    if instance.current_revision_id is not None and current_revision is None:
        raise RevisionServiceError(
            RevisionServiceErrorCode.REVISION_NOT_FOUND,
            "current character instance revision is outside the novel scope",
        )
    previous_profile = dict(current_revision.profile_json or {}) if current_revision else {}
    row = CharacterInstanceRevision(
        id=id_factory(),
        novel_id=instance.novel_id,
        character_instance_id=instance.id,
        revision_number=max((item.revision_number for item in revisions), default=0) + 1,
        parent_revision_id=instance.current_revision_id,
        restored_from_revision_id=restored_from_revision_id,
        source_kind=source_kind,
        operation_key=operation_key,
        operation_hash=operation_hash,
        profile_schema_version=profile_schema_version,
        profile_json=profile_json,
        change_set_json={"changed_fields": _changed_fields(previous_profile, profile_json)},
        content_hash=_canonical_hash(profile_json),
        created_at=clock(),
    )
    session.add(row)
    instance.current_revision_id = row.id
    instance.version += 1
    instance.updated_at = clock()
    novel.story_ledger_version += 1
    session.flush()
    return {
        "revision": character_instance_revision_payload(row),
        "instance": character_instance_payload(instance),
        "story_ledger_version": novel.story_ledger_version,
        "replayed": False,
    }


def save_character_instance_profile(
    session: Session,
    novel_id: UUID,
    instance_id: UUID,
    *,
    expected_story_ledger_version: int,
    expected_instance_version: int,
    operation_key: str,
    profile: CharacterInstanceProfileV1,
    source_kind: Literal["manual", "ai_adopt"] = "manual",
    id_factory: IdFactory = uuid4,
    clock: Clock = _now,
) -> dict[str, object]:
    novel = _require_novel(session, novel_id, for_update=True)
    instance = _locked_instance(session, novel_id, instance_id)
    revisions = _instance_revisions(session, novel_id, instance_id, for_update=True)
    key = _validate_operation_key(operation_key)
    profile_json = profile.model_dump(mode="json", exclude_none=True)
    operation_hash = _canonical_hash(
        {"action": "save", "source_kind": source_kind, "profile": profile_json}
    )
    return _append_revision(
        session,
        novel=novel,
        instance=instance,
        revisions=revisions,
        expected_story_ledger_version=expected_story_ledger_version,
        expected_instance_version=expected_instance_version,
        operation_key=key,
        operation_hash=operation_hash,
        profile_schema_version=1,
        profile_json=profile_json,
        source_kind=source_kind,
        restored_from_revision_id=None,
        id_factory=id_factory,
        clock=clock,
    )


def restore_character_instance_profile(
    session: Session,
    novel_id: UUID,
    instance_id: UUID,
    target_revision_id: UUID,
    *,
    expected_story_ledger_version: int,
    expected_instance_version: int,
    operation_key: str,
    id_factory: IdFactory = uuid4,
    clock: Clock = _now,
) -> dict[str, object]:
    novel = _require_novel(session, novel_id, for_update=True)
    instance = _locked_instance(session, novel_id, instance_id)
    revisions = _instance_revisions(session, novel_id, instance_id, for_update=True)
    target = next((row for row in revisions if row.id == target_revision_id), None)
    if target is None:
        raise RevisionServiceError(
            RevisionServiceErrorCode.REVISION_NOT_FOUND,
            "target character instance revision was not found in the novel",
        )
    key = _validate_operation_key(operation_key)
    operation_hash = _canonical_hash(
        {
            "action": "restore",
            "target_revision_id": str(target.id),
            "target_content_hash": target.content_hash,
        }
    )
    return _append_revision(
        session,
        novel=novel,
        instance=instance,
        revisions=revisions,
        expected_story_ledger_version=expected_story_ledger_version,
        expected_instance_version=expected_instance_version,
        operation_key=key,
        operation_hash=operation_hash,
        profile_schema_version=target.profile_schema_version,
        profile_json=dict(target.profile_json or {}),
        source_kind="restore",
        restored_from_revision_id=target.id,
        id_factory=id_factory,
        clock=clock,
    )


def list_character_instance_profile_history(
    session: Session,
    novel_id: UUID,
    instance_id: UUID,
) -> list[dict[str, object]]:
    instance = session.scalar(
        select(CharacterInstance).where(
            CharacterInstance.id == instance_id,
            CharacterInstance.novel_id == novel_id,
        )
    )
    if instance is None:
        raise StoryStateError(
            StoryStateErrorCode.CHARACTER_INSTANCE_NOT_FOUND,
            "character instance was not found in the novel",
        )
    rows = _instance_revisions(session, novel_id, instance_id, for_update=False)
    return [
        {
            **character_instance_revision_payload(row),
            "is_current": row.id == instance.current_revision_id,
        }
        for row in reversed(rows)
    ]


def get_character_instance_profile(
    session: Session,
    novel_id: UUID,
    instance_id: UUID,
) -> dict[str, object]:
    instance = session.scalar(
        select(CharacterInstance).where(
            CharacterInstance.id == instance_id,
            CharacterInstance.novel_id == novel_id,
        )
    )
    if instance is None:
        raise StoryStateError(
            StoryStateErrorCode.CHARACTER_INSTANCE_NOT_FOUND,
            "character instance was not found in the novel",
        )
    if instance.current_revision_id is None:
        return {"instance": character_instance_payload(instance), "revision": None}
    revision = session.scalar(
        select(CharacterInstanceRevision).where(
            CharacterInstanceRevision.id == instance.current_revision_id,
            CharacterInstanceRevision.character_instance_id == instance.id,
            CharacterInstanceRevision.novel_id == novel_id,
        )
    )
    if revision is None:
        raise RevisionServiceError(
            RevisionServiceErrorCode.REVISION_NOT_FOUND,
            "current character instance revision was not found in the novel",
        )
    return {
        "instance": character_instance_payload(instance),
        "revision": character_instance_revision_payload(revision),
    }
