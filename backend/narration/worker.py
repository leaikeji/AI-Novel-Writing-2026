"""Fenced Provider-neutral narration segment worker.

Database work is deliberately split into short transactions.  Synthesis,
audio processing, FFmpeg, reference-media reads, and immutable file publication
run after the claim transaction has committed.  The final transaction locks
both the job and inference resource generations before making media reachable.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Final, Literal, Mapping, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from ..models import (
    BackgroundJob,
    Document,
    MediaAsset,
    ModelRunRecord,
    NarrationEdition,
    NarrationEditionSegment,
    NarrationEditionState,
    NarrationRequest,
    NarrationSegment,
    NarrationSegmentRender,
    NarrationSettingsSnapshot,
    VoiceProfileVersion,
)
from . import schemas as wire
from .audio_pipeline import (
    audio_validation_failure_evidence,
    AudioFormatError,
    AudioPipelineError,
    AudioQualityError,
    ProcessedPcmWav,
    process_provider_synthesis_wav,
)
from .contracts import (
    NarrationRequestScope,
    ReferenceAudioInput,
    TTSAudioFormat,
    TTSSynthesisRequest,
    TTSSynthesisResult,
    TTSVoiceInput,
    TTSVoiceKind,
)
from .digest_keyring import DigestKeyring, HmacDigestKey
from .disk_guard import NarrationDiskGuardError
from .editions import advance_edition_segment_state
from .fingerprints import canonical_json_bytes
from .jobs import (
    FailureResult,
    JobFenceError,
    JobLease,
    acknowledge_cancel,
    fail_attempt,
    heartbeat_attempt,
    lock_result_publish_fences,
)
from .manifest import (
    BUFFER_POLICIES,
    ManifestFailure,
    ManifestSegmentInput,
    PublishManifest,
    append_manifest_revision,
    publish_manifest,
)
from .providers.base import TTSProviderError
from .official_presets import (
    official_preset_provider_voice_id,
    require_official_preset,
)
from .publication import (
    ModelRunSuccessEvidence,
    RenderAudioEvidence,
    publish_render_result_in_session,
    render_asset_id,
)
from .progress import initialize_initial_document_edition
from .requests import advance_request_state
from .renders import (
    CreateRender,
    compute_render_fingerprint,
    render_job_input_hash,
)
from .scheduler import NarrationJobScheduler, SessionFactory
from .services import (
    InvalidNarrationState,
    NarrationScopeMismatch,
    SqlAlchemyNarrationStore,
    canonical_sha256,
    require_usable_voice,
)
from .storage import (
    NarrationStorage,
    PublicationValidationError,
    StorageError,
    StorageRootChanged,
    UnsafeStoragePath,
)
from .tts_execution import TTSExecutionService
from .tts_selection import selection_fingerprint, selection_from_settings_snapshot
from .transcoding import (
    DEFAULT_TRANSCODING_POLICY,
    TranscodedSegment,
    TranscodingError,
    TranscodingPolicy,
    TranscodingUnavailable,
    TranscodingValidationError,
    transcode_segment,
)


WorkerStatus = Literal[
    "idle",
    "succeeded",
    "cancelled",
    "retry_wait",
    "failed",
    "dead_letter",
    "stale",
]

MODEL_INPUT_DIGEST_SCHEMA_VERSION = "narration-model-input-digest/1"
MODEL_INPUT_DIGEST_PURPOSE = "qwen-tts-segment-synthesis"
QWEN_VOICE_PARAMETERS_SCHEMA_VERSION = "qwen-tts-voice/1"
AUDIO_VALIDATION_FAILURE_REASON_CODES: Final[frozenset[str]] = frozenset(
    {
        "AUDIO_VALIDATION_UNKNOWN",
        "POSTPROCESS_DURATION_CHANGED",
        "SHORT_CHINESE_DURATION_IMPLAUSIBLE",
        "WAV_CLIPPING_LIMIT_EXCEEDED",
        "WAV_CONTAINER_CORRUPT",
        "WAV_DURATION_DRIFT",
        "WAV_DURATION_OUT_OF_BOUNDS",
        "WAV_EMPTY_OR_NOT_BYTES",
        "WAV_FORMAT_MISMATCH",
        "WAV_FRAME_COUNT_MISMATCH",
        "WAV_INPUT_TOO_LARGE",
        "WAV_NOT_PCM",
        "WAV_PAYLOAD_EMPTY_OR_TRUNCATED",
        "WAV_SAMPLE_COUNT_MISMATCH",
        "WAV_SILENT",
    }
)


def derive_model_input_digest(
    key: HmacDigestKey,
    *,
    provider_metadata: bytes,
) -> tuple[str, str]:
    """HMAC the exact Provider request metadata with domain separation."""

    if type(key) is not HmacDigestKey or type(provider_metadata) is not bytes:
        raise WorkerContractError("model input digest requires canonical metadata")
    domain = (
        MODEL_INPUT_DIGEST_SCHEMA_VERSION.encode("ascii")
        + b"\0"
        + MODEL_INPUT_DIGEST_PURPOSE.encode("ascii")
        + b"\0"
    )
    return key.key_id, key.digest(domain + provider_metadata)


class WorkerContractError(RuntimeError):
    """The persisted work item or adapter result violated a frozen contract."""


class WorkerSecurityError(WorkerContractError):
    """A scope, model identity, or immutable-storage proof failed closed."""


class WorkerVoiceUnavailableError(WorkerContractError):
    """The selected Provider has no verified mapping for an official voice."""


@dataclass(frozen=True, slots=True)
class ReferenceMedia:
    relative_path: str = field(repr=False)
    actual_sha256: str
    byte_size: int
    content_type: str


@dataclass(frozen=True, slots=True)
class SegmentWorkItem:
    lease: JobLease
    render_id: UUID
    edition_id: UUID
    edition_segment_id: UUID
    request_id: UUID
    novel_id: UUID
    text: str = field(repr=False)
    selection: wire.TTSProviderSelection
    language: str
    voice_kind: TTSVoiceKind
    provider_voice_id: str
    seed: int | None
    instruction: str | None = field(repr=False)
    requested_provider_id: str
    requested_model_id: str | None
    requested_revision: str | None
    expected_model_fingerprint: str
    expected_postprocess_fingerprint: str
    parameters_digest: str
    input_digest_key_id: str
    input_digest: str
    reference_media: ReferenceMedia | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class _RenderWorkRows:
    render: NarrationSegmentRender
    edition: NarrationEdition
    edition_segment: NarrationEditionSegment
    segment: NarrationSegment
    voice: VoiceProfileVersion
    fanout_segments: tuple[NarrationEditionSegment, ...]
    fanout_editions: tuple[NarrationEdition, ...]


@dataclass(frozen=True, slots=True)
class PreparedRender:
    audio: RenderAudioEvidence
    model: ModelRunSuccessEvidence


@dataclass(frozen=True, slots=True)
class WorkerOutcome:
    status: WorkerStatus
    job_id: UUID | None = None
    render_id: UUID | None = None
    error_code: str | None = None


def _qwen_voice_parameters(
    voice: VoiceProfileVersion,
    selection: wire.TTSProviderSelection | None = None,
) -> tuple[TTSVoiceKind, str, str | None]:
    """Validate the only voice parameter shape accepted by the Qwen worker."""

    parameters = voice.parameters_json
    if type(parameters) is not dict:
        raise WorkerContractError("voice parameters must be an object")
    allowed_keys = {
        "schema_version",
        "voice_kind",
        "provider_voice_id",
        "provider_voice_ids",
        "instruction",
        "official_preset",
    }
    if (
        set(parameters) - allowed_keys
        or parameters.get("schema_version") != QWEN_VOICE_PARAMETERS_SCHEMA_VERSION
    ):
        raise WorkerContractError("voice parameters do not use the Qwen TTS schema")
    try:
        voice_kind = TTSVoiceKind(parameters.get("voice_kind"))
    except (TypeError, ValueError) as error:
        raise WorkerContractError("voice kind is invalid") from error
    provider_voice_id = parameters.get("provider_voice_id")
    provider_voice_ids = parameters.get("provider_voice_ids")
    if provider_voice_ids is not None:
        if type(provider_voice_ids) is not dict or any(
            type(key) is not str or type(value) is not str
            for key, value in provider_voice_ids.items()
        ):
            raise WorkerContractError("Provider voice map is invalid")
        if voice.preset_key is None:
            raise WorkerSecurityError("Qwen preset voice evidence is inconsistent")
        try:
            preset = require_official_preset(voice.preset_key)
        except ValueError as error:
            raise WorkerSecurityError("Qwen preset is not in the pinned catalog") from error
        if (
            provider_voice_ids != preset.provider_voice_ids
            or parameters.get("official_preset") != preset.provenance()
        ):
            raise WorkerSecurityError("Qwen preset Provider mapping changed")
        active_selection = selection or wire.TTSProviderSelection()
        provider_voice_id = official_preset_provider_voice_id(
            preset.preset_id,
            provider_id=active_selection.provider_id,
            aliyun_model_id=active_selection.aliyun_model_id,
        )
        if provider_voice_id is None:
            raise WorkerVoiceUnavailableError(
                "official voice has no mapping for the selected Provider"
            )
    if (
        type(provider_voice_id) is not str
        or not provider_voice_id
        or provider_voice_id != provider_voice_id.strip()
        or len(provider_voice_id) > 240
    ):
        raise WorkerContractError("Provider voice ID is invalid")
    instruction = parameters.get("instruction")
    if instruction is not None and (
        type(instruction) is not str
        or not instruction
        or instruction != instruction.strip()
        or len(instruction) > 2_000
    ):
        raise WorkerContractError("voice instruction is invalid")
    if voice_kind is TTSVoiceKind.PRESET:
        if (
            voice.source_type != "preset"
            or voice.reference_asset_id is not None
            or voice.preset_key is None
        ):
            raise WorkerSecurityError("Qwen preset voice evidence is inconsistent")
    elif voice_kind is TTSVoiceKind.REFERENCE_CLONE:
        if voice.source_type not in {"uploaded", "generated"} or voice.reference_asset_id is None:
            raise WorkerSecurityError("Qwen reference voice evidence is inconsistent")
    elif (
        voice.source_type != "generated"
        or voice.reference_asset_id is not None
        or voice.preset_key is not None
    ):
        raise WorkerSecurityError("Qwen designed voice evidence is inconsistent")
    return voice_kind, provider_voice_id, instruction


@dataclass(frozen=True, slots=True)
class NarrationWorkerConfig:
    actor: str
    heartbeat_seconds: float = 30.0
    max_reference_bytes: int = 25 * 1024 * 1024

    def validate(self) -> None:
        if (
            type(self.actor) is not str
            or not self.actor
            or self.actor != self.actor.strip()
            or len(self.actor) > 120
        ):
            raise ValueError("worker actor must be a normalized value")
        if not isinstance(self.heartbeat_seconds, (int, float)) or not (
            0.01 <= float(self.heartbeat_seconds) <= 1_800.0
        ):
            raise ValueError("worker heartbeat interval is outside its bounded range")
        if (
            type(self.max_reference_bytes) is not int
            or not 1 <= self.max_reference_bytes <= 256 * 1024 * 1024
        ):
            raise ValueError("worker reference-media bound is invalid")


class WorkerRepository(Protocol):
    def load_and_mark_running(
        self, lease: JobLease, *, actor: str
    ) -> SegmentWorkItem: ...

    def heartbeat_and_read_state(self, lease: JobLease) -> str: ...

    def read_job_state(self, lease: JobLease) -> str: ...

    def acknowledge_cancel(self, work: SegmentWorkItem) -> None: ...

    def publish(self, work: SegmentWorkItem, prepared: PreparedRender, *, actor: str) -> None: ...

    def fail(
        self,
        work: SegmentWorkItem,
        *,
        classification: Literal["retryable", "non_retryable", "security_failure"],
        error_code: str,
        failure_evidence: Mapping[str, object] | None = None,
    ) -> FailureResult: ...

    def fail_claim(
        self,
        lease: JobLease,
        *,
        classification: Literal["retryable", "non_retryable", "security_failure"],
        error_code: str,
    ) -> FailureResult: ...


class SqlAlchemyNarrationWorkerRepository:
    """Production short-transaction repository used by the async worker."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        digest_keyring: DigestKeyring,
        scope: NarrationRequestScope = NarrationRequestScope.fixed_local(),
    ) -> None:
        if not callable(session_factory):
            raise TypeError("worker repository requires a Session factory")
        if type(digest_keyring) is not DigestKeyring:
            raise TypeError("worker repository requires a digest keyring")
        scope.ensure_fixed_local()
        self._session_factory = session_factory
        self._digest_keyring = digest_keyring
        self._scope = scope

    def _transaction(self, operation: Callable[[Session], object]) -> object:
        with self._session_factory() as session:
            try:
                value = operation(session)
                session.commit()
                return value
            except BaseException:
                session.rollback()
                raise

    def _job(self, session: Session, lease: JobLease, *, for_update: bool) -> BackgroundJob:
        statement = select(BackgroundJob).where(
            BackgroundJob.id == lease.fence.job_id,
            BackgroundJob.owner_id == self._scope.owner_id,
            BackgroundJob.workspace_id == self._scope.workspace_id,
        )
        if for_update:
            statement = statement.with_for_update()
        job = session.scalar(statement.execution_options(populate_existing=True))
        if job is None:
            raise NarrationScopeMismatch("render job is outside fixed local scope")
        if job.job_kind != "narration.segment_render" or job.resource_class != "qwen-tts":
            raise WorkerSecurityError("claimed job is not a Qwen TTS segment render")
        return job

    def _work_rows(
        self,
        session: Session,
        *,
        job: BackgroundJob,
        for_update: bool,
        validate_current_authority: bool = True,
    ) -> _RenderWorkRows:
        render_statement = select(NarrationSegmentRender).where(
            NarrationSegmentRender.source_job_id == job.id
        )
        if for_update:
            render_statement = render_statement.with_for_update()
        render = session.scalar(
            render_statement.execution_options(populate_existing=True)
        )
        if render is None:
            raise InvalidNarrationState("claimed render job has no render row")
        statement = (
            select(
                NarrationEdition,
                NarrationEditionSegment,
                NarrationSegment,
                VoiceProfileVersion,
            )
            .join(
                NarrationEditionSegment,
                NarrationEditionSegment.edition_id == NarrationEdition.id,
            )
            .join(
                NarrationSegment,
                NarrationSegment.id == NarrationEditionSegment.segment_id,
            )
            .join(
                VoiceProfileVersion,
                VoiceProfileVersion.id == NarrationEditionSegment.voice_version_id,
            )
            .where(
                NarrationEdition.request_id == job.request_id,
                NarrationEdition.novel_id == job.novel_id,
                NarrationEditionSegment.render_fingerprint == render.render_fingerprint,
            )
            .order_by(NarrationEdition.id.asc(), NarrationEditionSegment.ordinal.asc())
        )
        if for_update:
            statement = statement.with_for_update()
        matches = session.execute(
            statement.execution_options(populate_existing=True)
        ).all()
        if not matches:
            raise InvalidNarrationState(
                "render job must resolve to an Edition segment in its request"
            )
        sources = [
            match
            for match in matches
            if job.input_hash
            == render_job_input_hash(
                edition_segment_id=match[1].id,
                render_fingerprint=render.render_fingerprint,
            )
        ]
        if len(sources) != 1:
            raise InvalidNarrationState(
                "render job input does not name one canonical source segment"
            )
        edition, edition_segment, segment, voice = sources[0]
        store = SqlAlchemyNarrationStore(session)
        fanout_segments: dict[UUID, NarrationEditionSegment] = {}
        fanout_editions: dict[UUID, NarrationEdition] = {}
        for (
            candidate_edition,
            candidate_edition_segment,
            candidate_segment,
            candidate_voice,
        ) in matches:
            if (
                render.owner_id != job.owner_id
                or render.workspace_id != job.workspace_id
                or render.novel_id != job.novel_id
                or render.request_id != job.request_id
                or candidate_edition.owner_id != job.owner_id
                or candidate_edition.workspace_id != job.workspace_id
                or candidate_edition.novel_id != job.novel_id
                or candidate_edition.request_id != job.request_id
                or candidate_edition.document_id != edition.document_id
                or render.voice_version_id != candidate_voice.id
                or candidate_edition_segment.profile_id
                != candidate_voice.profile_id
                or render.model_fingerprint
                != candidate_edition.tts_fingerprint
                or render.postprocess_fingerprint
                != candidate_edition.postprocess_fingerprint
                or candidate_edition_segment.render_fingerprint
                != render.render_fingerprint
                or candidate_segment.script_version_id
                != candidate_edition.script_version_id
                or (
                    validate_current_authority
                    and compute_render_fingerprint(
                        store,
                        CreateRender(
                            edition_segment_id=candidate_edition_segment.id,
                            digest_keyring=self._digest_keyring,
                        ),
                    )
                    != render.render_fingerprint
                )
            ):
                raise WorkerSecurityError(
                    "render work provenance is inconsistent"
                )
            fanout_segments[candidate_edition_segment.id] = (
                candidate_edition_segment
            )
            fanout_editions[candidate_edition.id] = candidate_edition
        return _RenderWorkRows(
            render=render,
            edition=edition,
            edition_segment=edition_segment,
            segment=segment,
            voice=voice,
            fanout_segments=tuple(fanout_segments.values()),
            fanout_editions=tuple(fanout_editions.values()),
        )

    def load_and_mark_running(
        self, lease: JobLease, *, actor: str
    ) -> SegmentWorkItem:
        def operation(session: Session) -> SegmentWorkItem:
            job = self._job(session, lease, for_update=True)
            if job.state != "running":
                raise JobFenceError("claimed job is no longer running")
            rows = self._work_rows(
                session, job=job, for_update=True
            )
            render = rows.render
            edition = rows.edition
            edition_segment = rows.edition_segment
            segment = rows.segment
            voice = rows.voice
            store = SqlAlchemyNarrationStore(session)
            _profile, usable_voice, _rights = require_usable_voice(
                store, voice.id, novel_id=edition.novel_id
            )
            if usable_voice.id != voice.id:
                raise WorkerSecurityError("usable voice authority changed")
            request = session.scalar(
                select(NarrationRequest)
                .where(NarrationRequest.id == edition.request_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if request is None:
                raise InvalidNarrationState("render request does not exist")
            if request.state == "queued":
                request = advance_request_state(
                    store,
                    request.id,
                    expected_version=request.version,
                    new_state="rendering",
                    novel_id=edition.novel_id,
                    actor=actor,
                )
            elif request.state not in {"rendering", "partial_ready"}:
                raise InvalidNarrationState("render request no longer accepts worker execution")
            for fanout_edition in rows.fanout_editions:
                if fanout_edition.state == "created":
                    fanout_edition.state = "rendering"
                elif fanout_edition.state not in {"rendering", "partial_ready"}:
                    raise InvalidNarrationState(
                        "Edition no longer accepts worker execution"
                    )
            for fanout_segment in rows.fanout_segments:
                if fanout_segment.render_state in {"pending", "queued"}:
                    advance_edition_segment_state(
                        store, fanout_segment.id, new_state="rendering"
                    )
                elif fanout_segment.render_state != "rendering":
                    raise InvalidNarrationState(
                        "Edition segment is no longer renderable"
                    )
            if render.state == "pending":
                render.state = "rendering"
            elif render.state != "rendering":
                raise InvalidNarrationState("render row is no longer in flight")

            snapshot = session.get(
                NarrationSettingsSnapshot,
                edition.settings_snapshot_id,
            )
            if (
                snapshot is None
                or snapshot.owner_id != job.owner_id
                or snapshot.workspace_id != job.workspace_id
                or snapshot.novel_id != job.novel_id
                or snapshot.fingerprint != request.settings_fingerprint
            ):
                raise WorkerSecurityError("render settings snapshot is inconsistent")
            try:
                selection = selection_from_settings_snapshot(snapshot.snapshot_json)
            except ValueError as error:
                raise WorkerContractError(
                    "render TTS Provider selection is invalid"
                ) from error
            if (
                selection_fingerprint(selection) != render.model_fingerprint
                or render.model_fingerprint != edition.tts_fingerprint
            ):
                raise WorkerSecurityError(
                    "render TTS Provider selection fingerprint changed"
                )
            voice_kind, provider_voice_id, instruction = _qwen_voice_parameters(
                voice,
                selection,
            )
            if (
                voice.provider_id not in {None, "qwen-tts"}
                and voice.provider_id != selection.provider_id
            ):
                raise WorkerSecurityError("voice belongs to another TTS Provider")
            requested_model_id = (
                selection.aliyun_model_id
                if selection.provider_id == "aliyun_qwen_audio_tts"
                else voice.model_id
            )
            if (
                selection.provider_id == "aliyun_qwen_audio_tts"
                and voice.provider_id != "qwen-tts"
                and voice.model_id is not None
                and voice.model_id != requested_model_id
            ):
                raise WorkerSecurityError("voice belongs to another TTS model")
            reference: ReferenceMedia | None = None
            if voice.reference_asset_id is not None:
                asset = session.get(MediaAsset, voice.reference_asset_id)
                if (
                    asset is None
                    or asset.owner_id != job.owner_id
                    or asset.workspace_id != job.workspace_id
                    or asset.novel_id not in {None, job.novel_id}
                    or asset.state != "ready"
                    or asset.asset_class != "voice_reference"
                    or asset.checksum_algorithm != "sha256"
                    or not asset.storage_path
                    or not asset.content_hash
                    or not asset.byte_size
                    or asset.mime_type not in {"audio/wav", "audio/flac"}
                ):
                    raise WorkerSecurityError("voice reference media is not authoritative")
                reference = ReferenceMedia(
                    relative_path=asset.storage_path,
                    actual_sha256=asset.content_hash,
                    byte_size=asset.byte_size,
                    content_type=asset.mime_type,
                )
            request_parameters = {
                "schema_version": "qwen-tts-worker-synthesis/1",
                "render_fingerprint": render.render_fingerprint,
                "voice_version_id": str(voice.id),
                "voice_fingerprint": voice.fingerprint,
                "selection": selection.model_dump(mode="json"),
                "language": voice.language,
                "voice_kind": voice_kind.value,
                "provider_voice_id": provider_voice_id,
                "seed": voice.seed,
                "instruction": instruction,
            }
            provider_metadata = canonical_json_bytes(
                {
                    **request_parameters,
                    "request_id": str(lease.fence.attempt_id),
                    "scope": {
                        "owner_id": str(self._scope.owner_id),
                        "workspace_id": str(self._scope.workspace_id),
                        "app_id": self._scope.app_id,
                        "is_local_only": self._scope.is_local_only,
                    },
                    "text": segment.spoken_text,
                    "reference_content_type": (
                        reference.content_type if reference else None
                    ),
                    "reference_actual_sha256": (
                        reference.actual_sha256 if reference else None
                    ),
                    "reference_size_bytes": (
                        reference.byte_size if reference else None
                    ),
                }
            )
            input_digest_key_id, input_digest = derive_model_input_digest(
                self._digest_keyring.active,
                provider_metadata=provider_metadata,
            )
            session.flush()
            return SegmentWorkItem(
                lease=lease,
                render_id=render.id,
                edition_id=edition.id,
                edition_segment_id=edition_segment.id,
                request_id=request.id,
                novel_id=edition.novel_id,
                text=segment.spoken_text,
                selection=selection,
                language=voice.language,
                voice_kind=voice_kind,
                provider_voice_id=provider_voice_id,
                seed=voice.seed,
                instruction=instruction,
                requested_provider_id=selection.provider_id,
                requested_model_id=requested_model_id,
                requested_revision=voice.model_revision,
                expected_model_fingerprint=render.model_fingerprint,
                expected_postprocess_fingerprint=render.postprocess_fingerprint,
                parameters_digest=canonical_sha256(request_parameters),
                input_digest_key_id=input_digest_key_id,
                input_digest=input_digest,
                reference_media=reference,
            )

        result = self._transaction(operation)
        if type(result) is not SegmentWorkItem:
            raise RuntimeError("worker load returned an invalid work item")
        return result

    def read_job_state(self, lease: JobLease) -> str:
        def operation(session: Session) -> str:
            return self._job(session, lease, for_update=False).state

        result = self._transaction(operation)
        if type(result) is not str:
            raise RuntimeError("job state read returned an invalid value")
        return result

    def heartbeat_and_read_state(self, lease: JobLease) -> str:
        def operation(session: Session) -> str:
            job = self._job(session, lease, for_update=True)
            if job.state == "running":
                heartbeat_attempt(
                    session,
                    scope=self._scope,
                    fence=lease.fence,
                )
            return job.state

        result = self._transaction(operation)
        if type(result) is not str:
            raise RuntimeError("worker heartbeat returned an invalid state")
        return result

    @staticmethod
    def _append_terminal_model_run(
        session: Session,
        work: SegmentWorkItem,
        *,
        result_classification: Literal[
            "retryable_failure",
            "non_retryable_failure",
            "cancelled",
            "security_failure",
        ],
    ) -> None:
        existing = session.scalar(
            select(ModelRunRecord).where(
                ModelRunRecord.attempt_id == work.lease.fence.attempt_id
            )
        )
        if existing is not None:
            raise InvalidNarrationState(
                "the active attempt already has model-run evidence"
            )
        session.add(
            ModelRunRecord(
                attempt_id=work.lease.fence.attempt_id,
                requested_provider_id=work.requested_provider_id,
                requested_model_id=work.requested_model_id or "provider-selected",
                requested_revision=work.requested_revision,
                actual_provider_id=None,
                actual_model_id=None,
                actual_revision=None,
                model_fingerprint=None,
                parameters_digest=work.parameters_digest,
                input_digest_key_id=work.input_digest_key_id,
                input_digest=work.input_digest,
                output_digest=None,
                duration_ms=None,
                provider_request_id=str(work.lease.fence.attempt_id),
                result_classification=result_classification,
            )
        )
        session.flush()

    def acknowledge_cancel(self, work: SegmentWorkItem) -> None:
        def operation(session: Session) -> None:
            job = self._job(session, work.lease, for_update=True)
            rows = self._work_rows(
                session, job=job, for_update=True
            )
            self._append_terminal_model_run(
                session,
                work,
                result_classification="cancelled",
            )
            acknowledge_cancel(
                session,
                scope=self._scope,
                fence=work.lease.fence,
            )
            store = SqlAlchemyNarrationStore(session)
            if rows.render.state in {"pending", "rendering"}:
                rows.render.state = "cancelled"
            for segment in rows.fanout_segments:
                if segment.render_state in {"pending", "queued", "rendering"}:
                    advance_edition_segment_state(
                        store,
                        segment.id,
                        new_state="cancelled",
                    )
            session.flush()

        self._transaction(operation)

    @staticmethod
    def _manifest_inputs(
        store: SqlAlchemyNarrationStore,
        edition: NarrationEdition,
    ) -> tuple[ManifestSegmentInput, ...]:
        rows = store.find_all(
            NarrationEditionSegment,
            edition_id=edition.id,
            order_by=("ordinal",),
            for_update=True,
        )
        inputs: list[ManifestSegmentInput] = []
        for row in rows:
            if row.render_state == "ready":
                render = store.find_one(
                    NarrationSegmentRender,
                    owner_id=edition.owner_id,
                    workspace_id=edition.workspace_id,
                    render_fingerprint=row.render_fingerprint,
                )
                if render is None or render.state != "ready":
                    raise InvalidNarrationState("ready Edition segment has no ready render")
                inputs.append(
                    ManifestSegmentInput(
                        edition_segment_id=row.id,
                        render_status="ready",
                        render_id=render.id,
                    )
                )
            elif row.render_state == "failed":
                inputs.append(
                    ManifestSegmentInput(
                        edition_segment_id=row.id,
                        render_status="failed",
                        failure=ManifestFailure(
                            code=row.failure_code or "SEGMENT_RENDER_FAILED",
                            retryable=False,
                            message="该句段生成失败，可稍后重新生成。",
                        ),
                    )
                )
            else:
                status = (
                    "cancelled"
                    if row.render_state in {"cancelled", "quarantined"}
                    else row.render_state
                )
                inputs.append(
                    ManifestSegmentInput(
                        edition_segment_id=row.id,
                        render_status=status,
                    )
                )
        return tuple(inputs)

    def _terminalize_render_job_in_session(
        self,
        session: Session,
        *,
        job: BackgroundJob,
        target_state: Literal["failed", "cancelled"],
        error_code: str,
        actor: str,
        failure_evidence: Mapping[str, object] | None = None,
    ) -> bool:
        """Close render fanout and append failure state in the caller's tx."""

        if (
            type(error_code) is not str
            or not error_code
            or error_code != error_code.strip()
            or len(error_code) > 96
        ):
            raise WorkerContractError("terminal render requires a canonical error code")
        if job.request_id is None or job.novel_id is None:
            raise WorkerSecurityError("terminal render job has no request/novel scope")
        rows = self._work_rows(
            session,
            job=job,
            for_update=True,
            validate_current_authority=False,
        )
        if rows.render.state == target_state and all(
            segment.render_state == target_state
            for segment in rows.fanout_segments
        ):
            return False
        if rows.render.state not in {"pending", "rendering"}:
            raise InvalidNarrationState(
                "terminal job cannot overwrite a terminal render"
            )
        rows.render.state = target_state
        if failure_evidence is not None:
            rows.render.audio_validation_json = dict(failure_evidence)

        store = SqlAlchemyNarrationStore(session)
        for segment in rows.fanout_segments:
            if segment.render_state in {"pending", "queued", "rendering"}:
                advance_edition_segment_state(
                    store,
                    segment.id,
                    new_state=target_state,
                    failure_code=(error_code if target_state == "failed" else None),
                )
            elif segment.render_state != target_state:
                raise InvalidNarrationState(
                    "terminal job cannot overwrite a terminal Edition segment"
                )

        for edition in rows.fanout_editions:
            pointer = store.find_one(
                NarrationEditionState,
                edition_id=edition.id,
                for_update=True,
            )
            edition_segments = store.find_all(
                NarrationEditionSegment,
                edition_id=edition.id,
                order_by=("ordinal",),
            )
            terminal = all(
                segment.render_state
                in {"ready", "failed", "cancelled", "quarantined"}
                for segment in edition_segments
            )
            has_ready = any(
                segment.render_state == "ready" for segment in edition_segments
            )
            # Before any segment is playable, a partially terminalized Edition
            # still has public status ``pending`` and the Manifest contract
            # correctly rejects it.  Wait for either a playable segment or the
            # whole Edition to become terminal; otherwise recovery of one old
            # attempt would poison the scheduler maintenance loop.
            if has_ready or terminal:
                append_manifest_revision(
                    store,
                    PublishManifest(
                        edition_id=edition.id,
                        expected_current_revision=(
                            pointer.current_manifest_revision
                            if pointer is not None
                            else 0
                        ),
                        expected_state_version=(
                            pointer.version if pointer is not None else 0
                        ),
                        buffer_policy=BUFFER_POLICIES[edition.buffer_policy_version],
                        segments=self._manifest_inputs(store, edition),
                        updated_actor=actor,
                    ),
                )
            if terminal and not has_ready:
                edition.state = "unavailable"
                edition.unavailable_reason = error_code
            elif has_ready and edition.state in {"created", "rendering"}:
                edition.state = "partial_ready"
                edition.unavailable_reason = None

        if target_state == "failed":
            request_editions = store.find_all(
                NarrationEdition,
                request_id=job.request_id,
            )
            request = store.get(NarrationRequest, job.request_id)
            if (
                request is not None
                and request_editions
                and all(
                    edition.state == "unavailable"
                    for edition in request_editions
                )
                and request.state in {"queued", "rendering", "partial_ready"}
            ):
                advance_request_state(
                    store,
                    request.id,
                    expected_version=request.version,
                    new_state="failed",
                    novel_id=job.novel_id,
                    actor=actor,
                    reason_code=error_code,
                )
        session.flush()
        return True

    def terminalize_job_in_session(
        self,
        session: Session,
        *,
        job_id: UUID,
    ) -> bool:
        """Close one reconciled terminal segment job before its tx commits."""

        job = session.scalar(
            select(BackgroundJob)
            .where(
                BackgroundJob.id == job_id,
                BackgroundJob.owner_id == self._scope.owner_id,
                BackgroundJob.workspace_id == self._scope.workspace_id,
                BackgroundJob.job_kind == "narration.segment_render",
                BackgroundJob.resource_class == "qwen-tts",
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if job is None:
            raise NarrationScopeMismatch(
                "terminal render job is outside fixed local scope"
            )
        if job.state in {"failed", "dead_letter"}:
            return self._terminalize_render_job_in_session(
                session,
                job=job,
                target_state="failed",
                error_code=job.error_code or "SEGMENT_RENDER_FAILED",
                actor="narration-worker-expired-attempt",
            )
        if job.state == "cancelled":
            return self._terminalize_render_job_in_session(
                session,
                job=job,
                target_state="cancelled",
                error_code="SEGMENT_RENDER_CANCELLED",
                actor="narration-worker-expired-attempt",
            )
        return False

    def publish(self, work: SegmentWorkItem, prepared: PreparedRender, *, actor: str) -> None:
        def operation(session: Session) -> None:
            context = lock_result_publish_fences(
                session,
                scope=self._scope,
                job_fence=work.lease.fence,
                resource_fence=work.lease.resource_fence,  # type: ignore[arg-type]
            )
            job = self._job(session, work.lease, for_update=True)
            if job.request_id is None or job.novel_id is None:
                raise WorkerSecurityError(
                    "render publication job has no request/document scope"
                )
            request = session.scalar(
                select(NarrationRequest)
                .where(NarrationRequest.id == job.request_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if (
                request is None
                or request.id != work.request_id
                or request.owner_id != job.owner_id
                or request.workspace_id != job.workspace_id
                or request.novel_id != job.novel_id
            ):
                raise WorkerSecurityError(
                    "render publication request is outside the job scope"
                )
            document_id = session.scalar(
                select(NarrationEdition.document_id).where(
                    NarrationEdition.id == work.edition_id,
                    NarrationEdition.request_id == request.id,
                    NarrationEdition.novel_id == request.novel_id,
                )
            )
            if document_id is None:
                raise WorkerSecurityError(
                    "render publication Edition has no document scope"
                )
            document = session.scalar(
                select(Document)
                .where(
                    Document.id == document_id,
                    Document.novel_id == request.novel_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if document is None or request.document_id not in {
                None,
                document.id,
            }:
                raise WorkerSecurityError(
                    "render publication document differs from its request"
                )
            rows = self._work_rows(
                session,
                job=job,
                for_update=True,
            )
            render_row = rows.render
            edition = rows.edition
            edition_segment = rows.edition_segment
            if (
                render_row.id != work.render_id
                or edition.id != work.edition_id
                or edition.document_id != document.id
                or edition_segment.id != work.edition_segment_id
                or render_row.postprocess_fingerprint
                != work.expected_postprocess_fingerprint
            ):
                raise WorkerSecurityError(
                    "postprocess publication provenance changed after rendering"
                )
            render = publish_render_result_in_session(
                session,
                self._storage,
                render_id=work.render_id,
                publication_context=context,
                audio=prepared.audio,
                model=prepared.model,
            )
            store = SqlAlchemyNarrationStore(session)
            for fanout_segment in rows.fanout_segments:
                advance_edition_segment_state(
                    store,
                    fanout_segment.id,
                    new_state="ready",
                )
            manifests = []
            source_manifest = None
            for fanout_edition in rows.fanout_editions:
                state = session.get(NarrationEditionState, fanout_edition.id)
                manifest = publish_manifest(
                    store,
                    PublishManifest(
                        edition_id=fanout_edition.id,
                        expected_current_revision=(
                            state.current_manifest_revision
                            if state is not None
                            else 0
                        ),
                        expected_state_version=(
                            state.version if state is not None else 0
                        ),
                        buffer_policy=BUFFER_POLICIES[
                            fanout_edition.buffer_policy_version
                        ],
                        segments=self._manifest_inputs(
                            store,
                            fanout_edition,
                        ),
                        updated_actor=actor,
                    ),
                )
                manifests.append(manifest)
                if fanout_edition.id == edition.id:
                    source_manifest = manifest
            if source_manifest is None:
                raise InvalidNarrationState(
                    "published render source Edition disappeared"
                )
            target = (
                "ready"
                if all(manifest.status == "ready" for manifest in manifests)
                else "partial_ready"
            )
            if request.state != target:
                request = advance_request_state(
                    store,
                    request.id,
                    expected_version=request.version,
                    new_state=target,
                    novel_id=work.novel_id,
                    actor=actor,
                )
            if render.state != "ready":
                raise InvalidNarrationState("render publication did not become ready")
            initialize_initial_document_edition(
                store,
                request_id=request.id,
                document_id=document.id,
                edition_id=edition.id,
                manifest_id=source_manifest.id,
                scope=self._scope,
            )

        if not hasattr(self, "_storage"):
            raise RuntimeError("worker repository storage was not bound")
        self._transaction(operation)

    def bind_storage(self, storage: NarrationStorage) -> None:
        if type(storage) is not NarrationStorage:
            raise TypeError("worker repository requires NarrationStorage")
        self._storage = storage

    def fail(
        self,
        work: SegmentWorkItem,
        *,
        classification: Literal["retryable", "non_retryable", "security_failure"],
        error_code: str,
        failure_evidence: Mapping[str, object] | None = None,
    ) -> FailureResult:
        if failure_evidence is not None:
            if (
                classification != "non_retryable"
                or error_code != "TTS_AUDIO_INVALID"
                or type(failure_evidence) is not dict
                or set(failure_evidence) != {"schema_version", "reason_code"}
                or failure_evidence.get("schema_version")
                != "narration-audio-validation-failure/1"
                or type(failure_evidence.get("reason_code")) is not str
                or failure_evidence["reason_code"]
                not in AUDIO_VALIDATION_FAILURE_REASON_CODES
            ):
                raise WorkerContractError("worker failure evidence is invalid")
            frozen_failure_evidence = dict(failure_evidence)
        else:
            frozen_failure_evidence = None

        def operation(session: Session) -> FailureResult:
            model_classification = {
                "retryable": "retryable_failure",
                "non_retryable": "non_retryable_failure",
                "security_failure": "security_failure",
            }[classification]
            self._append_terminal_model_run(
                session,
                work,
                result_classification=model_classification,  # type: ignore[arg-type]
            )
            result = fail_attempt(
                session,
                scope=self._scope,
                fence=work.lease.fence,
                classification=classification,
                error_code=error_code,
            )
            if result.state in {"failed", "dead_letter"}:
                job = self._job(session, work.lease, for_update=True)
                self._terminalize_render_job_in_session(
                    session,
                    job=job,
                    target_state="failed",
                    error_code=error_code,
                    actor="narration-worker",
                    failure_evidence=frozen_failure_evidence,
                )
            return result

        result = self._transaction(operation)
        if type(result) is not FailureResult:
            raise RuntimeError("worker failure transaction returned an invalid result")
        return result

    def fail_claim(
        self,
        lease: JobLease,
        *,
        classification: Literal["retryable", "non_retryable", "security_failure"],
        error_code: str,
    ) -> FailureResult:
        """Fence a claim that failed before a safe domain work item was loaded."""

        def operation(session: Session) -> FailureResult:
            job = self._job(session, lease, for_update=True)
            result = fail_attempt(
                session,
                scope=self._scope,
                fence=lease.fence,
                classification=classification,
                error_code=error_code,
            )
            if result.state in {"failed", "dead_letter"}:
                self._terminalize_render_job_in_session(
                    session,
                    job=job,
                    target_state="failed",
                    error_code=error_code,
                    actor="narration-worker-load-failure",
                )
            return result

        result = self._transaction(operation)
        if type(result) is not FailureResult:
            raise RuntimeError("worker claim failure returned an invalid result")
        return result


class FixedFfmpegTranscoder:
    """Callable fixed-toolchain adapter used outside database transactions."""

    def __init__(
        self,
        *,
        ffmpeg_path: Path,
        ffprobe_path: Path,
        policy: TranscodingPolicy = DEFAULT_TRANSCODING_POLICY,
    ) -> None:
        self._ffmpeg_path = ffmpeg_path
        self._ffprobe_path = ffprobe_path
        self._policy = policy

    def __call__(self, processed: ProcessedPcmWav) -> TranscodedSegment:
        return transcode_segment(
            processed,
            ffmpeg_path=self._ffmpeg_path,
            ffprobe_path=self._ffprobe_path,
            policy=self._policy,
        )


class NarrationSegmentWorker:
    def __init__(
        self,
        *,
        scheduler: NarrationJobScheduler,
        repository: WorkerRepository,
        execution: TTSExecutionService,
        storage: NarrationStorage,
        transcode: Callable[[ProcessedPcmWav], TranscodedSegment],
        config: NarrationWorkerConfig,
        disk_guard: Callable[[], None] | None = None,
    ) -> None:
        config.validate()
        if not callable(transcode):
            raise TypeError("worker requires a callable transcoder")
        self._scheduler = scheduler
        self._repository = repository
        self._execution = execution
        self._storage = storage
        self._transcode = transcode
        self._config = config
        if disk_guard is not None and not callable(disk_guard):
            raise TypeError("worker disk_guard must be callable")
        self._disk_guard = disk_guard
        bind_storage = getattr(repository, "bind_storage", None)
        if callable(bind_storage):
            bind_storage(storage)

    def _reference_input(self, reference: ReferenceMedia | None) -> ReferenceAudioInput | None:
        if reference is None:
            return None
        if reference.byte_size > self._config.max_reference_bytes:
            raise WorkerSecurityError("voice reference exceeds the worker byte bound")
        identity = self._storage.verify_media_identity(
            reference.relative_path,
            expected_sha256=reference.actual_sha256,
            expected_size=reference.byte_size,
            max_bytes=self._config.max_reference_bytes,
        )
        payload = b"".join(
            self._storage.stream_media(
                reference.relative_path,
                expected_device=identity.device,
                expected_inode=identity.inode,
                expected_size=identity.byte_size,
            )
        )
        return ReferenceAudioInput(
            audio_bytes=payload,
            actual_sha256=reference.actual_sha256,
            content_type=reference.content_type,
        )

    async def _synthesize(self, work: SegmentWorkItem) -> object:
        reference = (
            await asyncio.to_thread(self._reference_input, work.reference_media)
            if work.selection.provider_id == "local_qwen3_tts"
            else None
        )
        request = TTSSynthesisRequest(
            request_id=work.lease.fence.attempt_id,
            scope=NarrationRequestScope.fixed_local(),
            text=work.text,
            language=work.language,
            voice=TTSVoiceInput(
                kind=work.voice_kind,
                provider_voice_id=work.provider_voice_id,
                reference_audio=reference,
            ),
            seed=work.seed,
            instruction=work.instruction,
            audio_format=TTSAudioFormat.WAV,
        )
        task = asyncio.create_task(
            self._execution.synthesize(
                novel_id=work.novel_id,
                selection=work.selection,
                request=request,
            )
        )
        cancellation_sent = False
        try:
            while True:
                try:
                    return await asyncio.wait_for(
                        asyncio.shield(task),
                        timeout=float(self._config.heartbeat_seconds),
                    )
                except TimeoutError:
                    state = await asyncio.to_thread(
                        self._repository.heartbeat_and_read_state, work.lease
                    )
                    if state == "cancel_requested" and not cancellation_sent:
                        cancellation_sent = True
                        await self._execution.cancel(
                            selection=work.selection,
                            request_id=request.request_id,
                        )
                    elif state not in {"running", "cancel_requested"}:
                        task.cancel()
                        try:
                            await task
                        except (asyncio.CancelledError, Exception):
                            pass
                        raise JobFenceError("job became terminal during synthesis")
        except asyncio.CancelledError:
            # PawApp shutdown must not leave a shielded Provider request running
            # after the local worker task has disappeared.
            if not task.done():
                try:
                    await self._execution.cancel(
                        selection=work.selection,
                        request_id=request.request_id,
                    )
                finally:
                    task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
            raise

    def _prepare(self, work: SegmentWorkItem, synthesis: object) -> PreparedRender:
        if type(synthesis) is not TTSSynthesisResult:
            raise WorkerContractError("TTS Provider returned an invalid result type")
        if synthesis.request_id != work.lease.fence.attempt_id:
            raise WorkerSecurityError("TTS result belongs to another attempt")
        identity = synthesis.model_identity
        if identity.provider_id.value != work.selection.provider_id:
            raise WorkerSecurityError("TTS result belongs to another Provider")
        if (
            work.requested_model_id is not None
            and identity.model_id != work.requested_model_id
        ):
            raise WorkerSecurityError("TTS result belongs to another requested model")
        processed = process_provider_synthesis_wav(
            synthesis.audio_bytes,
            declared_sample_rate_hz=synthesis.sample_rate_hz,
            declared_channels=synthesis.channels,
            declared_sample_width_bytes=synthesis.sample_width_bytes,
            spoken_text=work.text,
        )
        transcoded = self._transcode(processed)
        if type(transcoded) is not TranscodedSegment:
            raise WorkerContractError("transcoder returned an invalid result type")
        if (
            type(transcoded.processing_fingerprint) is not str
            or transcoded.processing_fingerprint
            != work.expected_postprocess_fingerprint
        ):
            raise WorkerSecurityError(
                "transcoded audio differs from the Edition postprocess fingerprint"
            )
        # Capacity may change while Provider inference and FFmpeg are running. Recheck on
        # the same worker thread immediately before the first physical media
        # publication; the scheduler-side guard only protects job claiming.
        if self._disk_guard is not None:
            self._disk_guard()
        master = self._storage.publish_or_verify_media(
            (transcoded.master.audio_bytes,),
            asset_id=render_asset_id(work.render_id, "master"),
            expected_sha256=transcoded.master.actual_sha256,
            expected_size=transcoded.master.byte_size,
            extension=transcoded.master.extension,
            max_bytes=DEFAULT_TRANSCODING_POLICY.maximum_master_bytes,
        )
        playback = self._storage.publish_or_verify_media(
            (transcoded.playback.audio_bytes,),
            asset_id=render_asset_id(work.render_id, "playback"),
            expected_sha256=transcoded.playback.actual_sha256,
            expected_size=transcoded.playback.byte_size,
            extension=transcoded.playback.extension,
            max_bytes=DEFAULT_TRANSCODING_POLICY.maximum_playback_bytes,
        )
        duration_ms = processed.duration_ms
        return PreparedRender(
            audio=RenderAudioEvidence(
                master=master,
                playback=playback,
                duration_ms=duration_ms,
                sample_rate=processed.sample_rate_hz,
                channels=processed.channels,
                master_mime_type=transcoded.master.mime_type,
                playback_mime_type=transcoded.playback.mime_type,
            ),
            model=ModelRunSuccessEvidence(
                requested_provider_id=work.requested_provider_id,
                requested_model_id=work.requested_model_id or "provider-selected",
                requested_revision=work.requested_revision,
                actual_provider_id=identity.provider_id.value,
                actual_model_id=identity.model_id,
                actual_revision=identity.model_revision,
                # The persisted render identity is the frozen Provider selection
                # fingerprint, not a claim about one Provider artifact tree.
                model_fingerprint=work.expected_model_fingerprint,
                parameters_digest=work.parameters_digest,
                input_digest_key_id=work.input_digest_key_id,
                input_digest=work.input_digest,
                duration_ms=duration_ms,
                provider_request_id=str(work.lease.fence.attempt_id),
            ),
        )

    @staticmethod
    def _classification(error: BaseException) -> tuple[
        Literal["retryable", "non_retryable", "security_failure"], str
    ]:
        if isinstance(error, WorkerSecurityError):
            return "security_failure", "WORKER_SECURITY_FAILURE"
        if isinstance(error, WorkerVoiceUnavailableError):
            return "non_retryable", "TTS_VOICE_UNAVAILABLE"
        if isinstance(error, NarrationDiskGuardError):
            return "retryable", error.code
        if isinstance(error, (UnsafeStoragePath, StorageRootChanged)):
            return "security_failure", "STORAGE_IDENTITY_FAILURE"
        if isinstance(error, TTSProviderError):
            return (
                "retryable" if error.retryable else "non_retryable",
                error.code,
            )
        if isinstance(error, TranscodingUnavailable):
            return "retryable", "TRANSCODER_UNAVAILABLE"
        if isinstance(error, (AudioFormatError, AudioQualityError)):
            return "non_retryable", "TTS_AUDIO_INVALID"
        if isinstance(error, (TranscodingValidationError, PublicationValidationError)):
            return "non_retryable", "AUDIO_PUBLICATION_INVALID"
        if isinstance(error, (TranscodingError, StorageError, OSError)):
            return "retryable", "AUDIO_PIPELINE_TEMPORARY_FAILURE"
        if isinstance(error, (WorkerContractError, AudioPipelineError, InvalidNarrationState)):
            return "non_retryable", "RENDER_INPUT_INVALID"
        return "retryable", "WORKER_UNEXPECTED_FAILURE"

    _failure_evidence = staticmethod(audio_validation_failure_evidence)

    async def run_once(self) -> WorkerOutcome:
        lease = await asyncio.to_thread(self._scheduler.claim_next_segment)
        if lease is None:
            return WorkerOutcome(status="idle")
        return await self.process(lease)

    async def process(self, lease: JobLease) -> WorkerOutcome:
        """Process one lease already claimed by the shared fair dispatcher."""

        if type(lease) is not JobLease:
            raise TypeError("segment worker requires a JobLease")
        if lease.resource_fence is None:
            try:
                failure = await asyncio.to_thread(
                    self._repository.fail_claim,
                    lease,
                    classification="security_failure",
                    error_code="RESOURCE_FENCE_MISSING",
                )
                return WorkerOutcome(
                    status=failure.state,
                    job_id=lease.fence.job_id,
                    error_code="RESOURCE_FENCE_MISSING",
                )
            except JobFenceError:
                return WorkerOutcome(
                    status="stale",
                    job_id=lease.fence.job_id,
                    error_code="STALE_WORKER_FENCE",
                )
        work: SegmentWorkItem | None = None
        try:
            work = await asyncio.to_thread(
                self._repository.load_and_mark_running,
                lease,
                actor=self._config.actor,
            )
            if self._disk_guard is not None:
                await asyncio.to_thread(self._disk_guard)
            synthesis = await self._synthesize(work)
            state = await asyncio.to_thread(self._repository.read_job_state, lease)
            if state == "cancel_requested":
                await asyncio.to_thread(self._repository.acknowledge_cancel, work)
                return WorkerOutcome(
                    status="cancelled",
                    job_id=lease.fence.job_id,
                    render_id=work.render_id,
                )
            if state != "running":
                raise JobFenceError("job stopped accepting a result")
            prepared = await asyncio.to_thread(self._prepare, work, synthesis)
            state = await asyncio.to_thread(self._repository.read_job_state, lease)
            if state == "cancel_requested":
                await asyncio.to_thread(self._repository.acknowledge_cancel, work)
                return WorkerOutcome(
                    status="cancelled",
                    job_id=lease.fence.job_id,
                    render_id=work.render_id,
                )
            if state != "running":
                raise JobFenceError("job stopped accepting publication")
            await asyncio.to_thread(
                self._repository.publish,
                work,
                prepared,
                actor=self._config.actor,
            )
            return WorkerOutcome(
                status="succeeded",
                job_id=lease.fence.job_id,
                render_id=work.render_id,
            )
        except JobFenceError:
            return WorkerOutcome(
                status="stale",
                job_id=lease.fence.job_id,
                render_id=work.render_id if work else None,
                error_code="STALE_WORKER_FENCE",
            )
        except Exception as error:
            logger.exception(
                "narration segment worker failed",
                extra={
                    "job_id": str(lease.fence.job_id),
                    "error_type": type(error).__name__,
                },
            )
            if work is None:
                classification, error_code = self._classification(error)
                try:
                    failure = await asyncio.to_thread(
                        self._repository.fail_claim,
                        lease,
                        classification=classification,
                        error_code=error_code,
                    )
                except JobFenceError:
                    return WorkerOutcome(
                        status="stale",
                        job_id=lease.fence.job_id,
                        error_code="STALE_WORKER_FENCE",
                    )
                return WorkerOutcome(
                    status=failure.state,
                    job_id=lease.fence.job_id,
                    error_code=error_code,
                )
            try:
                state = await asyncio.to_thread(self._repository.read_job_state, lease)
                if state == "cancel_requested":
                    await asyncio.to_thread(self._repository.acknowledge_cancel, work)
                    return WorkerOutcome(
                        status="cancelled",
                        job_id=lease.fence.job_id,
                        render_id=work.render_id,
                    )
                classification, error_code = self._classification(error)
                failure = await asyncio.to_thread(
                    self._repository.fail,
                    work,
                    classification=classification,
                    error_code=error_code,
                    failure_evidence=self._failure_evidence(error),
                )
                return WorkerOutcome(
                    status=failure.state,
                    job_id=lease.fence.job_id,
                    render_id=work.render_id,
                    error_code=error_code,
                )
            except JobFenceError:
                return WorkerOutcome(
                    status="stale",
                    job_id=lease.fence.job_id,
                    render_id=work.render_id,
                    error_code="STALE_WORKER_FENCE",
                )
            except Exception:
                # The attempt remains recoverable by the lease reconciler.  Do
                # not invent success or publish media when failure recording is
                # temporarily unavailable.
                return WorkerOutcome(
                    status="stale",
                    job_id=lease.fence.job_id,
                    render_id=work.render_id,
                    error_code="FAILURE_RECORDING_UNAVAILABLE",
                )

    async def run_until_stopped(
        self,
        stop_event: asyncio.Event,
        *,
        idle_poll_seconds: float = 0.5,
        maintenance_interval_seconds: float = 30.0,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        """Run one bounded local worker loop until PawApp shutdown.

        No extra process, queue, or container is introduced.  Maintenance and
        claims still open their own short transactions.  A temporary database
        outage is reported through ``on_error`` and retried after the bounded
        idle delay; cancellation of this coroutine propagates into the active
        Provider request through ``_synthesize``.
        """

        if type(stop_event) is not asyncio.Event:
            raise TypeError("worker loop requires an asyncio.Event")
        for name, value, minimum, maximum in (
            ("idle_poll_seconds", idle_poll_seconds, 0.01, 60.0),
            (
                "maintenance_interval_seconds",
                maintenance_interval_seconds,
                0.1,
                3_600.0,
            ),
        ):
            if not isinstance(value, (int, float)) or not minimum <= float(value) <= maximum:
                raise ValueError(f"worker loop {name} is outside its bounded range")
        if on_error is not None and not callable(on_error):
            raise TypeError("worker loop on_error must be callable")
        loop = asyncio.get_running_loop()
        next_maintenance = 0.0
        while not stop_event.is_set():
            try:
                current = loop.time()
                if current >= next_maintenance:
                    await asyncio.to_thread(self._scheduler.maintain_once)
                    next_maintenance = current + float(maintenance_interval_seconds)
                outcome = await self.run_once()
                wait_seconds = float(idle_poll_seconds) if outcome.status == "idle" else 0.0
            except asyncio.CancelledError:
                raise
            except Exception as error:
                if on_error is not None:
                    on_error(error)
                wait_seconds = float(idle_poll_seconds)
            if wait_seconds <= 0:
                await asyncio.sleep(0)
                continue
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=wait_seconds)
            except TimeoutError:
                pass


__all__ = [
    "AUDIO_VALIDATION_FAILURE_REASON_CODES",
    "MODEL_INPUT_DIGEST_PURPOSE",
    "MODEL_INPUT_DIGEST_SCHEMA_VERSION",
    "FixedFfmpegTranscoder",
    "NarrationSegmentWorker",
    "NarrationWorkerConfig",
    "PreparedRender",
    "ReferenceMedia",
    "SegmentWorkItem",
    "SqlAlchemyNarrationWorkerRepository",
    "WorkerContractError",
    "WorkerOutcome",
    "WorkerRepository",
    "WorkerSecurityError",
    "WorkerVoiceUnavailableError",
    "derive_model_input_digest",
]
