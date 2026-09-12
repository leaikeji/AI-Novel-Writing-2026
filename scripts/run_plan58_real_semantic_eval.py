#!/usr/bin/env python3
"""Run the frozen Plan 58 semantic-routing set against QwenPaw's public API.

This is an evidence runner, not a product entrypoint.  It makes exactly one
HTTP request per scenario, never retries, never reads provider configuration,
and persists only the final routing JSON plus bounded public transport facts.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any
from urllib.request import Request, urlopen
from uuid import UUID, uuid4
import zlib

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
    SkillInvocationPlanV1,
    SourceItem,
    TaskModelInputProjectionV1,
    canonical_hash,
)
from backend.writing_skills.resolver import resolve_methods
from backend.writing_skills.semantic import (
    SemanticRouteRequestV2,
    SemanticTransportResultV1,
    apply_semantic_transport,
    prepare_semantic_request,
)
from backend.writing_skills.semantic_runtime import (
    SemanticAdapterObservationV1,
    build_semantic_prompt,
    classify_semantic_response_shape,
    parse_semantic_response,
)


FIXTURE = ROOT / "tests/writing_skills/fixtures/routing_scenarios.json"
PLAN70_ROUTE_FIXTURE = (
    ROOT / "tests/writing_skills/fixtures/plan70_chapter_route_requests.json"
)
FORMAL_IDS = frozenset({"suspense-writing", "golden-finger-writing"})
PLAN70_EXPLICIT_EXCLUSION_IDS = frozenset({"P70-C09", "P70-C16"})
EXIT_COMPLETE = 0
EXIT_PREFLIGHT_FAILED = 20
EXIT_STOPPED = 21
EXIT_SCORE_FAILED = 22
ISOLATED_ROUTE_HTTP_TIMEOUT_SECONDS = 120
OWNER = UUID("29cf94d9-a5c9-54ec-912c-5dfff8738c4c")
WORKSPACE = UUID("f0e2e632-bc99-52d2-9916-bb906aa4da6e")
SCOPE_ID = UUID("11111111-1111-4111-8111-111111111111")
DOCUMENT_ID = UUID("22222222-2222-4222-8222-222222222222")
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


def normalize_plan70_projection(
    projection: TaskModelInputProjectionV1, scenario_id: str
) -> TaskModelInputProjectionV1:
    """Remove run-specific DB identities from an actually captured projection."""

    normalized_sources = []
    for source in projection.sources:
        text = re.sub(
            r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
            "77777777-7777-4777-8777-777777777777",
            source.text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"\b[0-9a-f]{64}\b", "0" * 64, text, flags=re.IGNORECASE)
        normalized_sources.append(source.model_copy(update={"text": text}))
    return TaskModelInputProjectionV1(
        scope=Scope(
            owner_id=OWNER,
            workspace_id=WORKSPACE,
            kind="novel",
            scope_id=SCOPE_ID,
            document_id=DOCUMENT_ID,
            tab_id=f"plan70-{scenario_id.lower()}",
        ),
        task=projection.task,
        intent=projection.intent,
        operation=projection.operation,
        source_version="plan70-actual-chapter-capture/1",
        visibility_key=_sha256("".join(item.text for item in normalized_sources)),
        sources=tuple(normalized_sources),
        truncated=projection.truncated,
    )


def _plan70_catalog() -> CapabilityCatalog:
    return load_catalog(ROOT / "skills", packaged_approvals(), FORMAL_IDS)


def encode_plan70_projection(projection: TaskModelInputProjectionV1) -> str:
    raw = json.dumps(
        projection.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.b64encode(zlib.compress(raw, level=9)).decode("ascii")


def decode_plan70_projection(case: dict[str, Any]) -> TaskModelInputProjectionV1:
    if case.get("projection_encoding") != "zlib-base64-canonical-json/1":
        raise ValueError("invalid_plan70_projection_encoding")
    try:
        raw = zlib.decompress(base64.b64decode(case["projection_data"], validate=True))
    except (KeyError, TypeError, ValueError, zlib.error) as exc:
        raise ValueError("invalid_plan70_projection_data") from exc
    if _sha256(raw) != case.get("projection_sha256"):
        raise ValueError("plan70_projection_hash_mismatch")
    return TaskModelInputProjectionV1.model_validate_json(raw)


def _plan70_expected_by_skill(case: dict[str, Any]) -> dict[str, str]:
    outcome = case.get("expected_case_outcome")
    if outcome == "skip":
        if "expected_by_skill" in case:
            raise ValueError("invalid_plan70_expected_contract")
        return {}
    value = case.get("expected_by_skill")
    if outcome != "route" or not isinstance(value, dict):
        raise ValueError("invalid_plan70_expected_contract")
    if set(value) != set(FORMAL_IDS) or any(
        decision not in {"select", "reject", "unknown"}
        for decision in value.values()
    ):
        raise ValueError("invalid_plan70_expected_contract")
    return {str(skill_id): str(decision) for skill_id, decision in value.items()}


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
        "failure_stage": None,
        "failure_code": None,
        "failure_type": None,
        "duration_ms": None,
    }


def _load_plan70_approval(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "run_id", "provider_id", "model_id", "cases",
    } or value.get("schema_version") != "plan70-semantic-eval-approval/1":
        raise ValueError("invalid_plan70_approval")
    if not all(isinstance(value.get(key), str) and value[key].strip()
               for key in ("run_id", "provider_id", "model_id")):
        raise ValueError("invalid_plan70_approval_identity")
    cases = value.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= 46:
        raise ValueError("invalid_plan70_approval_cases")
    ids: set[str] = set()
    attempts: set[str] = set()
    for item in cases:
        if not isinstance(item, dict) or set(item) != {
            "scenario_id", "attempt_id", "request_hash",
        }:
            raise ValueError("invalid_plan70_approval_case")
        scenario_id = item.get("scenario_id")
        attempt_id = item.get("attempt_id")
        request_hash = item.get("request_hash")
        if (not isinstance(scenario_id, str) or not scenario_id
                or not isinstance(request_hash, str) or len(request_hash) != 64
                or any(character not in "0123456789abcdef" for character in request_hash)):
            raise ValueError("invalid_plan70_approval_case_identity")
        UUID(str(attempt_id))
        if scenario_id in ids or str(attempt_id) in attempts:
            raise ValueError("duplicate_plan70_approval_case")
        ids.add(scenario_id)
        attempts.add(str(attempt_id))
    return value


def _isolated_chapter_route(
    route_url: str,
    semantic_request: SemanticRouteRequestV2,
    *,
    approval: dict[str, Any],
    approved_case: dict[str, str],
) -> dict[str, Any]:
    payload = {
        "run_id": approval["run_id"],
        "scenario_id": approved_case["scenario_id"],
        "attempt_id": approved_case["attempt_id"],
        "request": semantic_request.model_dump(mode="json"),
    }
    request = Request(
        route_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=ISOLATED_ROUTE_HTTP_TIMEOUT_SECONDS) as response:
        value = json.load(response)
    if not isinstance(value, dict) or value.get("schema_version") != "plan70-semantic-route-transport/1":
        raise ValueError("invalid_plan70_route_response")
    if any(value.get(key) != payload[key] for key in ("run_id", "scenario_id", "attempt_id")):
        raise ValueError("plan70_route_response_identity_mismatch")
    if (value.get("provider_id"), value.get("model_id")) != (
        approval["provider_id"], approval["model_id"],
    ):
        raise ValueError("plan70_route_response_model_mismatch")
    raw_observation = value.get("observation")
    if not isinstance(raw_observation, dict):
        raise ValueError("invalid_plan70_route_observation")
    try:
        observation = SemanticAdapterObservationV1.model_validate(raw_observation)
    except Exception as error:
        raise ValueError("invalid_plan70_route_observation") from error
    status = observation.status
    text = observation.text
    counters = {
        key: getattr(observation, key)
        for key in ("model_rounds", "tool_calls", "transport_attempts")
    }
    if any(type(value) is not int for value in counters.values()):
        raise ValueError("invalid_plan70_route_counters")
    if (counters["model_rounds"] not in {0, 1} or counters["tool_calls"] != 0
            or counters["transport_attempts"] != 1):
        raise ValueError("plan70_route_transport_contract_violation")
    if status == "ok" and counters["model_rounds"] != 1:
        raise ValueError("plan70_route_success_without_one_model_round")
    return {
        "session_id": str(approved_case["attempt_id"]),
        "event_count": 1,
        "statuses": [status],
        "content_types": {"output_text": 1} if text else {},
        "tool_markers": counters["tool_calls"],
        "usage": {
            "provider_id": value["provider_id"],
            "model_id": value["model_id"],
        },
        "errors": [] if status == "ok" else [f"semantic_transport_{status}"],
        "final_text": text or "",
        "model_rounds": counters["model_rounds"],
        "transport_attempts": counters["transport_attempts"],
        "failure_stage": observation.failure_stage,
        "failure_code": observation.failure_code,
        "failure_type": observation.failure_type,
        "duration_ms": observation.duration_ms,
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
            item.get("status") == "ok"
            and bool(item.get("exact"))
            and not item["expected"]
            and not item["observed"]
            for item in results
        ),
        "all_candidates": metrics(None),
        "formal_modules": metrics(set(FORMAL_IDS)),
    }


def _suite_passed(
    suite: str,
    wanted: list[str],
    expected_full_order: list[str],
    score: dict[str, Any],
) -> bool:
    """Apply only the frozen full-suite gates; subsets are diagnostics."""

    if wanted != expected_full_order or score["total"] != len(expected_full_order):
        return False
    if score["exact"] < 18:
        return False
    formal = score["formal_modules"]
    if formal["precision"] < 0.95 or formal["recall"] < 0.90:
        return False
    if suite == "plan58-s":
        return all(
            formal["per_skill"].get(skill_id, {}).get("recall", 0.0) >= 0.90
            for skill_id in FORMAL_IDS
        )
    golden = formal["per_skill"].get("golden-finger-writing", {})
    return (
        golden.get("precision", 0.0) >= 0.95
        and golden.get("recall", 0.0) >= 0.90
    )


def _safe_transport_evidence(public: dict[str, Any] | None) -> dict[str, Any] | None:
    if public is None:
        return None
    final_text = public.get("final_text")
    return {
        "session_id": public.get("session_id"),
        "event_count": public.get("event_count"),
        "statuses": public.get("statuses", []),
        "content_types": public.get("content_types", {}),
        "tool_markers": public.get("tool_markers"),
        "usage": public.get("usage", {}),
        "errors": ["transport_reported_error"] if public.get("errors") else [],
        "failure_stage": public.get("failure_stage"),
        "failure_code": public.get("failure_code"),
        "failure_type": public.get("failure_type"),
        "duration_ms": public.get("duration_ms"),
        "model_rounds": public.get("model_rounds"),
        "transport_attempts": public.get("transport_attempts"),
        "response_shape": classify_semantic_response_shape(final_text)
        if isinstance(final_text, str) else "empty",
    }


def _transport_stop_reason(error: BaseException) -> str:
    code = error.args[0] if len(error.args) == 1 else None
    if code in {
        "plan70_route_transport_contract_violation",
        "plan70_route_success_without_one_model_round",
        "semantic_scope_or_catalog_mismatch",
        "semantic_request_changed",
        "semantic_request_candidate_mismatch",
        "semantic_transport_contract_violation",
        "semantic_success_without_one_call",
        "invalid_semantic_payload",
        "semantic_candidate_set_mismatch",
        "semantic_evidence_out_of_scope",
        "semantic_method_conflict",
        "semantic_capability_limit",
    }:
        return "route_contract_invalid"
    if code in {
        "invalid_plan70_route_response",
        "plan70_route_response_identity_mismatch",
        "plan70_route_response_model_mismatch",
        "invalid_plan70_route_observation",
        "invalid_plan70_route_counters",
        "semantic_response_not_bare_object",
        "semantic_response_invalid_json",
        "semantic_response_not_object",
    }:
        return "response_contract_invalid"
    return "transport_failed"


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
    parser.add_argument(
        "--suite", required=True, choices=("plan58-s", "plan70-chapter")
    )
    parser.add_argument("--ids")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--transport", required=True,
        choices=("isolated-chapter-pawapp", "legacy-console"),
        help="Plan70 runs must use isolated-chapter-pawapp; legacy-console is historical only.",
    )
    parser.add_argument("--route-url")
    parser.add_argument("--approval", type=Path)
    args = parser.parse_args()
    output_path = args.output.resolve()

    if output_path.exists():
        print("output_exists", file=sys.stderr, flush=True)
        return EXIT_PREFLIGHT_FAILED

    fixture_bytes = b""
    fixture: dict[str, Any] = {}
    cases: dict[str, dict[str, Any]] = {}
    default_wanted: list[str] = []
    wanted: list[str] = []
    prepared: dict[str, tuple[
        dict[str, Any], TaskModelInputProjectionV1, SkillInvocationPlanV1,
        SemanticRouteRequestV2, str,
    ]] = {}
    skipped: set[str] = set()
    approval: dict[str, Any] | None = None
    approved_cases: dict[str, dict[str, str]] = {}
    attempts: list[dict[str, str]] = []
    results: list[dict[str, Any]] = []
    started_model: tuple[str, str] | None = None
    attempted_count = 0

    def report(
        *, run_status: str, stop_reason: str | None,
        stopped_at_case: str | None,
    ) -> dict[str, Any]:
        score = _score(results)
        return {
            "schema_version": "plan58-real-semantic-evaluation/1",
            "suite": args.suite,
            "fixture_sha256": _sha256(fixture_bytes) if fixture_bytes else None,
            "requested_ids": wanted,
            "http_requests": attempted_count,
            "automatic_retries": 0,
            "semantic_request_schema": "semantic-route-request/2",
            "agent_id": "ai-novel-writer",
            "transport": args.transport,
            "run_id": approval["run_id"] if approval is not None else None,
            "attempts": attempts,
            "effective_model": ({
                "provider_id": started_model[0], "model_id": started_model[1],
            } if started_model is not None else None),
            "run_status": run_status,
            "stop_reason": stop_reason,
            "stopped_at_case": stopped_at_case,
            "unexecuted_count": max(
                0, len([item for item in wanted if item not in skipped])
                - attempted_count,
            ),
            "score": score,
            "results": results,
            "limitations": ([
                "隔离PawApp只执行一次受批准的语义路由，不生成正文、不调用工具、不经过QwenPaw助手聊天入口。",
                "当前隔离路由回执不提供token usage；成本未知，不作推算。",
                "测试未来模块仅来自冻结fixture，不进入正式Skill包或启用清单。",
            ] if approval is not None else [
                "legacy-console仅保留复核旧证据，不允许用于Plan70新评测。",
                "公开console API未暴露请求级tools参数；旧报告只记录SSE中实际观察到的tool markers。",
                "测试未来模块仅来自冻结fixture，不进入正式Skill包或启用清单。",
            ]),
        }

    def preflight_failure(reason: str) -> int:
        _atomic_json(output_path, report(
            run_status="preflight_failed", stop_reason=reason,
            stopped_at_case=None,
        ))
        print(reason, file=sys.stderr, flush=True)
        return EXIT_PREFLIGHT_FAILED

    def checkpoint() -> None:
        _atomic_json(output_path, {
            "schema_version": "plan70-semantic-eval-checkpoint/1",
            "suite": args.suite,
            "run_id": approval["run_id"] if approval is not None else None,
            "transport": args.transport,
            "requested_ids": wanted,
            "effective_model": ({
                "provider_id": started_model[0], "model_id": started_model[1],
            } if started_model is not None else None),
            "http_requests": attempted_count,
            "attempts": attempts,
            "results": results,
        })

    try:
        if args.suite == "plan58-s":
            fixture_bytes = FIXTURE.read_bytes()
            fixture = json.loads(fixture_bytes)
            cases = {item["id"]: item for item in fixture["s_scenarios"]}
            default_wanted = [f"S{index:02d}" for index in range(1, 21)]
            catalog = _catalog(fixture)
        else:
            if args.transport != "isolated-chapter-pawapp":
                return preflight_failure("approval_invalid")
            fixture_bytes = PLAN70_ROUTE_FIXTURE.read_bytes()
            fixture = json.loads(fixture_bytes)
            if fixture.get("schema_version") != "plan70-chapter-route-requests/2":
                return preflight_failure("approval_invalid")
            cases = {item["id"]: item for item in fixture["cases"]}
            default_wanted = [f"P70-C{index:02d}" for index in range(1, 21)]
            catalog = _plan70_catalog()
        wanted = (
            default_wanted if not args.ids
            else [item.strip() for item in args.ids.split(",") if item.strip()]
        )
        if not wanted or any(item not in cases for item in wanted):
            return preflight_failure("approval_scope_mismatch")

        for scenario_id in wanted:
            case = cases[scenario_id]
            projection = (
                _projection(case) if args.suite == "plan58-s"
                else decode_plan70_projection(case)
            )
            plan = resolve_methods(
                projection, catalog, MethodPreferences(), "prose-writing"
            )
            if args.suite == "plan70-chapter":
                expected_by_skill = _plan70_expected_by_skill(case)
            if (
                args.suite == "plan70-chapter"
                and case["expected_case_outcome"] == "skip"
            ):
                skipped.add(scenario_id)
                continue
            semantic_request = prepare_semantic_request(
                projection, catalog, plan, semantic_enabled=True
            )
            if not isinstance(semantic_request, SemanticRouteRequestV2):
                return preflight_failure("approval_scope_mismatch")
            prompt = build_semantic_prompt(semantic_request)
            prepared[scenario_id] = (
                case, projection, plan, semantic_request, prompt,
            )

        if args.transport == "isolated-chapter-pawapp":
            if args.approval is None or not args.route_url:
                return preflight_failure("approval_invalid")
            try:
                approval = _load_plan70_approval(args.approval.resolve())
            except Exception:
                return preflight_failure("approval_invalid")
            approved_cases = {
                item["scenario_id"]: item for item in approval["cases"]
            }
            actionable = [item for item in wanted if item not in skipped]
            if list(approved_cases) != actionable:
                return preflight_failure("approval_scope_mismatch")
            for scenario_id in actionable:
                request_hash = canonical_hash(prepared[scenario_id][3])
                if approved_cases[scenario_id]["request_hash"] != request_hash:
                    return preflight_failure("approval_request_hash_mismatch")
            attempts = [{
                "scenario_id": item["scenario_id"],
                "attempt_id": item["attempt_id"],
                "state": "planned",
            } for item in approval["cases"]]
    except Exception:
        return preflight_failure("approval_invalid")

    try:
        started_model = _active_model(args.base_url)
    except Exception:
        return preflight_failure("model_probe_failed")
    if approval is not None and started_model != (
        approval["provider_id"], approval["model_id"],
    ):
        return preflight_failure("effective_model_mismatch")
    checkpoint()

    stop_reason: str | None = None
    stopped_at_case: str | None = None
    for scenario_id in wanted:
        if scenario_id in skipped:
            case = cases[scenario_id]
            projection = decode_plan70_projection(case)
            results.append({
                "scenario_id": scenario_id,
                "task": projection.task,
                "expected": [],
                "expected_outcome": "skip",
                "expected_by_skill": {},
                "observed": [],
                "observed_by_skill": {},
                "exact": True,
                "status": "skipped",
                "error": None,
                "source_hash": projection.source_hash,
                "semantic_request_schema": None,
                "prompt_sha256": None,
                "prompt_characters": 0,
                "response_sha256": None,
                "response": None,
                "transport": None,
                "model_before": None,
                "model_after": None,
            })
            print(f"{scenario_id} skipped expected=[] observed=[]", flush=True)
            continue
        case, projection, plan, semantic_request, prompt = prepared[scenario_id]
        try:
            before = _active_model(args.base_url)
        except Exception:
            stop_reason = "model_probe_failed"
            stopped_at_case = scenario_id
            break
        if before != started_model:
            stop_reason = "effective_model_changed"
            stopped_at_case = scenario_id
            break
        if approval is not None:
            next(item for item in attempts if item["scenario_id"] == scenario_id)[
                "state"
            ] = "started"
        attempted_count += 1
        checkpoint()
        public: dict[str, Any] | None = None
        try:
            public = (_isolated_chapter_route(
                args.route_url,
                semantic_request,
                approval=approval,
                approved_case=approved_cases[scenario_id],
            ) if approval is not None else _public_chat(
                args.base_url, prompt, scenario_id,
            ))
        except Exception as exc:
            stop_reason = _transport_stop_reason(exc)
            stopped_at_case = scenario_id
            if args.suite == "plan58-s":
                failed_expected = sorted(str(item) for item in case["expected"])
                failed_expected_outcome = None
                failed_expected_by_skill = None
                failed_observed_by_skill = None
            else:
                failed_expected_by_skill = _plan70_expected_by_skill(case)
                failed_expected = sorted(
                    skill_id
                    for skill_id, decision in failed_expected_by_skill.items()
                    if decision == "select"
                )
                failed_expected_outcome = str(case["expected_case_outcome"])
                failed_observed_by_skill = {}
            results.append({
                "scenario_id": scenario_id,
                "task": projection.task,
                "expected": failed_expected,
                "expected_outcome": failed_expected_outcome,
                "expected_by_skill": failed_expected_by_skill,
                "observed": [],
                "observed_by_skill": failed_observed_by_skill,
                "exact": False,
                "status": "failed",
                "route_status": None,
                "error": stop_reason,
                "source_hash": projection.source_hash,
                "semantic_request_schema": semantic_request.schema_version,
                "prompt_sha256": _sha256(prompt),
                "prompt_characters": len(prompt),
                "response_sha256": None,
                "response": None,
                "decision_hash": None,
                "transport": None,
                "model_before": {
                    "provider_id": before[0], "model_id": before[1],
                },
                "model_after": None,
            })
            _atomic_json(output_path, report(
                run_status="stopped", stop_reason=stop_reason,
                stopped_at_case=stopped_at_case,
            ))
            break

        try:
            after = _active_model(args.base_url)
        except Exception:
            after = None
            stop_reason = "model_probe_failed"
            stopped_at_case = scenario_id
        status = "ok"
        error: str | None = None
        observed: list[str] = []
        route_status: str | None = None
        response_payload: dict[str, Any] | None = None
        observed_by_skill: dict[str, str] = {}
        decision_hash: str | None = None
        usage_model = (
            public.get("usage", {}).get("provider_id"),
            public.get("usage", {}).get("model_name")
            or public.get("usage", {}).get("model_id"),
        )
        if stop_reason is None and after != started_model:
            stop_reason = "effective_model_changed"
        if stop_reason is None and usage_model != started_model:
            stop_reason = "actual_model_mismatch"
        public_statuses = set(public.get("statuses", []))
        if stop_reason is None and (
            "unknown" in public_statuses
            or public.get("failure_code") in {
                "chat_error_after_observation",
                "chat_timeout_after_observation",
                "chat_cancelled_after_observation",
                "reply_evidence_postflight_unavailable",
            }
        ):
            stop_reason = "transport_unknown"
        if stop_reason is None and public.get("errors"):
            stop_reason = "transport_failed"
        if stop_reason is None and public.get("tool_markers"):
            stop_reason = "tool_call_observed"
        if stop_reason is None:
            try:
                response_payload = parse_semantic_response(public["final_text"])
                outcome = apply_semantic_transport(
                    projection,
                    catalog,
                    plan,
                    semantic_request,
                    SemanticTransportResultV1(
                        status="ok",
                        payload=response_payload,
                        model_rounds=public.get("model_rounds", 1),
                        tool_calls=public.get("tool_markers", 0),
                        transport_attempts=public.get("transport_attempts", 1),
                    ),
                )
                route_status = outcome.status
                decision_hash = outcome.decision_hash
                selected = {item.skill_id for item in outcome.plan.selected}
                if args.suite == "plan70-chapter":
                    selected.discard("prose-writing")
                observed = sorted(selected)
                if args.suite == "plan70-chapter":
                    response_decisions = {
                        str(item["skill_id"]): str(item["decision"])
                        for item in response_payload["decisions"]
                    }
                    observed_by_skill = {
                        skill_id: (
                            "select" if skill_id in selected
                            else response_decisions.get(skill_id, "reject")
                        )
                        for skill_id in sorted(FORMAL_IDS)
                    }
                if route_status == "unknown":
                    status = "unknown"
                    if (
                        args.suite != "plan70-chapter"
                        or "unknown" not in _plan70_expected_by_skill(case).values()
                    ):
                        stop_reason = "unexpected_abstention"
                elif route_status not in {"applied", "rejected"}:
                    stop_reason = "route_contract_invalid"
                if (
                    stop_reason is None
                    and args.suite == "plan70-chapter"
                    and scenario_id in PLAN70_EXPLICIT_EXCLUSION_IDS
                    and "golden-finger-writing" in observed
                ):
                    stop_reason = "explicit_exclusion_violated"
            except Exception as exc:
                stop_reason = _transport_stop_reason(exc)
        if stop_reason is not None:
            status = "unknown" if stop_reason == "transport_unknown" else "failed"
            error = stop_reason
            stopped_at_case = scenario_id
        if args.suite == "plan58-s":
            expected = sorted(str(item) for item in case["expected"])
            expected_outcome = None
            exact = status == "ok" and observed == expected
        else:
            expected_outcome = str(case["expected_case_outcome"])
            expected_by_skill = _plan70_expected_by_skill(case)
            expected = sorted(
                skill_id for skill_id, decision in expected_by_skill.items()
                if decision == "select"
            )
            expected_has_unknown = "unknown" in expected_by_skill.values()
            exact = observed_by_skill == expected_by_skill and (
                route_status == "unknown" if expected_has_unknown
                else status == "ok"
            )
        results.append(
            {
                "scenario_id": scenario_id,
                "task": projection.task,
                "expected": expected,
                "expected_outcome": expected_outcome,
                "expected_by_skill": (
                    expected_by_skill if args.suite == "plan70-chapter" else None
                ),
                "observed": observed,
                "observed_by_skill": (
                    observed_by_skill if args.suite == "plan70-chapter" else None
                ),
                "exact": exact,
                "status": status,
                "route_status": route_status,
                "error": error,
                "source_hash": projection.source_hash,
                "semantic_request_schema": semantic_request.schema_version,
                "prompt_sha256": _sha256(prompt),
                "prompt_characters": len(prompt),
                "response_sha256": _sha256(public["final_text"]),
                "response": response_payload,
                "decision_hash": decision_hash,
                "transport": _safe_transport_evidence(public),
                "model_before": {
                    "provider_id": before[0],
                    "model_id": before[1],
                },
                "model_after": ({
                    "provider_id": after[0],
                    "model_id": after[1],
                } if after is not None else None),
            }
        )
        if approval is not None:
            next(item for item in attempts if item["scenario_id"] == scenario_id)[
                "state"
            ] = "completed"
        if stop_reason is not None:
            _atomic_json(output_path, report(
                run_status="stopped", stop_reason=stop_reason,
                stopped_at_case=stopped_at_case,
            ))
        else:
            checkpoint()
        print(
            f"{scenario_id} {status} expected={expected} observed={observed}",
            flush=True,
        )
        if stop_reason is not None:
            break

    if stop_reason is not None:
        final_report = report(
            run_status="stopped", stop_reason=stop_reason,
            stopped_at_case=stopped_at_case,
        )
        _atomic_json(output_path, final_report)
        print(json.dumps(final_report["score"], ensure_ascii=False, indent=2))
        return EXIT_STOPPED

    final_score = _score(results)
    passed = _suite_passed(args.suite, wanted, default_wanted, final_score)
    final_report = report(
        run_status="complete",
        stop_reason=None if passed else "score_below_threshold",
        stopped_at_case=None,
    )
    _atomic_json(output_path, final_report)
    print(json.dumps(final_score, ensure_ascii=False, indent=2))
    return EXIT_COMPLETE if passed else EXIT_SCORE_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
