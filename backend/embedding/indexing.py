"""Prepare immutable V1 semantic sources and durable embedding batches."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from ..background.contracts import LocalWorkspaceScope
from ..background.jobs import enqueue_job
from ..creative_data_models import (
    EmbeddingGeneration,
    EmbeddingGenerationNovel,
    EmbeddingConfiguration,
    EmbeddingIndexBatch,
    EmbeddingIndexBatchItem,
    NovelAssetBinding,
    NovelEmbeddingConsent,
    NovelOutlineHead,
    NovelOutlineRevision,
    NovelSettingHead,
    NovelSettingRevision,
    PrivateAssetVersion,
    RevisionTimelineMappingHead,
    RevisionTimelineMappingSegment,
    SemanticChunk,
    SemanticEmbedding,
    SemanticSource,
    StoryTimeline,
)
from .chunking import (
    LEGACY_V1_RENDERER_VERSION,
    V1_RENDERER_VERSION,
    V1SourceInput,
    TOKEN_ESTIMATOR_VERSION,
    RenderedSource,
    chunk_rendered_source,
    estimate_token_count,
    render_structured_setting,
    render_v1_source,
)
from .lifecycle import EmbeddingLifecycleError
from .refresh import (
    PendingSourceSpec,
    PublicationAuthority,
    RefreshRequest,
    service_for_session,
)
from ..models import Document, DocumentRevision, DocumentWorkingCopy, Volume
from ..models import Novel
from ..volume_chapter_titles import embedding_chapter_title


V1_CORPORA = frozenset({"manuscript", "planning", "private_asset"})
# The current DashScope workspace endpoint is fast for one 2048-dimension
# document (including 1,800-character chunks) but can keep multi-document
# arrays open for minutes.  Preserve the protocol cap of ten while using the
# verified singleton product policy for predictable local-job fencing.
EMBEDDING_BATCH_MAX_ITEMS = 1
EMBEDDING_BATCH_MAX_CHARACTERS = 1_200


def _digest(value: object) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(text.encode("utf-8")).hexdigest()


def _logical_source_key(
    *,
    source_type: str,
    source_entity_id: UUID,
    timeline_id: UUID | None,
    locator: dict[str, object],
) -> str:
    return ":".join(
        (
            source_type,
            str(source_entity_id),
            str(timeline_id or "global"),
            str(locator.get("source_start", "head")),
        )
    )


def _batch_chunks(chunks: list[SemanticChunk]) -> tuple[tuple[SemanticChunk, ...], ...]:
    """Apply the verified item policy and the long-text request budget."""

    batches: list[tuple[SemanticChunk, ...]] = []
    current: list[SemanticChunk] = []
    current_characters = 0
    for chunk in chunks:
        chunk_characters = len(chunk.content_text)
        if current and (
            len(current) >= EMBEDDING_BATCH_MAX_ITEMS
            or current_characters + chunk_characters > EMBEDDING_BATCH_MAX_CHARACTERS
        ):
            batches.append(tuple(current))
            current = []
            current_characters = 0
        current.append(chunk)
        current_characters += chunk_characters
    if current:
        batches.append(tuple(current))
    return tuple(batches)


def build_generation_renderer(session: Session, generation_id: UUID) -> str:
    """Resolve the immutable renderer paired with a generation's chunker."""

    return (
        LEGACY_V1_RENDERER_VERSION
        if build_generation_chunker(session, generation_id)
        == "semantic-char-chunker/4"
        else V1_RENDERER_VERSION
    )


def _persist_source(
    session: Session,
    *,
    build: EmbeddingGenerationNovel,
    source_input: V1SourceInput,
    timeline_id: UUID | None,
    narrative_start: int | None,
    narrative_end: int | None,
    story_start: int | None,
    story_end: int | None,
    locator: dict[str, object],
    visibility: dict[str, object],
) -> tuple[SemanticSource, tuple[SemanticChunk, ...]]:
    rendered = render_v1_source(
        source_input,
        renderer_version=build_generation_renderer(session, build.generation_id),
    )
    logical_key = _logical_source_key(
        source_type=source_input.source_type,
        source_entity_id=source_input.source_entity_id,
        timeline_id=timeline_id,
        locator=locator,
    )
    stored_locator = dict(locator)
    stored_locator["_refresh_logical_key"] = logical_key
    source = SemanticSource(
        id=uuid4(), generation_id=build.generation_id, novel_id=build.novel_id,
        corpus=rendered.corpus, source_type=rendered.source_type,
        source_entity_id=rendered.source_entity_id,
        source_revision_id=rendered.source_revision_id,
        source_locator_json=stored_locator, content_hash=rendered.content_hash,
        renderer_version=rendered.renderer_version, timeline_id=timeline_id,
        character_instance_id=None,
        narrative_sequence_start=narrative_start,
        narrative_sequence_end=narrative_end,
        story_sequence_start=story_start,
        story_sequence_end=story_end,
        visibility_json=visibility,
        status="current",
        source_fingerprint=_digest(
            [
                rendered.source_fingerprint,
                str(timeline_id) if timeline_id else None,
                narrative_start,
                narrative_end,
                story_start,
                story_end,
                locator,
            ]
        ),
    )
    session.add(source)
    session.flush()
    records: list[SemanticChunk] = []
    for chunk in chunk_rendered_source(
        rendered, chunker_version=build_generation_chunker(session, build.generation_id)
    ):
        record = SemanticChunk(
            id=uuid4(), generation_id=build.generation_id, source_id=source.id,
            chunk_index=chunk.index, source_start=chunk.source_start,
            source_end=chunk.source_end, content_text=chunk.text,
            content_hash=chunk.content_hash,
            estimated_token_count=estimate_token_count(chunk.text),
            token_estimator_version=TOKEN_ESTIMATOR_VERSION,
            chunker_version=chunk.chunker_version,
        )
        session.add(record)
        records.append(record)
    session.flush()
    return source, tuple(records)


def _persist_chunks_for_rendered(
    session: Session,
    *,
    generation_id: UUID,
    source_id: UUID,
    rendered: RenderedSource,
    chunker_version: str,
) -> tuple[SemanticChunk, ...]:
    records: list[SemanticChunk] = []
    for chunk in chunk_rendered_source(rendered, chunker_version=chunker_version):
        record = SemanticChunk(
            id=uuid4(), generation_id=generation_id, source_id=source_id,
            chunk_index=chunk.index, source_start=chunk.source_start,
            source_end=chunk.source_end, content_text=chunk.text,
            content_hash=chunk.content_hash,
            estimated_token_count=estimate_token_count(chunk.text),
            token_estimator_version=TOKEN_ESTIMATOR_VERSION,
            chunker_version=chunk.chunker_version,
        )
        session.add(record)
        records.append(record)
    session.flush()
    return tuple(records)


def _enqueue_chunk_batches(
    session: Session,
    *,
    generation_id: UUID,
    novel_id: UUID,
    chunks: tuple[SemanticChunk, ...],
    batch_number_start: int,
    idempotency_prefix: str,
    refresh_id: UUID | None = None,
) -> int:
    scope = LocalWorkspaceScope.fixed_local()
    for offset, items in enumerate(_batch_chunks(list(chunks))):
        number = batch_number_start + offset
        input_hash = _digest([str(item.id) + ":" + item.content_hash for item in items])
        batch = EmbeddingIndexBatch(
            id=uuid4(), generation_id=generation_id, novel_id=novel_id,
            refresh_id=refresh_id, batch_number=number, input_hash=input_hash,
            item_count=len(items), state="pending", attempt_count=0, result_count=0,
        )
        session.add(batch)
        session.flush()
        for ordinal, item in enumerate(items):
            session.add(EmbeddingIndexBatchItem(
                id=uuid4(), batch_id=batch.id, generation_id=generation_id,
                chunk_id=item.id, ordinal=ordinal,
            ))
        job = enqueue_job(
            session, scope=scope, job_kind="embedding.index_batch",
            input_hash=input_hash,
            idempotency_key=f"{idempotency_prefix}:{offset}",
            resource_class="dashscope-embedding", novel_id=novel_id, max_attempts=3,
        )
        batch.background_job_id = job.job_id
        batch.state = "queued"
    return len(_batch_chunks(list(chunks)))


def _locator_without_refresh_key(value: dict[str, object]) -> dict[str, object]:
    return {
        key: item
        for key, item in value.items()
        if key not in {
            "_refresh_logical_key",
            "_metadata_projection_base_index_version",
        }
    }


def _same_source_projection(
    current: SemanticSource,
    *,
    rendered: RenderedSource,
    source_input: V1SourceInput,
    timeline_id: UUID | None,
    narrative_start: int | None,
    narrative_end: int | None,
    story_start: int | None,
    story_end: int | None,
    locator: dict[str, object],
    visibility: dict[str, object],
) -> bool:
    return (
        current.corpus == rendered.corpus
        and current.source_type == rendered.source_type
        and current.source_entity_id == source_input.source_entity_id
        and current.source_revision_id == source_input.source_revision_id
        and current.content_hash == rendered.content_hash
        and current.renderer_version == rendered.renderer_version
        and current.timeline_id == timeline_id
        and current.character_instance_id is None
        and current.narrative_sequence_start == narrative_start
        and current.narrative_sequence_end == narrative_end
        and current.story_sequence_start == story_start
        and current.story_sequence_end == story_end
        and _locator_without_refresh_key(dict(current.source_locator_json or {}))
        == locator
        and dict(current.visibility_json or {}) == visibility
    )


def _metadata_only_reprojection_source(
    candidates: tuple[SemanticSource, ...],
    *,
    rendered: RenderedSource,
    source_input: V1SourceInput,
    timeline_id: UUID | None,
    locator: dict[str, object],
    visibility: dict[str, object],
) -> SemanticSource | None:
    """Return a source whose immutable text is identical and only position moved."""

    for current in candidates:
        if (
            current.corpus == rendered.corpus
            and current.source_type == rendered.source_type
            and current.source_entity_id == source_input.source_entity_id
            and current.source_revision_id == source_input.source_revision_id
            and current.content_hash == rendered.content_hash
            and current.renderer_version == rendered.renderer_version
            and current.timeline_id == timeline_id
            and current.character_instance_id is None
            and _locator_without_refresh_key(dict(current.source_locator_json or {}))
            == locator
            and dict(current.visibility_json or {}) == visibility
        ):
            return current
    return None


def _copy_reprojection_embeddings(
    session: Session,
    *,
    generation_id: UUID,
    novel_id: UUID,
    refresh_id: UUID,
    source: SemanticSource,
    chunks: tuple[SemanticChunk, ...],
    batch_number_start: int,
) -> int:
    """Create ready local batch evidence by copying existing vectors, with no job."""

    previous = tuple(
        session.execute(
            select(SemanticChunk, SemanticEmbedding)
            .join(
                SemanticEmbedding,
                and_(
                    SemanticEmbedding.chunk_id == SemanticChunk.id,
                    SemanticEmbedding.generation_id == SemanticChunk.generation_id,
                ),
            )
            .where(
                SemanticChunk.generation_id == generation_id,
                SemanticChunk.source_id == source.id,
            )
            .order_by(SemanticChunk.chunk_index)
        ).all()
    )
    previous_by_index = {
        old_chunk.chunk_index: (old_chunk, old_embedding)
        for old_chunk, old_embedding in previous
    }
    if len(previous_by_index) != len(chunks):
        raise EmbeddingLifecycleError(
            "metadata_reprojection_unavailable",
            "current source has no complete reusable embedding set",
        )
    for chunk in chunks:
        pair = previous_by_index.get(chunk.chunk_index)
        if pair is None or (
            pair[0].content_hash != chunk.content_hash
            or pair[0].content_text != chunk.content_text
        ):
            raise EmbeddingLifecycleError(
                "metadata_reprojection_unavailable",
                "current source chunks do not match the new metadata projection",
            )

    completed_at = datetime.now(UTC)
    for offset, chunk in enumerate(chunks):
        old_chunk, old_embedding = previous_by_index[chunk.chunk_index]
        batch = EmbeddingIndexBatch(
            id=uuid4(),
            generation_id=generation_id,
            novel_id=novel_id,
            refresh_id=refresh_id,
            batch_number=batch_number_start + offset,
            background_job_id=None,
            input_hash=_digest([str(chunk.id) + ":" + chunk.content_hash]),
            item_count=1,
            state="ready",
            attempt_count=0,
            result_count=1,
            completed_at=completed_at,
        )
        session.add(batch)
        session.flush()
        session.add(
            EmbeddingIndexBatchItem(
                id=uuid4(),
                batch_id=batch.id,
                generation_id=generation_id,
                chunk_id=chunk.id,
                ordinal=0,
            )
        )
        session.add(
            SemanticEmbedding(
                id=uuid4(),
                generation_id=generation_id,
                chunk_id=chunk.id,
                batch_id=batch.id,
                dimension=old_embedding.dimension,
                embedding=list(old_embedding.embedding),
                embedding_hash=old_embedding.embedding_hash,
                model_run_id=old_embedding.model_run_id,
                response_ordinal=0,
            )
        )
    session.flush()
    return len(chunks)


def build_generation_chunker(session: Session, generation_id: UUID) -> str:
    generation = session.get(EmbeddingGeneration, generation_id)
    if generation is None:
        raise EmbeddingLifecycleError("generation_not_found", "generation is missing")
    return generation.chunker_version


def _manuscript_sources(
    session: Session, *, build: EmbeddingGenerationNovel
) -> tuple[
    list[
        tuple[
            V1SourceInput,
            UUID | None,
            int | None,
            int | None,
            int | None,
            int | None,
            dict[str, object],
        ]
    ],
    int,
]:
    timelines = tuple(
        session.scalars(
            select(StoryTimeline).where(
                StoryTimeline.novel_id == build.novel_id,
                StoryTimeline.lifecycle_state == "active",
            )
        )
    )
    single_timeline_id = timelines[0].id if len(timelines) == 1 else None
    canonical_documents = tuple(
        session.scalars(
            select(Document)
            .outerjoin(
                Volume,
                and_(
                    Volume.id == Document.volume_id,
                    Volume.novel_id == Document.novel_id,
                ),
            )
            .where(
                Document.novel_id == build.novel_id,
                Document.kind == "chapter",
            )
            .order_by(
                case((Document.volume_id.is_(None), 1), else_=0),
                Volume.position,
                Document.position,
                Document.id,
            )
        )
    )
    narrative_by_document_id = {
        document.id: ordinal
        for ordinal, document in enumerate(canonical_documents, start=1)
    }
    rows = session.execute(
        select(Document, DocumentRevision)
        .join(DocumentWorkingCopy, DocumentWorkingCopy.document_id == Document.id)
        .join(DocumentRevision, DocumentRevision.id == DocumentWorkingCopy.base_revision_id)
        .outerjoin(
            Volume,
            and_(
                Volume.id == Document.volume_id,
                Volume.novel_id == Document.novel_id,
            ),
        )
        .where(Document.novel_id == build.novel_id, Document.kind == "chapter")
        .order_by(
            case((Document.volume_id.is_(None), 1), else_=0),
            Volume.position,
            Document.position,
            Document.id,
        )
    ).all()
    results: list[
        tuple[
            V1SourceInput,
            UUID | None,
            int | None,
            int | None,
            int | None,
            int | None,
            dict[str, object],
        ]
    ] = []
    unmapped = 0
    for document, revision in sorted(
        rows,
        key=lambda item: narrative_by_document_id.get(item[0].id, 2**63 - 1),
    ):
        narrative_sequence = narrative_by_document_id.get(document.id)
        if narrative_sequence is None:
            continue
        if not revision.content_text.strip():
            continue
        if len(timelines) <= 1:
            results.append(
                (
                    V1SourceInput(
                        corpus="manuscript", source_type="chapter_revision",
                        source_entity_id=document.id, source_revision_id=revision.id,
                        title=embedding_chapter_title(document.title),
                        content=revision.content_text,
                    ),
                    single_timeline_id,
                    narrative_sequence,
                    narrative_sequence,
                    narrative_sequence,
                    narrative_sequence,
                    {"document_id": str(document.id), "revision_id": str(revision.id)},
                )
            )
            continue
        head = session.get(RevisionTimelineMappingHead, revision.id)
        if head is None or head.source_content_hash != revision.content_hash:
            unmapped += 1
            continue
        segments = tuple(
            session.scalars(
                select(RevisionTimelineMappingSegment)
                .where(
                    RevisionTimelineMappingSegment.mapping_revision_id
                    == head.current_mapping_revision_id
                )
                .order_by(RevisionTimelineMappingSegment.ordinal)
            )
        )
        for segment in segments:
            excerpt = revision.content_text[segment.source_start : segment.source_end]
            if not excerpt.strip():
                unmapped += 1
                continue
            results.append(
                (
                    V1SourceInput(
                        corpus="manuscript", source_type="chapter_revision",
                        source_entity_id=document.id, source_revision_id=revision.id,
                        title=(
                            f"{embedding_chapter_title(document.title)}"
                            f"·片段{segment.ordinal + 1}"
                        ),
                        content=excerpt,
                    ),
                    segment.timeline_id,
                    narrative_sequence,
                    narrative_sequence,
                    segment.story_sequence,
                    segment.story_sequence,
                    {
                        "document_id": str(document.id), "revision_id": str(revision.id),
                        "mapping_revision_id": str(head.current_mapping_revision_id),
                        "source_start": segment.source_start, "source_end": segment.source_end,
                    },
                )
            )
    return results, unmapped


def prepare_v1_novel_index(
    session: Session,
    *,
    generation_id: UUID,
    novel_id: UUID,
) -> EmbeddingGenerationNovel:
    """Build local sources/chunks and enqueue batches; never calls the cloud."""

    build = session.scalar(
        select(EmbeddingGenerationNovel)
        .where(
            EmbeddingGenerationNovel.generation_id == generation_id,
            EmbeddingGenerationNovel.novel_id == novel_id,
        )
        .with_for_update()
    )
    if build is None:
        raise EmbeddingLifecycleError("generation_novel_not_found", "generation novel is missing")
    generation = session.get(EmbeddingGeneration, generation_id)
    active_refresh = generation is not None and generation.state == "active"
    if build.state != "pending" and not (
        active_refresh and build.state in {"ready", "outdated", "partial_failed"}
    ):
        return build
    if generation is None or generation.state not in {"draft", "building", "active"}:
        raise EmbeddingLifecycleError("generation_state_invalid", "generation cannot be built")
    target = frozenset(build.target_corpora_json) & V1_CORPORA
    sources: list[
        tuple[
            V1SourceInput,
            UUID | None,
            int | None,
            int | None,
            int | None,
            int | None,
            dict[str, object],
            dict[str, object],
        ]
    ] = []
    failures = 0
    if "manuscript" in target:
        manuscript, failures = _manuscript_sources(session, build=build)
        sources.extend((*item, {"visibility": "public"}) for item in manuscript)
    if "planning" in target:
        outline_head = session.get(NovelOutlineHead, novel_id)
        if outline_head is not None:
            revision = session.get(NovelOutlineRevision, outline_head.current_revision_id)
            if revision is not None:
                body = "\n\n".join(
                    part for part in (
                        revision.background_text, revision.plot_text, revision.highlight_text
                    ) if part.strip()
                )
                if body:
                    sources.append((
                        V1SourceInput(
                            corpus="planning", source_type="outline_revision",
                            source_entity_id=novel_id, source_revision_id=revision.id,
                            title="正式大纲", content=body,
                        ), None, None, None, None, None,
                        {"outline_revision_id": str(revision.id)},
                        {"visibility": "author_only"},
                    ))
        setting_head = session.get(NovelSettingHead, novel_id)
        if setting_head is not None:
            revision = session.get(NovelSettingRevision, setting_head.current_revision_id)
            if revision is not None:
                sources.append((
                    V1SourceInput(
                        corpus="planning", source_type="setting_revision",
                        source_entity_id=novel_id, source_revision_id=revision.id,
                        title="正式故事设定",
                        content=render_structured_setting(revision.settings_json),
                    ), None, None, None, None, None,
                    {"setting_revision_id": str(revision.id)},
                    {"visibility": "author_only"},
                ))
    if "private_asset" in target:
        binding_rows = session.execute(
            select(NovelAssetBinding, PrivateAssetVersion)
            .join(PrivateAssetVersion, PrivateAssetVersion.id == NovelAssetBinding.asset_version_id)
            .where(
                NovelAssetBinding.novel_id == novel_id,
                NovelAssetBinding.lifecycle_state == "active",
                NovelAssetBinding.usage_policy != "prohibited",
            )
            .order_by(NovelAssetBinding.position, NovelAssetBinding.id)
        ).all()
        for binding, version in binding_rows:
            sources.append((
                V1SourceInput(
                    corpus="private_asset", source_type="private_asset_version",
                    source_entity_id=binding.asset_id, source_revision_id=version.id,
                    title=version.title, content=version.content,
                    usage_policy=binding.usage_policy,
                ), None, None, None, None, None,
                {"binding_id": str(binding.id), "asset_version_id": str(version.id)},
                {"visibility": "author_only"},
            ))
    authority_digest = _digest([
            {
                "corpus": item[0].corpus,
                "source_type": item[0].source_type,
                "source_entity_id": str(item[0].source_entity_id),
                "source_revision_id": str(item[0].source_revision_id) if item[0].source_revision_id else None,
                "title": item[0].title,
                "content": item[0].content,
                "timeline_id": str(item[1]) if item[1] else None,
                "narrative": [item[2], item[3]],
                "story": [item[4], item[5]],
                "locator": item[6],
            }
            for item in sources
        ])
    build.authority_digest = authority_digest
    if active_refresh:
        if build.state == "pending":
            build.state = "outdated"
            build.sync_state = "outdated"
        refresh_service = service_for_session(session)
        current_max_batch_number = session.scalar(
            select(func.coalesce(func.max(EmbeddingIndexBatch.batch_number), -1)).where(
                EmbeddingIndexBatch.generation_id == generation_id,
                EmbeddingIndexBatch.novel_id == novel_id,
            )
        )
        next_batch_number = int(
            current_max_batch_number
            if current_max_batch_number is not None
            else -1
        ) + 1
        created_refreshes = 0
        desired_logical_keys: set[str] = set()
        current_sources = tuple(
            session.scalars(
                select(SemanticSource)
                .where(
                    SemanticSource.generation_id == generation_id,
                    SemanticSource.novel_id == novel_id,
                    SemanticSource.status == "current",
                )
                .with_for_update()
            )
        )
        current_by_logical_key: dict[str, list[SemanticSource]] = {}
        for current_source in current_sources:
            current_key = str(
                current_source.source_locator_json.get("_refresh_logical_key")
                or _logical_source_key(
                    source_type=current_source.source_type,
                    source_entity_id=current_source.source_entity_id,
                    timeline_id=current_source.timeline_id,
                    locator=current_source.source_locator_json,
                )
            )
            current_by_logical_key.setdefault(current_key, []).append(current_source)
        for (
            source_input, timeline_id, narrative_start, narrative_end,
            story_start, story_end, locator, visibility,
        ) in sources:
            rendered = render_v1_source(
                source_input,
                renderer_version=build_generation_renderer(session, generation_id),
            )
            logical_key = _logical_source_key(
                source_type=source_input.source_type,
                source_entity_id=source_input.source_entity_id,
                timeline_id=timeline_id,
                locator=locator,
            )
            desired_logical_keys.add(logical_key)
            candidates = tuple(current_by_logical_key.get(logical_key, ()))
            if any(
                _same_source_projection(
                    current,
                    rendered=rendered,
                    source_input=source_input,
                    timeline_id=timeline_id,
                    narrative_start=narrative_start,
                    narrative_end=narrative_end,
                    story_start=story_start,
                    story_end=story_end,
                    locator=locator,
                    visibility=visibility,
                )
                for current in candidates
            ):
                continue
            reusable_source = _metadata_only_reprojection_source(
                candidates,
                rendered=rendered,
                source_input=source_input,
                timeline_id=timeline_id,
                locator=locator,
                visibility=visibility,
            )
            request_locator = dict(locator)
            if reusable_source is not None:
                # A canonical order may move A → B → A.  Include the
                # publication base version so a later immutable A projection
                # does not collide with a historical, already-published refresh
                # digest, while retries in the same transaction stay idempotent.
                request_locator["_metadata_projection_base_index_version"] = (
                    build.index_version
                )
            requested = refresh_service.request(RefreshRequest(
                generation_id=generation_id,
                novel_id=novel_id,
                novel_authority_digest=authority_digest,
                source=PendingSourceSpec(
                    corpus=rendered.corpus,
                    source_type=rendered.source_type,
                    source_entity_id=rendered.source_entity_id,
                    source_revision_id=rendered.source_revision_id,
                    content_hash=rendered.content_hash,
                    renderer_version=rendered.renderer_version,
                    logical_key=logical_key,
                    source_locator=request_locator,
                    visibility=visibility,
                    timeline_id=timeline_id,
                    narrative_sequence_start=narrative_start,
                    narrative_sequence_end=narrative_end,
                    story_sequence_start=story_start,
                    story_sequence_end=story_end,
                ),
            ))
            if not requested.created:
                continue
            chunks = _persist_chunks_for_rendered(
                session,
                generation_id=generation_id,
                source_id=requested.pending_source_id,
                rendered=rendered,
                chunker_version=generation.chunker_version,
            )
            if reusable_source is not None:
                added = _copy_reprojection_embeddings(
                    session,
                    generation_id=generation_id,
                    novel_id=novel_id,
                    refresh_id=requested.refresh_id,
                    source=reusable_source,
                    chunks=chunks,
                    batch_number_start=next_batch_number,
                )
                next_batch_number += added
                refresh_service.mark_queued(requested.refresh_id)
                refresh_service.mark_building(requested.refresh_id)
                refresh_service.mark_ready(requested.refresh_id)
                for current in candidates:
                    current.status = "retired"
                consent_active = bool(
                    session.scalar(
                        select(func.count())
                        .select_from(NovelEmbeddingConsent)
                        .where(
                            NovelEmbeddingConsent.id == build.consent_id,
                            NovelEmbeddingConsent.novel_id == novel_id,
                            NovelEmbeddingConsent.revoked_at.is_(None),
                        )
                    )
                )
                published = refresh_service.publish(
                    requested.refresh_id,
                    PublicationAuthority(
                        novel_authority_digest=authority_digest,
                        source_revision_id=rendered.source_revision_id,
                        content_hash=rendered.content_hash,
                        consent_active=consent_active,
                        source_in_scope=True,
                    ),
                )
                if not published.published:
                    for current in candidates:
                        current.status = "current"
                    raise EmbeddingLifecycleError(
                        published.code or "metadata_reprojection_failed",
                        "metadata-only semantic projection could not be published",
                    )
                continue
            added = _enqueue_chunk_batches(
                session,
                generation_id=generation_id,
                novel_id=novel_id,
                chunks=chunks,
                batch_number_start=next_batch_number,
                idempotency_prefix=f"embedding-refresh:{requested.request_digest}",
                refresh_id=requested.refresh_id,
            )
            next_batch_number += added
            refresh_service.mark_queued(requested.refresh_id)
            created_refreshes += 1
        retired_removed_sources = 0
        for current_source in session.scalars(
            select(SemanticSource)
            .where(
                SemanticSource.generation_id == generation_id,
                SemanticSource.novel_id == novel_id,
                SemanticSource.status == "current",
            )
            .with_for_update()
        ):
            current_logical_key = str(
                current_source.source_locator_json.get("_refresh_logical_key")
                or _logical_source_key(
                    source_type=current_source.source_type,
                    source_entity_id=current_source.source_entity_id,
                    timeline_id=current_source.timeline_id,
                    locator=current_source.source_locator_json,
                )
            )
            if current_logical_key not in desired_logical_keys:
                current_source.status = "retired"
                retired_removed_sources += 1
        if retired_removed_sources:
            build.index_version += 1
        build.failure_count = failures
        if failures:
            build.sync_state = "partial_failed"
            build.failure_code = "TIMELINE_MAPPING_REQUIRED"
        elif created_refreshes == 0:
            build.sync_state = "current"
            build.state = "ready"
            build.last_refresh_at = func.now()
            build.published_digest = authority_digest
            current_source_ids = tuple(
                session.scalars(
                    select(SemanticSource.id).where(
                        SemanticSource.generation_id == generation_id,
                        SemanticSource.novel_id == novel_id,
                        SemanticSource.status == "current",
                    )
                )
            )
            build.source_count = len(current_source_ids)
            if current_source_ids:
                current_chunk_ids = tuple(
                    session.scalars(
                        select(SemanticChunk.id).where(
                            SemanticChunk.source_id.in_(current_source_ids)
                        )
                    )
                )
                build.chunk_count = len(current_chunk_ids)
                build.embedded_count = int(
                    session.scalar(
                        select(func.count()).select_from(SemanticEmbedding).where(
                            SemanticEmbedding.generation_id == generation_id,
                            SemanticEmbedding.chunk_id.in_(current_chunk_ids),
                        )
                    )
                    or 0
                ) if current_chunk_ids else 0
            else:
                build.chunk_count = 0
                build.embedded_count = 0
        session.flush()
        return build

    persisted_chunks: list[SemanticChunk] = []
    for (
        source_input,
        timeline_id,
        narrative_start,
        narrative_end,
        story_start,
        story_end,
        locator,
        visibility,
    ) in sources:
        _, records = _persist_source(
            session, build=build, source_input=source_input, timeline_id=timeline_id,
            narrative_start=narrative_start,
            narrative_end=narrative_end,
            story_start=story_start,
            story_end=story_end,
            locator=locator,
            visibility=visibility,
        )
        persisted_chunks.extend(records)
    batches = _batch_chunks(persisted_chunks)
    scope = LocalWorkspaceScope.fixed_local()
    if (build.owner_id, build.workspace_id) != (scope.owner_id, scope.workspace_id):
        raise EmbeddingLifecycleError("scope_violation", "generation is outside fixed local scope")
    for number, items in enumerate(batches):
        input_hash = _digest([str(item.id) + ":" + item.content_hash for item in items])
        batch = EmbeddingIndexBatch(
            id=uuid4(), generation_id=generation_id, novel_id=novel_id,
            batch_number=number, input_hash=input_hash, item_count=len(items),
            state="pending", attempt_count=0, result_count=0,
        )
        session.add(batch)
        session.flush()
        for ordinal, item in enumerate(items):
            session.add(
                EmbeddingIndexBatchItem(
                    id=uuid4(), batch_id=batch.id, generation_id=generation_id,
                    chunk_id=item.id, ordinal=ordinal,
                )
            )
        job = enqueue_job(
            session, scope=scope, job_kind="embedding.index_batch",
            input_hash=input_hash,
            idempotency_key=f"embedding:{generation_id}:{novel_id}:{number}",
            resource_class="dashscope-embedding", novel_id=novel_id,
            max_attempts=3,
        )
        batch.background_job_id = job.job_id
        batch.state = "queued"
    build.source_count = len(sources)
    build.chunk_count = len(persisted_chunks)
    build.failure_count = failures
    if failures:
        build.state = "failed"
        build.failure_code = "TIMELINE_MAPPING_REQUIRED"
    elif batches:
        build.state = "building"
    else:
        build.state = "ready"
        build.sync_state = "current"
        build.published_digest = build.authority_digest
    generation.state = "failed" if failures else ("building" if batches else "ready")
    session.flush()
    return build


def request_active_novel_refresh(session: Session, novel_id: UUID) -> bool:
    """Queue the current authority projection after a formal write.

    The caller owns the surrounding authority transaction.  This helper does
    no cloud I/O and returns ``False`` when the novel is not configured for an
    active semantic index.
    """

    novel = session.get(Novel, novel_id)
    if novel is None:
        return False
    configuration = session.scalar(
        select(EmbeddingConfiguration).where(
            EmbeddingConfiguration.owner_id == novel.owner_id,
            EmbeddingConfiguration.workspace_id == novel.workspace_id,
        )
    )
    if configuration is None or configuration.active_generation_id is None:
        return False
    consent = session.scalar(
        select(NovelEmbeddingConsent).where(
            NovelEmbeddingConsent.novel_id == novel_id,
            NovelEmbeddingConsent.revoked_at.is_(None),
        )
    )
    if consent is None:
        return False
    build = session.scalar(
        select(EmbeddingGenerationNovel).where(
            EmbeddingGenerationNovel.generation_id == configuration.active_generation_id,
            EmbeddingGenerationNovel.novel_id == novel_id,
        )
    )
    if build is None:
        return False
    prepare_v1_novel_index(
        session,
        generation_id=configuration.active_generation_id,
        novel_id=novel_id,
    )
    return True
