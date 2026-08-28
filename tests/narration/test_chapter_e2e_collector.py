from __future__ import annotations

from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone
import base64
import fcntl
import hashlib
from inspect import signature
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import traceback
from uuid import UUID

import pytest

import scripts.tts.chapter_e2e_collector as collector_module
import scripts.tts.chapter_e2e_controller_trust as controller_trust
from scripts.tts.chapter_e2e_executor import TechnicalProbeContext
from scripts.tts.chapter_e2e_collector import (
    BrowserCollectorEvidence,
    COLLECTOR_COMMIT_MARKER_FILENAME,
    COLLECTOR_COMMIT_SCHEMA_VERSION,
    COLLECTOR_CONTROLLER_AUTHORITY_HOLD_ERROR,
    COLLECTOR_REPORT_FILENAME,
    COLLECTOR_SCHEMA_VERSION,
    CONTROLLER_ATTESTATION_CAPABILITY_FILENAME,
    CaptureDigest,
    CollectorError,
    FIXED_CONTROLLER_ID,
    FIXED_PUBLIC_PAGE_URL,
    FixedChapterE2ECollector,
    FixedControllerEvidence,
    PROBE_COLLECTOR_BUSY_ERROR,
    PROBE_COLLECTOR_INCOMPLETE_ERROR,
    PROBE_CONTROLLER_AUTHORITY_HOLD_ERROR,
    PROBE_REPORT_FILENAME,
    SidecarCollectorEvidence,
    SidecarMetricSampleDigest,
    SignedCollectorReportGuard,
    ControllerReportSigningContext,
    LEGACY_COLLECTOR_COMMIT_SCHEMA_VERSION,
    LEGACY_COLLECTOR_SCHEMA_VERSION,
    LOCAL_OPERATOR_COLLECTOR_SCHEMA_VERSION,
    LOCAL_OPERATOR_COMMIT_SCHEMA_VERSION,
    LocalOperatorCollectorReportGuard,
    build_controller_report_binding_payload,
    build_sidecar_metric_sample_chain_sha256,
    load_controller_attestation_capability,
    require_formal_controller_authority,
    prepare_controller_report_binding,
)
from scripts.tts.chapter_e2e_controller_trust import ObservedCaptureBinding
from scripts.tts.chapter_e2e_probe_request import (
    PROBE_REQUEST_FILENAME,
    PrivateProbeRequestPublisher,
)
from scripts.tts.chapter_e2e_probes import (
    ALLOWED_ASSISTANT_MODES,
    EXPECTED_RANGE_STATUS_CODES,
    EXPECTED_SIDECAR_CONTAINER_NAME,
    ProbeExpectation,
    ProbeReportError,
    StrictJsonChapterE2EProbeLoader,
)
from scripts.tts.validate_chapter_e2e import ALLOWED_VIEWPORTS, RunnerConfig


REQUESTED_AT = datetime(2026, 8, 27, 12, 0, 0, tzinfo=timezone.utc)
COLLECTED_AT = REQUESTED_AT + timedelta(minutes=30, seconds=1)
NOW = COLLECTED_AT + timedelta(seconds=20)
RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
NOVEL_ID = UUID("22222222-2222-4222-8222-222222222222")
DOCUMENT_ID = UUID("33333333-3333-4333-8333-333333333333")
AUTO_EDITION = UUID("44444444-4444-4444-8444-444444444444")
MANUAL_EDITION = UUID("55555555-5555-4555-8555-555555555555")
AUTO_EDITION_FINGERPRINT = hashlib.sha256(
    b"automatic-edition-fingerprint"
).hexdigest()
MANUAL_EDITION_FINGERPRINT = hashlib.sha256(
    b"manual-edition-fingerprint"
).hexdigest()
OUTPUT_HASHES = ("a" * 64, "b" * 64)
VALIDATION_TOKEN = "v" * 43
CONTROLLER_ATTESTATION_CAPABILITY = bytes(range(32))
UNTRUSTED_TEST_HMAC_KEY = b"untrusted-transaction-test-key"


def _formal_collector() -> FixedChapterE2ECollector:
    return FixedChapterE2ECollector(validation_token=VALIDATION_TOKEN)


def _formal_guard(
    *,
    validation_token: str = VALIDATION_TOKEN,
) -> SignedCollectorReportGuard:
    return SignedCollectorReportGuard(
        validation_token=validation_token,
    )


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


ASYMMETRIC_KEY_ID = "t4k-controller-ed25519-collector-test-01"
ASYMMETRIC_PRINCIPAL = (
    "t4k-controller-collector-test-01@ai-novel-world-2026.local"
)
ASYMMETRIC_BUILD_SHA256 = _sha("collector-controller-build")
ASYMMETRIC_BROWSER_SHA256 = _sha("collector-edge-binary")


def _sign_controller_payload(
    private_key: Path,
    payload: bytes,
    *,
    namespace: str,
) -> bytes:
    signed = subprocess.run(
        [
            str(controller_trust.SSH_KEYGEN_PATH),
            "-Y",
            "sign",
            "-f",
            str(private_key),
            "-n",
            namespace,
        ],
        input=payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
        timeout=10,
        check=False,
    )
    assert signed.returncode == 0
    return signed.stdout


def _replace_preflight(
    request_path: Path,
    payload: bytes,
    signature_bytes: bytes,
) -> None:
    preflight_path = request_path.parent / collector_module.CONTROLLER_PREFLIGHT_FILENAME
    signature_path = (
        request_path.parent
        / collector_module.CONTROLLER_PREFLIGHT_SIGNATURE_FILENAME
    )
    preflight_path.write_bytes(payload)
    signature_path.write_bytes(signature_bytes)
    preflight_path.chmod(0o600)
    signature_path.chmod(0o600)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["controller_preflight_payload_sha256"] = hashlib.sha256(
        payload
    ).hexdigest()
    unsigned = dict(request)
    unsigned.pop("request_fingerprint_sha256", None)
    request["request_fingerprint_sha256"] = hashlib.sha256(
        _canonical(unsigned)
    ).hexdigest()
    request_path.write_bytes(_canonical(request) + b"\n")
    request_path.chmod(0o600)


def _install_signed_preflight(
    request_path: Path,
    private_key: Path,
    trust_metadata: dict[str, str],
    *,
    changes: dict[str, object] | None = None,
) -> tuple[bytes, bytes]:
    request = json.loads(request_path.read_text(encoding="utf-8"))
    seed = request["binding_seed"]
    payload: dict[str, object] = {
        "schema_version": controller_trust.CONTROLLER_PREFLIGHT_SCHEMA_VERSION,
        "issued_at": "2026-08-27T11:59:00Z",
        "expires_at": "2026-08-27T12:14:00Z",
        "nonce_sha256": _sha("collector-preflight-nonce"),
        "run_fingerprint_sha256": seed["run_fingerprint_sha256"],
        "target_scope_sha256": seed["target_scope_sha256"],
        "operator_envelope_sha256": _sha("collector-operator-envelope"),
        "fixture_manifest_sha256": _sha("collector-fixture"),
        "required_stability_milliseconds": (
            controller_trust.FIXED_REQUIRED_STABILITY_MILLISECONDS
        ),
        "required_captures": [
            {
                "target_css_width": width,
                "target_css_height": height,
                "assistant_mode": mode,
            }
            for width, height, mode in controller_trust.FIXED_REQUIRED_CAPTURES
        ],
        "controller_id": controller_trust.CONTROLLER_ID,
        "controller_build_sha256": ASYMMETRIC_BUILD_SHA256,
        "signing_key_id": ASYMMETRIC_KEY_ID,
        "signer_principal": ASYMMETRIC_PRINCIPAL,
        "signature_namespace": controller_trust.PREFLIGHT_SIGNATURE_NAMESPACE,
        "trust_policy_sha256": trust_metadata["policy_sha256"],
        "allowed_signers_sha256": trust_metadata["allowed_signers_sha256"],
    }
    payload.update(changes or {})
    raw = controller_trust.canonical_json_bytes(payload)
    signature = _sign_controller_payload(
        private_key,
        raw,
        namespace=controller_trust.PREFLIGHT_SIGNATURE_NAMESPACE,
    )
    _replace_preflight(request_path, raw, signature)
    return raw, signature


def _active_public_trust(
    tmp_path: Path,
) -> tuple[object, Path, dict[str, str]]:
    directory = tmp_path / "asymmetric-public-trust"
    directory.mkdir(mode=0o700)
    private_key = directory / "controller-key"
    created = subprocess.run(
        [
            str(controller_trust.SSH_KEYGEN_PATH),
            "-q",
            "-t",
            "ed25519",
            "-N",
            "",
            "-f",
            str(private_key),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
    )
    assert created.returncode == 0
    private_key.chmod(0o600)
    public_key = private_key.with_suffix(".pub")
    public_key.chmod(0o600)
    key_parts = public_key.read_text(encoding="ascii").strip().split()
    blob = key_parts[1]
    fingerprint = "SHA256:" + base64.b64encode(
        hashlib.sha256(base64.b64decode(blob, validate=True)).digest()
    ).decode("ascii").rstrip("=")
    allowed_line = (
        f'{ASYMMETRIC_PRINCIPAL} namespaces="'
        f'{controller_trust.PREFLIGHT_SIGNATURE_NAMESPACE},'
        f'{controller_trust.REPORT_SIGNATURE_NAMESPACE}" '
        f"ssh-ed25519 {blob}\n"
    )
    allowed_path = directory / "controller_allowed_signers"
    allowed_path.write_text(allowed_line, encoding="ascii")
    allowed_path.chmod(0o600)
    policy = {
        "schema_version": (
            controller_trust.CONTROLLER_TRUST_POLICY_SCHEMA_VERSION
        ),
        "generation": 1,
        "allowed_signers_sha256": hashlib.sha256(
            allowed_line.encode("ascii")
        ).hexdigest(),
        "keys": [
            {
                "key_id": ASYMMETRIC_KEY_ID,
                "principal": ASYMMETRIC_PRINCIPAL,
                "algorithm": "ssh-ed25519",
                "public_key_fingerprint": fingerprint,
                "status": "active",
                "not_before": "2026-08-26T00:00:00Z",
                "not_after": "2026-08-29T00:00:00Z",
                "allowed_controller_build_sha256": [
                    ASYMMETRIC_BUILD_SHA256
                ],
                "allowed_browser_build_sha256": [
                    ASYMMETRIC_BROWSER_SHA256
                ],
            }
        ],
    }
    policy_raw = controller_trust.canonical_json_bytes(policy)
    policy_path = directory / "controller_trust_policy.json"
    policy_path.write_bytes(policy_raw)
    policy_path.chmod(0o600)
    verifier = controller_trust._test_verifier(
        policy_path,
        allowed_path,
    )
    result = (
        verifier,
        private_key,
        {
            "policy_sha256": hashlib.sha256(policy_raw).hexdigest(),
            "allowed_signers_sha256": hashlib.sha256(
                allowed_line.encode("ascii")
            ).hexdigest(),
        },
    )
    request_path = tmp_path / "private" / PROBE_REQUEST_FILENAME
    if request_path.exists():
        _install_signed_preflight(
            request_path,
            private_key,
            result[2],
        )
    return result


def _sign_report_binding(private_key: Path, payload: bytes) -> bytes:
    return _sign_controller_payload(
        private_key,
        payload,
        namespace=controller_trust.REPORT_SIGNATURE_NAMESPACE,
    )


def _observed_capture_bindings(
    evidence: FixedControllerEvidence,
) -> tuple[ObservedCaptureBinding, ...]:
    outer_hints = {
        (1920, 1080): (1939, 1091),
        (2560, 1440): (2586, 1455),
    }
    ordered = sorted(
        evidence.browser.captures,
        key=lambda item: (
            ALLOWED_VIEWPORTS.index((item.width, item.height)),
            ALLOWED_ASSISTANT_MODES.index(item.assistant_mode),
        ),
    )
    return tuple(
        ObservedCaptureBinding(
            target_css_width=item.width,
            target_css_height=item.height,
            requested_outer_width=outer_hints[(item.width, item.height)][0],
            requested_outer_height=outer_hints[(item.width, item.height)][1],
            observed_inner_width=item.width,
            observed_inner_height=item.height,
            device_pixel_ratio_micros=1_010_000,
            screenshot_pixel_width=round(item.width * 1.01),
            screenshot_pixel_height=round(item.height * 1.01),
            assistant_mode_requested=item.assistant_mode,
            assistant_mode_observed=item.assistant_mode,
            calibration_attempt_count=2,
            calibration_summary_sha256=_sha(
                f"calibration-{item.width}-{item.height}-{item.assistant_mode}"
            ),
            screenshot_sha256=item.screenshot_sha256,
            console_summary_sha256=item.console_summary_sha256,
            network_summary_sha256=item.network_summary_sha256,
        )
        for item in ordered
    )


def _formal_binding(
    request_path: Path,
    evidence: FixedControllerEvidence,
    private_key: Path,
    trust_metadata: dict[str, str],
) -> tuple[bytes, bytes]:
    preparation = prepare_controller_report_binding(
        request_path,
        evidence,
        now=NOW,
    )
    payload = build_controller_report_binding_payload(
        preparation,
        evidence,
        ControllerReportSigningContext(
            signed_at=NOW,
            controller_build_sha256=ASYMMETRIC_BUILD_SHA256,
            browser_binary_sha256=ASYMMETRIC_BROWSER_SHA256,
            signing_key_id=ASYMMETRIC_KEY_ID,
            signer_principal=ASYMMETRIC_PRINCIPAL,
            trust_policy_sha256=trust_metadata["policy_sha256"],
            allowed_signers_sha256=(
                trust_metadata["allowed_signers_sha256"]
            ),
            observed_captures=_observed_capture_bindings(evidence),
        ),
    )
    return payload, _sign_report_binding(private_key, payload)


def _config(tmp_path: Path) -> RunnerConfig:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    private.chmod(0o700)
    return RunnerConfig(
        run_id=RUN_ID,
        mode="real",
        fixture_manifest=tmp_path / "fixture.json",
        api_base="http://127.0.0.1:18088/api/ai-novel-world-2026",
        novel_id=NOVEL_ID,
        document_id=DOCUMENT_ID,
        automatic_case_id="automatic",
        manual_case_id="manual",
        private_work_dir=private,
        output_dir=tmp_path / "evidence",
        duration_minutes=30.0,
        listening_record=None,
        resume=False,
    )


def _expectation(config: RunnerConfig) -> ProbeExpectation:
    return ProbeExpectation.from_runner(
        config,
        automatic_edition_id=AUTO_EDITION,
        automatic_edition_fingerprint=AUTO_EDITION_FINGERPRINT,
        manual_edition_id=MANUAL_EDITION,
        manual_edition_fingerprint=MANUAL_EDITION_FINGERPRINT,
        listening_output_hashes=OUTPUT_HASHES,
    )


def _technical_context() -> TechnicalProbeContext:
    return TechnicalProbeContext(
        automatic_request_id=UUID("66666666-6666-4666-8666-666666666666"),
        automatic_edition_id=AUTO_EDITION,
        automatic_edition_fingerprint=AUTO_EDITION_FINGERPRINT,
        automatic_manifest_revision=2,
        manual_request_id=UUID("77777777-7777-4777-8777-777777777777"),
        manual_edition_id=MANUAL_EDITION,
        manual_edition_fingerprint=MANUAL_EDITION_FINGERPRINT,
        manual_manifest_revision=2,
        request_to_ready_seconds=(30.0, 45.75),
        observed_http_first_audio_ms=(900, 1250),
        chapter_audio_duration_seconds=120.25,
        range_status_codes=EXPECTED_RANGE_STATUS_CODES,
        listening_output_hashes=OUTPUT_HASHES,
    )


def _write_legacy_capability_file(
    private_work_dir: Path,
    *,
    key: bytes = CONTROLLER_ATTESTATION_CAPABILITY,
) -> Path:
    capability_path = (
        private_work_dir / CONTROLLER_ATTESTATION_CAPABILITY_FILENAME
    )
    file_fd = os.open(
        capability_path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    directory_fd: int | None = None
    try:
        assert os.write(file_fd, key) == len(key)
        os.fsync(file_fd)
        directory_fd = os.open(private_work_dir, os.O_RDONLY)
        os.fsync(directory_fd)
    finally:
        os.close(file_fd)
        if directory_fd is not None:
            os.close(directory_fd)
    return capability_path


def _publish(tmp_path: Path) -> tuple[Path, ProbeExpectation]:
    config = _config(tmp_path)
    expectation = _expectation(config)
    placeholder = _canonical(
        {
            "nonce_sha256": _sha("untrusted-placeholder-nonce"),
            "operator_envelope_sha256": _sha(
                "untrusted-placeholder-envelope"
            ),
            "fixture_manifest_sha256": _sha(
                "untrusted-placeholder-fixture"
            ),
        }
    ) + b"\n"
    PrivateProbeRequestPublisher(
        preflight_payload_sha256=hashlib.sha256(placeholder).hexdigest(),
        now=lambda: REQUESTED_AT,
    ).publish(
        config,
        expectation,
        _technical_context(),
    )
    preflight_path = (
        config.private_work_dir / collector_module.CONTROLLER_PREFLIGHT_FILENAME
    )
    signature_path = (
        config.private_work_dir
        / collector_module.CONTROLLER_PREFLIGHT_SIGNATURE_FILENAME
    )
    preflight_path.write_bytes(placeholder)
    signature_path.write_bytes(b"not-a-formal-sshsig\n")
    preflight_path.chmod(0o600)
    signature_path.chmod(0o600)
    return config.private_work_dir / PROBE_REQUEST_FILENAME, expectation


def _captures() -> tuple[CaptureDigest, ...]:
    rows: list[CaptureDigest] = []
    for index, (width, height, assistant_mode) in enumerate(
        (
            (width, height, assistant_mode)
            for width, height in ALLOWED_VIEWPORTS
            for assistant_mode in ALLOWED_ASSISTANT_MODES
        ),
        start=1,
    ):
        rows.append(
            CaptureDigest(
                width=width,
                height=height,
                assistant_mode=assistant_mode,
                observed_inner_width=width,
                observed_inner_height=height,
                device_pixel_ratio=1.0,
                screenshot_pixel_width=width,
                screenshot_pixel_height=height,
                calibration_summary_sha256=_sha(f"calibration-{index}"),
                screenshot_sha256=_sha(f"screenshot-{index}"),
                screenshot_bytes=10_000 + index,
                console_summary_sha256=_sha(f"console-{index}"),
                network_summary_sha256=_sha(f"network-{index}"),
                network_request_count=20 + index,
                console_error_count=0,
                overlap_count=0,
            )
        )
    return tuple(rows)


def _metric_samples() -> tuple[SidecarMetricSampleDigest, ...]:
    observed = [
        REQUESTED_AT + timedelta(minutes=index) for index in range(30)
    ]
    observed.append(COLLECTED_AT)
    return tuple(
        SidecarMetricSampleDigest(
            observed_at=observed_at,
            sample_sha256=_sha(f"sidecar-sample-{index}"),
            resident_memory_bytes=(
                2_000_000_000
                if index == len(observed) - 1
                else 1_000_000_000 + index
            ),
        )
        for index, observed_at in enumerate(observed)
    )


def _evidence(
    request_path: Path,
    *,
    synthetic: bool = False,
) -> FixedControllerEvidence:
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request_fingerprint = request["request_fingerprint_sha256"]
    metrics_summary = _sha("sidecar-metrics")
    metric_samples = _metric_samples()
    metric_sample_chain = build_sidecar_metric_sample_chain_sha256(
        request_fingerprint_sha256=request_fingerprint,
        window_started_at=REQUESTED_AT,
        window_ended_at=COLLECTED_AT,
        metrics_summary_sha256=metrics_summary,
        samples=metric_samples,
    )
    return FixedControllerEvidence(
        controller_id=FIXED_CONTROLLER_ID,
        page_url=FIXED_PUBLIC_PAGE_URL,
        request_fingerprint_sha256=request_fingerprint,
        collected_at=COLLECTED_AT,
        synthetic=synthetic,
        browser=BrowserCollectorEvidence(
            observer_report_sha256=_sha("observer-report"),
            captures=_captures(),
            range_status_codes=EXPECTED_RANGE_STATUS_CODES,
            range_summary_sha256=_sha("range-summary"),
            etag_summary_sha256=_sha("etag-summary"),
            etag_observed=True,
            if_none_match_304_observed=True,
            if_range_206_observed=True,
            unsatisfied_range_416_observed=True,
            time_to_first_audio_ms=1250,
            seam_pairs_checked=3,
            seek_latest_wins=True,
            pending_gap_not_skipped=True,
            interaction_summary_sha256=_sha("interaction-summary"),
            edit_actions_observed=2,
            edit_actions_created_tts_writes=0,
            editor_summary_sha256=_sha("editor-summary"),
        ),
        runtime=SidecarCollectorEvidence(
            sidecar_container_name=EXPECTED_SIDECAR_CONTAINER_NAME,
            window_started_at=REQUESTED_AT,
            window_ended_at=COLLECTED_AT,
            request_fingerprint_sha256=request_fingerprint,
            stability_elapsed_seconds=1801.0,
            chapter_audio_duration_seconds=120.25,
            request_to_ready_seconds=45.75,
            peak_memory_bytes=2_000_000_000,
            host_paging_observed=False,
            pageout_delta=0,
            swapout_delta=0,
            memory_baseline_median_bytes=1_000_000_002,
            memory_tail_median_bytes=1_000_000_028,
            memory_growth_bytes=26,
            memory_growth_limit_bytes=128 * 1024 * 1024,
            sidecar_memory_growth_observed=False,
            qwenpaw_slowdown_observed=False,
            sidecar_restart_count=0,
            health_failure_count=0,
            metric_sample_count=31,
            metric_samples=metric_samples,
            metric_sample_chain_sha256=metric_sample_chain,
            metrics_summary_sha256=metrics_summary,
        ),
    )


def _rewrite_request(path: Path, mutate: object) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert callable(mutate)
    mutate(payload)
    unsigned = dict(payload)
    unsigned.pop("request_fingerprint_sha256", None)
    payload["request_fingerprint_sha256"] = hashlib.sha256(
        _canonical(unsigned)
    ).hexdigest()
    path.write_bytes(_canonical(payload) + b"\n")
    path.chmod(0o600)


def _commit_untrusted_candidate(
    request_path: Path,
    evidence: FixedControllerEvidence,
    *,
    now: datetime = NOW,
) -> tuple[bytes, bytes]:
    """Exercise the private commit primitive without granting provenance.

    This test-only harness deliberately uses a known HMAC key.  Its output is
    therefore only an untrusted legacy candidate and the public guard must
    always terminate at ``PROBE_CONTROLLER_AUTHORITY_HOLD`` once committed.
    """

    request, parent, parent_identity = collector_module._load_request(
        request_path,
        now=now,
    )
    collector_module._validate_evidence(
        request,
        evidence,
        now=now,
        require_real=True,
    )
    collector_bytes, probe_bytes = collector_module._build_reports(
        request,
        evidence,
        attestation_key=UNTRUSTED_TEST_HMAC_KEY,
    )
    collector_module._ensure_outputs_absent(parent, parent_identity)
    with collector_module._collector_transaction_lock(
        parent,
        parent_identity,
        exclusive=True,
        create=True,
    ) as parent_fd:
        locked_request, locked_parent, locked_parent_identity = (
            collector_module._load_request(request_path, now=now)
        )
        if (
            locked_request != request
            or locked_parent != parent
            or locked_parent_identity != parent_identity
        ):
            raise CollectorError("COLLECTOR_FILE_UNSAFE")
        collector_identity = collector_module._existing_exact_identity(
            parent_fd,
            filename=COLLECTOR_REPORT_FILENAME,
            data=collector_bytes,
        )
        probe_identity = collector_module._existing_exact_identity(
            parent_fd,
            filename=PROBE_REPORT_FILENAME,
            data=probe_bytes,
        )
        try:
            os.stat(
                COLLECTOR_COMMIT_MARKER_FILENAME,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
            marker_exists = True
        except FileNotFoundError:
            marker_exists = False
        if marker_exists and (
            collector_identity is None or probe_identity is None
        ):
            raise CollectorError("COLLECTOR_REPORT_EXISTS")
        if collector_identity is None:
            collector_identity = collector_module._publish_exact_file(
                parent_fd,
                filename=COLLECTOR_REPORT_FILENAME,
                data=collector_bytes,
            )
        if probe_identity is None:
            probe_identity = collector_module._publish_exact_file(
                parent_fd,
                filename=PROBE_REPORT_FILENAME,
                data=probe_bytes,
            )
        marker_bytes = collector_module._build_commit_marker(
            request_fingerprint_sha256=request.request_fingerprint_sha256,
            collector_bytes=collector_bytes,
            collector_identity=collector_identity,
            probe_bytes=probe_bytes,
            probe_identity=probe_identity,
            attestation_key=UNTRUSTED_TEST_HMAC_KEY,
        )
        collector_module._publish_exact_file(
            parent_fd,
            filename=COLLECTOR_COMMIT_MARKER_FILENAME,
            data=marker_bytes,
        )
        collector_module._assert_parent_identity(
            parent,
            parent_fd,
            parent_identity,
        )
    return collector_bytes, probe_bytes


def _assert_guard_authority_hold(
    probe_path: Path,
    *,
    expectation: ProbeExpectation,
) -> None:
    with pytest.raises(
        ProbeReportError,
        match=PROBE_CONTROLLER_AUTHORITY_HOLD_ERROR,
    ):
        _formal_guard().verify(
            probe_path,
            expectation=expectation,
            now=NOW,
        )


def test_untrusted_transaction_candidate_is_private_but_not_formal(
    tmp_path: Path,
) -> None:
    request_path, expectation = _publish(tmp_path)
    evidence = _evidence(request_path)

    expected_collector, expected_probe = _commit_untrusted_candidate(
        request_path, evidence
    )

    collector_path = request_path.parent / COLLECTOR_REPORT_FILENAME
    probe_path = request_path.parent / PROBE_REPORT_FILENAME
    marker_path = request_path.parent / COLLECTOR_COMMIT_MARKER_FILENAME
    collector_raw = collector_path.read_bytes()
    probe_raw = probe_path.read_bytes()
    marker_raw = marker_path.read_bytes()
    collector = json.loads(collector_raw)
    probe = json.loads(probe_raw)
    marker = json.loads(marker_raw)
    assert collector_raw == expected_collector
    assert probe_raw == expected_probe
    for path in (collector_path, probe_path, marker_path):
        metadata = path.lstat()
        assert stat.S_IMODE(metadata.st_mode) == 0o600
        assert metadata.st_uid == os.getuid()
        assert metadata.st_nlink == 1

    assert collector["schema_version"] == LEGACY_COLLECTOR_SCHEMA_VERSION
    assert LEGACY_COLLECTOR_SCHEMA_VERSION == (
        "moss-tts-chapter-e2e-collector/1.2"
    )
    assert COLLECTOR_SCHEMA_VERSION == "moss-tts-chapter-e2e-collector/2.1"
    assert collector["formal_validation_eligible"] is True
    assert collector["source"] == {
        "controller_id": FIXED_CONTROLLER_ID,
        "page_url": FIXED_PUBLIC_PAGE_URL,
        "synthetic": False,
    }
    assert collector["probe_report_sha256"] == hashlib.sha256(
        probe_raw
    ).hexdigest()
    assert marker["schema_version"] == (
        LEGACY_COLLECTOR_COMMIT_SCHEMA_VERSION
    )
    assert marker["request_fingerprint_sha256"] == collector["request"][
        "request_fingerprint_sha256"
    ]
    assert marker["collector"]["sha256"] == hashlib.sha256(
        collector_raw
    ).hexdigest()
    assert marker["probe"]["sha256"] == hashlib.sha256(
        probe_raw
    ).hexdigest()
    signed = dict(collector)
    signature = signed.pop("controller_attestation_hmac_sha256")
    assert len(signature) == 64
    unsigned = dict(signed)
    fingerprint = unsigned.pop("collector_report_fingerprint_sha256")
    assert fingerprint == hashlib.sha256(_canonical(unsigned)).hexdigest()
    captures = collector["browser"]["captures"]
    assert len(captures) == 4
    assert {
        (row["width"], row["height"], row["assistant_mode"])
        for row in captures
    } == {
        (1920, 1080, "collapsed"),
        (1920, 1080, "expanded"),
        (2560, 1440, "collapsed"),
        (2560, 1440, "expanded"),
    }
    assert all(
        len(row[field]) == 64
        for row in captures
        for field in (
            "screenshot_sha256",
            "console_summary_sha256",
            "network_summary_sha256",
        )
    )
    assert collector["browser"]["observer_report_sha256"] == _sha(
        "observer-report"
    )
    assert probe["browser"]["observer_report_sha256"] == _sha(
        "observer-report"
    )
    range_etag = collector["browser"]["range_etag"]
    assert range_etag["range_status_codes"] == [200, 206, 304, 416]
    assert range_etag["etag_observed"] is True
    assert range_etag["if_none_match_304_observed"] is True
    assert range_etag["if_range_206_observed"] is True
    assert range_etag["unsatisfied_range_416_observed"] is True
    assert collector["browser"]["interaction"]["seek_latest_wins"] is True
    assert (
        collector["browser"]["interaction"]["pending_gap_not_skipped"]
        is True
    )
    assert (
        collector["browser"]["editor"][
            "edit_actions_created_tts_writes"
        ]
        == 0
    )
    runtime = collector["runtime"]
    assert runtime["window_started_at"] == "2026-08-27T12:00:00Z"
    assert runtime["window_ended_at"] == "2026-08-27T12:30:01Z"
    assert runtime["request_fingerprint_sha256"] == collector["request"][
        "request_fingerprint_sha256"
    ]
    assert runtime["stability_elapsed_seconds"] == 1801.0
    assert runtime["host_paging_observed"] is False
    assert runtime["pageout_delta"] == 0
    assert runtime["swapout_delta"] == 0
    assert runtime["memory_baseline_median_bytes"] == 1_000_000_002
    assert runtime["memory_tail_median_bytes"] == 1_000_000_028
    assert runtime["memory_growth_bytes"] == 26
    assert runtime["memory_growth_limit_bytes"] == 128 * 1024 * 1024
    assert runtime["sidecar_memory_growth_observed"] is False
    assert runtime["qwenpaw_slowdown_observed"] is False
    assert probe["runtime"]["host_paging_observed"] is False
    assert probe["runtime"]["pageout_delta"] == 0
    assert probe["runtime"]["swapout_delta"] == 0
    assert probe["runtime"]["memory_growth_bytes"] == 26
    assert probe["runtime"]["sidecar_memory_growth_observed"] is False
    assert probe["runtime"]["qwenpaw_slowdown_observed"] is False
    assert runtime["metric_sample_count"] == len(runtime["metric_samples"]) == 31
    assert runtime["peak_memory_bytes"] == max(
        row["resident_memory_bytes"] for row in runtime["metric_samples"]
    )
    assert runtime["metric_sample_chain_sha256"] == (
        _evidence(request_path).runtime.metric_sample_chain_sha256
    )

    bound = StrictJsonChapterE2EProbeLoader().load(
        probe_path,
        expectation=expectation,
        now=NOW,
    )
    _assert_guard_authority_hold(probe_path, expectation=expectation)
    assert bound.stability_elapsed_seconds == 1801.0
    assert bound.range_status_codes == (200, 206, 304, 416)
    assert bound.host_paging_observed is False
    assert bound.pageout_delta == 0
    assert bound.swapout_delta == 0
    assert bound.memory_growth_bytes == 26
    assert bound.sidecar_memory_growth_observed is False
    assert bound.qwenpaw_slowdown_observed is False


@pytest.mark.parametrize(
    "field",
    ("host_paging_observed", "qwenpaw_slowdown_observed"),
)
def test_true_host_observation_round_trips_through_both_signed_reports(
    tmp_path: Path,
    field: str,
) -> None:
    request_path, expectation = _publish(tmp_path)
    evidence = _evidence(request_path)
    replacements: dict[str, object] = {field: True}
    if field == "host_paging_observed":
        replacements["pageout_delta"] = 1
    evidence = replace(
        evidence,
        runtime=replace(evidence.runtime, **replacements),
    )

    collector_raw, probe_raw = _commit_untrusted_candidate(
        request_path,
        evidence,
    )
    collector = json.loads(collector_raw)
    probe = json.loads(probe_raw)
    assert collector["runtime"][field] is True
    assert probe["runtime"][field] is True
    assert collector_module._validate_untrusted_collector_candidate(
        collector_raw=collector_raw,
        collector=collector,
        probe_raw=probe_raw,
        probe=probe,
        expectation=expectation,
        now=NOW,
    ) == collector["request"]["request_fingerprint_sha256"]
    bound = StrictJsonChapterE2EProbeLoader().load_bytes(
        probe_raw,
        expectation=expectation,
        now=NOW,
    )
    assert getattr(bound, field) is True


@pytest.mark.parametrize(
    "field",
    (
        "host_paging_observed",
        "pageout_delta",
        "swapout_delta",
        "memory_baseline_median_bytes",
        "memory_tail_median_bytes",
        "memory_growth_bytes",
        "memory_growth_limit_bytes",
        "sidecar_memory_growth_observed",
        "qwenpaw_slowdown_observed",
    ),
)
@pytest.mark.parametrize("target", ("detailed", "probe"))
def test_signed_runtime_requires_every_memory_observation_key(
    tmp_path: Path,
    field: str,
    target: str,
) -> None:
    request_path, expectation = _publish(tmp_path)
    collector_raw, probe_raw = _commit_untrusted_candidate(
        request_path,
        _evidence(request_path),
    )
    collector = json.loads(collector_raw)
    probe = json.loads(probe_raw)
    runtime = collector["runtime"] if target == "detailed" else probe["runtime"]
    runtime.pop(field)

    with pytest.raises(CollectorError, match="COLLECTOR_REPORT_INVALID"):
        collector_module._validate_signed_runtime_report(
            request_payload=collector["request"],
            runtime_payload=collector["runtime"],
            probe_runtime_payload=probe["runtime"],
            collected_at=COLLECTED_AT,
            expectation=expectation,
        )


@pytest.mark.parametrize(
    "field",
    ("host_paging_observed", "qwenpaw_slowdown_observed"),
)
def test_signed_runtime_rejects_host_observation_projection_mismatch(
    tmp_path: Path,
    field: str,
) -> None:
    request_path, expectation = _publish(tmp_path)
    collector_raw, probe_raw = _commit_untrusted_candidate(
        request_path,
        _evidence(request_path),
    )
    collector = json.loads(collector_raw)
    probe = json.loads(probe_raw)
    probe["runtime"][field] = True

    with pytest.raises(CollectorError, match="COLLECTOR_REPORT_INVALID"):
        collector_module._validate_signed_runtime_report(
            request_payload=collector["request"],
            runtime_payload=collector["runtime"],
            probe_runtime_payload=probe["runtime"],
            collected_at=COLLECTED_AT,
            expectation=expectation,
        )


def test_synthetic_protocol_can_never_write_a_formal_report(
    tmp_path: Path,
) -> None:
    request_path, _ = _publish(tmp_path)
    synthetic = _evidence(request_path, synthetic=True)
    collector = FixedChapterE2ECollector()

    result = collector.validate_synthetic(request_path, synthetic, now=NOW)

    assert result.status == "SYNTHETIC_PROTOCOL_ONLY"
    assert result.formal_validation_eligible is False
    assert not (request_path.parent / COLLECTOR_REPORT_FILENAME).exists()
    assert not (request_path.parent / PROBE_REPORT_FILENAME).exists()
    with pytest.raises(
        CollectorError, match="COLLECTOR_SYNTHETIC_NOT_FORMAL"
    ):
        collector.finalize_real(request_path, synthetic, now=NOW)
    assert not (request_path.parent / COLLECTOR_REPORT_FILENAME).exists()
    assert not (request_path.parent / PROBE_REPORT_FILENAME).exists()


def test_ordinary_real_caller_cannot_persist_formal_artifacts(
    tmp_path: Path,
) -> None:
    request_path, _ = _publish(tmp_path)

    with pytest.raises(
        CollectorError,
        match=COLLECTOR_CONTROLLER_AUTHORITY_HOLD_ERROR,
    ):
        FixedChapterE2ECollector(
            validation_token=VALIDATION_TOKEN
        ).finalize_real(
            request_path,
            _evidence(request_path),
            now=NOW,
        )

    assert not (request_path.parent / COLLECTOR_REPORT_FILENAME).exists()
    assert not (request_path.parent / PROBE_REPORT_FILENAME).exists()
    assert not (
        request_path.parent / COLLECTOR_COMMIT_MARKER_FILENAME
    ).exists()
    assert not (
        request_path.parent / collector_module._TRANSACTION_LOCK_FILENAME
    ).exists()


def test_local_operator_evidence_commits_without_signing_authority(
    tmp_path: Path,
) -> None:
    request_path, expectation = _publish(tmp_path)

    result = FixedChapterE2ECollector().finalize_local_operator(
        request_path,
        _evidence(request_path),
        controller_build_sha256=_sha("local-controller-build"),
        browser_binary_sha256=_sha("local-edge-binary"),
        node_binary_sha256=_sha("local-node-binary"),
        now=NOW,
    )

    parent = request_path.parent
    collector_payload = json.loads(
        (parent / COLLECTOR_REPORT_FILENAME).read_text(encoding="utf-8")
    )
    marker_payload = json.loads(
        (parent / COLLECTOR_COMMIT_MARKER_FILENAME).read_text(
            encoding="utf-8"
        )
    )
    bound = LocalOperatorCollectorReportGuard().load_verified(
        parent / PROBE_REPORT_FILENAME,
        expectation=expectation,
        now=NOW,
    )

    assert result.status == "LOCAL_OPERATOR_OBSERVATION_COMMITTED"
    assert LOCAL_OPERATOR_COLLECTOR_SCHEMA_VERSION == (
        "moss-tts-chapter-e2e-local-operator/1.2"
    )
    assert collector_payload["schema_version"] == (
        LOCAL_OPERATOR_COLLECTOR_SCHEMA_VERSION
    )
    assert collector_payload["evidence_class"] == (
        "local_operator_observation"
    )
    assert collector_payload["acceptance_scope"] == (
        "technical_observation_only"
    )
    assert collector_payload["formal_validation_eligible"] is False
    assert "controller_authority" not in collector_payload
    assert collector_payload["binding"]["automatic_edition_id_sha256"] == (
        expectation.automatic_edition_id_sha256
    )
    assert collector_payload["binding"][
        "automatic_edition_fingerprint_sha256"
    ] == expectation.automatic_edition_fingerprint_sha256
    assert collector_payload["binding"]["manual_edition_id_sha256"] == (
        expectation.manual_edition_id_sha256
    )
    assert collector_payload["binding"][
        "manual_edition_fingerprint_sha256"
    ] == expectation.manual_edition_fingerprint_sha256
    assert marker_payload["schema_version"] == (
        LOCAL_OPERATOR_COMMIT_SCHEMA_VERSION
    )
    assert bound.listening_output_hashes == expectation.listening_output_hashes
    assert bound.evidence_class == "local_operator_observation"
    assert bound.evidence_root_sha256 is not None
    assert len(bound.evidence_root_sha256) == 64


def test_local_operator_guard_rejects_mixed_probe_bytes(tmp_path: Path) -> None:
    request_path, expectation = _publish(tmp_path)
    FixedChapterE2ECollector().finalize_local_operator(
        request_path,
        _evidence(request_path),
        controller_build_sha256=_sha("local-controller-build"),
        browser_binary_sha256=_sha("local-edge-binary"),
        node_binary_sha256=_sha("local-node-binary"),
        now=NOW,
    )
    probe_path = request_path.parent / PROBE_REPORT_FILENAME
    payload = json.loads(probe_path.read_text(encoding="utf-8"))
    payload["runtime"]["peak_memory_bytes"] += 1
    probe_path.write_bytes(_canonical(payload) + b"\n")
    probe_path.chmod(0o600)

    with pytest.raises(
        ProbeReportError,
        match="PROBE_COLLECTOR_LOCAL_EVIDENCE_INVALID",
    ):
        LocalOperatorCollectorReportGuard().load_verified(
            probe_path,
            expectation=expectation,
            now=NOW,
        )


def test_formal_sshsig_commit_binds_unsigned_core_and_final_file_separately(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path, expectation = _publish(tmp_path)
    verifier, private_key, metadata = _active_public_trust(tmp_path)
    evidence = _evidence(request_path)
    monkeypatch.setattr(
        collector_module,
        "FixedControllerTrustVerifier",
        lambda: verifier,
    )
    binding, report_signature = _formal_binding(
        request_path,
        evidence,
        private_key,
        metadata,
    )

    result = _formal_collector().finalize_real(
        request_path,
        evidence,
        controller_report_binding=binding,
        controller_report_signature=report_signature,
        now=NOW,
    )

    parent = request_path.parent
    request = json.loads(request_path.read_text(encoding="utf-8"))
    preflight_raw = (
        parent / collector_module.CONTROLLER_PREFLIGHT_FILENAME
    ).read_bytes()
    preflight_signature = (
        parent / collector_module.CONTROLLER_PREFLIGHT_SIGNATURE_FILENAME
    ).read_bytes()
    collector_raw = (parent / COLLECTOR_REPORT_FILENAME).read_bytes()
    probe_raw = (parent / PROBE_REPORT_FILENAME).read_bytes()
    marker_raw = (
        parent / COLLECTOR_COMMIT_MARKER_FILENAME
    ).read_bytes()
    collector = json.loads(collector_raw)
    marker = json.loads(marker_raw)
    unsigned_core = dict(collector)
    authority = unsigned_core.pop("controller_authority")
    unsigned_core_raw = _canonical(unsigned_core) + b"\n"

    assert result.status == "FORMAL_CONTROLLER_REPORT_COMMITTED"
    assert request["controller_preflight_payload_sha256"] == hashlib.sha256(
        preflight_raw
    ).hexdigest()
    assert preflight_signature.startswith(b"-----BEGIN SSH SIGNATURE-----\n")
    assert collector["schema_version"] == COLLECTOR_SCHEMA_VERSION
    assert marker["schema_version"] == COLLECTOR_COMMIT_SCHEMA_VERSION
    assert "hmac" not in collector_raw.decode("ascii")
    assert "hmac" not in marker_raw.decode("ascii")
    # Frozen semantic: this signed digest is the canonical unsigned core,
    # never the final collector-report file hash containing the SSHSIG.
    assert authority["report_binding"]["collector_report_sha256"] == (
        hashlib.sha256(unsigned_core_raw).hexdigest()
    )
    assert authority["report_binding"]["collector_report_sha256"] != (
        result.collector_report_sha256
    )
    assert marker["collector"]["sha256"] == result.collector_report_sha256
    assert marker["probe"]["sha256"] == hashlib.sha256(probe_raw).hexdigest()
    assert (
        _formal_guard().load_verified(
            parent / PROBE_REPORT_FILENAME,
            expectation=expectation,
            now=NOW,
        ).report_sha256
        == result.probe_report_sha256
    )


def _assert_no_formal_transaction_files(request_path: Path) -> None:
    for filename in (
        COLLECTOR_REPORT_FILENAME,
        PROBE_REPORT_FILENAME,
        COLLECTOR_COMMIT_MARKER_FILENAME,
        collector_module._TRANSACTION_LOCK_FILENAME,
    ):
        assert not (request_path.parent / filename).exists()


@pytest.mark.parametrize(
    ("case", "expected_code"),
    (
        ("missing_payload", "COLLECTOR_CONTROLLER_PREFLIGHT_INVALID"),
        ("missing_signature", "COLLECTOR_CONTROLLER_PREFLIGHT_INVALID"),
        ("stale", "COLLECTOR_CONTROLLER_PREFLIGHT_INVALID"),
        ("hash_mismatch", "COLLECTOR_CONTROLLER_PREFLIGHT_INVALID"),
        ("tampered", "COLLECTOR_CONTROLLER_PREFLIGHT_INVALID"),
        ("wrong_signature", "COLLECTOR_CONTROLLER_PREFLIGHT_INVALID"),
        (
            "cross_run",
            "COLLECTOR_CONTROLLER_PREFLIGHT_BINDING_MISMATCH",
        ),
        (
            "cross_scope",
            "COLLECTOR_CONTROLLER_PREFLIGHT_BINDING_MISMATCH",
        ),
    ),
)
def test_formal_preflight_failure_is_stable_and_writes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    expected_code: str,
) -> None:
    request_path, _ = _publish(tmp_path)
    verifier, private_key, metadata = _active_public_trust(tmp_path)
    monkeypatch.setattr(
        collector_module,
        "FixedControllerTrustVerifier",
        lambda: verifier,
    )
    preflight_path = (
        request_path.parent / collector_module.CONTROLLER_PREFLIGHT_FILENAME
    )
    signature_path = (
        request_path.parent
        / collector_module.CONTROLLER_PREFLIGHT_SIGNATURE_FILENAME
    )
    if case == "missing_payload":
        preflight_path.unlink()
    elif case == "missing_signature":
        signature_path.unlink()
    elif case == "stale":
        _install_signed_preflight(
            request_path,
            private_key,
            metadata,
            changes={
                "issued_at": "2026-08-27T11:30:00Z",
                "expires_at": "2026-08-27T11:45:00Z",
            },
        )
    elif case == "hash_mismatch":
        payload = json.loads(preflight_path.read_text(encoding="utf-8"))
        payload["nonce_sha256"] = _sha("hash-mismatch-preflight-nonce")
        preflight_path.write_bytes(controller_trust.canonical_json_bytes(payload))
        preflight_path.chmod(0o600)
    elif case == "tampered":
        payload = json.loads(preflight_path.read_text(encoding="utf-8"))
        payload["nonce_sha256"] = _sha("tampered-preflight-nonce")
        _replace_preflight(
            request_path,
            controller_trust.canonical_json_bytes(payload),
            signature_path.read_bytes(),
        )
    elif case == "wrong_signature":
        payload = preflight_path.read_bytes()
        _replace_preflight(
            request_path,
            payload,
            _sign_controller_payload(
                private_key,
                payload,
                namespace=controller_trust.REPORT_SIGNATURE_NAMESPACE,
            ),
        )
    else:
        assert case in {"cross_run", "cross_scope"}
        _install_signed_preflight(
            request_path,
            private_key,
            metadata,
            changes={
                (
                    "run_fingerprint_sha256"
                    if case == "cross_run"
                    else "target_scope_sha256"
                ): _sha(case)
            },
        )
    evidence = _evidence(request_path)

    with pytest.raises(CollectorError, match=expected_code):
        _formal_collector().finalize_real(
            request_path,
            evidence,
            now=NOW,
        )

    _assert_no_formal_transaction_files(request_path)


def test_formal_prepare_rechecks_preflight_before_returning_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path, _ = _publish(tmp_path)
    verifier, _private_key, _metadata = _active_public_trust(tmp_path)
    monkeypatch.setattr(
        collector_module,
        "FixedControllerTrustVerifier",
        lambda: verifier,
    )
    (
        request_path.parent / collector_module.CONTROLLER_PREFLIGHT_SIGNATURE_FILENAME
    ).unlink()

    with pytest.raises(
        CollectorError,
        match="COLLECTOR_CONTROLLER_PREFLIGHT_INVALID",
    ):
        prepare_controller_report_binding(
            request_path,
            _evidence(request_path),
            now=NOW,
        )

    _assert_no_formal_transaction_files(request_path)


@pytest.mark.parametrize("case", ("mode", "hardlink", "symlink"))
def test_formal_preflight_files_require_private_stable_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    request_path, _ = _publish(tmp_path)
    verifier, _private_key, _metadata = _active_public_trust(tmp_path)
    monkeypatch.setattr(
        collector_module,
        "FixedControllerTrustVerifier",
        lambda: verifier,
    )
    preflight_path = (
        request_path.parent / collector_module.CONTROLLER_PREFLIGHT_FILENAME
    )
    signature_path = (
        request_path.parent
        / collector_module.CONTROLLER_PREFLIGHT_SIGNATURE_FILENAME
    )
    if case == "mode":
        preflight_path.chmod(0o640)
    elif case == "hardlink":
        os.link(signature_path, request_path.parent / "signature-hardlink")
    else:
        original = request_path.parent / "preflight-original"
        preflight_path.rename(original)
        preflight_path.symlink_to(original)

    with pytest.raises(
        CollectorError,
        match="COLLECTOR_CONTROLLER_PREFLIGHT_INVALID",
    ):
        _formal_collector().finalize_real(
            request_path,
            _evidence(request_path),
            now=NOW,
        )

    _assert_no_formal_transaction_files(request_path)


def test_empty_production_trust_root_keeps_formal_commit_on_hold(
    tmp_path: Path,
) -> None:
    request_path, _ = _publish(tmp_path)

    with pytest.raises(
        CollectorError,
        match=COLLECTOR_CONTROLLER_AUTHORITY_HOLD_ERROR,
    ):
        _formal_collector().finalize_real(
            request_path,
            _evidence(request_path),
            controller_report_binding=b"{}\n",
            controller_report_signature=b"not-an-sshsig",
            now=NOW,
        )

    for filename in (
        COLLECTOR_REPORT_FILENAME,
        PROBE_REPORT_FILENAME,
        COLLECTOR_COMMIT_MARKER_FILENAME,
        collector_module._TRANSACTION_LOCK_FILENAME,
    ):
        assert not (request_path.parent / filename).exists()


@pytest.mark.parametrize(
    ("mutation", "resign", "expected_code"),
    (
        (
            lambda payload: payload.update(
                run_fingerprint_sha256=_sha("different-run")
            ),
            True,
            "COLLECTOR_CONTROLLER_BINDING_MISMATCH",
        ),
        (
            lambda payload: payload.update(
                stability_elapsed_milliseconds=1_799_000
            ),
            True,
            "COLLECTOR_CONTROLLER_ATTESTATION_INVALID",
        ),
        (
            lambda payload: payload["observed_captures"][0].update(
                observed_inner_width=1901
            ),
            True,
            "COLLECTOR_CONTROLLER_ATTESTATION_INVALID",
        ),
        (
                lambda payload: payload.update(
                    browser_binary_sha256=_sha("tampered-browser")
                ),
                False,
                COLLECTOR_CONTROLLER_AUTHORITY_HOLD_ERROR,
            ),
    ),
)
def test_formal_sshsig_rejects_cross_run_viewport_stability_and_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: object,
    resign: bool,
    expected_code: str,
) -> None:
    request_path, _ = _publish(tmp_path)
    verifier, private_key, metadata = _active_public_trust(tmp_path)
    evidence = _evidence(request_path)
    monkeypatch.setattr(
        collector_module,
        "FixedControllerTrustVerifier",
        lambda: verifier,
    )
    binding, report_signature = _formal_binding(
        request_path,
        evidence,
        private_key,
        metadata,
    )
    payload = json.loads(binding)
    assert callable(mutation)
    mutation(payload)
    binding = controller_trust.canonical_json_bytes(payload)
    if resign:
        report_signature = _sign_report_binding(private_key, binding)

    with pytest.raises(CollectorError, match=expected_code):
        _formal_collector().finalize_real(
            request_path,
            evidence,
            controller_report_binding=binding,
            controller_report_signature=report_signature,
            now=NOW,
        )

    for filename in (
        COLLECTOR_REPORT_FILENAME,
        PROBE_REPORT_FILENAME,
        COLLECTOR_COMMIT_MARKER_FILENAME,
        collector_module._TRANSACTION_LOCK_FILENAME,
    ):
        assert not (request_path.parent / filename).exists()


def test_require_formal_controller_authority_is_frozen_and_side_effect_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def forbidden_io(*args: object, **kwargs: object) -> None:
        del args, kwargs
        calls.append("unexpected")
        raise AssertionError("authority gate performed I/O")

    assert (
        tuple(signature(require_formal_controller_authority).parameters) == ()
    )
    before = tuple(tmp_path.iterdir())
    monkeypatch.setattr(collector_module.os, "open", forbidden_io)
    monkeypatch.setattr(collector_module.fcntl, "flock", forbidden_io)
    monkeypatch.setattr(socket, "socket", forbidden_io)

    with pytest.raises(
        ProbeReportError,
        match=PROBE_CONTROLLER_AUTHORITY_HOLD_ERROR,
    ) as captured:
        require_formal_controller_authority()

    assert captured.value.args == (PROBE_CONTROLLER_AUTHORITY_HOLD_ERROR,)
    assert calls == []
    assert tuple(tmp_path.iterdir()) == before


def test_guard_initial_missing_report_is_retryable_incomplete(
    tmp_path: Path,
) -> None:
    request_path, expectation = _publish(tmp_path)

    with pytest.raises(
        ProbeReportError,
        match=PROBE_COLLECTOR_INCOMPLETE_ERROR,
    ):
        _formal_guard().load_verified(
            request_path.parent / PROBE_REPORT_FILENAME,
            expectation=expectation,
            now=NOW,
        )


def test_guard_lockless_foreign_fixed_content_is_permanent_invalid(
    tmp_path: Path,
) -> None:
    request_path, expectation = _publish(tmp_path)
    probe_path = request_path.parent / PROBE_REPORT_FILENAME
    probe_path.write_bytes(b"foreign")
    probe_path.chmod(0o600)

    with pytest.raises(
        ProbeReportError,
        match="PROBE_COLLECTOR_ATTESTATION_INVALID",
    ):
        _formal_guard().load_verified(
            probe_path,
            expectation=expectation,
            now=NOW,
        )


def test_clean_install_controller_authority_lifecycle_is_fail_closed(
    tmp_path: Path,
) -> None:
    request_path, expectation = _publish(tmp_path)
    probe_path = request_path.parent / PROBE_REPORT_FILENAME

    with pytest.raises(
        ProbeReportError,
        match=PROBE_COLLECTOR_INCOMPLETE_ERROR,
    ):
        _formal_guard().load_verified(
            probe_path,
            expectation=expectation,
            now=NOW,
        )
    with pytest.raises(
        ProbeReportError,
        match=PROBE_CONTROLLER_AUTHORITY_HOLD_ERROR,
    ):
        load_controller_attestation_capability(request_path.parent)

    capability_path = _write_legacy_capability_file(request_path.parent)
    before = (capability_path.read_bytes(), capability_path.lstat().st_ino)
    with pytest.raises(
        ProbeReportError,
        match=PROBE_CONTROLLER_AUTHORITY_HOLD_ERROR,
    ):
        load_controller_attestation_capability(request_path.parent)
    with pytest.raises(
        CollectorError,
        match=COLLECTOR_CONTROLLER_AUTHORITY_HOLD_ERROR,
    ):
        _formal_collector().finalize_real(
            request_path,
            _evidence(request_path),
            now=NOW,
        )
    assert (capability_path.read_bytes(), capability_path.lstat().st_ino) == before
    assert not probe_path.exists()


def test_committed_legacy_hmac_candidate_is_never_formal_and_tamper_is_permanent(
    tmp_path: Path,
) -> None:
    request_path, expectation = _publish(tmp_path)
    _commit_untrusted_candidate(request_path, _evidence(request_path))
    probe_path = request_path.parent / PROBE_REPORT_FILENAME

    with pytest.raises(
        ProbeReportError,
        match=PROBE_CONTROLLER_AUTHORITY_HOLD_ERROR,
    ):
        _formal_guard(validation_token="w" * 43).load_verified(
            probe_path,
            expectation=expectation,
            now=NOW,
        )

    replacement = json.loads(probe_path.read_bytes())
    replacement["browser"]["time_to_first_audio_ms"] = 0
    probe_path.write_bytes(_canonical(replacement) + b"\n")
    probe_path.chmod(0o600)
    with pytest.raises(
        ProbeReportError,
        match="PROBE_COLLECTOR_ATTESTATION_INVALID",
    ):
        _formal_guard().load_verified(
            probe_path,
            expectation=expectation,
            now=NOW,
        )


def test_raw_controller_key_cannot_bypass_the_fixed_capability_port() -> None:
    with pytest.raises(
        CollectorError,
        match="COLLECTOR_ATTESTATION_KEY_INVALID",
    ):
        FixedChapterE2ECollector(
            validation_token=VALIDATION_TOKEN,
            controller_attestation_capability=(
                CONTROLLER_ATTESTATION_CAPABILITY  # type: ignore[arg-type]
            ),
        )
    with pytest.raises(
        ProbeReportError,
        match="PROBE_COLLECTOR_ATTESTATION_INVALID",
    ):
        SignedCollectorReportGuard(
            validation_token=VALIDATION_TOKEN,
            controller_attestation_capability=(
                CONTROLLER_ATTESTATION_CAPABILITY  # type: ignore[arg-type]
            ),
        )


def test_real_evidence_cannot_enter_the_synthetic_test_seam(
    tmp_path: Path,
) -> None:
    request_path, _ = _publish(tmp_path)
    with pytest.raises(
        CollectorError, match="COLLECTOR_SYNTHETIC_MODE_REQUIRED"
    ):
        FixedChapterE2ECollector().validate_synthetic(
            request_path,
            _evidence(request_path),
            now=NOW,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("controller_id", "arbitrary.module:collector"),
        ("page_url", "http://127.0.0.1:18088/chat/private"),
        ("request_fingerprint_sha256", "f" * 64),
    ],
)
def test_source_is_fixed_and_cannot_be_freely_injected(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    request_path, _ = _publish(tmp_path)
    evidence = replace(_evidence(request_path), **{field: value})

    with pytest.raises(CollectorError, match="COLLECTOR_SOURCE_INVALID"):
        _formal_collector().finalize_real(
            request_path, evidence, now=NOW
        )
    assert not (request_path.parent / PROBE_REPORT_FILENAME).exists()


def test_evidence_contract_has_no_raw_log_body_path_or_command_fields() -> None:
    names = {
        item.name
        for model in (
            CaptureDigest,
            BrowserCollectorEvidence,
            SidecarCollectorEvidence,
            FixedControllerEvidence,
        )
        for item in fields(model)
    }
    assert names.isdisjoint(
        {
            "command",
            "module",
            "script",
            "path",
            "body",
            "text",
            "audio",
            "screenshot",
            "console_log",
            "network_log",
            "database_url",
            "model_path",
            "token",
        }
    )


@pytest.mark.parametrize(
    "case",
    [
        "below_1080p",
        "missing",
        "duplicate",
        "duplicate_screenshot",
        "console_error",
        "overlap",
        "empty_screenshot",
        "no_network",
        "bad_digest",
    ],
)
def test_only_four_desktop_captures_with_clean_digest_evidence_are_allowed(
    tmp_path: Path,
    case: str,
) -> None:
    request_path, _ = _publish(tmp_path)
    evidence = _evidence(request_path)
    captures = list(evidence.browser.captures)
    if case == "below_1080p":
        captures[0] = replace(captures[0], width=1600, height=900)
    elif case == "missing":
        captures.pop()
    elif case == "duplicate":
        captures[-1] = replace(
            captures[-1],
            width=captures[0].width,
            height=captures[0].height,
            assistant_mode=captures[0].assistant_mode,
        )
    elif case == "duplicate_screenshot":
        captures[-1] = replace(
            captures[-1], screenshot_sha256=captures[0].screenshot_sha256
        )
    elif case == "console_error":
        captures[0] = replace(captures[0], console_error_count=1)
    elif case == "overlap":
        captures[0] = replace(captures[0], overlap_count=1)
    elif case == "empty_screenshot":
        captures[0] = replace(captures[0], screenshot_bytes=0)
    elif case == "no_network":
        captures[0] = replace(captures[0], network_request_count=0)
    else:
        captures[0] = replace(captures[0], network_summary_sha256="BAD")
    evidence = replace(
        evidence,
        browser=replace(evidence.browser, captures=tuple(captures)),
    )

    with pytest.raises(
        CollectorError,
        match="COLLECTOR_CAPTURE_(?:MATRIX_)?INVALID",
    ):
        _formal_collector().finalize_real(
            request_path, evidence, now=NOW
        )
    assert not (request_path.parent / PROBE_REPORT_FILENAME).exists()


def test_ui_contract_is_exactly_four_1080p_or_larger_desktop_combinations() -> None:
    assert ALLOWED_VIEWPORTS == ((1920, 1080), (2560, 1440))
    assert ALLOWED_ASSISTANT_MODES == ("collapsed", "expanded")
    assert min(height for _, height in ALLOWED_VIEWPORTS) == 1080
    assert len(_captures()) == 4


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("range_status_codes", (200, 206, 304)),
        ("range_summary_sha256", "bad"),
        ("etag_summary_sha256", "bad"),
        ("etag_observed", False),
        ("if_none_match_304_observed", False),
        ("if_range_206_observed", False),
        ("unsatisfied_range_416_observed", False),
        ("time_to_first_audio_ms", -1),
        ("seam_pairs_checked", 0),
        ("seek_latest_wins", False),
        ("pending_gap_not_skipped", False),
        ("interaction_summary_sha256", "bad"),
        ("edit_actions_observed", 0),
        ("edit_actions_created_tts_writes", 1),
        ("editor_summary_sha256", "bad"),
    ],
)
def test_range_etag_interaction_and_zero_write_gates_fail_closed(
    tmp_path: Path,
    field: str,
    replacement: object,
) -> None:
    request_path, _ = _publish(tmp_path)
    evidence = _evidence(request_path)
    evidence = replace(
        evidence,
        browser=replace(evidence.browser, **{field: replacement}),
    )

    with pytest.raises(CollectorError, match="COLLECTOR_BROWSER_GATE_FAILED"):
        _formal_collector().finalize_real(
            request_path, evidence, now=NOW
        )
    assert not (request_path.parent / PROBE_REPORT_FILENAME).exists()


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("sidecar_container_name", "untrusted-sidecar"),
        ("stability_elapsed_seconds", 1799.999),
        ("stability_elapsed_seconds", 1802.0),
        ("window_started_at", REQUESTED_AT - timedelta(seconds=1)),
        ("window_ended_at", COLLECTED_AT - timedelta(seconds=1)),
        ("request_fingerprint_sha256", "f" * 64),
        ("chapter_audio_duration_seconds", 0),
        ("request_to_ready_seconds", -1),
        ("peak_memory_bytes", -1),
        ("host_paging_observed", "false"),
        ("host_paging_observed", 0),
        ("host_paging_observed", float("nan")),
        ("pageout_delta", -1),
        ("pageout_delta", False),
        ("swapout_delta", -1),
        ("swapout_delta", 0.0),
        ("memory_baseline_median_bytes", -1),
        ("memory_tail_median_bytes", False),
        ("memory_growth_bytes", -1),
        ("memory_growth_limit_bytes", 1.0),
        ("sidecar_memory_growth_observed", 0),
        ("qwenpaw_slowdown_observed", "false"),
        ("qwenpaw_slowdown_observed", 1),
        ("qwenpaw_slowdown_observed", None),
        ("sidecar_restart_count", 1),
        ("health_failure_count", 1),
        ("metric_sample_count", 1),
        ("metric_sample_chain_sha256", "f" * 64),
        ("metrics_summary_sha256", "bad"),
    ],
)
def test_sidecar_30_minute_metrics_gate_fails_closed(
    tmp_path: Path,
    field: str,
    replacement: object,
) -> None:
    request_path, _ = _publish(tmp_path)
    evidence = _evidence(request_path)
    evidence = replace(
        evidence,
        runtime=replace(evidence.runtime, **{field: replacement}),
    )

    with pytest.raises(CollectorError, match="COLLECTOR_RUNTIME_GATE_FAILED"):
        _formal_collector().finalize_real(
            request_path, evidence, now=NOW
        )
    assert not (request_path.parent / PROBE_REPORT_FILENAME).exists()


@pytest.mark.parametrize(
    ("surface", "field", "replacement"),
    [
        ("browser", "time_to_first_audio_ms", 1249),
        ("runtime", "request_to_ready_seconds", 45.5),
        ("runtime", "chapter_audio_duration_seconds", 120.0),
    ],
)
def test_formal_evidence_must_match_executor_performance_seed(
    tmp_path: Path,
    surface: str,
    field: str,
    replacement: object,
) -> None:
    request_path, _ = _publish(tmp_path)
    evidence = _evidence(request_path)
    evidence = replace(
        evidence,
        **{
            surface: replace(
                getattr(evidence, surface),
                **{field: replacement},
            )
        },
    )

    with pytest.raises(
        CollectorError,
        match=(
            "COLLECTOR_BROWSER_GATE_FAILED"
            if surface == "browser"
            else "COLLECTOR_RUNTIME_GATE_FAILED"
        ),
    ):
        _formal_collector().finalize_real(request_path, evidence, now=NOW)


def test_peak_memory_is_derived_from_metric_samples_not_caller_scalar(
    tmp_path: Path,
) -> None:
    request_path, _ = _publish(tmp_path)
    evidence = _evidence(request_path)
    samples = list(evidence.runtime.metric_samples)
    samples[-1] = replace(samples[-1], resident_memory_bytes=1_100_000_000)
    chain = build_sidecar_metric_sample_chain_sha256(
        request_fingerprint_sha256=(
            evidence.runtime.request_fingerprint_sha256
        ),
        window_started_at=evidence.runtime.window_started_at,
        window_ended_at=evidence.runtime.window_ended_at,
        metrics_summary_sha256=evidence.runtime.metrics_summary_sha256,
        samples=tuple(samples),
    )
    forged = replace(
        evidence,
        runtime=replace(
            evidence.runtime,
            metric_samples=tuple(samples),
            metric_sample_chain_sha256=chain,
            peak_memory_bytes=2_000_000_000,
        ),
    )

    with pytest.raises(CollectorError, match="COLLECTOR_RUNTIME_GATE_FAILED"):
        _formal_collector().finalize_real(request_path, forged, now=NOW)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("host_paging_observed", True),
        ("memory_baseline_median_bytes", 1_000_000_003),
        ("memory_tail_median_bytes", 1_000_000_029),
        ("memory_growth_bytes", 27),
        ("memory_growth_limit_bytes", 128 * 1024 * 1024 + 1),
        ("sidecar_memory_growth_observed", True),
    ],
)
def test_memory_summaries_must_match_raw_deltas_and_31_samples(
    tmp_path: Path,
    field: str,
    replacement: object,
) -> None:
    request_path, _ = _publish(tmp_path)
    evidence = _evidence(request_path)
    forged = replace(
        evidence,
        runtime=replace(evidence.runtime, **{field: replacement}),
    )

    with pytest.raises(CollectorError, match="COLLECTOR_RUNTIME_GATE_FAILED"):
        _formal_collector().finalize_real(request_path, forged, now=NOW)


def test_memory_summary_is_rederived_when_sample_rss_changes(
    tmp_path: Path,
) -> None:
    request_path, _ = _publish(tmp_path)
    evidence = _evidence(request_path)
    samples = list(evidence.runtime.metric_samples)
    for index in range(5):
        samples[index] = replace(
            samples[index],
            resident_memory_bytes=1_500_000_000 + index,
        )
    chain = build_sidecar_metric_sample_chain_sha256(
        request_fingerprint_sha256=(
            evidence.runtime.request_fingerprint_sha256
        ),
        window_started_at=evidence.runtime.window_started_at,
        window_ended_at=evidence.runtime.window_ended_at,
        metrics_summary_sha256=evidence.runtime.metrics_summary_sha256,
        samples=tuple(samples),
    )
    forged = replace(
        evidence,
        runtime=replace(
            evidence.runtime,
            metric_samples=tuple(samples),
            metric_sample_chain_sha256=chain,
        ),
    )

    with pytest.raises(CollectorError, match="COLLECTOR_RUNTIME_GATE_FAILED"):
        _formal_collector().finalize_real(request_path, forged, now=NOW)


def test_sidecar_sample_chain_rejects_tampered_sample_digest(
    tmp_path: Path,
) -> None:
    request_path, _ = _publish(tmp_path)
    evidence = _evidence(request_path)
    samples = list(evidence.runtime.metric_samples)
    samples[10] = replace(samples[10], sample_sha256="f" * 64)
    forged = replace(
        evidence,
        runtime=replace(evidence.runtime, metric_samples=tuple(samples)),
    )

    with pytest.raises(CollectorError, match="COLLECTOR_RUNTIME_GATE_FAILED"):
        _formal_collector().finalize_real(request_path, forged, now=NOW)


def test_sidecar_chain_requires_continuous_minute_samples(
    tmp_path: Path,
) -> None:
    request_path, _ = _publish(tmp_path)
    runtime = _evidence(request_path).runtime
    only_endpoints = (
        runtime.metric_samples[0],
        runtime.metric_samples[-1],
    )
    with pytest.raises(CollectorError, match="COLLECTOR_RUNTIME_GATE_FAILED"):
        build_sidecar_metric_sample_chain_sha256(
            request_fingerprint_sha256=runtime.request_fingerprint_sha256,
            window_started_at=runtime.window_started_at,
            window_ended_at=runtime.window_ended_at,
            metrics_summary_sha256=runtime.metrics_summary_sha256,
            samples=only_endpoints,
        )

    gap_samples = list(runtime.metric_samples)
    gap_samples[10] = replace(
        gap_samples[10],
        observed_at=gap_samples[9].observed_at + timedelta(seconds=66),
    )
    with pytest.raises(CollectorError, match="COLLECTOR_RUNTIME_GATE_FAILED"):
        build_sidecar_metric_sample_chain_sha256(
            request_fingerprint_sha256=runtime.request_fingerprint_sha256,
            window_started_at=runtime.window_started_at,
            window_ended_at=runtime.window_ended_at,
            metrics_summary_sha256=runtime.metrics_summary_sha256,
            samples=tuple(gap_samples),
        )


@pytest.mark.parametrize("case", ["starts_before_request", "ends_early"])
def test_sidecar_rejects_invalid_window_even_with_recomputed_chain(
    tmp_path: Path,
    case: str,
) -> None:
    request_path, _ = _publish(tmp_path)
    evidence = _evidence(request_path)
    runtime = evidence.runtime
    samples = list(runtime.metric_samples)
    if case == "starts_before_request":
        started_at = REQUESTED_AT - timedelta(seconds=1)
        ended_at = COLLECTED_AT
        samples[0] = replace(samples[0], observed_at=started_at)
    else:
        started_at = REQUESTED_AT
        ended_at = COLLECTED_AT - timedelta(seconds=2)
        samples[-1] = replace(samples[-1], observed_at=ended_at)
    elapsed = (ended_at - started_at).total_seconds()
    chain = build_sidecar_metric_sample_chain_sha256(
        request_fingerprint_sha256=runtime.request_fingerprint_sha256,
        window_started_at=started_at,
        window_ended_at=ended_at,
        metrics_summary_sha256=runtime.metrics_summary_sha256,
        samples=tuple(samples),
    )
    forged = replace(
        evidence,
        runtime=replace(
            runtime,
            window_started_at=started_at,
            window_ended_at=ended_at,
            stability_elapsed_seconds=elapsed,
            metric_samples=tuple(samples),
            metric_sample_chain_sha256=chain,
        ),
    )

    with pytest.raises(CollectorError, match="COLLECTOR_RUNTIME_GATE_FAILED"):
        _formal_collector().finalize_real(request_path, forged, now=NOW)


def test_request_exactly_binds_scope_editions_outputs_and_30_minutes(
    tmp_path: Path,
) -> None:
    request_path, _ = _publish(tmp_path)
    original = json.loads(request_path.read_text(encoding="utf-8"))
    assert original["binding_seed"]["automatic_edition_id_sha256"] == (
        hashlib.sha256(str(AUTO_EDITION).encode("utf-8")).hexdigest()
    )
    assert original["binding_seed"][
        "automatic_edition_fingerprint_sha256"
    ] == AUTO_EDITION_FINGERPRINT
    assert original["binding_seed"]["manual_edition_id_sha256"] == (
        hashlib.sha256(str(MANUAL_EDITION).encode("utf-8")).hexdigest()
    )
    assert original["binding_seed"][
        "manual_edition_fingerprint_sha256"
    ] == MANUAL_EDITION_FINGERPRINT
    fields_to_change = (
        "run_fingerprint_sha256",
        "target_scope_sha256",
        "automatic_edition_id_sha256",
        "automatic_edition_fingerprint_sha256",
        "manual_edition_id_sha256",
        "manual_edition_fingerprint_sha256",
    )
    for field in fields_to_change:
        _rewrite_request(
            request_path,
            lambda payload, field=field: payload["binding_seed"].__setitem__(
                field, "f" * 64
            ),
        )
        stale_evidence = _evidence(request_path)
        stale_evidence = replace(
            stale_evidence,
            request_fingerprint_sha256=original[
                "request_fingerprint_sha256"
            ],
        )
        with pytest.raises(CollectorError, match="COLLECTOR_SOURCE_INVALID"):
            _formal_collector().finalize_real(
                request_path, stale_evidence, now=NOW
            )
        request_path.write_bytes(_canonical(original) + b"\n")
        request_path.chmod(0o600)

    _rewrite_request(
        request_path,
        lambda payload: payload["binding_seed"].__setitem__(
            "listening_output_hashes", ["c" * 64, "d" * 64]
        ),
    )
    with pytest.raises(CollectorError, match="COLLECTOR_SOURCE_INVALID"):
        _formal_collector().finalize_real(
            request_path,
            replace(
                _evidence(request_path),
                request_fingerprint_sha256=original[
                    "request_fingerprint_sha256"
                ],
            ),
            now=NOW,
        )

    _rewrite_request(
        request_path,
        lambda payload: payload["binding_seed"].__setitem__(
            "required_stability_seconds", 1799.0
        ),
    )
    with pytest.raises(CollectorError, match="COLLECTOR_BINDING_INVALID"):
        _formal_collector().finalize_real(
            request_path, _evidence(request_path), now=NOW
        )


@pytest.mark.parametrize(
    "field",
    (
        "automatic_edition_id_sha256",
        "automatic_edition_fingerprint_sha256",
        "manual_edition_id_sha256",
        "manual_edition_fingerprint_sha256",
    ),
)
def test_request_rejects_a_missing_edition_binding(
    tmp_path: Path,
    field: str,
) -> None:
    request_path, _ = _publish(tmp_path)
    _rewrite_request(
        request_path,
        lambda payload: payload["binding_seed"].pop(field),
    )

    with pytest.raises(CollectorError, match="COLLECTOR_BINDING_INVALID"):
        collector_module._load_request(request_path, now=NOW)


@pytest.mark.parametrize(
    ("automatic_field", "manual_field"),
    (
        ("automatic_edition_id_sha256", "manual_edition_id_sha256"),
        (
            "automatic_edition_fingerprint_sha256",
            "manual_edition_fingerprint_sha256",
        ),
    ),
)
def test_request_rejects_swapped_edition_bindings_against_run_evidence(
    tmp_path: Path,
    automatic_field: str,
    manual_field: str,
) -> None:
    request_path, _ = _publish(tmp_path)
    original = json.loads(request_path.read_text(encoding="utf-8"))

    def swap(payload: dict[str, object]) -> None:
        binding = payload["binding_seed"]
        assert isinstance(binding, dict)
        binding[automatic_field], binding[manual_field] = (
            binding[manual_field],
            binding[automatic_field],
        )

    _rewrite_request(request_path, swap)
    stale_evidence = replace(
        _evidence(request_path),
        request_fingerprint_sha256=original["request_fingerprint_sha256"],
    )

    with pytest.raises(CollectorError, match="COLLECTOR_SOURCE_INVALID"):
        _formal_collector().finalize_real(
            request_path,
            stale_evidence,
            now=NOW,
        )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("request_to_ready_seconds", [30.0]),
        ("request_to_ready_seconds", [30.0, "nan"]),
        ("observed_http_first_audio_ms", [900, -1]),
        ("chapter_audio_duration_seconds", 0),
    ],
)
def test_request_rejects_invalid_performance_seed(
    tmp_path: Path,
    field: str,
    replacement: object,
) -> None:
    request_path, _ = _publish(tmp_path)
    _rewrite_request(
        request_path,
        lambda payload: payload["performance_seed"].__setitem__(
            field, replacement
        ),
    )

    with pytest.raises(
        CollectorError, match="COLLECTOR_PERFORMANCE_SEED_INVALID"
    ):
        collector_module._load_request(request_path, now=NOW)


def test_legacy_probe_request_schema_is_rejected_not_upgraded(
    tmp_path: Path,
) -> None:
    request_path, _ = _publish(tmp_path)
    _rewrite_request(
        request_path,
        lambda payload: payload.__setitem__(
            "schema_version", "moss-tts-chapter-e2e-probe-request/1.1"
        ),
    )

    with pytest.raises(CollectorError, match="COLLECTOR_REQUEST_SCHEMA_INVALID"):
        collector_module._load_request(request_path, now=NOW)

def test_request_matrix_rejects_below_1080p_even_with_valid_fingerprint(
    tmp_path: Path,
) -> None:
    request_path, _ = _publish(tmp_path)
    _rewrite_request(
        request_path,
        lambda payload: payload["required_captures"][0].update(
            {"width": 1600, "height": 900}
        ),
    )

    with pytest.raises(
        CollectorError, match="COLLECTOR_CAPTURE_MATRIX_INVALID"
    ):
        _formal_collector().finalize_real(
            request_path, _evidence(request_path), now=NOW
        )


def test_request_fingerprint_duplicate_json_and_nonfinite_fail_closed(
    tmp_path: Path,
) -> None:
    request_path, _ = _publish(tmp_path)
    evidence = _evidence(request_path)
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    payload["request_fingerprint_sha256"] = "f" * 64
    request_path.write_bytes(_canonical(payload) + b"\n")
    with pytest.raises(
        CollectorError, match="COLLECTOR_REQUEST_FINGERPRINT_MISMATCH"
    ):
        _formal_collector().finalize_real(
            request_path, evidence, now=NOW
        )

    duplicated = (
        '{"schema_version":"duplicate",'
        + json.dumps(payload, separators=(",", ":"))[1:]
    )
    request_path.write_text(duplicated, encoding="utf-8")
    request_path.chmod(0o600)
    with pytest.raises(CollectorError, match="COLLECTOR_REQUEST_INVALID"):
        _formal_collector().finalize_real(
            request_path, evidence, now=NOW
        )

    request_path.write_text('{"x":NaN}', encoding="utf-8")
    request_path.chmod(0o600)
    with pytest.raises(CollectorError, match="COLLECTOR_REQUEST_INVALID"):
        _formal_collector().finalize_real(
            request_path, evidence, now=NOW
        )


def test_private_request_requires_external_owned_0700_parent_and_0600_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path, _ = _publish(tmp_path)
    request_path.chmod(0o640)
    with pytest.raises(CollectorError, match="COLLECTOR_FILE_UNSAFE"):
        _formal_collector().finalize_real(
            request_path, _evidence(request_path), now=NOW
        )

    request_path.chmod(0o600)
    request_path.parent.chmod(0o755)
    with pytest.raises(CollectorError, match="COLLECTOR_FILE_UNSAFE"):
        _formal_collector().finalize_real(
            request_path, _evidence(request_path), now=NOW
        )

    request_path.parent.chmod(0o700)
    actual_uid = os.getuid()
    monkeypatch.setattr(collector_module.os, "getuid", lambda: actual_uid + 1)
    with pytest.raises(CollectorError, match="COLLECTOR_FILE_UNSAFE"):
        _formal_collector().finalize_real(
            request_path, _evidence(request_path), now=NOW
        )


def test_symlink_hardlink_repository_and_installed_roots_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path, _ = _publish(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(request_path.parent, target_is_directory=True)
    with pytest.raises(CollectorError, match="COLLECTOR_PATH_UNSAFE"):
        _formal_collector().finalize_real(
            linked_parent / PROBE_REQUEST_FILENAME,
            _evidence(request_path),
            now=NOW,
        )

    hardlink = outside / PROBE_REQUEST_FILENAME
    os.link(request_path, hardlink)
    with pytest.raises(CollectorError, match="COLLECTOR_FILE_UNSAFE"):
        _formal_collector().finalize_real(
            hardlink, _evidence(request_path), now=NOW
        )
    hardlink.unlink()

    monkeypatch.setattr(collector_module, "REPOSITORY_ROOT", tmp_path)
    with pytest.raises(CollectorError, match="COLLECTOR_PATH_UNSAFE"):
        _formal_collector().finalize_real(
            request_path, _evidence(request_path), now=NOW
        )
    monkeypatch.setattr(collector_module, "REPOSITORY_ROOT", Path("/"))
    monkeypatch.setattr(
        collector_module, "CURRENT_PAWAPP_ROOT", request_path.parent
    )
    with pytest.raises(CollectorError, match="COLLECTOR_PATH_UNSAFE"):
        _formal_collector().finalize_real(
            request_path, _evidence(request_path), now=NOW
        )


def test_output_is_non_overwriting_if_either_fixed_report_exists(
    tmp_path: Path,
) -> None:
    request_path, _ = _publish(tmp_path)
    existing = request_path.parent / PROBE_REPORT_FILENAME
    existing.write_text("do-not-overwrite", encoding="utf-8")
    existing.chmod(0o600)

    with pytest.raises(CollectorError, match="COLLECTOR_REPORT_EXISTS"):
        _commit_untrusted_candidate(request_path, _evidence(request_path))

    assert existing.read_text(encoding="utf-8") == "do-not-overwrite"
    assert not (request_path.parent / COLLECTOR_REPORT_FILENAME).exists()


def test_identical_committed_retry_is_idempotent(tmp_path: Path) -> None:
    request_path, expectation = _publish(tmp_path)
    evidence = _evidence(request_path)
    first = _commit_untrusted_candidate(request_path, evidence)
    paths = (
        request_path.parent / COLLECTOR_REPORT_FILENAME,
        request_path.parent / PROBE_REPORT_FILENAME,
        request_path.parent / COLLECTOR_COMMIT_MARKER_FILENAME,
    )
    before = {
        path.name: (path.read_bytes(), path.lstat().st_ino) for path in paths
    }

    second = _commit_untrusted_candidate(request_path, evidence)

    assert second == first
    assert {
        path.name: (path.read_bytes(), path.lstat().st_ino) for path in paths
    } == before
    _assert_guard_authority_hold(
        request_path.parent / PROBE_REPORT_FILENAME,
        expectation=expectation,
    )


def test_second_publish_crash_is_uncommitted_then_recovers_exactly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path, expectation = _publish(tmp_path)
    evidence = _evidence(request_path)
    original_unlink = collector_module.os.unlink
    failed = False

    def crash_before_second_stage_cleanup(
        path: str | bytes | int,
        *args: object,
        **kwargs: object,
    ) -> None:
        nonlocal failed
        if (
            not failed
            and type(path) is str
            and path.startswith(f".{PROBE_REPORT_FILENAME}.")
            and path.endswith(".stage")
        ):
            failed = True
            raise OSError("simulated-crash")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(
        collector_module.os,
        "unlink",
        crash_before_second_stage_cleanup,
    )
    with pytest.raises(CollectorError, match="COLLECTOR_WRITE_FAILED"):
        _commit_untrusted_candidate(request_path, evidence)

    collector_path = request_path.parent / COLLECTOR_REPORT_FILENAME
    probe_path = request_path.parent / PROBE_REPORT_FILENAME
    marker_path = request_path.parent / COLLECTOR_COMMIT_MARKER_FILENAME
    assert collector_path.exists()
    assert probe_path.exists()
    assert probe_path.lstat().st_nlink == 2
    assert not marker_path.exists()
    with pytest.raises(
        ProbeReportError,
        match=PROBE_COLLECTOR_INCOMPLETE_ERROR,
    ):
        _formal_guard().verify(probe_path, expectation=expectation, now=NOW)

    _commit_untrusted_candidate(request_path, evidence)

    assert probe_path.lstat().st_nlink == 1
    assert marker_path.exists()
    _assert_guard_authority_hold(probe_path, expectation=expectation)


def test_marker_cleanup_crash_is_incomplete_then_exact_retry_commits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path, expectation = _publish(tmp_path)
    evidence = _evidence(request_path)
    original_unlink = collector_module.os.unlink
    failed = False

    def crash_after_marker_link_before_stage_cleanup(
        path: str | bytes | int,
        *args: object,
        **kwargs: object,
    ) -> None:
        nonlocal failed
        if (
            not failed
            and type(path) is str
            and path.startswith(f".{COLLECTOR_COMMIT_MARKER_FILENAME}.")
            and path.endswith(".stage")
        ):
            failed = True
            raise OSError("simulated-marker-cleanup-crash")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(
        collector_module.os,
        "unlink",
        crash_after_marker_link_before_stage_cleanup,
    )
    with pytest.raises(CollectorError, match="COLLECTOR_WRITE_FAILED"):
        _commit_untrusted_candidate(request_path, evidence)
    probe_path = request_path.parent / PROBE_REPORT_FILENAME
    marker_path = request_path.parent / COLLECTOR_COMMIT_MARKER_FILENAME
    assert probe_path.exists()
    assert marker_path.exists()
    assert marker_path.lstat().st_nlink == 2
    with pytest.raises(
        ProbeReportError,
        match=PROBE_COLLECTOR_INCOMPLETE_ERROR,
    ):
        _formal_guard().verify(probe_path, expectation=expectation, now=NOW)

    _commit_untrusted_candidate(request_path, evidence)
    assert marker_path.lstat().st_nlink == 1
    _assert_guard_authority_hold(probe_path, expectation=expectation)


def test_guard_and_finalizer_report_busy_without_blocking(
    tmp_path: Path,
) -> None:
    request_path, expectation = _publish(tmp_path)
    evidence = _evidence(request_path)
    _commit_untrusted_candidate(request_path, evidence)
    probe_path = request_path.parent / PROBE_REPORT_FILENAME
    lock_path = request_path.parent / collector_module._TRANSACTION_LOCK_FILENAME
    lock_fd = os.open(lock_path, os.O_RDWR)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ProbeReportError, match=PROBE_COLLECTOR_BUSY_ERROR):
            _formal_guard().verify(
                probe_path,
                expectation=expectation,
                now=NOW,
            )
        with pytest.raises(CollectorError, match="COLLECTOR_TRANSACTION_BUSY"):
            _commit_untrusted_candidate(request_path, evidence)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def test_foreign_stage_residue_is_never_overwritten_or_removed(
    tmp_path: Path,
) -> None:
    request_path, _ = _publish(tmp_path)
    residue = request_path.parent / (
        f".{PROBE_REPORT_FILENAME}.{'f' * 64}.foreign.stage"
    )
    residue.write_bytes(b"foreign-residue")
    residue.chmod(0o600)
    before = (residue.read_bytes(), residue.lstat().st_ino)

    _commit_untrusted_candidate(request_path, _evidence(request_path))

    assert (residue.read_bytes(), residue.lstat().st_ino) == before


def test_request_file_identity_must_remain_stable_while_reading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path, _ = _publish(tmp_path)
    original_bytes = request_path.read_bytes()
    evidence = _evidence(request_path)
    original_read = collector_module.os.read
    replaced = False

    def replace_after_first_read(descriptor: int, size: int) -> bytes:
        nonlocal replaced
        data = original_read(descriptor, size)
        if data and not replaced:
            replaced = True
            request_path.unlink()
            request_path.write_bytes(original_bytes)
            request_path.chmod(0o600)
        return data

    monkeypatch.setattr(collector_module.os, "read", replace_after_first_read)
    with pytest.raises(CollectorError, match="COLLECTOR_FILE_UNSAFE"):
        _formal_collector().finalize_real(
            request_path, evidence, now=NOW
        )


def test_parent_identity_cannot_change_between_request_read_and_report_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path, _ = _publish(tmp_path)
    evidence = _evidence(request_path)
    original_preflight = collector_module._ensure_outputs_absent
    original_parent = request_path.parent
    moved_parent = tmp_path / "private-before-replacement"

    def replace_parent(parent: Path, identity: tuple[int, ...]) -> None:
        parent.rename(moved_parent)
        parent.mkdir(mode=0o700)
        parent.chmod(0o700)
        original_preflight(parent, identity)

    monkeypatch.setattr(
        collector_module,
        "_ensure_outputs_absent",
        replace_parent,
    )
    with pytest.raises(CollectorError, match="COLLECTOR_FILE_UNSAFE"):
        _commit_untrusted_candidate(request_path, evidence)
    assert not (moved_parent / COLLECTOR_REPORT_FILENAME).exists()
    assert not (original_parent / COLLECTOR_REPORT_FILENAME).exists()


def test_collection_time_must_be_fresh_and_follow_the_same_request(
    tmp_path: Path,
) -> None:
    request_path, _ = _publish(tmp_path)
    for collected_at, current in (
        (REQUESTED_AT - timedelta(seconds=1), NOW),
        (NOW + timedelta(seconds=31), NOW),
        (COLLECTED_AT, COLLECTED_AT + timedelta(minutes=16)),
        (COLLECTED_AT.replace(microsecond=1), NOW),
    ):
        with pytest.raises(
            CollectorError, match="COLLECTOR_COLLECTION_TIME_INVALID"
        ):
            _formal_collector().finalize_real(
                request_path,
                replace(_evidence(request_path), collected_at=collected_at),
                now=current,
            )


def test_errors_do_not_render_private_path_or_contents(tmp_path: Path) -> None:
    private = tmp_path / "PRIVATE-PATH-MARKER"
    private.mkdir(mode=0o700)
    path = private / PROBE_REQUEST_FILENAME
    secret = "DO-NOT-LEAK-PRIVATE-CONTENT"
    path.write_text(secret, encoding="utf-8")
    path.chmod(0o600)

    with pytest.raises(CollectorError) as captured:
        _formal_collector().finalize_real(
            path,
            FixedControllerEvidence(
                controller_id=FIXED_CONTROLLER_ID,
                page_url=FIXED_PUBLIC_PAGE_URL,
                request_fingerprint_sha256="a" * 64,
                collected_at=COLLECTED_AT,
                synthetic=False,
                browser=BrowserCollectorEvidence(
                    observer_report_sha256="8" * 64,
                    captures=(),
                    range_status_codes=EXPECTED_RANGE_STATUS_CODES,
                    range_summary_sha256="a" * 64,
                    etag_summary_sha256="b" * 64,
                    etag_observed=True,
                    if_none_match_304_observed=True,
                    if_range_206_observed=True,
                    unsatisfied_range_416_observed=True,
                    time_to_first_audio_ms=0,
                    seam_pairs_checked=1,
                    seek_latest_wins=True,
                    pending_gap_not_skipped=True,
                    interaction_summary_sha256="c" * 64,
                    edit_actions_observed=1,
                    edit_actions_created_tts_writes=0,
                    editor_summary_sha256="d" * 64,
                ),
                runtime=SidecarCollectorEvidence(
                    sidecar_container_name=EXPECTED_SIDECAR_CONTAINER_NAME,
                    window_started_at=REQUESTED_AT,
                    window_ended_at=COLLECTED_AT,
                    request_fingerprint_sha256="a" * 64,
                    stability_elapsed_seconds=1800,
                    chapter_audio_duration_seconds=1,
                    request_to_ready_seconds=0,
                    peak_memory_bytes=0,
                    host_paging_observed=False,
                    pageout_delta=0,
                    swapout_delta=0,
                    memory_baseline_median_bytes=0,
                    memory_tail_median_bytes=0,
                    memory_growth_bytes=0,
                    memory_growth_limit_bytes=128 * 1024 * 1024,
                    sidecar_memory_growth_observed=False,
                    qwenpaw_slowdown_observed=False,
                    sidecar_restart_count=0,
                    health_failure_count=0,
                    metric_sample_count=31,
                    metric_samples=_metric_samples(),
                    metric_sample_chain_sha256="f" * 64,
                    metrics_summary_sha256="e" * 64,
                ),
            ),
            now=NOW,
        )

    rendered = "".join(
        traceback.format_exception(
            captured.type,
            captured.value,
            captured.tb,
        )
    )
    assert str(captured.value) == "COLLECTOR_REQUEST_INVALID"
    assert str(path) not in rendered
    assert secret not in rendered
