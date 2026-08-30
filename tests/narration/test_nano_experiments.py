from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import hashlib
import io
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5
import wave

import pytest

from backend.narration.jobs import JobFence, JobLease
from backend.narration.nano_experiments import (
    NANO_DECODE_PARAMETERS_V3,
    NANO_EXPERIMENT_MAX_NEW_FRAMES,
    NANO_EXPERIMENT_SAMPLE_MODE,
    NANO_EXPERIMENT_VALIDATION_TEXT,
    NanoDecodeParametersV3,
    NanoExperimentApplyRequest,
    NanoExperimentCommand,
    NanoExperimentContractError,
    NanoExperimentError,
    NanoExperimentFailure,
    NanoExperimentIdempotencyConflict,
    NanoExperimentIntent,
    NanoExperimentModelIdentity,
    NanoExperimentProcessor,
    NanoExperimentReservation,
    NanoExperimentService,
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
    StrictNanoExperimentValidator,
    build_nano_experiment_intent,
    ensure_idempotent_request,
    ensure_state_transition,
    nano_experiment_fingerprint,
    nano_experiment_profile_id,
    nano_parameters_digest,
    production_nano_experiment_identity,
)


NOW = datetime(2026, 8, 29, 8, 0, tzinfo=UTC)
NOVEL_ID = UUID("a61af3b8-c08b-4a96-80e5-74a7f264c079")
CHARACTER_ID = UUID("f858dadb-dad7-433d-a59e-f291cc02d17d")
PRESET_ID = "onnx.Zhiming"
VALIDATION_DIGEST = hashlib.sha256(b"trusted-validation-hmac").hexdigest()


def _validation_input() -> NanoExperimentValidationInput:
    return NanoExperimentValidationInput(
        text=NANO_EXPERIMENT_VALIDATION_TEXT,
        input_digest_key_id="tts-key-20260829",
        input_digest=VALIDATION_DIGEST,
    )


def _identity() -> NanoExperimentModelIdentity:
    return production_nano_experiment_identity()


def _narrator_target(*, settings_version: int = 4) -> NanoExperimentTarget:
    return NanoExperimentTarget(
        target_kind="narrator",
        character_id=None,
        expected_settings_version=settings_version,
        expected_binding_version=None,
    )


def _character_target(
    *, settings_version: int = 4, binding_version: int = 2
) -> NanoExperimentTarget:
    return NanoExperimentTarget(
        target_kind="character",
        character_id=CHARACTER_ID,
        expected_settings_version=settings_version,
        expected_binding_version=binding_version,
    )


def _lease(job_id: UUID) -> JobLease:
    return JobLease(
        fence=JobFence(
            job_id=job_id,
            attempt_id=uuid4(),
            lease_token=uuid4(),
            lease_generation=1,
        ),
        attempt_number=1,
        retry_kind="initial",
        lease_owner="nano-experiment-test-worker",
        lease_until=NOW + timedelta(minutes=2),
    )


def _wav_bytes(*, duration_ms: int = 100) -> bytes:
    frames = 48_000 * duration_ms // 1_000
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setframerate(48_000)
        writer.setnchannels(2)
        writer.setsampwidth(2)
        writer.writeframes(b"\x01\x00\x01\x00" * frames)
    return output.getvalue()


class InMemoryRepository:
    def __init__(self) -> None:
        self.intents: dict[str, NanoExperimentIntent] = {}
        self.commands: dict[UUID, NanoExperimentCommand] = {}
        self.validation_inputs: dict[UUID, NanoExperimentValidationInput] = {}
        self.identities: dict[UUID, NanoExperimentModelIdentity] = {}
        self.reuse_by_fingerprint: dict[str, NanoReusableVersion] = {}
        self.candidate_by_command: dict[UUID, NanoReusableVersion] = {}
        self.failures: list[NanoExperimentFailure] = []
        self.fail_claims: list[NanoExperimentFailure] = []

    def reserve(
        self, intent: NanoExperimentIntent, *, idempotency_key: str
    ) -> NanoExperimentReservation:
        existing_intent = self.intents.get(idempotency_key)
        if existing_intent is not None:
            ensure_idempotent_request(
                stored_request_digest=existing_intent.request_digest,
                incoming_request_digest=intent.request_digest,
            )
            command = self.commands[existing_intent.command_id]
            return NanoExperimentReservation(command=command, replayed=True)
        self.intents[idempotency_key] = intent
        candidate = self.reuse_by_fingerprint.get(intent.fingerprint)
        command = NanoExperimentCommand(
            command_id=intent.command_id,
            novel_id=intent.novel_id,
            profile_id=intent.profile_id,
            version_id=(candidate.version_id if candidate is not None else uuid4()),
            preview_id=(candidate.preview_id if candidate is not None else uuid4()),
            background_job_id=uuid4(),
            base_preset_id=intent.base_preset_id,
            target=intent.target,
            parameters=intent.parameters,
            parameters_digest=intent.parameters_digest,
            fingerprint=intent.fingerprint,
            request_digest=intent.request_digest,
            state="pending",
            reused_version=False,
            failure_code=None,
            retryable=False,
            created_at=NOW,
        )
        self.commands[command.command_id] = command
        self.validation_inputs[command.command_id] = intent.validation_input
        self.identities[command.command_id] = intent.model_identity
        if candidate is not None:
            self.candidate_by_command[command.command_id] = candidate
        return NanoExperimentReservation(
            command=command,
            replayed=False,
            reusable_version=candidate,
        )

    def get(
        self, *, novel_id: UUID, command_id: UUID
    ) -> NanoExperimentCommand:
        command = self.commands[command_id]
        if command.novel_id != novel_id:
            raise LookupError("novel scope changed")
        return command

    def list_for_novel(
        self, *, novel_id: UUID
    ) -> tuple[NanoExperimentCommand, ...]:
        return tuple(
            command
            for command in self.commands.values()
            if command.novel_id == novel_id
        )

    def load_and_mark_running(self, lease: JobLease) -> NanoExperimentWorkItem:
        command = next(
            command
            for command in self.commands.values()
            if command.background_job_id == lease.fence.job_id
        )
        ensure_state_transition(command.state, "running")
        running = replace(command, state="running", started_at=NOW)
        self.commands[command.command_id] = running
        model_input_digest = hashlib.sha256(
            (
                f"{command.request_digest}:{lease.fence.attempt_id}"
            ).encode("ascii")
        ).hexdigest()
        return NanoExperimentWorkItem(
            lease=lease,
            command=running,
            validation_input=self.validation_inputs[command.command_id],
            model_identity=self.identities[command.command_id],
            model_input_digest_key_id="tts-key-20260829",
            model_input_digest=model_input_digest,
            reusable_version=self.candidate_by_command.get(command.command_id),
        )

    def fail(
        self, work: NanoExperimentWorkItem, failure: NanoExperimentFailure
    ) -> NanoExperimentWorkerOutcome:
        self.failures.append(failure)
        ensure_state_transition(work.command.state, "failed")
        failed = replace(
            work.command,
            state="failed",
            failure_code=failure.code,
            retryable=failure.retryable,
            completed_at=NOW + timedelta(seconds=2),
        )
        self.commands[failed.command_id] = failed
        return NanoExperimentWorkerOutcome(
            "failed",
            work.lease.fence.job_id,
            failed.command_id,
            failure.code,
            failed,
        )

    def fail_claim(
        self, lease: JobLease, failure: NanoExperimentFailure
    ) -> NanoExperimentWorkerOutcome:
        self.fail_claims.append(failure)
        return NanoExperimentWorkerOutcome(
            "failed", lease.fence.job_id, failure_code=failure.code
        )


class InMemoryBinder:
    def __init__(self, repository: InMemoryRepository) -> None:
        self.repository = repository
        self.settings_version = 4
        self.binding_versions = {CHARACTER_ID: 2}
        self.narrator_version_id: UUID | None = None
        self.character_version_ids: dict[UUID, UUID] = {}
        self.complete_calls = 0
        self.raise_on_complete = False

    def _complete(
        self,
        work: NanoExperimentWorkItem,
        *,
        version_id: UUID,
        reused: bool,
    ) -> NanoExperimentCommand:
        self.complete_calls += 1
        if self.raise_on_complete:
            # Simulates a transaction rollback before any target write.
            raise RuntimeError("database unavailable")
        target = work.command.target
        applied = self.settings_version == target.expected_settings_version
        if target.target_kind == "character":
            applied = applied and (
                self.binding_versions[target.character_id]
                == target.expected_binding_version
            )
        state = "ready_applied" if applied else "ready_unapplied"
        ensure_state_transition(work.command.state, state)
        completed = replace(
            work.command,
            version_id=version_id,
            state=cast(object, state),
            reused_version=reused,
            completed_at=NOW + timedelta(seconds=1),
        )
        if applied:
            if target.target_kind == "narrator":
                self.narrator_version_id = version_id
                self.settings_version += 1
            else:
                assert target.character_id is not None
                self.character_version_ids[target.character_id] = version_id
                self.binding_versions[target.character_id] += 1
        self.repository.commands[completed.command_id] = completed
        return completed

    def complete_validated(
        self,
        work: NanoExperimentWorkItem,
        evidence: NanoValidatedEvidence,
    ) -> NanoExperimentCommand:
        assert evidence.parameters_digest == work.command.parameters_digest
        return self._complete(
            work, version_id=work.command.version_id, reused=False
        )

    def complete_reused(
        self,
        work: NanoExperimentWorkItem,
        reusable_version: NanoReusableVersion,
    ) -> NanoExperimentCommand:
        return self._complete(
            work, version_id=reusable_version.version_id, reused=True
        )

    def apply_ready_unapplied(
        self,
        *,
        novel_id: UUID,
        command_id: UUID,
        request: NanoExperimentApplyRequest,
    ) -> NanoExperimentCommand:
        command = self.repository.get(novel_id=novel_id, command_id=command_id)
        request.validate_for(command.target)
        if command.state == "ready_applied":
            return command
        if command.state != "ready_unapplied":
            raise NanoExperimentStateError("not ready for explicit apply")
        target = command.target
        if request.expected_settings_version != self.settings_version:
            raise NanoExperimentStateError("settings CAS drifted")
        if target.target_kind == "character":
            assert target.character_id is not None
            if (
                request.expected_binding_version
                != self.binding_versions[target.character_id]
            ):
                raise NanoExperimentStateError("binding CAS drifted")
            self.character_version_ids[target.character_id] = command.version_id
            self.binding_versions[target.character_id] += 1
        else:
            self.narrator_version_id = command.version_id
            self.settings_version += 1
        ensure_state_transition(command.state, "ready_applied")
        applied = replace(command, state="ready_applied")
        self.repository.commands[command_id] = applied
        return applied


class RecordingSynthesizer:
    def __init__(self) -> None:
        self.requests: list[NanoExperimentSynthesisRequest] = []
        self.error: BaseException | None = None
        self.mutate: str | None = None

    async def synthesize(
        self, request: NanoExperimentSynthesisRequest
    ) -> NanoExperimentSynthesisResult:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        audio = (
            b""
            if self.mutate == "empty_audio"
            else _wav_bytes(duration_ms=10_000 if self.mutate == "long_audio" else 100)
        )
        output_digest = hashlib.sha256(audio).hexdigest()
        identity = request.model_identity
        run_output_digest = (
            hashlib.sha256(b"different-output").hexdigest()
            if self.mutate == "run_output"
            else output_digest
        )
        run = NanoModelRunEvidence(
            model_run_id=uuid4(),
            attempt_id=request.attempt_id,
            requested_provider_id=identity.requested_provider_id,
            requested_model_id=identity.requested_model_id,
            requested_revision=identity.requested_revision,
            actual_provider_id=identity.actual_provider_id,
            actual_model_id=(
                "wrong-model"
                if self.mutate == "actual_model"
                else identity.actual_model_id
            ),
            actual_revision=identity.actual_revision,
            model_fingerprint_sha256=identity.model_fingerprint_sha256,
            parameters_digest=(
                hashlib.sha256(b"different-parameters").hexdigest()
                if self.mutate == "parameters"
                else request.parameters_digest
            ),
            input_digest_key_id=request.input_digest_key_id,
            input_digest=(
                hashlib.sha256(b"different-input-hmac").hexdigest()
                if self.mutate == "input_hmac"
                else request.input_digest
            ),
            output_digest=run_output_digest,
            result_classification="success",
        )
        result_asset_id = uuid4()
        claimed_output_digest = (
            hashlib.sha256(b"wrong-audio-hash").hexdigest()
            if self.mutate == "audio_hash"
            else output_digest
        )
        return NanoExperimentSynthesisResult(
            command_id=request.command_id,
            attempt_id=request.attempt_id,
            audio_bytes=audio,
            output_sha256=claimed_output_digest,
            sample_rate_hz=48_000,
            channels=2,
            sample_width_bytes=2,
            duration_ms=(
                0
                if self.mutate == "empty_audio"
                else 10_000 if self.mutate == "long_audio" else 100
            ),
            sidecar_protocol_version=identity.sidecar_protocol_version,
            postprocess_fingerprint=identity.postprocess_fingerprint,
            preview_id=request.preview_id,
            result_asset_id=result_asset_id,
            published_relative_path=(
                f"assets/{result_asset_id.hex[:2]}/{result_asset_id.hex}/"
                f"{claimed_output_digest}.wav"
            ),
            published_byte_size=len(audio),
            model_run=run,
        )


def _service_parts() -> tuple[
    InMemoryRepository,
    InMemoryBinder,
    RecordingSynthesizer,
    NanoExperimentService,
    NanoExperimentProcessor,
]:
    repository = InMemoryRepository()
    binder = InMemoryBinder(repository)
    synthesizer = RecordingSynthesizer()
    service = NanoExperimentService(
        repository=repository,
        binder=binder,
        validation_input=_validation_input(),
        model_identity=_identity(),
    )
    processor = NanoExperimentProcessor(
        repository=repository,
        synthesizer=synthesizer,
        validator=StrictNanoExperimentValidator(),
        binder=binder,
    )
    return repository, binder, synthesizer, service, processor


def test_v3_defaults_and_sidecar_projection_are_exact() -> None:
    parameters = NanoDecodeParametersV3()

    assert parameters.schema_version == NANO_DECODE_PARAMETERS_V3
    assert parameters.sample_mode == NANO_EXPERIMENT_SAMPLE_MODE == "full"
    assert parameters.max_new_frames == NANO_EXPERIMENT_MAX_NEW_FRAMES == 375
    assert dict(parameters.sidecar_decode_parameters().wire_payload()) == {
        "schema_version": "moss-nano-decode-parameters/2",
        "text_temperature_milli": 1_000,
        "text_top_p_milli": 1_000,
        "text_top_k": 50,
        "audio_temperature_milli": 800,
        "audio_top_p_milli": 950,
        "audio_top_k": 25,
        "audio_repetition_penalty_milli": 1_200,
    }
    assert NanoDecodeParametersV3.from_payload(
        dict(parameters.canonical_payload())
    ) == parameters


@pytest.mark.parametrize(
    ("field_name", "minimum", "maximum"),
    [
        ("seed", 0, 2**63 - 1),
        ("text_temperature_milli", 100, 2_000),
        ("text_top_p_milli", 1, 1_000),
        ("text_top_k", 1, 100),
        ("audio_temperature_milli", 100, 2_000),
        ("audio_top_p_milli", 1, 1_000),
        ("audio_top_k", 1, 100),
        ("audio_repetition_penalty_milli", 1_000, 2_000),
    ],
)
def test_v3_parameter_bounds_are_closed(
    field_name: str, minimum: int, maximum: int
) -> None:
    assert getattr(
        replace(NanoDecodeParametersV3(), **{field_name: minimum}), field_name
    ) == minimum
    assert getattr(
        replace(NanoDecodeParametersV3(), **{field_name: maximum}), field_name
    ) == maximum
    with pytest.raises(NanoExperimentContractError):
        replace(NanoDecodeParametersV3(), **{field_name: minimum - 1})
    with pytest.raises(NanoExperimentContractError):
        replace(NanoDecodeParametersV3(), **{field_name: maximum + 1})
    with pytest.raises(NanoExperimentContractError):
        replace(NanoDecodeParametersV3(), **{field_name: True})


@pytest.mark.parametrize(
    "change",
    [
        {"sample_mode": "fixed"},
        {"max_new_frames": 374},
        {"max_new_frames": 376},
        {"schema_version": "nano-decode-parameters/2"},
    ],
)
def test_v3_rejects_non_full_non_375_and_unknown_schema(
    change: dict[str, object],
) -> None:
    with pytest.raises(NanoExperimentContractError):
        replace(NanoDecodeParametersV3(), **change)


def test_target_contract_rejects_cross_kind_fields() -> None:
    with pytest.raises(NanoExperimentContractError):
        NanoExperimentTarget("narrator", CHARACTER_ID, 0, None)
    with pytest.raises(NanoExperimentContractError):
        NanoExperimentTarget("character", None, 0, 0)
    with pytest.raises(NanoExperimentContractError):
        NanoExperimentTarget("character", CHARACTER_ID, 0, None)
    with pytest.raises(NanoExperimentContractError):
        NanoExperimentTarget("narrator", None, -1, None)


def test_profile_identity_matches_frozen_uuid5_formula() -> None:
    expected = uuid5(
        NAMESPACE_URL,
        f"nano-experiment-profile/1:{NOVEL_ID}:{PRESET_ID}",
    )
    assert (
        nano_experiment_profile_id(
            novel_id=NOVEL_ID, base_preset_id=PRESET_ID
        )
        == expected
    )


def test_unknown_base_preset_fails_closed() -> None:
    with pytest.raises(NanoExperimentContractError):
        nano_experiment_profile_id(
            novel_id=NOVEL_ID,
            base_preset_id="onnx.NotInPinnedCatalog",
        )


def test_digest_and_fingerprint_are_deterministic_and_complete() -> None:
    parameters = NanoDecodeParametersV3()
    validation = _validation_input()
    identity = _identity()

    digest = nano_parameters_digest(parameters)
    fingerprint = nano_experiment_fingerprint(
        novel_id=NOVEL_ID,
        base_preset_id=PRESET_ID,
        parameters=parameters,
        validation_input=validation,
        model_identity=identity,
    )
    assert digest == nano_parameters_digest(parameters)
    assert fingerprint == nano_experiment_fingerprint(
        novel_id=NOVEL_ID,
        base_preset_id=PRESET_ID,
        parameters=parameters,
        validation_input=validation,
        model_identity=identity,
    )

    for changed in (
        replace(parameters, seed=parameters.seed + 1),
        replace(parameters, text_temperature_milli=999),
        replace(parameters, text_top_p_milli=999),
        replace(parameters, text_top_k=49),
        replace(parameters, audio_temperature_milli=799),
        replace(parameters, audio_top_p_milli=949),
        replace(parameters, audio_top_k=24),
        replace(parameters, audio_repetition_penalty_milli=1_199),
    ):
        assert nano_parameters_digest(changed) != digest
        assert nano_experiment_fingerprint(
            novel_id=NOVEL_ID,
            base_preset_id=PRESET_ID,
            parameters=changed,
            validation_input=validation,
            model_identity=identity,
        ) != fingerprint

    assert nano_experiment_fingerprint(
        novel_id=NOVEL_ID,
        base_preset_id="onnx.Junhao",
        parameters=parameters,
        validation_input=validation,
        model_identity=identity,
    ) != fingerprint
    assert nano_experiment_fingerprint(
        novel_id=NOVEL_ID,
        base_preset_id=PRESET_ID,
        parameters=parameters,
        validation_input=replace(
            validation,
            input_digest=hashlib.sha256(b"rotated-hmac").hexdigest(),
        ),
        model_identity=identity,
    ) != fingerprint
    assert nano_experiment_fingerprint(
        novel_id=NOVEL_ID,
        base_preset_id=PRESET_ID,
        parameters=parameters,
        validation_input=validation,
        model_identity=replace(
            identity,
            postprocess_fingerprint=hashlib.sha256(
                b"new-postprocess"
            ).hexdigest(),
        ),
    ) != fingerprint
    assert nano_experiment_fingerprint(
        novel_id=NOVEL_ID,
        base_preset_id=PRESET_ID,
        parameters=parameters,
        validation_input=validation,
        model_identity=replace(identity, sidecar_protocol_version="sidecar/2"),
    ) != fingerprint
    assert nano_experiment_fingerprint(
        novel_id=NOVEL_ID,
        base_preset_id=PRESET_ID,
        parameters=parameters,
        validation_input=validation,
        model_identity=replace(identity, actual_revision="different-revision"),
    ) != fingerprint
    assert nano_experiment_fingerprint(
        novel_id=uuid5(NAMESPACE_URL, "another-novel"),
        base_preset_id=PRESET_ID,
        parameters=parameters,
        validation_input=validation,
        model_identity=identity,
    ) != fingerprint


def test_intent_rejects_tampered_fingerprint_and_request_digest() -> None:
    intent = build_nano_experiment_intent(
        novel_id=NOVEL_ID,
        base_preset_id=PRESET_ID,
        target=_narrator_target(),
        parameters=NanoDecodeParametersV3(),
        validation_input=_validation_input(),
        model_identity=_identity(),
        idempotency_key="nano-test-intent-tamper",
    )
    with pytest.raises(NanoExperimentContractError):
        replace(
            intent,
            fingerprint=hashlib.sha256(b"tampered-fingerprint").hexdigest(),
        )
    with pytest.raises(NanoExperimentContractError):
        replace(
            intent,
            request_digest=hashlib.sha256(b"tampered-request").hexdigest(),
        )


def test_same_idempotency_key_replays_and_changed_request_conflicts() -> None:
    repository, _binder, _synthesizer, service, _processor = _service_parts()
    first = service.create(
        novel_id=NOVEL_ID,
        base_preset_id=PRESET_ID,
        target=_narrator_target(),
        parameters=NanoDecodeParametersV3(),
        idempotency_key="nano-test-create-0001",
    )
    replay = service.create(
        novel_id=NOVEL_ID,
        base_preset_id=PRESET_ID,
        target=_narrator_target(),
        parameters=NanoDecodeParametersV3(),
        idempotency_key="nano-test-create-0001",
    )

    assert replay.replayed is True
    assert replay.command.command_id == first.command.command_id
    assert len(repository.commands) == 1
    assert service.list_for_novel(novel_id=NOVEL_ID) == (first.command,)
    with pytest.raises(NanoExperimentIdempotencyConflict):
        service.create(
            novel_id=NOVEL_ID,
            base_preset_id=PRESET_ID,
            target=_narrator_target(),
            parameters=NanoDecodeParametersV3(seed=9_999),
            idempotency_key="nano-test-create-0001",
        )


def test_state_machine_only_allows_frozen_transitions() -> None:
    for current, target in (
        ("pending", "running"),
        ("running", "ready_applied"),
        ("running", "ready_unapplied"),
        ("running", "failed"),
        ("ready_unapplied", "ready_applied"),
    ):
        ensure_state_transition(current, target)
    for current, target in (
        ("pending", "ready_applied"),
        ("ready_applied", "ready_unapplied"),
        ("failed", "running"),
        ("ready_unapplied", "failed"),
    ):
        with pytest.raises(NanoExperimentStateError):
            ensure_state_transition(current, target)


@pytest.mark.asyncio
async def test_successful_validation_applies_binding_after_synthesis() -> None:
    repository, binder, synthesizer, service, processor = _service_parts()
    reservation = service.create(
        novel_id=NOVEL_ID,
        base_preset_id=PRESET_ID,
        target=_narrator_target(),
        parameters=NanoDecodeParametersV3(seed=77),
        idempotency_key="nano-test-success-0001",
    )

    assert binder.narrator_version_id is None
    outcome = await processor.process(
        _lease(reservation.command.background_job_id)
    )

    assert outcome.status == "succeeded"
    assert outcome.command is not None
    assert outcome.command.state == "ready_applied"
    assert outcome.command.reused_version is False
    assert binder.narrator_version_id == outcome.command.version_id
    assert len(synthesizer.requests) == 1
    request = synthesizer.requests[0]
    assert request.parameters.sample_mode == "full"
    assert request.parameters.max_new_frames == 375
    assert request.parameters.seed == 77
    assert request.input_digest != VALIDATION_DIGEST
    assert repository.failures == []


@pytest.mark.asyncio
async def test_cas_drift_preserves_result_without_overwriting_author_choice() -> None:
    repository, binder, synthesizer, service, processor = _service_parts()
    reservation = service.create(
        novel_id=NOVEL_ID,
        base_preset_id=PRESET_ID,
        target=_character_target(),
        parameters=NanoDecodeParametersV3(),
        idempotency_key="nano-test-cas-drift-0001",
    )
    author_selected = uuid4()
    binder.character_version_ids[CHARACTER_ID] = author_selected
    binder.binding_versions[CHARACTER_ID] += 1

    outcome = await processor.process(
        _lease(reservation.command.background_job_id)
    )

    assert outcome.command is not None
    assert outcome.command.state == "ready_unapplied"
    assert binder.character_version_ids[CHARACTER_ID] == author_selected
    assert len(synthesizer.requests) == 1

    applied = service.apply(
        novel_id=NOVEL_ID,
        command_id=reservation.command.command_id,
        request=NanoExperimentApplyRequest(
            expected_settings_version=binder.settings_version,
            expected_binding_version=binder.binding_versions[CHARACTER_ID],
        ),
    )
    assert applied.state == "ready_applied"
    assert binder.character_version_ids[CHARACTER_ID] == applied.version_id
    assert service.apply(
        novel_id=NOVEL_ID,
        command_id=applied.command_id,
        request=NanoExperimentApplyRequest(
            expected_settings_version=binder.settings_version,
            expected_binding_version=binder.binding_versions[CHARACTER_ID],
        ),
    ) == applied


@pytest.mark.asyncio
async def test_verified_version_reuse_skips_synthesis_and_still_uses_cas() -> None:
    repository, binder, synthesizer, service, processor = _service_parts()
    intent = build_nano_experiment_intent(
        novel_id=NOVEL_ID,
        base_preset_id=PRESET_ID,
        target=_narrator_target(),
        parameters=NanoDecodeParametersV3(seed=88),
        validation_input=_validation_input(),
        model_identity=_identity(),
        idempotency_key="nano-reuse-source-0001",
    )
    reusable = NanoReusableVersion(
        version_id=uuid4(),
        profile_id=intent.profile_id,
        model_run_id=uuid4(),
        preview_id=uuid4(),
        result_asset_id=uuid4(),
        fingerprint=intent.fingerprint,
        parameters_digest=intent.parameters_digest,
        model_fingerprint_sha256=(
            intent.model_identity.model_fingerprint_sha256
        ),
        output_sha256=hashlib.sha256(b"reusable-output").hexdigest(),
    )
    repository.reuse_by_fingerprint[intent.fingerprint] = reusable

    reservation = service.create(
        novel_id=NOVEL_ID,
        base_preset_id=PRESET_ID,
        target=_narrator_target(),
        parameters=NanoDecodeParametersV3(seed=88),
        idempotency_key="nano-reuse-command-0001",
    )
    assert reservation.reusable_version == reusable

    outcome = await processor.process(
        _lease(reservation.command.background_job_id)
    )

    assert outcome.command is not None
    assert outcome.command.state == "ready_applied"
    assert outcome.command.reused_version is True
    assert outcome.command.version_id == reusable.version_id
    assert synthesizer.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutate", "failure_code"),
    [
        ("parameters", "NANO_EXPERIMENT_PARAMETERS_MISMATCH"),
        ("input_hmac", "NANO_EXPERIMENT_PARAMETERS_MISMATCH"),
        ("actual_model", "NANO_EXPERIMENT_MODEL_IDENTITY_MISMATCH"),
        ("run_output", "NANO_EXPERIMENT_OUTPUT_HASH_MISMATCH"),
        ("audio_hash", "NANO_EXPERIMENT_OUTPUT_HASH_MISMATCH"),
        ("empty_audio", "NANO_EXPERIMENT_AUDIO_INVALID"),
        ("long_audio", "NANO_EXPERIMENT_AUDIO_INVALID"),
    ],
)
async def test_invalid_machine_evidence_never_binds(
    mutate: str, failure_code: str
) -> None:
    repository, binder, synthesizer, service, processor = _service_parts()
    synthesizer.mutate = mutate
    reservation = service.create(
        novel_id=NOVEL_ID,
        base_preset_id=PRESET_ID,
        target=_narrator_target(),
        parameters=NanoDecodeParametersV3(),
        idempotency_key=f"nano-test-invalid-{mutate}",
    )

    outcome = await processor.process(
        _lease(reservation.command.background_job_id)
    )

    assert outcome.status == "failed"
    assert outcome.failure_code == failure_code
    assert binder.narrator_version_id is None
    assert binder.complete_calls == 0
    assert repository.commands[reservation.command.command_id].state == "failed"


@pytest.mark.asyncio
async def test_synthesis_failure_has_no_default_retry_or_binding_side_effect() -> None:
    repository, binder, synthesizer, service, processor = _service_parts()
    synthesizer.error = NanoExperimentError(
        "NANO_EXPERIMENT_MODEL_UNAVAILABLE",
        "model unavailable",
        retryable=True,
    )
    reservation = service.create(
        novel_id=NOVEL_ID,
        base_preset_id=PRESET_ID,
        target=_narrator_target(),
        parameters=NanoDecodeParametersV3(seed=2026),
        idempotency_key="nano-test-model-down-0001",
    )

    outcome = await processor.process(
        _lease(reservation.command.background_job_id)
    )

    assert outcome.failure_code == "NANO_EXPERIMENT_MODEL_UNAVAILABLE"
    assert binder.narrator_version_id is None
    assert binder.complete_calls == 0
    assert len(synthesizer.requests) == 1
    assert synthesizer.requests[0].parameters.seed == 2026
    assert repository.failures[-1].retryable is True


@pytest.mark.asyncio
async def test_atomic_binder_failure_is_persisted_without_binding() -> None:
    repository, binder, synthesizer, service, processor = _service_parts()
    binder.raise_on_complete = True
    reservation = service.create(
        novel_id=NOVEL_ID,
        base_preset_id=PRESET_ID,
        target=_narrator_target(),
        parameters=NanoDecodeParametersV3(),
        idempotency_key="nano-test-db-failure-0001",
    )

    outcome = await processor.process(
        _lease(reservation.command.background_job_id)
    )

    assert outcome.failure_code == "NANO_EXPERIMENT_DATABASE_FAILED"
    assert binder.narrator_version_id is None
    assert len(synthesizer.requests) == 1
    assert repository.commands[reservation.command.command_id].state == "failed"


def test_explicit_apply_shape_is_target_specific() -> None:
    with pytest.raises(NanoExperimentContractError):
        NanoExperimentApplyRequest(4, 2).validate_for(_narrator_target())
    with pytest.raises(NanoExperimentContractError):
        NanoExperimentApplyRequest(4, None).validate_for(_character_target())


def test_reusable_version_must_match_complete_fingerprint() -> None:
    intent = build_nano_experiment_intent(
        novel_id=NOVEL_ID,
        base_preset_id=PRESET_ID,
        target=_narrator_target(),
        parameters=NanoDecodeParametersV3(),
        validation_input=_validation_input(),
        model_identity=_identity(),
        idempotency_key="nano-test-reuse-mismatch",
    )
    reusable = NanoReusableVersion(
        version_id=uuid4(),
        profile_id=intent.profile_id,
        model_run_id=uuid4(),
        preview_id=uuid4(),
        result_asset_id=uuid4(),
        fingerprint=hashlib.sha256(b"different-fingerprint").hexdigest(),
        parameters_digest=intent.parameters_digest,
        model_fingerprint_sha256=(
            intent.model_identity.model_fingerprint_sha256
        ),
        output_sha256=hashlib.sha256(b"output").hexdigest(),
    )
    with pytest.raises(
        NanoExperimentError,
        match="reusable Nano version does not match",
    ):
        from backend.narration.nano_experiments import validate_reusable_version

        validate_reusable_version(intent, reusable)
