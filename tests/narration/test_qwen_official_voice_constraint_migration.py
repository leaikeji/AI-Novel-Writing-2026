from __future__ import annotations

from pathlib import Path

from backend.models import VoiceActionCommand


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (
    ROOT
    / "backend/migrations/versions/20260909_0045_qwen_official_voice_constraints.py"
)


def test_qwen_official_voice_constraint_replaces_retired_moss_guard() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "20260909_0045"' in source
    assert 'down_revision = "20260908_0044"' in source
    assert "('qwen.WarmFemale','qwen.ClearMale')" in source
    assert ")) NOT VALID" in source
    assert "provider_id='qwen-tts'" in source
    assert "qwen-tts-catalog://" in source
    assert "OpenMOSS-Team" not in source
    assert "onnx." not in source
    assert "DELETE FROM" not in source
    assert "UPDATE voice_" not in source


def test_voice_action_model_accepts_only_the_pinned_qwen_catalog() -> None:
    constraint = next(
        item
        for item in VoiceActionCommand.__table__.constraints
        if item.name == "ck_voice_action_command_preset_key"
    )
    sql = str(constraint.sqltext)
    assert "qwen.WarmFemale" in sql
    assert "qwen.ClearMale" in sql
    assert "onnx." not in sql
