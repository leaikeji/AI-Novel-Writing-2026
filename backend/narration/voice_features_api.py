"""Novel-scoped HTTP surface for the three Plan35 narration features."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
import hashlib
import logging
import time
from typing import Awaitable, Callable, Mapping
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from ..character_workspace.contracts import (
    CharacterWorkspaceError,
    CharacterWorkspaceErrorCode,
)
from ..character_workspace.service import service_for_session
from ..database import get_engine, get_session
from ..model_runtime import (
    NOVEL_AGENT_ID,
    ModelAudit,
    ModelVerificationError,
    effective_model_audit,
    ensure_prompt_within_effective_limit,
    parse_model_json,
    reply_final_text,
)
try:
    from ..generation_dependencies import (
        EffectiveModelProbe,
        NovelModelEvidenceRejected,
        get_novel_effective_model,
        get_novel_effective_model_probe,
        get_novel_generation_ctx,
        verify_novel_model_reply,
    )
except ModuleNotFoundError as error:  # pragma: no cover - host-only fallback
    if error.name != "qwenpaw" and not str(error.name).startswith("qwenpaw."):
        raise

    EffectiveModelProbe = Callable[[], Awaitable[ModelAudit]]

    class NovelModelEvidenceRejected(ModelVerificationError):
        pass

    async def _missing_qwenpaw_dependency():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"type": "generation_model_unavailable"},
        )

    get_novel_effective_model = _missing_qwenpaw_dependency
    get_novel_effective_model_probe = _missing_qwenpaw_dependency
    get_novel_generation_ctx = _missing_qwenpaw_dependency

    async def verify_novel_model_reply(*_args, **_kwargs):
        return await _missing_qwenpaw_dependency()
from . import schemas as wire
from .character_voice_matching import (
    CharacterVoiceLanguage,
    CharacterVoiceMatchingError,
    build_character_voice_prompt,
    match_official_voice,
    parse_character_voice_brief,
)
from .character_cast_plan_service import (
    CharacterCastTargetAnalysis,
    SqlAlchemyCharacterCastPlanService,
    character_cast_plan_request_hash,
)
from .narrator_voice_brief import (
    build_narrator_voice_prompt,
    parse_narrator_voice_brief,
)
from .voice_design import build_voice_design_instruction
from .feature_readiness import NARRATION_FEATURE_READINESS_PROVIDER
from .nano_experiments import (
    NanoExperimentApplyRequest,
    NanoExperimentCommand,
    NanoExperimentContractError,
    NanoExperimentIdempotencyConflict,
    NanoExperimentStateError,
    NanoExperimentTarget,
)
from .official_voice_selection import OfficialVoiceSelectionService
from .privacy import get_character_voice_binding, get_narration_settings
from .production_runtime import (
    current_generic_voice_pack_service,
    current_nano_experiment_service,
    current_private_voice_deletion_service,
    current_private_voice_lifecycle_service,
    current_voice_generator_service,
    current_voice_preparation_service,
    current_voice_product_port,
    wake_voice_preparation_reconciler,
)
from .services import (
    IdempotencyConflict,
    InvalidNarrationState,
    NarrationCasConflict,
    NarrationNotFound,
    NarrationScopeMismatch,
    NarrationServiceError,
    SqlAlchemyNarrationStore,
    canonical_sha256,
)
from .storage import StorageError
from .voice_deletion import VoiceDeletionConflict, VoiceDeletionRequestSnapshot
from .voice_generator_service import (
    SqlAlchemyVoiceGeneratorService,
    VoiceGeneratorAnalysis,
    voice_generator_request_hash,
)
from .voice_preparation import VoicePreparationCreateRequest


# Product default proven by the T3/T5 cold-run matrix. Authors may still
# provide an explicit seed through the frozen API, but one-click generation
# must not derive an unqualified seed from an idempotency hash.
DEFAULT_VOICE_GENERATOR_SEED = 104_729
logger = logging.getLogger(__name__)
AUTOMATIC_GENERIC_PACK_BUILD_KEY = "automatic-generic-voice-pack:zh-CN:v1"


def _resolved_voice_generator_seed(requested_seed: str | None) -> int:
    return (
        int(requested_seed)
        if requested_seed is not None
        else DEFAULT_VOICE_GENERATOR_SEED
    )


router = APIRouter(tags=["narration-features-v3"])
_IDEMPOTENCY_HEADER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$"


def _character_cast_plan_service() -> SqlAlchemyCharacterCastPlanService:
    return SqlAlchemyCharacterCastPlanService(lambda: Session(get_engine()))


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FeatureApiError(_StrictModel):
    type: str
    message: str
    retryable: bool = False
    capability: wire.CapabilityKey | None = None
    reason_code: str | None = None


def _raise_feature_error(
    status_code: int,
    error_type: str,
    message: str,
    *,
    retryable: bool = False,
    capability: wire.CapabilityKey | None = None,
    reason_code: str | None = None,
) -> None:
    raise HTTPException(
        status_code=status_code,
        detail=FeatureApiError(
            type=error_type,
            message=message,
            retryable=retryable,
            capability=capability,
            reason_code=reason_code,
        ).model_dump(mode="json"),
    )


def _require_capability(key: wire.CapabilityKey) -> None:
    capability = NARRATION_FEATURE_READINESS_PROVIDER.snapshot().item(key)
    if (
        capability.state is wire.CapabilityState.ENABLED
        and capability.visible
        and capability.actionable
    ):
        return
    _raise_feature_error(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "capability_unavailable",
        "该朗读能力当前尚未就绪，请稍后重试。",
        retryable=True,
        capability=key,
        reason_code=capability.reason_code,
    )


def _raise_service_error(error: BaseException) -> None:
    if isinstance(error, (NarrationNotFound, NarrationScopeMismatch)):
        _raise_feature_error(
            status.HTTP_404_NOT_FOUND,
            "resource_not_found",
            "找不到当前小说范围内的朗读资源。",
        )
    if isinstance(
        error,
        (
            NarrationCasConflict,
            IdempotencyConflict,
            VoiceDeletionConflict,
            NanoExperimentIdempotencyConflict,
            NanoExperimentStateError,
            InvalidNarrationState,
        ),
    ):
        _raise_feature_error(
            status.HTTP_409_CONFLICT,
            "state_conflict",
            "朗读资源已发生变化，请刷新后重试。",
        )
    if isinstance(error, (StorageError, OSError)):
        _raise_feature_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "storage_unavailable",
            "朗读存储当前不可用。",
            retryable=True,
        )
    if isinstance(error, (NanoExperimentContractError, ValueError)):
        _raise_feature_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "request_validation_failed",
            str(error),
        )
    if isinstance(error, NarrationServiceError):
        _raise_feature_error(
            status.HTTP_409_CONFLICT,
            "invalid_state",
            "朗读资源当前状态不允许执行此操作。",
        )
    raise error


NanoDecodeParametersResource = wire.NanoDecodeParametersResource
CreateNanoVoiceExperimentRequest = wire.CreateNanoVoiceExperimentRequest
ApplyNanoVoiceExperimentRequest = wire.ApplyNanoVoiceExperimentRequest
NanoVoiceExperimentResource = wire.NanoVoiceExperimentResource
NanoVoiceExperimentListResource = wire.NanoVoiceExperimentListResource


def _nano_resource(
    command: NanoExperimentCommand,
    *,
    session: Session,
) -> NanoVoiceExperimentResource:
    store = SqlAlchemyNarrationStore(session)
    settings = get_narration_settings(store, novel_id=command.novel_id)
    binding = None
    if command.target.target_kind == "character":
        assert command.target.character_id is not None
        binding = get_character_voice_binding(
            store,
            novel_id=command.novel_id,
            character_id=command.target.character_id,
        )
    preview = None
    if command.state != "failed":
        product = current_voice_product_port()
        if product is None:
            raise RuntimeError("voice preview projection is unavailable")
        preview = product.get_preview(preview_id=command.preview_id)
    return NanoVoiceExperimentResource(
        command_id=command.command_id,
        novel_id=command.novel_id,
        profile_id=command.profile_id,
        version_id=command.version_id,
        background_job_id=command.background_job_id,
        base_preset_id=command.base_preset_id,
        target_kind=command.target.target_kind,
        character_id=command.target.character_id,
        expected_settings_version=command.target.expected_settings_version,
        expected_binding_version=command.target.expected_binding_version,
        parameters=NanoDecodeParametersResource.from_domain(command.parameters),
        parameters_digest=command.parameters_digest,
        fingerprint=command.fingerprint,
        state=command.state,
        reused_version=command.reused_version,
        preview=preview,
        current_settings=(settings if command.target.target_kind == "narrator" else None),
        current_character_binding=binding,
        failure_code=command.failure_code,
        retryable=command.retryable,
        created_at=command.created_at,
        started_at=command.started_at,
        completed_at=command.completed_at,
    )


def _nano_service():
    _require_capability(wire.CapabilityKey.NANO_ADVANCED_TUNING)
    service = current_nano_experiment_service()
    if service is None:
        _raise_feature_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "capability_unavailable",
            "Nano 高级调音服务当前不可用。",
            retryable=True,
            capability=wire.CapabilityKey.NANO_ADVANCED_TUNING,
        )
    return service


@router.get(
    "/novels/{novel_id}/nano-voice-experiments",
    response_model=NanoVoiceExperimentListResource,
)
def nano_voice_experiments_index(
    novel_id: UUID,
    session: Session = Depends(get_session),
) -> NanoVoiceExperimentListResource:
    try:
        items = _nano_service().list_for_novel(novel_id=novel_id)
        return NanoVoiceExperimentListResource(
            novel_id=novel_id,
            items=[_nano_resource(item, session=session) for item in items],
        )
    except Exception as error:
        _raise_service_error(error)
        raise


@router.post(
    "/novels/{novel_id}/nano-voice-experiments",
    response_model=NanoVoiceExperimentResource,
    status_code=status.HTTP_202_ACCEPTED,
)
def nano_voice_experiments_create(
    novel_id: UUID,
    payload: CreateNanoVoiceExperimentRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
        pattern=_IDEMPOTENCY_HEADER_PATTERN,
    ),
    session: Session = Depends(get_session),
) -> NanoVoiceExperimentResource:
    try:
        reservation = _nano_service().create(
            novel_id=novel_id,
            base_preset_id=payload.base_preset_id,
            target=NanoExperimentTarget(
                target_kind=payload.target_kind,
                character_id=payload.character_id,
                expected_settings_version=payload.expected_settings_version,
                expected_binding_version=payload.expected_binding_version,
            ),
            parameters=payload.parameters.domain(),
            idempotency_key=idempotency_key,
        )
        return _nano_resource(reservation.command, session=session)
    except Exception as error:
        _raise_service_error(error)
        raise


@router.get(
    "/novels/{novel_id}/nano-voice-experiments/{command_id}",
    response_model=NanoVoiceExperimentResource,
)
def nano_voice_experiments_get(
    novel_id: UUID,
    command_id: UUID,
    session: Session = Depends(get_session),
) -> NanoVoiceExperimentResource:
    try:
        command = _nano_service().get(novel_id=novel_id, command_id=command_id)
        return _nano_resource(command, session=session)
    except Exception as error:
        _raise_service_error(error)
        raise


@router.put(
    "/novels/{novel_id}/nano-voice-experiments/{command_id}/binding",
    response_model=NanoVoiceExperimentResource,
)
def nano_voice_experiments_apply(
    novel_id: UUID,
    command_id: UUID,
    payload: ApplyNanoVoiceExperimentRequest,
    session: Session = Depends(get_session),
) -> NanoVoiceExperimentResource:
    try:
        command = _nano_service().apply(
            novel_id=novel_id,
            command_id=command_id,
            request=NanoExperimentApplyRequest(
                expected_settings_version=payload.expected_settings_version,
                expected_binding_version=payload.expected_binding_version,
            ),
        )
        return _nano_resource(command, session=session)
    except Exception as error:
        _raise_service_error(error)
        raise


CreatePrivateVoiceDeletionRequest = wire.CreatePrivateVoiceDeletionRequest
ConfirmPrivateVoiceDeletionRequest = wire.ConfirmPrivateVoiceDeletionRequest
PrivateVoiceDeletionImpactResource = wire.PrivateVoiceDeletionImpactResource
PrivateVoiceDeletionRequestResource = wire.PrivateVoiceDeletionRequestResource
PrivateVoiceLifecycleProfileResource = wire.PrivateVoiceLifecycleProfileResource
PrivateVoiceLifecycleResource = wire.PrivateVoiceLifecycleResource


def _deletion_service():
    _require_capability(wire.CapabilityKey.PRIVATE_VOICE_DELETION)
    service = current_private_voice_deletion_service()
    if service is None:
        _raise_feature_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "capability_unavailable",
            "私人音色删除服务当前不可用。",
            retryable=True,
            capability=wire.CapabilityKey.PRIVATE_VOICE_DELETION,
        )
    return service


def _deletion_resource(
    snapshot: VoiceDeletionRequestSnapshot,
) -> PrivateVoiceDeletionRequestResource:
    return PrivateVoiceDeletionRequestResource.model_validate(asdict(snapshot))


@router.get(
    "/novels/{novel_id}/private-voice-lifecycle",
    response_model=PrivateVoiceLifecycleResource,
)
def private_voice_lifecycle_index(novel_id: UUID) -> PrivateVoiceLifecycleResource:
    _require_capability(wire.CapabilityKey.PRIVATE_VOICE_DELETION)
    service = current_private_voice_lifecycle_service()
    if service is None:
        _raise_feature_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "capability_unavailable",
            "私人音色生命周期服务当前不可用。",
            retryable=True,
            capability=wire.CapabilityKey.PRIVATE_VOICE_DELETION,
        )
    try:
        snapshot = service.list_profiles(novel_id=novel_id)
        return PrivateVoiceLifecycleResource.model_validate(asdict(snapshot))
    except Exception as error:
        _raise_service_error(error)
        raise


@router.post(
    "/novels/{novel_id}/voice-profiles/{profile_id}/deletion-requests",
    response_model=PrivateVoiceDeletionRequestResource,
    status_code=status.HTTP_202_ACCEPTED,
)
def private_voice_deletion_create(
    novel_id: UUID,
    profile_id: UUID,
    payload: CreatePrivateVoiceDeletionRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
        pattern=_IDEMPOTENCY_HEADER_PATTERN,
    ),
) -> PrivateVoiceDeletionRequestResource:
    try:
        return _deletion_resource(
            _deletion_service().create_request(
                novel_id=novel_id,
                profile_id=profile_id,
                expected_profile_version=payload.expected_profile_version,
                idempotency_key=idempotency_key,
                actor="local-owner",
            )
        )
    except Exception as error:
        _raise_service_error(error)
        raise


@router.get(
    "/novels/{novel_id}/voice-deletion-requests/{request_id}",
    response_model=PrivateVoiceDeletionRequestResource,
)
def private_voice_deletion_get(
    novel_id: UUID,
    request_id: UUID,
) -> PrivateVoiceDeletionRequestResource:
    try:
        return _deletion_resource(
            _deletion_service().get_request(
                novel_id=novel_id,
                request_id=request_id,
            )
        )
    except Exception as error:
        _raise_service_error(error)
        raise


@router.post(
    "/novels/{novel_id}/voice-deletion-requests/{request_id}/confirm",
    response_model=PrivateVoiceDeletionRequestResource,
)
def private_voice_deletion_confirm(
    novel_id: UUID,
    request_id: UUID,
    payload: ConfirmPrivateVoiceDeletionRequest,
) -> PrivateVoiceDeletionRequestResource:
    try:
        return _deletion_resource(
            _deletion_service().confirm(
                novel_id=novel_id,
                request_id=request_id,
                expected_profile_version=payload.expected_profile_version,
                impact_digest=payload.impact_digest,
                actor="local-owner",
            )
        )
    except Exception as error:
        _raise_service_error(error)
        raise


@router.post(
    "/novels/{novel_id}/voice-deletion-requests/{request_id}/cancel",
    response_model=PrivateVoiceDeletionRequestResource,
)
def private_voice_deletion_cancel(
    novel_id: UUID,
    request_id: UUID,
) -> PrivateVoiceDeletionRequestResource:
    try:
        return _deletion_resource(
            _deletion_service().cancel(
                novel_id=novel_id,
                request_id=request_id,
                actor="local-owner",
            )
        )
    except Exception as error:
        _raise_service_error(error)
        raise


@router.post(
    "/novels/{novel_id}/voice-deletion-requests/{request_id}/retry",
    response_model=PrivateVoiceDeletionRequestResource,
)
def private_voice_deletion_retry(
    novel_id: UUID,
    request_id: UUID,
) -> PrivateVoiceDeletionRequestResource:
    try:
        return _deletion_resource(
            _deletion_service().retry(
                novel_id=novel_id,
                request_id=request_id,
                actor="local-owner",
            )
        )
    except Exception as error:
        _raise_service_error(error)
        raise


CharacterVoiceMatchRequest = wire.CharacterVoiceMatchRequest
CharacterVoiceMatchResource = wire.CharacterVoiceMatchResource
CreateCharacterCastPlanRequest = wire.CreateCharacterCastPlanRequest
CharacterCastPlanResource = wire.CharacterCastPlanResource
CharacterCastPlanListResource = wire.CharacterCastPlanListResource
CreateCharacterVoiceGeneratorCommandRequest = (
    wire.CreateCharacterVoiceGeneratorCommandRequest
)
RetryCharacterVoiceGeneratorCommandRequest = (
    wire.RetryCharacterVoiceGeneratorCommandRequest
)
ApplyCharacterVoiceGeneratorCommandRequest = (
    wire.ApplyCharacterVoiceGeneratorCommandRequest
)
CharacterVoiceGeneratorCommandResource = (
    wire.CharacterVoiceGeneratorCommandResource
)
CharacterVoiceGeneratorCommandListResource = (
    wire.CharacterVoiceGeneratorCommandListResource
)


def _voice_generator_service(
    *, require_actionable: bool = True
) -> SqlAlchemyVoiceGeneratorService:
    if require_actionable:
        _require_capability(wire.CapabilityKey.VOICE_GENERATOR)
    service = current_voice_generator_service()
    if service is None:
        _raise_feature_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "capability_unavailable",
            "人物专属音色生成服务当前不可用。",
            retryable=True,
            capability=wire.CapabilityKey.VOICE_GENERATOR,
        )
    return service


def _workspace_payload(workspace) -> dict[str, object]:
    return {
        "character": workspace.character.model_dump(mode="json"),
        "selected_instance": workspace.selected_instance.model_dump(mode="json"),
        "aliases": [item.model_dump(mode="json") for item in workspace.aliases],
        "relationships": [
            item.model_dump(mode="json") for item in workspace.relationships
        ],
        "projected_state": workspace.projected_state.model_dump(mode="json"),
    }


async def _run_voice_generator_analysis(
    *,
    service: SqlAlchemyVoiceGeneratorService,
    novel_id: UUID,
    character_id: UUID,
    command_id: UUID,
    timeline_id: UUID | None,
    character_instance_id: UUID | None,
    requested_seed: str | None,
    ctx,
    configured_model: ModelAudit,
    model_probe: EffectiveModelProbe,
    session: Session,
) -> CharacterVoiceGeneratorCommandResource:
    if not service.begin_analysis(novel_id=novel_id, command_id=command_id):
        return service.get_resource(novel_id=novel_id, command_id=command_id)
    try:
        workspace = service_for_session(session).get_workspace(
            novel_id,
            character_id,
            timeline_id=timeline_id,
            character_instance_id=character_instance_id,
        )
        workspace_payload = _workspace_payload(workspace)
        session.rollback()
        prompt = build_character_voice_prompt(workspace_payload)
        ensure_prompt_within_effective_limit(prompt, configured_model)
        started_monotonic = time.monotonic()
        reply = await ctx.chat(
            prompt,
            skill="character-craft",
            session_id=f"novel-character-voice-generate:{command_id}",
        )
        evidence = await verify_novel_model_reply(
            reply,
            configured=configured_model,
            probe=model_probe,
            started_monotonic=started_monotonic,
        )
        brief = parse_character_voice_brief(parse_model_json(reply_final_text(reply)))
        default_language = CharacterVoiceLanguage.ZH_CN
        if workspace.voice_binding is not None:
            try:
                default_language = CharacterVoiceLanguage(workspace.voice_binding.language)
            except ValueError:
                default_language = CharacterVoiceLanguage.ZH_CN
        instruction = build_voice_design_instruction(
            brief,
            default_language=default_language,
        )
        seed = _resolved_voice_generator_seed(requested_seed)
        service.finish_analysis(
            novel_id=novel_id,
            command_id=command_id,
            analysis=VoiceGeneratorAnalysis(
                character_version=workspace.character.version,
                character_catalog_version=workspace.character_catalog_version,
                workspace_digest=canonical_sha256(workspace_payload),
                brief=brief,
                instruction=instruction.text,
                model_evidence=evidence.as_dict(),
                language=instruction.language.value,
                seed=seed,
            ),
        )
    except CharacterWorkspaceError as error:
        service.fail_analysis(
            novel_id=novel_id,
            command_id=command_id,
            failure_code="CHARACTER_WORKSPACE_UNAVAILABLE",
        )
        if error.code in {
            CharacterWorkspaceErrorCode.CHARACTER_NOT_FOUND,
            CharacterWorkspaceErrorCode.TIMELINE_NOT_FOUND,
            CharacterWorkspaceErrorCode.CHARACTER_INSTANCE_NOT_FOUND,
        }:
            raise NarrationNotFound(str(error)) from error
        raise ValueError(str(error)) from error
    except (NovelModelEvidenceRejected, ModelVerificationError):
        service.fail_analysis(
            novel_id=novel_id,
            command_id=command_id,
            failure_code="CHARACTER_VOICE_MODEL_UNAVAILABLE",
        )
    except (CharacterVoiceMatchingError, ValueError):
        service.fail_analysis(
            novel_id=novel_id,
            command_id=command_id,
            failure_code="CHARACTER_VOICE_ANALYSIS_INVALID",
        )
    return service.get_resource(novel_id=novel_id, command_id=command_id)


@router.get(
    "/novels/{novel_id}/characters/{character_id}/voice-generator-commands",
    response_model=CharacterVoiceGeneratorCommandListResource,
)
def character_voice_generator_commands_index(
    novel_id: UUID,
    character_id: UUID,
) -> CharacterVoiceGeneratorCommandListResource:
    try:
        return _voice_generator_service(require_actionable=False).list_resources(
            novel_id=novel_id,
            character_id=character_id,
        )
    except Exception as error:
        _raise_service_error(error)
        raise


@router.post(
    "/novels/{novel_id}/characters/{character_id}/voice-generator-commands",
    response_model=CharacterVoiceGeneratorCommandResource,
    status_code=status.HTTP_202_ACCEPTED,
)
async def character_voice_generator_commands_create(
    novel_id: UUID,
    character_id: UUID,
    payload: CreateCharacterVoiceGeneratorCommandRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
        pattern=_IDEMPOTENCY_HEADER_PATTERN,
    ),
    ctx=Depends(get_novel_generation_ctx),
    configured_model: ModelAudit = Depends(get_novel_effective_model),
    model_probe: EffectiveModelProbe = Depends(get_novel_effective_model_probe),
    session: Session = Depends(get_session),
) -> CharacterVoiceGeneratorCommandResource:
    service = _voice_generator_service()
    request_hash = voice_generator_request_hash(
        novel_id=novel_id,
        character_id=character_id,
        timeline_id=payload.timeline_id,
        character_instance_id=payload.character_instance_id,
        expected_binding_version=payload.expected_binding_version,
        seed=payload.seed,
    )
    try:
        reservation = service.reserve(
            novel_id=novel_id,
            character_id=character_id,
            expected_binding_version=payload.expected_binding_version,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        return await _run_voice_generator_analysis(
            service=service,
            novel_id=novel_id,
            character_id=character_id,
            command_id=reservation.command_id,
            timeline_id=payload.timeline_id,
            character_instance_id=payload.character_instance_id,
            requested_seed=payload.seed,
            ctx=ctx,
            configured_model=configured_model,
            model_probe=model_probe,
            session=session,
        )
    except Exception as error:
        session.rollback()
        _raise_service_error(error)
        raise


@router.get(
    "/novels/{novel_id}/voice-generator-commands/{command_id}",
    response_model=CharacterVoiceGeneratorCommandResource,
)
def character_voice_generator_command_get(
    novel_id: UUID,
    command_id: UUID,
) -> CharacterVoiceGeneratorCommandResource:
    try:
        return _voice_generator_service(require_actionable=False).get_resource(
            novel_id=novel_id,
            command_id=command_id,
        )
    except Exception as error:
        _raise_service_error(error)
        raise


@router.post(
    "/novels/{novel_id}/voice-generator-commands/{command_id}/cancel",
    response_model=CharacterVoiceGeneratorCommandResource,
)
def character_voice_generator_command_cancel(
    novel_id: UUID,
    command_id: UUID,
) -> CharacterVoiceGeneratorCommandResource:
    try:
        service = _voice_generator_service(require_actionable=False)
        service.cancel(novel_id=novel_id, command_id=command_id)
        return service.get_resource(novel_id=novel_id, command_id=command_id)
    except Exception as error:
        _raise_service_error(error)
        raise


@router.post(
    "/novels/{novel_id}/voice-generator-commands/{command_id}/retry",
    response_model=CharacterVoiceGeneratorCommandResource,
    status_code=status.HTTP_202_ACCEPTED,
)
async def character_voice_generator_command_retry(
    novel_id: UUID,
    command_id: UUID,
    payload: RetryCharacterVoiceGeneratorCommandRequest,
    ctx=Depends(get_novel_generation_ctx),
    configured_model: ModelAudit = Depends(get_novel_effective_model),
    model_probe: EffectiveModelProbe = Depends(get_novel_effective_model_probe),
    session: Session = Depends(get_session),
) -> CharacterVoiceGeneratorCommandResource:
    service = _voice_generator_service()
    try:
        previous = service.get_resource(novel_id=novel_id, command_id=command_id)
        if not previous.retryable:
            raise InvalidNarrationState("VoiceGenerator command is not retryable")
        retry_key = f"voice-generator-retry:{command_id}"
        request_hash = voice_generator_request_hash(
            novel_id=novel_id,
            character_id=previous.character_id,
            timeline_id=None,
            character_instance_id=None,
            expected_binding_version=payload.expected_binding_version,
            seed=None,
        )
        reservation = service.reserve(
            novel_id=novel_id,
            character_id=previous.character_id,
            expected_binding_version=payload.expected_binding_version,
            idempotency_key=retry_key,
            request_hash=request_hash,
        )
        return await _run_voice_generator_analysis(
            service=service,
            novel_id=novel_id,
            character_id=previous.character_id,
            command_id=reservation.command_id,
            timeline_id=None,
            character_instance_id=None,
            requested_seed=None,
            ctx=ctx,
            configured_model=configured_model,
            model_probe=model_probe,
            session=session,
        )
    except Exception as error:
        session.rollback()
        _raise_service_error(error)
        raise


@router.put(
    "/novels/{novel_id}/voice-generator-commands/{command_id}/binding",
    response_model=CharacterVoiceGeneratorCommandResource,
)
def character_voice_generator_command_apply(
    novel_id: UUID,
    command_id: UUID,
    payload: ApplyCharacterVoiceGeneratorCommandRequest,
) -> CharacterVoiceGeneratorCommandResource:
    try:
        service = _voice_generator_service(require_actionable=False)
        service.apply(
            novel_id=novel_id,
            command_id=command_id,
            expected_binding_version=payload.expected_binding_version,
        )
        return service.get_resource(novel_id=novel_id, command_id=command_id)
    except Exception as error:
        _raise_service_error(error)
        raise


def _voice_preparation_service(require_actionable: bool = True):
    if require_actionable:
        _require_capability(wire.CapabilityKey.AUTOMATIC_CHARACTER_VOICE_GENERATION)
    service = current_voice_preparation_service()
    if service is None:
        _raise_feature_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "capability_unavailable",
            "人物声音自动准备服务当前不可用。",
            retryable=True,
            capability=wire.CapabilityKey.AUTOMATIC_CHARACTER_VOICE_GENERATION,
        )
    return service


def _prepare_generic_voice_pack_for_novel(novel_id: UUID) -> None:
    """Project an active pack or start its workspace build without blocking narration."""

    service = current_generic_voice_pack_service()
    if service is None:
        return
    try:
        if service.active_pack_ready():
            service.ensure_novel_projection(novel_id)
        else:
            service.build(idempotency_key=AUTOMATIC_GENERIC_PACK_BUILD_KEY)
    except Exception as error:
        # A chapter still has the existing same-language official fallback.
        # The durable pack resource exposes the failure for management/retry;
        # it must not turn an otherwise usable narration request into a gate.
        logger.warning(
            "generic voice pack preparation did not complete",
            exc_info=error,
            extra={"novel_id": str(novel_id)},
        )


async def _prepare_voice_generator_children(
    *,
    service,
    novel_id: UUID,
    command_id: UUID,
    ctx,
    configured_model: ModelAudit,
    model_probe: EffectiveModelProbe,
) -> None:
    """Analyze all frozen targets; heavy generation remains scheduler-serialized."""

    try:
        for _ in range(256):
            command = service.get_domain(novel_id=novel_id, command_id=command_id)
            candidate = None
            for item in command.items:
                if item.voice_generator_command_id is None:
                    continue
                child = service.voice_generator_service.get_resource(
                    novel_id=novel_id,
                    command_id=item.voice_generator_command_id,
                )
                if child.state == "queued":
                    candidate = (item.character_id, child.command_id)
                    break
            if candidate is None:
                if not any(item.state.value == "pending" for item in command.items):
                    break
                command = service.reserve_next_pending(
                    novel_id=novel_id,
                    command_id=command_id,
                )
                candidate = next(
                    (
                        (item.character_id, item.voice_generator_command_id)
                        for item in command.items
                        if item.voice_generator_command_id is not None
                        and service.voice_generator_service.get_resource(
                            novel_id=novel_id,
                            command_id=item.voice_generator_command_id,
                        ).state
                        == "queued"
                    ),
                    None,
                )
            if candidate is None:
                break
            character_id, child_id = candidate
            with Session(get_engine()) as analysis_session:
                try:
                    await _run_voice_generator_analysis(
                        service=service.voice_generator_service,
                        novel_id=novel_id,
                        character_id=character_id,
                        command_id=child_id,
                        timeline_id=None,
                        character_instance_id=None,
                        requested_seed=None,
                        ctx=ctx,
                        configured_model=configured_model,
                        model_probe=model_probe,
                        session=analysis_session,
                    )
                except Exception as error:
                    analysis_session.rollback()
                    logger.warning(
                        "automatic character voice analysis failed",
                        exc_info=error,
                        extra={
                            "voice_preparation_command_id": str(command_id),
                            "voice_generator_command_id": str(child_id),
                        },
                    )
            service.reconcile_once(novel_id=novel_id, command_id=command_id)
            wake_voice_preparation_reconciler()
    except Exception as error:
        # Durable child/parent state remains the recovery authority.  This
        # task must never turn an already accepted HTTP response into a lost
        # in-memory-only workflow.
        logger.warning(
            "voice preparation background analysis stopped",
            exc_info=error,
            extra={"voice_preparation_command_id": str(command_id)},
        )
    finally:
        wake_voice_preparation_reconciler()


@router.get(
    "/novels/{novel_id}/voice-preparation-commands",
    response_model=wire.VoicePreparationListResource,
)
def voice_preparation_commands_index(
    novel_id: UUID,
) -> wire.VoicePreparationListResource:
    try:
        return _voice_preparation_service(False).list_resources(novel_id=novel_id)
    except Exception as error:
        _raise_service_error(error)
        raise


@router.post(
    "/novels/{novel_id}/voice-preparation-commands",
    response_model=wire.VoicePreparationResource,
    status_code=status.HTTP_202_ACCEPTED,
)
def voice_preparation_command_create(
    novel_id: UUID,
    payload: wire.CreateVoicePreparationRequest,
    background_tasks: BackgroundTasks,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
        pattern=_IDEMPOTENCY_HEADER_PATTERN,
    ),
    ctx=Depends(get_novel_generation_ctx),
    configured_model: ModelAudit = Depends(get_novel_effective_model),
    model_probe: EffectiveModelProbe = Depends(get_novel_effective_model_probe),
) -> wire.VoicePreparationResource:
    service = _voice_preparation_service()
    try:
        _prepare_generic_voice_pack_for_novel(novel_id)
        reservation = service.create(
            VoicePreparationCreateRequest(
                novel_id=novel_id,
                document_id=payload.document_id,
                expected_draft_version=payload.expected_draft_version,
                expected_content_hash=payload.expected_content_hash,
                expected_settings_version=payload.expected_settings_version,
                idempotency_key=idempotency_key,
                actor="local-owner",
                explicit_requested_at=datetime.now(UTC),
                mode=payload.mode,
            )
        )
        background_tasks.add_task(
            _prepare_voice_generator_children,
            service=service,
            novel_id=novel_id,
            command_id=reservation.command_id,
            ctx=ctx,
            configured_model=configured_model,
            model_probe=model_probe,
        )
        wake_voice_preparation_reconciler()
        return service.get_resource(
            novel_id=novel_id, command_id=reservation.command_id
        )
    except Exception as error:
        _raise_service_error(error)
        raise


@router.get(
    "/novels/{novel_id}/voice-preparation-commands/{command_id}",
    response_model=wire.VoicePreparationResource,
)
def voice_preparation_command_get(
    novel_id: UUID,
    command_id: UUID,
) -> wire.VoicePreparationResource:
    try:
        return _voice_preparation_service(False).get_resource(
            novel_id=novel_id, command_id=command_id
        )
    except Exception as error:
        _raise_service_error(error)
        raise


@router.post(
    "/novels/{novel_id}/voice-preparation-commands/{command_id}/resume",
    response_model=wire.VoicePreparationResource,
    status_code=status.HTTP_202_ACCEPTED,
)
def voice_preparation_command_resume(
    novel_id: UUID,
    command_id: UUID,
    background_tasks: BackgroundTasks,
    ctx=Depends(get_novel_generation_ctx),
    configured_model: ModelAudit = Depends(get_novel_effective_model),
    model_probe: EffectiveModelProbe = Depends(get_novel_effective_model_probe),
) -> wire.VoicePreparationResource:
    """Reacquire public Agent context for an interrupted durable command."""

    service = _voice_preparation_service()
    try:
        current = service.get_resource(novel_id=novel_id, command_id=command_id)
        if not current.terminal:
            background_tasks.add_task(
                _prepare_voice_generator_children,
                service=service,
                novel_id=novel_id,
                command_id=command_id,
                ctx=ctx,
                configured_model=configured_model,
                model_probe=model_probe,
            )
            wake_voice_preparation_reconciler()
        return current
    except Exception as error:
        _raise_service_error(error)
        raise


@router.post(
    "/novels/{novel_id}/voice-preparation-commands/{command_id}/retry",
    response_model=wire.VoicePreparationResource,
    status_code=status.HTTP_202_ACCEPTED,
)
def voice_preparation_command_retry(
    novel_id: UUID,
    command_id: UUID,
    background_tasks: BackgroundTasks,
    ctx=Depends(get_novel_generation_ctx),
    configured_model: ModelAudit = Depends(get_novel_effective_model),
    model_probe: EffectiveModelProbe = Depends(get_novel_effective_model_probe),
) -> wire.VoicePreparationResource:
    service = _voice_preparation_service()
    try:
        reservation = service.retry(novel_id=novel_id, command_id=command_id)
        background_tasks.add_task(
            _prepare_voice_generator_children,
            service=service,
            novel_id=novel_id,
            command_id=reservation.command_id,
            ctx=ctx,
            configured_model=configured_model,
            model_probe=model_probe,
        )
        wake_voice_preparation_reconciler()
        return service.get_resource(
            novel_id=novel_id, command_id=reservation.command_id
        )
    except Exception as error:
        _raise_service_error(error)
        raise


@router.post(
    "/novels/{novel_id}/voice-preparation-commands/{command_id}/cancel",
    response_model=wire.VoicePreparationResource,
)
def voice_preparation_command_cancel(
    novel_id: UUID,
    command_id: UUID,
) -> wire.VoicePreparationResource:
    try:
        result = _voice_preparation_service(False).cancel(
            novel_id=novel_id, command_id=command_id
        )
        wake_voice_preparation_reconciler()
        return result
    except Exception as error:
        _raise_service_error(error)
        raise


def _generic_voice_pack_service(require_actionable: bool = True):
    if require_actionable:
        _require_capability(wire.CapabilityKey.GENERIC_VOICE_POOL)
    service = current_generic_voice_pack_service()
    if service is None:
        _raise_feature_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "capability_unavailable",
            "中文通用角色音色服务当前不可用。",
            retryable=True,
            capability=wire.CapabilityKey.GENERIC_VOICE_POOL,
        )
    return service


@router.get(
    "/voice-library/generic-pack",
    response_model=wire.GenericVoicePackLoadResource,
)
def generic_voice_pack_get() -> wire.GenericVoicePackLoadResource:
    try:
        return _generic_voice_pack_service(False).get_load_resource()
    except Exception as error:
        _raise_service_error(error)
        raise


@router.post(
    "/voice-library/generic-pack/build-commands",
    response_model=wire.GenericVoicePackLoadResource,
    status_code=status.HTTP_202_ACCEPTED,
)
def generic_voice_pack_build(
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
        pattern=_IDEMPOTENCY_HEADER_PATTERN,
    ),
) -> wire.GenericVoicePackLoadResource:
    try:
        return _generic_voice_pack_service().build(idempotency_key=idempotency_key)
    except Exception as error:
        _raise_service_error(error)
        raise


@router.get(
    "/voice-library/generic-pack/build-commands/{command_id}",
    response_model=wire.GenericVoicePackLoadResource,
)
def generic_voice_pack_build_get(
    command_id: UUID,
) -> wire.GenericVoicePackLoadResource:
    try:
        return _generic_voice_pack_service(False).get_build_resource(command_id)
    except Exception as error:
        _raise_service_error(error)
        raise


@router.post(
    "/voice-library/generic-pack/build-commands/{command_id}/retry",
    response_model=wire.GenericVoicePackLoadResource,
    status_code=status.HTTP_202_ACCEPTED,
)
def generic_voice_pack_build_retry(
    command_id: UUID,
) -> wire.GenericVoicePackLoadResource:
    try:
        return _generic_voice_pack_service().retry(command_id)
    except Exception as error:
        _raise_service_error(error)
        raise


@router.post(
    "/voice-library/generic-pack/build-commands/{command_id}/cancel",
    response_model=wire.GenericVoicePackLoadResource,
)
def generic_voice_pack_build_cancel(
    command_id: UUID,
) -> wire.GenericVoicePackLoadResource:
    try:
        return _generic_voice_pack_service(False).cancel(command_id)
    except Exception as error:
        _raise_service_error(error)
        raise


@router.post(
    "/voice-library/generic-pack/slots/{slot_key}/regenerate",
    response_model=wire.GenericVoicePackLoadResource,
    status_code=status.HTTP_202_ACCEPTED,
)
def generic_voice_pack_slot_regenerate(
    slot_key: str,
    payload: wire.RejectGenericVoiceSlotRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
        pattern=_IDEMPOTENCY_HEADER_PATTERN,
    ),
) -> wire.GenericVoicePackLoadResource:
    try:
        return _generic_voice_pack_service().regenerate(
            slot_key=slot_key,
            expected_pack_version_id=payload.expected_pack_version_id,
            idempotency_key=idempotency_key,
        )
    except Exception as error:
        _raise_service_error(error)
        raise


@router.post(
    "/voice-library/generic-pack/slots/{slot_key}/reject",
    response_model=wire.GenericVoicePackLoadResource,
)
def generic_voice_pack_slot_reject(
    slot_key: str,
    payload: wire.RejectGenericVoiceSlotRequest,
) -> wire.GenericVoicePackLoadResource:
    try:
        return _generic_voice_pack_service().reject(
            slot_key=slot_key,
            expected_pack_version_id=payload.expected_pack_version_id,
        )
    except Exception as error:
        _raise_service_error(error)
        raise


@router.get(
    "/novels/{novel_id}/character-cast-plans",
    response_model=wire.CharacterCastPlanListResource,
)
def character_cast_plans_index(
    novel_id: UUID,
) -> wire.CharacterCastPlanListResource:
    _require_capability(wire.CapabilityKey.CHARACTER_CAST_PLANNING)
    try:
        return _character_cast_plan_service().list_resources(novel_id=novel_id)
    except Exception as error:
        _raise_service_error(error)
        raise


@router.post(
    "/novels/{novel_id}/character-cast-plans",
    response_model=wire.CharacterCastPlanResource,
    status_code=status.HTTP_202_ACCEPTED,
)
def character_cast_plan_create(
    novel_id: UUID,
    payload: wire.CreateCharacterCastPlanRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
        pattern=_IDEMPOTENCY_HEADER_PATTERN,
    ),
) -> wire.CharacterCastPlanResource:
    _require_capability(wire.CapabilityKey.CHARACTER_CAST_PLANNING)
    try:
        service = _character_cast_plan_service()
        reservation = service.reserve(
            novel_id=novel_id,
            timeline_id=payload.timeline_id,
            idempotency_key=idempotency_key,
            request_hash=character_cast_plan_request_hash(
                novel_id=novel_id,
                timeline_id=payload.timeline_id,
                mode=payload.mode,
            ),
        )
        # A command containing only already-valid protected/official voices can
        # complete without an AI call.  Finalization is still transactional.
        return service.finalize_if_ready(
            novel_id=novel_id,
            command_id=reservation.command_id,
        )
    except Exception as error:
        _raise_service_error(error)
        raise


@router.get(
    "/novels/{novel_id}/character-cast-plans/{command_id}",
    response_model=wire.CharacterCastPlanResource,
)
def character_cast_plan_get(
    novel_id: UUID,
    command_id: UUID,
) -> wire.CharacterCastPlanResource:
    _require_capability(wire.CapabilityKey.CHARACTER_CAST_PLANNING)
    try:
        return _character_cast_plan_service().get_resource(
            novel_id=novel_id,
            command_id=command_id,
        )
    except Exception as error:
        _raise_service_error(error)
        raise


@router.post(
    "/novels/{novel_id}/character-cast-plans/{command_id}/advance",
    response_model=wire.CharacterCastPlanResource,
)
async def character_cast_plan_advance(
    novel_id: UUID,
    command_id: UUID,
    request: Request,
    ctx=Depends(get_novel_generation_ctx),
) -> wire.CharacterCastPlanResource:
    """Advance at most one target; the browser may safely call this repeatedly."""

    _require_capability(wire.CapabilityKey.CHARACTER_CAST_PLANNING)
    service = _character_cast_plan_service()
    try:
        lease = service.claim_next(novel_id=novel_id, command_id=command_id)
    except Exception as error:
        _raise_service_error(error)
        raise
    if lease is None:
        try:
            return service.finalize_if_ready(
                novel_id=novel_id, command_id=command_id
            )
        except Exception as error:
            _raise_service_error(error)
            raise

    try:
        # Resolve the model only after the target lease is durable.  A missing
        # or changing Agent model must become a recoverable target failure;
        # rejecting the request before ``claim_next`` would strand the active
        # command without progress or evidence.
        configured_model = await effective_model_audit(
            request.app,
            agent_id=NOVEL_AGENT_ID,
        )

        async def model_probe() -> ModelAudit:
            return await effective_model_audit(
                request.app,
                agent_id=NOVEL_AGENT_ID,
            )

        if lease.target_kind == "narrator":
            novel_payload = lease.prompt_payload.get("novel")
            if not isinstance(novel_payload, Mapping):
                raise ValueError("narrator cast evidence is malformed")
            prompt = build_narrator_voice_prompt(
                novel_payload,
                narration_language=lease.narration_language,
            )
        else:
            prompt = build_character_voice_prompt(dict(lease.prompt_payload))
        ensure_prompt_within_effective_limit(prompt, configured_model)
        started_monotonic = time.monotonic()
        reply = await ctx.chat(
            prompt,
            skill="character-craft",
            session_id=(
                f"novel-character-cast:{command_id}:{lease.target_key}:"
                f"{lease.attempt}"
            ),
        )
        evidence = await verify_novel_model_reply(
            reply,
            configured=configured_model,
            probe=model_probe,
            started_monotonic=started_monotonic,
        )
        parsed = parse_model_json(reply_final_text(reply))
        brief = (
            parse_narrator_voice_brief(parsed)
            if lease.target_kind == "narrator"
            else parse_character_voice_brief(parsed)
        )
        service.finish_analysis(
            novel_id=novel_id,
            command_id=command_id,
            item_id=lease.item_id,
            attempt=lease.attempt,
            fence_token=lease.fence_token,
            analysis=CharacterCastTargetAnalysis(
                workspace_digest=lease.workspace_digest,
                brief=brief,
                model_evidence=evidence.as_dict(),
            ),
        )
    except NovelModelEvidenceRejected:
        service.fail_analysis(
            novel_id=novel_id,
            command_id=command_id,
            item_id=lease.item_id,
            attempt=lease.attempt,
            fence_token=lease.fence_token,
            failure_code="CAST_PLAN_MODEL_REJECTED",
        )
    except ModelVerificationError:
        service.fail_analysis(
            novel_id=novel_id,
            command_id=command_id,
            item_id=lease.item_id,
            attempt=lease.attempt,
            fence_token=lease.fence_token,
            failure_code="CAST_PLAN_MODEL_UNAVAILABLE",
        )
    except CharacterVoiceMatchingError as error:
        service.fail_analysis(
            novel_id=novel_id,
            command_id=command_id,
            item_id=lease.item_id,
            attempt=lease.attempt,
            fence_token=lease.fence_token,
            failure_code=error.code,
        )
    except ValueError:
        service.fail_analysis(
            novel_id=novel_id,
            command_id=command_id,
            item_id=lease.item_id,
            attempt=lease.attempt,
            fence_token=lease.fence_token,
            failure_code="CAST_PLAN_ANALYSIS_INVALID",
        )
    except Exception as error:
        # Provider/network errors are target-local warnings.  Persist the
        # failure before returning so refresh never loses command progress.
        logger.warning(
            "character cast target analysis failed",
            exc_info=error,
            extra={"command_id": str(command_id)},
        )
        try:
            service.fail_analysis(
                novel_id=novel_id,
                command_id=command_id,
                item_id=lease.item_id,
                attempt=lease.attempt,
                fence_token=lease.fence_token,
                failure_code="CAST_PLAN_MODEL_UNAVAILABLE",
            )
        except Exception as persistence_error:
            _raise_service_error(persistence_error)
            raise

    try:
        return service.finalize_if_ready(
            novel_id=novel_id,
            command_id=command_id,
        )
    except Exception as error:
        _raise_service_error(error)
        raise


@router.post(
    "/novels/{novel_id}/character-cast-plans/{command_id}/retry",
    response_model=wire.CharacterCastPlanResource,
)
def character_cast_plan_retry(
    novel_id: UUID,
    command_id: UUID,
) -> wire.CharacterCastPlanResource:
    _require_capability(wire.CapabilityKey.CHARACTER_CAST_PLANNING)
    try:
        return _character_cast_plan_service().retry(
            novel_id=novel_id,
            command_id=command_id,
        )
    except Exception as error:
        _raise_service_error(error)
        raise


@router.post(
    "/novels/{novel_id}/characters/{character_id}/official-voice-match",
    response_model=CharacterVoiceMatchResource,
)
async def character_official_voice_match(
    novel_id: UUID,
    character_id: UUID,
    payload: CharacterVoiceMatchRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
        pattern=_IDEMPOTENCY_HEADER_PATTERN,
    ),
    ctx=Depends(get_novel_generation_ctx),
    configured_model: ModelAudit = Depends(get_novel_effective_model),
    model_probe: EffectiveModelProbe = Depends(get_novel_effective_model_probe),
    session: Session = Depends(get_session),
) -> CharacterVoiceMatchResource:
    _require_capability(wire.CapabilityKey.CHARACTER_VOICE_MATCHING)
    try:
        workspace = service_for_session(session).get_workspace(
            novel_id,
            character_id,
            timeline_id=payload.timeline_id,
            character_instance_id=payload.character_instance_id,
        )
        store = SqlAlchemyNarrationStore(session)
        settings = get_narration_settings(store, novel_id=novel_id)
        binding = get_character_voice_binding(
            store,
            novel_id=novel_id,
            character_id=character_id,
        )
        if binding.version != payload.expected_binding_version:
            raise NarrationCasConflict("character voice binding changed")
        workspace_payload = {
            "character": workspace.character.model_dump(mode="json"),
            "selected_instance": workspace.selected_instance.model_dump(mode="json"),
            "aliases": [item.model_dump(mode="json") for item in workspace.aliases],
            "relationships": [
                item.model_dump(mode="json") for item in workspace.relationships
            ],
            "projected_state": workspace.projected_state.model_dump(mode="json"),
        }
        # End the read transaction before the external model call.
        session.rollback()
        prompt = build_character_voice_prompt(workspace_payload)
        ensure_prompt_within_effective_limit(prompt, configured_model)
        started_monotonic = time.monotonic()
        reply = await ctx.chat(
            prompt,
            skill="character-craft",
            session_id=(
                f"novel-character-voice-match:{novel_id}:{character_id}:"
                f"{hashlib.sha256(idempotency_key.encode('utf-8')).hexdigest()}"
            ),
        )
        evidence = await verify_novel_model_reply(
            reply,
            configured=configured_model,
            probe=model_probe,
            started_monotonic=started_monotonic,
        )
        brief = parse_character_voice_brief(
            parse_model_json(reply_final_text(reply))
        )
        matched = match_official_voice(brief)
        selection_key = "character-match:" + hashlib.sha256(
            f"{novel_id}:{character_id}:{idempotency_key}".encode("utf-8")
        ).hexdigest()
        selection = OfficialVoiceSelectionService(
            lambda: Session(get_engine())
        )
        try:
            selected = selection.select_official_voice(
                novel_id=novel_id,
                request=wire.OfficialVoiceSelectionRequest(
                    preset_id=matched.selected_preset_id,
                    target_kind=wire.OfficialVoiceSelectionTargetKind.CHARACTER,
                    character_id=character_id,
                    expected_settings_version=settings.version,
                    expected_binding_version=payload.expected_binding_version,
                ),
                idempotency_key=selection_key,
            )
        except NarrationCasConflict:
            current = get_character_voice_binding(
                SqlAlchemyNarrationStore(session),
                novel_id=novel_id,
                character_id=character_id,
            )
            state = "ready_unapplied"
            still_current = False
        else:
            assert selected.current_character_binding is not None
            current = selected.current_character_binding
            still_current = selected.selection_still_current
            state = "ready_applied" if still_current else "ready_unapplied"
        return CharacterVoiceMatchResource(
            character_id=character_id,
            brief=brief.to_payload(),
            selected_preset_id=matched.selected_preset_id,
            score_milli=matched.score_milli,
            state=state,
            selection_still_current=still_current,
            current_character_binding=current,
            model_evidence=evidence.as_dict(),
        )
    except CharacterWorkspaceError as error:
        session.rollback()
        status_code = (
            status.HTTP_404_NOT_FOUND
            if error.code
            in {
                CharacterWorkspaceErrorCode.CHARACTER_NOT_FOUND,
                CharacterWorkspaceErrorCode.TIMELINE_NOT_FOUND,
                CharacterWorkspaceErrorCode.CHARACTER_INSTANCE_NOT_FOUND,
            }
            else status.HTTP_422_UNPROCESSABLE_CONTENT
        )
        _raise_feature_error(
            status_code,
            error.code.value,
            str(error),
        )
    except NovelModelEvidenceRejected as error:
        session.rollback()
        _raise_feature_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "CHARACTER_VOICE_MODEL_REJECTED",
            str(error),
            retryable=True,
        )
    except ModelVerificationError as error:
        session.rollback()
        _raise_feature_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "CHARACTER_VOICE_MODEL_UNAVAILABLE",
            str(error),
            retryable=True,
        )
    except CharacterVoiceMatchingError as error:
        session.rollback()
        _raise_feature_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            error.code,
            str(error),
            retryable=True,
        )
    except Exception as error:
        session.rollback()
        _raise_service_error(error)
        raise


__all__ = [
    "ApplyNanoVoiceExperimentRequest",
    "ApplyCharacterVoiceGeneratorCommandRequest",
    "CharacterVoiceGeneratorCommandListResource",
    "CharacterVoiceGeneratorCommandResource",
    "CharacterVoiceMatchRequest",
    "CharacterVoiceMatchResource",
    "CreateCharacterCastPlanRequest",
    "CharacterCastPlanResource",
    "CharacterCastPlanListResource",
    "ConfirmPrivateVoiceDeletionRequest",
    "CreateCharacterVoiceGeneratorCommandRequest",
    "CreateNanoVoiceExperimentRequest",
    "CreatePrivateVoiceDeletionRequest",
    "NanoVoiceExperimentListResource",
    "NanoVoiceExperimentResource",
    "PrivateVoiceDeletionRequestResource",
    "PrivateVoiceLifecycleResource",
    "RetryCharacterVoiceGeneratorCommandRequest",
    "router",
]
