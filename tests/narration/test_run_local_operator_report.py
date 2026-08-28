from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.tts.chapter_e2e_collector import CollectorResult
from scripts.tts import run_local_operator_report as command


NOVEL_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
DOCUMENT_ID = "01234567-89ab-4cde-8fab-0123456789ab"
TOKEN = "v" * 43
COLLECTOR_SHA = "a" * 64
PROBE_SHA = "b" * 64


def _private_inputs(tmp_path: Path) -> tuple[Path, Path]:
    tmp_path.chmod(0o700)
    probe = tmp_path / "probe-request.json"
    token = tmp_path / "token"
    probe.write_text("{}\n", encoding="utf-8")
    token.write_text(TOKEN, encoding="ascii")
    probe.chmod(0o600)
    token.chmod(0o600)
    return probe, token


def _argv(probe: Path, token: Path) -> list[str]:
    return [
        "--probe-request-file",
        str(probe),
        "--host-token-file",
        str(token),
        "--novel-id",
        NOVEL_ID,
        "--document-id",
        DOCUMENT_ID,
        "--confirm",
        command.CONFIRMATION,
    ]


def test_cli_runs_only_the_fixed_local_operator_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    probe, token = _private_inputs(tmp_path)
    calls: list[tuple[Path, str, str, str]] = []

    def run(
        probe_path: Path,
        novel_id: str,
        document_id: str,
        validation_token: str,
    ) -> CollectorResult:
        calls.append((probe_path, novel_id, document_id, validation_token))
        return CollectorResult(
            status="LOCAL_OPERATOR_OBSERVATION_COMMITTED",
            collector_report_sha256=COLLECTOR_SHA,
            probe_report_sha256=PROBE_SHA,
        )

    monkeypatch.setattr(command, "run_fixed_local_operator_report_stage", run)

    assert command.main(_argv(probe, token)) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert captured.err == ""
    assert calls == [(probe, NOVEL_ID, DOCUMENT_ID, TOKEN)]
    assert payload == {
        "schema_version": command.REPORT_SCHEMA,
        "status": "LOCAL_OPERATOR_OBSERVATION_COMMITTED",
        "collector_report_sha256": COLLECTOR_SHA,
        "probe_report_sha256": PROBE_SHA,
        "secret_values_emitted": False,
        "private_paths_emitted": False,
    }
    rendered = captured.out + captured.err
    assert TOKEN not in rendered
    assert str(probe) not in rendered
    assert str(token) not in rendered
    assert NOVEL_ID not in rendered
    assert DOCUMENT_ID not in rendered


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        (lambda argv: [*argv[:-1], "wrong"], "LOCAL_OPERATOR_CONFIRMATION_REQUIRED"),
        (
            lambda argv: [
                *argv[:1],
                "relative/probe-request.json",
                *argv[2:],
            ],
            "LOCAL_OPERATOR_PATH_INVALID",
        ),
        (
            lambda argv: [
                *argv[:5],
                NOVEL_ID.upper(),
                *argv[6:],
            ],
            "LOCAL_OPERATOR_SCOPE_INVALID",
        ),
        (
            lambda argv: [*argv, "--browser", "edge"],
            "LOCAL_OPERATOR_ARGUMENTS_INVALID",
        ),
    ),
)
def test_invalid_inputs_fail_before_token_or_observer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mutation,
    expected_code: str,
) -> None:
    probe, token = _private_inputs(tmp_path)
    monkeypatch.setattr(
        command,
        "read_private_host_token",
        lambda _path: (_ for _ in ()).throw(
            AssertionError("token must not be read")
        ),
    )
    monkeypatch.setattr(
        command,
        "run_fixed_local_operator_report_stage",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("observer must not run")
        ),
    )

    assert command.main(mutation(_argv(probe, token))) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    payload = json.loads(captured.err)
    assert payload["code"] == expected_code
    assert payload["status"] == "HOLD"
    assert TOKEN not in captured.err
    assert str(probe) not in captured.err
    assert str(token) not in captured.err


def test_owner_only_token_policy_is_reused_and_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    probe, token = _private_inputs(tmp_path)
    token.chmod(0o644)
    monkeypatch.setattr(
        command,
        "run_fixed_local_operator_report_stage",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("observer must not run")
        ),
    )

    assert command.main(_argv(probe, token)) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.err)
    assert payload["code"] == "HOST_TOKEN_FILE_INVALID"
    assert TOKEN not in captured.err
    assert str(token) not in captured.err


def test_lifecycle_failure_preserves_only_stable_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    probe, token = _private_inputs(tmp_path)

    def fail(*_args: object) -> CollectorResult:
        from scripts.tts.chapter_e2e_controller_lifecycle import (
            ControllerLifecycleError,
        )

        raise ControllerLifecycleError("CONTROLLER_LIFECYCLE_BROWSER_HOLD")

    monkeypatch.setattr(command, "run_fixed_local_operator_report_stage", fail)

    assert command.main(_argv(probe, token)) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["code"] == "CONTROLLER_LIFECYCLE_BROWSER_HOLD"
    assert TOKEN not in captured.err
    assert str(probe) not in captured.err


def test_help_is_available_without_running_the_stage(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        command,
        "run_fixed_local_operator_report_stage",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("observer must not run")
        ),
    )

    assert command.main(["--help"]) == 0
    captured = capsys.readouterr()
    assert "--probe-request-file" in captured.out
    assert "--browser" not in captured.out
    assert captured.err == ""
