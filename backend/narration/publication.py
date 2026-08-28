"""Atomic database publication of one completed segment render.

Audio generation, transcoding, and filesystem publication happen before the
caller opens this short transaction.  Asset IDs are deterministic per render,
so a crash after the atomic file rename but before the database commit can
re-adopt the same immutable files on retry.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    MediaAsset,
    ModelRunRecord,
    NarrationRenderAsset,
    NarrationSegmentRender,
)

from .jobs import PublicationFenceContext
from .media import apply_ready_evidence_in_session
from .renders import publish_render_ready
from .services import (
    InvalidNarrationState,
    NarrationScopeMismatch,
    SqlAlchemyNarrationStore,
    require_exact_int,
    require_nonempty,
    require_sha256,
)
from .storage import NarrationStorage, PublishedFile


_RENDER_ASSET_ROLES = frozenset({"master", "playback"})


def render_asset_id(render_id: UUID, role: str) -> UUID:
    """Return the stable logical asset ID for one render output role."""

    if type(render_id) is not UUID or role not in _RENDER_ASSET_ROLES:
        raise InvalidNarrationState("render asset identity requires a supported role")
    return uuid5(render_id, f"ai-novel-world-2026:narration-render:{role}:v1")


@dataclass(frozen=True, slots=True)
class RenderAudioEvidence:
    master: PublishedFile
    playback: PublishedFile
    duration_ms: int
    sample_rate: int
    channels: int
    master_mime_type: str = "audio/wav"
    playback_mime_type: str = "audio/ogg"


@dataclass(frozen=True, slots=True)
class ModelRunSuccessEvidence:
    requested_model_id: str
    actual_model_id: str
    model_fingerprint: str
    parameters_digest: str
    input_digest_key_id: str
    input_digest: str
    duration_ms: int
    requested_provider_id: str | None = None
    requested_revision: str | None = None
    actual_provider_id: str | None = None
    actual_revision: str | None = None
    provider_request_id: str | None = None


def _validate_audio_evidence(
    render: NarrationSegmentRender, evidence: RenderAudioEvidence
) -> None:
    require_exact_int(evidence.duration_ms, field="render duration_ms", minimum=1)
    require_exact_int(evidence.sample_rate, field="render sample_rate", minimum=1)
    require_exact_int(evidence.channels, field="render channels", minimum=1)
    for role, published in (
        ("master", evidence.master),
        ("playback", evidence.playback),
    ):
        if type(published) is not PublishedFile:
            raise InvalidNarrationState(f"{role} publication evidence has an invalid type")
        if published.asset_id != render_asset_id(render.id, role):
            raise InvalidNarrationState(
                f"{role} publication does not use the deterministic render asset ID"
            )
        require_sha256(published.actual_sha256, field=f"{role} actual_sha256")
        require_exact_int(published.byte_size, field=f"{role} byte_size", minimum=1)


def _validate_model_evidence(
    render: NarrationSegmentRender,
    context: PublicationFenceContext,
    evidence: ModelRunSuccessEvidence,
) -> None:
    if type(context) is not PublicationFenceContext:
        raise InvalidNarrationState("render publication requires a combined fence context")
    if context.job_lease.fence.job_id != render.source_job_id:
        raise NarrationScopeMismatch("model evidence belongs to another render job")
    require_nonempty(evidence.requested_model_id, field="requested_model_id")
    require_nonempty(evidence.actual_model_id, field="actual_model_id")
    require_nonempty(evidence.input_digest_key_id, field="input_digest_key_id")
    require_sha256(evidence.model_fingerprint, field="model_fingerprint")
    require_sha256(evidence.parameters_digest, field="parameters_digest")
    require_sha256(evidence.input_digest, field="input_digest")
    require_exact_int(evidence.duration_ms, field="model duration_ms", minimum=0)
    if evidence.model_fingerprint != render.model_fingerprint:
        raise NarrationScopeMismatch("actual model fingerprint differs from the render input")


def publish_render_result_in_session(
    session: Session,
    storage: NarrationStorage,
    *,
    render_id: UUID,
    publication_context: PublicationFenceContext,
    audio: RenderAudioEvidence,
    model: ModelRunSuccessEvidence,
) -> NarrationSegmentRender:
    """Publish model run, media, links, render, and attempt in one transaction.

    The caller owns commit/rollback.  No network, synthesis, transcoding, or
    filesystem write is performed here; both ``PublishedFile`` values must have
    been atomically published and verified by ``NarrationStorage`` first.
    """

    render = session.scalar(
        select(NarrationSegmentRender)
        .where(NarrationSegmentRender.id == render_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if render is None:
        raise InvalidNarrationState("render publication target does not exist")
    if render.state not in {"pending", "rendering"}:
        raise InvalidNarrationState("only an in-flight render can publish a result")
    _validate_audio_evidence(render, audio)
    _validate_model_evidence(render, publication_context, model)
    if model.duration_ms != audio.duration_ms:
        raise InvalidNarrationState("model and audio duration evidence differ")

    existing_model_run = session.scalar(
        select(ModelRunRecord).where(
            ModelRunRecord.attempt_id == publication_context.job_lease.fence.attempt_id
        )
    )
    if existing_model_run is not None:
        raise InvalidNarrationState("the active attempt already has model-run evidence")
    session.add(
        ModelRunRecord(
            attempt_id=publication_context.job_lease.fence.attempt_id,
            requested_provider_id=model.requested_provider_id,
            requested_model_id=model.requested_model_id,
            requested_revision=model.requested_revision,
            actual_provider_id=model.actual_provider_id,
            actual_model_id=model.actual_model_id,
            actual_revision=model.actual_revision,
            model_fingerprint=model.model_fingerprint,
            parameters_digest=model.parameters_digest,
            input_digest_key_id=model.input_digest_key_id,
            input_digest=model.input_digest,
            output_digest=audio.playback.actual_sha256,
            duration_ms=model.duration_ms,
            provider_request_id=model.provider_request_id,
            result_classification="success",
        )
    )
    session.flush()

    for role, published, mime_type in (
        ("master", audio.master, audio.master_mime_type),
        ("playback", audio.playback, audio.playback_mime_type),
    ):
        if session.get(MediaAsset, published.asset_id) is not None:
            raise InvalidNarrationState(f"{role} logical media asset already exists")
        asset = MediaAsset(
            id=published.asset_id,
            owner_id=render.owner_id,
            workspace_id=render.workspace_id,
            novel_id=render.novel_id,
            kind=f"narration_segment_{role}",
            asset_class=f"segment_{role}",
            mime_type=mime_type,
            byte_size=published.byte_size,
            duration_ms=audio.duration_ms,
            sample_rate=audio.sample_rate,
            channels=audio.channels,
            storage_backend="local",
            state="staging",
            retention_policy="narration",
            checksum_algorithm="sha256",
            validation_json={},
            gc_generation=0,
            storage_path=published.relative_path,
            content_hash=published.actual_sha256,
            metadata_json={
                "render_id": str(render.id),
                "role": role,
                "publication_schema": "narration-render-publication/1",
            },
        )
        session.add(asset)
        session.flush([asset])
        apply_ready_evidence_in_session(
            session,
            storage,
            asset_id=asset.id,
            published=published,
            mime_type=mime_type,
            validation={
                "render_id": str(render.id),
                "role": role,
                "model_fingerprint": model.model_fingerprint,
            },
            structured_parent_state="ready_in_same_transaction",
        )
        session.add(
            NarrationRenderAsset(
                render_id=render.id,
                asset_id=asset.id,
                role=role,
                actual_sha256=published.actual_sha256,
            )
        )
        session.flush()

    return publish_render_ready(
        SqlAlchemyNarrationStore(session),
        render.id,
        publication_context=publication_context,
    )


__all__ = [
    "ModelRunSuccessEvidence",
    "RenderAudioEvidence",
    "publish_render_result_in_session",
    "render_asset_id",
]
