from __future__ import annotations

from array import array
import hashlib
import io
import os
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4, uuid5
import wave

import pytest
from sqlalchemy import create_engine, delete, inspect, select, text
from sqlalchemy.engine import Connection, Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from backend.models import (
    BackgroundJob,
    BackgroundJobAttempt,
    GenericVoiceDesignDraft,
    GenericVoiceGenerationCommand,
    GenericVoicePackVersion,
    GenericVoicePackVersionSlot,
    MediaAsset,
    ModelRunRecord,
    VoiceProfile,
    VoiceProfileVersion,
)
from backend.narration.contracts import (
    LOCAL_WORKSPACE_ID,
    NarrationRequestScope,
    SynthesisRequest,
    SynthesisResult,
)
from backend.narration.jobs import JobFenceError, JobLease, claim_next_job
from backend.narration import generic_voice_pack_service as pack_module
from backend.narration.generic_voice_pack_service import (
    SqlAlchemyGenericVoicePackService,
    SqlAlchemyGenericVoiceRepository,
    resolve_generic_voice_slot_media,
)
from backend.narration.generic_voice_generation import GENERIC_VOICE_JOB_KIND
from backend.narration.runtime import EXPECTED_PRODUCTION_MODEL_FINGERPRINT
from backend.narration.scheduler import NarrationJobScheduler, SchedulerConfig
from backend.narration.services import InvalidNarrationState, NarrationNotFound
from backend.narration.storage import NarrationStorage
from backend.narration.voice_generator_processor import VoiceGeneratorProcessor
from backend.narration.voice_generator_service import VoiceGeneratorCommandState
from backend.narration.voice_generator_runtime import (
    EXPECTED_RUNTIME_FINGERPRINT,
    EXPECTED_RUNTIME_IDENTITY,
    HostGenerationReceipt,
    VoiceGeneratorAudioResult,
    VoiceGeneratorHostHealth,
    VoiceGeneratorHostRequest,
    inspect_generated_wav,
)
from tests.narration.current_schema_gate import assert_database_at_repository_head
from tests.narration.digest_fixtures import TEST_DIGEST_KEYRING


EXPECTED_DATABASE = "ai_novel_world_2026_tts_test"
SessionFactory = Callable[[], Session]


def _wav() -> bytes:
    samples = array("h")
    for index in range(48_000 * 3):
        sample = 2_800 if (index // 80) % 2 else -2_800
        samples.extend((sample, sample))
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(2)
        target.setsampwidth(2)
        target.setframerate(48_000)
        target.writeframes(samples.tobytes())
    return output.getvalue()


class _Host:
    def __init__(self) -> None:
        self.audio = _wav()

    async def health(self) -> VoiceGeneratorHostHealth:
        return VoiceGeneratorHostHealth(
            ready=True,
            status="ready",
            runtime_identity=EXPECTED_RUNTIME_IDENTITY,
            runtime_fingerprint=EXPECTED_RUNTIME_FINGERPRINT,
            active_request_id=None,
        )

    def _receipt(self, request: VoiceGeneratorHostRequest) -> HostGenerationReceipt:
        return HostGenerationReceipt.from_wire(
            {
                "protocol_version": "moss-voice-generator-host/1",
                "request_id": str(request.request_id),
                "request_digest": request.request_digest,
                "status": "completed",
                "terminal": True,
                "cancellable": False,
                "retryable": False,
                "failure_code": None,
                "runtime_identity": EXPECTED_RUNTIME_IDENTITY.wire_payload(),
                "runtime_fingerprint": EXPECTED_RUNTIME_FINGERPRINT,
                "token_sha256": hashlib.sha256(b"tokens").hexdigest(),
                "audio_sha256": hashlib.sha256(self.audio).hexdigest(),
                "audio_size_bytes": len(self.audio),
                "memory_summary": {
                    "minimum_available_memory_bytes": 900_000_000,
                    "maximum_swap_delta_bytes": 2_000_000_000,
                    "maximum_pageouts_per_second": 3,
                    "critical_pressure_milliseconds": 0,
                    "stage_pid_overlap": False,
                    "recovered_within_60_seconds": True,
                },
                "started_at": "2026-09-03T08:00:00Z",
                "completed_at": "2026-09-03T08:01:00Z",
            }
        )

    async def create(self, request: VoiceGeneratorHostRequest) -> HostGenerationReceipt:
        return self._receipt(request)

    async def get(self, request: VoiceGeneratorHostRequest) -> HostGenerationReceipt:
        return self._receipt(request)

    async def cancel(self, request: VoiceGeneratorHostRequest) -> HostGenerationReceipt:
        raise AssertionError("successful host must not be cancelled")

    async def download_audio(
        self,
        request: VoiceGeneratorHostRequest,
        receipt: HostGenerationReceipt,
    ) -> VoiceGeneratorAudioResult:
        return VoiceGeneratorAudioResult(
            request_id=request.request_id,
            audio_bytes=self.audio,
            audio_sha256=hashlib.sha256(self.audio).hexdigest(),
            runtime_fingerprint=receipt.runtime_fingerprint,
            metrics=inspect_generated_wav(self.audio),
        )


class _Nano:
    def __init__(self) -> None:
        self.released = False

    async def release_model_for_heavy_runtime(self) -> None:
        self.released = True

    async def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        assert self.released
        audio = _wav()
        return SynthesisResult(
            request_id=request.request_id,
            audio_bytes=audio,
            actual_output_sha256=hashlib.sha256(audio).hexdigest(),
            sample_rate_hz=48_000,
            channels=2,
            sample_width_bytes=2,
            model_fingerprint=EXPECTED_PRODUCTION_MODEL_FINGERPRINT,
            worker_generation=1,
        )

    async def cancel(self, request_id: UUID) -> object:
        raise AssertionError("successful Nano validation must not be cancelled")


def _live_url() -> str:
    raw = os.environ.get("TTS_TEST_DATABASE_URL", "").strip()
    if not raw:
        pytest.skip("TTS_TEST_DATABASE_URL is not configured")
    parsed = make_url(raw)
    if (
        not parsed.drivername.startswith("postgresql")
        or parsed.database != EXPECTED_DATABASE
        or parsed.host not in {"127.0.0.1", "localhost", "::1"}
    ):
        raise RuntimeError(
            "generic voice-pack tests require the exact loopback disposable TTS database"
        )
    production = os.environ.get("AI_NOVEL_DATABASE_URL", "").strip()
    if production:
        current = make_url(production)
        if (parsed.host, parsed.port, parsed.database) == (
            current.host,
            current.port,
            current.database,
        ):
            raise RuntimeError("generic voice-pack test database must differ from production")
    return raw


@pytest.fixture
def generic_pack_pg() -> Iterator[tuple[Connection, SessionFactory]]:
    engine: Engine = create_engine(_live_url(), pool_pre_ping=True)
    connection = engine.connect()
    outer = connection.begin()
    try:
        assert_database_at_repository_head(connection)
    except AssertionError as error:
        outer.rollback()
        connection.close()
        engine.dispose()
        raise RuntimeError(
            "generic voice-pack PostgreSQL tests require the repository head"
        ) from error
    required = {
        "generic_voice_pack_versions",
        "generic_voice_pack_version_slots",
        "generic_voice_design_drafts",
        "generic_voice_generation_commands",
    }
    if not required <= set(inspect(connection).get_table_names()):
        outer.rollback()
        connection.close()
        engine.dispose()
        raise RuntimeError("generic voice-pack PostgreSQL schema is incomplete")
    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    # A developer may have issued a manual build against this disposable test
    # database.  Isolate every test from it inside the outer rollback boundary.
    connection.execute(text("SET LOCAL session_replication_role=replica"))
    with factory() as session:
        job_ids = tuple(
            session.scalars(select(GenericVoiceGenerationCommand.background_job_id))
        )
        session.execute(delete(GenericVoicePackVersionSlot))
        session.execute(delete(GenericVoiceGenerationCommand))
        if job_ids:
            session.execute(
                delete(BackgroundJobAttempt).where(
                    BackgroundJobAttempt.job_id.in_(job_ids)
                )
            )
            session.execute(delete(BackgroundJob).where(BackgroundJob.id.in_(job_ids)))
        session.execute(delete(GenericVoicePackVersion))
        session.execute(delete(GenericVoiceDesignDraft))
        session.commit()
    connection.execute(text("SET LOCAL session_replication_role=origin"))
    try:
        yield connection, factory
    finally:
        if outer.is_active:
            outer.rollback()
        connection.close()
        engine.dispose()


def test_build_is_durable_idempotent_and_enqueues_one_slot(
    generic_pack_pg: tuple[Connection, SessionFactory],
) -> None:
    _connection, factory = generic_pack_pg
    service = SqlAlchemyGenericVoicePackService(factory)

    created = service.build(idempotency_key="tts55-pack-build-idempotency")
    replay = service.build(idempotency_key="tts55-pack-build-idempotency")

    assert created.command is not None
    assert created.command.command_id == replay.command.command_id
    assert created.pack.pack_version_id == replay.pack.pack_version_id
    assert created.pack.state == "building"
    assert len(created.pack.slots) == 24
    assert {slot.category for slot in created.pack.slots} == {
        "child",
        "youth",
        "middle_age",
        "older",
        "neutral_group",
    }
    assert sum(slot.state == "generating" for slot in created.pack.slots) == 1
    assert sum(slot.state == "pending" for slot in created.pack.slots) == 23

    with factory() as session:
        commands = tuple(session.scalars(select(GenericVoiceGenerationCommand)))
        assert len(commands) == 1
        assert session.scalar(select(BackgroundJob).where(
            BackgroundJob.id == commands[0].background_job_id
        )) is not None
        assert SqlAlchemyGenericVoiceRepository(factory).owns_job(
            commands[0].background_job_id
        )


@pytest.mark.asyncio
async def test_processor_publishes_one_validated_slot_and_enqueues_the_next(
    generic_pack_pg: tuple[Connection, SessionFactory], tmp_path: Path
) -> None:
    _connection, factory = generic_pack_pg
    service = SqlAlchemyGenericVoicePackService(factory)
    created = service.build(idempotency_key="tts55-pack-publish-first-slot")
    assert created.command is not None

    with factory() as session:
        first = session.scalar(
            select(GenericVoiceGenerationCommand).where(
                GenericVoiceGenerationCommand.pack_version_id
                == created.pack.pack_version_id
            )
        )
        assert first is not None
        lease = claim_next_job(
            session,
            scope=NarrationRequestScope.fixed_local(),
            lease_owner=f"generic-voice-pg:{uuid4()}",
            resource_classes=("moss-nano",),
            job_kinds=(GENERIC_VOICE_JOB_KIND,),
            lease_seconds=900,
        )
        assert lease is not None
        assert lease.fence.job_id == first.background_job_id
        session.commit()

    models_root = tmp_path / "models"
    media_root = tmp_path / "media"
    models_root.mkdir(mode=0o700)
    media_root.mkdir(mode=0o700)
    await VoiceGeneratorProcessor(
        repository=SqlAlchemyGenericVoiceRepository(factory),  # type: ignore[arg-type]
        host=_Host(),
        nano_adapter=_Nano(),  # type: ignore[arg-type]
        storage=NarrationStorage(models_root=models_root, media_root=media_root),
        digest_keyring=TEST_DIGEST_KEYRING,
        poll_seconds=0.01,
    ).process(lease)

    resource = service.get_build_resource(created.command.command_id)
    assert resource.pack.state == "building"
    assert resource.pack.prepared_slots == 1
    assert sum(slot.state == "validated" for slot in resource.pack.slots) == 1
    assert sum(slot.state == "generating" for slot in resource.pack.slots) == 1
    published_slot = next(slot for slot in resource.pack.slots if slot.state == "validated")
    assert published_slot.preview_available
    assert published_slot.preview_asset is not None
    with factory() as session:
        commands = tuple(
            session.scalars(
                select(GenericVoiceGenerationCommand)
                .where(
                    GenericVoiceGenerationCommand.pack_version_id
                    == created.pack.pack_version_id
                )
                .order_by(GenericVoiceGenerationCommand.created_at)
            )
        )
        assert [command.state for command in commands] == ["ready", "queued"]
        ready = commands[0]
        assert ready.voice_profile_id is not None
        assert ready.voice_version_id is not None
        profile = session.get(VoiceProfile, ready.voice_profile_id)
        version = session.get(VoiceProfileVersion, ready.voice_version_id)
        assert profile is not None and profile.novel_id is None
        assert profile.status == "active"
        assert version is not None
        assert version.activation_basis == "generic_voice_pack_generation"
        assert session.scalar(
            select(text("count(*)"))
            .select_from(ModelRunRecord)
            .where(ModelRunRecord.attempt_id == lease.fence.attempt_id)
        ) == 2
        resolved = resolve_generic_voice_slot_media(
            session,
            published_slot.slot_id,
            published_slot.preview_asset.asset_id,
        )
        assert resolved.id == published_slot.preview_asset.asset_id
        with pytest.raises(NarrationNotFound):
            resolve_generic_voice_slot_media(
                session,
                published_slot.slot_id,
                uuid4(),
            )
        assert session.scalar(
            select(text("count(*)"))
            .select_from(MediaAsset)
            .where(
                MediaAsset.id.in_(
                    (
                        ready.generated_reference_asset_id,
                        ready.nano_validation_asset_id,
                    )
                )
            )
        ) == 2


def test_cancel_is_monotonic_and_successor_gets_a_new_identity(
    generic_pack_pg: tuple[Connection, SessionFactory],
) -> None:
    _connection, factory = generic_pack_pg
    service = SqlAlchemyGenericVoicePackService(factory)
    active = service.build(idempotency_key="tts55-pack-cancel")
    assert active.command is not None

    cancelled = service.cancel(active.command.command_id)
    repeated = service.cancel(active.command.command_id)
    successor = service.build(idempotency_key="tts55-pack-successor")

    assert cancelled.command is not None
    assert cancelled.command.state == "cancelled"
    assert repeated.command is not None
    assert repeated.command.state == "cancelled"
    assert successor.pack.pack_version_id != active.pack.pack_version_id
    assert successor.pack.state == "building"
    assert successor.command is not None and not successor.command.terminal

    with factory() as session:
        state = session.scalar(
            select(GenericVoicePackVersion.state).where(
                GenericVoicePackVersion.id == active.pack.pack_version_id
            )
        )
        assert state == "superseded"


def test_reject_is_monotonic_and_fences_the_current_slot_job(
    generic_pack_pg: tuple[Connection, SessionFactory],
) -> None:
    _connection, factory = generic_pack_pg
    service = SqlAlchemyGenericVoicePackService(factory)
    created = service.build(idempotency_key="tts55-pack-reject")
    assert created.pack.pack_version_id is not None
    current_slot = next(slot for slot in created.pack.slots if slot.state == "generating")

    rejected = service.reject(
        slot_key=current_slot.slot_key,
        expected_pack_version_id=created.pack.pack_version_id,
    )
    repeated = service.reject(
        slot_key=current_slot.slot_key,
        expected_pack_version_id=created.pack.pack_version_id,
    )

    assert rejected.pack.state == repeated.pack.state == "rejected"
    assert next(
        slot for slot in repeated.pack.slots if slot.slot_key == current_slot.slot_key
    ).state == "rejected"
    with factory() as session:
        command = session.scalar(
            select(GenericVoiceGenerationCommand).where(
                GenericVoiceGenerationCommand.pack_version_id
                == created.pack.pack_version_id
            )
        )
        assert command is not None and command.state == "cancelled"
        job = session.get(BackgroundJob, command.background_job_id)
        assert job is not None and job.state == "cancelled"
        assert claim_next_job(
            session,
            scope=NarrationRequestScope.fixed_local(),
            lease_owner=f"generic-voice-rejected:{uuid4()}",
            resource_classes=("moss-nano",),
            job_kinds=(GENERIC_VOICE_JOB_KIND,),
            lease_seconds=900,
        ) is None


def _claim_generic(factory: SessionFactory) -> JobLease:
    with factory() as session:
        lease = claim_next_job(
            session,
            scope=NarrationRequestScope.fixed_local(),
            lease_owner=f"tts56-pool:{uuid4()}",
            resource_classes=("moss-nano",),
            job_kinds=(GENERIC_VOICE_JOB_KIND,),
            lease_seconds=900,
        )
        assert lease is not None
        session.commit()
        return lease


def _processor(factory: SessionFactory, tmp_path: Path) -> VoiceGeneratorProcessor:
    models = tmp_path / "models"
    media = tmp_path / "media"
    models.mkdir(exist_ok=True)
    media.mkdir(exist_ok=True)
    return VoiceGeneratorProcessor(
        repository=SqlAlchemyGenericVoiceRepository(factory),  # type: ignore[arg-type]
        host=_Host(),
        nano_adapter=_Nano(),  # type: ignore[arg-type]
        storage=NarrationStorage(models_root=models, media_root=media),
        digest_keyring=TEST_DIGEST_KEYRING,
        poll_seconds=0.01,
    )


def _draft_seeds(factory: SessionFactory, pack_id: UUID) -> dict[str, int]:
    with factory() as session:
        return dict(session.execute(
            select(GenericVoicePackVersionSlot.slot_key, GenericVoiceDesignDraft.seed)
            .join(GenericVoiceDesignDraft, GenericVoiceDesignDraft.id == GenericVoicePackVersionSlot.design_draft_id)
            .where(GenericVoicePackVersionSlot.pack_version_id == pack_id)
        ).all())


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_path", ["worker_failure", "lease_expired", "legacy_failed_child"])
async def test_failed_job_closes_pack_and_retry_reuses_validated_slot(
    generic_pack_pg: tuple[Connection, SessionFactory], tmp_path: Path, failure_path: str
) -> None:
    _connection, factory = generic_pack_pg
    service = SqlAlchemyGenericVoicePackService(factory)
    original = service.build(idempotency_key=f"tts56-recovery-{failure_path}")
    await _processor(factory, tmp_path).process(_claim_generic(factory))
    before = service.get_load_resource()
    accepted = next(slot for slot in before.pack.slots if slot.state == "validated")
    lease = _claim_generic(factory)
    repository = SqlAlchemyGenericVoiceRepository(factory)
    work = repository.load_and_mark_generating(lease)
    if failure_path == "worker_failure":
        repository.fail(
            work, state=VoiceGeneratorCommandState.FAILED_GENERATION,
            failure_code="HOST_TEMPORARILY_UNAVAILABLE", classification="retryable",
        )
    else:
        with factory() as session:
            attempt = session.get(BackgroundJobAttempt, lease.fence.attempt_id)
            assert attempt is not None
            attempt.lease_until = datetime.now(UTC) - timedelta(seconds=1)
            if failure_path == "legacy_failed_child":
                command = session.scalar(select(GenericVoiceGenerationCommand).where(
                    GenericVoiceGenerationCommand.background_job_id == lease.fence.job_id
                ))
                assert command is not None
                command.state = "failed"
                command.completed_at = datetime.now(UTC)
            session.commit()
        scheduler = NarrationJobScheduler(
            factory,
            config=SchedulerConfig(lease_owner="tts56-recovery", job_kinds=(GENERIC_VOICE_JOB_KIND,)),
            terminalizers={GENERIC_VOICE_JOB_KIND: repository.terminalize_job_in_session},
        )
        scheduler.maintain_once()
    failed = service.get_load_resource()
    assert failed.pack.state == "failed"
    assert failed.command is not None and failed.command.terminal and failed.command.retryable
    assert failed.pack.prepared_slots == 1
    assert sum(slot.state == "failed" for slot in failed.pack.slots) == 1
    with factory() as session:
        repository.terminalize_job_in_session(session, job_id=lease.fence.job_id)
        session.commit()
    successor = service.retry(original.command.command_id)
    assert successor.pack.pack_version_id != original.pack.pack_version_id
    assert _draft_seeds(factory, successor.pack.pack_version_id) == _draft_seeds(factory, original.pack.pack_version_id)
    reused = next(slot for slot in successor.pack.slots if slot.slot_key == accepted.slot_key)
    assert reused.state == "reused" and reused.voice_version_id == accepted.voice_version_id
    with factory() as session:
        repository.terminalize_job_in_session(session, job_id=lease.fence.job_id)
        session.commit()
    assert service.get_load_resource().pack.state == "building"


def test_cancelled_running_job_does_not_revive_after_late_failure(
    generic_pack_pg: tuple[Connection, SessionFactory],
) -> None:
    _connection, factory = generic_pack_pg
    service = SqlAlchemyGenericVoicePackService(factory)
    original = service.build(idempotency_key="tts56-running-cancel")
    repository = SqlAlchemyGenericVoiceRepository(factory)
    work = repository.load_and_mark_generating(_claim_generic(factory))
    service.cancel(original.command.command_id)
    service.cancel(original.command.command_id)
    with factory() as session:
        assert session.get(BackgroundJob, work.lease.fence.job_id).state == "cancel_requested"
    repository.acknowledge_cancel(work)
    with pytest.raises(JobFenceError):
        repository.fail(work, state=VoiceGeneratorCommandState.FAILED_GENERATION, failure_code="LATE_FAILURE")
    cancelled = service.get_build_resource(original.command.command_id)
    assert cancelled.pack.state == "superseded" and cancelled.command.state == "cancelled"
    successor = service.build(idempotency_key="tts56-resume-cancelled")
    with factory() as session:
        repository.terminalize_job_in_session(session, job_id=work.lease.fence.job_id)
        session.commit()
    assert service.get_load_resource().pack.pack_version_id == successor.pack.pack_version_id
    assert service.get_load_resource().pack.state == "building"


@pytest.mark.asyncio
async def test_active_regeneration_is_atomic_bounded_and_replayable(
    generic_pack_pg: tuple[Connection, SessionFactory], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _connection, factory = generic_pack_pg
    service = SqlAlchemyGenericVoicePackService(factory)
    original = service.build(idempotency_key="tts56-active-original")
    processor = _processor(factory, tmp_path)
    for _ in range(24):
        await processor.process(_claim_generic(factory))
    active = service.get_load_resource().pack
    assert active.state == "active" and service.active_pack_ready()
    target = active.slots[0]
    expected = active.pack_version_id
    old_seeds = _draft_seeds(factory, expected)

    def fail_enqueue(*_args, **_kwargs):
        raise RuntimeError("injected successor enqueue failure")

    with monkeypatch.context() as patch:
        patch.setattr(pack_module, "_enqueue_next_slot", fail_enqueue)
        with pytest.raises(RuntimeError, match="injected successor"):
            service.regenerate(slot_key=target.slot_key, expected_pack_version_id=expected,
                               idempotency_key="tts56-atomic-regeneration")
    unchanged = service.get_load_resource().pack
    assert unchanged.state == "active" and unchanged.pack_version_id == expected
    assert unchanged.slots[0].state == "validated"
    assert service.active_pack_ready()
    with pytest.raises(ValueError):
        service.regenerate(slot_key=target.slot_key, expected_pack_version_id=expected, idempotency_key="a" * 129)
    assert service.get_load_resource().pack.state == "active"

    key = "a" * 128
    successor = service.regenerate(slot_key=target.slot_key, expected_pack_version_id=expected, idempotency_key=key)
    new_seeds = _draft_seeds(factory, successor.pack.pack_version_id)
    assert 0 <= new_seeds[target.slot_key] <= 2**63 - 1
    assert new_seeds[target.slot_key] not in set(old_seeds.values())
    assert {k: v for k, v in new_seeds.items() if k != target.slot_key} == {
        k: v for k, v in old_seeds.items() if k != target.slot_key
    }
    assert successor.pack.prepared_slots == 23
    assert successor.pack.slots[0].state == "generating"
    assert service.get_build_resource(original.command.command_id).pack.state == "retired_for_new_use"
    for old, new in zip(active.slots[1:], successor.pack.slots[1:], strict=True):
        assert new.state == "reused" and new.voice_version_id == old.voice_version_id
    with factory() as session:
        rows = tuple(session.scalars(select(GenericVoicePackVersionSlot).where(
            GenericVoicePackVersionSlot.pack_version_id == successor.pack.pack_version_id,
            GenericVoicePackVersionSlot.state == "reused",
        )))
        assert len(rows) == 23
        assert all(row.reference_audio_sha256 and row.validation_audio_sha256 for row in rows)
    replay = service.regenerate(slot_key=target.slot_key, expected_pack_version_id=expected, idempotency_key=key)
    assert replay.pack.pack_version_id == successor.pack.pack_version_id
    assert _draft_seeds(factory, replay.pack.pack_version_id) == new_seeds
    await processor.process(_claim_generic(factory))
    replay = service.regenerate(slot_key=target.slot_key, expected_pack_version_id=expected, idempotency_key=key)
    assert replay.pack.state == "active" and replay.pack.pack_version_id == successor.pack.pack_version_id
    assert replay.pack.slots[0].voice_version_id != target.voice_version_id
    with factory() as session:
        version = session.get(VoiceProfileVersion, replay.pack.slots[0].voice_version_id)
        assert version.seed == new_seeds[target.slot_key]
    with pytest.raises(InvalidNarrationState):
        service.regenerate(slot_key=target.slot_key, expected_pack_version_id=replay.pack.pack_version_id,
                           idempotency_key=key)
    with pytest.raises(InvalidNarrationState):
        service.regenerate(slot_key=target.slot_key, expected_pack_version_id=expected,
                           idempotency_key="tts56-stale-cas")
    assert service.active_pack_ready()

    second = service.regenerate(slot_key=target.slot_key, expected_pack_version_id=replay.pack.pack_version_id,
                                idempotency_key="tts56-second-explicit-regeneration")
    second_seed = _draft_seeds(factory, second.pack.pack_version_id)[target.slot_key]
    assert second_seed not in {old_seeds[target.slot_key], new_seeds[target.slot_key]}
    repository = SqlAlchemyGenericVoiceRepository(factory)
    work = repository.load_and_mark_generating(_claim_generic(factory))
    assert work.seed == work.host_request.seed == second_seed
    repository.fail(work, state=VoiceGeneratorCommandState.FAILED_GENERATION, failure_code="HOST_FAILURE")
    retry = service.retry(second.command.command_id)
    assert _draft_seeds(factory, retry.pack.pack_version_id)[target.slot_key] == second_seed


@pytest.mark.asyncio
@pytest.mark.parametrize("pack_state", ["building", "failed"])
async def test_regenerate_partial_pack_replaces_target_not_accepted_siblings(
    generic_pack_pg: tuple[Connection, SessionFactory], tmp_path: Path, pack_state: str
) -> None:
    _connection, factory = generic_pack_pg
    service = SqlAlchemyGenericVoicePackService(factory)
    service.build(idempotency_key=f"tts56-partial-{pack_state}")
    processor = _processor(factory, tmp_path)
    for _ in range(2):
        await processor.process(_claim_generic(factory))
    if pack_state == "failed":
        repo = SqlAlchemyGenericVoiceRepository(factory)
        work = repo.load_and_mark_generating(_claim_generic(factory))
        repo.fail(work, state=VoiceGeneratorCommandState.FAILED_GENERATION, failure_code="HOST_FAILURE")
    original = service.get_load_resource().pack
    assert original.state == pack_state
    target, kept = original.slots[:2]
    successor = service.regenerate(slot_key=target.slot_key, expected_pack_version_id=original.pack_version_id,
                                   idempotency_key=f"tts56-partial-replace-{pack_state}")
    assert successor.pack.pack_version_id != original.pack_version_id
    assert successor.pack.prepared_slots == 1
    assert successor.pack.slots[0].state == "generating"
    assert successor.pack.slots[0].voice_version_id is None
    assert successor.pack.slots[1].state == "reused"
    assert successor.pack.slots[1].voice_version_id == kept.voice_version_id
    await processor.process(_claim_generic(factory))
    assert service.get_load_resource().pack.slots[0].voice_version_id != target.voice_version_id


@pytest.mark.asyncio
async def test_explicit_reject_then_continue_changes_only_rejected_seed(
    generic_pack_pg: tuple[Connection, SessionFactory], tmp_path: Path,
) -> None:
    _connection, factory = generic_pack_pg
    service = SqlAlchemyGenericVoicePackService(factory)
    service.build(idempotency_key="tts56-reject-continue-original")
    processor = _processor(factory, tmp_path)
    for _ in range(2):
        await processor.process(_claim_generic(factory))
    original = service.get_load_resource().pack
    target = original.slots[0]
    original_seeds = _draft_seeds(factory, original.pack_version_id)
    service.reject(slot_key=target.slot_key, expected_pack_version_id=original.pack_version_id)
    successor = service.retry(original.pack_version_id)
    seeds = _draft_seeds(factory, successor.pack.pack_version_id)
    assert seeds[target.slot_key] != original_seeds[target.slot_key]
    assert successor.pack.slots[1].state == "reused"
    assert seeds[original.slots[1].slot_key] == original_seeds[original.slots[1].slot_key]
    assert service.retry(original.pack_version_id).pack.pack_version_id == successor.pack.pack_version_id
    await processor.process(_claim_generic(factory))
    assert service.get_load_resource().pack.slots[0].voice_version_id != target.voice_version_id


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_first_builds_return_one_durable_command(same_key: bool) -> None:
    # This test needs committed visibility and an exclusive disposable database,
    # not the single-connection savepoint fixture.  Clean only these exact IDs.
    engine = create_engine(
        _live_url(), pool_pre_ping=True,
        connect_args={"options": "-c statement_timeout=15000 -c lock_timeout=10000"},
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    keys = [f"tts56-concurrent:{uuid4()}", f"tts56-concurrent:{uuid4()}"]
    if same_key:
        keys[1] = keys[0]
    ids = tuple(uuid5(LOCAL_WORKSPACE_ID, f"generic-voice-pack-build/1:{key}") for key in keys)
    with engine.connect() as connection:
        assert_database_at_repository_head(connection)
        assert connection.scalar(select(text("count(*)")).select_from(GenericVoicePackVersion)) == 0, (
            "concurrent generic-pack test requires an exclusively assigned empty disposable database"
        )
    barrier = Barrier(2)

    def build(key: str):
        barrier.wait(timeout=10)
        return SqlAlchemyGenericVoicePackService(factory).build(idempotency_key=key)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(build, keys))
        assert results[0].command.command_id == results[1].command.command_id
        with factory() as session:
            assert session.scalar(select(text("count(*)")).select_from(GenericVoicePackVersion)) == 1
            assert session.scalar(select(text("count(*)")).select_from(GenericVoiceGenerationCommand)) == 1
        repository = SqlAlchemyGenericVoiceRepository(factory)
        work = repository.load_and_mark_generating(_claim_generic(factory))
        race = Barrier(2)

        def cancel_or_fail(action: str) -> str:
            race.wait(timeout=10)
            try:
                if action == "cancel":
                    SqlAlchemyGenericVoicePackService(factory).cancel(results[0].command.command_id)
                else:
                    repository.fail(work, state=VoiceGeneratorCommandState.FAILED_GENERATION,
                                    failure_code="CONCURRENT_HOST_FAILURE")
                return "completed"
            except (InvalidNarrationState, JobFenceError):
                # The other action won its authoritative fence.
                return "fenced"

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(cancel_or_fail, ("cancel", "fail")))
        assert "completed" in outcomes
        with factory() as session:
            cancellation_pending = session.get(BackgroundJob, work.lease.fence.job_id).state == "cancel_requested"
        if cancellation_pending:
            repository.acknowledge_cancel(work)
        settled = SqlAlchemyGenericVoicePackService(factory).get_load_resource()
        assert settled.command.terminal and settled.pack.state in {"failed", "superseded"}
    finally:
        with factory() as session:
            commands = tuple(session.scalars(select(GenericVoiceGenerationCommand).where(
                GenericVoiceGenerationCommand.pack_version_id.in_(ids)
            )))
            jobs = tuple(command.background_job_id for command in commands)
            drafts = tuple(session.scalars(select(GenericVoicePackVersionSlot.design_draft_id).where(
                GenericVoicePackVersionSlot.pack_version_id.in_(ids)
            )))
            assert all(command.state in {"queued", "cancelled", "failed"}
                       and command.voice_version_id is None for command in commands)
            session.execute(text("SET LOCAL session_replication_role=replica"))
            session.execute(delete(GenericVoicePackVersionSlot).where(GenericVoicePackVersionSlot.pack_version_id.in_(ids)))
            session.execute(delete(GenericVoiceGenerationCommand).where(GenericVoiceGenerationCommand.pack_version_id.in_(ids)))
            session.execute(delete(BackgroundJobAttempt).where(BackgroundJobAttempt.job_id.in_(jobs)))
            session.execute(delete(BackgroundJob).where(BackgroundJob.id.in_(jobs)))
            session.execute(delete(GenericVoicePackVersion).where(GenericVoicePackVersion.id.in_(ids)))
            session.execute(delete(GenericVoiceDesignDraft).where(GenericVoiceDesignDraft.id.in_(drafts)))
            session.commit()
        engine.dispose()
