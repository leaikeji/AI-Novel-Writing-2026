"""Run one real Plan 74 assistant-maintenance turn through public HTTP APIs.

The script creates a short-lived, server-validated private-library context
reference and sends one author command to the existing ``ai-novel-writer``
Agent.  It never accepts or prints provider credentials and never exposes the
opaque context reference; all mutations still go through the released Skill,
tools and domain services.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any
from urllib.request import Request, urlopen
from uuid import uuid4


def _post_json(url: str, payload: dict[str, Any], *, timeout: float) -> Any:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - local URL
        return json.load(response)


def _tool_markers(value: object) -> int:
    if isinstance(value, list):
        return sum(_tool_markers(item) for item in value)
    if not isinstance(value, dict):
        return 0
    result = 0
    discriminator = value.get("type") or value.get("object")
    if isinstance(discriminator, str) and "tool" in discriminator.lower():
        result += 1
    for key, item in value.items():
        if "tool_call" in str(key).lower() and item not in (None, [], {}):
            result += 1
        result += _tool_markers(item)
    return result


def _chat(
    base_url: str,
    *,
    prompt: str,
    session_id: str,
    context_ref: str,
) -> dict[str, Any]:
    payload = {
        "input": [{
            "role": "user",
            "content": [{"type": "text", "text": prompt}],
        }],
        "session_id": session_id,
        "user_id": "plan74-formal-author",
        "channel": "console",
        "request_context": {"context_ref": context_ref},
    }
    request = Request(
        base_url.rstrip("/") + "/api/console/chat",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Agent-Id": "ai-novel-writer",
        },
        method="POST",
    )
    events: list[dict[str, Any]] = []
    with urlopen(request, timeout=240) as response:  # noqa: S310 - local URL
        for raw in response:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data: "):
                continue
            try:
                event = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)

    texts: list[str] = []
    errors: list[str] = []
    usage: dict[str, Any] = {}
    for event in events:
        if isinstance(event.get("usage"), dict):
            usage = event["usage"]
        error = event.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            errors.append(error["message"][:500])
        for item in event.get("output") or []:
            if not isinstance(item, dict) or item.get("role") != "assistant":
                continue
            for part in item.get("content") or []:
                if not isinstance(part, dict):
                    continue
                if part.get("type") not in ("text", "output_text"):
                    continue
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    texts.append(text.strip())
    return {
        "event_count": len(events),
        "completed": bool(events) and not errors,
        "tool_markers": _tool_markers(events),
        "usage": usage,
        "errors": errors,
        "response": max(texts, key=len) if texts else "",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18088")
    parser.add_argument("--novel-id", required=True)
    parser.add_argument("--novel-title", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--session-id")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    session_id = args.session_id or f"plan74-formal-assistant-{uuid4()}"
    snapshot = {
        "schemaVersion": "private-library-assistant-context/1",
        "contextRevision": 1,
        "capturedAt": now.isoformat(),
        "expiresAt": (now + timedelta(minutes=10)).isoformat(),
        "agentId": "ai-novel-writer",
        "sessionId": session_id,
        "library": {"id": "personal"},
        "novel": {"id": args.novel_id, "title": args.novel_title},
        "page": {"section": "private-library", "view": "library"},
        "budget": {
            "maxCharacters": 24_000,
            "usedCharacters": 0,
            "truncated": False,
            "omittedFieldIds": [],
        },
    }
    context = _post_json(
        args.base_url.rstrip("/")
        + "/api/ai-novel-world-2026/assistant-contexts",
        {
            "ownerToken": f"plan74_owner_{uuid4().hex}",
            "tabInstance": f"plan74_tab_{uuid4().hex}",
            "agentId": "ai-novel-writer",
            "scopeKind": "private_library",
            "scopeId": "personal",
            "novelId": args.novel_id,
            "sessionId": session_id,
            "snapshot": snapshot,
        },
        timeout=30,
    )
    context_ref = context.get("contextRef") if isinstance(context, dict) else None
    if not isinstance(context_ref, str) or not context_ref:
        raise RuntimeError("private-library context reference was not created")

    result = {
        "schema_version": "plan74-formal-assistant-run/1",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "novel_id": args.novel_id,
        "context_ref_sha256": hashlib.sha256(context_ref.encode()).hexdigest(),
        "writing_action_id": context.get("writingActionId"),
        "transport": _chat(
            args.base_url,
            prompt=args.prompt,
            session_id=session_id,
            context_ref=context_ref,
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    transport = result["transport"]
    return 0 if transport["completed"] and transport["response"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
