"""Transactional domain service for incremental semantic-source refreshes.

This module never commits and never performs network I/O.  Rendering,
chunking and embedding happen through existing indexing/worker adapters; this
service owns only the durable refresh state and the atomic publication fence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Callable, Protocol, Sequence
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...creative_data_models import (
    EmbeddingGenerationNovel,
    EmbeddingIndexBatch,
    SemanticChunk,
    SemanticEmbedding,
    SemanticSource,
    SemanticSourceRefresh,
)
from .contracts import (
    PendingSourceSpec,
    PublicationAuthority,
    PublishResult,
    RefreshBuildState,
    RefreshRequest,
    RefreshRequestResult,
)


ACTIVE_REFRESH_STATES = frozenset({"pending", "queued", "building", "ready"})
BUILDABLE_NOVEL_STATES = frozenset({"ready", "updating", "outdated", "partial_failed"})
_LOGICAL_KEY_FIELD = "_refresh_logical_key"


class RefreshServiceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _digest(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return sha256(encoded.encode("utf-8")).hexdigest()


def _require_digest(value: str, *, field_name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise RefreshServiceError("invalid_digest", f"{field_name} must be lowercase sha256")


def refresh_request_digest(request: RefreshRequest) -> str:
    """Stable idempotency digest for a concrete authoritative source head."""

    source = request.source
    return _digest(
        {
            "generation_id": request.generation_id,
            "novel_id": request.novel_id,
            "corpus": source.corpus,
            "source_type": source.source_type,
            "source_entity_id": source.source_entity_id,
            "source_revision_id": source.source_revision_id,
            "content_hash": source.content_hash,
            "renderer_version": source.renderer_version,
            "logical_key": source.logical_key,
            "timeline_id": source.timeline_id,
            "character_instance_id": source.character_instance_id,
            "narrative": [
                source.narrative_sequence_start,
                source.narrative_sequence_end,
            ],
            "story": [source.story_sequence_start, source.story_sequence_end],
            "locator": dict(source.source_locator),
            "visibility": dict(source.visibility),
        }
    )


class RefreshStore(Protocol):
    """Minimal persistence port; implementations must use the caller transaction."""

    def get_build_for_update(
        self, generation_id: UUID, novel_id: UUID
    ) -> EmbeddingGenerationNovel | None: ...

    def find_refresh_by_digest(
        self, generation_id: UUID, novel_id: UUID, request_digest: str
    ) -> SemanticSourceRefresh | None: ...

    def active_refreshes_for_source(
        self, generation_id: UUID, novel_id: UUID, source_type: str, source_entity_id: UUID
    ) -> Sequence[SemanticSourceRefresh]: ...

    def get_refresh_for_update(self, refresh_id: UUID) -> SemanticSourceRefresh | None: ...

    def get_source_for_update(self, source_id: UUID) -> SemanticSource | None: ...

    def current_sources_for_logical_key(
        self,
        generation_id: UUID,
        novel_id: UUID,
        source_type: str,
        source_entity_id: UUID,
        logical_key: str,
    ) -> Sequence[SemanticSource]: ...

    def refresh_build_state(self, refresh: SemanticSourceRefresh) -> RefreshBuildState: ...

    def active_refresh_count(self, generation_id: UUID, novel_id: UUID) -> int: ...

    def current_index_counts(self, generation_id: UUID, novel_id: UUID) -> tuple[int, int, int]: ...

    def add(self, value: object) -> None: ...

    def flush(self) -> None: ...


class SqlAlchemyRefreshStore:
    """SQLAlchemy adapter with row locks on all publication authority rows."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_build_for_update(
        self, generation_id: UUID, novel_id: UUID
    ) -> EmbeddingGenerationNovel | None:
        return self.session.scalar(
            select(EmbeddingGenerationNovel)
            .where(
                EmbeddingGenerationNovel.generation_id == generation_id,
                EmbeddingGenerationNovel.novel_id == novel_id,
            )
            .with_for_update()
        )

    def find_refresh_by_digest(
        self, generation_id: UUID, novel_id: UUID, request_digest: str
    ) -> SemanticSourceRefresh | None:
        return self.session.scalar(
            select(SemanticSourceRefresh).where(
                SemanticSourceRefresh.generation_id == generation_id,
                SemanticSourceRefresh.novel_id == novel_id,
                SemanticSourceRefresh.request_digest == request_digest,
            )
        )

    def active_refreshes_for_source(
        self, generation_id: UUID, novel_id: UUID, source_type: str, source_entity_id: UUID
    ) -> Sequence[SemanticSourceRefresh]:
        return tuple(
            self.session.scalars(
                select(SemanticSourceRefresh)
                .where(
                    SemanticSourceRefresh.generation_id == generation_id,
                    SemanticSourceRefresh.novel_id == novel_id,
                    SemanticSourceRefresh.source_type == source_type,
                    SemanticSourceRefresh.source_entity_id == source_entity_id,
                    SemanticSourceRefresh.state.in_(ACTIVE_REFRESH_STATES),
                )
                .with_for_update()
            )
        )

    def get_refresh_for_update(self, refresh_id: UUID) -> SemanticSourceRefresh | None:
        return self.session.scalar(
            select(SemanticSourceRefresh)
            .where(SemanticSourceRefresh.id == refresh_id)
            .with_for_update()
        )

    def get_source_for_update(self, source_id: UUID) -> SemanticSource | None:
        return self.session.scalar(
            select(SemanticSource)
            .where(SemanticSource.id == source_id)
            .with_for_update()
        )

    def current_sources_for_logical_key(
        self,
        generation_id: UUID,
        novel_id: UUID,
        source_type: str,
        source_entity_id: UUID,
        logical_key: str,
    ) -> Sequence[SemanticSource]:
        candidates = tuple(
            self.session.scalars(
                select(SemanticSource)
                .where(
                    SemanticSource.generation_id == generation_id,
                    SemanticSource.novel_id == novel_id,
                    SemanticSource.source_type == source_type,
                    SemanticSource.source_entity_id == source_entity_id,
                    SemanticSource.status == "current",
                )
                .with_for_update()
            )
        )
        return tuple(
            source
            for source in candidates
            if source.source_locator_json.get(_LOGICAL_KEY_FIELD) == logical_key
        )

    def refresh_build_state(self, refresh: SemanticSourceRefresh) -> RefreshBuildState:
        if refresh.pending_source_id is None:
            return RefreshBuildState(0, 0, 0, 0, 0)
        states = tuple(
            self.session.scalars(
                select(EmbeddingIndexBatch.state).where(
                    EmbeddingIndexBatch.refresh_id == refresh.id
                )
            )
        )
        chunk_ids = tuple(
            self.session.scalars(
                select(SemanticChunk.id).where(
                    SemanticChunk.source_id == refresh.pending_source_id
                )
            )
        )
        embedded = 0
        if chunk_ids:
            embedded = int(
                self.session.scalar(
                    select(func.count()).select_from(SemanticEmbedding).where(
                        SemanticEmbedding.generation_id == refresh.generation_id,
                        SemanticEmbedding.chunk_id.in_(chunk_ids),
                    )
                )
                or 0
            )
        return RefreshBuildState(
            batch_count=len(states),
            ready_batch_count=sum(state == "ready" for state in states),
            failed_batch_count=sum(state in {"failed", "cancelled"} for state in states),
            chunk_count=len(chunk_ids),
            embedded_count=embedded,
        )

    def active_refresh_count(self, generation_id: UUID, novel_id: UUID) -> int:
        return int(
            self.session.scalar(
                select(func.count()).select_from(SemanticSourceRefresh).where(
                    SemanticSourceRefresh.generation_id == generation_id,
                    SemanticSourceRefresh.novel_id == novel_id,
                    SemanticSourceRefresh.state.in_(ACTIVE_REFRESH_STATES),
                )
            )
            or 0
        )

    def current_index_counts(self, generation_id: UUID, novel_id: UUID) -> tuple[int, int, int]:
        current_source_ids = tuple(
            self.session.scalars(
                select(SemanticSource.id).where(
                    SemanticSource.generation_id == generation_id,
                    SemanticSource.novel_id == novel_id,
                    SemanticSource.status == "current",
                )
            )
        )
        if not current_source_ids:
            return (0, 0, 0)
        chunk_ids = tuple(
            self.session.scalars(
                select(SemanticChunk.id).where(SemanticChunk.source_id.in_(current_source_ids))
            )
        )
        if not chunk_ids:
            return (len(current_source_ids), 0, 0)
        embedded = int(
            self.session.scalar(
                select(func.count()).select_from(SemanticEmbedding).where(
                    SemanticEmbedding.generation_id == generation_id,
                    SemanticEmbedding.chunk_id.in_(chunk_ids),
                )
            )
            or 0
        )
        return (len(current_source_ids), len(chunk_ids), embedded)

    def add(self, value: object) -> None:
        self.session.add(value)

    def flush(self) -> None:
        self.session.flush()


@dataclass(slots=True)
class IncrementalRefreshService:
    store: RefreshStore
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    def request(self, command: RefreshRequest) -> RefreshRequestResult:
        _require_digest(command.novel_authority_digest, field_name="novel_authority_digest")
        _require_digest(command.source.content_hash, field_name="content_hash")
        if not command.source.logical_key.strip():
            raise RefreshServiceError("logical_key_required", "logical_key must not be empty")
        build = self.store.get_build_for_update(command.generation_id, command.novel_id)
        if build is None:
            raise RefreshServiceError("generation_novel_not_found", "novel index build is missing")
        if build.sync_state == "revoked":
            raise RefreshServiceError("consent_revoked", "novel embedding consent is revoked")
        if build.state not in BUILDABLE_NOVEL_STATES:
            raise RefreshServiceError("generation_state_invalid", "novel index cannot refresh")

        request_digest = refresh_request_digest(command)
        existing = self.store.find_refresh_by_digest(
            command.generation_id, command.novel_id, request_digest
        )
        build.authority_digest = command.novel_authority_digest
        if existing is not None:
            if existing.pending_source_id is None:
                raise RefreshServiceError(
                    "refresh_source_missing", "idempotent refresh lost its pending source"
                )
            return RefreshRequestResult(
                refresh_id=existing.id,
                pending_source_id=existing.pending_source_id,
                request_digest=request_digest,
                created=False,
            )

        now = self.clock()
        for older in self.store.active_refreshes_for_source(
            command.generation_id,
            command.novel_id,
            command.source.source_type,
            command.source.source_entity_id,
        ):
            older_source = (
                self.store.get_source_for_update(older.pending_source_id)
                if older.pending_source_id is not None
                else None
            )
            if (
                older_source is None
                or older_source.source_locator_json.get(_LOGICAL_KEY_FIELD)
                != command.source.logical_key
            ):
                continue
            older.state = "superseded"
            older.failure_code = "SUPERSEDED_BY_NEW_HEAD"
            older.completed_at = now
            if older_source.status == "pending":
                older_source.status = "invalid"

        source_id = uuid4()
        locator = dict(command.source.source_locator)
        locator[_LOGICAL_KEY_FIELD] = command.source.logical_key
        source = SemanticSource(
            id=source_id,
            generation_id=command.generation_id,
            novel_id=command.novel_id,
            corpus=command.source.corpus,
            source_type=command.source.source_type,
            source_entity_id=command.source.source_entity_id,
            source_revision_id=command.source.source_revision_id,
            source_locator_json=locator,
            content_hash=command.source.content_hash,
            renderer_version=command.source.renderer_version,
            timeline_id=command.source.timeline_id,
            character_instance_id=command.source.character_instance_id,
            narrative_sequence_start=command.source.narrative_sequence_start,
            narrative_sequence_end=command.source.narrative_sequence_end,
            story_sequence_start=command.source.story_sequence_start,
            story_sequence_end=command.source.story_sequence_end,
            visibility_json=dict(command.source.visibility),
            status="pending",
            source_fingerprint=_digest(
                {"logical_source": command.source.logical_key, "request": request_digest}
            ),
        )
        refresh = SemanticSourceRefresh(
            id=uuid4(),
            generation_id=command.generation_id,
            novel_id=command.novel_id,
            source_type=command.source.source_type,
            source_entity_id=command.source.source_entity_id,
            source_revision_id=command.source.source_revision_id,
            target_content_hash=command.source.content_hash,
            request_digest=request_digest,
            state="pending",
            pending_source_id=source_id,
        )
        self.store.add(source)
        self.store.add(refresh)
        self.store.flush()
        build.pending_refresh_count = self.store.active_refresh_count(
            command.generation_id, command.novel_id
        )
        build.state = "updating"
        build.sync_state = "updating"
        build.failure_code = None
        self.store.flush()
        return RefreshRequestResult(
            refresh_id=refresh.id,
            pending_source_id=source.id,
            request_digest=request_digest,
            created=True,
        )

    def mark_queued(self, refresh_id: UUID) -> None:
        refresh = self._active_refresh(refresh_id, allowed={"pending", "queued"})
        refresh.state = "queued"
        self.store.flush()

    def mark_building(self, refresh_id: UUID) -> None:
        refresh = self._active_refresh(refresh_id, allowed={"pending", "queued", "building"})
        refresh.state = "building"
        if refresh.started_at is None:
            refresh.started_at = self.clock()
        self.store.flush()

    def mark_ready(self, refresh_id: UUID) -> RefreshBuildState:
        refresh = self._active_refresh(refresh_id, allowed={"building", "ready"})
        evidence = self.store.refresh_build_state(refresh)
        if not evidence.complete:
            raise RefreshServiceError(
                "refresh_build_incomplete", "every pending chunk must have a ready embedding"
            )
        refresh.state = "ready"
        refresh.failure_code = None
        refresh.completed_at = self.clock()
        self.store.flush()
        return evidence

    def publish(
        self, refresh_id: UUID, authority: PublicationAuthority
    ) -> PublishResult:
        _require_digest(authority.novel_authority_digest, field_name="novel_authority_digest")
        _require_digest(authority.content_hash, field_name="content_hash")
        refresh = self.store.get_refresh_for_update(refresh_id)
        if refresh is None:
            raise RefreshServiceError("refresh_not_found", "source refresh is missing")
        build = self.store.get_build_for_update(refresh.generation_id, refresh.novel_id)
        if build is None:
            raise RefreshServiceError("generation_novel_not_found", "novel index build is missing")
        if refresh.state == "published":
            return PublishResult(
                refresh.id, True, True, None, build.index_version, build.sync_state
            )
        if refresh.state != "ready":
            raise RefreshServiceError("refresh_not_ready", "only a ready refresh can publish")
        if refresh.pending_source_id is None:
            raise RefreshServiceError("refresh_source_missing", "pending source is missing")
        if not self.store.refresh_build_state(refresh).complete:
            raise RefreshServiceError(
                "refresh_build_incomplete", "ready refresh artifacts are no longer complete"
            )
        pending = self.store.get_source_for_update(refresh.pending_source_id)
        if pending is None or pending.status != "pending":
            raise RefreshServiceError("pending_source_invalid", "pending source is not publishable")

        if not authority.consent_active:
            return self._reject(refresh, pending, build, code="consent_revoked", revoked=True)
        stale = (
            not authority.source_in_scope
            or authority.novel_authority_digest != build.authority_digest
            or authority.source_revision_id != refresh.source_revision_id
            or authority.source_revision_id != pending.source_revision_id
            or authority.content_hash != refresh.target_content_hash
            or authority.content_hash != pending.content_hash
        )
        if stale:
            return self._reject(refresh, pending, build, code="stale_authority", revoked=False)

        logical_key = pending.source_locator_json.get(_LOGICAL_KEY_FIELD)
        if not isinstance(logical_key, str) or not logical_key:
            raise RefreshServiceError("logical_key_missing", "pending source has no logical key")
        for current in self.store.current_sources_for_logical_key(
            refresh.generation_id,
            refresh.novel_id,
            refresh.source_type,
            refresh.source_entity_id,
            logical_key,
        ):
            if current.id != pending.id:
                current.status = "retired"
        pending.status = "current"
        refresh.state = "published"
        refresh.failure_code = None
        refresh.published_at = self.clock()
        refresh.completed_at = refresh.completed_at or refresh.published_at
        self.store.flush()

        build.pending_refresh_count = self.store.active_refresh_count(
            refresh.generation_id, refresh.novel_id
        )
        build.index_version += 1
        build.last_refresh_at = refresh.published_at
        source_count, chunk_count, embedded_count = self.store.current_index_counts(
            refresh.generation_id, refresh.novel_id
        )
        build.source_count = source_count
        build.chunk_count = chunk_count
        build.embedded_count = embedded_count
        if build.pending_refresh_count == 0:
            build.published_digest = authority.novel_authority_digest
            build.sync_state = "current"
            build.state = "ready"
            build.failure_code = None
            build.completed_at = refresh.published_at
        else:
            build.sync_state = "updating"
            build.state = "updating"
        self.store.flush()
        return PublishResult(
            refresh.id, True, False, None, build.index_version, build.sync_state
        )

    def fail(self, refresh_id: UUID, *, failure_code: str) -> None:
        refresh = self._active_refresh(refresh_id, allowed=ACTIVE_REFRESH_STATES)
        build = self.store.get_build_for_update(refresh.generation_id, refresh.novel_id)
        if build is None:
            raise RefreshServiceError("generation_novel_not_found", "novel index build is missing")
        pending = (
            self.store.get_source_for_update(refresh.pending_source_id)
            if refresh.pending_source_id is not None
            else None
        )
        refresh.state = "failed"
        refresh.failure_code = failure_code
        refresh.completed_at = self.clock()
        if pending is not None and pending.status == "pending":
            pending.status = "invalid"
        self.store.flush()
        build.pending_refresh_count = self.store.active_refresh_count(
            refresh.generation_id, refresh.novel_id
        )
        build.sync_state = "partial_failed"
        build.state = "partial_failed"
        build.failure_code = failure_code
        self.store.flush()

    def _active_refresh(
        self, refresh_id: UUID, *, allowed: set[str] | frozenset[str]
    ) -> SemanticSourceRefresh:
        refresh = self.store.get_refresh_for_update(refresh_id)
        if refresh is None:
            raise RefreshServiceError("refresh_not_found", "source refresh is missing")
        if refresh.state not in allowed:
            raise RefreshServiceError("refresh_state_invalid", "refresh transition is invalid")
        return refresh

    def _reject(
        self,
        refresh: SemanticSourceRefresh,
        pending: SemanticSource,
        build: EmbeddingGenerationNovel,
        *,
        code: str,
        revoked: bool,
    ) -> PublishResult:
        refresh.state = "cancelled" if revoked else "superseded"
        refresh.failure_code = code.upper()
        refresh.completed_at = self.clock()
        pending.status = "invalid"
        self.store.flush()
        build.pending_refresh_count = self.store.active_refresh_count(
            refresh.generation_id, refresh.novel_id
        )
        build.sync_state = "revoked" if revoked else "outdated"
        build.state = "cancelled" if revoked else "outdated"
        build.failure_code = code.upper()
        self.store.flush()
        return PublishResult(
            refresh.id, False, False, code, build.index_version, build.sync_state
        )


def service_for_session(
    session: Session, *, clock: Callable[[], datetime] | None = None
) -> IncrementalRefreshService:
    """Integration hook for API/worker code while preserving caller commits."""

    return IncrementalRefreshService(
        store=SqlAlchemyRefreshStore(session),
        clock=clock or (lambda: datetime.now(UTC)),
    )
