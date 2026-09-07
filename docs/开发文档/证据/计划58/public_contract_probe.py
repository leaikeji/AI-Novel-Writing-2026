"""Run with the installed public AgentScope SDK and an in-process fake model.

No QwenPaw state/config is read, changed or installed; no Provider is called.
This proves SDK hooks only, not QwenPaw factory/transport integration.
"""
import asyncio
import json
import hashlib
import sys
from types import SimpleNamespace

from pydantic import BaseModel
from agentscope.agent import Agent
from agentscope.middleware import MiddlewareBase
from agentscope.model import ChatModelBase, ChatResponse
from agentscope.message import Msg, TextBlock, ToolCallBlock
from agentscope.tool import Toolkit, FunctionTool, ToolResponse


class Params(BaseModel):
    pass


async def project_adapter_probe():
    from backend.writing_skills.contracts import MethodBlock, SkillInjectionPacketV1, SkillInvocationPlanV1
    from backend.writing_skills.load_policy import (
        ManagedMethodPolicy, PublicLoadCapabilities, create_managed_method_middleware,
        managed_method_request,
    )
    block = MethodBlock(skill_id="prose-writing", path="SKILL.md", text="S58_REAL_ADAPTER",
                        sha256=hashlib.sha256(b"S58_REAL_ADAPTER").hexdigest())
    plan = SkillInvocationPlanV1(task="chapter_body", primary_skill="prose-writing", source_hash="a"*64,
                                catalog_version="b"*64, genre_state="excluded", mechanism_state="excluded")
    policy = ManagedMethodPolicy(SkillInjectionPacketV1(plan=plan, blocks=(block,), estimated_tokens=8))
    counts = []
    compression_counts = []
    checks = []
    async def authorize():
        checks.append("checked")
    class FakeStream(ChatModelBase):
        async def __call__(self, messages, tools=None, tool_choice=None, **kwargs):
            async def chunks():
                # Access happens after on_model_call returned the generator.
                counts.append(sum(b.text == "S58_REAL_ADAPTER" for m in messages for b in m.content if isinstance(b, TextBlock)))
                assert tools == [] and tool_choice is None
                yield ChatResponse(content=[TextBlock(text="stream-ok")], is_last=True)
            return chunks()
    ctx = SimpleNamespace(agent_id="ai-novel-writer", root_agent_id="ai-novel-writer", session_id="s58-sdk", request=None)
    with managed_method_request(
        policy,
        session_id="s58-sdk",
        entry="native",
        capabilities=PublicLoadCapabilities(True, True, True, True, True),
        verify_current=authorize,
    ) as binding:
        middleware = create_managed_method_middleware(ctx, None)
        agent = Agent(name="s58-real-adapter", system_prompt="test", model=FakeStream(
            credential=None, model="s58-no-network", parameters=Params(), stream=True, max_retries=0), middlewares=[middleware])
        await agent.reply(Msg(name="user", role="user", content=[TextBlock(text="first")]))

        compression_kwargs = {
            "messages": [Msg(
                name="history", role="user", content=[TextBlock(text="durable-history")]
            )],
            "tools": [{
                "type": "function", "function": {"name": "materialize_skill"}
            }],
            "tool_choice": object(),
        }

        async def compression_model():
            compression_counts.append(sum(
                b.text == "S58_REAL_ADAPTER"
                for message in compression_kwargs["messages"]
                for b in message.content
                if isinstance(b, TextBlock)
            ))
            assert compression_kwargs["tools"] == []
            assert compression_kwargs["tool_choice"] is None
            return "compressed"

        async def compress():
            assert await middleware.on_model_call(
                None, compression_kwargs, compression_model
            ) == "compressed"

        await middleware.on_compress_context(None, {}, compress)
        assert compression_kwargs["messages"][0].name == "history"
        assert compression_kwargs["tools"][0]["function"]["name"] == "materialize_skill"

        await agent.reply(Msg(name="user", role="user", content=[TextBlock(text="second")]))
    assert counts == [1, 1] and compression_counts == [0]
    assert len(checks) == 3 and not binding.active
    assert binding.observed_model_calls == 2
    assert binding.observed_compression_calls == 1
    return {"fake_stream_calls": len(counts), "packet_counts": counts,
            "compression_packet_counts": compression_counts,
            "writing_model_calls": binding.observed_model_calls,
            "compression_model_calls": binding.observed_compression_calls,
            "authorization_checks": len(checks), "expired_after_exit": not binding.active}


async def main():
    seen = []
    counts = {"fake_model": 0, "tool_io": 0, "intercepted": 0}

    class Fake(ChatModelBase):
        async def __call__(self, messages, tools=None, tool_choice=None, **kwargs):
            seen.append([b.text for m in messages for b in m.content if isinstance(b, TextBlock)])
            return ChatResponse(content=[TextBlock(text="probe-ok")], is_last=True)

    class Inject(MiddlewareBase):
        async def on_model_call(self, agent, input_kwargs, next_handler):
            input_kwargs["messages"] = [*input_kwargs["messages"], Msg(name="s58", role="system", content=[TextBlock(text="S58_CURRENT_ONLY")])]
            return await next_handler()

    agent = Agent(name="s58-probe", system_prompt="test", model=Fake(
        credential=None, model="s58-no-network", parameters=Params(), stream=False, max_retries=0), middlewares=[Inject()])
    for prompt in ("first", "second"):
        await agent.reply(Msg(name="user", role="user", content=[TextBlock(text=prompt)]))

    def loader():
        """Test-only method source that must never be read."""
        counts["tool_io"] += 1
        return ToolResponse(content=[TextBlock(text="FORBIDDEN_METHOD")])

    class ToolFake(ChatModelBase):
        async def __call__(self, messages, tools=None, tool_choice=None, **kwargs):
            counts["fake_model"] += 1
            content = ([ToolCallBlock(id="s58-tool", name="materialize_skill", input="{}", state="allowed")]
                       if counts["fake_model"] == 1 else [TextBlock(text="done")])
            return ChatResponse(content=content, is_last=True)

    class Deny(MiddlewareBase):
        async def on_acting(self, agent, input_kwargs, next_handler):
            counts["intercepted"] += 1
            yield ToolResponse(content=[TextBlock(text="denied")], state="denied")

    tool_agent = Agent(name="s58-tools", system_prompt="test", model=ToolFake(
        credential=None, model="s58-no-network", parameters=Params(), stream=False, max_retries=0),
        toolkit=Toolkit(tools=[FunctionTool(loader, name="materialize_skill", is_read_only=True)]), middlewares=[Deny()])
    result = await tool_agent.reply(Msg(name="user", role="user", content=[TextBlock(text="test")]))
    adapter = await project_adapter_probe() if len(sys.argv) > 1 else None
    print(json.dumps({"provider_calls": 0, "sdk_injection_calls": len(seen),
                      "packet_counts": [x.count("S58_CURRENT_ONLY") for x in seen],
                      "tool_probe": counts, "result_block_types": [b.type for b in result.content],
                      "project_adapter": adapter}))


if len(sys.argv) > 1:
    sys.path.insert(0, sys.argv[1])
asyncio.run(main())
