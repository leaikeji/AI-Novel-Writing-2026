"""Read-only SQLAlchemy loader for the unified context V3 assembler."""

from __future__ import annotations

import json
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .creative_data_models import (
    CharacterInstance,
    CharacterInstanceRevision,
    NovelAssetBinding,
    NovelCharacterRevision,
    NovelOutlineHead,
    NovelOutlineRevision,
    NovelSettingHead,
    NovelSettingRevision,
    PrivateAssetVersion,
    RevisionTimelineMappingHead,
    RevisionTimelineMappingSegment,
    StoryEventLink,
    StoryTimeline,
)
from .embedding.chunking import render_structured_setting
from .models import (
    ChapterBrief,
    DerivedSourceBinding,
    Document,
    DocumentWorkingCopy,
    Novel,
    NovelCharacter,
    StoryFact,
)
from .story_state.persistence import (
    _event_link_record,
    _fact_record,
    _timeline_record,
)
from .story_state import StoryTimeV1

from .context_v3.assembler import assemble_novel_context
from .context_v3.contracts import (
    AuthorSecretConstraintV1,
    BoundPrivateAssetRecordV1,
    ChapterRoleConstraintsV3,
    CharacterContextRecordV2,
    CharacterRefV2,
    FormalPlanningRecordV1,
    NovelContextAssemblySnapshotV3,
    NovelContextEnvelopeV3,
    PerspectiveKind,
    PerspectiveV1,
    PlanningKind,
    PrivateAssetPolicy,
    SemanticEvidenceRecordV1,
    StoryPositionV2,
)


class ContextPersistenceError(ValueError):
    pass


def _merge_story_times(
    segments: Sequence[RevisionTimelineMappingSegment],
) -> StoryTimeV1 | None:
    times: list[StoryTimeV1] = []
    for segment in segments:
        try:
            item = StoryTimeV1.model_validate(dict(segment.story_time_json or {}))
        except ValueError as error:
            raise ContextPersistenceError("revision timeline mapping contains invalid story time") from error
        if item != StoryTimeV1():
            times.append(item)
    if not times:
        return None
    if all(item == times[0] for item in times[1:]):
        return times[0]
    calendars = {item.calendar_id for item in times}
    if len(calendars) != 1 or any(
        item.lower_bound is None or item.upper_bound is None for item in times
    ):
        return None
    labels = list(dict.fromkeys(item.label for item in times if item.label))
    label = " → ".join(labels)
    if len(label) > 300:
        label = "章节包含多个可比较故事时间"
    return StoryTimeV1(
        label=label or None,
        calendar_id=times[0].calendar_id,
        lower_bound=min(int(item.lower_bound) for item in times if item.lower_bound is not None),
        upper_bound=max(int(item.upper_bound) for item in times if item.upper_bound is not None),
        precision="range",
    )


def _chapter_requirements_from_brief(
    session: Session,
    document_id: UUID,
) -> tuple[ChapterRoleConstraintsV3 | None, UUID | None]:
    brief = session.scalar(
        select(ChapterBrief).where(ChapterBrief.document_id == document_id)
    )
    if brief is None or not isinstance(brief.role_constraints, dict):
        return None, None
    raw = dict(brief.role_constraints.get("_v3") or {})
    if not raw:
        return None, None
    raw_timeline_id = raw.pop("timeline_id", None)
    try:
        requirements = ChapterRoleConstraintsV3.model_validate(raw)
        parsed_timeline_id = UUID(str(raw_timeline_id)) if raw_timeline_id else None
    except ValueError as error:
        raise ContextPersistenceError("chapter brief contains invalid V3 role constraints") from error
    return requirements, parsed_timeline_id


def _latest_root_revision(
    session: Session, novel_id: UUID, character_id: UUID
) -> NovelCharacterRevision | None:
    return session.scalar(
        select(NovelCharacterRevision)
        .where(
            NovelCharacterRevision.novel_id == novel_id,
            NovelCharacterRevision.character_id == character_id,
        )
        .order_by(NovelCharacterRevision.character_version.desc())
        .limit(1)
    )


def _public_profile(
    root: NovelCharacterRevision, instance: CharacterInstanceRevision
) -> str:
    instance_profile = dict(instance.profile_json or {})
    for key in ("secret", "secrets", "author_secret_constraints"):
        instance_profile.pop(key, None)
    payload = {
        "name": root.name,
        "role_type": root.role_type,
        "description": root.description,
        "public_root_profile": dict(root.details_json or {}),
        "instance_profile": instance_profile,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _secret_constraints(
    instance: CharacterInstanceRevision, ref: CharacterRefV2
) -> tuple[AuthorSecretConstraintV1, ...]:
    raw = dict(instance.profile_json or {}).get("author_secret_constraints", ())
    if not isinstance(raw, list):
        return ()
    result: list[AuthorSecretConstraintV1] = []
    for index, item in enumerate(raw):
        if isinstance(item, str) and item.strip():
            # Stable within the immutable instance revision.
            result.append(
                AuthorSecretConstraintV1(
                    constraint_id=UUID(int=(instance.id.int + index + 1) % (1 << 128)),
                    instruction=item,
                    source_revision_id=instance.id,
                    character_ref=ref,
                )
            )
        elif isinstance(item, dict) and str(item.get("instruction", "")).strip():
            raw_id = item.get("constraint_id")
            result.append(
                AuthorSecretConstraintV1(
                    constraint_id=UUID(str(raw_id)) if raw_id else UUID(
                        int=(instance.id.int + index + 1) % (1 << 128)
                    ),
                    instruction=str(item["instruction"]),
                    source_revision_id=instance.id,
                    character_ref=ref,
                )
            )
    return tuple(result)


def _story_position(
    session: Session,
    novel_id: UUID,
    document_id: UUID | None,
    timeline_id: UUID | None,
) -> StoryPositionV2:
    narrative_sequence: int | None = None
    revision_id: UUID | None = None
    story_time: StoryTimeV1 | None = None
    if document_id is not None:
        document = session.scalar(
            select(Document).where(Document.id == document_id, Document.novel_id == novel_id)
        )
        if document is None:
            raise ContextPersistenceError("document does not belong to this novel")
        narrative_sequence = int(
            session.scalar(
                select(func.count()).select_from(Document).where(
                    Document.novel_id == novel_id,
                    Document.kind == "chapter",
                    Document.position <= document.position,
                )
            )
            or 0
        )
        working = session.get(DocumentWorkingCopy, document_id)
        revision_id = working.base_revision_id if working else None
        if revision_id is not None:
            head = session.get(RevisionTimelineMappingHead, revision_id)
            if head is not None:
                segments = tuple(
                    session.scalars(
                        select(RevisionTimelineMappingSegment).where(
                            RevisionTimelineMappingSegment.mapping_revision_id
                            == head.current_mapping_revision_id
                        )
                    )
                )
                mapped_timeline_ids = {item.timeline_id for item in segments}
                if timeline_id is None and len(mapped_timeline_ids) == 1:
                    timeline_id = next(iter(mapped_timeline_ids))
                sequences = [item.story_sequence for item in segments if item.story_sequence is not None]
                if sequences:
                    narrative_sequence = max(sequences)
                story_time = _merge_story_times(segments)
    return StoryPositionV2(
        timeline_id=timeline_id,
        narrative_sequence=narrative_sequence,
        chapter_id=document_id,
        document_revision_id=revision_id,
        story_time=story_time,
    )


def load_context_snapshot(
    session: Session,
    novel_id: UUID,
    *,
    document_id: UUID | None = None,
    timeline_id: UUID | None = None,
    perspective: PerspectiveV1 | None = None,
    chapter_requirements: ChapterRoleConstraintsV3 | None = None,
    semantic_evidence: Sequence[SemanticEvidenceRecordV1] = (),
) -> NovelContextAssemblySnapshotV3:
    """Load only current, novel-scoped authority records; never flushes."""

    if session.get(Novel, novel_id) is None:
        raise ContextPersistenceError("novel was not found")
    if document_id is not None and chapter_requirements is None:
        stored_requirements, stored_timeline_id = _chapter_requirements_from_brief(
            session, document_id
        )
        chapter_requirements = stored_requirements
        if stored_timeline_id is not None:
            if timeline_id is not None and timeline_id != stored_timeline_id:
                raise ContextPersistenceError(
                    "requested timeline conflicts with the chapter brief"
                )
            timeline_id = stored_timeline_id
    timelines = tuple(
        _timeline_record(item)
        for item in session.scalars(
            select(StoryTimeline)
            .where(
                StoryTimeline.novel_id == novel_id,
                StoryTimeline.lifecycle_state == "active",
            )
            .order_by(StoryTimeline.position, StoryTimeline.id)
        )
    )
    if not timelines:
        raise ContextPersistenceError("novel has no initialized story timeline")

    characters: list[CharacterContextRecordV2] = []
    instance_rows = session.execute(
        select(CharacterInstance, NovelCharacter)
        .join(
            NovelCharacter,
            (NovelCharacter.id == CharacterInstance.character_id)
            & (NovelCharacter.novel_id == CharacterInstance.novel_id),
        )
        .where(
            CharacterInstance.novel_id == novel_id,
            CharacterInstance.lifecycle_state == "active",
            NovelCharacter.lifecycle_state == "active",
        )
        .order_by(NovelCharacter.position, CharacterInstance.id)
    ).all()
    for instance, root in instance_rows:
        root_revision = _latest_root_revision(session, novel_id, root.id)
        instance_revision = (
            session.get(CharacterInstanceRevision, instance.current_revision_id)
            if instance.current_revision_id
            else None
        )
        if root_revision is None or instance_revision is None:
            continue
        profile = dict(instance_revision.profile_json or {})
        raw_birth_year = profile.get("birth_year")
        birth_year = (
            raw_birth_year
            if isinstance(raw_birth_year, int) and not isinstance(raw_birth_year, bool)
            else None
        )
        raw_birth_calendar = profile.get("birth_calendar_id")
        birth_calendar_id = (
            str(raw_birth_calendar).strip()
            if isinstance(raw_birth_calendar, str) and raw_birth_calendar.strip()
            else None
        )
        ref = CharacterRefV2(
            character_id=root.id,
            character_instance_id=instance.id,
            display_label=instance.display_label or root.name,
        )
        characters.append(
            CharacterContextRecordV2(
                novel_id=novel_id,
                ref=ref,
                root_revision_id=root_revision.id,
                instance_revision_id=instance_revision.id,
                present_on_timeline_ids=(instance.origin_timeline_id,),
                birth_year=birth_year,
                birth_calendar_id=birth_calendar_id,
                public_profile=_public_profile(root_revision, instance_revision),
                author_secret_constraints=_secret_constraints(instance_revision, ref),
            )
        )

    facts = tuple(
        _fact_record(item)
        for item in session.scalars(
            select(StoryFact)
            .where(
                StoryFact.novel_id == novel_id,
                StoryFact.schema_version == "story-fact/2",
                StoryFact.status.in_(("active", "source_restored")),
            )
            .order_by(StoryFact.created_at, StoryFact.id)
        )
    )
    links = tuple(
        _event_link_record(item)
        for item in session.scalars(
            select(StoryEventLink)
            .where(StoryEventLink.novel_id == novel_id)
            .order_by(StoryEventLink.created_at, StoryEventLink.id)
        )
    )
    current_revision_ids = set(
        session.scalars(
            select(DocumentWorkingCopy.base_revision_id)
            .join(Document, Document.id == DocumentWorkingCopy.document_id)
            .where(Document.novel_id == novel_id)
        )
    )
    validity = {
        fact.source_revision_id: fact.source_revision_id in current_revision_ids
        for fact in facts
        if fact.source_revision_id is not None
    }
    for binding in session.scalars(
        select(DerivedSourceBinding)
        .join(StoryFact, StoryFact.id == DerivedSourceBinding.derived_entity_id)
        .where(
            StoryFact.novel_id == novel_id,
            DerivedSourceBinding.derived_entity_type == "story_fact",
        )
    ):
        validity[binding.source_chapter_revision_id] = binding.validity_state in {
            "current", "source_restored"
        }

    planning: list[FormalPlanningRecordV1] = []
    outline_head = session.get(NovelOutlineHead, novel_id)
    if outline_head is not None:
        revision = session.get(NovelOutlineRevision, outline_head.current_revision_id)
        if revision is not None:
            content = "\n\n".join(
                item
                for item in (
                    revision.background_text,
                    revision.plot_text,
                    revision.highlight_text,
                )
                if item.strip()
            )
            if content:
                planning.append(
                    FormalPlanningRecordV1(
                        novel_id=novel_id,
                        planning_kind=PlanningKind.OUTLINE,
                        source_id=novel_id,
                        revision_id=revision.id,
                        title="正式大纲",
                        content=content,
                        content_hash=revision.content_hash,
                    )
                )
    setting_head = session.get(NovelSettingHead, novel_id)
    if setting_head is not None:
        revision = session.get(NovelSettingRevision, setting_head.current_revision_id)
        if revision is not None:
            content = render_structured_setting(revision.settings_json)
            if content:
                planning.append(
                    FormalPlanningRecordV1(
                        novel_id=novel_id,
                        planning_kind=PlanningKind.SETTING,
                        source_id=novel_id,
                        revision_id=revision.id,
                        title="正式故事设定",
                        content=content,
                        content_hash=revision.content_hash,
                    )
                )

    assets = tuple(
        BoundPrivateAssetRecordV1(
            novel_id=novel_id,
            binding_id=binding.id,
            asset_id=binding.asset_id,
            asset_version_id=version.id,
            title=version.title,
            content=version.content,
            content_hash=version.content_hash,
            policy=PrivateAssetPolicy(binding.usage_policy),
        )
        for binding, version in session.execute(
            select(NovelAssetBinding, PrivateAssetVersion)
            .join(PrivateAssetVersion, PrivateAssetVersion.id == NovelAssetBinding.asset_version_id)
            .where(
                NovelAssetBinding.novel_id == novel_id,
                NovelAssetBinding.lifecycle_state == "active",
            )
            .order_by(NovelAssetBinding.position, NovelAssetBinding.id)
        )
    )
    return NovelContextAssemblySnapshotV3(
        novel_id=novel_id,
        position=_story_position(session, novel_id, document_id, timeline_id),
        perspective=perspective or PerspectiveV1(kind=PerspectiveKind.AUTHOR),
        chapter_requirements=chapter_requirements or ChapterRoleConstraintsV3(),
        timelines=timelines,
        character_records=tuple(characters),
        facts=facts,
        event_links=links,
        source_revision_validity=validity,
        formal_planning=tuple(planning),
        private_assets=assets,
        semantic_evidence=tuple(semantic_evidence),
    )


def assemble_context_from_db(
    session: Session,
    novel_id: UUID,
    **kwargs: object,
) -> NovelContextEnvelopeV3:
    return assemble_novel_context(load_context_snapshot(session, novel_id, **kwargs))
