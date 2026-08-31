"""Deterministic CharacterVoiceBrief-to-instruction projection for Plan 40.

The language model may extract only the six frozen brief dimensions.  This
module turns those known values into a bounded local instruction without
looking at names, aliases, occupations, age labels, identities, or any other
character field.  Unknown dimensions remain unspecified.
"""

from __future__ import annotations

from dataclasses import dataclass
import unicodedata

from .character_voice_matching import (
    CharacterVoiceBrief,
    CharacterVoiceLanguage,
)


_ZH_PRESENTATION = {
    "masculine": "偏阳刚的声音呈现",
    "feminine": "偏柔美的声音呈现",
    "androgynous": "中性声音呈现",
}
_ZH_AXIS = {
    "pitch": {-2: "明显低音", -1: "略低音", 0: "中等音高", 1: "略高音", 2: "明显高音"},
    "pace": {-2: "明显慢速", -1: "略慢语速", 0: "中等语速", 1: "略快语速", 2: "明显快速"},
    "energy": {-2: "非常克制", -1: "较为克制", 0: "中等能量", 1: "较有活力", 2: "很有活力"},
}
_ZH_TEXTURE = {
    "clear": "清晰质感",
    "warm": "温暖质感",
    "airy": "轻盈气声质感",
    "husky": "沙哑质感",
    "firm": "坚定质感",
    "soft": "柔和质感",
    "bright": "明亮质感",
    "dark": "深沉质感",
}

_EN_PRESENTATION = {
    "masculine": "a masculine presentation",
    "feminine": "a feminine presentation",
    "androgynous": "an androgynous presentation",
}
_EN_AXIS = {
    "pitch": {-2: "very low pitch", -1: "slightly low pitch", 0: "mid pitch", 1: "slightly high pitch", 2: "very high pitch"},
    "pace": {-2: "very slow pace", -1: "slightly slow pace", 0: "moderate pace", 1: "slightly fast pace", 2: "very fast pace"},
    "energy": {-2: "very restrained energy", -1: "restrained energy", 0: "moderate energy", 1: "lively energy", 2: "very lively energy"},
}
_EN_TEXTURE = {
    "clear": "a clear texture",
    "warm": "a warm texture",
    "airy": "an airy texture",
    "husky": "a husky texture",
    "firm": "a firm texture",
    "soft": "a soft texture",
    "bright": "a bright texture",
    "dark": "a dark texture",
}

_JA_PRESENTATION = {
    "masculine": "男性的な声の表現",
    "feminine": "女性的な声の表現",
    "androgynous": "中性的な声の表現",
}
_JA_AXIS = {
    "pitch": {-2: "かなり低い音域", -1: "やや低い音域", 0: "中程度の音域", 1: "やや高い音域", 2: "かなり高い音域"},
    "pace": {-2: "かなり遅い話速", -1: "やや遅い話速", 0: "中程度の話速", 1: "やや速い話速", 2: "かなり速い話速"},
    "energy": {-2: "非常に抑制された力感", -1: "抑制された力感", 0: "中程度の力感", 1: "活気のある力感", 2: "非常に活気のある力感"},
}
_JA_TEXTURE = {
    "clear": "明瞭な質感",
    "warm": "温かい質感",
    "airy": "息の混じる軽い質感",
    "husky": "かすれた質感",
    "firm": "芯のある質感",
    "soft": "柔らかな質感",
    "bright": "明るい質感",
    "dark": "深みのある質感",
}


@dataclass(frozen=True, slots=True)
class VoiceDesignInstruction:
    language: CharacterVoiceLanguage
    text: str


def build_voice_design_instruction(
    brief: CharacterVoiceBrief,
    *,
    default_language: CharacterVoiceLanguage,
) -> VoiceDesignInstruction:
    """Return one stable, NFC-normalized instruction from known brief axes."""

    if type(brief) is not CharacterVoiceBrief:
        raise TypeError("voice design requires CharacterVoiceBrief")
    if type(default_language) is not CharacterVoiceLanguage:
        raise TypeError("default language must use CharacterVoiceLanguage")
    language = brief.language or default_language
    values: list[str] = []
    if language is CharacterVoiceLanguage.ZH_CN:
        if brief.presentation is not None:
            values.append(_ZH_PRESENTATION[brief.presentation.value])
        for field_name in ("pitch", "pace", "energy"):
            value = getattr(brief, field_name)
            if value is not None:
                values.append(_ZH_AXIS[field_name][value])
        if brief.texture is not None:
            values.append(_ZH_TEXTURE[brief.texture.value])
        known = "、".join(values) if values else "不指定具体声音特征"
        text = f"设计一条独特且自然的中文人物声音：{known}。未指定的维度保持中性，不推断人物身份。"
    elif language is CharacterVoiceLanguage.EN:
        if brief.presentation is not None:
            values.append(_EN_PRESENTATION[brief.presentation.value])
        for field_name in ("pitch", "pace", "energy"):
            value = getattr(brief, field_name)
            if value is not None:
                values.append(_EN_AXIS[field_name][value])
        if brief.texture is not None:
            values.append(_EN_TEXTURE[brief.texture.value])
        known = ", ".join(values) if values else "no specified vocal traits"
        text = f"Design one distinct, natural English character voice with {known}. Keep unspecified dimensions neutral and do not infer identity."
    else:
        if brief.presentation is not None:
            values.append(_JA_PRESENTATION[brief.presentation.value])
        for field_name in ("pitch", "pace", "energy"):
            value = getattr(brief, field_name)
            if value is not None:
                values.append(_JA_AXIS[field_name][value])
        if brief.texture is not None:
            values.append(_JA_TEXTURE[brief.texture.value])
        known = "、".join(values) if values else "具体的な声質は指定しない"
        text = f"自然で固有の日本語キャラクター音声を設計する：{known}。未指定の要素は中立に保ち、人物属性を推測しない。"
    normalized = unicodedata.normalize("NFC", text).strip()
    if not 1 <= len(normalized) <= 1_200:
        raise ValueError("voice design instruction is outside the frozen bound")
    return VoiceDesignInstruction(language=language, text=normalized)


__all__ = ["VoiceDesignInstruction", "build_voice_design_instruction"]
