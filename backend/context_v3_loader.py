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
    return StoryPositionV2(
        timeline_id=timeline_id,
        narrative_sequence=narrative_sequence,
        chapter_id=document_id,
        document_revision_id=revision_id,
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
