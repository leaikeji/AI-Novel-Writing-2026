"""Frozen contracts for one-source incremental semantic-index refreshes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PendingSourceSpec:
    """A locally rendered source waiting for chunks and embeddings.

    ``logical_key`` identifies the replaceable slot.  It is deliberately
    separate from ``source_fingerprint``: an immutable, retired source may
    retain its fingerprint while a later refresh reuses the logical slot.
    """

    corpus: str
    source_type: str
    source_entity_id: UUID
    source_revision_id: UUID | None
    content_hash: str
    renderer_version: str
    logical_key: str
    source_locator: Mapping[str, object] = field(default_factory=dict)
    visibility: Mapping[str, object] = field(default_factory=dict)
    timeline_id: UUID | None = None
    character_instance_id: UUID | None = None
    narrative_sequence_start: int | None = None
    narrative_sequence_end: int | None = None
    story_sequence_start: int | None = None
    story_sequence_end: int | None = None


@dataclass(frozen=True, slots=True)
class RefreshRequest:
    generation_id: UUID
    novel_id: UUID
    novel_authority_digest: str
    source: PendingSourceSpec


@dataclass(frozen=True, slots=True)
class RefreshRequestResult:
    refresh_id: UUID
    pending_source_id: UUID
    request_digest: str
    created: bool


@dataclass(frozen=True, slots=True)
class PublicationAuthority:
    """Fresh authoritative observation made immediately before publication.

    The caller resolves current heads/bindings and consent without performing
    cloud I/O.  The service compares the concrete revision and content hash;
    the booleans are not substitutes for those comparisons.
    """

    novel_authority_digest: str
    source_revision_id: UUID | None
    content_hash: str
    consent_active: bool
    source_in_scope: bool


@dataclass(frozen=True, slots=True)
class RefreshBuildState:
    batch_count: int
    ready_batch_count: int
    failed_batch_count: int
    chunk_count: int
    embedded_count: int

    @property
    def complete(self) -> bool:
        return (
            self.batch_count > 0
            and self.ready_batch_count == self.batch_count
            and self.failed_batch_count == 0
            and self.chunk_count > 0
            and self.embedded_count == self.chunk_count
        )


@dataclass(frozen=True, slots=True)
class PublishResult:
    refresh_id: UUID
    published: bool
    already_published: bool
    code: str | None
    index_version: int
    sync_state: str
