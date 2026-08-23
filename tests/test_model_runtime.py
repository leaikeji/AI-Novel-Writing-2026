from __future__ import annotations

import sys
from types import SimpleNamespace
from types import ModuleType

import pytest

from backend.model_runtime import (
    ModelAudit,
    ModelVerificationError,
    is_minimax_m3,
    parse_model_json,
    reply_model_audit,
)


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
