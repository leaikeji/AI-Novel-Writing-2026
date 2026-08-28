"""Live PostgreSQL + filesystem gates for asset-scoped narration media.

These tests are intentionally skipped unless ``TTS_TEST_DATABASE_URL`` names
the exact loopback disposable test database.  The database is expected to be
empty and migrated to the repository's single Alembic head by the caller.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from backend.models import (
    MediaAsset,
    ModelRunRecord,
    NarrationEditionSegment,
    NarrationRenderAsset,
    NarrationSegment,
    NarrationSegmentRender,
    VoiceProfile,
    VoiceProfileVersion,
    VoiceRightsRecord,
)
from backend.narration.contracts import (
    LOCAL_OWNER_ID,
    LOCAL_WORKSPACE_ID,
    NarrationRequestScope,
)
from backend.narration.editions import CreateEdition, EditionSegmentInput, create_edition
from backend.narration.jobs import claim_next_job, enqueue_job, lock_result_publish_fences
from backend.narration.manifest import INITIAL_BUFFER_POLICY
from backend.narration.media import (
    apply_ready_evidence_in_session,
    begin_gc_deletion_in_session,
    execute_gc_delete,
    finalize_gc_deletion_in_session,
    plan_media_read_in_session,
    stream_read_decision,
)
from backend.narration.renders import (
    CreateRender,
    create_or_reuse_render,
    publish_render_ready,
    render_job_input_hash,
)
from backend.narration.requests import (
    CreateNarrationRequest,
    advance_request_state,
    create_request,
)
from tests.narration.digest_fixtures import TEST_DIGEST_KEYRING
from backend.narration.script_versions import (
    CreateScriptDraft,
    approve_script_version,
    create_script_draft,
)
from backend.narration.services import SqlAlchemyNarrationStore
from backend.narration.settings import NarrationSettingsUpdate, update_settings
from backend.narration.snapshots import CreateSettingsSnapshot, create_settings_snapshot
from backend.narration.storage import NarrationStorage
from tests.narration.test_domain_services import (
    NOW,
    SHA_A,
    SHA_B,
    SHA_C,
    _novel,
    _script_segments,
    _seed_document,
)


POSTPROCESS_FINGERPRINT = "d" * 64


def _expected_alembic_head() -> str:
    repository_root = Path(__file__).resolve().parents[2]
    script = ScriptDirectory.from_config(Config(str(repository_root / "alembic.ini")))
    heads = script.get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"asset-scoped media tests require one Alembic head, got {heads!r}")
    return heads[0]


def _live_url() -> str:
    raw = os.environ.get("TTS_TEST_DATABASE_URL", "").strip()
    if not raw:
        pytest.skip("TTS_TEST_DATABASE_URL is not configured")
    parsed = make_url(raw)
    if (
        parsed.database != "ai_novel_world_2026_tts_test"
        or parsed.username != "tts_test"
        or parsed.host not in {"127.0.0.1", "localhost", "::1"}
    ):
        raise RuntimeError(
            "asset-scoped media tests require the exact loopback disposable test database"
        )
    production = os.environ.get("AI_NOVEL_DATABASE_URL", "").strip()
    if production:
        production_url = make_url(production)
        if (parsed.host, parsed.port, parsed.database) == (
            production_url.host,
            production_url.port,
            production_url.database,
        ):
            raise RuntimeError("asset-scoped media tests refuse the configured production DB")
    return raw


@pytest.fixture(scope="module")
def engine() -> Engine:
    database = create_engine(_live_url(), pool_pre_ping=True)
    with database.connect() as connection:
        identity = connection.execute(
            text("SELECT current_database(), current_user, version()")
        ).one()
        assert identity[0] == "ai_novel_world_2026_tts_test"
        assert identity[1] == "tts_test"
        assert "PostgreSQL 18" in identity[2]
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            _expected_alembic_head()
        )
    try:
        yield database
    finally:
        database.dispose()


def _storage(tmp_path: Path) -> NarrationStorage:
    models_root = tmp_path / "models"
    media_root = tmp_path / "media"
    models_root.mkdir(mode=0o750)
    media_root.mkdir(mode=0o750)
    return NarrationStorage(models_root=models_root, media_root=media_root)


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class _RenderFixture:
    novel_id: UUID
    render_id: UUID
    segment_id: UUID
    attempt_id: UUID | None
    lease: object | None
    model_fingerprint: str


def _prepare_render(
    session: Session,
    *,
    marker: str,
    claim: bool,
) -> _RenderFixture:
    """Create a real novel -> script segment -> edition -> render chain."""

    store = SqlAlchemyNarrationStore(session)
    novel = _novel()
    novel.title = f"asset-scope-{marker}-{novel.id}"
    store.add(novel)
    store.flush()
    document, revision = _seed_document(store, novel, marker=marker)
    store.flush()

    rights = VoiceRightsRecord(
        id=uuid4(),
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        novel_id=novel.id,
        source_kind="preset_license",
        source_identifier=f"preset:asset-scope:{novel.id}",
        notice_version="rights/1",
        purpose="narration",
        commercial_use=True,
        redistribution=False,
        voice_cloning=True,
        confirmed_actor="owner",
        confirmed_at=NOW,
        expires_at=NOW + timedelta(days=365),
        risk_flags_json=[],
    )
    store.add(rights)
    store.flush()
    profile = VoiceProfile(
        id=uuid4(),
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        novel_id=novel.id,
        name=f"asset-scope-{marker}",
        current_version_id=None,
        status="active",
        version=1,
    )
    store.add(profile)
    store.flush()
    voice_fingerprint = _sha(novel.id.bytes + b":voice")
    voice = VoiceProfileVersion(
        id=uuid4(),
        profile_id=profile.id,
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        version_number=1,
        source_type="preset",
        state="locked",
        preset_key=f"asset-scope-{novel.id}",
        rights_record_id=rights.id,
        language="zh-CN",
        seed=7,
        parameters_json={},
        fingerprint=voice_fingerprint,
        quality_state="accepted",
        locked_actor="owner",
        locked_at=NOW,
    )
    store.add(voice)
    store.flush()
    profile.current_version_id = voice.id
    profile.version = 2
    store.flush()

    settings = update_settings(
        store,
        NarrationSettingsUpdate(
            novel_id=novel.id,
            script_review_policy="blockers_only",
            analysis_mode="local_rules_only",
            settings_json={"language": "zh-CN", "asset_scope_fixture": str(novel.id)},
            expected_version=0,
        ),
    )
    snapshot = create_settings_snapshot(
        store,
        CreateSettingsSnapshot(novel_id=novel.id, settings_version=settings.version),
    )
    request = create_request(
        store,
        CreateNarrationRequest(
            novel_id=novel.id,
            document_id=document.id,
            source_revision_id=revision.id,
            source_content_hash=revision.content_hash,
            intent="create",
            idempotency_key=f"asset-scope-request-{uuid4()}",
            settings_fingerprint=snapshot.fingerprint,
            explicit_generation_intent_at=NOW,
            explicit_generation_actor="owner",
        ),
    )
    version = create_script_draft(
        store,
        CreateScriptDraft(
            novel_id=novel.id,
            document_id=document.id,
            revision_id=revision.id,
            content_hash=revision.content_hash,
            settings_fingerprint=snapshot.fingerprint,
            analyzer_fingerprint=SHA_A,
            rules_fingerprint=SHA_B,
            idempotency_key=f"asset-scope-script-{uuid4()}",
            effective_policy="blockers_only",
            segments=_script_segments(),
        ),
    )
    request = advance_request_state(
        store,
        request.id,
        expected_version=request.version,
        new_state="analyzing",
        novel_id=novel.id,
        actor="asset-scope-analyzer",
    )
    version = approve_script_version(
        store,
        version.id,
        request_id=request.id,
        actor_type="system",
        actor_id="asset-scope-rules-v1",
    )
    request = advance_request_state(
        store,
        request.id,
        expected_version=request.version,
        new_state="queued",
        novel_id=novel.id,
        actor="asset-scope-orchestrator",
    )
    segments = store.find_all(
        NarrationSegment,
        script_version_id=version.id,
        order_by=("ordinal",),
    )
    model_fingerprint = _sha(novel.id.bytes + b":model")
    edition = create_edition(
        store,
        CreateEdition(
            novel_id=novel.id,
            document_id=document.id,
            request_id=request.id,
            script_version_id=version.id,
            settings_snapshot_id=snapshot.id,
            tts_fingerprint=model_fingerprint,
            tokenizer_fingerprint=SHA_B,
            normalizer_fingerprint=SHA_C,
            postprocess_fingerprint=POSTPROCESS_FINGERPRINT,
            buffer_policy_version=INITIAL_BUFFER_POLICY.version,
            created_actor="owner",
            digest_keyring=TEST_DIGEST_KEYRING,
            segments=tuple(
                EditionSegmentInput(
                    segment_id=segment.id,
                    ordinal=segment.ordinal,
                    profile_id=profile.id,
                    voice_version_id=voice.id,
                    resolution_json={"source": "asset-scope-test"},
                )
                for segment in segments
            ),
        ),
    )
    edition_segment = store.find_all(
        NarrationEditionSegment,
        edition_id=edition.id,
        order_by=("ordinal",),
    )[0]
    input_hash = render_job_input_hash(
        edition_segment_id=edition_segment.id,
        render_fingerprint=edition_segment.render_fingerprint,
    )
    enqueued = enqueue_job(
        session,
        scope=NarrationRequestScope.fixed_local(),
        job_kind="narration.segment_render",
        input_hash=input_hash,
        idempotency_key=f"asset-scope-render-job-{uuid4()}",
        resource_class="moss-nano",
        novel_id=novel.id,
        request_id=request.id,
        # Keep a rerun's new publication job ahead of any deliberately
        # abandoned pending-render fixture left by an earlier successful run.
        base_priority=1000 if claim else -1000,
    )
    lease = None
    if claim:
        lease = claim_next_job(
            session,
            scope=NarrationRequestScope.fixed_local(),
            lease_owner=f"asset-scope-worker-{uuid4()}",
            resource_classes=("moss-nano",),
        )
        assert lease is not None and lease.resource_fence is not None
        assert lease.fence.job_id == enqueued.job_id
    render, reused = create_or_reuse_render(
        store,
        CreateRender(
            edition_segment_id=edition_segment.id,
            digest_keyring=TEST_DIGEST_KEYRING,
            source_job_id=enqueued.job_id,
        ),
    )
    assert reused is False
    assert render.canonical_input_json["schema_version"] == "narration-render-input/3"
    assert "segment_id" not in render.canonical_input_json
    assert "canonical_spoken_text_hash" not in render.canonical_input_json
    return _RenderFixture(
        novel_id=novel.id,
        render_id=render.id,
        segment_id=edition_segment.segment_id,
        attempt_id=lease.fence.attempt_id if lease is not None else None,
        lease=lease,
        model_fingerprint=model_fingerprint,
    )


def _new_asset(
    *,
    published,
    novel_id: UUID,
    asset_class: str,
    mime_type: str | None = None,
    metadata_json: dict[str, object] | None = None,
) -> MediaAsset:
    return MediaAsset(
        id=published.asset_id,
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        novel_id=novel_id,
        kind=f"narration_{asset_class}",
        asset_class=asset_class,
        mime_type=mime_type,
        byte_size=published.byte_size,
        duration_ms=1000,
        sample_rate=48_000,
        channels=2,
        storage_backend="local",
        state="staging",
        retention_policy="derivable",
        checksum_algorithm="sha256",
        validation_json={},
        gc_generation=0,
        storage_path=published.relative_path,
        content_hash=published.actual_sha256,
        metadata_json=metadata_json or {},
    )


def _publish_ready_render(
    session: Session,
    storage: NarrationStorage,
    fixture: _RenderFixture,
    *,
    payload: bytes,
) -> tuple[UUID, UUID]:
    assert fixture.lease is not None and fixture.attempt_id is not None
    digest = _sha(payload)
    master = storage.publish_media(
        [payload],
        asset_id=uuid4(),
        expected_sha256=digest,
        expected_size=len(payload),
        extension="wav",
        max_bytes=len(payload),
    )
    playback = storage.publish_media(
        [payload],
        asset_id=uuid4(),
        expected_sha256=digest,
        expected_size=len(payload),
        extension="ogg",
        max_bytes=len(payload),
    )
    context = lock_result_publish_fences(
        session,
        scope=NarrationRequestScope.fixed_local(),
        job_fence=fixture.lease.fence,
        resource_fence=fixture.lease.resource_fence,
    )
    db_now = session.scalar(select(func.clock_timestamp()))
    assert db_now is not None
    session.add(
        ModelRunRecord(
            id=uuid4(),
            attempt_id=fixture.attempt_id,
            requested_provider_id="asset-scope-test",
            requested_model_id="fake-moss-nano",
            requested_revision="asset-scope/1",
            actual_provider_id="asset-scope-test",
            actual_model_id="fake-moss-nano",
            actual_revision="asset-scope/1",
            model_fingerprint=fixture.model_fingerprint,
            parameters_digest=_sha(b"asset-scope-parameters"),
            input_digest_key_id="asset-scope-test-key-v1",
            input_digest=_sha(b"asset-scope-input"),
            output_digest=playback.actual_sha256,
            duration_ms=1000,
            result_classification="success",
            created_at=db_now,
        )
    )
    session.flush()
    for role, published, mime_type in (
        ("master", master, "audio/wav"),
        ("playback", playback, "audio/ogg"),
    ):
        asset = _new_asset(
            published=published,
            novel_id=fixture.novel_id,
            asset_class=f"segment_{role}",
            metadata_json={
                "render_id": str(fixture.render_id),
                "segment_id": str(fixture.segment_id),
            },
        )
        session.add(asset)
        session.flush()
        apply_ready_evidence_in_session(
            session,
            storage,
            asset_id=asset.id,
            published=published,
            mime_type=mime_type,
            validation={"source": "asset-scope-live-test"},
            structured_parent_state="ready_in_same_transaction",
        )
        session.add(
            NarrationRenderAsset(
                id=uuid4(),
                render_id=fixture.render_id,
                asset_id=asset.id,
                role=role,
                actual_sha256=published.actual_sha256,
            )
        )
        session.flush()
    publish_render_ready(
        SqlAlchemyNarrationStore(session),
        fixture.render_id,
        publication_context=context,
    )
    return master.asset_id, playback.asset_id


def _age_staging_asset_for_gc(engine: Engine, asset_id: UUID) -> None:
    """Time-travel one disposable fixture without weakening the tested transaction."""

    with engine.begin() as connection:
        assert connection.scalar(text("SELECT rolsuper FROM pg_roles WHERE rolname=current_user"))
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        connection.execute(
            text(
                "UPDATE media_assets SET created_at=clock_timestamp()-interval '25 hours' "
                "WHERE id=:asset"
            ),
            {"asset": asset_id},
        )
        connection.execute(text("SET LOCAL session_replication_role = origin"))
        assert connection.scalar(text("SHOW session_replication_role")) == "origin"


def test_cross_novel_master_playback_same_bytes_are_isolated_and_gc_safe(
    engine: Engine,
    tmp_path: Path,
) -> None:
    storage = _storage(tmp_path)
    payload = b"asset-scoped-identical-master-playback-bytes"
    digest = _sha(payload)

    with Session(engine, expire_on_commit=False) as session, session.begin():
        playback_fixture = _prepare_render(session, marker="b", claim=True)
        _master_id, playback_id = _publish_ready_render(
            session,
            storage,
            playback_fixture,
            payload=payload,
        )

    with Session(engine, expire_on_commit=False) as session, session.begin():
        master_fixture = _prepare_render(session, marker="a", claim=False)
        master_file = storage.publish_media(
            [payload],
            asset_id=uuid4(),
            expected_sha256=digest,
            expected_size=len(payload),
            extension="wav",
            max_bytes=len(payload),
        )
        staged_master = _new_asset(
            published=master_file,
            novel_id=master_fixture.novel_id,
            asset_class="segment_master",
            mime_type="audio/wav",
            metadata_json={
                "render_id": str(master_fixture.render_id),
                "segment_id": str(master_fixture.segment_id),
                "publication_phase": "filesystem_published",
            },
        )
        session.add(staged_master)
        session.flush()
        staged_master_id = staged_master.id

    with Session(engine) as session:
        playback_asset = session.get(MediaAsset, playback_id)
        assert playback_asset is not None and playback_asset.state == "ready"
        assert playback_asset.asset_class == "segment_playback"
        assert playback_asset.content_hash == digest
        assert playback_asset.novel_id == playback_fixture.novel_id
        assert playback_fixture.novel_id != master_fixture.novel_id
        assert playback_fixture.render_id != master_fixture.render_id
        assert playback_fixture.segment_id != master_fixture.segment_id
        assert playback_asset.storage_path != master_file.relative_path
        playback_path = playback_asset.storage_path

    master_stat = storage.media_stat(master_file.relative_path)
    playback_stat = storage.media_stat(playback_path)
    assert (master_stat.st_dev, master_stat.st_ino) != (
        playback_stat.st_dev,
        playback_stat.st_ino,
    )
    assert b"".join(storage.stream_media(master_file.relative_path)) == payload
    assert b"".join(storage.stream_media(playback_path)) == payload

    _age_staging_asset_for_gc(engine, staged_master_id)
    with Session(engine, expire_on_commit=False) as session, session.begin():
        plan = begin_gc_deletion_in_session(
            session,
            storage,
            asset_id=staged_master_id,
            expected_generation=0,
        )
    assert plan.relative_path == master_file.relative_path
    assert plan.content_hash == digest
    result = execute_gc_delete(storage, plan)
    assert result.removed and result.verified_absent
    with Session(engine) as session, session.begin():
        finalize_gc_deletion_in_session(
            session,
            storage,
            asset_id=staged_master_id,
            digest_key_id="asset-scope-live-key-v1",
            digest_key=b"k" * 32,
            deleted_actor="asset-scope-live-test",
        )

    assert not storage.media_path_exists(master_file.relative_path)
    assert storage.media_path_exists(playback_path)
    with Session(engine) as session, session.begin():
        deleted = session.get(MediaAsset, staged_master_id)
        retained = session.get(MediaAsset, playback_id)
        assert deleted is not None and deleted.state == "deleted"
        assert retained is not None and retained.state == "ready"
        decision = plan_media_read_in_session(
            session,
            storage,
            asset_id=playback_id,
            method="GET",
        )
        assert decision.status == 200
        assert b"".join(stream_read_decision(storage, decision)) == payload


@pytest.mark.parametrize(
    "corruption",
    ("asset_id", "prefix", "hash", "extension"),
)
def test_database_rejects_each_noncanonical_asset_scoped_path(
    engine: Engine,
    corruption: str,
) -> None:
    novel_id = uuid4()
    asset_id = uuid4()
    digest = _sha(f"bad-path-{corruption}-{asset_id}".encode("ascii"))
    other_id = uuid4()
    prefix = asset_id.hex[:2]
    path = f"assets/{prefix}/{asset_id.hex}/{digest}.wav"
    if corruption == "asset_id":
        path = f"assets/{other_id.hex[:2]}/{other_id.hex}/{digest}.wav"
    elif corruption == "prefix":
        wrong_prefix = "ff" if prefix != "ff" else "ee"
        path = f"assets/{wrong_prefix}/{asset_id.hex}/{digest}.wav"
    elif corruption == "hash":
        wrong_digest = "0" * 64 if digest != "0" * 64 else "1" * 64
        path = f"assets/{prefix}/{asset_id.hex}/{wrong_digest}.wav"
    elif corruption == "extension":
        path = f"assets/{prefix}/{asset_id.hex}/{digest}.txt"

    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(
                text("INSERT INTO novels (id,title,description,version) VALUES (:id,:title,'',1)"),
                {"id": novel_id, "title": f"bad-path-{corruption}-{novel_id}"},
            )
            savepoint = connection.begin_nested()
            try:
                with pytest.raises(DBAPIError):
                    connection.execute(
                        text(
                            """
                            INSERT INTO media_assets
                              (id,owner_id,workspace_id,novel_id,kind,asset_class,
                               byte_size,storage_backend,state,retention_policy,
                               checksum_algorithm,validation_json,gc_generation,storage_path,
                               content_hash,metadata_json)
                            VALUES
                              (:id,:owner,:workspace,:novel,'narration_preview','preview',4,
                               'local','staging','derivable','sha256','{}'::jsonb,0,:path,
                               :digest,'{}'::jsonb)
                            """
                        ),
                        {
                            "id": asset_id,
                            "owner": LOCAL_OWNER_ID,
                            "workspace": LOCAL_WORKSPACE_ID,
                            "novel": novel_id,
                            "path": path,
                            "digest": digest,
                        },
                    )
                    savepoint.commit()
            finally:
                if savepoint.is_active:
                    savepoint.rollback()
        finally:
            transaction.rollback()


def test_published_file_is_re_adopted_after_precommit_database_abort(
    engine: Engine,
    tmp_path: Path,
) -> None:
    storage = _storage(tmp_path)
    novel_id, asset_id = uuid4(), uuid4()
    payload = b"asset-scope-publish-before-database-commit"
    digest = _sha(payload)
    expected_path = f"assets/{asset_id.hex[:2]}/{asset_id.hex}/{digest}.wav"

    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO novels (id,title,description,version) VALUES (:id,:title,'',1)"),
            {"id": novel_id, "title": f"re-adopt-{novel_id}"},
        )
        connection.execute(
            text(
                """
                INSERT INTO media_assets
                  (id,owner_id,workspace_id,novel_id,kind,asset_class,byte_size,
                   storage_backend,state,retention_policy,checksum_algorithm,
                   validation_json,gc_generation,storage_path,content_hash,metadata_json)
                VALUES
                  (:id,:owner,:workspace,:novel,'narration_preview','preview',:size,
                   'local','staging','derivable','sha256','{}'::jsonb,0,:path,:digest,
                   '{}'::jsonb)
                """
            ),
            {
                "id": asset_id,
                "owner": LOCAL_OWNER_ID,
                "workspace": LOCAL_WORKSPACE_ID,
                "novel": novel_id,
                "size": len(payload),
                "path": expected_path,
                "digest": digest,
            },
        )

    published = storage.publish_media(
        [payload],
        asset_id=asset_id,
        expected_sha256=digest,
        expected_size=len(payload),
        extension="wav",
        max_bytes=len(payload),
    )
    assert published.relative_path == expected_path

    class _SimulatedPrecommitAbort(RuntimeError):
        pass

    with pytest.raises(_SimulatedPrecommitAbort):
        with Session(engine) as session, session.begin():
            apply_ready_evidence_in_session(
                session,
                storage,
                asset_id=asset_id,
                published=published,
                mime_type="audio/wav",
                validation={"attempt": "rolled-back"},
            )
            raise _SimulatedPrecommitAbort("simulated process failure before DB commit")

    with Session(engine) as session:
        rolled_back = session.get(MediaAsset, asset_id)
        assert rolled_back is not None and rolled_back.state == "staging"
        assert rolled_back.verified_at is None
    assert storage.media_path_exists(expected_path)

    re_adopted = storage.verify_existing_media(
        expected_path,
        expected_sha256=digest,
        expected_size=len(payload),
        max_bytes=len(payload),
    )
    assert re_adopted.asset_id == asset_id
    assert re_adopted.relative_path == published.relative_path
    assert (re_adopted.device, re_adopted.inode) == (published.device, published.inode)
    with Session(engine) as session, session.begin():
        recovered = apply_ready_evidence_in_session(
            session,
            storage,
            asset_id=asset_id,
            published=re_adopted,
            mime_type="audio/wav",
            validation={"recovery": "verify_existing_media"},
        )
        assert recovered.state == "ready"

    with Session(engine) as session, session.begin():
        recovered = session.get(MediaAsset, asset_id)
        assert recovered is not None and recovered.state == "ready"
        decision = plan_media_read_in_session(
            session,
            storage,
            asset_id=asset_id,
            method="GET",
        )
        assert b"".join(stream_read_decision(storage, decision)) == payload
