"""Disposable PostgreSQL 18 gate for T3 typed script persistence and API replay."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

from backend.models import (
    Document,
    DocumentRevision,
    NarrationEdition,
    NarrationScript,
    NarrationScriptVersion,
    NarrationSegment,
    Novel,
    NovelNarrationSettings,
)
from backend.narration.contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID
from backend.narration.privacy import (
    _storage_settings,
    default_narration_settings_values,
)
from backend.narration.requests import CreateNarrationRequest, create_request
from backend.narration.script_api import (
    AnalyzeScriptRequest,
    ScriptApiCommand,
    ScriptApiOperation,
    ScriptReviewResource,
)
from backend.narration.script_backend import build_script_api_backend
from backend.narration.script_contracts import text_sha256
from backend.narration.script_versions import (
    ReserveScriptIdentity,
    persist_script_contract,
    reserve_script_identity,
)
from backend.narration.services import SqlAlchemyNarrationStore
from backend.narration.snapshots import (
    CreateSettingsSnapshot,
    create_settings_snapshot,
)
from tests.narration.test_script_versions_t3_gate import _contract


EXPECTED_DATABASE = "ai_novel_world_2026_tts_test"
EXPECTED_USERNAME = "tts_test"
EXPECTED_HEAD = "20260826_0016"
SOURCE_TEXT = "“没有任何说话提示。”"


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
            "T3 script gate requires the exact disposable loopback database"
        )
    production = os.environ.get("AI_NOVEL_DATABASE_URL", "").strip()
    if production:
        prod = make_url(production)
        if (parsed.host, parsed.port, parsed.database) == (
            prod.host,
            prod.port,
            prod.database,
        ):
            raise RuntimeError("T3 script database must differ from production")
    return raw


@pytest.fixture(scope="module")
def pg_engine() -> Engine:
    engine = create_engine(_live_url(), pool_pre_ping=True)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            EXPECTED_HEAD
        )
        assert int(connection.scalar(text("SHOW server_version_num"))) // 10_000 == 18
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
    content_hash: str


def _seed(engine: Engine) -> _Seed:
    source = SOURCE_TEXT
    novel_id = uuid4()
    document_id = uuid4()
    revision_id = uuid4()
    content_hash = text_sha256(source)
    values = default_narration_settings_values()
    with Session(engine, expire_on_commit=False) as session, session.begin():
        store = SqlAlchemyNarrationStore(session)
        session.add(
            Novel(
                id=novel_id,
                owner_id=LOCAL_OWNER_ID,
                workspace_id=LOCAL_WORKSPACE_ID,
                title=f"t3-script-{novel_id}",
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
                content_markdown=source,
                content_text=source,
                content_hash=content_hash,
                source="manual",
            )
        )
        session.add(
            NovelNarrationSettings(
                id=uuid4(),
                novel_id=novel_id,
                script_review_policy=values.script_review_policy.value,
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
                intent="analyze_only",
                idempotency_key=f"t3-script-request-{novel_id}",
                settings_fingerprint=snapshot.fingerprint,
                effective_policy="blockers_only",
            ),
        )
    return _Seed(
        novel_id=novel_id,
        document_id=document_id,
        revision_id=revision_id,
        request_id=request.id,
        content_hash=content_hash,
    )


def _command(seed: _Seed) -> ScriptApiCommand:
    return ScriptApiCommand(
        operation=ScriptApiOperation.ANALYZE_SCRIPT,
        document_id=seed.document_id,
        idempotency_key="t3-script-analysis-0001",
        payload=AnalyzeScriptRequest(
            request_id=seed.request_id,
            source_revision_id=seed.revision_id,
            source_content_hash=seed.content_hash,
        ),
    )


def test_typed_script_write_reload_and_api_replay_are_postgresql_durable(
    pg_engine: Engine,
) -> None:
    seed = _seed(pg_engine)
    with Session(pg_engine, expire_on_commit=False) as session:
        first = build_script_api_backend(session).dispatch(_command(seed))
    assert isinstance(first, ScriptReviewResource)
    assert first.novel_id == seed.novel_id
    assert first.document_id == seed.document_id
    assert first.revision_id == seed.revision_id
    assert first.blocker_count == 3

    with Session(pg_engine, expire_on_commit=False) as session:
        replay = build_script_api_backend(session).dispatch(_command(seed))
    assert replay == first

    with Session(pg_engine) as session:
        script = session.scalar(
            select(NarrationScript).where(
                NarrationScript.document_id == seed.document_id
            )
        )
        assert script is not None
        versions = session.scalars(
            select(NarrationScriptVersion).where(
                NarrationScriptVersion.script_id == script.id
            )
        ).all()
        assert len(versions) == 1
        assert versions[0].id == first.script_version_id
        assert versions[0].immutable_hash == first.immutable_hash
        segments = session.scalars(
            select(NarrationSegment).where(
                NarrationSegment.script_version_id == first.script_version_id
            )
        ).all()
        assert segments
        assert all(
            segment.casting_json.get("contract_version")
            == "narration-casting-decision/1"
            and segment.evidence_json.get("contract_version")
            == "narration-segment-evidence/1"
            for segment in segments
        )
        assert session.scalar(select(func.count()).select_from(NarrationEdition)) == 0


def test_document_lock_serializes_two_typed_version_allocations(
    pg_engine: Engine,
) -> None:
    seed = _seed(pg_engine)
    first_reserved = threading.Event()
    release_first = threading.Event()
    second_reserved = threading.Event()
    results: dict[str, object] = {}

    def run_first() -> None:
        try:
            with Session(pg_engine, expire_on_commit=False) as session, session.begin():
                store = SqlAlchemyNarrationStore(session)
                allocation = reserve_script_identity(
                    store,
                    ReserveScriptIdentity(
                        novel_id=seed.novel_id,
                        document_id=seed.document_id,
                        revision_id=seed.revision_id,
                        content_hash=seed.content_hash,
                        idempotency_key="t3-concurrent-first-v1",
                    ),
                )
                first_reserved.set()
                assert release_first.wait(timeout=8)
                persist_script_contract(
                    store,
                    allocation,
                    _contract(allocation, SOURCE_TEXT),
                )
                results["first"] = allocation.version_number
        except BaseException as error:
            results["first_error"] = error
            first_reserved.set()

    def run_second() -> None:
        try:
            assert first_reserved.wait(timeout=8)
            with Session(pg_engine, expire_on_commit=False) as session, session.begin():
                store = SqlAlchemyNarrationStore(session)
                allocation = reserve_script_identity(
                    store,
                    ReserveScriptIdentity(
                        novel_id=seed.novel_id,
                        document_id=seed.document_id,
                        revision_id=seed.revision_id,
                        content_hash=seed.content_hash,
                        idempotency_key="t3-concurrent-second-v1",
                    ),
                )
                second_reserved.set()
                persist_script_contract(
                    store,
                    allocation,
                    _contract(allocation, SOURCE_TEXT),
                )
                results["second"] = allocation.version_number
        except BaseException as error:
            results["second_error"] = error
            second_reserved.set()

    first = threading.Thread(target=run_first, daemon=True)
    second = threading.Thread(target=run_second, daemon=True)
    first.start()
    assert first_reserved.wait(timeout=8)
    second.start()
    time.sleep(0.2)
    assert not second_reserved.is_set(), "second allocation bypassed the document lock"
    release_first.set()
    first.join(timeout=8)
    second.join(timeout=8)

    assert not first.is_alive() and not second.is_alive()
    assert "first_error" not in results
    assert "second_error" not in results
    assert results == {"first": 1, "second": 2}
    with Session(pg_engine) as session:
        script = session.scalar(
            select(NarrationScript).where(
                NarrationScript.document_id == seed.document_id
            )
        )
        assert script is not None
        numbers = session.scalars(
            select(NarrationScriptVersion.version_number)
            .where(NarrationScriptVersion.script_id == script.id)
            .order_by(NarrationScriptVersion.version_number)
        ).all()
        assert numbers == [1, 2]
