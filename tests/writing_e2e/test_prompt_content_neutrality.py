from backend.creative_services import build_creative_generation_prompt


def test_template_prompt_has_no_story_specific_keyword_routing() -> None:
    prompt = build_creative_generation_prompt(
        {
            "kind": "novel_template",
            "input_snapshot": {
                "audience": "成年读者",
                "creative_idea": "一段由旧物引发的关系与责任冲突",
            },
        }
    )

    assert "久别重逢和治愈故事优先" not in prompt
    assert "不得依赖单个题材关键词" in prompt
