from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from tests.writing_e2e._host_stub import FakeSession, import_creative_api


def test_delete_route_uses_scoped_narration_cleanup_runtime(monkeypatch) -> None:
    api = import_creative_api(monkeypatch)
    runtime = SimpleNamespace()
    novel_id = uuid4()
    expected = {
        "deleted": True,
        "media_cleanup_pending": False,
        "deleted_media_count": 2,
        "deleted_document_ids": [str(uuid4())],
    }
    calls: list[tuple[object, object, int]] = []

    def delete_with_runtime(selected, selected_novel_id, *, expected_version):
        calls.append((selected, selected_novel_id, expected_version))
        return expected

    monkeypatch.setattr(api, "current_narration_cache_runtime", lambda: runtime)
    monkeypatch.setattr(api, "delete_novel_with_narration", delete_with_runtime)

    assert api.novels_delete(novel_id, expected_version=7, session=FakeSession()) == expected
    assert calls == [(runtime, novel_id, 7)]


def test_delete_route_preserves_legacy_path_when_media_runtime_is_absent(monkeypatch) -> None:
    api = import_creative_api(monkeypatch)
    session = FakeSession()
    novel_id = uuid4()
    calls: list[tuple[object, object, int]] = []

    def legacy_delete(selected, selected_novel_id, *, expected_version):
        calls.append((selected, selected_novel_id, expected_version))

    monkeypatch.setattr(api, "current_narration_cache_runtime", lambda: None)
    monkeypatch.setattr(api, "delete_novel", legacy_delete)

    assert api.novels_delete(novel_id, expected_version=3, session=session) == {
        "deleted": True,
        "media_cleanup_pending": False,
        "deleted_media_count": 0,
        "deleted_document_ids": [],
    }
    assert calls == [(session, novel_id, 3)]
