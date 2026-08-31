from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.character_workspace import commands
from backend.story_state.revisions import CharacterInstanceProfileV2


class FakeSession:
    def __init__(self, rows: list[object]) -> None:
        self.rows = list(rows)

    def scalar(self, _statement):
        return self.rows.pop(0)


def scoped_rows():
    novel_id = uuid4()
    character_id = uuid4()
    timeline_id = uuid4()
    instance_id = uuid4()
    novel = SimpleNamespace(
        id=novel_id,
        character_catalog_version=7,
        story_ledger_version=11,
    )
    character = SimpleNamespace(
        id=character_id,
        novel_id=novel_id,
        role_type="main",
        name="沈砚",
        description="调查记者",
        details={"hidden": "preserve"},
        lifecycle_state="active",
        position=1000,
        version=3,
    )
    instance = SimpleNamespace(
        id=instance_id,
        novel_id=novel_id,
        character_id=character_id,
        lifecycle_state="active",
        version=2,
    )
    timeline = SimpleNamespace(
        id=timeline_id,
        novel_id=novel_id,
        lifecycle_state="active",
    )
    return novel, character, instance, timeline


def test_atomic_command_derives_bounded_child_keys_and_calls_both_writers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel, character, instance, timeline = scoped_rows()
    calls: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        commands,
        "validate_character_root_update",
        lambda *_args, **_kwargs: {
            "role_type": "main",
            "name": "沈砚",
            "description": "调查记者",
            "details": {"hidden": "preserve", "gender": "男"},
        },
    )
    monkeypatch.setattr(
        commands,
        "save_character_root",
        lambda *_args, **kwargs: (
            calls.append(("root", kwargs))
            or SimpleNamespace(replayed=False)
        ),
    )
    monkeypatch.setattr(
        commands,
        "save_character_instance_profile",
        lambda *_args, **kwargs: (
            calls.append(("profile", kwargs))
            or {"replayed": False}
        ),
    )
    profile = CharacterInstanceProfileV2(
        occupation="记者",
        age_at_story_start_note="三十岁上下",
    )

    result = commands.save_character_workspace(
        FakeSession([novel, character, instance, timeline]),
        novel.id,
        character.id,
        selected_timeline_id=timeline.id,
        selected_instance_id=instance.id,
        operation_key="x" * 120,
        expected_character_catalog_version=7,
        expected_story_ledger_version=11,
        expected_character_version=3,
        expected_instance_version=2,
        root_patch={
            "role_type": "main",
            "name": "沈砚",
            "description": "调查记者",
            "gender": "男",
            "core_theme": "真相",
        },
        profile=profile,
    )

    assert result == {
        "no_changes": False,
        "root_replayed": False,
        "profile_replayed": False,
    }
    assert [name for name, _kwargs in calls] == ["root", "profile"]
    root_key = str(calls[0][1]["operation_key"])
    profile_key = str(calls[1][1]["operation_key"])
    assert root_key.startswith("cw2:root:") and len(root_key) <= 120
    assert profile_key.startswith("cw2:profile:") and len(profile_key) <= 120
    assert root_key != profile_key


def test_root_only_save_never_touches_story_profile_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel, character, instance, timeline = scoped_rows()
    monkeypatch.setattr(
        commands,
        "validate_character_root_update",
        lambda *_args, **_kwargs: {
            "role_type": "main",
            "name": "沈砚",
            "description": "新小传",
            "details": dict(character.details),
        },
    )
    monkeypatch.setattr(
        commands,
        "save_character_root",
        lambda *_args, **_kwargs: SimpleNamespace(replayed=True),
    )
    monkeypatch.setattr(
        commands,
        "save_character_instance_profile",
        lambda *_args, **_kwargs: pytest.fail("profile writer must not run"),
    )

    result = commands.save_character_workspace(
        FakeSession([novel, character, instance, timeline]),
        novel.id,
        character.id,
        selected_timeline_id=timeline.id,
        selected_instance_id=instance.id,
        operation_key="root-only",
        expected_character_catalog_version=7,
        expected_story_ledger_version=1,
        expected_character_version=3,
        expected_instance_version=1,
        root_patch={
            "role_type": "main",
            "name": "沈砚",
            "description": "新小传",
            "gender": "男",
            "core_theme": "真相",
        },
        profile=None,
    )

    assert result["root_replayed"] is True
    assert result["profile_replayed"] is False


def test_no_change_command_returns_without_calling_writers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel, character, instance, timeline = scoped_rows()
    monkeypatch.setattr(
        commands,
        "save_character_root",
        lambda *_args, **_kwargs: pytest.fail("root writer must not run"),
    )
    monkeypatch.setattr(
        commands,
        "save_character_instance_profile",
        lambda *_args, **_kwargs: pytest.fail("profile writer must not run"),
    )

    result = commands.save_character_workspace(
        FakeSession([novel, character, instance, timeline]),
        novel.id,
        character.id,
        selected_timeline_id=timeline.id,
        selected_instance_id=instance.id,
        operation_key="no-change",
        expected_character_catalog_version=0,
        expected_story_ledger_version=1,
        expected_character_version=1,
        expected_instance_version=1,
        root_patch=None,
        profile=None,
    )

    assert result["no_changes"] is True
