from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import hashlib
from io import BytesIO
import math
from types import SimpleNamespace
from uuid import UUID, uuid4
import wave

import pytest

from backend.models import (
    MediaAsset,
    VoiceActionReceipt,
    VoicePreview,
    VoiceProfile,
    VoiceProfileVersion,
    VoiceRightsEvent,
    VoiceRightsRecord,
)
from backend.narration.official_presets import (
    official_preset_canonical_profile_id,
    official_preset_canonical_version_id,
    official_preset_direct_version_fingerprint,
)
from backend.narration.adapters import (
    FakeMossNanoTTSAdapter,
    MOSS_NANO_SIDECAR_CONTRACT_CAPABILITIES,
    MossNanoTTSAdapter,
)
from backend.narration.contracts import (
    AdapterHealth,
    AdapterHealthStatus,
    CancelDisposition,
    ModelFingerprint,
    NarrationRequestScope,
    SynthesisRequest,
    SynthesisResult,
)
from backend.narration.fingerprints import (
    capabilities_fingerprint,
    model_fingerprint_sha256,
)
from backend.narration.digest_keyring import (
    DigestKeyring,
    HmacDigestKey,
    private_text_digest,
)
from backend.narration.jobs import FailureResult, JobFence, JobLease
from backend.narration.resource_locks import ResourceFence
from backend.narration.services import IdempotencyConflict, VoiceRightsUnavailable
from backend.narration.storage import PublishedFile, TargetCollision
import backend.narration.voice_product as product
from backend.narration.voice_product import (
    SqlAlchemyVoicePreviewRepository,
    VoicePreviewNotFound,
    VoicePreviewPolicy,
    VoicePreviewProcessor,
    VoicePreviewWorkItem,
    VoiceReferenceMedia,
    resolve_voice_preview_media,
)


NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
SCOPE = NarrationRequestScope.fixed_local()


def _model() -> ModelFingerprint:
    return ModelFingerprint(
        adapter_contract_version="moss-nano-tts-adapter/1",
        model_name="real-test-shaped-nano",
        model_revision="revision-1",
        artifact_tree_sha256="a" * 64,
        runtime_name="onnxruntime",
        runtime_version="1",
        execution_backend="cpu",
        protocol_version="sidecar/1",
        deployment_topology="single-sidecar",
        parameters={},
    )


def _wav(duration_ms: int = 200) -> bytes:
    sample_rate = 48_000
    output = BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(2)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        frames = bytearray()
        for index in range(round(sample_rate * duration_ms / 1000)):
            value = round(3_000 * math.sin(2 * math.pi * 220 * index / sample_rate))
            encoded = value.to_bytes(2, "little", signed=True)
            frames.extend(encoded)
            frames.extend(encoded)
        target.writeframes(bytes(frames))
    return output.getvalue()


class _Adapter(MossNanoTTSAdapter):
    def __init__(self, *, fingerprint: ModelFingerprint | None = None) -> None:
        self.fingerprint = fingerprint or _model()
        self.requests: list[SynthesisRequest] = []

    @property
    def capabilities(self):
        return MOSS_NANO_SIDECAR_CONTRACT_CAPABILITIES

    async def health(self) -> AdapterHealth:
        return AdapterHealth(
            status=AdapterHealthStatus.HEALTHY,
            capabilities_sha256=capabilities_fingerprint(self.capabilities),
            model_fingerprint_sha256=model_fingerprint_sha256(self.fingerprint),
        )

    async def model_fingerprint(self) -> ModelFingerprint:
        return self.fingerprint

    async def warmup(self) -> AdapterHealth:
        return await self.health()

    async def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        self.requests.append(request)
        audio = _wav()
        return SynthesisResult(
            request_id=request.request_id,
            audio_bytes=audio,
            actual_output_sha256=hashlib.sha256(audio).hexdigest(),
            sample_rate_hz=48_000,
            channels=2,
            sample_width_bytes=2,
            model_fingerprint=self.fingerprint,
            worker_generation=1,
        )

    async def cancel(self, request_id: UUID) -> CancelDisposition:
        del request_id
        return CancelDisposition.REQUESTED


class _Storage:
    def __init__(self, reference: bytes) -> None:
        self.reference = reference
        self.published: list[PublishedFile] = []

    def verify_media_identity(self, relative_path: str, **_: object):
        assert relative_path == "reference.wav"
        return SimpleNamespace(device=1, inode=2, byte_size=len(self.reference))

    def stream_media(self, relative_path: str, **_: object):
        assert relative_path == "reference.wav"
        yield self.reference

    def publish_media(
        self,
        chunks,
        *,
        asset_id: UUID,
        expected_sha256: str,
        expected_size: int,
        extension: str,
        max_bytes: int,
    ) -> PublishedFile:
        payload = b"".join(chunks)
        assert len(payload) == expected_size <= max_bytes
        assert hashlib.sha256(payload).hexdigest() == expected_sha256
        published = PublishedFile(
            asset_id=asset_id,
            relative_path=(
                f"assets/{asset_id.hex[:2]}/{asset_id.hex}/"
                f"{expected_sha256}.{extension}"
            ),
            actual_sha256=expected_sha256,
            byte_size=expected_size,
            strong_etag=f'"{expected_sha256}"',
            device=3,
            inode=4,
        )
        self.published.append(published)
        return published


class _Repository:
    def __init__(self, work: VoicePreviewWorkItem) -> None:
        self.work = work
        self.state = "running"
        self.private_text: str | None = work.text
        self.prepared = None
        self.failure: tuple[str, str] | None = None

    def load_and_mark_running(self, lease: JobLease) -> VoicePreviewWorkItem:
        assert lease == self.work.lease
        return self.work

    def read_job_state(self, lease: JobLease) -> str:
        assert lease == self.work.lease
        return self.state

    def heartbeat_and_read_state(self, lease: JobLease) -> str:
        return self.read_job_state(lease)

    def publish(self, work: VoicePreviewWorkItem, prepared) -> None:
        assert work == self.work
        self.prepared = prepared
        self.private_text = None
        self.state = "succeeded"

    def fail(self, work: VoicePreviewWorkItem, *, classification: str, error_code: str):
        assert work == self.work
        self.failure = (classification, error_code)
        self.private_text = None
        self.state = "failed"
        return FailureResult(job_id=work.lease.fence.job_id, state="failed", next_retry_at=None)

    def fail_claim(self, lease: JobLease, *, classification: str, error_code: str):
        self.failure = (classification, error_code)
        self.private_text = None
        return FailureResult(job_id=lease.fence.job_id, state="failed", next_retry_at=None)

    def acknowledge_cancel(self, work: VoicePreviewWorkItem) -> None:
        assert work == self.work
        self.private_text = None
        self.state = "cancelled"


def _lease() -> JobLease:
    job_id, attempt_id = uuid4(), uuid4()
    return JobLease(
        fence=JobFence(
            job_id=job_id,
            attempt_id=attempt_id,
            lease_token=uuid4(),
            lease_generation=1,
        ),
        attempt_number=1,
        retry_kind="initial",
        lease_owner="worker-1",
        lease_until=NOW + timedelta(minutes=2),
        executor_epoch_id=uuid4(),
        resource_fence=ResourceFence(
            resource_key="moss-nano:inference",
            lease_owner="worker-1",
            lease_token=uuid4(),
            lease_generation=1,
        ),
    )


def _work(reference: bytes, model_digest: str) -> VoicePreviewWorkItem:
    lease = _lease()
    return VoicePreviewWorkItem(
        lease=lease,
        preview_id=uuid4(),
        profile_id=uuid4(),
        version_id=uuid4(),
        rights_record_id=uuid4(),
        novel_id=None,
        text="这是一段真实 Nano 试听文本。",
        voice="uploaded-reference",
        seed=0,
        sample_mode="fixed",
        max_new_frames=375,
        expected_model_fingerprint=model_digest,
        reference_fingerprint="b" * 64,
        parameters_fingerprint="c" * 64,
        input_digest_key_id="key-1",
        input_digest="d" * 64,
        reference=VoiceReferenceMedia(
            relative_path="reference.wav",
            actual_sha256=hashlib.sha256(reference).hexdigest(),
            byte_size=len(reference),
            content_type="audio/wav",
        ),
    )


def test_preview_processor_runs_real_adapter_contract_and_clears_private_text() -> None:
    reference = b"private-reference-bytes"
    adapter = _Adapter()
    expected = model_fingerprint_sha256(adapter.fingerprint)
    work = _work(reference, expected)
    repository = _Repository(work)
    storage = _Storage(reference)
    policy = VoicePreviewPolicy(expected_model_fingerprint=expected)
    processor = VoicePreviewProcessor(
        repository=repository,
        adapter=adapter,
        storage=storage,  # type: ignore[arg-type]
        policy=policy,
    )

    outcome = asyncio.run(processor.process(work.lease))

    assert outcome.status == "succeeded"
    assert repository.private_text is None
    assert repository.prepared is not None
    assert repository.prepared.model_fingerprint == expected
    assert repository.prepared.published == storage.published[0]
    assert adapter.requests[0].reference_audio is not None
    assert adapter.requests[0].reference_audio.audio_bytes == reference


def test_default_preview_policy_uses_pinned_official_runtime_defaults() -> None:
    policy = VoicePreviewPolicy(expected_model_fingerprint="b" * 64)

    assert (policy.seed, policy.sample_mode, policy.max_new_frames) == (
        1234,
        "fixed",
        375,
    )


def test_official_preset_preview_uses_exact_id_without_reference_media() -> None:
    adapter = _Adapter()
    expected = model_fingerprint_sha256(adapter.fingerprint)
    work = replace(
        _work(b"unused-reference", expected),
        voice="onnx.Trump",
        reference=None,
    )
    repository = _Repository(work)
    processor = VoicePreviewProcessor(
        repository=repository,
        adapter=adapter,
        storage=_Storage(b"must-not-be-read"),  # type: ignore[arg-type]
        policy=VoicePreviewPolicy(expected_model_fingerprint=expected),
    )

    outcome = asyncio.run(processor.process(work.lease))

    assert outcome.status == "succeeded"
    assert adapter.requests[0].voice == "onnx.Trump"
    assert adapter.requests[0].reference_audio is None


def test_preview_processor_fails_security_closed_on_model_identity_drift() -> None:
    reference = b"private-reference-bytes"
    adapter = _Adapter()
    work = _work(reference, "f" * 64)
    repository = _Repository(work)
    processor = VoicePreviewProcessor(
        repository=repository,
        adapter=adapter,
        storage=_Storage(reference),  # type: ignore[arg-type]
        policy=VoicePreviewPolicy(expected_model_fingerprint="f" * 64),
    )

    outcome = asyncio.run(processor.process(work.lease))

    assert outcome.status == "failed"
    assert repository.failure == (
        "security_failure",
        "VOICE_PREVIEW_SECURITY_FAILURE",
    )
    assert repository.private_text is None


def test_preview_processor_rejects_test_double_adapter() -> None:
    with pytest.raises(TypeError, match="real reference-capable Nano"):
        VoicePreviewProcessor(
            repository=SimpleNamespace(),  # type: ignore[arg-type]
            adapter=FakeMossNanoTTSAdapter(),
            storage=SimpleNamespace(),  # type: ignore[arg-type]
            policy=VoicePreviewPolicy(expected_model_fingerprint="f" * 64),
        )


class _ReplaySession:
    def __init__(
        self,
        receipt: VoiceActionReceipt,
        preview: VoicePreview,
    ) -> None:
        self._rows = iter((receipt, preview))
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    def get_bind(self):
        return self.bind

    def scalar(self, _statement):
        return next(self._rows)


def test_preview_replay_uses_historical_verify_only_digest_key() -> None:
    old_secret = b"o" * 32
    old_active = HmacDigestKey("old-key", old_secret, status="active")
    text = "密钥轮换后仍需安全重放。"
    digest = private_text_digest(
        old_active,
        purpose=product.VOICE_PREVIEW_TEXT_PURPOSE,
        text=text,
    )
    keyring = DigestKeyring(
        active_key_id="new-key",
        keys={
            "old-key": HmacDigestKey(
                "old-key", old_secret, status="verify_only"
            ),
            "new-key": HmacDigestKey("new-key", b"n" * 32, status="active"),
        },
    )
    profile_id, version_id, preview_id = uuid4(), uuid4(), uuid4()
    request_fingerprint = "a" * 64
    receipt = VoiceActionReceipt(
        id=uuid4(),
        owner_id=SCOPE.owner_id,
        workspace_id=SCOPE.workspace_id,
        operation=product.VOICE_PREVIEW_OPERATION,
        idempotency_key="preview-key-rotate",
        request_hash=request_fingerprint,
        resource_id=preview_id,
        state="completed",
        reserved_at=NOW,
        completed_at=NOW,
    )
    preview = VoicePreview(
        id=preview_id,
        owner_id=SCOPE.owner_id,
        workspace_id=SCOPE.workspace_id,
        novel_id=None,
        profile_id=profile_id,
        version_id=version_id,
        rights_record_id=uuid4(),
        job_id=uuid4(),
        reference_asset_id=uuid4(),
        result_asset_id=None,
        preview_text=None,
        preview_text_digest_key_id="old-key",
        preview_text_digest=digest,
        model_fingerprint="b" * 64,
        reference_fingerprint="c" * 64,
        parameters_fingerprint="d" * 64,
        request_fingerprint=request_fingerprint,
        status="failed",
        started_at=NOW,
        completed_at=NOW,
        expires_at=None,
        failure_code="FAILED",
        created_at=NOW,
        updated_at=NOW,
    )
    service = product.VoiceProductService(
        lambda: None,  # type: ignore[arg-type,return-value]
        storage=SimpleNamespace(
            publish_media=lambda *_args, **_kwargs: None,
            verify_existing_media=lambda *_args, **_kwargs: None,
        ),  # type: ignore[arg-type]
        normalize_reference=lambda _parsed: None,  # type: ignore[arg-type,return-value]
        digest_keyring=keyring,
        preview_policy=VoicePreviewPolicy(expected_model_fingerprint="b" * 64),
    )

    resource = service._create_preview_in_session(
        _ReplaySession(receipt, preview),  # type: ignore[arg-type]
        profile_id=profile_id,
        request=product.wire.CreateVoicePreviewRequest(
            version_id=version_id,
            preview_text=text,
        ),
        idempotency_key="preview-key-rotate",
        text=text,
        text_digest="e" * 64,
        text_digest_key_id="new-key",
    )

    assert resource.preview_id == preview_id
    assert resource.status is product.wire.VoicePreviewStatus.FAILED


class _ReceiptSession:
    def __init__(self) -> None:
        self.row: VoiceActionReceipt | None = None
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    def get_bind(self):
        return self.bind

    def scalar(self, _statement):
        return self.row

    def add(self, row: VoiceActionReceipt) -> None:
        self.row = row

    def flush(self) -> None:
        pass


def test_receipt_completion_never_precedes_database_reservation_clock() -> None:
    reserved_at = NOW + timedelta(milliseconds=5)
    receipt = VoiceActionReceipt(
        id=uuid4(),
        owner_id=SCOPE.owner_id,
        workspace_id=SCOPE.workspace_id,
        operation=product.VOICE_PREVIEW_OPERATION,
        idempotency_key="preview-clock-order-v1",
        request_hash="a" * 64,
        resource_id=uuid4(),
        state="reserved",
        reserved_at=reserved_at,
        completed_at=None,
    )
    session = SimpleNamespace(scalar=lambda _statement: receipt)

    product._complete_receipt(session, receipt.id, at=NOW)  # type: ignore[arg-type]

    assert receipt.state == "completed"
    assert receipt.completed_at == reserved_at


def test_receipt_reservation_replays_and_conflicts_durably() -> None:
    session = _ReceiptSession()
    resource_id = uuid4()
    first = product._reserve_receipt(
        session,  # type: ignore[arg-type]
        operation=product.VOICE_PREVIEW_OPERATION,
        idempotency_key="preview-key-0001",
        request_hash="a" * 64,
        resource_id=resource_id,
    )
    replay = product._reserve_receipt(
        session,  # type: ignore[arg-type]
        operation=product.VOICE_PREVIEW_OPERATION,
        idempotency_key="preview-key-0001",
        request_hash="a" * 64,
        resource_id=resource_id,
    )
    assert not first.replay and replay.replay
    assert replay.resource_id == resource_id
    with pytest.raises(IdempotencyConflict):
        product._reserve_receipt(
            session,  # type: ignore[arg-type]
            operation=product.VOICE_PREVIEW_OPERATION,
            idempotency_key="preview-key-0001",
            request_hash="b" * 64,
            resource_id=resource_id,
        )


class _UploadReserveSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def scalars(self, _statement):
        return []

    def add(self, row: object) -> None:
        self.added.append(row)

    def flush(self) -> None:
        pass


def test_upload_reserve_persists_both_staging_asset_identities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = VoiceProfile(
        id=uuid4(),
        owner_id=SCOPE.owner_id,
        workspace_id=SCOPE.workspace_id,
        novel_id=None,
        name="voice",
        current_version_id=None,
        status="draft",
        version=1,
        archived_at=None,
        created_at=NOW,
        updated_at=NOW,
    )
    source = b"RIFF-source-WAVE"
    source_digest = hashlib.sha256(source).hexdigest()
    metadata = product.wire.UploadedVoiceVersionMetadata.model_validate(
        {
            "expected_profile_version": 1,
            "language": "zh-CN",
            "original_filename": "reference.wav",
            "reference_sha256": source_digest,
            "rights": {
                "notice_version": "voice-rights/1",
                "source_identifier": "owner-recording-1",
                "purpose": "private_novel_narration",
                "commercial_use": False,
                "redistribution": False,
                "voice_cloning": True,
                "subject_consent_reference": "self-consent-1",
                "confirmed": True,
            },
        }
    )
    parsed = product.ParsedUploadedVoice(
        metadata=metadata,
        mime_type="audio/wav",
        filename="reference.wav",
        byte_size=len(source),
        checksum_sha256=source_digest,
        reference_audio=source,
    )
    normalized_digest = "b" * 64
    normalized = SimpleNamespace(
        source=SimpleNamespace(
            duration_ms=4_000,
            sample_rate_hz=48_000,
            channels=2,
        ),
        normalized_byte_size=768_044,
        duration_ms=4_000,
        sample_rate_hz=48_000,
        channels=2,
        normalized_sha256=normalized_digest,
    )
    monkeypatch.setattr(product, "_required_profile", lambda *_a, **_k: profile)
    monkeypatch.setattr(product, "_db_now", lambda _session: NOW)
    monkeypatch.setattr(
        product,
        "_reserve_receipt",
        lambda *_args, **_kwargs: product._ReceiptReservation(
            row_id=uuid4(),
            resource_id=product._stable_uuid(
                product.VOICE_UPLOAD_OPERATION, "upload-key-0001"
            ),
            state="reserved",
            replay=False,
        ),
    )
    session = _UploadReserveSession()

    reservation = _service_for_private_methods()._reserve_upload(
        session,  # type: ignore[arg-type]
        profile_id=profile.id,
        parsed=parsed,
        normalized=normalized,  # type: ignore[arg-type]
        idempotency_key="upload-key-0001",
        request_hash="a" * 64,
    )

    assets = [row for row in session.added if isinstance(row, MediaAsset)]
    assert len(assets) == 2
    by_class = {asset.asset_class: asset for asset in assets}
    assert by_class["source"].kind == "narration_voice_reference_source"
    assert by_class["source"].retention_policy == "uploaded_original"
    assert by_class["source"].state == "staging"
    assert by_class["voice_reference"].kind == "narration_voice_reference"
    assert by_class["voice_reference"].retention_policy == "locked_voice"
    assert by_class["voice_reference"].content_hash == normalized_digest
    assert reservation.source_asset_id == by_class["source"].id
    assert reservation.reference_asset_id == by_class["voice_reference"].id


class _CollisionStorage:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.verified = False

    def publish_media(self, *_args, **_kwargs):
        raise TargetCollision("already published")

    def verify_existing_media(
        self,
        relative_path: str,
        *,
        expected_sha256: str,
        expected_size: int,
        max_bytes: int,
    ) -> PublishedFile:
        self.verified = True
        asset_id = UUID(hex=relative_path.split("/")[2])
        assert expected_size == len(self.payload) <= max_bytes
        return PublishedFile(
            asset_id=asset_id,
            relative_path=relative_path,
            actual_sha256=expected_sha256,
            byte_size=expected_size,
            strong_etag=f'"{expected_sha256}"',
            device=1,
            inode=2,
        )


def test_publication_adopts_verified_immutable_media_after_crash() -> None:
    payload = b"normalized-media"
    digest = hashlib.sha256(payload).hexdigest()
    storage = _CollisionStorage(payload)
    published = product._published_or_adopted(
        storage,  # type: ignore[arg-type]
        payload,
        asset_id=uuid4(),
        digest=digest,
        extension="wav",
        max_bytes=1_024,
    )
    assert storage.verified
    assert published.actual_sha256 == digest


class _RightsSession:
    def __init__(self, rights: VoiceRightsRecord, events: list[VoiceRightsEvent]) -> None:
        self.rights = rights
        self.events = events

    def scalar(self, _statement):
        return self.rights

    def scalars(self, _statement):
        return self.events


def test_rights_must_have_confirmed_evidence_and_no_negative_history() -> None:
    profile = VoiceProfile(
        id=uuid4(),
        owner_id=SCOPE.owner_id,
        workspace_id=SCOPE.workspace_id,
        novel_id=None,
        name="voice",
        current_version_id=None,
        status="draft",
        version=1,
        archived_at=None,
        created_at=NOW,
        updated_at=NOW,
    )
    rights = VoiceRightsRecord(
        id=uuid4(),
        owner_id=SCOPE.owner_id,
        workspace_id=SCOPE.workspace_id,
        novel_id=None,
        source_kind="user_upload",
        source_identifier="private",
        notice_version="v1",
        purpose="private_novel_narration",
        commercial_use=False,
        redistribution=False,
        voice_cloning=True,
        subject_consent_reference="consent",
        confirmed_actor="owner",
        confirmed_at=NOW,
        expires_at=NOW + timedelta(days=1),
        risk_flags_json=[],
    )
    version = VoiceProfileVersion(
        id=uuid4(),
        profile_id=profile.id,
        owner_id=SCOPE.owner_id,
        workspace_id=SCOPE.workspace_id,
        version_number=1,
        source_type="uploaded",
        state="draft",
        rights_record_id=rights.id,
    )
    confirmed = VoiceRightsEvent(
        id=uuid4(),
        rights_record_id=rights.id,
        event_key="confirmed",
        event_type="confirmed",
        actor="owner",
        reason_code=None,
        occurred_at=NOW,
    )
    assert product._required_active_rights(
        _RightsSession(rights, [confirmed]),  # type: ignore[arg-type]
        profile,
        version,
        at=NOW,
        for_update=True,
    ) is rights
    revoked = VoiceRightsEvent(
        id=uuid4(),
        rights_record_id=rights.id,
        event_key="revoked",
        event_type="revoked",
        actor="owner",
        reason_code="OWNER_REVOKED",
        occurred_at=NOW,
    )
    with pytest.raises(VoiceRightsUnavailable):
        product._required_active_rights(
            _RightsSession(rights, [confirmed, revoked]),  # type: ignore[arg-type]
            profile,
            version,
            at=NOW,
            for_update=True,
        )


class _MediaSession:
    def __init__(self, preview: VoicePreview, asset: MediaAsset) -> None:
        self.preview, self.asset = preview, asset
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    def get_bind(self):
        return self.bind

    def scalar(self, _statement):
        return self.preview

    def get(self, _model, row_id: UUID):
        return self.asset if row_id == self.asset.id else None


def test_preview_media_resolver_requires_ready_unexpired_exact_asset() -> None:
    preview_id, asset_id = uuid4(), uuid4()
    expiry = datetime.now(UTC) + timedelta(hours=1)
    digest = "e" * 64
    preview = VoicePreview(
        id=preview_id,
        owner_id=SCOPE.owner_id,
        workspace_id=SCOPE.workspace_id,
        novel_id=None,
        profile_id=uuid4(),
        version_id=uuid4(),
        rights_record_id=uuid4(),
        job_id=uuid4(),
        reference_asset_id=uuid4(),
        result_asset_id=asset_id,
        preview_text=None,
        preview_text_digest_key_id="key-1",
        preview_text_digest="a" * 64,
        model_fingerprint="b" * 64,
        reference_fingerprint="c" * 64,
        parameters_fingerprint="d" * 64,
        request_fingerprint="f" * 64,
        status="ready",
        started_at=NOW,
        completed_at=NOW,
        expires_at=expiry,
        failure_code=None,
        created_at=NOW,
        updated_at=NOW,
    )
    asset = MediaAsset(
        id=asset_id,
        owner_id=SCOPE.owner_id,
        workspace_id=SCOPE.workspace_id,
        novel_id=None,
        source_revision_id=None,
        kind="narration_voice_preview",
        asset_class="preview",
        mime_type="audio/wav",
        byte_size=1_000,
        duration_ms=200,
        sample_rate=48_000,
        channels=2,
        storage_backend="local",
        state="ready",
        retention_policy="temporary_preview",
        checksum_algorithm="sha256",
        validation_json={},
        verified_at=NOW,
        last_accessed_at=None,
        expires_at=expiry,
        deleted_at=None,
        gc_generation=0,
        gc_marked_at=None,
        storage_path=f"assets/{asset_id.hex[:2]}/{asset_id.hex}/{digest}.wav",
        content_hash=digest,
        metadata_json={},
        created_at=NOW,
    )
    session = _MediaSession(preview, asset)
    assert resolve_voice_preview_media(
        session, preview_id, asset_id  # type: ignore[arg-type]
    ) is asset
    preview.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(VoicePreviewNotFound):
        resolve_voice_preview_media(
            session, preview_id, asset_id  # type: ignore[arg-type]
        )


def test_terminal_preview_always_removes_private_text() -> None:
    preview = VoicePreview(status="running", preview_text="private", result_asset_id=None)
    SqlAlchemyVoicePreviewRepository._terminal_preview(
        preview,
        status="failed",
        at=NOW,
        failure_code="NANO_PREVIEW_AUDIO_INVALID",
    )
    assert preview.preview_text is None
    assert preview.status == "failed"
    assert preview.completed_at == NOW


class _LockSession:
    def __init__(
        self,
        previews: list[VoicePreview],
        result_asset: MediaAsset | None = None,
        model_run: object | None = None,
    ) -> None:
        self.previews = previews
        self._scalar_rows = iter((result_asset, model_run))

    def scalars(self, _statement):
        return self.previews

    def scalar(self, _statement):
        return next(self._scalar_rows)

    def flush(self) -> None:
        pass


def _service_for_private_methods(
    *, preview_policy: VoicePreviewPolicy | None = None
) -> product.VoiceProductService:
    keyring = DigestKeyring(
        active_key_id="key-1",
        keys={"key-1": HmacDigestKey("key-1", b"k" * 32)},
    )
    return product.VoiceProductService(
        lambda: None,  # type: ignore[arg-type,return-value]
        storage=SimpleNamespace(
            publish_media=lambda *_args, **_kwargs: None,
            verify_existing_media=lambda *_args, **_kwargs: None,
        ),  # type: ignore[arg-type]
        normalize_reference=lambda _parsed: None,  # type: ignore[arg-type,return-value]
        digest_keyring=keyring,
        preview_policy=preview_policy
        or VoicePreviewPolicy(expected_model_fingerprint="b" * 64),
    )


def test_version_decode_parameters_override_process_defaults_for_preview() -> None:
    version = VoiceProfileVersion(
        id=uuid4(),
        profile_id=uuid4(),
        owner_id=SCOPE.owner_id,
        workspace_id=SCOPE.workspace_id,
        source_type="preset",
        state="draft",
        seed=1,
        parameters_json={
            "schema_version": product.OFFICIAL_PRESET_VERSION_SCHEMA_VERSION,
            "sample_mode": "fixed",
            "max_new_frames": 300,
        },
    )
    process_defaults = VoicePreviewPolicy(
        expected_model_fingerprint="b" * 64,
        seed=0,
        sample_mode="greedy",
        max_new_frames=375,
    )

    assert product._version_decode_parameters(version) == (1, "fixed", 300, None)
    assert process_defaults.parameters_fingerprint_for_version(
        version, "onnx.Zhiming"
    ) != process_defaults.parameters_fingerprint_for("onnx.Zhiming")


def test_version_decode_v2_changes_preview_fingerprint_and_rejects_ineffective_mode() -> None:
    parameters = {
        "schema_version": "moss-nano-decode-parameters/2",
        "text_temperature_milli": 1_200,
        "text_top_p_milli": 800,
        "text_top_k": 40,
        "audio_temperature_milli": 1_100,
        "audio_top_p_milli": 850,
        "audio_top_k": 30,
        "audio_repetition_penalty_milli": 1_300,
    }
    version = VoiceProfileVersion(
        id=uuid4(),
        profile_id=uuid4(),
        owner_id=SCOPE.owner_id,
        workspace_id=SCOPE.workspace_id,
        source_type="uploaded",
        state="draft",
        seed=7,
        parameters_json={
            "schema_version": product.VOICE_PRODUCT_SCHEMA_VERSION,
            "sample_mode": "full",
            "max_new_frames": 375,
            "decode_parameters": parameters,
        },
    )
    policy = VoicePreviewPolicy(expected_model_fingerprint="b" * 64)

    seed, mode, frames, decoded = product._version_decode_parameters(version)

    assert (seed, mode, frames) == (7, "full", 375)
    assert decoded is not None
    assert dict(decoded.wire_payload()) == parameters
    fingerprint = policy.parameters_fingerprint_for_version(
        version, "uploaded-reference"
    )
    version.parameters_json = {
        **version.parameters_json,
        "decode_parameters": {**parameters, "audio_top_k": 31},
    }
    assert (
        policy.parameters_fingerprint_for_version(version, "uploaded-reference")
        != fingerprint
    )
    version.parameters_json = {
        **version.parameters_json,
        "sample_mode": "fixed",
    }
    with pytest.raises(product.VoiceProductSecurityError, match="require full"):
        product._version_decode_parameters(version)


@pytest.mark.parametrize(
    ("seed", "sample_mode", "max_new_frames"),
    (
        (0, "fixed", 375),
        (1, "fixed", 375),
        (1234, "greedy", 375),
        (1234, "fixed", 374),
    ),
)
def test_official_preset_creation_rejects_nondefault_decode_parameters_before_db(
    seed: int,
    sample_mode: str,
    max_new_frames: int,
) -> None:
    service = _service_for_private_methods(
        preview_policy=VoicePreviewPolicy(
            expected_model_fingerprint=(
                product.OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256
            ),
            seed=seed,
            sample_mode=sample_mode,
            max_new_frames=max_new_frames,
        )
    )

    with pytest.raises(
        product.VoiceProductSecurityError,
        match="decode parameters differ from the pinned runtime",
    ):
        service.create_preset_version(
            profile_id=uuid4(),
            request=product.wire.CreatePresetVoiceVersionRequest(
                expected_profile_version=1,
                preset_id="onnx.Zhiming",
            ),
            idempotency_key=f"official-default-reject-{seed}-{sample_mode}-{max_new_frames}",
        )


class _CanonicalOfficialSession:
    def __init__(self) -> None:
        self.rows: dict[type[object], list[object]] = {
            VoiceProfile: [],
            VoiceProfileVersion: [],
            VoiceRightsRecord: [],
            VoiceRightsEvent: [],
        }

    @staticmethod
    def _entity(statement) -> type[object]:
        return statement.column_descriptions[0]["entity"]

    def scalar(self, statement):
        rows = self.rows[self._entity(statement)]
        return rows[0] if rows else None

    def scalars(self, statement):
        return list(self.rows[self._entity(statement)])

    def add(self, row: object) -> None:
        self.rows[type(row)].append(row)

    def add_all(self, rows: list[object]) -> None:
        for row in rows:
            self.add(row)

    def flush(self) -> None:
        pass


def test_canonical_official_voice_uses_direct_v2_and_explicit_restore_only() -> None:
    session = _CanonicalOfficialSession()
    novel_id = uuid4()
    profile_id = official_preset_canonical_profile_id(
        owner_id=SCOPE.owner_id,
        workspace_id=SCOPE.workspace_id,
        novel_id=novel_id,
        preset_id="onnx.Trump",
    )
    version_id = official_preset_canonical_version_id(
        profile_id=profile_id,
        preset_id="onnx.Trump",
    )

    created = product.ensure_canonical_official_preset_voice(
        session,  # type: ignore[arg-type]
        novel_id=novel_id,
        preset_id="onnx.Trump",
        actor="local-owner",
        at=NOW,
    )

    assert created.profile.id == profile_id
    assert created.profile.novel_id == novel_id
    assert created.profile.current_version_id == version_id
    assert created.profile.status == "active"
    assert created.profile.version == 2
    assert created.version.state == "locked"
    assert created.version.quality_state == "pending"
    assert created.version.activation_basis == (
        "explicit_official_preset_selection"
    )
    assert created.version.validation_basis == "not_required"
    assert created.version.locked_actor is None
    assert created.version.locked_at is None
    assert created.version.fingerprint == official_preset_direct_version_fingerprint(
        profile_id=profile_id,
        version_id=version_id,
        preset_id="onnx.Trump",
    )
    assert created.version.fingerprint != product.official_preset_version_fingerprint(
        profile_id=profile_id,
        version_id=version_id,
        preset_id="onnx.Trump",
    )

    created.profile.status = "archived"
    created.profile.archived_at = NOW
    restored = product.ensure_canonical_official_preset_voice(
        session,  # type: ignore[arg-type]
        novel_id=novel_id,
        preset_id="onnx.Trump",
        actor="local-owner",
        at=NOW + timedelta(minutes=1),
    )
    assert restored.profile is created.profile
    assert restored.version is created.version
    assert restored.profile.status == "active"
    assert restored.profile.archived_at is None
    assert restored.profile.version == 3

    restored.profile.status = "unavailable"
    with pytest.raises(VoiceRightsUnavailable, match="unavailable"):
        product.ensure_canonical_official_preset_voice(
            session,  # type: ignore[arg-type]
            novel_id=novel_id,
            preset_id="onnx.Trump",
            actor="local-owner",
            at=NOW + timedelta(minutes=2),
        )


@pytest.mark.parametrize("seed", [-1, 2**63, True])
def test_voice_preview_policy_rejects_seed_outside_sidecar_contract(
    seed: int,
) -> None:
    with pytest.raises(ValueError, match="seed is outside"):
        VoicePreviewPolicy(
            expected_model_fingerprint="b" * 64,
            seed=seed,
        ).validate()


def test_lock_uses_global_order_and_requires_matching_unexpired_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = VoiceProfile(
        id=uuid4(),
        owner_id=SCOPE.owner_id,
        workspace_id=SCOPE.workspace_id,
        novel_id=None,
        name="voice",
        current_version_id=None,
        status="draft",
        version=2,
        archived_at=None,
        created_at=NOW,
        updated_at=NOW,
    )
    rights = VoiceRightsRecord(id=uuid4())
    version = VoiceProfileVersion(
        id=uuid4(),
        profile_id=profile.id,
        owner_id=SCOPE.owner_id,
        workspace_id=SCOPE.workspace_id,
        version_number=1,
        source_type="uploaded",
        state="preview_ready",
        rights_record_id=rights.id,
        fingerprint="a" * 64,
        quality_state="pending",
        seed=0,
        parameters_json={
            "schema_version": product.VOICE_PRODUCT_SCHEMA_VERSION,
            "sample_mode": "fixed",
            "max_new_frames": 375,
        },
    )
    reference_id, result_id = uuid4(), uuid4()
    version.reference_asset_id = reference_id
    link = SimpleNamespace(
        profile_id=profile.id,
        rights_record_id=rights.id,
        reference_asset_id=reference_id,
        normalization_fingerprint="c" * 64,
        validation_fingerprint="d" * 64,
    )
    reference = MediaAsset(
        id=reference_id,
        content_hash="e" * 64,
    )
    expected_reference = product._reference_fingerprint(version, link, reference)
    expiry = NOW + timedelta(hours=1)
    preview = VoicePreview(
        id=uuid4(),
        profile_id=profile.id,
        version_id=version.id,
        rights_record_id=rights.id,
        reference_asset_id=reference_id,
        result_asset_id=result_id,
        status="ready",
        expires_at=expiry,
        completed_at=NOW,
        reference_fingerprint=expected_reference,
        model_fingerprint="b" * 64,
        parameters_fingerprint=VoicePreviewPolicy(
            expected_model_fingerprint="b" * 64
        ).parameters_fingerprint_for_version(version, "uploaded-reference"),
    )
    result = MediaAsset(
        id=result_id,
        owner_id=SCOPE.owner_id,
        workspace_id=SCOPE.workspace_id,
        novel_id=None,
        kind="narration_voice_preview",
        asset_class="preview",
        retention_policy="temporary_preview",
        state="ready",
        expires_at=expiry,
        content_hash="f" * 64,
    )
    model_run = SimpleNamespace(
        model_fingerprint="b" * 64,
        parameters_digest=preview.parameters_fingerprint,
        output_digest=result.content_hash,
    )
    order: list[str] = []
    monkeypatch.setattr(
        product,
        "_required_version",
        lambda *_args, **_kwargs: (order.append("version"), version)[1],
    )
    monkeypatch.setattr(
        product,
        "_required_profile",
        lambda *_args, **_kwargs: (order.append("profile"), profile)[1],
    )
    monkeypatch.setattr(
        product,
        "_required_active_rights",
        lambda *_args, **_kwargs: (order.append("rights"), rights)[1],
    )
    monkeypatch.setattr(product, "_required_reference_link", lambda *_a, **_k: link)
    monkeypatch.setattr(product, "_required_reference_asset", lambda *_a, **_k: reference)
    monkeypatch.setattr(product, "_db_now", lambda _session: NOW)
    monkeypatch.setattr(
        product,
        "_reserve_receipt",
        lambda *_args, **_kwargs: product._ReceiptReservation(
            row_id=uuid4(),
            resource_id=version.id,
            state="reserved",
            replay=False,
        ),
    )
    monkeypatch.setattr(product, "_complete_receipt", lambda *_a, **_k: None)
    monkeypatch.setattr(product, "voice_profile_resource", lambda *_a, **_k: "locked")
    service = _service_for_private_methods()

    resource = service._lock_in_session(
        _LockSession([preview], result, model_run),  # type: ignore[arg-type]
        profile_id=profile.id,
        request=product.wire.LockVoiceProfileRequest(
            expected_profile_version=2,
            version_id=version.id,
            quality_confirmed=True,
        ),
    )

    assert resource == "locked"
    assert order[:3] == ["version", "profile", "rights"]
    assert (version.state, version.quality_state) == ("locked", "accepted")
    assert profile.current_version_id == version.id
    assert profile.version == 3


def test_lock_rejects_when_no_unexpired_ready_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = VoiceProfile(
        id=uuid4(),
        owner_id=SCOPE.owner_id,
        workspace_id=SCOPE.workspace_id,
        novel_id=None,
        status="draft",
        version=1,
    )
    rights = VoiceRightsRecord(id=uuid4())
    version = VoiceProfileVersion(
        id=uuid4(),
        profile_id=profile.id,
        owner_id=SCOPE.owner_id,
        workspace_id=SCOPE.workspace_id,
        source_type="uploaded",
        state="preview_ready",
        rights_record_id=rights.id,
        fingerprint="a" * 64,
        quality_state="pending",
    )
    reference = MediaAsset(id=uuid4(), content_hash="e" * 64)
    version.reference_asset_id = reference.id
    link = SimpleNamespace(
        profile_id=profile.id,
        rights_record_id=rights.id,
        reference_asset_id=reference.id,
        normalization_fingerprint="c" * 64,
        validation_fingerprint="d" * 64,
    )
    monkeypatch.setattr(product, "_required_version", lambda *_a, **_k: version)
    monkeypatch.setattr(product, "_required_profile", lambda *_a, **_k: profile)
    monkeypatch.setattr(product, "_required_active_rights", lambda *_a, **_k: rights)
    monkeypatch.setattr(product, "_required_reference_link", lambda *_a, **_k: link)
    monkeypatch.setattr(product, "_required_reference_asset", lambda *_a, **_k: reference)
    monkeypatch.setattr(product, "_db_now", lambda _session: NOW)
    monkeypatch.setattr(
        product,
        "_reserve_receipt",
        lambda *_args, **_kwargs: product._ReceiptReservation(
            row_id=uuid4(),
            resource_id=version.id,
            state="reserved",
            replay=False,
        ),
    )

    with pytest.raises(product.InvalidNarrationState, match="unexpired Nano preview"):
        _service_for_private_methods()._lock_in_session(
            _LockSession([]),  # type: ignore[arg-type]
            profile_id=profile.id,
            request=product.wire.LockVoiceProfileRequest(
                expected_profile_version=1,
                version_id=version.id,
                quality_confirmed=True,
            ),
        )
