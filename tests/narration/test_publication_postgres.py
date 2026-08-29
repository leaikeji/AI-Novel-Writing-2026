"""PostgreSQL 18 gate for atomic narration render publication.

The test owns no production state.  It requires an exact loopback disposable
database, publishes immutable files before the database transaction, injects a
failure after both media rows have been flushed, and proves that a new
transaction can adopt the same deterministic files without partial DB state.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from backend.models import (
    BackgroundJob,
    BackgroundJobAttempt,
    DocumentWorkingCopy,
    MediaAsset,
    ModelRunRecord,
    NarrationEdition,
    NarrationEditionSegment,
    NarrationRenderAsset,
    NarrationRequest,
    NarrationSegment,
    NarrationSegmentRender,
    VoiceProfile,
    VoiceProfileVersion,
    VoiceRightsRecord,
)
from backend.narration import publication
from backend.narration.contracts import (
    LOCAL_OWNER_ID,
    LOCAL_WORKSPACE_ID,
    NarrationRequestScope,
)
from backend.narration.editions import CreateEdition, EditionSegmentInput, create_edition
from backend.narration.jobs import (
    JobLease,
    claim_next_job,
    enqueue_job,
    lock_result_publish_fences,
)
from backend.narration.manifest import INITIAL_BUFFER_POLICY
from backend.narration.publication import ModelRunSuccessEvidence, RenderAudioEvidence
from backend.narration.renders import (
    CreateRender,
    create_or_reuse_render,
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
from backend.narration.storage import NarrationStorage, PublishedFile
from tests.narration.test_domain_services import (
    NOW,
    SHA_A,
    SHA_B,
    SHA_C,
    _novel,
    _script_segments,
    _seed_document,
)
from tests.narration.test_foundation_integration import POSTPROCESS_FINGERPRINT


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_DATABASE = "ai_novel_world_2026_tts_test"
EXPECTED_USERNAME = "tts_test"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
SCOPE = NarrationRequestScope.fixed_local()
FAULT_MESSAGE = "fault injection: rollback after both ready media rows"


def _repository_head() -> str:
    config = Config(str(ROOT / "alembic.ini"))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"publication gate requires one Alembic head, got {heads!r}")
    return heads[0]


def _live_url() -> str:
    raw = os.environ.get("TTS_TEST_DATABASE_URL", "").strip()
    if not raw:
        pytest.skip("TTS_TEST_DATABASE_URL is not configured")
    parsed = make_url(raw)
    if not parsed.drivername.startswith("postgresql"):
        raise RuntimeError("TTS_TEST_DATABASE_URL must use PostgreSQL")
    if (
        parsed.database != EXPECTED_DATABASE
        or parsed.username != EXPECTED_USERNAME
        or parsed.host not in LOOPBACK_HOSTS
    ):
        raise RuntimeError(
            "publication tests require the exact loopback disposable TTS database identity"
        )
    production = os.environ.get("AI_NOVEL_DATABASE_URL", "").strip()
    if production:
        live = make_url(production)
        if (parsed.host, parsed.port, parsed.database) == (
            live.host,
            live.port,
            live.database,
        ):
            raise RuntimeError("publication test database must differ from production")
    return raw


@pytest.fixture(scope="module")
def publication_pg_engine() -> Engine:
    engine = create_engine(_live_url(), pool_pre_ping=True)
    with engine.connect() as connection:
        server_version = connection.scalar(text("SHOW server_version"))
        assert isinstance(server_version, str) and server_version.startswith("18.")
        assert connection.scalar(text("SELECT current_database()")) == EXPECTED_DATABASE
        assert connection.scalar(text("SELECT current_user")) == EXPECTED_USERNAME
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            _repository_head()
        )
        unique_constraints = set(
            connection.scalars(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE conrelid='narration_segment_renders'::regclass AND contype='u'"
                )
            )
        )
        assert "uq_narration_segment_render_source_job" in unique_constraints
    try:
        yield engine
    finally:
        engine.dispose()


def _storage(tmp_path: Path) -> NarrationStorage:
    models_root = tmp_path / "models"
    media_root = tmp_path / "media"
    models_root.mkdir(mode=0o750)
    media_root.mkdir(mode=0o750)
    return NarrationStorage(models_root=models_root, media_root=media_root)


@dataclass(frozen=True, slots=True)
class PendingPublication:
    request_id: UUID
    request_version: int
    job_id: UUID
    attempt_id: UUID
    render_id: UUID
    novel_id: UUID
    lease: JobLease
    model_fingerprint: str
    prepublication_xmins: dict[str, str]


def _row_xmin(session: Session, table: str, row_id: UUID) -> str:
    allowed = {
        "narration_requests",
        "background_jobs",
        "background_job_attempts",
        "narration_segment_renders",
    }
    if table not in allowed:
        raise AssertionError(f"unapproved xmin table: {table}")
    value = session.scalar(
        text(f"SELECT xmin::text FROM {table} WHERE id = :row_id"),
        {"row_id": row_id},
    )
    assert isinstance(value, str)
    return value


def _seed_scope_foundation(
    session: Session,
) -> tuple[
    SqlAlchemyNarrationStore,
    object,
    object,
    object,
    VoiceProfile,
    VoiceProfileVersion,
]:
    store = SqlAlchemyNarrationStore(session)
    novel = _novel()
    store.add(novel)
    store.flush()
    document, revision = _seed_document(store, novel)
    store.flush()
    store.add(
        DocumentWorkingCopy(
            document_id=document.id,
            base_revision_id=revision.id,
            draft_version=1,
            content_markdown=revision.content_markdown,
            content_hash=revision.content_hash,
        )
    )
    rights = VoiceRightsRecord(
        id=uuid4(),
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        novel_id=novel.id,
        source_kind="preset_license",
        source_identifier=f"preset:publication:{uuid4()}",
        notice_version="rights/1",
        purpose="narration",
        commercial_use=True,
        redistribution=False,
        voice_cloning=True,
        confirmed_actor="owner",
        confirmed_at=NOW,
        expires_at=NOW.replace(year=NOW.year + 1),
        risk_flags_json=[],
    )
    store.add(rights)
    profile = VoiceProfile(
        id=uuid4(),
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        novel_id=novel.id,
        name="Atomic publication preset",
        current_version_id=None,
        status="active",
        version=1,
    )
    store.add(profile)
    store.flush()
    voice = VoiceProfileVersion(
        id=uuid4(),
        profile_id=profile.id,
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        version_number=1,
        source_type="preset",
        state="locked",
        preset_key=f"publication-preset-{uuid4()}",
        rights_record_id=rights.id,
        language="zh-CN",
        seed=7,
        parameters_json={},
        fingerprint=hashlib.sha256(uuid4().bytes).hexdigest(),
        quality_state="accepted",
        activation_basis="preview_confirmed",
        validation_basis="human_accepted",
        locked_actor="owner",
        locked_at=NOW,
    )
    store.add(voice)
    store.flush()
    profile.current_version_id = voice.id
    profile.version = 2
    store.flush()
    return store, novel, document, revision, profile, voice


def _seed_analyzed_request_without_edition(engine: Engine) -> tuple[UUID, UUID]:
    with Session(engine, expire_on_commit=False) as session, session.begin():
        store, novel, document, revision, _profile, _voice = _seed_scope_foundation(
            session
        )
        settings = update_settings(
            store,
            NarrationSettingsUpdate(
                novel_id=novel.id,
                script_review_policy="blockers_only",
                analysis_mode="local_rules_only",
                settings_json={"language": "zh-CN"},
                expected_version=0,
            ),
        )
        snapshot = create_settings_snapshot(
            store,
            CreateSettingsSnapshot(
                novel_id=novel.id,
                settings_version=settings.version,
            ),
        )
        request = create_request(
            store,
            CreateNarrationRequest(
                novel_id=novel.id,
                document_id=document.id,
                source_revision_id=revision.id,
                source_content_hash=revision.content_hash,
                intent="create",
                idempotency_key=f"generation-guard-request-{uuid4()}",
                settings_fingerprint=snapshot.fingerprint,
                explicit_generation_intent_at=NOW,
                explicit_generation_actor="owner",
            ),
        )
        script = create_script_draft(
            store,
            CreateScriptDraft(
                novel_id=novel.id,
                document_id=document.id,
                revision_id=revision.id,
                content_hash=revision.content_hash,
                settings_fingerprint=snapshot.fingerprint,
                analyzer_fingerprint=SHA_A,
                rules_fingerprint=SHA_B,
                idempotency_key=f"generation-guard-script-{uuid4()}",
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
            actor="generation-guard-analyzer",
        )
        approve_script_version(
            store,
            script.id,
            request_id=request.id,
            actor_type="system",
            actor_id="generation-guard-rules",
        )
        request = advance_request_state(
            store,
            request.id,
            expected_version=request.version,
            new_state="analyzed",
            novel_id=novel.id,
            actor="generation-guard-analyzer",
        )
        return request.id, novel.id


def test_deferred_guard_rejects_queued_request_without_edition(
    publication_pg_engine: Engine,
) -> None:
    request_id, novel_id = _seed_analyzed_request_without_edition(
        publication_pg_engine
    )

    with Session(publication_pg_engine, expire_on_commit=False) as session:
        store = SqlAlchemyNarrationStore(session)
        request = store.get(NarrationRequest, request_id, for_update=True)
        assert request is not None and request.state == "analyzed"
        advance_request_state(
            store,
            request.id,
            expected_version=request.version,
            new_state="queued",
            novel_id=novel_id,
            actor="generation-guard-orchestrator",
        )
        with pytest.raises((IntegrityError, DBAPIError)) as caught:
            session.commit()
        assert "requires an Edition in the same transaction" in str(caught.value)
        session.rollback()

    with Session(publication_pg_engine) as session:
        assert session.scalar(
            select(NarrationRequest.state).where(NarrationRequest.id == request_id)
        ) == "analyzed"
        assert session.scalar(
            select(func.count()).select_from(NarrationEdition).where(
                NarrationEdition.request_id == request_id
            )
        ) == 0


def _seed_pending_publication(engine: Engine) -> PendingPublication:
    with Session(engine, expire_on_commit=False) as session, session.begin():
        store, novel, document, revision, profile, voice = _seed_scope_foundation(
            session
        )
        settings = update_settings(
            store,
            NarrationSettingsUpdate(
                novel_id=novel.id,
                script_review_policy="blockers_only",
                analysis_mode="local_rules_only",
                settings_json={"language": "zh-CN"},
                expected_version=0,
            ),
        )
        snapshot = create_settings_snapshot(
            store,
            CreateSettingsSnapshot(
                novel_id=novel.id,
                settings_version=settings.version,
            ),
        )
        request = create_request(
            store,
            CreateNarrationRequest(
                novel_id=novel.id,
                document_id=document.id,
                source_revision_id=revision.id,
                source_content_hash=revision.content_hash,
                intent="create",
                idempotency_key=f"publication-request-{uuid4()}",
                settings_fingerprint=snapshot.fingerprint,
                explicit_generation_intent_at=NOW,
                explicit_generation_actor="owner",
            ),
        )
        script = create_script_draft(
            store,
            CreateScriptDraft(
                novel_id=novel.id,
                document_id=document.id,
                revision_id=revision.id,
                content_hash=revision.content_hash,
                settings_fingerprint=snapshot.fingerprint,
                analyzer_fingerprint=SHA_A,
                rules_fingerprint=SHA_B,
                idempotency_key=f"publication-script-{uuid4()}",
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
            actor="publication-test-analyzer",
        )
        script = approve_script_version(
            store,
            script.id,
            request_id=request.id,
            actor_type="system",
            actor_id="publication-test-rules",
        )
        request = advance_request_state(
            store,
            request.id,
            expected_version=request.version,
            new_state="analyzed",
            novel_id=novel.id,
            actor="publication-test-analyzer",
        )
        request = advance_request_state(
            store,
            request.id,
            expected_version=request.version,
            new_state="queued",
            novel_id=novel.id,
            actor="publication-test-orchestrator",
        )
        segments = store.find_all(
            NarrationSegment,
            script_version_id=script.id,
            order_by=("ordinal",),
        )
        edition = create_edition(
            store,
            CreateEdition(
                novel_id=novel.id,
                document_id=document.id,
                request_id=request.id,
                script_version_id=script.id,
                settings_snapshot_id=snapshot.id,
                tts_fingerprint=SHA_A,
                tokenizer_fingerprint=SHA_B,
                normalizer_fingerprint=SHA_C,
                postprocess_fingerprint=POSTPROCESS_FINGERPRINT,
                buffer_policy_version=INITIAL_BUFFER_POLICY.version,
                created_actor="publication-test-owner",
                digest_keyring=TEST_DIGEST_KEYRING,
                segments=tuple(
                    EditionSegmentInput(
                        segment_id=segment.id,
                        ordinal=segment.ordinal,
                        profile_id=profile.id,
                        voice_version_id=voice.id,
                        resolution_json={"source": "narrator"},
                    )
                    for segment in segments
                ),
            ),
        )
        edition_segment = session.scalars(
            select(NarrationEditionSegment)
            .where(NarrationEditionSegment.edition_id == edition.id)
            .order_by(NarrationEditionSegment.ordinal)
        ).first()
        assert edition_segment is not None
        enqueued = enqueue_job(
            session,
            scope=SCOPE,
            job_kind="narration.segment_render",
            input_hash=render_job_input_hash(
                edition_segment_id=edition_segment.id,
                render_fingerprint=edition_segment.render_fingerprint,
            ),
            idempotency_key=f"publication-render-job-{uuid4()}",
            resource_class="moss-nano",
            novel_id=novel.id,
            request_id=request.id,
        )
        lease = claim_next_job(
            session,
            scope=SCOPE,
            lease_owner=f"publication-worker-{uuid4()}",
            resource_classes=("moss-nano",),
            lease_seconds=900,
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
        session.flush()
        prepublication_xmins = {
            "request": _row_xmin(session, "narration_requests", request.id),
            "job": _row_xmin(session, "background_jobs", enqueued.job_id),
            "attempt": _row_xmin(
                session, "background_job_attempts", lease.fence.attempt_id
            ),
            "render": _row_xmin(session, "narration_segment_renders", render.id),
        }
        return PendingPublication(
            request_id=request.id,
            request_version=request.version,
            job_id=enqueued.job_id,
            attempt_id=lease.fence.attempt_id,
            render_id=render.id,
            novel_id=novel.id,
            lease=lease,
            model_fingerprint=SHA_A,
            prepublication_xmins=prepublication_xmins,
        )


def _publish_files(
    storage: NarrationStorage, pending: PendingPublication
) -> RenderAudioEvidence:
    published: dict[str, PublishedFile] = {}
    for role, extension, payload in (
        ("master", "wav", b"publication-master-immutable-v1"),
        ("playback", "ogg", b"publication-playback-immutable-v1"),
    ):
        digest = hashlib.sha256(payload).hexdigest()
        published[role] = storage.publish_media(
            [payload],
            asset_id=publication.render_asset_id(pending.render_id, role),
            expected_sha256=digest,
            expected_size=len(payload),
            extension=extension,
            max_bytes=len(payload),
        )
    return RenderAudioEvidence(
        master=published["master"],
        playback=published["playback"],
        duration_ms=1200,
        sample_rate=48_000,
        channels=2,
    )


def _model_evidence(pending: PendingPublication) -> ModelRunSuccessEvidence:
    return ModelRunSuccessEvidence(
        requested_provider_id="fake",
        requested_model_id="fake-moss-nano",
        requested_revision="publication-test-v1",
        actual_provider_id="fake",
        actual_model_id="fake-moss-nano",
        actual_revision="publication-test-v1",
        model_fingerprint=pending.model_fingerprint,
        parameters_digest="d" * 64,
        input_digest_key_id="publication-test-key",
        input_digest="e" * 64,
        duration_ms=1200,
        provider_request_id="publication-test-request",
    )


def _assert_files_retained(
    storage: NarrationStorage, audio: RenderAudioEvidence
) -> None:
    for published in (audio.master, audio.playback):
        identity = storage.verify_media_identity(
            published.relative_path,
            expected_sha256=published.actual_sha256,
            expected_size=published.byte_size,
            max_bytes=published.byte_size,
        )
        assert (identity.device, identity.inode, identity.byte_size) == (
            published.device,
            published.inode,
            published.byte_size,
        )


def test_atomic_render_publication_rolls_back_and_re_adopts_deterministic_files(
    publication_pg_engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = publication_pg_engine
    pending = _seed_pending_publication(engine)
    storage = _storage(tmp_path)
    audio = _publish_files(storage, pending)
    model = _model_evidence(pending)
    assert audio.master.asset_id == publication.render_asset_id(
        pending.render_id, "master"
    )
    assert audio.playback.asset_id == publication.render_asset_id(
        pending.render_id, "playback"
    )

    real_apply = publication.apply_ready_evidence_in_session
    ready_calls = 0
    failed_xid: str | None = None

    def fail_after_second_ready(*args: object, **kwargs: object) -> MediaAsset:
        nonlocal ready_calls
        asset = real_apply(*args, **kwargs)
        ready_calls += 1
        if ready_calls == 2:
            raise RuntimeError(FAULT_MESSAGE)
        return asset

    with monkeypatch.context() as fault:
        fault.setattr(
            publication,
            "apply_ready_evidence_in_session",
            fail_after_second_ready,
        )
        with pytest.raises(RuntimeError, match="rollback after both ready media rows"):
            with Session(engine, expire_on_commit=False) as session, session.begin():
                failed_xid = session.scalar(text("SELECT pg_current_xact_id()::text"))
                context = lock_result_publish_fences(
                    session,
                    scope=SCOPE,
                    job_fence=pending.lease.fence,
                    resource_fence=pending.lease.resource_fence,
                )
                publication.publish_render_result_in_session(
                    session,
                    storage,
                    render_id=pending.render_id,
                    publication_context=context,
                    audio=audio,
                    model=model,
                )
    assert ready_calls == 2
    assert isinstance(failed_xid, str)

    with Session(engine, expire_on_commit=False) as session:
        request = session.get(NarrationRequest, pending.request_id)
        job = session.get(BackgroundJob, pending.job_id)
        attempt = session.get(BackgroundJobAttempt, pending.attempt_id)
        render = session.get(NarrationSegmentRender, pending.render_id)
        assert request is not None and request.state == "queued"
        assert request.allows_render is True and request.sources_sealed_at is not None
        assert request.version == pending.request_version
        assert job is not None and job.state == "running"
        assert job.request_id == request.id
        assert attempt is not None and attempt.job_id == job.id
        assert attempt.completed_at is None and attempt.actual_result_digest is None
        assert render is not None and render.state == "pending"
        assert render.request_id == request.id and render.source_job_id == job.id
        assert render.ready_at is None and render.duration_ms is None
        assert render.audio_validation_json == {}
        assert session.scalar(
            select(ModelRunRecord.id).where(ModelRunRecord.attempt_id == pending.attempt_id)
        ) is None
        assert session.scalars(
            select(MediaAsset).where(
                MediaAsset.id.in_((audio.master.asset_id, audio.playback.asset_id))
            )
        ).all() == []
        assert session.scalars(
            select(NarrationRenderAsset).where(
                NarrationRenderAsset.render_id == pending.render_id
            )
        ).all() == []
        assert {
            "request": _row_xmin(session, "narration_requests", pending.request_id),
            "job": _row_xmin(session, "background_jobs", pending.job_id),
            "attempt": _row_xmin(
                session, "background_job_attempts", pending.attempt_id
            ),
            "render": _row_xmin(session, "narration_segment_renders", pending.render_id),
        } == pending.prepublication_xmins
        assert failed_xid not in pending.prepublication_xmins.values()
    _assert_files_retained(storage, audio)

    with Session(engine, expire_on_commit=False) as session, session.begin():
        context = lock_result_publish_fences(
            session,
            scope=SCOPE,
            job_fence=pending.lease.fence,
            resource_fence=pending.lease.resource_fence,
        )
        published = publication.publish_render_result_in_session(
            session,
            storage,
            render_id=pending.render_id,
            publication_context=context,
            audio=audio,
            model=model,
        )
        assert published.state == "ready"
        successful_xid = session.scalar(text("SELECT pg_current_xact_id()::text"))
        assert isinstance(successful_xid, str) and successful_xid != failed_xid

    with Session(engine, expire_on_commit=False) as session:
        request = session.get(NarrationRequest, pending.request_id)
        job = session.get(BackgroundJob, pending.job_id)
        attempt = session.get(BackgroundJobAttempt, pending.attempt_id)
        render = session.get(NarrationSegmentRender, pending.render_id)
        model_runs = session.scalars(
            select(ModelRunRecord).where(ModelRunRecord.attempt_id == pending.attempt_id)
        ).all()
        assets = session.scalars(
            select(MediaAsset).where(
                MediaAsset.id.in_((audio.master.asset_id, audio.playback.asset_id))
            )
        ).all()
        links = session.scalars(
            select(NarrationRenderAsset).where(
                NarrationRenderAsset.render_id == pending.render_id
            )
        ).all()
        assert request is not None and request.state == "queued"
        assert request.allows_render is True and request.sources_sealed_at is not None
        assert request.version == pending.request_version
        assert job is not None and job.state == "succeeded"
        assert job.request_id == request.id and job.request_allows_render is True
        assert attempt is not None and attempt.job_id == job.id
        assert attempt.completed_at is not None
        assert attempt.actual_result_digest == audio.playback.actual_sha256
        assert render is not None and render.state == "ready"
        assert render.request_id == request.id and render.source_job_id == job.id
        assert render.novel_id == request.novel_id == pending.novel_id
        assert render.duration_ms == 1200 and render.ready_at is not None
        assert len(model_runs) == 1
        assert model_runs[0].attempt_id == attempt.id
        assert model_runs[0].result_classification == "success"
        assert model_runs[0].output_digest == audio.playback.actual_sha256
        assert len(assets) == 2 and {asset.id for asset in assets} == {
            audio.master.asset_id,
            audio.playback.asset_id,
        }
        assets_by_id = {asset.id: asset for asset in assets}
        for published_file in (audio.master, audio.playback):
            asset = assets_by_id[published_file.asset_id]
            assert asset.storage_path == published_file.relative_path
            assert asset.content_hash == published_file.actual_sha256
            assert asset.byte_size == published_file.byte_size
        assert all(
            asset.state == "ready"
            and asset.novel_id == pending.novel_id
            and asset.owner_id == request.owner_id
            and asset.workspace_id == request.workspace_id
            for asset in assets
        )
        assert len(links) == 2 and {link.role for link in links} == {
            "master",
            "playback",
        }
        assert {link.asset_id for link in links} == {
            audio.master.asset_id,
            audio.playback.asset_id,
        }
        links_by_role = {link.role: link for link in links}
        assert links_by_role["master"].actual_sha256 == audio.master.actual_sha256
        assert links_by_role["playback"].actual_sha256 == (
            audio.playback.actual_sha256
        )

        publication_xmins = {
            session.scalar(
                text("SELECT xmin::text FROM background_jobs WHERE id = :id"),
                {"id": pending.job_id},
            ),
            session.scalar(
                text("SELECT xmin::text FROM background_job_attempts WHERE id = :id"),
                {"id": pending.attempt_id},
            ),
            session.scalar(
                text("SELECT xmin::text FROM narration_segment_renders WHERE id = :id"),
                {"id": pending.render_id},
            ),
            *session.scalars(
                text("SELECT xmin::text FROM model_run_records WHERE attempt_id = :id"),
                {"id": pending.attempt_id},
            ).all(),
            *session.scalars(
                text("SELECT xmin::text FROM media_assets WHERE id IN (:master, :playback)"),
                {"master": audio.master.asset_id, "playback": audio.playback.asset_id},
            ).all(),
            *session.scalars(
                text("SELECT xmin::text FROM narration_render_assets WHERE render_id = :id"),
                {"id": pending.render_id},
            ).all(),
        }
        assert publication_xmins == {successful_xid}
        assert _row_xmin(session, "narration_requests", pending.request_id) == (
            pending.prepublication_xmins["request"]
        )
    _assert_files_retained(storage, audio)
