from __future__ import annotations

import fcntl
import hashlib
import json
import os
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from scripts.tts import run_chapter_e2e_real as launcher
from scripts.tts.chapter_e2e_probes import StrictReportBrowserProbe
from scripts.tts.chapter_e2e_collector import LocalOperatorCollectorReportGuard
from scripts.tts.chapter_e2e_probe_request import PrivateProbeRequestPublisher
from scripts.tts.chapter_e2e_runtime_audit import ReportBackedRuntimeAuditProbe
from scripts.tts.chapter_e2e_executor import (
    HttpResponse,
    PartialReadyValidationEvidence,
)
from scripts.tts.validate_chapter_e2e import (
    RecoveryClaimBinding,
    RecoveryClaimSnapshot,
    RunnerConfig,
)


RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
NOVEL_ID = UUID("22222222-2222-4222-8222-222222222222")
DOCUMENT_ID = UUID("33333333-3333-4333-8333-333333333333")
AUTOMATIC_CASE_ID = "chapter-auto-zero-blockers"
MANUAL_CASE_ID = "chapter-real-blocker"
FIXTURE_MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "tests/fixtures/narration/chapter-e2e-v3.json"
)


def _private_file(path: Path, content: bytes = b"lock\n") -> Path:
    path.write_bytes(content)
    path.chmod(0o600)
    return path


def _paths(tmp_path: Path) -> dict[str, Path]:
    tmp_path.chmod(0o700)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    private.chmod(0o700)
    fixture = _private_file(
        tmp_path / "fixture.json",
        FIXTURE_MANIFEST.read_bytes(),
    )
    return {
        "envelope": _private_file(private / "operator-envelope.json"),
        "attestation": _private_file(private / "readiness-attestation.json"),
        "probe": _private_file(private / "probe-report.json"),
        "preflight": _private_file(
            private / launcher.CONTROLLER_PREFLIGHT_FILENAME,
            b'{"schema_version":"signed-preflight"}\n',
        ),
        "preflight_signature": _private_file(
            private / launcher.CONTROLLER_PREFLIGHT_SIGNATURE_FILENAME,
            (
                b"-----BEGIN SSH SIGNATURE-----\n"
                b"c2lnbmF0dXJl\n"
                b"-----END SSH SIGNATURE-----\n"
            ),
        ),
        "token": _private_file(tmp_path / "validation.token", b"v" * 43),
        "nano": _private_file(private / "nano.lock"),
        "browser": _private_file(private / "browser.lock"),
        "data": _private_file(private / "data.lock"),
        "fixture": fixture,
        "private": private,
        "output": tmp_path / "result",
    }


def _argv(
    paths: dict[str, Path],
    *,
    confirmation: str = launcher.FIXED_LAUNCHER_CONFIRMATION,
    resume: bool = False,
) -> list[str]:
    return [
        "--mode",
        "real",
        "--operator-envelope-file",
        str(paths["envelope"]),
        "--readiness-attestation-file",
        str(paths["attestation"]),
        "--probe-report",
        str(paths["probe"]),
        "--validation-token-file",
        str(paths["token"]),
        "--lock-nano-file",
        str(paths["nano"]),
        "--lock-browser-file",
        str(paths["browser"]),
        "--lock-data-file",
        str(paths["data"]),
        "--lock-nano-grant",
        "LOCK-NANO/nano-grant-001",
        "--lock-browser-grant",
        "LOCK-BROWSER/browser-grant-001",
        "--lock-data-grant",
        "LOCK-T4-K-DATA/data-grant-001",
        "--confirm-fixed-launcher",
        confirmation,
        *_runner_argv(paths, resume=resume),
    ]


def _runner_argv(paths: dict[str, Path], *, resume: bool = False) -> list[str]:
    args = [
        "--run-id",
        str(RUN_ID),
        "--fixture-manifest",
        str(paths["fixture"]),
        "--api-base",
        "http://127.0.0.1:18088/api/ai-novel-world-2026",
        "--novel-id",
        str(NOVEL_ID),
        "--document-id",
        str(DOCUMENT_ID),
        "--automatic-case-id",
        AUTOMATIC_CASE_ID,
        "--manual-case-id",
        MANUAL_CASE_ID,
        "--private-work-dir",
        str(paths["private"]),
        "--confirm-dedicated-test-novel",
        str(NOVEL_ID),
        "--confirm-dedicated-test-document",
        str(DOCUMENT_ID),
        "--duration-minutes",
        "30",
        "--output-dir",
        str(paths["output"]),
        "--confirm-real-run",
        "RUN-T4-K-REAL-CHAPTER",
        "--confirm-baseline-restore",
        "RESTORE-T4-K-BASELINE",
        "--confirm-private-work-dir-local-non-synced",
        "PRIVATE-WORK-DIR-LOCAL-NON-SYNCED",
    ]
    if resume:
        args.append("--resume")
    return args


def _config(tmp_path: Path, *, resume: bool = False) -> RunnerConfig:
    return RunnerConfig(
        run_id=RUN_ID,
        mode="real",
        fixture_manifest=tmp_path / "fixture.json",
        api_base="http://127.0.0.1:18088/api/ai-novel-world-2026",
        novel_id=NOVEL_ID,
        document_id=DOCUMENT_ID,
        automatic_case_id=AUTOMATIC_CASE_ID,
        manual_case_id=MANUAL_CASE_ID,
        private_work_dir=tmp_path / "private",
        output_dir=tmp_path / "result",
        duration_minutes=30.0,
        listening_record=None,
        resume=resume,
    )


@pytest.fixture(autouse=True)
def _fixed_token_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        launcher,
        "FIXED_VALIDATION_TOKEN_FILE",
        tmp_path / "validation.token",
    )


class _FakeClaim:
    def __init__(self) -> None:
        self.binding = RecoveryClaimBinding(
            claim_identity_sha256="a" * 64,
            envelope_fingerprint_sha256="b" * 64,
            private_work_dir_canonical_sha256="c" * 64,
            private_work_dir_identity_sha256="d" * 64,
        )

    def transition(
        self,
        _state: str,
        _generation: int,
        _digest: str,
    ) -> None:
        return None

    def snapshot(self) -> RecoveryClaimSnapshot:
        return RecoveryClaimSnapshot("PREPARED", 0, None)


def _fake_envelope(paths: dict[str, Path]) -> SimpleNamespace:
    grants = {
        "nano": "LOCK-NANO/nano-grant-001",
        "browser": "LOCK-BROWSER/browser-grant-001",
        "data": "LOCK-T4-K-DATA/data-grant-001",
    }
    return SimpleNamespace(
        run_id=RUN_ID,
        nonce="n" * 43,
        novel_id=NOVEL_ID,
        document_id=DOCUMENT_ID,
        fixture_manifest_sha256=hashlib.sha256(
            paths["fixture"].read_bytes()
        ).hexdigest(),
        required_captures=launcher.FIXED_REQUIRED_CAPTURES,
        envelope_fingerprint_sha256="e" * 64,
        locks=tuple(
            SimpleNamespace(
                name=name,
                identity_sha256=launcher.private_lock_identity_from_stat(
                    paths[name].stat(),
                    name=name,
                    grant=grants[name],
                ),
            )
            for name in ("nano", "browser", "data")
        )
    )


def _patch_operator_inputs(
    monkeypatch: pytest.MonkeyPatch,
    paths: dict[str, Path],
    calls: list[str] | None = None,
) -> None:
    events = calls if calls is not None else []
    envelope = _fake_envelope(paths)
    monkeypatch.setattr(
        launcher,
        "load_operator_envelope",
        lambda *_args, **_kwargs: events.append("load-envelope") or envelope,
    )
    monkeypatch.setattr(
        launcher,
        "load_private_attestation",
        lambda *_args, **_kwargs: events.append("load-attestation") or object(),
    )


def _patch_ready_operator_gate(
    monkeypatch: pytest.MonkeyPatch,
    paths: dict[str, Path],
    calls: list[str] | None = None,
) -> None:
    events = calls if calls is not None else []
    _patch_operator_inputs(monkeypatch, paths, events)
    monkeypatch.setattr(
        launcher,
        "SqlAlchemyReadinessReader",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(launcher, "_storage_from_environment", lambda: None)
    monkeypatch.setattr(
        launcher,
        "evaluate_readiness",
        lambda *_args, **_kwargs: events.append("readiness")
        or {"decision": "READY_FOR_OPERATOR_REVIEW"},
    )
    monkeypatch.setattr(
        launcher,
        "verify_operator_envelope_binding",
        lambda *_args, **_kwargs: events.append("verify-envelope"),
    )
    @contextmanager
    def fake_claim(*_args: object, **_kwargs: object):
        events.append("claim-envelope")
        yield _FakeClaim()

    monkeypatch.setattr(launcher, "claim_operator_envelope", fake_claim)


def _assert_unlocked(path: Path) -> None:
    descriptor = os.open(path, os.O_RDWR)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _gate_response(
    config: RunnerConfig,
    *,
    state: str,
    code: str,
    claimed: int,
) -> HttpResponse:
    bound = state in {"armed", "paused"} or code.endswith("RELEASED")
    payload = {
        "code": code,
        "state": state,
        "claim_limit": 1 if bound else 0,
        "claimed_count": claimed if bound else 0,
        "remaining_count": 1 - claimed if bound else 0,
        "expires_at": "2026-08-27T13:00:00Z" if bound else None,
        "run_fingerprint_sha256": (
            launcher._PartialReadyCoordinator._fingerprint(
                b"narration-validation-claim-gate-run/1",
                config.run_id,
            )
            if bound
            else None
        ),
        "scope_fingerprint_sha256": (
            launcher._PartialReadyCoordinator._fingerprint(
                b"narration-validation-claim-gate-scope/1",
                config.novel_id,
                config.document_id,
            )
            if bound
            else None
        ),
    }
    return HttpResponse(
        status=200,
        headers={"Cache-Control": "no-store"},
        body=json.dumps(payload, sort_keys=True).encode("utf-8"),
    )


def test_partial_ready_coordinator_releases_host_gate_and_hash_chains_marker(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    config = _config(tmp_path)
    calls: list[dict[str, object]] = []
    responses = [
        _gate_response(
            config,
            state="armed",
            code="VALIDATION_SEGMENT_CLAIM_GATE_ARMED",
            claimed=0,
        ),
        _gate_response(
            config,
            state="default_allow",
            code="VALIDATION_SEGMENT_CLAIM_GATE_RELEASED",
            claimed=0,
        ),
    ]

    class Transport:
        def request(self, **kwargs: object) -> HttpResponse:
            calls.append(dict(kwargs))
            return responses.pop(0)

    with launcher._private_work_directory(paths["private"]) as directory:
        coordinator = launcher._PartialReadyCoordinator(
            config,
            transport=Transport(),  # type: ignore[arg-type]
            private_directory=directory,
        )
        coordinator.require_host_prearm_and_release()
        evidence = PartialReadyValidationEvidence(
            source_content_sha256="a" * 64,
            return_fence_sha256="b" * 64,
        )
        coordinator.record(config, state="staging", evidence=evidence)
        marker = paths["private"] / launcher.PARTIAL_READY_MARKER_FILENAME
        first_raw = marker.read_bytes()
        validator_config = replace(
            config,
            expected_formal_speakers=("林晚", "沈川"),
        )
        coordinator.record(
            validator_config,
            state="gate_armed",
            evidence=evidence,
        )
        with pytest.raises(
            launcher.RunnerError,
            match="PARTIAL_READY_COORDINATOR_SCOPE_INVALID",
        ):
            coordinator.record(
                replace(validator_config, document_id=uuid4()),
                state="gate_armed",
                evidence=evidence,
            )

    assert [call["method"] for call in calls] == ["GET", "POST"]
    assert calls[0]["json_body"] is None
    assert calls[1]["json_body"] == {"run_id": str(RUN_ID)}
    assert str(calls[1]["path"]).endswith("/release")
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert set(payload) == {
        "schema_version",
        "generation",
        "previous_record_sha256",
        "state",
        "run_id",
        "novel_id",
        "document_id",
        "source_content_sha256",
        "return_fence_sha256",
        "request_id",
        "script_version_id",
        "edition_id",
        "manifest_revision",
        "manifest_etag_sha256",
        "manifest_payload_sha256",
        "ready_prefix_count",
        "ready_prefix_duration_ms",
        "cache_hit_prefix_count",
        "cache_miss_job_count",
        "gate_claimed_count",
        "gate_run_fingerprint_sha256",
        "gate_scope_fingerprint_sha256",
        "restored_fence_sha256",
        "error_code",
    }
    assert payload["generation"] == 2
    assert payload["previous_record_sha256"] == hashlib.sha256(first_raw).hexdigest()
    assert payload["state"] == "gate_armed"
    assert marker.stat().st_mode & 0o777 == 0o600
    serialized = marker.read_text(encoding="utf-8")
    assert serialized.count('"cache_hit_prefix_count"') == 1
    assert "content_markdown" not in serialized
    assert "http://" not in serialized
    assert "validation.token" not in serialized


def test_partial_ready_coordinator_rejects_wrong_host_gate_scope(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    config = _config(tmp_path)
    wrong = json.loads(
        _gate_response(
            config,
            state="armed",
            code="VALIDATION_SEGMENT_CLAIM_GATE_ARMED",
            claimed=0,
        ).body
    )
    wrong["scope_fingerprint_sha256"] = "f" * 64

    class Transport:
        def request(self, **_kwargs: object) -> HttpResponse:
            return HttpResponse(
                status=200,
                headers={"Cache-Control": "no-store"},
                body=json.dumps(wrong).encode("utf-8"),
            )

    with launcher._private_work_directory(paths["private"]) as directory:
        coordinator = launcher._PartialReadyCoordinator(
            config,
            transport=Transport(),  # type: ignore[arg-type]
            private_directory=directory,
        )
        with pytest.raises(
            launcher.RunnerError,
            match="PARTIAL_READY_GATE_INVALID",
        ):
            coordinator.require_host_prearm_and_release()


def test_launcher_rejects_wrong_confirmation_before_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = _paths(tmp_path)
    monkeypatch.setattr(
        launcher,
        "get_engine",
        lambda: (_ for _ in ()).throw(AssertionError("must not reach database")),
    )

    exit_code = launcher.main(_argv(paths, confirmation="wrong"))

    assert exit_code == 2
    assert json.loads(capsys.readouterr().err) == {
        "status": "FAILED",
        "code": "REAL_LAUNCHER_CONFIRMATION_REQUIRED",
    }


def test_launcher_rejects_relative_paths_and_exposes_no_import_hook(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = _paths(tmp_path)
    paths["probe"] = Path("relative-probe.json")
    monkeypatch.setattr(
        launcher,
        "get_engine",
        lambda: (_ for _ in ()).throw(AssertionError("must not reach database")),
    )

    exit_code = launcher.main(_argv(paths))

    assert exit_code == 2
    assert json.loads(capsys.readouterr().err) == {
        "status": "FAILED",
        "code": "REAL_LAUNCHER_PATH_INVALID",
    }
    parser_fields = {action.dest for action in launcher.build_parser()._actions}
    assert not {
        "executor_import",
        "transport_import",
        "browser_probe_import",
        "runtime_probe_import",
        "database_url",
        "shell_command",
        "controller_preflight_file",
        "controller_preflight_signature_file",
    } & parser_fields


def test_launcher_requires_probe_report_in_the_same_private_run_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = _paths(tmp_path)
    paths["probe"] = tmp_path / "probe-report.json"
    monkeypatch.setattr(
        launcher,
        "load_operator_envelope",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("path binding must fail before private inputs")
        ),
    )

    result = launcher.main(_argv(paths))

    assert result == 2
    assert json.loads(capsys.readouterr().err) == {
        "code": "REAL_LAUNCHER_PROBE_PATH_MISMATCH",
        "status": "FAILED",
    }


def test_fresh_launcher_uses_local_guard_and_exact_executor_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _paths(tmp_path)
    paths["token"].write_text("v" * 43, encoding="ascii")
    paths["preflight"].unlink()
    paths["preflight_signature"].unlink()
    config = _config(tmp_path)
    engine = object()
    session_factory = lambda: None
    factory_token = object()
    calls: dict[str, object] = {}
    operator_calls: list[str] = []
    envelope = _fake_envelope(paths)
    fixture = launcher.validator.load_fixture(
        paths["fixture"],
        automatic_case_id=AUTOMATIC_CASE_ID,
        manual_case_id=MANUAL_CASE_ID,
    )
    expected_binding = launcher._local_executor_binding_sha256(
        envelope=envelope,
        config=config,
        fixture=fixture,
    )

    monkeypatch.setattr(launcher, "get_engine", lambda: engine)
    _patch_ready_operator_gate(monkeypatch, paths, operator_calls)

    def fake_verify_gate(
        observed_config: RunnerConfig,
        *,
        validation_token: str,
    ) -> None:
        assert observed_config == config
        assert validation_token == "v" * 43
        operator_calls.append("hidden-gate")
        calls["gate"] = True

    monkeypatch.setattr(
        launcher,
        "verify_t4k_hidden_release_gate",
        fake_verify_gate,
    )
    monkeypatch.setattr(
        launcher,
        "_verify_controller_preflight",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("fresh local product path must not read preflight")
        ),
    )
    monkeypatch.setattr(
        launcher,
        "FixedControllerTrustVerifier",
        lambda: (_ for _ in ()).throw(
            AssertionError("fresh local product path must not verify authority")
        ),
    )
    real_local_binding = launcher._local_executor_binding_sha256

    def bind_local_executor(**kwargs: object) -> str:
        assert operator_calls[-1] == "hidden-gate"
        binding = real_local_binding(**kwargs)  # type: ignore[arg-type]
        assert binding == expected_binding
        operator_calls.append("local-executor-binding")
        calls["binding"] = binding
        return binding

    monkeypatch.setattr(
        launcher,
        "_local_executor_binding_sha256",
        bind_local_executor,
    )

    class FakePartialReadyCoordinator:
        def __init__(self, observed_config, **kwargs):  # type: ignore[no-untyped-def]
            assert observed_config == config
            assert isinstance(kwargs["transport"], launcher.LoopbackHttpTransport)
            assert kwargs["private_directory"].path == paths["private"]
            calls["partial-coordinator"] = self

        def require_host_prearm_and_release(self) -> None:
            assert operator_calls[-1] == "local-executor-binding"
            operator_calls.append("host-gate-released")

    monkeypatch.setattr(
        launcher,
        "_PartialReadyCoordinator",
        FakePartialReadyCoordinator,
    )

    def fake_sessionmaker(*, bind: object, expire_on_commit: bool):
        assert bind is engine
        assert expire_on_commit is False
        return session_factory

    def fake_build_factory(**ports: object):
        assert operator_calls[-1] == "host-gate-released"
        operator_calls.append("executor-factory")
        transport = ports["transport_factory"](config)  # type: ignore[operator]
        assert isinstance(transport, launcher.LoopbackHttpTransport)
        assert transport._validation_token == "v" * 43  # noqa: SLF001
        browser = ports["browser_probe_factory"](config)  # type: ignore[operator]
        runtime = ports["runtime_audit_probe_factory"](config)  # type: ignore[operator]
        assert isinstance(browser, StrictReportBrowserProbe)
        assert isinstance(runtime, ReportBackedRuntimeAuditProbe)
        assert ports["partial_ready_coordinator"] is calls["partial-coordinator"]
        assert isinstance(
            browser._cache._request_publisher,  # noqa: SLF001
            PrivateProbeRequestPublisher,
        )
        assert (
            browser._cache._request_publisher._preflight_payload_sha256  # noqa: SLF001
            == expected_binding
        )
        assert isinstance(
            browser._cache._report_guard,  # noqa: SLF001
            LocalOperatorCollectorReportGuard,
        )
        calls["ports"] = ports
        return factory_token

    def fake_validator_main(
        argv: list[str],
        *,
        executor_factory: object,
        fixture_override: object,
        recovery_claim_binding: object,
        recovery_state_observer: object,
        recovery_claim_state_reader: object,
    ) -> int:
        assert argv == ["--mode", "real", *_runner_argv(paths)]
        assert executor_factory is factory_token
        assert getattr(fixture_override, "manifest_sha256")
        assert recovery_claim_binding is not None
        assert callable(recovery_state_observer)
        assert callable(recovery_claim_state_reader)
        for path in (paths["nano"], paths["browser"], paths["data"]):
            descriptor = os.open(path, os.O_RDWR)
            try:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                os.close(descriptor)
        calls["validator"] = True
        operator_calls.append("validator")
        return 17

    monkeypatch.setattr(launcher, "sessionmaker", fake_sessionmaker)
    monkeypatch.setattr(launcher, "build_real_executor_factory", fake_build_factory)
    monkeypatch.setattr(launcher.validator, "main", fake_validator_main)

    exit_code = launcher.main(_argv(paths))

    assert exit_code == 17
    assert calls.keys() == {
        "gate",
        "binding",
        "partial-coordinator",
        "ports",
        "validator",
    }
    assert operator_calls == [
        "load-envelope",
        "load-attestation",
        "readiness",
        "verify-envelope",
        "hidden-gate",
        "local-executor-binding",
        "host-gate-released",
        "executor-factory",
        "claim-envelope",
        "validator",
    ]
    _assert_unlocked(paths["nano"])
    _assert_unlocked(paths["browser"])
    _assert_unlocked(paths["data"])


def test_busy_lock_fails_before_database_or_executor_wiring(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = _paths(tmp_path)
    _patch_operator_inputs(monkeypatch, paths)
    held_descriptor = os.open(paths["nano"], os.O_RDWR)
    fcntl.flock(held_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    monkeypatch.setattr(
        launcher,
        "get_engine",
        lambda: (_ for _ in ()).throw(AssertionError("must not reach database")),
    )
    monkeypatch.setattr(
        launcher,
        "build_real_executor_factory",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("must not wire executor")
        ),
    )
    try:
        exit_code = launcher.main(_argv(paths))
    finally:
        fcntl.flock(held_descriptor, fcntl.LOCK_UN)
        os.close(held_descriptor)

    assert exit_code == 2
    assert json.loads(capsys.readouterr().err) == {
        "status": "FAILED",
        "code": "LOCK_NANO_BUSY",
    }


def test_launcher_rejects_non_private_or_malformed_validation_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = _paths(tmp_path)
    paths["token"].write_text("too-short", encoding="ascii")
    _patch_ready_operator_gate(monkeypatch, paths)
    monkeypatch.setattr(launcher, "get_engine", lambda: object())
    monkeypatch.setattr(
        launcher,
        "sessionmaker",
        lambda *, bind, expire_on_commit: object(),
    )

    exit_code = launcher.main(_argv(paths))

    assert exit_code == 2
    stderr = capsys.readouterr().err
    assert json.loads(stderr) == {
        "status": "FAILED",
        "code": "VALIDATION_TOKEN_FILE_INVALID",
    }
    assert "too-short" not in stderr


def test_launcher_rejects_an_alternate_private_token_with_the_same_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = _paths(tmp_path)
    alternate = _private_file(tmp_path / "alternate.token", b"v" * 43)
    paths["token"] = alternate
    monkeypatch.setattr(
        launcher,
        "get_engine",
        lambda: (_ for _ in ()).throw(AssertionError("must reject before DB")),
    )

    assert launcher.main(_argv(paths)) == 2
    assert json.loads(capsys.readouterr().err) == {
        "status": "FAILED",
        "code": "VALIDATION_TOKEN_FILE_INVALID",
    }


def test_launcher_rejects_validation_token_inside_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = _paths(tmp_path)
    token = "r" * 43
    paths["token"].write_text(token, encoding="ascii")
    _patch_ready_operator_gate(monkeypatch, paths)
    monkeypatch.setattr(launcher, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(launcher, "get_engine", lambda: object())
    monkeypatch.setattr(
        launcher,
        "sessionmaker",
        lambda *, bind, expire_on_commit: object(),
    )

    exit_code = launcher.main(_argv(paths))

    assert exit_code == 2
    stderr = capsys.readouterr().err
    assert json.loads(stderr) == {
        "status": "FAILED",
        "code": "VALIDATION_TOKEN_FILE_INVALID",
    }
    assert token not in stderr
    assert str(paths["token"]) not in stderr


def test_launcher_stops_before_executor_chain_when_hidden_gate_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = _paths(tmp_path)
    token = "s" * 43
    paths["token"].write_text(token, encoding="ascii")
    config = _config(tmp_path)
    engine = object()

    _patch_ready_operator_gate(monkeypatch, paths)
    monkeypatch.setattr(launcher, "get_engine", lambda: engine)
    monkeypatch.setattr(
        launcher,
        "sessionmaker",
        lambda *, bind, expire_on_commit: object(),
    )

    def fail_gate(
        _config: RunnerConfig,
        *,
        validation_token: str,
    ) -> None:
        assert validation_token == token
        raise launcher.RunnerError("T4_HIDDEN_ROUTE_GATE_FAILED")

    def fake_build_factory(**ports: object):
        ports["transport_factory"](config)  # type: ignore[operator]
        raise AssertionError("gate failure must stop executor construction")

    monkeypatch.setattr(launcher, "verify_t4k_hidden_release_gate", fail_gate)
    monkeypatch.setattr(
        launcher,
        "build_real_executor_factory",
        fake_build_factory,
    )
    monkeypatch.setattr(
        launcher.validator,
        "main",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("gate failure must stop the existing chain")
        ),
    )

    exit_code = launcher.main(_argv(paths))

    assert exit_code == 2
    stderr = capsys.readouterr().err
    assert json.loads(stderr) == {
        "status": "FAILED",
        "code": "T4_HIDDEN_ROUTE_GATE_FAILED",
    }
    assert token not in stderr
    for path in (paths["nano"], paths["browser"], paths["data"]):
        _assert_unlocked(path)


@pytest.mark.parametrize(
    ("artifact", "mutation"),
    [
        ("preflight", "missing"),
        ("preflight", "wide-mode"),
        ("preflight", "hard-link"),
        ("preflight", "symlink"),
        ("preflight_signature", "non-ascii"),
    ],
)
def test_experimental_controller_preflight_files_are_private_artifacts(
    tmp_path: Path,
    artifact: str,
    mutation: str,
) -> None:
    paths = _paths(tmp_path)
    target = paths[artifact]
    if mutation == "missing":
        target.unlink()
    elif mutation == "wide-mode":
        target.chmod(0o640)
    elif mutation == "hard-link":
        os.link(target, tmp_path / "authority-hard-link")
    elif mutation == "symlink":
        target.unlink()
        target.symlink_to(paths["attestation"].name)
    elif mutation == "non-ascii":
        target.write_bytes("not-ascii-签名".encode("utf-8"))
        target.chmod(0o600)
    else:  # pragma: no cover - parametrization is frozen above
        raise AssertionError(mutation)

    config = _config(tmp_path)
    fixture = launcher.validator.load_fixture(
        paths["fixture"],
        automatic_case_id=AUTOMATIC_CASE_ID,
        manual_case_id=MANUAL_CASE_ID,
    )
    with launcher._private_work_directory(paths["private"]) as directory:
        with pytest.raises(launcher.RunnerError) as caught:
            launcher._verify_controller_preflight(
                private_directory=directory,
                envelope=_fake_envelope(paths),
                config=config,
                fixture=fixture,
            )
    assert caught.value.code == "CONTROLLER_PREFLIGHT_FILE_INVALID"


@pytest.mark.parametrize(
    ("trust_code", "launcher_code"),
    [
        (
            "CONTROLLER_TRUST_ROOT_HOLD",
            "PROBE_CONTROLLER_AUTHORITY_HOLD",
        ),
        ("CONTROLLER_PREFLIGHT_INVALID", "CONTROLLER_PREFLIGHT_INVALID"),
        (
            "CONTROLLER_PREFLIGHT_BINDING_MISMATCH",
            "CONTROLLER_PREFLIGHT_BINDING_MISMATCH",
        ),
        ("CONTROLLER_SIGNATURE_INVALID", "CONTROLLER_SIGNATURE_INVALID"),
    ],
)
def test_experimental_controller_preflight_verifier_maps_stable_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    trust_code: str,
    launcher_code: str,
) -> None:
    paths = _paths(tmp_path)
    events: list[str] = []

    class RejectingVerifier:
        def verify_preflight(self, *_args: object, **_kwargs: object) -> None:
            events.append("verify-controller-preflight")
            raise launcher.ControllerTrustError(trust_code)

    monkeypatch.setattr(
        launcher,
        "FixedControllerTrustVerifier",
        RejectingVerifier,
    )
    config = _config(tmp_path)
    fixture = launcher.validator.load_fixture(
        paths["fixture"],
        automatic_case_id=AUTOMATIC_CASE_ID,
        manual_case_id=MANUAL_CASE_ID,
    )
    with launcher._private_work_directory(paths["private"]) as directory:
        with pytest.raises(launcher.RunnerError) as caught:
            launcher._verify_controller_preflight(
                private_directory=directory,
                envelope=_fake_envelope(paths),
                config=config,
                fixture=fixture,
            )
    assert caught.value.code == launcher_code
    assert events == ["verify-controller-preflight"]


def test_launcher_requires_explicit_run_id_before_operator_or_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = _paths(tmp_path)
    argv = _argv(paths)
    run_index = argv.index("--run-id")
    del argv[run_index : run_index + 2]
    monkeypatch.setattr(
        launcher,
        "load_operator_envelope",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("must reject before loading an envelope")
        ),
    )
    monkeypatch.setattr(
        launcher,
        "get_engine",
        lambda: (_ for _ in ()).throw(AssertionError("must not reach database")),
    )

    result = launcher.main(argv)

    assert result == 2
    assert json.loads(capsys.readouterr().err) == {
        "code": "OPERATOR_ENVELOPE_RUN_REQUIRED",
        "status": "FAILED",
    }


def test_private_lock_parent_must_be_owner_only_before_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = _paths(tmp_path)
    _patch_operator_inputs(monkeypatch, paths)
    paths["private"].chmod(0o755)
    monkeypatch.setattr(
        launcher,
        "get_engine",
        lambda: (_ for _ in ()).throw(AssertionError("must not reach database")),
    )

    result = launcher.main(_argv(paths))

    assert result == 2
    assert json.loads(capsys.readouterr().err) == {
        "code": "REAL_LAUNCHER_PRIVATE_DIR_INVALID",
        "status": "FAILED",
    }


def test_private_lock_rejects_rename_swap_after_flock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path.chmod(0o700)
    lock_path = _private_file(tmp_path / "nano.lock")
    replacement = _private_file(tmp_path / "replacement.lock")
    moved = tmp_path / "moved.lock"
    grant = "LOCK-NANO/nano-grant-001"
    expected = launcher.private_lock_identity_from_stat(
        lock_path.stat(),
        name="nano",
        grant=grant,
    )
    real_flock = fcntl.flock
    swapped = False

    def swapping_flock(descriptor: int, operation: int) -> None:
        nonlocal swapped
        real_flock(descriptor, operation)
        if not swapped and operation & fcntl.LOCK_EX:
            lock_path.rename(moved)
            replacement.rename(lock_path)
            swapped = True

    monkeypatch.setattr(launcher.fcntl, "flock", swapping_flock)

    with pytest.raises(launcher.RunnerError, match="REAL_LAUNCHER_LOCK_INVALID"):
        with launcher._private_work_directory(tmp_path) as private_directory:
            with launcher._private_lock(
                lock_path,
                private_directory=private_directory,
                name="nano",
                grant=grant,
                expected_identity_sha256=expected,
                busy_code="LOCK_NANO_BUSY",
            ):
                raise AssertionError("rename swap must fail before the body")


def test_resume_requires_same_claim_and_skips_new_readiness_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _paths(tmp_path)
    paths["token"].write_text("z" * 43, encoding="ascii")
    events: list[tuple[str, object]] = []
    envelope = _fake_envelope(paths)
    attestation = object()
    factory = object()
    monkeypatch.setattr(
        launcher,
        "load_operator_envelope",
        lambda *_args, **kwargs: events.append(
            ("load-envelope-fresh", kwargs["require_fresh"])
        )
        or envelope,
    )
    monkeypatch.setattr(
        launcher,
        "load_private_attestation",
        lambda *_args, **_kwargs: attestation,
    )
    monkeypatch.setattr(
        launcher,
        "get_engine",
        lambda: (_ for _ in ()).throw(
            AssertionError("resume must not construct a readiness database port")
        ),
    )
    monkeypatch.setattr(
        launcher,
        "sessionmaker",
        lambda *, bind, expire_on_commit: object(),
    )
    monkeypatch.setattr(
        launcher,
        "evaluate_readiness",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("recovery must not be blocked by a new readiness verdict")
        ),
    )
    monkeypatch.setattr(
        launcher,
        "_verify_controller_preflight",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("product recovery must not consult experimental preflight")
        ),
    )

    def verify(*_args, **kwargs):  # type: ignore[no-untyped-def]
        events.append(("verify-resume", kwargs["resume"]))
        assert kwargs["readiness_report"] is None

    @contextmanager
    def claim(*_args, **kwargs):  # type: ignore[no-untyped-def]
        events.append(("claim-resume", kwargs["resume"]))
        yield _FakeClaim()

    monkeypatch.setattr(launcher, "verify_operator_envelope_binding", verify)
    monkeypatch.setattr(launcher, "claim_operator_envelope", claim)
    monkeypatch.setattr(
        launcher,
        "build_real_recovery_executor_factory",
        lambda **_kwargs: factory,
    )
    monkeypatch.setattr(
        launcher,
        "build_real_executor_factory",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("resume must not construct the normal executor")
        ),
    )

    def validator_main(
        argv,
        *,
        recovery_executor_factory,
        fixture_override,
        recovery_claim_binding,
        recovery_state_observer,
        recovery_claim_state_reader,
    ):  # type: ignore[no-untyped-def]
        assert argv == ["--mode", "real", *_runner_argv(paths, resume=True)]
        assert recovery_executor_factory is factory
        assert getattr(fixture_override, "manifest_sha256")
        assert recovery_claim_binding is not None
        assert callable(recovery_state_observer)
        assert callable(recovery_claim_state_reader)
        return 0

    monkeypatch.setattr(launcher.validator, "main", validator_main)

    result = launcher.main(_argv(paths, resume=True))

    assert result == 0
    assert events == [
        ("load-envelope-fresh", False),
        ("verify-resume", True),
        ("claim-resume", True),
    ]


def test_launcher_help_preserves_argparse_success(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert launcher.main(["--help"]) == 0
    captured = capsys.readouterr()
    assert "usage:" in captured.out
    assert captured.err == ""
