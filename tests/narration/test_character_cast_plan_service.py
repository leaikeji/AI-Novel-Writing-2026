from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
import re
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import sessionmaker

from backend.creative_data_models import StoryTimeline
from backend.models import (
    CharacterCastPlanCommand,
    CharacterCastPlanItem,
    Novel,
    NovelNarrationSettings,
    VoiceActionCommand,
)
from backend.narration.character_cast_plan_service import (
    CharacterCastTargetAnalysis,
    SqlAlchemyCharacterCastPlanService,
    _no_assignment_terminal_state,
    _settings_digest,
    character_cast_plan_request_hash,
)
from backend.narration.character_casting import (
    CastDecision,
    CastDecisionStatus,
    CharacterCastSolution,
)
from backend.narration.contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID
from backend.narration.narrator_voice_brief import parse_narrator_voice_brief
from backend.narration.privacy import default_narration_settings_values
from backend.narration.schemas import NarrationSettingsResource


EXPECTED_DATABASE = "ai_novel_world_2026_tts_test"
EXPECTED_USER = "tts_test"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_SCHEMA = re.compile(r"^character_cast_plan_[0-9a-f]{12}$")
_CLONED_TABLES = (
    "novels",
    "story_timelines",
    "novel_characters",
    "media_assets",
    "voice_rights_records",
    "voice_rights_events",
    "voice_profiles",
    "voice_profile_versions",
    "voice_previews",
    "voice_action_receipts",
    "voice_action_commands",
    "novel_narration_settings",
    "character_voice_bindings",
    "character_cast_plan_commands",
    "character_cast_plan_items",
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
            "character cast tests require the exact disposable loopback TTS DB"
        )
    return raw


@pytest.fixture(scope="module")
def cast_engine() -> Engine:
    base = create_engine(_live_url(), pool_pre_ping=True)
    schema = f"character_cast_plan_{uuid4().hex[:12]}"
    assert _SCHEMA.fullmatch(schema)
    with base.begin() as connection:
        identity = connection.execute(
            text("SELECT current_database(), current_user")
        ).one()
        if identity != (EXPECTED_DATABASE, EXPECTED_USER):
            raise RuntimeError("character cast test database identity changed")
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


def _factory(engine: Engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


def _seed_novel(factory) -> tuple[UUID, UUID]:
    novel_id = uuid4()
    timeline_id = uuid4()
    with factory() as session, session.begin():
        session.add(
            Novel(
                id=novel_id,
                owner_id=LOCAL_OWNER_ID,
                workspace_id=LOCAL_WORKSPACE_ID,
                title="雾港来信",
                author_name="作者",
                description="克制冷峻的悬疑调查故事",
                writing_type="novel",
                audience="general",
                genre="悬疑",
                subgenre="刑侦",
                idea="一封迟到十年的信",
                template_name="",
                template_data={},
                cover_mode="none",
                cover_image_data="",
                outline_target_chapters=4,
                highlight="多线索收束",
                background="沿海旧城",
                main_plot="刑警追查旧案",
                story_ledger_version=1,
                character_catalog_version=0,
                version=1,
            )
        )
        session.add(
            StoryTimeline(
                id=timeline_id,
                novel_id=novel_id,
                timeline_key="main",
                name="主时间线",
                normalized_name="主时间线",
                timeline_kind="main",
                is_primary=True,
                parent_timeline_id=None,
                fork_story_sequence=None,
                fork_anchor_json={},
                lifecycle_state="active",
                position=0,
                version=1,
            )
        )
    return novel_id, timeline_id


def _brief():
    return parse_narrator_voice_brief(
        {
            "schema_version": "narrator-voice-brief/1",
            "language": "zh-CN",
            "presentation": "androgynous",
            "pitch": -1,
            "pace": 0,
            "energy": 1,
            "texture": "dark",
            "evidence_fields": [
                "language:narration_settings.language",
                "presentation:novel.genre",
                "pitch:novel.description",
                "pace:novel.main_plot",
                "energy:novel.highlight",
                "texture:novel.background",
            ],
        }
    )


def _reserve(service, *, novel_id: UUID, timeline_id: UUID):
    return service.reserve(
        novel_id=novel_id,
        timeline_id=timeline_id,
        idempotency_key=f"character-cast-{uuid4()}",
        request_hash=character_cast_plan_request_hash(
            novel_id=novel_id,
            timeline_id=timeline_id,
        ),
    )


def test_default_settings_digest_is_float_free_stable_and_sensitive() -> None:
    novel_id = uuid4()
    baseline = NarrationSettingsResource(
        novel_id=novel_id,
        exists=False,
        version=0,
        values=default_narration_settings_values(),
    )
    changed = baseline.model_copy(deep=True)
    changed.values.playback.playback_rate = 1.25

    assert _settings_digest(baseline) == _settings_digest(
        baseline.model_copy(deep=True)
    )
    assert _settings_digest(changed) != _settings_digest(baseline)


def test_preserved_voice_does_not_mask_total_failure_of_targets_needing_analysis() -> None:
    solution = CharacterCastSolution(
        baseline_sha256="a" * 64,
        decisions=(
            CastDecision(
                target_key="character:preserved",
                status=CastDecisionStatus.PRESERVED,
                reason_code="CHARACTER_CAST_EXISTING_OFFICIAL_PRESERVED",
                preset_id="onnx.Yuewen",
                language=None,
            ),
            CastDecision(
                target_key="narrator",
                status=CastDecisionStatus.BLOCKED,
                reason_code="CAST_PLAN_MODEL_UNAVAILABLE",
                preset_id=None,
                language=None,
            ),
        ),
        warnings=(),
    )

    assert _no_assignment_terminal_state(solution, has_warnings=True) == (
        "failed",
        "CAST_PLAN_ALL_TARGETS_FAILED",
    )


def test_all_preserved_targets_complete_without_an_empty_write_batch() -> None:
    solution = CharacterCastSolution(
        baseline_sha256="a" * 64,
        decisions=(
            CastDecision(
                target_key="character:preserved",
                status=CastDecisionStatus.PRESERVED,
                reason_code="CHARACTER_CAST_EXISTING_OFFICIAL_PRESERVED",
                preset_id="onnx.Yuewen",
                language=None,
            ),
        ),
        warnings=(),
    )

    assert _no_assignment_terminal_state(solution, has_warnings=False) == (
        "ready_applied",
        None,
    )


def test_single_target_lease_finishes_and_links_the_atomic_action_chain(
    cast_engine: Engine,
) -> None:
    factory = _factory(cast_engine)
    novel_id, timeline_id = _seed_novel(factory)
    service = SqlAlchemyCharacterCastPlanService(factory)
    reservation = _reserve(service, novel_id=novel_id, timeline_id=timeline_id)

    lease = service.claim_next(
        novel_id=novel_id,
        command_id=reservation.command_id,
    )
    assert lease is not None and lease.target_key == "narrator"
    assert service.claim_next(
        novel_id=novel_id,
        command_id=reservation.command_id,
    ) is None
    assert not service.finish_analysis(
        novel_id=novel_id,
        command_id=reservation.command_id,
        item_id=lease.item_id,
        attempt=lease.attempt,
        fence_token=uuid4(),
        analysis=CharacterCastTargetAnalysis(
            workspace_digest=lease.workspace_digest,
            brief=_brief(),
            model_evidence={"schema_version": "model-execution-evidence/2"},
        ),
    )
    assert service.finish_analysis(
        novel_id=novel_id,
        command_id=reservation.command_id,
        item_id=lease.item_id,
        attempt=lease.attempt,
        fence_token=lease.fence_token,
        analysis=CharacterCastTargetAnalysis(
            workspace_digest=lease.workspace_digest,
            brief=_brief(),
            model_evidence={"schema_version": "model-execution-evidence/2"},
        ),
    )

    result = service.finalize_if_ready(
        novel_id=novel_id,
        command_id=reservation.command_id,
    )
    assert result.state == "ready_applied"
    assert result.progress_current == result.progress_total == 1
    assert len(result.assignments) == 1
    assert result.assignments[0].voice_action_command_id is not None
    assert result.items[0].state == "assigned"
    assert result.items[0].voice_action_command_id == (
        result.assignments[0].voice_action_command_id
    )

    with factory() as session:
        assert session.scalar(
            select(func.count()).select_from(VoiceActionCommand).where(
                VoiceActionCommand.novel_id == novel_id
            )
        ) == 1
        settings = session.scalar(
            select(NovelNarrationSettings).where(
                NovelNarrationSettings.novel_id == novel_id
            )
        )
        assert settings is not None and settings.version == 1


def test_workspace_drift_after_analysis_produces_zero_voice_writes(
    cast_engine: Engine,
) -> None:
    factory = _factory(cast_engine)
    novel_id, timeline_id = _seed_novel(factory)
    service = SqlAlchemyCharacterCastPlanService(factory)
    reservation = _reserve(service, novel_id=novel_id, timeline_id=timeline_id)
    lease = service.claim_next(
        novel_id=novel_id,
        command_id=reservation.command_id,
    )
    assert lease is not None
    assert service.finish_analysis(
        novel_id=novel_id,
        command_id=reservation.command_id,
        item_id=lease.item_id,
        attempt=lease.attempt,
        fence_token=lease.fence_token,
        analysis=CharacterCastTargetAnalysis(
            workspace_digest=lease.workspace_digest,
            brief=_brief(),
            model_evidence={"schema_version": "model-execution-evidence/2"},
        ),
    )
    with factory() as session, session.begin():
        novel = session.get(Novel, novel_id)
        assert novel is not None
        novel.main_plot = "作者在分析期间修改了主线"

    result = service.finalize_if_ready(
        novel_id=novel_id,
        command_id=reservation.command_id,
    )
    assert result.state == "ready_unapplied"
    assert any(warning.code == "CAST_PLAN_AUTHORITY_DRIFT" for warning in result.warnings)
    with factory() as session:
        assert session.scalar(
            select(func.count()).select_from(VoiceActionCommand).where(
                VoiceActionCommand.novel_id == novel_id
            )
        ) == 0
        assert session.scalar(
            select(func.count()).select_from(NovelNarrationSettings).where(
                NovelNarrationSettings.novel_id == novel_id
            )
        ) == 0


def test_expired_lease_rejects_stale_fence_and_retry_clears_stale_failure_warning(
    cast_engine: Engine,
) -> None:
    factory = _factory(cast_engine)
    novel_id, timeline_id = _seed_novel(factory)
    service = SqlAlchemyCharacterCastPlanService(factory)
    reservation = _reserve(service, novel_id=novel_id, timeline_id=timeline_id)
    first = service.claim_next(
        novel_id=novel_id,
        command_id=reservation.command_id,
    )
    assert first is not None
    with factory() as session, session.begin():
        item = session.get(CharacterCastPlanItem, first.item_id)
        assert item is not None
        item.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)

    recovered = service.claim_next(
        novel_id=novel_id,
        command_id=reservation.command_id,
    )
    assert recovered is not None
    assert recovered.attempt == first.attempt + 1
    assert recovered.fence_token != first.fence_token
    assert not service.fail_analysis(
        novel_id=novel_id,
        command_id=reservation.command_id,
        item_id=first.item_id,
        attempt=first.attempt,
        fence_token=first.fence_token,
    )
    assert service.fail_analysis(
        novel_id=novel_id,
        command_id=reservation.command_id,
        item_id=recovered.item_id,
        attempt=recovered.attempt,
        fence_token=recovered.fence_token,
        failure_code="CAST_PLAN_MODEL_UNAVAILABLE",
    )

    failed = service.finalize_if_ready(
        novel_id=novel_id,
        command_id=reservation.command_id,
    )
    assert failed.state == "failed" and failed.retryable
    assert any(
        warning.code == "CAST_PLAN_MODEL_UNAVAILABLE"
        for warning in failed.warnings
    )
    retried = service.retry(
        novel_id=novel_id,
        command_id=reservation.command_id,
    )
    assert retried.state == "analyzing"
    assert retried.progress_current == 0
    assert all(
        warning.code != "CAST_PLAN_MODEL_UNAVAILABLE"
        for warning in retried.warnings
    )
    with factory() as session:
        row = session.get(CharacterCastPlanCommand, reservation.command_id)
        assert row is not None and row.failure_code is None
        item = session.scalar(
            select(CharacterCastPlanItem).where(
                CharacterCastPlanItem.command_id == reservation.command_id
            )
        )
        assert item is not None
        assert item.state == "pending"
        assert item.failure_code is None
        assert item.warning_code is None
        assert item.attempt == 2
