"""Frozen value contracts shared by selectors, loaders and dispatch adapters.

These values are not authorization tokens. Entry adapters must validate scope
and construct projections from the existing task-specific model allowlists.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

FIXED_LOCAL_OWNER_ID = UUID("29cf94d9-a5c9-54ec-912c-5dfff8738c4c")
FIXED_LOCAL_WORKSPACE_ID = UUID("f0e2e632-bc99-52d2-9916-bb906aa4da6e")

SkillId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Task = Literal[
    "direction", "chapter_body", "chapter_outline", "chapter_storyline_recommendation",
    "outline_background", "outline_characters", "outline_plot", "outline_highlight",
    "character_profile_completion", "review", "continuity_check", "selection_edit",
    "novel_template", "novel_naming", "mechanical", "excluded",
]
DimensionState = Literal["resolved", "unresolved", "not_applicable", "excluded"]


def canonical_hash(value: object) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Scope(FrozenModel):
    owner_id: UUID
    workspace_id: UUID
    kind: Literal["novel", "creation_draft"]
    scope_id: UUID
    document_id: UUID | None = None
    tab_id: str = Field(min_length=1, max_length=160)


class SourceItem(FrozenModel):
    key: str = Field(min_length=1, max_length=240)
    text: str = Field(max_length=40000)
    kind: Literal["genre", "subgenre", "mechanism", "content", "author_request"]


class TaskModelInputProjectionV1(FrozenModel):
    schema_version: Literal["task-model-input/1"] = "task-model-input/1"
    scope: Scope
    task: Task
    intent: Literal["fresh", "refine", "write", "review"]
    operation: Literal["", "polish", "rewrite", "expand", "shorten", "dialogue", "review", "custom"] = ""
    source_version: str = Field(min_length=1, max_length=240)
    visibility_key: str = Field(min_length=1, max_length=240)
    sources: tuple[SourceItem, ...] = Field(max_length=128)
    truncated: bool = False

    @model_validator(mode="after")
    def unique_sources(self) -> "TaskModelInputProjectionV1":
        if len({s.key for s in self.sources}) != len(self.sources):
            raise ValueError("duplicate source key")
        if sum(len(s.text) for s in self.sources) > 80000:
            raise ValueError("routing projection exceeds character budget")
        return self

    @property
    def source_hash(self) -> str:
        return canonical_hash(self)


class MethodPreferences(FrozenModel):
    mode: Literal["auto", "generic_only"] = "auto"
    semantic_mode: Literal["off", "auto"] = "off"
    excluded_ids: tuple[SkillId, ...] = ()
    required_ids: tuple[SkillId, ...] = ()
    version: str = "request/1"

    @model_validator(mode="after")
    def consistent(self) -> "MethodPreferences":
        if set(self.required_ids) & set(self.excluded_ids):
            raise ValueError("a method cannot be required and excluded")
        if self.mode == "generic_only" and self.required_ids:
            raise ValueError("generic-only cannot require a capability")
        return self


class ReferenceRule(FrozenModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    path: str = Field(pattern=r"^references/[a-zA-Z0-9_./-]+\.md$")
    tasks: tuple[Task, ...] = Field(min_length=1)
    required: bool = False

    @model_validator(mode="after")
    def safe_path(self) -> "ReferenceRule":
        if any(part in (".", "..", "") for part in self.path.split("/")):
            raise ValueError("reference must be a normal relative path")
        return self


class CapabilityDeclaration(FrozenModel):
    routing_schema_version: Literal["writing-capability/1"] = "writing-capability/1"
    skill_id: SkillId
    capability_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    kind: Literal["genre", "mechanism"]
    display_name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=600)
    approval_ref: str = Field(min_length=1, max_length=240)
    release_status: Literal["author_approved"]
    genre_aliases: tuple[str, ...] = ()
    mechanism_tags: tuple[str, ...] = ()
    applicable_tasks: tuple[Task, ...] = Field(min_length=1)
    excluded_tasks: tuple[Task, ...] = ()
    semantic_criteria: tuple[str, ...] = Field(min_length=1, max_length=16)
    negative_examples: tuple[str, ...] = Field(min_length=1, max_length=16)
    reference_rules: tuple[ReferenceRule, ...] = ()
    conflicts_with: tuple[SkillId, ...] = ()
    supersedes: tuple[SkillId, ...] = ()
    auto_eligible: bool = True
    budget_hint: int = Field(default=2000, ge=1, le=6000)

    @model_validator(mode="after")
    def consistent(self) -> "CapabilityDeclaration":
        if self.skill_id in (*self.conflicts_with, *self.supersedes):
            raise ValueError("self conflict or supersession")
        keys = [rule.key for rule in self.reference_rules]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate reference key")
        if set(self.applicable_tasks) & set(self.excluded_tasks):
            raise ValueError("task both allowed and excluded")
        return self


class MethodBlock(FrozenModel):
    skill_id: SkillId
    path: str
    text: str
    sha256: Digest

    @model_validator(mode="after")
    def matches_hash(self) -> "MethodBlock":
        if hashlib.sha256(self.text.encode("utf-8")).hexdigest() != self.sha256:
            raise ValueError("method content hash mismatch")
        return self


class LoadedCapability(FrozenModel):
    declaration: CapabilityDeclaration
    routing_hash: Digest
    body: MethodBlock
    references: tuple[MethodBlock, ...] = ()


class ApprovedAsset(FrozenModel):
    path: str
    sha256: Digest


class ApprovalRecord(FrozenModel):
    skill_id: SkillId
    capability_version: str
    approval_ref: str
    routing_hash: Digest
    assets: tuple[ApprovedAsset, ...]


class CapabilityCatalog(FrozenModel):
    schema_version: Literal["writing-catalog/1"] = "writing-catalog/1"
    capabilities: tuple[LoadedCapability, ...]
    rejected: tuple[str, ...] = ()

    @model_validator(mode="after")
    def unique_ids(self) -> "CapabilityCatalog":
        ids = [x.declaration.skill_id for x in self.capabilities]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate capability")
        return self

    @property
    def version(self) -> str:
        return canonical_hash(sorted([
            (x.declaration.skill_id, x.routing_hash, x.body.sha256,
             sorted((r.path, r.sha256) for r in x.references))
            for x in self.capabilities
        ]))


class MethodSelection(FrozenModel):
    skill_id: SkillId
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    reference_keys: tuple[str, ...] = ()
    basis: Literal["explicit", "deterministic", "semantic"] = "deterministic"


class SkillInvocationPlanV1(FrozenModel):
    schema_version: Literal["skill-invocation/1"] = "skill-invocation/1"
    task: Task
    primary_skill: SkillId
    source_hash: Digest
    catalog_version: Digest
    selected: tuple[MethodSelection, ...] = ()
    genre_state: DimensionState
    mechanism_state: DimensionState
    excluded_ids: tuple[SkillId, ...] = ()
    unresolved_ids: tuple[SkillId, ...] = ()
    reasons: tuple[str, ...] = ()


class SemanticRouteEvidenceV1(FrozenModel):
    """Content-free proof attached only after one successful routing call."""

    schema_version: Literal["semantic-route-evidence/1"] = "semantic-route-evidence/1"
    status: Literal["applied", "rejected"]
    auxiliary_calls: Literal[1] = 1
    decision_hash: Digest


class SemanticRouteEvidenceV2(FrozenModel):
    """Content-free proof binding a decision to its exact request and prompt."""

    schema_version: Literal["semantic-route-evidence/2"] = "semantic-route-evidence/2"
    request_schema: Literal["semantic-route-request/2"] = "semantic-route-request/2"
    prompt_contract: Literal["semantic-routing-prompt/2"] = "semantic-routing-prompt/2"
    status: Literal["applied", "rejected"]
    auxiliary_calls: Literal[1] = 1
    request_hash: Digest
    prompt_hash: Digest
    decision_hash: Digest


class SkillInjectionPacketV1(FrozenModel):
    schema_version: Literal["skill-packet/1"] = "skill-packet/1"
    plan: SkillInvocationPlanV1
    blocks: tuple[MethodBlock, ...]
    omitted_ids: tuple[SkillId, ...] = ()
    estimated_tokens: int = Field(ge=0)
    semantic_evidence: SemanticRouteEvidenceV1 | SemanticRouteEvidenceV2 | None = None

    @property
    def method_input_hash(self) -> str:
        value = {
            "schema": self.schema_version, "selection_schema": self.plan.schema_version,
            "policy": "writing-routing/1",
            "task": self.plan.task, "primary": self.plan.primary_skill,
            "source": self.plan.source_hash, "catalog": self.plan.catalog_version,
            "excluded": self.plan.excluded_ids, "omitted": self.omitted_ids,
            "blocks": [(b.skill_id, b.path, b.sha256) for b in self.blocks],
        }
        # Preserve every pre-semantic packet hash bit-for-bit. Only packets
        # produced by the gated semantic branch add this identity component.
        if self.semantic_evidence is not None:
            value["semantic"] = self.semantic_evidence.model_dump(mode="json")
        return canonical_hash(value)


class ActionIdentity(FrozenModel):
    owner_id: UUID
    workspace_id: UUID
    agent_id: Literal["ai-novel-writer"] = "ai-novel-writer"
    entry: Literal["button", "native"]
    action_id: UUID

    @property
    def key(self) -> str:
        return canonical_hash(self)


class FrozenRouteRequest(FrozenModel):
    identity: ActionIdentity
    projection: TaskModelInputProjectionV1
    preferences: MethodPreferences
    catalog_version: Digest
    provider_id: str = Field(min_length=1, max_length=240)
    model_id: str = Field(min_length=1, max_length=240)
    retry_of_action_id: UUID | None = None
    policy_version: Literal["writing-routing/1"] = "writing-routing/1"

    @model_validator(mode="after")
    def distinct_retry_parent(self) -> "FrozenRouteRequest":
        if self.retry_of_action_id == self.identity.action_id:
            raise ValueError("a writing action cannot retry itself")
        return self

    @model_validator(mode="after")
    def matching_owner(self) -> "FrozenRouteRequest":
        if (self.identity.owner_id, self.identity.workspace_id) != (
            self.projection.scope.owner_id, self.projection.scope.workspace_id
        ):
            raise ValueError("action and projection scope mismatch")
        return self

    @property
    def route_request_key(self) -> str:
        # Action and retry lineage identify execution records, not route
        # content. They must not defeat same-input comparison or packet reuse.
        return canonical_hash(self.model_dump(mode="json", exclude={"identity", "retry_of_action_id"}))
