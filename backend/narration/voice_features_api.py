"""Novel-scoped HTTP surface for the three Plan35 narration features."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import time
from typing import Awaitable, Callable
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from ..character_workspace.contracts import (
    CharacterWorkspaceError,
    CharacterWorkspaceErrorCode,
)
from ..character_workspace.service import service_for_session
from ..database import get_engine, get_session
from ..model_runtime import (
    ModelAudit,
    ModelVerificationError,
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
    CharacterVoiceMatchingError,
    match_official_voice,
    parse_character_voice_brief,
)
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
    current_nano_experiment_service,
    current_private_voice_deletion_service,
    current_private_voice_lifecycle_service,
    current_voice_product_port,
)
from .services import (
    IdempotencyConflict,
    InvalidNarrationState,
    NarrationCasConflict,
    NarrationNotFound,
    NarrationScopeMismatch,
    NarrationServiceError,
    SqlAlchemyNarrationStore,
)
from .storage import StorageError
from .voice_deletion import VoiceDeletionConflict, VoiceDeletionRequestSnapshot


router = APIRouter(tags=["narration-features-v2"])
_IDEMPOTENCY_HEADER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$"


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


def _character_voice_prompt(workspace_payload: dict[str, object]) -> str:
    evidence = json.dumps(
        workspace_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        "你正在为作者自有小说提取人物声音描述。只依据下面已保存的人物工作区 JSON，"
        "禁止用姓名、别名、年龄或身份刻板印象补全声音；缺失信息必须为 null。\n"
        "只返回一个裸 JSON 对象，不要解释，不要选择或输出任何 preset ID。字段必须且只能是："
        "schema_version='character-voice-brief/1'；language 为 zh-CN/en/ja-JP/null；"
        "presentation 为 masculine/feminine/androgynous/null；pitch、pace、energy 为 "
        "-2..2 的整数或 null；texture 为 clear/warm/airy/husky/firm/soft/bright/dark/null；"
        "evidence_fields 为字符串数组。每个非空维度必须有至少一个路径，格式为"
        "'<维度>:character.<字段>'、'<维度>:selected_instance.<字段>'、"
        "'<维度>:aliases[索引].<字段>'、'<维度>:relationships[索引].<字段>' 或"
        "'<维度>:projected_state.<字段>'；空维度不得声称证据。\n"
        f"人物工作区：{evidence}"
    )


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
        prompt = _character_voice_prompt(workspace_payload)
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
    "CharacterVoiceMatchRequest",
    "CharacterVoiceMatchResource",
    "ConfirmPrivateVoiceDeletionRequest",
    "CreateNanoVoiceExperimentRequest",
    "CreatePrivateVoiceDeletionRequest",
    "NanoVoiceExperimentListResource",
    "NanoVoiceExperimentResource",
    "PrivateVoiceDeletionRequestResource",
    "PrivateVoiceLifecycleResource",
    "router",
]
