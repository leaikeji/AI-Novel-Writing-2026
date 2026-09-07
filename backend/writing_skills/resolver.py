"""Deterministic method selection without IO or model calls.

The catalog supplied here must already be the approved/enabled intersection.
Only typed explicit labels match deterministically; story text is unresolved
evidence for the later, separately gated semantic selector.
"""

from __future__ import annotations

import unicodedata

from .contracts import (
    CapabilityCatalog, DimensionState, LoadedCapability, MethodPreferences,
    MethodSelection, SkillInvocationPlanV1, TaskModelInputProjectionV1,
)


class RequiredMethodUnavailable(ValueError):
    """An explicit required method cannot be faithfully included."""


def _label(text: str) -> str:
    return unicodedata.normalize("NFKC", text).strip().casefold()


def resolve_methods(
    projection: TaskModelInputProjectionV1,
    catalog: CapabilityCatalog,
    preferences: MethodPreferences,
    primary_skill: str,
) -> SkillInvocationPlanV1:
    """Resolve only typed facts and validated structured author preferences.

    An entry translating a UI ``required_ids`` selection must also provide an
    ``author_request`` SourceItem recording that validated selection. This is
    author evidence, not a story fact. Required IDs without that evidence fail.
    Free text (including dialogue and natural-language negation) is never parsed
    into a structured preference here. Actual byte/token budgets belong to the
    composer; declaration budget hints cannot prove that a module will not fit.
    """
    required = set(preferences.required_ids)
    excluded = set(preferences.excluded_ids)
    reasons: list[str] = []
    selections: dict[str, MethodSelection] = {}
    dimensions: dict[str, DimensionState] = {}
    unresolved: set[str] = set()
    available: dict[str, LoadedCapability] = {}
    mechanical = projection.task in ("mechanical", "excluded")
    generic = preferences.mode == "generic_only"
    author_refs = tuple(s.key for s in projection.sources
                        if s.kind == "author_request" and s.text.strip())

    for capability in catalog.capabilities:
        declaration = capability.declaration
        sid = declaration.skill_id
        task_ok = (projection.task in declaration.applicable_tasks
                   and projection.task not in declaration.excluded_tasks)
        if task_ok and sid not in excluded and not mechanical and not generic:
            if declaration.auto_eligible or sid in required:
                available[sid] = capability

    unavailable = required - set(available)
    if unavailable:
        raise RequiredMethodUnavailable(
            "required method unavailable for this request: " + ", ".join(sorted(unavailable))
        )
    if required and not author_refs:
        raise RequiredMethodUnavailable("required method has no author_request evidence")

    for dimension in ("genre", "mechanism"):
        declared = [c for c in catalog.capabilities
                    if c.declaration.kind == dimension
                    and projection.task in c.declaration.applicable_tasks
                    and projection.task not in c.declaration.excluded_tasks]
        candidates = sorted((c for c in available.values()
                             if c.declaration.kind == dimension),
                            key=lambda c: c.declaration.skill_id)
        if mechanical:
            dimensions[dimension] = "not_applicable"
            continue
        if generic:
            dimensions[dimension] = "excluded"
            continue
        if not candidates:
            dimensions[dimension] = (
                "excluded" if declared and all(c.declaration.skill_id in excluded
                                               for c in declared)
                else "not_applicable"
            )
            continue
        matched = False
        for capability in candidates:
            declaration = capability.declaration
            sid = declaration.skill_id
            labels = (declaration.genre_aliases if dimension == "genre"
                      else declaration.mechanism_tags)
            normalized = {_label(label) for label in labels if _label(label)}
            kinds = ("genre", "subgenre") if dimension == "genre" else ("mechanism",)
            refs = tuple(s.key for s in projection.sources
                         if s.kind in kinds and _label(s.text) in normalized)
            explicit = sid in required
            if explicit or refs:
                matched = True
                selections[sid] = MethodSelection(
                    skill_id=sid, evidence_refs=author_refs if explicit else refs,
                    basis="explicit" if explicit else "deterministic",
                    reference_keys=tuple(sorted(r.key for r in declaration.reference_rules
                                                if projection.task in r.tasks)),
                )
        dimensions[dimension] = "resolved" if matched else "unresolved"
        if not matched:
            unresolved.update(c.declaration.skill_id for c in candidates)

    # Author-required methods outrank automatic ones. Superseders precede older
    # candidates, then genre and stable IDs decide remaining equal-priority ties.
    def priority(sid: str) -> tuple[int, int, int, str]:
        d = available[sid].declaration
        return (0 if sid in required else 1,
                -len(set(d.supersedes) & selections.keys()),
                0 if d.kind == "genre" else 1, sid)

    selected: list[MethodSelection] = []
    for sid in sorted(selections, key=priority):
        d = available[sid].declaration
        conflicts = []
        for previous in selected:
            p = available[previous.skill_id].declaration
            if (previous.skill_id in (*d.conflicts_with, *d.supersedes)
                    or sid in (*p.conflicts_with, *p.supersedes)):
                conflicts.append(previous.skill_id)
        reason = ("conflict:" + ",".join(conflicts) if conflicts else
                  "capability_limit" if len(selected) >= 2 else "")
        if reason:
            if sid in required:
                raise RequiredMethodUnavailable(f"required method {sid} cannot fit: {reason}")
            reasons.append(f"omitted:{sid}:{reason}")
            continue
        selected.append(selections[sid])
    if mechanical:
        reasons.append("task_not_applicable")
    elif generic:
        reasons.append("author_generic_only")
    if projection.truncated:
        reasons.append("source_projection_truncated")
    if unresolved:
        reasons.append("unresolved_requires_semantic_evidence")
    return SkillInvocationPlanV1(
        task=projection.task, primary_skill=primary_skill,
        source_hash=projection.source_hash, catalog_version=catalog.version,
        selected=tuple(selected), genre_state=dimensions["genre"],
        mechanism_state=dimensions["mechanism"], excluded_ids=tuple(sorted(excluded)),
        unresolved_ids=tuple(sorted(unresolved)), reasons=tuple(reasons),
    )
