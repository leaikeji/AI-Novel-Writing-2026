from __future__ import annotations

import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from fastapi import HTTPException
import pytest

from backend import creative_data_api
from backend.creative_data_api import LibraryCheckCreate


@pytest.mark.parametrize("endpoint", ["versions", "restore"])
def test_legacy_private_asset_mutation_endpoints_reject_novel_scoped_copies(
    monkeypatch,
    endpoint: str,
) -> None:
    asset_id = uuid4()
    session = MagicMock()
    session.get.return_value = SimpleNamespace(
        id=asset_id,
        scope_kind="novel",
        scope_novel_id=uuid4(),
    )
    if endpoint == "versions":
        with pytest.raises(HTTPException) as captured:
            creative_data_api.asset_versions(asset_id, session=session)
    else:
        request = creative_data_api.AssetRestoreRequest(
            expected_root_version=1,
            operation_key="restore-scope-guard",
            asset_version_id=uuid4(),
        )
        with pytest.raises(HTTPException) as captured:
            creative_data_api.asset_restore(asset_id, request, session=session)
    assert captured.value.status_code == 404


def test_working_copy_check_uses_document_as_stable_source_identity() -> None:
    novel_id, document_id = uuid4(), uuid4()
    text = "潮声越过堤岸。"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    document = SimpleNamespace(id=document_id, novel_id=novel_id)
    working = SimpleNamespace(
        document_id=document_id,
        draft_version=3,
        content_hash=digest,
        content_markdown=text,
    )
    session = MagicMock()
    session.get.side_effect = [document, working]
    source, source_id, unchanged_baseline = creative_data_api._library_check_source(
        session,
        novel_id,
        LibraryCheckCreate(
            source_kind="working_copy",
            document_id=document_id,
            source_version=3,
            text_sha256=digest,
        ),
    )
    assert source == text
    assert source_id == document_id
    assert unchanged_baseline is None


def test_selection_result_check_reconstructs_the_final_working_copy() -> None:
    novel_id, document_id, job_id = uuid4(), uuid4(), uuid4()
    baseline = "潮声越过堤岸。旧句。灯塔仍亮着。"
    selected = "旧句。"
    replacement = "不禁让人觉得潮声很轻。"
    digest = hashlib.sha256(replacement.encode("utf-8")).hexdigest()
    source_digest = hashlib.sha256(baseline.encode("utf-8")).hexdigest()
    start = len("潮声越过堤岸。".encode("utf-16-le")) // 2
    end = start + len(selected.encode("utf-16-le")) // 2
    document = SimpleNamespace(id=document_id, novel_id=novel_id)
    job = SimpleNamespace(
        id=job_id,
        kind="selection_edit",
        state="ready",
        novel_id=novel_id,
        document_id=document_id,
        attempt=2,
        output_text=replacement,
        output_json={"diff_segments": []},
        input_snapshot={
            "target": {"field_id": "chapter.body", "persistence": "autosave",
                       "novel_id": str(novel_id), "document_id": str(document_id)},
            "base": {
                "persistence_version_kind": "draft",
                "persistence_version": 4,
                "field_value_sha256": source_digest,
                "start_utf16": start,
                "end_utf16": end,
                "selection_text": selected,
            }
        },
    )
    working = SimpleNamespace(
        draft_version=4,
        content_hash=source_digest,
        content_markdown=baseline,
    )
    session = MagicMock()
    session.get.side_effect = [document, document, job, working]

    source, source_id, unchanged_baseline = creative_data_api._library_check_source(
        session,
        novel_id,
        LibraryCheckCreate(
            source_kind="selection_result",
            source_id=job_id,
            document_id=document_id,
            source_version=2,
            text_sha256=digest,
        ),
    )

    assert source == "潮声越过堤岸。不禁让人觉得潮声很轻。灯塔仍亮着。"
    assert source_id == job_id
    assert unchanged_baseline == (baseline, start, end)


def test_partial_selection_result_check_accepts_only_frozen_diff_decisions() -> None:
    novel_id, document_id, job_id = uuid4(), uuid4(), uuid4()
    source = "甲乙丙"
    source_digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    application = "甲新乙丙"
    application_digest = hashlib.sha256(application.encode("utf-8")).hexdigest()
    document = SimpleNamespace(id=document_id, novel_id=novel_id)
    job = SimpleNamespace(
        id=job_id,
        kind="selection_edit",
        state="ready",
        novel_id=novel_id,
        document_id=document_id,
        attempt=1,
        output_text="甲新乙新丙",
        output_json={"diff_segments": [
            {"segment_id": "same-a", "kind": "equal", "text": "甲"},
            {"segment_id": "change-a", "kind": "insert", "replacement_text": "新"},
            {"segment_id": "same-b", "kind": "equal", "text": "乙"},
            {"segment_id": "change-b", "kind": "replace", "original_text": "丙", "replacement_text": "新丙"},
        ]},
        input_snapshot={"target": {"field_id": "chapter.body", "persistence": "autosave",
                                   "novel_id": str(novel_id), "document_id": str(document_id)}, "base": {
            "persistence_version_kind": "draft",
            "persistence_version": 2,
            "field_value_sha256": source_digest,
            "start_utf16": 0,
            "end_utf16": 3,
            "selection_text": source,
        }},
    )
    working = SimpleNamespace(
        draft_version=2,
        content_hash=source_digest,
        content_markdown=source,
    )
    session = MagicMock()
    session.get.side_effect = [document, document, job, working]

    checked, _, unchanged_baseline = creative_data_api._library_check_source(
        session,
        novel_id,
        LibraryCheckCreate(
            source_kind="selection_result",
            source_id=job_id,
            document_id=document_id,
            source_version=1,
            text_sha256=application_digest,
            accepted_segment_ids=["change-a"],
        ),
    )

    assert checked == application
    assert unchanged_baseline == (source, 0, 3)


def test_archive_put_replays_an_already_reached_desired_state(monkeypatch) -> None:
    asset_id = uuid4()
    asset = SimpleNamespace(
        id=asset_id,
        version=2,
        archived=True,
        scope_kind="library",
        scope_novel_id=None,
    )
    session = MagicMock()
    session.scalar.return_value = asset
    monkeypatch.setattr(
        creative_data_api,
        "get_scoped_asset_view",
        lambda *_args, **_kwargs: {"id": str(asset_id), "version": asset.version},
    )

    result = creative_data_api.private_library_asset_archived_put(
        asset_id,
        creative_data_api.PrivateLibraryArchivedPut(
            expected_root_version=1,
            archived=True,
            operation_key="archive-replay-key",
        ),
        session=session,
    )

    assert result["changed"] is False
    session.flush.assert_not_called()
    session.commit.assert_called_once()


def test_selection_capture_rejects_a_changed_frozen_text_before_writing() -> None:
    session = MagicMock()
    request = creative_data_api.PrivateLibraryCaptureCreate(
        selection_id=uuid4(),
        selected_text="潮声越过堤岸。",
        selected_text_sha256=hashlib.sha256("另一段文字".encode("utf-8")).hexdigest(),
        source_value_sha256=hashlib.sha256("整段来源".encode("utf-8")).hexdigest(),
        source_document_id="chapter-body",
        field_id="chapter.body",
        category="vocabulary",
        destination="collect",
        operation_key="capture-hash-guard",
    )

    with pytest.raises(HTTPException) as captured:
        creative_data_api.private_library_capture_create(request, session=session)

    assert captured.value.status_code == 409
    assert captured.value.detail["code"] == "selection_text_changed"
    session.add.assert_not_called()
    session.commit.assert_not_called()


def test_selection_capture_requires_novel_exactly_for_use_current_novel() -> None:
    text = "排水坡度"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    request = creative_data_api.PrivateLibraryCaptureCreate(
        selection_id=uuid4(),
        selected_text=text,
        selected_text_sha256=digest,
        source_value_sha256=digest,
        source_document_id="chapter-body",
        field_id="chapter.body",
        category="vocabulary",
        destination="use_current_novel",
        operation_key="capture-scope-guard",
    )

    with pytest.raises(HTTPException) as captured:
        creative_data_api.private_library_capture_create(request, session=MagicMock())

    assert captured.value.status_code == 422
