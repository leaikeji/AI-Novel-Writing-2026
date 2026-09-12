from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from backend.models import (
    Base,
    Novel,
    NovelNarrationSettings,
    VoiceActionCommand,
    VoiceActionReceipt,
    VoiceProfile,
    VoiceProfileVersion,
)
from backend.narration import schemas as wire
from backend.narration.contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID
from backend.narration.official_presets import (
    OFFICIAL_PRESET_IDENTITY_CONTRACT_VERSION,
    OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256,
    OFFICIAL_PRESETS,
    official_preset_canonical_profile_id,
    official_preset_canonical_version_id,
    validate_official_version_evidence,
)
from backend.narration.official_voice_records import build_official_preset_version_rows
from backend.narration.official_voice_selection import _require_current_provider_mapping
from backend.narration.services import VoiceSourceUnavailable
from tests.narration.current_schema_gate import assert_database_at_repository_head


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (
    ROOT
    / "backend/migrations/versions/20260829_0031_official_voice_selection.py"
)
EXPECTED_DATABASE = "ai_novel_world_2026_tts_test"
EXPECTED_USER = "tts_test"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _constraint_names(table_name: str) -> set[str]:
    return {
        str(item.name)
        for item in Base.metadata.tables[table_name].constraints
        if item.name is not None
    }


def test_canonical_identity_is_stable_per_novel_and_separates_inputs() -> None:
    novel_id = UUID("11111111-2222-4333-8444-555555555555")
    profile_id = official_preset_canonical_profile_id(
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        novel_id=novel_id,
        preset_id="qwen.WarmFemale",
    )
    assert OFFICIAL_PRESET_IDENTITY_CONTRACT_VERSION == (
        "qwen-tts-preset-identity/1"
    )
    version_id = official_preset_canonical_version_id(
        profile_id=profile_id,
        preset_id="qwen.WarmFemale",
    )
    assert version_id == official_preset_canonical_version_id(
        profile_id=profile_id,
        preset_id="qwen.WarmFemale",
    )
    assert official_preset_canonical_profile_id(
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        novel_id=UUID("21111111-2222-4333-8444-555555555555"),
        preset_id="qwen.WarmFemale",
    ) != profile_id
    assert official_preset_canonical_profile_id(
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        novel_id=novel_id,
        preset_id="qwen.ClearMale",
    ) != profile_id


def test_identity_functions_cover_all_pinned_qwen_presets() -> None:
    novel_id = UUID("11111111-2222-4333-8444-555555555555")
    pairs = []
    for preset in OFFICIAL_PRESETS:
        profile_id = official_preset_canonical_profile_id(
            owner_id=LOCAL_OWNER_ID,
            workspace_id=LOCAL_WORKSPACE_ID,
            novel_id=novel_id,
            preset_id=preset.preset_id,
        )
        pairs.append(
            (
                profile_id,
                official_preset_canonical_version_id(
                    profile_id=profile_id,
                    preset_id=preset.preset_id,
                ),
            )
        )
    assert len(pairs) == len(OFFICIAL_PRESETS)
    assert len({profile for profile, _version in pairs}) == len(OFFICIAL_PRESETS)
    assert len({version for _profile, version in pairs}) == len(OFFICIAL_PRESETS)


def test_orm_freezes_truthful_activation_and_immutable_command_shape() -> None:
    assert {"activation_basis", "validation_basis"} <= {
        column.name for column in VoiceProfileVersion.__table__.columns
    }
    assert {
        "ck_voice_profile_version_activation_basis",
        "ck_voice_profile_version_validation_basis",
        "ck_voice_profile_version_locked_shape",
        "ck_voice_profile_version_unlocked_activation",
    } <= _constraint_names("voice_profile_versions")
    assert VoiceActionCommand.__tablename__ == "voice_action_commands"
    assert {
        "ck_voice_action_command_lifecycle",
        "ck_voice_action_command_target_shape",
        "fk_voice_action_command_version",
        "fk_voice_action_command_receipt",
    } <= _constraint_names("voice_action_commands")
    ddl = str(
        CreateTable(VoiceActionCommand.__table__).compile(
            dialect=postgresql.dialect()
        )
    )
    assert "CREATE TABLE voice_action_commands" in ddl
    assert "target_language" in ddl
    assert "language_mismatch" in ddl
    assert "result_json" not in ddl
    assert "target_kind IN ('narrator','character')" in ddl
    for preset in OFFICIAL_PRESETS:
        assert preset.preset_id in ddl


def test_official_selection_rejects_local_only_voice_for_cloud_before_writes() -> None:
    cloud_settings = SimpleNamespace(
        values=SimpleNamespace(
            tts_provider=wire.TTSProviderSelection(
                provider_id="aliyun_qwen_audio_tts",
                aliyun_model_id="qwen-audio-3.0-tts-plus",
            )
        )
    )
    with pytest.raises(VoiceSourceUnavailable, match="no verified mapping"):
        _require_current_provider_mapping(
            settings=cloud_settings,
            preset_ids={"qwen.Vivian"},
        )

    _require_current_provider_mapping(
        settings=cloud_settings,
        preset_ids={"qwen.WarmFemale", "qwen.ClearMale"},
    )


def test_migration_is_linear_io_free_and_keeps_source_specific_guards() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    for forbidden in (
        "from backend.models",
        "create_engine",
        "requests.",
        "subprocess",
    ):
        assert forbidden not in source
    for marker in (
        'revision = "20260829_0031"',
        'down_revision = "20260829_0030"',
        "voice_action_commands",
        "explicit_official_preset_selection",
        "character_one_click_generation",
        "experimental_machine_validated",
        "human_accepted",
        "machine_validated",
        "voice action command receipt closure failed",
        "official voice version evidence closure failed",
        "completed voice action command is immutable",
        "direct-use activation evidence exists",
    ):
        assert marker in source


def test_contract_does_not_rewrite_historical_voice_evidence() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert "UPDATE voice_profile_versions" in source
    assert "SET validation_basis='human_accepted'" in source
    for forbidden in (
        "UPDATE voice_profiles",
        "UPDATE character_voice_bindings",
        "UPDATE novel_narration_settings",
        "UPDATE narration_editions",
        "DELETE FROM",
    ):
        assert forbidden not in source


def test_shared_official_validator_rejects_model_parameters_and_rights_drift() -> None:
    now = datetime.now(timezone.utc)
    profile = VoiceProfile(
        id=uuid4(),
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        novel_id=uuid4(),
        name="Warm Female",
        status="active",
    )
    version_id = official_preset_canonical_version_id(
        profile_id=profile.id,
        preset_id="qwen.WarmFemale",
    )
    rows = build_official_preset_version_rows(
        profile=profile,
        preset=OFFICIAL_PRESETS[0],
        version_id=version_id,
        version_number=1,
        actor="local-owner",
        at=now,
        direct_selection=True,
    )
    validate_official_version_evidence(
        rows.version,
        rows.rights,
        expected_model_fingerprint=OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256,
    )
    for field, bad_value in (
        ("model_id", "fixture"),
        ("model_revision", "0" * 40),
        ("parameters_json", {}),
    ):
        original = getattr(rows.version, field)
        setattr(rows.version, field, bad_value)
        with pytest.raises(ValueError):
            validate_official_version_evidence(
                rows.version,
                rows.rights,
                expected_model_fingerprint=OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256,
            )
        setattr(rows.version, field, original)
    original_source = rows.rights.source_identifier
    rows.rights.source_identifier = "fixture:qwen.WarmFemale"
    with pytest.raises(ValueError):
        validate_official_version_evidence(
            rows.version,
            rows.rights,
            expected_model_fingerprint=OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256,
        )
    rows.rights.source_identifier = original_source


def test_official_row_builder_persists_sparse_maps_for_all_nine_presets() -> None:
    now = datetime.now(timezone.utc)
    for preset in OFFICIAL_PRESETS:
        profile = VoiceProfile(
            id=uuid4(),
            owner_id=LOCAL_OWNER_ID,
            workspace_id=LOCAL_WORKSPACE_ID,
            novel_id=uuid4(),
            name=preset.display_name,
            status="active",
        )
        version_id = official_preset_canonical_version_id(
            profile_id=profile.id,
            preset_id=preset.preset_id,
        )
        rows = build_official_preset_version_rows(
            profile=profile,
            preset=preset,
            version_id=version_id,
            version_number=1,
            actor="local-owner",
            at=now,
            direct_selection=True,
        )
        assert rows.version.parameters_json["provider_voice_ids"] == (
            preset.provider_voice_ids
        )
        assert rows.version.language == preset.language
        validate_official_version_evidence(
            rows.version,
            rows.rights,
            expected_model_fingerprint=OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256,
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
        raise RuntimeError("official voice contract requires the exact disposable DB")
    production = os.environ.get("AI_NOVEL_DATABASE_URL", "").strip()
    if production:
        live = make_url(production)
        if (parsed.host, parsed.port, parsed.database) == (
            live.host,
            live.port,
            live.database,
        ):
            raise RuntimeError("official voice tests refuse the production database")
    return raw


@pytest.mark.parametrize(
    "preset",
    OFFICIAL_PRESETS,
    ids=[item.preset_id for item in OFFICIAL_PRESETS],
)
def test_live_postgres_accepts_truthful_direct_use_and_rejects_false_evidence(
    preset,
) -> None:
    engine = create_engine(_live_url(), pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            session: Session | None = None
            try:
                assert_database_at_repository_head(connection)
                session = Session(bind=connection, join_transaction_mode="create_savepoint")
                novel_id = uuid4()
                profile_id = official_preset_canonical_profile_id(
                    owner_id=LOCAL_OWNER_ID,
                    workspace_id=LOCAL_WORKSPACE_ID,
                    novel_id=novel_id,
                    preset_id=preset.preset_id,
                )
                version_id = official_preset_canonical_version_id(
                    profile_id=profile_id,
                    preset_id=preset.preset_id,
                )
                now = datetime.now(timezone.utc)
                session.add(
                    Novel(
                        id=novel_id,
                        owner_id=LOCAL_OWNER_ID,
                        workspace_id=LOCAL_WORKSPACE_ID,
                        title="P0 contract fixture",
                    )
                )
                profile = VoiceProfile(
                    id=profile_id,
                    owner_id=LOCAL_OWNER_ID,
                    workspace_id=LOCAL_WORKSPACE_ID,
                    novel_id=novel_id,
                    name=preset.display_name,
                    status="active",
                )
                session.add(profile)
                session.flush()
                rows = build_official_preset_version_rows(
                    profile=profile,
                    preset=preset,
                    version_id=version_id,
                    version_number=1,
                    actor="local-owner",
                    at=now,
                    direct_selection=True,
                )
                session.add(rows.rights)
                session.flush()
                session.add_all([rows.event, rows.version])
                session.flush()
                legacy_version_id = uuid4()
                legacy_rows = build_official_preset_version_rows(
                    profile=profile,
                    preset=preset,
                    version_id=legacy_version_id,
                    version_number=2,
                    actor="local-owner",
                    at=now,
                    direct_selection=False,
                )
                session.add(legacy_rows.rights)
                session.flush()
                session.add_all([legacy_rows.event, legacy_rows.version])
                session.flush()
                legacy_rows.version.state = "preview_ready"
                session.flush()
                session.execute(
                    text(
                        "UPDATE voice_profile_versions SET state='locked', "
                        "quality_state='accepted', locked_actor='local-owner', "
                        "locked_at=:at WHERE id=:id"
                    ),
                    {"at": datetime.now(timezone.utc), "id": legacy_version_id},
                )
                assert session.scalar(
                    text(
                        "SELECT validation_basis FROM voice_profile_versions "
                        "WHERE id=:id"
                    ),
                    {"id": legacy_version_id},
                ) == "human_accepted"
                profile.current_version_id = version_id
                profile.version = 2
                session.add(
                    NovelNarrationSettings(
                        id=uuid4(),
                        novel_id=novel_id,
                        narrator_profile_id=profile_id,
                        narrator_version_id=version_id,
                        settings_json={},
                        version=1,
                    )
                )
                session.flush()

                command_id = uuid4()
                request_hash = "c" * 64
                receipt = VoiceActionReceipt(
                    id=uuid4(),
                    owner_id=LOCAL_OWNER_ID,
                    workspace_id=LOCAL_WORKSPACE_ID,
                    operation="official_preset_selection",
                    idempotency_key="contract-test-0001",
                    request_hash=request_hash,
                    resource_id=command_id,
                    state="reserved",
                    reserved_at=now,
                )
                session.add(receipt)
                session.flush()
                command = VoiceActionCommand(
                    id=command_id,
                    owner_id=LOCAL_OWNER_ID,
                    workspace_id=LOCAL_WORKSPACE_ID,
                    novel_id=novel_id,
                    operation="official_preset_selection",
                    target_kind="narrator",
                    target_character_id=None,
                    preset_key=preset.preset_id,
                    request_hash=request_hash,
                    state="reserved",
                )
                session.add(command)
                session.flush()
                command.state = "completed"
                command.profile_id = profile_id
                command.voice_version_id = version_id
                command.settings_version = 1
                command.target_language = preset.language
                command.language_mismatch = False
                completed_at = datetime.now(timezone.utc)
                command.completed_at = completed_at
                receipt.state = "completed"
                receipt.completed_at = completed_at
                session.flush()
                session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

                with pytest.raises(DBAPIError):
                    with session.begin_nested():
                        session.execute(
                            text(
                                "UPDATE voice_action_commands "
                                "SET request_hash=:value WHERE id=:id"
                            ),
                            {"value": "d" * 64, "id": command_id},
                        )
                        session.flush()

                session.execute(text("SET CONSTRAINTS ALL DEFERRED"))
                with pytest.raises(DBAPIError):
                    with session.begin_nested():
                        session.add(
                            VoiceActionCommand(
                                id=uuid4(),
                                owner_id=LOCAL_OWNER_ID,
                                workspace_id=LOCAL_WORKSPACE_ID,
                                novel_id=novel_id,
                                operation="official_preset_selection",
                                target_kind="narrator",
                                preset_key=preset.preset_id,
                                request_hash="e" * 64,
                                state="completed",
                                profile_id=profile_id,
                                voice_version_id=version_id,
                                settings_version=1,
                                target_language=preset.language,
                                language_mismatch=False,
                                completed_at=now,
                            )
                        )
                        session.flush()
            finally:
                if session is not None:
                    session.close()
                transaction.rollback()
    finally:
        engine.dispose()
