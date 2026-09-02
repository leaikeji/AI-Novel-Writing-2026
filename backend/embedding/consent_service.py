"""Novel-level embedding consent orchestration for creation entrypoints.

The preparation function participates in the caller's novel-creation
transaction.  It never commits, enqueues a background job, reads a secret, or
calls a Provider.  The caller may invoke the explicitly named enqueue helper
only after that transaction has committed successfully.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..creative_data_models import (
    EmbeddingGeneration,
    EmbeddingProfile,
    NovelEmbeddingConsent,
)
from .contracts import (
    DEFAULT_NOVEL_EMBEDDING_CORPORA,
    NOVEL_EMBEDDING_CONSENT_NOTICE_VERSION,
    SUPPORTED_EMBEDDING_DIMENSIONS,
    TARGET_CANDIDATE_MODEL_ID,
    NovelEmbeddingConsentState,
)
from .persistence import (
    get_configuration,
    grant_consent,
    load_consent_history,
)


DEFAULT_NEW_NOVEL_CONSENT_ACTOR = "product-default:new-novel"
DEFAULT_NEW_NOVEL_CONSENT_CORPORA = tuple(
    corpus.value for corpus in DEFAULT_NOVEL_EMBEDDING_CORPORA
)


@dataclass(frozen=True, slots=True)
class ActiveEmbeddingConsentTarget:
    configuration_version: int
    generation_id: UUID
    provider_id: str
    model_id: str


@dataclass(frozen=True, slots=True)
class NewNovelConsentPreparation:
    novel_id: UUID
    owner_id: UUID
    workspace_id: UUID
    state: NovelEmbeddingConsentState
    consent_version: int
    consent_id: UUID | None
    configuration_version: int | None
    generation_id: UUID | None
    provider_id: str | None
    model_id: str | None
    created: bool
    enqueue_after_commit: bool
    reason_code: str | None = None


def consent_state_for_target(
    consent: NovelEmbeddingConsent | None,
    *,
    provider_id: str | None = None,
    model_id: str | None = None,
) -> NovelEmbeddingConsentState:
    """Project consent authority separately from temporary service availability."""

    if consent is None:
        return NovelEmbeddingConsentState.NOT_AUTHORIZED
    if consent.revoked_at is not None:
        return NovelEmbeddingConsentState.REVOKED
    if (
        consent.notice_version != NOVEL_EMBEDDING_CONSENT_NOTICE_VERSION
        or tuple(sorted(consent.data_scope_json))
        != tuple(sorted(DEFAULT_NEW_NOVEL_CONSENT_CORPORA))
        or (provider_id is not None and consent.provider_id != provider_id)
        or (model_id is not None and consent.model_id != model_id)
    ):
        return NovelEmbeddingConsentState.REQUIRES_RECONSENT
    return NovelEmbeddingConsentState.GRANTED


def resolve_active_embedding_consent_target(
    session: Session,
    *,
    owner_id: UUID,
    workspace_id: UUID,
) -> tuple[ActiveEmbeddingConsentTarget | None, str | None]:
    configuration = get_configuration(
        session,
        owner_id=owner_id,
        workspace_id=workspace_id,
        for_update=True,
    )
    if configuration is None:
        return None, "embedding_configuration_missing"
    if configuration.credential_ref is None:
        return None, "embedding_credential_missing"
    if configuration.connection_state != "available":
        return None, "embedding_configuration_unavailable"
    if configuration.active_generation_id is None:
        return None, "active_generation_missing"

    generation = session.scalar(
        select(EmbeddingGeneration)
        .where(
            EmbeddingGeneration.id == configuration.active_generation_id,
            EmbeddingGeneration.owner_id == owner_id,
            EmbeddingGeneration.workspace_id == workspace_id,
        )
        .with_for_update()
    )
    if generation is None or generation.state != "active":
        return None, "active_generation_unavailable"
    profile = session.scalar(
        select(EmbeddingProfile).where(
            EmbeddingProfile.id == generation.profile_id,
            EmbeddingProfile.owner_id == owner_id,
            EmbeddingProfile.workspace_id == workspace_id,
        )
    )
    if (
        profile is None
        or profile.connection_state != "available"
        or profile.credential_ref != configuration.credential_ref
        or profile.provider_id != "aliyun-bailian"
        or profile.actual_model_id != TARGET_CANDIDATE_MODEL_ID
        or profile.dimension not in SUPPORTED_EMBEDDING_DIMENSIONS
    ):
        return None, "active_profile_unavailable"
    return (
        ActiveEmbeddingConsentTarget(
            configuration_version=configuration.version,
            generation_id=generation.id,
            provider_id=profile.provider_id,
            model_id=profile.actual_model_id,
        ),
        None,
    )


def prepare_new_novel_default_consent(
    session: Session,
    *,
    novel_id: UUID,
    owner_id: UUID,
    workspace_id: UUID,
    operation_key: str | None = None,
    actor: str = DEFAULT_NEW_NOVEL_CONSENT_ACTOR,
) -> NewNovelConsentPreparation:
    """Prepare a new novel's independent consent in the creation transaction.

    ``expected_version=0`` is deliberate: an older, ungranted novel can never
    be passed through this default path to gain authorization.  An exact retry
    of the same new-novel operation remains a safe no-op.
    """

    before = load_consent_history(
        session,
        novel_id=novel_id,
        owner_id=owner_id,
        workspace_id=workspace_id,
        for_update=True,
    )
    target, reason_code = resolve_active_embedding_consent_target(
        session,
        owner_id=owner_id,
        workspace_id=workspace_id,
    )
    if target is None:
        return NewNovelConsentPreparation(
            novel_id=novel_id,
            owner_id=owner_id,
            workspace_id=workspace_id,
            state=consent_state_for_target(before.active),
            consent_version=before.version,
            consent_id=before.active.id if before.active is not None else None,
            configuration_version=None,
            generation_id=None,
            provider_id=None,
            model_id=None,
            created=False,
            enqueue_after_commit=False,
            reason_code=reason_code,
        )

    consent = grant_consent(
        session,
        novel_id=novel_id,
        owner_id=owner_id,
        workspace_id=workspace_id,
        idempotency_key=operation_key or f"new-novel-default:{novel_id}",
        notice_version=NOVEL_EMBEDDING_CONSENT_NOTICE_VERSION,
        corpora=DEFAULT_NEW_NOVEL_CONSENT_CORPORA,
        actor=actor,
        provider_id=target.provider_id,
        model_id=target.model_id,
        expected_version=0,
    )
    created = all(record.id != consent.id for record in before.records)
    consent_version = 1 if created else before.version
    return NewNovelConsentPreparation(
        novel_id=novel_id,
        owner_id=owner_id,
        workspace_id=workspace_id,
        state=consent_state_for_target(
            consent,
            provider_id=target.provider_id,
            model_id=target.model_id,
        ),
        consent_version=consent_version,
        consent_id=consent.id,
        configuration_version=target.configuration_version,
        generation_id=target.generation_id,
        provider_id=target.provider_id,
        model_id=target.model_id,
        created=created,
        enqueue_after_commit=created,
    )


def enqueue_new_novel_index_after_commit(
    session: Session,
    preparation: NewNovelConsentPreparation,
) -> bool:
    """Request local index preparation after the caller committed the consent.

    This helper deliberately does not commit.  The caller owns the independent
    enqueue transaction and its retry/error projection.  Exact consent replays
    carry ``enqueue_after_commit=False`` and therefore cannot duplicate work.
    """

    if not preparation.enqueue_after_commit:
        return False
    history = load_consent_history(
        session,
        novel_id=preparation.novel_id,
        owner_id=preparation.owner_id,
        workspace_id=preparation.workspace_id,
        for_update=True,
    )
    if history.active is None or history.active.id != preparation.consent_id:
        return False
    if (
        history.active.provider_id != preparation.provider_id
        or history.active.model_id != preparation.model_id
    ):
        return False
    target, _ = resolve_active_embedding_consent_target(
        session,
        owner_id=preparation.owner_id,
        workspace_id=preparation.workspace_id,
    )
    if target is None or consent_state_for_target(
        history.active,
        provider_id=target.provider_id,
        model_id=target.model_id,
    ) is not NovelEmbeddingConsentState.GRANTED:
        return False
    from .indexing import request_active_novel_refresh

    return request_active_novel_refresh(session, preparation.novel_id)
