"""Read-only SQLAlchemy adapter for the Context V4 production path."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar
from uuid import UUID, NAMESPACE_URL, uuid5

from sqlalchemy import String, and_, case, cast, func, or_, select
from sqlalchemy.orm import Session

from .context_v4 import (
    SINGLE_TIMELINE_MAPPING_VERSION,
    ContextAssemblyError,
    ContextAssemblyErrorCode,
    ContextBlockV2,
    ContextBudgetV1,
    ContextBudgetV2,
    ContextOmissionV2,
    ContextRequirement,
    ContextSection,
    NovelContextAssemblySnapshotV4,
    OmissionCode,
    PerspectiveKind,
    PerspectiveV1,
    PositionDomain,
    RetrievalPurpose,
    StoryPositionV3,
    assemble_novel_context,
    freeze_writing_context,
    freeze_writing_context_v2,
    resolve_context_scope,
)
from .context_v4.assembler import ResolvedContextScope
from .creative_data_models import (
    CharacterInstance,
    CharacterInstanceRevision,
    NovelCharacterRevision,
    NovelAssetBinding,
    NovelOutlineHead,
    NovelOutlineRevision,
    NovelSettingHead,
    NovelSettingRevision,
    PrivateAssetVersion,
    RevisionTimelineMapping,
    RevisionTimelineMappingHead,
    RevisionTimelineMappingSegment,
    StoryEventLink,
    StoryTimeline,
)
from .embedding.chunking import estimate_token_count
from .embedding.writing import WritingPosition
from .models import (
    ChapterBrief,
    DerivedSourceBinding,
    Document,
    DocumentRevision,
    DocumentWorkingCopy,
    IntelligenceCommitBatch,
    Novel,
    StoryFact,
    Volume,
)
from .story_state import (
    StoryEventLinkRecord,
    StoryFactV2,
    StoryStateError,
    StoryTimelineRecord,
    project_story_facts,
)
from .story_state.contracts import StoryVisibilityV1, VisibilityScope
from .story_state.fact_authority import (
    FactAuthorityRow,
    resolve_fact_authority_rows,
)
from .volume_chapter_titles import context_chapter_title


CONTEXT_POLICY_VERSION = "context-source-policy/1"
TOKEN_ESTIMATOR_VERSION = "unicode-cjk-estimator/1"

MAX_ADJACENT_CHAPTERS = 8
MAX_FACT_CANDIDATES = 512
MAX_FINAL_FACTS = 160
MAX_CHARACTER_INSTANCES = 64
MAX_PRIVATE_ASSETS = 32
MAX_SEMANTIC_HITS = 10
MAX_MANUSCRIPT_EVIDENCE = 20
MAX_CONTEXT_BLOCK_CHARACTERS = 200_000


@dataclass(frozen=True, slots=True)
class _ChapterRevisionRef:
    document_id: UUID
    title: str
    narrative_sequence: int
    revision_id: UUID
    content_hash: str
    markdown_character_count: int | None = None
    text_character_count: int | None = None


@dataclass(frozen=True, slots=True)
class _StoryFactAuthorityCandidate:
    id: UUID
    source_revision_id: UUID | None
    status: str
    story_sequence: int | None


def _selection_incomplete(
    resource: str,
    *,
    cap: int,
    candidate_count: int,
    reason: str,
    **details: Any,
) -> ContextAssemblyError:
    return ContextAssemblyError(
        ContextAssemblyErrorCode.CONTEXT_SELECTION_INCOMPLETE,
        reason,
        details={
            "resource": resource,
            "cap": cap,
            "candidate_count": candidate_count,
            **details,
        },
    )


def _scope_unresolved(reason: str, **details: Any) -> ContextAssemblyError:
    return ContextAssemblyError(
        ContextAssemblyErrorCode.CONTEXT_SCOPE_UNRESOLVED,
        reason,
        details=details,
    )


_StoryFactRowT = TypeVar("_StoryFactRowT", bound=FactAuthorityRow)


def _resolve_story_fact_rows(
    facts: Sequence[_StoryFactRowT],
    bindings: Sequence[DerivedSourceBinding],
    batch_states: Mapping[UUID, str],
    event_links: Sequence[StoryEventLink],
) -> tuple[tuple[_StoryFactRowT, ...], dict[UUID, bool]]:
    """Apply the frozen fact-specific authority resolver before assembly."""

    superseded_fact_ids = {
        link.target_fact_id
        for link in event_links
        if link.link_type == "supersedes"
    }
    results = resolve_fact_authority_rows(
        facts,
        bindings=bindings,
        batch_states=batch_states,
        incoming_superseded_fact_ids=superseded_fact_ids,
    )
    included = [
        fact for fact in facts if results[fact.id].included_in_current_projection
    ]
    source_validity = {
        fact.source_revision_id: True
        for fact in included
        if fact.source_revision_id is not None
    }
    return tuple(included), source_validity


def _load_effective_story_fact_rows(
    session: Session,
    facts: Sequence[_StoryFactRowT],
    event_links: Sequence[StoryEventLink],
) -> tuple[tuple[_StoryFactRowT, ...], dict[UUID, bool]]:
    """Load provenance evidence for ``facts`` and resolve each fact once."""

    fact_ids = tuple(item.id for item in facts)
    binding_rows = (
        tuple(
            session.scalars(
                select(DerivedSourceBinding).where(
                    DerivedSourceBinding.derived_entity_id.in_(fact_ids),
                )
            )
        )
        if fact_ids
        else ()
    )
    batch_ids = tuple(
        sorted(
            {
                binding.commit_batch_id
                for binding in binding_rows
                if binding.commit_batch_id is not None
            },
            key=str,
        )
    )
    batch_states = (
        {
            batch.id: batch.state
            for batch in session.scalars(
                select(IntelligenceCommitBatch).where(
                    IntelligenceCommitBatch.id.in_(batch_ids)
                )
            )
        }
        if batch_ids
        else {}
    )
    return _resolve_story_fact_rows(
        facts,
        binding_rows,
        batch_states,
        event_links,
    )


def _block_id(*parts: object) -> UUID:
    return uuid5(NAMESPACE_URL, "ai-novel-world/context-v4/" + "/".join(map(str, parts)))


def _tokens(value: str) -> int:
    return max(1, estimate_token_count(value))


def _author_visibility() -> StoryVisibilityV1:
    return StoryVisibilityV1(scope=VisibilityScope.AUTHOR)


def _block(
    *,
    novel_id: UUID,
    section: ContextSection,
    source_kind: str,
    source_id: UUID,
    source_revision_id: UUID | None,
    title: str,
    content: str,
    requirement: ContextRequirement = ContextRequirement.PREFERRED,
    priority: int = 100,
    position_domain: PositionDomain = PositionDomain.NONE,
    timeline_id: UUID | None = None,
    narrative_sequence: int | None = None,
    story_sequence: int | None = None,
    block_discriminator: str | None = None,
) -> ContextBlockV2 | None:
    if not content.strip():
        return None
    if len(content) > MAX_CONTEXT_BLOCK_CHARACTERS:
        raise _selection_incomplete(
            "context_blocks",
            cap=MAX_CONTEXT_BLOCK_CHARACTERS,
            candidate_count=1,
            reason="selected source exceeds the bounded context block contract",
            source_kind=source_kind,
            source_id=str(source_id),
            character_count=len(content),
        )
    block_id = _block_id(source_kind, source_id, source_revision_id or "head")
    if block_discriminator is not None:
        block_id = _block_id(
            source_kind,
            source_id,
            source_revision_id or "head",
            block_discriminator,
        )
    return ContextBlockV2(
        block_id=block_id,
        novel_id=novel_id,
        section=section,
        source_kind=source_kind,
        source_id=source_id,
        source_revision_id=source_revision_id,
        title=title or source_kind,
        content=content,
        estimated_token_count=_tokens(content),
        estimator_version=TOKEN_ESTIMATOR_VERSION,
        requirement=requirement,
        priority=priority,
        position_domain=position_domain,
        timeline_id=timeline_id,
        narrative_sequence=narrative_sequence,
        story_sequence=story_sequence,
        visibility=_author_visibility(),
    )


def _planning_blocks(session: Session, novel_id: UUID) -> list[ContextBlockV2]:
    result: list[ContextBlockV2] = []
    outline_head = session.get(NovelOutlineHead, novel_id)
    if outline_head is not None:
        revision = session.get(NovelOutlineRevision, outline_head.current_revision_id)
        if revision is not None:
            content = "\n\n".join(
                item for item in (
                    revision.background_text,
                    revision.plot_text,
                    revision.highlight_text,
                ) if item.strip()
            )
            item = _block(
                novel_id=novel_id, section=ContextSection.FORMAL_PLANNING,
                source_kind="outline_revision", source_id=novel_id,
                source_revision_id=revision.id, title="正式大纲", content=content,
                priority=10,
            )
            if item is not None:
                result.append(item)
    setting_head = session.get(NovelSettingHead, novel_id)
    if setting_head is not None:
        revision = session.get(NovelSettingRevision, setting_head.current_revision_id)
        if revision is not None:
            item = _block(
                novel_id=novel_id, section=ContextSection.FORMAL_PLANNING,
                source_kind="setting_revision", source_id=novel_id,
                source_revision_id=revision.id, title="正式故事设定",
                content=json.dumps(revision.settings_json, ensure_ascii=False, sort_keys=True),
                priority=20,
            )
            if item is not None:
                result.append(item)
    return result


def _character_blocks(
    session: Session,
    novel_id: UUID,
    *,
    timeline_id: UUID,
) -> list[ContextBlockV2]:
    instance_ids = tuple(
        session.scalars(
            select(CharacterInstance.id)
            .where(
                CharacterInstance.novel_id == novel_id,
                CharacterInstance.origin_timeline_id == timeline_id,
                CharacterInstance.lifecycle_state == "active",
            )
            .order_by(CharacterInstance.id)
            .limit(MAX_CHARACTER_INSTANCES + 1)
        )
    )
    if len(instance_ids) > MAX_CHARACTER_INSTANCES:
        raise _selection_incomplete(
            "character_instances",
            cap=MAX_CHARACTER_INSTANCES,
            candidate_count=len(instance_ids),
            reason="active character instances exceed the proven selection boundary",
            timeline_id=str(timeline_id),
        )
    if not instance_ids:
        return []

    instances = tuple(
        session.scalars(
            select(CharacterInstance)
            .where(
                CharacterInstance.novel_id == novel_id,
                CharacterInstance.id.in_(instance_ids),
            )
            .order_by(CharacterInstance.id)
        )
    )
    if {item.id for item in instances} != set(instance_ids):
        raise _selection_incomplete(
            "character_instances",
            cap=MAX_CHARACTER_INSTANCES,
            candidate_count=len(instance_ids),
            reason="selected character instances changed before hydration",
            timeline_id=str(timeline_id),
        )

    character_ids = tuple(sorted({item.character_id for item in instances}, key=str))
    latest_versions = (
        select(
            NovelCharacterRevision.character_id.label("character_id"),
            func.max(NovelCharacterRevision.character_version).label("character_version"),
        )
        .where(
            NovelCharacterRevision.novel_id == novel_id,
            NovelCharacterRevision.character_id.in_(character_ids),
        )
        .group_by(NovelCharacterRevision.character_id)
        .subquery()
    )
    latest_root_rows = tuple(
        session.scalars(
            select(NovelCharacterRevision)
            .join(
                latest_versions,
                and_(
                    NovelCharacterRevision.character_id
                    == latest_versions.c.character_id,
                    NovelCharacterRevision.character_version
                    == latest_versions.c.character_version,
                ),
            )
            .where(NovelCharacterRevision.novel_id == novel_id)
            .order_by(NovelCharacterRevision.character_id, NovelCharacterRevision.id)
        )
    )
    latest_roots = {item.character_id: item for item in latest_root_rows}

    revision_ids = tuple(
        sorted(
            {
                item.current_revision_id
                for item in instances
                if item.current_revision_id is not None
            },
            key=str,
        )
    )
    instance_revisions = {
        item.id: item
        for item in (
            session.scalars(
                select(CharacterInstanceRevision)
                .where(
                    CharacterInstanceRevision.novel_id == novel_id,
                    CharacterInstanceRevision.id.in_(revision_ids),
                )
                .order_by(CharacterInstanceRevision.id)
            )
            if revision_ids
            else ()
        )
    }
    result: list[ContextBlockV2] = []
    for instance in instances:
        # Forks create an explicit derived instance on the target timeline.  A
        # sibling (or the parent instance it was derived from) must never be
        # selected by name, insertion order, or recent use.
        if instance.origin_timeline_id != timeline_id:
            raise _selection_incomplete(
                "character_instances",
                cap=MAX_CHARACTER_INSTANCES,
                candidate_count=len(instance_ids),
                reason="hydrated character instance escaped the selected timeline",
                character_instance_id=str(instance.id),
            )
        root = latest_roots.get(instance.character_id)
        instance_revision = instance_revisions.get(instance.current_revision_id)
        if instance.current_revision_id is not None and (
            instance_revision is None
            or instance_revision.character_instance_id != instance.id
        ):
            raise _selection_incomplete(
                "character_instances",
                cap=MAX_CHARACTER_INSTANCES,
                candidate_count=len(instance_ids),
                reason="current character profile could not be proven during hydration",
                character_instance_id=str(instance.id),
            )
        if root is None and instance_revision is None:
            raise _selection_incomplete(
                "character_instances",
                cap=MAX_CHARACTER_INSTANCES,
                candidate_count=len(instance_ids),
                reason="selected character has no authoritative profile revision",
                character_instance_id=str(instance.id),
            )
        payload = {
            "character_id": str(instance.character_id),
            "character_instance_id": str(instance.id),
            "display_label": instance.display_label,
            "root": ({
                "name": root.name, "role_type": root.role_type,
                "description": root.description, "details": root.details_json,
            } if root is not None else None),
            "instance": instance_revision.profile_json if instance_revision else None,
        }
        item = _block(
            novel_id=novel_id, section=ContextSection.CHARACTER_STATE,
            source_kind="character_instance_revision", source_id=instance.id,
            source_revision_id=(instance_revision.id if instance_revision else None),
            title=instance.display_label or (root.name if root else "人物实例"),
            content=json.dumps(payload, ensure_ascii=False, sort_keys=True), priority=30,
            timeline_id=instance.origin_timeline_id,
        )
        if item is not None:
            result.append(item)
    return result


def _ranked_chapters(novel_id: UUID) -> Any:
    """Return a body-free chapter rank relation with a stable UUID tie-breaker."""

    return (
        select(
            Document.id.label("document_id"),
            Document.title.label("title"),
            func.row_number()
            .over(
                order_by=(
                    case((Document.volume_id.is_(None), 1), else_=0),
                    Volume.position,
                    Document.position,
                    Document.id,
                )
            )
            .label("narrative_sequence"),
        )
        .outerjoin(
            Volume,
            and_(
                Volume.id == Document.volume_id,
                Volume.novel_id == Document.novel_id,
            ),
        )
        .where(Document.novel_id == novel_id, Document.kind == "chapter")
        .subquery()
    )


def _chapter_ref_from_row(row: Any) -> _ChapterRevisionRef:
    return _ChapterRevisionRef(
        document_id=row.document_id,
        title=row.title,
        narrative_sequence=int(row.narrative_sequence),
        revision_id=row.revision_id,
        content_hash=row.content_hash,
        markdown_character_count=(
            int(row.markdown_character_count)
            if getattr(row, "markdown_character_count", None) is not None
            else None
        ),
        text_character_count=(
            int(row.text_character_count)
            if getattr(row, "text_character_count", None) is not None
            else None
        ),
    )


def _select_adjacent_chapter_refs(
    session: Session,
    *,
    novel_id: UUID,
    target_document_id: UUID,
    target_narrative_sequence: int,
    purpose: RetrievalPurpose,
) -> tuple[_ChapterRevisionRef, ...]:
    """Select bounded immutable revision refs without reading chapter bodies."""

    ranked = _ranked_chapters(novel_id)
    target_rows = tuple(
        session.execute(
            select(ranked.c.document_id, ranked.c.narrative_sequence).where(
                ranked.c.document_id == target_document_id
            )
        )
    )
    if len(target_rows) != 1:
        raise _scope_unresolved(
            "target chapter is not uniquely present in the novel scope",
            novel_id=str(novel_id),
            document_id=str(target_document_id),
        )
    observed_sequence = int(target_rows[0].narrative_sequence)
    if observed_sequence != target_narrative_sequence:
        raise _scope_unresolved(
            "target chapter narrative position changed before context selection",
            novel_id=str(novel_id),
            document_id=str(target_document_id),
            expected_narrative_sequence=target_narrative_sequence,
            observed_narrative_sequence=observed_sequence,
        )

    base = (
        select(
            ranked.c.document_id,
            ranked.c.title,
            ranked.c.narrative_sequence,
            DocumentWorkingCopy.base_revision_id.label("revision_id"),
            DocumentRevision.content_hash.label("content_hash"),
            func.char_length(DocumentRevision.content_markdown).label(
                "markdown_character_count"
            ),
            func.char_length(DocumentRevision.content_text).label(
                "text_character_count"
            ),
        )
        .join(
            DocumentWorkingCopy,
            DocumentWorkingCopy.document_id == ranked.c.document_id,
        )
        .join(
            DocumentRevision,
            and_(
                DocumentRevision.id == DocumentWorkingCopy.base_revision_id,
                DocumentRevision.document_id == ranked.c.document_id,
            ),
        )
    )

    if purpose in {RetrievalPurpose.CHAPTER_BODY, RetrievalPurpose.CHAPTER_OUTLINE}:
        rows = tuple(
            session.execute(
                base.where(ranked.c.narrative_sequence < observed_sequence)
                .order_by(
                    ranked.c.narrative_sequence.desc(),
                    ranked.c.document_id.desc(),
                )
                .limit(MAX_ADJACENT_CHAPTERS + 1)
            )
        )
        # Extra older chapters are safely omitted by the frozen nearest-eight
        # generation policy.  Reverse so blocks retain narrative order.
        selected = list(reversed(rows[:MAX_ADJACENT_CHAPTERS]))
    else:
        side_cap = MAX_ADJACENT_CHAPTERS // 2
        previous = tuple(
            session.execute(
                base.where(ranked.c.narrative_sequence < observed_sequence)
                .order_by(
                    ranked.c.narrative_sequence.desc(),
                    ranked.c.document_id.desc(),
                )
                .limit(side_cap + 1)
            )
        )
        following = tuple(
            session.execute(
                base.where(ranked.c.narrative_sequence > observed_sequence)
                .order_by(
                    ranked.c.narrative_sequence,
                    ranked.c.document_id,
                )
                .limit(side_cap + 1)
            )
        )
        selected = [*reversed(previous[:side_cap]), *following[:side_cap]]

    refs = tuple(_chapter_ref_from_row(row) for row in selected)
    if len(refs) > MAX_ADJACENT_CHAPTERS:
        raise _selection_incomplete(
            "adjacent_chapters",
            cap=MAX_ADJACENT_CHAPTERS,
            candidate_count=len(refs),
            reason="adjacent chapter policy returned too many revisions",
        )
    return refs


def _hydrate_manuscript_blocks(
    session: Session,
    *,
    novel_id: UUID,
    timeline_id: UUID,
    timelines: Sequence[StoryTimeline | StoryTimelineRecord],
    scope: ResolvedContextScope,
    refs: Sequence[_ChapterRevisionRef],
) -> list[ContextBlockV2]:
    if not refs:
        return []
    scoped_timelines = tuple(item for item in timelines if item.novel_id == novel_id)
    # Once a novel has more than one timeline record, chapter text must retain
    # its immutable mapping evidence even if a sibling was later archived.
    single_timeline_identity = len(scoped_timelines) == 1
    ref_by_revision_id = {item.revision_id: item for item in refs}
    revision_ids = tuple(sorted(ref_by_revision_id, key=str))

    if single_timeline_identity:
        oversized = next(
            (
                item
                for item in refs
                if item.markdown_character_count is not None
                and item.markdown_character_count > MAX_CONTEXT_BLOCK_CHARACTERS
            ),
            None,
        )
        if oversized is not None:
            raise _selection_incomplete(
                "manuscript_evidence",
                cap=MAX_MANUSCRIPT_EVIDENCE,
                candidate_count=len(refs),
                reason="selected chapter exceeds the bounded context block contract",
                revision_id=str(oversized.revision_id),
                character_count=oversized.markdown_character_count,
            )
        revisions = tuple(
            session.scalars(
                select(DocumentRevision)
                .where(DocumentRevision.id.in_(revision_ids))
                .order_by(DocumentRevision.id)
            )
        )
        revision_by_id = {item.id: item for item in revisions}
        if set(revision_by_id) != set(revision_ids):
            raise _selection_incomplete(
                "manuscript_evidence",
                cap=MAX_MANUSCRIPT_EVIDENCE,
                candidate_count=len(refs),
                reason="selected chapter revisions changed before body hydration",
            )
        result: list[ContextBlockV2] = []
        for ref in refs:
            revision = revision_by_id[ref.revision_id]
            if (
                revision.document_id != ref.document_id
                or revision.content_hash != ref.content_hash
            ):
                raise _selection_incomplete(
                    "manuscript_evidence",
                    cap=MAX_MANUSCRIPT_EVIDENCE,
                    candidate_count=len(refs),
                    reason="selected chapter revision failed its immutable hash guard",
                    revision_id=str(ref.revision_id),
                )
            item = _block(
                novel_id=novel_id,
                section=ContextSection.MANUSCRIPT,
                source_kind="chapter_revision",
                source_id=ref.document_id,
                source_revision_id=revision.id,
                title=context_chapter_title(ref.title, ref.narrative_sequence),
                content=revision.content_markdown,
                priority=100 + ref.narrative_sequence,
                position_domain=PositionDomain.NARRATIVE,
                timeline_id=timeline_id,
                narrative_sequence=ref.narrative_sequence,
            )
            if item is not None:
                result.append(item)
        return result

    heads = tuple(
        session.scalars(
            select(RevisionTimelineMappingHead)
            .where(
                RevisionTimelineMappingHead.novel_id == novel_id,
                RevisionTimelineMappingHead.revision_id.in_(revision_ids),
            )
            .order_by(RevisionTimelineMappingHead.revision_id)
        )
    )
    oversized = next(
        (
            item
            for item in refs
            if item.text_character_count is not None
            and item.text_character_count > MAX_CONTEXT_BLOCK_CHARACTERS
        ),
        None,
    )
    if oversized is not None:
        raise _selection_incomplete(
            "manuscript_evidence",
            cap=MAX_MANUSCRIPT_EVIDENCE,
            candidate_count=len(refs),
            reason="selected mapped chapter exceeds the bounded hydration contract",
            revision_id=str(oversized.revision_id),
            character_count=oversized.text_character_count,
        )
    head_by_revision_id = {item.revision_id: item for item in heads}
    if set(head_by_revision_id) != set(revision_ids):
        raise _selection_incomplete(
            "manuscript_timeline_mappings",
            cap=MAX_MANUSCRIPT_EVIDENCE,
            candidate_count=len(refs),
            reason="selected multi-timeline chapter is missing a current mapping head",
        )
    for ref in refs:
        head = head_by_revision_id[ref.revision_id]
        if (
            head.document_id != ref.document_id
            or head.source_content_hash != ref.content_hash
        ):
            raise _selection_incomplete(
                "manuscript_timeline_mappings",
                cap=MAX_MANUSCRIPT_EVIDENCE,
                candidate_count=len(refs),
                reason="selected multi-timeline mapping head is stale",
                revision_id=str(ref.revision_id),
            )

    mapping_ids = tuple(
        sorted(
            {item.current_mapping_revision_id for item in heads},
            key=str,
        )
    )
    mappings = tuple(
        session.scalars(
            select(RevisionTimelineMapping)
            .where(
                RevisionTimelineMapping.novel_id == novel_id,
                RevisionTimelineMapping.id.in_(mapping_ids),
            )
            .order_by(RevisionTimelineMapping.id)
        )
    )
    mapping_by_id = {item.id: item for item in mappings}
    if set(mapping_by_id) != set(mapping_ids):
        raise _selection_incomplete(
            "manuscript_timeline_mappings",
            cap=MAX_MANUSCRIPT_EVIDENCE,
            candidate_count=len(refs),
            reason="selected mapping revision changed before segment selection",
        )
    ref_by_mapping_id: dict[UUID, _ChapterRevisionRef] = {}
    for ref in refs:
        head = head_by_revision_id[ref.revision_id]
        mapping = mapping_by_id[head.current_mapping_revision_id]
        if (
            mapping.revision_id != ref.revision_id
            or mapping.document_id != ref.document_id
            or mapping.source_content_hash != ref.content_hash
        ):
            raise _selection_incomplete(
                "manuscript_timeline_mappings",
                cap=MAX_MANUSCRIPT_EVIDENCE,
                candidate_count=len(refs),
                reason="selected mapping revision failed its immutable source guard",
                mapping_revision_id=str(mapping.id),
            )
        ref_by_mapping_id[mapping.id] = ref

    timeline_predicates = tuple(
        and_(
            RevisionTimelineMappingSegment.timeline_id == inherited_timeline_id,
            RevisionTimelineMappingSegment.story_sequence.is_not(None),
            RevisionTimelineMappingSegment.story_sequence <= story_limit,
        )
        for inherited_timeline_id, story_limit in scope.story_limits.items()
    )
    if not timeline_predicates:
        raise _scope_unresolved(
            "resolved timeline has no comparable inheritance path",
            timeline_id=str(timeline_id),
        )
    unpositioned_segment = session.scalar(
        select(RevisionTimelineMappingSegment.id)
        .where(
            RevisionTimelineMappingSegment.novel_id == novel_id,
            RevisionTimelineMappingSegment.mapping_revision_id.in_(mapping_ids),
            RevisionTimelineMappingSegment.timeline_id.in_(scope.inheritance_path),
            RevisionTimelineMappingSegment.story_sequence.is_(None),
        )
        .order_by(RevisionTimelineMappingSegment.id)
        .limit(1)
    )
    if unpositioned_segment is not None:
        raise _selection_incomplete(
            "manuscript_timeline_mappings",
            cap=MAX_MANUSCRIPT_EVIDENCE,
            candidate_count=len(refs),
            reason="selected mapping contains an unpositioned inherited segment",
            segment_id=str(unpositioned_segment),
        )

    sequence_by_mapping = {
        mapping_id: ref.narrative_sequence
        for mapping_id, ref in ref_by_mapping_id.items()
    }
    segment_rows = tuple(
        session.scalars(
            select(RevisionTimelineMappingSegment)
            .where(
                RevisionTimelineMappingSegment.novel_id == novel_id,
                RevisionTimelineMappingSegment.mapping_revision_id.in_(mapping_ids),
                or_(*timeline_predicates),
            )
            .order_by(
                case(
                    sequence_by_mapping,
                    value=RevisionTimelineMappingSegment.mapping_revision_id,
                ),
                RevisionTimelineMappingSegment.ordinal,
                RevisionTimelineMappingSegment.id,
            )
            .limit(MAX_MANUSCRIPT_EVIDENCE + 1)
        )
    )
    if len(segment_rows) > MAX_MANUSCRIPT_EVIDENCE:
        raise _selection_incomplete(
            "manuscript_evidence",
            cap=MAX_MANUSCRIPT_EVIDENCE,
            candidate_count=len(segment_rows),
            reason="eligible mapped manuscript segments exceed the proven evidence boundary",
        )
    hydrated_revision_ids = tuple(
        sorted(
            {
                ref_by_mapping_id[item.mapping_revision_id].revision_id
                for item in segment_rows
            },
            key=str,
        )
    )
    revisions = tuple(
        session.scalars(
            select(DocumentRevision)
            .where(DocumentRevision.id.in_(hydrated_revision_ids))
            .order_by(DocumentRevision.id)
        )
    ) if hydrated_revision_ids else ()
    revision_by_id = {item.id: item for item in revisions}
    if set(revision_by_id) != set(hydrated_revision_ids):
        raise _selection_incomplete(
            "manuscript_evidence",
            cap=MAX_MANUSCRIPT_EVIDENCE,
            candidate_count=len(segment_rows),
            reason="mapped chapter bodies changed before hydration",
        )

    result = []
    for segment in segment_rows:
        mapping = mapping_by_id[segment.mapping_revision_id]
        ref = ref_by_mapping_id[mapping.id]
        revision = revision_by_id[ref.revision_id]
        content = revision.content_text
        if (
            revision.document_id != ref.document_id
            or revision.content_hash != ref.content_hash
            or segment.source_start < 0
            or segment.source_end <= segment.source_start
            or segment.source_end > len(content)
        ):
            raise _selection_incomplete(
                "manuscript_evidence",
                cap=MAX_MANUSCRIPT_EVIDENCE,
                candidate_count=len(segment_rows),
                reason="mapped manuscript segment failed its immutable range guard",
                segment_id=str(segment.id),
            )
        item = _block(
            novel_id=novel_id,
            section=ContextSection.MANUSCRIPT,
            source_kind="chapter_revision",
            source_id=ref.document_id,
            source_revision_id=revision.id,
            title=context_chapter_title(
                ref.title,
                ref.narrative_sequence,
                suffix=f" · 片段 {segment.ordinal + 1}",
            ),
            content=content[segment.source_start:segment.source_end],
            priority=100 + ref.narrative_sequence,
            position_domain=PositionDomain.NARRATIVE,
            timeline_id=segment.timeline_id,
            narrative_sequence=ref.narrative_sequence,
            block_discriminator=(
                f"mapping:{mapping.id}:segment:{segment.ordinal}:"
                f"{segment.source_start}:{segment.source_end}"
            ),
        )
        if item is not None:
            result.append(item)
    return result


def _private_asset_blocks(
    novel_id: UUID, assets: Sequence[dict[str, Any]]
) -> list[ContextBlockV2]:
    requirements = {
        "required": ContextRequirement.REQUIRED,
        "preferred": ContextRequirement.PREFERRED,
        "context_only": ContextRequirement.CONTEXT_ONLY,
        "prohibited": ContextRequirement.PROHIBITED,
    }
    normalized: list[tuple[UUID, UUID | None, dict[str, Any]]] = []
    seen: set[tuple[UUID, UUID | None]] = set()
    for asset in assets:
        try:
            source_id = UUID(str(asset.get("asset_id")))
            raw_revision = asset.get("asset_version_id") or asset.get("version_id")
            revision_id = UUID(str(raw_revision)) if raw_revision else None
        except (TypeError, ValueError) as error:
            raise _selection_incomplete(
                "private_assets",
                cap=MAX_PRIVATE_ASSETS,
                candidate_count=len(normalized) + 1,
                reason="private asset selection contains an invalid authority reference",
            ) from error
        if revision_id is None:
            raise _selection_incomplete(
                "private_assets",
                cap=MAX_PRIVATE_ASSETS,
                candidate_count=len(normalized) + 1,
                reason="private asset selection lacks an immutable version reference",
                asset_id=str(source_id),
            )
        key = (source_id, revision_id)
        if key in seen:
            continue
        seen.add(key)
        normalized.append((source_id, revision_id, asset))
        if len(normalized) > MAX_PRIVATE_ASSETS:
            raise _selection_incomplete(
                "private_assets",
                cap=MAX_PRIVATE_ASSETS,
                candidate_count=len(normalized),
                reason="private asset selection exceeds the frozen source boundary",
            )

    result: list[ContextBlockV2] = []
    for index, (source_id, revision_id, asset) in enumerate(normalized):
        item = _block(
            novel_id=novel_id, section=ContextSection.PRIVATE_ASSETS,
            source_kind="private_asset_version", source_id=source_id,
            source_revision_id=revision_id,
            title=str(asset.get("title") or "私有素材"),
            content=str(asset.get("content") or ""),
            requirement=requirements.get(
                str(asset.get("usage_policy") or "preferred"),
                ContextRequirement.PREFERRED,
            ),
            priority=40 + index,
        )
        if item is not None:
            result.append(item)
    return result


def _bound_private_assets(session: Session, novel_id: UUID) -> list[dict[str, Any]]:
    bindings = tuple(
        session.scalars(
            select(NovelAssetBinding)
            .where(
                NovelAssetBinding.novel_id == novel_id,
                NovelAssetBinding.lifecycle_state == "active",
            )
            .order_by(NovelAssetBinding.position, NovelAssetBinding.id)
            .limit(MAX_PRIVATE_ASSETS + 1)
        )
    )
    if len(bindings) > MAX_PRIVATE_ASSETS:
        raise _selection_incomplete(
            "private_assets",
            cap=MAX_PRIVATE_ASSETS,
            candidate_count=len(bindings),
            reason="active private asset bindings exceed the frozen source boundary",
        )
    version_ids = tuple(
        sorted({item.asset_version_id for item in bindings}, key=str)
    )
    versions = {
        item.id: item
        for item in (
            session.scalars(
                select(PrivateAssetVersion)
                .where(PrivateAssetVersion.id.in_(version_ids))
                .order_by(PrivateAssetVersion.id)
            )
            if version_ids
            else ()
        )
    }
    if set(versions) != set(version_ids):
        raise _selection_incomplete(
            "private_assets",
            cap=MAX_PRIVATE_ASSETS,
            candidate_count=len(bindings),
            reason="bound private asset version changed before hydration",
        )
    result: list[dict[str, Any]] = []
    for binding in bindings:
        version = versions[binding.asset_version_id]
        if version.asset_id != binding.asset_id:
            raise _selection_incomplete(
                "private_assets",
                cap=MAX_PRIVATE_ASSETS,
                candidate_count=len(bindings),
                reason="bound private asset failed its immutable version guard",
                binding_id=str(binding.id),
            )
        result.append({
            "asset_id": str(binding.asset_id),
            "asset_version_id": str(version.id),
            "title": version.title,
            "content": version.content,
            "usage_policy": binding.usage_policy,
        })
    return result


def _semantic_blocks(
    novel_id: UUID, retrieval: dict[str, Any] | None
) -> list[ContextBlockV2]:
    normalized: list[tuple[UUID, UUID | None, int | None, int | None, dict[str, Any]]] = []
    seen: set[tuple[UUID, UUID | None, int | None, int | None]] = set()
    for hit in (retrieval or {}).get("hits", []):
        try:
            source_id = UUID(str(hit["source_id"]))
            revision_id = (
                UUID(str(hit["source_revision_id"]))
                if hit.get("source_revision_id")
                else None
            )
            source_start = (
                int(hit["source_start"]) if hit.get("source_start") is not None else None
            )
            source_end = (
                int(hit["source_end"]) if hit.get("source_end") is not None else None
            )
        except (KeyError, TypeError, ValueError) as error:
            raise _selection_incomplete(
                "semantic_hits",
                cap=MAX_SEMANTIC_HITS,
                candidate_count=len(normalized) + 1,
                reason="semantic hit contains an invalid source reference",
            ) from error
        if (source_start is None) != (source_end is None) or (
            source_start is not None
            and source_end is not None
            and (source_start < 0 or source_end <= source_start)
        ):
            raise _selection_incomplete(
                "semantic_hits",
                cap=MAX_SEMANTIC_HITS,
                candidate_count=len(normalized) + 1,
                reason="semantic hit contains an invalid source range",
                source_id=str(source_id),
            )
        key = (source_id, revision_id, source_start, source_end)
        if key in seen:
            continue
        seen.add(key)
        normalized.append((source_id, revision_id, source_start, source_end, hit))
        if len(normalized) > MAX_SEMANTIC_HITS:
            raise _selection_incomplete(
                "semantic_hits",
                cap=MAX_SEMANTIC_HITS,
                candidate_count=len(normalized),
                reason="semantic hit selection exceeds the frozen retrieval boundary",
            )

    result: list[ContextBlockV2] = []
    for index, (source_id, revision_id, source_start, source_end, hit) in enumerate(normalized):
        item = _block(
            novel_id=novel_id, section=ContextSection.SEMANTIC_EVIDENCE,
            source_kind=str(hit.get("source_type") or "semantic_source"),
            source_id=source_id, source_revision_id=revision_id,
            title=f"语义证据 {index + 1}", content=str(hit.get("snippet") or ""),
            priority=200 + index,
            block_discriminator=(
                f"range:{source_start}:{source_end}"
                if source_start is not None or source_end is not None
                else None
            ),
        )
        if item is not None:
            result.append(item)
    return result


def _deduplicate_blocks(blocks: Sequence[ContextBlockV2]) -> list[ContextBlockV2]:
    """Prefer an already-selected full source over a duplicate semantic hit."""

    full_sources = {
        (item.source_id, item.source_revision_id)
        for item in blocks
        if item.section is not ContextSection.SEMANTIC_EVIDENCE
    }
    result: list[ContextBlockV2] = []
    seen_block_ids: set[UUID] = set()
    for block in blocks:
        if block.block_id in seen_block_ids:
            continue
        if (
            block.section is ContextSection.SEMANTIC_EVIDENCE
            and (block.source_id, block.source_revision_id) in full_sources
        ):
            continue
        seen_block_ids.add(block.block_id)
        result.append(block)
    return result


def _story_fact_blocks(
    novel_id: UUID,
    facts: Sequence[StoryFactV2],
) -> list[ContextBlockV2]:
    """Render only the already-resolved current projection into budgeted blocks."""

    result: list[ContextBlockV2] = []
    for index, fact in enumerate(facts):
        if fact.story_sequence is None:
            continue
        item = _block(
            novel_id=novel_id,
            section=ContextSection.STORY_STATE,
            source_kind="story_fact",
            source_id=fact.id,
            source_revision_id=fact.source_revision_id,
            title=f"故事事实 {index + 1}",
            content=f"{fact.subject}｜{fact.predicate}｜{fact.object_text}",
            priority=100 + index,
            position_domain=PositionDomain.STORY,
            timeline_id=fact.timeline_id,
            story_sequence=fact.story_sequence,
        )
        if item is not None:
            result.append(item)
    return result


def _context_budget(
    *,
    requested_model_id: str,
    actual_model_id: str | None,
    requested_provider_id: str | None,
    budget_provider_id: str | None,
    budget_model_id: str | None,
    effective_context_window_tokens: int,
    reserved_output_tokens: int,
) -> ContextBudgetV1 | ContextBudgetV2:
    available_for_input = effective_context_window_tokens - reserved_output_tokens
    if available_for_input <= 1:
        raise ContextAssemblyError(
            ContextAssemblyErrorCode.CONTEXT_OVERFLOW,
            "reserved output leaves no prompt input budget",
            details={
                "effective_context_window_tokens": effective_context_window_tokens,
                "reserved_output_tokens": reserved_output_tokens,
            },
        )
    reserved_prompt_tokens = min(
        max(1536, effective_context_window_tokens // 20),
        available_for_input - 1,
    )
    if requested_provider_id and budget_provider_id and budget_model_id:
        return ContextBudgetV2(
            requested_provider_id=requested_provider_id,
            requested_model_id=requested_model_id,
            budget_provider_id=budget_provider_id,
            budget_model_id=budget_model_id,
            effective_context_window_tokens=effective_context_window_tokens,
            reserved_output_tokens=reserved_output_tokens,
            reserved_prompt_tokens=reserved_prompt_tokens,
            fixed_overhead_tokens=256,
            estimator_version=TOKEN_ESTIMATOR_VERSION,
        )
    if not actual_model_id:
        raise ValueError("V1 context assembly requires actual_model_id")
    return ContextBudgetV1(
        actual_model_id=actual_model_id,
        effective_context_window_tokens=effective_context_window_tokens,
        reserved_output_tokens=reserved_output_tokens,
        reserved_prompt_tokens=reserved_prompt_tokens,
        fixed_overhead_tokens=256,
        estimator_version=TOKEN_ESTIMATOR_VERSION,
    )


def _scope_snapshot(
    *,
    position: WritingPosition,
    purpose: RetrievalPurpose,
    budget: ContextBudgetV1 | ContextBudgetV2,
    timelines: Sequence[StoryTimelineRecord],
) -> NovelContextAssemblySnapshotV4:
    return NovelContextAssemblySnapshotV4(
        novel_id=position.novel_id,
        purpose=purpose,
        position=StoryPositionV3(
            timeline_id=position.timeline_id,
            narrative_sequence=position.narrative_sequence,
            story_sequence_cutoff=position.story_sequence_cutoff,
            timeline_mapping_version=position.mapping_version,
            chapter_id=position.document_id,
        ),
        perspective=PerspectiveV1(kind=PerspectiveKind.AUTHOR),
        budget=budget,
        timelines=tuple(timelines),
    )


def _resolve_loader_scope(
    snapshot: NovelContextAssemblySnapshotV4,
) -> ResolvedContextScope:
    try:
        return resolve_context_scope(snapshot)
    except ContextAssemblyError as error:
        if error.code in {
            ContextAssemblyErrorCode.CONTEXT_SCOPE_UNRESOLVED,
            ContextAssemblyErrorCode.CONTEXT_SELECTION_INCOMPLETE,
        }:
            raise
        raise _scope_unresolved(
            "writing context timeline scope could not be resolved",
            cause_code=error.code.value,
            **error.details,
        ) from error
    except (StoryStateError, KeyError, ValueError) as error:
        details = getattr(error, "details", {})
        cause_code = getattr(getattr(error, "code", None), "value", None)
        raise _scope_unresolved(
            "writing context timeline scope could not be resolved",
            **({"cause_code": cause_code} if cause_code else {}),
            **details,
        ) from error


def _validate_target_timeline_scope(
    session: Session,
    *,
    position: WritingPosition,
    timelines: Sequence[StoryTimelineRecord],
) -> None:
    """Re-prove the target mapping without loading the target chapter body."""

    scoped_timelines = tuple(
        item for item in timelines if item.novel_id == position.novel_id
    )
    if len(scoped_timelines) == 1:
        only = scoped_timelines[0]
        if (
            position.timeline_id != only.id
            or position.story_sequence_cutoff != position.narrative_sequence
            or position.mapping_version != SINGLE_TIMELINE_MAPPING_VERSION
        ):
            raise _scope_unresolved(
                "single-timeline writing position is not the frozen identity mapping",
                document_id=str(position.document_id),
                timeline_id=str(position.timeline_id),
            )
        return

    mapping_rows = tuple(
        session.execute(
            select(
                DocumentWorkingCopy.base_revision_id.label("revision_id"),
                DocumentRevision.content_hash.label("content_hash"),
                RevisionTimelineMappingHead.document_id.label("document_id"),
                RevisionTimelineMappingHead.novel_id.label("novel_id"),
                RevisionTimelineMappingHead.source_content_hash.label(
                    "mapping_source_content_hash"
                ),
                RevisionTimelineMappingHead.current_mapping_revision_id.label(
                    "mapping_revision_id"
                ),
                RevisionTimelineMappingHead.version.label("mapping_head_version"),
            )
            .join(
                DocumentRevision,
                and_(
                    DocumentRevision.id == DocumentWorkingCopy.base_revision_id,
                    DocumentRevision.document_id == DocumentWorkingCopy.document_id,
                ),
            )
            .join(
                RevisionTimelineMappingHead,
                and_(
                    RevisionTimelineMappingHead.revision_id
                    == DocumentWorkingCopy.base_revision_id,
                    RevisionTimelineMappingHead.document_id
                    == DocumentWorkingCopy.document_id,
                ),
            )
            .where(
                DocumentWorkingCopy.document_id == position.document_id,
                RevisionTimelineMappingHead.novel_id == position.novel_id,
            )
            .limit(2)
        )
    )
    if len(mapping_rows) != 1:
        raise _scope_unresolved(
            "multi-timeline target chapter lacks one current immutable mapping",
            document_id=str(position.document_id),
            timeline_id=str(position.timeline_id),
        )
    mapping_ref = mapping_rows[0]
    expected_mapping_version = (
        f"revision-timeline-mapping/{mapping_ref.mapping_head_version}"
    )
    if (
        mapping_ref.document_id != position.document_id
        or mapping_ref.novel_id != position.novel_id
        or mapping_ref.mapping_source_content_hash != mapping_ref.content_hash
        or position.mapping_version != expected_mapping_version
    ):
        raise _scope_unresolved(
            "multi-timeline target mapping changed before context selection",
            document_id=str(position.document_id),
            timeline_id=str(position.timeline_id),
            expected_mapping_version=position.mapping_version,
            observed_mapping_version=expected_mapping_version,
        )

    mapping_revisions = tuple(
        session.scalars(
            select(RevisionTimelineMapping)
            .where(
                RevisionTimelineMapping.id == mapping_ref.mapping_revision_id,
                RevisionTimelineMapping.novel_id == position.novel_id,
            )
            .limit(2)
        )
    )
    if len(mapping_revisions) != 1:
        raise _scope_unresolved(
            "multi-timeline target mapping revision is unavailable",
            document_id=str(position.document_id),
            mapping_revision_id=str(mapping_ref.mapping_revision_id),
        )
    mapping = mapping_revisions[0]
    if (
        mapping.revision_id != mapping_ref.revision_id
        or mapping.document_id != position.document_id
        or mapping.source_content_hash != mapping_ref.content_hash
    ):
        raise _scope_unresolved(
            "multi-timeline target mapping failed its immutable source guard",
            document_id=str(position.document_id),
            mapping_revision_id=str(mapping.id),
        )

    segment_groups = tuple(
        session.execute(
            select(
                RevisionTimelineMappingSegment.timeline_id.label("timeline_id"),
                func.max(RevisionTimelineMappingSegment.story_sequence).label(
                    "max_story_sequence"
                ),
                func.count().label("segment_count"),
                func.count(RevisionTimelineMappingSegment.story_sequence).label(
                    "positioned_segment_count"
                ),
            )
            .where(
                RevisionTimelineMappingSegment.novel_id == position.novel_id,
                RevisionTimelineMappingSegment.mapping_revision_id == mapping.id,
            )
            .group_by(RevisionTimelineMappingSegment.timeline_id)
            .order_by(RevisionTimelineMappingSegment.timeline_id)
            .limit(2)
        )
    )
    if len(segment_groups) != 1:
        raise _scope_unresolved(
            "multi-timeline target mapping is not confined to one timeline",
            document_id=str(position.document_id),
            mapping_revision_id=str(mapping.id),
        )
    group = segment_groups[0]
    if (
        group.timeline_id != position.timeline_id
        or group.max_story_sequence is None
        or int(group.max_story_sequence) != position.story_sequence_cutoff
        or int(group.positioned_segment_count) != int(group.segment_count)
    ):
        raise _scope_unresolved(
            "multi-timeline target mapping no longer matches the writing cutoff",
            document_id=str(position.document_id),
            mapping_revision_id=str(mapping.id),
            timeline_id=str(position.timeline_id),
        )


def _select_story_facts(
    session: Session,
    *,
    novel_id: UUID,
    scope: ResolvedContextScope,
) -> tuple[
    tuple[StoryFactV2, ...],
    tuple[StoryEventLinkRecord, ...],
    dict[UUID, bool],
    int,
]:
    malformed_fact_id = session.scalar(
        select(StoryFact.id)
        .where(
            StoryFact.novel_id == novel_id,
            StoryFact.schema_version == "story-fact/2",
            StoryFact.timeline_id.is_(None),
        )
        .order_by(StoryFact.id)
        .limit(1)
    )
    if malformed_fact_id is not None:
        raise _selection_incomplete(
            "story_facts",
            cap=MAX_FACT_CANDIDATES,
            candidate_count=1,
            reason="a V2 story fact lacks the timeline required for safe selection",
            fact_id=str(malformed_fact_id),
        )

    scope_predicates = tuple(
        and_(
            StoryFact.timeline_id == timeline_id,
            or_(
                StoryFact.story_sequence.is_(None),
                StoryFact.story_sequence <= story_limit,
            ),
        )
        for timeline_id, story_limit in scope.story_limits.items()
    )
    if not scope_predicates:
        raise _scope_unresolved(
            "resolved timeline has no comparable fact scope",
            timeline_id=str(scope.timeline.id),
        )
    fact_order = (
        case((StoryFact.story_sequence.is_(None), 1), else_=0),
        StoryFact.story_sequence.desc(),
        StoryFact.created_at.desc(),
        StoryFact.id.desc(),
    )
    scoped_fact_count = int(
        session.scalar(
            select(func.count())
            .select_from(StoryFact)
            .where(
                StoryFact.novel_id == novel_id,
                StoryFact.schema_version == "story-fact/2",
                or_(*scope_predicates),
            )
        )
        or 0
    )
    raw_candidate_rows = tuple(
        session.execute(
            select(
                StoryFact.id.label("id"),
                StoryFact.source_revision_id.label("source_revision_id"),
                StoryFact.status.label("status"),
                StoryFact.story_sequence.label("story_sequence"),
            )
            .where(
                StoryFact.novel_id == novel_id,
                StoryFact.schema_version == "story-fact/2",
                or_(*scope_predicates),
            )
            .order_by(*fact_order)
            .limit(MAX_FACT_CANDIDATES)
        )
    )
    if len(raw_candidate_rows) > MAX_FACT_CANDIDATES:
        raise _selection_incomplete(
            "story_facts",
            cap=MAX_FACT_CANDIDATES,
            candidate_count=len(raw_candidate_rows),
            reason="database driver exceeded the frozen story-fact row limit",
        )
    candidate_rows = raw_candidate_rows[:MAX_FACT_CANDIDATES]
    if not candidate_rows:
        return (), (), {}, scoped_fact_count
    candidates = tuple(
        _StoryFactAuthorityCandidate(
            id=item.id,
            source_revision_id=item.source_revision_id,
            status=item.status,
            story_sequence=item.story_sequence,
        )
        for item in candidate_rows
    )
    candidate_ids = tuple(item.id for item in candidates)

    incoming_supersedes = tuple(
        session.scalars(
            select(StoryEventLink)
            .where(
                StoryEventLink.novel_id == novel_id,
                StoryEventLink.link_type == "supersedes",
                StoryEventLink.target_fact_id.in_(candidate_ids),
            )
            .order_by(StoryEventLink.id)
            .limit(MAX_FACT_CANDIDATES + 1)
        )
    )
    if len(incoming_supersedes) > MAX_FACT_CANDIDATES:
        raise _selection_incomplete(
            "story_fact_supersedes",
            cap=MAX_FACT_CANDIDATES,
            candidate_count=len(incoming_supersedes),
            reason="incoming supersedes evidence exceeds the proven authority boundary",
        )
    effective_candidates, _ = _load_effective_story_fact_rows(
        session,
        candidates,
        incoming_supersedes,
    )
    effective_ids = tuple(item.id for item in effective_candidates)
    if not effective_ids:
        return (), (), {}, max(0, scoped_fact_count - len(candidate_rows))

    stable_entity = func.coalesce(
        cast(StoryFact.character_instance_id, String),
        cast(StoryFact.relationship_id, String),
        cast(StoryFact.storyline_id, String),
        cast(StoryFact.foreshadow_id, String),
        cast(StoryFact.character_id, String),
        StoryFact.subject,
    )
    ranked = (
        select(
            StoryFact.id.label("fact_id"),
            StoryFact.story_sequence.label("story_sequence"),
            func.dense_rank()
            .over(
                partition_by=(
                    StoryFact.fact_type,
                    stable_entity,
                    StoryFact.dimension,
                    StoryFact.predicate,
                ),
                order_by=StoryFact.story_sequence.desc(),
            )
            .label("projection_rank"),
        )
        .where(
            StoryFact.novel_id == novel_id,
            StoryFact.id.in_(effective_ids),
            StoryFact.story_sequence.is_not(None),
        )
        .subquery()
    )
    raw_projected_ids = tuple(
        session.scalars(
            select(ranked.c.fact_id)
            .where(ranked.c.projection_rank == 1)
            .order_by(ranked.c.story_sequence.desc(), ranked.c.fact_id.desc())
            .limit(MAX_FINAL_FACTS)
        )
    )
    projected_ids = raw_projected_ids[:MAX_FINAL_FACTS]
    unpositioned_ids = tuple(
        sorted(
            (
                item.id
                for item in effective_candidates
                if item.story_sequence is None
            ),
            key=str,
        )
    )
    remaining_fact_slots = max(0, MAX_FINAL_FACTS - len(projected_ids))
    final_ids = (*projected_ids, *unpositioned_ids[:remaining_fact_slots])
    fact_rows = tuple(
        session.scalars(
            select(StoryFact)
            .where(
                StoryFact.novel_id == novel_id,
                StoryFact.id.in_(final_ids),
            )
            .order_by(*fact_order)
        )
    ) if final_ids else ()
    if {item.id for item in fact_rows} != set(final_ids):
        raise _selection_incomplete(
            "story_facts",
            cap=MAX_FINAL_FACTS,
            candidate_count=len(final_ids),
            reason="selected final story facts changed before hydration",
        )
    try:
        validated_facts = tuple(StoryFactV2.model_validate(item) for item in fact_rows)
    except ValueError as error:
        raise _selection_incomplete(
            "story_facts",
            cap=MAX_FINAL_FACTS,
            candidate_count=len(fact_rows),
            reason="selected story fact does not satisfy the V2 authority contract",
        ) from error

    contradiction_rows = tuple(
        session.scalars(
            select(StoryEventLink)
            .where(
                StoryEventLink.novel_id == novel_id,
                StoryEventLink.link_type == "contradicts",
                StoryEventLink.source_fact_id.in_(final_ids),
                StoryEventLink.target_fact_id.in_(final_ids),
            )
            .order_by(StoryEventLink.id)
            .limit(MAX_FACT_CANDIDATES + 1)
        )
    ) if effective_ids else ()
    if len(contradiction_rows) > MAX_FACT_CANDIDATES:
        raise _selection_incomplete(
            "story_fact_links",
            cap=MAX_FACT_CANDIDATES,
            candidate_count=len(contradiction_rows),
            reason="fact conflict evidence exceeds the proven selection boundary",
        )
    try:
        event_links = tuple(
            StoryEventLinkRecord.model_validate(item) for item in contradiction_rows
        )
    except ValueError as error:
        raise _selection_incomplete(
            "story_fact_links",
            cap=MAX_FACT_CANDIDATES,
            candidate_count=len(contradiction_rows),
            reason="selected story fact link violates the authority contract",
        ) from error
    source_validity = {
        item.source_revision_id: True
        for item in validated_facts
        if item.source_revision_id is not None
    }
    selection_omitted_count = max(
        0,
        scoped_fact_count - len(candidate_rows),
    ) + max(0, len(effective_ids) - len(final_ids))
    return validated_facts, event_links, source_validity, selection_omitted_count


def assemble_writing_context_from_db(
    session: Session,
    *,
    position: WritingPosition,
    purpose: RetrievalPurpose,
    requested_model_id: str,
    actual_model_id: str | None = None,
    requested_provider_id: str | None = None,
    budget_provider_id: str | None = None,
    budget_model_id: str | None = None,
    effective_context_window_tokens: int,
    reserved_output_tokens: int,
    chapter_brief: ChapterBrief | None = None,
    current_draft_markdown: str | None = None,
    private_assets: Sequence[dict[str, Any]] | None = None,
    writing_retrieval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Select bounded authority refs, hydrate them in batches, then freeze V4."""

    novel = session.get(Novel, position.novel_id)
    if novel is None:
        raise ValueError("novel not found")
    timeline_rows = tuple(
        session.scalars(
            select(StoryTimeline)
            .where(StoryTimeline.novel_id == position.novel_id)
            .order_by(StoryTimeline.position, StoryTimeline.id)
        )
    )
    try:
        timelines = tuple(
            StoryTimelineRecord.model_validate(item) for item in timeline_rows
        )
    except ValueError as error:
        raise _scope_unresolved(
            "timeline authority rows do not satisfy the story-state contract",
            novel_id=str(position.novel_id),
        ) from error
    budget = _context_budget(
        requested_model_id=requested_model_id,
        actual_model_id=actual_model_id,
        requested_provider_id=requested_provider_id,
        budget_provider_id=budget_provider_id,
        budget_model_id=budget_model_id,
        effective_context_window_tokens=effective_context_window_tokens,
        reserved_output_tokens=reserved_output_tokens,
    )
    empty_snapshot = _scope_snapshot(
        position=position,
        purpose=purpose,
        budget=budget,
        timelines=timelines,
    )
    scope = _resolve_loader_scope(empty_snapshot)
    _validate_target_timeline_scope(
        session,
        position=position,
        timelines=timelines,
    )

    # Validate the target and select only body-free adjacent refs before any
    # StoryFact or manuscript body hydration.
    chapter_refs = _select_adjacent_chapter_refs(
        session,
        novel_id=position.novel_id,
        target_document_id=position.document_id,
        target_narrative_sequence=position.narrative_sequence,
        purpose=purpose,
    )
    facts, event_links, source_validity, fact_selection_omitted_count = _select_story_facts(
        session,
        novel_id=position.novel_id,
        scope=scope,
    )
    projection = project_story_facts(
        position.novel_id,
        scope.timeline.id,
        narrative_cutoff=scope.position.story_sequence_cutoff,
        timelines=timelines,
        facts=facts,
        event_links=event_links,
        source_revision_validity=source_validity,
    )

    blocks: list[ContextBlockV2] = []
    if chapter_brief is not None:
        brief_content = json.dumps(
            {
                "expectation_text": chapter_brief.expectation_text,
                "outline_text": chapter_brief.outline_text,
                "forbidden_text": chapter_brief.forbidden_text,
                "role_constraints": chapter_brief.role_constraints,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        item = _block(
            novel_id=position.novel_id, section=ContextSection.CHAPTER_REQUIREMENTS,
            source_kind="chapter_brief", source_id=position.document_id,
            source_revision_id=None, title="章前要求", content=brief_content,
            requirement=ContextRequirement.REQUIRED, priority=0,
        )
        if item is not None:
            blocks.append(item)
    blocks.extend(_story_fact_blocks(position.novel_id, projection.current_facts))
    blocks.extend(_planning_blocks(session, position.novel_id))
    blocks.extend(
        _character_blocks(
            session,
            position.novel_id,
            timeline_id=scope.timeline.id,
        )
    )
    blocks.extend(
        _hydrate_manuscript_blocks(
            session,
            novel_id=position.novel_id,
            timeline_id=scope.timeline.id,
            timelines=timeline_rows,
            scope=scope,
            refs=chapter_refs,
        )
    )
    if current_draft_markdown:
        draft_block = _block(
            novel_id=position.novel_id,
            section=ContextSection.MANUSCRIPT,
            source_kind="current_chapter_draft",
            source_id=position.document_id,
            source_revision_id=position.document_revision_id,
            title="当前章旧稿",
            content=current_draft_markdown,
            requirement=ContextRequirement.PREFERRED,
            priority=0,
            block_discriminator="working-copy",
        )
        if draft_block is not None:
            blocks.append(draft_block)
    effective_assets = (
        list(private_assets)
        if private_assets is not None
        else _bound_private_assets(session, position.novel_id)
    )
    blocks.extend(_private_asset_blocks(position.novel_id, effective_assets))
    blocks.extend(_semantic_blocks(position.novel_id, writing_retrieval))
    blocks = _deduplicate_blocks(blocks)
    envelope = assemble_novel_context(
        empty_snapshot.model_copy(
            update={
                "facts": tuple(facts),
                "event_links": event_links,
                "source_revision_validity": source_validity,
                "blocks": tuple(blocks),
                "max_final_story_facts": MAX_FINAL_FACTS,
                "preselection_omissions": (
                    (
                        ContextOmissionV2(
                            code=OmissionCode.SELECTION_CAP_OMITTED,
                            count=fact_selection_omitted_count,
                            source_ids=(),
                            block_ids=(),
                            estimated_token_count=0,
                            explanation=(
                                "故事事实候选超过版本化选择上限；"
                                "只装载更接近当前写作位置的有界集合。"
                            ),
                        ),
                    )
                    if fact_selection_omitted_count
                    else ()
                ),
            }
        )
    )
    if isinstance(budget, ContextBudgetV2):
        return freeze_writing_context_v2(
            envelope,
            context_policy_version=CONTEXT_POLICY_VERSION,
        ).model_dump(mode="json")
    return freeze_writing_context(
        envelope,
        requested_model_id=requested_model_id,
        actual_model_id=str(actual_model_id),
        context_policy_version=CONTEXT_POLICY_VERSION,
    ).model_dump(mode="json")
