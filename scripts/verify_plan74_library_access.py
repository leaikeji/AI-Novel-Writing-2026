"""Offline P0 probe. Exit 0 means LOCAL_PASS, never a real-host G1A pass.

Run from the repository root with .venv/bin/python. Uses synthetic in-memory
data only; no model, database, Docker, credentials or deployment is accessed.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from types import SimpleNamespace

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.assistant_context import TARGET_AGENT_ID
from backend.assistant_context_registry import (
    AssistantContextRefRegistry, ContextRefBinding, PRIVATE_LIBRARY_CONTEXT_SCHEMA,
)
from backend.private_library.access_context import (
    create_library_access_probe, current_library_access,
)


def sample_scope(*, session_id: str | None = "plan74-session") -> ContextRefBinding:
    return ContextRefBinding(
        owner_token="plan74_owner_0000000000001",
        tab_instance="plan74_tab_000000000000001",
        agent_id=TARGET_AGENT_ID, novel_id=None,
        session_id=session_id, private_library_id="personal",
    )


def sample_snapshot(now: datetime, *, session_id: str | None = "plan74-session") -> dict:
    value = {
        "schemaVersion": PRIVATE_LIBRARY_CONTEXT_SCHEMA,
        "contextRevision": 1, "capturedAt": now.isoformat(),
        "expiresAt": (now + timedelta(minutes=5)).isoformat(),
        "agentId": TARGET_AGENT_ID, "library": {"id": "personal"},
        "page": {"section": "private-library", "view": "library"},
    }
    if session_id is not None:
        value["sessionId"] = session_id
    return value


def runtime_context(ref: str, *, session_id: str = "plan74-session") -> SimpleNamespace:
    return SimpleNamespace(
        agent_id=TARGET_AGENT_ID, root_agent_id=TARGET_AGENT_ID,
        session_id=session_id,
        request=SimpleNamespace(
            agent_id=TARGET_AGENT_ID, session_id=session_id,
            request_context={"context_ref": ref},
        ),
    )


async def run_probe() -> dict:
    now = datetime.now(timezone.utc)
    registry = AssistantContextRefRegistry(clock=lambda: now)
    created = registry.create(binding=sample_scope(), snapshot=sample_snapshot(now))
    ctx = runtime_context(created.context_ref)
    disabled = create_library_access_probe(ctx, None, registry=registry) is None
    middleware = create_library_access_probe(ctx, None, registry=registry, probe_enabled=True)
    checks = {"unregistered_default_off": disabled, "library_scope_created": middleware is not None}
    if middleware is not None:
        observed = []

        async def downstream():
            observed.append(current_library_access())
            yield "synthetic-event"

        inputs = [{"role": "user", "content": [{"type": "text", "text": "收藏排水坡度"}]}]
        events = [event async for event in middleware.on_reply(None, {"inputs": inputs}, downstream)]
        evidence = observed[0]
        checks.update({
            "stream_preserved": events == ["synthetic-event"],
            "no_fake_novel": evidence is not None and evidence.novel_id is None,
            "current_author_input": evidence is not None and evidence.author_text == "收藏排水坡度",
            "page_scope_does_not_authorize_write": evidence is not None and not evidence.write_authorized,
            "scope_reset_after_stream": current_library_access() is None,
        })
    checks["cross_session_rejected"] = create_library_access_probe(
        runtime_context(created.context_ref, session_id="another-session"), None,
        registry=registry, probe_enabled=True,
    ) is None
    registry.clear()
    checks["restart_invalidates_ticket"] = create_library_access_probe(
        ctx, None, registry=registry, probe_enabled=True,
    ) is None
    return {
        "schema_version": "plan74-library-access-local-probe/1",
        "local_status": "LOCAL_PASS" if all(checks.values()) else "LOCAL_FAIL",
        "g1a_real_host_status": "NOT_RUN", "checks": checks,
        "model_calls": 0, "database_writes": 0,
        "remaining": ["public_http_and_browser_transport", "real_skill_and_tool_scope",
                      "explicit_command_authorization", "persistent_receipt_and_undo"],
    }


def main() -> int:
    result = asyncio.run(run_probe())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["local_status"] == "LOCAL_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
