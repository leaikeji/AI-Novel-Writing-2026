"""PostgreSQL 18 live gate for T1 narration aggregate serialization.

The tests in this module deliberately use independent transactions and inspect
``pg_stat_activity`` before releasing the blocker.  They are skipped unless the
caller supplies the exact disposable loopback database through
``TTS_TEST_DATABASE_URL``.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from backend.models import (
    Document,
    DocumentRevision,
    NarrationScene,
    NarrationScopeOverride,
    NarrationScriptVersion,
    NarrationSettingsSnapshot,
    Novel,
    VoiceProfile,
    VoiceProfileVersion,
    VoiceRightsEvent,
    VoiceRightsRecord,
)
from backend.narration.contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID
from backend.narration.requests import (
    CreateNarrationRequest,
    advance_request_state,
    create_request,
)
from backend.narration.script_versions import (
    CreateScriptDraft,
    ScriptSceneInput,
    ScriptSegmentInput,
    approve_script_version,
    create_script_draft,
)
from backend.narration.services import (
    NarrationNotFound,
    SqlAlchemyNarrationStore,
    StaleNarrationInput,
    VoiceRightsUnavailable,
    require_usable_voice,
)
from backend.narration.settings import NarrationSettingsUpdate, update_settings
from backend.narration.snapshots import CreateSettingsSnapshot, create_settings_snapshot
from backend.services import content_hash


EXPECTED_DATABASE = "ai_novel_world_2026_tts_test"
EXPECTED_USERNAME = "tts_test"
EXPECTED_HEAD = "20260826_0015"
SHA_A = "a" * 64
SHA_B = "b" * 64
NOW = datetime(2026, 8, 26, 8, 0, tzinfo=UTC)


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
            "domain concurrency tests require the exact disposable loopback PostgreSQL database"
        )
    production = os.environ.get("AI_NOVEL_DATABASE_URL", "").strip()
    if production:
        production_url = make_url(production)
        if (parsed.host, parsed.port, parsed.database) == (
            production_url.host,
            production_url.port,
            production_url.database,
        ):
            raise RuntimeError("domain concurrency database must differ from production")
    return raw


@pytest.fixture(scope="module")
def pg_engine() -> Engine:
    engine = create_engine(_live_url(), pool_pre_ping=True, pool_size=12, max_overflow=4)
    with engine.connect() as connection:
        head = connection.scalar(text("SELECT version_num FROM alembic_version"))
        version_num = int(connection.scalar(text("SHOW server_version_num")))
        assert head == EXPECTED_HEAD
        assert version_num // 10_000 == 18
        print(
            f"POSTGRES_GATE_EVIDENCE version_num={version_num} alembic_head={head}",
            flush=True,
        )
    try:
        yield engine
    finally:
        engine.dispose()


def _novel(novel_id: UUID | None = None) -> Novel:
    return Novel(
        id=novel_id or uuid4(),
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        title=f"domain-concurrency-{uuid4()}",
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


def _set_worker(session: Session, application_name: str) -> None:
    application_name = application_name[:63]
    session.execute(
        text("SELECT set_config('application_name', :name, true)"),
        {"name": application_name},
    )
    session.execute(text("SET LOCAL lock_timeout = '8s'"))


@dataclass(frozen=True, slots=True)
class LockWaitEvidence:
    application_name: str
    pid: int
    wait_event: str
    blocker_pids: tuple[int, ...]


def _wait_until_lock_wait(engine: Engine, application_name: str) -> LockWaitEvidence:
    application_name = application_name[:63]
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        with engine.connect() as observer:
            row = observer.execute(
                text(
                    """
                    SELECT pid, wait_event_type, wait_event, pg_blocking_pids(pid)
                    FROM pg_stat_activity
                    WHERE application_name=:name AND state='active'
                    """
                ),
                {"name": application_name},
            ).one_or_none()
        if row is not None and row.wait_event_type == "Lock" and row[3]:
            evidence = LockWaitEvidence(
                application_name=application_name,
                pid=int(row.pid),
                wait_event=str(row.wait_event),
                blocker_pids=tuple(int(item) for item in row[3]),
            )
            print(
                "LOCK_WAIT_EVIDENCE "
                f"worker={evidence.application_name} pid={evidence.pid} "
                f"wait_event={evidence.wait_event} blockers={evidence.blocker_pids}",
                flush=True,
            )
            return evidence
        time.sleep(0.02)
    raise AssertionError(f"{application_name} never reached an observable PostgreSQL lock wait")


def _join_threads(*threads: threading.Thread) -> None:
    for thread in threads:
        thread.join(timeout=8)
    assert all(not thread.is_alive() for thread in threads), "concurrency worker did not finish"


@dataclass(frozen=True, slots=True)
class ScriptSeed:
    novel_id: UUID
    request_id: UUID
    version_id: UUID
    scene_id: UUID | None


def _seed_script(engine: Engine, *, with_scene: bool) -> ScriptSeed:
    novel = _novel()
    document = Document(
        id=uuid4(),
        novel_id=novel.id,
        kind="chapter",
        title="chapter",
        position=1,
        status="draft",
        version=1,
    )
    markdown = "并发审批基线"
    revision = DocumentRevision(
        id=uuid4(),
        document_id=document.id,
        revision_number=1,
        content_markdown=markdown,
        content_text=markdown,
        content_hash=content_hash(markdown),
        source="manual_checkpoint",
    )
    scene_id = uuid4() if with_scene else None
    segment_id = uuid4()
    scenes = (
        (
            ScriptSceneInput(
                scene_id=scene_id,
                ordinal=0,
                source_start=0,
                source_end=4,
                boundary_source="paragraph",
                local_hash=SHA_A,
                title="baseline-scene",
            ),
        )
        if scene_id is not None
        else ()
    )
    with Session(engine, expire_on_commit=False) as session:
        store = SqlAlchemyNarrationStore(session)
        store.add(novel)
        store.flush()
        store.add(document)
        store.flush()
        store.add(revision)
        store.flush()
        request = create_request(
            store,
            CreateNarrationRequest(
                novel_id=novel.id,
                document_id=document.id,
                source_revision_id=revision.id,
                source_content_hash=revision.content_hash,
                intent="create",
                idempotency_key=f"domain-concurrency-request-{uuid4()}",
                settings_fingerprint=SHA_A,
                explicit_generation_intent_at=NOW,
                explicit_generation_actor="owner",
            ),
        )
        version = create_script_draft(
            store,
            CreateScriptDraft(
                novel_id=novel.id,
                document_id=document.id,
                revision_id=revision.id,
                content_hash=revision.content_hash,
                settings_fingerprint=SHA_A,
                analyzer_fingerprint=SHA_A,
                rules_fingerprint=SHA_B,
                idempotency_key=f"domain-concurrency-script-{uuid4()}",
                effective_policy="blockers_only",
                scenes=scenes,
                segments=(
                    ScriptSegmentInput(
                        segment_id=segment_id,
                        scene_id=scene_id,
                        ordinal=0,
                        segment_kind="narration",
                        paragraph_ordinal=0,
                        source_block_key="paragraph-0",
                        source_start_utf16=0,
                        source_end_utf16=4,
                        source_text=markdown,
                        spoken_text=markdown,
                        local_hash=SHA_B,
                        speaker_kind="narrator",
                        casting_json={"source": "narrator"},
                        evidence_json={},
                        confidence="high",
                        pause_before_ms=0,
                        pause_after_ms=0,
                        manual_override=False,
                    ),
                ),
            ),
        )
        request = advance_request_state(
            store,
            request.id,
            expected_version=request.version,
            new_state="analyzing",
            novel_id=novel.id,
            actor="analyzer",
        )
        session.commit()
        return ScriptSeed(novel.id, request.id, version.id, scene_id)


def _approve_and_hold(
    engine: Engine,
    seed: ScriptSeed,
    *,
    application_name: str,
    approved: threading.Event,
    release: threading.Event,
    result: dict[str, object],
) -> None:
    try:
        with Session(engine, expire_on_commit=False) as session:
            _set_worker(session, application_name)
            row = approve_script_version(
                SqlAlchemyNarrationStore(session),
                seed.version_id,
                request_id=seed.request_id,
                actor_type="system",
                actor_id="rules-v1",
            )
            assert row.state == "approved"
            approved.set()
            assert release.wait(timeout=8)
            session.commit()
    except BaseException as error:  # asserted in the controlling test thread
        result["approval_error"] = error
        approved.set()


def test_script_child_insert_first_blocks_approval_then_stale_hash_rejects(
    pg_engine: Engine,
) -> None:
    """A committed pre-approval child may invalidate, but never trail, approval."""

    seed = _seed_script(pg_engine, with_scene=False)
    child_written = threading.Event()
    release_child = threading.Event()
    result: dict[str, object] = {}
    approval_name = f"t1f-script-approval-after-child-{uuid4()}"

    def insert_child() -> None:
        try:
            with Session(pg_engine) as session:
                _set_worker(session, f"t1f-script-child-first-{uuid4()}")
                session.add(
                    NarrationScene(
                        id=uuid4(),
                        script_version_id=seed.version_id,
                        ordinal=0,
                        source_start=0,
                        source_end=1,
                        boundary_source="injected-before-approval",
                        local_hash=SHA_A,
                        title="new child",
                    )
                )
                session.flush()
                child_written.set()
                assert release_child.wait(timeout=8)
                session.commit()
        except BaseException as error:
            result["child_error"] = error
            child_written.set()

    def approve_after_child() -> None:
        assert child_written.wait(timeout=8)
        try:
            with Session(pg_engine) as session:
                _set_worker(session, approval_name)
                approve_script_version(
                    SqlAlchemyNarrationStore(session),
                    seed.version_id,
                    request_id=seed.request_id,
                    actor_type="system",
                    actor_id="rules-v1",
                )
                session.commit()
        except BaseException as error:
            result["approval_error"] = error

    child_thread = threading.Thread(target=insert_child, daemon=True)
    approval_thread = threading.Thread(target=approve_after_child, daemon=True)
    child_thread.start()
    assert child_written.wait(timeout=8)
    approval_thread.start()
    try:
        evidence = _wait_until_lock_wait(pg_engine, approval_name)
        assert evidence.blocker_pids
    finally:
        release_child.set()
    _join_threads(child_thread, approval_thread)

    assert "child_error" not in result
    assert isinstance(result.get("approval_error"), StaleNarrationInput)
    with Session(pg_engine) as session:
        version = session.get(NarrationScriptVersion, seed.version_id)
        assert version is not None and version.state == "analyzed"
        assert session.scalar(
            select(func.count()).select_from(NarrationScene).where(
                NarrationScene.script_version_id == seed.version_id
            )
        ) == 1


def test_script_approval_first_blocks_then_rejects_child_insert(
    pg_engine: Engine,
) -> None:
    seed = _seed_script(pg_engine, with_scene=False)
    approved = threading.Event()
    release_approval = threading.Event()
    result: dict[str, object] = {}
    child_name = f"t1f-script-child-after-approval-{uuid4()}"

    approval_thread = threading.Thread(
        target=_approve_and_hold,
        args=(pg_engine, seed),
        kwargs={
            "application_name": f"t1f-script-approval-first-{uuid4()}",
            "approved": approved,
            "release": release_approval,
            "result": result,
        },
        daemon=True,
    )

    def insert_child() -> None:
        assert approved.wait(timeout=8)
        try:
            with Session(pg_engine) as session:
                _set_worker(session, child_name)
                session.add(
                    NarrationScene(
                        id=uuid4(),
                        script_version_id=seed.version_id,
                        ordinal=0,
                        source_start=0,
                        source_end=1,
                        boundary_source="injected-after-approval",
                        local_hash=SHA_A,
                        title="must fail",
                    )
                )
                session.commit()
        except BaseException as error:
            result["child_error"] = error

    child_thread = threading.Thread(target=insert_child, daemon=True)
    approval_thread.start()
    assert approved.wait(timeout=8)
    child_thread.start()
    try:
        evidence = _wait_until_lock_wait(pg_engine, child_name)
        assert evidence.blocker_pids
    finally:
        release_approval.set()
    _join_threads(approval_thread, child_thread)

    assert "approval_error" not in result
    assert isinstance(result.get("child_error"), DBAPIError)
    assert "approved narration script children are immutable" in str(
        result["child_error"]
    )
    with Session(pg_engine) as session:
        version = session.get(NarrationScriptVersion, seed.version_id)
        assert version is not None and version.state == "approved"
        assert session.scalar(
            select(func.count()).select_from(NarrationScene).where(
                NarrationScene.script_version_id == seed.version_id
            )
        ) == 0


@pytest.mark.parametrize("mutation", ["update", "delete"])
def test_script_approval_first_blocks_then_rejects_existing_child_mutation(
    pg_engine: Engine,
    mutation: str,
) -> None:
    seed = _seed_script(pg_engine, with_scene=True)
    assert seed.scene_id is not None
    approved = threading.Event()
    release_approval = threading.Event()
    result: dict[str, object] = {}
    child_name = f"t1f-script-child-{mutation}-after-approval-{uuid4()}"

    approval_thread = threading.Thread(
        target=_approve_and_hold,
        args=(pg_engine, seed),
        kwargs={
            "application_name": f"t1f-script-approval-before-{mutation}-{uuid4()}",
            "approved": approved,
            "release": release_approval,
            "result": result,
        },
        daemon=True,
    )

    def mutate_child() -> None:
        assert approved.wait(timeout=8)
        statement = (
            text("UPDATE narration_scenes SET title='forbidden' WHERE id=:id")
            if mutation == "update"
            else text("DELETE FROM narration_scenes WHERE id=:id")
        )
        try:
            with Session(pg_engine) as session:
                _set_worker(session, child_name)
                session.execute(statement, {"id": seed.scene_id})
                session.commit()
        except BaseException as error:
            result["child_error"] = error

    child_thread = threading.Thread(target=mutate_child, daemon=True)
    approval_thread.start()
    assert approved.wait(timeout=8)
    child_thread.start()
    try:
        evidence = _wait_until_lock_wait(pg_engine, child_name)
        assert evidence.blocker_pids
    finally:
        release_approval.set()
    _join_threads(approval_thread, child_thread)

    assert "approval_error" not in result
    assert isinstance(result.get("child_error"), DBAPIError)
    assert "approved narration script children are immutable" in str(
        result["child_error"]
    )
    with Session(pg_engine) as session:
        version = session.get(NarrationScriptVersion, seed.version_id)
        scene = session.get(NarrationScene, seed.scene_id)
        assert version is not None and version.state == "approved"
        assert scene is not None and scene.title == "baseline-scene"


@dataclass(frozen=True, slots=True)
class SettingsSeed:
    novel_id: UUID
    override_id: UUID | None
    override_scope_id: UUID | None


def _seed_settings(
    engine: Engine,
    *,
    with_settings: bool,
    with_override: bool = False,
) -> SettingsSeed:
    novel = _novel()
    novel_id = novel.id
    override_id = uuid4() if with_override else None
    # narration_validate_scope requires a real chapter/volume target.
    override_scope_id = uuid4()
    with Session(engine, expire_on_commit=False) as session:
        store = SqlAlchemyNarrationStore(session)
        store.add(novel)
        store.flush()
        store.add(
            Document(
                id=override_scope_id,
                novel_id=novel_id,
                kind="chapter",
                title="settings scope",
                position=1,
                status="draft",
                version=1,
            )
        )
        store.flush()
        if with_settings:
            update_settings(
                store,
                NarrationSettingsUpdate(
                    novel_id=novel_id,
                    script_review_policy="blockers_only",
                    analysis_mode="local_rules_only",
                    settings_json={"epoch": "before"},
                    expected_version=0,
                ),
            )
        if with_override:
            assert override_id is not None
            store.add(
                NarrationScopeOverride(
                    id=override_id,
                    novel_id=novel_id,
                    scope_kind="chapter",
                    scope_id=override_scope_id,
                    settings_json={"voice": "before"},
                    version=1,
                )
            )
            store.flush()
        session.commit()
    return SettingsSeed(novel_id, override_id, override_scope_id)


def _create_settings_snapshot_committed(
    engine: Engine,
    *,
    novel_id: UUID,
    settings_version: int,
) -> dict[str, object]:
    with Session(engine, expire_on_commit=False) as session:
        row = create_settings_snapshot(
            SqlAlchemyNarrationStore(session),
            CreateSettingsSnapshot(
                novel_id=novel_id,
                settings_version=settings_version,
            ),
        )
        payload = row.snapshot_json
        session.commit()
        return payload


def _resolved_settings(payload: dict[str, object]) -> dict[str, object]:
    resolved = payload["resolved_settings"]
    assert isinstance(resolved, dict)
    return resolved


def test_initial_settings_insert_waits_for_snapshot_aggregate_probe(
    pg_engine: Engine,
) -> None:
    """Even the first settings row cannot appear inside a snapshot read window."""

    seed = _seed_settings(pg_engine, with_settings=False)
    probe_locked = threading.Event()
    release_probe = threading.Event()
    result: dict[str, object] = {}
    writer_name = f"t1f-settings-initial-insert-{uuid4()}"

    def snapshot_probe() -> None:
        try:
            with Session(pg_engine) as session:
                _set_worker(session, f"t1f-settings-missing-probe-{uuid4()}")
                try:
                    create_settings_snapshot(
                        SqlAlchemyNarrationStore(session),
                        CreateSettingsSnapshot(
                            novel_id=seed.novel_id,
                            settings_version=1,
                        ),
                    )
                except NarrationNotFound as error:
                    result["probe_error"] = error
                else:
                    raise AssertionError("settings-less snapshot probe unexpectedly succeeded")
                # The service acquired Novel FOR UPDATE before discovering the
                # absent settings row.  Keep that exact transaction open.
                probe_locked.set()
                assert release_probe.wait(timeout=8)
                session.rollback()
        except BaseException as error:
            result["probe_thread_error"] = error
            probe_locked.set()

    def insert_initial_settings() -> None:
        assert probe_locked.wait(timeout=8)
        try:
            with Session(pg_engine) as session:
                _set_worker(session, writer_name)
                session.execute(
                    text(
                        """
                        INSERT INTO novel_narration_settings
                          (id,novel_id,script_review_policy,analysis_mode,settings_json,version)
                        VALUES
                          (:id,:novel_id,'blockers_only','local_rules_only',
                           CAST(:settings AS jsonb),1)
                        """
                    ),
                    {
                        "id": uuid4(),
                        "novel_id": seed.novel_id,
                        "settings": json.dumps({"epoch": "after"}),
                    },
                )
                session.commit()
        except BaseException as error:
            result["writer_error"] = error

    probe_thread = threading.Thread(target=snapshot_probe, daemon=True)
    writer_thread = threading.Thread(target=insert_initial_settings, daemon=True)
    probe_thread.start()
    assert probe_locked.wait(timeout=8)
    writer_thread.start()
    try:
        evidence = _wait_until_lock_wait(pg_engine, writer_name)
        assert evidence.blocker_pids
    finally:
        release_probe.set()
    _join_threads(probe_thread, writer_thread)

    assert isinstance(result.get("probe_error"), NarrationNotFound)
    assert "probe_thread_error" not in result and "writer_error" not in result
    after = _create_settings_snapshot_committed(
        pg_engine, novel_id=seed.novel_id, settings_version=1
    )
    resolved = _resolved_settings(after)
    assert resolved["settings"] == {"epoch": "after"}
    assert resolved["scope_overrides"] == []


@pytest.mark.parametrize(
    ("mutation", "with_override"),
    [
        ("settings_update", False),
        ("override_insert", False),
        ("override_update", True),
    ],
)
def test_settings_snapshot_serializes_settings_and_override_mutations(
    pg_engine: Engine,
    mutation: str,
    with_override: bool,
) -> None:
    seed = _seed_settings(
        pg_engine,
        with_settings=True,
        with_override=with_override,
    )
    snapshot_ready = threading.Event()
    release_snapshot = threading.Event()
    result: dict[str, object] = {}
    writer_name = f"t1f-settings-{mutation}-{uuid4()}"

    def snapshot_before() -> None:
        try:
            with Session(pg_engine, expire_on_commit=False) as session:
                _set_worker(session, f"t1f-settings-snapshot-before-{uuid4()}")
                row = create_settings_snapshot(
                    SqlAlchemyNarrationStore(session),
                    CreateSettingsSnapshot(
                        novel_id=seed.novel_id,
                        settings_version=1,
                    ),
                )
                result["before"] = row.snapshot_json
                snapshot_ready.set()
                assert release_snapshot.wait(timeout=8)
                session.commit()
        except BaseException as error:
            result["snapshot_error"] = error
            snapshot_ready.set()

    def mutate_settings() -> None:
        assert snapshot_ready.wait(timeout=8)
        if mutation == "settings_update":
            statement = text(
                """
                UPDATE novel_narration_settings
                SET settings_json=CAST(:settings AS jsonb), version=version+1
                WHERE novel_id=:novel_id
                """
            )
            params = {
                "novel_id": seed.novel_id,
                "settings": json.dumps({"epoch": "after"}),
            }
        elif mutation == "override_insert":
            assert seed.override_scope_id is not None
            statement = text(
                """
                INSERT INTO narration_scope_overrides
                  (id,novel_id,scope_kind,scope_id,settings_json,version)
                VALUES
                  (:id,:novel_id,'chapter',:scope_id,CAST(:settings AS jsonb),1)
                """
            )
            params = {
                "id": uuid4(),
                "novel_id": seed.novel_id,
                "scope_id": seed.override_scope_id,
                "settings": json.dumps({"voice": "after-insert"}),
            }
        else:
            assert seed.override_id is not None
            statement = text(
                """
                UPDATE narration_scope_overrides
                SET settings_json=CAST(:settings AS jsonb), version=version+1
                WHERE id=:id
                """
            )
            params = {
                "id": seed.override_id,
                "settings": json.dumps({"voice": "after-update"}),
            }
        try:
            with Session(pg_engine) as session:
                _set_worker(session, writer_name)
                changed = session.execute(statement, params)
                assert changed.rowcount == 1
                session.commit()
        except BaseException as error:
            result["writer_error"] = error

    snapshot_thread = threading.Thread(target=snapshot_before, daemon=True)
    writer_thread = threading.Thread(target=mutate_settings, daemon=True)
    snapshot_thread.start()
    assert snapshot_ready.wait(timeout=8)
    writer_thread.start()
    try:
        evidence = _wait_until_lock_wait(pg_engine, writer_name)
        assert evidence.blocker_pids
    finally:
        release_snapshot.set()
    _join_threads(snapshot_thread, writer_thread)

    assert "snapshot_error" not in result and "writer_error" not in result
    before = result["before"]
    assert isinstance(before, dict)
    before_resolved = _resolved_settings(before)
    expected_version = 2 if mutation == "settings_update" else 1
    after = _create_settings_snapshot_committed(
        pg_engine,
        novel_id=seed.novel_id,
        settings_version=expected_version,
    )
    after_resolved = _resolved_settings(after)

    if mutation == "settings_update":
        assert before_resolved["settings"] == {"epoch": "before"}
        assert after_resolved["settings"] == {"epoch": "after"}
        assert before_resolved["scope_overrides"] == []
        assert after_resolved["scope_overrides"] == []
    elif mutation == "override_insert":
        assert before_resolved["settings"] == after_resolved["settings"] == {
            "epoch": "before"
        }
        assert before_resolved["scope_overrides"] == []
        assert len(after_resolved["scope_overrides"]) == 1
        assert after_resolved["scope_overrides"][0]["version"] == 1
        assert after_resolved["scope_overrides"][0]["settings"] == {
            "voice": "after-insert"
        }
    else:
        before_overrides = before_resolved["scope_overrides"]
        after_overrides = after_resolved["scope_overrides"]
        assert len(before_overrides) == len(after_overrides) == 1
        assert before_overrides[0]["version"] == 1
        assert before_overrides[0]["settings"] == {"voice": "before"}
        assert after_overrides[0]["version"] == 2
        assert after_overrides[0]["settings"] == {"voice": "after-update"}

    with Session(pg_engine) as session:
        assert session.scalar(
            select(func.count()).select_from(NarrationSettingsSnapshot).where(
                NarrationSettingsSnapshot.novel_id == seed.novel_id
            )
        ) == 2


@dataclass(frozen=True, slots=True)
class VoiceSeed:
    novel_id: UUID
    rights_id: UUID
    profile_id: UUID
    voice_version_id: UUID


def _seed_voice(engine: Engine) -> VoiceSeed:
    novel = _novel()
    rights = VoiceRightsRecord(
        id=uuid4(),
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        novel_id=novel.id,
        source_kind="preset_license",
        source_identifier=f"preset:{uuid4()}",
        notice_version="rights/1",
        purpose="narration",
        commercial_use=True,
        redistribution=False,
        voice_cloning=True,
        confirmed_actor="owner",
        confirmed_at=NOW,
        expires_at=NOW + timedelta(days=365),
        risk_flags_json=[],
    )
    profile = VoiceProfile(
        id=uuid4(),
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        novel_id=novel.id,
        name="concurrency voice",
        current_version_id=None,
        status="active",
        version=1,
    )
    voice = VoiceProfileVersion(
        id=uuid4(),
        profile_id=profile.id,
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        version_number=1,
        source_type="preset",
        state="locked",
        preset_key=f"domain-concurrency-{uuid4()}",
        rights_record_id=rights.id,
        language="zh-CN",
        seed=7,
        parameters_json={},
        fingerprint=content_hash(str(uuid4())),
        quality_state="accepted",
        activation_basis="preview_confirmed",
        validation_basis="human_accepted",
        locked_actor="owner",
        locked_at=NOW,
    )
    seed = VoiceSeed(novel.id, rights.id, profile.id, voice.id)
    with Session(engine, expire_on_commit=False) as session:
        session.add(novel)
        session.flush()
        session.add(rights)
        session.flush()
        session.add(profile)
        session.flush()
        session.add(voice)
        session.flush()
        profile.current_version_id = voice.id
        profile.version = 2
        session.flush()
        session.commit()
    return seed


def _insert_revoke_and_hold(
    engine: Engine,
    seed: VoiceSeed,
    *,
    application_name: str,
    inserted: threading.Event,
    release: threading.Event,
    result: dict[str, object],
) -> None:
    try:
        with Session(engine) as session:
            _set_worker(session, application_name)
            session.add(
                VoiceRightsEvent(
                    id=uuid4(),
                    rights_record_id=seed.rights_id,
                    event_key=f"revoke-{uuid4()}",
                    event_type="revoked",
                    actor="owner",
                    reason_code="owner-revoked",
                    occurred_at=NOW,
                )
            )
            session.flush()
            inserted.set()
            assert release.wait(timeout=8)
            session.commit()
    except BaseException as error:
        result["revoke_error"] = error
        inserted.set()


def test_voice_use_first_serializes_revoke_after_publication_boundary(
    pg_engine: Engine,
) -> None:
    """The authority read used by Edition/Manifest holds rights until commit."""

    seed = _seed_voice(pg_engine)
    voice_usable = threading.Event()
    release_voice_use = threading.Event()
    result: dict[str, object] = {}
    revoke_name = f"t1f-rights-revoke-after-use-{uuid4()}"
    release_revoke = threading.Event()

    def use_voice_and_hold() -> None:
        try:
            with Session(pg_engine) as session:
                _set_worker(session, f"t1f-rights-use-first-{uuid4()}")
                profile, voice, rights = require_usable_voice(
                    SqlAlchemyNarrationStore(session),
                    seed.voice_version_id,
                    novel_id=seed.novel_id,
                    at=NOW,
                )
                result["usable_ids"] = (profile.id, voice.id, rights.id)
                voice_usable.set()
                assert release_voice_use.wait(timeout=8)
                session.commit()
        except BaseException as error:
            result["voice_error"] = error
            voice_usable.set()

    revoke_inserted = threading.Event()
    use_thread = threading.Thread(target=use_voice_and_hold, daemon=True)
    revoke_thread = threading.Thread(
        target=_insert_revoke_and_hold,
        args=(pg_engine, seed),
        kwargs={
            "application_name": revoke_name,
            "inserted": revoke_inserted,
            # The revoker cannot reach its post-flush hold until use commits.
            "release": release_revoke,
            "result": result,
        },
        daemon=True,
    )
    use_thread.start()
    assert voice_usable.wait(timeout=8)
    revoke_thread.start()
    try:
        evidence = _wait_until_lock_wait(pg_engine, revoke_name)
        assert evidence.blocker_pids
    finally:
        release_voice_use.set()
    assert revoke_inserted.wait(timeout=8)
    release_revoke.set()
    _join_threads(use_thread, revoke_thread)

    assert "voice_error" not in result and "revoke_error" not in result
    assert result["usable_ids"] == (
        seed.profile_id,
        seed.voice_version_id,
        seed.rights_id,
    )
    with Session(pg_engine) as session:
        assert session.scalar(
            select(func.count()).select_from(VoiceRightsEvent).where(
                VoiceRightsEvent.rights_record_id == seed.rights_id,
                VoiceRightsEvent.event_type == "revoked",
            )
        ) == 1


def test_voice_revoke_first_blocks_then_rejects_publication_boundary(
    pg_engine: Engine,
) -> None:
    seed = _seed_voice(pg_engine)
    revoke_inserted = threading.Event()
    release_revoke = threading.Event()
    result: dict[str, object] = {}
    use_name = f"t1f-rights-use-after-revoke-{uuid4()}"

    revoke_thread = threading.Thread(
        target=_insert_revoke_and_hold,
        args=(pg_engine, seed),
        kwargs={
            "application_name": f"t1f-rights-revoke-first-{uuid4()}",
            "inserted": revoke_inserted,
            "release": release_revoke,
            "result": result,
        },
        daemon=True,
    )

    def use_voice_after_revoke() -> None:
        assert revoke_inserted.wait(timeout=8)
        try:
            with Session(pg_engine) as session:
                _set_worker(session, use_name)
                require_usable_voice(
                    SqlAlchemyNarrationStore(session),
                    seed.voice_version_id,
                    novel_id=seed.novel_id,
                    at=NOW,
                )
                session.commit()
        except BaseException as error:
            result["voice_error"] = error

    use_thread = threading.Thread(target=use_voice_after_revoke, daemon=True)
    revoke_thread.start()
    assert revoke_inserted.wait(timeout=8)
    use_thread.start()
    try:
        evidence = _wait_until_lock_wait(pg_engine, use_name)
        assert evidence.blocker_pids
    finally:
        release_revoke.set()
    _join_threads(revoke_thread, use_thread)

    assert "revoke_error" not in result
    assert isinstance(result.get("voice_error"), VoiceRightsUnavailable)
    assert "negative history" in str(result["voice_error"])
