from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
import re
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from backend.models import (
    CharacterVoiceBinding,
    Novel,
    NovelCharacter,
    NovelNarrationSettings,
    VoiceActionCommand,
    VoiceActionReceipt,
    VoiceProfile,
    VoiceProfileVersion,
)
from backend.narration import schemas as wire
from backend.narration.contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID
from backend.narration.official_presets import OFFICIAL_PRESETS
from backend.narration.official_voice_selection import OfficialVoiceSelectionService
from backend.narration.services import IdempotencyConflict, NarrationCasConflict


EXPECTED_DATABASE = "ai_novel_world_2026_tts_test"
EXPECTED_USER = "tts_test"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_SCHEMA = re.compile(r"^official_selection_[0-9a-f]{12}$")
_CLONED_TABLES = (
    "novels",
    "novel_characters",
    "media_assets",
    "voice_rights_records",
    "voice_rights_events",
    "voice_profiles",
    "voice_profile_versions",
    "voice_action_receipts",
    "voice_action_commands",
    "voice_previews",
    "novel_narration_settings",
    "character_voice_bindings",
    "narration_segments",
    "narration_script_versions",
    "narration_scripts",
    "narration_editions",
)


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
            "official selection tests require the exact disposable loopback TTS DB"
        )
    return raw


@pytest.fixture(scope="module")
def selection_engine() -> Engine:
    base = create_engine(_live_url(), pool_pre_ping=True, pool_size=8)
    schema = f"official_selection_{uuid4().hex[:12]}"
    assert _SCHEMA.fullmatch(schema)
    with base.begin() as connection:
        identity = connection.execute(
            text("SELECT current_database(), current_user")
        ).one()
        if identity != (EXPECTED_DATABASE, EXPECTED_USER):
            raise RuntimeError("official selection test database identity changed")
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        for table_name in _CLONED_TABLES:
            connection.execute(
                text(
                    f'CREATE TABLE "{schema}"."{table_name}" '
                    f'(LIKE public."{table_name}" INCLUDING ALL)'
                )
            )
    translated = base.execution_options(schema_translate_map={None: schema})
    try:
        yield translated
    finally:
        translated.dispose()
        with base.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        base.dispose()


@pytest.fixture(scope="module")
def public_selection_engine() -> Engine:
    engine = create_engine(_live_url(), pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()


def _factory(engine: Engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


def _seed_novel(factory, *, with_character: bool) -> tuple[UUID, UUID | None]:
    novel_id = uuid4()
    character_id = uuid4() if with_character else None
    with factory() as session, session.begin():
        session.add(
            Novel(
                id=novel_id,
                owner_id=LOCAL_OWNER_ID,
                workspace_id=LOCAL_WORKSPACE_ID,
                title="官方音色原子选择测试",
                author_name="作者",
                description="",
                writing_type="novel",
                audience="general",
                genre="fiction",
                subgenre="",
                idea="",
                template_name="",
                template_data={},
                cover_mode="none",
                cover_image_data="",
                outline_target_chapters=0,
                highlight="",
                background="",
                main_plot="",
                story_ledger_version=1,
                character_catalog_version=0,
                version=1,
            )
        )
        if character_id is not None:
            session.add(
                NovelCharacter(
                    id=character_id,
                    novel_id=novel_id,
                    role_type="protagonist",
                    name="林岚",
                    description="",
                    details={},
                    lifecycle_state="active",
                    archived_at=None,
                    position=1,
                    version=1,
                )
            )
    return novel_id, character_id


def test_all_eighteen_narrator_and_character_actions_are_atomic_and_replayable(
    selection_engine: Engine,
) -> None:
    factory = _factory(selection_engine)
    novel_id, character_id = _seed_novel(factory, with_character=True)
    assert character_id is not None
    service = OfficialVoiceSelectionService(factory)

    settings_version = 0
    first_request: wire.OfficialVoiceSelectionRequest | None = None
    first_key = "official-matrix-narrator-00"
    for index, preset in enumerate(OFFICIAL_PRESETS):
        request = wire.OfficialVoiceSelectionRequest(
            preset_id=preset.preset_id,
            target_kind="narrator",
            expected_settings_version=settings_version,
        )
        if first_request is None:
            first_request = request
        response = service.select_official_voice(
            novel_id=novel_id,
            request=request,
            idempotency_key=f"official-matrix-narrator-{index:02d}",
        )
        settings_version = response.frozen_result.settings_version
        assert not response.replayed
        assert response.selection_still_current
        assert response.current_settings is not None
        assert response.current_character_binding is None
        assert response.frozen_result.preset_id == preset.preset_id
        assert response.frozen_result.language_mismatch is (
            preset.language.split("-", 1)[0].casefold() != "zh"
        )
        selected = next(
            item
            for item in response.profile.versions
            if item.version_id == response.frozen_result.version_id
        )
        assert selected.state is wire.VoiceVersionState.LOCKED
        assert selected.activation_basis is (
            wire.VoiceActivationBasis.EXPLICIT_OFFICIAL_PRESET_SELECTION
        )
        assert selected.validation_basis is wire.VoiceValidationBasis.NOT_REQUIRED
        assert selected.quality_state is wire.VoiceQualityState.PENDING

    binding_version = 0
    for index, preset in enumerate(OFFICIAL_PRESETS):
        response = service.select_official_voice(
            novel_id=novel_id,
            request=wire.OfficialVoiceSelectionRequest(
                preset_id=preset.preset_id,
                target_kind="character",
                character_id=character_id,
                expected_settings_version=settings_version,
                expected_binding_version=binding_version,
            ),
            idempotency_key=f"official-matrix-character-{index:02d}",
        )
        binding_version = response.frozen_result.binding_version or 0
        assert response.selection_still_current
        assert response.current_settings is None
        assert response.current_character_binding is not None
        assert response.current_character_binding.character_id == character_id

    assert first_request is not None
    replay = service.select_official_voice(
        novel_id=novel_id,
        request=first_request,
        idempotency_key=first_key,
    )
    assert replay.replayed
    assert not replay.selection_still_current
    assert replay.frozen_result.settings_version == 1
    assert replay.current_settings is not None
    assert replay.current_settings.version == settings_version

    with pytest.raises(IdempotencyConflict):
        service.select_official_voice(
            novel_id=novel_id,
            request=first_request.model_copy(update={"preset_id": "onnx.Zhiming"}),
            idempotency_key=first_key,
        )

    with factory() as session:
        assert session.scalar(
            select(func.count()).select_from(VoiceActionCommand).where(
                VoiceActionCommand.novel_id == novel_id
            )
        ) == 36
        assert session.scalar(
            select(func.count()).select_from(VoiceActionReceipt).join(
                VoiceActionCommand,
                VoiceActionReceipt.resource_id == VoiceActionCommand.id,
            ).where(VoiceActionCommand.novel_id == novel_id)
        ) == 36
        assert session.scalar(
            select(func.count()).select_from(VoiceProfile).where(
                VoiceProfile.novel_id == novel_id
            )
        ) == 18
        assert session.scalar(
            select(func.count()).select_from(VoiceProfileVersion).join(
                VoiceProfile,
                VoiceProfileVersion.profile_id == VoiceProfile.id,
            ).where(VoiceProfile.novel_id == novel_id)
        ) == 18
        settings = session.scalar(
            select(NovelNarrationSettings).where(
                NovelNarrationSettings.novel_id == novel_id
            )
        )
        binding = session.scalar(
            select(CharacterVoiceBinding).where(
                CharacterVoiceBinding.character_id == character_id
            )
        )
        assert settings is not None and settings.version == 18
        assert binding is not None and binding.version == 18


def test_service_satisfies_real_0031_deferred_closure_then_outer_rolls_back(
    public_selection_engine: Engine,
) -> None:
    connection = public_selection_engine.connect()
    outer = connection.begin()
    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        novel_id, character_id = _seed_novel(factory, with_character=True)
        assert character_id is not None
        service = OfficialVoiceSelectionService(factory)
        narrator = service.select_official_voice(
            novel_id=novel_id,
            request=wire.OfficialVoiceSelectionRequest(
                preset_id="onnx.Junhao",
                target_kind="narrator",
                expected_settings_version=0,
            ),
            idempotency_key="official-real-closure-narrator-0001",
        )
        character = service.select_official_voice(
            novel_id=novel_id,
            request=wire.OfficialVoiceSelectionRequest(
                preset_id="onnx.Zhiming",
                target_kind="character",
                character_id=character_id,
                expected_settings_version=narrator.frozen_result.settings_version,
                expected_binding_version=0,
            ),
            idempotency_key="official-real-closure-character-0001",
        )
        assert narrator.selection_still_current
        assert character.selection_still_current
        # Force every initially-deferred 0031 closure while all rows are still
        # visible, then roll the outer transaction back for zero persistent data.
        connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        assert connection.execute(
            text(
                "SELECT count(*) FROM voice_action_commands "
                "WHERE novel_id=:novel_id AND state='completed'"
            ),
            {"novel_id": novel_id},
        ).scalar_one() == 2
    finally:
        outer.rollback()
        connection.close()


def test_new_cas_failure_rolls_back_receipt_command_and_canonical_rows(
    selection_engine: Engine,
) -> None:
    factory = _factory(selection_engine)
    novel_id, _ = _seed_novel(factory, with_character=False)
    service = OfficialVoiceSelectionService(factory)

    with pytest.raises(NarrationCasConflict):
        service.select_official_voice(
            novel_id=novel_id,
            request=wire.OfficialVoiceSelectionRequest(
                preset_id="onnx.Ava",
                target_kind="narrator",
                expected_settings_version=1,
            ),
            idempotency_key="official-cas-rollback-0001",
        )

    with factory() as session:
        assert session.scalar(
            select(func.count()).select_from(VoiceActionCommand).where(
                VoiceActionCommand.novel_id == novel_id
            )
        ) == 0
        assert session.scalar(
            select(func.count()).select_from(VoiceProfile).where(
                VoiceProfile.novel_id == novel_id
            )
        ) == 0
        assert session.scalar(
            select(func.count()).select_from(VoiceActionReceipt).where(
                VoiceActionReceipt.idempotency_key == "official-cas-rollback-0001"
            )
        ) == 0


def test_concurrent_first_use_converges_on_one_command_and_one_frozen_result(
    selection_engine: Engine,
) -> None:
    factory = _factory(selection_engine)
    novel_id, _ = _seed_novel(factory, with_character=False)
    request = wire.OfficialVoiceSelectionRequest(
        preset_id="onnx.Soyo",
        target_kind="narrator",
        expected_settings_version=0,
    )

    def invoke() -> wire.OfficialVoiceSelectionResponse:
        return OfficialVoiceSelectionService(factory).select_official_voice(
            novel_id=novel_id,
            request=request,
            idempotency_key="official-concurrent-first-0001",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _index: invoke(), range(2)))

    assert sorted(item.replayed for item in responses) == [False, True]
    assert responses[0].frozen_result == responses[1].frozen_result
    assert all(item.selection_still_current for item in responses)
    with factory() as session:
        assert session.scalar(
            select(func.count()).select_from(VoiceActionCommand).where(
                VoiceActionCommand.novel_id == novel_id
            )
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(VoiceProfile).where(
                VoiceProfile.novel_id == novel_id
            )
        ) == 1
