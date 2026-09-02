from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Generic, TypeVar
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..creative_data_models import (
    NovelCharacterRevision,
    NovelOutlineHead,
    NovelOutlineRevision,
    NovelSettingHead,
    NovelSettingRevision,
)
from ..models import CharacterAlias, Novel, NovelCharacter
from ..narration.aliases import normalize_character_alias

from .errors import (
    AuthorityConflictError,
    AuthorityIdempotencyConflict,
    AuthorityNotFoundError,
    AuthorityValidationError,
)
from .hashing import canonical_hash


RevisionT = TypeVar("RevisionT")
HeadT = TypeVar("HeadT")


@dataclass(frozen=True, slots=True)
class AuthorityWriteResult(Generic[RevisionT, HeadT]):
    revision: RevisionT
    head: HeadT
    replayed: bool


@dataclass(frozen=True, slots=True)
class CharacterRevisionResult:
    revision: NovelCharacterRevision
    character: NovelCharacter
    catalog_version: int
    replayed: bool


_SETTING_PROJECTION_FIELDS = (
    "author_name",
    "writing_type",
    "audience",
    "genre",
    "subgenre",
    "idea",
    "template_key",
    "template_name",
    "template_data",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _required_text(value: str, *, field: str, maximum: int) -> str:
    normalized = str(value).strip()
    if not normalized or len(normalized) > maximum:
        raise AuthorityValidationError(f"{field} must contain 1 to {maximum} characters")
    return normalized


def _json_dict(value: dict[str, Any], *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AuthorityValidationError(f"{field} must be an object")
    copied = deepcopy(value)
    canonical_hash(copied)
    return copied


def _json_list_of_dicts(
    value: list[dict[str, Any]], *, field: str
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise AuthorityValidationError(f"{field} must be an array of objects")
    copied = deepcopy(value)
    canonical_hash(copied)
    return copied


def _lock_novel(session: Session, novel_id: UUID) -> Novel:
    novel = session.scalar(
        select(Novel).where(Novel.id == novel_id).with_for_update()
    )
    if novel is None:
        raise AuthorityNotFoundError(f"novel {novel_id} not found")
    return novel


def _outline_content(
    *,
    target_chapter_count: int,
    background_text: str,
    plot_text: str,
    highlight_text: str,
    character_revision_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    if isinstance(target_chapter_count, bool) or target_chapter_count <= 0:
        raise AuthorityValidationError("target_chapter_count must be positive")
    refs = _json_list_of_dicts(
        character_revision_refs, field="character_revision_refs"
    )
    return {
        "target_chapter_count": target_chapter_count,
        "background_text": str(background_text),
        "plot_text": str(plot_text),
        "highlight_text": str(highlight_text),
        "character_revision_refs": refs,
    }


def _outline_request(
    *,
    content: dict[str, Any],
    change_set: dict[str, Any],
    source_kind: str,
    source_job_id: UUID | None,
    restored_from_revision_id: UUID | None,
) -> dict[str, Any]:
    return {
        "operation": "restore" if restored_from_revision_id else "save",
        "source_kind": source_kind,
        "source_job_id": source_job_id,
        "restored_from_revision_id": restored_from_revision_id,
        "content": content,
        "change_set": change_set,
    }


def _outline_head(
    session: Session, novel_id: UUID, *, for_update: bool
) -> NovelOutlineHead | None:
    statement = select(NovelOutlineHead).where(NovelOutlineHead.novel_id == novel_id)
    if for_update:
        statement = statement.with_for_update()
    return session.scalar(statement)


def _outline_idempotent_revision(
    session: Session, novel_id: UUID, idempotency_key: str
) -> NovelOutlineRevision | None:
    return session.scalar(
        select(NovelOutlineRevision).where(
            NovelOutlineRevision.novel_id == novel_id,
            NovelOutlineRevision.idempotency_key == idempotency_key,
        )
    )


def _outline_current_revision(
    session: Session, head: NovelOutlineHead
) -> NovelOutlineRevision:
    revision = session.get(NovelOutlineRevision, head.current_revision_id)
    if revision is None or revision.novel_id != head.novel_id:
        raise AuthorityConflictError(
            "outline_head_invalid",
            current={"head_version": int(head.version)},
        )
    return revision


def save_outline(
    session: Session,
    novel_id: UUID,
    *,
    expected_head_version: int,
    idempotency_key: str,
    source_kind: str,
    target_chapter_count: int,
    background_text: str,
    plot_text: str,
    highlight_text: str,
    character_revision_refs: list[dict[str, Any]] | None = None,
    change_set: dict[str, Any] | None = None,
    source_job_id: UUID | None = None,
) -> AuthorityWriteResult[NovelOutlineRevision, NovelOutlineHead]:
    return _write_outline(
        session,
        novel_id,
        expected_head_version=expected_head_version,
        idempotency_key=idempotency_key,
        source_kind=source_kind,
        content=_outline_content(
            target_chapter_count=target_chapter_count,
            background_text=background_text,
            plot_text=plot_text,
            highlight_text=highlight_text,
            character_revision_refs=character_revision_refs or [],
        ),
        change_set=change_set or {},
        source_job_id=source_job_id,
        restored_from_revision_id=None,
    )


def restore_outline(
    session: Session,
    novel_id: UUID,
    revision_id: UUID,
    *,
    expected_head_version: int,
    idempotency_key: str,
) -> AuthorityWriteResult[NovelOutlineRevision, NovelOutlineHead]:
    _lock_novel(session, novel_id)
    target = session.get(NovelOutlineRevision, revision_id)
    if target is None or target.novel_id != novel_id:
        raise AuthorityNotFoundError(f"outline revision {revision_id} not found")
    return _write_outline(
        session,
        novel_id,
        expected_head_version=expected_head_version,
        idempotency_key=idempotency_key,
        source_kind="restore",
        content=_outline_content(
            target_chapter_count=target.target_chapter_count,
            background_text=target.background_text,
            plot_text=target.plot_text,
            highlight_text=target.highlight_text,
            character_revision_refs=list(target.character_revision_refs_json or []),
        ),
        change_set={"restored_from_revision_id": str(target.id)},
        source_job_id=None,
        restored_from_revision_id=target.id,
        novel_already_locked=True,
    )


def _write_outline(
    session: Session,
    novel_id: UUID,
    *,
    expected_head_version: int,
    idempotency_key: str,
    source_kind: str,
    content: dict[str, Any],
    change_set: dict[str, Any],
    source_job_id: UUID | None,
    restored_from_revision_id: UUID | None,
    novel_already_locked: bool = False,
) -> AuthorityWriteResult[NovelOutlineRevision, NovelOutlineHead]:
    if isinstance(expected_head_version, bool) or expected_head_version < 0:
        raise AuthorityValidationError("expected_head_version must be non-negative")
    key = _required_text(idempotency_key, field="idempotency_key", maximum=160)
    source = _required_text(source_kind, field="source_kind", maximum=40)
    changes = _json_dict(change_set, field="change_set")
    request_hash = canonical_hash(
        _outline_request(
            content=content,
            change_set=changes,
            source_kind=source,
            source_job_id=source_job_id,
            restored_from_revision_id=restored_from_revision_id,
        )
    )
    novel = (
        session.get(Novel, novel_id)
        if novel_already_locked
        else _lock_novel(session, novel_id)
    )
    if novel is None:
        raise AuthorityNotFoundError(f"novel {novel_id} not found")
    existing = _outline_idempotent_revision(session, novel_id, key)
    head = _outline_head(session, novel_id, for_update=True)
    if existing is not None:
        if existing.request_hash != request_hash:
            raise AuthorityIdempotencyConflict(key)
        if head is None:
            raise AuthorityConflictError("outline_head_missing", current={})
        return AuthorityWriteResult(existing, head, True)
    current_version = int(head.version) if head is not None else 0
    if current_version != expected_head_version:
        raise AuthorityConflictError(
            "outline_head_version_conflict",
            current={
                "head_version": current_version,
                "current_revision_id": str(head.current_revision_id) if head else None,
            },
        )
    parent = _outline_current_revision(session, head) if head is not None else None
    refs = list(content["character_revision_refs"])
    now = _now()
    revision = NovelOutlineRevision(
        id=uuid4(),
        novel_id=novel_id,
        revision_number=(int(parent.revision_number) + 1 if parent else 1),
        parent_revision_id=parent.id if parent else None,
        restored_from_revision_id=restored_from_revision_id,
        source_kind=source,
        source_job_id=source_job_id,
        idempotency_key=key,
        request_hash=request_hash,
        target_chapter_count=int(content["target_chapter_count"]),
        background_text=str(content["background_text"]),
        plot_text=str(content["plot_text"]),
        highlight_text=str(content["highlight_text"]),
        character_revision_refs_json=deepcopy(refs),
        character_reference_digest=canonical_hash(refs),
        change_set_json=changes,
        content_hash=canonical_hash(content),
        created_at=now,
    )
    session.add(revision)
    if head is None:
        head = NovelOutlineHead(
            novel_id=novel_id,
            current_revision_id=revision.id,
            version=1,
            established_at=now,
            establishment_source=source,
            updated_at=now,
        )
        session.add(head)
    else:
        head.current_revision_id = revision.id
        head.version = current_version + 1
        head.updated_at = now
    novel.outline_target_chapters = revision.target_chapter_count
    novel.background = revision.background_text
    novel.main_plot = revision.plot_text
    novel.highlight = revision.highlight_text
    novel.version = int(novel.version) + 1
    session.flush()
    from ..embedding.indexing import SourceRefreshHint, request_active_novel_refresh
    request_active_novel_refresh(
        session,
        novel_id,
        source_hints=(SourceRefreshHint("outline_revision", novel_id),),
    )
    return AuthorityWriteResult(revision, head, False)


def get_outline(
    session: Session, novel_id: UUID
) -> tuple[NovelOutlineHead, NovelOutlineRevision] | None:
    head = _outline_head(session, novel_id, for_update=False)
    if head is None:
        return None
    return head, _outline_current_revision(session, head)


def list_outline_history(
    session: Session,
    novel_id: UUID,
    *,
    before_revision_number: int | None = None,
    limit: int = 100,
) -> list[NovelOutlineRevision]:
    if isinstance(limit, bool) or not 1 <= limit <= 500:
        raise AuthorityValidationError("limit must be between 1 and 500")
    statement = select(NovelOutlineRevision).where(
        NovelOutlineRevision.novel_id == novel_id
    )
    if before_revision_number is not None:
        statement = statement.where(
            NovelOutlineRevision.revision_number < before_revision_number
        )
    return list(
        session.scalars(
            statement.order_by(NovelOutlineRevision.revision_number.desc()).limit(limit)
        ).all()
    )


def _setting_content(
    *, schema_id: str, schema_version: int, settings: dict[str, Any]
) -> dict[str, Any]:
    if isinstance(schema_version, bool) or schema_version <= 0:
        raise AuthorityValidationError("schema_version must be positive")
    return {
        "schema_id": _required_text(schema_id, field="schema_id", maximum=80),
        "schema_version": schema_version,
        "settings": _json_dict(settings, field="settings"),
    }


def _setting_head(
    session: Session, novel_id: UUID, *, for_update: bool
) -> NovelSettingHead | None:
    statement = select(NovelSettingHead).where(NovelSettingHead.novel_id == novel_id)
    if for_update:
        statement = statement.with_for_update()
    return session.scalar(statement)


def _setting_idempotent_revision(
    session: Session, novel_id: UUID, idempotency_key: str
) -> NovelSettingRevision | None:
    return session.scalar(
        select(NovelSettingRevision).where(
            NovelSettingRevision.novel_id == novel_id,
            NovelSettingRevision.idempotency_key == idempotency_key,
        )
    )


def _setting_current_revision(
    session: Session, head: NovelSettingHead
) -> NovelSettingRevision:
    revision = session.get(NovelSettingRevision, head.current_revision_id)
    if revision is None or revision.novel_id != head.novel_id:
        raise AuthorityConflictError(
            "setting_head_invalid", current={"head_version": int(head.version)}
        )
    return revision


def save_settings(
    session: Session,
    novel_id: UUID,
    *,
    expected_head_version: int,
    idempotency_key: str,
    source_kind: str,
    schema_id: str,
    schema_version: int,
    settings: dict[str, Any],
    change_set: dict[str, Any] | None = None,
    source_job_id: UUID | None = None,
) -> AuthorityWriteResult[NovelSettingRevision, NovelSettingHead]:
    return _write_settings(
        session,
        novel_id,
        expected_head_version=expected_head_version,
        idempotency_key=idempotency_key,
        source_kind=source_kind,
        content=_setting_content(
            schema_id=schema_id, schema_version=schema_version, settings=settings
        ),
        change_set=change_set or {},
        source_job_id=source_job_id,
        restored_from_revision_id=None,
    )


def restore_settings(
    session: Session,
    novel_id: UUID,
    revision_id: UUID,
    *,
    expected_head_version: int,
    idempotency_key: str,
) -> AuthorityWriteResult[NovelSettingRevision, NovelSettingHead]:
    _lock_novel(session, novel_id)
    target = session.get(NovelSettingRevision, revision_id)
    if target is None or target.novel_id != novel_id:
        raise AuthorityNotFoundError(f"setting revision {revision_id} not found")
    return _write_settings(
        session,
        novel_id,
        expected_head_version=expected_head_version,
        idempotency_key=idempotency_key,
        source_kind="restore",
        content=_setting_content(
            schema_id=target.schema_id,
            schema_version=target.schema_version,
            settings=dict(target.settings_json or {}),
        ),
        change_set={"restored_from_revision_id": str(target.id)},
        source_job_id=None,
        restored_from_revision_id=target.id,
        novel_already_locked=True,
    )


def _write_settings(
    session: Session,
    novel_id: UUID,
    *,
    expected_head_version: int,
    idempotency_key: str,
    source_kind: str,
    content: dict[str, Any],
    change_set: dict[str, Any],
    source_job_id: UUID | None,
    restored_from_revision_id: UUID | None,
    novel_already_locked: bool = False,
) -> AuthorityWriteResult[NovelSettingRevision, NovelSettingHead]:
    if isinstance(expected_head_version, bool) or expected_head_version < 0:
        raise AuthorityValidationError("expected_head_version must be non-negative")
    key = _required_text(idempotency_key, field="idempotency_key", maximum=160)
    source = _required_text(source_kind, field="source_kind", maximum=40)
    changes = _json_dict(change_set, field="change_set")
    request_hash = canonical_hash(
        {
            "operation": "restore" if restored_from_revision_id else "save",
            "source_kind": source,
            "source_job_id": source_job_id,
            "restored_from_revision_id": restored_from_revision_id,
            "content": content,
            "change_set": changes,
        }
    )
    novel = (
        session.get(Novel, novel_id)
        if novel_already_locked
        else _lock_novel(session, novel_id)
    )
    if novel is None:
        raise AuthorityNotFoundError(f"novel {novel_id} not found")
    existing = _setting_idempotent_revision(session, novel_id, key)
    head = _setting_head(session, novel_id, for_update=True)
    if existing is not None:
        if existing.request_hash != request_hash:
            raise AuthorityIdempotencyConflict(key)
        if head is None:
            raise AuthorityConflictError("setting_head_missing", current={})
        return AuthorityWriteResult(existing, head, True)
    current_version = int(head.version) if head is not None else 0
    if current_version != expected_head_version:
        raise AuthorityConflictError(
            "setting_head_version_conflict",
            current={
                "head_version": current_version,
                "current_revision_id": str(head.current_revision_id) if head else None,
            },
        )
    parent = _setting_current_revision(session, head) if head is not None else None
    now = _now()
    revision = NovelSettingRevision(
        id=uuid4(),
        novel_id=novel_id,
        revision_number=(int(parent.revision_number) + 1 if parent else 1),
        parent_revision_id=parent.id if parent else None,
        restored_from_revision_id=restored_from_revision_id,
        source_kind=source,
        source_job_id=source_job_id,
        idempotency_key=key,
        request_hash=request_hash,
        schema_id=str(content["schema_id"]),
        schema_version=int(content["schema_version"]),
        settings_json=deepcopy(content["settings"]),
        change_set_json=changes,
        content_hash=canonical_hash(content),
        created_at=now,
    )
    session.add(revision)
    if head is None:
        head = NovelSettingHead(
            novel_id=novel_id,
            current_revision_id=revision.id,
            version=1,
            established_at=now,
            establishment_source=source,
            updated_at=now,
        )
        session.add(head)
    else:
        head.current_revision_id = revision.id
        head.version = current_version + 1
        head.updated_at = now
    for field in _SETTING_PROJECTION_FIELDS:
        if field in revision.settings_json:
            setattr(novel, field, deepcopy(revision.settings_json[field]))
    novel.version = int(novel.version) + 1
    session.flush()
    from ..embedding.indexing import SourceRefreshHint, request_active_novel_refresh
    request_active_novel_refresh(
        session,
        novel_id,
        source_hints=(SourceRefreshHint("setting_revision", novel_id),),
    )
    return AuthorityWriteResult(revision, head, False)


def get_settings(
    session: Session, novel_id: UUID
) -> tuple[NovelSettingHead, NovelSettingRevision] | None:
    head = _setting_head(session, novel_id, for_update=False)
    if head is None:
        return None
    return head, _setting_current_revision(session, head)


def list_settings_history(
    session: Session,
    novel_id: UUID,
    *,
    before_revision_number: int | None = None,
    limit: int = 100,
) -> list[NovelSettingRevision]:
    if isinstance(limit, bool) or not 1 <= limit <= 500:
        raise AuthorityValidationError("limit must be between 1 and 500")
    statement = select(NovelSettingRevision).where(
        NovelSettingRevision.novel_id == novel_id
    )
    if before_revision_number is not None:
        statement = statement.where(
            NovelSettingRevision.revision_number < before_revision_number
        )
    return list(
        session.scalars(
            statement.order_by(NovelSettingRevision.revision_number.desc()).limit(limit)
        ).all()
    )


def _character_content(
    *,
    role_type: str,
    name: str,
    description: str,
    details: dict[str, Any],
    lifecycle_state: str,
    position: int,
) -> dict[str, Any]:
    if isinstance(position, bool):
        raise AuthorityValidationError("position must be an integer")
    return {
        "role_type": _required_text(role_type, field="role_type", maximum=30),
        "name": _required_text(name, field="name", maximum=240),
        "description": str(description),
        "details": _json_dict(details, field="details"),
        "lifecycle_state": _required_text(
            lifecycle_state, field="lifecycle_state", maximum=30
        ),
        "position": int(position),
    }


def _lock_character(
    session: Session, novel_id: UUID, character_id: UUID
) -> NovelCharacter:
    character = session.scalar(
        select(NovelCharacter)
        .where(
            NovelCharacter.id == character_id,
            NovelCharacter.novel_id == novel_id,
        )
        .with_for_update()
    )
    if character is None:
        raise AuthorityNotFoundError(f"character {character_id} not found")
    return character


def _character_operation(
    session: Session,
    novel_id: UUID,
    character_id: UUID,
    operation_key: str,
) -> NovelCharacterRevision | None:
    return session.scalar(
        select(NovelCharacterRevision).where(
            NovelCharacterRevision.novel_id == novel_id,
            NovelCharacterRevision.character_id == character_id,
            NovelCharacterRevision.operation_key == operation_key,
        )
    )


def _latest_character_revision(
    session: Session, novel_id: UUID, character_id: UUID
) -> NovelCharacterRevision | None:
    return session.scalar(
        select(NovelCharacterRevision)
        .where(
            NovelCharacterRevision.novel_id == novel_id,
            NovelCharacterRevision.character_id == character_id,
        )
        .order_by(NovelCharacterRevision.character_version.desc())
        .limit(1)
    )


def _upsert_authority_alias(
    session: Session,
    *,
    character: NovelCharacter,
    revision: NovelCharacterRevision,
    alias: str,
    alias_kind: str,
) -> CharacterAlias:
    normalized = normalize_character_alias(alias)
    existing = session.scalar(
        select(CharacterAlias).where(
            CharacterAlias.character_id == character.id,
            CharacterAlias.normalized_alias == normalized,
        )
    )
    if existing is None:
        existing = CharacterAlias(
            id=uuid4(),
            novel_id=character.novel_id,
            character_id=character.id,
            alias=alias,
            normalized_alias=normalized,
            alias_kind=alias_kind,
            identity_layer="public",
            source="character_authority",
            source_character_revision_id=revision.id,
            lifecycle_state="active",
        )
        session.add(existing)
    else:
        existing.alias = alias
        existing.alias_kind = alias_kind
        existing.identity_layer = existing.identity_layer or "public"
        existing.source = "character_authority"
        existing.source_character_revision_id = revision.id
    return existing


def _refresh_authority_alias_states(
    session: Session,
    *,
    novel_id: UUID,
    normalized_aliases: set[str],
) -> None:
    """Make alias ambiguity explicit; never choose one character by recency."""

    for normalized in normalized_aliases:
        rows = list(
            session.scalars(
                select(CharacterAlias).where(
                    CharacterAlias.novel_id == novel_id,
                    CharacterAlias.normalized_alias == normalized,
                )
            )
        )
        active_character_ids = {
            item.id
            for item in session.scalars(
                select(NovelCharacter).where(
                    NovelCharacter.novel_id == novel_id,
                    NovelCharacter.id.in_([row.character_id for row in rows]),
                    NovelCharacter.lifecycle_state == "active",
                )
            )
        } if rows else set()
        state = "active" if len(active_character_ids) == 1 else (
            "conflicted" if len(active_character_ids) > 1 else "archived"
        )
        for row in rows:
            row.lifecycle_state = (
                state if row.character_id in active_character_ids else "archived"
            )


def _sync_character_authority_aliases(
    session: Session,
    *,
    character: NovelCharacter,
    revision: NovelCharacterRevision,
    parent: NovelCharacterRevision | None,
) -> None:
    """Persist official/former names in the same transaction as the revision."""

    current_name = str(revision.name).strip()
    current_normalized = normalize_character_alias(current_name)
    affected = {current_normalized}
    _upsert_authority_alias(
        session,
        character=character,
        revision=revision,
        alias=current_name,
        alias_kind="official_name",
    )
    if parent is not None:
        former_name = str(parent.name).strip()
        former_normalized = normalize_character_alias(former_name)
        affected.add(former_normalized)
        if former_normalized != current_normalized:
            _upsert_authority_alias(
                session,
                character=character,
                revision=revision,
                alias=former_name,
                alias_kind="former_name",
            )
    for row in session.scalars(
        select(CharacterAlias).where(
            CharacterAlias.character_id == character.id,
            CharacterAlias.alias_kind.in_(("official_name", "former_name")),
        )
    ):
        affected.add(row.normalized_alias)
        row.alias_kind = (
            "official_name"
            if row.normalized_alias == current_normalized
            else "former_name"
        )
    _refresh_authority_alias_states(
        session,
        novel_id=character.novel_id,
        normalized_aliases=affected,
    )


def establish_character_revision(
    session: Session,
    novel_id: UUID,
    character_id: UUID,
    *,
    expected_catalog_version: int,
    expected_character_version: int,
    operation_key: str,
    source_kind: str,
    change_set: dict[str, Any] | None = None,
    source_job_id: UUID | None = None,
    source_batch_id: UUID | None = None,
) -> CharacterRevisionResult:
    return _write_character_revision(
        session,
        novel_id,
        character_id,
        expected_catalog_version=expected_catalog_version,
        expected_character_version=expected_character_version,
        operation_key=operation_key,
        source_kind=source_kind,
        desired_content=None,
        change_set=change_set or {},
        source_job_id=source_job_id,
        source_batch_id=source_batch_id,
        restored_from_revision_id=None,
        establish=True,
    )


def save_character_root(
    session: Session,
    novel_id: UUID,
    character_id: UUID,
    *,
    expected_catalog_version: int,
    expected_character_version: int,
    operation_key: str,
    source_kind: str,
    role_type: str,
    name: str,
    description: str,
    details: dict[str, Any],
    lifecycle_state: str,
    position: int,
    change_set: dict[str, Any] | None = None,
    source_job_id: UUID | None = None,
    source_batch_id: UUID | None = None,
) -> CharacterRevisionResult:
    return _write_character_revision(
        session,
        novel_id,
        character_id,
        expected_catalog_version=expected_catalog_version,
        expected_character_version=expected_character_version,
        operation_key=operation_key,
        source_kind=source_kind,
        desired_content=_character_content(
            role_type=role_type,
            name=name,
            description=description,
            details=details,
            lifecycle_state=lifecycle_state,
            position=position,
        ),
        change_set=change_set or {},
        source_job_id=source_job_id,
        source_batch_id=source_batch_id,
        restored_from_revision_id=None,
        establish=False,
    )


def restore_character_root(
    session: Session,
    novel_id: UUID,
    character_id: UUID,
    revision_id: UUID,
    *,
    expected_catalog_version: int,
    expected_character_version: int,
    operation_key: str,
) -> CharacterRevisionResult:
    target = session.get(NovelCharacterRevision, revision_id)
    if (
        target is None
        or target.novel_id != novel_id
        or target.character_id != character_id
    ):
        raise AuthorityNotFoundError(f"character revision {revision_id} not found")
    return _write_character_revision(
        session,
        novel_id,
        character_id,
        expected_catalog_version=expected_catalog_version,
        expected_character_version=expected_character_version,
        operation_key=operation_key,
        source_kind="restore",
        desired_content=_character_content(
            role_type=target.role_type,
            name=target.name,
            description=target.description,
            details=dict(target.details_json or {}),
            lifecycle_state=target.lifecycle_state,
            position=target.position,
        ),
        change_set={"restored_from_revision_id": str(target.id)},
        source_job_id=None,
        source_batch_id=None,
        restored_from_revision_id=target.id,
        establish=False,
    )


def _write_character_revision(
    session: Session,
    novel_id: UUID,
    character_id: UUID,
    *,
    expected_catalog_version: int,
    expected_character_version: int,
    operation_key: str,
    source_kind: str,
    desired_content: dict[str, Any] | None,
    change_set: dict[str, Any],
    source_job_id: UUID | None,
    source_batch_id: UUID | None,
    restored_from_revision_id: UUID | None,
    establish: bool,
) -> CharacterRevisionResult:
    if (
        isinstance(expected_catalog_version, bool)
        or expected_catalog_version < 0
        or isinstance(expected_character_version, bool)
        or expected_character_version < 1
    ):
        raise AuthorityValidationError("character and catalog versions are invalid")
    key = _required_text(operation_key, field="operation_key", maximum=160)
    source = _required_text(source_kind, field="source_kind", maximum=40)
    changes = _json_dict(change_set, field="change_set")
    novel = _lock_novel(session, novel_id)
    character = _lock_character(session, novel_id, character_id)
    content = desired_content or _character_content(
        role_type=character.role_type,
        name=character.name,
        description=character.description,
        details=dict(character.details or {}),
        lifecycle_state=character.lifecycle_state,
        position=character.position,
    )
    operation_payload: dict[str, Any] = {
        "operation": "establish" if establish else (
            "restore" if restored_from_revision_id else "save"
        ),
        "source_kind": source,
        "source_job_id": source_job_id,
        "source_batch_id": source_batch_id,
        "restored_from_revision_id": restored_from_revision_id,
        "change_set": changes,
    }
    if establish:
        # Establishment snapshots the already-existing root.  Its idempotency
        # identity must remain stable after later, legitimate root edits.
        operation_payload["expected_character_version"] = expected_character_version
    else:
        operation_payload["content"] = content
    operation_hash = canonical_hash(operation_payload)
    existing = _character_operation(session, novel_id, character_id, key)
    if existing is not None:
        if existing.operation_hash != operation_hash:
            raise AuthorityIdempotencyConflict(key)
        return CharacterRevisionResult(
            existing, character, int(novel.character_catalog_version), True
        )
    if int(novel.character_catalog_version) != expected_catalog_version:
        raise AuthorityConflictError(
            "character_catalog_version_conflict",
            current={"character_catalog_version": int(novel.character_catalog_version)},
        )
    if int(character.version) != expected_character_version:
        raise AuthorityConflictError(
            "character_version_conflict",
            current={
                "character_id": str(character.id),
                "character_version": int(character.version),
            },
        )
    parent = _latest_character_revision(session, novel_id, character_id)
    if establish and parent is not None:
        raise AuthorityConflictError(
            "character_revision_already_established",
            current={"character_version": int(parent.character_version)},
        )
    if not establish:
        character.role_type = str(content["role_type"])
        character.name = str(content["name"])
        character.description = str(content["description"])
        character.details = deepcopy(content["details"])
        character.lifecycle_state = str(content["lifecycle_state"])
        if character.lifecycle_state == "active":
            character.archived_at = None
        elif character.archived_at is None:
            character.archived_at = _now()
        character.position = int(content["position"])
        character.version = expected_character_version + 1
    revision_version = int(character.version)
    if parent is not None and revision_version <= int(parent.character_version):
        raise AuthorityConflictError(
            "character_revision_version_conflict",
            current={"character_version": int(parent.character_version)},
        )
    revision = NovelCharacterRevision(
        id=uuid4(),
        novel_id=novel_id,
        character_id=character_id,
        character_version=revision_version,
        parent_revision_id=parent.id if parent else None,
        restored_from_revision_id=restored_from_revision_id,
        source_kind=source,
        source_job_id=source_job_id,
        source_batch_id=source_batch_id,
        operation_key=key,
        operation_hash=operation_hash,
        role_type=character.role_type,
        name=character.name,
        description=character.description,
        details_json=deepcopy(character.details or {}),
        lifecycle_state=character.lifecycle_state,
        position=character.position,
        change_set_json=changes,
        content_hash=canonical_hash(content),
        created_at=_now(),
    )
    session.add(revision)
    novel.character_catalog_version = expected_catalog_version + 1
    _sync_character_authority_aliases(
        session,
        character=character,
        revision=revision,
        parent=parent,
    )
    session.flush()
    return CharacterRevisionResult(
        revision, character, int(novel.character_catalog_version), False
    )


def list_character_history(
    session: Session,
    novel_id: UUID,
    character_id: UUID,
    *,
    before_character_version: int | None = None,
    limit: int = 100,
) -> list[NovelCharacterRevision]:
    if isinstance(limit, bool) or not 1 <= limit <= 500:
        raise AuthorityValidationError("limit must be between 1 and 500")
    statement = select(NovelCharacterRevision).where(
        NovelCharacterRevision.novel_id == novel_id,
        NovelCharacterRevision.character_id == character_id,
    )
    if before_character_version is not None:
        statement = statement.where(
            NovelCharacterRevision.character_version < before_character_version
        )
    return list(
        session.scalars(
            statement.order_by(NovelCharacterRevision.character_version.desc()).limit(limit)
        ).all()
    )
