"""Atomic author save-and-use; PostgreSQL cases require an explicit temporary DB."""
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from backend.creative_data_models import PrivateAssetVersion
from backend.models import PrivateAsset
from backend.private_library import maintenance as m
from backend.private_library.contracts import UsagePolicy, VersionSelection
from backend.private_library.errors import PrivateLibraryValidationError
from backend.private_library.lexicon_contracts import LexiconEntry, LexiconPack
from backend.private_library.lexicon_service import lexicon_pack_from_version
from backend.private_library.maintenance_contracts import LibraryChangeAction, LibraryChangeOperation
from backend.private_library.service import get_asset, list_novel_bindings, replace_novel_bindings, update_asset
from tests.private_library.test_capture_saved_binding import capture_session, seed, binding_state
from tests.private_library.test_maintenance import MemoryStore, _access


def action_for(session, novel, target, **overrides):
    values = dict(
        operation=LibraryChangeOperation.UPSERT_AND_USE_LEXICON_ENTRIES,
        asset_id=target.asset.id,
        asset_version_id=target.asset_version.id,
        expected_root_version=int(target.asset.version),
        payload={
            "entries": [LexiconEntry(entry_id="entry_0001", term="管钳", action="recommend",
                                      note="用于咬紧锈蚀管道，写清施力方向。").model_dump(mode="json")],
            "expected_binding_versions": {
                str(key): value[1] for key, value in binding_state(session, novel.id).items()
            },
        },
    )
    values.update(overrides)
    return LibraryChangeAction(**values)


def apply_action(session, novel, action):
    access = _access(novel_id=novel.id, text="修改管钳说明并让本书使用修改后的版本")
    store, executor = m.SqlAlchemyChangeRequestStore(session), m.P1MaintenanceActionExecutor(session)
    proposal = m.prepare_library_change(store, access, actions=[action], intent=m.AuthorMaintenanceIntent.DIRECT)["proposal"]
    receipt = m.apply_library_change(store, executor, access, proposal_id=UUID(proposal["proposal_id"]),
        expected_version=proposal["version"], intent=m.AuthorMaintenanceIntent.DIRECT)["receipt"]
    return access, store, executor, receipt


def undo(session, novel, receipt):
    return m.undo_library_change(m.SqlAlchemyChangeRequestStore(session), m.P1MaintenanceActionExecutor(session),
        _access(novel_id=novel.id, text="撤销刚才的私有库修改"),
        proposal_id=UUID(receipt["proposal_id"]), expected_version=receipt["version"],
        intent=m.AuthorMaintenanceIntent.UNDO)["receipt"]


def test_atomic_action_requires_trusted_novel_at_prepare():
    with pytest.raises(PrivateLibraryValidationError, match="trusted current novel"):
        m.prepare_library_change(MemoryStore(), _access(), actions=[LibraryChangeAction(
            operation=LibraryChangeOperation.UPSERT_AND_USE_LEXICON_ENTRIES,
        )], intent=m.AuthorMaintenanceIntent.DIRECT)


def test_atomic_action_rejects_companion_actions_before_writing():
    with pytest.raises(PrivateLibraryValidationError, match="only proposal action"):
        m.prepare_library_change(MemoryStore(), _access(novel_id=uuid4()), actions=[
            LibraryChangeAction(operation=LibraryChangeOperation.UPSERT_AND_USE_LEXICON_ENTRIES),
            LibraryChangeAction(operation=LibraryChangeOperation.SET_NOVEL_BINDING),
        ], intent=m.AuthorMaintenanceIntent.DIRECT)


@pytest.mark.parametrize("payload", [
    {"entries": [], "expected_binding_versions": {}, "copy_to_novel": "true"},
    {"entries": {}, "expected_binding_versions": {}},
    {"entries": [], "expected_binding_versions": []},
    {"entries": [], "expected_binding_versions": {str(uuid4()): True}},
    {"entries": [], "expected_binding_versions": {}, "novel_id": str(uuid4())},
    {"entries": [], "expected_binding_versions": {}},
])
def test_invalid_atomic_payload_never_touches_database(payload):
    if payload["entries"] == [] and payload != {"entries": [], "expected_binding_versions": {}}:
        payload = {**payload, "entries": [LexiconEntry(
            entry_id="entry_0001", term="管钳", action="recommend"
        ).model_dump(mode="json")]}
    session = MagicMock()
    with pytest.raises(PrivateLibraryValidationError):
        m.P1MaintenanceActionExecutor(session).apply(
            SimpleNamespace(id=uuid4(), scope_kind="novel", scope_novel_id=uuid4()),
            LibraryChangeAction(operation=LibraryChangeOperation.UPSERT_AND_USE_LEXICON_ENTRIES,
                asset_id=uuid4(), asset_version_id=uuid4(), expected_root_version=1, payload=payload),
            action_index=0,
        )
    assert not session.mock_calls


@pytest.mark.parametrize("usage", ["preferred", "required", "context_only", "prohibited", "missing"])
def test_postgres_atomic_old_fixed_base_replay_and_complete_undo(capture_session, usage):
    session = capture_session
    novel, other_novel, target, other = seed(session, usage=usage)
    before = binding_state(session, novel.id)
    other_book_before = binding_state(session, other_novel.id)
    if usage != "missing":
        pending = update_asset(session, target.asset.id, expected_root_version=target.asset.version,
            title=target.asset.title, content="未启用的钉枪",
            metadata=LexiconPack(entries=[LexiconEntry(entry_id="entry_0001", term="管钳", action="recommend"),
                LexiconEntry(entry_id="entry_0002", term="钉枪", action="recommend")]).model_dump(mode="json"),
            operation_key=str(uuid4()))
        old_root = pending.asset_version
    else:
        old_root = target.asset_version
    action = action_for(session, novel, target)
    access, store, executor, receipt = apply_action(session, novel, action)
    assert receipt["state"] == "applied"
    assert receipt["operations"] == ["upsert_and_use_lexicon_entries"]
    after = binding_state(session, novel.id)
    actual = receipt["targets"][0]
    assert actual["used_by_current_novel"] is True
    assert after[target.asset.id][0] == UUID(actual["asset_version_id"])
    assert after[target.asset.id][1] == actual["binding_version"]
    assert after[target.asset.id][2] == (usage if usage in {"required", "context_only"} else "preferred")
    assert after[other.asset.id] == before[other.asset.id]
    assert binding_state(session, other_novel.id) == other_book_before
    version = session.get(PrivateAssetVersion, after[target.asset.id][0])
    pack = lexicon_pack_from_version(version)
    assert [entry.term for entry in pack.entries] == ["管钳"]
    assert pack.entries[0].note == "用于咬紧锈蚀管道，写清施力方向。"
    replay = m.apply_library_change(store, executor, access, proposal_id=UUID(receipt["proposal_id"]),
        expected_version=1, intent=m.AuthorMaintenanceIntent.DIRECT)["receipt"]
    assert replay["replayed"] is True
    assert binding_state(session, novel.id) == after
    undone = undo(session, novel, receipt)
    assert undone["state"] == "applied"
    restored = binding_state(session, novel.id)
    assert {key: (value[0], *value[2:]) for key, value in restored.items()} == {
        key: (value[0], *value[2:]) for key, value in before.items()}
    _, restored_root = get_asset(session, target.asset.id)
    assert lexicon_pack_from_version(restored_root) == lexicon_pack_from_version(old_root)
    assert restored_root.id != old_root.id


def test_postgres_atomic_copy_keeps_source_and_undo_archives_copy(capture_session):
    session = capture_session
    novel, _, target, _ = seed(session, usage="required")
    target.asset.scope_kind, target.asset.scope_novel_id = "library", None
    session.flush()
    source_version, source_root = target.asset.current_version_id, target.asset.version
    before = binding_state(session, novel.id)
    action = action_for(session, novel, target)
    action = action.model_copy(update={"payload": {**action.payload, "copy_to_novel": True}})
    _, _, _, receipt = apply_action(session, novel, action)
    assert receipt["state"] == "applied"
    copy_id = UUID(receipt["targets"][0]["asset_id"])
    assert copy_id != target.asset.id
    after = binding_state(session, novel.id)
    assert target.asset.id not in after
    assert after[copy_id][2:] == before[target.asset.id][2:]
    assert (target.asset.current_version_id, target.asset.version) == (source_version, source_root)
    assert undo(session, novel, receipt)["state"] == "applied"
    assert session.get(PrivateAsset, copy_id).archived is True
    assert binding_state(session, novel.id)[target.asset.id][0] == source_version
    assert (target.asset.current_version_id, target.asset.version) == (source_version, source_root)


@pytest.mark.parametrize("fault", ["root", "binding", "base", "archived", "other_novel", "global_without_copy"])
def test_postgres_atomic_conflict_changes_nothing(capture_session, fault):
    session = capture_session
    novel, other_novel, target, _ = seed(
        session, usage="missing" if fault == "other_novel" else "preferred",
    )
    action = action_for(session, novel, target)
    if fault == "root":
        action = action.model_copy(update={"expected_root_version": 999})
    elif fault == "binding":
        action = action.model_copy(update={"payload": {**action.payload, "expected_binding_versions": {}}})
    elif fault == "base":
        action = action.model_copy(update={"asset_version_id": uuid4()})
    elif fault == "archived":
        target.asset.archived = True
    elif fault == "other_novel":
        target.asset.scope_novel_id = other_novel.id
    else:
        target.asset.scope_kind, target.asset.scope_novel_id = "library", None
    session.flush()
    before_root = target.asset.current_version_id
    before = binding_state(session, novel.id)
    _, _, _, receipt = apply_action(session, novel, action)
    assert receipt["state"] == "conflict"
    assert receipt["counts"]["changed"] == 0
    assert get_asset(session, target.asset.id)[0].current_version_id == before_root
    assert binding_state(session, novel.id) == before


def test_postgres_atomic_undo_root_conflict_rolls_back_earlier_binding_restore(capture_session):
    session = capture_session
    novel, _, target, _ = seed(session)
    _, _, _, receipt = apply_action(session, novel, action_for(session, novel, target))
    before = binding_state(session, novel.id)
    asset, version = get_asset(session, target.asset.id)
    changed = update_asset(session, asset.id, expected_root_version=asset.version,
        title=asset.title, content=version.content + "\n另一次作者修改", operation_key=str(uuid4()))
    preserved_root = changed.asset_version.id
    assert undo(session, novel, receipt)["state"] == "conflict"
    assert binding_state(session, novel.id) == before
    assert get_asset(session, target.asset.id)[0].current_version_id == preserved_root


def test_postgres_atomic_binding_failure_rolls_back_saved_version(capture_session, monkeypatch):
    session = capture_session
    novel, _, target, _ = seed(session)
    before = binding_state(session, novel.id)
    root = target.asset.current_version_id
    versions = tuple(session.scalars(select(PrivateAssetVersion.id).where(PrivateAssetVersion.asset_id == target.asset.id)))
    def fail(*args, **kwargs):
        raise m.PrivateLibraryConflictError("injected_binding_conflict", current={})
    monkeypatch.setattr(m, "replace_novel_bindings", fail)
    _, _, _, receipt = apply_action(session, novel, action_for(session, novel, target))
    assert receipt["state"] == "conflict"
    assert get_asset(session, target.asset.id)[0].current_version_id == root
    assert binding_state(session, novel.id) == before
    assert tuple(session.scalars(select(PrivateAssetVersion.id).where(PrivateAssetVersion.asset_id == target.asset.id))) == versions


def test_postgres_asset_query_exposes_fixed_pack_not_pending_root(capture_session):
    session = capture_session
    novel, _, target, _ = seed(session)
    update_asset(session, target.asset.id, expected_root_version=target.asset.version,
        title=target.asset.title, content="尚未启用", metadata=LexiconPack().model_dump(mode="json"),
        operation_key=str(uuid4()))
    result = m.query_library(m.SqlAlchemyChangeRequestStore(session), _access(novel_id=novel.id),
        query={"kind": "asset", "asset_id": str(target.asset.id)})["asset"]
    assert result["bound_version"]["asset_version_id"] == str(target.asset_version.id)
    assert result["bound_version"]["lexicon_pack"]["entries"][0]["term"] == "管钳"


def test_postgres_atomic_first_collection_and_existing_rejection(capture_session):
    session = capture_session
    novel, _, target, _ = seed(session)
    before = binding_state(session, novel.id)
    action = action_for(session, novel, target, asset_id=None, asset_version_id=None, expected_root_version=None)
    _, _, _, receipt = apply_action(session, novel, action)
    assert receipt["state"] == "applied"
    collection_id = UUID(receipt["targets"][0]["asset_id"])
    collection, version = get_asset(session, collection_id)
    assert collection.collection_key is not None
    assert len(lexicon_pack_from_version(version).entries) == 1
    after = binding_state(session, novel.id)
    assert all(after[key] == value for key, value in before.items())
    existing_action = action.model_copy(update={"payload": {**action.payload,
        "expected_binding_versions": {str(key): value[1] for key, value in after.items()}}})
    _, _, _, rejected = apply_action(session, novel, existing_action)
    assert rejected["state"] == "conflict"
    assert rejected["error"]["code"] == "collection_already_exists"
    assert get_asset(session, collection_id)[1].id == version.id
    assert binding_state(session, novel.id) == after
    assert undo(session, novel, receipt)["state"] == "applied"
    assert session.get(PrivateAsset, collection_id).archived
    assert binding_state(session, novel.id) == before


def test_postgres_existing_novel_copy_cannot_be_overwritten(capture_session):
    from backend.private_library.lexicon_service import create_novel_lexicon_copy
    session = capture_session
    novel, _, target, _ = seed(session)
    target.asset.scope_kind, target.asset.scope_novel_id = "library", None
    session.flush()
    copy, copy_version, _ = create_novel_lexicon_copy(session, novel_id=novel.id,
        source_asset_id=target.asset.id, source_version_id=target.asset_version.id, operation_key=str(uuid4()))
    before = binding_state(session, novel.id)
    action = action_for(session, novel, target)
    action = action.model_copy(update={"payload": {**action.payload, "copy_to_novel": True}})
    _, _, _, receipt = apply_action(session, novel, action)
    assert receipt["state"] == "conflict"
    assert receipt["error"]["code"] == "novel_copy_already_exists"
    assert get_asset(session, copy.id)[1].id == copy_version.id
    assert target.asset.current_version_id == target.asset_version.id
    assert binding_state(session, novel.id) == before


def test_postgres_atomic_undo_binding_conflict_keeps_root(capture_session):
    session = capture_session
    novel, _, target, _ = seed(session)
    _, _, _, receipt = apply_action(session, novel, action_for(session, novel, target))
    views = list_novel_bindings(session, novel.id)
    replace_novel_bindings(session, novel.id,
        expected_binding_versions={view.asset.id: int(view.binding.version) for view in views},
        selections=[VersionSelection(view.asset.id, view.asset_version.id,
            UsagePolicy.CONTEXT_ONLY if view.asset.id == target.asset.id else UsagePolicy(view.binding.usage_policy),
            view.binding.position) for view in views], operation_key=str(uuid4()))
    before, root = binding_state(session, novel.id), target.asset.current_version_id
    assert undo(session, novel, receipt)["state"] == "conflict"
    assert binding_state(session, novel.id) == before
    assert get_asset(session, target.asset.id)[0].current_version_id == root


def test_postgres_v4_root_v2_binding_preserves_all_unedited_entry_fields(capture_session):
    session = capture_session
    novel, _, target, _ = seed(session)
    preserved = LexiconEntry(entry_id="entry_0002", term="轻轻", action="watch", state="inactive",
        variants=["轻声"], categories=["动作"], genres=["科幻"], eras=["现代"], positions=["body"],
        note="按语境取舍", example="他轻轻合上阀门。", counterexample="他轻轻扛起承重梁。",
        replacement_hint="写出施力动作", watch_threshold={"count": 2, "window_characters": 800})
    fixed_pack = LexiconPack(entries=[lexicon_pack_from_version(target.asset_version).entries[0], preserved])
    fixed = update_asset(session, target.asset.id, expected_root_version=target.asset.version,
        title=target.asset.title, content="固定词项", metadata=fixed_pack.model_dump(mode="json"),
        operation_key=str(uuid4()))
    views = list_novel_bindings(session, novel.id)
    replace_novel_bindings(session, novel.id,
        expected_binding_versions={view.asset.id: int(view.binding.version) for view in views},
        selections=[VersionSelection(view.asset.id,
            fixed.asset_version.id if view.asset.id == target.asset.id else view.asset_version.id,
            UsagePolicy(view.binding.usage_policy), view.binding.position) for view in views],
        operation_key=str(uuid4()))
    for _ in range(2):
        pending = update_asset(session, target.asset.id, expected_root_version=target.asset.version,
            title=target.asset.title, content="尚未采用的词项",
            metadata=LexiconPack(entries=[preserved.model_copy(update={"note": "未采用改动"})]).model_dump(mode="json"),
            operation_key=str(uuid4()))
    assert target.asset.version == 4
    assert fixed.asset_version.version_number == 2
    _, _, _, receipt = apply_action(session, novel, action_for(session, novel, target,
        asset_version_id=fixed.asset_version.id))
    assert receipt["state"] == "applied"
    _, saved = get_asset(session, target.asset.id)
    assert lexicon_pack_from_version(saved).entries[1] == preserved
    assert undo(session, novel, receipt)["state"] == "applied"
    assert get_asset(session, target.asset.id)[1].metadata_json == pending.asset_version.metadata_json
    assert binding_state(session, novel.id)[target.asset.id][0] == fixed.asset_version.id
