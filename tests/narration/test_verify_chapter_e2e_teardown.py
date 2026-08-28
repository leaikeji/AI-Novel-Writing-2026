from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
from typing import Mapping
from uuid import UUID

import pytest

from backend.narration.privacy import t2_settings_capabilities
from scripts.tts import verify_chapter_e2e_teardown as teardown


RUN_ID = UUID("10000000-0000-4000-8000-000000000001")
NOVEL_ID = UUID("20000000-0000-4000-8000-000000000001")
DOCUMENT_ID = UUID("30000000-0000-4000-8000-000000000001")
TOKEN = "v" * 43
TOKEN_FINGERPRINT = hashlib.sha256(TOKEN.encode("ascii")).hexdigest()


def _observation(
    status: int,
    payload: object,
    *,
    cache_control: str | None = None,
) -> teardown.HttpObservation:
    headers = {"Content-Type": "application/json"}
    if cache_control is not None:
        headers["Cache-Control"] = cache_control
    return teardown.HttpObservation(
        status=status,
        headers=headers,
        body=json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8"),
    )


def _config(**changes: object) -> teardown.TeardownConfig:
    values: dict[str, object] = {
        "run_id": RUN_ID,
        "novel_id": NOVEL_ID,
        "document_id": DOCUMENT_ID,
        "expected_token_fingerprint": TOKEN_FINGERPRINT,
    }
    values.update(changes)
    return teardown.TeardownConfig(**values)  # type: ignore[arg-type]


class _TokenPort:
    def __init__(
        self,
        *,
        host_token: str = TOKEN,
        container_fingerprint: str | None = TOKEN_FINGERPRINT,
    ) -> None:
        self.host_token = host_token
        self.container_fingerprint = container_fingerprint
        self.host_reads = 0
        self.container_reads = 0
        self.destroy_expected: list[str] = []

    def read_host_token(self) -> str:
        self.host_reads += 1
        return self.host_token

    def read_container_fingerprint(self) -> str | None:
        self.container_reads += 1
        return self.container_fingerprint

    def destroy_copies(self, expected_fingerprint: str) -> Mapping[str, object]:
        self.destroy_expected.append(expected_fingerprint)
        return {
            "schema_version": 1,
            "status": "DESTROYED",
            "host_token_present": False,
            "container_token_present": False,
            "secret_values_emitted": False,
        }


class _ReadPort:
    def __init__(
        self,
        *,
        fail_token_class: str | None = None,
        bad_t2_matrix: bool = False,
        formal_claim_present: bool = False,
        new_claims_allowed: bool = False,
        product_requested: bool = False,
        product_enabled: bool = False,
    ) -> None:
        self.fail_token_class = fail_token_class
        self.bad_t2_matrix = bad_t2_matrix
        self.formal_claim_present = formal_claim_present
        self.new_claims_allowed = new_claims_allowed
        self.product_requested = product_requested
        self.product_enabled = product_enabled
        self.requests: list[tuple[str, str | None]] = []
        self.worker_reads = 0

    @staticmethod
    def _token_class(token: str | None) -> str:
        if token is None:
            return "missing"
        if token == TOKEN:
            return "old"
        return "wrong"

    def _health(self) -> teardown.HttpObservation:
        return _observation(
            200,
            {
                "status": "ready",
                "database": {"connected": True},
                "narration": {
                    "technical_enabled": True,
                    "lifecycle_status": "ready",
                    "sidecar_reachable": True,
                    "model_ready": True,
                    "product_visible": self.product_enabled,
                    "reason_code": None,
                },
                "narration_production": {
                    "product_requested": self.product_requested,
                    "lifecycle_status": "playback_only",
                    "playback_installed": True,
                    "digest_keyring_loaded": False,
                    "production_backend_installed": False,
                    "worker_running": False,
                    "reference_clone_ready": False,
                    "reason_code": None,
                },
            },
        )

    def _overview(self) -> teardown.HttpObservation:
        capabilities = t2_settings_capabilities().model_dump(mode="json")
        if self.bad_t2_matrix:
            capabilities["items"][0]["state"] = "hold"
        return _observation(
            200,
            {
                "contract_version": "narration-settings-api/1",
                "novel_id": str(NOVEL_ID),
                "capabilities": capabilities,
                "runtime": {"product_visible": False},
            },
        )

    def request(
        self,
        *,
        path: str,
        validation_token: str | None,
    ) -> teardown.HttpObservation:
        self.requests.append((path, validation_token))
        if path == "/health":
            return self._health()
        if path.endswith("/narration-overview"):
            return self._overview()
        if self._token_class(validation_token) == self.fail_token_class:
            return _observation(200, {"unexpected": True})
        return _observation(
            404,
            {
                "detail": {
                    "code": "RESOURCE_NOT_FOUND",
                    "message": "找不到请求的朗读资源。",
                }
            },
            cache_control="no-store",
        )

    def worker_target_evidence(
        self,
        config: teardown.TeardownConfig,
    ) -> teardown.WorkerTargetEvidence:
        self.worker_reads += 1
        return teardown.WorkerTargetEvidence(
            run_id=config.run_id,
            novel_id=config.novel_id,
            document_id=config.document_id,
            read_only=True,
            formal_claim_present=self.formal_claim_present,
            new_claims_allowed=self.new_claims_allowed,
        )


def _unsigned_integration_receipt(
    config: teardown.TeardownConfig,
) -> dict[str, object]:
    return {
        "schema_version": teardown.INTEGRATION_RECEIPT_SCHEMA,
        "work_package": teardown.INTEGRATION_WORK_PACKAGE,
        "decision": "PASS",
        "run_id": str(config.run_id),
        "novel_id": str(config.novel_id),
        "document_id": str(config.document_id),
        "product_requested": True,
        "product_enabled": True,
    }


def _integration_receipt(
    config: teardown.TeardownConfig,
) -> tuple[dict[str, object], str]:
    receipt = _unsigned_integration_receipt(config)
    fingerprint = teardown.integration_receipt_fingerprint(receipt)
    receipt["receipt_fingerprint"] = fingerprint
    return receipt, fingerprint


def test_readonly_verify_proves_complete_t2_teardown_protocol() -> None:
    read_port = _ReadPort()
    token_port = _TokenPort()

    report = teardown.verify_teardown(
        _config(),
        read_port=read_port,
        token_port=token_port,
    )

    assert report["status"] == "VERIFIED"
    assert report["decision"] == "T2_TEARDOWN_VERIFIED"
    assert report["product_requested"] is False
    assert report["product_enabled"] is False
    assert report["integration_pass_bound"] is False
    assert report["negative_token_classes"] == ["missing", "wrong", "old"]
    assert report["hidden_route_classes"] == [
        "synthesis",
        "editor_production",
        "player_manifest",
    ]
    assert report["overview_tier"] == "T2"
    assert report["worker_target_formal_claim_present"] is False
    assert report["token_copies_identical"] is True
    assert report["expected_token_fingerprint_bound"] is True
    assert report["token_copies_destroyed"] is False
    assert report["viewport_requirements_changed"] is False
    assert token_port.destroy_expected == []
    assert token_port.host_reads == token_port.container_reads == 1
    assert read_port.worker_reads == 1

    negative_requests = [
        item for item in read_port.requests if item[0] != "/health"
    ]
    assert len(negative_requests) == 12
    observed_tokens = {token for _path, token in negative_requests}
    assert None in observed_tokens
    assert TOKEN in observed_tokens
    wrong_tokens = observed_tokens - {None, TOKEN}
    assert len(wrong_tokens) == 1
    wrong_token = next(iter(wrong_tokens))
    assert isinstance(wrong_token, str) and wrong_token != TOKEN
    assert all(
        sum(1 for _path, observed in negative_requests if observed == token) == 4
        for token in observed_tokens
    )

    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    assert TOKEN not in serialized
    assert TOKEN_FINGERPRINT not in serialized


def test_cli_defaults_to_readonly_verify_and_emits_only_redacted_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    token_port = _TokenPort()

    status = teardown.main(
        [
            "--run-id",
            str(RUN_ID),
            "--novel-id",
            str(NOVEL_ID),
            "--document-id",
            str(DOCUMENT_ID),
            "--expected-token-fingerprint",
            TOKEN_FINGERPRINT,
        ],
        read_port_factory=_ReadPort,
        token_port_factory=lambda: token_port,
    )

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert status == 0
    assert captured.err == ""
    assert report["status"] == "VERIFIED"
    assert report["token_copies_destroyed"] is False
    assert token_port.destroy_expected == []
    assert TOKEN not in captured.out
    assert TOKEN_FINGERPRINT not in captured.out


@pytest.mark.parametrize("token_class", ("missing", "wrong", "old"))
def test_each_negative_token_class_must_be_hidden_with_no_store(
    token_class: str,
) -> None:
    with pytest.raises(teardown.TeardownError) as captured:
        teardown.verify_teardown(
            _config(),
            read_port=_ReadPort(fail_token_class=token_class),
            token_port=_TokenPort(),
        )

    assert captured.value.code == "HIDDEN_ROUTE_GATE_FAILED"


def test_t2_capability_matrix_drift_fails_closed() -> None:
    with pytest.raises(teardown.TeardownError) as captured:
        teardown.verify_teardown(
            _config(),
            read_port=_ReadPort(bad_t2_matrix=True),
            token_port=_TokenPort(),
        )

    assert captured.value.code == "T2_OVERVIEW_MATRIX_FAILED"


@pytest.mark.parametrize(
    ("formal_claim_present", "new_claims_allowed"),
    ((True, False), (False, True)),
)
def test_worker_target_must_have_no_formal_or_future_claim(
    formal_claim_present: bool,
    new_claims_allowed: bool,
) -> None:
    with pytest.raises(teardown.TeardownError) as captured:
        teardown.verify_teardown(
            _config(),
            read_port=_ReadPort(
                formal_claim_present=formal_claim_present,
                new_claims_allowed=new_claims_allowed,
            ),
            token_port=_TokenPort(),
        )

    assert captured.value.code == "WORKER_TARGET_CLAIM_REMAINS"


@pytest.mark.parametrize(
    ("container_fingerprint", "expected_code"),
    (
        (hashlib.sha256(b"different").hexdigest(), "TOKEN_COPIES_MISMATCH"),
        (None, "TOKEN_COPIES_INCOMPLETE"),
    ),
)
def test_token_copies_must_be_complete_identical_and_expected(
    container_fingerprint: str | None,
    expected_code: str,
) -> None:
    read_port = _ReadPort()
    with pytest.raises(teardown.TeardownError) as captured:
        teardown.verify_teardown(
            _config(),
            read_port=read_port,
            token_port=_TokenPort(container_fingerprint=container_fingerprint),
        )

    assert captured.value.code == expected_code
    assert read_port.requests == []


def test_expected_token_fingerprint_is_an_independent_binding() -> None:
    with pytest.raises(teardown.TeardownError) as captured:
        teardown.verify_teardown(
            _config(expected_token_fingerprint="a" * 64),
            read_port=_ReadPort(),
            token_port=_TokenPort(),
        )

    assert captured.value.code == "TOKEN_FINGERPRINT_MISMATCH"


def test_product_request_without_same_run_integration_pass_is_rejected() -> None:
    with pytest.raises(teardown.TeardownError) as captured:
        teardown.verify_teardown(
            _config(),
            read_port=_ReadPort(product_requested=True),
            token_port=_TokenPort(),
        )

    assert captured.value.code == "INTEGRATION_PASS_REQUIRED_FOR_PRODUCT"


def test_missing_or_forged_integration_pass_receipt_fails_closed() -> None:
    base = _config()
    valid_receipt, trusted_fingerprint = _integration_receipt(base)
    bound = replace(
        base,
        expected_integration_receipt_fingerprint=trusted_fingerprint,
    )

    with pytest.raises(teardown.TeardownError) as missing:
        teardown.verify_teardown(
            bound,
            read_port=_ReadPort(),
            token_port=_TokenPort(),
        )
    assert missing.value.code == "INTEGRATION_PASS_RECEIPT_MISSING"

    forged = dict(valid_receipt)
    forged["document_id"] = "40000000-0000-4000-8000-000000000001"
    forged_unsigned = dict(forged)
    forged_unsigned.pop("receipt_fingerprint")
    forged["receipt_fingerprint"] = teardown.integration_receipt_fingerprint(
        forged_unsigned
    )
    with pytest.raises(teardown.TeardownError) as invalid:
        teardown.verify_teardown(
            bound,
            read_port=_ReadPort(),
            token_port=_TokenPort(),
            integration_receipt=forged,
        )
    assert invalid.value.code == "INTEGRATION_PASS_RECEIPT_INVALID"


def test_valid_same_run_integration_receipt_is_bound_but_does_not_flip_t2() -> None:
    base = _config()
    receipt, trusted_fingerprint = _integration_receipt(base)
    bound = replace(
        base,
        expected_integration_receipt_fingerprint=trusted_fingerprint,
    )

    report = teardown.verify_teardown(
        bound,
        read_port=_ReadPort(),
        token_port=_TokenPort(),
        integration_receipt=receipt,
    )

    assert report["integration_pass_bound"] is True
    assert report["product_requested"] is False
    assert report["product_enabled"] is False


@pytest.mark.parametrize(
    ("confirm_teardown", "confirm_token_destroy", "expected_code"),
    (
        (
            "",
            teardown.TOKEN_DESTROY_CONFIRMATION,
            "TEARDOWN_DESTROY_CONFIRMATION_REQUIRED",
        ),
        (
            teardown.TEARDOWN_DESTROY_CONFIRMATION,
            "",
            "TOKEN_DESTROY_CONFIRMATION_REQUIRED",
        ),
    ),
)
def test_destroy_without_both_distinct_confirmations_performs_no_reads_or_destroy(
    confirm_teardown: str,
    confirm_token_destroy: str,
    expected_code: str,
) -> None:
    read_port = _ReadPort()
    token_port = _TokenPort()

    with pytest.raises(teardown.TeardownError) as captured:
        teardown.destroy_teardown(
            _config(),
            read_port=read_port,
            token_port=token_port,
            verified_fingerprint="a" * 64,
            confirm_teardown=confirm_teardown,
            confirm_token_destroy=confirm_token_destroy,
        )

    assert captured.value.code == expected_code
    assert read_port.requests == []
    assert token_port.host_reads == token_port.container_reads == 0
    assert token_port.destroy_expected == []


def test_destroy_reverifies_receipt_and_calls_exact_token_adapter_once() -> None:
    config = _config()
    initial_read_port = _ReadPort()
    initial_token_port = _TokenPort()
    verified = teardown.verify_teardown(
        config,
        read_port=initial_read_port,
        token_port=initial_token_port,
    )
    fingerprint = verified["verification_fingerprint"]
    assert isinstance(fingerprint, str)

    read_port = _ReadPort()
    token_port = _TokenPort()
    destroyed = teardown.destroy_teardown(
        config,
        read_port=read_port,
        token_port=token_port,
        verified_fingerprint=fingerprint,
        confirm_teardown=teardown.TEARDOWN_DESTROY_CONFIRMATION,
        confirm_token_destroy=teardown.TOKEN_DESTROY_CONFIRMATION,
    )

    assert destroyed["status"] == "DESTROYED"
    assert destroyed["verification_fingerprint"] == fingerprint
    assert destroyed["product_requested"] is False
    assert destroyed["product_enabled"] is False
    assert destroyed["token_copies_destroyed"] is True
    assert token_port.host_reads == token_port.container_reads == 2
    assert token_port.destroy_expected == [TOKEN_FINGERPRINT]
    assert TOKEN not in json.dumps(destroyed, sort_keys=True)


def test_fixed_destroy_adapter_delegates_directly_to_existing_provisioner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_path = Path("/private/t4k/token")

    class ContainerPort:
        def current_digest(self) -> str:
            return TOKEN_FINGERPRINT

    container = ContainerPort()
    calls: list[tuple[Path, object]] = []
    expected_result = {
        "schema_version": 1,
        "status": "DESTROYED",
        "host_token_present": False,
        "container_token_present": False,
        "secret_values_emitted": False,
    }
    monkeypatch.setattr(
        teardown.token_provisioner,
        "read_private_host_token",
        lambda path: TOKEN if path == private_path else pytest.fail("wrong path"),
    )

    def destroy(path: Path, port: object) -> dict[str, object]:
        calls.append((path, port))
        return dict(expected_result)

    monkeypatch.setattr(teardown.token_provisioner, "destroy_token", destroy)
    adapter = teardown._FixedProvisionerTokenPort(private_path, container)

    assert adapter.destroy_copies(TOKEN_FINGERPRINT) == expected_result
    assert calls == [(private_path, container)]


def test_default_container_fingerprint_probe_is_strictly_read_only() -> None:
    class ReadOnlyPort(teardown._ReadOnlyDockerContainerTokenPort):
        def __init__(self) -> None:
            self.calls: list[tuple[str, ...]] = []

        def _prepare_directory(self) -> None:
            pytest.fail("read-only verification attempted to prepare a directory")

        def _run(self, *args: str, timeout: float = 30) -> str:
            del timeout
            self.calls.append(args)
            return TOKEN_FINGERPRINT

    port = ReadOnlyPort()

    assert port.current_digest() == TOKEN_FINGERPRINT
    assert len(port.calls) == 1
    assert port.calls[0][:3] == (
        "exec",
        teardown.token_provisioner.QWENPAW_CONTAINER,
        "/app/venv/bin/python",
    )


def test_fixed_worker_claim_audit_uses_existing_postgres_read_only_transaction() -> None:
    events: list[object] = []

    class _Mappings:
        def one(self) -> dict[str, int]:
            events.append("one")
            return {"open_claim_count": 0}

    class _Result:
        def mappings(self) -> _Mappings:
            events.append("mappings")
            return _Mappings()

    class _Transaction:
        def rollback(self) -> None:
            events.append("rollback")

    class _Connection:
        def begin(self) -> _Transaction:
            events.append("begin")
            return _Transaction()

        def exec_driver_sql(self, statement: str) -> None:
            events.append(statement)

        def execute(self, statement: object, parameters: object) -> _Result:
            events.append((str(statement), parameters))
            return _Result()

        def close(self) -> None:
            events.append("close")

    class _Dialect:
        name = "postgresql"

    class _Engine:
        dialect = _Dialect()

        def connect(self) -> _Connection:
            events.append("connect")
            return _Connection()

    evidence = teardown._FixedPostgresWorkerClaimAudit(
        engine_provider=lambda: _Engine()
    ).read(_config())

    assert evidence == teardown.WorkerTargetEvidence(
        run_id=RUN_ID,
        novel_id=NOVEL_ID,
        document_id=DOCUMENT_ID,
        read_only=True,
        formal_claim_present=False,
        new_claims_allowed=False,
    )
    assert "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY" in events
    query, parameters = next(item for item in events if isinstance(item, tuple))
    assert "attempt.completed_at IS NULL" in query
    assert "narration.segment_render" in query
    assert parameters == {"novel_id": NOVEL_ID, "document_id": DOCUMENT_ID}
    assert events[-2:] == ["rollback", "close"]


def test_fixed_worker_claim_audit_rejects_non_postgres() -> None:
    class _Dialect:
        name = "sqlite"

    class _Engine:
        dialect = _Dialect()

    with pytest.raises(
        teardown.TeardownError,
        match="WORKER_CLAIM_AUDIT_UNAVAILABLE",
    ):
        teardown._FixedPostgresWorkerClaimAudit(
            engine_provider=lambda: _Engine()
        ).read(_config())


def test_cli_sanitizes_adapter_exception_without_traceback_secret_or_path(
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_path = "/Users/example/private/t4k/token"

    class FailingReadPort(_ReadPort):
        def request(
            self,
            *,
            path: str,
            validation_token: str | None,
        ) -> teardown.HttpObservation:
            raise RuntimeError(f"{private_path} contained {TOKEN}")

    status = teardown.main(
        [
            "--mode",
            "verify",
            "--run-id",
            str(RUN_ID),
            "--novel-id",
            str(NOVEL_ID),
            "--document-id",
            str(DOCUMENT_ID),
            "--expected-token-fingerprint",
            TOKEN_FINGERPRINT,
        ],
        read_port_factory=FailingReadPort,
        token_port_factory=_TokenPort,
    )

    captured = capsys.readouterr()
    assert status == 2
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "status": "FAILED",
        "code": "TEARDOWN_READ_FAILED",
    }
    assert TOKEN not in captured.err
    assert private_path not in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    "forbidden_arguments",
    (
        ("--host-token-file", "/tmp/token"),
        ("--api-base", "http://127.0.0.1:18088"),
        ("--dsn", "postgresql://example"),
        ("--adapter", "package.module:factory"),
        ("--viewport", "1920x1080"),
    ),
)
def test_cli_has_no_import_shell_dsn_path_or_viewport_injection_surface(
    forbidden_arguments: tuple[str, str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    factories_called: list[str] = []

    def read_factory() -> _ReadPort:
        factories_called.append("read")
        return _ReadPort()

    def token_factory() -> _TokenPort:
        factories_called.append("token")
        return _TokenPort()

    status = teardown.main(
        [
            "--run-id",
            str(RUN_ID),
            "--novel-id",
            str(NOVEL_ID),
            "--document-id",
            str(DOCUMENT_ID),
            "--expected-token-fingerprint",
            TOKEN_FINGERPRINT,
            *forbidden_arguments,
        ],
        read_port_factory=read_factory,
        token_port_factory=token_factory,
    )

    captured = capsys.readouterr()
    assert status == 2
    assert json.loads(captured.err) == {
        "status": "FAILED",
        "code": "ARGUMENTS_INVALID",
    }
    assert factories_called == []
