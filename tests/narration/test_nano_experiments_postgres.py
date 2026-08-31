"""PostgreSQL closure tests for the Nano advanced-tuning state machine.

The test is opt-in and accepts only the exact loopback disposable TTS database.
Every service commit is joined to one outer transaction that is rolled back, so
the suite exercises real 0034 triggers without leaving test novels or media rows.
"""

from __future__ import annotations

import hashlib
import io
import os
from dataclasses import replace
from pathlib import Path
import socket
from typing import Callable
from uuid import UUID, uuid4
import wave

import pytest
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.engine import Connection, Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from backend.models import (
    BackgroundJob,
    MediaAsset,
    ModelRunRecord,
    NanoVoiceExperimentCommand as NanoVoiceExperimentCommandRow,
    Novel,
    NovelNarrationSettings,
    VoicePreview,
    VoiceProfile,
    VoiceProfileVersion,
)
from backend.narration.contracts import NarrationRequestScope
from backend.narration.jobs import JobLease, claim_next_job
from backend.narration.nano_experiment_runtime import (
    SidecarNanoExperimentSynthesizer,
    SqlAlchemyNanoExperimentStore,
    build_nano_experiment_validation_input,
)
from backend.narration.nano_experiments import (
    NanoDecodeParametersV3,
    NanoExperimentApplyRequest,
    NanoExperimentProcessor,
    NanoExperimentService,
    NanoExperimentStateError,
    NanoExperimentSynthesisRequest,
    NanoExperimentSynthesisResult,
    NanoExperimentTarget,
    NanoModelRunEvidence,
    StrictNanoExperimentValidator,
    production_nano_experiment_identity,
)
from backend.narration.privacy import _storage_settings, get_narration_settings
from backend.narration.runtime import SidecarMossNanoTTSAdapter, SidecarRuntimeConfig
from backend.narration.services import SqlAlchemyNarrationStore
from backend.narration.settings import NarrationSettingsUpdate, update_settings
from backend.narration.storage import NarrationStorage
from backend.narration.voice_product import VoicePreviewPolicy
from backend.narration.voice_deletion import VoiceDeletionService
from tests.narration.digest_fixtures import TEST_DIGEST_KEYRING


EXPECTED_DATABASE = "ai_novel_world_2026_tts_test"
EXPECTED_USER = "tts_test"
EXPECTED_HEAD = "20260829_0034"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
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
        or parsed.username != EXPECTED_USER
        or parsed.host not in LOOPBACK_HOSTS
    ):
        raise RuntimeError(
            "Nano experiment tests require the exact loopback disposable TTS database"
        )
    production = os.environ.get("AI_NOVEL_DATABASE_URL", "").strip()
    if production:
        prod = make_url(production)
        if (parsed.host, parsed.port, parsed.database) == (
            prod.host,
            prod.port,
            prod.database,
        ):
            raise RuntimeError("Nano experiment test database must differ from production")
    return raw


@pytest.fixture
def nano_pg_runtime() -> tuple[Connection, SessionFactory]:
    engine: Engine = create_engine(_live_url(), pool_pre_ping=True)
    connection = engine.connect()
    outer = connection.begin()
    required_tables = {
        "nano_voice_experiment_commands",
        "voice_profile_versions",
        "voice_previews",
        "model_run_records",
        "background_jobs",
    }
    if not required_tables <= set(inspect(connection).get_table_names()):
        outer.rollback()
        connection.close()
        engine.dispose()
        raise RuntimeError("disposable TTS database lacks the 0034 experiment schema")
    if connection.scalar(text("SELECT version_num FROM alembic_version")) != EXPECTED_HEAD:
        outer.rollback()
        connection.close()
        engine.dispose()
        raise RuntimeError("Nano experiment PostgreSQL tests require exact head 0034")
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


def _wav_bytes(*, duration_ms: int = 600) -> bytes:
    frames = 48_000 * duration_ms // 1_000
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setframerate(48_000)
        writer.setnchannels(2)
        writer.setsampwidth(2)
        writer.writeframes(b"\x01\x00\x01\x00" * frames)
    return output.getvalue()


class ValidSynthesizer:
    def __init__(self) -> None:
        self.requests: list[NanoExperimentSynthesisRequest] = []

    async def synthesize(
        self, request: NanoExperimentSynthesisRequest
    ) -> NanoExperimentSynthesisResult:
        self.requests.append(request)
        audio = _wav_bytes()
        digest = hashlib.sha256(audio).hexdigest()
        asset_id = uuid4()
        identity = request.model_identity
        return NanoExperimentSynthesisResult(
            command_id=request.command_id,
            attempt_id=request.attempt_id,
            audio_bytes=audio,
            output_sha256=digest,
            sample_rate_hz=48_000,
            channels=2,
            sample_width_bytes=2,
            duration_ms=600,
            sidecar_protocol_version=identity.sidecar_protocol_version,
            postprocess_fingerprint=identity.postprocess_fingerprint,
            preview_id=request.preview_id,
            result_asset_id=asset_id,
            published_relative_path=(
                f"assets/{asset_id.hex[:2]}/{asset_id.hex}/{digest}.wav"
            ),
            published_byte_size=len(audio),
            model_run=NanoModelRunEvidence(
                model_run_id=uuid4(),
                attempt_id=request.attempt_id,
                requested_provider_id=identity.requested_provider_id,
                requested_model_id=identity.requested_model_id,
                requested_revision=identity.requested_revision,
                actual_provider_id=identity.actual_provider_id,
                actual_model_id=identity.actual_model_id,
                actual_revision=identity.actual_revision,
                model_fingerprint_sha256=identity.model_fingerprint_sha256,
                parameters_digest=request.parameters_digest,
                input_digest_key_id=request.input_digest_key_id,
                input_digest=request.input_digest,
                output_digest=digest,
                result_classification="success",
            ),
        )


class NeverSynthesizer:
    async def synthesize(
        self, request: NanoExperimentSynthesisRequest
    ) -> NanoExperimentSynthesisResult:
        raise AssertionError(f"reusable command unexpectedly synthesized {request.command_id}")


class StagedVoiceDeletionService(VoiceDeletionService):
    """Expose the physical fence boundary to the outer-transaction fixture."""

    _test_novel_id: UUID

    def _execute_and_notify(self, request_id: UUID, *, actor: str):  # type: ignore[no-untyped-def]
        return self.get_request(
            novel_id=self._test_novel_id,
            request_id=request_id,
        )


class FailOnRestartLifecycle:
    async def restart_after_poison(
        self,
        reason_code: str,
        *,
        previous_generation: int | None = None,
    ) -> None:
        raise AssertionError(
            "isolated real Nano acceptance must not need a restart: "
            f"{reason_code}/{previous_generation}"
        )


class CapturingSynthesizer:
    def __init__(self, delegate: SidecarNanoExperimentSynthesizer) -> None:
        self._delegate = delegate
        self.requests: list[NanoExperimentSynthesisRequest] = []
        self.results: list[NanoExperimentSynthesisResult] = []
        self.error: BaseException | None = None

    async def synthesize(
        self, request: NanoExperimentSynthesisRequest
    ) -> NanoExperimentSynthesisResult:
        self.requests.append(request)
        try:
            result = await self._delegate.synthesize(request)
        except BaseException as error:
            self.error = error
            raise
        self.results.append(result)
        return result


def _seed_novel(factory: SessionFactory) -> UUID:
    novel_id = uuid4()
    with factory() as session:
        session.add(
            Novel(
                id=novel_id,
                owner_id=SCOPE.owner_id,
                workspace_id=SCOPE.workspace_id,
                title="Nano 高级调音 PostgreSQL 闭环测试",
                author_name="本地测试",
                description="",
                writing_type="long",
                audience="",
                genre="",
                subgenre="",
                idea="",
                template_name="",
                template_data={},
                cover_mode="system",
                cover_image_data="",
                outline_target_chapters=200,
                highlight="",
                background="",
                main_plot="",
            )
        )
        session.commit()
    return novel_id


def _parts(
    factory: SessionFactory,
) -> tuple[SqlAlchemyNanoExperimentStore, NanoExperimentService]:
    identity = production_nano_experiment_identity()
    store = SqlAlchemyNanoExperimentStore(
        factory,
        digest_keyring=TEST_DIGEST_KEYRING,
        preview_policy=VoicePreviewPolicy(
            expected_model_fingerprint=identity.model_fingerprint_sha256,
            requested_provider_id=identity.requested_provider_id,
            requested_model_id=identity.requested_model_id,
            requested_revision=identity.requested_revision,
        ),
    )
    service = NanoExperimentService(
        repository=store,
        binder=store,
        validation_input=build_nano_experiment_validation_input(
            TEST_DIGEST_KEYRING
        ),
        model_identity=identity,
    )
    return store, service


def _real_nano_token_file() -> Path:
    raw = os.environ.get("TTS_REAL_NANO_TOKEN_FILE", "").strip()
    if not raw:
        pytest.skip("TTS_REAL_NANO_TOKEN_FILE is not configured")
    path = Path(raw)
    if not path.is_absolute():
        raise RuntimeError("TTS_REAL_NANO_TOKEN_FILE must be an absolute path")
    return path


def _claim(factory: SessionFactory, *, job_id: UUID) -> JobLease:
    with factory() as session:
        lease = claim_next_job(
            session,
            scope=SCOPE,
            lease_owner=f"nano-pg-{uuid4()}",
            resource_classes=("moss-nano",),
            job_kinds=("narration.voice_preview",),
            lease_seconds=900,
        )
        assert lease is not None
        assert lease.fence.job_id == job_id
        assert lease.resource_fence is not None
        session.commit()
        return lease


def _force_deferred_closure(connection: Connection) -> None:
    connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))


def _processor(
    store: SqlAlchemyNanoExperimentStore,
    synthesizer: object,
) -> NanoExperimentProcessor:
    return NanoExperimentProcessor(
        repository=store,
        synthesizer=synthesizer,  # type: ignore[arg-type]
        validator=StrictNanoExperimentValidator(),
        binder=store,
    )


def _advance_settings(factory: SessionFactory, *, novel_id: UUID) -> int:
    with factory() as session:
        store = SqlAlchemyNarrationStore(session)
        current = get_narration_settings(store, novel_id=novel_id)
        update_settings(
            store,
            NarrationSettingsUpdate(
                novel_id=novel_id,
                script_review_policy=current.values.script_review_policy.value,
                analysis_mode=current.values.analysis_mode.value,
                settings_json=_storage_settings(current.values),
                expected_version=current.version,
                narrator_profile_id=(
                    current.values.narrator.profile_id
                    if current.values.narrator is not None
                    else None
                ),
                narrator_version_id=(
                    current.values.narrator.version_id
                    if current.values.narrator is not None
                    else None
                ),
            ),
        )
        session.commit()
        return current.version + 1


@pytest.mark.asyncio
async def test_real_0034_success_reuse_and_cas_drift_close_atomically(
    nano_pg_runtime: tuple[Connection, SessionFactory],
) -> None:
    connection, factory = nano_pg_runtime
    novel_id = _seed_novel(factory)
    store, service = _parts(factory)
    default_parameters = NanoDecodeParametersV3()

    first = service.create(
        novel_id=novel_id,
        base_preset_id="onnx.Zhiming",
        target=NanoExperimentTarget("narrator", None, 0, None),
        parameters=default_parameters,
        idempotency_key=f"nano-pg-first-{uuid4()}",
    )
    _force_deferred_closure(connection)
    first_synthesizer = ValidSynthesizer()
    first_lease = _claim(factory, job_id=first.command.background_job_id)
    _force_deferred_closure(connection)
    first_outcome = await _processor(store, first_synthesizer).process(
        first_lease
    )
    assert first_outcome.status == "succeeded"
    assert first_outcome.command is not None
    assert first_outcome.command.state == "ready_applied"
    assert first_outcome.command.reused_version is False
    assert len(first_synthesizer.requests) == 1

    with factory() as session:
        settings = session.scalar(
            select(NovelNarrationSettings).where(
                NovelNarrationSettings.novel_id == novel_id
            )
        )
        version = session.get(VoiceProfileVersion, first.command.version_id)
        preview = session.get(VoicePreview, first.command.preview_id)
        job = session.get(BackgroundJob, first.command.background_job_id)
        assert settings is not None and settings.version == 1
        assert settings.narrator_profile_id == first.command.profile_id
        assert settings.narrator_version_id == first.command.version_id
        assert version is not None
        assert version.state == "locked"
        assert version.activation_basis == "experimental_machine_validated"
        assert version.validation_basis == "machine_validated"
        assert version.quality_state == "accepted"
        assert version.model_run_id is not None
        assert preview is not None and preview.status == "ready"
        assert preview.preview_text is None and preview.result_asset_id is not None
        asset = session.get(MediaAsset, preview.result_asset_id)
        run = session.get(ModelRunRecord, version.model_run_id)
        assert asset is not None and run is not None
        assert asset.content_hash == run.output_digest
        assert run.parameters_digest == first.command.parameters_digest
        assert job is not None and job.state == "succeeded"

    reused = service.create(
        novel_id=novel_id,
        base_preset_id="onnx.Zhiming",
        target=NanoExperimentTarget("narrator", None, 1, None),
        parameters=default_parameters,
        idempotency_key=f"nano-pg-reuse-{uuid4()}",
    )
    _force_deferred_closure(connection)
    reused_lease = _claim(factory, job_id=reused.command.background_job_id)
    _force_deferred_closure(connection)
    reused_outcome = await _processor(store, NeverSynthesizer()).process(
        reused_lease
    )
    assert reused_outcome.status == "succeeded", reused_outcome
    assert reused_outcome.command is not None
    assert reused_outcome.command.state == "ready_applied"
    assert reused_outcome.command.reused_version is True
    assert reused_outcome.command.version_id == first.command.version_id

    custom_parameters = replace(
        default_parameters,
        seed=9_876,
        text_temperature_milli=1_150,
        text_top_p_milli=900,
        text_top_k=37,
        audio_temperature_milli=900,
        audio_top_p_milli=875,
        audio_top_k=31,
        audio_repetition_penalty_milli=1_350,
    )
    drifted = service.create(
        novel_id=novel_id,
        base_preset_id="onnx.Zhiming",
        target=NanoExperimentTarget("narrator", None, 2, None),
        parameters=custom_parameters,
        idempotency_key=f"nano-pg-drift-{uuid4()}",
    )
    _force_deferred_closure(connection)
    assert _advance_settings(factory, novel_id=novel_id) == 3
    drift_synthesizer = ValidSynthesizer()
    drift_lease = _claim(factory, job_id=drifted.command.background_job_id)
    _force_deferred_closure(connection)
    drift_outcome = await _processor(store, drift_synthesizer).process(
        drift_lease
    )
    assert drift_outcome.status == "succeeded"
    assert drift_outcome.command is not None
    assert drift_outcome.command.state == "ready_unapplied"
    assert drift_outcome.command.version_id != first.command.version_id
    assert drift_outcome.command.fingerprint != first.command.fingerprint
    assert len(drift_synthesizer.requests) == 1

    with factory() as session:
        settings = session.scalar(
            select(NovelNarrationSettings).where(
                NovelNarrationSettings.novel_id == novel_id
            )
        )
        assert settings is not None and settings.version == 3
        assert settings.narrator_version_id == first.command.version_id

    applied = service.apply(
        novel_id=novel_id,
        command_id=drifted.command.command_id,
        request=NanoExperimentApplyRequest(
            expected_settings_version=3,
            expected_binding_version=None,
        ),
    )
    assert applied.state == "ready_applied"
    with factory() as session:
        settings = session.scalar(
            select(NovelNarrationSettings).where(
                NovelNarrationSettings.novel_id == novel_id
            )
        )
        assert settings is not None and settings.version == 4
        assert settings.narrator_version_id == drifted.command.version_id
        assert session.scalar(
            select(func.count()).select_from(ModelRunRecord).join(
                VoiceProfileVersion,
                VoiceProfileVersion.model_run_id == ModelRunRecord.id,
            ).join(
                VoiceProfile,
                VoiceProfile.id == VoiceProfileVersion.profile_id,
            ).where(VoiceProfile.novel_id == novel_id)
        ) == 2
        commands = session.scalars(
            select(NanoVoiceExperimentCommandRow).where(
                NanoVoiceExperimentCommandRow.novel_id == novel_id
            )
        ).all()
        assert [command.state for command in commands].count("ready_applied") == 3

    # Force all initially-deferred 0034 closure triggers while the complete
    # graph remains visible, then the fixture rolls the root transaction back.
    connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


@pytest.mark.asyncio
async def test_completed_private_voice_deletion_allows_new_parameters_without_poisoning_list(
    nano_pg_runtime: tuple[Connection, SessionFactory],
    tmp_path: Path,
) -> None:
    connection, factory = nano_pg_runtime
    novel_id = _seed_novel(factory)
    store, service = _parts(factory)
    first = service.create(
        novel_id=novel_id,
        base_preset_id="onnx.Zhiming",
        target=NanoExperimentTarget("narrator", None, 0, None),
        parameters=NanoDecodeParametersV3(),
        idempotency_key=f"nano-delete-first-{uuid4()}",
    )
    _force_deferred_closure(connection)
    first_lease = _claim(factory, job_id=first.command.background_job_id)
    assert (
        await _processor(store, ValidSynthesizer()).process(first_lease)
    ).status == "succeeded"
    _force_deferred_closure(connection)

    models_root = tmp_path / "models"
    media_root = tmp_path / "media"
    models_root.mkdir(mode=0o750)
    media_root.mkdir(mode=0o750)
    deletion = StagedVoiceDeletionService(
        factory,
        storage=NarrationStorage(models_root=models_root, media_root=media_root),
        digest_keyring=TEST_DIGEST_KEYRING,
    )
    deletion._test_novel_id = novel_id
    with factory() as session:
        profile = session.get(VoiceProfile, first.command.profile_id)
        assert profile is not None
        profile_version = profile.version
    request = deletion.create_request(
        novel_id=novel_id,
        profile_id=first.command.profile_id,
        expected_profile_version=profile_version,
        idempotency_key=f"nano-delete-request-{uuid4()}",
        actor="local-owner",
    )
    fenced = deletion.confirm(
        novel_id=novel_id,
        request_id=request.request_id,
        expected_profile_version=profile_version,
        impact_digest=request.impact_digest,
        actor="local-owner",
    )
    assert fenced.state == "live_deleting"
    _force_deferred_closure(connection)
    completed = VoiceDeletionService._execute_and_notify(
        deletion,
        request.request_id,
        actor="local-owner",
    )
    assert completed.state == "completed"
    _force_deferred_closure(connection)
    assert service.list_for_novel(novel_id=novel_id) == ()

    # The immutable, deleted fingerprint remains an audit record and cannot be
    # silently re-created with changed semantics.
    with pytest.raises(NanoExperimentStateError, match="changed seed or parameter"):
        service.create(
            novel_id=novel_id,
            base_preset_id="onnx.Zhiming",
            target=NanoExperimentTarget("narrator", None, 2, None),
            parameters=NanoDecodeParametersV3(),
            idempotency_key=f"nano-delete-same-{uuid4()}",
        )

    replacement = service.create(
        novel_id=novel_id,
        base_preset_id="onnx.Zhiming",
        target=NanoExperimentTarget("narrator", None, 2, None),
        parameters=replace(NanoDecodeParametersV3(), seed=1_235),
        idempotency_key=f"nano-delete-replacement-{uuid4()}",
    )
    _force_deferred_closure(connection)
    assert service.list_for_novel(novel_id=novel_id) == (replacement.command,)
    replacement_lease = _claim(
        factory, job_id=replacement.command.background_job_id
    )
    outcome = await _processor(store, ValidSynthesizer()).process(
        replacement_lease
    )
    assert outcome.status == "succeeded"
    assert outcome.command is not None
    assert outcome.command.state == "ready_applied"
    assert service.list_for_novel(novel_id=novel_id) == (outcome.command,)
    with factory() as session:
        profile = session.get(VoiceProfile, first.command.profile_id)
        assert profile is not None
        assert profile.status == "active"
        assert profile.current_version_id == replacement.command.version_id
    connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


@pytest.mark.asyncio
async def test_isolated_real_nano_default_and_custom_parameters_publish_evidence(
    nano_pg_runtime: tuple[Connection, SessionFactory],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Opt-in real-model gate; never targets the long-term Sidecar or media root."""

    token_file = _real_nano_token_file()
    original_getaddrinfo = socket.getaddrinfo

    def isolated_sidecar_dns(
        host: str | bytes | None,
        port: str | int | None,
        *args: object,
        **kwargs: object,
    ) -> list[tuple[object, ...]]:
        resolved_host = "127.0.0.1" if host == "tts-sidecar" else host
        return original_getaddrinfo(resolved_host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", isolated_sidecar_dns)
    connection, factory = nano_pg_runtime
    models_root = tmp_path / "models"
    media_root = tmp_path / "media"
    models_root.mkdir(mode=0o750)
    media_root.mkdir(mode=0o750)
    models_root.chmod(0o750)
    media_root.chmod(0o750)
    storage = NarrationStorage(models_root=models_root, media_root=media_root)
    adapter = SidecarMossNanoTTSAdapter(
        SidecarRuntimeConfig(
            host="tts-sidecar",
            port=8765,
            token_file=token_file,
            timeout_seconds=300,
        ),
        lifecycle=FailOnRestartLifecycle(),
    )
    await adapter.activate()
    try:
        health = await adapter.warmup()
        assert health.status.value == "healthy", health
        novel_id = _seed_novel(factory)
        store, service = _parts(factory)
        synthesizer = CapturingSynthesizer(
            SidecarNanoExperimentSynthesizer(adapter=adapter, storage=storage)
        )
        processor = _processor(store, synthesizer)
        cases = (
            ("onnx.Zhiming", NanoDecodeParametersV3(), 0),
            (
                "onnx.Ava",
                NanoDecodeParametersV3(
                    seed=7_777,
                    text_temperature_milli=1_100,
                    text_top_p_milli=920,
                    text_top_k=43,
                    audio_temperature_milli=900,
                    audio_top_p_milli=900,
                    audio_top_k=30,
                    audio_repetition_penalty_milli=1_300,
                ),
                1,
            ),
        )
        commands = []
        for index, (preset_id, parameters, settings_version) in enumerate(cases):
            reservation = service.create(
                novel_id=novel_id,
                base_preset_id=preset_id,
                target=NanoExperimentTarget(
                    "narrator", None, settings_version, None
                ),
                parameters=parameters,
                idempotency_key=f"nano-real-{index}-{uuid4()}",
            )
            _force_deferred_closure(connection)
            lease = _claim(
                factory, job_id=reservation.command.background_job_id
            )
            _force_deferred_closure(connection)
            outcome = await processor.process(lease)
            assert outcome.status == "succeeded", (
                outcome.status,
                outcome.failure_code,
                outcome.command.state if outcome.command is not None else None,
                repr(synthesizer.error),
            )
            assert outcome.command is not None
            assert outcome.command.state == "ready_applied"
            assert outcome.command.reused_version is False
            commands.append(outcome.command)

        assert [request.parameters for request in synthesizer.requests] == [
            case[1] for case in cases
        ]
        assert len(synthesizer.results) == 2
        assert len({result.output_sha256 for result in synthesizer.results}) == 2
        for result in synthesizer.results:
            published = media_root / result.published_relative_path
            payload = published.read_bytes()
            assert hashlib.sha256(payload).hexdigest() == result.output_sha256
            assert len(payload) == result.published_byte_size
            assert result.duration_ms > 0
            assert result.model_run.model_fingerprint_sha256 == (
                production_nano_experiment_identity().model_fingerprint_sha256
            )

        with factory() as session:
            settings = session.scalar(
                select(NovelNarrationSettings).where(
                    NovelNarrationSettings.novel_id == novel_id
                )
            )
            assert settings is not None and settings.version == 2
            assert settings.narrator_version_id == commands[-1].version_id
            versions = session.scalars(
                select(VoiceProfileVersion)
                .join(VoiceProfile, VoiceProfile.id == VoiceProfileVersion.profile_id)
                .where(VoiceProfile.novel_id == novel_id)
                .order_by(VoiceProfileVersion.created_at, VoiceProfileVersion.id)
            ).all()
            assert len(versions) == 2
            assert {version.fingerprint for version in versions} == {
                command.fingerprint for command in commands
            }
            assert all(
                version.activation_basis == "experimental_machine_validated"
                and version.validation_basis == "machine_validated"
                and version.model_run_id is not None
                for version in versions
            )
            runs = session.scalars(
                select(ModelRunRecord).where(
                    ModelRunRecord.id.in_(
                        [version.model_run_id for version in versions]
                    )
                )
            ).all()
            assert len(runs) == 2
            assert {run.parameters_digest for run in runs} == {
                command.parameters_digest for command in commands
            }
            assert all(
                run.input_digest_key_id == TEST_DIGEST_KEYRING.active_key_id
                and run.result_classification == "success"
                and run.output_digest is not None
                for run in runs
            )
        connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    finally:
        await adapter.deactivate()
