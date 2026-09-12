"""Full public PawApp transport; no monkeypatch, runtime core or real novels."""
from dataclasses import replace
import hashlib
import json
import os
import threading
import time
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field
from qwenpaw.pawapp import PawApp, get_ctx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .backend.database import get_session
from .backend.models import ChapterGenerationJob, Document, Novel
from .backend.creative_authority import save_outline
from .backend.schemas import GenerateChapterRequest
from .backend.services import create_novel, save_chapter_brief
from .backend.model_runtime import effective_model_audit, reply_final_text
from .backend.generation_dependencies import verify_novel_model_reply
from .backend.writing_skills.button import generate_managed_chapter
from .backend.writing_skills.contracts import FrozenModel, canonical_hash
from .backend.writing_skills.load_policy import PublicLoadCapabilities, create_managed_method_middleware
from .backend.writing_skills.semantic import SemanticRouteRequestV2
from .backend.writing_skills.semantic_runtime import build_semantic_prompt, public_semantic_call


def _plan70_outline_fields(seed):
    return {
        "background_text": f"【description】\n{seed.description}\n\n【background】\n{seed.background}",
        "plot_text": seed.main_plot,
        "highlight_text": seed.idea,
    }


def _plan70_input_evidence(seed, snapshot, prompt):
    """Observe the frozen project input before ctx.chat, not Provider wire bytes."""
    blocks = snapshot["writing_context"]["envelope"]["included_blocks"]
    sources = {}
    for section, fields in (
        ("formal_planning", ("description", "background", "main_plot", "idea")),
        ("chapter_requirements", ("expectation_text", "outline_text", "forbidden_text")),
    ):
        section_blocks = [block for block in blocks if block["section"] == section]
        for field in fields:
            value = getattr(seed, field)
            matches = [block for block in section_blocks if value in block["content"]]
            if not matches or value not in prompt:
                raise ValueError(f"Plan70 frozen input missing: {field}")
            sources[field] = value
    return {
        "schema_version": "plan70-writing-input/1",
        "observation_boundary": "project_frozen_input_before_ctx_chat",
        "provider_receipt_proven": False,
        "sources": sources,
        "source_hash": canonical_hash(sources),
        "included_blocks": blocks,
        "brief_version": snapshot["brief"]["version"],
        "snapshot_sha256": canonical_hash(snapshot),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    }


class _Plan70ProseContext:
    """Narrow test adapter around the public chat callable; no host patching."""

    def __init__(self, ctx, session, document_id, seed):
        self.ctx, self.session = ctx, session
        self.document_id, self.seed = document_id, seed
        self.evidence = None

    async def chat(self, prompt, *, skill, session_id):
        if self.evidence is not None or not session_id.startswith("novel-generation:"):
            raise ValueError("Plan70 unexpected or repeated prose call")
        job = self.session.get(ChapterGenerationJob, UUID(session_id.split(":", 1)[1]))
        if job is None or job.document_id != self.document_id:
            raise ValueError("Plan70 input job scope mismatch")
        self.evidence = _plan70_input_evidence(
            self.seed, job.generation_context_snapshot, prompt,
        )
        self.session.rollback()
        return await self.ctx.chat(prompt, skill=skill, session_id=session_id)


pawapp = PawApp(name="S58 isolated chapter transport", app_id="s58-chapter-transport")
router = APIRouter()
_attempt_lock = threading.Lock()
_started_attempts: set[str] = set()
_PLAN70_ALLOWED_REQUEST_DIFFERENCES = [
    "arm",
    "generation.writing_action.action_id",
    "generation.writing_action.tab_id",
    "generation.writing_action.preferences.mode",
    "generation.writing_action.preferences.semantic_mode",
]
_PLAN70_SAMPLING_POLICY = {
    "request_level_overrides": {},
    "provider_defaults_apply": True,
    "variance_control": "balanced_interleaved_execution_order",
}


class Plan70SemanticRoutePayload(FrozenModel):
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
    scenario_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")
    attempt_id: UUID
    request: SemanticRouteRequestV2


class Plan70WritingSeed(FrozenModel):
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=4000)
    genre: str = Field(min_length=1, max_length=80)
    subgenre: str = Field(min_length=1, max_length=80)
    idea: str = Field(min_length=1, max_length=12000)
    background: str = Field(min_length=1, max_length=30000)
    main_plot: str = Field(min_length=1, max_length=30000)
    chapter_title: str = Field(min_length=1, max_length=240)
    expectation_text: str = Field(min_length=1, max_length=12000)
    outline_text: str = Field(min_length=1, max_length=30000)
    forbidden_text: str = Field(min_length=1, max_length=8000)


class Plan70WritingCellRequest(FrozenModel):
    pair_id: str = Field(pattern=r"^T0[1-4]$")
    arm: Literal["A", "B"]
    seed: Plan70WritingSeed
    generation: GenerateChapterRequest


class Plan70WritingCellPayload(FrozenModel):
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
    cell_id: str = Field(pattern=r"^T0[1-4]-[AB]$")
    attempt_id: UUID
    request: Plan70WritingCellRequest


def _plan70_shared_input_hash(request: Plan70WritingCellRequest) -> str:
    value = request.model_dump(mode="json")
    value["arm"] = "<METHOD_ARM>"
    action = value["generation"]["writing_action"]
    action["action_id"] = "<ACTION_ID>"
    action["tab_id"] = "<TAB_ID>"
    preferences = action["preferences"]
    preferences["mode"] = "<METHOD_MODE>"
    preferences["semantic_mode"] = "<SEMANTIC_MODE>"
    return canonical_hash(value)


def _plan70_approval(payload: Plan70SemanticRoutePayload) -> dict:
    raw = os.environ.get("PLAN70_SEMANTIC_EVAL_APPROVAL_JSON", "")
    if not raw or len(raw) > 32_000:
        raise HTTPException(403, "Plan70 semantic evaluation is not approved")
    try:
        approval = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as error:
        raise HTTPException(403, "invalid Plan70 semantic approval") from error
    if not isinstance(approval, dict) or set(approval) != {
        "schema_version", "run_id", "provider_id", "model_id", "cases",
    } or approval.get("schema_version") != "plan70-semantic-eval-approval/1":
        raise HTTPException(403, "invalid Plan70 semantic approval")
    cases = approval.get("cases")
    if (not all(isinstance(approval.get(key), str) and approval[key].strip()
                for key in ("run_id", "provider_id", "model_id"))
            or not isinstance(cases, list) or not 1 <= len(cases) <= 46):
        raise HTTPException(403, "invalid Plan70 semantic approval")
    scenario_ids: set[str] = set()
    attempt_ids: set[str] = set()
    for item in cases:
        if not isinstance(item, dict) or set(item) != {
            "scenario_id", "attempt_id", "request_hash",
        }:
            raise HTTPException(403, "invalid Plan70 semantic approval case")
        scenario_id = item.get("scenario_id")
        attempt_id = item.get("attempt_id")
        request_hash = item.get("request_hash")
        try:
            UUID(str(attempt_id))
        except (TypeError, ValueError, AttributeError) as error:
            raise HTTPException(403, "invalid Plan70 semantic approval case") from error
        if (not isinstance(scenario_id, str) or not scenario_id
                or not isinstance(attempt_id, str)
                or not isinstance(request_hash, str) or len(request_hash) != 64
                or any(character not in "0123456789abcdef" for character in request_hash)
                or scenario_id in scenario_ids or attempt_id in attempt_ids):
            raise HTTPException(403, "invalid or duplicate Plan70 semantic approval case")
        scenario_ids.add(scenario_id)
        attempt_ids.add(attempt_id)
    if approval["run_id"] != payload.run_id:
        raise HTTPException(403, "Plan70 run is outside the approval")
    matches = [item for item in cases if item["scenario_id"] == payload.scenario_id]
    if len(matches) != 1:
        raise HTTPException(403, "Plan70 scenario is outside the approval")
    match = matches[0]
    if (match["attempt_id"] != str(payload.attempt_id)
            or match["request_hash"] != canonical_hash(payload.request)):
        raise HTTPException(403, "Plan70 frozen request does not match approval")
    return approval


def _plan70_writing_approval(payload: Plan70WritingCellPayload) -> dict:
    approval_path = os.environ.get("PLAN70_WRITING_AB_APPROVAL_FILE", "").strip()
    if approval_path:
        try:
            with open(approval_path, "r", encoding="utf-8") as handle:
                raw = handle.read(64_001)
        except OSError as error:
            raise HTTPException(403, "Plan70 writing A/B approval is unavailable") from error
    else:
        raw = os.environ.get("PLAN70_WRITING_AB_APPROVAL_JSON", "")
    if not raw or len(raw) > 64_000:
        raise HTTPException(403, "Plan70 writing A/B evaluation is not approved")
    try:
        approval = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as error:
        raise HTTPException(403, "invalid Plan70 writing A/B approval") from error
    if not isinstance(approval, dict) or set(approval) != {
        "schema_version", "run_id", "provider_id", "model_id",
        "effective_max_input_length", "fixture_sha256", "methods",
        "comparison_contract", "cells",
    } or approval.get("schema_version") != "plan70-writing-ab-approval/3":
        raise HTTPException(403, "invalid Plan70 writing A/B approval")
    cells = approval.get("cells")
    fixture_hash = approval.get("fixture_sha256")
    if (not all(isinstance(approval.get(key), str) and approval[key].strip()
                for key in ("run_id", "provider_id", "model_id"))
            or not isinstance(fixture_hash, str) or len(fixture_hash) != 64
            or any(character not in "0123456789abcdef" for character in fixture_hash)
            or type(approval.get("effective_max_input_length")) is not int
            or approval["effective_max_input_length"] <= 0
            or not isinstance(approval.get("methods"), list)
            or len(approval["methods"]) != 2
            or not isinstance(cells, list) or not 1 <= len(cells) <= 8):
        raise HTTPException(403, "invalid Plan70 writing A/B approval")
    expected_method_ids = ["prose-writing", "golden-finger-writing"]
    for index, method in enumerate(approval["methods"]):
        if (not isinstance(method, dict) or set(method) != {
                "skill_id", "version", "body_sha256",
            } or method.get("skill_id") != expected_method_ids[index]
                or not isinstance(method.get("version"), str)
                or not isinstance(method.get("body_sha256"), str)
                or len(method["body_sha256"]) != 64
                or any(character not in "0123456789abcdef"
                       for character in method["body_sha256"])):
            raise HTTPException(403, "invalid Plan70 writing A/B approved method")
    comparison = approval.get("comparison_contract")
    if (not isinstance(comparison, dict) or set(comparison) != {
            "schema_version", "allowed_request_differences", "sampling_policy",
            "pair_baselines",
        } or comparison.get("schema_version") != "plan70-writing-ab-comparison/1"
            or comparison.get("allowed_request_differences")
            != _PLAN70_ALLOWED_REQUEST_DIFFERENCES
            or comparison.get("sampling_policy") != _PLAN70_SAMPLING_POLICY):
        raise HTTPException(403, "invalid Plan70 writing A/B comparison contract")
    baselines = comparison.get("pair_baselines")
    if (not isinstance(baselines, list) or len(baselines) != 4
            or [item.get("pair_id") for item in baselines
                if isinstance(item, dict)] != ["T01", "T02", "T03", "T04"]
            or any(not isinstance(item, dict) or set(item) != {
                "pair_id", "shared_input_hash",
            } or not isinstance(item.get("shared_input_hash"), str)
                or len(item["shared_input_hash"]) != 64
                or any(character not in "0123456789abcdef"
                       for character in item["shared_input_hash"])
                for item in baselines)):
        raise HTTPException(403, "invalid Plan70 writing A/B pair baselines")
    cell_ids: set[str] = set()
    attempt_ids: set[str] = set()
    action_ids: set[str] = set()
    for item in cells:
        if not isinstance(item, dict) or set(item) != {
            "cell_id", "attempt_id", "action_id", "request_hash",
        }:
            raise HTTPException(403, "invalid Plan70 writing A/B approval cell")
        try:
            UUID(str(item.get("attempt_id")))
            UUID(str(item.get("action_id")))
        except (TypeError, ValueError, AttributeError) as error:
            raise HTTPException(403, "invalid Plan70 writing A/B approval cell") from error
        cell_id = item.get("cell_id")
        attempt_id = item.get("attempt_id")
        action_id = item.get("action_id")
        request_hash = item.get("request_hash")
        if (not isinstance(cell_id, str) or not cell_id
                or not isinstance(attempt_id, str) or not isinstance(action_id, str)
                or not isinstance(request_hash, str) or len(request_hash) != 64
                or any(character not in "0123456789abcdef" for character in request_hash)
                or cell_id in cell_ids or attempt_id in attempt_ids or action_id in action_ids):
            raise HTTPException(403, "invalid or duplicate Plan70 writing A/B approval cell")
        cell_ids.add(cell_id)
        attempt_ids.add(attempt_id)
        action_ids.add(action_id)
    if approval["run_id"] != payload.run_id:
        raise HTTPException(403, "Plan70 writing run is outside the approval")
    matches = [item for item in cells if item["cell_id"] == payload.cell_id]
    if len(matches) != 1:
        raise HTTPException(403, "Plan70 writing cell is outside the approval")
    match = matches[0]
    action = payload.request.generation.writing_action
    if (match["attempt_id"] != str(payload.attempt_id)
            or action is None or match["action_id"] != str(action.action_id)
            or match["request_hash"] != canonical_hash(payload.request)):
        raise HTTPException(403, "Plan70 frozen writing request does not match approval")
    baseline = next(
        item for item in baselines if item["pair_id"] == payload.request.pair_id
    )
    if baseline["shared_input_hash"] != _plan70_shared_input_hash(payload.request):
        raise HTTPException(403, "Plan70 shared A/B input does not match approval")
    return approval


def _validate_plan70_writing_cell(payload: Plan70WritingCellPayload) -> None:
    value = payload.request
    generation = value.generation
    action = generation.writing_action
    if value.pair_id != payload.cell_id[:3] or value.arm != payload.cell_id[-1]:
        raise HTTPException(403, "Plan70 writing cell identity mismatch")
    if (generation.expected_brief_version != 1 or generation.force_new
            or generation.asset_ids or generation.preset_id is not None
            or action is None or action.retry_of_action_id is not None):
        raise HTTPException(403, "Plan70 writing cell must be one fresh unassisted action")
    preferences = action.preferences
    if preferences.excluded_ids or preferences.required_ids:
        raise HTTPException(403, "Plan70 writing cell cannot force or exclude methods")
    expected = (
        ("generic_only", "off") if value.arm == "A" else ("auto", "auto")
    )
    if (preferences.mode, preferences.semantic_mode) != expected:
        raise HTTPException(403, "Plan70 writing arm method policy mismatch")


@router.post("/semantic-route")
async def run_semantic_route(payload: Plan70SemanticRoutePayload, request: Request,
                             ctx=Depends(get_ctx)):
    approval = _plan70_approval(payload)
    attempt_key = f"{payload.run_id}:{payload.scenario_id}:{payload.attempt_id}"
    with _attempt_lock:
        if attempt_key in _started_attempts:
            raise HTTPException(409, "Plan70 attempt was already started")
        _started_attempts.add(attempt_key)

    async def probe():
        current = _plan70_approval(payload)
        result = await effective_model_audit(request.app, agent_id="ai-novel-writer")
        if (result.provider_id, result.model_id) != (
            current["provider_id"], current["model_id"],
        ):
            raise HTTPException(409, "Plan70 approved effective model changed")
        return result

    configured = await probe()
    managed_ctx = replace(ctx, agent_id="ai-novel-writer")
    started = time.monotonic()

    async def verify_current():
        await probe()

    async def verify_reply(reply):
        await verify_novel_model_reply(
            reply, configured=configured, probe=probe, started_monotonic=started,
        )
        return reply_final_text(reply)

    call = public_semantic_call(
        ctx=managed_ctx,
        session_id=f"plan70-semantic:{payload.run_id}:{payload.scenario_id}:{payload.attempt_id}",
        capabilities=PublicLoadCapabilities(True, True, True),
        verify_current=verify_current,
        verify_reply=verify_reply,
    )
    observation = await call(build_semantic_prompt(payload.request), payload.request)
    return {
        "schema_version": "plan70-semantic-route-transport/1",
        "run_id": payload.run_id,
        "scenario_id": payload.scenario_id,
        "attempt_id": str(payload.attempt_id),
        "provider_id": approval["provider_id"],
        "model_id": approval["model_id"],
        "observation": observation.model_dump(mode="json"),
    }


@router.post("/writing-ab")
async def run_writing_ab(payload: Plan70WritingCellPayload, request: Request,
                         ctx=Depends(get_ctx), session: Session = Depends(get_session)):
    approval = _plan70_writing_approval(payload)
    _validate_plan70_writing_cell(payload)
    attempt_key = f"writing:{payload.run_id}:{payload.cell_id}:{payload.attempt_id}"
    with _attempt_lock:
        if attempt_key in _started_attempts:
            raise HTTPException(409, "Plan70 writing attempt was already started")
        _started_attempts.add(attempt_key)

    async def probe():
        current = _plan70_writing_approval(payload)
        result = await effective_model_audit(request.app, agent_id="ai-novel-writer")
        if (result.provider_id, result.model_id) != (
            current["provider_id"], current["model_id"],
        ):
            raise HTTPException(409, "Plan70 approved writing model changed")
        if result.effective_max_input_length is None:
            result = replace(
                result,
                source="effective-model-api+plan70-approved-context",
                effective_max_input_length=current["effective_max_input_length"],
            )
        return result

    await probe()
    seed = payload.request.seed
    created = create_novel(session, seed.title, seed.description)
    novel_id = UUID(created["id"])
    document_id = UUID(created["initial_document_id"])
    novel = session.get(Novel, novel_id)
    document = session.get(Document, document_id)
    if novel is None or document is None:
        raise HTTPException(500, "Plan70 synthetic writing seed was not created")
    novel.genre = seed.genre
    novel.subgenre = seed.subgenre
    novel.idea = seed.idea
    novel.background = seed.background
    novel.main_plot = seed.main_plot
    document.title = seed.chapter_title
    session.commit()
    save_outline(
        session, novel_id, expected_head_version=0,
        idempotency_key=f"plan70-outline:{payload.attempt_id}",
        source_kind="manual", target_chapter_count=12,
        **_plan70_outline_fields(seed),
    )
    session.commit()
    brief = save_chapter_brief(
        session,
        document_id,
        expected_version=0,
        target_word_count=2500,
        expectation_text=seed.expectation_text,
        outline_text=seed.outline_text,
        forbidden_text=seed.forbidden_text,
        role_constraints={},
    )
    managed_ctx = replace(ctx, agent_id="ai-novel-writer")
    capabilities = PublicLoadCapabilities(True, True, True)

    def semantic_factory(session_id, verify_current, configured):
        started = time.monotonic()

        async def verify_reply(reply):
            await verify_novel_model_reply(
                reply,
                configured=configured,
                probe=probe,
                started_monotonic=started,
            )
            return reply_final_text(reply)

        return public_semantic_call(
            ctx=managed_ctx,
            session_id=session_id,
            capabilities=capabilities,
            verify_current=verify_current,
            verify_reply=verify_reply,
        )

    prose_ctx = _Plan70ProseContext(managed_ctx, session, document_id, seed)
    generated = await generate_managed_chapter(
        document_id=document_id,
        request=payload.request.generation,
        ctx=prose_ctx,
        model_probe=probe,
        session=session,
        asgi_app=request.app,
        capabilities=capabilities,
        semantic_call_factory=(
            semantic_factory if payload.request.arm == "B" else None
        ),
    )
    method = generated.get("writing_method") or {}
    expected_ids = ["golden-finger-writing"] if payload.request.arm == "B" else []
    candidate = generated.get("candidate") or {}
    details = method.get("details") or {}
    method_items = details.get("methods") or []
    observed_methods = [
        {
            "skill_id": item.get("skill_id"),
            "version": item.get("version"),
            "body_sha256": item.get("body_sha256"),
        }
        for item in method_items
        if isinstance(item, dict)
    ]
    expected_methods = (
        approval["methods"] if payload.request.arm == "B" else approval["methods"][:1]
    )
    if (generated.get("state") != "ready" or method.get("selected_ids") != expected_ids
            or method.get("auxiliary_calls") != (1 if payload.request.arm == "B" else 0)
            or observed_methods != expected_methods
            or candidate.get("state") != "ready"
            or candidate.get("adopted_revision_id") is not None):
        raise HTTPException(409, "Plan70 writing result violated the frozen A/B contract")
    return {
        "schema_version": "plan70-writing-ab-transport/2",
        "run_id": payload.run_id,
        "cell_id": payload.cell_id,
        "attempt_id": str(payload.attempt_id),
        "pair_id": payload.request.pair_id,
        "arm": payload.request.arm,
        "provider_id": approval["provider_id"],
        "model_id": approval["model_id"],
        "novel_id": str(novel_id),
        "document_id": str(document_id),
        "brief_version": brief["version"],
        "input_evidence": prose_ctx.evidence,
        "prose_model_call_limit": 1,
        "automatic_retries": 0,
        "generation": generated,
    }


@router.post("/chapters/{document_id}")
async def run(document_id: UUID, payload: GenerateChapterRequest, request: Request,
              ctx=Depends(get_ctx), session: Session = Depends(get_session)):
    title = session.scalar(select(Novel.title).join(Document, Document.novel_id == Novel.id)
                           .where(Document.id == document_id))
    if title != "s58-method-atomic-test" or payload.writing_action is None:
        raise HTTPException(403, "only the synthetic S58 chapter fixture is allowed")
    session.rollback()
    async def probe():
        result = await effective_model_audit(request.app, agent_id="ai-novel-writer")
        if (result.provider_id, result.model_id) != ("s58-fake", "s58-fake-model"):
            raise HTTPException(403, "only the configured loopback fake model is allowed")
        return result
    managed_ctx = replace(ctx, agent_id="ai-novel-writer")
    capabilities = PublicLoadCapabilities(True, True, True)

    def semantic_factory(session_id, verify_current, configured):
        started = time.monotonic()

        async def verify_reply(reply):
            await verify_novel_model_reply(
                reply,
                configured=configured,
                probe=probe,
                started_monotonic=started,
            )
            return reply_final_text(reply)

        return public_semantic_call(
            ctx=managed_ctx,
            session_id=session_id,
            capabilities=capabilities,
            verify_current=verify_current,
            verify_reply=verify_reply,
        )

    return await generate_managed_chapter(document_id=document_id, request=payload,
        ctx=managed_ctx, model_probe=probe, session=session,
        asgi_app=request.app, capabilities=capabilities,
        semantic_call_factory=(semantic_factory
                               if payload.writing_action.preferences.semantic_mode == "auto"
                               else None))


pawapp.include_router(router)


class FixturePlugin:
    def register(self, api):
        if not os.environ.get("AI_NOVEL_DATABASE_URL", "").endswith("@postgres:5432/ai_novel_s58_test"):
            raise RuntimeError("S58 fixture requires the disposable test database")
        pawapp.register(api)
        api.register_middleware(create_managed_method_middleware, priority=65)


plugin = FixturePlugin()
