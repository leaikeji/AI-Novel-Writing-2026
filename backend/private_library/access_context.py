"""Released Plan 74 access boundary for private-library maintenance tools.

It reuses the existing context-ref registry and public ``on_reply`` boundary.
A page lease proves scope, not that the author authorized a mutation; the
maintenance service separately classifies the current author's instruction.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
from typing import Any
from uuid import UUID

from ..assistant_context import MiddlewareBase, TARGET_AGENT_ID
from ..assistant_context_registry import (
    AssistantContextRefRegistry, PRIVATE_LIBRARY_CONTEXT_SCHEMA,
)
from ..writing_skills.middleware import current_native_user_text


@dataclass(frozen=True)
class LibraryAccessEvidence:
    agent_id: str
    session_id: str = field(repr=False)
    request_id: UUID
    scope_kind: str
    novel_id: str | None = field(repr=False)
    context_revision: int
    expires_at: datetime
    author_text: str = field(repr=False)
    author_text_hash: str = field(repr=False)

    @property
    def write_authorized(self) -> bool:
        # A later maintenance command requires its own service-owned decision.
        return False


_CURRENT_ACCESS: ContextVar[LibraryAccessEvidence | None] = ContextVar(
    "plan74_library_access_evidence", default=None,
)


def current_library_access() -> LibraryAccessEvidence | None:
    return _CURRENT_ACCESS.get()


def _optional_runtime_identity(value: object) -> str | None:
    """Match the host's public context semantics for optional request fields."""

    return value.strip() if isinstance(value, str) and value.strip() else None


class LibraryAccessProbeMiddleware(MiddlewareBase):
    def __init__(self, *, session_id: str, request_id: UUID, scope_kind: str,
                 novel_id: str | None, revision: int, expires_at: datetime) -> None:
        self._scope = {
            "agent_id": TARGET_AGENT_ID, "session_id": session_id,
            "request_id": request_id, "scope_kind": scope_kind,
            "novel_id": novel_id, "context_revision": revision,
            "expires_at": expires_at,
        }
        # QwenPaw/AgentScope may execute tool bodies in an ``on_acting`` task
        # whose ContextVar context is distinct from the reply stream.  Keep
        # the immutable, request-local evidence on this per-request middleware
        # instance so ``on_acting`` can re-establish the same authority
        # boundary around the actual tool invocation.
        self._evidence: LibraryAccessEvidence | None = None

    async def on_reply(self, agent: Any, input_kwargs: dict[str, Any],
                       next_handler: Any) -> Any:
        del agent
        # This public boundary supplies the current turn, not stored history.
        # No snapshot fields are passed to the text extractor.
        text = current_native_user_text(input_kwargs.get("inputs"))
        evidence = None if text is None else LibraryAccessEvidence(
            **self._scope, author_text=text,
            author_text_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )
        self._evidence = evidence
        upstream = next_handler().__aiter__()
        try:
            while True:
                token = _CURRENT_ACCESS.set(self._evidence)
                try:
                    try:
                        event = await upstream.__anext__()
                    except StopAsyncIteration:
                        return
                finally:
                    _CURRENT_ACCESS.reset(token)
                yield event
        finally:
            self._evidence = None
            close = getattr(upstream, "aclose", None)
            if close is not None:
                await close()

    async def on_acting(self, agent: Any, input_kwargs: dict[str, Any],
                        next_handler: Any) -> Any:
        del agent, input_kwargs
        upstream = next_handler().__aiter__()
        try:
            while True:
                token = _CURRENT_ACCESS.set(self._evidence)
                try:
                    try:
                        event = await upstream.__anext__()
                    except StopAsyncIteration:
                        return
                finally:
                    _CURRENT_ACCESS.reset(token)
                yield event
        finally:
            close = getattr(upstream, "aclose", None)
            if close is not None:
                await close()


def create_library_access_probe(
    ctx: Any, agent_config: Any, *, registry: AssistantContextRefRegistry,
    probe_enabled: bool = False,
) -> LibraryAccessProbeMiddleware | None:
    """Build the shared access middleware, with an explicit release switch."""
    del agent_config
    if not probe_enabled:
        return None
    request = getattr(ctx, "request", None)
    session_id = getattr(ctx, "session_id", None)
    request_context = getattr(request, "request_context", None)
    request_session_id = _optional_runtime_identity(
        getattr(request, "session_id", None),
    )
    request_agent_id = _optional_runtime_identity(
        getattr(request, "agent_id", None),
    )
    if (
        getattr(ctx, "agent_id", None) != TARGET_AGENT_ID
        or getattr(ctx, "root_agent_id", None) not in (None, "", TARGET_AGENT_ID)
        or not isinstance(session_id, str) or not session_id.strip()
        or (
            request_session_id is not None
            and request_session_id != session_id
        )
        or (
            request_agent_id is not None
            and request_agent_id != TARGET_AGENT_ID
        )
        or not isinstance(request_context, Mapping)
    ):
        return None
    context_ref = request_context.get("context_ref")
    if not isinstance(context_ref, str):
        return None
    lease = registry.lease_for_runtime(
        context_ref, agent_id=TARGET_AGENT_ID, session_id=session_id,
    )
    snapshot = lease.snapshot if lease.accepted else None
    if snapshot is None or lease.writing_action_id is None or lease.expires_at is None:
        return None
    novel = snapshot.get("novel")
    if snapshot.get("schemaVersion") == PRIVATE_LIBRARY_CONTEXT_SCHEMA:
        if novel is None:
            scope_kind, novel_id = "library", None
        elif isinstance(novel, Mapping):
            novel_id = novel.get("id")
            if not isinstance(novel_id, str) or not novel_id.strip():
                return None
            scope_kind = "novel"
        else:
            return None
    elif snapshot.get("schemaVersion") == 2 and isinstance(novel, Mapping):
        novel_id = novel.get("id")
        if not isinstance(novel_id, str) or not novel_id.strip():
            return None
        scope_kind = "novel"
    else:
        # Creation drafts are NOT personal-library authorization.
        return None
    return LibraryAccessProbeMiddleware(
        session_id=session_id, request_id=lease.writing_action_id,
        scope_kind=scope_kind, novel_id=novel_id,
        revision=lease.context_revision or 0, expires_at=lease.expires_at,
    )


def create_released_library_access_middleware(
    ctx: Any,
    agent_config: Any,
) -> LibraryAccessProbeMiddleware | None:
    """Released public factory sharing the PawApp endpoint's opaque registry."""

    from ..assistant_api import assistant_context_registry

    return create_library_access_probe(
        ctx,
        agent_config,
        registry=assistant_context_registry,
        probe_enabled=True,
    )


__all__ = [
    "LibraryAccessEvidence",
    "LibraryAccessProbeMiddleware",
    "create_library_access_probe",
    "create_released_library_access_middleware",
    "current_library_access",
]
