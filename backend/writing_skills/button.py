"""Managed chapter HTTP orchestration. Release capabilities remain closed.

No client flag can open a release gate. The host model and enabled Skills are
read through public APIs; no alternate Agent, Provider or runtime is created.
"""
import asyncio
from pathlib import Path
import time
from uuid import UUID

import httpx
from fastapi import HTTPException
from sqlalchemy import select

from ..models import Document, Novel, ChapterGenerationJob
from ..schemas import GenerateChapterRequest
from ..services import (
    prepare_chapter_generation, start_chapter_generation, build_chapter_generation_prompt,
    get_chapter_brief, complete_chapter_generation, fail_chapter_generation,
    _generation_job_payload, ChapterLengthValidationError,
)
from ..embedding.contracts import RetrievalPurpose
from ..embedding.writing import resolve_writing_position, retrieve_for_writing, deterministic_query
from ..model_runtime import GENERATION_CONTRACT_VERSION, reply_final_text, ensure_prompt_within_effective_limit
from ..generation_runtime import await_chapter_generation
from .contracts import ActionIdentity, FrozenRouteRequest, Scope, canonical_hash
from .catalog import load_catalog, packaged_approvals
from .loader import load_primary_blocks
from .resolver import resolve_methods
from .composer import compose_writing_request
from .projection import chapter_routing_projection
from .persistence import (Claim, lookup_action, read_action, claim_pending_action,
                          freeze_prepared_action, advance, ActionConflict, StaleFence)
from .load_policy import PublicLoadCapabilities, ManagedMethodPolicy, MethodPolicyViolation, managed_method_request
from .api import method_status
from .primary import PRIMARY_REFERENCES_BY_SKILL
from .semantic_runtime import SemanticCallFactory
from .semantic_orchestration import complete_button_route, SemanticRouteIncomplete

SKILLS_ROOT = Path(__file__).resolve().parents[2] / "skills"
# Server-owned, button-only release decision for the pinned QwenPaw 2.1.x
# public middleware contract. Runtime observation still fails closed unless the
# factory and exactly one raw model call are seen. Native history/compression
# capabilities remain false and cannot pass this same value's native gate.
CHAPTER_CAPABILITIES = PublicLoadCapabilities(
    current_request_injection=True,
    pre_io_tool_control=True,
    no_unobserved_load_path=True,
)
def _scope(session, document_id: UUID, tab_id: str) -> Scope:
    row = session.execute(select(Document.id, Document.kind, Novel.id.label("novel_id"),
        Novel.owner_id, Novel.workspace_id).join(Novel, Novel.id == Document.novel_id)
        .where(Document.id == document_id)).first()
    if row is None or row.kind != "chapter":
        raise HTTPException(404, "chapter not found")
    return Scope(owner_id=row.owner_id, workspace_id=row.workspace_id, kind="novel",
                 scope_id=row.novel_id, document_id=document_id, tab_id=tab_id)


def _authorize(session, scope):
    if scope.kind != "novel" or scope.document_id is None or _scope(session, scope.document_id, scope.tab_id) != scope:
        raise HTTPException(403, "method scope changed")


def _validation_retry_parent(session, identity: ActionIdentity, scope: Scope, request: GenerateChapterRequest) -> Claim | None:
    """Resolve an explicitly linked, completed length failure in this exact tab.

    The new action remains independently deduplicated, but it may reuse only
    the immutable packet of a prior managed request whose own job proves a
    retryable length rejection. Client claims never confer this authority.
    """
    retry_id = request.writing_action.retry_of_action_id
    if retry_id is None:
        return None
    if retry_id == identity.action_id or not request.force_new:
        raise ActionConflict("invalid validation retry identity")
    parent_identity = identity.model_copy(update={"action_id": retry_id})
    parent = read_action(session, parent_identity, scope, authorize=_authorize)
    if not isinstance(parent, Claim) or parent.state != "dispatched" or parent.packet is None or not parent.job_ref:
        raise ActionConflict("validation retry parent is unavailable")
    if request.writing_action.preferences != parent.request.preferences:
        raise ActionConflict("validation retry cannot change writing methods")
    kind, _, value = parent.job_ref.partition(":")
    try:
        parent_job_id = UUID(value)
    except (TypeError, ValueError, AttributeError):
        raise ActionConflict("validation retry parent job is invalid") from None
    parent_job = session.get(ChapterGenerationJob, parent_job_id) if kind == "chapter" else None
    if (parent_job is None or parent_job.document_id != scope.document_id or parent_job.state != "failed"
            or parent_job.validation_state not in {"above_target", "below_target"}
            or parent_job.brief_version != request.expected_brief_version):
        raise ActionConflict("validation retry parent is not a matching length failure")
    snapshot = parent_job.generation_context_snapshot
    invocation = snapshot.get("skill_invocation") if isinstance(snapshot, dict) else None
    if (not isinstance(invocation, dict) or invocation.get("schema_version") != "job-skill-invocation/1"
            or invocation.get("dispatch_id") != str(parent.id)
            or invocation.get("method_input_hash") != parent.packet.method_input_hash):
        raise ActionConflict("validation retry parent evidence is inconsistent")
    return parent


async def current_catalog(asgi_app, *, primary_skill: str = "prose-writing"):
    """Load current modules plus the exact enabled task Skill bytes.

    ``primary_skill`` comes from a server-owned task mapping. Capability
    modules can add genre/mechanism methods, but can never replace this primary
    task contract or choose arbitrary files.
    """
    references = PRIMARY_REFERENCES_BY_SKILL.get(primary_skill)
    if references is None:
        raise ValueError("unsupported primary Skill")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=asgi_app),
                                  base_url="http://qwenpaw.internal", timeout=10) as client:
        response = await client.get("/api/skills", headers={"X-Agent-Id": "ai-novel-writer"})
        response.raise_for_status()
        rows = response.json()
    if not isinstance(rows, list):
        raise ValueError("invalid public Skill inventory")
    enabled = frozenset(row["name"] for row in rows if isinstance(row, dict)
        and isinstance(row.get("name"), str) and row.get("source") == "plugin:ai-novel-world-2026"
        and row.get("enabled") is True)
    if primary_skill not in enabled:
        raise ValueError("primary Skill is disabled or unavailable")
    catalog = load_catalog(SKILLS_ROOT, packaged_approvals(), enabled)
    primary = load_primary_blocks(SKILLS_ROOT, primary_skill, references)
    return catalog, primary


def _response(session, claim, *, job=None):
    _authorize(session, claim.scope)
    if job is None and claim.job_ref is not None:
        kind, _, value = claim.job_ref.partition(":")
        if kind != "chapter":
            raise ActionConflict("unexpected method job kind")
        row = session.get(ChapterGenerationJob, UUID(value))
        if row is None or row.document_id != claim.scope.document_id:
            raise ActionConflict("method job scope mismatch")
        job = _generation_job_payload(session, row)
    result = dict(job) if job is not None else {"state": "method_pending"}
    result.pop("generation_context_snapshot", None)
    result.pop("should_execute", None)
    result["writing_method"] = method_status(claim).model_dump(mode="json")
    return result


async def generate_managed_chapter(*, document_id, request: GenerateChapterRequest,
                                   ctx, model_probe, session, asgi_app,
                                   capabilities: PublicLoadCapabilities | None = None,
                                   semantic_call_factory: SemanticCallFactory | None = None):
    """One stable action; duplicates never re-enter config, retrieval or model.

    Existing optional retrieval remains task-input preparation. This service
    adds no auxiliary model calls; new routing and prose execution begin only
    after the durable action claim. Input freezes once preparation completes.
    Unknown transport outcomes cannot replay.
    """
    from ..generation_dependencies import (
        verify_novel_model_reply, failed_novel_model_evidence, NovelModelEvidenceRejected,
    )
    # Trusted adapter capability input (e.g. isolated integration fixture).
    # The public product HTTP endpoint never accepts or passes a client override.
    capabilities = capabilities if capabilities is not None else CHAPTER_CAPABILITIES

    action = request.writing_action
    scope = _scope(session, document_id, action.tab_id)
    identity = ActionIdentity(owner_id=scope.owner_id, workspace_id=scope.workspace_id,
                              entry="button", action_id=action.action_id)
    client_hash = canonical_hash(request.model_dump(mode="json", exclude={"writing_action": {"action_id"}}))
    claim = None
    job = None
    configured = None
    evidence = None
    started = None
    transport_started = False
    reply_received = False
    owns_action = False
    try:
        existing = lookup_action(session, identity, scope, client_hash, authorize=_authorize)
        if existing is not None:
            return _response(session, existing)
        session.rollback()
        capabilities.require("button")
        if action.preferences.semantic_mode != "off" and semantic_call_factory is None:
            raise HTTPException(409, "semantic routing is not released")
        claim = claim_pending_action(session, identity, scope, client_hash, authorize=_authorize)
        if not claim.acquired:
            return _response(session, claim)
        owns_action = True
        retry_parent = _validation_retry_parent(session, identity, scope, request)
        configured = await model_probe()
        catalog, primary = await current_catalog(asgi_app, primary_skill="prose-writing")
        pending = lookup_action(session, identity, scope, client_hash, authorize=_authorize)
        if pending is None or pending.id != claim.id or pending.fence != claim.fence or pending.state != "claimed":
            raise StaleFence("input preparation cancelled or changed")
        position = resolve_writing_position(session, document_id)
        brief = get_chapter_brief(session, document_id)
        session.rollback()
        retrieval = await retrieve_for_writing(session, novel_id=scope.scope_id,
            purpose=RetrievalPurpose.CHAPTER_BODY,
            query=deterministic_query(purpose=RetrievalPurpose.CHAPTER_BODY, title=position.title,
                outline=str(brief.get("outline_text") or ""), expectation=str(brief.get("expectation_text") or "")),
            timeline_id=position.timeline_id, narrative_sequence=position.narrative_sequence,
            story_sequence_cutoff=position.story_sequence_cutoff)
        options = dict(expected_brief_version=request.expected_brief_version, execution_agent_id="ai-novel-writer",
            requested_provider_id=configured.provider_id, requested_model_id=configured.model_id,
            generation_contract_version=GENERATION_CONTRACT_VERSION, force_new=request.force_new,
            asset_ids=request.asset_ids, preset_id=request.preset_id, writing_retrieval=retrieval,
            writing_position=position, effective_context_window_tokens=configured.effective_max_input_length)
        snapshot, _ = prepare_chapter_generation(session, document_id, **options)
        prompt = build_chapter_generation_prompt(snapshot)
        projection = chapter_routing_projection(scope, snapshot, required_ids=action.preferences.required_ids)
        if retry_parent is not None:
            frozen_primary = tuple(block for block in retry_parent.packet.blocks if block.skill_id == "prose-writing")
            if (projection != retry_parent.request.projection or configured.provider_id != retry_parent.request.provider_id
                    or configured.model_id != retry_parent.request.model_id
                    or catalog.version != retry_parent.request.catalog_version or frozen_primary != primary):
                raise ActionConflict("validation retry source or method package changed")
        frozen = FrozenRouteRequest(identity=identity, projection=projection, preferences=action.preferences,
            catalog_version=catalog.version, provider_id=configured.provider_id, model_id=configured.model_id,
            retry_of_action_id=retry_parent.identity.action_id if retry_parent is not None else None)
        claim = freeze_prepared_action(session, claim, frozen)

        async def verify_current():
            nonlocal claim
            _authorize(session, scope)
            found = lookup_action(session, identity, scope, client_hash, authorize=_authorize)
            if found.id != claim.id or found.fence != claim.fence or found.state != claim.state:
                raise StaleFence("method action changed")
            fresh_snapshot, _ = prepare_chapter_generation(session, document_id, **options)
            if chapter_routing_projection(scope, fresh_snapshot,
                                          required_ids=action.preferences.required_ids) != projection:
                raise ActionConflict("method source changed")
            session.rollback()
            fresh_model = await model_probe()
            configured.ensure_matches(fresh_model)
            fresh_catalog, fresh_primary = await current_catalog(
                asgi_app, primary_skill="prose-writing"
            )
            if (fresh_catalog.version != catalog.version or fresh_primary != primary
                    or fresh_model.effective_max_input_length != configured.effective_max_input_length):
                raise ActionConflict("method configuration changed")

        if retry_parent is not None:
            packet = retry_parent.packet
        else:
            plan = resolve_methods(projection, catalog, action.preferences, primary_skill="prose-writing")
            semantic_evidence = None
            if action.preferences.semantic_mode == "auto":
                claim = advance(session, claim, "routing_started")
                await verify_current()
                plan, semantic_evidence = await complete_button_route(
                    projection,
                    catalog,
                    plan,
                    action.preferences,
                    semantic_call=semantic_call_factory(
                        f"writing-semantic:{claim.id}", verify_current, configured
                    ),
                )
                await verify_current()
            ledger = snapshot["prompt_budget_ledger"]
            packet = compose_writing_request(plan, catalog, primary_blocks=primary,
                effective_input_budget=configured.effective_max_input_length,
                reserved_task_tokens=ledger["included_token_count"] + ledger["reserved_output_tokens"] + 2048,
                required_ids=action.preferences.required_ids,
                semantic_evidence=semantic_evidence)
        claim = advance(session, claim, "route_ready")
        claim = advance(session, claim, "assembled", packet=packet)

        await verify_current()
        job = start_chapter_generation(session, document_id, **options, method_dispatch=claim)
        claim = lookup_action(session, identity, scope, client_hash, authorize=_authorize)
        if not job.get("should_execute", True):
            return _response(session, claim, job=job)
        prompt = build_chapter_generation_prompt(job["generation_context_snapshot"])
        ensure_prompt_within_effective_limit(prompt, configured)
        session.rollback()
        started = time.monotonic()
        with managed_method_request(ManagedMethodPolicy(packet), session_id=f"novel-generation:{job['id']}",
                capabilities=capabilities, entry="button", verify_current=verify_current,
                max_model_calls=1) as binding:
            transport_started = True
            reply = await await_chapter_generation(ctx.chat(prompt, skill=None, session_id=binding.session_id))
            reply_received = True
            if not binding.factory_claimed or binding.observed_model_calls != 1:
                raise RuntimeError("managed method transport not observed exactly once")
        evidence = await verify_novel_model_reply(reply, configured=configured, probe=model_probe, started_monotonic=started)
        claim = advance(session, claim, "dispatched")
        completed = complete_chapter_generation(session, UUID(job["id"]),
            content_markdown=reply_final_text(reply), model_evidence=evidence.as_dict())
        return _response(session, claim, job=completed)
    except (Exception, asyncio.CancelledError) as error:
        session.rollback()
        if owns_action and claim is not None and claim.state in {"claimed", "routing_started", "route_ready", "assembled", "dispatch_started"}:
            semantic_uncertain = (
                isinstance(error, SemanticRouteIncomplete)
                and error.remote_outcome_uncertain
            )
            terminal = "unknown" if semantic_uncertain or (transport_started and not reply_received) else "failed"
            try:
                claim = advance(session, claim, terminal, error_code="managed_chapter_failed")
            except StaleFence:
                pass
        if job is not None and job.get("should_execute", True):
            try:
                if isinstance(error, NovelModelEvidenceRejected):
                    evidence = error.evidence
                elif evidence is None and configured is not None:
                    evidence = failed_novel_model_evidence(configured,
                        started_monotonic=started if started is not None else time.monotonic())
                actual = evidence.actual_identity if evidence is not None else None
                job = fail_chapter_generation(session, UUID(job["id"]), str(error),
                    actual_provider_id=actual.provider_id if actual is not None else None,
                    actual_model_id=actual.model_id if actual is not None else None,
                    model_evidence=evidence.as_dict() if evidence is not None else None)
            except Exception:
                session.rollback()
        if isinstance(error, asyncio.CancelledError):
            raise
        if isinstance(error, HTTPException):
            raise
        detail = (error.as_detail(job=_response(session, claim, job=job) if job is not None else None)
                  if isinstance(error, ChapterLengthValidationError)
                  else {"type": "managed_chapter_failed", "message": str(error)})
        if claim is not None:
            detail["writing_method"] = method_status(claim).model_dump(mode="json")
        status = 409 if isinstance(error, (ActionConflict, StaleFence)) else 502
        if isinstance(error, MethodPolicyViolation) and claim is None:
            status = 503
        if isinstance(error, ChapterLengthValidationError):
            status = 422
        raise HTTPException(status, detail) from error
