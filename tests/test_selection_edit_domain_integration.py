from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
import re
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from backend.creative_services import (
    complete_creative_generation,
    create_novel_character,
    list_creative_generations,
    start_creative_generation,
)
from backend.models import CreativeGenerationJob
from backend.selection_edit_diff import (
    build_selection_edit_result,
    reconstruct_selection_edit_diff,
)
from backend.services import ValidationError, content_hash, create_novel


TEST_DATABASE_URL = os.environ.get("AI_NOVEL_TEST_DATABASE_URL", "").strip()
PRODUCTION_DATABASE_URL = os.environ.get("AI_NOVEL_DATABASE_URL", "").strip()
pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="integration database not configured",
)

TEST_AGENT_ID = "ai-novel-writer"
TEST_PROVIDER_ID = "provider-selection-test"
TEST_MODEL_ID = "model-selection-test-v1"
TEST_CONTRACT_VERSION = "follow-agent-effective-selection-test-v1"
TEST_TITLE_PREFIX = "pytest-selection-edit-db-"
SAFE_TEST_DATABASE_NAME = re.compile(
    r"^[a-zA-Z0-9][a-zA-Z0-9_-]*_test(?:_[a-zA-Z0-9_-]+)?$"
)


def _isolated_test_database_url() -> str:
    """Reject a production-looking URL before SQLAlchemy opens a connection."""

    test_url = make_url(TEST_DATABASE_URL)
    database_name = test_url.database or ""
    if not SAFE_TEST_DATABASE_NAME.fullmatch(database_name):
        raise RuntimeError(
            "AI_NOVEL_TEST_DATABASE_URL must target an explicitly named *_test database"
        )
    if PRODUCTION_DATABASE_URL:
        production_url = make_url(PRODUCTION_DATABASE_URL)
        test_target = (
            test_url.host,
            test_url.port,
            test_url.database,
        )
        production_target = (
            production_url.host,
            production_url.port,
            production_url.database,
        )
        if test_target == production_target:
            raise RuntimeError(
                "AI_NOVEL_TEST_DATABASE_URL must not target AI_NOVEL_DATABASE_URL"
            )
    return TEST_DATABASE_URL


@pytest.fixture
def database_session() -> Session:
    engine = create_engine(
        _isolated_test_database_url(),
        pool_pre_ping=True,
    )
    with Session(engine, expire_on_commit=False) as session:
        yield session
        session.rollback()
        session.execute(
            text("DELETE FROM novels WHERE title LIKE :title_prefix"),
            {"title_prefix": f"{TEST_TITLE_PREFIX}%"},
        )
        session.commit()
    engine.dispose()


def _requested_model_arguments() -> dict[str, str]:
    return {
        "execution_agent_id": TEST_AGENT_ID,
        "requested_provider_id": TEST_PROVIDER_ID,
        "requested_model_id": TEST_MODEL_ID,
        "generation_contract_version": TEST_CONTRACT_VERSION,
    }


def _selection_snapshot(
    novel_id: UUID,
    *,
    selection_id: UUID | None = None,
    selection_text: str = "她把湿透的车票攥在掌心。",
) -> dict[str, object]:
    field_value = f"前文。{selection_text}后文。"
    return {
        "schema_version": 1,
        "selection_id": str(selection_id or uuid4()),
        "operation": "polish",
        "custom_instruction": None,
        "target": {
            "novel_id": str(novel_id),
            "document_id": None,
            "entity_type": "setting",
            "entity_id": str(novel_id),
            "field_id": "settings.idea",
            "field_label": "创作思路",
            "persistence": "explicit-save",
            "context_revision": 3,
        },
        "base": {
            "field_value_sha256": content_hash(field_value),
            "persistence_version_kind": "entity",
            "persistence_version": 1,
            "start_utf16": 3,
            "end_utf16": 3 + len(selection_text.encode("utf-16-le")) // 2,
            "selection_text": selection_text,
            "selection_text_sha256": content_hash(selection_text),
            "before": "前文。",
            "after": "后文。",
        },
    }


def _start_selection_job(
    session: Session,
    novel_id: UUID,
    snapshot: dict[str, object],
    *,
    force_new: bool = False,
) -> dict[str, object]:
    return start_creative_generation(
        session,
        scope_type="novel",
        scope_id=novel_id,
        kind="selection_edit",
        input_snapshot=snapshot,
        novel_id=novel_id,
        force_new=force_new,
        **_requested_model_arguments(),
    )


def test_selection_edit_persists_result_model_evidence_failure_and_recovery(
    database_session: Session,
) -> None:
    novel = create_novel(
        database_session,
        f"{TEST_TITLE_PREFIX}lifecycle-{uuid4()}",
    )
    novel_id = UUID(novel["id"])
    other_novel = create_novel(
        database_session,
        f"{TEST_TITLE_PREFIX}other-{uuid4()}",
    )
    other_novel_id = UUID(other_novel["id"])
    snapshot = _selection_snapshot(novel_id)
    normalized_snapshot = {**snapshot, "use_novel_context": False}

    first = _start_selection_job(database_session, novel_id, snapshot)
    assert first["attempt"] == 1
    assert first["state"] == "running"
    assert first["should_execute"] is True

    repeated_running = _start_selection_job(database_session, novel_id, snapshot)
    assert repeated_running["id"] == first["id"]
    assert repeated_running["attempt"] == 1
    assert repeated_running["should_execute"] is False

    replacement_text = "她把湿透的旧车票紧紧攥在掌心。"
    result = build_selection_edit_result(
        job_id=str(first["id"]),
        selection_id=str(snapshot["selection_id"]),
        operation="polish",
        original_text=str(snapshot["base"]["selection_text"]),
        replacement_text=replacement_text,
        short_summary="增强物件质感与动作力度。",
    )
    completed = complete_creative_generation(
        database_session,
        UUID(str(first["id"])),
        actual_provider_id=TEST_PROVIDER_ID,
        actual_model_id=TEST_MODEL_ID,
        output_text=replacement_text,
        output_json=result,
    )
    assert completed["state"] == "ready"

    repeated_ready = _start_selection_job(database_session, novel_id, snapshot)
    assert repeated_ready["id"] == first["id"]
    assert repeated_ready["should_execute"] is False

    database_session.expire_all()
    persisted = database_session.get(
        CreativeGenerationJob,
        UUID(str(first["id"])),
    )
    assert persisted is not None
    assert persisted.kind == "selection_edit"
    assert persisted.state == "ready"
    assert persisted.attempt == 1
    assert persisted.input_snapshot == normalized_snapshot
    assert persisted.execution_agent_id == TEST_AGENT_ID
    assert persisted.requested_provider_id == TEST_PROVIDER_ID
    assert persisted.requested_model_id == TEST_MODEL_ID
    assert persisted.actual_provider_id == TEST_PROVIDER_ID
    assert persisted.actual_model_id == TEST_MODEL_ID
    assert persisted.generation_contract_version == TEST_CONTRACT_VERSION
    assert persisted.output_text == replacement_text
    assert persisted.output_json == result
    assert persisted.failure_message is None
    assert reconstruct_selection_edit_diff(
        persisted.output_json["diff_segments"],
        candidate=False,
    ) == snapshot["base"]["selection_text"]
    assert reconstruct_selection_edit_diff(
        persisted.output_json["diff_segments"],
        candidate=True,
    ) == replacement_text

    recovered = list_creative_generations(
        database_session,
        scope_type="novel",
        scope_id=novel_id,
        kind="selection_edit",
        selection_id=UUID(str(snapshot["selection_id"])),
    )
    assert [item["id"] for item in recovered] == [first["id"]]
    assert list_creative_generations(
        database_session,
        scope_type="novel",
        scope_id=novel_id,
        kind="selection_edit",
        selection_id=uuid4(),
    ) == []
    assert list_creative_generations(
        database_session,
        scope_type="novel",
        scope_id=other_novel_id,
        kind="selection_edit",
        selection_id=UUID(str(snapshot["selection_id"])),
    ) == []

    failed_attempt = _start_selection_job(
        database_session,
        novel_id,
        snapshot,
        force_new=True,
    )
    assert failed_attempt["attempt"] == 2
    with pytest.raises(ValidationError, match="模型与任务启动模型不一致"):
        complete_creative_generation(
            database_session,
            UUID(str(failed_attempt["id"])),
            actual_provider_id="provider-unexpected",
            actual_model_id="model-unexpected",
            output_text=replacement_text,
            output_json=result,
        )

    database_session.expire_all()
    persisted_failure = database_session.get(
        CreativeGenerationJob,
        UUID(str(failed_attempt["id"])),
    )
    assert persisted_failure is not None
    assert persisted_failure.state == "failed"
    assert persisted_failure.attempt == 2
    assert persisted_failure.requested_provider_id == TEST_PROVIDER_ID
    assert persisted_failure.requested_model_id == TEST_MODEL_ID
    # A rejected legacy mismatch is not verified actual-model evidence.  Keep
    # the attempted identity in the immutable failure diagnostic, not in the
    # authoritative actual_* columns.
    assert persisted_failure.actual_provider_id is None
    assert persisted_failure.actual_model_id is None
    assert persisted_failure.output_json == {}
    assert persisted_failure.output_text == ""
    assert "requested=" in str(persisted_failure.failure_message)
    assert "actual=" in str(persisted_failure.failure_message)

    terminal_replay = complete_creative_generation(
        database_session,
        UUID(str(failed_attempt["id"])),
        actual_provider_id=TEST_PROVIDER_ID,
        actual_model_id=TEST_MODEL_ID,
        output_text=replacement_text,
        output_json=result,
    )
    assert terminal_replay["state"] == "failed"
    assert terminal_replay["failure_message"] == persisted_failure.failure_message


def test_selection_edit_concurrent_idempotency_and_force_new_attempts(
    database_session: Session,
) -> None:
    novel = create_novel(
        database_session,
        f"{TEST_TITLE_PREFIX}concurrency-{uuid4()}",
    )
    novel_id = UUID(novel["id"])
    snapshot = _selection_snapshot(novel_id)
    engine = create_engine(_isolated_test_database_url(), pool_pre_ping=True)

    default_barrier = Barrier(2)

    def create_default_job() -> dict[str, object]:
        with Session(engine, expire_on_commit=False) as worker_session:
            default_barrier.wait(timeout=5)
            return _start_selection_job(worker_session, novel_id, snapshot)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            default_results = list(
                executor.map(lambda _: create_default_job(), range(2))
            )
        assert len({str(item["id"]) for item in default_results}) == 1
        assert {int(item["attempt"]) for item in default_results} == {1}
        assert sorted(bool(item["should_execute"]) for item in default_results) == [
            False,
            True,
        ]

        forced_barrier = Barrier(2)

        def create_forced_job() -> dict[str, object]:
            with Session(engine, expire_on_commit=False) as worker_session:
                forced_barrier.wait(timeout=5)
                return _start_selection_job(
                    worker_session,
                    novel_id,
                    snapshot,
                    force_new=True,
                )

        with ThreadPoolExecutor(max_workers=2) as executor:
            forced_results = list(
                executor.map(lambda _: create_forced_job(), range(2))
            )
    finally:
        engine.dispose()

    assert sorted(int(item["attempt"]) for item in forced_results) == [2, 3]
    assert len({str(item["id"]) for item in forced_results}) == 2
    persisted_attempts = database_session.scalars(
        select(CreativeGenerationJob)
        .where(
            CreativeGenerationJob.scope_type == "novel",
            CreativeGenerationJob.scope_id == novel_id,
            CreativeGenerationJob.kind == "selection_edit",
        )
        .order_by(CreativeGenerationJob.attempt)
    ).all()
    assert [item.attempt for item in persisted_attempts] == [1, 2, 3]
    assert database_session.scalar(
        select(func.count(CreativeGenerationJob.id)).where(
            CreativeGenerationJob.scope_type == "novel",
            CreativeGenerationJob.scope_id == novel_id,
            CreativeGenerationJob.kind == "selection_edit",
        )
    ) == 3


def test_selection_edit_rejects_cross_book_persisted_entity(
    database_session: Session,
) -> None:
    source_novel = create_novel(
        database_session,
        f"{TEST_TITLE_PREFIX}source-{uuid4()}",
    )
    target_novel = create_novel(
        database_session,
        f"{TEST_TITLE_PREFIX}target-{uuid4()}",
    )
    source_novel_id = UUID(source_novel["id"])
    target_novel_id = UUID(target_novel["id"])
    character = create_novel_character(
        database_session,
        source_novel_id,
        role_type="main",
        name=f"苏晚-{uuid4().hex[:8]}",
        description="旧电台修复师",
        details={},
    )
    selection_text = "旧电台修复师"
    snapshot = _selection_snapshot(
        target_novel_id,
        selection_text=selection_text,
    )
    snapshot["target"] = {
        "novel_id": str(target_novel_id),
        "document_id": None,
        "entity_type": "character",
        "entity_id": str(character["id"]),
        "field_id": "character.description",
        "field_label": "人物小传",
        "persistence": "explicit-save",
        "context_revision": 4,
    }
    snapshot["base"] = {
        "field_value_sha256": content_hash(selection_text),
        "persistence_version_kind": "entity",
        "persistence_version": int(character["version"]),
        "start_utf16": 0,
        "end_utf16": len(selection_text.encode("utf-16-le")) // 2,
        "selection_text": selection_text,
        "selection_text_sha256": content_hash(selection_text),
        "before": "",
        "after": "",
    }

    with pytest.raises(ValidationError, match="不属于当前小说"):
        _start_selection_job(
            database_session,
            target_novel_id,
            snapshot,
        )

    assert database_session.scalar(
        select(func.count(CreativeGenerationJob.id)).where(
            CreativeGenerationJob.novel_id == target_novel_id,
            CreativeGenerationJob.kind == "selection_edit",
        )
    ) == 0
