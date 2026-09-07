import hashlib

import pytest

from backend.writing_skills.composer import MethodCompositionError, compose_writing_request
from backend.writing_skills.contracts import (
    CapabilityCatalog, CapabilityDeclaration, LoadedCapability, MethodBlock,
    MethodSelection, ReferenceRule, SkillInvocationPlanV1, canonical_hash,
)


def block(sid="prose-writing", path="SKILL.md", text="主方法\r\n保持原字节。"):
    return MethodBlock(skill_id=sid, path=path, text=text,
                       sha256=hashlib.sha256(text.encode()).hexdigest())


def capability(sid="third-fixture", *, references=(), rules=(), **kwargs):
    declaration = CapabilityDeclaration(
        skill_id=sid, capability_version="1.0.0", kind="genre", display_name=sid,
        description="测试第三模块", approval_ref="test-approved", release_status="author_approved",
        applicable_tasks=("chapter_body",), semantic_criteria=("有效依据",),
        negative_examples=("无依据",), reference_rules=rules, **kwargs,
    )
    return LoadedCapability(declaration=declaration, routing_hash=canonical_hash(declaration),
                            body=block(sid, text="第三模块完整方法"), references=references)


def make_plan(catalog, *, selected=None, **kwargs):
    if selected is None:
        selected = tuple(MethodSelection(skill_id=c.declaration.skill_id, evidence_refs=("genre",))
                         for c in catalog.capabilities)
    return SkillInvocationPlanV1(task="chapter_body", primary_skill="prose-writing",
                                 source_hash="a" * 64, catalog_version=catalog.version,
                                 genre_state="resolved", mechanism_state="not_applicable",
                                 selected=selected, **kwargs)


def compose(plan, catalog, **kwargs):
    return compose_writing_request(plan, catalog, **({
        "primary_blocks": (block(),), "effective_input_budget": 10000,
        "reserved_task_tokens": 1000,
    } | kwargs))


def test_third_module_exact_bytes_and_only_selected_reference():
    required = block("third-fixture", "references/needed.md", "必须参考\r\n不得改写。")
    extra = block("third-fixture", "references/unused.md", "未选择的方法不可进入模型。")
    module = capability(references=(required, extra), rules=(
        ReferenceRule(key="needed", path=required.path, tasks=("chapter_body",), required=True),
        ReferenceRule(key="unused", path=extra.path, tasks=("chapter_body",)),
    ))
    catalog = CapabilityCatalog(capabilities=(module,))
    plan = make_plan(catalog, selected=(MethodSelection(skill_id="third-fixture",
                     evidence_refs=("genre",), reference_keys=("needed",)),))
    packet = compose(plan, catalog)
    assert packet.plan == plan
    assert packet.blocks == (block(), module.body, required)
    assert all(hashlib.sha256(b.text.encode()).hexdigest() == b.sha256 for b in packet.blocks)
    assert "\r\n" in packet.blocks[-1].text
    assert packet.omitted_ids == ()


def test_catalog_identity_mismatch_and_unknown_selection_fail():
    c = CapabilityCatalog(capabilities=(capability(),))
    with pytest.raises(MethodCompositionError, match="catalog_version_mismatch"):
        compose(make_plan(c).model_copy(update={"catalog_version": "b" * 64}), c)
    plan = make_plan(c, selected=(MethodSelection(skill_id="missing", evidence_refs=("genre",)),))
    with pytest.raises(MethodCompositionError, match="not_in_catalog"):
        compose(plan, c)


@pytest.mark.parametrize("path", ["../SKILL.md", "/SKILL.md", "references/../a.md", "references//a.md"])
def test_primary_paths_cannot_escape_trusted_block_identity(path):
    c = CapabilityCatalog(capabilities=())
    with pytest.raises(MethodCompositionError, match="invalid_method_path"):
        compose(make_plan(c), c, primary_blocks=(block(path=path),))


def test_hash_rechecked_even_after_unvalidated_model_copy():
    c = CapabilityCatalog(capabilities=())
    corrupted = block().model_copy(update={"text": "篡改"})
    with pytest.raises(ValueError, match="hash mismatch"):
        compose(make_plan(c), c, primary_blocks=(corrupted,))


def test_missing_primary_and_duplicate_blocks_fail():
    c = CapabilityCatalog(capabilities=())
    with pytest.raises(MethodCompositionError, match="primary_body_missing"):
        compose(make_plan(c), c, primary_blocks=())
    with pytest.raises(MethodCompositionError, match="duplicate_primary_block"):
        compose(make_plan(c), c, primary_blocks=(block(), block()))


def test_generic_dependencies_cannot_smuggle_catalog_capabilities():
    module = capability()
    c = CapabilityCatalog(capabilities=(module,))
    with pytest.raises(MethodCompositionError, match="capability_in_primary"):
        compose(make_plan(c, selected=()), c, primary_blocks=(block(), module.body))


def test_selected_excluded_or_duplicate_method_rejected():
    c = CapabilityCatalog(capabilities=(capability(),))
    plan = make_plan(c)
    with pytest.raises(MethodCompositionError, match="selected_method_excluded"):
        compose(plan.model_copy(update={"excluded_ids": ("third-fixture",)}), c)
    with pytest.raises(MethodCompositionError, match="duplicate_selection"):
        compose(plan.model_copy(update={"selected": plan.selected * 2}), c)


def test_unresolved_conflict_rejected_independent_of_direction():
    c = CapabilityCatalog(capabilities=(capability("a", conflicts_with=("b",)), capability("b")))
    with pytest.raises(MethodCompositionError, match="unresolved_method_conflict"):
        compose(make_plan(c), c)


@pytest.mark.parametrize("key,expected", [("missing", "reference_key_not_declared"),
                                          ("wrong-task", "reference_task_not_applicable"),
                                          ("unloaded", "reference_asset_missing")])
def test_reference_identity_errors_are_not_hidden_by_budget_omission(key, expected):
    module = capability(rules=(
        ReferenceRule(key="wrong-task", path="references/a.md", tasks=("review",)),
        ReferenceRule(key="unloaded", path="references/b.md", tasks=("chapter_body",)),
    ))
    c = CapabilityCatalog(capabilities=(module,))
    plan = make_plan(c, selected=(MethodSelection(skill_id="third-fixture", evidence_refs=("genre",),
                     reference_keys=(key,)),))
    with pytest.raises(MethodCompositionError, match=expected):
        compose(plan, c, effective_input_budget=100, reserved_task_tokens=0)


def test_required_reference_must_exist_in_frozen_selection():
    module = capability(rules=(ReferenceRule(key="must", path="references/a.md",
                                            tasks=("chapter_body",), required=True),))
    c = CapabilityCatalog(capabilities=(module,))
    with pytest.raises(MethodCompositionError, match="required_reference_not_selected"):
        compose(make_plan(c), c)


def test_duplicate_reference_aliases_cannot_load_same_bytes_twice():
    ref = block("third-fixture", "references/a.md")
    module = capability(references=(ref,), rules=(
        ReferenceRule(key="one", path=ref.path, tasks=("chapter_body",)),
        ReferenceRule(key="two", path=ref.path, tasks=("chapter_body",)),
    ))
    c = CapabilityCatalog(capabilities=(module,))
    plan = make_plan(c, selected=(MethodSelection(skill_id="third-fixture", evidence_refs=("genre",),
                                                reference_keys=("one", "two")),))
    with pytest.raises(MethodCompositionError, match="duplicate_method_block"):
        compose(plan, c)


def test_packet_hash_tracks_content_not_explanation():
    c = CapabilityCatalog(capabilities=(capability(),))
    original = make_plan(c)
    changed = original.model_copy(update={"reasons": ("不同的展示用解释",)})
    assert compose(original, c).method_input_hash == compose(changed, c).method_input_hash
    assert compose(original, c).method_input_hash != compose(original, c, primary_blocks=(
        block(text="另一版主要方法"),)).method_input_hash
