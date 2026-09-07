"""Read-only authorization for a persisted character VoiceGenerator preview.

This selects an existing Nano validation asset; it never creates a Preview,
loads a model, accesses storage, or owns a transaction. HTTP callers must still
use the shared physical-media planner after this relational authorization.
"""

from __future__ import annotations

from datetime import datetime
from typing import TypeVar
from uuid import UUID

from ..models import (
    BackgroundJob,
    BackgroundJobAttempt,
    MediaAsset,
    ModelRunRecord,
    NovelCharacter,
    VoiceDesignDraft,
    VoiceGeneratorCommand,
    VoiceGeneratorRunEvidence,
    VoiceProfile,
    VoiceProfileVersion,
    VoiceRightsEvent,
)
from .contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID, NanoDecodeParametersV2
from .nano_experiments import production_nano_experiment_identity
from .services import (
    InvalidNarrationState,
    NarrationNotFound,
    NarrationScopeMismatch,
    NarrationStore,
    canonical_sha256,
    require_local_novel,
    require_sha256,
    require_usable_voice,
    utc_now,
)
from .voice_generator_runtime import (
    EXPECTED_AUDIO_PARAMETERS,
    EXPECTED_RUNTIME_FINGERPRINT,
    EXPECTED_RUNTIME_IDENTITY,
    HOST_PROTOCOL_VERSION,
    RUNTIME_TOPOLOGY,
)


T = TypeVar("T")


class _ReadOnlyStore:
    """Reuse activation/rights rules without row locks in profile projections."""

    def __init__(self, store: NarrationStore) -> None:
        self._store = store

    def get(self, model: type[T], row_id: object, *, for_update: bool = False) -> T | None:
        return self._store.get(model, row_id, for_update=False)

    def find_one(self, model: type[T], *, for_update: bool = False, **filters: object) -> T | None:
        return self._store.find_one(model, for_update=False, **filters)

    def find_all(
        self, model: type[T], *, order_by: tuple[str, ...] = (),
        for_update: bool = False, **filters: object,
    ) -> list[T]:
        return self._store.find_all(model, order_by=order_by, for_update=False, **filters)

    def add(self, row: object) -> None:
        raise InvalidNarrationState("voice media authorization is read-only")

    def flush(self) -> None:
        raise InvalidNarrationState("voice media authorization is read-only")

    def consume_render_publication_context(self, **kwargs: object) -> None:
        raise InvalidNarrationState("voice media authorization cannot publish")


def _required(store: NarrationStore, model: type[T], identity: UUID | None) -> T:
    row = store.get(model, identity) if identity is not None else None
    if row is None:
        raise NarrationNotFound("character voice preview evidence is unavailable")
    return row


def _scope(row: object, novel_id: UUID) -> None:
    if (
        getattr(row, "owner_id", None) != LOCAL_OWNER_ID
        or getattr(row, "workspace_id", None) != LOCAL_WORKSPACE_ID
        or getattr(row, "novel_id", None) != novel_id
    ):
        raise NarrationScopeMismatch("character voice preview evidence scope mismatch")


def _run(
    run: ModelRunRecord, *, provider: str, model: str, revision: str | None,
    fingerprint: str, output_digest: str,
) -> None:
    if (
        run.result_classification != "success"
        or run.requested_provider_id != provider
        or run.actual_provider_id != provider
        or run.requested_model_id != model
        or run.actual_model_id != model
        or run.requested_revision != revision
        or run.actual_revision != revision
        or run.model_fingerprint != fingerprint
        or run.output_digest != output_digest
        or run.duration_ms is None
        or run.duration_ms < 0
    ):
        raise InvalidNarrationState("character voice preview model evidence mismatch")


def _asset(asset: MediaAsset, *, novel_id: UUID, kind: str, asset_class: str, retention: str) -> None:
    _scope(asset, novel_id)
    if asset.state != "ready":
        raise NarrationNotFound("character voice preview media is unavailable")
    require_sha256(asset.content_hash, field="voice_media_hash")
    if (
        asset.kind != kind
        or asset.asset_class != asset_class
        or asset.retention_policy != retention
        or asset.storage_backend != "local"
        or asset.mime_type != "audio/wav"
        or asset.checksum_algorithm != "sha256"
        or asset.byte_size is None or asset.byte_size <= 0
        or asset.duration_ms is None or asset.duration_ms <= 0
        or asset.sample_rate is None or asset.sample_rate <= 0
        or asset.channels is None or asset.channels <= 0
        or asset.verified_at is None
        or asset.expires_at is not None
        or asset.storage_path != f"assets/{asset.id.hex[:2]}/{asset.id.hex}/{asset.content_hash}.wav"
    ):
        raise InvalidNarrationState("character voice preview media metadata mismatch")


def resolve_voice_version_media(
    store: NarrationStore,
    version_id: UUID,
    asset_id: UUID,
    *,
    at: datetime | None = None,
) -> MediaAsset:
    """Resolve only the completed character version's exact Nano validation WAV.

    A current character binding is deliberately not required: a successfully
    generated, unapplied voice and an author-replaced voice remain previewable
    while their own profile/rights/assets are available. Deleted legacy graphs
    are never reconstructed from a bare preview_asset_id.
    """

    readonly = _ReadOnlyStore(store)
    version = _required(readonly, VoiceProfileVersion, version_id)
    profile = _required(readonly, VoiceProfile, version.profile_id)
    if (
        profile.novel_id is None
        or profile.status != "active"
        or version.state != "locked"
        or version.source_type != "generated"
        or version.activation_basis != "character_one_click_generation"
        or version.preview_asset_id != asset_id
    ):
        raise NarrationNotFound("character voice version preview is unavailable")
    novel_id = profile.novel_id
    require_local_novel(readonly, novel_id)
    profile, version, rights = require_usable_voice(
        readonly, version_id, novel_id=novel_id, at=at or utc_now(),
    )
    _scope(rights, novel_id)
    events = readonly.find_all(VoiceRightsEvent, rights_record_id=rights.id)
    if not any(event.event_type == "confirmed" for event in events):
        raise NarrationNotFound("character voice rights confirmation is unavailable")
    commands = readonly.find_all(
        VoiceGeneratorCommand, voice_profile_id=profile.id, voice_version_id=version.id,
    )
    if len(commands) != 1:
        raise NarrationNotFound("character voice generation publication is unavailable")
    command = commands[0]
    _scope(command, novel_id)
    if (
        command.state not in {"ready_applied", "ready_unapplied"}
        or command.completed_at is None or command.failure_code is not None
        or command.nano_validation_asset_id != asset_id
        or command.generated_reference_asset_id != version.reference_asset_id
        or command.nano_model_run_id != version.model_run_id
    ):
        raise NarrationNotFound("character voice generation result is unavailable")
    draft = _required(readonly, VoiceDesignDraft, command.draft_id)
    job = _required(readonly, BackgroundJob, command.background_job_id)
    character = _required(readonly, NovelCharacter, command.character_id)
    _scope(draft, novel_id)
    _scope(job, novel_id)
    if character.novel_id != novel_id or draft.character_id != command.character_id:
        raise NarrationScopeMismatch("character voice generation character scope mismatch")
    if (
        job.job_kind != "narration.voice_generate" or job.state != "succeeded"
        or job.resource_class != "moss-nano" or job.input_hash != draft.fingerprint
    ):
        raise InvalidNarrationState("character voice preview job evidence mismatch")
    asset = _required(readonly, MediaAsset, asset_id)
    reference = _required(readonly, MediaAsset, version.reference_asset_id)
    _asset(asset, novel_id=novel_id, kind="narration_voice_preview", asset_class="preview", retention="private_voice_validation")
    _asset(reference, novel_id=novel_id, kind="narration_voice_reference", asset_class="voice_reference", retention="private_voice_source")
    generator = _required(readonly, ModelRunRecord, command.generator_model_run_id)
    nano = _required(readonly, ModelRunRecord, command.nano_model_run_id)
    identity = production_nano_experiment_identity()
    _run(generator, provider="local-native-host", model=version.model_id,
         revision=version.model_revision, fingerprint=EXPECTED_RUNTIME_FINGERPRINT, output_digest=reference.content_hash)
    _run(nano, provider=identity.requested_provider_id, model=identity.requested_model_id,
         revision=identity.requested_revision, fingerprint=identity.model_fingerprint_sha256, output_digest=asset.content_hash)
    attempt = _required(readonly, BackgroundJobAttempt, generator.attempt_id)
    if (
        nano.attempt_id != attempt.id or attempt.job_id != job.id
        or attempt.completed_at is None
        or attempt.error_classification is not None or attempt.error_code is not None
        or attempt.actual_result_digest != canonical_sha256({
            "schema_version": "voice-generator-result/1", "command_id": str(command.id),
            "voice_version_id": str(version.id), "generator_audio_sha256": reference.content_hash,
            "nano_audio_sha256": asset.content_hash,
        })
    ):
        raise InvalidNarrationState("character voice preview attempt evidence mismatch")
    evidence_rows = readonly.find_all(
        VoiceGeneratorRunEvidence, command_id=command.id, model_run_id=generator.id,
    )
    if len(evidence_rows) != 1:
        raise NarrationNotFound("character voice runtime receipt is unavailable")
    evidence = evidence_rows[0]
    runtime_identity = EXPECTED_RUNTIME_IDENTITY.wire_payload()
    if (
        evidence.result_classification != "success" or evidence.exit_reason_code != "COMPLETED"
        or evidence.attempt_number != attempt.attempt_number
        or evidence.protocol_version != HOST_PROTOCOL_VERSION or evidence.topology != RUNTIME_TOPOLOGY
        or evidence.runtime_fingerprint != EXPECTED_RUNTIME_FINGERPRINT
        or evidence.requested_identity_json != runtime_identity
        or evidence.actual_identity_json != runtime_identity
        or evidence.audio_digest != reference.content_hash
        or evidence.instruction_digest != draft.instruction_digest
        or generator.input_digest != draft.instruction_digest
        or generator.input_digest_key_id != draft.instruction_digest_key_id
        or generator.parameters_digest != draft.parameters_digest
        or version.description_digest != draft.instruction_digest
        or version.description_digest_key_id != draft.instruction_digest_key_id
        or draft.runtime_identity_json != runtime_identity
        or draft.parameters_json != EXPECTED_AUDIO_PARAMETERS.wire_payload()
        or draft.parameters_digest != canonical_sha256(draft.parameters_json)
        or nano.parameters_digest != canonical_sha256({
            "schema_version": "voice-generator-nano-validation-parameters/1",
            "seed": draft.seed, "sample_mode": "full", "max_new_frames": 375,
            "decode_parameters": dict(NanoDecodeParametersV2().wire_payload()),
            "reference_sha256": reference.content_hash,
        })
        or version.provider_id != "local-native-host"
        or version.seed != draft.seed or version.language != draft.language
        or rights.source_identifier != f"local://voice-generator/{command.id}"
        or rights.notice_version != "voice-generator-private-use/1"
        or rights.risk_flags_json != []
    ):
        raise InvalidNarrationState("character voice preview runtime evidence mismatch")
    require_sha256(evidence.request_digest, field="voice_request_digest")
    require_sha256(evidence.token_digest, field="voice_token_digest")
    require_sha256(nano.input_digest, field="nano_input_digest")
    if not nano.input_digest_key_id:
        raise InvalidNarrationState("character voice preview input digest key is absent")
    if (
        version.parameters_json != {
            "schema_version": "voice-generator-version/1", "draft_fingerprint": draft.fingerprint,
            "runtime_identity": runtime_identity, "generator_parameters": draft.parameters_json,
            "nano_parameters_digest": nano.parameters_digest,
        }
        or version.fingerprint != canonical_sha256({
            "schema_version": "voice-generator-version/1", "draft_fingerprint": draft.fingerprint,
            "generator_audio_sha256": reference.content_hash, "nano_audio_sha256": asset.content_hash,
            "generator_model_run_id": str(generator.id), "nano_model_run_id": str(nano.id),
            "runtime_fingerprint": EXPECTED_RUNTIME_FINGERPRINT,
            "nano_model_fingerprint": identity.model_fingerprint_sha256,
        })
        or asset.metadata_json != {"schema_version": "voice-generator-validation/1", "command_id": str(command.id)}
        or asset.validation_json != {
            "schema_version": "voice-generator-nano-validation/1", "reference_sha256": reference.content_hash,
            "model_fingerprint": identity.model_fingerprint_sha256,
        }
        or reference.metadata_json != {
            "schema_version": "voice-generator-reference/1", "command_id": str(command.id),
            "runtime_fingerprint": EXPECTED_RUNTIME_FINGERPRINT,
        }
    ):
        raise InvalidNarrationState("character voice preview asset provenance mismatch")
    return asset
