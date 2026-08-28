"""Edition render-cache planning without synthesis or media I/O.

The caller owns one short database transaction.  This module only resolves
authoritative ready-cache hits, idempotently enqueues cache misses, and creates
the pending render rows required by workers.  It never calls Nano, FFmpeg, the
filesystem, or a network service.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from ..models import (
    BackgroundJob,
    NarrationEdition,
    NarrationEditionSegment,
    NarrationSegmentRender,
)

from .contracts import NarrationRequestScope
from .digest_keyring import DigestKeyring
from .editions import advance_edition_segment_state
from .jobs import (
    EnqueueResult,
    JobIdempotencyConflict,
    JobServiceError,
    enqueue_job,
)
from .renders import (
    CreateRender,
    create_or_reuse_render,
    render_job_input_hash,
)
from .services import (
    IdempotencyConflict,
    InvalidNarrationState,
    NarrationScopeMismatch,
    NarrationStore,
    canonical_sha256,
    require_exact_int,
    require_row,
    require_same_novel,
)


SEGMENT_RENDER_JOB_KIND = "narration.segment_render"
SEGMENT_RENDER_RESOURCE_CLASS = "moss-nano"


class RenderJobQueue(Protocol):
    """Narrow queue boundary used by the transaction-shaped domain service."""

    def enqueue_segment_render(
        self,
        *,
        novel_id: UUID,
        request_id: UUID,
        edition_segment_id: UUID,
        render_fingerprint: str,
        base_priority: int,
        max_attempts: int,
    ) -> EnqueueResult: ...


class SqlAlchemyRenderJobQueue:
    """Production adapter over the existing fenced background-job service."""

    def __init__(
        self,
        session: Session,
        *,
        scope: NarrationRequestScope = NarrationRequestScope.fixed_local(),
    ) -> None:
        if not isinstance(session, Session):
            raise TypeError("render job queue requires a SQLAlchemy Session")
        self._session = session
        self._scope = scope

    def enqueue_segment_render(
        self,
        *,
        novel_id: UUID,
        request_id: UUID,
        edition_segment_id: UUID,
        render_fingerprint: str,
        base_priority: int,
        max_attempts: int,
    ) -> EnqueueResult:
        input_hash = render_job_input_hash(
            edition_segment_id=edition_segment_id,
            render_fingerprint=render_fingerprint,
        )
        idempotency_key = "narration-render:" + canonical_sha256(
            {
                "schema_version": "narration-segment-render-enqueue/1",
                "edition_segment_id": str(edition_segment_id),
                "render_fingerprint": render_fingerprint,
            }
        )
        try:
            return enqueue_job(
                self._session,
                scope=self._scope,
                job_kind=SEGMENT_RENDER_JOB_KIND,
                input_hash=input_hash,
                idempotency_key=idempotency_key,
                resource_class=SEGMENT_RENDER_RESOURCE_CLASS,
                novel_id=novel_id,
                request_id=request_id,
                base_priority=base_priority,
                max_attempts=max_attempts,
            )
        except JobIdempotencyConflict as error:
            raise IdempotencyConflict(
                "segment-render enqueue idempotency conflict"
            ) from error
        except JobServiceError as error:
            raise InvalidNarrationState(
                "segment-render job could not be enqueued"
            ) from error


@dataclass(frozen=True, slots=True)
class RenderPlan:
    edition_id: UUID
    job_ids: tuple[UUID, ...]
    ready_cache_hits: int
    in_flight_reuses: int
    cache_misses: int


def _validate_existing_render(
    store: NarrationStore,
    *,
    edition: NarrationEdition,
    segment: NarrationEditionSegment,
    render: NarrationSegmentRender,
    digest_keyring: DigestKeyring,
) -> None:
    if (
        render.owner_id != edition.owner_id
        or render.workspace_id != edition.workspace_id
        or render.novel_id != edition.novel_id
        or render.render_fingerprint != segment.render_fingerprint
        or render.voice_version_id != segment.voice_version_id
        or render.model_fingerprint != edition.tts_fingerprint
        or render.postprocess_fingerprint != edition.postprocess_fingerprint
    ):
        raise NarrationScopeMismatch(
            "render cache entry differs from the immutable Edition segment"
        )
    # Reuse the authoritative renderer's full canonical-input and voice-rights
    # validation instead of maintaining another cache state machine here.
    create_or_reuse_render(
        store,
        CreateRender(
            edition_segment_id=segment.id,
            digest_keyring=digest_keyring,
            source_job_id=(None if render.state == "ready" else render.source_job_id),
        ),
    )


def plan_edition_renders(
    store: NarrationStore,
    queue: RenderJobQueue,
    *,
    edition_id: UUID,
    digest_keyring: DigestKeyring,
    base_priority: int = 0,
    max_attempts: int = 3,
) -> RenderPlan:
    """Resolve every Edition segment to one ready render or one fenced job.

    In-flight work can only be replayed by the same generation request.  A
    cross-request in-flight cache transfer has no frozen fencing contract and
    therefore fails closed; ready renders remain reusable within the novel.
    """

    if type(digest_keyring) is not DigestKeyring:
        raise InvalidNarrationState("render planning requires a digest keyring")
    require_exact_int(base_priority, field="base_priority", minimum=-1000)
    require_exact_int(max_attempts, field="max_attempts", minimum=1)
    edition = require_row(
        store.get(NarrationEdition, edition_id, for_update=True),
        label="narration Edition",
    )
    segments = store.find_all(
        NarrationEditionSegment,
        edition_id=edition.id,
        order_by=("ordinal",),
        for_update=True,
    )
    if not segments or [row.ordinal for row in segments] != list(range(len(segments))):
        raise InvalidNarrationState(
            "Edition render planning requires a complete contiguous segment set"
        )

    job_ids: list[UUID] = []
    ready_hits = 0
    in_flight_reuses = 0
    misses = 0
    for segment in segments:
        existing = store.find_one(
            NarrationSegmentRender,
            owner_id=edition.owner_id,
            workspace_id=edition.workspace_id,
            render_fingerprint=segment.render_fingerprint,
        )
        if existing is not None:
            if existing.state == "ready":
                _validate_existing_render(
                    store,
                    edition=edition,
                    segment=segment,
                    render=existing,
                    digest_keyring=digest_keyring,
                )
                advance_edition_segment_state(
                    store,
                    segment.id,
                    new_state="ready",
                )
                ready_hits += 1
                continue
            if existing.state not in {"pending", "rendering"}:
                raise InvalidNarrationState(
                    "terminal non-ready render retry remains HOLD"
                )
            if existing.request_id != edition.request_id:
                raise InvalidNarrationState(
                    "cross-request in-flight render reuse has no publication fence"
                )
            _validate_existing_render(
                store,
                edition=edition,
                segment=segment,
                render=existing,
                digest_keyring=digest_keyring,
            )
            job = require_row(
                store.get(BackgroundJob, existing.source_job_id),
                label="in-flight render job",
            )
            require_same_novel(job.novel_id, edition.novel_id, label="render job")
            advance_edition_segment_state(
                store,
                segment.id,
                new_state=("rendering" if existing.state == "rendering" else "queued"),
            )
            job_ids.append(job.id)
            in_flight_reuses += 1
            continue

        if segment.render_digest_key_id != digest_keyring.active_key_id:
            raise InvalidNarrationState(
                "render cache miss requires a new Edition with the active digest key"
            )
        result = queue.enqueue_segment_render(
            novel_id=edition.novel_id,
            request_id=edition.request_id,
            edition_segment_id=segment.id,
            render_fingerprint=segment.render_fingerprint,
            base_priority=base_priority,
            max_attempts=max_attempts,
        )
        create_or_reuse_render(
            store,
            CreateRender(
                edition_segment_id=segment.id,
                digest_keyring=digest_keyring,
                source_job_id=result.job_id,
            ),
        )
        advance_edition_segment_state(
            store,
            segment.id,
            new_state="queued",
        )
        job_ids.append(result.job_id)
        misses += 1

    # Preserve ordinal order while making replay output canonical.
    canonical_jobs = tuple(dict.fromkeys(job_ids))
    return RenderPlan(
        edition_id=edition.id,
        job_ids=canonical_jobs,
        ready_cache_hits=ready_hits,
        in_flight_reuses=in_flight_reuses,
        cache_misses=misses,
    )


__all__ = [
    "RenderJobQueue",
    "RenderPlan",
    "SEGMENT_RENDER_JOB_KIND",
    "SEGMENT_RENDER_RESOURCE_CLASS",
    "SqlAlchemyRenderJobQueue",
    "plan_edition_renders",
]
