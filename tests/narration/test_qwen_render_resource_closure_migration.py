from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (
    ROOT
    / "backend/migrations/versions/20260909_0047_qwen_render_resource_closures.py"
)


def test_qwen_render_resource_closure_migration_is_narrow_and_fail_closed() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    for marker in (
        'revision = "20260909_0047"',
        'down_revision = "20260909_0046"',
        "narration_guard_ready_render_assets()",
        "narration_failed_segment_retry_authorized_v1(uuid,uuid,uuid,uuid,uuid)",
        "pg_get_functiondef",
        "j.resource_class=''moss-nano''",
        "j.resource_class=''qwen-tts''",
        "position(old_fragment IN function_definition)=0",
        "EXECUTE replace(function_definition, old_fragment, new_fragment)",
    ):
        assert marker in source
    for forbidden in (
        "DELETE FROM",
        "UPDATE narration_",
        "DROP FUNCTION",
        "from backend.models",
        "create_engine",
    ):
        assert forbidden not in source
