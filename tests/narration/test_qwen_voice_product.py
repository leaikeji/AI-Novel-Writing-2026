from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import hashlib
from io import BytesIO
import math
import os
from types import SimpleNamespace
from uuid import UUID, uuid4
import wave

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from backend.models import ModelRunRecord, Novel, VoicePreview, VoiceProfile, VoiceProfileVersion
from backend.narration import schemas as wire
from backend.narration.contracts import (
    LOCAL_OWNER_ID,
    LOCAL_WORKSPACE_ID,
    NarrationRequestScope,
    TTSModelIdentity,
    TTSProviderId,
    TTSVoiceKind,
    TTSVoicePreparationResult,
)
from backend.narration.digest_keyring import DigestKeyring, HmacDigestKey
from backend.narration.jobs import FailureResult, JobFence, JobLease
from backend.narration.qwen_voice_product import (
    QwenReferenceMedia,
    QwenVoicePreviewProcessor,
    QwenVoicePreviewWorkItem,
    QwenVoiceProductPolicy,
    QwenVoiceProductSecurityError,
    QwenVoiceProductService,
    VOICE_BASE_ARTIFACT_SHA256,
    VOICE_BASE_MODEL_ID,
    VOICE_BASE_MODEL_REVISION,
    VOICE_DESIGN_ANCHOR_TEXT,
    VOICE_DESIGN_ARTIFACT_SHA256,
    VOICE_DESIGN_MODEL_ID,
    VOICE_DESIGN_MODEL_REVISION,
)
from backend.narration.resource_locks import ResourceFence
from backend.narration.scheduler import NarrationJobScheduler, SchedulerConfig
from backend.narration.services import IdempotencyConflict
from backend.narration.storage import PublishedFile


NOW = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)


def _wav(duration_ms: int = 2_000) -> bytes:
    sample_rate = 24_000
    output = BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        frames = bytearray()
        for index in range(round(sample_rate * duration_ms / 1000)):
            value = round(4_000 * math.sin(2 * math.pi * 220 * index / sample_rate))
            frames.extend(value.to_bytes(2, "little", signed=True))
        target.writeframes(bytes(frames))
    return output.getvalue()


def _identity(*, design: bool) -> TTSModelIdentity:
    return TTSModelIdentity(
        provider_id=TTSProviderId.LOCAL_QWEN3_TTS,
        model_id=VOICE_DESIGN_MODEL_ID if design else VOICE_BASE_MODEL_ID,
        model_revision=(
            VOICE_DESIGN_MODEL_REVISION if design else VOICE_BASE_MODEL_REVISION
        ),
        runtime_id="mlx-audio",
        runtime_version="test",
        quantization="bf16" if design else "8bit",
        artifact_tree_sha256=(
            VOICE_DESIGN_ARTIFACT_SHA256 if design else VOICE_BASE_ARTIFACT_SHA256
        ),
    )


def _result(request_id: UUID, *, design: bool, payload: bytes | None = None):
    audio = payload or _wav()
    return TTSVoicePreparationResult(
        request_id=request_id,
        provider_voice_id="ephemeral-design" if design else "durable-reference",
        preview_audio_bytes=audio,
        actual_output_sha256=hashlib.sha256(audio).hexdigest(),
        model_identity=_identity(design=design),
        voice_kind=TTSVoiceKind.DESIGNED if design else TTSVoiceKind.REFERENCE_CLONE,
    )


def _lease() -> JobLease:
    return JobLease(
        fence=JobFence(
            job_id=uuid4(),
            attempt_id=uuid4(),
            lease_token=uuid4(),
            lease_generation=1,
        ),
        attempt_number=1,
        retry_kind="initial",
        lease_owner="qwen-preview-test",
        lease_until=NOW + timedelta(minutes=2),
        executor_epoch_id=uuid4(),
        resource_fence=ResourceFence(
            resource_key="qwen-tts:inference",
            lease_owner="qwen-preview-test",
            lease_token=uuid4(),
            lease_generation=1,
        ),
    )


class _Storage:
    def __init__(self) -> None:
        self.payloads: dict[str, bytes] = {}
        self.publications: list[PublishedFile] = []

    def publish_or_verify_media(
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
        path = (
            f"assets/{asset_id.hex[:2]}/{asset_id.hex}/"
            f"{expected_sha256}.{extension}"
        )
        existing = self.payloads.get(path)
        assert existing in {None, payload}
        self.payloads[path] = payload
        published = PublishedFile(
            asset_id=asset_id,
            relative_path=path,
            actual_sha256=expected_sha256,
            byte_size=len(payload),
            strong_etag=f'"{expected_sha256}"',
            device=1,
            inode=len(self.payloads),
        )
        self.publications.append(published)
        return published

    def verify_media_identity(self, relative_path: str, **expected):
        payload = self.payloads[relative_path]
        assert hashlib.sha256(payload).hexdigest() == expected["expected_sha256"]
        assert len(payload) == expected["expected_size"]
        return SimpleNamespace(device=1, inode=2, byte_size=len(payload))

    def stream_media(self, relative_path: str, **_expected):
        yield self.payloads[relative_path]


class _Execution:
    def __init__(self, *, drift_design_identity: bool = False) -> None:
        self.calls: list[tuple[str, object]] = []
        self.drift_design_identity = drift_design_identity

    async def design_voice(self, *, novel_id, selection, request):
        del novel_id, selection
        self.calls.append(("design", request))
        result = _result(request.request_id, design=True)
        if not self.drift_design_identity:
            return result
        return TTSVoicePreparationResult(
            request_id=result.request_id,
            provider_voice_id=result.provider_voice_id,
            preview_audio_bytes=result.preview_audio_bytes,
            actual_output_sha256=result.actual_output_sha256,
            model_identity=TTSModelIdentity(
                provider_id=TTSProviderId.LOCAL_QWEN3_TTS,
                model_id=VOICE_DESIGN_MODEL_ID,
                model_revision=VOICE_DESIGN_MODEL_REVISION,
                runtime_id="mlx-audio",
                runtime_version="test",
                quantization="bf16",
                artifact_tree_sha256="f" * 64,
            ),
            voice_kind=TTSVoiceKind.DESIGNED,
        )

    async def clone_voice(self, *, novel_id, selection, request):
        del novel_id, selection
        self.calls.append(("clone", request))
        return _result(request.request_id, design=False)

    async def cancel(self, *, selection, request_id):
        del selection, request_id
        return None


class _Repository:
    def __init__(self, work: QwenVoicePreviewWorkItem) -> None:
        self.work = work
        self.state = "running"
        self.reference_prepared = None
        self.preview_prepared = None
        self.preview_work = None
        self.failure: tuple[str, str] | None = None

    def load_and_mark_running(self, lease: JobLease):
        assert lease == self.work.lease
        return self.work

    def read_job_state(self, lease: JobLease) -> str:
        assert lease == self.work.lease
        return self.state

    def heartbeat_and_read_state(self, lease: JobLease) -> str:
        return self.read_job_state(lease)

    def publish_generated_reference(self, work, prepared):
        assert work == self.work
        self.reference_prepared = prepared
        return QwenReferenceMedia(
            asset_id=prepared.published.asset_id,
            relative_path=prepared.published.relative_path,
            actual_sha256=prepared.published.actual_sha256,
            byte_size=prepared.published.byte_size,
            content_type="audio/wav",
            reference_text=VOICE_DESIGN_ANCHOR_TEXT,
        )

    def publish_preview(self, work, reference, prepared) -> None:
        assert reference.asset_id == self.reference_prepared.published.asset_id
        self.preview_work = work
        self.preview_prepared = prepared
        self.state = "succeeded"

    def fail(self, work, *, classification: str, error_code: str):
        self.failure = (classification, error_code)
        self.state = "failed"
        return FailureResult(
            job_id=work.lease.fence.job_id,
            state="failed",
            next_retry_at=None,
        )

    def fail_claim(self, lease, *, classification: str, error_code: str):
        self.failure = (classification, error_code)
        return FailureResult(
            job_id=lease.fence.job_id,
            state="failed",
            next_retry_at=None,
        )

    def acknowledge_cancel(self, work) -> None:
        assert work.lease == self.work.lease
        self.state = "cancelled"


def _work(*, reference: QwenReferenceMedia | None = None):
    return QwenVoicePreviewWorkItem(
        lease=_lease(),
        preview_id=uuid4(),
        profile_id=uuid4(),
        version_id=uuid4(),
        rights_record_id=uuid4(),
        novel_id=uuid4(),
        preview_text="故事从这里开始。",
        description=("沉稳、温暖、清晰的普通话男声" if reference is None else None),
        seed=1234,
        request_fingerprint="a" * 64,
        parameters_fingerprint="b" * 64,
        input_digest_key_id="test-key",
        input_digest="c" * 64,
        reference=reference,
    )


def _processor(repository, execution, storage):
    return QwenVoicePreviewProcessor(
        repository=repository,
        execution=execution,
        storage=storage,
        policy=QwenVoiceProductPolicy(heartbeat_seconds=0.01),
    )


def test_designed_preview_persists_anchor_then_uses_base_clone() -> None:
    work = _work()
    repository = _Repository(work)
    storage = _Storage()
    execution = _Execution()

    outcome = asyncio.run(_processor(repository, execution, storage).process(work.lease))

    assert outcome.status == "succeeded", outcome
    assert [kind for kind, _request in execution.calls] == ["design", "clone"]
    design_request = execution.calls[0][1]
    clone_request = execution.calls[1][1]
    assert design_request.language == clone_request.language == "zh-CN"
    assert design_request.preview_text == VOICE_DESIGN_ANCHOR_TEXT
    assert clone_request.reference_text == VOICE_DESIGN_ANCHOR_TEXT
    assert clone_request.reference_audio is not None
    assert repository.reference_prepared.requested_model_id == VOICE_DESIGN_MODEL_ID
    assert repository.preview_prepared.requested_model_id == VOICE_BASE_MODEL_ID
    assert repository.preview_work.description is None
    assert len(storage.publications) == 2


def test_identity_drift_fails_closed_without_publishing_reference() -> None:
    work = _work()
    repository = _Repository(work)
    storage = _Storage()
    execution = _Execution(drift_design_identity=True)

    outcome = asyncio.run(_processor(repository, execution, storage).process(work.lease))

    assert outcome.status == "failed"
    assert outcome.error_code == "VOICE_PREVIEW_SECURITY_FAILURE"
    assert repository.failure == (
        "security_failure",
        "VOICE_PREVIEW_SECURITY_FAILURE",
    )
    assert storage.publications == []
    assert repository.preview_prepared is None


class _ApplicationRepository:
    def __init__(self) -> None:
        self.design_calls: list[dict[str, object]] = []
        self.by_key: dict[str, tuple[str, UUID]] = {}

    def create_designed_version(self, **values):
        prior = self.by_key.get(values["idempotency_key"])
        identity = (values["request_hash"], values["version_id"])
        if prior is not None and prior != identity:
            raise IdempotencyConflict("conflict")
        self.by_key[values["idempotency_key"]] = identity
        self.design_calls.append(values)
        return SimpleNamespace(version_id=values["version_id"])


def _keyring() -> DigestKeyring:
    key = HmacDigestKey(key_id="test-key", secret=b"k" * 32)
    return DigestKeyring(active_key_id=key.key_id, keys={key.key_id: key})


def test_design_request_is_deterministic_and_never_hashes_plaintext_naked() -> None:
    repository = _ApplicationRepository()
    service = QwenVoiceProductService(
        lambda: None,
        storage=_Storage(),
        normalize_reference=lambda _parsed: None,
        digest_keyring=_keyring(),
        repository=repository,  # type: ignore[arg-type]
    )
    request = wire.CreateDesignedVoiceVersionRequest(
        expected_profile_version=2,
        description=" 沉稳、温暖、清晰的普通话男声 ",
        language="zh-CN",
        seed=7,
    )

    first = service.create_designed_version(
        profile_id=uuid4(),
        request=request,
        idempotency_key="design-key-0001",
    )
    second = service.create_designed_version(
        profile_id=repository.design_calls[0]["profile_id"],
        request=request,
        idempotency_key="design-key-0001",
    )

    assert first.version_id == second.version_id
    call = repository.design_calls[0]
    assert call["description"] == "沉稳、温暖、清晰的普通话男声"
    assert call["description_digest"] != hashlib.sha256(
        call["description"].encode("utf-8")
    ).hexdigest()
    assert call["description_digest_key_id"] == "test-key"


def test_design_idempotency_key_rejects_a_different_request() -> None:
    repository = _ApplicationRepository()
    profile_id = uuid4()
    service = QwenVoiceProductService(
        lambda: None,
        storage=_Storage(),
        normalize_reference=lambda _parsed: None,
        digest_keyring=_keyring(),
        repository=repository,  # type: ignore[arg-type]
    )
    service.create_designed_version(
        profile_id=profile_id,
        request=wire.CreateDesignedVoiceVersionRequest(
            expected_profile_version=1,
            description="清晰自然的普通话女声",
        ),
        idempotency_key="design-key-0002",
    )

    with pytest.raises(IdempotencyConflict):
        service.create_designed_version(
            profile_id=profile_id,
            request=wire.CreateDesignedVoiceVersionRequest(
                expected_profile_version=1,
                description="低沉自然的普通话男声",
            ),
            idempotency_key="design-key-0002",
        )


def test_live_postgres_designed_voice_reaches_locked_durable_closure() -> None:
    """Exercise the real repository and deferred triggers on the exact test DB."""

    raw = os.environ.get("TTS_TEST_DATABASE_URL", "").strip()
    if not raw:
        pytest.skip("TTS_TEST_DATABASE_URL is not configured")
    url = make_url(raw)
    if (
        url.database != "ai_novel_world_2026_tts_test"
        or url.username != "tts_test"
        or url.host not in {"127.0.0.1", "localhost", "::1"}
    ):
        raise RuntimeError("live Qwen voice test requires the exact disposable TTS database")
    engine = create_engine(raw, pool_pre_ping=True)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20260912_0055"
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    novel_id = uuid4()
    profile_id = uuid4()
    with sessions.begin() as session:
        session.add(Novel(
            id=novel_id,
            owner_id=LOCAL_OWNER_ID,
            workspace_id=LOCAL_WORKSPACE_ID,
            title="计划 76 一次性声音闭环测试",
        ))
        session.add(VoiceProfile(
            id=profile_id,
            owner_id=LOCAL_OWNER_ID,
            workspace_id=LOCAL_WORKSPACE_ID,
            novel_id=novel_id,
            name="普通话设计音色",
            current_version_id=None,
            status="draft",
            version=1,
            archived_at=None,
        ))

    storage = _Storage()
    service = QwenVoiceProductService(
        sessions,
        storage=storage,
        normalize_reference=lambda _parsed: None,
        digest_keyring=_keyring(),
    )
    version = service.create_designed_version(
        profile_id=profile_id,
        request=wire.CreateDesignedVoiceVersionRequest(
            expected_profile_version=1,
            description="沉稳、温暖、清晰的普通话男声",
        ),
        idempotency_key=f"design-live-{uuid4().hex}",
    )
    preview = service.create_preview(
        profile_id=profile_id,
        request=wire.CreateVoicePreviewRequest(
            version_id=version.version_id,
            preview_text="这是一次普通话音色试听。",
        ),
        idempotency_key=f"preview-live-{uuid4().hex}",
    )
    scheduler = NarrationJobScheduler(
        sessions,
        config=SchedulerConfig(
            lease_owner="plan76-live-voice-test",
            job_kinds=("narration.voice_preview",),
            novel_ids=(novel_id,),
        ),
        terminalizers={
            "narration.voice_preview": service.repository.terminalize_job_in_session,
        },
    )
    scheduled = scheduler.claim_next_typed_job()
    assert scheduled is not None and scheduled.job_kind == "narration.voice_preview"
    outcome = asyncio.run(
        QwenVoicePreviewProcessor(
            repository=service.repository,
            execution=_Execution(),  # type: ignore[arg-type]
            storage=storage,
        ).process(scheduled.lease)
    )
    assert outcome.status == "succeeded", outcome
    ready = service.get_preview(preview_id=preview.preview_id)
    assert ready.status is wire.VoicePreviewStatus.READY and ready.asset is not None
    locked = service.lock_profile(
        profile_id=profile_id,
        request=wire.LockVoiceProfileRequest(
            expected_profile_version=2,
            version_id=version.version_id,
            quality_confirmed=True,
        ),
    )
    assert locked.current_version_id == version.version_id
    with sessions() as session:
        stored_version = session.get(VoiceProfileVersion, version.version_id)
        stored_preview = session.get(VoicePreview, preview.preview_id)
        runs = list(session.scalars(
            select(ModelRunRecord).where(
                ModelRunRecord.attempt_id == scheduled.lease.fence.attempt_id
            )
        ))
        assert stored_version is not None
        assert stored_preview is not None
        assert stored_version.state == "locked"
        assert stored_version.reference_asset_id is not None
        assert stored_version.preview_asset_id == stored_preview.result_asset_id
        assert {item.requested_model_id for item in runs} == {
            VOICE_DESIGN_MODEL_ID,
            VOICE_BASE_MODEL_ID,
        }
    engine.dispose()


def test_missing_resource_fence_never_calls_provider() -> None:
    work = _work()
    work = QwenVoicePreviewWorkItem(
        **{
            **{name: getattr(work, name) for name in work.__dataclass_fields__},
            "lease": JobLease(
                fence=work.lease.fence,
                attempt_number=work.lease.attempt_number,
                retry_kind=work.lease.retry_kind,
                lease_owner=work.lease.lease_owner,
                lease_until=work.lease.lease_until,
                executor_epoch_id=work.lease.executor_epoch_id,
                resource_fence=None,
            ),
        }
    )
    repository = _Repository(work)
    execution = _Execution()

    outcome = asyncio.run(
        _processor(repository, execution, _Storage()).process(work.lease)
    )

    assert outcome.status == "failed"
    assert repository.failure == ("security_failure", "RESOURCE_FENCE_MISSING")
    assert execution.calls == []
