"""Pure, fact-specific effective-state and health classification.

The module deliberately accepts immutable evidence instead of ORM rows.  A
caller must assemble one fact's bindings and projection evidence in its own
read snapshot; the functions below perform no database or network I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from .contracts import StoryFactStatus


class FactEffectiveState(str, Enum):
    CURRENT = "current"
    HISTORICAL = "historical"
    SUPERSEDED = "superseded"
    SOURCE_INVALID = "source_invalid"
    BATCH_REVERTED = "batch_reverted"


class FactEffectiveReasonCode(str, Enum):
    BATCH_REVERTED = "batch_reverted"
    SUPERSEDED_BY_FACT = "superseded_by_fact"
    FACT_STATUS_SUPERSEDED = "fact_status_superseded"
    FACT_STATUS_INVALID = "fact_status_invalid"
    SOURCE_NOT_APPLICABLE = "source_not_applicable"
    SOURCE_BINDING_MISSING = "source_binding_missing"
    SOURCE_BINDING_INVALID = "source_binding_invalid"
    TIMELINE_OUT_OF_SCOPE = "timeline_out_of_scope"
    AFTER_NARRATIVE_CUTOFF = "after_narrative_cutoff"
    PROJECTION_CURRENT = "projection_current"
    PROJECTION_HISTORICAL = "projection_historical"
    NON_STATE_EVENT = "non_state_event"


class FactHealth(str, Enum):
    OK = "ok"
    CONFLICT = "conflict"
    AMBIGUOUS = "ambiguous"


class FactHealthReasonCode(str, Enum):
    EXPLICIT_CONTRADICTION = "explicit_contradiction"
    SAME_POSITION_CONFLICT = "same_position_conflict"
    SOURCE_REFERENCE_INCOMPLETE = "source_reference_incomplete"
    SOURCE_HASH_MISMATCH = "source_hash_mismatch"
    SOURCE_COORDINATE_INVALID = "source_coordinate_invalid"
    STORY_SEQUENCE_AMBIGUOUS = "story_sequence_ambiguous"
    ENTITY_REFERENCE_MISSING = "entity_reference_missing"


_CURRENT_BINDING_STATES = frozenset({"current", "source_restored"})


@dataclass(frozen=True, slots=True)
class FactSourceBindingEvidence:
    """One binding supplied to a fact-specific resolution.

    ``commit_batch_state=None`` means the provenance is independent of an
    intelligence commit batch.  A caller resolving batch-backed provenance
    must supply the observed batch state from the same read snapshot.
    """

    fact_id: UUID
    source_revision_id: UUID
    validity_state: str
    commit_batch_state: str | None = None


@dataclass(frozen=True, slots=True)
class FactProjectionEvidence:
    """Projection facts already resolved from the target timeline graph."""

    timeline_in_scope: bool = True
    narrative_cutoff: int | None = None
    story_sequence: int | None = None
    story_sequence_required: bool = False
    selected_as_current: bool = False
    is_state_fact: bool = True

    def __post_init__(self) -> None:
        if self.narrative_cutoff is not None and self.narrative_cutoff < 0:
            raise ValueError("narrative_cutoff must be non-negative")
        if self.story_sequence is not None and self.story_sequence < 0:
            raise ValueError("story_sequence must be non-negative")

    @property
    def story_sequence_is_ambiguous(self) -> bool:
        return self.story_sequence_required and self.story_sequence is None


@dataclass(frozen=True, slots=True)
class FactEffectiveStateEvidence:
    fact_id: UUID
    lifecycle_status: StoryFactStatus | str
    source_revision_id: UUID | None = None
    bindings: tuple[FactSourceBindingEvidence, ...] = ()
    has_incoming_supersedes: bool = False
    projection: FactProjectionEvidence = FactProjectionEvidence()


@dataclass(frozen=True, slots=True)
class FactEffectiveStateResult:
    included_in_current_projection: bool
    effective_state: FactEffectiveState
    reason_codes: tuple[FactEffectiveReasonCode, ...]


@dataclass(frozen=True, slots=True)
class FactHealthEvidence:
    explicit_contradiction: bool = False
    same_position_conflict: bool = False
    source_reference_incomplete: bool = False
    source_hash_mismatch: bool = False
    source_coordinate_invalid: bool = False
    entity_reference_missing: bool = False
    projection: FactProjectionEvidence | None = None


@dataclass(frozen=True, slots=True)
class FactHealthResult:
    health: FactHealth
    reason_codes: tuple[FactHealthReasonCode, ...]


def resolve_fact_effective_state(
    evidence: FactEffectiveStateEvidence,
) -> FactEffectiveStateResult:
    """Resolve one fact using the frozen G0 precedence rules."""

    try:
        lifecycle = StoryFactStatus(evidence.lifecycle_status)
    except ValueError as error:
        raise ValueError(
            f"unsupported StoryFact lifecycle status: {evidence.lifecycle_status!r}"
        ) from error

    matching_bindings = tuple(
        binding
        for binding in evidence.bindings
        if binding.fact_id == evidence.fact_id
        and binding.source_revision_id == evidence.source_revision_id
    )
    has_valid_independent_provenance = any(
        binding.validity_state in _CURRENT_BINDING_STATES
        and binding.commit_batch_state != "reverted"
        for binding in matching_bindings
    )
    has_reverted_owning_binding = any(
        binding.commit_batch_state == "reverted" for binding in matching_bindings
    )

    if has_reverted_owning_binding and not has_valid_independent_provenance:
        return FactEffectiveStateResult(
            included_in_current_projection=False,
            effective_state=FactEffectiveState.BATCH_REVERTED,
            reason_codes=(FactEffectiveReasonCode.BATCH_REVERTED,),
        )

    superseded_reasons: list[FactEffectiveReasonCode] = []
    if evidence.has_incoming_supersedes:
        superseded_reasons.append(FactEffectiveReasonCode.SUPERSEDED_BY_FACT)
    if lifecycle is StoryFactStatus.SUPERSEDED:
        superseded_reasons.append(FactEffectiveReasonCode.FACT_STATUS_SUPERSEDED)
    if superseded_reasons:
        return FactEffectiveStateResult(
            included_in_current_projection=False,
            effective_state=FactEffectiveState.SUPERSEDED,
            reason_codes=tuple(superseded_reasons),
        )

    if lifecycle in {
        StoryFactStatus.INVALID,
        StoryFactStatus.SOURCE_SUPERSEDED,
    }:
        return FactEffectiveStateResult(
            included_in_current_projection=False,
            effective_state=FactEffectiveState.SOURCE_INVALID,
            reason_codes=(FactEffectiveReasonCode.FACT_STATUS_INVALID,),
        )

    source_reasons: tuple[FactEffectiveReasonCode, ...] = ()
    if evidence.source_revision_id is None:
        source_reasons = (FactEffectiveReasonCode.SOURCE_NOT_APPLICABLE,)
    elif not matching_bindings:
        return FactEffectiveStateResult(
            included_in_current_projection=False,
            effective_state=FactEffectiveState.SOURCE_INVALID,
            reason_codes=(FactEffectiveReasonCode.SOURCE_BINDING_MISSING,),
        )
    elif not has_valid_independent_provenance:
        return FactEffectiveStateResult(
            included_in_current_projection=False,
            effective_state=FactEffectiveState.SOURCE_INVALID,
            reason_codes=(FactEffectiveReasonCode.SOURCE_BINDING_INVALID,),
        )

    projection = evidence.projection
    if not projection.timeline_in_scope:
        return FactEffectiveStateResult(
            included_in_current_projection=False,
            effective_state=FactEffectiveState.HISTORICAL,
            reason_codes=source_reasons
            + (FactEffectiveReasonCode.TIMELINE_OUT_OF_SCOPE,),
        )

    if projection.narrative_cutoff is not None:
        if projection.story_sequence is None:
            return FactEffectiveStateResult(
                included_in_current_projection=False,
                effective_state=FactEffectiveState.HISTORICAL,
                reason_codes=source_reasons
                + (FactEffectiveReasonCode.PROJECTION_HISTORICAL,),
            )
        if projection.story_sequence > projection.narrative_cutoff:
            return FactEffectiveStateResult(
                included_in_current_projection=False,
                effective_state=FactEffectiveState.HISTORICAL,
                reason_codes=source_reasons
                + (FactEffectiveReasonCode.AFTER_NARRATIVE_CUTOFF,),
            )

    if projection.story_sequence_is_ambiguous:
        return FactEffectiveStateResult(
            included_in_current_projection=False,
            effective_state=FactEffectiveState.HISTORICAL,
            reason_codes=source_reasons
            + (FactEffectiveReasonCode.PROJECTION_HISTORICAL,),
        )

    if projection.is_state_fact and projection.selected_as_current:
        return FactEffectiveStateResult(
            included_in_current_projection=True,
            effective_state=FactEffectiveState.CURRENT,
            reason_codes=source_reasons
            + (FactEffectiveReasonCode.PROJECTION_CURRENT,),
        )

    historical_reason = (
        FactEffectiveReasonCode.PROJECTION_HISTORICAL
        if projection.is_state_fact
        else FactEffectiveReasonCode.NON_STATE_EVENT
    )
    return FactEffectiveStateResult(
        included_in_current_projection=True,
        effective_state=FactEffectiveState.HISTORICAL,
        reason_codes=source_reasons + (historical_reason,),
    )


def classify_fact_health(evidence: FactHealthEvidence) -> FactHealthResult:
    """Classify health without reading or changing the effective-state axis."""

    reasons: list[FactHealthReasonCode] = []
    if evidence.explicit_contradiction:
        reasons.append(FactHealthReasonCode.EXPLICIT_CONTRADICTION)
    if evidence.same_position_conflict:
        reasons.append(FactHealthReasonCode.SAME_POSITION_CONFLICT)
    if evidence.source_reference_incomplete:
        reasons.append(FactHealthReasonCode.SOURCE_REFERENCE_INCOMPLETE)
    if evidence.source_hash_mismatch:
        reasons.append(FactHealthReasonCode.SOURCE_HASH_MISMATCH)
    if evidence.source_coordinate_invalid:
        reasons.append(FactHealthReasonCode.SOURCE_COORDINATE_INVALID)
    if (
        evidence.projection is not None
        and evidence.projection.story_sequence_is_ambiguous
    ):
        reasons.append(FactHealthReasonCode.STORY_SEQUENCE_AMBIGUOUS)
    if evidence.entity_reference_missing:
        reasons.append(FactHealthReasonCode.ENTITY_REFERENCE_MISSING)

    if any(
        reason
        in {
            FactHealthReasonCode.EXPLICIT_CONTRADICTION,
            FactHealthReasonCode.SAME_POSITION_CONFLICT,
        }
        for reason in reasons
    ):
        health = FactHealth.CONFLICT
    elif reasons:
        health = FactHealth.AMBIGUOUS
    else:
        health = FactHealth.OK
    return FactHealthResult(health=health, reason_codes=tuple(reasons))


__all__ = [
    "FactEffectiveReasonCode",
    "FactEffectiveState",
    "FactEffectiveStateEvidence",
    "FactEffectiveStateResult",
    "FactHealth",
    "FactHealthEvidence",
    "FactHealthReasonCode",
    "FactHealthResult",
    "FactProjectionEvidence",
    "FactSourceBindingEvidence",
    "classify_fact_health",
    "resolve_fact_effective_state",
]
