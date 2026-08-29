from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from backend.creative_data_models import PrivateAssetVersion
from backend.models import PrivateAsset
from backend.private_library import (
    PrivateLibraryConflictError,
    create_asset,
    list_asset_history,
    restore_asset,
    update_asset,
)
from backend.private_library.hashing import canonical_hash
from backend.private_library import service


def _session() -> MagicMock:
    return MagicMock(spec=Session)


def _content_hash(
    title: str,
    content: str,
    *,
    metadata: dict | None = None,
    source: dict | None = None,
    rights: dict | None = None,
) -> str:
    return canonical_hash(
        {
            "title": title,
            "content": content,
            "metadata": metadata or {},
            "source": source or {},
            "rights": rights or {},
        }
    )


def _root(*, version: int = 1) -> PrivateAsset:
    return PrivateAsset(
        id=uuid4(),
        asset_type="plot",
        title="旧标题",
        content="旧内容",
        version=version,
        archived=False,
        current_version_id=uuid4(),
        tags_json=["旧标签"],
        source_json={"origin": "author"},
        rights_json={"scope": "private"},
    )


def _version(
    asset_id,
    version_number: int,
    *,
    version_id=None,
    title: str = "旧标题",
    content: str = "旧内容",
) -> PrivateAssetVersion:
    return PrivateAssetVersion(
        id=version_id or uuid4(),
        asset_id=asset_id,
        version_number=version_number,
        title=title,
        content=content,
        metadata_json={},
        source_json={"origin": "author"},
        rights_json={"scope": "private"},
        content_hash=_content_hash(
            title,
            content,
            source={"origin": "author"},
            rights={"scope": "private"},
        ),
        operation_key=f"asset-op-{version_number}",
        operation_hash="a" * 64,
    )


def test_create_asset_writes_root_and_first_immutable_version_together() -> None:
    session = _session()
    session.scalar.return_value = None
    asset_id = uuid4()

    result = create_asset(
        session,
        asset_id=asset_id,
        asset_type="plot",
        title="  第一版  ",
        content="  正文素材  ",
        operation_key="create-1",
        tags=["悬疑", "悬疑", "线索"],
        metadata={"era": "近未来"},
        source={"origin": "author"},
        rights={"cloud_embedding": True},
    )

    assert result.replayed is False
    assert result.asset.id == asset_id
    assert result.asset.current_version_id == result.asset_version.id
    assert result.asset.version == 1
    assert result.asset.tags_json == ["悬疑", "线索"]
    assert result.asset_version.version_number == 1
    assert result.asset_version.title == "第一版"
    assert result.asset_version.content == "正文素材"
    assert len(result.asset_version.content_hash) == 64
    session.add.assert_any_call(result.asset)
    session.add.assert_any_call(result.asset_version)
    assert session.flush.call_count == 3
    session.commit.assert_not_called()


def test_update_appends_version_and_advances_pointer_with_cas(monkeypatch) -> None:
    session = _session()
    asset = _root(version=3)
    current = _version(asset.id, 2, version_id=asset.current_version_id)
    monkeypatch.setattr(service, "_lock_asset", lambda *_: asset)
    monkeypatch.setattr(service, "_idempotent_asset_version", lambda *_: None)
    monkeypatch.setattr(service, "_current_asset_version", lambda *_: current)

    result = update_asset(
        session,
        asset.id,
        expected_root_version=3,
        operation_key="update-3",
        title="新标题",
        content="新内容",
        tags=["新标签"],
        metadata={"chapter": 9},
        source={"origin": "author"},
        rights={"scope": "novel"},
    )

    assert result.asset_version.id != current.id
    assert result.asset_version.version_number == 3
    assert current.title == "旧标题"
    assert current.content == "旧内容"
    assert asset.current_version_id == result.asset_version.id
    assert asset.version == 4
    assert asset.title == "新标题"
    assert asset.tags_json == ["新标签"]
    session.add.assert_called_once_with(result.asset_version)
    session.flush.assert_called_once_with()
    session.commit.assert_not_called()


def test_update_rejects_stale_root_without_appending(monkeypatch) -> None:
    session = _session()
    asset = _root(version=4)
    monkeypatch.setattr(service, "_lock_asset", lambda *_: asset)
    monkeypatch.setattr(service, "_idempotent_asset_version", lambda *_: None)

    with pytest.raises(PrivateLibraryConflictError) as captured:
        update_asset(
            session,
            asset.id,
            expected_root_version=3,
            operation_key="stale-update",
            title="不会写入",
            content="不会写入",
        )

    assert captured.value.code == "asset_root_version_conflict"
    session.add.assert_not_called()
    session.flush.assert_not_called()


def test_restore_copies_old_content_into_a_new_version(monkeypatch) -> None:
    session = _session()
    asset = _root(version=5)
    current = _version(asset.id, 5, version_id=asset.current_version_id, title="当前")
    target = _version(asset.id, 2, title="要恢复的标题", content="要恢复的内容")
    monkeypatch.setattr(service, "_lock_asset", lambda *_: asset)
    monkeypatch.setattr(service, "_idempotent_asset_version", lambda *_: None)
    monkeypatch.setattr(service, "_current_asset_version", lambda *_: current)
    session.get.return_value = target

    result = restore_asset(
        session,
        asset.id,
        target.id,
        expected_root_version=5,
        operation_key="restore-2",
    )

    assert result.restored_from_version_id == target.id
    assert result.asset_version.id != target.id
    assert result.asset_version.version_number == 6
    assert result.asset_version.title == target.title
    assert result.asset_version.content == target.content
    assert result.asset_version.content_hash == target.content_hash
    assert target.version_number == 2
    assert asset.current_version_id == result.asset_version.id
    assert asset.version == 6


def test_history_query_is_read_only() -> None:
    session = _session()
    revisions = [_version(uuid4(), 2), _version(uuid4(), 1)]
    session.scalars.return_value.all.return_value = revisions

    assert list_asset_history(session, revisions[0].asset_id, limit=20) == revisions
    session.add.assert_not_called()
    session.add_all.assert_not_called()
    session.delete.assert_not_called()
    session.flush.assert_not_called()
    session.commit.assert_not_called()
