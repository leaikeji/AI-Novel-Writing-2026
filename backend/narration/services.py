"""Shared persistence boundary and fail-closed errors for narration services.

The caller owns the transaction.  Service functions flush their writes but never
commit and never perform model, network, or media I/O.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any, Protocol, TypeVar
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    BackgroundJob,
    Novel,
    VoiceProfile,
    VoiceProfileVersion,
    VoiceRightsEvent,
    VoiceRightsRecord,
)

from .contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID, NarrationRequestScope
from .fingerprints import canonical_json_bytes
from .jobs import JobFence, PublicationFenceContext
from .official_presets import (
    OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256,
    validate_official_version_evidence,
)


T = TypeVar("T")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")


class NarrationServiceError(RuntimeError):
    """Base error safe for API/worker adapters to classify."""


class NarrationNotFound(NarrationServiceError):
    pass


class NarrationScopeMismatch(NarrationServiceError):
    pass


class IdempotencyConflict(NarrationServiceError):
    pass


class InvalidNarrationState(NarrationServiceError):
    pass


class StaleNarrationInput(NarrationServiceError):
    pass


class VoiceRightsUnavailable(NarrationServiceError):
    pass


class NarrationCasConflict(NarrationServiceError):
    pass


class ManifestRevisionCollision(NarrationServiceError):
    pass


class NarrationStore(Protocol):
    """Narrow persistence interface used by domain services and unit fakes."""

    def add(self, row: object) -> None: ...

    def flush(self) -> None: ...

    def get(self, model: type[T], row_id: object, *, for_update: bool = False) -> T | None: ...

    def find_one(
        self, model: type[T], *, for_update: bool = False, **filters: object
    ) -> T | None: ...

    def find_all(
        self,
        model: type[T],
        *,
        order_by: tuple[str, ...] = (),
        for_update: bool = False,
        **filters: object,
    ) -> list[T]: ...

    def consume_render_publication_context(
        self,
        *,
        publication_context: PublicationFenceContext,
        source_job_id: UUID,
        request_id: UUID,
        novel_id: UUID,
        actual_result_digest: str,
    ) -> None: ...


class SqlAlchemyNarrationStore:
    """Production adapter over the existing SQLAlchemy transaction/session."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, row: object) -> None:
        self.session.add(row)

    def flush(self) -> None:
        self.session.flush()

    def get(self, model: type[T], row_id: object, *, for_update: bool = False) -> T | None:
        statement = select(model).where(model.id == row_id)  # type: ignore[attr-defined]
        if for_update:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        return self.session.scalar(statement)

    def find_one(
        self, model: type[T], *, for_update: bool = False, **filters: object
    ) -> T | None:
        statement = select(model).filter_by(**filters)
        if for_update:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        return self.session.scalar(statement)

    def find_all(
        self,
        model: type[T],
        *,
        order_by: tuple[str, ...] = (),
        for_update: bool = False,
        **filters: object,
    ) -> list[T]:
        statement = select(model).filter_by(**filters)
        if order_by:
            statement = statement.order_by(*(getattr(model, name) for name in order_by))
        if for_update:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        return list(self.session.scalars(statement))

    def consume_render_publication_context(
        self,
        *,
        publication_context: PublicationFenceContext,
        source_job_id: UUID,
        request_id: UUID,
        novel_id: UUID,
        actual_result_digest: str,
    ) -> None:
        """Consume a T1-C context acquired earlier in this exact transaction."""

        from .jobs import complete_attempt

        if type(publication_context) is not PublicationFenceContext:
            raise InvalidNarrationState(
                "render result requires a transaction-bound publication context"
            )
        job_fence = publication_context.job_lease.fence
        if type(job_fence) is not JobFence or job_fence.job_id != source_job_id:
            raise InvalidNarrationState("render result fence names another source job")
        digest = require_sha256(actual_result_digest, field="actual_result_digest")
        scope = NarrationRequestScope.fixed_local()
        job = self.session.scalar(
            select(BackgroundJob)
            .where(
                BackgroundJob.id == source_job_id,
                BackgroundJob.owner_id == scope.owner_id,
                BackgroundJob.workspace_id == scope.workspace_id,
            )
            .with_for_update()
        )
        if job is None:
            raise NarrationNotFound("render source job not found")
        if (
            job.job_kind != "narration.segment_render"
            or job.request_id != request_id
            or job.novel_id != novel_id
        ):
            raise NarrationScopeMismatch("render result fence provenance mismatch")
        complete_attempt(
            self.session,
            scope=scope,
            fence=job_fence,
            actual_result_digest=digest,
            publication_context=publication_context,
        )


def utc_now() -> datetime:
    return datetime.now(UTC)


def canonical_sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def canonical_payload(payload: Any) -> Any:
    """Return the normalized JSON value whose bytes are fingerprinted."""

    return json.loads(canonical_json_bytes(payload))


def require_sha256(value: str, *, field: str) -> str:
    if type(value) is not str or not _SHA256.fullmatch(value):
        raise NarrationServiceError(f"{field} must be a lowercase SHA-256")
    return value


def require_nonempty(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NarrationServiceError(f"{field} must be non-empty")
    return value


def require_exact_bool(value: bool, *, field: str) -> bool:
    if type(value) is not bool:
        raise NarrationServiceError(f"{field} must be an exact boolean")
    return value


def require_exact_int(
    value: int,
    *,
    field: str,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if type(value) is not int:
        raise NarrationServiceError(f"{field} must be an exact integer")
    if minimum is not None and value < minimum:
        raise NarrationServiceError(f"{field} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise NarrationServiceError(f"{field} must be <= {maximum}")
    return value


def require_fixed_scope(scope: NarrationRequestScope) -> NarrationRequestScope:
    scope.ensure_fixed_local()
    return scope


def require_local_novel(
    store: NarrationStore, novel_id: UUID, *, for_update: bool = False
) -> Novel:
    novel = store.get(Novel, novel_id, for_update=for_update)
    if novel is None:
        raise NarrationNotFound("novel not found")
    if novel.owner_id != LOCAL_OWNER_ID or novel.workspace_id != LOCAL_WORKSPACE_ID:
        raise NarrationScopeMismatch("novel is outside the fixed local narration scope")
    return novel


def require_row(row: T | None, *, label: str) -> T:
    if row is None:
        raise NarrationNotFound(f"{label} not found")
    return row


def require_same_novel(actual: UUID | None, expected: UUID, *, label: str) -> None:
    if actual != expected:
        raise NarrationScopeMismatch(f"{label} belongs to another novel")


def voice_activation_evidence_is_usable(
    version: VoiceProfileVersion,
    rights: VoiceRightsRecord,
) -> bool:
    """Apply the one fail-closed activation/evidence policy to a voice pair."""

    human_confirmed = (
        version.activation_basis == "preview_confirmed"
        and version.validation_basis == "human_accepted"
        and version.quality_state == "accepted"
        and version.locked_actor is not None
        and version.locked_at is not None
    )
    official_direct = (
        version.source_type == "preset"
        and rights.source_kind == "official_preset"
        and version.activation_basis == "explicit_official_preset_selection"
        and version.validation_basis == "not_required"
        and version.quality_state == "pending"
        and version.locked_actor is None
        and version.locked_at is None
    )
    if not (human_confirmed or official_direct):
        return False
    if rights.source_kind == "official_preset":
        try:
            validate_official_version_evidence(
                version,
                rights,
                expected_model_fingerprint=(
                    OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256
                ),
            )
        except ValueError:
            return False
    return True


def require_usable_voice(
    store: NarrationStore,
    voice_version_id: UUID,
    *,
    novel_id: UUID,
    at: datetime | None = None,
) -> tuple[VoiceProfile, VoiceProfileVersion, VoiceRightsRecord]:
    """Recheck current locked voice scope and conservative negative rights history."""

    now = at or utc_now()
    version = require_row(
        store.get(VoiceProfileVersion, voice_version_id, for_update=True),
        label="voice version",
    )
    profile = require_row(
        store.get(VoiceProfile, version.profile_id, for_update=True),
        label="voice profile",
    )
    if profile.owner_id != LOCAL_OWNER_ID or profile.workspace_id != LOCAL_WORKSPACE_ID:
        raise NarrationScopeMismatch("voice profile is outside fixed local scope")
    if version.owner_id != profile.owner_id or version.workspace_id != profile.workspace_id:
        raise NarrationScopeMismatch("voice version/profile scope mismatch")
    if profile.novel_id not in {None, novel_id}:
        raise NarrationScopeMismatch("private voice profile belongs to another novel")
    if profile.status != "active":
        raise VoiceRightsUnavailable("voice profile is not active")
    if version.state != "locked":
        raise VoiceRightsUnavailable("voice version is not locked")
    rights = require_row(
        store.get(VoiceRightsRecord, version.rights_record_id, for_update=True),
        label="voice rights record",
    )
    if rights.owner_id != profile.owner_id or rights.workspace_id != profile.workspace_id:
        raise NarrationScopeMismatch("voice rights scope mismatch")
    if rights.novel_id not in {None, novel_id}:
        raise NarrationScopeMismatch("voice rights belong to another novel")
    if not voice_activation_evidence_is_usable(version, rights):
        raise VoiceRightsUnavailable("voice version activation evidence is unusable")
    if version.source_type == "uploaded" and not rights.voice_cloning:
        raise VoiceRightsUnavailable("uploaded voice has no cloning permission")
    if rights.expires_at is not None and rights.expires_at <= now:
        raise VoiceRightsUnavailable("voice rights expired")
    if any(
        event.event_type in {"revoked", "expired", "review_blocked"}
        for event in store.find_all(
            VoiceRightsEvent,
            rights_record_id=rights.id,
            for_update=True,
        )
    ):
        raise VoiceRightsUnavailable("voice rights have negative history")
    return profile, version, rights


__all__ = [
    "IdempotencyConflict",
    "InvalidNarrationState",
    "ManifestRevisionCollision",
    "NarrationCasConflict",
    "NarrationNotFound",
    "NarrationScopeMismatch",
    "NarrationServiceError",
    "NarrationStore",
    "SqlAlchemyNarrationStore",
    "StaleNarrationInput",
    "VoiceRightsUnavailable",
    "canonical_sha256",
    "canonical_payload",
    "require_exact_bool",
    "require_exact_int",
    "require_fixed_scope",
    "require_local_novel",
    "require_nonempty",
    "require_row",
    "require_same_novel",
    "require_sha256",
    "require_usable_voice",
    "utc_now",
    "voice_activation_evidence_is_usable",
]
