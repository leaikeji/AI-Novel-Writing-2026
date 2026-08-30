"""PostgreSQL, Sidecar and binding adapter for validated Nano experiments.

The domain orchestration lives in :mod:`nano_experiments`.  This module owns
the short SQLAlchemy transactions, immutable media publication and the one
shared production worker integration.  Synthesis is always outside a database
transaction; publication, ModelRun evidence, machine validation and target CAS
application commit atomically.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hmac
from typing import Callable, Final, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ..models import (
    BackgroundJob,
    CharacterVoiceBinding,
    MediaAsset,
    ModelRunRecord,
    NanoVoiceExperimentCommand as NanoVoiceExperimentCommandRow,
    NovelNarrationSettings,
    VoicePreview,
    VoiceDeletionRequest,
    VoiceProfile,
    VoiceProfileVersion,
)
from . import schemas as wire
from .adapters import MossNanoTTSAdapter
from .audio_pipeline import process_synthesis_wav
from .contracts import NarrationRequestScope, SynthesisRequest
from .digest_keyring import DigestKeyring, historical_private_text_digest
from .fingerprints import model_fingerprint_sha256
from .jobs import (
    JobLease,
    complete_attempt,
    enqueue_job,
    fail_attempt,
    heartbeat_attempt,
    lock_result_publish_fences,
)
from .media import release_active_job_assets_in_session
from .nano_experiments import (
    NANO_EXPERIMENT_VALIDATION_TEXT,
    NanoDecodeParametersV3,
    NanoExperimentApplyRequest,
    NanoExperimentCommand,
    NanoExperimentContractError,
    NanoExperimentFailure,
    NanoExperimentIntent,
    NanoExperimentModelIdentity,
    NanoExperimentReservation,
    NanoExperimentStateError,
    NanoExperimentSynthesisRequest,
    NanoExperimentSynthesisResult,
    NanoExperimentTarget,
    NanoExperimentValidationInput,
    NanoExperimentWorkItem,
    NanoExperimentWorkerOutcome,
    NanoModelRunEvidence,
    NanoReusableVersion,
    NanoValidatedEvidence,
    ensure_idempotent_request,
    ensure_state_transition,
    production_nano_experiment_identity,
    validate_nano_experiment_version_evidence,
    validate_reusable_version,
)
from .official_presets import (
    OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256,
    require_official_preset,
)
from .privacy import (
    _require_character,
    _storage_settings,
    get_character_voice_binding,
    get_narration_settings,
    put_character_voice_binding,
)
from .runtime import PROTOCOL_VERSION, canonical_sidecar_synthesis_metadata
from .services import (
    InvalidNarrationState,
    NarrationCasConflict,
    NarrationNotFound,
    NarrationScopeMismatch,
    SqlAlchemyNarrationStore,
    require_local_novel,
)
from .settings import NarrationSettingsUpdate, update_settings
from .storage import NarrationStorage
from .voice_product import (
    MAX_PREVIEW_MEDIA_BYTES,
    VOICE_PREVIEW_JOB_KIND,
    VOICE_PREVIEW_RESOURCE_CLASS,
    VOICE_PREVIEW_TEXT_PURPOSE,
    VoicePreviewPolicy,
    _child_uuid,
    _db_now,
    _model_input_digest,
    _published_or_adopted,
    _transaction,
    build_official_preset_version_rows,
)


SessionFactory = Callable[[], Session]
EXPERIMENT_VERSION_SCHEMA_VERSION: Final = "narration-nano-experiment-version/1"
EXPERIMENT_ACTOR: Final = "local-owner"
EXPERIMENT_PREVIEW_TTL_SECONDS: Final = 24 * 60 * 60

_RETRYABLE_FAILURES: Final[frozenset[str]] = frozenset(
    {
        "NANO_EXPERIMENT_MODEL_UNAVAILABLE",
        "NANO_EXPERIMENT_SYNTHESIS_FAILED",
        "NANO_EXPERIMENT_DATABASE_FAILED",
    }
)


def _aware(value: datetime | None, *, field_name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidNarrationState(f"{field_name} is not timezone-aware")
    return value.astimezone(timezone.utc)


def _command(row: NanoVoiceExperimentCommandRow) -> NanoExperimentCommand:
    parameters = NanoDecodeParametersV3.from_payload(row.parameters_json)
    target = NanoExperimentTarget(
        target_kind=row.target_kind,  # type: ignore[arg-type]
        character_id=row.target_character_id,
        expected_settings_version=int(row.expected_settings_version),
        expected_binding_version=(
            int(row.expected_binding_version)
            if row.expected_binding_version is not None
            else None
        ),
    )
    return NanoExperimentCommand(
        command_id=row.id,
        novel_id=row.novel_id,
        profile_id=row.profile_id,
        version_id=row.version_id,
        preview_id=row.preview_id,
        background_job_id=row.background_job_id,
        base_preset_id=row.base_preset_id,
        target=target,
        parameters=parameters,
        parameters_digest=row.parameters_digest,
        fingerprint=row.fingerprint,
        request_digest=row.request_hash,
        state=row.state,  # type: ignore[arg-type]
        reused_version=bool(row.reused_version),
        failure_code=row.failure_code,
        retryable=row.failure_code in _RETRYABLE_FAILURES,
        created_at=_aware(row.created_at, field_name="created_at"),  # type: ignore[arg-type]
        started_at=_aware(row.started_at, field_name="started_at"),
        completed_at=_aware(row.completed_at, field_name="completed_at"),
    )


def _command_row(
    session: Session,
    *,
    command_id: UUID | None = None,
    job_id: UUID | None = None,
    novel_id: UUID | None = None,
    for_update: bool,
) -> NanoVoiceExperimentCommandRow:
    if (command_id is None) == (job_id is None):
        raise ValueError("exactly one Nano experiment lookup identity is required")
    statement = select(NanoVoiceExperimentCommandRow).where(
        NanoVoiceExperimentCommandRow.owner_id
        == NarrationRequestScope.fixed_local().owner_id,
        NanoVoiceExperimentCommandRow.workspace_id
        == NarrationRequestScope.fixed_local().workspace_id,
    )
    statement = statement.where(
        NanoVoiceExperimentCommandRow.id == command_id
        if command_id is not None
        else NanoVoiceExperimentCommandRow.background_job_id == job_id
    )
    if novel_id is not None:
        statement = statement.where(NanoVoiceExperimentCommandRow.novel_id == novel_id)
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    row = session.scalar(statement)
    if row is None:
        raise NarrationNotFound("Nano experiment command not found")
    return row


def _profile_row(
    session: Session, profile_id: UUID, *, novel_id: UUID, for_update: bool
) -> VoiceProfile:
    statement = select(VoiceProfile).where(VoiceProfile.id == profile_id)
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    profile = session.scalar(statement)
    scope = NarrationRequestScope.fixed_local()
    if profile is None:
        raise NarrationNotFound("Nano experiment profile not found")
    if (
        profile.owner_id != scope.owner_id
        or profile.workspace_id != scope.workspace_id
        or profile.novel_id != novel_id
    ):
        raise NarrationScopeMismatch("Nano experiment profile left its novel scope")
    return profile


def _version_row(
    session: Session,
    *,
    profile_id: UUID,
    version_id: UUID,
    for_update: bool,
) -> VoiceProfileVersion:
    statement = select(VoiceProfileVersion).where(
        VoiceProfileVersion.id == version_id,
        VoiceProfileVersion.profile_id == profile_id,
    )
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    version = session.scalar(statement)
    if version is None:
        raise NarrationNotFound("Nano experiment version not found")
    return version


def _preview_row(
    session: Session, preview_id: UUID, *, for_update: bool
) -> VoicePreview:
    statement = select(VoicePreview).where(VoicePreview.id == preview_id)
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    preview = session.scalar(statement)
    if preview is None:
        raise NarrationNotFound("Nano experiment preview not found")
    return preview


def _job_row(session: Session, job_id: UUID, *, for_update: bool) -> BackgroundJob:
    statement = select(BackgroundJob).where(BackgroundJob.id == job_id)
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    job = session.scalar(statement)
    scope = NarrationRequestScope.fixed_local()
    if (
        job is None
        or job.owner_id != scope.owner_id
        or job.workspace_id != scope.workspace_id
        or job.job_kind != VOICE_PREVIEW_JOB_KIND
        or job.resource_class != VOICE_PREVIEW_RESOURCE_CLASS
    ):
        raise InvalidNarrationState("Nano experiment job identity changed")
    return job


def _validation_input(
    keyring: DigestKeyring,
    *,
    key_id: str | None = None,
    digest: str | None = None,
) -> NanoExperimentValidationInput:
    resolved_key_id = key_id or keyring.active_key_id
    key = keyring.require(resolved_key_id)
    expected = historical_private_text_digest(
        key,
        purpose=VOICE_PREVIEW_TEXT_PURPOSE,
        text=NANO_EXPERIMENT_VALIDATION_TEXT,
    )
    if digest is not None and not hmac.compare_digest(expected, digest):
        raise InvalidNarrationState("Nano experiment validation HMAC changed")
    return NanoExperimentValidationInput(
        text=NANO_EXPERIMENT_VALIDATION_TEXT,
        input_digest_key_id=resolved_key_id,
        input_digest=expected,
    )


def build_nano_experiment_validation_input(
    keyring: DigestKeyring,
) -> NanoExperimentValidationInput:
    """Create the fixed private validation-text HMAC for the service."""

    return _validation_input(keyring)


class SqlAlchemyNanoExperimentStore:
    """Repository and Binder sharing one fixed local PostgreSQL authority."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        digest_keyring: DigestKeyring,
        preview_policy: VoicePreviewPolicy,
    ) -> None:
        if not callable(session_factory):
            raise TypeError("Nano experiment store requires a Session factory")
        if type(digest_keyring) is not DigestKeyring:
            raise TypeError("Nano experiment store requires a digest keyring")
        preview_policy.validate()
        self._session_factory = session_factory
        self._digest_keyring = digest_keyring
        self._preview_policy = preview_policy
        self._scope = NarrationRequestScope.fixed_local()
        self._identity = production_nano_experiment_identity()

    @property
    def session_factory(self) -> SessionFactory:
        return self._session_factory

    def _reusable(
        self,
        session: Session,
        intent: NanoExperimentIntent,
    ) -> NanoReusableVersion | None:
        version = session.scalar(
            select(VoiceProfileVersion).where(
                VoiceProfileVersion.profile_id == intent.profile_id,
                VoiceProfileVersion.fingerprint == intent.fingerprint,
                VoiceProfileVersion.state == "locked",
                VoiceProfileVersion.activation_basis
                == "experimental_machine_validated",
                VoiceProfileVersion.validation_basis == "machine_validated",
                VoiceProfileVersion.quality_state == "accepted",
                VoiceProfileVersion.model_run_id.is_not(None),
            )
        )
        if version is None or version.model_run_id is None:
            return None
        preview = session.scalar(
            select(VoicePreview)
            .where(
                VoicePreview.profile_id == version.profile_id,
                VoicePreview.version_id == version.id,
                VoicePreview.status == "ready",
                VoicePreview.result_asset_id.is_not(None),
            )
            .order_by(VoicePreview.completed_at.desc(), VoicePreview.id.desc())
        )
        run = session.get(ModelRunRecord, version.model_run_id)
        if preview is None or preview.result_asset_id is None or run is None:
            return None
        asset = session.get(MediaAsset, preview.result_asset_id)
        source_job = session.get(BackgroundJob, preview.job_id)
        if (
            asset is None
            or source_job is None
            or source_job.state != "succeeded"
            or run.result_classification != "success"
            or run.parameters_digest != intent.parameters_digest
            or run.model_fingerprint != intent.model_identity.model_fingerprint_sha256
            or run.output_digest != asset.content_hash
            or asset.state != "ready"
            or asset.asset_class != "preview"
            or asset.duration_ms is None
            or asset.duration_ms <= 0
        ):
            return None
        reusable = NanoReusableVersion(
            version_id=version.id,
            profile_id=version.profile_id,
            model_run_id=run.id,
            preview_id=preview.id,
            result_asset_id=asset.id,
            fingerprint=version.fingerprint,
            parameters_digest=run.parameters_digest,
            model_fingerprint_sha256=run.model_fingerprint or "",
            output_sha256=asset.content_hash,
        )
        validate_reusable_version(intent, reusable)
        return reusable

    def _reopen_completed_deletion(
        self,
        session: Session,
        *,
        profile: VoiceProfile,
        intent: NanoExperimentIntent,
        now: datetime,
    ) -> None:
        """Re-open the one active experiment Profile after a completed delete.

        Deletion deliberately keeps immutable Versions, commands and audit
        rows.  A new parameter set may therefore continue in the same
        novel+preset Profile, but only when a completed deletion proves why the
        Profile is unavailable and no deletion request is still active.  The
        exact deleted fingerprint cannot be recreated because its immutable
        Version remains the audit authority; callers must change the seed or
        another parameter instead of receiving a silent parameter change.
        """

        completed_deletion = session.scalar(
            select(VoiceDeletionRequest.id)
            .where(
                VoiceDeletionRequest.owner_id == self._scope.owner_id,
                VoiceDeletionRequest.workspace_id == self._scope.workspace_id,
                VoiceDeletionRequest.novel_id == intent.novel_id,
                VoiceDeletionRequest.voice_profile_id == profile.id,
                VoiceDeletionRequest.state == "completed",
            )
            .order_by(
                VoiceDeletionRequest.completed_at.desc(),
                VoiceDeletionRequest.id.desc(),
            )
            .limit(1)
        )
        active_deletion = session.scalar(
            select(VoiceDeletionRequest.id)
            .where(
                VoiceDeletionRequest.owner_id == self._scope.owner_id,
                VoiceDeletionRequest.workspace_id == self._scope.workspace_id,
                VoiceDeletionRequest.voice_profile_id == profile.id,
                VoiceDeletionRequest.state.in_(
                    {
                        "grace_pending",
                        "requested",
                        "live_deleting",
                        "live_deleted_backup_pending",
                        "failed",
                    }
                ),
            )
            .limit(1)
        )
        versions = tuple(
            session.scalars(
                select(VoiceProfileVersion).where(
                    VoiceProfileVersion.profile_id == profile.id
                )
            )
        )
        safe_experiment_history = bool(versions) and all(
            version.source_type == "generated"
            and version.activation_basis == "experimental_machine_validated"
            and version.preset_key == intent.base_preset_id
            for version in versions
        )
        if (
            completed_deletion is None
            or active_deletion is not None
            or not safe_experiment_history
        ):
            raise NarrationScopeMismatch("Nano experiment profile is unsafe")
        if any(version.fingerprint == intent.fingerprint for version in versions):
            raise NanoExperimentStateError(
                "deleted Nano experiment parameters require a changed seed or parameter"
            )
        profile.current_version_id = None
        profile.status = "draft"
        profile.archived_at = None
        profile.version += 1
        profile.updated_at = now
        session.flush([profile])

    @staticmethod
    def _unfinished_version(
        session: Session,
        intent: NanoExperimentIntent,
    ) -> VoiceProfileVersion | None:
        version = session.scalar(
            select(VoiceProfileVersion).where(
                VoiceProfileVersion.profile_id == intent.profile_id,
                VoiceProfileVersion.fingerprint == intent.fingerprint,
                VoiceProfileVersion.state.in_({"draft", "preview_ready"}),
            )
        )
        if version is None:
            return None
        active = session.scalar(
            select(NanoVoiceExperimentCommandRow.id).where(
                NanoVoiceExperimentCommandRow.version_id == version.id,
                NanoVoiceExperimentCommandRow.state.in_({"pending", "running"}),
            )
        )
        if active is not None:
            raise InvalidNarrationState(
                "identical Nano experiment already has active work"
            )
        return version

    def reserve(
        self, intent: NanoExperimentIntent, *, idempotency_key: str
    ) -> NanoExperimentReservation:
        def operation(session: Session) -> NanoExperimentReservation:
            store = SqlAlchemyNarrationStore(session)
            require_local_novel(store, intent.novel_id, for_update=True)
            existing = session.scalar(
                select(NanoVoiceExperimentCommandRow)
                .where(NanoVoiceExperimentCommandRow.id == intent.command_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if existing is not None:
                ensure_idempotent_request(
                    stored_request_digest=existing.request_hash,
                    incoming_request_digest=intent.request_digest,
                )
                return NanoExperimentReservation(
                    command=_command(existing), replayed=True
                )

            now = _db_now(session)
            preset = require_official_preset(intent.base_preset_id)
            profile = session.get(VoiceProfile, intent.profile_id)
            if profile is None:
                profile = VoiceProfile(
                    id=intent.profile_id,
                    owner_id=self._scope.owner_id,
                    workspace_id=self._scope.workspace_id,
                    novel_id=intent.novel_id,
                    name=f"高级调音 · {preset.display_name}",
                    current_version_id=None,
                    status="draft",
                    version=1,
                    archived_at=None,
                    created_at=now,
                    updated_at=now,
                )
                session.add(profile)
                session.flush([profile])
            elif (
                profile.owner_id != self._scope.owner_id
                or profile.workspace_id != self._scope.workspace_id
                or profile.novel_id != intent.novel_id
                or profile.status == "archived"
            ):
                raise NarrationScopeMismatch("Nano experiment profile is unsafe")
            elif profile.status == "unavailable":
                self._reopen_completed_deletion(
                    session,
                    profile=profile,
                    intent=intent,
                    now=now,
                )

            reusable = self._reusable(session, intent)
            unfinished = None if reusable is not None else self._unfinished_version(session, intent)
            job = enqueue_job(
                session,
                scope=self._scope,
                job_kind=VOICE_PREVIEW_JOB_KIND,
                input_hash=intent.fingerprint,
                idempotency_key=f"nano-experiment-job:{intent.command_id.hex}",
                resource_class=VOICE_PREVIEW_RESOURCE_CLASS,
                novel_id=intent.novel_id,
                request_id=None,
                base_priority=100,
                max_attempts=3,
            )
            if not job.created:
                raise InvalidNarrationState("new Nano command replayed an old job")

            if reusable is not None:
                version_id = reusable.version_id
                preview_id = reusable.preview_id
            else:
                version = unfinished
                if version is None:
                    version_id = _child_uuid(intent.command_id, "version")
                    version_number = int(
                        session.scalar(
                            select(func.max(VoiceProfileVersion.version_number)).where(
                                VoiceProfileVersion.profile_id == profile.id
                            )
                        )
                        or 0
                    ) + 1
                    rows = build_official_preset_version_rows(
                        profile=profile,
                        preset=preset,
                        version_id=version_id,
                        version_number=version_number,
                        actor=EXPERIMENT_ACTOR,
                        at=now,
                        direct_selection=False,
                    )
                    rows.version.source_type = "generated"
                    rows.version.parameters_json = {
                        "schema_version": EXPERIMENT_VERSION_SCHEMA_VERSION,
                        "official_preset": preset.provenance(),
                        "sample_mode": intent.parameters.sample_mode,
                        "max_new_frames": intent.parameters.max_new_frames,
                        "decode_parameters": dict(
                            intent.parameters.canonical_payload()
                        ),
                    }
                    rows.version.seed = intent.parameters.seed
                    rows.version.fingerprint = intent.fingerprint
                    rows.version.model_run_id = None
                    session.add(rows.rights)
                    session.flush([rows.rights])
                    session.add_all([rows.event, rows.version])
                    profile.version += 1
                    profile.updated_at = now
                    session.flush()
                    version = rows.version
                else:
                    version_id = version.id
                    if (
                        version.source_type != "generated"
                        or version.preset_key != intent.base_preset_id
                        or version.parameters_json.get("decode_parameters")
                        != dict(intent.parameters.canonical_payload())
                    ):
                        raise InvalidNarrationState(
                            "unfinished Nano version evidence changed"
                        )
                preview_id = _child_uuid(intent.command_id, "preview")
                validation = intent.validation_input
                preview = VoicePreview(
                    id=preview_id,
                    owner_id=self._scope.owner_id,
                    workspace_id=self._scope.workspace_id,
                    novel_id=intent.novel_id,
                    profile_id=profile.id,
                    version_id=version_id,
                    rights_record_id=version.rights_record_id,
                    job_id=job.job_id,
                    reference_asset_id=None,
                    result_asset_id=None,
                    preview_text=validation.text,
                    preview_text_digest_key_id=validation.input_digest_key_id,
                    preview_text_digest=validation.input_digest,
                    model_fingerprint=intent.model_identity.model_fingerprint_sha256,
                    reference_fingerprint=str(
                        preset.provenance()["provenance_fingerprint_sha256"]
                    ),
                    parameters_fingerprint=intent.parameters_digest,
                    request_fingerprint=intent.fingerprint,
                    status="queued",
                    started_at=None,
                    completed_at=None,
                    expires_at=None,
                    failure_code=None,
                    created_at=now,
                    updated_at=now,
                )
                session.add(preview)
                # The command and preview mappers do not expose ORM
                # relationships, so SQLAlchemy cannot infer their insert order
                # from object references alone.  Materialize the preview (and
                # its already-added Version/Job dependencies) before inserting
                # the command that owns its immediate foreign key.
                session.flush([preview])

            row = NanoVoiceExperimentCommandRow(
                id=intent.command_id,
                owner_id=self._scope.owner_id,
                workspace_id=self._scope.workspace_id,
                novel_id=intent.novel_id,
                profile_id=profile.id,
                version_id=version_id,
                preview_id=preview_id,
                background_job_id=job.job_id,
                base_preset_id=intent.base_preset_id,
                target_kind=intent.target.target_kind,
                target_character_id=intent.target.character_id,
                expected_settings_version=intent.target.expected_settings_version,
                expected_binding_version=intent.target.expected_binding_version,
                applied_settings_version=None,
                applied_binding_version=None,
                parameters_json=dict(intent.parameters.canonical_payload()),
                parameters_digest=intent.parameters_digest,
                input_digest_key_id=intent.validation_input.input_digest_key_id,
                input_digest=intent.validation_input.input_digest,
                fingerprint=intent.fingerprint,
                request_hash=intent.request_digest,
                idempotency_key=idempotency_key,
                state="pending",
                reused_version=False,
                failure_code=None,
                created_at=now,
                started_at=None,
                completed_at=None,
                applied_at=None,
                updated_at=now,
            )
            session.add(row)
            session.flush()
            return NanoExperimentReservation(
                command=_command(row),
                replayed=False,
                reusable_version=reusable,
            )

        return _transaction(self._session_factory, operation)

    def get(self, *, novel_id: UUID, command_id: UUID) -> NanoExperimentCommand:
        return _transaction(
            self._session_factory,
            lambda session: _command(
                _command_row(
                    session,
                    novel_id=novel_id,
                    command_id=command_id,
                    for_update=False,
                )
            ),
        )

    def list_for_novel(self, *, novel_id: UUID) -> tuple[NanoExperimentCommand, ...]:
        def operation(session: Session) -> tuple[NanoExperimentCommand, ...]:
            require_local_novel(SqlAlchemyNarrationStore(session), novel_id)
            rows = session.scalars(
                select(NanoVoiceExperimentCommandRow)
                .join(
                    VoiceProfile,
                    VoiceProfile.id == NanoVoiceExperimentCommandRow.profile_id,
                )
                .join(
                    VoicePreview,
                    VoicePreview.id == NanoVoiceExperimentCommandRow.preview_id,
                )
                .outerjoin(MediaAsset, MediaAsset.id == VoicePreview.result_asset_id)
                .where(
                    NanoVoiceExperimentCommandRow.owner_id == self._scope.owner_id,
                    NanoVoiceExperimentCommandRow.workspace_id
                    == self._scope.workspace_id,
                    NanoVoiceExperimentCommandRow.novel_id == novel_id,
                    VoiceProfile.status.in_({"draft", "active"}),
                    or_(
                        NanoVoiceExperimentCommandRow.state.not_in(
                            {"ready_applied", "ready_unapplied"}
                        ),
                        and_(
                            VoicePreview.status == "ready",
                            MediaAsset.state == "ready",
                        ),
                    ),
                )
                .order_by(
                    NanoVoiceExperimentCommandRow.created_at.desc(),
                    NanoVoiceExperimentCommandRow.id.desc(),
                )
            ).all()
            return tuple(_command(row) for row in rows)

        return _transaction(self._session_factory, operation)

    def _reusable_for_work(
        self,
        session: Session,
        row: NanoVoiceExperimentCommandRow,
        version: VoiceProfileVersion,
        preview: VoicePreview,
    ) -> NanoReusableVersion | None:
        if row.background_job_id == preview.job_id:
            return None
        if (
            version.state != "locked"
            or version.model_run_id is None
            or preview.status != "ready"
            or preview.result_asset_id is None
        ):
            raise InvalidNarrationState("Nano reuse source is not validated")
        run = session.get(ModelRunRecord, version.model_run_id)
        asset = session.get(MediaAsset, preview.result_asset_id)
        source_job = session.get(BackgroundJob, preview.job_id)
        if run is None or asset is None or source_job is None or source_job.state != "succeeded":
            raise InvalidNarrationState("Nano reuse evidence is incomplete")
        return NanoReusableVersion(
            version_id=version.id,
            profile_id=version.profile_id,
            model_run_id=run.id,
            preview_id=preview.id,
            result_asset_id=asset.id,
            fingerprint=version.fingerprint,
            parameters_digest=run.parameters_digest,
            model_fingerprint_sha256=run.model_fingerprint or "",
            output_sha256=asset.content_hash,
        )

    def load_and_mark_running(self, lease: JobLease) -> NanoExperimentWorkItem:
        def operation(session: Session) -> NanoExperimentWorkItem:
            heartbeat_attempt(session, scope=self._scope, fence=lease.fence)
            row = _command_row(session, job_id=lease.fence.job_id, for_update=True)
            job = _job_row(session, row.background_job_id, for_update=True)
            profile = _profile_row(
                session, row.profile_id, novel_id=row.novel_id, for_update=True
            )
            version = _version_row(
                session,
                profile_id=profile.id,
                version_id=row.version_id,
                for_update=True,
            )
            preview = _preview_row(session, row.preview_id, for_update=True)
            if job.state != "running" or row.state not in {"pending", "running"}:
                raise InvalidNarrationState("Nano experiment claim is not runnable")
            validation = _validation_input(
                self._digest_keyring,
                key_id=row.input_digest_key_id,
                digest=row.input_digest,
            )
            reusable = self._reusable_for_work(session, row, version, preview)
            if reusable is None:
                if (
                    preview.job_id != job.id
                    or preview.status not in {"queued", "running"}
                    or preview.preview_text != validation.text
                    or version.state not in {"draft", "preview_ready"}
                ):
                    raise InvalidNarrationState("Nano experiment input changed")
            parameters = NanoDecodeParametersV3.from_payload(row.parameters_json)
            metadata = canonical_sidecar_synthesis_metadata(
                request_id=lease.fence.attempt_id,
                scope=self._scope,
                requested_model_fingerprint_sha256=(
                    self._identity.model_fingerprint_sha256
                ),
                text=validation.text,
                voice=row.base_preset_id,
                seed=parameters.seed,
                sample_mode=parameters.sample_mode,
                max_new_frames=parameters.max_new_frames,
                decode_parameters=parameters.sidecar_decode_parameters(),
                reference_content_type=None,
                reference_actual_sha256=None,
                reference_size_bytes=None,
            )
            model_input_key_id = self._digest_keyring.active_key_id
            model_input_digest = _model_input_digest(
                self._digest_keyring,
                key_id=model_input_key_id,
                metadata=metadata,
            )
            now = _db_now(session)
            if row.state == "pending":
                row.state = "running"
                row.started_at = now
            if reusable is None and preview.status == "queued":
                preview.status = "running"
                preview.started_at = now
                preview.updated_at = now
            row.updated_at = now
            session.flush()
            return NanoExperimentWorkItem(
                lease=lease,
                command=_command(row),
                validation_input=validation,
                model_identity=self._identity,
                model_input_digest_key_id=model_input_key_id,
                model_input_digest=model_input_digest,
                reusable_version=reusable,
            )

        return _transaction(self._session_factory, operation)

    def _fail_in_session(
        self,
        session: Session,
        *,
        lease: JobLease,
        failure: NanoExperimentFailure,
    ) -> NanoExperimentWorkerOutcome:
        row = _command_row(session, job_id=lease.fence.job_id, for_update=True)
        preview = _preview_row(session, row.preview_id, for_update=True)
        now = _db_now(session)
        if row.state == "pending":
            row.state = "running"
            row.started_at = now
            row.updated_at = now
            session.flush([row])
        result = fail_attempt(
            session,
            scope=self._scope,
            fence=lease.fence,
            classification=("retryable" if failure.retryable else "non_retryable"),
            error_code=failure.code,
        )
        if result.state in {"failed", "dead_letter"}:
            ensure_state_transition(row.state, "failed")
            row.state = "failed"
            row.failure_code = failure.code
            row.completed_at = now
            row.updated_at = now
            if preview.job_id == row.background_job_id and preview.status in {
                "queued",
                "running",
            }:
                preview.status = "failed"
                preview.preview_text = None
                preview.result_asset_id = None
                preview.completed_at = now
                preview.expires_at = None
                preview.failure_code = failure.code
                preview.updated_at = now
            release_active_job_assets_in_session(
                session, job_id=row.background_job_id
            )
        session.flush()
        return NanoExperimentWorkerOutcome(
            status=result.state,
            job_id=row.background_job_id,
            command_id=row.id,
            failure_code=failure.code,
            command=_command(row),
        )

    def fail(
        self, work: NanoExperimentWorkItem, failure: NanoExperimentFailure
    ) -> NanoExperimentWorkerOutcome:
        return _transaction(
            self._session_factory,
            lambda session: self._fail_in_session(
                session, lease=work.lease, failure=failure
            ),
        )

    def fail_claim(
        self, lease: JobLease, failure: NanoExperimentFailure
    ) -> NanoExperimentWorkerOutcome:
        return _transaction(
            self._session_factory,
            lambda session: self._fail_in_session(
                session, lease=lease, failure=failure
            ),
        )

    @staticmethod
    def _target_apply(
        session: Session,
        *,
        row: NanoVoiceExperimentCommandRow,
        profile: VoiceProfile,
        version: VoiceProfileVersion,
        expected_settings_version: int,
        expected_binding_version: int | None,
    ) -> tuple[bool, int | None, int | None]:
        store = SqlAlchemyNarrationStore(session)
        require_local_novel(store, row.novel_id, for_update=True)
        store.find_one(
            NovelNarrationSettings, novel_id=row.novel_id, for_update=True
        )
        settings = get_narration_settings(store, novel_id=row.novel_id)
        if settings.version != expected_settings_version:
            return False, None, None
        values = settings.values
        if row.target_kind == "narrator":
            update_settings(
                store,
                NarrationSettingsUpdate(
                    novel_id=row.novel_id,
                    script_review_policy=values.script_review_policy.value,
                    analysis_mode=values.analysis_mode.value,
                    settings_json=_storage_settings(values),
                    expected_version=settings.version,
                    narrator_profile_id=profile.id,
                    narrator_version_id=version.id,
                ),
            )
            current = get_narration_settings(store, novel_id=row.novel_id)
            return True, current.version, None
        if row.target_character_id is None or expected_binding_version is None:
            raise InvalidNarrationState("Nano character target is incomplete")
        character = _require_character(
            store,
            novel_id=row.novel_id,
            character_id=row.target_character_id,
            for_update=True,
        )
        if character.lifecycle_state != "active":
            return False, None, None
        binding_row = store.find_one(
            CharacterVoiceBinding,
            character_id=row.target_character_id,
            for_update=True,
        )
        binding_version = 0 if binding_row is None else binding_row.version
        if binding_version != expected_binding_version:
            return False, None, None
        if not settings.exists:
            update_settings(
                store,
                NarrationSettingsUpdate(
                    novel_id=row.novel_id,
                    script_review_policy=values.script_review_policy.value,
                    analysis_mode=values.analysis_mode.value,
                    settings_json=_storage_settings(values),
                    expected_version=0,
                    narrator_profile_id=None,
                    narrator_version_id=None,
                ),
            )
            settings = get_narration_settings(store, novel_id=row.novel_id)
        binding = put_character_voice_binding(
            store,
            novel_id=row.novel_id,
            character_id=row.target_character_id,
            request=wire.PutCharacterVoiceBindingRequest(
                expected_version=expected_binding_version,
                binding_policy=wire.CharacterVoiceBindingPolicy.DEDICATED,
                profile_id=profile.id,
                version_id=version.id,
                language=settings.values.language,
            ),
        )
        return True, settings.version, binding.version

    def _complete(
        self,
        session: Session,
        *,
        work: NanoExperimentWorkItem,
        evidence: NanoValidatedEvidence | None,
        reusable: NanoReusableVersion | None,
    ) -> NanoExperimentCommand:
        if work.lease.resource_fence is None:
            raise InvalidNarrationState("Nano experiment lease lacks a resource fence")
        context = lock_result_publish_fences(
            session,
            scope=self._scope,
            job_fence=work.lease.fence,
            resource_fence=work.lease.resource_fence,
        )
        row = _command_row(session, command_id=work.command.command_id, for_update=True)
        profile = _profile_row(
            session, row.profile_id, novel_id=row.novel_id, for_update=True
        )
        version = _version_row(
            session,
            profile_id=profile.id,
            version_id=row.version_id,
            for_update=True,
        )
        preview = _preview_row(session, row.preview_id, for_update=True)
        now = _db_now(session)
        if row.state != "running" or row.background_job_id != work.lease.fence.job_id:
            raise NanoExperimentStateError("Nano experiment success fence changed")
        if reusable is not None:
            validate_reusable_version(
                NanoExperimentIntent(
                    command_id=work.command.command_id,
                    novel_id=work.command.novel_id,
                    profile_id=work.command.profile_id,
                    base_preset_id=work.command.base_preset_id,
                    target=work.command.target,
                    parameters=work.command.parameters,
                    parameters_digest=work.command.parameters_digest,
                    fingerprint=work.command.fingerprint,
                    request_digest=work.command.request_digest,
                    validation_input=work.validation_input,
                    model_identity=work.model_identity,
                ),
                reusable,
            )
            # Structural evidence plus the 0034 deferred closure protects the
            # source Version/Preview/ModelRun relation.  Read its rights row
            # without mutating any reusable evidence.
            from ..models import VoiceRightsRecord

            rights_row = session.get(VoiceRightsRecord, version.rights_record_id)
            if rights_row is None:
                raise InvalidNarrationState("reused Nano rights are absent")
            validate_nano_experiment_version_evidence(
                version,
                rights_row,
                expected_model_fingerprint=OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256,
            )
            output_digest = reusable.output_sha256
        else:
            if evidence is None or evidence.preview_id != preview.id:
                raise InvalidNarrationState("Nano validated evidence changed")
            if preview.status != "running" or preview.preview_text is None:
                raise InvalidNarrationState("Nano preview is not publishable")
            if session.get(MediaAsset, evidence.result_asset_id) is not None:
                raise InvalidNarrationState("Nano experiment result asset already exists")
            expires_at = now + timedelta(seconds=EXPERIMENT_PREVIEW_TTL_SECONDS)
            asset = MediaAsset(
                id=evidence.result_asset_id,
                owner_id=self._scope.owner_id,
                workspace_id=self._scope.workspace_id,
                novel_id=row.novel_id,
                source_revision_id=None,
                kind="narration_voice_preview",
                asset_class="preview",
                mime_type="audio/wav",
                byte_size=evidence.published_byte_size,
                duration_ms=evidence.duration_ms,
                sample_rate=evidence.sample_rate_hz,
                channels=evidence.channels,
                storage_backend="local",
                state="ready",
                retention_policy="temporary_preview",
                checksum_algorithm="sha256",
                validation_json={
                    "schema_version": EXPERIMENT_VERSION_SCHEMA_VERSION,
                    "postprocess_fingerprint": evidence.postprocess_fingerprint,
                    "parameters_digest": evidence.parameters_digest,
                },
                verified_at=now,
                last_accessed_at=None,
                expires_at=expires_at,
                deleted_at=None,
                gc_generation=0,
                gc_marked_at=None,
                storage_path=evidence.published_relative_path,
                content_hash=evidence.output_sha256,
                metadata_json={
                    "schema_version": EXPERIMENT_VERSION_SCHEMA_VERSION,
                    "preview_id": str(preview.id),
                    "model_fingerprint": evidence.model_fingerprint_sha256,
                },
                created_at=now,
            )
            session.add(asset)
            run = ModelRunRecord(
                id=evidence.model_run_id,
                attempt_id=evidence.attempt_id,
                requested_provider_id=work.model_identity.requested_provider_id,
                requested_model_id=work.model_identity.requested_model_id,
                requested_revision=work.model_identity.requested_revision,
                actual_provider_id=work.model_identity.actual_provider_id,
                actual_model_id=work.model_identity.actual_model_id,
                actual_revision=work.model_identity.actual_revision,
                model_fingerprint=evidence.model_fingerprint_sha256,
                parameters_digest=evidence.parameters_digest,
                input_digest_key_id=evidence.input_digest_key_id,
                input_digest=evidence.input_digest,
                output_digest=evidence.output_sha256,
                duration_ms=evidence.duration_ms,
                provider_request_id=str(evidence.attempt_id),
                result_classification="success",
                created_at=now,
            )
            session.add(run)
            preview.status = "ready"
            preview.preview_text = None
            preview.result_asset_id = asset.id
            preview.completed_at = now
            preview.expires_at = expires_at
            preview.failure_code = None
            preview.updated_at = now
            if version.state == "draft":
                version.state = "preview_ready"
                session.flush([asset, run, preview, version])
            if version.state != "preview_ready":
                raise InvalidNarrationState("Nano version cannot be machine validated")
            version.state = "locked"
            version.quality_state = "accepted"
            version.activation_basis = "experimental_machine_validated"
            version.validation_basis = "machine_validated"
            version.model_run_id = run.id
            version.locked_actor = None
            version.locked_at = None
            output_digest = evidence.output_sha256
        profile.current_version_id = version.id
        profile.status = "active"
        profile.version += 1
        profile.updated_at = now

        applied, settings_version, binding_version = self._target_apply(
            session,
            row=row,
            profile=profile,
            version=version,
            expected_settings_version=row.expected_settings_version,
            expected_binding_version=row.expected_binding_version,
        )
        row.state = "ready_applied" if applied else "ready_unapplied"
        if reusable is not None:
            # The 0034 trigger requires reuse evidence and the ready terminal
            # transition to be written atomically.  Do not expose
            # ``reused_version=true`` while the command is still running; a
            # target lookup may otherwise autoflush that impossible state.
            row.reused_version = True
        row.applied_settings_version = settings_version
        row.applied_binding_version = binding_version
        row.completed_at = now
        row.applied_at = now if applied else None
        row.failure_code = None
        row.updated_at = now
        release_active_job_assets_in_session(session, job_id=row.background_job_id)
        complete_attempt(
            session,
            scope=self._scope,
            fence=work.lease.fence,
            actual_result_digest=output_digest,
            publication_context=context,
        )
        session.flush()
        return _command(row)

    def complete_validated(
        self,
        work: NanoExperimentWorkItem,
        evidence: NanoValidatedEvidence,
    ) -> NanoExperimentCommand:
        return _transaction(
            self._session_factory,
            lambda session: self._complete(
                session, work=work, evidence=evidence, reusable=None
            ),
        )

    def complete_reused(
        self,
        work: NanoExperimentWorkItem,
        reusable_version: NanoReusableVersion,
    ) -> NanoExperimentCommand:
        return _transaction(
            self._session_factory,
            lambda session: self._complete(
                session,
                work=work,
                evidence=None,
                reusable=reusable_version,
            ),
        )

    def apply_ready_unapplied(
        self,
        *,
        novel_id: UUID,
        command_id: UUID,
        request: NanoExperimentApplyRequest,
    ) -> NanoExperimentCommand:
        def operation(session: Session) -> NanoExperimentCommand:
            row = _command_row(
                session,
                command_id=command_id,
                novel_id=novel_id,
                for_update=True,
            )
            if row.state == "ready_applied":
                return _command(row)
            if row.state != "ready_unapplied":
                raise NanoExperimentStateError(
                    "only a ready-unapplied Nano command can be applied"
                )
            profile = _profile_row(
                session, row.profile_id, novel_id=novel_id, for_update=True
            )
            version = _version_row(
                session,
                profile_id=profile.id,
                version_id=row.version_id,
                for_update=True,
            )
            applied, settings_version, binding_version = self._target_apply(
                session,
                row=row,
                profile=profile,
                version=version,
                expected_settings_version=request.expected_settings_version,
                expected_binding_version=request.expected_binding_version,
            )
            if not applied or settings_version is None:
                raise NarrationCasConflict("Nano experiment target changed again")
            now = _db_now(session)
            row.state = "ready_applied"
            row.applied_settings_version = settings_version
            row.applied_binding_version = binding_version
            row.applied_at = now
            row.updated_at = now
            session.flush()
            return _command(row)

        return _transaction(self._session_factory, operation)

    def terminalize_job_in_session(self, session: Session, *, job_id: UUID) -> bool:
        row = _command_row(session, job_id=job_id, for_update=True)
        if row.state in {"ready_applied", "ready_unapplied", "failed"}:
            return False
        job = _job_row(session, job_id, for_update=True)
        if job.state not in {"failed", "dead_letter", "cancelled"}:
            return False
        preview = _preview_row(session, row.preview_id, for_update=True)
        now = _db_now(session)
        if row.state == "pending":
            row.state = "running"
            row.started_at = now
            row.updated_at = now
            session.flush([row])
        row.state = "failed"
        row.failure_code = "NANO_EXPERIMENT_DATABASE_FAILED"
        row.completed_at = now
        row.updated_at = now
        if preview.job_id == job.id and preview.status in {"queued", "running"}:
            preview.status = "cancelled" if job.state == "cancelled" else "failed"
            preview.preview_text = None
            preview.result_asset_id = None
            preview.completed_at = now
            preview.expires_at = None
            preview.failure_code = (
                None if job.state == "cancelled" else row.failure_code
            )
            preview.updated_at = now
        release_active_job_assets_in_session(session, job_id=job.id)
        session.flush()
        return True

    def owns_job(self, job_id: UUID) -> bool:
        def operation(session: Session) -> bool:
            return (
                session.scalar(
                    select(NanoVoiceExperimentCommandRow.id).where(
                        NanoVoiceExperimentCommandRow.background_job_id == job_id,
                        NanoVoiceExperimentCommandRow.owner_id == self._scope.owner_id,
                        NanoVoiceExperimentCommandRow.workspace_id
                        == self._scope.workspace_id,
                    )
                )
                is not None
            )

        return _transaction(self._session_factory, operation)

    def owns_job_in_session(self, session: Session, *, job_id: UUID) -> bool:
        """Check ownership without opening a nested transaction."""

        return (
            session.scalar(
                select(NanoVoiceExperimentCommandRow.id).where(
                    NanoVoiceExperimentCommandRow.background_job_id == job_id,
                    NanoVoiceExperimentCommandRow.owner_id == self._scope.owner_id,
                    NanoVoiceExperimentCommandRow.workspace_id
                    == self._scope.workspace_id,
                )
            )
            is not None
        )


class SidecarNanoExperimentSynthesizer:
    """Run the real Nano adapter and publish a content-addressed WAV."""

    def __init__(
        self,
        *,
        adapter: MossNanoTTSAdapter,
        storage: NarrationStorage,
    ) -> None:
        self._adapter = adapter
        self._storage = storage

    async def synthesize(
        self, request: NanoExperimentSynthesisRequest
    ) -> NanoExperimentSynthesisResult:
        result = await self._adapter.synthesize(
            SynthesisRequest(
                request_id=request.attempt_id,
                scope=NarrationRequestScope.fixed_local(),
                text=request.text,
                voice=request.base_preset_id,
                seed=request.parameters.seed,
                sample_mode=request.parameters.sample_mode,
                max_new_frames=request.parameters.max_new_frames,
                decode_parameters=request.parameters.sidecar_decode_parameters(),
                reference_audio=None,
            )
        )
        processed = process_synthesis_wav(
            result.audio_bytes,
            spoken_text=request.text,
        )
        result_asset_id = _child_uuid(request.preview_id, "preview-result")
        published = _published_or_adopted(
            self._storage,
            processed.wav_bytes,
            asset_id=result_asset_id,
            digest=processed.actual_sha256,
            extension="wav",
            max_bytes=MAX_PREVIEW_MEDIA_BYTES,
        )
        actual_fingerprint = model_fingerprint_sha256(result.model_fingerprint)
        run = NanoModelRunEvidence(
            model_run_id=_child_uuid(request.attempt_id, "model-run"),
            attempt_id=request.attempt_id,
            requested_provider_id=request.model_identity.requested_provider_id,
            requested_model_id=request.model_identity.requested_model_id,
            requested_revision=request.model_identity.requested_revision,
            actual_provider_id=request.model_identity.actual_provider_id,
            actual_model_id=result.model_fingerprint.model_name,
            actual_revision=result.model_fingerprint.model_revision,
            model_fingerprint_sha256=actual_fingerprint,
            parameters_digest=request.parameters_digest,
            input_digest_key_id=request.input_digest_key_id,
            input_digest=request.input_digest,
            output_digest=processed.actual_sha256,
            result_classification="success",
        )
        return NanoExperimentSynthesisResult(
            command_id=request.command_id,
            attempt_id=request.attempt_id,
            audio_bytes=processed.wav_bytes,
            output_sha256=processed.actual_sha256,
            sample_rate_hz=processed.sample_rate_hz,
            channels=processed.channels,
            sample_width_bytes=processed.sample_width_bytes,
            duration_ms=processed.duration_ms,
            sidecar_protocol_version=PROTOCOL_VERSION,
            postprocess_fingerprint=processed.processing_fingerprint,
            preview_id=request.preview_id,
            result_asset_id=result_asset_id,
            published_relative_path=published.relative_path,
            published_byte_size=published.byte_size,
            model_run=run,
        )


class NanoVoicePreviewTerminalizer:
    """Route the shared preview job kind to its exact owning state machine."""

    def __init__(self, experiment: SqlAlchemyNanoExperimentStore, ordinary: object):
        self._experiment = experiment
        self._ordinary = ordinary

    def __call__(self, session: Session, *, job_id: UUID) -> bool:
        if self._experiment.owns_job_in_session(session, job_id=job_id):
            return self._experiment.terminalize_job_in_session(
                session, job_id=job_id
            )
        terminalize = getattr(self._ordinary, "terminalize_job_in_session", None)
        if not callable(terminalize):
            raise InvalidNarrationState("ordinary preview terminalizer is unavailable")
        return bool(terminalize(session, job_id=job_id))


__all__ = [
    "EXPERIMENT_VERSION_SCHEMA_VERSION",
    "NanoVoicePreviewTerminalizer",
    "SidecarNanoExperimentSynthesizer",
    "SqlAlchemyNanoExperimentStore",
    "build_nano_experiment_validation_input",
]
