"""Read-only character workspace and archive-impact aggregation."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, Sequence
from uuid import UUID

from sqlalchemy import and_, case, or_, select
from sqlalchemy.orm import Session

from ..creative_data_models import (
    CharacterInstance,
    CharacterInstanceRevision,
    NovelCharacterRevision,
    StoryEventLink,
    StoryTimeline,
)
from ..models import (
    ChapterBrief,
    CharacterAlias,
    CharacterRelationship,
    CharacterVoiceBinding,
    DerivedSourceBinding,
    Document,
    DocumentRevision,
    DocumentWorkingCopy,
    IntelligenceCommitBatch,
    Novel,
    NovelCharacter,
    StoryFact,
    Volume,
)
from ..story_state import (
    CharacterInstanceRecord,
    StoryStateError,
    StoryStateErrorCode,
    StoryTimelineRecord,
    resolve_character_instance,
    resolve_timeline,
)
from ..story_state.persistence import get_story_projection_payload
from ..volume_chapter_titles import context_chapter_title
from .contracts import (
    ArchiveImpactReference,
    ChapterCharacterReference,
    CharacterAliasView,
    CharacterArchiveImpactV1,
    CharacterFactHistoryPage,
    CharacterInstanceView,
    CharacterProjectedState,
    CharacterProjectedStateV2,
    CharacterRelationshipView,
    CharacterRootView,
    CharacterVoiceBindingView,
    CharacterWorkspaceError,
    CharacterWorkspaceErrorCode,
    CharacterWorkspaceV1,
    CharacterWorkspaceV2,
    FactEffectiveState,
    FactHealth,
    FactHistorySummary,
    FactSourceView,
    ProjectedFactView,
    ProjectedFactViewV2,
    ProjectionConflictView,
    TimelineView,
)
from .writing_state import (
    build_writing_state,
    fact_history_summary,
    fact_sort_key,
    is_state_fact,
)


@dataclass(frozen=True, slots=True)
class CharacterFactReadSet:
    facts: tuple[StoryFact, ...]
    bindings_by_fact_id: dict[UUID, tuple[DerivedSourceBinding, ...]]
    documents_by_id: dict[UUID, Document]
    revisions_by_id: dict[UUID, DocumentRevision]
    current_revision_by_document_id: dict[UUID, UUID | None]
    batch_state_by_id: dict[UUID, str]
    superseded_fact_ids: frozenset[UUID]


@dataclass(frozen=True, slots=True)
class _ClassifiedFact:
    row: StoryFact
    effective_state: FactEffectiveState
    health: FactHealth


@dataclass(frozen=True, slots=True)
class _ResolvedScope:
    novel: Novel
    root: NovelCharacter
    timelines: tuple[StoryTimeline, ...]
    instances: tuple[CharacterInstance, ...]
    active_timelines: tuple[StoryTimeline, ...]
    timeline: StoryTimelineRecord
    instance: CharacterInstanceRecord


class CharacterWorkspaceStore(Protocol):
    def novel(self, novel_id: UUID) -> Novel | None: ...

    def character(self, novel_id: UUID, character_id: UUID) -> NovelCharacter | None: ...

    def character_revision(self, character: NovelCharacter) -> NovelCharacterRevision | None: ...

    def timelines(self, novel_id: UUID) -> Sequence[StoryTimeline]: ...

    def instances(self, novel_id: UUID, character_id: UUID) -> Sequence[CharacterInstance]: ...

    def instance_revision(
        self, instance: CharacterInstance
    ) -> CharacterInstanceRevision | None: ...

    def aliases(self, novel_id: UUID, character_id: UUID) -> Sequence[CharacterAlias]: ...

    def relationships(
        self, novel_id: UUID, character_id: UUID
    ) -> Sequence[CharacterRelationship]: ...

    def chapter_briefs(self, novel_id: UUID) -> Sequence[tuple[ChapterBrief, Document]]: ...

    def chapter_ordinals(self, novel_id: UUID) -> dict[UUID, int]: ...

    def voice_binding(
        self, novel_id: UUID, character_id: UUID
    ) -> CharacterVoiceBinding | None: ...

    def projection(
        self, novel_id: UUID, timeline_id: UUID, narrative_cutoff: int | None
    ) -> dict[str, Any]: ...

    def story_facts(
        self,
        novel_id: UUID,
        character_id: UUID,
        relationship_ids: Sequence[UUID] = (),
    ) -> Sequence[StoryFact]: ...

    def fact_read_set(
        self,
        novel_id: UUID,
        character_id: UUID,
        relationship_ids: Sequence[UUID] = (),
    ) -> CharacterFactReadSet: ...


class SqlAlchemyCharacterWorkspaceStore:
    """SQLAlchemy read adapter.  Every statement is a plain SELECT."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def _scalar(self, statement: Any) -> Any:
        with self.session.no_autoflush:
            return self.session.scalar(statement)

    def _scalars(self, statement: Any) -> tuple[Any, ...]:
        with self.session.no_autoflush:
            return tuple(self.session.scalars(statement))

    def _rows(self, statement: Any) -> tuple[Any, ...]:
        with self.session.no_autoflush:
            return tuple(self.session.execute(statement).all())

    def novel(self, novel_id: UUID) -> Novel | None:
        return self._scalar(select(Novel).where(Novel.id == novel_id))

    def character(self, novel_id: UUID, character_id: UUID) -> NovelCharacter | None:
        return self._scalar(
            select(NovelCharacter).where(
                NovelCharacter.id == character_id,
                NovelCharacter.novel_id == novel_id,
            )
        )

    def character_revision(self, character: NovelCharacter) -> NovelCharacterRevision | None:
        return self._scalar(
            select(NovelCharacterRevision)
            .where(
                NovelCharacterRevision.character_id == character.id,
                NovelCharacterRevision.novel_id == character.novel_id,
                NovelCharacterRevision.character_version == character.version,
            )
            .order_by(NovelCharacterRevision.created_at.desc(), NovelCharacterRevision.id.desc())
        )

    def timelines(self, novel_id: UUID) -> Sequence[StoryTimeline]:
        return self._scalars(
            select(StoryTimeline)
            .where(StoryTimeline.novel_id == novel_id)
            .order_by(StoryTimeline.position, StoryTimeline.id)
        )

    def instances(self, novel_id: UUID, character_id: UUID) -> Sequence[CharacterInstance]:
        return self._scalars(
            select(CharacterInstance)
            .where(
                CharacterInstance.novel_id == novel_id,
                CharacterInstance.character_id == character_id,
            )
            .order_by(CharacterInstance.created_at, CharacterInstance.id)
        )

    def instance_revision(
        self, instance: CharacterInstance
    ) -> CharacterInstanceRevision | None:
        if instance.current_revision_id is None:
            return None
        return self._scalar(
            select(CharacterInstanceRevision).where(
                CharacterInstanceRevision.id == instance.current_revision_id,
                CharacterInstanceRevision.character_instance_id == instance.id,
                CharacterInstanceRevision.novel_id == instance.novel_id,
            )
        )

    def aliases(self, novel_id: UUID, character_id: UUID) -> Sequence[CharacterAlias]:
        return self._scalars(
            select(CharacterAlias)
            .where(
                CharacterAlias.novel_id == novel_id,
                CharacterAlias.character_id == character_id,
            )
            .order_by(CharacterAlias.created_at, CharacterAlias.id)
        )

    def relationships(
        self, novel_id: UUID, character_id: UUID
    ) -> Sequence[CharacterRelationship]:
        return self._scalars(
            select(CharacterRelationship)
            .where(
                CharacterRelationship.novel_id == novel_id,
                or_(
                    CharacterRelationship.source_character_id == character_id,
                    CharacterRelationship.target_character_id == character_id,
                ),
            )
            .order_by(CharacterRelationship.created_at, CharacterRelationship.id)
        )

    def chapter_briefs(self, novel_id: UUID) -> Sequence[tuple[ChapterBrief, Document]]:
        return self._rows(
            select(ChapterBrief, Document)
            .join(Document, Document.id == ChapterBrief.document_id)
            .outerjoin(
                Volume,
                and_(
                    Volume.id == Document.volume_id,
                    Volume.novel_id == Document.novel_id,
                ),
            )
            .where(Document.novel_id == novel_id, Document.kind == "chapter")
            .order_by(
                case((Document.volume_id.is_(None), 1), else_=0),
                Volume.position,
                Document.position,
                Document.id,
            )
        )

    def chapter_ordinals(self, novel_id: UUID) -> dict[UUID, int]:
        document_ids = self._scalars(
            select(Document.id)
            .outerjoin(
                Volume,
                and_(
                    Volume.id == Document.volume_id,
                    Volume.novel_id == Document.novel_id,
                ),
            )
            .where(Document.novel_id == novel_id, Document.kind == "chapter")
            .order_by(
                case((Document.volume_id.is_(None), 1), else_=0),
                Volume.position,
                Document.position,
                Document.id,
            )
        )
        return {
            document_id: ordinal
            for ordinal, document_id in enumerate(document_ids, start=1)
        }

    def voice_binding(
        self, novel_id: UUID, character_id: UUID
    ) -> CharacterVoiceBinding | None:
        return self._scalar(
            select(CharacterVoiceBinding).where(
                CharacterVoiceBinding.novel_id == novel_id,
                CharacterVoiceBinding.character_id == character_id,
            )
        )

    def projection(
        self, novel_id: UUID, timeline_id: UUID, narrative_cutoff: int | None
    ) -> dict[str, Any]:
        with self.session.no_autoflush:
            return get_story_projection_payload(
                self.session,
                novel_id,
                timeline_id=timeline_id,
                narrative_cutoff=narrative_cutoff,
            )

    def story_facts(
        self,
        novel_id: UUID,
        character_id: UUID,
        relationship_ids: Sequence[UUID] = (),
    ) -> Sequence[StoryFact]:
        entity_scope = StoryFact.character_id == character_id
        if relationship_ids:
            entity_scope = or_(
                entity_scope, StoryFact.relationship_id.in_(tuple(relationship_ids))
            )
        return self._scalars(
            select(StoryFact)
            .where(
                StoryFact.novel_id == novel_id,
                entity_scope,
                StoryFact.schema_version == "story-fact/2",
            )
            .order_by(StoryFact.created_at, StoryFact.id)
        )

    def fact_read_set(
        self,
        novel_id: UUID,
        character_id: UUID,
        relationship_ids: Sequence[UUID] = (),
    ) -> CharacterFactReadSet:
        facts = tuple(self.story_facts(novel_id, character_id, relationship_ids))
        fact_ids = tuple(fact.id for fact in facts)
        if not fact_ids:
            return CharacterFactReadSet(
                facts=(),
                bindings_by_fact_id={},
                documents_by_id={},
                revisions_by_id={},
                current_revision_by_document_id={},
                batch_state_by_id={},
                superseded_fact_ids=frozenset(),
            )

        bindings = self._scalars(
            select(DerivedSourceBinding)
            .where(
                DerivedSourceBinding.derived_entity_type == "story_fact",
                DerivedSourceBinding.derived_entity_id.in_(fact_ids),
            )
            .order_by(DerivedSourceBinding.created_at, DerivedSourceBinding.id)
        )
        bindings_by_fact_id: dict[UUID, list[DerivedSourceBinding]] = {}
        for binding in bindings:
            bindings_by_fact_id.setdefault(binding.derived_entity_id, []).append(binding)

        revision_ids = tuple(
            {
                fact.source_revision_id
                for fact in facts
                if fact.source_revision_id is not None
            }
        )
        revisions = (
            self._scalars(
                select(DocumentRevision).where(DocumentRevision.id.in_(revision_ids))
            )
            if revision_ids
            else ()
        )
        document_ids = tuple(
            {
                fact.source_document_id
                for fact in facts
                if fact.source_document_id is not None
            }
        )
        document_rows = (
            self._rows(
                select(Document, DocumentWorkingCopy)
                .outerjoin(
                    DocumentWorkingCopy,
                    DocumentWorkingCopy.document_id == Document.id,
                )
                .where(
                    Document.novel_id == novel_id,
                    Document.id.in_(document_ids),
                )
            )
            if document_ids
            else ()
        )

        batch_ids = tuple(
            {
                binding.commit_batch_id
                for binding in bindings
                if binding.commit_batch_id is not None
            }
        )
        batches = (
            self._scalars(
                select(IntelligenceCommitBatch).where(
                    IntelligenceCommitBatch.id.in_(batch_ids)
                )
            )
            if batch_ids
            else ()
        )
        supersedes = self._scalars(
            select(StoryEventLink).where(
                StoryEventLink.novel_id == novel_id,
                StoryEventLink.link_type == "supersedes",
                StoryEventLink.target_fact_id.in_(fact_ids),
            )
        )
        return CharacterFactReadSet(
            facts=facts,
            bindings_by_fact_id={
                fact_id: tuple(rows) for fact_id, rows in bindings_by_fact_id.items()
            },
            documents_by_id={document.id: document for document, _working in document_rows},
            revisions_by_id={revision.id: revision for revision in revisions},
            current_revision_by_document_id={
                document.id: working.base_revision_id if working is not None else None
                for document, working in document_rows
            },
            batch_state_by_id={batch.id: batch.state for batch in batches},
            superseded_fact_ids=frozenset(link.target_fact_id for link in supersedes),
        )


@dataclass(slots=True)
class CharacterWorkspaceService:
    store: CharacterWorkspaceStore

    def _resolve_scope(
        self,
        novel_id: UUID,
        character_id: UUID,
        *,
        timeline_id: UUID | None,
        character_instance_id: UUID | None,
    ) -> _ResolvedScope:
        novel = self.store.novel(novel_id)
        if novel is None:
            raise CharacterWorkspaceError(
                CharacterWorkspaceErrorCode.CHARACTER_NOT_FOUND,
                "novel or character was not found",
            )
        root = self._require_character(novel_id, character_id)
        timelines = tuple(self.store.timelines(novel_id))
        instances = tuple(self.store.instances(novel_id, character_id))
        active_timelines = tuple(
            item for item in timelines if item.lifecycle_state == "active"
        )
        try:
            resolved_timeline = resolve_timeline(
                tuple(StoryTimelineRecord.model_validate(item) for item in timelines),
                novel_id,
                timeline_id,
            )
            if len(active_timelines) > 1 and character_instance_id is None:
                candidates = tuple(
                    item
                    for item in instances
                    if item.lifecycle_state == "active"
                    and item.origin_timeline_id == resolved_timeline.id
                )
                raise StoryStateError(
                    StoryStateErrorCode.CHARACTER_INSTANCE_REQUIRED,
                    "character_instance_id is required in a multi-timeline workspace",
                    details={
                        "character_instance_ids": [str(item.id) for item in candidates]
                    },
                )
            resolved_instance = resolve_character_instance(
                tuple(CharacterInstanceRecord.model_validate(item) for item in instances),
                novel_id,
                character_id=character_id,
                timeline_id=resolved_timeline.id,
                character_instance_id=character_instance_id,
            )
        except StoryStateError as error:
            raise self._workspace_error(error) from error
        return _ResolvedScope(
            novel=novel,
            root=root,
            timelines=timelines,
            instances=instances,
            active_timelines=active_timelines,
            timeline=resolved_timeline,
            instance=resolved_instance,
        )

    def _relationships_for_scope(
        self, scope: _ResolvedScope
    ) -> tuple[CharacterRelationship, ...]:
        return tuple(
            row
            for row in self.store.relationships(scope.novel.id, scope.root.id)
            if row.archived_at is None
            and (row.timeline_id is None or row.timeline_id == scope.timeline.id)
            and (
                (
                    row.source_character_id == scope.root.id
                    and row.source_character_instance_id in {None, scope.instance.id}
                )
                or (
                    row.target_character_id == scope.root.id
                    and row.target_character_instance_id in {None, scope.instance.id}
                )
            )
        )

    def _fact_read_set(
        self,
        novel_id: UUID,
        character_id: UUID,
        relationship_ids: Sequence[UUID],
    ) -> CharacterFactReadSet:
        reader = getattr(self.store, "fact_read_set", None)
        if callable(reader):
            return reader(novel_id, character_id, relationship_ids)
        return CharacterFactReadSet(
            facts=tuple(self.store.story_facts(novel_id, character_id, relationship_ids)),
            bindings_by_fact_id={},
            documents_by_id={},
            revisions_by_id={},
            current_revision_by_document_id={},
            batch_state_by_id={},
            superseded_fact_ids=frozenset(),
        )

    def get_workspace(
        self,
        novel_id: UUID,
        character_id: UUID,
        *,
        timeline_id: UUID | None = None,
        character_instance_id: UUID | None = None,
        narrative_cutoff: int | None = None,
        view_version: Literal[1, 2] = 1,
    ) -> CharacterWorkspaceV1 | CharacterWorkspaceV2:
        scope = self._resolve_scope(
            novel_id,
            character_id,
            timeline_id=timeline_id,
            character_instance_id=character_instance_id,
        )
        try:
            projection = self.store.projection(
                novel_id, scope.timeline.id, narrative_cutoff
            )
        except StoryStateError as error:
            raise self._workspace_error(error) from error
        root_revision = self.store.character_revision(scope.root)
        relationship_rows = self._relationships_for_scope(scope)
        relationship_ids = {row.id for row in relationship_rows}
        read_set = (
            self._fact_read_set(novel_id, character_id, tuple(relationship_ids))
            if view_version == 2
            else None
        )
        workspace_facts = (
            read_set.facts
            if read_set is not None
            else self.store.story_facts(novel_id, character_id, tuple(relationship_ids))
        )
        character_fact_ids = {
            row.id
            for row in workspace_facts
            if row.relationship_id in relationship_ids
            or row.character_instance_id in {None, scope.instance.id}
        }
        ordinals = _store_chapter_ordinals(self.store, novel_id)
        workspace = CharacterWorkspaceV1(
            novel_id=novel_id,
            character_catalog_version=scope.novel.character_catalog_version,
            story_ledger_version=scope.novel.story_ledger_version,
            timeline_mode="multiple" if len(scope.active_timelines) > 1 else "single",
            character=CharacterRootView(
                id=scope.root.id,
                novel_id=scope.root.novel_id,
                name=scope.root.name,
                role_type=scope.root.role_type,
                description=scope.root.description,
                details=dict(scope.root.details or {}),
                lifecycle_state=scope.root.lifecycle_state,
                position=scope.root.position,
                version=scope.root.version,
                current_revision_id=root_revision.id if root_revision else None,
            ),
            selected_timeline=_timeline_view(scope.timeline),
            selected_instance=self._instance_view(
                next(item for item in scope.instances if item.id == scope.instance.id)
            ),
            timelines=tuple(
                _timeline_view(StoryTimelineRecord.model_validate(item))
                for item in scope.timelines
                if item.lifecycle_state == "active"
            ),
            instances=tuple(self._instance_view(item) for item in scope.instances),
            aliases=tuple(
                _alias_view(item)
                for item in self.store.aliases(novel_id, character_id)
                if item.lifecycle_state != "archived"
                and item.timeline_id in {None, scope.timeline.id}
                and item.character_instance_id in {None, scope.instance.id}
            ),
            relationships=tuple(_relationship_view(item) for item in relationship_rows),
            chapter_references=_chapter_references(
                self.store.chapter_briefs(novel_id),
                character_id=character_id,
                instance_id=scope.instance.id,
                timeline_id=scope.timeline.id,
                ordinals=ordinals,
            ),
            voice_binding=_voice_binding_view(
                self.store.voice_binding(novel_id, character_id)
            ),
            projected_state=_projected_state(
                projection,
                character_id=character_id,
                instance_id=scope.instance.id,
                character_fact_ids=character_fact_ids,
                relationship_ids=relationship_ids,
            ),
        )
        if view_version == 1:
            return workspace

        assert read_set is not None
        fact_views = _fact_views(
            read_set,
            projection=projection,
            instance_id=scope.instance.id,
            relationship_ids=relationship_ids,
            document_ordinals=ordinals,
        )
        facts_by_id = {fact.id: fact for fact in fact_views}
        current_v2 = tuple(
            facts_by_id[fact.id]
            for fact in workspace.projected_state.current_facts
            if fact.id in facts_by_id
            and facts_by_id[fact.id].effective_state == "current"
        )
        projected_state_v2 = CharacterProjectedStateV2(
            timeline_id=workspace.projected_state.timeline_id,
            narrative_cutoff=workspace.projected_state.narrative_cutoff,
            current_facts=current_v2,
            conflicts=workspace.projected_state.conflicts,
            ambiguous_fact_ids=workspace.projected_state.ambiguous_fact_ids,
        )
        payload = workspace.model_dump(exclude={"schema_version", "projected_state"})
        return CharacterWorkspaceV2(
            **payload,
            projected_state=projected_state_v2,
            writing_state=build_writing_state(
                timeline_id=scope.timeline.id,
                narrative_cutoff=narrative_cutoff,
                facts=fact_views,
            ),
        )

    def list_facts(
        self,
        novel_id: UUID,
        character_id: UUID,
        *,
        timeline_id: UUID | None = None,
        character_instance_id: UUID | None = None,
        narrative_cutoff: int | None = None,
        effective_state: Literal[
            "all",
            "current",
            "historical",
            "superseded",
            "source_invalid",
            "batch_reverted",
        ] = "all",
        health: Literal["all", "ok", "conflict", "ambiguous"] = "all",
        dimension: str | None = None,
        source_document_id: UUID | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> CharacterFactHistoryPage:
        scope = self._resolve_scope(
            novel_id,
            character_id,
            timeline_id=timeline_id,
            character_instance_id=character_instance_id,
        )
        relationship_rows = self._relationships_for_scope(scope)
        relationship_ids = {row.id for row in relationship_rows}
        try:
            projection = self.store.projection(
                novel_id, scope.timeline.id, narrative_cutoff
            )
        except StoryStateError as error:
            raise self._workspace_error(error) from error
        read_set = self._fact_read_set(
            novel_id, character_id, tuple(relationship_ids)
        )
        facts = list(
            _classify_facts(
                read_set,
                projection=projection,
                instance_id=scope.instance.id,
                relationship_ids=relationship_ids,
            )
        )
        if effective_state != "all":
            facts = [fact for fact in facts if fact.effective_state == effective_state]
        if health != "all":
            facts = [fact for fact in facts if fact.health == health]
        if dimension is not None:
            facts = [
                fact
                for fact in facts
                if (fact.row.dimension or fact.row.predicate) == dimension
            ]
        if source_document_id is not None:
            facts = [
                fact
                for fact in facts
                if fact.row.source_document_id == source_document_id
            ]
        facts.sort(key=_story_fact_sort_key, reverse=True)
        summary = _classified_fact_history_summary(facts)
        if cursor is not None:
            cursor_key = _decode_cursor(cursor)
            facts = [fact for fact in facts if _story_fact_sort_key(fact) < cursor_key]
        page = facts[:limit]
        next_cursor = (
            _encode_cursor(_story_fact_sort_key(page[-1]))
            if len(facts) > limit
            else None
        )
        ordinals = _store_chapter_ordinals(self.store, novel_id) or {}
        return CharacterFactHistoryPage(
            items=tuple(
                _classified_fact_view(fact, read_set, ordinals) for fact in page
            ),
            next_cursor=next_cursor,
            total_summary=summary,
        )

    def archive_impact(
        self, novel_id: UUID, character_id: UUID
    ) -> CharacterArchiveImpactV1:
        root = self._require_character(novel_id, character_id)
        references: list[ArchiveImpactReference] = []
        instances = tuple(self.store.instances(novel_id, character_id))
        aliases = tuple(self.store.aliases(novel_id, character_id))
        relationships = tuple(self.store.relationships(novel_id, character_id))
        briefs = tuple(self.store.chapter_briefs(novel_id))
        for instance in instances:
            if instance.lifecycle_state == "active":
                references.append(
                    ArchiveImpactReference(
                        reference_type="active_instance",
                        reference_id=instance.id,
                        label=instance.display_label or root.name,
                        disposition="requires_review",
                    )
                )
        for alias in aliases:
            if alias.lifecycle_state == "active":
                references.append(
                    ArchiveImpactReference(
                        reference_type="active_alias",
                        reference_id=alias.id,
                        label=alias.alias,
                        disposition="requires_review",
                    )
                )
        for relationship in relationships:
            if relationship.archived_at is None:
                references.append(
                    ArchiveImpactReference(
                        reference_type="active_relationship",
                        reference_id=relationship.id,
                        label=relationship.label,
                        disposition="requires_review",
                    )
                )
        for reference in _chapter_references(
            briefs,
            character_id=character_id,
            instance_id=None,
            timeline_id=None,
            ordinals=_store_chapter_ordinals(self.store, novel_id),
        ):
            references.append(
                ArchiveImpactReference(
                    reference_type="chapter_brief",
                    reference_id=reference.document_id,
                    label=reference.document_title,
                    disposition="requires_review",
                )
            )
        voice = self.store.voice_binding(novel_id, character_id)
        if voice is not None and voice.binding_policy != "unset":
            references.append(
                ArchiveImpactReference(
                    reference_type="voice_binding",
                    reference_id=voice.id,
                    label=voice.binding_policy,
                    disposition="requires_review",
                )
            )
        relationship_ids = tuple(item.id for item in relationships)
        for fact in self.store.story_facts(
            novel_id, character_id, relationship_ids
        ):
            references.append(
                ArchiveImpactReference(
                    reference_type="story_fact",
                    reference_id=fact.id,
                    label=f"{fact.dimension or fact.predicate}: {fact.object_text}",
                    disposition="preserved_history",
                )
            )
        references.sort(key=lambda item: (item.reference_type, str(item.reference_id)))
        current_count = sum(
            item.disposition == "requires_review" for item in references
        )
        history_count = len(references) - current_count
        return CharacterArchiveImpactV1(
            novel_id=novel_id,
            character_id=root.id,
            character_name=root.name,
            character_version=root.version,
            already_archived=root.lifecycle_state == "archived",
            requires_confirmation=current_count > 0,
            current_dependency_count=current_count,
            preserved_history_count=history_count,
            references=tuple(references),
        )

    def _require_character(self, novel_id: UUID, character_id: UUID) -> NovelCharacter:
        root = self.store.character(novel_id, character_id)
        if root is None:
            raise CharacterWorkspaceError(
                CharacterWorkspaceErrorCode.CHARACTER_NOT_FOUND,
                "character was not found in the novel",
                details={"character_id": str(character_id)},
            )
        return root

    def _instance_view(self, instance: CharacterInstance) -> CharacterInstanceView:
        revision = self.store.instance_revision(instance)
        return CharacterInstanceView(
            id=instance.id,
            character_id=instance.character_id,
            origin_timeline_id=instance.origin_timeline_id,
            continuity_kind=instance.continuity_kind,
            display_label=instance.display_label,
            derived_from_instance_id=instance.derived_from_instance_id,
            lifecycle_state=instance.lifecycle_state,
            version=instance.version,
            current_revision_id=instance.current_revision_id,
            profile=dict(revision.profile_json or {}) if revision else {},
            profile_schema_version=revision.profile_schema_version if revision else None,
        )

    @staticmethod
    def _workspace_error(error: StoryStateError) -> CharacterWorkspaceError:
        mapping = {
            StoryStateErrorCode.TIMELINE_NOT_FOUND: CharacterWorkspaceErrorCode.TIMELINE_NOT_FOUND,
            StoryStateErrorCode.TIMELINE_REQUIRED: CharacterWorkspaceErrorCode.TIMELINE_REQUIRED,
            StoryStateErrorCode.TIMELINE_CONFLICT: CharacterWorkspaceErrorCode.TIMELINE_CONFLICT,
            StoryStateErrorCode.CHARACTER_INSTANCE_NOT_FOUND: CharacterWorkspaceErrorCode.CHARACTER_INSTANCE_NOT_FOUND,
            StoryStateErrorCode.CHARACTER_INSTANCE_REQUIRED: CharacterWorkspaceErrorCode.CHARACTER_INSTANCE_REQUIRED,
            StoryStateErrorCode.CHARACTER_INSTANCE_CONFLICT: CharacterWorkspaceErrorCode.CHARACTER_INSTANCE_CONFLICT,
        }
        code = mapping.get(error.code, CharacterWorkspaceErrorCode.TIMELINE_CONFLICT)
        return CharacterWorkspaceError(code, str(error), details=dict(error.details))


def _timeline_view(timeline: StoryTimelineRecord) -> TimelineView:
    return TimelineView(
        id=timeline.id,
        name=timeline.name,
        timeline_kind=timeline.timeline_kind.value,
        is_primary=timeline.is_primary,
        parent_timeline_id=timeline.parent_timeline_id,
        fork_story_sequence=timeline.fork_story_sequence,
    )


def _alias_view(alias: CharacterAlias) -> CharacterAliasView:
    return CharacterAliasView(
        id=alias.id,
        alias=alias.alias,
        alias_kind=alias.alias_kind,
        character_instance_id=alias.character_instance_id,
        timeline_id=alias.timeline_id,
        identity_layer=alias.identity_layer,
        valid_from_sequence=alias.valid_from_sequence,
        valid_to_sequence=alias.valid_to_sequence,
        lifecycle_state=alias.lifecycle_state,
    )


def _relationship_view(row: CharacterRelationship) -> CharacterRelationshipView:
    return CharacterRelationshipView(
        id=row.id,
        timeline_id=row.timeline_id,
        source_character_id=row.source_character_id,
        target_character_id=row.target_character_id,
        source_character_instance_id=row.source_character_instance_id,
        target_character_instance_id=row.target_character_instance_id,
        directionality=row.directionality,
        relation_kind=row.relation_kind,
        label=row.label,
        description=row.description or "",
        status=row.status,
        manual_override=row.manual_override,
        version=row.version,
    )


def _voice_binding_view(
    binding: CharacterVoiceBinding | None,
) -> CharacterVoiceBindingView | None:
    if binding is None:
        return None
    return CharacterVoiceBindingView(
        binding_id=binding.id,
        binding_policy=binding.binding_policy,
        profile_id=binding.profile_id,
        voice_version_id=binding.voice_version_id,
        language=binding.language,
        version=binding.version,
    )


def _chapter_references(
    rows: Sequence[tuple[ChapterBrief, Document]],
    *,
    character_id: UUID,
    instance_id: UUID | None,
    timeline_id: UUID | None,
    ordinals: dict[UUID, int] | None = None,
) -> tuple[ChapterCharacterReference, ...]:
    results: list[ChapterCharacterReference] = []
    fallback_ordinals = {
        document.id: ordinal
        for ordinal, (_brief, document) in enumerate(rows, start=1)
    }
    effective_ordinals = ordinals or fallback_ordinals
    for brief, document in rows:
        raw = brief.role_constraints if isinstance(brief.role_constraints, dict) else {}
        v3 = raw.get("_v3")
        if not isinstance(v3, dict) or v3.get("schema_version") != "chapter-role-constraints/3":
            continue
        try:
            brief_timeline_id = UUID(str(v3["timeline_id"]))
        except (KeyError, TypeError, ValueError):
            continue
        if timeline_id is not None and brief_timeline_id != timeline_id:
            continue
        matches: list[tuple[str, UUID | None]] = []
        required = v3.get("required_characters")
        if isinstance(required, list):
            for item in required:
                if not isinstance(item, dict):
                    continue
                try:
                    item_character_id = UUID(str(item["character_id"]))
                    item_instance_id = UUID(str(item["character_instance_id"]))
                except (KeyError, TypeError, ValueError):
                    continue
                if item_character_id == character_id and (
                    instance_id is None or item_instance_id == instance_id
                ):
                    matches.append(("required", item_instance_id))
        point_of_view = v3.get("point_of_view")
        if isinstance(point_of_view, dict):
            try:
                pov_character_id = UUID(str(point_of_view["character_id"]))
                pov_instance_id = UUID(str(point_of_view["character_instance_id"]))
            except (KeyError, TypeError, ValueError):
                pass
            else:
                if pov_character_id == character_id and (
                    instance_id is None or pov_instance_id == instance_id
                ):
                    matches.append(("point_of_view", pov_instance_id))
        if not matches:
            continue
        results.append(
            ChapterCharacterReference(
                document_id=document.id,
                document_title=context_chapter_title(
                    document.title,
                    effective_ordinals.get(document.id, fallback_ordinals[document.id]),
                ),
                document_position=document.position,
                reference_kinds=tuple(dict.fromkeys(kind for kind, _ in matches)),
                character_instance_id=matches[0][1],
                timeline_id=brief_timeline_id,
            )
        )
    return tuple(results)


def _store_chapter_ordinals(
    store: CharacterWorkspaceStore,
    novel_id: UUID,
) -> dict[UUID, int] | None:
    resolver = getattr(store, "chapter_ordinals", None)
    if resolver is None or not callable(resolver):
        return None
    return dict(resolver(novel_id))


def _projected_state(
    payload: dict[str, Any],
    *,
    character_id: UUID,
    instance_id: UUID,
    character_fact_ids: set[UUID],
    relationship_ids: set[UUID],
) -> CharacterProjectedState:
    all_character_fact_ids = set(character_fact_ids)
    relationship_id_strings = {str(item) for item in relationship_ids}
    current: list[ProjectedFactView] = []
    for raw in payload.get("visible_facts", []):
        if (
            raw.get("character_id") == str(character_id)
            or raw.get("character_instance_id") == str(instance_id)
            or raw.get("relationship_id") in relationship_id_strings
        ):
            all_character_fact_ids.add(UUID(str(raw["id"])))
    for raw in payload.get("current_facts", []):
        if (
            raw.get("character_id") != str(character_id)
            and raw.get("character_instance_id") != str(instance_id)
            and raw.get("relationship_id") not in relationship_id_strings
        ):
            continue
        fact = ProjectedFactView(
            id=UUID(str(raw["id"])),
            fact_type=str(raw["fact_type"]),
            timeline_id=UUID(str(raw["timeline_id"])),
            character_id=(
                UUID(str(raw["character_id"])) if raw.get("character_id") else None
            ),
            character_instance_id=(
                UUID(str(raw["character_instance_id"]))
                if raw.get("character_instance_id")
                else None
            ),
            relationship_id=(
                UUID(str(raw["relationship_id"]))
                if raw.get("relationship_id")
                else None
            ),
            dimension=str(raw["dimension"]),
            event_kind=str(raw["event_kind"]),
            predicate=str(raw["predicate"]),
            object_text=str(raw["object_text"]),
            details=dict(raw.get("details") or {}),
            story_sequence=raw.get("story_sequence"),
            source_revision_id=(
                UUID(str(raw["source_revision_id"]))
                if raw.get("source_revision_id")
                else None
            ),
        )
        current.append(fact)
        all_character_fact_ids.add(fact.id)
    conflicts = tuple(
        ProjectionConflictView.model_validate(item)
        for item in payload.get("conflicts", [])
        if all_character_fact_ids.intersection(
            UUID(str(fact_id)) for fact_id in item.get("fact_ids", [])
        )
    )
    ambiguous = tuple(
        sorted(
            all_character_fact_ids.intersection(
                UUID(str(item)) for item in payload.get("ambiguous_fact_ids", [])
            ),
            key=str,
        )
    )
    return CharacterProjectedState(
        timeline_id=UUID(str(payload["timeline_id"])),
        narrative_cutoff=payload.get("narrative_cutoff"),
        current_facts=tuple(current),
        conflicts=conflicts,
        ambiguous_fact_ids=ambiguous,
    )


def _fact_views(
    read_set: CharacterFactReadSet,
    *,
    projection: dict[str, Any],
    instance_id: UUID,
    relationship_ids: set[UUID],
    document_ordinals: dict[UUID, int] | None,
) -> tuple[ProjectedFactViewV2, ...]:
    ordinals = document_ordinals or {}
    return tuple(
        sorted(
            (
                _classified_fact_view(fact, read_set, ordinals)
                for fact in _classify_facts(
                    read_set,
                    projection=projection,
                    instance_id=instance_id,
                    relationship_ids=relationship_ids,
                )
            ),
            key=fact_sort_key,
            reverse=True,
        )
    )


def _classify_facts(
    read_set: CharacterFactReadSet,
    *,
    projection: dict[str, Any],
    instance_id: UUID,
    relationship_ids: set[UUID],
) -> tuple[_ClassifiedFact, ...]:
    visible_ids = {
        UUID(str(item["id"])) for item in projection.get("visible_facts", [])
    }
    current_ids = {
        UUID(str(item["id"])) for item in projection.get("current_facts", [])
    }
    ambiguous_ids = {
        UUID(str(item)) for item in projection.get("ambiguous_fact_ids", [])
    }
    suppressed_ids = {
        UUID(str(item)) for item in projection.get("suppressed_fact_ids", [])
    }
    eligible_ids = visible_ids | ambiguous_ids | suppressed_ids
    conflict_ids = {
        UUID(str(fact_id))
        for conflict in projection.get("conflicts", [])
        for fact_id in conflict.get("fact_ids", [])
    }
    results: list[_ClassifiedFact] = []
    for row in read_set.facts:
        if row.id not in eligible_ids:
            continue
        if (
            row.relationship_id not in relationship_ids
            and row.character_instance_id not in {None, instance_id}
        ):
            continue
        source_ambiguous = _fact_source_is_ambiguous(row, read_set)
        bindings = read_set.bindings_by_fact_id.get(row.id, ())
        has_reverted_batch = any(
            binding.commit_batch_id is not None
            and read_set.batch_state_by_id.get(binding.commit_batch_id) == "reverted"
            for binding in bindings
        )
        has_invalid_binding = bool(bindings) and not any(
            binding.validity_state in {"current", "source_restored"}
            for binding in bindings
        )
        if has_reverted_batch:
            effective_state: FactEffectiveState = "batch_reverted"
        elif row.id in read_set.superseded_fact_ids or row.status == "superseded":
            effective_state = "superseded"
        elif row.status in {"invalid", "source_superseded"} or has_invalid_binding:
            effective_state = "source_invalid"
        elif row.id in current_ids and _is_state_row(row):
            effective_state = "current"
        else:
            effective_state = "historical"

        health: FactHealth
        if row.id in conflict_ids:
            health = "conflict"
        elif row.id in ambiguous_ids or source_ambiguous:
            health = "ambiguous"
        else:
            health = "ok"
        results.append(
            _ClassifiedFact(
                row=row,
                effective_state=effective_state,
                health=health,
            )
        )
    return tuple(results)


def _classified_fact_view(
    fact: _ClassifiedFact,
    read_set: CharacterFactReadSet,
    document_ordinals: dict[UUID, int],
) -> ProjectedFactViewV2:
    row = fact.row
    source, _source_ambiguous = _fact_source_view(
        row, read_set, document_ordinals
    )
    return ProjectedFactViewV2(
        id=row.id,
        fact_type=row.fact_type,
        timeline_id=row.timeline_id,
        character_id=row.character_id,
        character_instance_id=row.character_instance_id,
        relationship_id=row.relationship_id,
        dimension=row.dimension or row.predicate,
        event_kind=row.event_kind or "unknown",
        predicate=row.predicate,
        object_text=row.object_text,
        details=dict(row.details or {}),
        story_sequence=row.story_sequence,
        source_revision_id=row.source_revision_id,
        source_document_id=row.source_document_id,
        story_time=(
            dict(row.story_time_json)
            if isinstance(row.story_time_json, dict)
            else None
        ),
        created_at=row.created_at or datetime(1970, 1, 1, tzinfo=UTC),
        effective_state=fact.effective_state,
        health=fact.health,
        source=source,
    )


def _story_fact_sort_key(fact: _ClassifiedFact) -> tuple[int, int, str, str]:
    row = fact.row
    created_at = row.created_at or datetime(1970, 1, 1, tzinfo=UTC)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    else:
        created_at = created_at.astimezone(UTC)
    return (
        int(row.story_sequence is not None),
        row.story_sequence if row.story_sequence is not None else -1,
        created_at.isoformat(timespec="microseconds"),
        str(row.id),
    )


def _classified_fact_history_summary(
    facts: Sequence[_ClassifiedFact],
) -> FactHistorySummary:
    counts = {
        state: sum(fact.effective_state == state for fact in facts)
        for state in (
            "current",
            "historical",
            "superseded",
            "source_invalid",
            "batch_reverted",
        )
    }
    return FactHistorySummary(total=len(facts), **counts)


def _is_state_row(row: StoryFact) -> bool:
    if row.dimension in {"action", "presence"}:
        return False
    if row.fact_type in {"relationship_state", "knowledge_event"}:
        return True
    return row.dimension in {
        "location",
        "goal",
        "health",
        "emotion",
        "identity",
        "knowledge",
        "possession",
        "relationship",
    }


def _matching_source_binding(
    row: StoryFact,
    read_set: CharacterFactReadSet,
) -> DerivedSourceBinding | None:
    bindings = read_set.bindings_by_fact_id.get(row.id, ())
    return next(
        (
            binding
            for binding in bindings
            if binding.source_chapter_revision_id == row.source_revision_id
        ),
        bindings[-1] if bindings else None,
    )


def _fact_source_is_ambiguous(
    row: StoryFact,
    read_set: CharacterFactReadSet,
) -> bool:
    if row.source_document_id is None and row.source_revision_id is None:
        return False
    if row.source_document_id is None or row.source_revision_id is None:
        return True
    document = read_set.documents_by_id.get(row.source_document_id)
    revision = read_set.revisions_by_id.get(row.source_revision_id)
    binding = _matching_source_binding(row, read_set)
    if document is None or revision is None or revision.document_id != document.id:
        return True
    if binding is None or binding.source_content_hash != revision.content_hash:
        return True
    if row.source_start is None and row.source_end is None:
        return False
    return not (
        row.source_start is not None
        and row.source_end is not None
        and 0 <= row.source_start < row.source_end <= len(revision.content_text)
    )


def _fact_source_view(
    row: StoryFact,
    read_set: CharacterFactReadSet,
    document_ordinals: dict[UUID, int],
) -> tuple[FactSourceView | None, bool]:
    if row.source_document_id is None or row.source_revision_id is None:
        return None, False
    document = read_set.documents_by_id.get(row.source_document_id)
    revision = read_set.revisions_by_id.get(row.source_revision_id)
    matching_binding = _matching_source_binding(row, read_set)
    if document is None or revision is None or revision.document_id != document.id:
        return None, True

    source_content_hash = revision.content_hash
    source_ambiguous = matching_binding is None
    if (
        matching_binding is not None
        and matching_binding.source_content_hash != revision.content_hash
    ):
        source_ambiguous = True

    source_range_hash: str | None = None
    source_excerpt = ""
    source_excerpt_truncated = False
    if row.source_start is not None and row.source_end is not None:
        if 0 <= row.source_start < row.source_end <= len(revision.content_text):
            evidence = revision.content_text[row.source_start : row.source_end]
            source_range_hash = hashlib.sha256(evidence.encode("utf-8")).hexdigest()
            source_excerpt = evidence[:500]
            source_excerpt_truncated = len(evidence) > 500
        else:
            source_ambiguous = True
    elif row.source_start is not None or row.source_end is not None:
        source_ambiguous = True

    document_position = document_ordinals.get(document.id, document.position)
    document_title = (
        context_chapter_title(document.title, document_position)
        if document.kind == "chapter"
        else document.title
    )
    return (
        FactSourceView(
            document_id=document.id,
            document_title=document_title,
            document_position=document_position,
            revision_id=revision.id,
            revision_is_current=(
                read_set.current_revision_by_document_id.get(document.id) == revision.id
            ),
            source_content_hash=source_content_hash,
            source_start=row.source_start,
            source_end=row.source_end,
            source_range_hash=source_range_hash,
            source_excerpt=source_excerpt,
            source_excerpt_truncated=source_excerpt_truncated,
            binding_state=(
                matching_binding.validity_state if matching_binding is not None else None
            ),
            proposal_item_id=(
                matching_binding.proposal_item_id if matching_binding is not None else None
            ),
            commit_batch_id=(
                matching_binding.commit_batch_id if matching_binding is not None else None
            ),
        ),
        source_ambiguous,
    )


def _encode_cursor(key: tuple[int, int, str, str]) -> str:
    payload = json.dumps(
        {"v": 1, "sequence_known": key[0], "sequence": key[1], "created": key[2], "id": key[3]},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> tuple[int, int, str, str]:
    try:
        padding = "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(value + padding))
        if set(payload) != {"v", "sequence_known", "sequence", "created", "id"}:
            raise ValueError
        if payload["v"] != 1 or payload["sequence_known"] not in {0, 1}:
            raise ValueError
        sequence = int(payload["sequence"])
        created = str(payload["created"])
        datetime.fromisoformat(created)
        fact_id = str(UUID(str(payload["id"])))
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CharacterWorkspaceError(
            CharacterWorkspaceErrorCode.INVALID_CURSOR,
            "fact history cursor is invalid",
        ) from error
    return int(payload["sequence_known"]), sequence, created, fact_id


def service_for_session(session: Session) -> CharacterWorkspaceService:
    return CharacterWorkspaceService(SqlAlchemyCharacterWorkspaceStore(session))
