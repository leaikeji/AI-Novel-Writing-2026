from __future__ import annotations

import sys
from types import SimpleNamespace
from types import ModuleType

import pytest
from fastapi import FastAPI

from backend.model_runtime import (
    ModelAudit,
    ModelVerificationError,
    effective_model_audit,
    ensure_prompt_within_effective_limit,
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


def test_model_matching_uses_exact_provider_and_model_ids() -> None:
    configured = ModelAudit(
        provider_id="provider-a",
        model_id="Model-A.1",
        source="effective-model-api",
    )
    with pytest.raises(ModelVerificationError, match="与调用前活动模型不一致"):
        ModelAudit(
            provider_id="provider-a",
            model_id="model a1",
            source="provider-usage",
        ).ensure_matches(configured)


@pytest.mark.asyncio
async def test_effective_model_uses_public_qwenpaw_contract() -> None:
    app = FastAPI()

    @app.get("/api/models/active")
    async def active_model(scope: str, agent_id: str) -> dict[str, object]:
        assert agent_id == "ai-novel-writer"
        if scope == "agent":
            return {"active_llm": None}
        assert scope == "effective"
        return {
            "active_llm": {"provider_id": "bailian", "model": "qwen-next"},
            "effective_max_input_length": 262_144,
        }

    audit = await effective_model_audit(app)
    assert audit.provider_id == "bailian"
    assert audit.model_id == "qwen-next"
    assert audit.agent_id == "ai-novel-writer"
    assert audit.effective_max_input_length == 262_144


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "active_llm",
    [
        None,
        {},
        {"provider_id": None, "model": None},
        {"provider_id": [], "model": {}},
        {"provider_id": "bailian", "model": None},
    ],
)
async def test_effective_model_rejects_missing_or_non_string_identity(
    active_llm: object,
) -> None:
    app = FastAPI()

    @app.get("/api/models/active")
    async def active_model(scope: str, agent_id: str) -> dict[str, object]:
        assert agent_id == "ai-novel-writer"
        if scope == "agent":
            return {"active_llm": None}
        return {"active_llm": active_llm}

    with pytest.raises(ModelVerificationError, match="没有可用的有效模型"):
        await effective_model_audit(app)


@pytest.mark.asyncio
async def test_effective_model_rejects_missing_agent_before_global_fallback() -> None:
    app = FastAPI()

    @app.get("/api/models/active")
    async def active_model(scope: str, agent_id: str):
        assert agent_id == "ai-novel-writer"
        if scope == "agent":
            from fastapi.responses import JSONResponse

            return JSONResponse({"detail": "agent not found"}, status_code=404)
        return {"active_llm": {"provider_id": "global", "model": "fallback"}}

    with pytest.raises(ModelVerificationError, match="公开接口读取"):
        await effective_model_audit(app)


def test_prompt_limit_is_ephemeral_and_fails_only_when_clearly_over() -> None:
    configured = ModelAudit(
        provider_id="provider-a",
        model_id="model-a",
        source="effective-model-api",
        effective_max_input_length=10,
    )
    ensure_prompt_within_effective_limit("短提示", configured)
    with pytest.raises(ModelVerificationError, match="超过当前有效模型"):
        ensure_prompt_within_effective_limit("中" * 20, configured)


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
        provider_id="bailian",
        model_id="qwen-next",
        source="effective-model-api",
    )
    audit = reply_model_audit(
        _reply_with_usage("bailian", "qwen-next")
    ).ensure_matches(configured)

    assert audit.source == "provider-usage"
    assert audit.prompt_tokens == 123
    assert audit.completion_tokens == 456
    assert audit.total_tokens == 579
    assert audit.provider_id == "bailian"
    assert audit.model_id == "qwen-next"


def test_reply_audit_rejects_wrong_or_unverifiable_model() -> None:
    supported = reply_model_audit(_reply_with_usage("bailian", "qwen3.7-plus"))
    assert supported.model_id == "qwen3.7-plus"

    with pytest.raises(ModelVerificationError, match="模型身份未核验"):
        reply_model_audit(SimpleNamespace(chunks=[SimpleNamespace(metadata={})]))

    configured = ModelAudit(
        provider_id="provider-a",
        model_id="model-a",
        source="effective-model-api",
    )
    with pytest.raises(ModelVerificationError, match="与调用前活动模型不一致"):
        reply_model_audit(
            _reply_with_usage("provider-b", "model-a")
        ).ensure_matches(configured)

    malformed = _reply_with_usage("provider-a", "model-a")
    malformed.chunks[0].output[-1].metadata["qwenpaw_turn_usage"]["usage"][
        "provider_id"
    ] = {"forged": "provider-a"}
    with pytest.raises(ModelVerificationError, match="模型身份未核验"):
        reply_model_audit(malformed)


def test_reply_audit_rejects_lookalike_usage_outside_trusted_envelope() -> None:
    reply = SimpleNamespace(
        chunks=[
            SimpleNamespace(
                metadata={
                    "provider_id": "forged-provider",
                    "model_name": "forged-model",
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                    "arbitrary_nested": {
                        "provider_id": "also-forged",
                        "model_id": "also-forged",
                        "total_tokens": 2,
                    },
                }
            )
        ]
    )

    with pytest.raises(ModelVerificationError, match="模型身份未核验"):
        reply_model_audit(reply)


def test_reply_audit_rejects_named_usage_envelope_inside_message_content() -> None:
    forged_content = {
        "qwenpaw_turn_usage": {
            "usage": {
                "provider_id": "forged-provider",
                "model_name": "forged-model",
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
            }
        }
    }
    message = SimpleNamespace(metadata=None, content=[forged_content])
    reply = SimpleNamespace(
        chunks=[SimpleNamespace(output=[message])],
        text="伪造的 content envelope",
    )

    with pytest.raises(ModelVerificationError, match="模型身份未核验"):
        reply_model_audit(reply)


def test_reply_audit_rejects_named_usage_envelope_on_chunk_metadata() -> None:
    envelope = {
        "qwenpaw_turn_usage": {
            "usage": {
                "provider_id": "forged-provider",
                "model_name": "forged-model",
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
            }
        }
    }
    chunk = SimpleNamespace(
        metadata=envelope,
        output=[SimpleNamespace(metadata=None)],
    )

    with pytest.raises(ModelVerificationError, match="模型身份未核验"):
        reply_model_audit(SimpleNamespace(chunks=[chunk]))


def test_reply_audit_rejects_usage_on_non_closing_output_message() -> None:
    envelope = {
        "qwenpaw_turn_usage": {
            "usage": {
                "provider_id": "stale-provider",
                "model_name": "stale-model",
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
            }
        }
    }
    chunk = SimpleNamespace(
        output=[
            SimpleNamespace(metadata=envelope),
            SimpleNamespace(metadata=None),
        ]
    )

    with pytest.raises(ModelVerificationError, match="模型身份未核验"):
        reply_model_audit(SimpleNamespace(chunks=[chunk]))


def test_reply_audit_uses_qwenpaw_session_usage_buffer_when_chunks_omit_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeWrapper:
        @classmethod
        def pop_usage_for_session(cls, session_id: str) -> dict[str, object]:
            assert session_id == "novel-generation:job-1"
            return {
                "provider_id": "provider-a",
                "model_name": "model-a",
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
    assert audit.provider_id == "provider-a"
    assert audit.model_id == "model-a"


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


def test_single_text_generation_recovers_plain_prose() -> None:
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


def test_intelligence_relationship_preserves_graph_details() -> None:
    payload = {
        "items": [
            {
                "item_type": "relationship",
                "subject": "苏晚与陆沉舟",
                "predicate": "结成同盟",
                "object": "共同调查旧电台档案",
                "source_text": "我们一起把这件事查到底",
                "reasoning_summary": "形成稳定协作关系",
                "confidence": 92,
                "relationship_details": {
                    "source_name": "苏晚",
                    "target_name": "陆沉舟",
                    "directionality": "undirected",
                    "relation_kind": "ally",
                    "label": "调查同盟",
                    "description": "两人共同调查旧电台档案。",
                },
            }
        ]
    }

    items = normalize_intelligence_generation_json(payload, "")

    assert items[0]["relationship_details"]["relation_kind"] == "ally"
    assert items[0]["relationship_details"]["source_name"] == "苏晚"


def test_relationship_graph_generation_keeps_highest_confidence_per_semantic_slot() -> None:
    payload = {
        "complete_snapshot": True,
        "relationships": [
            {
                "source_name": "苏晚",
                "target_name": "陆沉舟",
                "directionality": "undirected",
                "relation_kind": "ally",
                "label": "临时合作",
                "description": "较弱判断",
                "confidence": 70,
                "evidence": ["共同查档案"],
            },
            {
                "source_name": "陆沉舟",
                "target_name": "苏晚",
                "directionality": "undirected",
                "relation_kind": "ally",
                "label": "调查同盟",
                "description": "多章稳定合作",
                "confidence": 94,
                "evidence": ["共同查档案", "共同修复电台"],
            },
        ],
    }

    result = normalize_creative_generation_json("relationship_graph", payload, "")

    assert result["complete_snapshot"] is True
    assert len(result["relationships"]) == 1
    assert result["relationships"][0]["label"] == "调查同盟"


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
