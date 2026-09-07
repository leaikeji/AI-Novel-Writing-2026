from __future__ import annotations

from datetime import UTC, datetime, timedelta
from dataclasses import replace
import os
from types import SimpleNamespace
from typing import Callable, Iterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Connection, Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from backend.models import Novel, NovelCharacter
from backend.narration.voice_generator_service import SqlAlchemyVoiceGeneratorService
from backend.narration.voice_preparation import VoicePreparationCreateRequest
from backend.narration.voice_preparation_service import SqlAlchemyVoicePreparationService
from backend.narration.services import InvalidNarrationState, NarrationCasConflict
from tests.narration.current_schema_gate import assert_database_at_repository_head
from tests.narration.digest_fixtures import TEST_DIGEST_KEYRING


EXPECTED_DATABASE = "ai_novel_world_2026_tts_test"
SessionFactory = Callable[[], Session]
NOW = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)


def _live_url() -> str:
    raw = os.environ.get("TTS_TEST_DATABASE_URL", "").strip()
    if not raw:
        pytest.skip("TTS_TEST_DATABASE_URL is not configured")
    parsed = make_url(raw)
    if (
        not parsed.drivername.startswith("postgresql")
        or parsed.database != EXPECTED_DATABASE
        or parsed.host not in {"127.0.0.1", "localhost", "::1"}
    ):
        raise RuntimeError(
            "voice preparation tests require the exact loopback disposable TTS database"
        )
    production = os.environ.get("AI_NOVEL_DATABASE_URL", "").strip()
    if production:
        current = make_url(production)
        if (parsed.host, parsed.port, parsed.database) == (
            current.host,
            current.port,
            current.database,
        ):
            raise RuntimeError("voice preparation test database must differ from production")
    return raw


@pytest.fixture
def preparation_pg() -> Iterator[tuple[Connection, SessionFactory]]:
    engine: Engine = create_engine(_live_url(), pool_pre_ping=True)
    connection = engine.connect()
    outer = connection.begin()
    assert_database_at_repository_head(connection)
    required = {"voice_preparation_commands", "voice_preparation_items"}
    if not required <= set(inspect(connection).get_table_names()):
        raise RuntimeError("voice preparation PostgreSQL schema is incomplete")
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


class _Dump:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def model_dump(self, *, mode: str) -> dict[str, object]:
        assert mode == "json"
        return dict(self._payload)


class _WorkspaceService:
    def get_workspace(self, novel_id: UUID, character_id: UUID):
        return SimpleNamespace(
            character=_Dump({"id": str(character_id), "novel_id": str(novel_id)}),
            selected_instance=_Dump({"id": str(character_id)}),
            aliases=(),
            relationships=(),
            projected_state=_Dump({"current_facts": []}),
        )


def _seed(factory: SessionFactory) -> tuple[UUID, UUID]:
    novel_id, character_id = uuid4(), uuid4()
    with factory() as session:
        session.add(
            Novel(
                id=novel_id,
                title="潮汐盲区",
                author_name="",
                description="",
                writing_type="long",
                audience="",
                genre="悬疑",
                subgenre="刑侦",
                idea="",
                template_name="",
                template_data={},
                cover_mode="none",
                cover_image_data="",
                outline_target_chapters=4,
                highlight="",
                background="",
                main_plot="",
                story_ledger_version=1,
                character_catalog_version=1,
                version=1,
            )
        )
        # ``protagonist`` is preserved by older novels and must be normalized
        # into the frozen preparation DTO without rewriting source data.
        session.add(
            NovelCharacter(
                id=character_id,
                novel_id=novel_id,
                role_type="protagonist",
                name="沈砚",
                description="调查员",
                details={},
                lifecycle_state="active",
                position=1,
                version=1,
            )
        )
        session.commit()
    return novel_id, character_id


def test_whole_book_create_normalizes_legacy_role_and_replays_timestamp(
    preparation_pg: tuple[Connection, SessionFactory],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _connection, factory = preparation_pg
    novel_id, character_id = _seed(factory)
    monkeypatch.setattr(
        "backend.narration.voice_preparation_service.service_for_session",
        lambda _session: _WorkspaceService(),
    )
    service = SqlAlchemyVoicePreparationService(
        factory,
        policy=object(),  # whole-book preparation performs no narration preflight
        voice_generator=SqlAlchemyVoiceGeneratorService(
            factory,
            digest_keyring=TEST_DIGEST_KEYRING,
        ),
    )
    request = VoicePreparationCreateRequest(
        novel_id=novel_id,
        document_id=None,
        expected_draft_version=None,
        expected_content_hash=None,
        expected_settings_version=None,
        idempotency_key="tts55-whole-book-preparation",
        actor="local-owner",
        explicit_requested_at=NOW,
    )

    first = service.create(request)
    replay = service.create(
        VoicePreparationCreateRequest(
            novel_id=novel_id,
            document_id=None,
            expected_draft_version=None,
            expected_content_hash=None,
            expected_settings_version=None,
            idempotency_key=request.idempotency_key,
            actor=request.actor,
            explicit_requested_at=NOW + timedelta(seconds=5),
        )
    )
    resource = service.get_resource(novel_id=novel_id, command_id=first.command_id)

    assert first.replayed is False
    assert replay.command_id == first.command_id and replay.replayed is True
    assert resource.progress_total == 1
    assert resource.current_target is not None
    assert resource.current_target.character_id == character_id
    assert resource.current_target.role_type == "main"
    assert resource.state == "reserved"


@pytest.mark.parametrize("drifted", [False, True])
def test_child_reservation_conflict_releases_durable_parent_activity_slot(
    preparation_pg: tuple[Connection, SessionFactory],
    monkeypatch: pytest.MonkeyPatch,
    drifted: bool,
) -> None:
    _connection, factory = preparation_pg
    novel_id, _character_id = _seed(factory)
    monkeypatch.setattr(
        "backend.narration.voice_preparation_service.service_for_session",
        lambda _session: _WorkspaceService(),
    )
    generator = SqlAlchemyVoiceGeneratorService(factory, digest_keyring=TEST_DIGEST_KEYRING)

    def conflict(**_kwargs):
        raise (NarrationCasConflict if drifted else InvalidNarrationState)(
            "another entry point changed or reserved this character"
        )

    monkeypatch.setattr(generator, "reserve", conflict)
    service = SqlAlchemyVoicePreparationService(factory, policy=object(), voice_generator=generator)
    request = VoicePreparationCreateRequest(
        novel_id=novel_id, document_id=None, expected_draft_version=None,
        expected_content_hash=None, expected_settings_version=None,
        idempotency_key="tts56-conflict-parent", actor="local-owner", explicit_requested_at=NOW,
    )
    first = service.create(request)
    service.reserve_next_pending(novel_id=novel_id, command_id=first.command_id)
    stored = service.get_resource(novel_id=novel_id, command_id=first.command_id)
    assert stored.state == ("superseded" if drifted else "failed")
    assert stored.failure_code == (
        "VOICE_PREPARATION_BINDING_DRIFTED" if drifted else "VOICE_PREPARATION_TARGET_FAILED"
    )
    assert stored.terminal
    # The partial command remains auditable, but its active unique index must
    # not prevent a fresh author request from taking a current snapshot.
    successor = service.create(replace(request, idempotency_key="tts56-conflict-successor"))
    assert successor.command_id != first.command_id
    assert service.get_resource(novel_id=novel_id, command_id=successor.command_id).state == "reserved"
