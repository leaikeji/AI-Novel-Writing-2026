from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import traceback
from uuid import UUID

import pytest
import scripts.tts.chapter_e2e_probes as probe_module

from scripts.tts.chapter_e2e_probes import (
    ALLOWED_ASSISTANT_MODES,
    BoundProbeReportCache,
    DEFAULT_REPORT_WAIT_TIMEOUT_SECONDS,
    EXPECTED_SIDECAR_CONTAINER_NAME,
    PROBE_SCHEMA_VERSION,
    ProbeExpectation,
    ProbeReportError,
    StrictJsonChapterE2EProbeLoader,
    StrictReportBrowserProbe,
    load_chapter_e2e_probe_report,
)
from scripts.tts.chapter_e2e_executor import (
    BrowserManifestObservation,
    TechnicalProbeContext,
)
from scripts.tts.validate_chapter_e2e import (
    ALLOWED_VIEWPORTS,
    ChapterCase,
    ChapterFixture,
    RunnerConfig,
    RunnerError,
    SIDECAR_PEAK_MEMORY_LIMIT_BYTES,
    TechnicalOutcome,
    _validate_technical,
)


NOW = datetime(2026, 8, 27, 12, 0, 0, tzinfo=timezone.utc)
COLLECTED_AT = NOW - timedelta(seconds=30)
RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
NOVEL_ID = UUID("22222222-2222-4222-8222-222222222222")
DOCUMENT_ID = UUID("33333333-3333-4333-8333-333333333333")
AUTOMATIC_EDITION_ID = UUID("44444444-4444-4444-8444-444444444444")
MANUAL_EDITION_ID = UUID("55555555-5555-4555-8555-555555555555")
AUTOMATIC_EDITION_FINGERPRINT = "c" * 64
MANUAL_EDITION_FINGERPRINT = "d" * 64
OUTPUT_HASHES = ("a" * 64, "b" * 64)


def _config(tmp_path: Path, *, duration_minutes: float = 30.0) -> RunnerConfig:
    return RunnerConfig(
        run_id=RUN_ID,
        mode="real",
        fixture_manifest=tmp_path / "fixture.json",
        api_base="http://127.0.0.1:18088/api/ai-novel-world-2026",
        novel_id=NOVEL_ID,
        document_id=DOCUMENT_ID,
        automatic_case_id="automatic",
        manual_case_id="manual",
        private_work_dir=tmp_path / "private",
        output_dir=tmp_path / "evidence",
        duration_minutes=duration_minutes,
        listening_record=None,
        resume=False,
    )


def _expectation(
    tmp_path: Path,
    *,
    duration_minutes: float = 30.0,
    output_hashes: tuple[str, ...] = OUTPUT_HASHES,
) -> ProbeExpectation:
    return ProbeExpectation.from_runner(
        _config(tmp_path, duration_minutes=duration_minutes),
        automatic_edition_id=AUTOMATIC_EDITION_ID,
        automatic_edition_fingerprint=AUTOMATIC_EDITION_FINGERPRINT,
        manual_edition_id=MANUAL_EDITION_ID,
        manual_edition_fingerprint=MANUAL_EDITION_FINGERPRINT,
        listening_output_hashes=output_hashes,
    )


def _payload(
    expectation: ProbeExpectation,
    *,
    collected_at: datetime = COLLECTED_AT,
) -> dict[str, object]:
    return {
        "schema_version": PROBE_SCHEMA_VERSION,
        "collected_at": collected_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "binding": expectation.report_binding(collected_at=collected_at),
        "browser": {
            "observer_report_sha256": "8" * 64,
            "captures": [
                {
                    "width": width,
                    "height": height,
                    "assistant_mode": mode,
                    "console_error_count": 0,
                    "overlap_count": 0,
                }
                for width, height in ALLOWED_VIEWPORTS
                for mode in ALLOWED_ASSISTANT_MODES
            ],
            "range_status_codes": [200, 206, 304, 416],
            "time_to_first_audio_ms": 1250,
            "seam_pairs_checked": 3,
            "seek_latest_wins": True,
            "pending_gap_not_skipped": True,
            "edit_actions_created_tts_writes": 0,
        },
        "runtime": {
            "sidecar_container_name": EXPECTED_SIDECAR_CONTAINER_NAME,
            "stability_elapsed_seconds": 1800.5,
            "chapter_audio_duration_seconds": 120.25,
            "request_to_ready_seconds": 45.75,
            "peak_memory_bytes": 2_000_000_000,
            "host_paging_observed": False,
            "pageout_delta": 0,
            "swapout_delta": 0,
            "memory_baseline_median_bytes": 1_500_000_000,
            "memory_tail_median_bytes": 1_600_000_000,
            "memory_growth_bytes": 100_000_000,
            "memory_growth_limit_bytes": 128 * 1024 * 1024,
            "sidecar_memory_growth_observed": False,
            "qwenpaw_slowdown_observed": False,
            "sidecar_restart_count": 0,
            "health_failure_count": 0,
        },
    }


def _write_report(
    path: Path,
    payload: object,
    *,
    mode: int = 0o600,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    path.chmod(mode)
    return path


def _technical_context() -> TechnicalProbeContext:
    return TechnicalProbeContext(
        automatic_request_id=UUID("66666666-6666-4666-8666-666666666666"),
        automatic_edition_id=AUTOMATIC_EDITION_ID,
        automatic_edition_fingerprint=AUTOMATIC_EDITION_FINGERPRINT,
        automatic_manifest_revision=2,
        manual_request_id=UUID("77777777-7777-4777-8777-777777777777"),
        manual_edition_id=MANUAL_EDITION_ID,
        manual_edition_fingerprint=MANUAL_EDITION_FINGERPRINT,
        manual_manifest_revision=1,
        request_to_ready_seconds=(12.0, 15.0),
        observed_http_first_audio_ms=(500, 750),
        chapter_audio_duration_seconds=120.25,
        range_status_codes=(200, 206, 304, 416),
        listening_output_hashes=OUTPUT_HASHES,
    )


def _fixture() -> ChapterFixture:
    automatic = ChapterCase(
        case_id="automatic",
        mode="automatic_zero_blockers",
        source_text="自动链",
        source_sha256="a" * 64,
        review_policy="blockers_only",
        expected_initial_blocker_codes=(),
        corrections=(),
    )
    manual = ChapterCase(
        case_id="manual",
        mode="manual_blocker_resolution",
        source_text="人工链",
        source_sha256="b" * 64,
        review_policy="blockers_only",
        expected_initial_blocker_codes=("B_SPEAKER_UNKNOWN",),
        corrections=(),
    )
    return ChapterFixture(
        fixture_id="fixture-v2",
        manifest_sha256="c" * 64,
        authorization_reference="authorized-fixture",
        voice_scope="isolated_test_only",
        production_eligible=False,
        commercial_distribution_status="not_evaluated",
        minimum_character_speakers=2,
        minimum_distinct_voice_versions=3,
        expected_formal_speakers=("林晚", "沈川"),
        require_uncached_nano_model_run=True,
        restoration_policy="dedicated_append_only_author_visible",
        automatic=automatic,
        manual=manual,
        required_viewports=ALLOWED_VIEWPORTS,
    )


def _load(
    tmp_path: Path,
    payload: dict[str, object],
    *,
    expectation: ProbeExpectation | None = None,
) -> object:
    expected = expectation or _expectation(tmp_path)
    path = _write_report(tmp_path / "probe-report.json", payload)
    return StrictJsonChapterE2EProbeLoader().load(
        path,
        expectation=expected,
        now=NOW,
    )


def test_valid_report_is_bound_and_maps_only_measured_values(
    tmp_path: Path,
) -> None:
    expectation = _expectation(tmp_path)
    payload = _payload(expectation)
    path = _write_report(tmp_path / "probe-report.json", payload)

    bound = load_chapter_e2e_probe_report(
        path,
        expectation=expectation,
        now=NOW,
    )

    assert bound.collected_at == COLLECTED_AT
    assert bound.report_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert bound.binding_fingerprint_sha256 == payload["binding"][
        "binding_fingerprint_sha256"
    ]
    assert bound.host_paging_observed is False
    assert bound.pageout_delta == 0
    assert bound.swapout_delta == 0
    assert bound.memory_baseline_median_bytes == 1_500_000_000
    assert bound.memory_tail_median_bytes == 1_600_000_000
    assert bound.memory_growth_bytes == 100_000_000
    assert bound.memory_growth_limit_bytes == 128 * 1024 * 1024
    assert bound.sidecar_memory_growth_observed is False
    assert bound.qwenpaw_slowdown_observed is False
    assert str(path) not in repr(bound)
    outcome = bound.to_technical_outcome()
    assert type(outcome) is TechnicalOutcome
    assert outcome == TechnicalOutcome(
        collector_collected_at="2026-08-27T11:59:30Z",
        stability_elapsed_seconds=1800.5,
        chapter_audio_duration_seconds=120.25,
        request_to_ready_seconds=45.75,
        time_to_first_audio_ms=1250,
        peak_memory_bytes=2_000_000_000,
        host_paging_observed=False,
        pageout_delta=0,
        swapout_delta=0,
        memory_baseline_median_bytes=1_500_000_000,
        memory_tail_median_bytes=1_600_000_000,
        memory_growth_bytes=100_000_000,
        memory_growth_limit_bytes=128 * 1024 * 1024,
        sidecar_memory_growth_observed=False,
        qwenpaw_slowdown_observed=False,
        range_status_codes=(200, 206, 304, 416),
        seam_pairs_checked=3,
        seek_latest_wins=True,
        pending_gap_not_skipped=True,
        edit_actions_created_tts_writes=0,
        browser_viewports=ALLOWED_VIEWPORTS,
        browser_assistant_modes=("collapsed", "expanded"),
        browser_console_error_count=0,
        browser_overlap_count=0,
        sidecar_restart_count=0,
        health_failure_count=0,
        listening_output_hashes=OUTPUT_HASHES,
        evidence_class="unclassified_probe",
    )


def test_browser_observer_report_hash_is_required(tmp_path: Path) -> None:
    expectation = _expectation(tmp_path)
    payload = _payload(expectation)
    browser = payload["browser"]
    assert isinstance(browser, dict)
    browser["observer_report_sha256"] = "not-a-sha"

    with pytest.raises(ProbeReportError, match="PROBE_BROWSER_GATE_FAILED"):
        _load(tmp_path, payload, expectation=expectation)


def test_probe_schema_minor_version_is_frozen_at_two_three() -> None:
    assert PROBE_SCHEMA_VERSION == "moss-tts-chapter-e2e-probes/2.3"


def test_expectation_separates_edition_id_hash_from_api_fingerprint(
    tmp_path: Path,
) -> None:
    expectation = _expectation(tmp_path)

    assert expectation.run_fingerprint_sha256 == hashlib.sha256(
        str(RUN_ID).encode()
    ).hexdigest()
    assert expectation.target_scope_sha256 == hashlib.sha256(
        f"{NOVEL_ID}:{DOCUMENT_ID}".encode()
    ).hexdigest()
    assert expectation.automatic_edition_id_sha256 == hashlib.sha256(
        str(AUTOMATIC_EDITION_ID).encode()
    ).hexdigest()
    assert expectation.manual_edition_id_sha256 == hashlib.sha256(
        str(MANUAL_EDITION_ID).encode()
    ).hexdigest()
    assert (
        expectation.automatic_edition_fingerprint_sha256
        == AUTOMATIC_EDITION_FINGERPRINT
    )
    assert (
        expectation.manual_edition_fingerprint_sha256
        == MANUAL_EDITION_FINGERPRINT
    )
    assert (
        expectation.automatic_edition_id_sha256
        != expectation.automatic_edition_fingerprint_sha256
    )
    assert (
        expectation.manual_edition_id_sha256
        != expectation.manual_edition_fingerprint_sha256
    )
    assert expectation.required_stability_seconds == 1800.0


@pytest.mark.parametrize(
    "location,key",
    [
        ("top", "runtime"),
        ("binding", "run_fingerprint_sha256"),
        ("browser", "captures"),
        ("runtime", "peak_memory_bytes"),
        ("runtime", "host_paging_observed"),
        ("runtime", "pageout_delta"),
        ("runtime", "swapout_delta"),
        ("runtime", "memory_baseline_median_bytes"),
        ("runtime", "memory_tail_median_bytes"),
        ("runtime", "memory_growth_bytes"),
        ("runtime", "memory_growth_limit_bytes"),
        ("runtime", "sidecar_memory_growth_observed"),
        ("runtime", "qwenpaw_slowdown_observed"),
    ],
)
def test_missing_required_key_fails_closed(
    tmp_path: Path,
    location: str,
    key: str,
) -> None:
    expectation = _expectation(tmp_path)
    payload = _payload(expectation)
    target = payload if location == "top" else payload[location]
    assert isinstance(target, dict)
    target.pop(key)

    with pytest.raises(ProbeReportError):
        _load(tmp_path, payload, expectation=expectation)


@pytest.mark.parametrize("location", ["top", "binding", "browser", "runtime"])
def test_extra_or_sensitive_key_fails_without_leaking_value(
    tmp_path: Path,
    location: str,
) -> None:
    expectation = _expectation(tmp_path)
    payload = _payload(expectation)
    target = payload if location == "top" else payload[location]
    assert isinstance(target, dict)
    target["private_audio_path"] = "/private/secret/reference.wav"

    with pytest.raises(ProbeReportError) as captured:
        _load(tmp_path, payload, expectation=expectation)
    assert "/private/secret/reference.wav" not in str(captured.value)


@pytest.mark.parametrize(
    "field,replacement",
    [
        ("run_fingerprint_sha256", "1" * 64),
        ("target_scope_sha256", "2" * 64),
        ("automatic_edition_id_sha256", "6" * 64),
        ("manual_edition_id_sha256", "7" * 64),
        ("automatic_edition_fingerprint_sha256", "3" * 64),
        ("manual_edition_fingerprint_sha256", "4" * 64),
        ("listening_output_hashes", ["c" * 64]),
        ("required_stability_seconds", 1801.0),
        ("binding_fingerprint_sha256", "5" * 64),
    ],
)
def test_every_authority_binding_mismatch_fails_closed(
    tmp_path: Path,
    field: str,
    replacement: object,
) -> None:
    expectation = _expectation(tmp_path)
    payload = _payload(expectation)
    binding = payload["binding"]
    assert isinstance(binding, dict)
    binding[field] = replacement

    with pytest.raises(ProbeReportError) as captured:
        _load(tmp_path, payload, expectation=expectation)
    assert captured.value.code in {"PROBE_BINDING_INVALID", "PROBE_BINDING_MISMATCH"}


@pytest.mark.parametrize(
    "automatic_key,manual_key",
    [
        ("automatic_edition_id_sha256", "manual_edition_id_sha256"),
        (
            "automatic_edition_fingerprint_sha256",
            "manual_edition_fingerprint_sha256",
        ),
    ],
)
def test_swapped_automatic_manual_edition_binding_fails_with_valid_digest(
    tmp_path: Path,
    automatic_key: str,
    manual_key: str,
) -> None:
    expectation = _expectation(tmp_path)
    payload = _payload(expectation)
    binding = payload["binding"]
    assert isinstance(binding, dict)
    binding[automatic_key], binding[manual_key] = (
        binding[manual_key],
        binding[automatic_key],
    )
    unsigned_binding = dict(binding)
    unsigned_binding.pop("binding_fingerprint_sha256")
    digest_input = {
        "schema_version": PROBE_SCHEMA_VERSION,
        "collected_at": payload["collected_at"],
        **unsigned_binding,
    }
    binding["binding_fingerprint_sha256"] = hashlib.sha256(
        json.dumps(
            digest_input,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()

    with pytest.raises(ProbeReportError, match="PROBE_BINDING_MISMATCH"):
        _load(tmp_path, payload, expectation=expectation)


def test_malformed_unhashable_listening_item_is_a_stable_failure(
    tmp_path: Path,
) -> None:
    expectation = _expectation(tmp_path)
    payload = _payload(expectation)
    payload["binding"]["listening_output_hashes"] = [{"not": "a hash"}]

    with pytest.raises(ProbeReportError, match="PROBE_BINDING_INVALID"):
        _load(tmp_path, payload, expectation=expectation)


def test_collection_time_is_part_of_binding(tmp_path: Path) -> None:
    expectation = _expectation(tmp_path)
    payload = _payload(expectation)
    payload["collected_at"] = (COLLECTED_AT + timedelta(seconds=1)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    with pytest.raises(ProbeReportError, match="PROBE_BINDING_MISMATCH"):
        _load(tmp_path, payload, expectation=expectation)


def test_expired_and_future_reports_fail_with_matching_bindings(
    tmp_path: Path,
) -> None:
    expectation = _expectation(tmp_path)
    expired = NOW - timedelta(minutes=16)
    with pytest.raises(ProbeReportError, match="PROBE_REPORT_EXPIRED"):
        _load(
            tmp_path,
            _payload(expectation, collected_at=expired),
            expectation=expectation,
        )

    future = NOW + timedelta(seconds=31)
    with pytest.raises(ProbeReportError, match="PROBE_COLLECTION_TIME_FUTURE"):
        _load(
            tmp_path,
            _payload(expectation, collected_at=future),
            expectation=expectation,
        )


@pytest.mark.parametrize(
    "case",
    [
        "duplicate",
        "missing",
        "extra",
        "unsupported_viewport",
        "unsupported_assistant_mode",
    ],
)
def test_viewport_matrix_rejects_missing_duplicate_or_extra_capture(
    tmp_path: Path,
    case: str,
) -> None:
    expectation = _expectation(tmp_path)
    payload = _payload(expectation)
    captures = payload["browser"]["captures"]
    assert isinstance(captures, list)
    if case == "duplicate":
        captures[-1] = deepcopy(captures[0])
    elif case == "missing":
        captures.pop()
    elif case == "extra":
        captures.append(
            {
                "width": 3840,
                "height": 2160,
                "assistant_mode": "collapsed",
                "console_error_count": 0,
                "overlap_count": 0,
            }
        )
    elif case == "unsupported_viewport":
        captures[-1]["width"] = 1280
    else:
        captures[-1]["assistant_mode"] = "hidden"

    with pytest.raises(ProbeReportError, match="PROBE_BROWSER_GATE_FAILED"):
        _load(tmp_path, payload, expectation=expectation)


def test_viewport_contract_is_exactly_the_four_frozen_desktop_combinations() -> None:
    assert ALLOWED_VIEWPORTS == ((1920, 1080), (2560, 1440))
    assert ALLOWED_ASSISTANT_MODES == ("collapsed", "expanded")
    assert {
        (width, height, mode)
        for width, height in ALLOWED_VIEWPORTS
        for mode in ALLOWED_ASSISTANT_MODES
    } == {
        (1920, 1080, "collapsed"),
        (1920, 1080, "expanded"),
        (2560, 1440, "collapsed"),
        (2560, 1440, "expanded"),
    }


@pytest.mark.parametrize(
    "case",
    [
        "console_error",
        "overlap",
        "seek_not_latest",
        "gap_skipped",
        "edit_write",
        "bad_ranges",
        "duplicate_range",
        "no_seam",
        "negative_first_audio",
    ],
)
def test_browser_gate_rejects_any_failed_contract_metric(
    tmp_path: Path,
    case: str,
) -> None:
    expectation = _expectation(tmp_path)
    payload = _payload(expectation)
    browser = payload["browser"]
    assert isinstance(browser, dict)
    if case == "console_error":
        browser["captures"][0]["console_error_count"] = 1
    elif case == "overlap":
        browser["captures"][0]["overlap_count"] = 1
    elif case == "seek_not_latest":
        browser["seek_latest_wins"] = False
    elif case == "gap_skipped":
        browser["pending_gap_not_skipped"] = False
    elif case == "edit_write":
        browser["edit_actions_created_tts_writes"] = 1
    elif case == "bad_ranges":
        browser["range_status_codes"] = [200, 206, 304]
    elif case == "duplicate_range":
        browser["range_status_codes"] = [200, 206, 304, 304, 416]
    elif case == "no_seam":
        browser["seam_pairs_checked"] = 0
    else:
        browser["time_to_first_audio_ms"] = -1

    with pytest.raises(ProbeReportError, match="PROBE_BROWSER_GATE_FAILED"):
        _load(tmp_path, payload, expectation=expectation)


@pytest.mark.parametrize(
    "field,replacement",
    [
        ("sidecar_container_name", "untrusted-sidecar"),
        ("sidecar_restart_count", 1),
        ("health_failure_count", 1),
        ("peak_memory_bytes", -1),
        ("pageout_delta", -1),
        ("pageout_delta", False),
        ("swapout_delta", -1),
        ("swapout_delta", 0.0),
        ("memory_baseline_median_bytes", -1),
        ("memory_tail_median_bytes", False),
        ("memory_growth_bytes", -1),
        ("memory_growth_limit_bytes", 1.0),
        ("stability_elapsed_seconds", 1799.999),
        ("chapter_audio_duration_seconds", 0),
        ("request_to_ready_seconds", -1),
    ],
)
def test_runtime_gate_rejects_wrong_sidecar_failures_or_unmeasured_duration(
    tmp_path: Path,
    field: str,
    replacement: object,
) -> None:
    expectation = _expectation(tmp_path)
    payload = _payload(expectation)
    runtime = payload["runtime"]
    assert isinstance(runtime, dict)
    runtime[field] = replacement

    with pytest.raises(ProbeReportError, match="PROBE_RUNTIME_GATE_FAILED"):
        _load(tmp_path, payload, expectation=expectation)


@pytest.mark.parametrize(
    "field",
    (
        "host_paging_observed",
        "sidecar_memory_growth_observed",
        "qwenpaw_slowdown_observed",
    ),
)
@pytest.mark.parametrize(
    "replacement",
    ("false", 0, 1, None, [], {}),
)
def test_runtime_host_observations_require_exact_json_booleans(
    tmp_path: Path,
    field: str,
    replacement: object,
) -> None:
    expectation = _expectation(tmp_path)
    payload = _payload(expectation)
    runtime = payload["runtime"]
    assert isinstance(runtime, dict)
    runtime[field] = replacement

    with pytest.raises(ProbeReportError, match="PROBE_RUNTIME_GATE_FAILED"):
        _load(tmp_path, payload, expectation=expectation)


def test_true_host_paging_round_trips_as_nonblocking_telemetry(
    tmp_path: Path,
) -> None:
    expectation = _expectation(tmp_path)
    payload = _payload(expectation)
    runtime = payload["runtime"]
    assert isinstance(runtime, dict)
    runtime["host_paging_observed"] = True
    runtime["pageout_delta"] = 1

    bound = _load(tmp_path, payload, expectation=expectation)
    outcome = replace(
        bound.to_technical_outcome(),
        evidence_class="local_operator_observation",
        evidence_root_sha256="d" * 64,
    )
    assert bound.host_paging_observed is True
    assert outcome.host_paging_observed is True
    assert _validate_technical(outcome, required_seconds=1800.0) is outcome


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("host_paging_observed", True),
        ("memory_baseline_median_bytes", 1_500_000_001),
        ("memory_tail_median_bytes", 1_600_000_001),
        ("memory_growth_bytes", 100_000_001),
        ("memory_growth_limit_bytes", 128 * 1024 * 1024 + 1),
        ("sidecar_memory_growth_observed", True),
    ],
)
def test_runtime_rejects_inconsistent_memory_summaries(
    tmp_path: Path,
    field: str,
    replacement: object,
) -> None:
    expectation = _expectation(tmp_path)
    payload = _payload(expectation)
    runtime = payload["runtime"]
    assert isinstance(runtime, dict)
    runtime[field] = replacement

    with pytest.raises(ProbeReportError, match="PROBE_RUNTIME_GATE_FAILED"):
        _load(tmp_path, payload, expectation=expectation)


def test_true_qwenpaw_slowdown_round_trips_for_validator_rejection(
    tmp_path: Path,
) -> None:
    expectation = _expectation(tmp_path)
    payload = _payload(expectation)
    runtime = payload["runtime"]
    assert isinstance(runtime, dict)
    runtime["qwenpaw_slowdown_observed"] = True

    bound = _load(tmp_path, payload, expectation=expectation)
    outcome = bound.to_technical_outcome()
    assert bound.qwenpaw_slowdown_observed is True
    assert outcome.qwenpaw_slowdown_observed is True
    with pytest.raises(
        RunnerError,
        match="TECHNICAL_MEMORY_SAFETY_GATE_FAILED",
    ):
        _validate_technical(outcome, required_seconds=1800.0)


def test_sidecar_peak_above_container_limit_is_semantically_rejected(
    tmp_path: Path,
) -> None:
    expectation = _expectation(tmp_path)
    payload = _payload(expectation)
    runtime = payload["runtime"]
    assert isinstance(runtime, dict)
    runtime["peak_memory_bytes"] = SIDECAR_PEAK_MEMORY_LIMIT_BYTES + 1

    bound = _load(tmp_path, payload, expectation=expectation)
    outcome = bound.to_technical_outcome()
    assert outcome.peak_memory_bytes == SIDECAR_PEAK_MEMORY_LIMIT_BYTES + 1
    with pytest.raises(
        RunnerError,
        match="TECHNICAL_MEMORY_SAFETY_GATE_FAILED",
    ):
        _validate_technical(outcome, required_seconds=1800.0)


def test_wrong_schema_and_nonfinite_json_fail_closed(tmp_path: Path) -> None:
    expectation = _expectation(tmp_path)
    payload = _payload(expectation)
    payload["schema_version"] = "moss-tts-chapter-e2e-probes/1.0"
    with pytest.raises(ProbeReportError, match="PROBE_SCHEMA_INVALID"):
        _load(tmp_path, payload, expectation=expectation)

    payload = _payload(expectation)
    payload["schema_version"] = "moss-tts-chapter-e2e-probes/2.0"
    with pytest.raises(ProbeReportError, match="PROBE_SCHEMA_INVALID"):
        _load(tmp_path, payload, expectation=expectation)

    payload = _payload(expectation)
    payload["runtime"]["peak_memory_bytes"] = float("nan")
    path = tmp_path / "nonfinite.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)
    with pytest.raises(ProbeReportError, match="PROBE_REPORT_INVALID"):
        StrictJsonChapterE2EProbeLoader().load(
            path,
            expectation=expectation,
            now=NOW,
        )


@pytest.mark.parametrize(
    "field",
    ("host_paging_observed", "qwenpaw_slowdown_observed"),
)
def test_nonfinite_host_observation_is_rejected_during_json_parse(
    tmp_path: Path,
    field: str,
) -> None:
    expectation = _expectation(tmp_path)
    payload = _payload(expectation)
    runtime = payload["runtime"]
    assert isinstance(runtime, dict)
    runtime[field] = float("nan")
    path = tmp_path / f"nonfinite-{field}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)

    with pytest.raises(ProbeReportError, match="PROBE_REPORT_INVALID"):
        StrictJsonChapterE2EProbeLoader().load(
            path,
            expectation=expectation,
            now=NOW,
        )


def test_duplicate_json_key_is_rejected_before_schema_validation(
    tmp_path: Path,
) -> None:
    expectation = _expectation(tmp_path)
    encoded = json.dumps(_payload(expectation), separators=(",", ":"))
    duplicated = (
        '{"schema_version":"moss-tts-chapter-e2e-probes/0.0",'
        + encoded[1:]
    )
    path = tmp_path / "duplicate.json"
    path.write_text(duplicated, encoding="utf-8")
    path.chmod(0o600)

    with pytest.raises(ProbeReportError, match="PROBE_REPORT_INVALID"):
        StrictJsonChapterE2EProbeLoader().load(
            path,
            expectation=expectation,
            now=NOW,
        )


def test_report_requires_absolute_external_regular_owned_0600_file(
    tmp_path: Path,
) -> None:
    expectation = _expectation(tmp_path)
    payload = _payload(expectation)
    unsafe_mode = _write_report(tmp_path / "mode.json", payload, mode=0o640)
    with pytest.raises(ProbeReportError, match="PROBE_FILE_UNSAFE"):
        StrictJsonChapterE2EProbeLoader().load(
            unsafe_mode,
            expectation=expectation,
            now=NOW,
        )

    with pytest.raises(ProbeReportError, match="PROBE_PATH_UNSAFE"):
        StrictJsonChapterE2EProbeLoader().load(
            Path("relative-probe.json"),
            expectation=expectation,
            now=NOW,
        )

    with pytest.raises(ProbeReportError, match="PROBE_PATH_UNSAFE"):
        StrictJsonChapterE2EProbeLoader().load(
            Path(__file__).resolve(),
            expectation=expectation,
            now=NOW,
        )


def test_symlink_and_hardlink_reports_are_rejected(tmp_path: Path) -> None:
    expectation = _expectation(tmp_path)
    target = _write_report(tmp_path / "target.json", _payload(expectation))
    symlink = tmp_path / "symlink.json"
    symlink.symlink_to(target)
    with pytest.raises(ProbeReportError, match="PROBE_PATH_UNSAFE"):
        StrictJsonChapterE2EProbeLoader().load(
            symlink,
            expectation=expectation,
            now=NOW,
        )

    hardlink = tmp_path / "hardlink.json"
    os.link(target, hardlink)
    with pytest.raises(ProbeReportError, match="PROBE_FILE_UNSAFE"):
        StrictJsonChapterE2EProbeLoader().load(
            hardlink,
            expectation=expectation,
            now=NOW,
        )


def test_report_parent_requires_current_uid_owner_only_regular_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expectation = _expectation(tmp_path)
    directory = tmp_path / "private-report-parent"
    report = _write_report(directory / "report.json", _payload(expectation))

    directory.chmod(0o755)
    with pytest.raises(ProbeReportError, match="PROBE_FILE_UNSAFE"):
        StrictJsonChapterE2EProbeLoader().load(
            report,
            expectation=expectation,
            now=NOW,
        )

    directory.chmod(0o700)
    actual_uid = os.getuid()
    monkeypatch.setattr(probe_module.os, "getuid", lambda: actual_uid + 1)
    with pytest.raises(ProbeReportError, match="PROBE_FILE_UNSAFE"):
        StrictJsonChapterE2EProbeLoader().load(
            report,
            expectation=expectation,
            now=NOW,
        )


def test_report_rejects_installed_pawapp_root_and_symlink_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expectation = _expectation(tmp_path)
    installed_root = tmp_path / "installed-pawapp"
    private_inside = installed_root / "private"
    report = _write_report(private_inside / "report.json", _payload(expectation))
    monkeypatch.setattr(probe_module, "CURRENT_PAWAPP_ROOT", installed_root)
    with pytest.raises(ProbeReportError, match="PROBE_PATH_UNSAFE"):
        StrictJsonChapterE2EProbeLoader().load(
            report,
            expectation=expectation,
            now=NOW,
        )

    external = tmp_path / "external-private"
    external_report = _write_report(
        external / "report.json",
        _payload(expectation),
    )
    linked_parent = tmp_path / "linked-private"
    linked_parent.symlink_to(external, target_is_directory=True)
    with pytest.raises(ProbeReportError, match="PROBE_PATH_UNSAFE"):
        StrictJsonChapterE2EProbeLoader().load(
            linked_parent / external_report.name,
            expectation=expectation,
            now=NOW,
        )


def test_report_file_identity_must_remain_stable_while_reading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expectation = _expectation(tmp_path)
    report = _write_report(tmp_path / "identity-report.json", _payload(expectation))
    original_read = probe_module.os.read
    replaced = False

    def replace_after_read(descriptor: int, size: int) -> bytes:
        nonlocal replaced
        data = original_read(descriptor, size)
        if data and not replaced:
            replaced = True
            report.unlink()
            report.write_bytes(data)
            report.chmod(0o600)
        return data

    monkeypatch.setattr(probe_module.os, "read", replace_after_read)
    with pytest.raises(ProbeReportError, match="PROBE_FILE_UNSAFE"):
        StrictJsonChapterE2EProbeLoader().load(
            report,
            expectation=expectation,
            now=NOW,
        )


def test_report_parent_identity_must_remain_stable_while_reading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expectation = _expectation(tmp_path)
    directory = tmp_path / "identity-parent"
    report = _write_report(directory / "report.json", _payload(expectation))
    original_bytes = report.read_bytes()
    moved_directory = tmp_path / "identity-parent-before"
    original_read = probe_module.os.read
    replaced = False

    def replace_parent_after_read(descriptor: int, size: int) -> bytes:
        nonlocal replaced
        data = original_read(descriptor, size)
        if data and not replaced:
            replaced = True
            directory.rename(moved_directory)
            directory.mkdir(mode=0o700)
            replacement = directory / report.name
            replacement.write_bytes(original_bytes)
            replacement.chmod(0o600)
        return data

    monkeypatch.setattr(probe_module.os, "read", replace_parent_after_read)
    with pytest.raises(ProbeReportError, match="PROBE_FILE_UNSAFE"):
        StrictJsonChapterE2EProbeLoader().load(
            report,
            expectation=expectation,
            now=NOW,
        )


def test_private_file_errors_are_stable_and_do_not_render_path_or_contents(
    tmp_path: Path,
) -> None:
    expectation = _expectation(tmp_path)
    private_value = "DO-NOT-LEAK-PRIVATE-PROBE-CONTENT"
    report = tmp_path / "DO-NOT-LEAK-private-report.json"
    report.write_text(private_value, encoding="utf-8")
    report.chmod(0o640)

    with pytest.raises(ProbeReportError) as captured:
        StrictJsonChapterE2EProbeLoader().load(
            report,
            expectation=expectation,
            now=NOW,
        )

    rendered = "".join(
        traceback.format_exception(
            captured.type,
            captured.value,
            captured.tb,
        )
    )
    assert str(captured.value) == "PROBE_FILE_UNSAFE"
    assert str(report) not in rendered
    assert private_value not in rendered


def test_invalid_expectation_and_loader_policy_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ProbeReportError, match="PROBE_EXPECTATION_INVALID"):
        _expectation(tmp_path, output_hashes=("a" * 64, "a" * 64))
    with pytest.raises(ProbeReportError, match="PROBE_EXPECTATION_INVALID"):
        _expectation(tmp_path, duration_minutes=0)
    with pytest.raises(ProbeReportError, match="PROBE_EXPECTATION_INVALID"):
        ProbeExpectation(
            run_fingerprint_sha256="not-a-hash",
            target_scope_sha256="2" * 64,
            automatic_edition_id_sha256="5" * 64,
            manual_edition_id_sha256="6" * 64,
            automatic_edition_fingerprint_sha256="3" * 64,
            manual_edition_fingerprint_sha256="4" * 64,
            listening_output_hashes=("a" * 64,),
            required_stability_seconds=1800.0,
        )
    with pytest.raises(ProbeReportError, match="PROBE_LOADER_POLICY_INVALID"):
        StrictJsonChapterE2EProbeLoader(max_report_age_seconds=0)
    with pytest.raises(ProbeReportError, match="PROBE_COLLECTION_TIME_INVALID"):
        _expectation(tmp_path).report_binding(
            collected_at=COLLECTED_AT.replace(microsecond=1)
        )
    report = _write_report(
        tmp_path / "naive-now.json",
        _payload(_expectation(tmp_path)),
    )
    with pytest.raises(ProbeReportError, match="PROBE_COLLECTION_TIME_INVALID"):
        StrictJsonChapterE2EProbeLoader().load(
            report,
            expectation=_expectation(tmp_path),
            now=NOW.replace(tzinfo=None),
        )


def test_bound_cache_and_browser_port_require_both_completed_chains(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    context = _technical_context()
    expectation = ProbeExpectation.from_runner(
        config,
        automatic_edition_id=context.automatic_edition_id,
        automatic_edition_fingerprint=context.automatic_edition_fingerprint,
        manual_edition_id=context.manual_edition_id,
        manual_edition_fingerprint=context.manual_edition_fingerprint,
        listening_output_hashes=context.listening_output_hashes,
    )
    collected_at = datetime.now(timezone.utc).replace(microsecond=0)
    report = _write_report(
        tmp_path / "external-probe.json",
        _payload(expectation, collected_at=collected_at),
    )
    cache = BoundProbeReportCache(report)
    probe = StrictReportBrowserProbe(config, cache=cache)

    probe.begin_chain(config, "automatic")
    probe.observe_manifest(
        config,
        BrowserManifestObservation(
            chain_label="automatic",
            request_id=context.automatic_request_id,
            edition_id=context.automatic_edition_id,
            workflow_state="partial_ready",
            manifest_revision=1,
            ready_segment_count=1,
            total_segment_count=3,
            elapsed_ms=500,
        ),
    )
    probe.observe_manifest(
        config,
        BrowserManifestObservation(
            chain_label="automatic",
            request_id=context.automatic_request_id,
            edition_id=context.automatic_edition_id,
            workflow_state="ready",
            manifest_revision=2,
            ready_segment_count=3,
            total_segment_count=3,
            elapsed_ms=1500,
        ),
    )
    probe.complete_chain(
        config,
        chain_label="automatic",
        request_id=context.automatic_request_id,
        edition_id=context.automatic_edition_id,
    )
    probe.begin_chain(config, "manual")
    probe.observe_manifest(
        config,
        BrowserManifestObservation(
            chain_label="manual",
            request_id=context.manual_request_id,
            edition_id=context.manual_edition_id,
            workflow_state="ready",
            manifest_revision=1,
            ready_segment_count=4,
            total_segment_count=4,
            elapsed_ms=2000,
        ),
    )
    probe.complete_chain(
        config,
        chain_label="manual",
        request_id=context.manual_request_id,
        edition_id=context.manual_edition_id,
    )

    evidence = probe.collect(config, _fixture(), context)

    assert evidence.browser_viewports == ((1920, 1080), (2560, 1440))
    assert evidence.browser_assistant_modes == ("collapsed", "expanded")
    assert evidence.browser_console_error_count == 0
    assert evidence.browser_overlap_count == 0
    assert evidence.seek_latest_wins is True
    assert cache.load(config, context).report_sha256 == hashlib.sha256(
        report.read_bytes()
    ).hexdigest()


def test_browser_port_rejects_wrong_order_and_incomplete_ready_observation(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    cache = BoundProbeReportCache(tmp_path / "not-created.json")
    probe = StrictReportBrowserProbe(config, cache=cache)

    with pytest.raises(ProbeReportError, match="PROBE_BROWSER_SEQUENCE_INVALID"):
        probe.begin_chain(config, "manual")

    probe.begin_chain(config, "automatic")
    probe.observe_manifest(
        config,
        BrowserManifestObservation(
            chain_label="automatic",
            request_id=_technical_context().automatic_request_id,
            edition_id=AUTOMATIC_EDITION_ID,
            workflow_state="partial_ready",
            manifest_revision=1,
            ready_segment_count=1,
            total_segment_count=3,
            elapsed_ms=1,
        ),
    )
    with pytest.raises(ProbeReportError, match="PROBE_BROWSER_SEQUENCE_INVALID"):
        probe.complete_chain(
            config,
            chain_label="automatic",
            request_id=_technical_context().automatic_request_id,
            edition_id=AUTOMATIC_EDITION_ID,
        )


def test_bound_report_cache_times_out_without_external_evidence(
    tmp_path: Path,
) -> None:
    class Clock:
        value = 0.0

        def monotonic(self) -> float:
            return self.value

        def sleep(self, seconds: float) -> None:
            self.value += seconds

    clock = Clock()
    cache = BoundProbeReportCache(
        tmp_path / "missing.json",
        wait_timeout_seconds=1,
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
        poll_interval_seconds=0.25,
    )

    with pytest.raises(ProbeReportError, match="PROBE_REPORT_TIMEOUT"):
        cache.load(_config(tmp_path), _technical_context())


def test_default_wait_budget_covers_full_stability_window_and_publish_margin(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    context = _technical_context()
    expectation = ProbeExpectation.from_runner(
        config,
        automatic_edition_id=context.automatic_edition_id,
        automatic_edition_fingerprint=context.automatic_edition_fingerprint,
        manual_edition_id=context.manual_edition_id,
        manual_edition_fingerprint=context.manual_edition_fingerprint,
        listening_output_hashes=context.listening_output_hashes,
    )
    report = tmp_path / "delayed-formal-report.json"
    published: list[object] = []

    class Publisher:
        def publish(  # type: ignore[no-untyped-def]
            self, supplied_config, supplied_expectation, supplied_context
        ):
            published.append(
                (supplied_config, supplied_expectation, supplied_context)
            )

    class Clock:
        value = 0.0

        def monotonic(self) -> float:
            return self.value

        def sleep(self, seconds: float) -> None:
            self.value += seconds
            if self.value >= 1805.0 and not report.exists():
                _write_report(
                    report,
                    _payload(
                        expectation,
                        collected_at=datetime.now(timezone.utc).replace(
                            microsecond=0
                        ),
                    ),
                )

    clock = Clock()
    cache = BoundProbeReportCache(
        report,
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
        poll_interval_seconds=5.0,
        request_publisher=Publisher(),  # type: ignore[arg-type]
    )

    bound = cache.load(config, context)

    assert DEFAULT_REPORT_WAIT_TIMEOUT_SECONDS == 2100
    assert published == [(config, expectation, context)]
    assert clock.value == 1805.0
    assert bound.stability_elapsed_seconds >= 1800.0


@pytest.mark.parametrize(
    "retryable_code",
    ["PROBE_COLLECTOR_BUSY", "PROBE_COLLECTOR_INCOMPLETE"],
)
def test_formal_cache_waits_for_the_committed_collector_pair(
    tmp_path: Path,
    retryable_code: str,
) -> None:
    config = _config(tmp_path)
    context = _technical_context()
    expectation = ProbeExpectation.from_runner(
        config,
        automatic_edition_id=context.automatic_edition_id,
        automatic_edition_fingerprint=context.automatic_edition_fingerprint,
        manual_edition_id=context.manual_edition_id,
        manual_edition_fingerprint=context.manual_edition_fingerprint,
        listening_output_hashes=context.listening_output_hashes,
    )
    report = tmp_path / "collector-owned-probe-report.json"

    class Clock:
        value = 0.0

        def monotonic(self) -> float:
            return self.value

        def sleep(self, seconds: float) -> None:
            self.value += seconds

    clock = Clock()

    class CommitAwareGuard:
        calls = 0

        def load_verified(self, path, *, expectation):  # type: ignore[no-untyped-def]
            self.calls += 1
            if clock.value < 1805.0:
                raise ProbeReportError(retryable_code)
            _write_report(
                path,
                _payload(
                    expectation,
                    collected_at=datetime.now(timezone.utc).replace(
                        microsecond=0
                    ),
                ),
            )
            return StrictJsonChapterE2EProbeLoader().load(
                path,
                expectation=expectation,
            )

    guard = CommitAwareGuard()
    cache = BoundProbeReportCache(
        report,
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
        poll_interval_seconds=5.0,
        report_guard=guard,  # type: ignore[arg-type]
    )

    bound = cache.load(config, context)

    assert clock.value == 1805.0
    assert guard.calls > 1
    assert bound.stability_elapsed_seconds >= 1800.0


def test_formal_cache_times_out_while_collector_commit_is_incomplete(
    tmp_path: Path,
) -> None:
    class Clock:
        value = 0.0

        def monotonic(self) -> float:
            return self.value

        def sleep(self, seconds: float) -> None:
            self.value += seconds

    class IncompleteGuard:
        def load_verified(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise ProbeReportError("PROBE_COLLECTOR_INCOMPLETE")

    clock = Clock()
    cache = BoundProbeReportCache(
        tmp_path / "probe-report.json",
        wait_timeout_seconds=1,
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
        poll_interval_seconds=0.25,
        report_guard=IncompleteGuard(),  # type: ignore[arg-type]
    )

    with pytest.raises(ProbeReportError, match="PROBE_REPORT_TIMEOUT"):
        cache.load(_config(tmp_path), _technical_context())

    assert clock.value == 1.0


def test_formal_guard_returns_the_bound_bytes_without_loader_reopen(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    context = _technical_context()
    expectation = ProbeExpectation.from_runner(
        config,
        automatic_edition_id=context.automatic_edition_id,
        automatic_edition_fingerprint=context.automatic_edition_fingerprint,
        manual_edition_id=context.manual_edition_id,
        manual_edition_fingerprint=context.manual_edition_fingerprint,
        listening_output_hashes=context.listening_output_hashes,
    )
    report = _write_report(
        tmp_path / "guarded.json",
        _payload(
            expectation,
            collected_at=datetime.now(timezone.utc).replace(microsecond=0),
        ),
    )

    class SwappingGuard:
        def load_verified(self, path, *, expectation):  # type: ignore[no-untyped-def]
            bound = StrictJsonChapterE2EProbeLoader().load(
                path,
                expectation=expectation,
            )
            path.write_bytes(b"{}\n")
            path.chmod(0o600)
            return bound

    class ForbiddenLoader:
        def load(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("guarded bytes must never be reopened")

    cache = BoundProbeReportCache(
        report,
        loader=ForbiddenLoader(),  # type: ignore[arg-type]
        report_guard=SwappingGuard(),  # type: ignore[arg-type]
    )

    bound = cache.load(config, context)

    assert bound.listening_output_hashes == context.listening_output_hashes
    assert report.read_bytes() == b"{}\n"
