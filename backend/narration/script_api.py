"""Strict, fail-closed HTTP facade for narration script review.

T3-H freezes the wire contract and routes only.  T3-GATE installs the scoped
backend adapter that delegates to the shared narration request/script domain
services.  Until then every route returns a truthful 503 and performs no
database, model, worker, or media operation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import unicodedata
from typing import Callable, Final, Iterator, Literal, Protocol, TypeVar
from uuid import RFC_4122, UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse, Response

from ..database import DatabaseNotConfigured, get_session

from .contracts import (
    NARRATION_REVIEW_TAXONOMY_VERSION,
    ReviewIssueSeverity,
    UnknownTaxonomyCodeError,
    issue_severity,
)
from .services import (
    IdempotencyConflict,
    InvalidNarrationState,
    NarrationCasConflict,
    NarrationNotFound,
    NarrationScopeMismatch,
    NarrationServiceError,
    StaleNarrationInput,
)
from .script_contracts import SegmentKind
from .release_gate import require_narration_t4_http_access


NARRATION_SCRIPT_REVIEW_API_VERSION: Final = "narration-script-review-api/1"
_IDEMPOTENCY_KEY_PATTERN: Final = r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$"
_SHA256_PATTERN: Final = r"^[a-f0-9]{64}$"
_SAFE_CODE_PATTERN: Final = r"^[A-Z][A-Z0-9_]{0,95}$"
_SOURCE_BLOCK_KEY_PATTERN: Final = r"^sb1_[a-f0-9]{64}$"


class _StrictModel(BaseModel):
    # Authoritative source/spoken text is byte-significant.  Request-only human
    # fields use explicit non-blank validators instead of global normalization.
    model_config = ConfigDict(extra="forbid")


def _non_blank(value: str, *, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank")
    return value


def _rfc4122_uuid(value: UUID, *, field_name: str) -> UUID:
    if value.variant != RFC_4122 or value.version not in {1, 2, 3, 4, 5}:
        raise ValueError(f"{field_name} must be an RFC-4122 UUID v1-v5")
    return value


class ScriptApiErrorCode(str, Enum):
    REQUEST_VALIDATION_FAILED = "REQUEST_VALIDATION_FAILED"
    RESPONSE_CONTRACT_VIOLATION = "RESPONSE_CONTRACT_VIOLATION"
    SCRIPT_BACKEND_NOT_INSTALLED = "SCRIPT_BACKEND_NOT_INSTALLED"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    SCOPE_VIOLATION = "SCOPE_VIOLATION"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    INVALID_STATE = "INVALID_STATE"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    STALE_INPUT = "STALE_INPUT"
    VALIDATION_FAILED = "VALIDATION_FAILED"


class ScriptState(str, Enum):
    DRAFT = "draft"
    ANALYZING = "analyzing"
    ANALYZED = "analyzed"
    REVIEW_REQUIRED = "review_required"
    APPROVED = "approved"
    FAILED = "failed"


class ScriptReviewPolicy(str, Enum):
    BLOCKERS_ONLY = "blockers_only"
    ALWAYS_REVIEW = "always_review"


class ScriptSourceStatus(str, Enum):
    CURRENT = "current"
    WORKING_COPY_DIVERGED = "working_copy_diverged"
    SUPERSEDED = "superseded"


class ScriptReviewAction(str, Enum):
    APPROVE = "approve"
    EDIT_SEGMENT = "edit_segment"
    REANALYZE_SEGMENTS = "reanalyze_segments"
    CONTINUE_SNAPSHOT = "continue_snapshot"
    REANALYZE_LATEST = "reanalyze_latest"


class ScriptSpeakerKind(str, Enum):
    NARRATOR = "narrator"
    CHARACTER = "character"
    ANONYMOUS = "anonymous"
    GROUP = "group"
    UNKNOWN = "unknown"


class ScriptCastingState(str, Enum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"


class ScriptConfidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class ScriptApiErrorDetail(_StrictModel):
    contract_version: Literal["narration-script-review-api/1"] = (
        NARRATION_SCRIPT_REVIEW_API_VERSION
    )
    code: ScriptApiErrorCode
    message: str = Field(min_length=1, max_length=400)
    retryable: bool = Field(strict=True)
    field: str | None = Field(default=None, max_length=160)
    current_version: int | None = Field(default=None, ge=1, strict=True)

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        return _non_blank(value, field_name="message")


class ScriptReviewIssueResource(_StrictModel):
    taxonomy_version: Literal["narration-review-taxonomy/1"] = (
        NARRATION_REVIEW_TAXONOMY_VERSION
    )
    code: str = Field(pattern=_SAFE_CODE_PATTERN)
    severity: Literal["warning", "blocker"]
    segment_id: UUID | None = None
    evidence_summary: str | None = Field(default=None, min_length=1, max_length=500)
    evidence_digest: str | None = Field(default=None, pattern=_SHA256_PATTERN)

    @field_validator("segment_id")
    @classmethod
    def validate_segment_id(cls, value: UUID | None) -> UUID | None:
        if value is None:
            return None
        return _rfc4122_uuid(value, field_name="issue segment_id")

    @field_validator("evidence_summary")
    @classmethod
    def validate_evidence_summary(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _non_blank(value, field_name="evidence_summary")

    @model_validator(mode="after")
    def validate_server_severity(self) -> "ScriptReviewIssueResource":
        try:
            expected = issue_severity(self.code)
        except UnknownTaxonomyCodeError as error:
            raise ValueError(str(error)) from error
        if self.severity != expected.value:
            raise ValueError("review issue severity differs from frozen taxonomy")
        if self.evidence_summary is not None and self.evidence_digest is None:
            raise ValueError("evidence summary requires an irreversible digest")
        return self


class ScriptReviewSegmentResource(_StrictModel):
    segment_id: UUID
    ordinal: int = Field(ge=0, strict=True)
    segment_kind: SegmentKind
    source_block_key: str = Field(pattern=_SOURCE_BLOCK_KEY_PATTERN)
    source_start_utf16: int | None = Field(default=None, ge=0, strict=True)
    source_end_utf16: int | None = Field(default=None, ge=0, strict=True)
    source_text: str
    spoken_text: str = Field(max_length=4000)
    local_hash: str = Field(pattern=_SHA256_PATTERN)
    speaker_kind: ScriptSpeakerKind
    speaker_label: str = Field(min_length=1, max_length=160)
    character_id: UUID | None = None
    anonymous_speaker_id: UUID | None = None
    confidence: ScriptConfidence
    casting_state: ScriptCastingState
    issue_codes: list[str]
    editable: bool = Field(strict=True)

    @field_validator("segment_id", "character_id", "anonymous_speaker_id")
    @classmethod
    def validate_uuid_fields(cls, value: UUID | None) -> UUID | None:
        if value is None:
            return None
        return _rfc4122_uuid(value, field_name="segment identity")

    @field_validator("speaker_label")
    @classmethod
    def validate_speaker_label(cls, value: str) -> str:
        return _non_blank(value, field_name="speaker_label")

    @field_validator("issue_codes")
    @classmethod
    def validate_issue_codes(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)) or value != sorted(value):
            raise ValueError("segment issue_codes must be unique and sorted")
        for code in value:
            try:
                issue_severity(code)
            except UnknownTaxonomyCodeError as error:
                raise ValueError(str(error)) from error
        return value

    @model_validator(mode="after")
    def validate_segment_shape(self) -> "ScriptReviewSegmentResource":
        if (self.source_start_utf16 is None) != (self.source_end_utf16 is None):
            raise ValueError("source UTF-16 range must be fully present or absent")
        if (
            self.source_start_utf16 is not None
            and self.source_end_utf16 is not None
            and self.source_end_utf16 < self.source_start_utf16
        ):
            raise ValueError("source UTF-16 range is reversed")
        if self.speaker_kind is ScriptSpeakerKind.CHARACTER:
            if self.character_id is None or self.anonymous_speaker_id is not None:
                raise ValueError("character segment requires only character_id")
        elif self.speaker_kind is ScriptSpeakerKind.ANONYMOUS:
            if self.anonymous_speaker_id is None or self.character_id is not None:
                raise ValueError("anonymous segment requires only anonymous_speaker_id")
        elif self.character_id is not None or self.anonymous_speaker_id is not None:
            raise ValueError("non-identity speaker cannot carry identity ids")
        if (
            self.speaker_kind is ScriptSpeakerKind.UNKNOWN
            and "B_SPEAKER_UNKNOWN" not in self.issue_codes
        ):
            raise ValueError("unknown speaker must expose B_SPEAKER_UNKNOWN")
        if (
            self.confidence is ScriptConfidence.LOW
            and "B_SPEAKER_LOW_CONFIDENCE" not in self.issue_codes
        ):
            raise ValueError("low confidence must expose B_SPEAKER_LOW_CONFIDENCE")
        if (
            self.confidence is ScriptConfidence.UNKNOWN
            and "B_SPEAKER_LOW_CONFIDENCE" not in self.issue_codes
        ):
            raise ValueError(
                "unknown confidence must expose B_SPEAKER_LOW_CONFIDENCE"
            )
        if (
            self.confidence is ScriptConfidence.MEDIUM
            and "W_SPEAKER_MEDIUM_CONFIDENCE" not in self.issue_codes
        ):
            raise ValueError("medium confidence must expose its warning")
        if (
            self.casting_state is ScriptCastingState.UNRESOLVED
            and "B_CASTING_TARGET_UNRESOLVED" not in self.issue_codes
        ):
            raise ValueError("unresolved casting must expose its blocker")
        return self


class ScriptApprovalResource(_StrictModel):
    kind: Literal["auto_no_blockers", "manual_after_review"]
    request_id: UUID
    actor_type: Literal["owner", "system", "service"]
    actor_id: str = Field(min_length=1, max_length=120)
    approved_at: datetime

    @field_validator("request_id")
    @classmethod
    def validate_request_id(cls, value: UUID) -> UUID:
        return _rfc4122_uuid(value, field_name="request_id")

    @field_validator("actor_id")
    @classmethod
    def validate_actor_id(cls, value: str) -> str:
        return _non_blank(value, field_name="actor_id")

    @model_validator(mode="after")
    def validate_actor(self) -> "ScriptApprovalResource":
        if self.kind == "auto_no_blockers" and self.actor_type not in {"system", "service"}:
            raise ValueError("automatic approval requires system/service actor")
        if self.kind == "manual_after_review" and self.actor_type != "owner":
            raise ValueError("manual approval requires owner actor")
        if self.approved_at.tzinfo is None or self.approved_at.utcoffset() != timedelta(0):
            raise ValueError("approved_at must be UTC")
        return self


class ScriptReviewResource(_StrictModel):
    contract_version: Literal["narration-script-review-api/1"] = (
        NARRATION_SCRIPT_REVIEW_API_VERSION
    )
    taxonomy_version: Literal["narration-review-taxonomy/1"] = (
        NARRATION_REVIEW_TAXONOMY_VERSION
    )
    script_id: UUID
    script_version_id: UUID
    novel_id: UUID
    document_id: UUID
    revision_id: UUID
    source_content_hash: str = Field(pattern=_SHA256_PATTERN)
    immutable_hash: str = Field(pattern=_SHA256_PATTERN)
    version_number: int = Field(ge=1, strict=True)
    state: ScriptState
    effective_policy: ScriptReviewPolicy
    source_status: ScriptSourceStatus
    warning_count: int = Field(ge=0, strict=True)
    blocker_count: int = Field(ge=0, strict=True)
    allowed_actions: list[ScriptReviewAction]
    segments: list[ScriptReviewSegmentResource]
    issues: list[ScriptReviewIssueResource]
    approval: ScriptApprovalResource | None = None

    @field_validator(
        "script_id",
        "script_version_id",
        "novel_id",
        "document_id",
        "revision_id",
    )
    @classmethod
    def validate_scope_uuid(cls, value: UUID) -> UUID:
        return _rfc4122_uuid(value, field_name="resource scope")

    @model_validator(mode="after")
    def validate_resource(self) -> "ScriptReviewResource":
        if self.allowed_actions != list(dict.fromkeys(self.allowed_actions)):
            raise ValueError("allowed_actions must be unique and stable")
        if [segment.ordinal for segment in self.segments] != list(range(len(self.segments))):
            raise ValueError("segment ordinals must be contiguous from zero")
        segment_ids = {segment.segment_id for segment in self.segments}
        if len(segment_ids) != len(self.segments):
            raise ValueError("segment ids must be unique")
        for issue in self.issues:
            if issue.segment_id is not None and issue.segment_id not in segment_ids:
                raise ValueError("issue references an unknown segment")
        issue_keys = [
            (issue.code, issue.segment_id, issue.evidence_digest) for issue in self.issues
        ]
        if len(issue_keys) != len(set(issue_keys)):
            raise ValueError("review issues must be unique")
        canonical_issue_keys = sorted(
            issue_keys,
            key=lambda item: (
                item[0],
                str(item[1]) if item[1] is not None else "",
                item[2] or "",
            ),
        )
        if issue_keys != canonical_issue_keys:
            raise ValueError("review issues must use canonical order")
        warnings = sum(issue.severity == ReviewIssueSeverity.WARNING.value for issue in self.issues)
        blockers = sum(issue.severity == ReviewIssueSeverity.BLOCKER.value for issue in self.issues)
        if (warnings, blockers) != (self.warning_count, self.blocker_count):
            raise ValueError("issue counts differ from issue rows")
        codes_by_segment: dict[UUID, set[str]] = {segment_id: set() for segment_id in segment_ids}
        for issue in self.issues:
            if issue.segment_id is not None:
                codes_by_segment[issue.segment_id].add(issue.code)
        for segment in self.segments:
            if set(segment.issue_codes) != codes_by_segment[segment.segment_id]:
                raise ValueError("segment issue_codes differ from issue rows")
        if self.state is ScriptState.APPROVED:
            if blockers or self.approval is None or self.allowed_actions:
                raise ValueError("approved script must be blocker-free, audited, and terminal")
            if (
                self.approval.kind == "auto_no_blockers"
                and self.effective_policy is not ScriptReviewPolicy.BLOCKERS_ONLY
            ):
                raise ValueError("automatic approval is only valid for blockers_only")
        elif self.approval is not None:
            raise ValueError("only approved script may contain approval")
        action_set = set(self.allowed_actions)
        if ScriptReviewAction.APPROVE in action_set and (
            self.state is not ScriptState.REVIEW_REQUIRED or blockers > 0
        ):
            raise ValueError("approve action requires zero-blocker review_required state")
        if blockers > 0 and self.state is not ScriptState.REVIEW_REQUIRED:
            raise ValueError("blockers require review_required state")
        if self.state is not ScriptState.REVIEW_REQUIRED and action_set:
            raise ValueError("only review_required script may expose review actions")
        if self.source_status is ScriptSourceStatus.SUPERSEDED and action_set:
            raise ValueError("superseded script must be read-only")
        snapshot_actions = {
            ScriptReviewAction.CONTINUE_SNAPSHOT,
            ScriptReviewAction.REANALYZE_LATEST,
        }
        if (
            self.source_status is ScriptSourceStatus.CURRENT
            and action_set.intersection(snapshot_actions)
        ):
            raise ValueError("current source cannot expose snapshot decisions")
        if (
            self.state is ScriptState.REVIEW_REQUIRED
            and self.source_status is ScriptSourceStatus.WORKING_COPY_DIVERGED
        ):
            required = {
                ScriptReviewAction.CONTINUE_SNAPSHOT,
                ScriptReviewAction.REANALYZE_LATEST,
            }
            if not required.issubset(action_set):
                raise ValueError("diverged source must expose both snapshot decisions")
        return self


class AnalyzeScriptRequest(_StrictModel):
    request_id: UUID
    source_revision_id: UUID
    source_content_hash: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("request_id", "source_revision_id")
    @classmethod
    def validate_uuid_fields(cls, value: UUID) -> UUID:
        return _rfc4122_uuid(value, field_name="analyze request identity")


class SegmentReviewPatch(_StrictModel):
    expected_request_version: int = Field(ge=1, strict=True)
    expected_version_number: int = Field(ge=1, strict=True)
    expected_immutable_hash: str = Field(pattern=_SHA256_PATTERN)
    expected_local_hash: str = Field(pattern=_SHA256_PATTERN)
    request_id: UUID
    speaker_kind: ScriptSpeakerKind
    speaker_label: str = Field(min_length=1, max_length=160)
    character_id: UUID | None = None
    anonymous_speaker_id: UUID | None = None
    group_key: str | None = Field(default=None, min_length=1, max_length=160)
    spoken_text: str = Field(max_length=4000)
    reason: str = Field(min_length=1, max_length=400)

    @field_validator("request_id", "character_id", "anonymous_speaker_id")
    @classmethod
    def validate_uuid_fields(cls, value: UUID | None) -> UUID | None:
        if value is None:
            return None
        return _rfc4122_uuid(value, field_name="segment patch identity")

    @field_validator("speaker_label", "group_key", "reason")
    @classmethod
    def validate_human_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _non_blank(value, field_name="segment patch text")

    @field_validator("spoken_text")
    @classmethod
    def validate_spoken_text(cls, value: str) -> str:
        if value != unicodedata.normalize("NFC", value):
            raise ValueError("spoken_text must be Unicode NFC")
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeEncodeError as error:
            raise ValueError(
                "spoken_text contains an unpaired Unicode surrogate"
            ) from error
        return value

    @model_validator(mode="after")
    def validate_speaker_target(self) -> "SegmentReviewPatch":
        target_count = sum(
            value is not None
            for value in (self.character_id, self.anonymous_speaker_id, self.group_key)
        )
        if self.speaker_kind is ScriptSpeakerKind.CHARACTER:
            if self.character_id is None or target_count != 1:
                raise ValueError("character correction requires only character_id")
        elif self.speaker_kind is ScriptSpeakerKind.ANONYMOUS:
            if self.anonymous_speaker_id is None or target_count != 1:
                raise ValueError("anonymous correction requires only anonymous_speaker_id")
        elif self.speaker_kind is ScriptSpeakerKind.GROUP:
            if self.group_key is None or target_count != 1:
                raise ValueError("group correction requires only group_key")
        elif target_count:
            raise ValueError("narrator/unknown correction cannot carry an identity target")
        if self.speaker_kind is ScriptSpeakerKind.UNKNOWN:
            raise ValueError("manual correction cannot select unknown speaker")
        return self


class ApproveScriptRequest(_StrictModel):
    request_id: UUID
    expected_request_version: int = Field(ge=1, strict=True)
    expected_version_number: int = Field(ge=1, strict=True)
    expected_immutable_hash: str = Field(pattern=_SHA256_PATTERN)
    source_revision_id: UUID
    confirmed: Literal[True]

    @field_validator("request_id", "source_revision_id")
    @classmethod
    def validate_uuid_fields(cls, value: UUID) -> UUID:
        return _rfc4122_uuid(value, field_name="approval request identity")


class ReanalyzeSegmentsRequest(_StrictModel):
    request_id: UUID
    expected_request_version: int = Field(ge=1, strict=True)
    expected_version_number: int = Field(ge=1, strict=True)
    expected_immutable_hash: str = Field(pattern=_SHA256_PATTERN)
    segment_ids: list[UUID] = Field(min_length=1, max_length=64)

    @field_validator("segment_ids")
    @classmethod
    def validate_segment_ids(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("segment_ids must be unique")
        for segment_id in value:
            _rfc4122_uuid(segment_id, field_name="segment_id")
        return value

    @field_validator("request_id")
    @classmethod
    def validate_request_id(cls, value: UUID) -> UUID:
        return _rfc4122_uuid(value, field_name="request_id")


class ScriptApiOperation(str, Enum):
    ANALYZE_SCRIPT = "analyze_script"
    GET_SCRIPT = "get_script"
    GET_SCRIPT_VERSION = "get_script_version"
    PATCH_SEGMENT = "patch_segment"
    APPROVE_SCRIPT_VERSION = "approve_script_version"
    REANALYZE_SEGMENTS = "reanalyze_segments"


@dataclass(frozen=True, slots=True)
class ScriptApiCommand:
    operation: ScriptApiOperation
    document_id: UUID | None = None
    script_id: UUID | None = None
    version_id: UUID | None = None
    segment_id: UUID | None = None
    payload: BaseModel | None = None
    idempotency_key: str | None = None


class ScriptApiBackend(Protocol):
    def dispatch(self, command: ScriptApiCommand) -> object: ...


ScriptApiBackendFactory = Callable[[Session], ScriptApiBackend]


class ScriptApiFault(RuntimeError):
    def __init__(
        self,
        code: ScriptApiErrorCode,
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


SCRIPT_API_ERROR_HTTP_STATUS: Final[dict[ScriptApiErrorCode, int]] = {
    ScriptApiErrorCode.REQUEST_VALIDATION_FAILED: status.HTTP_422_UNPROCESSABLE_CONTENT,
    ScriptApiErrorCode.RESPONSE_CONTRACT_VIOLATION: status.HTTP_500_INTERNAL_SERVER_ERROR,
    ScriptApiErrorCode.SCRIPT_BACKEND_NOT_INSTALLED: status.HTTP_503_SERVICE_UNAVAILABLE,
    ScriptApiErrorCode.STORAGE_UNAVAILABLE: status.HTTP_503_SERVICE_UNAVAILABLE,
    ScriptApiErrorCode.RESOURCE_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ScriptApiErrorCode.SCOPE_VIOLATION: status.HTTP_404_NOT_FOUND,
    ScriptApiErrorCode.VERSION_CONFLICT: status.HTTP_409_CONFLICT,
    ScriptApiErrorCode.INVALID_STATE: status.HTTP_409_CONFLICT,
    ScriptApiErrorCode.IDEMPOTENCY_CONFLICT: status.HTTP_409_CONFLICT,
    ScriptApiErrorCode.STALE_INPUT: status.HTTP_409_CONFLICT,
    ScriptApiErrorCode.VALIDATION_FAILED: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


def script_api_error_detail(fault: ScriptApiFault) -> ScriptApiErrorDetail:
    return ScriptApiErrorDetail(
        code=fault.code,
        message=fault.message,
        retryable=fault.retryable,
        field=fault.field,
        current_version=fault.current_version,
    )


class _UnavailableScriptBackend:
    def dispatch(self, command: ScriptApiCommand) -> object:
        del command
        raise ScriptApiFault(
            ScriptApiErrorCode.SCRIPT_BACKEND_NOT_INSTALLED,
            "脚本复核后端尚未通过 T3-GATE 接线。",
        )


class _StorageUnavailableScriptBackend:
    def dispatch(self, command: ScriptApiCommand) -> object:
        del command
        raise ScriptApiFault(
            ScriptApiErrorCode.STORAGE_UNAVAILABLE,
            "朗读脚本数据库当前不可用。",
            retryable=True,
        )


_backend_factory: ScriptApiBackendFactory | None = None


def install_script_api_backend_factory(factory: ScriptApiBackendFactory) -> None:
    global _backend_factory
    if not callable(factory):
        raise TypeError("script API backend factory must be callable")
    if _backend_factory is not None and _backend_factory is not factory:
        raise RuntimeError("script API backend factory is already installed")
    _backend_factory = factory


def uninstall_script_api_backend_factory(
    factory: ScriptApiBackendFactory | None = None,
) -> None:
    global _backend_factory
    if factory is not None and _backend_factory is not None and _backend_factory is not factory:
        raise RuntimeError("refusing to remove another script API backend factory")
    _backend_factory = None


def get_script_api_backend() -> Iterator[ScriptApiBackend]:
    factory = _backend_factory
    if factory is None:
        yield _UnavailableScriptBackend()
        return
    session_dependency = get_session()
    try:
        session = next(session_dependency)
    except DatabaseNotConfigured:
        yield _StorageUnavailableScriptBackend()
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


def _error_response(fault: ScriptApiFault) -> JSONResponse:
    return JSONResponse(
        status_code=SCRIPT_API_ERROR_HTTP_STATUS[fault.code],
        content={"detail": script_api_error_detail(fault).model_dump(mode="json")},
        headers={"Cache-Control": "no-store"},
    )


class ScriptContractRoute(APIRoute):
    def get_route_handler(self):  # type: ignore[no-untyped-def]
        original = super().get_route_handler()

        async def route_handler(request: Request) -> Response:
            try:
                response = await original(request)
            except RequestValidationError as error:
                return _error_response(
                    ScriptApiFault(
                        ScriptApiErrorCode.REQUEST_VALIDATION_FAILED,
                        "请求字段不符合脚本复核契约。",
                        field=_field_from_validation(error),
                    )
                )
            except ResponseValidationError:
                return _error_response(
                    ScriptApiFault(
                        ScriptApiErrorCode.RESPONSE_CONTRACT_VIOLATION,
                        "脚本复核服务返回了不兼容的数据。",
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
    route_class=ScriptContractRoute,
    dependencies=[Depends(require_narration_t4_http_access)],
)
_ResponseModel = TypeVar("_ResponseModel", bound=BaseModel)


def _fault_from_service(error: NarrationServiceError) -> ScriptApiFault:
    if isinstance(error, NarrationNotFound):
        return ScriptApiFault(
            ScriptApiErrorCode.RESOURCE_NOT_FOUND,
            "找不到请求的朗读脚本。",
        )
    if isinstance(error, NarrationScopeMismatch):
        return ScriptApiFault(
            ScriptApiErrorCode.SCOPE_VIOLATION,
            "找不到请求的朗读脚本。",
        )
    if isinstance(error, NarrationCasConflict):
        return ScriptApiFault(
            ScriptApiErrorCode.VERSION_CONFLICT,
            "脚本版本已经变化，请刷新后重试。",
        )
    if isinstance(error, IdempotencyConflict):
        return ScriptApiFault(
            ScriptApiErrorCode.IDEMPOTENCY_CONFLICT,
            "幂等键已用于另一份请求。",
        )
    if isinstance(error, StaleNarrationInput):
        return ScriptApiFault(
            ScriptApiErrorCode.STALE_INPUT,
            "正文、设置或脚本快照已经变化。",
        )
    if isinstance(error, InvalidNarrationState):
        return ScriptApiFault(
            ScriptApiErrorCode.INVALID_STATE,
            "当前脚本状态不允许此操作。",
        )
    return ScriptApiFault(
        ScriptApiErrorCode.VALIDATION_FAILED,
        "脚本操作未通过领域校验。",
    )


def _run(
    backend: ScriptApiBackend,
    command: ScriptApiCommand,
    response_model: type[_ResponseModel],
) -> _ResponseModel:
    try:
        return response_model.model_validate(backend.dispatch(command))
    except ScriptApiFault as fault:
        raise HTTPException(
            status_code=SCRIPT_API_ERROR_HTTP_STATUS[fault.code],
            detail=script_api_error_detail(fault).model_dump(mode="json"),
        ) from fault
    except NarrationServiceError as error:
        fault = _fault_from_service(error)
        raise HTTPException(
            status_code=SCRIPT_API_ERROR_HTTP_STATUS[fault.code],
            detail=script_api_error_detail(fault).model_dump(mode="json"),
        ) from error
    except ValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ScriptApiErrorDetail(
                code=ScriptApiErrorCode.RESPONSE_CONTRACT_VIOLATION,
                message="脚本复核服务返回了不兼容的数据。",
                retryable=False,
            ).model_dump(mode="json"),
        ) from error


def _response_contract_violation() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=ScriptApiErrorDetail(
            code=ScriptApiErrorCode.RESPONSE_CONTRACT_VIOLATION,
            message="脚本复核服务返回了不兼容的数据。",
            retryable=False,
        ).model_dump(mode="json"),
    )


def _require_response_scope(
    resource: ScriptReviewResource,
    *,
    exact: dict[str, object] | None = None,
    excluded_version_id: UUID | None = None,
    minimum_version_number: int | None = None,
    expected_state: ScriptState | None = None,
) -> ScriptReviewResource:
    for field_name, expected in (exact or {}).items():
        if getattr(resource, field_name) != expected:
            raise _response_contract_violation()
    if (
        excluded_version_id is not None
        and resource.script_version_id == excluded_version_id
    ):
        raise _response_contract_violation()
    if (
        minimum_version_number is not None
        and resource.version_number < minimum_version_number
    ):
        raise _response_contract_violation()
    if expected_state is not None and resource.state is not expected_state:
        raise _response_contract_violation()
    return resource


@router.post(
    "/documents/{document_id}/narration-scripts/analyze",
    response_model=ScriptReviewResource,
    status_code=status.HTTP_202_ACCEPTED,
)
def analyze_script(
    document_id: UUID,
    payload: AnalyzeScriptRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
        pattern=_IDEMPOTENCY_KEY_PATTERN,
    ),
    backend: ScriptApiBackend = Depends(get_script_api_backend),
) -> ScriptReviewResource:
    return _require_response_scope(
        _run(
            backend,
            ScriptApiCommand(
                operation=ScriptApiOperation.ANALYZE_SCRIPT,
                document_id=document_id,
                payload=payload,
                idempotency_key=idempotency_key,
            ),
            ScriptReviewResource,
        ),
        exact={
            "document_id": document_id,
            "revision_id": payload.source_revision_id,
            "source_content_hash": payload.source_content_hash,
        },
    )


@router.get("/narration-scripts/{script_id}", response_model=ScriptReviewResource)
def get_script(
    script_id: UUID,
    backend: ScriptApiBackend = Depends(get_script_api_backend),
) -> ScriptReviewResource:
    return _require_response_scope(
        _run(
            backend,
            ScriptApiCommand(operation=ScriptApiOperation.GET_SCRIPT, script_id=script_id),
            ScriptReviewResource,
        ),
        exact={"script_id": script_id},
    )


@router.get(
    "/narration-script-versions/{version_id}",
    response_model=ScriptReviewResource,
)
def get_script_version(
    version_id: UUID,
    backend: ScriptApiBackend = Depends(get_script_api_backend),
) -> ScriptReviewResource:
    return _require_response_scope(
        _run(
            backend,
            ScriptApiCommand(
                operation=ScriptApiOperation.GET_SCRIPT_VERSION,
                version_id=version_id,
            ),
            ScriptReviewResource,
        ),
        exact={"script_version_id": version_id},
    )


@router.patch(
    "/narration-script-versions/{version_id}/segments/{segment_id}",
    response_model=ScriptReviewResource,
    status_code=status.HTTP_201_CREATED,
)
def patch_script_segment(
    version_id: UUID,
    segment_id: UUID,
    payload: SegmentReviewPatch,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
        pattern=_IDEMPOTENCY_KEY_PATTERN,
    ),
    backend: ScriptApiBackend = Depends(get_script_api_backend),
) -> ScriptReviewResource:
    return _require_response_scope(
        _run(
            backend,
            ScriptApiCommand(
                operation=ScriptApiOperation.PATCH_SEGMENT,
                version_id=version_id,
                segment_id=segment_id,
                payload=payload,
                idempotency_key=idempotency_key,
            ),
            ScriptReviewResource,
        ),
        excluded_version_id=version_id,
        minimum_version_number=payload.expected_version_number + 1,
    )


@router.post(
    "/narration-script-versions/{version_id}/approve",
    response_model=ScriptReviewResource,
)
def approve_script_version(
    version_id: UUID,
    payload: ApproveScriptRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
        pattern=_IDEMPOTENCY_KEY_PATTERN,
    ),
    backend: ScriptApiBackend = Depends(get_script_api_backend),
) -> ScriptReviewResource:
    resource = _require_response_scope(
        _run(
            backend,
            ScriptApiCommand(
                operation=ScriptApiOperation.APPROVE_SCRIPT_VERSION,
                version_id=version_id,
                payload=payload,
                idempotency_key=idempotency_key,
            ),
            ScriptReviewResource,
        ),
        exact={
            "script_version_id": version_id,
            "revision_id": payload.source_revision_id,
            "immutable_hash": payload.expected_immutable_hash,
            "version_number": payload.expected_version_number,
        },
        expected_state=ScriptState.APPROVED,
    )
    if (
        resource.approval is None
        or resource.approval.kind != "manual_after_review"
        or resource.approval.request_id != payload.request_id
    ):
        raise _response_contract_violation()
    return resource


@router.post(
    "/narration-script-versions/{version_id}/reanalyze-segments",
    response_model=ScriptReviewResource,
    status_code=status.HTTP_202_ACCEPTED,
)
def reanalyze_segments(
    version_id: UUID,
    payload: ReanalyzeSegmentsRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
        pattern=_IDEMPOTENCY_KEY_PATTERN,
    ),
    backend: ScriptApiBackend = Depends(get_script_api_backend),
) -> ScriptReviewResource:
    return _require_response_scope(
        _run(
            backend,
            ScriptApiCommand(
                operation=ScriptApiOperation.REANALYZE_SEGMENTS,
                version_id=version_id,
                payload=payload,
                idempotency_key=idempotency_key,
            ),
            ScriptReviewResource,
        ),
        excluded_version_id=version_id,
        minimum_version_number=payload.expected_version_number + 1,
    )


__all__ = [
    "AnalyzeScriptRequest",
    "ApproveScriptRequest",
    "NARRATION_SCRIPT_REVIEW_API_VERSION",
    "ReanalyzeSegmentsRequest",
    "SCRIPT_API_ERROR_HTTP_STATUS",
    "ScriptApiBackend",
    "ScriptApiBackendFactory",
    "ScriptApiCommand",
    "ScriptApiErrorCode",
    "ScriptApiErrorDetail",
    "ScriptApiFault",
    "ScriptApiOperation",
    "ScriptApprovalResource",
    "ScriptContractRoute",
    "ScriptReviewAction",
    "ScriptReviewIssueResource",
    "ScriptReviewResource",
    "ScriptReviewSegmentResource",
    "SegmentReviewPatch",
    "get_script_api_backend",
    "install_script_api_backend_factory",
    "router",
    "script_api_error_detail",
    "uninstall_script_api_backend_factory",
]
