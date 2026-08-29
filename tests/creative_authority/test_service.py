from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import inspect
from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList

from backend.creative_authority import (
    AuthorityConflictError,
    AuthorityIdempotencyConflict,
    establish_character_revision,
    get_outline,
    get_settings,
    list_character_history,
    list_outline_history,
    list_settings_history,
    restore_character_root,
    restore_outline,
    restore_settings,
    save_character_root,
    save_outline,
    save_settings,
)
from backend.creative_data_models import (
    NovelCharacterRevision,
    NovelOutlineHead,
    NovelOutlineRevision,
    NovelSettingHead,
    NovelSettingRevision,
)
from backend.models import CharacterAlias, Novel, NovelCharacter


class _ScalarRows:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class MemorySession:
    """Small behavioral Session fake; commit is deliberately unavailable."""

    def __init__(self, *objects: Any) -> None:
        self.rows: dict[type[Any], list[Any]] = defaultdict(list)
        self.flush_count = 0
        for item in objects:
            self.add(item)

    def add(self, item: Any) -> None:
        if item not in self.rows[type(item)]:
            self.rows[type(item)].append(item)

    def flush(self) -> None:
        self.flush_count += 1

    def commit(self) -> None:
        raise AssertionError("authority helpers must not commit")

    def get(self, model: type[Any], identity: Any) -> Any | None:
        keys = [column.key for column in inspect(model).primary_key]
        values = identity if isinstance(identity, tuple) else (identity,)
        for row in self.rows[model]:
            if tuple(getattr(row, key) for key in keys) == tuple(values):
                return row
        return None

    def scalar(self, statement: Any) -> Any | None:
        rows = self._select(statement)
        return rows[0] if rows else None

    def scalars(self, statement: Any) -> _ScalarRows:
        return _ScalarRows(self._select(statement))

    def _select(self, statement: Any) -> list[Any]:
        model = statement.column_descriptions[0]["entity"]
        rows = [
            row
            for row in self.rows[model]
            if all(_matches(row, criterion) for criterion in statement._where_criteria)
        ]
        if model in (NovelOutlineRevision, NovelSettingRevision):
            rows.sort(key=lambda row: row.revision_number, reverse=True)
        elif model is NovelCharacterRevision:
            rows.sort(key=lambda row: row.character_version, reverse=True)
        limit_clause = statement._limit_clause
        if limit_clause is not None:
            rows = rows[: int(limit_clause.value)]
        return rows


def _matches(row: Any, expression: Any) -> bool:
    if isinstance(expression, BooleanClauseList):
        return all(_matches(row, item) for item in expression.clauses)
    if isinstance(expression, BinaryExpression):
        left = getattr(row, expression.left.key)
        right = expression.right.value
        if expression.operator is operators.in_op:
            return left in right
        return bool(expression.operator(left, right))
    raise AssertionError(f"unsupported SQL expression in MemorySession: {expression!r}")


def _novel() -> Novel:
    return Novel(
        id=uuid4(),
        title="Authority Test",
        description="book description must stay independent",
        author_name="original author",
        genre="original genre",
        outline_target_chapters=20,
        background="old background",
        main_plot="old plot",
        highlight="old highlight",
        character_catalog_version=0,
        version=1,
    )


def _character(novel_id: UUID, *, position: int = 0) -> NovelCharacter:
    return NovelCharacter(
        id=uuid4(),
        novel_id=novel_id,
        role_type="protagonist",
        name="Old Name",
        description="initial root",
        details={"theme": "home"},
        lifecycle_state="active",
        position=position,
        version=1,
    )


def _outline_payload(*, suffix: str = "one") -> dict[str, Any]:
    return {
        "source_kind": "manual",
        "target_chapter_count": 120,
        "background_text": f"background {suffix}",
        "plot_text": f"plot {suffix}",
        "highlight_text": f"highlight {suffix}",
        "character_revision_refs": [{"character_id": "c1", "version": 2}],
        "change_set": {"reason": suffix},
    }


def test_outline_save_history_restore_cas_idempotency_and_projection() -> None:
    novel = _novel()
    session = MemorySession(novel)
    payload = _outline_payload()

    first = save_outline(
        session, novel.id, expected_head_version=0, idempotency_key="outline-1", **payload
    )

    assert first.replayed is False
    assert first.revision.revision_number == 1
    assert first.revision.parent_revision_id is None
    assert first.head.version == 1
    assert novel.outline_target_chapters == 120
    assert novel.background == "background one"
    assert novel.main_plot == "plot one"
    assert novel.highlight == "highlight one"
    assert novel.description == "book description must stay independent"
    assert novel.version == 2
    assert session.flush_count == 1

    # A transport retry ignores its now-stale CAS version and performs no write.
    replay = save_outline(
        session, novel.id, expected_head_version=0, idempotency_key="outline-1", **payload
    )
    assert replay.replayed is True
    assert replay.revision.id == first.revision.id
    assert session.flush_count == 1
    assert novel.version == 2

    with pytest.raises(AuthorityIdempotencyConflict):
        save_outline(
            session,
            novel.id,
            expected_head_version=1,
            idempotency_key="outline-1",
            **_outline_payload(suffix="different"),
        )

    changed_audit = _outline_payload()
    changed_audit["change_set"] = {"reason": "different audit meaning"}
    with pytest.raises(AuthorityIdempotencyConflict):
        save_outline(
            session,
            novel.id,
            expected_head_version=1,
            idempotency_key="outline-1",
            **changed_audit,
        )

    second = save_outline(
        session,
        novel.id,
        expected_head_version=1,
        idempotency_key="outline-2",
        **_outline_payload(suffix="two"),
    )
    assert second.revision.parent_revision_id == first.revision.id
    assert second.revision.revision_number == 2
    assert second.head.version == 2

    with pytest.raises(AuthorityConflictError) as stale:
        save_outline(
            session,
            novel.id,
            expected_head_version=1,
            idempotency_key="outline-stale",
            **_outline_payload(suffix="stale"),
        )
    assert stale.value.code == "outline_head_version_conflict"
    assert stale.value.current["head_version"] == 2

    restored = restore_outline(
        session,
        novel.id,
        first.revision.id,
        expected_head_version=2,
        idempotency_key="outline-restore-1",
    )
    assert restored.revision.id != first.revision.id
    assert restored.revision.revision_number == 3
    assert restored.revision.parent_revision_id == second.revision.id
    assert restored.revision.restored_from_revision_id == first.revision.id
    assert restored.head.current_revision_id == restored.revision.id
    assert restored.head.version == 3
    assert novel.background == first.revision.background_text
    assert get_outline(session, novel.id) == (restored.head, restored.revision)
    assert [item.revision_number for item in list_outline_history(session, novel.id)] == [3, 2, 1]
    assert [item.revision_number for item in list_outline_history(
        session, novel.id, before_revision_number=3
    )] == [2, 1]


def test_settings_save_restore_is_immutable_and_projects_only_compat_fields() -> None:
    novel = _novel()
    session = MemorySession(novel)
    original_settings = {
        "author_name": "A",
        "genre": "mystery",
        "world_rules": {"magic": False},
    }

    first = save_settings(
        session,
        novel.id,
        expected_head_version=0,
        idempotency_key="settings-1",
        source_kind="manual",
        schema_id="story-settings",
        schema_version=1,
        settings=original_settings,
    )
    original_settings["world_rules"]["magic"] = True
    assert first.revision.settings_json["world_rules"] == {"magic": False}
    assert novel.author_name == "A"
    assert novel.genre == "mystery"
    assert not hasattr(novel, "world_rules")
    assert novel.description == "book description must stay independent"

    replay = save_settings(
        session,
        novel.id,
        expected_head_version=0,
        idempotency_key="settings-1",
        source_kind="manual",
        schema_id="story-settings",
        schema_version=1,
        settings={
            "author_name": "A",
            "genre": "mystery",
            "world_rules": {"magic": False},
        },
    )
    assert replay.replayed is True
    assert replay.revision.id == first.revision.id

    second = save_settings(
        session,
        novel.id,
        expected_head_version=1,
        idempotency_key="settings-2",
        source_kind="manual",
        schema_id="story-settings",
        schema_version=2,
        settings={"author_name": "B", "genre": "fantasy", "world_rules": {}},
    )
    restored = restore_settings(
        session,
        novel.id,
        first.revision.id,
        expected_head_version=2,
        idempotency_key="settings-restore-1",
    )
    assert restored.revision.parent_revision_id == second.revision.id
    assert restored.revision.restored_from_revision_id == first.revision.id
    assert restored.revision.id != first.revision.id
    assert novel.author_name == "A"
    assert novel.genre == "mystery"
    assert get_settings(session, novel.id) == (restored.head, restored.revision)
    assert [item.revision_number for item in list_settings_history(session, novel.id)] == [3, 2, 1]


def test_character_root_revision_catalog_cas_restore_and_late_replay() -> None:
    novel = _novel()
    character = _character(novel.id)
    session = MemorySession(novel, character)

    established = establish_character_revision(
        session,
        novel.id,
        character.id,
        expected_catalog_version=0,
        expected_character_version=1,
        operation_key="character-establish",
        source_kind="formalize",
    )
    assert established.revision.character_version == 1
    assert established.revision.parent_revision_id is None
    assert character.version == 1
    assert novel.character_catalog_version == 1
    aliases = session.rows[CharacterAlias]
    assert [(item.alias, item.alias_kind) for item in aliases] == [
        ("Old Name", "official_name")
    ]

    saved = save_character_root(
        session,
        novel.id,
        character.id,
        expected_catalog_version=1,
        expected_character_version=1,
        operation_key="character-save-2",
        source_kind="manual",
        role_type="protagonist",
        name="New Name",
        description="grew",
        details={"theme": "truth"},
        lifecycle_state="active",
        position=0,
    )
    assert saved.revision.character_version == 2
    assert saved.revision.parent_revision_id == established.revision.id
    assert character.name == "New Name"
    assert character.version == 2
    assert novel.character_catalog_version == 2
    assert {
        (item.alias, item.alias_kind, item.lifecycle_state)
        for item in session.rows[CharacterAlias]
    } == {
        ("Old Name", "former_name", "active"),
        ("New Name", "official_name", "active"),
    }

    # Establishment replay remains stable even though the live root has evolved.
    establish_replay = establish_character_revision(
        session,
        novel.id,
        character.id,
        expected_catalog_version=0,
        expected_character_version=1,
        operation_key="character-establish",
        source_kind="formalize",
    )
    assert establish_replay.replayed is True
    assert establish_replay.revision.id == established.revision.id
    assert character.version == 2
    assert novel.character_catalog_version == 2

    with pytest.raises(AuthorityConflictError) as stale:
        save_character_root(
            session,
            novel.id,
            character.id,
            expected_catalog_version=1,
            expected_character_version=2,
            operation_key="character-stale",
            source_kind="manual",
            role_type="protagonist",
            name="Wrong",
            description="",
            details={},
            lifecycle_state="active",
            position=0,
        )
    assert stale.value.code == "character_catalog_version_conflict"

    restored = restore_character_root(
        session,
        novel.id,
        character.id,
        established.revision.id,
        expected_catalog_version=2,
        expected_character_version=2,
        operation_key="character-restore-1",
    )
    assert restored.revision.id != established.revision.id
    assert restored.revision.character_version == 3
    assert restored.revision.parent_revision_id == saved.revision.id
    assert restored.revision.restored_from_revision_id == established.revision.id
    assert character.name == "Old Name"
    assert character.version == 3
    assert novel.character_catalog_version == 3
    assert {
        (item.alias, item.alias_kind, item.lifecycle_state)
        for item in session.rows[CharacterAlias]
    } == {
        ("Old Name", "official_name", "active"),
        ("New Name", "former_name", "active"),
    }
    assert [item.character_version for item in list_character_history(
        session, novel.id, character.id
    )] == [3, 2, 1]
    assert [item.character_version for item in list_character_history(
        session, novel.id, character.id, before_character_version=3
    )] == [2, 1]
    assert session.flush_count == 3


def test_character_catalog_version_is_novel_wide() -> None:
    novel = _novel()
    first_character = _character(novel.id, position=0)
    second_character = _character(novel.id, position=1)
    second_character.name = "Second"
    session = MemorySession(novel, first_character, second_character)

    establish_character_revision(
        session,
        novel.id,
        first_character.id,
        expected_catalog_version=0,
        expected_character_version=1,
        operation_key="first-establish",
        source_kind="formalize",
    )
    with pytest.raises(AuthorityConflictError) as stale:
        establish_character_revision(
            session,
            novel.id,
            second_character.id,
            expected_catalog_version=0,
            expected_character_version=1,
            operation_key="second-establish-stale",
            source_kind="formalize",
        )
    assert stale.value.code == "character_catalog_version_conflict"

    second = establish_character_revision(
        session,
        novel.id,
        second_character.id,
        expected_catalog_version=1,
        expected_character_version=1,
        operation_key="second-establish",
        source_kind="formalize",
    )
    assert second.catalog_version == 2


def test_character_alias_collision_is_explicitly_conflicted() -> None:
    novel = _novel()
    first = _character(novel.id, position=0)
    first.name = "Ａ"
    second = _character(novel.id, position=1)
    second.name = "a"
    session = MemorySession(novel, first, second)

    establish_character_revision(
        session, novel.id, first.id,
        expected_catalog_version=0, expected_character_version=1,
        operation_key="alias-first", source_kind="formalize",
    )
    establish_character_revision(
        session, novel.id, second.id,
        expected_catalog_version=1, expected_character_version=1,
        operation_key="alias-second", source_kind="formalize",
    )

    aliases = session.rows[CharacterAlias]
    assert {item.normalized_alias for item in aliases} == {"a"}
    assert {item.lifecycle_state for item in aliases} == {"conflicted"}
    assert {item.character_id for item in aliases} == {first.id, second.id}
