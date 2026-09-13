from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from backend.private_library.errors import (
    PrivateLibraryNotFoundError,
    PrivateLibraryValidationError,
)
from backend.private_library.lexicon_contracts import (
    MAX_LEXICON_METADATA_BYTES,
    LexiconEntry,
    LexiconPack,
)
from backend.private_library.lexicon_service import (
    merge_lexicon_entries,
    remove_lexicon_entries,
    require_asset_scope,
    resolve_effective_lexicon_policy,
    effective_policy_from_snapshot,
    effective_policy_snapshot,
    validate_lexicon_pack_budget,
)


def _entry(entry_id: str, term: str, action: str = "recommend") -> LexiconEntry:
    return LexiconEntry(entry_id=entry_id, term=term, action=action)


def test_merge_changes_only_requested_entries_and_appends_stably() -> None:
    original = LexiconPack(entries=[
        _entry("entry_0001", "掠过"),
        _entry("entry_0002", "凝视", "watch"),
    ])
    merged = merge_lexicon_entries(original, [
        _entry("entry_0002", "凝视", "forbid"),
        _entry("entry_0003", "攥紧"),
    ])
    assert [entry.entry_id for entry in merged.entries] == [
        "entry_0001", "entry_0002", "entry_0003",
    ]
    assert merged.entries[0] == original.entries[0]
    assert merged.entries[1].action.value == "forbid"


def test_merge_rejects_duplicate_updates_before_touching_pack() -> None:
    with pytest.raises(PrivateLibraryValidationError):
        merge_lexicon_entries(LexiconPack(), [
            _entry("entry_0001", "掠过"),
            _entry("entry_0001", "扫过"),
        ])


def test_remove_is_exact_and_never_silently_ignores_missing_ids() -> None:
    pack = LexiconPack(entries=[
        _entry("entry_0001", "掠过"),
        _entry("entry_0002", "凝视"),
    ])
    result = remove_lexicon_entries(pack, ["entry_0001"])
    assert [entry.entry_id for entry in result.entries] == ["entry_0002"]
    with pytest.raises(PrivateLibraryNotFoundError):
        remove_lexicon_entries(pack, ["entry_9999"])


def test_asset_scope_allows_library_or_same_novel_only() -> None:
    novel_id = uuid4()
    require_asset_scope(
        SimpleNamespace(scope_kind="library", scope_novel_id=None),
        novel_id=None,
    )
    require_asset_scope(
        SimpleNamespace(scope_kind="novel", scope_novel_id=novel_id),
        novel_id=novel_id,
    )
    with pytest.raises(PrivateLibraryNotFoundError):
        require_asset_scope(
            SimpleNamespace(scope_kind="novel", scope_novel_id=uuid4()),
            novel_id=novel_id,
        )
    with pytest.raises(PrivateLibraryNotFoundError):
        require_asset_scope(
            SimpleNamespace(scope_kind="library", scope_novel_id=None),
            novel_id=novel_id,
            allow_library=False,
        )


def test_lexicon_metadata_budget_is_enforced_on_canonical_utf8() -> None:
    validate_lexicon_pack_budget(LexiconPack(entries=[
        LexiconEntry(entry_id="entry_0001", term="潮声", action="recommend")
    ]))
    oversized = LexiconPack(entries=[
        LexiconEntry(
            entry_id=f"entry_{index:04d}",
            term=f"词{index}",
            action="recommend",
            note="海" * 1900,
        )
        for index in range(200)
    ])
    with pytest.raises(
        PrivateLibraryValidationError,
        match=str(MAX_LEXICON_METADATA_BYTES),
    ):
        validate_lexicon_pack_budget(oversized)


def _resolved_policy(monkeypatch, packs: list[LexiconPack]):
    novel_id = uuid4()
    rows = []
    objects = {}
    for position, pack in enumerate(packs):
        asset_id, version_id = uuid4(), uuid4()
        rows.append(SimpleNamespace(
            asset_id=asset_id,
            asset_version_id=version_id,
            position=position,
        ))
        objects[asset_id] = SimpleNamespace(
            id=asset_id,
            asset_type="vocabulary",
            scope_kind="library",
            scope_novel_id=None,
        )
        objects[version_id] = SimpleNamespace(
            id=version_id,
            asset_id=asset_id,
            metadata_json=pack.model_dump(mode="json"),
        )
    session = MagicMock()
    session.scalars.return_value.all.return_value = rows
    session.get.side_effect = lambda _model, key: objects.get(key)
    monkeypatch.setattr(
        "backend.private_library.lexicon_service.lock_active_novel",
        lambda *_args: object(),
    )
    return resolve_effective_lexicon_policy(session, novel_id)


def test_effective_rules_resolve_variant_conflicts_without_losing_other_terms(
    monkeypatch,
) -> None:
    policy = _resolved_policy(monkeypatch, [
        LexiconPack(entries=[LexiconEntry(
            entry_id="entry_0001",
            term="潮声",
            variants=["眼底闪过"],
            action="recommend",
        )]),
        LexiconPack(entries=[LexiconEntry(
            entry_id="entry_0002",
            term="眼底闪过",
            action="forbid",
        )]),
    ])
    assert [(item.entry.term, item.entry.action.value) for item in policy.rules] == [
        ("眼底闪过", "forbid"),
        ("潮声", "recommend"),
    ]
    assert policy.conflicts[0]["winner"] == "forbid"


def test_case_sensitive_spellings_do_not_conflict_until_insensitive_rule_bridges(
    monkeypatch,
) -> None:
    separate = _resolved_policy(monkeypatch, [
        LexiconPack(entries=[LexiconEntry(
            entry_id="entry_0001", term="AI", action="recommend",
            match_mode="ascii_word", case_sensitive=True,
        )]),
        LexiconPack(entries=[LexiconEntry(
            entry_id="entry_0002", term="ai", action="forbid",
            match_mode="ascii_word", case_sensitive=True,
        )]),
    ])
    assert len(separate.rules) == 2
    assert separate.conflicts == ()

    bridged = _resolved_policy(monkeypatch, [
        LexiconPack(entries=[LexiconEntry(
            entry_id="entry_0001", term="AI", action="recommend",
            match_mode="ascii_word", case_sensitive=True,
        )]),
        LexiconPack(entries=[LexiconEntry(
            entry_id="entry_0002", term="ai", action="forbid",
            match_mode="ascii_word", case_sensitive=False,
        )]),
    ])
    assert [(item.entry.term, item.entry.action.value) for item in bridged.rules] == [
        ("ai", "forbid")
    ]
    assert bridged.conflicts[0]["winner"] == "forbid"


def test_effective_policy_snapshot_round_trip_rejects_tampering(monkeypatch) -> None:
    policy = _resolved_policy(monkeypatch, [LexiconPack(entries=[LexiconEntry(
        entry_id="entry_0001", term="眼底闪过", action="forbid",
    )])])
    snapshot = effective_policy_snapshot(policy)
    restored = effective_policy_from_snapshot(policy.novel_id, snapshot)
    assert restored == policy
    snapshot["rules"][0]["entry"]["term"] = "暗自思忖"  # type: ignore[index]
    with pytest.raises(Exception, match="hash"):
        effective_policy_from_snapshot(policy.novel_id, snapshot)
