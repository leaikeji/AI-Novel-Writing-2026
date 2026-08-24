from __future__ import annotations

import sys
from types import SimpleNamespace
from types import ModuleType

import pytest

from backend.model_runtime import (
    ModelAudit,
    ModelVerificationError,
    is_minimax_m3,
    normalize_creative_generation_json,
    normalize_intelligence_generation_json,
    parse_model_json,
    reply_model_audit,
)
from backend.services import build_chapter_generation_prompt


def _reply_with_usage(provider_id: str, model_name: str) -> SimpleNamespace:
    closing_message = SimpleNamespace(
        metadata={
            "qwenpaw_turn_usage": {
                "usage": {
                    "provider_id": provider_id,
                    "model_name": model_name,
                    "prompt_tokens": 123,
                    "completion_tokens": 456,
                    "total_tokens": 579,
                }
            }
        },
        content=[],
    )
    final_response = SimpleNamespace(output=[closing_message], metadata=None)
    return SimpleNamespace(chunks=[final_response], text="完成")


def test_minimax_m3_matching_is_exact() -> None:
    assert is_minimax_m3("MiniMax-M3")
    assert is_minimax_m3("minimax m3")
    assert not is_minimax_m3("MiniMax-M2.7")
    assert not is_minimax_m3("MiniMax-M30")
    assert not is_minimax_m3("qwen3.7-plus")


def test_chapter_prompt_enforces_current_acceptance_window() -> None:
    prompt = build_chapter_generation_prompt(
        {
            "novel": {"title": "长篇小说"},
            "chapter": {"title": "第四章", "base_content_markdown": ""},
            "brief": {
                "target_word_count": 5000,
                "expectation_text": "推进防汛主线",
                "outline_text": "人物核对值班表。",
                "forbidden_text": "",
                "role_constraints": {
                    "required": [],
                    "allowed": [],
                    "context_only": [],
                    "forbidden": [],
                },
            },
            "acceptance": {
                "minimum_visible_character_count": 1000,
                "maximum_visible_character_count": 1500,
                "target_visible_character_count": 1000,
                "requested_visible_character_count": 1250,
            },
            "previous_context": [],
            "story_facts": [],
            "private_assets": [],
        }
    )

    assert "创作目标：约 1250 个中文可见字符" in prompt
    assert "验收范围：1000—1500 个中文可见字符" in prompt
    assert "固定输出 6 个自然段" in prompt
    assert "不得输出“我需要先加载”等内部工作语句" in prompt
    assert "内容禁区、角色限制和验收规则只用于约束创作，不是正文素材" in prompt
    assert "不得用“没有……”“不出现……”“不靠……”等作者说明" in prompt


def test_reply_audit_reads_actual_provider_usage_metadata() -> None:
    configured = ModelAudit(
        provider_id="minimax-cn",
        model_id="MiniMax-M3",
        source="agent-config",
    )
    audit = reply_model_audit(
        _reply_with_usage("minimax-cn", "MiniMax-M3")
    ).ensure_matches(configured)

    assert audit.source == "provider-usage"
    assert audit.prompt_tokens == 123
    assert audit.completion_tokens == 456
    assert audit.total_tokens == 579
    assert "minimax-cn:MiniMax-M3" in audit.fingerprint


def test_reply_audit_rejects_wrong_or_unverifiable_model() -> None:
    with pytest.raises(ModelVerificationError, match="不是 MiniMax M3"):
        reply_model_audit(_reply_with_usage("bailian", "qwen3.7-plus"))

    with pytest.raises(ModelVerificationError, match="缺少实际 provider/model"):
        reply_model_audit(SimpleNamespace(chunks=[SimpleNamespace(metadata={})]))

    configured = ModelAudit(
        provider_id="minimax-cn",
        model_id="MiniMax-M3",
        source="agent-config",
    )
    with pytest.raises(ModelVerificationError, match="与调用前活动模型不一致"):
        reply_model_audit(
            _reply_with_usage("minimax", "MiniMax-M3")
        ).ensure_matches(configured)


def test_reply_audit_uses_qwenpaw_session_usage_buffer_when_chunks_omit_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeWrapper:
        @classmethod
        def pop_usage_for_session(cls, session_id: str) -> dict[str, object]:
            assert session_id == "novel-generation:job-1"
            return {
                "provider_id": "minimax-cn",
                "model_name": "MiniMax-M3",
                "prompt_tokens": 321,
                "completion_tokens": 654,
                "total_tokens": 975,
            }

    qwenpaw_module = ModuleType("qwenpaw")
    token_usage_module = ModuleType("qwenpaw.token_usage")
    model_wrapper_module = ModuleType("qwenpaw.token_usage.model_wrapper")
    model_wrapper_module.TokenRecordingModelWrapper = FakeWrapper
    monkeypatch.setitem(sys.modules, "qwenpaw", qwenpaw_module)
    monkeypatch.setitem(sys.modules, "qwenpaw.token_usage", token_usage_module)
    monkeypatch.setitem(
        sys.modules,
        "qwenpaw.token_usage.model_wrapper",
        model_wrapper_module,
    )

    audit = reply_model_audit(
        SimpleNamespace(chunks=[]),
        session_id="novel-generation:job-1",
    )
    assert audit.source == "provider-usage-buffer"
    assert audit.provider_id == "minimax-cn"
    assert audit.model_id == "MiniMax-M3"


def test_model_json_parser_accepts_fenced_or_embedded_objects() -> None:
    assert parse_model_json('```json\n{"titles":["甲"]}\n```') == {
        "titles": ["甲"]
    }
    assert parse_model_json('前缀说明 {"outline_text":"章纲"} 后缀') == {
        "outline_text": "章纲"
    }
    with pytest.raises(ModelVerificationError, match="可解析的 JSON"):
        parse_model_json("没有结构化结果")


def test_model_json_parser_repairs_missing_character_item_boundary() -> None:
    malformed = (
        '{"characters":['
        '{"name":"甲","role_type":"main","details":{"age":"17"},'
        '{"name":"乙","role_type":"supporting","details":{"age":"18"}}]}'
    )
    payload = parse_model_json(malformed)
    assert [item["name"] for item in payload["characters"]] == ["甲", "乙"]


def test_single_text_generation_recovers_plain_minimax_prose() -> None:
    recovered = normalize_creative_generation_json(
        "outline_highlight",
        {},
        "旧电台连接两代人的秘密，久别重逢的恋人在台风夜重新听见彼此。",
    )
    assert recovered == {
        "highlight_text": "旧电台连接两代人的秘密，久别重逢的恋人在台风夜重新听见彼此。"
    }


def test_outline_plot_recovers_complete_prose_after_unescaped_quote() -> None:
    body = (
        "第一章，苏晚回到澄屿，在阁楼发现未寄出的录音。"
        "她听见外婆说“别让潮声替你沉默”，决定留下修复电台。"
        + "陆沉舟协助她查清旧录音、共同面对台风与当年的误会。" * 45
    )
    recovered = normalize_creative_generation_json(
        "outline_plot",
        {"plot_text": "第一章，苏晚回到澄屿，在阁楼发现未寄出的录音。她听见外婆说"},
        f'{{"plot_text":"{body}"}}\n\n⟦ 状态：完成；下一步：逐章创作 ⟧',
    )
    assert recovered == {"plot_text": body}


def test_outline_plot_rejects_silently_truncated_fragment() -> None:
    with pytest.raises(ModelVerificationError, match="故事情节结果过短"):
        normalize_creative_generation_json(
            "outline_plot",
            {"plot_text": "第一章刚刚开始，模型输出便被错误截断。"},
            '{"plot_text":"第一章刚刚开始，模型输出便被错误截断。"}',
        )


def test_outline_background_is_kept_at_source_like_length() -> None:
    recovered = normalize_creative_generation_json(
        "outline_background",
        {"background_text": "澄屿临海。" + "海风吹过旧电台与灯塔，未寄出的录音等待被听见。" * 20},
        "",
    )
    assert 80 <= len(recovered["background_text"]) <= 220
    assert recovered["background_text"].endswith("。")


def test_structured_generation_rejects_missing_required_fields() -> None:
    with pytest.raises(ModelVerificationError, match="章纲结果结构不完整"):
        normalize_creative_generation_json(
            "chapter_outline",
            {"title": "旧车站来信"},
            '{"title":"旧车站来信"}',
        )

    with pytest.raises(ModelVerificationError, match="角色结果结构不完整"):
        normalize_creative_generation_json(
            "outline_characters",
            {"characters": []},
            '{"characters":[]}',
        )


def test_novel_template_generation_normalizes_editable_fields() -> None:
    recovered = normalize_creative_generation_json(
        "novel_template",
        {
            "genre": "现实",
            "template_key": "real-life",
            "template_name": "现实生活",
            "template_fields": ["模型返回的字段顺序会被规范化"],
            "template_data": {
                "protagonist_identity": "电台修复师与灯塔工程师",
                "background_setting": "东南沿海小城澄屿",
                "core_conflict": "隐藏录音与当年误会",
                "emotional_mainline": "双向暗恋久别重逢",
                "style_features": "克制细腻、治愈圆满",
            },
        },
        "",
    )

    assert recovered["template_fields"] == [
        "protagonist_identity",
        "background_setting",
        "core_conflict",
        "emotional_mainline",
        "style_features",
    ]
    assert recovered["template_data"]["core_conflict"] == "隐藏录音与当年误会"


def test_intelligence_payload_recovers_valid_items_from_malformed_envelope() -> None:
    malformed = (
        '{"items":['
        '{"item_type":"fact","subject":"沈青禾","predicate":"重生",'
        '"object":"回到1992年","source_text":"她睁开眼",'
        '"reasoning_summary":"时间锚点","confidence":96},'
        '{"item_type":"fact","subject":"沈佑平","predicate":"被处分",'
        '"object":"处分事由"扣留单据"","source_text":"处分公告",'
        '"reasoning_summary":"未转义引号使这一项无效"},'
        '{"item_type":"storyline_event","subject":"沈青禾",'
        '"predicate":"启动调查","object":"列下三项计划",'
        '"source_text":"她写下三条线",'
        '"reasoning_summary":"主线启动","confidence":88}]}'
    )
    parsed = parse_model_json(malformed)
    assert parsed["subject"] == "沈青禾"

    items = normalize_intelligence_generation_json(parsed, malformed)

    assert [item["subject"] for item in items] == ["沈青禾", "沈青禾"]
    assert items[1]["item_type"] == "storyline_event"


def test_intelligence_payload_rejects_empty_success() -> None:
    with pytest.raises(ModelVerificationError, match="未返回可用"):
        normalize_intelligence_generation_json({"items": []}, '{"items":[]}')


def test_review_payload_recovers_envelope_and_valid_embedded_issues() -> None:
    malformed = (
        '{"passed":false,"summary":"发现两处连续性问题","issues":['
        '{"severity":"P0","type":"时间矛盾","evidence":"周三锁门",'
        '"suggestion":"改为周五"},'
        '{"severity":"P1","type":"坏对象","evidence":"缺少结尾",'
        "'suggestion':'补齐'},"
        '{"severity":"P2","type":"重复描写","evidence":"连续两次愣住",'
        '"suggestion":"删去一次"}]}'
    )
    parsed = parse_model_json(malformed)
    assert parsed["type"] == "时间矛盾"

    recovered = normalize_creative_generation_json("review", parsed, malformed)

    assert recovered["passed"] is False
    assert recovered["summary"] == "发现两处连续性问题"
    assert [issue["type"] for issue in recovered["issues"]] == [
        "时间矛盾",
        "重复描写",
    ]


def test_review_payload_rejects_incomplete_negative_report() -> None:
    with pytest.raises(ModelVerificationError, match="结构不完整"):
        normalize_creative_generation_json(
            "review",
            {"passed": False, "summary": "发现问题", "issues": []},
            '{"passed":false,"summary":"发现问题","issues":[]}',
        )
