"""Fail-closed narration media publication, reads, reachability, and GC.

Filesystem work runs outside database transactions except bounded metadata
opens. Reference insertion and GC transitions serialize on the same media row
through T1-E database triggers. Helpers ending in ``_in_session`` are the
production contract; pure policy functions support deterministic tests.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from typing import Iterable, Iterator, Mapping
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    ActiveJobAsset,
    AssetTombstone,
    BackgroundJob,
    MediaAsset,
    MediaGcDeletionRecord,
    NarrationExport,
    NarrationManifestSegment,
    NarrationRenderAsset,
    Novel,
    VoiceProfileVersion,
)
from .storage import (
    NarrationStorage,
    PublishedFile,
    StorageError,
    StoredFileIdentity,
    UnsafeStoragePath,
)


SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
FIXED_OWNER_ID = UUID("29cf94d9-a5c9-54ec-912c-5dfff8738c4c")
FIXED_WORKSPACE_ID = UUID("f0e2e632-bc99-52d2-9916-bb906aa4da6e")
DERIVABLE_CLASSES = frozenset({"preview", "segment_master", "segment_playback", "export"})
NEVER_ORDINARY_GC_CLASSES = frozenset({"source", "voice_reference"})
NEVER_ORDINARY_GC_RETENTION = frozenset(
    {"source", "cover", "uploaded_original", "locked_voice", "legal_hold", "keep"}
)
ACTIVE_JOB_STATES = frozenset({"queued", "running", "retry_wait", "cancel_requested"})
ACTIVE_JOB_ASSET_ROLES = frozenset({"input", "working", "output", "checkpoint"})
MAX_ROOT_SNAPSHOT_ASSETS = 1_000
ALLOWED_MEDIA_TYPES = {
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".wav": "audio/wav",
}
SERVABLE_ASSET_CLASSES = frozenset(
    {"source", "voice_reference", "preview", "segment_master", "segment_playback", "export"}
)


class MediaPolicyError(RuntimeError):
    pass


class MediaConflict(MediaPolicyError):
    pass


class MediaNotEligible(MediaPolicyError):
    pass


@dataclass(frozen=True, slots=True)
class ByteRange:
    start: int
    end_inclusive: int

    @property
    def length(self) -> int:
        return self.end_inclusive - self.start + 1


@dataclass(frozen=True, slots=True)
class MediaReadDecision:
    status: int
    headers: Mapping[str, str]
    byte_range: ByteRange | None
    send_body: bool
    relative_path: str
    device: int
    inode: int
    byte_size: int


def strong_etag(actual_sha256: str) -> str:
    if not SHA256_RE.fullmatch(actual_sha256):
        raise MediaPolicyError("ETag requires actual lowercase SHA-256 bytes")
    return f'"{actual_sha256}"'


def _if_none_match_matches(value: str, etag: str) -> bool:
    return any(
        candidate.strip() in {"*", etag, f"W/{etag}"}
        for candidate in value.split(",")
    )


def parse_single_range(value: str, size: int) -> ByteRange:
    if size < 0:
        raise MediaPolicyError("negative media size")
    if not value.startswith("bytes=") or "," in value:
        raise MediaPolicyError("only one bytes range is supported")
    spec = value[6:].strip()
    if spec.count("-") != 1:
        raise MediaPolicyError("malformed bytes range")
    first, last = (part.strip() for part in spec.split("-", 1))
    if not first and not last:
        raise MediaPolicyError("empty bytes range")
    if size == 0:
        raise MediaPolicyError("empty media has no satisfiable range")
    try:
        if not first:
            suffix = int(last)
            if suffix <= 0:
                raise MediaPolicyError("suffix range must be positive")
            return ByteRange(max(0, size - suffix), size - 1)
        start = int(first)
        if start < 0 or start >= size:
            raise MediaPolicyError("range start is unsatisfiable")
        if not last:
            return ByteRange(start, size - 1)
        end = int(last)
        if end < start:
            raise MediaPolicyError("range end precedes start")
        return ByteRange(start, min(end, size - 1))
    except ValueError as error:
        raise MediaPolicyError("non-numeric bytes range") from error


def _canonical_media_suffix(
    relative_path: str, content_hash: str, asset_id: UUID
) -> str:
    if not SHA256_RE.fullmatch(content_hash):
        raise MediaNotEligible("media lacks actual lowercase SHA-256 evidence")
    suffix = PurePosixPath(relative_path).suffix.lower()
    if suffix not in ALLOWED_MEDIA_TYPES:
        raise MediaNotEligible("media extension is outside the frozen allowlist")
    asset_key = asset_id.hex
    expected_path = (
        f"assets/{asset_key[:2]}/{asset_key}/{content_hash}{suffix}"
    )
    if relative_path != expected_path:
        raise MediaNotEligible("media path is not the canonical asset-scoped path")
    return suffix


def _validate_ready_asset_for_read(
    storage: NarrationStorage, asset: MediaAsset
) -> tuple[str, int, int, int]:
    if asset.owner_id != FIXED_OWNER_ID or asset.workspace_id != FIXED_WORKSPACE_ID:
        raise MediaNotEligible("media is outside the fixed local scope")
    if asset.state != "ready" or asset.storage_backend != "local":
        raise MediaNotEligible("only ready local media can be served")
    if asset.asset_class not in SERVABLE_ASSET_CLASSES:
        raise MediaNotEligible("media class is outside the narration serving contract")
    if asset.checksum_algorithm != "sha256":
        raise MediaNotEligible("media checksum algorithm is not SHA-256")
    if asset.byte_size is None or asset.mime_type is None or asset.verified_at is None:
        raise MediaNotEligible("ready media is missing byte/MIME/verification evidence")
    suffix = _canonical_media_suffix(asset.storage_path, asset.content_hash, asset.id)
    if ALLOWED_MEDIA_TYPES[suffix] != asset.mime_type:
        raise MediaNotEligible("media MIME and extension are outside the frozen allowlist")
    try:
        identity = storage.verify_media_identity(
            asset.storage_path,
            expected_sha256=asset.content_hash,
            expected_size=asset.byte_size,
            max_bytes=asset.byte_size,
        )
    except (FileNotFoundError, StorageError, UnsafeStoragePath) as error:
        raise MediaNotEligible("ready media bytes are unavailable or unsafe") from error
    return suffix, identity.device, identity.inode, identity.byte_size


def _cache_control(asset_class: str | None) -> str:
    if asset_class in {"source", "voice_reference"}:
        return "private, no-store"
    if asset_class == "preview":
        return "private, max-age=60, must-revalidate"
    return "private, max-age=31536000, immutable"


def plan_media_read(
    storage: NarrationStorage,
    asset: MediaAsset,
    *,
    method: str,
    range_header: str | None = None,
    if_range: str | None = None,
    if_none_match: str | None = None,
) -> MediaReadDecision:
    """Plan GET/HEAD only after validating DB state and physical bytes.

    Validation also precedes HEAD and a prospective 304, so a stale DB row can
    never make missing bytes appear cache-valid.
    """

    method = method.upper()
    if method not in {"GET", "HEAD"}:
        raise MediaPolicyError("media planner only supports GET and HEAD")
    suffix, device, inode, byte_size = _validate_ready_asset_for_read(storage, asset)
    etag = strong_etag(asset.content_hash)
    disposition = "attachment" if asset.asset_class == "export" else "inline"
    base = {
        "Accept-Ranges": "bytes",
        "Cache-Control": _cache_control(asset.asset_class),
        "Content-Disposition": f'{disposition}; filename="asset-{asset.id}{suffix}"',
        "Content-Type": asset.mime_type or "application/octet-stream",
        "ETag": etag,
        "X-Content-Type-Options": "nosniff",
    }

    def make_decision(
        status: int,
        headers: Mapping[str, str],
        selected: ByteRange | None,
        send_body: bool,
    ) -> MediaReadDecision:
        return MediaReadDecision(
            status=status,
            headers=headers,
            byte_range=selected,
            send_body=send_body,
            relative_path=asset.storage_path,
            device=device,
            inode=inode,
            byte_size=byte_size,
        )

    if if_none_match and _if_none_match_matches(if_none_match, etag):
        return make_decision(304, base, None, False)
    selected: ByteRange | None = None
    if range_header and (if_range is None or if_range == etag):
        try:
            selected = parse_single_range(range_header, byte_size)
        except MediaPolicyError:
            return make_decision(
                416,
                {**base, "Content-Range": f"bytes */{byte_size}", "Content-Length": "0"},
                None,
                False,
            )
    if selected is not None:
        return make_decision(
            206,
            {
                **base,
                "Content-Range": f"bytes {selected.start}-{selected.end_inclusive}/{byte_size}",
                "Content-Length": str(selected.length),
            },
            selected,
            method == "GET",
        )
    return make_decision(
        200, {**base, "Content-Length": str(byte_size)}, None, method == "GET"
    )


def plan_media_read_in_session(
    session: Session,
    storage: NarrationStorage,
    *,
    asset_id: UUID,
    method: str,
    range_header: str | None = None,
    if_range: str | None = None,
    if_none_match: str | None = None,
) -> MediaReadDecision:
    """Refresh and share-lock the DB row while producing an HTTP plan."""

    asset = session.scalar(
        select(MediaAsset)
        .where(MediaAsset.id == asset_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if asset is None:
        raise MediaNotEligible("media asset does not exist")
    return plan_media_read(
        storage,
        asset,
        method=method,
        range_header=range_header,
        if_range=if_range,
        if_none_match=if_none_match,
    )


def stream_read_decision(
    storage: NarrationStorage,
    decision: MediaReadDecision,
    *,
    chunk_size: int = 64 * 1024,
) -> Iterator[bytes]:
    if not decision.send_body:
        return iter(())
    selected = decision.byte_range
    return storage.stream_media(
        decision.relative_path,
        start=selected.start if selected else 0,
        end_exclusive=(selected.end_inclusive + 1) if selected else None,
        chunk_size=chunk_size,
        expected_device=decision.device,
        expected_inode=decision.inode,
        expected_size=decision.byte_size,
    )


def _mime_matches_path(relative_path: str, mime_type: str) -> bool:
    suffix = PurePosixPath(relative_path).suffix.lower()
    return suffix in ALLOWED_MEDIA_TYPES and ALLOWED_MEDIA_TYPES[suffix] == mime_type


def apply_ready_evidence(
    asset: MediaAsset,
    published: PublishedFile,
    *,
    mime_type: str,
    now: datetime,
    validation: Mapping[str, object] | None = None,
    structured_parent_state: str | None = None,
) -> None:
    """Apply already-published byte evidence in the short publication tx."""

    if asset.state != "staging":
        raise MediaConflict("only a staging asset can become ready")
    if asset.asset_class is None or asset.novel_id is None:
        raise MediaConflict("TTS media needs explicit class and novel scope")
    if asset.owner_id != FIXED_OWNER_ID or asset.workspace_id != FIXED_WORKSPACE_ID:
        raise MediaConflict("media is outside the fixed local narration scope")
    if asset.id != published.asset_id:
        raise MediaConflict("published bytes belong to another logical media asset")
    if asset.asset_class in {"segment_master", "segment_playback", "export"}:
        if structured_parent_state not in {"ready", "ready_in_same_transaction"}:
            raise MediaConflict("generated media requires a ready parent in the publication tx")
    if asset.content_hash != published.actual_sha256:
        raise MediaConflict("reserved asset hash differs from actual bytes")
    if asset.storage_path != published.relative_path:
        raise MediaConflict("reserved asset path differs from published bytes")
    if asset.byte_size is not None and asset.byte_size != published.byte_size:
        raise MediaConflict("reserved asset size differs from actual bytes")
    if not _mime_matches_path(published.relative_path, mime_type):
        raise MediaConflict("published MIME and extension are outside the allowlist")
    asset.byte_size = published.byte_size
    asset.mime_type = mime_type
    asset.checksum_algorithm = "sha256"
    asset.validation_json = {
        **dict(validation or {}),
        "filesystem_device": published.device,
        "filesystem_inode": published.inode,
        "immutable_mode": "0440",
    }
    asset.verified_at = now
    asset.state = "ready"


def apply_ready_evidence_in_session(
    session: Session,
    storage: NarrationStorage,
    *,
    asset_id: UUID,
    published: PublishedFile,
    mime_type: str,
    validation: Mapping[str, object] | None = None,
    structured_parent_state: str | None = None,
) -> MediaAsset:
    """Re-verify caller evidence and publish exactly one reserved DB owner."""

    asset = _locked_asset(session, asset_id)
    owners = session.scalars(
        select(MediaAsset)
        .where(
            MediaAsset.storage_backend == asset.storage_backend,
            MediaAsset.storage_path == asset.storage_path,
        )
        .order_by(MediaAsset.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    if len(owners) != 1 or owners[0].id != asset.id:
        raise MediaConflict("published blob must have exactly one reserved DB owner")
    try:
        identity = storage.verify_media_identity(
            asset.storage_path,
            expected_sha256=asset.content_hash,
            expected_size=published.byte_size,
            max_bytes=published.byte_size,
        )
    except (FileNotFoundError, StorageError) as error:
        raise MediaConflict("published byte evidence cannot be reproduced") from error
    if (
        published.asset_id,
        published.relative_path,
        published.actual_sha256,
        published.byte_size,
        published.device,
        published.inode,
    ) != (
        asset.id,
        asset.storage_path,
        asset.content_hash,
        identity.byte_size,
        identity.device,
        identity.inode,
    ):
        raise MediaConflict("caller publication evidence differs from verified inode")
    verified = PublishedFile(
        asset_id=asset.id,
        relative_path=asset.storage_path,
        actual_sha256=asset.content_hash,
        byte_size=identity.byte_size,
        strong_etag=strong_etag(asset.content_hash),
        device=identity.device,
        inode=identity.inode,
    )
    apply_ready_evidence(
        asset,
        verified,
        mime_type=mime_type,
        now=_db_clock(session),
        validation=validation,
        structured_parent_state=structured_parent_state,
    )
    session.flush([asset])
    return asset


@dataclass(frozen=True, slots=True)
class ReferenceRoots:
    novel_cover: frozenset[UUID] = field(default_factory=frozenset)
    render_assets: frozenset[UUID] = field(default_factory=frozenset)
    export_assets: frozenset[UUID] = field(default_factory=frozenset)
    voice_references: frozenset[UUID] = field(default_factory=frozenset)
    locked_voice_assets: frozenset[UUID] = field(default_factory=frozenset)
    manifest_assets: frozenset[UUID] = field(default_factory=frozenset)
    active_job_assets: frozenset[UUID] = field(default_factory=frozenset)
    uploaded_originals: frozenset[UUID] = field(default_factory=frozenset)

    @property
    def all(self) -> frozenset[UUID]:
        return frozenset().union(
            self.novel_cover,
            self.render_assets,
            self.export_assets,
            self.voice_references,
            self.locked_voice_assets,
            self.manifest_assets,
            self.active_job_assets,
            self.uploaded_originals,
        )

    def categories_for(self, asset_id: UUID) -> tuple[str, ...]:
        return tuple(
            name
            for name in (
                "novel_cover",
                "render_assets",
                "export_assets",
                "voice_references",
                "locked_voice_assets",
                "manifest_assets",
                "active_job_assets",
                "uploaded_originals",
            )
            if asset_id in getattr(self, name)
        )


def _bounded_asset_ids(asset_ids: Iterable[UUID]) -> tuple[UUID, ...]:
    unique: dict[UUID, None] = {}
    for index, value in enumerate(asset_ids, start=1):
        if index > MAX_ROOT_SNAPSHOT_ASSETS:
            raise MediaPolicyError("DB root snapshot requires 1..1000 explicit asset IDs")
        if not isinstance(value, UUID):
            raise MediaPolicyError("DB root snapshot accepts UUID asset IDs only")
        unique.setdefault(value, None)
    if not unique:
        raise MediaPolicyError("DB root snapshot requires 1..1000 explicit asset IDs")
    return tuple(unique)


def _uuid_set(session: Session, statement: object) -> frozenset[UUID]:
    return frozenset(value for value in session.scalars(statement) if value is not None)


def load_reference_roots_in_session(
    session: Session, *, asset_ids: Iterable[UUID]
) -> ReferenceRoots:
    """Build roots only from structured DB associations, never caller JSON."""

    ids = _bounded_asset_ids(asset_ids)
    covers = _uuid_set(session, select(Novel.cover_asset_id).where(Novel.cover_asset_id.in_(ids)))
    renders = _uuid_set(
        session, select(NarrationRenderAsset.asset_id).where(NarrationRenderAsset.asset_id.in_(ids))
    )
    exports = _uuid_set(
        session, select(NarrationExport.asset_id).where(NarrationExport.asset_id.in_(ids))
    )
    voice_references = _uuid_set(
        session,
        select(VoiceProfileVersion.reference_asset_id).where(
            VoiceProfileVersion.reference_asset_id.in_(ids)
        ),
    ) | _uuid_set(
        session,
        select(VoiceProfileVersion.preview_asset_id).where(
            VoiceProfileVersion.preview_asset_id.in_(ids)
        ),
    )
    locked = _uuid_set(
        session,
        select(VoiceProfileVersion.reference_asset_id).where(
            VoiceProfileVersion.state == "locked",
            VoiceProfileVersion.reference_asset_id.in_(ids),
        ),
    ) | _uuid_set(
        session,
        select(VoiceProfileVersion.preview_asset_id).where(
            VoiceProfileVersion.state == "locked",
            VoiceProfileVersion.preview_asset_id.in_(ids),
        ),
    )
    manifests = _uuid_set(
        session,
        select(NarrationRenderAsset.asset_id)
        .join(
            NarrationManifestSegment,
            NarrationManifestSegment.render_id == NarrationRenderAsset.render_id,
        )
        .where(NarrationRenderAsset.asset_id.in_(ids)),
    )
    active_jobs = _uuid_set(
        session,
        select(ActiveJobAsset.asset_id).where(
            ActiveJobAsset.asset_id.in_(ids), ActiveJobAsset.released_at.is_(None)
        ),
    )
    uploaded = _uuid_set(
        session,
        select(VoiceProfileVersion.reference_asset_id).where(
            VoiceProfileVersion.source_type == "uploaded",
            VoiceProfileVersion.reference_asset_id.in_(ids),
        ),
    )
    return ReferenceRoots(
        novel_cover=covers,
        render_assets=renders,
        export_assets=exports,
        voice_references=voice_references,
        locked_voice_assets=locked,
        manifest_assets=manifests,
        active_job_assets=active_jobs,
        uploaded_originals=uploaded,
    )


def _db_clock(session: Session) -> datetime:
    value = session.scalar(select(func.clock_timestamp()))
    if not isinstance(value, datetime):
        raise MediaConflict("database did not return clock_timestamp()")
    return value


def _locked_asset(session: Session, asset_id: UUID) -> MediaAsset:
    asset = session.scalar(
        select(MediaAsset)
        .where(MediaAsset.id == asset_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if asset is None:
        raise MediaConflict("media asset does not exist")
    return asset


def attach_active_job_asset_in_session(
    session: Session, *, job_id: UUID, asset_id: UUID, role: str
) -> ActiveJobAsset:
    if role not in ACTIVE_JOB_ASSET_ROLES:
        raise MediaPolicyError("invalid active job asset role")
    job = session.scalar(
        select(BackgroundJob)
        .where(BackgroundJob.id == job_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if job is None or job.state not in ACTIVE_JOB_STATES or job.novel_id is None:
        raise MediaConflict("active media requires a non-terminal novel-scoped job")
    asset = _locked_asset(session, asset_id)
    if asset.state != "ready" or (
        asset.owner_id,
        asset.workspace_id,
        asset.novel_id,
    ) != (job.owner_id, job.workspace_id, job.novel_id):
        raise MediaConflict("active job asset is unavailable or outside job scope")
    existing = session.scalar(
        select(ActiveJobAsset)
        .where(ActiveJobAsset.job_id == job_id, ActiveJobAsset.asset_id == asset_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if existing is not None:
        if existing.released_at is not None or existing.role != role:
            raise MediaConflict("active job asset association cannot be reused or retyped")
        return existing
    row = ActiveJobAsset(
        job_id=job.id,
        asset_id=asset.id,
        owner_id=job.owner_id,
        workspace_id=job.workspace_id,
        novel_id=job.novel_id,
        role=role,
        acquired_at=_db_clock(session),
        released_at=None,
    )
    session.add(row)
    session.flush([row])
    return row


def release_active_job_assets_in_session(session: Session, *, job_id: UUID) -> int:
    job = session.scalar(select(BackgroundJob).where(BackgroundJob.id == job_id).with_for_update())
    if job is None:
        raise MediaConflict("background job does not exist")
    rows = session.scalars(
        select(ActiveJobAsset)
        .where(ActiveJobAsset.job_id == job_id, ActiveJobAsset.released_at.is_(None))
        .order_by(ActiveJobAsset.asset_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    released_at = _db_clock(session)
    for row in rows:
        row.released_at = released_at
    session.flush(rows)
    return len(rows)


@dataclass(frozen=True, slots=True)
class GcPolicy:
    staging_grace: timedelta = timedelta(hours=24)
    ready_mark_grace: timedelta = timedelta(days=7)


@dataclass(frozen=True, slots=True)
class GcDecision:
    eligible: bool
    action: str
    reason: str


@dataclass(frozen=True, slots=True)
class GcDeletionPlan:
    asset_id: UUID
    owner_id: UUID
    workspace_id: UUID
    novel_id: UUID
    storage_backend: str
    relative_path: str
    content_hash: str
    byte_size: int
    generation: int
    reason_code: str
    file_present: bool
    device: int | None
    inode: int | None
    created_at: datetime

    def canonical_identity(self) -> dict[str, object]:
        return {
            "asset_id": str(self.asset_id),
            "byte_size": self.byte_size,
            "content_hash": self.content_hash,
            "created_at": self.created_at.isoformat(),
            "device": self.device,
            "file_present": self.file_present,
            "generation": self.generation,
            "inode": self.inode,
            "novel_id": str(self.novel_id),
            "owner_id": str(self.owner_id),
            "reason_code": self.reason_code,
            "storage_backend": self.storage_backend,
            "storage_path": self.relative_path,
            "workspace_id": str(self.workspace_id),
        }


@dataclass(frozen=True, slots=True)
class GcDeleteResult:
    plan: GcDeletionPlan
    removed: bool
    verified_absent: bool


@dataclass(frozen=True, slots=True)
class QuotaCandidate:
    asset_id: UUID
    byte_size: int
    action: str
    reason: str


def evaluate_gc(
    asset: MediaAsset,
    roots: ReferenceRoots,
    *,
    now: datetime,
    policy: GcPolicy = GcPolicy(),
) -> GcDecision:
    if asset.id in roots.all:
        return GcDecision(
            False,
            "retain",
            "structured_reference:" + ",".join(roots.categories_for(asset.id)),
        )
    if asset.asset_class in NEVER_ORDINARY_GC_CLASSES:
        return GcDecision(False, "retain", f"protected_class:{asset.asset_class}")
    if asset.retention_policy in NEVER_ORDINARY_GC_RETENTION:
        return GcDecision(False, "retain", f"protected_retention:{asset.retention_policy}")
    if asset.expires_at is not None and now < asset.expires_at:
        return GcDecision(False, "wait", "retention_not_expired")
    if asset.state == "staging":
        if asset.created_at is None or now - asset.created_at < policy.staging_grace:
            return GcDecision(False, "wait", "staging_grace")
        return GcDecision(True, "delete", "staging_orphan")
    if asset.state == "ready":
        if asset.asset_class not in DERIVABLE_CLASSES:
            return GcDecision(False, "retain", "non_derivable_ready_asset")
        if asset.gc_marked_at is None:
            return GcDecision(False, "mark", "unreferenced_derivative")
        if now - asset.gc_marked_at < policy.ready_mark_grace:
            return GcDecision(False, "wait", "ready_mark_grace")
        return GcDecision(True, "delete", "unreferenced_derivative_after_grace")
    if asset.state == "deleting":
        return GcDecision(True, "resume_delete", "recover_interrupted_delete")
    return GcDecision(False, "retain", f"state:{asset.state}")


def select_quota_candidates(
    assets: Iterable[MediaAsset],
    roots: ReferenceRoots,
    *,
    now: datetime,
    limit: int,
    policy: GcPolicy = GcPolicy(),
) -> tuple[QuotaCandidate, ...]:
    if limit < 0:
        raise MediaPolicyError("quota candidate limit cannot be negative")
    ranked: list[tuple[datetime, datetime, str, QuotaCandidate]] = []
    far_future = datetime.max.replace(tzinfo=timezone.utc)
    for asset in assets:
        gc_decision = evaluate_gc(asset, roots, now=now, policy=policy)
        if gc_decision.action not in {"mark", "delete", "resume_delete"}:
            continue
        candidate = QuotaCandidate(
            asset_id=asset.id,
            byte_size=asset.byte_size or 0,
            action=gc_decision.action,
            reason=gc_decision.reason,
        )
        ranked.append(
            (
                asset.last_accessed_at or asset.created_at or far_future,
                asset.created_at or far_future,
                str(asset.id),
                candidate,
            )
        )
    ranked.sort(key=lambda item: item[:3])
    return tuple(item[3] for item in ranked[:limit])


def mark_gc_candidate(asset: MediaAsset, roots: ReferenceRoots, *, now: datetime) -> int:
    gc_decision = evaluate_gc(asset, roots, now=now)
    if gc_decision.action != "mark":
        raise MediaNotEligible(gc_decision.reason)
    asset.gc_generation += 1
    asset.gc_marked_at = now
    return asset.gc_generation


def mark_gc_candidate_in_session(session: Session, *, asset_id: UUID) -> int:
    asset = _locked_asset(session, asset_id)
    roots = load_reference_roots_in_session(session, asset_ids=(asset.id,))
    generation = mark_gc_candidate(asset, roots, now=_db_clock(session))
    session.flush([asset])
    return generation


def _plan_from_asset(
    asset: MediaAsset,
    *,
    reason_code: str,
    identity: StoredFileIdentity | None,
    created_at: datetime,
) -> GcDeletionPlan:
    if asset.novel_id is None or asset.byte_size is None:
        raise MediaConflict("deletion requires explicit novel scope and byte size")
    if asset.storage_backend != "local" or not SHA256_RE.fullmatch(asset.content_hash):
        raise MediaConflict("deletion requires local storage and actual SHA-256")
    try:
        suffix = _canonical_media_suffix(asset.storage_path, asset.content_hash, asset.id)
    except MediaNotEligible as error:
        raise MediaConflict("deletion requires a canonical narration media path") from error
    if asset.mime_type is None or ALLOWED_MEDIA_TYPES[suffix] != asset.mime_type:
        raise MediaConflict("deletion requires canonical narration MIME evidence")
    if identity is not None and identity.byte_size != asset.byte_size:
        raise MediaConflict("physical bytes differ from frozen DB size")
    return GcDeletionPlan(
        asset_id=asset.id,
        owner_id=asset.owner_id,
        workspace_id=asset.workspace_id,
        novel_id=asset.novel_id,
        storage_backend=asset.storage_backend,
        relative_path=asset.storage_path,
        content_hash=asset.content_hash,
        byte_size=asset.byte_size,
        generation=asset.gc_generation,
        reason_code=reason_code,
        file_present=identity is not None,
        device=identity.device if identity else None,
        inode=identity.inode if identity else None,
        created_at=created_at,
    )


def begin_gc_deletion(
    asset: MediaAsset,
    roots: ReferenceRoots,
    *,
    expected_generation: int,
    now: datetime,
    storage: NarrationStorage,
    policy: GcPolicy = GcPolicy(),
) -> GcDeletionPlan:
    if asset.gc_generation != expected_generation:
        raise MediaConflict("GC generation changed")
    gc_decision = evaluate_gc(asset, roots, now=now, policy=policy)
    if not gc_decision.eligible:
        raise MediaNotEligible(gc_decision.reason)
    identity = storage.capture_media_identity(
        asset.storage_path, missing_ok=asset.state in {"staging", "deleting"}
    )
    if asset.state == "ready" and identity is None:
        raise MediaConflict("ready GC candidate has no physical bytes")
    plan = _plan_from_asset(
        asset, reason_code=gc_decision.reason, identity=identity, created_at=now
    )
    asset.state = "deleting"
    return plan


def _plan_from_record(record: MediaGcDeletionRecord) -> GcDeletionPlan:
    return GcDeletionPlan(
        asset_id=record.asset_id,
        owner_id=record.owner_id,
        workspace_id=record.workspace_id,
        novel_id=record.novel_id,
        storage_backend=record.storage_backend,
        relative_path=record.storage_path,
        content_hash=record.content_hash,
        byte_size=record.byte_size,
        generation=record.generation,
        reason_code=record.reason_code,
        file_present=record.file_present,
        device=record.device,
        inode=record.inode,
        created_at=record.created_at,
    )


def begin_gc_deletion_in_session(
    session: Session,
    storage: NarrationStorage,
    *,
    asset_id: UUID,
    expected_generation: int,
    policy: GcPolicy = GcPolicy(),
) -> GcDeletionPlan:
    asset = _locked_asset(session, asset_id)
    same_path = session.scalars(
        select(MediaAsset)
        .where(
            MediaAsset.storage_backend == asset.storage_backend,
            MediaAsset.storage_path == asset.storage_path,
        )
        .order_by(MediaAsset.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    if len(same_path) != 1 or same_path[0].id != asset.id:
        raise MediaConflict("physical blob must have exactly one DB owner")
    roots = load_reference_roots_in_session(session, asset_ids=(asset.id,))
    if asset.state == "deleting":
        record = session.get(MediaGcDeletionRecord, asset.id)
        if record is None or record.generation != expected_generation:
            raise MediaConflict("deleting media lacks its durable matching plan")
        return _plan_from_record(record)
    original_state = asset.state
    plan = begin_gc_deletion(
        asset,
        roots,
        expected_generation=expected_generation,
        now=_db_clock(session),
        storage=storage,
        policy=policy,
    )
    # Flush the durable plan while the DB row retains its eligible source state
    # (ready or stale staging); the deferred DB constraint then requires the
    # matching deleting transition at commit.
    asset.state = original_state
    record = MediaGcDeletionRecord(
        asset_id=plan.asset_id,
        owner_id=plan.owner_id,
        workspace_id=plan.workspace_id,
        novel_id=plan.novel_id,
        storage_backend=plan.storage_backend,
        storage_path=plan.relative_path,
        content_hash=plan.content_hash,
        byte_size=plan.byte_size,
        generation=plan.generation,
        file_present=plan.file_present,
        device=plan.device,
        inode=plan.inode,
        reason_code=plan.reason_code,
        created_at=plan.created_at,
    )
    session.add(record)
    session.flush([record])
    asset.state = "deleting"
    session.flush([asset])
    return plan


def execute_gc_delete(storage: NarrationStorage, plan: GcDeletionPlan) -> GcDeleteResult:
    removed = storage.delete_media_verified(
        plan.relative_path,
        expected_sha256=plan.content_hash,
        expected_size=plan.byte_size,
        expected_device=plan.device,
        expected_inode=plan.inode,
        expected_present=plan.file_present,
        missing_ok=True,
    )
    storage.ensure_media_absent(plan.relative_path)
    return GcDeleteResult(plan=plan, removed=removed, verified_absent=True)


def _asset_matches_plan(asset: MediaAsset, plan: GcDeletionPlan) -> bool:
    return (
        asset.id,
        asset.owner_id,
        asset.workspace_id,
        asset.novel_id,
        asset.storage_backend,
        asset.storage_path,
        asset.content_hash,
        asset.byte_size,
        asset.gc_generation,
    ) == (
        plan.asset_id,
        plan.owner_id,
        plan.workspace_id,
        plan.novel_id,
        plan.storage_backend,
        plan.relative_path,
        plan.content_hash,
        plan.byte_size,
        plan.generation,
    )


def finalize_gc_deletion(
    asset: MediaAsset,
    result: GcDeleteResult,
    *,
    digest_key_id: str,
    digest_key: bytes,
    deleted_actor: str,
    now: datetime,
) -> AssetTombstone:
    plan = result.plan
    if asset.state != "deleting" or not _asset_matches_plan(asset, plan):
        raise MediaConflict("asset changed while deletion ran outside the transaction")
    if not result.verified_absent:
        raise MediaConflict("GC result does not prove the path is absent")
    if not isinstance(digest_key, bytes) or len(digest_key) < 32:
        raise MediaPolicyError("tombstone HMAC key must contain at least 32 bytes")
    if not isinstance(digest_key_id, str) or not isinstance(deleted_actor, str):
        raise MediaPolicyError("tombstone key id and actor must be text")
    digest_key_id = digest_key_id.strip()
    deleted_actor = deleted_actor.strip()
    if (
        not digest_key_id
        or len(digest_key_id) > 80
        or any(ord(character) < 32 or ord(character) == 127 for character in digest_key_id)
    ):
        raise MediaPolicyError("tombstone HMAC key id is required and bounded")
    if (
        not deleted_actor
        or len(deleted_actor) > 120
        or any(ord(character) < 32 or ord(character) == 127 for character in deleted_actor)
    ):
        raise MediaPolicyError("tombstone deleted actor is required and bounded")
    canonical = json.dumps(
        plan.canonical_identity(), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    digest = hmac.new(digest_key, canonical, hashlib.sha256).hexdigest()
    asset.state = "deleted"
    asset.deleted_at = now
    return AssetTombstone(
        owner_id=asset.owner_id,
        workspace_id=asset.workspace_id,
        original_asset_id=asset.id,
        deletion_request_id=None,
        digest_key_id=digest_key_id,
        digest=digest,
        reason_code=plan.reason_code,
        deleted_actor=deleted_actor,
        deleted_at=now,
    )


def finalize_gc_deletion_in_session(
    session: Session,
    storage: NarrationStorage,
    *,
    asset_id: UUID,
    digest_key_id: str,
    digest_key: bytes,
    deleted_actor: str,
) -> AssetTombstone:
    asset = _locked_asset(session, asset_id)
    record = session.scalar(
        select(MediaGcDeletionRecord)
        .where(MediaGcDeletionRecord.asset_id == asset_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if record is None:
        raise MediaConflict("media deletion plan is missing")
    plan = _plan_from_record(record)
    roots = load_reference_roots_in_session(session, asset_ids=(asset.id,))
    if asset.id in roots.all:
        raise MediaConflict("a structured reference exists at GC finalization")
    same_path_count = session.scalar(
        select(func.count())
        .select_from(MediaAsset)
        .where(
            MediaAsset.storage_backend == plan.storage_backend,
            MediaAsset.storage_path == plan.relative_path,
        )
    )
    if same_path_count != 1:
        raise MediaConflict("physical blob ownership changed before GC finalization")
    storage.ensure_media_absent(plan.relative_path)
    tombstone = finalize_gc_deletion(
        asset,
        GcDeleteResult(plan=plan, removed=False, verified_absent=True),
        digest_key_id=digest_key_id,
        digest_key=digest_key,
        deleted_actor=deleted_actor,
        now=_db_clock(session),
    )
    session.add(tombstone)
    session.flush([asset, tombstone])
    return tombstone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


__all__ = [
    "ALLOWED_MEDIA_TYPES",
    "ByteRange",
    "GcDecision",
    "GcDeleteResult",
    "GcDeletionPlan",
    "GcPolicy",
    "MediaConflict",
    "MediaNotEligible",
    "MediaPolicyError",
    "MediaReadDecision",
    "QuotaCandidate",
    "ReferenceRoots",
    "apply_ready_evidence",
    "apply_ready_evidence_in_session",
    "attach_active_job_asset_in_session",
    "begin_gc_deletion",
    "begin_gc_deletion_in_session",
    "evaluate_gc",
    "execute_gc_delete",
    "finalize_gc_deletion",
    "finalize_gc_deletion_in_session",
    "load_reference_roots_in_session",
    "mark_gc_candidate",
    "mark_gc_candidate_in_session",
    "parse_single_range",
    "plan_media_read",
    "plan_media_read_in_session",
    "release_active_job_assets_in_session",
    "select_quota_candidates",
    "stream_read_decision",
    "strong_etag",
    "utc_now",
]
