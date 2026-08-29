"""Real PostgreSQL concurrency gate for the T4 script-review backend.

The module is intentionally inert unless ``TTS_TEST_DATABASE_URL`` identifies
the exact disposable loopback PostgreSQL 18 database owned by ``tts_test`` at
the current Alembic head.  Seeds are random and retained, so the suite is repeatable
without deleting any pre-existing test data.
"""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

from backend.models import (
    BackgroundJob,
    CharacterVoiceBinding,
    Document,
    DocumentRevision,
    NarrationEdition,
    NarrationEditionSegment,
    NarrationRequest,
    NarrationScriptReviewActionRecord,
    NarrationScriptVersion,
    NarrationSegmentRender,
    NarrationSettingsSnapshot,
    NovelCharacter,
    NovelNarrationSettings,
    VoiceProfile,
    VoiceProfileVersion,
    VoiceRightsEvent,
    VoiceRightsRecord,
)
from backend.narration import edition_service as edition_service_module
from backend.narration import schemas as wire
from backend.narration import script_backend as script_backend_module
from backend.narration.contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID
from backend.narration.edition_service import NarrationProductionPolicy
from backend.narration.privacy import (
    FIXED_LOCAL_OWNER_NARRATION_AUTHORIZATION,
    _storage_settings,
    build_narration_settings_backend,
    default_narration_settings_values,
)
from backend.narration.requests import CreateNarrationRequest, create_request
from backend.narration.script_api import (
    AnalyzeScriptRequest,
    ApproveScriptRequest,
    ScriptApiCommand,
    ScriptApiOperation,
    ScriptReviewResource,
    ScriptState,
    ScriptSpeakerKind,
    SegmentReviewPatch,
)
from backend.narration.script_backend import (
    SqlAlchemyScriptApiBackend,
    build_script_api_backend,
)
from backend.narration.script_contracts import CastingTargetKind, text_sha256
from backend.narration.script_versions import load_script_contract
from backend.narration.services import (
    IdempotencyConflict,
    InvalidNarrationState,
    NarrationCasConflict,
    SqlAlchemyNarrationStore,
)
from backend.narration.settings_api import (
    NarrationApiFault,
    NarrationSettingsApiCommand,
    NarrationSettingsOperation,
)
from backend.narration.snapshots import (
    CreateSettingsSnapshot,
    create_settings_snapshot,
)
from tests.narration.digest_fixtures import TEST_DIGEST_KEYRING
from tests.narration.test_domain_services import _novel


EXPECTED_DATABASE = "ai_novel_world_2026_tts_test"
EXPECTED_USERNAME = "tts_test"
EXPECTED_HEAD = "20260829_0032"
NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
POLICY = NarrationProductionPolicy(
    tts_fingerprint="a" * 64,
    tokenizer_fingerprint="b" * 64,
    normalizer_fingerprint="c" * 64,
    postprocess_fingerprint="d" * 64,
    digest_keyring=TEST_DIGEST_KEYRING,
)


def _enabled_voice_lock_capabilities() -> wire.NarrationCapabilities:
    enabled = {
        wire.CapabilityKey.NARRATION_PRODUCT,
        wire.CapabilityKey.READING_SETTINGS,
    }
    return wire.NarrationCapabilities(
        items=[
            wire.FeatureCapability(
                key=item.key,
                state=wire.CapabilityState.ENABLED,
                visible=True,
                actionable=True,
                reason_code=None,
                required_gate=None,
            )
            if item.key in enabled
            else item.model_copy(deep=True)
            for item in wire.t2_hold_capabilities().items
        ]
    )


def _live_url() -> str:
    raw = os.environ.get("TTS_TEST_DATABASE_URL", "").strip()
    if not raw:
        pytest.skip("TTS_TEST_DATABASE_URL is not configured")
    parsed = make_url(raw)
    if (
        not parsed.drivername.startswith("postgresql")
        or parsed.database != EXPECTED_DATABASE
        or parsed.username != EXPECTED_USERNAME
        or parsed.host not in {"127.0.0.1", "localhost", "::1"}
    ):
        raise RuntimeError(
            "script-review backend concurrency requires the exact disposable "
            "loopback PostgreSQL database"
        )
    production = os.environ.get("AI_NOVEL_DATABASE_URL", "").strip()
    if production:
        configured = make_url(production)
        if (parsed.host, parsed.port, parsed.database) == (
            configured.host,
            configured.port,
            configured.database,
        ):
            raise RuntimeError(
                "script-review backend concurrency refuses the production database"
            )
    return raw


@pytest.fixture(scope="module")
def pg_engine() -> Engine:
    engine = create_engine(
        _live_url(),
        pool_pre_ping=True,
        connect_args={
            "options": "-c statement_timeout=20000 -c lock_timeout=10000"
        },
    )
    with engine.connect() as connection:
        identity = connection.execute(
            text("SELECT current_database(), current_user, version()")
        ).one()
        assert identity[0] == EXPECTED_DATABASE
        assert identity[1] == EXPECTED_USERNAME
        assert "PostgreSQL 18" in identity[2]
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            EXPECTED_HEAD
        )
        deferred = dict(
            connection.execute(
                text(
                    """SELECT tgname, tgdeferrable AND tginitdeferred
                       FROM pg_trigger
                       WHERE NOT tgisinternal
                         AND tgname IN (
                           'trg_t4_review_action_required',
                           'trg_t4_manual_script_approval_required',
                           'trg_t4_review_action_target_required'
                         )"""
                )
            ).all()
        )
        assert deferred == {
            "trg_t4_review_action_required": True,
            "trg_t4_manual_script_approval_required": True,
            "trg_t4_review_action_target_required": True,
        }
    try:
        yield engine
    finally:
        engine.dispose()


@dataclass(frozen=True, slots=True)
class _Voice:
    profile_id: UUID
    version_id: UUID


@dataclass(frozen=True, slots=True)
class _ReviewSeed:
    novel_id: UUID
    document_id: UUID
    revision_id: UUID
    request_id: UUID
    request_version: int
    settings_fingerprint: str
    resource: ScriptReviewResource
    characters: dict[str, UUID]


@dataclass(frozen=True, slots=True)
class _Outcome:
    value: object | None = None
    error: BaseException | None = None


def _create_voice(
    session: Session,
    *,
    marker: str,
    novel_id: UUID | None,
) -> _Voice:
    rights = VoiceRightsRecord(
        id=uuid4(),
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        novel_id=novel_id,
        source_kind="preset_catalog",
        source_identifier=f"preset:t4-rc-backend:{marker}:{uuid4()}",
        notice_version="voice-rights/1",
        purpose="narration",
        commercial_use=True,
        redistribution=False,
        voice_cloning=True,
        confirmed_actor="owner",
        confirmed_at=NOW,
        expires_at=NOW + timedelta(days=365),
        risk_flags_json=[],
    )
    profile = VoiceProfile(
        id=uuid4(),
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        novel_id=novel_id,
        name=f"t4-rc-{marker}",
        current_version_id=None,
        status="active",
        version=1,
    )
    session.add(rights)
    session.add(profile)
    session.flush()
    version = VoiceProfileVersion(
        id=uuid4(),
        profile_id=profile.id,
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        version_number=1,
        source_type="preset",
        state="locked",
        preset_key=f"t4-rc-{marker}-{uuid4()}",
        rights_record_id=rights.id,
        language="zh-CN",
        seed=7,
        parameters_json={},
        fingerprint=text_sha256(f"t4-rc-voice:{marker}:{uuid4()}"),
        quality_state="accepted",
        activation_basis="preview_confirmed",
        validation_basis="human_accepted",
        locked_actor="owner",
        locked_at=NOW,
    )
    session.add(version)
    session.flush()
    profile.current_version_id = version.id
    profile.version = 2
    session.flush()
    return _Voice(profile_id=profile.id, version_id=version.id)


def _shared_voice_pair(engine: Engine, *, marker: str) -> tuple[_Voice, _Voice]:
    with Session(engine, expire_on_commit=False) as session, session.begin():
        first = _create_voice(session, marker=f"{marker}-v1", novel_id=None)
        second = _create_voice(session, marker=f"{marker}-v2", novel_id=None)
    return first, second


def _seed_review(
    engine: Engine,
    *,
    marker: str,
    source: str,
    character_voices: tuple[tuple[str, _Voice], ...],
) -> _ReviewSeed:
    novel = _novel()
    novel.title = f"t4-rc-backend-{marker}-{novel.id}"
    document_id = uuid4()
    revision_id = uuid4()
    content_hash = text_sha256(source)
    character_ids: dict[str, UUID] = {}

    with Session(engine, expire_on_commit=False) as session, session.begin():
        session.add(novel)
        session.flush()
        narrator = _create_voice(
            session,
            marker=f"{marker}-narrator",
            novel_id=novel.id,
        )
        document = Document(
            id=document_id,
            novel_id=novel.id,
            kind="chapter",
            title=f"{marker} chapter",
            position=1,
            status="draft",
            version=1,
        )
        revision = DocumentRevision(
            id=revision_id,
            document_id=document.id,
            revision_number=1,
            content_markdown=source,
            content_text=source,
            content_hash=content_hash,
            source="manual",
        )
        session.add(document)
        session.add(revision)
        for position, (name, voice) in enumerate(character_voices):
            character = NovelCharacter(
                id=uuid4(),
                novel_id=novel.id,
                role_type="supporting",
                name=name,
                description="",
                details={},
                lifecycle_state="active",
                position=position,
                version=1,
            )
            character_ids[name] = character.id
            session.add(character)
            session.flush()
            session.add(
                CharacterVoiceBinding(
                    id=uuid4(),
                    novel_id=novel.id,
                    character_id=character.id,
                    profile_id=voice.profile_id,
                    voice_version_id=voice.version_id,
                    binding_policy="dedicated",
                    language="zh-CN",
                    parameters_json={},
                    version=1,
                )
            )

        values = default_narration_settings_values().model_copy(
            update={
                "narrator": wire.NarratorVoiceSelection(
                    profile_id=narrator.profile_id,
                    version_id=narrator.version_id,
                ),
                "script_review_policy": wire.ScriptReviewPolicy.ALWAYS_REVIEW,
            }
        )
        session.add(
            NovelNarrationSettings(
                id=uuid4(),
                novel_id=novel.id,
                narrator_profile_id=narrator.profile_id,
                narrator_version_id=narrator.version_id,
                script_review_policy=values.script_review_policy.value,
                analysis_mode=values.analysis_mode.value,
                settings_json=_storage_settings(values),
                version=1,
            )
        )
        session.flush()
        store = SqlAlchemyNarrationStore(session)
        snapshot = create_settings_snapshot(
            store,
            CreateSettingsSnapshot(novel_id=novel.id, settings_version=1),
        )
        request = create_request(
            store,
            CreateNarrationRequest(
                novel_id=novel.id,
                document_id=document.id,
                source_revision_id=revision.id,
                source_content_hash=revision.content_hash,
                intent="create",
                idempotency_key=f"t4-rc-request-{marker}-{uuid4().hex}",
                settings_fingerprint=snapshot.fingerprint,
                force_review=True,
                effective_policy="always_review",
                explicit_generation_intent_at=datetime.now(UTC),
                explicit_generation_actor="owner",
            ),
        )
        request_id = request.id
        settings_fingerprint = snapshot.fingerprint

    analyze = ScriptApiCommand(
        operation=ScriptApiOperation.ANALYZE_SCRIPT,
        document_id=document_id,
        idempotency_key=f"t4-rc-analysis-{marker}-{uuid4().hex}",
        payload=AnalyzeScriptRequest(
            request_id=request_id,
            source_revision_id=revision_id,
            source_content_hash=content_hash,
        ),
    )
    with Session(engine, expire_on_commit=False) as session:
        resource = build_script_api_backend(
            session,
            production_policy_provider=lambda: POLICY,
        ).dispatch(analyze)
    assert isinstance(resource, ScriptReviewResource)
    with Session(engine) as session:
        request = session.get(NarrationRequest, request_id)
        assert request is not None
        request_version = request.version
        assert request.state == "review_required"
        assert request.current_review_version_id == resource.script_version_id
    return _ReviewSeed(
        novel_id=novel.id,
        document_id=document_id,
        revision_id=revision_id,
        request_id=request_id,
        request_version=request_version,
        settings_fingerprint=settings_fingerprint,
        resource=resource,
        characters=character_ids,
    )


def _approve_command(
    seed: _ReviewSeed,
    *,
    key: str,
) -> ScriptApiCommand:
    return ScriptApiCommand(
        operation=ScriptApiOperation.APPROVE_SCRIPT_VERSION,
        version_id=seed.resource.script_version_id,
        idempotency_key=key,
        payload=ApproveScriptRequest(
            request_id=seed.request_id,
            expected_request_version=seed.request_version,
            expected_version_number=seed.resource.version_number,
            expected_immutable_hash=seed.resource.immutable_hash,
            source_revision_id=seed.revision_id,
            confirmed=True,
        ),
    )


def _patch_command(
    seed: _ReviewSeed,
    *,
    key: str,
    character_name: str | None = None,
) -> ScriptApiCommand:
    target = next(
        (
            segment
            for segment in seed.resource.segments
            if segment.speaker_kind is ScriptSpeakerKind.UNKNOWN
        ),
        seed.resource.segments[0],
    )
    if character_name is None:
        speaker_kind = ScriptSpeakerKind.NARRATOR
        character_id = None
    else:
        speaker_kind = ScriptSpeakerKind.CHARACTER
        character_id = seed.characters[character_name]
    return ScriptApiCommand(
        operation=ScriptApiOperation.PATCH_SEGMENT,
        version_id=seed.resource.script_version_id,
        segment_id=target.segment_id,
        idempotency_key=key,
        payload=SegmentReviewPatch(
            request_id=seed.request_id,
            expected_request_version=seed.request_version,
            expected_version_number=seed.resource.version_number,
            expected_immutable_hash=seed.resource.immutable_hash,
            expected_local_hash=target.local_hash,
            speaker_kind=speaker_kind,
            speaker_label="client label is non-authoritative",
            character_id=character_id,
            spoken_text=target.spoken_text,
            reason="PostgreSQL backend concurrency gate",
        ),
    )


def _run_pair(
    engine: Engine,
    commands: tuple[ScriptApiCommand, ScriptApiCommand],
    *,
    backend_factory: Callable[[Session, int], SqlAlchemyScriptApiBackend] | None = None,
) -> tuple[_Outcome, _Outcome]:
    start = threading.Barrier(2)

    def run(index: int) -> _Outcome:
        try:
            start.wait(timeout=5)
            with Session(engine, expire_on_commit=False) as session:
                backend = (
                    backend_factory(session, index)
                    if backend_factory is not None
                    else build_script_api_backend(
                        session,
                        production_policy_provider=lambda: POLICY,
                    )
                )
                return _Outcome(value=backend.dispatch(commands[index]))
        except Exception as error:  # captured for deterministic pair assertions
            return _Outcome(error=error)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run, index) for index in range(2)]
        return (futures[0].result(timeout=30), futures[1].result(timeout=30))


def _sqlstate(error: BaseException) -> str | None:
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        original = getattr(current, "orig", None)
        for candidate in (current, original):
            state = getattr(candidate, "sqlstate", None) or getattr(
                candidate, "pgcode", None
            )
            if state:
                return str(state)
        current = current.__cause__ or current.__context__
    return None


def _assert_pair_succeeded(outcomes: tuple[_Outcome, _Outcome]) -> None:
    failures = [item.error for item in outcomes if item.error is not None]
    assert not failures, [
        {
            "type": type(error).__name__,
            "sqlstate": _sqlstate(error),
            "message": str(error),
        }
        for error in failures
    ]
    assert all(isinstance(item.value, ScriptReviewResource) for item in outcomes)


def _soft_barrier_wait(barrier: threading.Barrier) -> None:
    try:
        barrier.wait(timeout=1.5)
    except threading.BrokenBarrierError:
        # A corrected stable lock plan can serialize before the second worker
        # reaches this probe.  The timeout must then release the first worker.
        pass


def _shared_voice_order(
    engine: Engine,
    seed: _ReviewSeed,
    *,
    shared_ids: frozenset[UUID],
) -> tuple[UUID, ...]:
    with Session(engine) as session:
        store = SqlAlchemyNarrationStore(session)
        contract = load_script_contract(store, seed.resource.script_version_id)
        snapshot = session.scalar(
            select(NarrationSettingsSnapshot).where(
                NarrationSettingsSnapshot.fingerprint == seed.settings_fingerprint,
                NarrationSettingsSnapshot.novel_id == seed.novel_id,
            )
        )
        assert snapshot is not None
        resolved = snapshot.snapshot_json["resolved_settings"]
        assert isinstance(resolved, dict)
        result: list[UUID] = []
        for segment in contract.segments:
            target = segment.casting.final_target
            if target is None:
                continue
            if target.kind is CastingTargetKind.PROFILE:
                voice_id = UUID(str(resolved["narrator_version_id"]))
            elif target.kind is CastingTargetKind.CHARACTER_BINDING:
                binding = session.get(CharacterVoiceBinding, target.binding_id)
                assert binding is not None and binding.voice_version_id is not None
                voice_id = binding.voice_version_id
            else:
                continue
            if voice_id in shared_ids:
                result.append(voice_id)
        return tuple(result)


def _request_counts(engine: Engine, request_id: UUID) -> dict[str, int]:
    with Session(engine) as session:
        request = session.get(NarrationRequest, request_id)
        assert request is not None and request.review_script_id is not None
        return {
            "versions": int(
                session.scalar(
                    select(func.count())
                    .select_from(NarrationScriptVersion)
                    .where(
                        NarrationScriptVersion.script_id == request.review_script_id
                    )
                )
                or 0
            ),
            "actions": int(
                session.scalar(
                    select(func.count())
                    .select_from(NarrationScriptReviewActionRecord)
                    .where(
                        NarrationScriptReviewActionRecord.request_id == request_id
                    )
                )
                or 0
            ),
            "editions": int(
                session.scalar(
                    select(func.count())
                    .select_from(NarrationEdition)
                    .where(NarrationEdition.request_id == request_id)
                )
                or 0
            ),
            "edition_segments": int(
                session.scalar(
                    select(func.count())
                    .select_from(NarrationEditionSegment)
                    .join(
                        NarrationEdition,
                        NarrationEdition.id == NarrationEditionSegment.edition_id,
                    )
                    .where(NarrationEdition.request_id == request_id)
                )
                or 0
            ),
            "jobs": int(
                session.scalar(
                    select(func.count())
                    .select_from(BackgroundJob)
                    .where(BackgroundJob.request_id == request_id)
                )
                or 0
            ),
            "renders": int(
                session.scalar(
                    select(func.count())
                    .select_from(NarrationSegmentRender)
                    .where(NarrationSegmentRender.request_id == request_id)
                )
                or 0
            ),
        }


def _voice_graph_state(
    engine: Engine,
    *,
    profile_id: UUID,
    version_id: UUID,
) -> tuple[object, ...]:
    with Session(engine) as session:
        profile = session.get(VoiceProfile, profile_id)
        version = session.get(VoiceProfileVersion, version_id)
        assert profile is not None and version is not None
        event_count = int(
            session.scalar(
                select(func.count())
                .select_from(VoiceRightsEvent)
                .where(VoiceRightsEvent.rights_record_id == version.rights_record_id)
            )
            or 0
        )
        return (
            profile.status,
            profile.version,
            profile.current_version_id,
            version.state,
            version.quality_state,
            version.locked_at,
            event_count,
        )


def test_reverse_voice_approval_lock_plan_has_no_postgresql_deadlock(
    pg_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    voice_one, voice_two = _shared_voice_pair(pg_engine, marker="approve-lock")
    seed_one = _seed_review(
        pg_engine,
        marker="approve-lock-a",
        source=(
            "“第一句。”甲舟说道。\n\n---\n\n"
            "乙岛说道：“第二句。”"
        ),
        character_voices=(("甲舟", voice_one), ("乙岛", voice_two)),
    )
    seed_two = _seed_review(
        pg_engine,
        marker="approve-lock-b",
        source=(
            "“第一句。”丙川说道。\n\n---\n\n"
            "丁岭说道：“第二句。”"
        ),
        character_voices=(("丙川", voice_two), ("丁岭", voice_one)),
    )
    assert seed_one.resource.blocker_count == seed_two.resource.blocker_count == 0
    shared = frozenset({voice_one.version_id, voice_two.version_id})
    assert _shared_voice_order(pg_engine, seed_one, shared_ids=shared) == (
        voice_one.version_id,
        voice_two.version_id,
    )
    assert _shared_voice_order(pg_engine, seed_two, shared_ids=shared) == (
        voice_two.version_id,
        voice_one.version_id,
    )

    rendezvous = threading.Barrier(2)
    local = threading.local()
    original = edition_service_module._voice_resolution

    def synchronized_first_shared_voice(*args: object, **kwargs: object):
        result = original(*args, **kwargs)
        if result.voice_version_id in shared and not getattr(local, "waited", False):
            local.waited = True
            _soft_barrier_wait(rendezvous)
        return result

    monkeypatch.setattr(
        edition_service_module,
        "_voice_resolution",
        synchronized_first_shared_voice,
    )
    outcomes = _run_pair(
        pg_engine,
        (
            _approve_command(
                seed_one, key=f"t4-rc-approve-lock-a-{uuid4().hex}"
            ),
            _approve_command(
                seed_two, key=f"t4-rc-approve-lock-b-{uuid4().hex}"
            ),
        ),
    )
    _assert_pair_succeeded(outcomes)
    for seed in (seed_one, seed_two):
        counts = _request_counts(pg_engine, seed.request_id)
        assert counts["actions"] == counts["editions"] == 1
        assert counts["jobs"] == counts["edition_segments"] > 0


def test_voice_lock_route_and_review_share_version_then_profile_order(
    pg_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    voice, _unused = _shared_voice_pair(pg_engine, marker="cross-route")
    seed = _seed_review(
        pg_engine,
        marker="cross-route",
        source="“交错锁验证。”甲锁说道。",
        character_voices=(("甲锁", voice),),
    )
    assert seed.resource.blocker_count == 0
    assert _shared_voice_order(
        pg_engine,
        seed,
        shared_ids=frozenset({voice.version_id}),
    ) == (voice.version_id,)

    before = _voice_graph_state(
        pg_engine,
        profile_id=voice.profile_id,
        version_id=voice.version_id,
    )
    expected_profile_version = before[1]
    assert type(expected_profile_version) is int
    review_command = _approve_command(
        seed,
        key=f"t4-rc-cross-route-review-{uuid4().hex}",
    )
    voice_command = NarrationSettingsApiCommand(
        operation=NarrationSettingsOperation.LOCK_VOICE_PROFILE,
        profile_id=voice.profile_id,
        payload=wire.LockVoiceProfileRequest(
            expected_profile_version=expected_profile_version,
            version_id=voice.version_id,
            quality_confirmed=True,
        ),
    )

    review_version_locked = threading.Event()
    release_review = threading.Event()
    voice_profile_locked = threading.Event()
    original_get = SqlAlchemyNarrationStore.get
    review_thread_name = f"t4-cross-review-{uuid4().hex}"[:63]
    voice_thread_name = f"t4-cross-voice-{uuid4().hex}"[:63]

    def probed_get(
        store: SqlAlchemyNarrationStore,
        model: type[object],
        row_id: object,
        *,
        for_update: bool = False,
    ) -> object | None:
        row = original_get(store, model, row_id, for_update=for_update)
        current_name = threading.current_thread().name
        if (
            for_update
            and model is VoiceProfileVersion
            and row_id == voice.version_id
            and current_name == review_thread_name
        ):
            review_version_locked.set()
            if not release_review.wait(timeout=10):
                raise AssertionError("review version-lock probe timed out")
        if (
            for_update
            and model is VoiceProfile
            and row_id == voice.profile_id
            and current_name == voice_thread_name
        ):
            voice_profile_locked.set()
        return row

    monkeypatch.setattr(SqlAlchemyNarrationStore, "get", probed_get)
    common_options = "-c statement_timeout=20000 -c lock_timeout=10000"
    review_engine = create_engine(
        _live_url(),
        pool_pre_ping=True,
        connect_args={
            "application_name": review_thread_name,
            "options": common_options,
        },
    )
    voice_engine = create_engine(
        _live_url(),
        pool_pre_ping=True,
        connect_args={
            "application_name": voice_thread_name,
            "options": common_options,
        },
    )
    outcomes: dict[str, _Outcome] = {}

    def run_review() -> None:
        try:
            with Session(review_engine, expire_on_commit=False) as session:
                backend = build_script_api_backend(
                    session,
                    production_policy_provider=lambda: POLICY,
                )
                outcomes["review"] = _Outcome(
                    value=backend.dispatch(review_command)
                )
        except Exception as error:
            outcomes["review"] = _Outcome(error=error)

    def run_voice_lock() -> None:
        try:
            with Session(voice_engine, expire_on_commit=False) as session:
                backend = build_narration_settings_backend(
                    session,
                    authorization=FIXED_LOCAL_OWNER_NARRATION_AUTHORIZATION,
                    capabilities=_enabled_voice_lock_capabilities(),
                )
                outcomes["voice"] = _Outcome(
                    value=backend.dispatch(voice_command)
                )
        except Exception as error:
            outcomes["voice"] = _Outcome(error=error)

    review_worker = threading.Thread(
        target=run_review,
        name=review_thread_name,
        daemon=True,
    )
    voice_worker = threading.Thread(
        target=run_voice_lock,
        name=voice_thread_name,
        daemon=True,
    )
    voice_started = False
    wait_evidence: tuple[str | None, tuple[int, ...]] | None = None
    voice_had_profile_before_release = False
    try:
        review_worker.start()
        assert review_version_locked.wait(timeout=8), outcomes.get("review")
        voice_worker.start()
        voice_started = True
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            with pg_engine.connect() as observer:
                waiting = observer.execute(
                    text(
                        """SELECT wait_event_type, pg_blocking_pids(pid)
                           FROM pg_stat_activity
                           WHERE application_name = :application_name
                             AND state = 'active'"""
                    ),
                    {"application_name": voice_thread_name},
                ).one_or_none()
            if waiting is not None and waiting[1]:
                wait_evidence = (waiting[0], tuple(waiting[1]))
                break
            time.sleep(0.05)
        voice_had_profile_before_release = voice_profile_locked.is_set()
    finally:
        release_review.set()
        review_worker.join(timeout=30)
        if voice_started:
            voice_worker.join(timeout=30)
        review_engine.dispose()
        voice_engine.dispose()

    assert wait_evidence is not None
    assert wait_evidence[0] == "Lock"
    assert not voice_had_profile_before_release
    assert not review_worker.is_alive()
    assert not voice_worker.is_alive()
    review_outcome = outcomes.get("review")
    voice_outcome = outcomes.get("voice")
    assert review_outcome is not None and review_outcome.error is None, review_outcome
    assert isinstance(review_outcome.value, ScriptReviewResource)
    assert review_outcome.value.state is ScriptState.APPROVED
    assert voice_outcome is not None and voice_outcome.value is None
    assert isinstance(voice_outcome.error, NarrationApiFault)
    assert voice_outcome.error.code is wire.NarrationErrorCode.VOICE_SOURCE_UNAVAILABLE
    assert voice_outcome.error.capability is wire.CapabilityKey.PRESET_VOICE_SOURCE
    assert voice_outcome.error.retryable is False
    assert _sqlstate(voice_outcome.error) is None
    assert voice_profile_locked.is_set()

    counts = _request_counts(pg_engine, seed.request_id)
    assert counts["versions"] == 1
    assert counts["actions"] == counts["editions"] == 1
    assert counts["jobs"] == counts["edition_segments"] > 0
    assert counts["renders"] == counts["edition_segments"]
    assert _voice_graph_state(
        pg_engine,
        profile_id=voice.profile_id,
        version_id=voice.version_id,
    ) == before


def test_reverse_patch_authority_lock_plan_has_no_postgresql_deadlock(
    pg_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    voice_one, voice_two = _shared_voice_pair(pg_engine, marker="patch-lock")
    seed_one = _seed_review(
        pg_engine,
        marker="patch-lock-a",
        source="“已有归属。”乙湖说道。\n\n---\n\n“陌生结尾。”",
        character_voices=(("甲林", voice_one), ("乙湖", voice_two)),
    )
    seed_two = _seed_review(
        pg_engine,
        marker="patch-lock-b",
        source="“已有归属。”丙海说道。\n\n---\n\n“陌生结尾。”",
        character_voices=(("丙海", voice_one), ("丁峰", voice_two)),
    )
    assert seed_one.resource.blocker_count > 0
    assert seed_two.resource.blocker_count > 0
    assert any(
        segment.speaker_kind is ScriptSpeakerKind.UNKNOWN
        for segment in seed_one.resource.segments
    )
    assert any(
        segment.speaker_kind is ScriptSpeakerKind.UNKNOWN
        for segment in seed_two.resource.segments
    )

    rendezvous = threading.Barrier(2)
    original = script_backend_module.correct_review_segment

    def synchronized_after_selected_voice(*args: object, **kwargs: object):
        _soft_barrier_wait(rendezvous)
        return original(*args, **kwargs)

    monkeypatch.setattr(
        script_backend_module,
        "correct_review_segment",
        synchronized_after_selected_voice,
    )
    outcomes = _run_pair(
        pg_engine,
        (
            _patch_command(
                seed_one,
                key=f"t4-rc-patch-lock-a-{uuid4().hex}",
                character_name="甲林",
            ),
            _patch_command(
                seed_two,
                key=f"t4-rc-patch-lock-b-{uuid4().hex}",
                character_name="丁峰",
            ),
        ),
    )
    _assert_pair_succeeded(outcomes)
    for seed in (seed_one, seed_two):
        counts = _request_counts(pg_engine, seed.request_id)
        assert counts == {
            "versions": 2,
            "actions": 1,
            "editions": 0,
            "edition_segments": 0,
            "jobs": 0,
            "renders": 0,
        }


def test_patch_same_key_replays_and_different_key_loses_request_cas(
    pg_engine: Engine,
) -> None:
    voice_one, _voice_two = _shared_voice_pair(pg_engine, marker="patch-keys")
    same_seed = _seed_review(
        pg_engine,
        marker="patch-same-key",
        source="“没有说话提示。”",
        character_voices=(("甲子", voice_one),),
    )
    same_command = _patch_command(
        same_seed,
        key=f"t4-rc-patch-same-{uuid4().hex}",
    )
    same_outcomes = _run_pair(pg_engine, (same_command, same_command))
    _assert_pair_succeeded(same_outcomes)
    assert same_outcomes[0].value == same_outcomes[1].value
    assert _request_counts(pg_engine, same_seed.request_id) == {
        "versions": 2,
        "actions": 1,
        "editions": 0,
        "edition_segments": 0,
        "jobs": 0,
        "renders": 0,
    }

    different_seed = _seed_review(
        pg_engine,
        marker="patch-different-key",
        source="“仍然没有说话提示。”",
        character_voices=(("乙子", voice_one),),
    )
    different_outcomes = _run_pair(
        pg_engine,
        (
            _patch_command(
                different_seed,
                key=f"t4-rc-patch-different-a-{uuid4().hex}",
            ),
            _patch_command(
                different_seed,
                key=f"t4-rc-patch-different-b-{uuid4().hex}",
            ),
        ),
    )
    assert sum(item.error is None for item in different_outcomes) == 1
    loser = next(item.error for item in different_outcomes if item.error is not None)
    assert isinstance(loser, NarrationCasConflict)
    assert _sqlstate(loser) is None
    assert _request_counts(pg_engine, different_seed.request_id) == {
        "versions": 2,
        "actions": 1,
        "editions": 0,
        "edition_segments": 0,
        "jobs": 0,
        "renders": 0,
    }


def test_approve_same_key_replays_and_different_key_has_one_production_graph(
    pg_engine: Engine,
) -> None:
    voice_one, _voice_two = _shared_voice_pair(pg_engine, marker="approve-keys")
    same_seed = _seed_review(
        pg_engine,
        marker="approve-same-key",
        source="“我来了。”甲辰说道。",
        character_voices=(("甲辰", voice_one),),
    )
    assert same_seed.resource.blocker_count == 0
    same_command = _approve_command(
        same_seed,
        key=f"t4-rc-approve-same-{uuid4().hex}",
    )
    same_outcomes = _run_pair(pg_engine, (same_command, same_command))
    _assert_pair_succeeded(same_outcomes)
    assert same_outcomes[0].value == same_outcomes[1].value
    same_counts = _request_counts(pg_engine, same_seed.request_id)
    assert same_counts["versions"] == 1
    assert same_counts["actions"] == same_counts["editions"] == 1
    assert same_counts["jobs"] == same_counts["edition_segments"] > 0
    assert same_counts["renders"] == same_counts["edition_segments"]

    different_seed = _seed_review(
        pg_engine,
        marker="approve-different-key",
        source="“出发。”乙辰说道。",
        character_voices=(("乙辰", voice_one),),
    )
    assert different_seed.resource.blocker_count == 0
    different_outcomes = _run_pair(
        pg_engine,
        (
            _approve_command(
                different_seed,
                key=f"t4-rc-approve-different-a-{uuid4().hex}",
            ),
            _approve_command(
                different_seed,
                key=f"t4-rc-approve-different-b-{uuid4().hex}",
            ),
        ),
    )
    assert sum(item.error is None for item in different_outcomes) == 1
    loser = next(item.error for item in different_outcomes if item.error is not None)
    assert isinstance(loser, IdempotencyConflict)
    assert _sqlstate(loser) is None
    different_counts = _request_counts(pg_engine, different_seed.request_id)
    assert different_counts["versions"] == 1
    assert different_counts["actions"] == different_counts["editions"] == 1
    assert different_counts["jobs"] == different_counts["edition_segments"] > 0
    assert different_counts["renders"] == different_counts["edition_segments"]


def test_policy_and_queue_failures_roll_back_real_backend_transaction(
    pg_engine: Engine,
) -> None:
    voice_one, _voice_two = _shared_voice_pair(pg_engine, marker="rollback")
    seed = _seed_review(
        pg_engine,
        marker="rollback",
        source="“回滚验证。”甲戌说道。",
        character_voices=(("甲戌", voice_one),),
    )
    assert seed.resource.blocker_count == 0
    initial = _request_counts(pg_engine, seed.request_id)
    assert initial == {
        "versions": 1,
        "actions": 0,
        "editions": 0,
        "edition_segments": 0,
        "jobs": 0,
        "renders": 0,
    }

    def unavailable_policy() -> NarrationProductionPolicy:
        raise RuntimeError("private policy provider detail")

    with Session(pg_engine) as session:
        backend = build_script_api_backend(
            session,
            production_policy_provider=unavailable_policy,
        )
        with pytest.raises(Exception) as policy_failure:
            backend.dispatch(
                _approve_command(
                    seed,
                    key=f"t4-rc-policy-rollback-{uuid4().hex}",
                )
            )
    assert isinstance(policy_failure.value, InvalidNarrationState) or getattr(
        policy_failure.value, "retryable", False
    )
    assert _request_counts(pg_engine, seed.request_id) == initial

    class _FailingQueue:
        def enqueue_segment_render(self, **values: object):
            del values
            raise RuntimeError("private queue failure detail")

    with Session(pg_engine) as session:
        backend = build_script_api_backend(
            session,
            production_policy_provider=lambda: POLICY,
            queue_factory=lambda _session: _FailingQueue(),
        )
        with pytest.raises(Exception):
            backend.dispatch(
                _approve_command(
                    seed,
                    key=f"t4-rc-queue-rollback-{uuid4().hex}",
                )
            )
    assert _request_counts(pg_engine, seed.request_id) == initial

    with Session(pg_engine) as session:
        request = session.get(NarrationRequest, seed.request_id)
        version = session.get(
            NarrationScriptVersion,
            seed.resource.script_version_id,
        )
        assert request is not None and request.state == "review_required"
        assert request.version == seed.request_version
        assert version is not None and version.state == "review_required"
