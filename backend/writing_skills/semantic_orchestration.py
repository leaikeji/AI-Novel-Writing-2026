"""Shared server-only orchestration for the unreleased semantic branch."""

from __future__ import annotations

import hashlib

from .contracts import (
    CapabilityCatalog,
    MethodPreferences,
    SemanticRouteEvidenceV2,
    SkillInvocationPlanV1,
    TaskModelInputProjectionV1,
    canonical_hash,
)
from .semantic import SemanticRoutingOutcomeV1, prepare_semantic_request
from .semantic_runtime import (
    SEMANTIC_PROMPT_CONTRACT,
    SemanticCall,
    build_semantic_prompt,
    complete_prepared_semantic_selection_async,
)


class SemanticRouteIncomplete(ValueError):
    """A semantic request cannot safely continue to writing generation."""

    def __init__(self, status: str, *, remote_outcome_uncertain: bool):
        super().__init__(f"semantic_route_{status}")
        self.status = status
        self.remote_outcome_uncertain = remote_outcome_uncertain


async def complete_button_route(
    projection: TaskModelInputProjectionV1,
    catalog: CapabilityCatalog,
    plan: SkillInvocationPlanV1,
    preferences: MethodPreferences,
    *,
    semantic_call: SemanticCall | None,
) -> tuple[SkillInvocationPlanV1, SemanticRouteEvidenceV2 | None]:
    """Optionally complete unresolved dimensions with one injected call.

    ``semantic_call`` is server-owned and never accepted from an HTTP body.
    Product endpoints pass ``None`` until a separate release gate is approved.
    """

    if preferences.semantic_mode == "off":
        return plan, None
    if semantic_call is None:
        raise SemanticRouteIncomplete(
            "not_released", remote_outcome_uncertain=False
        )
    prepared = prepare_semantic_request(
        projection,
        catalog,
        plan,
        semantic_enabled=True,
    )
    if isinstance(prepared, SemanticRoutingOutcomeV1):
        outcome = prepared
    else:
        outcome = await complete_prepared_semantic_selection_async(
            projection,
            catalog,
            plan,
            prepared,
            call=semantic_call,
        )
    if outcome.status == "not_requested":
        return outcome.plan, None
    if outcome.status not in {"applied", "rejected"}:
        raise SemanticRouteIncomplete(
            outcome.status,
            remote_outcome_uncertain=(
                outcome.auxiliary_calls == 1 and outcome.decision_hash is None
            ),
        )
    if outcome.decision_hash is None or outcome.auxiliary_calls != 1:
        raise SemanticRouteIncomplete(
            "evidence_missing", remote_outcome_uncertain=False
        )
    if isinstance(prepared, SemanticRoutingOutcomeV1):
        raise SemanticRouteIncomplete(
            "evidence_request_missing", remote_outcome_uncertain=False
        )
    prompt = build_semantic_prompt(prepared)
    return outcome.plan, SemanticRouteEvidenceV2(
        status=outcome.status,
        auxiliary_calls=outcome.auxiliary_calls,
        request_hash=canonical_hash(prepared),
        prompt_hash=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        prompt_contract=SEMANTIC_PROMPT_CONTRACT,
        decision_hash=outcome.decision_hash,
    )
