"""Plan 33 gates for request-scoped private voice deletion.

The PostgreSQL test is opt-in and refuses every database except the named
loopback disposable database.  It never targets the long-running project DB.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from backend.models import (
    AssetTombstone,
    MediaAsset,
    Novel,
    VoiceDeletionAssetPlan,
    VoiceProfile,
    VoiceProfileVersion,
    VoiceRightsRecord,
)
from backend.narration.contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID
from backend.narration.storage import NarrationStorage
from backend.narration.voice_deletion import (
    VoiceDeletionConflict,
    VoiceDeletionImpact,
    VoiceDeletionService,
)
from tests.narration.digest_fixtures import TEST_DIGEST_KEYRING


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_DATABASE = "plan33_del"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def test_impact_payload_exposes_consequences_without_private_text() -> None:
    impact = VoiceDeletionImpact(
        profile_id=uuid4(),
        novel_id=uuid4(),
        profile_version=3,
        voice_version_ids=(uuid4(),),
        current_narrator_count=1,
        character_binding_count=2,
        anonymous_speaker_count=0,
        generic_slot_count=0,
        edition_ids=(uuid4(),),
        render_ids=(uuid4(),),
        export_count=1,
        asset_roles=((uuid4(), "preview"),),
        total_bytes=42,
        active_job_ids=(),
    )

    payload = impact.payload()

    assert payload["historical_audio_consequence"] == (
        "unavailable_private_voice_deleted"
    )
    assert payload["external_backup_status"] == "unmanaged"
    assert payload["asset_count"] == 1
    assert "description" not in payload


def test_service_rejects_bad_idempotency_key_before_opening_database() -> None:
    service = VoiceDeletionService(
        lambda: (_ for _ in ()).throw(AssertionError("database must not open")),
        storage=object(),  # type: ignore[arg-type]
        digest_keyring=TEST_DIGEST_KEYRING,
    )

    with pytest.raises(ValueError, match="idempotency"):
        service.create_request(
            profile_id=uuid4(),
            expected_profile_version=1,
            discard_unreferenced=False,
            idempotency_key="short",
            actor="local-owner",
        )


@pytest.mark.parametrize("operation", ["confirm", "retry"])
def test_service_rejects_invalid_execution_actor_before_opening_database(
    operation: str,
) -> None:
    service = VoiceDeletionService(
        lambda: (_ for _ in ()).throw(AssertionError("database must not be opened")),
        storage=object(),  # type: ignore[arg-type]
        digest_keyring=object(),  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match="actor"):
        if operation == "confirm":
            service.confirm(
                uuid4(),
                expected_profile_version=1,
                impact_digest="a" * 64,
                actor="   ",
            )
        else:
            service.retry(uuid4(), actor="   ")


def _postgres_url() -> str:
    raw = os.environ.get("TTS_VOICE_DELETION_TEST_DATABASE_URL", "").strip()
    if not raw:
        pytest.skip("set TTS_VOICE_DELETION_TEST_DATABASE_URL for the deletion gate")
    parsed = make_url(raw)
    if (
        not parsed.drivername.startswith("postgresql")
        or parsed.database != EXPECTED_DATABASE
        or parsed.host not in LOOPBACK_HOSTS
    ):
        raise RuntimeError("voice deletion test requires the exact disposable database")
    production = os.environ.get("AI_NOVEL_DATABASE_URL", "").strip()
    if production:
        live = make_url(production)
        if (parsed.host, parsed.port, parsed.database) == (
            live.host,
            live.port,
            live.database,
        ):
            raise RuntimeError("voice deletion test refuses the production database")
    return raw


@pytest.fixture(scope="module")
def deletion_engine() -> Engine:
    engine = create_engine(_postgres_url(), pool_pre_ping=True)
    scripts = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT current_database()").scalar() == (
            EXPECTED_DATABASE
        )
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar() == scripts.get_current_head()
    try:
        yield engine
    finally:
        engine.dispose()


def _storage(tmp_path: Path) -> NarrationStorage:
    models = tmp_path / "models"
    media = tmp_path / "media"
    models.mkdir(mode=0o750)
    media.mkdir(mode=0o750)
    return NarrationStorage(models_root=models, media_root=media)


def _seed_profile(
    engine: Engine,
    storage: NarrationStorage,
    *,
    source_type: str,
    with_preview: bool,
) -> tuple[UUID, UUID | None, str | None]:
    now = datetime.now(timezone.utc)
    asset_id: UUID | None = None
    storage_path: str | None = None
    published = None
    voice_bytes = b"RIFF-plan33-private-voice-test"
    if with_preview:
        asset_id = uuid4()
        digest = hashlib.sha256(voice_bytes).hexdigest()
        published = storage.publish_media(
            [voice_bytes],
            asset_id=asset_id,
            expected_sha256=digest,
            expected_size=len(voice_bytes),
            extension="wav",
            max_bytes=1024,
        )
        storage_path = published.relative_path
    with Session(engine, expire_on_commit=False) as session, session.begin():
        novel = Novel(
            id=uuid4(),
            owner_id=LOCAL_OWNER_ID,
            workspace_id=LOCAL_WORKSPACE_ID,
            title="Plan 33 deletion test",
        )
        session.add(novel)
        session.flush()
        rights = VoiceRightsRecord(
            id=uuid4(),
            owner_id=LOCAL_OWNER_ID,
            workspace_id=LOCAL_WORKSPACE_ID,
            novel_id=novel.id,
            source_kind="generated_description",
            source_identifier=f"plan33:{uuid4()}",
            notice_version="rights/1",
            purpose="narration",
            commercial_use=False,
            redistribution=False,
            voice_cloning=True,
            confirmed_actor="local-owner",
            confirmed_at=now,
            risk_flags_json=[],
        )
        profile = VoiceProfile(
            id=uuid4(),
            owner_id=LOCAL_OWNER_ID,
            workspace_id=LOCAL_WORKSPACE_ID,
            novel_id=novel.id,
            name="Plan 33 private voice",
            current_version_id=None,
            status="draft",
            version=1,
        )
        session.add_all([rights, profile])
        session.flush()
        if published is not None and asset_id is not None:
            session.add(
                MediaAsset(
                    id=asset_id,
                    owner_id=LOCAL_OWNER_ID,
                    workspace_id=LOCAL_WORKSPACE_ID,
                    novel_id=novel.id,
                    kind="narration_voice_preview",
                    asset_class="preview",
                    mime_type="audio/wav",
                    byte_size=published.byte_size,
                    duration_ms=100,
                    sample_rate=24_000,
                    channels=1,
                    storage_backend="local",
                    state="ready",
                    retention_policy="temporary_preview",
                    checksum_algorithm="sha256",
                    validation_json={},
                    verified_at=now,
                    storage_path=published.relative_path,
                    content_hash=published.actual_sha256,
                    metadata_json={},
                )
            )
            session.flush()
        version = VoiceProfileVersion(
            id=uuid4(),
            profile_id=profile.id,
            owner_id=LOCAL_OWNER_ID,
            workspace_id=LOCAL_WORKSPACE_ID,
            version_number=1,
            source_type=source_type,
            state="draft",
            preview_asset_id=asset_id,
            rights_record_id=rights.id,
            language="zh-CN",
            seed=7,
            parameters_json={},
            fingerprint=hashlib.sha256(uuid4().bytes).hexdigest(),
            quality_state="pending",
            activation_basis="preview_confirmed",
            validation_basis="pending",
        )
        session.add(version)
        session.flush()
        profile.current_version_id = version.id
        profile.version = 2
        return profile.id, asset_id, storage_path


def test_postgres_private_voice_delete_unlinks_and_tombstones_exact_asset(
    deletion_engine: Engine,
    tmp_path: Path,
) -> None:
    storage = _storage(tmp_path)
    profile_id, asset_id, storage_path = _seed_profile(
        deletion_engine, storage, source_type="generated", with_preview=True
    )
    assert asset_id is not None and storage_path is not None
    service = VoiceDeletionService(
        sessionmaker(deletion_engine, expire_on_commit=False),
        storage=storage,
        digest_keyring=TEST_DIGEST_KEYRING,
    )

    request = service.create_request(
        profile_id=profile_id,
        expected_profile_version=2,
        discard_unreferenced=False,
        idempotency_key=f"delete-{uuid4()}",
        actor="local-owner",
    )
    completed = service.confirm(
        request.request_id,
        expected_profile_version=2,
        impact_digest=request.impact_digest,
        actor="local-owner",
    )

    with Session(deletion_engine) as session:
        profile = session.get(VoiceProfile, profile_id)
        asset = session.get(MediaAsset, asset_id)
        plan = session.scalar(
            select(VoiceDeletionAssetPlan).where(
                VoiceDeletionAssetPlan.deletion_request_id == request.request_id
            )
        )
        tombstone = session.scalar(
            select(AssetTombstone).where(
                AssetTombstone.deletion_request_id == request.request_id
            )
        )
        assert completed.state == "completed"
        assert profile is not None and profile.status == "unavailable"
        assert asset is not None and asset.state == "deleted"
        assert plan is not None and plan.state == "finalized"
        assert tombstone is not None and tombstone.original_asset_id == asset_id
    assert not storage.media_path_exists(storage_path)


def test_postgres_grace_cancel_and_official_profile_rejection(
    deletion_engine: Engine,
    tmp_path: Path,
) -> None:
    storage = _storage(tmp_path)
    factory = sessionmaker(deletion_engine, expire_on_commit=False)
    service = VoiceDeletionService(
        factory, storage=storage, digest_keyring=TEST_DIGEST_KEYRING
    )
    private_id, _asset_id, _path = _seed_profile(
        deletion_engine, storage, source_type="generated", with_preview=False
    )
    request = service.create_request(
        profile_id=private_id,
        expected_profile_version=2,
        discard_unreferenced=True,
        idempotency_key=f"discard-{uuid4()}",
        actor="local-owner",
    )
    assert request.state == "grace_pending"
    assert request.execute_after is not None
    assert request.execute_after > datetime.now(timezone.utc) + timedelta(seconds=20)
    assert service.cancel(request.request_id, actor="local-owner").state == "cancelled"

    official_id, _asset_id, _path = _seed_profile(
        deletion_engine, storage, source_type="preset", with_preview=False
    )
    with pytest.raises(VoiceDeletionConflict, match="official or mixed-source"):
        service.create_request(
            profile_id=official_id,
            expected_profile_version=2,
            discard_unreferenced=True,
            idempotency_key=f"official-{uuid4()}",
            actor="local-owner",
        )


def test_postgres_expired_grace_cannot_be_undone_and_can_complete(
    deletion_engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.narration.voice_deletion.UNREFERENCED_GRACE", timedelta(0)
    )
    storage = _storage(tmp_path)
    factory = sessionmaker(deletion_engine, expire_on_commit=False)
    service = VoiceDeletionService(
        factory, storage=storage, digest_keyring=TEST_DIGEST_KEYRING
    )
    profile_id, _asset_id, _path = _seed_profile(
        deletion_engine, storage, source_type="generated", with_preview=False
    )
    request = service.create_request(
        profile_id=profile_id,
        expected_profile_version=2,
        discard_unreferenced=True,
        idempotency_key=f"expire-{uuid4()}",
        actor="local-owner",
    )
    with pytest.raises(VoiceDeletionConflict, match="undo window has expired"):
        service.cancel(request.request_id, actor="local-owner")
    completed = service.confirm(
        request.request_id,
        expected_profile_version=2,
        impact_digest=request.impact_digest,
        actor="local-owner",
    )
    assert completed.state == "completed"


@pytest.mark.parametrize(
    "crash_boundary",
    ("before_unlink", "after_unlink_before_finalize", "after_finalize"),
)
def test_postgres_crash_boundaries_resume_the_same_frozen_plan(
    deletion_engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    crash_boundary: str,
) -> None:
    from backend.narration import voice_deletion as module

    storage = _storage(tmp_path)
    profile_id, asset_id, storage_path = _seed_profile(
        deletion_engine, storage, source_type="generated", with_preview=True
    )
    assert asset_id is not None and storage_path is not None
    service = VoiceDeletionService(
        sessionmaker(deletion_engine, expire_on_commit=False),
        storage=storage,
        digest_keyring=TEST_DIGEST_KEYRING,
    )
    request = service.create_request(
        profile_id=profile_id,
        expected_profile_version=2,
        discard_unreferenced=False,
        idempotency_key=f"crash-{uuid4()}",
        actor="local-owner",
    )

    if crash_boundary == "before_unlink":
        original = storage.delete_media_verified
        monkeypatch.setattr(
            storage,
            "delete_media_verified",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                OSError("injected before unlink")
            ),
        )
    elif crash_boundary == "after_unlink_before_finalize":
        original = module.finalize_voice_deletion_asset_in_session
        monkeypatch.setattr(
            module,
            "finalize_voice_deletion_asset_in_session",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                OSError("injected after unlink")
            ),
        )
    else:
        original = VoiceDeletionService._complete_request
        monkeypatch.setattr(
            VoiceDeletionService,
            "_complete_request",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                OSError("injected after finalize")
            ),
        )

    with pytest.raises(OSError, match="injected"):
        service.confirm(
            request.request_id,
            expected_profile_version=2,
            impact_digest=request.impact_digest,
            actor="local-owner",
        )

    if crash_boundary == "before_unlink":
        assert storage.media_path_exists(storage_path)
        monkeypatch.setattr(storage, "delete_media_verified", original)
        completed = service.retry(request.request_id, actor="local-owner")
    elif crash_boundary == "after_unlink_before_finalize":
        assert not storage.media_path_exists(storage_path)
        monkeypatch.setattr(
            module, "finalize_voice_deletion_asset_in_session", original
        )
        completed = service.retry(request.request_id, actor="local-owner")
    else:
        assert not storage.media_path_exists(storage_path)
        monkeypatch.setattr(VoiceDeletionService, "_complete_request", original)
        completed = service.confirm(
            request.request_id,
            expected_profile_version=2,
            impact_digest=request.impact_digest,
            actor="local-owner",
        )

    assert completed.state == "completed"
    with Session(deletion_engine) as session:
        plans = tuple(
            session.scalars(
                select(VoiceDeletionAssetPlan).where(
                    VoiceDeletionAssetPlan.deletion_request_id == request.request_id
                )
            )
        )
        tombstones = tuple(
            session.scalars(
                select(AssetTombstone).where(
                    AssetTombstone.deletion_request_id == request.request_id
                )
            )
        )
        assert len(plans) == 1 and plans[0].state == "finalized"
        assert len(tombstones) == 1
    assert not storage.media_path_exists(storage_path)
