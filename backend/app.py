"""AI小说世界2026 PawApp HTTP API."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from qwenpaw.pawapp import PawApp, get_ctx
from sqlalchemy.orm import Session

from .contracts import APP_ID, APP_VERSION
from .creative_api import router as creative_router
from .database import database_status, get_session
from .model_runtime import (
    ModelVerificationError,
    configured_model_audit,
    normalize_intelligence_generation_json,
    parse_model_json,
    reply_model_audit,
)
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
router.include_router(creative_router)


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
        "required_generation_model": "MiniMax-M3",
        "model_verification_mode": "agent-config+provider-usage",
        "vector_retrieval_enabled": False,
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
    ctx=Depends(get_ctx),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    job: dict[str, Any] | None = None
    try:
        job = start_chapter_generation(
            session,
            document_id,
            expected_brief_version=request.expected_brief_version,
            force_new=request.force_new,
            asset_ids=request.asset_ids,
            preset_id=request.preset_id,
            requested_model_id=request.requested_model_id,
        )
        if job["state"] == "ready" and job.get("candidate"):
            return job
        configured_model = configured_model_audit(ctx.agent_id)
        prompt = build_chapter_generation_prompt(job["generation_context_snapshot"])
        generation_session_id = f"novel-generation:{job['id']}"
        reply = await ctx.chat(
            prompt,
            skill="prose-writing",
            session_id=generation_session_id,
        )
        actual_model = reply_model_audit(
            reply,
            session_id=generation_session_id,
        ).ensure_matches(configured_model)
        return complete_chapter_generation(
            session,
            UUID(str(job["id"])),
            content_markdown=reply.text,
            model_profile_fingerprint=actual_model.fingerprint,
            actual_model_id=actual_model.model_id,
            provider_profile=actual_model.provider_id,
        )
    except Exception as error:
        session.rollback()
        if job is not None:
            try:
                failed = fail_chapter_generation(session, UUID(str(job["id"])), str(error))
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
    ctx=Depends(get_ctx),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    proposal: dict[str, Any] | None = None
    try:
        proposal = start_intelligence_proposal(
            session, document_id, revision_id=request.revision_id
        )
        if proposal["state"] in {"ready", "partially_accepted", "accepted", "rejected"}:
            return proposal
        prompt = build_intelligence_prompt(session, UUID(str(proposal["id"])))
        configured_model = configured_model_audit(ctx.agent_id)
        intelligence_session_id = f"novel-intelligence:{proposal['id']}"
        reply = await ctx.chat(
            prompt,
            skill="story-bible",
            session_id=intelligence_session_id,
        )
        actual_model = reply_model_audit(
            reply,
            session_id=intelligence_session_id,
        ).ensure_matches(configured_model)
        try:
            payload = parse_model_json(reply.text)
        except ModelVerificationError:
            payload = {}
        raw_items = normalize_intelligence_generation_json(payload, reply.text)
        return complete_intelligence_proposal(
            session,
            UUID(str(proposal["id"])),
            items=raw_items,
            model_profile_fingerprint=actual_model.fingerprint,
            actual_model_id=actual_model.model_id,
            provider_profile=actual_model.provider_id,
        )
    except Exception as error:
        session.rollback()
        if proposal is not None and not isinstance(error, ProposalSupersededError):
            try:
                failed = fail_intelligence_proposal(
                    session, UUID(str(proposal["id"])), str(error)
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
        return commit_intelligence_items(
            session,
            proposal_id,
            accepted_item_ids=request.accepted_item_ids,
            item_overrides=request.item_overrides,
        )
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
