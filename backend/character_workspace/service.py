"""Read-only character workspace and archive-impact aggregation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, Sequence
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..creative_data_models import (
    CharacterInstance,
    CharacterInstanceRevision,
    NovelCharacterRevision,
    StoryTimeline,
)
from ..models import (
    ChapterBrief,
    CharacterAlias,
    CharacterRelationship,
    CharacterVoiceBinding,
    Document,
    Novel,
    NovelCharacter,
    StoryFact,
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
from .contracts import (
    ArchiveImpactReference,
    ChapterCharacterReference,
    CharacterAliasView,
    CharacterArchiveImpactV1,
    CharacterInstanceView,
    CharacterProjectedState,
    CharacterRelationshipView,
    CharacterRootView,
    CharacterVoiceBindingView,
    CharacterWorkspaceError,
    CharacterWorkspaceErrorCode,
    CharacterWorkspaceV1,
    ProjectedFactView,
    ProjectionConflictView,
    TimelineView,
)


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
            .where(Document.novel_id == novel_id, Document.kind == "chapter")
            .order_by(Document.position, Document.id)
        )

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


@dataclass(slots=True)
class CharacterWorkspaceService:
    store: CharacterWorkspaceStore

    def get_workspace(
        self,
        novel_id: UUID,
        character_id: UUID,
        *,
        timeline_id: UUID | None = None,
        character_instance_id: UUID | None = None,
        narrative_cutoff: int | None = None,
    ) -> CharacterWorkspaceV1:
        novel = self.store.novel(novel_id)
        if novel is None:
            raise CharacterWorkspaceError(
                CharacterWorkspaceErrorCode.CHARACTER_NOT_FOUND,
                "novel or character was not found",
            )
        root = self._require_character(novel_id, character_id)
        timelines = tuple(self.store.timelines(novel_id))
        instances = tuple(self.store.instances(novel_id, character_id))
        try:
            resolved_timeline = resolve_timeline(
                tuple(StoryTimelineRecord.model_validate(item) for item in timelines),
                novel_id,
                timeline_id,
            )
            active_timelines = tuple(
                item for item in timelines if item.lifecycle_state == "active"
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

        try:
            projection = self.store.projection(
                novel_id, resolved_timeline.id, narrative_cutoff
            )
        except StoryStateError as error:
            raise self._workspace_error(error) from error
        root_revision = self.store.character_revision(root)
        relationship_rows = tuple(
            row
            for row in self.store.relationships(novel_id, character_id)
            if row.archived_at is None
            and (row.timeline_id is None or row.timeline_id == resolved_timeline.id)
            and (
                (
                    row.source_character_id == character_id
                    and row.source_character_instance_id in {None, resolved_instance.id}
                )
                or (
                    row.target_character_id == character_id
                    and row.target_character_instance_id in {None, resolved_instance.id}
                )
            )
        )
        relationship_ids = {row.id for row in relationship_rows}
        workspace_facts = self.store.story_facts(
            novel_id, character_id, tuple(relationship_ids)
        )
        character_fact_ids = {
            row.id
            for row in workspace_facts
            if row.relationship_id in relationship_ids
            or row.character_instance_id in {None, resolved_instance.id}
        }
        return CharacterWorkspaceV1(
            novel_id=novel_id,
            character_catalog_version=novel.character_catalog_version,
            story_ledger_version=novel.story_ledger_version,
            timeline_mode="multiple" if len(active_timelines) > 1 else "single",
            character=CharacterRootView(
                id=root.id,
                novel_id=root.novel_id,
                name=root.name,
                role_type=root.role_type,
                description=root.description,
                details=dict(root.details or {}),
                lifecycle_state=root.lifecycle_state,
                position=root.position,
                version=root.version,
                current_revision_id=root_revision.id if root_revision else None,
            ),
            selected_timeline=_timeline_view(resolved_timeline),
            selected_instance=self._instance_view(
                next(item for item in instances if item.id == resolved_instance.id)
            ),
            timelines=tuple(
                _timeline_view(StoryTimelineRecord.model_validate(item))
                for item in timelines
                if item.lifecycle_state == "active"
            ),
            instances=tuple(self._instance_view(item) for item in instances),
            aliases=tuple(
                _alias_view(item)
                for item in self.store.aliases(novel_id, character_id)
                if item.lifecycle_state != "archived"
                and item.timeline_id in {None, resolved_timeline.id}
                and item.character_instance_id in {None, resolved_instance.id}
            ),
            relationships=tuple(_relationship_view(item) for item in relationship_rows),
            chapter_references=_chapter_references(
                self.store.chapter_briefs(novel_id),
                character_id=character_id,
                instance_id=resolved_instance.id,
                timeline_id=resolved_timeline.id,
            ),
            voice_binding=_voice_binding_view(
                self.store.voice_binding(novel_id, character_id)
            ),
            projected_state=_projected_state(
                projection,
                character_id=character_id,
                instance_id=resolved_instance.id,
                character_fact_ids=character_fact_ids,
                relationship_ids=relationship_ids,
            ),
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
) -> tuple[ChapterCharacterReference, ...]:
    results: list[ChapterCharacterReference] = []
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
                document_title=document.title,
                document_position=document.position,
                reference_kinds=tuple(dict.fromkeys(kind for kind, _ in matches)),
                character_instance_id=matches[0][1],
                timeline_id=brief_timeline_id,
            )
        )
    return tuple(results)


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


def service_for_session(session: Session) -> CharacterWorkspaceService:
    return CharacterWorkspaceService(SqlAlchemyCharacterWorkspaceStore(session))
