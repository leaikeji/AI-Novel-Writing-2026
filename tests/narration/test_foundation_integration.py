from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from backend.models import (
    BackgroundJob,
    BackgroundJobAttempt,
    DocumentRevision,
    DocumentWorkingCopy,
    MediaAsset,
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
from backend.narration.adapters import FakeMossNanoTTSAdapter
from backend.narration.contracts import (
    LOCAL_OWNER_ID,
    LOCAL_WORKSPACE_ID,
    NarrationRequestScope,
    SynthesisRequest,
)
from backend.narration.editions import CreateEdition, EditionSegmentInput, create_edition
from backend.narration.fingerprints import model_fingerprint_sha256
from backend.narration.jobs import (
    claim_next_job,
    enqueue_job,
    lock_result_publish_fences,
)
from backend.narration.manifest import INITIAL_BUFFER_POLICY
from backend.narration.publication import (
    ModelRunSuccessEvidence,
    RenderAudioEvidence,
    publish_render_result_in_session,
    render_asset_id,
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
from backend.narration.script_versions import (
    CreateScriptDraft,
    approve_script_version,
    create_script_draft,
)
from backend.narration.services import (
    InvalidNarrationState,
    NarrationScopeMismatch,
    SqlAlchemyNarrationStore,
)
from backend.narration.settings import NarrationSettingsUpdate, update_settings
from backend.narration.snapshots import CreateSettingsSnapshot, create_settings_snapshot
from backend.narration.storage import NarrationStorage
from tests.narration.digest_fixtures import TEST_DIGEST_KEYRING
from tests.narration.test_crash_recovery import _t1g_live_url
from tests.narration.test_domain_services import (
    NOW,
    SHA_A,
    SHA_B,
    SHA_C,
    MemoryNarrationStore,
    _approved_foundation,
    _novel,
    _seed_document,
    _seed_render_job,
    _script_segments,
)


POSTPROCESS_FINGERPRINT = "d" * 64


def _source_guard(
    store: MemoryNarrationStore,
    *,
    document_id: object,
    revision: DocumentRevision,
) -> tuple[str, str, int, str]:
    working_copy = DocumentWorkingCopy(
        document_id=document_id,
        base_revision_id=revision.id,
        draft_version=7,
        content_markdown="authoritative working copy",
        content_hash=hashlib.sha256(b"authoritative working copy").hexdigest(),
    )
    store.add(working_copy)
    return (
        revision.content_markdown,
        revision.content_hash,
        working_copy.draft_version,
        working_copy.content_hash,
    )


def _assert_source_guard(
    store: MemoryNarrationStore,
    *,
    revision: DocumentRevision,
    expected: tuple[str, str, int, str],
) -> None:
    working_copy = store.rows[DocumentWorkingCopy][0]
    assert (
        revision.content_markdown,
        revision.content_hash,
        working_copy.draft_version,
        working_copy.content_hash,
    ) == expected


def _queued_edition(
    store: MemoryNarrationStore,
) -> tuple[object, object, DocumentRevision, NarrationRequest, NarrationEdition, object]:
    (
        novel,
        document,
        revision,
        snapshot,
        request,
        _script,
        version,
        profile,
        voice,
        _rights,
    ) = _approved_foundation(store)
    approve_script_version(
        store,
        version.id,
        request_id=request.id,
        actor_type="system",
        actor_id="rules-v1",
    )
    request = advance_request_state(
        store,
        request.id,
        expected_version=request.version,
        new_state="queued",
        novel_id=novel.id,
        actor="orchestrator",
    )
    script_segments = store.find_all(
        NarrationSegment,
        script_version_id=version.id,
        order_by=("ordinal",),
    )
    edition = create_edition(
        store,
        CreateEdition(
            novel_id=novel.id,
            document_id=document.id,
            request_id=request.id,
            script_version_id=version.id,
            settings_snapshot_id=snapshot.id,
            tts_fingerprint=SHA_A,
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
                    resolution_json={"source": "narrator"},
                    gap_after_ms=100,
                )
                for segment in script_segments
            ),
        ),
    )
    return novel, document, revision, request, edition, voice


def _attach_fake_result_assets(
    store: MemoryNarrationStore,
    *,
    novel_id: object,
    render: NarrationSegmentRender,
    master_digest: str,
) -> str:
    playback_digest = hashlib.sha256(
        bytes.fromhex(master_digest) + b"deterministic-playback"
    ).hexdigest()
    for role, digest, mime_type in (
        ("master", master_digest, "audio/wav"),
        ("playback", playback_digest, "audio/ogg"),
    ):
        asset = MediaAsset(
            id=uuid4(),
            owner_id=render.owner_id,
            workspace_id=render.workspace_id,
            novel_id=novel_id,
            kind=f"narration_segment_{role}",
            asset_class=f"segment_{role}",
            mime_type=mime_type,
            byte_size=4096,
            duration_ms=1200,
            sample_rate=48_000,
            channels=2,
            storage_backend="local",
            state="ready",
            retention_policy="narration",
            checksum_algorithm="sha256",
            validation_json={"source": "fake-adapter"},
            verified_at=NOW,
            gc_generation=0,
            storage_path=f"narration/integration/{render.id}/{role}",
            content_hash=digest,
            metadata_json={},
        )
        store.add(asset)
        store.add(
            NarrationRenderAsset(
                id=uuid4(),
                render_id=render.id,
                asset_id=asset.id,
                role=role,
                actual_sha256=digest,
            )
        )
    return playback_digest


def _storage(tmp_path: Path) -> NarrationStorage:
    models_root = tmp_path / "models"
    media_root = tmp_path / "media"
    models_root.mkdir(mode=0o750)
    media_root.mkdir(mode=0o750)
    models_root.chmod(0o750)
    media_root.chmod(0o750)
    return NarrationStorage(models_root=models_root, media_root=media_root)


@pytest.fixture
def t1g_domain_pg_session() -> Session:
    engine = create_engine(_t1g_live_url(), pool_pre_ping=True)
    connection = engine.connect()
    outer = connection.begin()
    head = connection.scalar(text("SELECT version_num FROM alembic_version"))
    if head != "20260826_0015":
        outer.rollback()
        connection.close()
        engine.dispose()
        raise RuntimeError("T1-G domain integration requires exact Alembic head 0015")
    session = Session(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        yield session
    finally:
        session.close()
        if outer.is_active:
            outer.rollback()
        connection.close()
        engine.dispose()


def _seed_live_domain_foundation(
    session: Session,
) -> tuple[
    SqlAlchemyNarrationStore,
    object,
    object,
    DocumentRevision,
    DocumentWorkingCopy,
    VoiceProfile,
    VoiceProfileVersion,
]:
    store = SqlAlchemyNarrationStore(session)
    novel = _novel()
    store.add(novel)
    store.flush()
    document, revision = _seed_document(store, novel)
    store.flush()
    working_copy = DocumentWorkingCopy(
        document_id=document.id,
        base_revision_id=revision.id,
        draft_version=1,
        content_markdown=revision.content_markdown,
        content_hash=revision.content_hash,
    )
    store.add(working_copy)
    store.flush()
    rights = VoiceRightsRecord(
        id=uuid4(),
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        novel_id=novel.id,
        source_kind="preset_license",
        source_identifier="preset:t1-g",
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
    store.flush()
    profile = VoiceProfile(
        id=uuid4(),
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        novel_id=novel.id,
        name="T1-G preset",
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
        preset_key="t1-g-preset",
        rights_record_id=rights.id,
        language="zh-CN",
        seed=7,
        parameters_json={},
        fingerprint=SHA_B,
        quality_state="accepted",
        locked_actor="owner",
        locked_at=NOW,
    )
    store.add(voice)
    store.flush()
    profile.current_version_id = voice.id
    profile.version = 2
    store.flush()
    return store, novel, document, revision, working_copy, profile, voice


def test_fake_adapter_domain_pipeline_reuses_cache_and_never_changes_source() -> None:
    store = MemoryNarrationStore()
    novel, document, revision, request, edition, voice = _queued_edition(store)
    source_before = _source_guard(
        store,
        document_id=document.id,
        revision=revision,
    )
    edition_segment = store.find_all(
        NarrationEditionSegment,
        edition_id=edition.id,
        order_by=("ordinal",),
    )[0]
    segment = store.get(NarrationSegment, edition_segment.segment_id)
    assert segment is not None

    adapter = FakeMossNanoTTSAdapter()
    synthesis_request = SynthesisRequest(
        request_id=uuid4(),
        scope=NarrationRequestScope.fixed_local(),
        text=segment.spoken_text,
        voice=str(voice.id),
        seed=voice.seed,
        sample_mode="deterministic-integration",
        max_new_frames=1024,
    )
    first_audio = asyncio.run(adapter.synthesize(synthesis_request))
    replay_audio = asyncio.run(adapter.synthesize(synthesis_request))
    assert first_audio.actual_output_sha256 == replay_audio.actual_output_sha256
    assert first_audio.audio_bytes == replay_audio.audio_bytes
    assert adapter.capabilities.is_test_double is True
    assert adapter.capabilities.product_visible is False

    job, publication_context = _seed_render_job(
        store,
        request=request,
        marker=41,
        edition_segment=edition_segment,
    )
    render, reused = create_or_reuse_render(
        store,
        CreateRender(
            edition_segment_id=edition_segment.id,
            digest_keyring=TEST_DIGEST_KEYRING,
            source_job_id=job.id,
        ),
    )
    assert reused is False
    playback_digest = _attach_fake_result_assets(
        store,
        novel_id=novel.id,
        render=render,
        master_digest=first_audio.actual_output_sha256,
    )
    published = publish_render_ready(
        store,
        render.id,
        publication_context=publication_context,
    )
    assert published.state == "ready"
    assert published.audio_validation_json["master_sha256"] == first_audio.actual_output_sha256
    assert published.audio_validation_json["playback_sha256"] == playback_digest

    cached, cache_hit = create_or_reuse_render(
        store,
        CreateRender(
            edition_segment_id=edition_segment.id,
            digest_keyring=TEST_DIGEST_KEYRING,
        ),
    )
    assert cache_hit is True and cached is render
    assert len(store.rows[NarrationSegmentRender]) == 1
    assert len(store.rows[BackgroundJob]) == 1
    _assert_source_guard(store, revision=revision, expected=source_before)


def test_render_cache_poisoned_across_novel_scope_is_rejected() -> None:
    store = MemoryNarrationStore()
    novel, _document, _revision, request, edition, _voice = _queued_edition(store)
    edition_segment = store.find_all(
        NarrationEditionSegment,
        edition_id=edition.id,
        order_by=("ordinal",),
    )[0]
    job, _publication_context = _seed_render_job(
        store,
        request=request,
        marker=42,
        edition_segment=edition_segment,
    )
    render, reused = create_or_reuse_render(
        store,
        CreateRender(
            edition_segment_id=edition_segment.id,
            digest_keyring=TEST_DIGEST_KEYRING,
            source_job_id=job.id,
        ),
    )
    assert reused is False and render.novel_id == novel.id
    foreign = _novel()
    store.add(foreign)
    render.novel_id = foreign.id
    with pytest.raises(NarrationScopeMismatch, match="cross novel scope"):
        create_or_reuse_render(
            store,
            CreateRender(
                edition_segment_id=edition_segment.id,
                digest_keyring=TEST_DIGEST_KEYRING,
            ),
        )
    assert len(store.rows[NarrationSegmentRender]) == 1


def test_analyze_only_cannot_enter_generation_or_create_edition_or_render() -> None:
    store = MemoryNarrationStore()
    novel = _novel()
    store.add(novel)
    document, revision = _seed_document(store, novel)
    request = create_request(
        store,
        CreateNarrationRequest(
            novel_id=novel.id,
            document_id=document.id,
            source_revision_id=revision.id,
            source_content_hash=revision.content_hash,
            intent="analyze_only",
            idempotency_key=f"scan-{uuid4()}",
            settings_fingerprint=SHA_A,
        ),
    )
    assert request.allows_edition is False and request.allows_render is False
    with pytest.raises(InvalidNarrationState, match="invalid request transition|analyze_only"):
        advance_request_state(
            store,
            request.id,
            expected_version=request.version,
            new_state="queued",
            novel_id=novel.id,
            actor="forbidden-orchestrator",
        )
    with pytest.raises(InvalidNarrationState, match="analyze_only"):
        create_edition(
            store,
            CreateEdition(
                novel_id=novel.id,
                document_id=document.id,
                request_id=request.id,
                script_version_id=uuid4(),
                settings_snapshot_id=uuid4(),
                tts_fingerprint=SHA_A,
                tokenizer_fingerprint=SHA_B,
                normalizer_fingerprint=SHA_C,
                postprocess_fingerprint=POSTPROCESS_FINGERPRINT,
                buffer_policy_version=INITIAL_BUFFER_POLICY.version,
                created_actor="forbidden-orchestrator",
                digest_keyring=TEST_DIGEST_KEYRING,
                segments=(),
            ),
        )
    assert store.rows[NarrationEdition] == []
    assert store.rows[NarrationSegmentRender] == []
    assert store.rows[MediaAsset] == []


def test_fake_adapter_publication_failure_leaves_no_target_or_db_media(
    tmp_path: Path,
) -> None:
    store = MemoryNarrationStore()
    _novel_row, document, revision, _request, _edition, _voice = _queued_edition(store)
    source_before = _source_guard(
        store,
        document_id=document.id,
        revision=revision,
    )
    adapter = FakeMossNanoTTSAdapter()
    result = asyncio.run(
        adapter.synthesize(
            SynthesisRequest(
                request_id=uuid4(),
                scope=NarrationRequestScope.fixed_local(),
                text="failure injection must not change the novel",
                voice="test-voice",
                seed=19,
                sample_mode="producer-crash",
                max_new_frames=1024,
            )
        )
    )
    storage = _storage(tmp_path)

    def crashing_stream():
        midpoint = len(result.audio_bytes) // 2
        yield result.audio_bytes[:midpoint]
        raise RuntimeError("injected adapter stream crash")

    with pytest.raises(RuntimeError, match="injected adapter stream crash"):
        storage.publish_media(
            crashing_stream(),
            asset_id=uuid4(),
            expected_sha256=result.actual_output_sha256,
            expected_size=len(result.audio_bytes),
            extension="wav",
            max_bytes=len(result.audio_bytes),
        )
    assert list(storage.media.path.rglob("*.wav")) == []
    assert list(storage.media.path.rglob("*.part")) == []
    assert store.rows[MediaAsset] == []
    assert store.rows[NarrationRenderAsset] == []
    assert store.rows[NarrationSegmentRender] == []
    _assert_source_guard(store, revision=revision, expected=source_before)


def test_live_postgresql_fake_adapter_to_ready_render_cache_rolls_back(
    t1g_domain_pg_session: Session,
    tmp_path: Path,
) -> None:
    session = t1g_domain_pg_session
    (
        store,
        novel,
        document,
        revision,
        working_copy,
        profile,
        voice,
    ) = _seed_live_domain_foundation(session)
    source_before = (
        revision.content_markdown,
        revision.content_hash,
        working_copy.draft_version,
        working_copy.content_hash,
    )
    adapter = FakeMossNanoTTSAdapter()
    adapter_model = asyncio.run(adapter.model_fingerprint())
    tts_fingerprint = model_fingerprint_sha256(adapter_model)
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
            idempotency_key=f"t1-g-domain-{uuid4()}",
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
            idempotency_key=f"t1-g-script-{uuid4()}",
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
        actor="analyzer",
    )
    version = approve_script_version(
        store,
        version.id,
        request_id=request.id,
        actor_type="system",
        actor_id="rules-v1",
    )
    request = advance_request_state(
        store,
        request.id,
        expected_version=request.version,
        new_state="queued",
        novel_id=novel.id,
        actor="orchestrator",
    )
    segments = store.find_all(
        NarrationSegment,
        script_version_id=version.id,
        order_by=("ordinal",),
    )
    edition = create_edition(
        store,
        CreateEdition(
            novel_id=novel.id,
            document_id=document.id,
            request_id=request.id,
            script_version_id=version.id,
            settings_snapshot_id=snapshot.id,
            tts_fingerprint=tts_fingerprint,
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
                    resolution_json={"source": "narrator"},
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
    render_input_hash = render_job_input_hash(
        edition_segment_id=edition_segment.id,
        render_fingerprint=edition_segment.render_fingerprint,
    )
    enqueued = enqueue_job(
        session,
        scope=NarrationRequestScope.fixed_local(),
        job_kind="narration.segment_render",
        input_hash=render_input_hash,
        idempotency_key=f"t1-g-domain-render-{uuid4()}",
        resource_class="moss-nano",
        novel_id=novel.id,
        request_id=request.id,
    )
    lease = claim_next_job(
        session,
        scope=NarrationRequestScope.fixed_local(),
        lease_owner=f"t1-g-domain-worker-{uuid4()}",
        resource_classes=("moss-nano",),
    )
    assert lease is not None and lease.resource_fence is not None
    render, reused = create_or_reuse_render(
        store,
        CreateRender(
            edition_segment_id=edition_segment.id,
            digest_keyring=TEST_DIGEST_KEYRING,
            source_job_id=enqueued.job_id,
        ),
    )
    assert reused is False

    synthesis = asyncio.run(
        adapter.synthesize(
            SynthesisRequest(
                request_id=uuid4(),
                scope=NarrationRequestScope.fixed_local(),
                text=segments[0].spoken_text,
                voice=str(voice.id),
                seed=voice.seed,
                sample_mode="postgresql-integration",
                max_new_frames=1024,
            )
        )
    )
    storage = _storage(tmp_path)
    master = storage.publish_media(
        [synthesis.audio_bytes],
        asset_id=render_asset_id(render.id, "master"),
        expected_sha256=synthesis.actual_output_sha256,
        expected_size=len(synthesis.audio_bytes),
        extension="wav",
        max_bytes=len(synthesis.audio_bytes),
    )
    playback = storage.publish_media(
        [synthesis.audio_bytes],
        asset_id=render_asset_id(render.id, "playback"),
        expected_sha256=synthesis.actual_output_sha256,
        expected_size=len(synthesis.audio_bytes),
        extension="ogg",
        max_bytes=len(synthesis.audio_bytes),
    )
    publication_context = lock_result_publish_fences(
        session,
        scope=NarrationRequestScope.fixed_local(),
        job_fence=lease.fence,
        resource_fence=lease.resource_fence,
    )
    published_render = publish_render_result_in_session(
        session,
        storage,
        render_id=render.id,
        publication_context=publication_context,
        audio=RenderAudioEvidence(
            master=master,
            playback=playback,
            duration_ms=1200,
            sample_rate=48_000,
            channels=2,
        ),
        model=ModelRunSuccessEvidence(
            requested_provider_id="fake",
            requested_model_id=adapter_model.model_name,
            requested_revision=adapter_model.model_revision,
            actual_provider_id="fake",
            actual_model_id=adapter_model.model_name,
            actual_revision=adapter_model.model_revision,
            model_fingerprint=tts_fingerprint,
            parameters_digest="3" * 64,
            input_digest_key_id="t1-g-test",
            input_digest="4" * 64,
            duration_ms=1200,
        ),
    )
    assert published_render.id == render.id and published_render.state == "ready"
    cached, cache_hit = create_or_reuse_render(
        store,
        CreateRender(
            edition_segment_id=edition_segment.id,
            digest_keyring=TEST_DIGEST_KEYRING,
        ),
    )
    assert cache_hit is True and cached.id == render.id
    job = session.get(BackgroundJob, enqueued.job_id)
    attempt = session.get(BackgroundJobAttempt, lease.fence.attempt_id)
    assert job is not None and job.state == "succeeded"
    assert attempt is not None
    assert attempt.actual_result_digest == playback.actual_sha256
    assert (
        revision.content_markdown,
        revision.content_hash,
        working_copy.draft_version,
        working_copy.content_hash,
    ) == source_before
    session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    session.execute(text("SET CONSTRAINTS ALL DEFERRED"))


def test_foundation_orm_catalog_contains_frozen_cross_layer_columns() -> None:
    expected_columns = {
        "narration_requests": {
            "owner_id",
            "workspace_id",
            "novel_id",
            "intent",
            "allows_edition",
            "allows_render",
            "request_hash",
        },
        "narration_settings_snapshots": {
            "owner_id",
            "workspace_id",
            "novel_id",
            "fingerprint",
            "snapshot_json",
        },
        "narration_script_versions": {
            "immutable_hash",
            "settings_fingerprint",
            "approval_request_id",
            "is_approved",
        },
        "narration_editions": {
            "request_id",
            "script_version_id",
            "settings_snapshot_id",
            "edition_fingerprint",
        },
        "narration_segment_renders": {
            "request_id",
            "render_fingerprint",
            "source_job_id",
            "state",
        },
        "media_assets": {
            "storage_path",
            "content_hash",
            "state",
            "gc_generation",
        },
    }
    metadata = NarrationRequest.metadata
    for table_name, required in expected_columns.items():
        assert table_name in metadata.tables
        assert required <= set(metadata.tables[table_name].columns.keys())
