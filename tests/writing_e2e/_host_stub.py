from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import importlib
import sys
from types import ModuleType, SimpleNamespace
from typing import Any


class FakeSession:
    """Narrow request-session stub; it never opens a database connection."""

    def __init__(self) -> None:
        self.rollback_count = 0

    def rollback(self) -> None:
        self.rollback_count += 1


def reply(*, text: str, provider_id: str | None, model_id: str | None) -> object:
    metadata: dict[str, object] | None = None
    if provider_id is not None and model_id is not None:
        metadata = {
            "qwenpaw_turn_usage": {
                "usage": {
                    "provider_id": provider_id,
                    "model_name": model_id,
                    "prompt_tokens": 11,
                    "completion_tokens": 17,
                    "total_tokens": 28,
                    "request_id": "stub-request-plan37",
                }
            }
        }
    message = SimpleNamespace(
        role="assistant",
        content=[SimpleNamespace(type="output_text", text=text)],
        metadata=metadata,
    )
    return SimpleNamespace(
        chunks=[SimpleNamespace(output=[message])],
        text=text,
    )


def import_creative_api(monkeypatch: Any):
    qwenpaw_module = ModuleType("qwenpaw")
    qwenpaw_module.__path__ = []  # type: ignore[attr-defined]
    pawapp_module = ModuleType("qwenpaw.pawapp")

    async def get_ctx() -> None:
        raise AssertionError("stub tests must not resolve a real PawApp context")

    pawapp_module.get_ctx = get_ctx
    qwenpaw_module.pawapp = pawapp_module
    monkeypatch.setitem(sys.modules, "qwenpaw", qwenpaw_module)
    monkeypatch.setitem(sys.modules, "qwenpaw.pawapp", pawapp_module)
    monkeypatch.delitem(sys.modules, "backend.generation_dependencies", raising=False)
    monkeypatch.delitem(sys.modules, "backend.creative_api", raising=False)
    return importlib.import_module("backend.creative_api")


def import_app(monkeypatch: Any):
    """Import the public app boundary with only QwenPaw's public shapes stubbed."""

    qwenpaw_module = ModuleType("qwenpaw")
    qwenpaw_module.__path__ = []  # type: ignore[attr-defined]
    pawapp_module = ModuleType("qwenpaw.pawapp")

    class PawApp:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.routers: list[object] = []

        def hook(self, *_args: object, **_kwargs: object):
            return lambda function: function

        def on_uninstall(self, function):
            return function

        def include_router(self, router: object) -> None:
            self.routers.append(router)

    async def get_ctx() -> None:
        raise AssertionError("stub tests must not resolve a real PawApp context")

    pawapp_module.PawApp = PawApp
    pawapp_module.get_ctx = get_ctx
    qwenpaw_module.pawapp = pawapp_module

    runtime_module = ModuleType("qwenpaw.runtime")
    runtime_module.__path__ = []  # type: ignore[attr-defined]
    hooks_module = ModuleType("qwenpaw.runtime.hooks")
    phases_module = ModuleType("qwenpaw.runtime.phases")

    class HookBase:
        pass

    @dataclass
    class HookResult:
        pass

    class Phase(str, Enum):
        PRE_EXECUTE = "pre_execute"

    hooks_module.HookBase = HookBase
    hooks_module.HookResult = HookResult
    phases_module.Phase = Phase

    modules = {
        "qwenpaw": qwenpaw_module,
        "qwenpaw.pawapp": pawapp_module,
        "qwenpaw.runtime": runtime_module,
        "qwenpaw.runtime.hooks": hooks_module,
        "qwenpaw.runtime.phases": phases_module,
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    for name in (
        "backend.app",
        "backend.creative_api",
        "backend.generation_dependencies",
    ):
        monkeypatch.delitem(sys.modules, name, raising=False)
    return importlib.import_module("backend.app")
