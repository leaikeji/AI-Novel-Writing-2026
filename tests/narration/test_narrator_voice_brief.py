from __future__ import annotations

import json

import pytest

from backend.narration.character_voice_matching import CharacterVoiceMatchingError
from backend.narration.narrator_voice_brief import (
    NARRATOR_VOICE_BRIEF_INVALID,
    NarratorVoiceBrief,
    build_narrator_voice_prompt,
    parse_narrator_voice_brief,
)
from backend.narration.schemas import NarratorVoiceBriefResource


def _valid_payload() -> dict[str, object]:
    return {
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


def test_narrator_brief_parser_is_exact_and_round_trips() -> None:
    brief = parse_narrator_voice_brief(_valid_payload())

    assert isinstance(brief, NarratorVoiceBrief)
    assert brief.language.value == "zh-CN"
    assert brief.to_payload() == _valid_payload()
    assert NarratorVoiceBriefResource.model_validate(brief.to_payload()).model_dump(
        mode="json"
    ) == _valid_payload()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update({"preset_id": "onnx.Junhao"}),
        lambda payload: payload.update({"pace": True}),
        lambda payload: payload.update(
            {
                "evidence_fields": [
                    *payload["evidence_fields"],
                    "texture:character.description",
                ]
            }
        ),
        lambda payload: payload.update(
            {"evidence_fields": payload["evidence_fields"][:-1]}
        ),
        lambda payload: payload.update(
            {
                "evidence_fields": [
                    *payload["evidence_fields"],
                    "language:novel.unsaved_draft",
                ]
            }
        ),
    ],
)
def test_narrator_brief_rejects_extra_coercion_and_out_of_scope_evidence(
    mutate,
) -> None:
    payload = _valid_payload()
    mutate(payload)

    with pytest.raises(CharacterVoiceMatchingError) as caught:
        parse_narrator_voice_brief(payload)

    assert caught.value.code == NARRATOR_VOICE_BRIEF_INVALID


def test_narrator_prompt_whitelists_saved_novel_metadata() -> None:
    prompt = build_narrator_voice_prompt(
        {
            "title": "雾港来信",
            "genre": "悬疑",
            "subgenre": "刑侦",
            "description": "克制冷峻的调查故事",
            "idea": "一封迟到十年的信",
            "highlight": "多线索收束",
            "background": "沿海旧城",
            "main_plot": "刑警追查旧案",
            "unsaved_draft": "绝不能进入提示词",
            "characters": "也不属于旁白证据",
        },
        narration_language="zh-CN",
    )

    assert "绝不能进入提示词" not in prompt
    assert "也不属于旁白证据" not in prompt
    assert "preset ID" in prompt
    encoded = prompt.split("旁白证据：", 1)[1]
    payload = json.loads(encoded)
    assert set(payload) == {"narration_settings", "novel"}
    assert set(payload["novel"]) == {
        "title",
        "genre",
        "subgenre",
        "description",
        "idea",
        "highlight",
        "background",
        "main_plot",
    }


def test_narrator_prompt_rejects_unsupported_saved_language() -> None:
    with pytest.raises(ValueError, match="unsupported saved narration language"):
        build_narrator_voice_prompt({}, narration_language="fr")
