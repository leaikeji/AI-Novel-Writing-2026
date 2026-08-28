"""PostgreSQL 18 red-team gate for T1 request source-manifest sealing.

This module is deliberately destructive, but only against two exact databases
inside the one-off loopback container selected by ``TTS_TEST_DATABASE_URL``.
It owns both databases for the duration of this module and drops them at the
end.  It must never be pointed at the normal TTS test port or a production URL.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import hashlib
import os
from pathlib import Path
from typing import Iterator
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from backend.models import NarrationRequest, NarrationRequestSource
from backend.narration.contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID
from backend.narration.requests import (
    CreateNarrationRequest,
    RequestSource,
    create_request,
    source_set_hash,
)
from backend.narration.services import IdempotencyConflict, SqlAlchemyNarrationStore


ROOT = Path(__file__).resolve().parents[2]
SERVICE_DATABASE = "ai_novel_world_2026_tts_test"
PREFLIGHT_DATABASE = "ai_novel_world_2026_tts_request_preflight"
CONTROL_DATABASE = "postgres"
EXPECTED_USERNAME = "tts_test"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
FORBIDDEN_SHARED_PORT = 15432
REVISION_0013 = "20260826_0013"
REVISION_0014 = "20260826_0014"
EMPTY_SOURCE_SET_HASH = (
    "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
)
SHA_A = "a" * 64


def _live_url() -> str:
    raw = os.environ.get("TTS_TEST_DATABASE_URL", "").strip()
    if not raw:
        pytest.skip(
            "TTS_TEST_DATABASE_URL is not configured; request-sealing PostgreSQL gate is pending"
        )
    parsed = make_url(raw)
    if not parsed.drivername.startswith("postgresql"):
        raise RuntimeError("request-sealing gate requires PostgreSQL")
    if (
        parsed.database != SERVICE_DATABASE
        or parsed.username != EXPECTED_USERNAME
        or parsed.host not in LOOPBACK_HOSTS
        or parsed.port in {None, FORBIDDEN_SHARED_PORT}
    ):
        raise RuntimeError(
            "request-sealing gate requires the exact disposable loopback database identity "
            "on a non-shared explicit port"
        )
    production = os.environ.get("AI_NOVEL_DATABASE_URL", "").strip()
    if production:
        prod = make_url(production)
        if (parsed.host, parsed.port, parsed.database) == (
            prod.host,
            prod.port,
            prod.database,
        ):
            raise RuntimeError("request-sealing database must differ from production")
    return raw


def _database_url(base_url: str, database: str) -> str:
    return make_url(base_url).set(database=database).render_as_string(hide_password=False)


def _alembic_config(url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    return config


@contextmanager
def _migration_database(url: str) -> Iterator[None]:
    old_url = os.environ.get("AI_NOVEL_DATABASE_URL")
    os.environ["AI_NOVEL_DATABASE_URL"] = url
    try:
        yield
    finally:
        if old_url is None:
            os.environ.pop("AI_NOVEL_DATABASE_URL", None)
        else:
            os.environ["AI_NOVEL_DATABASE_URL"] = old_url


def _upgrade(url: str, revision: str) -> None:
    with _migration_database(url):
        command.upgrade(_alembic_config(url), revision)


def _downgrade(url: str, revision: str) -> None:
    with _migration_database(url):
        command.downgrade(_alembic_config(url), revision)


def _reset_exact_databases(control_engine: Engine, names: tuple[str, ...]) -> None:
    allowed = {SERVICE_DATABASE, PREFLIGHT_DATABASE}
    if not names or not set(names) <= allowed:
        raise RuntimeError("refusing to reset an unowned database")
    with control_engine.connect() as connection:
        for name in names:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname=:database AND pid<>pg_backend_pid()"
                ),
                {"database": name},
            )
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
            connection.execute(text(f'CREATE DATABASE "{name}" OWNER "{EXPECTED_USERNAME}"'))


def _drop_exact_databases(control_engine: Engine, names: tuple[str, ...]) -> None:
    allowed = {SERVICE_DATABASE, PREFLIGHT_DATABASE}
    if not names or not set(names) <= allowed:
        raise RuntimeError("refusing to drop an unowned database")
    with control_engine.connect() as connection:
        for name in names:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname=:database AND pid<>pg_backend_pid()"
                ),
                {"database": name},
            )
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))


def _seed_novel_and_sources(
    connection,
    *,
    source_count: int,
    novel_id: UUID | None = None,
) -> tuple[UUID, tuple[RequestSource, ...]]:
    novel_id = novel_id or uuid4()
    connection.execute(
        text("INSERT INTO novels (id,title,description,version) VALUES (:id,:title,'',1)"),
        {"id": novel_id, "title": f"request-seal-{novel_id}"},
    )
    sources: list[RequestSource] = []
    for position in range(source_count):
        document_id = uuid4()
        revision_id = uuid4()
        content = f"request sealing source {novel_id} {position}"
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        connection.execute(
            text(
                "INSERT INTO documents "
                "(id,novel_id,kind,title,position,status,version) "
                "VALUES (:id,:novel,'chapter',:title,:position,'draft',1)"
            ),
            {
                "id": document_id,
                "novel": novel_id,
                "title": f"chapter-{position}",
                "position": position + 1,
            },
        )
        connection.execute(
            text(
                "INSERT INTO document_revisions "
                "(id,document_id,revision_number,content_markdown,content_text,"
                "content_hash,source) "
                "VALUES (:id,:document,1,:content,:content,:hash,'manual')"
            ),
            {
                "id": revision_id,
                "document": document_id,
                "content": content,
                "hash": content_hash,
            },
        )
        sources.append(
            RequestSource(
                document_id=document_id,
                revision_id=revision_id,
                content_hash=content_hash,
                position=position,
            )
        )
    return novel_id, tuple(sources)


def _insert_old_0013_request(engine: Engine) -> UUID:
    request_id = uuid4()
    with engine.begin() as connection:
        novel_id, sources = _seed_novel_and_sources(connection, source_count=1)
        source = sources[0]
        connection.execute(
            text(
                """
                INSERT INTO narration_requests
                  (id,owner_id,workspace_id,novel_id,document_id,intent,request_hash,
                   idempotency_key,source_revision_id,source_content_hash,
                   settings_fingerprint,force_review,effective_policy,state,version)
                VALUES
                  (:id,:owner,:workspace,:novel,:document,'analyze_only',:request_hash,
                   :key,:revision,:content_hash,:settings,false,'blockers_only','created',1)
                """
            ),
            {
                "id": request_id,
                "owner": LOCAL_OWNER_ID,
                "workspace": LOCAL_WORKSPACE_ID,
                "novel": novel_id,
                "document": source.document_id,
                "request_hash": SHA_A,
                "key": f"preflight-{uuid4()}",
                "revision": source.revision_id,
                "content_hash": source.content_hash,
                "settings": SHA_A,
            },
        )
    return request_id


def _request_schema_snapshot(engine: Engine) -> tuple[object, ...]:
    with engine.connect() as connection:
        return (
            connection.scalar(text("SELECT version_num FROM alembic_version")),
            tuple(
                connection.execute(
                    text(
                        "SELECT table_name,column_name,ordinal_position,data_type,is_nullable "
                        "FROM information_schema.columns "
                        "WHERE table_schema='public' "
                        "AND table_name IN ('narration_requests','narration_request_sources') "
                        "ORDER BY table_name,ordinal_position"
                    )
                ).all()
            ),
            tuple(
                connection.execute(
                    text(
                        "SELECT c.conname,pg_get_constraintdef(c.oid,true) "
                        "FROM pg_constraint c JOIN pg_class r ON r.oid=c.conrelid "
                        "WHERE r.relname IN ('narration_requests','narration_request_sources') "
                        "ORDER BY c.conname"
                    )
                ).all()
            ),
            tuple(
                connection.execute(
                    text(
                        "SELECT r.relname,t.tgname,pg_get_triggerdef(t.oid,true) "
                        "FROM pg_trigger t JOIN pg_class r ON r.oid=t.tgrelid "
                        "WHERE NOT t.tgisinternal "
                        "AND r.relname IN ('narration_requests','narration_request_sources') "
                        "ORDER BY r.relname,t.tgname"
                    )
                ).all()
            ),
            connection.scalar(
                text(
                    "SELECT COALESCE(jsonb_agg(to_jsonb(r) ORDER BY r.id)::text,'[]') "
                    "FROM narration_requests r"
                )
            ),
            connection.scalar(text("SELECT count(*) FROM narration_request_sources")),
        )


@pytest.fixture(scope="module")
def request_sealing_databases() -> dict[str, object]:
    base_url = _live_url()
    service_url = _database_url(base_url, SERVICE_DATABASE)
    preflight_url = _database_url(base_url, PREFLIGHT_DATABASE)
    control_url = _database_url(base_url, CONTROL_DATABASE)
    control_engine = create_engine(
        control_url,
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
    )
    service_engine: Engine | None = None
    preflight_engine: Engine | None = None
    owned_databases = (PREFLIGHT_DATABASE, SERVICE_DATABASE)
    try:
        with control_engine.connect() as connection:
            version = connection.scalar(text("SHOW server_version"))
            assert isinstance(version, str) and version.startswith("18.")
        _reset_exact_databases(control_engine, owned_databases)

        _upgrade(preflight_url, REVISION_0013)
        preflight_engine = create_engine(preflight_url, pool_pre_ping=True)
        request_id = _insert_old_0013_request(preflight_engine)
        before = _request_schema_snapshot(preflight_engine)
        try:
            _upgrade(preflight_url, REVISION_0014)
        except DBAPIError as error:
            preflight_error = str(error)
        else:
            raise AssertionError("0014 upgrade accepted an existing narration request")
        after = _request_schema_snapshot(preflight_engine)
        assert before == after
        assert "existing requests require an audited source-manifest fix-forward" in preflight_error
        assert str(request_id) in str(before[-2])

        _upgrade(service_url, REVISION_0013)
        service_engine = create_engine(service_url, pool_pre_ping=True)
        with service_engine.connect() as connection:
            columns_at_0013 = {
                item["name"] for item in inspect(connection).get_columns("narration_requests")
            }
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == REVISION_0013
            )
            assert not {
                "source_count",
                "source_set_hash",
                "sources_sealed_at",
            } & columns_at_0013
        _upgrade(service_url, REVISION_0014)
        with service_engine.connect() as connection:
            columns_first_0014 = {
                item["name"] for item in inspect(connection).get_columns("narration_requests")
            }
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == REVISION_0014
            )
            assert {
                "source_count",
                "source_set_hash",
                "sources_sealed_at",
            } <= columns_first_0014
        _downgrade(service_url, REVISION_0013)
        with service_engine.connect() as connection:
            columns_second_0013 = {
                item["name"] for item in inspect(connection).get_columns("narration_requests")
            }
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == REVISION_0013
            )
            assert not {
                "source_count",
                "source_set_hash",
                "sources_sealed_at",
            } & columns_second_0013
        _upgrade(service_url, REVISION_0014)
        with service_engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == REVISION_0014
            )
            assert connection.scalar(text("SELECT count(*) FROM narration_requests")) == 0

        yield {
            "engine": service_engine,
            "preflight_unchanged": before == after,
            "preflight_error": preflight_error,
            "cycle": (REVISION_0013, REVISION_0014, REVISION_0013, REVISION_0014),
        }
    finally:
        if service_engine is not None:
            service_engine.dispose()
        if preflight_engine is not None:
            preflight_engine.dispose()
        _drop_exact_databases(control_engine, owned_databases)
        control_engine.dispose()


def _engine(context: dict[str, object]) -> Engine:
    engine = context["engine"]
    assert isinstance(engine, Engine)
    return engine


def _raw_multi_request(
    connection,
    *,
    novel_id: UUID,
    source_count: int,
) -> UUID:
    request_id = uuid4()
    connection.execute(
        text(
            """
            INSERT INTO narration_requests
              (id,owner_id,workspace_id,novel_id,document_id,intent,request_hash,
               idempotency_key,source_revision_id,source_content_hash,source_count,
               source_set_hash,sources_sealed_at,settings_fingerprint,force_review,
               effective_policy,state,version)
            VALUES
              (:id,:owner,:workspace,:novel,NULL,'analyze_only',:request_hash,
               :key,NULL,NULL,:source_count,:source_hash,NULL,:settings,false,
               'blockers_only','created',1)
            """
        ),
        {
            "id": request_id,
            "owner": LOCAL_OWNER_ID,
            "workspace": LOCAL_WORKSPACE_ID,
            "novel": novel_id,
            "request_hash": hashlib.sha256(str(request_id).encode()).hexdigest(),
            "key": f"raw-multi-{request_id}",
            "source_count": source_count,
            "source_hash": SHA_A,
            "settings": SHA_A,
        },
    )
    return request_id


def _raw_source(connection, *, request_id: UUID, novel_id: UUID, source: RequestSource) -> None:
    connection.execute(
        text(
            """
            INSERT INTO narration_request_sources
              (id,request_id,novel_id,document_id,revision_id,content_hash,position)
            VALUES (:id,:request,:novel,:document,:revision,:content_hash,:position)
            """
        ),
        {
            "id": uuid4(),
            "request": request_id,
            "novel": novel_id,
            "document": source.document_id,
            "revision": source.revision_id,
            "content_hash": source.content_hash,
            "position": source.position,
        },
    )


def _service_command(
    *,
    novel_id: UUID,
    sources: tuple[RequestSource, ...],
    intent: str,
    key: str,
) -> CreateNarrationRequest:
    if intent == "create":
        source = sources[0]
        return CreateNarrationRequest(
            novel_id=novel_id,
            document_id=source.document_id,
            source_revision_id=source.revision_id,
            source_content_hash=source.content_hash,
            intent="create",
            idempotency_key=key,
            settings_fingerprint=SHA_A,
            explicit_generation_intent_at=datetime.now(UTC),
            explicit_generation_actor="request-sealing-redteam",
        )
    assert intent == "analyze_only"
    return CreateNarrationRequest(
        novel_id=novel_id,
        intent="analyze_only",
        idempotency_key=key,
        settings_fingerprint=SHA_A,
        sources=sources,
    )


def test_0014_preflight_is_atomic_and_empty_cycle_is_reversible(
    request_sealing_databases: dict[str, object],
) -> None:
    assert request_sealing_databases["preflight_unchanged"] is True
    assert "existing requests require an audited source-manifest fix-forward" in str(
        request_sealing_databases["preflight_error"]
    )
    assert request_sealing_databases["cycle"] == (
        REVISION_0013,
        REVISION_0014,
        REVISION_0013,
        REVISION_0014,
    )


def test_0014_catalog_freezes_checks_and_deferred_closure_triggers(
    request_sealing_databases: dict[str, object],
) -> None:
    engine = _engine(request_sealing_databases)
    with engine.connect() as connection:
        checks = {
            row["conname"]: row["definition"]
            for row in connection.execute(
                text(
                    "SELECT c.conname,pg_get_constraintdef(c.oid,true) AS definition "
                    "FROM pg_constraint c JOIN pg_class r ON r.oid=c.conrelid "
                    "WHERE r.relname='narration_requests' AND c.contype='c'"
                )
            ).mappings()
        }
        assert "source_count >= 0" in checks["ck_narration_request_source_count"]
        assert "source_set_hash" in checks["ck_narration_request_source_set_hash"]
        assert EMPTY_SOURCE_SET_HASH in checks["ck_narration_request_source_manifest_shape"]
        triggers = {
            row["tgname"]: row
            for row in connection.execute(
                text(
                    "SELECT t.tgname,r.relname,t.tgdeferrable,t.tginitdeferred,"
                    "pg_get_triggerdef(t.oid,true) AS definition "
                    "FROM pg_trigger t JOIN pg_class r ON r.oid=t.tgrelid "
                    "WHERE NOT t.tgisinternal AND "
                    "t.tgname IN ('trg_narration_request_sources_scope',"
                    "'trg_t1_request_source_closure_parent',"
                    "'trg_t1_request_source_closure_child')"
                )
            ).mappings()
        }
        assert set(triggers) == {
            "trg_narration_request_sources_scope",
            "trg_t1_request_source_closure_parent",
            "trg_t1_request_source_closure_child",
        }
        scope = triggers["trg_narration_request_sources_scope"]
        assert scope["relname"] == "narration_request_sources"
        assert scope["tgdeferrable"] is False and scope["tginitdeferred"] is False
        for operation in ("INSERT", "UPDATE", "DELETE"):
            assert operation in scope["definition"]
        for name, table in (
            ("trg_t1_request_source_closure_parent", "narration_requests"),
            ("trg_t1_request_source_closure_child", "narration_request_sources"),
        ):
            trigger = triggers[name]
            assert trigger["relname"] == table
            assert trigger["tgdeferrable"] is True
            assert trigger["tginitdeferred"] is True
        guard = connection.scalar(
            text(
                "SELECT pg_get_functiondef('narration_guard_request'::regproc)"
            )
        )
        assert "NEW.sources_sealed_at := clock_timestamp()" in guard
        assert "request source seal requires the complete reserved source set" in guard


@pytest.mark.parametrize(
    ("case", "source_count", "positions"),
    (
        ("unsealed", 1, ()),
        ("short", 2, (0,)),
        ("noncontiguous", 3, (0, 2)),
    ),
)
def test_unsealed_short_and_noncontiguous_manifests_cannot_commit(
    request_sealing_databases: dict[str, object],
    case: str,
    source_count: int,
    positions: tuple[int, ...],
) -> None:
    engine = _engine(request_sealing_databases)
    connection = engine.connect()
    transaction = connection.begin()
    try:
        novel_id, sources = _seed_novel_and_sources(
            connection,
            source_count=max(source_count, 1),
        )
        request_id = _raw_multi_request(
            connection,
            novel_id=novel_id,
            source_count=source_count,
        )
        for position in positions:
            _raw_source(
                connection,
                request_id=request_id,
                novel_id=novel_id,
                source=sources[position],
            )
        if case != "unsealed":
            savepoint = connection.begin_nested()
            with pytest.raises(DBAPIError, match="complete reserved source set"):
                connection.execute(
                    text(
                        "UPDATE narration_requests SET sources_sealed_at=clock_timestamp() "
                        "WHERE id=:id"
                    ),
                    {"id": request_id},
                )
                savepoint.commit()
            if savepoint.is_active:
                savepoint.rollback()
        with pytest.raises(DBAPIError, match="must be sealed before commit"):
            transaction.commit()
    finally:
        if transaction.is_active:
            transaction.rollback()
        connection.close()


def test_service_direct_and_multi_creation_use_exact_db_seals_and_replay(
    request_sealing_databases: dict[str, object],
) -> None:
    engine = _engine(request_sealing_databases)
    with Session(engine, expire_on_commit=False) as session:
        direct_novel, direct_sources = _seed_novel_and_sources(
            session.connection(),
            source_count=1,
        )
        direct_command = _service_command(
            novel_id=direct_novel,
            sources=direct_sources,
            intent="create",
            key=f"service-direct-{uuid4()}",
        )
        direct_before = session.scalar(select(func.clock_timestamp()))
        direct = create_request(SqlAlchemyNarrationStore(session), direct_command)
        direct_after = session.scalar(select(func.clock_timestamp()))
        assert direct.sources_sealed_at is not None
        assert direct_before <= direct.sources_sealed_at <= direct_after
        assert direct.source_count == 0
        assert direct.source_set_hash == EMPTY_SOURCE_SET_HASH
        assert session.scalar(
            select(func.count()).select_from(NarrationRequestSource).where(
                NarrationRequestSource.request_id == direct.id
            )
        ) == 0
        replayed_direct = create_request(SqlAlchemyNarrationStore(session), direct_command)
        assert replayed_direct.id == direct.id

        multi_novel, multi_sources = _seed_novel_and_sources(
            session.connection(),
            source_count=2,
        )
        multi_command = _service_command(
            novel_id=multi_novel,
            sources=multi_sources,
            intent="analyze_only",
            key=f"service-multi-{uuid4()}",
        )
        multi_before = session.scalar(select(func.clock_timestamp()))
        multi = create_request(SqlAlchemyNarrationStore(session), multi_command)
        multi_after = session.scalar(select(func.clock_timestamp()))
        assert multi.sources_sealed_at is not None
        assert multi_before <= multi.sources_sealed_at <= multi_after
        assert multi.source_count == len(multi_sources) == 2
        assert multi.source_set_hash == source_set_hash(multi_sources)
        stored_sources = tuple(
            RequestSource(row.document_id, row.revision_id, row.content_hash, row.position)
            for row in session.scalars(
                select(NarrationRequestSource)
                .where(NarrationRequestSource.request_id == multi.id)
                .order_by(NarrationRequestSource.position)
            )
        )
        assert stored_sources == multi_sources
        replayed_multi = create_request(SqlAlchemyNarrationStore(session), multi_command)
        assert replayed_multi.id == multi.id
        assert session.scalar(
            select(func.count()).select_from(NarrationRequest).where(
                NarrationRequest.id.in_((direct.id, multi.id))
            )
        ) == 2
        session.commit()


def test_sealed_child_insert_update_delete_are_rejected(
    request_sealing_databases: dict[str, object],
) -> None:
    engine = _engine(request_sealing_databases)
    with Session(engine, expire_on_commit=False) as session:
        novel_id, sources = _seed_novel_and_sources(session.connection(), source_count=2)
        command_value = _service_command(
            novel_id=novel_id,
            sources=sources,
            intent="analyze_only",
            key=f"sealed-child-{uuid4()}",
        )
        request = create_request(SqlAlchemyNarrationStore(session), command_value)
        request_id = request.id
        session.commit()
        rows = session.scalars(
            select(NarrationRequestSource)
            .where(NarrationRequestSource.request_id == request_id)
            .order_by(NarrationRequestSource.position)
        ).all()
        assert len(rows) == 2
        statements = (
            (
                "INSERT INTO narration_request_sources "
                "(id,request_id,novel_id,document_id,revision_id,content_hash,position) "
                "VALUES (:id,:request,:novel,:document,:revision,:hash,2)",
                {
                    "id": uuid4(),
                    "request": request_id,
                    "novel": novel_id,
                    "document": sources[0].document_id,
                    "revision": sources[0].revision_id,
                    "hash": sources[0].content_hash,
                },
            ),
            (
                "UPDATE narration_request_sources SET position=position WHERE id=:id",
                {"id": rows[0].id},
            ),
            (
                "DELETE FROM narration_request_sources WHERE id=:id",
                {"id": rows[0].id},
            ),
        )
        for statement, parameters in statements:
            savepoint = session.begin_nested()
            # The older append-only guard and the 0014 sealed guard overlap for
            # UPDATE/DELETE.  Trigger name order decides which fail-closed
            # message is observed; either rejection preserves the invariant.
            with pytest.raises(
                DBAPIError,
                match="sealed|unsealed created|immutable narration row",
            ):
                session.execute(text(statement), parameters)
                savepoint.commit()
            if savepoint.is_active:
                savepoint.rollback()
        session.rollback()
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT count(*) FROM narration_request_sources WHERE request_id=:id"),
            {"id": request_id},
        ) == 2


def test_corrupt_replay_conflicts_without_poisoning_outer_transaction(
    request_sealing_databases: dict[str, object],
) -> None:
    engine = _engine(request_sealing_databases)
    with Session(engine, expire_on_commit=False) as session:
        novel_id, sources = _seed_novel_and_sources(session.connection(), source_count=2)
        command_value = _service_command(
            novel_id=novel_id,
            sources=sources,
            intent="analyze_only",
            key=f"corrupt-replay-{uuid4()}",
        )
        request = create_request(SqlAlchemyNarrationStore(session), command_value)
        request_id = request.id
        expected_hash = request.source_set_hash
        session.commit()

    with Session(engine, expire_on_commit=False) as session:
        session.execute(text("ALTER TABLE narration_requests DISABLE TRIGGER USER"))
        session.execute(
            text("UPDATE narration_requests SET source_set_hash=:hash WHERE id=:id"),
            {"id": request_id, "hash": "f" * 64},
        )
        session.execute(text("ALTER TABLE narration_requests ENABLE TRIGGER USER"))
        with pytest.raises(IdempotencyConflict, match="manifest hash drifted"):
            create_request(SqlAlchemyNarrationStore(session), command_value)
        assert session.in_transaction()
        assert session.scalar(text("SELECT 40 + 2")) == 42
        assert session.scalar(
            text("SELECT source_set_hash FROM narration_requests WHERE id=:id"),
            {"id": request_id},
        ) == "f" * 64
        session.rollback()

    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT source_set_hash FROM narration_requests WHERE id=:id"),
            {"id": request_id},
        ) == expected_hash
        enabled = connection.scalar(
            text(
                "SELECT bool_and(tgenabled='O') FROM pg_trigger t "
                "JOIN pg_class r ON r.oid=t.tgrelid "
                "WHERE r.relname='narration_requests' AND NOT t.tgisinternal"
            )
        )
        assert enabled is True
