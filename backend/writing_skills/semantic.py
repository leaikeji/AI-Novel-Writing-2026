"""Fail-closed semantic completion for unresolved writing-method dimensions.

This module owns no model transport.  A runtime adapter may make exactly one
bounded call and must return observable counters; deterministic requests never
enter this module's transport path.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from .contracts import (
    CapabilityCatalog,
    FrozenModel,
    MethodSelection,
    SkillId,
    SkillInvocationPlanV1,
    SourceItem,
    Task,
    TaskModelInputProjectionV1,
    canonical_hash,
)


class SemanticGateError(ValueError):
    """The semantic branch cannot prove its one-call, no-tool contract."""


class SemanticCandidateV1(FrozenModel):
    skill_id: SkillId
    kind: Literal["genre", "mechanism"]
    description: str = Field(min_length=1, max_length=600)
    semantic_criteria: tuple[str, ...] = Field(min_length=1, max_length=16)
    negative_examples: tuple[str, ...] = Field(min_length=1, max_length=16)
    conflicts_with: tuple[SkillId, ...] = ()
    supersedes: tuple[SkillId, ...] = ()

    @model_validator(mode="after")
    def relations_are_unambiguous(self) -> "SemanticCandidateV1":
        if (
            len(set(self.conflicts_with)) != len(self.conflicts_with)
            or len(set(self.supersedes)) != len(self.supersedes)
            or self.skill_id in self.conflicts_with
            or self.skill_id in self.supersedes
            or set(self.conflicts_with) & set(self.supersedes)
        ):
            raise ValueError("invalid semantic candidate relations")
        return self


class SemanticRouteRequestV2(FrozenModel):
    schema_version: Literal["semantic-route-request/2"] = "semantic-route-request/2"
    purpose: Literal["writing_skill_routing"] = "writing_skill_routing"
    source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    catalog_version: str = Field(pattern=r"^[a-f0-9]{64}$")
    task: Task
    intent: Literal["fresh", "refine", "write", "review"]
    operation: Literal["", "polish", "rewrite", "expand", "shorten", "dialogue", "review", "custom"]
    sources: tuple[SourceItem, ...]
    candidates: tuple[SemanticCandidateV1, ...] = Field(min_length=1, max_length=32)
    tools: tuple[()] = ()
    max_model_rounds: Literal[1] = 1
    max_transport_attempts: Literal[1] = 1


class SemanticCapabilityDecisionV1(FrozenModel):
    skill_id: SkillId
    decision: Literal["select", "reject", "unknown"]
    evidence_refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def evidence_matches_decision(self) -> "SemanticCapabilityDecisionV1":
        if self.decision == "unknown" and self.evidence_refs:
            raise ValueError("unknown decision cannot claim evidence")
        if self.decision != "unknown" and not self.evidence_refs:
            raise ValueError("select and reject decisions require evidence")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("duplicate semantic evidence reference")
        return self


class SemanticRouteResponseV1(FrozenModel):
    schema_version: Literal["semantic-route-response/1"] = "semantic-route-response/1"
    decisions: tuple[SemanticCapabilityDecisionV1, ...] = Field(min_length=1)


class SemanticTransportResultV1(FrozenModel):
    schema_version: Literal["semantic-transport-result/1"] = "semantic-transport-result/1"
    status: Literal["ok", "timeout", "cancelled", "unknown", "failed"]
    payload: object | None = None
    model_rounds: int = Field(ge=0, le=8)
    tool_calls: int = Field(ge=0, le=64)
    transport_attempts: int = Field(ge=0, le=8)
    recursion_detected: bool = False


class SemanticRoutingOutcomeV1(FrozenModel):
    schema_version: Literal["semantic-routing-outcome/1"] = "semantic-routing-outcome/1"
    status: Literal[
        "not_requested", "applied", "rejected", "timeout", "cancelled",
        "unknown", "failed",
    ]
    plan: SkillInvocationPlanV1
    auxiliary_calls: Literal[0, 1]
    decision_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


def _unchanged(plan: SkillInvocationPlanV1, status: str, calls: int) -> SemanticRoutingOutcomeV1:
    return SemanticRoutingOutcomeV1(status=status, plan=plan, auxiliary_calls=calls)


def _semantic_candidates(
    catalog: CapabilityCatalog, unresolved: tuple[SkillId, ...]
) -> tuple[SemanticCandidateV1, ...]:
    capability_by_id = {
        item.declaration.skill_id: item for item in catalog.capabilities
    }
    if any(skill_id not in capability_by_id for skill_id in unresolved):
        raise SemanticGateError("unresolved_capability_missing")
    return tuple(
        SemanticCandidateV1(
            skill_id=skill_id,
            kind=capability_by_id[skill_id].declaration.kind,
            description=capability_by_id[skill_id].declaration.description,
            semantic_criteria=capability_by_id[skill_id].declaration.semantic_criteria,
            negative_examples=capability_by_id[skill_id].declaration.negative_examples,
            conflicts_with=capability_by_id[skill_id].declaration.conflicts_with,
            supersedes=capability_by_id[skill_id].declaration.supersedes,
        )
        for skill_id in unresolved
    )


def prepare_semantic_request(
    projection: TaskModelInputProjectionV1,
    catalog: CapabilityCatalog,
    plan: SkillInvocationPlanV1,
    *,
    semantic_enabled: bool,
    cancelled: Callable[[], bool] = lambda: False,
    routing_depth: int = 0,
) -> SemanticRouteRequestV2 | SemanticRoutingOutcomeV1:
    """Return a frozen request, or a zero-call terminal outcome.

    This phase owns no transport and is shared by the synchronous test adapter
    and the asynchronous product adapter.
    """
    if projection.source_hash != plan.source_hash or catalog.version != plan.catalog_version:
        raise SemanticGateError("semantic_scope_or_catalog_mismatch")
    if not semantic_enabled or not plan.unresolved_ids:
        return _unchanged(plan, "not_requested", 0)
    if projection.task in ("mechanical", "excluded"):
        return _unchanged(plan, "not_requested", 0)
    if routing_depth:
        raise SemanticGateError("semantic_recursion_blocked")
    if cancelled():
        return _unchanged(plan, "cancelled", 0)

    unresolved = tuple(sorted(set(plan.unresolved_ids)))
    return SemanticRouteRequestV2(
        source_hash=projection.source_hash,
        catalog_version=catalog.version,
        task=projection.task,
        intent=projection.intent,
        operation=projection.operation,
        sources=projection.sources,
        candidates=_semantic_candidates(catalog, unresolved),
    )


def apply_semantic_transport(
    projection: TaskModelInputProjectionV1,
    catalog: CapabilityCatalog,
    plan: SkillInvocationPlanV1,
    request: SemanticRouteRequestV2,
    transport: SemanticTransportResultV1,
    *,
    cancelled: Callable[[], bool] = lambda: False,
) -> SemanticRoutingOutcomeV1:
    """Validate and merge one observed transport result, fail closed."""
    capability_by_id = {
        item.declaration.skill_id: item for item in catalog.capabilities
    }
    unresolved = tuple(sorted(set(plan.unresolved_ids)))
    if projection.source_hash != plan.source_hash or catalog.version != plan.catalog_version:
        raise SemanticGateError("semantic_scope_or_catalog_mismatch")
    if (request.source_hash != projection.source_hash
            or request.catalog_version != catalog.version
            or request.task != projection.task
            or request.intent != projection.intent
            or request.operation != projection.operation
            or request.sources != projection.sources):
        raise SemanticGateError("semantic_request_changed")
    if request.candidates != _semantic_candidates(catalog, unresolved):
        raise SemanticGateError("semantic_request_candidate_mismatch")
    if (
        transport.model_rounds > 1
        or transport.tool_calls != 0
        or transport.transport_attempts > 1
        or transport.recursion_detected
    ):
        raise SemanticGateError("semantic_transport_contract_violation")
    if transport.status != "ok":
        status = transport.status if transport.status in {
            "timeout", "cancelled", "unknown", "failed"
        } else "failed"
        return _unchanged(plan, status, 1)
    if (
        transport.model_rounds != 1
        or transport.transport_attempts != 1
        or cancelled()
    ):
        if cancelled():
            return _unchanged(plan, "cancelled", 1)
        raise SemanticGateError("semantic_success_without_one_call")
    try:
        response = SemanticRouteResponseV1.model_validate(transport.payload)
    except (ValidationError, TypeError, ValueError) as exc:
        raise SemanticGateError("invalid_semantic_payload") from exc

    decisions = {item.skill_id: item for item in response.decisions}
    if len(decisions) != len(response.decisions) or set(decisions) != set(unresolved):
        raise SemanticGateError("semantic_candidate_set_mismatch")
    source_keys = {item.key for item in projection.sources}
    if any(not set(item.evidence_refs) <= source_keys for item in response.decisions):
        raise SemanticGateError("semantic_evidence_out_of_scope")

    selections = list(plan.selected)
    selected_ids = {item.skill_id for item in selections}
    semantic_selected = sorted(
        (item for item in response.decisions if item.decision == "select"),
        key=lambda item: (
            0 if capability_by_id[item.skill_id].declaration.kind == "genre" else 1,
            item.skill_id,
        ),
    )
    for decision in semantic_selected:
        declaration = capability_by_id[decision.skill_id].declaration
        for previous_id in selected_ids:
            previous = capability_by_id[previous_id].declaration
            if (
                previous_id in (*declaration.conflicts_with, *declaration.supersedes)
                or decision.skill_id in (*previous.conflicts_with, *previous.supersedes)
            ):
                raise SemanticGateError("semantic_method_conflict")
        if len(selections) >= 2:
            raise SemanticGateError("semantic_capability_limit")
        selections.append(MethodSelection(
            skill_id=decision.skill_id,
            evidence_refs=decision.evidence_refs,
            basis="semantic",
            reference_keys=tuple(sorted(
                rule.key for rule in declaration.reference_rules
                if projection.task in rule.tasks
            )),
        ))
        selected_ids.add(decision.skill_id)

    remaining = tuple(sorted(
        item.skill_id for item in response.decisions if item.decision == "unknown"
    ))
    dimension_states = {
        "genre": plan.genre_state,
        "mechanism": plan.mechanism_state,
    }
    for dimension in dimension_states:
        dimension_ids = {
            skill_id for skill_id in unresolved
            if capability_by_id[skill_id].declaration.kind == dimension
        }
        if dimension_ids and not dimension_ids & set(remaining):
            dimension_states[dimension] = "resolved"
    reasons = tuple(
        reason for reason in plan.reasons
        if reason != "unresolved_requires_semantic_evidence"
    )
    if remaining:
        reasons = (*reasons, "unresolved_requires_semantic_evidence")
    reasons = (*reasons, "semantic_evidence_applied" if semantic_selected
               else "semantic_evidence_rejected")
    enriched = plan.model_copy(update={
        "selected": tuple(selections),
        "genre_state": dimension_states["genre"],
        "mechanism_state": dimension_states["mechanism"],
        "unresolved_ids": remaining,
        "reasons": reasons,
    })
    return SemanticRoutingOutcomeV1(
        status=("unknown" if remaining else
                "applied" if semantic_selected else "rejected"),
        plan=enriched,
        auxiliary_calls=1,
        decision_hash=canonical_hash(response),
    )


def complete_semantic_selection(
    projection: TaskModelInputProjectionV1,
    catalog: CapabilityCatalog,
    plan: SkillInvocationPlanV1,
    *,
    semantic_enabled: bool,
    invoke: Callable[[SemanticRouteRequestV2], SemanticTransportResultV1],
    cancelled: Callable[[], bool] = lambda: False,
    routing_depth: int = 0,
) -> SemanticRoutingOutcomeV1:
    """Complete all unresolved candidates with at most one observable call.

    Failures never become an empty successful selection. Invalid counters,
    candidate IDs, evidence references, conflicts, or payloads raise before a
    generated writing request can be dispatched.
    """
    prepared = prepare_semantic_request(
        projection,
        catalog,
        plan,
        semantic_enabled=semantic_enabled,
        cancelled=cancelled,
        routing_depth=routing_depth,
    )
    if isinstance(prepared, SemanticRoutingOutcomeV1):
        return prepared
    try:
        transport = invoke(prepared)
    except Exception as exc:
        raise SemanticGateError("semantic_transport_error") from exc
    return apply_semantic_transport(
        projection,
        catalog,
        plan,
        prepared,
        transport,
        cancelled=cancelled,
    )
