from __future__ import annotations

import os
import re
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from backend.character_profile_services import normalize_character_profile_output
from backend.creative_services import (
    EntityConflictError,
    apply_character_profile_completion,
    build_character_profile_completion_snapshot,
    complete_creative_generation,
    create_novel_character,
    get_character_profile_completion_status,
    restore_character_profile_apply_batch,
    start_creative_generation,
    update_novel_character,
)
from backend.models import CharacterProfileApplyBatch, NovelCharacter
from backend.services import create_checkpoint, create_novel, save_draft


TEST_DATABASE_URL = os.environ.get("AI_NOVEL_TEST_DATABASE_URL", "").strip()
PRODUCTION_DATABASE_URL = os.environ.get("AI_NOVEL_DATABASE_URL", "").strip()
pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="integration database not configured",
)

TEST_TITLE_PREFIX = "pytest-character-profile-db-"
TEST_AGENT_ID = "ai-novel-writer"
TEST_PROVIDER_ID = "provider-character-profile-test"
TEST_MODEL_ID = "model-character-profile-test-v1"
TEST_CONTRACT_VERSION = "follow-agent-effective-character-profile-test-v1"
SAFE_TEST_DATABASE_NAME = re.compile(
    r"^[a-zA-Z0-9][a-zA-Z0-9_-]*_test(?:_[a-zA-Z0-9_-]+)?$"
)


def _isolated_test_database_url() -> str:
    test_url = make_url(TEST_DATABASE_URL)
    database_name = test_url.database or ""
    if not SAFE_TEST_DATABASE_NAME.fullmatch(database_name):
        raise RuntimeError(
            "AI_NOVEL_TEST_DATABASE_URL must target an explicitly named *_test database"
        )
    if PRODUCTION_DATABASE_URL:
        production_url = make_url(PRODUCTION_DATABASE_URL)
        if (
            test_url.host,
            test_url.port,
            test_url.database,
        ) == (
            production_url.host,
            production_url.port,
            production_url.database,
        ):
            raise RuntimeError(
                "AI_NOVEL_TEST_DATABASE_URL must not target AI_NOVEL_DATABASE_URL"
            )
    return TEST_DATABASE_URL


@pytest.fixture
def database_session() -> Session:
    engine = create_engine(_isolated_test_database_url(), pool_pre_ping=True)
    with Session(engine, expire_on_commit=False) as session:
        yield session
        session.rollback()
        session.execute(
            text("DELETE FROM novels WHERE title LIKE :title_prefix"),
            {"title_prefix": f"{TEST_TITLE_PREFIX}%"},
        )
        session.commit()
    engine.dispose()


def _create_profile_novel(
    session: Session,
    *,
    character_count: int = 2,
) -> tuple[UUID, UUID, list[dict[str, object]]]:
    novel = create_novel(
        session,
        f"{TEST_TITLE_PREFIX}{uuid4()}",
    )
    novel_id = UUID(novel["id"])
    document_id = UUID(novel["tree"][0]["documents"][0]["id"])
    character_specs = [
        (
            "江述",
            "重视可复核事实，面对无辜者受伤时会暂缓追查。",
            {
                "gender": "男",
                "secret": "父亲留下的旧案编号",
                "core_flaw": "过度依赖程序",
                "core_motivation": "查清失踪档案",
                "growth_direction": "学会信任同伴",
                "interlock": "与林青瓷共享证据",
            },
        ),
        (
            "林青瓷",
            "习惯先保护原始证据，面对权力施压时却会正面坚持。",
            {
                "gender": "女",
                "secret": "保留了一页销毁清单",
                "core_flaw": "不愿求助",
                "core_motivation": "守住证据链",
                "growth_direction": "允许他人共同承担",
                "interlock": "掌握江述需要的清单",
            },
        ),
    ]
    characters = [
        create_novel_character(
            session,
            novel_id,
            role_type="main" if index == 0 else "supporting",
            name=name,
            description=description,
            details=details,
        )
        for index, (name, description, details) in enumerate(
            character_specs[:character_count]
        )
    ]
    return novel_id, document_id, characters


def _ready_profile_job(
    session: Session,
    novel_id: UUID,
) -> tuple[dict[str, object], dict[str, object]]:
    snapshot = build_character_profile_completion_snapshot(session, novel_id)
    raw_characters = []
    for character in snapshot["characters"]:
        description = str(character["description"])
        raw_characters.append(
            {
                "character_id": character["id"],
                "base_version": character["base_version"],
                "status": "candidate",
                "personality": (
                    "重事实、守证据，面对风险时会先保护他人再继续追查。"
                    if character["name"] == "江述"
                    else "谨慎而有韧性，面对施压时会坚持证据并独自承担代价。"
                ),
                "basis": "designed",
                "confidence": 86,
                "evidence": [
                    {
                        "source_type": "character",
                        "source_id": character["id"],
                        "quote": description,
                    }
                ],
                "warnings": [],
            }
        )
    normalized_output = normalize_character_profile_output(
        snapshot,
        {"characters": raw_characters},
    )
    job = start_creative_generation(
        session,
        scope_type="novel",
        scope_id=novel_id,
        kind="character_profile_completion",
        input_snapshot=snapshot,
        execution_agent_id=TEST_AGENT_ID,
        requested_provider_id=TEST_PROVIDER_ID,
        requested_model_id=TEST_MODEL_ID,
        generation_contract_version=TEST_CONTRACT_VERSION,
        novel_id=novel_id,
    )
    completed = complete_creative_generation(
        session,
        UUID(str(job["id"])),
        actual_provider_id=TEST_PROVIDER_ID,
        actual_model_id=TEST_MODEL_ID,
        output_text="profile test output",
        output_json=normalized_output,
    )
    assert completed["state"] == "ready"
    return completed, normalized_output


def _decisions(output: dict[str, object]) -> list[dict[str, object]]:
    return [
        {
            "character_id": item["character_id"],
            "base_version": item["base_version"],
            "replace_existing": False,
        }
        for item in output["characters"]
    ]


def _character_rows(
    session: Session,
    novel_id: UUID,
) -> list[NovelCharacter]:
    session.expire_all()
    return list(
        session.scalars(
            select(NovelCharacter)
            .where(NovelCharacter.novel_id == novel_id)
            .order_by(NovelCharacter.position)
        ).all()
    )


def test_snapshot_reads_formal_revision_and_never_uncheckpointed_working_draft(
    database_session: Session,
) -> None:
    novel_id, document_id, _ = _create_profile_novel(
        database_session,
        character_count=1,
    )
    formal_text = "江述把正式卷宗压在桌上，坚持逐页核对蓝色印章。"
    saved = save_draft(
        database_session,
        document_id,
        expected_draft_version=1,
        content_markdown=formal_text,
    )
    checkpoint = create_checkpoint(
        database_session,
        document_id,
        expected_draft_version=saved["draft_version"],
    )
    uncheckpointed_text = "江述在未同步草稿里决定销毁唯一证据。"
    save_draft(
        database_session,
        document_id,
        expected_draft_version=checkpoint["document"]["draft_version"],
        content_markdown=uncheckpointed_text,
    )

    snapshot = build_character_profile_completion_snapshot(
        database_session,
        novel_id,
    )
    chapter_text = "\n".join(
        str(item["excerpt"]) for item in snapshot["chapter_evidence"]
    )

    assert formal_text in chapter_text
    assert "未同步草稿" not in chapter_text
    assert "销毁唯一证据" not in chapter_text
    assert {item["source_id"] for item in snapshot["chapter_evidence"]} == {
        checkpoint["revision"]["id"]
    }
    assert {item["title"] for item in snapshot["chapter_evidence"]} == {"第1章"}
    assert {item["position"] for item in snapshot["chapter_evidence"]} == {1}


def test_apply_is_atomic_preserves_hidden_details_and_is_idempotent(
    database_session: Session,
) -> None:
    novel_id, _, created = _create_profile_novel(database_session)
    before = {item["id"]: dict(item["details"]) for item in created}
    job, output = _ready_profile_job(database_session, novel_id)
    decisions = _decisions(output)

    result = apply_character_profile_completion(
        database_session,
        novel_id,
        UUID(str(job["id"])),
        idempotency_key="profile-apply-idempotent-001",
        decisions=decisions,
    )
    rows = _character_rows(database_session, novel_id)

    assert result["state"] == "applied"
    assert result["can_restore"] is True
    assert result["last_apply_batch_id"]
    assert [row.version for row in rows] == [2, 2]
    for row in rows:
        original = before[str(row.id)]
        assert row.details["personality"]
        for hidden_key in (
            "secret",
            "core_flaw",
            "core_motivation",
            "growth_direction",
            "interlock",
            "gender",
        ):
            assert row.details[hidden_key] == original[hidden_key]

    repeated = apply_character_profile_completion(
        database_session,
        novel_id,
        UUID(str(job["id"])),
        idempotency_key="profile-apply-idempotent-001",
        decisions=decisions,
    )
    repeated_rows = _character_rows(database_session, novel_id)
    batch_count = database_session.scalar(
        select(func.count(CharacterProfileApplyBatch.id)).where(
            CharacterProfileApplyBatch.novel_id == novel_id
        )
    )

    assert repeated["last_apply_batch_id"] == result["last_apply_batch_id"]
    assert [row.version for row in repeated_rows] == [2, 2]
    assert batch_count == 1


def test_concurrent_character_version_conflict_rolls_back_entire_apply_batch(
    database_session: Session,
) -> None:
    novel_id, _, created = _create_profile_novel(database_session)
    job, output = _ready_profile_job(database_session, novel_id)
    decisions = _decisions(output)
    first_before = dict(created[0]["details"])
    second_before = dict(created[1]["details"])

    update_novel_character(
        database_session,
        novel_id,
        UUID(created[1]["id"]),
        expected_version=created[1]["version"],
        role_type=str(created[1]["role_type"]),
        name=str(created[1]["name"]),
        description=str(created[1]["description"]),
        details={"identity": "并发保存后的新身份"},
    )

    with pytest.raises(EntityConflictError):
        apply_character_profile_completion(
            database_session,
            novel_id,
            UUID(str(job["id"])),
            idempotency_key="profile-apply-conflict-001",
            decisions=decisions,
        )
    database_session.rollback()
    rows = _character_rows(database_session, novel_id)
    batch_count = database_session.scalar(
        select(func.count(CharacterProfileApplyBatch.id)).where(
            CharacterProfileApplyBatch.novel_id == novel_id
        )
    )

    assert rows[0].version == 1
    assert rows[0].details == first_before
    assert "personality" not in rows[0].details
    assert rows[1].version == 2
    assert rows[1].details["identity"] == "并发保存后的新身份"
    assert all(
        rows[1].details[key] == second_before[key]
        for key in second_before
    )
    assert "personality" not in rows[1].details
    assert batch_count == 0


def test_restore_creates_new_versions_and_an_idempotent_restore_batch(
    database_session: Session,
) -> None:
    novel_id, _, created = _create_profile_novel(database_session)
    original_details = {item["id"]: dict(item["details"]) for item in created}
    job, output = _ready_profile_job(database_session, novel_id)
    apply_character_profile_completion(
        database_session,
        novel_id,
        UUID(str(job["id"])),
        idempotency_key="profile-restore-source-001",
        decisions=_decisions(output),
    )
    source_batch = database_session.scalar(
        select(CharacterProfileApplyBatch).where(
            CharacterProfileApplyBatch.novel_id == novel_id,
            CharacterProfileApplyBatch.state == "applied",
        )
    )
    assert source_batch is not None

    restored = restore_character_profile_apply_batch(
        database_session,
        novel_id,
        source_batch.id,
        idempotency_key="profile-restore-idempotent-001",
    )
    rows = _character_rows(database_session, novel_id)
    batches = list(
        database_session.scalars(
            select(CharacterProfileApplyBatch)
            .where(CharacterProfileApplyBatch.novel_id == novel_id)
            .order_by(CharacterProfileApplyBatch.created_at)
        ).all()
    )

    assert restored["state"] == "applied"
    assert restored["can_restore"] is False
    assert [row.version for row in rows] == [3, 3]
    assert all(row.details == original_details[str(row.id)] for row in rows)
    assert [batch.state for batch in batches] == ["applied", "restored"]
    assert batches[1].restored_from_batch_id == source_batch.id

    repeated = restore_character_profile_apply_batch(
        database_session,
        novel_id,
        source_batch.id,
        idempotency_key="profile-restore-idempotent-001",
    )
    repeated_rows = _character_rows(database_session, novel_id)
    batch_count = database_session.scalar(
        select(func.count(CharacterProfileApplyBatch.id)).where(
            CharacterProfileApplyBatch.novel_id == novel_id
        )
    )
    assert repeated["state"] == "applied"
    assert [row.version for row in repeated_rows] == [3, 3]
    assert batch_count == 2


def test_restore_conflict_keeps_every_character_and_creates_no_restore_batch(
    database_session: Session,
) -> None:
    novel_id, _, created = _create_profile_novel(database_session)
    job, output = _ready_profile_job(database_session, novel_id)
    apply_character_profile_completion(
        database_session,
        novel_id,
        UUID(str(job["id"])),
        idempotency_key="profile-restore-conflict-source-001",
        decisions=_decisions(output),
    )
    source_batch = database_session.scalar(
        select(CharacterProfileApplyBatch).where(
            CharacterProfileApplyBatch.novel_id == novel_id,
            CharacterProfileApplyBatch.state == "applied",
        )
    )
    assert source_batch is not None
    applied_rows = _character_rows(database_session, novel_id)
    untouched_after_apply = dict(applied_rows[0].details)
    changed = applied_rows[1]
    update_novel_character(
        database_session,
        novel_id,
        changed.id,
        expected_version=changed.version,
        role_type=changed.role_type,
        name=changed.name,
        description=changed.description,
        details={"identity": "应用后作者再次确认的身份"},
    )

    with pytest.raises(EntityConflictError):
        restore_character_profile_apply_batch(
            database_session,
            novel_id,
            source_batch.id,
            idempotency_key="profile-restore-conflict-001",
        )
    database_session.rollback()
    rows = _character_rows(database_session, novel_id)
    restore_count = database_session.scalar(
        select(func.count(CharacterProfileApplyBatch.id)).where(
            CharacterProfileApplyBatch.novel_id == novel_id,
            CharacterProfileApplyBatch.state == "restored",
        )
    )

    assert rows[0].version == 2
    assert rows[0].details == untouched_after_apply
    assert rows[1].version == 3
    assert rows[1].details["identity"] == "应用后作者再次确认的身份"
    assert rows[1].details["personality"]
    assert restore_count == 0


def test_status_recovers_persisted_ready_job_after_session_refresh(
    database_session: Session,
) -> None:
    novel_id, _, _ = _create_profile_novel(database_session, character_count=1)
    job, _ = _ready_profile_job(database_session, novel_id)
    database_session.expire_all()

    status = get_character_profile_completion_status(database_session, novel_id)

    assert status["state"] == "ready"
    assert status["job"]["id"] == str(job["id"])
    assert status["job"]["requested_model"] == TEST_MODEL_ID
    assert status["job"]["actual_model"] == TEST_MODEL_ID
