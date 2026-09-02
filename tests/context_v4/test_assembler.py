from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from backend.context_v4 import (
    SINGLE_TIMELINE_MAPPING_VERSION,
    ContextAssemblyError,
    ContextAssemblyErrorCode,
    ContextBlockV2,
    ContextBudgetV1,
    ContextRequirement,
    ContextSection,
    NovelContextAssemblySnapshotV4,
    OmissionCode,
    PerspectiveKind,
    PerspectiveV1,
    PositionDomain,
    RetrievalPurpose,
    StoryPositionV3,
    TimelineMappingKind,
    assemble_novel_context,
    freeze_writing_context,
)
from backend.story_state import (
    GeneralFactDetailsV1,
    StoryFactType,
    StoryFactV2,
    StoryTimelineRecord,
    StoryVisibilityV1,
    TimelineKind,
)
from backend.story_state.contracts import VisibilityScope


NOW = datetime(2026, 8, 29, tzinfo=UTC)


def _timeline(
    novel_id: UUID,
    *,
    key: str = "main",
    kind: TimelineKind = TimelineKind.MAIN,
    primary: bool = True,
    parent_id: UUID | None = None,
    fork_sequence: int | None = None,
) -> StoryTimelineRecord:
    return StoryTimelineRecord(
        id=uuid4(),
        novel_id=novel_id,
        timeline_key=key,
        name=key,
        normalized_name=key,
        timeline_kind=kind,
        is_primary=primary,
        parent_timeline_id=parent_id,
        fork_story_sequence=fork_sequence,
        created_at=NOW,
        updated_at=NOW,
    )


def _visibility(
    scope: VisibilityScope = VisibilityScope.ALL,
    *,
    revealed_at: int | None = None,
) -> StoryVisibilityV1:
    return StoryVisibilityV1(scope=scope, revealed_at_sequence=revealed_at)


def _block(
    novel_id: UUID,
    *,
    title: str,
    tokens: int,
    sequence: int | None = None,
    story_sequence: int | None = None,
    timeline_id: UUID | None = None,
    requirement: ContextRequirement = ContextRequirement.PREFERRED,
    priority: int = 100,
    visibility: StoryVisibilityV1 | None = None,
) -> ContextBlockV2:
    if sequence is not None:
        domain = PositionDomain.NARRATIVE
    elif story_sequence is not None:
        domain = PositionDomain.STORY
    else:
        domain = PositionDomain.NONE
    return ContextBlockV2(
        block_id=uuid4(),
        novel_id=novel_id,
        section=(
            ContextSection.MANUSCRIPT
            if domain is PositionDomain.NARRATIVE
            else ContextSection.SEMANTIC_EVIDENCE
        ),
        source_kind="fixture",
        source_id=uuid4(),
        title=title,
        content=f"完整块：{title}",
        estimated_token_count=tokens,
        estimator_version="fixture-estimator/1",
        requirement=requirement,
        priority=priority,
        position_domain=domain,
        timeline_id=timeline_id,
        narrative_sequence=sequence,
        story_sequence=story_sequence,
        visibility=visibility or _visibility(),
    )


def _fact(
    novel_id: UUID,
    timeline_id: UUID,
    *,
    sequence: int,
    label: str,
    visibility: StoryVisibilityV1 | None = None,
) -> StoryFactV2:
    fact_id = uuid4()
    return StoryFactV2(
        id=fact_id,
        novel_id=novel_id,
        fact_type=StoryFactType.GENERAL_FACT,
        subject=label,
        predicate="state",
        object_text=label,
        details=GeneralFactDetailsV1(value=label),
        timeline_id=timeline_id,
        dimension=label,
        event_kind="confirmed",
        story_sequence=sequence,
        visibility_json=visibility or _visibility(),
        event_fingerprint=sha256(str(fact_id).encode()).hexdigest(),
        created_at=NOW,
    )


def _budget(
    *,
    window: int = 200,
    output: int = 20,
    prompt: int = 10,
    overhead: int = 10,
) -> ContextBudgetV1:
    return ContextBudgetV1(
        actual_model_id="writer-model",
        effective_context_window_tokens=window,
        reserved_output_tokens=output,
        reserved_prompt_tokens=prompt,
        fixed_overhead_tokens=overhead,
        estimator_version="fixture-estimator/1",
    )


def _snapshot(
    novel_id: UUID,
    timeline: StoryTimelineRecord,
    *,
    purpose: RetrievalPurpose = RetrievalPurpose.CHAPTER_BODY,
    narrative_sequence: int = 5,
    story_cutoff: int | None = None,
    mapping_version: str | None = None,
    blocks: tuple[ContextBlockV2, ...] = (),
    facts: tuple[StoryFactV2, ...] = (),
    timelines: tuple[StoryTimelineRecord, ...] | None = None,
    budget: ContextBudgetV1 | None = None,
    perspective: PerspectiveV1 | None = None,
) -> NovelContextAssemblySnapshotV4:
    return NovelContextAssemblySnapshotV4(
        novel_id=novel_id,
        purpose=purpose,
        position=StoryPositionV3(
            timeline_id=timeline.id,
            narrative_sequence=narrative_sequence,
            story_sequence_cutoff=story_cutoff,
            timeline_mapping_version=mapping_version,
        ),
        perspective=perspective or PerspectiveV1(kind=PerspectiveKind.AUTHOR),
        budget=budget or _budget(),
        timelines=timelines or (timeline,),
        blocks=blocks,
        facts=facts,
    )


def _omission_codes(envelope) -> set[OmissionCode]:
    return {item.code for item in envelope.diagnostics.omissions}


def test_story_position_is_one_based() -> None:
    with pytest.raises(ValidationError):
        StoryPositionV3(narrative_sequence=0)


def test_single_timeline_defaults_to_versioned_identity_mapping() -> None:
    novel_id = uuid4()
    main = _timeline(novel_id)
    previous = _block(novel_id, title="previous", tokens=20, sequence=4, timeline_id=main.id)

    envelope = assemble_novel_context(_snapshot(novel_id, main, blocks=(previous,)))

    assert envelope.position.story_sequence_cutoff == 5
    assert envelope.position.timeline_mapping_version == SINGLE_TIMELINE_MAPPING_VERSION
    assert envelope.chapter_timeline.mapping_kind is TimelineMappingKind.SINGLE_TIMELINE_IDENTITY
    assert envelope.chapter_timeline.mapping_version == SINGLE_TIMELINE_MAPPING_VERSION
    assert [item.title for item in envelope.included_blocks] == ["previous"]


def test_single_timeline_accepts_the_frozen_identity_version_from_loader() -> None:
    novel_id = uuid4()
    main = _timeline(novel_id)
    envelope = assemble_novel_context(
        _snapshot(
            novel_id,
            main,
            narrative_sequence=5,
            story_cutoff=5,
            mapping_version=SINGLE_TIMELINE_MAPPING_VERSION,
        )
    )

    assert envelope.chapter_timeline.mapping_kind is TimelineMappingKind.SINGLE_TIMELINE_IDENTITY
    assert envelope.chapter_timeline.mapping_version == SINGLE_TIMELINE_MAPPING_VERSION


def test_multi_timeline_without_story_mapping_fails_structurally() -> None:
    novel_id = uuid4()
    main = _timeline(novel_id)
    branch = _timeline(
        novel_id,
        key="branch",
        kind=TimelineKind.BRANCH,
        primary=False,
        parent_id=main.id,
        fork_sequence=2,
    )
    snapshot = _snapshot(
        novel_id,
        branch,
        timelines=(main, branch),
        narrative_sequence=3,
    )

    with pytest.raises(ContextAssemblyError) as captured:
        assemble_novel_context(snapshot)

    assert captured.value.code is ContextAssemblyErrorCode.TIMELINE_MAPPING_REQUIRED
    assert "story_sequence_cutoff" in captured.value.details["missing_fields"]
    assert "timeline_mapping_version" in captured.value.details["missing_fields"]


def test_retrieval_purpose_controls_previous_only_and_current_inclusive() -> None:
    novel_id = uuid4()
    main = _timeline(novel_id)
    previous = _block(novel_id, title="chapter-4", tokens=10, sequence=4, timeline_id=main.id)
    current = _block(novel_id, title="chapter-5", tokens=10, sequence=5, timeline_id=main.id)

    for purpose in (RetrievalPurpose.CHAPTER_BODY, RetrievalPurpose.CHAPTER_OUTLINE):
        envelope = assemble_novel_context(
            _snapshot(novel_id, main, purpose=purpose, blocks=(previous, current))
        )
        assert [item.title for item in envelope.included_blocks] == ["chapter-4"]
        assert OmissionCode.AFTER_NARRATIVE_CUTOFF in _omission_codes(envelope)

    for purpose in (RetrievalPurpose.REVIEW, RetrievalPurpose.SELECTION):
        envelope = assemble_novel_context(
            _snapshot(novel_id, main, purpose=purpose, blocks=(previous, current))
        )
        assert {item.title for item in envelope.included_blocks} == {"chapter-4", "chapter-5"}


def test_story_state_visibility_uses_story_cutoff_while_manuscript_uses_narrative() -> None:
    novel_id = uuid4()
    main = _timeline(novel_id)
    manuscript = _block(
        novel_id,
        title="narrative-9",
        tokens=10,
        sequence=9,
        timeline_id=main.id,
    )
    hidden_block = _block(
        novel_id,
        title="revealed-at-5",
        tokens=10,
        story_sequence=2,
        timeline_id=main.id,
        visibility=_visibility(VisibilityScope.READER, revealed_at=5),
    )
    visible_fact = _fact(novel_id, main.id, sequence=2, label="story-2")
    future_fact = _fact(novel_id, main.id, sequence=4, label="story-4")
    envelope = assemble_novel_context(
        _snapshot(
            novel_id,
            main,
            purpose=RetrievalPurpose.CHAPTER_BODY,
            narrative_sequence=10,
            story_cutoff=3,
            mapping_version="explicit-mapping/1",
            blocks=(manuscript, hidden_block),
            facts=(visible_fact, future_fact),
            perspective=PerspectiveV1(kind=PerspectiveKind.READER),
        )
    )

    assert [item.title for item in envelope.included_blocks] == ["narrative-9"]
    assert [item.id for item in envelope.current_story_facts] == [visible_fact.id]
    assert OmissionCode.NOT_VISIBLE in _omission_codes(envelope)
    assert OmissionCode.AFTER_STORY_CUTOFF in _omission_codes(envelope)


def test_budget_omits_complete_optional_blocks_without_truncation() -> None:
    novel_id = uuid4()
    main = _timeline(novel_id)
    first = _block(novel_id, title="first-complete", tokens=40, priority=1)
    second = _block(novel_id, title="second-complete", tokens=30, priority=2)
    envelope = assemble_novel_context(
        _snapshot(
            novel_id,
            main,
            blocks=(second, first),
            budget=_budget(window=100, output=20, prompt=10, overhead=10),
        )
    )

    assert [item.content for item in envelope.included_blocks] == ["完整块：first-complete"]
    omission = next(
        item for item in envelope.diagnostics.omissions
        if item.code is OmissionCode.BUDGET_OMITTED
    )
    assert omission.block_ids == (second.block_id,)
    assert omission.estimated_token_count == 30
    assert envelope.budget.included_block_tokens == 40
    assert envelope.budget.remaining_tokens == 20


def test_block_content_is_preserved_exactly_and_estimator_drift_is_rejected() -> None:
    novel_id = uuid4()
    main = _timeline(novel_id)
    exact = ContextBlockV2(
        block_id=uuid4(),
        novel_id=novel_id,
        section=ContextSection.FORMAL_PLANNING,
        source_kind="fixture",
        source_id=uuid4(),
        title="exact",
        content="\n  保留首尾空白的完整块  \n",
        estimated_token_count=10,
        estimator_version="fixture-estimator/1",
        visibility=_visibility(),
    )
    envelope = assemble_novel_context(_snapshot(novel_id, main, blocks=(exact,)))
    assert envelope.included_blocks[0].content == exact.content

    drifted = exact.model_copy(
        update={"block_id": uuid4(), "estimator_version": "different-estimator/1"}
    )
    with pytest.raises(ValidationError, match="budget estimator"):
        _snapshot(novel_id, main, blocks=(drifted,))


def test_required_or_explicit_content_over_real_budget_returns_overflow() -> None:
    novel_id = uuid4()
    main = _timeline(novel_id)
    required = _block(
        novel_id,
        title="required",
        tokens=61,
        requirement=ContextRequirement.REQUIRED,
    )

    with pytest.raises(ContextAssemblyError) as captured:
        assemble_novel_context(
            _snapshot(
                novel_id,
                main,
                blocks=(required,),
                budget=_budget(window=100, output=20, prompt=10, overhead=10),
            )
        )

    assert captured.value.code is ContextAssemblyErrorCode.CONTEXT_OVERFLOW
    assert captured.value.details["overflow_tokens"] == 1
    assert captured.value.details["mandatory_block_ids"] == [str(required.block_id)]


def test_production_fact_ceiling_fails_closed_without_truncating_projection() -> None:
    novel_id = uuid4()
    main = _timeline(novel_id)
    facts = tuple(
        _fact(novel_id, main.id, sequence=index + 1, label=f"fact-{index}")
        for index in range(3)
    )
    snapshot = _snapshot(novel_id, main, facts=facts).model_copy(
        update={"max_final_story_facts": 2}
    )

    with pytest.raises(ContextAssemblyError) as captured:
        assemble_novel_context(snapshot)

    assert captured.value.code is ContextAssemblyErrorCode.CONTEXT_SELECTION_INCOMPLETE
    assert captured.value.details == {
        "resource": "story_facts",
        "candidate_count": 3,
        "selected_count": 3,
        "cap": 2,
    }


def test_new_selection_fields_are_additive_for_legacy_snapshot_inputs() -> None:
    novel_id = uuid4()
    main = _timeline(novel_id)
    payload = _snapshot(novel_id, main).model_dump()
    payload.pop("max_final_story_facts")

    restored = NovelContextAssemblySnapshotV4.model_validate(payload)

    assert restored.max_final_story_facts is None
    assert ContextAssemblyErrorCode.CONTEXT_SCOPE_UNRESOLVED.value == "context_scope_unresolved"
    assert (
        ContextAssemblyErrorCode.CONTEXT_SELECTION_INCOMPLETE.value
        == "context_selection_incomplete"
    )


def test_writing_snapshot_hash_is_stable_and_bound_to_budgeted_model() -> None:
    novel_id = uuid4()
    main = _timeline(novel_id)
    envelope = assemble_novel_context(_snapshot(novel_id, main))

    left = freeze_writing_context(
        envelope,
        requested_model_id="writer-requested",
        actual_model_id="writer-model",
        context_policy_version="writing-context/1",
    )
    right = freeze_writing_context(
        envelope,
        requested_model_id="writer-requested",
        actual_model_id="writer-model",
        context_policy_version="writing-context/1",
    )
    assert left.assembly_hash == right.assembly_hash
    assert left.envelope == envelope

    with pytest.raises(ValueError, match="differs"):
        freeze_writing_context(
            envelope,
            requested_model_id="writer-requested",
            actual_model_id="another-model",
            context_policy_version="writing-context/1",
        )
