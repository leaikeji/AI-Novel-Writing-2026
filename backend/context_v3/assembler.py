"""Pure, deterministic assembly for ``NovelContextEnvelopeV3``.

The assembler accepts an already-loaded immutable snapshot.  It has no
SQLAlchemy dependency, callback, network client, or mutation hook.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from uuid import UUID

from ..story_state import (
    StoryFactType,
    StoryFactV2,
    StoryTimeV1,
    StoryTimelineRecord,
    project_story_facts,
    resolve_timeline,
    validate_inheritance_dag,
)
from ..story_state.contracts import VisibilityScope

from .contracts import (
    AgeProjectionV1,
    CONTEXT_SECTION_ORDER,
    AuthorSecretConstraintV1,
    BoundPrivateAssetRecordV1,
    ChapterRoleConstraintsV3,
    ChapterTimelineContextV2,
    CharacterContextRecordV2,
    CharacterContextV2,
    CharacterRefV2,
    ContextAssemblyError,
    ContextAssemblyErrorCode,
    ContextAuthority,
    ContextConflictV1,
    ContextDiagnosticsV1,
    ContextOmissionV1,
    ContextSourceV1,
    ContextTextBlockV1,
    FormalPlanningRecordV1,
    NovelContextAssemblySnapshotV3,
    NovelContextEnvelopeV3,
    OmissionCode,
    PerspectiveKind,
    PrivateAssetPolicy,
    SemanticContextEvidenceV1,
    SemanticEvidenceRecordV1,
    StoryStateContextV1,
)


_OMISSION_EXPLANATIONS: dict[OmissionCode, str] = {
    OmissionCode.CROSS_NOVEL: "记录属于其他小说，已按小说稳定 ID 隔离。",
    OmissionCode.NOT_CURRENT: "记录不是当前正式来源或固定绑定，未进入上下文。",
    OmissionCode.OUTSIDE_TIMELINE: "记录不在目标时间线的主继承路径上。",
    OmissionCode.AFTER_CUTOFF: "记录晚于目标叙事截止点或分支继承锚点。",
    OmissionCode.NOT_VISIBLE: "记录不属于当前观察者的知识可见范围。",
    OmissionCode.SOURCE_INVALID: "记录来源 revision 未被证明仍然有效。",
    OmissionCode.AMBIGUOUS: "记录缺少可比较位置或来源依据，未作为当前状态使用。",
    OmissionCode.SUPERSEDED_OR_INVALID: "记录已失效、被替代或不是当前状态。",
    OmissionCode.PROHIBITED: "素材绑定策略明确禁止进入生成上下文。",
    OmissionCode.AUTHOR_SECRET_WITHHELD: "作者秘密未向读者或人物观察者披露。",
}


def _is_visible(
    visibility: object,
    *,
    perspective_kind: PerspectiveKind,
    observer_instance_id: UUID | None,
    narrative_cutoff: int | None,
) -> bool:
    scope = visibility.scope
    if perspective_kind is PerspectiveKind.AUTHOR:
        return True
    reveal_sequence = visibility.revealed_at_sequence
    if reveal_sequence is not None and (
        narrative_cutoff is None or reveal_sequence > narrative_cutoff
    ):
        return False
    if scope is VisibilityScope.ALL:
        return True
    if perspective_kind is PerspectiveKind.READER:
        return scope is VisibilityScope.READER
    return (
        scope is VisibilityScope.CHARACTER_INSTANCES
        and observer_instance_id in visibility.character_instance_ids
    )


def _timeline_limits(
    timelines: Sequence[StoryTimelineRecord],
    *,
    novel_id: UUID,
    timeline_id: UUID,
    narrative_cutoff: int | None,
) -> tuple[tuple[UUID, ...], dict[UUID, int | None]]:
    by_id = {item.id: item for item in timelines if item.novel_id == novel_id}
    current = by_id[timeline_id]
    target_to_root: list[UUID] = []
    limits: dict[UUID, int | None] = {}
    current_limit = narrative_cutoff
    while True:
        target_to_root.append(current.id)
        limits[current.id] = current_limit
        if current.parent_timeline_id is None:
            break
        fork_limit = current.fork_story_sequence
        if fork_limit is None:
            # ``resolve_timeline`` and the story-state projector will provide the
            # public domain error.  This guard keeps the helper total in tests.
            raise ValueError("inherited timeline has no fork sequence")
        current_limit = (
            fork_limit if current_limit is None else min(current_limit, fork_limit)
        )
        current = by_id[current.parent_timeline_id]
    return tuple(reversed(target_to_root)), limits


def _present_at(
    record: CharacterContextRecordV2,
    *,
    timeline_id: UUID,
    narrative_cutoff: int | None,
) -> bool:
    if timeline_id not in record.present_on_timeline_ids:
        return False
    if narrative_cutoff is None:
        return record.active_from_sequence is None
    if (
        record.active_from_sequence is not None
        and record.active_from_sequence > narrative_cutoff
    ):
        return False
    return not (
        record.active_to_sequence is not None
        and record.active_to_sequence < narrative_cutoff
    )


def _same_character(left: CharacterRefV2, right: CharacterRefV2) -> bool:
    return (
        left.character_id == right.character_id
        and left.character_instance_id == right.character_instance_id
    )


def _filter_characters(
    snapshot: NovelContextAssemblySnapshotV3,
    timeline_id: UUID,
    omissions: Counter[OmissionCode],
) -> list[CharacterContextRecordV2]:
    result: list[CharacterContextRecordV2] = []
    for record in snapshot.character_records:
        if record.novel_id != snapshot.novel_id:
            omissions[OmissionCode.CROSS_NOVEL] += 1
            continue
        if not _present_at(
            record,
            timeline_id=timeline_id,
            narrative_cutoff=snapshot.position.narrative_sequence,
        ):
            omissions[OmissionCode.OUTSIDE_TIMELINE] += 1
            continue
        result.append(record)
    return result


def _require_stable_character_refs(
    requirements: ChapterRoleConstraintsV3,
    records: Sequence[CharacterContextRecordV2],
) -> None:
    available = {
        (item.ref.character_id, item.ref.character_instance_id) for item in records
    }
    requested = list(requirements.required_characters)
    if requirements.point_of_view is not None:
        requested.append(requirements.point_of_view)
    for ref in requested:
        if (ref.character_id, ref.character_instance_id) not in available:
            raise ContextAssemblyError(
                ContextAssemblyErrorCode.REQUIRED_CHARACTER_UNAVAILABLE,
                "required character instance is unavailable at the target position",
                details={
                    "character_id": str(ref.character_id),
                    "character_instance_id": str(ref.character_instance_id),
                },
            )


def _chapter_requirements(
    snapshot: NovelContextAssemblySnapshotV3,
    character_records: Sequence[CharacterContextRecordV2],
    omissions: Counter[OmissionCode],
) -> ChapterRoleConstraintsV3:
    secrets = list(snapshot.chapter_requirements.author_secret_constraints)
    for record in character_records:
        secrets.extend(record.author_secret_constraints)
    if snapshot.perspective.kind is not PerspectiveKind.AUTHOR:
        if secrets:
            omissions[OmissionCode.AUTHOR_SECRET_WITHHELD] += len(secrets)
        secrets = []
    deduplicated: dict[UUID, AuthorSecretConstraintV1] = {}
    for secret in secrets:
        previous = deduplicated.get(secret.constraint_id)
        if previous is not None and previous != secret:
            raise ValueError("one author-secret constraint ID has conflicting content")
        deduplicated[secret.constraint_id] = secret
    original = snapshot.chapter_requirements
    return ChapterRoleConstraintsV3(
        required_characters=original.required_characters,
        point_of_view=original.point_of_view,
        public_requirements=original.public_requirements,
        prohibited_outcomes=original.prohibited_outcomes,
        author_secret_constraints=tuple(
            deduplicated[key] for key in sorted(deduplicated, key=str)
        ),
        author_secret_facts=(),
    )


def _filter_facts(
    snapshot: NovelContextAssemblySnapshotV3,
    omissions: Counter[OmissionCode],
) -> list[StoryFactV2]:
    result: list[StoryFactV2] = []
    for fact in snapshot.facts:
        if fact.novel_id != snapshot.novel_id:
            omissions[OmissionCode.CROSS_NOVEL] += 1
            continue
        if not _is_visible(
            fact.visibility_json,
            perspective_kind=snapshot.perspective.kind,
            observer_instance_id=snapshot.perspective.observer_character_instance_id,
            narrative_cutoff=snapshot.position.narrative_sequence,
        ):
            omissions[OmissionCode.NOT_VISIBLE] += 1
            continue
        result.append(fact)
    return result


def _planning_blocks(
    records: Sequence[FormalPlanningRecordV1],
    novel_id: UUID,
    *,
    include_author_materials: bool,
    omissions: Counter[OmissionCode],
) -> tuple[ContextTextBlockV1, ...]:
    blocks: list[tuple[int, ContextTextBlockV1]] = []
    kind_order = {"outline": 0, "setting": 1}
    for record in records:
        if record.novel_id != novel_id:
            omissions[OmissionCode.CROSS_NOVEL] += 1
            continue
        if not record.is_current:
            omissions[OmissionCode.NOT_CURRENT] += 1
            continue
        if not include_author_materials:
            omissions[OmissionCode.NOT_VISIBLE] += 1
            continue
        blocks.append(
            (
                kind_order[record.planning_kind.value],
                ContextTextBlockV1(
                    source_id=record.source_id,
                    revision_id=record.revision_id,
                    title=record.title,
                    content=record.content,
                    authority=ContextAuthority.FORMAL,
                ),
            )
        )
    return tuple(
        item
        for _, item in sorted(blocks, key=lambda pair: (pair[0], str(pair[1].source_id)))
    )


def _private_blocks(
    records: Sequence[BoundPrivateAssetRecordV1],
    novel_id: UUID,
    *,
    include_author_materials: bool,
    omissions: Counter[OmissionCode],
) -> tuple[ContextTextBlockV1, ...]:
    blocks: list[ContextTextBlockV1] = []
    for record in records:
        if record.novel_id != novel_id:
            omissions[OmissionCode.CROSS_NOVEL] += 1
            continue
        if not record.is_current_binding:
            omissions[OmissionCode.NOT_CURRENT] += 1
            continue
        if not include_author_materials:
            omissions[OmissionCode.NOT_VISIBLE] += 1
            continue
        if record.policy is PrivateAssetPolicy.PROHIBITED:
            omissions[OmissionCode.PROHIBITED] += 1
            continue
        blocks.append(
            ContextTextBlockV1(
                source_id=record.asset_id,
                revision_id=record.asset_version_id,
                title=record.title,
                content=record.content,
                authority=ContextAuthority.FIXED_PRIVATE,
                policy=record.policy,
            )
        )
    policy_order = {
        PrivateAssetPolicy.REQUIRED: 0,
        PrivateAssetPolicy.PREFERRED: 1,
        PrivateAssetPolicy.CONTEXT_ONLY: 2,
    }
    return tuple(
        sorted(blocks, key=lambda item: (policy_order[item.policy], str(item.source_id)))
    )


def _semantic_evidence(
    records: Sequence[SemanticEvidenceRecordV1],
    *,
    snapshot: NovelContextAssemblySnapshotV3,
    timeline_limits: Mapping[UUID, int | None],
    omissions: Counter[OmissionCode],
) -> tuple[SemanticContextEvidenceV1, ...]:
    result: list[SemanticContextEvidenceV1] = []
    for record in records:
        if record.novel_id != snapshot.novel_id:
            omissions[OmissionCode.CROSS_NOVEL] += 1
            continue
        if not record.is_current_source:
            omissions[OmissionCode.NOT_CURRENT] += 1
            continue
        if record.source_revision_id is not None and (
            snapshot.source_revision_validity.get(record.source_revision_id) is not True
        ):
            omissions[OmissionCode.SOURCE_INVALID] += 1
            continue
        if not _is_visible(
            record.visibility,
            perspective_kind=snapshot.perspective.kind,
            observer_instance_id=snapshot.perspective.observer_character_instance_id,
            narrative_cutoff=snapshot.position.narrative_sequence,
        ):
            omissions[OmissionCode.NOT_VISIBLE] += 1
            continue
        timeline_id = record.timeline_id
        if timeline_id is None:
            limit = snapshot.position.narrative_sequence
        elif timeline_id not in timeline_limits:
            omissions[OmissionCode.OUTSIDE_TIMELINE] += 1
            continue
        else:
            limit = timeline_limits[timeline_id]
        if limit is not None:
            if record.story_sequence is None:
                omissions[OmissionCode.AMBIGUOUS] += 1
                continue
            if record.story_sequence > limit:
                omissions[OmissionCode.AFTER_CUTOFF] += 1
                continue
        result.append(
            SemanticContextEvidenceV1(
                evidence_id=record.evidence_id,
                corpus=record.corpus,
                source_id=record.source_id,
                source_revision_id=record.source_revision_id,
                chunk_id=record.chunk_id,
                content=record.content,
                score=record.score,
                visibility=record.visibility,
            )
        )
    return tuple(
        sorted(
            result,
            key=lambda item: (item.corpus.value, -item.score, str(item.evidence_id)),
        )
    )


def _sources(
    *,
    requirements: ChapterRoleConstraintsV3,
    planning: Sequence[ContextTextBlockV1],
    characters: Sequence[CharacterContextV2],
    facts: Sequence[StoryFactV2],
    private_assets: Sequence[ContextTextBlockV1],
    semantic: Sequence[SemanticContextEvidenceV1],
) -> tuple[ContextSourceV1, ...]:
    sources: list[ContextSourceV1] = []
    sources.extend(
        ContextSourceV1(
            source_kind="author_secret_constraint",
            source_id=item.constraint_id,
            revision_id=item.source_revision_id,
            authority=ContextAuthority.INSTRUCTION,
        )
        for item in requirements.author_secret_constraints
    )
    sources.extend(
        ContextSourceV1(
            source_kind="author_secret_story_fact",
            source_id=item.id,
            revision_id=item.source_revision_id,
            timeline_id=item.timeline_id,
            authority=ContextAuthority.DETERMINISTIC,
        )
        for item in requirements.author_secret_facts
    )
    sources.extend(
        ContextSourceV1(
            source_kind="formal_planning",
            source_id=item.source_id,
            revision_id=item.revision_id,
            authority=ContextAuthority.FORMAL,
        )
        for item in planning
    )
    for character in characters:
        sources.append(
            ContextSourceV1(
                source_kind="character_root",
                source_id=character.ref.character_id,
                revision_id=character.root_revision_id,
                authority=ContextAuthority.FORMAL,
            )
        )
        sources.append(
            ContextSourceV1(
                source_kind="character_instance",
                source_id=character.ref.character_instance_id,
                revision_id=character.instance_revision_id,
                authority=ContextAuthority.FORMAL,
            )
        )
    sources.extend(
        ContextSourceV1(
            source_kind="story_fact",
            source_id=fact.id,
            revision_id=fact.source_revision_id,
            timeline_id=fact.timeline_id,
            authority=ContextAuthority.DETERMINISTIC,
        )
        for fact in facts
    )
    sources.extend(
        ContextSourceV1(
            source_kind="private_asset",
            source_id=item.source_id,
            revision_id=item.revision_id,
            authority=ContextAuthority.FIXED_PRIVATE,
        )
        for item in private_assets
    )
    sources.extend(
        ContextSourceV1(
            source_kind=f"semantic:{item.corpus.value}",
            source_id=item.source_id,
            revision_id=item.source_revision_id,
            authority=ContextAuthority.SUPPLEMENTAL,
        )
        for item in semantic
    )
    unique: dict[tuple[object, ...], ContextSourceV1] = {}
    for source in sources:
        key = (
            source.source_kind,
            source.source_id,
            source.revision_id,
            source.timeline_id,
            source.authority,
        )
        unique[key] = source
    return tuple(unique.values())


def _omission_records(
    omissions: Counter[OmissionCode],
) -> tuple[ContextOmissionV1, ...]:
    return tuple(
        ContextOmissionV1(
            code=code,
            count=omissions[code],
            explanation=_OMISSION_EXPLANATIONS[code],
        )
        for code in OmissionCode
        if omissions[code]
    )


def _age_projection(
    record: CharacterContextRecordV2,
    story_time: StoryTimeV1 | None,
) -> AgeProjectionV1:
    if record.birth_year is None:
        return AgeProjectionV1(
            birth_calendar_id=record.birth_calendar_id,
            as_of_story_time=story_time,
            reason="missing_birth_year",
        )
    if (
        story_time is None
        or story_time.lower_bound is None
        or story_time.upper_bound is None
    ):
        return AgeProjectionV1(
            birth_year=record.birth_year,
            birth_calendar_id=record.birth_calendar_id,
            as_of_story_time=story_time,
            reason="missing_story_time_bounds",
        )
    if (
        record.birth_calendar_id is not None
        and story_time.calendar_id is not None
        and record.birth_calendar_id != story_time.calendar_id
    ):
        return AgeProjectionV1(
            birth_year=record.birth_year,
            birth_calendar_id=record.birth_calendar_id,
            as_of_story_time=story_time,
            reason="calendar_mismatch",
        )
    minimum_age = story_time.lower_bound - record.birth_year - 1
    maximum_age = story_time.upper_bound - record.birth_year
    if maximum_age < 0:
        return AgeProjectionV1(
            birth_year=record.birth_year,
            birth_calendar_id=record.birth_calendar_id,
            as_of_story_time=story_time,
            reason="before_birth",
        )
    return AgeProjectionV1(
        birth_year=record.birth_year,
        birth_calendar_id=record.birth_calendar_id or story_time.calendar_id,
        as_of_story_time=story_time,
        minimum_age=max(0, minimum_age),
        maximum_age=maximum_age,
        precision="range",
        reason="year_only_birth",
    )


def assemble_novel_context(
    snapshot: NovelContextAssemblySnapshotV3,
) -> NovelContextEnvelopeV3:
    """Build one read-only V3 envelope from explicit, stable-ID snapshots."""

    omissions: Counter[OmissionCode] = Counter()
    resolved_timeline = resolve_timeline(
        snapshot.timelines, snapshot.novel_id, snapshot.position.timeline_id
    )
    validate_inheritance_dag(snapshot.timelines, snapshot.novel_id)
    inheritance_path, timeline_limits = _timeline_limits(
        snapshot.timelines,
        novel_id=snapshot.novel_id,
        timeline_id=resolved_timeline.id,
        narrative_cutoff=snapshot.position.narrative_sequence,
    )
    character_records = _filter_characters(snapshot, resolved_timeline.id, omissions)
    _require_stable_character_refs(snapshot.chapter_requirements, character_records)
    if snapshot.perspective.kind is PerspectiveKind.CHARACTER:
        observer_id = snapshot.perspective.observer_character_instance_id
        if not any(item.ref.character_instance_id == observer_id for item in character_records):
            raise ContextAssemblyError(
                ContextAssemblyErrorCode.OBSERVER_UNAVAILABLE,
                "observer character instance is unavailable at the target position",
                details={"character_instance_id": str(observer_id)},
            )

    requirements = _chapter_requirements(snapshot, character_records, omissions)
    perspective_facts = _filter_facts(snapshot, omissions)
    projection = project_story_facts(
        snapshot.novel_id,
        resolved_timeline.id,
        narrative_cutoff=snapshot.position.narrative_sequence,
        timelines=snapshot.timelines,
        facts=perspective_facts,
        event_links=snapshot.event_links,
        source_revision_validity=snapshot.source_revision_validity,
    )
    source_invalid_fact_ids = {
        fact.id
        for fact in perspective_facts
        if fact.source_revision_id is not None
        and snapshot.source_revision_validity.get(fact.source_revision_id) is not True
    }
    ambiguous_fact_ids = set(projection.ambiguous_fact_ids)
    omissions[OmissionCode.SOURCE_INVALID] += len(
        ambiguous_fact_ids & source_invalid_fact_ids
    )
    omissions[OmissionCode.AMBIGUOUS] += len(
        ambiguous_fact_ids - source_invalid_fact_ids
    )
    future_fact_ids = {
        fact.id
        for fact in perspective_facts
        if fact.timeline_id in timeline_limits
        and timeline_limits[fact.timeline_id] is not None
        and fact.story_sequence is not None
        and fact.story_sequence > timeline_limits[fact.timeline_id]
    }
    suppressed_fact_ids = set(projection.suppressed_fact_ids)
    omissions[OmissionCode.AFTER_CUTOFF] += len(
        suppressed_fact_ids & future_fact_ids
    )
    omissions[OmissionCode.SUPERSEDED_OR_INVALID] += len(
        suppressed_fact_ids - future_fact_ids
    )
    projected_ids = {
        *(item.id for item in projection.visible_facts),
        *projection.ambiguous_fact_ids,
        *projection.suppressed_fact_ids,
    }
    outside_timeline_count = sum(
        1 for item in perspective_facts if item.id not in projected_ids
    )
    if outside_timeline_count:
        omissions[OmissionCode.OUTSIDE_TIMELINE] += outside_timeline_count

    current_character_facts: dict[UUID, list[StoryFactV2]] = {}
    current_story_facts: list[StoryFactV2] = []
    author_secret_facts: list[StoryFactV2] = []
    for fact in projection.current_facts:
        if (
            snapshot.perspective.kind is PerspectiveKind.AUTHOR
            and fact.visibility_json.scope is VisibilityScope.AUTHOR
        ):
            author_secret_facts.append(fact)
            continue
        if fact.fact_type is StoryFactType.CHARACTER_STATE:
            current_character_facts.setdefault(fact.character_instance_id, []).append(fact)
        else:
            current_story_facts.append(fact)

    requirements = ChapterRoleConstraintsV3(
        required_characters=requirements.required_characters,
        point_of_view=requirements.point_of_view,
        public_requirements=requirements.public_requirements,
        prohibited_outcomes=requirements.prohibited_outcomes,
        author_secret_constraints=requirements.author_secret_constraints,
        author_secret_facts=tuple(author_secret_facts),
    )

    required_order = {
        item.character_instance_id: index
        for index, item in enumerate(requirements.required_characters)
    }
    character_context = tuple(
        CharacterContextV2(
            ref=record.ref,
            root_revision_id=record.root_revision_id,
            instance_revision_id=record.instance_revision_id,
            public_profile=record.public_profile,
            age_projection=_age_projection(record, snapshot.position.story_time),
            current_state_facts=tuple(
                current_character_facts.get(record.ref.character_instance_id, ())
            ),
        )
        for record in sorted(
            character_records,
            key=lambda item: (
                required_order.get(item.ref.character_instance_id, len(required_order)),
                str(item.ref.character_instance_id),
            ),
        )
    )
    author_view = snapshot.perspective.kind is PerspectiveKind.AUTHOR
    planning = _planning_blocks(
        snapshot.formal_planning,
        snapshot.novel_id,
        include_author_materials=author_view,
        omissions=omissions,
    )
    private_assets = _private_blocks(
        snapshot.private_assets,
        snapshot.novel_id,
        include_author_materials=author_view,
        omissions=omissions,
    )
    semantic = _semantic_evidence(
        snapshot.semantic_evidence,
        snapshot=snapshot,
        timeline_limits=timeline_limits,
        omissions=omissions,
    )
    diagnostics = ContextDiagnosticsV1(
        sources=_sources(
            requirements=requirements,
            planning=planning,
            characters=character_context,
            # Visible projection facts include every side of a conflict and
            # therefore preserve the complete deterministic evidence trail.
            facts=projection.visible_facts,
            private_assets=private_assets,
            semantic=semantic,
        ),
        conflicts=tuple(
            ContextConflictV1(
                conflict_key=item.conflict_key,
                fact_ids=item.fact_ids,
                reason=item.reason,
            )
            for item in projection.conflicts
        ),
        omissions=_omission_records(omissions),
        ambiguous_fact_ids=projection.ambiguous_fact_ids,
        suppressed_fact_ids=projection.suppressed_fact_ids,
    )
    return NovelContextEnvelopeV3(
        novel_id=snapshot.novel_id,
        chapter_timeline=ChapterTimelineContextV2(
            timeline_id=resolved_timeline.id,
            timeline_key=resolved_timeline.timeline_key,
            narrative_sequence=snapshot.position.narrative_sequence,
            story_time=snapshot.position.story_time,
            perspective=snapshot.perspective,
            inheritance_path=inheritance_path,
        ),
        chapter_requirements=requirements,
        formal_planning=planning,
        character_state=character_context,
        story_state=StoryStateContextV1(current_facts=tuple(current_story_facts)),
        private_assets=private_assets,
        semantic_evidence=semantic,
        diagnostics=diagnostics,
        section_order=CONTEXT_SECTION_ORDER,
    )
