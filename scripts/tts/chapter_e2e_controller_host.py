#!/usr/bin/env python3
"""Fixed host-side constructor for T4-K controller SSHSIG payloads.

This module does not drive a browser and it never accepts a verdict.  The
approved browser port must return raw, read-only observations.  This boundary
then derives the four capture bindings and the thirty-minute metric chain
before constructing one of the two canonical DTOs frozen by AUTH-2.

The production port reads only the repository-packaged public trust policy.
With the intentionally empty production trust root it fails closed before it
can construct an artifact eligible for formal signing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import binascii
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import struct
from typing import Final, Mapping, Sequence
from uuid import UUID

from scripts.tts.chapter_e2e_controller_build import (
    ControllerBuildError,
    fixed_controller_build_sha256,
)

from scripts.tts.chapter_e2e_controller_trust import (
    ALLOWED_SIGNERS_PATH,
    CONTROLLER_ID,
    CONTROLLER_PREFLIGHT_SCHEMA_VERSION,
    CONTROLLER_REPORT_BINDING_SCHEMA_VERSION,
    CONTROLLER_TRUST_ROOT_HOLD_ERROR,
    FIXED_REQUIRED_CAPTURES,
    FIXED_REQUIRED_STABILITY_MILLISECONDS,
    PREFLIGHT_SIGNATURE_NAMESPACE,
    REPORT_SIGNATURE_NAMESPACE,
    TRUST_POLICY_PATH,
    ControllerTrustError,
    PreflightExpectation,
    ReportExpectation,
    _ControllerTrustVerifier,
    _decode_canonical_mapping,
    _load_policy_from_paths,
    canonical_json_bytes,
)
from scripts.tts.chapter_e2e_metric_chain import (
    build_metric_sample_chain_sha256,
    build_metric_summary_sha256,
)


CONTROLLER_OBSERVATION_INVALID_ERROR: Final = (
    "CONTROLLER_OBSERVATION_INVALID"
)
CONTROLLER_CAPTURE_INVALID_ERROR: Final = "CONTROLLER_CAPTURE_INVALID"
CONTROLLER_STABILITY_INVALID_ERROR: Final = "CONTROLLER_STABILITY_INVALID"
CONTROLLER_BINDING_INVALID_ERROR: Final = "CONTROLLER_BINDING_INVALID"
CONTROLLER_HOST_POLICY_INVALID_ERROR: Final = "CONTROLLER_HOST_POLICY_INVALID"

PREFLIGHT_LIFETIME_SECONDS: Final = 10 * 60
MAX_METRIC_SAMPLE_GAP_SECONDS: Final = 65
MIN_METRIC_SAMPLE_COUNT: Final = 31
MAX_SUMMARY_BYTES: Final = 1024 * 1024
MAX_SCREENSHOT_BYTES: Final = 32 * 1024 * 1024
_SHA256_CHARS: Final = frozenset("0123456789abcdef")
FIXED_BROWSER_BINARY_PATH: Final = Path(
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
)


class ControllerHostError(RuntimeError):
    """Fail-closed host-controller error exposing only a stable code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_fixed_executable(path: Path) -> str:
    try:
        details = path.lstat()
        if (
            not path.is_absolute()
            or stat.S_ISLNK(details.st_mode)
            or not stat.S_ISREG(details.st_mode)
            or not os.access(path, os.X_OK)
        ):
            raise OSError
        with path.open("rb") as handle:
            return hashlib.file_digest(handle, "sha256").hexdigest()
    except OSError:
        raise ControllerHostError(
            CONTROLLER_HOST_POLICY_INVALID_ERROR
        ) from None


def _is_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in _SHA256_CHARS for character in value)
    )


def _timestamp(value: datetime, *, code: str) -> str:
    if type(value) is not datetime or value.tzinfo is None:
        raise ControllerHostError(code)
    normalized = value.astimezone(timezone.utc)
    if normalized.microsecond != 0:
        raise ControllerHostError(code)
    return normalized.strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical_uuid(value: object, *, code: str) -> str:
    if type(value) is not str:
        raise ControllerHostError(code)
    try:
        canonical = str(UUID(value))
    except (ValueError, AttributeError):
        raise ControllerHostError(code) from None
    if value != canonical:
        raise ControllerHostError(code)
    return canonical


def _summary_bytes(value: object, *, code: str) -> bytes:
    if type(value) is not bytes or not 1 <= len(value) <= MAX_SUMMARY_BYTES:
        raise ControllerHostError(code)
    return value


def _screenshot_bytes(value: object, *, code: str) -> bytes:
    if type(value) is not bytes or not 33 <= len(value) <= MAX_SCREENSHOT_BYTES:
        raise ControllerHostError(code)
    return value


def _png_dimensions(value: bytes, *, code: str) -> tuple[int, int]:
    """Authenticate the PNG signature and mandatory first IHDR chunk."""

    if len(value) < 33 or value[:8] != b"\x89PNG\r\n\x1a\n":
        raise ControllerHostError(code)
    length = struct.unpack(">I", value[8:12])[0]
    chunk_type = value[12:16]
    if length != 13 or chunk_type != b"IHDR":
        raise ControllerHostError(code)
    payload = value[16:29]
    expected_crc = struct.unpack(">I", value[29:33])[0]
    if binascii.crc32(chunk_type + payload) & 0xFFFFFFFF != expected_crc:
        raise ControllerHostError(code)
    width, height = struct.unpack(">II", payload[:8])
    if width < 1 or height < 1:
        raise ControllerHostError(code)
    return width, height


def derive_preflight_expectation(
    *,
    run_id: str,
    novel_id: str,
    document_id: str,
    envelope_nonce: str,
    envelope_fingerprint_sha256: str,
    fixture_manifest_sha256: str,
) -> PreflightExpectation:
    """Derive the launcher-frozen preflight hashes without delimiter joins."""

    code = CONTROLLER_BINDING_INVALID_ERROR
    run = _canonical_uuid(run_id, code=code)
    novel = _canonical_uuid(novel_id, code=code)
    document = _canonical_uuid(document_id, code=code)
    if (
        type(envelope_nonce) is not str
        or not envelope_nonce
        or len(envelope_nonce.encode("utf-8")) > 4096
        or not _is_sha256(envelope_fingerprint_sha256)
        or not _is_sha256(fixture_manifest_sha256)
    ):
        raise ControllerHostError(code)
    scope = canonical_json_bytes(
        {"document_id": document, "novel_id": novel}
    )
    return PreflightExpectation(
        nonce_sha256=_sha256_bytes(envelope_nonce.encode("utf-8")),
        run_fingerprint_sha256=_sha256_bytes(run.encode("utf-8")),
        target_scope_sha256=_sha256_bytes(scope),
        operator_envelope_sha256=envelope_fingerprint_sha256,
        fixture_manifest_sha256=fixture_manifest_sha256,
    )


@dataclass(frozen=True, slots=True)
class PreflightObservation:
    run_id: str
    novel_id: str
    document_id: str
    envelope_nonce: str
    envelope_fingerprint_sha256: str
    fixture_manifest_sha256: str
    issued_at: datetime


@dataclass(frozen=True, slots=True)
class CalibrationObservation:
    requested_outer_width: int
    requested_outer_height: int
    observed_inner_width: int
    observed_inner_height: int

    def payload(self) -> dict[str, int]:
        return {
            "observed_inner_height": self.observed_inner_height,
            "observed_inner_width": self.observed_inner_width,
            "requested_outer_height": self.requested_outer_height,
            "requested_outer_width": self.requested_outer_width,
        }


@dataclass(frozen=True, slots=True)
class BrowserCaptureObservation:
    """Raw facts returned by the fixed read-only browser observation port."""

    calibration_attempts: tuple[CalibrationObservation, ...]
    assistant_panel_expanded: bool
    device_pixel_ratio: float
    screenshot_pixel_width: int
    screenshot_pixel_height: int
    screenshot_bytes: bytes
    console_summary_bytes: bytes
    network_summary_bytes: bytes


@dataclass(frozen=True, slots=True)
class RuntimeMetricObservation:
    """One raw, timestamped, read-only runtime metrics projection."""

    observed_at: datetime
    sidecar_healthy: bool
    sidecar_restart_count: int
    health_failure_count: int
    active_synthesis_count: int
    queued_job_count: int
    resident_memory_bytes: int

    def payload(self) -> dict[str, object]:
        code = CONTROLLER_STABILITY_INVALID_ERROR
        return {
            "active_synthesis_count": self.active_synthesis_count,
            "health_failure_count": self.health_failure_count,
            "observed_at": _timestamp(self.observed_at, code=code),
            "queued_job_count": self.queued_job_count,
            "resident_memory_bytes": self.resident_memory_bytes,
            "sidecar_healthy": self.sidecar_healthy,
            "sidecar_restart_count": self.sidecar_restart_count,
        }


@dataclass(frozen=True, slots=True)
class ReportBindingObservation:
    preflight_payload: bytes
    preflight_signature: bytes
    run_fingerprint_sha256: str
    target_scope_sha256: str
    probe_request_bytes: bytes
    request_fingerprint_sha256: str
    automatic_edition_fingerprint_sha256: str
    manual_edition_fingerprint_sha256: str
    listening_output_hashes: tuple[str, ...]
    collector_report_bytes: bytes
    probe_report_bytes: bytes
    signed_at: datetime
    captures: tuple[BrowserCaptureObservation, ...]
    metric_samples: tuple[RuntimeMetricObservation, ...]


@dataclass(frozen=True, slots=True)
class CanonicalControllerArtifact:
    schema_version: str
    signature_namespace: str
    payload: bytes


@dataclass(frozen=True, slots=True)
class _ControllerIdentity:
    key_id: str
    principal: str
    policy_sha256: str
    allowed_signers_sha256: str


class _ControllerHost:
    def __init__(
        self,
        *,
        policy_path: Path,
        allowed_signers_path: Path,
        controller_build_sha256: str,
        browser_binary_sha256: str,
    ) -> None:
        if (
            not isinstance(policy_path, Path)
            or not policy_path.is_absolute()
            or not isinstance(allowed_signers_path, Path)
            or not allowed_signers_path.is_absolute()
            or not _is_sha256(controller_build_sha256)
            or not _is_sha256(browser_binary_sha256)
        ):
            raise ControllerHostError(CONTROLLER_HOST_POLICY_INVALID_ERROR)
        self._policy_path = policy_path
        self._allowed_signers_path = allowed_signers_path
        self._controller_build_sha256 = controller_build_sha256
        self._browser_binary_sha256 = browser_binary_sha256
        self._verifier = _ControllerTrustVerifier(
            policy_path=policy_path,
            allowed_signers_path=allowed_signers_path,
        )

    def _identity(self, *, at: datetime) -> _ControllerIdentity:
        _timestamp(at, code=CONTROLLER_HOST_POLICY_INVALID_ERROR)
        try:
            policy, _raw = _load_policy_from_paths(
                self._policy_path,
                self._allowed_signers_path,
            )
        except ControllerTrustError as error:
            raise ControllerHostError(error.code) from None
        candidates = tuple(
            key
            for key in policy.keys
            if key.status == "active"
            and key.not_before <= at < key.not_after
            and self._controller_build_sha256
            in key.allowed_controller_build_sha256
            and self._browser_binary_sha256
            in key.allowed_browser_build_sha256
        )
        if len(candidates) != 1:
            raise ControllerHostError(CONTROLLER_TRUST_ROOT_HOLD_ERROR)
        key = candidates[0]
        return _ControllerIdentity(
            key_id=key.key_id,
            principal=key.principal,
            policy_sha256=policy.policy_sha256,
            allowed_signers_sha256=policy.allowed_signers_sha256,
        )

    def build_preflight(
        self,
        observation: PreflightObservation,
    ) -> CanonicalControllerArtifact:
        if type(observation) is not PreflightObservation:
            raise ControllerHostError(CONTROLLER_OBSERVATION_INVALID_ERROR)
        issued_at = observation.issued_at.astimezone(timezone.utc)
        issued_text = _timestamp(
            issued_at, code=CONTROLLER_OBSERVATION_INVALID_ERROR
        )
        identity = self._identity(at=issued_at)
        expectation = derive_preflight_expectation(
            run_id=observation.run_id,
            novel_id=observation.novel_id,
            document_id=observation.document_id,
            envelope_nonce=observation.envelope_nonce,
            envelope_fingerprint_sha256=(
                observation.envelope_fingerprint_sha256
            ),
            fixture_manifest_sha256=observation.fixture_manifest_sha256,
        )
        expires_at = issued_at + timedelta(seconds=PREFLIGHT_LIFETIME_SECONDS)
        payload: dict[str, object] = {
            "allowed_signers_sha256": identity.allowed_signers_sha256,
            "controller_build_sha256": self._controller_build_sha256,
            "controller_id": CONTROLLER_ID,
            "expires_at": _timestamp(
                expires_at, code=CONTROLLER_OBSERVATION_INVALID_ERROR
            ),
            "fixture_manifest_sha256": expectation.fixture_manifest_sha256,
            "issued_at": issued_text,
            "nonce_sha256": expectation.nonce_sha256,
            "operator_envelope_sha256": (
                expectation.operator_envelope_sha256
            ),
            "required_captures": [
                {
                    "assistant_mode": mode,
                    "target_css_height": height,
                    "target_css_width": width,
                }
                for width, height, mode in FIXED_REQUIRED_CAPTURES
            ],
            "required_stability_milliseconds": (
                FIXED_REQUIRED_STABILITY_MILLISECONDS
            ),
            "run_fingerprint_sha256": expectation.run_fingerprint_sha256,
            "schema_version": CONTROLLER_PREFLIGHT_SCHEMA_VERSION,
            "signature_namespace": PREFLIGHT_SIGNATURE_NAMESPACE,
            "signer_principal": identity.principal,
            "signing_key_id": identity.key_id,
            "target_scope_sha256": expectation.target_scope_sha256,
            "trust_policy_sha256": identity.policy_sha256,
        }
        return CanonicalControllerArtifact(
            schema_version=CONTROLLER_PREFLIGHT_SCHEMA_VERSION,
            signature_namespace=PREFLIGHT_SIGNATURE_NAMESPACE,
            payload=canonical_json_bytes(payload),
        )

    @staticmethod
    def _capture_payloads(
        captures: object,
    ) -> list[dict[str, object]]:
        code = CONTROLLER_CAPTURE_INVALID_ERROR
        if type(captures) is not tuple or len(captures) != len(
            FIXED_REQUIRED_CAPTURES
        ):
            raise ControllerHostError(code)
        result: list[dict[str, object]] = []
        screenshot_hashes: set[str] = set()
        for required, raw in zip(FIXED_REQUIRED_CAPTURES, captures, strict=True):
            if type(raw) is not BrowserCaptureObservation:
                raise ControllerHostError(code)
            width, height, expected_mode = required
            attempts = raw.calibration_attempts
            if (
                type(attempts) is not tuple
                or not 1 <= len(attempts) <= 8
                or any(type(item) is not CalibrationObservation for item in attempts)
                or type(raw.assistant_panel_expanded) is not bool
                or type(raw.device_pixel_ratio) not in {int, float}
                or not math.isfinite(float(raw.device_pixel_ratio))
                or not 0.1 <= float(raw.device_pixel_ratio) <= 8.0
                or type(raw.screenshot_pixel_width) is not int
                or type(raw.screenshot_pixel_height) is not int
            ):
                raise ControllerHostError(code)
            for attempt in attempts:
                if (
                    type(attempt.requested_outer_width) is not int
                    or type(attempt.requested_outer_height) is not int
                    or type(attempt.observed_inner_width) is not int
                    or type(attempt.observed_inner_height) is not int
                    or attempt.requested_outer_width < 1
                    or attempt.requested_outer_height < 1
                    or attempt.observed_inner_width < 1
                    or attempt.observed_inner_height < 1
                ):
                    raise ControllerHostError(code)
            final = attempts[-1]
            observed_mode = (
                "expanded" if raw.assistant_panel_expanded else "collapsed"
            )
            dpr_micros = round(float(raw.device_pixel_ratio) * 1_000_000)
            expected_pixel_width = round(width * dpr_micros / 1_000_000)
            expected_pixel_height = round(height * dpr_micros / 1_000_000)
            screenshot = _screenshot_bytes(raw.screenshot_bytes, code=code)
            decoded_pixel_width, decoded_pixel_height = _png_dimensions(
                screenshot,
                code=code,
            )
            screenshot_sha256 = _sha256_bytes(screenshot)
            if (
                final.observed_inner_width != width
                or final.observed_inner_height != height
                or observed_mode != expected_mode
                or raw.screenshot_pixel_width != expected_pixel_width
                or raw.screenshot_pixel_height != expected_pixel_height
                or decoded_pixel_width != raw.screenshot_pixel_width
                or decoded_pixel_height != raw.screenshot_pixel_height
                or screenshot_sha256 in screenshot_hashes
            ):
                raise ControllerHostError(code)
            screenshot_hashes.add(screenshot_sha256)
            calibration_bytes = canonical_json_bytes(
                [attempt.payload() for attempt in attempts]
            )
            result.append(
                {
                    "assistant_mode_observed": observed_mode,
                    "assistant_mode_requested": expected_mode,
                    "calibration_attempt_count": len(attempts),
                    "calibration_summary_sha256": _sha256_bytes(
                        calibration_bytes
                    ),
                    "console_summary_sha256": _sha256_bytes(
                        _summary_bytes(raw.console_summary_bytes, code=code)
                    ),
                    "device_pixel_ratio_micros": dpr_micros,
                    "network_summary_sha256": _sha256_bytes(
                        _summary_bytes(raw.network_summary_bytes, code=code)
                    ),
                    "observed_inner_height": final.observed_inner_height,
                    "observed_inner_width": final.observed_inner_width,
                    "requested_outer_height": final.requested_outer_height,
                    "requested_outer_width": final.requested_outer_width,
                    "screenshot_pixel_height": raw.screenshot_pixel_height,
                    "screenshot_pixel_width": raw.screenshot_pixel_width,
                    "screenshot_sha256": screenshot_sha256,
                    "target_css_height": height,
                    "target_css_width": width,
                }
            )
        return result

    @staticmethod
    def _metric_window(
        samples: object,
        *,
        request_fingerprint_sha256: str,
    ) -> tuple[str, str, int, int, str]:
        code = CONTROLLER_STABILITY_INVALID_ERROR
        if (
            type(samples) is not tuple
            or len(samples) < MIN_METRIC_SAMPLE_COUNT
            or not _is_sha256(request_fingerprint_sha256)
        ):
            raise ControllerHostError(code)
        payloads: list[dict[str, object]] = []
        previous: datetime | None = None
        for sample in samples:
            if type(sample) is not RuntimeMetricObservation:
                raise ControllerHostError(code)
            payload = sample.payload()
            observed = sample.observed_at.astimezone(timezone.utc)
            integer_values = (
                sample.sidecar_restart_count,
                sample.health_failure_count,
                sample.active_synthesis_count,
                sample.queued_job_count,
                sample.resident_memory_bytes,
            )
            if (
                sample.sidecar_healthy is not True
                or any(type(value) is not int or value < 0 for value in integer_values)
                or sample.sidecar_restart_count != 0
                or sample.health_failure_count != 0
                or (previous is not None and observed <= previous)
                or (
                    previous is not None
                    and (observed - previous).total_seconds()
                    > MAX_METRIC_SAMPLE_GAP_SECONDS
                )
            ):
                raise ControllerHostError(code)
            payloads.append(payload)
            previous = observed
        started = samples[0].observed_at.astimezone(timezone.utc)
        ended = samples[-1].observed_at.astimezone(timezone.utc)
        elapsed_ms = int((ended - started).total_seconds() * 1000)
        if elapsed_ms < FIXED_REQUIRED_STABILITY_MILLISECONDS:
            raise ControllerHostError(code)
        started_text = _timestamp(started, code=code)
        ended_text = _timestamp(ended, code=code)
        sample_digests = [
            {
                "index": index,
                "observed_at": str(payload["observed_at"]),
                "sample_sha256": _sha256_bytes(canonical_json_bytes(payload)),
            }
            for index, payload in enumerate(payloads)
        ]
        chain = build_metric_sample_chain_sha256(
            request_fingerprint_sha256=request_fingerprint_sha256,
            window_started_at=started_text,
            window_ended_at=ended_text,
            metrics_summary_sha256=build_metric_summary_sha256(payloads),
            samples=sample_digests,
        )
        return (
            started_text,
            ended_text,
            elapsed_ms,
            len(payloads),
            chain,
        )

    def build_report_binding(
        self,
        observation: ReportBindingObservation,
    ) -> CanonicalControllerArtifact:
        code = CONTROLLER_BINDING_INVALID_ERROR
        if type(observation) is not ReportBindingObservation:
            raise ControllerHostError(CONTROLLER_OBSERVATION_INVALID_ERROR)
        signed_at = observation.signed_at.astimezone(timezone.utc)
        signed_text = _timestamp(signed_at, code=code)
        identity = self._identity(at=signed_at)
        byte_values = (
            observation.preflight_payload,
            observation.preflight_signature,
            observation.probe_request_bytes,
            observation.collector_report_bytes,
            observation.probe_report_bytes,
        )
        if any(type(value) is not bytes or not value for value in byte_values):
            raise ControllerHostError(code)
        hash_values = (
            observation.run_fingerprint_sha256,
            observation.target_scope_sha256,
            observation.request_fingerprint_sha256,
            observation.automatic_edition_fingerprint_sha256,
            observation.manual_edition_fingerprint_sha256,
        )
        if (
            any(not _is_sha256(value) for value in hash_values)
            or type(observation.listening_output_hashes) is not tuple
            or not observation.listening_output_hashes
            or any(
                not _is_sha256(value)
                for value in observation.listening_output_hashes
            )
            or observation.listening_output_hashes
            != tuple(sorted(set(observation.listening_output_hashes)))
        ):
            raise ControllerHostError(code)
        try:
            preflight = _decode_canonical_mapping(
                observation.preflight_payload,
                max_bytes=32 * 1024,
                code=code,
            )
        except ControllerTrustError:
            raise ControllerHostError(code) from None
        if (
            preflight.get("schema_version")
            != CONTROLLER_PREFLIGHT_SCHEMA_VERSION
            or preflight.get("run_fingerprint_sha256")
            != observation.run_fingerprint_sha256
            or preflight.get("target_scope_sha256")
            != observation.target_scope_sha256
            or preflight.get("controller_build_sha256")
            != self._controller_build_sha256
            or preflight.get("signing_key_id") != identity.key_id
            or preflight.get("signer_principal") != identity.principal
            or preflight.get("trust_policy_sha256") != identity.policy_sha256
            or preflight.get("allowed_signers_sha256")
            != identity.allowed_signers_sha256
        ):
            raise ControllerHostError(code)
        try:
            issued_at = datetime.strptime(
                str(preflight.get("issued_at")),
                "%Y-%m-%dT%H:%M:%SZ",
            ).replace(tzinfo=timezone.utc)
            preflight_expectation = PreflightExpectation(
                nonce_sha256=str(preflight["nonce_sha256"]),
                run_fingerprint_sha256=(
                    observation.run_fingerprint_sha256
                ),
                target_scope_sha256=observation.target_scope_sha256,
                operator_envelope_sha256=str(
                    preflight["operator_envelope_sha256"]
                ),
                fixture_manifest_sha256=str(
                    preflight["fixture_manifest_sha256"]
                ),
            )
            self._verifier.verify_preflight(
                observation.preflight_payload,
                observation.preflight_signature,
                expectation=preflight_expectation,
                now=issued_at,
            )
        except (KeyError, ValueError, ControllerTrustError):
            raise ControllerHostError(code) from None
        captures = self._capture_payloads(observation.captures)
        started, ended, elapsed, sample_count, sample_chain = (
            self._metric_window(
                observation.metric_samples,
                request_fingerprint_sha256=(
                    observation.request_fingerprint_sha256
                ),
            )
        )
        if (
            observation.metric_samples[0].observed_at < issued_at
            or observation.metric_samples[-1].observed_at > signed_at
        ):
            raise ControllerHostError(code)
        expectation = ReportExpectation(
            preflight_payload_sha256=_sha256_bytes(
                observation.preflight_payload
            ),
            run_fingerprint_sha256=observation.run_fingerprint_sha256,
            target_scope_sha256=observation.target_scope_sha256,
            probe_request_sha256=_sha256_bytes(
                observation.probe_request_bytes
            ),
            request_fingerprint_sha256=(
                observation.request_fingerprint_sha256
            ),
            automatic_edition_fingerprint_sha256=(
                observation.automatic_edition_fingerprint_sha256
            ),
            manual_edition_fingerprint_sha256=(
                observation.manual_edition_fingerprint_sha256
            ),
            listening_output_hashes=observation.listening_output_hashes,
            collector_report_sha256=_sha256_bytes(
                observation.collector_report_bytes
            ),
            probe_report_sha256=_sha256_bytes(observation.probe_report_bytes),
        )
        payload: dict[str, object] = {
            "allowed_signers_sha256": identity.allowed_signers_sha256,
            "automatic_edition_fingerprint_sha256": (
                expectation.automatic_edition_fingerprint_sha256
            ),
            "browser_binary_sha256": self._browser_binary_sha256,
            "collector_report_sha256": expectation.collector_report_sha256,
            "controller_build_sha256": self._controller_build_sha256,
            "controller_id": CONTROLLER_ID,
            "listening_output_hashes": list(
                expectation.listening_output_hashes
            ),
            "manual_edition_fingerprint_sha256": (
                expectation.manual_edition_fingerprint_sha256
            ),
            "metric_sample_chain_sha256": sample_chain,
            "metric_sample_count": sample_count,
            "observed_captures": captures,
            "preflight_payload_sha256": expectation.preflight_payload_sha256,
            "probe_report_sha256": expectation.probe_report_sha256,
            "probe_request_sha256": expectation.probe_request_sha256,
            "request_fingerprint_sha256": (
                expectation.request_fingerprint_sha256
            ),
            "required_stability_milliseconds": (
                FIXED_REQUIRED_STABILITY_MILLISECONDS
            ),
            "run_fingerprint_sha256": expectation.run_fingerprint_sha256,
            "schema_version": CONTROLLER_REPORT_BINDING_SCHEMA_VERSION,
            "signature_namespace": REPORT_SIGNATURE_NAMESPACE,
            "signed_at": signed_text,
            "signer_principal": identity.principal,
            "signing_key_id": identity.key_id,
            "stability_elapsed_milliseconds": elapsed,
            "target_scope_sha256": expectation.target_scope_sha256,
            "trust_policy_sha256": identity.policy_sha256,
            "window_ended_at": ended,
            "window_started_at": started,
        }
        return CanonicalControllerArtifact(
            schema_version=CONTROLLER_REPORT_BINDING_SCHEMA_VERSION,
            signature_namespace=REPORT_SIGNATURE_NAMESPACE,
            payload=canonical_json_bytes(payload),
        )


def _fixed_controller_host() -> _ControllerHost:
    """Build the internal host used only by the fixed controller lifecycle.

    This is deliberately not a public production API: ordinary callers must
    not receive a production-policy host that accepts caller-constructed
    browser or runtime observations.
    """

    try:
        controller_hash = fixed_controller_build_sha256()
        browser_hash = _sha256_fixed_executable(FIXED_BROWSER_BINARY_PATH)
    except ControllerBuildError:
        raise ControllerHostError(CONTROLLER_HOST_POLICY_INVALID_ERROR) from None
    return _ControllerHost(
        policy_path=TRUST_POLICY_PATH,
        allowed_signers_path=ALLOWED_SIGNERS_PATH,
        controller_build_sha256=controller_hash,
        browser_binary_sha256=browser_hash,
    )


def _test_controller_host(
    policy_path: Path,
    allowed_signers_path: Path,
    *,
    controller_build_sha256: str,
    browser_binary_sha256: str,
) -> _ControllerHost:
    """Test-only seam; production callers cannot select trust or binaries."""

    return _ControllerHost(
        policy_path=policy_path,
        allowed_signers_path=allowed_signers_path,
        controller_build_sha256=controller_build_sha256,
        browser_binary_sha256=browser_binary_sha256,
    )


__all__ = [
    "BrowserCaptureObservation",
    "CalibrationObservation",
    "CanonicalControllerArtifact",
    "CONTROLLER_BINDING_INVALID_ERROR",
    "CONTROLLER_CAPTURE_INVALID_ERROR",
    "CONTROLLER_HOST_POLICY_INVALID_ERROR",
    "CONTROLLER_OBSERVATION_INVALID_ERROR",
    "CONTROLLER_STABILITY_INVALID_ERROR",
    "ControllerHostError",
    "PreflightObservation",
    "ReportBindingObservation",
    "RuntimeMetricObservation",
    "derive_preflight_expectation",
]
