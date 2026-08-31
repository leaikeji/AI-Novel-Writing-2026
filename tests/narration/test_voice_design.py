from __future__ import annotations

from backend.narration.character_voice_matching import (
    CharacterVoiceBrief,
    CharacterVoiceLanguage,
    CharacterVoicePresentation,
    CharacterVoiceTexture,
)
from backend.narration.voice_design import build_voice_design_instruction


def test_instruction_uses_only_known_brief_dimensions() -> None:
    brief = CharacterVoiceBrief(
        language=CharacterVoiceLanguage.ZH_CN,
        presentation=CharacterVoicePresentation.ANDROGYNOUS,
        pitch=-1,
        pace=None,
        energy=1,
        texture=CharacterVoiceTexture.FIRM,
        evidence_fields=(
            "language:character.voice_language",
            "presentation:character.voice_presentation",
            "pitch:character.voice_pitch",
            "energy:character.voice_energy",
            "texture:character.voice_texture",
        ),
    )

    result = build_voice_design_instruction(
        brief,
        default_language=CharacterVoiceLanguage.EN,
    )

    assert result.language is CharacterVoiceLanguage.ZH_CN
    assert "中性声音呈现" in result.text
    assert "略低音" in result.text
    assert "较有活力" in result.text
    assert "坚定质感" in result.text
    assert "语速" not in result.text


def test_unknown_dimensions_stay_unspecified_and_default_language_is_explicit() -> None:
    brief = CharacterVoiceBrief(
        language=None,
        presentation=None,
        pitch=None,
        pace=None,
        energy=None,
        texture=None,
        evidence_fields=(),
    )

    result = build_voice_design_instruction(
        brief,
        default_language=CharacterVoiceLanguage.EN,
    )

    assert result.language is CharacterVoiceLanguage.EN
    assert "no specified vocal traits" in result.text
    assert "do not infer identity" in result.text
