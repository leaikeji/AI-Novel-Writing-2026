from __future__ import annotations

from pathlib import Path

from sqlalchemy import CheckConstraint

from backend.models import VoiceProfileVersion


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (
    ROOT
    / "backend/migrations/versions/20260912_0055_qwen_private_voice_mandarin.py"
)


def test_private_voice_mandarin_migration_is_narrow_and_forward_only() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'revision = "20260912_0055"' in source
    assert 'down_revision = "20260912_0054"' in source
    assert "language='zh-CN'" in source
    assert "source_type<>'generated'" in source
    assert "ck_voice_profile_version_product_language" in source
    assert "ck_voice_profile_version_generated_reference" in source
    assert "ck_narration_scope_override_mandarin" in source
    assert "reference_asset_id IS NOT NULL" in source
    assert "NOT VALID" in source
    assert "narration_check_official_voice_action_closure_v1" in source
    assert "CREATE OR REPLACE FUNCTION narration_guard_voice_preview_lifecycle_v1" in source
    assert "generated_reference_publication" in source
    assert "OLD.reference_asset_id IS NULL" in source
    assert "NEW.reference_asset_id IS NOT NULL" in source
    assert "job.resource_class='qwen-tts'" in source
    assert "tts_nano_model_runs" not in source
    assert "toSSA_jsonb" not in source
    assert "IS NOT-book" not in source
    assert "UPDATE voice_" not in source
    assert "DELETE FROM" not in source
    assert "MOSS" not in source
    assert "Nano" not in source
    assert "VoiceGenerator" not in source


def test_voice_version_model_mirrors_new_mandarin_reference_guards() -> None:
    constraints = {
        item.name: str(item.sqltext)
        for item in VoiceProfileVersion.__table__.constraints
        if isinstance(item, CheckConstraint) and item.name is not None
    }

    assert "language = 'zh-CN'" in constraints[
        "ck_voice_profile_version_product_language"
    ]
    generated = constraints["ck_voice_profile_version_generated_reference"]
    assert "source_type <> 'generated'" in generated
    assert "preview_ready" in generated
    assert "locked" in generated
    assert "reference_asset_id IS NOT NULL" in generated
