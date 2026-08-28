from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import base64
import binascii
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import zlib

import pytest
import scripts.tts.chapter_e2e_controller_host as host_module

from scripts.tts.chapter_e2e_controller_host import (
    BrowserCaptureObservation,
    CalibrationObservation,
    CONTROLLER_CAPTURE_INVALID_ERROR,
    CONTROLLER_STABILITY_INVALID_ERROR,
    ControllerHostError,
    PreflightObservation,
    ReportBindingObservation,
    RuntimeMetricObservation,
    _test_controller_host,
    derive_preflight_expectation,
)
from scripts.tts.chapter_e2e_controller_trust import (
    CONTROLLER_TRUST_POLICY_SCHEMA_VERSION,
    CONTROLLER_TRUST_ROOT_HOLD_ERROR,
    FIXED_REQUIRED_CAPTURES,
    PREFLIGHT_SIGNATURE_NAMESPACE,
    REPORT_SIGNATURE_NAMESPACE,
    SSH_KEYGEN_PATH,
    canonical_json_bytes,
)
from scripts.tts.chapter_e2e_collector import (
    SidecarMetricSampleDigest,
    build_sidecar_metric_sample_chain_sha256,
)
from scripts.tts.chapter_e2e_metric_chain import build_metric_summary_sha256


NOW = datetime(2026, 8, 27, 13, 0, 0, tzinfo=timezone.utc)
RUN_ID = "11111111-2222-4333-8444-555555555555"
NOVEL_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
DOCUMENT_ID = "01234567-89ab-4cde-8fab-0123456789ab"
KEY_ID = "t4k-controller-ed25519-test-key-01"
PRINCIPAL = "t4k-controller-test-key-01@ai-novel-world-2026.local"
BUILD_SHA = hashlib.sha256(b"controller-build").hexdigest()
BROWSER_SHA = hashlib.sha256(b"browser-build").hexdigest()


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _timestamp(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _trust_files(tmp_path: Path) -> tuple[Path, Path]:
    private = tmp_path / "controller"
    result = subprocess.run(
        [
            str(SSH_KEYGEN_PATH),
            "-q",
            "-t",
            "ed25519",
            "-N",
            "",
            "-f",
            str(private),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0
    parts = private.with_suffix(".pub").read_text(encoding="ascii").split()
    blob = base64.b64decode(parts[1], validate=True)
    fingerprint = "SHA256:" + base64.b64encode(
        hashlib.sha256(blob).digest()
    ).decode().rstrip("=")
    allowed = tmp_path / "allowed_signers"
    allowed_raw = (
        f'{PRINCIPAL} namespaces="{PREFLIGHT_SIGNATURE_NAMESPACE},'
        f'{REPORT_SIGNATURE_NAMESPACE}" ssh-ed25519 {parts[1]}\n'
    ).encode()
    allowed.write_bytes(allowed_raw)
    allowed.chmod(0o600)
    policy = {
        "schema_version": CONTROLLER_TRUST_POLICY_SCHEMA_VERSION,
        "generation": 1,
        "allowed_signers_sha256": hashlib.sha256(allowed_raw).hexdigest(),
        "keys": [
            {
                "algorithm": "ssh-ed25519",
                "allowed_controller_build_sha256": [BUILD_SHA],
                "allowed_browser_build_sha256": [BROWSER_SHA],
                "key_id": KEY_ID,
                "not_after": _timestamp(NOW + timedelta(days=1)),
                "not_before": _timestamp(NOW - timedelta(days=1)),
                "principal": PRINCIPAL,
                "public_key_fingerprint": fingerprint,
                "status": "active",
            }
        ],
    }
    policy_path = tmp_path / "policy.json"
    policy_path.write_bytes(canonical_json_bytes(policy))
    policy_path.chmod(0o600)
    return policy_path, allowed


def _host(tmp_path: Path):
    policy, allowed = _trust_files(tmp_path)
    return _test_controller_host(
        policy,
        allowed,
        controller_build_sha256=BUILD_SHA,
        browser_binary_sha256=BROWSER_SHA,
    )


def _preflight() -> PreflightObservation:
    return PreflightObservation(
        run_id=RUN_ID,
        novel_id=NOVEL_ID,
        document_id=DOCUMENT_ID,
        envelope_nonce="nonce-utf8-中文",
        envelope_fingerprint_sha256=_sha("envelope"),
        fixture_manifest_sha256=_sha("fixture"),
        issued_at=NOW - timedelta(minutes=31),
    )


def _captures() -> tuple[BrowserCaptureObservation, ...]:
    values = []
    for index, (width, height, mode) in enumerate(FIXED_REQUIRED_CAPTURES):
        values.append(
            BrowserCaptureObservation(
                calibration_attempts=(
                    CalibrationObservation(
                        requested_outer_width=width + 30,
                        requested_outer_height=height + 20,
                        observed_inner_width=width - 2,
                        observed_inner_height=height - 1,
                    ),
                    CalibrationObservation(
                        requested_outer_width=width + 32,
                        requested_outer_height=height + 21,
                        observed_inner_width=width,
                        observed_inner_height=height,
                    ),
                ),
                assistant_panel_expanded=mode == "expanded",
                device_pixel_ratio=1.25,
                screenshot_pixel_width=round(width * 1.25),
                screenshot_pixel_height=round(height * 1.25),
                screenshot_bytes=_png(
                    round(width * 1.25),
                    round(height * 1.25),
                    marker=index,
                ),
                console_summary_bytes=f"console-{index}".encode(),
                network_summary_bytes=f"network-{index}".encode(),
            )
        )
    return tuple(values)


def _png(width: int, height: int, *, marker: int) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    rows = (b"\x00" + (b"\x00" * width)) * height
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"tEXt", f"capture={marker}".encode("ascii"))
        + chunk(b"IDAT", zlib.compress(rows, level=9))
        + chunk(b"IEND", b"")
    )


def _samples() -> tuple[RuntimeMetricObservation, ...]:
    return tuple(
        RuntimeMetricObservation(
            observed_at=NOW - timedelta(minutes=30) + timedelta(minutes=index),
            sidecar_healthy=True,
            sidecar_restart_count=0,
            health_failure_count=0,
            active_synthesis_count=1 if index < 4 else 0,
            queued_job_count=max(0, 4 - index),
            resident_memory_bytes=100_000_000 + index,
        )
        for index in range(31)
    )


def _sign_preflight(tmp_path: Path, payload: bytes) -> bytes:
    completed = subprocess.run(
        [
            str(SSH_KEYGEN_PATH),
            "-Y",
            "sign",
            "-f",
            str(tmp_path / "controller"),
            "-n",
            PREFLIGHT_SIGNATURE_NAMESPACE,
        ],
        input=payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
        check=False,
        timeout=10,
    )
    assert completed.returncode == 0
    return completed.stdout


def _report(
    preflight_payload: bytes,
    preflight_signature: bytes,
) -> ReportBindingObservation:
    expectation = derive_preflight_expectation(
        run_id=RUN_ID,
        novel_id=NOVEL_ID,
        document_id=DOCUMENT_ID,
        envelope_nonce="nonce-utf8-中文",
        envelope_fingerprint_sha256=_sha("envelope"),
        fixture_manifest_sha256=_sha("fixture"),
    )
    return ReportBindingObservation(
        preflight_payload=preflight_payload,
        preflight_signature=preflight_signature,
        run_fingerprint_sha256=expectation.run_fingerprint_sha256,
        target_scope_sha256=expectation.target_scope_sha256,
        probe_request_bytes=b"probe request\n",
        request_fingerprint_sha256=_sha("request fingerprint"),
        automatic_edition_fingerprint_sha256=_sha("automatic edition"),
        manual_edition_fingerprint_sha256=_sha("manual edition"),
        listening_output_hashes=tuple(sorted((_sha("a"), _sha("b")))),
        collector_report_bytes=b"collector report\n",
        probe_report_bytes=b"probe report\n",
        signed_at=NOW,
        captures=_captures(),
        metric_samples=_samples(),
    )


def test_preflight_hash_derivation_is_byte_exact_and_not_colon_joined() -> None:
    derived = derive_preflight_expectation(
        run_id=RUN_ID,
        novel_id=NOVEL_ID,
        document_id=DOCUMENT_ID,
        envelope_nonce="nonce-utf8-中文",
        envelope_fingerprint_sha256=_sha("envelope"),
        fixture_manifest_sha256=_sha("fixture"),
    )

    assert derived.nonce_sha256 == hashlib.sha256(
        "nonce-utf8-中文".encode("utf-8")
    ).hexdigest()
    assert derived.run_fingerprint_sha256 == hashlib.sha256(
        RUN_ID.encode("utf-8")
    ).hexdigest()
    assert derived.target_scope_sha256 == hashlib.sha256(
        canonical_json_bytes(
            {"document_id": DOCUMENT_ID, "novel_id": NOVEL_ID}
        )
    ).hexdigest()
    assert derived.target_scope_sha256 != hashlib.sha256(
        f"{NOVEL_ID}:{DOCUMENT_ID}".encode()
    ).hexdigest()


def test_empty_production_trust_root_cannot_construct_formal_preflight() -> None:
    with pytest.raises(ControllerHostError) as captured:
        host_module._fixed_controller_host().build_preflight(_preflight())
    assert captured.value.code == CONTROLLER_TRUST_ROOT_HOLD_ERROR


def test_production_host_accepting_raw_observations_is_not_public() -> None:
    assert not hasattr(host_module, "FixedControllerHost")
    assert "FixedControllerHost" not in host_module.__all__


def test_host_constructs_only_frozen_preflight_and_report_dtos(
    tmp_path: Path,
) -> None:
    host = _host(tmp_path)
    preflight = host.build_preflight(_preflight())
    preflight_signature = _sign_preflight(tmp_path, preflight.payload)
    preflight_payload = json.loads(preflight.payload)
    assert preflight.signature_namespace == PREFLIGHT_SIGNATURE_NAMESPACE
    assert preflight_payload["required_captures"] == [
        {
            "assistant_mode": mode,
            "target_css_height": height,
            "target_css_width": width,
        }
        for width, height, mode in FIXED_REQUIRED_CAPTURES
    ]
    assert "status" not in preflight_payload
    assert "passed" not in preflight_payload

    report = host.build_report_binding(
        _report(preflight.payload, preflight_signature)
    )
    payload = json.loads(report.payload)
    assert report.signature_namespace == REPORT_SIGNATURE_NAMESPACE
    assert payload["metric_sample_count"] == 31
    assert payload["stability_elapsed_milliseconds"] == 1_800_000
    assert len(payload["observed_captures"]) == 4
    assert "status" not in payload
    assert "passed" not in payload
    assert all(
        row["observed_inner_width"] == row["target_css_width"]
        and row["observed_inner_height"] == row["target_css_height"]
        for row in payload["observed_captures"]
    )

    raw_metric_payloads = [sample.payload() for sample in _samples()]
    collector_samples = tuple(
        SidecarMetricSampleDigest(
            observed_at=sample.observed_at,
            sample_sha256=hashlib.sha256(
                canonical_json_bytes(raw_payload)
            ).hexdigest(),
        )
        for sample, raw_payload in zip(
            _samples(), raw_metric_payloads, strict=True
        )
    )
    assert payload["metric_sample_chain_sha256"] == (
        build_sidecar_metric_sample_chain_sha256(
            request_fingerprint_sha256=_sha("request fingerprint"),
            window_started_at=_samples()[0].observed_at,
            window_ended_at=_samples()[-1].observed_at,
            metrics_summary_sha256=build_metric_summary_sha256(
                raw_metric_payloads
            ),
            samples=collector_samples,
        )
    )


def test_report_builder_rejects_unsigned_or_tampered_preflight(
    tmp_path: Path,
) -> None:
    host = _host(tmp_path)
    preflight = host.build_preflight(_preflight())
    signature = _sign_preflight(tmp_path, preflight.payload)
    tampered = bytearray(signature)
    tampered[len(tampered) // 2] ^= 1

    with pytest.raises(ControllerHostError) as captured:
        host.build_report_binding(
            _report(preflight.payload, bytes(tampered))
        )

    assert captured.value.code == "CONTROLLER_BINDING_INVALID"


@pytest.mark.parametrize("mutation", ["inner", "assistant", "pixels"])
def test_host_rejects_requested_viewport_mode_or_screenshot_claims(
    tmp_path: Path,
    mutation: str,
) -> None:
    host = _host(tmp_path)
    preflight = host.build_preflight(_preflight())
    preflight_signature = _sign_preflight(tmp_path, preflight.payload)
    captures = list(_captures())
    first = captures[0]
    if mutation == "inner":
        attempts = list(first.calibration_attempts)
        attempts[-1] = replace(attempts[-1], observed_inner_width=1919)
        captures[0] = replace(first, calibration_attempts=tuple(attempts))
    elif mutation == "assistant":
        captures[0] = replace(first, assistant_panel_expanded=True)
    else:
        captures[0] = replace(first, screenshot_pixel_width=1919)

    with pytest.raises(ControllerHostError) as captured:
        host.build_report_binding(
            replace(
                _report(preflight.payload, preflight_signature),
                captures=tuple(captures),
            )
        )
    assert captured.value.code == CONTROLLER_CAPTURE_INVALID_ERROR


@pytest.mark.parametrize("mutation", ["short", "gap", "restart"])
def test_host_recomputes_and_rejects_invalid_thirty_minute_sample_chain(
    tmp_path: Path,
    mutation: str,
) -> None:
    host = _host(tmp_path)
    preflight = host.build_preflight(_preflight())
    preflight_signature = _sign_preflight(tmp_path, preflight.payload)
    samples = list(_samples())
    if mutation == "short":
        samples = samples[:30]
    elif mutation == "gap":
        samples[10] = replace(
            samples[10], observed_at=samples[9].observed_at + timedelta(seconds=66)
        )
    else:
        samples[10] = replace(samples[10], sidecar_restart_count=1)

    with pytest.raises(ControllerHostError) as captured:
        host.build_report_binding(
            replace(
                _report(preflight.payload, preflight_signature),
                metric_samples=tuple(samples),
            )
        )
    assert captured.value.code == CONTROLLER_STABILITY_INVALID_ERROR
