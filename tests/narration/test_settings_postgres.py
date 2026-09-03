"""Disposable PostgreSQL 18 gate for the integrated T2 settings backend."""

from __future__ import annotations

import os
import threading
import time
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

from backend.models import Novel, NovelNarrationSettings
from backend.narration import schemas as wire
from backend.narration.contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID
from backend.narration.privacy import (
    FIXED_LOCAL_OWNER_NARRATION_AUTHORIZATION,
    build_narration_settings_backend,
    default_narration_settings_values,
)
from backend.narration.services import NarrationCasConflict
from backend.narration.settings_api import (
    NarrationSettingsApiCommand,
    NarrationSettingsOperation,
)
from tests.narration.current_schema_gate import assert_database_at_repository_head


EXPECTED_DATABASE = "ai_novel_world_2026_tts_test"
EXPECTED_USERNAME = "tts_test"


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
        raise RuntimeError("T2 settings gate requires the exact disposable loopback database")
    production = os.environ.get("AI_NOVEL_DATABASE_URL", "").strip()
    if production:
        prod = make_url(production)
        if (parsed.host, parsed.port, parsed.database) == (
            prod.host,
            prod.port,
            prod.database,
        ):
            raise RuntimeError("T2 settings database must differ from production")
    return raw


@pytest.fixture(scope="module")
def pg_engine() -> Engine:
    engine = create_engine(_live_url(), pool_pre_ping=True, pool_size=6)
    with engine.connect() as connection:
        assert_database_at_repository_head(connection)
        assert int(connection.scalar(text("SHOW server_version_num"))) // 10_000 == 18
    try:
        yield engine
    finally:
        engine.dispose()


def _enabled_settings_capabilities() -> wire.NarrationCapabilities:
    enabled = {
        wire.CapabilityKey.NARRATION_PRODUCT,
        wire.CapabilityKey.READING_SETTINGS,
    }
    return wire.NarrationCapabilities(
        items=[
            wire.FeatureCapability(
                key=item.key,
                state=wire.CapabilityState.ENABLED,
                visible=True,
                actionable=True,
                reason_code=None,
                required_gate=None,
            )
            if item.key in enabled
            else item.model_copy(deep=True)
            for item in wire.t2_hold_capabilities().items
        ]
    )


def _seed_novel(engine: Engine) -> UUID:
    novel_id = uuid4()
    with Session(engine) as session, session.begin():
        session.add(
            Novel(
                id=novel_id,
                owner_id=LOCAL_OWNER_ID,
                workspace_id=LOCAL_WORKSPACE_ID,
                title=f"t2-settings-{novel_id}",
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
    return novel_id


def _settings_request(language: str) -> wire.UpdateNarrationSettingsRequest:
    values = default_narration_settings_values().model_copy(update={"language": language})
    return wire.UpdateNarrationSettingsRequest(expected_version=0, values=values)


def test_first_settings_write_serializes_and_loser_observes_cas(
    pg_engine: Engine,
) -> None:
    novel_id = _seed_novel(pg_engine)
    first_flushed = threading.Event()
    release_first = threading.Event()
    results: dict[str, object] = {}
    worker_a_name = f"t2-settings-first-{uuid4()}"[:63]
    worker_b_name = f"t2-settings-contender-{uuid4()}"[:63]
    url = _live_url()
    worker_a_engine = create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"application_name": worker_a_name},
    )
    worker_b_engine = create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"application_name": worker_b_name},
    )

    def run_first() -> None:
        try:
            with Session(worker_a_engine) as session:
                def pause_after_flush(_session: Session, _context: object) -> None:
                    first_flushed.set()
                    assert release_first.wait(timeout=8)

                event.listen(session, "after_flush", pause_after_flush, once=True)
                backend = build_narration_settings_backend(
                    session,
                    authorization=FIXED_LOCAL_OWNER_NARRATION_AUTHORIZATION,
                    capabilities=_enabled_settings_capabilities(),
                )
                results["first"] = backend.dispatch(
                    NarrationSettingsApiCommand(
                        operation=NarrationSettingsOperation.PUT_SETTINGS,
                        novel_id=novel_id,
                        payload=_settings_request("zh-CN"),
                    )
                )
        except BaseException as error:
            results["first_error"] = error
            first_flushed.set()

    def run_contender() -> None:
        try:
            with Session(worker_b_engine) as session:
                backend = build_narration_settings_backend(
                    session,
                    authorization=FIXED_LOCAL_OWNER_NARRATION_AUTHORIZATION,
                    capabilities=_enabled_settings_capabilities(),
                )
                results["contender"] = backend.dispatch(
                    NarrationSettingsApiCommand(
                        operation=NarrationSettingsOperation.PUT_SETTINGS,
                        novel_id=novel_id,
                        payload=_settings_request("en-US"),
                    )
                )
        except BaseException as error:
            results["contender_error"] = error

    first = threading.Thread(target=run_first, daemon=True)
    contender = threading.Thread(target=run_contender, daemon=True)
    first.start()
    assert first_flushed.wait(timeout=8)
    contender.start()

    wait_evidence: tuple[str, tuple[int, ...]] | None = None
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        with pg_engine.connect() as observer:
            row = observer.execute(
                text(
                    """
                    SELECT wait_event_type, pg_blocking_pids(pid)
                    FROM pg_stat_activity
                    WHERE application_name=:name AND state='active'
                    """
                ),
                {"name": worker_b_name},
            ).one_or_none()
        if row is not None and row.wait_event_type == "Lock" and row[1]:
            wait_evidence = (str(row.wait_event_type), tuple(int(pid) for pid in row[1]))
            break
        time.sleep(0.02)

    release_first.set()
    first.join(timeout=8)
    contender.join(timeout=8)
    worker_a_engine.dispose()
    worker_b_engine.dispose()

    assert not first.is_alive() and not contender.is_alive()
    assert wait_evidence is not None
    assert "first_error" not in results
    assert isinstance(results.get("contender_error"), NarrationCasConflict)
    first_resource = results["first"]
    assert isinstance(first_resource, wire.NarrationSettingsResource)
    assert first_resource.version == 1
    with Session(pg_engine) as session:
        rows = list(
            session.scalars(
                select(NovelNarrationSettings).where(
                    NovelNarrationSettings.novel_id == novel_id,
                )
            )
        )
    assert len(rows) == 1
    assert rows[0].version == 1
    print(
        "T2_SETTINGS_LOCK_EVIDENCE "
        f"wait_event={wait_evidence[0]} blockers={len(wait_evidence[1])} winner_version=1",
        flush=True,
    )
