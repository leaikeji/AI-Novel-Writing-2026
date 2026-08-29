"""Recoverable, request-scoped deletion for one private narration profile.

Voice versions, Editions and audit rows remain immutable.  Only current voice
selection is fenced and exact media bytes listed in a durable request plan are
eligible for physical deletion.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Final, Iterable
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    ActiveJobAsset,
    AnonymousSpeaker,
    BackgroundJob,
    CharacterVoiceBinding,
    GenericVoiceSlot,
    MediaAsset,
    NarrationEdition,
    NarrationEditionSegment,
    NarrationExport,
    NarrationManifestSegment,
    NarrationRenderAsset,
    NarrationSegmentRender,
    NovelNarrationSettings,
    VoiceDeletionAssetPlan,
    VoiceDeletionRequest,
    VoicePreview,
    VoiceProfile,
    VoiceProfileVersion,
    VoiceReferenceAssetLink,
)
from .digest_keyring import DigestKeyring
from .media import finalize_voice_deletion_asset_in_session
from .services import (
    IdempotencyConflict,
    InvalidNarrationState,
    NarrationCasConflict,
    NarrationNotFound,
    NarrationScopeMismatch,
)
from .storage import NarrationStorage, StoredFileIdentity


LOCAL_OWNER_ID: Final = UUID("29cf94d9-a5c9-54ec-912c-5dfff8738c4c")
LOCAL_WORKSPACE_ID: Final = UUID("f0e2e632-bc99-52d2-9916-bb906aa4da6e")
IMPACT_TTL: Final = timedelta(minutes=15)
UNREFERENCED_GRACE: Final = timedelta(seconds=30)
IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
ACTIVE_REQUEST_STATES: Final = frozenset(
    {"grace_pending", "requested", "live_deleting", "live_deleted_backup_pending", "failed"}
)
PRIVATE_SOURCE_TYPES: Final = frozenset({"uploaded", "generated"})


SessionFactory = Callable[[], Session]


class VoiceDeletionConflict(InvalidNarrationState):
    pass


class VoiceDeletionNotFound(NarrationNotFound):
    pass


@dataclass(frozen=True, slots=True)
class VoiceDeletionImpact:
    profile_id: UUID
    novel_id: UUID
    profile_version: int
    voice_version_ids: tuple[UUID, ...]
    current_narrator_count: int
    character_binding_count: int
    anonymous_speaker_count: int
    generic_slot_count: int
    edition_ids: tuple[UUID, ...]
    render_ids: tuple[UUID, ...]
    export_count: int
    asset_roles: tuple[tuple[UUID, str], ...]
    total_bytes: int
    active_job_ids: tuple[UUID, ...]

    @property
    def has_usage(self) -> bool:
        return any(
            (
                self.current_narrator_count,
                self.character_binding_count,
                self.anonymous_speaker_count,
                self.generic_slot_count,
                len(self.edition_ids),
                len(self.render_ids),
                self.export_count,
                len(self.active_job_ids),
            )
        )

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": "private-voice-deletion-impact/1",
            "profile_id": str(self.profile_id),
            "novel_id": str(self.novel_id),
            "profile_version": self.profile_version,
            "voice_version_ids": [str(value) for value in self.voice_version_ids],
            "current_narrator_count": self.current_narrator_count,
            "character_binding_count": self.character_binding_count,
            "anonymous_speaker_count": self.anonymous_speaker_count,
            "generic_slot_count": self.generic_slot_count,
            "historical_edition_count": len(self.edition_ids),
            "render_count": len(self.render_ids),
            "export_count": self.export_count,
            "asset_count": len(self.asset_roles),
            "total_bytes": self.total_bytes,
            "active_job_count": len(self.active_job_ids),
            "external_backup_status": "unmanaged",
            "historical_audio_consequence": (
                "unavailable_private_voice_deleted" if self.edition_ids else None
            ),
        }


@dataclass(frozen=True, slots=True)
class VoiceDeletionRequestSnapshot:
    request_id: UUID
    profile_id: UUID
    novel_id: UUID
    command: str
    state: str
    expected_profile_version: int
    impact_digest: str
    impact: dict[str, object]
    execute_after: datetime | None
    impact_expires_at: datetime | None
    asset_count: int
    total_bytes: int
    external_backup_status: str
    confirmed_at: datetime | None
    cancelled_at: datetime | None
    completed_at: datetime | None
    failure_code: str | None


@dataclass(frozen=True, slots=True)
class _AssetCandidate:
    asset_id: UUID
    role: str
    owner_id: UUID
    workspace_id: UUID
    novel_id: UUID
    storage_backend: str
    storage_path: str
    content_hash: str
    byte_size: int
    gc_generation: int


@dataclass(frozen=True, slots=True)
class _AssetPlanSnapshot:
    plan_id: UUID
    deletion_request_id: UUID
    asset_id: UUID
    storage_path: str
    content_hash: str
    byte_size: int
    file_present: bool
    device: int | None
    inode: int | None


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _validated_actor(actor: str) -> str:
    value = actor.strip()
    if not value or len(value) > 120:
        raise ValueError("voice deletion actor is invalid")
    return value


def _transaction(factory: SessionFactory, operation):  # type: ignore[no-untyped-def]
    with factory() as session:
        if session.in_transaction():
            raise RuntimeError("voice deletion requires a fresh session")
        with session.begin():
            return operation(session)


def _profile_and_versions(
    session: Session,
    profile_id: UUID,
    *,
    for_update: bool,
) -> tuple[VoiceProfile, tuple[VoiceProfileVersion, ...]]:
    statement = select(VoiceProfile).where(VoiceProfile.id == profile_id)
    if for_update:
        statement = statement.with_for_update()
    profile = session.scalar(statement.execution_options(populate_existing=True))
    if profile is None:
        raise VoiceDeletionNotFound("voice profile not found")
    if profile.owner_id != LOCAL_OWNER_ID or profile.workspace_id != LOCAL_WORKSPACE_ID:
        raise NarrationScopeMismatch("voice profile is outside fixed local scope")
    if profile.novel_id is None:
        raise VoiceDeletionConflict("only novel-scoped private profiles can be deleted")
    versions_statement = (
        select(VoiceProfileVersion)
        .where(VoiceProfileVersion.profile_id == profile_id)
        .order_by(VoiceProfileVersion.version_number, VoiceProfileVersion.id)
    )
    if for_update:
        versions_statement = versions_statement.with_for_update()
    versions = tuple(
        session.scalars(
            versions_statement.execution_options(populate_existing=True)
        ).all()
    )
    source_types = {row.source_type for row in versions}
    if "preset" in source_types or not source_types.issubset(PRIVATE_SOURCE_TYPES):
        raise VoiceDeletionConflict("official or mixed-source voice profiles cannot be deleted")
    return profile, versions


def _count(session: Session, model: type[object], *conditions: object) -> int:
    value = session.scalar(select(func.count()).select_from(model).where(*conditions))
    return int(value or 0)


def _asset_role_map(
    session: Session,
    *,
    versions: tuple[VoiceProfileVersion, ...],
    render_ids: tuple[UUID, ...],
    edition_ids: tuple[UUID, ...],
) -> dict[UUID, str]:
    roles: dict[UUID, str] = {}

    def remember(asset_id: UUID | None, role: str) -> None:
        if asset_id is None:
            return
        priority = {
            "reference": 5,
            "preview": 4,
            "render_master": 3,
            "render_playback": 2,
            "export": 1,
        }
        current = roles.get(asset_id)
        if current is None or priority[role] > priority[current]:
            roles[asset_id] = role

    for version in versions:
        remember(version.reference_asset_id, "reference")
        remember(version.preview_asset_id, "preview")
    version_ids = tuple(row.id for row in versions)
    if version_ids:
        for link in session.scalars(
            select(VoiceReferenceAssetLink).where(
                VoiceReferenceAssetLink.voice_version_id.in_(version_ids)
            )
        ):
            remember(link.source_asset_id, "reference")
            remember(link.reference_asset_id, "reference")
        for preview in session.scalars(
            select(VoicePreview).where(VoicePreview.version_id.in_(version_ids))
        ):
            remember(preview.reference_asset_id, "reference")
            remember(preview.result_asset_id, "preview")
    if render_ids:
        for row in session.scalars(
            select(NarrationRenderAsset).where(
                NarrationRenderAsset.render_id.in_(render_ids)
            )
        ):
            remember(row.asset_id, f"render_{row.role}")
    if edition_ids:
        for asset_id in session.scalars(
            select(NarrationExport.asset_id).where(
                NarrationExport.edition_id.in_(edition_ids)
            )
        ):
            remember(asset_id, "export")
    return roles


def compute_voice_deletion_impact(
    session: Session,
    profile_id: UUID,
    *,
    for_update: bool = False,
) -> VoiceDeletionImpact:
    profile, versions = _profile_and_versions(session, profile_id, for_update=for_update)
    version_ids = tuple(row.id for row in versions)
    if not version_ids:
        return VoiceDeletionImpact(
            profile_id=profile.id,
            novel_id=profile.novel_id,
            profile_version=profile.version,
            voice_version_ids=(),
            current_narrator_count=0,
            character_binding_count=0,
            anonymous_speaker_count=0,
            generic_slot_count=0,
            edition_ids=(),
            render_ids=(),
            export_count=0,
            asset_roles=(),
            total_bytes=0,
            active_job_ids=(),
        )
    render_ids = tuple(
        sorted(
            session.scalars(
                select(NarrationSegmentRender.id).where(
                    NarrationSegmentRender.voice_version_id.in_(version_ids)
                )
            ).all(),
            key=str,
        )
    )
    edition_ids = set(
        session.scalars(
            select(NarrationEditionSegment.edition_id).where(
                NarrationEditionSegment.voice_version_id.in_(version_ids)
            )
        ).all()
    )
    if render_ids:
        edition_ids.update(
            session.scalars(
                select(NarrationManifestSegment.edition_id).where(
                    NarrationManifestSegment.render_id.in_(render_ids)
                )
            ).all()
        )
    ordered_editions = tuple(sorted(edition_ids, key=str))
    roles = _asset_role_map(
        session,
        versions=versions,
        render_ids=render_ids,
        edition_ids=ordered_editions,
    )
    assets: dict[UUID, MediaAsset] = {}
    if roles:
        assets = {
            row.id: row
            for row in session.scalars(
                select(MediaAsset).where(MediaAsset.id.in_(tuple(roles)))
            )
        }
        if set(assets) != set(roles):
            raise VoiceDeletionConflict("private voice references missing media evidence")
    for row in assets.values():
        if (
            row.owner_id != profile.owner_id
            or row.workspace_id != profile.workspace_id
            or row.novel_id != profile.novel_id
            or row.storage_backend != "local"
            or row.byte_size is None
            or row.byte_size < 0
            or re.fullmatch(r"[0-9a-f]{64}", row.content_hash) is None
        ):
            raise VoiceDeletionConflict("private voice media is outside the deletable scope")
    active_jobs: tuple[UUID, ...] = ()
    if roles:
        active_jobs = tuple(
            sorted(
                session.scalars(
                    select(ActiveJobAsset.job_id).where(
                        ActiveJobAsset.asset_id.in_(tuple(roles)),
                        ActiveJobAsset.released_at.is_(None),
                    )
                ).all(),
                key=str,
            )
        )
    return VoiceDeletionImpact(
        profile_id=profile.id,
        novel_id=profile.novel_id,
        profile_version=profile.version,
        voice_version_ids=tuple(sorted(version_ids, key=str)),
        current_narrator_count=_count(
            session,
            NovelNarrationSettings,
            NovelNarrationSettings.narrator_version_id.in_(version_ids),
        ),
        character_binding_count=_count(
            session,
            CharacterVoiceBinding,
            CharacterVoiceBinding.voice_version_id.in_(version_ids),
        ),
        anonymous_speaker_count=_count(
            session,
            AnonymousSpeaker,
            AnonymousSpeaker.voice_version_id.in_(version_ids),
        ),
        generic_slot_count=_count(
            session,
            GenericVoiceSlot,
            GenericVoiceSlot.voice_version_id.in_(version_ids),
            GenericVoiceSlot.enabled.is_(True),
        ),
        edition_ids=ordered_editions,
        render_ids=render_ids,
        export_count=(
            _count(
                session,
                NarrationExport,
                NarrationExport.edition_id.in_(ordered_editions),
            )
            if ordered_editions
            else 0
        ),
        asset_roles=tuple(sorted(roles.items(), key=lambda pair: str(pair[0]))),
        total_bytes=sum(int(row.byte_size or 0) for row in assets.values()),
        active_job_ids=active_jobs,
    )


def _request_hash(profile_id: UUID, expected_version: int, command: str) -> str:
    return hashlib.sha256(
        _canonical_bytes(
            {
                "schema_version": "private-voice-deletion-command/1",
                "profile_id": str(profile_id),
                "expected_profile_version": expected_version,
                "command": command,
            }
        )
    ).hexdigest()


def _impact_digest(keyring: DigestKeyring, impact: VoiceDeletionImpact) -> tuple[str, str]:
    return keyring.digest_active(_canonical_bytes(impact.payload()))


def _matches_confirmed_waiting_job_impact(
    row: VoiceDeletionRequest,
    impact: VoiceDeletionImpact,
) -> bool:
    """Allow only the expected active-job drain after the user confirmed.

    The first confirmation freezes the complete visible impact, including the
    number of jobs that must be cancelled.  Releasing those leases necessarily
    changes that one count before retry.  Every other visible consequence must
    remain byte-for-byte equal or the original confirmation is stale.
    """

    if (
        row.confirmed_at is None
        or row.failure_code != "VOICE_DELETE_WAITING_FOR_JOBS"
    ):
        return False
    frozen = dict(row.impact_snapshot_json)
    current = impact.payload()
    frozen_jobs = frozen.pop("active_job_count", None)
    current_jobs = current.pop("active_job_count", None)
    return (
        type(frozen_jobs) is int
        and type(current_jobs) is int
        and 0 <= current_jobs <= frozen_jobs
        and current == frozen
    )


def _request_by_id(
    session: Session, request_id: UUID, *, for_update: bool
) -> VoiceDeletionRequest:
    statement = select(VoiceDeletionRequest).where(VoiceDeletionRequest.id == request_id)
    if for_update:
        statement = statement.with_for_update()
    row = session.scalar(statement.execution_options(populate_existing=True))
    if row is None:
        raise VoiceDeletionNotFound("voice deletion request not found")
    if row.owner_id != LOCAL_OWNER_ID or row.workspace_id != LOCAL_WORKSPACE_ID:
        raise NarrationScopeMismatch("voice deletion request is outside fixed local scope")
    return row


def _request_snapshot(row: VoiceDeletionRequest) -> VoiceDeletionRequestSnapshot:
    if row.novel_id is None or row.expected_profile_version is None:
        raise VoiceDeletionConflict("legacy deletion request lacks novel/profile CAS evidence")
    return VoiceDeletionRequestSnapshot(
        request_id=row.id,
        profile_id=row.voice_profile_id,
        novel_id=row.novel_id,
        command=row.command,
        state=row.state,
        expected_profile_version=row.expected_profile_version,
        impact_digest=row.impact_digest,
        impact=dict(row.impact_snapshot_json),
        execute_after=row.execute_after,
        impact_expires_at=row.impact_expires_at,
        asset_count=row.asset_count,
        total_bytes=row.total_bytes,
        external_backup_status=row.external_backup_status,
        confirmed_at=row.confirmed_at,
        cancelled_at=row.cancelled_at,
        completed_at=row.completed_at,
        failure_code=row.failure_code,
    )


class VoiceDeletionService:
    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        storage: NarrationStorage,
        digest_keyring: DigestKeyring,
    ) -> None:
        if not callable(session_factory):
            raise TypeError("voice deletion requires a session factory")
        self._session_factory = session_factory
        self._storage = storage
        self._digest_keyring = digest_keyring

    def create_request(
        self,
        *,
        profile_id: UUID,
        expected_profile_version: int,
        discard_unreferenced: bool,
        idempotency_key: str,
        actor: str,
    ) -> VoiceDeletionRequestSnapshot:
        if type(expected_profile_version) is not int or expected_profile_version < 1:
            raise ValueError("expected_profile_version must be positive")
        if IDEMPOTENCY_KEY.fullmatch(idempotency_key) is None:
            raise ValueError("invalid voice deletion idempotency key")
        actor = _validated_actor(actor)
        command = (
            "discard_unreferenced_private_voice"
            if discard_unreferenced
            else "true_delete_private_voice"
        )
        request_hash = _request_hash(profile_id, expected_profile_version, command)

        def operation(session: Session) -> VoiceDeletionRequestSnapshot:
            existing = session.scalar(
                select(VoiceDeletionRequest)
                .where(
                    VoiceDeletionRequest.owner_id == LOCAL_OWNER_ID,
                    VoiceDeletionRequest.workspace_id == LOCAL_WORKSPACE_ID,
                    VoiceDeletionRequest.command == command,
                    VoiceDeletionRequest.idempotency_key == idempotency_key,
                )
                .with_for_update()
            )
            if existing is not None:
                if existing.request_hash != request_hash:
                    raise IdempotencyConflict("voice deletion idempotency key was reused")
                return _request_snapshot(existing)
            profile, _versions = _profile_and_versions(session, profile_id, for_update=True)
            if profile.version != expected_profile_version:
                raise NarrationCasConflict("voice profile version changed")
            active = session.scalar(
                select(VoiceDeletionRequest)
                .where(
                    VoiceDeletionRequest.voice_profile_id == profile_id,
                    VoiceDeletionRequest.state.in_(ACTIVE_REQUEST_STATES),
                )
                .with_for_update()
            )
            if active is not None:
                raise VoiceDeletionConflict("voice profile already has an active deletion request")
            impact = compute_voice_deletion_impact(session, profile_id, for_update=False)
            if discard_unreferenced and impact.has_usage:
                raise VoiceDeletionConflict("voice profile is still current or historically referenced")
            key_id, digest = _impact_digest(self._digest_keyring, impact)
            now = _utc_now()
            row = VoiceDeletionRequest(
                id=uuid4(),
                owner_id=profile.owner_id,
                workspace_id=profile.workspace_id,
                novel_id=profile.novel_id,
                voice_profile_id=profile.id,
                command=command,
                state="grace_pending" if discard_unreferenced else "requested",
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                expected_profile_version=profile.version,
                impact_digest_key_id=key_id,
                impact_digest=digest,
                impact_snapshot_json=impact.payload(),
                impact_expires_at=now + IMPACT_TTL,
                execute_after=(now + UNREFERENCED_GRACE if discard_unreferenced else None),
                asset_count=len(impact.asset_roles),
                total_bytes=impact.total_bytes,
                external_backup_status="unmanaged",
                requested_actor=actor,
                requested_at=now,
                updated_at=now,
            )
            session.add(row)
            session.flush([row])
            return _request_snapshot(row)

        return _transaction(self._session_factory, operation)

    def get_request(self, request_id: UUID) -> VoiceDeletionRequestSnapshot:
        return _transaction(
            self._session_factory,
            lambda session: _request_snapshot(
                _request_by_id(session, request_id, for_update=False)
            ),
        )

    def cancel(self, request_id: UUID, *, actor: str) -> VoiceDeletionRequestSnapshot:
        actor = _validated_actor(actor)

        def operation(session: Session) -> VoiceDeletionRequestSnapshot:
            row = _request_by_id(session, request_id, for_update=True)
            if row.state == "cancelled":
                return _request_snapshot(row)
            if row.state not in {"grace_pending", "requested"} or row.confirmed_at is not None:
                raise VoiceDeletionConflict("voice deletion can no longer be cancelled")
            now = _utc_now()
            if (
                row.state == "grace_pending"
                and row.execute_after is not None
                and now >= row.execute_after
            ):
                raise VoiceDeletionConflict("voice deletion undo window has expired")
            row.state = "cancelled"
            row.cancelled_actor = actor
            row.cancelled_at = now
            row.updated_at = now
            session.flush([row])
            return _request_snapshot(row)

        return _transaction(self._session_factory, operation)

    def confirm(
        self,
        request_id: UUID,
        *,
        expected_profile_version: int,
        impact_digest: str,
        actor: str,
    ) -> VoiceDeletionRequestSnapshot:
        actor = _validated_actor(actor)
        current = self.get_request(request_id)
        if current.state in {"completed", "live_deleted_backup_pending"}:
            return current
        if current.state == "live_deleting":
            return self._execute_plans(request_id, actor=actor)
        candidates = _transaction(
            self._session_factory,
            lambda session: self._prepare_confirmation(
                session,
                request_id=request_id,
                expected_profile_version=expected_profile_version,
                impact_digest=impact_digest,
                actor=actor,
            ),
        )
        if isinstance(candidates, VoiceDeletionRequestSnapshot):
            return candidates
        identities: dict[UUID, StoredFileIdentity | None] = {}
        for candidate in candidates:
            identities[candidate.asset_id] = self._storage.capture_media_identity(
                candidate.storage_path, missing_ok=True
            )
            identity = identities[candidate.asset_id]
            if identity is not None and identity.byte_size != candidate.byte_size:
                raise VoiceDeletionConflict("voice deletion media changed before fencing")
        row = _transaction(
            self._session_factory,
            lambda session: self._fence_confirmation(
                session,
                request_id=request_id,
                expected_profile_version=expected_profile_version,
                impact_digest=impact_digest,
                actor=actor,
                candidates=candidates,
                identities=identities,
            ),
        )
        if row.state == "live_deleting":
            return self._execute_plans(request_id, actor=actor)
        return row

    def retry(self, request_id: UUID, *, actor: str) -> VoiceDeletionRequestSnapshot:
        actor = _validated_actor(actor)
        row = self.get_request(request_id)
        if row.state in {"completed", "live_deleted_backup_pending"}:
            return row
        if row.state == "live_deleting":
            return self._execute_plans(request_id, actor=actor)
        if row.state != "failed" or row.confirmed_at is None:
            raise VoiceDeletionConflict("voice deletion request is not retryable")
        if row.failure_code == "VOICE_DELETE_WAITING_FOR_JOBS":
            return self.confirm(
                request_id,
                expected_profile_version=int(row.expected_profile_version or 0),
                impact_digest=row.impact_digest,
                actor=row.confirmed_actor or actor,
            )
        _transaction(
            self._session_factory,
            lambda session: self._resume_failed_request(session, request_id),
        )
        return self._execute_plans(request_id, actor=actor)

    def _prepare_confirmation(
        self,
        session: Session,
        *,
        request_id: UUID,
        expected_profile_version: int,
        impact_digest: str,
        actor: str,
    ) -> tuple[_AssetCandidate, ...] | VoiceDeletionRequestSnapshot:
        row = _request_by_id(session, request_id, for_update=True)
        if row.state in {"completed", "live_deleted_backup_pending"}:
            return _request_snapshot(row)
        if row.state == "cancelled" or row.state == "live_deleting":
            raise VoiceDeletionConflict("voice deletion request cannot be confirmed")
        if row.state == "grace_pending" and row.execute_after is not None:
            if _utc_now() < row.execute_after:
                raise VoiceDeletionConflict("unreferenced voice is still inside its undo window")
        if row.state == "failed" and row.failure_code != "VOICE_DELETE_WAITING_FOR_JOBS":
            raise VoiceDeletionConflict("failed physical deletion must use retry")
        profile, _versions = _profile_and_versions(
            session, row.voice_profile_id, for_update=True
        )
        if (
            profile.version != expected_profile_version
            or row.expected_profile_version != expected_profile_version
        ):
            raise NarrationCasConflict("voice profile version changed")
        impact = compute_voice_deletion_impact(session, profile.id, for_update=False)
        key_id, digest = _impact_digest(self._digest_keyring, impact)
        exact_impact = (
            key_id == row.impact_digest_key_id and digest == row.impact_digest
        )
        waiting_job_drain = _matches_confirmed_waiting_job_impact(row, impact)
        unexpired = (
            row.confirmed_at is not None
            or (
                row.impact_expires_at is not None
                and _utc_now() < row.impact_expires_at
            )
        )
        if (
            impact_digest != row.impact_digest
            or not unexpired
            or not (exact_impact or waiting_job_drain)
        ):
            raise NarrationCasConflict("voice deletion impact changed or expired")
        now = _utc_now()
        if row.confirmed_at is None:
            row.confirmed_actor = actor
            row.confirmed_at = now
        if impact.active_job_ids:
            for job in session.scalars(
                select(BackgroundJob)
                .where(BackgroundJob.id.in_(impact.active_job_ids))
                .with_for_update()
            ):
                if job.state in {"queued", "running", "retry_wait"}:
                    job.state = "cancel_requested"
                    job.cancel_requested_at = now
                    job.cancel_actor = actor
                    job.cancel_reason_code = "PRIVATE_VOICE_DELETE"
                    job.updated_at = now
            row.state = "failed"
            row.failure_code = "VOICE_DELETE_WAITING_FOR_JOBS"
            row.updated_at = now
            session.flush()
            return _request_snapshot(row)
        assets = self._asset_candidates(session, impact)
        row.failure_code = None
        row.updated_at = now
        session.flush([row])
        return assets

    def _asset_candidates(
        self, session: Session, impact: VoiceDeletionImpact
    ) -> tuple[_AssetCandidate, ...]:
        if not impact.asset_roles:
            return ()
        role_map = dict(impact.asset_roles)
        rows = tuple(
            session.scalars(
                select(MediaAsset)
                .where(MediaAsset.id.in_(tuple(role_map)))
                .order_by(MediaAsset.id)
            ).all()
        )
        if {row.id for row in rows} != set(role_map):
            raise VoiceDeletionConflict("voice deletion media evidence changed")
        return tuple(
            _AssetCandidate(
                asset_id=row.id,
                role=role_map[row.id],
                owner_id=row.owner_id,
                workspace_id=row.workspace_id,
                novel_id=impact.novel_id,
                storage_backend=row.storage_backend,
                storage_path=row.storage_path,
                content_hash=row.content_hash,
                byte_size=int(row.byte_size or 0),
                gc_generation=row.gc_generation,
            )
            for row in rows
        )

    def _fence_confirmation(
        self,
        session: Session,
        *,
        request_id: UUID,
        expected_profile_version: int,
        impact_digest: str,
        actor: str,
        candidates: tuple[_AssetCandidate, ...],
        identities: dict[UUID, StoredFileIdentity | None],
    ) -> VoiceDeletionRequestSnapshot:
        row = _request_by_id(session, request_id, for_update=True)
        profile, versions = _profile_and_versions(session, row.voice_profile_id, for_update=True)
        if row.state == "live_deleting":
            return _request_snapshot(row)
        if row.state not in {"requested", "grace_pending", "failed"}:
            raise VoiceDeletionConflict("voice deletion request changed before fencing")
        if profile.version != expected_profile_version or row.impact_digest != impact_digest:
            raise NarrationCasConflict("voice deletion profile or impact changed")
        impact = compute_voice_deletion_impact(session, profile.id, for_update=False)
        _key_id, digest = _impact_digest(self._digest_keyring, impact)
        if (
            digest != row.impact_digest
            and not _matches_confirmed_waiting_job_impact(row, impact)
        ) or impact.active_job_ids:
            raise NarrationCasConflict("voice deletion impact changed before fencing")
        current_candidates = self._asset_candidates(session, impact)
        if current_candidates != candidates:
            raise NarrationCasConflict("voice deletion asset set changed before fencing")
        now = _utc_now()
        for candidate in candidates:
            asset = session.scalar(
                select(MediaAsset)
                .where(MediaAsset.id == candidate.asset_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if asset is None or asset.state not in {"ready", "staging"}:
                raise VoiceDeletionConflict("voice deletion asset is not fenceable")
            identity = identities[candidate.asset_id]
            plan = VoiceDeletionAssetPlan(
                id=uuid4(),
                deletion_request_id=row.id,
                owner_id=candidate.owner_id,
                workspace_id=candidate.workspace_id,
                novel_id=candidate.novel_id,
                asset_id=candidate.asset_id,
                role=candidate.role,
                storage_backend=candidate.storage_backend,
                storage_path=candidate.storage_path,
                content_hash=candidate.content_hash,
                byte_size=candidate.byte_size,
                gc_generation=candidate.gc_generation,
                file_present=identity is not None,
                device=(identity.device if identity is not None else None),
                inode=(identity.inode if identity is not None else None),
                state="planned",
                created_at=now,
            )
            session.add(plan)
            session.flush([plan])
            asset.state = "deleting"
        version_ids = tuple(item.id for item in versions)
        for settings in session.scalars(
            select(NovelNarrationSettings)
            .where(NovelNarrationSettings.narrator_version_id.in_(version_ids))
            .with_for_update()
        ):
            settings.narrator_profile_id = None
            settings.narrator_version_id = None
            settings.version += 1
            settings.updated_at = now
        for binding in session.scalars(
            select(CharacterVoiceBinding)
            .where(CharacterVoiceBinding.voice_version_id.in_(version_ids))
            .with_for_update()
        ):
            binding.profile_id = None
            binding.voice_version_id = None
            binding.binding_policy = "unset"
            binding.version += 1
            binding.updated_at = now
        for speaker in session.scalars(
            select(AnonymousSpeaker)
            .where(AnonymousSpeaker.voice_version_id.in_(version_ids))
            .with_for_update()
        ):
            speaker.voice_version_id = None
        for slot in session.scalars(
            select(GenericVoiceSlot)
            .where(GenericVoiceSlot.voice_version_id.in_(version_ids))
            .with_for_update()
        ):
            slot.enabled = False
        if impact.edition_ids:
            for edition in session.scalars(
                select(NarrationEdition)
                .where(NarrationEdition.id.in_(impact.edition_ids))
                .with_for_update()
            ):
                edition.state = "unavailable"
                edition.unavailable_reason = "unavailable_private_voice_deleted"
            for segment in session.scalars(
                select(NarrationEditionSegment)
                .where(NarrationEditionSegment.edition_id.in_(impact.edition_ids))
                .with_for_update()
            ):
                if segment.voice_version_id in version_ids:
                    segment.render_state = "quarantined"
                    segment.failure_code = "PRIVATE_VOICE_DELETED"
        if impact.render_ids:
            for render in session.scalars(
                select(NarrationSegmentRender)
                .where(NarrationSegmentRender.id.in_(impact.render_ids))
                .with_for_update()
            ):
                render.state = "quarantined"
        profile.status = "unavailable"
        profile.version += 1
        profile.updated_at = now
        row.state = "live_deleting"
        row.confirmed_actor = row.confirmed_actor or actor
        row.confirmed_at = row.confirmed_at or now
        row.failure_code = None
        row.updated_at = now
        session.flush()
        return _request_snapshot(row)

    def _execute_plans(
        self, request_id: UUID, *, actor: str
    ) -> VoiceDeletionRequestSnapshot:
        plan_ids = _transaction(
            self._session_factory,
            lambda session: tuple(
                session.scalars(
                    select(VoiceDeletionAssetPlan.id)
                    .where(
                        VoiceDeletionAssetPlan.deletion_request_id == request_id,
                        VoiceDeletionAssetPlan.state != "finalized",
                    )
                    .order_by(VoiceDeletionAssetPlan.asset_id)
                ).all()
            ),
        )
        for plan_id in plan_ids:
            try:
                plan = _transaction(
                    self._session_factory,
                    lambda session, plan_id=plan_id: self._mark_unlinking(session, plan_id),
                )
                self._storage.delete_media_verified(
                    plan.storage_path,
                    expected_sha256=plan.content_hash,
                    expected_size=plan.byte_size,
                    expected_device=plan.device,
                    expected_inode=plan.inode,
                    expected_present=plan.file_present,
                    missing_ok=True,
                )
                self._storage.ensure_media_absent(plan.storage_path)
                _transaction(
                    self._session_factory,
                    lambda session, plan_id=plan_id: self._finalize_unlinked(
                        session, plan_id=plan_id, actor=actor
                    ),
                )
            except Exception:
                _transaction(
                    self._session_factory,
                    lambda session, plan_id=plan_id: self._mark_plan_failed(
                        session, plan_id
                    ),
                )
                raise
        return _transaction(
            self._session_factory,
            lambda session: self._complete_request(session, request_id),
        )

    def _mark_unlinking(
        self, session: Session, plan_id: UUID
    ) -> _AssetPlanSnapshot:
        plan = session.scalar(
            select(VoiceDeletionAssetPlan)
            .where(VoiceDeletionAssetPlan.id == plan_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if plan is None:
            raise VoiceDeletionNotFound("voice deletion asset plan not found")
        if plan.state == "finalized":
            return _AssetPlanSnapshot(
                plan_id=plan.id,
                deletion_request_id=plan.deletion_request_id,
                asset_id=plan.asset_id,
                storage_path=plan.storage_path,
                content_hash=plan.content_hash,
                byte_size=plan.byte_size,
                file_present=plan.file_present,
                device=plan.device,
                inode=plan.inode,
            )
        if plan.state not in {"planned", "unlinking", "unlinked", "failed"}:
            raise VoiceDeletionConflict("voice deletion asset plan cannot resume")
        plan.state = "unlinking"
        plan.failure_code = None
        session.flush([plan])
        return _AssetPlanSnapshot(
            plan_id=plan.id,
            deletion_request_id=plan.deletion_request_id,
            asset_id=plan.asset_id,
            storage_path=plan.storage_path,
            content_hash=plan.content_hash,
            byte_size=plan.byte_size,
            file_present=plan.file_present,
            device=plan.device,
            inode=plan.inode,
        )

    def _finalize_unlinked(self, session: Session, *, plan_id: UUID, actor: str) -> None:
        plan = session.scalar(
            select(VoiceDeletionAssetPlan)
            .where(VoiceDeletionAssetPlan.id == plan_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if plan is None:
            raise VoiceDeletionNotFound("voice deletion asset plan not found")
        if plan.state == "finalized":
            return
        plan.state = "unlinked"
        plan.unlinked_at = _utc_now()
        session.flush([plan])
        finalize_voice_deletion_asset_in_session(
            session,
            self._storage,
            deletion_request_id=plan.deletion_request_id,
            asset_id=plan.asset_id,
            digest_key_id=self._digest_keyring.active_key_id,
            digest_key=self._digest_keyring.active.secret,
            deleted_actor=actor,
        )

    def _mark_plan_failed(self, session: Session, plan_id: UUID) -> None:
        plan = session.scalar(
            select(VoiceDeletionAssetPlan)
            .where(VoiceDeletionAssetPlan.id == plan_id)
            .with_for_update()
        )
        if plan is None or plan.state == "finalized":
            return
        plan.state = "failed"
        plan.failure_code = "VOICE_DELETE_UNLINK_FAILED"
        request = _request_by_id(session, plan.deletion_request_id, for_update=True)
        request.state = "failed"
        request.failure_code = plan.failure_code
        request.updated_at = _utc_now()
        session.flush()

    def _complete_request(
        self, session: Session, request_id: UUID
    ) -> VoiceDeletionRequestSnapshot:
        row = _request_by_id(session, request_id, for_update=True)
        remaining = _count(
            session,
            VoiceDeletionAssetPlan,
            VoiceDeletionAssetPlan.deletion_request_id == request_id,
            VoiceDeletionAssetPlan.state != "finalized",
        )
        if remaining:
            raise VoiceDeletionConflict("voice deletion asset plans are incomplete")
        now = _utc_now()
        row.state = "completed"
        row.completed_at = now
        row.failure_code = None
        row.updated_at = now
        session.flush([row])
        return _request_snapshot(row)

    def _resume_failed_request(self, session: Session, request_id: UUID) -> None:
        row = _request_by_id(session, request_id, for_update=True)
        row.state = "live_deleting"
        row.failure_code = None
        row.updated_at = _utc_now()
        session.flush([row])


__all__ = [
    "VoiceDeletionConflict",
    "VoiceDeletionImpact",
    "VoiceDeletionNotFound",
    "VoiceDeletionRequestSnapshot",
    "VoiceDeletionService",
    "compute_voice_deletion_impact",
]
