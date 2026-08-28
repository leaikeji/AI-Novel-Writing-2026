from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import base64
import hashlib
from inspect import signature
import json
from pathlib import Path
import subprocess

import pytest

import scripts.tts.chapter_e2e_controller_trust as trust_module
from scripts.tts.chapter_e2e_controller_trust import (
    CONTROLLER_ID,
    CONTROLLER_PREFLIGHT_BINDING_MISMATCH_ERROR,
    CONTROLLER_PREFLIGHT_INVALID_ERROR,
    CONTROLLER_PREFLIGHT_SCHEMA_VERSION,
    CONTROLLER_REPORT_BINDING_INVALID_ERROR,
    CONTROLLER_REPORT_BINDING_MISMATCH_ERROR,
    CONTROLLER_REPORT_BINDING_SCHEMA_VERSION,
    CONTROLLER_SIGNATURE_INVALID_ERROR,
    CONTROLLER_TRUST_POLICY_INVALID_ERROR,
    CONTROLLER_TRUST_POLICY_SCHEMA_VERSION,
    CONTROLLER_TRUST_ROOT_HOLD_ERROR,
    FIXED_REQUIRED_CAPTURES,
    FIXED_REQUIRED_STABILITY_MILLISECONDS,
    FixedControllerTrustVerifier,
    PREFLIGHT_SIGNATURE_NAMESPACE,
    PreflightExpectation,
    REPORT_SIGNATURE_NAMESPACE,
    ReportExpectation,
    SSH_KEYGEN_PATH,
    ControllerTrustError,
    _test_verifier,
    canonical_json_bytes,
)


NOW = datetime(2026, 8, 27, 12, 45, 0, tzinfo=timezone.utc)
ISSUED_AT = NOW - timedelta(minutes=2)
EXPIRES_AT = NOW + timedelta(minutes=8)
WINDOW_STARTED_AT = NOW - timedelta(minutes=31)
WINDOW_ENDED_AT = NOW - timedelta(minutes=1)
KEY_ID = "t4k-controller-ed25519-test-key-01"
PRINCIPAL = "t4k-controller-test-key-01@ai-novel-world-2026.local"
BUILD_SHA256 = hashlib.sha256(b"fixed-controller-build").hexdigest()
BROWSER_SHA256 = hashlib.sha256(b"fixed-edge-binary").hexdigest()


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _timestamp(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_private(path: Path, data: bytes) -> None:
    path.write_bytes(data)
    path.chmod(0o600)


def _generate_key(directory: Path, name: str = "controller") -> tuple[Path, str, str]:
    private_key = directory / name
    completed = subprocess.run(
        [
            str(SSH_KEYGEN_PATH),
            "-q",
            "-t",
            "ed25519",
            "-N",
            "",
            "-C",
            name,
            "-f",
            str(private_key),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    private_key.chmod(0o600)
    public_key_path = private_key.with_suffix(".pub")
    public_key_path.chmod(0o600)
    parts = public_key_path.read_text(encoding="ascii").strip().split()
    assert parts[0] == "ssh-ed25519"
    blob = base64.b64decode(parts[1], validate=True)
    fingerprint = "SHA256:" + base64.b64encode(
        hashlib.sha256(blob).digest()
    ).decode("ascii").rstrip("=")
    return private_key, parts[1], fingerprint


def _allowed_line(principal: str, blob: str) -> str:
    return (
        f'{principal} namespaces="{PREFLIGHT_SIGNATURE_NAMESPACE},'
        f'{REPORT_SIGNATURE_NAMESPACE}" ssh-ed25519 {blob}'
    )


def _build_verifier(
    tmp_path: Path,
    *,
    status: str = "active",
    not_before: datetime = NOW - timedelta(days=1),
    not_after: datetime = NOW + timedelta(days=1),
    build_hashes: tuple[str, ...] = (BUILD_SHA256,),
    name: str = "controller",
) -> tuple[object, Path, dict[str, object]]:
    directory = tmp_path / name
    directory.mkdir(mode=0o700)
    private_key, blob, fingerprint = _generate_key(directory, name=name)
    allowed_path = directory / "controller_allowed_signers"
    allowed_text = (
        _allowed_line(PRINCIPAL, blob) + "\n" if status == "active" else ""
    )
    _write_private(allowed_path, allowed_text.encode("ascii"))
    policy: dict[str, object] = {
        "schema_version": CONTROLLER_TRUST_POLICY_SCHEMA_VERSION,
        "generation": 1,
        "allowed_signers_sha256": hashlib.sha256(
            allowed_text.encode("ascii")
        ).hexdigest(),
        "keys": [
            {
                "key_id": KEY_ID,
                "principal": PRINCIPAL,
                "algorithm": "ssh-ed25519",
                "public_key_fingerprint": fingerprint,
                "status": status,
                "not_before": _timestamp(not_before),
                "not_after": _timestamp(not_after),
                "allowed_controller_build_sha256": sorted(build_hashes),
                "allowed_browser_build_sha256": [BROWSER_SHA256],
            }
        ],
    }
    policy_path = directory / "controller_trust_policy.json"
    policy_raw = canonical_json_bytes(policy)
    _write_private(policy_path, policy_raw)
    metadata = {
        "policy_path": policy_path,
        "allowed_path": allowed_path,
        "policy_sha256": hashlib.sha256(policy_raw).hexdigest(),
        "allowed_sha256": hashlib.sha256(allowed_text.encode("ascii")).hexdigest(),
        "policy": policy,
        "allowed_text": allowed_text,
    }
    return (
        _test_verifier(policy_path, allowed_path),
        private_key,
        metadata,
    )


def _sign(private_key: Path, payload: bytes, namespace: str) -> bytes:
    completed = subprocess.run(
        [
            str(SSH_KEYGEN_PATH),
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
        check=False,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    assert completed.stdout.startswith(b"-----BEGIN SSH SIGNATURE-----\n")
    return completed.stdout


def _preflight_expectation() -> PreflightExpectation:
    return PreflightExpectation(
        nonce_sha256=_sha("nonce"),
        run_fingerprint_sha256=_sha("run"),
        target_scope_sha256=_sha("scope"),
        operator_envelope_sha256=_sha("operator-envelope"),
        fixture_manifest_sha256=_sha("fixture"),
    )


def _preflight_payload(
    metadata: dict[str, object],
    *,
    expectation: PreflightExpectation | None = None,
) -> dict[str, object]:
    expected = expectation or _preflight_expectation()
    return {
        "schema_version": CONTROLLER_PREFLIGHT_SCHEMA_VERSION,
        "issued_at": _timestamp(ISSUED_AT),
        "expires_at": _timestamp(EXPIRES_AT),
        "nonce_sha256": expected.nonce_sha256,
        "run_fingerprint_sha256": expected.run_fingerprint_sha256,
        "target_scope_sha256": expected.target_scope_sha256,
        "operator_envelope_sha256": expected.operator_envelope_sha256,
        "fixture_manifest_sha256": expected.fixture_manifest_sha256,
        "required_stability_milliseconds": (
            FIXED_REQUIRED_STABILITY_MILLISECONDS
        ),
        "required_captures": [
            {
                "target_css_width": width,
                "target_css_height": height,
                "assistant_mode": mode,
            }
            for width, height, mode in FIXED_REQUIRED_CAPTURES
        ],
        "controller_id": CONTROLLER_ID,
        "controller_build_sha256": BUILD_SHA256,
        "signing_key_id": KEY_ID,
        "signer_principal": PRINCIPAL,
        "signature_namespace": PREFLIGHT_SIGNATURE_NAMESPACE,
        "trust_policy_sha256": metadata["policy_sha256"],
        "allowed_signers_sha256": metadata["allowed_sha256"],
    }


def _report_expectation(preflight_sha256: str) -> ReportExpectation:
    return ReportExpectation(
        preflight_payload_sha256=preflight_sha256,
        run_fingerprint_sha256=_sha("run"),
        target_scope_sha256=_sha("scope"),
        probe_request_sha256=_sha("probe-request-file"),
        request_fingerprint_sha256=_sha("probe-request"),
        automatic_edition_fingerprint_sha256=_sha("automatic-edition"),
        manual_edition_fingerprint_sha256=_sha("manual-edition"),
        listening_output_hashes=tuple(
            sorted((_sha("automatic-output"), _sha("manual-output")))
        ),
        collector_report_sha256=_sha("collector-report"),
        probe_report_sha256=_sha("probe-report"),
    )


def _capture_payload(
    width: int,
    height: int,
    mode: str,
    index: int,
) -> dict[str, object]:
    outer_hints = {
        (1920, 1080): (1939, 1091),
        (2560, 1440): (2586, 1455),
    }
    outer_width, outer_height = outer_hints[(width, height)]
    return {
        "target_css_width": width,
        "target_css_height": height,
        "requested_outer_width": outer_width,
        "requested_outer_height": outer_height,
        "observed_inner_width": width,
        "observed_inner_height": height,
        "device_pixel_ratio_micros": 1_010_000,
        "screenshot_pixel_width": round(width * 1.01),
        "screenshot_pixel_height": round(height * 1.01),
        "assistant_mode_requested": mode,
        "assistant_mode_observed": mode,
        "calibration_attempt_count": 2,
        "calibration_summary_sha256": _sha(f"calibration-{index}"),
        "screenshot_sha256": _sha(f"screenshot-{index}"),
        "console_summary_sha256": _sha(f"console-{index}"),
        "network_summary_sha256": _sha(f"network-{index}"),
    }


def _report_payload(
    metadata: dict[str, object],
    expectation: ReportExpectation,
) -> dict[str, object]:
    return {
        "schema_version": CONTROLLER_REPORT_BINDING_SCHEMA_VERSION,
        "signed_at": _timestamp(NOW),
        "preflight_payload_sha256": expectation.preflight_payload_sha256,
        "run_fingerprint_sha256": expectation.run_fingerprint_sha256,
        "target_scope_sha256": expectation.target_scope_sha256,
        "probe_request_sha256": expectation.probe_request_sha256,
        "request_fingerprint_sha256": expectation.request_fingerprint_sha256,
        "automatic_edition_fingerprint_sha256": (
            expectation.automatic_edition_fingerprint_sha256
        ),
        "manual_edition_fingerprint_sha256": (
            expectation.manual_edition_fingerprint_sha256
        ),
        "listening_output_hashes": list(expectation.listening_output_hashes),
        "required_stability_milliseconds": (
            FIXED_REQUIRED_STABILITY_MILLISECONDS
        ),
        "observed_captures": [
            _capture_payload(width, height, mode, index)
            for index, (width, height, mode) in enumerate(
                FIXED_REQUIRED_CAPTURES,
                start=1,
            )
        ],
        "window_started_at": _timestamp(WINDOW_STARTED_AT),
        "window_ended_at": _timestamp(WINDOW_ENDED_AT),
        "stability_elapsed_milliseconds": (
            FIXED_REQUIRED_STABILITY_MILLISECONDS
        ),
        "metric_sample_count": 31,
        "metric_sample_chain_sha256": _sha("metric-chain"),
        "collector_report_sha256": expectation.collector_report_sha256,
        "probe_report_sha256": expectation.probe_report_sha256,
        "controller_id": CONTROLLER_ID,
        "controller_build_sha256": BUILD_SHA256,
        "browser_binary_sha256": BROWSER_SHA256,
        "signing_key_id": KEY_ID,
        "signer_principal": PRINCIPAL,
        "signature_namespace": REPORT_SIGNATURE_NAMESPACE,
        "trust_policy_sha256": metadata["policy_sha256"],
        "allowed_signers_sha256": metadata["allowed_sha256"],
    }


def test_fixed_production_port_has_no_path_or_signing_input_and_empty_root_holds() -> None:
    assert tuple(signature(FixedControllerTrustVerifier).parameters) == ()
    source = Path(trust_module.__file__).read_text(encoding="utf-8")
    assert "subprocess.run" in source
    assert '"verify"' in source
    assert '"sign"' not in source
    assert "os.environ" not in source
    assert 'getenv("SSH_AUTH_SOCK"' not in source

    verifier = FixedControllerTrustVerifier()
    expectation = _preflight_expectation()
    with pytest.raises(
        ControllerTrustError,
        match=CONTROLLER_TRUST_ROOT_HOLD_ERROR,
    ):
        verifier.verify_preflight(
            canonical_json_bytes({}),
            b"not-a-signature",
            expectation=expectation,
            now=NOW,
        )


def test_valid_preflight_and_report_binding_verify_with_public_key_only(
    tmp_path: Path,
) -> None:
    verifier, private_key, metadata = _build_verifier(tmp_path)
    preflight_expectation = _preflight_expectation()
    preflight_raw = canonical_json_bytes(_preflight_payload(metadata))
    preflight_signature = _sign(
        private_key,
        preflight_raw,
        PREFLIGHT_SIGNATURE_NAMESPACE,
    )

    preflight = verifier.verify_preflight(
        preflight_raw,
        preflight_signature,
        expectation=preflight_expectation,
        now=NOW,
    )

    assert preflight.key_id == KEY_ID
    assert preflight.principal == PRINCIPAL
    assert preflight.payload_sha256 == hashlib.sha256(preflight_raw).hexdigest()
    report_expectation = _report_expectation(preflight.payload_sha256)
    report_raw = canonical_json_bytes(
        _report_payload(metadata, report_expectation)
    )
    report_signature = _sign(
        private_key,
        report_raw,
        REPORT_SIGNATURE_NAMESPACE,
    )

    report = verifier.verify_report_binding(
        report_raw,
        report_signature,
        expectation=report_expectation,
        now=NOW,
    )

    assert report.payload_sha256 == hashlib.sha256(report_raw).hexdigest()
    assert report.controller_build_sha256 == BUILD_SHA256
    assert report.browser_binary_sha256 == BROWSER_SHA256
    assert report.stability_elapsed_milliseconds == 1_800_000
    assert report.metric_sample_count == 31
    assert tuple(
        (
            capture.observed_inner_width,
            capture.observed_inner_height,
            capture.assistant_mode_observed,
        )
        for capture in report.captures
    ) == FIXED_REQUIRED_CAPTURES


@pytest.mark.parametrize(
    ("mutation", "namespace", "expected_code"),
    [
        (
            lambda payload: payload.__setitem__("signing_key_id", "t4k-controller-ed25519-unknown-key"),
            PREFLIGHT_SIGNATURE_NAMESPACE,
            CONTROLLER_TRUST_ROOT_HOLD_ERROR,
        ),
        (
            lambda payload: payload.__setitem__(
                "signer_principal",
                "t4k-controller-other-key-01@ai-novel-world-2026.local",
            ),
            PREFLIGHT_SIGNATURE_NAMESPACE,
            CONTROLLER_TRUST_ROOT_HOLD_ERROR,
        ),
        (
            lambda payload: payload.__setitem__(
                "controller_build_sha256", _sha("wrong-build")
            ),
            PREFLIGHT_SIGNATURE_NAMESPACE,
            CONTROLLER_TRUST_ROOT_HOLD_ERROR,
        ),
        (
            lambda payload: None,
            REPORT_SIGNATURE_NAMESPACE,
            CONTROLLER_SIGNATURE_INVALID_ERROR,
        ),
    ],
)
def test_unknown_key_wrong_principal_build_or_signature_namespace_fail_closed(
    tmp_path: Path,
    mutation: object,
    namespace: str,
    expected_code: str,
) -> None:
    verifier, private_key, metadata = _build_verifier(tmp_path)
    payload = _preflight_payload(metadata)
    assert callable(mutation)
    mutation(payload)
    raw = canonical_json_bytes(payload)
    signed = _sign(private_key, raw, namespace)

    with pytest.raises(ControllerTrustError, match=expected_code):
        verifier.verify_preflight(
            raw,
            signed,
            expectation=_preflight_expectation(),
            now=NOW,
        )


def test_tamper_and_cross_run_replay_fail_closed(tmp_path: Path) -> None:
    verifier, private_key, metadata = _build_verifier(tmp_path)
    raw = canonical_json_bytes(_preflight_payload(metadata))
    signed = _sign(private_key, raw, PREFLIGHT_SIGNATURE_NAMESPACE)
    tampered = raw.replace(_sha("fixture").encode(), _sha("tampered").encode())

    with pytest.raises(
        ControllerTrustError,
        match=CONTROLLER_PREFLIGHT_BINDING_MISMATCH_ERROR,
    ):
        verifier.verify_preflight(
            tampered,
            signed,
            expectation=_preflight_expectation(),
            now=NOW,
        )

    replay_expectation = PreflightExpectation(
        nonce_sha256=_sha("other-nonce"),
        run_fingerprint_sha256=_sha("other-run"),
        target_scope_sha256=_sha("scope"),
        operator_envelope_sha256=_sha("operator-envelope"),
        fixture_manifest_sha256=_sha("fixture"),
    )
    with pytest.raises(
        ControllerTrustError,
        match=CONTROLLER_PREFLIGHT_BINDING_MISMATCH_ERROR,
    ):
        verifier.verify_preflight(
            raw,
            signed,
            expectation=replay_expectation,
            now=NOW,
        )


@pytest.mark.parametrize(
    ("status", "not_before", "not_after"),
    [
        ("revoked", NOW - timedelta(days=1), NOW + timedelta(days=1)),
        ("active", NOW - timedelta(days=2), NOW - timedelta(days=1)),
        ("active", NOW + timedelta(days=1), NOW + timedelta(days=2)),
    ],
)
def test_revoked_expired_or_not_yet_valid_key_holds(
    tmp_path: Path,
    status: str,
    not_before: datetime,
    not_after: datetime,
) -> None:
    verifier, private_key, metadata = _build_verifier(
        tmp_path,
        status=status,
        not_before=not_before,
        not_after=not_after,
    )
    raw = canonical_json_bytes(_preflight_payload(metadata))
    signed = _sign(private_key, raw, PREFLIGHT_SIGNATURE_NAMESPACE)

    with pytest.raises(
        ControllerTrustError,
        match=CONTROLLER_TRUST_ROOT_HOLD_ERROR,
    ):
        verifier.verify_preflight(
            raw,
            signed,
            expectation=_preflight_expectation(),
            now=NOW,
        )


def test_wrong_private_key_and_noncanonical_payload_fail_signature_or_schema(
    tmp_path: Path,
) -> None:
    verifier, _private_key, metadata = _build_verifier(tmp_path)
    other_directory = tmp_path / "other"
    other_directory.mkdir(mode=0o700)
    other_private, _blob, _fingerprint = _generate_key(other_directory, "other")
    payload = _preflight_payload(metadata)
    raw = canonical_json_bytes(payload)
    wrong_signature = _sign(
        other_private,
        raw,
        PREFLIGHT_SIGNATURE_NAMESPACE,
    )
    with pytest.raises(
        ControllerTrustError,
        match=CONTROLLER_SIGNATURE_INVALID_ERROR,
    ):
        verifier.verify_preflight(
            raw,
            wrong_signature,
            expectation=_preflight_expectation(),
            now=NOW,
        )

    noncanonical = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    with pytest.raises(
        ControllerTrustError,
        match=CONTROLLER_PREFLIGHT_INVALID_ERROR,
    ):
        verifier.verify_preflight(
            noncanonical,
            wrong_signature,
            expectation=_preflight_expectation(),
            now=NOW,
        )


def test_preflight_expiry_and_policy_or_allowed_signers_tamper_fail_closed(
    tmp_path: Path,
) -> None:
    verifier, private_key, metadata = _build_verifier(tmp_path)
    payload = _preflight_payload(metadata)
    payload["expires_at"] = _timestamp(NOW)
    raw = canonical_json_bytes(payload)
    signed = _sign(private_key, raw, PREFLIGHT_SIGNATURE_NAMESPACE)
    with pytest.raises(
        ControllerTrustError,
        match=CONTROLLER_PREFLIGHT_INVALID_ERROR,
    ):
        verifier.verify_preflight(
            raw,
            signed,
            expectation=_preflight_expectation(),
            now=NOW,
        )

    allowed_path = metadata["allowed_path"]
    assert isinstance(allowed_path, Path)
    allowed_path.write_text("# tampered\n", encoding="ascii")
    allowed_path.chmod(0o600)
    with pytest.raises(
        ControllerTrustError,
        match=CONTROLLER_TRUST_POLICY_INVALID_ERROR,
    ):
        verifier.verify_preflight(
            raw,
            signed,
            expectation=_preflight_expectation(),
            now=NOW,
        )


def test_report_rejects_requested_name_instead_of_observed_exact_viewport(
    tmp_path: Path,
) -> None:
    verifier, private_key, metadata = _build_verifier(tmp_path)
    expectation = _report_expectation(_sha("preflight-payload"))
    payload = _report_payload(metadata, expectation)
    payload["observed_captures"][0]["observed_inner_width"] = 1901
    raw = canonical_json_bytes(payload)
    signed = _sign(private_key, raw, REPORT_SIGNATURE_NAMESPACE)

    with pytest.raises(
        ControllerTrustError,
        match=CONTROLLER_REPORT_BINDING_INVALID_ERROR,
    ):
        verifier.verify_report_binding(
            raw,
            signed,
            expectation=expectation,
            now=NOW,
        )


def test_report_hash_replay_tamper_stability_and_age_fail_closed(
    tmp_path: Path,
) -> None:
    verifier, private_key, metadata = _build_verifier(tmp_path)
    expectation = _report_expectation(_sha("preflight-payload"))
    payload = _report_payload(metadata, expectation)

    replay_expectation = replace(
        expectation,
        collector_report_sha256=_sha("other-collector"),
    )
    raw = canonical_json_bytes(payload)
    signed = _sign(private_key, raw, REPORT_SIGNATURE_NAMESPACE)
    with pytest.raises(
        ControllerTrustError,
        match=CONTROLLER_REPORT_BINDING_MISMATCH_ERROR,
    ):
        verifier.verify_report_binding(
            raw,
            signed,
            expectation=replay_expectation,
            now=NOW,
        )

    short = deepcopy(payload)
    short["window_started_at"] = _timestamp(NOW - timedelta(minutes=30))
    short["window_ended_at"] = _timestamp(NOW - timedelta(seconds=1))
    short["stability_elapsed_milliseconds"] = 1_799_000
    short_raw = canonical_json_bytes(short)
    short_signed = _sign(private_key, short_raw, REPORT_SIGNATURE_NAMESPACE)
    with pytest.raises(
        ControllerTrustError,
        match=CONTROLLER_REPORT_BINDING_INVALID_ERROR,
    ):
        verifier.verify_report_binding(
            short_raw,
            short_signed,
            expectation=expectation,
            now=NOW,
        )

    with pytest.raises(
        ControllerTrustError,
        match=CONTROLLER_REPORT_BINDING_INVALID_ERROR,
    ):
        verifier.verify_report_binding(
            raw,
            signed,
            expectation=expectation,
            now=NOW + timedelta(minutes=16),
        )


def test_public_trust_files_and_test_private_key_are_never_confused(
    tmp_path: Path,
) -> None:
    _verifier, private_key, _metadata = _build_verifier(tmp_path)
    assert private_key.is_relative_to(tmp_path)
    assert not private_key.is_relative_to(Path(trust_module.__file__).parent)
    assert "PRIVATE KEY" not in trust_module.ALLOWED_SIGNERS_PATH.read_text(
        encoding="utf-8"
    )
    production_policy = json.loads(
        trust_module.TRUST_POLICY_PATH.read_text(encoding="utf-8")
    )
    assert production_policy["keys"] == []


def test_group_writable_public_policy_is_rejected(tmp_path: Path) -> None:
    verifier, private_key, metadata = _build_verifier(tmp_path)
    policy_path = metadata["policy_path"]
    assert isinstance(policy_path, Path)
    policy_path.chmod(0o620)
    raw = canonical_json_bytes(_preflight_payload(metadata))
    signed = _sign(private_key, raw, PREFLIGHT_SIGNATURE_NAMESPACE)

    with pytest.raises(
        ControllerTrustError,
        match=CONTROLLER_TRUST_POLICY_INVALID_ERROR,
    ):
        verifier.verify_preflight(
            raw,
            signed,
            expectation=_preflight_expectation(),
            now=NOW,
        )
