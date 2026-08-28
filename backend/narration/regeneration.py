"""T4-I local regeneration, history, and cache-only completion helpers.

The helpers in this module are deliberately transaction-shaped domain logic.
They never mutate an immutable ScriptVersion, Edition, or Manifest revision,
never perform model/media I/O, and never transfer in-flight work between
requests.  A caller owns the surrounding short transaction.

Failed-segment writes live in ``failed_segment_retry``.  This module retains a
single-segment compatibility projection, but never resets retry rows itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from ..models import (
    BackgroundJob,
    Document,
    DocumentNarrationState,
    DocumentWorkingCopy,
    NarrationEdition,
    NarrationEditionSegment,
    NarrationEditionState,
    NarrationManifest,
    NarrationPlaybackProgress,
    NarrationRequest,
    NarrationScript,
    NarrationScriptVersion,
    NarrationSegmentRender,
)

from .contracts import NarrationRequestScope
from .failed_segment_retry import project_failed_segment_retries
from .digest_keyring import DigestKeyring
from .manifest import (
    BUFFER_POLICIES,
    ManifestSegmentInput,
    PublishManifest,
    publish_manifest,
)
from .progress import (
    initialize_initial_document_edition,
    restore_playback_progress,
)
from .renders import CreateRender, compute_render_fingerprint
from .requests import advance_request_state
from .services import (
    InvalidNarrationState,
    NarrationCasConflict,
    NarrationScopeMismatch,
    NarrationStore,
    VoiceRightsUnavailable,
    require_exact_int,
    require_fixed_scope,
    require_local_novel,
    require_nonempty,
    require_row,
    require_sha256,
    require_usable_voice,
)


REGENERATION_CONTRACT_VERSION = "narration-regeneration/1"
EDITION_HISTORY_CONTRACT_VERSION = "narration-edition-history/1"
SegmentReuseState = Literal[
    "ready_cache_reused",
    "same_request_in_flight",
    "render_required",
    "failed_retry_hold",
]


@dataclass(frozen=True, slots=True)
class SegmentRegenerationProjection:
    target_edition_segment_id: UUID
    target_segment_id: UUID
    ordinal: int
    render_fingerprint: str
    prior_edition_segment_id: UUID | None
    reuse_state: SegmentReuseState
    invalidation_reason: str | None


@dataclass(frozen=True, slots=True)
class EditionRegenerationProjection:
    contract_version: str
    prior_edition_id: UUID
    target_edition_id: UUID
    total_segment_count: int
    ready_cache_reuse_count: int
    same_request_in_flight_count: int
    render_required_count: int
    failed_retry_hold_count: int
    invalidated_prior_segment_ids: tuple[UUID, ...]
    segments: tuple[SegmentRegenerationProjection, ...]


@dataclass(frozen=True, slots=True)
class CacheOnlyFinalizationResult:
    edition_id: UUID
    request_id: UUID
    request_version: int
    manifest_id: UUID
    manifest_revision: int
    manifest_etag: str
    ready_segment_count: int
    job_count: int
    replayed: bool


@dataclass(frozen=True, slots=True)
class FailedSegmentRetryEligibility:
    edition_id: UUID
    edition_segment_id: UUID
    render_id: UUID
    job_id: UUID
    job_state: str
    existing_job_manual_retry_authorizable: bool
    execution_supported: bool
    hold_reason: str | None
    fanout_segment_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class EditionHistoryItem:
    edition_id: UUID
    request_id: UUID
    source_revision_id: UUID
    source_content_hash: str
    edition_fingerprint: str
    state: str
    created_at: datetime | None
    manifest_revision: int | None
    manifest_etag: str | None
    ready_segment_count: int
    total_segment_count: int
    is_current: bool
    source_status: Literal["current", "working_copy_diverged", "superseded"]
    rights_available: bool
    playable: bool
    default_start_ready: bool
    resume_available: bool
    switch_allowed: bool


@dataclass(frozen=True, slots=True)
class DocumentEditionHistoryProjection:
    contract_version: str
    document_id: UUID
    pointer_version: int
    current_edition_id: UUID | None
    working_copy_content_hash: str
    working_copy_draft_version: int
    editions: tuple[EditionHistoryItem, ...]


def _require_scoped_edition(
    store: NarrationStore,
    edition_id: UUID,
    *,
    scope: NarrationRequestScope,
    for_update: bool = False,
) -> NarrationEdition:
    edition = require_row(
        store.get(NarrationEdition, edition_id, for_update=for_update),
        label="narration Edition",
    )
    if edition.owner_id != scope.owner_id or edition.workspace_id != scope.workspace_id:
        raise NarrationScopeMismatch("Edition is outside fixed local scope")
    require_local_novel(store, edition.novel_id)
    return edition


def _edition_segments(
    store: NarrationStore,
    edition: NarrationEdition,
    *,
    for_update: bool = False,
) -> list[NarrationEditionSegment]:
    rows = store.find_all(
        NarrationEditionSegment,
        edition_id=edition.id,
        order_by=("ordinal",),
        for_update=for_update,
    )
    if not rows or [row.ordinal for row in rows] != list(range(len(rows))):
        raise InvalidNarrationState("Edition segments must be complete and contiguous")
    for row in rows:
        require_sha256(row.render_fingerprint, field="render_fingerprint")
        if row.script_version_id != edition.script_version_id:
            raise NarrationScopeMismatch("Edition segment belongs to another script version")
    return rows


def _exact_render(
    store: NarrationStore,
    *,
    edition: NarrationEdition,
    segment: NarrationEditionSegment,
) -> NarrationSegmentRender | None:
    render = store.find_one(
        NarrationSegmentRender,
        owner_id=edition.owner_id,
        workspace_id=edition.workspace_id,
        render_fingerprint=segment.render_fingerprint,
    )
    if render is None:
        return None
    if (
        render.novel_id != edition.novel_id
        or render.render_fingerprint != segment.render_fingerprint
        or render.voice_version_id != segment.voice_version_id
        or render.model_fingerprint != edition.tts_fingerprint
        or render.postprocess_fingerprint != edition.postprocess_fingerprint
    ):
        raise NarrationScopeMismatch("render cache entry differs from the Edition segment")
    return render


def project_local_regeneration(
    store: NarrationStore,
    *,
    prior_edition_id: UUID,
    target_edition_id: UUID,
    scope: NarrationRequestScope = NarrationRequestScope.fixed_local(),
) -> EditionRegenerationProjection:
    """Project exact-fingerprint reuse without mutating either Edition.

    A fingerprint match is intentionally exact.  Similar text, anchors, or
    ordinals never authorize media reuse.  Historical ready renders can be
    reused; pending/rendering work is only recognized when it belongs to the
    target request itself.
    """

    require_fixed_scope(scope)
    if prior_edition_id == target_edition_id:
        raise InvalidNarrationState("regeneration requires two distinct Editions")
    prior = _require_scoped_edition(store, prior_edition_id, scope=scope)
    target = _require_scoped_edition(store, target_edition_id, scope=scope)
    if prior.document_id != target.document_id or prior.novel_id != target.novel_id:
        raise NarrationScopeMismatch("regeneration Editions must belong to one document")
    prior_rows = _edition_segments(store, prior)
    target_rows = _edition_segments(store, target)

    prior_by_fingerprint: dict[str, list[NarrationEditionSegment]] = {}
    for row in prior_rows:
        prior_by_fingerprint.setdefault(row.render_fingerprint, []).append(row)
    target_fingerprints = {row.render_fingerprint for row in target_rows}
    decisions: list[SegmentRegenerationProjection] = []
    for row in target_rows:
        matches = prior_by_fingerprint.get(row.render_fingerprint, [])
        prior_match = matches[0] if matches else None
        render = _exact_render(store, edition=target, segment=row)
        invalidation_reason = None if prior_match is not None else "render_fingerprint_changed"
        if row.render_state == "ready":
            if render is None or render.state != "ready":
                raise InvalidNarrationState("ready Edition segment lacks its exact ready render")
            require_usable_voice(store, row.voice_version_id, novel_id=target.novel_id)
            reuse_state: SegmentReuseState = "ready_cache_reused"
        elif row.render_state in {"pending", "queued", "rendering"}:
            if render is not None and render.state in {"pending", "rendering"}:
                if render.request_id != target.request_id:
                    raise InvalidNarrationState(
                        "cross-request in-flight render transfer remains HOLD"
                    )
                reuse_state = "same_request_in_flight"
            else:
                reuse_state = "render_required"
        elif row.render_state == "failed":
            reuse_state = "failed_retry_hold"
        else:
            reuse_state = "render_required"
        decisions.append(
            SegmentRegenerationProjection(
                target_edition_segment_id=row.id,
                target_segment_id=row.segment_id,
                ordinal=row.ordinal,
                render_fingerprint=row.render_fingerprint,
                prior_edition_segment_id=(prior_match.id if prior_match else None),
                reuse_state=reuse_state,
                invalidation_reason=invalidation_reason,
            )
        )

    return EditionRegenerationProjection(
        contract_version=REGENERATION_CONTRACT_VERSION,
        prior_edition_id=prior.id,
        target_edition_id=target.id,
        total_segment_count=len(target_rows),
        ready_cache_reuse_count=sum(
            item.reuse_state == "ready_cache_reused" for item in decisions
        ),
        same_request_in_flight_count=sum(
            item.reuse_state == "same_request_in_flight" for item in decisions
        ),
        render_required_count=sum(
            item.reuse_state == "render_required" for item in decisions
        ),
        failed_retry_hold_count=sum(
            item.reuse_state == "failed_retry_hold" for item in decisions
        ),
        invalidated_prior_segment_ids=tuple(
            row.id for row in prior_rows if row.render_fingerprint not in target_fingerprints
        ),
        segments=tuple(decisions),
    )


def finalize_ready_cache_only_edition(
    store: NarrationStore,
    *,
    edition_id: UUID,
    request_id: UUID,
    expected_request_version: int,
    expected_manifest_revision: int,
    expected_manifest_state_version: int,
    actor: str,
    digest_keyring: DigestKeyring,
    scope: NarrationRequestScope = NarrationRequestScope.fixed_local(),
) -> CacheOnlyFinalizationResult:
    """Publish and finish an all-ready, zero-job Edition in one short transaction.

    This is the integration seam for T4-A after cache planning returns no job
    IDs.  The caller must pass the pre-publication request and Manifest CAS
    tokens.  Exact replay with those same tokens is idempotent; any other
    concurrent pointer or request change fails closed.
    """

    if type(digest_keyring) is not DigestKeyring:
        raise InvalidNarrationState("cache-only finalization requires a digest keyring")
    require_fixed_scope(scope)
    require_exact_int(
        expected_request_version, field="expected_request_version", minimum=1
    )
    require_exact_int(
        expected_manifest_revision, field="expected_manifest_revision", minimum=0
    )
    require_exact_int(
        expected_manifest_state_version,
        field="expected_manifest_state_version",
        minimum=0,
    )
    require_nonempty(actor, field="actor")
    request = require_row(
        store.get(NarrationRequest, request_id, for_update=True),
        label="narration request",
    )
    if (
        request.owner_id != scope.owner_id
        or request.workspace_id != scope.workspace_id
        or request.intent not in {"create", "update"}
        or request.allows_render is not True
        or request.document_id is None
    ):
        raise NarrationScopeMismatch("cache-only request provenance is invalid")
    document = require_row(
        store.get(Document, request.document_id, for_update=True),
        label="document",
    )
    if document.novel_id != request.novel_id:
        raise NarrationScopeMismatch(
            "cache-only request belongs to another document"
        )
    edition = _require_scoped_edition(
        store, edition_id, scope=scope, for_update=True
    )
    if (
        edition.request_id != request.id
        or edition.novel_id != request.novel_id
        or edition.document_id != document.id
    ):
        raise NarrationScopeMismatch(
            "Edition belongs to another narration request/document"
        )
    version = require_row(
        store.get(NarrationScriptVersion, edition.script_version_id),
        label="approved script version",
    )
    script = require_row(store.get(NarrationScript, version.script_id), label="script")
    if (
        version.state != "approved"
        or version.approval_request_id != request.id
        or script.document_id != edition.document_id
        or script.novel_id != edition.novel_id
        or request.source_revision_id != script.revision_id
        or request.source_content_hash != script.content_hash
    ):
        raise InvalidNarrationState(
            "cache-only Edition lacks exact approved request/script provenance"
        )
    jobs = store.find_all(BackgroundJob, request_id=request.id, for_update=True)
    if jobs:
        raise InvalidNarrationState("cache-only finalization requires job_ids=0")
    rows = _edition_segments(store, edition, for_update=True)
    manifest_inputs: list[ManifestSegmentInput] = []
    for row in rows:
        if row.render_state != "ready":
            raise InvalidNarrationState("cache-only finalization requires every segment ready")
        # Re-derive the full canonical identity at the final publication
        # boundary; a persisted fingerprint string alone is not authorization
        # to attach another render's media.
        compute_render_fingerprint(
            store,
            CreateRender(
                edition_segment_id=row.id,
                digest_keyring=digest_keyring,
            ),
        )
        render = _exact_render(store, edition=edition, segment=row)
        if render is None or render.state != "ready":
            raise InvalidNarrationState("cache-only segment has no exact ready render")
        require_usable_voice(store, row.voice_version_id, novel_id=edition.novel_id)
        manifest_inputs.append(
            ManifestSegmentInput(
                edition_segment_id=row.id,
                render_status="ready",
                render_id=render.id,
            )
        )

    pointer = store.find_one(
        NarrationEditionState, edition_id=edition.id, for_update=True
    )
    current_revision = pointer.current_manifest_revision if pointer else 0
    current_state_version = pointer.version if pointer else 0
    replayed = request.state == "ready"
    if replayed:
        if request.version != expected_request_version + 2:
            raise NarrationCasConflict("cache-only request replay version changed")
        if (
            current_revision != expected_manifest_revision + 1
            or current_state_version != expected_manifest_state_version + 1
        ):
            raise NarrationCasConflict("cache-only Manifest replay pointer changed")
    else:
        if request.state != "queued" or request.version != expected_request_version:
            raise NarrationCasConflict("cache-only request version or state changed")
        if (
            current_revision != expected_manifest_revision
            or current_state_version != expected_manifest_state_version
        ):
            raise NarrationCasConflict("cache-only Manifest pointer changed")

    policy = BUFFER_POLICIES.get(edition.buffer_policy_version)
    if policy is None:
        raise InvalidNarrationState("Edition buffer policy is unsupported")
    manifest = publish_manifest(
        store,
        PublishManifest(
            edition_id=edition.id,
            expected_current_revision=expected_manifest_revision,
            expected_state_version=expected_manifest_state_version,
            buffer_policy=policy,
            segments=tuple(manifest_inputs),
            updated_actor=actor,
        ),
    )
    if manifest.status != "ready":
        raise InvalidNarrationState("cache-only finalization produced a non-ready Manifest")
    if not replayed:
        request = advance_request_state(
            store,
            request.id,
            expected_version=request.version,
            new_state="rendering",
            novel_id=edition.novel_id,
            actor=actor,
            scope=scope,
        )
        request = advance_request_state(
            store,
            request.id,
            expected_version=request.version,
            new_state="ready",
            novel_id=edition.novel_id,
            actor=actor,
            scope=scope,
        )
        initialize_initial_document_edition(
            store,
            request_id=request.id,
            document_id=document.id,
            edition_id=edition.id,
            manifest_id=manifest.id,
            scope=scope,
        )
    return CacheOnlyFinalizationResult(
        edition_id=edition.id,
        request_id=request.id,
        request_version=request.version,
        manifest_id=manifest.id,
        manifest_revision=manifest.manifest_revision,
        manifest_etag=f'"{manifest.etag_sha256}"',
        ready_segment_count=len(rows),
        job_count=0,
        replayed=replayed,
    )


def project_failed_segment_retry_eligibility(
    store: NarrationStore,
    *,
    edition_id: UUID,
    edition_segment_id: UUID,
    scope: NarrationRequestScope = NarrationRequestScope.fixed_local(),
) -> FailedSegmentRetryEligibility:
    """Compatibility projection keyed by the internal EditionSegment UUID.

    The public contract is keyed by ``NarrationSegment.id``.  Resolving through
    the complete projection fixes the historical false negative where a
    non-source fanout segment could not match the source segment-specific job
    input hash.
    """

    row = require_row(
        store.get(NarrationEditionSegment, edition_segment_id),
        label="Edition segment",
    )
    if row.edition_id != edition_id:
        raise NarrationScopeMismatch("failed segment belongs to another Edition")
    projection = project_failed_segment_retries(
        store,
        edition_id=edition_id,
        scope=scope,
    )
    item = next(
        (candidate for candidate in projection.items if candidate.segment_id == row.segment_id),
        None,
    )
    if item is None:
        raise InvalidNarrationState("retry eligibility requires a failed Edition segment")
    edition = _require_scoped_edition(store, edition_id, scope=scope)
    return FailedSegmentRetryEligibility(
        edition_id=edition_id,
        edition_segment_id=row.id,
        render_id=require_row(
            store.find_one(
                NarrationSegmentRender,
                owner_id=edition.owner_id,
                workspace_id=edition.workspace_id,
                render_fingerprint=row.render_fingerprint,
            ),
            label="failed segment render",
        ).id,
        job_id=item.job_id,
        job_state=require_row(store.get(BackgroundJob, item.job_id), label="render job").state,
        existing_job_manual_retry_authorizable=item.retryable,
        execution_supported=item.retryable,
        hold_reason=item.retry_reason_code,
        fanout_segment_ids=item.fanout_segment_ids,
    )


def _history_manifest(
    store: NarrationStore,
    edition: NarrationEdition,
) -> tuple[NarrationManifest | None, bool, int, bool]:
    state = store.find_one(NarrationEditionState, edition_id=edition.id)
    if state is None or state.current_manifest_id is None:
        return None, False, 0, False
    manifest = require_row(
        store.get(NarrationManifest, state.current_manifest_id),
        label="current Manifest",
    )
    if (
        manifest.edition_id != edition.id
        or manifest.manifest_revision != state.current_manifest_revision
    ):
        raise InvalidNarrationState("Edition current Manifest pointer is inconsistent")
    payload = manifest.canonical_json
    if (
        type(payload) is not dict
        or payload.get("edition_id") != str(edition.id)
        or payload.get("manifest_revision") != manifest.manifest_revision
        or type(payload.get("segments")) is not list
    ):
        raise InvalidNarrationState("Edition current Manifest projection is malformed")
    ready_count = sum(
        type(item) is dict and item.get("render_status") == "ready"
        for item in payload["segments"]
    )
    default_start_ready = payload.get("default_start_ready") is True
    ready_ranges = payload.get("ready_ranges")
    if type(ready_ranges) is not list:
        raise InvalidNarrationState("Edition current Manifest ready ranges are malformed")
    playable = manifest.status in {"partial_ready", "ready"} and bool(ready_ranges)
    return manifest, playable, ready_count, default_start_ready


def project_document_edition_history(
    store: NarrationStore,
    *,
    document_id: UUID,
    profile_id: str | None = None,
    scope: NarrationRequestScope = NarrationRequestScope.fixed_local(),
) -> DocumentEditionHistoryProjection:
    """Build a read-only Edition history and safe switch-eligibility projection."""

    require_fixed_scope(scope)
    if profile_id is not None:
        require_nonempty(profile_id, field="profile_id")
    document = require_row(store.get(Document, document_id), label="document")
    require_local_novel(store, document.novel_id)
    working = require_row(
        store.find_one(DocumentWorkingCopy, document_id=document.id),
        label="document working copy",
    )
    require_sha256(working.content_hash, field="working copy content_hash")
    pointer = store.find_one(
        DocumentNarrationState,
        owner_id=scope.owner_id,
        workspace_id=scope.workspace_id,
        document_id=document.id,
    )
    pointer_version = pointer.version if pointer else 0
    current_edition_id = pointer.current_edition_id if pointer else None
    editions = store.find_all(
        NarrationEdition,
        owner_id=scope.owner_id,
        workspace_id=scope.workspace_id,
        document_id=document.id,
    )
    items: list[EditionHistoryItem] = []
    for edition in editions:
        if edition.novel_id != document.novel_id:
            raise NarrationScopeMismatch("Edition history crosses novel scope")
        require_sha256(edition.edition_fingerprint, field="edition_fingerprint")
        request = require_row(
            store.get(NarrationRequest, edition.request_id), label="narration request"
        )
        if (
            request.owner_id != scope.owner_id
            or request.workspace_id != scope.workspace_id
            or request.novel_id != edition.novel_id
            or request.document_id != document.id
            or request.intent not in {"create", "update"}
        ):
            raise NarrationScopeMismatch("Edition history request provenance is invalid")
        version = require_row(
            store.get(NarrationScriptVersion, edition.script_version_id),
            label="script version",
        )
        script = require_row(store.get(NarrationScript, version.script_id), label="script")
        if script.document_id != document.id or script.novel_id != document.novel_id:
            raise NarrationScopeMismatch("Edition history script provenance is invalid")
        require_sha256(script.content_hash, field="script content_hash")
        rows = _edition_segments(store, edition)
        rights_available = True
        try:
            for voice_version_id in sorted({row.voice_version_id for row in rows}, key=str):
                require_usable_voice(
                    store, voice_version_id, novel_id=edition.novel_id
                )
        except VoiceRightsUnavailable:
            rights_available = False
        manifest, manifest_playable, ready_count, default_ready = _history_manifest(
            store, edition
        )
        resume_available = False
        if profile_id is not None and manifest is not None:
            progress = store.find_one(
                NarrationPlaybackProgress,
                owner_id=scope.owner_id,
                workspace_id=scope.workspace_id,
                profile_id=profile_id,
                edition_id=edition.id,
            )
            if progress is not None:
                try:
                    resume_available = (
                        restore_playback_progress(
                            store,
                            profile_id=profile_id,
                            edition_id=edition.id,
                            scope=scope,
                        )
                        is not None
                    )
                except InvalidNarrationState:
                    resume_available = False
        is_current = edition.id == current_edition_id
        source_status: Literal["current", "working_copy_diverged", "superseded"]
        if not is_current:
            source_status = "superseded"
        elif script.content_hash == working.content_hash:
            source_status = "current"
        else:
            source_status = "working_copy_diverged"
        playable = (
            rights_available
            and manifest_playable
            and edition.state in {"partial_ready", "ready"}
        )
        items.append(
            EditionHistoryItem(
                edition_id=edition.id,
                request_id=edition.request_id,
                source_revision_id=script.revision_id,
                source_content_hash=script.content_hash,
                edition_fingerprint=edition.edition_fingerprint,
                state=edition.state,
                created_at=edition.created_at,
                manifest_revision=(manifest.manifest_revision if manifest else None),
                manifest_etag=(f'"{manifest.etag_sha256}"' if manifest else None),
                ready_segment_count=ready_count,
                total_segment_count=len(rows),
                is_current=is_current,
                source_status=source_status,
                rights_available=rights_available,
                playable=playable,
                default_start_ready=default_ready,
                resume_available=resume_available,
                switch_allowed=playable and (default_ready or resume_available),
            )
        )
    items.sort(
        key=lambda item: (
            item.created_at or datetime.min.replace(tzinfo=UTC),
            str(item.edition_id),
        ),
        reverse=True,
    )
    if current_edition_id is not None and not any(
        item.edition_id == current_edition_id for item in items
    ):
        raise NarrationScopeMismatch("document narration pointer names an unknown Edition")
    return DocumentEditionHistoryProjection(
        contract_version=EDITION_HISTORY_CONTRACT_VERSION,
        document_id=document.id,
        pointer_version=pointer_version,
        current_edition_id=current_edition_id,
        working_copy_content_hash=working.content_hash,
        working_copy_draft_version=working.draft_version,
        editions=tuple(items),
    )


__all__ = [
    "CacheOnlyFinalizationResult",
    "DocumentEditionHistoryProjection",
    "EDITION_HISTORY_CONTRACT_VERSION",
    "EditionHistoryItem",
    "EditionRegenerationProjection",
    "FailedSegmentRetryEligibility",
    "REGENERATION_CONTRACT_VERSION",
    "SegmentRegenerationProjection",
    "finalize_ready_cache_only_edition",
    "project_document_edition_history",
    "project_failed_segment_retry_eligibility",
    "project_local_regeneration",
]
