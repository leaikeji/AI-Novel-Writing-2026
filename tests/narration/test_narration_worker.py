from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import hashlib
from io import BytesIO
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Mapping
import wave
from uuid import uuid4

import pytest

from backend.models import (
    BackgroundJob,
    Document,
    DocumentNarrationState,
    DocumentWorkingCopy,
    NarrationEdition,
    NarrationEditionSegment,
    NarrationManifest,
    NarrationRequest,
)
from backend.narration.adapters import FakeMossNanoTTSAdapter
from backend.narration.audio_pipeline import (
    AudioFormatError,
    AudioQualityError,
    ProcessedPcmWav,
)
from backend.narration.contracts import (
    ContractError,
    NanoDecodeParametersV2,
    NarrationRequestScope,
    ReferenceAudioInput,
    SynthesisRequest,
    SynthesisResult,
)
from backend.narration.digest_keyring import HmacDigestKey
from backend.narration.disk_guard import NarrationDiskGuardError
from backend.narration.fingerprints import model_fingerprint_sha256
from backend.narration.jobs import FailureResult, JobFence, JobFenceError, JobLease
from backend.narration.manifest import (
    INITIAL_BUFFER_POLICY,
    ManifestSegmentInput,
    PublishManifest,
    publish_manifest,
)
from backend.narration.nano_experiments import (
    NANO_EXPERIMENT_MAX_NEW_FRAMES,
    NANO_EXPERIMENT_SAMPLE_MODE,
    NanoDecodeParametersV3,
)
from backend.narration.official_presets import (
    OFFICIAL_PRESET_MANIFEST_PATH,
    OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256,
    OFFICIAL_PRESET_REPOSITORY,
    OFFICIAL_PRESET_REVISION,
    OFFICIAL_PRESET_RIGHTS_POLICY_VERSION,
    require_official_preset,
)
from backend.narration.progress import initialize_initial_document_edition
from backend.narration.resource_locks import ResourceFence
from backend.narration.runtime import canonical_sidecar_synthesis_metadata
from backend.narration.voice_generator_runtime import (
    EXPECTED_AUDIO_PARAMETERS as VOICE_GENERATOR_AUDIO_PARAMETERS,
    EXPECTED_RUNTIME_IDENTITY as VOICE_GENERATOR_RUNTIME_IDENTITY,
    VOICE_GENERATOR_REVISION,
)
from backend.narration.scheduler import (
    NarrationJobScheduler,
    SchedulerConfig,
    SchedulerMaintenance,
)
from backend.narration.services import InvalidNarrationState
from backend.narration.storage import NarrationStorage
from backend.narration.transcoding import TranscodeArtifact, TranscodedSegment
from backend.narration import worker as worker_module
from backend.narration.worker import (
    NarrationSegmentWorker,
    NarrationWorkerConfig,
    PreparedRender,
    SegmentWorkItem,
    ReferenceMedia,
    SqlAlchemyNarrationWorkerRepository,
    WorkerContractError,
    derive_model_input_digest,
)
from backend.narration.renders import render_job_input_hash
from tests.narration.test_domain_services import (
    MemoryNarrationStore,
    _edition_with_ready_renders,
)


NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def _nano_experiment_voice_evidence() -> tuple[SimpleNamespace, SimpleNamespace]:
    preset = require_official_preset("onnx.Zhiming")
    owner_id = uuid4()
    workspace_id = uuid4()
    complete_parameters = NanoDecodeParametersV3(
        seed=9_876,
        text_temperature_milli=1_250,
        text_top_p_milli=875,
        text_top_k=41,
        audio_temperature_milli=925,
        audio_top_p_milli=825,
        audio_top_k=19,
        audio_repetition_penalty_milli=1_350,
    )
    voice = SimpleNamespace(
        id=uuid4(),
        profile_id=uuid4(),
        owner_id=owner_id,
        workspace_id=workspace_id,
        source_type="generated",
        provider_id="local-sidecar",
        model_id=OFFICIAL_PRESET_REPOSITORY,
        model_revision=OFFICIAL_PRESET_REVISION,
        preset_key=preset.preset_id,
        reference_asset_id=None,
        language=preset.language,
        seed=complete_parameters.seed,
        state="locked",
        quality_state="accepted",
        activation_basis="experimental_machine_validated",
        validation_basis="machine_validated",
        model_run_id=uuid4(),
        locked_actor=None,
        locked_at=None,
        fingerprint="a" * 64,
        parameters_json={
            "schema_version": "narration-nano-experiment-version/1",
            "official_preset": preset.provenance(),
            "sample_mode": NANO_EXPERIMENT_SAMPLE_MODE,
            "max_new_frames": NANO_EXPERIMENT_MAX_NEW_FRAMES,
            "decode_parameters": dict(complete_parameters.canonical_payload()),
        },
    )
    rights = SimpleNamespace(
        owner_id=owner_id,
        workspace_id=workspace_id,
        source_kind="official_preset",
        source_identifier=(
            f"hf://{OFFICIAL_PRESET_REPOSITORY}@{OFFICIAL_PRESET_REVISION}/"
            f"{OFFICIAL_PRESET_MANIFEST_PATH}#{preset.preset_id}"
        ),
        notice_version=OFFICIAL_PRESET_RIGHTS_POLICY_VERSION,
        purpose="private_novel_narration",
        commercial_use=False,
        redistribution=False,
        voice_cloning=False,
        subject_consent_reference=None,
        expires_at=None,
        risk_flags_json=["COMMERCIAL_DISTRIBUTION_NOT_EVALUATED"],
        confirmed_actor="owner",
        confirmed_at=NOW,
    )
    return voice, rights


def test_worker_projects_validated_nano_experiment_into_sidecar_parameters() -> None:
    voice, rights = _nano_experiment_voice_evidence()

    decoded = worker_module._validated_nano_experiment_decode_parameters(  # noqa: SLF001
        voice=voice,
        rights=rights,
        render_model_fingerprint=OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256,
    )

    assert dict(decoded.wire_payload()) == {
        "schema_version": "moss-nano-decode-parameters/2",
        "text_temperature_milli": 1_250,
        "text_top_p_milli": 875,
        "text_top_k": 41,
        "audio_temperature_milli": 925,
        "audio_top_p_milli": 825,
        "audio_top_k": 19,
        "audio_repetition_penalty_milli": 1_350,
    }


def test_worker_rejects_nano_experiment_evidence_drift() -> None:
    voice, rights = _nano_experiment_voice_evidence()
    voice.seed += 1

    with pytest.raises(
        worker_module.WorkerSecurityError,
        match="version evidence changed",
    ):
        worker_module._validated_nano_experiment_decode_parameters(  # noqa: SLF001
            voice=voice,
            rights=rights,
            render_model_fingerprint=OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256,
        )

    voice.seed -= 1
    with pytest.raises(
        worker_module.WorkerSecurityError,
        match="render model identity changed",
    ):
        worker_module._validated_nano_experiment_decode_parameters(  # noqa: SLF001
            voice=voice,
            rights=rights,
            render_model_fingerprint="b" * 64,
        )


def _voice_generator_voice_evidence() -> tuple[SimpleNamespace, SimpleNamespace]:
    owner_id = uuid4()
    workspace_id = uuid4()
    voice = SimpleNamespace(
        id=uuid4(),
        profile_id=uuid4(),
        owner_id=owner_id,
        workspace_id=workspace_id,
        source_type="generated",
        provider_id="local-native-host",
        model_id="OpenMOSS-Team/MOSS-VoiceGenerator",
        model_revision=VOICE_GENERATOR_REVISION,
        preset_key=None,
        reference_asset_id=uuid4(),
        language="zh-CN",
        seed=104_729,
        state="locked",
        quality_state="accepted",
        activation_basis="character_one_click_generation",
        validation_basis="machine_validated",
        model_run_id=uuid4(),
        locked_actor=None,
        locked_at=None,
        fingerprint="a" * 64,
        description_digest_key_id="vg40-test-key",
        description_digest="b" * 64,
        parameters_json={
            "schema_version": "voice-generator-version/1",
            "draft_fingerprint": "c" * 64,
            "runtime_identity": dict(
                VOICE_GENERATOR_RUNTIME_IDENTITY.wire_payload()
            ),
            "generator_parameters": dict(
                VOICE_GENERATOR_AUDIO_PARAMETERS.wire_payload()
            ),
            "nano_parameters_digest": "d" * 64,
        },
    )
    rights = SimpleNamespace(
        owner_id=owner_id,
        workspace_id=workspace_id,
        source_kind="voice_generator",
        source_identifier=f"local://voice-generator/{uuid4()}",
        notice_version="voice-generator-private-use/1",
        purpose="private_novel_narration",
        commercial_use=False,
        redistribution=False,
        voice_cloning=False,
        subject_consent_reference=None,
        expires_at=None,
        risk_flags_json=[],
    )
    return voice, rights


@pytest.mark.parametrize(
    "activation_basis",
    ("character_one_click_generation", "generic_voice_pack_generation"),
)
def test_worker_projects_validated_voice_generator_reference_to_nano(
    activation_basis: str,
) -> None:
    voice, rights = _voice_generator_voice_evidence()
    voice.activation_basis = activation_basis
    if activation_basis == "generic_voice_pack_generation":
        voice.parameters_json = {
            "schema_version": "generic-voice-version/1",
            "design_fingerprint": "e" * 64,
        }
        rights.source_identifier = f"local://generic-voice/{uuid4()}/male_child_bright"

    decoded = worker_module._validated_voice_generator_decode_parameters(  # noqa: SLF001
        voice=voice,
        rights=rights,
        render_model_fingerprint=OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256,
    )

    assert decoded == NanoDecodeParametersV2()


def test_worker_rejects_generic_voice_with_character_parameter_shape() -> None:
    voice, rights = _voice_generator_voice_evidence()
    voice.activation_basis = "generic_voice_pack_generation"

    with pytest.raises(
        worker_module.WorkerSecurityError,
        match="version evidence changed",
    ):
        worker_module._validated_voice_generator_decode_parameters(  # noqa: SLF001
            voice=voice,
            rights=rights,
            render_model_fingerprint=OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256,
        )


def test_worker_rejects_voice_generator_evidence_drift() -> None:
    voice, rights = _voice_generator_voice_evidence()
    voice.parameters_json["runtime_identity"] = {"schema_version": "changed"}

    with pytest.raises(
        worker_module.WorkerSecurityError,
        match="version evidence changed",
    ):
        worker_module._validated_voice_generator_decode_parameters(  # noqa: SLF001
            voice=voice,
            rights=rights,
            render_model_fingerprint=OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256,
        )


def test_worker_resolves_one_source_job_and_all_identical_segment_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fingerprint = "a" * 64
    request_id = uuid4()
    novel_id = uuid4()
    owner_id = uuid4()
    workspace_id = uuid4()
    document_id = uuid4()
    edition_id = uuid4()
    script_version_id = uuid4()
    voice_id = uuid4()
    profile_id = uuid4()
    source_id = uuid4()
    alias_id = uuid4()
    job = SimpleNamespace(
        id=uuid4(),
        input_hash=render_job_input_hash(
            edition_segment_id=source_id,
            render_fingerprint=fingerprint,
        ),
        request_id=request_id,
        novel_id=novel_id,
        owner_id=owner_id,
        workspace_id=workspace_id,
    )
    render = SimpleNamespace(
        owner_id=owner_id,
        workspace_id=workspace_id,
        novel_id=novel_id,
        request_id=request_id,
        render_fingerprint=fingerprint,
        voice_version_id=voice_id,
        model_fingerprint="b" * 64,
        postprocess_fingerprint="c" * 64,
    )
    edition = SimpleNamespace(
        id=edition_id,
        owner_id=owner_id,
        workspace_id=workspace_id,
        novel_id=novel_id,
        document_id=document_id,
        request_id=request_id,
        script_version_id=script_version_id,
        tts_fingerprint="b" * 64,
        postprocess_fingerprint="c" * 64,
    )
    source = SimpleNamespace(
        id=source_id,
        profile_id=profile_id,
        render_fingerprint=fingerprint,
    )
    alias = SimpleNamespace(
        id=alias_id,
        profile_id=profile_id,
        render_fingerprint=fingerprint,
    )
    source_text = SimpleNamespace(script_version_id=script_version_id)
    alias_text = SimpleNamespace(script_version_id=script_version_id)
    voice = SimpleNamespace(id=voice_id, profile_id=profile_id)

    class _Rows:
        def all(self) -> list[tuple[object, object, object, object]]:
            return [
                (edition, source, source_text, voice),
                (edition, alias, alias_text, voice),
            ]

    class _Session:
        def scalar(self, _statement: object) -> object:
            return render

        def execute(self, _statement: object) -> _Rows:
            return _Rows()

    repository = object.__new__(SqlAlchemyNarrationWorkerRepository)
    repository._digest_keyring = object()  # type: ignore[assignment]
    monkeypatch.setattr(
        worker_module,
        "compute_render_fingerprint",
        lambda *_args, **_kwargs: fingerprint,
    )

    rows = repository._work_rows(  # noqa: SLF001
        _Session(),  # type: ignore[arg-type]
        job=job,  # type: ignore[arg-type]
        for_update=True,
    )

    assert rows.edition_segment is source
    assert rows.segment is source_text
    assert rows.fanout_segments == (source, alias)
    assert rows.fanout_editions == (edition,)

    job.input_hash = render_job_input_hash(
        edition_segment_id=uuid4(),
        render_fingerprint=fingerprint,
    )
    with pytest.raises(
        InvalidNarrationState,
        match="input does not name one canonical source segment",
    ):
        repository._work_rows(  # noqa: SLF001
            _Session(),  # type: ignore[arg-type]
            job=job,  # type: ignore[arg-type]
            for_update=True,
        )


class _PointerLockTrackingStore(MemoryNarrationStore):
    def __init__(self) -> None:
        super().__init__()
        self.pointer_lock_order: list[type[object]] = []

    def get(
        self,
        model: type[object],
        row_id: object,
        *,
        for_update: bool = False,
    ) -> object | None:
        if for_update and model in {
            NarrationRequest,
            Document,
            NarrationEdition,
        }:
            self.pointer_lock_order.append(model)
        return super().get(model, row_id, for_update=for_update)

    def find_one(
        self,
        model: type[object],
        *,
        for_update: bool = False,
        **filters: object,
    ) -> object | None:
        if for_update and model in {
            DocumentWorkingCopy,
            DocumentNarrationState,
        }:
            self.pointer_lock_order.append(model)
        return super().find_one(model, for_update=for_update, **filters)


def _initial_pointer_foundation(
    *,
    playable: bool = True,
    store: MemoryNarrationStore | None = None,
):
    target_store = store or MemoryNarrationStore()
    foundation = _edition_with_ready_renders(target_store)
    _novel, document, revision, request, edition, _segments, renders, *_rest = (
        foundation
    )
    target_store.add(
        DocumentWorkingCopy(
            document_id=document.id,
            base_revision_id=revision.id,
            draft_version=1,
            content_markdown=revision.content_markdown,
            content_hash=revision.content_hash,
        )
    )
    edition_rows = target_store.find_all(
        NarrationEditionSegment,
        edition_id=edition.id,
        order_by=("ordinal",),
    )
    if not playable:
        edition_rows[1].render_state = "pending"
    manifest = publish_manifest(
        target_store,
        PublishManifest(
            edition_id=edition.id,
            expected_current_revision=0,
            expected_state_version=0,
            buffer_policy=INITIAL_BUFFER_POLICY,
            segments=tuple(
                ManifestSegmentInput(
                    row.id,
                    row.render_state,
                    renders[index].id if row.render_state == "ready" else None,
                )
                for index, row in enumerate(edition_rows)
            ),
            updated_actor="test-worker",
        ),
    )
    request.state = manifest.status
    return target_store, document, revision, request, edition, manifest


def _initialize_pointer(
    store: MemoryNarrationStore,
    document: Document,
    request: NarrationRequest,
    edition: NarrationEdition,
    manifest: NarrationManifest,
) -> DocumentNarrationState | None:
    return initialize_initial_document_edition(
        store,
        request_id=request.id,
        document_id=document.id,
        edition_id=edition.id,
        manifest_id=manifest.id,
    )


def test_first_playable_create_installs_initial_pointer_in_global_lock_order() -> None:
    store = _PointerLockTrackingStore()
    store, document, _revision, request, edition, manifest = (
        _initial_pointer_foundation(store=store)
    )
    store.pointer_lock_order.clear()

    pointer = _initialize_pointer(store, document, request, edition, manifest)

    assert pointer is not None
    assert pointer.current_edition_id == edition.id
    assert pointer.current_script_version_id == edition.script_version_id
    assert pointer.version == 1
    assert pointer.switched_actor == request.explicit_generation_actor == "owner"
    assert store.pointer_lock_order[:5] == [
        NarrationRequest,
        Document,
        DocumentWorkingCopy,
        DocumentNarrationState,
        NarrationEdition,
    ]


def test_initial_pointer_never_replaces_an_existing_current_edition() -> None:
    store, document, _revision, request, edition, manifest = (
        _initial_pointer_foundation()
    )
    existing_id = uuid4()
    existing = DocumentNarrationState(
        id=uuid4(),
        owner_id=request.owner_id,
        workspace_id=request.workspace_id,
        document_id=document.id,
        script_id=None,
        current_script_version_id=None,
        current_edition_id=existing_id,
        version=7,
        switched_actor="owner",
        switched_at=NOW,
    )
    store.add(existing)
    before_flush = store.flush_count

    assert _initialize_pointer(store, document, request, edition, manifest) is None
    assert existing.current_edition_id == existing_id
    assert existing.version == 7
    assert store.flush_count == before_flush


def test_initial_pointer_advances_one_existing_empty_pointer_once() -> None:
    store, document, _revision, request, edition, manifest = (
        _initial_pointer_foundation()
    )
    empty = DocumentNarrationState(
        id=uuid4(),
        owner_id=request.owner_id,
        workspace_id=request.workspace_id,
        document_id=document.id,
        script_id=None,
        current_script_version_id=None,
        current_edition_id=None,
        version=3,
        switched_actor="analysis",
        switched_at=NOW,
    )
    store.add(empty)

    pointer = _initialize_pointer(store, document, request, edition, manifest)

    assert pointer is empty
    assert empty.current_edition_id == edition.id
    assert empty.version == 4
    assert _initialize_pointer(store, document, request, edition, manifest) is None
    assert empty.current_edition_id == edition.id
    assert empty.version == 4


def test_initial_pointer_skips_when_working_copy_hash_has_diverged() -> None:
    store, document, _revision, request, edition, manifest = (
        _initial_pointer_foundation()
    )
    working = store.find_one(DocumentWorkingCopy, document_id=document.id)
    assert working is not None
    working.content_hash = "f" * 64
    working.draft_version += 1
    before_flush = store.flush_count

    assert _initialize_pointer(store, document, request, edition, manifest) is None
    assert store.find_one(DocumentNarrationState, document_id=document.id) is None
    assert store.flush_count == before_flush


def test_initial_pointer_requires_explicit_create_generation_evidence() -> None:
    store, document, _revision, request, edition, manifest = (
        _initial_pointer_foundation()
    )
    request.explicit_generation_actor = None

    with pytest.raises(InvalidNarrationState):
        _initialize_pointer(store, document, request, edition, manifest)
    assert store.find_one(DocumentNarrationState, document_id=document.id) is None


@pytest.mark.parametrize("intent", ["update", "batch", "analyze_only"])
def test_initial_pointer_is_create_only(intent: str) -> None:
    store, document, _revision, request, edition, manifest = (
        _initial_pointer_foundation()
    )
    request.intent = intent
    before_flush = store.flush_count

    assert _initialize_pointer(store, document, request, edition, manifest) is None
    assert store.find_one(DocumentNarrationState, document_id=document.id) is None
    assert store.flush_count == before_flush


def test_initial_pointer_waits_until_manifest_has_a_playable_range() -> None:
    store, document, _revision, request, edition, manifest = (
        _initial_pointer_foundation(playable=False)
    )
    assert manifest.status == "partial_ready"
    assert manifest.ready_ranges_json == []

    assert _initialize_pointer(store, document, request, edition, manifest) is None
    assert store.find_one(DocumentNarrationState, document_id=document.id) is None


def _model_input_metadata(**changes: object) -> bytes:
    values: dict[str, object] = {
        "request_id": uuid4(),
        "scope": NarrationRequestScope.fixed_local(),
        "requested_model_fingerprint_sha256": "a" * 64,
        "text": "不要把这句私密台词写入日志。",
        "voice": "narrator-young-female",
        "seed": 7,
        "sample_mode": "fixed",
        "max_new_frames": 375,
        "reference_content_type": "audio/wav",
        "reference_actual_sha256": "b" * 64,
        "reference_size_bytes": 8192,
    }
    values.update(changes)
    return canonical_sidecar_synthesis_metadata(**values)  # type: ignore[arg-type]


def test_model_input_hmac_covers_every_sidecar_metadata_field() -> None:
    key = HmacDigestKey("worker-audit-test-v1", b"worker-audit-test-key-material-0001")
    base = _model_input_metadata()
    key_id, digest = derive_model_input_digest(key, sidecar_metadata=base)

    assert key_id == key.key_id
    assert len(digest) == 64
    assert digest != hashlib.sha256(base).hexdigest()
    for change in (
        {"request_id": uuid4()},
        {"requested_model_fingerprint_sha256": "c" * 64},
        {"text": "另一句台词。"},
        {"voice": "narrator-middle-aged-female"},
        {"seed": 8},
        {"sample_mode": "greedy"},
        {"max_new_frames": 374},
        {"reference_content_type": "audio/flac"},
        {"reference_actual_sha256": "d" * 64},
        {"reference_size_bytes": 8193},
    ):
        assert derive_model_input_digest(
            key,
            sidecar_metadata=_model_input_metadata(**change),
        )[1] != digest
    other_key = HmacDigestKey(
        "worker-audit-test-v2", b"worker-audit-test-key-material-0002"
    )
    assert derive_model_input_digest(other_key, sidecar_metadata=base)[1] != digest


@pytest.mark.parametrize(
    "change",
    (
        {"seed": -1},
        {"seed": 2**63},
        {"seed": True},
        {"sample_mode": "narration-segment"},
        {"sample_mode": "preview"},
        {"max_new_frames": 376},
        {"max_new_frames": 4096},
    ),
)
def test_sidecar_metadata_rejects_values_outside_frozen_nano_runtime(
    change: dict[str, object],
) -> None:
    with pytest.raises(ContractError):
        _model_input_metadata(**change)


def test_private_worker_payloads_are_redacted_from_repr() -> None:
    lease = _lease()
    private_text = "绝不能出现在 repr 的私密台词"
    private_path = "private/voice/reference-secret.wav"
    reference = ReferenceMedia(
        relative_path=private_path,
        actual_sha256="e" * 64,
        byte_size=32,
        content_type="audio/wav",
    )
    work = SegmentWorkItem(
        lease=lease,
        render_id=uuid4(),
        edition_id=uuid4(),
        edition_segment_id=uuid4(),
        request_id=uuid4(),
        novel_id=uuid4(),
        text=private_text,
        voice="private-voice",
        seed=1,
        sample_mode="fixed",
        max_new_frames=100,
        requested_provider_id="local",
        requested_model_id="moss",
        requested_revision=None,
        expected_model_fingerprint="a" * 64,
        expected_postprocess_fingerprint="3" * 64,
        parameters_digest="b" * 64,
        input_digest_key_id="private-test-key",
        input_digest="c" * 64,
        reference_media=reference,
    )
    audio = b"private-reference-bytes"
    reference_input = ReferenceAudioInput(
        audio_bytes=audio,
        actual_sha256=hashlib.sha256(audio).hexdigest(),
    )
    synthesis = SynthesisRequest(
        request_id=lease.fence.attempt_id,
        scope=NarrationRequestScope.fixed_local(),
        text=private_text,
        voice="private-voice",
        seed=1,
        sample_mode="fixed",
        max_new_frames=100,
        reference_audio=reference_input,
    )

    combined = repr(work) + repr(reference) + repr(reference_input) + repr(synthesis)
    assert private_text not in combined
    assert private_path not in combined
    assert repr(audio) not in combined


def _wav_bytes(*, silent: bool = False, duration_ms: int = 120) -> bytes:
    frames = round(48_000 * duration_ms / 1000)
    payload = bytearray()
    for index in range(frames):
        sample = 0 if silent else round(4_000 * math.sin(index * math.tau * 220 / 48_000))
        encoded = sample.to_bytes(2, "little", signed=True)
        payload.extend(encoded)
        payload.extend(encoded)
    output = BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(2)
        writer.setsampwidth(2)
        writer.setframerate(48_000)
        writer.writeframes(bytes(payload))
    return output.getvalue()


class ControlledAdapter(FakeMossNanoTTSAdapter):
    def __init__(
        self,
        *,
        silent: bool = False,
        delay_seconds: float = 0.0,
        duration_ms: int = 120,
    ) -> None:
        super().__init__()
        self.silent = silent
        self.delay_seconds = delay_seconds
        self.duration_ms = duration_ms
        self.cancel_calls: list[object] = []

    async def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        fingerprint = await self.model_fingerprint()
        payload = _wav_bytes(silent=self.silent, duration_ms=self.duration_ms)
        return SynthesisResult(
            request_id=request.request_id,
            audio_bytes=payload,
            actual_output_sha256=hashlib.sha256(payload).hexdigest(),
            sample_rate_hz=48_000,
            channels=2,
            sample_width_bytes=2,
            model_fingerprint=fingerprint,
            worker_generation=1,
        )

    async def cancel(self, request_id: object) -> object:
        self.cancel_calls.append(request_id)
        return await super().cancel(request_id)  # type: ignore[arg-type]


class FakeScheduler:
    def __init__(self, lease: JobLease | None) -> None:
        self.lease = lease
        self.claim_count = 0
        self.maintenance_count = 0

    def claim_next_segment(self) -> JobLease | None:
        self.claim_count += 1
        value, self.lease = self.lease, None
        return value

    def maintain_once(self) -> None:
        self.maintenance_count += 1


class FakeRepository:
    def __init__(
        self,
        work: SegmentWorkItem,
        *,
        read_states: list[str] | None = None,
        heartbeat_states: list[str] | None = None,
        failure_state: str = "failed",
        publish_error: BaseException | None = None,
        load_error: BaseException | None = None,
    ) -> None:
        self.work = work
        self.read_states = read_states or ["running", "running"]
        self.heartbeat_states = heartbeat_states or ["running"]
        self.failure_state = failure_state
        self.publish_error = publish_error
        self.load_error = load_error
        self.loaded = 0
        self.heartbeats = 0
        self.cancelled = 0
        self.published: list[PreparedRender] = []
        self.failures: list[tuple[str, str]] = []
        self.failure_evidence: list[Mapping[str, object] | None] = []
        self.claim_failures: list[tuple[str, str]] = []

    def load_and_mark_running(
        self, lease: JobLease, *, default_max_new_frames: int, actor: str
    ) -> SegmentWorkItem:
        assert lease == self.work.lease
        assert default_max_new_frames == 375
        assert actor == "test-worker"
        if self.load_error is not None:
            raise self.load_error
        self.loaded += 1
        return self.work

    def read_job_state(self, _lease: JobLease) -> str:
        if len(self.read_states) > 1:
            return self.read_states.pop(0)
        return self.read_states[0]

    def heartbeat_and_read_state(self, _lease: JobLease) -> str:
        self.heartbeats += 1
        if len(self.heartbeat_states) > 1:
            return self.heartbeat_states.pop(0)
        return self.heartbeat_states[0]

    def acknowledge_cancel(self, _work: SegmentWorkItem) -> None:
        self.cancelled += 1

    def publish(
        self, _work: SegmentWorkItem, prepared: PreparedRender, *, actor: str
    ) -> None:
        assert actor == "test-worker"
        if self.publish_error is not None:
            raise self.publish_error
        self.published.append(prepared)

    def fail(
        self,
        _work: SegmentWorkItem,
        *,
        classification: str,
        error_code: str,
        failure_evidence: Mapping[str, object] | None = None,
    ) -> FailureResult:
        self.failures.append((classification, error_code))
        self.failure_evidence.append(failure_evidence)
        return FailureResult(
            job_id=self.work.lease.fence.job_id,
            state=self.failure_state,  # type: ignore[arg-type]
            next_retry_at=(NOW + timedelta(seconds=5) if self.failure_state == "retry_wait" else None),
        )

    def fail_claim(
        self,
        _lease: JobLease,
        *,
        classification: str,
        error_code: str,
    ) -> FailureResult:
        self.claim_failures.append((classification, error_code))
        return FailureResult(
            job_id=self.work.lease.fence.job_id,
            state=self.failure_state,  # type: ignore[arg-type]
            next_retry_at=(NOW + timedelta(seconds=5) if self.failure_state == "retry_wait" else None),
        )


def _lease() -> JobLease:
    resource = ResourceFence(
        resource_key="moss-nano:inference",
        lease_owner="test-worker",
        lease_token=uuid4(),
        lease_generation=1,
    )
    return JobLease(
        fence=JobFence(
            job_id=uuid4(),
            attempt_id=uuid4(),
            lease_token=uuid4(),
            lease_generation=1,
        ),
        attempt_number=1,
        retry_kind="initial",
        lease_owner="test-worker",
        lease_until=NOW + timedelta(minutes=2),
        executor_epoch_id=uuid4(),
        resource_fence=resource,
    )


async def _work(adapter: ControlledAdapter, lease: JobLease) -> SegmentWorkItem:
    fingerprint = await adapter.model_fingerprint()
    return SegmentWorkItem(
        lease=lease,
        render_id=uuid4(),
        edition_id=uuid4(),
        edition_segment_id=uuid4(),
        request_id=uuid4(),
        novel_id=uuid4(),
        text="第一句测试台词。",
        voice="narrator-young-female",
        seed=7,
        sample_mode="fixed",
        max_new_frames=375,
        requested_provider_id="local-sidecar",
        requested_model_id=fingerprint.model_name,
        requested_revision=fingerprint.model_revision,
        expected_model_fingerprint=model_fingerprint_sha256(fingerprint),
        expected_postprocess_fingerprint="3" * 64,
        parameters_digest="1" * 64,
        input_digest_key_id="render-fingerprint-v1",
        input_digest="2" * 64,
    )


def _storage(tmp_path: Path) -> NarrationStorage:
    models = tmp_path / "models"
    media = tmp_path / "media"
    models.mkdir()
    media.mkdir()
    return NarrationStorage(models_root=models, media_root=media)


def _transcode(processed: ProcessedPcmWav) -> TranscodedSegment:
    def artifact() -> TranscodeArtifact:
        return TranscodeArtifact(
            audio_bytes=processed.wav_bytes,
            actual_sha256=processed.actual_sha256,
            byte_size=len(processed.wav_bytes),
            extension="wav",
            mime_type="audio/wav",
            codec="pcm_s16le",
            duration_ms=processed.duration_ms,
            sample_rate_hz=processed.sample_rate_hz,
            channels=processed.channels,
        )

    return TranscodedSegment(
        master=artifact(),
        playback=artifact(),
        used_wav_fallback=True,
        processing_fingerprint="3" * 64,
    )


async def _worker(
    tmp_path: Path,
    *,
    adapter: ControlledAdapter,
    repository: FakeRepository,
    disk_guard: Callable[[], None] | None = None,
) -> NarrationSegmentWorker:
    return NarrationSegmentWorker(
        scheduler=FakeScheduler(repository.work.lease),  # type: ignore[arg-type]
        repository=repository,
        adapter=adapter,
        storage=_storage(tmp_path),
        transcode=_transcode,
        config=NarrationWorkerConfig(
            actor="test-worker",
            heartbeat_seconds=0.01,
        ),
        disk_guard=disk_guard,
    )


@pytest.mark.asyncio
async def test_worker_success_keeps_external_work_between_claim_and_fenced_publish(
    tmp_path: Path,
) -> None:
    adapter = ControlledAdapter()
    work = await _work(adapter, _lease())
    repository = FakeRepository(work)
    worker = await _worker(tmp_path, adapter=adapter, repository=repository)

    outcome = await worker.run_once()

    assert outcome.status == "succeeded"
    assert outcome.job_id == work.lease.fence.job_id
    assert outcome.render_id == work.render_id
    assert repository.loaded == 1
    assert len(repository.published) == 1
    assert repository.failures == []
    published = repository.published[0]
    assert published.audio.master.actual_sha256 == published.audio.playback.actual_sha256
    assert published.model.model_fingerprint == work.expected_model_fingerprint


@pytest.mark.asyncio
async def test_worker_low_disk_before_synthesis_remains_retryable_and_publishes_nothing(
    tmp_path: Path,
) -> None:
    adapter = ControlledAdapter()
    work = await _work(adapter, _lease())
    repository = FakeRepository(work, failure_state="retry_wait")

    def low_disk() -> None:
        raise NarrationDiskGuardError("DISK_SPACE_INSUFFICIENT")

    worker = await _worker(
        tmp_path,
        adapter=adapter,
        repository=repository,
        disk_guard=low_disk,
    )

    outcome = await worker.run_once()

    assert outcome.status == "retry_wait"
    assert outcome.error_code == "DISK_SPACE_INSUFFICIENT"
    assert repository.failures == [
        ("retryable", "DISK_SPACE_INSUFFICIENT")
    ]
    assert repository.failure_evidence == [None]
    assert repository.published == []
    assert not any(path.is_file() for path in (tmp_path / "media").rglob("*"))


@pytest.mark.asyncio
async def test_worker_rechecks_disk_before_physical_publication(
    tmp_path: Path,
) -> None:
    adapter = ControlledAdapter()
    work = await _work(adapter, _lease())
    repository = FakeRepository(work, failure_state="retry_wait")
    checks = 0
    events: list[str] = []

    def disk_changes_after_synthesis() -> None:
        nonlocal checks
        checks += 1
        events.append(f"guard-{checks}")
        if checks == 2:
            raise NarrationDiskGuardError("DISK_SPACE_INSUFFICIENT")

    worker = await _worker(
        tmp_path,
        adapter=adapter,
        repository=repository,
        disk_guard=disk_changes_after_synthesis,
    )
    production_transcode = worker._transcode

    def transcode_before_publication(processed: ProcessedPcmWav) -> TranscodedSegment:
        events.append("transcode")
        return production_transcode(processed)

    worker._transcode = transcode_before_publication

    outcome = await worker.run_once()

    assert checks == 2
    assert events == ["guard-1", "transcode", "guard-2"]
    assert outcome.status == "retry_wait"
    assert outcome.error_code == "DISK_SPACE_INSUFFICIENT"
    assert repository.failures == [
        ("retryable", "DISK_SPACE_INSUFFICIENT")
    ]
    assert repository.failure_evidence == [None]
    assert repository.published == []
    assert not any(path.is_file() for path in (tmp_path / "media").rglob("*"))


@pytest.mark.asyncio
async def test_worker_honours_cancel_after_segment_boundary_without_publication(
    tmp_path: Path,
) -> None:
    adapter = ControlledAdapter(delay_seconds=0.03)
    work = await _work(adapter, _lease())
    repository = FakeRepository(
        work,
        read_states=["cancel_requested"],
        heartbeat_states=["cancel_requested"],
    )
    worker = await _worker(tmp_path, adapter=adapter, repository=repository)

    outcome = await worker.run_once()

    assert outcome.status == "cancelled"
    assert repository.heartbeats >= 1
    assert repository.cancelled == 1
    assert repository.published == []
    assert repository.failures == []
    assert adapter.cancel_calls == [work.lease.fence.attempt_id]


@pytest.mark.asyncio
async def test_invalid_nano_audio_is_non_retryable_and_never_published(
    tmp_path: Path,
) -> None:
    adapter = ControlledAdapter(silent=True)
    work = await _work(adapter, _lease())
    repository = FakeRepository(work, failure_state="failed")
    worker = await _worker(tmp_path, adapter=adapter, repository=repository)

    outcome = await worker.run_once()

    assert outcome.status == "failed"
    assert outcome.error_code == "NANO_AUDIO_INVALID"
    assert repository.failures == [("non_retryable", "NANO_AUDIO_INVALID")]
    assert repository.failure_evidence == [
        {
            "schema_version": "narration-audio-validation-failure/1",
            "reason_code": "WAV_SILENT",
        }
    ]
    assert repository.published == []


@pytest.mark.parametrize(
    ("error", "expected_reason_code"),
    (
        (
            AudioFormatError("synthesis WAV container is corrupt"),
            "WAV_CONTAINER_CORRUPT",
        ),
        (
            AudioQualityError(
                "synthesis WAV duration is implausible for short Chinese text"
            ),
            "SHORT_CHINESE_DURATION_IMPLAUSIBLE",
        ),
        (
            AudioQualityError("内部检验失败：第一章林晚的绝密正文"),
            "AUDIO_VALIDATION_UNKNOWN",
        ),
    ),
)
def test_audio_failure_evidence_is_bounded_and_never_copies_exception_text(
    error: BaseException,
    expected_reason_code: str,
) -> None:
    evidence = NarrationSegmentWorker._failure_evidence(error)  # noqa: SLF001

    assert evidence == {
        "schema_version": "narration-audio-validation-failure/1",
        "reason_code": expected_reason_code,
    }
    assert "林晚" not in repr(evidence)
    assert "绝密正文" not in repr(evidence)


@pytest.mark.parametrize(
    "error",
    (
        RuntimeError("非音频错误包含林晚的绝密正文"),
        NarrationDiskGuardError("DISK_SPACE_INSUFFICIENT"),
        ContractError("request contract failed"),
    ),
)
def test_non_audio_failure_never_creates_audio_validation_evidence(
    error: BaseException,
) -> None:
    assert NarrationSegmentWorker._failure_evidence(error) is None  # noqa: SLF001


@pytest.mark.parametrize(
    "failure_evidence",
    (
        {},
        {
            "schema_version": "narration-audio-validation-failure/0",
            "reason_code": "WAV_SILENT",
        },
        {
            "schema_version": "narration-audio-validation-failure/1",
            "reason_code": "",
        },
        {
            "schema_version": "narration-audio-validation-failure/1",
            "reason_code": "NOT_A_REAL_AUDIO_REASON",
        },
        {
            "schema_version": "narration-audio-validation-failure/1",
            "reason_code": "WAV_SILENT ",
        },
        {
            "schema_version": "narration-audio-validation-failure/1",
            "reason_code": "林晚的绝密正文",
        },
        {
            "schema_version": "narration-audio-validation-failure/1",
            "reason_code": "WAV_SILENT",
            "detail": "林晚的绝密正文",
        },
        {
            "schema_version": "narration-audio-validation-failure/1",
            "reason_code": "X" * 97,
        },
    ),
)
def test_repository_rejects_noncanonical_failure_evidence_before_transaction(
    failure_evidence: dict[str, object],
) -> None:
    repository = object.__new__(SqlAlchemyNarrationWorkerRepository)

    def transaction_must_not_start(_operation: object) -> object:
        raise AssertionError("invalid evidence must fail before a DB transaction")

    repository._transaction = transaction_must_not_start  # type: ignore[method-assign]

    with pytest.raises(WorkerContractError, match="failure evidence is invalid"):
        repository.fail(
            SimpleNamespace(),  # type: ignore[arg-type]
            classification="non_retryable",
            error_code="NANO_AUDIO_INVALID",
            failure_evidence=failure_evidence,
        )


@pytest.mark.parametrize(
    ("classification", "error_code"),
    (
        ("retryable", "NANO_AUDIO_INVALID"),
        ("security_failure", "NANO_AUDIO_INVALID"),
        ("non_retryable", "RENDER_INPUT_INVALID"),
        ("non_retryable", "AUDIO_PUBLICATION_INVALID"),
    ),
)
def test_repository_rejects_audio_evidence_for_non_audio_failure_before_transaction(
    classification: str,
    error_code: str,
) -> None:
    repository = object.__new__(SqlAlchemyNarrationWorkerRepository)

    def transaction_must_not_start(_operation: object) -> object:
        raise AssertionError("mismatched evidence must fail before a DB transaction")

    repository._transaction = transaction_must_not_start  # type: ignore[method-assign]

    with pytest.raises(WorkerContractError, match="failure evidence is invalid"):
        repository.fail(
            SimpleNamespace(),  # type: ignore[arg-type]
            classification=classification,  # type: ignore[arg-type]
            error_code=error_code,
            failure_evidence={
                "schema_version": "narration-audio-validation-failure/1",
                "reason_code": "WAV_SILENT",
            },
        )


def test_repository_terminalizes_a_load_failure_in_the_same_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = object.__new__(SqlAlchemyNarrationWorkerRepository)
    repository._scope = NarrationRequestScope.fixed_local()  # noqa: SLF001
    lease = _lease()
    job = SimpleNamespace(id=lease.fence.job_id)
    session = SimpleNamespace()
    terminalized: list[tuple[object, str, str]] = []

    repository._job = (  # type: ignore[method-assign]
        lambda observed_session, observed_lease, *, for_update: (
            job
            if observed_session is session
            and observed_lease is lease
            and for_update
            else (_ for _ in ()).throw(AssertionError("unexpected job lookup"))
        )
    )
    repository._terminalize_render_job_in_session = (  # type: ignore[method-assign]
        lambda observed_session, *, job, target_state, error_code, actor: (
            terminalized.append((job, target_state, actor)) or True
        )
    )
    repository._transaction = (  # type: ignore[method-assign]
        lambda operation: operation(session)
    )
    monkeypatch.setattr(
        worker_module,
        "fail_attempt",
        lambda *_args, **_kwargs: FailureResult(
            job_id=lease.fence.job_id,
            state="failed",
            next_retry_at=None,
        ),
    )

    result = repository.fail_claim(
        lease,
        classification="non_retryable",
        error_code="RENDER_INPUT_INVALID",
    )

    assert result.state == "failed"
    assert terminalized == [
        (job, "failed", "narration-worker-load-failure"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("spoken_text", "duration_ms"),
    [
        ("林晚说道：", 3_760),
        ("沈川说道：", 22_080),
    ],
)
async def test_short_chinese_duration_runaway_is_non_retryable_and_never_published(
    tmp_path: Path,
    spoken_text: str,
    duration_ms: int,
) -> None:
    adapter = ControlledAdapter(duration_ms=duration_ms)
    work = replace(await _work(adapter, _lease()), text=spoken_text)
    repository = FakeRepository(work, failure_state="failed")
    worker = await _worker(tmp_path, adapter=adapter, repository=repository)
    transcode_calls = 0

    def should_not_transcode(_processed: ProcessedPcmWav) -> TranscodedSegment:
        nonlocal transcode_calls
        transcode_calls += 1
        raise AssertionError("duration runaway must fail before transcoding")

    worker._transcode = should_not_transcode
    outcome = await worker.run_once()

    assert outcome.status == "failed"
    assert outcome.error_code == "NANO_AUDIO_INVALID"
    assert repository.failures == [("non_retryable", "NANO_AUDIO_INVALID")]
    assert repository.failure_evidence == [
        {
            "schema_version": "narration-audio-validation-failure/1",
            "reason_code": "SHORT_CHINESE_DURATION_IMPLAUSIBLE",
        }
    ]
    assert repository.published == []
    assert transcode_calls == 0
    assert not any(path.is_file() for path in (tmp_path / "media").rglob("*"))


@pytest.mark.asyncio
async def test_retryable_failure_surfaces_retry_wait_without_reusing_result(
    tmp_path: Path,
) -> None:
    adapter = ControlledAdapter()
    work = await _work(adapter, _lease())
    repository = FakeRepository(work, failure_state="retry_wait")
    worker = await _worker(tmp_path, adapter=adapter, repository=repository)

    def unavailable(_processed: ProcessedPcmWav) -> TranscodedSegment:
        from backend.narration.transcoding import TranscodingUnavailable

        raise TranscodingUnavailable("fixed FFmpeg is unavailable")

    worker._transcode = unavailable  # noqa: SLF001 - focused worker seam
    outcome = await worker.run_once()

    assert outcome.status == "retry_wait"
    assert repository.failures == [("retryable", "TRANSCODER_UNAVAILABLE")]
    assert repository.published == []


@pytest.mark.asyncio
async def test_postprocess_fingerprint_mismatch_fails_closed_before_asset_publication(
    tmp_path: Path,
) -> None:
    adapter = ControlledAdapter()
    work = await _work(adapter, _lease())
    repository = FakeRepository(work, failure_state="failed")
    worker = await _worker(tmp_path, adapter=adapter, repository=repository)

    def mismatched_transcode(processed: ProcessedPcmWav) -> TranscodedSegment:
        return replace(
            _transcode(processed),
            processing_fingerprint="4" * 64,
        )

    worker._transcode = mismatched_transcode  # noqa: SLF001 - focused worker seam
    outcome = await worker.run_once()

    assert outcome.status == "failed"
    assert outcome.error_code == "WORKER_SECURITY_FAILURE"
    assert repository.failures == [
        ("security_failure", "WORKER_SECURITY_FAILURE")
    ]
    assert repository.failure_evidence == [None]
    assert repository.published == []
    assert not any(path.is_file() for path in (tmp_path / "media").rglob("*"))


@pytest.mark.asyncio
async def test_late_result_with_stale_dual_fence_is_discarded_not_failed(
    tmp_path: Path,
) -> None:
    adapter = ControlledAdapter()
    work = await _work(adapter, _lease())
    repository = FakeRepository(
        work,
        publish_error=JobFenceError("resource generation changed"),
    )
    worker = await _worker(tmp_path, adapter=adapter, repository=repository)

    outcome = await worker.run_once()

    assert outcome.status == "stale"
    assert outcome.error_code == "STALE_WORKER_FENCE"
    assert repository.published == []
    assert repository.failures == []


@pytest.mark.asyncio
async def test_idle_worker_performs_no_external_or_repository_work(tmp_path: Path) -> None:
    adapter = ControlledAdapter()
    work = await _work(adapter, _lease())
    repository = FakeRepository(work)
    worker = NarrationSegmentWorker(
        scheduler=FakeScheduler(None),  # type: ignore[arg-type]
        repository=repository,
        adapter=adapter,
        storage=_storage(tmp_path),
        transcode=_transcode,
        config=NarrationWorkerConfig(actor="test-worker"),
    )

    outcome = await worker.run_once()

    assert outcome.status == "idle"
    assert repository.loaded == 0
    assert repository.published == []


@pytest.mark.asyncio
async def test_work_item_load_failure_is_fenced_instead_of_leaking_running_claim(
    tmp_path: Path,
) -> None:
    adapter = ControlledAdapter()
    work = await _work(adapter, _lease())
    repository = FakeRepository(
        work,
        load_error=InvalidNarrationState("render provenance drifted"),
        failure_state="failed",
    )
    worker = await _worker(tmp_path, adapter=adapter, repository=repository)

    outcome = await worker.run_once()

    assert outcome.status == "failed"
    assert outcome.error_code == "RENDER_INPUT_INVALID"
    assert repository.claim_failures == [
        ("non_retryable", "RENDER_INPUT_INVALID")
    ]
    assert repository.published == []


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def __enter__(self) -> "FakeSession":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def test_scheduler_commits_maintenance_separately_and_claims_only_moss_nano(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.narration import scheduler as scheduler_module

    sessions: list[FakeSession] = []
    claimed = _lease()
    observed: dict[str, object] = {}

    def factory() -> FakeSession:
        session = FakeSession()
        sessions.append(session)
        return session

    monkeypatch.setattr(
        scheduler_module,
        "promote_due_retries",
        lambda _session, **_kwargs: (uuid4(),),
    )
    monkeypatch.setattr(
        scheduler_module,
        "reconcile_expired_attempts",
        lambda _session, **_kwargs: (),
    )

    def claim(_session: object, **kwargs: object) -> JobLease:
        observed.update(kwargs)
        return claimed

    monkeypatch.setattr(scheduler_module, "claim_next_job", claim)
    scheduler = NarrationJobScheduler(
        factory,  # type: ignore[arg-type]
        config=SchedulerConfig(lease_owner="test-worker"),
    )

    maintenance = scheduler.maintain_once()
    lease = scheduler.claim_next_segment()

    assert len(maintenance.promoted_job_ids) == 1
    assert maintenance.reconciled_attempts == ()
    assert lease == claimed
    assert observed["resource_classes"] == ("moss-nano",)
    assert observed["job_kinds"] == ("narration.segment_render",)
    assert observed["novel_ids"] is None
    assert observed["document_ids"] is None
    assert len(sessions) == 3
    assert [session.commits for session in sessions] == [1, 1, 1]
    assert [session.rollbacks for session in sessions] == [0, 0, 0]


def test_scheduler_can_isolate_voice_preview_claims() -> None:
    novel_id = uuid4()
    document_id = uuid4()
    config = SchedulerConfig(
        lease_owner="voice-preview-worker",
        job_kinds=("narration.voice_preview",),
        novel_ids=(novel_id,),
        document_ids=(document_id,),
    )

    config.validate()
    assert config.job_kinds == ("narration.voice_preview",)
    assert config.novel_ids == (novel_id,)
    assert config.document_ids == (document_id,)


def test_scheduler_applies_same_validation_scope_to_all_mutating_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.narration import scheduler as scheduler_module

    novel_id = uuid4()
    document_id = uuid4()
    observed: dict[str, dict[str, object]] = {}

    def capture(name: str, result: object):
        def operation(_session: object, **kwargs: object) -> object:
            observed[name] = kwargs
            return result

        return operation

    monkeypatch.setattr(
        scheduler_module,
        "promote_due_retries",
        capture("promote", ()),
    )
    monkeypatch.setattr(
        scheduler_module,
        "reconcile_expired_attempts",
        capture("reconcile", ()),
    )
    monkeypatch.setattr(
        scheduler_module,
        "claim_next_job",
        capture("claim", None),
    )
    scheduler = NarrationJobScheduler(
        FakeSession,  # type: ignore[arg-type]
        config=SchedulerConfig(
            lease_owner="validation-worker",
            novel_ids=(novel_id,),
            document_ids=(document_id,),
        ),
    )

    scheduler.maintain_once()
    assert scheduler.claim_next_job() is None

    for name in ("promote", "reconcile", "claim"):
        assert observed[name]["novel_ids"] == (novel_id,)
        assert observed[name]["document_ids"] == (document_id,)
        assert observed[name]["resource_classes"] == ("moss-nano",)
        assert observed[name]["job_kinds"] == ("narration.segment_render",)


def test_expired_validation_scheduler_performs_no_database_mutation() -> None:
    def forbidden_factory() -> FakeSession:
        raise AssertionError("expired validation scheduler opened the database")

    scheduler = NarrationJobScheduler(
        forbidden_factory,
        config=SchedulerConfig(
            lease_owner="expired-validation-worker",
            novel_ids=(uuid4(),),
            not_after=datetime.now(UTC) - timedelta(seconds=1),
        ),
    )

    assert scheduler.maintain_once() == SchedulerMaintenance(
        promoted_job_ids=(),
        reconciled_attempts=(),
    )
    assert scheduler.claim_next_job() is None
    assert scheduler.claim_next_typed_job() is None


def test_scheduler_low_disk_claim_guard_opens_no_database_transaction() -> None:
    def forbidden_factory() -> FakeSession:
        raise AssertionError("low-disk scheduler opened the database")

    scheduler = NarrationJobScheduler(
        forbidden_factory,
        config=SchedulerConfig(lease_owner="disk-guarded-worker"),
        claim_guard=lambda: False,
    )

    assert scheduler.claim_next_job() is None
    assert scheduler.claim_next_typed_job() is None


def test_scheduler_claim_guard_failure_is_fail_closed() -> None:
    def forbidden_factory() -> FakeSession:
        raise AssertionError("failed disk guard opened the database")

    def failed_guard() -> bool:
        raise OSError("private storage path must not escape")

    scheduler = NarrationJobScheduler(
        forbidden_factory,
        config=SchedulerConfig(lease_owner="failed-disk-guard-worker"),
        claim_guard=failed_guard,
    )

    assert scheduler.claim_next_job() is None
    assert scheduler.claim_next_typed_job() is None


def test_scheduler_job_kind_gate_pauses_only_segment_claims_and_not_maintenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.narration import scheduler as scheduler_module

    claimed = _lease()
    claim_filters: list[tuple[str, ...]] = []
    settled: list[str | None] = []
    gate_calls = 0

    class KindSession(FakeSession):
        def scalar(self, _statement: object) -> str:
            return "narration.segment_render"

    class Reservation:
        def __init__(self, allowed: tuple[str, ...]) -> None:
            self.allowed_job_kinds = allowed

        def settle(self, claimed_job_kind: str | None) -> None:
            settled.append(claimed_job_kind)

    def gate(configured: tuple[str, ...]) -> Reservation:
        nonlocal gate_calls
        gate_calls += 1
        assert configured == (
            "narration.segment_render",
            "narration.voice_preview",
        )
        return Reservation(
            configured if gate_calls == 1 else ("narration.voice_preview",)
        )

    monkeypatch.setattr(
        scheduler_module,
        "promote_due_retries",
        lambda _session, **kwargs: claim_filters.append(kwargs["job_kinds"]) or (),
    )
    monkeypatch.setattr(
        scheduler_module,
        "reconcile_expired_attempts",
        lambda _session, **kwargs: claim_filters.append(kwargs["job_kinds"]) or (),
    )

    def claim(_session: object, **kwargs: object) -> JobLease:
        claim_filters.append(kwargs["job_kinds"])  # type: ignore[arg-type]
        return claimed

    monkeypatch.setattr(scheduler_module, "claim_next_job", claim)
    scheduler = NarrationJobScheduler(
        KindSession,  # type: ignore[arg-type]
        config=SchedulerConfig(
            lease_owner="validation-kind-gate",
            job_kinds=("narration.segment_render", "narration.voice_preview"),
        ),
        job_kind_claim_gate=gate,
    )

    scheduler.maintain_once()
    first = scheduler.claim_next_typed_job()
    second = scheduler.claim_next_typed_job()

    assert first is not None and first.job_kind == "narration.segment_render"
    assert second is not None and second.job_kind == "narration.voice_preview"
    assert claim_filters == [
        ("narration.segment_render", "narration.voice_preview"),
        ("narration.segment_render", "narration.voice_preview"),
        ("narration.segment_render", "narration.voice_preview"),
        ("narration.voice_preview",),
    ]
    assert settled == ["narration.segment_render", "narration.voice_preview"]


def test_scheduler_empty_or_failed_job_kind_gate_opens_no_database_transaction() -> None:
    def forbidden_factory() -> FakeSession:
        raise AssertionError("paused validation gate opened the database")

    class EmptyReservation:
        allowed_job_kinds: tuple[str, ...] = ()

        def settle(self, _claimed_job_kind: str | None) -> None:
            return None

    paused = NarrationJobScheduler(
        forbidden_factory,
        config=SchedulerConfig(lease_owner="paused-validation-kind-gate"),
        job_kind_claim_gate=lambda _kinds: EmptyReservation(),
    )
    failed = NarrationJobScheduler(
        forbidden_factory,
        config=SchedulerConfig(lease_owner="failed-validation-kind-gate"),
        job_kind_claim_gate=lambda _kinds: (_ for _ in ()).throw(OSError("secret")),
    )

    assert paused.claim_next_typed_job() is None
    assert failed.claim_next_typed_job() is None


def test_scheduler_terminalizes_expired_voice_preview_in_the_reconcile_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.narration import scheduler as scheduler_module

    job_id = uuid4()
    attempt_id = uuid4()
    sessions: list[FakeSession] = []
    terminalizer_observations: list[tuple[object, int]] = []

    class Rows:
        def all(self) -> list[tuple[object, str]]:
            return [(job_id, "narration.voice_preview")]

    class TerminalSession(FakeSession):
        def execute(self, _statement: object) -> Rows:
            return Rows()

    def factory() -> TerminalSession:
        session = TerminalSession()
        sessions.append(session)
        return session

    monkeypatch.setattr(
        scheduler_module,
        "promote_due_retries",
        lambda _session, **_kwargs: (),
    )
    monkeypatch.setattr(
        scheduler_module,
        "reconcile_expired_attempts",
        lambda _session, **_kwargs: (
            scheduler_module.ReconciledAttempt(
                job_id=job_id,
                attempt_id=attempt_id,
                resulting_state="dead_letter",
            ),
        ),
    )

    def terminalize(session: FakeSession, *, job_id: object) -> bool:
        terminalizer_observations.append((job_id, session.commits))
        return True

    scheduler = NarrationJobScheduler(
        factory,  # type: ignore[arg-type]
        config=SchedulerConfig(lease_owner="shared-worker"),
        terminalizers={"narration.voice_preview": terminalize},
    )

    maintenance = scheduler.maintain_once()

    assert maintenance.reconciled_attempts[0].resulting_state == "dead_letter"
    assert terminalizer_observations == [(job_id, 0)]
    assert [session.commits for session in sessions] == [1, 1]


def test_expired_segment_terminalizer_closes_render_and_appends_failed_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = MemoryNarrationStore()
    (
        _novel,
        _document,
        _revision,
        request,
        edition,
        _segments,
        renders,
        _voice,
        _rights,
    ) = _edition_with_ready_renders(store)
    edition_segments = store.find_all(
        NarrationEditionSegment,
        edition_id=edition.id,
        order_by=("ordinal",),
    )
    target_render = renders[0]
    target_segment = edition_segments[0]
    target_job = store.get(BackgroundJob, target_render.source_job_id)
    assert target_job is not None
    target_job.state = "dead_letter"
    target_job.error_code = "LEASE_EXPIRED"
    target_render.state = "rendering"
    target_segment.render_state = "rendering"
    renders[1].state = "failed"
    edition_segments[1].render_state = "failed"
    edition_segments[1].failure_code = "SECOND_SEGMENT_FAILED"
    edition.state = "rendering"
    request.state = "rendering"

    class TerminalSession:
        def scalar(self, _statement: object) -> object:
            return target_job

        def get(self, model: type[object], row_id: object) -> object | None:
            return store.get(model, row_id)

        def flush(self) -> None:
            return None

    session = TerminalSession()
    repository = object.__new__(SqlAlchemyNarrationWorkerRepository)
    repository._scope = NarrationRequestScope.fixed_local()
    monkeypatch.setattr(
        worker_module,
        "SqlAlchemyNarrationStore",
        lambda _session: store,
    )
    monkeypatch.setattr(
        repository,
        "_work_rows",
        lambda _session, *, job, for_update, validate_current_authority: SimpleNamespace(
            render=target_render,
            fanout_segments=(target_segment,),
            fanout_editions=(edition,),
        ),
    )

    assert repository.terminalize_job_in_session(  # type: ignore[arg-type]
        session, job_id=target_job.id
    ) is True
    assert target_render.state == "failed"
    assert target_segment.render_state == "failed"
    assert target_segment.failure_code == "LEASE_EXPIRED"
    assert edition.state == "unavailable"
    assert request.state == "failed"
    manifests = store.find_all(
        NarrationManifest,
        edition_id=edition.id,
        order_by=("manifest_revision",),
    )
    assert len(manifests) == 1
    assert manifests[0].manifest_revision == 1
    assert manifests[0].canonical_json["status"] == "failed"
    assert manifests[0].canonical_json["segments"][0]["failure"]["code"] == (
        "LEASE_EXPIRED"
    )
    assert repository.terminalize_job_in_session(  # type: ignore[arg-type]
        session, job_id=target_job.id
    ) is False
    assert len(store.find_all(NarrationManifest, edition_id=edition.id)) == 1


def test_expired_segment_terminalizer_waits_before_first_playable_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = MemoryNarrationStore()
    (
        _novel,
        _document,
        _revision,
        request,
        edition,
        _segments,
        renders,
        _voice,
        _rights,
    ) = _edition_with_ready_renders(store)
    edition_segments = store.find_all(
        NarrationEditionSegment,
        edition_id=edition.id,
        order_by=("ordinal",),
    )
    target_render = renders[0]
    target_segment = edition_segments[0]
    target_job = store.get(BackgroundJob, target_render.source_job_id)
    assert target_job is not None
    target_job.state = "cancelled"
    target_render.state = "rendering"
    target_segment.render_state = "rendering"
    renders[1].state = "pending"
    edition_segments[1].render_state = "queued"
    edition.state = "rendering"
    request.state = "rendering"

    class TerminalSession:
        def scalar(self, _statement: object) -> object:
            return target_job

        def get(self, model: type[object], row_id: object) -> object | None:
            return store.get(model, row_id)

        def flush(self) -> None:
            return None

    repository = object.__new__(SqlAlchemyNarrationWorkerRepository)
    repository._scope = NarrationRequestScope.fixed_local()
    monkeypatch.setattr(
        worker_module,
        "SqlAlchemyNarrationStore",
        lambda _session: store,
    )
    monkeypatch.setattr(
        repository,
        "_work_rows",
        lambda _session, *, job, for_update, validate_current_authority: SimpleNamespace(
            render=target_render,
            fanout_segments=(target_segment,),
            fanout_editions=(edition,),
        ),
    )

    assert repository.terminalize_job_in_session(  # type: ignore[arg-type]
        TerminalSession(), job_id=target_job.id
    ) is True
    assert target_render.state == "cancelled"
    assert target_segment.render_state == "cancelled"
    assert edition_segments[1].render_state == "queued"
    assert edition.state == "rendering"
    assert request.state == "rendering"
    assert store.find_all(NarrationManifest, edition_id=edition.id) == []


@pytest.mark.parametrize(
    ("resulting_state", "expected_terminalizations"),
    [("retry_wait", 0), ("dead_letter", 1)],
)
def test_regular_failure_appends_manifest_only_when_attempt_becomes_terminal(
    monkeypatch: pytest.MonkeyPatch,
    resulting_state: str,
    expected_terminalizations: int,
) -> None:
    lease = _lease()
    work = SimpleNamespace(lease=lease)
    job = SimpleNamespace(id=lease.fence.job_id)
    terminalizations: list[tuple[str, str]] = []
    repository = object.__new__(SqlAlchemyNarrationWorkerRepository)
    repository._scope = NarrationRequestScope.fixed_local()
    repository._transaction = lambda operation: operation(SimpleNamespace())  # type: ignore[method-assign]
    repository._append_terminal_model_run = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
    repository._job = lambda *_args, **_kwargs: job  # type: ignore[method-assign]
    repository._terminalize_render_job_in_session = (  # type: ignore[method-assign]
        lambda _session, *, job, target_state, error_code, actor, failure_evidence: (
            terminalizations.append((target_state, error_code)) or True
        )
    )
    monkeypatch.setattr(
        worker_module,
        "fail_attempt",
        lambda *_args, **_kwargs: FailureResult(
            job_id=lease.fence.job_id,
            state=resulting_state,  # type: ignore[arg-type]
            next_retry_at=(NOW + timedelta(seconds=5) if resulting_state == "retry_wait" else None),
        ),
    )

    result = repository.fail(
        work,  # type: ignore[arg-type]
        classification="retryable",
        error_code="LEASE_EXPIRED",
    )

    assert result.state == resulting_state
    assert len(terminalizations) == expected_terminalizations
    if expected_terminalizations:
        assert terminalizations == [("failed", "LEASE_EXPIRED")]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("job_kinds", ()),
        ("job_kinds", ("",)),
        (
            "job_kinds",
            ("narration.voice_preview", "narration.voice_preview"),
        ),
        ("novel_ids", ()),
        ("novel_ids", (uuid4(), uuid4().hex)),
        ("document_ids", ()),
        ("document_ids", (uuid4(), uuid4().hex)),
        ("not_after", (datetime(2026, 8, 27, 12, 0),)),
    ],
)
def test_scheduler_rejects_ambiguous_job_kind_filters(
    field: str,
    value: tuple[object, ...],
) -> None:
    kwargs = {field: value[0] if field == "not_after" else value}
    with pytest.raises(ValueError, match=field):
        SchedulerConfig(lease_owner="worker", **kwargs).validate()  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_worker_loop_runs_maintenance_and_stops_without_an_extra_process(
    tmp_path: Path,
) -> None:
    adapter = ControlledAdapter()
    work = await _work(adapter, _lease())
    repository = FakeRepository(work)
    scheduler = FakeScheduler(None)
    worker = NarrationSegmentWorker(
        scheduler=scheduler,  # type: ignore[arg-type]
        repository=repository,
        adapter=adapter,
        storage=_storage(tmp_path),
        transcode=_transcode,
        config=NarrationWorkerConfig(actor="test-worker"),
    )
    stop = asyncio.Event()

    async def request_stop() -> None:
        await asyncio.sleep(0.03)
        stop.set()

    await asyncio.gather(
        worker.run_until_stopped(
            stop,
            idle_poll_seconds=0.01,
            maintenance_interval_seconds=0.1,
        ),
        request_stop(),
    )

    assert scheduler.maintenance_count == 1
    assert scheduler.claim_count >= 1
    assert repository.loaded == 0
