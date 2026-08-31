"""Single-slot VoiceGenerator -> Nano validation product processor."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from typing import Callable
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    BackgroundJob,
    MediaAsset,
    ModelRunRecord,
    NovelCharacter,
    VoiceDesignDraft,
    VoiceGeneratorCommand,
    VoiceGeneratorRunEvidence,
    VoiceProfile,
    VoiceProfileVersion,
    VoiceRightsEvent,
    VoiceRightsRecord,
)
from . import schemas as wire
from .audio_pipeline import process_synthesis_wav
from .contracts import (
    NanoDecodeParametersV2,
    NarrationRequestScope,
    ReferenceAudioInput,
    SynthesisResult,
    SynthesisRequest,
)
from .digest_keyring import DigestKeyring, private_text_digest
from .fingerprints import model_fingerprint_sha256
from .jobs import (
    JobFenceError,
    JobLease,
    acknowledge_cancel,
    complete_attempt,
    fail_attempt,
    heartbeat_attempt,
    lock_result_publish_fences,
)
from .nano_experiments import production_nano_experiment_identity
from .privacy import put_character_voice_binding
from .runtime import SidecarMossNanoTTSAdapter, SidecarRuntimeError
from .services import (
    InvalidNarrationState,
    NarrationCasConflict,
    NarrationNotFound,
    NarrationScopeMismatch,
    SqlAlchemyNarrationStore,
    canonical_sha256,
)
from .storage import NarrationStorage, PublishedFile
from .voice_generator_runtime import (
    EXPECTED_RUNTIME_FINGERPRINT,
    EXPECTED_RUNTIME_IDENTITY,
    HOST_PROTOCOL_VERSION,
    RUNTIME_TOPOLOGY,
    VOICE_GENERATOR_REVISION,
    HostGenerationReceipt,
    HostGenerationStatus,
    VoiceGeneratorHostRequest,
    VoiceGeneratorRuntimeError,
)
from .voice_generator_service import (
    VoiceGeneratorCommandState,
    VoiceGeneratorRuntimePort,
    ValidatedVoiceGeneratorResult,
    command_state_for_host_receipt,
    terminal_state_for_runtime_error,
    validate_runtime_completion,
)


def _transport_instruction_digest(instruction: str) -> str:
    """Digest the plaintext instruction for the native-host wire contract."""

    if not isinstance(instruction, str):
        raise TypeError("VoiceGenerator instruction must be text")
    return hashlib.sha256(instruction.encode("utf-8")).hexdigest()


VOICE_GENERATOR_MODEL_ID = "OpenMOSS-Team/MOSS-VoiceGenerator"
NANO_MODEL_ID = (
    "OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX+"
    "MOSS-Audio-Tokenizer-Nano-ONNX"
)
VALIDATION_TEXT_PURPOSE = "voice-generator-nano-validation"
MAX_GENERATED_AUDIO_BYTES = 4 * 1024 * 1024
MAX_VALIDATION_AUDIO_BYTES = 16 * 1024 * 1024

_VALIDATION_TEXT = {
    "zh-CN": "雨停之后，旧钟楼的回声依然清晰。",
    "en": "After the rain, the old clock tower still echoes clearly.",
    "ja-JP": "雨が上がったあとも、古い時計塔の響きは鮮明だった。",
}


SessionFactory = Callable[[], Session]


def _require_production_nano_result(result: SynthesisResult) -> str:
    identity = production_nano_experiment_identity()
    fingerprint = model_fingerprint_sha256(result.model_fingerprint)
    if (
        result.model_fingerprint.model_name != identity.actual_model_id
        or result.model_fingerprint.model_revision != identity.actual_revision
        or result.model_fingerprint.protocol_version != identity.sidecar_protocol_version
        or fingerprint != identity.model_fingerprint_sha256
    ):
        raise SidecarRuntimeError(
            "MODEL_FINGERPRINT_MISMATCH",
            "Nano validation model identity changed",
            poison=True,
        )
    return fingerprint


def _transaction(factory: SessionFactory, operation):
    with factory() as session:
        try:
            result = operation(session)
            session.commit()
            return result
        except BaseException:
            session.rollback()
            raise


@dataclass(frozen=True, slots=True)
class VoiceGeneratorWorkItem:
    lease: JobLease
    command_id: UUID
    novel_id: UUID
    character_id: UUID
    host_request: VoiceGeneratorHostRequest
    draft_fingerprint: str
    parameters_digest: str
    language: str
    seed: int


@dataclass(frozen=True, slots=True)
class PreparedVoiceGeneratorPublication:
    generated: PublishedFile
    validation: PublishedFile
    generator_result: ValidatedVoiceGeneratorResult
    nano_result: SynthesisResult
    nano_duration_ms: int
    nano_sample_rate_hz: int
    nano_channels: int
    nano_parameters_digest: str
    nano_input_digest_key_id: str
    nano_input_digest: str
    nano_model_fingerprint: str


class SqlAlchemyVoiceGeneratorRepository:
    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        digest_keyring: DigestKeyring,
    ) -> None:
        self._session_factory = session_factory
        self._digest_keyring = digest_keyring
        self._scope = NarrationRequestScope.fixed_local()

    def owns_job(self, job_id: UUID) -> bool:
        def operation(session: Session) -> bool:
            return session.scalar(
                select(VoiceGeneratorCommand.id).where(
                    VoiceGeneratorCommand.background_job_id == job_id
                )
            ) is not None

        return _transaction(self._session_factory, operation)

    @staticmethod
    def _command_for_job(
        session: Session, job_id: UUID, *, for_update: bool
    ) -> VoiceGeneratorCommand:
        statement = select(VoiceGeneratorCommand).where(
            VoiceGeneratorCommand.background_job_id == job_id
        )
        if for_update:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        row = session.scalar(statement)
        if row is None:
            raise NarrationNotFound("VoiceGenerator command for job not found")
        return row

    def load_and_mark_generating(self, lease: JobLease) -> VoiceGeneratorWorkItem:
        def operation(session: Session) -> VoiceGeneratorWorkItem:
            heartbeat_attempt(
                session,
                scope=self._scope,
                fence=lease.fence,
                progress_current=2,
                progress_total=6,
            )
            row = self._command_for_job(session, lease.fence.job_id, for_update=True)
            resumable_states = {
                VoiceGeneratorCommandState.WAITING_FOR_HEAVY_RUNTIME.value,
                VoiceGeneratorCommandState.GENERATING_VOICE.value,
                VoiceGeneratorCommandState.UNLOADING_VOICE_GENERATOR.value,
                VoiceGeneratorCommandState.VALIDATING_WITH_NANO.value,
            }
            if row.state not in resumable_states:
                raise InvalidNarrationState("VoiceGenerator command is not runnable")
            draft = session.get(VoiceDesignDraft, row.draft_id)
            if draft is None or draft.novel_id != row.novel_id or draft.character_id != row.character_id:
                raise NarrationScopeMismatch("VoiceGenerator draft scope changed")
            now = datetime.now(UTC)
            row.state = VoiceGeneratorCommandState.GENERATING_VOICE.value
            row.progress_current = 3
            row.updated_at = now
            session.flush()
            return VoiceGeneratorWorkItem(
                lease=lease,
                command_id=row.id,
                novel_id=row.novel_id,
                character_id=row.character_id,
                host_request=VoiceGeneratorHostRequest(
                    request_id=row.host_request_id,
                    instruction=draft.instruction,
                    # The durable draft digest is a keyed, privacy-preserving
                    # HMAC.  The native host receives the instruction itself,
                    # so its transport digest must be the plain SHA-256 that
                    # the frozen host protocol independently verifies.
                    instruction_digest=_transport_instruction_digest(
                        draft.instruction
                    ),
                    language=draft.language,
                    seed=draft.seed,
                ),
                draft_fingerprint=draft.fingerprint,
                parameters_digest=draft.parameters_digest,
                language=draft.language,
                seed=draft.seed,
            )

        return _transaction(self._session_factory, operation)

    def advance(
        self,
        work: VoiceGeneratorWorkItem,
        target: VoiceGeneratorCommandState,
    ) -> None:
        def operation(session: Session) -> None:
            heartbeat_attempt(session, scope=self._scope, fence=work.lease.fence)
            row = self._command_for_job(
                session, work.lease.fence.job_id, for_update=True
            )
            current = VoiceGeneratorCommandState(row.state)
            expected = {
                VoiceGeneratorCommandState.UNLOADING_VOICE_GENERATOR: (
                    VoiceGeneratorCommandState.GENERATING_VOICE
                ),
                VoiceGeneratorCommandState.VALIDATING_WITH_NANO: (
                    VoiceGeneratorCommandState.UNLOADING_VOICE_GENERATOR
                ),
            }
            if expected.get(target) is not current:
                raise InvalidNarrationState("VoiceGenerator command progress changed")
            now = datetime.now(UTC)
            row.state = target.value
            row.progress_current = 4 if target is VoiceGeneratorCommandState.UNLOADING_VOICE_GENERATOR else 5
            row.updated_at = now
            session.flush()

        _transaction(self._session_factory, operation)

    def heartbeat_and_job_state(self, work: VoiceGeneratorWorkItem) -> str:
        def operation(session: Session) -> str:
            job = session.scalar(
                select(BackgroundJob)
                .where(BackgroundJob.id == work.lease.fence.job_id)
                .with_for_update()
            )
            if job is None:
                raise NarrationNotFound("VoiceGenerator job not found")
            if job.state == "running":
                heartbeat_attempt(session, scope=self._scope, fence=work.lease.fence)
            return job.state

        return _transaction(self._session_factory, operation)

    def acknowledge_cancel(self, work: VoiceGeneratorWorkItem) -> None:
        def operation(session: Session) -> None:
            acknowledge_cancel(session, scope=self._scope, fence=work.lease.fence)

        _transaction(self._session_factory, operation)

    def record_host_terminal(
        self,
        work: VoiceGeneratorWorkItem,
        receipt: HostGenerationReceipt,
    ) -> None:
        if type(receipt) is not HostGenerationReceipt:
            raise TypeError("host receipt is invalid")

        def operation(session: Session) -> None:
            if receipt.status not in {
                HostGenerationStatus.FAILED,
                HostGenerationStatus.CANCELLED,
            } or not receipt.terminal or receipt.completed_at is None:
                raise InvalidNarrationState("host receipt is not a terminal failure")
            row = self._command_for_job(
                session, work.lease.fence.job_id, for_update=True
            )
            draft = session.get(VoiceDesignDraft, row.draft_id)
            if draft is None or draft.fingerprint != work.draft_fingerprint:
                raise NarrationScopeMismatch("VoiceGenerator failure draft changed")
            existing = session.scalar(
                select(VoiceGeneratorRunEvidence).where(
                    VoiceGeneratorRunEvidence.command_id == row.id,
                    VoiceGeneratorRunEvidence.attempt_number
                    == work.lease.attempt_number,
                )
            )
            if existing is not None:
                return
            started_at = receipt.started_at or row.started_at or receipt.completed_at
            classification = (
                "cancelled"
                if receipt.status is HostGenerationStatus.CANCELLED
                else "retryable_failure"
                if receipt.retryable
                else "non_retryable_failure"
            )
            recorded_at = datetime.now(UTC)
            model_run = ModelRunRecord(
                id=uuid5(row.id, "generator-model-run"),
                attempt_id=work.lease.fence.attempt_id,
                requested_provider_id="local-native-host",
                requested_model_id=VOICE_GENERATOR_MODEL_ID,
                requested_revision=VOICE_GENERATOR_REVISION,
                actual_provider_id="local-native-host",
                actual_model_id=VOICE_GENERATOR_MODEL_ID,
                actual_revision=VOICE_GENERATOR_REVISION,
                model_fingerprint=receipt.runtime_fingerprint,
                parameters_digest=work.parameters_digest,
                input_digest_key_id=draft.instruction_digest_key_id,
                input_digest=draft.instruction_digest,
                output_digest=None,
                duration_ms=max(
                    0,
                    int(
                        (receipt.completed_at - started_at).total_seconds() * 1000
                    ),
                ),
                provider_request_id=str(receipt.request_id),
                result_classification=classification,
                # ModelRun creation is fenced by the authoritative database clock.
                # The native receipt timestamps remain preserved on run evidence.
                created_at=recorded_at,
            )
            evidence = VoiceGeneratorRunEvidence(
                id=uuid5(row.id, "generator-run-evidence"),
                command_id=row.id,
                attempt_number=work.lease.attempt_number,
                model_run_id=model_run.id,
                request_digest=receipt.request_digest,
                protocol_version=HOST_PROTOCOL_VERSION,
                topology=RUNTIME_TOPOLOGY,
                runtime_fingerprint=receipt.runtime_fingerprint,
                requested_identity_json=EXPECTED_RUNTIME_IDENTITY.wire_payload(),
                actual_identity_json=receipt.runtime_identity.wire_payload(),
                instruction_digest=draft.instruction_digest,
                token_digest=receipt.token_sha256,
                audio_digest=None,
                audio_metrics_json={},
                memory_summary_json=(
                    {}
                    if receipt.memory_summary is None
                    else dict(receipt.memory_summary.public_payload())
                ),
                result_classification=classification,
                exit_reason_code=receipt.failure_code or "HOST_FAILED",
                started_at=started_at,
                completed_at=receipt.completed_at,
            )
            session.add_all([model_run, evidence])
            session.flush()

        _transaction(self._session_factory, operation)

    def fail(
        self,
        work: VoiceGeneratorWorkItem,
        *,
        state: VoiceGeneratorCommandState,
        failure_code: str,
        classification: str = "non_retryable",
    ) -> None:
        def operation(session: Session) -> None:
            row = self._command_for_job(
                session, work.lease.fence.job_id, for_update=True
            )
            if row.state == VoiceGeneratorCommandState.CANCELLED.value:
                acknowledge_cancel(session, scope=self._scope, fence=work.lease.fence)
                return
            fail_attempt(
                session,
                scope=self._scope,
                fence=work.lease.fence,
                classification=classification,
                error_code=failure_code,
            )
            now = datetime.now(UTC)
            row.state = state.value
            row.progress_current = 6
            row.failure_code = failure_code
            row.completed_at = now
            row.updated_at = now
            session.flush()

        _transaction(self._session_factory, operation)

    def terminalize_job_in_session(self, session: Session, *, job_id: UUID) -> None:
        row = self._command_for_job(session, job_id, for_update=True)
        if row.state in {state.value for state in VoiceGeneratorCommandState if state.value.startswith("failed_")} | {
            VoiceGeneratorCommandState.CANCELLED.value,
            VoiceGeneratorCommandState.SUPERSEDED.value,
            VoiceGeneratorCommandState.READY_APPLIED.value,
            VoiceGeneratorCommandState.READY_UNAPPLIED.value,
        }:
            return
        job = session.get(BackgroundJob, job_id)
        if job is None or job.state not in {"failed", "dead_letter", "cancelled"}:
            return
        now = datetime.now(UTC)
        if job.state == "cancelled":
            row.state = VoiceGeneratorCommandState.CANCELLED.value
            row.failure_code = None
        else:
            row.state = VoiceGeneratorCommandState.FAILED_STORAGE.value
            row.failure_code = job.error_code or "VOICE_GENERATOR_JOB_TERMINATED"
        row.progress_current = 6
        row.completed_at = now
        row.updated_at = now
        session.flush()

    def publish(
        self,
        work: VoiceGeneratorWorkItem,
        prepared: PreparedVoiceGeneratorPublication,
    ) -> None:
        generator_result = prepared.generator_result
        nano_result = prepared.nano_result
        nano_identity = production_nano_experiment_identity()

        def operation(session: Session) -> None:
            if work.lease.resource_fence is None:
                raise InvalidNarrationState("VoiceGenerator lease lacks resource fence")
            context = lock_result_publish_fences(
                session,
                scope=self._scope,
                job_fence=work.lease.fence,
                resource_fence=work.lease.resource_fence,
            )
            row = self._command_for_job(
                session, work.lease.fence.job_id, for_update=True
            )
            if row.state != VoiceGeneratorCommandState.VALIDATING_WITH_NANO.value:
                raise InvalidNarrationState("VoiceGenerator command left validation state")
            draft = session.get(VoiceDesignDraft, row.draft_id)
            character = session.get(NovelCharacter, row.character_id)
            if (
                draft is None
                or character is None
                or character.novel_id != row.novel_id
                or draft.fingerprint != work.draft_fingerprint
            ):
                raise NarrationScopeMismatch("VoiceGenerator publication scope changed")
            now = datetime.now(UTC)
            reference_asset = MediaAsset(
                id=prepared.generated.asset_id,
                owner_id=self._scope.owner_id,
                workspace_id=self._scope.workspace_id,
                novel_id=row.novel_id,
                source_revision_id=None,
                kind="narration_voice_reference",
                asset_class="voice_reference",
                mime_type="audio/wav",
                byte_size=prepared.generated.byte_size,
                duration_ms=generator_result.audio_metrics.duration_milliseconds,
                sample_rate=generator_result.audio_metrics.sample_rate_hz,
                channels=generator_result.audio_metrics.channels,
                storage_backend="local",
                state="ready",
                retention_policy="private_voice_source",
                checksum_algorithm="sha256",
                validation_json={
                    "schema_version": "voice-generator-audio-validation/1",
                    "metrics": dict(generator_result.audio_metrics.public_payload()),
                },
                verified_at=now,
                storage_path=prepared.generated.relative_path,
                content_hash=prepared.generated.actual_sha256,
                metadata_json={
                    "schema_version": "voice-generator-reference/1",
                    "command_id": str(row.id),
                    "runtime_fingerprint": generator_result.runtime_fingerprint,
                },
                created_at=now,
            )
            validation_asset = MediaAsset(
                id=prepared.validation.asset_id,
                owner_id=self._scope.owner_id,
                workspace_id=self._scope.workspace_id,
                novel_id=row.novel_id,
                source_revision_id=None,
                kind="narration_voice_preview",
                asset_class="preview",
                mime_type="audio/wav",
                byte_size=prepared.validation.byte_size,
                duration_ms=prepared.nano_duration_ms,
                sample_rate=prepared.nano_sample_rate_hz,
                channels=prepared.nano_channels,
                storage_backend="local",
                state="ready",
                retention_policy="private_voice_validation",
                checksum_algorithm="sha256",
                validation_json={
                    "schema_version": "voice-generator-nano-validation/1",
                    "reference_sha256": prepared.generated.actual_sha256,
                    "model_fingerprint": prepared.nano_model_fingerprint,
                },
                verified_at=now,
                storage_path=prepared.validation.relative_path,
                content_hash=prepared.validation.actual_sha256,
                metadata_json={
                    "schema_version": "voice-generator-validation/1",
                    "command_id": str(row.id),
                },
                created_at=now,
            )
            generator_run = ModelRunRecord(
                id=uuid5(row.id, "generator-model-run"),
                attempt_id=work.lease.fence.attempt_id,
                requested_provider_id="local-native-host",
                requested_model_id=VOICE_GENERATOR_MODEL_ID,
                requested_revision=VOICE_GENERATOR_REVISION,
                actual_provider_id="local-native-host",
                actual_model_id=VOICE_GENERATOR_MODEL_ID,
                actual_revision=VOICE_GENERATOR_REVISION,
                model_fingerprint=generator_result.runtime_fingerprint,
                parameters_digest=work.parameters_digest,
                input_digest_key_id=draft.instruction_digest_key_id,
                input_digest=draft.instruction_digest,
                output_digest=prepared.generated.actual_sha256,
                duration_ms=int(
                    (generator_result.completed_at - generator_result.started_at).total_seconds()
                    * 1000
                ),
                provider_request_id=str(generator_result.request_id),
                result_classification="success",
                created_at=now,
            )
            nano_run = ModelRunRecord(
                id=uuid5(row.id, "nano-model-run"),
                attempt_id=work.lease.fence.attempt_id,
                requested_provider_id="local-sidecar",
                requested_model_id=NANO_MODEL_ID,
                requested_revision=nano_identity.requested_revision,
                actual_provider_id=nano_identity.actual_provider_id,
                actual_model_id=nano_identity.actual_model_id,
                actual_revision=nano_identity.actual_revision,
                model_fingerprint=prepared.nano_model_fingerprint,
                parameters_digest=prepared.nano_parameters_digest,
                input_digest_key_id=prepared.nano_input_digest_key_id,
                input_digest=prepared.nano_input_digest,
                output_digest=prepared.validation.actual_sha256,
                duration_ms=prepared.nano_duration_ms,
                provider_request_id=str(work.lease.fence.attempt_id),
                result_classification="success",
                created_at=now,
            )
            profile = VoiceProfile(
                id=uuid5(row.id, "voice-profile"),
                owner_id=self._scope.owner_id,
                workspace_id=self._scope.workspace_id,
                novel_id=row.novel_id,
                name=f"{character.name} · 专属音色",
                current_version_id=None,
                status="draft",
                version=1,
                created_at=now,
                updated_at=now,
            )
            rights = VoiceRightsRecord(
                id=uuid5(row.id, "voice-rights"),
                owner_id=self._scope.owner_id,
                workspace_id=self._scope.workspace_id,
                novel_id=row.novel_id,
                source_kind="voice_generator",
                source_identifier=f"local://voice-generator/{row.id}",
                notice_version="voice-generator-private-use/1",
                purpose="private_novel_narration",
                commercial_use=False,
                redistribution=False,
                voice_cloning=False,
                subject_consent_reference=None,
                confirmed_actor="local-owner",
                confirmed_at=now,
                expires_at=None,
                risk_flags_json=[],
            )
            rights_event = VoiceRightsEvent(
                id=uuid5(row.id, "voice-rights-event"),
                rights_record_id=rights.id,
                event_key=f"voice-generator-confirmed:{row.id.hex}",
                event_type="confirmed",
                actor="local-owner",
                reason_code=None,
                occurred_at=now,
            )
            version_id = uuid5(row.id, "voice-version")
            fingerprint = canonical_sha256(
                {
                    "schema_version": "voice-generator-version/1",
                    "draft_fingerprint": draft.fingerprint,
                    "generator_audio_sha256": prepared.generated.actual_sha256,
                    "nano_audio_sha256": prepared.validation.actual_sha256,
                    "generator_model_run_id": str(generator_run.id),
                    "nano_model_run_id": str(nano_run.id),
                    "runtime_fingerprint": generator_result.runtime_fingerprint,
                    "nano_model_fingerprint": prepared.nano_model_fingerprint,
                }
            )
            version = VoiceProfileVersion(
                id=version_id,
                profile_id=profile.id,
                owner_id=self._scope.owner_id,
                workspace_id=self._scope.workspace_id,
                version_number=1,
                source_type="generated",
                state="locked",
                provider_id="local-native-host",
                model_id=VOICE_GENERATOR_MODEL_ID,
                model_revision=VOICE_GENERATOR_REVISION,
                preset_key=None,
                reference_asset_id=reference_asset.id,
                preview_asset_id=validation_asset.id,
                model_run_id=nano_run.id,
                rights_record_id=rights.id,
                description_digest_key_id=draft.instruction_digest_key_id,
                description_digest=draft.instruction_digest,
                language=draft.language,
                seed=draft.seed,
                parameters_json={
                    "schema_version": "voice-generator-version/1",
                    "draft_fingerprint": draft.fingerprint,
                    "runtime_identity": EXPECTED_RUNTIME_IDENTITY.wire_payload(),
                    "generator_parameters": draft.parameters_json,
                    "nano_parameters_digest": prepared.nano_parameters_digest,
                },
                fingerprint=fingerprint,
                quality_state="accepted",
                activation_basis="character_one_click_generation",
                validation_basis="machine_validated",
                locked_actor=None,
                locked_at=None,
                created_at=now,
            )
            run_evidence = VoiceGeneratorRunEvidence(
                id=uuid5(row.id, "generator-run-evidence"),
                command_id=row.id,
                attempt_number=work.lease.attempt_number,
                model_run_id=generator_run.id,
                request_digest=generator_result.request_digest,
                protocol_version=HOST_PROTOCOL_VERSION,
                topology=RUNTIME_TOPOLOGY,
                runtime_fingerprint=generator_result.runtime_fingerprint,
                requested_identity_json=EXPECTED_RUNTIME_IDENTITY.wire_payload(),
                actual_identity_json=EXPECTED_RUNTIME_IDENTITY.wire_payload(),
                # The native transport must prove the plaintext SHA-256, but
                # durable product evidence retains only the private keyed
                # digest already bound to the design draft.
                instruction_digest=draft.instruction_digest,
                token_digest=generator_result.token_digest,
                audio_digest=generator_result.audio_digest,
                audio_metrics_json=dict(generator_result.audio_metrics.public_payload()),
                memory_summary_json=dict(generator_result.memory_summary),
                result_classification="success",
                exit_reason_code="COMPLETED",
                started_at=generator_result.started_at,
                completed_at=generator_result.completed_at,
            )
            # The legacy scope trigger intentionally queries referenced rows
            # during the version INSERT.  Persist its dependencies first;
            # the outer transaction still keeps the complete publication
            # atomic and the deferred closure sees only the final graph.
            session.add_all(
                [
                    reference_asset,
                    validation_asset,
                    generator_run,
                    nano_run,
                    profile,
                    rights,
                ]
            )
            session.flush()
            session.add_all([rights_event, version, run_evidence])
            session.flush()
            profile.current_version_id = version.id
            profile.status = "active"
            profile.version += 1
            profile.updated_at = now
            row.generated_reference_asset_id = reference_asset.id
            row.nano_validation_asset_id = validation_asset.id
            row.generator_model_run_id = generator_run.id
            row.nano_model_run_id = nano_run.id
            row.voice_profile_id = profile.id
            row.voice_version_id = version.id
            try:
                binding = put_character_voice_binding(
                    SqlAlchemyNarrationStore(session),
                    novel_id=row.novel_id,
                    character_id=row.character_id,
                    request=wire.PutCharacterVoiceBindingRequest(
                        binding_policy=wire.CharacterVoiceBindingPolicy.DEDICATED,
                        profile_id=profile.id,
                        version_id=version.id,
                        language=version.language,
                        expected_version=row.expected_binding_version,
                    ),
                )
            except NarrationCasConflict:
                row.state = VoiceGeneratorCommandState.READY_UNAPPLIED.value
                row.applied_binding_version = None
                row.applied_at = None
            else:
                row.state = VoiceGeneratorCommandState.READY_APPLIED.value
                row.applied_binding_version = binding.version
                row.applied_at = now
            row.progress_current = 6
            row.failure_code = None
            row.completed_at = now
            row.updated_at = now
            result_digest = canonical_sha256(
                {
                    "schema_version": "voice-generator-result/1",
                    "command_id": str(row.id),
                    "voice_version_id": str(version.id),
                    "generator_audio_sha256": prepared.generated.actual_sha256,
                    "nano_audio_sha256": prepared.validation.actual_sha256,
                }
            )
            complete_attempt(
                session,
                scope=self._scope,
                fence=work.lease.fence,
                actual_result_digest=result_digest,
                publication_context=context,
            )
            session.flush()

        _transaction(self._session_factory, operation)


class VoiceGeneratorProcessor:
    def __init__(
        self,
        *,
        repository: SqlAlchemyVoiceGeneratorRepository,
        host: VoiceGeneratorRuntimePort,
        nano_adapter: SidecarMossNanoTTSAdapter,
        storage: NarrationStorage,
        digest_keyring: DigestKeyring,
        poll_seconds: float = 1.0,
    ) -> None:
        self._repository = repository
        self._host = host
        self._nano = nano_adapter
        self._storage = storage
        self._digest_keyring = digest_keyring
        self._poll_seconds = poll_seconds

    async def _validate_with_nano(
        self,
        work: VoiceGeneratorWorkItem,
        request: SynthesisRequest,
    ) -> SynthesisResult:
        """Keep the durable lease alive while Nano performs the validation call."""

        task = asyncio.create_task(self._nano.synthesize(request))
        cancellation_sent = False
        try:
            while True:
                try:
                    result = await asyncio.wait_for(
                        asyncio.shield(task), timeout=max(self._poll_seconds, 0.1)
                    )
                    if cancellation_sent:
                        state = await asyncio.to_thread(
                            self._repository.heartbeat_and_job_state, work
                        )
                        if state == "cancel_requested":
                            await asyncio.to_thread(
                                self._repository.acknowledge_cancel, work
                            )
                            raise JobFenceError(
                                "VoiceGenerator Nano validation was cancelled"
                            )
                    if type(result) is not SynthesisResult:
                        raise InvalidNarrationState("Nano returned an invalid result")
                    return result
                except TimeoutError:
                    state = await asyncio.to_thread(
                        self._repository.heartbeat_and_job_state, work
                    )
                    if state == "cancel_requested" and not cancellation_sent:
                        cancellation_sent = True
                        await self._nano.cancel(request.request_id)
                    elif state not in {"running", "cancel_requested"}:
                        task.cancel()
                        try:
                            await task
                        except (asyncio.CancelledError, Exception):
                            pass
                        raise JobFenceError(
                            "VoiceGenerator job became terminal during Nano validation"
                        )
                except Exception as error:
                    if isinstance(error, JobFenceError):
                        raise
                    if cancellation_sent:
                        state = await asyncio.to_thread(
                            self._repository.heartbeat_and_job_state, work
                        )
                        if state == "cancel_requested":
                            await asyncio.to_thread(
                                self._repository.acknowledge_cancel, work
                            )
                            raise JobFenceError(
                                "VoiceGenerator Nano validation was cancelled"
                            )
                    raise
        except asyncio.CancelledError:
            if not task.done():
                try:
                    await self._nano.cancel(request.request_id)
                finally:
                    task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
            raise

    async def _generate(self, work: VoiceGeneratorWorkItem):
        health = await self._host.health()
        if not health.ready or health.runtime_fingerprint != EXPECTED_RUNTIME_FINGERPRINT:
            raise VoiceGeneratorRuntimeError(
                "HOST_NOT_READY", "VoiceGenerator host is not ready", retryable=True
            )
        receipt = await self._host.create(work.host_request)
        while not receipt.terminal:
            state = await asyncio.to_thread(
                self._repository.heartbeat_and_job_state, work
            )
            if state == "cancel_requested":
                await self._host.cancel(work.host_request)
            elif state != "running":
                raise JobFenceError("VoiceGenerator job left running state")
            await asyncio.sleep(self._poll_seconds)
            receipt = await self._host.get(work.host_request)
        projected = command_state_for_host_receipt(receipt)
        if projected is VoiceGeneratorCommandState.CANCELLED:
            await asyncio.to_thread(
                self._repository.record_host_terminal, work, receipt
            )
            await asyncio.to_thread(self._repository.acknowledge_cancel, work)
            return None
        if projected is not VoiceGeneratorCommandState.VALIDATING_WITH_NANO:
            await asyncio.to_thread(
                self._repository.record_host_terminal, work, receipt
            )
            raise VoiceGeneratorRuntimeError(
                receipt.failure_code or "GENERATOR_PROCESS_FAILED",
                "VoiceGenerator host failed",
                retryable=receipt.retryable,
            )
        audio = await self._host.download_audio(work.host_request, receipt)
        return validate_runtime_completion(work.host_request, receipt, audio)

    async def _release_nano_for_heavy_runtime(
        self, work: VoiceGeneratorWorkItem
    ) -> None:
        """Keep the durable lease alive while Nano replaces its process."""

        task = asyncio.create_task(self._nano.release_model_for_heavy_runtime())
        try:
            while True:
                try:
                    await asyncio.wait_for(
                        asyncio.shield(task), timeout=max(self._poll_seconds, 0.1)
                    )
                    state = await asyncio.to_thread(
                        self._repository.heartbeat_and_job_state, work
                    )
                    if state == "cancel_requested":
                        await asyncio.to_thread(
                            self._repository.acknowledge_cancel, work
                        )
                        raise JobFenceError(
                            "VoiceGenerator was cancelled while releasing Nano"
                        )
                    if state != "running":
                        raise JobFenceError(
                            "VoiceGenerator job became terminal while releasing Nano"
                        )
                    return
                except TimeoutError:
                    state = await asyncio.to_thread(
                        self._repository.heartbeat_and_job_state, work
                    )
                    if state not in {"running", "cancel_requested"}:
                        task.cancel()
                        try:
                            await task
                        except (asyncio.CancelledError, Exception):
                            pass
                        raise JobFenceError(
                            "VoiceGenerator job became terminal while releasing Nano"
                        )
        except asyncio.CancelledError:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
            raise

    async def process(self, lease: JobLease) -> None:
        work = await asyncio.to_thread(self._repository.load_and_mark_generating, lease)
        failure_state = VoiceGeneratorCommandState.FAILED_RUNTIME_UNAVAILABLE
        failure_code = "VOICE_GENERATOR_RUNTIME_UNAVAILABLE"
        try:
            await self._release_nano_for_heavy_runtime(work)
            failure_state = VoiceGeneratorCommandState.FAILED_GENERATION
            failure_code = "VOICE_GENERATOR_GENERATION_FAILED"
            generator_result = await self._generate(work)
            if generator_result is None:
                return
            failure_state = VoiceGeneratorCommandState.FAILED_STORAGE
            failure_code = "VOICE_GENERATOR_STORAGE_FAILED"
            generated_asset_id = uuid5(work.command_id, "generated-reference-asset")
            generated = await asyncio.to_thread(
                self._storage.publish_media,
                [generator_result.audio_bytes],
                asset_id=generated_asset_id,
                expected_sha256=generator_result.audio_digest,
                expected_size=len(generator_result.audio_bytes),
                extension="wav",
                max_bytes=MAX_GENERATED_AUDIO_BYTES,
            )
            await asyncio.to_thread(
                self._repository.advance,
                work,
                VoiceGeneratorCommandState.UNLOADING_VOICE_GENERATOR,
            )
            await asyncio.to_thread(
                self._repository.advance,
                work,
                VoiceGeneratorCommandState.VALIDATING_WITH_NANO,
            )
            failure_state = VoiceGeneratorCommandState.FAILED_NANO_VALIDATION
            failure_code = "VOICE_GENERATOR_VALIDATION_FAILED"
            validation_text = _VALIDATION_TEXT[work.language]
            validation_key = self._digest_keyring.active
            validation_input_digest = private_text_digest(
                validation_key,
                purpose=VALIDATION_TEXT_PURPOSE,
                text=validation_text,
            )
            decode = NanoDecodeParametersV2()
            nano_parameters_digest = canonical_sha256(
                {
                    "schema_version": "voice-generator-nano-validation-parameters/1",
                    "seed": work.seed,
                    "sample_mode": "full",
                    "max_new_frames": 375,
                    "decode_parameters": dict(decode.wire_payload()),
                    "reference_sha256": generator_result.audio_digest,
                }
            )
            nano_request = SynthesisRequest(
                request_id=lease.fence.attempt_id,
                scope=NarrationRequestScope.fixed_local(),
                text=validation_text,
                voice="uploaded-reference",
                seed=work.seed,
                sample_mode="full",
                max_new_frames=375,
                decode_parameters=decode,
                reference_audio=ReferenceAudioInput(
                    audio_bytes=generator_result.audio_bytes,
                    actual_sha256=generator_result.audio_digest,
                ),
            )
            nano_result = await self._validate_with_nano(work, nano_request)
            nano_model_fingerprint = _require_production_nano_result(nano_result)
            processed = await asyncio.to_thread(
                process_synthesis_wav,
                nano_result.audio_bytes,
                spoken_text=validation_text,
            )
            validation_asset_id = uuid5(work.command_id, "nano-validation-asset")
            validation = await asyncio.to_thread(
                self._storage.publish_media,
                [processed.wav_bytes],
                asset_id=validation_asset_id,
                expected_sha256=processed.actual_sha256,
                expected_size=len(processed.wav_bytes),
                extension="wav",
                max_bytes=MAX_VALIDATION_AUDIO_BYTES,
            )
            await asyncio.to_thread(
                self._repository.publish,
                work,
                PreparedVoiceGeneratorPublication(
                    generated=generated,
                    validation=validation,
                    generator_result=generator_result,
                    nano_result=nano_result,
                    nano_duration_ms=processed.duration_ms,
                    nano_sample_rate_hz=processed.sample_rate_hz,
                    nano_channels=processed.channels,
                    nano_parameters_digest=nano_parameters_digest,
                    nano_input_digest_key_id=validation_key.key_id,
                    nano_input_digest=validation_input_digest,
                    nano_model_fingerprint=nano_model_fingerprint,
                ),
            )
        except asyncio.CancelledError:
            raise
        except JobFenceError:
            return
        except VoiceGeneratorRuntimeError as error:
            await asyncio.to_thread(
                self._repository.fail,
                work,
                state=terminal_state_for_runtime_error(error),
                failure_code=error.code,
            )
        except SidecarRuntimeError as error:
            await asyncio.to_thread(
                self._repository.fail,
                work,
                state=failure_state,
                failure_code=error.code,
            )
        except BaseException:
            current = await asyncio.to_thread(
                self._repository.heartbeat_and_job_state, work
            )
            if current == "cancel_requested":
                await asyncio.to_thread(self._repository.acknowledge_cancel, work)
                return
            await asyncio.to_thread(
                self._repository.fail,
                work,
                state=failure_state,
                failure_code=failure_code,
            )


__all__ = [
    "SqlAlchemyVoiceGeneratorRepository",
    "VoiceGeneratorProcessor",
    "VOICE_GENERATOR_MODEL_ID",
    "NANO_MODEL_ID",
    "_require_production_nano_result",
]
