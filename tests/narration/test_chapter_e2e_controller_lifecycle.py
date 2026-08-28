from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
from inspect import signature
from pathlib import Path
from uuid import UUID

import pytest

import scripts.tts.chapter_e2e_controller_lifecycle as lifecycle
from scripts.tts.chapter_e2e_browser_observer import (
    BrowserInteractionEvidence,
    BrowserLayoutObservation,
    BrowserObservationRequest,
    VerifiedBrowserObservation,
)
from scripts.tts.chapter_e2e_collector import (
    CollectorError,
    CollectorRequest,
    CollectorResult,
    PerformanceSeed,
    _VerifiedRequestPreflight,
)
from scripts.tts.chapter_e2e_controller_evidence import (
    ControllerEvidenceAssemblyError,
    CONTROLLER_EVIDENCE_BROWSER_HOLD,
    CONTROLLER_EVIDENCE_BROWSER_CONTROLS_HOLD,
    CONTROLLER_EVIDENCE_BROWSER_CURSOR_SEEK_HOLD,
    CONTROLLER_EVIDENCE_BROWSER_EDIT_RESTORE_HOLD,
    CONTROLLER_EVIDENCE_BROWSER_LATEST_WINS_HOLD,
    CONTROLLER_EVIDENCE_BROWSER_MEDIA_HTTP_HOLD,
    CONTROLLER_EVIDENCE_BROWSER_PARAGRAPH_SEEK_HOLD,
    CONTROLLER_EVIDENCE_BROWSER_PLAYER_HOLD,
    CONTROLLER_EVIDENCE_LAYOUT_HOLD,
    CONTROLLER_EVIDENCE_PENDING_GAP_HOLD,
    CONTROLLER_EVIDENCE_RUNTIME_HOLD,
)
from scripts.tts.chapter_e2e_controller_host import (
    BrowserCaptureObservation,
    CalibrationObservation,
    CanonicalControllerArtifact,
    RuntimeMetricObservation,
)
from scripts.tts.chapter_e2e_controller_trust import (
    CONTROLLER_ID,
    CONTROLLER_REPORT_BINDING_SCHEMA_VERSION,
    FIXED_REQUIRED_CAPTURES,
    REPORT_SIGNATURE_NAMESPACE,
    VerifiedControllerPreflight,
    canonical_json_bytes,
)
from scripts.tts.chapter_e2e_probe_request import PROBE_REQUEST_FILENAME
from scripts.tts.chapter_e2e_probes import ProbeExpectation
from scripts.tts.chapter_e2e_runtime_observer import RuntimeObserverError
from scripts.tts.chapter_e2e_runtime_observer import (
    HostPagingSummary,
    RuntimeObservationResult,
)
from scripts.tts.validate_chapter_e2e import RunnerConfig


STARTED_AT = datetime(2026, 8, 27, 12, 0, 0, tzinfo=timezone.utc)
ENDED_AT = STARTED_AT + timedelta(minutes=30)
COMMITTED_AT = ENDED_AT + timedelta(seconds=5)
NOVEL_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
DOCUMENT_ID = "01234567-89ab-4cde-8fab-0123456789ab"
VALIDATION_TOKEN = "T" * 43
REQUEST_PATH = Path("/private/t4-k") / PROBE_REQUEST_FILENAME
REQUEST_BYTES = b'{"kind":"fixed-probe-request"}\n'
PREFLIGHT_BYTES = b'{"kind":"fixed-controller-preflight"}\n'
PREFLIGHT_SIGNATURE = b"fixed-preflight-signature"


def _sha(value: str | bytes) -> str:
    raw = value if type(value) is bytes else value.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _scope_sha256() -> str:
    return _sha(f"{NOVEL_ID}:{DOCUMENT_ID}")


def _request() -> CollectorRequest:
    return CollectorRequest(
        created_at=STARTED_AT,
        request_sha256=_sha(REQUEST_BYTES),
        request_fingerprint_sha256=_sha("request-fingerprint"),
        preflight_payload_sha256=_sha(PREFLIGHT_BYTES),
            expectation=ProbeExpectation(
                run_fingerprint_sha256=_sha("run"),
                target_scope_sha256=_scope_sha256(),
                automatic_edition_id_sha256=_sha("automatic-id"),
                automatic_edition_fingerprint_sha256=_sha("automatic"),
                manual_edition_id_sha256=_sha("manual-id"),
                manual_edition_fingerprint_sha256=_sha("manual"),
            listening_output_hashes=tuple(
                sorted((_sha("output-one"), _sha("output-two")))
            ),
            required_stability_seconds=1800.0,
        ),
        performance_seed=PerformanceSeed(
            request_to_ready_seconds=(18.5, 24.25),
            observed_http_first_audio_ms=(640, 820),
            chapter_audio_duration_seconds=126.5,
        ),
    )


def _snapshot() -> lifecycle._VerifiedRequestSnapshot:
    request = _request()
    payload_identity = (1, 2, 3, 4, 5, 6)
    signature_identity = (7, 8, 9, 10, 11, 12)
    verified = _VerifiedRequestPreflight(
        verified=VerifiedControllerPreflight(
            issued_at=STARTED_AT - timedelta(minutes=1),
            expires_at=ENDED_AT + timedelta(minutes=1),
            key_id="fixed-controller-key",
            principal="fixed-controller",
            controller_build_sha256=_sha("controller-build"),
            payload_sha256=_sha(PREFLIGHT_BYTES),
            policy_sha256=_sha("policy"),
            allowed_signers_sha256=_sha("allowed-signers"),
        ),
        payload_identity=payload_identity,
        signature_identity=signature_identity,
    )
    return lifecycle._VerifiedRequestSnapshot(
        request=request,
        parent=REQUEST_PATH.parent,
        parent_identity=(21, 22, 23, 24, 25, 26),
        request_bytes=REQUEST_BYTES,
        request_identity=(31, 32, 33, 34, 35, 36),
        preflight_payload=PREFLIGHT_BYTES,
        preflight_payload_identity=payload_identity,
        preflight_signature=PREFLIGHT_SIGNATURE,
        preflight_signature_identity=signature_identity,
        verified_preflight=verified,
    )


def _local_snapshot() -> lifecycle._LocalRequestSnapshot:
    return lifecycle._LocalRequestSnapshot(
        request=_request(),
        parent=REQUEST_PATH.parent,
        parent_identity=(21, 22, 23, 24, 25, 26),
        request_bytes=REQUEST_BYTES,
        request_identity=(31, 32, 33, 34, 35, 36),
    )


def _browser() -> VerifiedBrowserObservation:
    captures: list[BrowserCaptureObservation] = []
    layouts: list[BrowserLayoutObservation] = []
    for index, (width, height, mode) in enumerate(FIXED_REQUIRED_CAPTURES):
        captures.append(
            BrowserCaptureObservation(
                calibration_attempts=(
                    CalibrationObservation(
                        requested_outer_width=width + 20,
                        requested_outer_height=height + 10,
                        observed_inner_width=width,
                        observed_inner_height=height,
                    ),
                ),
                assistant_panel_expanded=mode == "expanded",
                device_pixel_ratio=1.0,
                screenshot_pixel_width=width,
                screenshot_pixel_height=height,
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


def _artifact(observation: object) -> CanonicalControllerArtifact:
    payload = {
        "schema_version": CONTROLLER_REPORT_BINDING_SCHEMA_VERSION,
        "signature_namespace": REPORT_SIGNATURE_NAMESPACE,
        "controller_id": CONTROLLER_ID,
        "signed_at": observation.signed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "preflight_payload_sha256": _sha(observation.preflight_payload),
        "run_fingerprint_sha256": observation.run_fingerprint_sha256,
        "target_scope_sha256": observation.target_scope_sha256,
        "probe_request_sha256": _sha(observation.probe_request_bytes),
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
        "required_stability_milliseconds": 1_800_000,
        "collector_report_sha256": _sha(
            observation.collector_report_bytes
        ),
        "probe_report_sha256": _sha(observation.probe_report_bytes),
        "metric_sample_count": len(observation.metric_samples),
        "observed_captures": [
            {"capture": index} for index in range(len(observation.captures))
        ],
        "controller_build_sha256": _sha("controller-build"),
        "browser_binary_sha256": _sha("browser-binary"),
    }
    return CanonicalControllerArtifact(
        schema_version=CONTROLLER_REPORT_BINDING_SCHEMA_VERSION,
        signature_namespace=REPORT_SIGNATURE_NAMESPACE,
        payload=canonical_json_bytes(payload),
    )


class _Calls:
    def __init__(self) -> None:
        self.authority_checks: list[datetime] = []
        self.controller_build_checks: list[str] = []
        self.loaded: list[datetime] = []
        self.browser_requests: list[BrowserObservationRequest] = []
        self.runtime_requests: list[tuple[str, str, str]] = []
        self.binding_observations: list[object] = []
        self.signed: list[CanonicalControllerArtifact] = []
        self.finalized: list[tuple[object, ...]] = []


def _dependencies(
    *,
    browser: VerifiedBrowserObservation | None = None,
    runtime: RuntimeObservationResult | None = None,
    second_snapshot: lifecycle._VerifiedRequestSnapshot | None = None,
    third_snapshot: lifecycle._VerifiedRequestSnapshot | None = None,
    artifact_drift: bool = False,
    artifact_build_drift: bool = False,
    production_signer_port: bool = False,
    post_sign_authority_hold: bool = False,
    pre_sign_source_drift: bool = False,
    post_sign_source_drift: bool = False,
) -> tuple[lifecycle._LifecycleDependencies, _Calls]:
    calls = _Calls()
    first = _snapshot()
    second = second_snapshot or _snapshot()
    snapshots = (first, second, third_snapshot or second)
    times = iter((STARTED_AT, ENDED_AT, COMMITTED_AT))
    expected_build = _sha("controller-build")
    source_builds = iter(
        (
            expected_build,
            _sha("pre-sign-source-drift")
            if pre_sign_source_drift
            else expected_build,
            _sha("post-sign-source-drift")
            if post_sign_source_drift
            else expected_build,
        )
    )

    def controller_build_sha256() -> str:
        value = next(source_builds)
        calls.controller_build_checks.append(value)
        return value

    def require_authority(now: datetime) -> None:
        calls.authority_checks.append(now)
        if post_sign_authority_hold and len(calls.authority_checks) == 2:
            raise lifecycle.ControllerLifecycleError(
                lifecycle.CONTROLLER_LIFECYCLE_AUTHORITY_HOLD
            )

    def load(path: Path, now: datetime) -> lifecycle._VerifiedRequestSnapshot:
        assert path == REQUEST_PATH
        calls.loaded.append(now)
        return snapshots[len(calls.loaded) - 1]

    def run_browser(request: BrowserObservationRequest) -> VerifiedBrowserObservation:
        calls.browser_requests.append(request)
        return browser or _browser()

    def collect_runtime(
        novel_id: str,
        document_id: str,
        validation_token: str,
    ) -> RuntimeObservationResult:
        calls.runtime_requests.append(
            (novel_id, document_id, validation_token)
        )
        return runtime or _runtime()

    def build(observation: object) -> CanonicalControllerArtifact:
        calls.binding_observations.append(observation)
        artifact = _artifact(observation)
        if artifact_drift:
            payload = lifecycle._decode_canonical_mapping(
                artifact.payload,
                max_bytes=96 * 1024,
                code="test",
            )
            return replace(
                artifact,
                payload=canonical_json_bytes(
                    {**payload, "target_scope_sha256": _sha("drift")}
                ),
            )
        if artifact_build_drift:
            payload = lifecycle._decode_canonical_mapping(
                artifact.payload,
                max_bytes=96 * 1024,
                code="test",
            )
            return replace(
                artifact,
                payload=canonical_json_bytes(
                    {
                        **payload,
                        "controller_build_sha256": _sha("other-build"),
                    }
                ),
            )
        return artifact

    def sign(artifact: CanonicalControllerArtifact) -> bytes:
        calls.signed.append(artifact)
        return b"fixed-report-signature"

    def finalize(*args: object) -> CollectorResult:
        calls.finalized.append(args)
        return CollectorResult(
            status="FORMAL_CONTROLLER_REPORT_COMMITTED",
            collector_report_sha256=_sha("collector"),
            probe_report_sha256=_sha("probe"),
        )

    dependencies = lifecycle._LifecycleDependencies(
        require_authority=require_authority,
        controller_build_sha256=controller_build_sha256,
        load_verified_request=load,
        run_browser=run_browser,
        collect_runtime=collect_runtime,
        build_report_binding=build,
        sign_report_binding=(
            lifecycle._production_sign_report_binding
            if production_signer_port
            else sign
        ),
        finalize_report=finalize,
        utc_now=lambda: next(times),
    )
    return dependencies, calls


def _run(dependencies: lifecycle._LifecycleDependencies) -> CollectorResult:
    return lifecycle._run_fixed_controller_report_stage(
        REQUEST_PATH,
        NOVEL_ID,
        DOCUMENT_ID,
        VALIDATION_TOKEN,
        dependencies=dependencies,
    )


def _install_local_stage(
    monkeypatch: pytest.MonkeyPatch,
    *,
    browser_observation: VerifiedBrowserObservation | None = None,
    second_snapshot: lifecycle._LocalRequestSnapshot | None = None,
    source_drift: bool = False,
) -> dict[str, list[object]]:
    first = _local_snapshot()
    snapshots = iter((first, second_snapshot or first))
    expected_build = _sha("controller-build")
    builds = iter(
        (
            expected_build,
            _sha("source-drift") if source_drift else expected_build,
        )
    )
    times = iter((STARTED_AT, ENDED_AT))
    calls: dict[str, list[object]] = {
        "builds": [],
        "loaded": [],
        "browser": [],
        "runtime": [],
        "finalized": [],
        "forbidden": [],
    }

    class _FixedDateTime:
        @classmethod
        def now(cls, tz: object) -> datetime:
            assert tz is timezone.utc
            return next(times)

    def controller_build_sha256() -> str:
        value = next(builds)
        calls["builds"].append(value)
        return value

    def load(
        path: Path,
        now: datetime,
    ) -> lifecycle._LocalRequestSnapshot:
        assert path == REQUEST_PATH
        calls["loaded"].append(now)
        return next(snapshots)

    def browser(
        request: BrowserObservationRequest,
    ) -> VerifiedBrowserObservation:
        calls["browser"].append(request)
        return browser_observation or _browser()

    def runtime(
        novel_id: str,
        document_id: str,
        validation_token: str,
    ) -> RuntimeObservationResult:
        calls["runtime"].append(
            (novel_id, document_id, validation_token)
        )
        return _runtime()

    class _Collector:
        def finalize_local_operator(
            self,
            path: Path,
            evidence: object,
            **kwargs: object,
        ) -> CollectorResult:
            calls["finalized"].append((path, evidence, kwargs))
            return CollectorResult(
                status="LOCAL_OPERATOR_OBSERVATION_COMMITTED",
                collector_report_sha256=_sha("local-collector"),
                probe_report_sha256=_sha("local-probe"),
            )

    def forbidden(*args: object, **kwargs: object) -> object:
        calls["forbidden"].append((args, kwargs))
        raise AssertionError("signed controller port used by local stage")

    monkeypatch.setattr(lifecycle, "datetime", _FixedDateTime)
    monkeypatch.setattr(
        lifecycle,
        "fixed_local_operator_build_sha256",
        controller_build_sha256,
    )
    monkeypatch.setattr(lifecycle, "_load_local_request_snapshot", load)
    monkeypatch.setattr(lifecycle, "_run_fixed_browser_observer", browser)
    monkeypatch.setattr(lifecycle, "collect_runtime_observations", runtime)
    monkeypatch.setattr(lifecycle, "FixedChapterE2ECollector", _Collector)
    monkeypatch.setattr(lifecycle, "_require_production_authority", forbidden)
    monkeypatch.setattr(lifecycle, "_production_dependencies", forbidden)
    monkeypatch.setattr(
        lifecycle,
        "_production_build_report_binding",
        forbidden,
    )
    monkeypatch.setattr(
        lifecycle,
        "_production_sign_report_binding",
        forbidden,
    )
    return calls


def test_scope_hash_matches_probe_expectation_from_runner() -> None:
    config = RunnerConfig(
        run_id=UUID("11111111-2222-4333-8444-555555555555"),
        mode="real",
        fixture_manifest=Path("/private/fixture.json"),
        api_base="http://127.0.0.1:18088",
        novel_id=UUID(NOVEL_ID),
        document_id=UUID(DOCUMENT_ID),
        automatic_case_id="automatic",
        manual_case_id="manual",
        private_work_dir=Path("/private/work"),
        output_dir=Path("/private/output"),
        duration_minutes=30.0,
        listening_record=None,
        resume=False,
    )
    expectation = ProbeExpectation.from_runner(
        config,
        automatic_edition_id=UUID(
            "22222222-3333-4444-8555-666666666666"
        ),
        automatic_edition_fingerprint=_sha("automatic-fingerprint"),
        manual_edition_id=UUID("33333333-4444-4555-8666-777777777777"),
        manual_edition_fingerprint=_sha("manual-fingerprint"),
        listening_output_hashes=(_sha("output-one"), _sha("output-two")),
    )

    assert expectation.target_scope_sha256 == _scope_sha256()
    lifecycle._validate_scope(
        replace(_request(), expectation=expectation),
        NOVEL_ID,
        DOCUMENT_ID,
    )
    with pytest.raises(lifecycle.ControllerLifecycleError) as captured:
        lifecycle._validate_scope(
            replace(_request(), expectation=expectation),
            NOVEL_ID,
            "ffffffff-eeee-4ddd-8ccc-bbbbbbbbbbbb",
        )
    assert captured.value.code == lifecycle.CONTROLLER_LIFECYCLE_REQUEST_HOLD


def test_local_operator_stage_uses_fixed_observers_and_digest_identities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_local_stage(monkeypatch)

    result = lifecycle.run_fixed_local_operator_report_stage(
        REQUEST_PATH,
        NOVEL_ID,
        DOCUMENT_ID,
        VALIDATION_TOKEN,
    )

    assert result.status == "LOCAL_OPERATOR_OBSERVATION_COMMITTED"
    assert calls["forbidden"] == []
    assert calls["builds"] == [
        _sha("controller-build"),
        _sha("controller-build"),
    ]
    assert calls["loaded"] == [STARTED_AT, ENDED_AT]
    assert calls["browser"] == [
        BrowserObservationRequest(
            novel_id=NOVEL_ID,
            document_id=DOCUMENT_ID,
            request_fingerprint_sha256=(
                _request().request_fingerprint_sha256
            ),
            run_fingerprint_sha256=(
                _request().expectation.run_fingerprint_sha256
            ),
            target_scope_sha256=_scope_sha256(),
            validation_token=VALIDATION_TOKEN,
        )
    ]
    assert calls["runtime"] == [
        (NOVEL_ID, DOCUMENT_ID, VALIDATION_TOKEN)
    ]
    assert len(calls["finalized"]) == 1
    path, evidence, kwargs = calls["finalized"][0]
    assert path == REQUEST_PATH
    assert evidence.collected_at == ENDED_AT
    assert kwargs == {
        "controller_build_sha256": _sha("controller-build"),
        "browser_binary_sha256": _sha("browser-binary"),
        "node_binary_sha256": _sha("node-binary"),
        "now": ENDED_AT,
    }


@pytest.mark.parametrize(
    ("field", "expected_code"),
    [
        ("player_visible", CONTROLLER_EVIDENCE_BROWSER_PLAYER_HOLD),
        (
            "paragraph_context_menu_seek_observed",
            CONTROLLER_EVIDENCE_BROWSER_PARAGRAPH_SEEK_HOLD,
        ),
        (
            "cursor_keyboard_seek_observed",
            CONTROLLER_EVIDENCE_BROWSER_CURSOR_SEEK_HOLD,
        ),
        ("latest_wins_observed", CONTROLLER_EVIDENCE_BROWSER_LATEST_WINS_HOLD),
        (
            "play_pause_rate_seek_observed",
            CONTROLLER_EVIDENCE_BROWSER_CONTROLS_HOLD,
        ),
        ("edit_restored", CONTROLLER_EVIDENCE_BROWSER_EDIT_RESTORE_HOLD),
        ("media_http_observed", CONTROLLER_EVIDENCE_BROWSER_MEDIA_HTTP_HOLD),
    ],
)
def test_local_operator_rejects_browser_interaction_before_runtime(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    expected_code: str,
) -> None:
    browser = _browser()
    browser = replace(
        browser,
        interaction_evidence=replace(
            browser.interaction_evidence,
            **{field: False},
        ),
    )
    calls = _install_local_stage(
        monkeypatch,
        browser_observation=browser,
    )

    with pytest.raises(lifecycle.ControllerLifecycleError) as captured:
        lifecycle.run_fixed_local_operator_report_stage(
            REQUEST_PATH,
            NOVEL_ID,
            DOCUMENT_ID,
            VALIDATION_TOKEN,
        )

    assert captured.value.code == expected_code
    assert calls["runtime"] == []
    assert calls["finalized"] == []


def test_local_operator_request_drift_holds_after_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    drifted = replace(
        _local_snapshot(),
        request_identity=(70, 71, 72, 73, 74, 75),
    )
    calls = _install_local_stage(
        monkeypatch,
        second_snapshot=drifted,
    )

    with pytest.raises(lifecycle.ControllerLifecycleError) as captured:
        lifecycle.run_fixed_local_operator_report_stage(
            REQUEST_PATH,
            NOVEL_ID,
            DOCUMENT_ID,
            VALIDATION_TOKEN,
        )

    assert captured.value.code == lifecycle.CONTROLLER_LIFECYCLE_REQUEST_DRIFT
    assert len(calls["browser"]) == 1
    assert len(calls["runtime"]) == 1
    assert calls["loaded"] == [STARTED_AT, ENDED_AT]
    assert calls["finalized"] == []
    assert calls["forbidden"] == []


def test_local_operator_source_drift_holds_after_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_local_stage(monkeypatch, source_drift=True)

    with pytest.raises(lifecycle.ControllerLifecycleError) as captured:
        lifecycle.run_fixed_local_operator_report_stage(
            REQUEST_PATH,
            NOVEL_ID,
            DOCUMENT_ID,
            VALIDATION_TOKEN,
        )

    assert captured.value.code == lifecycle.CONTROLLER_LIFECYCLE_SOURCE_HOLD
    assert len(calls["browser"]) == 1
    assert len(calls["runtime"]) == 1
    assert calls["loaded"] == [STARTED_AT]
    assert calls["finalized"] == []
    assert calls["forbidden"] == []


def test_local_operator_preserves_runtime_observer_error_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_local_stage(monkeypatch)

    def runtime_holds(*args: object) -> object:
        del args
        raise RuntimeObserverError("RUNTIME_OBSERVER_SIDECAR_UNHEALTHY")

    monkeypatch.setattr(lifecycle, "collect_runtime_observations", runtime_holds)

    with pytest.raises(lifecycle.ControllerLifecycleError) as captured:
        lifecycle.run_fixed_local_operator_report_stage(
            REQUEST_PATH,
            NOVEL_ID,
            DOCUMENT_ID,
            VALIDATION_TOKEN,
        )

    assert captured.value.code == "RUNTIME_OBSERVER_SIDECAR_UNHEALTHY"
    assert len(calls["browser"]) == 1
    assert calls["finalized"] == []


def test_local_operator_redacts_unknown_runtime_observer_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_local_stage(monkeypatch)

    def runtime_fails(*args: object) -> object:
        del args
        raise RuntimeError("private runtime detail")

    monkeypatch.setattr(lifecycle, "collect_runtime_observations", runtime_fails)

    with pytest.raises(lifecycle.ControllerLifecycleError) as captured:
        lifecycle.run_fixed_local_operator_report_stage(
            REQUEST_PATH,
            NOVEL_ID,
            DOCUMENT_ID,
            VALIDATION_TOKEN,
        )

    assert captured.value.code == lifecycle.CONTROLLER_LIFECYCLE_RUNTIME_HOLD
    assert len(calls["browser"]) == 1
    assert calls["finalized"] == []


@pytest.mark.parametrize(
    "reason_code",
    [
        "PLAYER_NOT_VISIBLE",
        "STATE_UNAVAILABLE",
        "BOUNDARY_NOT_FOUND",
        "TIMELINE_MISMATCH",
        "RATE_CHANGE_FAILED",
        "SEEK_CURRENT_NULL",
        "SEEK_COMMAND_NOT_APPLIED",
        "SEEK_COMMAND_UNAVAILABLE",
        "SEEK_WRONG_READY_ORDINAL",
        "STATE_CHANGED",
        "GAP_CROSSED",
        "BLOCKED_MISMATCH",
        "PLAYBACK_TIMEOUT",
        "PLAYBACK_TIMEOUT_IDLE",
        "PLAYBACK_TIMEOUT_PREPARING",
        "PLAYBACK_TIMEOUT_BUFFERING",
        "PLAYBACK_TIMEOUT_PLAYING",
        "PLAYBACK_TIMEOUT_PAUSED",
        "PLAYBACK_TIMEOUT_ENDED",
        "PLAYBACK_TIMEOUT_ERROR",
        "PLAYBACK_START_UNAVAILABLE",
    ],
)
def test_local_operator_preserves_allowlisted_pending_gap_reason(
    monkeypatch: pytest.MonkeyPatch,
    reason_code: str,
) -> None:
    browser = replace(
        _browser(),
        interaction_evidence=replace(
            _browser().interaction_evidence,
            pending_gap_status="not_observed",
            pending_gap_stop_before_observed=False,
            pending_gap_reason_code=reason_code,
        ),
    )
    calls = _install_local_stage(
        monkeypatch,
        browser_observation=browser,
    )

    with pytest.raises(lifecycle.ControllerLifecycleError) as captured:
        lifecycle.run_fixed_local_operator_report_stage(
            REQUEST_PATH,
            NOVEL_ID,
            DOCUMENT_ID,
            VALIDATION_TOKEN,
        )

    assert captured.value.code == (
        "CONTROLLER_EVIDENCE_PENDING_GAP_" + reason_code
    )
    assert calls["runtime"] == []
    assert calls["finalized"] == []


@pytest.mark.parametrize("reason_code", ["OBSERVED", "PRIVATE_DETAIL"])
def test_local_operator_redacts_invalid_pending_gap_reason(
    monkeypatch: pytest.MonkeyPatch,
    reason_code: str,
) -> None:
    browser = replace(
        _browser(),
        interaction_evidence=replace(
            _browser().interaction_evidence,
            pending_gap_status="not_observed",
            pending_gap_stop_before_observed=False,
            pending_gap_reason_code=reason_code,
        ),
    )
    calls = _install_local_stage(
        monkeypatch,
        browser_observation=browser,
    )

    with pytest.raises(lifecycle.ControllerLifecycleError) as captured:
        lifecycle.run_fixed_local_operator_report_stage(
            REQUEST_PATH,
            NOVEL_ID,
            DOCUMENT_ID,
            VALIDATION_TOKEN,
        )

    assert captured.value.code == "CONTROLLER_EVIDENCE_PENDING_GAP_HOLD"
    assert calls["runtime"] == []
    assert calls["finalized"] == []


@pytest.mark.parametrize(
    ("status", "stop_before", "reason_code"),
    [
        ("not_observed", True, "PLAYBACK_TIMEOUT"),
        ("private_status", False, "PLAYBACK_TIMEOUT"),
        ("observed", False, "PLAYBACK_TIMEOUT"),
        ("observed", True, "PLAYBACK_TIMEOUT"),
        ("not_observed", False, ["PLAYBACK_TIMEOUT"]),
    ],
)
def test_local_operator_redacts_inconsistent_pending_gap_evidence(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    stop_before: bool,
    reason_code: object,
) -> None:
    browser = replace(
        _browser(),
        interaction_evidence=replace(
            _browser().interaction_evidence,
            pending_gap_status=status,
            pending_gap_stop_before_observed=stop_before,
            pending_gap_reason_code=reason_code,  # type: ignore[arg-type]
        ),
    )
    calls = _install_local_stage(
        monkeypatch,
        browser_observation=browser,
    )

    with pytest.raises(lifecycle.ControllerLifecycleError) as captured:
        lifecycle.run_fixed_local_operator_report_stage(
            REQUEST_PATH,
            NOVEL_ID,
            DOCUMENT_ID,
            VALIDATION_TOKEN,
        )

    assert captured.value.code == "CONTROLLER_EVIDENCE_PENDING_GAP_HOLD"
    assert calls["runtime"] == []
    assert calls["finalized"] == []


def test_local_operator_preserves_evidence_assembly_error_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_local_stage(monkeypatch)

    def assembly_holds(*args: object) -> object:
        del args
        raise ControllerEvidenceAssemblyError(
            "CONTROLLER_EVIDENCE_PENDING_GAP_HOLD"
        )

    monkeypatch.setattr(
        lifecycle,
        "assemble_fixed_controller_evidence",
        assembly_holds,
    )

    with pytest.raises(lifecycle.ControllerLifecycleError) as captured:
        lifecycle.run_fixed_local_operator_report_stage(
            REQUEST_PATH,
            NOVEL_ID,
            DOCUMENT_ID,
            VALIDATION_TOKEN,
        )

    assert captured.value.code == "CONTROLLER_EVIDENCE_PENDING_GAP_HOLD"
    assert calls["finalized"] == []


def test_local_operator_preserves_collector_error_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_local_stage(monkeypatch)

    class _Collector:
        def finalize_local_operator(self, *args: object, **kwargs: object) -> object:
            del args, kwargs
            raise CollectorError("COLLECTOR_RUNTIME_GATE_FAILED")

    monkeypatch.setattr(lifecycle, "FixedChapterE2ECollector", _Collector)

    with pytest.raises(lifecycle.ControllerLifecycleError) as captured:
        lifecycle.run_fixed_local_operator_report_stage(
            REQUEST_PATH,
            NOVEL_ID,
            DOCUMENT_ID,
            VALIDATION_TOKEN,
        )

    assert captured.value.code == "COLLECTOR_RUNTIME_GATE_FAILED"
    assert calls["finalized"] == []


def test_local_operator_redacts_collector_publication_error_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_local_stage(monkeypatch)

    class _Collector:
        def finalize_local_operator(self, *args: object, **kwargs: object) -> object:
            del args, kwargs
            raise CollectorError("COLLECTOR_WRITE_FAILED")

    monkeypatch.setattr(lifecycle, "FixedChapterE2ECollector", _Collector)

    with pytest.raises(lifecycle.ControllerLifecycleError) as captured:
        lifecycle.run_fixed_local_operator_report_stage(
            REQUEST_PATH,
            NOVEL_ID,
            DOCUMENT_ID,
            VALIDATION_TOKEN,
        )

    assert captured.value.code == lifecycle.CONTROLLER_LIFECYCLE_FINALIZE_HOLD
    assert calls["finalized"] == []


def test_lifecycle_derives_all_ports_and_finalizes_exact_artifact() -> None:
    dependencies, calls = _dependencies()

    result = _run(dependencies)

    assert result.status == "FORMAL_CONTROLLER_REPORT_COMMITTED"
    assert calls.authority_checks == [STARTED_AT, COMMITTED_AT]
    assert calls.controller_build_checks == [
        _sha("controller-build"),
        _sha("controller-build"),
        _sha("controller-build"),
    ]
    assert calls.loaded == [STARTED_AT, ENDED_AT, COMMITTED_AT]
    assert len(calls.browser_requests) == 1
    browser_request = calls.browser_requests[0]
    assert browser_request == BrowserObservationRequest(
        novel_id=NOVEL_ID,
        document_id=DOCUMENT_ID,
        request_fingerprint_sha256=_request().request_fingerprint_sha256,
        run_fingerprint_sha256=_request().expectation.run_fingerprint_sha256,
        target_scope_sha256=_scope_sha256(),
        validation_token=VALIDATION_TOKEN,
    )
    assert calls.runtime_requests == [
        (NOVEL_ID, DOCUMENT_ID, VALIDATION_TOKEN)
    ]
    observation = calls.binding_observations[0]
    assert observation.preflight_payload == PREFLIGHT_BYTES
    assert observation.preflight_signature == PREFLIGHT_SIGNATURE
    assert observation.probe_request_bytes == REQUEST_BYTES
    assert observation.captures == _browser().captures
    assert observation.metric_samples == _runtime().metric_samples
    assert calls.signed[0].payload == calls.finalized[0][2]
    assert calls.finalized[0][3] == b"fixed-report-signature"
    assert calls.finalized[0][4] == COMMITTED_AT


def test_public_entry_has_no_injectable_observation_or_signing_ports() -> None:
    expected_parameters = (
        "probe_request_path",
        "novel_id",
        "document_id",
        "validation_token",
    )
    assert tuple(
        signature(lifecycle.run_fixed_local_operator_report_stage).parameters
    ) == expected_parameters
    assert tuple(
        signature(
            lifecycle.run_experimental_signed_controller_report_stage
        ).parameters
    ) == expected_parameters
    assert tuple(
        signature(lifecycle.run_fixed_controller_report_stage).parameters
    ) == expected_parameters
    assert "run_fixed_local_operator_report_stage" in lifecycle.__all__
    assert "run_experimental_signed_controller_report_stage" in lifecycle.__all__
    assert "_run_fixed_controller_report_stage" not in lifecycle.__all__
    assert "_LifecycleDependencies" not in lifecycle.__all__


def test_private_test_seam_requires_exact_dependency_type() -> None:
    with pytest.raises(lifecycle.ControllerLifecycleError) as captured:
        lifecycle._run_fixed_controller_report_stage(
            REQUEST_PATH,
            NOVEL_ID,
            DOCUMENT_ID,
            VALIDATION_TOKEN,
            dependencies=object(),
        )
    assert captured.value.code == lifecycle.CONTROLLER_LIFECYCLE_INPUT_INVALID


def test_pending_gap_failure_never_reaches_signing() -> None:
    browser = _browser()
    browser = replace(
        browser,
        interaction_evidence=replace(
            browser.interaction_evidence,
            pending_gap_status="not_observed",
            pending_gap_stop_before_observed=False,
        ),
    )
    dependencies, calls = _dependencies(browser=browser)

    with pytest.raises(lifecycle.ControllerLifecycleError) as captured:
        _run(dependencies)
    assert captured.value.code == CONTROLLER_EVIDENCE_PENDING_GAP_HOLD
    assert calls.signed == []
    assert calls.finalized == []


def test_layout_failure_never_reaches_signing() -> None:
    browser = _browser()
    layouts = list(browser.layout_observations)
    layouts[0] = replace(layouts[0], nonzero_overlap_pair_count=1)
    dependencies, calls = _dependencies(
        browser=replace(browser, layout_observations=tuple(layouts))
    )

    with pytest.raises(lifecycle.ControllerLifecycleError) as captured:
        _run(dependencies)
    assert captured.value.code == CONTROLLER_EVIDENCE_LAYOUT_HOLD
    assert calls.signed == []
    assert calls.finalized == []


def test_runtime_failure_never_reaches_signing() -> None:
    runtime = _runtime()
    samples = list(runtime.metric_samples)
    samples[5] = replace(samples[5], sidecar_restart_count=1)
    dependencies, calls = _dependencies(
        runtime=replace(runtime, metric_samples=tuple(samples))
    )

    with pytest.raises(lifecycle.ControllerLifecycleError) as captured:
        _run(dependencies)
    assert captured.value.code == CONTROLLER_EVIDENCE_RUNTIME_HOLD
    assert calls.signed == []
    assert calls.finalized == []


def test_second_preflight_identity_drift_is_detected_before_binding() -> None:
    first = _snapshot()
    drift_identity = (90, 91, 92, 93, 94, 95)
    drifted = replace(
        first,
        preflight_signature_identity=drift_identity,
        verified_preflight=replace(
            first.verified_preflight,
            signature_identity=drift_identity,
        ),
    )
    dependencies, calls = _dependencies(second_snapshot=drifted)

    with pytest.raises(lifecycle.ControllerLifecycleError) as captured:
        _run(dependencies)
    assert captured.value.code == lifecycle.CONTROLLER_LIFECYCLE_REQUEST_DRIFT
    assert calls.binding_observations == []
    assert calls.signed == []


def test_snapshot_identity_must_match_verified_preflight_identity() -> None:
    mismatched = replace(
        _snapshot(),
        preflight_payload_identity=(80, 81, 82, 83, 84, 85),
    )
    dependencies, calls = _dependencies(second_snapshot=mismatched)

    with pytest.raises(lifecycle.ControllerLifecycleError) as captured:
        _run(dependencies)
    assert captured.value.code == lifecycle.CONTROLLER_LIFECYCLE_REQUEST_HOLD
    assert calls.binding_observations == []
    assert calls.signed == []


def test_unbound_host_artifact_is_rejected_before_signing() -> None:
    dependencies, calls = _dependencies(artifact_drift=True)

    with pytest.raises(lifecycle.ControllerLifecycleError) as captured:
        _run(dependencies)
    assert captured.value.code == lifecycle.CONTROLLER_LIFECYCLE_BINDING_HOLD
    assert calls.signed == []
    assert calls.finalized == []


def test_artifact_must_bind_the_pre_observation_controller_build() -> None:
    dependencies, calls = _dependencies(artifact_build_drift=True)

    with pytest.raises(lifecycle.ControllerLifecycleError) as captured:
        _run(dependencies)

    assert captured.value.code == lifecycle.CONTROLLER_LIFECYCLE_BINDING_HOLD
    assert calls.signed == []
    assert calls.finalized == []


def test_controller_source_drift_after_observation_never_reaches_signing() -> None:
    dependencies, calls = _dependencies(pre_sign_source_drift=True)

    with pytest.raises(lifecycle.ControllerLifecycleError) as captured:
        _run(dependencies)

    assert captured.value.code == lifecycle.CONTROLLER_LIFECYCLE_SOURCE_HOLD
    assert len(calls.controller_build_checks) == 2
    assert calls.signed == []
    assert calls.finalized == []


def test_controller_source_drift_after_signing_never_finalizes() -> None:
    dependencies, calls = _dependencies(post_sign_source_drift=True)

    with pytest.raises(lifecycle.ControllerLifecycleError) as captured:
        _run(dependencies)

    assert captured.value.code == lifecycle.CONTROLLER_LIFECYCLE_SOURCE_HOLD
    assert len(calls.controller_build_checks) == 3
    assert len(calls.signed) == 1
    assert calls.finalized == []


def test_observed_edge_identity_drift_is_rejected_before_signing() -> None:
    browser = replace(
        _browser(),
        edge_executable_sha256=_sha("different-observed-browser"),
    )
    dependencies, calls = _dependencies(browser=browser)

    with pytest.raises(lifecycle.ControllerLifecycleError) as captured:
        _run(dependencies)

    assert captured.value.code == lifecycle.CONTROLLER_LIFECYCLE_BINDING_HOLD
    assert calls.signed == []
    assert calls.finalized == []


def test_post_sign_request_identity_drift_never_finalizes() -> None:
    drifted = replace(
        _snapshot(),
        request_identity=(70, 71, 72, 73, 74, 75),
    )
    dependencies, calls = _dependencies(third_snapshot=drifted)

    with pytest.raises(lifecycle.ControllerLifecycleError) as captured:
        _run(dependencies)

    assert captured.value.code == lifecycle.CONTROLLER_LIFECYCLE_REQUEST_DRIFT
    assert len(calls.signed) == 1
    assert calls.finalized == []


def test_post_sign_authority_drift_never_finalizes() -> None:
    dependencies, calls = _dependencies(post_sign_authority_hold=True)

    with pytest.raises(lifecycle.ControllerLifecycleError) as captured:
        _run(dependencies)

    assert captured.value.code == lifecycle.CONTROLLER_LIFECYCLE_AUTHORITY_HOLD
    assert len(calls.signed) == 1
    assert calls.loaded == [STARTED_AT, ENDED_AT]
    assert calls.finalized == []


def test_production_empty_root_holds_before_browser_and_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = {"browser": 0, "runtime": 0}

    def browser_should_not_run(request: BrowserObservationRequest) -> object:
        del request
        observed["browser"] += 1
        raise AssertionError

    def runtime_should_not_run(*args: object) -> object:
        del args
        observed["runtime"] += 1
        raise AssertionError

    monkeypatch.setattr(
        lifecycle,
        "_run_fixed_browser_observer",
        browser_should_not_run,
    )
    monkeypatch.setattr(
        lifecycle,
        "collect_runtime_observations",
        runtime_should_not_run,
    )

    with pytest.raises(lifecycle.ControllerLifecycleError) as captured:
        lifecycle.run_fixed_controller_report_stage(
            REQUEST_PATH,
            NOVEL_ID,
            DOCUMENT_ID,
            VALIDATION_TOKEN,
        )
    assert captured.value.code == lifecycle.CONTROLLER_LIFECYCLE_AUTHORITY_HOLD
    assert observed == {"browser": 0, "runtime": 0}


def test_missing_os_isolated_production_signer_holds_at_signing_port() -> None:
    dependencies, calls = _dependencies(production_signer_port=True)

    with pytest.raises(lifecycle.ControllerLifecycleError) as captured:
        _run(dependencies)
    assert captured.value.code == lifecycle.CONTROLLER_LIFECYCLE_SIGNING_PORT_HOLD
    assert len(calls.binding_observations) == 1
    assert calls.finalized == []
