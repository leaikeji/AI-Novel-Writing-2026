from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from backend.creative_data_models import (
    EmbeddingGenerationNovel,
    SemanticSource,
    SemanticSourceRefresh,
)
from backend.embedding.refresh import (
    IncrementalRefreshService,
    PendingSourceSpec,
    PublicationAuthority,
    RefreshBuildState,
    RefreshRequest,
    RefreshServiceError,
)


NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


class MemoryStore:
    def __init__(self, build: EmbeddingGenerationNovel) -> None:
        self.build = build
        self.refreshes: dict[UUID, SemanticSourceRefresh] = {}
        self.sources: dict[UUID, SemanticSource] = {}
        self.build_evidence: dict[UUID, RefreshBuildState] = {}
        self.index_counts = (1, 2, 2)
        self.flush_count = 0

    def get_build_for_update(self, generation_id: UUID, novel_id: UUID):
        if (self.build.generation_id, self.build.novel_id) == (generation_id, novel_id):
            return self.build
        return None

    def find_refresh_by_digest(
        self, generation_id: UUID, novel_id: UUID, request_digest: str
    ):
        return next(
            (
                item
                for item in self.refreshes.values()
                if item.generation_id == generation_id
                and item.novel_id == novel_id
                and item.request_digest == request_digest
            ),
            None,
        )

    def active_refreshes_for_source(
        self,
        generation_id: UUID,
        novel_id: UUID,
        source_type: str,
        source_entity_id: UUID,
    ):
        return tuple(
            item
            for item in self.refreshes.values()
            if item.generation_id == generation_id
            and item.novel_id == novel_id
            and item.source_type == source_type
            and item.source_entity_id == source_entity_id
            and item.state in {"pending", "queued", "building", "ready"}
        )

    def get_refresh_for_update(self, refresh_id: UUID):
        return self.refreshes.get(refresh_id)

    def get_source_for_update(self, source_id: UUID):
        return self.sources.get(source_id)

    def current_sources_for_logical_key(
        self,
        generation_id: UUID,
        novel_id: UUID,
        source_type: str,
        source_entity_id: UUID,
        logical_key: str,
    ):
        return tuple(
            item
            for item in self.sources.values()
            if item.generation_id == generation_id
            and item.novel_id == novel_id
            and item.source_type == source_type
            and item.source_entity_id == source_entity_id
            and item.status == "current"
            and item.source_locator_json.get("_refresh_logical_key") == logical_key
        )

    def refresh_build_state(self, refresh: SemanticSourceRefresh):
        return self.build_evidence.get(refresh.id, RefreshBuildState(0, 0, 0, 0, 0))

    def active_refresh_count(self, generation_id: UUID, novel_id: UUID) -> int:
        return sum(
            item.generation_id == generation_id
            and item.novel_id == novel_id
            and item.state in {"pending", "queued", "building", "ready"}
            for item in self.refreshes.values()
        )

    def current_index_counts(self, generation_id: UUID, novel_id: UUID):
        return self.index_counts

    def add(self, value: object) -> None:
        if isinstance(value, SemanticSourceRefresh):
            self.refreshes[value.id] = value
        elif isinstance(value, SemanticSource):
            self.sources[value.id] = value
        else:  # pragma: no cover - protects the test adapter contract
            raise AssertionError(type(value))

    def flush(self) -> None:
        self.flush_count += 1


def make_build() -> EmbeddingGenerationNovel:
    return EmbeddingGenerationNovel(
        id=uuid4(),
        generation_id=uuid4(),
        novel_id=uuid4(),
        owner_id=uuid4(),
        workspace_id=uuid4(),
        consent_id=uuid4(),
        state="ready",
        target_corpora_json=["manuscript"],
        input_digest=HASH_A,
        source_count=1,
        chunk_count=2,
        embedded_count=2,
        failure_count=0,
        index_version=3,
        authority_digest=HASH_A,
        published_digest=HASH_A,
        sync_state="current",
        pending_refresh_count=0,
    )


def make_request(
    build: EmbeddingGenerationNovel,
    *,
    entity_id: UUID | None = None,
    revision_id: UUID | None = None,
    content_hash: str = HASH_B,
    authority_digest: str = HASH_B,
    logical_key: str = "chapter:1:segment:0",
) -> RefreshRequest:
    return RefreshRequest(
        generation_id=build.generation_id,
        novel_id=build.novel_id,
        novel_authority_digest=authority_digest,
        source=PendingSourceSpec(
            corpus="manuscript",
            source_type="chapter_revision",
            source_entity_id=entity_id or uuid4(),
            source_revision_id=revision_id or uuid4(),
            content_hash=content_hash,
            renderer_version="manuscript/2",
            logical_key=logical_key,
            source_locator={"segment": 0},
            visibility={"visibility": "public"},
            narrative_sequence_start=1,
            narrative_sequence_end=1,
            story_sequence_start=1,
            story_sequence_end=1,
        ),
    )


def make_current_source(command: RefreshRequest) -> SemanticSource:
    source = command.source
    return SemanticSource(
        id=uuid4(),
        generation_id=command.generation_id,
        novel_id=command.novel_id,
        corpus=source.corpus,
        source_type=source.source_type,
        source_entity_id=source.source_entity_id,
        source_revision_id=uuid4(),
        source_locator_json={"_refresh_logical_key": source.logical_key},
        content_hash=HASH_A,
        renderer_version="manuscript/1",
        visibility_json={"visibility": "public"},
        status="current",
        source_fingerprint=HASH_A,
    )


def prepare_ready(
    service: IncrementalRefreshService, store: MemoryStore, command: RefreshRequest
):
    result = service.request(command)
    service.mark_queued(result.refresh_id)
    service.mark_building(result.refresh_id)
    store.build_evidence[result.refresh_id] = RefreshBuildState(2, 2, 0, 3, 3)
    service.mark_ready(result.refresh_id)
    return result


def authority_for(command: RefreshRequest, **changes: object) -> PublicationAuthority:
    values = {
        "novel_authority_digest": command.novel_authority_digest,
        "source_revision_id": command.source.source_revision_id,
        "content_hash": command.source.content_hash,
        "consent_active": True,
        "source_in_scope": True,
    }
    values.update(changes)
    return PublicationAuthority(**values)  # type: ignore[arg-type]


def test_request_is_idempotent_and_creates_one_pending_source() -> None:
    build = make_build()
    store = MemoryStore(build)
    service = IncrementalRefreshService(store, clock=lambda: NOW)
    command = make_request(build)

    first = service.request(command)
    second = service.request(command)

    assert first.created is True
    assert second.created is False
    assert first.refresh_id == second.refresh_id
    assert len(store.refreshes) == len(store.sources) == 1
    assert store.sources[first.pending_source_id].status == "pending"
    assert build.pending_refresh_count == 1
    assert (build.state, build.sync_state) == ("updating", "updating")
    assert build.authority_digest == HASH_B


def test_new_head_supersedes_only_the_same_logical_slot() -> None:
    build = make_build()
    store = MemoryStore(build)
    service = IncrementalRefreshService(store, clock=lambda: NOW)
    entity_id = uuid4()
    first = make_request(build, entity_id=entity_id, logical_key="segment:0")
    sibling = make_request(build, entity_id=entity_id, logical_key="segment:1")
    first_result = service.request(first)
    sibling_result = service.request(sibling)
    replacement = make_request(
        build,
        entity_id=entity_id,
        revision_id=uuid4(),
        content_hash=HASH_C,
        authority_digest=HASH_C,
        logical_key="segment:0",
    )

    replacement_result = service.request(replacement)

    assert store.refreshes[first_result.refresh_id].state == "superseded"
    assert store.sources[first_result.pending_source_id].status == "invalid"
    assert store.refreshes[sibling_result.refresh_id].state == "pending"
    assert store.refreshes[replacement_result.refresh_id].state == "pending"
    assert build.pending_refresh_count == 2


def test_mark_ready_requires_batches_and_one_embedding_per_chunk() -> None:
    build = make_build()
    store = MemoryStore(build)
    service = IncrementalRefreshService(store, clock=lambda: NOW)
    result = service.request(make_request(build))
    service.mark_building(result.refresh_id)
    store.build_evidence[result.refresh_id] = RefreshBuildState(2, 2, 0, 3, 2)

    with pytest.raises(RefreshServiceError) as caught:
        service.mark_ready(result.refresh_id)

    assert caught.value.code == "refresh_build_incomplete"
    assert store.refreshes[result.refresh_id].state == "building"


def test_stale_head_is_recorded_and_cannot_publish() -> None:
    build = make_build()
    store = MemoryStore(build)
    service = IncrementalRefreshService(store, clock=lambda: NOW)
    command = make_request(build)
    result = prepare_ready(service, store, command)
    old_version = build.index_version

    outcome = service.publish(
        result.refresh_id,
        authority_for(command, source_revision_id=uuid4()),
    )

    assert outcome.published is False
    assert outcome.code == "stale_authority"
    assert store.refreshes[result.refresh_id].state == "superseded"
    assert store.sources[result.pending_source_id].status == "invalid"
    assert build.index_version == old_version
    assert build.pending_refresh_count == 0
    assert (build.state, build.sync_state) == ("outdated", "outdated")


def test_publish_atomically_retires_current_and_advances_index_version() -> None:
    build = make_build()
    store = MemoryStore(build)
    service = IncrementalRefreshService(store, clock=lambda: NOW)
    command = make_request(build)
    old = make_current_source(command)
    store.sources[old.id] = old
    result = prepare_ready(service, store, command)
    store.index_counts = (1, 3, 3)

    outcome = service.publish(result.refresh_id, authority_for(command))

    assert outcome.published is True
    assert outcome.already_published is False
    assert old.status == "retired"
    assert store.sources[result.pending_source_id].status == "current"
    assert store.refreshes[result.refresh_id].state == "published"
    assert build.index_version == 4
    assert build.pending_refresh_count == 0
    assert build.published_digest == HASH_B
    assert (build.state, build.sync_state) == ("ready", "current")
    assert (build.source_count, build.chunk_count, build.embedded_count) == (1, 3, 3)
    assert store.refreshes[result.refresh_id].published_at == NOW


def test_publication_stays_updating_while_an_independent_refresh_is_pending() -> None:
    build = make_build()
    store = MemoryStore(build)
    service = IncrementalRefreshService(store, clock=lambda: NOW)
    first = make_request(build, entity_id=uuid4(), logical_key="chapter:1")
    first_result = prepare_ready(service, store, first)
    second = make_request(
        build,
        entity_id=uuid4(),
        content_hash=HASH_C,
        authority_digest=HASH_C,
        logical_key="chapter:2",
    )
    service.request(second)

    outcome = service.publish(
        first_result.refresh_id,
        authority_for(first, novel_authority_digest=HASH_C),
    )

    assert outcome.published is True
    assert build.pending_refresh_count == 1
    assert (build.state, build.sync_state) == ("updating", "updating")
    assert build.published_digest == HASH_A


def test_revoked_consent_discards_pending_without_deleting_local_index() -> None:
    build = make_build()
    store = MemoryStore(build)
    service = IncrementalRefreshService(store, clock=lambda: NOW)
    command = make_request(build)
    result = prepare_ready(service, store, command)

    outcome = service.publish(
        result.refresh_id, authority_for(command, consent_active=False)
    )

    assert outcome.code == "consent_revoked"
    assert store.refreshes[result.refresh_id].state == "cancelled"
    assert store.sources[result.pending_source_id].status == "invalid"
    assert build.sync_state == "revoked"
    assert build.index_version == 3


def test_service_never_owns_commit_or_cloud_transport() -> None:
    import inspect

    from backend.embedding.refresh import service as module

    source = inspect.getsource(module)
    assert ".commit(" not in source
    assert "DashScope" not in source
    assert "httpx" not in source
