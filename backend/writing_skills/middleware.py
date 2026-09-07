"""Public native-chat middleware core; production activation remains closed.

The adapter accepts only a server-owned preparation callback.  It observes the
current ``on_reply`` input, never conversation history or a client-declared
Skill id, and delegates the raw model/tool boundary to the same frozen method
policy used by managed buttons.  A production factory must still provide a
durable native action claim and public catalog revalidation before registering
this middleware.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from ..assistant_context import MiddlewareBase
from .load_policy import (
    ManagedMethodMiddleware,
    ManagedMethodPolicy,
    ManagedRequestBinding,
    MethodPolicyViolation,
)


MAX_NATIVE_USER_INPUT_CHARACTERS = 20_000


@dataclass(frozen=True)
class NativeTaskRoute:
    """A narrowly recognized author operation, not a genre/mechanism guess."""

    task: str
    intent: str
    primary_skill: str
    operation: str = ""


_SELECTION_OPERATIONS = (
    (("请润色", "润色"), "polish"),
    (("请改写", "改写"), "rewrite"),
    (("请扩写", "扩写"), "expand"),
    (("请缩写", "缩写"), "shorten"),
    (("请优化对白", "优化对白", "请修改对白", "修改对白"), "dialogue"),
    (("请审查", "审查", "请检查", "检查", "请评审", "评审"), "review"),
)
_REVIEW_PREFIXES = ("请审查", "审查", "请检查", "检查", "请评审", "评审")
_WRITE_PREFIXES = ("请续写", "续写", "请写", "写一", "创作", "请创作", "生成正文", "请生成正文")
_DESIGN_PREFIXES = ("请设计", "设计", "请规划", "规划", "请完善", "完善", "请补全", "补全")


def _starts_with_any(text: str, prefixes: tuple[str, ...]) -> bool:
    compact = text.lstrip(" \t\r\n，。；：:！!")
    return any(compact.startswith(prefix) for prefix in prefixes)


def native_task_route(snapshot: Mapping[str, object], user_text: str) -> NativeTaskRoute | None:
    """Recognize only explicit current-turn writing operations.

    The function deliberately ignores book titles, genre words, plot words and
    mechanism words.  Those are content, not task authority.  Ambiguous native
    chat stays on QwenPaw's original path instead of receiving writing methods.
    """

    page = snapshot.get("page")
    if not isinstance(page, Mapping):
        return None
    view = page.get("modal") or page.get("view")
    if not isinstance(view, str):
        return None
    has_selection = isinstance(snapshot.get("selection"), Mapping)
    if has_selection:
        for prefixes, operation in _SELECTION_OPERATIONS:
            if _starts_with_any(user_text, prefixes):
                return NativeTaskRoute(
                    task="selection_edit",
                    intent="review" if operation == "review" else "write",
                    primary_skill="style-review" if operation == "review" else "prose-writing",
                    operation=operation,
                )
    if _starts_with_any(user_text, _REVIEW_PREFIXES) and view in {
        "chapter-editor",
        "chapter-outline-editor",
        "novel-outline",
        "character-editor",
    }:
        return NativeTaskRoute(task="review", intent="review", primary_skill="style-review")
    if view == "chapter-editor" and _starts_with_any(user_text, _WRITE_PREFIXES):
        return NativeTaskRoute(task="chapter_body", intent="write", primary_skill="prose-writing")
    if view == "chapter-outline-editor" and (
        _starts_with_any(user_text, _WRITE_PREFIXES)
        or _starts_with_any(user_text, _DESIGN_PREFIXES)
    ):
        return NativeTaskRoute(task="chapter_outline", intent="fresh", primary_skill="chapter-outline")
    if view == "novel-outline" and _starts_with_any(user_text, _DESIGN_PREFIXES):
        return NativeTaskRoute(task="direction", intent="fresh", primary_skill="novel-direction")
    if view == "character-editor" and (
        _starts_with_any(user_text, _WRITE_PREFIXES)
        or _starts_with_any(user_text, _DESIGN_PREFIXES)
    ):
        return NativeTaskRoute(
            task="character_profile_completion",
            intent="write",
            primary_skill="character-craft",
        )
    return None


@dataclass(frozen=True)
class NativePreparedAction:
    """One already-claimed action supplied by the project domain service."""

    action_id: UUID
    policy: ManagedMethodPolicy
    verify_current: Callable[[], Awaitable[None]]
    mark_dispatch_started: Callable[[], Awaitable[None]]
    mark_dispatched: Callable[[], Awaitable[None]]
    mark_failed: Callable[[bool], Awaitable[None]]
    route_data_text: str | None = None


NativePrepare = Callable[[str], Awaitable[NativePreparedAction | None]]


def _block_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        text = value.get("text")
        return text if isinstance(text, str) else ""
    text = getattr(value, "text", None)
    return text if isinstance(text, str) else ""


def _message_text(value: object) -> str:
    if isinstance(value, str):
        return value
    role = value.get("role") if isinstance(value, Mapping) else getattr(value, "role", None)
    if role not in (None, "user"):
        return ""
    content = value.get("content") if isinstance(value, Mapping) else getattr(value, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, Sequence) and not isinstance(content, (str, bytes, bytearray)):
        return "".join(_block_text(block) for block in content)
    return ""


def current_native_user_text(inputs: object) -> str | None:
    """Return only the final current-turn user text, never stored history."""

    values = inputs if isinstance(inputs, list) else [inputs]
    candidates = [text.strip() for value in values if (text := _message_text(value)).strip()]
    if not candidates:
        return None
    result = candidates[-1]
    if len(result) > MAX_NATIVE_USER_INPUT_CHARACTERS:
        raise MethodPolicyViolation("native_user_input_too_large")
    return result


def create_native_writing_middleware(
    ctx: Any,
    agent_config: Any,
    *,
    released: bool = False,
    registry: Any | None = None,
    session_factory: Callable[[], Any] | None = None,
    model_probe_override: Callable[[], Awaitable[Any]] | None = None,
) -> "NativeWritingMethodMiddleware | None":
    """Build the native adapter from a leased server ticket.

    Production registration does not pass ``released=True`` while ``G-NATIVE``
    is blocked.  The keyword exists for isolated public-contract tests only;
    no request or model field can set it.
    """

    del agent_config
    if not released:
        return None
    request = getattr(ctx, "request", None)
    request_context = getattr(request, "request_context", None)
    session_id = getattr(ctx, "session_id", None)
    if (
        getattr(ctx, "agent_id", None) != "ai-novel-writer"
        or getattr(ctx, "root_agent_id", None) not in (None, "", "ai-novel-writer")
        or not isinstance(session_id, str)
        or not session_id
        or not isinstance(request_context, Mapping)
        or not isinstance(request_context.get("context_ref"), str)
    ):
        return None
    if registry is None:
        from ..assistant_api import assistant_context_registry

        registry = assistant_context_registry
    leased = registry.lease_for_runtime(
        request_context["context_ref"],
        agent_id="ai-novel-writer",
        session_id=session_id,
    )
    snapshot = leased.snapshot if leased.accepted else None
    if (
        snapshot is None
        or leased.writing_action_id is None
        or leased.runtime_app is None
        or leased.tab_instance is None
    ):
        return None
    if session_factory is None:
        from sqlalchemy.orm import sessionmaker
        from ..database import get_engine

        session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False)

    if model_probe_override is not None:
        model_probe = model_probe_override
    else:
        async def model_probe():
            from ..model_runtime import effective_model_audit
            from .native import NativeModelConfig

            audit = await effective_model_audit(
                leased.runtime_app,
                agent_id="ai-novel-writer",
            )
            return NativeModelConfig(
                provider_id=audit.provider_id,
                model_id=audit.model_id,
                effective_input_budget=audit.effective_max_input_length,
            )

    async def prepare(user_text: str) -> NativePreparedAction | None:
        from .native import prepare_native_action

        return await prepare_native_action(
            session_factory=session_factory,
            asgi_app=leased.runtime_app,
            action_id=leased.writing_action_id,
            tab_id=leased.tab_instance,
            session_id=session_id,
            snapshot=snapshot,
            user_text=user_text,
            model_probe=model_probe,
        )

    return NativeWritingMethodMiddleware(session_id=session_id, prepare=prepare)


def create_released_native_writing_middleware(
    ctx: Any,
    agent_config: Any,
) -> "NativeWritingMethodMiddleware | None":
    """Production factory for the deterministic novel-workbench branch.

    Release authority is server-owned by plugin registration. Requests cannot
    enable it, provide method bytes, or choose a Skill id. Semantic routing
    remains separately disabled by its own catalog capability gate.
    """

    return create_native_writing_middleware(ctx, agent_config, released=True)


class NativeWritingMethodMiddleware(MiddlewareBase):
    """Bind one current native send to one frozen method packet.

    ``prepare`` must claim the server-generated action before reading model or
    catalog configuration.  Returning ``None`` leaves ordinary chat untouched.
    This class intentionally cannot construct a packet or infer a genre.
    """

    def __init__(self, *, session_id: str, prepare: NativePrepare) -> None:
        if not session_id or len(session_id) > 240:
            raise MethodPolicyViolation("invalid_native_session")
        self._session_id = session_id
        self._prepare = prepare
        self._binding: ManagedRequestBinding | None = None
        self._delegate: ManagedMethodMiddleware | None = None
        self._used = False

    async def on_reply(
        self,
        agent: Any,
        input_kwargs: dict[str, Any],
        next_handler: Any,
    ) -> AsyncIterator[Any]:
        del agent
        if self._used:
            raise MethodPolicyViolation("native_send_reentered")
        self._used = True
        user_text = current_native_user_text(input_kwargs.get("inputs"))
        if user_text is None:
            async for event in next_handler():
                yield event
            return

        prepared = await self._prepare(user_text)
        if prepared is None:
            async for event in next_handler():
                yield event
            return

        binding = ManagedRequestBinding(
            policy=prepared.policy,
            session_id=self._session_id,
            verify_current=prepared.verify_current,
            active=True,
            factory_claimed=True,
            max_model_calls=1,
            route_data_text=prepared.route_data_text,
        )
        self._binding = binding
        self._delegate = ManagedMethodMiddleware(binding)
        started = False
        try:
            await prepared.mark_dispatch_started()
            started = True
            async for event in next_handler():
                yield event
            if binding.observed_model_calls != 1:
                raise MethodPolicyViolation("native_model_call_not_observed_once")
            await prepared.mark_dispatched()
        except BaseException:
            if started:
                try:
                    await prepared.mark_failed(binding.observed_model_calls > 0)
                except BaseException:
                    # Preserve the actual request/model failure. A secondary
                    # evidence-write failure must not replace what the author
                    # and host need to diagnose from the native request.
                    pass
            raise
        finally:
            binding.active = False

    async def on_model_call(
        self,
        agent: Any,
        input_kwargs: dict[str, Any],
        next_handler: Any,
    ) -> Any:
        if self._delegate is None:
            return await next_handler()
        return await self._delegate.on_model_call(agent, input_kwargs, next_handler)

    async def on_compress_context(
        self,
        agent: Any,
        input_kwargs: dict[str, Any],
        next_handler: Any,
    ) -> None:
        if self._delegate is None:
            await next_handler()
            return
        await self._delegate.on_compress_context(agent, input_kwargs, next_handler)

    async def on_acting(
        self,
        agent: Any,
        input_kwargs: dict[str, Any],
        next_handler: Any,
    ) -> AsyncIterator[Any]:
        if self._delegate is None:
            async for event in next_handler():
                yield event
            return
        async for event in self._delegate.on_acting(agent, input_kwargs, next_handler):
            yield event


__all__ = [
    "MAX_NATIVE_USER_INPUT_CHARACTERS",
    "NativePreparedAction",
    "NativeTaskRoute",
    "NativeWritingMethodMiddleware",
    "create_native_writing_middleware",
    "create_released_native_writing_middleware",
    "current_native_user_text",
    "native_task_route",
]
