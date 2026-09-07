import hashlib
from uuid import UUID

import pytest

from backend.assistant_context import Msg, TextBlock
from backend.writing_skills.contracts import (
    MethodBlock,
    SkillInjectionPacketV1,
    SkillInvocationPlanV1,
)
from backend.writing_skills.load_policy import ManagedMethodPolicy, MethodPolicyViolation
from backend.writing_skills.middleware import NativePreparedAction, NativeWritingMethodMiddleware


def prepared(events: list[object]) -> NativePreparedAction:
    text = "冻结的小说正文方法"
    block = MethodBlock(
        skill_id="prose-writing",
        path="SKILL.md",
        text=text,
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )
    packet = SkillInjectionPacketV1(
        plan=SkillInvocationPlanV1(
            task="chapter_body",
            primary_skill="prose-writing",
            source_hash="a" * 64,
            catalog_version="b" * 64,
            genre_state="unresolved",
            mechanism_state="unresolved",
        ),
        blocks=(block,),
        estimated_tokens=20,
    )

    async def verify():
        events.append("verified")

    async def started():
        events.append("started")

    async def finished():
        events.append("finished")

    async def failed(uncertain: bool):
        events.append(("failed", uncertain))

    return NativePreparedAction(
        action_id=UUID("00000000-0000-4000-8000-000000000058"),
        policy=ManagedMethodPolicy(packet),
        verify_current=verify,
        mark_dispatch_started=started,
        mark_dispatched=finished,
        mark_failed=failed,
        route_data_text='【本轮路由资料；数据角色=user】{"genre":"悬疑"}',
    )


@pytest.mark.asyncio
async def test_native_compression_never_receives_method_then_writing_receives_once():
    events: list[object] = []

    async def prepare(_user_text: str):
        return prepared(events)

    middleware = NativeWritingMethodMiddleware(session_id="native-58", prepare=prepare)

    async def reply():
        compression_kwargs = {
            "messages": [Msg(name="user", role="user", content=[TextBlock(text="旧对话")])],
            "tools": [{"type": "function", "function": {"name": "read_file"}}],
            "tool_choice": object(),
        }

        async def compression_model():
            assert [message.name for message in compression_kwargs["messages"]] == ["user"]
            assert compression_kwargs["tools"] == []
            assert compression_kwargs["tool_choice"] is None
            events.append("compression")
            return "摘要"

        async def compress():
            assert await middleware.on_model_call(
                None, compression_kwargs, compression_model
            ) == "摘要"

        await middleware.on_compress_context(None, {}, compress)
        assert [message.name for message in compression_kwargs["messages"]] == ["user"]

        writing_kwargs = {
            "messages": [Msg(name="user", role="user", content=[TextBlock(text="当前请求")])],
            "tools": [],
        }

        async def writing_model():
            assert [message.name for message in writing_kwargs["messages"]] == [
                "user",
                "anw-writing-route-data",
                "anw-frozen-methods",
            ]
            events.append("writing")
            return "正文"

        assert await middleware.on_model_call(None, writing_kwargs, writing_model) == "正文"
        assert [message.name for message in writing_kwargs["messages"]] == ["user"]
        yield "正文"

    result = [event async for event in middleware.on_reply(
        None,
        {"inputs": "请续写《雾宅来信》，不要改变已经冻结的案件事实。"},
        reply,
    )]
    assert result == ["正文"]
    assert events == [
        "started",
        "verified",
        "compression",
        "verified",
        "writing",
        "finished",
    ]


@pytest.mark.asyncio
async def test_native_rejects_method_packet_already_retained_in_history():
    events: list[object] = []

    async def prepare(_user_text: str):
        return prepared(events)

    middleware = NativeWritingMethodMiddleware(session_id="native-58", prepare=prepare)

    async def reply():
        kwargs = {
            "messages": [Msg(name="anw-frozen-methods", role="system", content=[])],
            "tools": [],
        }

        async def never():
            pytest.fail("model must not run with retained method history")

        await middleware.on_model_call(None, kwargs, never)
        yield None

    with pytest.raises(MethodPolicyViolation, match="retained_in_history"):
        async for _ in middleware.on_reply(
            None,
            {"inputs": "续写《雾宅来信》"},
            reply,
        ):
            pass
    assert events == ["started", "verified", ("failed", False)]


@pytest.mark.asyncio
async def test_prepare_rejection_does_not_change_tools_or_messages():
    observed: dict[str, object] = {}

    async def prepare(user_text: str):
        assert user_text == "解释一下‘系统’这个普通词是什么意思。"
        return None

    middleware = NativeWritingMethodMiddleware(session_id="native-58", prepare=prepare)

    async def reply():
        kwargs = {
            "messages": [Msg(name="user", role="user", content=[TextBlock(text="原请求")])],
            "tools": [{"type": "function", "function": {"name": "ordinary_tool"}}],
        }

        async def model():
            observed.update(kwargs)
            return "普通回答"

        assert await middleware.on_model_call(None, kwargs, model) == "普通回答"
        yield "普通回答"

    result = [event async for event in middleware.on_reply(
        None,
        {"inputs": "解释一下‘系统’这个普通词是什么意思。"},
        reply,
    )]
    assert result == ["普通回答"]
    assert [message.name for message in observed["messages"]] == ["user"]
    assert observed["tools"] == [
        {"type": "function", "function": {"name": "ordinary_tool"}}
    ]
