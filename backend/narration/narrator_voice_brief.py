"""Strict narrator voice briefs derived only from saved novel evidence.

Narration has no character workspace, so it must not borrow character evidence
paths.  This module owns a separate schema and allowlist while reusing the same
frozen acoustic vocabulary as character casting.  The model describes axes;
it never selects an official preset.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Final, Mapping

from .character_voice_matching import (
    CharacterVoiceLanguage,
    CharacterVoiceMatchingError,
    CharacterVoicePresentation,
    CharacterVoiceTexture,
)


NARRATOR_BRIEF_SCHEMA_VERSION: Final = "narrator-voice-brief/1"
NARRATOR_VOICE_BRIEF_INVALID: Final = "NARRATOR_VOICE_BRIEF_INVALID"

_BRIEF_DIMENSIONS: Final = (
    "language",
    "presentation",
    "pitch",
    "pace",
    "energy",
    "texture",
)
_NOVEL_EVIDENCE_FIELDS: Final = frozenset(
    {
        "title",
        "genre",
        "subgenre",
        "description",
        "idea",
        "highlight",
        "background",
        "main_plot",
    }
)
_EVIDENCE_PATH = re.compile(
    r"^(language|presentation|pitch|pace|energy|texture):"
    r"(?:narration_settings\.language|novel\."
    r"(?:title|genre|subgenre|description|idea|highlight|background|main_plot))$"
)


def _invalid(message: str) -> CharacterVoiceMatchingError:
    # Reuse the existing typed exception boundary while keeping a narrator-
    # specific stable code for HTTP/service integration.
    return CharacterVoiceMatchingError(NARRATOR_VOICE_BRIEF_INVALID, message)


def _exact_enum(enum_type: type, value: object, *, field_name: str):
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
class NarratorVoiceBrief:
    """Validated narrator axes; every known dimension cites saved evidence."""

    language: CharacterVoiceLanguage | None
    presentation: CharacterVoicePresentation | None
    pitch: int | None
    pace: int | None
    energy: int | None
    texture: CharacterVoiceTexture | None
    evidence_fields: tuple[str, ...]
    schema_version: str = NARRATOR_BRIEF_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != NARRATOR_BRIEF_SCHEMA_VERSION:
            raise _invalid("narrator voice brief schema changed")
        if self.language is not None and type(self.language) is not CharacterVoiceLanguage:
            raise _invalid("language must use the frozen enum")
        if self.presentation is not None and type(
            self.presentation
        ) is not CharacterVoicePresentation:
            raise _invalid("presentation must use the frozen enum")
        for field_name in ("pitch", "pace", "energy"):
            _axis(getattr(self, field_name), field_name=field_name)
        if self.texture is not None and type(self.texture) is not CharacterVoiceTexture:
            raise _invalid("texture must use the frozen enum")
        if type(self.evidence_fields) is not tuple:
            raise _invalid("evidence_fields must be a tuple")
        if len(self.evidence_fields) > 48 or len(set(self.evidence_fields)) != len(
            self.evidence_fields
        ):
            raise _invalid("evidence_fields must be bounded and unique")

        dimensions_with_evidence: set[str] = set()
        for evidence in self.evidence_fields:
            if type(evidence) is not str or len(evidence) > 240:
                raise _invalid("evidence field path is malformed")
            match = _EVIDENCE_PATH.fullmatch(evidence)
            if match is None:
                raise _invalid("evidence field path is outside saved novel metadata")
            dimensions_with_evidence.add(match.group(1))

        populated = {
            field_name
            for field_name in _BRIEF_DIMENSIONS
            if getattr(self, field_name) is not None
        }
        if dimensions_with_evidence != populated:
            raise _invalid(
                "every known dimension needs evidence and unknown dimensions cannot claim it"
            )

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "language": self.language.value if self.language is not None else None,
            "presentation": (
                self.presentation.value if self.presentation is not None else None
            ),
            "pitch": self.pitch,
            "pace": self.pace,
            "energy": self.energy,
            "texture": self.texture.value if self.texture is not None else None,
            "evidence_fields": list(self.evidence_fields),
        }


def parse_narrator_voice_brief(value: object) -> NarratorVoiceBrief:
    """Parse one exact model response without coercion or extra fields."""

    if type(value) is not dict:
        raise _invalid("narrator voice brief must be an object")
    expected = {"schema_version", *_BRIEF_DIMENSIONS, "evidence_fields"}
    if set(value) != expected:
        raise _invalid("narrator voice brief fields changed")
    evidence = value["evidence_fields"]
    if type(evidence) is not list:
        raise _invalid("evidence_fields must be a JSON array")
    return NarratorVoiceBrief(
        schema_version=value["schema_version"],
        language=_exact_enum(
            CharacterVoiceLanguage, value["language"], field_name="language"
        ),
        presentation=_exact_enum(
            CharacterVoicePresentation,
            value["presentation"],
            field_name="presentation",
        ),
        pitch=_axis(value["pitch"], field_name="pitch"),
        pace=_axis(value["pace"], field_name="pace"),
        energy=_axis(value["energy"], field_name="energy"),
        texture=_exact_enum(
            CharacterVoiceTexture, value["texture"], field_name="texture"
        ),
        evidence_fields=tuple(evidence),
    )


def build_narrator_voice_prompt(
    novel_payload: Mapping[str, object],
    *,
    narration_language: str | None,
) -> str:
    """Build a prompt containing only the frozen saved-novel evidence set."""

    if not isinstance(novel_payload, Mapping):
        raise TypeError("narrator novel payload must be a mapping")
    if narration_language is not None:
        try:
            CharacterVoiceLanguage(narration_language)
        except (TypeError, ValueError) as error:
            raise ValueError("unsupported saved narration language") from error

    novel_evidence: dict[str, object] = {}
    for field_name in sorted(_NOVEL_EVIDENCE_FIELDS):
        value = novel_payload.get(field_name)
        if value is not None and type(value) is not str:
            raise TypeError(f"saved novel {field_name} must be text or null")
        novel_evidence[field_name] = value
    evidence_payload = {
        "narration_settings": {"language": narration_language},
        "novel": novel_evidence,
    }
    evidence = json.dumps(
        evidence_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        "你正在为作者自有小说提取旁白声音描述。只依据下面已保存的小说元数据和朗读语言，"
        "不得读取未保存草稿，也不得使用下列字段之外的信息推断；缺失信息必须为 null。\n"
        "只返回一个裸 JSON 对象，不要解释，不要选择或输出任何 preset ID。字段必须且只能是："
        "schema_version='narrator-voice-brief/1'；language 为 zh-CN/en/ja-JP/null；"
        "presentation 为 masculine/feminine/androgynous/null；pitch、pace、energy 为 "
        "-2..2 的整数或 null；texture 为 clear/warm/airy/husky/firm/soft/bright/dark/null；"
        "evidence_fields 为字符串数组。每个非空维度必须至少引用一个路径，路径只能是"
        "'<维度>:narration_settings.language' 或 '<维度>:novel.title/genre/subgenre/"
        "description/idea/highlight/background/main_plot'；空维度不得声称证据。\n"
        f"旁白证据：{evidence}"
    )


__all__ = [
    "NARRATOR_BRIEF_SCHEMA_VERSION",
    "NARRATOR_VOICE_BRIEF_INVALID",
    "NarratorVoiceBrief",
    "build_narrator_voice_prompt",
    "parse_narrator_voice_brief",
]
