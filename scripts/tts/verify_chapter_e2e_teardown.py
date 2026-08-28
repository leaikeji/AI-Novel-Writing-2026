#!/usr/bin/env python3
"""Verify and explicitly destroy the hidden T4-K validation token.

The default mode is read-only.  It proves that the application has already
returned to the public T2 matrix before it permits token destruction.  This
module deliberately has no runtime switcher, database adapter, shell hook, or
user-selectable filesystem path.  The destructive CLI path uses only the
existing fixed validation-token provisioner and requires two distinct exact
confirmations plus a freshly reproduced verification fingerprint.

No viewport is accepted here.  The four desktop combinations remain owned by
the T4-K browser collector; this verifier adds no sub-1080p requirement.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import hmac
import json
from pathlib import Path
import re
import sys
from typing import Final, Protocol
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID


CURRENT_PAWAPP_ROOT: Final = Path(__file__).resolve().parents[2]
if str(CURRENT_PAWAPP_ROOT) not in sys.path:
    sys.path.insert(0, str(CURRENT_PAWAPP_ROOT))

from sqlalchemy import text

from backend.narration.privacy import t2_settings_capabilities
from scripts.tts import provision_validation_token as token_provisioner
from scripts.tts.chapter_e2e_executor import LoopbackHttpTransport
from scripts.tts.validate_chapter_e2e import API_PATH, LOOPBACK_HOSTS, RunnerError


REPORT_SCHEMA: Final = "moss-tts-t4k-teardown/1.0"
INTEGRATION_RECEIPT_SCHEMA: Final = "moss-tts-t4k-integration-pass/1.0"
WORK_PACKAGE: Final = "T4-K-TD"
INTEGRATION_WORK_PACKAGE: Final = "T4-K-I"
TEARDOWN_DESTROY_CONFIRMATION: Final = (
    "DESTROY-T4K-TEARDOWN-AFTER-READONLY-VERIFY"
)
TOKEN_DESTROY_CONFIRMATION: Final = token_provisioner.DESTROY_CONFIRMATION

_SAFE_CODE_RE: Final = re.compile(r"^[A-Z][A-Z0-9_]{1,95}$")
_SHA256_RE: Final = re.compile(r"^[a-f0-9]{64}$")
_TOKEN_RE: Final = re.compile(r"^[A-Za-z0-9_-]{43,128}$")
_MAX_JSON_BYTES: Final = 2 * 1024 * 1024
_T2_CAPABILITY_MATRIX_FINGERPRINT: Final = (
    "49809245b9bd9d9769c2f9b9fa0690a111dad807f23a8e842b8d248378c0f35e"
)
_GATE_NOT_FOUND_DETAIL: Final = {
    "code": "RESOURCE_NOT_FOUND",
    "message": "找不到请求的朗读资源。",
}
_HIDDEN_ROUTE_TEMPLATES: Final[tuple[tuple[str, str], ...]] = (
    ("synthesis", "/narration-requests/{identity}"),
    ("editor_production", "/narration-script-versions/{identity}"),
    ("player_manifest", "/narration-editions/{identity}/manifest"),
)
_NEGATIVE_TOKEN_CLASSES: Final = ("missing", "wrong", "old")
_INTEGRATION_RECEIPT_FIELDS: Final = frozenset(
    {
        "schema_version",
        "work_package",
        "decision",
        "run_id",
        "novel_id",
        "document_id",
        "product_requested",
        "product_enabled",
        "receipt_fingerprint",
    }
)


class TeardownError(RuntimeError):
    """Stable redacted failure safe for stderr and machine evidence."""

    def __init__(self, code: str) -> None:
        if _SAFE_CODE_RE.fullmatch(code) is None:
            raise ValueError("teardown error code must be stable")
        super().__init__(code)
        self.code = code


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # pragma: no cover - argparse owns it
        del message
        raise TeardownError("ARGUMENTS_INVALID")


@dataclass(frozen=True, slots=True)
class TeardownConfig:
    """Non-secret binding for one exact T4-K run and token fingerprint."""

    run_id: UUID
    novel_id: UUID
    document_id: UUID
    expected_token_fingerprint: str
    expected_integration_receipt_fingerprint: str | None = None

    def __post_init__(self) -> None:
        if any(
            type(value) is not UUID
            for value in (self.run_id, self.novel_id, self.document_id)
        ):
            raise TeardownError("TEARDOWN_BINDING_INVALID")
        if (
            type(self.expected_token_fingerprint) is not str
            or _SHA256_RE.fullmatch(self.expected_token_fingerprint) is None
        ):
            raise TeardownError("TOKEN_FINGERPRINT_INVALID")
        receipt_fingerprint = self.expected_integration_receipt_fingerprint
        if receipt_fingerprint is not None and (
            type(receipt_fingerprint) is not str
            or _SHA256_RE.fullmatch(receipt_fingerprint) is None
        ):
            raise TeardownError("INTEGRATION_RECEIPT_FINGERPRINT_INVALID")


@dataclass(frozen=True, slots=True)
class HttpObservation:
    """Bounded HTTP response shape accepted by the read-only verifier."""

    status: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True, slots=True)
class WorkerTargetEvidence:
    """Read-only, scope-bound evidence about the former validation target."""

    run_id: UUID
    novel_id: UUID
    document_id: UUID
    read_only: bool
    formal_claim_present: bool
    new_claims_allowed: bool


class TeardownReadPort(Protocol):
    """Only the bounded reads needed after an external runtime rollback."""

    def request(
        self,
        *,
        path: str,
        validation_token: str | None,
    ) -> HttpObservation: ...

    def worker_target_evidence(
        self,
        config: TeardownConfig,
    ) -> WorkerTargetEvidence: ...


class ValidationTokenPort(Protocol):
    """Private token access; secret values must never leave verifier memory."""

    def read_host_token(self) -> str: ...

    def read_container_fingerprint(self) -> str | None: ...

    def destroy_copies(self, expected_fingerprint: str) -> Mapping[str, object]: ...


def _canonical_fingerprint(value: object) -> str:
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeError) as error:
        raise TeardownError("CANONICAL_EVIDENCE_INVALID") from error
    return hashlib.sha256(payload).hexdigest()


def integration_receipt_fingerprint(receipt_without_fingerprint: object) -> str:
    """Return the canonical fingerprint used by a trusted T4-K-I receipt."""

    return _canonical_fingerprint(receipt_without_fingerprint)


def _validate_integration_receipt(
    config: TeardownConfig,
    receipt: Mapping[str, object] | None,
) -> bool:
    expected = config.expected_integration_receipt_fingerprint
    if receipt is None:
        if expected is not None:
            raise TeardownError("INTEGRATION_PASS_RECEIPT_MISSING")
        return False
    if expected is None or type(receipt) is not dict:
        raise TeardownError("INTEGRATION_PASS_RECEIPT_INVALID")
    if set(receipt) != _INTEGRATION_RECEIPT_FIELDS:
        raise TeardownError("INTEGRATION_PASS_RECEIPT_INVALID")
    observed_fingerprint = receipt.get("receipt_fingerprint")
    unsigned = dict(receipt)
    unsigned.pop("receipt_fingerprint", None)
    if (
        receipt.get("schema_version") != INTEGRATION_RECEIPT_SCHEMA
        or receipt.get("work_package") != INTEGRATION_WORK_PACKAGE
        or receipt.get("decision") != "PASS"
        or receipt.get("run_id") != str(config.run_id)
        or receipt.get("novel_id") != str(config.novel_id)
        or receipt.get("document_id") != str(config.document_id)
        or receipt.get("product_requested") is not True
        or receipt.get("product_enabled") is not True
        or type(observed_fingerprint) is not str
        or _SHA256_RE.fullmatch(observed_fingerprint) is None
    ):
        raise TeardownError("INTEGRATION_PASS_RECEIPT_INVALID")
    computed = integration_receipt_fingerprint(unsigned)
    if not hmac.compare_digest(observed_fingerprint, computed) or not hmac.compare_digest(
        observed_fingerprint,
        expected,
    ):
        raise TeardownError("INTEGRATION_PASS_RECEIPT_INVALID")
    return True


def _verify_token_copies(
    config: TeardownConfig,
    port: ValidationTokenPort,
) -> str:
    try:
        token = port.read_host_token()
    except TeardownError:
        raise
    except Exception as error:
        raise TeardownError("HOST_TOKEN_COPY_INVALID") from error
    if type(token) is not str or _TOKEN_RE.fullmatch(token) is None:
        raise TeardownError("HOST_TOKEN_COPY_INVALID")
    host_fingerprint = hashlib.sha256(token.encode("ascii", errors="strict")).hexdigest()
    try:
        container_fingerprint = port.read_container_fingerprint()
    except TeardownError:
        raise
    except Exception as error:
        raise TeardownError("CONTAINER_TOKEN_COPY_INVALID") from error
    if (
        type(container_fingerprint) is not str
        or _SHA256_RE.fullmatch(container_fingerprint) is None
    ):
        raise TeardownError("TOKEN_COPIES_INCOMPLETE")
    if not hmac.compare_digest(host_fingerprint, container_fingerprint):
        raise TeardownError("TOKEN_COPIES_MISMATCH")
    if not hmac.compare_digest(host_fingerprint, config.expected_token_fingerprint):
        raise TeardownError("TOKEN_FINGERPRINT_MISMATCH")
    return token


def _wrong_token(token: str) -> str:
    replacement = "A" if token[0] != "A" else "B"
    wrong = f"{replacement}{token[1:]}"
    if wrong == token or _TOKEN_RE.fullmatch(wrong) is None:
        raise TeardownError("NEGATIVE_TOKEN_GENERATION_FAILED")
    return wrong


def _header(response: HttpObservation, name: str) -> str | None:
    try:
        matches = [
            value
            for key, value in response.headers.items()
            if type(key) is str and key.casefold() == name.casefold()
        ]
    except Exception as error:
        raise TeardownError("HTTP_RESPONSE_INVALID") from error
    if len(matches) > 1 or any(type(value) is not str for value in matches):
        raise TeardownError("HTTP_RESPONSE_INVALID")
    return matches[0] if matches else None


def _response_json(response: HttpObservation, *, code: str) -> dict[str, object]:
    if type(response) is not HttpObservation or type(response.status) is not int:
        raise TeardownError(code)
    if type(response.body) is not bytes or len(response.body) > _MAX_JSON_BYTES:
        raise TeardownError(code)
    content_type = _header(response, "Content-Type")
    if content_type is not None and content_type.split(";", 1)[0].strip() not in {
        "application/json",
        "application/problem+json",
    }:
        raise TeardownError(code)

    def reject_duplicate_keys(
        pairs: list[tuple[str, object]],
    ) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    try:
        payload = json.loads(
            response.body.decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicate_keys,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise TeardownError(code) from error
    if type(payload) is not dict:
        raise TeardownError(code)
    return payload


def _request(
    port: TeardownReadPort,
    *,
    path: str,
    validation_token: str | None,
) -> HttpObservation:
    try:
        response = port.request(path=path, validation_token=validation_token)
    except TeardownError:
        raise
    except Exception as error:
        raise TeardownError("TEARDOWN_READ_FAILED") from error
    if type(response) is not HttpObservation:
        raise TeardownError("HTTP_RESPONSE_INVALID")
    return response


def _assert_hidden_route(response: HttpObservation) -> None:
    code = "HIDDEN_ROUTE_GATE_FAILED"
    if response.status != 404 or _header(response, "Cache-Control") != "no-store":
        raise TeardownError(code)
    payload = _response_json(response, code=code)
    if payload != {"detail": _GATE_NOT_FOUND_DETAIL}:
        raise TeardownError(code)


def _assert_t2_overview(
    response: HttpObservation,
    *,
    novel_id: UUID,
) -> None:
    code = "T2_OVERVIEW_MATRIX_FAILED"
    if response.status != 200:
        raise TeardownError(code)
    payload = _response_json(response, code=code)
    runtime = payload.get("runtime")
    try:
        expected_capabilities = t2_settings_capabilities().model_dump(mode="json")
    except Exception as error:
        raise TeardownError("T2_CAPABILITY_BASELINE_INVALID") from error
    if (
        _canonical_fingerprint(expected_capabilities)
        != _T2_CAPABILITY_MATRIX_FINGERPRINT
    ):
        raise TeardownError("T2_CAPABILITY_BASELINE_INVALID")
    if (
        payload.get("contract_version") != "narration-settings-api/1"
        or payload.get("novel_id") != str(novel_id)
        or payload.get("capabilities") != expected_capabilities
        or type(runtime) is not dict
        or runtime.get("product_visible") is not False
    ):
        raise TeardownError(code)


def _read_health(port: TeardownReadPort) -> tuple[bool, bool]:
    response = _request(port, path="/health", validation_token=None)
    if response.status != 200:
        raise TeardownError("T2_RUNTIME_STATUS_INVALID")
    payload = _response_json(response, code="T2_RUNTIME_STATUS_INVALID")
    database = payload.get("database")
    technical = payload.get("narration")
    production = payload.get("narration_production")
    if type(database) is not dict or type(technical) is not dict or type(production) is not dict:
        raise TeardownError("T2_RUNTIME_STATUS_INVALID")
    product_requested = production.get("product_requested")
    product_enabled = technical.get("product_visible")
    if type(product_requested) is not bool or type(product_enabled) is not bool:
        raise TeardownError("T2_RUNTIME_STATUS_INVALID")
    if (
        payload.get("status") != "ready"
        or database.get("connected") is not True
        or technical.get("technical_enabled") is not True
        or technical.get("lifecycle_status") != "ready"
        or technical.get("sidecar_reachable") is not True
        or technical.get("model_ready") is not True
        or technical.get("reason_code") is not None
        or production.get("lifecycle_status") != "playback_only"
        or production.get("playback_installed") is not True
        or production.get("digest_keyring_loaded") is not False
        or production.get("production_backend_installed") is not False
        or production.get("worker_running") is not False
        or production.get("reference_clone_ready") is not False
        or production.get("reason_code") is not None
    ):
        raise TeardownError("T2_RUNTIME_STATUS_INVALID")
    return product_requested, product_enabled


def _assert_worker_target_released(
    port: TeardownReadPort,
    config: TeardownConfig,
) -> None:
    try:
        evidence = port.worker_target_evidence(config)
    except TeardownError:
        raise
    except Exception as error:
        raise TeardownError("WORKER_CLAIM_AUDIT_UNAVAILABLE") from error
    if type(evidence) is not WorkerTargetEvidence:
        raise TeardownError("WORKER_CLAIM_EVIDENCE_INVALID")
    if (
        evidence.run_id != config.run_id
        or evidence.novel_id != config.novel_id
        or evidence.document_id != config.document_id
        or evidence.read_only is not True
        or type(evidence.formal_claim_present) is not bool
        or type(evidence.new_claims_allowed) is not bool
    ):
        raise TeardownError("WORKER_CLAIM_EVIDENCE_INVALID")
    if evidence.formal_claim_present or evidence.new_claims_allowed:
        raise TeardownError("WORKER_TARGET_CLAIM_REMAINS")


def _verification_fingerprint(
    config: TeardownConfig,
    report_without_fingerprint: Mapping[str, object],
) -> str:
    return _canonical_fingerprint(
        {
            "schema_version": REPORT_SCHEMA,
            "run_id": str(config.run_id),
            "novel_id": str(config.novel_id),
            "document_id": str(config.document_id),
            "expected_token_fingerprint": config.expected_token_fingerprint,
            "expected_integration_receipt_fingerprint": (
                config.expected_integration_receipt_fingerprint
            ),
            "report": dict(report_without_fingerprint),
        }
    )


def verify_teardown(
    config: TeardownConfig,
    *,
    read_port: TeardownReadPort,
    token_port: ValidationTokenPort,
    integration_receipt: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Perform the complete read-only T2 teardown verification."""

    if type(config) is not TeardownConfig:
        raise TeardownError("TEARDOWN_BINDING_INVALID")
    integration_pass_bound = _validate_integration_receipt(
        config,
        integration_receipt,
    )
    old_token = _verify_token_copies(config, token_port)
    product_requested, product_enabled = _read_health(read_port)
    if (product_requested or product_enabled) and not integration_pass_bound:
        raise TeardownError("INTEGRATION_PASS_REQUIRED_FOR_PRODUCT")
    # A valid integration receipt is only a necessary input to a later
    # T4-GATE.  TD itself must still observe the already restored T2 matrix.
    if product_requested or product_enabled:
        raise TeardownError("TEARDOWN_T2_RUNTIME_REQUIRED")

    tokens: tuple[tuple[str, str | None], ...] = (
        ("missing", None),
        ("wrong", _wrong_token(old_token)),
        ("old", old_token),
    )
    overview_path = f"/novels/{config.novel_id}/narration-overview"
    for token_class, token in tokens:
        if token_class not in _NEGATIVE_TOKEN_CLASSES:  # pragma: no cover
            raise TeardownError("NEGATIVE_TOKEN_CLASS_INVALID")
        for _route_class, template in _HIDDEN_ROUTE_TEMPLATES:
            _assert_hidden_route(
                _request(
                    read_port,
                    path=template.format(identity=config.document_id),
                    validation_token=token,
                )
            )
        _assert_t2_overview(
            _request(
                read_port,
                path=overview_path,
                validation_token=token,
            ),
            novel_id=config.novel_id,
        )
    _assert_worker_target_released(read_port, config)

    report: dict[str, object] = {
        "schema_version": REPORT_SCHEMA,
        "work_package": WORK_PACKAGE,
        "status": "VERIFIED",
        "decision": "T2_TEARDOWN_VERIFIED",
        "product_requested": False,
        "product_enabled": False,
        "integration_pass_bound": integration_pass_bound,
        "validation_hidden": True,
        "negative_token_classes": list(_NEGATIVE_TOKEN_CLASSES),
        "hidden_route_classes": [name for name, _path in _HIDDEN_ROUTE_TEMPLATES],
        "overview_tier": "T2",
        "worker_target_formal_claim_present": False,
        "worker_target_new_claims_allowed": False,
        "token_copies_identical": True,
        "expected_token_fingerprint_bound": True,
        "token_copies_destroyed": False,
        "secret_values_emitted": False,
        "private_paths_emitted": False,
        "viewport_requirements_changed": False,
    }
    report["verification_fingerprint"] = _verification_fingerprint(config, report)
    return report


def destroy_teardown(
    config: TeardownConfig,
    *,
    read_port: TeardownReadPort,
    token_port: ValidationTokenPort,
    verified_fingerprint: str,
    confirm_teardown: str,
    confirm_token_destroy: str,
    integration_receipt: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Re-verify T2, then call the one fixed token-destroy port."""

    if confirm_teardown != TEARDOWN_DESTROY_CONFIRMATION:
        raise TeardownError("TEARDOWN_DESTROY_CONFIRMATION_REQUIRED")
    if confirm_token_destroy != TOKEN_DESTROY_CONFIRMATION:
        raise TeardownError("TOKEN_DESTROY_CONFIRMATION_REQUIRED")
    if confirm_teardown == confirm_token_destroy:
        raise TeardownError("DISTINCT_DESTROY_CONFIRMATIONS_REQUIRED")
    if type(verified_fingerprint) is not str or _SHA256_RE.fullmatch(
        verified_fingerprint
    ) is None:
        raise TeardownError("VERIFICATION_FINGERPRINT_INVALID")

    verification = verify_teardown(
        config,
        read_port=read_port,
        token_port=token_port,
        integration_receipt=integration_receipt,
    )
    observed_verification = verification.get("verification_fingerprint")
    if type(observed_verification) is not str or not hmac.compare_digest(
        observed_verification,
        verified_fingerprint,
    ):
        raise TeardownError("VERIFICATION_FINGERPRINT_MISMATCH")

    # Re-read both copies immediately before entering the fixed adapter.  The
    # adapter repeats the expected-fingerprint check before delegating to the
    # provisioner's identity-preserving destroy_token implementation.
    _verify_token_copies(config, token_port)
    try:
        destroyed = token_port.destroy_copies(config.expected_token_fingerprint)
    except TeardownError:
        raise
    except Exception as error:
        raise TeardownError("TOKEN_DESTROY_FAILED") from error
    if type(destroyed) is not dict or destroyed != {
        "schema_version": 1,
        "status": "DESTROYED",
        "host_token_present": False,
        "container_token_present": False,
        "secret_values_emitted": False,
    }:
        raise TeardownError("TOKEN_DESTROY_RESULT_INVALID")

    return {
        "schema_version": REPORT_SCHEMA,
        "work_package": WORK_PACKAGE,
        "status": "DESTROYED",
        "decision": "T2_TEARDOWN_TOKEN_DESTROYED",
        "verification_fingerprint": observed_verification,
        "product_requested": False,
        "product_enabled": False,
        "token_copies_destroyed": True,
        "secret_values_emitted": False,
        "private_paths_emitted": False,
    }


class _FixedProvisionerTokenPort:
    """The only destructive adapter used by the CLI."""

    def __init__(
        self,
        host_token_path: Path,
        container_port: token_provisioner.ContainerTokenPort,
    ) -> None:
        self._host_token_path = host_token_path
        self._container_port = container_port

    @classmethod
    def from_public_install_configuration(cls) -> "_FixedProvisionerTokenPort":
        # Imported lazily so importing this offline-testable module never reads
        # host configuration or opens Docker.
        from scripts import qwenpaw_lab_plugin

        try:
            host_path = qwenpaw_lab_plugin.validation_host_token_path()
            container_port = _ReadOnlyDockerContainerTokenPort()
        except Exception as error:
            raise TeardownError("TOKEN_ADAPTER_INITIALIZATION_FAILED") from error
        return cls(host_path, container_port)

    def read_host_token(self) -> str:
        try:
            return token_provisioner.read_private_host_token(self._host_token_path)
        except Exception as error:
            raise TeardownError("HOST_TOKEN_COPY_INVALID") from error

    def read_container_fingerprint(self) -> str | None:
        try:
            return self._container_port.current_digest()
        except Exception as error:
            raise TeardownError("CONTAINER_TOKEN_COPY_INVALID") from error

    def destroy_copies(self, expected_fingerprint: str) -> Mapping[str, object]:
        token = self.read_host_token()
        host_fingerprint = hashlib.sha256(token.encode("ascii")).hexdigest()
        container_fingerprint = self.read_container_fingerprint()
        if (
            type(container_fingerprint) is not str
            or not hmac.compare_digest(host_fingerprint, container_fingerprint)
            or not hmac.compare_digest(host_fingerprint, expected_fingerprint)
        ):
            raise TeardownError("TOKEN_DESTROY_IDENTITY_MISMATCH")
        try:
            return token_provisioner.destroy_token(
                self._host_token_path,
                self._container_port,
            )
        except Exception as error:
            raise TeardownError("TOKEN_DESTROY_FAILED") from error


class _ReadOnlyDockerContainerTokenPort(
    token_provisioner.DockerContainerTokenPort
):
    """Use the provisioner's fixed Docker argv without creating directories.

    The upstream provisioner's ``current_digest`` prepares its target directory
    for provision mode.  TD verify must be strictly read-only, so this narrow
    subclass keeps the same fixed container validation and destroy adapter but
    refuses to create a missing directory while reading the digest.
    """

    def current_digest(self) -> str | None:
        code = (
            "import hashlib,os,re,stat,sys; d,p=sys.argv[1:3]; "
            "d_exists=os.path.lexists(d); "
            "sys.stdout.write('MISSING') if not d_exists else None; "
            "sys.exit(0) if not d_exists else None; "
            "ds=os.lstat(d); "
            "d_ok=stat.S_ISDIR(ds.st_mode) and not stat.S_ISLNK(ds.st_mode) "
            "and ds.st_uid==os.geteuid() and stat.S_IMODE(ds.st_mode)==0o700; "
            "sys.exit(64) if not d_ok else None; "
            "exists=os.path.lexists(p); "
            "sys.stdout.write('MISSING') if not exists else None; "
            "sys.exit(0) if not exists else None; "
            "fd=os.open(p,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW); "
            "s=os.fstat(fd); b=os.read(fd,129); os.close(fd); "
            "ok=stat.S_ISREG(s.st_mode) and s.st_nlink==1 "
            "and s.st_uid==os.geteuid() and stat.S_IMODE(s.st_mode)==0o600 "
            "and len(b)==s.st_size and re.fullmatch(b'[A-Za-z0-9_-]{43,128}',b); "
            "sys.stdout.write(hashlib.sha256(b).hexdigest()) if ok else None; "
            "sys.exit(0 if ok else 64)"
        )
        try:
            value = self._run(
                "exec",
                token_provisioner.QWENPAW_CONTAINER,
                "/app/venv/bin/python",
                "-c",
                code,
                token_provisioner.CONTAINER_TOKEN_DIRECTORY,
                token_provisioner.CONTAINER_TOKEN_FILE,
            )
        except Exception as error:
            raise TeardownError("CONTAINER_TOKEN_COPY_INVALID") from error
        if value == "MISSING":
            return None
        if _SHA256_RE.fullmatch(value) is None:
            raise TeardownError("CONTAINER_TOKEN_COPY_INVALID")
        return value


class _FixedLoopbackReadPort:
    """Fixed no-redirect HTTP reads against the existing public lab URL."""

    def __init__(
        self,
        api_base: str,
        *,
        worker_claim_audit: "_FixedPostgresWorkerClaimAudit | None" = None,
    ) -> None:
        # Constructor validation is read-only and pins every later request to
        # one loopback origin and the PawApp API prefix.
        try:
            LoopbackHttpTransport(api_base, maximum_response_bytes=_MAX_JSON_BYTES)
        except Exception as error:
            raise TeardownError("LOOPBACK_CONFIGURATION_INVALID") from error
        self._api_base = api_base
        self._worker_claim_audit = (
            _FixedPostgresWorkerClaimAudit()
            if worker_claim_audit is None
            else worker_claim_audit
        )

    @classmethod
    def from_public_install_configuration(cls) -> "_FixedLoopbackReadPort":
        from scripts import qwenpaw_lab_plugin

        parsed = urlsplit(qwenpaw_lab_plugin.BASE_URL)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in LOOPBACK_HOSTS
            or parsed.port is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path.rstrip("/")
        ):
            raise TeardownError("LOOPBACK_CONFIGURATION_INVALID")
        host = (
            f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
        )
        api_base = urlunsplit(("http", f"{host}:{parsed.port}", API_PATH, "", ""))
        return cls(api_base)

    def request(
        self,
        *,
        path: str,
        validation_token: str | None,
    ) -> HttpObservation:
        try:
            transport = LoopbackHttpTransport(
                self._api_base,
                validation_token=validation_token,
                maximum_response_bytes=_MAX_JSON_BYTES,
            )
            response = transport.request(
                method="GET",
                path=path,
                timeout_seconds=30,
            )
        except RunnerError as error:
            raise TeardownError("LOOPBACK_READ_FAILED") from error
        except Exception as error:
            raise TeardownError("LOOPBACK_READ_FAILED") from error
        return HttpObservation(
            status=response.status,
            headers=dict(response.headers),
            body=response.body,
        )

    def worker_target_evidence(
        self,
        config: TeardownConfig,
    ) -> WorkerTargetEvidence:
        # `_read_health` has already proved that the only in-process worker is
        # stopped and its production backend is uninstalled.  This fixed,
        # read-only PostgreSQL audit independently proves that the exact target
        # has no unfinished segment-render attempt.  Raw scope IDs therefore
        # stay out of the public `/health` response.
        return self._worker_claim_audit.read(config)


class _FixedPostgresWorkerClaimAudit:
    """Read one exact target in the existing project PostgreSQL, never a DSN."""

    _QUERY: Final = """
        SELECT count(*) AS open_claim_count
        FROM background_job_attempts AS attempt
        JOIN background_jobs AS job ON job.id = attempt.job_id
        JOIN narration_requests AS request ON request.id = job.request_id
        WHERE attempt.completed_at IS NULL
          AND job.job_kind = 'narration.segment_render'
          AND job.novel_id = :novel_id
          AND (
              request.document_id = :document_id
              OR EXISTS (
                  SELECT 1
                  FROM narration_request_sources AS source
                  WHERE source.request_id = request.id
                    AND source.novel_id = :novel_id
                    AND source.document_id = :document_id
              )
          )
    """

    def __init__(self, engine_provider: Callable[[], object] | None = None) -> None:
        self._engine_provider = engine_provider

    def _engine(self) -> object:
        if self._engine_provider is not None:
            return self._engine_provider()
        from backend.database import get_engine

        return get_engine()

    def read(self, config: TeardownConfig) -> WorkerTargetEvidence:
        connection = None
        transaction = None
        try:
            engine = self._engine()
            dialect = getattr(engine, "dialect", None)
            if getattr(dialect, "name", None) != "postgresql":
                raise TeardownError("WORKER_CLAIM_AUDIT_UNAVAILABLE")
            connection = engine.connect()  # type: ignore[attr-defined]
            transaction = connection.begin()
            connection.exec_driver_sql(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
            )
            row = connection.execute(
                text(self._QUERY),
                {
                    "novel_id": config.novel_id,
                    "document_id": config.document_id,
                },
            ).mappings().one()
            count = row.get("open_claim_count")
            if type(count) is not int or count < 0:
                raise TeardownError("WORKER_CLAIM_EVIDENCE_INVALID")
            transaction.rollback()
            transaction = None
            return WorkerTargetEvidence(
                run_id=config.run_id,
                novel_id=config.novel_id,
                document_id=config.document_id,
                read_only=True,
                formal_claim_present=count != 0,
                new_claims_allowed=False,
            )
        except TeardownError:
            raise
        except Exception as error:
            raise TeardownError("WORKER_CLAIM_AUDIT_UNAVAILABLE") from error
        finally:
            if transaction is not None:
                try:
                    transaction.rollback()
                except Exception:
                    pass
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass


def build_parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("verify", "destroy"), default="verify")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--novel-id", required=True)
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--expected-token-fingerprint", required=True)
    parser.add_argument("--verified-fingerprint")
    parser.add_argument("--confirm-teardown")
    parser.add_argument("--confirm-token-destroy")
    return parser


def _config_from_arguments(args: argparse.Namespace) -> TeardownConfig:
    try:
        return TeardownConfig(
            run_id=UUID(args.run_id),
            novel_id=UUID(args.novel_id),
            document_id=UUID(args.document_id),
            expected_token_fingerprint=args.expected_token_fingerprint,
        )
    except TeardownError:
        raise
    except (AttributeError, TypeError, ValueError) as error:
        raise TeardownError("TEARDOWN_BINDING_INVALID") from error


ReadPortFactory = Callable[[], TeardownReadPort]
TokenPortFactory = Callable[[], ValidationTokenPort]


def main(
    argv: Sequence[str] | None = None,
    *,
    read_port_factory: ReadPortFactory | None = None,
    token_port_factory: TokenPortFactory | None = None,
) -> int:
    try:
        args = build_parser().parse_args(argv)
        config = _config_from_arguments(args)
        if args.mode == "verify" and any(
            value is not None
            for value in (
                args.verified_fingerprint,
                args.confirm_teardown,
                args.confirm_token_destroy,
            )
        ):
            raise TeardownError("DESTROY_ARGUMENTS_NOT_ALLOWED_IN_VERIFY")
        try:
            read_port = (
                _FixedLoopbackReadPort.from_public_install_configuration()
                if read_port_factory is None
                else read_port_factory()
            )
            token_port = (
                _FixedProvisionerTokenPort.from_public_install_configuration()
                if token_port_factory is None
                else token_port_factory()
            )
        except TeardownError:
            raise
        except Exception as error:
            raise TeardownError("ADAPTER_INITIALIZATION_FAILED") from error

        if args.mode == "verify":
            result = verify_teardown(
                config,
                read_port=read_port,
                token_port=token_port,
            )
        else:
            result = destroy_teardown(
                config,
                read_port=read_port,
                token_port=token_port,
                verified_fingerprint=args.verified_fingerprint,
                confirm_teardown=args.confirm_teardown,
                confirm_token_destroy=args.confirm_token_destroy,
            )
        sys.stdout.write(
            json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        )
        return 0
    except TeardownError as error:
        sys.stderr.write(
            json.dumps(
                {"status": "FAILED", "code": error.code},
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        return 2
    except KeyboardInterrupt:
        sys.stderr.write('{"code":"TEARDOWN_INTERRUPTED","status":"FAILED"}\n')
        return 130
    except Exception:
        sys.stderr.write('{"code":"TEARDOWN_INTERNAL_ERROR","status":"FAILED"}\n')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
