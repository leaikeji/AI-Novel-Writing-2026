import importlib
import sys
from dataclasses import dataclass
from types import ModuleType

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from starlette.requests import Request


def _import_generation_dependencies(monkeypatch):
    qwenpaw_module = ModuleType("qwenpaw")
    pawapp_module = ModuleType("qwenpaw.pawapp")

    async def get_ctx():
        raise AssertionError("FastAPI dependency should not execute in this unit test")

    pawapp_module.get_ctx = get_ctx
    qwenpaw_module.pawapp = pawapp_module
    monkeypatch.setitem(sys.modules, "qwenpaw", qwenpaw_module)
    monkeypatch.setitem(sys.modules, "qwenpaw.pawapp", pawapp_module)
    monkeypatch.delitem(sys.modules, "backend.generation_dependencies", raising=False)
    return importlib.import_module("backend.generation_dependencies")


@dataclass(frozen=True)
class _FakePawAppContext:
    agent_id: str
    session_id: str


@pytest.mark.asyncio
async def test_novel_generation_context_forces_agent_without_mutating_source(
    monkeypatch,
) -> None:
    dependencies = _import_generation_dependencies(monkeypatch)
    original = _FakePawAppContext(agent_id="default", session_id="session-1")

    result = await dependencies.get_novel_generation_ctx(original)

    assert result is not original
    assert result.agent_id == "ai-novel-writer"
    assert result.session_id == original.session_id
    assert original.agent_id == "default"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure_mode",
    ["public-api-error", "no-effective-model", "missing-agent"],
)
async def test_novel_effective_model_maps_unavailable_public_contract_to_503(
    monkeypatch,
    failure_mode: str,
) -> None:
    dependencies = _import_generation_dependencies(monkeypatch)
    app = FastAPI()

    @app.get("/api/models/active")
    async def active_model(scope: str, agent_id: str):
        assert agent_id == "ai-novel-writer"
        if scope == "agent":
            if failure_mode == "missing-agent":
                return JSONResponse({"detail": "not found"}, status_code=404)
            return {"active_llm": None}
        assert scope == "effective"
        if failure_mode == "public-api-error":
            return JSONResponse({"detail": "unavailable"}, status_code=503)
        return {"active_llm": None}

    request = Request(
        {
            "type": "http",
            "app": app,
            "method": "GET",
            "path": "/test",
            "headers": [],
        }
    )

    with pytest.raises(HTTPException) as captured:
        await dependencies.get_novel_effective_model(request)

    assert captured.value.status_code == 503
    assert captured.value.detail["type"] == "generation_model_unavailable"
