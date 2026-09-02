"""Disposable PostgreSQL 18 gate for the T4 review pointer/action ledger."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from backend.models import (
    Document,
    DocumentRevision,
    NarrationEdition,
    NarrationRequest,
    NarrationScript,
    NarrationScriptReviewActionRecord,
    NarrationScriptVersion,
    Novel,
    NovelNarrationSettings,
)
from backend.narration.contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID
from backend.narration.privacy import (
    _storage_settings,
    default_narration_settings_values,
)
from backend.narration.requests import (
    CreateNarrationRequest,
    advance_request_state,
    create_request,
)
from backend.narration.script_contracts import text_sha256
from backend.narration.services import SqlAlchemyNarrationStore
from backend.narration.snapshots import (
    CreateSettingsSnapshot,
    create_settings_snapshot,
)
from tests.narration.current_schema_gate import assert_database_at_repository_head


EXPECTED_DATABASE = "ai_novel_world_2026_tts_test"
EXPECTED_USERNAME = "tts_test"
SOURCE_TEXT = "她望向窗外。\n\n“我们现在出发。”"


def _live_url() -> str:
    raw = os.environ.get("TTS_TEST_DATABASE_URL", "").strip()
    if not raw:
        pytest.skip("TTS_TEST_DATABASE_URL is not configured")
    parsed = make_url(raw)
    if (
        not parsed.drivername.startswith("postgresql")
        or parsed.database != EXPECTED_DATABASE
        or parsed.username != EXPECTED_USERNAME
        or parsed.host not in {"127.0.0.1", "localhost", "::1"}
    ):
        raise RuntimeError(
            "T4 review ledger gate requires the exact disposable loopback database"
        )
    production = os.environ.get("AI_NOVEL_DATABASE_URL", "").strip()
    if production:
        prod = make_url(production)
        if (parsed.host, parsed.port, parsed.database) == (
            prod.host,
            prod.port,
            prod.database,
        ):
            raise RuntimeError("T4 review ledger database must differ from production")
    return raw


@pytest.fixture(scope="module")
def pg_engine() -> Engine:
    engine = create_engine(_live_url(), pool_pre_ping=True)
    with engine.connect() as connection:
        assert_database_at_repository_head(connection)
        assert int(connection.scalar(text("SHOW server_version_num"))) // 10_000 == 18
        trigger_names = set(
            connection.scalars(
                text(
                    """SELECT tgname
                       FROM pg_trigger
                       WHERE NOT tgisinternal
                         AND tgrelid IN (
                           'narration_requests'::regclass,
                           'narration_script_versions'::regclass,
                           'narration_script_review_actions'::regclass
                         )"""
                )
            )
        )
        assert {
            "trg_t4_review_action_required",
            "trg_t4_manual_script_approval_required",
            "trg_t4_review_action_target_required",
            "trg_t4_narration_script_review_actions_immutable",
        } <= trigger_names
        function_def = connection.scalar(
            text(
                """SELECT pg_get_functiondef(p.oid)
                   FROM pg_proc p
                   JOIN pg_namespace n ON n.oid=p.pronamespace
                   WHERE n.nspname=current_schema()
                     AND p.proname='narration_require_manual_script_approval_action'"""
            )
        )
        assert function_def is not None
        for marker in (
            "became_manual_approved",
            "manual script approval requires action, Edition, and queued request",
            "r.version>=a.request_version_after",
        ):
            assert marker in function_def
        approve_index = connection.scalar(
            text(
                """SELECT indexdef FROM pg_indexes
                   WHERE schemaname=current_schema()
                     AND indexname='uq_narration_review_action_approve_request'"""
            )
        )
        assert approve_index is not None
        assert "CREATE UNIQUE INDEX" in approve_index
        assert "request_id" in approve_index and "action_kind" in approve_index
    try:
        yield engine
    finally:
        engine.dispose()


@dataclass(frozen=True, slots=True)
class _Seed:
    novel_id: UUID
    document_id: UUID
    revision_id: UUID
    request_id: UUID
    legacy_request_id: UUID
    script_id: UUID
    root_version_id: UUID
    settings_snapshot_id: UUID
    settings_fingerprint: str
    content_hash: str


def _review_version(
    *,
    version_id: UUID,
    script_id: UUID,
    version_number: int,
    parent_version_id: UUID | None,
    settings_fingerprint: str,
) -> NarrationScriptVersion:
    return NarrationScriptVersion(
        id=version_id,
        script_id=script_id,
        version_number=version_number,
        parent_version_id=parent_version_id,
        state="review_required",
        analyzer_fingerprint="1" * 64,
        rules_fingerprint="2" * 64,
        settings_fingerprint=settings_fingerprint,
        requested_model_fingerprint=None,
        actual_model_fingerprint=None,
        taxonomy_version="narration-review-taxonomy/1",
        immutable_hash=f"{version_number:x}" * 64,
        idempotency_key=f"t4-pg-version-{version_id}",
        warning_count=0,
        blocker_count=0,
        approval_kind=None,
        approval_request_id=None,
        approval_request_allows_edition=None,
        effective_policy="always_review",
        approved_actor_type=None,
        approved_actor_id=None,
        approved_at=None,
    )


def _expect_statement_rejection(
    session: Session,
    statement: str,
    parameters: dict[str, object],
) -> str:
    savepoint = session.begin_nested()
    try:
        with pytest.raises(DBAPIError) as captured:
            session.execute(text(statement), parameters)
        return str(captured.value)
    finally:
        if savepoint.is_active:
            savepoint.rollback()
        session.expire_all()


def _seed_review_request(engine: Engine) -> _Seed:
    novel_id, document_id, revision_id = uuid4(), uuid4(), uuid4()
    request_id, legacy_request_id = uuid4(), uuid4()
    script_id, root_version_id = uuid4(), uuid4()
    content_hash = text_sha256(SOURCE_TEXT)
    values = default_narration_settings_values()

    with Session(engine, expire_on_commit=False) as session, session.begin():
        store = SqlAlchemyNarrationStore(session)
        session.add(
            Novel(
                id=novel_id,
                owner_id=LOCAL_OWNER_ID,
                workspace_id=LOCAL_WORKSPACE_ID,
                title=f"t4-review-ledger-{novel_id}",
                author_name="author",
                description="",
                writing_type="novel",
                audience="general",
                genre="fiction",
                subgenre="",
                idea="",
                template_name="",
                template_data={},
                cover_mode="none",
                cover_image_data="",
                outline_target_chapters=0,
                highlight="",
                background="",
                main_plot="",
                story_ledger_version=1,
                version=1,
            )
        )
        session.add(
            Document(
                id=document_id,
                novel_id=novel_id,
                kind="chapter",
                title="第一章",
                position=1,
                status="draft",
                version=1,
            )
        )
        session.add(
            DocumentRevision(
                id=revision_id,
                document_id=document_id,
                revision_number=1,
                content_markdown=SOURCE_TEXT,
                content_text=SOURCE_TEXT,
                content_hash=content_hash,
                source="manual",
            )
        )
        session.add(
            NovelNarrationSettings(
                id=uuid4(),
                novel_id=novel_id,
                script_review_policy="always_review",
                analysis_mode=values.analysis_mode.value,
                settings_json=_storage_settings(values),
                version=1,
            )
        )
        session.flush()
        snapshot = create_settings_snapshot(
            store,
            CreateSettingsSnapshot(novel_id=novel_id, settings_version=1),
        )

        request = create_request(
            store,
            CreateNarrationRequest(
                novel_id=novel_id,
                document_id=document_id,
                source_revision_id=revision_id,
                source_content_hash=content_hash,
                intent="create",
                idempotency_key=f"t4-pg-request-{request_id}",
                settings_fingerprint=snapshot.fingerprint,
                force_review=True,
                effective_policy="always_review",
                explicit_generation_intent_at=datetime.now(UTC),
                explicit_generation_actor="owner",
            ),
        )
        request_id = request.id
        request = advance_request_state(
            store,
            request.id,
            expected_version=1,
            new_state="analyzing",
            novel_id=novel_id,
            actor="owner",
        )
        session.add(
            NarrationScript(
                id=script_id,
                novel_id=novel_id,
                document_id=document_id,
                revision_id=revision_id,
                content_hash=content_hash,
                version=1,
            )
        )
        session.add(
            _review_version(
                version_id=root_version_id,
                script_id=script_id,
                version_number=1,
                parent_version_id=None,
                settings_fingerprint=snapshot.fingerprint,
            )
        )
        session.flush()

        same_version_error = _expect_statement_rejection(
            session,
            """UPDATE narration_requests
               SET review_script_id=:script,current_review_version_id=:version
               WHERE id=:request""",
            {"script": script_id, "version": root_version_id, "request": request.id},
        )
        assert "version" in same_version_error or "pointer" in same_version_error
        jump_error = _expect_statement_rejection(
            session,
            """UPDATE narration_requests
               SET review_script_id=:script,current_review_version_id=:version,version=4
               WHERE id=:request""",
            {"script": script_id, "version": root_version_id, "request": request.id},
        )
        assert "version" in jump_error or "pointer" in jump_error

        request = session.get(NarrationRequest, request.id)
        assert request is not None and request.version == 2
        request.review_script_id = script_id
        request.current_review_version_id = root_version_id
        request.version = 3
        request.updated_at = datetime.now(UTC)
        session.flush()
        request = advance_request_state(
            store,
            request.id,
            expected_version=3,
            new_state="review_required",
            novel_id=novel_id,
            actor="owner",
        )
        assert request.version == 4

        legacy = create_request(
            store,
            CreateNarrationRequest(
                novel_id=novel_id,
                document_id=document_id,
                source_revision_id=revision_id,
                source_content_hash=content_hash,
                intent="create",
                idempotency_key=f"t4-pg-legacy-{legacy_request_id}",
                settings_fingerprint=snapshot.fingerprint,
                force_review=True,
                effective_policy="always_review",
                explicit_generation_intent_at=datetime.now(UTC),
                explicit_generation_actor="owner",
            ),
        )
        legacy_request_id = legacy.id
        legacy = advance_request_state(
            store,
            legacy.id,
            expected_version=1,
            new_state="analyzing",
            novel_id=novel_id,
            actor="owner",
        )
        advance_request_state(
            store,
            legacy.id,
            expected_version=legacy.version,
            new_state="review_required",
            novel_id=novel_id,
            actor="owner",
        )

    return _Seed(
        novel_id=novel_id,
        document_id=document_id,
        revision_id=revision_id,
        request_id=request_id,
        legacy_request_id=legacy_request_id,
        script_id=script_id,
        root_version_id=root_version_id,
        settings_snapshot_id=snapshot.id,
        settings_fingerprint=snapshot.fingerprint,
        content_hash=content_hash,
    )


def _action(
    seed: _Seed,
    *,
    action_kind: str,
    parent_version_id: UUID,
    result_version_id: UUID,
    result_edition_id: UUID | None,
    before: int,
    after: int,
    key: str,
) -> NarrationScriptReviewActionRecord:
    seed_bound_key = f"{key}:{seed.request_id}"
    if len(seed_bound_key) > 128:
        raise ValueError("seed-bound review action idempotency key exceeds 128 chars")
    return NarrationScriptReviewActionRecord(
        id=uuid4(),
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        novel_id=seed.novel_id,
        request_id=seed.request_id,
        request_allows_render=True,
        script_id=seed.script_id,
        parent_version_id=parent_version_id,
        result_version_id=result_version_id,
        result_edition_id=result_edition_id,
        action_kind=action_kind,
        request_hash="c" * 64,
        idempotency_key=seed_bound_key,
        request_version_before=before,
        request_version_after=after,
        actor_type="owner",
        actor_id="owner",
    )


def _edition(seed: _Seed, *, edition_id: UUID, version_id: UUID) -> NarrationEdition:
    return NarrationEdition(
        id=edition_id,
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        novel_id=seed.novel_id,
        document_id=seed.document_id,
        request_id=seed.request_id,
        request_allows_edition=True,
        script_version_id=version_id,
        script_is_approved=True,
        settings_snapshot_id=seed.settings_snapshot_id,
        pronunciation_profile_id=None,
        tts_fingerprint="3" * 64,
        tokenizer_fingerprint="4" * 64,
        normalizer_fingerprint="5" * 64,
        postprocess_fingerprint="6" * 64,
        context_mode="independent_segment",
        buffer_policy_version="t4-review-ledger/1",
        edition_fingerprint=text_sha256(
            f"t4-pg-edition:{seed.request_id}:{edition_id}"
        ),
        state="created",
        unavailable_reason=None,
        created_actor="owner",
    )


def test_review_pointer_action_approval_and_downgrade_guards_are_live(
    pg_engine: Engine,
) -> None:
    seed = _seed_review_request(pg_engine)

    with Session(pg_engine) as session:
        transaction = session.begin()
        try:
            session.execute(
                text(
                    """UPDATE narration_requests
                       SET state='analyzing',version=4 WHERE id=:request"""
                ),
                {"request": seed.legacy_request_id},
            )
            session.execute(
                text(
                    """UPDATE narration_requests
                       SET state='queued',version=5 WHERE id=:request"""
                ),
                {"request": seed.legacy_request_id},
            )
            with pytest.raises(DBAPIError, match="proven review pointer"):
                session.execute(
                    text("SET CONSTRAINTS trg_t4_review_action_required IMMEDIATE")
                )
        finally:
            transaction.rollback()

    child_version_id = uuid4()
    with Session(pg_engine, expire_on_commit=False) as session, session.begin():
        request = session.scalar(
            select(NarrationRequest)
            .where(NarrationRequest.id == seed.request_id)
            .with_for_update()
        )
        assert request is not None and request.version == 4
        session.add(
            _review_version(
                version_id=child_version_id,
                script_id=seed.script_id,
                version_number=2,
                parent_version_id=seed.root_version_id,
                settings_fingerprint=seed.settings_fingerprint,
            )
        )
        session.flush()
        correction = _action(
            seed,
            action_kind="patch_segment",
            parent_version_id=seed.root_version_id,
            result_version_id=child_version_id,
            result_edition_id=None,
            before=4,
            after=5,
            key="t4-pg-correction-0001",
        )
        session.add(correction)
        request.current_review_version_id = child_version_id
        request.version = 5
        request.updated_at = datetime.now(UTC)

    orphan_version_id = uuid4()
    with pytest.raises(DBAPIError, match="current pointer"):
        with Session(pg_engine) as session, session.begin():
            session.add(
                _review_version(
                    version_id=orphan_version_id,
                    script_id=seed.script_id,
                    version_number=3,
                    parent_version_id=child_version_id,
                    settings_fingerprint=seed.settings_fingerprint,
                )
            )
            session.flush()
            session.add(
                _action(
                    seed,
                    action_kind="patch_segment",
                    parent_version_id=child_version_id,
                    result_version_id=orphan_version_id,
                    result_edition_id=None,
                    before=5,
                    after=6,
                    key="t4-pg-orphan-0001",
                )
            )

    with pytest.raises(IntegrityError, match="uq_narration_review_action_request_version"):
        with Session(pg_engine) as session, session.begin():
            session.add(
                _action(
                    seed,
                    action_kind="patch_segment",
                    parent_version_id=seed.root_version_id,
                    result_version_id=child_version_id,
                    result_edition_id=None,
                    before=4,
                    after=5,
                    key="t4-pg-duplicate-transition-0001",
                )
            )
            session.flush()

    with Session(pg_engine) as session:
        action_id = session.scalar(
            select(NarrationScriptReviewActionRecord.id).where(
                NarrationScriptReviewActionRecord.request_id == seed.request_id
            )
        )
        assert action_id is not None
        assert "immutable narration row" in _expect_statement_rejection(
            session,
            "UPDATE narration_script_review_actions SET actor_id='changed' WHERE id=:id",
            {"id": action_id},
        )
        assert "immutable narration row" in _expect_statement_rejection(
            session,
            "DELETE FROM narration_script_review_actions WHERE id=:id",
            {"id": action_id},
        )

    with pytest.raises(
        DBAPIError,
        match="manual script approval requires action, Edition, and queued request",
    ):
        with Session(pg_engine) as session, session.begin():
            version = session.get(NarrationScriptVersion, child_version_id)
            assert version is not None
            version.state = "approved"
            version.approval_kind = "manual_after_review"
            version.approval_request_id = seed.request_id
            version.approval_request_allows_edition = True
            version.approved_actor_type = "owner"
            version.approved_actor_id = "owner"
            version.approved_at = datetime.now(UTC)

    rejected_edition_id = uuid4()
    with Session(pg_engine) as session:
        transaction = session.begin()
        try:
            request = session.get(NarrationRequest, seed.request_id)
            version = session.get(NarrationScriptVersion, child_version_id)
            assert request is not None and version is not None
            version.state = "approved"
            version.approval_kind = "manual_after_review"
            version.approval_request_id = request.id
            version.approval_request_allows_edition = True
            version.approved_actor_type = "owner"
            version.approved_actor_id = "owner"
            version.approved_at = datetime.now(UTC)
            session.flush()
            session.add(
                _edition(
                    seed,
                    edition_id=rejected_edition_id,
                    version_id=child_version_id,
                )
            )
            request.state = "queued"
            request.version = 6
            request.updated_at = datetime.now(UTC)
            session.flush()
            with pytest.raises(DBAPIError, match="manual review continuation"):
                session.execute(
                    text("SET CONSTRAINTS trg_t4_review_action_required IMMEDIATE")
                )
        finally:
            transaction.rollback()

    edition_id = uuid4()
    with Session(pg_engine, expire_on_commit=False) as session, session.begin():
        request = session.scalar(
            select(NarrationRequest)
            .where(NarrationRequest.id == seed.request_id)
            .with_for_update()
        )
        version = session.get(NarrationScriptVersion, child_version_id)
        assert request is not None and request.version == 5 and version is not None
        version.state = "approved"
        version.approval_kind = "manual_after_review"
        version.approval_request_id = request.id
        version.approval_request_allows_edition = True
        version.approved_actor_type = "owner"
        version.approved_actor_id = "owner"
        version.approved_at = datetime.now(UTC)
        session.flush()
        session.add(_edition(seed, edition_id=edition_id, version_id=child_version_id))
        session.flush()
        approval = _action(
            seed,
            action_kind="approve",
            parent_version_id=child_version_id,
            result_version_id=child_version_id,
            result_edition_id=edition_id,
            before=5,
            after=6,
            key="t4-pg-approve-0001",
        )
        session.add(approval)
        request.state = "queued"
        request.version = 6
        request.updated_at = datetime.now(UTC)

    with Session(pg_engine) as session:
        request = session.get(NarrationRequest, seed.request_id)
        assert request is not None
        assert (request.state, request.version) == ("queued", 6)
        actions = session.scalars(
            select(NarrationScriptReviewActionRecord)
            .where(NarrationScriptReviewActionRecord.request_id == seed.request_id)
            .order_by(NarrationScriptReviewActionRecord.request_version_after)
        ).all()
        assert [item.action_kind for item in actions] == ["patch_segment", "approve"]
        assert actions[-1].result_edition_id == edition_id
        assert actions[-1].created_at.year >= 2026

    with Session(pg_engine) as session, session.begin():
        store = SqlAlchemyNarrationStore(session)
        request = advance_request_state(
            store,
            seed.request_id,
            expected_version=6,
            new_state="rendering",
            novel_id=seed.novel_id,
            actor="worker",
        )
        request = advance_request_state(
            store,
            seed.request_id,
            expected_version=request.version,
            new_state="ready",
            novel_id=seed.novel_id,
            actor="worker",
        )
        assert request.version == 8

    with pytest.raises(
        IntegrityError,
        match="uq_narration_review_action_approve_request",
    ):
        with Session(pg_engine) as session, session.begin():
            session.add(
                _action(
                    seed,
                    action_kind="approve",
                    parent_version_id=child_version_id,
                    result_version_id=child_version_id,
                    result_edition_id=edition_id,
                    before=7,
                    after=8,
                    key="t4-pg-fake-second-approve-0002",
                )
            )
            session.flush()

    with Session(pg_engine) as session:
        request = session.get(NarrationRequest, seed.request_id)
        assert request is not None and (request.state, request.version) == ("ready", 8)
        assert session.scalar(
            text(
                """SELECT count(*) FROM narration_script_review_actions
                   WHERE request_id=:request AND action_kind='approve'"""
            ),
            {"request": seed.request_id},
        ) == 1

    url = _live_url()
    config = Config(str(os.path.join(os.path.dirname(__file__), "../../alembic.ini")))
    config.set_main_option("sqlalchemy.url", url)
    old_database_url = os.environ.get("AI_NOVEL_DATABASE_URL")
    os.environ["AI_NOVEL_DATABASE_URL"] = url
    try:
        with pytest.raises(Exception, match="0020 downgrade refused"):
            command.downgrade(config, "20260827_0019")
    finally:
        if old_database_url is None:
            os.environ.pop("AI_NOVEL_DATABASE_URL", None)
        else:
            os.environ["AI_NOVEL_DATABASE_URL"] = old_database_url
    with pg_engine.connect() as connection:
        assert_database_at_repository_head(connection)
