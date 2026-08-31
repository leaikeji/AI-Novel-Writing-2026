from __future__ import annotations

from array import array
import hashlib
import io
import os
from pathlib import Path
from typing import Callable
from uuid import UUID, uuid4
import wave

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import Connection, Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from backend.models import (
    MediaAsset,
    ModelRunRecord,
    Novel,
    NovelCharacter,
    VoiceDesignDraft,
    VoiceGeneratorCommand,
    VoiceGeneratorRunEvidence,
    VoiceProfile,
)
from backend.narration.character_voice_matching import CharacterVoiceBrief
from backend.narration import schemas as wire
from backend.narration.contracts import (
    NarrationRequestScope,
    SynthesisRequest,
    SynthesisResult,
)
from backend.narration.jobs import claim_next_job
from backend.narration.official_presets import OFFICIAL_PRESETS
from backend.narration.official_voice_selection import OfficialVoiceSelectionService
from backend.narration.runtime import EXPECTED_PRODUCTION_MODEL_FINGERPRINT
from backend.narration.storage import NarrationStorage
from backend.narration.voice_deletion import (
    VoiceDeletionService,
    compute_voice_deletion_impact,
)
from backend.narration.voice_generator_processor import (
    SqlAlchemyVoiceGeneratorRepository,
    VoiceGeneratorProcessor,
)
from backend.narration.voice_generator_runtime import (
    EXPECTED_RUNTIME_FINGERPRINT,
    EXPECTED_RUNTIME_IDENTITY,
    HostGenerationReceipt,
    VoiceGeneratorAudioResult,
    VoiceGeneratorHostHealth,
    VoiceGeneratorHostRequest,
    inspect_generated_wav,
)
from backend.narration.voice_generator_service import (
    SqlAlchemyVoiceGeneratorService,
    VoiceGeneratorAnalysis,
    VoiceGeneratorCommandState,
)
from tests.narration.digest_fixtures import TEST_DIGEST_KEYRING


EXPECTED_DATABASE = "ai_novel_world_2026_tts_test"
EXPECTED_HEAD = "20260830_0035"
SCOPE = NarrationRequestScope.fixed_local()
SessionFactory = Callable[[], Session]


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
            "VoiceGenerator tests require the exact loopback disposable TTS database"
        )
    production = os.environ.get("AI_NOVEL_DATABASE_URL", "").strip()
    if production:
        current = make_url(production)
        if (parsed.host, parsed.port, parsed.database) == (
            current.host,
            current.port,
            current.database,
        ):
            raise RuntimeError("VoiceGenerator test database must differ from production")
    return raw


@pytest.fixture
def vg_pg_runtime() -> tuple[Connection, SessionFactory]:
    engine: Engine = create_engine(_live_url(), pool_pre_ping=True)
    connection = engine.connect()
    outer = connection.begin()
    if connection.scalar(text("SELECT version_num FROM alembic_version")) != EXPECTED_HEAD:
        outer.rollback()
        connection.close()
        engine.dispose()
        raise RuntimeError("VoiceGenerator PostgreSQL tests require exact head 0035")
    required = {
        "voice_design_drafts",
        "voice_generator_commands",
        "voice_generator_run_evidence",
    }
    if not required <= set(inspect(connection).get_table_names()):
        outer.rollback()
        connection.close()
        engine.dispose()
        raise RuntimeError("VoiceGenerator PostgreSQL schema is incomplete")
    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        yield connection, factory
    finally:
        if outer.is_active:
            outer.rollback()
        connection.close()
        engine.dispose()


def _seed(factory: SessionFactory) -> tuple[UUID, UUID]:
    novel_id, character_id = uuid4(), uuid4()
    with factory() as session:
        session.add(
            Novel(
                id=novel_id,
                title="雾港来信",
                author_name="",
                description="",
                writing_type="long",
                audience="",
                genre="悬疑",
                subgenre="刑侦",
                idea="",
                template_name="",
                template_data={},
                cover_mode="none",
                cover_image_data="",
                outline_target_chapters=4,
                highlight="",
                background="",
                main_plot="",
                story_ledger_version=1,
                character_catalog_version=1,
                version=1,
            )
        )
        session.add(
            NovelCharacter(
                id=character_id,
                novel_id=novel_id,
                role_type="protagonist",
                name="沈砚",
                description="",
                details={},
                lifecycle_state="active",
                archived_at=None,
                position=1,
                version=1,
            )
        )
        session.commit()
    return novel_id, character_id


def _analysis() -> VoiceGeneratorAnalysis:
    return VoiceGeneratorAnalysis(
        character_version=1,
        character_catalog_version=1,
        workspace_digest=hashlib.sha256(b"workspace").hexdigest(),
        brief=CharacterVoiceBrief(
            language=None,
            presentation=None,
            pitch=None,
            pace=None,
            energy=None,
            texture=None,
            evidence_fields=(),
        ),
        instruction="声音克制、清晰，节奏沉稳。",
        model_evidence={
            "schema_version": "model-execution-evidence/1",
            "requested_model_id": "ai-novel-writer",
            "actual_model_id": "ai-novel-writer",
        },
        language="zh-CN",
        seed=104729,
    )


def _reserve_and_analyze(
    factory: SessionFactory, novel_id: UUID, character_id: UUID
) -> tuple[SqlAlchemyVoiceGeneratorService, UUID, UUID]:
    service = SqlAlchemyVoiceGeneratorService(
        factory, digest_keyring=TEST_DIGEST_KEYRING
    )
    reservation = service.reserve(
        novel_id=novel_id,
        character_id=character_id,
        expected_binding_version=0,
        idempotency_key=f"voice-generator-pg:{uuid4()}",
        request_hash=hashlib.sha256(b"request").hexdigest(),
    )
    assert service.begin_analysis(
        novel_id=novel_id, command_id=reservation.command_id
    )
    job_id = service.finish_analysis(
        novel_id=novel_id,
        command_id=reservation.command_id,
        analysis=_analysis(),
    )
    assert job_id is not None
    return service, reservation.command_id, job_id


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
                "started_at": "2026-08-30T08:00:00Z",
                "completed_at": "2026-08-30T08:01:00Z",
            }
        )

    async def create(
        self, request: VoiceGeneratorHostRequest
    ) -> HostGenerationReceipt:
        return self._receipt(request)

    async def get(self, request: VoiceGeneratorHostRequest) -> HostGenerationReceipt:
        return self._receipt(request)

    async def cancel(
        self, request: VoiceGeneratorHostRequest
    ) -> HostGenerationReceipt:
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


class _FailedHost(_Host):
    async def create(
        self, request: VoiceGeneratorHostRequest
    ) -> HostGenerationReceipt:
        return HostGenerationReceipt.from_wire(
            {
                "protocol_version": "moss-voice-generator-host/1",
                "request_id": str(request.request_id),
                "request_digest": request.request_digest,
                "status": "failed",
                "terminal": True,
                "cancellable": False,
                "retryable": True,
                "failure_code": "GENERATOR_PROCESS_FAILED",
                "runtime_identity": EXPECTED_RUNTIME_IDENTITY.wire_payload(),
                "runtime_fingerprint": EXPECTED_RUNTIME_FINGERPRINT,
                "token_sha256": None,
                "audio_sha256": None,
                "audio_size_bytes": None,
                "memory_summary": None,
                "started_at": "2026-08-30T08:00:00Z",
                "completed_at": "2026-08-30T08:00:01Z",
            }
        )


def _claim(factory: SessionFactory, job_id: UUID):
    with factory() as session:
        lease = claim_next_job(
            session,
            scope=SCOPE,
            lease_owner=f"voice-generator-pg:{uuid4()}",
            resource_classes=("moss-nano",),
            job_kinds=("narration.voice_generate",),
            lease_seconds=900,
        )
        assert lease is not None and lease.fence.job_id == job_id
        session.commit()
        return lease


def test_generator_work_item_is_idempotently_recoverable_after_dispatch_crash(
    vg_pg_runtime: tuple[Connection, SessionFactory],
) -> None:
    _, factory = vg_pg_runtime
    novel_id, character_id = _seed(factory)
    _, command_id, job_id = _reserve_and_analyze(factory, novel_id, character_id)
    lease = _claim(factory, job_id)
    repository = SqlAlchemyVoiceGeneratorRepository(
        factory, digest_keyring=TEST_DIGEST_KEYRING
    )

    first = repository.load_and_mark_generating(lease)
    resumed = repository.load_and_mark_generating(lease)

    assert first.command_id == resumed.command_id == command_id
    assert resumed.host_request.request_id == first.host_request.request_id
    assert resumed.host_request.instruction_digest == hashlib.sha256(
        resumed.host_request.instruction.encode("utf-8")
    ).hexdigest()


@pytest.mark.asyncio
async def test_generated_voice_publishes_two_model_runs_and_enters_deletion_lifecycle(
    vg_pg_runtime: tuple[Connection, SessionFactory], tmp_path: Path
) -> None:
    _, factory = vg_pg_runtime
    novel_id, character_id = _seed(factory)
    service, command_id, job_id = _reserve_and_analyze(
        factory, novel_id, character_id
    )
    lease = _claim(factory, job_id)
    models_root, media_root = tmp_path / "models", tmp_path / "media"
    models_root.mkdir(mode=0o700)
    media_root.mkdir(mode=0o700)
    storage = NarrationStorage(models_root=models_root, media_root=media_root)
    repository = SqlAlchemyVoiceGeneratorRepository(
        factory, digest_keyring=TEST_DIGEST_KEYRING
    )

    await VoiceGeneratorProcessor(
        repository=repository,
        host=_Host(),
        nano_adapter=_Nano(),  # type: ignore[arg-type]
        storage=storage,
        digest_keyring=TEST_DIGEST_KEYRING,
        poll_seconds=0.01,
    ).process(lease)

    resource = service.get_resource(novel_id=novel_id, command_id=command_id)
    assert resource.state == VoiceGeneratorCommandState.READY_APPLIED.value, (
        resource.failure_code
    )
    assert resource.selection_still_current is True
    assert resource.voice_profile_id is not None
    with factory() as session:
        command = session.get(VoiceGeneratorCommand, command_id)
        assert command is not None
        assert session.scalar(
            select(text("count(*)")).select_from(ModelRunRecord).where(
                ModelRunRecord.attempt_id == lease.fence.attempt_id
            )
        ) == 2
        assert session.scalar(
            select(text("count(*)")).select_from(VoiceGeneratorRunEvidence).where(
                VoiceGeneratorRunEvidence.command_id == command_id
            )
        ) == 1
        evidence = session.scalar(
            select(VoiceGeneratorRunEvidence).where(
                VoiceGeneratorRunEvidence.command_id == command_id
            )
        )
        draft = session.get(VoiceDesignDraft, command.draft_id)
        assert evidence is not None and draft is not None
        assert evidence.instruction_digest == draft.instruction_digest
        assert evidence.instruction_digest != hashlib.sha256(
            draft.instruction.encode("utf-8")
        ).hexdigest()
        assert session.scalar(
            select(text("count(*)")).select_from(MediaAsset).where(
                MediaAsset.id.in_(
                    (
                        command.generated_reference_asset_id,
                        command.nano_validation_asset_id,
                    )
                )
            )
        ) == 2
        impact = compute_voice_deletion_impact(
            session, novel_id, resource.voice_profile_id
        )
        assert len(impact.asset_roles) == 2
        assert impact.character_binding_count == 1
        assert impact.active_job_ids == ()

    with factory() as session:
        profile = session.get(VoiceProfile, resource.voice_profile_id)
        assert profile is not None
        profile_version = profile.version
    deletion = VoiceDeletionService(
        factory,
        storage=storage,
        digest_keyring=TEST_DIGEST_KEYRING,
    )
    deletion_request = deletion.create_request(
        novel_id=novel_id,
        profile_id=resource.voice_profile_id,
        expected_profile_version=profile_version,
        idempotency_key=f"voice-generator-delete:{uuid4()}",
        actor="local-owner",
    )
    assert deletion_request.state == "requested"
    deleted = deletion.confirm(
        novel_id=novel_id,
        request_id=deletion_request.request_id,
        expected_profile_version=profile_version,
        impact_digest=deletion_request.impact_digest,
        actor="local-owner",
    )
    assert deleted.terminal is True
    with factory() as session:
        profile = session.get(VoiceProfile, resource.voice_profile_id)
        assert profile is not None and profile.status == "unavailable"
        command = session.get(VoiceGeneratorCommand, command_id)
        assert command is not None
        assets = tuple(
            session.scalars(
                select(MediaAsset).where(
                    MediaAsset.id.in_(
                        (
                            command.generated_reference_asset_id,
                            command.nano_validation_asset_id,
                        )
                    )
                )
            )
        )
        assert len(assets) == 2
        assert {asset.state for asset in assets} == {"deleted"}


def test_character_change_supersedes_before_a_heavy_job_is_enqueued(
    vg_pg_runtime: tuple[Connection, SessionFactory]
) -> None:
    _, factory = vg_pg_runtime
    novel_id, character_id = _seed(factory)
    service = SqlAlchemyVoiceGeneratorService(
        factory, digest_keyring=TEST_DIGEST_KEYRING
    )
    reservation = service.reserve(
        novel_id=novel_id,
        character_id=character_id,
        expected_binding_version=0,
        idempotency_key=f"voice-generator-pg:{uuid4()}",
        request_hash=hashlib.sha256(b"supersede").hexdigest(),
    )
    assert service.begin_analysis(
        novel_id=novel_id, command_id=reservation.command_id
    )
    with factory() as session:
        character = session.get(NovelCharacter, character_id)
        assert character is not None
        character.version += 1
        session.commit()

    assert service.finish_analysis(
        novel_id=novel_id,
        command_id=reservation.command_id,
        analysis=_analysis(),
    ) is None
    resource = service.get_resource(
        novel_id=novel_id, command_id=reservation.command_id
    )
    assert resource.state == VoiceGeneratorCommandState.SUPERSEDED.value
    assert resource.background_job_id is None
    assert resource.retryable is True


@pytest.mark.asyncio
async def test_binding_cas_drift_keeps_generated_voice_without_overwriting_author_choice(
    vg_pg_runtime: tuple[Connection, SessionFactory], tmp_path: Path
) -> None:
    _, factory = vg_pg_runtime
    novel_id, character_id = _seed(factory)
    service, command_id, job_id = _reserve_and_analyze(
        factory, novel_id, character_id
    )
    lease = _claim(factory, job_id)
    official = OfficialVoiceSelectionService(factory).select_official_voice(
        novel_id=novel_id,
        request=wire.OfficialVoiceSelectionRequest(
            preset_id=OFFICIAL_PRESETS[0].preset_id,
            target_kind="character",
            character_id=character_id,
            expected_settings_version=0,
            expected_binding_version=0,
        ),
        idempotency_key=f"voice-generator-cas-drift:{uuid4()}",
    )
    assert official.frozen_result.binding_version == 1
    models_root, media_root = tmp_path / "models", tmp_path / "media"
    models_root.mkdir(mode=0o700)
    media_root.mkdir(mode=0o700)
    storage = NarrationStorage(models_root=models_root, media_root=media_root)

    await VoiceGeneratorProcessor(
        repository=SqlAlchemyVoiceGeneratorRepository(
            factory, digest_keyring=TEST_DIGEST_KEYRING
        ),
        host=_Host(),
        nano_adapter=_Nano(),  # type: ignore[arg-type]
        storage=storage,
        digest_keyring=TEST_DIGEST_KEYRING,
        poll_seconds=0.01,
    ).process(lease)

    resource = service.get_resource(novel_id=novel_id, command_id=command_id)
    assert resource.state == VoiceGeneratorCommandState.READY_UNAPPLIED.value
    assert resource.voice_version_id is not None
    assert resource.selection_still_current is False
    assert resource.current_character_binding.version == 1
    assert resource.current_character_binding.version_id == (
        official.frozen_result.version_id
    )


@pytest.mark.asyncio
async def test_failed_host_attempt_keeps_immutable_failure_evidence(
    vg_pg_runtime: tuple[Connection, SessionFactory], tmp_path: Path
) -> None:
    _, factory = vg_pg_runtime
    novel_id, character_id = _seed(factory)
    service, command_id, job_id = _reserve_and_analyze(
        factory, novel_id, character_id
    )
    lease = _claim(factory, job_id)
    models_root, media_root = tmp_path / "models", tmp_path / "media"
    models_root.mkdir(mode=0o700)
    media_root.mkdir(mode=0o700)

    await VoiceGeneratorProcessor(
        repository=SqlAlchemyVoiceGeneratorRepository(
            factory, digest_keyring=TEST_DIGEST_KEYRING
        ),
        host=_FailedHost(),
        nano_adapter=_Nano(),  # type: ignore[arg-type]
        storage=NarrationStorage(
            models_root=models_root,
            media_root=media_root,
        ),
        digest_keyring=TEST_DIGEST_KEYRING,
        poll_seconds=0.01,
    ).process(lease)

    resource = service.get_resource(novel_id=novel_id, command_id=command_id)
    assert resource.state == VoiceGeneratorCommandState.FAILED_GENERATION.value
    assert resource.failure_code == "GENERATOR_PROCESS_FAILED"
    assert resource.retryable is True
    with factory() as session:
        evidence = session.scalar(
            select(VoiceGeneratorRunEvidence).where(
                VoiceGeneratorRunEvidence.command_id == command_id
            )
        )
        assert evidence is not None
        assert evidence.result_classification == "retryable_failure"
        assert evidence.exit_reason_code == "GENERATOR_PROCESS_FAILED"
        model_run = session.get(ModelRunRecord, evidence.model_run_id)
        assert model_run is not None
        assert model_run.result_classification == "retryable_failure"
        assert model_run.output_digest is None
