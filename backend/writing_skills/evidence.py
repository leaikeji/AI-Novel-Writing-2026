"""Content-free display evidence, derived only from immutable method bytes."""
import re
from typing import Literal

from .contracts import FrozenModel, SkillInjectionPacketV1
from .loader import CatalogError, _frontmatter


class MethodItem(FrozenModel):
    skill_id: str
    display_name: str
    version: str | None
    body_sha256: str
    reference_count: int
    basis: Literal["primary", "explicit", "deterministic", "semantic"]
    evidence_refs: tuple[str, ...] = ()


class MethodDetails(FrozenModel):
    schema_version: Literal["writing-method-details/1"] = "writing-method-details/1"
    primary_skill: str
    methods: tuple[MethodItem, ...]
    reasons: tuple[str, ...]
    estimated_tokens: int


def method_details(packet: SkillInjectionPacketV1) -> MethodDetails:
    selected = {item.skill_id: item for item in packet.plan.selected}
    items = []
    for block in packet.blocks:
        if block.path != "SKILL.md":
            continue
        try:
            metadata = _frontmatter(block.text)
        except CatalogError:
            metadata = {}  # Old test/legacy bytes have no declared version.
        version = metadata.get(("metadata", "capability_version")) or metadata.get(("metadata", "plugin_skill_version"))
        if version is not None and not re.fullmatch(r"\d+\.\d+\.\d+", version):
            version = None
        selection = selected.get(block.skill_id)
        heading = re.search(r"^# ([^\r\n]{1,80})$", block.text, re.MULTILINE)
        items.append(MethodItem(skill_id=block.skill_id, display_name=heading[1] if heading else block.skill_id,
            version=version, body_sha256=block.sha256,
            reference_count=sum(b.skill_id == block.skill_id and b.path != "SKILL.md" for b in packet.blocks),
            basis=selection.basis if selection else "primary",
            evidence_refs=tuple(ref for ref in selection.evidence_refs
                if re.fullmatch(r"[a-zA-Z0-9_.:/-]{1,240}", ref)) if selection else ()))
    return MethodDetails(primary_skill=packet.plan.primary_skill, methods=tuple(items),
                         reasons=tuple(reason for reason in packet.plan.reasons
                             if re.fullmatch(r"[a-zA-Z0-9_.:/,-]{1,240}", reason)),
                         estimated_tokens=packet.estimated_tokens)
