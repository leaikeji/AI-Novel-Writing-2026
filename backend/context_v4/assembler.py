"""Pure deterministic Context V4 assembly.

The module accepts immutable DTOs only.  It has no persistence, network,
clock, environment or model-runtime dependency.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from uuid import UUID

from ..story_state import (
    LifecycleState,
    StoryFactV2,
    StoryTimelineRecord,
    project_story_facts,
    resolve_timeline,
    validate_inheritance_dag,
)
from ..story_state.contracts import VisibilityScope

from .contracts import (
    CONTEXT_SECTION_ORDER,
    SINGLE_TIMELINE_MAPPING_VERSION,
    ChapterTimelineContextV3,
    ContextAssemblyError,
    ContextAssemblyErrorCode,
    ContextBlockV2,
    ContextBudgetResultV1,
    ContextBudgetResultV2,
    ContextBudgetV1,
    ContextBudgetV2,
    ContextConflictV2,
    ContextDiagnosticsV2,
    ContextOmissionV2,
    ContextRequirement,
    NovelContextAssemblySnapshotV4,
    NovelContextEnvelopeV4,
    OmissionCode,
    PerspectiveKind,
    PositionDomain,
    RetrievalPurpose,
    StoryPositionV3,
    TimelineMappingKind,
    WRITING_CONTEXT_SNAPSHOT_VERSION_V2,
    WritingContextSnapshotV1,
    WritingContextSnapshotV2,
)
from .hashing import canonical_hash


_OMISSION_EXPLANATIONS: dict[OmissionCode, str] = {
    OmissionCode.CROSS_NOVEL: "记录属于其他小说，已按稳定小说 ID 隔离。",
    OmissionCode.NOT_CURRENT: "记录不是当前正式来源或当前固定绑定。",
    OmissionCode.SOURCE_INVALID: "记录来源 revision 未被证明仍然有效。",
    OmissionCode.OUTSIDE_TIMELINE: "记录不在目标时间线的主继承路径中。",
    OmissionCode.AFTER_NARRATIVE_CUTOFF: "正文来源晚于当前检索用途允许的章节截止点。",
    OmissionCode.AFTER_STORY_CUTOFF: "故事状态或知识晚于明确的世界事件截止点。",
    OmissionCode.NOT_VISIBLE: "记录不属于当前读者或人物观察者的知识范围。",
    OmissionCode.SUPERSEDED_OR_INVALID: "故事事实已失效、被替代或不是当前状态。",
    OmissionCode.AMBIGUOUS: "故事事实缺少可比较位置或有效来源依据。",
    OmissionCode.PROHIBITED: "上下文策略明确禁止使用该完整块。",
    OmissionCode.BUDGET_OMITTED: "完整逻辑块无法放入真实模型输入预算，未做静默截断。",
    OmissionCode.SELECTION_CAP_OMITTED: "候选超过版本化选择上限，已保留更接近当前写作位置的记录。",
}


@dataclass(slots=True)
class _OmissionAccumulator:
    count: int = 0
    source_ids: set[UUID] = field(default_factory=set)
    block_ids: set[UUID] = field(default_factory=set)
    estimated_tokens: int = 0


@dataclass(frozen=True, slots=True)
class ResolvedContextScope:
    """Pure, comparable scope shared by selection and final assembly."""

    timeline: StoryTimelineRecord
    position: StoryPositionV3
    mapping_kind: TimelineMappingKind
    mapping_version: str
    inheritance_path: tuple[UUID, ...]
    story_limits: Mapping[UUID, int]


def _add_omission(
    omissions: dict[OmissionCode, _OmissionAccumulator],
    code: OmissionCode,
    *,
    source_id: UUID,
    block_id: UUID | None = None,
    estimated_tokens: int = 0,
) -> None:
    item = omissions.setdefault(code, _OmissionAccumulator())
    item.count += 1
    item.source_ids.add(source_id)
    if block_id is not None:
        item.block_ids.add(block_id)
    item.estimated_tokens += estimated_tokens


def _omission_records(
    omissions: Mapping[OmissionCode, _OmissionAccumulator],
) -> tuple[ContextOmissionV2, ...]:
    return tuple(
        ContextOmissionV2(
            code=code,
            count=item.count,
            source_ids=tuple(sorted(item.source_ids, key=str)),
            block_ids=tuple(sorted(item.block_ids, key=str)),
            estimated_token_count=item.estimated_tokens,
            explanation=_OMISSION_EXPLANATIONS[code],
        )
        for code in OmissionCode
        if (item := omissions.get(code)) is not None
    )


def _resolve_position(
    snapshot: NovelContextAssemblySnapshotV4,
) -> tuple[StoryTimelineRecord, StoryPositionV3, TimelineMappingKind, str]:
    active = [
        timeline
        for timeline in snapshot.timelines
        if timeline.novel_id == snapshot.novel_id
        and timeline.lifecycle_state is LifecycleState.ACTIVE
    ]
    position = snapshot.position
    if len(active) > 1 and (
        position.timeline_id is None
        or position.story_sequence_cutoff is None
        or position.timeline_mapping_version is None
    ):
        missing = []
        if position.timeline_id is None:
            missing.append("timeline_id")
        if position.story_sequence_cutoff is None:
            missing.append("story_sequence_cutoff")
        if position.timeline_mapping_version is None:
            missing.append("timeline_mapping_version")
        raise ContextAssemblyError(
            ContextAssemblyErrorCode.TIMELINE_MAPPING_REQUIRED,
            "multi-timeline context requires an explicit comparable timeline mapping",
            details={
                "missing_fields": missing,
                "timeline_ids": [str(item.id) for item in active],
            },
        )

    resolved = resolve_timeline(
        snapshot.timelines,
        snapshot.novel_id,
        position.timeline_id,
    )
    if position.story_sequence_cutoff is None:
        cutoff = position.narrative_sequence
        mapping_kind = TimelineMappingKind.SINGLE_TIMELINE_IDENTITY
        mapping_version = SINGLE_TIMELINE_MAPPING_VERSION
    elif (
        len(active) == 1
        and position.story_sequence_cutoff == position.narrative_sequence
        and position.timeline_mapping_version
        in {None, SINGLE_TIMELINE_MAPPING_VERSION}
    ):
        cutoff = position.story_sequence_cutoff
        mapping_kind = TimelineMappingKind.SINGLE_TIMELINE_IDENTITY
        mapping_version = SINGLE_TIMELINE_MAPPING_VERSION
    else:
        if position.timeline_mapping_version is None:
            raise ContextAssemblyError(
                ContextAssemblyErrorCode.TIMELINE_MAPPING_REQUIRED,
                "non-identity story cutoff requires an explicit mapping version",
                details={"missing_fields": ["timeline_mapping_version"]},
            )
        cutoff = position.story_sequence_cutoff
        mapping_kind = TimelineMappingKind.EXPLICIT
        mapping_version = position.timeline_mapping_version

    return (
        resolved,
        StoryPositionV3(
            timeline_id=resolved.id,
            narrative_sequence=position.narrative_sequence,
            story_sequence_cutoff=cutoff,
            timeline_mapping_version=mapping_version,
            chapter_id=position.chapter_id,
            document_revision_id=position.document_revision_id,
        ),
        mapping_kind,
        mapping_version,
    )


def _timeline_limits(
    timelines: Sequence[StoryTimelineRecord],
    *,
    novel_id: UUID,
    timeline_id: UUID,
    story_cutoff: int,
) -> tuple[tuple[UUID, ...], dict[UUID, int]]:
    by_id = {item.id: item for item in timelines if item.novel_id == novel_id}
    current = by_id[timeline_id]
    target_to_root: list[UUID] = []
    limits: dict[UUID, int] = {}
    current_limit = story_cutoff
    while True:
        target_to_root.append(current.id)
        limits[current.id] = current_limit
        if current.parent_timeline_id is None:
            break
        if current.fork_story_sequence is None:
            raise ValueError("inherited timeline has no fork story sequence")
        current_limit = min(current_limit, current.fork_story_sequence)
        current = by_id[current.parent_timeline_id]
    return tuple(reversed(target_to_root)), limits


def resolve_context_scope(
    snapshot: NovelContextAssemblySnapshotV4,
) -> ResolvedContextScope:
    """Resolve exactly the scope rules used by :func:`assemble_novel_context`.

    Database adapters call this before selecting source IDs so they cannot
    drift from the pure assembler's timeline and cutoff semantics.
    """

    validate_inheritance_dag(snapshot.timelines, snapshot.novel_id)
    resolved, position, mapping_kind, mapping_version = _resolve_position(snapshot)
    assert position.story_sequence_cutoff is not None
    inheritance_path, story_limits = _timeline_limits(
        snapshot.timelines,
        novel_id=snapshot.novel_id,
        timeline_id=resolved.id,
        story_cutoff=position.story_sequence_cutoff,
    )
    return ResolvedContextScope(
        timeline=resolved,
        position=position,
        mapping_kind=mapping_kind,
        mapping_version=mapping_version,
        inheritance_path=inheritance_path,
        story_limits=story_limits,
    )


def _visible(
    visibility: object,
    *,
    perspective_kind: PerspectiveKind,
    observer_instance_id: UUID | None,
    story_cutoff: int,
) -> bool:
    if perspective_kind is PerspectiveKind.AUTHOR:
        return True
    if (
        visibility.revealed_at_sequence is not None
        and visibility.revealed_at_sequence > story_cutoff
    ):
        return False
    if visibility.scope is VisibilityScope.ALL:
        return True
    if perspective_kind is PerspectiveKind.READER:
        return visibility.scope is VisibilityScope.READER
    return (
        visibility.scope is VisibilityScope.CHARACTER_INSTANCES
        and observer_instance_id in visibility.character_instance_ids
    )


def _fact_inputs(
    snapshot: NovelContextAssemblySnapshotV4,
    *,
    story_cutoff: int,
    omissions: dict[OmissionCode, _OmissionAccumulator],
) -> list[StoryFactV2]:
    result: list[StoryFactV2] = []
    for fact in snapshot.facts:
        if fact.novel_id != snapshot.novel_id:
            _add_omission(omissions, OmissionCode.CROSS_NOVEL, source_id=fact.id)
            continue
        if not _visible(
            fact.visibility_json,
            perspective_kind=snapshot.perspective.kind,
            observer_instance_id=snapshot.perspective.observer_character_instance_id,
            story_cutoff=story_cutoff,
        ):
            _add_omission(omissions, OmissionCode.NOT_VISIBLE, source_id=fact.id)
            continue
        result.append(fact)
    return result


def _narrative_allows(
    purpose: RetrievalPurpose,
    source_sequence: int,
    target_sequence: int,
) -> bool:
    if purpose in {RetrievalPurpose.CHAPTER_BODY, RetrievalPurpose.CHAPTER_OUTLINE}:
        return source_sequence < target_sequence
    # Review and selection contexts may use the loader's bounded four-before /
    # four-after evidence window.  The persistence selector, not an unbounded
    # pure snapshot scan, owns that versioned adjacency policy.
    return True


def _eligible_blocks(
    snapshot: NovelContextAssemblySnapshotV4,
    *,
    position: StoryPositionV3,
    inheritance_path: tuple[UUID, ...],
    story_limits: Mapping[UUID, int],
    omissions: dict[OmissionCode, _OmissionAccumulator],
) -> list[ContextBlockV2]:
    result: list[ContextBlockV2] = []
    inherited = set(inheritance_path)
    story_cutoff = position.story_sequence_cutoff
    assert story_cutoff is not None
    for block in snapshot.blocks:
        omission: OmissionCode | None = None
        if block.novel_id != snapshot.novel_id:
            omission = OmissionCode.CROSS_NOVEL
        elif not block.is_current_source:
            omission = OmissionCode.NOT_CURRENT
        elif not block.source_is_valid:
            omission = OmissionCode.SOURCE_INVALID
        elif block.requirement is ContextRequirement.PROHIBITED:
            omission = OmissionCode.PROHIBITED
        elif block.timeline_id is not None and block.timeline_id not in inherited:
            omission = OmissionCode.OUTSIDE_TIMELINE
        elif not _visible(
            block.visibility,
            perspective_kind=snapshot.perspective.kind,
            observer_instance_id=snapshot.perspective.observer_character_instance_id,
            story_cutoff=story_cutoff,
        ):
            omission = OmissionCode.NOT_VISIBLE
        elif block.position_domain is PositionDomain.NARRATIVE:
            assert block.narrative_sequence is not None
            if not _narrative_allows(
                snapshot.purpose,
                block.narrative_sequence,
                position.narrative_sequence,
            ):
                omission = OmissionCode.AFTER_NARRATIVE_CUTOFF
        elif block.position_domain is PositionDomain.STORY:
            assert block.timeline_id is not None and block.story_sequence is not None
            if block.story_sequence > story_limits[block.timeline_id]:
                omission = OmissionCode.AFTER_STORY_CUTOFF
        if omission is not None:
            _add_omission(
                omissions,
                omission,
                source_id=block.source_id,
                block_id=block.block_id,
                estimated_tokens=block.estimated_token_count,
            )
            continue
        result.append(block)
    return result


_SECTION_ORDER = {section: index for index, section in enumerate(CONTEXT_SECTION_ORDER)}
_REQUIREMENT_ORDER = {
    ContextRequirement.REQUIRED: 0,
    ContextRequirement.EXPLICIT: 1,
    ContextRequirement.PREFERRED: 2,
    ContextRequirement.CONTEXT_ONLY: 3,
    ContextRequirement.PROHIBITED: 4,
}


def _block_order(block: ContextBlockV2) -> tuple[int, int, int, str]:
    return (
        _SECTION_ORDER[block.section],
        _REQUIREMENT_ORDER[block.requirement],
        block.priority,
        str(block.block_id),
    )


def _apply_budget(
    snapshot: NovelContextAssemblySnapshotV4,
    blocks: Sequence[ContextBlockV2],
    omissions: dict[OmissionCode, _OmissionAccumulator],
) -> tuple[
    tuple[ContextBlockV2, ...],
    ContextBudgetResultV1 | ContextBudgetResultV2,
]:
    budget = snapshot.budget
    hard = budget.hard_input_token_budget
    mandatory = [block for block in blocks if block.requirement.mandatory]
    mandatory_tokens = sum(block.estimated_token_count for block in mandatory)
    forced_total = budget.fixed_overhead_tokens + mandatory_tokens
    if forced_total > hard:
        raise ContextAssemblyError(
            ContextAssemblyErrorCode.CONTEXT_OVERFLOW,
            "required context exceeds the effective model input budget",
            details={
                **(
                    {"actual_model_id": budget.actual_model_id}
                    if isinstance(budget, ContextBudgetV1)
                    else {
                        "requested_provider_id": budget.requested_provider_id,
                        "requested_model_id": budget.requested_model_id,
                        "budget_provider_id": budget.budget_provider_id,
                        "budget_model_id": budget.budget_model_id,
                    }
                ),
                "hard_input_token_budget": hard,
                "fixed_overhead_tokens": budget.fixed_overhead_tokens,
                "mandatory_block_tokens": mandatory_tokens,
                "overflow_tokens": forced_total - hard,
                "mandatory_block_ids": [
                    str(item.block_id) for item in sorted(mandatory, key=_block_order)
                ],
            },
        )

    included = list(sorted(mandatory, key=_block_order))
    consumed = forced_total
    omitted_tokens = 0
    optional = sorted(
        (block for block in blocks if not block.requirement.mandatory),
        key=_block_order,
    )
    for block in optional:
        if consumed + block.estimated_token_count <= hard:
            included.append(block)
            consumed += block.estimated_token_count
            continue
        omitted_tokens += block.estimated_token_count
        _add_omission(
            omissions,
            OmissionCode.BUDGET_OMITTED,
            source_id=block.source_id,
            block_id=block.block_id,
            estimated_tokens=block.estimated_token_count,
        )
    included.sort(key=_block_order)
    included_tokens = sum(block.estimated_token_count for block in included)
    common_result = {
        "effective_context_window_tokens": budget.effective_context_window_tokens,
        "reserved_output_tokens": budget.reserved_output_tokens,
        "reserved_prompt_tokens": budget.reserved_prompt_tokens,
        "hard_input_token_budget": hard,
        "fixed_overhead_tokens": budget.fixed_overhead_tokens,
        "included_block_tokens": included_tokens,
        "omitted_block_tokens": omitted_tokens,
        "remaining_tokens": hard - budget.fixed_overhead_tokens - included_tokens,
        "estimator_version": budget.estimator_version,
    }
    if isinstance(budget, ContextBudgetV2):
        result: ContextBudgetResultV1 | ContextBudgetResultV2 = ContextBudgetResultV2(
            requested_provider_id=budget.requested_provider_id,
            requested_model_id=budget.requested_model_id,
            budget_provider_id=budget.budget_provider_id,
            budget_model_id=budget.budget_model_id,
            **common_result,
        )
    else:
        result = ContextBudgetResultV1(
            actual_model_id=budget.actual_model_id,
            **common_result,
        )
    return tuple(included), result


def _fact_omissions(
    facts: Sequence[StoryFactV2],
    *,
    projection: object,
    story_limits: Mapping[UUID, int],
    source_validity: Mapping[UUID, bool],
    omissions: dict[OmissionCode, _OmissionAccumulator],
) -> None:
    by_id = {fact.id: fact for fact in facts}
    ambiguous = set(projection.ambiguous_fact_ids)
    suppressed = set(projection.suppressed_fact_ids)
    for fact_id in ambiguous:
        fact = by_id.get(fact_id)
        invalid = (
            fact is not None
            and fact.source_revision_id is not None
            and source_validity.get(fact.source_revision_id) is not True
        )
        _add_omission(
            omissions,
            OmissionCode.SOURCE_INVALID if invalid else OmissionCode.AMBIGUOUS,
            source_id=fact_id,
        )
    for fact_id in suppressed:
        fact = by_id.get(fact_id)
        future = (
            fact is not None
            and fact.timeline_id in story_limits
            and fact.story_sequence is not None
            and fact.story_sequence > story_limits[fact.timeline_id]
        )
        _add_omission(
            omissions,
            OmissionCode.AFTER_STORY_CUTOFF if future else OmissionCode.SUPERSEDED_OR_INVALID,
            source_id=fact_id,
        )
    accounted = {
        *(fact.id for fact in projection.visible_facts),
        *projection.ambiguous_fact_ids,
        *projection.suppressed_fact_ids,
    }
    for fact in facts:
        if fact.id not in accounted:
            _add_omission(
                omissions,
                OmissionCode.OUTSIDE_TIMELINE,
                source_id=fact.id,
            )


def assemble_novel_context(
    snapshot: NovelContextAssemblySnapshotV4,
) -> NovelContextEnvelopeV4:
    """Assemble one V4 envelope without reads, writes or external calls."""

    omissions: dict[OmissionCode, _OmissionAccumulator] = defaultdict(
        _OmissionAccumulator
    )
    scope = resolve_context_scope(snapshot)
    resolved = scope.timeline
    position = scope.position
    mapping_kind = scope.mapping_kind
    mapping_version = scope.mapping_version
    inheritance_path = scope.inheritance_path
    story_limits = scope.story_limits
    assert position.story_sequence_cutoff is not None
    fact_inputs = _fact_inputs(
        snapshot,
        story_cutoff=position.story_sequence_cutoff,
        omissions=omissions,
    )
    projection = project_story_facts(
        snapshot.novel_id,
        resolved.id,
        narrative_cutoff=position.story_sequence_cutoff,
        timelines=snapshot.timelines,
        facts=fact_inputs,
        event_links=snapshot.event_links,
        source_revision_validity=snapshot.source_revision_validity,
    )
    if (
        snapshot.max_final_story_facts is not None
        and len(projection.visible_facts) > snapshot.max_final_story_facts
    ):
        raise ContextAssemblyError(
            ContextAssemblyErrorCode.CONTEXT_SELECTION_INCOMPLETE,
            "visible story facts exceed the proven final selection boundary",
            details={
                "resource": "story_facts",
                "candidate_count": len(fact_inputs),
                "selected_count": len(projection.visible_facts),
                "cap": snapshot.max_final_story_facts,
            },
        )
    _fact_omissions(
        fact_inputs,
        projection=projection,
        story_limits=story_limits,
        source_validity=snapshot.source_revision_validity,
        omissions=omissions,
    )
    eligible = _eligible_blocks(
        snapshot,
        position=position,
        inheritance_path=inheritance_path,
        story_limits=story_limits,
        omissions=omissions,
    )
    included, budget = _apply_budget(snapshot, eligible, omissions)
    return NovelContextEnvelopeV4(
        novel_id=snapshot.novel_id,
        purpose=snapshot.purpose,
        position=position,
        perspective=snapshot.perspective,
        chapter_timeline=ChapterTimelineContextV3(
            timeline_id=resolved.id,
            timeline_key=resolved.timeline_key,
            narrative_sequence=position.narrative_sequence,
            story_sequence_cutoff=position.story_sequence_cutoff,
            mapping_kind=mapping_kind,
            mapping_version=mapping_version,
            inheritance_path=inheritance_path,
        ),
        current_story_facts=projection.current_facts,
        visible_story_facts=projection.visible_facts,
        included_blocks=included,
        diagnostics=ContextDiagnosticsV2(
            omissions=(*snapshot.preselection_omissions, *_omission_records(omissions)),
            conflicts=tuple(
                ContextConflictV2(
                    conflict_key=item.conflict_key,
                    fact_ids=item.fact_ids,
                    reason=item.reason,
                )
                for item in projection.conflicts
            ),
            ambiguous_fact_ids=projection.ambiguous_fact_ids,
            suppressed_fact_ids=projection.suppressed_fact_ids,
            mapping_version=mapping_version,
        ),
        budget=budget,
    )


def freeze_writing_context(
    envelope: NovelContextEnvelopeV4,
    *,
    requested_model_id: str,
    actual_model_id: str,
    context_policy_version: str,
) -> WritingContextSnapshotV1:
    """Freeze the exact assembled envelope and its deterministic digest."""

    if not isinstance(envelope.budget, ContextBudgetResultV1):
        raise ValueError("V1 freeze requires a V1 context budget")
    if actual_model_id != envelope.budget.actual_model_id:
        raise ValueError("actual model differs from the model used for context budgeting")
    requested = requested_model_id.strip()
    actual = actual_model_id.strip()
    policy = context_policy_version.strip()
    hash_payload = {
        "novel_id": envelope.novel_id,
        "purpose": envelope.purpose,
        "requested_model_id": requested,
        "actual_model_id": actual,
        "context_policy_version": policy,
        "envelope": envelope,
    }
    return WritingContextSnapshotV1(
        novel_id=envelope.novel_id,
        purpose=envelope.purpose,
        requested_model_id=requested,
        actual_model_id=actual,
        context_policy_version=policy,
        envelope=envelope,
        assembly_hash=canonical_hash(hash_payload),
    )


def freeze_writing_context_v2(
    envelope: NovelContextEnvelopeV4,
    *,
    context_policy_version: str,
) -> WritingContextSnapshotV2:
    """Freeze pre-call identities without requiring an actual model value."""

    budget = envelope.budget
    if not isinstance(budget, ContextBudgetResultV2):
        raise ValueError("V2 freeze requires a V2 context budget")
    policy = context_policy_version.strip()
    if not policy:
        raise ValueError("context_policy_version cannot be blank")
    hash_payload = {
        "schema_version": WRITING_CONTEXT_SNAPSHOT_VERSION_V2,
        "novel_id": envelope.novel_id,
        "purpose": envelope.purpose,
        "requested_provider_id": budget.requested_provider_id,
        "requested_model_id": budget.requested_model_id,
        "budget_provider_id": budget.budget_provider_id,
        "budget_model_id": budget.budget_model_id,
        "effective_context_window_tokens": budget.effective_context_window_tokens,
        "context_policy_version": policy,
        "envelope": envelope,
    }
    return WritingContextSnapshotV2(
        novel_id=envelope.novel_id,
        purpose=envelope.purpose,
        requested_provider_id=budget.requested_provider_id,
        requested_model_id=budget.requested_model_id,
        budget_provider_id=budget.budget_provider_id,
        budget_model_id=budget.budget_model_id,
        effective_context_window_tokens=budget.effective_context_window_tokens,
        context_policy_version=policy,
        envelope=envelope,
        assembly_hash=canonical_hash(hash_payload),
    )
