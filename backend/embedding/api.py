"""PawApp-owned embedding configuration, consent and semantic-index routes."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from time import monotonic
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..creative_data_models import (
    EmbeddingConfiguration,
    EmbeddingGeneration,
    EmbeddingGenerationNovel,
    EmbeddingIndexBatch,
    EmbeddingProfile,
    NovelAssetBinding,
    NovelEmbeddingConsent,
    NovelOutlineHead,
    NovelSettingHead,
    SemanticChunk,
    SemanticEmbedding,
    SemanticSource,
    StoryTimeline,
)
from ..background.jobs import manual_retry, request_cancel
from ..database import get_session
from .adapter import DashScopeEmbeddingAdapter, EmbeddingAdapterError, normalize_dashscope_base_url
from .contracts import (
    ConsentAction,
    CredentialAction,
    EmbeddingCorpus,
    NovelEmbeddingConsentMutation,
    NOVEL_EMBEDDING_CONSENT_NOTICE_VERSION,
    PerspectiveKind,
    RetrievalPurpose as ApiRetrievalPurpose,
    SUPPORTED_EMBEDDING_DIMENSIONS,
    SemanticSearchRequest,
    TARGET_CANDIDATE_DIMENSION,
)
from .indexing import prepare_v1_novel_index, request_active_novel_refresh
from .evaluation_v2 import evaluate_frozen_vectors, load_frozen_evaluation_fixture
from .lifecycle import EmbeddingLifecycleError
from .local_lexical import (
    LocalLexicalScopeError,
    LocalLexicalSearchRequest,
    LocalTimelineLimit,
    author_visible_v1_snippet,
    search_local_authority,
)
from .persistence import (
    activate_candidate_generation,
    apply_credential_reference,
    create_verified_candidate,
    ensure_configuration,
    get_configuration,
    grant_consent,
    revoke_consent,
)
from .retrieval import (
    CandidateVisibility,
    RawChannelScore,
    RetrievalCandidate,
    RetrievalChannel,
    RetrievalChannelEvidence,
    RetrievalChannelStatus,
    RetrievalPerspective,
    RetrievalPolicyV1,
    RetrievalPurpose as CoreRetrievalPurpose,
    KnowledgeProjectionScope,
    SearchScope,
    SemanticSearchRequestV2,
    TimelineSearchLimit,
    derive_known_visibility_keys,
    retrieve,
)
from .secrets import EmbeddingSecretError, EmbeddingSecretStore
from ..models import BackgroundJob, DerivedSourceBinding, DocumentWorkingCopy, StoryFact
from ..narration.contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID, NarrationRequestScope
from ..story_state.contracts import StoryFactV2


router = APIRouter(tags=["embedding"])
SECRET_ROOT_ENV = "AI_NOVEL_EMBEDDING_SECRET_ROOT_KEY_FILE"
SECRET_DIR_ENV = "AI_NOVEL_EMBEDDING_SECRET_RECORDS_DIR"
EVALUATION_QUERY_BATCH_SIZE = 1


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CandidateRequest(_Strict):
    expected_version: int = Field(ge=0)
    base_url: str = Field(min_length=1, max_length=500)
    requested_model_id: str = Field(default="qwen3.7-text-embedding", min_length=1, max_length=160)
    requested_dimension: int = Field(default=TARGET_CANDIDATE_DIMENSION)
    api_key_action: CredentialAction = CredentialAction.KEEP
    api_key: SecretStr | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def validate_secret(self) -> "CandidateRequest":
        if self.api_key_action is CredentialAction.REPLACE and self.api_key is None:
            raise ValueError("replace requires api_key")
        if self.api_key_action is not CredentialAction.REPLACE and self.api_key is not None:
            raise ValueError("api_key is valid only for replace")
        return self

    @field_validator("requested_dimension")
    @classmethod
    def validate_dimension(cls, value: int) -> int:
        if value not in SUPPORTED_EMBEDDING_DIMENSIONS:
            raise ValueError("unsupported qwen3.7-text-embedding dimension")
        return value


class ConnectionTestRequest(_Strict):
    base_url: str = Field(min_length=1, max_length=500)
    requested_model_id: str = Field(default="qwen3.7-text-embedding", min_length=1, max_length=160)
    requested_dimension: int = Field(default=TARGET_CANDIDATE_DIMENSION)
    api_key: SecretStr | None = Field(default=None, repr=False)

    @field_validator("requested_dimension")
    @classmethod
    def validate_dimension(cls, value: int) -> int:
        if value not in SUPPORTED_EMBEDDING_DIMENSIONS:
            raise ValueError("unsupported qwen3.7-text-embedding dimension")
        return value


class VersionRequest(_Strict):
    expected_version: int = Field(ge=1)


class CancelRequest(_Strict):
    reason: str = Field(default="author_cancelled", min_length=1, max_length=96)


class ConsentUiRequest(_Strict):
    action: ConsentAction
    expected_version: int = Field(ge=0)
    notice_version: str = Field(min_length=1, max_length=80)
    acknowledged_scopes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _SentinelEvidence:
    query_request_id: str
    document_request_id: str
    actual_dimension: int
    total_tokens: int
    latency_ms: int


async def _evaluate_candidate(
    session: Session, configuration: EmbeddingConfiguration
) -> EmbeddingGeneration:
    generation_id = configuration.candidate_generation_id
    if generation_id is None:
        raise EmbeddingLifecycleError("candidate_missing", "candidate generation is missing")
    generation = session.get(EmbeddingGeneration, generation_id)
    if generation is None or generation.state != "ready":
        raise EmbeddingLifecycleError("candidate_not_ready", "candidate generation is not ready")
    profile = session.get(EmbeddingProfile, generation.profile_id)
    if profile is None:
        raise EmbeddingLifecycleError("profile_missing", "candidate profile is missing")
    fixture = load_frozen_evaluation_fixture()
    credential_ref = configuration.credential_ref
    configuration_version = configuration.version
    if credential_ref is None:
        raise EmbeddingLifecycleError(
            "embedding_not_configured", "embedding credential is missing"
        )
    base_url = profile.base_url
    model_id = profile.actual_model_id
    dimension = profile.dimension
    generation.evaluation_state = "pending"
    generation.evaluation_summary_json = {
        "schema_version": "embedding-evaluation/2",
        "case_count": len(fixture.cases),
        "state": "running",
    }
    session.commit()

    api_key = _secret_store().get(credential_ref)
    adapter = DashScopeEmbeddingAdapter(base_url=base_url)
    source_vectors: dict[str, tuple[float, ...]] = {}
    query_vectors: dict[str, tuple[float, ...]] = {}
    request_ids: list[str] = []
    total_tokens = 0
    for source in fixture.sources:
        result = await adapter.embed(
            api_key=api_key,
            texts=[str(source["content"])],
            text_type="document",
            model_id=model_id,
            dimension=dimension,
        )
        source_vectors[str(source["source_key"])] = tuple(
            float(value) for value in result.vectors[0].values
        )
        request_ids.append(result.request_id)
        total_tokens += result.total_tokens
    for start in range(0, len(fixture.cases), EVALUATION_QUERY_BATCH_SIZE):
        batch = fixture.cases[start : start + EVALUATION_QUERY_BATCH_SIZE]
        result = await adapter.embed(
            api_key=api_key,
            texts=[str(item["query"]) for item in batch],
            text_type="query",
            model_id=model_id,
            dimension=dimension,
            instruct="Retrieve the matching evidence from this novel corpus.",
        )
        for item, vector in zip(batch, result.vectors):
            query_vectors[str(item["case_id"])] = tuple(
                float(value) for value in vector.values
            )
        request_ids.append(result.request_id)
        total_tokens += result.total_tokens
    summary = evaluate_frozen_vectors(
        fixture,
        source_vectors=source_vectors,
        query_vectors=query_vectors,
    )
    current_configuration = get_configuration(
        session,
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        for_update=True,
    )
    current = session.scalar(
        select(EmbeddingGeneration)
        .where(EmbeddingGeneration.id == generation_id)
        .with_for_update()
    )
    if (
        current_configuration is None
        or current_configuration.candidate_generation_id != generation_id
        or current_configuration.version != configuration_version
        or current_configuration.credential_ref != credential_ref
        or current is None
        or current.index_fingerprint != generation.index_fingerprint
        or current.state != "ready"
    ):
        session.rollback()
        raise EmbeddingLifecycleError("candidate_changed", "candidate changed during evaluation")
    current.evaluation_state = "passed" if summary["passed"] else "failed"
    current.evaluation_summary_json = {
        **summary,
        "request_ids": request_ids,
        "total_tokens": total_tokens,
    }
    session.commit()
    return current


def _secret_store() -> EmbeddingSecretStore:
    root = os.environ.get(SECRET_ROOT_ENV, "").strip()
    records = os.environ.get(SECRET_DIR_ENV, "").strip()
    if not root or not records:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "embedding_secret_unavailable", "message": "向量密钥存储尚未配置"},
        )
    return EmbeddingSecretStore(root_key_path=Path(root), records_dir=Path(records))


def _secret_store_ready() -> bool:
    try:
        store = _secret_store()
        store.validate()
    except (HTTPException, EmbeddingSecretError):
        return False
    return True


def _masked_api_key(configuration: EmbeddingConfiguration | None) -> str | None:
    if (
        configuration is None
        or configuration.credential_ref is None
        or configuration.api_key_last4 is None
        or len(configuration.api_key_last4) != 4
    ):
        return None
    return f"********{configuration.api_key_last4}"


def _raise(error: Exception) -> None:
    if isinstance(error, IntegrityError):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "code": "version_conflict",
                "message": "向量配置已被其他操作更新",
            },
        ) from error
    if isinstance(error, EmbeddingLifecycleError):
        code = error.code
        http_status = status.HTTP_404_NOT_FOUND if code.endswith("not_found") else status.HTTP_409_CONFLICT
        if code in {"dimension_mismatch", "scope_violation"}:
            http_status = status.HTTP_422_UNPROCESSABLE_ENTITY
        raise HTTPException(http_status, detail={"code": code, "message": str(error)}) from error
    if isinstance(error, (EmbeddingAdapterError, EmbeddingSecretError)):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": error.code.lower(), "message": str(error)},
        ) from error
    raise error


def _generation_payload(
    session: Session, generation_id: UUID | None
) -> dict[str, object] | None:
    if generation_id is None:
        return None
    generation = session.get(EmbeddingGeneration, generation_id)
    if generation is None:
        return None
    profile = session.get(EmbeddingProfile, generation.profile_id)
    builds = tuple(
        session.scalars(
            select(EmbeddingGenerationNovel).where(
                EmbeddingGenerationNovel.generation_id == generation.id
            )
        )
    )
    return {
        "id": str(generation.id), "generation_number": generation.generation_number,
        "state": generation.state, "model_id": profile.actual_model_id if profile else None,
        "actual_revision": profile.actual_revision if profile else None,
        "dimension": profile.dimension if profile else None,
        "index_fingerprint": generation.index_fingerprint,
        "renderer_bundle_version": generation.renderer_bundle_version,
        "authorized_novel_count": len(builds),
        "ready_novel_count": sum(item.state == "ready" for item in builds),
        "pending_novel_count": sum(item.state in {"pending", "building"} for item in builds),
        "failed_novel_count": sum(item.state == "failed" for item in builds),
        "evaluation_state": generation.evaluation_state,
        "activation_eligible": (
            generation.state == "ready"
            and generation.evaluation_state == "passed"
            and all(item.state == "ready" for item in builds)
        ),
    }


@router.get("/embedding-config")
def embedding_config_get(session: Session = Depends(get_session)) -> dict[str, object]:
    configuration = get_configuration(
        session, owner_id=LOCAL_OWNER_ID, workspace_id=LOCAL_WORKSPACE_ID
    )
    active_consents = int(
        session.scalar(
            select(func.count()).select_from(NovelEmbeddingConsent).where(
                NovelEmbeddingConsent.revoked_at.is_(None)
            )
        )
        or 0
    )
    if configuration is None:
        return {
            "schema_version": "embedding-config/1", "version": 0,
            "provider_id": "aliyun-bailian", "provider_label": "阿里云百炼",
            "protocol": "dashscope-native-v1", "protocol_label": "DashScope Native",
            "base_url": "",
            "secret_store_ready": _secret_store_ready(),
            "api_key_configured": False, "api_key_masked": None,
            "credential_cleanup_warning": None,
            "connection_state": "unconfigured",
            "requested_model_id": "qwen3.7-text-embedding",
            "requested_dimension": TARGET_CANDIDATE_DIMENSION,
            "active_generation": None, "candidate_generation": None,
            "previous_generation": None, "authorized_novel_count": active_consents,
            "pending_rebuild_novel_count": 0, "failed_novel_count": 0,
            "last_request": None,
        }
    candidate_payload = _generation_payload(session, configuration.candidate_generation_id)
    active_payload = _generation_payload(session, configuration.active_generation_id)
    previous_payload = _generation_payload(session, configuration.previous_generation_id)
    preferred = candidate_payload or active_payload
    summary = dict(configuration.connection_summary_json or {})
    state = (
        "ready" if configuration.connection_state == "available" else
        "unconfigured" if configuration.connection_state == "unconfigured" else
        "untested" if configuration.connection_state in {"unverified", "testing"} else
        "failed"
    )
    return {
        "schema_version": "embedding-config/1", "version": configuration.version,
        "provider_id": "aliyun-bailian", "provider_label": "阿里云百炼",
        "protocol": "dashscope-native-v1", "protocol_label": "DashScope Native",
        "base_url": configuration.base_url,
        "secret_store_ready": _secret_store_ready(),
        "api_key_configured": configuration.credential_ref is not None,
        "api_key_masked": _masked_api_key(configuration),
        "credential_cleanup_warning": (
            "旧 API Key 加密记录未能自动清理，请检查密钥保险箱。"
            if (summary.get("credential_cleanup") or {}).get("state") == "pending"
            else None
        ),
        "connection_state": state,
        "requested_model_id": preferred["model_id"] if preferred else "qwen3.7-text-embedding",
        "requested_dimension": (
            preferred["dimension"] if preferred else TARGET_CANDIDATE_DIMENSION
        ),
        "active_generation": active_payload,
        "candidate_generation": candidate_payload,
        "previous_generation": previous_payload,
        "authorized_novel_count": active_consents,
        "pending_rebuild_novel_count": candidate_payload["pending_novel_count"] if candidate_payload else 0,
        "failed_novel_count": candidate_payload["failed_novel_count"] if candidate_payload else 0,
        "last_request": (
            {
                "request_id": summary.get("request_id"),
                "document_request_id": summary.get("document_request_id"),
                "token_count": summary.get("total_tokens"),
                "latency_ms": summary.get("latency_ms"),
                "error_summary": summary.get("error_summary"),
                "observed_at": summary.get("observed_at"),
            }
            if summary else None
        ),
    }


@router.post("/embedding-config/secret-store/initialize")
def embedding_secret_store_initialize(
    session: Session = Depends(get_session),
) -> dict[str, object]:
    root = os.environ.get(SECRET_ROOT_ENV, "").strip()
    records = os.environ.get(SECRET_DIR_ENV, "").strip()
    if not root or not records:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "embedding_secret_unavailable", "message": "向量密钥保险箱路径尚未配置"},
        )
    try:
        EmbeddingSecretStore.provision(
            root_key_path=Path(root),
            records_dir=Path(records),
        )
    except EmbeddingSecretError as error:
        _raise(error)
    return embedding_config_get(session)


async def _sentinel(
    *, base_url: str, credential_ref: str | None, model_id: str, dimension: int,
    ephemeral_api_key: str | None = None,
) -> _SentinelEvidence:
    if ephemeral_api_key is None and credential_ref is None:
        raise EmbeddingLifecycleError("embedding_not_configured", "embedding credential is missing")
    api_key = ephemeral_api_key or _secret_store().get(credential_ref or "")
    started = monotonic()
    adapter = DashScopeEmbeddingAdapter(base_url=base_url)
    query_result = await adapter.embed(
        api_key=api_key, texts=["语义索引连接验证"], text_type="query",
        model_id=model_id, dimension=dimension,
        instruct="Retrieve relevant evidence for a novel-writing workspace.",
    )
    document_result = await adapter.embed(
        api_key=api_key,
        texts=["这是用于验证语义索引写入能力的非敏感测试文本。"],
        text_type="document",
        model_id=model_id,
        dimension=dimension,
    )
    query_dimension = len(query_result.vectors[0].values)
    document_dimension = len(document_result.vectors[0].values)
    if query_dimension != document_dimension:
        raise EmbeddingLifecycleError(
            "dimension_mismatch", "query and document vector dimensions differ"
        )
    return _SentinelEvidence(
        query_request_id=query_result.request_id,
        document_request_id=document_result.request_id,
        actual_dimension=query_dimension,
        total_tokens=query_result.total_tokens + document_result.total_tokens,
        latency_ms=max(0, int((monotonic() - started) * 1000)),
    )


@router.post("/embedding-config/test")
async def embedding_config_test(
    request: ConnectionTestRequest, session: Session = Depends(get_session)
) -> dict[str, object]:
    try:
        base_url = normalize_dashscope_base_url(request.base_url)
        configuration = get_configuration(
            session, owner_id=LOCAL_OWNER_ID, workspace_id=LOCAL_WORKSPACE_ID
        )
        credential_ref = configuration.credential_ref if configuration else None
        session.rollback()
        evidence = await _sentinel(
            base_url=base_url, credential_ref=credential_ref,
            model_id=request.requested_model_id, dimension=request.requested_dimension,
            ephemeral_api_key=(request.api_key.get_secret_value() if request.api_key else None),
        )
        return {
            "connection_state": "ready", "request_id": evidence.query_request_id,
            "document_request_id": evidence.document_request_id,
            "actual_model_id": request.requested_model_id, "actual_revision": None,
            "actual_dimension": evidence.actual_dimension,
            "token_count": evidence.total_tokens, "latency_ms": evidence.latency_ms,
            "error_summary": None,
        }
    except Exception as error:
        _raise(error)
        raise


def _require_configuration_version(
    configuration: EmbeddingConfiguration | None,
    *,
    expected_version: int,
) -> None:
    if expected_version == 0:
        if configuration is not None:
            raise EmbeddingLifecycleError(
                "version_conflict", "embedding configuration changed"
            )
        return
    if configuration is None or configuration.version != expected_version:
        raise EmbeddingLifecycleError(
            "version_conflict", "embedding configuration changed"
        )


def _discard_temporary_secret(
    store: EmbeddingSecretStore,
    credential_ref: str | None,
) -> None:
    if credential_ref is None:
        return
    try:
        store.delete(credential_ref)
    except EmbeddingSecretError as error:
        raise EmbeddingSecretError(
            "SECRET_DELETE_FAILED",
            "临时 API Key 加密记录清理失败，请检查密钥保险箱",
        ) from error


def _delete_replaced_secret(
    session: Session,
    *,
    store: EmbeddingSecretStore,
    stale_credential_ref: str | None,
    active_credential_ref: str | None,
) -> str | None:
    if stale_credential_ref is None or stale_credential_ref == active_credential_ref:
        return None
    try:
        store.delete(stale_credential_ref)
        return None
    except EmbeddingSecretError as error:
        warning = "旧 API Key 加密记录未能自动清理，请检查密钥保险箱。"
        reference_digest = sha256(stale_credential_ref.encode("utf-8")).hexdigest()
        try:
            session.rollback()
            current = get_configuration(
                session,
                owner_id=LOCAL_OWNER_ID,
                workspace_id=LOCAL_WORKSPACE_ID,
                for_update=True,
            )
            if current is not None and current.credential_ref == active_credential_ref:
                summary = dict(current.connection_summary_json or {})
                summary["credential_cleanup"] = {
                    "state": "pending",
                    "error_code": error.code,
                    "reference_sha256": reference_digest,
                    "observed_at": datetime.now(UTC).isoformat(),
                }
                current.connection_summary_json = summary
                session.commit()
            else:
                session.rollback()
        except Exception:
            session.rollback()
        return warning


@router.put("/embedding-config/candidate")
async def embedding_candidate_put(
    request: CandidateRequest, session: Session = Depends(get_session)
) -> dict[str, object]:
    store = _secret_store()
    new_secret_ref: str | None = None
    committed_secret_ref: str | None = None
    old_secret_ref: str | None = None
    try:
        base_url = normalize_dashscope_base_url(request.base_url)
        configuration = get_configuration(
            session,
            owner_id=LOCAL_OWNER_ID,
            workspace_id=LOCAL_WORKSPACE_ID,
        )
        _require_configuration_version(
            configuration,
            expected_version=request.expected_version,
        )
        old_secret_ref = configuration.credential_ref if configuration is not None else None
        credential_ref = old_secret_ref
        last4 = configuration.api_key_last4 if configuration is not None else None
        ephemeral_key: str | None = None
        session.rollback()

        if request.api_key_action is CredentialAction.CLEAR:
            if configuration is None:
                raise EmbeddingLifecycleError(
                    "embedding_not_configured", "embedding configuration is missing"
                )
            current = get_configuration(
                session,
                owner_id=LOCAL_OWNER_ID,
                workspace_id=LOCAL_WORKSPACE_ID,
                for_update=True,
            )
            _require_configuration_version(
                current,
                expected_version=request.expected_version,
            )
            assert current is not None
            cleared = apply_credential_reference(
                session,
                owner_id=LOCAL_OWNER_ID,
                workspace_id=LOCAL_WORKSPACE_ID,
                expected_version=current.version,
                credential_ref=None,
                last4=None,
            )
            session.commit()
            warning = _delete_replaced_secret(
                session,
                store=store,
                stale_credential_ref=old_secret_ref,
                active_credential_ref=None,
            )
            payload = embedding_config_get(session)
            if warning:
                payload["credential_cleanup_warning"] = warning
            del cleared
            return payload

        if request.api_key_action is CredentialAction.REPLACE:
            assert request.api_key is not None
            ephemeral_key = request.api_key.get_secret_value().strip()
            stored = store.put(ephemeral_key)
            new_secret_ref = stored.credential_ref
            credential_ref, last4 = stored.credential_ref, stored.last4
        elif credential_ref is None:
            raise EmbeddingLifecycleError(
                "embedding_not_configured", "embedding credential is missing"
            )

        evidence = await _sentinel(
            base_url=base_url,
            credential_ref=credential_ref,
            model_id=request.requested_model_id,
            dimension=request.requested_dimension,
            ephemeral_api_key=ephemeral_key,
        )

        current = get_configuration(
            session,
            owner_id=LOCAL_OWNER_ID,
            workspace_id=LOCAL_WORKSPACE_ID,
            for_update=True,
        )
        _require_configuration_version(
            current,
            expected_version=request.expected_version,
        )
        if current is None:
            current = ensure_configuration(
                session,
                owner_id=LOCAL_OWNER_ID,
                workspace_id=LOCAL_WORKSPACE_ID,
                base_url=base_url,
            )
        current.base_url = base_url
        if request.api_key_action is CredentialAction.REPLACE:
            current = apply_credential_reference(
                session,
                owner_id=LOCAL_OWNER_ID,
                workspace_id=LOCAL_WORKSPACE_ID,
                expected_version=current.version,
                credential_ref=credential_ref,
                last4=last4,
            )
        saved_version = current.version
        _, generation = create_verified_candidate(
            session, owner_id=LOCAL_OWNER_ID, workspace_id=LOCAL_WORKSPACE_ID,
            expected_config_version=saved_version,
            requested_model_id=request.requested_model_id,
            actual_model_id=request.requested_model_id,
            actual_revision=None, dimension=evidence.actual_dimension,
            request_id=evidence.query_request_id,
            document_request_id=evidence.document_request_id,
            total_tokens=evidence.total_tokens,
            latency_ms=evidence.latency_ms,
        )
        session.commit()
        committed_secret_ref = credential_ref
        warning = None
        if request.api_key_action is CredentialAction.REPLACE:
            warning = _delete_replaced_secret(
                session,
                store=store,
                stale_credential_ref=old_secret_ref,
                active_credential_ref=credential_ref,
            )
        del generation
        payload = embedding_config_get(session)
        if warning:
            payload["credential_cleanup_warning"] = warning
        return payload
    except Exception as error:
        session.rollback()
        if new_secret_ref is not None and committed_secret_ref != new_secret_ref:
            try:
                _discard_temporary_secret(store, new_secret_ref)
            except EmbeddingSecretError as cleanup_error:
                _raise(cleanup_error)
                raise
        _raise(error)
        raise


@router.post("/embedding-config/candidate/rebuild", status_code=status.HTTP_202_ACCEPTED)
def embedding_candidate_rebuild(session: Session = Depends(get_session)) -> dict[str, object]:
    try:
        configuration = get_configuration(
            session, owner_id=LOCAL_OWNER_ID, workspace_id=LOCAL_WORKSPACE_ID,
            for_update=True,
        )
        if configuration is None or configuration.candidate_generation_id is None:
            raise EmbeddingLifecycleError("candidate_missing", "candidate generation is missing")
        builds = tuple(
            session.scalars(
                select(EmbeddingGenerationNovel).where(
                    EmbeddingGenerationNovel.generation_id == configuration.candidate_generation_id,
                    EmbeddingGenerationNovel.state == "pending",
                )
            )
        )
        for build in builds:
            prepare_v1_novel_index(
                session, generation_id=build.generation_id, novel_id=build.novel_id
            )
        session.commit()
        return _generation_payload(session, configuration.candidate_generation_id) or {}
    except Exception as error:
        session.rollback(); _raise(error); raise


@router.post("/embedding-config/candidate/cancel")
def embedding_candidate_cancel(
    request: CancelRequest, session: Session = Depends(get_session)
) -> dict[str, object]:
    del request
    try:
        configuration = get_configuration(
            session, owner_id=LOCAL_OWNER_ID, workspace_id=LOCAL_WORKSPACE_ID,
            for_update=True,
        )
        if configuration is None or configuration.candidate_generation_id is None:
            raise EmbeddingLifecycleError("candidate_missing", "candidate generation is missing")
        generation = session.get(EmbeddingGeneration, configuration.candidate_generation_id)
        if generation is not None and generation.state not in {"active", "retired"}:
            generation.state = "cancelled"
            for build in session.scalars(
                select(EmbeddingGenerationNovel).where(
                    EmbeddingGenerationNovel.generation_id == generation.id,
                    EmbeddingGenerationNovel.state.in_(("pending", "building")),
                )
            ):
                build.state = "cancelled"
                build.completed_at = datetime.now(UTC)
            jobs = tuple(
                session.scalars(
                    select(BackgroundJob)
                    .join(
                        EmbeddingIndexBatch,
                        EmbeddingIndexBatch.background_job_id == BackgroundJob.id,
                    )
                    .where(EmbeddingIndexBatch.generation_id == generation.id)
                )
            )
            for job in jobs:
                request_cancel(
                    session,
                    scope=NarrationRequestScope.fixed_local(),
                    job_id=job.id,
                    actor="local-author",
                    reason_code="EMBEDDING_GENERATION_CANCELLED",
                )
        configuration.candidate_generation_id = None
        configuration.version += 1
        session.commit()
        return {"cancelled": True}
    except Exception as error:
        session.rollback(); _raise(error); raise


@router.post("/embedding-config/candidate/activate")
def embedding_candidate_activate(
    request: VersionRequest, session: Session = Depends(get_session)
) -> dict[str, object]:
    try:
        configuration = get_configuration(
            session, owner_id=LOCAL_OWNER_ID, workspace_id=LOCAL_WORKSPACE_ID
        )
        if configuration is None or configuration.version != request.expected_version:
            raise EmbeddingLifecycleError("version_conflict", "embedding configuration changed")
        generation = activate_candidate_generation(
            session, owner_id=LOCAL_OWNER_ID, workspace_id=LOCAL_WORKSPACE_ID,
            expected_config_version=request.expected_version,
        )
        session.commit()
        return _generation_payload(session, generation.id) or {}
    except Exception as error:
        session.rollback(); _raise(error); raise


@router.post("/embedding-config/candidate/evaluate")
async def embedding_candidate_evaluate(
    request: VersionRequest, session: Session = Depends(get_session)
) -> dict[str, object]:
    """Run the fixed retrieval gate without changing the active generation."""

    try:
        configuration = get_configuration(
            session, owner_id=LOCAL_OWNER_ID, workspace_id=LOCAL_WORKSPACE_ID
        )
        if configuration is None or configuration.version != request.expected_version:
            raise EmbeddingLifecycleError("version_conflict", "embedding configuration changed")
        await _evaluate_candidate(session, configuration)
        return embedding_config_get(session)
    except Exception as error:
        session.rollback(); _raise(error); raise


@router.post("/embedding-config/rollback")
def embedding_generation_rollback(
    request: VersionRequest, session: Session = Depends(get_session)
) -> dict[str, object]:
    try:
        configuration = get_configuration(
            session, owner_id=LOCAL_OWNER_ID, workspace_id=LOCAL_WORKSPACE_ID,
            for_update=True,
        )
        if configuration is None or configuration.version != request.expected_version:
            raise EmbeddingLifecycleError("version_conflict", "embedding configuration changed")
        if configuration.previous_generation_id is None:
            raise EmbeddingLifecycleError("previous_generation_missing", "previous generation is missing")
        previous = session.get(EmbeddingGeneration, configuration.previous_generation_id)
        current = session.get(EmbeddingGeneration, configuration.active_generation_id)
        if previous is None or previous.state != "retired":
            raise EmbeddingLifecycleError("previous_generation_not_ready", "previous generation cannot be restored")
        if current is not None:
            current.state = "retired"; current.retired_at = datetime.now(UTC)
            session.flush()
        previous.state = "active"; previous.activated_at = datetime.now(UTC)
        previous.retired_at = None
        configuration.active_generation_id = previous.id
        configuration.previous_generation_id = current.id if current else None
        configuration.version += 1
        session.commit()
        return _generation_payload(session, previous.id) or {}
    except Exception as error:
        session.rollback(); _raise(error); raise


@router.get("/novels/{novel_id}/embedding-consent")
def embedding_consent_get(
    novel_id: UUID, session: Session = Depends(get_session)
) -> dict[str, object]:
    consent = session.scalar(
        select(NovelEmbeddingConsent)
        .where(NovelEmbeddingConsent.novel_id == novel_id)
        .order_by(NovelEmbeddingConsent.confirmed_at.desc())
    )
    if consent is None:
        return {
            "novel_id": str(novel_id), "state": "not_granted", "consent_id": None,
            "version": 0, "notice_version": None, "provider_id": None,
            "model_id": None, "confirmed_at": None, "revoked_at": None,
            "writing_query_authorized": False,
        }
    return {
        "novel_id": str(novel_id),
        "state": "granted" if consent.revoked_at is None else "revoked",
        "consent_id": str(consent.id), "notice_version": consent.notice_version,
        "version": 1 if consent.revoked_at is None else 2,
        "provider_id": consent.provider_id, "model_id": consent.model_id,
        "confirmed_at": consent.confirmed_at, "revoked_at": consent.revoked_at,
        "writing_query_authorized": (
            consent.revoked_at is None
            and consent.notice_version == NOVEL_EMBEDDING_CONSENT_NOTICE_VERSION
        ),
    }


@router.put("/novels/{novel_id}/embedding-consent")
def embedding_consent_put(
    novel_id: UUID,
    request: ConsentUiRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        if request.action is ConsentAction.GRANT:
            if request.notice_version != NOVEL_EMBEDDING_CONSENT_NOTICE_VERSION:
                raise EmbeddingLifecycleError(
                    "consent_notice_outdated", "writing queries require the current consent notice"
                )
            if request.expected_version not in {0, 1}:
                raise EmbeddingLifecycleError("version_conflict", "consent state changed")
            consent = grant_consent(
                session, novel_id=novel_id, owner_id=LOCAL_OWNER_ID,
                workspace_id=LOCAL_WORKSPACE_ID,
                idempotency_key=f"consent:{novel_id}:grant:{request.notice_version}",
                notice_version=request.notice_version,
                corpora=("manuscript", "planning", "private_asset"),
                actor="local-author",
            )
            request_active_novel_refresh(session, novel_id)
        else:
            if request.expected_version != 1:
                raise EmbeddingLifecycleError("version_conflict", "consent state changed")
            active = session.scalar(
                select(NovelEmbeddingConsent).where(
                    NovelEmbeddingConsent.novel_id == novel_id,
                    NovelEmbeddingConsent.revoked_at.is_(None),
                )
            )
            if active is None:
                raise EmbeddingLifecycleError("consent_not_found", "active consent was not found")
            consent = revoke_consent(
                session, novel_id=novel_id, consent_id=active.id,
                owner_id=LOCAL_OWNER_ID, workspace_id=LOCAL_WORKSPACE_ID,
                actor="local-author", reason="author_revoked",
            )
        session.commit()
        return embedding_consent_get(novel_id, session)
    except Exception as error:
        session.rollback(); _raise(error); raise


@router.get("/novels/{novel_id}/semantic-index/status")
def semantic_index_status(
    novel_id: UUID, session: Session = Depends(get_session)
) -> dict[str, object]:
    consent = session.scalar(
        select(NovelEmbeddingConsent).where(
            NovelEmbeddingConsent.novel_id == novel_id,
            NovelEmbeddingConsent.revoked_at.is_(None),
        )
    )
    configuration = get_configuration(
        session, owner_id=LOCAL_OWNER_ID, workspace_id=LOCAL_WORKSPACE_ID
    )
    active_generation_id = configuration.active_generation_id if configuration else None
    generation_id = active_generation_id
    build: EmbeddingGenerationNovel | None = None
    if generation_id is not None:
        build = session.scalar(
            select(EmbeddingGenerationNovel).where(
                EmbeddingGenerationNovel.generation_id == generation_id,
                EmbeddingGenerationNovel.novel_id == novel_id,
            )
        )
    active_generation = session.get(EmbeddingGeneration, active_generation_id) if active_generation_id else None
    active_profile = session.get(EmbeddingProfile, active_generation.profile_id) if active_generation else None
    corpus_rows = []
    if build is not None:
        corpus_rows = session.execute(
            select(
                SemanticSource.corpus,
                func.count(func.distinct(SemanticSource.id)),
                func.count(SemanticChunk.id),
            )
            .outerjoin(SemanticChunk, SemanticChunk.source_id == SemanticSource.id)
            .where(
                SemanticSource.generation_id == build.generation_id,
                SemanticSource.novel_id == novel_id,
                SemanticSource.status == "current",
            )
            .group_by(SemanticSource.corpus)
        ).all()
    by_corpus = {name: (int(source_count), int(chunk_count)) for name, source_count, chunk_count in corpus_rows}
    vector_count = int(
        session.scalar(
            select(func.count()).select_from(SemanticEmbedding).join(
                SemanticChunk, SemanticChunk.id == SemanticEmbedding.chunk_id
            ).join(SemanticSource, SemanticSource.id == SemanticChunk.source_id).where(
                SemanticSource.novel_id == novel_id
            )
        ) or 0
    )
    state = (
        "not_authorized" if consent is None else
        "empty" if build is None else
        "ready" if build.sync_state == "current" and build.generation_id == active_generation_id else
        "updating" if build.sync_state == "updating" else
        "outdated" if build.sync_state == "outdated" else
        "partial_failed" if build.sync_state == "partial_failed" else
        "revoked" if build.sync_state == "revoked" else
        "stale" if build.state == "stale" else
        "update_pending"
    )
    return {
        "novel_id": str(novel_id), "state": state,
        "active_model_id": active_profile.actual_model_id if active_profile else None,
        "active_dimension": active_profile.dimension if active_profile else None,
        "active_generation_number": active_generation.generation_number if active_generation else None,
        "corpora": [
            {
                "corpus": corpus.value,
                "state": (
                    "disabled" if corpus.value not in set(build.target_corpora_json if build else []) else
                    "failed" if build and build.state == "failed" else
                    "building" if build and build.state in {"pending", "building"} else
                    "ready" if by_corpus.get(corpus.value, (0, 0))[0] else "empty"
                ),
                "source_count": by_corpus.get(corpus.value, (0, 0))[0],
                "chunk_count": by_corpus.get(corpus.value, (0, 0))[1],
                "failure_count": build.failure_count if build and build.state == "failed" else 0,
                "reason_code": build.failure_code if build and build.state == "failed" else None,
            }
            for corpus in EmbeddingCorpus
        ],
        "source_count": build.source_count if build else 0,
        "chunk_count": build.chunk_count if build else 0,
        "failure_count": build.failure_count if build else 0,
        "last_indexed_at": build.completed_at if build else None,
        "index_version": build.index_version if build else None,
        "authority_digest": build.authority_digest if build else None,
        "published_digest": build.published_digest if build else None,
        "sync_state": build.sync_state if build else None,
        "pending_refresh_count": build.pending_refresh_count if build else 0,
        "error_summary": build.failure_code if build else None,
        "can_rebuild": consent is not None and active_generation_id is not None,
        "can_cancel": bool(build and build.state in {"pending", "building", "updating"}),
        "can_retry_failed": bool(build and build.state in {"failed", "partial_failed"}),
        "has_local_vectors": vector_count > 0,
    }


@router.post("/novels/{novel_id}/semantic-index/rebuild", status_code=status.HTTP_202_ACCEPTED)
def semantic_index_rebuild(
    novel_id: UUID, session: Session = Depends(get_session)
) -> dict[str, object]:
    try:
        configuration = get_configuration(
            session, owner_id=LOCAL_OWNER_ID, workspace_id=LOCAL_WORKSPACE_ID
        )
        if configuration is None or configuration.active_generation_id is None:
            raise EmbeddingLifecycleError("active_generation_missing", "activate an embedding generation first")
        build = prepare_v1_novel_index(
            session, generation_id=configuration.active_generation_id, novel_id=novel_id
        )
        session.commit()
        return semantic_index_status(novel_id, session)
    except Exception as error:
        session.rollback(); _raise(error); raise


@router.post("/novels/{novel_id}/semantic-index/cancel")
def semantic_index_cancel(
    novel_id: UUID, request: CancelRequest, session: Session = Depends(get_session)
) -> dict[str, object]:
    del request
    builds = tuple(
        session.scalars(
            select(EmbeddingGenerationNovel).where(
                EmbeddingGenerationNovel.novel_id == novel_id,
                EmbeddingGenerationNovel.state.in_(("pending", "building", "updating")),
            )
        )
    )
    generation_ids = tuple(build.generation_id for build in builds)
    for build in builds:
        build.state = "cancelled"; build.completed_at = datetime.now(UTC)
    if generation_ids:
        jobs = tuple(
            session.scalars(
                select(BackgroundJob)
                .join(
                    EmbeddingIndexBatch,
                    EmbeddingIndexBatch.background_job_id == BackgroundJob.id,
                )
                .where(
                    EmbeddingIndexBatch.generation_id.in_(generation_ids),
                    EmbeddingIndexBatch.novel_id == novel_id,
                )
            )
        )
        for job in jobs:
            request_cancel(
                session,
                scope=NarrationRequestScope.fixed_local(),
                job_id=job.id,
                actor="local-author",
                reason_code="EMBEDDING_NOVEL_BUILD_CANCELLED",
            )
    session.commit()
    return semantic_index_status(novel_id, session)


@router.post("/novels/{novel_id}/semantic-index/retry-failed", status_code=status.HTTP_202_ACCEPTED)
def semantic_index_retry_failed(
    novel_id: UUID, session: Session = Depends(get_session)
) -> dict[str, object]:
    configuration = get_configuration(
        session, owner_id=LOCAL_OWNER_ID, workspace_id=LOCAL_WORKSPACE_ID
    )
    if configuration is None or configuration.active_generation_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "active_generation_missing"})
    rows = session.execute(
        select(EmbeddingIndexBatch, BackgroundJob)
        .join(BackgroundJob, BackgroundJob.id == EmbeddingIndexBatch.background_job_id)
        .where(
            EmbeddingIndexBatch.generation_id == configuration.active_generation_id,
            EmbeddingIndexBatch.novel_id == novel_id,
            EmbeddingIndexBatch.state == "failed",
            BackgroundJob.state.in_(("failed", "dead_letter")),
        )
    ).all()
    try:
        for batch, job in rows:
            manual_retry(
                session, scope=NarrationRequestScope.fixed_local(), job_id=job.id,
                actor="local-author", reason="retry failed embedding batch",
                idempotency_key=f"semantic-retry:{job.id}:{job.attempt_count}",
            )
            batch.state = "queued"; batch.failure_code = None
        build = session.scalar(
            select(EmbeddingGenerationNovel).where(
                EmbeddingGenerationNovel.generation_id == configuration.active_generation_id,
                EmbeddingGenerationNovel.novel_id == novel_id,
            )
        )
        if build is not None and rows:
            build.state = "building"; build.failure_code = None
        session.commit()
        return semantic_index_status(novel_id, session)
    except Exception as error:
        session.rollback(); _raise(error); raise


@router.delete("/novels/{novel_id}/semantic-index")
def semantic_index_delete(
    novel_id: UUID, session: Session = Depends(get_session)
) -> dict[str, object]:
    source_ids = select(SemanticSource.id).where(SemanticSource.novel_id == novel_id)
    chunk_ids = select(SemanticChunk.id).where(SemanticChunk.source_id.in_(source_ids))
    deleted = session.execute(
        delete(SemanticEmbedding).where(SemanticEmbedding.chunk_id.in_(chunk_ids))
    ).rowcount
    for source in session.scalars(select(SemanticSource).where(SemanticSource.novel_id == novel_id)):
        source.status = "retired"
    for build in session.scalars(
        select(EmbeddingGenerationNovel).where(EmbeddingGenerationNovel.novel_id == novel_id)
    ):
        build.state = "stale"
    session.commit()
    result = semantic_index_status(novel_id, session)
    result["deleted_embeddings"] = int(deleted or 0)
    return result


def _inheritance_scope(
    session: Session,
    *,
    novel_id: UUID,
    requested: UUID | None,
    story_cutoff: int | None,
) -> tuple[frozenset[UUID], tuple[tuple[UUID, int | None], ...]]:
    timelines = tuple(
        session.scalars(
            select(StoryTimeline).where(
                StoryTimeline.novel_id == novel_id,
                StoryTimeline.lifecycle_state == "active",
            )
        )
    )
    if requested is None:
        if len(timelines) != 1:
            raise EmbeddingLifecycleError("timeline_required", "timeline is required")
        requested = timelines[0].id
    by_id = {item.id: item for item in timelines}
    if requested not in by_id:
        raise EmbeddingLifecycleError("timeline_not_found", "timeline is not active")
    path: set[UUID] = set()
    target_to_root: list[tuple[UUID, int | None]] = []
    current: UUID | None = requested
    current_limit = story_cutoff
    while current is not None:
        if current in path or current not in by_id:
            raise EmbeddingLifecycleError("timeline_conflict", "timeline inheritance is invalid")
        path.add(current)
        timeline = by_id[current]
        target_to_root.append((current, current_limit))
        parent_id = timeline.parent_timeline_id
        if parent_id is not None:
            fork_limit = timeline.fork_story_sequence
            if fork_limit is None:
                raise EmbeddingLifecycleError(
                    "timeline_conflict", "inherited timeline has no fork anchor"
                )
            current_limit = (
                fork_limit if current_limit is None else min(current_limit, fork_limit)
            )
        current = parent_id
    return frozenset(path), tuple(reversed(target_to_root))


def _story_fact_source_is_effective(session: Session, fact: StoryFact) -> bool:
    if fact.status not in {"active", "source_restored"}:
        return False
    if fact.source_revision_id is None:
        return True
    bindings = tuple(
        session.scalars(
            select(DerivedSourceBinding).where(
                DerivedSourceBinding.derived_entity_type == "story_fact",
                DerivedSourceBinding.derived_entity_id == fact.id,
                DerivedSourceBinding.source_chapter_revision_id
                == fact.source_revision_id,
            )
        )
    )
    return bool(bindings) and all(
        item.validity_state in {"current", "source_restored"} for item in bindings
    )


def _known_visibility_keys(
    session: Session,
    *,
    novel_id: UUID,
    scope: KnowledgeProjectionScope,
) -> frozenset[str]:
    observer_id = scope.observer_character_instance_id
    if scope.perspective != "character_instance" or observer_id is None:
        return frozenset()
    rows = tuple(
        session.scalars(
            select(StoryFact)
            .where(
                StoryFact.novel_id == novel_id,
                StoryFact.schema_version == "story-fact/2",
                StoryFact.fact_type == "knowledge_event",
                StoryFact.character_instance_id == observer_id,
                StoryFact.timeline_id.in_(tuple(scope.reachable_timeline_ids)),
                StoryFact.status.in_(("active", "source_restored")),
            )
            .order_by(StoryFact.created_at, StoryFact.id)
        )
    )
    facts: list[StoryFactV2] = []
    row_by_id: dict[UUID, StoryFact] = {}
    for row in rows:
        try:
            fact = StoryFactV2.model_validate(row)
        except ValueError:
            # A malformed row cannot grant visibility; search fails closed.
            continue
        facts.append(fact)
        row_by_id[fact.id] = row
    bindings_by_fact: dict[UUID, list[DerivedSourceBinding]] = {}
    if row_by_id:
        for binding in session.scalars(
            select(DerivedSourceBinding).where(
                DerivedSourceBinding.derived_entity_type == "story_fact",
                DerivedSourceBinding.derived_entity_id.in_(tuple(row_by_id)),
            )
        ):
            bindings_by_fact.setdefault(binding.derived_entity_id, []).append(binding)
    source_validity: dict[UUID, bool] = {}
    for fact in facts:
        if fact.source_revision_id is not None:
            matching = [
                item
                for item in bindings_by_fact.get(fact.id, ())
                if item.source_chapter_revision_id == fact.source_revision_id
            ]
            current = bool(matching) and all(
                item.validity_state in {"current", "source_restored"}
                for item in matching
            )
            previous = source_validity.get(fact.source_revision_id)
            source_validity[fact.source_revision_id] = (
                current if previous is None else previous and current
            )
    return derive_known_visibility_keys(
        facts,
        scope=scope,
        source_revision_validity=source_validity,
    )


def _source_is_current(session: Session, source: SemanticSource) -> bool:
    if source.status != "current":
        return False
    if source.source_type == "chapter_revision":
        return session.scalar(
            select(func.count()).select_from(DocumentWorkingCopy).where(
                DocumentWorkingCopy.document_id == source.source_entity_id,
                DocumentWorkingCopy.base_revision_id == source.source_revision_id,
            )
        ) == 1
    if source.source_type == "outline_revision":
        head = session.get(NovelOutlineHead, source.novel_id)
        return head is not None and head.current_revision_id == source.source_revision_id
    if source.source_type == "setting_revision":
        head = session.get(NovelSettingHead, source.novel_id)
        return head is not None and head.current_revision_id == source.source_revision_id
    if source.source_type == "private_asset_version":
        return session.scalar(
            select(func.count()).select_from(NovelAssetBinding).where(
                NovelAssetBinding.novel_id == source.novel_id,
                NovelAssetBinding.asset_id == source.source_entity_id,
                NovelAssetBinding.asset_version_id == source.source_revision_id,
                NovelAssetBinding.lifecycle_state == "active",
            )
        ) == 1
    if source.source_type == "story_fact":
        fact = session.get(StoryFact, source.source_entity_id)
        return (
            fact is not None
            and fact.novel_id == source.novel_id
            and fact.source_revision_id == source.source_revision_id
            and _story_fact_source_is_effective(session, fact)
        )
    return False


def _candidate(
    session: Session,
    *,
    source: SemanticSource,
    chunk: SemanticChunk,
    generation_id: UUID,
    index_version: int,
) -> RetrievalCandidate:
    visibility_json = source.visibility_json or {}
    visibility_value = str(
        visibility_json.get("visibility")
        or visibility_json.get("visibility_key")
        or "public"
    )
    if visibility_value in {"author", "author_only", "secret"}:
        visibility = CandidateVisibility.AUTHOR_ONLY
    elif visibility_value in {"knowledge", "knowledge_scoped"}:
        visibility = CandidateVisibility.KNOWLEDGE
    else:
        visibility = CandidateVisibility.PUBLIC
    raw_keys = visibility_json.get("required_knowledge_keys") or ()
    required_keys = frozenset(str(item) for item in raw_keys if str(item).strip())
    return RetrievalCandidate(
        chunk_id=chunk.id,
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        novel_id=source.novel_id,
        generation_id=generation_id,
        index_version=index_version,
        corpus=EmbeddingCorpus(source.corpus),
        source_type=source.source_type,
        source_id=source.source_entity_id,
        source_revision_id=source.source_revision_id,
        chunk_ordinal=chunk.chunk_index,
        text=chunk.content_text,
        source_current=_source_is_current(session, source),
        binding_permitted=(
            source.source_type != "private_asset_version"
            or _source_is_current(session, source)
        ),
        timeline_id=source.timeline_id,
        narrative_sequence_start=source.narrative_sequence_start,
        narrative_sequence_end=source.narrative_sequence_end,
        story_sequence_start=source.story_sequence_start,
        story_sequence_end=source.story_sequence_end,
        visibility=visibility,
        required_knowledge_keys=required_keys,
    )


def _source_state(source_type: str) -> str:
    if source_type == "chapter_revision":
        return "current_revision"
    if source_type == "private_asset_version":
        return "bound_asset_version"
    if source_type == "story_fact":
        return "accepted_story_fact"
    return "current_entity_revision"


def _author_visible_snippet(chunks: Iterable[Any]) -> str:
    return "\n".join(
        author_visible_v1_snippet(chunk.text)
        for chunk in chunks
    )[:4000]


def _local_authority_search_payload(
    session: Session,
    *,
    novel_id: UUID,
    request: SemanticSearchRequest,
    timeline_limits: tuple[tuple[UUID, int | None], ...],
    narrative_cutoff: int | None,
    index_status: str,
) -> dict[str, object]:
    perspective_map = {
        PerspectiveKind.AUTHOR: RetrievalPerspective.AUTHOR,
        PerspectiveKind.READER: RetrievalPerspective.READER,
        PerspectiveKind.CHARACTER_INSTANCE: RetrievalPerspective.CHARACTER_INSTANCE,
    }
    try:
        local_result = search_local_authority(
            session,
            LocalLexicalSearchRequest(
                owner_id=LOCAL_OWNER_ID,
                workspace_id=LOCAL_WORKSPACE_ID,
                novel_id=novel_id,
                query=request.query,
                corpora=frozenset(request.corpora),
                top_k=request.top_k,
                target_timeline_id=(timeline_limits[-1][0] if timeline_limits else None),
                narrative_sequence_cutoff=narrative_cutoff,
                story_sequence_cutoff=request.story_sequence_cutoff,
                timeline_limits=tuple(
                    LocalTimelineLimit(
                        timeline_id=timeline_id,
                        story_sequence_cutoff=cutoff,
                    )
                    for timeline_id, cutoff in timeline_limits
                ),
                perspective=perspective_map[request.perspective.kind],
            ),
        )
    except LocalLexicalScopeError as error:
        raise EmbeddingLifecycleError(error.code, error.message) from error
    public_hits = local_result.as_semantic_search_hits()
    omission_summary = list(local_result.diagnostics.omission_summary)
    return {
        "schema_version": request.schema_version,
        "request_id": f"semantic:{datetime.now(UTC).timestamp()}",
        # Authority-local chunks are not members of an embedding generation.
        "generation_id": None,
        "index_version": None,
        # Keep the public query/fusion policy stable.  The authority fallback's
        # renderer/chunker identity is encoded in deterministic chunk IDs.
        "retrieval_policy_version": "writing-retrieval/2",
        "mode": "lexical_only",
        "index_status": index_status,
        "hits": [item.model_dump(mode="json") for item in public_hits],
        "omitted_count": sum(int(item["count"]) for item in omission_summary),
        "warnings": ["dense_unavailable"],
        "provider_request_id": None,
        "token_count": None,
        "latency_ms": None,
        "degraded_reason": "dense_unavailable",
        "omission_summary": omission_summary,
    }


@router.post("/novels/{novel_id}/semantic-search")
async def semantic_search(
    novel_id: UUID, request: SemanticSearchRequest, session: Session = Depends(get_session)
) -> dict[str, object]:
    try:
        configuration = get_configuration(
            session, owner_id=LOCAL_OWNER_ID, workspace_id=LOCAL_WORKSPACE_ID
        )
        consent = session.scalar(
            select(NovelEmbeddingConsent).where(
                NovelEmbeddingConsent.novel_id == novel_id,
                NovelEmbeddingConsent.revoked_at.is_(None),
            )
        )
        generation = (
            session.get(EmbeddingGeneration, configuration.active_generation_id)
            if configuration is not None and configuration.active_generation_id is not None
            else None
        )
        build = (
            session.scalar(
                select(EmbeddingGenerationNovel).where(
                    EmbeddingGenerationNovel.generation_id == generation.id,
                    EmbeddingGenerationNovel.novel_id == novel_id,
                )
            )
            if generation is not None and generation.state == "active"
            else None
        )
        path, timeline_limits = _inheritance_scope(
            session,
            novel_id=novel_id,
            requested=request.timeline_id,
            story_cutoff=request.story_sequence_cutoff,
        )
        narrative_cutoff = request.narrative_sequence
        if (
            narrative_cutoff is not None
            and request.retrieval_purpose
            in {ApiRetrievalPurpose.CHAPTER_BODY, ApiRetrievalPurpose.CHAPTER_OUTLINE}
        ):
            narrative_cutoff = max(0, narrative_cutoff - 1)
        perspective_map = {
            PerspectiveKind.AUTHOR: RetrievalPerspective.AUTHOR,
            PerspectiveKind.READER: RetrievalPerspective.READER,
            PerspectiveKind.CHARACTER_INSTANCE: RetrievalPerspective.CHARACTER_INSTANCE,
        }
        generation_id = generation.id if generation is not None else None
        if generation_id is None or build is None:
            return _local_authority_search_payload(
                session,
                novel_id=novel_id,
                request=request,
                timeline_limits=timeline_limits,
                narrative_cutoff=narrative_cutoff,
                index_status="not_built",
            )
        eligible_conditions: list[object] = []
        eligible_conditions.extend(
            (
                SemanticSource.generation_id == generation_id,
                SemanticSource.novel_id == novel_id,
                SemanticSource.corpus.in_(tuple(item.value for item in request.corpora)),
                SemanticSource.status == "current",
                or_(
                    SemanticSource.timeline_id.is_(None),
                    SemanticSource.timeline_id.in_(tuple(path)),
                ),
            )
        )
        if narrative_cutoff is not None:
            eligible_conditions.append(
                or_(
                    SemanticSource.source_type != "chapter_revision",
                    and_(
                        SemanticSource.narrative_sequence_start.is_not(None),
                        SemanticSource.narrative_sequence_start <= narrative_cutoff,
                    ),
                )
            )
        story_filters = [SemanticSource.timeline_id.is_(None)]
        for scoped_timeline_id, cutoff in timeline_limits:
            timeline_filter = SemanticSource.timeline_id == scoped_timeline_id
            if cutoff is not None:
                timeline_filter = and_(
                    timeline_filter,
                    SemanticSource.story_sequence_start.is_not(None),
                    SemanticSource.story_sequence_start <= cutoff,
                )
            story_filters.append(timeline_filter)
        eligible_conditions.append(or_(*story_filters))

        legacy_scope = KnowledgeProjectionScope(
            novel_id=novel_id,
            reachable_timeline_ids=path,
            story_sequence_cutoff=request.story_sequence_cutoff,
            perspective=request.perspective.kind.value,
            observer_character_instance_id=request.perspective.character_instance_id,
            timeline_sequence_limits=timeline_limits,
        )
        known_visibility_keys = _known_visibility_keys(
            session,
            novel_id=novel_id,
            scope=legacy_scope,
        )

        dense_status = RetrievalChannelStatus.UNAVAILABLE
        dense_scores: tuple[RawChannelScore, ...] = ()
        dense_error = "dense index, v2 consent, or credential unavailable"
        provider_request_id = None
        provider_token_count = None
        provider_latency_ms = None
        dense_allowed = (
            consent is not None
            and consent.notice_version == NOVEL_EMBEDDING_CONSENT_NOTICE_VERSION
            and build.published_digest != "0" * 64
            and configuration.credential_ref is not None
        )
        profile = session.get(EmbeddingProfile, generation.profile_id)
        if dense_allowed and profile is not None:
            try:
                expected_generation_id = generation.id
                expected_index_version = build.index_version
                expected_published_digest = build.published_digest
                expected_authority_digest = build.authority_digest
                credential_ref = configuration.credential_ref
                profile_base_url = profile.base_url
                profile_model_id = profile.actual_model_id
                profile_dimension = profile.dimension
                session.rollback()
                api_key = _secret_store().get(credential_ref)
                started = monotonic()
                query_result = await asyncio.wait_for(
                    DashScopeEmbeddingAdapter(base_url=profile_base_url).embed(
                        api_key=api_key, texts=[request.query], text_type="query",
                        model_id=profile_model_id, dimension=profile_dimension,
                        instruct=(
                            "Retrieve only current, scope-valid evidence for this novel-writing task."
                        ),
                    ),
                    timeout=8.0,
                )
                provider_latency_ms = int((monotonic() - started) * 1000)
                provider_request_id = query_result.request_id
                provider_token_count = query_result.total_tokens
                current_configuration = get_configuration(
                    session,
                    owner_id=LOCAL_OWNER_ID,
                    workspace_id=LOCAL_WORKSPACE_ID,
                )
                current_build = session.scalar(
                    select(EmbeddingGenerationNovel).where(
                        EmbeddingGenerationNovel.generation_id == expected_generation_id,
                        EmbeddingGenerationNovel.novel_id == novel_id,
                    )
                )
                current_consent = session.scalar(
                    select(NovelEmbeddingConsent).where(
                        NovelEmbeddingConsent.novel_id == novel_id,
                        NovelEmbeddingConsent.revoked_at.is_(None),
                        NovelEmbeddingConsent.notice_version
                        == NOVEL_EMBEDDING_CONSENT_NOTICE_VERSION,
                    )
                )
                if (
                    current_configuration is None
                    or current_configuration.active_generation_id
                    != expected_generation_id
                    or current_build is None
                    or current_build.index_version != expected_index_version
                    or current_build.published_digest != expected_published_digest
                    or current_build.authority_digest != expected_authority_digest
                    or current_consent is None
                ):
                    raise EmbeddingLifecycleError(
                        "semantic_scope_changed", "semantic scope changed during query"
                    )
                distance = SemanticEmbedding.embedding.cosine_distance(
                    list(query_result.vectors[0].values)
                )
                dense_rows = session.execute(
                    select(SemanticChunk.id, distance.label("dense_distance"))
                    .select_from(SemanticSource)
                    .join(SemanticChunk, SemanticChunk.source_id == SemanticSource.id)
                    .join(
                        SemanticEmbedding,
                        and_(
                            SemanticEmbedding.chunk_id == SemanticChunk.id,
                            SemanticEmbedding.generation_id == expected_generation_id,
                        ),
                    )
                    .where(*eligible_conditions, distance <= 2.0)
                    .order_by(distance)
                ).all()
                dense_scores = tuple(
                    RawChannelScore(chunk_id=chunk_id, score=1.0 - float(distance_value))
                    for chunk_id, distance_value in dense_rows
                )
                dense_status = RetrievalChannelStatus.AVAILABLE
                dense_error = None
            except asyncio.TimeoutError:
                dense_status = RetrievalChannelStatus.TIMEOUT
                dense_error = "dense query timed out"
            except (EmbeddingAdapterError, EmbeddingSecretError):
                dense_status = RetrievalChannelStatus.NETWORK_FAILURE
                dense_error = "dense provider unavailable"
            except EmbeddingLifecycleError:
                dense_status = RetrievalChannelStatus.UNAVAILABLE
                dense_error = "semantic scope changed during dense query"

        similarity = func.similarity(SemanticChunk.content_text, request.query)
        candidate_rows = session.execute(
            select(SemanticSource, SemanticChunk, similarity.label("lexical_score"))
            .join(SemanticChunk, SemanticChunk.source_id == SemanticSource.id)
            .where(*eligible_conditions)
            .order_by(SemanticSource.id, SemanticChunk.chunk_index)
        ).all()
        if not candidate_rows:
            return _local_authority_search_payload(
                session,
                novel_id=novel_id,
                request=request,
                timeline_limits=timeline_limits,
                narrative_cutoff=narrative_cutoff,
                index_status=(
                    "ready" if build.sync_state == "current" else build.sync_state
                ),
            )
        candidates = tuple(
            _candidate(
                session,
                source=source,
                chunk=chunk,
                generation_id=generation_id,
                index_version=build.index_version,
            )
            for source, chunk, _ in candidate_rows
        )
        lexical_scores = tuple(
            RawChannelScore(chunk_id=chunk.id, score=float(score_value))
            for _, chunk, score_value in candidate_rows
            if float(score_value) > 0.01
        )

        purpose_map = {
            ApiRetrievalPurpose.MANUAL_SEARCH: CoreRetrievalPurpose.REVIEW,
            ApiRetrievalPurpose.CHAPTER_BODY: CoreRetrievalPurpose.CHAPTER_BODY,
            ApiRetrievalPurpose.CHAPTER_OUTLINE: CoreRetrievalPurpose.CHAPTER_OUTLINE,
            ApiRetrievalPurpose.CHAPTER_REVIEW: CoreRetrievalPurpose.CHAPTER_REVIEW,
            ApiRetrievalPurpose.SELECTION_REWRITE: CoreRetrievalPurpose.SELECTION_REWRITE,
            ApiRetrievalPurpose.SELECTION_EXPAND: CoreRetrievalPurpose.EXPAND,
            ApiRetrievalPurpose.SELECTION_DIALOGUE: CoreRetrievalPurpose.DIALOGUE,
            ApiRetrievalPurpose.SELECTION_REVIEW: CoreRetrievalPurpose.REVIEW,
            ApiRetrievalPurpose.SELECTION_CUSTOM: CoreRetrievalPurpose.CUSTOM,
        }
        core_scope = SearchScope(
            owner_id=LOCAL_OWNER_ID,
            workspace_id=LOCAL_WORKSPACE_ID,
            novel_id=novel_id,
            generation_id=generation_id,
            index_version=build.index_version,
            corpora=frozenset(request.corpora),
            target_timeline_id=timeline_limits[-1][0] if timeline_limits else None,
            narrative_sequence_cutoff=narrative_cutoff,
            story_sequence_cutoff=request.story_sequence_cutoff,
            timeline_limits=tuple(
                TimelineSearchLimit(
                    timeline_id=timeline_id,
                    story_sequence_cutoff=cutoff,
                )
                for timeline_id, cutoff in timeline_limits
            ),
            perspective=perspective_map[request.perspective.kind],
            observer_character_instance_id=request.perspective.character_instance_id,
            knowledge_keys=known_visibility_keys,
        )
        policy = RetrievalPolicyV1(
            policy_version=(
                configuration.retrieval_policy_version or "writing-retrieval/2"
            )
        )
        core_result = retrieve(
            SemanticSearchRequestV2(
                query=request.query,
                purpose=purpose_map[request.retrieval_purpose],
                use_novel_context=(
                    request.retrieval_purpose is ApiRetrievalPurpose.SELECTION_CUSTOM
                ),
                scope=core_scope,
                top_k=request.top_k,
            ),
            candidates=candidates,
            lexical=RetrievalChannelEvidence(
                channel=RetrievalChannel.LEXICAL,
                status=RetrievalChannelStatus.AVAILABLE,
                scores=lexical_scores,
                latency_ms=0,
            ),
            dense=RetrievalChannelEvidence(
                channel=RetrievalChannel.DENSE,
                status=dense_status,
                scores=dense_scores,
                provider_request_id=provider_request_id,
                token_count=provider_token_count,
                latency_ms=provider_latency_ms,
                redacted_error=dense_error,
            ),
            policy=policy,
        )
        candidate_by_id = {item.chunk_id: item for item in candidates}
        warnings = (
            [core_result.degradation_reason.value]
            if core_result.degradation_reason is not None
            else []
        )
        return {
            "schema_version": request.schema_version,
            "request_id": f"semantic:{datetime.now(UTC).timestamp()}",
            "generation_id": str(generation_id) if generation_id else None,
            "index_version": build.index_version if build else None,
            "retrieval_policy_version": core_result.policy_version,
            "mode": core_result.mode.value,
            "index_status": (
                "ready" if build is not None and build.sync_state == "current"
                else build.sync_state if build is not None else "not_built"
            ),
            "hits": [
                {
                    "corpus": item.corpus.value,
                    "source_type": item.source_type,
                    "source_state": _source_state(item.source_type),
                    "source_id": str(item.source_id),
                    "source_revision_id": str(item.source_revision_id) if item.source_revision_id else None,
                    "chunk_id": str(item.anchor_chunk_id),
                    "timeline_id": str(candidate_by_id[item.anchor_chunk_id].timeline_id) if candidate_by_id[item.anchor_chunk_id].timeline_id else None,
                    "character_instance_id": None,
                    "narrative_sequence_start": candidate_by_id[item.anchor_chunk_id].narrative_sequence_start,
                    "narrative_sequence_end": candidate_by_id[item.anchor_chunk_id].narrative_sequence_end,
                    "story_sequence_start": candidate_by_id[item.anchor_chunk_id].story_sequence_start,
                    "story_sequence_end": candidate_by_id[item.anchor_chunk_id].story_sequence_end,
                    "snippet": _author_visible_snippet(item.chunks),
                    "channels": [channel.value for channel in item.channels],
                    "lexical_score": item.lexical_raw_score,
                    "dense_distance": (
                        1.0 - item.dense_raw_score
                        if item.dense_raw_score is not None
                        else None
                    ),
                    "fused_score": item.fused_score,
                }
                for item in core_result.hits
            ],
            "omitted_count": (
                core_result.diagnostics.below_threshold_count
                + core_result.diagnostics.duplicate_source_count
                + core_result.diagnostics.quota_omitted_count
                + core_result.diagnostics.top_k_omitted_count
            ),
            "warnings": warnings,
            "provider_request_id": core_result.dense.provider_request_id,
            "token_count": core_result.dense.token_count,
            "latency_ms": core_result.dense.latency_ms,
            "degraded_reason": warnings[0] if warnings else None,
            "omission_summary": [
                {
                    "reason": item.reason.value,
                    "count": item.count,
                }
                for item in core_result.diagnostics.filtered
            ],
        }
    except Exception as error:
        _raise(error); raise
