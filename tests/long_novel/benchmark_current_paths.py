"""Measure the unmodified long-novel read paths against synthetic data only.

The benchmark refuses every database except the exact Plan 52 test database.
It never invokes an embedding or writing provider.  Run it from the repository
root with ``AI_NOVEL_TEST_DATABASE_URL`` set to a URL whose database name is
``ai_novel_world_2026_plan52_test``.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from math import ceil
import os
from pathlib import Path
import platform
from statistics import median
from time import perf_counter
import tracemalloc
from typing import Any, Callable
from uuid import UUID, uuid4

from sqlalchemy import create_engine, delete, event, func, insert, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

from backend.context_v4 import RetrievalPurpose as ContextRetrievalPurpose
from backend.context_v4_loader import assemble_writing_context_from_db
from backend.creative_data_models import (
    EmbeddingGeneration,
    EmbeddingGenerationNovel,
    EmbeddingProfile,
    NovelEmbeddingConsent,
    SemanticChunk,
    SemanticSource,
    StoryTimeline,
)
from backend.embedding.contracts import EmbeddingCorpus
from backend.embedding.local_lexical import (
    LocalLexicalSearchRequest,
    search_local_authority,
)
from backend.embedding.query_service import DenseQueryInput, execute_bounded_retrieval
from backend.embedding.retrieval import (
    RetrievalChannelStatus,
    RetrievalPerspective,
    RetrievalPurpose as CoreRetrievalPurpose,
    SearchScope,
    SemanticSearchRequestV2,
    TimelineSearchLimit,
)
from backend.embedding.writing import WritingPosition
from backend.models import (
    ChapterBrief,
    Document,
    DocumentRevision,
    DocumentWorkingCopy,
    Novel,
    StoryFact,
    Volume,
)
from backend.narration.contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID
from backend.services import (
    build_chapter_generation_prompt,
    get_document,
    get_novel,
    get_novel_context,
    list_novels,
    search_novel,
    visible_character_count,
)


SAFE_DATABASE_NAME = "ai_novel_world_2026_plan52_test"
TITLE_PREFIX = "L52-G0-SYNTHETIC-"
SAMPLES = 5
QUERY = "蓝钥匙"


@dataclass(frozen=True, slots=True)
class ScaleProfile:
    label: str
    target_characters: int
    chapter_count: int
    fact_count: int
    chunk_count: int


@dataclass(frozen=True, slots=True)
class Seed:
    novel_id: UUID
    volume_id: UUID
    timeline_id: UUID
    target_document_id: UUID
    generation_id: UUID
    profile_id: UUID


PROFILES = {
    "small": ScaleProfile("small", 40_000, 20, 100, 60),
    "1m": ScaleProfile("1m", 1_000_000, 500, 2_000, 1_500),
    "5m": ScaleProfile("5m", 5_000_000, 2_500, 10_000, 7_500),
}


def guarded_engine() -> Engine:
    raw = os.environ.get("AI_NOVEL_TEST_DATABASE_URL", "").strip()
    if not raw:
        raise RuntimeError("AI_NOVEL_TEST_DATABASE_URL is required")
    parsed = make_url(raw)
    if parsed.get_backend_name() != "postgresql" or parsed.database != SAFE_DATABASE_NAME:
        raise RuntimeError(
            f"benchmark requires the exact PostgreSQL database {SAFE_DATABASE_NAME!r}"
        )
    production = os.environ.get("AI_NOVEL_DATABASE_URL", "").strip()
    if production:
        production_target = make_url(production)
        if (
            parsed.host,
            parsed.port,
            parsed.database,
        ) == (
            production_target.host,
            production_target.port,
            production_target.database,
        ):
            raise RuntimeError("Plan 52 benchmark database must differ from production")
    return create_engine(raw, pool_pre_ping=True)


def _hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _chapter_text(index: int, length: int) -> str:
    prefix = f"第{index + 1}章。"
    if index == 2:
        prefix += "蓝钥匙由林川保管。"
    filler = "潮声穿过旧城，灯影沿着石阶缓慢移动。"
    return (prefix + filler * ceil(length / len(filler)))[:length]


def _chunks(rows: list[dict[str, Any]], size: int = 500) -> list[list[dict[str, Any]]]:
    return [rows[offset : offset + size] for offset in range(0, len(rows), size)]


def seed_profile(engine: Engine, profile: ScaleProfile) -> tuple[Seed, dict[str, Any]]:
    novel_id = uuid4()
    volume_id = uuid4()
    timeline_id = uuid4()
    profile_id = uuid4()
    generation_id = uuid4()
    consent_id = uuid4()
    chars_per_chapter = profile.target_characters // profile.chapter_count
    remainder = profile.target_characters % profile.chapter_count
    documents: list[dict[str, Any]] = []
    revisions: list[dict[str, Any]] = []
    workings: list[dict[str, Any]] = []
    semantic_sources: list[dict[str, Any]] = []
    semantic_chunks: list[dict[str, Any]] = []
    target_document_id: UUID | None = None

    started = perf_counter()
    with engine.begin() as connection:
        connection.execute(
            insert(Novel.__table__),
            {
                "id": novel_id,
                "title": f"{TITLE_PREFIX}{profile.label}",
                "description": "isolated synthetic scale evidence",
                "outline_target_chapters": profile.chapter_count,
            },
        )
        connection.execute(
            insert(Volume.__table__),
            {"id": volume_id, "novel_id": novel_id, "title": "合成卷", "position": 1_000},
        )
        connection.execute(
            insert(StoryTimeline.__table__),
            {
                "id": timeline_id,
                "novel_id": novel_id,
                "timeline_key": "main",
                "name": "主时间线",
                "normalized_name": "主时间线",
                "timeline_kind": "main",
                "is_primary": True,
                "parent_timeline_id": None,
                "fork_story_sequence": None,
                "fork_anchor_json": {},
                "lifecycle_state": "active",
                "position": 0,
                "version": 1,
            },
        )
        connection.execute(
            insert(EmbeddingProfile.__table__),
            {
                "id": profile_id,
                "owner_id": LOCAL_OWNER_ID,
                "workspace_id": LOCAL_WORKSPACE_ID,
                "provider_id": "plan52-no-provider",
                "protocol": "synthetic",
                "base_url": "https://invalid.plan52.local",
                "credential_ref": "plan52-none",
                "requested_model_id": "synthetic-2048",
                "actual_model_id": "synthetic-2048",
                "actual_revision": "g0",
                "dimension": 2048,
                "output_type": "dense",
                "document_text_type": "document",
                "query_text_type": "query",
                "distance_metric": "cosine",
                "index_fingerprint": _hash(f"profile:{profile.label}"),
                "connection_state": "ready",
            },
        )
        connection.execute(
            insert(EmbeddingGeneration.__table__),
            {
                "id": generation_id,
                "owner_id": LOCAL_OWNER_ID,
                "workspace_id": LOCAL_WORKSPACE_ID,
                "profile_id": profile_id,
                "generation_number": {"small": 101, "1m": 102, "5m": 103}[profile.label],
                "state": "active",
                "renderer_bundle_version": "semantic-renderers/1",
                "chunker_version": "semantic-char-chunker/5b",
                "query_policy_version": "writing-retrieval/2",
                "index_fingerprint": _hash(f"generation:{profile.label}"),
                "consent_cohort_hash": _hash(f"cohort:{profile.label}"),
                "evaluation_state": "passed",
                "evaluation_summary_json": {"synthetic": True},
            },
        )
        connection.execute(
            insert(NovelEmbeddingConsent.__table__),
            {
                "id": consent_id,
                "novel_id": novel_id,
                "purpose": "semantic_retrieval",
                "data_scope_json": ["manuscript", "planning", "private_asset", "writing_query"],
                "notice_version": "novel-embedding-consent/2",
                "provider_id": "plan52-no-provider",
                "model_id": "synthetic-2048",
                "idempotency_key": f"plan52:{profile.label}",
                "operation_hash": _hash(f"consent:{profile.label}"),
                "confirmed_actor": "plan52-benchmark",
            },
        )
        connection.execute(
            insert(EmbeddingGenerationNovel.__table__),
            {
                "id": uuid4(),
                "generation_id": generation_id,
                "novel_id": novel_id,
                "owner_id": LOCAL_OWNER_ID,
                "workspace_id": LOCAL_WORKSPACE_ID,
                "consent_id": consent_id,
                "state": "ready",
                "target_corpora_json": ["manuscript"],
                "input_digest": _hash(f"input:{profile.label}"),
                "source_count": profile.chapter_count,
                "chunk_count": profile.chunk_count,
                "embedded_count": 0,
                "failure_count": 0,
                "index_version": 1,
                "authority_digest": _hash(f"authority:{profile.label}"),
                "published_digest": _hash(f"published:{profile.label}"),
                "sync_state": "current",
                "pending_refresh_count": 0,
            },
        )

        for index in range(profile.chapter_count):
            document_id = uuid4()
            revision_id = uuid4()
            chapter_length = chars_per_chapter + (1 if index < remainder else 0)
            content = _chapter_text(index, chapter_length)
            content_hash = _hash(content)
            if index == profile.chapter_count - 1:
                target_document_id = document_id
            documents.append(
                {
                    "id": document_id,
                    "novel_id": novel_id,
                    "volume_id": volume_id,
                    "kind": "chapter",
                    "title": f"合成章节{index + 1}",
                    "position": (index + 1) * 1_000,
                    "status": "final",
                    "version": 1,
                }
            )
            revisions.append(
                {
                    "id": revision_id,
                    "document_id": document_id,
                    "revision_number": 2 if index % 50 == 0 else 1,
                    "content_markdown": content,
                    "content_text": content,
                    "content_hash": content_hash,
                    "source": "manual",
                }
            )
            if index % 50 == 0:
                previous = content[:-1] + "旧"
                revisions.append(
                    {
                        "id": uuid4(),
                        "document_id": document_id,
                        "revision_number": 1,
                        "content_markdown": previous,
                        "content_text": previous,
                        "content_hash": _hash(previous),
                        "source": "checkpoint",
                    }
                )
            workings.append(
                {
                    "document_id": document_id,
                    "base_revision_id": revision_id,
                    "draft_version": 1,
                    "content_markdown": content,
                    "content_hash": content_hash,
                    "visible_character_count": visible_character_count(content),
                }
            )
            source_id = uuid4()
            semantic_sources.append(
                {
                    "id": source_id,
                    "generation_id": generation_id,
                    "novel_id": novel_id,
                    "corpus": "manuscript",
                    "source_type": "chapter_revision",
                    "source_entity_id": document_id,
                    "source_revision_id": revision_id,
                    "source_locator_json": {"document_id": str(document_id)},
                    "content_hash": content_hash,
                    "renderer_version": "semantic-v1-renderers/2",
                    "timeline_id": timeline_id,
                    "narrative_sequence_start": index + 1,
                    "narrative_sequence_end": index + 1,
                    "story_sequence_start": index + 1,
                    "story_sequence_end": index + 1,
                    "visibility_json": {"visibility": "public"},
                    "status": "current",
                    "source_fingerprint": _hash(f"source:{profile.label}:{index}"),
                }
            )
            for chunk_index in range(3):
                chunk_text = (
                    "蓝钥匙由林川保管。"
                    if index == 2 and chunk_index == 0
                    else f"章节{index + 1}片段{chunk_index + 1}。" + "潮声旧城" * 80
                )
                semantic_chunks.append(
                    {
                        "id": uuid4(),
                        "generation_id": generation_id,
                        "source_id": source_id,
                        "chunk_index": chunk_index,
                        "source_start": chunk_index * 640,
                        "source_end": chunk_index * 640 + len(chunk_text),
                        "content_text": chunk_text,
                        "content_hash": _hash(chunk_text),
                        "estimated_token_count": len(chunk_text),
                        "token_estimator_version": "unicode-char-estimate/1",
                        "chunker_version": "semantic-char-chunker/5b",
                    }
                )

        for batch in _chunks(documents):
            connection.execute(insert(Document.__table__), batch)
        for batch in _chunks(revisions):
            connection.execute(insert(DocumentRevision.__table__), batch)
        for batch in _chunks(workings):
            connection.execute(insert(DocumentWorkingCopy.__table__), batch)

        facts = []
        for index in range(profile.fact_count):
            facts.append(
                {
                    "id": uuid4(),
                    "novel_id": novel_id,
                    "fact_type": "general_fact",
                    "subject": f"实体{index % 200}",
                    "predicate": f"槽位{index % 50}",
                    "object_text": f"事实值{index}",
                    "details": {"schema_version": "general-fact/1", "value": f"事实值{index}"},
                    "schema_version": "story-fact/2",
                    "timeline_id": timeline_id,
                    "dimension": "fact",
                    "event_kind": "note",
                    "story_sequence": index % profile.chapter_count + 1,
                    "visibility_json": {"scope": "author"},
                    "event_fingerprint": _hash(f"fact:{profile.label}:{index}"),
                    "status": "active",
                }
            )
        for batch in _chunks(facts, 1_000):
            connection.execute(insert(StoryFact.__table__), batch)
        for batch in _chunks(semantic_sources):
            connection.execute(insert(SemanticSource.__table__), batch)
        for batch in _chunks(semantic_chunks):
            connection.execute(insert(SemanticChunk.__table__), batch)
        connection.execute(
            insert(ChapterBrief.__table__),
            {
                "id": uuid4(),
                "document_id": target_document_id,
                "version": 1,
                "target_word_count": 3_000,
                "expectation_text": "延续蓝钥匙伏笔",
                "outline_text": "人物回到旧城",
                "forbidden_text": "不得泄漏未来事件",
                "role_constraints": {},
            },
        )
        connection.execute(text("ANALYZE"))

    assert target_document_id is not None
    return (
        Seed(
            novel_id=novel_id,
            volume_id=volume_id,
            timeline_id=timeline_id,
            target_document_id=target_document_id,
            generation_id=generation_id,
            profile_id=profile_id,
        ),
        {
            "elapsed_ms": round((perf_counter() - started) * 1_000, 3),
            "chapter_count": profile.chapter_count,
            "target_characters": profile.target_characters,
            "fact_count": profile.fact_count,
            "semantic_source_count": len(semantic_sources),
            "semantic_chunk_count": len(semantic_chunks),
            "historical_revision_count": sum(1 for index in range(profile.chapter_count) if index % 50 == 0),
        },
    )


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, ceil(len(ordered) * fraction) - 1))]


def _json_size(value: Any) -> int:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if hasattr(value, "as_semantic_search_hits"):
        value = {
            "hits": [item.model_dump(mode="json") for item in value.as_semantic_search_hits()],
            "diagnostics": asdict(value.diagnostics),
        }
    return len(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"))


def measure(engine: Engine, operation: Callable[[Session], Any]) -> dict[str, Any]:
    elapsed_values: list[float] = []
    sql_counts: list[int] = []
    response_bytes = 0
    peak_bytes = 0
    for _ in range(SAMPLES):
        sql_count = 0

        def count_sql(*_args: Any, **_kwargs: Any) -> None:
            nonlocal sql_count
            sql_count += 1

        event.listen(engine, "before_cursor_execute", count_sql)
        tracemalloc.start()
        started = perf_counter()
        try:
            with Session(engine) as session:
                result = operation(session)
                response_bytes = max(response_bytes, _json_size(result))
                session.rollback()
            elapsed_values.append((perf_counter() - started) * 1_000)
            _, current_peak = tracemalloc.get_traced_memory()
            peak_bytes = max(peak_bytes, current_peak)
        finally:
            tracemalloc.stop()
            event.remove(engine, "before_cursor_execute", count_sql)
        sql_counts.append(sql_count)
    return {
        "samples": SAMPLES,
        "p50_ms": round(median(elapsed_values), 3),
        "p95_ms": round(_percentile(elapsed_values, 0.95), 3),
        "peak_tracemalloc_mib": round(peak_bytes / 1024 / 1024, 3),
        "response_bytes": response_bytes,
        "sql_count_min": min(sql_counts),
        "sql_count_max": max(sql_counts),
    }


def _indexed_lexical(session: Session, seed: Seed, profile: ScaleProfile) -> dict[str, Any]:
    request = SemanticSearchRequestV2(
        query=QUERY,
        purpose=CoreRetrievalPurpose.CHAPTER_BODY,
        scope=SearchScope(
            owner_id=LOCAL_OWNER_ID,
            workspace_id=LOCAL_WORKSPACE_ID,
            novel_id=seed.novel_id,
            generation_id=seed.generation_id,
            index_version=1,
            corpora=frozenset({EmbeddingCorpus.MANUSCRIPT}),
            target_timeline_id=seed.timeline_id,
            narrative_sequence_cutoff=profile.chapter_count,
            story_sequence_cutoff=profile.chapter_count,
            timeline_limits=(
                TimelineSearchLimit(
                    timeline_id=seed.timeline_id,
                    story_sequence_cutoff=profile.chapter_count,
                ),
            ),
            perspective=RetrievalPerspective.AUTHOR,
        ),
        top_k=10,
    )
    execution = execute_bounded_retrieval(
        session,
        request=request,
        dense_input=DenseQueryInput(
            status=RetrievalChannelStatus.UNAVAILABLE,
            redacted_error="synthetic benchmark intentionally disables provider calls",
        ),
    )
    return {
        "result": execution.result.model_dump(mode="json"),
        "dense_candidate_count": execution.dense_candidate_count,
        "lexical_candidate_count": execution.lexical_candidate_count,
        "enriched_candidate_count": execution.enriched_candidate_count,
        "adjacent_candidate_count": execution.adjacent_candidate_count,
    }


def _explain(session: Session, sql: str, parameters: dict[str, Any]) -> dict[str, Any]:
    payload = session.execute(
        text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql), parameters
    ).scalar_one()[0]
    return payload


def _scan_summary(plan: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    def visit(node: dict[str, Any]) -> None:
        if "Scan" in str(node.get("Node Type", "")):
            result.append(
                {
                    "node_type": node.get("Node Type"),
                    "relation": node.get("Relation Name"),
                    "index": node.get("Index Name"),
                    "actual_rows": node.get("Actual Rows"),
                    "rows_removed_by_filter": node.get("Rows Removed by Filter", 0),
                    "shared_hit_blocks": node.get("Shared Hit Blocks", 0),
                    "shared_read_blocks": node.get("Shared Read Blocks", 0),
                }
            )
        for child in node.get("Plans", ()):  # type: ignore[union-attr]
            visit(child)

    visit(plan["Plan"])
    return result


def explain_lexical(engine: Engine, seed: Seed) -> dict[str, Any]:
    common = """
        FROM semantic_sources s
        JOIN semantic_chunks c ON c.source_id = s.id
        WHERE s.generation_id = :generation_id
          AND s.novel_id = :novel_id
          AND s.corpus = 'manuscript'
          AND s.status = 'current'
    """
    params = {"generation_id": seed.generation_id, "novel_id": seed.novel_id, "query": QUERY}
    with Session(engine) as session:
        current = _explain(
            session,
            "SELECT c.id, similarity(c.content_text, :query) AS score "
            + common
            + " ORDER BY s.id, c.chunk_index",
            params,
        )
        session.execute(text("SET LOCAL pg_trgm.similarity_threshold = 0.05"))
        bounded = _explain(
            session,
            "SELECT c.id, similarity(c.content_text, :query) AS score "
            + common
            + " AND c.content_text % :query ORDER BY score DESC LIMIT 80",
            params,
        )
        return {
            "current_unbounded": {
                "planning_ms": round(float(current["Planning Time"]), 3),
                "execution_ms": round(float(current["Execution Time"]), 3),
                "root_rows": current["Plan"]["Actual Rows"],
                "scans": _scan_summary(current),
            },
            "candidate_bounded": {
                "planning_ms": round(float(bounded["Planning Time"]), 3),
                "execution_ms": round(float(bounded["Execution Time"]), 3),
                "root_rows": bounded["Plan"]["Actual Rows"],
                "scans": _scan_summary(bounded),
            },
        }


def cleanup(engine: Engine, seed: Seed) -> None:
    with engine.begin() as connection:
        # SemanticSource's timeline scope is deliberately RESTRICT, so derived
        # rows must be removed before deleting the synthetic authority root.
        connection.execute(
            delete(SemanticSource).where(SemanticSource.generation_id == seed.generation_id)
        )
        connection.execute(delete(Novel).where(Novel.id == seed.novel_id))
        connection.execute(
            delete(EmbeddingGeneration).where(EmbeddingGeneration.id == seed.generation_id)
        )
        connection.execute(delete(EmbeddingProfile).where(EmbeddingProfile.id == seed.profile_id))


def benchmark_profile(engine: Engine, profile: ScaleProfile) -> dict[str, Any]:
    seed, seed_evidence = seed_profile(engine, profile)
    try:
        position = WritingPosition(
            novel_id=seed.novel_id,
            document_id=seed.target_document_id,
            title=f"合成章节{profile.chapter_count}",
            narrative_sequence=profile.chapter_count,
            timeline_id=seed.timeline_id,
            story_sequence_cutoff=profile.chapter_count,
            mapping_version="single-timeline-identity/1",
        )

        def context_operation(session: Session) -> dict[str, Any]:
            brief = session.scalar(
                select(ChapterBrief).where(ChapterBrief.document_id == seed.target_document_id)
            )
            assert brief is not None
            return assemble_writing_context_from_db(
                session,
                position=position,
                purpose=ContextRetrievalPurpose.CHAPTER_BODY,
                requested_provider_id="plan52-provider",
                requested_model_id="plan52-model",
                budget_provider_id="plan52-provider",
                budget_model_id="plan52-model",
                effective_context_window_tokens=128_000,
                reserved_output_tokens=6_000,
                chapter_brief=brief,
                private_assets=(),
                writing_retrieval=None,
            )

        with Session(engine) as session:
            context_snapshot = context_operation(session)
            document = get_document(session, seed.target_document_id)
            brief = session.scalar(
                select(ChapterBrief).where(ChapterBrief.document_id == seed.target_document_id)
            )
            assert brief is not None
            prompt_snapshot = {
                "novel": {"id": str(seed.novel_id), "title": f"合成长篇{profile.label}"},
                "chapter": {
                    "document_id": str(seed.target_document_id),
                    "title": document["title"],
                    "base_content_markdown": document["content_markdown"],
                },
                "brief": {
                    "target_word_count": brief.target_word_count,
                    "expectation_text": brief.expectation_text,
                    "outline_text": brief.outline_text,
                    "forbidden_text": brief.forbidden_text,
                    "role_constraints": {
                        "required": [],
                        "allowed": [],
                        "context_only": [],
                        "forbidden": [],
                    },
                },
                "acceptance": {
                    "requested_visible_character_count": brief.target_word_count,
                },
                "writing_context": context_snapshot,
            }

        local_request = LocalLexicalSearchRequest(
            owner_id=LOCAL_OWNER_ID,
            workspace_id=LOCAL_WORKSPACE_ID,
            novel_id=seed.novel_id,
            query=QUERY,
            corpora=frozenset({EmbeddingCorpus.MANUSCRIPT}),
            top_k=10,
            target_timeline_id=seed.timeline_id,
            narrative_sequence_cutoff=profile.chapter_count - 1,
            story_sequence_cutoff=profile.chapter_count - 1,
        )
        paths = {
            "list_novels": measure(engine, lambda session: list_novels(session)),
            "open_novel_metadata": measure(engine, lambda session: get_novel(session, seed.novel_id)),
            "selected_document": measure(engine, lambda session: get_document(session, seed.target_document_id)),
            "assistant_context": measure(
                engine,
                lambda session: get_novel_context(
                    session,
                    seed.novel_id,
                    document_id=seed.target_document_id,
                    max_chars=40_000,
                ),
            ),
            "search_novel": measure(engine, lambda session: search_novel(session, seed.novel_id, QUERY, 20)),
            "context_v4": measure(engine, context_operation),
            "prompt_builder": measure(
                engine,
                lambda _session: {"prompt": build_chapter_generation_prompt(prompt_snapshot)},
            ),
            "authority_local_lexical": measure(
                engine, lambda session: search_local_authority(session, local_request)
            ),
            "indexed_lexical_current": measure(
                engine, lambda session: _indexed_lexical(session, seed, profile)
            ),
        }
        return {
            "profile": profile.label,
            "seed": seed_evidence,
            "paths": paths,
            "lexical_explain": explain_lexical(engine, seed),
        }
    finally:
        cleanup(engine, seed)


def run(labels: list[str]) -> dict[str, Any]:
    engine = guarded_engine()
    try:
        with engine.connect() as connection:
            head = connection.scalar(text("SELECT version_num FROM alembic_version"))
            if head != "20260902_0039":
                raise RuntimeError(f"Plan 52 database is not at the frozen head: {head}")
            leftovers = connection.scalar(
                select(func.count()).select_from(Novel).where(Novel.title.like(f"{TITLE_PREFIX}%"))
            )
            if leftovers:
                raise RuntimeError("stale Plan 52 synthetic novels exist; inspect before retrying")
        evidence = {
            "schema_version": "plan52-scale-evidence/2",
            "database_name": SAFE_DATABASE_NAME,
            "alembic_head": "20260902_0039",
            "provider_calls": 0,
            "samples_per_path": SAMPLES,
            "host": {
                "platform": platform.platform(),
                "machine": platform.machine(),
                "python": platform.python_version(),
                "processor": platform.processor(),
            },
            "profiles": [benchmark_profile(engine, PROFILES[label]) for label in labels],
        }
        return evidence
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles", default="small,1m,5m")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    labels = [item.strip() for item in args.profiles.split(",") if item.strip()]
    unknown = sorted(set(labels) - set(PROFILES))
    if unknown:
        raise SystemExit(f"unknown profiles: {', '.join(unknown)}")
    evidence = run(labels)
    serialized = json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)


if __name__ == "__main__":
    main()
