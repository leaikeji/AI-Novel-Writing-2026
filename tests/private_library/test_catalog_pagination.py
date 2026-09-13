"""Catalogue code checks; PostgreSQL cases only use an explicit temporary test DB."""
from datetime import datetime, timedelta, timezone
import os
import re
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from backend.creative_data_models import LibraryChangeRequest, NovelAssetBinding, PrivateAssetVersion
from backend.models import Novel, PrivateAsset
from backend.private_library.errors import PrivateLibraryIdempotencyConflict, PrivateLibraryValidationError
from backend.private_library.lexicon_service import get_scoped_asset_view, list_scoped_assets
from backend.private_library.maintenance import SqlAlchemyChangeRequestStore, query_library
from backend.private_library.service import (
    create_asset, list_novel_bindings, set_novel_asset_enabled, update_asset,
)
from tests.private_library.test_maintenance import _access


@pytest.mark.parametrize("arguments", [
    {"offset": True}, {"offset": -1}, {"offset": "50"},
    {"limit": 101}, {"limit": 0}, {"limit": True},
    {"scope_filter": "foreign"}, {"enabled_filter": "sometimes"},
    {"projection": "everything"}, {"scope_filter": "novel"},
    {"enabled_filter": "enabled"}, {"enabled_filter": "disabled"},
    {"scope_filter": []}, {"enabled_filter": {}}, {"projection": []},
    {"include_archived": "true"}, {"asset_type": []},
])
def test_catalog_rejects_invalid_or_untrusted_filters_before_query(arguments):
    session = MagicMock(spec=Session)
    with pytest.raises(PrivateLibraryValidationError):
        list_scoped_assets(session, **arguments)
    session.execute.assert_not_called()
    session.scalar.assert_not_called()


def test_summary_is_a_column_projection_and_search_is_before_paging():
    session = MagicMock(spec=Session)
    session.scalar.return_value = 0
    session.execute.return_value.mappings.return_value.all.return_value = []
    result = list_scoped_assets(session, query="潮声%_", projection="summary", offset=100)
    statement = session.execute.call_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "jsonb_path_query_array" in sql
    assert "private_assets.tags_json" in sql
    assert "private_asset_versions.metadata_json AS metadata" not in sql
    assert "content" not in statement.selected_columns.keys()
    assert "metadata" not in statement.selected_columns.keys()
    assert "substr(private_asset_versions.content" in sql
    assert sql.index("WHERE") < sql.index("LIMIT")
    assert "FOR UPDATE" not in sql
    assert result.total == 0
    assert result.has_more is False
    assert result.next_offset is None
    session.get.assert_not_called()


def test_prohibited_detail_retains_active_binding_version_for_enable_cas():
    novel_id, asset_id, version_id = uuid4(), uuid4(), uuid4()
    asset = PrivateAsset(
        id=asset_id, asset_type="vocabulary", title="慎选用词", version=1,
        current_version_id=version_id, scope_kind="library", tags_json=[], archived=False,
    )
    version = PrivateAssetVersion(
        id=version_id, asset_id=asset_id, title=asset.title, content="词包说明", metadata_json={},
    )
    binding = NovelAssetBinding(
        novel_id=novel_id, asset_id=asset_id, asset_version_id=version_id,
        usage_policy="prohibited", lifecycle_state="active", version=7,
    )
    session = MagicMock(spec=Session)
    session.get.side_effect = [asset, version]
    session.scalar.side_effect = [1, binding]
    view = get_scoped_asset_view(session, asset_id, novel_id=novel_id)
    assert view["enabled"] is False
    assert view["binding_version"] == 7


TEST_DATABASE_URL = os.environ.get("AI_NOVEL_TEST_DATABASE_URL", "").strip()
PRODUCTION_DATABASE_URL = os.environ.get("AI_NOVEL_DATABASE_URL", "").strip()
SAFE_TEST_DATABASE_NAME = re.compile(
    r"^[a-zA-Z0-9][a-zA-Z0-9_-]*_test(?:_[a-zA-Z0-9_-]+)?$"
)


def _isolated_test_database_url() -> str:
    """Validate the explicit test target before creating any engine/connection."""
    test_url = make_url(TEST_DATABASE_URL)
    if not SAFE_TEST_DATABASE_NAME.fullmatch(test_url.database or ""):
        raise RuntimeError(
            "AI_NOVEL_TEST_DATABASE_URL must target an explicitly named *_test database"
        )
    if PRODUCTION_DATABASE_URL:
        production_url = make_url(PRODUCTION_DATABASE_URL)
        test_target = (test_url.host, test_url.port or 5432, test_url.database)
        production_target = (
            production_url.host, production_url.port or 5432, production_url.database,
        )
        if test_target == production_target:
            raise RuntimeError(
                "AI_NOVEL_TEST_DATABASE_URL must not target AI_NOVEL_DATABASE_URL"
            )
    return TEST_DATABASE_URL


@pytest.fixture
def catalog_session():
    if not TEST_DATABASE_URL:
        pytest.skip("explicit temporary integration database not configured")
    engine = create_engine(_isolated_test_database_url())
    # Nothing is committed, and no cleanup query can touch unrelated records.
    with Session(engine, expire_on_commit=False) as session:
        yield session
        session.rollback()
    engine.dispose()


@pytest.mark.parametrize("test_url,production_url,message", [
    ("postgresql://localhost/novel_world", "", "explicitly named"),
    ("postgresql://localhost/test", "", "explicitly named"),
    ("postgresql://reader@localhost/novel_world_test",
     "postgresql://writer@localhost:5432/novel_world_test", "must not target"),
])
def test_catalog_database_url_is_rejected_before_engine_creation(
    monkeypatch, test_url, production_url, message,
):
    monkeypatch.setitem(globals(), "TEST_DATABASE_URL", test_url)
    monkeypatch.setitem(globals(), "PRODUCTION_DATABASE_URL", production_url)
    engine_factory = MagicMock()
    monkeypatch.setitem(globals(), "create_engine", engine_factory)
    fixture = catalog_session.__wrapped__()
    with pytest.raises(RuntimeError, match=message):
        next(fixture)
    engine_factory.assert_not_called()


def test_catalog_database_url_accepts_a_distinct_explicit_test_target(monkeypatch):
    test_url = "postgresql://localhost:5432/novel_world_test_catalog"
    monkeypatch.setitem(globals(), "TEST_DATABASE_URL", test_url)
    monkeypatch.setitem(globals(), "PRODUCTION_DATABASE_URL", "postgresql://localhost/novel_world")
    assert _isolated_test_database_url() == test_url


def _create_catalog_asset(session, *, title, index=0, asset_type="vocabulary", metadata=None,
                          tags=(), scope_novel_id=None, archived=False):
    result = create_asset(
        session, asset_type=asset_type, title=title,
        content=f"词包说明 {index}", tags=list(tags), metadata=metadata or {},
        operation_key=f"catalog-{uuid4()}",
    )
    result.asset.scope_kind = "novel" if scope_novel_id else "library"
    result.asset.scope_novel_id = scope_novel_id
    result.asset.archived = archived
    result.asset.updated_at = datetime.now(timezone.utc) - timedelta(days=index)
    session.flush()
    return result


def test_postgres_catalog_searches_entire_library_and_uses_fixed_query_count(catalog_session):
    session = catalog_session
    prefix = f"目录-{uuid4()}"
    for index in range(151):
        _create_catalog_asset(session, title=f"{prefix}-{index}", index=index,
                              asset_type="idea" if index % 2 else "vocabulary")
    target = _create_catalog_asset(
        session, title=f"{prefix}-沉井", index=200, tags=["跨页地下工事"],
        metadata={"schema_version": "lexicon-pack/1", "entries": [{
            "term": "跨页排水坡度", "variants": ["跨页沟底落差"],
            "note": "跨页用于工事描写", "categories": ["跨页抢修动作"],
            "replacement_hint": "跨页写出具体工具", "action": "recommend",
        }]},
    )
    first = list_scoped_assets(session, query=prefix, limit=100, projection="summary")
    assert first.total == 152 and first.next_offset == 100
    assert str(target.asset.id) not in {item["id"] for item in first.items}
    second = list_scoped_assets(session, query=prefix, offset=first.next_offset,
                                limit=100, projection="summary")
    assert len(second.items) == 52 and second.next_offset is None
    assert str(target.asset.id) in {item["id"] for item in second.items}
    for query in ("跨页地下工事", "跨页排水坡度", "跨页沟底落差", "跨页用于工事描写",
                  "跨页抢修动作", "跨页写出具体工具"):
        page = list_scoped_assets(session, query=query, projection="summary")
        assert [item["id"] for item in page.items] == [str(target.asset.id)]
        assert page.total == 1
        assert page.items[0]["entry_count"] == 1
        assert not {"content", "metadata", "lexicon"}.intersection(page.items[0])
        tool_page = query_library(SqlAlchemyChangeRequestStore(session), _access(), {
            "kind": "assets", "search": query, "projection": "summary", "offset": 0,
        })
        assert [item["id"] for item in tool_page["items"]] == [str(target.asset.id)]
        assert tool_page["total"] == page.total

    calls = []
    def record(_connection, _cursor, statement, _parameters, _context, _executemany):
        calls.append(statement)
    event.listen(session.bind, "before_cursor_execute", record)
    try:
        list_scoped_assets(session, query=prefix, projection="summary", limit=50)
        count50 = len(calls)
        calls.clear()
        list_scoped_assets(session, query=prefix, projection="summary", limit=100)
        count100 = len(calls)
    finally:
        event.remove(session.bind, "before_cursor_execute", record)
    assert count50 == count100 == 3
    full = list_scoped_assets(session, query="跨页排水坡度")
    assert full.items[0]["detail_loaded"] is True
    assert full.items[0]["lexicon"]["entries"][0]["term"] == "跨页排水坡度"


def test_postgres_scope_enabled_archive_and_literal_search_share_one_query(catalog_session):
    session = catalog_session
    own, other = Novel(title="pytest-目录甲书"), Novel(title="pytest-目录乙书")
    session.add_all([own, other])
    session.flush()
    prefix = f"scope-{uuid4()}"
    common = _create_catalog_asset(session, title=f"{prefix}-通用")
    local = _create_catalog_asset(session, title=f"{prefix}-本书", scope_novel_id=own.id)
    foreign = _create_catalog_asset(session, title=f"{prefix}-其他书", scope_novel_id=other.id)
    archived = _create_catalog_asset(session, title=f"{prefix}-已归档", archived=True)
    for position, asset in enumerate((common, local, archived)):
        session.add(NovelAssetBinding(
            novel_id=own.id, asset_id=asset.asset.id, asset_version_id=asset.asset_version.id,
            usage_policy="prohibited" if asset is local else "preferred", position=position,
            lifecycle_state="active", version=position + 1,
            operation_key=f"query-binding-{uuid4()}", operation_hash="a" * 64,
        ))
    session.flush()
    enabled = list_scoped_assets(session, novel_id=own.id, query=prefix,
                                 enabled_filter="enabled", include_archived=True)
    assert {item["id"] for item in enabled.items} == {str(common.asset.id), str(archived.asset.id)}
    assert all(item["enabled"] for item in enabled.items)
    disabled = list_scoped_assets(session, novel_id=own.id, query=prefix,
                                  scope_filter="novel", enabled_filter="disabled")
    assert [item["id"] for item in disabled.items] == [str(local.asset.id)]
    assert disabled.items[0]["binding_count"] == 1
    assert disabled.items[0]["enabled"] is False
    assert disabled.items[0]["binding_version"] == 2
    set_novel_asset_enabled(session, novel_id=own.id, asset_id=local.asset.id,
        expected_binding_version=disabled.items[0]["binding_version"],
        enabled=True, operation_key="enable-prohibited-with-projected-cas")
    reenabled = get_scoped_asset_view(session, local.asset.id, novel_id=own.id)
    assert reenabled["enabled"] is True
    assert reenabled["binding_version"] == 3
    library = list_scoped_assets(session, query=prefix, include_archived=True)
    assert str(foreign.asset.id) not in {item["id"] for item in library.items}
    assert str(local.asset.id) not in {item["id"] for item in library.items}
    literal = _create_catalog_asset(session, title=f"{prefix}-百分比%_\\刻度")
    exact = list_scoped_assets(session, query="%_\\", projection="summary")
    assert [item["id"] for item in exact.items] == [str(literal.asset.id)]


def _toggle_receipts(session, novel_id):
    return session.scalars(select(LibraryChangeRequest).where(
        LibraryChangeRequest.scope_novel_id == novel_id,
    )).all()


def test_postgres_enable_disable_replay_and_noop_keep_durable_receipts(catalog_session):
    session = catalog_session
    novel = Novel(title="pytest-启停回执")
    session.add(novel); session.flush()
    asset = _create_catalog_asset(session, title="pytest-启停词包").asset
    request = dict(novel_id=novel.id, asset_id=asset.id, expected_binding_version=0,
                   enabled=True, operation_key="enable-a")
    set_novel_asset_enabled(session, **request)
    binding = list_novel_bindings(session, novel.id)[0].binding
    set_novel_asset_enabled(session, **{**request, "enabled": False,
        "expected_binding_version": binding.version, "operation_key": "disable-b"})
    assert list_novel_bindings(session, novel.id) == []
    set_novel_asset_enabled(session, **request)
    assert list_novel_bindings(session, novel.id) == []
    assert len(_toggle_receipts(session, novel.id)) == 2
    noop = {**request, "enabled": False, "operation_key": "already-disabled"}
    set_novel_asset_enabled(session, **noop)
    receipts = _toggle_receipts(session, novel.id)
    assert len(receipts) == 3
    receipt = next(row for row in receipts if row.source_json["operation_key"] == "already-disabled")
    assert receipt.state == "applied" and receipt.result_json["changed"] is False
    with pytest.raises(PrivateLibraryIdempotencyConflict):
        set_novel_asset_enabled(session, **{**noop, "enabled": True})
    other = _create_catalog_asset(session, title="pytest-另一词包").asset
    with pytest.raises(PrivateLibraryIdempotencyConflict):
        set_novel_asset_enabled(session, **{**noop, "asset_id": other.id})
    assert list_novel_bindings(session, novel.id) == []
    assert len(_toggle_receipts(session, novel.id)) == 3


def test_postgres_repeated_enable_never_advances_a_fixed_version(catalog_session):
    session = catalog_session
    novel = Novel(title="pytest-固定绑定保持")
    session.add(novel); session.flush()
    original = _create_catalog_asset(session, title="pytest-固定词包")
    set_novel_asset_enabled(session, novel_id=novel.id, asset_id=original.asset.id,
        expected_binding_version=0, enabled=True, operation_key="initial-enable")
    before = list_novel_bindings(session, novel.id)[0].binding
    before_hash = before.operation_hash
    update_asset(session, original.asset.id, expected_root_version=original.asset.version,
        operation_key="update-source", title="pytest-固定词包新版", content="新版说明")
    set_novel_asset_enabled(session, novel_id=novel.id, asset_id=original.asset.id,
        expected_binding_version=before.version, enabled=True, operation_key="repeat-enable")
    after = list_novel_bindings(session, novel.id)[0]
    assert after.asset_version.id == original.asset_version.id
    assert after.asset.current_version_id != after.asset_version.id
    assert after.binding.operation_hash == before_hash
    receipt = next(row for row in _toggle_receipts(session, novel.id)
                   if row.source_json["operation_key"] == "repeat-enable")
    assert receipt.result_json["changed"] is False


def test_postgres_toggle_and_receipt_rollback_together(catalog_session):
    session = catalog_session
    novel = Novel(title="pytest-启停事务恢复")
    session.add(novel); session.flush()
    asset = _create_catalog_asset(session, title="pytest-事务词包").asset
    request = dict(novel_id=novel.id, asset_id=asset.id, expected_binding_version=0,
                   enabled=True, operation_key="recoverable-toggle")
    with pytest.raises(RuntimeError, match="caller failed"):
        with session.begin_nested():
            set_novel_asset_enabled(session, **request)
            assert len(list_novel_bindings(session, novel.id)) == 1
            assert len(_toggle_receipts(session, novel.id)) == 1
            raise RuntimeError("caller failed")
    assert list_novel_bindings(session, novel.id) == []
    assert _toggle_receipts(session, novel.id) == []
    set_novel_asset_enabled(session, **request)
    assert len(list_novel_bindings(session, novel.id)) == 1
    assert len(_toggle_receipts(session, novel.id)) == 1
