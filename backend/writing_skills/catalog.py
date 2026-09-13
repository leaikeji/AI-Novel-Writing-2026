"""Discover approved, enabled writing modules from one trusted package only."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

from .contracts import (
    ApprovalRecord, ApprovedAsset, CapabilityCatalog, LoadedCapability,
)
from .loader import (
    CatalogError, load_capability, read_declaration, trusted_skills_root,
)

BASE_TASK_IDS = frozenset({
    "novel-direction", "story-foundation", "character-craft", "chapter-outline",
    "scene-craft", "dialogue-craft", "prose-writing", "continuity-check", "style-review",
})
GENERIC_PROJECT_SKILL_IDS = frozenset({"private-library-maintenance"})


def packaged_approvals() -> tuple[ApprovalRecord, ...]:
    """Read the publisher-owned index, never a module's self-approval."""
    path = Path(__file__).with_name("approved-capabilities.json")
    return tuple(ApprovalRecord.model_validate(record) for record in json.loads(path.read_text(encoding="utf-8")))


def published_skill_ids(root: Path) -> frozenset[str]:
    """Validated installed source inventory; does not assert host enablement."""
    approvals = packaged_approvals()
    catalog = load_catalog(root, approvals, frozenset(a.skill_id for a in approvals))
    if catalog.rejected:
        raise CatalogError("published_catalog_invalid:" + ",".join(catalog.rejected))
    for skill_id in BASE_TASK_IDS | GENERIC_PROJECT_SKILL_IDS:
        if not (root / skill_id / "SKILL.md").is_file():
            raise CatalogError("missing_base_task_skill")
    return (
        BASE_TASK_IDS
        | GENERIC_PROJECT_SKILL_IDS
        | frozenset(c.declaration.skill_id for c in catalog.capabilities)
    )


def asset_inventory(capability: LoadedCapability) -> tuple[ApprovedAsset, ...]:
    """Pure deterministic file digest inventory for trusted release tooling."""
    return tuple(ApprovedAsset(path=block.path, sha256=block.sha256)
                 for block in sorted((capability.body, *capability.references),
                                     key=lambda item: item.path))


def create_approval_record(
    capability: LoadedCapability, *, approval_ref: str, capability_version: str,
) -> ApprovalRecord:
    """Serialize a release decision supplied by the trusted publisher.

    Call only AFTER independently verifying the author's release decision.
    Reading a candidate or generating this structure does not grant approval;
    runtime never invokes this helper or trusts a module-local approval file.
    """
    declaration = capability.declaration
    if (approval_ref, capability_version) != (
        declaration.approval_ref, declaration.capability_version,
    ):
        raise CatalogError("release_decision_mismatch")
    return ApprovalRecord(skill_id=declaration.skill_id,
                          capability_version=capability_version,
                          approval_ref=approval_ref, routing_hash=capability.routing_hash,
                          assets=asset_inventory(capability))


def load_catalog(
    root: Path, approvals: tuple[ApprovalRecord, ...], enabled_ids: frozenset[str],
) -> CapabilityCatalog:
    """Return valid modules plus bounded diagnostics for each rejected module.

    Generic Skills with no routing declaration are outside this catalog. Both
    approval and enablement must come from trusted host state. A disabled module
    is never returned as a selectable capability, even when its files are valid.
    """
    root = trusted_skills_root(root)
    approval_counts = Counter(record.skill_id for record in approvals)
    approval_by_id = {record.skill_id: record for record in approvals}
    rejected: list[str] = []
    candidates: dict[str, str] = {}
    try:
        children = sorted(root.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        raise CatalogError("unreadable_skills_root") from exc
    for child in children:
        if child.is_symlink():
            rejected.append(f"{child.name}:unsafe_module_path")
            continue
        if not child.is_dir():
            continue
        # No recursive discovery. Generic Skills intentionally lack this file.
        declaration_path = child / "routing.json"
        if not declaration_path.exists() and not declaration_path.is_symlink():
            continue
        try:
            declaration, _ = read_declaration(root, child.name)
            candidates[child.name] = declaration.skill_id
        except CatalogError as exc:
            rejected.append(f"{child.name}:{exc}")

    declared_counts = Counter(candidates.values())
    validated: list[LoadedCapability] = []
    for directory_id, declared_id in sorted(candidates.items()):
        error = None
        if declared_counts[declared_id] != 1:
            error = "duplicate_skill_id"
        elif directory_id != declared_id:
            error = "directory_id_mismatch"
        elif approval_counts[declared_id] > 1:
            error = "duplicate_approval"
        elif declared_id not in approval_by_id:
            error = "not_approved"
        if error:
            rejected.append(f"{directory_id}:{error}")
            continue
        try:
            validated.append(load_capability(root, directory_id, approval_by_id[declared_id]))
        except CatalogError as exc:
            rejected.append(f"{directory_id}:{exc}")

    # Relations can point at disabled but registered/approved capabilities.
    # Rejections propagate so an unusable target cannot remain an override.
    while True:
        registered = {item.declaration.skill_id for item in validated}
        invalid = [item for item in validated if not set(
            (*item.declaration.conflicts_with, *item.declaration.supersedes)
        ) <= registered]
        if not invalid:
            break
        invalid_ids = {item.declaration.skill_id for item in invalid}
        rejected.extend(f"{item}:unknown_relation" for item in sorted(invalid_ids))
        validated = [item for item in validated if item.declaration.skill_id not in invalid_ids]

    enabled: list[LoadedCapability] = []
    for item in validated:
        if item.declaration.skill_id not in enabled_ids:
            rejected.append(f"{item.declaration.skill_id}:disabled")
        else:
            enabled.append(item)
    return CapabilityCatalog(capabilities=tuple(enabled), rejected=tuple(sorted(rejected)))
