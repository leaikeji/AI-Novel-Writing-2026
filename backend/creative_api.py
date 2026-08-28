"""HTTP routes for the complete long-form creation workflow."""

from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from .character_profile_services import (
    CharacterProfileValidationError,
    normalize_character_profile_output,
)
from .creative_schemas import (
    ApplyOutlineGenerationRequest,
    ApplyCharacterProfileCompletionRequest,
    BatchRelationshipsRequest,
    CompleteVersionedRequest,
    CreateAssetPresetRequest,
    CreateChapterDraftRequest,
    CreateCharacterRequest,
    CreateExportRequest,
    CreateForeshadowRequest,
    CreateNovelDraftRequest,
    CreatePrivateAssetRequest,
    CreateRelationshipRequest,
    CreateStorylineRequest,
    DeleteVolumeRequest,
    GenerateCharacterProfileCompletionRequest,
    ReorderChaptersRequest,
    ReorderVolumesRequest,
    RestoreCharacterProfileBatchRequest,
    SaveRelationshipGraphViewRequest,
    StartCreativeGenerationRequest,
    SyncRelationshipsRequest,
    UpdateAssetPresetRequest,
    UpdateChapterDraftRequest,
    UpdateCharacterRequest,
    UpdateDocumentMetadataRequest,
    UpdateForeshadowRequest,
    UpdateNovelDraftRequest,
    UpdateNovelSettingsRequest,
    UpdateOutlineDraftRequest,
    UpdatePrivateAssetRequest,
    UpdateRelationshipRequest,
    UpdateStorylineRequest,
    UpdateVolumeRequest,
)
from .creative_services import (
    EntityConflictError,
    archive_asset_preset,
    archive_private_asset,
    apply_relationship_graph_generation,
    apply_outline_generation_candidate,
    apply_character_profile_completion,
    build_character_profile_completion_snapshot,
    build_relationship_graph_snapshot,
    build_creative_generation_prompt,
    build_novel_export,
    batch_character_relationships,
    complete_chapter_creation_draft,
    complete_creative_generation,
    complete_novel_creation_draft,
    complete_outline_draft,
    create_asset_preset,
    create_character_relationship,
    create_foreshadow,
    create_novel_character,
    create_private_asset,
    create_storyline,
    creative_generation_skill,
    delete_character_relationship,
    delete_document,
    delete_foreshadow,
    delete_novel_character,
    delete_storyline,
    delete_volume,
    fail_creative_generation,
    get_novel_creation_draft,
    get_character_profile_completion_job,
    get_character_profile_completion_status,
    get_relationship_graph_view,
    get_or_create_chapter_creation_draft,
    get_or_create_novel_creation_draft,
    get_or_create_outline_draft,
    get_relationship_auto_sync_status,
    list_asset_presets,
    list_character_relationships,
    list_character_relationship_history,
    list_creative_generations,
    list_foreshadows,
    list_novel_characters,
    list_private_assets,
    list_storylines,
    outline_candidate_review,
    reorder_chapters,
    reorder_volumes,
    restore_character_relationship,
    restore_character_profile_apply_batch,
    save_relationship_graph_view,
    start_creative_generation,
    update_asset_preset,
    update_chapter_creation_draft,
    update_character_relationship,
    update_document_metadata,
    update_foreshadow,
    update_novel_character,
    update_novel_creation_draft,
    update_novel_settings,
    update_outline_draft,
    update_private_asset,
    update_storyline,
    update_volume,
)
from .database import get_session
from .generation_dependencies import (
    get_novel_effective_model,
    get_novel_generation_ctx,
)
from .model_runtime import (
    GENERATION_CONTRACT_VERSION,
    NOVEL_AGENT_ID,
    ModelAudit,
    ModelVerificationError,
    ensure_prompt_within_effective_limit,
    normalize_creative_generation_json,
    parse_model_json,
    reply_final_text,
    reply_model_audit,
)
from .services import NotFoundError, ValidationError, delete_novel
from .selection_edit_diff import (
    SelectionEditDiffError,
    build_selection_edit_result,
)


router = APIRouter()


def _raise(error: Exception) -> None:
    if isinstance(error, EntityConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"type": "entity_conflict", "current": error.current},
        ) from error
    if isinstance(error, NotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    if isinstance(error, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    raise error


@router.delete("/novels/{novel_id}")
def novels_delete(
    novel_id: UUID,
    expected_version: int = Query(ge=1),
    session: Session = Depends(get_session),
) -> dict[str, bool]:
    try:
        delete_novel(session, novel_id, expected_version=expected_version)
        return {"deleted": True}
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.post("/creation-drafts", status_code=status.HTTP_201_CREATED)
def creation_drafts_create(
    request: CreateNovelDraftRequest, session: Session = Depends(get_session)
) -> dict[str, object]:
    try:
        return get_or_create_novel_creation_draft(session, request.draft_key)
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.get("/creation-drafts/{draft_id}")
def creation_drafts_get(
    draft_id: UUID, session: Session = Depends(get_session)
) -> dict[str, object]:
    try:
        return get_novel_creation_draft(session, draft_id)
    except Exception as error:
        _raise(error)
        raise


@router.patch("/creation-drafts/{draft_id}")
def creation_drafts_update(
    draft_id: UUID,
    request: UpdateNovelDraftRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return update_novel_creation_draft(
            session,
            draft_id,
            expected_version=request.expected_version,
            step=request.step,
            data_patch=request.data_patch,
        )
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.post("/creation-drafts/{draft_id}/complete", status_code=status.HTTP_201_CREATED)
def creation_drafts_complete(
    draft_id: UUID,
    request: CompleteVersionedRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return complete_novel_creation_draft(
            session, draft_id, expected_version=request.expected_version
        )
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.get("/private-assets")
def private_assets_index(
    asset_type: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
    session: Session = Depends(get_session),
) -> list[dict[str, object]]:
    try:
        return list_private_assets(
            session, asset_type=asset_type, include_archived=include_archived
        )
    except Exception as error:
        _raise(error)
        raise


@router.post("/private-assets", status_code=status.HTTP_201_CREATED)
def private_assets_create(
    request: CreatePrivateAssetRequest, session: Session = Depends(get_session)
) -> dict[str, object]:
    try:
        return create_private_asset(
            session,
            asset_type=request.asset_type,
            title=request.title,
            content=request.content,
        )
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.put("/private-assets/{asset_id}")
def private_assets_update(
    asset_id: UUID,
    request: UpdatePrivateAssetRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return update_private_asset(
            session,
            asset_id,
            expected_version=request.expected_version,
            title=request.title,
            content=request.content,
        )
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.delete("/private-assets/{asset_id}")
def private_assets_delete(
    asset_id: UUID,
    expected_version: int = Query(ge=1),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return archive_private_asset(session, asset_id, expected_version=expected_version)
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.get("/asset-presets")
def asset_presets_index(
    include_archived: bool = Query(default=False), session: Session = Depends(get_session)
) -> list[dict[str, object]]:
    return list_asset_presets(session, include_archived=include_archived)


@router.post("/asset-presets", status_code=status.HTTP_201_CREATED)
def asset_presets_create(
    request: CreateAssetPresetRequest, session: Session = Depends(get_session)
) -> dict[str, object]:
    try:
        return create_asset_preset(
            session,
            title=request.title,
            description=request.description,
            asset_ids=request.asset_ids,
        )
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.put("/asset-presets/{preset_id}")
def asset_presets_update(
    preset_id: UUID,
    request: UpdateAssetPresetRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return update_asset_preset(
            session,
            preset_id,
            expected_version=request.expected_version,
            title=request.title,
            description=request.description,
            asset_ids=request.asset_ids,
        )
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.delete("/asset-presets/{preset_id}")
def asset_presets_delete(
    preset_id: UUID,
    expected_version: int = Query(ge=1),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return archive_asset_preset(session, preset_id, expected_version=expected_version)
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.get("/novels/{novel_id}/outline-draft")
def outline_drafts_get(
    novel_id: UUID, session: Session = Depends(get_session)
) -> dict[str, object]:
    try:
        return get_or_create_outline_draft(session, novel_id)
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.patch("/novels/{novel_id}/outline-draft")
def outline_drafts_update(
    novel_id: UUID,
    request: UpdateOutlineDraftRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return update_outline_draft(
            session,
            novel_id,
            expected_version=request.expected_version,
            step=request.step,
            target_chapter_count=request.target_chapter_count,
            background_text=request.background_text,
            characters=request.characters,
            plot_text=request.plot_text,
            highlight_text=request.highlight_text,
        )
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.post("/novels/{novel_id}/outline-draft/complete")
def outline_drafts_complete(
    novel_id: UUID,
    request: CompleteVersionedRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return complete_outline_draft(
            session, novel_id, expected_version=request.expected_version
        )
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.get("/novels/{novel_id}/characters")
def characters_index(
    novel_id: UUID, session: Session = Depends(get_session)
) -> list[dict[str, object]]:
    return list_novel_characters(session, novel_id)


@router.post("/novels/{novel_id}/characters", status_code=status.HTTP_201_CREATED)
def characters_create(
    novel_id: UUID,
    request: CreateCharacterRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return create_novel_character(
            session,
            novel_id,
            role_type=request.role_type,
            name=request.name,
            description=request.description,
            details=request.details,
        )
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.put("/novels/{novel_id}/characters/{character_id}")
def characters_update(
    novel_id: UUID,
    character_id: UUID,
    request: UpdateCharacterRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return update_novel_character(
            session,
            novel_id,
            character_id,
            expected_version=request.expected_version,
            role_type=request.role_type,
            name=request.name,
            description=request.description,
            details=(
                request.details_patch
                if request.details_patch is not None
                else request.details or {}
            ),
        )
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.delete("/novels/{novel_id}/characters/{character_id}")
def characters_delete(
    novel_id: UUID,
    character_id: UUID,
    expected_version: int = Query(ge=1),
    session: Session = Depends(get_session),
) -> dict[str, bool]:
    try:
        delete_novel_character(
            session, novel_id, character_id, expected_version=expected_version
        )
        return {"deleted": True}
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.get("/novels/{novel_id}/character-profile-completion/status")
def character_profile_completion_status(
    novel_id: UUID,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return get_character_profile_completion_status(session, novel_id)
    except Exception as error:
        _raise(error)
        raise


@router.post("/novels/{novel_id}/character-profile-completion/generate")
async def character_profile_completion_generate(
    novel_id: UUID,
    request: GenerateCharacterProfileCompletionRequest,
    ctx=Depends(get_novel_generation_ctx),
    configured_model: ModelAudit = Depends(get_novel_effective_model),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    job: dict[str, object] | None = None
    owns_execution = False
    actual_model: ModelAudit | None = None
    try:
        current_status = get_character_profile_completion_status(session, novel_id)
        if not current_status["eligible"]:
            raise ValidationError("当前没有可核验的正式角色设定或正文证据")
        snapshot = build_character_profile_completion_snapshot(session, novel_id)
        job = start_creative_generation(
            session,
            scope_type="novel",
            scope_id=novel_id,
            kind="character_profile_completion",
            input_snapshot=snapshot,
            execution_agent_id=NOVEL_AGENT_ID,
            requested_provider_id=configured_model.provider_id,
            requested_model_id=configured_model.model_id,
            generation_contract_version=GENERATION_CONTRACT_VERSION,
            novel_id=novel_id,
            force_new=request.force_new,
        )
        owns_execution = bool(job.get("should_execute", True))
        if job["state"] == "running" and owns_execution:
            generation_session_id = f"novel-character-profile-completion:{job['id']}"
            prompt = build_creative_generation_prompt(job)
            ensure_prompt_within_effective_limit(prompt, configured_model)
            reply = await ctx.chat(
                prompt,
                skill="character-craft",
                session_id=generation_session_id,
            )
            actual_model = reply_model_audit(reply, session_id=generation_session_id)
            actual_model.ensure_matches(configured_model)
            final_text = reply_final_text(reply)
            strict_candidate = final_text.strip()
            if not strict_candidate.startswith("{") or not strict_candidate.endswith("}"):
                raise ModelVerificationError(
                    "模型没有返回可解析的 JSON："
                    "角色卡补全必须只返回唯一裸 JSON 对象"
                )
            try:
                parsed_output = json.loads(strict_candidate)
            except json.JSONDecodeError as error:
                raise ModelVerificationError("模型没有返回可解析的 JSON 对象") from error
            if not isinstance(parsed_output, dict):
                raise ModelVerificationError("角色卡补全模型结果必须是 JSON 对象")
            normalized_output = normalize_character_profile_output(snapshot, parsed_output)
            complete_creative_generation(
                session,
                UUID(str(job["id"])),
                actual_provider_id=actual_model.provider_id,
                actual_model_id=actual_model.model_id,
                output_text=final_text,
                output_json=normalized_output,
            )
        return get_character_profile_completion_status(session, novel_id)
    except Exception as error:
        session.rollback()
        failed = job
        if owns_execution and job is not None and job.get("id"):
            try:
                failed = fail_creative_generation(
                    session,
                    UUID(str(job["id"])),
                    failure_message=str(error),
                    actual_provider_id=(actual_model.provider_id if actual_model else None),
                    actual_model_id=(actual_model.model_id if actual_model else None),
                )
            except Exception:
                session.rollback()
        if isinstance(error, (ModelVerificationError, CharacterProfileValidationError)):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"type": "model_verification_failed", "job": failed},
            ) from error
        _raise(error)
        raise


@router.get(
    "/novels/{novel_id}/character-profile-completion/jobs/{job_id}"
)
def character_profile_completion_job(
    novel_id: UUID,
    job_id: UUID,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return get_character_profile_completion_job(session, novel_id, job_id)
    except Exception as error:
        _raise(error)
        raise


@router.post(
    "/novels/{novel_id}/character-profile-completion/jobs/{job_id}/apply"
)
def character_profile_completion_apply(
    novel_id: UUID,
    job_id: UUID,
    request: ApplyCharacterProfileCompletionRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return apply_character_profile_completion(
            session,
            novel_id,
            job_id,
            idempotency_key=request.idempotency_key,
            decisions=[item.model_dump(mode="json") for item in request.decisions],
        )
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.post(
    "/novels/{novel_id}/character-profile-completion/apply-batches/{batch_id}/restore"
)
def character_profile_completion_restore(
    novel_id: UUID,
    batch_id: UUID,
    request: RestoreCharacterProfileBatchRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return restore_character_profile_apply_batch(
            session,
            novel_id,
            batch_id,
            idempotency_key=request.idempotency_key,
        )
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.get("/novels/{novel_id}/relationships")
def relationships_index(
    novel_id: UUID,
    include_archived: bool = Query(default=False),
    session: Session = Depends(get_session),
) -> list[dict[str, object]]:
    return list_character_relationships(
        session,
        novel_id,
        include_archived=include_archived,
    )


@router.get("/novels/{novel_id}/relationships/auto-sync/status")
def relationships_auto_sync_status(
    novel_id: UUID,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return get_relationship_auto_sync_status(session, novel_id)
    except Exception as error:
        _raise(error)
        raise


@router.post("/novels/{novel_id}/relationships/auto-sync")
async def relationships_auto_sync(
    novel_id: UUID,
    request: SyncRelationshipsRequest,
    ctx=Depends(get_novel_generation_ctx),
    configured_model: ModelAudit = Depends(get_novel_effective_model),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    job: dict[str, object] | None = None
    owns_execution = False
    actual_model: ModelAudit | None = None
    try:
        snapshot = build_relationship_graph_snapshot(session, novel_id)
        job = start_creative_generation(
            session,
            scope_type="novel",
            scope_id=novel_id,
            kind="relationship_graph",
            input_snapshot=snapshot,
            execution_agent_id=NOVEL_AGENT_ID,
            requested_provider_id=configured_model.provider_id,
            requested_model_id=configured_model.model_id,
            generation_contract_version=GENERATION_CONTRACT_VERSION,
            novel_id=novel_id,
            force_new=request.force_new,
        )
        owns_execution = bool(job.get("should_execute", True))
        if job["state"] == "running" and not owns_execution:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "type": "relationship_generation_in_progress",
                    "job": job,
                },
            )
        if job["state"] == "running" and job.get("should_execute", True):
            generation_session_id = f"novel-relationship-auto-sync:{job['id']}"
            prompt = build_creative_generation_prompt(job)
            ensure_prompt_within_effective_limit(prompt, configured_model)
            reply = await ctx.chat(
                prompt,
                skill="story-foundation",
                session_id=generation_session_id,
            )
            actual_model = reply_model_audit(
                reply,
                session_id=generation_session_id,
            )
            actual_model.ensure_matches(configured_model)
            final_text = reply_final_text(reply)
            try:
                parsed_output = parse_model_json(final_text)
            except ModelVerificationError:
                parsed_output = {}
            output_json = normalize_creative_generation_json(
                "relationship_graph",
                parsed_output,
                final_text,
            )
            job = complete_creative_generation(
                session,
                UUID(str(job["id"])),
                actual_provider_id=actual_model.provider_id,
                actual_model_id=actual_model.model_id,
                output_text=final_text,
                output_json=output_json,
            )
        return apply_relationship_graph_generation(
            session,
            novel_id,
            UUID(str(job["id"])),
        )
    except Exception as error:
        session.rollback()
        if owns_execution and job is not None and job.get("id"):
            try:
                failed = fail_creative_generation(
                    session,
                    UUID(str(job["id"])),
                    failure_message=str(error),
                    actual_provider_id=(
                        actual_model.provider_id if actual_model else None
                    ),
                    actual_model_id=(actual_model.model_id if actual_model else None),
                )
            except Exception:
                session.rollback()
                failed = job
            if isinstance(error, ModelVerificationError):
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail={"type": "model_verification_failed", "job": failed},
                ) from error
        _raise(error)
        raise


@router.post("/novels/{novel_id}/relationships", status_code=status.HTTP_201_CREATED)
def relationships_create(
    novel_id: UUID,
    request: CreateRelationshipRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return create_character_relationship(
            session,
            novel_id,
            source_character_id=request.source_character_id,
            target_character_id=request.target_character_id,
            label=request.label or request.relation_type or "",
            directionality=request.directionality,
            relation_kind=request.relation_kind,
            description=request.description,
        )
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.post("/novels/{novel_id}/relationships/batch")
def relationships_batch(
    novel_id: UUID,
    request: BatchRelationshipsRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return batch_character_relationships(
            session,
            novel_id,
            operations=[operation.model_dump() for operation in request.operations],
        )
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.put("/novels/{novel_id}/relationships/{relationship_id}")
def relationships_update(
    novel_id: UUID,
    relationship_id: UUID,
    request: UpdateRelationshipRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return update_character_relationship(
            session,
            novel_id,
            relationship_id,
            expected_version=request.expected_version,
            source_character_id=request.source_character_id,
            target_character_id=request.target_character_id,
            label=request.label or request.relation_type,
            directionality=request.directionality,
            relation_kind=request.relation_kind,
            description=request.description,
            status=request.status,
        )
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.post("/novels/{novel_id}/relationships/{relationship_id}/restore")
def relationships_restore(
    novel_id: UUID,
    relationship_id: UUID,
    request: CompleteVersionedRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return restore_character_relationship(
            session,
            novel_id,
            relationship_id,
            expected_version=request.expected_version,
        )
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.get("/novels/{novel_id}/relationships/{relationship_id}/history")
def relationships_history(
    novel_id: UUID,
    relationship_id: UUID,
    session: Session = Depends(get_session),
) -> list[dict[str, object]]:
    return list_character_relationship_history(session, novel_id, relationship_id)


@router.get("/novels/{novel_id}/relationship-graph-view")
def relationship_graph_view_show(
    novel_id: UUID,
    name: str = Query(default="默认视图", min_length=1, max_length=120),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return get_relationship_graph_view(session, novel_id, name=name)


@router.put("/novels/{novel_id}/relationship-graph-view")
def relationship_graph_view_save(
    novel_id: UUID,
    request: SaveRelationshipGraphViewRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return save_relationship_graph_view(
            session,
            novel_id,
            expected_version=request.expected_version,
            name=request.name,
            layout_algorithm=request.layout_algorithm,
            random_seed=request.random_seed,
            zoom=request.zoom,
            pan_x=request.pan_x,
            pan_y=request.pan_y,
            positions=[position.model_dump() for position in request.positions],
        )
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.delete("/novels/{novel_id}/relationships/{relationship_id}")
def relationships_delete(
    novel_id: UUID,
    relationship_id: UUID,
    expected_version: int = Query(ge=1),
    session: Session = Depends(get_session),
) -> dict[str, bool]:
    try:
        delete_character_relationship(
            session, novel_id, relationship_id, expected_version=expected_version
        )
        return {"deleted": True}
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.get("/novels/{novel_id}/storylines")
def storylines_index(
    novel_id: UUID, session: Session = Depends(get_session)
) -> list[dict[str, object]]:
    return list_storylines(session, novel_id)


@router.post("/novels/{novel_id}/storylines", status_code=status.HTTP_201_CREATED)
def storylines_create(
    novel_id: UUID,
    request: CreateStorylineRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return create_storyline(
            session,
            novel_id,
            storyline_type=request.storyline_type,
            title=request.title,
            description=request.description,
        )
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.put("/novels/{novel_id}/storylines/{storyline_id}")
def storylines_update(
    novel_id: UUID,
    storyline_id: UUID,
    request: UpdateStorylineRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return update_storyline(
            session,
            novel_id,
            storyline_id,
            expected_version=request.expected_version,
            storyline_type=request.storyline_type,
            title=request.title,
            description=request.description,
            status=request.status,
            progress=request.progress,
        )
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.delete("/novels/{novel_id}/storylines/{storyline_id}")
def storylines_delete(
    novel_id: UUID,
    storyline_id: UUID,
    expected_version: int = Query(ge=1),
    session: Session = Depends(get_session),
) -> dict[str, bool]:
    try:
        delete_storyline(session, novel_id, storyline_id, expected_version=expected_version)
        return {"deleted": True}
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.get("/novels/{novel_id}/foreshadows")
def foreshadows_index(
    novel_id: UUID, session: Session = Depends(get_session)
) -> list[dict[str, object]]:
    return list_foreshadows(session, novel_id)


@router.post("/novels/{novel_id}/foreshadows", status_code=status.HTTP_201_CREATED)
def foreshadows_create(
    novel_id: UUID,
    request: CreateForeshadowRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return create_foreshadow(
            session,
            novel_id,
            title=request.title,
            content=request.content,
            latest_progress=request.latest_progress,
        )
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.put("/novels/{novel_id}/foreshadows/{foreshadow_id}")
def foreshadows_update(
    novel_id: UUID,
    foreshadow_id: UUID,
    request: UpdateForeshadowRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return update_foreshadow(
            session,
            novel_id,
            foreshadow_id,
            expected_version=request.expected_version,
            title=request.title,
            content=request.content,
            latest_progress=request.latest_progress,
            status=request.status,
            progress=request.progress,
        )
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.delete("/novels/{novel_id}/foreshadows/{foreshadow_id}")
def foreshadows_delete(
    novel_id: UUID,
    foreshadow_id: UUID,
    expected_version: int = Query(ge=1),
    session: Session = Depends(get_session),
) -> dict[str, bool]:
    try:
        delete_foreshadow(session, novel_id, foreshadow_id, expected_version=expected_version)
        return {"deleted": True}
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.post("/novels/{novel_id}/chapter-drafts", status_code=status.HTTP_201_CREATED)
def chapter_drafts_create(
    novel_id: UUID,
    request: CreateChapterDraftRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return get_or_create_chapter_creation_draft(
            session,
            novel_id=novel_id,
            volume_id=request.volume_id,
            draft_key=request.draft_key,
        )
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.patch("/chapter-drafts/{draft_id}")
def chapter_drafts_update(
    draft_id: UUID,
    request: UpdateChapterDraftRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return update_chapter_creation_draft(
            session,
            draft_id,
            expected_version=request.expected_version,
            step=request.step,
            title=request.title,
            target_character_count=request.target_character_count,
            expectation_text=request.expectation_text,
            outline_text=request.outline_text,
            data_patch=request.data_patch,
        )
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.post("/chapter-drafts/{draft_id}/complete", status_code=status.HTTP_201_CREATED)
def chapter_drafts_complete(
    draft_id: UUID,
    request: CompleteVersionedRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return complete_chapter_creation_draft(
            session, draft_id, expected_version=request.expected_version
        )
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.post("/creative-generations", status_code=status.HTTP_201_CREATED)
async def creative_generations_create(
    request: StartCreativeGenerationRequest,
    ctx=Depends(get_novel_generation_ctx),
    configured_model: ModelAudit = Depends(get_novel_effective_model),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    job: dict[str, object] | None = None
    actual_model: ModelAudit | None = None
    try:
        job = start_creative_generation(
            session,
            scope_type=request.scope_type,
            scope_id=request.scope_id,
            kind=request.kind,
            input_snapshot=request.input_snapshot,
            execution_agent_id=NOVEL_AGENT_ID,
            requested_provider_id=configured_model.provider_id,
            requested_model_id=configured_model.model_id,
            generation_contract_version=GENERATION_CONTRACT_VERSION,
            novel_id=request.novel_id,
            document_id=request.document_id,
            target_character_count=request.target_character_count,
            force_new=request.force_new,
        )
        if job["state"] != "running" or not job.get("should_execute", True):
            return job
        generation_session_id = f"novel-creative-generation:{job['id']}"
        prompt = build_creative_generation_prompt(job)
        kind = str(job["kind"])
        verification_attempts = 2 if kind == "selection_edit" else 1
        output_json: dict[str, object] = {}
        reply = None
        for verification_attempt in range(verification_attempts):
            attempt_session_id = (
                generation_session_id
                if verification_attempt == 0
                else f"{generation_session_id}:verification-retry-{verification_attempt}"
            )
            attempt_prompt = prompt
            if verification_attempt > 0:
                attempt_prompt += (
                    "\n上一次响应未通过严格 JSON 验证。重新执行同一任务；"
                    "只输出唯一一个两字段 JSON 对象，不要输出备选方案、示例或解释。"
                )
            ensure_prompt_within_effective_limit(attempt_prompt, configured_model)
            reply = await ctx.chat(
                attempt_prompt,
                skill=creative_generation_skill(job),
                session_id=attempt_session_id,
            )
            actual_model = reply_model_audit(
                reply,
                session_id=attempt_session_id,
            )
            actual_model.ensure_matches(configured_model)
            final_text = reply_final_text(reply)
            try:
                parsed_output = parse_model_json(final_text)
            except ModelVerificationError:
                if kind == "selection_edit":
                    if verification_attempt + 1 < verification_attempts:
                        continue
                    raise
                # Single-text helpers can safely recover useful prose even when the
                # model omitted its JSON envelope. Kind-aware normalization below
                # still rejects every incomplete structured result.
                parsed_output = {}
            try:
                output_json = normalize_creative_generation_json(
                    kind,
                    parsed_output,
                    final_text,
                )
            except ModelVerificationError:
                if kind == "selection_edit" and verification_attempt + 1 < verification_attempts:
                    continue
                raise
            break
        if reply is None:
            raise ModelVerificationError("模型选区编辑未返回候选")
        output_text = final_text
        if kind == "selection_edit":
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
        elif kind.startswith("outline_"):
            output_json["candidate_review"] = outline_candidate_review(
                kind,
                dict(job.get("input_snapshot") or {}),
                output_json,
            )
        return complete_creative_generation(
            session,
            UUID(str(job["id"])),
            actual_provider_id=actual_model.provider_id,
            actual_model_id=actual_model.model_id,
            output_text=output_text,
            output_json=output_json,
        )
    except Exception as error:
        session.rollback()
        if job is not None and job.get("id"):
            try:
                failed = fail_creative_generation(
                    session,
                    UUID(str(job["id"])),
                    failure_message=str(error),
                    actual_provider_id=(
                        actual_model.provider_id if actual_model else None
                    ),
                    actual_model_id=(actual_model.model_id if actual_model else None),
                )
            except Exception:
                session.rollback()
                failed = job
            if isinstance(error, (ModelVerificationError, SelectionEditDiffError)):
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail={"type": "model_verification_failed", "job": failed},
                ) from error
        _raise(error)
        raise


@router.post("/creative-generations/{job_id}/apply-outline")
def creative_generations_apply_outline(
    job_id: UUID,
    request: ApplyOutlineGenerationRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return apply_outline_generation_candidate(
            session,
            job_id,
            expected_version=request.expected_version,
        )
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.get("/creative-generations")
def creative_generations_index(
    scope_type: str = Query(min_length=1, max_length=40),
    scope_id: UUID = Query(),
    kind: str | None = Query(default=None, min_length=1, max_length=40),
    selection_id: UUID | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[dict[str, object]]:
    try:
        return list_creative_generations(
            session,
            scope_type=scope_type,
            scope_id=scope_id,
            kind=kind,
            selection_id=selection_id,
        )
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.put("/novels/{novel_id}/volumes/{volume_id}")
def volumes_update(
    novel_id: UUID,
    volume_id: UUID,
    request: UpdateVolumeRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return update_volume(
            session,
            novel_id,
            volume_id,
            expected_version=request.expected_version,
            title=request.title,
        )
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.put("/novels/{novel_id}/settings")
def novels_update_settings(
    novel_id: UUID,
    request: UpdateNovelSettingsRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return update_novel_settings(
            session,
            novel_id,
            expected_version=request.expected_version,
            genre=request.genre,
            subgenre=request.subgenre,
            idea=request.idea,
            template_name=request.template_name,
            template_data=request.template_data,
            cover_mode=request.cover_mode,
            cover_image_data=request.cover_image_data,
        )
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.delete("/novels/{novel_id}/volumes/{volume_id}")
def volumes_delete(
    novel_id: UUID,
    volume_id: UUID,
    request: DeleteVolumeRequest,
    session: Session = Depends(get_session),
) -> dict[str, bool]:
    try:
        delete_volume(
            session,
            novel_id,
            volume_id,
            expected_version=request.expected_version,
            move_documents_to=request.move_documents_to,
        )
        return {"deleted": True}
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.post("/novels/{novel_id}/volumes/reorder")
def volumes_reorder(
    novel_id: UUID,
    request: ReorderVolumesRequest,
    session: Session = Depends(get_session),
) -> list[dict[str, object]]:
    try:
        return reorder_volumes(
            session, novel_id, ordered_volume_ids=request.ordered_volume_ids
        )
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.put("/novels/{novel_id}/documents/{document_id}")
def documents_update_metadata(
    novel_id: UUID,
    document_id: UUID,
    request: UpdateDocumentMetadataRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return update_document_metadata(
            session,
            novel_id,
            document_id,
            expected_version=request.expected_version,
            title=request.title,
        )
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.delete("/novels/{novel_id}/documents/{document_id}")
def documents_delete(
    novel_id: UUID,
    document_id: UUID,
    expected_version: int = Query(ge=1),
    session: Session = Depends(get_session),
) -> dict[str, bool]:
    try:
        delete_document(
            session, novel_id, document_id, expected_version=expected_version
        )
        return {"deleted": True}
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.post("/novels/{novel_id}/chapters/reorder")
def chapters_reorder(
    novel_id: UUID,
    request: ReorderChaptersRequest,
    session: Session = Depends(get_session),
) -> list[dict[str, object]]:
    try:
        return reorder_chapters(
            session,
            novel_id,
            ordered_document_ids=request.ordered_document_ids,
            volume_by_document=request.volume_by_document,
        )
    except Exception as error:
        session.rollback()
        _raise(error)
        raise


@router.post("/novels/{novel_id}/exports", status_code=status.HTTP_201_CREATED)
def exports_create(
    novel_id: UUID,
    request: CreateExportRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        return build_novel_export(
            session, novel_id, export_format=request.export_format
        )
    except Exception as error:
        session.rollback()
        _raise(error)
        raise
