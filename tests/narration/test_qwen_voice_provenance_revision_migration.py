from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (
    ROOT
    / "backend/migrations/versions/20260909_0046_qwen_voice_provenance_revision_key.py"
)


def test_qwen_provenance_revision_key_correction_is_narrow_and_fail_closed() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    for marker in (
        'revision = "20260909_0046"',
        'down_revision = "20260909_0045"',
        "pg_get_functiondef",
        "old_fragment",
        "local_model_revision",
        "position(old_fragment IN function_definition)=0",
        "EXECUTE replace(function_definition, old_fragment, new_fragment)",
    ):
        assert marker in source
    for forbidden in (
        "DELETE FROM",
        "UPDATE voice_",
        "from backend.models",
        "create_engine",
    ):
        assert forbidden not in source
