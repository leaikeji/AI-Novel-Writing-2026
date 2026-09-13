from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from backend.creative_data_models import NovelAssetBinding, PrivateAssetVersion
from backend.models import PrivateAsset
from backend.private_library import service
from backend.private_library.contracts import UsagePolicy, VersionSelection
from backend.private_library.errors import PrivateLibraryConflictError
from backend.private_library.service import replace_novel_bindings, update_asset


def _session() -> MagicMock:
    return MagicMock(spec=Session)


def _asset_and_version() -> tuple[PrivateAsset, PrivateAssetVersion]:
    asset_id = uuid4()
    version = PrivateAssetVersion(
        id=uuid4(),
        asset_id=asset_id,
        version_number=2,
        title="新标题",
        content="新内容",
        metadata_json={},
        source_json={},
        rights_json={},
        content_hash="a" * 64,
        operation_key="asset-version",
        operation_hash="b" * 64,
    )
    asset = PrivateAsset(
        id=asset_id,
        asset_type="vocabulary",
        title="旧标题",
        content="旧内容",
        version=3,
        archived=False,
        current_version_id=version.id,
        tags_json=["旧标签"],
        source_json={},
        rights_json={},
    )
    return asset, version


def test_update_asset_consumes_generator_tags_once(monkeypatch) -> None:
    session = _session()
    asset, current = _asset_and_version()
    prior: list[PrivateAssetVersion | None] = [None]
    monkeypatch.setattr(service, "_lock_asset", lambda *_: asset)
    monkeypatch.setattr(service, "_idempotent_asset_version", lambda *_: prior[0])
    monkeypatch.setattr(service, "_current_asset_version", lambda *_: current)

    result = update_asset(
        session,
        asset.id,
        expected_root_version=3,
        operation_key="generator-tags",
        title="新标题",
        content="新内容",
        tags=(item for item in ["标签甲", "标签甲", "标签乙"]),
    )

    assert asset.tags_json == ["标签甲", "标签乙"]
    assert result.asset_version.operation_key == "generator-tags"
    assert result.replayed is False

    prior[0] = result.asset_version
    replay = update_asset(
        session,
        asset.id,
        expected_root_version=3,
        operation_key="generator-tags",
        title="新标题",
        content="新内容",
        tags=["标签甲", "标签乙"],
    )
    assert replay.replayed is True
    assert replay.asset_version is result.asset_version


def _binding_fixture():
    asset, selected = _asset_and_version()
    old_version_id = uuid4()
    novel_id = uuid4()
    binding = NovelAssetBinding(
        id=uuid4(),
        novel_id=novel_id,
        asset_id=asset.id,
        asset_version_id=old_version_id,
        usage_policy="preferred",
        position=0,
        lifecycle_state="active",
        version=3,
        operation_key="older-operation",
        operation_hash="c" * 64,
    )
    selection = VersionSelection(
        asset_id=asset.id,
        asset_version_id=selected.id,
        usage_policy=UsagePolicy.CONTEXT_ONLY,
        position=1000,
    )
    return novel_id, asset, selected, binding, selection


def test_binding_retry_replays_same_desired_state_before_stale_cas(monkeypatch) -> None:
    session = _session()
    novel_id, asset, selected, binding, selection = _binding_fixture()
    refresh = MagicMock()
    monkeypatch.setattr(service, "_lock_novel", lambda *_: object())
    monkeypatch.setattr(service, "_active_bindings", lambda *_: [binding])
    monkeypatch.setattr(
        service,
        "_validate_version_selections",
        lambda *_args, **_kwargs: {asset.id: (asset, selected)},
    )
    monkeypatch.setattr(
        "backend.embedding.indexing.request_active_novel_refresh", refresh
    )

    first = replace_novel_bindings(
        session,
        novel_id,
        expected_binding_versions={asset.id: 3},
        selections=[selection],
        operation_key="same-binding-request",
    )
    assert first.changed is True
    assert binding.version == 4
    assert binding.operation_key == "same-binding-request"

    session.reset_mock()
    session.scalars.return_value.all.return_value = [binding]
    replay = replace_novel_bindings(
        session,
        novel_id,
        expected_binding_versions={asset.id: 3},
        selections=[selection],
        operation_key="same-binding-request",
    )

    assert replay.changed is False
    assert replay.bindings[0].binding is binding
    assert binding.version == 4
    session.flush.assert_not_called()
    assert refresh.call_count == 1


def test_binding_retry_with_same_key_but_different_target_conflicts(monkeypatch) -> None:
    session = _session()
    novel_id, asset, selected, binding, selection = _binding_fixture()
    monkeypatch.setattr(service, "_lock_novel", lambda *_: object())
    monkeypatch.setattr(service, "_active_bindings", lambda *_: [binding])
    monkeypatch.setattr(
        service,
        "_validate_version_selections",
        lambda *_args, **_kwargs: {asset.id: (asset, selected)},
    )
    monkeypatch.setattr(
        "backend.embedding.indexing.request_active_novel_refresh",
        lambda *_args, **_kwargs: None,
    )
    replace_novel_bindings(
        session,
        novel_id,
        expected_binding_versions={asset.id: 3},
        selections=[selection],
        operation_key="reused-key",
    )

    different = VersionSelection(
        asset_id=asset.id,
        asset_version_id=uuid4(),
        usage_policy=UsagePolicy.PREFERRED,
        position=0,
    )
    # Even if the current projection happens to equal the reused request, the
    # durable hash for the original key still attests its different target.
    binding.asset_version_id = different.asset_version_id
    binding.usage_policy = "preferred"
    binding.position = 0
    session.scalars.return_value.all.return_value = [binding]
    with pytest.raises(PrivateLibraryConflictError) as captured:
        replace_novel_bindings(
            session,
            novel_id,
            expected_binding_versions={asset.id: 3},
            selections=[different],
            operation_key="reused-key",
        )

    assert captured.value.code == "novel_asset_bindings_conflict"
    assert binding.version == 4


def test_binding_removal_retry_uses_archived_operation_evidence(monkeypatch) -> None:
    session = _session()
    novel_id, asset, _selected, binding, _selection = _binding_fixture()
    refresh = MagicMock()
    monkeypatch.setattr(service, "_lock_novel", lambda *_: object())
    monkeypatch.setattr(
        service,
        "_active_bindings",
        lambda *_: [binding] if binding.lifecycle_state == "active" else [],
    )
    monkeypatch.setattr(
        service, "_validate_version_selections", lambda *_args, **_kwargs: {}
    )
    monkeypatch.setattr(
        "backend.embedding.indexing.request_active_novel_refresh", refresh
    )

    first = replace_novel_bindings(
        session,
        novel_id,
        expected_binding_versions={asset.id: 3},
        selections=[],
        operation_key="remove-binding",
    )
    assert first.changed is True
    assert binding.lifecycle_state == "archived"

    session.reset_mock()
    session.scalars.return_value.all.return_value = [binding]
    replay = replace_novel_bindings(
        session,
        novel_id,
        expected_binding_versions={asset.id: 3},
        selections=[],
        operation_key="remove-binding",
    )

    assert replay.changed is False
    assert replay.bindings == ()
    assert binding.version == 4
    session.flush.assert_not_called()
    assert refresh.call_count == 1
