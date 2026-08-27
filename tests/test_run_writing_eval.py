from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
import stat

import pytest

from scripts import run_writing_eval as runner


class _Response:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return copy.deepcopy(self._payload)


def _valid_result(
    sample_id: str, *, actual_exposed: bool = True
) -> dict[str, object]:
    sample = runner.build_sample(runner.EXPERIMENT_ID, sample_id)
    output_text = f"{sample.case_id} 的冻结测试输出。"
    model = {
        "provider_id": "provider-a",
        "model_id": "model-a",
        "source": "provider-usage",
        "agent_id": runner.EXPERIMENT_ID,
        "effective_max_input_length": 131_072,
    }
    return {
        "schema_version": runner.SCHEMA_VERSION,
        "state": "generated",
        "experiment_id": runner.EXPERIMENT_ID,
        "sample_id": sample.sample_id,
        "case_id": sample.case_id,
        "variant": sample.variant,
        "attempt": sample.attempt,
        "source_suite_sha256": runner.SOURCE_SUITE_SHA256,
        "candidate_overlay_sha256": runner.CANDIDATE_OVERLAY_SHA256,
        "manifest_sha256": runner.MANIFEST_SHA256,
        "rubric_sha256": runner.RUBRIC_SHA256,
        "prompt_contract": runner.PROMPT_CONTRACT_VERSION,
        "output_purity_contract": runner.OUTPUT_PURITY_CONTRACT_VERSION,
        "base_prompt_sha256": runner.sha256_text(sample.base_prompt),
        "prompt_sha256": runner.sha256_text(sample.prompt),
        "requested_model": dict(model, source="effective-model-api"),
        "postflight_model": dict(model, source="effective-model-api"),
        "actual_model": model if actual_exposed else None,
        "usage": (
            {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
            }
            if actual_exposed
            else None
        ),
        "model_evidence": {
            "contract": "writing-eval-effective-model-pre-post-v1",
            "actual_model_policy": "provider_usage_optional_not_exposed_allowed",
            "effective_model_pre_post_match": True,
            "actual_model_status": (
                "verified_from_provider_usage" if actual_exposed else "not_exposed"
            ),
            "usage_status": "exposed" if actual_exposed else "not_exposed",
            "private_usage_buffer_used": False,
        },
        "session_id": f"eval-session:{sample_id}",
        "skill_selection_enforcement": "requested_via_pawapp_context_parameter",
        "tool_policy_enforcement": "prompt_only",
        "stream_diagnostics": {
            "contract": "writing-eval-stream-diagnostics-v1",
            "content_recorded": False,
            "stream_completed": True,
            "event_count": 1,
            "first_event_elapsed_ms": 10,
            "last_event_elapsed_ms": 20,
            "event_type_counts": {"model_response": 1},
            "message_role_counts": {"assistant": 1},
            "message_type_counts": {"message": 1},
            "content_part_type_counts": {"output_text": 1},
        },
        "output_text": output_text,
        "output_sha256": runner.sha256_text(output_text),
        "deterministic_checks": runner.deterministic_output_checks(
            sample.case_id, output_text
        ),
        "server_persistence": "none",
    }


def _args(
    evidence_root: Path,
    *,
    run_id: str = "rr-test",
    sample: list[str] | None = None,
    resume: bool = False,
    acknowledge_model_cost: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        evidence_root=evidence_root,
        run_id=run_id,
        sample=sample,
        resume=resume,
        acknowledge_model_cost=acknowledge_model_cost,
        api_base="http://qwenpaw.invalid/api/ai-novel-world-2026",
        timeout_seconds=1.0,
    )


def _install_httpx_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    result: dict[str, object] | None = None,
    post_error: Exception | None = None,
) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []
    contract = runner.experiment_contract(runner.EXPERIMENT_ID)

    class Client:
        def __init__(self, **_: object) -> None:
            pass

        def __enter__(self) -> "Client":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def get(self, path: str) -> _Response:
            calls.append(("GET", path))
            return _Response(contract)

        def post(self, path: str) -> _Response:
            calls.append(("POST", path))
            if post_error is not None:
                raise post_error
            assert result is not None
            return _Response(result)

    monkeypatch.setattr(runner.httpx, "Client", Client)
    return calls


def test_cli_rejects_unregistered_sample_and_invalid_run_id(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        runner._parser().parse_args(
            [
                "run",
                "--run-id",
                "rr-test",
                "--sample",
                "X99",
                "--acknowledge-model-cost",
            ]
        )

    with pytest.raises(runner.RunnerError, match="run-id"):
        runner._run_directory(tmp_path / "evidence", "../escape")
    assert not (tmp_path / "escape").exists()


def test_run_requires_explicit_model_cost_acknowledgement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_httpx_client(monkeypatch, result=_valid_result("X01"))

    with pytest.raises(runner.RunnerError, match="acknowledge-model-cost"):
        runner.command_run(
            _args(
                tmp_path / "evidence",
                sample=["X01"],
                acknowledge_model_cost=False,
            )
        )

    assert calls == []
    assert not (tmp_path / "evidence").exists()


def test_local_contract_hash_drift_fails_before_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_httpx_client(monkeypatch, result=_valid_result("X01"))
    monkeypatch.setattr(runner, "SOURCE_SUITE_SHA256", "0" * 64)

    with pytest.raises(runner.RunnerError, match="CONTRACT_HASH_MISMATCH: cases.json"):
        runner.command_run(_args(tmp_path / "evidence", sample=["X01"]))

    assert calls == []


def test_atomic_write_uses_private_permissions_and_preserves_destination_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "evidence" / "result.json"
    runner._atomic_write(destination, b"first\n")

    assert destination.read_bytes() == b"first\n"
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert stat.S_IMODE(destination.parent.stat().st_mode) == 0o700

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise OSError("injected replace failure")

    monkeypatch.setattr(runner.os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected replace failure"):
        runner._atomic_write(destination, b"second\n")

    assert destination.read_bytes() == b"first\n"
    assert list(destination.parent.glob(f".{destination.name}.tmp-*")) == []


def test_complete_existing_sample_is_skipped_without_post(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence_root = tmp_path / "evidence"
    run_dir = evidence_root / "rr-test"
    runner._save_result(run_dir, _valid_result("X01"))
    calls = _install_httpx_client(monkeypatch, result=_valid_result("X01"))

    exit_code = runner.command_run(
        _args(evidence_root, sample=["X01"], resume=True)
    )

    assert exit_code == 0
    assert [method for method, _path in calls] == ["GET"]
    assert runner._read_json(run_dir / "summary.json") == {
        "complete": True,
        "completed": 1,
        "experiment_id": runner.EXPERIMENT_ID,
        "failed": 0,
        "requested_sample_count": 1,
        "run_id": "rr-test",
    }


def test_failed_dispatch_is_recorded_once_and_resume_never_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence_root = tmp_path / "evidence"
    calls = _install_httpx_client(
        monkeypatch,
        post_error=RuntimeError("injected provider failure"),
    )
    args = _args(evidence_root, sample=["X01"])

    assert runner.command_run(args) == 2
    failure = runner._read_json(
        evidence_root / "rr-test" / "samples" / "X01" / "failure.json"
    )
    assert failure["automatic_retry"] is False
    assert failure["error_class"] == "RuntimeError"
    assert isinstance(failure["dispatch_started_at"], str)
    assert isinstance(failure["failed_at"], str)
    assert isinstance(failure["client_duration_ms"], int)
    assert [method for method, _path in calls].count("POST") == 1

    args.resume = True
    with pytest.raises(runner.RunnerError, match="AMBIGUOUS_OR_FAILED_ATTEMPT"):
        runner.command_run(args)
    assert [method for method, _path in calls].count("POST") == 1


def test_http_failure_preserves_bounded_server_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = runner.httpx.Request(
        "POST",
        "http://qwenpaw.invalid/api/ai-novel-world-2026/research/"
        "writing-evaluations/mystery-ab-20260827-v1/samples/X01/generate",
    )
    server_detail = {
        "detail": {
            "type": "writing_evaluation_timed_out",
            "sample_id": "X01",
            "session_id": "novel-writing-eval:test-session",
            "stream_diagnostics": {
                "content_recorded": False,
                "event_count": 4,
            },
        }
    }
    response = runner.httpx.Response(504, request=request, json=server_detail)
    error = runner.httpx.HTTPStatusError(
        "server timeout",
        request=request,
        response=response,
    )
    evidence_root = tmp_path / "evidence"
    calls = _install_httpx_client(monkeypatch, post_error=error)

    assert runner.command_run(_args(evidence_root, sample=["X01"])) == 2

    sample_dir = evidence_root / "rr-test" / "samples" / "X01"
    dispatch = runner._read_json(sample_dir / "dispatch.json")
    failure = runner._read_json(sample_dir / "failure.json")
    assert dispatch["state"] == "dispatching"
    assert isinstance(dispatch["dispatch_started_at"], str)
    assert failure["http_status"] == 504
    assert failure["response_json"] == server_detail
    assert failure["response_body_bytes"] <= runner.MAX_HTTP_ERROR_BODY_BYTES
    assert len(failure["response_body_sha256"]) == 64
    assert [method for method, _path in calls].count("POST") == 1


def test_http_failure_hashes_but_does_not_store_oversized_body(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = runner.httpx.Request(
        "POST",
        "http://qwenpaw.invalid/api/ai-novel-world-2026/research/"
        "writing-evaluations/mystery-ab-20260827-v1/samples/X01/generate",
    )
    oversized_body = b"x" * (runner.MAX_HTTP_ERROR_BODY_BYTES + 1)
    response = runner.httpx.Response(
        502,
        request=request,
        headers={"content-type": "text/plain"},
        content=oversized_body,
    )
    error = runner.httpx.HTTPStatusError(
        "server failure",
        request=request,
        response=response,
    )
    evidence_root = tmp_path / "evidence"
    _install_httpx_client(monkeypatch, post_error=error)

    assert runner.command_run(_args(evidence_root, sample=["X01"])) == 2

    failure = runner._read_json(
        evidence_root / "rr-test" / "samples" / "X01" / "failure.json"
    )
    assert failure["response_body_bytes"] == len(oversized_body)
    assert failure["response_body_sha256"] == runner._sha256_bytes(oversized_body)
    assert failure["response_body_truncated"] is True
    assert "response_json" not in failure
    assert oversized_body.decode() not in json.dumps(failure)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("schema", "RESULT_IDENTITY_MISMATCH"),
        ("identity", "RESULT_IDENTITY_MISMATCH"),
        ("model", "RESULT_MODEL_MISMATCH"),
        ("output_hash", "RESULT_OUTPUT_HASH_MISMATCH"),
    ],
)
def test_result_identity_model_and_output_hash_are_verified(
    mutation: str,
    message: str,
) -> None:
    result = _valid_result("X01")
    if mutation == "schema":
        result["schema_version"] = "1.0"
    elif mutation == "identity":
        result["case_id"] = "CF-01"
    elif mutation == "model":
        actual = result["actual_model"]
        assert isinstance(actual, dict)
        actual["model_id"] = "model-b"
    else:
        result["output_sha256"] = "f" * 64

    with pytest.raises(runner.RunnerError, match=message):
        runner._validate_result(result, "X01")


def test_result_without_public_actual_or_usage_is_valid_when_pre_post_match() -> None:
    runner._validate_result(_valid_result("X01", actual_exposed=False), "X01")


def test_result_rejects_effective_model_drift() -> None:
    result = _valid_result("X01", actual_exposed=False)
    postflight = result["postflight_model"]
    assert isinstance(postflight, dict)
    postflight["model_id"] = "model-b"

    with pytest.raises(runner.RunnerError, match="RESULT_MODEL_MISMATCH"):
        runner._validate_result(result, "X01")


def test_result_rejects_forged_deterministic_checks() -> None:
    result = _valid_result("X01")
    checks = result["deterministic_checks"]
    assert isinstance(checks, dict)
    checks["output_purity_pass"] = False

    with pytest.raises(
        runner.RunnerError, match="RESULT_DETERMINISTIC_CHECKS_MISMATCH"
    ):
        runner._validate_result(result, "X01")


def test_impure_output_is_preserved_but_rejected_before_blind_sample(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _valid_result("X01", actual_exposed=False)
    output_text = (
        "门内传来一声轻响。\n\n"
        "⟦ 合成写作评测｜已完成：锚点齐全；无下一步 ⟧"
    )
    result["output_text"] = output_text
    result["output_sha256"] = runner.sha256_text(output_text)
    result["deterministic_checks"] = runner.deterministic_output_checks(
        "SP-02", output_text
    )
    evidence_root = tmp_path / "evidence"
    _install_httpx_client(monkeypatch, result=result)

    assert runner.command_run(_args(evidence_root, sample=["X01"])) == 2

    run_dir = evidence_root / "rr-test"
    sample_dir = run_dir / "samples" / "X01"
    assert (sample_dir / "output.txt").read_text(encoding="utf-8") == output_text
    assert runner._read_json(sample_dir / "result.json")[
        "output_sha256"
    ] == runner.sha256_text(output_text)
    failure = runner._read_json(sample_dir / "failure.json")
    assert failure["failure_code"] == "output_purity_failed"
    assert failure["wrapper_flags"]["agent_status_capsule"] is True
    assert not (run_dir / "blind-samples" / "X01.md").exists()
    assert runner._read_json(run_dir / "summary.json") == {
        "complete": False,
        "completed": 0,
        "experiment_id": runner.EXPERIMENT_ID,
        "failed": 1,
        "requested_sample_count": 1,
        "run_id": "rr-test",
    }


def test_status_and_verify_report_complete_run(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    evidence_root = tmp_path / "evidence"
    run_dir = evidence_root / "rr-complete"
    contract = runner._local_contract()
    runner._write_json(
        run_dir / "plan.json",
        runner._plan_payload("rr-complete", contract),
    )
    for sample_id in contract["sample_ids"]:
        runner._save_result(run_dir, _valid_result(str(sample_id)))
    summary = {
        "run_id": "rr-complete",
        "experiment_id": runner.EXPERIMENT_ID,
        "completed": len(contract["sample_ids"]),
        "failed": 0,
        "requested_sample_count": len(contract["sample_ids"]),
        "complete": True,
    }
    runner._write_json(run_dir / "summary.json", summary)

    assert runner.command_status(
        _args(evidence_root, run_id="rr-complete")
    ) == 0
    assert json.loads(capsys.readouterr().out) == summary

    assert runner.command_verify(
        _args(evidence_root, run_id="rr-complete")
    ) == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified["valid"] == contract["sample_ids"]
    assert verified["incomplete"] == []


def test_verify_reports_incomplete_without_dispatching(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    evidence_root = tmp_path / "evidence"
    run_dir = evidence_root / "rr-incomplete"
    contract = runner._local_contract()
    runner._write_json(
        run_dir / "plan.json",
        runner._plan_payload("rr-incomplete", contract),
    )
    runner._save_result(run_dir, _valid_result("X01"))

    assert runner.command_verify(
        _args(evidence_root, run_id="rr-incomplete")
    ) == 2
    verified = json.loads(capsys.readouterr().out)
    assert verified["valid"] == ["X01"]
    assert "X02" in verified["incomplete"]
