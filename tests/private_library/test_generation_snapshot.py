from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.creative_data_models import NovelAssetBinding, PrivateAssetVersion
from backend.models import AssetPreset, AssetPresetItem, Novel, PrivateAsset
from backend.private_library import (
    DirectAssetSelection,
    UsagePolicy,
    build_generation_asset_snapshot,
)
from backend.private_library.hashing import canonical_hash
from backend.private_library import service


def _version(asset_id, *, number: int, title: str, content: str):
    payload = {
        "title": title,
        "content": content,
        "metadata": {"number": number},
        "source": {"origin": "author"},
        "rights": {"cloud": True},
    }
    return PrivateAssetVersion(
        id=uuid4(),
        asset_id=asset_id,
        version_number=number,
        title=title,
        content=content,
        metadata_json=payload["metadata"],
        source_json=payload["source"],
        rights_json=payload["rights"],
        content_hash=canonical_hash(payload),
        operation_key=f"version-{number}",
        operation_hash="a" * 64,
    )


def test_generation_snapshot_copies_exact_versions_and_selection_sources(monkeypatch) -> None:
    session = MagicMock(spec=Session)
    novel = Novel(id=uuid4(), title="测试小说")
    asset = PrivateAsset(
        id=uuid4(),
        asset_type="plot",
        title="根当前标题",
        content="根当前内容",
        version=3,
        archived=False,
        tags_json=[],
        source_json={},
        rights_json={},
    )
    old = _version(asset.id, number=1, title="固定旧标题", content="固定旧内容")
    current = _version(asset.id, number=3, title="当前标题", content="当前内容")
    asset.current_version_id = current.id
    preset = AssetPreset(
        id=uuid4(), title="固定预设", description="", version=1, archived=False
    )
    preset_item = AssetPresetItem(
        id=uuid4(),
        preset_id=preset.id,
        asset_id=asset.id,
        asset_version_id=old.id,
        usage_policy="required",
        position=1000,
    )
    binding = NovelAssetBinding(
        id=uuid4(),
        novel_id=novel.id,
        asset_id=asset.id,
        asset_version_id=old.id,
        usage_policy="context_only",
        position=2000,
        lifecycle_state="active",
        version=1,
        operation_key="bind",
        operation_hash="b" * 64,
    )

    objects = {
        (Novel, novel.id): novel,
        (PrivateAsset, asset.id): asset,
        (PrivateAssetVersion, old.id): old,
        (PrivateAssetVersion, current.id): current,
        (AssetPreset, preset.id): preset,
    }
    session.get.side_effect = lambda model, identity: objects.get((model, identity))
    session.scalars.return_value.all.return_value = [preset_item]
    monkeypatch.setattr(service, "_active_bindings", lambda *_: [binding])

    snapshot = build_generation_asset_snapshot(
        session,
        novel.id,
        direct_selections=[
            DirectAssetSelection(
                asset_id=asset.id,
                usage_policy=UsagePolicy.PREFERRED,
                selection_key="manual-choice",
            )
        ],
        preset_ids=[preset.id],
        include_novel_bindings=True,
    )

    assert [item["selection_source"]["kind"] for item in snapshot] == [
        "direct",
        "preset",
        "novel_binding",
    ]
    assert snapshot[0]["asset_version_id"] == str(current.id)
    assert snapshot[0]["content"] == "当前内容"
    assert snapshot[0]["selection_source"]["source_id"] == "manual-choice"
    assert snapshot[1]["asset_version_id"] == str(old.id)
    assert snapshot[1]["title"] == "固定旧标题"
    assert snapshot[1]["usage_policy"] == "required"
    assert snapshot[2]["asset_version_id"] == str(old.id)
    assert snapshot[2]["content"] == "固定旧内容"
    assert snapshot[2]["usage_policy"] == "context_only"
    assert all(
        item["content_hash"] in {old.content_hash, current.content_hash}
        for item in snapshot
    )

    # Mutating the compatibility projection cannot change the already-copied
    # snapshot or the fixed preset/binding selection.
    asset.title = "稍后更新的根标题"
    asset.content = "稍后更新的根内容"
    assert snapshot[1]["title"] == "固定旧标题"
    assert snapshot[2]["content"] == "固定旧内容"

    session.add.assert_not_called()
    session.add_all.assert_not_called()
    session.delete.assert_not_called()
    session.flush.assert_not_called()
    session.commit.assert_not_called()
