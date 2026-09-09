"""Strict voice-design briefs independent of any preset catalogue."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import re
from typing import Final


BRIEF_SCHEMA_VERSION: Final = "character-voice-brief/1"
VOICE_BRIEF_INVALID: Final = "VOICE_BRIEF_INVALID"

_EVIDENCE_PATH = re.compile(
    r"^(language|presentation|pitch|pace|energy|texture):"
    r"(character|selected_instance|aliases|relationships|projected_state)"
    r"(?:\.|\[)[A-Za-z0-9_\-\[\].]+$"
)
_IDENTITY_ONLY_EVIDENCE = re.compile(
    r"^[a-z_]+:(?:character\.name|selected_instance\.display_label|aliases(?:\[|\.))"
)
_BRIEF_DIMENSIONS: Final = (
    "language",
    "presentation",
    "pitch",
    "pace",
    "energy",
    "texture",
)


class CharacterVoiceLanguage(str, Enum):
    ZH_CN = "zh-CN"
    EN = "en"
    JA_JP = "ja-JP"


class CharacterVoicePresentation(str, Enum):
    MASCULINE = "masculine"
    FEMININE = "feminine"
    ANDROGYNOUS = "androgynous"


class CharacterVoiceTexture(str, Enum):
    CLEAR = "clear"
    WARM = "warm"
    AIRY = "airy"
    HUSKY = "husky"
    FIRM = "firm"
    SOFT = "soft"
    BRIGHT = "bright"
    DARK = "dark"


class VoiceBriefError(ValueError):
    """Stable fail-closed error for a malformed voice brief."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _invalid(message: str) -> VoiceBriefError:
    return VoiceBriefError(VOICE_BRIEF_INVALID, message)


def _exact_enum(enum_type: type[Enum], value: object, *, field_name: str) -> Enum | None:
    if value is None:
        return None
    if type(value) is not str:
        raise _invalid(f"{field_name} must be exact text or null")
    try:
        return enum_type(value)
    except ValueError as error:
        raise _invalid(f"{field_name} is outside the frozen vocabulary") from error


def _axis(value: object, *, field_name: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value not in {-2, -1, 0, 1, 2}:
        raise _invalid(f"{field_name} must be -2..2 or null")
    return value


@dataclass(frozen=True, slots=True)
class CharacterVoiceBrief:
    """Validated Qwen voice-design axes; unknown facts remain ``None``."""

    language: CharacterVoiceLanguage | None
    presentation: CharacterVoicePresentation | None
    pitch: int | None
    pace: int | None
    energy: int | None
    texture: CharacterVoiceTexture | None
    evidence_fields: tuple[str, ...]
    schema_version: str = BRIEF_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != BRIEF_SCHEMA_VERSION:
            raise _invalid("character voice brief schema changed")
        if self.language is not None and type(self.language) is not CharacterVoiceLanguage:
            raise _invalid("language must use the frozen enum")
        if self.presentation is not None and type(self.presentation) is not CharacterVoicePresentation:
            raise _invalid("presentation must use the frozen enum")
        for field_name in ("pitch", "pace", "energy"):
            _axis(getattr(self, field_name), field_name=field_name)
        if self.texture is not None and type(self.texture) is not CharacterVoiceTexture:
            raise _invalid("texture must use the frozen enum")
        if type(self.evidence_fields) is not tuple:
            raise _invalid("evidence_fields must be a tuple")
        if len(self.evidence_fields) > 48 or len(set(self.evidence_fields)) != len(self.evidence_fields):
            raise _invalid("evidence_fields must be bounded and unique")
        dimensions_with_evidence: set[str] = set()
        for evidence in self.evidence_fields:
            if type(evidence) is not str or len(evidence) > 240:
                raise _invalid("evidence field path is malformed")
            match = _EVIDENCE_PATH.fullmatch(evidence)
            if match is None:
                raise _invalid("evidence field path is outside the workspace")
            if _IDENTITY_ONLY_EVIDENCE.match(evidence) is not None:
                raise _invalid("names and aliases cannot evidence a voice characteristic")
            dimensions_with_evidence.add(match.group(1))
        populated = {
            field_name
            for field_name in _BRIEF_DIMENSIONS
            if getattr(self, field_name) is not None
        }
        if dimensions_with_evidence != populated:
            raise _invalid("every known dimension needs evidence and unknown dimensions cannot claim it")

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "language": self.language.value if self.language is not None else None,
            "presentation": self.presentation.value if self.presentation is not None else None,
            "pitch": self.pitch,
            "pace": self.pace,
            "energy": self.energy,
            "texture": self.texture.value if self.texture is not None else None,
            "evidence_fields": list(self.evidence_fields),
        }


def parse_character_voice_brief(value: object) -> CharacterVoiceBrief:
    if type(value) is not dict:
        raise _invalid("character voice brief must be an object")
    expected = {"schema_version", *_BRIEF_DIMENSIONS, "evidence_fields"}
    if set(value) != expected:
        raise _invalid("character voice brief fields changed")
    evidence = value["evidence_fields"]
    if type(evidence) is not list:
        raise _invalid("evidence_fields must be a JSON array")
    return CharacterVoiceBrief(
        schema_version=value["schema_version"],
        language=_exact_enum(CharacterVoiceLanguage, value["language"], field_name="language"),
        presentation=_exact_enum(CharacterVoicePresentation, value["presentation"], field_name="presentation"),
        pitch=_axis(value["pitch"], field_name="pitch"),
        pace=_axis(value["pace"], field_name="pace"),
        energy=_axis(value["energy"], field_name="energy"),
        texture=_exact_enum(CharacterVoiceTexture, value["texture"], field_name="texture"),
        evidence_fields=tuple(evidence),
    )


def build_character_voice_prompt(workspace_payload: dict[str, object]) -> str:
    if type(workspace_payload) is not dict:
        raise TypeError("character voice workspace payload must be an object")
    evidence = json.dumps(workspace_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (
        "你正在为作者自有小说提取人物声音描述。只依据下面已保存的人物工作区 JSON，"
        "禁止用姓名、别名、年龄或身份刻板印象补全声音；缺失信息必须为 null。\n"
        "只返回裸 JSON，不选择预设音色。字段为 schema_version、language、presentation、"
        "pitch、pace、energy、texture、evidence_fields。\n"
        f"人物工作区：{evidence}"
    )


__all__ = [
    "BRIEF_SCHEMA_VERSION",
    "VOICE_BRIEF_INVALID",
    "CharacterVoiceBrief",
    "CharacterVoiceLanguage",
    "CharacterVoicePresentation",
    "CharacterVoiceTexture",
    "VoiceBriefError",
    "build_character_voice_prompt",
    "parse_character_voice_brief",
]
