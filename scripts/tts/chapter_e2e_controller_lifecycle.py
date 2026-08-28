#!/usr/bin/env python3
"""Fixed local controller lifecycle plus an experimental signed candidate.

The public entry point accepts only the private probe-request path, exact
novel/document scope and the in-memory validation bearer.  It does not accept
browser observations, runtime samples, evidence DTOs, verdicts, hashes, page
URLs, host objects, signer objects or signing context.

The active product path is an author/operator-run local evidence executor.  It
does not claim cryptographic remote attestation and does not require an OS
service, dedicated identity, SSHSIG key or trust root.  The older signed path
is retained below only as a non-blocking experiment and is excluded from the
PawApp production package.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
from typing import Callable, Final, Mapping
from uuid import UUID

import scripts.tts.chapter_e2e_collector as collector
from scripts.tts.chapter_e2e_browser_observer import (
    BrowserObservationRequest,
    BrowserObserverError,
    PENDING_GAP_NOT_OBSERVED_REASON_CODES,
    VerifiedBrowserObservation,
    _run_fixed_browser_observer,
)
from scripts.tts.chapter_e2e_collector import (
    COLLECTOR_CONTROLLER_AUTHORITY_HOLD_ERROR,
    CONTROLLER_PREFLIGHT_FILENAME,
    CONTROLLER_PREFLIGHT_SIGNATURE_FILENAME,
    CollectorError,
    CollectorRequest,
    CollectorResult,
    FixedChapterE2ECollector,
    FixedControllerEvidence,
    _VerifiedRequestPreflight,
)
from scripts.tts.chapter_e2e_controller_evidence import (
    ControllerEvidenceAssemblyError,
    assemble_fixed_controller_evidence,
    validate_fixed_browser_evidence,
)
from scripts.tts.chapter_e2e_controller_build import (
    fixed_controller_build_sha256,
    fixed_local_operator_build_sha256,
)
from scripts.tts.chapter_e2e_controller_host import (
    CanonicalControllerArtifact,
    ControllerHostError,
    ReportBindingObservation,
    _fixed_controller_host,
)
from scripts.tts.chapter_e2e_controller_signer import ControllerSigningError
from scripts.tts.chapter_e2e_controller_trust import (
    CONTROLLER_ID,
    CONTROLLER_REPORT_BINDING_SCHEMA_VERSION,
    CONTROLLER_TRUST_ROOT_HOLD_ERROR,
    FIXED_REQUIRED_CAPTURES,
    FIXED_REQUIRED_STABILITY_MILLISECONDS,
    REPORT_SIGNATURE_NAMESPACE,
    ControllerTrustError,
    FixedControllerTrustVerifier,
    _decode_canonical_mapping,
    canonical_json_bytes,
)
from scripts.tts.chapter_e2e_probe_request import PROBE_REQUEST_FILENAME
from scripts.tts.chapter_e2e_runtime_observer import (
    RuntimeObservationResult,
    RuntimeObserverError,
    collect_runtime_observations,
)


CONTROLLER_LIFECYCLE_INPUT_INVALID: Final = (
    "CONTROLLER_LIFECYCLE_INPUT_INVALID"
)
CONTROLLER_LIFECYCLE_AUTHORITY_HOLD: Final = (
    "CONTROLLER_LIFECYCLE_AUTHORITY_HOLD"
)
CONTROLLER_LIFECYCLE_REQUEST_HOLD: Final = (
    "CONTROLLER_LIFECYCLE_REQUEST_HOLD"
)
CONTROLLER_LIFECYCLE_REQUEST_DRIFT: Final = (
    "CONTROLLER_LIFECYCLE_REQUEST_DRIFT"
)
CONTROLLER_LIFECYCLE_BROWSER_HOLD: Final = (
    "CONTROLLER_LIFECYCLE_BROWSER_HOLD"
)
CONTROLLER_LIFECYCLE_RUNTIME_HOLD: Final = (
    "CONTROLLER_LIFECYCLE_RUNTIME_HOLD"
)
CONTROLLER_LIFECYCLE_SOURCE_HOLD: Final = (
    "CONTROLLER_LIFECYCLE_SOURCE_HOLD"
)
CONTROLLER_LIFECYCLE_BINDING_HOLD: Final = (
    "CONTROLLER_LIFECYCLE_BINDING_HOLD"
)
CONTROLLER_LIFECYCLE_SIGNING_PORT_HOLD: Final = (
    "CONTROLLER_LIFECYCLE_SIGNING_PORT_HOLD"
)
CONTROLLER_LIFECYCLE_FINALIZE_HOLD: Final = (
    "CONTROLLER_LIFECYCLE_FINALIZE_HOLD"
)
_LOCAL_OPERATOR_COLLECTOR_CODES: Final = frozenset(
    {
        "COLLECTOR_EVIDENCE_INVALID",
        "COLLECTOR_SOURCE_INVALID",
        "COLLECTOR_SYNTHETIC_NOT_FORMAL",
        "COLLECTOR_COLLECTION_TIME_INVALID",
        "COLLECTOR_BROWSER_INVALID",
        "COLLECTOR_CAPTURE_MATRIX_INVALID",
        "COLLECTOR_CAPTURE_INVALID",
        "COLLECTOR_BROWSER_GATE_FAILED",
        "COLLECTOR_RUNTIME_INVALID",
        "COLLECTOR_RUNTIME_GATE_FAILED",
    }
)

_TOKEN = re.compile(r"^[A-Za-z0-9_-]{43,128}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ControllerLifecycleError(RuntimeError):
    """Fail-closed lifecycle error exposing only a stable code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class _VerifiedRequestSnapshot:
    request: CollectorRequest
    parent: Path
    parent_identity: tuple[int, ...]
    request_bytes: bytes
    request_identity: tuple[int, ...]
    preflight_payload: bytes
    preflight_payload_identity: tuple[int, ...]
    preflight_signature: bytes
    preflight_signature_identity: tuple[int, ...]
    verified_preflight: _VerifiedRequestPreflight


@dataclass(frozen=True, slots=True)
class _LocalRequestSnapshot:
    request: CollectorRequest
    parent: Path
    parent_identity: tuple[int, ...]
    request_bytes: bytes
    request_identity: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _LifecycleDependencies:
    require_authority: Callable[[datetime], None]
    controller_build_sha256: Callable[[], str]
    load_verified_request: Callable[
        [Path, datetime], _VerifiedRequestSnapshot
    ]
    run_browser: Callable[
        [BrowserObservationRequest], VerifiedBrowserObservation
    ]
    collect_runtime: Callable[[str, str, str], RuntimeObservationResult]
    build_report_binding: Callable[
        [ReportBindingObservation], CanonicalControllerArtifact
    ]
    sign_report_binding: Callable[[CanonicalControllerArtifact], bytes]
    finalize_report: Callable[
        [
            Path,
            FixedControllerEvidence,
            bytes,
            bytes,
            datetime,
        ],
        CollectorResult,
    ]
    utc_now: Callable[[], datetime]


def _error(code: str) -> ControllerLifecycleError:
    return ControllerLifecycleError(code)


def _canonical_uuid(value: object) -> str:
    if type(value) is not str:
        raise _error(CONTROLLER_LIFECYCLE_INPUT_INVALID)
    try:
        canonical = str(UUID(value))
    except (AttributeError, ValueError):
        raise _error(CONTROLLER_LIFECYCLE_INPUT_INVALID) from None
    if value != canonical:
        raise _error(CONTROLLER_LIFECYCLE_INPUT_INVALID)
    return canonical


def _now(dependencies: _LifecycleDependencies) -> datetime:
    try:
        value = dependencies.utc_now()
    except Exception:
        raise _error(CONTROLLER_LIFECYCLE_REQUEST_HOLD) from None
    if type(value) is not datetime or value.tzinfo is None:
        raise _error(CONTROLLER_LIFECYCLE_REQUEST_HOLD)
    return value.astimezone(timezone.utc).replace(microsecond=0)


def _controller_build_identity(dependencies: _LifecycleDependencies) -> str:
    try:
        value = dependencies.controller_build_sha256()
    except Exception:
        raise _error(CONTROLLER_LIFECYCLE_SOURCE_HOLD) from None
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise _error(CONTROLLER_LIFECYCLE_SOURCE_HOLD)
    return value


def _require_production_authority(now: datetime) -> None:
    """Check the fixed public root before any costly or private observation."""

    try:
        policy, _allowed = FixedControllerTrustVerifier()._load_policy()
    except ControllerTrustError as error:
        if error.code == CONTROLLER_TRUST_ROOT_HOLD_ERROR:
            raise _error(CONTROLLER_LIFECYCLE_AUTHORITY_HOLD) from None
        raise _error(CONTROLLER_LIFECYCLE_REQUEST_HOLD) from None
    if not any(
        key.status == "active" and key.not_before <= now < key.not_after
        for key in policy.keys
    ):
        raise _error(CONTROLLER_LIFECYCLE_AUTHORITY_HOLD)


def _production_load_verified_request(
    path: Path,
    now: datetime,
) -> _VerifiedRequestSnapshot:
    request, parent, parent_identity = collector._load_request(path, now=now)
    verified = collector._verify_request_controller_preflight(
        request,
        parent,
        parent_identity,
    )
    (
        request_raw,
        _request_payload,
        request_parent,
        request_parent_identity,
        request_identity,
    ) = collector._read_private_json(
        path,
        expected_filename=PROBE_REQUEST_FILENAME,
        name_error_code="COLLECTOR_REQUEST_NAME_INVALID",
        json_error_code="COLLECTOR_REQUEST_INVALID",
    )
    (
        preflight_raw,
        _preflight_payload,
        preflight_parent,
        preflight_parent_identity,
        preflight_identity,
    ) = collector._read_private_json(
        parent / CONTROLLER_PREFLIGHT_FILENAME,
        expected_filename=CONTROLLER_PREFLIGHT_FILENAME,
        name_error_code="COLLECTOR_CONTROLLER_PREFLIGHT_INVALID",
        json_error_code="COLLECTOR_CONTROLLER_PREFLIGHT_INVALID",
    )
    signature_raw, signature_identity = collector._read_private_sibling_bytes(
        parent,
        parent_identity,
        filename=CONTROLLER_PREFLIGHT_SIGNATURE_FILENAME,
    )
    if (
        request_parent != parent
        or request_parent_identity != parent_identity
        or preflight_parent != parent
        or preflight_parent_identity != parent_identity
        or hashlib.sha256(request_raw).hexdigest() != request.request_sha256
        or hashlib.sha256(preflight_raw).hexdigest()
        != request.preflight_payload_sha256
        or preflight_identity != verified.payload_identity
        or signature_identity != verified.signature_identity
    ):
        raise CollectorError("COLLECTOR_FILE_UNSAFE")
    return _VerifiedRequestSnapshot(
        request=request,
        parent=parent,
        parent_identity=parent_identity,
        request_bytes=request_raw,
        request_identity=request_identity,
        preflight_payload=preflight_raw,
        preflight_payload_identity=preflight_identity,
        preflight_signature=signature_raw,
        preflight_signature_identity=signature_identity,
        verified_preflight=verified,
    )


def _load_local_request_snapshot(
    path: Path,
    now: datetime,
) -> _LocalRequestSnapshot:
    """Pin one private request without requiring a signature artifact."""

    request, parent, parent_identity = collector._load_request(path, now=now)
    (
        request_raw,
        _request_payload,
        request_parent,
        request_parent_identity,
        request_identity,
    ) = collector._read_private_json(
        path,
        expected_filename=PROBE_REQUEST_FILENAME,
        name_error_code="COLLECTOR_REQUEST_NAME_INVALID",
        json_error_code="COLLECTOR_REQUEST_INVALID",
    )
    if (
        request_parent != parent
        or request_parent_identity != parent_identity
        or hashlib.sha256(request_raw).hexdigest() != request.request_sha256
    ):
        raise CollectorError("COLLECTOR_FILE_UNSAFE")
    return _LocalRequestSnapshot(
        request=request,
        parent=parent,
        parent_identity=parent_identity,
        request_bytes=request_raw,
        request_identity=request_identity,
    )


def _production_build_report_binding(
    observation: ReportBindingObservation,
) -> CanonicalControllerArtifact:
    return _fixed_controller_host().build_report_binding(observation)


def _production_sign_report_binding(
    artifact: CanonicalControllerArtifact,
) -> bytes:
    """Fixed signing port pending an OS-isolated controller service.

    A Python-private zero-argument factory is not a security boundary: other
    code in the same process can obtain it and submit a caller-built artifact.
    Formal signing therefore remains unavailable until the controller owns the
    key through an independently enforced OS boundary, or the threat model is
    explicitly re-decided.
    """

    del artifact
    raise _error(CONTROLLER_LIFECYCLE_SIGNING_PORT_HOLD)


def _production_finalize_report(
    path: Path,
    evidence: FixedControllerEvidence,
    binding: bytes,
    signature: bytes,
    now: datetime,
) -> CollectorResult:
    return FixedChapterE2ECollector().finalize_real(
        path,
        evidence,
        controller_report_binding=binding,
        controller_report_signature=signature,
        now=now,
    )


def _production_dependencies() -> _LifecycleDependencies:
    return _LifecycleDependencies(
        require_authority=_require_production_authority,
        controller_build_sha256=fixed_controller_build_sha256,
        load_verified_request=_production_load_verified_request,
        run_browser=_run_fixed_browser_observer,
        collect_runtime=collect_runtime_observations,
        build_report_binding=_production_build_report_binding,
        sign_report_binding=_production_sign_report_binding,
        finalize_report=_production_finalize_report,
        utc_now=lambda: datetime.now(timezone.utc),
    )


def _validate_snapshot(snapshot: object) -> _VerifiedRequestSnapshot:
    if (
        type(snapshot) is not _VerifiedRequestSnapshot
        or type(snapshot.request) is not CollectorRequest
        or not isinstance(snapshot.parent, Path)
        or not snapshot.parent.is_absolute()
        or type(snapshot.parent_identity) is not tuple
        or not snapshot.parent_identity
        or any(type(value) is not int for value in snapshot.parent_identity)
        or type(snapshot.request_bytes) is not bytes
        or not snapshot.request_bytes
        or hashlib.sha256(snapshot.request_bytes).hexdigest()
        != snapshot.request.request_sha256
        or type(snapshot.request_identity) is not tuple
        or not snapshot.request_identity
        or any(type(value) is not int for value in snapshot.request_identity)
        or type(snapshot.preflight_payload) is not bytes
        or not snapshot.preflight_payload
        or hashlib.sha256(snapshot.preflight_payload).hexdigest()
        != snapshot.request.preflight_payload_sha256
        or type(snapshot.preflight_payload_identity) is not tuple
        or not snapshot.preflight_payload_identity
        or any(
            type(value) is not int
            for value in snapshot.preflight_payload_identity
        )
        or type(snapshot.preflight_signature) is not bytes
        or not snapshot.preflight_signature
        or type(snapshot.preflight_signature_identity) is not tuple
        or not snapshot.preflight_signature_identity
        or any(
            type(value) is not int
            for value in snapshot.preflight_signature_identity
        )
        or type(snapshot.verified_preflight)
        is not _VerifiedRequestPreflight
    ):
        raise _error(CONTROLLER_LIFECYCLE_REQUEST_HOLD)
    verified = snapshot.verified_preflight
    if (
        verified.verified.payload_sha256
        != snapshot.request.preflight_payload_sha256
        or verified.payload_identity
        != snapshot.preflight_payload_identity
        or verified.signature_identity
        != snapshot.preflight_signature_identity
    ):
        raise _error(CONTROLLER_LIFECYCLE_REQUEST_HOLD)
    return snapshot


def _load_snapshot(
    dependencies: _LifecycleDependencies,
    path: Path,
    now: datetime,
) -> _VerifiedRequestSnapshot:
    try:
        snapshot = dependencies.load_verified_request(path, now)
    except ControllerLifecycleError:
        raise
    except CollectorError as error:
        if error.code == COLLECTOR_CONTROLLER_AUTHORITY_HOLD_ERROR:
            raise _error(CONTROLLER_LIFECYCLE_AUTHORITY_HOLD) from None
        raise _error(CONTROLLER_LIFECYCLE_REQUEST_HOLD) from None
    except Exception:
        raise _error(CONTROLLER_LIFECYCLE_REQUEST_HOLD) from None
    return _validate_snapshot(snapshot)


def _validate_scope(
    request: CollectorRequest,
    novel_id: str,
    document_id: str,
) -> None:
    if (
        request.expectation.target_scope_sha256
        != hashlib.sha256(
            f"{novel_id}:{document_id}".encode("utf-8")
        ).hexdigest()
    ):
        raise _error(CONTROLLER_LIFECYCLE_REQUEST_HOLD)


def _validate_report_artifact(
    artifact: object,
    *,
    observation: ReportBindingObservation,
    observed_browser_binary_sha256: str,
    observed_controller_build_sha256: str,
) -> CanonicalControllerArtifact:
    if (
        type(artifact) is not CanonicalControllerArtifact
        or artifact.schema_version
        != CONTROLLER_REPORT_BINDING_SCHEMA_VERSION
        or artifact.signature_namespace != REPORT_SIGNATURE_NAMESPACE
        or type(artifact.payload) is not bytes
        or not artifact.payload
        or _SHA256.fullmatch(observed_browser_binary_sha256) is None
        or _SHA256.fullmatch(observed_controller_build_sha256) is None
    ):
        raise _error(CONTROLLER_LIFECYCLE_BINDING_HOLD)
    try:
        payload = _decode_canonical_mapping(
            artifact.payload,
            max_bytes=96 * 1024,
            code=CONTROLLER_LIFECYCLE_BINDING_HOLD,
        )
    except ControllerTrustError:
        raise _error(CONTROLLER_LIFECYCLE_BINDING_HOLD) from None
    expected: Mapping[str, object] = {
        "schema_version": CONTROLLER_REPORT_BINDING_SCHEMA_VERSION,
        "signature_namespace": REPORT_SIGNATURE_NAMESPACE,
        "controller_id": CONTROLLER_ID,
        "preflight_payload_sha256": hashlib.sha256(
            observation.preflight_payload
        ).hexdigest(),
        "run_fingerprint_sha256": observation.run_fingerprint_sha256,
        "target_scope_sha256": observation.target_scope_sha256,
        "probe_request_sha256": hashlib.sha256(
            observation.probe_request_bytes
        ).hexdigest(),
        "request_fingerprint_sha256": (
            observation.request_fingerprint_sha256
        ),
        "automatic_edition_fingerprint_sha256": (
            observation.automatic_edition_fingerprint_sha256
        ),
        "manual_edition_fingerprint_sha256": (
            observation.manual_edition_fingerprint_sha256
        ),
        "listening_output_hashes": list(
            observation.listening_output_hashes
        ),
        "required_stability_milliseconds": (
            FIXED_REQUIRED_STABILITY_MILLISECONDS
        ),
        "collector_report_sha256": hashlib.sha256(
            observation.collector_report_bytes
        ).hexdigest(),
        "probe_report_sha256": hashlib.sha256(
            observation.probe_report_bytes
        ).hexdigest(),
        "metric_sample_count": len(observation.metric_samples),
    }
    if (
        any(payload.get(key) != value for key, value in expected.items())
        or payload.get("signed_at")
        != observation.signed_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        or type(payload.get("observed_captures")) is not list
        or len(payload["observed_captures"])
        != len(FIXED_REQUIRED_CAPTURES)
        or payload.get("controller_build_sha256")
        != observed_controller_build_sha256
        or payload.get("browser_binary_sha256")
        != observed_browser_binary_sha256
    ):
        raise _error(CONTROLLER_LIFECYCLE_BINDING_HOLD)
    return artifact


def _run_fixed_controller_report_stage(
    probe_request_path: Path,
    novel_id: str,
    document_id: str,
    validation_token: str,
    *,
    dependencies: _LifecycleDependencies,
) -> CollectorResult:
    if (
        not isinstance(probe_request_path, Path)
        or not probe_request_path.is_absolute()
        or probe_request_path.name != PROBE_REQUEST_FILENAME
        or type(validation_token) is not str
        or _TOKEN.fullmatch(validation_token) is None
        or type(dependencies) is not _LifecycleDependencies
    ):
        raise _error(CONTROLLER_LIFECYCLE_INPUT_INVALID)
    novel = _canonical_uuid(novel_id)
    document = _canonical_uuid(document_id)
    initial_now = _now(dependencies)
    try:
        dependencies.require_authority(initial_now)
    except ControllerLifecycleError:
        raise
    except ControllerTrustError as error:
        if error.code == CONTROLLER_TRUST_ROOT_HOLD_ERROR:
            raise _error(CONTROLLER_LIFECYCLE_AUTHORITY_HOLD) from None
        raise _error(CONTROLLER_LIFECYCLE_REQUEST_HOLD) from None
    except Exception:
        raise _error(CONTROLLER_LIFECYCLE_AUTHORITY_HOLD) from None
    initial_controller_build_sha256 = _controller_build_identity(dependencies)
    first = _load_snapshot(
        dependencies,
        probe_request_path,
        initial_now,
    )
    _validate_scope(first.request, novel, document)
    browser_request = BrowserObservationRequest(
        novel_id=novel,
        document_id=document,
        request_fingerprint_sha256=(
            first.request.request_fingerprint_sha256
        ),
        run_fingerprint_sha256=(
            first.request.expectation.run_fingerprint_sha256
        ),
        target_scope_sha256=first.request.expectation.target_scope_sha256,
        validation_token=validation_token,
    )
    try:
        browser = dependencies.run_browser(browser_request)
    except (BrowserObserverError, ControllerLifecycleError):
        raise _error(CONTROLLER_LIFECYCLE_BROWSER_HOLD) from None
    except Exception:
        raise _error(CONTROLLER_LIFECYCLE_BROWSER_HOLD) from None
    if type(browser) is not VerifiedBrowserObservation:
        raise _error(CONTROLLER_LIFECYCLE_BROWSER_HOLD)
    try:
        runtime = dependencies.collect_runtime(
            novel,
            document,
            validation_token,
        )
    except (RuntimeObserverError, ControllerLifecycleError):
        raise _error(CONTROLLER_LIFECYCLE_RUNTIME_HOLD) from None
    except Exception:
        raise _error(CONTROLLER_LIFECYCLE_RUNTIME_HOLD) from None
    if type(runtime) is not RuntimeObservationResult:
        raise _error(CONTROLLER_LIFECYCLE_RUNTIME_HOLD)

    final_now = _now(dependencies)
    if _controller_build_identity(dependencies) != initial_controller_build_sha256:
        raise _error(CONTROLLER_LIFECYCLE_SOURCE_HOLD)
    second = _load_snapshot(
        dependencies,
        probe_request_path,
        final_now,
    )
    if second != first:
        raise _error(CONTROLLER_LIFECYCLE_REQUEST_DRIFT)
    try:
        evidence = assemble_fixed_controller_evidence(
            browser,
            runtime,
            second.request,
        )
        collector._validate_evidence(
            second.request,
            evidence,
            now=final_now,
            require_real=True,
        )
    except ControllerEvidenceAssemblyError as error:
        raise _error(error.code) from None
    except CollectorError:
        raise _error(CONTROLLER_LIFECYCLE_BINDING_HOLD) from None
    except Exception:
        raise _error(CONTROLLER_LIFECYCLE_BINDING_HOLD) from None

    try:
        preparation, collector_core, probe_bytes = (
            collector._prepare_controller_report(
                second.request,
                evidence,
                preflight_payload_sha256=(
                    second.request.preflight_payload_sha256
                ),
            )
        )
    except CollectorError:
        raise _error(CONTROLLER_LIFECYCLE_BINDING_HOLD) from None
    except Exception:
        raise _error(CONTROLLER_LIFECYCLE_BINDING_HOLD) from None
    expectation = preparation.expectation
    observation = ReportBindingObservation(
        preflight_payload=second.preflight_payload,
        preflight_signature=second.preflight_signature,
        run_fingerprint_sha256=expectation.run_fingerprint_sha256,
        target_scope_sha256=expectation.target_scope_sha256,
        probe_request_bytes=second.request_bytes,
        request_fingerprint_sha256=(
            expectation.request_fingerprint_sha256
        ),
        automatic_edition_fingerprint_sha256=(
            expectation.automatic_edition_fingerprint_sha256
        ),
        manual_edition_fingerprint_sha256=(
            expectation.manual_edition_fingerprint_sha256
        ),
        listening_output_hashes=expectation.listening_output_hashes,
        collector_report_bytes=collector_core,
        probe_report_bytes=probe_bytes,
        signed_at=final_now,
        captures=browser.captures,
        metric_samples=runtime.metric_samples,
    )
    try:
        artifact = dependencies.build_report_binding(observation)
    except (ControllerHostError, ControllerLifecycleError):
        raise _error(CONTROLLER_LIFECYCLE_BINDING_HOLD) from None
    except Exception:
        raise _error(CONTROLLER_LIFECYCLE_BINDING_HOLD) from None
    artifact = _validate_report_artifact(
        artifact,
        observation=observation,
        observed_browser_binary_sha256=browser.edge_executable_sha256,
        observed_controller_build_sha256=initial_controller_build_sha256,
    )
    try:
        signature = dependencies.sign_report_binding(artifact)
    except ControllerLifecycleError:
        raise
    except ControllerSigningError as error:
        if error.code == CONTROLLER_TRUST_ROOT_HOLD_ERROR:
            raise _error(CONTROLLER_LIFECYCLE_AUTHORITY_HOLD) from None
        raise _error(CONTROLLER_LIFECYCLE_SIGNING_PORT_HOLD) from None
    except Exception:
        raise _error(CONTROLLER_LIFECYCLE_SIGNING_PORT_HOLD) from None
    if type(signature) is not bytes or not signature:
        raise _error(CONTROLLER_LIFECYCLE_SIGNING_PORT_HOLD)

    # Confirmation and signing can outlive the time/policy/request view used
    # to build the artifact.  Never finalize against that stale view.  A real
    # OS service must perform the same post-sign checks inside its protected
    # lifecycle, immediately before the public collector transaction.
    commit_now = _now(dependencies)
    if commit_now < final_now:
        raise _error(CONTROLLER_LIFECYCLE_REQUEST_HOLD)
    try:
        dependencies.require_authority(commit_now)
    except ControllerLifecycleError:
        raise
    except ControllerTrustError as error:
        if error.code == CONTROLLER_TRUST_ROOT_HOLD_ERROR:
            raise _error(CONTROLLER_LIFECYCLE_AUTHORITY_HOLD) from None
        raise _error(CONTROLLER_LIFECYCLE_REQUEST_HOLD) from None
    except Exception:
        raise _error(CONTROLLER_LIFECYCLE_AUTHORITY_HOLD) from None
    if _controller_build_identity(dependencies) != initial_controller_build_sha256:
        raise _error(CONTROLLER_LIFECYCLE_SOURCE_HOLD)
    committed_snapshot = _load_snapshot(
        dependencies,
        probe_request_path,
        commit_now,
    )
    if committed_snapshot != second:
        raise _error(CONTROLLER_LIFECYCLE_REQUEST_DRIFT)
    try:
        result = dependencies.finalize_report(
            probe_request_path,
            evidence,
            artifact.payload,
            signature,
            commit_now,
        )
    except CollectorError as error:
        if error.code == COLLECTOR_CONTROLLER_AUTHORITY_HOLD_ERROR:
            raise _error(CONTROLLER_LIFECYCLE_AUTHORITY_HOLD) from None
        if error.code in {
            "COLLECTOR_FILE_UNSAFE",
            "COLLECTOR_CONTROLLER_PREFLIGHT_INVALID",
            "COLLECTOR_CONTROLLER_PREFLIGHT_BINDING_MISMATCH",
        }:
            raise _error(CONTROLLER_LIFECYCLE_REQUEST_DRIFT) from None
        raise _error(CONTROLLER_LIFECYCLE_FINALIZE_HOLD) from None
    except Exception:
        raise _error(CONTROLLER_LIFECYCLE_FINALIZE_HOLD) from None
    if type(result) is not CollectorResult:
        raise _error(CONTROLLER_LIFECYCLE_FINALIZE_HOLD)
    return result


def run_fixed_local_operator_report_stage(
    probe_request_path: Path,
    novel_id: str,
    document_id: str,
    validation_token: str,
) -> CollectorResult:
    """Run the fixed author/operator evidence stage with no signing service."""

    if (
        not isinstance(probe_request_path, Path)
        or not probe_request_path.is_absolute()
        or probe_request_path.name != PROBE_REQUEST_FILENAME
        or type(validation_token) is not str
        or _TOKEN.fullmatch(validation_token) is None
    ):
        raise _error(CONTROLLER_LIFECYCLE_INPUT_INVALID)
    novel = _canonical_uuid(novel_id)
    document = _canonical_uuid(document_id)
    initial_now = datetime.now(timezone.utc).replace(microsecond=0)
    try:
        initial_build_sha256 = fixed_local_operator_build_sha256()
        first = _load_local_request_snapshot(
            probe_request_path,
            initial_now,
        )
        _validate_scope(first.request, novel, document)
    except ControllerLifecycleError:
        raise
    except Exception:
        raise _error(CONTROLLER_LIFECYCLE_REQUEST_HOLD) from None

    browser_request = BrowserObservationRequest(
        novel_id=novel,
        document_id=document,
        request_fingerprint_sha256=(
            first.request.request_fingerprint_sha256
        ),
        run_fingerprint_sha256=(
            first.request.expectation.run_fingerprint_sha256
        ),
        target_scope_sha256=first.request.expectation.target_scope_sha256,
        validation_token=validation_token,
    )
    try:
        browser = _run_fixed_browser_observer(browser_request)
    except Exception:
        raise _error(CONTROLLER_LIFECYCLE_BROWSER_HOLD) from None
    pending_gap = browser.interaction_evidence
    if pending_gap.pending_gap_status == "observed":
        if (
            pending_gap.pending_gap_stop_before_observed is not True
            or pending_gap.pending_gap_reason_code != "OBSERVED"
        ):
            raise _error("CONTROLLER_EVIDENCE_PENDING_GAP_HOLD")
    elif pending_gap.pending_gap_status == "not_observed":
        reason_code = pending_gap.pending_gap_reason_code
        if (
            pending_gap.pending_gap_stop_before_observed is not False
            or type(reason_code) is not str
            or reason_code not in PENDING_GAP_NOT_OBSERVED_REASON_CODES
        ):
            raise _error("CONTROLLER_EVIDENCE_PENDING_GAP_HOLD")
        raise _error(
            "CONTROLLER_EVIDENCE_PENDING_GAP_" + reason_code
        )
    else:
        raise _error("CONTROLLER_EVIDENCE_PENDING_GAP_HOLD")
    try:
        validate_fixed_browser_evidence(browser, first.request)
    except ControllerEvidenceAssemblyError as error:
        raise _error(error.code) from None
    try:
        runtime = collect_runtime_observations(
            novel,
            document,
            validation_token,
        )
    except RuntimeObserverError as error:
        raise _error(error.code) from None
    except Exception:
        raise _error(CONTROLLER_LIFECYCLE_RUNTIME_HOLD) from None

    final_now = datetime.now(timezone.utc).replace(microsecond=0)
    try:
        if fixed_local_operator_build_sha256() != initial_build_sha256:
            raise _error(CONTROLLER_LIFECYCLE_SOURCE_HOLD)
        second = _load_local_request_snapshot(
            probe_request_path,
            final_now,
        )
        if second != first:
            raise _error(CONTROLLER_LIFECYCLE_REQUEST_DRIFT)
        evidence = assemble_fixed_controller_evidence(
            browser,
            runtime,
            second.request,
        )
        collector._validate_evidence(
            second.request,
            evidence,
            now=final_now,
            require_real=True,
        )
        return FixedChapterE2ECollector().finalize_local_operator(
            probe_request_path,
            evidence,
            controller_build_sha256=initial_build_sha256,
            browser_binary_sha256=browser.edge_executable_sha256,
            node_binary_sha256=browser.node_executable_sha256,
            now=final_now,
        )
    except ControllerLifecycleError:
        raise
    except ControllerEvidenceAssemblyError as error:
        raise _error(error.code) from None
    except CollectorError as error:
        if error.code in _LOCAL_OPERATOR_COLLECTOR_CODES:
            raise _error(error.code) from None
        raise _error(CONTROLLER_LIFECYCLE_FINALIZE_HOLD) from None
    except Exception:
        raise _error(CONTROLLER_LIFECYCLE_FINALIZE_HOLD) from None


def run_experimental_signed_controller_report_stage(
    probe_request_path: Path,
    novel_id: str,
    document_id: str,
    validation_token: str,
) -> CollectorResult:
    """Retain the rejected SSHSIG design only as a non-product experiment."""

    return _run_fixed_controller_report_stage(
        probe_request_path,
        novel_id,
        document_id,
        validation_token,
        dependencies=_production_dependencies(),
    )


def run_fixed_controller_report_stage(
    probe_request_path: Path,
    novel_id: str,
    document_id: str,
    validation_token: str,
) -> CollectorResult:
    """Legacy name retained for the explicitly experimental signed stage."""

    return run_experimental_signed_controller_report_stage(
        probe_request_path,
        novel_id,
        document_id,
        validation_token,
    )


__all__ = [
    "CONTROLLER_LIFECYCLE_AUTHORITY_HOLD",
    "CONTROLLER_LIFECYCLE_BINDING_HOLD",
    "CONTROLLER_LIFECYCLE_BROWSER_HOLD",
    "CONTROLLER_LIFECYCLE_FINALIZE_HOLD",
    "CONTROLLER_LIFECYCLE_INPUT_INVALID",
    "CONTROLLER_LIFECYCLE_REQUEST_DRIFT",
    "CONTROLLER_LIFECYCLE_REQUEST_HOLD",
    "CONTROLLER_LIFECYCLE_RUNTIME_HOLD",
    "CONTROLLER_LIFECYCLE_SOURCE_HOLD",
    "CONTROLLER_LIFECYCLE_SIGNING_PORT_HOLD",
    "ControllerLifecycleError",
    "run_experimental_signed_controller_report_stage",
    "run_fixed_controller_report_stage",
    "run_fixed_local_operator_report_stage",
]
