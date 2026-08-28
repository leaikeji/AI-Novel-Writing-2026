"""AI小说世界2026 PawApp HTTP API."""

from __future__ import annotations

import os
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from qwenpaw.pawapp import PawApp
from sqlalchemy.orm import Session

from .assistant_api import router as assistant_router
from .contracts import APP_ID, APP_VERSION
from .creative_api import router as creative_router
from .creative_schemas import SELECTION_EDIT_OPERATIONS
from .creative_services import sync_relationships_from_intelligence_proposal
from .database import database_status, get_engine, get_session
from .generation_dependencies import (
    get_novel_effective_model,
    get_novel_generation_ctx,
)
from .model_runtime import (
    GENERATION_CONTRACT_VERSION,
    NOVEL_AGENT_ID,
    ModelAudit,
    ModelVerificationError,
    effective_model_audit,
    ensure_prompt_within_effective_limit,
    normalize_intelligence_generation_json,
    parse_model_json,
    reply_model_audit,
)
from .writing_eval_api import router as writing_eval_router
from .narration.pawapp_runtime import (
    launch_narration_runtime,
    narration_runtime_status,
    stop_narration_runtime,
)
from .narration.health_api import router as narration_health_router
from .narration.disk_guard import DISK_SPACE_INSUFFICIENT
from .narration.narration_api import router as narration_production_router
from .narration.official_presets import (
    OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256,
)
from .narration.playback_api import router as narration_playback_router
from .narration.production_runtime import (
    PRODUCT_ENABLE_ENV,
    REFERENCE_CLONE_ENABLE_ENV,
    ValidationRuntimeScope,
    VALIDATION_ENABLE_ENV,
    current_narration_cache_runtime,
    current_narration_production_policy,
    current_validation_runtime_scope,
    current_voice_product_port,
    launch_narration_production_runtime,
    narration_production_runtime_status,
    stop_narration_production_runtime,
    validation_route_token_authorized,
)
from .narration.privacy import (
    FIXED_LOCAL_OWNER_NARRATION_AUTHORIZATION,
    build_narration_settings_backend,
    t2_settings_capabilities,
    t4_product_capabilities,
)
from .narration.settings_api import (
    install_narration_settings_backend_factory,
    router as narration_settings_router,
    uninstall_narration_settings_backend_factory,
)
from .narration.script_api import (
    install_script_api_backend_factory,
    router as narration_script_router,
    uninstall_script_api_backend_factory,
)
from .narration.script_backend import build_script_api_backend
from .narration.release_gate import (
    VALIDATION_TOKEN_HEADER,
    install_narration_t4_http_access_policy,
    uninstall_narration_t4_http_access_policy,
)
from .narration.voice_product import SqlAlchemyVoiceActionReceiptPort
from .narration.validation_access import validation_request_scope_authorized
from .schemas import (
    AdoptCandidateRequest,
    CheckpointRequest,
    CommitIntelligenceRequest,
    CreateDocumentRequest,
    CreateNovelRequest,
    CreateVolumeRequest,
    ExtractIntelligenceRequest,
    GenerateChapterRequest,
    ReviewIntelligenceItemRequest,
    RestoreRevisionRequest,
    SaveDraftRequest,
    SaveChapterBriefRequest,
)
from .services import (
    BriefConflictError,
    CandidateConflictError,
    DraftConflictError,
    NotFoundError,
    ProposalSupersededError,
    RestorationPlanConflictError,
    ValidationError,
    adopt_candidate,
    build_chapter_generation_prompt,
    build_intelligence_prompt,
    commit_intelligence_items,
    complete_chapter_generation,
    complete_intelligence_proposal,
    create_checkpoint,
    create_document,
    create_novel,
    create_volume,
    fail_chapter_generation,
    fail_intelligence_proposal,
    get_candidate,
    get_chapter_brief,
    get_document,
    get_novel,
    get_novel_context,
    get_revision,
    list_chapter_generation_jobs,
    list_intelligence_proposals,
    list_novels,
    list_story_facts,
    preview_restore_revision,
    reject_candidate,
    review_intelligence_item,
    restore_revision,
    save_draft,
    save_chapter_brief,
    search_novel,
    start_chapter_generation,
    start_intelligence_proposal,
)


pawapp = PawApp(name="AI小说世界2026", app_id=APP_ID)
router = APIRouter()
router.include_router(assistant_router)
router.include_router(creative_router)
router.include_router(narration_settings_router)
router.include_router(narration_health_router)
router.include_router(narration_script_router)
router.include_router(narration_production_router)
router.include_router(narration_playback_router)
router.include_router(writing_eval_router)


def _production_runtime_accessible(status_snapshot: dict[str, object]) -> bool:
    """Keep existing playback readable while low space pauses new claims."""

    reason_code = status_snapshot.get("reason_code")
    return reason_code is None or (
        type(reason_code) is str and reason_code == DISK_SPACE_INSUFFICIENT
    )


def _t4_product_release_runtime_ready() -> bool:
    """Open public T4 capabilities only after the whole live chain is ready.

    The hidden T4-K validation runtime deliberately installs the same backend
    and worker while PRODUCT_ENABLE_ENV remains false.  It must never make this
    predicate true or expose production controls in the ordinary workbench.
    """

    if (
        os.environ.get(PRODUCT_ENABLE_ENV, "false") != "true"
        or os.environ.get(VALIDATION_ENABLE_ENV, "false") != "false"
    ):
        return False
    reference_clone = os.environ.get(REFERENCE_CLONE_ENABLE_ENV, "false")
    if reference_clone not in {"true", "false"} or (
        reference_clone == "true" and current_voice_product_port() is None
    ):
        return False
    technical = narration_runtime_status()
    production = narration_production_runtime_status()
    return (
        technical.get("technical_enabled") is True
        and technical.get("lifecycle_status") == "ready"
        and technical.get("sidecar_reachable") is True
        and technical.get("model_ready") is True
        and technical.get("product_visible") is True
        and technical.get("reason_code") is None
        and production.get("product_requested") is True
        and production.get("lifecycle_status") == "ready"
        and production.get("playback_installed") is True
        and production.get("digest_keyring_loaded") is True
        and production.get("production_backend_installed") is True
        and production.get("worker_running") is True
        and _production_runtime_accessible(production)
    )


def _t4_hidden_validation_runtime_ready() -> bool:
    """Require the same healthy chain while keeping public product visibility off."""

    if (
        os.environ.get(PRODUCT_ENABLE_ENV, "false") != "false"
        or os.environ.get(VALIDATION_ENABLE_ENV, "false") != "true"
    ):
        return False
    reference_clone = os.environ.get(REFERENCE_CLONE_ENABLE_ENV, "false")
    if reference_clone not in {"true", "false"} or (
        reference_clone == "true" and current_voice_product_port() is None
    ):
        return False
    technical = narration_runtime_status()
    production = narration_production_runtime_status()
    return (
        technical.get("technical_enabled") is True
        and technical.get("lifecycle_status") == "ready"
        and technical.get("sidecar_reachable") is True
        and technical.get("model_ready") is True
        and technical.get("product_visible") is False
        and technical.get("reason_code") is None
        and production.get("product_requested") is True
        and production.get("lifecycle_status") == "ready"
        and production.get("playback_installed") is True
        and production.get("digest_keyring_loaded") is True
        and production.get("production_backend_installed") is True
        and production.get("worker_running") is True
        and _production_runtime_accessible(production)
        and current_validation_runtime_scope() is not None
    )


def _validation_request_scope_allowed(
    request: Request,
    scope: ValidationRuntimeScope,
) -> bool:
    """Resolve the bearer-authenticated request through a SELECT-only scope check."""

    try:
        with Session(get_engine()) as session:
            return validation_request_scope_authorized(
                session,
                request,
                scope,
            )
    except Exception:
        return False


def _narration_t4_http_access_allowed(request: Request) -> bool:
    """Allow released T4, or one header-authenticated hidden validation run."""

    if _t4_product_release_runtime_ready():
        return True
    if not _t4_hidden_validation_runtime_ready():
        return False
    values = request.headers.getlist(VALIDATION_TOKEN_HEADER)
    if len(values) != 1 or not validation_route_token_authorized(values[0]):
        return False
    scope = current_validation_runtime_scope()
    if scope is None:
        return False
    return _validation_request_scope_allowed(request, scope)


_NARRATION_T4_HTTP_ACCESS_POLICY = _narration_t4_http_access_allowed


def _build_fixed_local_owner_narration_backend(
    session: Session,
    request: Request | None = None,
):  # type: ignore[no-untyped-def]
    """Bind T2 to the project's audited single-user, loopback-only trust domain."""

    product_ready = _t4_product_release_runtime_ready() or (
        request is not None and _narration_t4_http_access_allowed(request)
    )
    reference_clone_requested = (
        os.environ.get(REFERENCE_CLONE_ENABLE_ENV, "false") == "true"
    )
    voice_product = current_voice_product_port()
    production_policy = current_narration_production_policy()
    official_presets_ready = (
        product_ready
        and voice_product is not None
        and production_policy is not None
        and production_policy.tts_fingerprint
        == OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256
    )
    reference_clone_ready = (
        official_presets_ready
        and reference_clone_requested
    )
    if product_ready and not official_presets_ready:
        product_ready = False
    return build_narration_settings_backend(
        session,
        authorization=FIXED_LOCAL_OWNER_NARRATION_AUTHORIZATION,
        profile_creation_receipts=SqlAlchemyVoiceActionReceiptPort(session),
        cache_runtime=current_narration_cache_runtime(),
        voice_product=(voice_product if official_presets_ready else None),
        capabilities=(
            t4_product_capabilities(
                reference_clone_released=reference_clone_ready,
                official_presets_released=official_presets_ready,
            )
            if product_ready
            else t2_settings_capabilities()
        ),
    )


_NARRATION_SETTINGS_BACKEND_FACTORY = _build_fixed_local_owner_narration_backend


def _build_fixed_local_owner_script_backend(session: Session):  # type: ignore[no-untyped-def]
    """Bind script review to the same request-scoped DB and live TTS policy."""

    return build_script_api_backend(
        session,
        production_policy_provider=current_narration_production_policy,
    )


_NARRATION_SCRIPT_BACKEND_FACTORY = _build_fixed_local_owner_script_backend


@pawapp.hook("startup", priority=100)
async def _launch_narration_runtime() -> None:
    install_narration_t4_http_access_policy(
        _NARRATION_T4_HTTP_ACCESS_POLICY,
    )
    try:
        install_narration_settings_backend_factory(
            _NARRATION_SETTINGS_BACKEND_FACTORY,
        )
        try:
            install_script_api_backend_factory(
                _NARRATION_SCRIPT_BACKEND_FACTORY,
            )
            try:
                await launch_narration_runtime()
                try:
                    await launch_narration_production_runtime()
                except BaseException:
                    try:
                        await stop_narration_production_runtime()
                    finally:
                        await stop_narration_runtime()
                    raise
            except BaseException:
                uninstall_script_api_backend_factory(
                    _NARRATION_SCRIPT_BACKEND_FACTORY,
                )
                raise
        except BaseException:
            uninstall_narration_settings_backend_factory(
                _NARRATION_SETTINGS_BACKEND_FACTORY,
            )
            raise
    except BaseException:
        uninstall_narration_t4_http_access_policy(
            _NARRATION_T4_HTTP_ACCESS_POLICY,
        )
        raise


@pawapp.hook("shutdown", priority=100)
async def _stop_narration_runtime() -> None:
    try:
        await stop_narration_production_runtime()
    finally:
        try:
            await stop_narration_runtime()
        finally:
            try:
                uninstall_script_api_backend_factory(
                    _NARRATION_SCRIPT_BACKEND_FACTORY,
                )
            finally:
                try:
                    uninstall_narration_settings_backend_factory(
                        _NARRATION_SETTINGS_BACKEND_FACTORY,
                    )
                finally:
                    uninstall_narration_t4_http_access_policy(
                        _NARRATION_T4_HTTP_ACCESS_POLICY,
                    )


@pawapp.on_uninstall
async def _uninstall_narration_runtime() -> None:
    try:
        await stop_narration_production_runtime()
    finally:
        try:
            await stop_narration_runtime()
        finally:
            try:
                uninstall_script_api_backend_factory(
                    _NARRATION_SCRIPT_BACKEND_FACTORY,
                )
            finally:
                try:
                    uninstall_narration_settings_backend_factory(
                        _NARRATION_SETTINGS_BACKEND_FACTORY,
                    )
                finally:
                    uninstall_narration_t4_http_access_policy(
                        _NARRATION_T4_HTTP_ACCESS_POLICY,
                    )


def _raise_domain(error: Exception) -> None:
    if isinstance(error, DraftConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"type": "draft_conflict", "current": error.current},
        ) from error
    if isinstance(error, BriefConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"type": "brief_conflict", "current": error.current},
        ) from error
    if isinstance(error, CandidateConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "type": "candidate_conflict",
                "current": error.current,
                "candidate": error.candidate,
            },
        ) from error
    if isinstance(error, ProposalSupersededError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"type": "proposal_superseded", "proposal": error.proposal},
        ) from error
    if isinstance(error, RestorationPlanConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"type": "restoration_plan_conflict", "current": error.current},
        ) from error
    if isinstance(error, NotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    if isinstance(error, ValidationError):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    raise error


@router.get("/health")
def health() -> dict[str, object]:
    database = database_status()
    return {
        "app_id": APP_ID,
        "version": APP_VERSION,
        "status": "ready" if database["connected"] else "degraded",
        "database": database,
        "ai_candidate_generation_enabled": True,
        "ai_authoritative_write_enabled": False,
        "generation_agent_id": NOVEL_AGENT_ID,
        "generation_model_policy": "follow-agent-effective",
        "model_verification_mode": "preflight-effective+provider-usage",
        "selection_edit_enabled": True,
        "selection_edit_operations": list(SELECTION_EDIT_OPERATIONS),
        "vector_retrieval_enabled": False,
        "narration": narration_runtime_status(),
        "narration_production": narration_production_runtime_status(),
    }


@router.get("/generation-model")
async def generation_model_status(request: Request) -> dict[str, object]:
    try:
        configured = await effective_model_audit(
            request.app,
            agent_id=NOVEL_AGENT_ID,
        )
    except ModelVerificationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"type": "generation_model_unavailable", "message": str(error)},
        ) from error
    return {
        "agent_id": NOVEL_AGENT_ID,
        "provider_id": configured.provider_id,
        "model_id": configured.model_id,
        "effective_max_input_length": configured.effective_max_input_length,
        "policy": "follow-agent-effective",
    }


@router.get("/novels")
def novels_index(session: Session = Depends(get_session)) -> list[dict[str, object]]:
    return list_novels(session)


@router.post("/novels", status_code=status.HTTP_201_CREATED)
def novels_create(
    request: CreateNovelRequest, session: Session = Depends(get_session)
) -> dict[str, object]:
    try:
        return create_novel(session, request.title, request.description)
    except Exception as error:
        _raise_domain(error)
        raise


@router.get("/novels/{novel_id}")
def novels_get(novel_id: UUID, session: Session = Depends(get_session)) -> dict[str, object]:
    try:
        return get_novel(session, novel_id)
    except Exception as error:
        _raise_domain(error)
        raise


@router.get("/novels/{novel_id}/tree")
def novels_tree(novel_id: UUID, session: Session = Depends(get_session)) -> list[dict[str, object]]:
    try:
        return get_novel(session, novel_id)["tree"]
    except Exception as error:
        _raise_domain(error)
        raise


@router.post("/novels/{novel_id}/volumes", status_code=status.HTTP_201_CREATED)
def volumes_create(
    novel_id: UUID,
    request: CreateVolumeRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return create_volume(session, novel_id, request.title)
    except Exception as error:
        _raise_domain(error)
        raise


@router.post("/novels/{novel_id}/documents", status_code=status.HTTP_201_CREATED)
def documents_create(
    novel_id: UUID,
    request: CreateDocumentRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return create_document(
            session,
            novel_id,
            request.title,
            kind=request.kind,
            volume_id=request.volume_id,
        )
    except Exception as error:
        _raise_domain(error)
        raise


@router.get("/documents/{document_id}")
def documents_get(
    document_id: UUID, session: Session = Depends(get_session)
) -> dict[str, object]:
    try:
        return get_document(session, document_id)
    except Exception as error:
        _raise_domain(error)
        raise


@router.patch("/documents/{document_id}/draft")
def documents_save_draft(
    document_id: UUID,
    request: SaveDraftRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return save_draft(
            session,
            document_id,
            expected_draft_version=request.expected_draft_version,
            content_markdown=request.content_markdown,
            client_hash=request.content_hash,
        )
    except Exception as error:
        session.rollback()
        _raise_domain(error)
        raise


@router.post("/documents/{document_id}/checkpoints", status_code=status.HTTP_201_CREATED)
def documents_checkpoint(
    document_id: UUID,
    request: CheckpointRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return create_checkpoint(
            session, document_id, expected_draft_version=request.expected_draft_version
        )
    except Exception as error:
        session.rollback()
        _raise_domain(error)
        raise


@router.get("/documents/{document_id}/revisions/{revision_id}")
def revisions_get(
    document_id: UUID,
    revision_id: UUID,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return get_revision(session, document_id, revision_id)
    except Exception as error:
        _raise_domain(error)
        raise


@router.post(
    "/documents/{document_id}/revisions/{revision_id}/restore",
    status_code=status.HTTP_201_CREATED,
)
def revisions_restore(
    document_id: UUID,
    revision_id: UUID,
    request: RestoreRevisionRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return restore_revision(
            session,
            document_id,
            revision_id,
            expected_draft_version=request.expected_draft_version,
            expected_fact_plan_hash=request.expected_fact_plan_hash,
        )
    except Exception as error:
        session.rollback()
        _raise_domain(error)
        raise


@router.get("/documents/{document_id}/revisions/{revision_id}/restore-preview")
def revisions_restore_preview(
    document_id: UUID,
    revision_id: UUID,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return preview_restore_revision(session, document_id, revision_id)
    except Exception as error:
        _raise_domain(error)
        raise


@router.get("/documents/{document_id}/chapter-brief")
def chapter_brief_get(
    document_id: UUID, session: Session = Depends(get_session)
) -> dict[str, object]:
    try:
        return get_chapter_brief(session, document_id)
    except Exception as error:
        _raise_domain(error)
        raise


@router.put("/documents/{document_id}/chapter-brief")
def chapter_brief_save(
    document_id: UUID,
    request: SaveChapterBriefRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return save_chapter_brief(
            session,
            document_id,
            expected_version=request.expected_version,
            target_word_count=request.target_word_count,
            expectation_text=request.expectation_text,
            outline_text=request.outline_text,
            forbidden_text=request.forbidden_text,
            role_constraints=request.role_constraints,
        )
    except Exception as error:
        session.rollback()
        _raise_domain(error)
        raise


@router.get("/documents/{document_id}/generation-jobs")
def generation_jobs_index(
    document_id: UUID, session: Session = Depends(get_session)
) -> list[dict[str, object]]:
    try:
        return list_chapter_generation_jobs(session, document_id)
    except Exception as error:
        _raise_domain(error)
        raise


@router.post(
    "/documents/{document_id}/generation-jobs/body",
    status_code=status.HTTP_201_CREATED,
)
async def generation_jobs_create_body(
    document_id: UUID,
    request: GenerateChapterRequest,
    ctx=Depends(get_novel_generation_ctx),
    configured_model: ModelAudit = Depends(get_novel_effective_model),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    job: dict[str, Any] | None = None
    actual_model: ModelAudit | None = None
    try:
        job = start_chapter_generation(
            session,
            document_id,
            expected_brief_version=request.expected_brief_version,
            execution_agent_id=NOVEL_AGENT_ID,
            requested_provider_id=configured_model.provider_id,
            requested_model_id=configured_model.model_id,
            generation_contract_version=GENERATION_CONTRACT_VERSION,
            force_new=request.force_new,
            asset_ids=request.asset_ids,
            preset_id=request.preset_id,
        )
        if job["state"] == "ready" and job.get("candidate"):
            return job
        if not job.get("should_execute", True):
            return job
        prompt = build_chapter_generation_prompt(job["generation_context_snapshot"])
        ensure_prompt_within_effective_limit(prompt, configured_model)
        generation_session_id = f"novel-generation:{job['id']}"
        reply = await ctx.chat(
            prompt,
            skill="prose-writing",
            session_id=generation_session_id,
        )
        actual_model = reply_model_audit(
            reply,
            session_id=generation_session_id,
        )
        actual_model.ensure_matches(configured_model)
        return complete_chapter_generation(
            session,
            UUID(str(job["id"])),
            content_markdown=reply.text,
            actual_provider_id=actual_model.provider_id,
            actual_model_id=actual_model.model_id,
        )
    except Exception as error:
        session.rollback()
        if job is not None:
            try:
                failed = fail_chapter_generation(
                    session,
                    UUID(str(job["id"])),
                    str(error),
                    actual_provider_id=(
                        actual_model.provider_id if actual_model else None
                    ),
                    actual_model_id=(actual_model.model_id if actual_model else None),
                )
            except Exception:
                session.rollback()
                failed = job
            if not isinstance(
                error,
                (
                    BriefConflictError,
                    CandidateConflictError,
                    DraftConflictError,
                    NotFoundError,
                    ValidationError,
                ),
            ):
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail={"type": "generation_failed", "job": failed},
                ) from error
        _raise_domain(error)
        raise


@router.get("/candidates/{candidate_id}")
def candidates_get(
    candidate_id: UUID, session: Session = Depends(get_session)
) -> dict[str, object]:
    try:
        return get_candidate(session, candidate_id)
    except Exception as error:
        _raise_domain(error)
        raise


@router.post("/candidates/{candidate_id}/adopt", status_code=status.HTTP_201_CREATED)
def candidates_adopt(
    candidate_id: UUID,
    request: AdoptCandidateRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return adopt_candidate(
            session,
            candidate_id,
            expected_draft_version=request.expected_draft_version,
        )
    except Exception as error:
        session.rollback()
        _raise_domain(error)
        raise


@router.post("/candidates/{candidate_id}/reject")
def candidates_reject(
    candidate_id: UUID, session: Session = Depends(get_session)
) -> dict[str, object]:
    try:
        return reject_candidate(session, candidate_id)
    except Exception as error:
        session.rollback()
        _raise_domain(error)
        raise


@router.get("/documents/{document_id}/intelligence-proposals")
def intelligence_proposals_index(
    document_id: UUID, session: Session = Depends(get_session)
) -> list[dict[str, object]]:
    try:
        return list_intelligence_proposals(session, document_id)
    except Exception as error:
        _raise_domain(error)
        raise


@router.post(
    "/documents/{document_id}/intelligence-proposals",
    status_code=status.HTTP_201_CREATED,
)
async def intelligence_proposals_create(
    document_id: UUID,
    request: ExtractIntelligenceRequest,
    ctx=Depends(get_novel_generation_ctx),
    configured_model: ModelAudit = Depends(get_novel_effective_model),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    proposal: dict[str, Any] | None = None
    actual_model: ModelAudit | None = None
    try:
        proposal = start_intelligence_proposal(
            session,
            document_id,
            revision_id=request.revision_id,
            execution_agent_id=NOVEL_AGENT_ID,
            requested_provider_id=configured_model.provider_id,
            requested_model_id=configured_model.model_id,
            generation_contract_version=GENERATION_CONTRACT_VERSION,
        )
        if not proposal.get("should_execute", True):
            return proposal
        prompt = build_intelligence_prompt(session, UUID(str(proposal["id"])))
        ensure_prompt_within_effective_limit(prompt, configured_model)
        intelligence_session_id = f"novel-intelligence:{proposal['id']}"
        reply = await ctx.chat(
            prompt,
            skill="story-foundation",
            session_id=intelligence_session_id,
        )
        actual_model = reply_model_audit(
            reply,
            session_id=intelligence_session_id,
        )
        actual_model.ensure_matches(configured_model)
        try:
            payload = parse_model_json(reply.text)
        except ModelVerificationError:
            payload = {}
        raw_items = normalize_intelligence_generation_json(payload, reply.text)
        return complete_intelligence_proposal(
            session,
            UUID(str(proposal["id"])),
            items=raw_items,
            actual_provider_id=actual_model.provider_id,
            actual_model_id=actual_model.model_id,
        )
    except Exception as error:
        session.rollback()
        if proposal is not None and not isinstance(error, ProposalSupersededError):
            try:
                failed = fail_intelligence_proposal(
                    session,
                    UUID(str(proposal["id"])),
                    str(error),
                    actual_provider_id=(
                        actual_model.provider_id if actual_model else None
                    ),
                    actual_model_id=(actual_model.model_id if actual_model else None),
                )
            except Exception:
                session.rollback()
                failed = proposal
            if not isinstance(
                error,
                (NotFoundError, ProposalSupersededError, ValidationError),
            ):
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail={"type": "intelligence_failed", "proposal": failed},
                ) from error
        _raise_domain(error)
        raise


@router.patch("/intelligence-items/{item_id}")
def intelligence_items_review(
    item_id: UUID,
    request: ReviewIntelligenceItemRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return review_intelligence_item(
            session, item_id, review_state=request.review_state
        )
    except Exception as error:
        session.rollback()
        _raise_domain(error)
        raise


@router.post("/intelligence-proposals/{proposal_id}/commit")
def intelligence_proposals_commit(
    proposal_id: UUID,
    request: CommitIntelligenceRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        result = commit_intelligence_items(
            session,
            proposal_id,
            accepted_item_ids=request.accepted_item_ids,
            item_overrides=request.item_overrides,
        )
        relationship_sync = sync_relationships_from_intelligence_proposal(
            session,
            proposal_id,
        )
        result["relationship_sync"] = relationship_sync["changes"]
        return result
    except Exception as error:
        session.rollback()
        _raise_domain(error)
        raise


@router.get("/novels/{novel_id}/story-facts")
def story_facts_index(
    novel_id: UUID, session: Session = Depends(get_session)
) -> list[dict[str, object]]:
    try:
        return list_story_facts(session, novel_id)
    except Exception as error:
        _raise_domain(error)
        raise


@router.get("/novels/{novel_id}/search")
def novels_search(
    novel_id: UUID,
    q: str,
    limit: int = 20,
    session: Session = Depends(get_session),
) -> list[dict[str, object]]:
    try:
        return search_novel(session, novel_id, q, limit=limit)
    except Exception as error:
        _raise_domain(error)
        raise


@router.get("/novels/{novel_id}/context")
def novels_context(
    novel_id: UUID,
    document_id: UUID | None = None,
    max_chars: int = 12_000,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return get_novel_context(
            session, novel_id, document_id=document_id, max_chars=max_chars
        )
    except Exception as error:
        _raise_domain(error)
        raise


pawapp.include_router(router)
