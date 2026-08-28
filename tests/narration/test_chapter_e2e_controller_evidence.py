from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
from inspect import signature

import pytest
import scripts.tts.chapter_e2e_collector as collector_module

from scripts.tts.chapter_e2e_browser_observer import (
    BrowserInteractionEvidence,
    BrowserLayoutObservation,
    VerifiedBrowserObservation,
)
from scripts.tts.chapter_e2e_collector import (
    CollectorRequest,
    FIXED_CONTROLLER_ID,
    FIXED_PUBLIC_PAGE_URL,
    PerformanceSeed,
    build_sidecar_metric_sample_chain_sha256,
)
from scripts.tts.chapter_e2e_controller_evidence import (
    CONTROLLER_EVIDENCE_BROWSER_HOLD,
    CONTROLLER_EVIDENCE_BROWSER_CONTROLS_HOLD,
    CONTROLLER_EVIDENCE_BROWSER_CURSOR_SEEK_HOLD,
    CONTROLLER_EVIDENCE_BROWSER_EDIT_RESTORE_HOLD,
    CONTROLLER_EVIDENCE_BROWSER_EDIT_WRITE_HOLD,
    CONTROLLER_EVIDENCE_BROWSER_LATEST_WINS_HOLD,
    CONTROLLER_EVIDENCE_BROWSER_MEDIA_COUNT_HOLD,
    CONTROLLER_EVIDENCE_BROWSER_MEDIA_HTTP_HOLD,
    CONTROLLER_EVIDENCE_BROWSER_PARAGRAPH_SEEK_HOLD,
    CONTROLLER_EVIDENCE_BROWSER_PLAYER_HOLD,
    CONTROLLER_EVIDENCE_LAYOUT_HOLD,
    CONTROLLER_EVIDENCE_PENDING_GAP_HOLD,
    CONTROLLER_EVIDENCE_RUNTIME_HOLD,
    ControllerEvidenceAssemblyError,
    assemble_fixed_controller_evidence,
    validate_fixed_browser_evidence,
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
    RuntimeObservationResult,
)


STARTED_AT = datetime(2026, 8, 27, 12, 0, 0, tzinfo=timezone.utc)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _request() -> CollectorRequest:
    return CollectorRequest(
        created_at=STARTED_AT,
        request_sha256=_sha("request-bytes"),
        request_fingerprint_sha256=_sha("request-fingerprint"),
        preflight_payload_sha256=_sha("preflight"),
            expectation=ProbeExpectation(
                run_fingerprint_sha256=_sha("run"),
                target_scope_sha256=_sha("scope"),
                automatic_edition_id_sha256=_sha("automatic-id"),
                automatic_edition_fingerprint_sha256=_sha("automatic"),
                manual_edition_id_sha256=_sha("manual-id"),
                manual_edition_fingerprint_sha256=_sha("manual"),
            listening_output_hashes=tuple(sorted((_sha("one"), _sha("two")))),
            required_stability_seconds=1800.0,
        ),
        performance_seed=PerformanceSeed(
            request_to_ready_seconds=(18.5, 24.25),
            observed_http_first_audio_ms=(640, 820),
            chapter_audio_duration_seconds=126.5,
        ),
    )


def _browser() -> VerifiedBrowserObservation:
    captures = []
    layouts = []
    device_pixel_ratios = (1.0, 1.25, 2.0, 1.5)
    for index, (width, height, mode) in enumerate(FIXED_REQUIRED_CAPTURES):
        device_pixel_ratio = device_pixel_ratios[index]
        captures.append(
            BrowserCaptureObservation(
                calibration_attempts=(
                    CalibrationObservation(
                        requested_outer_width=width + 40,
                        requested_outer_height=height + 30,
                        observed_inner_width=width - 1,
                        observed_inner_height=height - 1,
                    ),
                    CalibrationObservation(
                        requested_outer_width=width + 20,
                        requested_outer_height=height + 10,
                        observed_inner_width=width,
                        observed_inner_height=height,
                    ),
                ),
                assistant_panel_expanded=mode == "expanded",
                device_pixel_ratio=device_pixel_ratio,
                screenshot_pixel_width=round(width * device_pixel_ratio),
                screenshot_pixel_height=round(height * device_pixel_ratio),
                screenshot_bytes=f"png-{index}".encode(),
                console_summary_bytes=f"console-{index}".encode(),
                network_summary_bytes=f"network-{index}".encode(),
            )
        )
        layouts.append(
            BrowserLayoutObservation(
                target_css_width=width,
                target_css_height=height,
                assistant_mode=mode,
                tracked_visible_region_count=3,
                nonzero_overlap_pair_count=0,
                horizontal_overflow_px=0,
            )
        )
    return VerifiedBrowserObservation(
        captures=tuple(captures),
        layout_observations=tuple(layouts),
        capture_console_error_counts=(0, 0, 0, 0),
        report_sha256=_sha("browser-report"),
        edge_executable_sha256=_sha("browser-binary"),
        node_executable_sha256=_sha("node-binary"),
        network_request_count=12,
        console_entry_count=13,
        console_error_count=0,
        page_error_count=0,
        interaction_evidence=BrowserInteractionEvidence(
            player_visible=True,
            editor_kind="codemirror6",
            paragraph_context_menu_seek_observed=True,
            cursor_keyboard_seek_observed=True,
            latest_wins_observed=True,
            play_pause_rate_seek_observed=True,
            edit_restored=True,
            edit_tts_write_request_count=0,
            media_http_observed=True,
            media_request_count=5,
            pending_gap_status="observed",
            pending_gap_stop_before_observed=True,
            pending_gap_reason_code="OBSERVED",
        ),
    )


def _runtime() -> RuntimeObservationResult:
    samples = tuple(
        RuntimeMetricObservation(
            observed_at=STARTED_AT + timedelta(minutes=index),
            sidecar_healthy=True,
            sidecar_restart_count=0,
            health_failure_count=0,
            active_synthesis_count=1 if index == 0 else 0,
            queued_job_count=0,
            resident_memory_bytes=1_000_000_000 + index * 1_000_000,
        )
        for index in range(31)
    )
    return RuntimeObservationResult(
        metric_samples=samples,
        host_paging=HostPagingSummary(
            host_paging_observed=False,
            pageout_delta=0,
            swapout_delta=0,
        ),
        max_qwenpaw_observation_latency_ms=150,
        qwenpaw_slowdown_observed=False,
    )


def test_assembler_derives_fixed_evidence_without_caller_verdicts() -> None:
    request = _request()
    runtime = _runtime()

    evidence = assemble_fixed_controller_evidence(
        _browser(), runtime, request
    )

    assert evidence.controller_id == FIXED_CONTROLLER_ID
    assert evidence.page_url == FIXED_PUBLIC_PAGE_URL
    assert evidence.page_url == "http://127.0.0.1:18088/chat"
    assert evidence.synthetic is False
    assert evidence.collected_at == runtime.metric_samples[-1].observed_at
    assert evidence.browser.time_to_first_audio_ms == 820
    assert evidence.runtime.request_to_ready_seconds == 24.25
    assert evidence.runtime.chapter_audio_duration_seconds == 126.5
    assert evidence.runtime.peak_memory_bytes == max(
        sample.resident_memory_bytes for sample in runtime.metric_samples
    )
    assert evidence.runtime.host_paging_observed is False
    assert evidence.runtime.pageout_delta == 0
    assert evidence.runtime.swapout_delta == 0
    assert evidence.runtime.memory_baseline_median_bytes == 1_002_000_000
    assert evidence.runtime.memory_tail_median_bytes == 1_028_000_000
    assert evidence.runtime.memory_growth_bytes == 26_000_000
    assert (
        evidence.runtime.memory_growth_limit_bytes
        == 128 * 1024 * 1024
    )
    assert evidence.runtime.sidecar_memory_growth_observed is False
    assert evidence.runtime.qwenpaw_slowdown_observed is False
    assert evidence.browser.edit_actions_created_tts_writes == 0
    assert evidence.browser.pending_gap_not_skipped is True
    assert [
        (row.width, row.height, row.assistant_mode)
        for row in evidence.browser.captures
    ] == list(FIXED_REQUIRED_CAPTURES)
    for observed, source in zip(
        evidence.browser.captures,
        _browser().captures,
        strict=True,
    ):
        final_calibration = source.calibration_attempts[-1]
        assert observed.observed_inner_width == (
            final_calibration.observed_inner_width
        )
        assert observed.observed_inner_height == (
            final_calibration.observed_inner_height
        )
        assert observed.device_pixel_ratio == source.device_pixel_ratio
        assert observed.screenshot_pixel_width == (
            source.screenshot_pixel_width
        )
        assert observed.screenshot_pixel_height == (
            source.screenshot_pixel_height
        )
        assert observed.calibration_summary_sha256 == hashlib.sha256(
            canonical_json_bytes(
                [
                    attempt.payload()
                    for attempt in source.calibration_attempts
                ]
            )
        ).hexdigest()
    assert not hasattr(evidence, "passed")

    raw_payloads = [sample.payload() for sample in runtime.metric_samples]
    assert evidence.runtime.metrics_summary_sha256 == (
        build_metric_summary_sha256(raw_payloads)
    )
    assert [row.sample_sha256 for row in evidence.runtime.metric_samples] == [
        hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        for payload in raw_payloads
    ]
    assert evidence.runtime.metric_sample_chain_sha256 == (
        build_sidecar_metric_sample_chain_sha256(
            request_fingerprint_sha256=request.request_fingerprint_sha256,
            window_started_at=runtime.metric_samples[0].observed_at,
            window_ended_at=runtime.metric_samples[-1].observed_at,
            metrics_summary_sha256=evidence.runtime.metrics_summary_sha256,
            samples=evidence.runtime.metric_samples,
        )
    )
    collector_module._validate_evidence(
        request,
        evidence,
        now=evidence.collected_at + timedelta(seconds=20),
        require_real=True,
    )


def test_public_browser_validator_matches_assembled_projection() -> None:
    browser = _browser()
    request = _request()

    projected = validate_fixed_browser_evidence(browser, request)
    assembled = assemble_fixed_controller_evidence(
        browser,
        _runtime(),
        request,
    )

    assert projected == assembled.browser


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tracked_visible_region_count", 0),
        ("nonzero_overlap_pair_count", 1),
        ("horizontal_overflow_px", 1),
    ],
)
def test_layout_gate_is_derived_from_exact_four_observations(
    field: str,
    value: int,
) -> None:
    browser = _browser()
    layouts = list(browser.layout_observations)
    layouts[0] = replace(layouts[0], **{field: value})

    with pytest.raises(ControllerEvidenceAssemblyError) as captured:
        assemble_fixed_controller_evidence(
            replace(browser, layout_observations=tuple(layouts)),
            _runtime(),
            _request(),
        )
    assert captured.value.code == CONTROLLER_EVIDENCE_LAYOUT_HOLD


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("console_error_count", 1),
        ("page_error_count", 1),
        ("network_request_count", 0),
    ],
)
def test_console_page_and_network_gate_fails_closed(
    field: str,
    value: int,
) -> None:
    with pytest.raises(ControllerEvidenceAssemblyError) as captured:
        assemble_fixed_controller_evidence(
            replace(_browser(), **{field: value}), _runtime(), _request()
        )
    assert captured.value.code == CONTROLLER_EVIDENCE_BROWSER_HOLD


def test_capture_console_errors_fail_closed() -> None:
    browser = replace(
        _browser(), capture_console_error_counts=(0, 0, 1, 0)
    )
    with pytest.raises(ControllerEvidenceAssemblyError) as captured:
        assemble_fixed_controller_evidence(browser, _runtime(), _request())
    assert captured.value.code == CONTROLLER_EVIDENCE_BROWSER_HOLD


def test_calibration_summary_binds_every_attempt_not_only_final_size() -> None:
    browser = _browser()
    baseline = assemble_fixed_controller_evidence(
        browser, _runtime(), _request()
    )
    captures = list(browser.captures)
    first = captures[0]
    attempts = list(first.calibration_attempts)
    attempts[0] = replace(
        attempts[0],
        requested_outer_width=attempts[0].requested_outer_width + 1,
    )
    captures[0] = replace(first, calibration_attempts=tuple(attempts))
    changed = assemble_fixed_controller_evidence(
        replace(browser, captures=tuple(captures)),
        _runtime(),
        _request(),
    )

    assert (
        changed.browser.captures[0].calibration_summary_sha256
        != baseline.browser.captures[0].calibration_summary_sha256
    )
    assert changed.browser.captures[0].observed_inner_width == (
        baseline.browser.captures[0].observed_inner_width
    )
    assert changed.browser.captures[0].observed_inner_height == (
        baseline.browser.captures[0].observed_inner_height
    )


@pytest.mark.parametrize(
    ("case", "value"),
    [
        ("inner_width", 1919),
        ("inner_height", 1079),
        ("device_pixel_ratio", 0.0),
        ("device_pixel_ratio", float("nan")),
        ("screenshot_pixel_width", 1),
        ("screenshot_pixel_height", 1),
        ("intermediate_outer_width", 0),
    ],
)
def test_actual_viewport_dpr_pixels_and_calibration_fail_closed(
    case: str,
    value: object,
) -> None:
    browser = _browser()
    captures = list(browser.captures)
    capture = captures[0]
    if case in {"inner_width", "inner_height"}:
        attempts = list(capture.calibration_attempts)
        field = (
            "observed_inner_width"
            if case == "inner_width"
            else "observed_inner_height"
        )
        attempts[-1] = replace(attempts[-1], **{field: value})
        capture = replace(capture, calibration_attempts=tuple(attempts))
    elif case == "intermediate_outer_width":
        attempts = list(capture.calibration_attempts)
        attempts[0] = replace(
            attempts[0], requested_outer_width=value
        )
        capture = replace(capture, calibration_attempts=tuple(attempts))
    else:
        capture = replace(capture, **{case: value})
    captures[0] = capture

    with pytest.raises(ControllerEvidenceAssemblyError) as captured:
        assemble_fixed_controller_evidence(
            replace(browser, captures=tuple(captures)),
            _runtime(),
            _request(),
        )
    assert captured.value.code == CONTROLLER_EVIDENCE_BROWSER_HOLD


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    [
        ("player_visible", False, CONTROLLER_EVIDENCE_BROWSER_PLAYER_HOLD),
        (
            "paragraph_context_menu_seek_observed",
            False,
            CONTROLLER_EVIDENCE_BROWSER_PARAGRAPH_SEEK_HOLD,
        ),
        (
            "cursor_keyboard_seek_observed",
            False,
            CONTROLLER_EVIDENCE_BROWSER_CURSOR_SEEK_HOLD,
        ),
        (
            "latest_wins_observed",
            False,
            CONTROLLER_EVIDENCE_BROWSER_LATEST_WINS_HOLD,
        ),
        (
            "play_pause_rate_seek_observed",
            False,
            CONTROLLER_EVIDENCE_BROWSER_CONTROLS_HOLD,
        ),
        (
            "edit_restored",
            False,
            CONTROLLER_EVIDENCE_BROWSER_EDIT_RESTORE_HOLD,
        ),
        (
            "edit_tts_write_request_count",
            1,
            CONTROLLER_EVIDENCE_BROWSER_EDIT_WRITE_HOLD,
        ),
        (
            "media_http_observed",
            False,
            CONTROLLER_EVIDENCE_BROWSER_MEDIA_HTTP_HOLD,
        ),
        (
            "media_request_count",
            4,
            CONTROLLER_EVIDENCE_BROWSER_MEDIA_COUNT_HOLD,
        ),
    ],
)
def test_required_browser_interactions_cannot_be_promoted_by_caller(
    field: str,
    value: object,
    expected_code: str,
) -> None:
    browser = _browser()
    browser = replace(
        browser,
        interaction_evidence=replace(
            browser.interaction_evidence, **{field: value}
        ),
    )
    with pytest.raises(ControllerEvidenceAssemblyError) as captured:
        assemble_fixed_controller_evidence(browser, _runtime(), _request())
    assert captured.value.code == expected_code


def test_pending_gap_not_observed_is_stable_hold() -> None:
    browser = _browser()
    browser = replace(
        browser,
        interaction_evidence=replace(
            browser.interaction_evidence,
            pending_gap_status="not_observed",
            pending_gap_stop_before_observed=False,
        ),
    )
    with pytest.raises(ControllerEvidenceAssemblyError) as captured:
        assemble_fixed_controller_evidence(browser, _runtime(), _request())
    assert captured.value.code == CONTROLLER_EVIDENCE_PENDING_GAP_HOLD


@pytest.mark.parametrize("case", ["paging_flag", "slow_flag", "restart", "gap"])
def test_runtime_booleans_and_metric_window_are_rederived(case: str) -> None:
    runtime = _runtime()
    if case == "paging_flag":
        runtime = replace(
            runtime,
            host_paging=replace(
                runtime.host_paging, host_paging_observed=True
            ),
        )
    elif case == "slow_flag":
        runtime = replace(runtime, qwenpaw_slowdown_observed=True)
    else:
        samples = list(runtime.metric_samples)
        if case == "restart":
            samples[5] = replace(samples[5], sidecar_restart_count=1)
        else:
            samples[5] = replace(
                samples[5], observed_at=samples[4].observed_at + timedelta(seconds=61)
            )
        runtime = replace(runtime, metric_samples=tuple(samples))

    with pytest.raises(ControllerEvidenceAssemblyError) as captured:
        assemble_fixed_controller_evidence(_browser(), runtime, _request())
    assert captured.value.code == CONTROLLER_EVIDENCE_RUNTIME_HOLD


def test_host_paging_is_bound_telemetry_without_changing_memory_trend() -> None:
    runtime = _runtime()
    runtime = replace(
        runtime,
        host_paging=HostPagingSummary(
            host_paging_observed=True,
            pageout_delta=2_503,
            swapout_delta=0,
        ),
    )

    evidence = assemble_fixed_controller_evidence(
        _browser(), runtime, _request()
    )

    assert evidence.runtime.host_paging_observed is True
    assert evidence.runtime.pageout_delta == 2_503
    assert evidence.runtime.swapout_delta == 0
    assert evidence.runtime.sidecar_memory_growth_observed is False


def test_sidecar_memory_growth_is_derived_from_bound_metric_samples() -> None:
    runtime = _runtime()
    samples = list(runtime.metric_samples)
    baseline = samples[2].resident_memory_bytes
    limit = 128 * 1024 * 1024
    for index in range(26, 31):
        samples[index] = replace(
            samples[index],
            resident_memory_bytes=baseline + limit + 1,
        )
    runtime = replace(runtime, metric_samples=tuple(samples))

    evidence = assemble_fixed_controller_evidence(
        _browser(), runtime, _request()
    )

    assert evidence.runtime.memory_baseline_median_bytes == baseline
    assert evidence.runtime.memory_tail_median_bytes == baseline + limit + 1
    assert evidence.runtime.memory_growth_bytes == limit + 1
    assert evidence.runtime.memory_growth_limit_bytes == limit
    assert evidence.runtime.sidecar_memory_growth_observed is True


def test_public_assembler_accepts_no_url_hash_or_performance_overrides() -> None:
    assert tuple(signature(assemble_fixed_controller_evidence).parameters) == (
        "browser",
        "runtime",
        "request",
    )
    assert tuple(signature(validate_fixed_browser_evidence).parameters) == (
        "browser",
        "request",
    )
