from __future__ import annotations

import pytest

from backend.model_runtime import (
    ModelVerificationError,
    normalize_creative_generation_json,
)


def test_ai_outline_character_output_is_normalized_to_typed_v2_draft() -> None:
    result = normalize_creative_generation_json(
        "outline_characters",
        {
            "characters": [
                {
                    "name": "沈砚舟",
                    "role_type": "main",
                    "gender": "男",
                    "age_at_story_start_note": "开篇约三十岁",
                    "identity_summary": "市档案馆数字化修复员",
                    "personality_summary": "凡事要求证据闭环，却会为保护证人独自承担风险。",
                    "core_goal": "找回被替换的火灾档案原件",
                    "bio": "曾以周砚之名生活，负责修复1988年火灾档案。",
                }
            ]
        },
        "",
    )

    character = result["characters"][0]
    assert character["schema_version"] == "outline-character-draft/2"
    assert character["draft_key"] == "ai-character-1"
    assert character["origin"] == "ai_candidate"
    assert character["identity_summary"] == "市档案馆数字化修复员"
    assert character["personality_summary"].startswith("凡事要求证据闭环")
    assert character["core_goal"] == "找回被替换的火灾档案原件"
    assert character["age_at_story_start_note"] == "开篇约三十岁"
    assert "character_id" not in character
    assert character["details"]["identity"] == character["identity_summary"]


@pytest.mark.parametrize("missing", ["identity_summary", "core_goal", "bio"])
def test_ai_outline_character_rejects_incomplete_v2_profile(missing: str) -> None:
    character = {
        "name": "沈砚舟",
        "role_type": "main",
        "gender": "男",
        "identity_summary": "市档案馆数字化修复员",
        "personality_summary": "凡事要求证据闭环，却会为保护证人独自承担风险。",
        "core_goal": "找回被替换的火灾档案原件",
        "bio": "曾以周砚之名生活。",
    }
    character.pop(missing)

    with pytest.raises(ModelVerificationError):
        normalize_creative_generation_json(
            "outline_characters",
            {"characters": [character]},
            "",
        )
