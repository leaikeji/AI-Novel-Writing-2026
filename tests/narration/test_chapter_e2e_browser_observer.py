from __future__ import annotations

import base64
import binascii
import hashlib
import json
import struct
import zlib

import pytest
import scripts.tts.chapter_e2e_browser_observer as observer_module

from scripts.tts.chapter_e2e_browser_observer import (
    BrowserObserverError,
    BrowserObservationRequest,
    BrowserObserverExpectation,
    _parse_browser_observer_report,
)
from scripts.tts.chapter_e2e_controller_host import _ControllerHost
from scripts.tts.chapter_e2e_controller_trust import (
    CONTROLLER_ID,
    FIXED_REQUIRED_CAPTURES,
)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _summary(kind: str) -> dict[str, object]:
    rows = [
        {
            "kind": kind,
            "location_sha256": _sha(f"{kind}-location".encode()),
            "message_sha256": _sha(f"{kind}-message".encode()),
        }
    ]
    return {
        "count": 1,
        "dropped_count": 0,
        "rows": rows,
        "summary_sha256": _sha(_canonical(rows)),
    }


def _png(width: int, height: int, marker: int) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    rows = (b"\x00" + b"\x00" * width) * height
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"tEXt", f"capture={marker}".encode())
        + chunk(b"IDAT", zlib.compress(rows, level=9))
        + chunk(b"IEND", b"")
    )


def _expectation() -> BrowserObserverExpectation:
    return BrowserObserverExpectation(
        novel_id="11111111-1111-4111-8111-111111111111",
        document_id="22222222-2222-4222-8222-222222222222",
        request_fingerprint_sha256="a" * 64,
        run_fingerprint_sha256="b" * 64,
        target_scope_sha256="c" * 64,
        node_executable_sha256="d" * 64,
        edge_executable_sha256="e" * 64,
    )


def _report() -> bytes:
    expected = _expectation()
    captures = []
    for index, (width, height, mode) in enumerate(FIXED_REQUIRED_CAPTURES):
        png = _png(width, height, index)
        collapsed = mode == "collapsed"
        captures.append(
            {
                "assistant": {
                    "collapsed_attribute": str(collapsed).lower(),
                    "mode_attribute": "inline" if collapsed else "overlay",
                    "observed_mode": mode,
                    "toggle_aria_expanded": str(not collapsed).lower(),
                },
                "calibration_attempts": [
                    {
                        "observed_inner_height": height,
                        "observed_inner_width": width,
                        "requested_outer_height": height + 10,
                        "requested_outer_width": width + 20,
                    }
                ],
                "console_summary": _summary(f"console-{index}"),
                "device_pixel_ratio": 1,
                "layout_observation": {
                    "horizontal_overflow_px": index * 2,
                    "nonzero_overlap_pair_count": index,
                    "tracked_visible_region_count": 3 + index,
                },
                "observed_inner_height": height,
                "observed_inner_width": width,
                "page_error_summary": _summary(f"page-{index}"),
                "screenshot_bytes": len(png),
                "screenshot_pixel_height": height,
                "screenshot_pixel_width": width,
                "screenshot_png_base64": base64.b64encode(png).decode(),
                "screenshot_sha256": _sha(png),
                "target_css_height": height,
                "target_css_width": width,
            }
        )
    query = _canonical(
        {
            "document_id": expected.document_id,
            "novel_id": expected.novel_id,
            "novel_workbench": "1",
        }
    )
    unsigned = {
        "browser_identity": {
            "codesign": {
                "cdhash": "0123456789abcdef",
                "deep_verified": True,
                "gatekeeper_accepted": True,
                "gatekeeper_override_security_disabled": False,
                "gatekeeper_result_sha256": "1" * 64,
                "gatekeeper_source_notarized_developer_id": True,
                "identifier": "com.microsoft.edgemac",
                "strict_result_sha256": "2" * 64,
                "strict_verified": True,
                "team_identifier": "UBF8T346G9",
            },
            "edge_executable_path": (
                "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
            ),
            "edge_executable_sha256": expected.edge_executable_sha256,
            "js_version": "14.2.231",
            "node_executable_sha256": expected.node_executable_sha256,
            "node_version": "24.19.0",
            "playwright_core_version": "1.62.1",
            "product": "Edg/140.0",
            "protocol_version": "1.3",
            "user_agent_sha256": "3" * 64,
        },
        "captures": captures,
        "console_summary": _summary("console"),
        "controller_id": CONTROLLER_ID,
        "interaction_evidence": {
            "controls": {
                "elapsed_ms": 30,
                "pause_observed": True,
                "play_observed": True,
                "rate_change_observed": True,
                "seek_observed": True,
                "status": "observed",
            },
            "cursor_keyboard_seek": {
                "command_dispatched": True,
                "elapsed_ms": 12,
                "status": "observed",
                "target_changed": True,
            },
            "edit_without_tts_write": {
                "after_sha256": "4" * 64,
                "before_sha256": "4" * 64,
                "editor_restored": True,
                "elapsed_ms": 40,
                "status": "observed",
                "tts_write_request_count": 0,
            },
            "editor": {
                "codemirror_observed": True,
                "kind": "codemirror6",
                "textarea_fallback_observed": False,
            },
            "latest_wins": {
                "elapsed_ms": 20,
                "final_target_won": True,
                "first_dispatch_observed": True,
                "second_dispatch_observed": True,
                "status": "observed",
            },
            "media_http": {
                "elapsed_ms": 50,
                "etag_observed": True,
                "if_none_match_304": True,
                "if_range_206": True,
                "range_206": True,
                "request_count": 5,
                "status": "observed",
                "unsatisfied_range_416": True,
            },
            "paragraph_context_menu_seek": {
                "command_dispatched": True,
                "elapsed_ms": 12,
                "status": "observed",
                "target_changed": True,
            },
            "pending_gap": {
                "reason_code": "BOUNDARY_NOT_FOUND",
                "status": "not_observed",
                "stop_before_gap_observed": False,
            },
            "player": {"visible": True},
        },
        "network_summary": _summary("network"),
        "page_error_summary": _summary("page-error"),
        "request_fingerprint_sha256": expected.request_fingerprint_sha256,
        "route_evidence": {
            "origin": "http://127.0.0.1:18088",
            "path_fingerprint_sha256": _sha(b"/chat"),
            "query_fingerprint_sha256": _sha(query),
            "route_kind": "chat_root",
        },
        "run_fingerprint_sha256": expected.run_fingerprint_sha256,
        "schema_version": "moss-tts-t4k-browser-observer-report/1.2",
        "target_scope_sha256": expected.target_scope_sha256,
    }
    report = {**unsigned, "report_sha256": _sha(_canonical(unsigned))}
    return _canonical(report) + b"\n"


def test_exact_node_report_maps_to_four_host_capture_observations() -> None:
    verified = _parse_browser_observer_report(_report(), _expectation())
    assert len(verified.captures) == 4
    assert verified.network_request_count == 1
    assert verified.console_entry_count == 1
    assert verified.console_error_count == 0
    assert verified.capture_console_error_counts == (0, 0, 0, 0)
    assert verified.page_error_count == 1
    assert verified.interaction_evidence.player_visible is True
    assert verified.interaction_evidence.media_http_observed is True
    assert verified.interaction_evidence.pending_gap_status == "not_observed"
    assert verified.interaction_evidence.pending_gap_reason_code == (
        "BOUNDARY_NOT_FOUND"
    )
    assert [
        (
            row.target_css_width,
            row.target_css_height,
            row.assistant_mode,
            row.tracked_visible_region_count,
            row.nonzero_overlap_pair_count,
            row.horizontal_overflow_px,
        )
        for row in verified.layout_observations
    ] == [
        (width, height, mode, 3 + index, index, index * 2)
        for index, (width, height, mode) in enumerate(FIXED_REQUIRED_CAPTURES)
    ]
    assert not hasattr(verified, "passed")
    assert not hasattr(verified, "layout_passed")
    payloads = _ControllerHost._capture_payloads(verified.captures)
    assert [
        (row["target_css_width"], row["target_css_height"], row["assistant_mode_observed"])
        for row in payloads
    ] == list(FIXED_REQUIRED_CAPTURES)


def test_console_logs_are_allowed_but_error_levels_are_counted() -> None:
    value = json.loads(_report())
    value["console_summary"] = _summary("error")
    value["captures"][2]["console_summary"] = _summary("assert")
    unsigned = dict(value)
    unsigned.pop("report_sha256", None)
    value["report_sha256"] = _sha(_canonical(unsigned))

    verified = _parse_browser_observer_report(
        _canonical(value) + b"\n", _expectation()
    )

    assert verified.console_entry_count == 1
    assert verified.console_error_count == 1
    assert verified.capture_console_error_counts == (0, 0, 1, 0)


def test_exact_edge_binary_and_deep_signature_do_not_depend_on_host_gatekeeper_mode() -> None:
    value = json.loads(_report())
    value["browser_identity"]["codesign"].update(
        {
            "strict_verified": False,
            "gatekeeper_override_security_disabled": True,
        }
    )
    unsigned = dict(value)
    unsigned.pop("report_sha256", None)
    value["report_sha256"] = _sha(_canonical(unsigned))

    verified = _parse_browser_observer_report(
        _canonical(value) + b"\n", _expectation()
    )

    assert verified.report_sha256 == value["report_sha256"]


def test_dropped_console_rows_fail_closed_as_unknown_errors() -> None:
    value = json.loads(_report())
    value["console_summary"]["count"] = 2
    value["console_summary"]["dropped_count"] = 1
    unsigned = dict(value)
    unsigned.pop("report_sha256", None)
    value["report_sha256"] = _sha(_canonical(unsigned))

    verified = _parse_browser_observer_report(
        _canonical(value) + b"\n", _expectation()
    )

    assert verified.console_entry_count == 2
    assert verified.console_error_count == 1


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update({"request_fingerprint_sha256": "f" * 64}),
        lambda value: value["browser_identity"].update(
            {"node_executable_sha256": "f" * 64}
        ),
        lambda value: value["browser_identity"]["codesign"].update(
            {"deep_verified": False}
        ),
        lambda value: value["browser_identity"]["codesign"].update(
            {"gatekeeper_accepted": False}
        ),
        lambda value: value["browser_identity"]["codesign"].update(
            {"gatekeeper_source_notarized_developer_id": False}
        ),
        lambda value: value["browser_identity"]["codesign"].update(
            {"team_identifier": "UNTRUSTED"}
        ),
        lambda value: value["browser_identity"]["codesign"].update(
            {"strict_verified": "false"}
        ),
        lambda value: value["browser_identity"]["codesign"].update(
            {"gatekeeper_override_security_disabled": 1}
        ),
        lambda value: value["captures"].pop(),
    ],
)
def test_report_fails_closed_on_scope_identity_or_capture_tampering(mutate) -> None:
    value = json.loads(_report())
    mutate(value)
    unsigned = dict(value)
    unsigned.pop("report_sha256", None)
    value["report_sha256"] = _sha(_canonical(unsigned))
    with pytest.raises(BrowserObserverError) as captured:
        _parse_browser_observer_report(_canonical(value) + b"\n", _expectation())
    assert captured.value.code == "BROWSER_OBSERVER_REPORT_INVALID"


def test_report_rejects_noncanonical_or_stale_self_hash() -> None:
    with pytest.raises(BrowserObserverError):
        _parse_browser_observer_report(_report().replace(b'"schema_version"', b' "schema_version"', 1), _expectation())
    value = json.loads(_report())
    value["captures"][0]["screenshot_bytes"] += 1
    with pytest.raises(BrowserObserverError):
        _parse_browser_observer_report(_canonical(value) + b"\n", _expectation())


@pytest.mark.parametrize(
    "mutate",
    [
        lambda layout: layout.pop("tracked_visible_region_count"),
        lambda layout: layout.update({"unexpected": 0}),
        lambda layout: layout.update({"tracked_visible_region_count": -1}),
        lambda layout: layout.update({"nonzero_overlap_pair_count": 1.5}),
        lambda layout: layout.update({"horizontal_overflow_px": True}),
    ],
)
def test_layout_observation_is_exact_and_nonnegative_integer_only(mutate) -> None:
    value = json.loads(_report())
    mutate(value["captures"][0]["layout_observation"])
    unsigned = dict(value)
    unsigned.pop("report_sha256", None)
    value["report_sha256"] = _sha(_canonical(unsigned))

    with pytest.raises(BrowserObserverError) as captured:
        _parse_browser_observer_report(
            _canonical(value) + b"\n", _expectation()
        )
    assert captured.value.code == "BROWSER_OBSERVER_REPORT_INVALID"


def test_fixed_runner_verifies_runtime_and_uses_only_fixed_command(monkeypatch) -> None:
    expected = _expectation()
    recorded = {}
    monkeypatch.setattr(
        observer_module,
        "verify_controller_node_environment",
        lambda: {
            "runtime": {"node_executable_sha256": expected.node_executable_sha256},
            "dependency": {"package_version": "1.62.1"},
        },
    )
    monkeypatch.setattr(
        observer_module,
        "fixed_node_executable",
        lambda: observer_module.Path("/private/controller/bin/node"),
    )
    monkeypatch.setattr(
        observer_module,
        "_sha256_fixed_executable",
        lambda _path: expected.edge_executable_sha256,
    )

    def run(command, **kwargs):
        recorded.update({"command": command, **kwargs})
        return observer_module.subprocess.CompletedProcess(
            command, 0, stdout=_report(), stderr=b""
        )

    monkeypatch.setattr(observer_module.subprocess, "run", run)
    result = observer_module._run_fixed_browser_observer(
        BrowserObservationRequest(
            novel_id=expected.novel_id,
            document_id=expected.document_id,
            request_fingerprint_sha256=expected.request_fingerprint_sha256,
            run_fingerprint_sha256=expected.run_fingerprint_sha256,
            target_scope_sha256=expected.target_scope_sha256,
            validation_token="T" * 43,
        )
    )
    assert len(result.captures) == 4
    assert recorded["command"] == [
        "/private/controller/bin/node",
        str(observer_module.OBSERVER_ENTRYPOINT),
    ]
    assert recorded["env"] == {
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
    }
    assert recorded["stderr"] is observer_module.subprocess.PIPE
    assert b"novel_id" in recorded["input"]
    assert b"T" * 43 not in recorded["input"]
    assert "T" * 43 not in repr(recorded["command"])
    assert "T" * 43 not in repr(recorded["env"])
    assert len(recorded["pass_fds"]) == 1
    assert callable(recorded["preexec_fn"])


def test_fixed_runner_redacts_runtime_failure(monkeypatch) -> None:
    def fail():
        raise observer_module.ControllerNodeRuntimeError("private-detail")

    monkeypatch.setattr(observer_module, "verify_controller_node_environment", fail)
    request = BrowserObservationRequest(
        novel_id=_expectation().novel_id,
        document_id=_expectation().document_id,
        request_fingerprint_sha256="a" * 64,
        run_fingerprint_sha256="b" * 64,
        target_scope_sha256="c" * 64,
        validation_token="T" * 43,
    )
    with pytest.raises(BrowserObserverError) as captured:
        observer_module._run_fixed_browser_observer(request)
    assert captured.value.code == "BROWSER_OBSERVER_RUNTIME_HOLD"
