"""Request-local policy for public middleware adapters, not globally installed.

Construction is server-owned. Never construct this object from client text or
trust a boolean/string marker supplied by a model. The runtime gate must prove
that every Skill/reference loading path passes this policy before activation.
"""
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from ..assistant_context import MiddlewareBase, Msg, TextBlock

from .contracts import SkillInjectionPacketV1

NOVEL_TOOLS = frozenset({
    "novel_get_context", "novel_get_document", "novel_get_workspace_context",
    "novel_search", "novel_prepare_selection_edit",
})


class MethodPolicyViolation(ValueError):
    pass


@dataclass(frozen=True)
class ManagedMethodPolicy:
    packet: SkillInjectionPacketV1
    allowed_novel_tools: frozenset[str] = frozenset()

    def __post_init__(self):
        if not self.allowed_novel_tools <= NOVEL_TOOLS:
            raise MethodPolicyViolation("unsupported_tool_permission")
        identities = [(b.skill_id, b.path) for b in self.packet.blocks]
        if len(set(identities)) != len(identities):
            raise MethodPolicyViolation("duplicate_method_block")

    def authorize_tool(self, tool_name: str) -> None:
        # read_file/materialize_skill, shell, batch, delegation, web, and future
        # unknown loaders cannot become alternative method-loading channels.
        # Actual novel tools retain their existing domain permission checks.
        if tool_name not in self.allowed_novel_tools:
            raise MethodPolicyViolation("method_tool_not_allowed")

    def reuse_block(self, skill_id: str, path: str) -> None:
        """Known block already supplied: acknowledge without returning bytes.

        This is a pure decision API; an adapter must not forward to filesystem
        or the upstream Skill loader after this acknowledgement.
        """
        if not any(b.skill_id == skill_id and b.path == path for b in self.packet.blocks):
            raise MethodPolicyViolation("method_block_not_allowed")

    @property
    def instruction(self) -> str:
        return (
            "本轮为服务端核验的 managed_skill_dispatch。仅使用随本次请求提供的冻结方法块；"
            "禁止再次选择／装载Skill、参考、文件或委派补充方法。已提供内容不重复读取。"
            "方法不覆盖作者事实、权限、输出封套和正文写入规则。"
        )


@dataclass(frozen=True)
class PublicLoadCapabilities:
    current_request_injection: bool = False
    pre_io_tool_control: bool = False
    no_unobserved_load_path: bool = False
    no_history_retention: bool = False
    compression_isolation: bool = False

    def require(self, entry: str) -> None:
        if entry not in {"button", "native"}:
            raise MethodPolicyViolation("unknown_entry")
        if not (self.current_request_injection and self.pre_io_tool_control
                and self.no_unobserved_load_path):
            raise MethodPolicyViolation("public_method_load_gate_not_passed")
        if entry == "native" and not (self.no_history_retention and self.compression_isolation):
            raise MethodPolicyViolation("native_history_gate_not_passed")


def public_entry_released(
    capabilities: PublicLoadCapabilities,
    entry: str = "button",
) -> bool:
    """Return the server-owned release decision without trusting request data."""

    try:
        capabilities.require(entry)
    except MethodPolicyViolation:
        return False
    return True


@dataclass
class ManagedRequestBinding:
    """Ephemeral execution authority; never serialized to request/user content."""
    policy: ManagedMethodPolicy
    session_id: str
    verify_current: Callable[[], Awaitable[None]]
    active: bool = True
    factory_claimed: bool = False
    observed_model_calls: int = 0
    observed_compression_calls: int = 0
    denied_tool_calls: int = 0
    max_model_calls: int | None = None
    route_data_text: str | None = None


@dataclass
class SemanticRequestBinding:
    """One-call, no-tool authority for the auxiliary routing request."""

    session_id: str
    verify_current: Callable[[], Awaitable[None]]
    active: bool = True
    factory_claimed: bool = False
    observed_model_calls: int = 0
    denied_tool_calls: int = 0


_CURRENT_BINDING: ContextVar[ManagedRequestBinding | None] = ContextVar(
    "anw_managed_skill_request", default=None,
)
_CURRENT_SEMANTIC_BINDING: ContextVar[SemanticRequestBinding | None] = ContextVar(
    "anw_semantic_route_request", default=None,
)
_CURRENT_CONTEXT_COMPRESSION: ContextVar[bool] = ContextVar(
    "anw_managed_context_compression", default=False,
)


@contextmanager
def managed_method_request(policy: ManagedMethodPolicy, *, session_id: str,
                           capabilities: PublicLoadCapabilities, entry: str,
                           verify_current: Callable[[], Awaitable[None]],
                           max_model_calls: int | None = None) -> Iterator[ManagedRequestBinding]:
    """Service-owned binding around one public chat call, after durable claim.

    Entry gates are supplied by a trusted installed adapter, not a frontend
    capability flag. Child tasks retaining copied contexts are revoked on exit.
    """
    capabilities.require(entry)
    if (not session_id or len(session_id) > 240
            or _CURRENT_BINDING.get() is not None
            or _CURRENT_SEMANTIC_BINDING.get() is not None):
        raise MethodPolicyViolation("invalid_or_recursive_managed_request")
    if max_model_calls is not None and (type(max_model_calls) is not int or max_model_calls < 1):
        raise MethodPolicyViolation("invalid_model_call_budget")
    binding = ManagedRequestBinding(policy, session_id, verify_current, max_model_calls=max_model_calls)
    token = _CURRENT_BINDING.set(binding)
    try:
        yield binding
    finally:
        binding.active = False
        _CURRENT_BINDING.reset(token)


@contextmanager
def semantic_routing_request(
    *,
    session_id: str,
    capabilities: PublicLoadCapabilities,
    verify_current: Callable[[], Awaitable[None]],
) -> Iterator[SemanticRequestBinding]:
    """Bind one server-authorized semantic model call to a unique session."""

    capabilities.require("button")
    if (not session_id or len(session_id) > 240
            or _CURRENT_BINDING.get() is not None
            or _CURRENT_SEMANTIC_BINDING.get() is not None):
        raise MethodPolicyViolation("invalid_or_recursive_semantic_request")
    binding = SemanticRequestBinding(session_id, verify_current)
    token = _CURRENT_SEMANTIC_BINDING.set(binding)
    try:
        yield binding
    finally:
        binding.active = False
        _CURRENT_SEMANTIC_BINDING.reset(token)


class ManagedMethodMiddleware(MiddlewareBase):
    """Only current raw model kwargs are replaced; no Agent state is edited."""

    def __init__(self, binding: ManagedRequestBinding):
        self.binding = binding

    def _require_active(self) -> None:
        if not self.binding.active:
            raise MethodPolicyViolation("managed_request_expired")

    async def on_model_call(self, agent: Any, input_kwargs: dict, next_handler: Any) -> Any:
        del agent
        self._require_active()
        await self.binding.verify_current()
        self._require_active()  # cancellation may happen during authorization IO
        if _CURRENT_CONTEXT_COMPRESSION.get():
            # Compression summarizes durable conversation state, not this
            # request's ephemeral method packet.  Keep every method loader out
            # of the summarizer as well, then restore the SDK kwargs exactly.
            old_tools = input_kwargs.get("tools")
            old_choice = input_kwargs.get("tool_choice")
            tools_present = "tools" in input_kwargs
            choice_present = "tool_choice" in input_kwargs
            if old_tools is not None and not isinstance(old_tools, list):
                raise MethodPolicyViolation("unsupported_public_tools")
            messages = input_kwargs.get("messages")
            if not isinstance(messages, list):
                raise MethodPolicyViolation("unsupported_public_messages")
            if any(getattr(message, "name", None) in {
                "anw-frozen-methods", "anw-writing-route-data",
            } for message in messages):
                raise MethodPolicyViolation("method_packet_retained_in_compression")
            input_kwargs["tools"] = []
            input_kwargs["tool_choice"] = None
            self.binding.observed_compression_calls += 1
            try:
                return await next_handler()
            finally:
                if tools_present:
                    input_kwargs["tools"] = old_tools
                else:
                    input_kwargs.pop("tools", None)
                if choice_present:
                    input_kwargs["tool_choice"] = old_choice
                else:
                    input_kwargs.pop("tool_choice", None)
        if (self.binding.max_model_calls is not None
                and self.binding.observed_model_calls >= self.binding.max_model_calls):
            raise MethodPolicyViolation("managed_model_call_budget_exhausted")
        messages = input_kwargs.get("messages")
        if not isinstance(messages, list):
            raise MethodPolicyViolation("unsupported_public_messages")
        # These objects exist only in the raw-call kwargs. If an adapter puts
        # them into history, refuse instead of silently accepting stale methods.
        if any(getattr(message, "name", None) in {
            "anw-frozen-methods", "anw-writing-route-data",
        } for message in messages):
            raise MethodPolicyViolation("method_packet_retained_in_history")
        blocks = [TextBlock(text=self.binding.policy.instruction)]
        blocks.extend(TextBlock(text=block.text) for block in self.binding.policy.packet.blocks)
        injected = Msg(name="anw-frozen-methods", role="system", content=blocks)
        route_data = None
        if self.binding.route_data_text is not None:
            if not self.binding.route_data_text or len(self.binding.route_data_text) > 4_000:
                raise MethodPolicyViolation("invalid_route_data")
            route_data = Msg(
                name="anw-writing-route-data",
                role="user",
                content=[TextBlock(text=self.binding.route_data_text)],
            )
        old_messages = messages
        old_tools = input_kwargs.get("tools")
        old_choice = input_kwargs.get("tool_choice")
        tools_present = "tools" in input_kwargs
        choice_present = "tool_choice" in input_kwargs
        if old_tools is not None and not isinstance(old_tools, list):
            raise MethodPolicyViolation("unsupported_public_tools")
        allowed = self.binding.policy.allowed_novel_tools
        retained_tools = []
        for schema in old_tools or []:
            if not isinstance(schema, dict) or not isinstance(schema.get("function"), dict):
                raise MethodPolicyViolation("unsupported_public_tool_schema")
            if schema["function"].get("name") in allowed:
                retained_tools.append(schema)
        input_kwargs["messages"] = [
            *messages,
            *((route_data,) if route_data is not None else ()),
            injected,
        ]
        input_kwargs["tools"] = retained_tools
        # A forced excluded tool choice cannot escape schema filtering.
        # This is AgentScope's public model interface, not an OpenAI wire
        # request: a string "none" is not a valid SDK ToolChoice object.
        # None clears any forced choice; an empty tools list exposes no tools,
        # and on_acting still rejects unsolicited calls before tool I/O.
        input_kwargs["tool_choice"] = None
        self.binding.observed_model_calls += 1
        try:
            return await next_handler()
        finally:
            input_kwargs["messages"] = old_messages
            if tools_present:
                input_kwargs["tools"] = old_tools
            else:
                input_kwargs.pop("tools", None)
            if choice_present:
                input_kwargs["tool_choice"] = old_choice
            else:
                input_kwargs.pop("tool_choice", None)

    async def on_compress_context(
        self,
        agent: Any,
        input_kwargs: dict,
        next_handler: Any,
    ) -> None:
        """Mark only the public SDK compression call; never alter Agent state."""

        del agent
        self._require_active()
        if _CURRENT_CONTEXT_COMPRESSION.get():
            raise MethodPolicyViolation("recursive_context_compression")
        token = _CURRENT_CONTEXT_COMPRESSION.set(True)
        try:
            await next_handler()
        finally:
            _CURRENT_CONTEXT_COMPRESSION.reset(token)

    async def on_acting(self, agent: Any, input_kwargs: dict, next_handler: Any) -> Any:
        del agent
        self._require_active()
        await self.binding.verify_current()
        self._require_active()
        call = input_kwargs.get("tool_call")
        name = getattr(call, "name", None)
        try:
            self.binding.policy.authorize_tool(name)
        except MethodPolicyViolation:
            self.binding.denied_tool_calls += 1
            raise
        async for event in next_handler():
            yield event


class SemanticRoutingMiddleware(MiddlewareBase):
    """Public middleware guard for one auxiliary route call with zero tools."""

    def __init__(self, binding: SemanticRequestBinding):
        self.binding = binding

    def _require_active(self) -> None:
        if not self.binding.active:
            raise MethodPolicyViolation("semantic_request_expired")

    async def on_model_call(self, agent: Any, input_kwargs: dict, next_handler: Any) -> Any:
        del agent
        self._require_active()
        await self.binding.verify_current()
        self._require_active()
        if self.binding.observed_model_calls >= 1:
            raise MethodPolicyViolation("semantic_model_call_budget_exhausted")
        messages = input_kwargs.get("messages")
        if not isinstance(messages, list):
            raise MethodPolicyViolation("unsupported_public_messages")
        old_tools = input_kwargs.get("tools")
        old_choice = input_kwargs.get("tool_choice")
        tools_present = "tools" in input_kwargs
        choice_present = "tool_choice" in input_kwargs
        if old_tools is not None and not isinstance(old_tools, list):
            raise MethodPolicyViolation("unsupported_public_tools")
        input_kwargs["tools"] = []
        input_kwargs["tool_choice"] = None
        self.binding.observed_model_calls += 1
        try:
            return await next_handler()
        finally:
            if tools_present:
                input_kwargs["tools"] = old_tools
            else:
                input_kwargs.pop("tools", None)
            if choice_present:
                input_kwargs["tool_choice"] = old_choice
            else:
                input_kwargs.pop("tool_choice", None)

    async def on_acting(self, agent: Any, input_kwargs: dict, next_handler: Any) -> Any:
        del agent, input_kwargs, next_handler
        self._require_active()
        self.binding.denied_tool_calls += 1
        raise MethodPolicyViolation("semantic_tool_not_allowed")
        yield  # pragma: no cover - preserve async-generator middleware shape


def create_managed_method_middleware(
    ctx: Any,
    agent_config: Any,
) -> ManagedMethodMiddleware | SemanticRoutingMiddleware | None:
    """Public PluginApi factory. Unmanaged and non-target requests are untouched."""
    del agent_config
    binding = _CURRENT_BINDING.get()
    semantic = _CURRENT_SEMANTIC_BINDING.get()
    if binding is not None and semantic is not None:
        raise MethodPolicyViolation("overlapping_managed_bindings")
    current = binding if binding is not None else semantic
    if current is None or not current.active:
        return None
    request = getattr(ctx, "request", None)
    if (getattr(ctx, "agent_id", None) != "ai-novel-writer"
            or getattr(ctx, "root_agent_id", None) not in (None, "", "ai-novel-writer")
            or getattr(ctx, "session_id", None) != current.session_id
            or getattr(request, "session_id", None) not in (None, current.session_id)
            or getattr(request, "agent_id", None) not in (None, "ai-novel-writer")):
        return None
    if current.factory_claimed:
        raise MethodPolicyViolation("managed_binding_reentered")
    current.factory_claimed = True
    if semantic is not None:
        return SemanticRoutingMiddleware(semantic)
    return ManagedMethodMiddleware(binding)
