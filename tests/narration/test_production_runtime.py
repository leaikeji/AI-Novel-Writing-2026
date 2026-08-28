from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import importlib
from pathlib import Path
from typing import Callable
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, text

from backend.narration.digest_keyring import DigestKeyringError
from backend.narration.runtime import EXPECTED_PRODUCTION_MODEL_FINGERPRINT
from backend.narration.transcoding import TranscodingUnavailable
from tests.narration.digest_fixtures import TEST_DIGEST_KEYRING
import backend.narration.narration_api as narration_api
import backend.narration.playback_api as playback_api
import backend.narration.production_runtime as production_runtime_module


VALIDATION_TOKEN = "v" * 43
VALIDATION_NOVEL_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
VALIDATION_DOCUMENT_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


class _IdleScheduler:
    """Minimal scheduler double for the shared segment/preview loop."""

    def maintain_once(self) -> None:
        return None

    def claim_next_typed_job(self) -> None:
        return None


class _SegmentRepositoryStub:
    def terminalize_job_in_session(self, _session, *, job_id):  # type: ignore[no-untyped-def]
        return job_id is not None


def _environment(
    tmp_path: Path,
    *,
    product: bool,
    validation: bool = False,
    technical: bool = True,
) -> dict[str, str]:
    models = tmp_path / "models"
    media = tmp_path / "media"
    models.mkdir(exist_ok=True)
    media.mkdir(exist_ok=True)
    values = {
        "AI_NOVEL_TTS_PRODUCT_ENABLED": "true" if product else "false",
        "AI_NOVEL_TTS_VALIDATION_ENABLED": "true" if validation else "false",
        "AI_NOVEL_TTS_RUNTIME_ENABLED": "true" if technical else "false",
        "AI_NOVEL_TTS_DIGEST_KEYRING_FILE": str(tmp_path / "keyring.json"),
        "AI_NOVEL_TTS_MODEL_METADATA_ROOT": str(models),
        "AI_NOVEL_TTS_MEDIA_ROOT": str(media),
        "AI_NOVEL_TTS_FFMPEG_PATH": str(tmp_path / "ffmpeg"),
        "AI_NOVEL_TTS_FFPROBE_PATH": str(tmp_path / "ffprobe"),
        "MOSS_FFMPEG_BUILD_ID": "ffmpeg-9.0.1-lgpl-narrow-linux-arm64-v1",
    }
    if validation:
        token_directory = tmp_path / "validation-token"
        token_directory.mkdir(mode=0o700, exist_ok=True)
        token_directory.chmod(0o700)
        token_file = token_directory / "token"
        token_file.write_text(VALIDATION_TOKEN, encoding="ascii")
        token_file.chmod(0o600)
        values["AI_NOVEL_TTS_VALIDATION_TOKEN_FILE"] = str(token_file)
        values["AI_NOVEL_TTS_VALIDATION_NOVEL_ID"] = str(VALIDATION_NOVEL_ID)
        values["AI_NOVEL_TTS_VALIDATION_DOCUMENT_ID"] = str(
            VALIDATION_DOCUMENT_ID
        )
        values["AI_NOVEL_TTS_VALIDATION_EXPIRES_AT"] = (
            datetime.now(timezone.utc) + timedelta(hours=1)
        ).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    return values


async def _wait_until(
    predicate: Callable[[], bool],
    *,
    timeout_seconds: float = 1.0,
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("production runtime did not settle")


@pytest_asyncio.fixture
async def production_owner():
    narration_api.uninstall_narration_production_backend_factory()
    playback_api.uninstall_playback_api_backend_factory()
    module = importlib.reload(production_runtime_module)
    yield module
    await module.stop_narration_production_runtime()
    narration_api.uninstall_narration_production_backend_factory()
    playback_api.uninstall_playback_api_backend_factory()
    leaked = [
        task
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task()
        and not task.done()
        and task.get_name() in {module.WORKER_TASK_NAME, module.WORKER_CYCLE_TASK_NAME}
    ]
    assert leaked == []


@pytest.mark.asyncio
async def test_database_probe_requires_exact_frozen_alembic_head(
    production_owner,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text("create table alembic_version (version_num varchar(32) not null)")
        )
        connection.execute(
            text("insert into alembic_version(version_num) values (:revision)"),
            {"revision": production_owner.EXPECTED_DATABASE_REVISION},
        )
    production_owner._verify_database(engine)

    with engine.begin() as connection:
        connection.execute(
            text("update alembic_version set version_num = '20260827_0018'")
        )
    with pytest.raises(
        production_owner.NarrationProductionRuntimeError,
        match="database schema",
    ) as captured:
        production_owner._verify_database(engine)
    assert captured.value.code == "TTS_DATABASE_SCHEMA_OUTDATED"
    engine.dispose()


@pytest.mark.asyncio
async def test_disabled_without_storage_performs_no_io(
    production_owner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        production_owner,
        "load_digest_keyring",
        lambda _path: calls.append("keyring"),
    )
    monkeypatch.setattr(
        production_owner,
        "get_engine",
        lambda: calls.append("database"),
    )

    await production_owner.launch_narration_production_runtime(
        {
            "AI_NOVEL_TTS_PRODUCT_ENABLED": "false",
            "AI_NOVEL_TTS_RUNTIME_ENABLED": "false",
        }
    )

    assert calls == []
    assert production_owner.narration_production_runtime_status() == {
        "product_requested": False,
        "lifecycle_status": "disabled",
        "playback_installed": False,
        "digest_keyring_loaded": False,
        "production_backend_installed": False,
        "worker_running": False,
        "reference_clone_ready": False,
        "reason_code": None,
    }


@pytest.mark.asyncio
async def test_reference_clone_flag_cannot_bypass_the_product_gate(
    production_owner,
) -> None:
    await production_owner.launch_narration_production_runtime(
        {
            "AI_NOVEL_TTS_PRODUCT_ENABLED": "false",
            "AI_NOVEL_TTS_REFERENCE_CLONE_ENABLED": "true",
            "AI_NOVEL_TTS_RUNTIME_ENABLED": "false",
        }
    )

    status = production_owner.narration_production_runtime_status()
    assert status["lifecycle_status"] == "configuration_error"
    assert status["playback_installed"] is False
    assert status["reason_code"] == "TTS_PRODUCT_CONFIGURATION_INVALID"


@pytest.mark.asyncio
async def test_product_release_and_hidden_validation_are_mutually_exclusive(
    production_owner,
    tmp_path: Path,
) -> None:
    await production_owner.launch_narration_production_runtime(
        _environment(tmp_path, product=True, validation=True)
    )

    status = production_owner.narration_production_runtime_status()
    assert status["product_requested"] is True
    assert status["lifecycle_status"] == "configuration_error"
    assert status["playback_installed"] is False
    assert status["reason_code"] == "TTS_PRODUCT_CONFIGURATION_INVALID"


@pytest.mark.asyncio
async def test_limited_validation_rejects_reference_clone_until_its_own_gate(
    production_owner,
    tmp_path: Path,
) -> None:
    environment = _environment(tmp_path, product=False, validation=True)
    environment["AI_NOVEL_TTS_REFERENCE_CLONE_ENABLED"] = "true"

    await production_owner.launch_narration_production_runtime(environment)

    status = production_owner.narration_production_runtime_status()
    assert status["product_requested"] is True
    assert status["lifecycle_status"] == "configuration_error"
    assert status["playback_installed"] is False
    assert status["reference_clone_ready"] is False
    assert status["reason_code"] == "TTS_PRODUCT_CONFIGURATION_INVALID"


@pytest.mark.asyncio
async def test_validation_token_loader_requires_private_file_and_compares_only_digest(
    production_owner,
    tmp_path: Path,
) -> None:
    token_directory = tmp_path / "private"
    token_directory.mkdir(mode=0o700)
    token = token_directory / "token"
    token.write_text(VALIDATION_TOKEN, encoding="ascii")
    token.chmod(0o600)

    production_owner._validation_token_digest = (
        production_owner._load_validation_token_digest(token)
    )
    production_owner._validation_runtime_scope = (
        production_owner.ValidationRuntimeScope(
            novel_id=VALIDATION_NOVEL_ID,
            document_id=VALIDATION_DOCUMENT_ID,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
    )
    assert production_owner.validation_route_token_authorized(VALIDATION_TOKEN)
    assert not production_owner.validation_route_token_authorized("w" * 43)
    assert not production_owner.validation_route_token_authorized(None)

    token.chmod(0o644)
    with pytest.raises(
        production_owner.NarrationProductionRuntimeError,
        match="token file",
    ) as captured:
        production_owner._load_validation_token_digest(token)
    assert captured.value.code == "TTS_VALIDATION_TOKEN_INVALID"


def test_validation_scope_is_canonical_short_lived_and_expiring(
    production_owner,
) -> None:
    now = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
    values = {
        "AI_NOVEL_TTS_VALIDATION_NOVEL_ID": str(VALIDATION_NOVEL_ID),
        "AI_NOVEL_TTS_VALIDATION_DOCUMENT_ID": str(VALIDATION_DOCUMENT_ID),
        "AI_NOVEL_TTS_VALIDATION_EXPIRES_AT": "2026-08-27T13:00:00Z",
    }

    scope = production_owner._load_validation_runtime_scope(values, now=now)
    assert scope.novel_id == VALIDATION_NOVEL_ID
    assert scope.document_id == VALIDATION_DOCUMENT_ID
    assert scope.active(now=now)
    assert not scope.active(
        now=datetime(2026, 8, 27, 13, 0, tzinfo=timezone.utc)
    )

    for invalid_expiry in (
        "2026-08-27T12:00:00Z",
        "2026-08-28T12:00:01Z",
        "2026-08-27T13:00:00+00:00",
    ):
        with pytest.raises(
            production_owner.NarrationProductionRuntimeError,
            match="expiry",
        ) as captured:
            production_owner._load_validation_runtime_scope(
                {**values, "AI_NOVEL_TTS_VALIDATION_EXPIRES_AT": invalid_expiry},
                now=now,
            )
        assert captured.value.code == "TTS_VALIDATION_SCOPE_INVALID"

    with pytest.raises(
        production_owner.NarrationProductionRuntimeError,
        match="canonical",
    ):
        production_owner._load_validation_runtime_scope(
            {
                **values,
                "AI_NOVEL_TTS_VALIDATION_NOVEL_ID": str(
                    VALIDATION_NOVEL_ID
                ).upper(),
            },
            now=now,
        )


def test_validation_segment_claim_gate_defaults_allow_and_limits_only_segments(
    production_owner,
) -> None:
    now = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
    gate = production_owner.ValidationSegmentClaimGate(clock=lambda: now)
    kinds = ("narration.segment_render", "narration.voice_preview")

    default = gate.reserve(kinds)
    assert default.allowed_job_kinds == kinds
    default.settle("narration.segment_render")
    assert gate.snapshot().state == "default_allow"

    armed = gate.arm(
        run_id=UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
        novel_id=VALIDATION_NOVEL_ID,
        document_id=VALIDATION_DOCUMENT_ID,
        runtime_expires_at=now + timedelta(hours=1),
    )
    assert armed.code == "VALIDATION_SEGMENT_CLAIM_GATE_ARMED"
    assert armed.claim_limit == 1
    assert armed.claimed_count == 0
    assert armed.remaining_count == 1
    assert armed.run_fingerprint_sha256 is not None
    assert str(VALIDATION_NOVEL_ID) not in repr(armed)

    preview = gate.reserve(("narration.voice_preview",))
    assert preview.allowed_job_kinds == ("narration.voice_preview",)
    preview.settle("narration.voice_preview")
    assert gate.snapshot().claimed_count == 0

    first = gate.reserve(kinds)
    assert first.allowed_job_kinds == kinds
    first.settle("narration.segment_render")
    paused = gate.snapshot()
    assert paused.state == "paused"
    assert paused.claimed_count == 1
    assert paused.remaining_count == 0

    later = gate.reserve(kinds)
    assert later.allowed_job_kinds == ("narration.voice_preview",)
    later.settle("narration.voice_preview")
    assert gate.snapshot().claimed_count == 1


def test_validation_segment_claim_gate_is_concurrent_releaseable_and_expiring(
    production_owner,
) -> None:
    current = [datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)]
    gate = production_owner.ValidationSegmentClaimGate(clock=lambda: current[0])
    first_run = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
    second_run = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
    arm_kwargs = {
        "novel_id": VALIDATION_NOVEL_ID,
        "document_id": VALIDATION_DOCUMENT_ID,
        "runtime_expires_at": current[0] + timedelta(hours=1),
        "ttl_seconds": 2,
    }
    gate.arm(run_id=first_run, **arm_kwargs)

    def claim_once() -> bool:
        reservation = gate.reserve(("narration.segment_render",))
        claimed = bool(reservation.allowed_job_kinds)
        reservation.settle("narration.segment_render" if claimed else None)
        return claimed

    with ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(lambda _index: claim_once(), range(32))) == 1
    assert gate.snapshot().claimed_count == 1

    with pytest.raises(
        production_owner.NarrationProductionRuntimeError,
        match="binding",
    ) as mismatch:
        gate.release(
            run_id=second_run,
            novel_id=VALIDATION_NOVEL_ID,
            document_id=VALIDATION_DOCUMENT_ID,
        )
    assert mismatch.value.code == "TTS_VALIDATION_CLAIM_GATE_BINDING_MISMATCH"

    released = gate.release(
        run_id=first_run,
        novel_id=VALIDATION_NOVEL_ID,
        document_id=VALIDATION_DOCUMENT_ID,
    )
    assert released.code == "VALIDATION_SEGMENT_CLAIM_GATE_RELEASED"
    assert released.state == "default_allow"
    gate.arm(run_id=second_run, **arm_kwargs)
    current[0] += timedelta(seconds=3)
    assert gate.snapshot().state == "default_allow"
    restored = gate.reserve(("narration.segment_render",))
    assert restored.allowed_job_kinds == ("narration.segment_render",)
    restored.settle("narration.segment_render")


def test_validation_segment_claim_gate_requires_active_exact_runtime_scope(
    production_owner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
    production_owner._validation_runtime_scope = None
    with pytest.raises(production_owner.NarrationProductionRuntimeError) as disabled:
        production_owner.arm_validation_segment_claim_gate(
            run_id=run_id,
            novel_id=VALIDATION_NOVEL_ID,
            document_id=VALIDATION_DOCUMENT_ID,
        )
    assert disabled.value.code == "TTS_VALIDATION_CLAIM_GATE_SCOPE_INVALID"

    production_owner._validation_runtime_scope = production_owner.ValidationRuntimeScope(
        novel_id=VALIDATION_NOVEL_ID,
        document_id=VALIDATION_DOCUMENT_ID,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    with pytest.raises(production_owner.NarrationProductionRuntimeError) as wrong_scope:
        production_owner.arm_validation_segment_claim_gate(
            run_id=run_id,
            novel_id=UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"),
            document_id=VALIDATION_DOCUMENT_ID,
        )
    assert wrong_scope.value.code == "TTS_VALIDATION_CLAIM_GATE_SCOPE_INVALID"

    monkeypatch.setattr(
        production_owner,
        "Session",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("claim gate control plane opened the database")
        ),
    )
    armed = production_owner.arm_validation_segment_claim_gate(
        run_id=run_id,
        novel_id=VALIDATION_NOVEL_ID,
        document_id=VALIDATION_DOCUMENT_ID,
    )
    assert armed.state == "armed"
    assert production_owner.read_validation_segment_claim_gate(
        novel_id=VALIDATION_NOVEL_ID,
        document_id=VALIDATION_DOCUMENT_ID,
    ).claimed_count == 0
    assert production_owner.release_validation_segment_claim_gate(
        run_id=run_id,
        novel_id=VALIDATION_NOVEL_ID,
        document_id=VALIDATION_DOCUMENT_ID,
    ).state == "default_allow"


@pytest.mark.asyncio
async def test_playback_only_never_reads_keyring_or_starts_worker(
    production_owner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    keyring_reads = 0

    def forbidden_keyring(_path: Path):  # type: ignore[no-untyped-def]
        nonlocal keyring_reads
        keyring_reads += 1
        raise AssertionError("playback-only runtime read the digest keyring")

    monkeypatch.setattr(production_owner, "load_digest_keyring", forbidden_keyring)
    await production_owner.launch_narration_production_runtime(
        _environment(tmp_path, product=False)
    )

    status = production_owner.narration_production_runtime_status()
    assert keyring_reads == 0
    assert status["lifecycle_status"] == "playback_only"
    assert status["playback_installed"] is True
    assert status["production_backend_installed"] is False
    assert status["worker_running"] is False


@pytest.mark.asyncio
async def test_missing_keyring_fails_closed_before_database_adapter_or_worker(
    production_owner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def missing(_path: Path):  # type: ignore[no-untyped-def]
        calls.append("keyring")
        raise DigestKeyringError(
            "DIGEST_KEYRING_UNAVAILABLE",
            "narration digest keyring is unavailable",
        )

    monkeypatch.setattr(production_owner, "load_digest_keyring", missing)
    monkeypatch.setattr(
        production_owner,
        "get_engine",
        lambda: calls.append("database"),
    )
    monkeypatch.setattr(
        production_owner,
        "get_ready_narration_adapter",
        lambda: calls.append("adapter"),
    )
    await production_owner.launch_narration_production_runtime(
        _environment(tmp_path, product=True)
    )
    await _wait_until(
        lambda: production_owner.narration_production_runtime_status()[
            "lifecycle_status"
        ]
        == "unavailable"
    )

    status = production_owner.narration_production_runtime_status()
    assert calls == ["keyring"]
    assert status["playback_installed"] is True
    assert status["digest_keyring_loaded"] is False
    assert status["production_backend_installed"] is False
    assert status["worker_running"] is False
    assert status["reason_code"] == "DIGEST_KEYRING_UNAVAILABLE"
    assert "keyring.json" not in str(status)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("product", "validation"),
    ((True, False), (False, True)),
)
async def test_ready_runtime_installs_one_backend_and_one_worker_then_cleans_up(
    production_owner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    product: bool,
    validation: bool,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    worker_instances: list[object] = []
    adapter_calls: list[str] = []
    scheduler_kwargs: list[dict[str, object]] = []

    class Adapter:
        async def model_fingerprint(self):  # type: ignore[no-untyped-def]
            adapter_calls.append("model_fingerprint")
            return EXPECTED_PRODUCTION_MODEL_FINGERPRINT

    class Worker:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs
            worker_instances.append(self)

        async def run_until_stopped(
            self,
            stop_event: asyncio.Event,
            **_kwargs: object,
        ) -> None:
            await stop_event.wait()

    monkeypatch.setattr(
        production_owner,
        "load_digest_keyring",
        lambda _path: TEST_DIGEST_KEYRING,
    )
    monkeypatch.setattr(production_owner, "get_engine", lambda: engine)
    monkeypatch.setattr(production_owner, "_verify_database", lambda _engine: None)
    monkeypatch.setattr(
        production_owner,
        "_verify_validation_runtime_scope",
        lambda _engine, _scope: None,
    )
    monkeypatch.setattr(
        production_owner,
        "validate_fixed_toolchain",
        lambda **_kwargs: None,
    )

    async def ready_immediately(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(
        production_owner,
        "wait_narration_runtime_initialized",
        ready_immediately,
    )
    adapter = Adapter()
    monkeypatch.setattr(
        production_owner,
        "get_ready_narration_adapter",
        lambda: adapter,
    )
    def scheduler_factory(*_args: object, **kwargs: object) -> _IdleScheduler:
        scheduler_kwargs.append(kwargs)
        return _IdleScheduler()

    monkeypatch.setattr(
        production_owner,
        "NarrationJobScheduler",
        scheduler_factory,
    )
    monkeypatch.setattr(
        production_owner,
        "SqlAlchemyNarrationWorkerRepository",
        lambda *_args, **_kwargs: _SegmentRepositoryStub(),
    )
    monkeypatch.setattr(
        production_owner,
        "FixedFfmpegTranscoder",
        lambda **_kwargs: (lambda _audio: None),
    )
    monkeypatch.setattr(production_owner, "NarrationSegmentWorker", Worker)
    monkeypatch.setattr(
        production_owner,
        "VoiceProductService",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        production_owner,
        "VoicePreviewProcessor",
        lambda **_kwargs: object(),
    )

    await production_owner.launch_narration_production_runtime(
        _environment(tmp_path, product=product, validation=validation)
    )
    await _wait_until(
        lambda: production_owner.narration_production_runtime_status()[
            "lifecycle_status"
        ]
        == "ready"
    )

    status = production_owner.narration_production_runtime_status()
    cache_runtime = production_owner.current_narration_cache_runtime()
    assert adapter_calls == ["model_fingerprint"]
    assert len(worker_instances) == 1
    assert len(scheduler_kwargs) == 1
    assert (
        callable(scheduler_kwargs[0]["job_kind_claim_gate"])
        if validation
        else scheduler_kwargs[0]["job_kind_claim_gate"] is None
    )
    assert isinstance(cache_runtime, production_owner.SqlAlchemyNarrationCacheRuntime)
    assert cache_runtime.cleanup_capability.state.value == "enabled"
    assert cache_runtime.cleanup_capability.visible is True
    assert cache_runtime.cleanup_capability.actionable is True
    assert callable(worker_instances[0].kwargs["disk_guard"])
    assert status["digest_keyring_loaded"] is True
    assert status["production_backend_installed"] is True
    assert status["worker_running"] is True
    assert status["reference_clone_ready"] is False
    assert not ({"path", "secret", "key_id"} & set(status))
    if validation:
        armed = production_owner.arm_validation_segment_claim_gate(
            run_id=UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
            novel_id=VALIDATION_NOVEL_ID,
            document_id=VALIDATION_DOCUMENT_ID,
        )
        assert armed.state == "armed"

    await production_owner.stop_narration_production_runtime()
    assert production_owner._validation_segment_claim_gate.snapshot().state == (
        "default_allow"
    )
    assert production_owner.current_narration_cache_runtime() is None
    assert production_owner.narration_production_runtime_status()[
        "lifecycle_status"
    ] == "disabled"
    engine.dispose()


@pytest.mark.asyncio
async def test_ready_runtime_health_exposes_only_stable_disk_guard_reason(
    production_owner,
) -> None:
    reason = "DISK_SPACE_INSUFFICIENT"

    class Guard:
        def status(self):  # type: ignore[no-untyped-def]
            return type("Status", (), {"reason_code": reason})()

    production_owner._snapshot = production_owner.NarrationProductionRuntimeSnapshot(
        product_requested=True,
        lifecycle_status="ready",
        playback_installed=True,
        digest_keyring_loaded=True,
        production_backend_installed=True,
        worker_running=True,
    )
    production_owner._disk_guard = Guard()

    status = production_owner.narration_production_runtime_status()

    assert status["reason_code"] == "DISK_SPACE_INSUFFICIENT"
    assert not ({"path", "free_bytes", "total_bytes"} & set(status))


@pytest.mark.asyncio
async def test_reference_clone_runtime_publishes_one_port_and_uses_shared_fair_dispatch(
    production_owner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    adapter = object()
    product_port = object()
    scheduler_configs: list[object] = []
    preview_processors: list[dict[str, object]] = []

    class FingerprintedAdapter:
        async def model_fingerprint(self):  # type: ignore[no-untyped-def]
            return EXPECTED_PRODUCTION_MODEL_FINGERPRINT

    adapter = FingerprintedAdapter()

    class PreviewRepository:
        def terminalize_job_in_session(self, _session, *, job_id):  # type: ignore[no-untyped-def]
            return job_id is not None

    class Scheduler:
        def maintain_once(self) -> None:
            return None

        def claim_next_typed_job(self):  # type: ignore[no-untyped-def]
            return None

    class SegmentWorker:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def process(self, _lease: object) -> None:
            raise AssertionError("idle shared dispatcher fabricated a segment lease")

    class PreviewProcessor:
        def __init__(self, **kwargs: object) -> None:
            preview_processors.append(kwargs)

        async def process(self, _lease: object) -> None:
            raise AssertionError("idle shared dispatcher fabricated a preview lease")

    monkeypatch.setattr(
        production_owner,
        "load_digest_keyring",
        lambda _path: TEST_DIGEST_KEYRING,
    )
    monkeypatch.setattr(production_owner, "get_engine", lambda: engine)
    monkeypatch.setattr(production_owner, "_verify_database", lambda _engine: None)
    monkeypatch.setattr(
        production_owner,
        "_verify_validation_runtime_scope",
        lambda _engine, _scope: None,
    )
    monkeypatch.setattr(
        production_owner,
        "validate_fixed_toolchain",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        production_owner,
        "get_ready_narration_adapter",
        lambda: adapter,
    )
    monkeypatch.setattr(
        production_owner,
        "SqlAlchemyNarrationWorkerRepository",
        lambda *_args, **_kwargs: _SegmentRepositoryStub(),
    )
    monkeypatch.setattr(
        production_owner,
        "SqlAlchemyVoicePreviewRepository",
        lambda *_args, **_kwargs: PreviewRepository(),
    )

    def build_scheduler(*_args: object, **kwargs: object) -> Scheduler:
        scheduler_configs.append(kwargs["config"])
        assert "narration.segment_render" in kwargs["terminalizers"]
        assert "narration.voice_preview" in kwargs["terminalizers"]
        assert kwargs["job_kind_claim_gate"] is None
        return Scheduler()

    monkeypatch.setattr(production_owner, "NarrationJobScheduler", build_scheduler)
    monkeypatch.setattr(
        production_owner,
        "FixedFfmpegTranscoder",
        lambda **_kwargs: (lambda _audio: None),
    )
    monkeypatch.setattr(production_owner, "NarrationSegmentWorker", SegmentWorker)
    monkeypatch.setattr(production_owner, "VoicePreviewProcessor", PreviewProcessor)
    monkeypatch.setattr(
        production_owner,
        "VoiceProductService",
        lambda *_args, **_kwargs: product_port,
    )

    environment = _environment(tmp_path, product=True, validation=False)
    environment["AI_NOVEL_TTS_REFERENCE_CLONE_ENABLED"] = "true"
    await production_owner.launch_narration_production_runtime(environment)
    await _wait_until(
        lambda: production_owner.narration_production_runtime_status()[
            "lifecycle_status"
        ]
        == "ready"
    )

    assert production_owner.current_voice_product_port() is product_port
    assert production_owner.narration_production_runtime_status()[
        "reference_clone_ready"
    ] is True
    assert len(preview_processors) == 1
    assert len(scheduler_configs) == 1
    assert scheduler_configs[0].job_kinds == (  # type: ignore[attr-defined]
        "narration.segment_render",
        "narration.voice_preview",
    )
    assert scheduler_configs[0].novel_ids is None  # type: ignore[attr-defined]
    assert scheduler_configs[0].document_ids is None  # type: ignore[attr-defined]

    await production_owner.stop_narration_production_runtime()
    assert production_owner.current_voice_product_port() is None
    engine.dispose()


@pytest.mark.asyncio
async def test_unusable_fixed_toolchain_fails_before_adapter_backend_or_worker(
    production_owner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    calls: list[str] = []
    monkeypatch.setattr(
        production_owner,
        "load_digest_keyring",
        lambda _path: TEST_DIGEST_KEYRING,
    )
    monkeypatch.setattr(production_owner, "get_engine", lambda: engine)
    monkeypatch.setattr(production_owner, "_verify_database", lambda _engine: None)

    def unavailable_toolchain(**_kwargs: object) -> None:
        calls.append("toolchain")
        raise TranscodingUnavailable("fixed ffmpeg executable is unavailable")

    monkeypatch.setattr(
        production_owner,
        "validate_fixed_toolchain",
        unavailable_toolchain,
    )
    monkeypatch.setattr(
        production_owner,
        "get_ready_narration_adapter",
        lambda: calls.append("adapter"),
    )
    await production_owner.launch_narration_production_runtime(
        _environment(tmp_path, product=True)
    )
    await _wait_until(
        lambda: production_owner.narration_production_runtime_status()[
            "lifecycle_status"
        ]
        == "unavailable"
    )

    assert calls == ["toolchain"]
    status = production_owner.narration_production_runtime_status()
    assert status["production_backend_installed"] is False
    assert status["worker_running"] is False
    assert status["reason_code"] == "TTS_PRODUCTION_START_FAILED"
    engine.dispose()


@pytest.mark.asyncio
async def test_adapter_lease_loss_detaches_and_rebuilds_one_worker_cycle(
    production_owner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    model_calls: list[str] = []
    worker_adapters: list[object] = []
    launches = 0

    class Adapter:
        def __init__(self, name: str) -> None:
            self.name = name

        async def model_fingerprint(self):  # type: ignore[no-untyped-def]
            model_calls.append(self.name)
            return EXPECTED_PRODUCTION_MODEL_FINGERPRINT

    first = Adapter("first")
    second = Adapter("second")
    current: list[Adapter | None] = [None]

    class Worker:
        def __init__(self, **kwargs: object) -> None:
            worker_adapters.append(kwargs["adapter"])

        async def run_until_stopped(
            self,
            stop_event: asyncio.Event,
            **_kwargs: object,
        ) -> None:
            await stop_event.wait()

    async def relaunch(*_args: object, **_kwargs: object) -> None:
        nonlocal launches
        launches += 1
        current[0] = first if launches == 1 else second

    async def initialized(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(
        production_owner,
        "load_digest_keyring",
        lambda _path: TEST_DIGEST_KEYRING,
    )
    monkeypatch.setattr(production_owner, "get_engine", lambda: engine)
    monkeypatch.setattr(production_owner, "_verify_database", lambda _engine: None)
    monkeypatch.setattr(
        production_owner,
        "validate_fixed_toolchain",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(production_owner, "launch_narration_runtime", relaunch)
    monkeypatch.setattr(
        production_owner,
        "wait_narration_runtime_initialized",
        initialized,
    )
    monkeypatch.setattr(
        production_owner,
        "narration_runtime_status",
        lambda: {
            "lifecycle_status": "ready" if current[0] is not None else "unavailable",
            "reason_code": None,
        },
    )
    monkeypatch.setattr(
        production_owner,
        "get_ready_narration_adapter",
        lambda: current[0],
    )
    monkeypatch.setattr(
        production_owner,
        "NarrationJobScheduler",
        lambda *_args, **_kwargs: _IdleScheduler(),
    )
    monkeypatch.setattr(
        production_owner,
        "SqlAlchemyNarrationWorkerRepository",
        lambda *_args, **_kwargs: _SegmentRepositoryStub(),
    )
    monkeypatch.setattr(
        production_owner,
        "FixedFfmpegTranscoder",
        lambda **_kwargs: (lambda _audio: None),
    )
    monkeypatch.setattr(production_owner, "NarrationSegmentWorker", Worker)
    monkeypatch.setattr(
        production_owner,
        "VoiceProductService",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        production_owner,
        "VoicePreviewProcessor",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(production_owner, "SIDECAR_RETRY_SECONDS", 0.01)

    await production_owner.launch_narration_production_runtime(
        _environment(tmp_path, product=True)
    )
    await _wait_until(lambda: len(worker_adapters) == 1)
    assert production_owner.narration_production_runtime_status()[
        "lifecycle_status"
    ] == "ready"

    current[0] = None
    await _wait_until(lambda: len(worker_adapters) == 2)

    assert worker_adapters == [first, second]
    assert model_calls == ["first", "second"]
    assert launches == 2
    status = production_owner.narration_production_runtime_status()
    assert status["lifecycle_status"] == "ready"
    assert status["production_backend_installed"] is True
    assert status["worker_running"] is True
    await production_owner.stop_narration_production_runtime()
    engine.dispose()
