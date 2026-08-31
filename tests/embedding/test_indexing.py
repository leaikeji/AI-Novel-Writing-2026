from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from backend.creative_data_models import (
    EmbeddingIndexBatch,
    EmbeddingIndexBatchItem,
    SemanticChunk,
    SemanticEmbedding,
    SemanticSource,
    StoryTimeline,
)
from backend.embedding.chunking import V1SourceInput, render_v1_source
from backend.embedding.indexing import (
    _copy_reprojection_embeddings,
    _metadata_only_reprojection_source,
    _manuscript_sources,
    _same_source_projection,
)
from backend.volume_chapter_titles import embedding_chapter_title
from backend.models import Document, DocumentRevision


def _projection() -> tuple[V1SourceInput, object, SemanticSource]:
    generation_id = uuid4()
    novel_id = uuid4()
    document_id = uuid4()
    revision_id = uuid4()
    source_input = V1SourceInput(
        corpus="manuscript",
        source_type="chapter_revision",
        source_entity_id=document_id,
        source_revision_id=revision_id,
        title=embedding_chapter_title(""),
        content="潮声穿过窗户。",
    )
    rendered = render_v1_source(source_input)
    source = SemanticSource(
        id=uuid4(),
        generation_id=generation_id,
        novel_id=novel_id,
        corpus=rendered.corpus,
        source_type=rendered.source_type,
        source_entity_id=document_id,
        source_revision_id=revision_id,
        source_locator_json={"document_id": str(document_id)},
        content_hash=rendered.content_hash,
        renderer_version=rendered.renderer_version,
        timeline_id=None,
        character_instance_id=None,
        narrative_sequence_start=1,
        narrative_sequence_end=1,
        story_sequence_start=1,
        story_sequence_end=1,
        visibility_json={"visibility": "public"},
        status="current",
        source_fingerprint="a" * 64,
    )
    return source_input, rendered, source


def test_metadata_only_candidate_requires_identical_immutable_text() -> None:
    source_input, rendered, source = _projection()
    locator = {"document_id": str(source_input.source_entity_id)}
    visibility = {"visibility": "public"}

    assert _metadata_only_reprojection_source(
        (source,),
        rendered=rendered,
        source_input=source_input,
        timeline_id=None,
        locator=locator,
        visibility=visibility,
    ) is source
    assert _same_source_projection(
        source,
        rendered=rendered,
        source_input=source_input,
        timeline_id=None,
        narrative_start=2,
        narrative_end=2,
        story_start=2,
        story_end=2,
        locator=locator,
        visibility=visibility,
    ) is False

    changed = render_v1_source(
        V1SourceInput(
            corpus="manuscript",
            source_type="chapter_revision",
            source_entity_id=source_input.source_entity_id,
            source_revision_id=source_input.source_revision_id,
            title="潮声",
            content=source_input.content,
        )
    )
    assert _metadata_only_reprojection_source(
        (source,),
        rendered=changed,
        source_input=source_input,
        timeline_id=None,
        locator=locator,
        visibility=visibility,
    ) is None


class _ManuscriptSession:
    def __init__(
        self,
        timeline: StoryTimeline,
        rows: list[tuple[Document, DocumentRevision]],
        canonical_documents: tuple[Document, ...] | None = None,
    ) -> None:
        self.timeline = timeline
        self.rows = rows
        self.canonical_documents = canonical_documents or tuple(
            document for document, _revision in rows
        )

    def scalars(self, _statement: object) -> tuple[object, ...]:
        sql = str(_statement)
        if "story_timelines" in sql:
            return (self.timeline,)
        return self.canonical_documents

    def execute(self, _statement: object) -> SimpleNamespace:
        return SimpleNamespace(all=lambda: self.rows)


def test_manuscript_source_title_is_stable_and_has_no_derived_ordinal() -> None:
    novel_id = uuid4()
    document = Document(
        id=uuid4(),
        novel_id=novel_id,
        kind="chapter",
        title="第十二章 · ",
        position=5_000,
        status="final",
        version=1,
    )
    revision = DocumentRevision(
        id=uuid4(),
        document_id=document.id,
        revision_number=1,
        content_markdown="潮声入夜",
        content_text="潮声入夜",
        content_hash="f" * 64,
        source="manual",
    )
    timeline = StoryTimeline(
        id=uuid4(),
        novel_id=novel_id,
        timeline_key="main",
        name="主线",
        normalized_name="主线",
        timeline_kind="main",
        is_primary=True,
        parent_timeline_id=None,
        fork_anchor_json={},
        lifecycle_state="active",
        position=1,
        version=1,
    )

    sources, failures = _manuscript_sources(
        _ManuscriptSession(timeline, [(document, revision)]),  # type: ignore[arg-type]
        build=SimpleNamespace(novel_id=novel_id),
    )

    assert failures == 0
    assert sources[0][0].title == "章节正文"
    assert "第" not in sources[0][0].title


def test_manuscript_position_counts_canonical_chapter_without_revision() -> None:
    novel_id = uuid4()
    empty_predecessor = Document(
        id=uuid4(),
        novel_id=novel_id,
        kind="chapter",
        title="",
        position=1_000,
        status="draft",
        version=1,
    )
    indexed = Document(
        id=uuid4(),
        novel_id=novel_id,
        kind="chapter",
        title="潮声",
        position=2_000,
        status="final",
        version=1,
    )
    revision = DocumentRevision(
        id=uuid4(),
        document_id=indexed.id,
        revision_number=1,
        content_markdown="潮声入夜",
        content_text="潮声入夜",
        content_hash="1" * 64,
        source="manual",
    )
    timeline = StoryTimeline(
        id=uuid4(),
        novel_id=novel_id,
        timeline_key="main",
        name="主线",
        normalized_name="主线",
        timeline_kind="main",
        is_primary=True,
        parent_timeline_id=None,
        fork_anchor_json={},
        lifecycle_state="active",
        position=1,
        version=1,
    )

    sources, _failures = _manuscript_sources(
        _ManuscriptSession(
            timeline,
            [(indexed, revision)],
            canonical_documents=(empty_predecessor, indexed),
        ),  # type: ignore[arg-type]
        build=SimpleNamespace(novel_id=novel_id),
    )

    assert sources[0][2:6] == (2, 2, 2, 2)


class _CopySession:
    def __init__(self, previous: tuple[SemanticChunk, SemanticEmbedding]) -> None:
        self.previous = previous
        self.added: list[object] = []

    def execute(self, _statement: object) -> SimpleNamespace:
        return SimpleNamespace(all=lambda: [self.previous])

    def add(self, value: object) -> None:
        self.added.append(value)

    def flush(self) -> None:
        return None


def test_metadata_only_copy_creates_ready_local_evidence_without_job() -> None:
    generation_id = uuid4()
    novel_id = uuid4()
    source_id = uuid4()
    content_hash = "b" * 64
    previous_chunk = SemanticChunk(
        id=uuid4(),
        generation_id=generation_id,
        source_id=source_id,
        chunk_index=0,
        source_start=0,
        source_end=8,
        content_text="语料: manuscript\n标题: 章节正文\n\n潮声入夜",
        content_hash=content_hash,
        estimated_token_count=8,
        token_estimator_version="unicode-char-estimate/1",
        chunker_version="semantic-char-chunker/5b",
    )
    previous_embedding = SemanticEmbedding(
        id=uuid4(),
        generation_id=generation_id,
        chunk_id=previous_chunk.id,
        batch_id=uuid4(),
        dimension=2048,
        embedding=[0.125] * 2048,
        embedding_hash="c" * 64,
        model_run_id=uuid4(),
        response_ordinal=0,
    )
    new_chunk = SemanticChunk(
        id=uuid4(),
        generation_id=generation_id,
        source_id=uuid4(),
        chunk_index=0,
        source_start=0,
        source_end=8,
        content_text=previous_chunk.content_text,
        content_hash=content_hash,
        estimated_token_count=8,
        token_estimator_version="unicode-char-estimate/1",
        chunker_version="semantic-char-chunker/5b",
    )
    session = _CopySession((previous_chunk, previous_embedding))
    source = SemanticSource(
        id=source_id,
        generation_id=generation_id,
        novel_id=novel_id,
        corpus="manuscript",
        source_type="chapter_revision",
        source_entity_id=uuid4(),
        source_revision_id=uuid4(),
        source_locator_json={},
        content_hash="d" * 64,
        renderer_version="semantic-v1-renderers/2",
        timeline_id=None,
        character_instance_id=None,
        narrative_sequence_start=1,
        narrative_sequence_end=1,
        story_sequence_start=1,
        story_sequence_end=1,
        visibility_json={"visibility": "public"},
        status="current",
        source_fingerprint="e" * 64,
    )

    copied = _copy_reprojection_embeddings(
        session,  # type: ignore[arg-type]
        generation_id=generation_id,
        novel_id=novel_id,
        refresh_id=uuid4(),
        source=source,
        chunks=(new_chunk,),
        batch_number_start=7,
    )

    assert copied == 1
    batch = next(item for item in session.added if isinstance(item, EmbeddingIndexBatch))
    item = next(item for item in session.added if isinstance(item, EmbeddingIndexBatchItem))
    embedding = next(item for item in session.added if isinstance(item, SemanticEmbedding))
    assert batch.state == "ready"
    assert batch.background_job_id is None
    assert batch.batch_number == 7
    assert item.chunk_id == new_chunk.id
    assert embedding.chunk_id == new_chunk.id
    assert embedding.embedding_hash == previous_embedding.embedding_hash
    assert list(embedding.embedding) == list(previous_embedding.embedding)
