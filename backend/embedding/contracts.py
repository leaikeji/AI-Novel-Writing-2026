"""Pure Pydantic contracts for embedding configuration and semantic search.

The target model values below are planning defaults only.  They must remain
``unverified`` until an implementation gate independently verifies the current
provider contract.  This module deliberately contains no network or persistence
logic and makes no assertions about price, rate limits, or provider availability.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from math import isfinite
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)


EMBEDDING_CONTRACT_VERSION = "embedding-api/2"
SEMANTIC_SEARCH_SCHEMA_VERSION = "semantic-search/2"
NOVEL_EMBEDDING_CONSENT_NOTICE_VERSION = "novel-embedding-consent/2"
RETRIEVAL_POLICY_VERSION = "writing-retrieval/2"

# Planning target only; it is not a claim that the live provider contract was
# verified by this code package.
TARGET_CANDIDATE_MODEL_ID = "qwen3.7-text-embedding"
SUPPORTED_EMBEDDING_DIMENSIONS = (2048,)
TARGET_CANDIDATE_DIMENSION = 2048


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CredentialAction(str, Enum):
    KEEP = "keep"
    REPLACE = "replace"
    CLEAR = "clear"


class ConsentAction(str, Enum):
    GRANT = "grant"
    REVOKE = "revoke"


class NovelEmbeddingConsentState(str, Enum):
    NOT_AUTHORIZED = "not_authorized"
    GRANTED = "granted"
    REVOKED = "revoked"
    REQUIRES_RECONSENT = "requires_reconsent"


class VerificationStatus(str, Enum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    FAILED = "failed"


class EmbeddingCorpus(str, Enum):
    MANUSCRIPT = "manuscript"
    PLANNING = "planning"
    PRIVATE_ASSET = "private_asset"
    CHARACTER = "character"
    RELATIONSHIP = "relationship"
    STORY_EVENT = "story_event"
    STORYLINE = "storyline"
    FORESHADOW = "foreshadow"
    TIMELINE = "timeline"


DEFAULT_NOVEL_EMBEDDING_CORPORA = (
    EmbeddingCorpus.MANUSCRIPT,
    EmbeddingCorpus.PLANNING,
    EmbeddingCorpus.PRIVATE_ASSET,
)


class EmbeddingConnectionStatus(str, Enum):
    UNCONFIGURED = "unconfigured"
    UNVERIFIED = "unverified"
    TESTING = "testing"
    AVAILABLE = "available"
    AUTHENTICATION_FAILED = "authentication_failed"
    PROTOCOL_ERROR = "protocol_error"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"


class EmbeddingGenerationStatus(str, Enum):
    NOT_BUILT = "not_built"
    QUEUED = "queued"
    BUILDING = "building"
    READY = "ready"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"
    STALE = "stale"
    ACTIVE = "active"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    RETIRED = "retired"


class SemanticIndexStatus(str, Enum):
    NOT_AUTHORIZED = "not_authorized"
    NOT_CONFIGURED = "not_configured"
    NOT_BUILT = "not_built"
    QUEUED = "queued"
    BUILDING = "building"
    READY = "ready"
    UPDATING = "updating"
    OUTDATED = "outdated"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"
    STALE = "stale"
    DISABLED = "disabled"
    REVOKED = "revoked"


class SemanticMatchChannel(str, Enum):
    LEXICAL = "lexical"
    DENSE = "dense"


class SemanticSearchMode(str, Enum):
    LEXICAL_ONLY = "lexical_only"
    DENSE_ONLY = "dense_only"
    HYBRID = "hybrid"


class SemanticSourceState(str, Enum):
    CURRENT_REVISION = "current_revision"
    WORKING_COPY = "working_copy"
    CURRENT_ENTITY_REVISION = "current_entity_revision"
    ACCEPTED_STORY_FACT = "accepted_story_fact"
    BOUND_ASSET_VERSION = "bound_asset_version"


class PerspectiveKind(str, Enum):
    AUTHOR = "author"
    READER = "reader"
    CHARACTER_INSTANCE = "character_instance"


class RetrievalPurpose(str, Enum):
    MANUAL_SEARCH = "manual_search"
    CHAPTER_BODY = "chapter_body"
    CHAPTER_OUTLINE = "chapter_outline"
    CHAPTER_REVIEW = "chapter_review"
    SELECTION_REWRITE = "selection_rewrite"
    SELECTION_EXPAND = "selection_expand"
    SELECTION_DIALOGUE = "selection_dialogue"
    SELECTION_REVIEW = "selection_review"
    SELECTION_CUSTOM = "selection_custom"


class EmbeddingErrorCode(str, Enum):
    REQUEST_VALIDATION_FAILED = "request_validation_failed"
    EMBEDDING_NOT_CONFIGURED = "embedding_not_configured"
    EMBEDDING_SECRET_UNAVAILABLE = "embedding_secret_unavailable"
    EMBEDDING_CONSENT_REQUIRED = "embedding_consent_required"
    EMBEDDING_CANDIDATE_NOT_VERIFIED = "embedding_candidate_not_verified"
    EMBEDDING_GENERATION_NOT_READY = "embedding_generation_not_ready"
    EMBEDDING_DIMENSION_MISMATCH = "embedding_dimension_mismatch"
    EMBEDDING_AUTHENTICATION_FAILED = "embedding_authentication_failed"
    EMBEDDING_RATE_LIMITED = "embedding_rate_limited"
    EMBEDDING_PROTOCOL_ERROR = "embedding_protocol_error"
    EMBEDDING_UNAVAILABLE = "embedding_unavailable"
    SEMANTIC_INDEX_STALE = "semantic_index_stale"
    SEMANTIC_SCOPE_VIOLATION = "semantic_scope_violation"
    CONSENT_VERSION_CONFLICT = "consent_version_conflict"
    CONSENT_SCOPE_MISMATCH = "consent_scope_mismatch"
    CONSENT_TARGET_CHANGED = "consent_target_changed"
    INDEX_ENQUEUE_FAILED = "index_enqueue_failed"


class EmbeddingCredentialMutation(_StrictModel):
    """Write-only credential command.

    ``api_key`` is accepted only when replacing the secret.  It is intentionally
    absent from every resource and search response type in this module.
    """

    contract_version: Literal[EMBEDDING_CONTRACT_VERSION] = EMBEDDING_CONTRACT_VERSION
    action: CredentialAction
    api_key: SecretStr | None = Field(default=None, repr=False)

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_api_key_shape(cls, value: object) -> object:
        if value is None:
            return None
        raw = value.get_secret_value() if isinstance(value, SecretStr) else str(value)
        raw = raw.strip()
        if not raw:
            raise ValueError("api_key must not be blank")
        if len(raw) > 4096:
            raise ValueError("api_key is too long")
        if "\x00" in raw:
            raise ValueError("api_key contains a null byte")
        return SecretStr(raw)

    @model_validator(mode="after")
    def validate_action_payload(self) -> "EmbeddingCredentialMutation":
        if self.action is CredentialAction.REPLACE and self.api_key is None:
            raise ValueError("replace requires api_key")
        if self.action is not CredentialAction.REPLACE and self.api_key is not None:
            raise ValueError("api_key is permitted only for replace")
        return self


class EmbeddingCandidateTarget(_StrictModel):
    """Frozen planning candidate; live compatibility remains unverified."""

    provider_id: Literal["aliyun-bailian"] = "aliyun-bailian"
    protocol: Literal["dashscope-native-v1"] = "dashscope-native-v1"
    model_id: str = Field(default=TARGET_CANDIDATE_MODEL_ID, min_length=1, max_length=200)
    dimension: int = Field(default=TARGET_CANDIDATE_DIMENSION, ge=1, le=65536)
    output_type: Literal["dense"] = "dense"
    document_text_type: Literal["document"] = "document"
    query_text_type: Literal["query"] = "query"
    distance: Literal["cosine"] = "cosine"
    verification_status: Literal[VerificationStatus.UNVERIFIED] = VerificationStatus.UNVERIFIED

    @field_validator("dimension")
    @classmethod
    def validate_dimension(cls, value: int) -> int:
        if value not in SUPPORTED_EMBEDDING_DIMENSIONS:
            raise ValueError("dimension is not supported by qwen3.7-text-embedding")
        return value


class EmbeddingProfileResource(_StrictModel):
    profile_id: UUID
    target: EmbeddingCandidateTarget
    generation_status: EmbeddingGenerationStatus
    actual_model_revision: str | None = Field(default=None, max_length=300)
    actual_dimension: int | None = Field(default=None, ge=1, le=65536)
    created_at: datetime


class EmbeddingConfigResource(_StrictModel):
    """Read resource: only credential presence metadata is exposed."""

    contract_version: Literal[EMBEDDING_CONTRACT_VERSION] = EMBEDDING_CONTRACT_VERSION
    version: int = Field(ge=0)
    provider_id: Literal["aliyun-bailian"] = "aliyun-bailian"
    protocol: Literal["dashscope-native-v1"] = "dashscope-native-v1"
    base_url: str | None = Field(default=None, max_length=2048)
    credential_configured: bool
    credential_updated_at: datetime | None = None
    connection_status: EmbeddingConnectionStatus
    active_profile: EmbeddingProfileResource | None = None
    candidate_profile: EmbeddingProfileResource | None = None
    authorized_novel_count: int = Field(default=0, ge=0)
    pending_rebuild_novel_count: int = Field(default=0, ge=0)
    failed_novel_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_credential_metadata(self) -> "EmbeddingConfigResource":
        if not self.credential_configured and self.credential_updated_at is not None:
            raise ValueError("credential_updated_at requires a configured credential")
        return self


class NovelEmbeddingConsentMutation(_StrictModel):
    contract_version: Literal[EMBEDDING_CONTRACT_VERSION] = EMBEDDING_CONTRACT_VERSION
    action: ConsentAction
    expected_version: int = Field(ge=0)
    idempotency_key: str = Field(min_length=1, max_length=160)
    active_consent_id: UUID | None = None
    notice_version: str | None = Field(default=None, min_length=1, max_length=100)
    acknowledged_corpora: tuple[EmbeddingCorpus, ...] = ()

    @field_validator("idempotency_key")
    @classmethod
    def validate_idempotency_key(cls, value: str) -> str:
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-")
        if value[0] not in allowed or any(character not in allowed for character in value):
            raise ValueError("idempotency_key contains unsupported characters")
        return value

    @field_validator("acknowledged_corpora")
    @classmethod
    def validate_unique_corpora(
        cls, value: tuple[EmbeddingCorpus, ...]
    ) -> tuple[EmbeddingCorpus, ...]:
        if len(value) != len(set(value)):
            raise ValueError("acknowledged_corpora must not contain duplicates")
        return value

    @model_validator(mode="after")
    def validate_consent_action(self) -> "NovelEmbeddingConsentMutation":
        if self.action is ConsentAction.GRANT:
            if self.active_consent_id is not None:
                raise ValueError("grant must not reference an active consent")
            if self.notice_version is None:
                raise ValueError("grant requires notice_version")
            if not self.acknowledged_corpora:
                raise ValueError("grant requires acknowledged_corpora")
        else:
            if self.active_consent_id is None:
                raise ValueError("revoke requires active_consent_id")
            if self.notice_version is not None or self.acknowledged_corpora:
                raise ValueError("revoke must not include grant acknowledgement fields")
        return self


class NovelEmbeddingConsentResource(_StrictModel):
    contract_version: Literal[EMBEDDING_CONTRACT_VERSION] = EMBEDDING_CONTRACT_VERSION
    novel_id: UUID
    authorized: bool
    consent_id: UUID | None = None
    notice_version: str | None = Field(default=None, min_length=1, max_length=100)
    acknowledged_corpora: tuple[EmbeddingCorpus, ...] = ()
    granted_at: datetime | None = None
    revoked_at: datetime | None = None
    writing_query_authorized: bool = False

    @field_validator("acknowledged_corpora")
    @classmethod
    def validate_unique_resource_corpora(
        cls, value: tuple[EmbeddingCorpus, ...]
    ) -> tuple[EmbeddingCorpus, ...]:
        if len(value) != len(set(value)):
            raise ValueError("acknowledged_corpora must not contain duplicates")
        return value

    @model_validator(mode="after")
    def validate_consent_state(self) -> "NovelEmbeddingConsentResource":
        if self.authorized:
            if (
                self.consent_id is None
                or self.notice_version is None
                or self.granted_at is None
                or not self.acknowledged_corpora
                or self.revoked_at is not None
            ):
                raise ValueError("authorized consent requires complete grant metadata")
        elif self.revoked_at is not None and self.consent_id is None:
            raise ValueError("revoked_at requires consent_id")
        return self


class SemanticPerspective(_StrictModel):
    kind: PerspectiveKind = PerspectiveKind.AUTHOR
    character_instance_id: UUID | None = None

    @model_validator(mode="after")
    def validate_character_scope(self) -> "SemanticPerspective":
        if self.kind is PerspectiveKind.CHARACTER_INSTANCE:
            if self.character_instance_id is None:
                raise ValueError("character perspective requires character_instance_id")
        elif self.character_instance_id is not None:
            raise ValueError("character_instance_id is valid only for character perspective")
        return self


class SemanticSearchRequest(_StrictModel):
    schema_version: Literal[SEMANTIC_SEARCH_SCHEMA_VERSION] = SEMANTIC_SEARCH_SCHEMA_VERSION
    query: str = Field(min_length=1, max_length=4000)
    retrieval_purpose: RetrievalPurpose = RetrievalPurpose.MANUAL_SEARCH
    corpora: tuple[EmbeddingCorpus, ...] = (
        EmbeddingCorpus.MANUSCRIPT,
        EmbeddingCorpus.PLANNING,
        EmbeddingCorpus.PRIVATE_ASSET,
    )
    top_k: int = Field(default=10, ge=1, le=50)
    timeline_id: UUID | None = None
    narrative_sequence: int | None = Field(default=None, ge=0)
    story_sequence_cutoff: int | None = Field(default=None, ge=0)
    perspective: SemanticPerspective = Field(default_factory=SemanticPerspective)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        if not value:
            raise ValueError("query must not be blank")
        return value

    @field_validator("corpora")
    @classmethod
    def validate_corpora(
        cls, value: tuple[EmbeddingCorpus, ...]
    ) -> tuple[EmbeddingCorpus, ...]:
        if not value:
            raise ValueError("corpora must not be empty")
        if len(value) != len(set(value)):
            raise ValueError("corpora must not contain duplicates")
        return value


class SemanticSearchHit(_StrictModel):
    corpus: EmbeddingCorpus
    source_type: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    source_id: UUID
    source_revision_id: UUID | None = None
    chunk_id: UUID
    source_state: SemanticSourceState
    timeline_id: UUID | None = None
    character_instance_id: UUID | None = None
    narrative_sequence_start: int | None = Field(default=None, ge=0)
    narrative_sequence_end: int | None = Field(default=None, ge=0)
    story_sequence_start: int | None = Field(default=None, ge=0)
    story_sequence_end: int | None = Field(default=None, ge=0)
    snippet: str = Field(min_length=1, max_length=4000)
    channels: tuple[SemanticMatchChannel, ...]
    lexical_score: float | None = Field(default=None, ge=0)
    dense_distance: float | None = Field(default=None, ge=0, le=2)
    fused_score: float = Field(ge=0)

    @field_validator("channels")
    @classmethod
    def validate_channels(
        cls, value: tuple[SemanticMatchChannel, ...]
    ) -> tuple[SemanticMatchChannel, ...]:
        if not value:
            raise ValueError("channels must not be empty")
        if len(value) != len(set(value)):
            raise ValueError("channels must not contain duplicates")
        return value

    @field_validator("fused_score")
    @classmethod
    def validate_finite_score(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("score must be finite")
        return value

    @model_validator(mode="after")
    def validate_narrative_range(self) -> "SemanticSearchHit":
        if self.narrative_sequence_end is not None and self.narrative_sequence_start is None:
            raise ValueError("narrative_sequence_end requires a start")
        if (
            self.narrative_sequence_start is not None
            and self.narrative_sequence_end is not None
            and self.narrative_sequence_end < self.narrative_sequence_start
        ):
            raise ValueError("narrative sequence range is reversed")
        return self


class SemanticSearchResult(_StrictModel):
    schema_version: Literal[SEMANTIC_SEARCH_SCHEMA_VERSION] = SEMANTIC_SEARCH_SCHEMA_VERSION
    request_id: str = Field(min_length=1, max_length=160)
    generation_id: UUID | None = None
    index_version: int | None = Field(default=None, ge=1)
    retrieval_policy_version: str = Field(
        default=RETRIEVAL_POLICY_VERSION, min_length=1, max_length=120
    )
    mode: SemanticSearchMode
    index_status: SemanticIndexStatus
    hits: tuple[SemanticSearchHit, ...] = ()
    omitted_count: int = Field(default=0, ge=0)
    provider_request_id: str | None = Field(default=None, max_length=240)
    token_count: int | None = Field(default=None, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    degraded_reason: str | None = Field(default=None, max_length=120)
    omission_summary: tuple[str, ...] = ()
    warnings: tuple[EmbeddingErrorCode, ...] = ()

    @field_validator("warnings")
    @classmethod
    def validate_unique_warnings(
        cls, value: tuple[EmbeddingErrorCode, ...]
    ) -> tuple[EmbeddingErrorCode, ...]:
        if len(value) != len(set(value)):
            raise ValueError("warnings must not contain duplicates")
        return value


class EmbeddingErrorResource(_StrictModel):
    contract_version: Literal[EMBEDDING_CONTRACT_VERSION] = EMBEDDING_CONTRACT_VERSION
    code: EmbeddingErrorCode
    message: str = Field(min_length=1, max_length=500)
    retryable: bool = False
    request_id: str | None = Field(default=None, min_length=1, max_length=160)
    field: str | None = Field(default=None, min_length=1, max_length=120)
