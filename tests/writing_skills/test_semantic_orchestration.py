"""Server-only semantic button orchestration; no network or real model."""

from __future__ import annotations

import json

import pytest

from backend.writing_skills.composer import compose_writing_request
from backend.writing_skills.contracts import (
    CapabilityCatalog,
    MethodPreferences,
    SemanticRouteEvidenceV1,
    SemanticRouteEvidenceV2,
    SkillInjectionPacketV1,
    canonical_hash,
)
from backend.writing_skills.resolver import resolve_methods
from backend.writing_skills.semantic_orchestration import (
    SemanticRouteIncomplete,
    complete_button_route,
)
from backend.writing_skills.semantic_runtime import SemanticAdapterObservationV1
from tests.writing_skills.test_evaluation_contract import (
    evaluation_catalog,
    scenarios,
    synthetic_projection,
)


def _case_and_plan():
    values = scenarios()
    case = next(item for item in values["s_scenarios"] if item["id"] == "S19")
    catalog = evaluation_catalog(values)
    projection = synthetic_projection(case)
    preferences = MethodPreferences(semantic_mode="auto")
    plan = resolve_methods(projection, catalog, preferences, "prose-writing")
    return case, catalog, projection, preferences, plan


def _response(request, selected):
    return json.dumps({
        "schema_version": "semantic-route-response/1",
        "decisions": [{
            "skill_id": item.skill_id,
            "decision": "select" if item.skill_id in selected else "reject",
            "evidence_refs": [request.sources[0].key],
        } for item in request.candidates],
    }, ensure_ascii=False)


@pytest.mark.asyncio
async def test_success_is_one_call_and_returns_immutable_content_free_evidence():
    case, catalog, projection, preferences, plan = _case_and_plan()
    calls = []

    async def call(prompt, request):
        calls.append((prompt, request))
        return SemanticAdapterObservationV1(
            status="ok",
            text=_response(request, set(case["expected"])),
            model_rounds=1,
            tool_calls=0,
            transport_attempts=1,
        )

    selected, evidence = await complete_button_route(
        projection, catalog, plan, preferences, semantic_call=call
    )
    assert len(calls) == 1
    assert [item.skill_id for item in selected.selected] == case["expected"]
    assert evidence.status == "applied"
    assert evidence.auxiliary_calls == 1
    assert len(evidence.decision_hash) == 64
    assert evidence.schema_version == "semantic-route-evidence/2"
    assert evidence.request_schema == "semantic-route-request/2"
    assert evidence.prompt_contract == "semantic-routing-prompt/3"
    assert len(evidence.request_hash) == len(evidence.prompt_hash) == 64
    assert projection.sources[0].text not in evidence.model_dump_json()


@pytest.mark.asyncio
async def test_off_and_resolved_inputs_do_not_consume_an_auxiliary_call():
    _, catalog, projection, _, plan = _case_and_plan()
    calls = 0

    async def call(*_args):
        nonlocal calls
        calls += 1
        raise AssertionError("must not call")

    unchanged, evidence = await complete_button_route(
        projection, catalog, plan, MethodPreferences(), semantic_call=call
    )
    assert unchanged == plan
    assert evidence is None
    assert calls == 0


@pytest.mark.asyncio
async def test_default_closed_and_uncertain_remote_outcome_stop_generation():
    _, catalog, projection, preferences, plan = _case_and_plan()
    with pytest.raises(SemanticRouteIncomplete, match="not_released") as closed:
        await complete_button_route(
            projection, catalog, plan, preferences, semantic_call=None
        )
    assert closed.value.remote_outcome_uncertain is False

    async def unknown(_prompt, _request):
        return SemanticAdapterObservationV1(
            status="unknown",
            text=None,
            model_rounds=1,
            tool_calls=0,
            transport_attempts=1,
        )

    with pytest.raises(SemanticRouteIncomplete, match="unknown") as uncertain:
        await complete_button_route(
            projection, catalog, plan, preferences, semantic_call=unknown
        )
    assert uncertain.value.remote_outcome_uncertain is True


@pytest.mark.asyncio
async def test_unobserved_cancellation_is_not_remote_outcome_uncertainty():
    _, catalog, projection, preferences, plan = _case_and_plan()

    async def cancelled_before_model(_prompt, _request):
        return SemanticAdapterObservationV1(
            status="cancelled",
            text=None,
            model_rounds=0,
            tool_calls=0,
            transport_attempts=1,
        )

    with pytest.raises(SemanticRouteIncomplete, match="cancelled") as stopped:
        await complete_button_route(
            projection,
            catalog,
            plan,
            preferences,
            semantic_call=cancelled_before_model,
        )
    assert stopped.value.remote_outcome_uncertain is False


def test_semantic_evidence_participates_in_packet_identity():
    _, catalog, _, _, plan = _case_and_plan()
    # This test needs no loaded capability blocks: the unresolved deterministic
    # plan is composed as generic-only test evidence.
    from tests.writing_skills.test_composer import block

    base = compose_writing_request(
        plan,
        catalog,
        primary_blocks=(block(),),
        effective_input_budget=100_000,
        reserved_task_tokens=1_000,
    )
    semantic = base.model_copy(update={
        "semantic_evidence": SemanticRouteEvidenceV1(
            status="rejected", decision_hash="a" * 64
        )
    })
    assert base.method_input_hash != semantic.method_input_hash
    assert semantic.model_dump(mode="json")["semantic_evidence"] == {
        "schema_version": "semantic-route-evidence/1",
        "status": "rejected",
        "auxiliary_calls": 1,
        "decision_hash": "a" * 64,
    }
    restored = SkillInjectionPacketV1.model_validate_json(
        semantic.model_dump_json()
    )
    assert isinstance(restored.semantic_evidence, SemanticRouteEvidenceV1)

    current = base.model_copy(update={
        "semantic_evidence": SemanticRouteEvidenceV2(
            status="rejected",
            request_hash="b" * 64,
            prompt_hash="c" * 64,
            decision_hash="a" * 64,
        )
    })
    restored_current = SkillInjectionPacketV1.model_validate_json(
        current.model_dump_json()
    )
    assert isinstance(
        restored_current.semantic_evidence, SemanticRouteEvidenceV2
    )
    assert restored_current.semantic_evidence.prompt_contract == (
        "semantic-routing-prompt/3"
    )
    legacy_evidence = SemanticRouteEvidenceV2.model_validate({
        **restored_current.semantic_evidence.model_dump(mode="json"),
        "prompt_contract": "semantic-routing-prompt/2",
    })
    assert legacy_evidence.prompt_contract == "semantic-routing-prompt/2"
    assert current.method_input_hash != semantic.method_input_hash


def test_relation_change_updates_catalog_version_and_packet_identity():
    _, catalog, _, _, plan = _case_and_plan()
    from tests.writing_skills.test_composer import block

    target = next(
        item for item in catalog.capabilities
        if item.declaration.skill_id == "golden-finger-writing"
    )
    changed_declaration = target.declaration.model_copy(
        update={"supersedes": ("suspense-writing",)}
    )
    changed_target = target.model_copy(
        update={
            "declaration": changed_declaration,
            # A real routing.json edit changes the loader-owned raw file hash.
            "routing_hash": canonical_hash(changed_declaration),
        }
    )
    changed_catalog = CapabilityCatalog(
        capabilities=tuple(
            changed_target if item.declaration.skill_id == "golden-finger-writing"
            else item
            for item in catalog.capabilities
        ),
        rejected=catalog.rejected,
    )
    assert changed_catalog.version != catalog.version

    original_packet = compose_writing_request(
        plan,
        catalog,
        primary_blocks=(block(),),
        effective_input_budget=100_000,
        reserved_task_tokens=1_000,
    )
    changed_plan = plan.model_copy(
        update={"catalog_version": changed_catalog.version}
    )
    changed_packet = compose_writing_request(
        changed_plan,
        changed_catalog,
        primary_blocks=(block(),),
        effective_input_budget=100_000,
        reserved_task_tokens=1_000,
    )
    assert changed_packet.method_input_hash != original_packet.method_input_hash
