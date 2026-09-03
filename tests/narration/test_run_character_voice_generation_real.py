from __future__ import annotations

from uuid import UUID

import pytest

from backend.narration.character_voice_matching import (
    CharacterVoicePresentation,
    CharacterVoiceTexture,
)
from scripts.tts.run_character_voice_generation_real import (
    RealCharacterVoiceError,
    parse_character_spec,
)


CHARACTER_ID = UUID("61f1f123-b9d3-45db-b00d-ff8ac869c564")


def test_character_spec_is_strict_and_typed() -> None:
    result = parse_character_spec(
        f"{CHARACTER_ID}|masculine|-2|-1|0|dark"
    )

    assert result.character_id == CHARACTER_ID
    assert result.presentation is CharacterVoicePresentation.MASCULINE
    assert (result.pitch, result.pace, result.energy) == (-2, -1, 0)
    assert result.texture is CharacterVoiceTexture.DARK


@pytest.mark.parametrize(
    "value",
    (
        str(CHARACTER_ID),
        f"{CHARACTER_ID}|masculine|-3|0|0|dark",
        f"{CHARACTER_ID}|unknown|0|0|0|dark",
        f"{CHARACTER_ID}|masculine|0|0|0|metallic",
    ),
)
def test_character_spec_rejects_unfrozen_values(value: str) -> None:
    with pytest.raises(RealCharacterVoiceError, match="CHARACTER_SPEC_INVALID"):
        parse_character_spec(value)
