from __future__ import annotations

from unittest.mock import MagicMock
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from backend.creative_data_models import LibraryChangeRequest, NovelAssetBinding, PrivateAssetVersion
from backend.models import AssetPreset, AssetPresetItem, PrivateAsset
from backend.private_library import (
    UsagePolicy,
    VersionSelection,
    apply_preset_to_novel,
    replace_novel_bindings,
    replace_preset_items,
)
from backend.private_library import service
from backend.private_library.errors import PrivateLibraryIdempotencyConflict, PrivateLibraryValidationError


def test_archived_enabled_asset_can_be_disabled_without_changing_other_archived_bindings(monkeypatch):
    session = _session()
    novel_id = uuid4()
    first, first_version = _pair(current_is_selected=True)
    second, second_version = _pair(current_is_selected=True)
    first.archived = second.archived = True
    rows = [SimpleNamespace(asset=asset, asset_version=version, binding=NovelAssetBinding(
        id=uuid4(), novel_id=novel_id, asset_id=asset.id, asset_version_id=version.id,
        version=2, position=position, usage_policy="preferred", lifecycle_state="active",
    )) for position, (asset, version) in enumerate(((first, first_version), (second, second_version)))]
    monkeypatch.setattr(service, "_lock_novel", lambda *_: None)
    monkeypatch.setattr(service, "_lock_asset", lambda *_: first)
    monkeypatch.setattr(service, "_require_asset_for_novel", lambda *_: None)
    monkeypatch.setattr(service, "list_novel_bindings", lambda *_: rows)
    replace = MagicMock(return_value=SimpleNamespace(changed=True, bindings=[rows[1]]))
    monkeypatch.setattr(service, "replace_novel_bindings", replace)
    session.scalar.return_value = None
    service.set_novel_asset_enabled(session, novel_id=novel_id, asset_id=first.id,
        expected_binding_version=2, enabled=False, operation_key="disable-archived")
    selections = replace.call_args.kwargs["selections"]
    assert len(selections) == 1
    assert selections[0].asset_id == second.id
    assert selections[0].asset_version_id == second_version.id
    assert selections[0].position == rows[1].binding.position
    assert selections[0].usage_policy.value == rows[1].binding.usage_policy
    receipt = session.add.call_args.args[0]
    assert isinstance(receipt, LibraryChangeRequest)
    assert receipt.source_json["channel"] == "structured_author_ui"
    assert receipt.result_json["before"]["asset_version_id"] == str(first_version.id)
    assert receipt.result_json["after"] is None
    assert receipt.result_json["undo_actions"] == []
    assert rows[0].binding.operation_hash is None  # Not repurposed as the UI receipt.
    session.commit.assert_not_called()


def test_archived_asset_cannot_be_newly_enabled(monkeypatch):
    session = _session()
    asset, _ = _pair(current_is_selected=True)
    asset.archived = True
    monkeypatch.setattr(service, "_lock_novel", lambda *_: None)
    monkeypatch.setattr(service, "_lock_asset", lambda *_: asset)
    monkeypatch.setattr(service, "_require_asset_for_novel", lambda *_: None)
    monkeypatch.setattr(service, "list_novel_bindings", lambda *_: [])
    replace = MagicMock()
    monkeypatch.setattr(service, "replace_novel_bindings", replace)
    session.scalar.return_value = None
    with pytest.raises(PrivateLibraryValidationError, match="归档"):
        service.set_novel_asset_enabled(session, novel_id=uuid4(), asset_id=asset.id,
            expected_binding_version=0, enabled=True, operation_key="enable-archived")
    replace.assert_not_called()
    session.add.assert_not_called()


def test_repeated_enable_preserves_fixed_version_and_records_a_durable_noop(monkeypatch):
    session = _session()
    novel_id = uuid4()
    asset, fixed_version = _pair(current_is_selected=False)
    binding = NovelAssetBinding(
        asset_id=asset.id, asset_version_id=fixed_version.id, novel_id=novel_id,
        version=4, position=8, usage_policy="required", lifecycle_state="active",
        operation_key="earlier-enable", operation_hash="b" * 64,
    )
    current = SimpleNamespace(asset=asset, asset_version=fixed_version, binding=binding)
    monkeypatch.setattr(service, "_lock_novel", lambda *_: None)
    monkeypatch.setattr(service, "_lock_asset", lambda *_: asset)
    monkeypatch.setattr(service, "_require_asset_for_novel", lambda *_: None)
    views = MagicMock(return_value=[current])
    monkeypatch.setattr(service, "list_novel_bindings", views)
    replace = MagicMock(return_value=SimpleNamespace(changed=False, bindings=[current]))
    monkeypatch.setattr(service, "replace_novel_bindings", replace)
    session.scalar.return_value = None
    request = dict(novel_id=novel_id, asset_id=asset.id, expected_binding_version=4,
                   enabled=True, operation_key="keep-enabled")
    service.set_novel_asset_enabled(session, **request)
    selection = replace.call_args.kwargs["selections"][0]
    assert selection.asset_version_id == fixed_version.id != asset.current_version_id
    assert selection.usage_policy.value == "required" and selection.position == 8
    receipt = session.add.call_args.args[0]
    assert receipt.state == "applied"
    assert receipt.result_json["changed"] is False
    assert receipt.result_json["counts"] == {"changed": 0, "unchanged": 1, "unsupported": 0}
    assert binding.operation_key == "earlier-enable" and binding.operation_hash == "b" * 64

    # A later mutable binding state is irrelevant to the durable prior receipt.
    session.scalar.return_value = receipt
    views.reset_mock(); replace.reset_mock(); session.add.reset_mock()
    service.set_novel_asset_enabled(session, **request)
    views.assert_not_called(); replace.assert_not_called(); session.add.assert_not_called()
    with pytest.raises(PrivateLibraryIdempotencyConflict):
        service.set_novel_asset_enabled(session, **{**request, "enabled": False})
    replace.assert_not_called()


def test_failed_toggle_does_not_create_an_applied_receipt(monkeypatch):
    session = _session()
    asset, _ = _pair(current_is_selected=True)
    monkeypatch.setattr(service, "_lock_novel", lambda *_: None)
    monkeypatch.setattr(service, "_lock_asset", lambda *_: asset)
    monkeypatch.setattr(service, "_require_asset_for_novel", lambda *_: None)
    monkeypatch.setattr(service, "list_novel_bindings", lambda *_: [])
    monkeypatch.setattr(service, "replace_novel_bindings", MagicMock(side_effect=RuntimeError("write failed")))
    session.scalar.return_value = None
    with pytest.raises(RuntimeError, match="write failed"):
        service.set_novel_asset_enabled(session, novel_id=uuid4(), asset_id=asset.id,
            expected_binding_version=0, enabled=True, operation_key="failed-enable")
    session.add.assert_not_called()
    session.commit.assert_not_called()


def _session() -> MagicMock:
    return MagicMock(spec=Session)


def _pair(*, current_is_selected: bool):
    asset_id = uuid4()
    selected_id = uuid4()
    current_id = selected_id if current_is_selected else uuid4()
    asset = PrivateAsset(
        id=asset_id,
        asset_type="plot",
        title="根投影",
        content="根投影",
        version=4,
        archived=False,
        current_version_id=current_id,
        tags_json=[],
        source_json={},
        rights_json={},
    )
    version = PrivateAssetVersion(
        id=selected_id,
        asset_id=asset_id,
        version_number=2,
        title="固定标题",
        content="固定内容",
        metadata_json={},
        source_json={},
        rights_json={},
        content_hash="a" * 64,
        operation_key="fixed-version",
        operation_hash="b" * 64,
    )
    return asset, version


def test_preset_replacement_pins_version_and_policy(monkeypatch) -> None:
    session = _session()
    preset = AssetPreset(
        id=uuid4(), title="预设", description="", version=7, archived=False
    )
    old = AssetPresetItem(
        id=uuid4(), preset_id=preset.id, asset_id=uuid4(), position=0
    )
    asset, version = _pair(current_is_selected=True)
    selection = VersionSelection(
        asset_id=asset.id,
        asset_version_id=version.id,
        usage_policy=UsagePolicy.REQUIRED,
        position=1000,
    )
    monkeypatch.setattr(service, "_lock_preset", lambda *_: preset)
    monkeypatch.setattr(
        service,
        "_validate_version_selections",
        lambda *_args, **_kwargs: {asset.id: (asset, version)},
    )
    session.scalars.return_value.all.return_value = [old]

    rows = replace_preset_items(
        session,
        preset.id,
        expected_preset_version=7,
        selections=[selection],
    )

    assert len(rows) == 1
    assert rows[0].asset_id == asset.id
    assert rows[0].asset_version_id == version.id
    assert rows[0].usage_policy == "required"
    assert rows[0].position == 1000
    assert preset.version == 8
    session.delete.assert_called_once_with(old)
    session.add_all.assert_called_once_with(rows)
    assert session.flush.call_count == 2
    session.commit.assert_not_called()


def test_unchanged_binding_keeps_old_version_and_reports_update(monkeypatch) -> None:
    session = _session()
    novel_id = uuid4()
    asset, selected = _pair(current_is_selected=False)
    binding = NovelAssetBinding(
        id=uuid4(),
        novel_id=novel_id,
        asset_id=asset.id,
        asset_version_id=selected.id,
        usage_policy="preferred",
        position=0,
        lifecycle_state="active",
        version=3,
        operation_key="old-op",
        operation_hash="c" * 64,
    )
    monkeypatch.setattr(service, "_lock_novel", lambda *_: object())
    monkeypatch.setattr(service, "_active_bindings", lambda *_: [binding])
    monkeypatch.setattr(
        service,
        "_validate_version_selections",
        lambda *_args, **_kwargs: {asset.id: (asset, selected)},
    )

    result = replace_novel_bindings(
        session,
        novel_id,
        expected_binding_versions={asset.id: 3},
        selections=[
            VersionSelection(
                asset_id=asset.id,
                asset_version_id=selected.id,
                usage_policy=UsagePolicy.PREFERRED,
                position=0,
            )
        ],
        operation_key="no-change",
    )

    assert result.changed is False
    assert result.bindings[0].asset_version.id == selected.id
    assert result.bindings[0].update_available is True
    assert binding.asset_version_id == selected.id
    assert binding.version == 3
    session.add.assert_not_called()
    session.flush.assert_not_called()


def test_explicit_binding_change_is_cas_versioned(monkeypatch) -> None:
    session = _session()
    novel_id = uuid4()
    asset, old_version = _pair(current_is_selected=False)
    new_version = PrivateAssetVersion(
        id=asset.current_version_id,
        asset_id=asset.id,
        version_number=4,
        title="新版",
        content="新版内容",
        metadata_json={},
        source_json={},
        rights_json={},
        content_hash="d" * 64,
        operation_key="new-version",
        operation_hash="e" * 64,
    )
    binding = NovelAssetBinding(
        id=uuid4(),
        novel_id=novel_id,
        asset_id=asset.id,
        asset_version_id=old_version.id,
        usage_policy="preferred",
        position=0,
        lifecycle_state="active",
        version=3,
        operation_key="old-op",
        operation_hash="f" * 64,
    )
    monkeypatch.setattr(service, "_lock_novel", lambda *_: object())
    monkeypatch.setattr(service, "_active_bindings", lambda *_: [binding])
    monkeypatch.setattr(
        service,
        "_validate_version_selections",
        lambda *_args, **_kwargs: {asset.id: (asset, new_version)},
    )

    result = replace_novel_bindings(
        session,
        novel_id,
        expected_binding_versions={asset.id: 3},
        selections=[
            VersionSelection(
                asset_id=asset.id,
                asset_version_id=new_version.id,
                usage_policy=UsagePolicy.CONTEXT_ONLY,
                position=1000,
            )
        ],
        operation_key="explicit-upgrade",
    )

    assert result.changed is True
    assert binding.asset_version_id == new_version.id
    assert binding.usage_policy == "context_only"
    assert binding.position == 1000
    assert binding.lifecycle_state == "active"
    assert binding.version == 4
    assert result.bindings[0].update_available is False
    assert session.flush.call_count == 2
    session.commit.assert_not_called()


def test_archived_binding_can_be_carried_forward_unchanged_while_adding_asset(
    monkeypatch,
) -> None:
    session = _session()
    novel_id = uuid4()
    archived_asset, archived_version = _pair(current_is_selected=True)
    archived_asset.archived = True
    new_asset, new_version = _pair(current_is_selected=True)
    existing_binding = NovelAssetBinding(
        id=uuid4(),
        novel_id=novel_id,
        asset_id=archived_asset.id,
        asset_version_id=archived_version.id,
        usage_policy="preferred",
        position=0,
        lifecycle_state="active",
        version=2,
        operation_key="prior-binding",
        operation_hash="a" * 64,
    )
    pairs = {
        archived_asset.id: (archived_asset, archived_version),
        new_asset.id: (new_asset, new_version),
    }
    monkeypatch.setattr(service, "_lock_novel", lambda *_: object())
    monkeypatch.setattr(service, "_active_bindings", lambda *_: [existing_binding])
    monkeypatch.setattr(
        service,
        "_validate_version_selections",
        lambda *_args, **_kwargs: pairs,
    )

    result = replace_novel_bindings(
        session,
        novel_id,
        expected_binding_versions={archived_asset.id: 2},
        selections=[
            VersionSelection(
                asset_id=archived_asset.id,
                asset_version_id=archived_version.id,
                usage_policy=UsagePolicy.PREFERRED,
                position=0,
            ),
            VersionSelection(
                asset_id=new_asset.id,
                asset_version_id=new_version.id,
                usage_policy=UsagePolicy.PREFERRED,
                position=1,
            ),
        ],
        operation_key="add-beside-archived-binding",
    )

    assert result.changed is True
    assert existing_binding.lifecycle_state == "active"
    assert existing_binding.version == 2
    assert {item.asset.id for item in result.bindings} == {
        archived_asset.id,
        new_asset.id,
    }
    session.add.assert_called_once()


def test_archived_binding_cannot_be_changed_during_set_replacement(monkeypatch) -> None:
    session = _session()
    novel_id = uuid4()
    asset, version = _pair(current_is_selected=True)
    asset.archived = True
    binding = NovelAssetBinding(
        id=uuid4(),
        novel_id=novel_id,
        asset_id=asset.id,
        asset_version_id=version.id,
        usage_policy="preferred",
        position=0,
        lifecycle_state="active",
        version=2,
        operation_key="prior-binding",
        operation_hash="a" * 64,
    )
    monkeypatch.setattr(service, "_lock_novel", lambda *_: object())
    monkeypatch.setattr(service, "_active_bindings", lambda *_: [binding])
    monkeypatch.setattr(
        service,
        "_validate_version_selections",
        lambda *_args, **_kwargs: {asset.id: (asset, version)},
    )

    with pytest.raises(service.PrivateLibraryNotFoundError):
        replace_novel_bindings(
            session,
            novel_id,
            expected_binding_versions={asset.id: 2},
            selections=[
                VersionSelection(
                    asset_id=asset.id,
                    asset_version_id=version.id,
                    usage_policy=UsagePolicy.REQUIRED,
                    position=0,
                )
            ],
            operation_key="change-archived-binding",
        )


def test_existing_combination_applies_its_fixed_version_and_preserves_other_bindings(
    monkeypatch,
) -> None:
    session = _session()
    novel_id = uuid4()
    preset = AssetPreset(
        id=uuid4(), title="雨夜用词", description="", version=2, archived=False,
    )
    preset_asset, preset_version = _pair(current_is_selected=False)
    item = AssetPresetItem(
        id=uuid4(),
        preset_id=preset.id,
        asset_id=preset_asset.id,
        asset_version_id=preset_version.id,
        usage_policy="preferred",
        position=1000,
    )
    other_asset, other_version = _pair(current_is_selected=True)
    other_binding = NovelAssetBinding(
        id=uuid4(), novel_id=novel_id, asset_id=other_asset.id,
        asset_version_id=other_version.id, usage_policy="context_only",
        position=5, lifecycle_state="active", version=3,
        operation_key="prior-binding", operation_hash="a" * 64,
    )
    other_view = service.BindingView(
        binding=other_binding,
        asset=other_asset,
        asset_version=other_version,
        update_available=False,
    )
    monkeypatch.setattr(service, "_lock_preset", lambda *_: preset)
    monkeypatch.setattr(service, "list_novel_bindings", lambda *_: [other_view])
    replaced = MagicMock(return_value=service.BindingSetResult(tuple(), True))
    monkeypatch.setattr(service, "replace_novel_bindings", replaced)
    session.scalars.return_value.all.return_value = [item]

    result = apply_preset_to_novel(
        session, novel_id, preset.id, operation_key="apply-existing-combination",
    )

    assert result.changed is True
    arguments = replaced.call_args.kwargs
    assert arguments["expected_binding_versions"] == {other_asset.id: 3}
    selections = arguments["selections"]
    assert [(row.asset_id, row.asset_version_id) for row in selections] == [
        (preset_asset.id, preset_version.id),
        (other_asset.id, other_version.id),
    ]
    assert selections[1].usage_policy is UsagePolicy.CONTEXT_ONLY
