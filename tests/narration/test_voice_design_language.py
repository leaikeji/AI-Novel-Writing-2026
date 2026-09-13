from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.narration.contracts import ContractError, require_mandarin_voice_design
from backend.narration.schemas import CreateDesignedVoiceVersionRequest


ACCEPTED_DESCRIPTIONS = (
    "26岁，青年男声；标准普通话，不使用方言。",
    "18岁，声音沙哑，听感接近四十岁；标准普通话。",
    "青年男声，不要播音腔，声音不像中年人。",
    "自然普通话，不要带任何地方口音。",
    "没有浓重口音，不带方言和英语口音。",
    "不要四川话、粤语或东北话，用标准普通话。",
    "不是粤语，而是标准普通话。",  # a clear correction is still an exclusion
    "不使用 方言，不要用粤语，标准普通话。",
    "禁止方言，不允许地方口音。",
    "不能使用方言，声音自然清晰。",
    "不要口音，但要清楚的吐字。",
)

REJECTED_DESCRIPTIONS = (
    "不用方言但要四川口音",
    "不用方言，不过要四川口音",
    "不用方言；带一点北京腔",
    "不用方言，英语旁白",
    "不使用方言，改用粤语",
    "不要普通话",
    "不是标准普通话",
    "不说国语，用青年男声",
    "不要用普通话",
    "拒绝Mandarin",
    "不用方言也不要普通话",
    "不能不使用方言",
    "不是不用方言",
    "不要避免方言",
    "不排斥四川口音",
    "没有必要避免方言",
    "方言要求不明确，请自由发挥",
    "不使用方言，也带一点口音",
    "不使用方言和英语，要粤语",
)


@pytest.mark.parametrize("description", ACCEPTED_DESCRIPTIONS)
def test_explicit_dialect_exclusion_preserves_description_and_passes_real_schema(
    description: str,
) -> None:
    padded = f"  {description}\n"
    assert require_mandarin_voice_design(padded) == description
    request = CreateDesignedVoiceVersionRequest(
        expected_profile_version=1, description=padded, language="zh-CN"
    )
    assert request.description == description


@pytest.mark.parametrize("description", REJECTED_DESCRIPTIONS)
def test_positive_conflicting_or_ambiguous_language_request_is_rejected(
    description: str,
) -> None:
    with pytest.raises(ContractError, match="请核对语言要求"):
        require_mandarin_voice_design(description)
    with pytest.raises(ValidationError, match="明确的标准普通话描述"):
        CreateDesignedVoiceVersionRequest(
            expected_profile_version=1, description=description, language="zh-CN"
        )


def test_conflict_error_identifies_the_conflicting_clause() -> None:
    with pytest.raises(ContractError, match="“要四川口音”"):
        require_mandarin_voice_design("自然青年声，不用方言但要四川口音")


@pytest.mark.parametrize("description", ["", "  ", "\n"])
def test_blank_description_is_still_rejected(description: str) -> None:
    with pytest.raises(ContractError):
        require_mandarin_voice_design(description)


@pytest.mark.parametrize("language", ["en", "ja-JP", "zh-HK", "yue-CN"])
def test_mandarin_description_does_not_relax_schema_language(language: str) -> None:
    with pytest.raises(ValidationError):
        CreateDesignedVoiceVersionRequest(
            expected_profile_version=1,
            description="自然普通话，不使用方言。",
            language=language,
        )
