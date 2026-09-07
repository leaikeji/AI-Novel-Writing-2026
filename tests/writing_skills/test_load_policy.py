import hashlib
from contextvars import copy_context
from types import SimpleNamespace

import pytest

from backend.writing_skills.contracts import MethodBlock, SkillInjectionPacketV1, SkillInvocationPlanV1
from backend.writing_skills.load_policy import (
    ManagedMethodPolicy, MethodPolicyViolation, PublicLoadCapabilities,
    create_managed_method_middleware, managed_method_request,
    semantic_routing_request,
)
from backend.assistant_context import Msg, TextBlock


def policy(tools=frozenset()):
    block = MethodBlock(skill_id="prose-writing", path="SKILL.md", text="generic", sha256=hashlib.sha256(b"generic").hexdigest())
    plan = SkillInvocationPlanV1(task="chapter_body", primary_skill="prose-writing", source_hash="a"*64, catalog_version="b"*64, genre_state="excluded", mechanism_state="excluded")
    return ManagedMethodPolicy(SkillInjectionPacketV1(plan=plan, blocks=(block,), estimated_tokens=2), tools)


@pytest.mark.parametrize("name", ["read_file", "materialize_skill", "execute_shell_command", "run_tool_batch", "spawn_subagent", "web_fetch", "future_loader"])
def test_alternative_load_paths_denied(name):
    with pytest.raises(MethodPolicyViolation):
        policy().authorize_tool(name)


def test_normal_novel_tools_preserve_existing_domain_path():
    policy(frozenset({"novel_get_context"})).authorize_tool("novel_get_context")
    with pytest.raises(MethodPolicyViolation):
        policy().authorize_tool("novel_prepare_selection_edit")


def test_duplicate_content_is_reused_without_returning_bytes():
    assert policy().reuse_block("prose-writing", "SKILL.md") is None
    with pytest.raises(MethodPolicyViolation):
        policy().reuse_block("suspense-writing", "SKILL.md")
    with pytest.raises(MethodPolicyViolation):
        policy().reuse_block("prose-writing", "references/genre-promises.md")


def test_capability_presence_is_not_a_passing_gate():
    with pytest.raises(MethodPolicyViolation):
        PublicLoadCapabilities(current_request_injection=True, pre_io_tool_control=True).require("button")
    verified = PublicLoadCapabilities(True, True, True)
    verified.require("button")
    with pytest.raises(MethodPolicyViolation):
        verified.require("native")


def test_product_chapter_gate_releases_only_the_verified_button_contract():
    from backend.writing_skills.button import CHAPTER_CAPABILITIES
    CHAPTER_CAPABILITIES.require("button")
    with pytest.raises(MethodPolicyViolation):
        CHAPTER_CAPABILITIES.require("native")


def test_policy_cannot_enable_arbitrary_tools():
    with pytest.raises(MethodPolicyViolation):
        policy(frozenset({"execute_shell_command"}))


async def authorized():
    pass


def context(agent="ai-novel-writer", session="s58"):
    return SimpleNamespace(agent_id=agent, session_id=session, root_agent_id=agent,
                           request=SimpleNamespace(agent_id=agent, session_id=session,
                                                   request_context={"managed_skill_dispatch": True}))


def managed(*, current=authorized, methods=None):
    return managed_method_request(methods or policy(), session_id="s58", entry="button",
                                  capabilities=PublicLoadCapabilities(True, True, True),
                                  verify_current=current)


def test_client_marker_cannot_construct_middleware():
    assert create_managed_method_middleware(context(), None) is None


def test_binding_checks_agent_session_and_duplicate_factory():
    with managed():
        assert create_managed_method_middleware(context(agent="default"), None) is None
        assert create_managed_method_middleware(context(session="other"), None) is None
        assert create_managed_method_middleware(context(), None) is not None
        with pytest.raises(MethodPolicyViolation):
            create_managed_method_middleware(context(), None)
        with pytest.raises(MethodPolicyViolation):
            with managed():
                pass


@pytest.mark.asyncio
async def test_injection_restores_original_kwargs_and_keeps_only_novel_tools():
    message = Msg(name="user", role="user", content=[TextBlock(text="author text")])
    kwargs = {"messages": [message], "tools": [
        {"type": "function", "function": {"name": "novel_get_context"}},
        {"type": "function", "function": {"name": "materialize_skill"}},
        {"type": "function", "function": {"name": "execute_shell_command"}},
    ], "tool_choice": {"type": "function", "function": {"name": "materialize_skill"}}}
    original = kwargs.copy()
    with managed(methods=policy(frozenset({"novel_get_context"}))) as binding:
        middleware = create_managed_method_middleware(context(), None)
        async def model():
            assert kwargs["messages"][-1].role == "system"
            assert kwargs["messages"][-1].content[-1].text == "generic"
            assert len(kwargs["messages"]) == 2
            assert kwargs["messages"][0] is message
            assert [t["function"]["name"] for t in kwargs["tools"]] == ["novel_get_context"]
            assert kwargs["tool_choice"] is None
            return "result"
        assert await middleware.on_model_call(None, kwargs, model) == "result"
        assert kwargs == original and kwargs["messages"] is original["messages"]
        assert binding.observed_model_calls == 1


@pytest.mark.asyncio
async def test_no_tools_uses_sdk_none_not_openai_wire_string():
    original_choice = object()
    kwargs = {"messages": [], "tools": [], "tool_choice": original_choice}
    with managed():
        middleware = create_managed_method_middleware(context(), None)
        async def sdk_model():
            assert kwargs["tools"] == []
            assert kwargs["tool_choice"] is None
            return "ok"
        assert await middleware.on_model_call(None, kwargs, sdk_model) == "ok"
    assert kwargs["tool_choice"] is original_choice


@pytest.mark.asyncio
async def test_authorization_failure_happens_before_model():
    async def revoked():
        raise PermissionError("scope revoked")
    async def never():
        pytest.fail("model executed")
    with managed(current=revoked) as binding:
        middleware = create_managed_method_middleware(context(), None)
        with pytest.raises(PermissionError):
            await middleware.on_model_call(None, {"messages": []}, never)
        assert binding.observed_model_calls == 0


@pytest.mark.asyncio
async def test_error_restores_kwargs_and_copied_context_cannot_outlive_request():
    kwargs = {"messages": []}
    with managed():
        copied = copy_context()
        middleware = create_managed_method_middleware(context(), None)
        async def failure():
            raise RuntimeError("fake network failure")
        with pytest.raises(RuntimeError):
            await middleware.on_model_call(None, kwargs, failure)
    assert kwargs == {"messages": []}
    assert copied.run(create_managed_method_middleware, context(), None) is None
    with pytest.raises(MethodPolicyViolation):
        await middleware.on_model_call(None, kwargs, failure)


@pytest.mark.asyncio
async def test_policy_stops_tool_io_even_if_model_forces_hidden_tool():
    with managed() as binding:
        middleware = create_managed_method_middleware(context(), None)
        async def never():
            pytest.fail("tool IO happened")
            yield None
        with pytest.raises(MethodPolicyViolation):
            async for _ in middleware.on_acting(None, {"tool_call": SimpleNamespace(name="run_tool_batch")}, never):
                pass
        assert binding.denied_tool_calls == 1


@pytest.mark.asyncio
async def test_allowed_novel_tool_is_not_reimplemented_or_blocked():
    with managed(methods=policy(frozenset({"novel_prepare_selection_edit"}))):
        middleware = create_managed_method_middleware(context(), None)
        async def original():
            yield "existing proposal result"
        events = [event async for event in middleware.on_acting(
            None, {"tool_call": SimpleNamespace(name="novel_prepare_selection_edit")}, original)]
        assert events == ["existing proposal result"]


@pytest.mark.asyncio
async def test_stale_method_history_is_not_silently_reused():
    with managed():
        middleware = create_managed_method_middleware(context(), None)
        async def never():
            pytest.fail("model executed")
        with pytest.raises(MethodPolicyViolation, match="retained_in_history"):
            await middleware.on_model_call(None, {"messages": [Msg(name="anw-frozen-methods", role="system", content=[])]}, never)


@pytest.mark.asyncio
async def test_context_compression_never_receives_or_retains_method_packet():
    compression_kwargs = {
        "messages": [
            Msg(name="user", role="user", content=[TextBlock(text="历史正文")]),
        ],
        "tools": [
            {"type": "function", "function": {"name": "materialize_skill"}},
        ],
        "tool_choice": {"type": "function", "function": {"name": "materialize_skill"}},
    }
    original = compression_kwargs.copy()
    with managed() as binding:
        middleware = create_managed_method_middleware(context(), None)

        async def compress_model():
            assert [message.name for message in compression_kwargs["messages"]] == ["user"]
            assert compression_kwargs["tools"] == []
            assert compression_kwargs["tool_choice"] is None
            return "summary"

        async def compress():
            assert await middleware.on_model_call(
                None, compression_kwargs, compress_model
            ) == "summary"

        await middleware.on_compress_context(
            None,
            {"context_config": object(), "instructions": None},
            compress,
        )
        assert compression_kwargs == original
        assert binding.observed_compression_calls == 1
        assert binding.observed_model_calls == 0

        writing_kwargs = {"messages": [], "tools": []}

        async def writing_model():
            assert writing_kwargs["messages"][-1].name == "anw-frozen-methods"
            return "chapter"

        assert await middleware.on_model_call(
            None, writing_kwargs, writing_model
        ) == "chapter"
        assert binding.observed_model_calls == 1


@pytest.mark.asyncio
async def test_compression_rejects_retained_method_and_recursive_entry():
    with managed():
        middleware = create_managed_method_middleware(context(), None)

        async def retained():
            async def never():
                pytest.fail("compression model executed")
            with pytest.raises(
                MethodPolicyViolation, match="retained_in_compression"
            ):
                await middleware.on_model_call(
                    None,
                    {"messages": [Msg(
                        name="anw-frozen-methods", role="system", content=[]
                    )]},
                    never,
                )

        await middleware.on_compress_context(None, {}, retained)

        async def recursive():
            with pytest.raises(
                MethodPolicyViolation, match="recursive_context_compression"
            ):
                await middleware.on_compress_context(
                    None, {}, lambda: pytest.fail("must not continue")
                )

        await middleware.on_compress_context(None, {}, recursive)


@pytest.mark.asyncio
async def test_semantic_binding_allows_one_model_round_and_zero_tools():
    kwargs = {
        "messages": [Msg(name="user", role="user", content=[TextBlock(text="route")])],
        "tools": [{"type": "function", "function": {"name": "novel_get_context"}}],
        "tool_choice": {"type": "function", "function": {"name": "novel_get_context"}},
    }
    original = kwargs.copy()
    with semantic_routing_request(
        session_id="semantic:s58",
        capabilities=PublicLoadCapabilities(True, True, True),
        verify_current=authorized,
    ) as binding:
        middleware = create_managed_method_middleware(
            context(session="semantic:s58"), None
        )

        async def model():
            assert kwargs["tools"] == []
            assert kwargs["tool_choice"] is None
            return "strict-json"

        assert await middleware.on_model_call(None, kwargs, model) == "strict-json"
        assert binding.observed_model_calls == 1
        assert kwargs == original
        with pytest.raises(MethodPolicyViolation, match="budget_exhausted"):
            await middleware.on_model_call(None, kwargs, model)


@pytest.mark.asyncio
async def test_semantic_binding_rejects_tool_acting_and_recursion():
    with semantic_routing_request(
        session_id="semantic:s58",
        capabilities=PublicLoadCapabilities(True, True, True),
        verify_current=authorized,
    ) as binding:
        middleware = create_managed_method_middleware(
            context(session="semantic:s58"), None
        )

        async def never():
            pytest.fail("tool IO happened")
            yield None

        with pytest.raises(MethodPolicyViolation, match="semantic_tool_not_allowed"):
            async for _ in middleware.on_acting(
                None, {"tool_call": SimpleNamespace(name="novel_get_context")}, never
            ):
                pass
        assert binding.denied_tool_calls == 1
        with pytest.raises(MethodPolicyViolation, match="recursive_semantic"):
            with semantic_routing_request(
                session_id="semantic:nested",
                capabilities=PublicLoadCapabilities(True, True, True),
                verify_current=authorized,
            ):
                pass
