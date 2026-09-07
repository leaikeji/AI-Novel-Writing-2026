"""Managed writing methods for creative helper buttons.

Template, naming, the four full-outline tasks, storyline recommendation,
chapter-outline, review, chapter-body selection editing and character-profile
completion use the same pinned public middleware after separate product checks.
Excluded media/fact-extraction tasks and non-body entity selections keep their
existing paths.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..creative_schemas import StartCreativeGenerationRequest
from ..character_profile_services import normalize_character_profile_output
from ..creative_services import (
    _validate_creative_generation_scope,
    _creative_job_payload,
    build_creative_generation_prompt,
    complete_creative_generation,
    fail_creative_generation,
    outline_candidate_review,
    prepare_creative_generation,
    start_creative_generation,
)
from ..embedding.chunking import estimate_token_count
from ..generation_dependencies import (
    NovelModelEvidenceRejected,
    failed_novel_model_evidence,
    verify_novel_model_reply,
)
from ..model_runtime import (
    GENERATION_CONTRACT_VERSION,
    ModelAudit,
    ModelVerificationError,
    ensure_prompt_within_effective_limit,
    normalize_creative_generation_json,
    parse_model_json,
    reply_final_text,
)
from ..selection_edit_diff import build_selection_edit_result
from ..models import (
    ChapterBrief,
    ChapterCreationDraft,
    Document,
    DocumentWorkingCopy,
    Novel,
    NovelCreationDraft,
    OutlineDraft,
)
from ..services import ValidationError
from .api import method_status
from .button import current_catalog
from .composer import compose_writing_request
from .contracts import (
    ActionIdentity,
    FIXED_LOCAL_OWNER_ID,
    FIXED_LOCAL_WORKSPACE_ID,
    FrozenRouteRequest,
    Scope,
    canonical_hash,
)
from .load_policy import (
    ManagedMethodPolicy,
    MethodPolicyViolation,
    PublicLoadCapabilities,
    managed_method_request,
    public_entry_released,
)
from .persistence import (
    ActionConflict,
    Claim,
    StaleFence,
    advance,
    claim_pending_action,
    freeze_prepared_action,
    lookup_action,
)
from .primary import creative_primary_skill
from .projection import creative_projection
from .resolver import resolve_methods
from .semantic_runtime import SemanticCallFactory
from .semantic_orchestration import complete_button_route, SemanticRouteIncomplete


# Server-owned release decision. The fake transport can inject an explicit
# capability object; product code cannot enable this with a request flag.
# Template/naming use the same pinned QwenPaw 2.1.x public request middleware
# proven for the chapter button. This value remains button-only; actual product
# release still requires this entry's own one-call, recovery and UI evidence.
CREATION_HELPER_CAPABILITIES = PublicLoadCapabilities(
    current_request_injection=True,
    pre_io_tool_control=True,
    no_unobserved_load_path=True,
)
NOVEL_CREATIVE_CAPABILITIES = PublicLoadCapabilities(
    current_request_injection=True,
    pre_io_tool_control=True,
    no_unobserved_load_path=True,
)
CREATION_KINDS = frozenset({"novel_template", "novel_naming"})
OUTLINE_KINDS = frozenset({
    "outline_background",
    "outline_characters",
    "outline_plot",
    "outline_highlight",
})
CHAPTER_CREATION_KINDS = frozenset({
    "chapter_storyline_recommendation",
    "chapter_outline",
})
DOCUMENT_CREATIVE_KINDS = frozenset({"review"})
SELECTION_EDIT_KINDS = frozenset({"selection_edit"})
CHARACTER_PROFILE_KINDS = frozenset({"character_profile_completion"})
NOVEL_CREATIVE_KINDS = (
    OUTLINE_KINDS | CHAPTER_CREATION_KINDS | CHARACTER_PROFILE_KINDS
)
SUPPORTED_KINDS = (
    CREATION_KINDS
    | NOVEL_CREATIVE_KINDS
    | DOCUMENT_CREATIVE_KINDS
    | SELECTION_EDIT_KINDS
)


def creative_button_capabilities(
    kind: str,
) -> PublicLoadCapabilities | None:
    """Resolve only server-owned capability gates for an existing task kind."""

    if kind in CREATION_KINDS:
        return CREATION_HELPER_CAPABILITIES
    if kind in (NOVEL_CREATIVE_KINDS | DOCUMENT_CREATIVE_KINDS | SELECTION_EDIT_KINDS):
        return NOVEL_CREATIVE_CAPABILITIES
    return None


def creative_button_released(
    kind: str,
    input_snapshot: Mapping[str, object] | None = None,
) -> bool:
    if kind in SELECTION_EDIT_KINDS:
        target = input_snapshot.get("target") if input_snapshot is not None else None
        if not isinstance(target, Mapping) or target.get("field_id") != "chapter.body":
            return False
    capabilities = creative_button_capabilities(kind)
    return capabilities is not None and public_entry_released(capabilities)

CreativeContextLoader = Callable[
    [ModelAudit],
    Awaitable[tuple[dict[str, object] | None, dict[str, object] | None]],
]


def _utf16_slice(value: str, start: int, end: int) -> str:
    """Mirror JavaScript String.slice offsets without weakening Unicode checks."""

    encoded = value.encode("utf-16-le")
    try:
        return encoded[start * 2 : end * 2].decode("utf-16-le")
    except UnicodeDecodeError as error:
        raise ValidationError("managed selection UTF-16 boundary is invalid") from error


def _validate_managed_selection(
    session: Session,
    request: StartCreativeGenerationRequest,
) -> tuple[Novel, Document, DocumentWorkingCopy]:
    novel = session.get(Novel, request.novel_id)
    document = session.get(Document, request.document_id)
    working_copy = session.get(DocumentWorkingCopy, request.document_id)
    snapshot = request.input_snapshot
    target = snapshot.get("target")
    base = snapshot.get("base")
    if (
        novel is None
        or document is None
        or working_copy is None
        or document.novel_id != novel.id
        or request.scope_id != document.id
        or not isinstance(target, dict)
        or not isinstance(base, dict)
        or target.get("field_id") != "chapter.body"
        or target.get("entity_id") != str(document.id)
        or target.get("document_id") != str(document.id)
        or request.expected_scope_version is None
        or working_copy.draft_version != request.expected_scope_version
        or base.get("persistence_version") != working_copy.draft_version
        or base.get("field_value_sha256") != working_copy.content_hash
    ):
        raise ValidationError("managed selection document scope is invalid")
    start = base.get("start_utf16")
    end = base.get("end_utf16")
    if type(start) is not int or type(end) is not int:
        raise ValidationError("managed selection range is invalid")
    content = working_copy.content_markdown
    if (
        _utf16_slice(content, start, end) != base.get("selection_text")
        or _utf16_slice(content, max(0, start - 1500), start) != base.get("before")
        or _utf16_slice(content, end, end + 1500) != base.get("after")
    ):
        raise ValidationError("managed selection text changed")
    return novel, document, working_copy


def _scope(session: Session, request: StartCreativeGenerationRequest) -> Scope:
    if request.kind not in SUPPORTED_KINDS:
        raise HTTPException(
            503,
            {
                "type": "writing_method_unavailable",
                "message": "this creative button is not released",
            },
        )
    _validate_creative_generation_scope(
        session,
        scope_type=request.scope_type,
        scope_id=request.scope_id,
        kind=request.kind,
        novel_id=request.novel_id,
        document_id=request.document_id,
    )
    if request.kind in CREATION_KINDS:
        draft = session.get(NovelCreationDraft, request.scope_id)
        if (
            draft is None
            or request.novel_id is not None
            or request.document_id is not None
            or request.expected_scope_version is None
            or draft.version != request.expected_scope_version
        ):
            raise ValidationError("managed creation helper scope is invalid")
        return Scope(
            owner_id=FIXED_LOCAL_OWNER_ID,
            workspace_id=FIXED_LOCAL_WORKSPACE_ID,
            kind="creation_draft",
            scope_id=draft.id,
            tab_id=request.writing_action.tab_id,
        )
    novel = session.get(Novel, request.novel_id)
    if request.kind in CHARACTER_PROFILE_KINDS:
        if (
            novel is None
            or request.scope_type != "novel"
            or request.scope_id != novel.id
            or request.document_id is not None
            or request.expected_scope_version is not None
            or set(request.input_snapshot) != {"expected_source_hash"}
        ):
            raise ValidationError("managed character profile scope is invalid")
        return Scope(
            owner_id=novel.owner_id,
            workspace_id=novel.workspace_id,
            kind="novel",
            scope_id=novel.id,
            tab_id=request.writing_action.tab_id,
        )
    if request.kind in SELECTION_EDIT_KINDS:
        novel, document, _ = _validate_managed_selection(session, request)
        return Scope(
            owner_id=novel.owner_id,
            workspace_id=novel.workspace_id,
            kind="novel",
            scope_id=novel.id,
            document_id=document.id,
            tab_id=request.writing_action.tab_id,
        )
    if request.kind in DOCUMENT_CREATIVE_KINDS:
        document = session.get(Document, request.document_id)
        working_copy = session.get(DocumentWorkingCopy, request.document_id)
        brief = session.query(ChapterBrief).filter_by(
            document_id=request.document_id
        ).one_or_none()
        snapshot = request.input_snapshot
        if (
            document is None
            or working_copy is None
            or novel is None
            or document.novel_id != novel.id
            or request.scope_id != document.id
            or request.expected_scope_version is None
            or working_copy.draft_version != request.expected_scope_version
            or snapshot.get("draft_version") != working_copy.draft_version
            or snapshot.get("content_hash") != working_copy.content_hash
            or snapshot.get("content_markdown") != working_copy.content_markdown
            or snapshot.get("visible_character_count")
            != working_copy.visible_character_count
            or snapshot.get("novel_title") != novel.title
            or snapshot.get("genre") != novel.genre
            or snapshot.get("subgenre") != novel.subgenre
            or snapshot.get("outline_text") != (brief.outline_text if brief else "")
            or snapshot.get("expectation_text")
            != (brief.expectation_text if brief else "")
        ):
            raise ValidationError("managed review scope is invalid")
        return Scope(
            owner_id=novel.owner_id,
            workspace_id=novel.workspace_id,
            kind="novel",
            scope_id=novel.id,
            document_id=document.id,
            tab_id=request.writing_action.tab_id,
        )
    if request.kind in CHAPTER_CREATION_KINDS:
        draft = session.get(ChapterCreationDraft, request.scope_id)
        if (
            draft is None
            or novel is None
            or draft.novel_id != novel.id
            or draft.state != "draft"
            or request.document_id is not None
            or request.expected_scope_version is None
            or draft.version != request.expected_scope_version
        ):
            raise ValidationError("managed chapter helper scope is invalid")
        return Scope(
            owner_id=novel.owner_id,
            workspace_id=novel.workspace_id,
            kind="novel",
            scope_id=novel.id,
            tab_id=request.writing_action.tab_id,
        )
    draft = session.get(OutlineDraft, request.scope_id)
    if (
        draft is None
        or novel is None
        or draft.novel_id != novel.id
        or request.document_id is not None
        or request.expected_scope_version is None
        or draft.version != request.expected_scope_version
    ):
        raise ValidationError("managed outline helper scope is invalid")
    return Scope(
        owner_id=novel.owner_id,
        workspace_id=novel.workspace_id,
        kind="novel",
        scope_id=novel.id,
        tab_id=request.writing_action.tab_id,
    )


def _authorize(session: Session, scope: Scope) -> None:
    if scope.kind == "creation_draft":
        if (
            scope.document_id is not None
            or scope.owner_id != FIXED_LOCAL_OWNER_ID
            or scope.workspace_id != FIXED_LOCAL_WORKSPACE_ID
            or session.get(NovelCreationDraft, scope.scope_id) is None
        ):
            raise ValidationError("managed creation helper scope changed")
        return
    novel = session.get(Novel, scope.scope_id)
    document = (
        session.get(Document, scope.document_id)
        if scope.document_id is not None
        else None
    )
    if (
        scope.kind != "novel"
        or novel is None
        or novel.owner_id != scope.owner_id
        or novel.workspace_id != scope.workspace_id
        or (
            scope.document_id is not None
            and (document is None or document.novel_id != novel.id)
        )
    ):
        raise ValidationError("managed novel helper scope changed")


def _response(session: Session, claim: Claim, *, job=None) -> dict[str, object]:
    _authorize(session, claim.scope)
    if job is None and claim.job_ref is not None:
        kind, _, value = claim.job_ref.partition(":")
        try:
            job_id = UUID(value)
        except (TypeError, ValueError, AttributeError):
            raise ActionConflict("invalid creative method job reference") from None
        if kind != "creative":
            raise ActionConflict("unexpected creative method job kind")
        from ..models import CreativeGenerationJob

        row = session.get(CreativeGenerationJob, job_id)
        if row is None or (
            claim.scope.kind == "creation_draft"
            and row.scope_id != claim.scope.scope_id
        ) or (
            claim.scope.kind == "novel"
            and (
                row.novel_id != claim.scope.scope_id
                or row.document_id != claim.scope.document_id
            )
        ):
            raise ActionConflict("creative method job scope mismatch")
        job = _creative_job_payload(row)
    result = dict(job) if job is not None else {"state": "method_pending"}
    result.pop("input_snapshot", None)
    result.pop("should_execute", None)
    result["writing_method"] = method_status(claim).model_dump(mode="json")
    return result


async def generate_managed_creation_helper(
    *,
    request: StartCreativeGenerationRequest,
    ctx,
    model_probe,
    session: Session,
    asgi_app,
    capabilities: PublicLoadCapabilities | None = None,
    context_loader: CreativeContextLoader | None = None,
    semantic_call_factory: SemanticCallFactory | None = None,
) -> dict[str, object]:
    """Claim first, then freeze one method packet and make one model call."""

    capabilities = capabilities or creative_button_capabilities(request.kind)
    if capabilities is None:
        raise HTTPException(
            503,
            {
                "type": "writing_method_unavailable",
                "message": "this creative button is not released",
            },
        )
    action = request.writing_action
    try:
        scope = _scope(session, request)
    except ValidationError as error:
        raise HTTPException(
            409,
            {
                "type": "managed_creation_scope_invalid",
                "message": str(error),
            },
        ) from error
    identity = ActionIdentity(
        owner_id=scope.owner_id,
        workspace_id=scope.workspace_id,
        entry="button",
        action_id=action.action_id,
    )
    client_hash = canonical_hash(
        request.model_dump(mode="json", exclude={"writing_action": {"action_id"}})
    )
    claim = None
    job = None
    configured = None
    evidence = None
    started = None
    transport_started = False
    reply_received = False
    owns_action = False
    try:
        prepared_source_hash: str | None = None

        def authorize(current_session: Session, current_scope: Scope) -> None:
            _authorize(current_session, current_scope)
            if request.kind in CREATION_KINDS:
                current_draft = current_session.get(
                    NovelCreationDraft, current_scope.scope_id
                )
                if (
                    current_draft is None
                    or current_draft.version != request.expected_scope_version
                ):
                    raise ActionConflict("creation draft version changed")
            elif request.kind in OUTLINE_KINDS:
                current_draft = current_session.get(OutlineDraft, request.scope_id)
                if (
                    current_draft is None
                    or current_draft.novel_id != current_scope.scope_id
                    or current_draft.version != request.expected_scope_version
                ):
                    raise ActionConflict("outline draft version changed")
            elif request.kind in CHAPTER_CREATION_KINDS:
                current_draft = current_session.get(
                    ChapterCreationDraft, request.scope_id
                )
                if (
                    current_draft is None
                    or current_draft.novel_id != current_scope.scope_id
                    or current_draft.state != "draft"
                    or current_draft.version != request.expected_scope_version
                ):
                    raise ActionConflict("chapter creation draft version changed")
                if prepared_source_hash is not None:
                    from ..creative_services import build_chapter_creation_generation_snapshot

                    current_snapshot = build_chapter_creation_generation_snapshot(
                        current_session,
                        current_draft,
                        kind=request.kind,
                        request_snapshot=request.input_snapshot,
                    )
                    if canonical_hash(current_snapshot) != prepared_source_hash:
                        raise ActionConflict("chapter creation sources changed")
            elif request.kind in CHARACTER_PROFILE_KINDS:
                from ..creative_services import build_character_profile_completion_snapshot

                expected = request.input_snapshot.get("expected_source_hash")
                if canonical_hash(
                    build_character_profile_completion_snapshot(
                        current_session, current_scope.scope_id
                    )
                ) != expected:
                    raise ActionConflict("character profile sources changed")
            else:
                try:
                    refreshed_scope = _scope(current_session, request)
                except ValidationError as error:
                    raise ActionConflict("creative document version changed") from error
                if refreshed_scope != current_scope:
                    raise ActionConflict("creative document version changed")

        existing = lookup_action(
            session, identity, scope, client_hash, authorize=authorize
        )
        if existing is not None:
            return _response(session, existing)
        session.rollback()
        capabilities.require("button")
        if action.preferences.semantic_mode != "off" and semantic_call_factory is None:
            raise HTTPException(409, "semantic routing is not released")
        claim = claim_pending_action(
            session, identity, scope, client_hash, authorize=authorize
        )
        if not claim.acquired:
            return _response(session, claim)
        owns_action = True
        prepared_snapshot = None
        if request.kind in CHAPTER_CREATION_KINDS:
            prepared_snapshot = prepare_creative_generation(
                session,
                scope_type=request.scope_type,
                scope_id=request.scope_id,
                kind=request.kind,
                input_snapshot=request.input_snapshot,
                novel_id=request.novel_id,
                document_id=request.document_id,
                target_character_count=request.target_character_count,
                trusted_chapter_sources=True,
            )
            prepared_source_hash = canonical_hash(prepared_snapshot)
        configured = await model_probe()
        writing_retrieval = None
        writing_context = None
        if context_loader is not None and request.kind not in CHAPTER_CREATION_KINDS:
            writing_retrieval, writing_context = await context_loader(configured)
        operation = (
            str(request.input_snapshot.get("operation") or "")
            if request.kind == "selection_edit"
            else ""
        )
        primary_skill = creative_primary_skill(request.kind, operation=operation)
        catalog, primary = await current_catalog(
            asgi_app, primary_skill=primary_skill
        )
        if prepared_snapshot is None:
            prepared_snapshot = prepare_creative_generation(
                session,
                scope_type=request.scope_type,
                scope_id=request.scope_id,
                kind=request.kind,
                input_snapshot=request.input_snapshot,
                novel_id=request.novel_id,
                document_id=request.document_id,
                target_character_count=request.target_character_count,
                writing_retrieval=writing_retrieval,
                writing_context=writing_context,
                trusted_chapter_sources=True,
            )
        prompt = build_creative_generation_prompt(
            {"kind": request.kind, "input_snapshot": prepared_snapshot}
        )
        projection = creative_projection(
            scope,
            request.kind,
            prepared_snapshot,
            prompt,
            required_ids=action.preferences.required_ids,
        )
        if request.kind in (
            CREATION_KINDS
            | CHAPTER_CREATION_KINDS
            | DOCUMENT_CREATIVE_KINDS
            | SELECTION_EDIT_KINDS
        ):
            projection = projection.model_copy(
                update={
                    "source_version": canonical_hash(
                        {
                            "model_source": projection.source_version,
                            "scope_version": request.expected_scope_version,
                        }
                    )
                }
            )
        frozen = FrozenRouteRequest(
            identity=identity,
            projection=projection,
            preferences=action.preferences,
            catalog_version=catalog.version,
            provider_id=configured.provider_id,
            model_id=configured.model_id,
        )
        claim = freeze_prepared_action(session, claim, frozen)

        async def verify_current() -> None:
            authorize(session, scope)
            found = lookup_action(
                session, identity, scope, client_hash, authorize=authorize
            )
            if (
                found.id != claim.id
                or found.fence != claim.fence
                or found.state != claim.state
            ):
                raise StaleFence("creative method action changed")
            session.rollback()
            fresh_model = await model_probe()
            configured.ensure_matches(fresh_model)
            fresh_catalog, fresh_primary = await current_catalog(
                asgi_app, primary_skill=primary_skill
            )
            if (
                fresh_catalog.version != catalog.version
                or fresh_primary != primary
                or fresh_model.effective_max_input_length
                != configured.effective_max_input_length
            ):
                raise ActionConflict("creative method configuration changed")

        plan = resolve_methods(
            projection,
            catalog,
            action.preferences,
            primary_skill=primary_skill,
        )
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
        packet = compose_writing_request(
            plan,
            catalog,
            primary_blocks=primary,
            effective_input_budget=configured.effective_max_input_length,
            reserved_task_tokens=estimate_token_count(prompt) + 6144,
            required_ids=action.preferences.required_ids,
            semantic_evidence=semantic_evidence,
        )
        claim = advance(session, claim, "route_ready")
        claim = advance(session, claim, "assembled", packet=packet)

        await verify_current()
        job = start_creative_generation(
            session,
            scope_type=request.scope_type,
            scope_id=request.scope_id,
            kind=request.kind,
            input_snapshot=request.input_snapshot,
            execution_agent_id="ai-novel-writer",
            requested_provider_id=configured.provider_id,
            requested_model_id=configured.model_id,
            generation_contract_version=GENERATION_CONTRACT_VERSION,
            novel_id=request.novel_id,
            document_id=request.document_id,
            target_character_count=request.target_character_count,
            force_new=request.force_new,
            writing_retrieval=writing_retrieval,
            writing_context=writing_context,
            method_dispatch=claim,
            method_scope_version=request.expected_scope_version,
        )
        claim = lookup_action(
            session, identity, scope, client_hash, authorize=authorize
        )
        if not job.get("should_execute", True):
            return _response(session, claim, job=job)
        prompt = build_creative_generation_prompt(job)
        ensure_prompt_within_effective_limit(prompt, configured)
        session.rollback()
        started = time.monotonic()
        with managed_method_request(
            ManagedMethodPolicy(packet),
            session_id=f"novel-creative-generation:{job['id']}",
            capabilities=capabilities,
            entry="button",
            verify_current=verify_current,
            max_model_calls=1,
        ) as binding:
            transport_started = True
            reply = await ctx.chat(
                prompt, skill=None, session_id=binding.session_id
            )
            reply_received = True
            if not binding.factory_claimed or binding.observed_model_calls != 1:
                raise RuntimeError("managed creative transport not observed exactly once")
        evidence = await verify_novel_model_reply(
            reply,
            configured=configured,
            probe=model_probe,
            started_monotonic=started,
        )
        final_text = reply_final_text(reply)
        try:
            parsed_output = parse_model_json(final_text)
        except ModelVerificationError:
            parsed_output = {}
        if request.kind in CHARACTER_PROFILE_KINDS:
            strict_candidate = final_text.strip()
            if not strict_candidate.startswith("{") or not strict_candidate.endswith("}"):
                raise ModelVerificationError(
                    "模型没有返回可解析的 JSON：角色卡补全必须只返回唯一裸 JSON 对象"
                )
            try:
                import json

                strict_output = json.loads(strict_candidate)
            except json.JSONDecodeError as error:
                raise ModelVerificationError("模型没有返回可解析的 JSON 对象") from error
            if not isinstance(strict_output, dict):
                raise ModelVerificationError("角色卡补全模型结果必须是 JSON 对象")
            output_json = normalize_character_profile_output(
                dict(job.get("input_snapshot") or {}), strict_output
            )
        else:
            output_json = normalize_creative_generation_json(
                request.kind, parsed_output, final_text
            )
        output_text = final_text
        if request.kind == "selection_edit":
            snapshot = dict(job.get("input_snapshot") or {})
            base = dict(snapshot.get("base") or {})
            output_json = build_selection_edit_result(
                job_id=str(job["id"]),
                selection_id=str(snapshot.get("selection_id") or ""),
                operation=str(snapshot.get("operation") or ""),
                original_text=str(base.get("selection_text") or ""),
                replacement_text=str(output_json["replacement_text"]),
                short_summary=str(output_json["short_summary"]),
            )
            output_text = str(output_json["replacement_text"])
        if request.kind in OUTLINE_KINDS:
            output_json["candidate_review"] = outline_candidate_review(
                request.kind,
                dict(job.get("input_snapshot") or {}),
                output_json,
            )
        claim = advance(session, claim, "dispatched")
        completed = complete_creative_generation(
            session,
            UUID(str(job["id"])),
            model_evidence=evidence.as_dict(),
            output_text=output_text,
            output_json=output_json,
        )
        return _response(session, claim, job=completed)
    except (Exception, asyncio.CancelledError) as error:
        session.rollback()
        if owns_action and claim is not None and claim.state in {
            "claimed",
            "routing_started",
            "route_ready",
            "assembled",
            "dispatch_started",
        }:
            semantic_uncertain = (
                isinstance(error, SemanticRouteIncomplete)
                and error.remote_outcome_uncertain
            )
            terminal = (
                "unknown"
                if semantic_uncertain or (transport_started and not reply_received)
                else "failed"
            )
            try:
                claim = advance(
                    session,
                    claim,
                    terminal,
                    error_code="managed_creation_helper_failed",
                )
            except StaleFence:
                pass
        if job is not None and job.get("should_execute", True):
            try:
                if isinstance(error, NovelModelEvidenceRejected):
                    evidence = error.evidence
                elif evidence is None and configured is not None:
                    evidence = failed_novel_model_evidence(
                        configured,
                        started_monotonic=(
                            started if started is not None else time.monotonic()
                        ),
                    )
                actual = evidence.actual_identity if evidence is not None else None
                job = fail_creative_generation(
                    session,
                    UUID(str(job["id"])),
                    failure_message=str(error),
                    actual_provider_id=(actual.provider_id if actual is not None else None),
                    actual_model_id=(actual.model_id if actual is not None else None),
                    model_evidence=(evidence.as_dict() if evidence is not None else None),
                )
            except Exception:
                session.rollback()
        if isinstance(error, asyncio.CancelledError):
            raise
        if isinstance(error, HTTPException):
            raise
        detail: dict[str, object] = {
            "type": "managed_creation_helper_failed",
            "message": str(error),
        }
        if claim is not None:
            detail["writing_method"] = method_status(claim).model_dump(mode="json")
        status = 409 if isinstance(error, (ActionConflict, StaleFence, ValidationError)) else 502
        if isinstance(error, MethodPolicyViolation) and claim is None:
            status = 503
        raise HTTPException(status, detail) from error
