"""Measure retired semantic-source churn against the current query shape."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

try:
    from .benchmark_current_paths import (
        PROFILES,
        cleanup,
        explain_lexical,
        guarded_engine,
        seed_profile,
    )
except ImportError:  # Direct script execution from the repository root.
    from benchmark_current_paths import (
        PROFILES,
        cleanup,
        explain_lexical,
        guarded_engine,
        seed_profile,
    )

from backend.creative_data_models import SemanticChunk, SemanticSource


def _seed_retired(engine, seed, factor: int) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    source_count = PROFILES["5m"].chapter_count * factor
    started = perf_counter()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO semantic_sources "
                "(id, generation_id, novel_id, corpus, source_type, source_entity_id, "
                " source_revision_id, source_locator_json, content_hash, renderer_version, "
                " timeline_id, narrative_sequence_start, narrative_sequence_end, "
                " story_sequence_start, story_sequence_end, visibility_json, status, source_fingerprint) "
                "SELECT gen_random_uuid(), :generation_id, :novel_id, 'manuscript', "
                "'chapter_revision', gen_random_uuid(), NULL, '{}'::jsonb, "
                "repeat(md5('retired-content:' || value::text), 2), 'semantic-v1-renderers/2', "
                ":timeline_id, value, value, value, value, '{\"visibility\":\"public\"}'::jsonb, "
                "'retired', repeat(md5('retired-source:' || value::text), 2) "
                "FROM generate_series(1, :source_count) AS value"
            ),
            {
                "generation_id": seed.generation_id,
                "novel_id": seed.novel_id,
                "timeline_id": seed.timeline_id,
                "source_count": source_count,
            },
        )
        connection.execute(
            text(
                "INSERT INTO semantic_chunks "
                "(id, generation_id, source_id, chunk_index, source_start, source_end, "
                " content_text, content_hash, estimated_token_count, token_estimator_version, chunker_version) "
                "SELECT gen_random_uuid(), s.generation_id, s.id, ordinal, ordinal * 640, "
                "ordinal * 640 + 320, '退役派生片段' || ordinal::text || repeat('旧城', 80), "
                "repeat(md5(s.id::text || ':' || ordinal::text), 2), 320, "
                "'unicode-char-estimate/1', 'semantic-char-chunker/5b' "
                "FROM semantic_sources s CROSS JOIN generate_series(0, 2) AS ordinal "
                "WHERE s.generation_id = :generation_id AND s.novel_id = :novel_id "
                "AND s.status = 'retired'"
            ),
            {"generation_id": seed.generation_id, "novel_id": seed.novel_id},
        )
        connection.execute(text("ANALYZE semantic_sources"))
        connection.execute(text("ANALYZE semantic_chunks"))
    return {
        "factor": factor,
        "retired_source_count": source_count,
        "retired_chunk_count": source_count * 3,
        "seed_ms": round((perf_counter() - started) * 1_000, 3),
    }


def _cleanup_retired(engine, seed) -> None:  # type: ignore[no-untyped-def]
    with engine.begin() as connection:
        connection.execute(
            delete(SemanticSource).where(
                SemanticSource.generation_id == seed.generation_id,
                SemanticSource.novel_id == seed.novel_id,
                SemanticSource.status == "retired",
            )
        )


def run() -> dict[str, Any]:
    engine = guarded_engine()
    seed, seed_evidence = seed_profile(engine, PROFILES["5m"])
    rows: list[dict[str, Any]] = []
    try:
        for factor in (1, 10):
            churn = _seed_retired(engine, seed, factor)
            with Session(engine) as session:
                counts = session.execute(
                    select(
                        func.count(SemanticSource.id),
                        func.count(SemanticSource.id).filter(SemanticSource.status == "current"),
                        func.count(SemanticSource.id).filter(SemanticSource.status == "retired"),
                    ).where(
                        SemanticSource.generation_id == seed.generation_id,
                        SemanticSource.novel_id == seed.novel_id,
                    )
                ).one()
                chunk_count = session.scalar(
                    select(func.count()).select_from(SemanticChunk).where(
                        SemanticChunk.generation_id == seed.generation_id
                    )
                )
            rows.append(
                churn
                | {
                    "total_source_count": int(counts[0]),
                    "current_source_count": int(counts[1]),
                    "observed_retired_source_count": int(counts[2]),
                    "total_chunk_count": int(chunk_count or 0),
                    "current_query": explain_lexical(engine, seed)["current_unbounded"],
                }
            )
            _cleanup_retired(engine, seed)
        return {
            "schema_version": "plan52-g0-churn-evidence/1",
            "database_name": "ai_novel_world_2026_plan52_test",
            "provider_calls": 0,
            "base": seed_evidence,
            "churn": rows,
        }
    finally:
        _cleanup_retired(engine, seed)
        cleanup(engine, seed)
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = run()
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)


if __name__ == "__main__":
    main()
