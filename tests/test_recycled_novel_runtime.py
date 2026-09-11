from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from backend.embedding import api as embedding_api
from backend.embedding import worker as embedding_worker
from backend.models import Novel
from backend.narration import jobs, media, narration_api, playback_api, services
from backend.narration.contracts import NarrationRequestScope
from backend.novel_lifecycle_errors import NovelRecycledError


NOW = datetime(2026, 9, 10, tzinfo=timezone.utc)


class _FakeNarrationStore:
    def __init__(self, novel: Novel) -> None:
        self.novel = novel

    def get(self, model, row_id, *, for_update=False):  # type: ignore[no-untyped-def]
        del row_id, for_update
        return self.novel if model is Novel else None


def _recycled_novel() -> Novel:
    scope = NarrationRequestScope.fixed_local()
    return Novel(
        id=uuid4(),
        owner_id=scope.owner_id,
        workspace_id=scope.workspace_id,
        title="已回收运行时测试",
        recycled_at=NOW,
        recycled_by="test",
    )


def test_narration_store_rejects_recycled_novel() -> None:
    novel = _recycled_novel()

    with pytest.raises(NovelRecycledError):
        services.require_local_novel(_FakeNarrationStore(novel), novel.id)  # type: ignore[arg-type]


def test_claim_sql_excludes_recycled_novels_but_keeps_global_jobs() -> None:
    statement = jobs.build_claim_statement(
        scope=NarrationRequestScope.fixed_local(),
        now=NOW,
        dialect_name="postgresql",
        lifecycle_guard=True,
    )
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "background_jobs.novel_id IS NULL OR" in sql
    assert "novels.recycled_at IS NULL" in sql
    assert "novels.id = background_jobs.novel_id" in sql


def test_legacy_narrow_job_fixture_can_explicitly_disable_lifecycle_join() -> None:
    statement = jobs.build_claim_statement(
        scope=NarrationRequestScope.fixed_local(),
        now=NOW,
        dialect_name="sqlite",
        lifecycle_guard=False,
    )
    sql = str(statement)

    assert "novels.recycled_at" not in sql


@pytest.mark.parametrize(
    "adapter",
    (embedding_api._raise, playback_api._raise_http),
)
def test_http_adapters_map_recycled_novel_to_stable_410(adapter) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(HTTPException) as raised:
        adapter(NovelRecycledError("hidden internal text"))

    assert raised.value.status_code == 410
    assert raised.value.detail["type"] == "novel_recycled"
    assert raised.value.detail["code"] == "novel_recycled"


def test_narration_production_adapter_maps_recycled_novel_to_stable_410() -> None:
    class _Backend:
        def dispatch(self, command):  # type: ignore[no-untyped-def]
            del command
            raise NovelRecycledError("hidden internal text")

    with pytest.raises(HTTPException) as raised:
        narration_api._run(_Backend(), object(), narration_api.NarrationWorkflowResource)  # type: ignore[arg-type]

    assert raised.value.status_code == 410
    assert raised.value.detail["type"] == "novel_recycled"


def test_embedding_late_result_checks_lifecycle_before_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = uuid4()
    touched = False

    def reject(_session, actual_novel_id):  # type: ignore[no-untyped-def]
        assert actual_novel_id == novel_id
        raise NovelRecycledError("小说已移入回收站")

    class _NoDatabaseAccess:
        def scalar(self, _statement):  # type: ignore[no-untyped-def]
            nonlocal touched
            touched = True
            raise AssertionError("publication touched data before lifecycle fence")

    monkeypatch.setattr(embedding_worker, "lock_active_novel", reject)
    snapshot = SimpleNamespace(novel_id=novel_id)

    with pytest.raises(NovelRecycledError):
        embedding_worker._record_success(  # type: ignore[arg-type]
            _NoDatabaseAccess(),
            lease=object(),
            snapshot=snapshot,
            result=object(),
            duration_ms=1,
        )

    assert touched is False


def test_gc_does_not_create_plan_for_recycled_novel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = uuid4()
    asset_id = uuid4()
    scalar_calls = 0

    class _IdentitySession:
        def scalar(self, _statement):  # type: ignore[no-untyped-def]
            nonlocal scalar_calls
            scalar_calls += 1
            if scalar_calls == 1:
                return novel_id
            raise AssertionError("asset row was locked before lifecycle rejection")

    def reject(_session, actual_novel_id):  # type: ignore[no-untyped-def]
        assert actual_novel_id == novel_id
        raise NovelRecycledError("小说已移入回收站")

    monkeypatch.setattr(media, "lock_active_novel", reject)

    with pytest.raises(NovelRecycledError):
        media.begin_gc_deletion_in_session(  # type: ignore[arg-type]
            _IdentitySession(),
            object(),
            asset_id=asset_id,
            expected_generation=1,
        )

    assert scalar_calls == 1
