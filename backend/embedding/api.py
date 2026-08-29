"""PawApp-owned embedding configuration, consent and semantic-index routes."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from time import monotonic
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from sqlalchemy import delete, func, select
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
from ..database import get_session
from .adapter import DashScopeEmbeddingAdapter, EmbeddingAdapterError, normalize_dashscope_base_url
from .contracts import (
    ConsentAction,
    CredentialAction,
    EmbeddingCorpus,
    NovelEmbeddingConsentMutation,
    PerspectiveKind,
    SUPPORTED_EMBEDDING_DIMENSIONS,
    SemanticSearchRequest,
    TARGET_CANDIDATE_DIMENSION,
)
from .indexing import prepare_v1_novel_index
from .evaluation import EvaluationCase, evaluate_rankings
from .lifecycle import EmbeddingLifecycleError
from .persistence import (
    activate_candidate_generation,
    apply_credential_reference,
    create_verified_candidate,
    ensure_configuration,
    get_configuration,
    grant_consent,
    revoke_consent,
)
from .search import Candidate, SearchScope, reciprocal_rank_fusion
from .search import derive_known_visibility_keys
from .secrets import EmbeddingSecretError, EmbeddingSecretStore
from ..models import BackgroundJob, DerivedSourceBinding, DocumentWorkingCopy, StoryFact
from ..narration.contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID, NarrationRequestScope
from ..narration.jobs import manual_retry
from ..story_state.contracts import StoryFactV2


router = APIRouter(tags=["embedding"])
DEFAULT_BASE_URL = "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1"
SECRET_ROOT_ENV = "AI_NOVEL_EMBEDDING_SECRET_ROOT_KEY_FILE"
SECRET_DIR_ENV = "AI_NOVEL_EMBEDDING_SECRET_RECORDS_DIR"


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
    rows = session.execute(
        select(SemanticSource, SemanticChunk, SemanticEmbedding)
        .join(SemanticChunk, SemanticChunk.source_id == SemanticSource.id)
        .join(
            SemanticEmbedding,
            (SemanticEmbedding.chunk_id == SemanticChunk.id)
            & (SemanticEmbedding.generation_id == generation.id),
        )
        .where(
            SemanticSource.generation_id == generation.id,
            SemanticSource.status == "current",
        )
        .order_by(
            SemanticSource.novel_id,
            SemanticSource.corpus,
            SemanticSource.id,
            SemanticChunk.chunk_index,
        )
    ).all()
    grouped: dict[tuple[UUID, str], list[tuple[UUID, tuple[float, ...], str]]] = {}
    for source, chunk, embedding in rows:
        grouped.setdefault((source.novel_id, source.corpus), []).append(
            (chunk.id, tuple(float(value) for value in embedding.embedding), chunk.content_text)
        )
    cases: list[EvaluationCase] = []
    for key in sorted(grouped, key=lambda item: (str(item[0]), item[1])):
        candidates = grouped[key]
        for expected_id, _, text_value in candidates[:5]:
            query = text_value.strip()[:240]
            if query:
                cases.append(
                    EvaluationCase(
                        query=query,
                        expected_chunk_id=expected_id,
                        candidate_vectors=tuple((chunk_id, vector) for chunk_id, vector, _ in candidates),
                    )
                )
    if not cases:
        raise EmbeddingLifecycleError(
            "candidate_evaluation_empty", "candidate has no fixed retrieval evaluation cases"
        )
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
    generation.evaluation_summary_json = {"case_count": len(cases)}
    session.commit()

    api_key = _secret_store().get(credential_ref)
    adapter = DashScopeEmbeddingAdapter(base_url=base_url)
    query_vectors: list[tuple[float, ...]] = []
    request_ids: list[str] = []
    total_tokens = 0
    for start in range(0, len(cases), 10):
        batch = cases[start : start + 10]
        result = await adapter.embed(
            api_key=api_key,
            texts=[item.query for item in batch],
            text_type="query",
            model_id=model_id,
            dimension=dimension,
            instruct="Retrieve the matching evidence from this novel corpus.",
        )
        query_vectors.extend(tuple(float(value) for value in item.values) for item in result.vectors)
        request_ids.append(result.request_id)
        total_tokens += result.total_tokens
    summary = evaluate_rankings(tuple(cases), tuple(query_vectors))
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
    current.evaluation_state = "passed" if summary.passed else "failed"
    current.evaluation_summary_json = {
        **summary.as_json(),
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
            "base_url": DEFAULT_BASE_URL,
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
        }
    return {
        "novel_id": str(novel_id),
        "state": "granted" if consent.revoked_at is None else "revoked",
        "consent_id": str(consent.id), "notice_version": consent.notice_version,
        "version": 1 if consent.revoked_at is None else 2,
        "provider_id": consent.provider_id, "model_id": consent.model_id,
        "confirmed_at": consent.confirmed_at, "revoked_at": consent.revoked_at,
    }


@router.put("/novels/{novel_id}/embedding-consent")
def embedding_consent_put(
    novel_id: UUID,
    request: ConsentUiRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        if request.action is ConsentAction.GRANT:
            if request.expected_version != 0:
                raise EmbeddingLifecycleError("version_conflict", "consent state changed")
            consent = grant_consent(
                session, novel_id=novel_id, owner_id=LOCAL_OWNER_ID,
                workspace_id=LOCAL_WORKSPACE_ID,
                idempotency_key=f"consent:{novel_id}:grant:{request.notice_version}",
                notice_version=request.notice_version,
                corpora=tuple(item.value for item in EmbeddingCorpus),
                actor="local-author",
            )
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
    candidate_generation_id = configuration.candidate_generation_id if configuration else None
    generation_id = candidate_generation_id or active_generation_id
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
        "current" if build.state == "ready" and build.generation_id == active_generation_id else
        "building" if build.state in {"pending", "building"} else
        "partial_failure" if build.state == "failed" else
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
        "error_summary": build.failure_code if build else None,
        "can_rebuild": consent is not None and candidate_generation_id is not None,
        "can_cancel": bool(build and build.state in {"pending", "building"}),
        "can_retry_failed": bool(build and build.state == "failed"),
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
        if configuration is None or configuration.candidate_generation_id is None:
            raise EmbeddingLifecycleError("candidate_missing", "save a candidate generation first")
        build = prepare_v1_novel_index(
            session, generation_id=configuration.candidate_generation_id, novel_id=novel_id
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
                EmbeddingGenerationNovel.state.in_(("pending", "building")),
            )
        )
    )
    for build in builds:
        build.state = "cancelled"; build.completed_at = datetime.now(UTC)
    session.commit()
    return semantic_index_status(novel_id, session)


@router.post("/novels/{novel_id}/semantic-index/retry-failed", status_code=status.HTTP_202_ACCEPTED)
def semantic_index_retry_failed(
    novel_id: UUID, session: Session = Depends(get_session)
) -> dict[str, object]:
    configuration = get_configuration(
        session, owner_id=LOCAL_OWNER_ID, workspace_id=LOCAL_WORKSPACE_ID
    )
    if configuration is None or configuration.candidate_generation_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "candidate_missing"})
    rows = session.execute(
        select(EmbeddingIndexBatch, BackgroundJob)
        .join(BackgroundJob, BackgroundJob.id == EmbeddingIndexBatch.background_job_id)
        .where(
            EmbeddingIndexBatch.generation_id == configuration.candidate_generation_id,
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
                EmbeddingGenerationNovel.generation_id == configuration.candidate_generation_id,
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
    narrative_cutoff: int | None,
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
    current_limit = narrative_cutoff
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
    scope: SearchScope,
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


def _candidate(source: SemanticSource, chunk: SemanticChunk) -> Candidate:
    visibility = None
    if source.visibility_json:
        visibility = source.visibility_json.get("visibility_key")
        if visibility is None:
            visibility = source.visibility_json.get("visibility")
    return Candidate(
        chunk_id=chunk.id, novel_id=source.novel_id, corpus=source.corpus,
        source_id=source.source_entity_id, source_revision_id=source.source_revision_id,
        source_type=source.source_type, text=chunk.content_text,
        source_status=source.status, timeline_id=source.timeline_id,
        character_instance_id=source.character_instance_id,
        narrative_start=source.narrative_start, narrative_end=source.narrative_end,
        visibility_key=str(visibility) if visibility else None,
    )


def _source_state(source_type: str) -> str:
    if source_type == "chapter_revision":
        return "current_revision"
    if source_type == "private_asset_version":
        return "bound_asset_version"
    if source_type == "story_fact":
        return "accepted_story_fact"
    return "current_entity_revision"


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
        if consent is None:
            raise EmbeddingLifecycleError("embedding_consent_required", "novel has no active consent")
        if configuration is None or configuration.active_generation_id is None:
            raise EmbeddingLifecycleError("embedding_generation_not_ready", "active index is unavailable")
        generation = session.get(EmbeddingGeneration, configuration.active_generation_id)
        if generation is None or generation.state != "active":
            raise EmbeddingLifecycleError("embedding_generation_not_ready", "active index is unavailable")
        build = session.scalar(
            select(EmbeddingGenerationNovel).where(
                EmbeddingGenerationNovel.generation_id == generation.id,
                EmbeddingGenerationNovel.novel_id == novel_id,
                EmbeddingGenerationNovel.state == "ready",
            )
        )
        if build is None:
            raise EmbeddingLifecycleError("embedding_generation_not_ready", "novel index is unavailable")
        path, timeline_limits = _inheritance_scope(
            session,
            novel_id=novel_id,
            requested=request.timeline_id,
            narrative_cutoff=request.narrative_sequence,
        )
        generation_id = generation.id
        rows = session.execute(
            select(SemanticSource, SemanticChunk)
            .join(SemanticChunk, SemanticChunk.source_id == SemanticSource.id)
            .where(
                SemanticSource.generation_id == generation_id,
                SemanticSource.novel_id == novel_id,
                SemanticSource.corpus.in_(tuple(item.value for item in request.corpora)),
                SemanticSource.status == "current",
                SemanticChunk.content_text.ilike(f"%{request.query}%"),
            )
            .limit(200)
        ).all()
        lexical = tuple(_candidate(source, chunk) for source, chunk in rows if _source_is_current(session, source))
        perspective = request.perspective.kind.value
        scope = SearchScope(
            novel_id=novel_id, corpora=frozenset(item.value for item in request.corpora),
            reachable_timeline_ids=path, narrative_sequence=request.narrative_sequence,
            perspective=perspective,
            observer_character_instance_id=request.perspective.character_instance_id,
            timeline_sequence_limits=timeline_limits,
        )
        scope = SearchScope(
            novel_id=scope.novel_id,
            corpora=scope.corpora,
            reachable_timeline_ids=scope.reachable_timeline_ids,
            narrative_sequence=scope.narrative_sequence,
            perspective=scope.perspective,
            observer_character_instance_id=scope.observer_character_instance_id,
            known_visibility_keys=_known_visibility_keys(
                session,
                novel_id=novel_id,
                scope=scope,
            ),
            timeline_sequence_limits=scope.timeline_sequence_limits,
        )
        dense: tuple[Candidate, ...] = ()
        warnings: list[str] = []
        profile = session.get(EmbeddingProfile, generation.profile_id)
        if profile is not None and configuration.credential_ref is not None:
            try:
                credential_ref = configuration.credential_ref
                profile_base_url = profile.base_url
                profile_model_id = profile.actual_model_id
                profile_dimension = profile.dimension
                session.rollback()
                api_key = _secret_store().get(credential_ref)
                query_result = await DashScopeEmbeddingAdapter(base_url=profile_base_url).embed(
                    api_key=api_key, texts=[request.query], text_type="query",
                    model_id=profile_model_id, dimension=profile_dimension,
                    instruct="Retrieve relevant evidence for a novel-writing workspace.",
                )
                distance = SemanticEmbedding.embedding.cosine_distance(
                    list(query_result.vectors[0].values)
                )
                dense_rows = session.execute(
                    select(SemanticSource, SemanticChunk)
                    .join(SemanticChunk, SemanticChunk.source_id == SemanticSource.id)
                    .join(SemanticEmbedding, SemanticEmbedding.chunk_id == SemanticChunk.id)
                    .where(
                        SemanticSource.generation_id == generation_id,
                        SemanticSource.novel_id == novel_id,
                        SemanticSource.corpus.in_(tuple(item.value for item in request.corpora)),
                        SemanticSource.status == "current",
                    )
                    .order_by(distance)
                    .limit(200)
                ).all()
                dense = tuple(
                    _candidate(source, chunk)
                    for source, chunk in dense_rows
                    if _source_is_current(session, source)
                )
            except (EmbeddingAdapterError, EmbeddingSecretError):
                warnings.append("embedding_unavailable")
        ranked = reciprocal_rank_fusion(
            lexical=lexical, dense=dense, scope=scope, top_k=request.top_k
        )
        return {
            "schema_version": request.schema_version,
            "request_id": f"semantic:{datetime.now(UTC).timestamp()}",
            "mode": "hybrid" if dense else "lexical_only", "index_status": "ready",
            "hits": [
                {
                    "corpus": item.candidate.corpus,
                    "source_type": item.candidate.source_type,
                    "source_state": _source_state(item.candidate.source_type),
                    "source_id": str(item.candidate.source_id),
                    "source_revision_id": str(item.candidate.source_revision_id) if item.candidate.source_revision_id else None,
                    "chunk_id": str(item.candidate.chunk_id),
                    "timeline_id": str(item.candidate.timeline_id) if item.candidate.timeline_id else None,
                    "character_instance_id": str(item.candidate.character_instance_id) if item.candidate.character_instance_id else None,
                    "narrative_sequence_start": item.candidate.narrative_start,
                    "narrative_sequence_end": item.candidate.narrative_end,
                    "snippet": item.candidate.text[:4000], "channels": list(item.channels),
                    "score": item.score,
                }
                for item in ranked
            ],
            "omitted_count": max(0, len(lexical) + len(dense) - len(ranked)),
            "warnings": warnings,
        }
    except Exception as error:
        _raise(error); raise
