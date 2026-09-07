import hashlib

import pytest

from backend.embedding.chunking import estimate_token_count
from backend.writing_skills.composer import (
    MethodBudgetError, MethodCompositionError, compose_writing_request,
)
from backend.writing_skills.contracts import (
    CapabilityCatalog, CapabilityDeclaration, LoadedCapability, MethodBlock,
    MethodSelection, ReferenceRule, SkillInvocationPlanV1, canonical_hash,
)


def method(sid, tokens, path="SKILL.md"):
    text = "字" * (tokens * 2)
    return MethodBlock(skill_id=sid, path=path, text=text,
                       sha256=hashlib.sha256(text.encode()).hexdigest())


def setup_packet(*specs, explicit=()):
    """spec=(id, body tokens, optional reference tokens, mandatory ref tokens)."""
    modules, selections = [], []
    for sid, body_tokens, optional, mandatory in specs:
        refs, rules = [], []
        for key, count, required in (("optional", optional, False), ("mandatory", mandatory, True)):
            if count:
                refs.append(method(sid, count, f"references/{key}.md"))
                rules.append(ReferenceRule(key=key, path=refs[-1].path, tasks=("chapter_body",),
                                           required=required))
        d = CapabilityDeclaration(
            skill_id=sid, capability_version="1.0.0", kind="genre", display_name=sid,
            description="预算测试", approval_ref="fixture", release_status="author_approved",
            applicable_tasks=("chapter_body",), semantic_criteria=("依据",),
            negative_examples=("反例",), reference_rules=tuple(rules),
        )
        modules.append(LoadedCapability(declaration=d, routing_hash=canonical_hash(d),
                                        body=method(sid, body_tokens), references=tuple(refs)))
        selections.append(MethodSelection(skill_id=sid, evidence_refs=("genre",),
                                           reference_keys=tuple(r.key for r in rules),
                                           basis="explicit" if sid in explicit else "deterministic"))
    c = CapabilityCatalog(capabilities=tuple(modules))
    p = SkillInvocationPlanV1(task="chapter_body", primary_skill="prose-writing", source_hash="a" * 64,
                              catalog_version=c.version, selected=tuple(selections),
                              genre_state="resolved", mechanism_state="not_applicable")
    return p, c


def compose(p, c, *, budget=10000, reserved=1000, primary=100, required=()):
    return compose_writing_request(p, c, primary_blocks=(method("prose-writing", primary),),
                                   effective_input_budget=budget, reserved_task_tokens=reserved,
                                   required_ids=required)


@pytest.mark.parametrize("budget,reserved", [(-1, 0), (1, -1), (True, 0), (1.5, 0), (10, False)])
def test_invalid_budgets_rejected(budget, reserved):
    p, c = setup_packet()
    with pytest.raises(MethodCompositionError, match="invalid_budget"):
        compose(p, c, budget=budget, reserved=reserved)


def test_primary_and_fact_reserve_are_not_reduced():
    p, c = setup_packet(("a", 100, 0, 0))
    with pytest.raises(MethodBudgetError, match="primary_and_task"):
        compose(p, c, budget=1000, reserved=901)
    packet = compose(p, c, budget=1000, reserved=900)
    assert packet.blocks == (method("prose-writing", 100),)
    assert packet.omitted_ids == ("a",)


def test_optional_references_removed_before_any_capability_body():
    p, c = setup_packet(("a", 400, 400, 100), ("b", 400, 400, 100))
    packet = compose(p, c)
    assert packet.omitted_ids == ()
    assert [(b.skill_id, b.path) for b in packet.blocks] == [
        ("prose-writing", "SKILL.md"), ("a", "SKILL.md"),
        ("a", "references/optional.md"), ("a", "references/mandatory.md"),
        ("b", "SKILL.md"), ("b", "references/mandatory.md"),
    ]
    assert packet.estimated_tokens == 1500
    assert packet.plan == p


def test_mandatory_reference_stays_with_body_or_entire_module_is_omitted():
    p, c = setup_packet(("a", 500, 0, 300), ("b", 500, 0, 300))
    packet = compose(p, c)
    assert packet.omitted_ids == ("b",)
    assert [(b.skill_id, b.path) for b in packet.blocks][-2:] == [
        ("a", "SKILL.md"), ("a", "references/mandatory.md")]
    assert packet.estimated_tokens == 900


def test_explicit_required_kept_even_if_last_and_optional_precedes_it():
    p, c = setup_packet(("a", 1000, 0, 0), ("b", 1000, 0, 0), explicit=("b",))
    packet = compose(p, c)
    assert packet.omitted_ids == ("a",)
    assert packet.blocks[-1].skill_id == "b"


def test_required_intact_module_fails_if_too_big():
    p, c = setup_packet(("a", 1400, 100, 200))
    with pytest.raises(MethodBudgetError, match="required_methods"):
        compose(p, c, required=("a",))


def test_optional_reference_of_required_module_can_be_removed():
    p, c = setup_packet(("a", 1000, 700, 200))
    packet = compose(p, c, required=("a",))
    assert packet.omitted_ids == ()
    assert packet.estimated_tokens == 1300
    assert all(b.path != "references/optional.md" for b in packet.blocks)


@pytest.mark.parametrize("budget,body,kept", [(10000, 1500, True), (10000, 1501, False),
                                           (100000, 6000, True), (100000, 6001, False)])
def test_fifteen_percent_and_absolute_ceiling(budget, body, kept):
    p, c = setup_packet(("a", body, 0, 0))
    packet = compose(p, c, budget=budget)
    assert (not packet.omitted_ids) is kept
    assert sum(estimate_token_count(b.text) for b in packet.blocks) == packet.estimated_tokens


def test_remaining_task_budget_can_be_stricter_than_percentage():
    p, c = setup_packet(("a", 401, 0, 0))
    packet = compose(p, c, budget=10000, reserved=9500)
    assert packet.omitted_ids == ("a",)
    assert packet.estimated_tokens == 100


def test_individually_oversized_optional_core_does_not_evict_smaller_module():
    p, c = setup_packet(("a", 1600, 0, 0), ("b", 300, 0, 0))
    packet = compose(p, c)
    assert packet.omitted_ids == ("a",)
    assert packet.blocks[-1].skill_id == "b"
    assert packet.estimated_tokens == 400


def test_primary_dependencies_are_counted_in_full():
    p, c = setup_packet(("a", 300, 0, 0))
    packet = compose_writing_request(p, c,
        primary_blocks=(method("prose-writing", 100), method("scene-craft", 600)),
        effective_input_budget=10000, reserved_task_tokens=9000)
    assert packet.estimated_tokens == 1000
    assert len(packet.blocks) == 3


def test_unknown_required_and_duplicate_required_are_rejected():
    p, c = setup_packet(("a", 100, 0, 0))
    with pytest.raises(MethodCompositionError, match="required_method_not_selected"):
        compose(p, c, required=("missing",))
    with pytest.raises(MethodCompositionError, match="duplicate_required"):
        compose(p, c, required=("a", "a"))
