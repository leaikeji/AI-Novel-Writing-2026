from __future__ import annotations

import os

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from backend.novel_workspace_service import (
    WorkspaceManifestError,
    _decode_cursor,
    get_workspace_manifest,
)
from backend.services import list_novels
from .benchmark_current_paths import PROFILES, cleanup, guarded_engine, seed_profile


pytestmark = pytest.mark.long_novel


def test_workspace_manifest_rejects_invalid_cursor_without_database() -> None:
    with pytest.raises(WorkspaceManifestError, match="游标"):
        _decode_cursor("not-json")


@pytest.mark.skipif(
    os.environ.get("AI_NOVEL_RUN_PLAN52_NAV_SCALE") != "1",
    reason="set AI_NOVEL_RUN_PLAN52_NAV_SCALE=1 for the isolated navigation scale test",
)
@pytest.mark.parametrize("profile_name", ["1m", "5m"])
def test_navigation_is_bounded_at_long_novel_scale(profile_name: str) -> None:
    engine = guarded_engine()
    seed = None
    statements: list[str] = []

    def record_sql(*args: object) -> None:
        statements.append(str(args[2]))

    event.listen(engine, "before_cursor_execute", record_sql)
    try:
        seed, _ = seed_profile(engine, PROFILES[profile_name])
        statements.clear()
        with Session(engine) as session:
            first = get_workspace_manifest(session, seed.novel_id, limit=200)
            assert len(first["items"]) == 200
            assert first["next_cursor"] is not None
            assert all("content_markdown" not in item for item in first["items"])
            second = get_workspace_manifest(
                session,
                seed.novel_id,
                cursor=first["next_cursor"],
                limit=200,
            )
            assert len(second["items"]) == 200
        assert len(statements) == 6
        assert all("content_markdown" not in statement for statement in statements)

        statements.clear()
        with Session(engine) as session:
            novels = list_novels(session)
            current = next(item for item in novels if item["id"] == str(seed.novel_id))
            assert current["chapter_count"] == PROFILES[profile_name].chapter_count
            assert current["visible_character_count"] == PROFILES[profile_name].target_characters
        assert len(statements) == 1
        assert "content_markdown" not in statements[0]
    finally:
        event.remove(engine, "before_cursor_execute", record_sql)
        if seed is not None:
            cleanup(engine, seed)
        engine.dispose()
