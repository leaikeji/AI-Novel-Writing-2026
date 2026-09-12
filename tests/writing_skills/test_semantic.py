"""Pure fake-transport tests for the separately gated semantic branch."""

from __future__ import annotations

from copy import deepcopy

import pytest

from backend.writing_skills.contracts import MethodPreferences
from backend.writing_skills.resolver import resolve_methods
from backend.writing_skills.semantic import (
    SemanticGateError,
    SemanticTransportResultV1,
    apply_semantic_transport,
    complete_semantic_selection,
    prepare_semantic_request,
)
from tests.writing_skills.test_evaluation_contract import (
    evaluation_catalog,
    synthetic_projection as projection,
    scenarios,
)


def transport(payload, *, status="ok", rounds=1, tools=0, attempts=1, recursion=False):
    return SemanticTransportResultV1(
        status=status,
        payload=payload,
        model_rounds=rounds,
        tool_calls=tools,
        transport_attempts=attempts,
        recursion_detected=recursion,
    )


def plan_for(case, catalog):
    return resolve_methods(
        projection(case), catalog,
        MethodPreferences.model_validate(case.get("preferences", {})),
        "prose-writing",
    )


def response_for(request, selected, *, unknown=()):
    evidence = request.sources[0].key
    return {
        "schema_version": "semantic-route-response/1",
        "decisions": [{
            "skill_id": candidate.skill_id,
            "decision": (
                "unknown" if candidate.skill_id in unknown else
                "select" if candidate.skill_id in selected else "reject"
            ),
            "evidence_refs": (
                [] if candidate.skill_id in unknown else [evidence]
            ),
        } for candidate in request.candidates],
    }


def test_disabled_or_already_resolved_semantics_make_zero_calls():
    value = scenarios()
    catalog = evaluation_catalog(value)
    unresolved_case = value["s_scenarios"][0]
    resolved_case = value["d_scenarios"][4]
    called = 0

    def invoke(_request):
        nonlocal called
        called += 1
        raise AssertionError("transport must not run")

    off = complete_semantic_selection(
        projection(unresolved_case), catalog, plan_for(unresolved_case, catalog),
        semantic_enabled=False, invoke=invoke,
    )
    resolved = complete_semantic_selection(
        projection(resolved_case), catalog, plan_for(resolved_case, catalog),
        semantic_enabled=True, invoke=invoke,
    )
    assert off.status == resolved.status == "not_requested"
    assert off.auxiliary_calls == resolved.auxiliary_calls == called == 0


def test_one_call_completes_both_dimensions_and_keeps_evidence_refs():
    value = scenarios()
    catalog = evaluation_catalog(value)
    case = next(item for item in value["s_scenarios"] if item["id"] == "S19")
    original = plan_for(case, catalog)
    requests = []

    def invoke(request):
        requests.append(request)
        return transport(response_for(request, set(case["expected"])))

    outcome = complete_semantic_selection(
        projection(case), catalog, original, semantic_enabled=True, invoke=invoke,
    )
    assert len(requests) == outcome.auxiliary_calls == 1
    assert requests[0].purpose == "writing_skill_routing"
    assert requests[0].tools == ()
    assert {item.skill_id for item in requests[0].candidates} >= {
        "suspense-writing", "golden-finger-writing",
    }
    assert [item.skill_id for item in outcome.plan.selected] == case["expected"]
    assert all(item.basis == "semantic" for item in outcome.plan.selected)
    assert all(item.evidence_refs == ("source.0",) for item in outcome.plan.selected)
    assert outcome.plan.genre_state == outcome.plan.mechanism_state == "resolved"
    assert outcome.plan.unresolved_ids == ()


def test_supported_empty_rejection_is_not_confused_with_failure():
    value = scenarios()
    catalog = evaluation_catalog(value)
    case = next(item for item in value["s_scenarios"] if item["id"] == "S17")
    original = plan_for(case, catalog)
    outcome = complete_semantic_selection(
        projection(case), catalog, original, semantic_enabled=True,
        invoke=lambda request: transport(response_for(request, set())),
    )
    assert outcome.status == "rejected"
    assert outcome.plan.selected == ()
    assert outcome.plan.unresolved_ids == ()
    assert outcome.decision_hash is not None


def test_payload_unknown_keeps_candidate_unresolved_and_cannot_pass():
    value = scenarios()
    catalog = evaluation_catalog(value)
    case = value["s_scenarios"][0]
    original = plan_for(case, catalog)
    unknown_id = original.unresolved_ids[0]
    outcome = complete_semantic_selection(
        projection(case), catalog, original, semantic_enabled=True,
        invoke=lambda request: transport(response_for(
            request, set(), unknown=(unknown_id,),
        )),
    )
    assert outcome.status == "unknown"
    assert unknown_id in outcome.plan.unresolved_ids
    assert outcome.auxiliary_calls == 1


@pytest.mark.parametrize("status", ["timeout", "cancelled", "unknown", "failed"])
def test_non_success_transport_never_becomes_an_empty_success(status):
    value = scenarios()
    catalog = evaluation_catalog(value)
    case = value["s_scenarios"][0]
    original = plan_for(case, catalog)
    outcome = complete_semantic_selection(
        projection(case), catalog, original, semantic_enabled=True,
        invoke=lambda _request: transport(None, status=status, rounds=0, attempts=1),
    )
    assert outcome.status == status
    assert outcome.plan == original
    assert outcome.auxiliary_calls == 0
    assert outcome.decision_hash is None


@pytest.mark.parametrize("status", ["timeout", "cancelled", "unknown", "failed"])
def test_observed_non_success_transport_records_one_auxiliary_call(status):
    value = scenarios()
    catalog = evaluation_catalog(value)
    case = value["s_scenarios"][0]
    original = plan_for(case, catalog)
    outcome = complete_semantic_selection(
        projection(case), catalog, original, semantic_enabled=True,
        invoke=lambda _request: transport(None, status=status, rounds=1, attempts=1),
    )
    assert outcome.status == status
    assert outcome.plan == original
    assert outcome.auxiliary_calls == 1
    assert outcome.decision_hash is None


@pytest.mark.parametrize("changes", [
    {"rounds": 2}, {"tools": 1}, {"attempts": 2}, {"recursion": True},
])
def test_unobservable_or_multi_call_transport_fails_closed(changes):
    value = scenarios()
    catalog = evaluation_catalog(value)
    case = value["s_scenarios"][0]
    original = plan_for(case, catalog)
    with pytest.raises(SemanticGateError, match="transport_contract_violation"):
        complete_semantic_selection(
            projection(case), catalog, original, semantic_enabled=True,
            invoke=lambda request: transport(
                response_for(request, set(case["expected"])), **changes,
            ),
        )


def test_recursion_and_pre_cancel_stop_before_transport():
    value = scenarios()
    catalog = evaluation_catalog(value)
    case = value["s_scenarios"][0]
    original = plan_for(case, catalog)
    with pytest.raises(SemanticGateError, match="recursion_blocked"):
        complete_semantic_selection(
            projection(case), catalog, original, semantic_enabled=True,
            invoke=lambda _request: pytest.fail("must not call"), routing_depth=1,
        )
    cancelled = complete_semantic_selection(
        projection(case), catalog, original, semantic_enabled=True,
        invoke=lambda _request: pytest.fail("must not call"), cancelled=lambda: True,
    )
    assert cancelled.status == "cancelled"
    assert cancelled.auxiliary_calls == 0


@pytest.mark.parametrize("mutation,match", [
    ("missing", "candidate_set_mismatch"),
    ("extra", "candidate_set_mismatch"),
    ("duplicate", "candidate_set_mismatch"),
    ("bad_evidence", "evidence_out_of_scope"),
])
def test_payload_candidate_and_evidence_scope_are_exact(mutation, match):
    value = scenarios()
    catalog = evaluation_catalog(value)
    case = value["s_scenarios"][0]
    original = plan_for(case, catalog)

    def invoke(request):
        payload = response_for(request, set(case["expected"]))
        if mutation == "missing":
            payload["decisions"].pop()
        elif mutation == "extra":
            payload["decisions"].append({
                "skill_id": "outside-fixture", "decision": "select",
                "evidence_refs": ["source.0"],
            })
        elif mutation == "duplicate":
            payload["decisions"].append(deepcopy(payload["decisions"][0]))
        else:
            payload["decisions"][0]["evidence_refs"] = ["future.chapter"]
        return transport(payload)

    with pytest.raises(SemanticGateError, match=match):
        complete_semantic_selection(
            projection(case), catalog, original, semantic_enabled=True, invoke=invoke,
        )


@pytest.mark.parametrize("field", [
    "description",
    "semantic_criteria",
    "negative_examples",
    "conflicts_with",
    "supersedes",
])
def test_frozen_request_rejects_each_candidate_metadata_or_relation_drift(field):
    value = scenarios()
    catalog = evaluation_catalog(value)
    case = next(item for item in value["s_scenarios"] if item["id"] == "S10")
    source = projection(case)
    original = plan_for(case, catalog)
    request = prepare_semantic_request(
        source, catalog, original, semantic_enabled=True
    )
    target = next(
        item for item in request.candidates if item.skill_id == "future-time-loop"
    )
    updates = {
        "description": "被传输层改写的候选说明",
        "semantic_criteria": (*target.semantic_criteria, "新增但未冻结的判定标准"),
        "negative_examples": (*target.negative_examples, "新增但未冻结的反例"),
        "conflicts_with": ("suspense-writing",),
        "supersedes": (),
    }
    changed_target = target.model_copy(update={field: updates[field]})
    changed = request.model_copy(
        update={
            "candidates": tuple(
                changed_target if item.skill_id == target.skill_id else item
                for item in request.candidates
            )
        }
    )
    with pytest.raises(SemanticGateError, match="request_candidate_mismatch"):
        apply_semantic_transport(
            source,
            catalog,
            original,
            changed,
            transport(response_for(request, set(case["expected"]))),
        )


def test_s_group_fake_oracle_is_technical_dry_run_only():
    value = scenarios()
    catalog = evaluation_catalog(value)
    observed = {}
    call_count = 0
    for case in value["s_scenarios"]:
        original = plan_for(case, catalog)

        def invoke(request, expected=set(case["expected"])):
            nonlocal call_count
            call_count += 1
            return transport(response_for(request, expected))

        outcome = complete_semantic_selection(
            projection(case), catalog, original, semantic_enabled=True, invoke=invoke,
        )
        observed[case["id"]] = [item.skill_id for item in outcome.plan.selected]
    assert call_count == 20
    assert observed == {
        case["id"]: case["expected"] for case in value["s_scenarios"]
    }
