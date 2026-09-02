from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from backend.creative_data_models import (
    EmbeddingGenerationNovel,
    NovelEmbeddingConsent,
)
from backend.embedding import consent_service, persistence
from backend.embedding.consent_service import (
    ActiveEmbeddingConsentTarget,
    consent_state_for_target,
    enqueue_new_novel_index_after_commit,
    prepare_new_novel_default_consent,
    resolve_active_embedding_consent_target,
)
from backend.embedding.contracts import (
    NOVEL_EMBEDDING_CONSENT_NOTICE_VERSION,
    NovelEmbeddingConsentState,
)
from backend.embedding.lifecycle import EmbeddingLifecycleError
from backend.models import Novel


OWNER_ID = UUID("29cf94d9-a5c9-54ec-912c-5dfff8738c4c")
WORKSPACE_ID = UUID("f0e2e632-bc99-52d2-9916-bb906aa4da6e")
NOW = datetime(2026, 9, 2, tzinfo=UTC)
CORPORA = ("manuscript", "planning", "private_asset")


def _consent(
    novel_id: UUID,
    *,
    key: str,
    revoked: bool,
    corpora: tuple[str, ...] = CORPORA,
    notice_version: str = NOVEL_EMBEDDING_CONSENT_NOTICE_VERSION,
    provider_id: str = "aliyun-bailian",
    model_id: str = "qwen3.7-text-embedding",
) -> NovelEmbeddingConsent:
    return NovelEmbeddingConsent(
        id=uuid4(),
        novel_id=novel_id,
        purpose="semantic_index",
        data_scope_json=list(corpora),
        notice_version=notice_version,
        provider_id=provider_id,
        model_id=model_id,
        idempotency_key=key,
        operation_hash="0" * 64,
        confirmed_actor="test-author",
        confirmed_at=NOW,
        revoked_actor="test-author" if revoked else None,
        revoked_at=NOW if revoked else None,
        revoked_reason="test" if revoked else None,
    )


class ConsentHistorySession:
    def __init__(
        self,
        novel_id: UUID,
        records: tuple[NovelEmbeddingConsent, ...] = (),
    ) -> None:
        self.novel = SimpleNamespace(
            id=novel_id,
            owner_id=OWNER_ID,
            workspace_id=WORKSPACE_ID,
        )
        self.records = list(records)
        self.added: list[Any] = []
        self.flush_count = 0
        self.commit_count = 0

    @staticmethod
    def _entity(statement: Any) -> type[Any] | None:
        return statement.column_descriptions[0].get("entity")

    def scalar(self, statement: Any) -> Any | None:
        if self._entity(statement) is Novel:
            return self.novel
        return None

    def scalars(self, statement: Any) -> tuple[Any, ...]:
        entity = self._entity(statement)
        if entity is NovelEmbeddingConsent:
            return tuple(self.records)
        if entity is EmbeddingGenerationNovel:
            return ()
        raise AssertionError(f"unexpected scalar collection: {entity}")

    def add(self, value: Any) -> None:
        self.added.append(value)
        if isinstance(value, NovelEmbeddingConsent):
            self.records.append(value)

    def flush(self) -> None:
        self.flush_count += 1

    def commit(self) -> None:
        self.commit_count += 1


class TargetSession:
    def __init__(self, *values: Any) -> None:
        self.values = iter(values)

    def scalar(self, _statement: Any) -> Any | None:
        return next(self.values)


def test_consent_history_version_is_derived_without_a_version_column() -> None:
    novel_id = uuid4()
    first = _consent(novel_id, key="grant:1", revoked=False)
    assert persistence.derive_consent_history_version(()) == 0
    assert persistence.derive_consent_history_version((first,)) == 1

    first.revoked_at = NOW
    second = _consent(novel_id, key="grant:2", revoked=False)
    assert persistence.derive_consent_history_version((first,)) == 2
    assert persistence.derive_consent_history_version((first, second)) == 3

    second.revoked_at = NOW
    assert persistence.derive_consent_history_version((first, second)) == 4


def test_same_notice_regrant_derives_a_new_key_and_replays_before_stale_cas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = uuid4()
    fixed_key = f"consent:{novel_id}:grant:{NOVEL_EMBEDDING_CONSENT_NOTICE_VERSION}"
    revoked = _consent(novel_id, key=fixed_key, revoked=True)
    session = ConsentHistorySession(novel_id, (revoked,))
    attached: list[UUID] = []
    monkeypatch.setattr(
        persistence,
        "_attach_consent_to_candidate",
        lambda _session, *, consent, **_kwargs: attached.append(consent.id),
    )

    regranted = persistence.grant_consent(
        session,
        novel_id=novel_id,
        owner_id=OWNER_ID,
        workspace_id=WORKSPACE_ID,
        idempotency_key=fixed_key,
        notice_version=NOVEL_EMBEDDING_CONSENT_NOTICE_VERSION,
        corpora=CORPORA,
        actor="test-author",
    )

    assert regranted.id != revoked.id
    assert regranted.idempotency_key != fixed_key
    assert regranted.operation_hash != revoked.operation_hash
    assert persistence.load_consent_history(
        session,
        novel_id=novel_id,
        owner_id=OWNER_ID,
        workspace_id=WORKSPACE_ID,
    ).version == 3
    assert attached == [regranted.id]

    replay = persistence.grant_consent(
        session,
        novel_id=novel_id,
        owner_id=OWNER_ID,
        workspace_id=WORKSPACE_ID,
        idempotency_key=fixed_key,
        notice_version=NOVEL_EMBEDDING_CONSENT_NOTICE_VERSION,
        corpora=CORPORA,
        actor="test-author",
    )

    assert replay.id == regranted.id
    assert len(session.records) == 2
    assert attached == [regranted.id]

    stale_cas_replay = persistence.grant_consent(
        session,
        novel_id=novel_id,
        owner_id=OWNER_ID,
        workspace_id=WORKSPACE_ID,
        idempotency_key=fixed_key,
        notice_version=NOVEL_EMBEDDING_CONSENT_NOTICE_VERSION,
        corpora=CORPORA,
        actor="test-author",
        expected_version=2,
    )
    assert stale_cas_replay.id == regranted.id


def test_same_key_changed_payload_wins_before_stale_cas() -> None:
    novel_id = uuid4()
    active = _consent(novel_id, key="grant:fixed", revoked=False)
    session = ConsentHistorySession(novel_id, (active,))

    with pytest.raises(EmbeddingLifecycleError) as captured:
        persistence.grant_consent(
            session,
            novel_id=novel_id,
            owner_id=OWNER_ID,
            workspace_id=WORKSPACE_ID,
            idempotency_key="grant:fixed",
            notice_version=NOVEL_EMBEDDING_CONSENT_NOTICE_VERSION,
            corpora=("manuscript",),
            actor="test-author",
            expected_version=0,
        )

    assert captured.value.code == "idempotency_conflict"


def test_new_key_with_stale_history_version_is_rejected() -> None:
    novel_id = uuid4()
    revoked = _consent(novel_id, key="grant:old", revoked=True)
    session = ConsentHistorySession(novel_id, (revoked,))

    with pytest.raises(EmbeddingLifecycleError) as captured:
        persistence.grant_consent(
            session,
            novel_id=novel_id,
            owner_id=OWNER_ID,
            workspace_id=WORKSPACE_ID,
            idempotency_key="grant:new",
            notice_version=NOVEL_EMBEDDING_CONSENT_NOTICE_VERSION,
            corpora=CORPORA,
            actor="test-author",
            expected_version=0,
        )

    assert captured.value.code == "consent_version_conflict"
    assert session.records == [revoked]


def test_revoke_replay_is_a_noop_before_stale_cas() -> None:
    novel_id = uuid4()
    active = _consent(novel_id, key="grant:1", revoked=False)
    session = ConsentHistorySession(novel_id, (active,))

    first = persistence.revoke_consent(
        session,
        novel_id=novel_id,
        consent_id=active.id,
        owner_id=OWNER_ID,
        workspace_id=WORKSPACE_ID,
        actor="test-author",
        reason="author_revoked",
        expected_version=1,
    )
    replay = persistence.revoke_consent(
        session,
        novel_id=novel_id,
        consent_id=active.id,
        owner_id=OWNER_ID,
        workspace_id=WORKSPACE_ID,
        actor="test-author",
        reason="author_revoked",
        expected_version=1,
    )

    assert replay is first
    assert persistence.load_consent_history(
        session,
        novel_id=novel_id,
        owner_id=OWNER_ID,
        workspace_id=WORKSPACE_ID,
    ).version == 2


@pytest.mark.parametrize(
    "change",
    ("notice", "scope", "provider", "model"),
)
def test_existing_consent_target_drift_requires_reconsent(change: str) -> None:
    values: dict[str, Any] = {
        "notice_version": NOVEL_EMBEDDING_CONSENT_NOTICE_VERSION,
        "corpora": CORPORA,
        "provider_id": "aliyun-bailian",
        "model_id": "qwen3.7-text-embedding",
    }
    if change == "notice":
        values["notice_version"] = "novel-embedding-consent/1"
    elif change == "scope":
        values["corpora"] = ("manuscript",)
    consent = _consent(
        uuid4(),
        key="grant:1",
        revoked=False,
        notice_version=values["notice_version"],
        corpora=values["corpora"],
    )
    provider_id = "provider:new" if change == "provider" else values["provider_id"]
    model_id = "model:new" if change == "model" else values["model_id"]

    assert consent_state_for_target(
        consent,
        provider_id=provider_id,
        model_id=model_id,
    ) is NovelEmbeddingConsentState.REQUIRES_RECONSENT


def test_temporary_configuration_unavailability_does_not_revoke_consent() -> None:
    consent = _consent(uuid4(), key="grant:1", revoked=False)

    assert consent_state_for_target(consent) is NovelEmbeddingConsentState.GRANTED


def test_active_target_requires_available_matching_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generation_id = uuid4()
    profile_id = uuid4()
    configuration = SimpleNamespace(
        version=7,
        credential_ref="credential:test",
        connection_state="available",
        active_generation_id=generation_id,
    )
    generation = SimpleNamespace(
        id=generation_id,
        profile_id=profile_id,
        state="active",
    )
    profile = SimpleNamespace(
        id=profile_id,
        provider_id="aliyun-bailian",
        actual_model_id="qwen3.7-text-embedding",
        dimension=2048,
        connection_state="available",
        credential_ref="credential:test",
    )
    monkeypatch.setattr(
        consent_service,
        "get_configuration",
        lambda *_args, **_kwargs: configuration,
    )

    target, reason = resolve_active_embedding_consent_target(
        TargetSession(generation, profile),
        owner_id=OWNER_ID,
        workspace_id=WORKSPACE_ID,
    )
    assert target == ActiveEmbeddingConsentTarget(
        configuration_version=7,
        generation_id=generation_id,
        provider_id="aliyun-bailian",
        model_id="qwen3.7-text-embedding",
    )
    assert reason is None

    profile.credential_ref = "credential:stale"
    target, reason = resolve_active_embedding_consent_target(
        TargetSession(generation, profile),
        owner_id=OWNER_ID,
        workspace_id=WORKSPACE_ID,
    )
    assert target is None
    assert reason == "active_profile_unavailable"


def test_valid_active_configuration_prepares_consent_without_commit_or_enqueue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = uuid4()
    generation_id = uuid4()
    session = ConsentHistorySession(novel_id)
    target = ActiveEmbeddingConsentTarget(
        configuration_version=7,
        generation_id=generation_id,
        provider_id="aliyun-bailian",
        model_id="qwen3.7-text-embedding",
    )
    captured: dict[str, Any] = {}
    consent = _consent(novel_id, key="new-book:1", revoked=False)
    monkeypatch.setattr(
        consent_service,
        "resolve_active_embedding_consent_target",
        lambda *_args, **_kwargs: (target, None),
    )

    def fake_grant(_session: Any, **kwargs: Any) -> NovelEmbeddingConsent:
        captured.update(kwargs)
        return consent

    monkeypatch.setattr(consent_service, "grant_consent", fake_grant)

    prepared = prepare_new_novel_default_consent(
        session,
        novel_id=novel_id,
        owner_id=OWNER_ID,
        workspace_id=WORKSPACE_ID,
        operation_key="new-book:1",
    )

    assert prepared.state is NovelEmbeddingConsentState.GRANTED
    assert prepared.consent_id == consent.id
    assert prepared.created is True
    assert prepared.enqueue_after_commit is True
    assert prepared.generation_id == generation_id
    assert captured["expected_version"] == 0
    assert captured["corpora"] == CORPORA
    assert captured["provider_id"] == "aliyun-bailian"
    assert captured["model_id"] == "qwen3.7-text-embedding"
    assert session.commit_count == 0


@pytest.mark.parametrize(
    "reason_code",
    (
        "embedding_configuration_missing",
        "embedding_credential_missing",
        "embedding_configuration_unavailable",
        "active_generation_missing",
        "active_generation_unavailable",
        "active_profile_unavailable",
    ),
)
def test_invalid_configuration_keeps_new_novel_local_and_never_grants(
    monkeypatch: pytest.MonkeyPatch,
    reason_code: str,
) -> None:
    novel_id = uuid4()
    session = ConsentHistorySession(novel_id)
    monkeypatch.setattr(
        consent_service,
        "resolve_active_embedding_consent_target",
        lambda *_args, **_kwargs: (None, reason_code),
    )
    monkeypatch.setattr(
        consent_service,
        "grant_consent",
        lambda *_args, **_kwargs: pytest.fail("invalid configuration must not grant"),
    )

    prepared = prepare_new_novel_default_consent(
        session,
        novel_id=novel_id,
        owner_id=OWNER_ID,
        workspace_id=WORKSPACE_ID,
    )

    assert prepared.state is NovelEmbeddingConsentState.NOT_AUTHORIZED
    assert prepared.reason_code == reason_code
    assert prepared.consent_id is None
    assert prepared.enqueue_after_commit is False
    assert session.commit_count == 0


def test_default_path_never_reauthorizes_an_existing_revoked_novel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = uuid4()
    revoked = _consent(novel_id, key="manual:old", revoked=True)
    session = ConsentHistorySession(novel_id, (revoked,))
    target = ActiveEmbeddingConsentTarget(
        configuration_version=7,
        generation_id=uuid4(),
        provider_id="aliyun-bailian",
        model_id="qwen3.7-text-embedding",
    )
    monkeypatch.setattr(
        consent_service,
        "resolve_active_embedding_consent_target",
        lambda *_args, **_kwargs: (target, None),
    )
    monkeypatch.setattr(persistence, "_attach_consent_to_candidate", lambda *_a, **_k: None)

    with pytest.raises(EmbeddingLifecycleError) as captured:
        prepare_new_novel_default_consent(
            session,
            novel_id=novel_id,
            owner_id=OWNER_ID,
            workspace_id=WORKSPACE_ID,
        )

    assert captured.value.code == "consent_version_conflict"
    assert session.records == [revoked]


def test_exact_new_novel_prepare_replay_does_not_request_another_enqueue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = uuid4()
    active = _consent(
        novel_id,
        key=f"new-novel-default:{novel_id}",
        revoked=False,
    )
    session = ConsentHistorySession(novel_id, (active,))
    target = ActiveEmbeddingConsentTarget(
        configuration_version=7,
        generation_id=uuid4(),
        provider_id="aliyun-bailian",
        model_id="qwen3.7-text-embedding",
    )
    monkeypatch.setattr(
        consent_service,
        "resolve_active_embedding_consent_target",
        lambda *_args, **_kwargs: (target, None),
    )

    replay = prepare_new_novel_default_consent(
        session,
        novel_id=novel_id,
        owner_id=OWNER_ID,
        workspace_id=WORKSPACE_ID,
    )

    assert replay.consent_id == active.id
    assert replay.consent_version == 1
    assert replay.created is False
    assert replay.enqueue_after_commit is False
    assert len(session.records) == 1


def test_enqueue_is_explicitly_after_commit_and_exact_replay_does_not_enqueue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = uuid4()
    calls: list[UUID] = []
    monkeypatch.setattr(
        "backend.embedding.indexing.request_active_novel_refresh",
        lambda _session, requested_novel_id: calls.append(requested_novel_id) or True,
    )
    prepared = consent_service.NewNovelConsentPreparation(
        novel_id=novel_id,
        owner_id=OWNER_ID,
        workspace_id=WORKSPACE_ID,
        state=NovelEmbeddingConsentState.GRANTED,
        consent_version=1,
        consent_id=uuid4(),
        configuration_version=7,
        generation_id=uuid4(),
        provider_id="aliyun-bailian",
        model_id="qwen3.7-text-embedding",
        created=True,
        enqueue_after_commit=True,
    )
    replay = consent_service.NewNovelConsentPreparation(
        novel_id=novel_id,
        owner_id=OWNER_ID,
        workspace_id=WORKSPACE_ID,
        state=NovelEmbeddingConsentState.GRANTED,
        consent_version=1,
        consent_id=prepared.consent_id,
        configuration_version=7,
        generation_id=prepared.generation_id,
        provider_id=prepared.provider_id,
        model_id=prepared.model_id,
        created=False,
        enqueue_after_commit=False,
    )
    active = _consent(novel_id, key="new-novel:1", revoked=False)
    active.id = prepared.consent_id
    session = ConsentHistorySession(novel_id, (active,))
    monkeypatch.setattr(
        consent_service,
        "resolve_active_embedding_consent_target",
        lambda *_args, **_kwargs: (
            ActiveEmbeddingConsentTarget(
                configuration_version=7,
                generation_id=prepared.generation_id,
                provider_id="aliyun-bailian",
                model_id="qwen3.7-text-embedding",
            ),
            None,
        ),
    )

    assert enqueue_new_novel_index_after_commit(session, prepared) is True
    assert enqueue_new_novel_index_after_commit(session, replay) is False
    assert calls == [novel_id]
    assert session.commit_count == 0

    monkeypatch.setattr(
        consent_service,
        "resolve_active_embedding_consent_target",
        lambda *_args, **_kwargs: (
            ActiveEmbeddingConsentTarget(
                configuration_version=8,
                generation_id=uuid4(),
                provider_id="aliyun-bailian",
                model_id="model:changed",
            ),
            None,
        ),
    )
    assert enqueue_new_novel_index_after_commit(session, prepared) is False
    assert calls == [novel_id]
