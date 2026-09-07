#!/usr/bin/env python3
"""Run the frozen Plan 58 semantic-routing set against QwenPaw's public API.

This is an evidence runner, not a product entrypoint.  It makes exactly one
HTTP request per scenario, never retries, never reads provider configuration,
and persists only the final routing JSON plus bounded public transport facts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.writing_skills.catalog import load_catalog, packaged_approvals
from backend.writing_skills.contracts import (
    CapabilityCatalog,
    CapabilityDeclaration,
    LoadedCapability,
    MethodBlock,
    MethodPreferences,
    Scope,
    SourceItem,
    TaskModelInputProjectionV1,
    canonical_hash,
)
from backend.writing_skills.resolver import resolve_methods
from backend.writing_skills.semantic import (
    SemanticTransportResultV1,
    apply_semantic_transport,
    prepare_semantic_request,
)
from backend.writing_skills.semantic_runtime import (
    build_semantic_prompt,
    parse_semantic_response,
)


FIXTURE = ROOT / "tests/writing_skills/fixtures/routing_scenarios.json"
FORMAL_IDS = frozenset({"suspense-writing", "golden-finger-writing"})
OWNER = UUID("29cf94d9-a5c9-54ec-912c-5dfff8738c4c")
WORKSPACE = UUID("f0e2e632-bc99-52d2-9916-bb906aa4da6e")
SCOPE_ID = UUID("11111111-1111-4111-8111-111111111111")
CREATIVE_TASKS = (
    "direction",
    "chapter_body",
    "chapter_outline",
    "chapter_storyline_recommendation",
    "outline_background",
    "outline_characters",
    "outline_plot",
    "outline_highlight",
    "character_profile_completion",
    "review",
    "continuity_check",
    "selection_edit",
)


def _sha256(value: str | bytes) -> str:
    raw = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _future_capability(item: dict[str, Any]) -> LoadedCapability:
    kind = str(item["kind"])
    label = str(item["label"])
    declaration = CapabilityDeclaration(
        skill_id=str(item["skill_id"]),
        capability_version="1.0.0",
        kind=kind,
        display_name=f"计划58测试模块 {item['skill_id']}",
        description=str(item["description"]),
        approval_ref="plan58-frozen-fixture",
        release_status="author_approved",
        genre_aliases=(label,) if kind == "genre" else (),
        mechanism_tags=(label,) if kind == "mechanism" else (),
        applicable_tasks=CREATIVE_TASKS,
        excluded_tasks=("mechanical", "excluded", "novel_naming", "novel_template"),
        semantic_criteria=tuple(str(x) for x in item["semantic_criteria"]),
        negative_examples=tuple(str(x) for x in item["negative_examples"]),
        supersedes=tuple(str(x) for x in item.get("supersedes", ())),
    )
    text = f"---\nname: {item['skill_id']}\n---\n\n# 计划58测试方法\n"
    return LoadedCapability(
        declaration=declaration,
        routing_hash=canonical_hash(declaration),
        body=MethodBlock(
            skill_id=str(item["skill_id"]),
            path="SKILL.md",
            text=text,
            sha256=_sha256(text),
        ),
    )


def _catalog(fixture: dict[str, Any]) -> CapabilityCatalog:
    formal = load_catalog(ROOT / "skills", packaged_approvals(), FORMAL_IDS)
    future = tuple(
        _future_capability(item) for item in fixture["catalog_fixture"].values()
    )
    return CapabilityCatalog(capabilities=(*formal.capabilities, *future))


def _projection(case: dict[str, Any]) -> TaskModelInputProjectionV1:
    task = str(case["task"])
    return TaskModelInputProjectionV1(
        scope=Scope(
            owner_id=OWNER,
            workspace_id=WORKSPACE,
            kind="novel",
            scope_id=SCOPE_ID,
            tab_id=f"plan58-real-{case['id']}",
        ),
        task=task,
        intent="review" if task in ("review", "continuity_check") else "write",
        operation="polish" if task == "selection_edit" else "",
        source_version="plan58-real-v2",
        visibility_key=f"frozen-{case['id']}",
        sources=tuple(
            SourceItem(key=f"source.{index}", kind=item[0], text=item[1])
            for index, item in enumerate(case["sources"])
        ),
    )


def _active_model(base_url: str) -> tuple[str, str]:
    url = (
        base_url.rstrip("/")
        + "/api/models/active?scope=effective&agent_id=ai-novel-writer"
    )
    with urlopen(url, timeout=10) as response:
        payload = json.load(response)
    active = payload.get("active_llm") if isinstance(payload, dict) else None
    provider = active.get("provider_id") if isinstance(active, dict) else None
    model = active.get("model") if isinstance(active, dict) else None
    if not isinstance(provider, str) or not provider.strip():
        raise RuntimeError("missing_effective_provider")
    if not isinstance(model, str) or not model.strip():
        raise RuntimeError("missing_effective_model")
    return provider.strip(), model.strip()


def _tool_marker_count(value: object) -> int:
    if isinstance(value, list):
        return sum(_tool_marker_count(item) for item in value)
    if not isinstance(value, dict):
        return 0
    count = 0
    discriminator = value.get("type") or value.get("object")
    if isinstance(discriminator, str) and "tool" in discriminator.lower():
        count += 1
    for key, item in value.items():
        if "tool_call" in str(key).lower() and item not in (None, [], {}):
            count += 1
        count += _tool_marker_count(item)
    return count


def _public_chat(
    base_url: str, prompt: str, scenario_id: str
) -> dict[str, Any]:
    session_id = f"plan58-real-route-{scenario_id}-{uuid4()}"
    payload = {
        "input": [
            {
                "role": "user",
                "content": [{"type": "text", "text": prompt}],
            }
        ],
        "session_id": session_id,
        "user_id": "plan58-evaluator",
        "channel": "console",
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
    with urlopen(request, timeout=120) as response:
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
    usage: dict[str, Any] = {}
    content_types: dict[str, int] = {}
    errors: list[str] = []
    for event in events:
        if isinstance(event.get("usage"), dict):
            usage = event["usage"]
        error = event.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            errors.append(error["message"][:300])
        for item in event.get("output") or []:
            if not isinstance(item, dict):
                continue
            for part in item.get("content") or []:
                if not isinstance(part, dict):
                    continue
                part_type = str(part.get("type") or "")
                content_types[part_type] = content_types.get(part_type, 0) + 1
                text = part.get("text")
                if (
                    item.get("role") == "assistant"
                    and part_type in ("text", "output_text")
                    and isinstance(text, str)
                    and text.strip()
                ):
                    texts.append(text.strip())
    final_text = max(texts, key=len) if texts else ""
    safe_usage = {
        key: usage.get(key)
        for key in (
            "provider_id",
            "model_name",
            "model_id",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
        )
        if key in usage
    }
    return {
        "session_id": session_id,
        "event_count": len(events),
        "statuses": [event.get("status") for event in events if event.get("status")],
        "content_types": content_types,
        "tool_markers": _tool_marker_count(events),
        "usage": safe_usage,
        "errors": errors,
        "final_text": final_text,
    }


def _score(results: list[dict[str, Any]]) -> dict[str, Any]:
    universe = sorted(
        {skill_id for result in results for skill_id in (*result["expected"], *result["observed"])}
    )
    def metrics(allowed: set[str] | None) -> dict[str, Any]:
        true_positive = false_positive = false_negative = 0
        per_skill: dict[str, dict[str, Any]] = {}
        skill_ids = universe if allowed is None else sorted(allowed)
        for skill_id in skill_ids:
            tp = sum(
                skill_id in item["expected"] and skill_id in item["observed"]
                for item in results
            )
            fp = sum(
                skill_id not in item["expected"] and skill_id in item["observed"]
                for item in results
            )
            fn = sum(
                skill_id in item["expected"] and skill_id not in item["observed"]
                for item in results
            )
            true_positive += tp
            false_positive += fp
            false_negative += fn
            per_skill[skill_id] = {
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "precision": tp / (tp + fp) if tp + fp else 1.0,
                "recall": tp / (tp + fn) if tp + fn else 1.0,
            }
        return {
            "tp": true_positive,
            "fp": false_positive,
            "fn": false_negative,
            "precision": true_positive / (true_positive + false_positive)
            if true_positive + false_positive
            else 1.0,
            "recall": true_positive / (true_positive + false_negative)
            if true_positive + false_negative
            else 1.0,
            "per_skill": per_skill,
        }
    exact = sum(bool(item.get("exact")) for item in results)
    successful = sum(item.get("status") == "ok" for item in results)
    return {
        "successful": successful,
        "exact": exact,
        "total": len(results),
        "empty_set_correct": sum(
            not item["expected"] and not item["observed"] for item in results
        ),
        "all_candidates": metrics(None),
        "formal_modules": metrics(set(FORMAL_IDS)),
    }


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18088")
    parser.add_argument("--ids", default="S01-S20")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    fixture_bytes = FIXTURE.read_bytes()
    fixture = json.loads(fixture_bytes)
    cases = {item["id"]: item for item in fixture["s_scenarios"]}
    if args.ids == "S01-S20":
        wanted = [f"S{index:02d}" for index in range(1, 21)]
    else:
        wanted = [item.strip() for item in args.ids.split(",") if item.strip()]
    if not wanted or any(item not in cases for item in wanted):
        raise SystemExit("unknown_or_empty_scenario_id")

    catalog = _catalog(fixture)
    started_model = _active_model(args.base_url)
    results: list[dict[str, Any]] = []
    for scenario_id in wanted:
        case = cases[scenario_id]
        projection = _projection(case)
        plan = resolve_methods(
            projection, catalog, MethodPreferences(), "prose-writing"
        )
        semantic_request = prepare_semantic_request(
            projection, catalog, plan, semantic_enabled=True
        )
        prompt = build_semantic_prompt(semantic_request)
        before = _active_model(args.base_url)
        public = _public_chat(args.base_url, prompt, scenario_id)
        after = _active_model(args.base_url)
        status = "ok"
        error = None
        observed: list[str] = []
        response_payload: dict[str, Any] | None = None
        usage_model = (
            public["usage"].get("provider_id"),
            public["usage"].get("model_name") or public["usage"].get("model_id"),
        )
        try:
            if before != started_model or after != started_model:
                raise ValueError("effective_model_changed")
            if usage_model != started_model:
                raise ValueError("actual_model_mismatch")
            if public["errors"]:
                raise ValueError("public_chat_failed")
            if public["tool_markers"]:
                raise ValueError("tool_marker_observed")
            response_payload = parse_semantic_response(public["final_text"])
            outcome = apply_semantic_transport(
                projection,
                catalog,
                plan,
                semantic_request,
                SemanticTransportResultV1(
                    status="ok",
                    payload=response_payload,
                    model_rounds=1,
                    tool_calls=0,
                    transport_attempts=1,
                ),
            )
            observed = sorted(item.skill_id for item in outcome.plan.selected)
        except Exception as exc:  # evidence runner must keep the failed sample
            status = "failed"
            error = f"{type(exc).__name__}:{exc}"
        expected = sorted(str(item) for item in case["expected"])
        results.append(
            {
                "scenario_id": scenario_id,
                "task": case["task"],
                "expected": expected,
                "observed": observed,
                "exact": status == "ok" and observed == expected,
                "status": status,
                "error": error,
                "source_hash": projection.source_hash,
                "semantic_request_schema": semantic_request.schema_version,
                "prompt_sha256": _sha256(prompt),
                "prompt_characters": len(prompt),
                "response_sha256": _sha256(public["final_text"]),
                "response": response_payload,
                "transport": {
                    key: public[key]
                    for key in (
                        "session_id",
                        "event_count",
                        "statuses",
                        "content_types",
                        "tool_markers",
                        "usage",
                        "errors",
                    )
                },
                "model_before": {
                    "provider_id": before[0],
                    "model_id": before[1],
                },
                "model_after": {
                    "provider_id": after[0],
                    "model_id": after[1],
                },
            }
        )
        print(
            f"{scenario_id} {status} expected={expected} observed={observed}",
            flush=True,
        )

    report = {
        "schema_version": "plan58-real-semantic-evaluation/1",
        "fixture_sha256": _sha256(fixture_bytes),
        "requested_ids": wanted,
        "http_requests": len(results),
        "automatic_retries": 0,
        "semantic_request_schema": "semantic-route-request/2",
        "agent_id": "ai-novel-writer",
        "effective_model": {
            "provider_id": started_model[0],
            "model_id": started_model[1],
        },
        "score": _score(results),
        "results": results,
        "limitations": [
            "公开console API未暴露请求级tools参数；本报告只记录SSE中实际观察到的tool markers。",
            "prompt_tokens为Provider经QwenPaw公开usage返回值，不作推算或修正。",
            "测试未来模块仅来自冻结fixture，不进入正式Skill包或启用清单。",
        ],
    }
    _atomic_json(args.output.resolve(), report)
    print(json.dumps(report["score"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
