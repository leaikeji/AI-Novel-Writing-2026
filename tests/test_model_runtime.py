from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from backend.model_runtime import (
    GENERATION_CONTRACT_VERSION,
    ModelAudit,
    ModelVerificationError,
    effective_model_audit,
    ensure_prompt_within_effective_limit,
    normalize_creative_generation_json,
    normalize_intelligence_generation_json,
    parse_model_json,
    reply_final_text,
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
    assert GENERATION_CONTRACT_VERSION == "follow-agent-effective-v6"
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
    snapshot = {
            "novel": {"title": "长篇小说"},
            "chapter": {
                "document_id": "chapter-4",
                "title": "第四章",
                "base_content_markdown": "旧稿内容。",
            },
            "brief": {
                "target_word_count": 2500,
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
                "minimum_visible_character_count": 2125,
                "maximum_visible_character_count": 2875,
                "target_visible_character_count": 2125,
                "requested_visible_character_count": 2500,
            },
            "previous_context": [
                {
                    "document_id": "chapter-4",
                    "title": "第四章",
                    "content_markdown": "旧稿内容。",
                }
            ],
            "story_facts": [],
            "private_assets": [],
        }
    prompt = build_chapter_generation_prompt(snapshot)

    assert "创作目标：约 2500 个中文可见字符" in prompt
    assert "验收范围：2125—2875 个中文可见字符" in prompt
    assert "按情节自然分段，不限定机械段数" in prompt
    assert "不得输出“我需要先加载”等内部工作语句" in prompt
    assert "内容禁区、角色限制和验收规则只用于约束创作，不是正文素材" in prompt
    assert "不得用“没有……”“不出现……”“不靠……”等作者说明" in prompt
    assert prompt.startswith("【AI小说世界2026 PawApp可信任务封套】")
    assert "kind=chapter_generation" in prompt
    assert "只做形成正文所必需的最少内部思考" in prompt
    assert "必须在本轮返回一次最终正文" in prompt
    assert "不得调用任何工具" in prompt
    assert "它不是本次最终答案" in prompt
    assert "不得原样返回旧稿" in prompt
    assert "本章之前的正文上下文（仅作连续性参考）" in prompt
    assert "contract=chapter-prose-candidate/v3" in prompt
    assert "【最终输出收束门】" in prompt
    assert "这是本轮首次生成" in prompt
    assert prompt.index("【最终输出收束门】") > prompt.index("来源、冲突和省略说明")

    retry_snapshot = dict(snapshot)
    retry_snapshot["length_control"] = {
        "schema_version": "chapter-length-control/1",
        "mode": "retry_feedback",
        "root_job_id": "job-first",
        "previous_job_id": "job-overlong",
        "retry_round": 2,
        "previous_validation_state": "above_target",
        "previous_visible_character_count": 3387,
        "required_adjustment_visible_character_count": 512,
        "calibrated_drafting_target_visible_character_count": 1475,
    }
    retry_prompt = build_chapter_generation_prompt(retry_snapshot)
    assert "上一次完整正文实际为 3387 个可见字符" in retry_prompt
    assert "本次至少减少 512 个可见字符" in retry_prompt
    assert "本轮先按约 1475 个可见字符的写作体量收束" in retry_prompt
    assert "最终完整正文仍必须落入 2125—2875 的硬范围" in retry_prompt
    assert "不要删除必要转折或截断结尾" in retry_prompt
    assert "job-overlong" not in retry_prompt


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


def test_reply_final_text_excludes_reasoning_and_prior_agent_turns() -> None:
    reply = SimpleNamespace(
        chunks=[
            SimpleNamespace(
                output=[
                    SimpleNamespace(
                        type="message",
                        role="assistant",
                        content=[
                            SimpleNamespace(type="reasoning", text="先分析人物动机。"),
                            SimpleNamespace(type="text", text="不应采用的中间轮。"),
                        ],
                    )
                ]
            ),
            SimpleNamespace(
                output=[
                    SimpleNamespace(
                        type="message",
                        role="assistant",
                        content=[
                            {"type": "thinking", "text": "静默检查字数。"},
                            {"type": "output_text", "text": "雨水沿着档案袋边缘滴下。"},
                        ],
                    )
                ]
            ),
        ],
        text="先分析人物动机。不应采用的中间轮。静默检查字数。雨水沿着档案袋边缘滴下。",
    )

    assert reply_final_text(reply) == "雨水沿着档案袋边缘滴下。"


def test_reply_final_text_rejects_reasoning_only_structured_reply() -> None:
    reply = SimpleNamespace(
        chunks=[
            SimpleNamespace(
                output=[
                    SimpleNamespace(
                        type="reasoning",
                        role="assistant",
                        content=[
                            {"type": "text", "text": "仍在思考。"},
                        ],
                    )
                ]
            )
        ],
        text="仍在思考。调用上下文工具。",
    )

    with pytest.raises(ModelVerificationError, match="没有返回独立的最终回答") as caught:
        reply_final_text(reply)

    diagnostic = str(caught.value)
    assert "reasoning/assistant[text:text=1:delta=0]" in diagnostic
    assert "仍在思考" not in diagnostic


def test_reply_final_text_skips_trailing_reasoning_after_final_message() -> None:
    reply = SimpleNamespace(
        chunks=[
            SimpleNamespace(
                output=[
                    SimpleNamespace(
                        type="message",
                        role="assistant",
                        content=[{"type": "text", "text": "最终正文。"}],
                    ),
                    SimpleNamespace(
                        type="reasoning",
                        role="assistant",
                        content=[{"type": "text", "text": "尾部自检。"}],
                    ),
                ]
            )
        ],
        text="最终正文。尾部自检。",
    )

    assert reply_final_text(reply) == "最终正文。"


def test_reply_final_text_uses_last_completed_standalone_message_when_response_empty() -> None:
    reply = SimpleNamespace(
        chunks=[
            SimpleNamespace(
                type="message",
                role="assistant",
                content=[{"type": "output_text", "text": "公开兼容路径正文。"}],
            ),
            SimpleNamespace(output=[]),
        ],
        text="公开兼容路径正文。",
    )

    assert reply_final_text(reply) == "公开兼容路径正文。"


def test_reply_final_text_does_not_skip_last_standalone_reasoning_message() -> None:
    reply = SimpleNamespace(
        chunks=[
            SimpleNamespace(
                type="message",
                role="assistant",
                content=[{"type": "text", "text": "更早的中间文本。"}],
            ),
            SimpleNamespace(
                type="reasoning",
                role="assistant",
                content=[{"type": "text", "text": "最后仍在思考。"}],
            ),
            SimpleNamespace(output=[]),
        ],
        text="更早的中间文本。最后仍在思考。",
    )

    with pytest.raises(ModelVerificationError, match="没有返回独立的最终回答"):
        reply_final_text(reply)


def test_reply_final_text_does_not_reuse_message_from_prior_response() -> None:
    reply = SimpleNamespace(
        chunks=[
            SimpleNamespace(
                output=[
                    SimpleNamespace(
                        type="message",
                        role="assistant",
                        content=[{"type": "text", "text": "先调用工具检查。"}],
                    )
                ]
            ),
            SimpleNamespace(
                output=[
                    SimpleNamespace(
                        type="reasoning",
                        role="assistant",
                        content=[{"type": "text", "text": "仍未形成最终回答。"}],
                    )
                ]
            ),
        ],
        text="先调用工具检查。仍未形成最终回答。",
    )

    with pytest.raises(ModelVerificationError, match="没有返回独立的最终回答"):
        reply_final_text(reply)


def test_reply_final_text_keeps_legacy_plain_reply_fallback() -> None:
    assert reply_final_text(SimpleNamespace(text="  最终正文  ")) == "最终正文"


def test_reply_audit_rejects_wrong_or_unverifiable_model() -> None:
    supported = reply_model_audit(_reply_with_usage("bailian", "qwen3.7-plus"))
    assert supported.model_id == "qwen3.7-plus"

    with pytest.raises(ModelVerificationError, match="公开回复未提供"):
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
    with pytest.raises(ModelVerificationError, match="公开回复未提供"):
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

    with pytest.raises(ModelVerificationError, match="公开回复未提供"):
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

    with pytest.raises(ModelVerificationError, match="公开回复未提供"):
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

    with pytest.raises(ModelVerificationError, match="公开回复未提供"):
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

    with pytest.raises(ModelVerificationError, match="公开回复未提供"):
        reply_model_audit(SimpleNamespace(chunks=[chunk]))


def test_reply_audit_never_uses_private_qwenpaw_session_usage_buffer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imported_modules: list[str] = []
    original_import = __import__

    def guarded_import(name: str, *args: object, **kwargs: object) -> object:
        imported_modules.append(name)
        if name.startswith("qwenpaw.token_usage"):
            raise AssertionError("private QwenPaw usage modules must not be imported")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", guarded_import)
    with pytest.raises(ModelVerificationError, match="公开回复未提供"):
        reply_model_audit(
            SimpleNamespace(chunks=[]),
            session_id="novel-generation:job-1",
        )
    assert not any(name.startswith("qwenpaw.token_usage") for name in imported_modules)


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


def test_outline_character_generation_normalizes_gender_without_name_guessing() -> None:
    recovered = normalize_creative_generation_json(
        "outline_characters",
        {
            "characters": [
                {
                    "name": "江述",
                    "role_type": "main",
                    "gender": "male",
                    "identity_summary": "刑侦科长",
                    "core_goal": "查清旧案证据被替换的原因",
                    "bio": "负责复核旧案原始物证。",
                    "details": {
                        "age": 37,
                        "personality": "重事实也重控制，压力下会把求真变成对他人的逼迫。",
                    },
                },
                {
                    "name": "林青瓷",
                    "role_type": "supporting",
                    "identity_summary": "省报记者",
                    "core_goal": "找到失踪证人的下落",
                    "bio": "长期追踪旧案中的证人保护记录。",
                    "details": {
                        "gender": "女性",
                        "personality": "外表冷静克制，涉及家人时会主动冒险并隐瞒代价。",
                    },
                },
                {
                    "name": "未定角色",
                    "role_type": "supporting",
                    "identity_summary": "身份尚未确定",
                    "core_goal": "确认自己是否应公开掌握的证据",
                    "bio": "身份和立场都仍待故事推进确认。",
                    "details": {
                        "gender": "unknown",
                        "personality": "习惯观察后行动，但身份未定使其选择仍保留弹性。",
                    },
                },
            ]
        },
        "",
    )

    assert [item["gender"] for item in recovered["characters"]] == [
        "男",
        "女",
        "未知",
    ]
    assert all(
        item["schema_version"] == "outline-character-draft/2"
        and item["origin"] == "ai_candidate"
        for item in recovered["characters"]
    )

    for invalid_gender in (None, "", "稍后再想想", 1):
        with pytest.raises(ModelVerificationError, match="性别字段"):
            normalize_creative_generation_json(
                "outline_characters",
                {
                    "characters": [
                        {
                            "name": "无有效性别",
                            "role_type": "main",
                            "identity_summary": "身份尚未确定",
                            "core_goal": "确认自己的公开身份",
                            "bio": "不能根据姓名猜测。",
                            "details": {
                                "gender": invalid_gender,
                                "personality": "会根据证据调整行动，不用姓名或身份替代判断。",
                            },
                        }
                    ]
                },
                "",
            )

    with pytest.raises(ModelVerificationError, match="互相冲突"):
        normalize_creative_generation_json(
            "outline_characters",
            {
                "characters": [
                    {
                        "name": "冲突角色",
                        "role_type": "main",
                        "gender": "男",
                        "identity_summary": "案件调查员",
                        "core_goal": "查明证据冲突",
                        "bio": "负责核对两份互相矛盾的证词。",
                        "details": {
                            "gender": "女",
                            "personality": "面对冲突先保护同伴，再追查事实并承担后果。",
                        },
                    }
                ]
            },
            "",
        )

    for invalid_personality in (None, "", "聪明、善良、冷酷", "太短"):
        with pytest.raises(ModelVerificationError, match="性格"):
            normalize_creative_generation_json(
                "outline_characters",
                {
                    "characters": [
                        {
                            "name": "性格无效角色",
                            "role_type": "supporting",
                            "identity_summary": "案件记录员",
                            "core_goal": "保持记录完整",
                            "bio": "性格必须可指导行动。",
                            "details": {
                                "gender": "未知",
                                "personality": invalid_personality,
                            },
                        }
                    ]
                },
                "",
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
        '{"fact_type":"general_fact","subject":"沈青禾","predicate":"重生",'
        '"object":"回到1992年","source_text":"她睁开眼",'
        '"reasoning_summary":"时间锚点","confidence":96},'
        '{"fact_type":"general_fact","subject":"沈佑平","predicate":"被处分",'
        '"object":"处分事由"扣留单据"","source_text":"处分公告",'
        '"reasoning_summary":"未转义引号使这一项无效"},'
        '{"fact_type":"storyline_event","entity_key":"storyline_1","subject":"沈青禾",'
        '"predicate":"启动调查","object":"列下三项计划",'
        '"source_text":"她写下三条线",'
        '"reasoning_summary":"主线启动","confidence":88}]}'
    )
    parsed = parse_model_json(malformed)
    assert parsed["subject"] == "沈青禾"

    items = normalize_intelligence_generation_json(parsed, malformed)

    assert [item["subject"] for item in items] == ["沈青禾", "沈青禾"]
    assert items[1]["fact_type"] == "storyline_event"


def test_intelligence_payload_rejects_empty_success() -> None:
    with pytest.raises(ModelVerificationError, match="未返回可用"):
        normalize_intelligence_generation_json({"items": []}, '{"items":[]}')


def test_intelligence_payload_accepts_explicit_no_changes() -> None:
    assert normalize_intelligence_generation_json(
        {"no_changes": True, "items": []},
        '{"no_changes":true,"items":[]}',
    ) == []


def test_intelligence_relationship_preserves_stable_entity_key() -> None:
    payload = {
        "items": [
            {
                "fact_type": "relationship_state",
                "entity_key": "relationship_1",
                "subject": "苏晚与陆沉舟",
                "predicate": "结成同盟",
                "object": "共同调查旧电台档案",
                "source_text": "我们一起把这件事查到底",
                "reasoning_summary": "形成稳定协作关系",
                "confidence": 92,
                "details": {},
            }
        ]
    }

    items = normalize_intelligence_generation_json(payload, "")

    assert items[0]["fact_type"] == "relationship_state"
    assert items[0]["entity_key"] == "relationship_1"


def test_intelligence_relationship_preserves_new_relationship_character_keys() -> None:
    payload = {
        "items": [
            {
                "fact_type": "relationship_state",
                "source_character_key": "character_1",
                "target_character_key": "character_2",
                "directionality": "undirected",
                "relation_kind": "ally",
                "relationship_label": "调查同盟",
                "subject": "苏晚与陆沉舟",
                "predicate": "结成同盟",
                "object": "共同调查旧电台档案",
                "source_text": "我们一起把这件事查到底",
                "reasoning_summary": "形成稳定协作关系",
                "confidence": 92,
                "details": {},
            }
        ]
    }

    items = normalize_intelligence_generation_json(payload, "")

    assert items[0]["entity_key"] == ""
    assert items[0]["source_character_key"] == "character_1"
    assert items[0]["target_character_key"] == "character_2"
    assert items[0]["directionality"] == "undirected"
    assert items[0]["relation_kind"] == "ally"
    assert items[0]["relationship_label"] == "调查同盟"


def test_intelligence_story_time_rejects_a_calendar_year_absent_from_evidence() -> None:
    payload = {
        "items": [
            {
                "fact_type": "story_time",
                "subject": "空播室案发",
                "predicate": "场景锚定在午夜零点",
                "object": "2000-01-01T00:00:00",
                "source_text": "零点零分，旧广播电台的频率忽然亮了一下。",
                "details": {
                    "transition": "anchor",
                    "to_time": "2000-01-01T00:00:00",
                },
                "reasoning_summary": "场景时间锚点",
                "confidence": 95,
            },
            {
                "fact_type": "general_fact",
                "subject": "空播室",
                "predicate": "频率异常激活",
                "object": "午夜零点出现旧节目女声",
                "source_text": "零点零分，旧广播电台的频率忽然亮了一下。",
                "reasoning_summary": "案件开端",
                "confidence": 90,
            },
        ]
    }

    items = normalize_intelligence_generation_json(payload, "")

    assert [item["fact_type"] for item in items] == ["general_fact"]


def test_relationship_graph_generation_keeps_highest_confidence_per_semantic_slot() -> None:
    payload = {
        "complete_snapshot": True,
        "relationships": [
            {
                "source_key": "character_a",
                "target_key": "character_b",
                "directionality": "undirected",
                "relation_kind": "ally",
                "label": "临时合作",
                "description": "较弱判断",
                "confidence": 70,
                "evidence": ["苏晚与陆沉舟共同查档案"],
            },
            {
                "source_key": "character_b",
                "target_key": "character_a",
                "directionality": "undirected",
                "relation_kind": "ally",
                "label": "调查同盟",
                "description": "多章稳定合作",
                "confidence": 94,
                "evidence": ["陆沉舟与苏晚共同查档案", "两人共同修复电台"],
            },
        ],
    }

    result = normalize_creative_generation_json("relationship_graph", payload, "")

    assert result["complete_snapshot"] is True
    assert len(result["relationships"]) == 1
    assert result["relationships"][0]["label"] == "调查同盟"


def test_relationship_graph_generation_rejects_nonempty_candidates_without_evidence() -> None:
    with pytest.raises(ModelVerificationError, match="没有可用关系"):
        normalize_creative_generation_json(
            "relationship_graph",
            {
                "complete_snapshot": True,
                "relationships": [
                    {
                        "source_key": "character_a",
                        "target_key": "character_b",
                        "directionality": "undirected",
                        "relation_kind": "ally",
                        "label": "调查同盟",
                        "confidence": 94,
                        "evidence": [],
                    }
                ],
            },
            "",
        )


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
