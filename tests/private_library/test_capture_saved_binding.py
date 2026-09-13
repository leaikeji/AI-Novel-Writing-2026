"""Save-and-use binds the saved version; only an explicit temporary PostgreSQL DB."""
import hashlib
from uuid import uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend import creative_data_api as api
from backend.creative_data_models import PrivateAssetVersion
from backend.models import Novel
from backend.private_library import UsagePolicy, VersionSelection
from backend.private_library.lexicon_contracts import LexiconEntry, LexiconPack
from backend.private_library.service import (
    create_asset, list_novel_bindings, replace_novel_bindings, set_novel_asset_enabled,
    update_asset,
)
from tests.private_library.test_catalog_pagination import TEST_DATABASE_URL, _isolated_test_database_url


@pytest.fixture
def capture_session():
    if not TEST_DATABASE_URL:
        pytest.skip("explicit temporary PostgreSQL code database required")
    engine = create_engine(_isolated_test_database_url())
    with engine.connect() as connection:
        outer = connection.begin()
        with Session(connection, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
            yield session
        outer.rollback()
    engine.dispose()


def request(novel_id, *, target=None, category="vocabulary", term="电工胶布"):
    return api.PrivateLibraryCaptureCreate(
        selection_id=uuid4(), selected_text=term,
        selected_text_sha256=hashlib.sha256(term.encode()).hexdigest(),
        source_value_sha256="b" * 64, source_document_id=str(uuid4()), field_id="chapter.body",
        category=category, destination="use_current_novel", novel_id=novel_id,
        target_asset_id=target, operation_key=f"capture:{uuid4()}",
    )


def seed(session, category="vocabulary", usage="preferred"):
    novel, other_novel = Novel(title="缺氧：末日地下世界"), Novel(title="潮声之后")
    session.add_all([novel, other_novel]); session.flush()
    pack = LexiconPack(entries=[LexiconEntry(entry_id="entry_0001", term="管钳", action="recommend")])
    target = create_asset(session, asset_type=category, title="本书材料", content="管钳",
        metadata=pack.model_dump(mode="json") if category == "vocabulary" else {}, operation_key=str(uuid4()))
    target.asset.scope_kind = "novel"; target.asset.scope_novel_id = novel.id
    other = create_asset(session, asset_type="plot", title="停电之后", content="居民轮流守护水泵。",
                         operation_key=str(uuid4()))
    selected = [VersionSelection(other.asset.id, other.asset_version.id, UsagePolicy.REQUIRED, 9)]
    if usage != "missing":
        selected.append(VersionSelection(target.asset.id, target.asset_version.id, UsagePolicy(usage), 4))
    replace_novel_bindings(session, novel.id, expected_binding_versions={}, selections=selected, operation_key=str(uuid4()))
    replace_novel_bindings(session, other_novel.id, expected_binding_versions={}, selections=[
        VersionSelection(other.asset.id, other.asset_version.id, UsagePolicy.PREFERRED, 3),
    ], operation_key=str(uuid4()))
    other.asset.archived = True
    session.commit()
    return novel, other_novel, target, other


def binding_state(session, novel_id):
    return {item.asset.id: (item.asset_version.id, item.binding.version,
                           item.binding.usage_policy, item.binding.position)
            for item in list_novel_bindings(session, novel_id)}


@pytest.mark.parametrize("category", ["vocabulary", "idea"])
@pytest.mark.parametrize("usage", ["missing", "preferred", "required", "prohibited"])
def test_capture_uses_new_version_and_preserves_other_bindings(capture_session, category, usage):
    session = capture_session
    novel, other_novel, target, other = seed(session, category, usage)
    before = binding_state(session, novel.id)
    other_before = binding_state(session, other_novel.id)
    old_version = target.asset_version.id
    result = api.private_library_capture_create(request(novel.id, target=target.asset.id, category=category), session)
    after = binding_state(session, novel.id)
    assert result["saved"] and result["used_by_current_novel"]
    assert str(after[target.asset.id][0]) == result["asset"]["current_version_id"]
    assert after[target.asset.id][0] != old_version
    assert after[target.asset.id][2] == (usage if usage in {"preferred", "required"} else "preferred")
    assert after[target.asset.id][3] == (10 if usage == "missing" else 4)
    assert after[other.asset.id] == before[other.asset.id]
    assert binding_state(session, other_novel.id) == other_before
    # The previous immutable version still exists; no historical content rewritten.
    assert session.get(PrivateAssetVersion, old_version).content == "管钳"


def test_default_collection_capture_updates_an_already_enabled_pack(capture_session):
    session = capture_session
    novel = Novel(title="缺氧：末日地下世界"); session.add(novel); session.commit()
    first = api.private_library_capture_create(request(novel.id, term="管钳"), session)
    second = api.private_library_capture_create(request(novel.id), session)
    assert first["asset"]["id"] == second["asset"]["id"]
    assert second["used_by_current_novel"]
    bound = list_novel_bindings(session, novel.id)
    assert len(bound) == 1 and str(bound[0].asset_version.id) == second["asset"]["current_version_id"]
    assert {item["term"] for item in bound[0].asset_version.metadata_json["entries"]} == {"管钳", "电工胶布"}


def test_capture_replay_after_author_disables_does_not_reenable(capture_session):
    session = capture_session
    novel, _, target, _ = seed(session)
    payload = request(novel.id, target=target.asset.id)
    first = api.private_library_capture_create(payload, session)
    version = binding_state(session, novel.id)[target.asset.id][1]
    set_novel_asset_enabled(session, novel_id=novel.id, asset_id=target.asset.id,
        expected_binding_version=version, enabled=False, operation_key="author-disables-capture")
    session.commit()
    before = binding_state(session, novel.id)
    replay = api.private_library_capture_create(payload, session)
    assert replay["saved"] and not replay["used_by_current_novel"]
    assert replay["asset"]["current_version_id"] == first["asset"]["current_version_id"]
    assert binding_state(session, novel.id) == before


def test_capture_binding_failure_rolls_back_saved_version(capture_session, monkeypatch):
    session = capture_session
    novel, _, target, _ = seed(session)
    root_version, old_version = target.asset.version, target.asset.current_version_id
    before = binding_state(session, novel.id)
    def fail(*args, **kwargs):
        raise RuntimeError("binding unavailable")
    monkeypatch.setattr(api, "use_saved_asset_version", fail)
    with pytest.raises(RuntimeError, match="binding unavailable"):
        api.private_library_capture_create(request(novel.id, target=target.asset.id), session)
    session.expire_all()
    assert target.asset.version == root_version and target.asset.current_version_id == old_version
    assert binding_state(session, novel.id) == before
    assert len(session.scalars(select(PrivateAssetVersion).where(PrivateAssetVersion.asset_id == target.asset.id)).all()) == 1


def test_capture_cannot_write_another_novels_pack(capture_session):
    session = capture_session
    novel, other_novel, target, _ = seed(session)
    old = target.asset.current_version_id
    with pytest.raises(HTTPException) as error:
        api.private_library_capture_create(request(other_novel.id, target=target.asset.id), session)
    assert error.value.status_code == 404
    session.expire_all()
    assert target.asset.current_version_id == old


@pytest.mark.parametrize("category", ["vocabulary", "idea"])
def test_capture_does_not_adopt_other_pending_pack_changes(capture_session, category):
    session = capture_session
    novel, _, target, _ = seed(session, category)
    pending = update_asset(session, target.asset.id,
        expected_root_version=target.asset.version, operation_key=str(uuid4()),
        title="本书材料整理", content="尚未采用的资料调整")
    session.commit()
    before = binding_state(session, novel.id)
    root_version = target.asset.version
    with pytest.raises(HTTPException) as error:
        api.private_library_capture_create(request(novel.id, target=target.asset.id, category=category), session)
    assert error.value.status_code == 409
    assert "尚未采用" in error.value.detail["message"]
    session.expire_all()
    assert target.asset.version == root_version
    assert target.asset.current_version_id == pending.asset_version.id
    assert binding_state(session, novel.id) == before
