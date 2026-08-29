from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.embedding.contracts import (
    TARGET_CANDIDATE_DIMENSION,
    TARGET_CANDIDATE_MODEL_ID,
    ConsentAction,
    CredentialAction,
    EmbeddingCandidateTarget,
    EmbeddingConfigResource,
    EmbeddingConnectionStatus,
    EmbeddingCorpus,
    EmbeddingCredentialMutation,
    EmbeddingErrorCode,
    EmbeddingErrorResource,
    EmbeddingGenerationStatus,
    EmbeddingProfileResource,
    NovelEmbeddingConsentMutation,
    NovelEmbeddingConsentResource,
    PerspectiveKind,
    SemanticIndexStatus,
    SemanticMatchChannel,
    SemanticPerspective,
    SemanticSearchHit,
    SemanticSearchMode,
    SemanticSearchRequest,
    SemanticSearchResult,
    SemanticSourceState,
    VerificationStatus,
)


def test_candidate_defaults_are_explicitly_unverified() -> None:
    candidate = EmbeddingCandidateTarget()

    assert candidate.model_id == TARGET_CANDIDATE_MODEL_ID
    assert candidate.dimension == TARGET_CANDIDATE_DIMENSION == 1024
    assert candidate.verification_status == VerificationStatus.UNVERIFIED
    with pytest.raises(ValidationError):
        EmbeddingCandidateTarget(verification_status="verified")


def test_resource_contracts_never_expose_api_key() -> None:
    resource_types = (
        EmbeddingCandidateTarget,
        EmbeddingProfileResource,
        EmbeddingConfigResource,
        NovelEmbeddingConsentResource,
        SemanticPerspective,
        SemanticSearchHit,
        SemanticSearchResult,
        EmbeddingErrorResource,
    )

    for resource_type in resource_types:
        assert "api_key" not in resource_type.model_fields
        assert "api_key" not in str(resource_type.model_json_schema())


def test_credential_action_is_write_only_and_action_specific() -> None:
    secret = "sk-test-must-not-leak"
    mutation = EmbeddingCredentialMutation(
        action=CredentialAction.REPLACE,
        api_key=secret,
    )

    assert mutation.api_key is not None
    assert mutation.api_key.get_secret_value() == secret
    assert secret not in repr(mutation)
    assert secret not in mutation.model_dump_json()
    EmbeddingCredentialMutation(action=CredentialAction.KEEP)
    EmbeddingCredentialMutation(action=CredentialAction.CLEAR)

    with pytest.raises(ValidationError):
        EmbeddingCredentialMutation(action=CredentialAction.REPLACE)
    with pytest.raises(ValidationError):
        EmbeddingCredentialMutation(action=CredentialAction.KEEP, api_key=secret)
    with pytest.raises(ValidationError):
        EmbeddingCredentialMutation(action=CredentialAction.CLEAR, api_key=secret)
    with pytest.raises(ValidationError):
        EmbeddingCredentialMutation(action=CredentialAction.REPLACE, api_key="   ")


def test_config_resource_exposes_only_credential_presence_metadata() -> None:
    resource = EmbeddingConfigResource(
        version=0,
        credential_configured=False,
        connection_status=EmbeddingConnectionStatus.UNCONFIGURED,
    )

    dumped = resource.model_dump(mode="json")
    assert dumped["credential_configured"] is False
    assert all("key" not in field_name for field_name in dumped)

    with pytest.raises(ValidationError):
        EmbeddingConfigResource(
            version=0,
            credential_configured=False,
            credential_updated_at=datetime.now(UTC),
            connection_status=EmbeddingConnectionStatus.UNCONFIGURED,
        )


def test_consent_grant_and_revoke_are_distinct_commands() -> None:
    grant = NovelEmbeddingConsentMutation(
        action=ConsentAction.GRANT,
        idempotency_key="grant:novel-1:1",
        notice_version="embedding-notice/1",
        acknowledged_corpora=[
            EmbeddingCorpus.MANUSCRIPT,
            EmbeddingCorpus.PLANNING,
            EmbeddingCorpus.PRIVATE_ASSET,
        ],
    )
    consent_id = uuid4()
    revoke = NovelEmbeddingConsentMutation(
        action=ConsentAction.REVOKE,
        idempotency_key="revoke:novel-1:1",
        active_consent_id=consent_id,
    )

    assert grant.notice_version == "embedding-notice/1"
    assert revoke.active_consent_id == consent_id

    with pytest.raises(ValidationError):
        NovelEmbeddingConsentMutation(
            action=ConsentAction.GRANT,
            idempotency_key="grant-1",
            acknowledged_corpora=[EmbeddingCorpus.MANUSCRIPT],
        )
    with pytest.raises(ValidationError):
        NovelEmbeddingConsentMutation(
            action=ConsentAction.REVOKE,
            idempotency_key="revoke-1",
        )
    with pytest.raises(ValidationError):
        NovelEmbeddingConsentMutation(
            action=ConsentAction.GRANT,
            idempotency_key="grant-2",
            notice_version="embedding-notice/1",
            acknowledged_corpora=[
                EmbeddingCorpus.MANUSCRIPT,
                EmbeddingCorpus.MANUSCRIPT,
            ],
        )


def test_authorized_consent_resource_requires_complete_metadata() -> None:
    now = datetime.now(UTC)
    resource = NovelEmbeddingConsentResource(
        novel_id=uuid4(),
        authorized=True,
        consent_id=uuid4(),
        notice_version="embedding-notice/1",
        acknowledged_corpora=[EmbeddingCorpus.MANUSCRIPT],
        granted_at=now,
    )

    assert resource.granted_at == now
    with pytest.raises(ValidationError):
        NovelEmbeddingConsentResource(novel_id=uuid4(), authorized=True)


def test_semantic_search_request_has_bounded_unique_scope() -> None:
    request = SemanticSearchRequest(query="  主角在哪里得知真相？  ")

    assert request.query == "主角在哪里得知真相？"
    assert request.corpora == (
        EmbeddingCorpus.MANUSCRIPT,
        EmbeddingCorpus.PLANNING,
        EmbeddingCorpus.PRIVATE_ASSET,
    )

    with pytest.raises(ValidationError):
        SemanticSearchRequest(query="   ")
    with pytest.raises(ValidationError):
        SemanticSearchRequest(query="线索", corpora=[])
    with pytest.raises(ValidationError):
        SemanticSearchRequest(
            query="线索",
            corpora=[EmbeddingCorpus.PLANNING, EmbeddingCorpus.PLANNING],
        )
    with pytest.raises(ValidationError):
        SemanticSearchRequest(query="线索", top_k=51)


def test_character_perspective_never_guesses_an_instance() -> None:
    instance_id = uuid4()
    perspective = SemanticPerspective(
        kind=PerspectiveKind.CHARACTER_INSTANCE,
        character_instance_id=instance_id,
    )
    assert perspective.character_instance_id == instance_id

    with pytest.raises(ValidationError):
        SemanticPerspective(kind=PerspectiveKind.CHARACTER_INSTANCE)
    with pytest.raises(ValidationError):
        SemanticPerspective(
            kind=PerspectiveKind.AUTHOR,
            character_instance_id=instance_id,
        )


def test_semantic_search_result_carries_source_and_scope_evidence() -> None:
    hit = SemanticSearchHit(
        corpus=EmbeddingCorpus.MANUSCRIPT,
        source_type="chapter_revision",
        source_id=uuid4(),
        source_revision_id=uuid4(),
        chunk_id=uuid4(),
        source_state=SemanticSourceState.CURRENT_REVISION,
        timeline_id=uuid4(),
        narrative_sequence_start=10,
        narrative_sequence_end=20,
        snippet="她在钟楼中看到了那封信。",
        channels=[SemanticMatchChannel.LEXICAL, SemanticMatchChannel.DENSE],
        score=0.82,
    )
    result = SemanticSearchResult(
        request_id="request-1",
        mode=SemanticSearchMode.HYBRID,
        index_status=SemanticIndexStatus.READY,
        hits=[hit],
    )

    assert result.hits[0].source_revision_id == hit.source_revision_id
    assert result.hits[0].timeline_id == hit.timeline_id
    assert result.hits[0].channels == (
        SemanticMatchChannel.LEXICAL,
        SemanticMatchChannel.DENSE,
    )

    with pytest.raises(ValidationError):
        SemanticSearchHit(**{**hit.model_dump(), "score": float("nan")})
    with pytest.raises(ValidationError):
        SemanticSearchHit(
            **{
                **hit.model_dump(),
                "narrative_sequence_start": 20,
                "narrative_sequence_end": 10,
            }
        )


def test_status_corpus_and_error_code_values_are_stable() -> None:
    assert {item.value for item in EmbeddingCorpus} == {
        "manuscript",
        "planning",
        "private_asset",
        "character",
        "relationship",
        "story_event",
        "storyline",
        "foreshadow",
        "timeline",
    }
    assert EmbeddingGenerationStatus.PARTIAL_FAILURE.value == "partial_failure"
    assert SemanticIndexStatus.NOT_AUTHORIZED.value == "not_authorized"

    error = EmbeddingErrorResource(
        code=EmbeddingErrorCode.EMBEDDING_CONSENT_REQUIRED,
        message="小说尚未授权云端向量处理",
        retryable=False,
        request_id="request-2",
    )
    assert error.model_dump(mode="json")["code"] == "embedding_consent_required"


def test_contracts_do_not_claim_price_or_rate_limit_values() -> None:
    forbidden_claim_fields = {
        "price",
        "rate_limit",
        "requests_per_minute",
        "tokens_per_minute",
    }
    for model in (
        EmbeddingCandidateTarget,
        EmbeddingConfigResource,
        SemanticSearchRequest,
        SemanticSearchResult,
    ):
        assert forbidden_claim_fields.isdisjoint(model.model_fields)


def test_contracts_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SemanticSearchRequest(query="线索", unexpected=True)
