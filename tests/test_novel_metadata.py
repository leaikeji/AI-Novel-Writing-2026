"""Code-level tests use only an explicitly provided workspace database."""
from datetime import datetime, timezone
import os
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.creative_authority.service import get_settings, save_settings
from backend.database import get_session
from backend.models import Novel
from backend.novel_metadata_api import NovelMetadataRequest, router
from backend.novel_metadata_service import update_novel_metadata


@pytest.mark.parametrize('change', [
    {'title': '   '}, {'author_name': ' '}, {'title': '字' * 241},
    {'author_name': '字' * 121}, {'expected_version': 0},
    {'expected_version': True}, {'description': 'not allowed'},
])
def test_metadata_request_rejects_invalid_fields(change):
    with pytest.raises(ValidationError):
        NovelMetadataRequest.model_validate({'title': '危楼余火', 'author_name': '南窗', 'expected_version': 1, **change})


@pytest.fixture
def db():
    url = os.environ.get('PLAN70_METADATA_CODE_DB', '')
    if not url:
        pytest.skip('workspace metadata database not configured')
    assert '@127.0.0.1:25473/ai_novel_s58_test' in url
    engine = create_engine(url)
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(connection, join_transaction_mode='create_savepoint', expire_on_commit=False) as session:
            yield session
        transaction.rollback()
    engine.dispose()


@pytest.fixture
def novel(db):
    item = Novel(title='危楼旧名', author_name='旧笔名', cover_mode='text', background='背景不变')
    db.add(item)
    db.commit()
    return item


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(router, prefix='/api/ai-novel-world-2026')
    app.dependency_overrides[get_session] = lambda: db
    with TestClient(app) as result:
        yield result


def endpoint(novel):
    return f'/api/ai-novel-world-2026/novels/{novel.id}/metadata'


def payload(novel):
    return {'expected_version': novel.version, 'title': ' 危楼余火 ', 'author_name': ' 南窗听雨 '}


def test_metadata_updates_revision_and_preserves_other_settings(client, db, novel):
    original = save_settings(db, novel.id, expected_head_version=0, idempotency_key='original',
                            source_kind='manual', schema_id='novel-settings/1', schema_version=1,
                            settings={'author_name': '旧笔名', 'custom': {'keep': [1, 2]}, 'genre': '都市'})
    db.commit()
    previous = original.revision.settings_json.copy()
    old_version = novel.version
    result = client.put(endpoint(novel), json=payload(novel))
    assert result.status_code == 200
    assert result.json()['title'] == '危楼余火'
    assert result.json()['author_name'] == '南窗听雨'
    assert result.json()['version'] == old_version + 1
    db.expire_all()
    head, revision = get_settings(db, novel.id)
    assert revision.parent_revision_id == original.revision.id
    assert revision.settings_json['custom'] == {'keep': [1, 2]}
    assert original.revision.settings_json == previous
    assert revision.change_set_json['before']['title'] == '危楼旧名'
    assert revision.change_set_json['after']['title'] == '危楼余火'
    assert novel.background == '背景不变'
    assert novel.cover_mode == 'text'


def test_metadata_stale_request_does_not_overwrite(client, db, novel):
    request = payload(novel)
    assert client.put(endpoint(novel), json=request).status_code == 200
    assert client.put(endpoint(novel), json={**request, 'title': '不应覆盖'}).status_code == 409
    db.expire_all()
    assert novel.title == '危楼余火'


def test_metadata_noop_does_not_create_revision(client, db, novel):
    result = client.put(endpoint(novel), json={**payload(novel), 'title': novel.title, 'author_name': novel.author_name})
    assert result.status_code == 200
    assert result.json()['version'] == novel.version == 1
    assert get_settings(db, novel.id) is None


def test_metadata_recycled_and_missing_are_rejected(client, db, novel):
    novel.recycled_at = datetime.now(timezone.utc)
    novel.recycled_by = 'author'
    db.commit()
    assert client.put(endpoint(novel), json=payload(novel)).status_code == 410
    assert client.put(f'/api/ai-novel-world-2026/novels/{uuid4()}/metadata', json=payload(novel)).status_code == 404


def test_metadata_atomic_rollback_on_revision_failure(client, db, novel, monkeypatch):
    import backend.novel_metadata_service as service
    def failure(*args, **kwargs):
        raise ValueError('revision unavailable')
    monkeypatch.setattr(service, 'save_settings', failure)
    assert client.put(endpoint(novel), json=payload(novel)).status_code == 422
    db.expire_all()
    assert novel.title == '危楼旧名'
    assert novel.author_name == '旧笔名'
    assert get_settings(db, novel.id) is None


def test_service_validates_before_any_write(db, novel):
    with pytest.raises(ValueError):
        update_novel_metadata(db, novel.id, expected_version=1, title=' ', author_name='南窗')
    assert novel.title == '危楼旧名'
