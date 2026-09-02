from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
from time import perf_counter
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, insert, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateIndex

from backend.models import Novel, StoryFact
from backend.story_ledger.query import LedgerQueryFilters, raw_page_ids_statement


ROOT = Path(__file__).resolve().parents[2]
REVISION = "20260902_0037"
DOWN_REVISION = "20260901_0036"
HEAD_REVISION = "20260902_0039"
SINGLE_CONTRACT_REVISION = "20260902_0038"
INDEX_NAME = "ix_story_facts_novel_created_v2"
MIGRATION = (
    ROOT
    / "backend/migrations/versions/20260902_0037_story_ledger_page_index.py"
)
EXPECTED_DATABASE = "ai_novel_world_2026_l51_migration_test"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _script_directory() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))


def _model_index():
    return next(
        index for index in StoryFact.__table__.indexes if index.name == INDEX_NAME
    )


def test_story_ledger_page_index_precedes_the_single_contract_head() -> None:
    scripts = _script_directory()
    assert scripts.get_heads() == [HEAD_REVISION]
    assert scripts.get_revision(HEAD_REVISION).down_revision == SINGLE_CONTRACT_REVISION
    assert scripts.get_revision(SINGLE_CONTRACT_REVISION).down_revision == REVISION
    assert scripts.get_revision(REVISION).down_revision == DOWN_REVISION


def test_story_ledger_page_index_model_contract_matches_query_order() -> None:
    index = _model_index()
    assert index.unique is False
    assert [str(expression) for expression in index.expressions] == [
        "story_facts.novel_id",
        "created_at DESC",
        "id DESC",
    ]
    assert str(index.dialect_options["postgresql"]["where"]) == (
        "schema_version = 'story-fact/2'"
    )
    assert str(CreateIndex(index).compile(dialect=postgresql.dialect())) == (
        "CREATE INDEX ix_story_facts_novel_created_v2 ON story_facts "
        "(novel_id, created_at DESC, id DESC) "
        "WHERE schema_version = 'story-fact/2'"
    )


def test_story_ledger_page_index_migration_is_narrow_and_io_free() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    for forbidden in (
        "from backend.models",
        "create_engine",
        "requests.",
        "subprocess",
        "op.create_table",
        "op.drop_table",
        "op.add_column",
        "op.drop_column",
        "op.execute",
    ):
        assert forbidden not in source
    for marker in (
        'revision = "20260902_0037"',
        'down_revision = "20260901_0036"',
        'INDEX_NAME = "ix_story_facts_novel_created_v2"',
        'sa.text("created_at DESC")',
        'sa.text("id DESC")',
        'sa.text("schema_version = \'story-fact/2\'")',
        "op.create_index(",
        "op.drop_index(INDEX_NAME, table_name=\"story_facts\")",
    ):
        assert marker in source


def _live_url() -> str:
    raw = os.environ.get("AI_NOVEL_MIGRATION_TEST_DATABASE_URL", "").strip()
    if not raw:
        pytest.skip(
            "AI_NOVEL_MIGRATION_TEST_DATABASE_URL is not configured; "
            "live Story Ledger migration gate is pending"
        )
    parsed = make_url(raw)
    if (
        parsed.get_backend_name() != "postgresql"
        or parsed.database != EXPECTED_DATABASE
        or parsed.host not in LOOPBACK_HOSTS
    ):
        raise RuntimeError(
            "Story Ledger migration gate requires the exact loopback PostgreSQL "
            f"database {EXPECTED_DATABASE}"
        )
    production = os.environ.get("AI_NOVEL_DATABASE_URL", "").strip()
    if production:
        production_url = make_url(production)
        if (parsed.host, parsed.port, parsed.database) == (
            production_url.host,
            production_url.port,
            production_url.database,
        ):
            raise RuntimeError(
                "Story Ledger migration database must differ from "
                "AI_NOVEL_DATABASE_URL"
            )
    return raw


def _alembic_config(url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def _seed_facts(engine: Engine, *, size: int, label: str) -> tuple[UUID, float]:
    novel_id = uuid4()
    base_time = datetime(2026, 9, 2, tzinfo=UTC)
    rows = [
        {
            "id": uuid4(),
            "novel_id": novel_id,
            "fact_type": "general_fact",
            "subject": f"{label}-entity-{index % 200}",
            "predicate": f"slot-{index % 200}",
            "object_text": f"value-{index}",
            "details": {"schema_version": "general-fact/1", "value": index},
            "schema_version": "story-fact/2",
            "dimension": "fact",
            "event_kind": "note",
            "story_sequence": index,
            "status": "active",
            "created_at": base_time + timedelta(microseconds=index),
        }
        for index in range(size)
    ]
    started = perf_counter()
    with Session(engine) as session:
        session.add(Novel(id=novel_id, title=f"L51 migration {label}"))
        session.flush()
        for offset in range(0, size, 1_000):
            session.execute(
                insert(StoryFact.__table__), rows[offset : offset + 1_000]
            )
        session.commit()
    return novel_id, (perf_counter() - started) * 1_000


def _page_plan(engine: Engine, novel_id: UUID) -> dict[str, object]:
    statement = raw_page_ids_statement(
        novel_id, LedgerQueryFilters(), limit=20
    ).compile(dialect=engine.dialect, compile_kwargs={"literal_binds": True})
    with engine.connect() as connection:
        payload = connection.execute(
            text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + str(statement))
        ).scalar_one()[0]
    return payload["Plan"]


def _scan_evidence(plan: dict[str, object]) -> list[dict[str, object]]:
    scans: list[dict[str, object]] = []

    def visit(node: dict[str, object]) -> None:
        if "Scan" in str(node.get("Node Type", "")):
            actual_rows = int(node.get("Actual Rows", 0))
            actual_loops = int(node.get("Actual Loops", 0))
            scans.append(
                {
                    "node_type": node.get("Node Type"),
                    "relation": node.get("Relation Name"),
                    "index": node.get("Index Name"),
                    "visited_rows": actual_rows * actual_loops,
                    "rows_removed_by_filter": int(
                        node.get("Rows Removed by Filter", 0)
                    ),
                }
            )
        for child in node.get("Plans", ()):
            visit(child)

    visit(plan)
    return scans


def _index_definition(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE schemaname = current_schema() "
                "AND tablename = 'story_facts' AND indexname = :index_name"
            ),
            {"index_name": INDEX_NAME},
        ).scalar_one_or_none()


def test_live_story_ledger_index_upgrade_downgrade_and_query_plan() -> None:
    """Run only in a generated schema inside the exact disposable database."""

    url = _live_url()
    base = create_engine(url, pool_pre_ping=True)
    schema = f"l51_migration_{uuid4().hex[:12]}"
    with base.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(
            text(
                f'CREATE TABLE "{schema}".alembic_version '
                "(version_num VARCHAR(32) PRIMARY KEY)"
            )
        )
    scoped_url = make_url(url).update_query_dict(
        {"options": f"-csearch_path={schema},public"}
    ).render_as_string(hide_password=False)
    escaped_scoped_url = scoped_url.replace("%", "%%")
    config = _alembic_config(escaped_scoped_url)
    old_database_url = os.environ.get("AI_NOVEL_DATABASE_URL")
    os.environ["AI_NOVEL_DATABASE_URL"] = escaped_scoped_url
    engine = create_engine(scoped_url, pool_pre_ping=True)
    evidence: dict[str, object] = {
        "schema_version": "story-ledger-index-migration/1",
        "database": EXPECTED_DATABASE,
        "row_count": 2_000,
    }
    try:
        command.upgrade(config, DOWN_REVISION)
        assert _index_definition(engine) is None

        novel_without_index, without_index_write_ms = _seed_facts(
            engine, size=2_000, label="without-index"
        )
        with engine.begin() as connection:
            connection.execute(text("ANALYZE story_facts"))
        without_index_scans = _scan_evidence(
            _page_plan(engine, novel_without_index)
        )
        assert max(scan["visited_rows"] for scan in without_index_scans) > 64

        command.upgrade(config, REVISION)
        definition = _index_definition(engine)
        assert definition is not None
        assert "(novel_id, created_at DESC, id DESC)" in definition
        assert "schema_version" in definition and "story-fact/2" in definition
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM story_facts")) == 2_000

        novel_with_index, with_index_write_ms = _seed_facts(
            engine, size=2_000, label="with-index"
        )
        with engine.begin() as connection:
            connection.execute(text("ANALYZE story_facts"))
        with_index_scans = _scan_evidence(_page_plan(engine, novel_with_index))
        assert any(scan["index"] == INDEX_NAME for scan in with_index_scans)
        formal_scan = next(
            scan for scan in with_index_scans if scan["index"] == INDEX_NAME
        )
        assert formal_scan["visited_rows"] <= 64

        command.downgrade(config, DOWN_REVISION)
        assert _index_definition(engine) is None
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM story_facts")) == 4_000

        command.upgrade(config, REVISION)
        assert _index_definition(engine) is not None
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM story_facts")) == 4_000

        evidence.update(
            {
                "without_index": {
                    "write_2000_ms": round(without_index_write_ms, 3),
                    "scan_nodes": without_index_scans,
                },
                "with_index": {
                    "write_2000_ms": round(with_index_write_ms, 3),
                    "scan_nodes": with_index_scans,
                    "definition": definition,
                },
                "round_trip": {
                    "upgrade": REVISION,
                    "downgrade": DOWN_REVISION,
                    "data_rows_preserved": 4_000,
                },
            }
        )
        print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    finally:
        engine.dispose()
        if old_database_url is None:
            os.environ.pop("AI_NOVEL_DATABASE_URL", None)
        else:
            os.environ["AI_NOVEL_DATABASE_URL"] = old_database_url
        with base.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        base.dispose()
