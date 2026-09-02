"""SQL-only classification and bounded page selection for Story Ledger reads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping
from uuid import UUID

from sqlalchemy import (
    String,
    and_,
    case,
    cast,
    exists,
    func,
    literal,
    or_,
    select,
)
from sqlalchemy.sql import Select

from ..creative_data_models import CharacterInstance, StoryEventLink, StoryTimeline
from ..models import (
    CharacterRelationship,
    DerivedSourceBinding,
    Document,
    DocumentRevision,
    Foreshadow,
    IntelligenceCommitBatch,
    NovelCharacter,
    StoryFact,
    Storyline,
)


EffectiveFilter = Literal[
    "current",
    "historical",
    "superseded",
    "source_invalid",
    "batch_reverted",
]
HealthFilter = Literal["ok", "conflict", "ambiguous"]
EntityType = Literal[
    "character",
    "character_instance",
    "relationship",
    "storyline",
    "foreshadow",
]

_CURRENT_BINDING_STATES = ("current", "source_restored")
_VISIBLE_LIFECYCLE_STATES = ("active", "source_restored")
_INVALID_LIFECYCLE_STATES = ("invalid", "source_superseded")
_STATE_DIMENSIONS = (
    "location",
    "goal",
    "health",
    "emotion",
    "identity",
    "knowledge",
    "possession",
    "relationship",
)


@dataclass(frozen=True, slots=True)
class LedgerQueryFilters:
    fact_types: tuple[str, ...] = ()
    effective_state: EffectiveFilter | None = None
    health: HealthFilter | None = None
    dimension: str | None = None
    source_document_id: UUID | None = None
    commit_batch_id: UUID | None = None
    fact_timeline_id: UUID | None = None
    entity_type: EntityType | None = None
    entity_id: UUID | None = None
    review_only: bool = False

    def canonical_payload(
        self,
        *,
        timeline_id: UUID | None,
        narrative_cutoff: int | None,
    ) -> dict[str, object]:
        return {
            "schema": "story-ledger-filter/1",
            "timeline_id": str(timeline_id) if timeline_id else None,
            "narrative_cutoff": narrative_cutoff,
            "fact_types": list(self.fact_types),
            "effective_state": self.effective_state,
            "health": self.health,
            "dimension": self.dimension,
            "source_document_id": (
                str(self.source_document_id) if self.source_document_id else None
            ),
            "commit_batch_id": (
                str(self.commit_batch_id) if self.commit_batch_id else None
            ),
            "fact_timeline_id": (
                str(self.fact_timeline_id) if self.fact_timeline_id else None
            ),
            "entity_type": self.entity_type,
            "entity_id": str(self.entity_id) if self.entity_id else None,
            "review_only": self.review_only,
        }


@dataclass(frozen=True, slots=True)
class TimelineQueryScope:
    timeline_id: UUID | None
    limits_by_timeline_id: Mapping[UUID, int | None]


def _classified_cte(novel_id: UUID, scope: TimelineQueryScope):
    fact = StoryFact.__table__
    binding = DerivedSourceBinding.__table__
    batch = IntelligenceCommitBatch.__table__
    link = StoryEventLink.__table__
    document = Document.__table__
    revision = DocumentRevision.__table__

    matching_binding = and_(
        binding.c.derived_entity_id == fact.c.id,
        binding.c.source_chapter_revision_id == fact.c.source_revision_id,
    )
    has_matching_binding = exists(
        select(literal(1)).select_from(binding).where(matching_binding)
    )
    has_valid_binding = exists(
        select(literal(1))
        .select_from(
            binding.outerjoin(batch, batch.c.id == binding.c.commit_batch_id)
        )
        .where(
            matching_binding,
            binding.c.validity_state.in_(_CURRENT_BINDING_STATES),
            or_(
                binding.c.commit_batch_id.is_(None),
                and_(batch.c.id.is_not(None), batch.c.state != "reverted"),
            ),
        )
    )
    has_reverted_binding = exists(
        select(literal(1))
        .select_from(binding.join(batch, batch.c.id == binding.c.commit_batch_id))
        .where(matching_binding, batch.c.state == "reverted")
    )
    has_observed_binding = exists(
        select(literal(1))
        .select_from(
            binding.outerjoin(batch, batch.c.id == binding.c.commit_batch_id)
        )
        .where(
            matching_binding,
            or_(binding.c.commit_batch_id.is_(None), batch.c.id.is_not(None)),
        )
    )
    incoming_supersedes = exists(
        select(literal(1)).select_from(link).where(
            link.c.novel_id == novel_id,
            link.c.target_fact_id == fact.c.id,
            link.c.link_type == "supersedes",
        )
    )

    source_absent = and_(
        fact.c.source_document_id.is_(None), fact.c.source_revision_id.is_(None)
    )
    source_partial = or_(
        and_(
            fact.c.source_document_id.is_(None),
            fact.c.source_revision_id.is_not(None),
        ),
        and_(
            fact.c.source_document_id.is_not(None),
            fact.c.source_revision_id.is_(None),
        ),
    )
    source_document_exists = exists(
        select(literal(1)).select_from(document).where(
            document.c.id == fact.c.source_document_id,
            document.c.novel_id == novel_id,
        )
    )
    source_revision_matches = exists(
        select(literal(1)).select_from(revision).where(
            revision.c.id == fact.c.source_revision_id,
            revision.c.document_id == fact.c.source_document_id,
        )
    )
    source_reference_incomplete = and_(
        ~source_absent,
        or_(
            source_partial,
            ~source_document_exists,
            ~source_revision_matches,
            ~has_matching_binding,
            ~has_observed_binding,
        ),
    )
    source_hash_mismatch = exists(
        select(literal(1))
        .select_from(
            binding.join(
                revision,
                revision.c.id == binding.c.source_chapter_revision_id,
            )
        )
        .where(
            matching_binding,
            binding.c.source_content_hash != revision.c.content_hash,
        )
    )
    source_coordinate_invalid = or_(
        and_(
            source_absent,
            or_(fact.c.source_start.is_not(None), fact.c.source_end.is_not(None)),
        ),
        and_(
            ~source_absent,
            or_(
                fact.c.source_start.is_(None),
                fact.c.source_end.is_(None),
                fact.c.source_start < 0,
                fact.c.source_end <= fact.c.source_start,
                ~exists(
                    select(literal(1)).select_from(revision).where(
                        revision.c.id == fact.c.source_revision_id,
                        fact.c.source_end <= func.char_length(revision.c.content_text),
                    )
                ),
            ),
        ),
    )

    missing_character = and_(
        fact.c.character_id.is_not(None),
        ~exists(
            select(literal(1)).select_from(NovelCharacter.__table__).where(
                NovelCharacter.id == fact.c.character_id,
                NovelCharacter.novel_id == novel_id,
            )
        ),
    )
    missing_instance = and_(
        fact.c.character_instance_id.is_not(None),
        ~exists(
            select(literal(1)).select_from(CharacterInstance.__table__).where(
                CharacterInstance.id == fact.c.character_instance_id,
                CharacterInstance.novel_id == novel_id,
            )
        ),
    )
    missing_relationship = and_(
        fact.c.relationship_id.is_not(None),
        ~exists(
            select(literal(1)).select_from(CharacterRelationship.__table__).where(
                CharacterRelationship.id == fact.c.relationship_id,
                CharacterRelationship.novel_id == novel_id,
            )
        ),
    )
    missing_storyline = and_(
        fact.c.storyline_id.is_not(None),
        ~exists(
            select(literal(1)).select_from(Storyline.__table__).where(
                Storyline.id == fact.c.storyline_id,
                Storyline.novel_id == novel_id,
            )
        ),
    )
    missing_foreshadow = and_(
        fact.c.foreshadow_id.is_not(None),
        ~exists(
            select(literal(1)).select_from(Foreshadow.__table__).where(
                Foreshadow.id == fact.c.foreshadow_id,
                Foreshadow.novel_id == novel_id,
            )
        ),
    )
    entity_reference_missing = or_(
        missing_character,
        missing_instance,
        missing_relationship,
        missing_storyline,
        missing_foreshadow,
    )

    if scope.limits_by_timeline_id:
        timeline_ids = tuple(scope.limits_by_timeline_id)
        timeline_in_scope = fact.c.timeline_id.in_(timeline_ids)
        cutoff_terms = tuple(
            and_(
                fact.c.timeline_id == timeline_id,
                or_(
                    fact.c.story_sequence.is_(None),
                    fact.c.story_sequence > cutoff,
                ),
            )
            for timeline_id, cutoff in scope.limits_by_timeline_id.items()
            if cutoff is not None
        )
        cutoff_blocked = or_(*cutoff_terms) if cutoff_terms else literal(False)
    else:
        timeline_in_scope = literal(True)
        cutoff_blocked = literal(False)

    source_valid = or_(fact.c.source_revision_id.is_(None), has_valid_binding)
    visible_lifecycle = fact.c.status.in_(_VISIBLE_LIFECYCLE_STATES)
    projection_eligible = and_(
        visible_lifecycle,
        source_valid,
        ~incoming_supersedes,
        timeline_in_scope,
        ~cutoff_blocked,
    )
    sequence_ambiguous = and_(
        projection_eligible, fact.c.story_sequence.is_(None)
    )
    is_state_fact = and_(
        or_(
            fact.c.fact_type.in_(("relationship_state", "knowledge_event")),
            fact.c.dimension.in_(_STATE_DIMENSIONS),
        ),
        or_(fact.c.dimension.is_(None), ~fact.c.dimension.in_(("action", "presence"))),
    )
    stable_entity = case(
        (
            fact.c.character_instance_id.is_not(None),
            cast(fact.c.character_instance_id, String),
        ),
        (
            fact.c.relationship_id.is_not(None),
            cast(fact.c.relationship_id, String),
        ),
        (fact.c.storyline_id.is_not(None), cast(fact.c.storyline_id, String)),
        (fact.c.foreshadow_id.is_not(None), cast(fact.c.foreshadow_id, String)),
        (fact.c.character_id.is_not(None), cast(fact.c.character_id, String)),
        else_=fact.c.subject,
    )
    slot_key = func.concat_ws(
        "|",
        fact.c.fact_type,
        stable_entity,
        func.coalesce(fact.c.dimension, ""),
        fact.c.predicate,
    )
    value_key = func.md5(
        func.concat(fact.c.object_text, "\x1f", cast(fact.c.details, String))
    )

    base = (
        select(
            *fact.c,
            has_valid_binding.label("has_valid_binding"),
            has_reverted_binding.label("has_reverted_binding"),
            incoming_supersedes.label("incoming_supersedes"),
            timeline_in_scope.label("timeline_in_scope"),
            cutoff_blocked.label("cutoff_blocked"),
            projection_eligible.label("projection_eligible"),
            sequence_ambiguous.label("sequence_ambiguous"),
            is_state_fact.label("is_state_fact"),
            source_reference_incomplete.label("source_reference_incomplete"),
            source_hash_mismatch.label("source_hash_mismatch"),
            source_coordinate_invalid.label("source_coordinate_invalid"),
            entity_reference_missing.label("entity_reference_missing"),
            slot_key.label("slot_key"),
            value_key.label("value_key"),
        )
        .where(
            fact.c.novel_id == novel_id,
            fact.c.schema_version == "story-fact/2",
        )
        .cte("ledger_fact_base")
    )
    candidates = (
        select(
            base.c.id,
            base.c.slot_key,
            base.c.story_sequence,
            base.c.value_key,
        )
        .where(base.c.projection_eligible, base.c.story_sequence.is_not(None))
        .cte("ledger_projection_candidates")
    )
    maxima = (
        select(
            candidates.c.slot_key,
            func.max(candidates.c.story_sequence).label("max_story_sequence"),
        )
        .group_by(candidates.c.slot_key)
        .cte("ledger_slot_maxima")
    )
    latest = (
        select(
            candidates.c.slot_key,
            maxima.c.max_story_sequence,
            func.count(func.distinct(candidates.c.value_key)).label(
                "distinct_value_count"
            ),
        )
        .join(
            maxima,
            and_(
                maxima.c.slot_key == candidates.c.slot_key,
                maxima.c.max_story_sequence == candidates.c.story_sequence,
            ),
        )
        .group_by(candidates.c.slot_key, maxima.c.max_story_sequence)
        .cte("ledger_latest_values")
    )

    source_candidate = candidates.alias("ledger_contradiction_source")
    target_candidate = candidates.alias("ledger_contradiction_target")
    contradiction_sources = (
        select(link.c.source_fact_id.label("fact_id"))
        .select_from(
            link.join(
                source_candidate,
                source_candidate.c.id == link.c.source_fact_id,
            ).join(
                target_candidate,
                target_candidate.c.id == link.c.target_fact_id,
            )
        )
        .where(link.c.novel_id == novel_id, link.c.link_type == "contradicts")
    )
    contradiction_targets = (
        select(link.c.target_fact_id.label("fact_id"))
        .select_from(
            link.join(
                source_candidate,
                source_candidate.c.id == link.c.source_fact_id,
            ).join(
                target_candidate,
                target_candidate.c.id == link.c.target_fact_id,
            )
        )
        .where(link.c.novel_id == novel_id, link.c.link_type == "contradicts")
    )
    contradiction_ids = contradiction_sources.union_all(
        contradiction_targets
    ).cte("ledger_contradiction_ids")
    explicit_contradiction = exists(
        select(literal(1)).select_from(contradiction_ids).where(
            contradiction_ids.c.fact_id == base.c.id
        )
    )
    latest_at_position = and_(
        base.c.story_sequence.is_not(None),
        base.c.story_sequence == latest.c.max_story_sequence,
    )
    same_position_conflict = and_(
        latest_at_position, latest.c.distinct_value_count > 1
    )
    selected_as_current = and_(
        base.c.projection_eligible,
        latest_at_position,
        latest.c.distinct_value_count == 1,
        ~explicit_contradiction,
    )

    batch_reverted = and_(
        base.c.has_reverted_binding, ~base.c.has_valid_binding
    )
    lifecycle_superseded = base.c.status == "superseded"
    lifecycle_invalid = or_(
        base.c.status.in_(_INVALID_LIFECYCLE_STATES),
        ~base.c.status.in_(
            _VISIBLE_LIFECYCLE_STATES + ("superseded",) + _INVALID_LIFECYCLE_STATES
        ),
    )
    source_invalid = and_(
        base.c.source_revision_id.is_not(None), ~base.c.has_valid_binding
    )
    effective_state = case(
        (batch_reverted, "batch_reverted"),
        (
            or_(base.c.incoming_supersedes, lifecycle_superseded),
            "superseded",
        ),
        (or_(lifecycle_invalid, source_invalid), "source_invalid"),
        (~base.c.timeline_in_scope, "historical"),
        (base.c.cutoff_blocked, "historical"),
        (base.c.sequence_ambiguous, "historical"),
        (and_(base.c.is_state_fact, selected_as_current), "current"),
        else_="historical",
    )
    included = case(
        (batch_reverted, literal(False)),
        (
            or_(base.c.incoming_supersedes, lifecycle_superseded),
            literal(False),
        ),
        (or_(lifecycle_invalid, source_invalid), literal(False)),
        (~base.c.timeline_in_scope, literal(False)),
        (base.c.cutoff_blocked, literal(False)),
        (base.c.sequence_ambiguous, literal(False)),
        else_=literal(True),
    )
    conflict = or_(explicit_contradiction, same_position_conflict)
    ambiguous = or_(
        base.c.source_reference_incomplete,
        base.c.source_hash_mismatch,
        base.c.source_coordinate_invalid,
        base.c.sequence_ambiguous,
        base.c.entity_reference_missing,
    )
    health = case(
        (conflict, "conflict"),
        (ambiguous, "ambiguous"),
        else_="ok",
    )
    return (
        select(
            *(
                column
                for column in base.c
                if column.key not in {"effective_state", "health"}
            ),
            explicit_contradiction.label("explicit_contradiction"),
            same_position_conflict.label("same_position_conflict"),
            selected_as_current.label("selected_as_current"),
            effective_state.label("effective_state"),
            included.label("included_in_current_projection"),
            health.label("health"),
        )
        .select_from(base.outerjoin(latest, latest.c.slot_key == base.c.slot_key))
        .cte("ledger_classified_facts")
    )


def _filter_conditions(classified, filters: LedgerQueryFilters):
    conditions = []
    if filters.fact_types:
        conditions.append(classified.c.fact_type.in_(filters.fact_types))
    if filters.effective_state is not None:
        conditions.append(
            classified.c.effective_state == filters.effective_state
        )
    if filters.health is not None:
        conditions.append(classified.c.health == filters.health)
    if filters.dimension is not None:
        conditions.append(
            func.coalesce(classified.c.dimension, classified.c.predicate)
            == filters.dimension
        )
    if filters.source_document_id is not None:
        conditions.append(
            classified.c.source_document_id == filters.source_document_id
        )
    if filters.fact_timeline_id is not None:
        conditions.append(classified.c.timeline_id == filters.fact_timeline_id)
    if filters.commit_batch_id is not None:
        binding = DerivedSourceBinding.__table__
        conditions.append(
            exists(
                select(literal(1)).select_from(binding).where(
                    binding.c.derived_entity_id == classified.c.id,
                    binding.c.commit_batch_id == filters.commit_batch_id,
                )
            )
        )
    entity_column = None
    if filters.entity_type == "character":
        entity_column = classified.c.character_id
    elif filters.entity_type == "character_instance":
        entity_column = classified.c.character_instance_id
    elif filters.entity_type == "relationship":
        entity_column = classified.c.relationship_id
    elif filters.entity_type == "storyline":
        entity_column = classified.c.storyline_id
    elif filters.entity_type == "foreshadow":
        entity_column = classified.c.foreshadow_id
    if entity_column is not None:
        conditions.append(entity_column.is_not(None))
        if filters.entity_id is not None:
            conditions.append(entity_column == filters.entity_id)
    elif filters.entity_id is not None:
        conditions.append(
            or_(
                classified.c.character_id == filters.entity_id,
                classified.c.character_instance_id == filters.entity_id,
                classified.c.relationship_id == filters.entity_id,
                classified.c.storyline_id == filters.entity_id,
                classified.c.foreshadow_id == filters.entity_id,
            )
        )
    if filters.review_only:
        conditions.append(
            or_(
                classified.c.health != "ok",
                classified.c.effective_state == "source_invalid",
            )
        )
    return tuple(conditions)


def _raw_filter_conditions(fact, filters: LedgerQueryFilters):
    """Filters answerable from StoryFact plus a bounded binding existence check."""

    conditions = []
    if filters.fact_types:
        conditions.append(fact.c.fact_type.in_(filters.fact_types))
    if filters.dimension is not None:
        conditions.append(
            func.coalesce(fact.c.dimension, fact.c.predicate) == filters.dimension
        )
    if filters.source_document_id is not None:
        conditions.append(fact.c.source_document_id == filters.source_document_id)
    if filters.fact_timeline_id is not None:
        conditions.append(fact.c.timeline_id == filters.fact_timeline_id)
    if filters.commit_batch_id is not None:
        binding = DerivedSourceBinding.__table__
        conditions.append(
            exists(
                select(literal(1)).select_from(binding).where(
                    binding.c.derived_entity_id == fact.c.id,
                    binding.c.commit_batch_id == filters.commit_batch_id,
                )
            )
        )
    entity_column = None
    if filters.entity_type == "character":
        entity_column = fact.c.character_id
    elif filters.entity_type == "character_instance":
        entity_column = fact.c.character_instance_id
    elif filters.entity_type == "relationship":
        entity_column = fact.c.relationship_id
    elif filters.entity_type == "storyline":
        entity_column = fact.c.storyline_id
    elif filters.entity_type == "foreshadow":
        entity_column = fact.c.foreshadow_id
    if entity_column is not None:
        conditions.append(entity_column.is_not(None))
        if filters.entity_id is not None:
            conditions.append(entity_column == filters.entity_id)
    elif filters.entity_id is not None:
        conditions.append(
            or_(
                fact.c.character_id == filters.entity_id,
                fact.c.character_instance_id == filters.entity_id,
                fact.c.relationship_id == filters.entity_id,
                fact.c.storyline_id == filters.entity_id,
                fact.c.foreshadow_id == filters.entity_id,
            )
        )
    return tuple(conditions)


def filters_require_classified_scan(filters: LedgerQueryFilters) -> bool:
    return (
        filters.effective_state is not None
        or filters.health is not None
        or filters.review_only
    )


def raw_page_ids_statement(
    novel_id: UUID,
    filters: LedgerQueryFilters,
    *,
    limit: int,
    before_created_at=None,
    before_fact_id: UUID | None = None,
) -> Select:
    fact = StoryFact.__table__
    conditions = [
        fact.c.novel_id == novel_id,
        fact.c.schema_version == "story-fact/2",
    ]
    conditions.extend(_raw_filter_conditions(fact, filters))
    if before_created_at is not None and before_fact_id is not None:
        conditions.append(
            or_(
                fact.c.created_at < before_created_at,
                and_(
                    fact.c.created_at == before_created_at,
                    fact.c.id < before_fact_id,
                ),
            )
        )
    return (
        select(fact.c.id, fact.c.created_at)
        .where(*conditions)
        .order_by(fact.c.created_at.desc(), fact.c.id.desc())
        .limit(limit + 1)
    )


def classify_fact_ids_statement(
    novel_id: UUID,
    scope: TimelineQueryScope,
    fact_ids: tuple[UUID, ...],
) -> Select:
    classified = _classified_cte(novel_id, scope)
    return select(*_page_identity_columns(classified)).where(
        classified.c.id.in_(fact_ids)
    )


def page_statement(
    novel_id: UUID,
    scope: TimelineQueryScope,
    filters: LedgerQueryFilters,
    *,
    limit: int,
    before_created_at=None,
    before_fact_id: UUID | None = None,
) -> Select:
    classified = _classified_cte(novel_id, scope)
    conditions = list(_filter_conditions(classified, filters))
    if before_created_at is not None and before_fact_id is not None:
        conditions.append(
            or_(
                classified.c.created_at < before_created_at,
                and_(
                    classified.c.created_at == before_created_at,
                    classified.c.id < before_fact_id,
                ),
            )
        )
    return (
        select(*_page_identity_columns(classified))
        .where(*conditions)
        .order_by(classified.c.created_at.desc(), classified.c.id.desc())
        .limit(limit + 1)
    )


def summary_statement(
    novel_id: UUID,
    scope: TimelineQueryScope,
    filters: LedgerQueryFilters,
) -> Select:
    classified = _classified_cte(novel_id, scope)
    return (
        select(
            classified.c.fact_type,
            classified.c.effective_state,
            classified.c.health,
            func.count().label("fact_count"),
        )
        .where(*_filter_conditions(classified, filters))
        .group_by(
            classified.c.fact_type,
            classified.c.effective_state,
            classified.c.health,
        )
    )


def fact_statement(
    novel_id: UUID,
    scope: TimelineQueryScope,
    fact_id: UUID,
) -> Select:
    classified = _classified_cte(novel_id, scope)
    return select(*_page_identity_columns(classified)).where(
        classified.c.id == fact_id
    )


def _page_identity_columns(classified):
    """Return only page identity and resolver evidence, never fact payloads."""

    return (
        classified.c.id,
        classified.c.created_at,
        classified.c.timeline_in_scope,
        classified.c.sequence_ambiguous,
        classified.c.selected_as_current,
        classified.c.is_state_fact,
        classified.c.explicit_contradiction,
        classified.c.same_position_conflict,
        classified.c.effective_state,
        classified.c.health,
    )


__all__ = [
    "EffectiveFilter",
    "EntityType",
    "HealthFilter",
    "LedgerQueryFilters",
    "TimelineQueryScope",
    "fact_statement",
    "classify_fact_ids_statement",
    "filters_require_classified_scan",
    "page_statement",
    "raw_page_ids_statement",
    "summary_statement",
]
