from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.creative_data_models import NovelAssetBinding, PrivateAssetVersion
from backend.models import AssetPreset, AssetPresetItem, PrivateAsset
from backend.private_library import (
    UsagePolicy,
    VersionSelection,
    replace_novel_bindings,
    replace_preset_items,
)
from backend.private_library import service


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
