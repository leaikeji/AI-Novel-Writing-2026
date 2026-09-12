#!/usr/bin/env python3
"""Run the frozen Plan 70 chapter-writing A/B cells through an isolated PawApp.

This is a test evidence runner.  It never uses the assistant console, never
retries. Only a reviewed four-cell checkpoint may continue; started attempts
cannot be replayed after interruption.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.schemas import GenerateChapterRequest
from backend.services import visible_character_count
from backend.writing_skills.contracts import canonical_hash


DEFAULT_FIXTURE = ROOT / "tests/writing_skills/fixtures/plan70_writing_ab_cases_v2.json"
EXIT_COMPLETE = 0
EXIT_PREFLIGHT_FAILED = 20
EXIT_STOPPED = 21
EXIT_AWAITING_REVIEW = 22
WRITING_HTTP_TIMEOUT_SECONDS = 900
COMPARISON_CONTRACT_SCHEMA = "plan70-writing-ab-comparison/1"
ALLOWED_REQUEST_DIFFERENCES = [
    "arm",
    "generation.writing_action.action_id",
    "generation.writing_action.tab_id",
    "generation.writing_action.preferences.mode",
    "generation.writing_action.preferences.semantic_mode",
]
SAMPLING_POLICY = {
    "request_level_overrides": {},
    "provider_defaults_apply": True,
    "variance_control": "balanced_interleaved_execution_order",
}


def _sha256(value: str | bytes) -> str:
    raw = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _load_fixture(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "title", "target_visible_character_count",
        "minimum_visible_character_count", "execution_order",
        "first_gate_cells", "pairs",
    } or value.get("schema_version") not in {"plan70-writing-ab-cases/1", "plan70-writing-ab-cases/2"}:
        raise ValueError("invalid Plan70 writing A/B fixture")
    pairs = value.get("pairs")
    order = value.get("execution_order")
    if (not isinstance(pairs, list) or len(pairs) != 4
            or not isinstance(order, list) or len(order) != 8
            or len(set(order)) != 8
            or value.get("target_visible_character_count") != 2500
            or value.get("minimum_visible_character_count") != 2000):
        raise ValueError("invalid Plan70 writing A/B fixture inventory")
    pair_ids = [item.get("pair_id") for item in pairs if isinstance(item, dict)]
    if pair_ids != ["T01", "T02", "T03", "T04"]:
        raise ValueError("invalid Plan70 writing A/B pair order")
    expected_cells = {f"{pair_id}-{arm}" for pair_id in pair_ids for arm in ("A", "B")}
    if set(order) != expected_cells or value.get("first_gate_cells") != order[:4]:
        raise ValueError("invalid Plan70 writing A/B execution gate")
    for pair in pairs:
        seed = pair.get("seed")
        if not isinstance(seed, dict) or set(seed) != {
            "title", "description", "genre", "subgenre", "idea", "background",
            "main_plot", "chapter_title", "expectation_text", "outline_text",
            "forbidden_text",
        } or any(not isinstance(item, str) or not item.strip() for item in seed.values()):
            raise ValueError("invalid Plan70 writing A/B seed")
    value["fixture_sha256"] = _sha256(raw)
    return value


def review_baselines(fixture: dict[str, Any]) -> dict[str, Any]:
    """Verbatim source baseline: no summary may strengthen 'has' into 'only'."""
    return {
        "schema_version": "plan70-writing-review-baselines/1",
        "fixture_sha256": fixture["fixture_sha256"],
        "pairs": [{"pair_id": pair["pair_id"], "sources": pair["seed"]}
                  for pair in fixture["pairs"]],
    }


def _cell_request(
    fixture: dict[str, Any], cell_id: str, action_id: str
) -> dict[str, Any]:
    pair_id, arm = cell_id.split("-")
    pair = next(item for item in fixture["pairs"] if item["pair_id"] == pair_id)
    preferences = {
        "mode": "generic_only" if arm == "A" else "auto",
        "semantic_mode": "off" if arm == "A" else "auto",
        "excluded_ids": [],
        "required_ids": [],
        "version": "request/1",
    }
    generation = GenerateChapterRequest.model_validate({
        "expected_brief_version": 1,
        "force_new": False,
        "asset_ids": [],
        "preset_id": None,
        "writing_action": {
            "action_id": action_id,
            "tab_id": f"plan70-writing-{pair_id.lower()}-{arm.lower()}",
            "retry_of_action_id": None,
            "preferences": preferences,
        },
    })
    return {
        "pair_id": pair_id,
        "arm": arm,
        "seed": dict(pair["seed"]),
        "generation": generation.model_dump(mode="json"),
    }


def _approved_methods() -> list[dict[str, str]]:
    return [
        {
            "skill_id": "prose-writing",
            "version": "0.4.0",
            "body_sha256": _sha256((ROOT / "skills/prose-writing/SKILL.md").read_bytes()),
        },
        {
            "skill_id": "golden-finger-writing",
            "version": "1.0.1",
            "body_sha256": _sha256((ROOT / "skills/golden-finger-writing/SKILL.md").read_bytes()),
        },
    ]


def _normalized_shared_input(request: dict[str, Any]) -> dict[str, Any]:
    """Mask only the pre-approved A/B identity and method-policy differences."""

    value = json.loads(json.dumps(request, ensure_ascii=False))
    value["arm"] = "<METHOD_ARM>"
    action = value["generation"]["writing_action"]
    action["action_id"] = "<ACTION_ID>"
    action["tab_id"] = "<TAB_ID>"
    preferences = action["preferences"]
    preferences["mode"] = "<METHOD_MODE>"
    preferences["semantic_mode"] = "<SEMANTIC_MODE>"
    return value


def _comparison_contract(fixture: dict[str, Any]) -> dict[str, Any]:
    baselines = []
    for pair in fixture["pairs"]:
        pair_id = pair["pair_id"]
        requests = [
            _cell_request(fixture, f"{pair_id}-{arm}", str(uuid4()))
            for arm in ("A", "B")
        ]
        hashes = {
            canonical_hash(_normalized_shared_input(request))
            for request in requests
        }
        if len(hashes) != 1:
            raise ValueError(f"Plan70 {pair_id} has an unapproved A/B request difference")
        baselines.append({
            "pair_id": pair_id,
            "shared_input_hash": hashes.pop(),
        })
    return {
        "schema_version": COMPARISON_CONTRACT_SCHEMA,
        "allowed_request_differences": ALLOWED_REQUEST_DIFFERENCES,
        "sampling_policy": SAMPLING_POLICY,
        "pair_baselines": baselines,
    }


def build_approval(
    fixture: dict[str, Any], *, run_id: str, provider_id: str, model_id: str,
    effective_max_input_length: int = 131_072,
) -> dict[str, Any]:
    if not all(isinstance(item, str) and item.strip()
               for item in (run_id, provider_id, model_id)):
        raise ValueError("run and model identity are required")
    if (type(effective_max_input_length) is not int
            or effective_max_input_length <= 0):
        raise ValueError("approved effective context window must be positive")
    cells = []
    for cell_id in fixture["execution_order"]:
        attempt_id = str(uuid4())
        action_id = str(uuid4())
        request = _cell_request(fixture, cell_id, action_id)
        cells.append({
            "cell_id": cell_id,
            "attempt_id": attempt_id,
            "action_id": action_id,
            "request_hash": canonical_hash(request),
        })
    return {
        "schema_version": ("plan70-writing-ab-approval/3" if fixture["schema_version"].endswith("/2")
                           else "plan70-writing-ab-approval/2"),
        "run_id": run_id,
        "provider_id": provider_id,
        "model_id": model_id,
        "effective_max_input_length": effective_max_input_length,
        "fixture_sha256": fixture["fixture_sha256"],
        "methods": _approved_methods(),
        "comparison_contract": _comparison_contract(fixture),
        "cells": cells,
    }


def _load_approval(path: Path, fixture: dict[str, Any]) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "run_id", "provider_id", "model_id",
        "effective_max_input_length", "fixture_sha256", "methods",
        "comparison_contract", "cells",
    } or value.get("schema_version") != (
        "plan70-writing-ab-approval/3" if fixture["schema_version"].endswith("/2")
        else "plan70-writing-ab-approval/2"
    ):
        raise ValueError("invalid Plan70 writing A/B approval")
    if value.get("fixture_sha256") != fixture["fixture_sha256"]:
        raise ValueError("Plan70 writing fixture changed after approval")
    expected_methods = _approved_methods()
    if value.get("methods") != expected_methods:
        raise ValueError("Plan70 writing method bytes changed after approval")
    if value.get("comparison_contract") != _comparison_contract(fixture):
        raise ValueError("Plan70 writing A/B comparison contract changed after approval")
    cells = value.get("cells")
    if not isinstance(cells, list) or len(cells) != 8:
        raise ValueError("Plan70 writing approval must contain exactly eight cells")
    if [item.get("cell_id") for item in cells if isinstance(item, dict)] != fixture["execution_order"]:
        raise ValueError("Plan70 writing approval order mismatch")
    attempt_ids: set[str] = set()
    action_ids: set[str] = set()
    for item in cells:
        if not isinstance(item, dict) or set(item) != {
            "cell_id", "attempt_id", "action_id", "request_hash",
        }:
            raise ValueError("invalid Plan70 writing approval cell")
        try:
            UUID(item["attempt_id"])
            UUID(item["action_id"])
        except (TypeError, ValueError, AttributeError) as error:
            raise ValueError("invalid Plan70 writing approval UUID") from error
        if item["attempt_id"] in attempt_ids or item["action_id"] in action_ids:
            raise ValueError("duplicate Plan70 writing approval UUID")
        attempt_ids.add(item["attempt_id"])
        action_ids.add(item["action_id"])
        request = _cell_request(fixture, item["cell_id"], item["action_id"])
        if item["request_hash"] != canonical_hash(request):
            raise ValueError("Plan70 frozen writing request hash mismatch")
    if not all(isinstance(value.get(key), str) and value[key].strip()
               for key in ("run_id", "provider_id", "model_id")):
        raise ValueError("invalid Plan70 approved model identity")
    if (type(value.get("effective_max_input_length")) is not int
            or value["effective_max_input_length"] <= 0):
        raise ValueError("invalid Plan70 approved effective context window")
    return value


def _active_model(base_url: str) -> tuple[str, str]:
    url = base_url.rstrip("/") + "/api/models/active?scope=effective&agent_id=ai-novel-writer"
    with urlopen(url, timeout=10) as response:
        value = json.load(response)
    active = value.get("active_llm") if isinstance(value, dict) else None
    provider = active.get("provider_id") if isinstance(active, dict) else None
    model = active.get("model") if isinstance(active, dict) else None
    if not isinstance(provider, str) or not provider.strip() or not isinstance(model, str) or not model.strip():
        raise RuntimeError("missing_effective_model")
    return provider.strip(), model.strip()


def _route_base_url(route_url: str) -> str:
    parsed = urlsplit(route_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("invalid Plan70 writing route URL")
    return f"{parsed.scheme}://{parsed.netloc}"


def _request_cell(route_url: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = Request(
        route_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=WRITING_HTTP_TIMEOUT_SECONDS) as response:
            value = json.load(response)
    except HTTPError as error:
        body = error.read(4000).decode("utf-8", errors="replace")
        raise RuntimeError(f"http_{error.code}:{body}") from error
    if not isinstance(value, dict):
        raise RuntimeError("invalid_writing_transport_response")
    return value


def _validate_response(
    response: dict[str, Any], *, approval: dict[str, Any], approved_cell: dict[str, Any]
) -> dict[str, Any]:
    cell_id = approved_cell["cell_id"]
    arm = cell_id[-1]
    if (response.get("schema_version") != "plan70-writing-ab-transport/2"
            or response.get("run_id") != approval["run_id"]
            or response.get("cell_id") != cell_id
            or response.get("attempt_id") != approved_cell["attempt_id"]
            or (response.get("provider_id"), response.get("model_id")) != (
                approval["provider_id"], approval["model_id"])
            or response.get("prose_model_call_limit") != 1
            or response.get("automatic_retries") != 0):
        raise ValueError("writing transport identity or budget mismatch")
    generation = response.get("generation")
    if not isinstance(generation, dict):
        raise ValueError("missing chapter generation result")
    candidate = generation.get("candidate")
    method = generation.get("writing_method")
    if (generation.get("state") != "ready" or not isinstance(candidate, dict)
            or candidate.get("state") != "ready"
            or candidate.get("adopted_revision_id") is not None
            or not isinstance(method, dict)):
        raise ValueError("chapter candidate is not isolated and ready")
    expected_ids = ["golden-finger-writing"] if arm == "B" else []
    expected_auxiliary = 1 if arm == "B" else 0
    if (method.get("selected_ids") != expected_ids
            or method.get("auxiliary_calls") != expected_auxiliary
            or bool(method.get("semantic_enabled")) != (arm == "B")):
        raise ValueError("chapter method result does not match the A/B arm")
    details = method.get("details")
    method_items = details.get("methods") if isinstance(details, dict) else None
    expected_methods = approval["methods"] if arm == "B" else approval["methods"][:1]
    observed_methods = [
        {
            "skill_id": item.get("skill_id"),
            "version": item.get("version"),
            "body_sha256": item.get("body_sha256"),
        }
        for item in method_items
    ] if isinstance(method_items, list) else None
    if observed_methods != expected_methods:
        raise ValueError("chapter method bytes or versions changed")
    if (generation.get("requested_provider_id"), generation.get("requested_model_id")) != (
            approval["provider_id"], approval["model_id"]):
        raise ValueError("requested chapter model changed")
    actual = (generation.get("actual_provider_id"), generation.get("actual_model_id"))
    if actual != (approval["provider_id"], approval["model_id"]):
        evidence = generation.get("model_evidence")
        expected_identity = {
            "provider_id": approval["provider_id"], "model_id": approval["model_id"]
        }
        if (actual != (None, None) or not isinstance(evidence, dict)
                or evidence.get("schema_version") != "model-execution-evidence/2"
                or evidence.get("status") != "not_exposed"
                or evidence.get("reported_actual") is not None
                or evidence.get("preflight_effective") is None
                or evidence.get("postflight_effective") is None
                or {key: evidence["preflight_effective"].get(key) for key in expected_identity}
                    != expected_identity
                or {key: evidence["postflight_effective"].get(key) for key in expected_identity}
                    != expected_identity):
            raise ValueError("actual chapter model changed")
    content = candidate.get("content_markdown")
    visible = candidate.get("visible_character_count")
    if not isinstance(content, str) or not content.strip() or type(visible) is not int:
        raise ValueError("chapter candidate content missing")
    if visible_character_count(content) != visible:
        raise ValueError("chapter candidate visible count mismatch")
    if visible < 2000:
        raise ValueError("chapter candidate is shorter than 2000 visible characters")
    if (generation.get("requested_visible_character_count") != 2500
            or generation.get("minimum_visible_character_count") != 2125
            or generation.get("maximum_visible_character_count") != 2875
            or not 2125 <= visible <= 2875):
        raise ValueError("chapter candidate violates frozen software length window")
    evidence = response.get("input_evidence")
    if (not isinstance(evidence, dict)
            or evidence.get("schema_version") != "plan70-writing-input/1"
            or evidence.get("observation_boundary") != "project_frozen_input_before_ctx_chat"
            or evidence.get("provider_receipt_proven") is not False
            or evidence.get("brief_version") != 1
            or not isinstance(evidence.get("sources"), dict)
            or canonical_hash(evidence["sources"]) != evidence.get("source_hash")):
        raise ValueError("missing or invalid frozen input evidence")
    return {
        "novel_id": response.get("novel_id"),
        "document_id": response.get("document_id"),
        "job_id": generation.get("id"),
        "candidate_id": candidate.get("id"),
        "candidate_state": candidate.get("state"),
        "adopted_revision_id": candidate.get("adopted_revision_id"),
        "visible_character_count": visible,
        "content_sha256": _sha256(content),
        "content_markdown": content,
        "requested_provider_id": generation.get("requested_provider_id"),
        "requested_model_id": generation.get("requested_model_id"),
        "actual_provider_id": generation.get("actual_provider_id"),
        "actual_model_id": generation.get("actual_model_id"),
        "writing_method": method,
        "validation_state": generation.get("validation_state"),
        "target_status": "TARGET_MET" if visible >= 2500 else "TARGET_MISSED",
        "input_evidence": evidence,
        "model_evidence": generation.get("model_evidence"),
    }


def _resume_checkpoint(output, review_path, fixture, approval, route_url):
    raw = output.read_bytes()
    report = json.loads(raw)
    review = json.loads(review_path.read_bytes())
    if (report.get("state") != "awaiting_review"
            or report.get("approval_sha256") != canonical_hash(approval)
            or report.get("fixture_sha256") != fixture["fixture_sha256"]
            or report.get("route_url") != route_url
            or report.get("run_id") != approval["run_id"]
            or report.get("http_requests") != 4 or report.get("prose_calls") != 4
            or report.get("auxiliary_calls") != 2):
        raise ValueError("checkpoint is not the frozen four-cell review gate")
    attempts = report.get("attempts", [])
    if len(attempts) != 8:
        raise ValueError("invalid checkpoint attempt inventory")
    for index, (attempt, cell) in enumerate(zip(attempts, approval["cells"])):
        if any(attempt.get(key) != value for key, value in cell.items()):
            raise ValueError("checkpoint attempt identity changed")
        if index < 4:
            result = attempt.get("result") or {}
            if (attempt.get("state") != "completed"
                    or not isinstance(result.get("content_markdown"), str)
                    or _sha256(result["content_markdown"]) != result.get("content_sha256")):
                raise ValueError("reviewed candidate changed")
        elif (attempt.get("state") != "planned" or attempt.get("started_at_unix_ms") is not None
              or attempt.get("result") is not None):
            raise ValueError("started attempts must never replay")
    if (review.get("schema_version") != "plan70-writing-review-receipt/1"
            or review.get("run_id") != approval["run_id"]
            or review.get("checkpoint_sha256") != _sha256(raw)
            or review.get("decision") != "continue"
            or type(review.get("major_errors")) is not int or review["major_errors"] != 0
            or type(review.get("clear_b_losses")) is not int or review["clear_b_losses"] != 0
            or not isinstance(review.get("reviewer"), str) or not review["reviewer"].strip()
            or not isinstance(review.get("signed_at"), str) or not review["signed_at"].strip()):
        raise ValueError("missing passing review bound to this checkpoint")
    # Local reviewer attestation, not a cryptographic identity signature.
    report["first_gate_review"] = review
    return report


def run(*, output: Path, **kwargs) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    # A stable sidecar lock prevents two processes continuing the same four cells.
    with output.with_suffix(output.suffix + ".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("writing checkpoint is already in use") from error
        return _run_locked(output=output, **kwargs)


def _run_locked(
    *, fixture: dict[str, Any], approval: dict[str, Any], route_url: str,
    output: Path, active_model: Callable[[str], tuple[str, str]] = _active_model,
    request_cell: Callable[[str, dict[str, Any]], dict[str, Any]] = _request_cell,
    review_path: Path | None = None,
) -> int:
    if fixture["schema_version"] != "plan70-writing-ab-cases/2":
        raise ValueError("legacy fixture is read-only; use v2 for new evaluation")
    resumed = None
    if review_path is not None:
        resumed = _resume_checkpoint(output, review_path, fixture, approval, route_url)
    elif output.exists():
        raise ValueError("output checkpoint already exists; started attempts must never replay")
    expected_model = (approval["provider_id"], approval["model_id"])
    base_url = _route_base_url(route_url)
    if active_model(base_url) != expected_model:
        raise ValueError("effective model does not match the writing approval")
    attempts = []
    for item in approval["cells"]:
        attempts.append({
            **item,
            "pair_id": item["cell_id"][:3],
            "arm": item["cell_id"][-1],
            "state": "planned",
            "started_at_unix_ms": None,
            "completed_at_unix_ms": None,
            "duration_ms": None,
            "result": None,
            "error_code": None,
            "error_detail": None,
        })
    report = {
        "schema_version": "plan70-real-writing-ab/1",
        "run_id": approval["run_id"],
        "fixture_sha256": fixture["fixture_sha256"],
        "approval_sha256": canonical_hash(approval),
        "comparison_contract": approval["comparison_contract"],
        "route_url": route_url,
        "agent_id": "ai-novel-writer",
        "effective_model": {
            "provider_id": approval["provider_id"], "model_id": approval["model_id"]
        },
        "target_visible_character_count": 2500,
        "minimum_visible_character_count": 2000,
        "maximum_cells": 8,
        "maximum_auxiliary_calls": 4,
        "maximum_prose_calls": 8,
        "automatic_retries": 0,
        "formal_novel_mutation": False,
        "assistant_console_used": False,
        "state": "prepared",
        "stop_reason": None,
        "http_requests": 0,
        "auxiliary_calls": 0,
        "prose_calls": 0,
        "attempts": attempts,
    }
    if resumed is not None:
        report = resumed
    _atomic_json(output, report)
    for index, approved_cell in enumerate(approval["cells"]):
        if resumed is not None and index < 4:
            continue
        attempt = report["attempts"][index]
        action_id = approved_cell["action_id"]
        cell_request = _cell_request(fixture, approved_cell["cell_id"], action_id)
        payload = {
            "run_id": approval["run_id"],
            "cell_id": approved_cell["cell_id"],
            "attempt_id": approved_cell["attempt_id"],
            "request": cell_request,
        }
        if canonical_hash(cell_request) != approved_cell["request_hash"]:
            raise ValueError("writing request changed after checkpoint preparation")
        before = active_model(base_url)
        if before != expected_model:
            report["state"] = "stopped"
            report["stop_reason"] = "model_identity_changed_before_cell"
            _atomic_json(output, report)
            return EXIT_STOPPED
        attempt["state"] = "started"
        attempt["started_at_unix_ms"] = int(time.time() * 1000)
        report["state"] = "running"
        report["http_requests"] += 1
        report["prose_calls"] += 1
        if approved_cell["cell_id"].endswith("-B"):
            report["auxiliary_calls"] += 1
        _atomic_json(output, report)
        started = time.monotonic()
        try:
            response = request_cell(route_url, payload)
            after = active_model(base_url)
            if after != expected_model:
                raise ValueError("model identity changed after cell")
            result = _validate_response(
                response, approval=approval, approved_cell=approved_cell
            )
            expected_sources = {key: cell_request["seed"][key] for key in (
                "description", "background", "main_plot", "idea",
                "expectation_text", "outline_text", "forbidden_text",
            )}
            if result["input_evidence"]["sources"] != expected_sources:
                raise ValueError("frozen story sources differ from approved baseline")
        except Exception as error:
            attempt["state"] = "failed"
            attempt["duration_ms"] = int((time.monotonic() - started) * 1000)
            attempt["completed_at_unix_ms"] = int(time.time() * 1000)
            attempt["error_code"] = type(error).__name__
            attempt["error_detail"] = str(error)[:2000]
            report["state"] = "stopped"
            report["stop_reason"] = f"cell_failed:{approved_cell['cell_id']}:{type(error).__name__}"
            _atomic_json(output, report)
            return EXIT_STOPPED
        attempt["state"] = "completed"
        attempt["duration_ms"] = int((time.monotonic() - started) * 1000)
        attempt["completed_at_unix_ms"] = int(time.time() * 1000)
        attempt["result"] = result
        _atomic_json(output, report)
        print(
            f"{approved_cell['cell_id']} completed chars={result['visible_character_count']}",
            flush=True,
        )
        if index == 3:
            report["state"] = "awaiting_review"
            _atomic_json(output, report)
            return EXIT_AWAITING_REVIEW
    report["state"] = "complete"
    _atomic_json(output, report)
    return EXIT_COMPLETE


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--prepare-approval", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--provider-id")
    parser.add_argument("--model-id")
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--route-url")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--review", type=Path, help="signed first-gate review; continue only remaining four cells")
    parser.add_argument("--export-baselines", type=Path)
    args = parser.parse_args()
    try:
        fixture = _load_fixture(args.fixture.resolve())
        if args.export_baselines:
            if any((args.prepare_approval, args.approval, args.route_url, args.output, args.review)):
                raise ValueError("baseline export cannot run evaluation")
            if args.export_baselines.exists():
                raise ValueError("baseline output already exists")
            _atomic_json(args.export_baselines, review_baselines(fixture))
            return EXIT_COMPLETE
        if args.prepare_approval is not None:
            if args.approval or args.route_url or args.output or args.review:
                raise ValueError("approval preparation cannot run evaluation")
            approval = build_approval(
                fixture,
                run_id=args.run_id or "",
                provider_id=args.provider_id or "",
                model_id=args.model_id or "",
            )
            target = args.prepare_approval.resolve()
            if target.exists():
                raise ValueError("approval output already exists")
            _atomic_json(target, approval)
            return EXIT_COMPLETE
        if not args.approval or not args.route_url or not args.output:
            raise ValueError("--approval, --route-url and --output are required")
        approval = _load_approval(args.approval.resolve(), fixture)
        return run(
            fixture=fixture,
            approval=approval,
            route_url=args.route_url,
            output=args.output.resolve(),
            review_path=args.review.resolve() if args.review else None,
        )
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(f"preflight_failed:{type(error).__name__}:{error}", file=sys.stderr)
        return EXIT_PREFLIGHT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
