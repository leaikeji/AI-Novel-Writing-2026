"""Read-only SQLAlchemy adapter for the Context V4 production path."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any
from uuid import UUID, NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from .context_v4 import (
    ContextBlockV2,
    ContextBudgetV1,
    ContextRequirement,
    ContextSection,
    NovelContextAssemblySnapshotV4,
    PerspectiveKind,
    PerspectiveV1,
    PositionDomain,
    RetrievalPurpose,
    StoryPositionV3,
    assemble_novel_context,
    freeze_writing_context,
)
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
    Novel,
    StoryFact,
)
from .story_state import StoryEventLinkRecord, StoryFactV2, StoryTimelineRecord
from .story_state.contracts import StoryVisibilityV1, VisibilityScope


CONTEXT_POLICY_VERSION = "context-v4-production/1"
TOKEN_ESTIMATOR_VERSION = "unicode-cjk-estimator/1"


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
) -> ContextBlockV2 | None:
    if not content.strip():
        return None
    return ContextBlockV2(
        block_id=_block_id(source_kind, source_id, source_revision_id or "head"),
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


def _character_blocks(session: Session, novel_id: UUID) -> list[ContextBlockV2]:
    latest_roots: dict[UUID, NovelCharacterRevision] = {}
    for revision in session.scalars(
        select(NovelCharacterRevision)
        .where(NovelCharacterRevision.novel_id == novel_id)
        .order_by(NovelCharacterRevision.character_version)
    ):
        latest_roots[revision.character_id] = revision
    instances = tuple(
        session.scalars(
            select(CharacterInstance).where(
                CharacterInstance.novel_id == novel_id,
                CharacterInstance.lifecycle_state == "active",
            )
        )
    )
    result: list[ContextBlockV2] = []
    for instance in instances:
        root = latest_roots.get(instance.character_id)
        instance_revision = (
            session.get(CharacterInstanceRevision, instance.current_revision_id)
            if instance.current_revision_id is not None else None
        )
        if root is None and instance_revision is None:
            continue
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
        )
        if item is not None:
            result.append(item)
    return result


def _manuscript_blocks(
    session: Session, novel_id: UUID, timeline_id: UUID
) -> list[ContextBlockV2]:
    documents = tuple(
        session.scalars(
            select(Document).where(
                Document.novel_id == novel_id,
                Document.kind == "chapter",
            ).order_by(Document.position, Document.id)
        )
    )
    result: list[ContextBlockV2] = []
    for sequence, document in enumerate(documents, start=1):
        working = session.get(DocumentWorkingCopy, document.id)
        revision = (
            session.get(DocumentRevision, working.base_revision_id)
            if working is not None and working.base_revision_id is not None else None
        )
        if revision is None:
            continue
        item = _block(
            novel_id=novel_id, section=ContextSection.MANUSCRIPT,
            source_kind="chapter_revision", source_id=document.id,
            source_revision_id=revision.id, title=document.title,
            content=revision.content_markdown, priority=100 + sequence,
            position_domain=PositionDomain.NARRATIVE,
            timeline_id=timeline_id, narrative_sequence=sequence,
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
    result: list[ContextBlockV2] = []
    for index, asset in enumerate(assets):
        source_id = UUID(str(asset.get("asset_id")))
        raw_revision = asset.get("asset_version_id") or asset.get("version_id")
        item = _block(
            novel_id=novel_id, section=ContextSection.PRIVATE_ASSETS,
            source_kind="private_asset_version", source_id=source_id,
            source_revision_id=UUID(str(raw_revision)) if raw_revision else None,
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
    result: list[dict[str, Any]] = []
    for binding in session.scalars(
        select(NovelAssetBinding).where(
            NovelAssetBinding.novel_id == novel_id,
            NovelAssetBinding.lifecycle_state == "active",
        ).order_by(NovelAssetBinding.position)
    ):
        version = session.get(PrivateAssetVersion, binding.asset_version_id)
        if version is None:
            continue
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
    result: list[ContextBlockV2] = []
    for index, hit in enumerate((retrieval or {}).get("hits", [])):
        try:
            source_id = UUID(str(hit["source_id"]))
            revision_id = UUID(str(hit["source_revision_id"])) if hit.get("source_revision_id") else None
        except (KeyError, ValueError):
            continue
        item = _block(
            novel_id=novel_id, section=ContextSection.SEMANTIC_EVIDENCE,
            source_kind=str(hit.get("source_type") or "semantic_source"),
            source_id=source_id, source_revision_id=revision_id,
            title=f"语义证据 {index + 1}", content=str(hit.get("snippet") or ""),
            priority=200 + index,
        )
        if item is not None:
            result.append(item)
    return result


def assemble_writing_context_from_db(
    session: Session,
    *,
    position: WritingPosition,
    purpose: RetrievalPurpose,
    requested_model_id: str,
    actual_model_id: str,
    effective_context_window_tokens: int,
    reserved_output_tokens: int,
    chapter_brief: ChapterBrief | None = None,
    private_assets: Sequence[dict[str, Any]] | None = None,
    writing_retrieval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read authority once, assemble once, and freeze one immutable snapshot."""

    novel = session.get(Novel, position.novel_id)
    if novel is None:
        raise ValueError("novel not found")
    timelines = tuple(
        StoryTimelineRecord.model_validate(item)
        for item in session.scalars(
            select(StoryTimeline).where(StoryTimeline.novel_id == position.novel_id)
        )
    )
    facts: list[StoryFactV2] = []
    for row in session.scalars(
        select(StoryFact).where(
            StoryFact.novel_id == position.novel_id,
            StoryFact.schema_version == "story-fact/2",
        )
    ):
        try:
            facts.append(StoryFactV2.model_validate(row))
        except ValueError:
            continue
    event_links = tuple(
        StoryEventLinkRecord.model_validate(item)
        for item in session.scalars(
            select(StoryEventLink).where(StoryEventLink.novel_id == position.novel_id)
        )
    )
    source_validity: dict[UUID, bool] = {}
    for binding in session.scalars(
        select(DerivedSourceBinding)
        .join(Document, Document.id == DerivedSourceBinding.source_chapter_id)
        .where(
            Document.novel_id == position.novel_id,
            DerivedSourceBinding.derived_entity_type == "story_fact",
        )
    ):
        valid = binding.validity_state in {"current", "source_restored"}
        previous = source_validity.get(binding.source_chapter_revision_id)
        source_validity[binding.source_chapter_revision_id] = (
            valid if previous is None else previous and valid
        )
    blocks: list[ContextBlockV2] = []
    if chapter_brief is not None:
        brief_content = json.dumps({
            "target_word_count": chapter_brief.target_word_count,
            "expectation_text": chapter_brief.expectation_text,
            "outline_text": chapter_brief.outline_text,
            "forbidden_text": chapter_brief.forbidden_text,
            "role_constraints": chapter_brief.role_constraints,
        }, ensure_ascii=False, sort_keys=True)
        item = _block(
            novel_id=position.novel_id, section=ContextSection.CHAPTER_REQUIREMENTS,
            source_kind="chapter_brief", source_id=position.document_id,
            source_revision_id=None, title="章前要求", content=brief_content,
            requirement=ContextRequirement.REQUIRED, priority=0,
        )
        if item is not None:
            blocks.append(item)
    blocks.extend(_planning_blocks(session, position.novel_id))
    blocks.extend(_character_blocks(session, position.novel_id))
    blocks.extend(_manuscript_blocks(session, position.novel_id, position.timeline_id))
    effective_assets = (
        list(private_assets)
        if private_assets is not None
        else _bound_private_assets(session, position.novel_id)
    )
    blocks.extend(_private_asset_blocks(position.novel_id, effective_assets))
    blocks.extend(_semantic_blocks(position.novel_id, writing_retrieval))
    budget = ContextBudgetV1(
        actual_model_id=actual_model_id,
        effective_context_window_tokens=effective_context_window_tokens,
        reserved_output_tokens=reserved_output_tokens,
        reserved_prompt_tokens=max(256, effective_context_window_tokens // 100),
        fixed_overhead_tokens=256,
        estimator_version=TOKEN_ESTIMATOR_VERSION,
    )
    envelope = assemble_novel_context(
        NovelContextAssemblySnapshotV4(
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
            timelines=timelines,
            facts=tuple(facts),
            event_links=event_links,
            source_revision_validity=source_validity,
            blocks=tuple(blocks),
        )
    )
    return freeze_writing_context(
        envelope,
        requested_model_id=requested_model_id,
        actual_model_id=actual_model_id,
        context_policy_version=CONTEXT_POLICY_VERSION,
    ).model_dump(mode="json")
