"""Transactional persistence for embedding configuration and consent.

Every function flushes but leaves commit/rollback to the API boundary.  Cloud
calls and secret-file writes are deliberately outside these transactions.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..creative_data_models import (
    EmbeddingConfiguration,
    EmbeddingGeneration,
    EmbeddingGenerationNovel,
    EmbeddingProfile,
    NovelEmbeddingConsent,
)
from .chunking import V1_CHUNKER_VERSION
from .contracts import SUPPORTED_EMBEDDING_DIMENSIONS
from .lifecycle import EmbeddingLifecycleError
from ..models import Novel


DEFAULT_RENDERER_BUNDLE_VERSION = "semantic-renderers/1"
DEFAULT_QUERY_POLICY_VERSION = "semantic-query-policy/1"


def _digest(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def _novel_in_scope(
    session: Session, *, novel_id: UUID, owner_id: UUID, workspace_id: UUID
) -> Novel:
    novel = session.scalar(
        select(Novel).where(
            Novel.id == novel_id,
            Novel.owner_id == owner_id,
            Novel.workspace_id == workspace_id,
        )
    )
    if novel is None:
        raise EmbeddingLifecycleError("novel_not_found", "novel is outside the local scope")
    return novel


def get_configuration(
    session: Session, *, owner_id: UUID, workspace_id: UUID, for_update: bool = False
) -> EmbeddingConfiguration | None:
    statement = select(EmbeddingConfiguration).where(
        EmbeddingConfiguration.owner_id == owner_id,
        EmbeddingConfiguration.workspace_id == workspace_id,
    )
    if for_update:
        statement = statement.with_for_update()
    return session.scalar(statement)


def ensure_configuration(
    session: Session,
    *,
    owner_id: UUID,
    workspace_id: UUID,
    base_url: str,
) -> EmbeddingConfiguration:
    current = get_configuration(
        session, owner_id=owner_id, workspace_id=workspace_id, for_update=True
    )
    if current is not None:
        return current
    current = EmbeddingConfiguration(
        id=uuid4(),
        owner_id=owner_id,
        workspace_id=workspace_id,
        base_url=base_url,
        connection_state="unconfigured",
        connection_summary_json={},
        version=1,
        updated_at=_now(),
    )
    session.add(current)
    session.flush()
    return current


def apply_credential_reference(
    session: Session,
    *,
    owner_id: UUID,
    workspace_id: UUID,
    expected_version: int,
    credential_ref: str | None,
    last4: str | None,
) -> EmbeddingConfiguration:
    configuration = get_configuration(
        session, owner_id=owner_id, workspace_id=workspace_id, for_update=True
    )
    if configuration is None:
        raise EmbeddingLifecycleError("embedding_not_configured", "embedding configuration is missing")
    if configuration.version != expected_version:
        raise EmbeddingLifecycleError("version_conflict", "embedding configuration changed")
    configuration.credential_ref = credential_ref
    configuration.api_key_last4 = last4
    configuration.api_key_updated_at = _now() if credential_ref else None
    configuration.connection_state = "unverified" if credential_ref else "unconfigured"
    previous_cleanup = dict(configuration.connection_summary_json or {}).get(
        "credential_cleanup"
    )
    configuration.connection_summary_json = (
        {"credential_cleanup": previous_cleanup}
        if isinstance(previous_cleanup, dict)
        else {}
    )
    configuration.version += 1
    configuration.updated_at = _now()
    session.flush()
    return configuration


def create_verified_candidate(
    session: Session,
    *,
    owner_id: UUID,
    workspace_id: UUID,
    expected_config_version: int,
    requested_model_id: str,
    actual_model_id: str,
    actual_revision: str | None,
    dimension: int,
    request_id: str,
    document_request_id: str,
    total_tokens: int,
    latency_ms: int,
) -> tuple[EmbeddingProfile, EmbeddingGeneration]:
    configuration = get_configuration(
        session, owner_id=owner_id, workspace_id=workspace_id, for_update=True
    )
    if configuration is None or configuration.credential_ref is None:
        raise EmbeddingLifecycleError("embedding_not_configured", "embedding credential is missing")
    if configuration.version != expected_config_version:
        raise EmbeddingLifecycleError("version_conflict", "embedding configuration changed")
    if dimension not in SUPPORTED_EMBEDDING_DIMENSIONS:
        raise EmbeddingLifecycleError(
            "dimension_mismatch", "verified dimension is not supported"
        )
    fingerprint = _digest(
        {
            "provider": "aliyun-bailian",
            "protocol": "dashscope-native-v1",
            "base_url": configuration.base_url,
            "model": actual_model_id,
            "revision": actual_revision,
            "dimension": dimension,
            "output": "dense",
            "document_role": "document",
            "query_role": "query",
            "distance": "cosine",
            "renderers": DEFAULT_RENDERER_BUNDLE_VERSION,
            "chunker": V1_CHUNKER_VERSION,
            "query_policy": DEFAULT_QUERY_POLICY_VERSION,
        }
    )
    profile = session.scalar(
        select(EmbeddingProfile).where(
            EmbeddingProfile.owner_id == owner_id,
            EmbeddingProfile.workspace_id == workspace_id,
            EmbeddingProfile.index_fingerprint == fingerprint,
        )
    )
    if profile is None:
        profile = EmbeddingProfile(
            id=uuid4(), owner_id=owner_id, workspace_id=workspace_id,
            provider_id="aliyun-bailian", protocol="dashscope-native-v1",
            base_url=configuration.base_url, credential_ref=configuration.credential_ref,
            requested_model_id=requested_model_id, actual_model_id=actual_model_id,
            actual_revision=actual_revision, dimension=dimension, output_type="dense",
            document_text_type="document", query_text_type="query",
            distance_metric="cosine", index_fingerprint=fingerprint,
            connection_state="available",
        )
        session.add(profile)
        session.flush()
    else:
        # Credentials are connection state, not vector-space identity.  Keep the
        # legacy column aligned while generation/profile fingerprints remain stable.
        profile.credential_ref = configuration.credential_ref
        profile.connection_state = "available"
    generation_number = int(
        session.scalar(
            select(func.max(EmbeddingGeneration.generation_number)).where(
                EmbeddingGeneration.owner_id == owner_id,
                EmbeddingGeneration.workspace_id == workspace_id,
            )
        )
        or 0
    ) + 1
    active_consents = tuple(
        session.scalars(
            select(NovelEmbeddingConsent)
            .join(Novel, Novel.id == NovelEmbeddingConsent.novel_id)
            .where(
                Novel.owner_id == owner_id,
                Novel.workspace_id == workspace_id,
                NovelEmbeddingConsent.revoked_at.is_(None),
            )
            .order_by(NovelEmbeddingConsent.novel_id)
        )
    )
    cohort_hash = _digest(
        [(str(item.novel_id), str(item.id), item.notice_version) for item in active_consents]
    )
    generation = EmbeddingGeneration(
        id=uuid4(), owner_id=owner_id, workspace_id=workspace_id,
        profile_id=profile.id, generation_number=generation_number, state="draft",
        renderer_bundle_version=DEFAULT_RENDERER_BUNDLE_VERSION,
        chunker_version=V1_CHUNKER_VERSION,
        query_policy_version=DEFAULT_QUERY_POLICY_VERSION,
        index_fingerprint=fingerprint, consent_cohort_hash=cohort_hash,
        evaluation_state="not_run", evaluation_summary_json={},
    )
    session.add(generation)
    session.flush()
    for consent in active_consents:
        session.add(
            EmbeddingGenerationNovel(
                id=uuid4(), generation_id=generation.id, novel_id=consent.novel_id,
                owner_id=owner_id, workspace_id=workspace_id, consent_id=consent.id,
                state="pending", target_corpora_json=list(consent.data_scope_json),
                input_digest=_digest(
                    [str(generation.id), str(consent.novel_id), str(consent.id), consent.data_scope_json]
                ),
                source_count=0, chunk_count=0, embedded_count=0, failure_count=0,
            )
        )
    configuration.candidate_generation_id = generation.id
    configuration.connection_state = "available"
    previous_cleanup = dict(configuration.connection_summary_json or {}).get(
        "credential_cleanup"
    )
    connection_summary: dict[str, object] = {
        "request_id": request_id,
        "document_request_id": document_request_id,
        "total_tokens": total_tokens,
        "latency_ms": latency_ms,
        "actual_dimension": dimension,
    }
    if isinstance(previous_cleanup, dict):
        # A successful candidate must not erase an unresolved, already
        # committed orphan-secret cleanup warning from an earlier rotation.
        connection_summary["credential_cleanup"] = previous_cleanup
    configuration.connection_summary_json = connection_summary
    configuration.version += 1
    configuration.updated_at = _now()
    session.flush()
    return profile, generation


def grant_consent(
    session: Session,
    *,
    novel_id: UUID,
    owner_id: UUID,
    workspace_id: UUID,
    idempotency_key: str,
    notice_version: str,
    corpora: tuple[str, ...],
    actor: str,
    model_id: str = "qwen3.7-text-embedding",
) -> NovelEmbeddingConsent:
    _novel_in_scope(
        session, novel_id=novel_id, owner_id=owner_id, workspace_id=workspace_id
    )
    operation_hash = _digest(
        {"action": "grant", "notice_version": notice_version, "corpora": sorted(corpora)}
    )
    replay = session.scalar(
        select(NovelEmbeddingConsent).where(
            NovelEmbeddingConsent.novel_id == novel_id,
            NovelEmbeddingConsent.idempotency_key == idempotency_key,
        )
    )
    if replay is not None:
        if replay.operation_hash != operation_hash:
            raise EmbeddingLifecycleError("idempotency_conflict", "consent command changed")
        _attach_consent_to_candidate(
            session,
            consent=replay,
            owner_id=owner_id,
            workspace_id=workspace_id,
        )
        return replay
    active = session.scalar(
        select(NovelEmbeddingConsent).where(
            NovelEmbeddingConsent.novel_id == novel_id,
            NovelEmbeddingConsent.revoked_at.is_(None),
        )
    )
    if active is not None:
        if active.notice_version == notice_version:
            raise EmbeddingLifecycleError("consent_already_active", "novel already has active consent")
        active.revoked_actor = actor
        active.revoked_reason = "notice_upgraded"
        active.revoked_at = _now()
    consent = NovelEmbeddingConsent(
        id=uuid4(), novel_id=novel_id, purpose="semantic_index",
        data_scope_json=list(corpora), notice_version=notice_version,
        provider_id="aliyun-bailian", model_id=model_id,
        idempotency_key=idempotency_key, operation_hash=operation_hash,
        confirmed_actor=actor, confirmed_at=_now(),
    )
    session.add(consent)
    session.flush()
    _attach_consent_to_candidate(
        session,
        consent=consent,
        owner_id=owner_id,
        workspace_id=workspace_id,
    )
    return consent


def _attach_consent_to_candidate(
    session: Session,
    *,
    consent: NovelEmbeddingConsent,
    owner_id: UUID,
    workspace_id: UUID,
) -> None:
    """Attach late authorization to active and candidate toolchain generations.

    A candidate may legitimately be saved while no novel is authorized.  Granting
    consent later must make that novel rebuildable without forcing the author to
    replace an otherwise valid model configuration.
    """

    configuration = get_configuration(
        session, owner_id=owner_id, workspace_id=workspace_id, for_update=True
    )
    if configuration is None:
        return
    generation_ids = tuple(
        dict.fromkeys(
            item
            for item in (
                getattr(configuration, "active_generation_id", None),
                configuration.candidate_generation_id,
            )
            if item is not None
        )
    )
    changed = False
    candidate_changed = False
    candidate_generation: EmbeddingGeneration | None = None
    for generation_id in generation_ids:
        generation = session.scalar(
            select(EmbeddingGeneration)
            .where(
                EmbeddingGeneration.id == generation_id,
                EmbeddingGeneration.owner_id == owner_id,
                EmbeddingGeneration.workspace_id == workspace_id,
            )
            .with_for_update()
        )
        if generation is None or generation.state not in {
            "active", "draft", "building", "ready"
        }:
            continue
        if generation.id == configuration.candidate_generation_id:
            candidate_generation = generation
        build = session.scalar(
            select(EmbeddingGenerationNovel)
            .where(
                EmbeddingGenerationNovel.generation_id == generation.id,
                EmbeddingGenerationNovel.novel_id == consent.novel_id,
            )
            .with_for_update()
        )
        input_digest = _digest(
            [str(generation.id), str(consent.novel_id), str(consent.id), consent.data_scope_json]
        )
        if build is None:
            session.add(
                EmbeddingGenerationNovel(
                    id=uuid4(), generation_id=generation.id, novel_id=consent.novel_id,
                    owner_id=owner_id, workspace_id=workspace_id, consent_id=consent.id,
                    state="pending", target_corpora_json=list(consent.data_scope_json),
                    input_digest=input_digest, source_count=0, chunk_count=0,
                    embedded_count=0, failure_count=0, index_version=1,
                    authority_digest=input_digest, published_digest="0" * 64,
                    sync_state="outdated", pending_refresh_count=0,
                )
            )
            changed = True
            candidate_changed = candidate_changed or (
                generation.id == configuration.candidate_generation_id
            )
        elif build.consent_id != consent.id or build.state in {
            "cancelled", "failed", "stale", "partial_failed"
        }:
            build.consent_id = consent.id
            build.state = "pending"
            build.target_corpora_json = list(consent.data_scope_json)
            build.input_digest = input_digest
            build.authority_digest = input_digest
            build.sync_state = "outdated"
            build.source_count = 0
            build.chunk_count = 0
            build.embedded_count = 0
            build.failure_count = 0
            build.failure_code = None
            build.started_at = None
            build.completed_at = None
            changed = True
            candidate_changed = candidate_changed or (
                generation.id == configuration.candidate_generation_id
            )
    if not changed:
        return
    active_consents = tuple(
        session.scalars(
            select(NovelEmbeddingConsent)
            .join(Novel, Novel.id == NovelEmbeddingConsent.novel_id)
            .where(
                Novel.owner_id == owner_id,
                Novel.workspace_id == workspace_id,
                NovelEmbeddingConsent.revoked_at.is_(None),
            )
            .order_by(NovelEmbeddingConsent.novel_id)
        )
    )
    if candidate_changed and candidate_generation is not None:
        candidate_generation.consent_cohort_hash = _digest(
            [(str(item.novel_id), str(item.id), item.notice_version) for item in active_consents]
        )
        candidate_generation.state = "draft"
        candidate_generation.evaluation_state = "not_run"
        candidate_generation.evaluation_summary_json = {}
    configuration.version += 1
    configuration.updated_at = _now()
    session.flush()


def revoke_consent(
    session: Session,
    *,
    novel_id: UUID,
    consent_id: UUID,
    owner_id: UUID,
    workspace_id: UUID,
    actor: str,
    reason: str,
) -> NovelEmbeddingConsent:
    _novel_in_scope(
        session, novel_id=novel_id, owner_id=owner_id, workspace_id=workspace_id
    )
    consent = session.scalar(
        select(NovelEmbeddingConsent)
        .where(
            NovelEmbeddingConsent.id == consent_id,
            NovelEmbeddingConsent.novel_id == novel_id,
        )
        .with_for_update()
    )
    if consent is None:
        raise EmbeddingLifecycleError("consent_not_found", "active consent was not found")
    if consent.revoked_at is None:
        consent.revoked_actor = actor
        consent.revoked_reason = reason
        consent.revoked_at = _now()
        for build in session.scalars(
            select(EmbeddingGenerationNovel)
            .where(
                EmbeddingGenerationNovel.novel_id == novel_id,
                EmbeddingGenerationNovel.consent_id == consent.id,
                EmbeddingGenerationNovel.state.in_(("pending", "building", "updating")),
            )
            .with_for_update()
        ):
            build.state = "cancelled"
            build.sync_state = "revoked"
            build.completed_at = _now()
    session.flush()
    return consent


def activate_candidate_generation(
    session: Session, *, owner_id: UUID, workspace_id: UUID, expected_config_version: int
) -> EmbeddingGeneration:
    configuration = get_configuration(
        session, owner_id=owner_id, workspace_id=workspace_id, for_update=True
    )
    if configuration is None or configuration.version != expected_config_version:
        raise EmbeddingLifecycleError("version_conflict", "embedding configuration changed")
    if configuration.candidate_generation_id is None:
        raise EmbeddingLifecycleError("candidate_missing", "candidate generation is missing")
    candidate = session.scalar(
        select(EmbeddingGeneration)
        .where(
            EmbeddingGeneration.id == configuration.candidate_generation_id,
            EmbeddingGeneration.owner_id == owner_id,
            EmbeddingGeneration.workspace_id == workspace_id,
        )
        .with_for_update()
    )
    if candidate is None or candidate.state != "ready":
        raise EmbeddingLifecycleError("candidate_not_ready", "candidate generation is not ready")
    if candidate.evaluation_state != "passed":
        raise EmbeddingLifecycleError("candidate_evaluation_failed", "candidate retrieval evaluation has not passed")
    builds = tuple(
        session.scalars(
            select(EmbeddingGenerationNovel).where(
                EmbeddingGenerationNovel.generation_id == candidate.id
            )
        )
    )
    active_consents = tuple(
        session.scalars(
            select(NovelEmbeddingConsent)
            .join(Novel, Novel.id == NovelEmbeddingConsent.novel_id)
            .where(
                Novel.owner_id == owner_id,
                Novel.workspace_id == workspace_id,
                NovelEmbeddingConsent.revoked_at.is_(None),
            )
        )
    )
    expected = {item.novel_id: item.id for item in active_consents}
    actual = {item.novel_id: item for item in builds}
    if set(expected) != set(actual) or any(
        actual[novel_id].consent_id != consent_id or actual[novel_id].state != "ready"
        for novel_id, consent_id in expected.items()
    ):
        raise EmbeddingLifecycleError("candidate_not_ready", "not every authorized novel is ready")
    previous_id = configuration.active_generation_id
    if previous_id is not None:
        previous = session.get(EmbeddingGeneration, previous_id)
        if previous is not None:
            previous.state = "retired"
            previous.retired_at = _now()
    candidate.state = "active"
    candidate.activated_at = _now()
    configuration.previous_generation_id = previous_id
    configuration.active_generation_id = candidate.id
    configuration.candidate_generation_id = None
    configuration.version += 1
    configuration.updated_at = _now()
    session.flush()
    return candidate
