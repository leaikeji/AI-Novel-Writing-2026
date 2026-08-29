from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

import pytest

from backend.embedding.chunking import (
    V1_CHUNKER_VERSION,
    V1SourceInput,
    batch_chunks,
    chunk_text,
    render_v1_source,
)
from backend.embedding.lifecycle import (
    ConsentSnapshot,
    EmbeddingLifecycleError,
    GenerationState,
    NovelBuildState,
    activate_candidate,
    revoke_consent,
)
from backend.embedding.search import (
    Candidate,
    SearchScope,
    derive_known_visibility_keys,
    filter_candidates,
    reciprocal_rank_fusion,
)
from backend.story_state.contracts import (
    KnowledgeEventDetailsV1,
    StoryFactStatus,
    StoryFactType,
    StoryFactV2,
    StoryVisibilityV1,
    VisibilityScope,
)


def test_v1_renderer_and_chunker_are_stable_and_lossless() -> None:
    source = V1SourceInput(
        corpus="manuscript",
        source_type="chapter_revision",
        source_entity_id=uuid4(),
        source_revision_id=uuid4(),
        title="第一章",
        content=("甲" * 400) + "\r\n" + ("乙" * 400),
    )
    first = render_v1_source(source)
    second = render_v1_source(source)
    assert first == second
    chunks = chunk_text(first.text, max_characters=256, overlap_characters=32)
    assert chunks[-1].source_end == len(first.text)
    assert all(first.text[item.source_start:item.source_end] == item.text for item in chunks)
    assert batch_chunks(chunks, batch_size=10)


def test_default_chunker_limits_high_density_novel_text() -> None:
    chunks = chunk_text("潮" * 1_500)

    assert V1_CHUNKER_VERSION == "semantic-char-chunker/4"
    assert len(chunks) == 7
    assert all(len(chunk.text) <= 256 for chunk in chunks)
    assert chunks[1].source_start == chunks[0].source_end - 32

    punctuation_boundary = chunk_text(("潮" * 256) + "。" + ("汐" * 300))
    assert all(len(chunk.text) <= 256 for chunk in punctuation_boundary)


def test_private_asset_must_be_fixed_and_indexable() -> None:
    source = V1SourceInput(
        corpus="private_asset",
        source_type="private_asset_version",
        source_entity_id=uuid4(),
        source_revision_id=uuid4(),
        title="秘密",
        content="只能在绑定后索引",
        usage_policy="prohibited",
    )
    with pytest.raises(ValueError, match="indexable"):
        render_v1_source(source)


def _candidate(*, novel_id, timeline_id, start=1, visibility="public", status="current"):
    return Candidate(
        chunk_id=uuid4(), novel_id=novel_id, corpus="manuscript",
        source_id=uuid4(), source_revision_id=uuid4(), source_type="chapter_revision",
        text="evidence", source_status=status, timeline_id=timeline_id,
        character_instance_id=None, narrative_start=start, narrative_end=start,
        visibility_key=visibility,
    )


def test_search_filters_before_fusion_without_cross_scope_leakage() -> None:
    novel = uuid4(); sibling = uuid4(); reachable = uuid4()
    good = _candidate(novel_id=novel, timeline_id=reachable)
    hidden = _candidate(novel_id=novel, timeline_id=reachable, visibility="secret:x")
    future = _candidate(novel_id=novel, timeline_id=reachable, start=99)
    wrong_line = _candidate(novel_id=novel, timeline_id=sibling)
    wrong_novel = _candidate(novel_id=uuid4(), timeline_id=reachable)
    invalid = _candidate(novel_id=novel, timeline_id=reachable, status="invalid")
    scope = SearchScope(
        novel_id=novel, corpora=frozenset({"manuscript"}),
        reachable_timeline_ids=frozenset({reachable}), narrative_sequence=10,
        perspective="reader",
    )
    assert filter_candidates((good, hidden, future, wrong_line, wrong_novel, invalid), scope) == (good,)
    fused = reciprocal_rank_fusion(
        lexical=(good, wrong_line), dense=(good, hidden), scope=scope, top_k=5
    )
    assert len(fused) == 1 and fused[0].channels == ("dense", "lexical")


def _knowledge_fact(
    *,
    novel_id: UUID,
    timeline_id: UUID,
    observer_id: UUID,
    key: str,
    operation: str,
    sequence: int,
    source_revision_id: UUID | None = None,
    status: StoryFactStatus = StoryFactStatus.ACTIVE,
) -> StoryFactV2:
    fact_id = uuid4()
    return StoryFactV2(
        id=fact_id,
        novel_id=novel_id,
        fact_type=StoryFactType.KNOWLEDGE_EVENT,
        subject="observer",
        predicate="knowledge",
        object_text=key,
        details=KnowledgeEventDetailsV1(operation=operation, knowledge_key=key),
        source_revision_id=source_revision_id,
        source_document_id=uuid4() if source_revision_id else None,
        timeline_id=timeline_id,
        character_id=uuid4(),
        character_instance_id=observer_id,
        dimension="knowledge",
        event_kind=operation,
        story_sequence=sequence,
        visibility_json=StoryVisibilityV1(scope=VisibilityScope.AUTHOR),
        event_fingerprint=sha256(str(fact_id).encode()).hexdigest(),
        status=status,
        created_at=datetime(2026, 8, 29, tzinfo=UTC),
    )


def test_knowledge_events_determine_character_visibility_and_forget_revokes() -> None:
    novel = uuid4()
    other_novel = uuid4()
    main = uuid4()
    branch = uuid4()
    sibling = uuid4()
    observer = uuid4()
    valid_revision = uuid4()
    invalid_revision = uuid4()
    events = (
        _knowledge_fact(
            novel_id=novel,
            timeline_id=main,
            observer_id=observer,
            key="secret:forgotten",
            operation="learn",
            sequence=4,
            source_revision_id=valid_revision,
        ),
        _knowledge_fact(
            novel_id=novel,
            timeline_id=branch,
            observer_id=observer,
            key="secret:forgotten",
            operation="forget",
            sequence=7,
        ),
        _knowledge_fact(
            novel_id=novel,
            timeline_id=branch,
            observer_id=observer,
            key="secret:known",
            operation="reveal",
            sequence=6,
        ),
        # Parent history after the branch anchor is not inherited.
        _knowledge_fact(
            novel_id=novel,
            timeline_id=main,
            observer_id=observer,
            key="secret:parent-future",
            operation="learn",
            sequence=6,
        ),
        _knowledge_fact(
            novel_id=novel,
            timeline_id=branch,
            observer_id=observer,
            key="secret:future",
            operation="learn",
            sequence=9,
        ),
        _knowledge_fact(
            novel_id=novel,
            timeline_id=sibling,
            observer_id=observer,
            key="secret:sibling",
            operation="learn",
            sequence=6,
        ),
        _knowledge_fact(
            novel_id=novel,
            timeline_id=branch,
            observer_id=uuid4(),
            key="secret:other-observer",
            operation="learn",
            sequence=6,
        ),
        _knowledge_fact(
            novel_id=other_novel,
            timeline_id=branch,
            observer_id=observer,
            key="secret:other-novel",
            operation="learn",
            sequence=6,
        ),
        _knowledge_fact(
            novel_id=novel,
            timeline_id=branch,
            observer_id=observer,
            key="secret:invalid-source",
            operation="learn",
            sequence=6,
            source_revision_id=invalid_revision,
        ),
        _knowledge_fact(
            novel_id=novel,
            timeline_id=branch,
            observer_id=observer,
            key="secret:invalid-status",
            operation="learn",
            sequence=6,
            status=StoryFactStatus.INVALID,
        ),
    )
    scope = SearchScope(
        novel_id=novel,
        corpora=frozenset({"manuscript", "story_event"}),
        reachable_timeline_ids=frozenset({main, branch}),
        narrative_sequence=7,
        perspective="character_instance",
        observer_character_instance_id=observer,
        timeline_sequence_limits=((main, 5), (branch, 7)),
    )

    known = derive_known_visibility_keys(
        events,
        scope=scope,
        source_revision_validity={valid_revision: True, invalid_revision: False},
    )

    assert known == frozenset({"secret:known"})
    visible = _candidate(
        novel_id=novel,
        timeline_id=branch,
        visibility="secret:known",
    )
    forgotten = _candidate(
        novel_id=novel,
        timeline_id=branch,
        visibility="secret:forgotten",
    )
    scoped = replace(scope, known_visibility_keys=known)
    assert filter_candidates((visible, forgotten), scoped) == (visible,)


def test_candidate_activation_requires_every_current_consent_ready() -> None:
    novel = uuid4(); consent = uuid4(); fingerprint = "a" * 64
    consent_snapshot = ConsentSnapshot(consent, novel, True, "notice/1", ("manuscript",))
    build = NovelBuildState(novel, consent, "ready", fingerprint)
    generation = GenerationState(uuid4(), "ready", fingerprint, 1024, (build,))
    assert activate_candidate(
        candidate=generation, active_consents=(consent_snapshot,),
        expected_dimension=1024, expected_fingerprint=fingerprint,
    ).state == "active"
    with pytest.raises(EmbeddingLifecycleError, match="cohort"):
        activate_candidate(
            candidate=generation,
            active_consents=(consent_snapshot, ConsentSnapshot(uuid4(), uuid4(), True, "notice/1", ("planning",))),
            expected_dimension=1024, expected_fingerprint=fingerprint,
        )


def test_revocation_cancels_new_work_but_does_not_delete_build_records() -> None:
    novel = uuid4()
    build = NovelBuildState(novel, uuid4(), "building", "b" * 64)
    result = revoke_consent((build,), novel_id=novel)
    assert len(result) == 1 and result[0].state == "cancelled"
