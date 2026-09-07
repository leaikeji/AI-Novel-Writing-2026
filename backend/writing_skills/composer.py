"""Build immutable method packets with the existing labelled token estimator.

No files, network, model or database are read here. Catalogs and primary blocks
must be provided by trusted loaders; source evidence was checked by selection.
"""

from __future__ import annotations

from ..embedding.chunking import estimate_token_count
from .contracts import (
    CapabilityCatalog, MethodBlock, SemanticRouteEvidenceV1, SemanticRouteEvidenceV2,
    SkillInjectionPacketV1, SkillInvocationPlanV1,
)


class MethodCompositionError(ValueError):
    """Invalid assembly input; messages contain identifiers, never story text."""


class MethodBudgetError(MethodCompositionError):
    """The primary or explicitly required methods cannot fit intact."""


def _validate_block(block: MethodBlock) -> MethodBlock:
    # Revalidate dicts so model_copy/model_construct cannot bypass the digest.
    checked = MethodBlock.model_validate(block.model_dump())
    parts = checked.path.split("/")
    if (any(part in ("", ".", "..") for part in parts)
            or "\\" in checked.path
            or not (checked.path == "SKILL.md"
                    or (checked.path.startswith("references/") and checked.path.endswith(".md")))):
        raise MethodCompositionError("invalid_method_path")
    if not checked.text.strip():
        raise MethodCompositionError("empty_method_block")
    return checked


def compose_writing_request(
    plan: SkillInvocationPlanV1,
    catalog: CapabilityCatalog,
    *,
    primary_blocks: tuple[MethodBlock, ...],
    effective_input_budget: int,
    reserved_task_tokens: int,
    required_ids: tuple[str, ...] = (),
    semantic_evidence: SemanticRouteEvidenceV1 | SemanticRouteEvidenceV2 | None = None,
) -> SkillInjectionPacketV1:
    """Preserve full bytes and drop optional references before optional modules.

    ``reserved_task_tokens`` reserves the entry's non-method task input, facts,
    output allowance and envelope overhead. It EXCLUDES ``primary_blocks``;
    these are separately counted in full and never removed. The caller must
    reserve any transport framing not represented in MethodBlock.text.

    The 6000/15% limit applies to additional capabilities only. Estimates use
    ``unicode-char-estimate/1`` and are not Provider tokenizer measurements.
    The frozen selection plan is retained. Actual loading is represented by
    ``blocks`` and ``omitted_ids``, including removed optional references being
    absent from ``blocks``; callers must not load directly from plan.selected.
    """
    if (type(effective_input_budget) is not int or effective_input_budget < 0
            or type(reserved_task_tokens) is not int or reserved_task_tokens < 0):
        raise MethodCompositionError("invalid_budget")
    plan = SkillInvocationPlanV1.model_validate(plan.model_dump())
    if plan.catalog_version != catalog.version:
        raise MethodCompositionError("catalog_version_mismatch")
    selected_ids = [item.skill_id for item in plan.selected]
    if len(set(selected_ids)) != len(selected_ids):
        raise MethodCompositionError("duplicate_selection")
    if len(selected_ids) > 2:
        raise MethodCompositionError("capability_limit")
    if set(selected_ids) & set(plan.excluded_ids):
        raise MethodCompositionError("selected_method_excluded")
    if len(set(required_ids)) != len(required_ids):
        raise MethodCompositionError("duplicate_required_id")
    required = set(required_ids) | {s.skill_id for s in plan.selected if s.basis == "explicit"}
    if not required <= set(selected_ids):
        raise MethodCompositionError("required_method_not_selected")
    capabilities = {c.declaration.skill_id: c for c in catalog.capabilities}
    if len(capabilities) != len(catalog.capabilities):
        raise MethodCompositionError("duplicate_catalog_id")
    if not set(selected_ids) <= capabilities.keys():
        raise MethodCompositionError("selected_method_not_in_catalog")

    primary = tuple(_validate_block(block) for block in primary_blocks)
    if not any(b.skill_id == plan.primary_skill and b.path == "SKILL.md" for b in primary):
        raise MethodCompositionError("primary_body_missing")
    if any(b.skill_id in capabilities or b.skill_id in plan.excluded_ids for b in primary):
        raise MethodCompositionError("capability_in_primary_dependencies")
    seen = {(b.skill_id, b.path) for b in primary}
    if len(seen) != len(primary):
        raise MethodCompositionError("duplicate_primary_block")
    primary_tokens = sum(estimate_token_count(b.text) for b in primary)
    if primary_tokens + reserved_task_tokens > effective_input_budget:
        raise MethodBudgetError("primary_and_task_exceed_budget")

    # Each group remains in frozen priority order: body, then selected refs.
    groups: dict[str, list[MethodBlock]] = {}
    optional_refs: list[tuple[str, str]] = []
    for selection in plan.selected:
        sid = selection.skill_id
        capability = capabilities[sid]
        declaration = capability.declaration
        if (plan.task not in declaration.applicable_tasks
                or plan.task in declaration.excluded_tasks):
            raise MethodCompositionError("method_task_not_applicable")
        peers = set(selected_ids) - {sid}
        if peers & set((*declaration.conflicts_with, *declaration.supersedes)):
            raise MethodCompositionError("unresolved_method_conflict")
        body = _validate_block(capability.body)
        if body.skill_id != sid or body.path != "SKILL.md":
            raise MethodCompositionError("capability_body_identity_mismatch")
        references = {_validate_block(b).path: b for b in capability.references}
        if len(references) != len(capability.references):
            raise MethodCompositionError("duplicate_reference_asset")
        if any(b.skill_id != sid or not b.path.startswith("references/")
               for b in capability.references):
            raise MethodCompositionError("reference_asset_identity_mismatch")
        rules = {rule.key: rule for rule in declaration.reference_rules}
        if len(rules) != len(declaration.reference_rules):
            raise MethodCompositionError("duplicate_reference_rule")
        keys = selection.reference_keys
        if len(set(keys)) != len(keys):
            raise MethodCompositionError("duplicate_reference_key")
        mandatory = {r.key for r in rules.values() if r.required and plan.task in r.tasks}
        if not mandatory <= set(keys):
            raise MethodCompositionError("required_reference_not_selected")
        blocks = [body]
        for key in keys:
            rule = rules.get(key)
            if rule is None:
                raise MethodCompositionError("reference_key_not_declared")
            if plan.task not in rule.tasks:
                raise MethodCompositionError("reference_task_not_applicable")
            reference = references.get(rule.path)
            if reference is None:
                raise MethodCompositionError("reference_asset_missing")
            blocks.append(reference)
            if not rule.required:
                optional_refs.append((sid, rule.path))
        for block in blocks:
            identity = (block.skill_id, block.path)
            if identity in seen:
                raise MethodCompositionError("duplicate_method_block")
            seen.add(identity)
        groups[sid] = blocks

    additional_limit = min(6000, effective_input_budget * 15 // 100,
                           effective_input_budget - reserved_task_tokens - primary_tokens)

    def tokens() -> int:
        return sum(estimate_token_count(b.text) for blocks in groups.values() for b in blocks)

    # Remove least-priority optional references before omitting any core body.
    for sid, path in reversed(optional_refs):
        if tokens() <= additional_limit:
            break
        groups[sid] = [block for block in groups[sid] if block.path != path]
    omitted: set[str] = set()
    # A core which cannot fit even alone must not evict smaller useful modules.
    for sid in selected_ids:
        if sum(estimate_token_count(b.text) for b in groups[sid]) > additional_limit:
            if sid in required:
                raise MethodBudgetError("required_methods_exceed_budget")
            del groups[sid]
            omitted.add(sid)
    for sid in reversed(selected_ids):
        if tokens() <= additional_limit:
            break
        if sid not in required and sid in groups:
            del groups[sid]
            omitted.add(sid)
    if tokens() > additional_limit:
        raise MethodBudgetError("required_methods_exceed_budget")
    blocks = primary + tuple(block for sid in selected_ids
                             for block in groups.get(sid, ()))
    return SkillInjectionPacketV1(
        plan=plan, blocks=blocks,
        omitted_ids=tuple(sid for sid in selected_ids if sid in omitted),
        estimated_tokens=primary_tokens + tokens(),
        semantic_evidence=semantic_evidence,
    )
