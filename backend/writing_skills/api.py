"""Read-only discovery and recovery. These routes never dispatch generation."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import Field
from sqlalchemy.orm import Session

from ..database import get_session
from .contracts import FrozenModel, ActionIdentity
from .persistence import Claim, PendingAction, read_action
from .evidence import MethodDetails, method_details

router = APIRouter()


class MethodStatus(FrozenModel):
    schema_version: str = "writing-method-status/1"
    action_id: str
    dispatch_id: str
    state: str
    selected_ids: tuple[str, ...] = ()
    omitted_ids: tuple[str, ...] = ()
    method_input_hash: str | None = None
    semantic_enabled: bool = False
    auxiliary_calls: int = Field(default=0, ge=0)
    job_ref: str | None = None
    details: MethodDetails | None = None


def method_status(claim: Claim | PendingAction) -> MethodStatus:
    """Only use after lookup_action has performed current scope authorization."""
    packet = claim.packet
    semantic = packet.semantic_evidence if packet else None
    return MethodStatus(
        action_id=str(claim.identity.action_id), dispatch_id=str(claim.id), state=claim.state,
        selected_ids=tuple(s.skill_id for s in packet.plan.selected) if packet else (),
        omitted_ids=packet.omitted_ids if packet else (),
        method_input_hash=packet.method_input_hash if packet else None,
        semantic_enabled=semantic is not None,
        auxiliary_calls=semantic.auxiliary_calls if semantic is not None else 0,
        job_ref=claim.job_ref,
        details=method_details(packet) if packet else None,
    )


@router.get("/documents/{document_id}/generation-jobs/{job_id}/writing-method")
def chapter_method_history(document_id: UUID, job_id: UUID,
                           tab_id: str = Query(min_length=1, max_length=160),
                           session: Session = Depends(get_session)):
    """Explicit job-history read, never a live action recovery or a generation.

    The current chapter is authorized first. The immutable job reference binds
    the historical method, even when its original browser tab no longer exists.
    No source projection, text, current catalog or current model is returned.
    """
    from sqlalchemy import select
    from ..models import ChapterGenerationJob
    from .models import WritingSkillDispatch
    from .contracts import SkillInjectionPacketV1
    from .button import _scope
    scope = _scope(session, document_id, tab_id)
    job = session.scalar(select(ChapterGenerationJob).where(
        ChapterGenerationJob.id == job_id, ChapterGenerationJob.document_id == document_id))
    if job is None:
        raise HTTPException(404, "chapter job not found in current scope")
    result = {"schema_version": "chapter-method-history/1", "job_id": str(job_id),
              "document_id": str(document_id), "record_status": "legacy_unrecorded",
              "phase": None, "method_input_hash": None, "details": None}
    snapshot = job.generation_context_snapshot
    if isinstance(snapshot, dict) and "skill_invocation" not in snapshot:
        return result
    result["record_status"] = "evidence_unavailable"
    if not isinstance(snapshot, dict):
        return result
    invocation = snapshot["skill_invocation"]
    if not isinstance(invocation, dict) or invocation.get("schema_version") != "job-skill-invocation/1":
        return result
    try:
        dispatch_id = UUID(invocation["dispatch_id"])
    except (KeyError, TypeError, ValueError, AttributeError):
        return result
    row = session.execute(select(WritingSkillDispatch.method_packet, WritingSkillDispatch.state).where(
        WritingSkillDispatch.id == dispatch_id, WritingSkillDispatch.owner_id == scope.owner_id,
        WritingSkillDispatch.workspace_id == scope.workspace_id, WritingSkillDispatch.entry == "button",
        WritingSkillDispatch.agent_id == "ai-novel-writer", WritingSkillDispatch.scope_kind == "novel",
        WritingSkillDispatch.scope_id == scope.scope_id, WritingSkillDispatch.novel_id == scope.scope_id,
        WritingSkillDispatch.job_ref == f"chapter:{job_id}",
        WritingSkillDispatch.route_snapshot["projection"]["scope"]["document_id"].astext == str(document_id),
    )).first()
    if row is None or row.method_packet is None:
        return result
    try:
        packet = SkillInjectionPacketV1.model_validate(row.method_packet)
    except ValueError:
        return result
    if packet.method_input_hash != invocation.get("method_input_hash"):
        return result
    return {**result, "record_status": "recorded", "phase": row.state,
            "method_input_hash": packet.method_input_hash, "details": method_details(packet)}


def _read_chapter_action(session, document_id, action_id, tab_id):
    from .button import _scope, _authorize
    scope = _scope(session, document_id, tab_id)
    identity = ActionIdentity(owner_id=scope.owner_id, workspace_id=scope.workspace_id,
                              entry="button", action_id=action_id)
    claim = read_action(session, identity, scope, authorize=_authorize)
    if claim is None:
        raise HTTPException(404, "writing action not found in current scope")
    return claim


def _creation_scope(session, draft_id, tab_id):
    from ..models import NovelCreationDraft
    from .contracts import (
        FIXED_LOCAL_OWNER_ID,
        FIXED_LOCAL_WORKSPACE_ID,
        Scope,
    )
    if session.get(NovelCreationDraft, draft_id) is None:
        raise HTTPException(404, "creation draft not found")
    return Scope(
        owner_id=FIXED_LOCAL_OWNER_ID,
        workspace_id=FIXED_LOCAL_WORKSPACE_ID,
        kind="creation_draft",
        scope_id=draft_id,
        tab_id=tab_id,
    )


def _read_creation_action(session, draft_id, action_id, tab_id):
    from .creative import _authorize
    scope = _creation_scope(session, draft_id, tab_id)
    identity = ActionIdentity(
        owner_id=scope.owner_id,
        workspace_id=scope.workspace_id,
        entry="button",
        action_id=action_id,
    )
    claim = read_action(session, identity, scope, authorize=_authorize)
    if claim is None:
        raise HTTPException(404, "writing action not found in current scope")
    return claim


def _novel_scope(session, novel_id, tab_id):
    from ..models import Novel
    from .contracts import Scope
    novel = session.get(Novel, novel_id)
    if novel is None:
        raise HTTPException(404, "novel not found")
    return Scope(
        owner_id=novel.owner_id,
        workspace_id=novel.workspace_id,
        kind="novel",
        scope_id=novel.id,
        tab_id=tab_id,
    )


def _read_novel_action(session, novel_id, action_id, tab_id):
    from .creative import _authorize
    scope = _novel_scope(session, novel_id, tab_id)
    identity = ActionIdentity(
        owner_id=scope.owner_id,
        workspace_id=scope.workspace_id,
        entry="button",
        action_id=action_id,
    )
    claim = read_action(session, identity, scope, authorize=_authorize)
    if claim is None:
        raise HTTPException(404, "writing action not found in current scope")
    return claim


def _read_native_action(
    session: Session,
    novel_id: UUID,
    action_id: UUID,
    tab_id: str,
    document_id: UUID | None,
):
    from ..models import Document, Novel

    scope = _novel_scope(session, novel_id, tab_id).model_copy(
        update={"document_id": document_id}
    )
    identity = ActionIdentity(
        owner_id=scope.owner_id,
        workspace_id=scope.workspace_id,
        entry="native",
        action_id=action_id,
    )
    def authorize(current_session: Session, current_scope) -> None:
        novel = current_session.get(Novel, current_scope.scope_id)
        document = (
            current_session.get(Document, current_scope.document_id)
            if current_scope.document_id is not None
            else None
        )
        if (
            current_scope.kind != "novel"
            or novel is None
            or novel.owner_id != current_scope.owner_id
            or novel.workspace_id != current_scope.workspace_id
            or (
                current_scope.document_id is not None
                and (document is None or document.novel_id != novel.id)
            )
        ):
            raise ValueError("native writing scope changed")

    try:
        claim = read_action(session, identity, scope, authorize=authorize)
    except Exception as error:
        # Do not disclose whether an action exists outside the supplied scope.
        from ..services import ValidationError

        if isinstance(error, (ValidationError, ValueError)):
            raise HTTPException(
                404,
                "native writing action not found in current scope",
            ) from None
        raise
    if claim is None:
        raise HTTPException(404, "native writing action not found in current scope")
    return claim


@router.get("/writing-skill-dispatches/{dispatch_id}", response_model=MethodStatus)
def writing_method_status(dispatch_id: UUID, action_id: UUID, document_id: UUID,
                          tab_id: str = Query(min_length=1, max_length=160),
                          session: Session = Depends(get_session)):
    claim = _read_chapter_action(session, document_id, action_id, tab_id)
    if claim.id != dispatch_id:
        raise HTTPException(404, "writing dispatch not found in current action")
    return method_status(claim)


@router.get("/documents/{document_id}/writing-method-actions/{action_id}")
def writing_action_result(document_id: UUID, action_id: UUID,
                          tab_id: str = Query(min_length=1, max_length=160),
                          session: Session = Depends(get_session)):
    """Recover a lost POST response even if its dispatch ID never reached UI."""
    claim = _read_chapter_action(session, document_id, action_id, tab_id)
    if claim.job_ref is not None and claim.job_ref.startswith("creative:"):
        from .creative import _response as creative_response

        return creative_response(session, claim)
    from .button import _response as chapter_response

    return chapter_response(session, claim)


@router.get("/creation-drafts/{draft_id}/writing-method-actions/{action_id}")
def creation_writing_action_result(
    draft_id: UUID,
    action_id: UUID,
    tab_id: str = Query(min_length=1, max_length=160),
    session: Session = Depends(get_session),
):
    """Recover one lost template/naming response without redispatching."""
    from .creative import _response
    claim = _read_creation_action(session, draft_id, action_id, tab_id)
    return _response(session, claim)


@router.get("/novels/{novel_id}/writing-method-actions/{action_id}")
def novel_writing_action_result(
    novel_id: UUID,
    action_id: UUID,
    tab_id: str = Query(min_length=1, max_length=160),
    session: Session = Depends(get_session),
):
    """Recover one lost novel-scoped creative response without redispatching."""
    from .creative import _response
    claim = _read_novel_action(session, novel_id, action_id, tab_id)
    return _response(session, claim)


@router.get(
    "/novels/{novel_id}/native-writing-actions/{action_id}",
    response_model=MethodStatus,
)
def native_writing_action_result(
    novel_id: UUID,
    action_id: UUID,
    tab_id: str = Query(min_length=1, max_length=160),
    document_id: UUID | None = None,
    session: Session = Depends(get_session),
):
    """Read one server-ticketed native action; never route or dispatch."""

    return method_status(
        _read_native_action(
            session,
            novel_id,
            action_id,
            tab_id,
            document_id,
        )
    )


@router.get("/writing-skills")
async def writing_skill_catalog(request: Request, document_id: UUID | None = None,
                                creation_draft_id: UUID | None = None,
                                novel_id: UUID | None = None,
                                creative_kind: str | None = None,
                                selection_operation: str | None = Query(
                                    default=None,
                                    pattern="^(polish|rewrite|expand|shorten|dialogue|review|custom)$",
                                ),
                                tab_id: str | None = Query(default=None, min_length=1, max_length=160),
                                session: Session = Depends(get_session)):
    from .button import current_catalog, CHAPTER_CAPABILITIES
    from .button import _scope
    from .creative import (
        CREATION_HELPER_CAPABILITIES,
        DOCUMENT_CREATIVE_KINDS,
        NOVEL_CREATIVE_KINDS,
        NOVEL_CREATIVE_CAPABILITIES,
        SELECTION_EDIT_KINDS,
    )
    from .load_policy import MethodPolicyViolation
    from .primary import creative_primary_skill
    target_count = (
        int(document_id is not None)
        + int(creation_draft_id is not None)
        + int(novel_id is not None)
    )
    if target_count > 1 or (target_count == 0) != (tab_id is None):
        raise HTTPException(
            422,
            "supply exactly one scope identifier together with tab_id",
        )
    if (creative_kind == "selection_edit") != (selection_operation is not None):
        raise HTTPException(
            422,
            "selection_operation is required only for selection_edit",
        )
    if document_id is not None:
        scope = _scope(session, document_id, tab_id)
        if creative_kind is None:
            primary_skill = "prose-writing"
        elif creative_kind in DOCUMENT_CREATIVE_KINDS:
            primary_skill = creative_primary_skill(creative_kind)
        elif creative_kind in SELECTION_EDIT_KINDS:
            primary_skill = creative_primary_skill(
                creative_kind,
                operation=selection_operation or "",
            )
        else:
            raise HTTPException(422, "document creative kind is not catalog-enabled")
    elif creation_draft_id is not None:
        scope = _creation_scope(session, creation_draft_id, tab_id)
        primary_skill = "novel-direction"
    elif novel_id is not None:
        if creative_kind not in NOVEL_CREATIVE_KINDS:
            raise HTTPException(422, "novel creative kind is not catalog-enabled")
        scope = _novel_scope(session, novel_id, tab_id)
        primary_skill = creative_primary_skill(creative_kind)
    else:
        if creative_kind is not None:
            raise HTTPException(422, "creative_kind requires novel_id")
        scope = None
        primary_skill = "prose-writing"
    session.rollback()
    try:
        catalog, _ = await current_catalog(request.app, primary_skill=primary_skill)
    except Exception:
        # Scope remains authoritative even when catalog files/enablement are
        # unavailable. Old actions must remain queryable; new work stays shut.
        catalog = None
    try:
        CHAPTER_CAPABILITIES.require("button")
        chapter_available = (
            catalog is not None
            and document_id is not None
            and creative_kind is None
        )
    except MethodPolicyViolation:
        chapter_available = False
    try:
        CREATION_HELPER_CAPABILITIES.require("button")
        creation_available = catalog is not None and creation_draft_id is not None
    except MethodPolicyViolation:
        creation_available = False
    try:
        NOVEL_CREATIVE_CAPABILITIES.require("button")
        novel_creative_available = catalog is not None and novel_id is not None
    except MethodPolicyViolation:
        novel_creative_available = False
    try:
        NOVEL_CREATIVE_CAPABILITIES.require("button")
        document_creative_available = (
            catalog is not None
            and document_id is not None
            and creative_kind in (DOCUMENT_CREATIVE_KINDS | SELECTION_EDIT_KINDS)
        )
    except MethodPolicyViolation:
        document_creative_available = False
    return {
        "schema_version": "writing-skill-catalog/1", "catalog_version": catalog.version if catalog else None,
        "agent_id": "ai-novel-writer", "chapter_body_available": chapter_available,
        "creation_helper_available": creation_available,
        "novel_creative_available": novel_creative_available,
        "document_creative_available": document_creative_available,
        "catalog_available": catalog is not None,
        "semantic_available": False,
        "scope": scope.model_dump(mode="json") if scope is not None else None,
        "capabilities": [{"skill_id": item.declaration.skill_id,
                          "display_name": item.declaration.display_name,
                          "version": item.declaration.capability_version}
                         for item in catalog.capabilities] if catalog else [],
    }
