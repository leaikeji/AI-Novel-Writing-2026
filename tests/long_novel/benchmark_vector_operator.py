"""Plan 52 exact pgvector operator baseline in the isolated test database."""

from __future__ import annotations

import argparse
import json
from math import ceil
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any

from sqlalchemy import text

try:
    from .benchmark_current_paths import guarded_engine
except ImportError:  # Direct script execution from the repository root.
    from benchmark_current_paths import guarded_engine


SAMPLES = 5
TABLE = "plan52_g0_vector_probe"


def _vector(first: float, second: float) -> str:
    return "[" + ",".join((str(first), str(second), *("0" for _ in range(2046)))) + "]"


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, ceil(len(ordered) * fraction) - 1))]


def _summarize(payload: dict[str, Any]) -> dict[str, Any]:
    scans: list[dict[str, Any]] = []

    def visit(node: dict[str, Any]) -> None:
        if "Scan" in str(node.get("Node Type", "")):
            scans.append(
                {
                    "node_type": node.get("Node Type"),
                    "relation": node.get("Relation Name"),
                    "index": node.get("Index Name"),
                    "actual_rows": node.get("Actual Rows"),
                    "shared_hit_blocks": node.get("Shared Hit Blocks", 0),
                    "shared_read_blocks": node.get("Shared Read Blocks", 0),
                }
            )
        for child in node.get("Plans", ()):  # type: ignore[union-attr]
            visit(child)

    visit(payload["Plan"])
    return {
        "planning_ms": round(float(payload["Planning Time"]), 3),
        "execution_ms": round(float(payload["Execution Time"]), 3),
        "root_rows": payload["Plan"]["Actual Rows"],
        "scans": scans,
    }


def _measure(connection, sql: str, query_vector: str) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    timings: list[float] = []
    returned = 0
    for _ in range(SAMPLES):
        started = perf_counter()
        rows = connection.execute(text(sql), {"query_vector": query_vector}).all()
        timings.append((perf_counter() - started) * 1_000)
        returned = len(rows)
    plan = connection.execute(
        text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql),
        {"query_vector": query_vector},
    ).scalar_one()[0]
    return {
        "samples": SAMPLES,
        "p50_ms": round(median(timings), 3),
        "p95_ms": round(_percentile(timings, 0.95), 3),
        "returned_rows": returned,
        "explain": _summarize(plan),
    }


def run(sizes: list[int]) -> dict[str, Any]:
    engine = guarded_engine()
    target = _vector(1.0, 0.0)
    other = _vector(0.0, 1.0)
    evidence: list[dict[str, Any]] = []
    try:
        with engine.begin() as connection:
            connection.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))
            connection.execute(
                text(f"CREATE UNLOGGED TABLE {TABLE} (id bigint PRIMARY KEY, embedding vector(2048) NOT NULL)")
            )
        for size in sizes:
            with engine.begin() as connection:
                connection.execute(text(f"TRUNCATE TABLE {TABLE}"))
                started = perf_counter()
                connection.execute(
                    text(
                        f"INSERT INTO {TABLE} (id, embedding) "
                        "SELECT value, CASE WHEN value = 1 "
                        "THEN CAST(:target AS vector(2048)) "
                        "ELSE CAST(:other AS vector(2048)) END "
                        "FROM generate_series(1, :size) AS value"
                    ),
                    {"target": target, "other": other, "size": size},
                )
                seed_ms = (perf_counter() - started) * 1_000
                connection.execute(text(f"ANALYZE {TABLE}"))
                base = (
                    f"SELECT id, embedding <=> CAST(:query_vector AS vector(2048)) AS distance "
                    f"FROM {TABLE} WHERE embedding <=> CAST(:query_vector AS vector(2048)) <= 2.0 "
                    "ORDER BY distance"
                )
                evidence.append(
                    {
                        "row_count": size,
                        "seed_ms": round(seed_ms, 3),
                        "current_unbounded": _measure(connection, base, target),
                        "candidate_bounded": _measure(connection, base + " LIMIT 80", target),
                    }
                )
        return {
            "schema_version": "plan52-g0-vector-evidence/1",
            "database_name": "ai_novel_world_2026_plan52_test",
            "dimension": 2048,
            "distance_metric": "cosine",
            "ann_index": None,
            "provider_calls": 0,
            "sizes": evidence,
        }
    finally:
        try:
            with engine.begin() as connection:
                connection.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))
        finally:
            engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", default="1500,7500")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    sizes = [int(item.strip()) for item in args.sizes.split(",") if item.strip()]
    payload = run(sizes)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)


if __name__ == "__main__":
    main()
