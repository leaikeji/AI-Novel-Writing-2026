"""Reproducible Plan 51 Story Ledger PostgreSQL benchmark.

Run only against an explicitly named ``*_test`` database::

    PYTHONPATH=. AI_NOVEL_TEST_DATABASE_URL=postgresql+psycopg://.../ledger_test \
      .venv/bin/python tests/story_ledger/benchmark_postgres.py

The script requires the approved production page index, creates synthetic
novels, prints JSON evidence, and deletes every synthetic novel before exiting.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from math import ceil
import os
import re
from statistics import median
from time import perf_counter
import tracemalloc
from uuid import UUID, uuid4

from sqlalchemy import create_engine, delete, event, insert, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

from backend.creative_data_models import StoryTimeline
from backend.models import Novel, StoryFact
from backend.story_ledger.query import (
    LedgerQueryFilters,
    TimelineQueryScope,
    fact_statement,
    raw_page_ids_statement,
    summary_statement,
)
from backend.story_ledger.service import StoryLedgerService


SIZES = (500, 2_000, 10_000)
FORMAL_INDEX = "ix_story_facts_novel_created_v2"


def _engine() -> Engine:
    raw = os.environ.get("AI_NOVEL_TEST_DATABASE_URL", "").strip()
    if not raw:
        raise RuntimeError("AI_NOVEL_TEST_DATABASE_URL is required")
    parsed = make_url(raw)
    if parsed.get_backend_name() != "postgresql" or not re.fullmatch(
        r"[A-Za-z0-9_]*_test", parsed.database or ""
    ):
        raise RuntimeError("benchmark requires an explicit PostgreSQL *_test database")
    production = os.environ.get("AI_NOVEL_DATABASE_URL", "").strip()
    if production and make_url(production) == parsed:
        raise RuntimeError("benchmark database must not equal AI_NOVEL_DATABASE_URL")
    return create_engine(raw, pool_pre_ping=True)


def _seed(engine: Engine, size: int) -> tuple[UUID, UUID, UUID, float]:
    novel_id = uuid4()
    timeline_id = uuid4()
    first_fact_id = uuid4()
    base_time = datetime(2026, 9, 2, tzinfo=UTC)
    rows = []
    for index in range(size):
        fact_id = first_fact_id if index == 0 else uuid4()
        rows.append(
            {
                "id": fact_id,
                "novel_id": novel_id,
                "fact_type": "general_fact",
                "subject": f"实体-{index % 200}",
                "predicate": f"槽位-{index % 200}",
                "object_text": f"值-{index}",
                "details": {
                    "schema_version": "general-fact/1",
                    "value": f"值-{index}",
                },
                "schema_version": "story-fact/2",
                "timeline_id": timeline_id,
                "dimension": "fact",
                "event_kind": "note",
                "story_sequence": index,
                "status": "active",
                "created_at": base_time + timedelta(microseconds=index),
            }
        )
    started = perf_counter()
    with Session(engine) as session:
        session.add(Novel(id=novel_id, title=f"L51 benchmark {size}"))
        session.flush()
        session.add(
            StoryTimeline(
                id=timeline_id,
                novel_id=novel_id,
                timeline_key="main",
                name="主时间线",
                normalized_name="主时间线",
                timeline_kind="main",
                is_primary=True,
                lifecycle_state="active",
                position=0,
                version=1,
            )
        )
        session.flush()
        for offset in range(0, len(rows), 1_000):
            session.execute(insert(StoryFact.__table__), rows[offset : offset + 1_000])
        session.commit()
    return novel_id, timeline_id, first_fact_id, (perf_counter() - started) * 1_000


def _formal_index_definition(engine: Engine) -> str:
    with engine.connect() as connection:
        definition = connection.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE schemaname = current_schema() "
                "AND tablename = 'story_facts' AND indexname = :index_name"
            ),
            {"index_name": FORMAL_INDEX},
        ).scalar_one_or_none()
    if definition is None:
        raise RuntimeError(
            f"required Story Ledger index is missing: {FORMAL_INDEX}"
        )
    return str(definition)


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, ceil(len(ordered) * fraction) - 1))
    return ordered[index]


def _measure_call(engine: Engine, operation) -> dict[str, object]:
    statement_count = 0
    fact_load_count = 0

    def count_statement(*_args, **_kwargs) -> None:
        nonlocal statement_count
        statement_count += 1

    def count_fact_load(*_args, **_kwargs) -> None:
        nonlocal fact_load_count
        fact_load_count += 1

    event.listen(engine, "before_cursor_execute", count_statement)
    event.listen(StoryFact, "load", count_fact_load)
    tracemalloc.start()
    started = perf_counter()
    try:
        result = operation()
        elapsed_ms = (perf_counter() - started) * 1_000
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
        event.remove(engine, "before_cursor_execute", count_statement)
        event.remove(StoryFact, "load", count_fact_load)
    if hasattr(result, "items"):
        returned = len(result.items)
    elif hasattr(result, "total"):
        returned = int(result.total)
    elif hasattr(result, "item"):
        returned = 1
    else:
        returned = 0
    return {
        "elapsed_ms": round(elapsed_ms, 3),
        "peak_mib": round(peak / 1024 / 1024, 3),
        "sql_count": statement_count,
        "story_fact_orm_load": fact_load_count,
        "returned": returned,
    }


def _timings(operation, samples: int) -> dict[str, float]:
    values = []
    for _ in range(samples):
        started = perf_counter()
        operation()
        values.append((perf_counter() - started) * 1_000)
    return {
        "p50_ms": round(median(values), 3),
        "p95_ms": round(_percentile(values, 0.95), 3),
    }


def _scan_nodes(plan: dict[str, object]) -> list[dict[str, object]]:
    found = []

    def visit(node: dict[str, object]) -> None:
        node_type = str(node.get("Node Type", ""))
        if "Scan" in node_type:
            found.append(
                {
                    "node_type": node_type,
                    "relation": node.get("Relation Name"),
                    "index": node.get("Index Name"),
                    "actual_rows": node.get("Actual Rows"),
                    "actual_loops": node.get("Actual Loops"),
                    "rows_removed_by_filter": node.get("Rows Removed by Filter", 0),
                    "shared_hit_blocks": node.get("Shared Hit Blocks", 0),
                    "shared_read_blocks": node.get("Shared Read Blocks", 0),
                }
            )
        for child in node.get("Plans", ()):
            visit(child)

    visit(plan)
    return found


def _explain_statement(engine: Engine, statement) -> dict[str, object]:
    compiled = statement.compile(
        dialect=engine.dialect, compile_kwargs={"literal_binds": True}
    )
    with engine.connect() as connection:
        payload = connection.execute(
            text(
                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + str(compiled)
            )
        ).scalar_one()[0]
    return {
        "planning_ms": round(float(payload["Planning Time"]), 3),
        "execution_ms": round(float(payload["Execution Time"]), 3),
        "root_actual_rows": payload["Plan"]["Actual Rows"],
        "scan_nodes": _scan_nodes(payload["Plan"]),
    }


def _explain_raw_page(engine: Engine, novel_id: UUID) -> dict[str, object]:
    return _explain_statement(
        engine,
        raw_page_ids_statement(novel_id, LedgerQueryFilters(), limit=20),
    )


def _assert_raw_page_gate(explain: dict[str, object], *, size: int) -> None:
    scans = explain["scan_nodes"]
    formal_scans = [
        scan for scan in scans if scan.get("index") == FORMAL_INDEX
    ]
    if not formal_scans:
        raise RuntimeError(
            f"{size}-row page query did not use required index {FORMAL_INDEX}"
        )
    visited = max(
        float(scan.get("actual_rows") or 0)
        * float(scan.get("actual_loops") or 0)
        for scan in formal_scans
    )
    if visited > 64:
        raise RuntimeError(
            f"{size}-row page query visited {visited:g} index rows; gate is 64"
        )


def main() -> None:
    engine = _engine()
    seeded: list[tuple[int, UUID, UUID, UUID, float]] = []
    evidence: dict[str, object] = {
        "schema_version": "story-ledger-benchmark/2",
        "database": "isolated *_test PostgreSQL",
        "page_limit": 20,
        "formal_index": {
            "name": FORMAL_INDEX,
            "definition": _formal_index_definition(engine),
        },
        "sizes": {},
    }
    try:
        for size in SIZES:
            novel_id, timeline_id, fact_id, seed_elapsed_ms = _seed(engine, size)
            seeded.append(
                (size, novel_id, timeline_id, fact_id, seed_elapsed_ms)
            )

        with engine.begin() as connection:
            connection.execute(text("ANALYZE story_facts"))

        for size, novel_id, timeline_id, fact_id, seed_elapsed_ms in seeded:
            def list_call():
                with Session(engine) as session:
                    return StoryLedgerService(session).list_facts(novel_id, limit=20)

            def summary_call():
                with Session(engine) as session:
                    return StoryLedgerService(session).summary(novel_id)

            def detail_call():
                with Session(engine) as session:
                    return StoryLedgerService(session).detail(novel_id, fact_id)

            list_call()
            summary_call()
            detail_call()
            scope = TimelineQueryScope(
                timeline_id=timeline_id,
                limits_by_timeline_id={timeline_id: None},
            )
            raw_page_explain = _explain_raw_page(engine, novel_id)
            _assert_raw_page_gate(raw_page_explain, size=size)
            evidence["sizes"][str(size)] = {
                "seed_elapsed_ms": round(seed_elapsed_ms, 3),
                "list": {
                    **_measure_call(engine, list_call),
                    **_timings(list_call, 5),
                },
                "summary": {
                    **_measure_call(engine, summary_call),
                    **_timings(summary_call, 3),
                },
                "detail": {
                    **_measure_call(engine, detail_call),
                    **_timings(detail_call, 3),
                },
                "raw_page_explain": raw_page_explain,
                "summary_explain": _explain_statement(
                    engine,
                    summary_statement(novel_id, scope, LedgerQueryFilters()),
                ),
                "detail_explain": _explain_statement(
                    engine,
                    fact_statement(novel_id, scope, fact_id),
                ),
            }

        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    finally:
        for _size, novel_id, _timeline_id, _fact_id, _seed_elapsed_ms in seeded:
            with Session(engine) as session:
                session.execute(delete(Novel).where(Novel.id == novel_id))
                session.commit()
        engine.dispose()


if __name__ == "__main__":
    main()
