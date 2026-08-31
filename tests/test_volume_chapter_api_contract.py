from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend import services
from backend.creative_schemas import UpdateDocumentMetadataRequest, UpdateVolumeRequest
from backend.schemas import CreateDocumentRequest, CreateVolumeRequest
from backend.volume_chapter_titles import VolumeChapterContractError, contract_error_detail


def test_create_requests_accept_omitted_semantic_name():
    assert CreateVolumeRequest().title == ""
    request = CreateDocumentRequest(kind="chapter")
    assert request.title == ""
    assert request.volume_id is None


def test_update_requests_accept_explicit_empty_name_but_do_not_make_title_optional():
    assert UpdateVolumeRequest(expected_version=1, title="").title == ""
    assert UpdateDocumentMetadataRequest(expected_version=1, title="").title == ""
    with pytest.raises(Exception):
        UpdateVolumeRequest(expected_version=1)
    with pytest.raises(Exception):
        UpdateDocumentMetadataRequest(expected_version=1)


def test_volume_contract_errors_use_structured_http_detail():
    error = VolumeChapterContractError(
        "chapter_volume_required", "请先创建分卷，再新建章节"
    )
    assert error.status_code == 422
    assert contract_error_detail(error) == {
        "type": "chapter_volume_required",
        "message": "请先创建分卷，再新建章节",
    }


def test_stale_draft_error_preserves_complete_current_payload():
    current = {"id": "draft-id", "version": 7, "data": {"storyline_ids": ["x"]}}
    error = VolumeChapterContractError(
        "chapter_draft_volume_stale",
        "章节草稿的目标分卷已失效，请重新选择分卷",
        status_code=409,
        current=current,
    )
    assert error.status_code == 409
    assert contract_error_detail(error)["current"] == current


def test_chapter_creation_checks_volume_before_optional_name(monkeypatch):
    monkeypatch.setattr(services, "_lock_novel", lambda session, novel_id: object())
    with pytest.raises(VolumeChapterContractError) as captured:
        services.create_document(object(), uuid4(), "", kind="chapter", volume_id=None)
    assert captured.value.code == "chapter_volume_required"


def test_chapter_creation_persists_only_semantic_name(monkeypatch):
    novel_id = uuid4()
    volume_id = uuid4()
    captured = {}

    class FakeSession:
        def scalar(self, statement):
            return SimpleNamespace(id=volume_id, novel_id=novel_id)

        def commit(self):
            captured["committed"] = True

    monkeypatch.setattr(services, "_lock_novel", lambda session, target_id: object())
    monkeypatch.setattr(services, "_next_position", lambda *args: 1000)

    def fake_new_document(session, **values):
        captured.update(values)
        return SimpleNamespace(id=uuid4())

    monkeypatch.setattr(services, "_new_document", fake_new_document)
    monkeypatch.setattr(
        services,
        "_refresh_active_novel_index_after_commit",
        lambda session, target_id: captured.setdefault("refreshed_novel_id", target_id),
    )
    monkeypatch.setattr(
        services,
        "get_document",
        lambda session, document_id: {"id": str(document_id), "title": captured["title"]},
    )

    result = services.create_document(
        FakeSession(),
        novel_id,
        "第十二章 · 海边来信",
        kind="chapter",
        volume_id=volume_id,
    )

    assert captured["title"] == "海边来信"
    assert captured["volume_id"] == volume_id
    assert captured["committed"] is True
    assert captured["refreshed_novel_id"] == novel_id
    assert result["title"] == "海边来信"


def test_post_commit_refresh_failure_is_recoverable_and_marks_index_outdated(
    monkeypatch,
):
    novel_id = uuid4()
    captured = {"rollbacks": 0, "marked": []}

    class FakeSession:
        def commit(self):
            raise AssertionError("failed refresh transaction must not commit")

        def rollback(self):
            captured["rollbacks"] += 1

    def fail_refresh(*_args, **_kwargs):
        raise RuntimeError("synthetic refresh failure")

    monkeypatch.setattr(
        "backend.embedding.indexing.request_active_novel_refresh",
        fail_refresh,
    )
    monkeypatch.setattr(
        services,
        "_mark_active_novel_index_outdated",
        lambda session, target_id: captured["marked"].append(target_id),
    )

    assert services._refresh_active_novel_index_after_commit(
        FakeSession(), novel_id
    ) is False
    assert captured == {"rollbacks": 1, "marked": [novel_id]}


def test_mark_active_index_outdated_updates_current_build():
    novel_id = uuid4()
    active_generation_id = uuid4()
    novel = SimpleNamespace(owner_id=uuid4(), workspace_id=uuid4())
    configuration = SimpleNamespace(active_generation_id=active_generation_id)
    build = SimpleNamespace(sync_state="current", state="ready")

    class FakeSession:
        def __init__(self):
            self.scalars = iter((configuration, build))
            self.commits = 0

        def get(self, model, target_id):
            assert model is services.Novel
            assert target_id == novel_id
            return novel

        def scalar(self, _statement):
            return next(self.scalars)

        def commit(self):
            self.commits += 1

    session = FakeSession()
    services._mark_active_novel_index_outdated(session, novel_id)

    assert (build.state, build.sync_state) == ("outdated", "outdated")
    assert session.commits == 1
