"""Strict HTTP facade for the frozen T4 narration-production API."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from typing import Annotated, Callable, Final, Iterator, Literal, Protocol, TypeVar
from uuid import RFC_4122, UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.routing import APIRoute
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse, Response

from ..database import DatabaseNotConfigured, get_engine, get_session

from .edition_service import (
    NarrationEditionProjection,
    NarrationProductionPolicy,
    NarrationWorkflowProjection,
    SqlAlchemyNarrationWorkflowService,
    StartNarrationWorkflow,
)
from .failed_segment_retry import (
    FAILED_SEGMENT_RETRY_CONTRACT_VERSION,
    FailedSegmentRetryProjection,
    RetryFailedSegmentsCommand,
    RetryFailedSegmentsResult,
    project_failed_segment_retries,
    retry_failed_segments,
)
from .release_gate import require_narration_t4_http_access
from .document_state import (
    DocumentNarrationContextProjection,
    ExplicitEditionSwitchResult,
    project_document_narration_context,
    switch_document_narration_edition_explicitly,
)
from .services import (
    IdempotencyConflict,
    InvalidNarrationState,
    NarrationCasConflict,
    NarrationNotFound,
    NarrationScopeMismatch,
    NarrationServiceError,
    StaleNarrationInput,
    SqlAlchemyNarrationStore,
    VoiceRightsUnavailable,
)
NARRATION_PRODUCTION_API_VERSION: Final = "narration-production-api/1"
_IDEMPOTENCY_KEY_PATTERN: Final = r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$"
_SHA256_PATTERN: Final = r"^[a-f0-9]{64}$"


def _rfc4122_uuid(value: UUID) -> UUID:
    if value.variant != RFC_4122 or value.version not in {1, 2, 3, 4, 5}:
        raise ValueError("identity must be an RFC-4122 UUID v1-v5")
    return value


CanonicalUuid = Annotated[UUID, AfterValidator(_rfc4122_uuid)]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NarrationRequestIntent(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    ANALYZE_ONLY = "analyze_only"


class NarrationWorkflowState(str, Enum):
    CREATED = "created"
    ANALYZING = "analyzing"
    ANALYZED = "analyzed"
    REVIEW_REQUIRED = "review_required"
    QUEUED = "queued"
    RENDERING = "rendering"
    PARTIAL_READY = "partial_ready"
    READY = "ready"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    FAILED = "failed"


class NarrationEditionState(str, Enum):
    CREATED = "created"
    RENDERING = "rendering"
    PARTIAL_READY = "partial_ready"
    READY = "ready"
    UNAVAILABLE = "unavailable"


class CreateNarrationWorkflowRequest(_StrictModel):
    intent: NarrationRequestIntent
    expected_draft_version: int = Field(ge=1, strict=True)
    expected_content_hash: str = Field(pattern=_SHA256_PATTERN)
    expected_settings_version: int = Field(ge=1, strict=True)
    force_review: bool = Field(strict=True)


class NarrationWorkflowResource(_StrictModel):
    contract_version: Literal["narration-production-api/1"] = (
        NARRATION_PRODUCTION_API_VERSION
    )
    request_id: CanonicalUuid
    intent: NarrationRequestIntent
    request_version: int = Field(ge=1, strict=True)
    workflow_state: NarrationWorkflowState
    source_revision_id: CanonicalUuid
    source_content_hash: str = Field(pattern=_SHA256_PATTERN)
    settings_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    warning_count: int = Field(ge=0, strict=True)
    blocker_count: int = Field(ge=0, strict=True)
    script_version_id: CanonicalUuid | None = None
    edition_id: CanonicalUuid | None = None
    current_manifest_revision: int | None = Field(default=None, ge=1, strict=True)
    job_ids: list[CanonicalUuid]
    replayed: bool = Field(strict=True)

    @model_validator(mode="after")
    def validate_shape(self) -> "NarrationWorkflowResource":
        if len(self.job_ids) != len(set(self.job_ids)):
            raise ValueError("job_ids must be unique")
        if self.edition_id is None and self.current_manifest_revision is not None:
            raise ValueError("Manifest revision requires an Edition")
        if self.intent is NarrationRequestIntent.ANALYZE_ONLY and (
            self.edition_id is not None
            or self.current_manifest_revision is not None
            or self.job_ids
        ):
            raise ValueError("analyze_only cannot expose production resources")
        return self


class NarrationEditionVoiceIdentityResource(_StrictModel):
    profile_id: CanonicalUuid
    voice_version_id: CanonicalUuid
    display_name: str = Field(min_length=1, max_length=240)
    source_type: Literal["preset", "uploaded", "generated"] | None
    preset_id: str | None = Field(default=None, min_length=1, max_length=160)
    resolution_contract_version: Literal[
        "narration-edition-resolution/1",
        "narration-edition-resolution/2",
    ]
    legacy_fallback: bool = Field(strict=True)

    @model_validator(mode="after")
    def validate_identity_shape(self) -> "NarrationEditionVoiceIdentityResource":
        if self.legacy_fallback:
            if (
                self.resolution_contract_version != "narration-edition-resolution/1"
                or self.display_name != "旧版未保存名称"
                or self.source_type is not None
                or self.preset_id is not None
            ):
                raise ValueError("legacy Edition identity must use the stable fallback")
        elif (
            self.resolution_contract_version != "narration-edition-resolution/2"
            or self.source_type is None
            or ((self.source_type == "preset") != (self.preset_id is not None))
        ):
            raise ValueError("Edition v2 identity has an invalid source shape")
        return self


class NarrationEditionResource(_StrictModel):
    contract_version: Literal["narration-production-api/1"] = (
        NARRATION_PRODUCTION_API_VERSION
    )
    edition_id: CanonicalUuid
    request_id: CanonicalUuid
    novel_id: CanonicalUuid
    document_id: CanonicalUuid
    script_version_id: CanonicalUuid
    settings_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    edition_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    state: NarrationEditionState
    segment_count: int = Field(ge=1, strict=True)
    pending_segment_count: int = Field(ge=0, strict=True)
    queued_segment_count: int = Field(ge=0, strict=True)
    rendering_segment_count: int = Field(ge=0, strict=True)
    ready_segment_count: int = Field(ge=0, strict=True)
    failed_segment_count: int = Field(ge=0, strict=True)
    current_manifest_revision: int | None = Field(default=None, ge=1, strict=True)
    job_ids: list[CanonicalUuid]

    @model_validator(mode="after")
    def validate_counts(self) -> "NarrationEditionResource":
        if len(self.job_ids) != len(set(self.job_ids)):
            raise ValueError("job_ids must be unique")
        known = (
            self.pending_segment_count
            + self.queued_segment_count
            + self.rendering_segment_count
            + self.ready_segment_count
            + self.failed_segment_count
        )
        if known > self.segment_count:
            raise ValueError("Edition segment-state counts exceed segment_count")
        return self


class NarrationSourceSnapshotResource(_StrictModel):
    revision_id: CanonicalUuid
    content_hash: str = Field(pattern=_SHA256_PATTERN)
    matches_working_copy: bool = Field(strict=True)


class EditionHistoryItemResource(_StrictModel):
    edition_id: CanonicalUuid
    request_id: CanonicalUuid
    source_revision_id: CanonicalUuid
    source_content_hash: str = Field(pattern=_SHA256_PATTERN)
    edition_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    state: NarrationEditionState
    created_at: datetime | None = None
    manifest_revision: int | None = Field(default=None, ge=1, strict=True)
    manifest_etag: str | None = None
    ready_segment_count: int = Field(ge=0, strict=True)
    total_segment_count: int = Field(ge=1, strict=True)
    is_current: bool = Field(strict=True)
    source_status: Literal["current", "working_copy_diverged", "superseded"]
    rights_available: bool = Field(strict=True)
    playable: bool = Field(strict=True)
    default_start_ready: bool = Field(strict=True)
    resume_available: bool = Field(strict=True)
    switch_allowed: bool = Field(strict=True)


class DocumentEditionHistoryResource(_StrictModel):
    contract_version: Literal["narration-edition-history/1"]
    document_id: CanonicalUuid
    pointer_version: int = Field(ge=0, strict=True)
    current_edition_id: CanonicalUuid | None = None
    working_copy_content_hash: str = Field(pattern=_SHA256_PATTERN)
    working_copy_draft_version: int = Field(ge=1, strict=True)
    editions: list[EditionHistoryItemResource]


class DocumentNarrationContextResource(_StrictModel):
    contract_version: Literal["document-narration-context/1"]
    document_id: CanonicalUuid
    novel_id: CanonicalUuid
    pointer_version: int = Field(ge=0, strict=True)
    current_script_version_id: CanonicalUuid | None = None
    current_edition_id: CanonicalUuid | None = None
    active_edition_id: CanonicalUuid | None = None
    active_is_current: bool = Field(strict=True)
    working_copy_draft_version: int = Field(ge=1, strict=True)
    working_copy_content_hash: str = Field(pattern=_SHA256_PATTERN)
    source_snapshot: NarrationSourceSnapshotResource | None = None
    compatibility: Literal[
        "no_current_edition",
        "current",
        "working_copy_diverged",
        "superseded",
        "unavailable",
    ]
    source_notice_code: Literal[
        "NO_CURRENT_EDITION",
        "CURRENT_SOURCE_SNAPSHOT",
        "OLD_SOURCE_SNAPSHOT",
        "HISTORICAL_EDITION",
        "EDITION_UNAVAILABLE",
    ]
    editor_timeline_mode: Literal[
        "none",
        "exact_working_copy",
        "immutable_edition_only",
    ]
    old_draft_subtitle_required: bool = Field(strict=True)
    explicit_update_required: bool = Field(strict=True)
    can_request_update: bool = Field(strict=True)
    available_current_source_edition_ids: list[CanonicalUuid]
    edition_history: DocumentEditionHistoryResource


class SwitchNarrationEditionRequest(_StrictModel):
    target_edition_id: CanonicalUuid
    expected_version: int = Field(ge=0, strict=True)
    switch_mode: Literal["immediate", "next_playback"]
    start_segment_id: CanonicalUuid | None = None
    playback_rate_millis: int = Field(default=1000, ge=250, le=4000, strict=True)
    confirmed: bool = Field(strict=True)

    @model_validator(mode="after")
    def validate_start_mode(self) -> "SwitchNarrationEditionRequest":
        if self.confirmed is not True:
            raise ValueError("Edition switch requires exact explicit confirmation")
        if self.switch_mode == "next_playback" and self.start_segment_id is not None:
            raise ValueError("next_playback cannot name an immediate start segment")
        return self


class SwitchNarrationEditionResource(_StrictModel):
    contract_version: Literal["document-narration-context/1"] = (
        "document-narration-context/1"
    )
    document_id: CanonicalUuid
    current_edition_id: CanonicalUuid
    pointer_version: int = Field(ge=1, strict=True)
    switch_mode: Literal["immediate", "next_playback"]
    start_segment_id: CanonicalUuid | None = None
    manifest_revision: int = Field(ge=1, strict=True)
    playback_progress_id: CanonicalUuid | None = None


class RetryFailedSegmentsRequest(_StrictModel):
    segment_ids: list[CanonicalUuid] = Field(min_length=1, max_length=100)
    expected_request_version: int = Field(ge=1, strict=True)
    expected_manifest_revision: int | None = Field(default=None, ge=1, strict=True)

    @field_validator("segment_ids")
    @classmethod
    def validate_unique_segment_ids(
        cls, value: list[UUID]
    ) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("segment_ids must be unique")
        return value


class FailedSegmentRetryItemResource(_StrictModel):
    segment_id: CanonicalUuid
    ordinal: int = Field(ge=0, strict=True)
    failure_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,95}$")
    retryable: bool = Field(strict=True)
    retry_reason_code: str | None = Field(
        default=None,
        pattern=r"^[A-Z][A-Z0-9_]{0,95}$",
    )
    job_id: CanonicalUuid
    fanout_segment_ids: list[CanonicalUuid] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_fanout(self) -> "FailedSegmentRetryItemResource":
        if (
            len(self.fanout_segment_ids) != len(set(self.fanout_segment_ids))
            or self.segment_id not in self.fanout_segment_ids
            or (self.retryable and self.retry_reason_code is not None)
            or (not self.retryable and self.retry_reason_code is None)
        ):
            raise ValueError("failed segment retry fanout is inconsistent")
        return self


class FailedSegmentsResource(_StrictModel):
    contract_version: Literal["narration-failed-segment-retry/1"] = (
        FAILED_SEGMENT_RETRY_CONTRACT_VERSION
    )
    edition_id: CanonicalUuid
    request_id: CanonicalUuid
    request_version: int = Field(ge=1, strict=True)
    manifest_revision: int | None = Field(default=None, ge=1, strict=True)
    request_state: NarrationWorkflowState
    edition_state: NarrationEditionState
    items: list[FailedSegmentRetryItemResource]

    @model_validator(mode="after")
    def validate_items(self) -> "FailedSegmentsResource":
        if (
            len({item.segment_id for item in self.items}) != len(self.items)
            or len({item.ordinal for item in self.items}) != len(self.items)
        ):
            raise ValueError("failed segment retry items must be unique")
        return self


class FailedSegmentRetryCommandResource(_StrictModel):
    command_id: CanonicalUuid
    job_id: CanonicalUuid
    affected_segment_ids: list[CanonicalUuid] = Field(min_length=1)

    @field_validator("affected_segment_ids")
    @classmethod
    def validate_unique_affected_ids(
        cls, value: list[UUID]
    ) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("affected_segment_ids must be unique")
        return value


class RetryFailedSegmentsResource(_StrictModel):
    contract_version: Literal["narration-failed-segment-retry/1"] = (
        FAILED_SEGMENT_RETRY_CONTRACT_VERSION
    )
    edition_id: CanonicalUuid
    request_id: CanonicalUuid
    accepted_segment_ids: list[CanonicalUuid] = Field(min_length=1, max_length=100)
    affected_segment_ids: list[CanonicalUuid] = Field(min_length=1)
    commands: list[FailedSegmentRetryCommandResource] = Field(min_length=1)
    request_version: int = Field(ge=1, strict=True)
    request_state: NarrationWorkflowState
    edition_state: NarrationEditionState
    replayed: bool = Field(strict=True)

    @model_validator(mode="after")
    def validate_result(self) -> "RetryFailedSegmentsResource":
        accepted = set(self.accepted_segment_ids)
        affected = set(self.affected_segment_ids)
        command_affected = {
            segment_id
            for command in self.commands
            for segment_id in command.affected_segment_ids
        }
        if (
            len(accepted) != len(self.accepted_segment_ids)
            or len(affected) != len(self.affected_segment_ids)
            or not accepted.issubset(affected)
            or command_affected != affected
            or len({command.command_id for command in self.commands})
            != len(self.commands)
            or len({command.job_id for command in self.commands})
            != len(self.commands)
        ):
            raise ValueError("failed segment retry result is inconsistent")
        return self


class NarrationProductionErrorCode(str, Enum):
    REQUEST_VALIDATION_FAILED = "REQUEST_VALIDATION_FAILED"
    RESPONSE_CONTRACT_VIOLATION = "RESPONSE_CONTRACT_VIOLATION"
    BACKEND_NOT_INSTALLED = "NARRATION_PRODUCTION_BACKEND_NOT_INSTALLED"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    SCOPE_VIOLATION = "SCOPE_VIOLATION"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    INVALID_STATE = "INVALID_STATE"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    STALE_INPUT = "STALE_INPUT"
    VOICE_RIGHTS_UNAVAILABLE = "VOICE_RIGHTS_UNAVAILABLE"
    VALIDATION_FAILED = "VALIDATION_FAILED"


class NarrationProductionErrorDetail(_StrictModel):
    contract_version: Literal["narration-production-api/1"] = (
        NARRATION_PRODUCTION_API_VERSION
    )
    code: NarrationProductionErrorCode
    message: str = Field(min_length=1, max_length=400)
    retryable: bool = Field(strict=True)
    field: str | None = Field(default=None, max_length=160)
    current_version: int | None = Field(default=None, ge=1, strict=True)

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be blank")
        return value


class NarrationProductionOperation(str, Enum):
    START = "start"
    GET_REQUEST = "get_request"
    GET_EDITION = "get_edition"
    GET_EDITION_VOICE_IDENTITIES = "get_edition_voice_identities"
    GET_DOCUMENT_CONTEXT = "get_document_context"
    SWITCH_DOCUMENT_EDITION = "switch_document_edition"
    GET_FAILED_SEGMENTS = "get_failed_segments"
    RETRY_FAILED_SEGMENTS = "retry_failed_segments"


@dataclass(frozen=True, slots=True)
class NarrationProductionApiCommand:
    operation: NarrationProductionOperation
    document_id: UUID | None = None
    request_id: UUID | None = None
    edition_id: UUID | None = None
    active_edition_id: UUID | None = None
    payload: (
        CreateNarrationWorkflowRequest
        | SwitchNarrationEditionRequest
        | RetryFailedSegmentsRequest
        | None
    ) = None
    idempotency_key: str | None = None


class NarrationProductionApiBackend(Protocol):
    def dispatch(self, command: NarrationProductionApiCommand) -> object: ...


NarrationProductionBackendFactory = Callable[
    [Session], NarrationProductionApiBackend
]


class NarrationProductionApiFault(RuntimeError):
    def __init__(
        self,
        code: NarrationProductionErrorCode,
        message: str,
        *,
        retryable: bool = False,
        field: str | None = None,
        current_version: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.field = field
        self.current_version = current_version


NARRATION_PRODUCTION_ERROR_STATUS: Final[
    dict[NarrationProductionErrorCode, int]
] = {
    NarrationProductionErrorCode.REQUEST_VALIDATION_FAILED: status.HTTP_422_UNPROCESSABLE_CONTENT,
    NarrationProductionErrorCode.RESPONSE_CONTRACT_VIOLATION: status.HTTP_500_INTERNAL_SERVER_ERROR,
    NarrationProductionErrorCode.BACKEND_NOT_INSTALLED: status.HTTP_503_SERVICE_UNAVAILABLE,
    NarrationProductionErrorCode.STORAGE_UNAVAILABLE: status.HTTP_503_SERVICE_UNAVAILABLE,
    NarrationProductionErrorCode.RESOURCE_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    NarrationProductionErrorCode.SCOPE_VIOLATION: status.HTTP_404_NOT_FOUND,
    NarrationProductionErrorCode.VERSION_CONFLICT: status.HTTP_409_CONFLICT,
    NarrationProductionErrorCode.INVALID_STATE: status.HTTP_409_CONFLICT,
    NarrationProductionErrorCode.IDEMPOTENCY_CONFLICT: status.HTTP_409_CONFLICT,
    NarrationProductionErrorCode.STALE_INPUT: status.HTTP_409_CONFLICT,
    NarrationProductionErrorCode.VOICE_RIGHTS_UNAVAILABLE: status.HTTP_403_FORBIDDEN,
    NarrationProductionErrorCode.VALIDATION_FAILED: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


def _error_detail(
    fault: NarrationProductionApiFault,
) -> NarrationProductionErrorDetail:
    return NarrationProductionErrorDetail(
        code=fault.code,
        message=fault.message,
        retryable=fault.retryable,
        field=fault.field,
        current_version=fault.current_version,
    )


class _UnavailableBackend:
    def dispatch(self, command: NarrationProductionApiCommand) -> object:
        del command
        raise NarrationProductionApiFault(
            NarrationProductionErrorCode.BACKEND_NOT_INSTALLED,
            "朗读生产后端尚未完成应用入口接线。",
        )


class _StorageUnavailableBackend:
    def dispatch(self, command: NarrationProductionApiCommand) -> object:
        del command
        raise NarrationProductionApiFault(
            NarrationProductionErrorCode.STORAGE_UNAVAILABLE,
            "朗读生产数据库当前不可用。",
            retryable=True,
        )


class SqlAlchemyNarrationProductionBackend:
    """Thin HTTP adapter over the one authoritative workflow service."""

    def __init__(self, session: Session, policy: NarrationProductionPolicy) -> None:
        self._service = SqlAlchemyNarrationWorkflowService(session, policy)
        self._session = session

    def dispatch(self, command: NarrationProductionApiCommand) -> object:
        if type(command) is not NarrationProductionApiCommand:
            raise NarrationServiceError("command must be NarrationProductionApiCommand")
        try:
            if command.operation is NarrationProductionOperation.START:
                if (
                    command.document_id is None
                    or command.idempotency_key is None
                    or type(command.payload) is not CreateNarrationWorkflowRequest
                ):
                    raise NarrationServiceError("start narration command is incomplete")
                payload = command.payload
                result = self._service.start(
                    StartNarrationWorkflow(
                        document_id=command.document_id,
                        intent=payload.intent.value,
                        expected_draft_version=payload.expected_draft_version,
                        expected_content_hash=payload.expected_content_hash,
                        expected_settings_version=payload.expected_settings_version,
                        force_review=payload.force_review,
                        idempotency_key=command.idempotency_key,
                        explicitly_requested=True,
                    )
                )
                return _workflow_payload(result)
            if command.operation is NarrationProductionOperation.GET_REQUEST:
                if command.request_id is None:
                    raise NarrationServiceError("request identity is missing")
                return _workflow_payload(
                    self._service.get_request(command.request_id)
                )
            if command.operation is NarrationProductionOperation.GET_EDITION:
                if command.edition_id is None:
                    raise NarrationServiceError("Edition identity is missing")
                return _edition_payload(
                    self._service.get_edition(command.edition_id)
                )
            if command.operation is NarrationProductionOperation.GET_EDITION_VOICE_IDENTITIES:
                if command.edition_id is None:
                    raise NarrationServiceError("Edition identity is missing")
                return {
                    "contract_version": "narration-edition-voice-identities/1",
                    "edition_id": command.edition_id,
                    "items": [
                        asdict(item)
                        for item in self._service.get_edition_voice_identities(
                            command.edition_id
                        )
                    ],
                }
            if command.operation is NarrationProductionOperation.GET_FAILED_SEGMENTS:
                if command.edition_id is None:
                    raise NarrationServiceError("Edition identity is missing")
                if self._session.in_transaction():
                    raise RuntimeError(
                        "failed-segment projection received a pre-opened transaction"
                    )
                with self._session.begin():
                    result = project_failed_segment_retries(
                        SqlAlchemyNarrationStore(self._session),
                        edition_id=command.edition_id,
                    )
                return _failed_segments_payload(result)
            if command.operation is NarrationProductionOperation.RETRY_FAILED_SEGMENTS:
                if (
                    command.edition_id is None
                    or command.idempotency_key is None
                    or type(command.payload) is not RetryFailedSegmentsRequest
                ):
                    raise NarrationServiceError(
                        "failed-segment retry command is incomplete"
                    )
                if self._session.in_transaction():
                    raise RuntimeError(
                        "failed-segment retry received a pre-opened transaction"
                    )
                payload = command.payload
                with self._session.begin():
                    result = retry_failed_segments(
                        self._session,
                        RetryFailedSegmentsCommand(
                            edition_id=command.edition_id,
                            segment_ids=tuple(payload.segment_ids),
                            expected_request_version=payload.expected_request_version,
                            expected_manifest_revision=(
                                payload.expected_manifest_revision
                            ),
                            idempotency_key=command.idempotency_key,
                            actor="local-owner",
                        ),
                    )
                return _retry_failed_segments_payload(result)
            if command.operation is NarrationProductionOperation.GET_DOCUMENT_CONTEXT:
                if command.document_id is None:
                    raise NarrationServiceError("document identity is missing")
                if self._session.in_transaction():
                    raise RuntimeError(
                        "document narration context received a pre-opened transaction"
                    )
                with self._session.begin():
                    result = project_document_narration_context(
                        SqlAlchemyNarrationStore(self._session),
                        document_id=command.document_id,
                        active_edition_id=command.active_edition_id,
                        profile_id="default",
                    )
                return _document_context_payload(result)
            if command.operation is NarrationProductionOperation.SWITCH_DOCUMENT_EDITION:
                if (
                    command.document_id is None
                    or type(command.payload) is not SwitchNarrationEditionRequest
                ):
                    raise NarrationServiceError("Edition switch command is incomplete")
                if self._session.in_transaction():
                    raise RuntimeError(
                        "Edition switch received a pre-opened transaction"
                    )
                payload = command.payload
                with self._session.begin():
                    result = switch_document_narration_edition_explicitly(
                        SqlAlchemyNarrationStore(self._session),
                        document_id=command.document_id,
                        target_edition_id=payload.target_edition_id,
                        expected_pointer_version=payload.expected_version,
                        switch_mode=payload.switch_mode,
                        start_segment_id=payload.start_segment_id,
                        profile_id="default",
                        playback_rate_millis=payload.playback_rate_millis,
                        actor="local-owner",
                        confirmed=payload.confirmed,
                    )
                return _edition_switch_payload(result)
            raise InvalidNarrationState("unsupported narration production operation")
        except SQLAlchemyError as error:
            self._session.rollback()
            raise NarrationProductionApiFault(
                NarrationProductionErrorCode.STORAGE_UNAVAILABLE,
                "朗读生产数据库当前不可用。",
                retryable=True,
            ) from error


def _workflow_payload(result: NarrationWorkflowProjection) -> dict[str, object]:
    if type(result) is not NarrationWorkflowProjection:
        raise NarrationServiceError("workflow result has an invalid type")
    payload = asdict(result)
    payload["contract_version"] = NARRATION_PRODUCTION_API_VERSION
    payload["job_ids"] = list(result.job_ids)
    return payload


def _edition_payload(result: NarrationEditionProjection) -> dict[str, object]:
    if type(result) is not NarrationEditionProjection:
        raise NarrationServiceError("Edition result has an invalid type")
    payload = asdict(result)
    payload["contract_version"] = NARRATION_PRODUCTION_API_VERSION
    payload["job_ids"] = list(result.job_ids)
    return payload


def _document_context_payload(
    result: DocumentNarrationContextProjection,
) -> dict[str, object]:
    if type(result) is not DocumentNarrationContextProjection:
        raise NarrationServiceError("document narration context has an invalid type")
    payload = asdict(result)
    payload["available_current_source_edition_ids"] = list(
        result.available_current_source_edition_ids
    )
    payload["edition_history"]["editions"] = [  # type: ignore[index]
        asdict(item) for item in result.edition_history.editions
    ]
    return payload


def _edition_switch_payload(
    result: ExplicitEditionSwitchResult,
) -> dict[str, object]:
    if type(result) is not ExplicitEditionSwitchResult:
        raise NarrationServiceError("Edition switch result has an invalid type")
    payload = asdict(result)
    payload["contract_version"] = "document-narration-context/1"
    return payload


def _failed_segments_payload(
    result: FailedSegmentRetryProjection,
) -> dict[str, object]:
    if type(result) is not FailedSegmentRetryProjection:
        raise NarrationServiceError("failed-segment projection has an invalid type")
    payload = asdict(result)
    payload["items"] = [
        {
            **asdict(item),
            "fanout_segment_ids": list(item.fanout_segment_ids),
        }
        for item in result.items
    ]
    return payload


def _retry_failed_segments_payload(
    result: RetryFailedSegmentsResult,
) -> dict[str, object]:
    if type(result) is not RetryFailedSegmentsResult:
        raise NarrationServiceError("failed-segment retry result has an invalid type")
    payload = asdict(result)
    payload["accepted_segment_ids"] = list(result.accepted_segment_ids)
    payload["affected_segment_ids"] = list(result.affected_segment_ids)
    payload["commands"] = [
        {
            **asdict(command),
            "affected_segment_ids": list(command.affected_segment_ids),
        }
        for command in result.commands
    ]
    return payload


def build_narration_production_backend_factory(
    policy: NarrationProductionPolicy,
) -> NarrationProductionBackendFactory:
    if type(policy) is not NarrationProductionPolicy:
        raise TypeError("production backend factory requires a frozen policy")

    def factory(session: Session) -> NarrationProductionApiBackend:
        return SqlAlchemyNarrationProductionBackend(session, policy)

    return factory


_backend_factory: NarrationProductionBackendFactory | None = None


def install_narration_production_backend_factory(
    factory: NarrationProductionBackendFactory,
) -> None:
    global _backend_factory
    if not callable(factory):
        raise TypeError("narration production backend factory must be callable")
    if _backend_factory is not None and _backend_factory is not factory:
        raise RuntimeError("narration production backend factory is already installed")
    _backend_factory = factory


def uninstall_narration_production_backend_factory(
    factory: NarrationProductionBackendFactory | None = None,
) -> None:
    global _backend_factory
    if factory is not None and _backend_factory is not None and _backend_factory is not factory:
        raise RuntimeError("refusing to remove another narration production backend")
    _backend_factory = None


def get_narration_production_backend() -> Iterator[NarrationProductionApiBackend]:
    factory = _backend_factory
    if factory is None:
        yield _UnavailableBackend()
        return
    session_dependency = get_session()
    try:
        session = next(session_dependency)
    except DatabaseNotConfigured:
        yield _StorageUnavailableBackend()
        return
    try:
        yield factory(session)
    finally:
        session_dependency.close()


def _field_from_validation(error: RequestValidationError) -> str | None:
    errors = error.errors()
    if not errors:
        return None
    parts = [
        str(item).replace("-", "_").lower()
        for item in errors[0].get("loc", ())
        if isinstance(item, str) and item not in {"body", "path", "header", "query"}
    ]
    candidate = ".".join(parts)
    return candidate if candidate and len(candidate) <= 160 else None


def _error_response(fault: NarrationProductionApiFault) -> JSONResponse:
    return JSONResponse(
        status_code=NARRATION_PRODUCTION_ERROR_STATUS[fault.code],
        content={"detail": _error_detail(fault).model_dump(mode="json")},
        headers={"Cache-Control": "no-store"},
    )


class NarrationProductionContractRoute(APIRoute):
    def get_route_handler(self):  # type: ignore[no-untyped-def]
        original = super().get_route_handler()

        async def route_handler(request: Request) -> Response:
            try:
                response = await original(request)
            except RequestValidationError as error:
                return _error_response(
                    NarrationProductionApiFault(
                        NarrationProductionErrorCode.REQUEST_VALIDATION_FAILED,
                        "请求字段不符合朗读生产契约。",
                        field=_field_from_validation(error),
                    )
                )
            except ResponseValidationError:
                return _error_response(
                    NarrationProductionApiFault(
                        NarrationProductionErrorCode.RESPONSE_CONTRACT_VIOLATION,
                        "朗读生产服务返回了不兼容的数据。",
                    )
                )
            except HTTPException as error:
                response = JSONResponse(
                    status_code=error.status_code,
                    content={"detail": jsonable_encoder(error.detail)},
                    headers=error.headers,
                )
            response.headers.setdefault("Cache-Control", "no-store")
            return response

        return route_handler


router = APIRouter(
    route_class=NarrationProductionContractRoute,
    dependencies=[Depends(require_narration_t4_http_access)],
)
_ResponseModel = TypeVar("_ResponseModel", bound=BaseModel)


def _fault_from_service(error: NarrationServiceError) -> NarrationProductionApiFault:
    if isinstance(error, NarrationNotFound):
        return NarrationProductionApiFault(
            NarrationProductionErrorCode.RESOURCE_NOT_FOUND,
            "找不到请求的朗读生产资源。",
        )
    if isinstance(error, NarrationScopeMismatch):
        return NarrationProductionApiFault(
            NarrationProductionErrorCode.SCOPE_VIOLATION,
            "找不到请求的朗读生产资源。",
        )
    if isinstance(error, NarrationCasConflict):
        return NarrationProductionApiFault(
            NarrationProductionErrorCode.VERSION_CONFLICT,
            "正文版本已经变化，请保存并刷新后重试。",
        )
    if isinstance(error, IdempotencyConflict):
        return NarrationProductionApiFault(
            NarrationProductionErrorCode.IDEMPOTENCY_CONFLICT,
            "幂等键已用于另一份朗读请求。",
        )
    if isinstance(error, StaleNarrationInput):
        return NarrationProductionApiFault(
            NarrationProductionErrorCode.STALE_INPUT,
            "正文、设置或脚本快照已经变化。",
        )
    if isinstance(error, VoiceRightsUnavailable) or (
        isinstance(error, InvalidNarrationState)
        and str(error)
        == "failed segment retry is unavailable: VOICE_RIGHTS_UNAVAILABLE"
    ):
        return NarrationProductionApiFault(
            NarrationProductionErrorCode.VOICE_RIGHTS_UNAVAILABLE,
            "当前音色版本不可用于新的朗读合成，请刷新音色绑定后重试。",
        )
    if isinstance(error, InvalidNarrationState):
        return NarrationProductionApiFault(
            NarrationProductionErrorCode.INVALID_STATE,
            "当前朗读状态不允许此操作。",
        )
    return NarrationProductionApiFault(
        NarrationProductionErrorCode.VALIDATION_FAILED,
        "朗读生产请求未通过领域校验。",
    )


def _run(
    backend: NarrationProductionApiBackend,
    command: NarrationProductionApiCommand,
    response_model: type[_ResponseModel],
) -> _ResponseModel:
    try:
        return response_model.model_validate(backend.dispatch(command))
    except NarrationProductionApiFault as fault:
        raise HTTPException(
            status_code=NARRATION_PRODUCTION_ERROR_STATUS[fault.code],
            detail=_error_detail(fault).model_dump(mode="json"),
        ) from fault
    except NarrationServiceError as error:
        fault = _fault_from_service(error)
        raise HTTPException(
            status_code=NARRATION_PRODUCTION_ERROR_STATUS[fault.code],
            detail=_error_detail(fault).model_dump(mode="json"),
        ) from error
    except ValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=NarrationProductionErrorDetail(
                code=NarrationProductionErrorCode.RESPONSE_CONTRACT_VIOLATION,
                message="朗读生产服务返回了不兼容的数据。",
                retryable=False,
            ).model_dump(mode="json"),
        ) from error


@router.post(
    "/documents/{document_id}/narration-requests",
    response_model=NarrationWorkflowResource,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_narration_request(
    document_id: CanonicalUuid,
    payload: CreateNarrationWorkflowRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
        pattern=_IDEMPOTENCY_KEY_PATTERN,
    ),
    backend: NarrationProductionApiBackend = Depends(
        get_narration_production_backend
    ),
) -> NarrationWorkflowResource:
    return _run(
        backend,
        NarrationProductionApiCommand(
            operation=NarrationProductionOperation.START,
            document_id=document_id,
            payload=payload,
            idempotency_key=idempotency_key,
        ),
        NarrationWorkflowResource,
    )


@router.get(
    "/narration-requests/{request_id}",
    response_model=NarrationWorkflowResource,
)
def get_narration_request(
    request_id: CanonicalUuid,
    backend: NarrationProductionApiBackend = Depends(
        get_narration_production_backend
    ),
) -> NarrationWorkflowResource:
    resource = _run(
        backend,
        NarrationProductionApiCommand(
            operation=NarrationProductionOperation.GET_REQUEST,
            request_id=request_id,
        ),
        NarrationWorkflowResource,
    )
    if resource.request_id != request_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=NarrationProductionErrorDetail(
                code=NarrationProductionErrorCode.RESPONSE_CONTRACT_VIOLATION,
                message="朗读生产服务返回了不兼容的数据。",
                retryable=False,
            ).model_dump(mode="json"),
        )
    return resource


@router.get(
    "/narration-editions/{edition_id}",
    response_model=NarrationEditionResource,
)
def get_narration_edition(
    edition_id: CanonicalUuid,
    backend: NarrationProductionApiBackend = Depends(
        get_narration_production_backend
    ),
) -> NarrationEditionResource:
    resource = _run(
        backend,
        NarrationProductionApiCommand(
            operation=NarrationProductionOperation.GET_EDITION,
            edition_id=edition_id,
        ),
        NarrationEditionResource,
    )
    if resource.edition_id != edition_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=NarrationProductionErrorDetail(
                code=NarrationProductionErrorCode.RESPONSE_CONTRACT_VIOLATION,
                message="朗读生产服务返回了不兼容的数据。",
                retryable=False,
            ).model_dump(mode="json"),
        )
    return resource


class NarrationEditionVoiceIdentitiesResource(_StrictModel):
    contract_version: Literal["narration-edition-voice-identities/1"]
    edition_id: CanonicalUuid
    items: list[NarrationEditionVoiceIdentityResource]

    @model_validator(mode="after")
    def validate_items(self) -> "NarrationEditionVoiceIdentitiesResource":
        versions = [item.voice_version_id for item in self.items]
        if not self.items or len(versions) != len(set(versions)):
            raise ValueError("voice identities must be non-empty and unique by version")
        return self


@router.get(
    "/narration-editions/{edition_id}/voice-identities",
    response_model=NarrationEditionVoiceIdentitiesResource,
)
def get_narration_edition_voice_identities(
    edition_id: CanonicalUuid,
    backend: NarrationProductionApiBackend = Depends(
        get_narration_production_backend
    ),
) -> NarrationEditionVoiceIdentitiesResource:
    resource = _run(
        backend,
        NarrationProductionApiCommand(
            operation=NarrationProductionOperation.GET_EDITION_VOICE_IDENTITIES,
            edition_id=edition_id,
        ),
        NarrationEditionVoiceIdentitiesResource,
    )
    if resource.edition_id != edition_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=NarrationProductionErrorDetail(
                code=NarrationProductionErrorCode.RESPONSE_CONTRACT_VIOLATION,
                message="朗读生产服务返回了不兼容的数据。",
                retryable=False,
            ).model_dump(mode="json"),
        )
    return resource


@router.get(
    "/narration-editions/{edition_id}/failed-segments",
    response_model=FailedSegmentsResource,
)
def get_failed_narration_segments(
    edition_id: CanonicalUuid,
    backend: NarrationProductionApiBackend = Depends(
        get_narration_production_backend
    ),
) -> FailedSegmentsResource:
    resource = _run(
        backend,
        NarrationProductionApiCommand(
            operation=NarrationProductionOperation.GET_FAILED_SEGMENTS,
            edition_id=edition_id,
        ),
        FailedSegmentsResource,
    )
    if resource.edition_id != edition_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=NarrationProductionErrorDetail(
                code=NarrationProductionErrorCode.RESPONSE_CONTRACT_VIOLATION,
                message="失败句段服务返回了不兼容的朗读版本。",
                retryable=False,
            ).model_dump(mode="json"),
        )
    return resource


@router.post(
    "/narration-editions/{edition_id}/retry-failed-segments",
    response_model=RetryFailedSegmentsResource,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_failed_narration_segments(
    edition_id: CanonicalUuid,
    payload: RetryFailedSegmentsRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
        pattern=_IDEMPOTENCY_KEY_PATTERN,
    ),
    backend: NarrationProductionApiBackend = Depends(
        get_narration_production_backend
    ),
) -> RetryFailedSegmentsResource:
    resource = _run(
        backend,
        NarrationProductionApiCommand(
            operation=NarrationProductionOperation.RETRY_FAILED_SEGMENTS,
            edition_id=edition_id,
            payload=payload,
            idempotency_key=idempotency_key,
        ),
        RetryFailedSegmentsResource,
    )
    if (
        resource.edition_id != edition_id
        or set(resource.accepted_segment_ids) != set(payload.segment_ids)
    ):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=NarrationProductionErrorDetail(
                code=NarrationProductionErrorCode.RESPONSE_CONTRACT_VIOLATION,
                message="失败句段重试返回了不兼容的选择结果。",
                retryable=False,
            ).model_dump(mode="json"),
        )
    return resource


@router.get(
    "/documents/{document_id}/narration-playback-context",
    response_model=DocumentNarrationContextResource,
)
def get_document_narration_context(
    document_id: CanonicalUuid,
    active_edition_id: CanonicalUuid | None = Query(default=None),
    backend: NarrationProductionApiBackend = Depends(
        get_narration_production_backend
    ),
) -> DocumentNarrationContextResource:
    resource = _run(
        backend,
        NarrationProductionApiCommand(
            operation=NarrationProductionOperation.GET_DOCUMENT_CONTEXT,
            document_id=document_id,
            active_edition_id=active_edition_id,
        ),
        DocumentNarrationContextResource,
    )
    history = resource.edition_history
    edition_by_id = {item.edition_id: item for item in history.editions}
    current_flags = {
        item.edition_id for item in history.editions if item.is_current
    }
    expected_current_flags = (
        {resource.current_edition_id}
        if resource.current_edition_id is not None
        else set()
    )
    active = (
        edition_by_id.get(resource.active_edition_id)
        if resource.active_edition_id is not None
        else None
    )
    source = resource.source_snapshot
    if (
        resource.document_id != document_id
        or history.document_id != document_id
        or history.pointer_version != resource.pointer_version
        or history.current_edition_id != resource.current_edition_id
        or history.working_copy_content_hash != resource.working_copy_content_hash
        or history.working_copy_draft_version != resource.working_copy_draft_version
        or current_flags != expected_current_flags
        or (
            active_edition_id is not None
            and resource.active_edition_id != active_edition_id
        )
        or (
            resource.active_edition_id is not None
            and active is None
        )
        or resource.active_is_current
        is not (
            resource.active_edition_id is not None
            and resource.active_edition_id == resource.current_edition_id
        )
        or (
            active is None
            and source is not None
        )
        or (
            active is not None
            and (
                source is None
                or source.revision_id != active.source_revision_id
                or source.content_hash != active.source_content_hash
                or source.matches_working_copy
                is not (
                    active.source_content_hash
                    == resource.working_copy_content_hash
                )
            )
        )
        or any(
            edition_id not in edition_by_id
            for edition_id in resource.available_current_source_edition_ids
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=NarrationProductionErrorDetail(
                code=NarrationProductionErrorCode.RESPONSE_CONTRACT_VIOLATION,
                message="朗读上下文返回了不兼容的文档或版本关系。",
                retryable=False,
            ).model_dump(mode="json"),
        )
    return resource


@router.put(
    "/documents/{document_id}/current-narration-edition",
    response_model=SwitchNarrationEditionResource,
)
def switch_document_narration_edition(
    document_id: CanonicalUuid,
    payload: SwitchNarrationEditionRequest,
    backend: NarrationProductionApiBackend = Depends(
        get_narration_production_backend
    ),
) -> SwitchNarrationEditionResource:
    resource = _run(
        backend,
        NarrationProductionApiCommand(
            operation=NarrationProductionOperation.SWITCH_DOCUMENT_EDITION,
            document_id=document_id,
            payload=payload,
        ),
        SwitchNarrationEditionResource,
    )
    if (
        resource.document_id != document_id
        or resource.current_edition_id != payload.target_edition_id
        or resource.pointer_version != payload.expected_version + 1
        or resource.switch_mode != payload.switch_mode
        or (
            payload.start_segment_id is not None
            and resource.start_segment_id != payload.start_segment_id
        )
        or (
            payload.switch_mode == "next_playback"
            and resource.start_segment_id is not None
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=NarrationProductionErrorDetail(
                code=NarrationProductionErrorCode.RESPONSE_CONTRACT_VIOLATION,
                message="朗读版本切换返回了不兼容的文档或版本关系。",
                retryable=False,
            ).model_dump(mode="json"),
        )
    return resource


__all__ = [
    "CreateNarrationWorkflowRequest",
    "DocumentNarrationContextResource",
    "DocumentEditionHistoryResource",
    "EditionHistoryItemResource",
    "FailedSegmentRetryCommandResource",
    "FailedSegmentRetryItemResource",
    "FailedSegmentsResource",
    "NARRATION_PRODUCTION_API_VERSION",
    "NarrationEditionResource",
    "NarrationProductionApiBackend",
    "NarrationProductionApiCommand",
    "NarrationProductionApiFault",
    "NarrationProductionBackendFactory",
    "NarrationProductionErrorCode",
    "NarrationProductionErrorDetail",
    "NarrationProductionOperation",
    "NarrationWorkflowResource",
    "RetryFailedSegmentsRequest",
    "RetryFailedSegmentsResource",
    "SqlAlchemyNarrationProductionBackend",
    "SwitchNarrationEditionRequest",
    "SwitchNarrationEditionResource",
    "build_narration_production_backend_factory",
    "get_narration_production_backend",
    "install_narration_production_backend_factory",
    "router",
    "uninstall_narration_production_backend_factory",
]
