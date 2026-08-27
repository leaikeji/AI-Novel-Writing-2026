#!/usr/bin/env python3
"""Run the frozen writing A/B experiment through the bounded PawApp API."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.writing_eval_contract import (  # noqa: E402
    ACTUAL_MODEL_POLICY,
    CANDIDATE_OVERLAY_SHA256,
    EXPERIMENT_ID,
    MANIFEST_SHA256,
    MODEL_EVIDENCE_CONTRACT_VERSION,
    PROMPT_CONTRACT_VERSION,
    RUBRIC_SHA256,
    SCHEMA_VERSION,
    SKILL_SELECTION_ENFORCEMENT,
    SOURCE_SUITE_SHA256,
    STREAM_DIAGNOSTIC_CONTRACT_VERSION,
    TOOL_POLICY_ENFORCEMENT,
    build_sample,
    experiment_contract,
    sha256_text,
)


DEFAULT_API_BASE = "http://127.0.0.1:18088/api/ai-novel-world-2026"
DEFAULT_EVIDENCE_ROOT = (
    ROOT
    / "docs"
    / "开发文档"
    / "证据"
    / "悬疑刑侦写作A-B-2026-08-27"
    / "runs"
)
RUN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
MAX_HTTP_ERROR_BODY_BYTES = 64 * 1024


class RunnerError(RuntimeError):
    """Fail closed without silently rerunning a paid model attempt."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _http_error_evidence(error: httpx.HTTPStatusError) -> dict[str, Any]:
    response = error.response
    payload: dict[str, Any] = {
        "http_status": response.status_code,
        "response_content_type": response.headers.get("content-type", ""),
        "response_body_bytes": len(response.content),
        "response_body_sha256": _sha256_bytes(response.content),
    }
    if len(response.content) > MAX_HTTP_ERROR_BODY_BYTES:
        payload["response_body_truncated"] = True
        return payload
    try:
        response_json = response.json()
    except (ValueError, UnicodeDecodeError):
        return payload
    if isinstance(response_json, (dict, list)):
        payload["response_json"] = response_json
    return payload


def _safe_directory(path: Path) -> None:
    if path.exists() and (path.is_symlink() or not path.is_dir()):
        raise RunnerError(f"证据路径不是安全目录：{path}")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError as error:
        raise RunnerError(f"无法收紧证据目录权限：{path}") from error


def _atomic_write(path: Path, payload: bytes) -> None:
    _safe_directory(path.parent)
    temporary = path.with_name(
        f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}"
    )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(temporary, flags, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            descriptor = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
        raise


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8") + b"\n"
    _atomic_write(path, serialized)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RunnerError(f"证据 JSON 无法读取：{path}") from error
    if not isinstance(payload, dict):
        raise RunnerError(f"证据 JSON 顶层必须是对象：{path}")
    return payload


class _RunLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.descriptor = -1

    def __enter__(self) -> "_RunLock":
        _safe_directory(self.path.parent)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        self.descriptor = os.open(self.path, flags, 0o600)
        try:
            fcntl.flock(self.descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            os.close(self.descriptor)
            self.descriptor = -1
            raise RunnerError("同一研究 run 已有进程在执行") from error
        os.ftruncate(self.descriptor, 0)
        os.write(self.descriptor, f"pid={os.getpid()}\n".encode("ascii"))
        os.fsync(self.descriptor)
        return self

    def __exit__(self, *args: object) -> None:
        if self.descriptor >= 0:
            fcntl.flock(self.descriptor, fcntl.LOCK_UN)
            os.close(self.descriptor)
            self.descriptor = -1


def _local_contract() -> dict[str, Any]:
    contract = experiment_contract(EXPERIMENT_ID)
    cases_path = ROOT / "tests" / "fixtures" / "writing_skill_eval" / "cases.json"
    overlay_path = (
        ROOT
        / "docs"
        / "开发文档"
        / "证据"
        / "悬疑刑侦写作A-B-2026-08-27"
        / "candidate-overlay.md"
    )
    manifest_path = overlay_path.parent / "manifest.json"
    rubric_path = overlay_path.parent / "rubric.md"
    try:
        cases_sha = _sha256_bytes(cases_path.read_bytes())
        overlay_sha = _sha256_bytes(overlay_path.read_bytes())
        manifest_sha = _sha256_bytes(manifest_path.read_bytes())
        rubric_sha = _sha256_bytes(rubric_path.read_bytes())
    except OSError as error:
        raise RunnerError("冻结评测输入不可读") from error
    if cases_sha != SOURCE_SUITE_SHA256:
        raise RunnerError("CONTRACT_HASH_MISMATCH: cases.json")
    if overlay_sha != CANDIDATE_OVERLAY_SHA256:
        raise RunnerError("CONTRACT_HASH_MISMATCH: candidate-overlay.md")
    if manifest_sha != MANIFEST_SHA256:
        raise RunnerError("CONTRACT_HASH_MISMATCH: manifest.json")
    if rubric_sha != RUBRIC_SHA256:
        raise RunnerError("CONTRACT_HASH_MISMATCH: rubric.md")
    return contract


def _validate_server_contract(server: dict[str, Any], local: dict[str, Any]) -> None:
    protected = (
        "schema_version",
        "experiment_id",
        "rights_basis",
        "source_suite_sha256",
        "candidate_overlay_sha256",
        "manifest_sha256",
        "rubric_sha256",
        "generation_contract",
        "prompt_contract",
        "stream_diagnostic_contract",
        "model_evidence_contract",
        "actual_model_policy",
        "skill_selection_enforcement",
        "tool_policy_enforcement",
        "sample_ids",
        "case_ids",
        "blind_pairs",
        "same_model_required",
        "attempts_per_variant",
        "server_persistence",
        "arbitrary_prompt_allowed",
    )
    mismatches = [field for field in protected if server.get(field) != local.get(field)]
    if mismatches:
        raise RunnerError(
            "SERVER_CONTRACT_MISMATCH: " + ", ".join(sorted(mismatches))
        )


def _validate_result(result: dict[str, Any], sample_id: str) -> None:
    sample = build_sample(EXPERIMENT_ID, sample_id)
    expected = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": EXPERIMENT_ID,
        "sample_id": sample.sample_id,
        "case_id": sample.case_id,
        "variant": sample.variant,
        "attempt": sample.attempt,
        "source_suite_sha256": SOURCE_SUITE_SHA256,
        "candidate_overlay_sha256": CANDIDATE_OVERLAY_SHA256,
        "manifest_sha256": MANIFEST_SHA256,
        "rubric_sha256": RUBRIC_SHA256,
        "prompt_contract": PROMPT_CONTRACT_VERSION,
        "base_prompt_sha256": sha256_text(sample.base_prompt),
        "prompt_sha256": sha256_text(sample.prompt),
        "server_persistence": "none",
    }
    mismatches = [field for field, value in expected.items() if result.get(field) != value]
    if mismatches:
        raise RunnerError("RESULT_IDENTITY_MISMATCH: " + ", ".join(mismatches))
    output_text = result.get("output_text")
    if not isinstance(output_text, str) or not output_text.strip():
        raise RunnerError("RESULT_OUTPUT_MISSING")
    if result.get("output_sha256") != sha256_text(output_text):
        raise RunnerError("RESULT_OUTPUT_HASH_MISMATCH")
    requested = result.get("requested_model")
    postflight = result.get("postflight_model")
    actual = result.get("actual_model")

    def model_identity(value: Any) -> tuple[str, str] | None:
        if not isinstance(value, dict):
            return None
        provider_id = value.get("provider_id")
        model_id = value.get("model_id")
        if (
            not isinstance(provider_id, str)
            or not provider_id.strip()
            or not isinstance(model_id, str)
            or not model_id.strip()
        ):
            return None
        return provider_id, model_id

    requested_identity = model_identity(requested)
    postflight_identity = model_identity(postflight)
    if requested_identity is None or postflight_identity is None:
        raise RunnerError("RESULT_MODEL_EVIDENCE_MISSING")
    if requested_identity != postflight_identity:
        raise RunnerError("RESULT_MODEL_MISMATCH")
    model_evidence = result.get("model_evidence")
    if (
        not isinstance(model_evidence, dict)
        or model_evidence.get("contract") != MODEL_EVIDENCE_CONTRACT_VERSION
        or model_evidence.get("actual_model_policy") != ACTUAL_MODEL_POLICY
        or model_evidence.get("effective_model_pre_post_match") is not True
        or model_evidence.get("private_usage_buffer_used") is not False
    ):
        raise RunnerError("RESULT_MODEL_EVIDENCE_INVALID")
    actual_status = model_evidence.get("actual_model_status")
    usage_status = model_evidence.get("usage_status")
    if actual_status == "not_exposed" and usage_status == "not_exposed":
        if actual is not None or result.get("usage") is not None:
            raise RunnerError("RESULT_MODEL_EVIDENCE_INVALID")
    elif (
        actual_status == "verified_from_provider_usage"
        and usage_status == "exposed"
    ):
        usage = result.get("usage")
        actual_identity = model_identity(actual)
        if actual_identity is None or not isinstance(usage, dict):
            raise RunnerError("RESULT_MODEL_EVIDENCE_MISSING")
        if requested_identity != actual_identity:
            raise RunnerError("RESULT_MODEL_MISMATCH")
        token_values = [
            usage.get(name)
            for name in ("prompt_tokens", "completion_tokens", "total_tokens")
        ]
        if any(
            value is not None and (type(value) is not int or value < 0)
            for value in token_values
        ) or all(value is None for value in token_values):
            raise RunnerError("RESULT_MODEL_EVIDENCE_INVALID")
    else:
        raise RunnerError("RESULT_MODEL_EVIDENCE_INVALID")
    diagnostics = result.get("stream_diagnostics")
    if (
        not isinstance(diagnostics, dict)
        or diagnostics.get("contract") != STREAM_DIAGNOSTIC_CONTRACT_VERSION
        or diagnostics.get("content_recorded") is not False
        or diagnostics.get("stream_completed") is not True
    ):
        raise RunnerError("RESULT_STREAM_DIAGNOSTICS_INVALID")
    if result.get("tool_policy_enforcement") != TOOL_POLICY_ENFORCEMENT:
        raise RunnerError("RESULT_TOOL_POLICY_EVIDENCE_INVALID")
    if result.get("skill_selection_enforcement") != SKILL_SELECTION_ENFORCEMENT:
        raise RunnerError("RESULT_SKILL_SELECTION_EVIDENCE_INVALID")


def _terminal_result_valid(sample_dir: Path, sample_id: str) -> bool:
    result_path = sample_dir / "result.json"
    output_path = sample_dir / "output.txt"
    prompt_path = sample_dir / "prompt.txt"
    if not (result_path.is_file() and output_path.is_file() and prompt_path.is_file()):
        return False
    result = _read_json(result_path)
    _validate_result(result, sample_id)
    sample = build_sample(EXPERIMENT_ID, sample_id)
    if prompt_path.read_text(encoding="utf-8") != sample.prompt:
        raise RunnerError(f"PROMPT_HASH_MISMATCH: {sample_id}")
    if output_path.read_text(encoding="utf-8") != result["output_text"]:
        raise RunnerError(f"RESULT_OUTPUT_HASH_MISMATCH: {sample_id}")
    return True


def _blind_markdown(result: dict[str, Any]) -> str:
    checks = result["deterministic_checks"]
    return (
        "---\n"
        f"sample_id: {result['sample_id']}\n"
        f"case_id: {result['case_id']}\n"
        f"output_sha256: {result['output_sha256']}\n"
        f"non_whitespace_chars: {checks['non_whitespace_chars']}\n"
        "---\n\n"
        f"{result['output_text'].strip()}\n"
    )


def _save_result(
    run_dir: Path,
    result: dict[str, Any],
    *,
    dispatch_started_at: str | None = None,
    client_duration_ms: int | None = None,
) -> None:
    sample_id = str(result["sample_id"])
    sample = build_sample(EXPERIMENT_ID, sample_id)
    sample_dir = run_dir / "samples" / sample_id
    _safe_directory(sample_dir)
    _atomic_write(sample_dir / "prompt.txt", sample.prompt.encode("utf-8"))
    _atomic_write(
        sample_dir / "output.txt", str(result["output_text"]).encode("utf-8")
    )
    _write_json(sample_dir / "hard-gates.json", result["deterministic_checks"])
    _write_json(sample_dir / "result.json", result)
    _atomic_write(
        run_dir / "blind-samples" / f"{sample_id}.md",
        _blind_markdown(result).encode("utf-8"),
    )
    dispatch: dict[str, Any] = {
        "state": "received",
        "sample_id": sample_id,
        "session_id": result["session_id"],
        "output_sha256": result["output_sha256"],
    }
    if dispatch_started_at is not None:
        dispatch["dispatch_started_at"] = dispatch_started_at
    if client_duration_ms is not None:
        dispatch["client_duration_ms"] = client_duration_ms
    _write_json(sample_dir / "dispatch.json", dispatch)


def _plan_payload(run_id: str, contract: dict[str, Any]) -> dict[str, Any]:
    samples = []
    for sample_id in contract["sample_ids"]:
        sample = build_sample(EXPERIMENT_ID, sample_id)
        samples.append(
            {
                "sample_id": sample.sample_id,
                "case_id": sample.case_id,
                "variant": sample.variant,
                "attempt": sample.attempt,
                "base_prompt_sha256": sha256_text(sample.base_prompt),
                "prompt_sha256": sha256_text(sample.prompt),
            }
        )
    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "experiment_id": EXPERIMENT_ID,
        "execution": "strict-serial",
        "automatic_retry": False,
        "samples": samples,
    }


def _run_directory(evidence_root: Path, run_id: str) -> Path:
    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise RunnerError("run-id 只能使用小写字母、数字、点、短横线和下划线")
    root = evidence_root.resolve()
    _safe_directory(root)
    run_dir = root / run_id
    if run_dir.exists() and run_dir.is_symlink():
        raise RunnerError("run 目录不能是符号链接")
    return run_dir


def command_verify_contract(_: argparse.Namespace) -> int:
    contract = _local_contract()
    print(
        json.dumps(
            {
                "status": "ok",
                "experiment_id": contract["experiment_id"],
                "sample_count": len(contract["sample_ids"]),
                "source_suite_sha256": contract["source_suite_sha256"],
                "candidate_overlay_sha256": contract[
                    "candidate_overlay_sha256"
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0


def command_run(args: argparse.Namespace) -> int:
    if not args.acknowledge_model_cost:
        raise RunnerError("run 必须显式传入 --acknowledge-model-cost")
    local_contract = _local_contract()
    run_dir = _run_directory(args.evidence_root, args.run_id)
    if run_dir.exists() and not args.resume:
        raise RunnerError("run 已存在；继续时必须显式传入 --resume")
    _safe_directory(run_dir)
    with _RunLock(run_dir / "lock"):
        plan_path = run_dir / "plan.json"
        plan = _plan_payload(args.run_id, local_contract)
        if plan_path.exists():
            if _read_json(plan_path) != plan:
                raise RunnerError("RUN_PLAN_MISMATCH")
        else:
            _write_json(plan_path, plan)

        headers = {"X-AI-Novel-Writing-Eval": EXPERIMENT_ID}
        timeout = httpx.Timeout(args.timeout_seconds)
        with httpx.Client(base_url=args.api_base, headers=headers, timeout=timeout) as client:
            response = client.get(f"/research/writing-evaluations/{EXPERIMENT_ID}")
            response.raise_for_status()
            server_contract = response.json()
            _validate_server_contract(server_contract, local_contract)

            requested_samples = args.sample or list(local_contract["sample_ids"])
            run_model: tuple[str, str] | None = None
            completed = 0
            failed = 0
            for sample_id in requested_samples:
                sample_dir = run_dir / "samples" / sample_id
                if _terminal_result_valid(sample_dir, sample_id):
                    existing = _read_json(sample_dir / "result.json")
                    requested = existing["requested_model"]
                    existing_model = (
                        str(requested["provider_id"]),
                        str(requested["model_id"]),
                    )
                    if run_model is None:
                        run_model = existing_model
                    elif run_model != existing_model:
                        raise RunnerError("MODEL_DRIFT")
                    completed += 1
                    continue
                dispatch_path = sample_dir / "dispatch.json"
                failure_path = sample_dir / "failure.json"
                if dispatch_path.exists() or failure_path.exists():
                    raise RunnerError(
                        f"AMBIGUOUS_OR_FAILED_ATTEMPT: {sample_id}; 不自动重试"
                    )
                _safe_directory(sample_dir)
                sample = build_sample(EXPERIMENT_ID, sample_id)
                dispatch_started_at = _utc_now_iso()
                dispatch_started_monotonic = time.monotonic()
                _write_json(
                    dispatch_path,
                    {
                        "state": "dispatching",
                        "sample_id": sample_id,
                        "prompt_sha256": sha256_text(sample.prompt),
                        "dispatch_started_at": dispatch_started_at,
                    },
                )
                try:
                    result_response = client.post(
                        f"/research/writing-evaluations/{EXPERIMENT_ID}/samples/"
                        f"{sample_id}/generate"
                    )
                    result_response.raise_for_status()
                    result = result_response.json()
                    if not isinstance(result, dict):
                        raise RunnerError("RESULT_ENVELOPE_INVALID")
                    _validate_result(result, sample_id)
                    requested = result["requested_model"]
                    current_model = (
                        str(requested["provider_id"]),
                        str(requested["model_id"]),
                    )
                    if run_model is None:
                        run_model = current_model
                    elif run_model != current_model:
                        raise RunnerError("MODEL_DRIFT")
                    _save_result(
                        run_dir,
                        result,
                        dispatch_started_at=dispatch_started_at,
                        client_duration_ms=max(
                            0,
                            round(
                                (time.monotonic() - dispatch_started_monotonic)
                                * 1000
                            ),
                        ),
                    )
                    completed += 1
                except Exception as error:
                    failed += 1
                    failure: dict[str, Any] = {
                        "state": "failed",
                        "sample_id": sample_id,
                        "error_class": type(error).__name__,
                        "message": str(error),
                        "dispatch_started_at": dispatch_started_at,
                        "failed_at": _utc_now_iso(),
                        "client_duration_ms": max(
                            0,
                            round(
                                (time.monotonic() - dispatch_started_monotonic)
                                * 1000
                            ),
                        ),
                        "automatic_retry": False,
                    }
                    if isinstance(error, httpx.HTTPStatusError):
                        failure.update(_http_error_evidence(error))
                    _write_json(
                        failure_path,
                        failure,
                    )
                    break
        _write_json(
            run_dir / "summary.json",
            {
                "run_id": args.run_id,
                "experiment_id": EXPERIMENT_ID,
                "completed": completed,
                "failed": failed,
                "requested_sample_count": len(requested_samples),
                "complete": failed == 0 and completed == len(requested_samples),
            },
        )
    return 0 if failed == 0 else 2


def command_status(args: argparse.Namespace) -> int:
    run_dir = _run_directory(args.evidence_root, args.run_id)
    summary_path = run_dir / "summary.json"
    if not summary_path.is_file():
        raise RunnerError("run 尚无 summary.json")
    print(json.dumps(_read_json(summary_path), ensure_ascii=False, indent=2))
    return 0


def command_verify(args: argparse.Namespace) -> int:
    local_contract = _local_contract()
    run_dir = _run_directory(args.evidence_root, args.run_id)
    plan = _read_json(run_dir / "plan.json")
    if plan != _plan_payload(args.run_id, local_contract):
        raise RunnerError("RUN_PLAN_MISMATCH")
    valid: list[str] = []
    incomplete: list[str] = []
    models: set[tuple[str, str]] = set()
    for sample_id in local_contract["sample_ids"]:
        sample_dir = run_dir / "samples" / sample_id
        if _terminal_result_valid(sample_dir, sample_id):
            valid.append(sample_id)
            result = _read_json(sample_dir / "result.json")
            requested = result["requested_model"]
            models.add(
                (
                    str(requested["provider_id"]),
                    str(requested["model_id"]),
                )
            )
        else:
            incomplete.append(sample_id)
    if len(models) > 1:
        raise RunnerError("MODEL_DRIFT")
    print(
        json.dumps(
            {"valid": valid, "incomplete": incomplete},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not incomplete else 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify_contract = subparsers.add_parser("verify-contract")
    verify_contract.set_defaults(handler=command_verify_contract)

    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--run-id", required=True)
    shared.add_argument(
        "--evidence-root", type=Path, default=DEFAULT_EVIDENCE_ROOT
    )

    run = subparsers.add_parser("run", parents=[shared])
    run.add_argument("--api-base", default=DEFAULT_API_BASE)
    run.add_argument("--sample", action="append", choices=experiment_contract(EXPERIMENT_ID)["sample_ids"])
    run.add_argument("--resume", action="store_true")
    run.add_argument("--acknowledge-model-cost", action="store_true")
    run.add_argument("--timeout-seconds", type=float, default=620.0)
    run.set_defaults(handler=command_run)

    status_parser = subparsers.add_parser("status", parents=[shared])
    status_parser.set_defaults(handler=command_status)
    verify = subparsers.add_parser("verify", parents=[shared])
    verify.set_defaults(handler=command_verify)
    return parser


def main() -> int:
    try:
        args = _parser().parse_args()
        if hasattr(args, "timeout_seconds") and args.timeout_seconds <= 0:
            raise RunnerError("timeout-seconds 必须大于0")
        return int(args.handler(args))
    except (RunnerError, httpx.HTTPError) as error:
        print(f"writing-eval: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
