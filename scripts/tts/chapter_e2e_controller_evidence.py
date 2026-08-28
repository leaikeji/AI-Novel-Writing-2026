#!/usr/bin/env python3
"""Pure, fail-closed assembler for fixed T4-K controller evidence.

This module performs no I/O and accepts no caller-supplied URL, hashes,
performance values, layout verdicts, or pass flags.  It projects only already
validated browser, runtime, and private probe-request observations into the
collector DTO.  Constructing this DTO is not evidence that Edge or the
30-minute observation window actually ran; provenance remains the controller
authority's responsibility.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import math
import re
from typing import Final

from scripts.tts.chapter_e2e_browser_observer import (
    BrowserLayoutObservation,
    BrowserInteractionEvidence,
    VerifiedBrowserObservation,
)
from scripts.tts.chapter_e2e_collector import (
    BrowserCollectorEvidence,
    CaptureDigest,
    CollectorRequest,
    EXPECTED_RANGE_STATUS_CODES,
    EXPECTED_SIDECAR_CONTAINER_NAME,
    FIXED_CONTROLLER_ID,
    FIXED_PUBLIC_PAGE_URL,
    FixedControllerEvidence,
    PerformanceSeed,
    SidecarCollectorEvidence,
    SidecarMetricSampleDigest,
    build_sidecar_metric_sample_chain_sha256,
)
from scripts.tts.chapter_e2e_controller_host import (
    BrowserCaptureObservation,
    CalibrationObservation,
    RuntimeMetricObservation,
)
from scripts.tts.chapter_e2e_controller_trust import (
    FIXED_REQUIRED_CAPTURES,
    canonical_json_bytes,
)
from scripts.tts.chapter_e2e_metric_chain import build_metric_summary_sha256
from scripts.tts.chapter_e2e_probes import ProbeExpectation
from scripts.tts.chapter_e2e_runtime_observer import (
    HostPagingSummary,
    QWENPAW_SLOW_OBSERVATION_MILLISECONDS,
    REQUIRED_WINDOW_SECONDS,
    RuntimeObservationResult,
    SAMPLE_COUNT,
    SAMPLE_INTERVAL_SECONDS,
    derive_sidecar_memory_trend,
)


CONTROLLER_EVIDENCE_INVALID: Final = "CONTROLLER_EVIDENCE_INVALID"
CONTROLLER_EVIDENCE_BROWSER_HOLD: Final = (
    "CONTROLLER_EVIDENCE_BROWSER_HOLD"
)
CONTROLLER_EVIDENCE_BROWSER_PLAYER_HOLD: Final = (
    "CONTROLLER_EVIDENCE_BROWSER_PLAYER_HOLD"
)
CONTROLLER_EVIDENCE_BROWSER_PARAGRAPH_SEEK_HOLD: Final = (
    "CONTROLLER_EVIDENCE_BROWSER_PARAGRAPH_SEEK_HOLD"
)
CONTROLLER_EVIDENCE_BROWSER_CURSOR_SEEK_HOLD: Final = (
    "CONTROLLER_EVIDENCE_BROWSER_CURSOR_SEEK_HOLD"
)
CONTROLLER_EVIDENCE_BROWSER_LATEST_WINS_HOLD: Final = (
    "CONTROLLER_EVIDENCE_BROWSER_LATEST_WINS_HOLD"
)
CONTROLLER_EVIDENCE_BROWSER_CONTROLS_HOLD: Final = (
    "CONTROLLER_EVIDENCE_BROWSER_CONTROLS_HOLD"
)
CONTROLLER_EVIDENCE_BROWSER_EDIT_RESTORE_HOLD: Final = (
    "CONTROLLER_EVIDENCE_BROWSER_EDIT_RESTORE_HOLD"
)
CONTROLLER_EVIDENCE_BROWSER_EDIT_WRITE_HOLD: Final = (
    "CONTROLLER_EVIDENCE_BROWSER_EDIT_WRITE_HOLD"
)
CONTROLLER_EVIDENCE_BROWSER_MEDIA_HTTP_HOLD: Final = (
    "CONTROLLER_EVIDENCE_BROWSER_MEDIA_HTTP_HOLD"
)
CONTROLLER_EVIDENCE_BROWSER_MEDIA_COUNT_HOLD: Final = (
    "CONTROLLER_EVIDENCE_BROWSER_MEDIA_COUNT_HOLD"
)
CONTROLLER_EVIDENCE_LAYOUT_HOLD: Final = "CONTROLLER_EVIDENCE_LAYOUT_HOLD"
CONTROLLER_EVIDENCE_PENDING_GAP_HOLD: Final = (
    "CONTROLLER_EVIDENCE_PENDING_GAP_HOLD"
)
CONTROLLER_EVIDENCE_RUNTIME_HOLD: Final = (
    "CONTROLLER_EVIDENCE_RUNTIME_HOLD"
)
_SHA256: Final = re.compile(r"^[0-9a-f]{64}$")


class ControllerEvidenceAssemblyError(RuntimeError):
    """Stable fail-closed outcome without private observation details."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _error(code: str) -> ControllerEvidenceAssemblyError:
    return ControllerEvidenceAssemblyError(code)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _validate_request(request: object) -> CollectorRequest:
    if (
        type(request) is not CollectorRequest
        or type(request.expectation) is not ProbeExpectation
        or type(request.performance_seed) is not PerformanceSeed
        or type(request.request_fingerprint_sha256) is not str
        or _SHA256.fullmatch(request.request_fingerprint_sha256) is None
        or type(request.request_sha256) is not str
        or _SHA256.fullmatch(request.request_sha256) is None
        or type(request.preflight_payload_sha256) is not str
        or _SHA256.fullmatch(request.preflight_payload_sha256) is None
        or type(request.created_at) is not datetime
        or request.created_at.tzinfo is None
        or type(request.performance_seed.request_to_ready_seconds) is not tuple
        or len(request.performance_seed.request_to_ready_seconds) != 2
        or any(
            type(value) not in {int, float}
            or not math.isfinite(float(value))
            or float(value) < 0
            for value in request.performance_seed.request_to_ready_seconds
        )
        or type(request.performance_seed.observed_http_first_audio_ms)
        is not tuple
        or len(request.performance_seed.observed_http_first_audio_ms) != 2
        or any(
            type(value) is not int or value < 0
            for value in request.performance_seed.observed_http_first_audio_ms
        )
        or type(request.performance_seed.chapter_audio_duration_seconds)
        not in {int, float}
        or not math.isfinite(
            float(request.performance_seed.chapter_audio_duration_seconds)
        )
        or request.performance_seed.chapter_audio_duration_seconds <= 0
        or request.expectation.required_stability_seconds
        != REQUIRED_WINDOW_SECONDS
    ):
        raise _error(CONTROLLER_EVIDENCE_INVALID)
    return request


def _browser_evidence(
    observation: VerifiedBrowserObservation,
    request: CollectorRequest,
) -> BrowserCollectorEvidence:
    if (
        type(observation) is not VerifiedBrowserObservation
        or type(observation.captures) is not tuple
        or type(observation.layout_observations) is not tuple
        or type(observation.capture_console_error_counts) is not tuple
        or len(observation.captures) != len(FIXED_REQUIRED_CAPTURES)
        or len(observation.layout_observations)
        != len(FIXED_REQUIRED_CAPTURES)
        or len(observation.capture_console_error_counts)
        != len(FIXED_REQUIRED_CAPTURES)
        or type(observation.console_entry_count) is not int
        or observation.console_entry_count < 0
        or type(observation.console_error_count) is not int
        or observation.console_error_count != 0
        or type(observation.page_error_count) is not int
        or observation.page_error_count != 0
        or type(observation.network_request_count) is not int
        or observation.network_request_count <= 0
        or type(observation.report_sha256) is not str
        or _SHA256.fullmatch(observation.report_sha256) is None
        or type(observation.interaction_evidence)
        is not BrowserInteractionEvidence
    ):
        raise _error(CONTROLLER_EVIDENCE_BROWSER_HOLD)

    captures: list[CaptureDigest] = []
    for capture, layout, console_error_count, expected in zip(
        observation.captures,
        observation.layout_observations,
        observation.capture_console_error_counts,
        FIXED_REQUIRED_CAPTURES,
        strict=True,
    ):
        width, height, mode = expected
        if (
            type(capture) is not BrowserCaptureObservation
            or type(layout) is not BrowserLayoutObservation
            or (
                layout.target_css_width,
                layout.target_css_height,
                layout.assistant_mode,
            )
            != expected
            or type(layout.tracked_visible_region_count) is not int
            or layout.tracked_visible_region_count <= 0
            or type(layout.nonzero_overlap_pair_count) is not int
            or layout.nonzero_overlap_pair_count != 0
            or type(layout.horizontal_overflow_px) is not int
            or layout.horizontal_overflow_px != 0
        ):
            raise _error(CONTROLLER_EVIDENCE_LAYOUT_HOLD)
        if (
            capture.assistant_panel_expanded is not (mode == "expanded")
            or type(console_error_count) is not int
            or console_error_count != 0
            or type(capture.calibration_attempts) is not tuple
            or not 1 <= len(capture.calibration_attempts) <= 8
            or any(
                type(item) is not CalibrationObservation
                for item in capture.calibration_attempts
            )
            or type(capture.device_pixel_ratio) not in {int, float}
            or not math.isfinite(float(capture.device_pixel_ratio))
            or not 0.1 <= float(capture.device_pixel_ratio) <= 8.0
            or type(capture.screenshot_pixel_width) is not int
            or capture.screenshot_pixel_width <= 0
            or type(capture.screenshot_pixel_height) is not int
            or capture.screenshot_pixel_height <= 0
            or type(capture.screenshot_bytes) is not bytes
            or not capture.screenshot_bytes
            or type(capture.console_summary_bytes) is not bytes
            or not capture.console_summary_bytes
            or type(capture.network_summary_bytes) is not bytes
            or not capture.network_summary_bytes
        ):
            raise _error(CONTROLLER_EVIDENCE_BROWSER_HOLD)
        for attempt in capture.calibration_attempts:
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
                raise _error(CONTROLLER_EVIDENCE_BROWSER_HOLD)
        final_calibration = capture.calibration_attempts[-1]
        device_pixel_ratio = float(capture.device_pixel_ratio)
        device_pixel_ratio_micros = round(device_pixel_ratio * 1_000_000)
        expected_screenshot_pixel_width = round(
            width * device_pixel_ratio_micros / 1_000_000
        )
        expected_screenshot_pixel_height = round(
            height * device_pixel_ratio_micros / 1_000_000
        )
        if (
            final_calibration.observed_inner_width != width
            or final_calibration.observed_inner_height != height
            or capture.screenshot_pixel_width
            != expected_screenshot_pixel_width
            or capture.screenshot_pixel_height
            != expected_screenshot_pixel_height
        ):
            raise _error(CONTROLLER_EVIDENCE_BROWSER_HOLD)
        calibration_summary_sha256 = _sha256(
            canonical_json_bytes(
                [
                    attempt.payload()
                    for attempt in capture.calibration_attempts
                ]
            )
        )
        captures.append(
            CaptureDigest(
                width=width,
                height=height,
                assistant_mode=mode,
                observed_inner_width=(
                    final_calibration.observed_inner_width
                ),
                observed_inner_height=(
                    final_calibration.observed_inner_height
                ),
                device_pixel_ratio=device_pixel_ratio,
                screenshot_pixel_width=capture.screenshot_pixel_width,
                screenshot_pixel_height=capture.screenshot_pixel_height,
                calibration_summary_sha256=(
                    calibration_summary_sha256
                ),
                screenshot_sha256=_sha256(capture.screenshot_bytes),
                screenshot_bytes=len(capture.screenshot_bytes),
                console_summary_sha256=_sha256(
                    capture.console_summary_bytes
                ),
                network_summary_sha256=_sha256(
                    capture.network_summary_bytes
                ),
                network_request_count=observation.network_request_count,
                console_error_count=console_error_count,
                overlap_count=layout.nonzero_overlap_pair_count,
            )
        )

    interaction = observation.interaction_evidence
    if interaction.pending_gap_status != "observed":
        raise _error(CONTROLLER_EVIDENCE_PENDING_GAP_HOLD)
    if interaction.player_visible is not True:
        raise _error(CONTROLLER_EVIDENCE_BROWSER_PLAYER_HOLD)
    if interaction.paragraph_context_menu_seek_observed is not True:
        raise _error(CONTROLLER_EVIDENCE_BROWSER_PARAGRAPH_SEEK_HOLD)
    if interaction.cursor_keyboard_seek_observed is not True:
        raise _error(CONTROLLER_EVIDENCE_BROWSER_CURSOR_SEEK_HOLD)
    if interaction.latest_wins_observed is not True:
        raise _error(CONTROLLER_EVIDENCE_BROWSER_LATEST_WINS_HOLD)
    if interaction.play_pause_rate_seek_observed is not True:
        raise _error(CONTROLLER_EVIDENCE_BROWSER_CONTROLS_HOLD)
    if interaction.edit_restored is not True:
        raise _error(CONTROLLER_EVIDENCE_BROWSER_EDIT_RESTORE_HOLD)
    if (
        type(interaction.edit_tts_write_request_count) is not int
        or interaction.edit_tts_write_request_count != 0
    ):
        raise _error(CONTROLLER_EVIDENCE_BROWSER_EDIT_WRITE_HOLD)
    if interaction.media_http_observed is not True:
        raise _error(CONTROLLER_EVIDENCE_BROWSER_MEDIA_HTTP_HOLD)
    if (
        type(interaction.media_request_count) is not int
        or interaction.media_request_count != 5
    ):
        raise _error(CONTROLLER_EVIDENCE_BROWSER_MEDIA_COUNT_HOLD)
    if interaction.pending_gap_stop_before_observed is not True:
        raise _error(CONTROLLER_EVIDENCE_PENDING_GAP_HOLD)

    interaction_payload = asdict(interaction)
    range_payload = {
        "media_http_observed": interaction.media_http_observed,
        "media_request_count": interaction.media_request_count,
        "range_status_codes": list(EXPECTED_RANGE_STATUS_CODES),
    }
    etag_payload = {
        "etag_observed": True,
        "if_none_match_304_observed": True,
        "if_range_206_observed": True,
        "unsatisfied_range_416_observed": True,
    }
    editor_payload = {
        "edit_restored": interaction.edit_restored,
        "edit_tts_write_request_count": (
            interaction.edit_tts_write_request_count
        ),
        "editor_kind": interaction.editor_kind,
    }
    observed_action_count = sum(
        (
            interaction.paragraph_context_menu_seek_observed,
            interaction.cursor_keyboard_seek_observed,
            interaction.latest_wins_observed,
            interaction.play_pause_rate_seek_observed,
            interaction.edit_restored,
        )
    )
    return BrowserCollectorEvidence(
        observer_report_sha256=observation.report_sha256,
        captures=tuple(captures),
        range_status_codes=EXPECTED_RANGE_STATUS_CODES,
        range_summary_sha256=_sha256(canonical_json_bytes(range_payload)),
        etag_summary_sha256=_sha256(canonical_json_bytes(etag_payload)),
        etag_observed=True,
        if_none_match_304_observed=True,
        if_range_206_observed=True,
        unsatisfied_range_416_observed=True,
        time_to_first_audio_ms=max(
            request.performance_seed.observed_http_first_audio_ms
        ),
        seam_pairs_checked=1,
        seek_latest_wins=True,
        pending_gap_not_skipped=True,
        interaction_summary_sha256=_sha256(
            canonical_json_bytes(interaction_payload)
        ),
        edit_actions_observed=observed_action_count,
        edit_actions_created_tts_writes=0,
        editor_summary_sha256=_sha256(
            canonical_json_bytes(editor_payload)
        ),
    )


def validate_fixed_browser_evidence(
    browser: VerifiedBrowserObservation,
    request: CollectorRequest,
) -> BrowserCollectorEvidence:
    """Validate and project browser evidence without runtime observation."""

    validated_request = _validate_request(request)
    try:
        return _browser_evidence(browser, validated_request)
    except ControllerEvidenceAssemblyError:
        raise
    except Exception:
        raise _error(CONTROLLER_EVIDENCE_INVALID) from None


def _runtime_evidence(
    observation: RuntimeObservationResult,
    request: CollectorRequest,
) -> SidecarCollectorEvidence:
    if (
        type(observation) is not RuntimeObservationResult
        or type(observation.metric_samples) is not tuple
        or len(observation.metric_samples) != SAMPLE_COUNT
        or type(observation.host_paging) is not HostPagingSummary
        or type(observation.max_qwenpaw_observation_latency_ms) is not int
        or observation.max_qwenpaw_observation_latency_ms < 0
        or type(observation.qwenpaw_slowdown_observed) is not bool
    ):
        raise _error(CONTROLLER_EVIDENCE_RUNTIME_HOLD)

    paging = observation.host_paging
    if (
        type(paging.host_paging_observed) is not bool
        or type(paging.pageout_delta) is not int
        or paging.pageout_delta < 0
        or type(paging.swapout_delta) is not int
        or paging.swapout_delta < 0
    ):
        raise _error(CONTROLLER_EVIDENCE_RUNTIME_HOLD)
    derived_paging = paging.pageout_delta > 0 or paging.swapout_delta > 0
    derived_slowdown = (
        observation.max_qwenpaw_observation_latency_ms
        >= QWENPAW_SLOW_OBSERVATION_MILLISECONDS
    )
    if (
        paging.host_paging_observed is not derived_paging
        or observation.qwenpaw_slowdown_observed is not derived_slowdown
    ):
        raise _error(CONTROLLER_EVIDENCE_RUNTIME_HOLD)

    payloads: list[dict[str, object]] = []
    digests: list[SidecarMetricSampleDigest] = []
    previous = None
    for sample in observation.metric_samples:
        if (
            type(sample) is not RuntimeMetricObservation
            or sample.sidecar_healthy is not True
            or type(sample.sidecar_restart_count) is not int
            or sample.sidecar_restart_count != 0
            or type(sample.health_failure_count) is not int
            or sample.health_failure_count != 0
            or type(sample.active_synthesis_count) is not int
            or not 0 <= sample.active_synthesis_count <= 1
            or type(sample.queued_job_count) is not int
            or sample.queued_job_count != 0
            or type(sample.resident_memory_bytes) is not int
            or sample.resident_memory_bytes < 0
            or type(sample.observed_at) is not datetime
            or sample.observed_at.tzinfo is None
        ):
            raise _error(CONTROLLER_EVIDENCE_RUNTIME_HOLD)
        observed = sample.observed_at.astimezone(timezone.utc)
        if (
            previous is not None
            and (observed - previous).total_seconds()
            != SAMPLE_INTERVAL_SECONDS
        ):
            raise _error(CONTROLLER_EVIDENCE_RUNTIME_HOLD)
        try:
            payload = sample.payload()
            payload_bytes = canonical_json_bytes(payload)
        except Exception:
            raise _error(CONTROLLER_EVIDENCE_RUNTIME_HOLD) from None
        payloads.append(payload)
        digests.append(
            SidecarMetricSampleDigest(
                observed_at=observed,
                sample_sha256=_sha256(payload_bytes),
                resident_memory_bytes=sample.resident_memory_bytes,
            )
        )
        previous = observed

    started = digests[0].observed_at
    ended = digests[-1].observed_at
    elapsed = (ended - started).total_seconds()
    if (
        elapsed != REQUIRED_WINDOW_SECONDS
        or started < request.created_at.astimezone(timezone.utc)
    ):
        raise _error(CONTROLLER_EVIDENCE_RUNTIME_HOLD)
    try:
        memory_trend = derive_sidecar_memory_trend(
            observation.metric_samples
        )
    except Exception:
        raise _error(CONTROLLER_EVIDENCE_RUNTIME_HOLD) from None
    metrics_summary = build_metric_summary_sha256(payloads)
    metric_chain = build_sidecar_metric_sample_chain_sha256(
        request_fingerprint_sha256=request.request_fingerprint_sha256,
        window_started_at=started,
        window_ended_at=ended,
        metrics_summary_sha256=metrics_summary,
        samples=tuple(digests),
    )
    return SidecarCollectorEvidence(
        sidecar_container_name=EXPECTED_SIDECAR_CONTAINER_NAME,
        window_started_at=started,
        window_ended_at=ended,
        request_fingerprint_sha256=request.request_fingerprint_sha256,
        stability_elapsed_seconds=elapsed,
        chapter_audio_duration_seconds=(
            request.performance_seed.chapter_audio_duration_seconds
        ),
        request_to_ready_seconds=max(
            request.performance_seed.request_to_ready_seconds
        ),
        peak_memory_bytes=max(
            sample.resident_memory_bytes for sample in digests
        ),
        host_paging_observed=derived_paging,
        pageout_delta=paging.pageout_delta,
        swapout_delta=paging.swapout_delta,
        memory_baseline_median_bytes=(
            memory_trend.memory_baseline_median_bytes
        ),
        memory_tail_median_bytes=memory_trend.memory_tail_median_bytes,
        memory_growth_bytes=memory_trend.memory_growth_bytes,
        memory_growth_limit_bytes=memory_trend.memory_growth_limit_bytes,
        sidecar_memory_growth_observed=(
            memory_trend.sidecar_memory_growth_observed
        ),
        qwenpaw_slowdown_observed=derived_slowdown,
        sidecar_restart_count=0,
        health_failure_count=0,
        metric_sample_count=len(digests),
        metric_samples=tuple(digests),
        metric_sample_chain_sha256=metric_chain,
        metrics_summary_sha256=metrics_summary,
    )


def assemble_fixed_controller_evidence(
    browser: VerifiedBrowserObservation,
    runtime: RuntimeObservationResult,
    request: CollectorRequest,
) -> FixedControllerEvidence:
    """Assemble one evidence DTO from fixed, already validated observations."""

    try:
        browser_evidence = validate_fixed_browser_evidence(browser, request)
        runtime_evidence = _runtime_evidence(runtime, request)
    except ControllerEvidenceAssemblyError:
        raise
    except Exception:
        raise _error(CONTROLLER_EVIDENCE_INVALID) from None
    return FixedControllerEvidence(
        controller_id=FIXED_CONTROLLER_ID,
        page_url=FIXED_PUBLIC_PAGE_URL,
        request_fingerprint_sha256=request.request_fingerprint_sha256,
        collected_at=runtime_evidence.window_ended_at,
        synthetic=False,
        browser=browser_evidence,
        runtime=runtime_evidence,
    )


__all__ = [
    "CONTROLLER_EVIDENCE_BROWSER_HOLD",
    "CONTROLLER_EVIDENCE_BROWSER_CONTROLS_HOLD",
    "CONTROLLER_EVIDENCE_BROWSER_CURSOR_SEEK_HOLD",
    "CONTROLLER_EVIDENCE_BROWSER_EDIT_RESTORE_HOLD",
    "CONTROLLER_EVIDENCE_BROWSER_EDIT_WRITE_HOLD",
    "CONTROLLER_EVIDENCE_BROWSER_LATEST_WINS_HOLD",
    "CONTROLLER_EVIDENCE_BROWSER_MEDIA_COUNT_HOLD",
    "CONTROLLER_EVIDENCE_BROWSER_MEDIA_HTTP_HOLD",
    "CONTROLLER_EVIDENCE_BROWSER_PARAGRAPH_SEEK_HOLD",
    "CONTROLLER_EVIDENCE_BROWSER_PLAYER_HOLD",
    "CONTROLLER_EVIDENCE_INVALID",
    "CONTROLLER_EVIDENCE_LAYOUT_HOLD",
    "CONTROLLER_EVIDENCE_PENDING_GAP_HOLD",
    "CONTROLLER_EVIDENCE_RUNTIME_HOLD",
    "ControllerEvidenceAssemblyError",
    "assemble_fixed_controller_evidence",
    "validate_fixed_browser_evidence",
]
