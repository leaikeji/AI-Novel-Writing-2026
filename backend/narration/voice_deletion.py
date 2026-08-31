"""Recoverable, request-scoped deletion for one private narration profile.

Voice versions, Editions and audit rows remain immutable.  Only current voice
selection is fenced and exact media bytes listed in a durable request plan are
eligible for physical deletion.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Final, Iterable, Sequence
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
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
    Novel,
    NovelNarrationSettings,
    VoiceDeletionAssetPlan,
    VoiceDeletionRequest,
    VoicePreview,
    VoiceProfile,
    VoiceProfileVersion,
    VoiceReferenceAssetLink,
)
from .contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID
from .digest_keyring import DigestKeyring
from .media import MediaConflict, MediaPolicyError, finalize_voice_deletion_asset_in_session
from .services import (
    IdempotencyConflict,
    InvalidNarrationState,
    NarrationCasConflict,
    NarrationNotFound,
    NarrationScopeMismatch,
)
from .storage import (
    NarrationStorage,
    PublicationValidationError,
    StorageError,
    StoredFileIdentity,
    UnsafeStoragePath,
    validate_relative_path,
)


IMPACT_TTL: Final = timedelta(minutes=15)
UNREFERENCED_GRACE: Final = timedelta(seconds=30)
JOB_DRAIN_TIMEOUT: Final = timedelta(minutes=5)
IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
ACTIVE_REQUEST_STATES: Final = frozenset(
    {"grace_pending", "requested", "live_deleting", "live_deleted_backup_pending", "failed"}
)
PRIVATE_SOURCE_TYPES: Final = frozenset({"uploaded", "generated"})
TERMINAL_REQUEST_STATES: Final = frozenset({"completed", "cancelled", "superseded"})
WAITING_FOR_JOBS: Final = "VOICE_DELETE_WAITING_FOR_JOBS"
SUPERSEDED_FAILURE_CODES: Final = frozenset(
    {
        "VOICE_DELETE_PROFILE_CHANGED",
        "VOICE_DELETE_IMPACT_CHANGED",
        "VOICE_DELETE_IMPACT_EXPIRED",
        "VOICE_DELETE_JOB_DRAIN_TIMEOUT",
    }
)
POST_FENCE_RETRYABLE_FAILURE_CODES: Final = frozenset(
    {
        "VOICE_DELETE_UNLINK_FAILED",
        "VOICE_DELETE_STORAGE_TEMPORARY",
        "VOICE_DELETE_FINALIZE_FAILED",
    }
)
NON_RETRYABLE_SAFETY_FAILURE_CODES: Final = frozenset(
    {
        "VOICE_DELETE_SCOPE_INVALID",
        "VOICE_DELETE_FILE_IDENTITY_INVALID",
        "VOICE_DELETE_ASSET_PLAN_INVALID",
    }
)
RECONCILIATION_BATCH_LIMIT: Final = 25


SessionFactory = Callable[[], Session]
StateChangeCallback = Callable[[], None]


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
    def current_reference_count(self) -> int:
        return (
            self.current_narrator_count
            + self.character_binding_count
            + self.anonymous_speaker_count
            + self.generic_slot_count
        )

    @property
    def historical_reference_count(self) -> int:
        return len(self.edition_ids) + len(self.render_ids) + self.export_count

    @property
    def reference_count(self) -> int:
        return self.current_reference_count + self.historical_reference_count

    @property
    def has_references(self) -> bool:
        return self.reference_count > 0

    @property
    def has_usage(self) -> bool:
        """Compatibility projection that also treats an active job as usage."""

        return self.has_references or bool(self.active_job_ids)

    def impact_summary(self) -> str:
        if not self.has_references:
            return f"未发现当前或历史朗读引用；将删除 {len(self.asset_roles)} 个私人音色资产。"
        return (
            f"将解除 {self.current_reference_count} 处当前引用，并使 "
            f"{self.historical_reference_count} 项历史朗读证据不可播放；"
            f"将删除 {len(self.asset_roles)} 个私人音色资产。"
        )

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": "private-voice-deletion-impact/2",
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
            "current_reference_count": self.current_reference_count,
            "historical_reference_count": self.historical_reference_count,
            "reference_count": self.reference_count,
            "asset_count": len(self.asset_roles),
            "total_bytes": self.total_bytes,
            "active_job_count": len(self.active_job_ids),
            "external_backup_status": "unmanaged",
            "historical_audio_consequence": (
                "unavailable_private_voice_deleted" if self.edition_ids else None
            ),
            "impact_summary": self.impact_summary(),
        }


@dataclass(frozen=True, slots=True)
class VoiceDeletionRequestSnapshot:
    request_id: UUID
    profile_id: UUID
    novel_id: UUID
    command: str
    state: str
    server_now: datetime
    expected_profile_version: int
    impact_digest: str
    impact: dict[str, object]
    eligibility: str
    reference_count: int
    execute_after: datetime | None
    impact_expires_at: datetime | None
    asset_count: int
    total_bytes: int
    external_backup_status: str
    confirmed_at: datetime | None
    cancelled_at: datetime | None
    completed_at: datetime | None
    superseded_at: datetime | None
    job_drain_started_at: datetime | None
    job_drain_deadline: datetime | None
    failure_code: str | None
    cancellable: bool
    retryable: bool
    terminal: bool


@dataclass(frozen=True, slots=True)
class VoiceDeletionReconciliationBatch:
    request_ids: tuple[UUID, ...]
    has_more: bool


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


def _require_local_novel(
    session: Session,
    novel_id: UUID,
    *,
    for_update: bool,
) -> Novel:
    if type(novel_id) is not UUID:
        raise ValueError("novel_id must be an exact UUID")
    statement = select(Novel).where(Novel.id == novel_id)
    if for_update:
        statement = statement.with_for_update()
    novel = session.scalar(statement.execution_options(populate_existing=True))
    if novel is None:
        raise VoiceDeletionNotFound("novel not found")
    if novel.owner_id != LOCAL_OWNER_ID or novel.workspace_id != LOCAL_WORKSPACE_ID:
        raise NarrationScopeMismatch("novel is outside fixed local scope")
    return novel


def _profile_and_versions(
    session: Session,
    novel_id: UUID,
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
    if profile.novel_id != novel_id:
        raise NarrationScopeMismatch("voice profile does not belong to the requested novel")
    if profile.status == "unavailable":
        raise VoiceDeletionConflict("unavailable voice profiles cannot be deleted again")
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
    if not versions:
        raise VoiceDeletionConflict("private voice profile has no version evidence")
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
    novel_id: UUID,
    profile_id: UUID,
    *,
    for_update: bool = False,
) -> VoiceDeletionImpact:
    _require_local_novel(session, novel_id, for_update=False)
    profile, versions = _profile_and_versions(
        session,
        novel_id,
        profile_id,
        for_update=for_update,
    )
    version_ids = tuple(row.id for row in versions)
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


def _request_hash(novel_id: UUID, profile_id: UUID, expected_version: int) -> str:
    return hashlib.sha256(
        _canonical_bytes(
            {
                "schema_version": "private-voice-deletion-command/2",
                "novel_id": str(novel_id),
                "profile_id": str(profile_id),
                "expected_profile_version": expected_version,
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
    session: Session,
    request_id: UUID,
    *,
    novel_id: UUID | None,
    for_update: bool,
) -> VoiceDeletionRequest:
    statement = select(VoiceDeletionRequest).where(VoiceDeletionRequest.id == request_id)
    if for_update:
        statement = statement.with_for_update()
    row = session.scalar(statement.execution_options(populate_existing=True))
    if row is None:
        raise VoiceDeletionNotFound("voice deletion request not found")
    if row.owner_id != LOCAL_OWNER_ID or row.workspace_id != LOCAL_WORKSPACE_ID:
        raise NarrationScopeMismatch("voice deletion request is outside fixed local scope")
    if row.novel_id is None:
        raise VoiceDeletionConflict("legacy voice deletion request lacks novel scope")
    if novel_id is not None and row.novel_id != novel_id:
        raise NarrationScopeMismatch(
            "voice deletion request does not belong to the requested novel"
        )
    return row


def _impact_count(payload: dict[str, object], field: str) -> int:
    value = payload.get(field, 0)
    return value if type(value) is int and value >= 0 else 0


def _request_snapshot(
    row: VoiceDeletionRequest,
    *,
    now: datetime | None = None,
) -> VoiceDeletionRequestSnapshot:
    if row.novel_id is None or row.expected_profile_version is None:
        raise VoiceDeletionConflict("legacy deletion request lacks novel/profile CAS evidence")
    server_now = now or _utc_now()
    impact = dict(row.impact_snapshot_json)
    reference_count = _impact_count(impact, "reference_count")
    if "reference_count" not in impact:
        reference_count = sum(
            _impact_count(impact, field)
            for field in (
                "current_narrator_count",
                "character_binding_count",
                "anonymous_speaker_count",
                "generic_slot_count",
                "historical_edition_count",
                "render_count",
                "export_count",
            )
        )
    superseded_at = getattr(row, "superseded_at", None)
    job_drain_started_at = getattr(row, "job_drain_started_at", None)
    job_drain_deadline = getattr(row, "job_drain_deadline", None)
    terminal = row.state in TERMINAL_REQUEST_STATES or (
        row.state == "failed"
        and row.failure_code in NON_RETRYABLE_SAFETY_FAILURE_CODES
    )
    cancellable = (
        (
            row.state == "grace_pending"
            and row.confirmed_at is None
            and row.execute_after is not None
            and server_now < row.execute_after
        )
        or (row.state == "requested" and row.confirmed_at is None)
        or (
            row.state == "failed"
            and row.failure_code == WAITING_FOR_JOBS
            and (job_drain_deadline is None or server_now < job_drain_deadline)
        )
    )
    retryable = (
        row.state == "failed"
        and (
            (
                row.failure_code == WAITING_FOR_JOBS
                and (job_drain_deadline is None or server_now < job_drain_deadline)
            )
            or row.failure_code in POST_FENCE_RETRYABLE_FAILURE_CODES
        )
    )
    eligibility = (
        "blocked"
        if row.failure_code in NON_RETRYABLE_SAFETY_FAILURE_CODES
        else ("referenced" if reference_count else "unreferenced")
    )
    return VoiceDeletionRequestSnapshot(
        request_id=row.id,
        profile_id=row.voice_profile_id,
        novel_id=row.novel_id,
        command=row.command,
        state=row.state,
        server_now=server_now,
        expected_profile_version=row.expected_profile_version,
        impact_digest=row.impact_digest,
        impact=impact,
        eligibility=eligibility,
        reference_count=reference_count,
        execute_after=row.execute_after,
        impact_expires_at=row.impact_expires_at,
        asset_count=row.asset_count,
        total_bytes=row.total_bytes,
        external_backup_status=row.external_backup_status,
        confirmed_at=row.confirmed_at,
        cancelled_at=row.cancelled_at,
        completed_at=row.completed_at,
        superseded_at=superseded_at,
        job_drain_started_at=job_drain_started_at,
        job_drain_deadline=job_drain_deadline,
        failure_code=row.failure_code,
        cancellable=cancellable,
        retryable=retryable,
        terminal=terminal,
    )


def _reconciliation_candidate_statement(
    *,
    current: datetime,
    exclude_request_ids: Sequence[UUID],
    limit: int,
):  # type: ignore[no-untyped-def]
    conditions = [
        VoiceDeletionRequest.owner_id == LOCAL_OWNER_ID,
        VoiceDeletionRequest.workspace_id == LOCAL_WORKSPACE_ID,
        or_(
            and_(
                VoiceDeletionRequest.state == "grace_pending",
                or_(
                    VoiceDeletionRequest.execute_after <= current,
                    VoiceDeletionRequest.impact_expires_at <= current,
                ),
            ),
            and_(
                VoiceDeletionRequest.state == "requested",
                or_(
                    VoiceDeletionRequest.confirmed_at.is_not(None),
                    VoiceDeletionRequest.impact_expires_at <= current,
                ),
            ),
            and_(
                VoiceDeletionRequest.state == "failed",
                VoiceDeletionRequest.failure_code == WAITING_FOR_JOBS,
            ),
            VoiceDeletionRequest.state.in_(
                ("live_deleting", "live_deleted_backup_pending")
            ),
            and_(
                VoiceDeletionRequest.state == "failed",
                VoiceDeletionRequest.failure_code.in_(
                    tuple(sorted(POST_FENCE_RETRYABLE_FAILURE_CODES))
                ),
            ),
        ),
    ]
    if exclude_request_ids:
        conditions.append(
            VoiceDeletionRequest.id.not_in(tuple(exclude_request_ids))
        )
    return (
        select(VoiceDeletionRequest.id)
        .where(*conditions)
        .order_by(
            VoiceDeletionRequest.requested_at,
            VoiceDeletionRequest.id,
        )
        .limit(limit)
        .with_for_update(skip_locked=True)
    )


class VoiceDeletionService:
    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        storage: NarrationStorage,
        digest_keyring: DigestKeyring,
        on_state_change: StateChangeCallback | None = None,
    ) -> None:
        if not callable(session_factory):
            raise TypeError("voice deletion requires a session factory")
        if on_state_change is not None and not callable(on_state_change):
            raise TypeError("voice deletion state-change callback must be callable")
        self._session_factory = session_factory
        self._storage = storage
        self._digest_keyring = digest_keyring
        self._on_state_change = on_state_change
        self._notification_context = threading.local()

    def set_state_change_callback(
        self,
        callback: StateChangeCallback | None,
    ) -> None:
        if callback is not None and not callable(callback):
            raise TypeError("voice deletion state-change callback must be callable")
        self._on_state_change = callback

    def _notify_state_change(self) -> None:
        callback = self._on_state_change
        if callback is not None and not getattr(
            self._notification_context,
            "suppressed",
            False,
        ):
            callback()

    def create_request(
        self,
        *,
        novel_id: UUID,
        profile_id: UUID,
        expected_profile_version: int,
        idempotency_key: str,
        actor: str,
    ) -> VoiceDeletionRequestSnapshot:
        if type(novel_id) is not UUID or type(profile_id) is not UUID:
            raise ValueError("novel_id and profile_id must be exact UUIDs")
        if type(expected_profile_version) is not int or expected_profile_version < 1:
            raise ValueError("expected_profile_version must be positive")
        if IDEMPOTENCY_KEY.fullmatch(idempotency_key) is None:
            raise ValueError("invalid voice deletion idempotency key")
        actor = _validated_actor(actor)
        request_hash = _request_hash(novel_id, profile_id, expected_profile_version)

        def operation(
            session: Session,
        ) -> tuple[VoiceDeletionRequestSnapshot, bool]:
            _require_local_novel(session, novel_id, for_update=False)
            existing = session.scalar(
                select(VoiceDeletionRequest)
                .where(
                    VoiceDeletionRequest.owner_id == LOCAL_OWNER_ID,
                    VoiceDeletionRequest.workspace_id == LOCAL_WORKSPACE_ID,
                    VoiceDeletionRequest.idempotency_key == idempotency_key,
                )
                .with_for_update()
            )
            if existing is not None:
                if existing.request_hash != request_hash:
                    raise IdempotencyConflict("voice deletion idempotency key was reused")
                if existing.novel_id != novel_id:
                    raise NarrationScopeMismatch(
                        "voice deletion request does not belong to the requested novel"
                    )
                return _request_snapshot(existing), False
            profile, _versions = _profile_and_versions(
                session,
                novel_id,
                profile_id,
                for_update=True,
            )
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
            impact = compute_voice_deletion_impact(
                session,
                novel_id,
                profile_id,
                for_update=False,
            )
            unreferenced = not impact.has_references
            command = (
                "discard_unreferenced_private_voice"
                if unreferenced
                else "true_delete_private_voice"
            )
            key_id, digest = _impact_digest(self._digest_keyring, impact)
            now = _utc_now()
            row = VoiceDeletionRequest(
                id=uuid4(),
                owner_id=profile.owner_id,
                workspace_id=profile.workspace_id,
                novel_id=profile.novel_id,
                voice_profile_id=profile.id,
                command=command,
                state="grace_pending" if unreferenced else "requested",
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                expected_profile_version=profile.version,
                impact_digest_key_id=key_id,
                impact_digest=digest,
                impact_snapshot_json=impact.payload(),
                impact_expires_at=now + IMPACT_TTL,
                execute_after=(now + UNREFERENCED_GRACE if unreferenced else None),
                asset_count=len(impact.asset_roles),
                total_bytes=impact.total_bytes,
                external_backup_status="unmanaged",
                requested_actor=actor,
                requested_at=now,
                updated_at=now,
            )
            session.add(row)
            session.flush([row])
            return _request_snapshot(row, now=now), True

        snapshot, created = _transaction(self._session_factory, operation)
        if created:
            self._notify_state_change()
        return snapshot

    def get_request(
        self,
        *,
        novel_id: UUID,
        request_id: UUID,
    ) -> VoiceDeletionRequestSnapshot:
        return _transaction(
            self._session_factory,
            lambda session: (
                _require_local_novel(session, novel_id, for_update=False),
                _request_snapshot(
                    _request_by_id(
                        session,
                        request_id,
                        novel_id=novel_id,
                        for_update=False,
                    )
                ),
            )[1],
        )

    def cancel(
        self,
        *,
        novel_id: UUID,
        request_id: UUID,
        actor: str,
    ) -> VoiceDeletionRequestSnapshot:
        actor = _validated_actor(actor)

        def operation(
            session: Session,
        ) -> tuple[VoiceDeletionRequestSnapshot, bool]:
            _require_local_novel(session, novel_id, for_update=False)
            row = _request_by_id(
                session,
                request_id,
                novel_id=novel_id,
                for_update=True,
            )
            now = _utc_now()
            if row.state in TERMINAL_REQUEST_STATES:
                return _request_snapshot(row, now=now), False
            waiting = row.state == "failed" and row.failure_code == WAITING_FOR_JOBS
            if not (
                (row.state == "grace_pending" and row.confirmed_at is None)
                or (row.state == "requested" and row.confirmed_at is None)
                or waiting
            ):
                raise VoiceDeletionConflict("voice deletion can no longer be cancelled")
            if (
                row.state == "grace_pending"
                and row.execute_after is not None
                and now >= row.execute_after
            ):
                raise VoiceDeletionConflict("voice deletion undo window has expired")
            if waiting:
                deadline = getattr(row, "job_drain_deadline", None)
                if deadline is not None and now >= deadline:
                    snapshot = self._supersede(
                        session,
                        row,
                        failure_code="VOICE_DELETE_JOB_DRAIN_TIMEOUT",
                        now=now,
                    )
                    return snapshot, True
                if _count(
                    session,
                    VoiceDeletionAssetPlan,
                    VoiceDeletionAssetPlan.deletion_request_id == row.id,
                ):
                    raise VoiceDeletionConflict(
                        "fenced voice deletion cannot be cancelled"
                    )
            row.state = "cancelled"
            row.cancelled_actor = actor
            row.cancelled_at = now
            row.failure_code = None
            row.updated_at = now
            session.flush([row])
            return _request_snapshot(row, now=now), True

        snapshot, changed = _transaction(self._session_factory, operation)
        if changed:
            self._notify_state_change()
        return snapshot

    def confirm(
        self,
        *,
        novel_id: UUID,
        request_id: UUID,
        expected_profile_version: int,
        impact_digest: str,
        actor: str,
    ) -> VoiceDeletionRequestSnapshot:
        if type(expected_profile_version) is not int or expected_profile_version < 1:
            raise ValueError("expected_profile_version must be positive")
        if re.fullmatch(r"[0-9a-f]{64}", impact_digest) is None:
            raise ValueError("impact_digest must be lowercase SHA-256")
        actor = _validated_actor(actor)
        current = self.get_request(novel_id=novel_id, request_id=request_id)
        if current.terminal:
            return current
        if current.state in {"live_deleting", "live_deleted_backup_pending"}:
            return self._execute_and_notify(request_id, actor=actor)
        candidates = _transaction(
            self._session_factory,
            lambda session: self._prepare_confirmation(
                session,
                novel_id=novel_id,
                request_id=request_id,
                expected_profile_version=expected_profile_version,
                impact_digest=impact_digest,
                actor=actor,
            ),
        )
        if isinstance(candidates, VoiceDeletionRequestSnapshot):
            self._notify_state_change()
            return candidates
        identities: dict[UUID, StoredFileIdentity | None] = {}
        try:
            for candidate in candidates:
                identities[candidate.asset_id] = self._storage.capture_media_identity(
                    candidate.storage_path,
                    missing_ok=True,
                )
                identity = identities[candidate.asset_id]
                if identity is not None and identity.byte_size != candidate.byte_size:
                    raise UnsafeStoragePath(
                        "voice deletion media changed before fencing"
                    )
        except UnsafeStoragePath:
            snapshot = _transaction(
                self._session_factory,
                lambda session: self._mark_pre_fence_failure(
                    session,
                    novel_id=novel_id,
                    request_id=request_id,
                    failure_code="VOICE_DELETE_FILE_IDENTITY_INVALID",
                ),
            )
            self._notify_state_change()
            return snapshot
        except (StorageError, OSError):
            # Confirmation is already durable, but no physical fence exists.
            # Keep the request eligible for reconciler retry instead of
            # turning a temporary storage outage into an irreversible safety
            # failure.
            self._notify_state_change()
            raise
        row = _transaction(
            self._session_factory,
            lambda session: self._fence_confirmation(
                session,
                novel_id=novel_id,
                request_id=request_id,
                expected_profile_version=expected_profile_version,
                impact_digest=impact_digest,
                actor=actor,
                candidates=candidates,
                identities=identities,
            ),
        )
        if row.state == "live_deleting":
            return self._execute_and_notify(request_id, actor=actor)
        self._notify_state_change()
        return row

    def retry(
        self,
        *,
        novel_id: UUID,
        request_id: UUID,
        actor: str,
    ) -> VoiceDeletionRequestSnapshot:
        actor = _validated_actor(actor)
        row = self.get_request(novel_id=novel_id, request_id=request_id)
        if row.terminal:
            return row
        if row.state in {"live_deleting", "live_deleted_backup_pending"}:
            return self._execute_and_notify(request_id, actor=actor)
        if row.state != "failed" or not row.retryable:
            raise VoiceDeletionConflict("voice deletion request is not retryable")
        if row.failure_code == WAITING_FOR_JOBS:
            return self.confirm(
                novel_id=novel_id,
                request_id=request_id,
                expected_profile_version=int(row.expected_profile_version or 0),
                impact_digest=row.impact_digest,
                actor=actor,
            )
        resumed = _transaction(
            self._session_factory,
            lambda session: self._resume_failed_request(
                session,
                novel_id=novel_id,
                request_id=request_id,
            ),
        )
        self._notify_state_change()
        if resumed:
            return self._execute_and_notify(request_id, actor=actor)
        return self.confirm(
            novel_id=novel_id,
            request_id=request_id,
            expected_profile_version=row.expected_profile_version,
            impact_digest=row.impact_digest,
            actor=actor,
        )

    def select_reconciliation_batch(
        self,
        *,
        exclude_request_ids: Sequence[UUID] = (),
        limit: int = RECONCILIATION_BATCH_LIMIT,
        now: datetime | None = None,
    ) -> VoiceDeletionReconciliationBatch:
        if type(limit) is not int or not 1 <= limit <= RECONCILIATION_BATCH_LIMIT:
            raise ValueError("voice deletion reconciliation batch must be 1..25")
        if any(type(request_id) is not UUID for request_id in exclude_request_ids):
            raise ValueError("voice deletion reconciliation exclusions must be UUIDs")
        current = now or _utc_now()

        def operation(session: Session) -> VoiceDeletionReconciliationBatch:
            rows = tuple(
                session.scalars(
                    _reconciliation_candidate_statement(
                        current=current,
                        exclude_request_ids=exclude_request_ids,
                        limit=limit,
                    )
                ).all()
            )
            return VoiceDeletionReconciliationBatch(
                request_ids=rows,
                has_more=len(rows) == limit,
            )

        return _transaction(self._session_factory, operation)

    def next_reconciliation_deadline(
        self,
        *,
        now: datetime | None = None,
    ) -> datetime | None:
        current = now or _utc_now()

        def operation(session: Session) -> datetime | None:
            deadlines: list[datetime] = []
            for value in session.scalars(
                select(VoiceDeletionRequest.execute_after).where(
                    VoiceDeletionRequest.owner_id == LOCAL_OWNER_ID,
                    VoiceDeletionRequest.workspace_id == LOCAL_WORKSPACE_ID,
                    VoiceDeletionRequest.state == "grace_pending",
                    VoiceDeletionRequest.execute_after > current,
                )
            ):
                if value is not None:
                    deadlines.append(value)
            for value in session.scalars(
                select(VoiceDeletionRequest.impact_expires_at).where(
                    VoiceDeletionRequest.owner_id == LOCAL_OWNER_ID,
                    VoiceDeletionRequest.workspace_id == LOCAL_WORKSPACE_ID,
                    VoiceDeletionRequest.state.in_({"grace_pending", "requested"}),
                    VoiceDeletionRequest.impact_expires_at > current,
                )
            ):
                if value is not None:
                    deadlines.append(value)
            for value in session.scalars(
                select(VoiceDeletionRequest.job_drain_deadline).where(
                    VoiceDeletionRequest.owner_id == LOCAL_OWNER_ID,
                    VoiceDeletionRequest.workspace_id == LOCAL_WORKSPACE_ID,
                    VoiceDeletionRequest.state == "failed",
                    VoiceDeletionRequest.failure_code == WAITING_FOR_JOBS,
                    VoiceDeletionRequest.job_drain_deadline > current,
                )
            ):
                if value is not None:
                    deadlines.append(value)
            return min(deadlines) if deadlines else None

        return _transaction(self._session_factory, operation)

    def reconcile_request(
        self,
        request_id: UUID,
        *,
        actor: str = "voice-deletion-reconciler",
    ) -> VoiceDeletionRequestSnapshot:
        previous = getattr(self._notification_context, "suppressed", False)
        self._notification_context.suppressed = True
        try:
            return self._reconcile_request_impl(request_id, actor=actor)
        finally:
            self._notification_context.suppressed = previous

    def _reconcile_request_impl(
        self,
        request_id: UUID,
        *,
        actor: str,
    ) -> VoiceDeletionRequestSnapshot:
        actor = _validated_actor(actor)
        current = _transaction(
            self._session_factory,
            lambda session: _request_snapshot(
                _request_by_id(
                    session,
                    request_id,
                    novel_id=None,
                    for_update=False,
                )
            ),
        )
        if current.terminal:
            return current
        if current.state == "grace_pending":
            if current.execute_after is not None and current.server_now < current.execute_after:
                return current
            return self.confirm(
                novel_id=current.novel_id,
                request_id=current.request_id,
                expected_profile_version=current.expected_profile_version,
                impact_digest=current.impact_digest,
                actor=actor,
            )
        if current.state == "requested":
            if (
                current.confirmed_at is None
                and current.impact_expires_at is not None
                and current.server_now < current.impact_expires_at
            ):
                return current
            return self.confirm(
                novel_id=current.novel_id,
                request_id=current.request_id,
                expected_profile_version=current.expected_profile_version,
                impact_digest=current.impact_digest,
                actor=actor,
            )
        if current.state == "failed" and current.retryable:
            return self.retry(
                novel_id=current.novel_id,
                request_id=current.request_id,
                actor=actor,
            )
        if current.state in {"live_deleting", "live_deleted_backup_pending"}:
            return self._execute_and_notify(request_id, actor=actor)
        return current

    def _supersede(
        self,
        session: Session,
        row: VoiceDeletionRequest,
        *,
        failure_code: str,
        now: datetime,
    ) -> VoiceDeletionRequestSnapshot:
        if failure_code not in SUPERSEDED_FAILURE_CODES:
            raise ValueError("invalid voice deletion superseded failure code")
        if row.state in TERMINAL_REQUEST_STATES:
            return _request_snapshot(row, now=now)
        if _count(
            session,
            VoiceDeletionAssetPlan,
            VoiceDeletionAssetPlan.deletion_request_id == row.id,
        ):
            raise VoiceDeletionConflict(
                "fenced voice deletion cannot be superseded"
            )
        row.state = "superseded"
        row.failure_code = failure_code
        row.superseded_at = now
        row.updated_at = now
        session.flush([row])
        return _request_snapshot(row, now=now)

    def _mark_pre_fence_failure(
        self,
        session: Session,
        *,
        novel_id: UUID,
        request_id: UUID,
        failure_code: str,
    ) -> VoiceDeletionRequestSnapshot:
        if failure_code not in NON_RETRYABLE_SAFETY_FAILURE_CODES:
            raise ValueError("invalid pre-fence voice deletion failure code")
        row = _request_by_id(
            session,
            request_id,
            novel_id=novel_id,
            for_update=True,
        )
        now = _utc_now()
        if row.state in TERMINAL_REQUEST_STATES:
            return _request_snapshot(row, now=now)
        if _count(
            session,
            VoiceDeletionAssetPlan,
            VoiceDeletionAssetPlan.deletion_request_id == row.id,
        ):
            raise VoiceDeletionConflict("voice deletion already crossed its physical fence")
        row.state = "failed"
        row.failure_code = failure_code
        row.updated_at = now
        session.flush([row])
        return _request_snapshot(row, now=now)

    def _prepare_confirmation(
        self,
        session: Session,
        *,
        novel_id: UUID,
        request_id: UUID,
        expected_profile_version: int,
        impact_digest: str,
        actor: str,
    ) -> tuple[_AssetCandidate, ...] | VoiceDeletionRequestSnapshot:
        _require_local_novel(session, novel_id, for_update=False)
        row = _request_by_id(
            session,
            request_id,
            novel_id=novel_id,
            for_update=True,
        )
        now = _utc_now()
        if row.state in TERMINAL_REQUEST_STATES:
            return _request_snapshot(row, now=now)
        if row.state in {"live_deleting", "live_deleted_backup_pending"}:
            raise VoiceDeletionConflict("voice deletion request cannot be confirmed")
        if row.state == "grace_pending" and row.execute_after is not None:
            if now < row.execute_after:
                raise VoiceDeletionConflict("unreferenced voice is still inside its undo window")
        if row.state == "failed" and row.failure_code != WAITING_FOR_JOBS:
            raise VoiceDeletionConflict("failed physical deletion must use retry")
        if row.expected_profile_version != expected_profile_version:
            raise NarrationCasConflict("voice deletion request CAS does not match")
        if row.impact_digest != impact_digest:
            raise NarrationCasConflict("voice deletion impact digest does not match")
        try:
            profile, _versions = _profile_and_versions(
                session,
                novel_id,
                row.voice_profile_id,
                for_update=True,
            )
        except NarrationScopeMismatch:
            return self._mark_pre_fence_failure(
                session,
                novel_id=novel_id,
                request_id=request_id,
                failure_code="VOICE_DELETE_SCOPE_INVALID",
            )
        except VoiceDeletionConflict:
            return self._supersede(
                session,
                row,
                failure_code="VOICE_DELETE_IMPACT_CHANGED",
                now=now,
            )
        if profile.version != row.expected_profile_version:
            return self._supersede(
                session,
                row,
                failure_code="VOICE_DELETE_PROFILE_CHANGED",
                now=now,
            )
        drain_deadline = getattr(row, "job_drain_deadline", None)
        if (
            row.failure_code == WAITING_FOR_JOBS
            and drain_deadline is not None
            and now >= drain_deadline
        ):
            return self._supersede(
                session,
                row,
                failure_code="VOICE_DELETE_JOB_DRAIN_TIMEOUT",
                now=now,
            )
        if row.impact_expires_at is None or now >= row.impact_expires_at:
            return self._supersede(
                session,
                row,
                failure_code="VOICE_DELETE_IMPACT_EXPIRED",
                now=now,
            )
        try:
            impact = compute_voice_deletion_impact(
                session,
                novel_id,
                profile.id,
                for_update=False,
            )
        except (VoiceDeletionConflict, NarrationScopeMismatch):
            return self._supersede(
                session,
                row,
                failure_code="VOICE_DELETE_IMPACT_CHANGED",
                now=now,
            )
        exact_impact = self._digest_keyring.verify(
            row.impact_digest_key_id,
            _canonical_bytes(impact.payload()),
            row.impact_digest,
        )
        waiting_job_drain = _matches_confirmed_waiting_job_impact(row, impact)
        if not (exact_impact or waiting_job_drain):
            return self._supersede(
                session,
                row,
                failure_code="VOICE_DELETE_IMPACT_CHANGED",
                now=now,
            )
        if row.confirmed_at is None:
            row.confirmed_actor = actor
            row.confirmed_at = now
        if impact.active_job_ids:
            if getattr(row, "job_drain_started_at", None) is None:
                row.job_drain_started_at = now
                row.job_drain_deadline = min(
                    now + JOB_DRAIN_TIMEOUT,
                    row.impact_expires_at,
                )
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
            row.failure_code = WAITING_FOR_JOBS
            row.updated_at = now
            session.flush()
            return _request_snapshot(row, now=now)
        try:
            assets = self._asset_candidates(session, impact)
        except VoiceDeletionConflict:
            return self._supersede(
                session,
                row,
                failure_code="VOICE_DELETE_IMPACT_CHANGED",
                now=now,
            )
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
        novel_id: UUID,
        request_id: UUID,
        expected_profile_version: int,
        impact_digest: str,
        actor: str,
        candidates: tuple[_AssetCandidate, ...],
        identities: dict[UUID, StoredFileIdentity | None],
    ) -> VoiceDeletionRequestSnapshot:
        row = _request_by_id(
            session,
            request_id,
            novel_id=novel_id,
            for_update=True,
        )
        now = _utc_now()
        if row.state in TERMINAL_REQUEST_STATES:
            return _request_snapshot(row, now=now)
        try:
            profile, versions = _profile_and_versions(
                session,
                novel_id,
                row.voice_profile_id,
                for_update=True,
            )
        except NarrationScopeMismatch:
            return self._mark_pre_fence_failure(
                session,
                novel_id=novel_id,
                request_id=request_id,
                failure_code="VOICE_DELETE_SCOPE_INVALID",
            )
        except VoiceDeletionConflict:
            return self._supersede(
                session,
                row,
                failure_code="VOICE_DELETE_IMPACT_CHANGED",
                now=now,
            )
        if row.state == "live_deleting":
            return _request_snapshot(row, now=now)
        if row.state not in {"requested", "grace_pending", "failed"}:
            raise VoiceDeletionConflict("voice deletion request changed before fencing")
        if (
            row.expected_profile_version != expected_profile_version
            or row.impact_digest != impact_digest
        ):
            raise NarrationCasConflict("voice deletion request CAS changed")
        if profile.version != row.expected_profile_version:
            return self._supersede(
                session,
                row,
                failure_code="VOICE_DELETE_PROFILE_CHANGED",
                now=now,
            )
        drain_deadline = getattr(row, "job_drain_deadline", None)
        if (
            row.failure_code == WAITING_FOR_JOBS
            and drain_deadline is not None
            and now >= drain_deadline
        ):
            return self._supersede(
                session,
                row,
                failure_code="VOICE_DELETE_JOB_DRAIN_TIMEOUT",
                now=now,
            )
        if row.impact_expires_at is None or now >= row.impact_expires_at:
            return self._supersede(
                session,
                row,
                failure_code="VOICE_DELETE_IMPACT_EXPIRED",
                now=now,
            )
        try:
            impact = compute_voice_deletion_impact(
                session,
                novel_id,
                profile.id,
                for_update=False,
            )
        except (VoiceDeletionConflict, NarrationScopeMismatch):
            return self._supersede(
                session,
                row,
                failure_code="VOICE_DELETE_IMPACT_CHANGED",
                now=now,
            )
        exact_impact = self._digest_keyring.verify(
            row.impact_digest_key_id,
            _canonical_bytes(impact.payload()),
            row.impact_digest,
        )
        if (
            not exact_impact
            and not _matches_confirmed_waiting_job_impact(row, impact)
        ) or impact.active_job_ids:
            return self._supersede(
                session,
                row,
                failure_code="VOICE_DELETE_IMPACT_CHANGED",
                now=now,
            )
        try:
            current_candidates = self._asset_candidates(session, impact)
        except VoiceDeletionConflict:
            return self._supersede(
                session,
                row,
                failure_code="VOICE_DELETE_IMPACT_CHANGED",
                now=now,
            )
        if current_candidates != candidates:
            return self._supersede(
                session,
                row,
                failure_code="VOICE_DELETE_IMPACT_CHANGED",
                now=now,
            )
        if set(identities) != {candidate.asset_id for candidate in candidates}:
            return self._mark_pre_fence_failure(
                session,
                novel_id=novel_id,
                request_id=request_id,
                failure_code="VOICE_DELETE_ASSET_PLAN_INVALID",
            )
        for candidate in candidates:
            asset = session.scalar(
                select(MediaAsset)
                .where(MediaAsset.id == candidate.asset_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if asset is None or asset.state not in {"ready", "staging"}:
                return self._supersede(
                    session,
                    row,
                    failure_code="VOICE_DELETE_IMPACT_CHANGED",
                    now=now,
                )
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
        return _request_snapshot(row, now=now)

    def _execute_and_notify(
        self,
        request_id: UUID,
        *,
        actor: str,
    ) -> VoiceDeletionRequestSnapshot:
        try:
            snapshot = self._execute_plans(request_id, actor=actor)
        except Exception:
            self._notify_state_change()
            raise
        self._notify_state_change()
        return snapshot

    @staticmethod
    def _execution_failure_code(error: Exception, *, phase: str) -> str:
        if isinstance(error, NarrationScopeMismatch):
            return "VOICE_DELETE_SCOPE_INVALID"
        if isinstance(error, UnsafeStoragePath):
            return "VOICE_DELETE_FILE_IDENTITY_INVALID"
        if isinstance(
            error,
            (
                PublicationValidationError,
                VoiceDeletionConflict,
                VoiceDeletionNotFound,
                MediaConflict,
                MediaPolicyError,
            ),
        ):
            return "VOICE_DELETE_ASSET_PLAN_INVALID"
        if isinstance(error, StorageError):
            return "VOICE_DELETE_STORAGE_TEMPORARY"
        if phase == "finalize":
            return "VOICE_DELETE_FINALIZE_FAILED"
        return "VOICE_DELETE_UNLINK_FAILED"

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
            except Exception as error:
                failure_code = self._execution_failure_code(error, phase="plan")
                _transaction(
                    self._session_factory,
                    lambda session, plan_id=plan_id, failure_code=failure_code: self._mark_plan_failed(
                        session,
                        request_id=request_id,
                        plan_id=plan_id,
                        failure_code=failure_code,
                    ),
                )
                raise
            try:
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
            except Exception as error:
                failure_code = self._execution_failure_code(error, phase="unlink")
                _transaction(
                    self._session_factory,
                    lambda session, plan_id=plan_id, failure_code=failure_code: self._mark_plan_failed(
                        session,
                        request_id=request_id,
                        plan_id=plan_id,
                        failure_code=failure_code,
                    ),
                )
                raise
            try:
                _transaction(
                    self._session_factory,
                    lambda session, plan_id=plan_id: self._finalize_unlinked(
                        session,
                        plan_id=plan_id,
                        actor=actor,
                    ),
                )
            except Exception as error:
                failure_code = self._execution_failure_code(error, phase="finalize")
                _transaction(
                    self._session_factory,
                    lambda session, plan_id=plan_id, failure_code=failure_code: self._mark_plan_failed(
                        session,
                        request_id=request_id,
                        plan_id=plan_id,
                        failure_code=failure_code,
                    ),
                )
                raise
        try:
            return _transaction(
                self._session_factory,
                lambda session: self._complete_request(session, request_id),
            )
        except Exception as error:
            failure_code = self._execution_failure_code(error, phase="finalize")
            _transaction(
                self._session_factory,
                lambda session: self._mark_request_failed(
                    session,
                    request_id=request_id,
                    failure_code=failure_code,
                ),
            )
            raise

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
        request = _request_by_id(
            session,
            plan.deletion_request_id,
            novel_id=None,
            for_update=True,
        )
        if request.state != "live_deleting":
            raise VoiceDeletionConflict("voice deletion request is not inside its fence")
        if (
            plan.owner_id != request.owner_id
            or plan.workspace_id != request.workspace_id
            or plan.novel_id != request.novel_id
        ):
            raise NarrationScopeMismatch("voice deletion asset plan scope changed")
        if (
            plan.storage_backend != "local"
            or re.fullmatch(r"[0-9a-f]{64}", plan.content_hash) is None
            or plan.byte_size < 0
            or plan.gc_generation < 0
            or plan.file_present != (plan.device is not None and plan.inode is not None)
        ):
            raise VoiceDeletionConflict("voice deletion asset plan identity is invalid")
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
        asset = session.scalar(
            select(MediaAsset)
            .where(MediaAsset.id == plan.asset_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if asset is None:
            raise VoiceDeletionConflict("voice deletion asset plan lost its media row")
        if (
            asset.owner_id != plan.owner_id
            or asset.workspace_id != plan.workspace_id
            or asset.novel_id != plan.novel_id
        ):
            raise NarrationScopeMismatch("voice deletion media scope changed")
        if (
            asset.storage_backend != plan.storage_backend
            or asset.storage_path != plan.storage_path
            or asset.content_hash != plan.content_hash
            or int(asset.byte_size or 0) != plan.byte_size
            or asset.gc_generation != plan.gc_generation
            or asset.state != "deleting"
        ):
            raise VoiceDeletionConflict("voice deletion media no longer matches its frozen plan")
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

    def _mark_plan_failed(
        self,
        session: Session,
        *,
        request_id: UUID,
        plan_id: UUID,
        failure_code: str,
    ) -> None:
        if failure_code not in (
            POST_FENCE_RETRYABLE_FAILURE_CODES | NON_RETRYABLE_SAFETY_FAILURE_CODES
        ):
            raise ValueError("invalid voice deletion execution failure code")
        plan = session.scalar(
            select(VoiceDeletionAssetPlan)
            .where(VoiceDeletionAssetPlan.id == plan_id)
            .with_for_update()
        )
        request = _request_by_id(
            session,
            request_id,
            novel_id=None,
            for_update=True,
        )
        if plan is not None and plan.deletion_request_id != request.id:
            failure_code = "VOICE_DELETE_ASSET_PLAN_INVALID"
        if plan is not None and plan.state != "finalized":
            plan.state = "failed"
            plan.failure_code = failure_code
        if request.state in TERMINAL_REQUEST_STATES:
            return
        request.state = "failed"
        request.failure_code = failure_code
        request.updated_at = _utc_now()
        session.flush()

    def _mark_request_failed(
        self,
        session: Session,
        *,
        request_id: UUID,
        failure_code: str,
    ) -> None:
        row = _request_by_id(
            session,
            request_id,
            novel_id=None,
            for_update=True,
        )
        if row.state in TERMINAL_REQUEST_STATES:
            return
        row.state = "failed"
        row.failure_code = failure_code
        row.updated_at = _utc_now()
        session.flush([row])

    def _complete_request(
        self, session: Session, request_id: UUID
    ) -> VoiceDeletionRequestSnapshot:
        row = _request_by_id(
            session,
            request_id,
            novel_id=None,
            for_update=True,
        )
        if row.state == "completed":
            return _request_snapshot(row)
        if row.state not in {"live_deleting", "live_deleted_backup_pending"}:
            raise VoiceDeletionConflict(
                "voice deletion request cannot complete before its physical fence"
            )
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
        return _request_snapshot(row, now=now)

    def _resume_failed_request(
        self,
        session: Session,
        *,
        novel_id: UUID,
        request_id: UUID,
    ) -> bool:
        row = _request_by_id(
            session,
            request_id,
            novel_id=novel_id,
            for_update=True,
        )
        if row.state != "failed" or row.failure_code not in POST_FENCE_RETRYABLE_FAILURE_CODES:
            raise VoiceDeletionConflict("voice deletion request is not physically retryable")
        plans = tuple(
            session.scalars(
                select(VoiceDeletionAssetPlan)
                .where(VoiceDeletionAssetPlan.deletion_request_id == request_id)
                .order_by(VoiceDeletionAssetPlan.asset_id)
                .with_for_update()
            ).all()
        )
        if len(plans) != row.asset_count:
            row.failure_code = "VOICE_DELETE_ASSET_PLAN_INVALID"
            row.updated_at = _utc_now()
            session.flush([row])
            return False
        if any(
            plan.owner_id != row.owner_id
            or plan.workspace_id != row.workspace_id
            or plan.novel_id != row.novel_id
            or plan.storage_backend != "local"
            for plan in plans
        ):
            row.failure_code = "VOICE_DELETE_SCOPE_INVALID"
            row.updated_at = _utc_now()
            session.flush([row])
            return False
        try:
            invalid_identity = any(
                re.fullmatch(r"[0-9a-f]{64}", plan.content_hash) is None
                or plan.byte_size < 0
                or plan.gc_generation < 0
                or plan.file_present != (plan.device is not None and plan.inode is not None)
                or plan.state
                not in {"planned", "unlinking", "unlinked", "finalized", "failed"}
                or not validate_relative_path(plan.storage_path)
                for plan in plans
            )
        except (StorageError, ValueError, TypeError):
            invalid_identity = True
        if invalid_identity:
            row.failure_code = "VOICE_DELETE_ASSET_PLAN_INVALID"
            row.updated_at = _utc_now()
            session.flush([row])
            return False
        assets_by_id = {
            asset.id: asset
            for asset in session.scalars(
                select(MediaAsset).where(
                    MediaAsset.id.in_(tuple(plan.asset_id for plan in plans))
                )
            )
        }
        if len(assets_by_id) != len(plans) or any(
            (
                asset := assets_by_id.get(plan.asset_id)
            ) is None
            or asset.storage_backend != plan.storage_backend
            or asset.storage_path != plan.storage_path
            or asset.content_hash != plan.content_hash
            or int(asset.byte_size or 0) != plan.byte_size
            or asset.gc_generation != plan.gc_generation
            or (
                plan.state == "finalized"
                and asset.state != "deleted"
            )
            or (
                plan.state != "finalized"
                and asset.state != "deleting"
            )
            for plan in plans
        ):
            row.failure_code = "VOICE_DELETE_ASSET_PLAN_INVALID"
            row.updated_at = _utc_now()
            session.flush([row])
            return False
        row.state = "live_deleting"
        row.failure_code = None
        row.updated_at = _utc_now()
        session.flush([row])
        return True


__all__ = [
    "VoiceDeletionConflict",
    "VoiceDeletionImpact",
    "VoiceDeletionNotFound",
    "VoiceDeletionRequestSnapshot",
    "VoiceDeletionService",
    "compute_voice_deletion_impact",
]
