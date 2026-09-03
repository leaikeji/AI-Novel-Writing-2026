from __future__ import annotations

from array import array
import hashlib
import io
import os
from collections.abc import Callable, Iterator
from pathlib import Path
from uuid import UUID, uuid4
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
    NarrationRequestScope,
    SynthesisRequest,
    SynthesisResult,
)
from backend.narration.jobs import claim_next_job
from backend.narration.generic_voice_pack_service import (
    SqlAlchemyGenericVoicePackService,
    SqlAlchemyGenericVoiceRepository,
    resolve_generic_voice_slot_media,
)
from backend.narration.generic_voice_generation import GENERIC_VOICE_JOB_KIND
from backend.narration.runtime import EXPECTED_PRODUCTION_MODEL_FINGERPRINT
from backend.narration.services import NarrationNotFound
from backend.narration.storage import NarrationStorage
from backend.narration.voice_generator_processor import VoiceGeneratorProcessor
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
